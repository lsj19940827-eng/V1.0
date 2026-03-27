# -*- coding: utf-8 -*-
"""渐变段水头损失完整推导详情单元测试。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from core.hydraulic_calc import HydraulicCalculator
from models.data_models import ChannelNode, ProjectSettings
from models.enums import InOutType, StructureType


def _make_transition_triplet():
    prev_node = ChannelNode()
    prev_node.structure_type = StructureType.from_string("明渠-梯形")
    prev_node.flow_section = "渠道5"
    prev_node.section_params = {"B": 2.4, "m": 1.5, "h": 1.6, "R": 0.78}
    prev_node.velocity = 1.35
    prev_node.water_depth = 1.6
    prev_node.roughness = 0.014

    transition = ChannelNode()
    transition.structure_type = StructureType.TRANSITION
    transition.is_transition = True
    transition.transition_skip_loss = False
    transition.transition_type = "进口"
    transition.transition_form = "曲线形反弯扭曲面"
    transition.flow_section = "渠道5"
    transition.roughness = 0.014

    next_node = ChannelNode()
    next_node.structure_type = StructureType.from_string("隧洞-圆形")
    next_node.name = "隧洞3"
    next_node.in_out = InOutType.INLET
    next_node.section_params = {"D": 2.2, "R": 0.74}
    next_node.velocity = 2.05
    next_node.water_depth = 1.75
    next_node.roughness = 0.014
    next_node.flow_section = "渠道5"

    return prev_node, transition, next_node


def test_transition_loss_details_include_complete_average_method_fields():
    prev_node, transition, next_node = _make_transition_triplet()
    calc = HydraulicCalculator(ProjectSettings())

    total = calc.calculate_transition_loss(
        transition, prev_node, next_node, [prev_node, transition, next_node]
    )

    details = transition.transition_calc_details
    assert total > 0
    assert details
    assert details["R1"] > 0
    assert details["R2"] > 0
    assert details["n"] == 0.014
    assert details["hydraulic_slope_i"] > 0
    assert isinstance(details.get("length_details"), dict)
    assert details["length_details"].get("L_result") == transition.transition_length
    assert details["h_f"] == transition.transition_head_loss_friction
    assert details["total"] == transition.head_loss_transition


def test_transition_loss_inline_details_match_full_derivation_contract():
    prev_node, _, next_node = _make_transition_triplet()
    calc = HydraulicCalculator(ProjectSettings())

    total, details = calc.calculate_transition_loss_inline(
        prev_node, next_node, ProjectSettings()
    )

    assert total > 0
    assert details["R1"] > 0
    assert details["R2"] > 0
    assert details["n"] == 0.014
    assert details["hydraulic_slope_i"] > 0
    assert isinstance(details.get("length_details"), dict)
    assert details["length_details"].get("L_result") == details["length"]
    assert details["h_f"] > 0
    assert details["total"] == total
