# -*- coding: utf-8 -*-
"""泄水渠与陡坡输入校验、非陡坡风险和规范提示单元测试。"""

import importlib


def _core_module():
    """载入泄水渠与陡坡计算内核。"""
    return importlib.import_module("calc_渠系计算算法内核.泄水渠与陡坡设计")


def test_invalid_input_returns_clear_validation_errors():
    """无效输入应返回失败状态和明确错误，不抛出底层异常。"""
    result = _core_module().quick_calculate_spillway_steep_chute(
        {
            "section_type": "trapezoidal",
            "Q": -1.0,
            "b": 0.0,
            "m": 1.5,
            "i": 0.02,
            "n": 0.014,
            "L": 80.0,
        }
    )

    assert result["success"] is False
    assert result["profile"]["available"] is False
    assert any("流量" in message for message in result["errors"])
    assert any("底宽" in message for message in result["errors"])


def test_non_steep_slope_does_not_silently_calculate_profile():
    """非陡坡工况不得静默计算水面线，应返回风险提示和不可用状态。"""
    result = _core_module().quick_calculate_spillway_steep_chute(
        {
            "section_type": "rectangular",
            "Q": 10.0,
            "b": 2.0,
            "m": 0.0,
            "i": 0.0001,
            "n": 0.014,
            "L": 30.0,
            "profile_mode": "END_DEPTH_BY_LENGTH",
        }
    )

    assert result["success"] is True
    assert result["hydraulic"]["slope_type"] == "mild"
    assert result["profile"]["available"] is False
    assert result["profile"]["status"] == "unavailable_non_steep_slope"
    assert any("非陡坡" in warning for warning in result["warnings"])


def test_weir_capacity_and_layout_checks_report_risks():
    """入口过流能力不足和布置风险应进入结果提示，供前端直接展示。"""
    result = _core_module().quick_calculate_spillway_steep_chute(
        {
            "section_type": "trapezoidal",
            "Q": 20.0,
            "b": 1.0,
            "m": 1.5,
            "i": 0.02,
            "n": 0.014,
            "L": 80.0,
            "profile_mode": "END_DEPTH_BY_LENGTH",
            "inlet_weir_width": 0.8,
            "inlet_head": 1.0,
            "weir_coefficient": 0.42,
            "upstream_straight_length": 3.0,
            "downstream_straight_length": 3.0,
        }
    )

    assert result["inlet_weir"]["passed"] is False
    assert result["inlet_weir"]["capacity_ratio"] < 1.0
    assert any(not item["passed"] for item in result["code_checks"])
    assert any("直线段" in item["message"] for item in result["code_checks"])
