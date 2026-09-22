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

echo [信息] 步骤 1/2：预编译查看器启动器（双击查看.exe）...
python -m PyInstaller ^
    --name "双击查看" ^
    --onefile ^
    --noconsole ^
    --clean ^
    --distpath ".\PanoramaManager\PanoramaMapper-PC\launcher" ^
    --workpath ".\PanoramaManager\PanoramaMapper-PC\build\launcher_build" ^
    --specpath ".\PanoramaManager\PanoramaMapper-PC\build" ^
    ".\PanoramaManager\PanoramaMapper-PC\launcher\launcher.py"

if errorlevel 1 (
    echo [错误] 启动器预编译失败，请检查上方错误信息。
    pause
    exit /b 1
)

if exist ".\PanoramaManager\PanoramaMapper-PC\build\双击查看.spec" del ".\PanoramaManager\PanoramaMapper-PC\build\双击查看.spec"

echo [信息] 步骤 2/2：打包影像管理器（内嵌预编译启动器）...
python -m PyInstaller ^
    --name "随系影像管理器" ^
    --onefile ^
    --noconsole ^
    --add-data "%~dp0PanoramaManager\PanoramaMapper-PC\launcher\双击查看.exe;launcher_template" ^
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
echo 已内嵌「双击查看.exe」，任何电脑导出查看包均可直接使用。
pause
