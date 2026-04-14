# -*- coding: utf-8 -*-
"""渐变段补段 donor 与暗涵家族插入节点测试。"""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from core.calculator import WaterProfileCalculator
from core.hydraulic_calc import HydraulicCalculator
from models.data_models import ChannelNode, OpenChannelParams, ProjectSettings
from models.enums import InOutType, StructureType


def _make_node(
    structure_type: str,
    *,
    flow_section: str,
    station: float,
    name: str,
    B: float = 0.0,
    H_total: float = 0.0,
    m: float = 0.0,
    theta_deg: float = 0.0,
    culvert_family_type: str = "",
    water_depth: float = 1.0,
    roughness: float = 0.014,
    slope_i: float = 1 / 3000,
) -> ChannelNode:
    node = ChannelNode()
    node.structure_type = StructureType.from_string(structure_type)
    node.flow_section = flow_section
    node.name = name
    node.station_MC = station
    node.in_out = InOutType.NORMAL
    node.water_depth = water_depth
    node.roughness = roughness
    node.slope_i = slope_i
    node.flow = 2.88
    node.section_params = {"B": B, "m": m}
    if H_total > 0:
        node.section_params["H_total"] = H_total
        node.structure_height = H_total
    if theta_deg > 0:
        node.section_params["theta_deg"] = theta_deg
    if culvert_family_type:
        node.section_params["culvert_family_type"] = culvert_family_type
    return node


@pytest.mark.parametrize(
    "structure_type",
    ["暗渠", "矩形暗渠", "矩形暗涵", "暗涵-矩形", "暗涵-圆拱直墙型"],
)
def test_reference_family_recognizes_culvert_family_aliases(structure_type):
    calc = WaterProfileCalculator(ProjectSettings())

    assert calc._reference_family_for_gap_type(structure_type) == "culvert"


def test_same_section_prefers_culvert_when_gap_both_sides_are_culverts():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [
        _make_node("矩形暗涵", flow_section="1", station=0.0, name="上游暗涵", B=2.4, H_total=2.0, water_depth=1.3),
        _make_node("矩形暗涵", flow_section="1", station=20.0, name="下游暗涵", B=2.6, H_total=2.2, water_depth=1.4),
        _make_node("明渠-矩形", flow_section="1", station=40.0, name="同段明渠", B=3.5, water_depth=1.1),
    ]

    ref = calc._find_reference_segment_same_section_v2(nodes, 1, 0, 1)

    assert ref is not None
    assert ref["structure_type"] == "矩形暗涵"
    assert ref["section_family"] == "culvert"
    assert ref["bottom_width"] == 2.6


def test_same_section_prefers_arch_culvert_family_with_new_structure_type():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [
        _make_node(
            "暗涵-圆拱直墙型",
            flow_section="1",
            station=0.0,
            name="上游圆拱暗涵",
            B=2.4,
            H_total=3.0,
            theta_deg=132.0,
            water_depth=1.3,
        ),
        _make_node(
            "暗涵-圆拱直墙型",
            flow_section="1",
            station=20.0,
            name="下游圆拱暗涵",
            B=2.6,
            H_total=3.2,
            theta_deg=140.0,
            water_depth=1.4,
        ),
        _make_node("明渠-矩形", flow_section="1", station=40.0, name="同段明渠", B=3.5, water_depth=1.1),
    ]

    ref = calc._find_reference_segment_same_section_v2(nodes, 1, 0, 1)

    assert ref is not None
    assert ref["structure_type"] == "暗涵-圆拱直墙型"
    assert ref["section_family"] == "culvert"
    assert ref["bottom_width"] == pytest.approx(2.6)
    assert ref["structure_height"] == pytest.approx(3.2)
    assert ref["theta_deg"] == pytest.approx(140.0)


def test_mixed_gap_prefers_open_channel_before_cross_section_culvert():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [
        _make_node("明渠-矩形", flow_section="1", station=0.0, name="同段明渠", B=2.8, water_depth=1.2),
        _make_node("矩形暗涵", flow_section="2", station=20.0, name="跨段暗涵", B=2.4, H_total=2.1, water_depth=1.3),
        _make_node("明渠-梯形", flow_section="1", station=40.0, name="目标右侧", B=2.6, m=1.5, water_depth=1.0),
    ]

    ref = calc._find_reference_segment_same_section_v2(nodes, 2, 1, 2)

    assert ref is not None
    assert ref["structure_type"] in {"明渠-矩形", "明渠-梯形"}
    assert ref["section_family"] == "open_channel"


@pytest.mark.parametrize("structure_type", ["矩形暗涵", "暗涵-矩形"])
def test_create_open_channel_node_supports_rect_culvert(structure_type):
    calc = WaterProfileCalculator(ProjectSettings())
    prev_node = _make_node(structure_type, flow_section="1", station=0.0, name="前", B=2.0, H_total=2.0)
    next_node = _make_node(structure_type, flow_section="1", station=50.0, name="后", B=2.0, H_total=2.0)
    prev_node.x = 0.0
    prev_node.y = 0.0
    next_node.x = 10.0
    next_node.y = 6.0

    params = OpenChannelParams(
        name="-",
        structure_type=structure_type,
        bottom_width=2.5,
        water_depth=1.6,
        side_slope=0.0,
        roughness=0.014,
        slope_inv=3000,
        flow=3.0,
        flow_section="1",
        structure_height=2.2,
    )

    node = calc._create_open_channel_node(params, prev_node, next_node)

    assert node.structure_type == StructureType.RECT_CULVERT
    assert node.is_auto_inserted_channel is True
    assert node.section_params["B"] == 2.5
    assert node.section_params["H_total"] == 2.2
    assert node.structure_height == 2.2
    assert node.water_depth == 1.6
    assert node.roughness == 0.014
    assert abs(node.slope_i - (1 / 3000)) < 1e-9
    assert node.section_params["A"] > 0
    assert node.velocity > 0


def test_create_open_channel_node_supports_arch_culvert_shared_params():
    calc = WaterProfileCalculator(ProjectSettings())
    prev_node = _make_node("暗涵-圆拱直墙型", flow_section="1", station=0.0, name="前", B=2.0, H_total=3.0)
    next_node = _make_node("暗涵-圆拱直墙型", flow_section="1", station=50.0, name="后", B=2.0, H_total=3.0)
    prev_node.x = 0.0
    prev_node.y = 0.0
    next_node.x = 10.0
    next_node.y = 6.0

    params = OpenChannelParams(
        name="-",
        structure_type="暗涵-圆拱直墙型",
        bottom_width=2.6,
        water_depth=1.5,
        side_slope=0.0,
        roughness=0.014,
        slope_inv=2500,
        flow=3.0,
        flow_section="1",
        structure_height=3.1,
        theta_deg=140.0,
    )

    node = calc._create_open_channel_node(params, prev_node, next_node)

    assert node.structure_type == StructureType.CULVERT_ARCH
    assert node.is_auto_inserted_channel is True
    assert node.section_params["B"] == pytest.approx(2.6)
    assert node.section_params["H_total"] == pytest.approx(3.1)
    assert node.section_params["theta_deg"] == pytest.approx(140.0)
    assert node.structure_height == pytest.approx(3.1)


def test_same_section_reference_preserves_arch_culvert_family():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [
        _make_node(
            "矩形暗涵",
            flow_section="1",
            station=0.0,
            name="上游圆拱暗涵",
            B=2.4,
            H_total=2.8,
            theta_deg=150.0,
            culvert_family_type="暗涵-圆拱直墙型",
            water_depth=1.4,
        ),
        _make_node(
            "矩形暗涵",
            flow_section="1",
            station=20.0,
            name="下游圆拱暗涵",
            B=2.6,
            H_total=3.0,
            theta_deg=150.0,
            culvert_family_type="暗涵-圆拱直墙型",
            water_depth=1.5,
        ),
    ]

    ref = calc._find_reference_segment_same_section_v2(nodes, 1, 0, 1)

    assert ref is not None
    assert ref["section_family"] == "culvert"
    assert ref["structure_type"] == "暗涵-圆拱直墙型"
    assert ref["structure_height"] == pytest.approx(3.0)


def test_arch_culvert_cross_section_area_uses_arch_formula():
    hyd = HydraulicCalculator(ProjectSettings())
    node = _make_node(
        "矩形暗涵",
        flow_section="1",
        station=0.0,
        name="圆拱暗涵",
        B=2.4,
        H_total=2.8,
        theta_deg=150.0,
        culvert_family_type="暗涵-圆拱直墙型",
        water_depth=1.6,
    )

    expected = hyd._arch_tunnel_area(2.4, 2.8, math.radians(150.0), 1.6)

    assert hyd.get_cross_section_area(node) == pytest.approx(expected)


def test_transition_detection_uses_effective_culvert_family_type():
    calc = WaterProfileCalculator(ProjectSettings())
    upstream = _make_node(
        "矩形暗涵",
        flow_section="1",
        station=0.0,
        name="上游矩形暗涵",
        B=2.6,
        H_total=3.0,
        culvert_family_type="暗涵-矩形",
    )
    downstream = _make_node(
        "矩形暗涵",
        flow_section="1",
        station=20.0,
        name="下游圆拱暗涵",
        B=2.6,
        H_total=3.0,
        theta_deg=140.0,
        culvert_family_type="暗涵-圆拱直墙型",
    )
    upstream.in_out = InOutType.OUTLET
    downstream.in_out = InOutType.INLET

    assert calc._needs_transition(upstream, downstream) is True


def test_building_lengths_use_effective_culvert_family_type():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [
        _make_node(
            "矩形暗涵",
            flow_section="1",
            station=0.0,
            name="圆拱暗涵",
            B=2.4,
            H_total=2.8,
            theta_deg=150.0,
            culvert_family_type="暗涵-圆拱直墙型",
        ),
        _make_node(
            "矩形暗涵",
            flow_section="1",
            station=18.0,
            name="圆拱暗涵",
            B=2.4,
            H_total=2.8,
            theta_deg=150.0,
            culvert_family_type="暗涵-圆拱直墙型",
        ),
    ]

    results = calc.calculate_building_lengths(nodes)

    assert len(results) == 1
    assert results[0]["structure_type"] == "暗涵-圆拱直墙型"
    assert results[0]["length"] == pytest.approx(18.0)
