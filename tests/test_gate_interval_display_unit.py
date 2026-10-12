"""闸来水区间、连续渠底以及旧成果恢复的显示链回归。"""

import copy
import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CODEX_FORCE_QTEXTBROWSER", "1")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app_渠系计算前端.batch.panel import BatchPanel
from app_渠系计算前端.water_profile import formula_dialog, panel as panel_module
from 推求水面线.core.hydraulic_calc import HydraulicCalculator
from 推求水面线.models.data_models import ChannelNode, ProjectSettings, restore_gate_water_levels
from 推求水面线.models.enums import StructureType


def _gate():
    return ChannelNode(name="双桥", structure_type=StructureType.DIVERSION_GATE,
                       is_diversion_gate=True, flow_section="1", station_MC=100,
                       water_level=99.833, gate_upstream_water_level=99.933,
                       gate_downstream_water_level=99.833, head_loss_friction=0.03,
                       head_loss_bend=0.01, head_loss_local=0.002,
                       head_loss_reserve=0.005, head_loss_gate=0.1,
                       head_loss_total=0.147, head_loss_cumulative=0.167)


def _backfill():
    return {
        "attempted": True, "target_row": 3, "target_name": "双桥",
        "target_flow_section": "1", "target_water_level": 99.833,
        "donor_row": 1, "donor_name": "上游明渠", "donor_structure_type": "明渠-矩形",
        "donor_direction": "上游", "donor_water_depth": 2,
        "donor_structure_height": 2.5,
        "bottom": {"attempted": True, "success": True, "method": "bed_slope",
                   "donor_bottom_elevation": 98, "donor_station_MC": 0,
                   "target_station_MC": 100, "slope_i": 0.001,
                   "station_distance_m": 100, "result": 97.9},
        "top": {"attempted": True, "success": True,
                "base_bottom_elevation": 97.9, "result": 100.4},
    }


def _profile():
    return {"success": True, "bottom_elevation": 97.88, "top_elevation": 100.38,
            "gate_row": 3, "gate_name": "双桥", "gate_bottom_elevation": 97.9,
            "gate_station_MC": 100, "target_station_MC": 120, "slope_i": 0.001,
            "station_distance_m": 20, "normal_water_depth": 1.5,
            "actual_water_depth": 1.94}


@pytest.fixture
def capture_dialog(monkeypatch):
    captured = []
    monkeypatch.setattr(formula_dialog, "FormulaDialog",
                        lambda _parent, title, sections: captured.append((title, sections)))
    return captured


@pytest.mark.parametrize("after, loss, expected", [(99.7, 0.1, 99.8), (-0.1, 0.1, 0), (99.7, 0, 99.7)])
def test_legacy_restores_before_from_own_after_and_loss_without_changing_saved_result(after, loss, expected):
    prev = ChannelNode(water_level=100)
    gate = _gate()
    gate.gate_upstream_water_level = None
    gate.gate_downstream_water_level = None
    gate.water_level = after
    gate.head_loss_gate = loss
    saved = (gate.water_level, gate.head_loss_total, gate.head_loss_gate)
    restore_gate_water_levels([prev, ChannelNode(is_transition=True, head_loss_transition=0.2), gate])
    assert gate.gate_upstream_water_level == pytest.approx(expected)
    assert gate.gate_downstream_water_level == after
    assert (gate.water_level, gate.head_loss_total, gate.head_loss_gate) == saved


def test_legacy_keeps_explicit_zero_and_first_gate_unknown():
    first = _gate()
    first.gate_upstream_water_level = None
    first.gate_downstream_water_level = 0
    first.water_level = 0
    next_gate = _gate()
    next_gate.gate_upstream_water_level = 0
    next_gate.gate_downstream_water_level = 0
    restore_gate_water_levels([first, next_gate])
    assert first.gate_upstream_water_level is None
    assert first.gate_downstream_water_level == 0
    assert next_gate.gate_upstream_water_level == 0
    assert next_gate.gate_downstream_water_level == 0
    missing = _gate()
    missing.water_level = 0
    missing.gate_upstream_water_level = missing.gate_downstream_water_level = None
    restore_gate_water_levels([first, missing])
    assert missing.gate_upstream_water_level is missing.gate_downstream_water_level is None


def test_gate_water_formula_lists_incoming_transition_and_gate_separately(capture_dialog):
    gate = _gate()
    prev = ChannelNode(water_level=100)
    transition = ChannelNode(is_transition=True, head_loss_transition=0.02)
    view = SimpleNamespace(_build_settings=lambda: ProjectSettings(start_water_level=100),
                           _calculate_exact_cumulative_loss_for_row=lambda nodes, row: sum(n.head_loss_transition if n.is_transition else n.head_loss_total for n in nodes[:row + 1]))
    panel_module.WaterProfilePanel._show_water_level_details(view, 2, gate, [prev, transition, gate])
    text = json.dumps(capture_dialog, ensure_ascii=False)
    assert "来水区间损失" in text and "中间渐变段小计" in text
    assert "100.000000 - 0.047000 - 0.020000 = 99.933000" in text
    assert "99.933000 - 0.100000 = 99.833000" in text
    assert "采用上一常规节点水位" not in text


def test_gate_bottom_formula_uses_slope_and_not_gate_after_depth(capture_dialog):
    details = _backfill()
    formula_dialog.show_terminal_gate_backfill_bottom_dialog(None, "双桥", details)
    text = json.dumps(capture_dialog, ensure_ascii=False)
    assert "无设计台阶" in text and "参考中心桩号" in text
    assert "98.000000 - 0.001000" in text and "100.000000 = 97.900000" in text
    assert "99.8330 - 2.0000" not in text


def test_gate_fallback_formula_uses_incoming_side_water(capture_dialog):
    details = _backfill()
    details["bottom"].update(method="normal_depth_fallback", incoming_water_level=99.933, result=97.933)
    formula_dialog.show_terminal_gate_backfill_bottom_dialog(None, "双桥", details)
    text = json.dumps(capture_dialog, ensure_ascii=False)
    assert "来水侧水位" in text
    assert "99.9330 - 2.0000 = 97.9330" in text
    assert "99.8330 - 2.0000" not in text


def test_connection_formula_keeps_design_depth_and_reports_actual_depth(capture_dialog):
    formula_dialog.show_gate_connection_bottom_dialog(None, "闸后补段", _profile(), 99.82, 1.5)
    text = json.dumps(capture_dialog, ensure_ascii=False)
    assert "97.900000 - 0.001000" in text and "20.000000 = 97.880000" in text
    assert "设计水深" in text and "1.500000" in text
    assert "99.820000 - 97.880000 = 1.940000" in text


def test_report_has_continuous_bottom_formula_and_both_depths():
    captured = []
    gate = _gate()
    gate.terminal_gate_backfill_details = _backfill()
    gate.bottom_elevation, gate.top_elevation = 97.9, 100.4
    connection = ChannelNode(name="闸后补段", structure_type=StructureType.MINGQU_RECTANGULAR,
                             is_auto_inserted_channel=True, station_MC=120, flow_section="2",
                             water_level=99.82, water_depth=1.5, velocity=0.8,
                             bottom_elevation=97.88, top_elevation=100.38,
                             connection_source_details={"gate_bed_profile": _profile()})
    view = SimpleNamespace(detail_text=SimpleNamespace(setPlainText=captured.append),
                           _describe_turn_radius_entry_usage=lambda _: "按各行值",
                           _build_terminal_gate_backfill_report_lines=lambda _: [])
    before = copy.deepcopy([n.to_dict() for n in (gate, connection)])
    panel_module.WaterProfilePanel._generate_detail_report(view, [gate, connection], ProjectSettings(start_water_level=100))
    assert [n.to_dict() for n in (gate, connection)] == before
    report = captured[0]
    assert "来水区间损失（不含另列渐变段） = 0.047000" in report
    assert "97.900000 - 0.001000 × 20.000000 = 97.880000" in report
    assert "设计水深 h设计 = 1.500000" in report and "实际水深 h实际 = 1.940000" in report
    view = SimpleNamespace(_collect_terminal_gate_backfill_records=lambda _: [gate.terminal_gate_backfill_details],
                           _format_terminal_gate_backfill_target=lambda _: "双桥",
                           _format_terminal_gate_backfill_source=lambda _: "上游明渠")
    explanation = "\n".join(panel_module.WaterProfilePanel._build_terminal_gate_backfill_report_lines(view, [gate]))
    assert "98.000000 - 0.001000 × 100.000000 = 97.900000" in explanation
    assert "99.833 - 2.000" not in explanation


@pytest.fixture
def actual_panel(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(BatchPanel, "_load_user_prefs", lambda _: None)
    for name in ("warning", "error", "info", "success"):
        monkeypatch.setattr(panel_module.InfoBar, name, lambda *args, **kwargs: None)
    # 此组用例隔离水力内核，专门验证已有分项结果的人工编辑与显示链。
    monkeypatch.setattr(HydraulicCalculator, "apply_gate_elevation_backfill", lambda self, nodes: [])
    panel = panel_module.WaterProfilePanel()
    panel.start_wl_edit.setText("100")
    panel._section_sync_ready = panel._transition_topology_prepared = True
    prev = ChannelNode(name="上游明渠", structure_type=StructureType.MINGQU_RECTANGULAR,
                       flow_section="1", water_level=100, station_MC=0)
    transition = ChannelNode(structure_type=StructureType.TRANSITION, is_transition=True,
                             head_loss_transition=0.02, head_loss_cumulative=0.02)
    gate = _gate()
    gate.terminal_gate_backfill_details = _backfill()
    gate.bottom_elevation, gate.top_elevation = 97.9, 100.4
    connection = ChannelNode(name="闸后补段", structure_type=StructureType.MINGQU_RECTANGULAR,
                             flow_section="2", is_auto_inserted_channel=True, station_MC=120,
                             water_level=99.82, water_depth=1.5, structure_height=2.5,
                             bottom_elevation=97.88, top_elevation=100.38,
                             connection_source_details={"gate_bed_profile": _profile()})
    panel.calculated_nodes = [prev, transition, gate, connection]
    panel.nodes = panel.calculated_nodes
    panel._settings = ProjectSettings(start_water_level=100)
    panel._update_table_from_nodes_full(panel.calculated_nodes)
    yield panel
    panel.deleteLater()
    app.processEvents()


def test_manual_loss_edit_does_not_reset_before_to_previous_water(actual_panel):
    panel = actual_panel
    assert panel._read_table_numeric_value(0, 41) == 100
    assert panel._read_table_numeric_value(1, 33) == pytest.approx(0.02)
    panel.node_table.setCurrentCell(2, 37)
    panel.node_table.item(2, 37).setText("0.2000")
    gate = panel.calculated_nodes[2]
    assert gate.gate_upstream_water_level == pytest.approx(99.933)
    assert gate.gate_downstream_water_level == pytest.approx(99.733)
    assert panel.node_table.item(2, 41).text() == "闸前 99.933\n闸后 99.733"
    assert panel.node_table.columnCount() == 44
    assert "至闸前的区间" in panel.node_table.item(2, 41).toolTip()
    panel._undo_loss_edit()
    assert panel.calculated_nodes[2].gate_upstream_water_level == pytest.approx(99.933)
    assert panel.calculated_nodes[2].gate_downstream_water_level == pytest.approx(99.833)
    panel._redo_loss_edit()
    assert panel.calculated_nodes[2].gate_upstream_water_level == pytest.approx(99.933)
    assert panel.calculated_nodes[2].gate_downstream_water_level == pytest.approx(99.733)


def test_legacy_table_recovers_own_before_and_refreshes_connection_geometry(actual_panel):
    panel = actual_panel
    gate_row = panel.node_table.item(2, 0)
    payload = gate_row.data(Qt.UserRole)
    payload.pop("_gate_upstream_water_level", None)
    payload.pop("_gate_downstream_water_level", None)
    gate_row.setData(Qt.UserRole, payload)
    panel._refresh_gate_water_level_cells()
    assert panel.node_table.item(2, 41).text() == "闸前 99.933\n闸后 99.833"
    connection = panel.calculated_nodes[3]
    connection.bottom_elevation, connection.top_elevation = 97.8754321, 100.3754321
    connection.connection_source_details["gate_bed_profile"].update(
        bottom_elevation=97.8754321, top_elevation=100.3754321, actual_water_depth=1.9445679)
    panel._refresh_gate_elevation_cells()
    assert panel.node_table.item(3, 42).text() == "97.875"
    assert panel.node_table.item(3, 43).text() == "100.375"
    assert panel._read_table_numeric_value(3, 42) == 97.8754321
    metadata = panel.node_table.item(3, 0).data(Qt.UserRole)
    assert metadata["_connection_source_details"]["gate_bed_profile"]["actual_water_depth"] == 1.9445679
    assert connection.water_depth == 1.5


def test_connection_bottom_dialog_dispatches_geometric_formula(actual_panel, capture_dialog):
    panel = actual_panel
    panel._show_bottom_elevation_details(3, panel.calculated_nodes[3], panel.calculated_nodes)
    text = json.dumps(capture_dialog, ensure_ascii=False)
    assert "连续渠底规则" in text and "实际水深" in text
    assert "97.900000 - 0.001000" in text


def test_successful_zero_connection_bed_is_not_missing(actual_panel):
    panel = actual_panel
    connection = panel.calculated_nodes[3]
    connection.bottom_elevation = 0
    connection.top_elevation = 2.5
    connection.connection_source_details["gate_bed_profile"].update(bottom_elevation=0, top_elevation=2.5)
    panel._refresh_gate_elevation_cells()
    assert panel.node_table.item(3, 42).text() == "0.000"
    assert panel.node_table.item(3, 43).text() == "2.500"
    assert panel._read_table_numeric_value(3, 42) == 0


def test_connection_geometric_metadata_restores_with_loss_snapshot(actual_panel):
    panel = actual_panel
    saved = panel._snapshot_editable_cols()
    original = copy.deepcopy(panel.calculated_nodes[3].connection_source_details)
    panel.calculated_nodes[3].connection_source_details["gate_bed_profile"]["actual_water_depth"] = 123
    panel._restore_loss_snapshot_overrides(saved)
    assert panel.calculated_nodes[3].connection_source_details == original


def test_elevation_refresh_updates_changed_siphon_neighbor_cells_without_recalculating_loss(actual_panel, monkeypatch):
    panel = actual_panel
    from 推求水面线.models.enums import InOutType
    inlet = ChannelNode(name="催龙村", structure_type=StructureType.INVERTED_SIPHON,
                        is_inverted_siphon=True, in_out=InOutType.INLET,
                        flow_section="2", water_level=99.8, bottom_elevation=98.3,
                        top_elevation=100.8, head_loss_total=0.02)
    panel.calculated_nodes.append(inlet)
    panel._update_table_from_nodes_full(panel.calculated_nodes)
    original_loss = inlet.head_loss_total
    called = []

    def sync_siphon_elevation(_calc, nodes):
        called.append(True)
        nodes[-1].bottom_elevation = nodes[-2].bottom_elevation
        nodes[-1].top_elevation = nodes[-2].top_elevation

    monkeypatch.setattr(HydraulicCalculator, "apply_siphon_outlet_elevation", sync_siphon_elevation)
    panel._refresh_gate_elevation_cells()
    assert called == [True]
    assert panel.node_table.item(4, 42).text() == "97.880"
    assert panel.node_table.item(4, 43).text() == "100.380"
    assert panel._read_table_numeric_value(4, 42) == 97.88
    assert inlet.head_loss_total == original_loss
