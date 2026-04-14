# -*- coding: utf-8 -*-
"""xx管模式基础规则单测。"""

import importlib.util
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from config.constants import (
    STRUCTURE_TYPE_OPTIONS,
    XXPIPE_ALLOWED_STRUCTURE_KEYWORDS,
    XXPIPE_ALLOWED_STRUCTURE_OPTIONS,
)
from models.enums import StructureType


def test_structure_type_enum_includes_xxpipe_specific_pipe_structures():
    assert StructureType.DIRECTIONAL_DRILL.value == "定向钻"
    assert StructureType.PIPE_JACKING.value == "顶管"
    assert StructureType.from_string("定向钻") is StructureType.DIRECTIONAL_DRILL
    assert StructureType.from_string("顶管") is StructureType.PIPE_JACKING


def test_structure_type_options_include_xxpipe_specific_pipe_structures():
    assert "定向钻" in STRUCTURE_TYPE_OPTIONS
    assert "顶管" in STRUCTURE_TYPE_OPTIONS


def test_xxpipe_allowed_structure_options_cover_pipe_rule_baseline():
    expected = {
        "有压管道",
        "隧洞-圆形",
        "隧洞-平底圆形",
        "隧洞-圆拱直墙型",
        "隧洞-马蹄形Ⅰ型",
        "隧洞-马蹄形Ⅱ型",
        "定向钻",
        "顶管",
    }

    assert set(XXPIPE_ALLOWED_STRUCTURE_OPTIONS) == expected
    assert "明渠-矩形" not in XXPIPE_ALLOWED_STRUCTURE_OPTIONS
    assert "暗涵-矩形" not in XXPIPE_ALLOWED_STRUCTURE_OPTIONS
    assert "暗涵-圆拱直墙型" not in XXPIPE_ALLOWED_STRUCTURE_OPTIONS
    assert set(XXPIPE_ALLOWED_STRUCTURE_OPTIONS).issubset(STRUCTURE_TYPE_OPTIONS)


def test_xxpipe_allowed_structure_options_include_all_tunnel_dropdown_variants():
    assert XXPIPE_ALLOWED_STRUCTURE_KEYWORDS == ("隧洞",)

    tunnel_options = {
        option
        for option in STRUCTURE_TYPE_OPTIONS
        if any(keyword in option for keyword in XXPIPE_ALLOWED_STRUCTURE_KEYWORDS)
    }

    assert tunnel_options
    assert tunnel_options.issubset(set(XXPIPE_ALLOWED_STRUCTURE_OPTIONS))


@pytest.mark.parametrize("structure_type", ["暗涵-矩形", "暗涵-圆拱直墙型"])
def test_xxpipe_allowed_structure_options_exclude_culvert_family(structure_type):
    assert structure_type in STRUCTURE_TYPE_OPTIONS
    assert structure_type not in XXPIPE_ALLOWED_STRUCTURE_OPTIONS


def test_cad_tools_xxpipe_helper_contract_is_available():
    root = Path(__file__).resolve().parents[1]
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "未找到 cad_tools.py"

    spec = importlib.util.spec_from_file_location("cad_tools_xxpipe_rules_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert callable(module._is_xxpipe_channel_level)
    assert callable(module._is_xxpipe_allowed_structure)
    assert callable(module._is_xxpipe_named_structure)
    assert module._is_xxpipe_channel_level("支管")
    assert module._is_xxpipe_allowed_structure("定向钻")
    assert module._is_xxpipe_named_structure("顶管")
    assert not module._is_xxpipe_allowed_structure("暗涵-矩形")
    assert not module._is_xxpipe_allowed_structure("暗涵-圆拱直墙型")
    assert not module._is_xxpipe_pressure_structure("暗涵-圆拱直墙型")
    assert not module._is_xxpipe_tunnel_structure("暗涵-圆拱直墙型")
    assert not module._is_xxpipe_named_structure("暗涵-圆拱直墙型")
