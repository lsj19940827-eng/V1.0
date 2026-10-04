# -*- coding: utf-8 -*-
"""泄水渠渐进输入、旧工程保值和缺资料提示回归测试。"""

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

from PySide6.QtWidgets import QApplication

from app_渠系计算前端.spillway_steep_chute.panel import SpillwaySteepChutePanel


@pytest.fixture
def panel():
    """保留应用生命周期，并在每次测试后清理面板。"""
    app = QApplication.instance() or QApplication([])
    widget = SpillwaySteepChutePanel()
    yield widget
    widget.deleteLater()
    app.processEvents()


def test_first_screen_only_has_basic_hydraulic_inputs(panel):
    """首屏保持基本参数，不要求用户先处理入口、尾水和高级系数。"""
    visible_fields = {key for key, field in panel._input_fields.items() if not field.isHidden()}
    assert visible_fields == {"design_flow", "channel_width", "side_slope", "chute_length", "bed_slope", "roughness"}
    assert all(group.is_collapsed() for group in (panel.inlet_group, panel.tailwater_group, panel.advanced_group))
    params = panel._collect_inputs()
    assert params["inlet_head"] == ""
    assert params["inlet_weir_width"] == ""
    assert params["downstream_tailwater_depth"] == ""
    assert params["n"] == pytest.approx(0.014)
    assert "混凝土" in panel.roughness_hint.text()
    assert "待补尾水" in panel.defaults_hint.text()
    assert panel.notebook.tabText(panel.notebook.currentIndex()) == "结果汇总"


def test_calculate_action_stays_visible_when_advanced_inputs_are_expanded(panel):
    """窄窗口或高缩放下，展开专业参数后计算按钮仍固定可见。"""
    panel.resize(960, 640)
    panel.show()
    panel._combo_fields["ui_mode_label"].setCurrentText("专业模式")
    QApplication.instance().processEvents()
    point = panel.calculate_btn.mapTo(panel, panel.calculate_btn.rect().center())
    assert panel.rect().contains(point)
    assert panel.calculate_btn.isVisible()
    assert panel.calculate_btn.parentWidget() is panel._action_bar


@pytest.mark.parametrize("slope", ["0.02", "1:50", "1：50", "2%", "2％"])
def test_common_slope_formats_have_identical_calculation_and_preserve_raw_input(panel, slope):
    """坡度快捷写法等价，保存工程仍保留用户熟悉的原始写法。"""
    panel._input_fields["bed_slope"].setText(slope)
    assert panel._collect_inputs()["i"] == pytest.approx(0.02)
    state = panel.to_project_dict()
    assert state["cases"][0]["bed_slope"] == slope
    panel.from_project_dict(state)
    assert panel._input_fields["bed_slope"].text() == slope
    assert panel._collect_inputs()["i"] == pytest.approx(0.02)


def test_rectangle_hides_side_slope_without_erasing_trapezoid_value(panel):
    """矩形仅省去不适用的输入，切回梯形仍保留原边坡。"""
    panel._input_fields["side_slope"].setText("2.3")
    panel._combo_fields["section_type"].setCurrentText("矩形")
    assert panel._input_fields["side_slope"].isHidden()
    assert panel._collect_inputs()["m"] == 0.0
    panel._combo_fields["section_type"].setCurrentText("梯形")
    assert panel._input_fields["side_slope"].text() == "2.3"
    assert panel._collect_inputs()["m"] == pytest.approx(2.3)


def test_mode_and_collapse_keep_custom_values_and_result(panel):
    """界面收拢不改算例参数，也不让已算成果无故失效。"""
    panel.from_project_dict({"input_params": {
        "section_type": "rectangular", "design_flow": 8.0,
        "alpha_profile": 1.07, "inlet_weir_width": 2.0, "inlet_head": 1.4,
        "contraction_coefficient": 0.87, "weir_coefficient": 0.41,
        "downstream_tailwater_depth": 1.9,
        "control_depth_mode": "manual", "start_depth": 0.8,
    }})
    original = panel._collect_inputs()
    result = {"success": True, "summary": {"末端水深": 0.6}}
    panel.current_result = result
    panel._combo_fields["ui_mode_label"].setCurrentText("专业模式")
    panel._combo_fields["ui_mode_label"].setCurrentText("新手模式")
    for group in (panel.inlet_group, panel.tailwater_group, panel.advanced_group):
        group.set_collapsed(True)
    collected = panel._collect_inputs()
    for key in ("alpha_profile", "contraction_coefficient", "weir_coefficient", "downstream_tailwater_depth", "start_depth", "control_depth_mode", "section_type"):
        assert collected[key] == original[key]
    assert collected["contraction_coefficient"] == pytest.approx(0.87)
    assert collected["start_depth"] == pytest.approx(0.8)
    assert panel.current_result is result


def test_legacy_special_control_and_optional_data_are_visible(panel):
    """旧工程的决定性边界条件自动展开，用户可直接核对。"""
    panel.from_project_dict({"input_params": {
        "profile_mode": "LENGTH_BY_TWO_DEPTHS", "control_depth_mode": "inlet_control",
        "inlet_control_depth": 1.5, "end_depth": 1.2,
        "inlet_head": 2.5, "inlet_weir_width": 1.5,
        "downstream_tailwater_depth": 1.0, "inlet_contraction_coefficient": 0.91,
    }})
    assert not any(group.is_collapsed() for group in (panel.inlet_group, panel.tailwater_group, panel.advanced_group))
    assert panel._input_fields["manual_start_depth"].text() == "1.5"
    assert not panel._input_fields["end_depth"].isHidden()
    inputs = panel._collect_inputs()
    assert inputs["profile_mode"] == "LENGTH_BY_TWO_DEPTHS"
    assert inputs["inlet_control_depth"] == pytest.approx(1.5)
    assert inputs["contraction_coefficient"] == pytest.approx(0.91)


def test_new_case_does_not_inherit_optional_values_from_previous_case(panel):
    """缺字段的旧工况使用其默认值，不继承另一个工况的尾水和系数。"""
    panel._cases = [
        {**panel._default_case(), "downstream_tailwater_depth": 2.4, "alpha_profile": 1.03},
        {"design_flow": 12.0, "channel_width": 3.0},
    ]
    panel._load_case(0)
    panel._load_case(1)
    params = panel._collect_inputs()
    assert params["downstream_tailwater_depth"] == ""
    assert params["alpha_profile"] == pytest.approx(1.1)


def test_incomplete_inlet_data_asks_for_missing_partner(panel):
    """入口资料不完整时给出明确补齐提示，不偷偷使用演示入口宽度。"""
    panel._input_fields["inlet_head"].setText("1.8")
    with pytest.raises(ValueError, match="同时填写入口宽度和堰上总水头"):
        panel._collect_inputs()


def test_selected_control_requires_depth_instead_of_falling_back_to_critical(panel):
    """用户已选择人工边界时，缺深度不能悄悄按临界深度计算。"""
    panel._combo_fields["control_depth_mode_label"].setCurrentText("人工指定")
    with pytest.raises(ValueError, match="控制水深"):
        panel._collect_inputs()


def test_teaching_example_replaces_prior_optional_data_and_uses_its_start_depth(panel):
    """载入教学算例应使用该算例起始水深，不挟带之前工程的入口和尾水。"""
    panel._input_fields["downstream_tailwater_depth"].setText("5.0")
    panel.load_teaching_example()
    params = panel._collect_inputs()
    assert params["start_depth"] == pytest.approx(1.788)
    assert params["control_depth_mode"] == "manual"
    assert params["downstream_tailwater_depth"] == ""
    assert params["inlet_head"] == ""


def test_missing_tailwater_result_is_pending_and_zero_pool_depth_remains_zero(panel):
    """缺资料显示待补，合法的零池深不应与缺失混淆。"""
    params = panel._collect_inputs()
    result = {
        "success": True,
        "summary": {"建议消力池深度": None},
        "hydraulic_jump": {
            "status": "missing_tailwater", "design_available": False,
            "conjugate_depth_m": 2.1, "recommended_pool_depth_m": None,
            "recommended_pool_length_m": 0.0, "tailwater_judgement": "待补尾水",
            "message": "理论共轭水深已算，待补尾水。",
        },
    }
    panel._all_results = [(0, params, result)]
    rendered = panel._case_result_html(0, params, result)
    assert "消能设计待补尾水" in rendered
    assert "理论共轭水深已算，待补尾水。" in rendered
    assert "未计算" in rendered
    assert "None" not in rendered
    _, layout = panel._comparison_rows()
    assert layout[0]["pool_depth"] == "未计算"
    assert layout[0]["pool_length"] == 0.0
    assert layout[0]["status"] == "待补尾水"


def test_trapezoid_jump_card_uses_momentum_relation(panel, monkeypatch):
    """梯形理论水跃说明使用动量关系，不能展示矩形共轭公式。"""
    monkeypatch.setattr(panel, "_latex_html", lambda formula: formula)
    html = panel._jump_html({
        "hydraulic": {"section_type": "trapezoidal"},
        "hydraulic_jump": {"message": "梯形只给理论共轭深"},
    })
    assert "M(h_1)=M(h_2)" in html
    assert "mh^3" in html
    assert "1+8Fr" not in html
