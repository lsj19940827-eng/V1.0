# -*- coding: utf-8 -*-
"""平底圆形隧洞共享结果与表3水力几何单元测试。"""

import math

import pytest

from 推求水面线.config.constants import STRUCTURE_TYPE_OPTIONS
from 推求水面线.core.hydraulic_calc import HydraulicCalculator
from 推求水面线.models.data_models import ChannelNode, ProjectSettings
from 推求水面线.models.enums import StructureType
from 推求水面线.shared.shared_data_manager import SectionResult, get_shared_data_manager


def _flat_bottom_circle_expected_geometry(diameter: float, bottom_width: float) -> dict:
    """独立计算平底圆形几何真值。"""
    radius = diameter / 2.0
    center_y = math.sqrt(max(radius * radius - (bottom_width / 2.0) ** 2, 0.0))
    cut_height = radius - center_y
    return {
        "radius": radius,
        "center_y": center_y,
        "cut_height": cut_height,
        "H_total": radius + center_y,
    }


def _circular_segment_area(diameter: float, depth: float) -> float:
    """独立计算完整圆从最低点起的弓形面积。"""
    radius = diameter / 2.0
    if depth <= 0:
        return 0.0
    depth = min(depth, diameter)
    if depth >= diameter:
        return math.pi * radius * radius
    theta = 2.0 * math.acos(max(-1.0, min(1.0, (radius - depth) / radius)))
    return radius * radius * (theta - math.sin(theta)) / 2.0


def _flat_bottom_circle_expected_area(diameter: float, bottom_width: float, depth: float) -> float:
    """独立计算平底圆形指定水深下的面积。"""
    geom = _flat_bottom_circle_expected_geometry(diameter, bottom_width)
    return _circular_segment_area(diameter, geom["cut_height"] + depth) - _circular_segment_area(diameter, geom["cut_height"])


def _flat_bottom_circle_expected_perimeter(diameter: float, bottom_width: float, depth: float) -> float:
    """独立计算平底圆形指定水深下的湿周。"""
    geom = _flat_bottom_circle_expected_geometry(diameter, bottom_width)
    radius = geom["radius"]
    start_angle = -math.asin(max(-1.0, min(1.0, geom["center_y"] / radius)))
    water_angle = math.asin(max(-1.0, min(1.0, (depth - geom["center_y"]) / radius)))
    return bottom_width + 2.0 * radius * (water_angle - start_angle)


def _flat_bottom_circle_expected_width(diameter: float, bottom_width: float, depth: float) -> float:
    """独立计算平底圆形指定水深下的水面宽。"""
    geom = _flat_bottom_circle_expected_geometry(diameter, bottom_width)
    radius = geom["radius"]
    return 2.0 * math.sqrt(max(0.0, radius * radius - (depth - geom["center_y"]) ** 2))


def test_flat_bottom_circle_is_registered_in_options_and_enum():
    """平底圆形应成为正式结构类型。"""
    assert "隧洞-平底圆形" in STRUCTURE_TYPE_OPTIONS
    assert hasattr(StructureType, "TUNNEL_FLAT_BOTTOM_CIRCULAR")
    assert StructureType.from_string("隧洞-平底圆形") == StructureType.TUNNEL_FLAT_BOTTOM_CIRCULAR


def test_shared_data_manager_preserves_flat_bottom_circle_params():
    """共享数据管理器应保留平底圆形的 B、D、H_total。"""
    manager = get_shared_data_manager()
    manager.clear_batch_results()

    payload = {
        "success": True,
        "section_type": "隧洞-平底圆形",
        "Q": 5.0,
        "n": 0.014,
        "h_design": 1.2,
        "A_design": 5.3036,
        "P_design": 6.0879,
        "R_hyd_design": 0.8712,
        "B": 2.0,
        "D": 4.0,
        "H_total": _flat_bottom_circle_expected_geometry(4.0, 2.0)["H_total"],
    }

    count = manager.register_batch_results([payload])
    assert count == 1

    rows = manager.get_batch_results()
    assert len(rows) == 1
    result = rows[0]
    assert result.section_type == "隧洞-平底圆形"
    assert result.B == pytest.approx(2.0)
    assert result.D == pytest.approx(4.0)
    assert result.H_total == pytest.approx(payload["H_total"])

    node_params = result.to_node_params()
    section_params = node_params["section_params"]
    assert section_params["B"] == pytest.approx(2.0)
    assert section_params["D"] == pytest.approx(4.0)
    assert section_params["H_total"] == pytest.approx(payload["H_total"])

    manager.clear_batch_results()


def test_hydraulic_calculator_supports_flat_bottom_circle_geometry():
    """表3水力计算应按平底圆形真实公式计算面积、湿周、水力半径和水面宽。"""
    calculator = HydraulicCalculator(ProjectSettings())
    node = ChannelNode()
    node.structure_type = StructureType.from_string("隧洞-平底圆形")
    node.water_depth = 1.2
    node.section_params = {
        "B": 2.0,
        "D": 4.0,
        "H_total": _flat_bottom_circle_expected_geometry(4.0, 2.0)["H_total"],
    }

    expected_area = _flat_bottom_circle_expected_area(4.0, 2.0, 1.2)
    expected_perimeter = _flat_bottom_circle_expected_perimeter(4.0, 2.0, 1.2)
    expected_width = _flat_bottom_circle_expected_width(4.0, 2.0, 1.2)

    area = calculator.get_cross_section_area(node)
    perimeter = calculator.get_wetted_perimeter(node)
    radius = calculator.calculate_hydraulic_radius(node)
    width = calculator.get_water_surface_width(node)

    assert area == pytest.approx(expected_area)
    assert perimeter == pytest.approx(expected_perimeter)
    assert radius == pytest.approx(expected_area / expected_perimeter)
    assert width == pytest.approx(expected_width)


def test_flat_bottom_circle_display_info_falls_back_gracefully_when_dims_missing():
    """共享结果展示在平底圆形尺寸缺失时不应直接报错。"""
    result = SectionResult(
        source="batch",
        timestamp=0.0,
        section_type="隧洞-平底圆形",
        Q=5.0,
        V=1.2,
    )

    text = result.get_display_info()

    assert text == "Q=5.00m³/s, V=1.20m/s"
