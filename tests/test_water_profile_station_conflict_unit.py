# -*- coding: utf-8 -*-
"""WaterProfileCalculator 同桩号高程冲突校验单测。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from core.calculator import WaterProfileCalculator
from models.data_models import ChannelNode, ProjectSettings


def _make_node(
    *,
    mc,
    bottom,
    top,
    water,
    ip_no=0,
    name="",
    is_transition=False,
    is_auto_inserted=False,
):
    node = ChannelNode()
    node.station_MC = float(mc)
    node.bottom_elevation = float(bottom)
    node.top_elevation = float(top)
    node.water_level = float(water)
    node.ip_number = int(ip_no)
    node.name = name
    node.is_transition = bool(is_transition)
    node.is_auto_inserted_channel = bool(is_auto_inserted)
    return node


def test_validate_station_conflicts_ignores_transition_and_auto_inserted():
    calc = WaterProfileCalculator(ProjectSettings())
    real = _make_node(mc=100.0, bottom=400.0, top=401.0, water=400.5, ip_no=1)
    transition = _make_node(
        mc=100.0, bottom=450.0, top=451.0, water=450.5, ip_no=2, is_transition=True
    )
    auto_row = _make_node(
        mc=100.0, bottom=460.0, top=461.0, water=460.5, ip_no=3, is_auto_inserted=True
    )

    calc._validate_real_node_station_conflicts([real, transition, auto_row])


def test_validate_station_conflicts_raise_on_non_zero_inconsistent_values():
    calc = WaterProfileCalculator(ProjectSettings())
    n1 = _make_node(mc=120.0, bottom=380.0, top=381.0, water=380.5, ip_no=10, name="A")
    n2 = _make_node(mc=120.0, bottom=381.2, top=381.0, water=380.5, ip_no=11, name="B")

    with pytest.raises(ValueError, match="同桩号高程冲突"):
        calc._validate_real_node_station_conflicts([n1, n2])


def test_calculate_all_enforces_station_conflict_validation(monkeypatch):
    calc = WaterProfileCalculator(ProjectSettings())
    n1 = _make_node(mc=200.0, bottom=360.0, top=361.0, water=360.5, ip_no=20)
    n2 = _make_node(mc=200.0, bottom=362.0, top=361.0, water=360.5, ip_no=21)

    monkeypatch.setattr(calc, "preprocess_nodes", lambda nodes: None)
    monkeypatch.setattr(calc, "identify_and_insert_transitions", lambda nodes, _cb=None: nodes)
    monkeypatch.setattr(calc, "calculate_geometry", lambda nodes: None)
    monkeypatch.setattr(calc, "calculate_hydraulics", lambda nodes: None)
    monkeypatch.setattr(calc, "calculate_transition_losses", lambda nodes: None)
    monkeypatch.setattr(calc, "_update_total_head_loss", lambda nodes: None)
    monkeypatch.setattr(calc.hyd_calc, "recalculate_water_levels_with_transition_losses", lambda nodes: None)
    monkeypatch.setattr(calc.hyd_calc, "apply_siphon_outlet_elevation", lambda nodes: None)
    monkeypatch.setattr(calc, "_calculate_cumulative_head_loss", lambda nodes: None)

    with pytest.raises(ValueError, match="同桩号高程冲突"):
        calc.calculate_all([n1, n2])
