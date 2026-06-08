from flask import Flask, render_template, request, send_file, jsonify
import io
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

APP_VERSION = "0.3"
MAX_TEXT_LENGTH = 20000
MAX_BATCH_FILES = 20
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
SINGLE_RESULTS = {}
SINGLE_RESULTS_LOCK = threading.Lock()
CLEANUP_LOCK = threading.Lock()
LAST_CLEANUP_AT = 0

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

def validate_voice_id(voice_id):
    """校验音色 ID 是否在当前白名单中。"""
    normalized_voice_id = (voice_id or "zh-CN-XiaoxiaoNeural").strip()
    if normalized_voice_id not in AVAILABLE_VOICE_IDS:
        raise ValueError("不支持的语音角色，请从列表中选择可用音色。")
    return normalized_voice_id

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
        os.environ.get("EDGE_TTS_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("http_proxy")
    )
    return proxy_url if is_proxy_available(proxy_url) else None

def check_network_connectivity():
    """检查网络连接状态"""
    if get_proxy_url():
        return True

    # 检查是否能连接到Microsoft Edge TTS服务
    return can_connect("speech.platform.bing.com", 443, timeout=10)

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
    return jsonify(AVAILABLE_VOICES)

@app.route('/health')
def health_check():
    """健康检查接口"""
    network_ok = check_network_connectivity()
    return jsonify({
        'version': APP_VERSION,
        'status': 'ok' if network_ok else 'network_error',
        'network_connectivity': network_ok,
        'message': '服务正常' if network_ok else '网络连接异常，可能无法使用语音转换功能'
    })

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
    cleanup_expired_audio_files()

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
    return render_template('index.html')

@app.route('/convert', methods=['POST'])
def convert():
    run_periodic_cleanup()

    text = request.form.get('text', '')
    if not text:
        return error_response("empty_text", "请输入要转换的文本。", 400)
    
    if len(text) > MAX_TEXT_LENGTH:
        return error_response("text_too_long", f"文本过长，最多支持 {MAX_TEXT_LENGTH} 字符。", 400)

    try:
        voice = validate_voice_id(request.form.get('voice', 'zh-CN-XiaoxiaoNeural'))
    except ValueError as e:
        return error_response("invalid_voice", str(e), 400)

    try:
        speech_rate = normalize_speech_rate(request.form.get('speech_rate', DEFAULT_SPEECH_RATE))
    except ValueError as e:
        return error_response("invalid_speech_rate", str(e), 400)
    
    # 检查网络连接
    if not check_network_connectivity():
        return error_response("network_unavailable", "网络连接异常，无法连接到语音服务。请检查网络连接后重试。", 503)
    
    try:
        audio_path = generate_speech_with_retries(text, voice, speech_rate)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        download_name = f'speech_{timestamp}.mp3'
        file_id = register_single_result(audio_path, download_name)

        return jsonify({
            'file_id': file_id,
            'download_name': download_name,
            'voice': voice,
            'speech_rate': speech_rate,
            'text_length': len(text)
        })
    except Exception as e:
        error_msg = error_message_from_exception(e)
        return error_response(
            "tts_generation_failed",
            error_msg,
            get_error_status_code(error_msg),
            detail={"attempts": MAX_RETRIES}
        )

@app.route('/batch/convert', methods=['POST'])
def batch_convert():
    run_periodic_cleanup(force=True)

    try:
        voice = validate_voice_id(request.form.get('voice', 'zh-CN-XiaoxiaoNeural'))
    except ValueError as e:
        return error_response("invalid_voice", str(e), 400)

    try:
        speech_rate = normalize_speech_rate(request.form.get('speech_rate', DEFAULT_SPEECH_RATE))
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

        if len(text) > MAX_TEXT_LENGTH:
            return error_response("file_text_too_long", f"{source_name} 超过 {MAX_TEXT_LENGTH} 字符限制。", 400)

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

if __name__ == '__main__':
    run_periodic_cleanup(force=True)
    app.run(debug=True, port=5013) 
