# -*- coding: utf-8 -*-
"""倒虹吸 donor 提取与跨段重算单元测试。"""

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "推求水面线"))

from models.data_models import ChannelNode
from models.enums import InOutType, StructureType
import utils.siphon_extractor as siphon_extractor_mod
from utils.siphon_extractor import SiphonDataExtractor


def _open_channel_node(
    *,
    name: str = "渠道",
    structure_type=StructureType.MINGQU_TRAPEZOIDAL,
    flow_section: str,
    velocity: float = 1.0,
    velocity_inc: float = 1.2,
    roughness: float = 0.014,
    slope_inv: float = 3000.0,
    water_depth: float = 1.5,
    section_params=None,
    is_transition: bool = False,
    is_auto_inserted_channel: bool = False,
) -> ChannelNode:
    node = ChannelNode(
        name=name,
        structure_type=structure_type,
        in_out=InOutType.NORMAL,
        flow_section=flow_section,
        velocity=velocity,
        velocity_increased=velocity_inc,
        water_depth=water_depth,
        roughness=roughness,
        section_params=section_params or {"B": 2.0, "m": 1.5},
        is_transition=is_transition,
        is_auto_inserted_channel=is_auto_inserted_channel,
    )
    if slope_inv and slope_inv > 0:
        node.slope_i = 1.0 / slope_inv
        node.section_params.setdefault("slope_inv", slope_inv)
    return node


def _transition_node(flow_section: str) -> ChannelNode:
    return ChannelNode(
        name="渐变段",
        structure_type=StructureType.TRANSITION,
        flow_section=flow_section,
        is_transition=True,
    )


def _gate_node(flow_section: str) -> ChannelNode:
    return ChannelNode(
        name="节制闸",
        structure_type=StructureType.CHECK_GATE,
        flow_section=flow_section,
        is_diversion_gate=True,
    )


def _circular_channel_node(
    *,
    name: str = "明渠圆形",
    flow_section: str,
    diameter: float,
    slope_inv: float = 3000.0,
    roughness: float = 0.014,
    velocity: float = 0.5,
    velocity_inc: float = 0.6,
) -> ChannelNode:
    return _open_channel_node(
        name=name,
        structure_type=StructureType.MINGQU_CIRCULAR,
        flow_section=flow_section,
        velocity=velocity,
        velocity_inc=velocity_inc,
        roughness=roughness,
        slope_inv=slope_inv,
        water_depth=max(0.8, round(diameter * 0.7, 3)),
        section_params={"D": diameter},
    )


def _u_channel_node(
    *,
    name: str = "明渠U形",
    flow_section: str,
    radius: float,
    theta_deg: float = 152.0,
    alpha_deg: float = 14.0,
    slope_inv: float = 3000.0,
    roughness: float = 0.014,
) -> ChannelNode:
    return _open_channel_node(
        name=name,
        structure_type=StructureType.MINGQU_U,
        flow_section=flow_section,
        velocity=0.7,
        velocity_inc=0.8,
        roughness=roughness,
        slope_inv=slope_inv,
        water_depth=0.9,
        section_params={
            "R_circle": radius,
            "theta_deg": theta_deg,
            "chamfer_angle": alpha_deg,
        },
    )


def _rect_culvert_node(
    *,
    name: str = "culvert",
    flow_section: str,
    width: float = 1.6,
    height: float = 2.0,
    slope_inv: float = 3000.0,
    roughness: float = 0.014,
    velocity: float = 0.65,
    velocity_inc: float = 0.78,
    water_depth: float = 1.1,
) -> ChannelNode:
    node = ChannelNode(
        name=name,
        structure_type=StructureType.RECT_CULVERT,
        in_out=InOutType.NORMAL,
        flow_section=flow_section,
        velocity=velocity,
        velocity_increased=velocity_inc,
        water_depth=water_depth,
        roughness=roughness,
        section_params={"B": width, "H_total": height},
        structure_height=height,
    )
    if slope_inv and slope_inv > 0:
        node.slope_i = 1.0 / slope_inv
        node.section_params["slope_inv"] = slope_inv
    return node


def _siphon_pair(name: str, flow_section: str, flow: float):
    return [
        ChannelNode(
            name=name,
            structure_type=StructureType.INVERTED_SIPHON,
            in_out=InOutType.INLET,
            flow_section=flow_section,
            flow=flow,
        ),
        ChannelNode(
            name=name,
            structure_type=StructureType.INVERTED_SIPHON,
            in_out=InOutType.OUTLET,
            flow_section=flow_section,
            flow=flow,
        ),
    ]


def _extract_one(nodes):
    groups = SiphonDataExtractor.extract_siphons(nodes)
    assert len(groups) == 1
    return groups[0]


def _siphon_plan_node(ip_number, *, radius=0.0, angle=0.0, explicit=False, text=""):
    node = ChannelNode(
        name="虹吸A",
        structure_type=StructureType.INVERTED_SIPHON,
        flow_section="A",
        flow=1.0,
    )
    node.station_MC = float(ip_number) * 10.0
    node.x = float(ip_number) * 100.0
    node.y = float(ip_number) * 20.0
    node.azimuth = 30.0
    node.turn_radius = radius
    node.turn_angle = angle
    node.ip_number = ip_number
    node.turn_radius_is_explicit = explicit
    node.turn_radius_text = text
    return node


def test_extract_plan_feature_points_marks_only_middle_excel_turn_radius():
    group = siphon_extractor_mod.SiphonGroup(
        name="虹吸A",
        rows=[
            _siphon_plan_node(1, radius=9.0, angle=20.0, explicit=True, text="9"),
            _siphon_plan_node(2, radius=10.0, angle=35.0, explicit=True, text="10"),
            _siphon_plan_node(3, radius=11.0, angle=25.0, explicit=True, text="11"),
        ],
    )

    SiphonDataExtractor._extract_plan_feature_points(group)

    assert group.plan_feature_points[0]["turn_radius"] == 0.0
    assert group.plan_feature_points[0]["turn_radius_is_explicit"] is False
    assert group.plan_feature_points[1]["turn_radius"] == 10.0
    assert group.plan_feature_points[1]["turn_radius_is_explicit"] is True
    assert group.plan_feature_points[1]["turn_radius_text"] == "10"
    assert group.plan_feature_points[1]["turn_radius_source"] == "water_profile"
    assert group.plan_feature_points[2]["turn_radius"] == 0.0
    assert group.plan_feature_points[2]["turn_radius_is_explicit"] is False


def test_extract_siphons_carries_excel_diameter_as_override():
    """倒虹吸自身 D 应作为指定管径传给计算窗口。"""
    inlet, outlet = _siphon_pair("虹吸A", "A", 1.0)
    middle = ChannelNode(
        name="虹吸A",
        structure_type=StructureType.INVERTED_SIPHON,
        flow_section="A",
        flow=1.0,
    )
    inlet.section_params["D"] = 1.6
    middle.section_params["D"] = 1.8
    outlet.section_params["D"] = 1.7

    group = _extract_one([inlet, middle, outlet])

    assert group.diameter_override == 1.6


def test_extract_siphons_ignores_blank_or_zero_diameter_override():
    """空白或 0 的倒虹吸 D 不应触发指定管径。"""
    inlet, outlet = _siphon_pair("虹吸A", "A", 1.0)
    inlet.section_params["D"] = 0.0
    outlet.section_params["D"] = ""

    group = _extract_one([inlet, outlet])

    assert group.diameter_override is None


def test_same_section_upstream_donor_is_reused_for_both_sides():
    siphon_in, siphon_out = _siphon_pair("虹吸A", "A", 1.0)
    nodes = [
        _open_channel_node(flow_section="A", velocity=1.2, velocity_inc=1.8),
        _gate_node("A"),
        _transition_node("A"),
        _open_channel_node(
            flow_section="A",
            velocity=9.9,
            velocity_inc=9.9,
            is_auto_inserted_channel=True,
        ),
        siphon_in,
        siphon_out,
        _transition_node("A"),
        _gate_node("A"),
        _open_channel_node(flow_section="A", velocity=0.9, velocity_inc=1.4),
    ]

    group = _extract_one(nodes)

    assert group.upstream_velocity == pytest.approx(1.2)
    assert group.downstream_velocity == pytest.approx(1.2)
    assert group.upstream_velocity_increased == pytest.approx(1.8)
    assert group.downstream_velocity_increased == pytest.approx(1.8)
    assert group.upstream_velocity_source == "same_section_donor"
    assert group.downstream_velocity_source == "same_section_donor"
    assert group.upstream_velocity_provenance["scan_direction"] == "upstream"
    assert group.downstream_velocity_provenance["scan_direction"] == "upstream"


def test_same_section_downstream_donor_backfills_both_sides_when_upstream_absent():
    siphon_in, siphon_out = _siphon_pair("催龙村", "2", 0.48)
    donor = _circular_channel_node(
        name="催龙村下游明渠",
        flow_section="2",
        diameter=1.3,
        velocity=0.48,
        velocity_inc=0.58,
    )
    nodes = [
        _transition_node("2"),
        siphon_in,
        siphon_out,
        _transition_node("2"),
        donor,
    ]

    group = _extract_one(nodes)

    assert group.upstream_velocity == pytest.approx(0.48)
    assert group.downstream_velocity == pytest.approx(0.48)
    assert group.upstream_velocity_increased == pytest.approx(0.58)
    assert group.downstream_velocity_increased == pytest.approx(0.58)
    assert group.upstream_velocity_source == "same_section_donor"
    assert group.downstream_velocity_source == "same_section_donor"
    assert group.upstream_velocity_provenance["scan_direction"] == "downstream"
    assert group.downstream_velocity_provenance["scan_direction"] == "downstream"


def test_cross_section_circular_donor_redesigns_with_target_flow():
    siphon_in, siphon_out = _siphon_pair("龙王沟", "1", 1.1)
    donor = _circular_channel_node(
        name="下游跨段圆形明渠",
        flow_section="2",
        diameter=1.3,
        slope_inv=3000.0,
        roughness=0.014,
    )
    nodes = [
        _transition_node("1"),
        siphon_in,
        siphon_out,
        _gate_node("1"),
        _transition_node("1"),
        donor,
    ]

    group = _extract_one(nodes)

    assert group.upstream_velocity_source == "cross_section_donor"
    assert group.downstream_velocity_source == "cross_section_donor"
    assert group.upstream_velocity_provenance["redesigned"] is True
    assert group.downstream_velocity_provenance["redesigned"] is True
    assert group.upstream_velocity_provenance["scan_direction"] == "downstream"
    assert group.upstream_velocity_provenance["donor_flow_section"] == "2"
    assert group.upstream_section_D == pytest.approx(1.8, abs=0.05)
    assert group.downstream_section_D == pytest.approx(1.8, abs=0.05)
    assert group.upstream_velocity == pytest.approx(0.789, abs=0.02)
    assert group.downstream_velocity == pytest.approx(0.789, abs=0.02)
    assert group.upstream_velocity_increased == pytest.approx(0.830, abs=0.02)
    assert group.downstream_velocity_increased == pytest.approx(0.830, abs=0.02)


def test_cross_section_resolution_continues_after_failed_donor():
    siphon_in, siphon_out = _siphon_pair("虹吸B", "A", 1.1)
    invalid_donor = _circular_channel_node(
        name="失败donor",
        flow_section="X",
        diameter=1.3,
        slope_inv=0.0,
    )
    valid_donor = _circular_channel_node(
        name="成功donor",
        flow_section="B",
        diameter=1.3,
        slope_inv=3000.0,
    )
    nodes = [
        invalid_donor,
        siphon_in,
        siphon_out,
        valid_donor,
    ]

    group = _extract_one(nodes)

    assert group.upstream_velocity_source == "cross_section_donor"
    assert group.upstream_velocity_provenance["donor_name"] == "成功donor"
    assert group.upstream_velocity_provenance["scan_direction"] == "downstream"
    assert group.upstream_section_D == pytest.approx(1.8, abs=0.05)


def test_missing_is_kept_after_all_donor_candidates_fail():
    siphon_in, siphon_out = _siphon_pair("虹吸C", "A", 1.1)
    invalid_donor = _open_channel_node(
        name="无效明渠",
        flow_section="B",
        velocity=0.0,
        velocity_inc=0.0,
        slope_inv=0.0,
        section_params={"B": 2.0, "m": 1.5},
    )
    nodes = [
        _transition_node("A"),
        siphon_in,
        siphon_out,
        invalid_donor,
    ]

    group = _extract_one(nodes)

    assert group.upstream_velocity_source == "missing"
    assert group.downstream_velocity_source == "missing"
    assert group.upstream_velocity == 0.0
    assert group.downstream_velocity == 0.0
    assert group.upstream_velocity_provenance["level"] == "missing"
    assert group.downstream_velocity_provenance["level"] == "missing"


def test_cross_section_u_shape_redesign_uses_search_wrapper(monkeypatch):
    siphon_in, siphon_out = _siphon_pair("虹吸U", "A", 1.6)
    donor = _u_channel_node(name="U形donor", flow_section="B", radius=0.0)

    calls = []

    def _fake_search(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "R": 1.05,
            "h_design": 0.88,
            "V_design": 0.91,
            "V_increased": 1.02,
        }

    monkeypatch.setattr(siphon_extractor_mod, "search_minimum_u_section_radius", _fake_search)

    group = _extract_one([siphon_in, siphon_out, donor])

    assert calls, "应进入 U 形 donor 的最小半径搜索"
    assert group.upstream_velocity_source == "cross_section_donor"
    assert group.upstream_velocity_provenance["redesigned"] is True
    assert group.upstream_section_R == pytest.approx(1.05)
    assert group.upstream_velocity == pytest.approx(0.91)
    assert group.upstream_velocity_increased == pytest.approx(1.02)


def test_cross_section_u_shape_redesign_failure_keeps_missing(monkeypatch):
    siphon_in, siphon_out = _siphon_pair("虹吸U失败", "A", 1.6)
    donor = _u_channel_node(name="U形失败donor", flow_section="B", radius=0.0)

    monkeypatch.setattr(
        siphon_extractor_mod,
        "search_minimum_u_section_radius",
        lambda **kwargs: {"success": False, "error_message": "not found"},
    )

    group = _extract_one([siphon_in, siphon_out, donor])

    assert group.upstream_velocity_source == "missing"
    assert group.downstream_velocity_source == "missing"


def test_same_section_rect_culvert_donor_is_reused():
    siphon_in, siphon_out = _siphon_pair("culvert-siphon", "A", 1.0)
    donor = _rect_culvert_node(
        name="same-culvert",
        flow_section="A",
        velocity=0.72,
        velocity_inc=0.88,
        width=1.8,
        height=2.2,
    )

    group = _extract_one([donor, siphon_in, siphon_out])

    assert group.upstream_velocity == pytest.approx(0.72)
    assert group.downstream_velocity == pytest.approx(0.72)
    assert group.upstream_velocity_increased == pytest.approx(0.88)
    assert group.downstream_velocity_increased == pytest.approx(0.88)
    assert group.upstream_velocity_source == "same_section_donor"
    assert group.downstream_velocity_source == "same_section_donor"
    assert group.upstream_velocity_provenance["section_family"] == "culvert"
    assert group.downstream_velocity_provenance["section_family"] == "culvert"
    assert group.upstream_velocity_provenance["redesigned"] is False


def test_cross_section_rect_culvert_uses_original_box_when_it_still_works(monkeypatch):
    siphon_in, siphon_out = _siphon_pair("culvert-fixed", "A", 1.2)
    donor = _rect_culvert_node(name="fixed-culvert", flow_section="B", width=1.8, height=2.1)
    quick_calls = []

    monkeypatch.setattr(siphon_extractor_mod, "get_flow_increase_percent", lambda _q: 10.0)

    def _fake_solve(width, height, n_value, slope, target_flow):
        assert width == pytest.approx(1.8)
        assert height == pytest.approx(2.1)
        return (1.05 if target_flow < 1.3 else 1.25), True

    def _fake_outputs(width, height, water_depth, n_value, slope):
        return {"V": 0.76 if water_depth < 1.2 else 0.92}

    def _unexpected_quick_calc(**kwargs):
        quick_calls.append(kwargs)
        return {"success": False}

    monkeypatch.setattr(siphon_extractor_mod, "solve_water_depth_rectangular", _fake_solve)
    monkeypatch.setattr(siphon_extractor_mod, "calculate_rectangular_outputs", _fake_outputs)
    monkeypatch.setattr(siphon_extractor_mod, "quick_calculate_rectangular_culvert", _unexpected_quick_calc)

    group = _extract_one([siphon_in, siphon_out, donor])

    assert not quick_calls
    assert group.upstream_velocity_source == "cross_section_donor"
    assert group.downstream_velocity_source == "cross_section_donor"
    assert group.upstream_velocity == pytest.approx(0.76)
    assert group.upstream_velocity_increased == pytest.approx(0.92)
    assert group.upstream_velocity_provenance["section_family"] == "culvert"
    assert group.upstream_velocity_provenance["redesigned"] is False
    assert group.upstream_velocity_provenance["redesign_mode"] == ""
    assert group.upstream_section_B == pytest.approx(1.8)
    assert group.upstream_section_h == pytest.approx(1.05)
    assert group.upstream_velocity_provenance["dimensions"]["H_total"] == pytest.approx(2.1)


def test_cross_section_rect_culvert_redesign_keeps_bottom_width_and_raises_height(monkeypatch):
    siphon_in, siphon_out = _siphon_pair("culvert-redesign", "A", 1.4)
    donor = _rect_culvert_node(name="resize-culvert", flow_section="B", width=1.7, height=1.9)

    monkeypatch.setattr(
        siphon_extractor_mod,
        "solve_water_depth_rectangular",
        lambda *args, **kwargs: (0.0, False),
    )
    monkeypatch.setattr(
        siphon_extractor_mod,
        "quick_calculate_rectangular_culvert",
        lambda **kwargs: {
            "success": True,
            "B": kwargs["manual_B"],
            "H": 2.6,
            "h_design": 1.45,
            "V_design": 0.84,
            "V_increased": 0.97,
        },
    )

    group = _extract_one([siphon_in, siphon_out, donor])

    assert group.upstream_velocity_source == "cross_section_donor"
    assert group.upstream_velocity == pytest.approx(0.84)
    assert group.upstream_velocity_increased == pytest.approx(0.97)
    assert group.upstream_section_B == pytest.approx(1.7)
    assert group.upstream_section_h == pytest.approx(1.45)
    assert group.upstream_velocity_provenance["dimensions"]["H_total"] == pytest.approx(2.6)
    assert group.upstream_velocity_provenance["section_family"] == "culvert"
    assert group.upstream_velocity_provenance["redesigned"] is True
    assert (
        group.upstream_velocity_provenance["redesign_mode"]
        == "keep_bottom_width_raise_height"
    )


def test_cross_section_rect_culvert_failure_keeps_missing(monkeypatch):
    siphon_in, siphon_out = _siphon_pair("culvert-missing", "A", 1.5)
    donor = _rect_culvert_node(name="failed-culvert", flow_section="B", width=1.5, height=1.6)

    monkeypatch.setattr(
        siphon_extractor_mod,
        "solve_water_depth_rectangular",
        lambda *args, **kwargs: (0.0, False),
    )
    monkeypatch.setattr(
        siphon_extractor_mod,
        "quick_calculate_rectangular_culvert",
        lambda **kwargs: {"success": False, "error_message": "no culvert fit"},
    )

    group = _extract_one([siphon_in, siphon_out, donor])

    assert group.upstream_velocity_source == "missing"
    assert group.downstream_velocity_source == "missing"
    assert group.upstream_velocity == 0.0
    assert group.downstream_velocity == 0.0
    assert group.upstream_velocity_provenance["level"] == "missing"
    assert group.upstream_velocity_provenance["section_family"] == ""
