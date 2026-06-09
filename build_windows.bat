@echo off
set APP_VERSION=v0.6

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 清理之前的构建
rmdir /s /q build dist

REM 使用 PyInstaller 构建应用
pyinstaller edge-tts-web.spec

REM 创建发布包
cd dist
powershell Compress-Archive -Path "edge-tts-web.exe" -DestinationPath "Edge-TTS-Web-%APP_VERSION%-Windows.zip"
cd ..

echo Windows 打包完成！
echo 发布包: dist\Edge-TTS-Web-%APP_VERSION%-Windows.zip
pause 
