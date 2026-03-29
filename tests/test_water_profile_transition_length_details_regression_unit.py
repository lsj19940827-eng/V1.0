# -*- coding: utf-8 -*-
"""表3 渐变段长度详情恢复与懒补建回归测试。"""

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

from 推求水面线.models.data_models import ChannelNode
from 推求水面线.models.enums import InOutType, StructureType


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _load_panel_module():
    panel_path = (ROOT / "app_渠系计算前端" / "water_profile" / "panel.py").resolve()
    spec = importlib.util.spec_from_file_location("wp_transition_length_detail_regression", panel_path)
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

    return [upstream, transition, tunnel]


def _make_rule_pair_nodes():
    upstream = ChannelNode()
    upstream.flow_section = "1"
    upstream.name = "暗涵出口"
    upstream.structure_type = StructureType.from_string("矩形暗涵")
    upstream.in_out = InOutType.OUTLET
    upstream.station_MC = 0.0
    upstream.section_params = {"B": 2.0, "H_total": 2.2, "A": 3.1, "X": 5.2, "R": 0.596}
    upstream.water_depth = 1.4
    upstream.velocity = 1.8
    upstream.roughness = 0.014
    upstream.flow = 5.0

    downstream = ChannelNode()
    downstream.flow_section = "1"
    downstream.name = "隧洞进口"
    downstream.structure_type = StructureType.from_string("隧洞-圆形")
    downstream.in_out = InOutType.INLET
    downstream.station_MC = 30.0
    downstream.section_params = {"D": 2.6, "A": 5.1, "X": 5.8, "R": 0.879}
    downstream.water_depth = 1.8
    downstream.velocity = 2.1
    downstream.roughness = 0.014
    downstream.flow = 5.0

    return [upstream, downstream]


def _make_transition_edit_nodes():
    upstream = ChannelNode()
    upstream.flow_section = "1"
    upstream.name = "隧洞出口"
    upstream.structure_type = StructureType.from_string("隧洞-圆形")
    upstream.in_out = InOutType.OUTLET
    upstream.station_MC = 0.0
    upstream.section_params = {"D": 2.4, "A": 4.52, "X": 5.33, "R": 0.848}
    upstream.water_depth = 1.8
    upstream.velocity = 2.0
    upstream.roughness = 0.014
    upstream.flow = 5.0

    transition_out = ChannelNode()
    transition_out.flow_section = "1"
    transition_out.name = "-"
    transition_out.structure_type = StructureType.TRANSITION
    transition_out.is_transition = True
    transition_out.transition_type = "出口"
    transition_out.transition_form = "曲线形反弯扭曲面"
    transition_out.transition_length = 5.0
    transition_out.transition_rule_upstream_structure_type = "隧洞-圆形"
    transition_out.transition_rule_downstream_structure_type = "矩形暗涵"
    transition_out.transition_length_calc_details = {
        "transition_type": "出口",
        "actual_length": 5.0,
        "formula_length": 5.0,
        "source": "formula",
        "upstream_structure_type": "隧洞-圆形",
        "downstream_structure_type": "矩形暗涵",
    }
    transition_out.roughness = 0.014
    transition_out.flow = 5.0

    open_channel = ChannelNode()
    open_channel.flow_section = "1"
    open_channel.name = "-"
    open_channel.structure_type = StructureType.from_string("明渠-矩形")
    open_channel.is_auto_inserted_channel = True
    open_channel.station_MC = 10.0
    open_channel.stat_length = 3.0
    open_channel.section_params = {"B": 2.2, "m": 0.0, "h": 1.6, "A": 3.52, "X": 5.4, "R": 0.652}
    open_channel.water_depth = 1.6
    open_channel.velocity = 1.5
    open_channel.roughness = 0.014
    open_channel.flow = 5.0

    transition_in = ChannelNode()
    transition_in.flow_section = "1"
    transition_in.name = "-"
    transition_in.structure_type = StructureType.TRANSITION
    transition_in.is_transition = True
    transition_in.transition_type = "进口"
    transition_in.transition_form = "曲线形反弯扭曲面"
    transition_in.transition_length = 4.0
    transition_in.transition_rule_upstream_structure_type = "隧洞-圆形"
    transition_in.transition_rule_downstream_structure_type = "矩形暗涵"
    transition_in.transition_length_calc_details = {
        "transition_type": "进口",
        "actual_length": 4.0,
        "formula_length": 4.0,
        "source": "formula",
        "upstream_structure_type": "隧洞-圆形",
        "downstream_structure_type": "矩形暗涵",
    }
    transition_in.roughness = 0.014
    transition_in.flow = 5.0

    downstream = ChannelNode()
    downstream.flow_section = "1"
    downstream.name = "暗涵进口"
    downstream.structure_type = StructureType.from_string("矩形暗涵")
    downstream.in_out = InOutType.INLET
    downstream.station_MC = 18.0
    downstream.section_params = {"B": 2.0, "H_total": 2.2, "A": 3.0, "X": 5.1, "R": 0.588}
    downstream.water_depth = 1.5
    downstream.velocity = 1.9
    downstream.roughness = 0.014
    downstream.flow = 5.0

    return [upstream, transition_out, open_channel, transition_in, downstream]


def _make_direct_gap_transition_nodes():
    upstream = ChannelNode()
    upstream.flow_section = "1"
    upstream.name = "-"
    upstream.structure_type = StructureType.from_string("明渠-圆形")
    upstream.station_MC = 10097.309
    upstream.section_params = {"D": 0.9, "A": 0.636, "X": 2.827, "R": 0.225}
    upstream.water_depth = 0.65
    upstream.velocity = 1.3
    upstream.roughness = 0.014
    upstream.flow = 0.51

    transition = ChannelNode()
    transition.flow_section = "1"
    transition.name = "-"
    transition.structure_type = StructureType.TRANSITION
    transition.is_transition = True
    transition.transition_type = "进口"
    transition.transition_form = "曲线形反弯扭曲面"
    transition.transition_length = 5.4
    transition.transition_rule_upstream_structure_type = "明渠-圆形"
    transition.transition_rule_downstream_structure_type = "隧洞-圆拱直墙型"
    transition.transition_length_calc_details = {
        "transition_type": "进口",
        "actual_length": 5.4,
        "formula_length": 5.4,
        "source": "formula",
        "upstream_structure_type": "明渠-圆形",
        "downstream_structure_type": "隧洞-圆拱直墙型",
    }
    transition.roughness = 0.014
    transition.flow = 0.51

    downstream = ChannelNode()
    downstream.flow_section = "1"
    downstream.name = "合作"
    downstream.structure_type = StructureType.from_string("隧洞-圆拱直墙型")
    downstream.in_out = InOutType.INLET
    downstream.station_MC = 10112.880
    downstream.section_params = {"D": 0.95, "A": 0.709, "X": 3.012, "R": 0.235}
    downstream.water_depth = 0.7
    downstream.velocity = 1.4
    downstream.roughness = 0.014
    downstream.flow = 0.51

    return [upstream, transition, downstream]


def test_project_reload_repairs_missing_transition_length_details():
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        nodes = _make_nodes()
        panel.calculated_nodes = nodes
        panel._update_table_from_nodes_full(nodes)
        _flush_events()

        state = panel.to_project_dict()
        state["calculated_nodes"][1]["transition_length_calc_details"] = {}
        state["node_table_rows"][1][32] = "9.000"
    finally:
        panel.deleteLater()

    restored = _build_panel(module)
    try:
        restored.from_project_dict(state, skip_dirty_signal=True)
        _flush_events()

        repaired = restored.calculated_nodes[1].transition_length_calc_details
        assert repaired, "加载旧项目后应自动补建渐变段长度详情"
        assert restored.node_table.item(1, 32).text() == "9.000"
        assert repaired.get("actual_length") == 9.0
        assert repaired.get("L_result") == 9.0
    finally:
        restored.deleteLater()


def test_rule_rows_require_existing_transition_instances():
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        raw_nodes = _make_rule_pair_nodes()
        panel.nodes = raw_nodes
        panel.calculated_nodes = []
        panel._update_table_from_nodes_full(raw_nodes)
        _flush_events()

        rows = panel._collect_transition_length_rule_rows()

        assert rows == []
    finally:
        panel.deleteLater()


def test_rule_rows_switch_to_current_hit_scope_after_transitions_exist():
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        nodes = _make_transition_edit_nodes()
        panel.calculated_nodes = nodes
        panel._update_table_from_nodes_full(nodes)
        _flush_events()

        rows = panel._collect_transition_length_rule_rows()

        rule_keys = {
            (
                row["upstream_structure_type"],
                row["downstream_structure_type"],
                row["transition_type"],
                row["count"],
                row["hit_count"],
                row["hit_scope"],
            )
            for row in rows
        }
        assert ("隧洞-圆形", "矩形暗涵", "出口", 1, 1, "current") in rule_keys
        assert ("隧洞-圆形", "矩形暗涵", "进口", 1, 1, "current") in rule_keys
    finally:
        panel.deleteLater()


def test_transition_length_rule_dialog_displays_hit_scope_copy():
    module = _load_panel_module()
    _get_qapp()
    dialog = module.TransitionLengthRuleDialog(
        [
            {
                "rule_key": "矩形暗涵|隧洞-圆形|进口",
                "upstream_structure_type": "矩形暗涵",
                "downstream_structure_type": "隧洞-圆形",
                "transition_type": "进口",
                "count": 1,
                "hit_count": 2,
                "hit_scope": "current",
                "rule_mode": "formula",
                "step_size_m": 1.0,
                "fixed_length_m": 0.0,
            }
        ]
    )
    try:
        assert dialog.table.columnCount() == 8
        assert dialog.table.horizontalHeaderItem(3).text() == "命中情况"
        assert dialog.table.item(0, 3).text() == "当前命中 2 条"
    finally:
        dialog.deleteLater()


def test_open_transition_length_rules_requires_inserted_transition_instances(monkeypatch):
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        raw_nodes = _make_rule_pair_nodes()
        panel.nodes = raw_nodes
        panel._update_table_from_nodes_full(raw_nodes)
        _flush_events()

        dialog_calls = []
        prompt_calls = []

        class _UnexpectedDialog:
            def __init__(self, rows, parent=None):
                dialog_calls.append((rows, parent))

            def exec(self):
                raise AssertionError("插入前不应打开长度规则编辑表")

        monkeypatch.setattr(module, "TransitionLengthRuleDialog", _UnexpectedDialog)
        monkeypatch.setattr(
            panel,
            "_show_transition_length_rules_insert_first_dialog",
            lambda: prompt_calls.append("shown"),
            raising=False,
        )

        panel._open_transition_length_rules()

        assert prompt_calls == ["shown"]
        assert dialog_calls == []
    finally:
        panel.deleteLater()


def test_insert_transitions_no_longer_defers_to_length_rule_nudge(monkeypatch):
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        panel.node_table.setRowCount(2)
        panel.design_flow_edit.setText("5.0")
        panel.max_flow_edit.setText("5.5")
        monkeypatch.setattr(panel, "_ensure_downstream_ready", lambda _action: True)
        build_settings_calls = []
        monkeypatch.setattr(panel, "_build_settings", lambda: build_settings_calls.append("called") or None)

        panel._insert_transitions()

        assert build_settings_calls
    finally:
        panel.deleteLater()


def test_open_transition_length_rules_after_insert_uses_current_rows_only(monkeypatch):
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        nodes = _make_transition_edit_nodes()
        panel.calculated_nodes = nodes
        panel._update_table_from_nodes_full(nodes)
        _flush_events()

        rule_rows = [
            {
                "rule_key": "隧洞-圆形|矩形暗涵|出口",
                "upstream_structure_type": "隧洞-圆形",
                "downstream_structure_type": "矩形暗涵",
                "transition_type": "出口",
                "count": 1,
                "hit_count": 1,
                "hit_scope": "current",
                "rule_mode": "formula",
                "step_size_m": 1.0,
                "fixed_length_m": 0.0,
            }
        ]

        seen_rows = []

        class _AcceptedDialog:
            def __init__(self, rows, parent=None):
                self.rows = rows
                seen_rows.extend(rows)

            def exec(self):
                return module.QDialog.DialogCode.Accepted

            def get_rules(self):
                return {
                    row["rule_key"]: {
                        "rule_key": row["rule_key"],
                        "upstream_structure_type": row["upstream_structure_type"],
                        "downstream_structure_type": row["downstream_structure_type"],
                        "transition_type": row["transition_type"],
                        "rule_mode": row["rule_mode"],
                        "step_size_m": row["step_size_m"],
                        "fixed_length_m": row["fixed_length_m"],
                    }
                    for row in self.rows
                }

        monkeypatch.setattr(module, "TransitionLengthRuleDialog", _AcceptedDialog)
        monkeypatch.setattr(panel, "_collect_transition_length_rule_rows", lambda *_args, **_kwargs: rule_rows)
        monkeypatch.setattr(panel, "_get_transition_nodes_for_editing", lambda source_nodes=None: (nodes, True))
        monkeypatch.setattr(panel, "_build_settings", lambda: object())
        monkeypatch.setattr(panel, "_refresh_all_transition_length_presentations", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(panel, "_rebuild_calculation_summary_state", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(panel, "_recalc_downstream", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(panel, "_apply_transition_length_override", lambda *_args, **_kwargs: False)

        panel._open_transition_length_rules()

        assert seen_rows == rule_rows
        assert all(row["hit_scope"] == "current" for row in seen_rows)
    finally:
        panel.deleteLater()


def test_open_transition_length_rules_reports_updated_and_skipped_rows(monkeypatch):
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        nodes = _make_transition_edit_nodes()
        nodes[1].transition_length_override_m = 5.0
        panel.calculated_nodes = nodes
        panel._update_table_from_nodes_full(nodes)
        _flush_events()

        rule_rows = [
            {
                "rule_key": "隧洞-圆形|矩形暗涵|出口",
                "upstream_structure_type": "隧洞-圆形",
                "downstream_structure_type": "矩形暗涵",
                "transition_type": "出口",
                "count": 1,
                "hit_count": 1,
                "hit_scope": "current",
                "rule_mode": "formula",
                "step_size_m": 1.0,
                "fixed_length_m": 0.0,
            },
            {
                "rule_key": "隧洞-圆形|矩形暗涵|进口",
                "upstream_structure_type": "隧洞-圆形",
                "downstream_structure_type": "矩形暗涵",
                "transition_type": "进口",
                "count": 1,
                "hit_count": 1,
                "hit_scope": "current",
                "rule_mode": "step_up",
                "step_size_m": 1.0,
                "fixed_length_m": 0.0,
            },
        ]

        class _AcceptedDialog:
            def __init__(self, rows, parent=None):
                self.rows = rows

            def exec(self):
                return module.QDialog.DialogCode.Accepted

            def get_rules(self):
                return {
                    row["rule_key"]: {
                        "rule_key": row["rule_key"],
                        "upstream_structure_type": row["upstream_structure_type"],
                        "downstream_structure_type": row["downstream_structure_type"],
                        "transition_type": row["transition_type"],
                        "rule_mode": row["rule_mode"],
                        "step_size_m": row["step_size_m"],
                        "fixed_length_m": row["fixed_length_m"],
                    }
                    for row in self.rows
                }

        monkeypatch.setattr(module, "TransitionLengthRuleDialog", _AcceptedDialog)
        monkeypatch.setattr(panel, "_collect_transition_length_rule_rows", lambda *_args, **_kwargs: rule_rows)
        monkeypatch.setattr(panel, "_get_transition_nodes_for_editing", lambda source_nodes=None: (nodes, True))
        monkeypatch.setattr(panel, "_build_settings", lambda: object())
        monkeypatch.setattr(panel, "_refresh_all_transition_length_presentations", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(panel, "_rebuild_calculation_summary_state", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(panel, "_recalc_downstream", lambda *_args, **_kwargs: None)

        def _fake_apply(row_idx, **kwargs):
            source_nodes = kwargs.get("source_nodes") or nodes
            if row_idx == 3:
                source_nodes[row_idx].transition_length = 6.0
                source_nodes[row_idx].transition_length_calc_details = {
                    "distance_clamped": True,
                    "warning": "规则长度受现有拓扑限制",
                }
                return True
            raise AssertionError("单条覆盖行应被跳过，不应重复应用组合规则")

        monkeypatch.setattr(panel, "_apply_transition_length_override", _fake_apply)

        success_calls = []
        warning_calls = []
        monkeypatch.setattr(module.InfoBar, "success", lambda *args, **kwargs: success_calls.append((args, kwargs)))
        monkeypatch.setattr(module.InfoBar, "warning", lambda *args, **kwargs: warning_calls.append((args, kwargs)))

        panel._open_transition_length_rules()

        assert success_calls, "保存规则后应反馈更新和跳过数量"
        success_text = " ".join(str(part) for part in success_calls[0][0])
        assert "已更新 1 条" in success_text
        assert "1 条因单条覆盖未改" in success_text
        assert "1 条受物理极限约束" in success_text
        assert warning_calls == []
    finally:
        panel.deleteLater()


def test_open_transition_length_rules_clamps_requested_length_to_physical_limit(monkeypatch):
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        panel.start_wl_edit.setText("420.000")
        nodes = _make_transition_edit_nodes()
        panel.calculated_nodes = nodes
        panel._update_table_from_nodes_full(nodes)
        _flush_events()

        rule_rows = [
            {
                "rule_key": "隧洞-圆形|矩形暗涵|出口",
                "upstream_structure_type": "隧洞-圆形",
                "downstream_structure_type": "矩形暗涵",
                "transition_type": "出口",
                "count": 1,
                "hit_count": 1,
                "hit_scope": "current",
                "rule_mode": "formula",
                "step_size_m": 1.0,
                "fixed_length_m": 0.0,
            },
            {
                "rule_key": "隧洞-圆形|矩形暗涵|进口",
                "upstream_structure_type": "隧洞-圆形",
                "downstream_structure_type": "矩形暗涵",
                "transition_type": "进口",
                "count": 1,
                "hit_count": 1,
                "hit_scope": "current",
                "rule_mode": "fixed",
                "step_size_m": 1.0,
                "fixed_length_m": 10.0,
            },
        ]

        class _AcceptedDialog:
            def __init__(self, rows, parent=None):
                self.rows = rows

            def exec(self):
                return module.QDialog.DialogCode.Accepted

            def get_rules(self):
                return {
                    row["rule_key"]: {
                        "rule_key": row["rule_key"],
                        "upstream_structure_type": row["upstream_structure_type"],
                        "downstream_structure_type": row["downstream_structure_type"],
                        "transition_type": row["transition_type"],
                        "rule_mode": row["rule_mode"],
                        "step_size_m": row["step_size_m"],
                        "fixed_length_m": row["fixed_length_m"],
                    }
                    for row in self.rows
                }

        monkeypatch.setattr(module, "TransitionLengthRuleDialog", _AcceptedDialog)
        monkeypatch.setattr(panel, "_collect_transition_length_rule_rows", lambda *_args, **_kwargs: rule_rows)

        success_calls = []
        warning_calls = []
        monkeypatch.setattr(module.InfoBar, "success", lambda *args, **kwargs: success_calls.append((args, kwargs)))
        monkeypatch.setattr(module.InfoBar, "warning", lambda *args, **kwargs: warning_calls.append((args, kwargs)))

        panel._open_transition_length_rules()

        details = panel.calculated_nodes[3].transition_length_calc_details
        assert panel.node_table.item(3, 32).text() == "7.000"
        assert details["requested_length"] == 10.0
        assert details["physical_limit"] == 7.0
        assert details["actual_length"] == 7.0
        assert details["distance_clamped"] is True
        tooltip = panel._build_transition_length_tooltip(details)
        assert "规则目标长度：10.000 m" in tooltip
        assert "物理上限：7.000 m" in tooltip
        assert "最终采用长度：7.000 m" in tooltip
        assert success_calls, "应用规则后应给出更新摘要"
        success_text = " ".join(str(part) for part in success_calls[0][0])
        assert "已更新 " in success_text
        assert "1 条受物理极限约束" in success_text
        assert not warning_calls, "批量规则应自动裁剪，不再额外弹出重新插入警告"
    finally:
        panel.deleteLater()


def test_open_transition_length_rules_uses_real_gap_for_direct_transition_without_auto_channel(monkeypatch):
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        panel.start_wl_edit.setText("420.000")
        nodes = _make_direct_gap_transition_nodes()
        panel.calculated_nodes = nodes
        panel._update_table_from_nodes_full(nodes)
        _flush_events()

        rule_rows = [
            {
                "rule_key": "明渠-圆形|隧洞-圆拱直墙型|进口",
                "upstream_structure_type": "明渠-圆形",
                "downstream_structure_type": "隧洞-圆拱直墙型",
                "transition_type": "进口",
                "count": 1,
                "hit_count": 1,
                "hit_scope": "current",
                "rule_mode": "fixed",
                "step_size_m": 1.0,
                "fixed_length_m": 6.0,
            },
        ]

        class _AcceptedDialog:
            def __init__(self, rows, parent=None):
                self.rows = rows

            def exec(self):
                return module.QDialog.DialogCode.Accepted

            def get_rules(self):
                return {
                    row["rule_key"]: {
                        "rule_key": row["rule_key"],
                        "upstream_structure_type": row["upstream_structure_type"],
                        "downstream_structure_type": row["downstream_structure_type"],
                        "transition_type": row["transition_type"],
                        "rule_mode": row["rule_mode"],
                        "step_size_m": row["step_size_m"],
                        "fixed_length_m": row["fixed_length_m"],
                    }
                    for row in self.rows
                }

        monkeypatch.setattr(module, "TransitionLengthRuleDialog", _AcceptedDialog)
        monkeypatch.setattr(panel, "_collect_transition_length_rule_rows", lambda *_args, **_kwargs: rule_rows)

        success_calls = []
        warning_calls = []
        monkeypatch.setattr(module.InfoBar, "success", lambda *args, **kwargs: success_calls.append((args, kwargs)))
        monkeypatch.setattr(module.InfoBar, "warning", lambda *args, **kwargs: warning_calls.append((args, kwargs)))

        ctx = panel._get_transition_context_for_row(1, nodes)
        assert round(panel._get_transition_length_override_upper_bound(ctx), 3) == 15.571

        panel._open_transition_length_rules()

        details = panel.calculated_nodes[1].transition_length_calc_details
        assert panel.node_table.item(1, 32).text() == "6.000"
        assert details["requested_length"] == 6.0
        assert round(details["physical_limit"], 3) == 15.571
        assert details["actual_length"] == 6.0
        assert details["distance_clamped"] is False
        success_text = " ".join(str(part) for part in success_calls[0][0])
        assert "已更新 1 条" in success_text
        assert "受物理极限约束" not in success_text
        assert warning_calls == []
    finally:
        panel.deleteLater()


def test_transition_length_process_section_displays_requested_and_physical_limit():
    formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")

    section = formula_module._build_transition_length_process_section(
        {
            "transition_type": "进口",
            "struct_name": "矩形暗涵",
            "B1": 2.2,
            "B2": 1.8,
            "coefficient": 2.5,
            "L_basic": 1.0,
            "channel_depth": 1.5,
            "L_result": 7.0,
            "formula_length": 5.4,
            "requested_length": 10.0,
            "physical_limit": 7.0,
            "actual_length": 7.0,
            "uses_existing_length": False,
            "constraint_applied": "倒虹吸",
            "constraint_desc": "5倍渠道设计水深",
            "depth_multiplier": 5,
            "L_depth": 7.5,
            "prev_name": "上游明渠",
            "next_name": "下游建筑物",
            "warning": "目标长度超过当前物理上限，已按最大可用长度采用。",
        },
        "2. 渐变段长度计算过程",
    )

    assert "公式/规范计算值" in section["values"]
    assert "规则目标长度" in section["values"]
    assert "物理上限" in section["values"]
    assert "最终采用长度" in section["values"]


def test_show_transition_length_dialog_displays_rule_target_and_physical_limit(monkeypatch):
    formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")
    captured = {}

    def _fake_formula_dialog(parent, title, sections):
        captured["title"] = title
        captured["sections"] = sections

    monkeypatch.setattr(formula_module, "FormulaDialog", _fake_formula_dialog)

    formula_module.show_transition_length_dialog(
        None,
        "测试渐变段",
        {
            "transition_type": "出口",
            "struct_name": "矩形暗涵",
            "B1": 3.0,
            "B2": 1.4,
            "coefficient": 3.5,
            "L_basic": 5.6,
            "channel_depth": 1.2,
            "L_result": 6.0,
            "formula_length": 5.4,
            "requested_length": 10.0,
            "physical_limit": 6.0,
            "actual_length": 6.0,
            "constraint_applied": "倒虹吸",
            "constraint_desc": "5倍渠道设计水深",
            "depth_multiplier": 5,
            "L_depth": 6.0,
            "prev_name": "上游建筑物",
            "next_name": "下游明渠",
            "source": "rule:step_up",
            "warning": "目标长度超过当前物理上限，已按最大可用长度采用。",
        },
    )

    assert captured["title"] == "测试渐变段 - 渐变段长度计算详情"
    summary_section = next(sec for sec in captured["sections"] if sec["title"] == "5. 长度规则与采用结果")
    assert "长度来源：组合规则-向上修约" in summary_section["values"]
    assert "规则目标长度" in summary_section["values"]
    assert "物理上限" in summary_section["values"]
    assert "最终采用长度" in summary_section["values"]
    assert "向上修整先计算目标整数长度，再按当前物理可用长度裁剪" in summary_section["content"]
    final_section = next(sec for sec in captured["sections"] if sec["title"] == "6. 最终采用长度")
    assert "$L = 6.000 \\ m$" == final_section["formula"]


def test_rule_rows_require_transition_rows_even_if_table_text_changes():
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        stale_nodes = _make_rule_pair_nodes()
        stale_nodes[0].structure_type = StructureType.from_string("明渠-梯形")
        panel.calculated_nodes = stale_nodes
        panel._update_table_from_nodes_full(stale_nodes)
        _flush_events()

        panel.node_table.item(0, 2).setText("矩形暗涵")
        _flush_events()

        rows = panel._collect_transition_length_rule_rows()

        assert rows == []
    finally:
        panel.deleteLater()


def test_transition_length_override_blocks_values_that_require_topology_rebuild(monkeypatch):
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        panel.start_wl_edit.setText("420.000")
        nodes = _make_transition_edit_nodes()
        panel.calculated_nodes = nodes
        panel._update_table_from_nodes_full(nodes)
        _flush_events()

        warning_calls = []
        monkeypatch.setattr(
            module.InfoBar,
            "warning",
            lambda *args, **kwargs: warning_calls.append((args, kwargs)),
        )

        result = panel._apply_transition_length_override(1, manual_length=8.1)

        assert result is False
        assert panel.node_table.item(1, 32).text() == "5.000"
        assert warning_calls, "超出物理可用里程时应提示用户重新插入渐变段"
        warning_text = " ".join(str(part) for part in warning_calls[0][0])
        assert "重新插入渐变段" in warning_text
    finally:
        panel.deleteLater()


def test_transition_length_override_allows_values_within_current_local_slack():
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        panel.start_wl_edit.setText("420.000")
        nodes = _make_transition_edit_nodes()
        panel.calculated_nodes = nodes
        panel._update_table_from_nodes_full(nodes)
        _flush_events()

        result = panel._apply_transition_length_override(1, manual_length=7.5)

        assert result is True
        assert panel.node_table.item(1, 32).text() == "7.500"
        assert panel.calculated_nodes[1].transition_length_override_m == 7.5
    finally:
        panel.deleteLater()


def test_show_transition_length_details_lazy_repairs_missing_details(monkeypatch):
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        panel.calculated_nodes = _make_nodes()
        panel._update_table_from_nodes_full(panel.calculated_nodes)
        panel.calculated_nodes[1].transition_length_calc_details = {}
        _flush_events()

        dialog_calls = []
        info_calls = []
        formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")

        monkeypatch.setattr(
            formula_module,
            "show_transition_length_dialog",
            lambda parent, node_name, details: dialog_calls.append((parent, node_name, details)),
        )
        monkeypatch.setattr(module, "fluent_info", lambda *args, **kwargs: info_calls.append((args, kwargs)))

        panel._show_transition_length_details(1, panel.calculated_nodes[1])

        assert dialog_calls, "双击时应先尝试懒补建详情，而不是直接提示失败"
        assert not info_calls, "懒补建成功后不应再显示“没有计算数据”提示"
        assert dialog_calls[0][2].get("actual_length") == 9.0
    finally:
        panel.deleteLater()


def test_show_transition_length_details_respects_explicit_zero_length(monkeypatch):
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        panel.calculated_nodes = _make_nodes()
        panel._update_table_from_nodes_full(panel.calculated_nodes)
        panel.calculated_nodes[1].transition_length = 9.0
        panel.calculated_nodes[1].transition_length_calc_details = {}
        panel.node_table.item(1, 32).setText("0.000")
        _flush_events()

        dialog_calls = []
        info_calls = []
        formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")

        monkeypatch.setattr(
            formula_module,
            "show_transition_length_dialog",
            lambda parent, node_name, details: dialog_calls.append((parent, node_name, details)),
        )
        monkeypatch.setattr(module, "fluent_info", lambda *args, **kwargs: info_calls.append((args, kwargs)))

        panel._show_transition_length_details(1, panel.calculated_nodes[1])

        assert dialog_calls, "表格明确给出 0.000 时，双击应按当前长度补建详情"
        assert not info_calls, "显式零长度可恢复详情，不应提示失败"
        details = dialog_calls[0][2]
        assert details.get("actual_length") == 0.0
        assert details.get("L_result") == 0.0
        assert details.get("uses_existing_length") is True
        assert (details.get("formula_length") or 0.0) > 0.0
    finally:
        panel.deleteLater()


def test_project_reload_repairs_single_override_warning_and_source():
    module = _load_panel_module()
    panel = _build_panel(module)
    try:
        nodes = _make_nodes()
        panel.calculated_nodes = nodes
        panel._update_table_from_nodes_full(nodes)
        _flush_events()

        state = panel.to_project_dict()
        state["calculated_nodes"][1]["transition_length"] = 5.0
        state["calculated_nodes"][1]["transition_length_override_m"] = 5.0
        state["calculated_nodes"][1]["transition_length_source"] = "override"
        state["calculated_nodes"][1]["transition_length_warning"] = ""
        state["calculated_nodes"][1]["transition_length_calc_details"] = {}
        state["node_table_rows"][1][32] = "5.000"
    finally:
        panel.deleteLater()

    restored = _build_panel(module)
    try:
        restored.from_project_dict(state, skip_dirty_signal=True)
        _flush_events()

        repaired = restored.calculated_nodes[1].transition_length_calc_details
        assert repaired, "重开项目后应补建单条覆盖的长度详情"
        assert repaired.get("actual_length") == 5.0
        assert repaired.get("L_result") == 5.0
        assert repaired.get("source") == "override"
        assert (repaired.get("formula_length") or 0.0) > 5.0
        assert "单条覆盖长度小于公式/规范值" in (repaired.get("warning") or "")
        assert restored.calculated_nodes[1].transition_length_override_m == 5.0
        assert restored.node_table.item(1, 32).text() == "5.000"
    finally:
        restored.deleteLater()
