# -*- coding: utf-8 -*-
"""末尾闸行高程回推单测。"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "推求水面线"))

from core.hydraulic_calc import HydraulicCalculator
from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType


def _make_node(
    *,
    name,
    structure_type,
    flow_section,
    water_level=0.0,
    water_depth=0.0,
    structure_height=0.0,
    bottom_elevation=0.0,
    top_elevation=0.0,
    is_gate=False,
):
    node = ChannelNode()
    node.name = name
    node.structure_type = structure_type
    node.flow_section = flow_section
    node.water_level = float(water_level)
    node.water_depth = float(water_depth)
    node.structure_height = float(structure_height)
    node.bottom_elevation = float(bottom_elevation)
    node.top_elevation = float(top_elevation)
    node.is_diversion_gate = bool(is_gate)
    return node


def test_terminal_gate_backfill_fills_bottom_and_top_from_same_section_upstream_donor():
    hyd = HydraulicCalculator(ProjectSettings())
    donor = _make_node(
        name="上游明渠",
        structure_type=StructureType.MINGQU_RECTANGULAR,
        flow_section="1",
        water_depth=1.2,
        structure_height=2.5,
    )
    target = _make_node(
        name="末尾泄水闸",
        structure_type=StructureType.DISCHARGE_GATE,
        flow_section="1",
        water_level=358.524,
        is_gate=True,
    )

    details = hyd.apply_terminal_gate_elevation_backfill([donor, target])

    assert details is target.terminal_gate_backfill_details
    assert details["status"] == "success"
    assert target.bottom_elevation == pytest.approx(357.324)
    assert target.top_elevation == pytest.approx(359.824)
    assert details["donor_row"] == 1
    assert details["filled_fields"] == ["bottom_elevation", "top_elevation"]


def test_terminal_gate_backfill_top_only_uses_existing_bottom_without_overwriting_it():
    hyd = HydraulicCalculator(ProjectSettings())
    donor = _make_node(
        name="上游暗涵",
        structure_type=StructureType.RECT_CULVERT,
        flow_section="2",
        water_depth=1.4,
        structure_height=2.2,
    )
    target = _make_node(
        name="末尾节制闸",
        structure_type=StructureType.CHECK_GATE,
        flow_section="2",
        water_level=350.0,
        bottom_elevation=347.8,
        top_elevation=0.0,
        is_gate=True,
    )

    details = hyd.apply_terminal_gate_elevation_backfill([donor, target])

    assert details["status"] == "success"
    assert details["bottom"]["attempted"] is False
    assert target.bottom_elevation == pytest.approx(347.8)
    assert target.top_elevation == pytest.approx(350.0)
    assert details["top"]["success"] is True


def test_terminal_gate_backfill_skips_empty_candidate_and_uses_earlier_valid_donor():
    hyd = HydraulicCalculator(ProjectSettings())
    empty_candidate = _make_node(
        name="最近但无结构高",
        structure_type=StructureType.MINGQU_TRAPEZOIDAL,
        flow_section="3",
        water_depth=1.1,
        structure_height=0.0,
    )
    valid_donor = _make_node(
        name="更上游有效明渠",
        structure_type=StructureType.MINGQU_TRAPEZOIDAL,
        flow_section="3",
        water_depth=1.6,
        structure_height=2.4,
    )
    target = _make_node(
        name="末尾分水闸",
        structure_type=StructureType.DIVERSION_GATE,
        flow_section="3",
        water_level=365.5,
        is_gate=True,
    )

    details = hyd.apply_terminal_gate_elevation_backfill([valid_donor, empty_candidate, target])

    assert details["status"] == "success"
    assert details["donor_row"] == 1
    assert details["donor_name"] == "更上游有效明渠"
    assert target.bottom_elevation == pytest.approx(363.9)


def test_terminal_gate_backfill_does_not_cross_flow_section_and_keeps_fields_empty_when_missing():
    hyd = HydraulicCalculator(ProjectSettings())
    cross_section_donor = _make_node(
        name="其他流量段明渠",
        structure_type=StructureType.MINGQU_RECTANGULAR,
        flow_section="9",
        water_depth=1.3,
        structure_height=2.1,
    )
    target = _make_node(
        name="末尾泄水闸",
        structure_type=StructureType.DISCHARGE_GATE,
        flow_section="4",
        water_level=340.0,
        is_gate=True,
    )

    details = hyd.apply_terminal_gate_elevation_backfill([cross_section_donor, target])

    assert details["status"] == "failed"
    assert target.bottom_elevation == 0.0
    assert target.top_elevation == 0.0
    assert "同流量段上游未找到" in details["failure_reason"]


def test_terminal_gate_backfill_only_applies_to_last_non_transition_gate():
    hyd = HydraulicCalculator(ProjectSettings())
    donor = _make_node(
        name="上游明渠",
        structure_type=StructureType.MINGQU_RECTANGULAR,
        flow_section="5",
        water_depth=1.1,
        structure_height=2.0,
    )
    non_terminal_gate = _make_node(
        name="中间泄水闸",
        structure_type=StructureType.DISCHARGE_GATE,
        flow_section="5",
        water_level=330.0,
        is_gate=True,
    )
    last_regular = _make_node(
        name="末尾明渠",
        structure_type=StructureType.MINGQU_TRAPEZOIDAL,
        flow_section="5",
        water_depth=1.0,
        structure_height=2.0,
        bottom_elevation=328.0,
        top_elevation=330.0,
    )

    details = hyd.apply_terminal_gate_elevation_backfill([donor, non_terminal_gate, last_regular])

    assert details is None
    assert non_terminal_gate.bottom_elevation == 0.0
    assert non_terminal_gate.terminal_gate_backfill_details == {}


def test_terminal_gate_backfill_details_are_serialized_with_channel_node():
    node = _make_node(
        name="末尾泄水闸",
        structure_type=StructureType.DISCHARGE_GATE,
        flow_section="6",
        water_level=355.0,
        bottom_elevation=353.7,
        top_elevation=356.1,
        is_gate=True,
    )
    node.terminal_gate_backfill_details = {
        "attempted": True,
        "status": "success",
        "target_row": 8,
        "donor_row": 6,
        "donor_name": "上游明渠",
    }

    restored = ChannelNode.from_project_dict(node.to_project_dict())

    assert restored.terminal_gate_backfill_details == node.terminal_gate_backfill_details
