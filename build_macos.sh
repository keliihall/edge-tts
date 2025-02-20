#!/bin/bash

# 激活虚拟环境
source venv/bin/activate

# 清理之前的构建
rm -rf build dist

# 使用 PyInstaller 构建应用
pyinstaller edge-tts-web.spec

# 创建发布包
cd dist
mv "Edge TTS Web" "Edge TTS Web.app"
zip -r "Edge-TTS-Web-macOS.zip" "Edge TTS Web.app"
cd ..

echo "macOS 打包完成！" 