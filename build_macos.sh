#!/bin/bash

APP_VERSION="v0.6"

# 激活虚拟环境
source venv/bin/activate

# 清理之前的构建
rm -rf build dist

# 使用 PyInstaller 构建应用
pyinstaller edge-tts-web.spec

# 创建发布包
cd dist
zip -r "Edge-TTS-Web-${APP_VERSION}-macOS.zip" "edge-tts-web"
cd ..

echo "macOS 单文件可执行程序打包完成！"
echo "可执行文件位置: dist/edge-tts-web"
echo "发布包: dist/Edge-TTS-Web-${APP_VERSION}-macOS.zip"
