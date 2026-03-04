"""Regression tests for water level linkage in WaterProfilePanel._recalc_downstream."""

import importlib.util
from pathlib import Path

from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem


def _load_panel_class():
    panel_path = next(Path(".").glob("**/water_profile/panel.py")).resolve()
    spec = importlib.util.spec_from_file_location("wp_panel_mod_for_test", panel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WaterProfilePanel


def _set_cell(table, row, col, text):
    item = table.item(row, col)
    if item is None:
        item = QTableWidgetItem("")
        table.setItem(row, col, item)
    item.setText(text)


def _build_minimal_panel():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel.node_table = QTableWidget(8, 44)
    panel._node_structure_heights = {}
    panel.calculated_nodes = []
    panel.start_wl_edit = object()
    panel._fval = lambda _w, default=0.0: 420.0
    return panel, WaterProfilePanel


def test_recalc_downstream_only_updates_downstream_rows():
    app = QApplication.instance() or QApplication([])
    _ = app

    panel, panel_cls = _build_minimal_panel()
    table = panel.node_table

    transition_label = "\u6e10\u53d8\u6bb5"
    regular_label = "\u5012\u8679\u5438"

    # Row 2 is transition; others are regular rows.
    for r in range(table.rowCount()):
        _set_cell(table, r, 2, transition_label if r == 2 else regular_label)

    # Existing totals/transition losses.
    _set_cell(table, 0, 39, "0.1000")
    _set_cell(table, 1, 39, "0.0276")
    _set_cell(table, 2, 33, "0.0076")
    _set_cell(table, 3, 39, "0.0154")
    _set_cell(table, 4, 39, "-")
    _set_cell(table, 5, 39, "-")
    _set_cell(table, 6, 39, "-")
    _set_cell(table, 7, 39, "1.6134")

    # Existing cumulative/water level values for upstream rows.
    preset_cum = [0.2172, 0.2448, 0.2524, 0.2678, 0.2678, 0.2678, 0.2678, 1.8812]
    preset_wl = [419.783, 419.755, None, 419.732, 419.732, 419.732, 419.732, 416.077]
    for r, value in enumerate(preset_cum):
        _set_cell(table, r, 40, f"{value:.4f}")
    for r, value in enumerate(preset_wl):
        if value is not None:
            _set_cell(table, r, 41, f"{value:.3f}")

    # Simulate editing row 7 siphon/pressure-pipe loss from 1.6134 to 0.6134.
    for c in (34, 35, 36, 37):
        _set_cell(table, 7, c, "-")
    _set_cell(table, 7, 38, "0.6134")

    panel_cls._recalc_downstream(panel, 7)

    # Upstream rows should stay unchanged.
    assert table.item(1, 41).text() == "419.755"
    assert table.item(3, 41).text() == "419.732"
    assert table.item(6, 41).text() == "419.732"

    # Edited row should be updated with downstream linkage.
    assert table.item(7, 39).text() == "0.6134"
    assert table.item(7, 40).text() == "0.8812"
    assert table.item(7, 41).text() == "419.119"
