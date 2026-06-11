@echo off
setlocal

set PYTHON=python
if exist .venv\Scripts\python.exe set PYTHON=.venv\Scripts\python.exe
if exist venv\Scripts\python.exe set PYTHON=venv\Scripts\python.exe
for /f %%i in ('%PYTHON% -c "from version import APP_VERSION; print(APP_VERSION)"') do set APP_VERSION=v%%i
for /f %%i in ('%PYTHON% -c "from version import APP_PACKAGE_NAME; print(APP_PACKAGE_NAME)"') do set APP_PACKAGE_NAME=%%i
for /f %%i in ('%PYTHON% -c "from version import APP_SLUG; print(APP_SLUG)"') do set APP_SLUG=%%i

REM 清理之前的构建
rmdir /s /q build dist

REM 使用 PyInstaller 构建应用
%PYTHON% -m PyInstaller edge-tts-web.spec

REM 创建发布包
cd dist
powershell Compress-Archive -Path "%APP_SLUG%.exe" -DestinationPath "%APP_PACKAGE_NAME%-%APP_VERSION%-Windows.zip"
cd ..

echo Windows 打包完成！
echo 发布包: dist\%APP_PACKAGE_NAME%-%APP_VERSION%-Windows.zip
pause 
