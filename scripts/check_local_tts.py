"""Validate a local TTS sidecar against the ShengJian v1.1 contract."""

import argparse
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tts_providers import LocalTTSClient


def main():
    parser = argparse.ArgumentParser(description="Check a ShengJian local TTS sidecar")
    parser.add_argument("base_url", help="Loopback URL, for example http://127.0.0.1:50000")
    parser.add_argument("--voice", help="Voice ID; defaults to the first returned voice")
    parser.add_argument("--text", default="欢迎使用声笺本地语音。")
    parser.add_argument("--output", default="local-tts-check.mp3")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()

    client = LocalTTSClient(args.base_url, timeout=args.timeout)
    health = client.health()
    voices = client.voices()
    if not voices:
        raise SystemExit("Sidecar did not return any voices")

    voice_id = args.voice or voices[0]["id"]
    if voice_id not in {voice["id"] for voice in voices}:
        raise SystemExit(f"Voice not found: {voice_id}")

    audio = client.synthesize(
        text=args.text,
        voice=voice_id,
        speech_rate=1.0,
        volume=1.0,
        pitch=0,
    )
    output_path = pathlib.Path(args.output).expanduser().resolve()
    output_path.write_bytes(audio)

    print(f"health: {health}")
    print(f"voices: {len(voices)}")
    print(f"voice: {voice_id}")
    print(f"audio: {output_path} ({len(audio)} bytes)")


if __name__ == "__main__":
    main()
