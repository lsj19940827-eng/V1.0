# -*- coding: utf-8 -*-
"""明渠复式梯形类型注册的单元测试。"""

from 推求水面线.config.constants import STRUCTURE_TYPE_OPTIONS
from 推求水面线.models.enums import StructureType


def test_compound_trapezoid_is_registered_in_options_and_enum():
    """复式梯形应作为独立结构类型对外暴露。"""
    assert "明渠-复式梯形" in STRUCTURE_TYPE_OPTIONS
    assert StructureType.from_string("明渠-复式梯形") == StructureType.MINGQU_COMPOUND_TRAPEZOIDAL
