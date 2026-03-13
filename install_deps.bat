@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo Installing release/build dependencies into .venv...
".venv\Scripts\python.exe" -m pip install --index-url https://pypi.org/simple --trusted-host pypi.org --trusted-host files.pythonhosted.org -r tools\requirements.txt PySide6
echo Done!
pause
