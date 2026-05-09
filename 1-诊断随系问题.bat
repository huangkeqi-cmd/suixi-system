@echo off
chcp 65001 >nul
title 随心系统 - 问题诊断工具
color 0E
echo.
echo ============================================
echo      随心系统 / Suixin System
echo      问题诊断工具
echo ============================================
echo.

:: 检查端口占用
echo [端口占用检查]
echo ----------------------------------------
for %%p in (8888 9000 9999 8080) do (
    echo 检查端口 %%p...
    netstat -ano | findstr :%%p | findstr LISTING >nul
    if !errorlevel! equ 0 (
        echo   [占用] 端口 %%p 被占用：
        for /f "tokens=2,5" %%a in ('netstat -ano ^| findstr :%%p ^| findstr LISTENING') do (
            echo     地址: %%a, PID: %%b
            for /f "tokens=1" %%c in ('tasklist ^| findstr %%b') do (
                echo     进程: %%c
            )
        )
    ) else (
        echo   [空闲] 端口 %%p 未被占用
    )
)
echo.

:: 检查 Python 进程
echo [Python 进程检查]
echo ----------------------------------------
tasklist | findstr python >nul
if %errorlevel% equ 0 (
    echo 发现 Python 进程：
    tasklist | findstr python
) else (
    echo 未发现 Python 进程
)
echo.

:: 检查随管进程
echo [随管进程检查]
echo ----------------------------------------
tasklist | findstr PanoramaManager >nul
if %errorlevel% equ 0 (
    echo 发现随管进程：
    tasklist | findstr PanoramaManager
) else (
    echo 未发现随管进程
)
echo.

:: 检查旧版目录
echo [旧版目录检查]
echo ----------------------------------------
if exist "D:\Users\huangkeqi\CodeBuddy\Claw" (
    echo [发现] 旧版目录存在：
    echo   D:\Users\huangkeqi\CodeBuddy\Claw
    dir /B "D:\Users\huangkeqi\CodeBuddy\Claw" 2>nul | findstr /C:"viewer" >nul
    if %errorlevel% equ 0 (
        echo   [警告] 旧版目录中发现 viewer 文件夹，可能与新版本冲突
    )
) else (
    echo [正常] 未发现旧版目录
)
echo.

:: 检查 PyInstaller 临时文件
echo [PyInstaller 临时文件检查]
echo ----------------------------------------
set found_mei=0
for /d %%D in ("%TEMP%\_MEI*") do (
    if %found_mei% equ 0 echo [发现] 临时目录中存在 _MEI 文件夹：
    set found_mei=1
    echo   %%D
)
if %found_mei% equ 0 echo [正常] 未发现 _MEI 临时文件夹
echo.

:: 检查新版 viewer 目录
echo [新版项目检查]
echo ----------------------------------------
if exist "D:\Users\huangkeqi\Desktop\随心系统\PanoramaManager" (
    echo [发现] 新版目录存在
    echo   检查项目中的 viewer 文件夹...
    for /r "D:\Users\huangkeqi\Desktop\随心系统" %%D in (*viewer*) do (
        if exist "%%D\index.html" (
            echo   [viewer] %%D\index.html
        )
    )
) else (
    echo [警告] 新版目录未找到
)
echo.

echo ============================================
echo.
echo 诊断完成！根据上方结果：
echo.
echo 常见问题及解决方案：
echo.
echo 1. [端口占用] - 运行"清理随系缓存.bat"释放端口
echo 2. [Python进程冲突] - 关闭所有Python进程后重试
echo 3. [旧版viewer冲突] - 删除旧版目录中的viewer文件夹
echo 4. [PyInstaller缓存] - 运行清理脚本删除临时文件
echo.
echo ============================================
pause
