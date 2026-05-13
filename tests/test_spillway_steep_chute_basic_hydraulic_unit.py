# -*- coding: utf-8 -*-
"""泄水渠与陡坡基础水力计算单元测试，覆盖前端快速调用所需字段。"""

import importlib
import math


def _core_module():
    """载入泄水渠与陡坡计算内核。"""
    return importlib.import_module("calc_渠系计算算法内核.泄水渠与陡坡设计")


def test_quick_calculate_returns_core_hydraulic_fields_for_rectangular_section():
    """矩形陡槽应返回正常水深、临界水深、临界底坡和常用能量指标。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(
        {
            "section_type": "rectangular",
            "Q": 10.0,
            "b": 2.0,
            "m": 0.0,
            "i": 0.01,
            "n": 0.014,
            "L": 30.0,
            "profile_mode": "END_DEPTH_BY_LENGTH",
        }
    )

    assert result["success"] is True
    assert result["hydraulic"]["section_type"] == "rectangular"
    assert result["hydraulic"]["normal_depth_m"] < result["hydraulic"]["critical_depth_m"]
    assert result["hydraulic"]["slope_type"] == "steep"
    assert result["hydraulic"]["critical_slope"] < 0.01
    expected_hk = ((10.0 / 2.0) ** 2 / 9.81) ** (1.0 / 3.0)
    assert result["hydraulic"]["critical_depth_m"] == pytest_approx(expected_hk, rel=1e-3)
    assert result["hydraulic"]["froude_at_start"] == pytest_approx(1.0, abs=0.01)
    assert result["hydraulic"]["specific_energy_start_m"] > result["hydraulic"]["critical_depth_m"]
    assert result["hydraulic"]["hydraulic_slope_at_normal"] == pytest_approx(0.01, rel=0.01)
    assert result["profile"]["available"] is True
    assert result["formula_cards"]
    assert any("\\frac" in card["latex"] for card in result["formula_cards"])


def test_quick_calculate_returns_trapezoid_section_metrics_and_weir_capacity():
    """梯形陡槽应返回断面水力要素，并能校核入口宽顶堰过流能力。"""
    core = _core_module()

    result = core.quick_calculate_spillway_steep_chute(
        {
            "section_type": "trapezoidal",
            "Q": 8.0,
            "b": 1.5,
            "m": 1.0,
            "i": 0.015,
            "n": 0.014,
            "L": 20.0,
            "profile_mode": "END_DEPTH_BY_LENGTH",
            "inlet_weir_width": 2.5,
            "inlet_head": 2.0,
            "weir_coefficient": 0.42,
            "contraction_coefficient": 1.0,
        }
    )

    assert result["success"] is True
    assert result["hydraulic"]["normal_depth_m"] > 0
    assert result["hydraulic"]["critical_depth_m"] > 0
    assert result["hydraulic"]["water_top_width_at_critical_m"] > 1.5
    assert result["inlet_weir"]["capacity_m3s"] > 8.0
    assert result["inlet_weir"]["capacity_ratio"] > 1.0
    assert result["inlet_weir"]["passed"] is True
    assert "泄(退)水" in result["discharge_hint"]["title"]


def pytest_approx(value, **kwargs):
    """延迟导入 pytest.approx，保持测试意图清晰。"""
    import pytest

    return pytest.approx(value, **kwargs)
