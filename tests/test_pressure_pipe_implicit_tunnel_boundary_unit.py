# -*- coding: utf-8 -*-
"""隧洞洞口不重复录入管道行时，拓扑和计损范围的回归检查。"""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "推求水面线"))
from core.calculator import WaterProfileCalculator
from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from utils.pressure_pipe_extractor import PressurePipeDataExtractor
from utils.pressure_pipe_tunnel import iter_internal_tunnel_boundaries, make_pipe_portal_node


def _nodes():
    result = []
    specs = [
        (0, "有压管道", "", InOutType.NORMAL, 0.5),
        (60, "有压管道", "", InOutType.NORMAL, 0.5),
        (100, "隧洞-圆拱直墙型", "罗家湾", InOutType.INLET, 0),
        (300, "隧洞-圆拱直墙型", "罗家湾", InOutType.OUTLET, 0),
        (340, "有压管道", "", InOutType.NORMAL, 0.6),
        (400, "有压管道", "", InOutType.NORMAL, 0.6),
    ]
    for i, (mc, st, name, role, diameter) in enumerate(specs):
        node = ChannelNode()
        node.flow_section = "1"
        node.name, node.in_out = name, role
        node.structure_type = StructureType.from_string(st)
        node.station_MC = node.station_ip = mc
        node.x, node.y = 1000 + mc, 2000
        node.ip_number = i
        node.flow = 0.19
        node.section_params = {"D": diameter, "pipe_material": "HDPE管" if diameter == 0.5 else "球墨铸铁管"}
        if "隧洞" in st:
            node.section_params = {"B": 1.8, "theta_deg": 180}
        result.append(node)
    return result


def _settings():
    settings = ProjectSettings()
    settings.channel_level = "支管"
    return settings


def test_implicit_portals_skip_both_gap_insertions_without_mutating_rows():
    nodes = _nodes()
    before = copy.deepcopy([node.to_dict() for node in nodes])
    calc = WaterProfileCalculator(_settings())
    for left, right in ((1, 2), (3, 4)):
        decision = calc._should_insert_open_channel(nodes[left], nodes[right], nodes)
        assert not decision["need_transition_1"]
        assert not decision["need_transition_2"]
        assert decision["distance"] == 40
    assert [node.to_dict() for node in nodes] == before


def test_inferred_approach_inherits_pipe_parameters_and_keeps_tunnel_geometry():
    nodes = _nodes()
    original_tunnel = copy.deepcopy(nodes[2].section_params)
    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(nodes, _settings())
    approach = next(group for group in groups if group.target_row_index == 2)
    after = next(group for group in groups if group.target_row_index == 4)
    assert approach.identity == "flow1-row3"
    assert approach.upstream_row_index == 1
    assert (approach.segment_start_mc, approach.segment_end_mc) == (60, 100)
    assert approach.diameter == 0.5 and approach.material_key == "HDPE管"
    assert approach.design_flow == 0.19
    assert not approach.has_inlet_transition and not approach.has_outlet_transition
    assert (after.segment_start_mc, after.segment_end_mc) == (300, 340)
    assert after.diameter == 0.6 and after.material_key == "球墨铸铁管"
    assert len({group.route_key for group in groups}) == 1
    assert len(nodes) == 6 and nodes[2].section_params == original_tunnel
    assert nodes[2].structure_type == StructureType.TUNNEL_ARCH


@pytest.mark.parametrize("boundary", ["channel", "flow_change", "named", "inserted"])
def test_explicit_boundaries_are_not_implicitly_extended(boundary):
    nodes = _nodes()
    if boundary == "channel":
        nodes[4].structure_type = StructureType.MINGQU_RECTANGULAR
    elif boundary == "flow_change":
        nodes[4].flow_section = "2"
    elif boundary == "named":
        nodes[1].name = "上游命名管道"
        nodes[4].name = "下游命名管道"
    else:
        nodes[2].is_transition = True
    assert list(iter_internal_tunnel_boundaries(nodes)) == []


def test_existing_duplicate_portal_does_not_add_a_second_approach():
    nodes = _nodes()
    nodes[1].station_MC = nodes[2].station_MC
    nodes[1].x, nodes[1].y = nodes[2].x, nodes[2].y
    groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(nodes, _settings())
    assert all(group.target_row_index != 2 for group in groups)


def test_virtual_portal_does_not_reuse_previous_result_or_ip_position():
    nodes = _nodes()
    nodes[1].pressure_pipe_row_identity = "old-row"
    nodes[1].pressure_pipe_window_override = {"enabled": True, "identity": "old-row"}
    nodes[1].section_params["pressure_pipe_window_override"] = {"enabled": True}
    endpoint = make_pipe_portal_node(nodes[1], nodes[2])
    assert endpoint.station_MC == endpoint.station_ip == 100
    assert endpoint.ip_number == nodes[2].ip_number
    assert endpoint.pressure_pipe_row_identity == ""
    assert endpoint.pressure_pipe_window_override == {}
    assert "pressure_pipe_window_override" not in endpoint.section_params
    assert nodes[1].pressure_pipe_window_override["enabled"]


def test_centimetre_station_tolerance_accepts_rounding_but_rejects_real_gap():
    from utils.pressure_pipe_longitudinal_utils import sample_longitudinal_elevation, clip_longitudinal_nodes_to_range
    profile = [
        {"chainage": 0, "elevation": 100},
        {"chainage": 100.005, "elevation": 99, "profile_gap_after": True},
        {"chainage": 300.005, "elevation": 98},
        {"chainage": 400, "elevation": 97},
    ]
    assert sample_longitudinal_elevation(profile, 300) == 98
    clipped = clip_longitudinal_nodes_to_range(profile, 300, 340)
    assert clipped[0]["elevation"] == 98
    with pytest.raises(ValueError):
        sample_longitudinal_elevation(profile, 299.98)
    with pytest.raises(ValueError, match="空档"):
        clip_longitudinal_nodes_to_range(profile, 299.98, 340)


def test_endpoint_rounding_tolerance_does_not_snap_internal_sample_points():
    from utils.pressure_pipe_longitudinal_utils import sample_longitudinal_elevation
    profile = [
        {"chainage": 0, "elevation": 100},
        {"chainage": 10, "elevation": 90},
        {"chainage": 20, "elevation": 90},
    ]
    assert sample_longitudinal_elevation(profile, 9.995) == pytest.approx(90.005)
