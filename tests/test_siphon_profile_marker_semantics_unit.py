# -*- coding: utf-8 -*-
"""倒虹吸纵断面转弯点语义单元测试。"""

import math
import os
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SIPHON_ROOT = ROOT / "倒虹吸水力计算系统"
if str(SIPHON_ROOT) not in sys.path:
    sys.path.insert(0, str(SIPHON_ROOT))

from app_渠系计算前端.siphon.canvas_view import PipelineCanvas
from arc_geometry import arc_midpoint
from siphon_models import SegmentDirection, SegmentType, StructureSegment


def _get_qapp():
    """确保测试环境下存在 Qt 应用实例。"""
    return QApplication.instance() or QApplication([])


def _make_bend_segment():
    """构造一段带真实圆弧几何的纵断面弯管。"""
    return StructureSegment(
        segment_type=SegmentType.BEND,
        direction=SegmentDirection.LONGITUDINAL,
        length=10.0 * math.pi / 2.0,
        radius=10.0,
        angle=90.0,
        coordinates=[(10.0, 100.0), (20.0, 90.0)],
        start_elevation=100.0,
        end_elevation=90.0,
        arc_geometry={
            "kind": "profile",
            "mode": "dxf_segment",
            "start": [10.0, 100.0],
            "end": [20.0, 90.0],
            "center": [10.0, 90.0],
            "radius": 10.0,
            "sweep_rad": math.pi / 2.0,
            "clockwise": True,
            "start_chainage": 10.0,
            "end_chainage": 20.0,
        },
    )


def _make_fold_segment():
    """构造一段折管。"""
    return StructureSegment(
        segment_type=SegmentType.FOLD,
        direction=SegmentDirection.LONGITUDINAL,
        length=20.0,
        angle=45.0,
        coordinates=[(40.0, 90.0), (50.0, 100.0), (60.0, 100.0)],
        start_elevation=90.0,
        end_elevation=100.0,
    )


def _make_straight_segment():
    """构造一段普通直管。"""
    return StructureSegment(
        segment_type=SegmentType.STRAIGHT,
        direction=SegmentDirection.LONGITUDINAL,
        length=30.0,
        coordinates=[(0.0, 110.0), (30.0, 110.0)],
        start_elevation=110.0,
        end_elevation=110.0,
    )


def test_profile_marker_specs_use_two_green_boundaries_and_one_orange_anchor_for_bend():
    """弯管应输出两个边界绿点和一个圆弧中点橙点。"""
    _get_qapp()
    canvas = PipelineCanvas()
    bend_segment = _make_bend_segment()
    canvas.set_data(segments=[bend_segment], longitudinal_is_example=False)

    marker_specs = canvas._get_profile_marker_specs()

    boundary_specs = [
        spec for spec in marker_specs
        if spec["marker_role"] in ("bend_boundary_start", "bend_boundary_end")
    ]
    assert [spec["coord"] for spec in boundary_specs] == [
        (10.0, 100.0),
        (20.0, 90.0),
    ]
    assert [spec["elevation"] for spec in boundary_specs] == [100.0, 90.0]
    assert all(spec["angle_text"] is None for spec in boundary_specs)

    bend_anchor = next(
        spec for spec in marker_specs
        if spec["marker_role"] == "bend_anchor"
    )
    assert bend_anchor["coord"] == pytest.approx(arc_midpoint(bend_segment.arc_geometry))
    assert bend_anchor["angle_text"] == "弯管 90.000°"
    assert bend_anchor["elevation"] is None


def test_profile_marker_specs_keep_only_orange_fold_anchor_and_skip_straight_green_nodes():
    """折管只保留一个橙点，普通直管不再产生绿点。"""
    _get_qapp()
    canvas = PipelineCanvas()
    canvas.set_data(
        segments=[_make_straight_segment(), _make_fold_segment()],
        longitudinal_is_example=False,
    )

    marker_specs = canvas._get_profile_marker_specs()

    assert not any(spec["segment_type"] == SegmentType.STRAIGHT for spec in marker_specs)
    assert not any(spec["marker_role"].startswith("bend_boundary") for spec in marker_specs)

    fold_anchor = next(
        spec for spec in marker_specs
        if spec["marker_role"] == "fold_anchor"
    )
    assert fold_anchor["coord"] == (50.0, 100.0)
    assert fold_anchor["elevation"] == 100.0
    assert fold_anchor["angle_text"] == "折管 45.000°"
