# -*- coding: utf-8 -*-
"""倒虹吸手动局部系数参与执行计算的回归测试。"""

import math
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_SIPHON_ROOT = _PROJECT_ROOT / "倒虹吸水力计算系统"
if str(_SIPHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_SIPHON_ROOT))

from PySide6.QtWidgets import QApplication, QWidget

import app_渠系计算前端.siphon.dialogs as siphon_dialogs_mod
import app_渠系计算前端.siphon.panel as siphon_panel_mod
from siphon_coefficients import CoefficientService
from siphon_hydraulics import HydraulicCore
from siphon_models import (
    BendEvent,
    GlobalParameters,
    GradientType,
    LongitudinalNode,
    PlanFeaturePoint,
    SegmentDirection,
    SegmentType,
    StructureSegment,
    TurnType,
    V2Strategy,
)
from spatial_merger import SpatialMerger


class _FakeWebView(QWidget):
    """替代真实 WebEngine，避免无头环境初始化失败。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.html = ""

    def setHtml(self, html, *_args, **_kwargs):
        """记录渲染结果，方便断言公式文本。"""
        self.html = html


class _InfoBarSpy:
    """记录 InfoBar 调用，避免测试时弹真实界面。"""

    warnings = []

    @classmethod
    def reset(cls):
        cls.warnings = []

    @classmethod
    def warning(cls, *args, **kwargs):
        cls.warnings.append((args, kwargs))
        return None

    @staticmethod
    def error(*_args, **_kwargs):
        return None

    @staticmethod
    def success(*_args, **_kwargs):
        return None


def _get_qapp():
    """返回测试可复用的 QApplication。"""
    return QApplication.instance() or QApplication([])


def _fake_web_view_factory(parent=None):
    """生成轻量 WebView 替身。"""
    return _FakeWebView(parent)


def _patch_dialog_formula_rendering(monkeypatch):
    """将公式渲染替换为纯文本 HTML，避免依赖真实 KaTeX。"""
    monkeypatch.setattr(
        siphon_dialogs_mod,
        "create_web_view",
        _fake_web_view_factory,
    )
    monkeypatch.setattr(
        siphon_dialogs_mod,
        "render_latex_svg",
        lambda latex, fontsize=14: f'<svg height="12pt">{latex}</svg>',
    )
    monkeypatch.setattr(
        siphon_dialogs_mod,
        "wrap_with_katex",
        lambda body, extra_css=None: body,
    )
    monkeypatch.setattr(
        siphon_dialogs_mod,
        "get_svg_height_px",
        lambda svg, padding=8: 40,
    )


def _sample_params():
    """返回一组最小可计算的倒虹吸全局参数。"""
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


def _make_plan_bend_segment(xi_user=0.2):
    """构造一个带手工局部系数的平面弯管段。"""
    radius = 4.8
    angle = 16.951
    length = radius * math.radians(angle)
    return StructureSegment(
        segment_type=SegmentType.BEND,
        direction=SegmentDirection.PLAN,
        radius=radius,
        angle=angle,
        length=length,
        xi_user=xi_user,
        locked=True,
        source_ip_index=1,
    )


def _make_composite_fold_inputs():
    """构造能生成真实 COMPOSITE 折管事件的最小平面/纵断面数据。"""
    plan_points = [
        PlanFeaturePoint(
            chainage=0.0,
            x=0.0,
            y=0.0,
            ip_index=0,
            azimuth_meas_deg=90.0,
            turn_type=TurnType.NONE,
        ),
        PlanFeaturePoint(
            chainage=100.0,
            x=100.0,
            y=0.0,
            ip_index=1,
            azimuth_meas_deg=90.0,
            turn_angle=20.0,
            turn_type=TurnType.FOLD,
        ),
        PlanFeaturePoint(
            chainage=200.0,
            x=193.97,
            y=34.20,
            ip_index=2,
            azimuth_meas_deg=70.0,
            turn_type=TurnType.NONE,
        ),
    ]
    longitudinal_nodes = [
        LongitudinalNode(
            chainage=0.0,
            elevation=100.0,
            turn_type=TurnType.NONE,
            slope_after=0.0,
        ),
        LongitudinalNode(
            chainage=100.0,
            elevation=100.0,
            turn_type=TurnType.FOLD,
            turn_angle=8.0,
            slope_before=math.radians(-4.0),
            slope_after=math.radians(4.0),
        ),
        LongitudinalNode(
            chainage=200.0,
            elevation=100.0,
            turn_type=TurnType.NONE,
            slope_before=0.0,
        ),
    ]
    plan_segment = StructureSegment(
        segment_type=SegmentType.FOLD,
        direction=SegmentDirection.PLAN,
        length=100.0,
        angle=20.0,
        xi_user=0.2,
        locked=True,
        source_ip_index=1,
    )
    long_segment = StructureSegment(
        segment_type=SegmentType.FOLD,
        direction=SegmentDirection.LONGITUDINAL,
        length=100.0,
        angle=8.0,
        xi_user=0.3,
        start_elevation=100.0,
        end_elevation=100.0,
        locked=True,
        source_long_node_index=1,
    )
    return plan_points, longitudinal_nodes, plan_segment, long_segment


def _make_longitudinal_manual_segment(segment_type, xi_user):
    """构造一个带手工局部系数的纵断面转弯段。"""
    if segment_type == SegmentType.FOLD:
        return StructureSegment(
            segment_type=segment_type,
            direction=SegmentDirection.LONGITUDINAL,
            length=25.0,
            angle=18.0,
            xi_user=xi_user,
            start_elevation=100.0,
            end_elevation=101.5,
            locked=True,
        )

    radius = 5.2
    angle = 12.0
    return StructureSegment(
        segment_type=segment_type,
        direction=SegmentDirection.LONGITUDINAL,
        length=radius * math.radians(angle),
        radius=radius,
        angle=angle,
        xi_user=xi_user,
        locked=True,
    )


def test_execute_calculation_uses_manual_xi_for_plan_bend_override():
    """平面弯管手工局部系数应直接参与执行计算。"""
    plan_segment = _make_plan_bend_segment(xi_user=0.2)

    result = HydraulicCore.execute_calculation(
        _sample_params(),
        [],
        verbose=True,
        plan_segments=[plan_segment],
        plan_total_length=plan_segment.length,
    )

    assert result.xi_sum_middle == pytest.approx(0.2, abs=1e-9)


def test_execute_calculation_detail_shows_auto_and_adopted_xi_for_plan_bend_override():
    """详细过程应同时保留自动值和最终采用的手工值。"""
    plan_segment = _make_plan_bend_segment(xi_user=0.2)

    result = HydraulicCore.execute_calculation(
        _sample_params(),
        [],
        verbose=True,
        plan_segments=[plan_segment],
        plan_total_length=plan_segment.length,
    )
    detail_text = "\n".join(result.calculation_steps)
    auto_xi = CoefficientService.calculate_bend_coeff(
        plan_segment.radius,
        result.diameter,
        plan_segment.angle,
        verbose=False,
    )

    assert f"{auto_xi:.4f}" in detail_text
    assert "0.2000" in detail_text


def test_execute_calculation_uses_manual_xi_for_plan_only_spatial_bend_event():
    """仅平面空间模式下，手工局部系数仍应映射到对应弯道事件。"""
    plan_segment = _make_plan_bend_segment(xi_user=0.2)
    d_out = (
        math.cos(math.radians(plan_segment.angle)),
        math.sin(math.radians(plan_segment.angle)),
    )
    plan_points = [
        PlanFeaturePoint(
            chainage=0.0,
            x=0.0,
            y=0.0,
            azimuth_meas_deg=90.0,
            turn_type=TurnType.NONE,
            ip_index=0,
        ),
        PlanFeaturePoint(
            chainage=50.0,
            x=50.0,
            y=0.0,
            azimuth_meas_deg=90.0,
            turn_radius=plan_segment.radius,
            turn_angle=plan_segment.angle,
            turn_type=TurnType.ARC,
            ip_index=1,
        ),
        PlanFeaturePoint(
            chainage=100.0,
            x=50.0 + 50.0 * d_out[0],
            y=50.0 * d_out[1],
            azimuth_meas_deg=90.0 - plan_segment.angle,
            turn_type=TurnType.NONE,
            ip_index=2,
        ),
    ]

    result = HydraulicCore.execute_calculation(
        _sample_params(),
        [],
        verbose=True,
        plan_segments=[plan_segment],
        plan_feature_points=plan_points,
        longitudinal_nodes=[],
    )

    assert result.xi_sum_middle == pytest.approx(0.2, abs=1e-9)
    assert "本次采用手工局部系数" in "\n".join(result.calculation_steps)


def test_execute_calculation_uses_missing_source_manual_xi_only_once_when_geometry_is_unique():
    """旧数据缺来源索引时，几何唯一匹配的手工值只能命中对应弯管一次。"""
    manual_bend = StructureSegment(
        segment_type=SegmentType.BEND,
        direction=SegmentDirection.PLAN,
        length=5.0 * math.radians(25.0),
        radius=5.0,
        angle=25.0,
        xi_user=0.3333,
        locked=True,
        source_ip_index=None,
    )
    auto_bend = StructureSegment(
        segment_type=SegmentType.BEND,
        direction=SegmentDirection.PLAN,
        length=5.0 * math.radians(40.0),
        radius=5.0,
        angle=40.0,
        locked=True,
        source_ip_index=3,
    )
    plan_segments = [manual_bend, auto_bend]
    az_after_first = 90.0 - manual_bend.angle
    x_after_first = 50.0 + 50.0 * math.cos(math.radians(manual_bend.angle))
    y_after_first = 50.0 * math.sin(math.radians(manual_bend.angle))
    x_second_ip = x_after_first + 40.0 * math.sin(math.radians(az_after_first))
    y_second_ip = y_after_first + 40.0 * math.cos(math.radians(az_after_first))
    az_after_second = az_after_first - auto_bend.angle
    x_end = x_second_ip + 50.0 * math.sin(math.radians(az_after_second))
    y_end = y_second_ip + 50.0 * math.cos(math.radians(az_after_second))
    plan_points = [
        PlanFeaturePoint(
            chainage=0.0,
            x=0.0,
            y=0.0,
            azimuth_meas_deg=90.0,
            turn_type=TurnType.NONE,
            ip_index=0,
        ),
        PlanFeaturePoint(
            chainage=50.0,
            x=50.0,
            y=0.0,
            azimuth_meas_deg=90.0,
            turn_radius=manual_bend.radius,
            turn_angle=manual_bend.angle,
            turn_type=TurnType.ARC,
            ip_index=1,
        ),
        PlanFeaturePoint(
            chainage=100.0,
            x=x_after_first,
            y=y_after_first,
            azimuth_meas_deg=az_after_first,
            turn_type=TurnType.NONE,
            ip_index=2,
        ),
        PlanFeaturePoint(
            chainage=140.0,
            x=x_second_ip,
            y=y_second_ip,
            azimuth_meas_deg=az_after_first,
            turn_radius=auto_bend.radius,
            turn_angle=auto_bend.angle,
            turn_type=TurnType.ARC,
            ip_index=3,
        ),
        PlanFeaturePoint(
            chainage=190.0,
            x=x_end,
            y=y_end,
            azimuth_meas_deg=az_after_second,
            turn_type=TurnType.NONE,
            ip_index=4,
        ),
    ]

    result = HydraulicCore.execute_calculation(
        _sample_params(),
        [],
        verbose=True,
        plan_segments=plan_segments,
        plan_feature_points=plan_points,
        longitudinal_nodes=[],
    )

    detail_text = "\n".join(result.calculation_steps)
    auto_second = CoefficientService.calculate_bend_coeff(
        auto_bend.radius,
        result.diameter,
        auto_bend.angle,
        verbose=False,
    )

    assert detail_text.count("本次采用手工局部系数 ξ=0.3333") == 1
    assert result.xi_sum_middle == pytest.approx(0.3333 + auto_second, abs=1e-6)


def test_execute_calculation_rejects_missing_source_manual_xi_when_geometry_is_ambiguous():
    """旧数据缺来源索引且几何不唯一时，应回退自动值并记录未采用原因。"""
    plan_segments = [
        StructureSegment(
            segment_type=SegmentType.BEND,
            direction=SegmentDirection.PLAN,
            length=5.0 * math.radians(25.0),
            radius=5.0,
            angle=25.0,
            xi_user=0.2,
            locked=True,
            source_ip_index=None,
        ),
        StructureSegment(
            segment_type=SegmentType.BEND,
            direction=SegmentDirection.PLAN,
            length=5.0 * math.radians(25.0),
            radius=5.0,
            angle=25.0,
            xi_user=0.3,
            locked=True,
            source_ip_index=None,
        ),
    ]
    plan_points = [
        PlanFeaturePoint(
            chainage=0.0,
            x=0.0,
            y=0.0,
            azimuth_meas_deg=90.0,
            turn_type=TurnType.NONE,
            ip_index=0,
        ),
        PlanFeaturePoint(
            chainage=50.0,
            x=50.0,
            y=0.0,
            azimuth_meas_deg=90.0,
            turn_radius=5.0,
            turn_angle=25.0,
            turn_type=TurnType.ARC,
            ip_index=1,
        ),
        PlanFeaturePoint(
            chainage=100.0,
            x=95.3154,
            y=21.1309,
            azimuth_meas_deg=65.0,
            turn_type=TurnType.NONE,
            ip_index=2,
        ),
        PlanFeaturePoint(
            chainage=140.0,
            x=131.5677,
            y=38.0356,
            azimuth_meas_deg=65.0,
            turn_radius=5.0,
            turn_angle=25.0,
            turn_type=TurnType.ARC,
            ip_index=3,
        ),
        PlanFeaturePoint(
            chainage=190.0,
            x=169.8707,
            y=70.1785,
            azimuth_meas_deg=40.0,
            turn_type=TurnType.NONE,
            ip_index=4,
        ),
    ]

    result = HydraulicCore.execute_calculation(
        _sample_params(),
        [],
        verbose=True,
        plan_segments=plan_segments,
        plan_feature_points=plan_points,
        longitudinal_nodes=[],
    )

    auto_xi = CoefficientService.calculate_bend_coeff(
        5.0,
        result.diameter,
        25.0,
        verbose=False,
    )
    detail_text = "\n".join(result.calculation_steps)

    assert result.xi_sum_middle == pytest.approx(auto_xi * 2, abs=1e-6)
    assert "本次采用手工局部系数" not in detail_text
    assert "存在多条手工局部系数，无法一一对应" in detail_text
    assert len(result.ignored_manual_overrides) == 2


def test_execute_calculation_keeps_composite_auto_xi_and_records_ignored_manual_overrides():
    """真实 COMPOSITE 事件应继续走自动值，并记录被忽略的手工值。"""
    plan_points, longitudinal_nodes, plan_segment, long_segment = _make_composite_fold_inputs()
    spatial_result = SpatialMerger.merge_and_compute(plan_points, longitudinal_nodes, verbose=False)
    composite_event = next(
        event
        for event in spatial_result.bend_events
        if event.event_type == "COMPOSITE" and event.turn_style == TurnType.FOLD
    )
    auto_xi = CoefficientService.calculate_fold_coeff(
        math.degrees(composite_event.theta_event),
        verbose=False,
    )

    result = HydraulicCore.execute_calculation(
        _sample_params(),
        [long_segment],
        verbose=True,
        plan_segments=[plan_segment],
        plan_feature_points=plan_points,
        longitudinal_nodes=longitudinal_nodes,
    )
    ignored_manual_overrides = getattr(result, "ignored_manual_overrides", None)

    assert result.xi_sum_middle == pytest.approx(auto_xi, abs=1e-6)
    assert ignored_manual_overrides is not None
    assert len(ignored_manual_overrides) >= 2


def test_spatial_merger_keeps_all_source_indices_when_adjacent_arc_events_are_merged():
    """相邻弯道事件合并后，必须保留全部来源索引，不能只剩一个。"""
    merged_events = SpatialMerger._merge_composite_events(
        [
            BendEvent(
                s_a=0.0,
                s_b=10.0,
                event_type="PLAN",
                turn_style=TurnType.ARC,
                R_h=5.0,
                plan_source_ip_index=1,
                plan_source_ip_indices=[1],
            ),
            BendEvent(
                s_a=10.0,
                s_b=20.0,
                event_type="PLAN",
                turn_style=TurnType.ARC,
                R_h=5.0,
                plan_source_ip_index=2,
                plan_source_ip_indices=[2],
            ),
        ],
        [],
        [],
        [],
    )

    assert len(merged_events) == 1
    assert merged_events[0].plan_source_ip_indices == [1, 2]
    assert merged_events[0].plan_source_ip_index is None


@pytest.mark.parametrize(
    ("segment_type", "xi_user"),
    [
        (SegmentType.FOLD, 0.21),
        (SegmentType.BEND, 0.19),
    ],
    ids=["longitudinal_fold", "longitudinal_bend"],
)
def test_execute_calculation_uses_manual_xi_for_longitudinal_turn_segments(segment_type, xi_user):
    """纵断面弯管/折管的手工局部系数也应进入执行计算。"""
    segment = _make_longitudinal_manual_segment(segment_type, xi_user)

    result = HydraulicCore.execute_calculation(
        _sample_params(),
        [segment],
        verbose=True,
    )

    assert result.xi_sum_middle == pytest.approx(xi_user, abs=1e-9)


def test_segment_edit_dialog_clearing_manual_xi_restores_auto_value(monkeypatch):
    """清空手工局部系数后，对话框应回到自动值。"""
    _get_qapp()
    _patch_dialog_formula_rendering(monkeypatch)

    angle = 42.7828
    auto_xi = CoefficientService.calculate_fold_coeff(angle, verbose=False)
    seg = siphon_dialogs_mod.StructureSegment(
        segment_type=siphon_dialogs_mod.SegmentType.FOLD,
        direction=siphon_dialogs_mod.SegmentDirection.PLAN,
        length=109.651,
        angle=angle,
        locked=True,
        xi_user=0.2,
        xi_calc=auto_xi,
    )

    dlg = siphon_dialogs_mod.SegmentEditDialog(
        None,
        segment=seg,
        Q=10.0,
        v=2.0,
        direction=siphon_dialogs_mod.SegmentDirection.PLAN,
    )

    assert dlg.ed_xi.text() == "0.2000"
    dlg.ed_xi.clear()
    dlg._on_geom()

    assert dlg.ed_xi.text() == f"{auto_xi:.4f}"
    assert f"{auto_xi:.4f}" in dlg.formula_view.html

    dlg.deleteLater()


def test_panel_warns_once_when_manual_overrides_are_ignored(monkeypatch):
    """只有本次确实未采用手工值时，界面才给一次非阻断提示。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    monkeypatch.setattr(siphon_panel_mod, "InfoBar", _InfoBarSpy)
    _InfoBarSpy.reset()

    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    panel._suppress_result_display = True
    panel.inc_cb.setChecked(False)
    panel._turn_n_user_confirmed = True
    panel.plan_feature_points = [
        siphon_panel_mod.PlanFeaturePoint(chainage=0.0, x=0.0, y=0.0),
        siphon_panel_mod.PlanFeaturePoint(chainage=100.0, x=100.0, y=0.0),
    ]
    monkeypatch.setattr(panel, "_validate_v_before_calc", lambda: True)
    monkeypatch.setattr(panel, "_validate_num_pipes_before_calc", lambda: True)
    monkeypatch.setattr(panel, "_validate_inlet_velocity", lambda: None)
    monkeypatch.setattr(
        panel,
        "_get_global_params",
        lambda: siphon_panel_mod.GlobalParameters(Q=10.0, v_guess=2.0),
    )

    def _fake_execute(_params, _segments, **_kwargs):
        return siphon_panel_mod.CalculationResult(
            diameter=1.0,
            velocity=1.0,
            total_head_loss=1.0,
            velocity_channel_in=1.0,
            velocity_pipe_in=1.0,
            velocity_outlet_start=1.0,
            velocity_channel_out=1.0,
            ignored_manual_overrides=["平面弯管手工局部系数 ξ=0.2000，因 3D 复合弯道无法一一对应，仍按自动值计算。"],
        )

    monkeypatch.setattr(siphon_panel_mod.HydraulicCore, "execute_calculation", _fake_execute)

    panel._execute_calculation()

    assert any("手工局部系数提示" in args[0] for args, _kwargs in _InfoBarSpy.warnings)

    panel.deleteLater()


def test_panel_segment_dict_roundtrip_preserves_manual_sources(monkeypatch):
    """保存再恢复时，手工局部系数来源索引不应丢失。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)

    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    segment = siphon_panel_mod.StructureSegment(
        segment_type=siphon_panel_mod.SegmentType.BEND,
        direction=siphon_panel_mod.SegmentDirection.LONGITUDINAL,
        length=1.2,
        radius=5.0,
        angle=20.0,
        xi_user=0.2,
        xi_calc=0.1337,
        source_ip_index=1,
        source_long_node_index=3,
    )

    serialized = panel._seg_to_dict(segment)
    restored = panel._dict_to_seg(serialized)

    assert restored.source_ip_index == 1
    assert restored.source_long_node_index == 3
    assert restored.xi_user == pytest.approx(0.2, abs=1e-9)
    assert restored.xi_calc == pytest.approx(0.1337, abs=1e-9)

    panel.deleteLater()


def test_panel_from_dict_recovers_plan_segment_source_ip_index_for_legacy_data(monkeypatch):
    """旧项目缺失平面段来源索引时，加载后应按唯一几何匹配补回。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)

    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    legacy_data = {
        "segments": [],
        "plan_segments": [
            {
                "type": "弯管",
                "direction": "平面",
                "length": round(5.0 * math.radians(25.0), 4),
                "radius": 5.0,
                "angle": 25.0,
                "xi_user": 0.3333,
                "xi_calc": 0.1337,
                "locked": True,
            }
        ],
        "plan_feature_points": [
            {
                "chainage": 0.0,
                "x": 0.0,
                "y": 0.0,
                "azimuth": 90.0,
                "turn_radius": 0.0,
                "turn_angle": 0.0,
                "turn_type": "无",
                "ip_index": 0,
            },
            {
                "chainage": 50.0,
                "x": 50.0,
                "y": 0.0,
                "azimuth": 65.0,
                "turn_radius": 5.0,
                "turn_angle": 25.0,
                "turn_type": "圆弧",
                "ip_index": 1,
            },
            {
                "chainage": 100.0,
                "x": 95.3154,
                "y": 21.1309,
                "azimuth": 65.0,
                "turn_radius": 0.0,
                "turn_angle": 0.0,
                "turn_type": "无",
                "ip_index": 2,
            },
        ],
        "longitudinal_nodes": [],
        "plan_source": "water_profile",
        "longitudinal_is_example": True,
    }

    panel.from_dict(legacy_data)

    assert len(panel.plan_segments) == 1
    assert panel.plan_segments[0].source_ip_index == 1
    assert panel.to_dict()["plan_segments"][0]["source_ip_index"] == 1

    panel.deleteLater()


def test_longitudinal_node_roundtrip_preserves_node_uid():
    """纵断面节点保存再恢复后，稳定标识不应丢失。"""
    node = LongitudinalNode(
        chainage=12.3,
        elevation=45.6,
        vertical_curve_radius=5.0,
        turn_type=TurnType.ARC,
        turn_angle=18.0,
        node_uid="node-keep-me",
    )

    restored = LongitudinalNode.from_dict(node.to_dict())

    assert restored.node_uid == "node-keep-me"


def test_sync_nodes_to_segments_preserves_manual_longitudinal_coefficients_after_row_shift(monkeypatch):
    """纵断面前面插入新节点后，原转弯段的手工局部系数仍应跟着节点走。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)

    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    panel._add_example_longitudinal()

    target = next(
        seg
        for seg in panel.segments
        if seg.direction == siphon_panel_mod.SegmentDirection.LONGITUDINAL
        and seg.segment_type in (
            siphon_panel_mod.SegmentType.BEND,
            siphon_panel_mod.SegmentType.FOLD,
        )
        and seg.source_long_node_index is not None
    )
    original_source_index = target.source_long_node_index
    target_node_uid = panel.longitudinal_nodes[original_source_index].node_uid
    target.xi_user = 0.2
    target.xi_calc = 0.1337

    panel.long_table.insertRow(0)
    combo = panel._create_turn_type_combo()
    panel.long_table.setCellWidget(0, 3, combo)
    for col in (0, 1, 2, 4):
        panel._ensure_long_table_item(0, col)
    panel.long_table.item(0, 0).setText("-10.000")
    panel.long_table.item(0, 1).setText("113.844")
    panel.long_table.item(0, 2).setText("")
    panel.long_table.item(0, 4).setText("")
    panel._set_long_row_uid(0, "test-new-leading-node")

    panel._sync_nodes_to_segments()

    restored = next(
        seg
        for seg in panel.segments
        if seg.direction == siphon_panel_mod.SegmentDirection.LONGITUDINAL
        and seg.segment_type == target.segment_type
        and seg.source_long_node_index is not None
        and panel.longitudinal_nodes[seg.source_long_node_index].node_uid == target_node_uid
    )
    assert restored.source_long_node_index != original_source_index
    assert restored.xi_user == pytest.approx(0.2, abs=1e-9)
    assert restored.xi_calc == pytest.approx(0.1337, abs=1e-9)

    panel.deleteLater()


def test_execute_calculation_counts_endpoint_component_xi_into_pipe_local_loss():
    """进水口和出水口构件系数应并入 ΔZ2 的局部损失。"""
    params = _sample_params()
    segments = [
        StructureSegment(
            segment_type=SegmentType.INLET,
            direction=SegmentDirection.COMMON,
            xi_user=0.2250,
            locked=True,
        ),
        StructureSegment(
            segment_type=SegmentType.TRASH_RACK,
            direction=SegmentDirection.COMMON,
            xi_user=0.2830,
            locked=True,
        ),
        StructureSegment(
            segment_type=SegmentType.OUTLET,
            direction=SegmentDirection.COMMON,
            xi_user=0.1600,
            locked=True,
        ),
    ]

    result = HydraulicCore.execute_calculation(params, segments, verbose=True)

    expected_xi_sum = 0.2250 + 0.2830 + 0.1600
    expected_local_loss = expected_xi_sum * result.velocity ** 2 / (2 * 9.81)

    assert result.xi_sum_middle == pytest.approx(expected_xi_sum, abs=1e-9)
    assert result.loss_local == pytest.approx(expected_local_loss, rel=1e-9)
    assert result.xi_inlet == pytest.approx(params.xi_inlet, abs=1e-9)
    assert result.xi_outlet == pytest.approx(params.xi_outlet, abs=1e-9)


def test_execute_calculation_detail_text_distinguishes_gradient_and_endpoint_coefficients():
    """详细过程应明确区分渐变段系数与进出水口构件局部系数。"""
    result = HydraulicCore.execute_calculation(
        _sample_params(),
        [
            StructureSegment(
                segment_type=SegmentType.INLET,
                direction=SegmentDirection.COMMON,
                xi_user=0.2250,
                locked=True,
            ),
            StructureSegment(
                segment_type=SegmentType.OUTLET,
                direction=SegmentDirection.COMMON,
                xi_user=0.1600,
                locked=True,
            ),
        ],
        verbose=True,
    )

    steps_text = "\n".join(result.calculation_steps)
    summary_text = HydraulicCore.format_result(result)

    assert "公式 L.1.6: ΔZ = ΔZ1 + ΔZ2 - ΔZ3" in steps_text
    assert "进口渐变段系数 ξ_1" in steps_text
    assert "出口渐变段系数 ξ_2" in steps_text
    assert "进水口构件局部损失，计入ΔZ2" in steps_text
    assert "出水口构件局部损失，计入ΔZ2" in steps_text
    assert "管道段水头损失 ΔZ2" in summary_text


def test_panel_keeps_gradient_coefficients_separate_from_endpoint_component_coefficients(monkeypatch):
    """界面上的 ξ₁/ξ₂ 应保持全局渐变段含义，不被结构段系数覆盖。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)

    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    panel.edit_Q.setText("4.0")
    panel.edit_v.setText("2.0")
    panel.edit_n.setText("0.014")
    panel.edit_xi_inlet.setText("0.2000")
    panel.edit_xi_outlet.setText("0.4000")
    panel.segments = [
        siphon_panel_mod.StructureSegment(
            segment_type=siphon_panel_mod.SegmentType.INLET,
            direction=siphon_panel_mod.SegmentDirection.COMMON,
            xi_user=0.2250,
            locked=True,
        ),
        siphon_panel_mod.StructureSegment(
            segment_type=siphon_panel_mod.SegmentType.OUTLET,
            direction=siphon_panel_mod.SegmentDirection.COMMON,
            xi_user=0.1600,
            locked=True,
        ),
    ]

    params = panel._get_global_params()
    result = siphon_panel_mod.HydraulicCore.execute_calculation(
        params,
        panel.segments,
        verbose=True,
    )

    assert params.xi_inlet == pytest.approx(0.2000, abs=1e-9)
    assert params.xi_outlet == pytest.approx(0.4000, abs=1e-9)
    assert panel.edit_xi_inlet.text() == "0.2000"
    assert panel.edit_xi_outlet.text() == "0.4000"
    assert result.xi_sum_middle == pytest.approx(0.2250 + 0.1600, abs=1e-9)

    panel.deleteLater()
