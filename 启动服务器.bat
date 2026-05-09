@echo off
chcp 65001 >nul
cd /d "%~dp0"
cd PanoramaManager\PanoramaMapper-PC

echo [INFO] 当前目录: %cd%

echo [INFO] 检查依赖...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] 依赖安装失败
    pause
    exit /b 1
)

echo [INFO] 启动程序...
python src\main.py
if errorlevel 1 (
    echo [ERROR] 程序启动失败，错误码: %errorlevel%
    pause
    exit /b 1
)

pause
