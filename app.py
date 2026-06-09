from flask import Flask, render_template, request, send_file, jsonify
import io
import json
import os
import re
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime
import time
import socket
from urllib.parse import urlparse

app = Flask(__name__)

APP_VERSION = "0.6"
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
DEFAULT_SPEECH_RATE = "1.0"
SPEECH_RATE_OPTIONS = {
    "0.75": "-25%",
    "0.9": "-10%",
    "1.0": "+0%",
    "1.1": "+10%",
    "1.25": "+25%",
    "1.5": "+50%",
    "2.0": "+100%",
}
BATCH_JOB_TTL_SECONDS = 6 * 60 * 60
BATCH_JOBS = {}
BATCH_LOCK = threading.Lock()
TEXT_JOB_TTL_SECONDS = 6 * 60 * 60
TEXT_JOBS = {}
TEXT_JOB_LOCK = threading.Lock()
HISTORY_LIMIT = 50
HISTORY_ITEMS = []
HISTORY_LOCK = threading.Lock()
USER_PREFERENCES = {
    "favorite_voices": [],
    "recent_voices": [],
}
PREFERENCES_LOCK = threading.Lock()
SINGLE_RESULTS = {}
SINGLE_RESULTS_LOCK = threading.Lock()
CLEANUP_LOCK = threading.Lock()
LAST_CLEANUP_AT = 0
SETTINGS_LOCK = threading.Lock()
DEFAULT_SETTINGS = {
    "default_voice": "zh-CN-XiaoxiaoNeural",
    "default_speech_rate": DEFAULT_SPEECH_RATE,
    "proxy_url": "",
    "history_retention_days": 7,
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
AVAILABLE_VOICE_IDS = {voice["id"] for voice in AVAILABLE_VOICES}
VOICE_PRESETS = [
    {
        "id": "short_video",
        "name": "短视频口播",
        "voice": "zh-CN-YunxiNeural",
        "speech_rate": "1.1",
    },
    {
        "id": "news",
        "name": "新闻播报",
        "voice": "zh-CN-YunyangNeural",
        "speech_rate": "1.0",
    },
    {
        "id": "story",
        "name": "小说旁白",
        "voice": "zh-CN-XiaoxiaoNeural",
        "speech_rate": "0.9",
    },
    {
        "id": "kids",
        "name": "儿童故事",
        "voice": "zh-CN-XiaoyiNeural",
        "speech_rate": "0.9",
    },
    {
        "id": "cantonese",
        "name": "粤语口播",
        "voice": "zh-HK-HiuGaaiNeural",
        "speech_rate": "1.0",
    },
]

def error_response(code, message, status_code=400, detail=None):
    """返回统一的 API 错误格式。"""
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
    settings["proxy_url"] = str(settings.get("proxy_url") or "").strip()
    settings["history_retention_days"] = normalize_int(settings.get("history_retention_days"), 7, 1, 365)
    settings["temp_file_ttl_hours"] = normalize_int(settings.get("temp_file_ttl_hours"), 6, 1, 168)
    settings["default_save_dir"] = str(settings.get("default_save_dir") or "").strip()
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
    settings_path = get_settings_path()
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)

    with SETTINGS_LOCK:
        APP_SETTINGS = normalized_settings
        with open(settings_path, "w", encoding="utf-8") as settings_file:
            json.dump(APP_SETTINGS, settings_file, ensure_ascii=False, indent=2)
        return APP_SETTINGS.copy()

def get_settings():
    with SETTINGS_LOCK:
        return APP_SETTINGS.copy()

def validate_voice_id(voice_id):
    """校验音色 ID 是否在当前白名单中。"""
    normalized_voice_id = (voice_id or "zh-CN-XiaoxiaoNeural").strip()
    if normalized_voice_id not in AVAILABLE_VOICE_IDS:
        raise ValueError("不支持的语音角色，请从列表中选择可用音色。")
    return normalized_voice_id

def voice_by_id(voice_id):
    return next((voice for voice in AVAILABLE_VOICES if voice["id"] == voice_id), None)

def remember_recent_voice(voice_id):
    """记录最近使用音色。"""
    if voice_id not in AVAILABLE_VOICE_IDS:
        return
    with PREFERENCES_LOCK:
        recent = [current for current in USER_PREFERENCES["recent_voices"] if current != voice_id]
        recent.insert(0, voice_id)
        USER_PREFERENCES["recent_voices"] = recent[:8]

def public_preferences():
    with PREFERENCES_LOCK:
        return {
            "favorite_voices": list(USER_PREFERENCES["favorite_voices"]),
            "recent_voices": list(USER_PREFERENCES["recent_voices"]),
        }

def set_favorite_voice(voice_id, favorite):
    validate_voice_id(voice_id)
    with PREFERENCES_LOCK:
        favorites = [current for current in USER_PREFERENCES["favorite_voices"] if current != voice_id]
        if favorite:
            favorites.insert(0, voice_id)
        USER_PREFERENCES["favorite_voices"] = favorites
        return {
            "favorite_voices": list(USER_PREFERENCES["favorite_voices"]),
            "recent_voices": list(USER_PREFERENCES["recent_voices"]),
        }

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
        "title": job.get("download_name") or "speech",
        "summary": job.get("text_summary") or "",
        "voice": job["voice"],
        "speech_rate": job["speech_rate"],
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

def public_history_items():
    with HISTORY_LOCK:
        cleanup_history_items_locked()
        return [item.copy() for item in HISTORY_ITEMS]

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

def register_single_result(audio_path, download_name):
    """登记单条转换结果，返回给前端安全的文件 token。"""
    file_id = uuid.uuid4().hex
    safe_download_name = sanitize_download_name(download_name, "speech.mp3")
    now = time.time()

    with SINGLE_RESULTS_LOCK:
        SINGLE_RESULTS[file_id] = {
            "id": file_id,
            "audio_path": audio_path,
            "download_name": safe_download_name,
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
        "download_name": job["download_name"],
        "downloadable": job["success_count"] > 0,
        "cancel_requested": job.get("cancel_requested", False),
        "summary": job.get("text_summary", ""),
        "audio_url": first_text_job_audio_url(job),
        "items": [
            {
                "id": item["id"],
                "index": item["index"],
                "status": item["status"],
                "text_length": item["text_length"],
                "size": item.get("size", 0),
                "error": item.get("error"),
                "attempts": item.get("attempts", 0),
            }
            for item in job["items"]
        ],
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
        return job.copy()

def create_text_job(text, voice, speech_rate):
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
            "download_name": f"{download_name}_part_{index + 1:03d}.mp3",
        }
        for index, chunk in enumerate(chunks)
    ]
    job = {
        "id": job_id,
        "status": "queued",
        "voice": voice,
        "speech_rate": speech_rate,
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
                return
            current_item = next((candidate for candidate in job["items"] if candidate["id"] == item["id"]), None)
            if not current_item:
                continue
            current_item["status"] = "processing"
            current_item["error"] = None
            current_item["attempts"] = current_item.get("attempts", 0) + 1
            job["updated_at"] = time.time()

        try:
            audio_path = generate_speech_with_retries(
                item["text"],
                job["voice"],
                job["speech_rate"],
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
                recompute_text_job_counts(job)
                job["updated_at"] = time.time()
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
                recompute_text_job_counts(job)
                job["updated_at"] = time.time()

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
    if get_proxy_url():
        return True

    # 检查是否能连接到Microsoft Edge TTS服务
    return can_connect("speech.platform.bing.com", 443, timeout=10)

def collect_network_diagnostics():
    """返回代理和 Edge TTS 服务诊断信息。"""
    configured_proxy = get_configured_proxy_url()
    proxy_available = is_proxy_available(configured_proxy) if configured_proxy else False
    service_available = can_connect("speech.platform.bing.com", 443, timeout=10)
    effective_proxy = configured_proxy if proxy_available else ""

    return {
        "version": APP_VERSION,
        "proxy_configured": bool(configured_proxy),
        "proxy_url": configured_proxy,
        "proxy_available": proxy_available,
        "effective_proxy": effective_proxy,
        "edge_tts_host": "speech.platform.bing.com",
        "edge_tts_available": service_available,
        "network_connectivity": proxy_available or service_available,
        "settings_path": get_settings_path(),
        "temp_dir": get_app_temp_dir(),
    }

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

@app.route('/voices')
def get_voices():
    """获取可用的语音列表"""
    preferences = public_preferences()
    favorite_set = set(preferences["favorite_voices"])
    recent_set = set(preferences["recent_voices"])
    voices = [
        {
            **voice,
            "favorite": voice["id"] in favorite_set,
            "recent": voice["id"] in recent_set,
        }
        for voice in AVAILABLE_VOICES
    ]
    return jsonify(voices)

@app.route('/presets')
def get_presets():
    return jsonify(VOICE_PRESETS)

@app.route('/preferences')
def get_preferences():
    return jsonify(public_preferences())

@app.route('/preferences/favorites/<voice_id>', methods=['POST'])
def update_favorite_voice(voice_id):
    data = request.get_json(silent=True) or {}
    favorite = bool(data.get("favorite", True))
    try:
        preferences = set_favorite_voice(voice_id, favorite)
    except ValueError as e:
        return error_response("invalid_voice", str(e), 400)
    return jsonify(preferences)

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
    return jsonify(collect_network_diagnostics())

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'GET':
        return jsonify(get_settings())

    data = request.get_json(silent=True) or {}
    try:
        updated_settings = save_settings(data)
    except ValueError as e:
        return error_response("invalid_settings", str(e), 400)
    except OSError as e:
        return error_response("settings_save_failed", f"设置保存失败：{str(e)}", 500)

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

    if not check_network_connectivity():
        return error_response("network_unavailable", "网络连接异常，无法连接到语音服务。请检查网络连接后重试。", 503)

    preview_text = text[:PREVIEW_TEXT_LENGTH]
    try:
        audio_path = generate_speech_with_retries(preview_text, voice, speech_rate)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_id = register_single_result(audio_path, f"preview_{timestamp}.mp3")
        remember_recent_voice(voice)
        return jsonify({
            "file_id": file_id,
            "audio_url": f"/audio/{file_id}",
            "download_url": f"/download/{file_id}",
            "text_length": len(preview_text),
            "voice": voice,
            "speech_rate": speech_rate,
        })
    except Exception as e:
        error_msg = error_message_from_exception(e)
        return error_response("preview_generation_failed", error_msg, get_error_status_code(error_msg))

@app.route('/audio/<file_id>')
def preview_audio(file_id):
    result = get_single_result(file_id)
    if not result:
        return error_response("audio_result_not_found", "音频文件不存在或已过期。", 404)

    audio_path = result.get("audio_path")
    if not audio_path or not is_managed_audio_path(audio_path) or not os.path.exists(audio_path):
        return error_response("audio_file_missing", "音频文件不存在或已过期。", 404)

    return send_file(audio_path, mimetype='audio/mpeg')

def generate_speech(text, voice="zh-CN-XiaoxiaoNeural", speech_rate=DEFAULT_SPEECH_RATE):
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

def generate_speech_with_retries(text, voice, speech_rate=DEFAULT_SPEECH_RATE):
    """带重试的语音生成。"""
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            audio_path = generate_speech(text, voice, speech_rate)

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
    expired_jobs = []

    with BATCH_LOCK:
        for job_id, job in BATCH_JOBS.items():
            if job.get("status") != "processing" and now - job.get("created_at", now) > BATCH_JOB_TTL_SECONDS:
                expired_jobs.append((job_id, job))
        for job_id, _job in expired_jobs:
            BATCH_JOBS.pop(job_id, None)

    for _job_id, job in expired_jobs:
        cleanup_job_files(job)

def cleanup_old_text_jobs():
    """清理过期的文本任务。"""
    now = time.time()
    expired_jobs = []

    with TEXT_JOB_LOCK:
        for job_id, job in list(TEXT_JOBS.items()):
            if job.get("status") != "processing" and now - job.get("created_at", now) > TEXT_JOB_TTL_SECONDS:
                expired_jobs.append((job_id, job))
        for job_id, _job in expired_jobs:
            TEXT_JOBS.pop(job_id, None)

    for _job_id, job in expired_jobs:
        cleanup_text_job_files(job)

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

@app.before_request
def cleanup_before_request():
    run_periodic_cleanup()

def public_batch_job(job):
    """返回可暴露给前端的批量任务数据。"""
    return {
        "id": job["id"],
        "status": job["status"],
        "voice": job["voice"],
        "speech_rate": job["speech_rate"],
        "total": job["total"],
        "completed": job["completed"],
        "success_count": job["success_count"],
        "failed_count": job["failed_count"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "items": [
            {
                "id": item["id"],
                "source_name": item["source_name"],
                "download_name": item["download_name"],
                "status": item["status"],
                "text_length": item["text_length"],
                "size": item.get("size", 0),
                "error": item.get("error"),
            }
            for item in job["items"]
        ],
    }

def update_batch_job(job_id, updater):
    """线程安全地更新批量任务。"""
    with BATCH_LOCK:
        job = BATCH_JOBS.get(job_id)
        if not job:
            return
        updater(job)
        job["updated_at"] = time.time()

def process_batch_job(job_id, prepared_files):
    """后台顺序处理批量语音任务。"""
    def mark_processing(job):
        job["status"] = "processing"

    update_batch_job(job_id, mark_processing)

    for prepared_file in prepared_files:
        item_id = prepared_file["id"]

        def mark_item_processing(job):
            for item in job["items"]:
                if item["id"] == item_id:
                    item["status"] = "processing"
                    item["error"] = None
                    break

        update_batch_job(job_id, mark_item_processing)

        try:
            audio_path = generate_speech_with_retries(
                prepared_file["text"],
                prepared_file["voice"],
                prepared_file["speech_rate"],
            )
            file_size = os.path.getsize(audio_path)

            def mark_item_done(job):
                job["completed"] += 1
                job["success_count"] += 1
                for item in job["items"]:
                    if item["id"] == item_id:
                        item["status"] = "done"
                        item["audio_path"] = audio_path
                        item["size"] = file_size
                        item["error"] = None
                        break

            update_batch_job(job_id, mark_item_done)
        except Exception as e:
            error_msg = str(e)

            def mark_item_failed(job):
                job["completed"] += 1
                job["failed_count"] += 1
                for item in job["items"]:
                    if item["id"] == item_id:
                        item["status"] = "failed"
                        item["error"] = error_msg
                        break

            update_batch_job(job_id, mark_item_failed)

    def mark_finished(job):
        job["status"] = "finished"

    update_batch_job(job_id, mark_finished)

@app.route('/')
def index():
    return render_template('index.html', settings=get_settings())

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
    
    # 检查网络连接
    if not check_network_connectivity():
        return error_response("network_unavailable", "网络连接异常，无法连接到语音服务。请检查网络连接后重试。", 503)

    try:
        job = create_text_job(text, voice, speech_rate)
        remember_recent_voice(voice)
        response_data = public_text_job(job)
        worker = threading.Thread(target=process_text_job, args=(job["id"],), daemon=True)
        worker.start()
        return jsonify(response_data), 202
    except Exception as e:
        error_msg = error_message_from_exception(e)
        return error_response(
            "text_job_create_failed",
            error_msg,
            get_error_status_code(error_msg),
            detail={"attempts": MAX_RETRIES}
        )

@app.route('/jobs/<job_id>')
def text_job_status(job_id):
    with TEXT_JOB_LOCK:
        job = TEXT_JOBS.get(job_id)
        if not job:
            return error_response("text_job_not_found", "文本任务不存在或已过期。", 404)
        data = public_text_job(job)

    return jsonify(data)

@app.route('/jobs/<job_id>/cancel', methods=['POST'])
def text_job_cancel(job_id):
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

    return jsonify(public_text_job(job))

@app.route('/jobs/<job_id>/items/<item_id>/retry', methods=['POST'])
def text_job_retry_item(job_id, item_id):
    with TEXT_JOB_LOCK:
        job = TEXT_JOBS.get(job_id)
        if not job:
            return error_response("text_job_not_found", "文本任务不存在或已过期。", 404)
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

    worker = threading.Thread(target=process_text_job, args=(job_id, item_id), daemon=True)
    worker.start()
    return jsonify(response_data), 202

@app.route('/jobs/<job_id>/download')
def text_job_download(job_id):
    with TEXT_JOB_LOCK:
        job = TEXT_JOBS.get(job_id)
        if not job:
            return error_response("text_job_not_found", "文本任务不存在或已过期。", 404)
        done_items = [
            item.copy()
            for item in sorted(job["items"], key=lambda current_item: current_item["index"])
            if item.get("status") == "done" and item.get("audio_path") and os.path.exists(item["audio_path"])
        ]
        default_download_name = job.get("download_name") or "speech"

    if not done_items:
        return error_response("no_downloadable_audio", "没有可下载的音频文件。", 404)

    requested_name = request.args.get("name") or default_download_name
    safe_name = sanitize_download_name(requested_name, default_download_name)

    if len(done_items) == 1:
        download_name = safe_name if safe_name.lower().endswith(".mp3") else f"{safe_name}.mp3"
        return send_file(
            done_items[0]["audio_path"],
            as_attachment=True,
            download_name=download_name,
            mimetype='audio/mpeg'
        )

    zip_name = safe_name if safe_name.lower().endswith(".zip") else f"{safe_name}.zip"
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for item in done_items:
            zip_file.write(item["audio_path"], arcname=item["download_name"])
    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        as_attachment=True,
        download_name=zip_name,
        mimetype='application/zip'
    )

@app.route('/jobs/<job_id>/items/<item_id>/audio')
def text_job_item_audio(job_id, item_id):
    with TEXT_JOB_LOCK:
        job = TEXT_JOBS.get(job_id)
        if not job:
            return error_response("text_job_not_found", "文本任务不存在或已过期。", 404)
        item = next((candidate.copy() for candidate in job["items"] if candidate["id"] == item_id), None)

    if not item or item.get("status") != "done":
        return error_response("audio_not_ready", "音频文件尚未生成或已不可用。", 404)

    audio_path = item.get("audio_path")
    if not audio_path or not is_managed_audio_path(audio_path) or not os.path.exists(audio_path):
        return error_response("audio_file_missing", "音频文件不存在或已过期。", 404)

    return send_file(audio_path, mimetype='audio/mpeg')

@app.route('/history')
def history_list():
    return jsonify(public_history_items())

@app.route('/history/<history_id>', methods=['DELETE'])
def history_delete(history_id):
    with HISTORY_LOCK:
        before_count = len(HISTORY_ITEMS)
        HISTORY_ITEMS[:] = [item for item in HISTORY_ITEMS if item["id"] != history_id]
        deleted = len(HISTORY_ITEMS) != before_count

    if not deleted:
        return error_response("history_item_not_found", "历史记录不存在。", 404)
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

    if not check_network_connectivity():
        return error_response("network_unavailable", "网络连接异常，无法连接到语音服务。请检查网络连接后重试。", 503)

    files = request.files.getlist('files')

    if not files:
        return error_response("no_files", "请选择至少一个 TXT 文件。", 400)

    if len(files) > MAX_BATCH_FILES:
        return error_response("too_many_files", f"一次最多上传 {MAX_BATCH_FILES} 个 TXT 文件。", 400)

    prepared_files = []
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

        prepared_files.append({
            "id": item_id,
            "text": text,
            "voice": voice,
            "speech_rate": speech_rate,
        })
        items.append({
            "id": item_id,
            "source_name": source_name,
            "download_name": download_name,
            "status": "pending",
            "text_length": len(text),
            "size": 0,
            "error": None,
            "audio_path": None,
        })

    job_id = uuid.uuid4().hex
    now = time.time()
    job = {
        "id": job_id,
        "status": "queued",
        "voice": voice,
        "speech_rate": speech_rate,
        "total": len(items),
        "completed": 0,
        "success_count": 0,
        "failed_count": 0,
        "created_at": now,
        "updated_at": now,
        "items": items,
    }

    with BATCH_LOCK:
        BATCH_JOBS[job_id] = job

    response_data = public_batch_job(job)
    worker = threading.Thread(target=process_batch_job, args=(job_id, prepared_files), daemon=True)
    worker.start()

    return jsonify(response_data), 202

@app.route('/batch/status/<job_id>')
def batch_status(job_id):
    with BATCH_LOCK:
        job = BATCH_JOBS.get(job_id)
        if not job:
            return error_response("batch_job_not_found", "批量任务不存在或已过期。", 404)
        data = public_batch_job(job)

    return jsonify(data)

@app.route('/batch/download/<job_id>')
def batch_download(job_id):
    with BATCH_LOCK:
        job = BATCH_JOBS.get(job_id)
        if not job:
            return error_response("batch_job_not_found", "批量任务不存在或已过期。", 404)
        done_items = [
            item.copy()
            for item in job["items"]
            if item.get("status") == "done" and item.get("audio_path") and os.path.exists(item["audio_path"])
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

@app.route('/batch/download/<job_id>/<item_id>')
def batch_download_item(job_id, item_id):
    with BATCH_LOCK:
        job = BATCH_JOBS.get(job_id)
        if not job:
            return error_response("batch_job_not_found", "批量任务不存在或已过期。", 404)

        item = next((current_item.copy() for current_item in job["items"] if current_item["id"] == item_id), None)

    if not item or item.get("status") != "done":
        return error_response("audio_not_ready", "音频文件尚未生成或已不可用。", 404)

    audio_path = item.get("audio_path")
    if not audio_path or not os.path.exists(audio_path):
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
        if job and job.get("status") == "processing":
            return error_response("batch_job_processing", "批量任务仍在处理中，暂时不能清理。", 409)
        job = BATCH_JOBS.pop(job_id, None)

    if not job:
        return error_response("batch_job_not_found", "批量任务不存在或已过期。", 404)

    cleanup_job_files(job)
    return jsonify({'deleted': True})

@app.route('/download/<file_id>')
def download(file_id):
    result = get_single_result(file_id)
    if not result:
        return error_response("audio_result_not_found", "音频文件不存在或已过期。", 404)

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

load_settings()

if __name__ == '__main__':
    run_periodic_cleanup(force=True)
    app.run(debug=True, port=5013) 
