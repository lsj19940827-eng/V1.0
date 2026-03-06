@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === 开始清理 ===

set BASE=%~dp0

REM 使用 PowerShell 的 VisualBasic 回收站功能逐个处理
powershell -NoProfile -Command "Add-Type -AssemblyName Microsoft.VisualBasic; $b='%BASE%'; @('fix_example1.py','fix_example2.py','fix_panel.py','test_case_management.py','test_example_data_enhancement.py','test_pressure_pipe_ui.py','test_siphon_example.py','test_siphon_example_flag.py','test_siphon_max_flow_loss.py','test_siphon_ui_detail.py','manual_test_example_data.py','audit_siphon.py','update_gist_only.py','upload_to_release.py','create_release.py','debug.log','data\run_errors.log','tools\compare_result.txt') | ForEach-Object { $p=Join-Path $b $_; if(Test-Path $p){[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p,'OnlyErrorDialogs','SendToRecycleBin'); Write-Host '[回收站]' $_}else{Write-Host '[跳过]  ' $_ '(不存在)'} }"

echo.
echo === 清理目录 ===

powershell -NoProfile -Command "Add-Type -AssemblyName Microsoft.VisualBasic; $b='%BASE%'; @('data\_test_auto_confirm','data\_test_unified_confirm','dist','.pytest_cache') | ForEach-Object { $p=Join-Path $b $_; if(Test-Path $p){[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($p,'OnlyErrorDialogs','SendToRecycleBin'); Write-Host '[回收站]' $_ '/'}else{Write-Host '[跳过]  ' $_ '/ (不存在)'} }"

echo.
echo === 清理完成 ===
pause
