# -*- coding: utf-8 -*-
"""Smoke tests for shared multi-case navigator integration in real panels."""

import importlib
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _load_panel_class(folder: str, class_name: str):
    webview_compat = importlib.import_module("app_渠系计算前端.webview_compat")
    webview_compat._QtWebEngineView = None
    webview_compat._WEB_ENGINE_IMPORT_ERROR = RuntimeError("forced fallback web view in smoke test")
    module = importlib.import_module(f"app_渠系计算前端.{folder}.panel")
    if hasattr(module, "QWebEngineView"):
        module.QWebEngineView = None
        module._WEB_ENGINE_IMPORT_ERROR = RuntimeError("forced fallback web view in smoke test")
    return getattr(module, class_name)


def test_open_channel_panel_places_case_strip_above_input_group_and_refreshes_labels():
    _get_qapp()
    panel_cls = _load_panel_class("open_channel", "OpenChannelPanel")
    panel = panel_cls()
    panel.resize(1366, 900)
    panel.show()
    _flush_events(6)

    assert hasattr(panel, "_case_strip")
    assert panel._case_strip.y() < panel._input_group.y()

    panel.m_edit.setText("2.5")
    panel._save_current_case()
    panel._add_case()
    _flush_events()

    assert panel._cases[-1]["Q"] == ""
    assert panel._cases[-1]["m"] == "2.5"

    for idx in range(2, 7):
        panel.Q_edit.setText(str(idx))
        _flush_events()
        if idx < 6:
            panel._add_case()
            _flush_events()

    labels_before = list(panel._case_strip.case_labels())
    panel._switch_case(2)
    panel.Q_edit.setText("99")
    _flush_events()
    labels_after = list(panel._case_strip.case_labels())

    assert panel._case_strip.chip_count() == 6
    assert labels_before[:2] == labels_after[:2]
    assert labels_before[3:] == labels_after[3:]
    assert "Q=99" in labels_after[2]
    assert "|" not in labels_after[2]

    panel._remove_current_case()
    _flush_events()

    assert panel._case_strip.chip_count() == 5

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_pressure_pipe_panel_uses_external_case_strip_and_supports_custom_labels():
    _get_qapp()
    panel_cls = _load_panel_class("pressure_pipe", "PressurePipePanel")
    panel = panel_cls()
    panel.resize(1366, 900)
    panel.show()
    _flush_events(6)

    assert hasattr(panel, "_case_strip")
    assert panel._case_strip.y() < panel._input_group.y()

    panel.length_edit.setText("1500")
    panel._save_current_case()
    panel._add_case()
    _flush_events()

    assert panel._cases[-1]["Q"] == ""
    assert panel._cases[-1]["length"] == "1500"

    for idx in range(2, 7):
        panel.Q_edit.setText(str(idx / 10))
        _flush_events()
        if idx < 6:
            panel._add_case()
            _flush_events()

    panel._on_case_renamed(1, "方案B")
    _flush_events()

    labels = panel._case_strip.case_labels()

    assert panel._case_strip.chip_count() == 6
    assert labels[1].startswith("方案B · Q=")
    assert "L=" not in labels[1]
    assert panel._case_strip._remove_button.isEnabled() is True

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_open_channel_panel_keeps_last_added_chip_visible_and_active_during_incremental_adds():
    _get_qapp()
    panel_cls = _load_panel_class("open_channel", "OpenChannelPanel")
    panel = panel_cls()
    panel.resize(1366, 900)
    panel.show()
    _flush_events(6)

    for expected_count in range(2, 7):
        panel.Q_edit.setText(str(expected_count))
        _flush_events()
        panel._add_case()
        _flush_events(6)

        chips = panel._case_strip.navigator()._chips
        geometries = [
            (chip.geometry().x(), chip.geometry().y(), chip.geometry().width(), chip.geometry().height())
            for chip in chips
        ]
        active_indexes = [
            idx for idx, chip in enumerate(chips) if "#0E5DB8" in chip.styleSheet()
        ]

        assert panel._case_strip.chip_count() == expected_count
        assert len(geometries) == expected_count
        assert active_indexes == [expected_count - 1]

        if expected_count >= 4:
            assert geometries[-1] != geometries[0]

    panel.close()
    panel.deleteLater()
    _flush_events(4)


def test_pressure_pipe_result_case_nav_bar_is_visible_and_clicks_reuse_anchor_jump():
    _get_qapp()
    webview_compat = importlib.import_module("app_渠系计算前端.webview_compat")
    webview_compat._QtWebEngineView = None
    webview_compat._WEB_ENGINE_IMPORT_ERROR = RuntimeError("forced fallback web view in smoke test")
    module = importlib.import_module("app_渠系计算前端.pressure_pipe.panel")
    module.QWebEngineView = None
    module._WEB_ENGINE_IMPORT_ERROR = RuntimeError("forced fallback web view in smoke test")

    scroll_calls = []

    def _spy_scroll(*args, **kwargs):
        scroll_calls.append((args, kwargs))
        return True

    module.scroll_view_to_anchor = _spy_scroll

    panel = module.PressurePipePanel()
    panel.resize(1366, 900)
    panel.show()
    _flush_events(6)

    panel.Q_edit.setText("0.8")
    _flush_events()
    panel._add_case()
    _flush_events()
    panel._switch_case(1)
    _flush_events()
    panel.Q_edit.setText("1.2")
    _flush_events()

    panel._calc_btn.click()
    _flush_events(8)

    assert panel._result_case_nav.isVisible() is True
    assert panel._result_case_nav.chip_count() == 2
    assert panel._result_case_nav.height() == panel._result_case_nav.sizeHint().height()
    assert panel._result_case_nav.height() < 120

    scroll_calls.clear()
    panel._result_case_nav.chips()[1].click()
    _flush_events(2)

    assert scroll_calls
    assert scroll_calls[-1][0][1] == "case-result-pressure-pipe-1"

    panel.close()
    panel.deleteLater()
    _flush_events(4)
