# -*- coding: utf-8 -*-
"""表3预留/过闸水头损失手动编辑回归测试。"""

import importlib
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "推求水面线") not in sys.path:
    sys.path.insert(0, str(ROOT / "推求水面线"))


def _get_qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _load_panel_module():
    app_name = next(path.name for path in ROOT.iterdir() if path.is_dir() and path.name.startswith("app_"))
    return importlib.import_module(f"{app_name}.water_profile.panel")


def _set_cell(table, row, col, text):
    item = table.item(row, col)
    if item is None:
        item = QTableWidgetItem("")
        table.setItem(row, col, item)
    item.setText(text)
    return item


def test_reserve_loss_column_double_click_begins_direct_edit(monkeypatch):
    _get_qt_app()
    panel_module = _load_panel_module()
    panel_cls = panel_module.WaterProfilePanel
    panel = panel_cls.__new__(panel_cls)
    panel.node_table = QTableWidget(2, len(panel_module.NODE_ALL_HEADERS))
    panel._is_table1_source_locked_cell = lambda _row, _col: False

    edit_cells = []
    monkeypatch.setattr(
        panel_cls,
        "_begin_inline_loss_edit",
        lambda self, row, col: edit_cells.append((row, col)) or True,
        raising=False,
    )

    panel_cls._on_node_cell_double_clicked(panel, 1, 36)

    assert edit_cells == [(1, 36)]


def test_gate_loss_column_double_click_begins_direct_edit(monkeypatch):
    _get_qt_app()
    panel_module = _load_panel_module()
    panel_cls = panel_module.WaterProfilePanel
    panel = panel_cls.__new__(panel_cls)
    panel.node_table = QTableWidget(2, len(panel_module.NODE_ALL_HEADERS))
    panel._is_table1_source_locked_cell = lambda _row, _col: False

    edit_cells = []
    monkeypatch.setattr(
        panel_cls,
        "_begin_inline_loss_edit",
        lambda self, row, col: edit_cells.append((row, col)) or True,
        raising=False,
    )

    panel_cls._on_node_cell_double_clicked(panel, 1, 37)

    assert edit_cells == [(1, 37)]


def test_reserve_and_gate_loss_edit_refuse_first_row():
    _get_qt_app()
    panel_module = _load_panel_module()
    panel_cls = panel_module.WaterProfilePanel
    panel = panel_cls.__new__(panel_cls)
    panel.node_table = QTableWidget(1, len(panel_module.NODE_ALL_HEADERS))
    _set_cell(panel.node_table, 0, 36, "0.0500")
    _set_cell(panel.node_table, 0, 37, "0.1000")

    assert panel_cls._begin_inline_loss_edit(panel, 0, 36) is False
    assert panel_cls._begin_inline_loss_edit(panel, 0, 37) is False


def test_build_nodes_from_table_preserves_explicit_zero_gate_loss():
    _get_qt_app()
    panel_module = _load_panel_module()
    panel_cls = panel_module.WaterProfilePanel
    panel = panel_cls()
    try:
        panel._add_node_row(
            ["1", "双桥", "分水闸", "", "IP1", "10", "20", ""],
            _skip_undo=True,
            _defer_controls_refresh=True,
        )
        _set_cell(panel.node_table, 0, 37, "0")

        nodes = panel._build_nodes_from_table()

        assert len(nodes) == 1
        assert nodes[0].head_loss_gate == 0.0
    finally:
        panel.deleteLater()


def test_build_nodes_from_table_uses_default_gate_loss_when_unedited():
    _get_qt_app()
    panel_module = _load_panel_module()
    panel_cls = panel_module.WaterProfilePanel
    panel = panel_cls()
    try:
        panel._add_node_row(
            ["1", "上游明渠", "明渠-梯形", "", "IP1", "0", "0", ""],
            _skip_undo=True,
            _defer_controls_refresh=True,
        )
        panel._add_node_row(
            ["1", "双桥", "分水闸", "", "IP2", "10", "20", ""],
            _skip_undo=True,
            _defer_controls_refresh=True,
        )
        panel.node_table.blockSignals(True)
        _set_cell(panel.node_table, 1, 37, "-")
        panel.node_table.blockSignals(False)

        nodes = panel._build_nodes_from_table()

        assert nodes[1].head_loss_gate == panel_module.DEFAULT_GATE_HEAD_LOSS
        assert "gate_head_loss_user_set" not in nodes[1].section_params
    finally:
        panel.deleteLater()


def test_build_nodes_from_table_preserves_cleared_gate_loss_after_user_edit():
    _get_qt_app()
    panel_module = _load_panel_module()
    panel_cls = panel_module.WaterProfilePanel
    panel = panel_cls()
    try:
        panel._add_node_row(
            ["1", "上游明渠", "明渠-梯形", "", "IP1", "0", "0", ""],
            _skip_undo=True,
            _defer_controls_refresh=True,
        )
        panel._add_node_row(
            ["1", "双桥", "分水闸", "", "IP2", "10", "20", ""],
            _skip_undo=True,
            _defer_controls_refresh=True,
        )
        _set_cell(panel.node_table, 1, 37, "")
        panel._mark_gate_loss_user_set_for_row(1, True)

        nodes = panel._build_nodes_from_table()

        assert nodes[1].head_loss_gate == 0.0
        assert nodes[1].section_params["gate_head_loss_user_set"] is True
    finally:
        panel.deleteLater()


def test_recalc_downstream_uses_edited_gate_loss_for_total_and_water_level():
    _get_qt_app()
    panel_module = _load_panel_module()
    panel_cls = panel_module.WaterProfilePanel
    panel = panel_cls.__new__(panel_cls)
    panel.node_table = QTableWidget(2, len(panel_module.NODE_ALL_HEADERS))
    panel._node_structure_heights = {}
    panel.calculated_nodes = []
    panel.start_wl_edit = object()
    panel._fval = lambda _widget, default=0.0: 100.0

    for row in range(2):
        _set_cell(panel.node_table, row, 2, "明渠-梯形" if row == 0 else "分水闸")
    _set_cell(panel.node_table, 0, 39, "0.0000")
    _set_cell(panel.node_table, 0, 40, "0.0000")
    _set_cell(panel.node_table, 0, 41, "100.000")
    for col in (34, 35, 36, 38):
        _set_cell(panel.node_table, 1, col, "-")
    _set_cell(panel.node_table, 1, 37, "0.0250")

    panel_cls._recalc_downstream(panel, 1)

    assert panel.node_table.item(1, 39).text() == "0.0250"
    assert panel.node_table.item(1, 40).text() == "0.0250"
    assert panel.node_table.item(1, 41).text() == "99.975"

    _set_cell(panel.node_table, 1, 37, "0")

    panel_cls._recalc_downstream(panel, 1)

    assert panel.node_table.item(1, 39).text() == "0.0000"
    assert panel.node_table.item(1, 40).text() == "0.0000"
    assert panel.node_table.item(1, 41).text() == "100.000"


def test_recalc_downstream_uses_edited_reserve_loss_for_total_and_water_level():
    _get_qt_app()
    panel_module = _load_panel_module()
    panel_cls = panel_module.WaterProfilePanel
    panel = panel_cls.__new__(panel_cls)
    panel.node_table = QTableWidget(2, len(panel_module.NODE_ALL_HEADERS))
    panel._node_structure_heights = {}
    panel.calculated_nodes = []
    panel.start_wl_edit = object()
    panel._fval = lambda _widget, default=0.0: 100.0

    for row in range(2):
        _set_cell(panel.node_table, row, 2, "明渠-梯形")
    _set_cell(panel.node_table, 0, 39, "0.0000")
    _set_cell(panel.node_table, 0, 40, "0.0000")
    _set_cell(panel.node_table, 0, 41, "100.000")
    for col in (34, 35, 37, 38):
        _set_cell(panel.node_table, 1, col, "-")
    _set_cell(panel.node_table, 1, 36, "0.0350")

    panel_cls._recalc_downstream(panel, 1)

    assert panel.node_table.item(1, 39).text() == "0.0350"
    assert panel.node_table.item(1, 40).text() == "0.0350"
    assert panel.node_table.item(1, 41).text() == "99.965"


def test_calculator_preprocess_preserves_marked_zero_gate_loss():
    from core.calculator import WaterProfileCalculator
    from models.data_models import ChannelNode, ProjectSettings
    from models.enums import StructureType

    panel_module = _load_panel_module()
    node = ChannelNode()
    node.name = "双桥"
    node.structure_type = StructureType.DIVERSION_GATE
    node.head_loss_gate = 0.0
    node.section_params["gate_head_loss_user_set"] = True

    WaterProfileCalculator(ProjectSettings()).preprocess_nodes([node])

    assert node.is_diversion_gate is True
    assert node.head_loss_gate == 0.0
    assert node.head_loss_gate != panel_module.DEFAULT_GATE_HEAD_LOSS
