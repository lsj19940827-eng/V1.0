import math
import sys
from pathlib import Path

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "倒虹吸水力计算系统"))

from dxf_parser import DxfParser  # noqa: E402
from siphon_hydraulics import HydraulicCore  # noqa: E402
from siphon_models import (  # noqa: E402
    GlobalParameters,
    GradientType,
    PlanFeaturePoint,
    SpatialNode,
    TurnType,
    V2Strategy,
)
from spatial_merger import SpatialMerger  # noqa: E402


_SAMPLE_PLAN_DXF = _PROJECT_ROOT / "蔡家沟倒虹吸测试_倒圆.dxf"


def _sample_params():
    return GlobalParameters(
        Q=4.0,
        v_guess=2.0,
        roughness_n=0.014,
        inlet_type=GradientType.QUARTER_ARC,
        outlet_type=GradientType.QUARTER_ARC,
        v_channel_in=0.0,
        v_pipe_in=0.0,
        v_channel_out=0.0,
        v_pipe_out=0.0,
        xi_inlet=0.15,
        xi_outlet=0.16,
        v2_strategy=V2Strategy.AUTO_PIPE,
    )


def _load_sample_plan_points():
    plan_points, _plan_segments, message = DxfParser.parse_plan_polyline(str(_SAMPLE_PLAN_DXF))
    assert plan_points, message
    return plan_points


def test_plan_geometry_rebuild_preserves_six_decimal_storage_precision():
    line_1_length = 69.109123456
    arc_radius = 4.800123456
    arc_angle_deg = 16.951234567
    arc_angle_rad = math.radians(arc_angle_deg)
    arc_length = arc_radius * arc_angle_rad
    line_2_length = 100.837654321

    p0 = (0.0, 0.0)
    p1 = (line_1_length, 0.0)
    p2 = (line_1_length + 1.23456789, 1.98765432)
    p3 = (p2[0] + line_2_length, p2[1])

    seg_infos = [
        {
            "type": "line",
            "p1": p0,
            "p2": p1,
            "chord": line_1_length,
            "length": line_1_length,
            "dir": DxfParser._get_direction(p0, p1),
            "source_ip_index": 0,
        },
        {
            "type": "arc",
            "p1": p1,
            "p2": p2,
            "chord": math.dist(p1, p2),
            "radius": arc_radius,
            "angle_rad": arc_angle_rad,
            "length": arc_length,
            "dir": DxfParser._get_direction(p1, p2),
            "source_ip_index": 1,
        },
        {
            "type": "line",
            "p1": p2,
            "p2": p3,
            "chord": line_2_length,
            "length": line_2_length,
            "dir": DxfParser._get_direction(p2, p3),
            "source_ip_index": 2,
        },
    ]

    plan_points, plan_segments, total_length = DxfParser._build_plan_geometry_from_seg_infos(seg_infos)

    assert plan_points[1].chainage == pytest.approx(round(line_1_length, 6), abs=1e-9)
    assert plan_points[1].turn_radius == pytest.approx(round(arc_radius, 6), abs=1e-9)
    assert plan_points[1].turn_angle == pytest.approx(round(arc_angle_deg, 6), abs=1e-9)
    assert plan_points[1].azimuth_meas_deg == pytest.approx(
        round(DxfParser._compute_measurement_azimuth(p2[0] - p1[0], p2[1] - p1[1]), 6),
        abs=1e-9,
    )
    assert plan_segments[0].length == pytest.approx(round(line_1_length, 6), abs=1e-9)
    assert plan_segments[1].length == pytest.approx(round(arc_length, 6), abs=1e-9)
    assert plan_segments[1].radius == pytest.approx(round(arc_radius, 6), abs=1e-9)
    assert plan_segments[1].angle == pytest.approx(round(arc_angle_deg, 6), abs=1e-9)
    assert total_length == pytest.approx(round(line_1_length + arc_length + line_2_length, 6), abs=1e-9)


def test_turn_node_tagging_uses_six_decimal_chainage_matching():
    nodes = [
        SpatialNode(chainage=10.123444),
        SpatialNode(chainage=10.123445),
    ]
    plan_points = [
        PlanFeaturePoint(
            chainage=10.123444,
            x=0.0,
            y=0.0,
            azimuth_meas_deg=90.123456,
            turn_radius=4.800123,
            turn_angle=16.951234,
            turn_type=TurnType.ARC,
        ),
        PlanFeaturePoint(
            chainage=10.123445,
            x=1.0,
            y=0.0,
            azimuth_meas_deg=91.654321,
            turn_radius=0.0,
            turn_angle=21.504321,
            turn_type=TurnType.FOLD,
        ),
    ]

    SpatialMerger._tag_turn_nodes(nodes, [], [], plan_points, [])

    assert nodes[0].has_plan_turn is True
    assert nodes[0].plan_turn_type == TurnType.ARC
    assert nodes[0].plan_turn_radius == pytest.approx(4.800123, abs=1e-9)
    assert nodes[0].plan_turn_angle == pytest.approx(16.951234, abs=1e-9)

    assert nodes[1].has_plan_turn is True
    assert nodes[1].plan_turn_type == TurnType.FOLD
    assert nodes[1].plan_turn_radius == pytest.approx(0.0, abs=1e-9)
    assert nodes[1].plan_turn_angle == pytest.approx(21.504321, abs=1e-9)


def test_spatial_event_lines_display_three_decimals_while_using_precise_backend_values():
    plan_points = _load_sample_plan_points()
    spatial_result = SpatialMerger.merge_and_compute(plan_points, [], verbose=True)
    counted_events = [
        event
        for event in spatial_result.bend_events
        if math.degrees(event.theta_event) > SpatialMerger.TURN_ANGLE_THRESH
    ]

    expected_lines = [
        (
            f"  [{event.event_type}] s=[{event.s_a:.3f},{event.s_b:.3f}] "
            f"θ={math.degrees(event.theta_event):.3f}° "
            f"R_eff={event.R_eff:.3f}m L={event.L_event:.3f}m"
        )
        for event in counted_events
    ]

    for line in expected_lines:
        assert line in spatial_result.computation_steps

    result = HydraulicCore.execute_calculation(
        _sample_params(),
        [],
        verbose=True,
        plan_feature_points=plan_points,
        longitudinal_nodes=[],
    )
    detail_text = HydraulicCore.format_result(result, show_steps=True)
    expected_hydraulic_fragments = [
        (
            f"s=[{event.s_a:.3f},{event.s_b:.3f}] 空间弯管: "
            f"R_eff={event.R_eff:.3f}m, θ_3D={math.degrees(event.theta_event):.3f}°"
        )
        for event in counted_events
        if event.turn_style == TurnType.ARC and event.R_eff > 0
    ]

    for fragment in expected_hydraulic_fragments:
        assert fragment in detail_text
