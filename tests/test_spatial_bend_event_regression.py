import math
import os
import sys
from pathlib import Path

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "倒虹吸水力计算系统"))

from dxf_parser import DxfParser  # noqa: E402
from siphon_coefficients import CoefficientService  # noqa: E402
from siphon_hydraulics import HydraulicCore  # noqa: E402
from siphon_models import (  # noqa: E402
    GlobalParameters,
    GradientType,
    LongitudinalNode,
    PlanFeaturePoint,
    TurnType,
    V2Strategy,
)
from spatial_merger import SpatialMerger  # noqa: E402


_SAMPLE_PLAN_DXF = _PROJECT_ROOT / "data" / "蔡家沟倒虹吸测试_倒圆.dxf"


def _load_sample_plan_points():
    plan_points, _plan_segments, message = DxfParser.parse_plan_polyline(str(_SAMPLE_PLAN_DXF))
    assert plan_points, message
    return plan_points


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


def _event_xi(event, diameter):
    angle_deg = math.degrees(event.theta_event)
    if event.turn_style == TurnType.ARC:
        return CoefficientService.calculate_bend_coeff(
            event.R_eff, diameter, angle_deg, verbose=False
        )
    return CoefficientService.calculate_fold_coeff(angle_deg, verbose=False)


def _make_ip_style_arc_points():
    radius = 500.0
    angle_deg = 30.0
    qz = 500.0

    ip0 = (0.0, 0.0)
    ip1 = (500.0, 0.0)
    d_out = (math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg)))
    ip2 = (ip1[0] + 500.0 * d_out[0], ip1[1] + 500.0 * d_out[1])

    return [
        PlanFeaturePoint(
            chainage=0.0,
            x=ip0[0],
            y=ip0[1],
            azimuth_meas_deg=90.0,
            turn_type=TurnType.NONE,
        ),
        PlanFeaturePoint(
            chainage=qz,
            x=ip1[0],
            y=ip1[1],
            azimuth_meas_deg=90.0,
            turn_angle=angle_deg,
            turn_radius=radius,
            turn_type=TurnType.ARC,
        ),
        PlanFeaturePoint(
            chainage=1000.0,
            x=ip2[0],
            y=ip2[1],
            azimuth_meas_deg=60.0,
            turn_type=TurnType.NONE,
        ),
    ]


def test_dxf_arc_events_use_real_segment_intervals():
    plan_points = _load_sample_plan_points()
    result = SpatialMerger.merge_and_compute(plan_points, [], verbose=False)

    expected_intervals = []
    for idx, point in enumerate(plan_points[:-1]):
        if point.turn_type == TurnType.ARC:
            expected_intervals.append((point.chainage, plan_points[idx + 1].chainage))

    actual_intervals = [
        (event.s_a, event.s_b)
        for event in result.bend_events
        if event.event_type == "PLAN" and event.turn_style == TurnType.ARC
    ]

    assert len(actual_intervals) == len(expected_intervals)
    for actual, expected in zip(actual_intervals, expected_intervals):
        assert actual == pytest.approx(expected, abs=1e-3)


def test_ip_style_arc_points_keep_qz_semantics():
    plan_points = _make_ip_style_arc_points()
    result = SpatialMerger.merge_and_compute(plan_points, [], verbose=False)

    event = next(
        event
        for event in result.bend_events
        if event.event_type == "PLAN" and event.turn_style == TurnType.ARC
    )
    expected_length = plan_points[1].turn_radius * math.radians(plan_points[1].turn_angle)
    expected_interval = (
        plan_points[1].chainage - expected_length / 2.0,
        plan_points[1].chainage + expected_length / 2.0,
    )

    assert (event.s_a, event.s_b) == pytest.approx(expected_interval, abs=1e-3)


def test_independent_plan_bend_loss_uses_feature_points_once_per_turn():
    plan_points = _load_sample_plan_points()
    result = HydraulicCore.execute_calculation(
        _sample_params(),
        [],
        verbose=True,
        plan_feature_points=plan_points,
        longitudinal_nodes=[],
    )
    counted_points = [
        point
        for point in plan_points
        if point.turn_angle > 0.1 and point.turn_type in (TurnType.ARC, TurnType.FOLD)
    ]
    expected_sum = 0.0
    for point in counted_points:
        if point.turn_type == TurnType.ARC and point.turn_radius > 0:
            expected_sum += CoefficientService.calculate_bend_coeff(
                point.turn_radius,
                result.diameter,
                point.turn_angle,
                verbose=False,
            )
        elif point.turn_type == TurnType.FOLD:
            expected_sum += CoefficientService.calculate_fold_coeff(
                point.turn_angle,
                verbose=False,
            )
    detail_lines = [
        line
        for line in result.calculation_steps
        if "平面弯管" in line or "平面折管" in line
    ]

    assert result.data_mode == "仅平面（独立计算）"
    assert len(detail_lines) == len(counted_points)
    assert result.xi_sum_middle == pytest.approx(expected_sum, rel=1e-6, abs=1e-6)


def test_geometry_diagnostics_are_non_blocking_and_sample_has_no_false_assertion2():
    plan_points = _load_sample_plan_points()
    result = SpatialMerger.merge_and_compute(plan_points, [], verbose=True)
    steps_text = "\n".join(result.computation_steps)

    assert "【几何一致性诊断】" in steps_text
    assert "仅为非阻断诊断，不参与弯道数量识别或局损累计" in steps_text
    assert "弦长>桩号差" not in steps_text


def test_same_chainage_auto_losses_sum_directly_without_spatial_merger(monkeypatch):
    """同桩号平面+纵断面自动值应直接相加，不生成3D复合弯道，也不依赖SpatialMerger。"""
    call_counts = {"merge": 0, "build": 0, "length": 0}

    def _count_merge(*_args, **_kwargs):
        call_counts["merge"] += 1
        raise AssertionError("倒虹吸主路径不应调用 SpatialMerger.merge_and_compute")

    def _count_build(*_args, **_kwargs):
        call_counts["build"] += 1
        raise AssertionError("倒虹吸主路径不应调用 SpatialMerger._build_profile_segments")

    def _count_length(*_args, **_kwargs):
        call_counts["length"] += 1
        raise AssertionError("倒虹吸主路径不应调用 SpatialMerger._compute_spatial_length")

    monkeypatch.setattr(SpatialMerger, "merge_and_compute", _count_merge)
    monkeypatch.setattr(SpatialMerger, "_build_profile_segments", _count_build)
    monkeypatch.setattr(SpatialMerger, "_compute_spatial_length", _count_length)

    plan_points = [
        PlanFeaturePoint(
            chainage=0.0,
            x=0.0,
            y=0.0,
            azimuth_meas_deg=90.0,
            turn_type=TurnType.NONE,
        ),
        PlanFeaturePoint(
            chainage=100.0,
            x=100.0,
            y=0.0,
            azimuth_meas_deg=90.0,
            turn_type=TurnType.FOLD,
            turn_angle=20.0,
        ),
        PlanFeaturePoint(
            chainage=200.0,
            x=193.97,
            y=34.20,
            azimuth_meas_deg=70.0,
            turn_type=TurnType.NONE,
        ),
    ]
    longitudinal_nodes = [
        LongitudinalNode(
            chainage=0.0,
            elevation=100.0,
            turn_type=TurnType.NONE,
            turn_angle=0.0,
        ),
        LongitudinalNode(
            chainage=100.0,
            elevation=96.0,
            turn_type=TurnType.FOLD,
            turn_angle=8.0,
        ),
        LongitudinalNode(
            chainage=200.0,
            elevation=94.0,
            turn_type=TurnType.NONE,
            turn_angle=0.0,
        ),
    ]

    result = HydraulicCore.execute_calculation(
        _sample_params(),
        [],
        verbose=True,
        plan_feature_points=plan_points,
        longitudinal_nodes=longitudinal_nodes,
    )

    expected_plan = CoefficientService.calculate_fold_coeff(20.0, verbose=False)
    expected_longitudinal = CoefficientService.calculate_fold_coeff(8.0, verbose=False)
    expected_length = math.hypot(100.0, 4.0) + math.hypot(100.0, 2.0)
    detail_text = "\n".join(result.calculation_steps)

    assert result.data_mode == "平面+纵断面（独立叠加）"
    assert result.xi_sum_middle == pytest.approx(
        expected_plan + expected_longitudinal,
        rel=1e-9,
    )
    assert result.total_length == pytest.approx(expected_length, rel=1e-9)
    assert "未采用三维空间合并" in detail_text
    assert "复合弯道" not in detail_text
    assert call_counts == {"merge": 0, "build": 0, "length": 0}
