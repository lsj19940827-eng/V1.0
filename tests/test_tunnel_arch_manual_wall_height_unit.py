# -*- coding: utf-8 -*-
"""测试隧洞-圆拱直墙型固定直墙高度的内核行为。"""

import math
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

from 隧洞设计 import quick_calculate_horseshoe


def _arch_height(B: float, theta_deg: float) -> float:
    """按底宽和圆心角计算拱高。"""
    theta_rad = math.radians(theta_deg)
    radius = (B / 2.0) / math.sin(theta_rad / 2.0)
    return radius * (1.0 - math.cos(theta_rad / 2.0))


def test_manual_wall_height_fixes_horseshoe_geometry():
    """填写 H直 时应固定直墙高度，并由 H直+H拱 得到总高。"""
    result = quick_calculate_horseshoe(
        Q=3.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=3.0,
        theta_deg=150.0,
        manual_B=3.0,
        manual_H_straight=1.2,
    )

    assert result["success"] is True
    assert result["used_manual_H_straight"] is True
    assert result["manual_H_straight"] == pytest.approx(1.2)
    assert result["H_straight"] == pytest.approx(1.2)
    assert result["H_total"] == pytest.approx(1.2 + _arch_height(3.0, 150.0))
    assert result["B"] == pytest.approx(3.0)


def test_manual_wall_height_requires_manual_bottom_width():
    """填写 H直 但未填写 B 时应失败并给出明确提示。"""
    result = quick_calculate_horseshoe(
        Q=3.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=3.0,
        theta_deg=150.0,
        manual_H_straight=1.2,
    )

    assert result["success"] is False
    assert "底宽" in result["error_message"]


def test_manual_wall_height_rejects_negative_value():
    """H直 不允许为负数。"""
    result = quick_calculate_horseshoe(
        Q=3.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=3.0,
        theta_deg=150.0,
        manual_B=3.0,
        manual_H_straight=-0.1,
    )

    assert result["success"] is False
    assert "直墙高度" in result["error_message"]


def test_manual_wall_height_does_not_fallback_to_auto_search():
    """固定几何不满足要求时应失败，不能改用自动寻优结果。"""
    result = quick_calculate_horseshoe(
        Q=8.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=3.0,
        theta_deg=150.0,
        manual_B=3.0,
        manual_H_straight=1.2,
    )

    assert result["success"] is False
    assert result["used_manual_H_straight"] is True
    assert "固定" in result["error_message"]
