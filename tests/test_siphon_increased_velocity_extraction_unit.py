# -*- coding: utf-8 -*-
"""倒虹吸加大流速提取策略单元测试。"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "推求水面线"))

from models.data_models import ChannelNode
from models.enums import InOutType, StructureType
from utils.siphon_extractor import SiphonDataExtractor


def _channel_node(*, velocity: float, velocity_inc: float, is_auto: bool = False) -> ChannelNode:
    return ChannelNode(
        name="渠道",
        structure_type=StructureType.MINGQU_TRAPEZOIDAL,
        in_out=InOutType.NORMAL,
        velocity=velocity,
        velocity_increased=velocity_inc,
        water_depth=1.5,
        section_params={"B": 2.0, "m": 1.5},
        is_auto_inserted_channel=is_auto,
    )


def _transition_node() -> ChannelNode:
    return ChannelNode(
        name="渐变段",
        structure_type=StructureType.TRANSITION,
        is_transition=True,
    )


def _siphon_pair(name: str):
    return [
        ChannelNode(name=name, structure_type=StructureType.INVERTED_SIPHON, in_out=InOutType.INLET),
        ChannelNode(name=name, structure_type=StructureType.INVERTED_SIPHON, in_out=InOutType.OUTLET),
    ]


def _extract_one(nodes):
    groups = SiphonDataExtractor.extract_siphons(nodes)
    assert len(groups) == 1
    return groups[0]


def test_extract_increased_velocity_from_real_adjacent_channels():
    siphon_in, siphon_out = _siphon_pair("虹吸A")
    nodes = [
        _channel_node(velocity=1.2, velocity_inc=1.8),
        _transition_node(),
        siphon_in,
        siphon_out,
        _transition_node(),
        _channel_node(velocity=0.9, velocity_inc=1.4),
    ]

    group = _extract_one(nodes)

    assert group.upstream_velocity == 1.2
    assert group.upstream_velocity_increased == 1.8
    assert group.downstream_velocity == 0.9
    assert group.downstream_velocity_increased == 1.4


def test_prefer_real_channel_over_nearer_auto_inserted_channel():
    siphon_in, siphon_out = _siphon_pair("虹吸B")
    nodes = [
        _channel_node(velocity=1.2, velocity_inc=1.8, is_auto=False),  # 更远真实渠道
        _channel_node(velocity=1.1, velocity_inc=0.0, is_auto=True),   # 更近自动连接段
        _transition_node(),
        siphon_in,
        siphon_out,
        _transition_node(),
        _channel_node(velocity=1.0, velocity_inc=0.0, is_auto=True),   # 更近自动连接段
        _channel_node(velocity=0.9, velocity_inc=1.4, is_auto=False),  # 更远真实渠道
    ]

    group = _extract_one(nodes)

    assert group.upstream_velocity == 1.2
    assert group.upstream_velocity_increased == 1.8
    assert group.downstream_velocity == 0.9
    assert group.downstream_velocity_increased == 1.4


def test_fallback_to_auto_inserted_channel_when_real_missing():
    siphon_in, siphon_out = _siphon_pair("虹吸C")
    nodes = [
        _channel_node(velocity=1.1, velocity_inc=1.6, is_auto=True),
        _transition_node(),
        siphon_in,
        siphon_out,
        _transition_node(),
        _channel_node(velocity=1.0, velocity_inc=1.3, is_auto=True),
    ]

    group = _extract_one(nodes)

    assert group.upstream_velocity == 1.1
    assert group.upstream_velocity_increased == 1.6
    assert group.downstream_velocity == 1.0
    assert group.downstream_velocity_increased == 1.3


def test_keep_default_zero_when_no_adjacent_channel_exists():
    siphon_in, siphon_out = _siphon_pair("虹吸D")
    nodes = [
        _transition_node(),
        siphon_in,
        siphon_out,
        _transition_node(),
    ]

    group = _extract_one(nodes)

    assert group.upstream_velocity == 0.0
    assert group.upstream_velocity_increased == 0.0
    assert group.downstream_velocity == 0.0
    assert group.downstream_velocity_increased == 0.0

