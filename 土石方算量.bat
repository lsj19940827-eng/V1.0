@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m app_渠系计算前端.app --earthwork
) else (
  python -m app_渠系计算前端.app --earthwork
)
