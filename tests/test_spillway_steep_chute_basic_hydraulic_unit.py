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


def test_water_profile_energy_alpha_participates_in_specific_energy_and_profile():
    """水面线动能修正系数应真实参与断面比能和逐段水面线计算。"""
    core = _core_module()
    base = {
        "section_type": "rectangular",
        "Q": 10.0,
        "b": 2.0,
        "m": 0.0,
        "i": 0.01,
        "n": 0.014,
        "L": 30.0,
        "profile_mode": "END_DEPTH_BY_LENGTH",
    }

    default_result = core.quick_calculate_spillway_steep_chute(base)
    legacy_result = core.quick_calculate_spillway_steep_chute({**base, "alpha_profile": 1.0})
    start = default_result["hydraulic"]["start"]
    expected_default_energy = start["depth_m"] + 1.1 * start["velocity_ms"] ** 2 / (2.0 * 9.81)

    assert default_result["input_params"]["alpha_profile"] == pytest_approx(1.1)
    assert default_result["hydraulic"]["water_profile_energy_alpha"] == pytest_approx(1.1)
    assert default_result["hydraulic"]["specific_energy_start_m"] == pytest_approx(expected_default_energy, rel=1e-6)
    assert default_result["profile"]["points"][0]["specific_energy_m"] == pytest_approx(expected_default_energy, rel=1e-6)
    assert legacy_result["hydraulic"]["specific_energy_start_m"] < default_result["hydraulic"]["specific_energy_start_m"]
    assert legacy_result["profile"]["end_depth_m"] != pytest_approx(default_result["profile"]["end_depth_m"])


def test_legacy_alpha_profile_migration_adds_risk_tip():
    """旧项目缺少水面线动能修正系数时，应按 1.1 迁移并提示结果可能变化。"""
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
            "legacy_alpha_profile_migrated": True,
        }
    )

    assert result["input_params"]["alpha_profile"] == pytest_approx(1.1)
    assert any("启用水面线动能修正系数 alpha_e=1.1" in risk for risk in result["risks"])


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


def test_inlet_weir_coefficient_uses_gb50288_connection_type_formulas():
    """入口流量系数应按 GB 50288-2018 附录 N 的连接形式自动计算。"""
    core = _core_module()
    base = {
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
        "contraction_coefficient": 1.0,
    }

    cases = [
        ("扭曲面连接", 0.474 - 0.018 * 2.5 / 2.0, "0.474-0.018b_c/H_0"),
        ("八字墙连接", 0.470 - 0.017 * 2.5 / 2.0, "0.470-0.017b_c/H_0"),
        ("横隔墙连接", 0.402 - 0.008 * 2.5 / 2.0, "0.402-0.008b_c/H_0"),
    ]

    for connection, expected_mu, formula in cases:
        result = core.quick_calculate_spillway_steep_chute(
            {**base, "inlet_connection_type": connection}
        )
        inlet = result["inlet_weir"]

        assert inlet["coefficient"] == pytest_approx(expected_mu, rel=1e-9)
        assert inlet["coefficient_formula"] == formula
        assert inlet["coefficient_source"] == "GB 50288-2018 附录 N"
        assert inlet["connection_type"] == connection
        assert inlet["capacity_m3s"] == pytest_approx(
            expected_mu * 2.5 * math.sqrt(2.0 * 9.81) * 2.0**1.5,
            rel=1e-6,
        )


def test_inlet_weir_manual_coefficient_overrides_connection_formula():
    """专业手动输入流量系数时，应优先使用手动值并说明来源。"""
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
            "inlet_connection_type": "手动输入流量系数",
            "weir_coefficient": 0.51,
            "contraction_coefficient": 1.0,
        }
    )
    inlet = result["inlet_weir"]

    assert inlet["coefficient"] == pytest_approx(0.51)
    assert inlet["coefficient_source"] == "用户手动输入"
    assert inlet["coefficient_formula"] == "手动输入"
    assert inlet["capacity_m3s"] == pytest_approx(
        0.51 * 2.5 * math.sqrt(2.0 * 9.81) * 2.0**1.5,
        rel=1e-6,
    )


def test_inlet_weir_missing_coefficient_does_not_fallback_to_hidden_042():
    """缺少连接形式和手动系数时，不应继续用隐藏 0.42 强行校核。"""
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
        }
    )
    inlet = result["inlet_weir"]

    assert inlet["passed"] is None
    assert inlet["capacity_m3s"] is None
    assert inlet["capacity_ratio"] is None
    assert inlet["coefficient"] is None
    assert "入口流量系数缺失" in inlet["message"]


def pytest_approx(value, **kwargs):
    """延迟导入 pytest.approx，保持测试意图清晰。"""
    import pytest

    return pytest.approx(value, **kwargs)
