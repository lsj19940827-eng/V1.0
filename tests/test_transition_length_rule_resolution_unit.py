# -*- coding: utf-8 -*-
"""渐变段长度规则、单条覆盖与规则来源保真单元测试。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from 推求水面线.core.hydraulic_calc import HydraulicCalculator
from 推求水面线.models.data_models import ChannelNode, ProjectSettings, TransitionLengthRule
from 推求水面线.models.enums import InOutType, StructureType


def _make_open_channel():
    node = ChannelNode()
    node.flow_section = "1"
    node.name = "上游明渠"
    node.structure_type = StructureType.from_string("明渠-梯形")
    node.section_params = {"B": 2.1, "m": 1.4, "h": 1.3, "A": 5.096, "X": 5.986, "R": 0.851}
    node.water_depth = 1.3
    node.velocity = 1.35
    node.roughness = 0.014
    node.flow = 4.8
    return node


def _make_culvert(name: str = "矩形暗涵1"):
    node = ChannelNode()
    node.flow_section = "1"
    node.name = name
    node.structure_type = StructureType.from_string("矩形暗涵")
    node.in_out = InOutType.INLET
    node.section_params = {"B": 2.05, "H_total": 2.0, "h": 1.3, "A": 2.665, "X": 4.65, "R": 0.573}
    node.water_depth = 1.3
    node.velocity = 1.8
    node.roughness = 0.014
    node.flow = 4.8
    return node


def _make_transition(transition_type: str, *, skip_loss: bool = False):
    node = ChannelNode()
    node.flow_section = "1"
    node.name = "-"
    node.structure_type = StructureType.TRANSITION
    node.is_transition = True
    node.transition_type = transition_type
    node.transition_form = "曲线形反弯扭曲面"
    node.transition_skip_loss = skip_loss
    node.roughness = 0.014
    node.flow = 4.8
    return node


def _make_settings(rule: TransitionLengthRule | None = None):
    settings = ProjectSettings()
    if rule is not None:
        settings.transition_length_rules = [rule]
    return settings


def _get_formula_length(transition_type: str) -> float:
    calc = HydraulicCalculator(ProjectSettings())
    prev_node = _make_open_channel()
    next_node = _make_culvert()
    transition = _make_transition(transition_type)
    return calc.calculate_transition_length(transition, prev_node, next_node, [prev_node, transition, next_node])


def test_formula_step_up_and_fixed_rules_resolve_distinct_lengths():
    formula_length = _get_formula_length("进口")

    rule_formula = TransitionLengthRule(
        upstream_structure_type="明渠-梯形",
        downstream_structure_type="矩形暗涵",
        transition_type="进口",
        rule_mode="formula",
    )
    calc_formula = HydraulicCalculator(_make_settings(rule_formula))
    prev_formula = _make_open_channel()
    next_formula = _make_culvert()
    transition_formula = _make_transition("进口")
    details_formula = calc_formula.ensure_transition_length_details(
        transition_formula,
        prev_formula,
        next_formula,
        [prev_formula, transition_formula, next_formula],
    )

    rule_step = TransitionLengthRule(
        upstream_structure_type="明渠-梯形",
        downstream_structure_type="矩形暗涵",
        transition_type="进口",
        rule_mode="step_up",
        step_size_m=1.0,
    )
    calc_step = HydraulicCalculator(_make_settings(rule_step))
    prev_step = _make_open_channel()
    next_step = _make_culvert()
    transition_step = _make_transition("进口")
    details_step = calc_step.ensure_transition_length_details(
        transition_step,
        prev_step,
        next_step,
        [prev_step, transition_step, next_step],
    )

    rule_fixed = TransitionLengthRule(
        upstream_structure_type="明渠-梯形",
        downstream_structure_type="矩形暗涵",
        transition_type="进口",
        rule_mode="fixed",
        fixed_length_m=8.0,
    )
    calc_fixed = HydraulicCalculator(_make_settings(rule_fixed))
    prev_fixed = _make_open_channel()
    next_fixed = _make_culvert()
    transition_fixed = _make_transition("进口")
    details_fixed = calc_fixed.ensure_transition_length_details(
        transition_fixed,
        prev_fixed,
        next_fixed,
        [prev_fixed, transition_fixed, next_fixed],
    )

    assert round(formula_length, 3) == 9.225
    assert round(details_formula["actual_length"], 3) == 9.225
    assert details_formula["source"] == "rule:formula"
    assert details_formula["rule_mode"] == "formula"

    assert details_step["formula_length"] == formula_length
    assert details_step["actual_length"] == 10.0
    assert details_step["source"] == "rule:step_up"
    assert details_step["rule_mode"] == "step_up"
    assert details_step["rule_value"] == 1.0

    assert details_fixed["formula_length"] == formula_length
    assert details_fixed["actual_length"] == 8.0
    assert details_fixed["source"] == "rule:fixed"
    assert details_fixed["rule_mode"] == "fixed"
    assert "组合规则长度小于公式/规范值" in details_fixed["warning"]


def test_same_structure_pair_inlet_and_outlet_rules_apply_independently():
    settings = ProjectSettings()
    settings.transition_length_rules = [
        TransitionLengthRule(
            upstream_structure_type="明渠-梯形",
            downstream_structure_type="矩形暗涵",
            transition_type="进口",
            rule_mode="step_up",
            step_size_m=1.0,
        ),
        TransitionLengthRule(
            upstream_structure_type="矩形暗涵",
            downstream_structure_type="明渠-梯形",
            transition_type="出口",
            rule_mode="fixed",
            fixed_length_m=14.0,
        ),
    ]
    calc = HydraulicCalculator(settings)

    upstream_channel = _make_open_channel()
    downstream_culvert = _make_culvert()
    inlet_transition = _make_transition("进口")
    inlet_details = calc.ensure_transition_length_details(
        inlet_transition,
        upstream_channel,
        downstream_culvert,
        [upstream_channel, inlet_transition, downstream_culvert],
    )

    upstream_culvert = _make_culvert("矩形暗涵2")
    upstream_culvert.in_out = InOutType.OUTLET
    downstream_channel = _make_open_channel()
    downstream_channel.name = "下游明渠"
    outlet_transition = _make_transition("出口")
    outlet_details = calc.ensure_transition_length_details(
        outlet_transition,
        upstream_culvert,
        downstream_channel,
        [upstream_culvert, outlet_transition, downstream_channel],
    )

    assert inlet_details["source"] == "rule:step_up"
    assert inlet_details["actual_length"] == 10.0
    assert inlet_details["upstream_structure_type"] == "明渠-梯形"
    assert inlet_details["downstream_structure_type"] == "矩形暗涵"

    assert outlet_details["source"] == "rule:fixed"
    assert outlet_details["actual_length"] == 14.0
    assert outlet_details["upstream_structure_type"] == "矩形暗涵"
    assert outlet_details["downstream_structure_type"] == "明渠-梯形"


def test_single_override_smaller_than_formula_warns_and_persists_on_roundtrip():
    calc = HydraulicCalculator(ProjectSettings())
    prev_node = _make_open_channel()
    next_node = _make_culvert()
    transition = _make_transition("进口")
    transition.transition_length_override_m = 7.0

    details = calc.ensure_transition_length_details(
        transition,
        prev_node,
        next_node,
        [prev_node, transition, next_node],
    )

    persisted = ChannelNode.from_project_dict(transition.to_project_dict())

    assert details["actual_length"] == 7.0
    assert details["source"] == "override"
    assert "单条覆盖长度小于公式/规范值" in details["warning"]
    assert persisted.transition_length_override_m == 7.0
    assert persisted.transition_length_source == "override"
    assert "单条覆盖长度小于公式/规范值" in persisted.transition_length_warning


def test_distance_clamped_and_skip_loss_transition_keep_rule_source():
    rule = TransitionLengthRule(
        upstream_structure_type="明渠-梯形",
        downstream_structure_type="矩形暗涵",
        transition_type="进口",
        rule_mode="step_up",
        step_size_m=1.0,
    )
    calc = HydraulicCalculator(_make_settings(rule))

    prev_clamped = _make_open_channel()
    next_clamped = _make_culvert()
    clamped_transition = _make_transition("进口")
    clamped_details = calc.ensure_transition_length_details(
        clamped_transition,
        prev_clamped,
        next_clamped,
        [prev_clamped, clamped_transition, next_clamped],
        actual_length=5.0,
        preserve_existing_length=True,
    )

    prev_skip = _make_open_channel()
    next_skip = _make_culvert("矩形暗涵3")
    skip_transition = _make_transition("进口", skip_loss=True)
    skip_transition.transition_length = 5.0
    loss = calc.calculate_transition_loss(
        skip_transition,
        prev_skip,
        next_skip,
        [prev_skip, skip_transition, next_skip],
    )

    assert clamped_details["source"] == "rule:step_up"
    assert clamped_details["uses_existing_length"] is True
    assert clamped_details["actual_length"] == 5.0
    assert "最终采用长度受可用里程约束已压缩" in clamped_details["warning"]

    assert loss == 0.0
    assert skip_transition.transition_length_source == "rule:step_up"
    assert skip_transition.transition_length_calc_details["source"] == "rule:step_up"
    assert skip_transition.transition_length_calc_details["actual_length"] == 5.0
    assert "最终采用长度受可用里程约束已压缩" in skip_transition.transition_length_calc_details["warning"]
