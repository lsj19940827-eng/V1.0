# -*- coding: utf-8 -*-
"""平底圆形隧洞内核与共享几何单元测试。"""

import importlib
import math
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for calc_dir in ROOT.glob("calc_*"):
    calc_path = str(calc_dir)
    if calc_path not in sys.path:
        sys.path.insert(0, calc_path)

tunnel_design = importlib.import_module("隧洞设计")
tunnel_geometry = importlib.import_module("app_渠系计算前端.tunnel.geometry")


def _circular_segment_area(diameter: float, depth: float) -> float:
    """独立计算完整圆从最低点起的弓形面积。"""
    if diameter <= 0 or depth <= 0:
        return 0.0
    radius = diameter / 2.0
    depth = min(depth, diameter)
    if depth >= diameter:
        return math.pi * radius * radius
    theta = 2.0 * math.acos(max(-1.0, min(1.0, (radius - depth) / radius)))
    return radius * radius * (theta - math.sin(theta)) / 2.0


def _flat_bottom_circle_expected_geometry(diameter: float, bottom_width: float) -> dict:
    """独立计算平底圆形几何真值。"""
    radius = diameter / 2.0
    half_bottom = bottom_width / 2.0
    center_y = math.sqrt(max(radius * radius - half_bottom * half_bottom, 0.0))
    cut_height = radius - center_y
    total_height = radius + center_y
    cut_theta = 2.0 * math.asin(max(-1.0, min(1.0, bottom_width / diameter)))
    cut_area = radius * radius * (cut_theta - math.sin(cut_theta)) / 2.0
    total_area = math.pi * radius * radius - cut_area
    return {
        "radius": radius,
        "center_y": center_y,
        "cut_height": cut_height,
        "H_total": total_height,
        "A_total": total_area,
        "major_arc_angle": math.pi + 2.0 * math.asin(max(-1.0, min(1.0, center_y / radius))),
    }


def _flat_bottom_circle_expected_area(diameter: float, bottom_width: float, depth: float) -> float:
    """独立计算平底圆形指定水深下的过水面积。"""
    geom = _flat_bottom_circle_expected_geometry(diameter, bottom_width)
    full_depth = geom["cut_height"] + min(max(depth, 0.0), geom["H_total"])
    return _circular_segment_area(diameter, full_depth) - _circular_segment_area(diameter, geom["cut_height"])


def _flat_bottom_circle_expected_perimeter(diameter: float, bottom_width: float, depth: float) -> float:
    """独立计算平底圆形指定水深下的湿周。"""
    geom = _flat_bottom_circle_expected_geometry(diameter, bottom_width)
    depth = min(max(depth, 0.0), geom["H_total"])
    if depth <= 0:
        return 0.0
    radius = geom["radius"]
    start_angle = -math.asin(max(-1.0, min(1.0, geom["center_y"] / radius)))
    water_angle = math.asin(max(-1.0, min(1.0, (depth - geom["center_y"]) / radius)))
    arc_length = 2.0 * radius * (water_angle - start_angle)
    return bottom_width + arc_length


def _flat_bottom_circle_expected_width(diameter: float, bottom_width: float, depth: float) -> float:
    """独立计算平底圆形指定水深下的水面宽。"""
    geom = _flat_bottom_circle_expected_geometry(diameter, bottom_width)
    depth = min(max(depth, 0.0), geom["H_total"])
    if depth <= 0 or depth >= geom["H_total"]:
        return 0.0
    radius = geom["radius"]
    return 2.0 * math.sqrt(max(0.0, radius * radius - (depth - geom["center_y"]) ** 2))


def test_flat_bottom_circle_geometry_helper_matches_expected_values():
    """共享几何 helper 应输出正确的总高、总面积和底边端点。"""
    build_geometry = getattr(tunnel_geometry, "build_flat_bottom_circle_geometry", None)
    assert callable(build_geometry), "缺少 build_flat_bottom_circle_geometry"

    geom = build_geometry(4.0, 2.0)
    expected = _flat_bottom_circle_expected_geometry(4.0, 2.0)

    assert geom["H_total"] == pytest.approx(expected["H_total"])
    assert geom["A_total"] == pytest.approx(expected["A_total"])
    assert geom["bottom_left"] == pytest.approx((-1.0, 0.0))
    assert geom["bottom_right"] == pytest.approx((1.0, 0.0))


@pytest.mark.parametrize(
    ("bottom_width", "depth", "expected_area", "expected_perimeter", "expected_width"),
    [
        (
            2.0,
            1.2,
            _flat_bottom_circle_expected_area(4.0, 2.0, 1.2),
            _flat_bottom_circle_expected_perimeter(4.0, 2.0, 1.2),
            _flat_bottom_circle_expected_width(4.0, 2.0, 1.2),
        ),
        (
            4.0,
            _flat_bottom_circle_expected_geometry(4.0, 4.0)["H_total"],
            _flat_bottom_circle_expected_geometry(4.0, 4.0)["A_total"],
            4.0 + _flat_bottom_circle_expected_geometry(4.0, 4.0)["radius"] * math.pi,
            0.0,
        ),
    ],
)
def test_flat_bottom_circle_kernel_geometry_matches_expected(bottom_width, depth, expected_area, expected_perimeter, expected_width):
    """平底圆形的面积、湿周和水面宽应与独立公式一致。"""
    area_func = getattr(tunnel_design, "calculate_flat_bottom_circular_area", None)
    perimeter_func = getattr(tunnel_design, "calculate_flat_bottom_circular_perimeter", None)
    width_func = getattr(tunnel_design, "calculate_flat_bottom_circular_surface_width", None)

    assert callable(area_func), "缺少 calculate_flat_bottom_circular_area"
    assert callable(perimeter_func), "缺少 calculate_flat_bottom_circular_perimeter"
    assert callable(width_func), "缺少 calculate_flat_bottom_circular_surface_width"

    assert area_func(4.0, bottom_width, depth) == pytest.approx(expected_area)
    assert perimeter_func(4.0, bottom_width, depth) == pytest.approx(expected_perimeter)
    assert width_func(4.0, bottom_width, depth) == pytest.approx(expected_width)


def test_flat_bottom_circle_outputs_and_quick_calculate_keep_d_b_h_total():
    """快速计算应保留 D、B、H_total，并给出设计/加大工况。"""
    outputs_func = getattr(tunnel_design, "calculate_flat_bottom_circular_outputs", None)
    quick_calc = getattr(tunnel_design, "quick_calculate_flat_bottom_circular", None)

    assert callable(outputs_func), "缺少 calculate_flat_bottom_circular_outputs"
    assert callable(quick_calc), "缺少 quick_calculate_flat_bottom_circular"

    outputs = outputs_func(4.0, 2.0, 1.2, 0.014, 1.0 / 2000.0)
    expected_area = _flat_bottom_circle_expected_area(4.0, 2.0, 1.2)
    expected_perimeter = _flat_bottom_circle_expected_perimeter(4.0, 2.0, 1.2)
    expected_geometry = _flat_bottom_circle_expected_geometry(4.0, 2.0)

    assert outputs["A"] == pytest.approx(expected_area)
    assert outputs["P"] == pytest.approx(expected_perimeter)
    assert outputs["A_total"] == pytest.approx(expected_geometry["A_total"])
    assert outputs["freeboard_hgt"] == pytest.approx(expected_geometry["H_total"] - 1.2)

    result = quick_calc(
        Q=5.0,
        n=0.014,
        slope_inv=2000.0,
        v_min=0.1,
        v_max=100.0,
        manual_D=4.0,
        manual_B=2.0,
        manual_increase_percent=20.0,
    )

    assert result["success"] is True
    assert result["section_type"] == "平底圆形"
    assert result["D"] == pytest.approx(4.0)
    assert result["B"] == pytest.approx(2.0)
    assert result["H_total"] == pytest.approx(expected_geometry["H_total"])
    assert result["design_method"] == pytest.approx if False else isinstance(result["design_method"], str)
    assert "平底圆形断面" in result["design_method"]
    assert "D=4.00" in result["design_method"]
    assert "B=2.00" in result["design_method"]
    assert "H=" in result["design_method"]
    assert result["h_increased"] > result["h_design"] > 0
    assert result["Q_increased"] == pytest.approx(6.0)


def test_flat_bottom_circle_quick_calculate_rejects_bottom_width_larger_than_diameter():
    """非法几何应明确失败。"""
    quick_calc = getattr(tunnel_design, "quick_calculate_flat_bottom_circular", None)
    assert callable(quick_calc), "缺少 quick_calculate_flat_bottom_circular"

    result = quick_calc(
        Q=5.0,
        n=0.014,
        slope_inv=2000.0,
        v_min=0.1,
        v_max=100.0,
        manual_D=4.0,
        manual_B=4.1,
        manual_increase_percent=20.0,
    )

    assert result["success"] is False
    assert "B" in result["error_message"]
    assert "D" in result["error_message"]
