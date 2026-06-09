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
tar -czf "Edge-TTS-Web-${APP_VERSION}-Linux.tar.gz" "edge-tts-web"
cd ..

echo "Linux 打包完成！"
echo "发布包: dist/Edge-TTS-Web-${APP_VERSION}-Linux.tar.gz"
