@echo off
cd /d "%~dp0"
set "PROJECT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" (
    echo [错误] 未找到项目虚拟环境: "%PROJECT_PYTHON%"
    echo 请先创建 .venv 并安装发版依赖。
    pause
    exit /b 1
)
"%PROJECT_PYTHON%" tools/release_gui.py
