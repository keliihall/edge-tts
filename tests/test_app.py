import os
import time

import pytest

import app as app_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    app_module.app.config.update(TESTING=True, TEMP_AUDIO_DIR=str(tmp_path / "audio"))

    with app_module.SINGLE_RESULTS_LOCK:
        app_module.SINGLE_RESULTS.clear()

    with app_module.BATCH_LOCK:
        app_module.BATCH_JOBS.clear()

    monkeypatch.setattr(app_module, "check_network_connectivity", lambda: True)

    def fake_generate_speech_with_retries(text, voice, speech_rate=app_module.DEFAULT_SPEECH_RATE):
        with app_module.create_temp_audio_file() as tmp_file:
            tmp_file.write(b"fake mp3 data")
            return tmp_file.name

    monkeypatch.setattr(app_module, "generate_speech_with_retries", fake_generate_speech_with_retries)

    yield app_module.app.test_client()

    with app_module.SINGLE_RESULTS_LOCK:
        app_module.SINGLE_RESULTS.clear()

    with app_module.BATCH_LOCK:
        app_module.BATCH_JOBS.clear()


def error_payload(response):
    data = response.get_json()
    assert "error" in data
    assert isinstance(data["error"], dict)
    return data["error"]


def test_normalize_speech_rate_accepts_supported_values():
    assert app_module.normalize_speech_rate("1") == "1.0"
    assert app_module.normalize_speech_rate("1.25") == "1.25"


def test_normalize_speech_rate_rejects_unsupported_values():
    with pytest.raises(ValueError):
        app_module.normalize_speech_rate("3.0")


def test_sanitize_download_name_removes_path_separators():
    assert app_module.sanitize_download_name("../bad:name.mp3") == "bad_name.mp3"
    assert app_module.sanitize_download_name("", "speech.mp3") == "speech.mp3"


def test_decode_text_file_supports_common_chinese_encodings():
    assert app_module.decode_text_file("你好".encode("utf-8")) == "你好"
    assert app_module.decode_text_file("你好".encode("gb18030")) == "你好"


def test_convert_returns_file_id_not_local_path(client):
    response = client.post(
        "/convert",
        data={
            "text": "你好",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speech_rate": "1.0",
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["file_id"]
    assert "audio_path" not in data
    assert data["download_name"].endswith(".mp3")


def test_download_uses_file_token_and_rejects_path_query(client):
    convert_response = client.post(
        "/convert",
        data={
            "text": "你好",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speech_rate": "1.0",
        },
    )
    file_id = convert_response.get_json()["file_id"]

    download_response = client.get(f"/download/{file_id}?name=demo.mp3")
    assert download_response.status_code == 200
    assert download_response.data == b"fake mp3 data"

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
