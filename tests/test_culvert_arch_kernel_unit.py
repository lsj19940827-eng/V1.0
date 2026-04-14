# -*- coding: utf-8 -*-
"""圆拱直墙型暗涵独立算法测试。"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CALC_ROOT = ROOT / "calc_渠系计算算法内核"
if str(CALC_ROOT) not in sys.path:
    sys.path.insert(0, str(CALC_ROOT))

from 圆拱直墙型暗涵设计 import quick_calculate_arch_culvert


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
