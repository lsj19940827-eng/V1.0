# -*- coding: utf-8 -*-
"""Qt WebEngine startup diagnostics and emergency runtime controls."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

EMERGENCY_SINGLE_PROCESS_ENV = "CANAL_QTWEBENGINE_FORCE_SINGLE_PROCESS"
EMERGENCY_SINGLE_PROCESS_FLAGS = ("--single-process", "--disable-gpu")
PROBE_TIMEOUT_SECONDS = 8
PROBE_CHILD_ARG = "--webengine-probe-child"
_PROBE_SUCCESS_TOKEN = "WEBENGINE_PROBE_OK"


@dataclass(frozen=True)
class WebEngineProbeResult:
    ok: bool
    failure_kind: str
    exit_code: int | None
    stdout: str
    stderr: str
    python_executable: str
    python_version: str
    platform_summary: str
    windows_build: str
    pyside_version: str
    qt_webengine_process_path: str
    qt_webengine_process_exists: bool
    import_error: str = ""
    probe_timeout: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def emergency_single_process_requested() -> bool:
    """Return whether the hidden emergency single-process mode is enabled."""
    return _env_flag(EMERGENCY_SINGLE_PROCESS_ENV)


def _merge_chromium_flags(existing_flags: str, required_flags: tuple[str, ...]) -> str:
    tokens = [token for token in str(existing_flags or "").split() if token]
    merged = []
    for token in required_flags:
        if token not in merged:
            merged.append(token)
    for token in tokens:
        if token not in merged:
            merged.append(token)
    return " ".join(merged)


def apply_emergency_single_process_mode() -> str:
    """Force Qt WebEngine to use Chromium single-process mode for this process."""
    merged = _merge_chromium_flags(
        os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""),
        EMERGENCY_SINGLE_PROCESS_FLAGS,
    )
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = merged
    return merged


def _current_runtime_facts() -> dict:
    python_version = sys.version.splitlines()[0].strip()
    windows_build = ""
    try:
        windows_build = str(sys.getwindowsversion().build)
    except Exception:
        windows_build = ""

    facts = {
        "python_executable": sys.executable,
        "python_version": python_version,
        "platform_summary": platform.platform(),
        "windows_build": windows_build,
        "pyside_version": "",
        "qt_webengine_process_path": "",
        "qt_webengine_process_exists": False,
        "import_error": "",
        "is_frozen_runtime": bool(getattr(sys, "frozen", False)),
    }

    try:
        from PySide6 import __version__ as pyside_version

        facts["pyside_version"] = str(pyside_version)
    except Exception as exc:
        facts["import_error"] = f"PySide6 导入失败: {exc}"
        return facts

    try:
        from PySide6.QtCore import QLibraryInfo

        exec_dir = Path(
            QLibraryInfo.path(QLibraryInfo.LibraryPath.LibraryExecutablesPath)
        )
        qt_process_path = exec_dir / "QtWebEngineProcess.exe"
        facts["qt_webengine_process_path"] = str(qt_process_path)
        facts["qt_webengine_process_exists"] = qt_process_path.exists()
    except Exception:
        pass

    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    except Exception as exc:
        facts["import_error"] = str(exc)

    return facts


def classify_probe_failure(stdout: str, stderr: str, exit_code: int | None) -> str:
    combined = "\n".join(part for part in (stdout, stderr) if part).lower()
    if ("hannel-pipe(89)" in combined or "channel-pipe(89)" in combined) and "0x5" in combined:
        return "ipc-access-denied"
    if "hannel-pipe(89)" in combined and (
        "access is denied" in combined or "拒绝访问" in combined
    ):
        return "ipc-access-denied"
    if "channel-pipe(89)" in combined and (
        "access is denied" in combined or "拒绝访问" in combined
    ):
        return "ipc-access-denied"
    if "access is denied" in combined and "qwebengineprocess" in combined:
        return "ipc-access-denied"
    if "拒绝访问" in combined and "qwebengineprocess" in combined:
        return "ipc-access-denied"
    if exit_code in (None, 0):
        return "unknown"
    return "unknown"


def _tail_text(value: str, *, max_lines: int = 20) -> str:
    lines = [line.rstrip() for line in str(value or "").splitlines() if line.strip()]
    if not lines:
        return ""
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[-max_lines:])


def _main_script_path() -> Path:
    return Path(__file__).resolve().parents[1] / "main.py"


def _probe_child_command(facts: dict) -> list[str]:
    if facts.get("is_frozen_runtime"):
        return [facts["python_executable"], PROBE_CHILD_ARG]

    cmd = [facts["python_executable"], "-X", "faulthandler"]
    main_script = _main_script_path()
    if main_script.exists():
        cmd.extend([str(main_script), PROBE_CHILD_ARG])
        return cmd

    raise FileNotFoundError(f"未找到 WebEngine 探测入口脚本: {main_script}")


def is_webengine_probe_child_command(argv: list[str] | tuple[str, ...]) -> bool:
    return PROBE_CHILD_ARG in list(argv or [])


def run_webengine_probe_child() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView

    app = QApplication.instance() or QApplication([])
    state = {"loaded": False, "ok": False}
    view = QWebEngineView()

    def _on_load_finished(ok):
        state["loaded"] = True
        state["ok"] = bool(ok)

    view.loadFinished.connect(_on_load_finished)
    view.setHtml("<html><body><h1>Qt WebEngine Probe</h1><p>ok</p></body></html>")

    deadline = time.time() + 2.5
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
        if state["loaded"]:
            break

    if not state["loaded"]:
        print("WEBENGINE_PROBE_TIMEOUT", file=sys.stderr)
        return 3

    if not state["ok"]:
        print("WEBENGINE_PROBE_LOAD_FAILED", file=sys.stderr)
        return 4

    print(_PROBE_SUCCESS_TOKEN)
    return 0


def probe_standard_webengine(*, timeout_seconds: int = PROBE_TIMEOUT_SECONDS) -> WebEngineProbeResult:
    """Run a minimal standard-mode Qt WebEngine probe in a child process."""
    facts = _current_runtime_facts()
    base_kwargs = {
        "python_executable": facts["python_executable"],
        "python_version": facts["python_version"],
        "platform_summary": facts["platform_summary"],
        "windows_build": facts["windows_build"],
        "pyside_version": facts["pyside_version"],
        "qt_webengine_process_path": facts["qt_webengine_process_path"],
        "qt_webengine_process_exists": facts["qt_webengine_process_exists"],
        "stdout": "",
        "stderr": "",
        "exit_code": None,
        "import_error": facts["import_error"],
    }

    if facts["import_error"]:
        return WebEngineProbeResult(
            ok=False,
            failure_kind="import-error",
            probe_timeout=False,
            **base_kwargs,
        )

    if not facts["qt_webengine_process_exists"]:
        return WebEngineProbeResult(
            ok=False,
            failure_kind="missing-process",
            probe_timeout=False,
            **base_kwargs,
        )

    env = os.environ.copy()
    env.pop(EMERGENCY_SINGLE_PROCESS_ENV, None)

    try:
        completed = subprocess.run(
            _probe_child_command(facts),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "").strip()
        stderr = (exc.stderr or "").strip()
        failure_kind = classify_probe_failure(stdout, stderr, None)
        if failure_kind == "unknown":
            failure_kind = "timeout"
        return WebEngineProbeResult(
            ok=False,
            failure_kind=failure_kind,
            exit_code=None,
            stdout=stdout,
            stderr=stderr,
            probe_timeout=True,
            **{
                key: value
                for key, value in base_kwargs.items()
                if key not in {"stdout", "stderr", "exit_code"}
            },
        )

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode == 0 and _PROBE_SUCCESS_TOKEN in stdout:
        return WebEngineProbeResult(
            ok=True,
            failure_kind="none",
            exit_code=0,
            stdout=stdout,
            stderr=stderr,
            probe_timeout=False,
            **{
                key: value
                for key, value in base_kwargs.items()
                if key not in {"stdout", "stderr", "exit_code"}
            },
        )

    return WebEngineProbeResult(
        ok=False,
        failure_kind=classify_probe_failure(stdout, stderr, completed.returncode),
        exit_code=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        probe_timeout=False,
        **{
            key: value
            for key, value in base_kwargs.items()
            if key not in {"stdout", "stderr", "exit_code"}
        },
    )


def build_failure_summary(result: WebEngineProbeResult) -> str:
    """Return the user-facing summary for a startup-blocking WebEngine failure."""
    if result.failure_kind == "import-error":
        return (
            "当前环境无法导入 Qt WebEngine 组件，程序未继续启动。"
        )
    if result.failure_kind == "missing-process":
        return (
            "当前环境缺少 QtWebEngineProcess.exe，程序未继续启动。"
        )
    if result.failure_kind == "timeout":
        return (
            "Qt WebEngine 标准模式预检超时，程序未继续启动。"
        )
    if result.failure_kind == "ipc-access-denied":
        return (
            "检测到 Qt WebEngine 标准模式在首次导航时触发了多进程 IPC“拒绝访问”，"
            "程序未继续启动。"
        )
    return "Qt WebEngine 标准模式预检失败，程序未继续启动。"


def build_failure_instructions(result: WebEngineProbeResult) -> list[str]:
    """Return deterministic remediation guidance for startup failures."""
    _ = result
    return [
        "检查并放行 python.exe / pythonw.exe / QtWebEngineProcess.exe。",
        "检查 Windows Defender、Exploit Protection 或第三方安全软件是否拦截子进程或 IPC。",
        "运行 tools/qt_webengine_doctor.py 导出诊断结果。",
        f"仅在必须继续工作的场景下，手动设置 {EMERGENCY_SINGLE_PROCESS_ENV}=1 启用 WebEngine 应急单进程模式。",
    ]


def format_probe_report(result: WebEngineProbeResult) -> str:
    """Format a support-friendly diagnostic report."""
    details = [
        "Qt WebEngine 诊断信息",
        f"ok: {result.ok}",
        f"failure_kind: {result.failure_kind}",
        f"exit_code: {result.exit_code}",
        f"python_executable: {result.python_executable}",
        f"python_version: {result.python_version}",
        f"platform_summary: {result.platform_summary}",
        f"windows_build: {result.windows_build}",
        f"pyside_version: {result.pyside_version}",
        f"qt_webengine_process_path: {result.qt_webengine_process_path}",
        f"qt_webengine_process_exists: {result.qt_webengine_process_exists}",
    ]
    if result.import_error:
        details.append(f"import_error: {result.import_error}")

    stdout_tail = _tail_text(result.stdout)
    stderr_tail = _tail_text(result.stderr)
    if stdout_tail:
        details.extend(["stdout_tail:", stdout_tail])
    if stderr_tail:
        details.extend(["stderr_tail:", stderr_tail])

    details.extend(["", "建议："])
    for index, step in enumerate(build_failure_instructions(result), start=1):
        details.append(f"{index}. {step}")
    return "\n".join(details)


def probe_result_json(result: WebEngineProbeResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
