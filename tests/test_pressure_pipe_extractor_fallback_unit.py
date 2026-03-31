# -*- coding: utf-8 -*-
"""utils.pressure_pipe_extractor 命名组提取回归测试。"""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode
from models.enums import StructureType, InOutType
from utils.pressure_pipe_extractor import PressurePipeDataExtractor


def _make_node(flow_section, name, structure, in_out, diameter=1.2, flow=2.4):
    node = ChannelNode()
    node.flow_section = flow_section
    node.name = name
    node.structure_type = StructureType.from_string(structure)
    node.in_out = in_out
    node.flow = flow
    node.section_params = {
        "D": diameter,
        "in_out_raw": in_out.value if hasattr(in_out, "value") else str(in_out),
    }
    return node


def test_extract_pipes_skips_unnamed_pressure_pipe_rows_and_keeps_named_groups_only():
    nodes = [
        _make_node("1", "", "有压管道", InOutType.INLET),
        _make_node("1", "纯牛马", "隧洞-圆形", InOutType.INLET, flow=0.0),
        _make_node("1", "纯牛马", "隧洞-圆形", InOutType.OUTLET, flow=0.0),
        _make_node("1", "", "有压管道", InOutType.OUTLET),
        _make_node("2", "", "有压管道", InOutType.INLET, diameter=1.0, flow=1.8),
        _make_node("2", "半兽人", "隧洞-圆形", InOutType.INLET, flow=0.0),
        _make_node("2", "半兽人", "隧洞-圆形", InOutType.OUTLET, flow=0.0),
        _make_node("2", "", "有压管道", InOutType.OUTLET, diameter=1.0, flow=1.8),
        _make_node("3", "", "有压管道", InOutType.INLET, diameter=0.8, flow=1.2),
        _make_node("3", "饿了么", "隧洞-圆形", InOutType.INLET, flow=0.0),
        _make_node("3", "饿了么", "隧洞-圆形", InOutType.OUTLET, flow=0.0),
        _make_node("3", "", "有压管道", InOutType.OUTLET, diameter=0.8, flow=1.2),
    ]

    groups = PressurePipeDataExtractor.extract_pipes(nodes)

    assert groups == []


def test_extract_pipes_ignores_incomplete_unnamed_group():
    nodes = [
        _make_node("1", "", "有压管道", InOutType.INLET, diameter=1.4, flow=2.1),
    ]

    groups = PressurePipeDataExtractor.extract_pipes(nodes)

    assert groups == []


def test_extract_pipes_stops_at_adjacent_pressure_pipe_like_nodes():
    nodes = [
        _make_node("2", "上游渠道", "隧洞-圆形", InOutType.INLET, flow=0.0),
        _make_node("2", "", "有压管道", InOutType.INLET, diameter=1.0, flow=1.55),
        _make_node("2", "半兽人", "定向钻", InOutType.INLET, diameter=1.0, flow=1.55),
        _make_node("2", "半兽人", "定向钻", InOutType.OUTLET, diameter=1.0, flow=1.55),
        _make_node("2", "", "有压管道", InOutType.OUTLET, diameter=1.0, flow=1.55),
        _make_node("2", "下游渠道", "隧洞-圆形", InOutType.OUTLET, flow=0.0),
    ]
    nodes[0].velocity = 1.039
    nodes[5].velocity = 1.039

    groups = PressurePipeDataExtractor.extract_pipes(nodes)

    assert len(groups) == 1
    group = groups[0]
    assert group.name == "半兽人"
    assert group.has_inlet_transition is False
    assert group.has_outlet_transition is False
    assert group.inlet_transition_reason == "紧邻有压同类结构，无渐变段"
    assert group.outlet_transition_reason == "紧邻有压同类结构，无渐变段"
    assert group.upstream_velocity == 0.0
    assert group.downstream_velocity == 0.0


def test_extract_pipes_keeps_channel_velocity_when_adjacent_node_is_not_pressure_pipe_like():
    nodes = [
        _make_node("3", "上游渠道", "隧洞-圆形", InOutType.INLET, flow=0.0),
        _make_node("3", "饿了么", "顶管", InOutType.INLET, diameter=0.8, flow=1.2),
        _make_node("3", "饿了么", "顶管", InOutType.OUTLET, diameter=0.8, flow=1.2),
        _make_node("3", "下游渠道", "隧洞-圆形", InOutType.OUTLET, flow=0.0),
    ]
    nodes[0].velocity = 1.039
    nodes[3].velocity = 0.886

    groups = PressurePipeDataExtractor.extract_pipes(nodes)

    assert len(groups) == 1
    group = groups[0]
    assert group.has_inlet_transition is True
    assert group.has_outlet_transition is True
    assert group.upstream_velocity == 1.039
    assert group.downstream_velocity == 0.886
