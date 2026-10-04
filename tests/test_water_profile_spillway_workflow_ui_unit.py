# -*- coding: utf-8 -*-
"""表3泄水渠连续链参数编辑、结果失效和工程往返验证。"""

import copy
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("CODEX_FORCE_QTEXTBROWSER", "1")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QTableWidget, QTextEdit

from app_渠系计算前端.water_profile import panel as panel_module
from app_渠系计算前端.water_profile.panel import WaterProfilePanel
from 推求水面线.core.spillway_steep_chute_adapter import (
    SPILLWAY_STEEP_CHUTE_PARAM_KEY,
    get_spillway_steep_chute_chain_indexes,
    resolve_spillway_steep_chute_chain_advanced_params,
)
from 推求水面线.models.data_models import ChannelNode
from 推求水面线.models.enums import StructureType


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app, monkeypatch):
    monkeypatch.setattr(panel_module, "fluent_info", lambda *_args, **_kwargs: None)
    widget = WaterProfilePanel()
    yield widget
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def _node(index, name="", flow_section="1", structure="泄水渠与陡坡", payload=None):
    """构造具有表3基础资料的真实节点。"""
    node = ChannelNode()
    node.name = name
    node.flow_section = flow_section
    node.structure_type = StructureType.from_string(structure)
    node.station_MC = index * 20.0
    node.x = index * 20.0
    node.flow = node.design_flow = 0.7
    node.roughness = 0.014
    node.slope_i = 0.05
    node.water_depth = 0.3
    node.water_level = 100.0 - index
    node.head_loss_reserve = 0.03
    node.head_loss_gate = 0.2
    node.head_loss_total = 0.4
    node.head_loss_cumulative = index * 0.4
    node.section_params = {"B": 1.0, "m": 0.0}
    if payload is not None:
        node.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY] = copy.deepcopy(payload)
    return node


def _load(panel, nodes):
    panel.nodes = nodes
    panel._update_table_from_nodes_full(nodes)


def _click_save(dialog):
    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()


def test_edit_scope_matches_kernel_continuous_chain_not_repeated_name(panel):
    nodes = [
        _node(0, "同名"), _node(1, "另一名称"), _node(2, ""),
        _node(3, "间隔", structure="明渠-矩形"),
        _node(4, "同名"), _node(5, "同名"),
        _node(6, "同名", "2"), _node(7, "同名", "2"),
    ]
    nodes[1].slope_i = 0.02
    _load(panel, nodes)
    rebuilt = panel._build_nodes_from_table()
    for row, expected in ((1, [0, 1, 2]), (4, [4, 5]), (7, [6, 7])):
        assert panel._spillway_steep_chute_group_rows(row) == expected
        assert panel._spillway_steep_chute_group_rows(row) == get_spillway_steep_chute_chain_indexes(rebuilt, row)


def test_default_details_use_existing_table_and_fold_optional_inputs(panel, app):
    _load(panel, [_node(0), _node(1)])
    dialog = panel._create_spillway_steep_chute_details_dialog(0)
    dialog.show()
    app.processEvents()
    try:
        assert all(group.is_collapsed() for group in dialog._spillway_groups.values())
        base = dialog.findChild(QTableWidget, "spillwayBasicInputsTable")
        assert base.rowCount() == 2
        assert float(base.item(0, 1).text()) == pytest.approx(0.7)
        assert float(base.item(0, 2).text()) == pytest.approx(1.0)
        assert base.item(0, 3).text() == "0"
        assert not (set(dialog._spillway_editors) & {"Q", "b", "m", "n", "L"})
        assert dialog._spillway_editors["inlet_head"].text() == ""
        assert dialog._spillway_editors["downstream_tailwater_depth"].text() == ""
        assert not dialog._spillway_editors["alpha_profile"].isVisible()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_isolated_incomplete_row_can_open_details_before_hydraulic_validation(panel):
    node = _node(0)
    node.section_params["B"] = 0
    _load(panel, [node])
    dialog = panel._create_spillway_steep_chute_details_dialog(0)
    assert dialog is not None
    assert panel._spillway_steep_chute_group_rows(0) == [0]
    dialog.deleteLater()


def test_patch_preserves_unknown_fields_and_invalidates_results_and_export_gate(panel, monkeypatch):
    payload = {"advanced_params": {"alpha_profile": 1.1, "future_parameter": {"value": 7}},
               "display_structure_type": "陡坡", "result": {"summary": {"旧": 9}},
               "input": {"manual_start_depth": 4.9}, "display_point": {"velocity_ms": 9}, "success": True}
    nodes = [_node(0, "同名", payload=payload), _node(1, "另名", payload=payload),
             _node(2, "间隔", structure="明渠-矩形"),
             _node(3, "同名", payload={"advanced_params": {"alpha_profile": 1.2}}), _node(4, "同名")]
    _load(panel, nodes)
    panel.calculated_nodes = nodes
    panel._apply_spillway_steep_chute_advanced_params(0, {"alpha_profile": 1.05})
    for row in (0, 1):
        stored = panel._get_spillway_steep_chute_payload_for_row(row)
        assert stored["advanced_params"]["alpha_profile"] == pytest.approx(1.05)
        assert stored["advanced_params"]["future_parameter"] == {"value": 7}
        assert "manual_start_depth" not in stored["advanced_params"]
        assert stored["display_structure_type"] == "陡坡"
        assert stored["params_dirty"] is True
        assert not ({"input", "result", "display_point"} & set(stored))
        assert panel.node_table.item(row, 39).text() == ""
        assert panel.node_table.item(row, 40).text() == ""
        assert panel.node_table.item(row, 41).text() == ""
        assert float(panel.node_table.item(row, 36).text()) == pytest.approx(0.03)
        assert float(panel.node_table.item(row, 37).text()) == pytest.approx(0.2)
    assert panel._get_spillway_steep_chute_payload_for_row(3)["advanced_params"]["alpha_profile"] == pytest.approx(1.2)
    assert panel.calculated_nodes == []
    notices = []
    monkeypatch.setattr(panel_module, "WORD_EXPORT_AVAILABLE", True)
    monkeypatch.setattr(panel_module.InfoBar, "warning", lambda title, text, **kwargs: notices.append(text))

    def unexpected_save_dialog(*_args, **_kwargs):
        raise AssertionError("过期成果不应进入文件保存对话框")

    monkeypatch.setattr(panel_module.QFileDialog, "getSaveFileName", unexpected_save_dialog)
    panel._export_excel()
    panel._export_word()
    assert notices == ["无结果可导出，请先执行计算", "请先进行计算。"]


def test_clear_optional_values_cannot_restore_previous_calculation_input(panel):
    payload = {"advanced_params": {"inlet_weir_width": 1.8, "inlet_head": 1.5, "downstream_tailwater_depth": 2.0},
               "input": {"inlet_weir_width": 1.8, "inlet_head": 1.5, "downstream_tailwater_depth": 2.0},
               "result": {"summary": {"旧池深": 0.8}}}
    _load(panel, [_node(0, payload=payload), _node(1, payload=payload)])
    dialog = panel._create_spillway_steep_chute_details_dialog(1)
    for key in ("inlet_weir_width", "inlet_head", "downstream_tailwater_depth"):
        dialog._spillway_editors[key].clear()
    _click_save(dialog)
    resolved = resolve_spillway_steep_chute_chain_advanced_params(panel._build_nodes_from_table(), 0)
    for key in ("inlet_weir_width", "inlet_head", "downstream_tailwater_depth"):
        assert resolved.get(key) is None
        assert panel._get_spillway_steep_chute_payload_for_row(0)["advanced_params"][key] is None
    assert dialog._spillway_changed is True
    dialog.deleteLater()


def test_view_and_save_without_edit_does_not_rewrite_parameters_or_drop_results(panel):
    payload = {"advanced_params": {"alpha_profile": 1.05, "unknown": 2}, "result": {"summary": {"原结果": 1}}}
    nodes = [_node(0, payload=payload), _node(1, payload=payload)]
    _load(panel, nodes)
    panel.calculated_nodes = nodes
    before = panel._get_spillway_steep_chute_payload_for_row(0)
    dialog = panel._create_spillway_steep_chute_details_dialog(1)
    for group in dialog._spillway_groups.values():
        group.toggle()
    _click_save(dialog)
    assert dialog._spillway_changed is False
    assert panel._get_spillway_steep_chute_payload_for_row(0) == before
    assert panel.calculated_nodes is nodes
    dialog.deleteLater()


def test_unsolved_table_edit_roundtrips_through_project_nodes(panel, app):
    _load(panel, [_node(0, "首行"), _node(1, "末行")])
    panel.nodes = []
    panel.calculated_nodes = []
    panel._apply_spillway_steep_chute_advanced_params(1, {"downstream_tailwater_depth": 1.8, "manual_start_depth": 0.25})
    saved = panel.to_project_dict()
    assert len(saved["nodes"]) == 2
    restored = WaterProfilePanel()
    try:
        restored.from_project_dict(saved, skip_dirty_signal=True)
        params = resolve_spillway_steep_chute_chain_advanced_params(restored._build_nodes_from_table(), 1)
        assert params["downstream_tailwater_depth"] == pytest.approx(1.8)
        assert params["manual_start_depth"] == pytest.approx(0.25)
        assert restored.calculated_nodes == []
        assert "result" not in restored._get_spillway_steep_chute_payload_for_row(1)
    finally:
        restored.close()
        restored.deleteLater()
        app.processEvents()


def test_result_summary_uses_terminal_dissipation_and_separates_energy_from_water_level(panel):
    payload = {"role": "middle", "chain_water_level_drop_m": 4.2, "chain_head_loss_total": 3.1,
               "result": {"hydraulic_jump": {"recommended_pool_depth_m": 99},
                          "aeration_and_sidewall": {"recommended_sidewall_height_m": 1.5, "message": "已校核加大流量"}}}
    terminal = {"result": {"hydraulic_jump": {"status": "missing_tailwater", "design_available": False,
                                             "conjugate_depth_m": 2.2, "recommended_pool_depth_m": None,
                                             "recommended_pool_length_m": 0.0, "message": "待补末端尾水"}}}
    text = "\n".join(panel._build_spillway_steep_chute_result_lines(1, _node(1), payload, terminal))
    assert "全链水位降：4.2000 m" in text
    assert "全链能量损失：3.1000 m" in text
    assert "已校核加大流量" in text
    assert "消能状态：待补尾水" in text
    assert "消力池深度：未计算" in text
    assert "消力池长度：0.000 m" in text
    assert "99" not in text


def test_dirty_payload_never_exposes_old_numeric_results(panel):
    text = "\n".join(panel._build_spillway_steep_chute_result_lines(0, _node(0), {
        "params_dirty": True, "result": {"profile": {"end_depth_m": 123.456}},
    }))
    assert "重新执行" in text
    assert "123.456" not in text


def test_invalid_input_keeps_details_open_without_saving(panel, app):
    _load(panel, [_node(0), _node(1)])
    dialog = panel._create_spillway_steep_chute_details_dialog(0)
    dialog.show()
    app.processEvents()
    dialog._spillway_editors["downstream_tailwater_depth"].setText("nan")
    _click_save(dialog)
    assert dialog.isVisible()
    assert dialog._spillway_changed is False
    dialog.close()
    dialog.deleteLater()
