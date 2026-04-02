# -*- coding: utf-8 -*-
"""bzzh2 桩号格式化回归测试。"""

from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace


def _load_cad_tools():
    """加载 cad_tools 模块，供独立单元测试复用。"""
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "未找到 cad_tools.py"
    spec = importlib.util.spec_from_file_location("cad_tools_bzzh2_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cad_tools = _load_cad_tools()


def _make_node(**overrides):
    """构造一个满足 bzzh2 提取所需字段的节点。"""
    base = {
        "station_MC": 39.497,
        "in_out": SimpleNamespace(value="进"),
        "name": "一号",
        "structure_type": SimpleNamespace(value="倒虹吸-圆形"),
        "is_transition": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_collect_bzzh2_rows_defaults_to_two_station_decimals():
    rows = cad_tools._collect_bzzh2_rows(
        [_make_node()],
        "合干",
        {"station_decimals": 2},
    )

    assert rows == [("合干0+039.50", "一号倒虹吸进")]


def test_collect_bzzh2_rows_respects_custom_station_decimals():
    rows = cad_tools._collect_bzzh2_rows(
        [_make_node()],
        "合干",
        {"station_decimals": 3},
    )

    assert rows == [("合干0+039.497", "一号倒虹吸进")]
