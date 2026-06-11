import json

import pytest

import tts_providers


def test_validate_loopback_url_rejects_remote_hosts():
    assert tts_providers.validate_loopback_url("http://127.0.0.1:50000/") == "http://127.0.0.1:50000"
    assert tts_providers.validate_loopback_url("http://[::1]:50001") == "http://[::1]:50001"
    with pytest.raises(ValueError):
        tts_providers.validate_loopback_url("https://example.com/tts")
    with pytest.raises(ValueError):
        tts_providers.validate_loopback_url("http://localhost:not-a-port")


def test_local_client_normalizes_voices_and_reads_mp3(monkeypatch):
    responses = [
        (json.dumps({"voices": [{"id": "voice-a", "name": "Voice A"}]}).encode(), "application/json"),
        (b"mp3-data", "audio/mpeg"),
    ]

    class FakeHeaders:
        def __init__(self, content_type):
            self.content_type = content_type

        def get_content_type(self):
            return self.content_type

    class FakeResponse:
        def __init__(self, body, content_type):
            self.body = body
            self.headers = FakeHeaders(content_type)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self.body

    def fake_urlopen(request, timeout):
        body, content_type = responses.pop(0)
        return FakeResponse(body, content_type)

    monkeypatch.setattr(tts_providers.urllib.request, "urlopen", fake_urlopen)
    client = tts_providers.LocalTTSClient("http://localhost:50000")

    assert client.voices() == [{
        "id": "voice-a",
        "name": "Voice A",
        "gender": "未知",
        "style": "",
    }]
    assert client.synthesize(
        text="hello",
        voice="voice-a",
        speech_rate=1.0,
        volume=1.0,
        pitch=0,
    ) == b"mp3-data"
