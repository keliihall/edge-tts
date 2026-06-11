from flask import (
    Flask,
    g,
    has_request_context,
    jsonify,
    render_template,
    request,
    send_file,
)
from concurrent.futures import ThreadPoolExecutor
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime
import time
import socket
from urllib.parse import urlparse
from auth import (
    LOGIN_FAILURES,
    LOGIN_FAILURES_LOCK,
    LOGIN_FAILURE_LIMIT,
    register_auth_routes,
)
from storage import StateRepository
from version import APP_NAME, APP_VERSION

app = Flask(__name__)

MAX_TEXT_LENGTH = 200000
MAX_CHUNK_LENGTH = 5000
PREVIEW_TEXT_LENGTH = 300
MAX_BATCH_FILES = 20
MAX_BATCH_TEXT_LENGTH = 20000
MAX_RETRIES = 3
CONNECT_TIMEOUT = 30
RECEIVE_TIMEOUT = 300
TEMP_DIR_NAME = "edge-tts-web"
SINGLE_RESULT_TTL_SECONDS = 6 * 60 * 60
CLEANUP_INTERVAL_SECONDS = 60
NETWORK_DIAGNOSTICS_TTL_SECONDS = 15
NETWORK_CONNECT_TIMEOUT_SECONDS = 3
MAX_WORKERS = 1
DEFAULT_SPEECH_RATE = "1.0"
DEFAULT_VOLUME = "1.0"
DEFAULT_PITCH = "0"
SPEECH_RATE_OPTIONS = {
    "0.75": "-25%",
    "0.9": "-10%",
    "1.0": "+0%",
    "1.1": "+10%",
    "1.25": "+25%",
    "1.5": "+50%",
    "2.0": "+100%",
}
VOLUME_OPTIONS = {
    "0.5": "-50%",
    "0.75": "-25%",
    "1.0": "+0%",
    "1.25": "+25%",
    "1.5": "+50%",
}
PITCH_OPTIONS = {
    "-20": "-20Hz",
    "-10": "-10Hz",
    "0": "+0Hz",
    "10": "+10Hz",
    "20": "+20Hz",
}
BATCH_JOB_TTL_SECONDS = 30 * 24 * 60 * 60
BATCH_JOBS = {}
BATCH_LOCK = threading.RLock()
TEXT_JOB_TTL_SECONDS = 30 * 24 * 60 * 60
TEXT_JOBS = {}
TEXT_JOB_LOCK = threading.RLock()
HISTORY_LIMIT = 50
HISTORY_ITEMS = []
HISTORY_LOCK = threading.Lock()
USER_PREFERENCES = {
    "favorite_voices": [],
    "recent_voices": [],
    "config_favorites": {},
    "auto_download": {},
}
PREFERENCES_LOCK = threading.Lock()
SINGLE_RESULTS = {}
SINGLE_RESULTS_LOCK = threading.Lock()
CLEANUP_LOCK = threading.Lock()
LAST_CLEANUP_AT = 0
SETTINGS_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
REPOSITORY_LOCK = threading.Lock()
REPOSITORY_CACHE = {
    "path": None,
    "repository": None,
}
NETWORK_DIAGNOSTICS_LOCK = threading.Lock()
NETWORK_DIAGNOSTICS_CACHE = {
    "checked_at": 0,
    "data": None,
}
JOB_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="edge-tts")
DEFAULT_SETTINGS = {
    "default_voice": "zh-CN-XiaoxiaoNeural",
    "default_speech_rate": DEFAULT_SPEECH_RATE,
    "default_volume": DEFAULT_VOLUME,
    "default_pitch": DEFAULT_PITCH,
    "proxy_url": "",
    "history_retention_days": 7,
    "task_retention_days": 30,
    "temp_file_ttl_hours": 6,
    "default_save_dir": "",
    "auto_open_browser": True,
    "chunk_length": MAX_CHUNK_LENGTH,
}
APP_SETTINGS = DEFAULT_SETTINGS.copy()

# 定义可用的语音列表
AVAILABLE_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓", "gender": "女", "style": "温暖，新闻，小说"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊", "gender": "女", "style": "可爱，卡通，小说"},
    {"id": "zh-CN-YunjianNeural", "name": "云健", "gender": "男", "style": "热情，运动，小说"},
    {"id": "zh-CN-YunxiNeural", "name": "云希", "gender": "男", "style": "阳光，小说"},
    {"id": "zh-CN-YunxiaNeural", "name": "云夏", "gender": "男", "style": "可爱，卡通，小说"},
    {"id": "zh-CN-YunyangNeural", "name": "云扬", "gender": "男", "style": "专业，新闻"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "晓北", "gender": "女", "style": "东北方言，幽默"},
    {"id": "zh-CN-shaanxi-XiaoniNeural", "name": "晓妮", "gender": "女", "style": "陕西方言，明快"},
    {"id": "zh-HK-HiuGaaiNeural", "name": "晓佳", "gender": "女", "style": "粤语，亲和"},
    {"id": "zh-HK-HiuMaanNeural", "name": "晓曼", "gender": "女", "style": "粤语，亲和"},
    {"id": "zh-HK-WanLungNeural", "name": "云龙", "gender": "男", "style": "粤语，亲和"},
    {"id": "zh-TW-HsiaoChenNeural", "name": "晓辰", "gender": "女", "style": "台湾腔，亲和"},
    {"id": "zh-TW-HsiaoYuNeural", "name": "晓语", "gender": "女", "style": "台湾腔，亲和"},
    {"id": "zh-TW-YunJheNeural", "name": "云哲", "gender": "男", "style": "台湾腔，亲和"}
]
BUILTIN_VOICES = [voice.copy() for voice in AVAILABLE_VOICES]
AVAILABLE_VOICE_IDS = {voice["id"] for voice in AVAILABLE_VOICES}
VOICE_CATALOG_LOCK = threading.RLock()
VOICE_PRESETS = [
    {
        "id": "short_video",
        "name": "短视频口播",
        "voice": "zh-CN-YunxiNeural",
        "speech_rate": "1.1",
        "volume": "1.25",
        "pitch": "10",
    },
    {
        "id": "news",
        "name": "新闻播报",
        "voice": "zh-CN-YunyangNeural",
        "speech_rate": "1.0",
        "volume": "1.0",
        "pitch": "0",
    },
    {
        "id": "story",
        "name": "小说旁白",
        "voice": "zh-CN-XiaoxiaoNeural",
        "speech_rate": "0.9",
        "volume": "1.0",
        "pitch": "-10",
    },
    {
        "id": "kids",
        "name": "儿童故事",
        "voice": "zh-CN-XiaoyiNeural",
        "speech_rate": "0.9",
        "volume": "1.25",
        "pitch": "10",
    },
    {
        "id": "cantonese",
        "name": "粤语口播",
        "voice": "zh-HK-HiuGaaiNeural",
        "speech_rate": "1.0",
        "volume": "1.0",
        "pitch": "0",
    },
]

def error_response(code, message, status_code=400, detail=None):
    """返回统一的 API 错误格式。"""
    app.logger.warning(
        "api_error code=%s status=%s request_id=%s",
        code,
        status_code,
        getattr(g, "request_id", "-") if has_request_context() else "-",
    )
    payload = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if detail:
        payload["error"]["detail"] = detail
    return jsonify(payload), status_code

def get_settings_path():
    """返回本地设置文件路径。"""
    configured_path = app.config.get("SETTINGS_PATH")
    if configured_path:
        return configured_path
    return os.path.join(get_app_temp_dir(), "settings.json")

def get_state_path():
    """返回旧版 JSON 状态文件路径，用于一次性迁移。"""
    configured_path = app.config.get("STATE_PATH")
    if configured_path:
        return configured_path
    return os.path.join(get_app_temp_dir(), "state.json")

def get_voice_cache_path():
    configured_path = app.config.get("VOICE_CACHE_PATH")
    if configured_path:
        return configured_path
    return os.path.join(get_app_temp_dir(), "voices.json")

def get_database_path():
    """返回 SQLite 状态数据库路径。"""
    configured_path = app.config.get("DATABASE_PATH")
    if configured_path:
        return configured_path
    return os.path.join(get_app_temp_dir(), "edge-tts-web.sqlite3")

def get_log_path():
    configured_path = app.config.get("LOG_PATH")
    if configured_path:
        return configured_path
    return os.path.join(get_app_temp_dir(), "edge-tts-web.log")

def get_secret_key_path():
    configured_path = app.config.get("SECRET_KEY_PATH")
    if configured_path:
        return configured_path
    return os.path.join(get_app_temp_dir(), "secret.key")

def configure_secret_key():
    path = get_secret_key_path()
    try:
        with open(path, "rb") as secret_file:
            secret_key = secret_file.read()
    except OSError:
        secret_key = os.urandom(32)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as secret_file:
            secret_file.write(secret_key)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    app.secret_key = secret_key
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=12 * 60 * 60,
    )

def configure_logging():
    """配置本地滚动日志，避免记录完整用户文本。"""
    log_path = get_log_path()
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    for handler in app.logger.handlers:
        if getattr(handler, "baseFilename", None) == os.path.abspath(log_path):
            return
    handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        "%Y-%m-%dT%H:%M:%S",
    ))
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)

def get_repository():
    path = get_database_path()
    with REPOSITORY_LOCK:
        if REPOSITORY_CACHE["path"] != path:
            REPOSITORY_CACHE["path"] = path
            REPOSITORY_CACHE["repository"] = StateRepository(path)
        return REPOSITORY_CACHE["repository"]

def write_json_atomic(path, payload):
    """原子写入 JSON，避免异常退出留下半个文件。"""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temp_path = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as output_file:
            json.dump(payload, output_file, ensure_ascii=False, indent=2)
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass

def save_user_state():
    """持久化收藏、最近使用和历史记录。"""
    with TEXT_JOB_LOCK:
        text_jobs = list(TEXT_JOBS.values())
    with BATCH_LOCK:
        batch_jobs = list(BATCH_JOBS.values())
    with HISTORY_LOCK:
        history = [item.copy() for item in HISTORY_ITEMS]
    with PREFERENCES_LOCK:
        preferences = {
            "favorite_voices": list(USER_PREFERENCES["favorite_voices"]),
            "recent_voices": list(USER_PREFERENCES["recent_voices"]),
            "config_favorites": dict(USER_PREFERENCES["config_favorites"]),
            "auto_download": dict(USER_PREFERENCES["auto_download"]),
        }

    repository = get_repository()
    repository.save_preferences(preferences)
    repository.replace_history(history)
    for job in text_jobs:
        repository.save_job("text", job)
    for job in batch_jobs:
        repository.save_job("batch", job)

def load_user_state():
    """从 SQLite 加载用户状态，并兼容迁移旧版 JSON。"""
    repository = get_repository()
    preferences = repository.load_preferences()
    history = repository.load_history(HISTORY_LIMIT)
    text_job_list = repository.load_jobs("text")
    batch_job_list = repository.load_jobs("batch")

    state_path = get_state_path()
    if not preferences and not history and not text_job_list and os.path.exists(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as state_file:
                legacy_payload = json.load(state_file)
        except (OSError, json.JSONDecodeError, ValueError):
            legacy_payload = {}
        preferences = legacy_payload.get("preferences") or {}
        history = legacy_payload.get("history") or []
        text_job_list = legacy_payload.get("text_jobs") or []

    favorites = [
        voice_id for voice_id in preferences.get("favorite_voices", [])
        if voice_id in AVAILABLE_VOICE_IDS
    ]
    recent = [
        voice_id for voice_id in preferences.get("recent_voices", [])
        if voice_id in AVAILABLE_VOICE_IDS
    ][:8]
    history = [
        item for item in history
        if isinstance(item, dict) and item.get("id") and item.get("job_id")
    ][:HISTORY_LIMIT]
    text_jobs = {}
    for job in text_job_list:
        if not isinstance(job, dict) or not job.get("id") or not isinstance(job.get("items"), list):
            continue
        if job.get("status") in ("queued", "processing"):
            job["status"] = "finished"
            job["finished_at"] = time.time()
            for item in job["items"]:
                if item.get("status") in ("pending", "processing"):
                    item["status"] = "failed"
                    item["error"] = "应用上次运行时任务被中断，请重试此片段。"
        for item in job["items"]:
            audio_path = item.get("audio_path")
            if item.get("status") == "done" and (
                not audio_path
                or not is_managed_audio_path(audio_path)
                or not os.path.exists(audio_path)
            ):
                item["status"] = "failed"
                item["audio_path"] = None
                item["size"] = 0
                item["error"] = "音频文件已清理，请重试此片段。"
        recompute_text_job_counts(job)
        text_jobs[job["id"]] = job
    batch_jobs = {}
    for job in batch_job_list:
        if not isinstance(job, dict) or not job.get("id") or not isinstance(job.get("items"), list):
            continue
        restore_interrupted_batch_job(job)
        batch_jobs[job["id"]] = job

    with PREFERENCES_LOCK:
        USER_PREFERENCES["favorite_voices"] = favorites
        USER_PREFERENCES["recent_voices"] = recent
        USER_PREFERENCES["config_favorites"] = (
            preferences.get("config_favorites")
            if isinstance(preferences.get("config_favorites"), dict)
            else {}
        )
        USER_PREFERENCES["auto_download"] = (
            preferences.get("auto_download")
            if isinstance(preferences.get("auto_download"), dict)
            else {}
        )
    with HISTORY_LOCK:
        HISTORY_ITEMS[:] = history
    with TEXT_JOB_LOCK:
        TEXT_JOBS.update(text_jobs)
    with BATCH_LOCK:
        BATCH_JOBS.update(batch_jobs)
    if os.path.exists(state_path):
        try:
            os.replace(state_path, f"{state_path}.migrated")
        except OSError:
            pass
    if preferences or history or text_jobs or batch_jobs:
        save_user_state()

def normalize_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on")
    return bool(value)

def normalize_int(value, fallback, minimum=None, maximum=None):
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = fallback
    if minimum is not None:
        normalized = max(minimum, normalized)
    if maximum is not None:
        normalized = min(maximum, normalized)
    return normalized

def normalize_settings(raw_settings):
    """校验并标准化用户设置。"""
    settings = DEFAULT_SETTINGS.copy()
    if raw_settings:
        settings.update(raw_settings)

    settings["default_voice"] = validate_voice_id(settings.get("default_voice"))
    settings["default_speech_rate"] = normalize_speech_rate(settings.get("default_speech_rate"))
    settings["default_volume"] = normalize_volume(settings.get("default_volume"))
    settings["default_pitch"] = normalize_pitch(settings.get("default_pitch"))
    settings["proxy_url"] = str(settings.get("proxy_url") or "").strip()
    settings["history_retention_days"] = normalize_int(settings.get("history_retention_days"), 7, 1, 365)
    settings["task_retention_days"] = normalize_int(settings.get("task_retention_days"), 30, 1, 365)
    settings["temp_file_ttl_hours"] = normalize_int(settings.get("temp_file_ttl_hours"), 6, 1, 168)
    save_dir = str(settings.get("default_save_dir") or "").strip()
    settings["default_save_dir"] = (
        os.path.abspath(os.path.expanduser(save_dir))
        if save_dir
        else ""
    )
    settings["auto_open_browser"] = normalize_bool(settings.get("auto_open_browser", True))
    settings["chunk_length"] = normalize_int(settings.get("chunk_length"), MAX_CHUNK_LENGTH, 500, MAX_CHUNK_LENGTH)
    return settings

def load_settings():
    """从本地文件加载设置。"""
    global APP_SETTINGS
    settings_path = get_settings_path()
    raw_settings = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as settings_file:
                raw_settings = json.load(settings_file)
        except (OSError, json.JSONDecodeError, ValueError):
            raw_settings = {}

    with SETTINGS_LOCK:
        APP_SETTINGS = normalize_settings(raw_settings)
        return APP_SETTINGS.copy()

def save_settings(new_settings):
    """保存本地设置。"""
    global APP_SETTINGS
    normalized_settings = normalize_settings(new_settings)
    save_dir = normalized_settings.get("default_save_dir")
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        if not os.path.isdir(save_dir) or not os.access(save_dir, os.W_OK):
            raise OSError("默认保存目录不可写。")
    settings_path = get_settings_path()
    with SETTINGS_LOCK:
        APP_SETTINGS = normalized_settings
        write_json_atomic(settings_path, APP_SETTINGS)
        return APP_SETTINGS.copy()

def get_settings():
    with SETTINGS_LOCK:
        return APP_SETTINGS.copy()

def settings_for_user(user):
    settings = get_settings()
    if not user or user.get("role") != "admin":
        settings["proxy_url"] = ""
        settings["default_save_dir"] = ""
    return settings

def validate_voice_id(voice_id):
    """校验音色 ID 是否在当前白名单中。"""
    normalized_voice_id = (voice_id or "zh-CN-XiaoxiaoNeural").strip()
    if normalized_voice_id not in AVAILABLE_VOICE_IDS:
        raise ValueError("不支持的语音角色，请从列表中选择可用音色。")
    return normalized_voice_id

def apply_voice_catalog(voices):
    valid_voices = [
        voice for voice in voices
        if isinstance(voice, dict)
        and voice.get("id")
        and voice.get("name")
    ]
    if not valid_voices:
        return
    with VOICE_CATALOG_LOCK:
        AVAILABLE_VOICES[:] = valid_voices
        AVAILABLE_VOICE_IDS.clear()
        AVAILABLE_VOICE_IDS.update(voice["id"] for voice in valid_voices)

def load_voice_cache():
    try:
        with open(get_voice_cache_path(), "r", encoding="utf-8") as cache_file:
            payload = json.load(cache_file)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    voices = payload.get("voices") if isinstance(payload, dict) else None
    if not isinstance(voices, list):
        return False
    apply_voice_catalog(voices)
    return True

def refresh_voice_catalog():
    import asyncio
    import edge_tts

    remote_voices = asyncio.run(edge_tts.list_voices(proxy=get_proxy_url()))
    curated_by_id = {voice["id"]: voice for voice in BUILTIN_VOICES}
    refreshed = []
    for remote in remote_voices:
        locale = remote.get("Locale", "")
        voice_id = remote.get("ShortName", "")
        if not locale.startswith("zh-") or not voice_id:
            continue
        curated = curated_by_id.get(voice_id)
        if curated:
            refreshed.append({**curated, "source": "curated"})
            continue
        tags = remote.get("VoiceTag") or {}
        style_values = (
            tags.get("VoicePersonalities", [])
            + tags.get("ContentCategories", [])
        )
        refreshed.append({
            "id": voice_id,
            "name": voice_id.rsplit("-", 1)[-1].replace("Neural", ""),
            "gender": "女" if remote.get("Gender") == "Female" else "男",
            "style": "，".join(style_values) or locale,
            "locale": locale,
            "source": "online",
        })
    if not refreshed:
        raise ValueError("在线音色目录没有返回可用的中文音色。")
    refreshed.sort(key=lambda voice: (voice.get("source") != "curated", voice.get("locale", ""), voice["name"]))
    apply_voice_catalog(refreshed)
    write_json_atomic(get_voice_cache_path(), {
        "updated_at": time.time(),
        "voices": refreshed,
    })
    return refreshed

def voice_by_id(voice_id):
    with VOICE_CATALOG_LOCK:
        return next((voice for voice in AVAILABLE_VOICES if voice["id"] == voice_id), None)

def remember_recent_voice(voice_id):
    """记录最近使用音色。"""
    if voice_id not in AVAILABLE_VOICE_IDS:
        return
    with PREFERENCES_LOCK:
        recent = [current for current in USER_PREFERENCES["recent_voices"] if current != voice_id]
        recent.insert(0, voice_id)
        USER_PREFERENCES["recent_voices"] = recent[:8]
    save_user_state()

def public_preferences():
    with PREFERENCES_LOCK:
        return {
            "favorite_voices": list(USER_PREFERENCES["favorite_voices"]),
            "recent_voices": list(USER_PREFERENCES["recent_voices"]),
        }

def preference_user_key(user):
    return str((user or {}).get("id", 0))

def public_user_workspace_preferences(user):
    user_key = preference_user_key(user)
    with PREFERENCES_LOCK:
        favorites = USER_PREFERENCES["config_favorites"].get(user_key, [])
        auto_download = USER_PREFERENCES["auto_download"].get(user_key, "off")
        return {
            "config_favorites": [item.copy() for item in favorites],
            "auto_download": auto_download,
        }

def save_user_workspace_preferences(user, *, favorites=None, auto_download=None):
    user_key = preference_user_key(user)
    with PREFERENCES_LOCK:
        if favorites is not None:
            USER_PREFERENCES["config_favorites"][user_key] = favorites
        if auto_download is not None:
            USER_PREFERENCES["auto_download"][user_key] = auto_download
    save_user_state()
    return public_user_workspace_preferences(user)

def set_favorite_voice(voice_id, favorite):
    validate_voice_id(voice_id)
    with PREFERENCES_LOCK:
        favorites = [current for current in USER_PREFERENCES["favorite_voices"] if current != voice_id]
        if favorite:
            favorites.insert(0, voice_id)
        USER_PREFERENCES["favorite_voices"] = favorites
        preferences = {
            "favorite_voices": list(USER_PREFERENCES["favorite_voices"]),
            "recent_voices": list(USER_PREFERENCES["recent_voices"]),
        }
    save_user_state()
    return preferences

def history_summary(text, limit=80):
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    return normalized[:limit]

def add_history_item(job):
    """记录已生成任务，避免同一任务重复写入。"""
    if not job.get("success_count"):
        return
    if job.get("history_recorded"):
        return

    first_done_item = next((item for item in job.get("items", []) if item.get("status") == "done"), None)
    history_item = {
        "id": uuid.uuid4().hex,
        "job_id": job["id"],
        "owner_id": job.get("owner_id"),
        "title": job.get("download_name") or "speech",
        "summary": job.get("text_summary") or "",
        "voice": job["voice"],
        "speech_rate": job["speech_rate"],
        "volume": job.get("volume", DEFAULT_VOLUME),
        "pitch": job.get("pitch", DEFAULT_PITCH),
        "text_length": job["text_length"],
        "total": job.get("total", 0),
        "success_count": job.get("success_count", 0),
        "failed_count": job.get("failed_count", 0),
        "created_at": job.get("created_at"),
        "finished_at": job.get("finished_at") or time.time(),
        "download_url": f"/jobs/{job['id']}/download",
        "audio_url": f"/jobs/{job['id']}/items/{first_done_item['id']}/audio" if first_done_item else None,
    }

    with HISTORY_LOCK:
        cleanup_history_items_locked()
        HISTORY_ITEMS.insert(0, history_item)
        del HISTORY_ITEMS[HISTORY_LIMIT:]

    job["history_recorded"] = True
    save_user_state()

def public_history_items(user=None):
    with HISTORY_LOCK:
        cleanup_history_items_locked()
        items = [item.copy() for item in HISTORY_ITEMS]
    if not user or user.get("role") == "admin":
        return items
    return [item for item in items if item.get("owner_id") == user.get("id")]

def cleanup_history_items_locked():
    """在 HISTORY_LOCK 内清理过期历史。"""
    retention_seconds = get_settings().get("history_retention_days", 7) * 24 * 60 * 60
    cutoff = time.time() - retention_seconds
    HISTORY_ITEMS[:] = [
        item for item in HISTORY_ITEMS
        if item.get("finished_at", item.get("created_at", time.time())) >= cutoff
    ]

def get_app_temp_dir():
    """返回应用专用临时目录。"""
    temp_dir = app.config.get("TEMP_AUDIO_DIR") or os.path.join(tempfile.gettempdir(), TEMP_DIR_NAME)
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir

def create_temp_audio_file():
    """在应用专用临时目录中创建 MP3 临时文件。"""
    return tempfile.NamedTemporaryFile(delete=False, suffix='.mp3', dir=get_app_temp_dir())

def merge_audio_files(audio_paths):
    """按顺序拼接 Edge TTS 生成的同编码 MP3 文件。"""
    if not audio_paths:
        raise ValueError("没有可合并的音频文件。")
    with create_temp_audio_file() as merged_file:
        for audio_path in audio_paths:
            if not is_managed_audio_path(audio_path) or not os.path.exists(audio_path):
                unlink_audio_file(merged_file.name)
                raise ValueError("音频片段不存在或不在受控目录中。")
            with open(audio_path, "rb") as source_file:
                while True:
                    block = source_file.read(1024 * 1024)
                    if not block:
                        break
                    merged_file.write(block)
        merged_path = merged_file.name
    if os.path.getsize(merged_path) == 0:
        unlink_audio_file(merged_path)
        raise ValueError("合并后的音频为空。")
    return merged_path

def is_managed_audio_path(path):
    """判断路径是否位于应用专用临时目录中。"""
    if not path:
        return False

    temp_dir = os.path.realpath(get_app_temp_dir())
    target_path = os.path.realpath(path)
    return target_path == temp_dir or target_path.startswith(temp_dir + os.sep)

def unlink_audio_file(path):
    """只删除应用受控目录内的音频文件。"""
    if path and is_managed_audio_path(path) and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass

def register_single_result(audio_path, download_name, owner_id=None):
    """登记单条转换结果，返回给前端安全的文件 token。"""
    file_id = uuid.uuid4().hex
    safe_download_name = sanitize_download_name(download_name, "speech.mp3")
    now = time.time()

    with SINGLE_RESULTS_LOCK:
        SINGLE_RESULTS[file_id] = {
            "id": file_id,
            "audio_path": audio_path,
            "download_name": safe_download_name,
            "owner_id": owner_id,
            "created_at": now,
            "expires_at": now + SINGLE_RESULT_TTL_SECONDS,
        }

    return file_id

def split_text_to_chunks(text, max_chars=MAX_CHUNK_LENGTH):
    """按自然断点把长文本切成 edge-tts 更稳定处理的片段。"""
    remaining_text = (text or "").strip()
    if not remaining_text:
        return []

    chunks = []
    strong_break_chars = "\n。！？!?"
    weak_break_chars = "；;，,、：:"
    min_soft_break = max(1, int(max_chars * 0.45))

    while len(remaining_text) > max_chars:
        window = remaining_text[:max_chars]
        split_at = -1

        for index in range(len(window) - 1, min_soft_break - 1, -1):
            if window[index] in strong_break_chars:
                split_at = index + 1
                break

        if split_at <= 0:
            for index in range(len(window) - 1, min_soft_break - 1, -1):
                if window[index] in weak_break_chars:
                    split_at = index + 1
                    break

        if split_at <= 0:
            for index in range(min(len(window) - 1, max_chars - 1), -1, -1):
                if window[index] in strong_break_chars:
                    split_at = index + 1
                    break

        if split_at <= 0:
            for index in range(min(len(window) - 1, max_chars - 1), -1, -1):
                if window[index] in weak_break_chars:
                    split_at = index + 1
                    break

        if split_at <= 0:
            for index in range(min(len(window) - 1, max_chars - 1), -1, -1):
                if window[index].isspace():
                    split_at = index + 1
                    break

        if split_at <= 0:
            split_at = max_chars

        chunk = remaining_text[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining_text = remaining_text[split_at:].strip()

    if remaining_text:
        chunks.append(remaining_text)

    return chunks

def recompute_text_job_counts(job):
    """根据 item 状态重新计算任务统计。"""
    items = job.get("items", [])
    job["total"] = len(items)
    job["success_count"] = sum(1 for item in items if item.get("status") == "done")
    job["failed_count"] = sum(1 for item in items if item.get("status") == "failed")
    job["cancelled_count"] = sum(1 for item in items if item.get("status") == "cancelled")
    job["completed"] = sum(
        1
        for item in items
        if item.get("status") in ("done", "failed", "cancelled")
    )
    return job

def recompute_batch_job_counts(job):
    """根据批量 item 状态统一计算任务统计。"""
    items = job.get("items", [])
    job["total"] = len(items)
    job["success_count"] = sum(1 for item in items if item.get("status") == "done")
    job["failed_count"] = sum(1 for item in items if item.get("status") == "failed")
    job["cancelled_count"] = sum(1 for item in items if item.get("status") == "cancelled")
    job["completed"] = sum(
        1 for item in items
        if item.get("status") in ("done", "failed", "cancelled")
    )
    return job

def restore_interrupted_batch_job(job):
    """把重启时未完成的批量任务转换为可重试状态。"""
    if job.get("status") in ("queued", "processing"):
        job["status"] = "finished"
        job["finished_at"] = time.time()
        for item in job.get("items", []):
            if item.get("status") in ("pending", "processing"):
                item["status"] = "failed"
                item["error"] = "应用上次运行时任务被中断，请重试此文件。"
    for item in job.get("items", []):
        audio_path = item.get("audio_path")
        if item.get("status") == "done" and (
            not audio_path
            or not is_managed_audio_path(audio_path)
            or not os.path.exists(audio_path)
        ):
            item["status"] = "failed"
            item["audio_path"] = None
            item["size"] = 0
            item["error"] = "音频文件已清理，请重试此文件。"
    recompute_batch_job_counts(job)
    return job

def estimate_remaining_seconds(job):
    """基于已完成片段粗略估算剩余耗时。"""
    if not job.get("started_at") or not job.get("completed"):
        return None

    remaining = max(job.get("total", 0) - job.get("completed", 0), 0)
    if remaining == 0:
        return 0

    elapsed = max(time.time() - job["started_at"], 0)
    average = elapsed / max(job["completed"], 1)
    return round(average * remaining, 1)

def task_queue_position(job):
    if job.get("status") != "queued":
        return None
    queued = [
        (candidate.get("created_at", 0), candidate["id"])
        for candidate in list(TEXT_JOBS.values()) + list(BATCH_JOBS.values())
        if candidate.get("status") == "queued"
    ]
    queued.sort()
    return next(
        (index + 1 for index, (_created_at, job_id) in enumerate(queued) if job_id == job["id"]),
        None,
    )

def estimate_item_remaining_seconds(item, job):
    if item.get("status") in ("done", "failed", "cancelled"):
        return 0
    completed_durations = [
        candidate.get("elapsed_seconds")
        for candidate in job.get("items", [])
        if candidate.get("status") in ("done", "failed")
        and candidate.get("elapsed_seconds") is not None
    ]
    if not completed_durations:
        return None
    average = sum(completed_durations) / len(completed_durations)
    if item.get("status") == "processing" and item.get("started_at"):
        average -= max(time.time() - item["started_at"], 0)
    return round(max(average, 0), 1)

def public_task_item(item, kind, job):
    now = time.time()
    started_at = item.get("started_at")
    finished_at = item.get("finished_at")
    elapsed_seconds = item.get("elapsed_seconds")
    if started_at and elapsed_seconds is None:
        elapsed_seconds = round(max((finished_at or now) - started_at, 0), 1)
    payload = {
        "id": item["id"],
        "index": item.get("index"),
        "status": item["status"],
        "text_length": item.get("text_length", 0),
        "size": item.get("size", 0),
        "error": item.get("error"),
        "attempts": item.get("attempts", 0),
        "created_at": item.get("created_at"),
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": elapsed_seconds,
        "estimated_remaining_seconds": estimate_item_remaining_seconds(item, job),
    }
    if kind == "batch":
        payload.update({
            "source_name": item.get("source_name"),
            "download_name": item.get("download_name"),
        })
    return payload

def public_text_job(job):
    """返回可暴露给前端的文本任务数据。"""
    recompute_text_job_counts(job)
    now = time.time()
    elapsed_seconds = None
    if job.get("started_at"):
        end_time = job.get("finished_at") or now
        elapsed_seconds = round(max(end_time - job["started_at"], 0), 1)

    return {
        "id": job["id"],
        "status": job["status"],
        "voice": job["voice"],
        "speech_rate": job["speech_rate"],
        "volume": job.get("volume", DEFAULT_VOLUME),
        "pitch": job.get("pitch", DEFAULT_PITCH),
        "text_length": job["text_length"],
        "total": job["total"],
        "completed": job["completed"],
        "success_count": job["success_count"],
        "failed_count": job["failed_count"],
        "cancelled_count": job.get("cancelled_count", 0),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "elapsed_seconds": elapsed_seconds,
        "estimated_remaining_seconds": estimate_remaining_seconds(job),
        "queue_position": task_queue_position(job),
        "download_name": job["download_name"],
        "downloadable": job["success_count"] > 0,
        "cancel_requested": job.get("cancel_requested", False),
        "summary": job.get("text_summary", ""),
        "audio_url": first_text_job_audio_url(job),
        "items": [public_task_item(item, "text", job) for item in job["items"]],
    }

def first_text_job_audio_url(job):
    first_done_item = next((item for item in job.get("items", []) if item.get("status") == "done"), None)
    if not first_done_item:
        return None
    return f"/jobs/{job['id']}/items/{first_done_item['id']}/audio"

def get_text_job(job_id):
    """线程安全读取文本任务。"""
    with TEXT_JOB_LOCK:
        job = TEXT_JOBS.get(job_id)
        if job:
            return job.copy()
    return None

def update_text_job(job_id, updater):
    """线程安全地更新文本任务。"""
    with TEXT_JOB_LOCK:
        job = TEXT_JOBS.get(job_id)
        if not job:
            return None
        updater(job)
        recompute_text_job_counts(job)
        job["updated_at"] = time.time()
        get_repository().save_job("text", job)
        return job.copy()

def create_text_job(
    text,
    voice,
    speech_rate,
    volume=DEFAULT_VOLUME,
    pitch=DEFAULT_PITCH,
    owner_id=None,
):
    """创建异步文本转语音任务。"""
    chunk_length = get_settings().get("chunk_length", MAX_CHUNK_LENGTH)
    chunks = split_text_to_chunks(text, chunk_length)
    if not chunks:
        raise ValueError("请输入要转换的文本。")

    job_id = uuid.uuid4().hex
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    download_name = f"speech_{timestamp}"
    now = time.time()
    items = [
        {
            "id": uuid.uuid4().hex,
            "index": index + 1,
            "text": chunk,
            "text_length": len(chunk),
            "status": "pending",
            "audio_path": None,
            "size": 0,
            "error": None,
            "attempts": 0,
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "elapsed_seconds": None,
            "download_name": f"{download_name}_part_{index + 1:03d}.mp3",
        }
        for index, chunk in enumerate(chunks)
    ]
    job = {
        "id": job_id,
        "owner_id": owner_id,
        "status": "queued",
        "voice": voice,
        "speech_rate": speech_rate,
        "volume": volume,
        "pitch": pitch,
        "text_length": len(text),
        "text_summary": history_summary(text),
        "download_name": download_name,
        "total": len(items),
        "completed": 0,
        "success_count": 0,
        "failed_count": 0,
        "cancelled_count": 0,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
        "cancel_requested": False,
        "history_recorded": False,
        "items": items,
    }
    recompute_text_job_counts(job)

    with TEXT_JOB_LOCK:
        TEXT_JOBS[job_id] = job

    get_repository().save_job("text", job)
    return job

def terminal_text_job_status(job):
    if job.get("cancel_requested"):
        return "cancelled"
    if any(item.get("status") in ("pending", "processing") for item in job.get("items", [])):
        return "processing"
    return "finished"

def mark_remaining_text_items_cancelled(job):
    for item in job.get("items", []):
        if item.get("status") in ("pending", "processing"):
            item["status"] = "cancelled"
            item["error"] = "任务已取消。"

def process_text_job(job_id, only_item_id=None):
    """后台处理文本转语音任务，可处理全量或单个失败片段。"""
    app.logger.info("text_job_started job_id=%s retry_item=%s", job_id, only_item_id or "-")
    def mark_job_processing(job):
        job["status"] = "processing"
        job["finished_at"] = None
        if not job.get("started_at"):
            job["started_at"] = time.time()

    update_text_job(job_id, mark_job_processing)

    with TEXT_JOB_LOCK:
        job = TEXT_JOBS.get(job_id)
        if not job:
            return
        target_items = [
            item
            for item in job["items"]
            if (only_item_id is None or item["id"] == only_item_id)
            and item.get("status") in ("pending", "failed", "cancelled")
        ]

    for item in target_items:
        with TEXT_JOB_LOCK:
            job = TEXT_JOBS.get(job_id)
            if not job:
                return
            if job.get("cancel_requested"):
                mark_remaining_text_items_cancelled(job)
                recompute_text_job_counts(job)
                job["status"] = "cancelled"
                job["finished_at"] = time.time()
                job["updated_at"] = time.time()
                get_repository().save_job("text", job)
                return
            current_item = next((candidate for candidate in job["items"] if candidate["id"] == item["id"]), None)
            if not current_item:
                continue
            current_item["status"] = "processing"
            current_item["error"] = None
            current_item["attempts"] = current_item.get("attempts", 0) + 1
            current_item["started_at"] = time.time()
            current_item["finished_at"] = None
            current_item["elapsed_seconds"] = None
            job["updated_at"] = time.time()
            get_repository().save_job("text", job)

        try:
            audio_path = generate_speech_with_retries(
                item["text"],
                job["voice"],
                job["speech_rate"],
                job.get("volume", DEFAULT_VOLUME),
                job.get("pitch", DEFAULT_PITCH),
            )
            file_size = os.path.getsize(audio_path)

            with TEXT_JOB_LOCK:
                job = TEXT_JOBS.get(job_id)
                if not job:
                    unlink_audio_file(audio_path)
                    return
                current_item = next((candidate for candidate in job["items"] if candidate["id"] == item["id"]), None)
                if not current_item:
                    unlink_audio_file(audio_path)
                    continue
                unlink_audio_file(current_item.get("audio_path"))
                current_item["status"] = "done"
                current_item["audio_path"] = audio_path
                current_item["size"] = file_size
                current_item["error"] = None
                current_item["finished_at"] = time.time()
                current_item["elapsed_seconds"] = round(
                    max(current_item["finished_at"] - current_item.get("started_at", current_item["finished_at"]), 0),
                    1,
                )
                recompute_text_job_counts(job)
                job["updated_at"] = time.time()
                get_repository().save_job("text", job)
        except Exception as e:
            error_msg = error_message_from_exception(e)
            with TEXT_JOB_LOCK:
                job = TEXT_JOBS.get(job_id)
                if not job:
                    return
                current_item = next((candidate for candidate in job["items"] if candidate["id"] == item["id"]), None)
                if current_item:
                    current_item["status"] = "failed"
                    current_item["error"] = error_msg
                    current_item["finished_at"] = time.time()
                    current_item["elapsed_seconds"] = round(
                        max(current_item["finished_at"] - current_item.get("started_at", current_item["finished_at"]), 0),
                        1,
                    )
                recompute_text_job_counts(job)
                job["updated_at"] = time.time()
                get_repository().save_job("text", job)

    with TEXT_JOB_LOCK:
        job = TEXT_JOBS.get(job_id)
        if not job:
            return
        if job.get("cancel_requested"):
            mark_remaining_text_items_cancelled(job)
        recompute_text_job_counts(job)
        job["status"] = terminal_text_job_status(job)
        if job["status"] in ("finished", "cancelled"):
            job["finished_at"] = time.time()
        if job["status"] == "finished" and job.get("success_count"):
            add_history_item(job)
        job["updated_at"] = time.time()
        get_repository().save_job("text", job)
        app.logger.info(
            "text_job_finished job_id=%s status=%s success=%s failed=%s elapsed_seconds=%s",
            job_id,
            job["status"],
            job.get("success_count", 0),
            job.get("failed_count", 0),
            round(max(job.get("finished_at", time.time()) - job.get("started_at", time.time()), 0), 1),
        )

def get_single_result(file_id):
    """读取单条转换结果。"""
    with SINGLE_RESULTS_LOCK:
        result = SINGLE_RESULTS.get(file_id)
        if result:
            return result.copy()
    return None

def cleanup_single_results():
    """清理过期的单条转换结果。"""
    now = time.time()
    expired_results = []

    with SINGLE_RESULTS_LOCK:
        for file_id, result in list(SINGLE_RESULTS.items()):
            audio_path = result.get("audio_path")
            if now > result.get("expires_at", now) or not audio_path or not os.path.exists(audio_path):
                expired_results.append(result)
                SINGLE_RESULTS.pop(file_id, None)

    for result in expired_results:
        unlink_audio_file(result.get("audio_path"))

def cleanup_expired_audio_files(max_age_seconds=SINGLE_RESULT_TTL_SECONDS):
    """清理应用临时目录中无任务引用且过期的音频文件。"""
    temp_dir = get_app_temp_dir()
    now = time.time()
    referenced_paths = set()

    with SINGLE_RESULTS_LOCK:
        referenced_paths.update(
            os.path.realpath(result["audio_path"])
            for result in SINGLE_RESULTS.values()
            if result.get("audio_path")
        )

    with BATCH_LOCK:
        for job in BATCH_JOBS.values():
            for item in job.get("items", []):
                audio_path = item.get("audio_path")
                if audio_path:
                    referenced_paths.add(os.path.realpath(audio_path))

    with TEXT_JOB_LOCK:
        for job in TEXT_JOBS.values():
            for item in job.get("items", []):
                audio_path = item.get("audio_path")
                if audio_path:
                    referenced_paths.add(os.path.realpath(audio_path))

    for filename in os.listdir(temp_dir):
        file_path = os.path.join(temp_dir, filename)
        if not file_path.lower().endswith(".mp3") or not os.path.isfile(file_path):
            continue
        if os.path.realpath(file_path) in referenced_paths:
            continue
        if now - os.path.getmtime(file_path) > max_age_seconds:
            unlink_audio_file(file_path)

def can_connect(host, port, timeout=5):
    """检查指定主机端口是否可连接。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return True
    except OSError:
        return False

def is_proxy_available(proxy_url):
    """检查代理地址是否可用。"""
    if not proxy_url:
        return False

    parsed = urlparse(proxy_url)
    host = parsed.hostname
    port = parsed.port
    if not host:
        return False
    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    return can_connect(host, port, timeout=2)

def get_proxy_url():
    """返回 edge-tts 可用的代理配置。"""
    proxy_url = (
        get_settings().get("proxy_url")
        or os.environ.get("EDGE_TTS_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("http_proxy")
    )
    return proxy_url if is_proxy_available(proxy_url) else None

def get_configured_proxy_url():
    """返回用户或环境配置的代理地址，不检查可用性。"""
    return (
        get_settings().get("proxy_url")
        or os.environ.get("EDGE_TTS_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("http_proxy")
        or ""
    )

def check_network_connectivity():
    """检查网络连接状态"""
    return collect_network_diagnostics()["network_connectivity"]

def collect_network_diagnostics(force=False):
    """返回代理和 Edge TTS 服务诊断信息。"""
    now = time.time()
    with NETWORK_DIAGNOSTICS_LOCK:
        cached_data = NETWORK_DIAGNOSTICS_CACHE["data"]
        checked_at = NETWORK_DIAGNOSTICS_CACHE["checked_at"]
        if not force and cached_data and now - checked_at < NETWORK_DIAGNOSTICS_TTL_SECONDS:
            return cached_data.copy()

    configured_proxy = get_configured_proxy_url()
    proxy_available = is_proxy_available(configured_proxy) if configured_proxy else False
    service_available = can_connect(
        "speech.platform.bing.com",
        443,
        timeout=NETWORK_CONNECT_TIMEOUT_SECONDS,
    )
    effective_proxy = configured_proxy if proxy_available else ""

    diagnostics = {
        "version": APP_VERSION,
        "proxy_configured": bool(configured_proxy),
        "proxy_url": configured_proxy,
        "proxy_available": proxy_available,
        "effective_proxy": effective_proxy,
        "edge_tts_host": "speech.platform.bing.com",
        "edge_tts_available": service_available,
        "network_connectivity": proxy_available or service_available,
        "settings_path": get_settings_path(),
        "database_path": get_database_path(),
        "log_path": get_log_path(),
        "temp_dir": get_app_temp_dir(),
        "checked_at": now,
    }
    with NETWORK_DIAGNOSTICS_LOCK:
        NETWORK_DIAGNOSTICS_CACHE["checked_at"] = now
        NETWORK_DIAGNOSTICS_CACHE["data"] = diagnostics.copy()
    return diagnostics

def sanitized_settings_summary():
    settings = get_settings()
    proxy_url = settings.get("proxy_url", "")
    if proxy_url:
        parsed = urlparse(proxy_url)
        proxy_url = f"{parsed.scheme}://{parsed.hostname or ''}"
        if parsed.port:
            proxy_url += f":{parsed.port}"
    settings["proxy_url"] = proxy_url
    settings["default_save_dir"] = bool(settings.get("default_save_dir"))
    return settings

def create_diagnostics_archive():
    """创建不包含用户文本的诊断 ZIP。"""
    diagnostics = collect_network_diagnostics(force=True)
    system_info = {
        "app_version": APP_VERSION,
        "generated_at": time.time(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "settings": sanitized_settings_summary(),
        "network": diagnostics,
        "storage_counts": get_repository().table_counts(),
    }
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr(
            "system.json",
            json.dumps(system_info, ensure_ascii=False, indent=2),
        )
        log_path = get_log_path()
        if os.path.exists(log_path):
            with open(log_path, "rb") as log_file:
                log_data = log_file.read()[-2 * 1024 * 1024:]
            zip_file.writestr("edge-tts-web.log", log_data)
        zip_file.writestr(
            "README.txt",
            "诊断包包含版本、系统、配置摘要、网络检测和最近日志，不包含输入文本或音频文件。\n",
        )
    archive.seek(0)
    return archive

def normalize_speech_rate(rate_value):
    """校验并标准化语速倍数。"""
    normalized_rate = str(rate_value or DEFAULT_SPEECH_RATE).strip()
    if normalized_rate == "1":
        normalized_rate = DEFAULT_SPEECH_RATE

    if normalized_rate not in SPEECH_RATE_OPTIONS:
        supported_rates = "、".join(f"{rate}x" for rate in SPEECH_RATE_OPTIONS)
        raise ValueError(f"不支持的语速：{normalized_rate}x。支持范围：{supported_rates}。")

    return normalized_rate

def edge_rate_from_speech_rate(rate_value):
    """将界面倍速转换为 edge-tts rate 参数。"""
    return SPEECH_RATE_OPTIONS[normalize_speech_rate(rate_value)]

def normalize_volume(value):
    normalized = str(value or DEFAULT_VOLUME).strip()
    if normalized == "1":
        normalized = DEFAULT_VOLUME
    if normalized not in VOLUME_OPTIONS:
        raise ValueError("不支持的音量，请从界面选项中选择。")
    return normalized

def normalize_pitch(value):
    normalized = str(DEFAULT_PITCH if value is None else value).strip()
    if normalized.startswith("+"):
        normalized = normalized[1:]
    if normalized not in PITCH_OPTIONS:
        raise ValueError("不支持的音高，请从界面选项中选择。")
    return normalized

def edge_volume_from_value(value):
    return VOLUME_OPTIONS[normalize_volume(value)]

def edge_pitch_from_value(value):
    return PITCH_OPTIONS[normalize_pitch(value)]

@app.route('/voices')
def get_voices():
    """获取可用的语音列表"""
    preferences = public_preferences()
    favorite_set = set(preferences["favorite_voices"])
    recent_set = set(preferences["recent_voices"])
    with VOICE_CATALOG_LOCK:
        voices = [
            {
                **voice,
                "favorite": voice["id"] in favorite_set,
                "recent": voice["id"] in recent_set,
            }
            for voice in AVAILABLE_VOICES
        ]
    return jsonify(voices)

@app.route('/voices/refresh', methods=['POST'])
def refresh_voices():
    if g.current_user.get("role") != "admin":
        return error_response("admin_required", "只有管理员可以刷新在线音色。", 403)
    try:
        voices = refresh_voice_catalog()
    except Exception as error:
        return error_response(
            "voice_refresh_failed",
            f"在线音色刷新失败：{error}",
            503,
        )
    app.logger.info(
        "voice_catalog_refreshed actor=%s count=%s",
        g.current_user["id"],
        len(voices),
    )
    return jsonify({"count": len(voices), "voices": voices})

@app.route('/presets')
def get_presets():
    return jsonify(VOICE_PRESETS)

@app.route('/preferences')
def get_preferences():
    return jsonify({
        **public_preferences(),
        **public_user_workspace_preferences(g.current_user),
    })

@app.route('/preferences/favorites/<voice_id>', methods=['POST'])
def update_favorite_voice(voice_id):
    data = request.get_json(silent=True) or {}
    favorite = bool(data.get("favorite", True))
    try:
        preferences = set_favorite_voice(voice_id, favorite)
    except ValueError as e:
        return error_response("invalid_voice", str(e), 400)
    return jsonify(preferences)

@app.route('/preferences/workspace', methods=['PATCH'])
def update_workspace_preferences():
    data = request.get_json(silent=True) or {}
    auto_download = data.get("auto_download")
    if auto_download not in ("off", "single", "all"):
        return error_response(
            "invalid_auto_download",
            "自动下载选项无效。",
            400,
        )
    return jsonify(save_user_workspace_preferences(
        g.current_user,
        auto_download=auto_download,
    ))

@app.route('/config-favorites', methods=['GET', 'POST'])
def config_favorites():
    workspace = public_user_workspace_preferences(g.current_user)
    if request.method == "GET":
        return jsonify(workspace["config_favorites"])

    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    if not name or len(name) > 30:
        return error_response("invalid_favorite_name", "收藏夹名称需为 1-30 个字符。", 400)
    try:
        favorite = {
            "id": uuid.uuid4().hex,
            "name": name,
            "voice": validate_voice_id(data.get("voice")),
            "speech_rate": normalize_speech_rate(data.get("speech_rate")),
            "volume": normalize_volume(data.get("volume")),
            "pitch": normalize_pitch(data.get("pitch")),
            "created_at": time.time(),
        }
    except ValueError as error:
        return error_response("invalid_favorite_config", str(error), 400)

    favorites = workspace["config_favorites"]
    favorites = [item for item in favorites if item.get("name") != name]
    favorites.insert(0, favorite)
    if len(favorites) > 20:
        favorites = favorites[:20]
    save_user_workspace_preferences(g.current_user, favorites=favorites)
    return jsonify(favorite), 201

@app.route('/config-favorites/<favorite_id>', methods=['DELETE'])
def delete_config_favorite(favorite_id):
    workspace = public_user_workspace_preferences(g.current_user)
    favorites = workspace["config_favorites"]
    filtered = [item for item in favorites if item.get("id") != favorite_id]
    if len(filtered) == len(favorites):
        return error_response("favorite_not_found", "配置收藏不存在。", 404)
    save_user_workspace_preferences(g.current_user, favorites=filtered)
    return jsonify({"deleted": True})

@app.route('/health')
def health_check():
    """健康检查接口"""
    diagnostics = collect_network_diagnostics()
    network_ok = diagnostics["network_connectivity"]
    return jsonify({
        'version': APP_VERSION,
        'status': 'ok' if network_ok else 'network_error',
        'network_connectivity': network_ok,
        'proxy_configured': diagnostics["proxy_configured"],
        'proxy_available': diagnostics["proxy_available"],
        'edge_tts_available': diagnostics["edge_tts_available"],
        'message': '服务正常' if network_ok else '网络连接异常，可能无法使用语音转换功能'
    })

@app.route('/diagnostics')
def diagnostics():
    force = request.args.get("force") in ("1", "true", "yes")
    return jsonify(collect_network_diagnostics(force=force))

@app.route('/diagnostics/download')
def diagnostics_download():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(
        create_diagnostics_archive(),
        as_attachment=True,
        download_name=f"edge-tts-diagnostics-{timestamp}.zip",
        mimetype="application/zip",
    )

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'GET':
        return jsonify(settings_for_user(g.current_user))

    if g.current_user.get("role") != "admin":
        return error_response("admin_required", "只有管理员可以修改系统设置。", 403)
    data = request.get_json(silent=True) or {}
    try:
        updated_settings = save_settings(data)
    except ValueError as e:
        return error_response("invalid_settings", str(e), 400)
    except OSError as e:
        return error_response("settings_save_failed", f"设置保存失败：{str(e)}", 500)

    with NETWORK_DIAGNOSTICS_LOCK:
        NETWORK_DIAGNOSTICS_CACHE["checked_at"] = 0
        NETWORK_DIAGNOSTICS_CACHE["data"] = None
    app.logger.info(
        "settings_updated actor=%s keys=%s",
        g.current_user["id"],
        ",".join(sorted(data.keys())),
    )
    return jsonify(updated_settings)

@app.route('/preview', methods=['POST'])
def preview_speech():
    run_periodic_cleanup()

    text = (request.form.get('text') or '').strip()
    if not text:
        return error_response("empty_text", "请输入要试听的文本。", 400)

    try:
        voice = validate_voice_id(request.form.get('voice') or get_settings().get("default_voice"))
    except ValueError as e:
        return error_response("invalid_voice", str(e), 400)

    try:
        speech_rate = normalize_speech_rate(request.form.get('speech_rate') or get_settings().get("default_speech_rate"))
    except ValueError as e:
        return error_response("invalid_speech_rate", str(e), 400)
    try:
        volume = normalize_volume(request.form.get('volume') or get_settings().get("default_volume"))
        pitch = normalize_pitch(
            request.form.get('pitch')
            if request.form.get('pitch') is not None
            else get_settings().get("default_pitch")
        )
    except ValueError as e:
        return error_response("invalid_voice_parameter", str(e), 400)

    if not check_network_connectivity():
        return error_response("network_unavailable", "网络连接异常，无法连接到语音服务。请检查网络连接后重试。", 503)

    preview_text = text[:PREVIEW_TEXT_LENGTH]
    try:
        audio_path = generate_speech_with_retries(
            preview_text,
            voice,
            speech_rate,
            volume,
            pitch,
        )
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_id = register_single_result(
            audio_path,
            f"preview_{timestamp}.mp3",
            owner_id=g.current_user["id"],
        )
        remember_recent_voice(voice)
        return jsonify({
            "file_id": file_id,
            "audio_url": f"/audio/{file_id}",
            "download_url": f"/download/{file_id}",
            "text_length": len(preview_text),
            "voice": voice,
            "speech_rate": speech_rate,
            "volume": volume,
            "pitch": pitch,
        })
    except Exception as e:
        error_msg = error_message_from_exception(e)
        return error_response("preview_generation_failed", error_msg, get_error_status_code(error_msg))

@app.route('/audio/<file_id>')
def preview_audio(file_id):
    result = get_single_result(file_id)
    if not result:
        return error_response("audio_result_not_found", "音频文件不存在或已过期。", 404)
    if g.current_user.get("role") != "admin" and result.get("owner_id") != g.current_user.get("id"):
        return error_response("audio_access_denied", "无权访问此音频。", 403)

    audio_path = result.get("audio_path")
    if not audio_path or not is_managed_audio_path(audio_path) or not os.path.exists(audio_path):
        return error_response("audio_file_missing", "音频文件不存在或已过期。", 404)

    return send_file(audio_path, mimetype='audio/mpeg')

def generate_speech(
    text,
    voice="zh-CN-XiaoxiaoNeural",
    speech_rate=DEFAULT_SPEECH_RATE,
    volume=DEFAULT_VOLUME,
    pitch=DEFAULT_PITCH,
):
    """使用 edge-tts Python API 生成语音"""
    temp_path = None
    try:
        # 创建临时文件
        with create_temp_audio_file() as tmp_file:
            temp_path = tmp_file.name
        
        # 使用 edge-tts Python API
        import asyncio
        import edge_tts
        import random
        
        async def _generate():
            # 添加随机延迟，避免请求过于频繁
            await asyncio.sleep(random.uniform(0.5, 2.0))
            
            # 使用更长的超时时间
            communicate = edge_tts.Communicate(
                text, 
                voice,
                rate=edge_rate_from_speech_rate(speech_rate),
                volume=edge_volume_from_value(volume),
                pitch=edge_pitch_from_value(pitch),
                proxy=get_proxy_url(),
                connect_timeout=CONNECT_TIMEOUT,
                receive_timeout=RECEIVE_TIMEOUT
            )
            await communicate.save(temp_path)
        
        # 运行异步函数
        asyncio.run(_generate())
        
        # 验证文件是否生成成功
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            raise Exception("Failed to generate audio file")
        
        return temp_path
    except Exception as e:
        error_msg = str(e)
        app.logger.error(f"Error in generate_speech: {error_msg}")
        
        # 清理临时文件
        unlink_audio_file(temp_path)
        
        # 根据错误类型提供更友好的错误信息
        if "403" in error_msg or "forbidden" in error_msg.lower():
            raise Exception("Microsoft Edge TTS 拒绝了本次请求。请先升级 edge-tts；如果仍失败，请检查网络或配置 EDGE_TTS_PROXY 代理。")
        elif "timeout" in error_msg.lower():
            raise Exception("网络连接超时，请检查网络连接后重试。")
        elif "connection" in error_msg.lower():
            raise Exception("无法连接到语音服务，请检查网络连接。")
        else:
            raise Exception(f"语音生成失败：{error_msg}")

def generate_speech_with_retries(
    text,
    voice,
    speech_rate=DEFAULT_SPEECH_RATE,
    volume=DEFAULT_VOLUME,
    pitch=DEFAULT_PITCH,
):
    """带重试的语音生成。"""
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            audio_path = generate_speech(text, voice, speech_rate, volume, pitch)

            if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
                raise Exception("Generated audio file is invalid")

            return audio_path
        except Exception as e:
            last_error = str(e)
            app.logger.error(f"Attempt {attempt + 1} failed: {last_error}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(1 * (attempt + 1))

    raise Exception(last_error or '语音生成失败，请稍后重试。')

def get_error_status_code(error_message):
    """根据错误内容返回更合适的 HTTP 状态码。"""
    if error_message and any(
        keyword in error_message.lower()
        for keyword in ("网络", "连接", "timeout", "proxy", "tts 拒绝")
    ):
        return 503
    return 500

def error_message_from_exception(error):
    return str(error) or "请求处理失败，请稍后重试。"

def sanitize_download_name(filename, fallback="speech.mp3"):
    """清理下载文件名，保留中文并去掉路径分隔符。"""
    name = os.path.basename(filename or fallback).replace("\x00", "").strip()
    name = re.sub(r'[\\/:"*?<>|]+', "_", name)
    return name or fallback

def unique_output_path(directory, filename):
    os.makedirs(directory, exist_ok=True)
    safe_name = sanitize_download_name(filename)
    stem, extension = os.path.splitext(safe_name)
    candidate = os.path.join(directory, safe_name)
    index = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{stem}_{index}{extension}")
        index += 1
    return candidate

def configured_save_directory():
    directory = get_settings().get("default_save_dir", "").strip()
    if not directory:
        raise ValueError("管理员尚未配置默认保存目录。")
    return os.path.abspath(os.path.expanduser(directory))

def text_job_audio_path(job):
    done_items = [
        item
        for item in sorted(job["items"], key=lambda current_item: current_item["index"])
        if item.get("status") == "done"
        and item.get("audio_path")
        and is_managed_audio_path(item["audio_path"])
        and os.path.exists(item["audio_path"])
    ]
    if not done_items:
        raise ValueError("没有可保存的音频文件。")
    if len(done_items) == 1:
        return done_items[0]["audio_path"], False
    return merge_audio_files([item["audio_path"] for item in done_items]), True

def mp3_name_from_txt(filename, used_names):
    """根据 txt 文件名生成唯一 mp3 文件名。"""
    safe_name = sanitize_download_name(filename, "speech.txt")
    base_name = os.path.splitext(safe_name)[0].strip() or "speech"
    candidate = f"{base_name}.mp3"
    index = 2

    while candidate in used_names:
        candidate = f"{base_name}_{index}.mp3"
        index += 1

    used_names.add(candidate)
    return candidate

def decode_text_file(raw_content):
    """解码上传的 txt 文件。"""
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return raw_content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文本编码，请使用 UTF-8、GBK 或 Big5 编码的 TXT 文件。")

def cleanup_job_files(job):
    """清理批量任务产生的音频文件。"""
    for item in job.get("items", []):
        audio_path = item.get("audio_path")
        unlink_audio_file(audio_path)

def cleanup_text_job_files(job):
    """清理文本任务产生的音频文件。"""
    for item in job.get("items", []):
        unlink_audio_file(item.get("audio_path"))

def cleanup_old_jobs():
    """清理过期的批量任务。"""
    now = time.time()
    retention_seconds = get_settings().get("task_retention_days", 30) * 24 * 60 * 60
    expired_jobs = []

    with BATCH_LOCK:
        for job_id, job in BATCH_JOBS.items():
            if job.get("status") not in ("queued", "processing") and now - job.get("created_at", now) > retention_seconds:
                expired_jobs.append((job_id, job))
        for job_id, _job in expired_jobs:
            BATCH_JOBS.pop(job_id, None)

    for _job_id, job in expired_jobs:
        cleanup_job_files(job)
        get_repository().delete_job(_job_id)

def cleanup_old_text_jobs():
    """清理过期的文本任务。"""
    now = time.time()
    retention_seconds = get_settings().get("task_retention_days", 30) * 24 * 60 * 60
    expired_jobs = []

    with TEXT_JOB_LOCK:
        for job_id, job in list(TEXT_JOBS.items()):
            if job.get("status") not in ("queued", "processing") and now - job.get("created_at", now) > retention_seconds:
                expired_jobs.append((job_id, job))
        for job_id, _job in expired_jobs:
            TEXT_JOBS.pop(job_id, None)

    for _job_id, job in expired_jobs:
        cleanup_text_job_files(job)
        get_repository().delete_job(_job_id)

def run_periodic_cleanup(force=False):
    """定期清理过期任务和临时文件。"""
    global LAST_CLEANUP_AT

    now = time.time()
    with CLEANUP_LOCK:
        if not force and now - LAST_CLEANUP_AT < CLEANUP_INTERVAL_SECONDS:
            return
        LAST_CLEANUP_AT = now

    cleanup_single_results()
    cleanup_old_jobs()
    cleanup_old_text_jobs()
    cleanup_expired_audio_files(get_settings().get("temp_file_ttl_hours", 6) * 60 * 60)

def public_user(user):
    if not user:
        return None
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "active": bool(user["active"]),
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
        "last_login_at": user.get("last_login_at"),
    }

def user_can_access_job(user, job):
    return bool(
        user
        and (
            user.get("role") == "admin"
            or job.get("owner_id") == user.get("id")
        )
    )

@app.before_request
def cleanup_before_request():
    g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    g.request_started_at = time.time()
    run_periodic_cleanup()

@app.after_request
def log_request(response):
    duration_ms = round((time.time() - getattr(g, "request_started_at", time.time())) * 1000)
    response.headers["X-Request-ID"] = getattr(g, "request_id", "-")
    app.logger.info(
        "request request_id=%s method=%s path=%s status=%s duration_ms=%s",
        getattr(g, "request_id", "-"),
        request.method,
        request.path,
        response.status_code,
        duration_ms,
    )
    return response

def public_batch_job(job):
    """返回可暴露给前端的批量任务数据。"""
    recompute_batch_job_counts(job)
    now = time.time()
    elapsed_seconds = None
    if job.get("started_at"):
        elapsed_seconds = round(
            max((job.get("finished_at") or now) - job["started_at"], 0),
            1,
        )
    return {
        "id": job["id"],
        "status": job["status"],
        "voice": job["voice"],
        "speech_rate": job["speech_rate"],
        "volume": job.get("volume", DEFAULT_VOLUME),
        "pitch": job.get("pitch", DEFAULT_PITCH),
        "total": job["total"],
        "completed": job["completed"],
        "success_count": job["success_count"],
        "failed_count": job["failed_count"],
        "cancelled_count": job.get("cancelled_count", 0),
        "cancel_requested": job.get("cancel_requested", False),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "elapsed_seconds": elapsed_seconds,
        "estimated_remaining_seconds": estimate_remaining_seconds(job),
        "queue_position": task_queue_position(job),
        "items": [public_task_item(item, "batch", job) for item in job["items"]],
    }

def update_batch_job(job_id, updater):
    """线程安全地更新批量任务。"""
    with BATCH_LOCK:
        job = BATCH_JOBS.get(job_id)
        if not job:
            return None
        updater(job)
        recompute_batch_job_counts(job)
        job["updated_at"] = time.time()
        get_repository().save_job("batch", job)
        return job.copy()

def process_batch_job(job_id, only_item_id=None):
    """后台顺序处理批量语音任务，也可仅重试一个失败项。"""
    app.logger.info("batch_job_started job_id=%s retry_item=%s", job_id, only_item_id or "-")
    def mark_processing(job):
        job["status"] = "processing"
        job["finished_at"] = None
        if not job.get("started_at"):
            job["started_at"] = time.time()

    update_batch_job(job_id, mark_processing)

    with BATCH_LOCK:
        job = BATCH_JOBS.get(job_id)
        if not job:
            return
        target_item_ids = [
            item["id"]
            for item in job["items"]
            if (only_item_id is None or item["id"] == only_item_id)
            and item.get("status") in ("pending", "failed", "cancelled")
        ]

    for item_id in target_item_ids:
        with BATCH_LOCK:
            job = BATCH_JOBS.get(job_id)
            if not job:
                return
            if job.get("cancel_requested"):
                for item in job["items"]:
                    if item.get("status") in ("pending", "processing"):
                        item["status"] = "cancelled"
                        item["error"] = "任务已取消。"
                job["status"] = "cancelled"
                job["finished_at"] = time.time()
                recompute_batch_job_counts(job)
                job["updated_at"] = time.time()
                get_repository().save_job("batch", job)
                return
            current_item = next(
                (item for item in job["items"] if item["id"] == item_id),
                None,
            )
            if not current_item:
                continue
            text = current_item.get("text", "")
            voice = job["voice"]
            speech_rate = job["speech_rate"]
            volume = job.get("volume", DEFAULT_VOLUME)
            pitch = job.get("pitch", DEFAULT_PITCH)

        def mark_item_processing(job):
            for item in job["items"]:
                if item["id"] == item_id:
                    item["status"] = "processing"
                    item["error"] = None
                    item["attempts"] = item.get("attempts", 0) + 1
                    item["started_at"] = time.time()
                    item["finished_at"] = None
                    item["elapsed_seconds"] = None
                    break

        update_batch_job(job_id, mark_item_processing)

        try:
            audio_path = generate_speech_with_retries(
                text,
                voice,
                speech_rate,
                volume,
                pitch,
            )
            file_size = os.path.getsize(audio_path)

            def mark_item_done(job):
                for item in job["items"]:
                    if item["id"] == item_id:
                        unlink_audio_file(item.get("audio_path"))
                        item["status"] = "done"
                        item["audio_path"] = audio_path
                        item["size"] = file_size
                        item["error"] = None
                        item["elapsed_seconds"] = round(
                            max(time.time() - item.get("started_at", time.time()), 0),
                            1,
                        )
                        item["finished_at"] = time.time()
                        break

            update_batch_job(job_id, mark_item_done)
        except Exception as e:
            error_msg = str(e)

            def mark_item_failed(job):
                for item in job["items"]:
                    if item["id"] == item_id:
                        item["status"] = "failed"
                        item["error"] = error_msg
                        item["elapsed_seconds"] = round(
                            max(time.time() - item.get("started_at", time.time()), 0),
                            1,
                        )
                        item["finished_at"] = time.time()
                        break

            update_batch_job(job_id, mark_item_failed)

    def mark_finished(job):
        if job.get("cancel_requested"):
            job["status"] = "cancelled"
        else:
            job["status"] = "finished"
        job["finished_at"] = time.time()

    update_batch_job(job_id, mark_finished)
    with BATCH_LOCK:
        finished_job = BATCH_JOBS.get(job_id)
        if finished_job:
            app.logger.info(
                "batch_job_finished job_id=%s status=%s success=%s failed=%s elapsed_seconds=%s",
                job_id,
                finished_job["status"],
                finished_job.get("success_count", 0),
                finished_job.get("failed_count", 0),
                round(max(
                    finished_job.get("finished_at", time.time())
                    - finished_job.get("started_at", time.time()),
                    0,
                ), 1),
            )

@app.route('/')
def index():
    return render_template(
        'index.html',
        settings=settings_for_user(g.current_user),
        app_name=APP_NAME,
        app_version=APP_VERSION,
        max_text_length=MAX_TEXT_LENGTH,
        max_batch_files=MAX_BATCH_FILES,
        current_user=public_user(g.current_user),
    )

@app.route('/convert', methods=['POST'])
def convert():
    run_periodic_cleanup()

    text = request.form.get('text', '')
    if not text:
        return error_response("empty_text", "请输入要转换的文本。", 400)
    
    if len(text) > MAX_TEXT_LENGTH:
        return error_response("text_too_long", f"文本过长，最多支持 {MAX_TEXT_LENGTH} 字符。", 400)

    try:
        voice = validate_voice_id(request.form.get('voice') or get_settings().get("default_voice"))
    except ValueError as e:
        return error_response("invalid_voice", str(e), 400)

    try:
        speech_rate = normalize_speech_rate(request.form.get('speech_rate') or get_settings().get("default_speech_rate"))
    except ValueError as e:
        return error_response("invalid_speech_rate", str(e), 400)
    try:
        volume = normalize_volume(request.form.get('volume') or get_settings().get("default_volume"))
        pitch = normalize_pitch(
            request.form.get('pitch')
            if request.form.get('pitch') is not None
            else get_settings().get("default_pitch")
        )
    except ValueError as e:
        return error_response("invalid_voice_parameter", str(e), 400)
    
    # 检查网络连接
    if not check_network_connectivity():
        return error_response("network_unavailable", "网络连接异常，无法连接到语音服务。请检查网络连接后重试。", 503)

    try:
        job = create_text_job(
            text,
            voice,
            speech_rate,
            volume,
            pitch,
            owner_id=g.current_user["id"],
        )
        app.logger.info(
            "text_job_created job_id=%s owner_id=%s voice=%s text_length=%s chunks=%s",
            job["id"],
            g.current_user["id"],
            voice,
            len(text),
            job["total"],
        )
        remember_recent_voice(voice)
        response_data = public_text_job(job)
        JOB_EXECUTOR.submit(process_text_job, job["id"])
        return jsonify(response_data), 202
    except Exception as e:
        error_msg = error_message_from_exception(e)
        return error_response(
            "text_job_create_failed",
            error_msg,
            get_error_status_code(error_msg),
            detail={"attempts": MAX_RETRIES}
        )

def public_task(job, kind, owner_names=None):
    data = public_text_job(job) if kind == "text" else public_batch_job(job)
    data["kind"] = kind
    data["title"] = (
        job.get("download_name") or job.get("text_summary") or "文本任务"
        if kind == "text"
        else f"批量任务 · {job.get('total', 0)} 个文件"
    )
    if owner_names is not None:
        data["owner_id"] = job.get("owner_id")
        data["owner_name"] = owner_names.get(job.get("owner_id"), "未知用户")
    return data

@app.route('/tasks')
def task_list():
    status_filter = str(request.args.get("status") or "").strip()
    kind_filter = str(request.args.get("kind") or "").strip()
    limit = normalize_int(request.args.get("limit"), 50, 1, 200)
    is_admin = g.current_user.get("role") == "admin"
    owner_names = None
    if is_admin:
        owner_names = {
            user["id"]: user["username"]
            for user in get_repository().list_users()
        }

    with TEXT_JOB_LOCK:
        text_jobs = [job.copy() for job in TEXT_JOBS.values()]
    with BATCH_LOCK:
        batch_jobs = [job.copy() for job in BATCH_JOBS.values()]

    tasks = []
    for kind, jobs in (("text", text_jobs), ("batch", batch_jobs)):
        if kind_filter and kind_filter != kind:
            continue
        for job in jobs:
            if not user_can_access_job(g.current_user, job):
                continue
            if status_filter and job.get("status") != status_filter:
                continue
            tasks.append(public_task(job, kind, owner_names))
    tasks.sort(key=lambda task: task.get("created_at", 0), reverse=True)
    return jsonify(tasks[:limit])

@app.route('/tasks/<kind>/<job_id>', methods=['DELETE'])
def delete_task(kind, job_id):
    if kind == "text":
        lock = TEXT_JOB_LOCK
        jobs = TEXT_JOBS
        cleanup = cleanup_text_job_files
    elif kind == "batch":
        lock = BATCH_LOCK
        jobs = BATCH_JOBS
        cleanup = cleanup_job_files
    else:
        return error_response("invalid_task_kind", "任务类型无效。", 400)

    with lock:
        job = jobs.get(job_id)
        if not job:
            return error_response("task_not_found", "任务不存在或已过期。", 404)
        if not user_can_access_job(g.current_user, job):
            return error_response("job_access_denied", "无权访问此任务。", 403)
        if job.get("status") in ("queued", "processing"):
            return error_response("task_processing", "任务仍在队列或处理中，暂时不能删除。", 409)
        job = jobs.pop(job_id)
    cleanup(job)
    get_repository().delete_job(job_id)
    return jsonify({"deleted": True})

@app.route('/jobs/<job_id>')
def text_job_status(job_id):
    with TEXT_JOB_LOCK:
        job = TEXT_JOBS.get(job_id)
        if not job:
            return error_response("text_job_not_found", "文本任务不存在或已过期。", 404)
        if not user_can_access_job(g.current_user, job):
            return error_response("job_access_denied", "无权访问此文本任务。", 403)
        data = public_text_job(job)

    return jsonify(data)

@app.route('/jobs/<job_id>/cancel', methods=['POST'])
def text_job_cancel(job_id):
    with TEXT_JOB_LOCK:
        existing_job = TEXT_JOBS.get(job_id)
        if existing_job and not user_can_access_job(g.current_user, existing_job):
            return error_response("job_access_denied", "无权访问此文本任务。", 403)

    def request_cancel(job):
        if job.get("status") in ("finished", "cancelled"):
            return
        job["cancel_requested"] = True
        if job.get("status") == "queued":
            mark_remaining_text_items_cancelled(job)
            job["status"] = "cancelled"
            job["finished_at"] = time.time()

    job = update_text_job(job_id, request_cancel)
    if not job:
        return error_response("text_job_not_found", "文本任务不存在或已过期。", 404)

    save_user_state()
    return jsonify(public_text_job(job))

@app.route('/jobs/<job_id>/items/<item_id>/retry', methods=['POST'])
def text_job_retry_item(job_id, item_id):
    with TEXT_JOB_LOCK:
        job = TEXT_JOBS.get(job_id)
        if not job:
            return error_response("text_job_not_found", "文本任务不存在或已过期。", 404)
        if not user_can_access_job(g.current_user, job):
            return error_response("job_access_denied", "无权访问此文本任务。", 403)
        if job.get("status") == "processing":
            return error_response("text_job_processing", "文本任务仍在处理中，请稍后再重试失败片段。", 409)
        item = next((candidate for candidate in job["items"] if candidate["id"] == item_id), None)
        if not item:
            return error_response("text_job_item_not_found", "文本片段不存在或已过期。", 404)
        if item.get("status") not in ("failed", "cancelled"):
            return error_response("text_job_item_not_retryable", "只有失败或取消的片段可以重试。", 400)
        job["cancel_requested"] = False
        item["status"] = "pending"
        item["error"] = None
        recompute_text_job_counts(job)
        job["status"] = "queued"
        job["finished_at"] = None
        job["updated_at"] = time.time()
        response_data = public_text_job(job)

    save_user_state()
    JOB_EXECUTOR.submit(process_text_job, job_id, item_id)
    return jsonify(response_data), 202

@app.route('/jobs/<job_id>/download')
def text_job_download(job_id):
    with TEXT_JOB_LOCK:
        job = TEXT_JOBS.get(job_id)
        if not job:
            return error_response("text_job_not_found", "文本任务不存在或已过期。", 404)
        if not user_can_access_job(g.current_user, job):
            return error_response("job_access_denied", "无权访问此文本任务。", 403)
        default_download_name = job.get("download_name") or "speech"

    try:
        audio_path, temporary_merged = text_job_audio_path(job)
    except ValueError:
        return error_response("no_downloadable_audio", "没有可下载的音频文件。", 404)

    requested_name = request.args.get("name") or default_download_name
    safe_name = sanitize_download_name(requested_name, default_download_name)

    download_name = safe_name
    if download_name.lower().endswith(".zip"):
        download_name = download_name[:-4]
    if not download_name.lower().endswith(".mp3"):
        download_name = f"{download_name}.mp3"

    response = send_file(
        audio_path,
        as_attachment=True,
        download_name=download_name,
        mimetype='audio/mpeg',
    )
    if temporary_merged:
        response.call_on_close(lambda: unlink_audio_file(audio_path))
    return response

@app.route('/jobs/<job_id>/save', methods=['POST'])
def text_job_save_to_directory(job_id):
    with TEXT_JOB_LOCK:
        job = TEXT_JOBS.get(job_id)
        if not job:
            return error_response("text_job_not_found", "文本任务不存在或已过期。", 404)
        if not user_can_access_job(g.current_user, job):
            return error_response("job_access_denied", "无权访问此文本任务。", 403)
        job_snapshot = job.copy()
        job_snapshot["items"] = [item.copy() for item in job["items"]]
    temporary_merged = False
    source_path = None
    try:
        directory = configured_save_directory()
        source_path, temporary_merged = text_job_audio_path(job_snapshot)
        data = request.get_json(silent=True) or {}
        filename = sanitize_download_name(
            data.get("name") or job_snapshot.get("download_name"),
            "speech",
        )
        if not filename.lower().endswith(".mp3"):
            filename += ".mp3"
        target_path = unique_output_path(directory, filename)
        shutil.copyfile(source_path, target_path)
    except (OSError, ValueError) as error:
        return error_response("save_to_directory_failed", f"保存失败：{error}", 400)
    finally:
        if temporary_merged and source_path:
            unlink_audio_file(source_path)
    app.logger.info(
        "text_job_saved job_id=%s owner_id=%s filename=%s",
        job_id,
        g.current_user["id"],
        os.path.basename(target_path),
    )
    return jsonify({"saved": True, "path": target_path})

@app.route('/jobs/<job_id>/items/<item_id>/audio')
def text_job_item_audio(job_id, item_id):
    with TEXT_JOB_LOCK:
        job = TEXT_JOBS.get(job_id)
        if not job:
            return error_response("text_job_not_found", "文本任务不存在或已过期。", 404)
        if not user_can_access_job(g.current_user, job):
            return error_response("job_access_denied", "无权访问此文本任务。", 403)
        item = next((candidate.copy() for candidate in job["items"] if candidate["id"] == item_id), None)

    if not item or item.get("status") != "done":
        return error_response("audio_not_ready", "音频文件尚未生成或已不可用。", 404)

    audio_path = item.get("audio_path")
    if not audio_path or not is_managed_audio_path(audio_path) or not os.path.exists(audio_path):
        return error_response("audio_file_missing", "音频文件不存在或已过期。", 404)

    return send_file(audio_path, mimetype='audio/mpeg')

@app.route('/history')
def history_list():
    return jsonify(public_history_items(g.current_user))

@app.route('/history/<history_id>', methods=['DELETE'])
def history_delete(history_id):
    with HISTORY_LOCK:
        target = next((item for item in HISTORY_ITEMS if item["id"] == history_id), None)
        if (
            target
            and g.current_user.get("role") != "admin"
            and target.get("owner_id") != g.current_user.get("id")
        ):
            return error_response("history_access_denied", "无权删除此历史记录。", 403)
        before_count = len(HISTORY_ITEMS)
        HISTORY_ITEMS[:] = [item for item in HISTORY_ITEMS if item["id"] != history_id]
        deleted = len(HISTORY_ITEMS) != before_count

    if not deleted:
        return error_response("history_item_not_found", "历史记录不存在。", 404)
    save_user_state()
    return jsonify({"deleted": True})

@app.route('/batch/convert', methods=['POST'])
def batch_convert():
    run_periodic_cleanup(force=True)

    try:
        voice = validate_voice_id(request.form.get('voice') or get_settings().get("default_voice"))
    except ValueError as e:
        return error_response("invalid_voice", str(e), 400)

    try:
        speech_rate = normalize_speech_rate(request.form.get('speech_rate') or get_settings().get("default_speech_rate"))
    except ValueError as e:
        return error_response("invalid_speech_rate", str(e), 400)
    try:
        volume = normalize_volume(request.form.get('volume') or get_settings().get("default_volume"))
        pitch = normalize_pitch(
            request.form.get('pitch')
            if request.form.get('pitch') is not None
            else get_settings().get("default_pitch")
        )
    except ValueError as e:
        return error_response("invalid_voice_parameter", str(e), 400)

    if not check_network_connectivity():
        return error_response("network_unavailable", "网络连接异常，无法连接到语音服务。请检查网络连接后重试。", 503)

    files = request.files.getlist('files')

    if not files:
        return error_response("no_files", "请选择至少一个 TXT 文件。", 400)

    if len(files) > MAX_BATCH_FILES:
        return error_response("too_many_files", f"一次最多上传 {MAX_BATCH_FILES} 个 TXT 文件。", 400)

    now = time.time()
    items = []
    used_download_names = set()

    for uploaded_file in files:
        source_name = sanitize_download_name(uploaded_file.filename, "未命名.txt")
        if not source_name.lower().endswith(".txt"):
            return error_response("invalid_file_type", f"{source_name} 不是 TXT 文件。", 400)

        raw_content = uploaded_file.read()
        if not raw_content:
            return error_response("empty_file", f"{source_name} 是空文件。", 400)

        try:
            text = decode_text_file(raw_content).strip()
        except ValueError as e:
            return error_response("unsupported_file_encoding", f"{source_name}: {str(e)}", 400)

        if not text:
            return error_response("empty_file_text", f"{source_name} 没有可转换的文本内容。", 400)

        if len(text) > MAX_BATCH_TEXT_LENGTH:
            return error_response("file_text_too_long", f"{source_name} 超过 {MAX_BATCH_TEXT_LENGTH} 字符限制。", 400)

        item_id = uuid.uuid4().hex
        download_name = mp3_name_from_txt(source_name, used_download_names)

        items.append({
            "id": item_id,
            "index": len(items) + 1,
            "source_name": source_name,
            "download_name": download_name,
            "text": text,
            "status": "pending",
            "text_length": len(text),
            "size": 0,
            "error": None,
            "audio_path": None,
            "attempts": 0,
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "elapsed_seconds": None,
        })

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "owner_id": g.current_user["id"],
        "status": "queued",
        "voice": voice,
        "speech_rate": speech_rate,
        "volume": volume,
        "pitch": pitch,
        "total": len(items),
        "completed": 0,
        "success_count": 0,
        "failed_count": 0,
        "cancelled_count": 0,
        "cancel_requested": False,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
        "items": items,
    }
    recompute_batch_job_counts(job)

    with BATCH_LOCK:
        BATCH_JOBS[job_id] = job
        get_repository().save_job("batch", job)
    app.logger.info(
        "batch_job_created job_id=%s owner_id=%s voice=%s files=%s",
        job_id,
        g.current_user["id"],
        voice,
        len(items),
    )

    response_data = public_batch_job(job)
    JOB_EXECUTOR.submit(process_batch_job, job_id)

    return jsonify(response_data), 202

@app.route('/batch/status/<job_id>')
def batch_status(job_id):
    with BATCH_LOCK:
        job = BATCH_JOBS.get(job_id)
        if not job:
            return error_response("batch_job_not_found", "批量任务不存在或已过期。", 404)
        if not user_can_access_job(g.current_user, job):
            return error_response("job_access_denied", "无权访问此批量任务。", 403)
        data = public_batch_job(job)

    return jsonify(data)

@app.route('/batch/job/<job_id>/cancel', methods=['POST'])
def batch_cancel(job_id):
    with BATCH_LOCK:
        existing_job = BATCH_JOBS.get(job_id)
        if existing_job and not user_can_access_job(g.current_user, existing_job):
            return error_response("job_access_denied", "无权访问此批量任务。", 403)

    def request_cancel(job):
        if job.get("status") in ("finished", "cancelled"):
            return
        job["cancel_requested"] = True
        if job.get("status") == "queued":
            for item in job["items"]:
                if item.get("status") in ("pending", "processing"):
                    item["status"] = "cancelled"
                    item["error"] = "任务已取消。"
            job["status"] = "cancelled"
            job["finished_at"] = time.time()

    job = update_batch_job(job_id, request_cancel)
    if not job:
        return error_response("batch_job_not_found", "批量任务不存在或已过期。", 404)
    return jsonify(public_batch_job(job))

@app.route('/batch/job/<job_id>/items/<item_id>/retry', methods=['POST'])
def batch_retry_item(job_id, item_id):
    with BATCH_LOCK:
        job = BATCH_JOBS.get(job_id)
        if not job:
            return error_response("batch_job_not_found", "批量任务不存在或已过期。", 404)
        if not user_can_access_job(g.current_user, job):
            return error_response("job_access_denied", "无权访问此批量任务。", 403)
        if job.get("status") == "processing":
            return error_response("batch_job_processing", "批量任务仍在处理中，请稍后重试。", 409)
        item = next((candidate for candidate in job["items"] if candidate["id"] == item_id), None)
        if not item:
            return error_response("batch_item_not_found", "批量任务文件不存在或已过期。", 404)
        if item.get("status") not in ("failed", "cancelled"):
            return error_response("batch_item_not_retryable", "只有失败或取消的文件可以重试。", 400)
        job["cancel_requested"] = False
        item["status"] = "pending"
        item["error"] = None
        job["status"] = "queued"
        job["finished_at"] = None
        recompute_batch_job_counts(job)
        job["updated_at"] = time.time()
        get_repository().save_job("batch", job)
        response_data = public_batch_job(job)

    JOB_EXECUTOR.submit(process_batch_job, job_id, item_id)
    return jsonify(response_data), 202

@app.route('/batch/download/<job_id>')
def batch_download(job_id):
    with BATCH_LOCK:
        job = BATCH_JOBS.get(job_id)
        if not job:
            return error_response("batch_job_not_found", "批量任务不存在或已过期。", 404)
        if not user_can_access_job(g.current_user, job):
            return error_response("job_access_denied", "无权访问此批量任务。", 403)
        done_items = [
            item.copy()
            for item in job["items"]
            if item.get("status") == "done"
            and item.get("audio_path")
            and is_managed_audio_path(item["audio_path"])
            and os.path.exists(item["audio_path"])
        ]

    if not done_items:
        return error_response("no_downloadable_audio", "没有可下载的音频文件。", 404)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for item in done_items:
            zip_file.write(item["audio_path"], arcname=item["download_name"])
    zip_buffer.seek(0)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        zip_buffer,
        as_attachment=True,
        download_name=f'edge_tts_batch_{timestamp}.zip',
        mimetype='application/zip'
    )

@app.route('/batch/job/<job_id>/save', methods=['POST'])
def batch_save_to_directory(job_id):
    with BATCH_LOCK:
        job = BATCH_JOBS.get(job_id)
        if not job:
            return error_response("batch_job_not_found", "批量任务不存在或已过期。", 404)
        if not user_can_access_job(g.current_user, job):
            return error_response("job_access_denied", "无权访问此批量任务。", 403)
        done_items = [
            item.copy()
            for item in job["items"]
            if item.get("status") == "done"
            and item.get("audio_path")
            and is_managed_audio_path(item["audio_path"])
            and os.path.exists(item["audio_path"])
        ]
    if not done_items:
        return error_response("no_downloadable_audio", "没有可保存的音频文件。", 404)
    try:
        directory = configured_save_directory()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        target_path = unique_output_path(directory, f"edge_tts_batch_{timestamp}.zip")
        with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for item in done_items:
                zip_file.write(item["audio_path"], arcname=item["download_name"])
    except (OSError, ValueError) as error:
        return error_response("save_to_directory_failed", f"保存失败：{error}", 400)
    app.logger.info(
        "batch_job_saved job_id=%s owner_id=%s filename=%s",
        job_id,
        g.current_user["id"],
        os.path.basename(target_path),
    )
    return jsonify({"saved": True, "path": target_path})

@app.route('/batch/download/<job_id>/<item_id>')
def batch_download_item(job_id, item_id):
    with BATCH_LOCK:
        job = BATCH_JOBS.get(job_id)
        if not job:
            return error_response("batch_job_not_found", "批量任务不存在或已过期。", 404)
        if not user_can_access_job(g.current_user, job):
            return error_response("job_access_denied", "无权访问此批量任务。", 403)

        item = next((current_item.copy() for current_item in job["items"] if current_item["id"] == item_id), None)

    if not item or item.get("status") != "done":
        return error_response("audio_not_ready", "音频文件尚未生成或已不可用。", 404)

    audio_path = item.get("audio_path")
    if not audio_path or not is_managed_audio_path(audio_path) or not os.path.exists(audio_path):
        return error_response("audio_file_missing", "音频文件不存在或已过期。", 404)

    return send_file(
        audio_path,
        as_attachment=True,
        download_name=item["download_name"],
        mimetype='audio/mpeg'
    )

@app.route('/batch/job/<job_id>', methods=['DELETE'])
def batch_delete_job(job_id):
    with BATCH_LOCK:
        job = BATCH_JOBS.get(job_id)
        if job and not user_can_access_job(g.current_user, job):
            return error_response("job_access_denied", "无权访问此批量任务。", 403)
        if job and job.get("status") in ("queued", "processing"):
            return error_response("batch_job_processing", "批量任务仍在处理中，暂时不能清理。", 409)
        job = BATCH_JOBS.pop(job_id, None)

    if not job:
        return error_response("batch_job_not_found", "批量任务不存在或已过期。", 404)

    cleanup_job_files(job)
    get_repository().delete_job(job_id)
    return jsonify({'deleted': True})

@app.route('/download/<file_id>')
def download(file_id):
    result = get_single_result(file_id)
    if not result:
        return error_response("audio_result_not_found", "音频文件不存在或已过期。", 404)
    if g.current_user.get("role") != "admin" and result.get("owner_id") != g.current_user.get("id"):
        return error_response("audio_access_denied", "无权访问此音频。", 403)

    if time.time() > result["expires_at"]:
        cleanup_single_results()
        return error_response("audio_result_expired", "音频文件已过期，请重新转换。", 404)

    audio_path = result.get("audio_path")
    if not audio_path or not is_managed_audio_path(audio_path) or not os.path.exists(audio_path):
        return error_response("audio_file_missing", "音频文件不存在或已过期。", 404)

    requested_name = request.args.get('name') or result.get("download_name") or "speech.mp3"
    download_name = sanitize_download_name(requested_name, "speech.mp3")

    return send_file(
        audio_path,
        as_attachment=True,
        download_name=download_name,
        mimetype='audio/mpeg'
    )

@app.route('/download')
def download_requires_token():
    return error_response("download_token_required", "下载链接已过期或格式不正确，请重新转换。", 404)

register_auth_routes(
    app,
    get_repository,
    error_response,
    public_user,
    APP_NAME,
    APP_VERSION,
)
configure_secret_key()
configure_logging()
load_voice_cache()
load_settings()
load_user_state()

if __name__ == '__main__':
    run_periodic_cleanup(force=True)
    app.run(debug=True, port=5013) 
