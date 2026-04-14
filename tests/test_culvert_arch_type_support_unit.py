# -*- coding: utf-8 -*-
"""暗涵类型统一口径的单元测试。"""

from 推求水面线.config.constants import (
    STRUCTURE_TYPE_OPTIONS,
    XXPIPE_ALLOWED_STRUCTURE_OPTIONS,
)
from 推求水面线.models.enums import StructureType


def test_culvert_types_are_registered_with_new_normalized_labels():
    """暗涵类型应对外统一暴露为新口径。"""
    assert "暗涵-矩形" in STRUCTURE_TYPE_OPTIONS
    assert "暗涵-圆拱直墙型" in STRUCTURE_TYPE_OPTIONS
    assert "矩形暗涵" not in STRUCTURE_TYPE_OPTIONS


def test_structure_type_from_string_supports_new_and_legacy_culvert_labels():
    """新旧暗涵标签都应可读，并归到统一结构类型。"""
    assert StructureType.from_string("暗涵-矩形") == StructureType.RECT_CULVERT
    assert StructureType.from_string("矩形暗涵") == StructureType.RECT_CULVERT
    assert StructureType.from_string("暗渠") == StructureType.RECT_CULVERT
    assert StructureType.from_string("矩形暗渠") == StructureType.RECT_CULVERT
    assert StructureType.from_string("暗涵-圆拱直墙型") == StructureType.CULVERT_ARCH
    assert StructureType.from_string("圆拱直墙型暗涵") == StructureType.CULVERT_ARCH


def test_culvert_arch_is_not_exposed_as_xxpipe_tunnel_option():
    """新暗涵类型不能被误归到 xx管 的隧洞类别。"""
    assert "暗涵-圆拱直墙型" not in XXPIPE_ALLOWED_STRUCTURE_OPTIONS
