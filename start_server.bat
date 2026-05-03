@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title 随心系统-本地服务器

echo.
echo ============================================
echo           随心系统 本地预览服务器
echo ============================================
echo.
echo [*] 正在获取本机 IP 地址...

:: 提取第一个有效的 IPv4 地址（跳过 127.0.0.1）
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
    set ip=%%a
    set ip=!ip: =!
    if not "!ip!"=="127.0.0.1" (
        echo [√] 本机 IP: !ip!
        echo.
        echo [→] 请在手机浏览器输入：
        echo     http://!ip!:8000/PanoramaCapture/capture.html
        goto start
    )
)

:start
echo.
echo [*] 启动 HTTP 服务器，端口 8000...
echo.
echo 注意：手机和电脑需连同一 WiFi
echo 如果打不开，请暂时关闭防火墙
echo 按 Ctrl+C 停止
echo ============================================
echo.
python -m http.server 8000
pause