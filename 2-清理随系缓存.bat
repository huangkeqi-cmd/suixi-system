@echo off
chcp 65001 >nul
title 随心系统 - 一键清理工具
color 0B
echo.
echo ============================================
echo      随心系统 / Suixin System
echo      一键清理工具
echo ============================================
echo.
echo  本工具用于解决新旧版本冲突问题
echo  清理内容：端口占用、浏览器缓存、临时文件
echo.
echo ============================================
echo.

:: 1. 关闭所有随管相关进程
echo [1/6] 正在关闭随管进程...
taskkill /F /FI "IMAGENAME eq PanoramaManager*.exe" 2>nul
taskkill /F /FI "IMAGENAME eq python*.exe" /FI "WINDOWTITLE eq *随管*" 2>nul
taskkill /F /FI "WINDOWTITLE eq *PanoramaManager*" 2>nul
echo      进程清理完成
echo.

:: 2. 释放端口 8888, 9000, 9999
echo [2/6] 正在释放占用的端口...
for %%p in (8888 9000 9999 8080) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%%p ^| findstr LISTENING') do (
        echo      正在终止占用端口 %%p 的进程 PID: %%a
        taskkill /F /PID %%a 2>nul
    )
)
echo      端口释放完成
echo.

:: 3. 清理 Windows 临时目录中的 PyInstaller 缓存
echo [3/6] 正在清理 PyInstaller 临时文件...
for /d %%D in ("%TEMP%\_MEI*") do (
    echo      删除: %%D
    rd /S /Q "%%D" 2>nul
)
for /d %%D in ("%LOCALAPPDATA%\Temp\_MEI*") do (
    echo      删除: %%D
    rd /S /Q "%%D" 2>nul
)
echo      PyInstaller 缓存清理完成
echo.

:: 4. 清理浏览器缓存（Edge/Chrome 本地存储）
echo [4/6] 正在清理浏览器本地存储缓存...
set "EDGE_CACHE=%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Storage"
set "CHROME_CACHE=%LOCALAPPDATA%\Google\Chrome\User Data\Default\Storage"

if exist "%EDGE_CACHE%\ext" (
    echo      清理 Edge 扩展存储...
    rd /S /Q "%EDGE_CACHE%\ext" 2>nul
)
if exist "%CHROME_CACHE%\ext" (
    echo      清理 Chrome 扩展存储...
    rd /S /Q "%CHROME_CACHE%\ext" 2>nul
)
echo      浏览器存储清理完成
echo.

:: 5. 清理随管生成的临时 viewer 目录（针对旧版 CodeBuddy 路径）
echo [5/6] 正在清理旧版 viewer 目录...
if exist "D:\Users\huangkeqi\CodeBuddy\Claw" (
    echo      发现旧版目录，清理其中的 viewer 文件夹...
    for /d %%D in ("D:\Users\huangkeqi\CodeBuddy\Claw\*viewer*") do (
        echo      删除: %%D
        rd /S /Q "%%D" 2>nul
    )
    for /d %%D in ("D:\Users\huangkeqi\CodeBuddy\Claw\*viewer*") do (
        if exist "%%D\external_photos" (
            echo      删除 junction: %%D\external_photos
            rmdir "%%D\external_photos" 2>nul
        )
    )
)
echo      旧版目录清理完成
echo.

:: 6. 重置 Windows 网络缓存
echo [6/6] 正在重置网络缓存...
ipconfig /flushdns >nul 2>&1
echo      DNS 缓存已刷新
echo.

echo ============================================
echo.
echo  清理完成！现在可以正常使用旧版随管了。
echo.
echo  建议操作：
echo  1. 重启浏览器后再打开查看器
echo  2. 如果问题仍然存在，尝试重启电脑
echo  3. 新旧版本不要同时运行
echo.
echo ============================================
echo.
pause
