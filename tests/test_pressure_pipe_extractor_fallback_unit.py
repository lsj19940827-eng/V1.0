# -*- coding: utf-8 -*-
"""utils.pressure_pipe_extractor 命名组提取回归测试。"""

import os
import sys
from types import SimpleNamespace

import pytest


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


def _set_plan_station(node, station_mc, x, y):
    node.station_MC = float(station_mc)
    node.x = float(x)
    node.y = float(y)
    return node


def _make_settings(channel_level):
    return SimpleNamespace(channel_level=channel_level)


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


def test_extract_dialog_pipe_groups_includes_unnamed_regular_pressure_pipe_rows_for_xxpipe():
    upstream = _make_node("2", "上游明渠", "明渠-梯形", InOutType.NORMAL, flow=1.8)
    upstream.x = 0.0
    upstream.y = 0.0
    upstream.velocity = 0.9
    upstream.water_depth = 1.3
    upstream.section_params = {"B": 2.2, "m": 1.5}

    named_inlet = _make_node("2", "半兽人", "定向钻", InOutType.INLET, diameter=1.0, flow=1.8)
    named_inlet.x = 10.0
    named_inlet.y = 0.0

    named_outlet = _make_node("2", "半兽人", "定向钻", InOutType.OUTLET, diameter=1.0, flow=1.8)
    named_outlet.x = 20.0
    named_outlet.y = 0.0

    anonymous = _make_node("2", "", "有压管道", InOutType.NORMAL, diameter=1.0, flow=1.8)
    anonymous.x = 30.0
    anonymous.y = 5.0
    anonymous.pressure_pipe_row_identity = "flow2-row4"

    downstream = _make_node("2", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=1.8)
    downstream.x = 45.0
    downstream.y = 5.0
    downstream.velocity = 1.1
    downstream.water_depth = 1.1
    downstream.section_params = {"B": 2.0, "m": 1.2}

    nodes = [upstream, named_inlet, named_outlet, anonymous, downstream]

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        nodes,
        settings=_make_settings("干管"),
    )

    assert [group.display_name for group in groups] == ["半兽人", "流量段2 第4行有压管道"]

    named_group = groups[0]
    assert named_group.group_mode == "named_group"
    assert named_group.name == "半兽人"
    assert named_group.display_name == "半兽人"
    assert named_group.storage_key == "2::半兽人::rows2-3"
    assert named_group.identity == "2::半兽人::rows2-3"
    assert named_group.legacy_identity == "2::半兽人"

    anonymous_group = groups[1]
    assert anonymous_group.group_mode == "unnamed_row_segment"
    assert anonymous_group.name == ""
    assert anonymous_group.display_name == "流量段2 第4行有压管道"
    assert anonymous_group.storage_key == "flow2-row4"
    assert anonymous_group.identity == "flow2-row4"
    assert anonymous_group.target_row_index == 3
    assert anonymous_group.upstream_row_index == 2
    assert anonymous_group.row_indices == [3]
    assert anonymous_group.rows == [anonymous]
    assert len(anonymous_group.ip_points) == 2
    assert anonymous_group.ip_points[0]["x"] == 20.0
    assert anonymous_group.ip_points[1]["x"] == 30.0


def test_extract_dialog_pipe_groups_skips_unnamed_regular_pressure_pipe_rows_for_non_xxpipe():
    upstream = _make_node("3", "上游明渠", "明渠-梯形", InOutType.NORMAL, flow=1.2)
    upstream.x = 0.0
    upstream.y = 0.0

    anonymous = _make_node("3", "", "有压管道", InOutType.NORMAL, diameter=0.8, flow=1.2)
    anonymous.x = 12.0
    anonymous.y = 0.0
    anonymous.pressure_pipe_row_identity = "flow3-row2"

    nodes = [upstream, anonymous]

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        nodes,
        settings=_make_settings("支渠"),
    )

    assert groups == []


def test_extract_dialog_pipe_groups_keeps_named_group_without_route_context_for_noncontinuous_xxqu():
    inlet = _make_node("7", "白马庙", "有压管道", InOutType.INLET, diameter=1.1, flow=0.72)
    inlet.x = 0.0
    inlet.y = 0.0

    outlet = _make_node("7", "白马庙", "有压管道", InOutType.OUTLET, diameter=1.1, flow=0.72)
    outlet.x = 18.0
    outlet.y = 0.0

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        [inlet, outlet],
        settings=_make_settings("支渠"),
    )

    assert len(groups) == 1
    group = groups[0]
    assert group.display_name == "白马庙"
    assert group.route_key == ""
    assert group.route_display_name == ""
    assert group.route_member_keys == []
    assert group.route_ip_points == []


def test_extract_dialog_pipe_groups_assigns_route_context_for_continuous_xxqu_run():
    upstream = _set_plan_station(
        _make_node("2", "上游明渠", "明渠-梯形", InOutType.NORMAL, flow=1.8),
        0.0,
        0.0,
        0.0,
    )
    upstream.velocity = 0.9
    upstream.water_depth = 1.3
    upstream.section_params = {"B": 2.2, "m": 1.5}

    drill_inlet = _set_plan_station(
        _make_node("2", "穿路段", "定向钻", InOutType.INLET, diameter=1.0, flow=1.8),
        10.0,
        10.0,
        0.0,
    )
    drill_outlet = _set_plan_station(
        _make_node("2", "穿路段", "定向钻", InOutType.OUTLET, diameter=1.0, flow=1.8),
        30.0,
        30.0,
        0.0,
    )
    tunnel = _set_plan_station(
        _make_node("3", "跨段洞身", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
        50.0,
        50.0,
        2.0,
    )
    anonymous = _set_plan_station(
        _make_node("3", "", "有压管道", InOutType.NORMAL, diameter=1.0, flow=1.8),
        80.0,
        80.0,
        4.0,
    )
    anonymous.pressure_pipe_row_identity = "flow3-row5"

    downstream = _set_plan_station(
        _make_node("3", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=1.8),
        110.0,
        110.0,
        4.0,
    )
    downstream.velocity = 1.1
    downstream.water_depth = 1.0
    downstream.section_params = {"B": 2.0, "m": 1.2}

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        [upstream, drill_inlet, drill_outlet, tunnel, anonymous, downstream],
        settings=_make_settings("支渠"),
    )

    assert [group.display_name for group in groups] == ["穿路段", "流量段3 第5行有压管道"]

    named_group, anonymous_group = groups
    assert named_group.route_key
    assert named_group.route_key == anonymous_group.route_key
    assert named_group.route_start_row_index == 1
    assert named_group.route_end_row_index == 4
    assert named_group.route_start_mc == 10.0
    assert named_group.route_end_mc == 80.0
    assert anonymous_group.segment_start_mc == 80.0
    assert anonymous_group.segment_end_mc == 80.0
    assert "流量段" not in named_group.route_display_name


def test_extract_dialog_pipe_groups_for_branch_channel_ignores_leading_tunnel_in_route_context():
    tunnel_1 = _set_plan_station(
        _make_node("8", "前置隧洞1", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
        0.0,
        0.0,
        0.0,
    )
    tunnel_2 = _set_plan_station(
        _make_node("8", "前置隧洞2", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
        20.0,
        20.0,
        0.0,
    )
    inlet = _set_plan_station(
        _make_node("8", "三清庙", "有压管道", InOutType.INLET, diameter=0.8, flow=0.49),
        40.0,
        40.0,
        2.0,
    )
    outlet = _set_plan_station(
        _make_node("8", "三清庙", "有压管道", InOutType.OUTLET, diameter=0.8, flow=0.49),
        60.0,
        60.0,
        2.0,
    )
    downstream_tunnel = _set_plan_station(
        _make_node("8", "后续洞身", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
        80.0,
        80.0,
        3.0,
    )

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        [tunnel_1, tunnel_2, inlet, outlet, downstream_tunnel],
        settings=_make_settings("支渠"),
    )

    assert len(groups) == 1
    group = groups[0]
    assert group.display_name == "三清庙"
    assert group.route_start_row_index == 2
    assert group.route_end_row_index == 4
    assert group.route_start_mc == 40.0
    assert group.route_end_mc == 80.0
    assert group.route_ip_points[0]["x"] == 40.0
    assert group.route_ip_points[-1]["x"] == 80.0
    assert group.ip_points[0]["station_mc"] == pytest.approx(40.0)
    assert group.ip_points[-1]["station_mc"] == pytest.approx(60.0)
    assert group.route_ip_points[0]["station_mc"] == pytest.approx(40.0)
    assert group.route_ip_points[-1]["station_mc"] == pytest.approx(80.0)


def test_extract_dialog_pipe_groups_for_branch_channel_marks_prefix_segment_metadata():
    prefix_inlet = _set_plan_station(
        _make_node("9", "苟家湾", "有压管道", InOutType.INLET, diameter=0.8, flow=0.49),
        40.0,
        40.0,
        2.0,
    )
    drill_inlet = _set_plan_station(
        _make_node("9", "大石包", "定向钻", InOutType.INLET, diameter=0.8, flow=0.49),
        60.0,
        60.0,
        2.0,
    )
    drill_outlet = _set_plan_station(
        _make_node("9", "大石包", "定向钻", InOutType.OUTLET, diameter=0.8, flow=0.49),
        80.0,
        80.0,
        2.0,
    )
    main_inlet = _set_plan_station(
        _make_node("9", "苟家湾", "有压管道", InOutType.INLET, diameter=0.8, flow=0.49),
        100.0,
        100.0,
        3.0,
    )
    main_outlet = _set_plan_station(
        _make_node("9", "苟家湾", "有压管道", InOutType.OUTLET, diameter=0.8, flow=0.49),
        140.0,
        140.0,
        3.0,
    )

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        [prefix_inlet, drill_inlet, drill_outlet, main_inlet, main_outlet],
        settings=_make_settings("支渠"),
    )

    assert [group.display_name for group in groups] == [
        "苟家湾（前缀段）",
        "大石包",
        "苟家湾（后段）",
    ]
    prefix_group = groups[0]
    assert prefix_group.member_role == "prefix_segment"
    assert prefix_group.prefix_target_row_index == 0
    assert prefix_group.prefix_end_row_index == 1
    assert prefix_group.is_anchor_member is False
    assert prefix_group.should_generate_row_loss is True


def test_extract_dialog_pipe_groups_builds_fallback_identity_for_unnamed_row():
    upstream = _make_node("5", "上游明渠", "明渠-梯形", InOutType.NORMAL, flow=2.0)
    upstream.x = 1.0
    upstream.y = 1.0

    anonymous = _make_node("5", "", "有压管道", InOutType.NORMAL, diameter=1.1, flow=2.0)
    anonymous.x = 9.0
    anonymous.y = 4.0

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        [upstream, anonymous],
        settings=_make_settings("总干管"),
    )

    assert len(groups) == 1
    assert groups[0].name == ""
    assert groups[0].display_name == "流量段5 第2行有压管道"
    assert groups[0].storage_key == "flow5-row2"
    assert groups[0].identity == "flow5-row2"


def test_extract_dialog_pipe_groups_keeps_cross_flow_boundary_out_of_next_flow_section_anonymous_segment():
    drill_inlet = _set_plan_station(
        _make_node("1", "穿路段", "定向钻", InOutType.INLET, diameter=1.0, flow=1.8),
        600.0,
        10.0,
        0.0,
    )
    drill_outlet = _set_plan_station(
        _make_node("1", "穿路段", "定向钻", InOutType.OUTLET, diameter=1.0, flow=1.8),
        700.0,
        30.0,
        0.0,
    )
    anonymous = _set_plan_station(
        _make_node("2", "", "有压管道", InOutType.NORMAL, diameter=1.0, flow=1.2),
        820.0,
        50.0,
        0.0,
    )
    anonymous.pressure_pipe_row_identity = "flow2-row3"
    downstream = _set_plan_station(
        _make_node("2", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=1.2),
        960.0,
        80.0,
        0.0,
    )

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        [drill_inlet, drill_outlet, anonymous, downstream],
        settings=_make_settings("支渠"),
    )

    assert [group.display_name for group in groups] == ["穿路段", "流量段2 第3行有压管道"]
    anonymous_group = groups[1]
    assert anonymous_group.segment_start_mc == 820.0
    assert anonymous_group.segment_end_mc == 820.0


def test_extract_dialog_pipe_groups_downstream_reference_stops_at_first_regular_row():
    upstream = _make_node("6", "上游明渠", "明渠-梯形", InOutType.NORMAL, flow=1.6)
    upstream.x = 0.0
    upstream.y = 0.0
    upstream.velocity = 0.8
    upstream.water_depth = 1.0
    upstream.section_params = {"B": 2.0, "m": 1.0}

    anonymous = _make_node("6", "", "有压管道", InOutType.NORMAL, diameter=0.9, flow=1.6)
    anonymous.x = 10.0
    anonymous.y = 0.0
    anonymous.pressure_pipe_row_identity = "flow6-row2"

    next_pressure_pipe = _make_node("6", "另一段", "顶管", InOutType.INLET, diameter=0.9, flow=1.6)
    next_pressure_pipe.x = 18.0
    next_pressure_pipe.y = 0.0

    later_open_channel = _make_node("6", "后续明渠", "明渠-梯形", InOutType.NORMAL, flow=1.6)
    later_open_channel.x = 30.0
    later_open_channel.y = 0.0
    later_open_channel.velocity = 1.4
    later_open_channel.water_depth = 0.9
    later_open_channel.section_params = {"B": 1.8, "m": 1.2}

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        [upstream, anonymous, next_pressure_pipe, later_open_channel],
        settings=_make_settings("分干管"),
    )

    anonymous_group = groups[0]
    assert anonymous_group.group_mode == "unnamed_row_segment"
    assert anonymous_group.downstream_velocity == 0.0
    assert anonymous_group.downstream_section_params == {}


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


def test_extract_dialog_pipe_groups_assigns_shared_route_context_for_mixed_xxpipe_run():
    upstream = _set_plan_station(
        _make_node("2", "上游明渠", "明渠-梯形", InOutType.NORMAL, flow=1.8),
        0.0,
        0.0,
        0.0,
    )
    upstream.velocity = 0.9
    upstream.water_depth = 1.3
    upstream.section_params = {"B": 2.2, "m": 1.5}

    drill_inlet = _set_plan_station(
        _make_node("2", "穿路段", "定向钻", InOutType.INLET, diameter=1.0, flow=1.8),
        10.0,
        10.0,
        0.0,
    )
    drill_outlet = _set_plan_station(
        _make_node("2", "穿路段", "定向钻", InOutType.OUTLET, diameter=1.0, flow=1.8),
        30.0,
        30.0,
        0.0,
    )
    tunnel_inlet = _set_plan_station(
        _make_node("2", "1#洞段", "隧洞-圆形", InOutType.INLET, flow=0.0),
        50.0,
        50.0,
        3.0,
    )
    tunnel_outlet = _set_plan_station(
        _make_node("2", "1#洞段", "隧洞-圆形", InOutType.OUTLET, flow=0.0),
        80.0,
        80.0,
        3.0,
    )
    anonymous = _set_plan_station(
        _make_node("2", "", "有压管道", InOutType.NORMAL, diameter=1.0, flow=1.8),
        100.0,
        100.0,
        6.0,
    )
    anonymous.pressure_pipe_row_identity = "flow2-row6"

    downstream = _set_plan_station(
        _make_node("2", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=1.8),
        130.0,
        130.0,
        6.0,
    )
    downstream.velocity = 1.1
    downstream.water_depth = 1.1
    downstream.section_params = {"B": 2.0, "m": 1.2}

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        [upstream, drill_inlet, drill_outlet, tunnel_inlet, tunnel_outlet, anonymous, downstream],
        settings=_make_settings("干管"),
    )

    assert [group.display_name for group in groups] == ["穿路段", "流量段2 第6行有压管道"]

    named_group, anonymous_group = groups
    assert named_group.route_key
    assert named_group.route_key == anonymous_group.route_key
    assert named_group.route_start_row_index == 1
    assert named_group.route_end_row_index == 5
    assert named_group.route_start_mc == 10.0
    assert named_group.route_end_mc == 100.0
    assert named_group.segment_start_mc == 10.0
    assert named_group.segment_end_mc == 30.0
    assert anonymous_group.segment_start_mc == 80.0
    assert anonymous_group.segment_end_mc == 100.0
    assert len(named_group.route_ip_points) >= 5
    assert named_group.route_ip_points[0]["x"] == 10.0
    assert named_group.route_ip_points[-1]["x"] == 100.0


def test_extract_dialog_pipe_groups_keeps_route_start_when_tunnel_is_first_member():
    tunnel_inlet = _set_plan_station(
        _make_node("3", "前置隧洞", "隧洞-圆形", InOutType.INLET, flow=0.0),
        0.0,
        0.0,
        0.0,
    )
    tunnel_outlet = _set_plan_station(
        _make_node("3", "前置隧洞", "隧洞-圆形", InOutType.OUTLET, flow=0.0),
        20.0,
        20.0,
        0.0,
    )
    drill_inlet = _set_plan_station(
        _make_node("3", "后续顶管", "顶管", InOutType.INLET, diameter=0.9, flow=1.2),
        40.0,
        40.0,
        5.0,
    )
    drill_outlet = _set_plan_station(
        _make_node("3", "后续顶管", "顶管", InOutType.OUTLET, diameter=0.9, flow=1.2),
        60.0,
        60.0,
        5.0,
    )

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        [tunnel_inlet, tunnel_outlet, drill_inlet, drill_outlet],
        settings=_make_settings("分干管"),
    )

    assert len(groups) == 1
    group = groups[0]
    assert group.route_start_row_index == 0
    assert group.route_end_row_index == 3
    assert group.route_start_mc == 0.0
    assert group.route_end_mc == 60.0
    assert group.segment_start_mc == 40.0
    assert group.segment_end_mc == 60.0
    assert group.route_ip_points[0]["x"] == 0.0
    assert group.route_ip_points[-1]["x"] == 60.0


def test_extract_dialog_pipe_groups_merges_route_across_flow_sections_when_structure_is_continuous():
    upstream = _set_plan_station(
        _make_node("2", "上游明渠", "明渠-梯形", InOutType.NORMAL, flow=1.8),
        0.0,
        0.0,
        0.0,
    )
    upstream.velocity = 0.9
    upstream.water_depth = 1.2
    upstream.section_params = {"B": 2.4, "m": 1.4}

    drill_inlet = _set_plan_station(
        _make_node("2", "穿路段", "定向钻", InOutType.INLET, diameter=1.0, flow=1.8),
        10.0,
        10.0,
        0.0,
    )
    drill_outlet = _set_plan_station(
        _make_node("2", "穿路段", "定向钻", InOutType.OUTLET, diameter=1.0, flow=1.8),
        30.0,
        30.0,
        0.0,
    )
    tunnel = _set_plan_station(
        _make_node("3", "跨段洞身", "隧洞-圆形", InOutType.NORMAL, flow=0.0),
        50.0,
        50.0,
        2.0,
    )
    anonymous = _set_plan_station(
        _make_node("3", "", "有压管道", InOutType.NORMAL, diameter=1.0, flow=1.8),
        80.0,
        80.0,
        4.0,
    )
    anonymous.pressure_pipe_row_identity = "flow3-row5"

    downstream = _set_plan_station(
        _make_node("3", "下游明渠", "明渠-梯形", InOutType.NORMAL, flow=1.8),
        110.0,
        110.0,
        4.0,
    )
    downstream.velocity = 1.1
    downstream.water_depth = 1.0
    downstream.section_params = {"B": 2.0, "m": 1.2}

    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(
        [upstream, drill_inlet, drill_outlet, tunnel, anonymous, downstream],
        settings=_make_settings("干管"),
    )

    assert [group.display_name for group in groups] == ["穿路段", "流量段3 第5行有压管道"]

    named_group, anonymous_group = groups
    assert named_group.route_key
    assert named_group.route_key == anonymous_group.route_key
    assert named_group.route_start_row_index == 1
    assert named_group.route_end_row_index == 4
    assert named_group.route_start_mc == 10.0
    assert named_group.route_end_mc == 80.0
    assert anonymous_group.segment_start_mc == 80.0
    assert anonymous_group.segment_end_mc == 80.0
    assert "流量段" not in named_group.route_display_name
