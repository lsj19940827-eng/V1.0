# -*- coding: utf-8 -*-
"""
Regression tests for pressure-pipe transition coefficient behavior.

Coverage goals:
1. core.pressure_pipe_calc.calc_total_head_loss:
   - explicit zeta override is honored when > 0
   - non-positive override falls back to form/default lookup
2. core.calculator.WaterProfileCalculator transition node builders:
   - pressure-pipe adjacent transitions reuse siphon transition settings
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from core.calculator import WaterProfileCalculator
from core.pressure_pipe_calc import (
    PIPE_MATERIALS,
    calc_pipe_velocity,
    calc_total_head_loss,
    calc_transition_loss,
    get_transition_zeta,
)
from models.data_models import ChannelNode, ProjectSettings
from models.enums import InOutType, StructureType


def _make_node(structure_name: str, in_out: InOutType, name: str) -> ChannelNode:
    node = ChannelNode()
    node.structure_type = StructureType.from_string(structure_name)
    node.in_out = in_out
    node.name = name
    node.flow = 1.2
    node.flow_section = "FLOW-1"
    node.roughness = 0.014
    node.section_params = {"D": 1.2, "b": 2.0, "m": 1.5}
    node.x = 0.0
    node.y = 0.0
    return node


def test_pressure_pipe_calc_uses_explicit_transition_zeta_override():
    material_key = next(iter(PIPE_MATERIALS.keys()))
    q = 1.6
    d = 1.0
    v_up = 0.55
    v_down = 0.70
    zeta_in = 0.77
    zeta_out = 0.88

    result = calc_total_head_loss(
        name="P-1",
        Q=q,
        D=d,
        material_key=material_key,
        ip_points=[{"x": 0.0, "y": 0.0}, {"x": 120.0, "y": 0.0}],
        upstream_velocity=v_up,
        downstream_velocity=v_down,
        inlet_transition_form="UNKNOWN_FORM",
        outlet_transition_form="UNKNOWN_FORM",
        inlet_transition_zeta=zeta_in,
        outlet_transition_zeta=zeta_out,
    )

    v_pipe = calc_pipe_velocity(q, d)
    expected_in, _ = calc_transition_loss(v_pipe, v_up, zeta_in, is_inlet=True)
    expected_out, _ = calc_transition_loss(v_pipe, v_down, zeta_out, is_inlet=False)

    assert result.inlet_transition_details["zeta"] == pytest.approx(zeta_in, rel=1e-9)
    assert result.outlet_transition_details["zeta"] == pytest.approx(zeta_out, rel=1e-9)
    assert result.inlet_transition_loss == pytest.approx(expected_in, rel=1e-9)
    assert result.outlet_transition_loss == pytest.approx(expected_out, rel=1e-9)


def test_pressure_pipe_calc_falls_back_when_override_not_positive():
    material_key = next(iter(PIPE_MATERIALS.keys()))
    form = "UNKNOWN_FORM"

    result = calc_total_head_loss(
        name="P-2",
        Q=1.4,
        D=1.0,
        material_key=material_key,
        ip_points=[{"x": 0.0, "y": 0.0}, {"x": 80.0, "y": 0.0}],
        upstream_velocity=0.50,
        downstream_velocity=0.60,
        inlet_transition_form=form,
        outlet_transition_form=form,
        inlet_transition_zeta=0.0,
        outlet_transition_zeta=-0.5,
    )

    expected_in = get_transition_zeta(form, is_inlet=True)
    expected_out = get_transition_zeta(form, is_inlet=False)
    assert result.inlet_transition_details["zeta"] == pytest.approx(expected_in, rel=1e-9)
    assert result.outlet_transition_details["zeta"] == pytest.approx(expected_out, rel=1e-9)


def test_create_transition_node_uses_siphon_settings_for_pressure_pipe_adjacency():
    settings = ProjectSettings()
    settings.transition_outlet_form = "NORMAL-OUT"
    settings.transition_outlet_zeta = 0.91
    settings.siphon_transition_outlet_form = "SIPHON-OUT"
    settings.siphon_transition_outlet_zeta = 0.31

    calculator = WaterProfileCalculator(settings)
    prev_node = _make_node("有压管道", InOutType.OUTLET, "P-1")
    next_node = _make_node("隧洞-圆形", InOutType.INLET, "T-1")

    transition = calculator._create_transition_node(prev_node, next_node, "出口")

    assert transition.transition_form == "SIPHON-OUT"
    assert transition.transition_zeta == pytest.approx(0.31, rel=1e-9)


def test_create_transition_node_uses_normal_settings_for_non_pressurized_adjacency():
    settings = ProjectSettings()
    settings.transition_outlet_form = "NORMAL-OUT"
    settings.transition_outlet_zeta = 0.91
    settings.siphon_transition_outlet_form = "SIPHON-OUT"
    settings.siphon_transition_outlet_zeta = 0.31

    calculator = WaterProfileCalculator(settings)
    prev_node = _make_node("隧洞-圆形", InOutType.OUTLET, "T-1")
    next_node = _make_node("渡槽-U形", InOutType.INLET, "A-1")

    transition = calculator._create_transition_node(prev_node, next_node, "出口")

    assert transition.transition_form == "NORMAL-OUT"
    assert transition.transition_zeta == pytest.approx(0.91, rel=1e-9)


def test_create_inlet_and_merged_transition_reuse_siphon_inlet_settings_for_pressure_pipe():
    settings = ProjectSettings()
    settings.transition_inlet_form = "NORMAL-IN"
    settings.transition_inlet_zeta = 0.12
    settings.siphon_transition_inlet_form = "SIPHON-IN"
    settings.siphon_transition_inlet_zeta = 0.42

    calculator = WaterProfileCalculator(settings)
    prev_node = _make_node("明渠-梯形", InOutType.OUTLET, "C-1")
    next_node = _make_node("有压管道", InOutType.INLET, "P-1")

    inlet_transition = calculator._create_inlet_transition_node(next_node)
    merged_transition = calculator._create_merged_transition_node(
        prev_node,
        next_node,
        distance=12.0,
        transition_type="进口",
    )

    assert inlet_transition.transition_form == "SIPHON-IN"
    assert inlet_transition.transition_zeta == pytest.approx(0.42, rel=1e-9)
    assert merged_transition.transition_form == "SIPHON-IN"
    assert merged_transition.transition_zeta == pytest.approx(0.42, rel=1e-9)
