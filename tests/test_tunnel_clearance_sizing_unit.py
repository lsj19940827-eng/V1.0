# -*- coding: utf-8 -*-
"""测试隧洞-圆拱直墙型按加大流量净空比例反推尺寸。"""

import os
import sys

import pytest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "calc_渠系计算算法内核",
    ),
)

from 隧洞设计 import design_horseshoe_by_freeboard_target, quick_calculate_horseshoe


def _default_kwargs(**overrides):
    """构造一组稳定通过的圆拱直墙反推输入。"""
    data = {
        "Q_design": 10.0,
        "Q_increased": 12.0,
        "n": 0.014,
        "slope_inv": 3000.0,
        "v_min": 0.1,
        "v_max": 3.0,
        "theta_deg": 120.0,
        "hb_ratio": 1.2,
        "target_freeboard_pct": 20.0,
    }
    data.update(overrides)
    return data


def test_clearance_target_sizing_returns_valid_horseshoe_dimensions():
    """典型参数应反推出满足目标净空比例的断面尺寸。"""
    result = design_horseshoe_by_freeboard_target(**_default_kwargs())

    assert result["success"] is True
    assert result["B"] == pytest.approx(3.187, abs=0.01)
    assert result["H_total"] / result["B"] == pytest.approx(1.2, abs=0.001)
    assert result["H_straight"] > 0
    assert result["h_increased"] > result["h_design"]
    assert result["Q_calc_increased"] == pytest.approx(12.0, rel=0.001)
    assert result["freeboard_pct_inc"] == pytest.approx(20.0, abs=0.05)
    assert result["freeboard_hgt_inc"] >= 0.4


def test_clearance_target_sizing_keeps_minimum_target_after_ui_roundtrip():
    """目标为15%时，反推结果按界面三位回填后仍应通过主流程校核。"""
    result = design_horseshoe_by_freeboard_target(
        **_default_kwargs(
            Q_increased=43.7,
            slope_inv=2000.0,
            v_max=100.0,
            hb_ratio=1.1,
            target_freeboard_pct=15.0,
        )
    )

    assert result["success"] is True
    assert result["freeboard_pct_inc"] >= 15.0

    main_result = quick_calculate_horseshoe(
        10.0,
        0.014,
        2000.0,
        0.1,
        100.0,
        manual_B=round(result["B"], 3),
        manual_H_straight=round(result["H_straight"], 3),
        theta_deg=round(result["theta_deg"], 3),
        manual_increase_percent=(43.7 / 10.0 - 1.0) * 100.0,
    )

    assert main_result["success"] is True
    assert main_result["freeboard_pct_inc"] >= 15.0


def test_clearance_target_sizing_rechecks_exact_three_decimal_adoption_case():
    """边界工况按界面三位回填后仍应通过固定断面校核。"""
    result = design_horseshoe_by_freeboard_target(
        **_default_kwargs(
            Q_design=1.0,
            Q_increased=1.3,
            n=0.017,
            slope_inv=8000.0,
            v_max=100.0,
            hb_ratio=1.1,
            theta_deg=150.0,
            target_freeboard_pct=15.0,
        )
    )

    assert result["success"] is True

    main_result = quick_calculate_horseshoe(
        1.0,
        0.017,
        8000.0,
        0.1,
        100.0,
        manual_B=float(f"{result['B']:.3f}"),
        manual_H_straight=float(f"{result['H_straight']:.3f}"),
        theta_deg=float(f"{result['theta_deg']:.3f}"),
        manual_increase_percent=30.0,
    )

    assert main_result["success"] is True
    assert main_result["freeboard_pct_inc"] >= 15.0


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("hb_ratio", 0.99, "高宽比"),
        ("hb_ratio", 1.51, "高宽比"),
        ("theta_deg", 89.9, "圆心角"),
        ("theta_deg", 180.1, "圆心角"),
        ("target_freeboard_pct", 14.9, "净空比例"),
        ("target_freeboard_pct", 100.0, "净空比例"),
        ("Q_increased", 10.0, "加大流量"),
    ],
)
def test_clearance_target_sizing_rejects_invalid_inputs(field, value, message):
    """无效输入应失败并提示对应字段。"""
    result = design_horseshoe_by_freeboard_target(**_default_kwargs(**{field: value}))

    assert result["success"] is False
    assert message in result["error_message"]


def test_clearance_target_sizing_rejects_velocity_out_of_range():
    """反推结果若不满足主流程流速限制，应禁止采用。"""
    result = design_horseshoe_by_freeboard_target(**_default_kwargs(v_max=0.5))

    assert result["success"] is False
    assert "流速" in result["error_message"]
