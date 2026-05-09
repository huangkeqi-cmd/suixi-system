@echo off
chcp 65001 >nul
title 随心系统 - 终极修复工具（强制重置）
color 0C
echo.
echo ============================================
echo   ⚠️  随心系统 - 终极修复工具 ⚠️
echo ============================================
echo.
echo  警告：此工具将执行强力清理操作
echo  会关闭所有相关进程并清除缓存
echo.
echo ============================================
echo.
pause
echo.

:: 1. 强力终止所有相关进程
echo [1/8] 强力终止所有相关进程...
taskkill /F /IM "PanoramaManager.exe" 2>nul
taskkill /F /IM "python.exe" 2>nul
taskkill /F /IM "pythonw.exe" 2>nul
taskkill /F /FI "WINDOWTITLE eq *随*" 2>nul
taskkill /F /FI "WINDOWTITLE eq *Panorama*" 2>nul
taskkill /F /FI "WINDOWTITLE eq *Viewer*" 2>nul
echo      进程终止完成
echo.

:: 2. 清理所有相关端口
echo [2/8] 强制释放所有相关端口...
for %%p in (8888 9000 9999 8080 8000 3000 5000) do (
    for /f "skip=4 tokens=2,5" %%a in ('netstat -ano ^| findstr :%%p') do (
        taskkill /F /PID %%b 2>nul >nul
    )
)
echo      端口清理完成
echo.

:: 3. 深度清理临时文件
echo [3/8] 深度清理临时文件...
:: 清理用户临时目录
if exist "%TEMP%" (
    for /d %%D in ("%TEMP%\_MEI*") do rd /S /Q "%%D" 2>nul
    for /d %%D in ("%TEMP%\tmp*") do rd /S /Q "%%D" 2>nul
)
:: 清理系统临时目录
if exist "%WINDIR%\Temp" (
    for /d %%D in ("%WINDIR%\Temp\_MEI*") do rd /S /Q "%%D" 2>nul
)
:: 清理 LocalAppData 临时目录
if exist "%LOCALAPPDATA%\Temp" (
    for /d %%D in ("%LOCALAPPDATA%\Temp\_MEI*") do rd /S /Q "%%D" 2>nul
)
echo      临时文件清理完成
echo.

:: 4. 清理旧版相关文件
echo [4/8] 清理旧版相关文件...
:: 旧版 CodeBuddy 目录
if exist "D:\Users\huangkeqi\CodeBuddy\Claw" (
    echo      发现旧版目录，清理 viewer 和临时文件...
    for /d %%D in ("D:\Users\huangkeqi\CodeBuddy\Claw\*viewer*") do (
        echo        删除: %%D
        rd /S /Q "%%D" 2>nul
    )
    :: 清理旧版生成的 junction 链接
    for /r "D:\Users\huangkeqi\CodeBuddy\Claw" %%L in (external_photos) do (
        if exist "%%L" (
            echo        删除 junction: %%L
            rmdir "%%L" 2>nul
        )
    )
)
echo      旧版清理完成
echo.

:: 5. 清理新版中的 viewer 文件夹
echo [5/8] 清理新版中的 viewer 文件夹...
if exist "D:\Users\huangkeqi\Desktop\随心系统" (
    for /r "D:\Users\huangkeqi\Desktop\随心系统" %%D in (viewer) do (
        if exist "%%D\index.html" (
            echo      清理 viewer: %%D
            rd /S /Q "%%D" 2>nul
        )
    )
)
echo      新版 viewer 清理完成
echo.

:: 6. 重置 Winsock 和网络
echo [6/8] 重置网络组件...
netsh winsock reset >nul 2>&1
netsh int ip reset >nul 2>&1
ipconfig /flushdns >nul 2>&1
echo      网络重置完成（重启后生效）
echo.

:: 7. 清理 Windows 资源管理器缓存
echo [7/8] 清理资源管理器缓存...
ie4uinit.exe -ClearIconCache 2>nul
taskkill /F /IM explorer.exe 2>nul >nul
start explorer.exe
echo      资源管理器缓存清理完成
echo.

:: 8. 清理浏览器相关缓存
echo [8/8] 清理浏览器相关缓存...
:: Edge
if exist "%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Code Cache" (
    rd /S /Q "%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Code Cache" 2>nul
)
:: Chrome  
if exist "%LOCALAPPDATA%\Google\Chrome\User Data\Default\Code Cache" (
    rd /S /Q "%LOCALAPPDATA%\Google\Chrome\User Data\Default\Code Cache" 2>nul
)
echo      浏览器缓存清理完成
echo.

echo ============================================
echo.
echo  ✅ 终极修复完成！
echo.
echo  重要提示：
echo  ─────────────────────────────────────
echo  1. 请立即重启电脑以确保所有更改生效
echo  2. 重启后先运行旧版随管测试
echo  3. 新旧版本请勿同时运行
echo  4. 建议浏览器使用隐私模式测试查看器
echo.
echo  ─────────────────────────────────────
echo.
set /p restart="是否立即重启电脑？(Y/N): "
if /I "%restart%"=="Y" (
    echo 系统将在 5 秒后重启...
    timeout /t 5 /nobreak >nul
    shutdown /r /t 0
) else (
    echo.
    echo 请记得手动重启电脑以完成修复！
    pause
)
