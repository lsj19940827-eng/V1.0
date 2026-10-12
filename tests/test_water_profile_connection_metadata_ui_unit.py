# -*- coding: utf-8 -*-
"""真实表格内部连接段长度回写不得失效拓扑或制造用户编辑。"""

import copy
import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CODEX_FORCE_QTEXTBROWSER", "1")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QDialog

from app_渠系计算前端.batch import panel as batch_module
from app_渠系计算前端.water_profile import panel as panel_module
from app_渠系计算前端.water_profile import water_profile_dialogs as dialogs_module
from 推求水面线.models.data_models import ChannelNode, ProjectSettings
from 推求水面线.models.enums import InOutType, StructureType


ROOT = Path(__file__).resolve().parents[1]


def _wait_until(app, predicate):
    """等待真实后台结果写回，不替换断面计算服务。"""
    deadline = time.monotonic() + 30
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert predicate(), "断面计算未在限时内结束"
    app.processEvents()


@pytest.fixture
def panel(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(batch_module.BatchPanel, "_load_user_prefs", lambda self: None)
    monkeypatch.setattr(batch_module.BatchPanel, "_save_user_prefs", lambda self: None)
    messages = []
    for name in ("warning", "error", "info", "success"):
        monkeypatch.setattr(panel_module.InfoBar, name, lambda *args, _name=name, **kwargs: messages.append((_name, args)))
    for module in (batch_module, panel_module, dialogs_module):
        for name in ("fluent_info", "fluent_batch_result"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, lambda *args, **kwargs: None)
        if hasattr(module, "fluent_question"):
            monkeypatch.setattr(module, "fluent_question", lambda *args, **kwargs: True)
    value = panel_module.WaterProfilePanel()
    yield app, value, messages
    value.cancel_calculation()
    value._batch_backend.cancel_calculation()
    _wait_until(app, lambda: not value.is_calculation_running() and not value._batch_backend.is_calculation_running())
    value.close()
    value.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def test_real_feilong_excel_keeps_prepared_topology_after_connection_length_sync(panel, monkeypatch):
    """68行原始Excel按真实按钮插成103行后，准备状态和撤销记录仍正确。"""
    app, value, messages = panel

    def confirm_recommended(self):
        self.rb_table.setChecked(True)
        self._on_ok()
        assert self.result["mode"] == self.RESULT_TABLE_EDIT
        assert len(self.result["params"]) == 7
        return QDialog.Accepted

    monkeypatch.setattr(dialogs_module.BatchChannelConfirmDialog, "exec", confirm_recommended)
    value._batch_backend._do_load_from_filepath(str(ROOT / "data" / "飞龙分干渠批量计算表.xlsx"), is_sample=False)
    value._sync_batch_settings()
    assert value._section_input_table.rowCount() == 68
    assert value.start_wl_edit.text() == "359.27"
    value._btn_section_calc.click()
    _wait_until(app, lambda: not value._batch_backend.is_calculation_running())
    assert value._count_section_calc_failures() == 0
    assert value._section_sync_ready
    assert value.node_table.rowCount() == 68
    undo_before = copy.deepcopy(value._loss_undo_stack)
    redo_before = copy.deepcopy(value._loss_redo_stack)

    value._btn_transition.click()
    app.processEvents()
    nodes = value._build_nodes_from_table()
    assert len(nodes) == 103
    assert sum(node.is_transition for node in nodes) == 28
    assert sum(node.is_auto_inserted_channel for node in nodes) == 7
    assert value._transition_topology_prepared is True
    assert value._section_sync_ready
    assert value._loss_undo_stack == undo_before
    assert value._loss_redo_stack == redo_before
    assert not [args for kind, args in messages if kind == "error"]
    assert value._last_channel_total_length > 0
    for record in value._last_building_lengths:
        if record.get("kind") == "connection":
            assert nodes[record["source_node_index"]].stat_length == record["length"]


@pytest.mark.parametrize("signals_blocked", [False, True])
@pytest.mark.parametrize("updating_cells", [False, True])
def test_connection_only_length_sync_preserves_calculation_gate_and_user_history(panel, signals_blocked, updating_cells):
    """没有渐变段可兜底时，内部统计刷新仍保持已准备拓扑和正式计算入口。"""
    _app, value, _messages = panel
    value.design_flow_edit.setText("1.0")
    value.max_flow_edit.setText("1.2")
    value.start_wl_edit.setText("100")
    value.roughness_edit.setText("0.014")
    value._settings = ProjectSettings(design_flow=1.0, max_flow=1.2, start_water_level=100)
    nodes = []
    for name, station, role, automatic in (
        ("上游隧洞", 0, InOutType.INLET, False),
        ("上游隧洞", 100, InOutType.OUTLET, False),
        ("-", 125, InOutType.NORMAL, True),
        ("下游隧洞", 130, InOutType.INLET, False),
        ("下游隧洞", 230, InOutType.OUTLET, False),
    ):
        node = ChannelNode(name=name, flow_section="1", station_MC=station, x=station,
                           structure_type=StructureType.RECTANGULAR if automatic else StructureType.TUNNEL_ARCH,
                           in_out=role, flow=1.0, roughness=0.014, slope_i=1 / 3000,
                           water_depth=1.2, structure_height=2.0)
        node.is_auto_inserted_channel = automatic
        node.stat_length = 999 if automatic else 0
        node.section_params = {"B": 2.0, "H_total": 2.0, "theta_deg": 180.0}
        nodes.append(node)
    value._update_table_from_nodes_full(nodes)
    value._section_sync_ready = value._transition_topology_prepared = True
    value._loss_undo_stack = [{"existing": "undo"}]
    value._loss_redo_stack = [{"existing": "redo"}]
    changed = []
    value.data_changed.connect(lambda: changed.append("project"))
    value.node_table.cellChanged.connect(lambda *args: changed.append("cell"))
    value.node_table.blockSignals(signals_blocked)
    value._updating_cells = updating_cells
    try:
        value._refresh_building_length_state(nodes)
        assert not value._last_building_stats_error
        assert value.node_table.signalsBlocked() is signals_blocked
        assert value._updating_cells is updating_cells
        assert value._transition_topology_prepared is True
        assert value._has_transition_topology_ready(value._build_nodes_from_table())
        assert not any(node.is_transition for node in value._build_nodes_from_table())
        assert nodes[2].stat_length == 30
        assert value.node_table.item(2, 0).data(Qt.UserRole)["_stat_length"] == 30
        assert value._build_nodes_from_table()[2].stat_length == 30
        assert value._last_channel_total_length == 230
        assert value._loss_undo_stack == [{"existing": "undo"}]
        assert value._loss_redo_stack == [{"existing": "redo"}]
        assert changed == []
        assert value._prepare_calculation() is not None
    finally:
        value.node_table.blockSignals(False)
        value._updating_cells = False
