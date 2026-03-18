# -*- coding: utf-8 -*-
"""Regression tests for non-zero start station handling in table 3."""

import importlib.util
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtWidgets import QApplication, QTableWidgetItem

from 推求水面线.models.data_models import ProjectSettings


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _load_panel_class():
    panel_path = next(Path(".").glob("**/water_profile/panel.py")).resolve()
    spec = importlib.util.spec_from_file_location("wp_panel_start_station_regression", panel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WaterProfilePanel


def _build_panel():
    _get_qapp()
    panel_cls = _load_panel_class()
    panel = panel_cls()
    panel.resize(1400, 900)
    panel.show()
    _flush_events()
    return panel


def _set_cell(table, row, col, text):
    item = table.item(row, col)
    if item is None:
        item = QTableWidgetItem("")
        table.setItem(row, col, item)
    item.setText(str(text))


def _configure_two_node_table(panel, start_station_text: str):
    table = panel.node_table
    panel._updating_cells = True
    try:
        table.clearContents()
        table.setRowCount(2)
        for row, x in enumerate((0.0, 100.0)):
            _set_cell(table, row, 0, "1")
            _set_cell(table, row, 1, "-")
            _set_cell(table, row, 2, "明渠-矩形")
            _set_cell(table, row, 5, f"{x:.3f}")
            _set_cell(table, row, 6, "0.000")
    finally:
        panel._updating_cells = False

    panel.channel_name_edit.setText("合作")
    idx = panel.channel_level_combo.findText("干渠")
    if idx >= 0:
        panel.channel_level_combo.setCurrentIndex(idx)
    panel.start_station_edit.setText(start_station_text)
    panel.turn_radius_edit.setText("9.0")


def test_table3_recalculate_geometry_uses_project_start_station():
    panel = _build_panel()
    try:
        _configure_two_node_table(panel, "10+097.309")
        panel._recalculate_geometry()
        _flush_events()

        prefix = "合干"
        expected_start = ProjectSettings.format_station(10097.309, prefix)
        expected_end = ProjectSettings.format_station(10197.309, prefix)

        assert panel.node_table.item(0, 13).text() == expected_start
        assert panel.node_table.item(0, 14).text() == expected_start
        assert panel.node_table.item(0, 15).text() == expected_start
        assert panel.node_table.item(0, 16).text() == expected_start
        assert panel.node_table.item(1, 13).text() == expected_end
        assert panel.node_table.item(1, 14).text() == expected_end
        assert panel.node_table.item(1, 15).text() == expected_end
        assert panel.node_table.item(1, 16).text() == expected_end
    finally:
        panel.deleteLater()


def test_project_reload_with_zero_based_snapshot_recovers_on_recalculate():
    panel = _build_panel()
    try:
        _configure_two_node_table(panel, "10+097.309")
        panel._recalculate_geometry()
        _flush_events()
        state = panel.to_project_dict()
    finally:
        panel.deleteLater()

    stale_start = "合干0+000.000"
    stale_end = "合干0+100.000"
    for col in (13, 14, 15, 16):
        state["node_table_rows"][0][col] = stale_start
        state["node_table_rows"][1][col] = stale_end

    restored = _build_panel()
    try:
        restored.from_project_dict(state, skip_dirty_signal=True)
        _flush_events()

        assert restored.node_table.item(0, 15).text() == stale_start
        assert restored.node_table.item(1, 15).text() == stale_end

        restored._recalculate_geometry()
        _flush_events()

        prefix = "合干"
        expected_start = ProjectSettings.format_station(10097.309, prefix)
        expected_end = ProjectSettings.format_station(10197.309, prefix)

        assert restored.node_table.item(0, 15).text() == expected_start
        assert restored.node_table.item(1, 15).text() == expected_end
    finally:
        restored.deleteLater()
