# -*- coding: utf-8 -*-
"""验证充水渠/泄水渠别名在表3中按泄水渠与陡坡专项链处理。"""

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WATER_PROFILE_ROOT = ROOT / "推求水面线"
for path in (str(ROOT), str(WATER_PROFILE_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from config.constants import STRUCTURE_TYPE_OPTIONS
from core.calculator import WaterProfileCalculator
from core.spillway_steep_chute_adapter import (
    SPILLWAY_STEEP_CHUTE_PARAM_KEY,
    build_spillway_steep_chute_input,
    calculate_and_apply_spillway_steep_chute_group,
    is_spillway_steep_chute_node,
    prepare_spillway_steep_chute_groups,
)
from models.data_models import ChannelNode, ProjectSettings
from models.enums import InOutType, StructureType


FILL_CHANNEL_ALIASES = ("充水渠", "泄水渠", "陡坡", "泄槽", "陡槽", "泄水渠及陡坡", "泄水渠与陡坡")


def _rectangular_node(
    name: str,
    structure: str,
    station: float,
    *,
    x: float,
    water_level: float | None = None,
    water_depth: float = 1.2,
    flow: float = 10.0,
    width: float = 2.0,
    roughness: float = 0.014,
    slope_inv: float = 100.0,
) -> ChannelNode:
    """构造表3常见的矩形渠道节点。"""
    node = ChannelNode()
    node.flow_section = "1"
    node.name = name
    node.structure_type = StructureType.from_string(structure)
    node.in_out = InOutType.NORMAL
    node.x = x
    node.y = 0.0
    node.station_MC = station
    node.flow = flow
    node.design_flow = flow
    node.roughness = roughness
    node.slope_i = 1.0 / slope_inv
    node.water_depth = water_depth
    node.structure_height = water_depth + 0.5
    if water_level is not None:
        node.water_level = water_level
        node.channel_bottom_elevation = water_level - water_depth
    node.section_params.update(
        {
            "B": width,
            "m": 0.0,
            "A": width * water_depth,
            "X": width + 2.0 * water_depth,
            "R": (width * water_depth) / (width + 2.0 * water_depth),
        }
    )
    return node


def test_structure_type_options_and_aliases_are_spillway_steep_chute():
    """结构形式列的充水渠类名称应统一识别为泄水渠与陡坡专项类型。"""
    for alias in FILL_CHANNEL_ALIASES:
        assert StructureType.from_string(alias) == StructureType.SPILLWAY_STEEP_CHUTE
    assert StructureType.SPILLWAY_STEEP_CHUTE.value in STRUCTURE_TYPE_OPTIONS


def test_table3_fill_channel_chain_splits_by_slope_and_uses_special_kernel():
    """连续充水渠链应按底坡变化分成专项子段，并保持水位连续。"""
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=105.0))
    nodes = [
        _rectangular_node("上游明渠", "明渠-矩形", 0.0, x=0.0, water_level=105.0, flow=0.7),
        _rectangular_node("-", "充水渠", 20.0, x=20.0, flow=0.7, width=1.0, slope_inv=100.0),
        _rectangular_node("-", "充水渠", 60.0, x=60.0, flow=0.7, width=1.0, slope_inv=10.0),
        _rectangular_node("-", "充水渠", 120.0, x=120.0, flow=0.7, width=1.0, slope_inv=24.5),
        _rectangular_node("-", "充水渠", 150.0, x=150.0, flow=0.7, width=1.0, slope_inv=24.5),
    ]

    results = calculator.calculate_all(nodes)
    spillway_nodes = [node for node in results if is_spillway_steep_chute_node(node)]

    assert len(spillway_nodes) == 4
    assert all(node.water_level > 0 and node.water_depth > 0 and node.velocity > 0 for node in spillway_nodes)
    payloads = [node.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY] for node in spillway_nodes]
    assert all(payload["chain_segment_count"] == 3 for payload in payloads)
    assert payloads[0]["role"] == "inlet"
    assert payloads[-1]["role"] == "outlet"
    assert all(node.name == "" for node in spillway_nodes)
    assert all(node.in_out == InOutType.NORMAL for node in spillway_nodes)
    assert all("泄陡" not in node.get_ip_str() for node in spillway_nodes)
    assert [item["slope_inv"] for item in payloads[0]["chain_subsegments"]] == pytest.approx([100.0, 10.0, 24.5])
    assert [item["node_count"] for item in payloads[0]["chain_subsegments"]] == [2, 2, 2]
    assert payloads[2]["segment_key"] == payloads[3]["segment_key"]
    assert payloads[1]["inlet_water_level_m"] == pytest.approx(payloads[0]["outlet_water_level_m"])
    assert payloads[2]["inlet_water_level_m"] == pytest.approx(payloads[1]["outlet_water_level_m"])


def test_table3_single_fill_channel_node_requires_downstream_node():
    """孤立单行充水渠不能退回普通明渠，应提示缺少下游节点。"""
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=105.0))
    nodes = [
        _rectangular_node("上游明渠", "明渠-矩形", 0.0, x=0.0, water_level=105.0),
        _rectangular_node("", "泄水渠与陡坡", 10.0, x=10.0, slope_inv=18.0),
        _rectangular_node("下游明渠", "明渠-矩形", 30.0, x=30.0),
    ]

    with pytest.raises(ValueError, match="缺少相邻下游节点"):
        calculator.calculate_all(nodes)


def _three_slope_chain():
    """构造同断面三段变坡，末段应继承浅水急流并形成c2增水曲线。"""
    return [
        _rectangular_node("", "陡坡", station, x=station, flow=0.7, width=1.0, slope_inv=slope)
        for station, slope in ((20.0, 100.0), (60.0, 10.0), (120.0, 24.5), (150.0, 24.5))
    ]


def test_chain_preserves_bed_depth_and_energy_at_slope_changes():
    """变坡交界不能靠重复设临界水深虚构渠底跌差。"""
    nodes = _three_slope_chain()
    prepare_spillway_steep_chute_groups(nodes)
    assert calculate_and_apply_spillway_steep_chute_group(nodes, 0, 105.0) == 3
    payloads = [node.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY] for node in nodes[:3]]
    results = [payload["result"] for payload in payloads]
    assert results[0]["start_control"]["mode"] == "critical_depth"
    for previous, following in zip(results, results[1:]):
        outlet = previous["profile"]["points"][-1]
        inlet = following["profile"]["points"][0]
        for key in ("depth_m", "bed_elevation_m", "water_elevation_m", "velocity_ms"):
            assert inlet[key] == pytest.approx(outlet[key], abs=2e-6)
        assert inlet["bed_elevation_m"] + inlet["specific_energy_m"] == pytest.approx(
            outlet["bed_elevation_m"] + outlet["specific_energy_m"], abs=2e-6)
        assert following["start_control"]["mode"] == "manual"
    initial = results[0]["profile"]["points"][0]
    final = results[-1]["profile"]["points"][-1]
    assert initial["bed_elevation_m"] - final["bed_elevation_m"] == pytest.approx(
        40.0 / 100.0 + 60.0 / 10.0 + 30.0 / 24.5, abs=2e-6)
    assert results[-1]["profile"]["water_profile_type"] == "c_2"
    assert final["depth_m"] > results[-1]["profile"]["points"][0]["depth_m"]


@pytest.mark.parametrize("key,value", [("B", 2.0), ("m", 1.5)])
@pytest.mark.parametrize("same_slope", [True, False])
def test_variable_geometry_cannot_silently_use_prismatic_chain(key, value, same_slope):
    """同坡和变坡处的几何变化均需独立过渡计算，不能忽略或重设临界深。"""
    nodes = _three_slope_chain()
    nodes[2].section_params[key] = value
    if same_slope:
        for node in nodes:
            node.slope_i = 0.01
    with pytest.raises(ValueError, match="变断面须另算过渡段及局部损失"):
        prepare_spillway_steep_chute_groups(nodes)


def test_adapter_does_not_invent_inlet_head_or_width():
    """专项链未填入口校核资料时不捏造总水头，真实输入仍可传递。"""
    nodes = _three_slope_chain()
    group = next(iter(prepare_spillway_steep_chute_groups(nodes).values()))
    payload = build_spillway_steep_chute_input(group["subsegments"][0], 105.0)
    assert "inlet_head" not in payload
    assert "inlet_weir_width" not in payload
    nodes[0].section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY]["advanced_params"] = {
        "inlet_head": 0.9, "inlet_weir_width": 1.1,
    }
    explicit = build_spillway_steep_chute_input(group["subsegments"][0], 105.0)
    assert explicit["inlet_head"] == 0.9
    assert explicit["inlet_weir_width"] == 1.1
