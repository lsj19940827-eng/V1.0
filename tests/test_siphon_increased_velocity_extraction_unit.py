# -*- coding: utf-8 -*-
"""倒虹吸加大流速提取策略单元测试。"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "推求水面线"))

from models.data_models import ChannelNode
from models.enums import InOutType, StructureType
from utils.siphon_extractor import SiphonDataExtractor


def _channel_node(
    *,
    velocity: float,
    velocity_inc: float,
    flow_section: str
) -> ChannelNode:
    return ChannelNode(
        name="渠道",
        structure_type=StructureType.MINGQU_TRAPEZOIDAL,
        in_out=InOutType.NORMAL,
        flow_section=flow_section,
        velocity=velocity,
        velocity_increased=velocity_inc,
        water_depth=1.5,
        section_params={"B": 2.0, "m": 1.5},
    )


def _transition_node(flow_section: str) -> ChannelNode:
    return ChannelNode(
        name="渐变段",
        structure_type=StructureType.TRANSITION,
        flow_section=flow_section,
        is_transition=True,
    )


def _gate_node(flow_section: str) -> ChannelNode:
    return ChannelNode(
        name="节制闸",
        structure_type=StructureType.CHECK_GATE,
        flow_section=flow_section,
        is_diversion_gate=True,
    )


def _siphon_pair(name: str, flow_section: str):
    return [
        ChannelNode(
            name=name,
            structure_type=StructureType.INVERTED_SIPHON,
            in_out=InOutType.INLET,
            flow_section=flow_section
        ),
        ChannelNode(
            name=name,
            structure_type=StructureType.INVERTED_SIPHON,
            in_out=InOutType.OUTLET,
            flow_section=flow_section
        ),
    ]


def _extract_one(nodes):
    groups = SiphonDataExtractor.extract_siphons(nodes)
    assert len(groups) == 1
    return groups[0]


def test_gate_penetration_reads_valid_adjacent_channel_velocity():
    siphon_in, siphon_out = _siphon_pair("虹吸A", "A")
    nodes = [
        _channel_node(velocity=1.2, velocity_inc=1.8, flow_section="A"),
        _gate_node("A"),
        _transition_node("A"),
        siphon_in,
        siphon_out,
        _transition_node("A"),
        _gate_node("A"),
        _channel_node(velocity=0.9, velocity_inc=1.4, flow_section="A"),
    ]

    group = _extract_one(nodes)

    assert group.upstream_velocity == 1.2
    assert group.upstream_velocity_increased == 1.8
    assert group.downstream_velocity == 0.9
    assert group.downstream_velocity_increased == 1.4
    assert group.upstream_velocity_source == "adjacent"
    assert group.downstream_velocity_source == "adjacent"


def test_fallback_to_nearest_same_section_channel_when_scan_hits_boundary():
    siphon_in, siphon_out = _siphon_pair("虹吸B", "A")
    nodes = [
        _channel_node(velocity=1.3, velocity_inc=1.9, flow_section="A"),
        siphon_in,
        siphon_out,
        _transition_node("A"),
        _gate_node("A"),
        _transition_node("A"),
        _channel_node(velocity=2.2, velocity_inc=2.8, flow_section="B"),
    ]

    group = _extract_one(nodes)

    assert group.upstream_velocity == 1.3
    assert group.upstream_velocity_increased == 1.9
    assert group.downstream_velocity == 1.3
    assert group.downstream_velocity_increased == 1.9
    assert group.upstream_velocity_source == "adjacent"
    assert group.downstream_velocity_source == "same_section_nearest_channel_fallback"


def test_keep_missing_when_same_section_has_no_open_channel_and_no_cross_section():
    siphon_in, siphon_out = _siphon_pair("虹吸C", "A")
    nodes = [
        _transition_node("A"),
        siphon_in,
        siphon_out,
        _transition_node("A"),
        _gate_node("A"),
        _channel_node(velocity=2.0, velocity_inc=2.6, flow_section="B"),
    ]

    group = _extract_one(nodes)

    assert group.upstream_velocity == 0.0
    assert group.upstream_velocity_increased == 0.0
    assert group.downstream_velocity == 0.0
    assert group.downstream_velocity_increased == 0.0
    assert group.upstream_velocity_source == "missing"
    assert group.downstream_velocity_source == "missing"


def test_velocity_source_marker_values_cover_adjacent_fallback_and_missing():
    siphon_in, siphon_out = _siphon_pair("虹吸D", "A")
    nodes = [
        _channel_node(velocity=1.1, velocity_inc=1.6, flow_section="A"),
        siphon_in,
        siphon_out,
        _gate_node("A"),
        _transition_node("A"),
        _channel_node(velocity=2.0, velocity_inc=2.6, flow_section="B"),
    ]

    group = _extract_one(nodes)

    assert group.upstream_velocity_source == "adjacent"
    assert group.downstream_velocity_source == "same_section_nearest_channel_fallback"

    siphon_in2, siphon_out2 = _siphon_pair("虹吸E", "C")
    nodes_missing = [
        _transition_node("C"),
        siphon_in2,
        siphon_out2,
        _transition_node("C"),
        _channel_node(velocity=2.1, velocity_inc=2.7, flow_section="D"),
    ]
    group_missing = _extract_one(nodes_missing)

    assert group_missing.upstream_velocity_source == "missing"
    assert group_missing.downstream_velocity_source == "missing"
