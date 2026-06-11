import argparse
import pathlib
import re
import shutil
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from version import APP_NAME, APP_PACKAGE_NAME, APP_SLUG, APP_VERSION


def configure_utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")


def run(command):
    print("+", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def require_version(path, pattern):
    content = path.read_text(encoding="utf-8")
    if not re.search(pattern, content):
        raise SystemExit(f"版本检查失败：{path.relative_to(ROOT)} 未标注 v{APP_VERSION}")


def main():
    configure_utf8_stdio()

    parser = argparse.ArgumentParser(description=f"{APP_NAME} release gate")
    parser.add_argument("--build", action="store_true", help="同时执行当前平台构建")
    args = parser.parse_args()

    require_version(ROOT / "README.md", rf"v{re.escape(APP_VERSION)}")
    require_version(ROOT / "README.md", re.escape(APP_NAME))
    require_version(ROOT / f"UPDATE_V{APP_VERSION}.md", rf"v{re.escape(APP_VERSION)}")
    require_version(ROOT / f"UPDATE_V{APP_VERSION}.md", re.escape(APP_NAME))
    for script_name in ("build_macos.sh", "build_linux.sh", "build_windows.bat"):
        require_version(ROOT / script_name, r"from version import APP_VERSION")
        require_version(ROOT / script_name, r"from version import APP_SLUG")
    require_version(ROOT / "static/css/style.css", r'Noto Sans SC')
    font_path = ROOT / "static/fonts/NotoSansSC-VariableFont_wght.ttf"
    font_license_path = ROOT / "static/fonts/OFL.txt"
    if not font_path.is_file() or font_path.stat().st_size < 1_000_000:
        raise SystemExit("字体检查失败：Noto Sans SC 字体文件缺失或不完整")
    if not font_license_path.is_file():
        raise SystemExit("字体检查失败：OFL.txt 缺失")

    run([
        sys.executable,
        "-m",
        "py_compile",
        "app.py",
        "auth.py",
        "run.py",
        "storage.py",
        "version.py",
        "scripts/release_check.py",
        "scripts/smoke_tts.py",
    ])
    run([sys.executable, "-m", "pytest", "-q"])
    run([sys.executable, "-m", "pip", "check"])
    if shutil.which("node"):
        run(["node", "--check", "static/js/app.js"])
        run(["node", "--check", "static/js/admin.js"])
        run(["node", "--check", "static/js/file-selection.js"])
        run(["node", "scripts/test_frontend.js"])

    if args.build:
        if sys.platform == "darwin":
            run(["bash", "build_macos.sh"])
        elif sys.platform.startswith("linux"):
            run(["bash", "build_linux.sh"])
        elif sys.platform == "win32":
            run(["cmd", "/c", "build_windows.bat"])
        else:
            raise SystemExit(f"暂不支持的平台：{sys.platform}")

    print(
        f"Release gate passed for {APP_NAME} v{APP_VERSION} "
        f"({APP_PACKAGE_NAME}/{APP_SLUG})"
    )


if __name__ == "__main__":
    main()
