# -*- coding: utf-8 -*-
"""表3专项链的距离、边界、能量、工况和结果失效回归。"""

import copy
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "推求水面线"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from core import spillway_steep_chute_adapter as adapter
from models.data_models import ChannelNode
from models.enums import StructureType

KEY = adapter.SPILLWAY_STEEP_CHUTE_PARAM_KEY


def _nodes(stations=(0.0, 20.0, 40.0), slopes=(0.05, 0.05, 0.05), roughness=(0.014, 0.014, 0.014)):
    """输入采用小流量矩形陡槽，避免把普通段均匀流水深用作入口条件。"""
    nodes = []
    for station, slope, n in zip(stations, slopes, roughness):
        node = ChannelNode()
        node.structure_type = StructureType.SPILLWAY_STEEP_CHUTE
        node.flow_section = "1"
        node.flow = node.design_flow = 0.7
        node.slope_i = slope
        node.roughness = n
        node.station_MC = node.x = station
        node.y = 0.0
        node.section_params.update(B=1.0, m=0.0)
        nodes.append(node)
    return nodes


def _calculate(nodes, water_level=100.0):
    groups = adapter.prepare_spillway_steep_chute_groups(nodes)
    adapter.calculate_and_apply_spillway_steep_chute_group(nodes, 0, water_level)
    return next(iter(groups.values()))


def test_coordinate_fallback_uses_cumulative_polyline_and_correct_ip_positions():
    nodes = _nodes(stations=(0.0, 0.0, 0.0))
    for node, xy in zip(nodes, ((0, 0), (30, 0), (30, 40))):
        node.x, node.y = xy
    group = _calculate(nodes)
    assert group["length"] == 70.0
    assert group["subsegments"][0]["node_distances"] == [0.0, 30.0, 70.0]
    assert nodes[0].bottom_elevation - nodes[-1].bottom_elevation == pytest.approx(3.5)
    assert nodes[1].section_params[KEY]["display_point"]["distance_m"] == 30.0


@pytest.mark.parametrize("stations", [(0, 100, 50), (0, 20, 20), (20, 20, 20), (0, 20, 0)])
def test_entered_station_must_be_strictly_increasing(stations):
    nodes = _nodes(stations=stations)
    with pytest.raises(ValueError, match="里程必须.*递增"):
        adapter.prepare_spillway_steep_chute_groups(nodes)


def test_same_slope_roughness_change_creates_independent_segment():
    nodes = _nodes(roughness=(0.014, 0.03, 0.03))
    group = _calculate(nodes)
    assert len(group["subsegments"]) == 2
    assert [item["roughness"] for item in group["chain_subsegments"]] == [0.014, 0.03]
    assert nodes[1].section_params[KEY]["input"]["n"] == 0.03
    assert nodes[-1].water_depth == pytest.approx(0.290405, abs=3e-6)


@pytest.mark.parametrize("water_level", [0.0, -20.0])
def test_zero_or_negative_datum_elevation_is_valid(water_level):
    nodes = _nodes()
    _calculate(nodes, water_level)
    assert nodes[0].water_level == pytest.approx(water_level, abs=2e-6)
    assert nodes[-1].water_level < water_level


def test_water_drop_and_true_energy_loss_are_separate():
    nodes = _nodes()
    _calculate(nodes)
    payload = nodes[-1].section_params[KEY]
    alpha = payload["input"]["alpha_profile"]
    expected = (nodes[0].water_level + alpha * nodes[0].velocity ** 2 / 19.62
                - nodes[-1].water_level - alpha * nodes[-1].velocity ** 2 / 19.62)
    assert payload["chain_head_loss_total"] == pytest.approx(expected, abs=1e-6)
    assert payload["chain_water_level_drop_m"] == pytest.approx(nodes[0].water_level - nodes[-1].water_level)
    assert expected < payload["chain_water_level_drop_m"]
    assert sum(adapter.get_spillway_steep_chute_total_loss(node) for node in nodes) == pytest.approx(expected)


def test_interpolated_ip_recomputes_geometry_and_continuity():
    nodes = _nodes(stations=(0, 7.234, 40))
    for node in nodes:
        node.section_params["m"] = 0.6
    _calculate(nodes)
    node = nodes[1]
    area = node.water_depth * (1.0 + 0.6 * node.water_depth)
    wetted = 1.0 + 2 * node.water_depth * math.sqrt(1.36)
    assert node.section_params["A"] == pytest.approx(area, abs=1e-12)
    assert node.velocity * area == pytest.approx(0.7, abs=1e-12)
    assert node.section_params["R"] == pytest.approx(area / wetted, abs=1e-12)


def test_authoritative_empty_parameters_do_not_resurrect_cached_input():
    nodes = _nodes()
    for node in nodes:
        node.section_params[KEY] = {"advanced_params": {}, "input": {"inlet_head": 0.8, "manual_start_depth": 0.2}}
    _calculate(nodes)
    payload = nodes[0].section_params[KEY]
    assert "inlet_head" not in payload["input"]
    assert "manual_start_depth" not in payload["input"]
    assert payload["params_dirty"] is False


def test_manual_start_and_tailwater_apply_at_chain_ends_only():
    nodes = _nodes(slopes=(0.05, 0.04, 0.04))
    nodes[0].section_params[KEY] = {"advanced_params": {"manual_start_depth": 0.3, "downstream_tailwater_depth": 0.0}}
    _calculate(nodes)
    first, last = nodes[0].section_params[KEY], nodes[-1].section_params[KEY]
    assert nodes[0].water_depth == pytest.approx(0.3)
    assert "downstream_tailwater_depth" not in first["input"]
    assert last["input"]["downstream_tailwater_depth"] == 0.0
    assert last["input"]["manual_start_depth"] != 0.3


def test_increased_flow_keeps_its_own_depth_across_slope_change():
    nodes = _nodes(slopes=(0.05, 0.04, 0.04))
    nodes[0].section_params[KEY] = {"use_increase": True, "Q_increased": 0.91, "advanced_params": {}}
    _calculate(nodes)
    first = nodes[0].section_params[KEY]["result"]["aeration_and_sidewall"]
    last = nodes[-1].section_params[KEY]["result"]["aeration_and_sidewall"]
    assert first["increased_flow_checked"] and last["increased_flow_checked"]
    previous = first["increased_flow_profile_points"][-1]
    following = last["increased_flow_profile_points"][0]
    for key in ("depth_m", "bed_elevation_m", "water_elevation_m", "velocity_ms"):
        # 内核传出的水深保留六位小数，流速由该水深重新计算。
        tolerance = 2e-5 if key == "velocity_ms" else 2e-6
        assert following[key] == pytest.approx(previous[key], abs=tolerance)
    assert following["depth_m"] != nodes[1].water_depth
    assert nodes[-1].structure_height >= last["recommended_sidewall_height_m"]


def test_partial_failure_clears_entire_old_chain_and_does_not_apply_first_segment(monkeypatch):
    nodes = _nodes(slopes=(0.05, 0.04, 0.04))
    _calculate(nodes)
    original = adapter.calculate_spillway_steep_chute
    calls = []

    def fail_second(*args):
        calls.append(args[0]["segment_index"])
        if len(calls) == 2:
            raise ValueError("测试后段边界失败")
        return original(*args)

    monkeypatch.setattr(adapter, "calculate_spillway_steep_chute", fail_second)
    with pytest.raises(ValueError, match="后段边界失败"):
        adapter.calculate_and_apply_spillway_steep_chute_group(nodes, 0, 100.0)
    assert calls == [1, 2]
    for node in nodes:
        assert not node.section_params[KEY]["success"]
        assert "result" not in node.section_params[KEY]
        assert node.water_level == 0.0
        assert adapter.get_spillway_steep_chute_total_loss(node) == 0.0


def test_short_success_profile_cannot_be_clamped_to_requested_length(monkeypatch):
    nodes = _nodes()
    group = next(iter(adapter.prepare_spillway_steep_chute_groups(nodes).values()))["subsegments"][0]
    result, _ = adapter.calculate_spillway_steep_chute(group, 100.0)
    truncated = copy.deepcopy(result)
    truncated["profile_points"] = result["profile_points"][:-1]
    monkeypatch.setattr(adapter, "_load_kernel_calculator", lambda: lambda data: truncated)
    with pytest.raises(ValueError, match="未完整覆盖实际渠长"):
        adapter.calculate_spillway_steep_chute(group, 100.0)


def test_dirty_payload_has_no_loss_even_if_old_output_key_remains():
    node = _nodes()[0]
    node.section_params[KEY] = {"success": True, "params_dirty": True, "role": "outlet", "head_loss_total": 99}
    assert adapter.get_spillway_steep_chute_total_loss(node) == 0.0


def test_geometry_failure_after_success_clears_numerical_results():
    nodes = _nodes()
    _calculate(nodes)
    nodes[1].station_MC = nodes[2].station_MC
    with pytest.raises(ValueError, match="里程必须"):
        adapter.calculate_and_apply_spillway_steep_chute_group(nodes, 0, 100.0)
    assert all(node.water_level == 0 and node.head_loss_total == 0 for node in nodes)
    assert all(not node.section_params[KEY]["success"] for node in nodes)


def test_design_steep_but_increased_mild_removes_whole_chain_wall_conclusion():
    """实际临界坡随流量变化，设计流量可算不能代表加大流量也可顺推。"""
    nodes = _nodes(slopes=(0.00525, 0.05, 0.05))
    nodes[0].section_params[KEY] = {"use_increase": True, "Q_increased": 0.91}
    _calculate(nodes)
    for node in nodes:
        payload = node.section_params[KEY]
        assert payload["success"]
        wall = payload["result"]["aeration_and_sidewall"]
        assert not wall["enabled"] and not wall["increased_flow_checked"]
        assert wall["recommended_sidewall_height_m"] is None
        assert "sidewall_height_m" not in payload["display_point"]
        assert "建议侧墙高度" not in payload["result"]["summary"]
        assert all("sidewall_height_m" not in point for point in payload["result"]["profile"]["points"])
    assert nodes[-1].section_params[KEY]["input"]["increased_flow_boundary_missing"] is True


@pytest.mark.parametrize("supplied_height", [0.0, 0.5, 1.5])
def test_failed_increase_removes_previous_automatic_wall_height(supplied_height):
    nodes = _nodes()
    for node in nodes:
        node.structure_height = supplied_height
    nodes[0].section_params[KEY] = {"use_increase": True, "Q_increased": 0.91}
    _calculate(nodes)
    assert nodes[0].structure_height >= 0.8637
    for node in nodes:
        node.slope_i = 0.00525
    _calculate(nodes)
    assert all(node.structure_height == supplied_height for node in nodes)
    if supplied_height == 0:
        assert all(node.top_elevation == 0 for node in nodes)
    for node in nodes:
        result = node.section_params[KEY]["result"]
        assert "建议侧墙高度" not in result["summary"]
        assert not result["aeration_and_sidewall"]["enabled"]


def test_manual_start_needs_own_increased_boundary_then_accepts_it():
    nodes = _nodes(slopes=(0.05, 0.04, 0.04))
    nodes[0].section_params[KEY] = {"use_increase": True, "Q_increased": 0.91,
                                 "advanced_params": {"manual_start_depth": 0.3}}
    _calculate(nodes)
    assert not nodes[-1].section_params[KEY]["result"]["aeration_and_sidewall"]["enabled"]
    nodes[0].section_params[KEY]["advanced_params"]["increased_flow_start_depth"] = 0.35
    _calculate(nodes)
    wall = nodes[0].section_params[KEY]["result"]["aeration_and_sidewall"]
    assert wall["increased_flow_checked"]
    assert wall["increased_flow_profile_points"][0]["depth_m"] == pytest.approx(0.35)


def test_disabled_increase_ignores_stored_manual_increased_flow():
    nodes = _nodes()
    nodes[0].section_params[KEY] = {"use_increase": False, "advanced_params": {"Q_increased": 0.91}}
    _calculate(nodes)
    assert "Q_increased" not in nodes[0].section_params[KEY]["input"]


@pytest.mark.parametrize("key", ["start_water_level", "start_bed_elevation", "start_station"])
def test_kernel_rejects_nonfinite_datums(key):
    calculate = adapter._load_kernel_calculator()
    result = calculate({"Q": 0.7, "b": 1, "m": 0, "n": 0.014, "i": 0.05, "L": 40, key: float("inf")})
    assert not result["success"]
    assert not result["profile"]["available"]


def test_invalid_design_profile_with_increase_returns_unavailable_without_crash():
    calculate = adapter._load_kernel_calculator()
    result = calculate({"Q": 0.7, "b": 1, "n": 0.014, "i": 0.05, "L": 40,
                        "manual_start_depth": 1.0, "Q_increased": 0.91,
                        "increased_flow_independent_control": True})
    assert not result["profile"]["available"]
    assert not result["aeration_and_sidewall"]["enabled"]
