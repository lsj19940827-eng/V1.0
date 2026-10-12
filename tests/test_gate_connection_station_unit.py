# -*- coding: utf-8 -*-
"""真实缺口内连接段代表桩号及渐变段长度守恒回归。"""

import copy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from 推求水面线.core.geometry_calc import GeometryCalculator
from 推求水面线.models.data_models import ChannelNode, ProjectSettings
from 推求水面线.models.enums import StructureType


def _real(name, distance=0.0, *, gate=False):
    return ChannelNode(
        name=name,
        structure_type=StructureType.DIVERSION_GATE if gate else StructureType.MINGQU_RECTANGULAR,
        straight_distance=distance,
        x=distance,
        flow_section="1",
        is_diversion_gate=gate,
    )


def _transition(length):
    return ChannelNode(
        is_transition=True, structure_type=StructureType.TRANSITION,
        transition_length=length, stat_length=length,
    )


def _auto(distance=50.0):
    return ChannelNode(
        is_auto_inserted_channel=True,
        structure_type=StructureType.MINGQU_RECTANGULAR,
        x=distance, y=17.0, straight_distance=distance, stat_length=12.34,
    )


def _station_tuple(node):
    return (node.station_ip, node.station_BC, node.station_MC, node.station_EC)


@pytest.mark.parametrize("upstream,downstream,expected", [
    (60.0, 0.0, 80.0),
    (60.0, 10.0, 75.0),
    (10.0, 60.0, 25.0),
    (20.0, 20.0, 50.0),
    (50.0, 0.0, 75.0),
])
def test_connection_center_uses_remaining_entity_and_conserves_each_half(upstream, downstream, expected):
    start, end = _real("左端"), _real("右端", 100.0)
    transition_out, transition_in = _transition(upstream), _transition(downstream)
    auto = _auto()
    nodes = [start, transition_out, auto, transition_in, end]

    GeometryCalculator(ProjectSettings()).calculate_stations(nodes, 0.0)

    assert auto.station_MC == pytest.approx(expected)
    assert auto.station_BC == auto.station_MC == auto.station_EC
    assert transition_out.station_MC == start.station_MC
    assert transition_in.station_MC == auto.station_MC
    assert transition_in.station_BC == transition_in.station_EC == auto.station_MC
    first_ordinary = auto.station_MC - start.station_MC - upstream
    last_ordinary = end.station_MC - auto.station_MC - downstream
    assert first_ordinary == pytest.approx(last_ordinary)
    assert first_ordinary + last_ordinary == pytest.approx(100.0 - upstream - downstream)
    assert _station_tuple(end) == pytest.approx((100.0, 100.0, 100.0, 100.0))


def test_only_connection_without_transition_uses_entity_midpoint():
    start, auto, end = _real("左端"), _auto(15.0), _real("右端", 100.0)
    GeometryCalculator(ProjectSettings()).calculate_stations([start, auto, end], 200.0)

    assert auto.station_MC == 250.0
    assert auto.station_ip == start.station_ip == 200.0
    assert end.station_ip == end.station_MC == 300.0


@pytest.mark.parametrize("gate_on_left", [False, True])
def test_gate_approach_and_departure_share_connection_length_rule(gate_on_left):
    start = _real("闸前或闸", gate=gate_on_left)
    end = _real("闸或闸后", 100.0, gate=not gate_on_left)
    auto = _auto()
    transition = _transition(60.0)
    nodes = [start, auto, transition, end] if gate_on_left else [start, transition, auto, end]

    GeometryCalculator(ProjectSettings()).calculate_stations(nodes, 4000.0)

    assert auto.station_MC == pytest.approx(4020.0 if gate_on_left else 4080.0)
    assert start.station_MC == 4000.0
    assert end.station_MC == end.station_ip == 4100.0


@pytest.mark.parametrize("distance,upstream,downstream,expected", [
    (0.0, 4.0, 4.0, 0.0),
    (100.0, 200.0, 10.0, 100.0),
    (100.0, 60.0, 60.0, 60.0),
    (100.0, float("nan"), -1.0, 50.0),
])
def test_zero_or_invalid_length_keeps_internal_station_inside_real_gap(distance, upstream, downstream, expected):
    start, auto, end = _real("左端"), _auto(), _real("右端", distance)
    transition_out, transition_in = _transition(upstream), _transition(downstream)
    nodes = [start, transition_out, auto, transition_in, end]

    GeometryCalculator(ProjectSettings()).calculate_stations(nodes, 0.0)

    assert auto.station_MC == pytest.approx(expected)
    assert start.station_MC <= auto.station_MC <= end.station_MC
    assert end.station_MC == end.station_ip == distance
    assert auto.stat_length == 12.34
    assert transition_in.transition_length == downstream
    if upstream == upstream:
        assert transition_out.transition_length == upstream


def test_real_stations_and_geometry_remain_identical_and_repeated_calculation_is_stable():
    start, end, following = _real("左端"), _real("右端", 100.0), _real("后续", 120.0)
    start.tangent_length, start.arc_length = 8.0, 5.0
    end.tangent_length, end.arc_length = 6.0, 8.0
    baseline = copy.deepcopy([start, end, following])
    calculator = GeometryCalculator(ProjectSettings())
    calculator.calculate_stations(baseline, 123.456)
    auto = _auto()
    out, incoming = _transition(60.0), _transition(10.0)
    nodes = [start, out, auto, incoming, end, following]
    preserved = [(n.x, n.y, n.straight_distance, n.tangent_length, n.arc_length, n.stat_length) for n in nodes]

    calculator.calculate_stations(nodes, 123.456)
    first_stations = [_station_tuple(n) for n in nodes]
    calculator.calculate_stations(nodes, 123.456)

    for real, original in zip((start, end, following), baseline):
        assert _station_tuple(real) == pytest.approx(_station_tuple(original))
    assert [_station_tuple(n) for n in nodes] == first_stations
    assert [(n.x, n.y, n.straight_distance, n.tangent_length, n.arc_length, n.stat_length) for n in nodes] == preserved
    entity_length = end.station_MC - start.station_MC - out.transition_length - incoming.transition_length
    assert auto.station_MC == pytest.approx(start.station_MC + 60.0 + entity_length / 2.0)
    assert following.station_MC - start.station_MC == pytest.approx(baseline[-1].station_MC - baseline[0].station_MC)


def test_multiple_auto_nodes_keep_existing_positions_without_guessing_subsegments():
    start, first, second, end = _real("左端"), _auto(30.0), _auto(70.0), _real("右端", 100.0)
    GeometryCalculator(ProjectSettings()).calculate_stations([start, first, second, end], 0.0)

    assert first.station_MC == 30.0
    assert second.station_MC == 70.0
    assert end.station_ip == end.station_MC == 100.0
