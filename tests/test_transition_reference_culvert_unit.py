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


@pytest.mark.parametrize("culvert_on_left", [True, False])
def test_adjacent_culvert_precedes_remote_steep_open_channel(culvert_on_left):
    calc = WaterProfileCalculator(ProjectSettings())
    culvert = _make_node(
        "暗涵-矩形", flow_section="1", station=260.7, name="相邻暗涵",
        B=1.6, H_total=1.6, water_depth=1.006, slope_i=1 / 2000,
    )
    tunnel = _make_node("隧洞-圆拱直墙型", flow_section="1", station=373.7, name="隧洞", B=1.8)
    remote = _make_node(
        "明渠-矩形", flow_section="1", station=4795, name="末尾陡坡",
        B=1.6, water_depth=0.114, slope_i=1 / 3.5,
    )
    nodes = ([culvert, tunnel] if culvert_on_left else [tunnel, culvert]) + [remote]
    ref = calc._find_reference_segment_same_section_v2(nodes, 0, 0, 1)
    assert ref["source_name"] == "相邻暗涵"
    assert ref["structure_type"] in {"暗涵-矩形", "矩形暗涵"}
    assert ref["slope_inv"] == 2000
    params = calc._build_open_channel_params_from_reference(ref, "1", 1.5)
    assert params.structure_type == ref["structure_type"]
    assert params.slope_inv == 2000


def _make_tunnel_and_steep_channels():
    tunnel = _make_node("隧洞-圆拱直墙型", flow_section="1", station=0, name="附近隧洞", B=1.8, slope_i=1/2000)
    siphon = _make_node("倒虹吸", flow_section="1", station=10, name="倒虹吸")
    channel = _make_node("明渠-矩形", flow_section="1", station=1000, name="末尾陡坡", B=1.6, water_depth=0.114, slope_i=1/3.5)
    for node in (tunnel, siphon, channel):
        node.flow = 1.5
    return [tunnel, siphon, channel]


def test_steep_channels_borrow_tunnel_slope_keep_open_shape_and_recompute_depth():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = _make_tunnel_and_steep_channels()
    nodes[-1].section_params['h'] = 0.114
    ref = calc._find_reference_segment_same_section_v2(nodes, 0, 0, 1)
    assert ref['structure_type'] == '明渠-矩形'
    assert ref['bottom_width'] == 1.6
    assert ref['slope_inv'] == 2000
    assert ref['slope_borrowed_from_tunnel'] is True
    assert ref['slope_source_name'] == '附近隧洞'
    assert 1.0 < ref['water_depth'] < 1.02
    assert ref['reference_froude'] < 1
    assert nodes[-1].slope_i == 1/3.5
    assert nodes[-1].section_params['h'] == 0.114
    assert nodes[-1].water_depth == 0.114


def test_suitable_open_channel_precedes_nearer_tunnel_and_skips_nearer_steep_channel():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = _make_tunnel_and_steep_channels()
    mild = _make_node('明渠-梯形', flow_section='1', station=2000, name='缓坡明渠', B=2.0, m=1.0, water_depth=1.0, slope_i=1/1500)
    mild.flow = 1.5
    nodes.append(mild)
    ref = calc._find_reference_segment_same_section_v2(nodes, 0, 0, 1)
    assert ref['source_name'] == '缓坡明渠'
    assert ref['slope_inv'] == 1500
    assert not ref['slope_borrowed_from_tunnel']


@pytest.mark.parametrize('froude', [0.999, 1.0, 1.001])
def test_froude_boundary_excludes_critical_and_supercritical_sources(froude):
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = _make_tunnel_and_steep_channels()
    channel = nodes[-1]
    channel.slope_i = 1/1500
    channel.water_depth = (channel.flow**2 / (9.81 * 1.6**2 * froude**2)) ** (1/3)
    assert calc._reference_froude(channel) == pytest.approx(froude)
    ref = calc._find_reference_segment_same_section_v2(nodes, 0, 0, 1)
    assert ref['slope_borrowed_from_tunnel'] == (froude >= 1.0)


def test_no_valid_slope_or_no_open_geometry_requires_manual_input():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = _make_tunnel_and_steep_channels()
    nodes[0].slope_i = 1/3.5
    assert calc._find_reference_segment_same_section_v2(nodes, 0, 0, 1) is None
    nodes[0].slope_i = 1/2000
    assert calc._find_reference_segment_same_section_v2(nodes[:2], 0, 0, 1) is None


def test_short_gap_merged_transition_also_uses_tunnel_fallback_slope():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = _make_tunnel_and_steep_channels()
    nodes[0].in_out = InOutType.OUTLET
    nodes[1].in_out = InOutType.INLET
    nodes[0].water_depth = 0.891
    nodes[0].section_params.update(H_total=2.0, theta_deg=180)
    nodes[0].x, nodes[1].x, nodes[2].x = 100, 110, 1100
    layout = calc._should_insert_open_channel(nodes[0], nodes[1], nodes)
    assert layout['use_merged_transition']
    assert layout['available_length'] == 0
    inserted = calc.identify_and_insert_transitions(nodes)
    merged = inserted[1]
    assert merged.is_transition
    assert merged.slope_i == 1/2000
    assert merged.transition_length <= 10


def test_cross_section_open_reference_is_recomputed_at_target_flow():
    calc = WaterProfileCalculator(ProjectSettings())
    nodes = _make_tunnel_and_steep_channels()
    channel = nodes[-1]
    channel.flow_section = '2'
    channel.flow = 0.5
    channel.slope_i = 1/1500
    channel.water_depth = 1.0
    ref = calc._find_reference_segment_cross_section_v2(nodes, 0, 0, 1)
    assert ref['flow'] == 1.5
    assert ref['flow_section'] == '1'
    assert ref['reference_source_flow_section'] == '2'
    assert ref['reference_froude'] < 1


@pytest.mark.parametrize('culvert_type', ['暗涵-矩形', '暗涵-圆拱直墙型'])
@pytest.mark.parametrize('structure_type', ['倒虹吸', '隧洞-圆拱直墙型'])
def test_adjacent_culvert_family_is_preserved_even_with_available_mild_channel(culvert_type, structure_type):
    calc = WaterProfileCalculator(ProjectSettings())
    culvert = _make_node(culvert_type, flow_section='1', station=0, name='相邻暗涵', B=1.8, H_total=2.5, theta_deg=180, slope_i=1/2000)
    structure = _make_node(structure_type, flow_section='1', station=10, name='建筑物', B=1.8)
    channel = _make_node('明渠-矩形', flow_section='1', station=20, name='缓坡明渠', B=2.0)
    ref = calc._find_reference_segment_same_section_v2([culvert, structure, channel], 0, 0, 1)
    assert ref['section_family'] == 'culvert'
    assert ref['slope_inv'] == 2000
    assert ('圆拱直墙型' in ref['structure_type']) == ('圆拱直墙型' in culvert_type)
    if '圆拱直墙型' in culvert_type:
        assert ref['theta_deg'] == 180
        assert ref['structure_height'] == 2.5


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
