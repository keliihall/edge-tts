import json
import os
import sqlite3
import threading


class StateRepository:
    """SQLite-backed storage for user preferences, history, and jobs."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS history (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    voice TEXT NOT NULL,
                    speech_rate TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS jobs_kind_created
                    ON jobs(kind, created_at DESC);

                CREATE TABLE IF NOT EXISTS job_items (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    item_index INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    text_content TEXT NOT NULL,
                    audio_path TEXT,
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS job_items_job_index
                    ON job_items(job_id, item_index);

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_login_at REAL
                );
                """
            )

    def save_preferences(self, preferences):
        with self._lock, self._connect() as connection:
            for key, value in preferences.items():
                connection.execute(
                    """
                    INSERT INTO preferences(key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, json.dumps(value, ensure_ascii=False)),
                )

    def load_preferences(self):
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM preferences").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def replace_history(self, history_items):
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM history")
            connection.executemany(
                "INSERT INTO history(id, payload, created_at) VALUES (?, ?, ?)",
                [
                    (
                        item["id"],
                        json.dumps(item, ensure_ascii=False),
                        item.get("created_at", 0),
                    )
                    for item in history_items
                ],
            )

    def load_history(self, limit=50):
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def save_job(self, kind, job):
        job_payload = {
            key: value
            for key, value in job.items()
            if key != "items"
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs(
                    id, kind, status, voice, speech_rate,
                    created_at, updated_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind = excluded.kind,
                    status = excluded.status,
                    voice = excluded.voice,
                    speech_rate = excluded.speech_rate,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (
                    job["id"],
                    kind,
                    job["status"],
                    job["voice"],
                    job["speech_rate"],
                    job["created_at"],
                    job["updated_at"],
                    json.dumps(job_payload, ensure_ascii=False),
                ),
            )
            connection.execute("DELETE FROM job_items WHERE job_id = ?", (job["id"],))
            connection.executemany(
                """
                INSERT INTO job_items(
                    id, job_id, item_index, status, text_content, audio_path, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["id"],
                        job["id"],
                        item.get("index", position + 1),
                        item["status"],
                        item.get("text", ""),
                        item.get("audio_path"),
                        json.dumps(
                            {
                                key: value
                                for key, value in item.items()
                                if key not in ("text", "audio_path")
                            },
                            ensure_ascii=False,
                        ),
                    )
                    for position, item in enumerate(job.get("items", []))
                ],
            )

    def load_jobs(self, kind):
        with self._lock, self._connect() as connection:
            job_rows = connection.execute(
                "SELECT payload FROM jobs WHERE kind = ? ORDER BY created_at DESC",
                (kind,),
            ).fetchall()
            jobs = []
            for job_row in job_rows:
                job = json.loads(job_row["payload"])
                item_rows = connection.execute(
                    """
                    SELECT text_content, audio_path, payload
                    FROM job_items WHERE job_id = ?
                    ORDER BY item_index
                    """,
                    (job["id"],),
                ).fetchall()
                job["items"] = []
                for item_row in item_rows:
                    item = json.loads(item_row["payload"])
                    item["text"] = item_row["text_content"]
                    item["audio_path"] = item_row["audio_path"]
                    job["items"].append(item)
                jobs.append(job)
        return jobs

    def delete_job(self, job_id):
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def cleanup_jobs(self, cutoff):
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id FROM jobs
                WHERE created_at < ? AND status NOT IN ('queued', 'processing')
                """,
                (cutoff,),
            ).fetchall()
            job_ids = [row["id"] for row in rows]
            connection.executemany(
                "DELETE FROM jobs WHERE id = ?",
                [(job_id,) for job_id in job_ids],
            )
        return job_ids

    def table_counts(self):
        with self._lock, self._connect() as connection:
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("preferences", "history", "jobs", "job_items", "users")
            }

    def user_count(self):
        with self._lock, self._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create_user(self, username, password_hash, role, now):
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users(
                    username, password_hash, role, active, created_at, updated_at
                ) VALUES (?, ?, ?, 1, ?, ?)
                """,
                (username, password_hash, role, now, now),
            )
            user_id = cursor.lastrowid
        return self.get_user(user_id)

    def get_user(self, user_id):
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, username, password_hash, role, active,
                       created_at, updated_at, last_login_at
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_username(self, username):
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, username, password_hash, role, active,
                       created_at, updated_at, last_login_at
                FROM users WHERE username = ?
                """,
                (username,),
            ).fetchone()
        return dict(row) if row else None

    def list_users(self):
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, username, role, active, created_at, updated_at, last_login_at
                FROM users ORDER BY created_at, id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def update_user(self, user_id, *, role=None, active=None, password_hash=None, now=None):
        assignments = []
        values = []
        if role is not None:
            assignments.append("role = ?")
            values.append(role)
        if active is not None:
            assignments.append("active = ?")
            values.append(1 if active else 0)
        if password_hash is not None:
            assignments.append("password_hash = ?")
            values.append(password_hash)
        if now is not None:
            assignments.append("updated_at = ?")
            values.append(now)
        if not assignments:
            return self.get_user(user_id)
        values.append(user_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE users SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
        return self.get_user(user_id)

    def mark_login(self, user_id, now):
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                (now, now, user_id),
            )
