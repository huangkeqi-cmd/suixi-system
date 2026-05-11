@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   随系 · 影像管理器 - 打包脚本
echo ============================================================

echo [信息] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请确认已安装并添加到 PATH。
    pause
    exit /b 1
)
echo [信息] Python 环境正常

echo [信息] 正在打包，请稍候...

python -m PyInstaller ^
    --name "随系影像管理器" ^
    --onefile ^
    --noconsole ^
    --distpath ".\PanoramaManager\PanoramaMapper-PC\dist" ^
    --workpath ".\PanoramaManager\PanoramaMapper-PC\build" ^
    --specpath ".\PanoramaManager\PanoramaMapper-PC" ^
    ".\PanoramaManager\PanoramaMapper-PC\src\main.py"

if errorlevel 1 (
    echo [错误] 打包失败，请检查上方错误信息。
    pause
    exit /b 1
)

echo.
echo [成功] 打包完成！
echo 输出文件：.\PanoramaManager\PanoramaMapper-PC\dist\随系影像管理器.exe
pause