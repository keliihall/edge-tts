"""TTS provider metadata and local sidecar clients."""

from __future__ import annotations

import base64
import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class ProviderError(RuntimeError):
    """Base error for TTS provider failures."""


class ProviderUnavailable(ProviderError):
    """Raised when a configured provider cannot be reached."""


PROVIDER_DEFINITIONS: dict[str, dict[str, Any]] = {
    "edge": {
        "id": "edge",
        "name": "Microsoft Edge TTS",
        "description": "云端语音，音色丰富，适合默认在线方案。",
        "local": False,
        "capabilities": {
            "rate": True,
            "volume": True,
            "pitch": True,
            "voice_cloning": False,
        },
    },
    "cosyvoice": {
        "id": "cosyvoice",
        "name": "CosyVoice 3",
        "description": "本地高质量中文语音与克隆方案，适合品质优先场景。",
        "local": True,
        "capabilities": {
            "rate": True,
            "volume": False,
            "pitch": False,
            "voice_cloning": True,
        },
    },
    "kokoro": {
        "id": "kokoro",
        "name": "Kokoro",
        "description": "轻量本地语音方案，适合低资源和高并发场景。",
        "local": True,
        "capabilities": {
            "rate": True,
            "volume": False,
            "pitch": False,
            "voice_cloning": False,
        },
    },
}

PROVIDER_IDS = tuple(PROVIDER_DEFINITIONS)


def validate_loopback_url(value: str) -> str:
    """Validate and normalize a local-only sidecar base URL."""
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        raise ValueError("本地 TTS 服务地址不能为空")

    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("本地 TTS 服务地址仅支持 http 或 https")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("本地 TTS 服务地址格式无效")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("本地 TTS 服务端口无效") from exc
    if parsed.query or parsed.fragment:
        raise ValueError("本地 TTS 服务地址不能包含查询参数或片段")

    hostname = parsed.hostname.lower()
    is_loopback = hostname == "localhost"
    if not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = False
    if not is_loopback:
        raise ValueError("本地 TTS 服务仅允许配置回环地址")

    return raw


def normalize_voice_catalog(payload: Any) -> list[dict[str, Any]]:
    """Normalize sidecar voice payloads to the application's voice schema."""
    items = payload.get("voices") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ProviderError("本地 TTS 服务返回了无效的音色列表")

    voices: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            voice_id = item.strip()
            voice = {
                "id": voice_id,
                "name": voice_id,
                "gender": "未知",
                "style": "",
            }
        elif isinstance(item, dict):
            voice_id = str(item.get("id") or item.get("voice") or "").strip()
            voice = {
                "id": voice_id,
                "name": str(item.get("name") or voice_id).strip(),
                "gender": str(item.get("gender") or "未知").strip(),
                "style": str(item.get("style") or "").strip(),
            }
        else:
            continue

        if not voice_id or voice_id in seen:
            continue
        seen.add(voice_id)
        voices.append(voice)
    return voices


@dataclass(frozen=True)
class LocalTTSClient:
    """HTTP client for a local CosyVoice or Kokoro sidecar."""

    base_url: str
    timeout: float = 300.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", validate_loopback_url(self.base_url))

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        accept: str = "application/json",
    ) -> tuple[bytes, str]:
        body = None
        headers = {"Accept": accept}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                content_type = response.headers.get_content_type()
                return response.read(), content_type
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail_payload = json.loads(exc.read().decode("utf-8"))
                error_value = detail_payload.get("error")
                if isinstance(error_value, dict):
                    error_value = error_value.get("message")
                detail = str(error_value or detail_payload.get("message") or "")
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                pass
            suffix = f"：{detail}" if detail else ""
            raise ProviderError(f"本地 TTS 服务请求失败（HTTP {exc.code}）{suffix}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailable(f"无法连接本地 TTS 服务：{self.base_url}") from exc

    def health(self) -> dict[str, Any]:
        raw, _ = self._request("/health")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("本地 TTS 服务健康检查返回了无效 JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError("本地 TTS 服务健康检查格式无效")
        return payload

    def voices(self) -> list[dict[str, Any]]:
        raw, _ = self._request("/voices")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("本地 TTS 服务音色接口返回了无效 JSON") from exc
        return normalize_voice_catalog(payload)

    def synthesize(
        self,
        *,
        text: str,
        voice: str,
        speech_rate: float,
        volume: float,
        pitch: int,
    ) -> bytes:
        raw, content_type = self._request(
            "/synthesize",
            method="POST",
            payload={
                "text": text,
                "voice": voice,
                "speech_rate": speech_rate,
                "volume": volume,
                "pitch": pitch,
                "format": "mp3",
            },
            accept="audio/mpeg, application/json",
        )
        if content_type == "application/json":
            try:
                payload = json.loads(raw.decode("utf-8"))
                if payload.get("format") not in {None, "mp3"}:
                    raise ProviderError("本地 TTS 服务必须返回 MP3 音频")
                raw = base64.b64decode(payload["audio_base64"], validate=True)
            except ProviderError:
                raise
            except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderError("本地 TTS 服务返回了无效的音频数据") from exc
        elif content_type not in {"audio/mpeg", "audio/mp3", "application/octet-stream"}:
            raise ProviderError(f"本地 TTS 服务返回了不支持的音频类型：{content_type}")

        if not raw:
            raise ProviderError("本地 TTS 服务返回了空音频")
        return raw
