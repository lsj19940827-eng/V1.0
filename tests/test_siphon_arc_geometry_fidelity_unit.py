# -*- coding: utf-8 -*-
"""倒虹吸 DXF 圆弧保真回归测试。"""

import math
import os
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QWidget

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SIPHON_ROOT = ROOT / "倒虹吸水力计算系统"
if str(SIPHON_ROOT) not in sys.path:
    sys.path.insert(0, str(SIPHON_ROOT))

import app_渠系计算前端.siphon.panel as siphon_panel_mod
from app_渠系计算前端.siphon.canvas_view import PipelineCanvas
from dxf_parser import DxfParser
from siphon_models import LongitudinalNode, PlanFeaturePoint, SegmentDirection, SegmentType, StructureSegment, TurnType


class _FakeWebView(QWidget):
    """替代真实 WebView，避免测试依赖浏览器内核。"""

    def setHtml(self, *_args, **_kwargs):
        return None


def _fake_web_view_factory(parent=None):
    return _FakeWebView(parent)


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _sample_dxf_path() -> str:
    """返回项目自带的倒虹吸示例 DXF。"""
    return str(ROOT / "倒虹吸水力计算系统" / "resources" / "导入纵断面dxf示例.dxf")


def _make_plan_arc_points():
    """构造一段带真实圆弧几何的平面特征点。"""
    arc_length = 10.0 * math.pi / 2.0
    return [
        PlanFeaturePoint(
            chainage=0.0,
            x=0.0,
            y=0.0,
            azimuth_meas_deg=90.0,
            turn_type=TurnType.NONE,
            ip_index=0,
        ),
        PlanFeaturePoint(
            chainage=10.0,
            x=10.0,
            y=0.0,
            azimuth_meas_deg=90.0,
            turn_radius=10.0,
            turn_angle=90.0,
            turn_type=TurnType.ARC,
            ip_index=1,
            arc_geometry={
                "kind": "plan",
                "mode": "dxf_segment",
                "start": [10.0, 0.0],
                "end": [20.0, 10.0],
                "center": [10.0, 10.0],
                "radius": 10.0,
                "sweep_rad": math.pi / 2.0,
                "clockwise": False,
                "start_chainage": 10.0,
                "end_chainage": 10.0 + arc_length,
            },
        ),
        PlanFeaturePoint(
            chainage=10.0 + arc_length,
            x=20.0,
            y=10.0,
            azimuth_meas_deg=180.0,
            turn_type=TurnType.NONE,
            ip_index=2,
        ),
    ]


def _make_profile_arc_segment():
    """构造一段带真实圆弧几何的纵断面弯段。"""
    return StructureSegment(
        segment_type=SegmentType.BEND,
        direction=SegmentDirection.LONGITUDINAL,
        length=10.0 * math.pi / 2.0,
        radius=10.0,
        angle=90.0,
        coordinates=[(0.0, 100.0), (10.0, 90.0)],
        start_elevation=100.0,
        end_elevation=90.0,
        arc_geometry={
            "kind": "profile",
            "mode": "dxf_segment",
            "start": [0.0, 100.0],
            "end": [10.0, 90.0],
            "center": [0.0, 90.0],
            "radius": 10.0,
            "sweep_rad": math.pi / 2.0,
            "clockwise": True,
            "start_chainage": 0.0,
            "end_chainage": 10.0,
        },
    )


def _make_legacy_profile_segments():
    """构造一组仅保留旧字段的纵断面结构段。"""
    return [
        {
            "type": SegmentType.STRAIGHT.value,
            "direction": SegmentDirection.LONGITUDINAL.value,
            "length": 10.0,
            "radius": 0.0,
            "angle": 0.0,
            "locked": True,
            "start_elev": 100.0,
            "end_elev": 100.0,
        },
        {
            "type": SegmentType.BEND.value,
            "direction": SegmentDirection.LONGITUDINAL.value,
            "length": 10.0 * math.pi / 4.0,
            "radius": 10.0,
            "angle": 45.0,
            "locked": True,
            "start_elev": 100.0,
            "end_elev": 102.92893218813452,
        },
        {
            "type": SegmentType.STRAIGHT.value,
            "direction": SegmentDirection.LONGITUDINAL.value,
            "length": math.sqrt(200.0),
            "radius": 0.0,
            "angle": 0.0,
            "locked": True,
            "start_elev": 102.92893218813452,
            "end_elev": 112.92893218813452,
        },
    ]


def _make_legacy_plan_feature_point_dicts():
    """构造仅保留旧字段的平面特征点字典。"""
    return [
        {
            "chainage": point.chainage,
            "x": point.x,
            "y": point.y,
            "azimuth": point.azimuth_meas_deg,
            "turn_radius": point.turn_radius,
            "turn_angle": point.turn_angle,
            "turn_type": point.turn_type.value,
            "ip_index": point.ip_index,
        }
        for point in _make_plan_arc_points()
    ]


def test_parse_plan_polyline_preserves_arc_geometry_for_points_and_segments():
    """平面 DXF 解析后，圆弧真源应同时保留在特征点和结构段里。"""
    sample_path = _sample_dxf_path()

    plan_points, plan_segments, _msg = DxfParser.parse_plan_polyline(sample_path)

    arc_point = next(point for point in plan_points if point.turn_type == TurnType.ARC)
    arc_segment = next(seg for seg in plan_segments if seg.segment_type == SegmentType.BEND)

    assert arc_point.arc_geometry["kind"] == "plan"
    assert arc_point.arc_geometry["mode"] == "dxf_segment"
    assert arc_point.arc_geometry["radius"] == pytest.approx(5.0, abs=1e-6)
    assert arc_point.arc_geometry["start_chainage"] == pytest.approx(arc_point.chainage, abs=1e-6)
    assert arc_point.arc_geometry["end_chainage"] > arc_point.arc_geometry["start_chainage"]

    assert arc_segment.arc_geometry["kind"] == "plan"
    assert arc_segment.arc_geometry["mode"] == "dxf_segment"
    assert arc_segment.arc_geometry["radius"] == pytest.approx(arc_segment.radius, abs=1e-6)
    assert arc_segment.arc_geometry["start"] != arc_segment.arc_geometry["end"]


def test_reverse_plan_geometry_keeps_arc_geometry_usable():
    """平面反向后，圆弧真源仍应完整可用。"""
    sample_path = _sample_dxf_path()
    plan_points, _plan_segments, _msg = DxfParser.parse_plan_polyline(sample_path)

    reversed_points, reversed_segments, total_length = DxfParser.reverse_plan_geometry(plan_points)

    reversed_arc_point = next(point for point in reversed_points if point.turn_type == TurnType.ARC)
    reversed_arc_segment = next(seg for seg in reversed_segments if seg.segment_type == SegmentType.BEND)

    assert total_length > 0
    assert reversed_arc_point.arc_geometry["kind"] == "plan"
    assert reversed_arc_point.arc_geometry["radius"] == pytest.approx(reversed_arc_point.turn_radius, abs=1e-6)
    assert reversed_arc_point.arc_geometry["start_chainage"] < reversed_arc_point.arc_geometry["end_chainage"]
    assert reversed_arc_segment.arc_geometry["radius"] == pytest.approx(reversed_arc_segment.radius, abs=1e-6)


def test_nodes_to_segments_and_segment_roundtrip_preserve_profile_arc_geometry(monkeypatch):
    """纵断面节点重建和保存恢复后，竖曲线圆弧真源不应丢失。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    sample_path = _sample_dxf_path()
    long_nodes, _msg = DxfParser.parse_longitudinal_profile(sample_path, chainage_offset=0.0)

    rebuilt_segments = panel._nodes_to_segments(long_nodes)
    rebuilt_bend = next(seg for seg in rebuilt_segments if seg.segment_type == SegmentType.BEND)
    restored = panel._dict_to_seg(panel._seg_to_dict(rebuilt_bend))

    assert rebuilt_bend.arc_geometry["kind"] == "profile"
    assert rebuilt_bend.arc_geometry["mode"] == "dxf_segment"
    assert rebuilt_bend.arc_geometry["center"] is not None
    assert rebuilt_bend.arc_geometry["radius"] == pytest.approx(rebuilt_bend.radius, abs=1e-6)
    assert restored.arc_geometry == rebuilt_bend.arc_geometry

    panel.deleteLater()


def test_nodes_to_segments_rebuild_profile_straight_and_fold_coordinates(monkeypatch):
    """纵断面节点重建后，直管和折管都应带回几何坐标。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    sample_path = _sample_dxf_path()
    long_nodes, _msg = DxfParser.parse_longitudinal_profile(sample_path, chainage_offset=0.0)

    rebuilt_segments = panel._nodes_to_segments(long_nodes)
    rebuilt_straight = next(seg for seg in rebuilt_segments if seg.segment_type == SegmentType.STRAIGHT)
    rebuilt_fold = next(seg for seg in rebuilt_segments if seg.segment_type == SegmentType.FOLD)

    assert rebuilt_straight.coordinates == [
        (long_nodes[0].chainage, long_nodes[0].elevation),
        (long_nodes[1].chainage, long_nodes[1].elevation),
    ]
    fold_index = rebuilt_fold.source_long_node_index
    assert fold_index is not None
    assert rebuilt_fold.coordinates == [
        (long_nodes[fold_index - 1].chainage, long_nodes[fold_index - 1].elevation),
        (long_nodes[fold_index].chainage, long_nodes[fold_index].elevation),
        (long_nodes[fold_index + 1].chainage, long_nodes[fold_index + 1].elevation),
    ]

    panel.deleteLater()


def test_segment_dict_roundtrip_preserves_longitudinal_coordinates(monkeypatch):
    """纵断面段保存恢复后，直管和折管坐标不应丢失。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    sample_path = _sample_dxf_path()
    long_nodes, _msg = DxfParser.parse_longitudinal_profile(sample_path, chainage_offset=0.0)

    rebuilt_segments = panel._nodes_to_segments(long_nodes)
    rebuilt_straight = next(seg for seg in rebuilt_segments if seg.segment_type == SegmentType.STRAIGHT)
    rebuilt_fold = next(seg for seg in rebuilt_segments if seg.segment_type == SegmentType.FOLD)
    restored_straight = panel._dict_to_seg(panel._seg_to_dict(rebuilt_straight))
    restored_fold = panel._dict_to_seg(panel._seg_to_dict(rebuilt_fold))

    assert restored_straight.coordinates == rebuilt_straight.coordinates
    assert restored_fold.coordinates == rebuilt_fold.coordinates

    panel.deleteLater()


def test_plan_canvas_sampling_uses_arc_geometry_instead_of_chord():
    """平面画布采样应取圆弧，不应只用弦线端点。"""
    _get_qapp()
    canvas = PipelineCanvas()
    canvas.set_data(plan_feature_points=_make_plan_arc_points(), plan_total_length=25.8)

    sampled = canvas._get_plan_path_coords_for_draw()

    assert len(sampled) > 3
    assert any(
        10.0 < x < 20.0 and y < (x - 10.0) - 0.5
        for x, y in sampled
    )

    canvas.deleteLater()


def test_profile_canvas_sampling_uses_arc_geometry_instead_of_chord():
    """纵断面画布采样应取圆弧，不应只用首尾两点。"""
    _get_qapp()
    canvas = PipelineCanvas()
    canvas.set_data(segments=[_make_profile_arc_segment()])

    sampled = canvas._get_profile_coords_for_draw()

    assert len(sampled) > 2
    assert any(
        0.0 < x < 10.0 and y > (100.0 - x) + 0.5
        for x, y in sampled
    )

    canvas.deleteLater()


def test_example_longitudinal_canvas_still_draws_real_arc_when_flagged_example(monkeypatch):
    """示例纵断面也应按真实圆弧采样，不应退回旧折线。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    panel._add_example_longitudinal()

    canvas = PipelineCanvas()
    canvas.set_data(
        segments=panel.segments,
        longitudinal_nodes=panel.longitudinal_nodes,
        longitudinal_is_example=True,
    )
    sampled = canvas._get_profile_coords_for_draw()

    assert len(sampled) > len(panel.longitudinal_nodes)
    assert any(
        145.103537 < x < 148.139331 and y > 48.873275 + 0.1
        for x, y in sampled
    )

    canvas.deleteLater()
    panel.deleteLater()


def test_from_dict_migrates_legacy_longitudinal_segments_into_arc_geometry(monkeypatch):
    """旧工况只有纵断面结构段时，也应自动补出节点和圆弧真源。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )

    panel.from_dict({
        "segments": _make_legacy_profile_segments(),
    })

    bend_nodes = [node for node in panel.longitudinal_nodes if node.turn_type == TurnType.ARC]
    bend_segments = [
        seg for seg in panel.segments
        if seg.direction == SegmentDirection.LONGITUDINAL and seg.segment_type == SegmentType.BEND
    ]
    sampled = panel.canvas._get_profile_coords_for_draw()
    saved = panel.to_dict()

    assert not panel._longitudinal_is_example
    assert bend_nodes
    assert bend_nodes[0].arc_center_s is not None
    assert bend_segments
    assert bend_segments[0].arc_geometry is not None
    assert len(sampled) > len(panel.longitudinal_nodes)
    assert "longitudinal_nodes" in saved
    assert any(seg.get("arc_geometry") for seg in saved.get("segments", []))

    panel.deleteLater()


def test_from_dict_rebuilds_longitudinal_segment_coordinates_from_nodes(monkeypatch):
    """已有纵断面节点但结构段缺坐标时，加载后应自动补齐直管/折管坐标。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    sample_path = _sample_dxf_path()
    long_nodes, _msg = DxfParser.parse_longitudinal_profile(sample_path, chainage_offset=0.0)

    legacy_segments = []
    for seg in panel._nodes_to_segments(long_nodes):
        legacy_seg = {
            "type": seg.segment_type.value,
            "direction": seg.direction.value,
            "length": seg.length,
            "radius": seg.radius,
            "angle": seg.angle,
            "locked": True,
            "start_elev": seg.start_elevation,
            "end_elev": seg.end_elevation,
            "source_long_node_index": seg.source_long_node_index,
        }
        if seg.arc_geometry is not None:
            legacy_seg["arc_geometry"] = seg.arc_geometry
        legacy_segments.append(legacy_seg)

    panel.from_dict({
        "segments": legacy_segments,
        "longitudinal_nodes": [node.to_dict() for node in long_nodes],
    })

    straight_seg = next(
        seg for seg in panel.segments
        if seg.direction == SegmentDirection.LONGITUDINAL and seg.segment_type == SegmentType.STRAIGHT
    )
    fold_seg = next(
        seg for seg in panel.segments
        if seg.direction == SegmentDirection.LONGITUDINAL and seg.segment_type == SegmentType.FOLD
    )

    assert len(straight_seg.coordinates) == 2
    assert len(fold_seg.coordinates) == 3

    panel.deleteLater()


def test_from_dict_migrates_legacy_plan_arc_geometry(monkeypatch):
    """旧平面特征点缺 arc_geometry 时，加载后应自动补齐并按圆弧绘制。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )

    panel.from_dict({
        "plan_feature_points": _make_legacy_plan_feature_point_dicts(),
        "plan_total_length": _make_plan_arc_points()[-1].chainage,
        "plan_source": "dxf",
    })

    arc_point = next(point for point in panel.plan_feature_points if point.turn_type == TurnType.ARC)
    bend_segment = next(seg for seg in panel.plan_segments if seg.segment_type == SegmentType.BEND)
    sampled = panel.canvas._get_plan_path_coords_for_draw()
    saved = panel.to_dict()

    assert arc_point.arc_geometry is not None
    assert bend_segment.arc_geometry is not None
    assert len(sampled) > len(panel.plan_feature_points)
    assert any(fp.get("arc_geometry") for fp in saved.get("plan_feature_points", []))

    panel.deleteLater()
