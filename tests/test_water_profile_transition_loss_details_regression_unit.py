# -*- coding: utf-8 -*-
"""表3 渐变段水头损失详情恢复与懒补建回归测试。"""

import importlib
import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from 推求水面线.core.hydraulic_calc import HydraulicCalculator
from 推求水面线.models.data_models import ChannelNode, ProjectSettings
from 推求水面线.models.enums import InOutType, StructureType


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _load_panel_module():
    panel_path = (ROOT / "app_渠系计算前端" / "water_profile" / "panel.py").resolve()
    spec = importlib.util.spec_from_file_location("wp_transition_loss_detail_regression", panel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_panel(module):
    _get_qapp()
    for attr in ("_open_transition_length_rules", "_show_node_table_context_menu"):
        if not hasattr(module.WaterProfilePanel, attr):
            setattr(module.WaterProfilePanel, attr, lambda self, *args, **kwargs: None)
    panel = module.WaterProfilePanel()
    panel.resize(1400, 900)
    return panel


def _make_nodes():
    upstream = ChannelNode()
    upstream.flow_section = "1"
    upstream.name = "-"
    upstream.structure_type = StructureType.from_string("明渠-梯形")
    upstream.section_params = {"B": 2.0, "m": 1.5, "h": 1.6, "A": 5.0, "X": 4.8, "R": 1.04}
    upstream.water_depth = 1.6
    upstream.velocity = 1.4
    upstream.roughness = 0.014
    upstream.flow = 5.0
    upstream.head_loss_total = 0.012
    upstream.head_loss_cumulative = 0.012

    transition = ChannelNode()
    transition.flow_section = "1"
    transition.name = "-"
    transition.structure_type = StructureType.TRANSITION
    transition.is_transition = True
    transition.transition_type = "进口"
    transition.transition_form = "曲线形反弯扭曲面"
    transition.transition_length = 9.0
    transition.roughness = 0.014
    transition.flow = 5.0
    transition.head_loss_cumulative = 0.012

    tunnel = ChannelNode()
    tunnel.flow_section = "1"
    tunnel.name = "隧洞1"
    tunnel.structure_type = StructureType.from_string("隧洞-圆形")
    tunnel.in_out = InOutType.INLET
    tunnel.section_params = {"D": 2.4, "A": 4.52, "X": 5.33, "R": 0.848}
    tunnel.water_depth = 1.8
    tunnel.velocity = 2.1
    tunnel.roughness = 0.014
    tunnel.flow = 5.0
    tunnel.head_loss_total = 0.034
    tunnel.head_loss_cumulative = 0.046

    HydraulicCalculator(ProjectSettings()).calculate_transition_loss(
        transition, upstream, tunnel, [upstream, transition, tunnel]
    )

    return [upstream, transition, tunnel]


def _legacy_transition_calc_details(details):
    return {
        "transition_type": details.get("transition_type"),
        "transition_form": details.get("transition_form"),
        "zeta": details.get("zeta"),
        "v1": details.get("v1"),
        "v2": details.get("v2"),
        "B1": details.get("B1"),
        "B2": details.get("B2"),
        "length": details.get("length"),
        "R_avg": details.get("R_avg"),
        "v_avg": details.get("v_avg"),
        "h_j1": details.get("h_j1"),
        "h_f": details.get("h_f"),
        "total": details.get("total"),
    }


def _make_bend_nodes():
    upstream = ChannelNode()
    upstream.flow_section = "1"
    upstream.name = "上游明渠"
    upstream.structure_type = StructureType.from_string("明渠-梯形")
    upstream.section_params = {"B": 2.2, "m": 1.5, "h": 1.4, "A": 6.02, "X": 5.84, "R": 1.03}
    upstream.water_depth = 1.4
    upstream.velocity = 1.1
    upstream.roughness = 0.014
    upstream.flow = 6.6
    upstream.water_level = 565.116

    bend = ChannelNode()
    bend.flow_section = "1"
    bend.name = "合作"
    bend.structure_type = StructureType.from_string("隧洞-圆拱直墙型")
    bend.section_params = {"B": 2.4, "m": 0.0, "h": 1.8, "A": 4.78, "X": 5.54, "R": 0.863}
    bend.water_depth = 1.8
    bend.velocity = 0.598
    bend.roughness = 0.014
    bend.flow = 6.6
    bend.arc_length = 5.698
    bend.turn_radius = 9.0

    calc = HydraulicCalculator(ProjectSettings())
    bend.head_loss_bend = calc.calculate_bend_loss(bend)
    bend.bend_calc_details = {}
    return [upstream, bend]


def test_project_reload_repairs_legacy_transition_loss_details():
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        nodes = _make_nodes()
        panel.calculated_nodes = nodes
        panel._update_table_from_nodes_full(nodes)
        _flush_events()

        state = panel.to_project_dict()
        legacy = _legacy_transition_calc_details(state["calculated_nodes"][1]["transition_calc_details"])
        state["calculated_nodes"][1]["transition_calc_details"] = legacy
    finally:
        panel.deleteLater()

    restored = _build_panel(module)
    try:
        restored.from_project_dict(state, skip_dirty_signal=True)
        _flush_events()

        repaired = restored.calculated_nodes[1].transition_calc_details
        assert repaired.get("R1") > 0
        assert repaired.get("R2") > 0
        assert repaired.get("n") == 0.014
        assert repaired.get("hydraulic_slope_i") > 0
        assert isinstance(repaired.get("length_details"), dict)
    finally:
        restored.deleteLater()


def test_show_transition_details_lazy_repairs_legacy_details(monkeypatch):
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        panel.calculated_nodes = _make_nodes()
        panel._update_table_from_nodes_full(panel.calculated_nodes)
        panel.calculated_nodes[1].transition_calc_details = _legacy_transition_calc_details(
            panel.calculated_nodes[1].transition_calc_details
        )
        _flush_events()

        dialog_calls = []
        info_calls = []
        formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")

        monkeypatch.setattr(
            formula_module,
            "show_transition_loss_dialog",
            lambda parent, node_name, details: dialog_calls.append((parent, node_name, details)),
        )
        monkeypatch.setattr(module, "fluent_info", lambda *args, **kwargs: info_calls.append((args, kwargs)))

        panel._show_transition_calc_details(1, panel.calculated_nodes[1])

        assert dialog_calls, "双击时应先补齐旧版渐变段损失详情"
        assert not info_calls, "补齐成功后不应提示失败"
        details = dialog_calls[0][2]
        assert details.get("R1") > 0
        assert details.get("R2") > 0
        assert details.get("hydraulic_slope_i") > 0
        assert isinstance(details.get("length_details"), dict)
    finally:
        panel.deleteLater()


def test_project_reload_repairs_transition_loss_details_with_override_length():
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        nodes = _make_nodes()
        nodes[1].transition_length = 5.0
        nodes[1].transition_length_override_m = 5.0
        panel.calculated_nodes = nodes
        panel._update_table_from_nodes_full(nodes)
        _flush_events()

        state = panel.to_project_dict()
        state["calculated_nodes"][1]["transition_length_calc_details"] = {}
        state["calculated_nodes"][1]["transition_calc_details"] = {}
        state["calculated_nodes"][1]["transition_length"] = 5.0
        state["calculated_nodes"][1]["transition_length_override_m"] = 5.0
        state["calculated_nodes"][1]["transition_length_source"] = "override"
        state["node_table_rows"][1][32] = "5.000"
    finally:
        panel.deleteLater()

    restored = _build_panel(module)
    try:
        restored.from_project_dict(state, skip_dirty_signal=True)
        _flush_events()

        repaired = restored.calculated_nodes[1].transition_calc_details
        assert repaired, "加载项目后应补建渐变段水头损失详情"
        assert repaired.get("length") == 5.0
        assert repaired.get("R1") > 0
        assert repaired.get("R2") > 0
        length_details = repaired.get("length_details") or {}
        assert length_details.get("actual_length") == 5.0
        assert length_details.get("source") == "override"
        assert (length_details.get("formula_length") or 0.0) > 5.0
        assert "单条覆盖长度小于公式/规范值" in (length_details.get("warning") or "")
    finally:
        restored.deleteLater()


def test_show_bend_details_lazy_repairs_missing_details(monkeypatch):
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        panel.calculated_nodes = _make_bend_nodes()
        panel._update_table_from_nodes_full(panel.calculated_nodes)
        _flush_events()

        dialog_calls = []
        info_calls = []
        formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")

        monkeypatch.setattr(
            formula_module,
            "show_bend_loss_dialog",
            lambda parent, node_name, details: dialog_calls.append((parent, node_name, details)),
        )
        monkeypatch.setattr(module, "fluent_info", lambda *args, **kwargs: info_calls.append((args, kwargs)))

        panel._show_bend_calc_details(1, panel.calculated_nodes[1])

        assert dialog_calls, "弯道损失已有数值但详情缺失时，双击应先懒补建详情"
        assert not info_calls, "懒补建成功后不应提示“没有弯道水头损失计算数据”"
        details = dialog_calls[0][2]
        assert details.get("hw", 0.0) > 0.0
        assert details.get("L", 0.0) > 0.0
        assert details.get("Rc", 0.0) > 0.0
    finally:
        panel.deleteLater()
