# -*- coding: utf-8 -*-
"""表3与水位详情口径统一回归测试。"""

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _flush_events(rounds: int = 4):
    app = QApplication.instance() or QApplication([])
    for _ in range(max(1, rounds)):
        app.processEvents()


def _load_formula_dialog_module():
    module_path = next(Path(".").glob("**/water_profile/formula_dialog.py")).resolve()
    spec = importlib.util.spec_from_file_location("wp_loss_alignment_formula_dialog_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_panel_module():
    module_path = next(Path(".").glob("**/water_profile/panel.py")).resolve()
    spec = importlib.util.spec_from_file_location("wp_loss_alignment_panel_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture_formula_dialog(monkeypatch, module):
    captured = {}

    class _FakeFormulaDialog:
        def __init__(self, parent, title, sections):
            captured["parent"] = parent
            captured["title"] = title
            captured["sections"] = sections

    monkeypatch.setattr(module, "FormulaDialog", _FakeFormulaDialog)
    return captured


def _build_panel(panel_module, start_level=565.1160):
    panel = panel_module.WaterProfilePanel.__new__(panel_module.WaterProfilePanel)
    panel._build_settings = lambda: SimpleNamespace(start_water_level=start_level)
    return panel


def _build_real_panel(panel_module):
    app = QApplication.instance() or QApplication([])
    _ = app
    for attr in ("_open_transition_length_rules", "_show_node_table_context_menu"):
        if not hasattr(panel_module.WaterProfilePanel, attr):
            setattr(panel_module.WaterProfilePanel, attr, lambda self, *args, **kwargs: None)
    panel = panel_module.WaterProfilePanel()
    panel.resize(1400, 900)
    return panel


def _make_node(**overrides):
    defaults = {
        "flow_section": "1",
        "name": "",
        "is_transition": False,
        "is_auto_inserted_channel": False,
        "from_table1_source": False,
        "structure_type": None,
        "section_params": {},
        "roughness": 0.0,
        "slope_i": 0.0,
        "flow": 0.0,
        "water_depth": 0.0,
        "velocity": 0.0,
        "station_MC": 0.0,
        "station_BC": 0.0,
        "station_EC": 0.0,
        "station_ip": 0.0,
        "turn_angle": 0.0,
        "tangent_length": 0.0,
        "arc_length": 0.0,
        "curve_length": 0.0,
        "straight_distance": 0.0,
        "check_pre_curve": 0.0,
        "check_post_curve": 0.0,
        "check_total_length": 0.0,
        "transition_length": 0.0,
        "transition_type": "",
        "transition_form": "",
        "is_diversion_gate": False,
        "head_loss_transition": 0.0,
        "head_loss_total": 0.0,
        "head_loss_bend": 0.0,
        "head_loss_friction": 0.0,
        "head_loss_local": 0.0,
        "head_loss_reserve": 0.0,
        "head_loss_gate": 0.0,
        "head_loss_siphon": 0.0,
        "head_loss_cumulative": 0.0,
        "water_level": 0.0,
        "bottom_elevation": 0.0,
        "top_elevation": 0.0,
        "structure_height": 0.0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _build_text_blob(sections):
    return "\n".join(
        "\n".join(str(section.get(key, "")) for key in ("title", "values", "content", "formula"))
        for section in sections
    )


def test_total_loss_details_exclude_preceding_transition_row(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _ = app

    panel_module = _load_panel_module()
    formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")
    captured = {}

    monkeypatch.setattr(
        formula_module,
        "show_total_loss_dialog",
        lambda parent, node_name, details: captured.update(
            parent=parent, node_name=node_name, details=details
        ),
    )

    panel = _build_panel(panel_module)
    nodes = [
        _make_node(name="上游普通行", head_loss_total=0.0055),
        _make_node(name="渐变段", is_transition=True, head_loss_transition=0.0021),
        _make_node(name="燕儿包", head_loss_total=0.0081, head_loss_friction=0.0081),
    ]

    panel_module.WaterProfilePanel._show_total_calc_details(panel, 2, nodes[2], nodes)

    assert captured["node_name"] == "燕儿包"
    assert captured["details"]["head_loss_total"] == 0.0081
    assert captured["details"]["head_loss_transition"] == 0.0


def test_transition_row_total_loss_details_reuse_transition_dialog(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _ = app

    panel_module = _load_panel_module()
    formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")
    dialog_calls = []
    info_calls = []

    monkeypatch.setattr(
        formula_module,
        "show_transition_loss_dialog",
        lambda parent, node_name, details: dialog_calls.append((parent, node_name, details)),
    )
    monkeypatch.setattr(panel_module, "fluent_info", lambda *args, **kwargs: info_calls.append((args, kwargs)))

    panel = _build_panel(panel_module)
    node = _make_node(
        name="渐变段",
        is_transition=True,
        head_loss_transition=0.0021,
        transition_calc_details={"total": 0.0021},
    )

    panel_module.WaterProfilePanel._show_total_calc_details(panel, 1, node, [node])

    assert dialog_calls
    assert not info_calls
    assert dialog_calls[0][1] == "渐变段"
    assert dialog_calls[0][2]["total"] == 0.0021


def test_transition_row_total_loss_column_matches_transition_loss_after_refresh():
    from 推求水面线.models.data_models import ChannelNode
    from 推求水面线.models.enums import StructureType

    panel_module = _load_panel_module()
    panel = _build_real_panel(panel_module)
    try:
        upstream = ChannelNode()
        upstream.flow_section = "1"
        upstream.name = "上一步普通行"
        upstream.structure_type = StructureType.from_string("明渠-梯形")
        upstream.head_loss_total = 0.4738
        upstream.head_loss_cumulative = 0.4738
        upstream.water_level = 564.6420

        transition = ChannelNode()
        transition.flow_section = "1"
        transition.name = "-"
        transition.structure_type = StructureType.TRANSITION
        transition.is_transition = True
        transition.head_loss_transition = 0.0021
        transition.head_loss_cumulative = 0.4759

        downstream = ChannelNode()
        downstream.flow_section = "1"
        downstream.name = "燕儿包"
        downstream.structure_type = StructureType.from_string("隧洞-圆拱直墙型")
        downstream.head_loss_total = 0.0081
        downstream.head_loss_friction = 0.0081
        downstream.head_loss_cumulative = 0.4840
        downstream.water_level = 564.6320

        nodes = [upstream, transition, downstream]

        panel.calculated_nodes = nodes
        panel._update_table_from_nodes_full(nodes)

        assert panel.node_table.item(1, 33).text() == "0.0021"
        assert panel.node_table.item(1, 39).text() == "0.0021"
    finally:
        panel.deleteLater()


def test_transition_row_total_loss_column_follows_zero_display_rule_after_refresh():
    from 推求水面线.models.data_models import ChannelNode
    from 推求水面线.models.enums import StructureType

    panel_module = _load_panel_module()
    panel = _build_real_panel(panel_module)
    try:
        upstream = ChannelNode()
        upstream.flow_section = "1"
        upstream.name = "上一步普通行"
        upstream.structure_type = StructureType.from_string("明渠-梯形")
        upstream.head_loss_total = 0.4738
        upstream.head_loss_cumulative = 0.4738
        upstream.water_level = 564.6420

        transition = ChannelNode()
        transition.flow_section = "1"
        transition.name = "-"
        transition.structure_type = StructureType.TRANSITION
        transition.is_transition = True
        transition.transition_skip_loss = True
        transition.head_loss_transition = 0.0
        transition.head_loss_cumulative = 0.4738

        downstream = ChannelNode()
        downstream.flow_section = "1"
        downstream.name = "燕儿包"
        downstream.structure_type = StructureType.from_string("隧洞-圆拱直墙型")
        downstream.head_loss_total = 0.0081
        downstream.head_loss_friction = 0.0081
        downstream.head_loss_cumulative = 0.4819
        downstream.water_level = 564.6320

        nodes = [upstream, transition, downstream]

        panel.calculated_nodes = nodes
        panel._update_table_from_nodes_full(nodes)

        assert panel.node_table.item(1, 33).text() == "-"
        assert panel.node_table.item(1, 39).text() == "-"
        assert panel.node_table.item(1, 40).text() == "0.4738"
    finally:
        panel.deleteLater()


def test_transition_row_total_loss_column_survives_project_reload():
    from 推求水面线.models.data_models import ChannelNode
    from 推求水面线.models.enums import StructureType

    panel_module = _load_panel_module()
    panel = _build_real_panel(panel_module)
    try:
        upstream = ChannelNode()
        upstream.flow_section = "1"
        upstream.name = "上一步普通行"
        upstream.structure_type = StructureType.from_string("明渠-梯形")
        upstream.head_loss_total = 0.4738
        upstream.head_loss_cumulative = 0.4738
        upstream.water_level = 564.6420

        transition = ChannelNode()
        transition.flow_section = "1"
        transition.name = "-"
        transition.structure_type = StructureType.TRANSITION
        transition.is_transition = True
        transition.head_loss_transition = 0.0021
        transition.head_loss_cumulative = 0.4759

        downstream = ChannelNode()
        downstream.flow_section = "1"
        downstream.name = "燕儿包"
        downstream.structure_type = StructureType.from_string("隧洞-圆拱直墙型")
        downstream.head_loss_total = 0.0081
        downstream.head_loss_friction = 0.0081
        downstream.head_loss_cumulative = 0.4840
        downstream.water_level = 564.6320

        nodes = [upstream, transition, downstream]

        panel.calculated_nodes = nodes
        panel._update_table_from_nodes_full(nodes)
        _flush_events()
        state = panel.to_project_dict()
    finally:
        panel.deleteLater()

    restored = _build_real_panel(panel_module)
    try:
        restored.from_project_dict(state, skip_dirty_signal=True)
        _flush_events()

        assert restored.node_table.item(1, 33).text() == "0.0021"
        assert restored.node_table.item(1, 39).text() == "0.0021"
        assert restored.node_table.item(1, 40).text() == "0.4759"
    finally:
        restored.deleteLater()


def test_water_level_details_distinguish_row_loss_transition_and_step_drop(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _ = app

    panel_module = _load_panel_module()
    formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")
    captured = {}

    monkeypatch.setattr(
        formula_module,
        "show_water_level_dialog",
        lambda parent, node_name, details: captured.update(
            parent=parent, node_name=node_name, details=details
        ),
    )

    panel = _build_panel(panel_module)
    nodes = [
        _make_node(name="上一步普通行", water_level=564.6420, head_loss_cumulative=0.4738, head_loss_total=0.4740),
        _make_node(name="渐变段", is_transition=True, head_loss_transition=0.0021, head_loss_cumulative=0.4759),
        _make_node(
            name="燕儿包",
            water_level=564.6320,
            head_loss_total=0.0081,
            head_loss_friction=0.0081,
            head_loss_cumulative=0.4840,
        ),
    ]

    panel_module.WaterProfilePanel._show_water_level_details(panel, 2, nodes[2], nodes)

    details = captured["details"]
    assert captured["node_name"] == "燕儿包"
    assert details["prev_level"] == 564.6420
    assert details["total_loss"] == 0.0081
    assert details["transition_step_loss"] == 0.0021
    assert details["step_drop"] == 0.0102
    assert details["cumulative"] == 0.4840
    assert details["water_level"] == 564.6320
    assert details["prev_level_exact"] == 564.642000
    assert details["total_loss_exact"] == 0.008100
    assert details["transition_step_loss_exact"] == 0.002100
    assert details["step_drop_exact"] == 0.010200
    assert details["cumulative_exact"] == 0.484200
    assert details["water_level_exact"] == 564.631800


def test_total_loss_dialog_describes_regular_row_loss_only(monkeypatch):
    module = _load_formula_dialog_module()
    captured = _capture_formula_dialog(monkeypatch, module)

    module.show_total_loss_dialog(
        None,
        "燕儿包",
        {
            "head_loss_bend": 0.0,
            "head_loss_transition": 0.0,
            "head_loss_friction": 0.0081,
            "head_loss_local": 0.0,
            "head_loss_reserve": 0.0,
            "head_loss_gate": 0.0,
            "head_loss_siphon": 0.0,
            "head_loss_total": 0.0081,
        },
    )

    text_blob = _build_text_blob(captured["sections"])

    assert captured["title"] == "燕儿包 - 总水头损失计算详情"
    assert "普通行自身损失" in text_blob
    assert "不含前方单独渐变段行" in text_blob
    assert "0.0081" in text_blob
    assert "h_{tr}" not in text_blob


def test_total_loss_details_for_xxpipe_unnamed_pressure_pipe_do_not_repeat_pressure_pipe_term(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _ = app

    panel_module = _load_panel_module()
    formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")
    captured = {}

    monkeypatch.setattr(
        formula_module,
        "show_total_loss_dialog",
        lambda parent, node_name, details: captured.update(
            parent=parent, node_name=node_name, details=details
        ),
    )

    panel = _build_panel(panel_module)
    panel.channel_level_combo = SimpleNamespace(currentText=lambda: "支管")
    node = _make_node(
        name="",
        structure_type=SimpleNamespace(value="有压管道"),
        head_loss_bend=0.0100,
        head_loss_friction=0.0215,
        head_loss_total=0.0315,
    )

    panel_module.WaterProfilePanel._show_total_calc_details(panel, 0, node, [node])

    assert captured["details"]["head_loss_siphon"] == 0.0
    assert captured["details"]["pressure_pipe_display_loss"] == 0.0315
    assert captured["details"]["pressure_pipe_display_is_row_sum"] is True


def test_total_loss_dialog_marks_row_level_display_without_duplicate_siphon(monkeypatch):
    module = _load_formula_dialog_module()
    captured = _capture_formula_dialog(monkeypatch, module)

    module.show_total_loss_dialog(
        None,
        "行5",
        {
            "head_loss_bend": 0.0100,
            "head_loss_transition": 0.0,
            "head_loss_friction": 0.0215,
            "head_loss_local": 0.0,
            "head_loss_reserve": 0.0,
            "head_loss_gate": 0.0,
            "head_loss_siphon": 0.0,
            "pressure_pipe_display_loss": 0.0315,
            "pressure_pipe_display_is_row_sum": True,
            "head_loss_total": 0.0315,
        },
    )

    text_blob = _build_text_blob(captured["sections"])

    assert "空名称普通有压管道行" in text_blob
    assert "本行承压段显示值" in text_blob
    assert "不再作为单独一项重复叠加" in text_blob
    assert "倒虹吸/有压管道水头损失  $h_{sip} = 0.0000" not in text_blob


def test_pressure_pipe_loss_dialog_for_named_group_outlet_points_group_total_to_summary(monkeypatch):
    module = _load_formula_dialog_module()
    captured = _capture_formula_dialog(monkeypatch, module)

    module.show_pressure_pipe_loss_dialog(
        None,
        "洞梁村",
        {
            "head_loss_bend": 0.0,
            "head_loss_friction": 0.8286,
            "head_loss_local": 0.0,
            "head_loss_siphon": 0.8286,
            "pressure_pipe_display_loss": 0.8286,
            "pressure_pipe_display_is_row_sum": False,
            "pressure_pipe_display_mode": "named_group_outlet",
            "pressure_pipe_named_group_total": 10.4901,
        },
    )

    text_blob = _build_text_blob(captured["sections"])

    assert "表3只显示本行损失" in text_blob
    assert "整组总损失请到“有压管道计算结果汇总”查看" in text_blob
    assert "总损失由外部水力计算回写，通常在出口行显示" not in text_blob


def test_water_level_dialog_shows_both_row_loss_and_step_drop(monkeypatch):
    module = _load_formula_dialog_module()
    captured = _capture_formula_dialog(monkeypatch, module)

    module.show_water_level_dialog(
        None,
        "燕儿包",
        {
            "is_first": False,
            "is_gate": False,
            "prev_level": 564.6420,
            "start_level": 565.1160,
            "cumulative": 0.4840,
            "water_level": 564.6320,
            "total_loss": 0.0081,
            "transition_step_loss": 0.0021,
            "step_drop": 0.0102,
            "prev_level_exact": 564.642000,
            "start_level_exact": 565.116000,
            "cumulative_exact": 0.484200,
            "water_level_exact": 564.631800,
            "total_loss_exact": 0.008100,
            "transition_step_loss_exact": 0.002100,
            "step_drop_exact": 0.010200,
            "hf": 0.0081,
            "hj": 0.0,
            "hw": 0.0,
            "h_reserve": 0.0,
            "h_gate": 0.0,
            "h_siphon": 0.0,
        },
    )

    text_blob = _build_text_blob(captured["sections"])

    assert captured["title"] == "燕儿包 - 水位计算详情"
    assert "本普通行总水头损失" in text_blob
    assert "中间渐变段小计" in text_blob
    assert "本步总落差" in text_blob
    assert "0.0081" in text_blob
    assert "0.0021" in text_blob
    assert "0.0102" in text_blob
    assert "多出的部分来自上一普通节点与本行之间的渐变段" in text_blob
    assert "564.642000 - 0.010200 = 564.631800" in text_blob
    assert "565.116000 - 0.484200 = 564.631800" in text_blob
    assert "表格显示水位" in text_blob
    assert "564.6320" in text_blob


def test_water_level_dialog_marks_row_level_display_without_duplicate_siphon(monkeypatch):
    module = _load_formula_dialog_module()
    captured = _capture_formula_dialog(monkeypatch, module)

    module.show_water_level_dialog(
        None,
        "行5",
        {
            "is_first": False,
            "is_gate": False,
            "prev_level": 564.9000,
            "start_level": 565.1160,
            "cumulative": 0.2240,
            "water_level": 564.8920,
            "total_loss": 0.0315,
            "transition_step_loss": 0.0,
            "step_drop": 0.0315,
            "prev_level_exact": 564.900000,
            "start_level_exact": 565.116000,
            "cumulative_exact": 0.224000,
            "water_level_exact": 564.892000,
            "total_loss_exact": 0.031500,
            "transition_step_loss_exact": 0.000000,
            "step_drop_exact": 0.031500,
            "hf": 0.0215,
            "hj": 0.0,
            "hw": 0.0100,
            "h_reserve": 0.0,
            "h_gate": 0.0,
            "h_siphon": 0.0,
            "pressure_pipe_display_loss": 0.0315,
            "pressure_pipe_display_is_row_sum": True,
        },
    )

    text_blob = _build_text_blob(captured["sections"])

    assert "只用于表3该列显示" in text_blob
    assert "不重复计入总损失" in text_blob
    assert "倒虹吸/有压管道水头损失  $h_{sip} = 0.0000" not in text_blob


def test_water_level_details_without_transition_use_row_total_as_step_drop(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _ = app

    panel_module = _load_panel_module()
    formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")
    captured = {}

    monkeypatch.setattr(
        formula_module,
        "show_water_level_dialog",
        lambda parent, node_name, details: captured.update(
            parent=parent, node_name=node_name, details=details
        ),
    )

    panel = _build_panel(panel_module)
    nodes = [
        _make_node(name="上一步普通行", water_level=564.9000, head_loss_cumulative=0.2160, head_loss_total=0.0060),
        _make_node(
            name="普通行",
            water_level=564.8920,
            head_loss_total=0.0080,
            head_loss_friction=0.0080,
            head_loss_cumulative=0.2240,
        ),
    ]

    panel_module.WaterProfilePanel._show_water_level_details(panel, 1, nodes[1], nodes)

    details = captured["details"]
    assert details["total_loss"] == 0.0080
    assert details["transition_step_loss"] == 0.0
    assert details["step_drop"] == 0.0080


def test_cumulative_loss_details_for_xxpipe_unnamed_pressure_pipe_skip_duplicate_pressure_pipe_part(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _ = app

    panel_module = _load_panel_module()
    formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")
    captured = {}

    monkeypatch.setattr(
        formula_module,
        "show_cumulative_loss_dialog",
        lambda parent, node_name, details: captured.update(
            parent=parent, node_name=node_name, details=details
        ),
    )

    panel = _build_panel(panel_module)
    panel.channel_level_combo = SimpleNamespace(currentText=lambda: "支管")
    nodes = [
        _make_node(
            name="",
            structure_type=SimpleNamespace(value="有压管道"),
            head_loss_bend=0.0100,
            head_loss_friction=0.0215,
            head_loss_total=0.0315,
        ),
    ]

    panel_module.WaterProfilePanel._show_cumulative_loss_details(panel, 0, nodes[0], nodes)

    rows_text = captured["details"]["rows_text"]
    assert "弯道0.0100" in rows_text
    assert "沿程0.0215" in rows_text
    assert "倒虹吸0.0315" not in rows_text


def test_water_level_dialog_first_row_keeps_start_level_explanation(monkeypatch):
    module = _load_formula_dialog_module()
    captured = _capture_formula_dialog(monkeypatch, module)

    module.show_water_level_dialog(
        None,
        "首行",
        {
            "is_first": True,
            "water_level": 565.1160,
            "start_level": 565.1160,
            "cumulative": 0.0,
        },
    )

    text_blob = _build_text_blob(captured["sections"])

    assert "起始水位由基础设置输入" in text_blob
    assert "565.1160" in text_blob
    assert "本步总落差" not in text_blob


def test_water_level_dialog_gate_row_keeps_gate_loss_explanation(monkeypatch):
    module = _load_formula_dialog_module()
    captured = _capture_formula_dialog(monkeypatch, module)

    module.show_water_level_dialog(
        None,
        "闸行",
        {
            "is_first": False,
            "is_gate": True,
            "prev_level": 564.9000,
            "head_loss_gate": 0.0120,
            "start_level": 565.1160,
            "cumulative": 0.2280,
            "water_level": 564.8880,
        },
    )

    text_blob = _build_text_blob(captured["sections"])

    assert "过闸水头损失" in text_blob
    assert "564.9000" in text_blob
    assert "0.0120" in text_blob
    assert "564.8880" in text_blob


def test_transition_row_water_level_details_show_info_instead_of_dialog(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _ = app

    panel_module = _load_panel_module()
    formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")
    dialog_calls = []
    info_calls = []

    monkeypatch.setattr(
        formula_module,
        "show_water_level_dialog",
        lambda *args, **kwargs: dialog_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(panel_module, "fluent_info", lambda *args, **kwargs: info_calls.append((args, kwargs)))

    panel = _build_panel(panel_module)
    nodes = [
        _make_node(name="普通行", water_level=564.9000),
        _make_node(name="渐变段", is_transition=True, head_loss_transition=0.0021),
    ]

    panel_module.WaterProfilePanel._show_water_level_details(panel, 1, nodes[1], nodes)

    assert not dialog_calls
    assert info_calls
    assert "渐变段行不显示水位" in str(info_calls[0][0][2])


def test_cumulative_loss_details_continue_to_match_water_level(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _ = app

    panel_module = _load_panel_module()
    formula_module = importlib.import_module("app_渠系计算前端.water_profile.formula_dialog")
    captured = {}

    monkeypatch.setattr(
        formula_module,
        "show_cumulative_loss_dialog",
        lambda parent, node_name, details: captured.update(
            parent=parent, node_name=node_name, details=details
        ),
    )

    panel = _build_panel(panel_module)
    nodes = [
        _make_node(name="上一步普通行", head_loss_total=0.4738, head_loss_cumulative=0.4738, water_level=564.6420),
        _make_node(name="渐变段", is_transition=True, head_loss_transition=0.0021, head_loss_cumulative=0.4759),
        _make_node(
            name="燕儿包",
            head_loss_total=0.0081,
            head_loss_friction=0.0081,
            head_loss_cumulative=0.4840,
            water_level=564.6320,
        ),
    ]

    panel_module.WaterProfilePanel._show_cumulative_loss_details(panel, 2, nodes[2], nodes)

    details = captured["details"]
    assert captured["node_name"] == "燕儿包"
    assert details["cumulative"] == 0.4840
    assert "第2行(渐变段):  $h_{tr} = 0.0021$ m" in details["rows_text"]
    assert "第3行(普通):  $h_{\\Sigma} = 0.0081$ m" in details["rows_text"]


def test_column_formula_descriptions_match_aligned_semantics():
    module = _load_formula_dialog_module()

    total = module.COLUMN_FORMULAS["总水头损失"]
    cumulative = module.COLUMN_FORMULAS["累计总水头损失"]
    water_level = module.COLUMN_FORMULAS["水位"]

    assert "普通行自身" in total["description"]
    assert "不含单独渐变段行" in total["description"]
    assert "渐变段行" in total["note"]
    assert "h_tr" in total["note"] or "h_{tr}" in total["note"]
    assert "按行序累加" in cumulative["description"] or "按行序累加" in cumulative["note"]
    assert "本步总落差" in water_level["description"]
    assert "可能包含中间渐变段" in water_level["description"] or "可能包含中间渐变段" in water_level["note"]
