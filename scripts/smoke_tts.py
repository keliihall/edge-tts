import argparse
import os
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as app_module


def main():
    parser = argparse.ArgumentParser(description="Run a real Edge TTS smoke test")
    parser.add_argument("--keep", action="store_true", help="保留生成的验证音频")
    args = parser.parse_args()

    paths = [
        app_module.generate_speech_with_retries(
            "这是第一段 Edge TTS 真实链路验证。",
            "zh-CN-XiaoxiaoNeural",
            "1.0",
        ),
        app_module.generate_speech_with_retries(
            "这是第二段，用于验证长文本音频合并。",
            "zh-CN-XiaoxiaoNeural",
            "1.0",
        ),
    ]
    merged_path = app_module.merge_audio_files(paths)
    size = os.path.getsize(merged_path)
    if size <= 1024:
        raise SystemExit("真实语音验证失败：合并音频过小")
    print(f"Real TTS smoke passed: {merged_path} ({size} bytes)")

    if not args.keep:
        for path in [*paths, merged_path]:
            app_module.unlink_audio_file(path)


if __name__ == "__main__":
    main()
