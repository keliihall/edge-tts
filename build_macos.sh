#!/bin/bash

set -euo pipefail

PYTHON="${PYTHON:-python3}"
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif [ -x "venv/bin/python" ]; then
    PYTHON="venv/bin/python"
fi
APP_VERSION="v$("$PYTHON" -c 'from version import APP_VERSION; print(APP_VERSION)')"
APP_PACKAGE_NAME="$("$PYTHON" -c 'from version import APP_PACKAGE_NAME; print(APP_PACKAGE_NAME)')"
APP_SLUG="$("$PYTHON" -c 'from version import APP_SLUG; print(APP_SLUG)')"

# 清理之前的构建
rm -rf build dist

# 使用 PyInstaller 构建应用
"$PYTHON" -m PyInstaller edge-tts-web.spec

# 创建发布包
cd dist
zip -r "${APP_PACKAGE_NAME}-${APP_VERSION}-macOS.zip" "$APP_SLUG"
cd ..

echo "macOS 单文件可执行程序打包完成！"
echo "可执行文件位置: dist/$APP_SLUG"
echo "发布包: dist/${APP_PACKAGE_NAME}-${APP_VERSION}-macOS.zip"
