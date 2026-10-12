# -*- coding: utf-8 -*-
"""点闸来流区间水损、连续床面与实际/设计水深的独立回归。"""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "推求水面线"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from 推求水面线.core.calculator import WaterProfileCalculator
from 推求水面线.core.hydraulic_calc import HydraulicCalculator
from 推求水面线.models.data_models import ChannelNode, ProjectSettings
from 推求水面线.models.enums import StructureType


def _channel(name, station, *, section="1", depth=1.2, height=2.5, auto=False, flow=2.0):
    return ChannelNode(
        name=name, structure_type=StructureType.MINGQU_RECTANGULAR,
        flow_section=section, flow=flow, x=float(station),
        station_MC=float(station), section_params={"B": 2.0, "h": depth, "m": 0.0},
        water_depth=depth, structure_height=height, slope_i=0.001,
        is_auto_inserted_channel=auto,
    )


def _gate(name, station, *, loss=0.1, section="1"):
    return ChannelNode(
        name=name, structure_type=StructureType.CHECK_GATE,
        flow_section=section, flow=2.0, x=float(station), station_MC=float(station),
        is_diversion_gate=True, head_loss_gate=loss,
        section_params={"gate_head_loss_user_set": True},
    )


def _calculate(nodes, *, start=100.0):
    return WaterProfileCalculator(
        ProjectSettings(start_water_level=start, design_flow=2.0),
    ).calculate_all(nodes)


def _auto_chain():
    # 分水后流量、设计正常水深改变，仍由已经指定的无台阶床面衔接。
    return [
        _channel("上游渠", 0), _gate("分水闸", 100),
        _channel("下游自动渠", 150, section="2", depth=0.6, height=1.5, auto=True, flow=1.0),
    ]


def test_100_m_approach_friction_and_gate_loss_are_both_in_final_profile():
    upstream, gate, downstream = _calculate([
        _channel("上游", 0), _gate("中间闸", 100), _channel("下游", 200),
    ])

    # 三个真实位置保留100米间距；点状闸不能吞掉到闸前的渠道摩阻。
    assert gate.head_loss_friction == pytest.approx(0.1)
    assert gate.gate_upstream_water_level == pytest.approx(99.9)
    assert gate.gate_downstream_water_level == pytest.approx(99.8)
    assert gate.head_loss_total == pytest.approx(0.2)
    assert downstream.water_level == pytest.approx(99.7)
    assert upstream.water_level - downstream.water_level == pytest.approx(
        sum(node.head_loss_total for node in (gate, downstream)),
    )
    assert gate.bottom_elevation == pytest.approx(98.7)
    assert gate.terminal_gate_backfill_details["bottom"]["method"] == "bed_slope"


def test_zero_gate_loss_still_has_nonzero_channel_approach_loss():
    _, gate = _calculate([_channel("上游", 0), _gate("零损失闸", 100, loss=0.0)])

    assert gate.head_loss_gate == 0.0
    assert gate.head_loss_friction == pytest.approx(0.1)
    assert gate.head_loss_total == pytest.approx(0.1)
    assert gate.gate_upstream_water_level == pytest.approx(99.9)
    assert gate.gate_downstream_water_level == pytest.approx(99.9)


def test_multiple_gates_inherit_hydraulic_approach_from_same_flow_channel():
    nodes = _calculate([
        _channel("参考渠", 0), _gate("闸一", 100), _gate("闸二", 150, loss=0.025),
        _channel("下游", 250),
    ])
    first, second = nodes[1:3]

    assert first.head_loss_friction == pytest.approx(0.1)
    assert second.head_loss_friction == pytest.approx(0.05)
    assert second.gate_upstream_water_level == pytest.approx(99.75)
    assert second.gate_downstream_water_level == pytest.approx(99.725)
    assert [first.bottom_elevation, second.bottom_elevation] == pytest.approx([98.7, 98.65])
    assert nodes[-1].water_level == pytest.approx(99.625)


def test_final_gate_recurrence_counts_approach_reserve_bend_and_separate_transition_once():
    upstream = _channel("上游", 0)
    transition = ChannelNode(is_transition=True, head_loss_transition=0.25)
    gate = _gate("有渐变段的闸", 100)
    # 这是第一轮已经计算好的分项，第二轮只应汇总递推，不能再计算或吞掉它们。
    gate.head_loss_friction = 0.05
    gate.head_loss_bend = 0.03
    gate.head_loss_reserve = 0.02

    HydraulicCalculator(ProjectSettings(start_water_level=100.0)).recalculate_water_levels_with_transition_losses(
        [upstream, transition, gate],
    )

    assert gate.gate_upstream_water_level == pytest.approx(99.65)
    assert gate.gate_downstream_water_level == pytest.approx(99.55)
    assert transition.head_loss_transition == pytest.approx(0.25)
    assert gate.gate_upstream_water_level - gate.gate_downstream_water_level == pytest.approx(0.1)


def test_first_gate_does_not_invent_upstream_boundary_or_apply_its_loss_before_start():
    gate, downstream = _calculate([_gate("起点闸", 0, loss=0.4), _channel("下游", 100)])

    assert gate.gate_upstream_water_level is None
    assert gate.gate_downstream_water_level == pytest.approx(100.0)
    assert downstream.water_level == pytest.approx(99.9)


def test_downstream_auto_bed_follows_gate_slope_and_keeps_design_depth():
    upstream, gate, automatic = _calculate(_auto_chain())

    assert gate.bottom_elevation == pytest.approx(upstream.bottom_elevation - 0.001 * 100)
    assert automatic.bottom_elevation == pytest.approx(gate.bottom_elevation - 0.001 * 50)
    assert automatic.top_elevation == pytest.approx(automatic.bottom_elevation + 1.5)
    assert automatic.water_depth == pytest.approx(0.6)
    metadata = automatic.connection_source_details["gate_bed_profile"]
    assert metadata["normal_water_depth"] == pytest.approx(0.6)
    assert metadata["actual_water_depth"] == pytest.approx(
        automatic.water_level - automatic.bottom_elevation,
    )
    assert metadata["actual_water_depth"] == pytest.approx(1.1)
    assert metadata["actual_water_depth"] != pytest.approx(automatic.water_depth)


def test_changing_gate_loss_changes_actual_depth_but_not_gate_or_auto_bed():
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=100.0, design_flow=2.0))
    nodes = calculator.calculate_all(_auto_chain())
    gate, automatic = nodes[1:]
    previous = (gate.bottom_elevation, gate.top_elevation, automatic.bottom_elevation, automatic.top_elevation)
    old_actual = automatic.connection_source_details["gate_bed_profile"]["actual_water_depth"]
    gate.head_loss_gate = 0.3

    recalculated = calculator.calculate_all(nodes)

    assert recalculated[1] is gate
    assert (gate.bottom_elevation, gate.top_elevation, automatic.bottom_elevation, automatic.top_elevation) == pytest.approx(previous)
    assert gate.gate_upstream_water_level == pytest.approx(99.9)
    assert gate.gate_downstream_water_level == pytest.approx(99.6)
    assert automatic.water_depth == pytest.approx(0.6)
    assert automatic.connection_source_details["gate_bed_profile"]["actual_water_depth"] == pytest.approx(old_actual - 0.2)


def test_independent_manual_gate_bottom_and_top_are_not_overwritten():
    gate = _gate("已有实测高程闸", 100)
    gate.bottom_elevation = 97.123456789
    gate.top_elevation = 102.987654321

    _, calculated = _calculate([_channel("参考渠", 0), gate])

    assert calculated.bottom_elevation == 97.123456789
    assert calculated.top_elevation == 102.987654321


def test_auto_bed_or_top_changed_manually_is_preserved_after_recalculation():
    calculator = WaterProfileCalculator(ProjectSettings(start_water_level=100.0, design_flow=2.0))
    nodes = calculator.calculate_all(_auto_chain())
    automatic = nodes[2]
    automatic.bottom_elevation = 96.123456789
    automatic.top_elevation = 100.987654321
    nodes[1].head_loss_gate = 0.3

    calculator.calculate_all(nodes)

    assert automatic.bottom_elevation == 96.123456789
    assert automatic.top_elevation == 100.987654321


def test_missing_same_flow_geometry_and_water_boundary_remain_unknown():
    foreign = _channel("其他流量段渠", 0, section="9")
    foreign.bottom_elevation = 98.8
    foreign.water_level = 100.0
    gate = _gate("无来源闸", 100, section="1")

    HydraulicCalculator(ProjectSettings()).apply_gate_elevation_backfill([foreign, gate])

    assert gate.bottom_elevation == 0.0
    assert gate.top_elevation == 0.0
    assert gate.terminal_gate_backfill_details["status"] == "failed"
    assert gate.terminal_gate_backfill_details["filled_fields"] == []


@pytest.mark.parametrize("start,expected_bottom", [(1.3, 0.0), (0.5, -0.8)])
def test_confirmed_zero_and_negative_bed_survive_project_roundtrip_and_recalculation(start, expected_bottom):
    nodes = _calculate([_channel("低高程渠", 0), _gate("低高程闸", 100)], start=start)
    gate = nodes[1]

    assert gate.bottom_elevation == pytest.approx(expected_bottom, abs=1e-12)
    assert gate.terminal_gate_backfill_details["bottom"]["success"] is True
    saved = json.loads(json.dumps([node.to_project_dict() for node in nodes], ensure_ascii=False))
    restored = [ChannelNode.from_project_dict(node) for node in saved]
    _calculate(restored, start=start)

    assert restored[1].bottom_elevation == pytest.approx(expected_bottom, abs=1e-12)
    assert restored[1].top_elevation == pytest.approx(expected_bottom + 2.5)
    assert restored[1].terminal_gate_backfill_details["bottom"]["success"] is True


def test_upstream_depth_fallback_uses_gate_before_level_without_bed_geometry():
    reference = _channel("只有设计断面", 0)
    reference.bottom_elevation = 0.0
    reference.water_level = 0.0
    gate = _gate("回退闸", 100)
    gate.gate_upstream_water_level = 100.0
    gate.gate_downstream_water_level = 99.9
    gate.water_level = 99.9

    HydraulicCalculator(ProjectSettings()).apply_gate_elevation_backfill([reference, gate])

    assert gate.bottom_elevation == pytest.approx(98.8)
    assert gate.top_elevation == pytest.approx(101.3)


def test_downstream_geometry_is_extended_back_to_first_gate_station():
    gate = _gate("起点闸", 0)
    gate.gate_downstream_water_level = 100.0
    gate.water_level = 100.0
    reference = _channel("下游已算床面", 100)
    reference.water_level = 99.9
    reference.bottom_elevation = 98.7
    reference.top_elevation = 101.2

    HydraulicCalculator(ProjectSettings()).apply_gate_elevation_backfill([gate, reference])

    assert gate.bottom_elevation == pytest.approx(98.8)
    assert gate.top_elevation == pytest.approx(101.3)
    assert gate.gate_upstream_water_level is None
    assert gate.terminal_gate_backfill_details["bottom"]["method"] == "bed_slope"


def test_bed_slope_extrapolation_retains_precision_until_display():
    reference = _channel("精确床面", 0)
    reference.water_level = 100.0
    reference.bottom_elevation = 98.123456789
    reference.slope_i = 1.0 / 3217.0
    gate = _gate("精确闸", 17.123456789)
    gate.gate_upstream_water_level = 99.9
    gate.gate_downstream_water_level = 99.8
    gate.water_level = 99.8

    HydraulicCalculator(ProjectSettings()).apply_gate_elevation_backfill([reference, gate])

    assert gate.bottom_elevation == pytest.approx(98.123456789 - 17.123456789 / 3217.0, abs=1e-12)
    assert gate.top_elevation == pytest.approx(gate.bottom_elevation + 2.5, abs=1e-12)
