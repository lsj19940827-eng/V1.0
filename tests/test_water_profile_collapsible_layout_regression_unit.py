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


def test_flow_selector_groups_stay_on_same_row_in_common_width():
    """常用窗口宽度下，设计流量和加大流量应保持同一行显示。"""
    panel = _build_panel(width=1400, height=900)
    try:
        assert panel._flow_pair_group_widget is not None
        assert panel._design_flow_group_widget.parentWidget() is panel._flow_pair_group_widget
        assert panel._max_flow_group_widget.parentWidget() is panel._flow_pair_group_widget
        assert panel._flow_pair_group_widget.y() == panel.start_wl_edit.parentWidget().y()
    finally:
        panel.deleteLater()


def test_flow_selector_groups_wrap_together_in_narrow_width():
    """窗口变窄时，设计流量和加大流量应作为一组一起换行。"""
    panel = _build_panel(width=1100, height=900)
    try:
        assert panel._flow_pair_group_widget is not None
        assert panel._design_flow_group_widget.parentWidget() is panel._flow_pair_group_widget
        assert panel._max_flow_group_widget.parentWidget() is panel._flow_pair_group_widget
        assert panel._flow_pair_group_widget.y() > panel.start_wl_edit.parentWidget().y()
    finally:
        panel.deleteLater()


def test_first_multi_segment_refresh_keeps_top_layout_stable_without_manual_toggle():
    """首次从单段切到多段时，也应自动重算顶部高度，不再压缩下方区域。"""
    panel = _build_panel(width=1360, height=900)
    stable_panel = _build_panel(width=1360, height=900)
    try:
        panel.design_flow_edit.setText("0.1")
        panel.max_flow_edit.setText("0.13")
        panel._sync_flow_segment_widgets(reset_index=True)
        _flush_events()

        panel.design_flow_edit.setText("4.6, 3.2, 2.1, 1.0, 0.4")
        panel.max_flow_edit.setText("5.75, 4.0, 2.6, 1.25, 0.52")
        panel._sync_flow_segment_widgets(reset_index=True)
        _flush_events()

        stable_panel.design_flow_edit.setText("4.6, 3.2, 2.1, 1.0, 0.4")
        stable_panel.max_flow_edit.setText("5.75, 4.0, 2.6, 1.25, 0.52")
        stable_panel._sync_flow_segment_widgets(reset_index=True)
        _flush_events()
        stable_panel._adjust_splitter_for_settings()
        _flush_events()

        assert panel.start_station_edit.parentWidget().y() >= stable_panel.start_station_edit.parentWidget().y() - 2
        assert panel._transition_group.height() >= stable_panel._transition_group.height() - 2
    finally:
        panel.deleteLater()
        stable_panel.deleteLater()
