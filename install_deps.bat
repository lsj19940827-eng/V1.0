@echo off
chcp 65001 > nul
echo Installing PySide6...
"%~dp0.venv\Scripts\pip.exe" install PySide6
echo Done!
pause
