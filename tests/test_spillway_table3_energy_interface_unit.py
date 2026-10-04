# -*- coding: utf-8 -*-
"""按总水头守恒验证普通渠段与泄水渠专项链的接口。"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "推求水面线")):
    if path not in sys.path:
        sys.path.insert(0, path)

from core.calculator import WaterProfileCalculator
from core.spillway_steep_chute_adapter import (
    SPILLWAY_STEEP_CHUTE_PARAM_KEY,
    prepare_spillway_steep_chute_groups,
)
from models.data_models import ChannelNode, ProjectSettings
from models.enums import InOutType, StructureType


def _node(station, *, special=False, depth=0.703631051891, alpha=1.0):
    """上游取同一流量的缓坡正常水深，专项段取陡坡。"""
    node = ChannelNode()
    node.flow_section = "1"
    node.structure_type = StructureType.SPILLWAY_STEEP_CHUTE if special else StructureType.from_string("明渠-矩形")
    node.in_out = InOutType.NORMAL
    node.x = station
    node.station_MC = station
    node.flow = node.design_flow = 0.7
    node.roughness = 0.014
    node.slope_i = 0.02 if special else 0.001
    node.water_depth = depth
    node.structure_height = 1.5
    node.section_params.update({
        "B": 1.0, "m": 0.0, "A": depth,
        "X": 1.0 + 2.0 * depth, "R": depth / (1.0 + 2.0 * depth),
        "alpha_profile": alpha,
    })
    return node


def _chain(alpha=1.0):
    return [_node(0.0, alpha=alpha), _node(20.0, special=True), _node(60.0, special=True)]


def _head(node, alpha):
    return node.water_level + alpha * node.velocity ** 2 / (2.0 * 9.81)


@pytest.mark.parametrize("upstream_alpha", [1.0, 1.2])
def test_inlet_and_chain_losses_equal_total_energy_drop(upstream_alpha):
    """入口速度头、上游20m摩阻和陡槽内部耗能共同闭合总能量。"""
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=105.0))
    nodes = calculator.calculate_all(_chain(upstream_alpha))
    upstream, inlet, outlet = [node for node in nodes if not node.is_transition]
    interface = inlet.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY]["inlet_interface"]
    outlet_payload = outlet.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY]
    alpha = outlet_payload["input"]["alpha_profile"]
    assert inlet.head_loss_friction == pytest.approx(0.02)
    assert inlet.head_loss_total == pytest.approx(0.02)
    assert interface["energy_residual_m"] == pytest.approx(0.0, abs=1e-12)
    assert _head(upstream, upstream_alpha) - _head(inlet, alpha) == pytest.approx(0.02, abs=2e-6)
    assert _head(upstream, upstream_alpha) - _head(outlet, alpha) == pytest.approx(
        outlet.head_loss_cumulative, abs=5e-6
    )
    assert outlet_payload["chain_water_level_drop_m"] > outlet_payload["chain_head_loss_total"] + 0.25
    # 用每步平均摩坡独立积分，防止把速度头增长误当作能量损失。
    points = outlet_payload["profile_points"]
    integrated_loss = 0.0
    for left, right in zip(points, points[1:]):
        def friction(point):
            depth = point["depth_m"]
            radius = depth / (1.0 + 2.0 * depth)
            return (0.014 * (0.7 / depth) / radius ** (2.0 / 3.0)) ** 2
        integrated_loss += (right["distance_m"] - left["distance_m"]) * (friction(left) + friction(right)) / 2.0
    assert outlet.head_loss_total == pytest.approx(integrated_loss, abs=1e-5)


def test_transition_loss_is_counted_once_and_second_pass_is_repeatable():
    """渐变段独立行、入口普通区间和专项内部损失各计一次，二轮重算不叠加。"""
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=105.0))
    nodes = _chain()
    transition = ChannelNode()
    transition.is_transition = True
    transition.transition_length = 5.0
    nodes.insert(1, transition)
    prepare_spillway_steep_chute_groups(nodes)
    calculator.hyd_calc._calculate_forward(nodes)
    transition.head_loss_transition = 0.012345
    transition.transition_calc_details = {"total": 0.012345}
    calculator.hyd_calc.recalculate_water_levels_with_transition_losses(nodes)
    calculator._update_total_head_loss(nodes)
    calculator._calculate_cumulative_head_loss(nodes)
    upstream, inlet, outlet = nodes[0], nodes[2], nodes[3]
    interface = inlet.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY]["inlet_interface"]
    assert inlet.head_loss_total == pytest.approx(0.015)
    assert interface["total_head_loss_m"] == pytest.approx(0.027345)
    assert interface["transition_loss_m"] == pytest.approx(transition.head_loss_transition)
    assert _head(upstream, 1.0) - _head(outlet, 1.1) == pytest.approx(outlet.head_loss_cumulative, abs=5e-6)
    before = [(node.water_level, node.bottom_elevation, node.head_loss_total, node.head_loss_cumulative) for node in nodes]
    calculator.hyd_calc.recalculate_water_levels_with_transition_losses(nodes)
    calculator._update_total_head_loss(nodes)
    calculator._calculate_cumulative_head_loss(nodes)
    after = [(node.water_level, node.bottom_elevation, node.head_loss_total, node.head_loss_cumulative) for node in nodes]
    for old, new in zip(before, after):
        assert new == pytest.approx(old, abs=1e-10)


def test_interface_reserve_and_gate_loss_survive_special_result_application():
    """专项结果回填不能抹去入口已填写的附加损失。"""
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=105.0))
    nodes = _chain()
    nodes[1].head_loss_reserve = 0.04
    nodes[1].head_loss_gate = 0.03
    result = calculator.calculate_all(nodes)
    upstream, inlet, outlet = [node for node in result if not node.is_transition]
    assert inlet.head_loss_total == pytest.approx(0.09)
    assert _head(upstream, 1.0) - _head(outlet, 1.1) == pytest.approx(outlet.head_loss_cumulative, abs=5e-6)


@pytest.mark.parametrize("downstream_depth", [0.703631051891, 0.2])
def test_rapid_outlet_cannot_silently_continue_with_ordinary_water_level_rule(downstream_depth):
    """急转缓缺水跃边界须阻止，继续急流也须保留专项水面线计算。"""
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=105.0))
    nodes = _chain() + [_node(80.0, depth=downstream_depth)]
    with pytest.raises(ValueError, match="尚未建立消能或控制断面"):
        calculator.calculate_all(nodes)


def test_second_pass_also_enforces_downstream_boundary():
    """后加普通下游节点时，重算路径不能绕开急流出口检查。"""
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=105.0))
    nodes = calculator.calculate_all(_chain())
    nodes.append(_node(80.0))
    with pytest.raises(ValueError, match="尚未建立消能或控制断面"):
        calculator.hyd_calc.recalculate_water_levels_with_transition_losses(nodes)


def test_special_chain_at_project_start_keeps_prescribed_start_water_level():
    """项目直接从陡槽起算时，设置水位就是专项入口水位。"""
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=105.0))
    nodes = calculator.calculate_all([_node(0.0, special=True), _node(40.0, special=True)])
    assert nodes[0].water_level == pytest.approx(105.0)
    assert nodes[0].head_loss_total == pytest.approx(0.0)
    assert "inlet_interface" not in nodes[0].section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY]


def test_manual_control_depth_is_used_in_interface_velocity_head():
    """显式入口深度和动能系数须同时用于接口与专项内核。"""
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=105.0))
    nodes = _chain()
    nodes[1].section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY] = {
        "advanced_params": {"manual_start_depth": 0.31, "control_depth_mode": "manual", "alpha_profile": 1.3}
    }
    result = calculator.calculate_all(nodes)
    upstream, inlet, outlet = [node for node in result if not node.is_transition]
    interface = inlet.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY]["inlet_interface"]
    assert inlet.water_depth == pytest.approx(0.31)
    assert interface["inlet_velocity_head_m"] == pytest.approx(1.3 * (0.7 / 0.31) ** 2 / (2.0 * 9.81))
    assert _head(upstream, 1.0) - _head(outlet, 1.3) == pytest.approx(outlet.head_loss_cumulative, abs=5e-6)


@pytest.mark.parametrize("split_by_transition", [False, True])
def test_two_adjacent_special_chains_cannot_reset_control_depth(split_by_transition):
    """流量段名或渐变段分行不能凭空在急流中建立第二个临界控制。"""
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=105.0))
    nodes = [_node(station, special=True) for station in (0.0, 40.0, 60.0, 100.0)]
    if split_by_transition:
        transition = ChannelNode()
        transition.is_transition = True
        nodes.insert(2, transition)
    else:
        nodes[2].flow_section = nodes[3].flow_section = "2"
    prepare_spillway_steep_chute_groups(nodes)
    with pytest.raises(ValueError, match="不能重新设定临界水深"):
        calculator.hyd_calc._calculate_forward(nodes)


@pytest.mark.parametrize("structure", [StructureType.INVERTED_SIPHON, StructureType.PRESSURE_PIPE])
def test_pressure_outlet_requires_free_surface_control_before_chute(structure):
    """承压出口节点缺少压力水头边界时不能当作自由水面。"""
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=105.0))
    nodes = _chain()
    nodes[0].structure_type = structure
    prepare_spillway_steep_chute_groups(nodes)
    with pytest.raises(ValueError, match="不能直接作为泄水渠的自由水面控制断面"):
        calculator.hyd_calc._apply_spillway_with_upstream_energy(
            nodes, 0, 1, use_actual_transition_losses=False
        )


def test_upstream_flow_change_requires_diversion_boundary():
    """入口流量变化须有分流控制，不能直接拼接同一水流的能量方程。"""
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=105.0))
    nodes = _chain()
    nodes[0].flow = nodes[0].design_flow = 0.8
    with pytest.raises(ValueError, match="须先明确分流或汇流控制断面"):
        calculator.calculate_all(nodes)
