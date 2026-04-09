# -*- coding: utf-8 -*-
"""复式梯形明渠内核的单元测试。"""

import math
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, os.path.join(str(ROOT), "calc_渠系计算算法内核"))

from 明渠设计 import (  # noqa: E402
    calculate_compound_trapezoid_area,
    calculate_compound_trapezoid_flow_rate,
    calculate_compound_trapezoid_wetted_perimeter,
    quick_calculate_compound_trapezoidal,
)


def test_compound_trapezoid_piecewise_geometry_matches_formula():
    """分段面积和湿周应严格符合需求公式。"""
    area_low = calculate_compound_trapezoid_area(3.0, 0.8, 1.0, 1.0, 1.0, 2.0, 1.5)
    perimeter_low = calculate_compound_trapezoid_wetted_perimeter(3.0, 0.8, 1.0, 1.0, 1.0, 2.0, 1.5)

    assert area_low == pytest.approx(3.04, abs=1e-6)
    assert perimeter_low == pytest.approx(3.0 + 1.6 * math.sqrt(2.0), abs=1e-6)

    area_high = calculate_compound_trapezoid_area(3.0, 1.6, 1.0, 1.0, 1.0, 2.0, 1.5)
    perimeter_high = calculate_compound_trapezoid_wetted_perimeter(3.0, 1.6, 1.0, 1.0, 1.0, 2.0, 1.5)

    assert area_high == pytest.approx(8.65, abs=1e-6)
    assert perimeter_high == pytest.approx(
        3.0 + math.sqrt(2.0) + 2.0 + 0.6 * math.sqrt(3.25) + 1.6 * math.sqrt(2.0),
        abs=1e-6,
    )


def test_compound_trapezoid_quick_calculate_inverts_depth_from_fixed_geometry():
    """固定几何参数时，应能反算回目标设计水深。"""
    target_h = 1.6
    design_q = calculate_compound_trapezoid_flow_rate(
        B2=3.0,
        h=target_h,
        i=1 / 3000,
        n=0.014,
        m1=1.5,
        B1=2.0,
        m2=1.0,
        m3=1.0,
        h1=1.0,
    )

    result = quick_calculate_compound_trapezoidal(
        Q=design_q,
        m1=1.5,
        B1=2.0,
        m2=1.0,
        B2=3.0,
        m3=1.0,
        h1=1.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=100.0,
        manual_increase_percent=20.0,
    )

    assert result["success"] is True
    assert result["design_method"] == "固定复式梯形断面"
    assert result["h_design"] == pytest.approx(target_h, abs=0.005)
    assert result["Q_calc"] == pytest.approx(round(design_q, 3), abs=0.01)
    assert result["h_increased"] > result["h_design"]
    assert result["h_prime"] == pytest.approx(result["h_increased"] + result["Fb"], abs=0.001)


def test_compound_trapezoid_quick_calculate_rejects_non_positive_platform_geometry():
    """平台宽和平台高差必须为正值，避免零几何进入后续计算。"""
    result_b1 = quick_calculate_compound_trapezoidal(
        Q=5.0,
        m1=1.5,
        B1=0.0,
        m2=1.0,
        B2=3.0,
        m3=1.0,
        h1=1.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=100.0,
    )
    result_h1 = quick_calculate_compound_trapezoidal(
        Q=5.0,
        m1=1.5,
        B1=2.0,
        m2=1.0,
        B2=3.0,
        m3=1.0,
        h1=0.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=100.0,
    )

    assert result_b1["success"] is False
    assert "B1" in result_b1["error_message"]
    assert result_h1["success"] is False
    assert "h1" in result_h1["error_message"]
