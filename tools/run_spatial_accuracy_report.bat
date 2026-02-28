@echo off
setlocal
cd /d "%~dp0.."
python tools\spatial_accuracy_report.py --output-dir dist\qa
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] Spatial accuracy validation failed. See dist\qa\spatial_accuracy_report_latest.md
  exit /b %EXIT_CODE%
)
echo.
echo [OK] Spatial accuracy validation passed. Report saved to dist\qa
exit /b 0

