# -*- coding: utf-8 -*-
"""Regression tests for WaterProfilePanel collapsible layout behavior."""

import importlib.util
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtWidgets import QApplication


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _load_panel_class():
    panel_path = next(Path(".").glob("**/water_profile/panel.py")).resolve()
    spec = importlib.util.spec_from_file_location("wp_panel_collapsible_regression", panel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WaterProfilePanel


def _build_panel(width: int = 1400, height: int = 900):
    _get_qapp()
    panel_cls = _load_panel_class()
    panel = panel_cls()
    panel.resize(width, height)
    panel.show()
    _flush_events()
    panel._adjust_splitter_for_settings()
    _flush_events()
    return panel


def _top_gap(panel):
    top_widget = panel._splitter.widget(0)
    used_height = panel._settings_group.height() + panel._transition_group.height() + panel._top_lay.spacing()
    return top_widget.height() - used_height


def _assert_no_abnormal_gap(panel, tolerance: int = 2):
    assert abs(_top_gap(panel)) <= tolerance


def test_collapsible_expand_recovers_settings_content_and_gap():
    panel = _build_panel()

    panel._settings_group.set_collapsed(True)
    panel._transition_group.set_collapsed(True)
    _flush_events()
    panel._adjust_splitter_for_settings()
    _flush_events()

    panel._settings_group.set_collapsed(False)
    _flush_events()
    panel._adjust_splitter_for_settings()
    _flush_events()

    assert not panel._settings_group.is_collapsed()
    assert panel._settings_group.content_widget().isVisible()
    assert panel._settings_group.height() >= 100

    panel._transition_group.set_collapsed(False)
    _flush_events()
    panel._adjust_splitter_for_settings()
    _flush_events()

    assert not panel._transition_group.is_collapsed()
    _assert_no_abnormal_gap(panel)

    panel.deleteLater()


def test_collapsible_repeated_toggle_keeps_stable_layout():
    panel = _build_panel()

    for _ in range(20):
        panel._settings_group.toggle()
        _flush_events()
        panel._adjust_splitter_for_settings()
        _flush_events()

        panel._transition_group.toggle()
        _flush_events()
        panel._adjust_splitter_for_settings()
        _flush_events()

        if not panel._settings_group.is_collapsed():
            assert panel._settings_group.height() >= 100
            assert panel._settings_group.content_widget().isVisible()
        if not panel._transition_group.is_collapsed():
            assert panel._transition_group.height() >= 120
            assert panel._transition_group.content_widget().isVisible()
        _assert_no_abnormal_gap(panel)

    panel.deleteLater()


def test_collapsible_state_persistence_after_reload_and_toggle():
    panel = _build_panel()
    panel._settings_group.set_collapsed(False)
    panel._transition_group.set_collapsed(True)
    _flush_events()
    panel._adjust_splitter_for_settings()
    _flush_events()

    state = panel.to_project_dict()
    panel.deleteLater()

    restored = _build_panel()
    restored.from_project_dict(state, skip_dirty_signal=True)
    _flush_events()
    restored._adjust_splitter_for_settings()
    _flush_events()

    assert restored._settings_group.is_collapsed() is False
    assert restored._transition_group.is_collapsed() is True

    restored._settings_group.set_collapsed(True)
    restored._transition_group.set_collapsed(True)
    _flush_events()
    restored._adjust_splitter_for_settings()
    _flush_events()

    restored._settings_group.set_collapsed(False)
    _flush_events()
    restored._adjust_splitter_for_settings()
    _flush_events()

    assert restored._settings_group.height() >= 100
    assert restored._settings_group.content_widget().isVisible()
    _assert_no_abnormal_gap(restored)

    restored.deleteLater()
