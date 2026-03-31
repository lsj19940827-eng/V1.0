# -*- coding: utf-8 -*-
"""WaterProfileCalculator 建筑物名称容错校验单测。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from core.calculator import WaterProfileCalculator
from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType


def _make_node(structure_type, *, name="", flow_section="1"):
    node = ChannelNode()
    node.flow_section = flow_section
    node.name = name
    node.structure_type = structure_type
    return node


def _make_settings():
    settings = ProjectSettings()
    settings.design_flow = 1.0
    settings.max_flow = 1.2
    settings.roughness = 0.014
    return settings


def test_validate_input_allows_empty_name_for_open_channel_allowlist():
    calc = WaterProfileCalculator(_make_settings())
    nodes = [
        _make_node(StructureType.MINGQU_RECTANGULAR, name=""),
        _make_node(StructureType.MINGQU_TRAPEZOIDAL, name="明渠二"),
    ]

    is_valid, errors = calc.validate_input(nodes)

    assert is_valid is True
    assert errors == []


def test_validate_input_allows_empty_name_for_pressure_pipe():
    calc = WaterProfileCalculator(_make_settings())
    nodes = [
        _make_node(StructureType.PRESSURE_PIPE, name=""),
        _make_node(StructureType.MINGQU_CIRCULAR, name="", flow_section="2"),
    ]

    is_valid, errors = calc.validate_input(nodes)

    assert is_valid is True
    assert errors == []


def test_validate_input_blocks_empty_name_for_inverted_siphon():
    calc = WaterProfileCalculator(_make_settings())
    nodes = [
        _make_node(StructureType.INVERTED_SIPHON, name=""),
        _make_node(StructureType.MINGQU_CIRCULAR, name="", flow_section="2"),
    ]

    is_valid, errors = calc.validate_input(nodes)

    assert is_valid is False
    assert any("建筑物名称仅以下结构必填" in error for error in errors)
    assert any("明渠-矩形/梯形/圆形、有压管道可留空" in error for error in errors)
    assert any(StructureType.INVERTED_SIPHON.value in error and "需要填写建筑物名称" in error for error in errors)
