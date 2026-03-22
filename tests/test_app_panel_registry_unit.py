# -*- coding: utf-8 -*-
"""Unit tests for main-window panel registry wiring."""

import importlib
import os
import sys
import tempfile
import types
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QWidget


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE_PACKAGE = "app_渠系计算前端"


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds=4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


class _DummyPanel(QWidget):
    data_changed = Signal()

    def __init__(self, name):
        super().__init__()
        self.name = name


class _DummySiphonPanel(_DummyPanel):
    def _save_autosave(self):
        return None


def test_main_window_builds_stack_from_panel_registry(monkeypatch):
    _get_qapp()

    compat_module = importlib.import_module(BASE_PACKAGE + ".qfluentwidgets_compat")
    compat_module.ensure_qfluentwidgets_compat()

    app_module = importlib.import_module(BASE_PACKAGE + ".app")
    project_manager_module = importlib.import_module(BASE_PACKAGE + ".project_manager")
    startup_context_module = importlib.import_module(BASE_PACKAGE + ".startup_context")

    monkeypatch.setattr(project_manager_module.ProjectManager, "start_auto_save", lambda self: None)
    monkeypatch.setattr(project_manager_module.ProjectManager, "check_save_on_close", lambda self: True)

    def _stub_runtime_services(self):
        self.siphon_manager = types.SimpleNamespace(set_project_path=lambda _path: None)
        self.pressure_pipe_manager = types.SimpleNamespace(set_project_path=lambda _path: None)

    monkeypatch.setattr(app_module.MainWindow, "_init_runtime_services", _stub_runtime_services)
    monkeypatch.setattr(app_module, "_create_open_channel_panel", lambda: _DummyPanel("open_channel"))
    monkeypatch.setattr(app_module, "_create_aqueduct_panel", lambda: _DummyPanel("aqueduct"))
    monkeypatch.setattr(app_module, "_create_tunnel_panel", lambda: _DummyPanel("tunnel"))
    monkeypatch.setattr(app_module, "_create_culvert_panel", lambda: _DummyPanel("culvert"))
    monkeypatch.setattr(
        app_module,
        "_create_siphon_panel",
        lambda **kwargs: _DummySiphonPanel("siphon"),
    )
    monkeypatch.setattr(app_module, "_create_pressure_pipe_panel", lambda: _DummyPanel("pressure_pipe"))
    monkeypatch.setattr(
        app_module,
        "_create_water_profile_panel",
        lambda **kwargs: _DummyPanel("water_profile"),
    )

    startup_context = startup_context_module.StartupContext(
        webengine_mode="standard",
        webengine_probe_result=None,
        update_checks_enabled=False,
        is_frozen_runtime=False,
    )

    window = app_module.MainWindow(startup_context)
    _flush_events()

    titles = [descriptor.title for descriptor in window._panel_registry.descriptors]
    assert titles == [
        "明渠设计",
        "渡槽设计",
        "隧洞设计",
        "矩形暗涵设计",
        "倒虹吸设计",
        "有压管道设计",
        "推求水面线",
    ]
    assert [button.text() for button in window._nav_buttons] == titles
    assert window.stack.count() == len(titles)
    assert window.open_channel_panel is window._panel_registry.get("open_channel")
    assert window.aqueduct_panel is window._panel_registry.get("aqueduct")
    assert window.tunnel_panel is window._panel_registry.get("tunnel")
    assert window.culvert_panel is window._panel_registry.get("culvert")
    assert window.siphon_panel is window._panel_registry.get("siphon")
    assert window.pressure_pipe_panel is window._panel_registry.get("pressure_pipe")
    assert window.water_profile_panel is window._panel_registry.get("water_profile")

    window.project_manager._is_dirty = False
    window.deleteLater()
    _flush_events()
