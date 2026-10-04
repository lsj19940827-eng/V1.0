# -*- coding: utf-8 -*-
"""用规范独立算例验证消能边界、尺寸适用性和加大流量侧墙控制。"""

import importlib
import math

import pytest


core = importlib.import_module("calc_渠系计算算法内核.泄水渠与陡坡设计")


def base(**extra):
    """矩形等宽陡槽基础工况。"""
    return {"section_type": "rectangular", "Q": 6.0, "b": 3.0,
            "m": 0.0, "n": 0.014, "i": 0.05, "L": 40.0, **extra}


def jump_at_depth(**extra):
    """固定独立跃前断面，避免用另一段求解代码生成预期值。"""
    data = base(**extra)
    params, errors = core._validate_input(data)
    assert not errors
    return core._hydraulic_jump_result(
        data, params, {"critical_depth_m": 0.77, "normal_depth_m": 0.3},
        {"available": True, "points": [{"depth_m": 0.4}]},
    )


def test_low_tailwater_pool_depth_matches_gb_n25_without_mixed_control():
    """GB N.2.5池深使用实际池后水深，独立数值为1.265960米。"""
    result = jump_at_depth(downstream_tailwater_depth=0.1)
    q, h1 = 2.0, 0.4
    h2 = h1 / 2 * (math.sqrt(1 + 8 * q * q / (9.81 * h1**3)) - 1)
    assert h2 == pytest.approx(1.241782, abs=1e-6)
    assert result["conjugate_depth_m"] == pytest.approx(h2, abs=1e-6)
    assert result["recommended_pool_depth_m"] == pytest.approx(1.1 * h2 - 0.1, abs=1e-6)
    assert result["recommended_pool_length_m"] == pytest.approx(4.5 * h2, abs=1e-6)
    assert result["control_depth_m"] == 0.1


def test_missing_tailwater_is_not_replaced_by_chute_normal_depth():
    result = jump_at_depth()
    assert result["conjugate_depth_m"] > 0
    assert result["tailwater_depth_m"] is None
    assert result["recommended_pool_depth_m"] is None
    assert result["design_available"] is False
    assert result["status"] == "missing_tailwater"


def test_dry_tailwater_is_a_valid_explicit_boundary():
    result = jump_at_depth(downstream_tailwater_depth=0)
    assert result["design_available"] is True
    assert result["recommended_pool_depth_m"] == pytest.approx(1.1 * result["conjugate_depth_m"], abs=1e-6)


@pytest.mark.parametrize("extra", [{"m": 1.5, "section_type": "trapezoidal"}, {"stilling_pool_width": 6.0}])
def test_nonrectangular_or_changed_pool_width_does_not_borrow_rectangular_dimensions(extra):
    result = jump_at_depth(downstream_tailwater_depth=0.8, **extra)
    assert result["conjugate_depth_m"] > 0
    assert result["recommended_pool_length_m"] is None
    assert result["recommended_pool_depth_m"] is None
    assert result["status"] == "unsupported_pool_geometry"


def test_near_critical_trapezoidal_jump_conserves_momentum():
    """弱水跃不能把能量临界深误作动量共轭根的下界。"""
    q, b, m = 6.0, 3.0, 1.5
    hc = core._solve_critical_depth(q, b, m, 1.0)
    h1 = hc * 0.99
    area = lambda h: (b + m * h) * h
    momentum = lambda h: q**2 / (9.81 * area(h)) + b * h**2 / 2 + m * h**3 / 3
    fr = q / area(h1) / math.sqrt(9.81 * area(h1) / (b + 2 * m * h1))
    h2 = core._solve_conjugate_depth(q, b, m, h1, core._solve_critical_depth(q, b, m, 1.1), fr)
    assert h2 > hc > h1
    assert momentum(h2) == pytest.approx(momentum(h1), rel=1e-9)


def test_individual_flow_tailwater_is_preserved_and_changes_control_case():
    result = core.quick_calculate_spillway_steep_chute(base(
        downstream_tailwater_depth=99.0,
        flow_cases=[{"Q": 3.0, "tailwater_depth": 0.0}, {"Q": 6.0, "tailwater_depth": 10.0}],
        flow_case_refinement={"enabled": True, "coarse_step_ratio": .1, "refine_step_ratio": .01},
    ))
    multi = result["multi_flow_control"]
    assert [case["tailwater_depth_m"] for case in multi["cases"]] == [0.0, 10.0]
    assert multi["control_flow_m3s"] == 3.0
    assert multi["pool_length_control_case"]["Q"] == 6.0
    assert multi["tailwater_assumption"] == "per_case"
    assert not multi["refinement"]


def test_missing_tailwater_multi_flow_returns_no_invented_control():
    result = core.quick_calculate_spillway_steep_chute(base(flow_cases=[3.0, 6.0]))
    multi = result["multi_flow_control"]
    assert multi["control_case"] is None
    assert len(multi["cases"]) == 2
    assert multi["complete"] is False


def test_equal_flow_with_different_tailwater_keeps_both_operating_conditions():
    result = core.quick_calculate_spillway_steep_chute(base(
        flow_cases=[{"Q": 6, "tailwater_depth": 10}, {"Q": 6, "tailwater_depth": 0}],
    ))
    multi = result["multi_flow_control"]
    assert len(multi["cases"]) == 2
    assert multi["max_pool_depth_m"] > 1.0
    assert multi["pool_depth_control_case"]["tailwater_depth_m"] == 0


def test_partial_individual_boundaries_do_not_inherit_unrelated_main_tailwater():
    result = core.quick_calculate_spillway_steep_chute(base(
        downstream_tailwater_depth=10,
        flow_cases=[{"Q": 3, "tailwater_depth": 0}, {"Q": 6}],
    ))
    multi = result["multi_flow_control"]
    assert multi["cases"][1]["tailwater_depth_m"] is None
    assert multi["complete"] is False


def test_increased_flow_controls_sidewall_height_and_plotted_wall():
    design = core.quick_calculate_spillway_steep_chute(base())
    increased = core.quick_calculate_spillway_steep_chute(base(Q=9.0))
    combined = core.quick_calculate_spillway_steep_chute(base(Q_increased=9.0))
    wall = combined["aeration_and_sidewall"]
    assert wall["increased_flow_checked"] is True
    assert wall["control_flow_m3s"] == 9.0
    assert wall["recommended_sidewall_height_m"] > design["aeration_and_sidewall"]["recommended_sidewall_height_m"]
    assert wall["recommended_sidewall_height_m"] == increased["aeration_and_sidewall"]["recommended_sidewall_height_m"]
    assert all(point["sidewall_height_m"] == wall["recommended_sidewall_height_m"] for point in combined["profile_points"])


def test_rectification_includes_actual_downstream_depth_requirement():
    result = jump_at_depth(downstream_tailwater_depth=20.0)
    assert result["recommended_transition_length_m"] > 60.0


def test_increased_flow_uses_same_physical_length_after_inverse_design():
    result = core.quick_calculate_spillway_steep_chute(base(
        profile_mode="LENGTH_BY_TWO_DEPTHS", start_depth=.2, end_depth=.3, Q_increased=9,
    ))
    length = result["profile"]["length_m"]
    increased_points = result["aeration_and_sidewall"]["increased_flow_profile_points"]
    assert increased_points[-1]["distance_m"] == pytest.approx(length, abs=1e-6)
    expected = core.quick_calculate_spillway_steep_chute(base(
        Q=9, start_depth=.2, L=length,
    ))
    assert result["aeration_and_sidewall"]["recommended_sidewall_height_m"] == expected["aeration_and_sidewall"]["recommended_sidewall_height_m"]


def test_layout_hints_do_not_claim_unverified_code_compliance():
    result = core.quick_calculate_spillway_steep_chute(base(axis_bend_angle_deg=5.0, inlet_contraction_angle_deg=10.0))
    checks = {row["item"]: row for row in result["checks"]}
    for key in ("轴线转折", "进口收缩", "底坡范围"):
        assert checks[key]["passed"] is None
        assert checks[key]["result"] != "通过"
    assert result["comparison"][0]["status"] != "通过"


@pytest.mark.parametrize("key", ["jump_alpha", "pool_depth_factor"])
def test_invalid_dissipation_coefficient_does_not_crash_or_silently_reset(key):
    result = core.quick_calculate_spillway_steep_chute(base(**{key: -1}, downstream_tailwater_depth=1))
    assert result["success"] is False


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_nonfinite_core_input_does_not_enter_the_solver(value):
    assert core.quick_calculate_spillway_steep_chute(base(Q=value))["success"] is False
