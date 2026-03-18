# -*- coding: utf-8 -*-
"""Regression tests for station calculations with inserted transition rows."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from core.calculator import WaterProfileCalculator
from core.geometry_calc import GeometryCalculator
from models.data_models import ChannelNode, OpenChannelParams, ProjectSettings
from models.enums import StructureType


def _make_profile_node(name, structure_type, x, station_mc, section_params, water_depth):
    node = ChannelNode()
    node.name = name
    node.structure_type = StructureType.from_string(structure_type)
    node.x = float(x)
    node.y = 0.0
    node.station_MC = float(station_mc)
    node.flow_section = "1"
    node.flow = 1.0
    node.roughness = 0.014
    node.slope_i = 1.0 / 3000.0
    node.section_params = dict(section_params)
    node.water_depth = float(water_depth)
    return node


def _assert_station_tuple(node, expected):
    station_ip, station_bc, station_mc, station_ec = expected
    assert node.station_ip == pytest.approx(station_ip)
    assert node.station_BC == pytest.approx(station_bc)
    assert node.station_MC == pytest.approx(station_mc)
    assert node.station_EC == pytest.approx(station_ec)


def test_calculate_stations_keeps_real_nodes_stable_with_transition_and_auto_channel():
    geo_calc = GeometryCalculator(ProjectSettings())

    baseline_start = ChannelNode()
    baseline_end = ChannelNode()
    baseline_end.straight_distance = 100.0

    geo_calc.calculate_stations([baseline_start, baseline_end], 0.0)
    baseline = (
        baseline_end.station_ip,
        baseline_end.station_BC,
        baseline_end.station_MC,
        baseline_end.station_EC,
    )

    start = ChannelNode()

    transition_out = ChannelNode()
    transition_out.is_transition = True

    auto_channel = ChannelNode()
    auto_channel.is_auto_inserted_channel = True
    auto_channel.straight_distance = 50.0

    transition_in = ChannelNode()
    transition_in.is_transition = True

    end = ChannelNode()
    end.straight_distance = 100.0

    geo_calc.calculate_stations(
        [start, transition_out, auto_channel, transition_in, end],
        0.0,
    )

    assert auto_channel.station_MC == pytest.approx(50.0)
    assert auto_channel.station_BC == pytest.approx(50.0)
    assert auto_channel.station_EC == pytest.approx(50.0)
    _assert_station_tuple(end, baseline)


def test_prepare_transitions_and_recalculate_geometry_preserve_real_node_stations():
    calculator = WaterProfileCalculator(ProjectSettings())

    pipe_inlet = _make_profile_node(
        "管道A",
        "有压管道",
        0.0,
        0.0,
        {"D": 1.5},
        2.0,
    )
    pipe_outlet = _make_profile_node(
        "管道A",
        "有压管道",
        50.0,
        50.0,
        {"D": 1.5},
        2.0,
    )
    tunnel_inlet = _make_profile_node(
        "隧洞B",
        "隧洞-圆形",
        150.0,
        150.0,
        {"D": 2.0},
        2.0,
    )
    tunnel_outlet = _make_profile_node(
        "隧洞B",
        "隧洞-圆形",
        200.0,
        200.0,
        {"D": 2.0},
        2.0,
    )
    original_nodes = [pipe_inlet, pipe_outlet, tunnel_inlet, tunnel_outlet]

    calculator.preprocess_nodes(original_nodes)
    calculator.calculate_geometry(original_nodes)
    baseline_by_id = {
        id(node): (node.station_ip, node.station_BC, node.station_MC, node.station_EC)
        for node in original_nodes
    }

    def open_channel_callback(_upstream, _available_length, _prev_struct, _next_struct, flow_section, flow):
        return OpenChannelParams(
            name="-",
            structure_type="明渠-矩形",
            bottom_width=2.0,
            water_depth=1.5,
            side_slope=0.0,
            roughness=0.014,
            slope_inv=3000.0,
            flow=flow,
            flow_section=flow_section,
            structure_height=2.0,
        )

    prepared_nodes = calculator.prepare_transitions(original_nodes, open_channel_callback)

    auto_channels = [node for node in prepared_nodes if node.is_auto_inserted_channel]
    transition_rows = [node for node in prepared_nodes if node.is_transition]
    assert len(auto_channels) == 1
    assert len(transition_rows) == 2
    assert auto_channels[0].station_MC == pytest.approx(100.0)

    for node in original_nodes:
        _assert_station_tuple(node, baseline_by_id[id(node)])

    calculator.calculate_geometry(prepared_nodes)

    assert auto_channels[0].station_MC == pytest.approx(100.0)
    for node in original_nodes:
        _assert_station_tuple(node, baseline_by_id[id(node)])


def test_prepare_transitions_prefers_project_start_station_over_stale_first_row_station():
    settings = ProjectSettings()
    settings.start_station = 10097.309
    calculator = WaterProfileCalculator(settings)

    pipe_inlet = _make_profile_node(
        "管道A",
        "有压管道",
        0.0,
        0.0,
        {"D": 1.5},
        2.0,
    )
    pipe_outlet = _make_profile_node(
        "管道A",
        "有压管道",
        50.0,
        0.0,
        {"D": 1.5},
        2.0,
    )
    tunnel_inlet = _make_profile_node(
        "隧洞B",
        "隧洞-圆形",
        150.0,
        0.0,
        {"D": 2.0},
        2.0,
    )
    tunnel_outlet = _make_profile_node(
        "隧洞B",
        "隧洞-圆形",
        200.0,
        0.0,
        {"D": 2.0},
        2.0,
    )
    original_nodes = [pipe_inlet, pipe_outlet, tunnel_inlet, tunnel_outlet]

    calculator.preprocess_nodes(original_nodes)
    calculator.calculate_geometry(original_nodes)
    baseline_by_id = {
        id(node): (node.station_ip, node.station_BC, node.station_MC, node.station_EC)
        for node in original_nodes
    }

    # 模拟项目加载旧快照后，表3首行桩号文本仍停留在 0 起点。
    original_nodes[0].station_ip = 0.0
    original_nodes[0].station_BC = 0.0
    original_nodes[0].station_MC = 0.0
    original_nodes[0].station_EC = 0.0

    def open_channel_callback(_upstream, _available_length, _prev_struct, _next_struct, flow_section, flow):
        return OpenChannelParams(
            name="-",
            structure_type="明渠-矩形",
            bottom_width=2.0,
            water_depth=1.5,
            side_slope=0.0,
            roughness=0.014,
            slope_inv=3000.0,
            flow=flow,
            flow_section=flow_section,
            structure_height=2.0,
        )

    prepared_nodes = calculator.prepare_transitions(original_nodes, open_channel_callback)

    auto_channels = [node for node in prepared_nodes if node.is_auto_inserted_channel]
    assert len(auto_channels) == 1
    assert prepared_nodes[0].station_MC == pytest.approx(settings.start_station)
    assert auto_channels[0].station_MC == pytest.approx(settings.start_station + 100.0)

    for node in original_nodes:
        _assert_station_tuple(node, baseline_by_id[id(node)])
