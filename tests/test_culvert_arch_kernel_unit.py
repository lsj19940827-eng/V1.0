# -*- coding: utf-8 -*-
"""圆拱直墙型暗涵独立算法测试。"""

import math
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CALC_ROOT = ROOT / "calc_渠系计算算法内核"
if str(CALC_ROOT) not in sys.path:
    sys.path.insert(0, str(CALC_ROOT))

from 圆拱直墙型暗涵设计 import quick_calculate_arch_culvert


def _arch_height(B: float, theta_deg: float) -> float:
    """按底宽和圆心角计算拱高。"""
    theta_rad = math.radians(theta_deg)
    radius = (B / 2.0) / math.sin(theta_rad / 2.0)
    return radius * (1.0 - math.cos(theta_rad / 2.0))


def test_arch_culvert_quick_calculate_uses_culvert_constraints():
    """圆拱直墙型暗涵应独立返回暗涵口径结果。"""
    result = quick_calculate_arch_culvert(
        Q=6.0,
        n=0.014,
        slope_inv=2200.0,
        v_min=0.6,
        v_max=2.8,
        theta_deg=140.0,
        manual_B=2.6,
        manual_increase_percent=20.0,
    )

    assert result["success"] is True
    assert result["section_type"] == "暗涵-圆拱直墙型"
    assert result["B"] == pytest.approx(2.6)
    assert result["theta_deg"] == pytest.approx(140.0)
    assert result["freeboard_pct_inc"] >= 10.0 - 1e-6
    assert result["freeboard_pct_inc"] <= 30.0 + 1e-6
    assert result["freeboard_hgt_inc"] >= 0.4 - 1e-6


def test_arch_culvert_quick_calculate_rejects_invalid_theta():
    """圆拱直墙型暗涵仍应拦截非法圆心角。"""
    result = quick_calculate_arch_culvert(
        Q=6.0,
        n=0.014,
        slope_inv=2200.0,
        v_min=0.6,
        v_max=2.8,
        theta_deg=80.0,
        manual_B=2.6,
    )

    assert result["success"] is False
    assert "圆心角" in result["error_message"]


def test_arch_culvert_manual_wall_height_fixes_geometry():
    """填写 H直 时应固定暗涵直墙高度，并由 H直+H拱 得到总高。"""
    result = quick_calculate_arch_culvert(
        Q=5.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=3.0,
        theta_deg=150.0,
        manual_B=3.0,
        manual_H_straight=1.2,
        manual_increase_percent=0.0,
    )

    assert result["success"] is True
    assert result["used_manual_H_straight"] is True
    assert result["manual_H_straight"] == pytest.approx(1.2)
    assert result["H_straight"] == pytest.approx(1.2)
    assert result["H_total"] == pytest.approx(1.2 + _arch_height(3.0, 150.0))
    assert result["B"] == pytest.approx(3.0)


def test_arch_culvert_manual_wall_height_requires_bottom_width():
    """填写 H直 但未填写 B 时应失败并给出明确提示。"""
    result = quick_calculate_arch_culvert(
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


def test_arch_culvert_manual_wall_height_rejects_negative_value():
    """H直 不允许为负数。"""
    result = quick_calculate_arch_culvert(
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


def test_arch_culvert_manual_wall_height_does_not_fallback_to_auto_search():
    """固定几何不满足要求时应失败，不能改用自动寻优结果。"""
    result = quick_calculate_arch_culvert(
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
