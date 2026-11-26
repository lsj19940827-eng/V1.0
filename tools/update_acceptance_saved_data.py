# -*- coding: utf-8 -*-
"""Drive the official old application through its normal case autosave UI."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from tools import release_acceptance as gate


_UI_AUTOMATION = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$window = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]@HWND@)
$scope = [System.Windows.Automation.TreeScope]::Descendants
$name = [System.Windows.Automation.AutomationElement]::NameProperty
$type = [System.Windows.Automation.AutomationElement]::ControlTypeProperty
if ('@ACTION@' -eq 'open') {
    $condition = [System.Windows.Automation.PropertyCondition]::new($name, '倒虹吸设计')
    foreach ($button in $window.FindAll($scope, $condition)) {
        $pattern = $null
        if ($button.Current.IsEnabled -and $button.TryGetCurrentPattern(
            [System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
            $pattern.Invoke()
            Write-Output 'opened'
            return
        }
    }
    return
}
$text = [System.Windows.Automation.PropertyCondition]::new($type, [System.Windows.Automation.ControlType]::Text)
$edit = [System.Windows.Automation.PropertyCondition]::new($type, [System.Windows.Automation.ControlType]::Edit)
$labels = @($window.FindAll($scope, $text) | Where-Object {
    -not $_.Current.IsOffscreen -and $_.Current.Name.StartsWith('设计流量 Q (')
})
if ($labels.Count -ne 1) {
    Write-Output "Visible flow labels: $($labels.Count)"
    return
}
$label = $labels[0].Current.BoundingRectangle
$fields = @($window.FindAll($scope, $edit) | Where-Object {
    $bounds = $_.Current.BoundingRectangle
    $_.Current.IsEnabled -and -not $_.Current.IsOffscreen -and -not $bounds.IsEmpty -and
        [Math]::Abs($bounds.Left - $label.Left) -le 12 -and
        $bounds.Top -ge $label.Bottom - 4 -and $bounds.Top -le $label.Bottom + 2 * $label.Height
} | Sort-Object { $_.Current.BoundingRectangle.Top })
foreach ($field in $fields) {
    $value = $null
    if ($field.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$value) -and
        -not $value.Current.IsReadOnly) {
        Write-Output "Flow field before edit: $($value.Current.Value)"
        $value.SetValue('@FLOW@')
        if ($value.Current.Value -eq '@FLOW@') {
            Write-Output 'edited'
            return
        }
    }
}
Write-Output "Editable flow candidates: $($fields.Count)"
"""


def _operate(hwnd, action, flow, output):
    command = (_UI_AUTOMATION.replace("@HWND@", str(int(hwnd)))
               .replace("@ACTION@", action).replace("@FLOW@", str(flow)))
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run(
        [str(executable), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, encoding="utf-8", errors="replace", timeout=12,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    with (output / "case-ui.log").open("a", encoding="utf-8") as stream:
        stream.write(f"{action} exit={result.returncode}\n{result.stdout}{result.stderr}\n")
    gate.require(result.returncode == 0, f"旧版工况 UI 操作失败，日志：{output / 'case-ui.log'}")
    return result.stdout.splitlines()


def save_formal_case(probe, app, version, output):
    """Edit an existing case and wait for the EXE to write the new flow to disk."""
    output.mkdir(parents=True, exist_ok=True)
    existing = {path: path.read_bytes() for data in (app / "_internal/data", app / "data")
                for path in (data / "siphon_cases").glob("*.siphon.json")}
    gate.require(existing, f"正式旧版 V{version} 安装包缺少已有倒虹吸工况")
    initial_flows = {path: json.loads(content).get("Q") for path, content in existing.items()}
    flow = next(value for value in (12.345, 23.456, 34.567) if value not in initial_flows.values())
    executable = app / "CanalHydraulicCalc.exe"
    executable_sha256 = gate.release_snapshot.sha256_file(str(executable))
    process = subprocess.Popen([str(executable)], cwd=app)
    try:
        start = time.monotonic()
        title = None
        observed_titles = set()
        while time.monotonic() - start < 45 and process.poll() is None:
            for window in probe.windows(probe.descendants(process.pid)):
                observed_titles.add(window["title"])
                if f"V{version}" in window["title"] and window["responsive"]:
                    if "opened" in _operate(window["hwnd"], "open", flow, output):
                        title = window["title"]
                        break
            if title:
                break
            time.sleep(0.5)
        if not title:
            with (output / "case-ui.log").open("a", encoding="utf-8") as stream:
                stream.write(f"启动期间观察到的窗口：{sorted(observed_titles)}\n")
            raise gate.AcceptanceError(f"未能打开 V{version} 倒虹吸设计，日志：{output / 'case-ui.log'}")

        start = time.monotonic()
        edited = False
        while time.monotonic() - start < 15 and process.poll() is None:
            if "edited" in _operate(window["hwnd"], "edit", flow, output):
                edited = True
                break
            time.sleep(0.5)
        gate.require(edited, f"未能修改 V{version} 设计流量，日志：{output / 'case-ui.log'}")

        start = time.monotonic()
        while time.monotonic() - start < 15 and process.poll() is None:
            for path, old_content in existing.items():
                if not path.is_file():
                    continue
                new_content = path.read_bytes()
                if new_content == old_content:
                    continue
                try:
                    saved_flow = json.loads(new_content).get("Q")
                except (ValueError, UnicodeError):
                    continue
                if saved_flow != flow:
                    continue
                gate.require(probe.close(process), f"V{version} 保存工况后未正常关闭")
                gate.require(json.loads(path.read_bytes()).get("Q") == flow,
                             f"V{version} 关闭后工况内容发生变化")
                return {
                    "source_version": version,
                    "executable_sha256": executable_sha256,
                    "window_title": title,
                    "path": path.relative_to(app).as_posix(),
                    "before_flow": initial_flows[path],
                    "saved_flow": flow,
                    "before_sha256": hashlib.sha256(old_content).hexdigest(),
                    "saved_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "normal_exit": True,
                }
            time.sleep(0.25)
        raise gate.AcceptanceError(f"V{version} 正式应用未自动保存修改后的工况，日志：{output / 'case-ui.log'}")
    finally:
        if process.poll() is None:
            probe.close(process)
