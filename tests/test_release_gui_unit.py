"""图形发布入口必须复用 CLI 的验收和失败退出，不访问真实发布服务。"""
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import release_gui


def test_start_button_dispatches_guarded_process_without_legacy_publish_helpers(monkeypatch):
    app = release_gui.QApplication.instance() or release_gui.QApplication([])
    calls = []
    class Thread:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def start(self):
            calls.append("started")
    monkeypatch.setattr(release_gui.threading, "Thread", Thread)
    window = release_gui.ReleaseWindow()
    try:
        window._on_start()
        assert calls[0]["target"] is release_gui._run_release and calls[1] == "started"
        assert window._running is True
        window._on_finished(False, "测试已停止")
    finally:
        window.close()


@pytest.mark.parametrize("returncode", [0, 2])
def test_gui_uses_guarded_cli_and_propagates_failed_gate(monkeypatch, returncode):
    calls, events = [], []
    class Process:
        stdout = ["[步骤 2/6] 打包\n", "[验收 U01-U07] 原生安装\n", "[验收未通过] 故障注入\n"]
        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def wait(self):
            return returncode
    bridge = SimpleNamespace(**{name: SimpleNamespace(emit=lambda *args, key=name: events.append((key, args)))
                                for name in ("log_signal", "step_signal", "progress_signal", "finished_signal")})
    monkeypatch.setattr(release_gui.subprocess, "Popen", Process)
    release_gui._run_release("patch", "修复说明\n第二条", bridge)
    command, kwargs = calls[0]
    assert command[1:3] == ["-u", str(Path(release_gui.SCRIPT_DIR) / "release.py")]
    assert command[-3:] == ["patch", "-m", "修复说明\n第二条"]
    assert kwargs.get("shell", False) is False
    finished = [args for name, args in events if name == "finished_signal"]
    assert len(finished) == 1 and finished[0][0] is (returncode == 0)
    if returncode:
        assert ("step_signal", (3, "error")) in events
        assert "发布已停止" in finished[0][1]
