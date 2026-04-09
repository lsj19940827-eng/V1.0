# -*- coding: utf-8 -*-
"""明渠复式梯形共享导入与基础几何计算单元测试。"""

import math

import pytest

from 推求水面线.core.hydraulic_calc import HydraulicCalculator
from 推求水面线.models.data_models import ChannelNode, ProjectSettings
from 推求水面线.models.enums import StructureType
from 推求水面线.shared.shared_data_manager import get_shared_data_manager


def test_shared_data_manager_preserves_compound_trapezoid_params():
    """共享数据管理器应保留复式梯形专有参数，并用 B2 兼容底宽口径。"""
    manager = get_shared_data_manager()
    manager.clear_batch_results()

    payload = {
        "success": True,
        "section_type": "明渠-复式梯形",
        "Q": 4.2,
        "n": 0.015,
        "h_design": 2.3,
        "A_design": 9.87,
        "X_design": 7.65,
        "R_hyd_design": 1.29,
        "m1": 0.5,
        "B1": 3.4,
        "m2": 1.25,
        "B2": 4.8,
        "m3": 1.5,
        "h1": 1.2,
    }

    count = manager.register_batch_results([payload])

    assert count == 1
    rows = manager.get_batch_results()
    assert len(rows) == 1

    result = rows[0]
    assert result.section_type == "明渠-复式梯形"
    assert result.B == pytest.approx(4.8)
    assert result.raw_result["m1"] == pytest.approx(0.5)
    assert result.raw_result["B1"] == pytest.approx(3.4)
    assert result.raw_result["m2"] == pytest.approx(1.25)
    assert result.raw_result["B2"] == pytest.approx(4.8)
    assert result.raw_result["m3"] == pytest.approx(1.5)
    assert result.raw_result["h1"] == pytest.approx(1.2)

    node_params = result.to_node_params()
    section_params = node_params["section_params"]
    assert section_params["B"] == pytest.approx(4.8)
    assert section_params["m1"] == pytest.approx(0.5)
    assert section_params["B1"] == pytest.approx(3.4)
    assert section_params["m2"] == pytest.approx(1.25)
    assert section_params["B2"] == pytest.approx(4.8)
    assert section_params["m3"] == pytest.approx(1.5)
    assert section_params["h1"] == pytest.approx(1.2)

    manager.clear_batch_results()


@pytest.mark.parametrize(
    ("water_depth", "expected_area", "expected_perimeter"),
    [
        (
            0.9,
            4.8 * 0.9 + 0.5 * (1.25 + 1.5) * 0.9**2,
            4.8 + 0.9 * math.sqrt(1 + 1.25**2) + 0.9 * math.sqrt(1 + 1.5**2),
        ),
        (
            2.1,
            (
                4.8 * 1.2
                + 0.5 * (1.25 + 1.5) * 1.2**2
                + (4.8 + (1.25 + 1.5) * 1.2 + 3.4) * (2.1 - 1.2)
                + 0.5 * (0.5 + 1.5) * (2.1 - 1.2) ** 2
            ),
            (
                4.8
                + 1.2 * math.sqrt(1 + 1.25**2)
                + 3.4
                + (2.1 - 1.2) * math.sqrt(1 + 0.5**2)
                + 2.1 * math.sqrt(1 + 1.5**2)
            ),
        ),
    ],
)
def test_hydraulic_calculator_supports_compound_trapezoid_geometry(
    water_depth,
    expected_area,
    expected_perimeter,
):
    """水力计算器应按复式梯形公式计算面积、湿周和水力半径。"""
    calculator = HydraulicCalculator(ProjectSettings())
    node = ChannelNode()
    node.structure_type = StructureType.from_string("明渠-复式梯形")
    node.water_depth = water_depth
    node.section_params = {
        "B": 4.8,
        "m1": 0.5,
        "B1": 3.4,
        "m2": 1.25,
        "B2": 4.8,
        "m3": 1.5,
        "h1": 1.2,
    }

    area = calculator.get_cross_section_area(node)
    perimeter = calculator.get_wetted_perimeter(node)
    radius = calculator.calculate_hydraulic_radius(node)

    assert area == pytest.approx(expected_area)
    assert perimeter == pytest.approx(expected_perimeter)
    assert radius == pytest.approx(expected_area / expected_perimeter)
