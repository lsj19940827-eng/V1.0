# -*- coding: utf-8 -*-
"""有压管道同类结构识别单元测试。"""

import os
import sys
from types import SimpleNamespace


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from core.calculator import WaterProfileCalculator
from core.pressure_pipe_data import PressurePipeDataExtractor
from models.enums import StructureType


def test_structure_type_pressure_pipe_like_helpers_cover_xxpipe_types():
    assert StructureType.is_pressure_pipe_like(StructureType.PRESSURE_PIPE) is True
    assert StructureType.is_pressure_pipe_like(StructureType.DIRECTIONAL_DRILL) is True
    assert StructureType.is_pressure_pipe_like(StructureType.PIPE_JACKING) is True

    assert StructureType.is_pressure_pipe_like_str("有压管道") is True
    assert StructureType.is_pressure_pipe_like_str("定向钻") is True
    assert StructureType.is_pressure_pipe_like_str("顶管") is True
    assert StructureType.is_pressure_pipe_like_str("明渠-矩形") is False


def test_calculator_and_extractor_treat_xxpipe_types_as_pressure_pipes():
    calculator = WaterProfileCalculator.__new__(WaterProfileCalculator)

    for structure_type in (StructureType.DIRECTIONAL_DRILL, StructureType.PIPE_JACKING):
        node = SimpleNamespace(structure_type=structure_type, is_pressure_pipe=False)
        assert calculator.is_pressure_pipe(node) is True
        assert PressurePipeDataExtractor._is_pressure_pipe(node) is True
