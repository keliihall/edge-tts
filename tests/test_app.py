import io
import os
import threading
import time
import zipfile

import pytest

import app as app_module
import run as run_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    app_module.app.config.update(
        TESTING=True,
        AUTH_DISABLED=True,
        TEMP_AUDIO_DIR=str(tmp_path / "audio"),
        SETTINGS_PATH=str(tmp_path / "settings.json"),
        STATE_PATH=str(tmp_path / "state.json"),
        DATABASE_PATH=str(tmp_path / "state.sqlite3"),
        LOG_PATH=str(tmp_path / "app.log"),
        AUDIT_LOG_PATH=str(tmp_path / "audit.log"),
        SECRET_KEY_PATH=str(tmp_path / "secret.key"),
        VOICE_CACHE_PATH=str(tmp_path / "voices.json"),
    )
    app_module.apply_voice_catalog(app_module.BUILTIN_VOICES)
    app_module.save_settings(app_module.DEFAULT_SETTINGS)

    with app_module.SINGLE_RESULTS_LOCK:
        app_module.SINGLE_RESULTS.clear()

    with app_module.BATCH_LOCK:
        app_module.BATCH_JOBS.clear()

    with app_module.TEXT_JOB_LOCK:
        app_module.TEXT_JOBS.clear()

    with app_module.HISTORY_LOCK:
        app_module.HISTORY_ITEMS.clear()

    with app_module.PREFERENCES_LOCK:
        app_module.USER_PREFERENCES["favorite_voices"] = []
        app_module.USER_PREFERENCES["recent_voices"] = []
        app_module.USER_PREFERENCES["config_favorites"] = {}
        app_module.USER_PREFERENCES["auto_download"] = {}
    app_module.apply_voice_catalog(app_module.BUILTIN_VOICES)

    with app_module.NETWORK_DIAGNOSTICS_LOCK:
        app_module.NETWORK_DIAGNOSTICS_CACHE["checked_at"] = 0
        app_module.NETWORK_DIAGNOSTICS_CACHE["data"] = None
    with app_module.LOGIN_FAILURES_LOCK:
        app_module.LOGIN_FAILURES.clear()

    app_module.save_settings(app_module.DEFAULT_SETTINGS)

    monkeypatch.setattr(app_module, "check_network_connectivity", lambda: True)

    def fake_generate_speech_with_retries(
        text,
        voice,
        speech_rate=app_module.DEFAULT_SPEECH_RATE,
        volume=app_module.DEFAULT_VOLUME,
        pitch=app_module.DEFAULT_PITCH,
        provider="edge",
    ):
        with app_module.create_temp_audio_file() as tmp_file:
            tmp_file.write(b"fake mp3 data")
            return tmp_file.name

    monkeypatch.setattr(app_module, "generate_speech_with_retries", fake_generate_speech_with_retries)

    yield app_module.app.test_client()

    with app_module.SINGLE_RESULTS_LOCK:
        app_module.SINGLE_RESULTS.clear()

    with app_module.BATCH_LOCK:
        app_module.BATCH_JOBS.clear()

    with app_module.TEXT_JOB_LOCK:
        app_module.TEXT_JOBS.clear()

    with app_module.HISTORY_LOCK:
        app_module.HISTORY_ITEMS.clear()

    with app_module.PREFERENCES_LOCK:
        app_module.USER_PREFERENCES["favorite_voices"] = []
        app_module.USER_PREFERENCES["recent_voices"] = []
        app_module.USER_PREFERENCES["config_favorites"] = {}
        app_module.USER_PREFERENCES["auto_download"] = {}


def error_payload(response):
    data = response.get_json()
    assert "error" in data
    assert isinstance(data["error"], dict)
    return data["error"]


def wait_for_text_job(client, job_id, expected_status="finished", timeout=2):
    deadline = time.time() + timeout
    last_data = None

    while time.time() < deadline:
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        last_data = response.get_json()
        if last_data["status"] == expected_status:
            return last_data
        time.sleep(0.02)

    raise AssertionError(f"Job {job_id} did not reach {expected_status}: {last_data}")


def wait_for_batch_job(client, job_id, expected_status="finished", timeout=2):
    deadline = time.time() + timeout
    last_data = None
    while time.time() < deadline:
        response = client.get(f"/batch/status/{job_id}")
        assert response.status_code == 200
        last_data = response.get_json()
        if last_data["status"] == expected_status:
            return last_data
        time.sleep(0.02)
    raise AssertionError(f"Batch job {job_id} did not reach {expected_status}: {last_data}")


def test_normalize_speech_rate_accepts_supported_values():
    assert app_module.normalize_speech_rate("1") == "1.0"
    assert app_module.normalize_speech_rate("1.25") == "1.25"


def test_normalize_speech_rate_rejects_unsupported_values():
    with pytest.raises(ValueError):
        app_module.normalize_speech_rate("3.0")


def test_volume_and_pitch_validation():
    assert app_module.normalize_volume("1.25") == "1.25"
    assert app_module.normalize_pitch("+10") == "10"
    assert app_module.edge_volume_from_value("0.75") == "-25%"
    assert app_module.edge_pitch_from_value("-10") == "-10Hz"
    with pytest.raises(ValueError):
        app_module.normalize_volume("2.0")
    with pytest.raises(ValueError):
        app_module.normalize_pitch("99")


def test_convert_accepts_volume_and_pitch(client):
    response = client.post(
        "/convert",
        data={
            "text": "参数验证",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speech_rate": "1.1",
            "volume": "1.25",
            "pitch": "10",
        },
    )
    assert response.status_code == 202
    data = response.get_json()
    assert data["volume"] == "1.25"
    assert data["pitch"] == "10"


def test_sanitize_download_name_removes_path_separators():
    assert app_module.sanitize_download_name("../bad:name.mp3") == "bad_name.mp3"
    assert app_module.sanitize_download_name("", "speech.mp3") == "speech.mp3"


def test_decode_text_file_supports_common_chinese_encodings():
    assert app_module.decode_text_file("你好".encode("utf-8")) == "你好"
    assert app_module.decode_text_file("你好".encode("gb18030")) == "你好"


def test_convert_creates_async_text_job(client):
    response = client.post(
        "/convert",
        data={
            "text": "你好",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speech_rate": "1.0",
        },
    )

    assert response.status_code == 202
    data = response.get_json()
    assert data["id"]
    assert data["status"] in ("queued", "processing", "finished")
    assert "audio_path" not in data
    assert data["total"] == 1
    assert data["download_name"]

def test_home_and_studio_form_a_two_step_product_flow(client):
    home = client.get("/")
    assert home.status_code == 200
    home_page = home.get_data(as_text=True)
    assert 'id="quick-start-form"' in home_page
    assert 'id="quick-generate-btn"' in home_page
    assert 'id="open-studio-btn"' in home_page
    assert 'href="/studio"' in home_page
    assert "logo-lockup.svg" in home_page
    assert "最近任务" not in home_page
    assert "常用入口" not in home_page
    assert "Edge TTS" not in home_page

    studio = client.get("/studio")
    assert studio.status_code == 200
    page = studio.get_data(as_text=True)
    assert 'id="composer-title"' in page
    assert "brand/logo-mark.svg" in page


def test_admin_can_query_structured_audit_logs(client):
    app_module.audit_event(
        "test_audit_event",
        actor_id=0,
        job_id="job-for-log-test",
        text_length=12,
    )

    response = client.get("/admin/logs?kind=audit&query=job-for-log-test")

    assert response.status_code == 200
    data = response.get_json()
    assert data["kind"] == "audit"
    assert data["count"] >= 1
    entry = next(item for item in data["entries"] if item["event"] == "test_audit_event")
    assert entry["job_id"] == "job-for-log-test"
    assert entry["actor_id"] == 0


def test_admin_logs_support_filtered_pagination(client):
    for index in range(25):
        app_module.audit_event(
            "pagination_audit_event",
            actor_id=0,
            sequence=index,
            group="pagination-test",
        )

    first_response = client.get(
        "/admin/logs?kind=audit&query=pagination-test&page=1&page_size=10"
    )
    second_response = client.get(
        "/admin/logs?kind=audit&query=pagination-test&page=2&page_size=10"
    )

    assert first_response.status_code == 200
    first = first_response.get_json()
    second = second_response.get_json()
    assert first["total"] == 25
    assert first["page"] == 1
    assert first["page_size"] == 10
    assert first["pages"] == 3
    assert first["count"] == 10
    assert first["has_prev"] is False
    assert first["has_next"] is True
    assert [entry["sequence"] for entry in first["entries"]] == list(range(24, 14, -1))
    assert [entry["sequence"] for entry in second["entries"]] == list(range(14, 4, -1))

    last = client.get(
        "/admin/logs?kind=audit&query=pagination-test&page=99&page_size=10"
    ).get_json()
    assert last["page"] == 3
    assert last["count"] == 5
    assert last["has_next"] is False

    legacy = client.get(
        "/admin/logs?kind=audit&query=pagination-test&limit=1"
    ).get_json()
    assert legacy["page_size"] == 1
    assert legacy["count"] == 1


def test_log_settings_are_normalized(client):
    response = client.post(
        "/settings",
        json={
            **app_module.DEFAULT_SETTINGS,
            "log_level": "debug",
            "log_max_mb": 999,
            "log_backup_count": 0,
        },
    )

    assert response.status_code == 200
    settings = response.get_json()
    assert settings["log_level"] == "DEBUG"
    assert settings["log_max_mb"] == 50
    assert settings["log_backup_count"] == 1


def test_text_job_downloads_finished_single_chunk(client):
    convert_response = client.post(
        "/convert",
        data={
            "text": "你好",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speech_rate": "1.0",
        },
    )
    job_id = convert_response.get_json()["id"]
    job = wait_for_text_job(client, job_id)

    assert job["success_count"] == 1
    assert job["downloadable"] is True

    download_response = client.get(f"/jobs/{job_id}/download?name=demo.mp3")
    assert download_response.status_code == 200
    assert download_response.data == b"fake mp3 data"

    audio_response = client.get(job["audio_url"])
    assert audio_response.status_code == 200
    assert audio_response.data == b"fake mp3 data"


def test_preview_generates_audio_url_and_remembers_recent_voice(client):
    response = client.post(
        "/preview",
        data={
            "text": "这是一段用于试听的文本" * 40,
            "voice": "zh-CN-XiaoyiNeural",
            "speech_rate": "0.9",
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["file_id"]
    assert data["text_length"] == app_module.PREVIEW_TEXT_LENGTH

    audio_response = client.get(data["audio_url"])
    assert audio_response.status_code == 200
    assert audio_response.data == b"fake mp3 data"

    preferences = client.get("/preferences").get_json()
    assert preferences["recent_voices"][0] == "zh-CN-XiaoyiNeural"


def test_voice_favorites_and_presets(client):
    favorite_response = client.post(
        "/preferences/favorites/zh-CN-XiaoxiaoNeural",
        json={"favorite": True},
    )
    assert favorite_response.status_code == 200
    assert "zh-CN-XiaoxiaoNeural" in favorite_response.get_json()["favorite_voices"]

    voices = client.get("/voices").get_json()
    selected_voice = next(voice for voice in voices if voice["id"] == "zh-CN-XiaoxiaoNeural")
    assert selected_voice["favorite"] is True

    presets = client.get("/presets").get_json()
    assert any(preset["id"] == "story" for preset in presets)

def test_provider_catalog_exposes_edge_and_local_engines(client, monkeypatch):
    monkeypatch.setattr(app_module, "can_connect", lambda *args, **kwargs: True)
    app_module.clear_provider_caches()

    response = client.get("/providers")

    assert response.status_code == 200
    providers = {item["id"]: item for item in response.get_json()}
    assert set(providers) == {"edge", "cosyvoice", "kokoro"}
    assert providers["edge"]["available"] is True
    assert providers["cosyvoice"]["local"] is True
    assert providers["cosyvoice"]["capabilities"]["voice_cloning"] is True
    assert providers["kokoro"]["enabled"] is False


def test_cosyvoice_provider_voices_and_task_flow(client, monkeypatch):
    class FakeLocalClient:
        def health(self):
            return {"status": "ready", "message": "model loaded"}

        def voices(self):
            return [{"id": "clone-demo", "name": "演示克隆音色", "gender": "女"}]

    monkeypatch.setattr(app_module, "get_local_tts_client", lambda *args, **kwargs: FakeLocalClient())
    app_module.save_settings({
        **app_module.DEFAULT_SETTINGS,
        "default_provider": "cosyvoice",
        "cosyvoice_enabled": True,
        "cosyvoice_default_voice": "clone-demo",
    })

    voices_response = client.get("/voices?provider=cosyvoice")
    assert voices_response.status_code == 200
    assert voices_response.get_json()[0]["id"] == "clone-demo"

    response = client.post(
        "/convert",
        data={
            "provider": "cosyvoice",
            "voice": "clone-demo",
            "text": "本地语音任务",
            "speech_rate": "1.0",
        },
    )
    assert response.status_code == 202
    task = wait_for_text_job(client, response.get_json()["id"])
    assert task["provider"] == "cosyvoice"
    assert task["voice"] == "clone-demo"
    assert task["success_count"] == 1


def test_disabled_local_provider_returns_structured_error(client):
    response = client.get("/voices?provider=kokoro")

    assert response.status_code == 503
    assert error_payload(response)["code"] == "provider_unavailable"


def test_configuration_favorites_store_complete_voice_settings(client):
    response = client.post(
        "/config-favorites",
        json={
            "name": "温和旁白",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speech_rate": "0.9",
            "volume": "1.25",
            "pitch": "-10",
        },
    )
    assert response.status_code == 201
    favorite = response.get_json()
    assert favorite["name"] == "温和旁白"
    assert favorite["speech_rate"] == "0.9"
    assert favorite["volume"] == "1.25"
    assert favorite["pitch"] == "-10"

    favorites = client.get("/config-favorites").get_json()
    assert favorites == [favorite]

    delete_response = client.delete(f"/config-favorites/{favorite['id']}")
    assert delete_response.status_code == 200
    assert client.get("/config-favorites").get_json() == []


def test_auto_download_preference_is_persisted(client):
    response = client.patch(
        "/preferences/workspace",
        json={"auto_download": "all"},
    )
    assert response.status_code == 200
    assert response.get_json()["auto_download"] == "all"
    assert client.get("/preferences").get_json()["auto_download"] == "all"

    invalid = client.patch(
        "/preferences/workspace",
        json={"auto_download": "invalid"},
    )
    assert invalid.status_code == 400


def test_admin_can_refresh_and_cache_online_chinese_voices(client, monkeypatch):
    import edge_tts

    async def fake_list_voices(**kwargs):
        return [
            {
                "ShortName": "zh-CN-NewVoiceNeural",
                "Gender": "Female",
                "Locale": "zh-CN",
                "VoiceTag": {
                    "VoicePersonalities": ["Friendly"],
                    "ContentCategories": ["General"],
                },
            },
            {
                "ShortName": "en-US-OtherNeural",
                "Gender": "Male",
                "Locale": "en-US",
                "VoiceTag": {},
            },
        ]

    monkeypatch.setattr(edge_tts, "list_voices", fake_list_voices)
    response = client.post("/voices/refresh")
    assert response.status_code == 200
    assert response.get_json()["count"] == 1
    assert "zh-CN-NewVoiceNeural" in app_module.AVAILABLE_VOICE_IDS
    assert os.path.exists(app_module.get_voice_cache_path())


def test_settings_can_be_saved_and_used_as_defaults(client):
    response = client.post(
        "/settings",
        json={
            "default_voice": "zh-CN-XiaoyiNeural",
            "default_speech_rate": "0.9",
            "proxy_url": "http://127.0.0.1:7890",
            "history_retention_days": 12,
            "temp_file_ttl_hours": 3,
            "default_save_dir": "/tmp",
            "auto_open_browser": False,
            "chunk_length": 1200,
        },
    )

    assert response.status_code == 200
    settings = response.get_json()
    assert settings["default_voice"] == "zh-CN-XiaoyiNeural"
    assert settings["default_speech_rate"] == "0.9"
    assert settings["chunk_length"] == 1200
    assert settings["auto_open_browser"] is False

    convert_response = client.post("/convert", data={"text": "使用默认设置"})
    assert convert_response.status_code == 202
    data = convert_response.get_json()
    assert data["voice"] == "zh-CN-XiaoyiNeural"
    assert data["speech_rate"] == "0.9"


def test_finished_job_can_save_to_backend_directory(client, tmp_path):
    save_dir = tmp_path / "exports"
    settings_response = client.post(
        "/settings",
        json={**app_module.DEFAULT_SETTINGS, "default_save_dir": str(save_dir)},
    )
    assert settings_response.status_code == 200

    convert_response = client.post(
        "/convert",
        data={
            "text": "保存到后端目录",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speech_rate": "1.0",
        },
    )
    job_id = convert_response.get_json()["id"]
    wait_for_text_job(client, job_id)

    save_response = client.post(
        f"/jobs/{job_id}/save",
        json={"name": "backend-save"},
    )
    assert save_response.status_code == 200
    saved_path = save_response.get_json()["path"]
    assert saved_path.endswith("backend-save.mp3")
    assert os.path.exists(saved_path)
    with open(saved_path, "rb") as saved_file:
        assert saved_file.read() == b"fake mp3 data"


def test_settings_reject_invalid_voice(client):
    response = client.post("/settings", json={"default_voice": "bad-voice"})

    assert response.status_code == 400
    error = error_payload(response)
    assert error["code"] == "invalid_settings"


def test_diagnostics_reports_network_fields(client, monkeypatch):
    def fake_can_connect(host, port, timeout=5):
        return host == "speech.platform.bing.com"

    monkeypatch.setattr(app_module, "can_connect", fake_can_connect)

    response = client.get("/diagnostics")

    assert response.status_code == 200
    data = response.get_json()
    assert data["version"] == app_module.APP_VERSION
    assert data["edge_tts_available"] is True
    assert data["network_connectivity"] is True
    assert data["settings_path"].endswith("settings.json")


def test_find_available_port_skips_busy_port(monkeypatch):
    busy_ports = {5013}

    monkeypatch.setattr(run_module, "can_connect", lambda port, timeout=0.5: port in busy_ports)

    assert run_module.find_available_port(5013) == 5014


def test_clear_runtime_state_only_removes_current_process_file(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime.json"
    monkeypatch.setattr(run_module, "runtime_state_path", lambda: str(state_path))

    run_module.write_runtime_state(5013)
    assert state_path.exists()

    run_module.clear_runtime_state()
    assert not state_path.exists()


def test_download_uses_token_route_and_rejects_path_query(client):
    with app_module.create_temp_audio_file() as tmp_file:
        tmp_file.write(b"legacy token audio")
        file_id = app_module.register_single_result(tmp_file.name, "legacy.mp3")

    download_response = client.get(f"/download/{file_id}?name=demo.mp3")
    assert download_response.status_code == 200
    assert download_response.data == b"legacy token audio"

    forged_response = client.get("/download?path=/etc/passwd&name=bad.mp3")
    assert forged_response.status_code == 404
    error = error_payload(forged_response)
    assert error["code"] == "download_token_required"


def test_missing_file_token_returns_structured_error(client):
    response = client.get("/download/not-a-real-token")

    assert response.status_code == 404
    error = error_payload(response)
    assert error["code"] == "audio_result_not_found"
    assert error["message"]


def test_convert_rejects_unknown_voice_with_structured_error(client):
    response = client.post(
        "/convert",
        data={
            "text": "你好",
            "voice": "unknown-voice",
            "speech_rate": "1.0",
        },
    )

    assert response.status_code == 400
    error = error_payload(response)
    assert error["code"] == "invalid_voice"


def test_split_text_to_chunks_prefers_sentence_boundaries():
    text = "第一句。" * 10 + "第二段很长，" * 80
    chunks = app_module.split_text_to_chunks(text, max_chars=80)

    assert len(chunks) > 1
    assert all(len(chunk) <= 80 for chunk in chunks)
    assert chunks[0].endswith("。")


def test_long_text_job_creates_multiple_chunks_and_merged_mp3_download(client):
    long_text = "这是一个长句子。" * 800

    response = client.post(
        "/convert",
        data={
            "text": long_text,
            "voice": "zh-CN-XiaoxiaoNeural",
            "speech_rate": "1.0",
        },
    )
    assert response.status_code == 202
    job_id = response.get_json()["id"]
    job = wait_for_text_job(client, job_id)

    assert job["total"] > 1
    assert job["success_count"] == job["total"]

    download_response = client.get(f"/jobs/{job_id}/download?name=long-job")
    assert download_response.status_code == 200
    assert download_response.mimetype == "audio/mpeg"
    assert download_response.data == b"fake mp3 data" * job["total"]


def test_finished_text_job_records_history(client):
    response = client.post(
        "/convert",
        data={
            "text": "这是一条会进入历史记录的文本",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speech_rate": "1.0",
        },
    )
    job_id = response.get_json()["id"]
    wait_for_text_job(client, job_id)

    history = client.get("/history").get_json()
    assert len(history) == 1
    assert history[0]["job_id"] == job_id
    assert history[0]["download_url"] == f"/jobs/{job_id}/download"
    assert history[0]["audio_url"]

    delete_response = client.delete(f"/history/{history[0]['id']}")
    assert delete_response.status_code == 200
    assert client.get("/history").get_json() == []


def test_task_list_restores_jobs_and_exposes_timing_fields(client):
    response = client.post(
        "/convert",
        data={
            "text": "刷新页面后仍应看到的任务",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speech_rate": "1.0",
        },
    )
    job_id = response.get_json()["id"]
    completed = wait_for_text_job(client, job_id)
    assert completed["started_at"]
    assert completed["finished_at"]
    assert completed["elapsed_seconds"] is not None
    assert completed["items"][0]["started_at"]
    assert completed["items"][0]["finished_at"]
    assert completed["items"][0]["elapsed_seconds"] is not None
    assert completed["items"][0]["estimated_remaining_seconds"] == 0

    tasks = client.get("/tasks").get_json()
    task = next(item for item in tasks if item["id"] == job_id)
    assert task["kind"] == "text"
    assert task["status"] == "finished"

    with app_module.TEXT_JOB_LOCK:
        app_module.TEXT_JOBS.clear()
    app_module.load_user_state()
    restored = client.get("/tasks").get_json()
    assert any(item["id"] == job_id for item in restored)


def test_task_retention_is_independent_from_audio_ttl(client):
    settings = client.post(
        "/settings",
        json={
            **app_module.DEFAULT_SETTINGS,
            "task_retention_days": 30,
            "temp_file_ttl_hours": 1,
        },
    ).get_json()
    assert settings["task_retention_days"] == 30

    job = app_module.create_text_job(
        "保留任务元数据",
        "zh-CN-XiaoxiaoNeural",
        "1.0",
    )
    with app_module.TEXT_JOB_LOCK:
        app_module.TEXT_JOBS[job["id"]]["created_at"] = time.time() - 2 * 24 * 60 * 60
        app_module.TEXT_JOBS[job["id"]]["status"] = "finished"
    app_module.cleanup_old_text_jobs()
    assert job["id"] in app_module.TEXT_JOBS


def test_task_list_reports_fifo_queue_positions(client):
    first = app_module.create_text_job(
        "第一个排队任务",
        "zh-CN-XiaoxiaoNeural",
        "1.0",
    )
    time.sleep(0.001)
    second = app_module.create_text_job(
        "第二个排队任务",
        "zh-CN-XiaoxiaoNeural",
        "1.0",
    )

    tasks = {item["id"]: item for item in client.get("/tasks").get_json()}
    assert tasks[first["id"]]["queue_position"] == 1
    assert tasks[second["id"]]["queue_position"] == 2


def test_user_state_persists_preferences_history_and_finished_jobs(client):
    favorite_response = client.post(
        "/preferences/favorites/zh-CN-XiaoyiNeural",
        json={"favorite": True},
    )
    assert favorite_response.status_code == 200

    response = client.post(
        "/convert",
        data={
            "text": "需要持久化的任务",
            "voice": "zh-CN-XiaoyiNeural",
            "speech_rate": "0.9",
        },
    )
    job_id = response.get_json()["id"]
    wait_for_text_job(client, job_id)

    with app_module.TEXT_JOB_LOCK:
        app_module.TEXT_JOBS.clear()
    with app_module.HISTORY_LOCK:
        app_module.HISTORY_ITEMS.clear()
    with app_module.PREFERENCES_LOCK:
        app_module.USER_PREFERENCES["favorite_voices"] = []
        app_module.USER_PREFERENCES["recent_voices"] = []

    app_module.load_user_state()

    assert job_id in app_module.TEXT_JOBS
    assert app_module.HISTORY_ITEMS[0]["job_id"] == job_id
    assert "zh-CN-XiaoyiNeural" in app_module.USER_PREFERENCES["favorite_voices"]


def test_history_retention_setting_removes_old_items(client):
    app_module.save_settings({**app_module.DEFAULT_SETTINGS, "history_retention_days": 1})
    with app_module.HISTORY_LOCK:
        app_module.HISTORY_ITEMS.append({
            "id": "old",
            "job_id": "job",
            "title": "old",
            "summary": "",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speech_rate": "1.0",
            "text_length": 1,
            "total": 1,
            "success_count": 1,
            "failed_count": 0,
            "created_at": time.time() - 3 * 24 * 60 * 60,
            "finished_at": time.time() - 3 * 24 * 60 * 60,
            "download_url": "/jobs/job/download",
            "audio_url": None,
        })

    assert client.get("/history").get_json() == []


def test_text_job_cancel_marks_queued_job_cancelled(client):
    job = app_module.create_text_job(
        "第一段。" * 100,
        "zh-CN-XiaoxiaoNeural",
        "1.0",
    )

    response = client.post(f"/jobs/{job['id']}/cancel")

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "cancelled"
    assert data["cancelled_count"] == data["total"]


def test_retry_failed_text_job_item(client, monkeypatch):
    attempts = {"count": 0}
    ready = threading.Event()

    def flaky_generate(
        text,
        voice,
        speech_rate=app_module.DEFAULT_SPEECH_RATE,
        volume=app_module.DEFAULT_VOLUME,
        pitch=app_module.DEFAULT_PITCH,
    ):
        attempts["count"] += 1
        if attempts["count"] == 1:
            ready.set()
            raise Exception("temporary failure")
        with app_module.create_temp_audio_file() as tmp_file:
            tmp_file.write(b"retry mp3 data")
            return tmp_file.name

    monkeypatch.setattr(app_module, "generate_speech_with_retries", flaky_generate)

    response = client.post(
        "/convert",
        data={
            "text": "需要重试的文本",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speech_rate": "1.0",
        },
    )
    job_id = response.get_json()["id"]
    assert ready.wait(1)
    job = wait_for_text_job(client, job_id)
    assert job["failed_count"] == 1
    item_id = job["items"][0]["id"]

    retry_response = client.post(f"/jobs/{job_id}/items/{item_id}/retry")
    assert retry_response.status_code == 202

    retried_job = wait_for_text_job(client, job_id)
    assert retried_job["success_count"] == 1
    assert retried_job["failed_count"] == 0


def test_batch_rejects_unknown_voice_with_structured_error(client):
    response = client.post(
        "/batch/convert",
        data={
            "voice": "unknown-voice",
            "speech_rate": "1.0",
        },
    )

    assert response.status_code == 400
    error = error_payload(response)
    assert error["code"] == "invalid_voice"


def test_batch_rejects_missing_files_with_structured_error(client):
    response = client.post(
        "/batch/convert",
        data={
            "voice": "zh-CN-XiaoxiaoNeural",
            "speech_rate": "1.0",
        },
    )

    assert response.status_code == 400
    error = error_payload(response)
    assert error["code"] == "no_files"


def test_unlink_audio_file_only_removes_managed_files(tmp_path):
    app_module.app.config.update(TESTING=True, TEMP_AUDIO_DIR=str(tmp_path / "managed"))

    with app_module.create_temp_audio_file() as managed_file:
        managed_file.write(b"managed")
        managed_path = managed_file.name

    outside_path = tmp_path / "outside.mp3"
    outside_path.write_bytes(b"outside")

    app_module.unlink_audio_file(managed_path)
    app_module.unlink_audio_file(str(outside_path))

    assert not os.path.exists(managed_path)
    assert outside_path.exists()


def test_cleanup_expired_audio_files_removes_unreferenced_old_files(tmp_path):
    app_module.app.config.update(TESTING=True, TEMP_AUDIO_DIR=str(tmp_path / "cleanup"))

    with app_module.create_temp_audio_file() as old_file:
        old_file.write(b"old")
        old_path = old_file.name

    old_time = time.time() - 3600
    os.utime(old_path, (old_time, old_time))

    app_module.cleanup_expired_audio_files(max_age_seconds=1)

    assert not os.path.exists(old_path)


def test_auth_setup_login_and_admin_user_management(tmp_path, monkeypatch):
    app_module.app.config.update(
        TESTING=True,
        AUTH_DISABLED=False,
        TEMP_AUDIO_DIR=str(tmp_path / "audio"),
        SETTINGS_PATH=str(tmp_path / "settings.json"),
        STATE_PATH=str(tmp_path / "state.json"),
        DATABASE_PATH=str(tmp_path / "auth.sqlite3"),
        LOG_PATH=str(tmp_path / "app.log"),
        SECRET_KEY_PATH=str(tmp_path / "secret.key"),
    )
    monkeypatch.setattr(app_module, "check_network_connectivity", lambda: True)
    client = app_module.app.test_client()

    assert client.get("/").status_code == 302
    setup_response = client.post(
        "/auth/setup",
        json={"username": "owner", "password": "strong-pass-123"},
    )
    assert setup_response.status_code == 201
    assert setup_response.get_json()["user"]["role"] == "admin"

    create_response = client.post(
        "/admin/users",
        json={"username": "creator", "password": "creator-pass-123", "role": "user"},
    )
    assert create_response.status_code == 201
    creator_id = create_response.get_json()["user"]["id"]

    assert client.post("/auth/logout").status_code == 200
    bad_login = client.post(
        "/auth/login",
        json={"username": "creator", "password": "wrong-password"},
    )
    assert bad_login.status_code == 401
    for _ in range(app_module.LOGIN_FAILURE_LIMIT - 1):
        client.post(
            "/auth/login",
            json={"username": "creator", "password": "wrong-password"},
        )
    limited_login = client.post(
        "/auth/login",
        json={"username": "creator", "password": "creator-pass-123"},
    )
    assert limited_login.status_code == 429
    with app_module.LOGIN_FAILURES_LOCK:
        app_module.LOGIN_FAILURES.clear()
    login_response = client.post(
        "/auth/login",
        json={"username": "creator", "password": "creator-pass-123"},
    )
    assert login_response.status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/admin/users").status_code == 403
    assert client.post("/settings", json={}).status_code == 403
    private_job = app_module.create_text_job(
        "creator private text",
        "zh-CN-XiaoxiaoNeural",
        "1.0",
        owner_id=creator_id,
    )
    assert client.get(f"/jobs/{private_job['id']}").status_code == 200

    client.post("/auth/logout")
    client.post(
        "/auth/login",
        json={"username": "owner", "password": "strong-pass-123"},
    )
    viewer_response = client.post(
        "/admin/users",
        json={"username": "viewer", "password": "viewer-pass-123", "role": "user"},
    )
    assert viewer_response.status_code == 201
    client.post("/auth/logout")
    client.post(
        "/auth/login",
        json={"username": "viewer", "password": "viewer-pass-123"},
    )
    assert client.get(f"/jobs/{private_job['id']}").status_code == 403
    client.post("/auth/logout")
    client.post(
        "/auth/login",
        json={"username": "owner", "password": "strong-pass-123"},
    )
    update_response = client.patch(
        f"/admin/users/{creator_id}",
        json={"active": False, "password": "new-creator-pass"},
    )
    assert update_response.status_code == 200
    assert update_response.get_json()["user"]["active"] is False

    owner_id = client.get("/auth/me").get_json()["user"]["id"]
    last_admin_response = client.patch(
        f"/admin/users/{owner_id}",
        json={"active": False},
    )
    assert last_admin_response.status_code == 409


def test_batch_retry_cancel_and_sqlite_restore(client, monkeypatch):
    attempts = {"first.txt": 0, "second.txt": 0}

    def flaky_generate(
        text,
        voice,
        speech_rate=app_module.DEFAULT_SPEECH_RATE,
        volume=app_module.DEFAULT_VOLUME,
        pitch=app_module.DEFAULT_PITCH,
    ):
        attempts[text] += 1
        if text == "first.txt" and attempts[text] == 1:
            raise Exception("temporary batch failure")
        with app_module.create_temp_audio_file() as tmp_file:
            tmp_file.write(text.encode("utf-8"))
            return tmp_file.name

    monkeypatch.setattr(app_module, "generate_speech_with_retries", flaky_generate)
    response = client.post(
        "/batch/convert",
        data={
            "voice": "zh-CN-XiaoxiaoNeural",
            "speech_rate": "1.0",
            "files": [
                (io.BytesIO(b"first.txt"), "first.txt"),
                (io.BytesIO(b"second.txt"), "second.txt"),
            ],
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 202
    job_id = response.get_json()["id"]
    job = wait_for_batch_job(client, job_id)
    assert job["failed_count"] == 1
    failed_item = next(item for item in job["items"] if item["status"] == "failed")

    retry_response = client.post(
        f"/batch/job/{job_id}/items/{failed_item['id']}/retry"
    )
    assert retry_response.status_code == 202
    retried = wait_for_batch_job(client, job_id)
    assert retried["success_count"] == 2
    assert retried["failed_count"] == 0

    with app_module.BATCH_LOCK:
        app_module.BATCH_JOBS.clear()
    app_module.load_user_state()
    restored = client.get(f"/batch/status/{job_id}").get_json()
    assert restored["success_count"] == 2
    assert all(item["attempts"] >= 1 for item in restored["items"])

    queued_job = {
        "id": "queued-batch",
        "status": "queued",
        "voice": "zh-CN-XiaoxiaoNeural",
        "speech_rate": "1.0",
        "created_at": time.time(),
        "updated_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "cancel_requested": False,
        "items": [{
            "id": "queued-item",
            "index": 1,
            "source_name": "queued.txt",
            "download_name": "queued.mp3",
            "text": "queued",
            "status": "pending",
            "text_length": 6,
            "size": 0,
            "error": None,
            "audio_path": None,
            "attempts": 0,
        }],
    }
    app_module.recompute_batch_job_counts(queued_job)
    with app_module.BATCH_LOCK:
        app_module.BATCH_JOBS[queued_job["id"]] = queued_job
        app_module.get_repository().save_job("batch", queued_job)
    cancel_response = client.post("/batch/job/queued-batch/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.get_json()["status"] == "cancelled"


def test_diagnostics_archive_excludes_user_text_and_passwords(client):
    secret_text = "PRIVATE-TEXT-MUST-NOT-LEAK"
    job = app_module.create_text_job(
        secret_text,
        "zh-CN-XiaoxiaoNeural",
        "1.0",
    )
    app_module.app.logger.info("job_created job_id=%s text_length=%s", job["id"], len(secret_text))

    response = client.get("/diagnostics/download")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        names = archive.namelist()
        assert "system.json" in names
        contents = b"".join(archive.read(name) for name in names)
    assert secret_text.encode("utf-8") not in contents
    assert b"password_hash" not in contents
