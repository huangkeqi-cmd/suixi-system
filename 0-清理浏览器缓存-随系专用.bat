@echo off
chcp 65001 >nul
title 随心系统 - 清理浏览器缓存（专用版）
color 0A
echo.
echo ============================================
echo      随心系统 - 浏览器缓存清理工具
echo ============================================
echo.
echo  问题：隐私模式可用，普通模式不可用
echo  原因：浏览器缓存了旧版 viewer 数据
echo  解决：清理本地存储和缓存文件
echo.
echo ============================================
echo.

:: 关闭所有浏览器进程
echo [1/5] 正在关闭浏览器进程...
taskkill /F /IM "msedge.exe" 2>nul
taskkill /F /IM "chrome.exe" 2>nul
taskkill /F /IM "firefox.exe" 2>nul
timeout /t 2 /nobreak >nul
echo      浏览器进程已关闭
echo.

:: 清理 Edge 缓存
echo [2/5] 正在清理 Edge 浏览器缓存...
set "EDGE_DATA=%LOCALAPPDATA%\Microsoft\Edge\User Data"
if exist "%EDGE_DATA%" (
    :: 清理本地存储
    if exist "%EDGE_DATA%\Default\Local Storage" (
        echo      清理 Local Storage...
        rd /S /Q "%EDGE_DATA%\Default\Local Storage" 2>nul
    )
    :: 清理 Session Storage
    if exist "%EDGE_DATA%\Default\Session Storage" (
        echo      清理 Session Storage...
        rd /S /Q "%EDGE_DATA%\Default\Session Storage" 2>nul
    )
    :: 清理 IndexedDB
    if exist "%EDGE_DATA%\Default\IndexedDB" (
        echo      清理 IndexedDB...
        rd /S /Q "%EDGE_DATA%\Default\IndexedDB" 2>nul
    )
    :: 清理 Cache
    if exist "%EDGE_DATA%\Default\Cache" (
        echo      清理 Cache...
        rd /S /Q "%EDGE_DATA%\Default\Cache" 2>nul
    )
    :: 清理 Code Cache
    if exist "%EDGE_DATA%\Default\Code Cache" (
        echo      清理 Code Cache...
        rd /S /Q "%EDGE_DATA%\Default\Code Cache" 2>nul
    )
    :: 清理 Service Worker
    if exist "%EDGE_DATA%\Default\Service Worker" (
        echo      清理 Service Worker...
        rd /S /Q "%EDGE_DATA%\Default\Service Worker" 2>nul
    )
    echo      Edge 缓存清理完成
echo.
)

:: 清理 Chrome 缓存
echo [3/5] 正在清理 Chrome 浏览器缓存...
set "CHROME_DATA=%LOCALAPPDATA%\Google\Chrome\User Data"
if exist "%CHROME_DATA%" (
    :: 清理本地存储
    if exist "%CHROME_DATA%\Default\Local Storage" (
        echo      清理 Local Storage...
        rd /S /Q "%CHROME_DATA%\Default\Local Storage" 2>nul
    )
    :: 清理 Session Storage
    if exist "%CHROME_DATA%\Default\Session Storage" (
        echo      清理 Session Storage...
        rd /S /Q "%CHROME_DATA%\Default\Session Storage" 2>nul
    )
    :: 清理 IndexedDB
    if exist "%CHROME_DATA%\Default\IndexedDB" (
        echo      清理 IndexedDB...
        rd /S /Q "%CHROME_DATA%\Default\IndexedDB" 2>nul
    )
    :: 清理 Cache
    if exist "%CHROME_DATA%\Default\Cache" (
        echo      清理 Cache...
        rd /S /Q "%CHROME_DATA%\Default\Cache" 2>nul
    )
    :: 清理 Code Cache
    if exist "%CHROME_DATA%\Default\Code Cache" (
        echo      清理 Code Cache...
        rd /S /Q "%CHROME_DATA%\Default\Code Cache" 2>nul
    )
    :: 清理 Service Worker
    if exist "%CHROME_DATA%\Default\Service Worker" (
        echo      清理 Service Worker...
        rd /S /Q "%CHROME_DATA%\Default\Service Worker" 2>nul
    )
    echo      Chrome 缓存清理完成
echo.
)

:: 清理系统级临时文件
echo [4/5] 正在清理系统临时文件...
:: 清理 Windows 临时目录中的网页缓存
del /Q /F /S "%TEMP%\*.tmp" 2>nul
del /Q /F /S "%TEMP%\ Temporary Internet Files" 2>nul
:: 清理 IE 缓存 (如果存在)
RunDll32.exe InetCpl.cpl,ClearMyTracksByProcess 8 2>nul
echo      系统临时文件清理完成
echo.

:: 清理 DNS 和 Socket 缓存
echo [5/5] 正在重置网络缓存...
ipconfig /flushdns >nul 2>&1
netsh winsock reset catalog >nul 2>&1
echo      网络缓存重置完成
echo.

echo ============================================
echo.
echo  ✅ 浏览器缓存清理完成！
echo.
echo  现在可以正常使用普通模式浏览器了：
echo.
echo  1. 打开随管，生成/启动查看器
echo  2. 打开普通浏览器窗口（非隐私模式）
echo  3. 访问 http://localhost:8888（或对应端口）
echo  4. 按 Ctrl+F5 强制刷新页面
echo.
echo  💡 提示：如果还有问题，尝试按 F12 打开开发者工具，
echo     在 Network 标签页勾选 "Disable cache" 后刷新
echo.
echo ============================================
echo.
pause
