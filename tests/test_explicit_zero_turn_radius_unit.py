# -*- coding: utf-8 -*-
"""显式填写 0 的转弯半径回归测试。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from core.geometry_calc import GeometryCalculator
from core.hydraulic_calc import HydraulicCalculator
from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType


def _make_pressure_pipe_node(x: float, y: float) -> ChannelNode:
    """创建一个最小可用的有压管道节点。"""
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.x = float(x)
    node.y = float(y)
    node.section_params = {"D": 1.0, "R": 0.25}
    node.velocity = 2.0
    return node


def test_geometry_calc_respects_explicit_zero_turn_radius():
    """表格里明确填 0 时，几何计算不应再套用默认半径。"""
    settings = ProjectSettings()
    settings.turn_radius = 100.0
    geo_calc = GeometryCalculator(settings)

    start = _make_pressure_pipe_node(0.0, 0.0)
    middle = _make_pressure_pipe_node(10.0, 0.0)
    middle.turn_radius = 0.0
    middle.turn_radius_is_explicit = True
    end = _make_pressure_pipe_node(10.0, 10.0)

    geo_calc.calculate_all_geometry([start, middle, end])

    assert middle.turn_angle == pytest.approx(90.0, abs=1e-6)
    assert middle.tangent_length == pytest.approx(0.0, abs=1e-9)
    assert middle.arc_length == pytest.approx(0.0, abs=1e-9)


def test_hydraulic_calc_respects_explicit_zero_turn_radius_for_xxpipe():
    """xx管匿名有压管道在显式填 0 时不应再计弯头损失。"""
    settings = ProjectSettings()
    settings.turn_radius = 100.0
    settings.channel_level = "支管"
    hyd_calc = HydraulicCalculator(settings)

    node = _make_pressure_pipe_node(10.0, 0.0)
    node.name = ""
    node.turn_angle = 45.0
    node.turn_radius = 0.0
    node.turn_radius_is_explicit = True

    bend_loss = hyd_calc.calculate_bend_loss(node)

    assert bend_loss == pytest.approx(0.0, abs=1e-9)
    assert node.bend_calc_details == {}


def test_geometry_calc_blank_turn_radius_defaults_to_zero():
    """单元格留空时，几何计算也应按 0 处理，不再套用全局半径。"""
    settings = ProjectSettings()
    settings.turn_radius = 100.0
    geo_calc = GeometryCalculator(settings)

    start = _make_pressure_pipe_node(0.0, 0.0)
    middle = _make_pressure_pipe_node(10.0, 0.0)
    middle.turn_radius = 0.0
    middle.turn_radius_is_explicit = False
    end = _make_pressure_pipe_node(10.0, 10.0)

    geo_calc.calculate_all_geometry([start, middle, end])

    assert middle.turn_angle == pytest.approx(90.0, abs=1e-6)
    assert middle.tangent_length == pytest.approx(0.0, abs=1e-9)
    assert middle.arc_length == pytest.approx(0.0, abs=1e-9)


def test_hydraulic_calc_blank_turn_radius_defaults_to_zero_for_xxpipe():
    """xx管匿名有压管道留空时，也应按 0 处理，不再计弯头损失。"""
    settings = ProjectSettings()
    settings.turn_radius = 100.0
    settings.channel_level = "支管"
    hyd_calc = HydraulicCalculator(settings)

    node = _make_pressure_pipe_node(10.0, 0.0)
    node.name = ""
    node.turn_angle = 45.0
    node.turn_radius = 0.0
    node.turn_radius_is_explicit = False

    bend_loss = hyd_calc.calculate_bend_loss(node)

    assert bend_loss == pytest.approx(0.0, abs=1e-9)
    assert node.bend_calc_details == {}
