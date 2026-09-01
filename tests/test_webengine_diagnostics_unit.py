# -*- coding: utf-8 -*-
"""Unit tests for Qt WebEngine startup diagnostics and bootstrap flow."""

import importlib
import os
import sys
import tempfile
import types
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE_PACKAGE = "app_渠系计算前端"

diagnostics = importlib.import_module(BASE_PACKAGE + ".webengine_diagnostics")
bootstrap = importlib.import_module(BASE_PACKAGE + ".bootstrap")
startup_context_module = importlib.import_module(BASE_PACKAGE + ".startup_context")


def _probe_result(**overrides):
    payload = {
        "ok": False,
        "failure_kind": "ipc-access-denied",
        "exit_code": 1,
        "stdout": "",
        "stderr": "[123:456:FATAL:hannel-pipe(89)] Check failed: . : Access is denied. (0x5)",
        "python_executable": sys.executable,
        "python_version": sys.version.splitlines()[0],
        "platform_summary": "Windows-11-10.0.26100-SP0",
        "windows_build": "26100",
        "pyside_version": "6.10.2",
        "qt_webengine_process_path": r"C:\Python\Lib\site-packages\PySide6\QtWebEngineProcess.exe",
        "qt_webengine_process_exists": True,
        "import_error": "",
        "probe_timeout": False,
    }
    payload.update(overrides)
    return diagnostics.WebEngineProbeResult(**payload)


def _startup_context(**overrides):
    payload = {
        "webengine_mode": "standard",
        "webengine_probe_result": _probe_result(ok=True, failure_kind="none", exit_code=0),
        "update_checks_enabled": True,
        "is_frozen_runtime": False,
    }
    payload.update(overrides)
    return startup_context_module.StartupContext(**payload)


def test_classify_probe_failure_recognizes_channel_pipe_access_denied():
    failure_kind = diagnostics.classify_probe_failure(
        "",
        "[123:456:FATAL:hannel-pipe(89)] Check failed: . : 拒绝访问。 (0x5)",
        1,
    )

    assert failure_kind == "ipc-access-denied"


def test_classify_probe_failure_recognizes_plain_windows_access_denied():
    failure_kind = diagnostics.classify_probe_failure(
        "",
        "[123:456:FATAL:x:82] Check failed: . : 拒绝访问。 (0x5)",
        3,
    )

    assert failure_kind == "ipc-access-denied"


def test_current_runtime_facts_avoids_blocking_platform_platform(monkeypatch):
    monkeypatch.setattr(
        diagnostics.platform,
        "platform",
        lambda: (_ for _ in ()).throw(AssertionError("platform.platform should not be called")),
    )
    monkeypatch.setattr(
        diagnostics.sys,
        "getwindowsversion",
        lambda: types.SimpleNamespace(
            major=10,
            minor=0,
            build=26100,
            service_pack_major=0,
        ),
    )

    facts = diagnostics._current_runtime_facts()

    assert facts["platform_summary"] == "Windows-11-10.0.26100-SP0"


def test_windows_platform_wmi_guard_prevents_platform_machine_from_calling_wmi(monkeypatch):
    if not sys.platform.startswith("win"):
        pytest.skip("Windows 专用的启动兼容测试")

    import platform as std_platform

    calls = []

    def _blocking_wmi_query(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("platform WMI query should be disabled before pandas import")

    monkeypatch.setattr(
        std_platform,
        "_v1_platform_wmi_guard_installed",
        False,
        raising=False,
    )
    monkeypatch.setattr(std_platform, "_wmi_query", _blocking_wmi_query, raising=False)
    monkeypatch.setattr(std_platform, "_uname_cache", None, raising=False)

    bootstrap.ensure_safe_windows_platform_queries()

    assert std_platform.machine()
    assert calls == []


def test_initialize_runtime_environment_installs_platform_wmi_guard(monkeypatch):
    calls = []

    monkeypatch.setattr(
        bootstrap,
        "ensure_safe_windows_platform_queries",
        lambda: calls.append("platform_guard"),
    )
    monkeypatch.setattr(bootstrap, "_set_windows_app_user_model_id", lambda: None)
    monkeypatch.setattr(bootstrap.QApplication, "instance", lambda: object())

    bootstrap.initialize_runtime_environment()

    assert calls == ["platform_guard"]


def test_apply_emergency_single_process_mode_merges_flags_without_duplication(monkeypatch):
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --foo")

    merged = diagnostics.apply_emergency_single_process_mode()

    assert merged.split().count("--single-process") == 1
    assert merged.split().count("--disable-gpu") == 1
    assert "--foo" in merged.split()


def test_probe_standard_webengine_short_circuits_when_process_is_missing(monkeypatch):
    monkeypatch.setattr(
        diagnostics,
        "_current_runtime_facts",
        lambda: {
            "python_executable": sys.executable,
            "python_version": "3.13.3",
            "platform_summary": "Windows-11-10.0.26100-SP0",
            "windows_build": "26100",
            "pyside_version": "6.10.2",
            "qt_webengine_process_path": r"C:\missing\QtWebEngineProcess.exe",
            "qt_webengine_process_exists": False,
            "import_error": "",
        },
    )

    called = {"run": False}

    def _unexpected_run(*_args, **_kwargs):
        called["run"] = True
        raise AssertionError("subprocess.run should not be called when process is missing")

    monkeypatch.setattr(diagnostics.subprocess, "run", _unexpected_run)

    result = diagnostics.probe_standard_webengine()

    assert result.ok is False
    assert result.failure_kind == "missing-process"
    assert called["run"] is False


def test_probe_standard_webengine_uses_hidden_child_command_in_frozen_runtime(monkeypatch):
    monkeypatch.setattr(
        diagnostics,
        "_current_runtime_facts",
        lambda: {
            "python_executable": r"C:\Program Files\CanalHydraulicCalc\CanalHydraulicCalc.exe",
            "python_version": "3.13.3",
            "platform_summary": "Windows-11-10.0.26100-SP0",
            "windows_build": "26100",
            "pyside_version": "6.10.2",
            "qt_webengine_process_path": r"C:\Program Files\CanalHydraulicCalc\_internal\PySide6\QtWebEngineProcess.exe",
            "qt_webengine_process_exists": True,
            "import_error": "",
            "is_frozen_runtime": True,
        },
    )

    calls = {}

    def _fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return types.SimpleNamespace(returncode=0, stdout="WEBENGINE_PROBE_OK\n", stderr="")

    monkeypatch.setattr(diagnostics.subprocess, "run", _fake_run)

    result = diagnostics.probe_standard_webengine()

    assert result.ok is True
    assert calls["cmd"] == [
        r"C:\Program Files\CanalHydraulicCalc\CanalHydraulicCalc.exe",
        "--webengine-probe-child",
    ]


def test_probe_standard_webengine_default_timeout_allows_slow_first_launch(monkeypatch):
    """首次加载 WebEngine 偶尔接近 8 秒，默认预检预算要留出余量。"""
    monkeypatch.setattr(
        diagnostics,
        "_current_runtime_facts",
        lambda: {
            "python_executable": sys.executable,
            "python_version": "3.13.3",
            "platform_summary": "Windows-11-10.0.26100-SP0",
            "windows_build": "26100",
            "pyside_version": "6.11.0",
            "qt_webengine_process_path": r"C:\Python\Lib\site-packages\PySide6\QtWebEngineProcess.exe",
            "qt_webengine_process_exists": True,
            "import_error": "",
            "is_frozen_runtime": False,
        },
    )

    calls = {}

    def _fake_run(cmd, **kwargs):
        calls["timeout"] = kwargs.get("timeout")
        return types.SimpleNamespace(returncode=0, stdout="WEBENGINE_PROBE_OK\n", stderr="")

    monkeypatch.setattr(diagnostics.subprocess, "run", _fake_run)

    result = diagnostics.probe_standard_webengine()

    assert result.ok is True
    assert calls["timeout"] >= 15


def test_build_startup_context_uses_standard_mode_when_probe_passes(monkeypatch):
    probe_result = _probe_result(ok=True, failure_kind="none", exit_code=0)

    monkeypatch.setattr(bootstrap, "emergency_single_process_requested", lambda: False)
    monkeypatch.setattr(bootstrap, "probe_standard_webengine", lambda: probe_result)

    context = bootstrap.build_startup_context(update_checks_enabled=False)

    assert context == startup_context_module.StartupContext(
        webengine_mode="standard",
        webengine_probe_result=probe_result,
        update_checks_enabled=False,
        is_frozen_runtime=False,
    )


def test_build_startup_context_honors_hidden_single_process_switch(monkeypatch):
    monkeypatch.setattr(bootstrap, "emergency_single_process_requested", lambda: True)

    applied_flags = []
    monkeypatch.setattr(
        bootstrap,
        "apply_emergency_single_process_mode",
        lambda: applied_flags.append("--single-process --disable-gpu") or "--single-process --disable-gpu",
    )

    def _unexpected_probe():
        raise AssertionError("standard probe should not run in emergency mode")

    monkeypatch.setattr(bootstrap, "probe_standard_webengine", _unexpected_probe)

    context = bootstrap.build_startup_context()

    assert context.webengine_mode == "single-process"
    assert context.webengine_probe_result is None
    assert applied_flags == ["--single-process --disable-gpu"]


def test_build_startup_context_blocks_and_reports_on_probe_failure(monkeypatch):
    failing_result = _probe_result(failure_kind="unknown")
    dialog_calls = []
    app_calls = []

    monkeypatch.setattr(bootstrap, "emergency_single_process_requested", lambda: False)
    monkeypatch.setattr(bootstrap, "probe_standard_webengine", lambda: failing_result)
    monkeypatch.setattr(bootstrap, "ensure_application", lambda argv=None: app_calls.append(argv) or object())
    monkeypatch.setattr(
        bootstrap,
        "_show_webengine_startup_failure_dialog",
        lambda result: dialog_calls.append(result),
    )

    context = bootstrap.build_startup_context()

    assert context is None
    assert app_calls == [None]
    assert dialog_calls == [failing_result]


def test_build_startup_context_auto_falls_back_on_ipc_access_denied(monkeypatch):
    failing_result = _probe_result(failure_kind="ipc-access-denied")
    applied_flags = []

    monkeypatch.setattr(bootstrap, "emergency_single_process_requested", lambda: False)
    monkeypatch.setattr(bootstrap, "probe_standard_webengine", lambda: failing_result)
    monkeypatch.setattr(
        bootstrap,
        "apply_emergency_single_process_mode",
        lambda: applied_flags.append("--single-process --disable-gpu") or "--single-process --disable-gpu",
    )

    context = bootstrap.build_startup_context(update_checks_enabled=False)

    assert context == startup_context_module.StartupContext(
        webengine_mode="single-process",
        webengine_probe_result=failing_result,
        update_checks_enabled=False,
        is_frozen_runtime=False,
    )
    assert applied_flags == ["--single-process --disable-gpu"]


def test_bootstrap_run_short_circuits_hidden_webengine_probe_child(monkeypatch):
    compat_calls = []
    child_calls = []

    monkeypatch.setattr(bootstrap, "initialize_runtime_environment", lambda: None)
    monkeypatch.setattr(
        bootstrap,
        "ensure_qfluentwidgets_compat",
        lambda: compat_calls.append("ensure_qfluentwidgets_compat"),
    )
    monkeypatch.setattr(
        bootstrap,
        "run_webengine_probe_child",
        lambda: child_calls.append(True) or 7,
        raising=False,
    )

    def _unexpected_license_check():
        raise AssertionError("license check should not run for hidden webengine probe child")

    monkeypatch.setattr(bootstrap, "_check_license", _unexpected_license_check)

    code = bootstrap.run(["main.py", "--webengine-probe-child"])

    assert code == 7
    assert child_calls == [True]
    assert compat_calls == []


def test_package_import_does_not_run_qfluentwidgets_compat(monkeypatch):
    compat = importlib.import_module(BASE_PACKAGE + ".qfluentwidgets_compat")
    calls = []

    monkeypatch.setattr(
        compat,
        "ensure_qfluentwidgets_compat",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    monkeypatch.delitem(sys.modules, BASE_PACKAGE, raising=False)

    importlib.import_module(BASE_PACKAGE)

    assert calls == []


def test_bootstrap_run_builds_main_window_and_starts_update_check(monkeypatch):
    compat_calls = []
    startup_context = _startup_context(update_checks_enabled=True)
    opened_dialog = []
    call_log = []

    class DummyApp:
        def setQuitOnLastWindowClosed(self, enabled):
            call_log.append(("app.setQuitOnLastWindowClosed", enabled))

        def processEvents(self):
            call_log.append("app.processEvents")

        def exec(self):
            call_log.append("app.exec")
            return 123

    class DummyWindow:
        def __init__(self, context):
            call_log.append("window.init")
            self.context = context

        def prepare_update_prompt(self, *, force_full_package_once=False):
            call_log.append(("prepare_update_prompt", force_full_package_once))

        def showNormal(self):
            call_log.append("window.showNormal")

        def winId(self):
            call_log.append("window.winId")
            return 123

        def raise_(self):
            call_log.append("window.raise")

        def activateWindow(self):
            call_log.append("window.activateWindow")

        def start_silent_update_check(self):
            call_log.append("window.start_silent_update_check")

        def _open_update_dialog(self):
            opened_dialog.append(True)

    dummy_app_module = types.ModuleType(BASE_PACKAGE + ".app")
    dummy_app_module.MainWindow = DummyWindow

    monkeypatch.setattr(bootstrap, "initialize_runtime_environment", lambda: call_log.append("initialize_runtime_environment"))
    monkeypatch.setattr(
        bootstrap,
        "ensure_qfluentwidgets_compat",
        lambda: compat_calls.append("ensure_qfluentwidgets_compat"),
    )
    monkeypatch.setattr(bootstrap, "_check_license", lambda: True)
    monkeypatch.setattr(
        bootstrap,
        "build_startup_context",
        lambda update_checks_enabled=True: startup_context,
    )
    monkeypatch.setattr(bootstrap, "ensure_application", lambda argv=None: DummyApp())
    monkeypatch.setattr(bootstrap.QCoreApplication, "removePostedEvents", lambda *_args: None)
    monkeypatch.setattr(bootstrap.QTimer, "singleShot", lambda _ms, func: func())
    monkeypatch.setitem(sys.modules, BASE_PACKAGE + ".app", dummy_app_module)

    code = bootstrap.run(
        [
            "main.py",
            bootstrap.updater.UPDATE_FLAG_OPEN_DIALOG,
            bootstrap.updater.UPDATE_FLAG_FORCE_FULL_PACKAGE,
        ]
    )

    assert code == 123
    assert compat_calls == ["ensure_qfluentwidgets_compat"]
    assert call_log == [
        "initialize_runtime_environment",
        ("app.setQuitOnLastWindowClosed", False),
        "window.init",
        ("prepare_update_prompt", True),
        "window.showNormal",
        "window.winId",
        "window.raise",
        "window.activateWindow",
        "app.processEvents",
        "window.start_silent_update_check",
        "app.exec",
    ]
    assert opened_dialog == [True]


def test_bootstrap_run_returns_failure_before_importing_main_window(monkeypatch):
    compat_calls = []
    dummy_app_module = types.ModuleType(BASE_PACKAGE + ".app")

    class _ExplodingWindow:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("MainWindow should not be constructed when startup context is unavailable")

    dummy_app_module.MainWindow = _ExplodingWindow

    monkeypatch.setattr(bootstrap, "initialize_runtime_environment", lambda: None)
    monkeypatch.setattr(
        bootstrap,
        "ensure_qfluentwidgets_compat",
        lambda: compat_calls.append("ensure_qfluentwidgets_compat"),
    )
    monkeypatch.setattr(bootstrap, "_check_license", lambda: True)
    monkeypatch.setattr(bootstrap, "build_startup_context", lambda update_checks_enabled=True: None)
    monkeypatch.setitem(sys.modules, BASE_PACKAGE + ".app", dummy_app_module)

    code = bootstrap.run(["main.py"])

    assert code == 2
    assert compat_calls == ["ensure_qfluentwidgets_compat"]
