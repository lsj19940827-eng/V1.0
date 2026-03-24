# -*- coding: utf-8 -*-
"""倒虹吸平面 DXF 反向能力测试。"""

import math
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TEST_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_SIPHON_ROOT = os.path.join(_ROOT, "倒虹吸水力计算系统")
if _SIPHON_ROOT not in sys.path:
    sys.path.insert(0, _SIPHON_ROOT)

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QModelIndex

import app_渠系计算前端.siphon.panel as siphon_panel_mod
from dxf_parser import DxfParser
from siphon_models import PlanFeaturePoint, SegmentDirection, SegmentType, StructureSegment, TurnType
from spatial_merger import SpatialMerger


class _FakeWebView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.html = ""

    def setHtml(self, html, *_args, **_kwargs):
        self.html = html


def _fake_web_view_factory(parent=None):
    return _FakeWebView(parent)


class _InfoBarSpy:
    successes = []
    warnings = []
    errors = []

    @classmethod
    def reset(cls):
        cls.successes = []
        cls.warnings = []
        cls.errors = []

    @staticmethod
    def success(*args, **kwargs):
        _InfoBarSpy.successes.append((args, kwargs))

    @staticmethod
    def warning(*args, **kwargs):
        _InfoBarSpy.warnings.append((args, kwargs))

    @staticmethod
    def error(*args, **kwargs):
        _InfoBarSpy.errors.append((args, kwargs))


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _make_straight_plan_points():
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
            turn_type=TurnType.NONE,
            ip_index=1,
        ),
    ]


def _make_straight_plan_segment():
    return StructureSegment(
        segment_type=SegmentType.STRAIGHT,
        direction=SegmentDirection.PLAN,
        length=10.0,
        coordinates=[(0.0, 0.0), (10.0, 0.0)],
        locked=True,
    )


def _make_panel(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    monkeypatch.setattr(siphon_panel_mod, "InfoBar", _InfoBarSpy)
    monkeypatch.setattr(
        siphon_panel_mod,
        "InfoBarPosition",
        SimpleNamespace(TOP="TOP", TOP_RIGHT="TOP_RIGHT"),
    )
    _InfoBarSpy.reset()
    return siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )


def test_reverse_plan_geometry_swaps_endpoints_and_recomputes_chainage():
    points = _make_straight_plan_points()

    reversed_points, reversed_segments, total_length = DxfParser.reverse_plan_geometry(points)

    assert len(reversed_points) == 2
    assert math.isclose(total_length, 10.0, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(reversed_points[0].chainage, 0.0, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(reversed_points[-1].chainage, 10.0, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(reversed_points[0].x, 10.0, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(reversed_points[-1].x, 0.0, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(reversed_points[0].azimuth_meas_deg, 270.0, rel_tol=0.0, abs_tol=1e-9)
    assert len(reversed_segments) == 1
    assert reversed_segments[0].segment_type == SegmentType.STRAIGHT
    assert reversed_segments[0].coordinates == [(10.0, 0.0), (0.0, 0.0)]


def test_reverse_plan_geometry_keeps_arc_fold_data_usable_for_spatial_merger():
    sample_path = os.path.join(
        _ROOT, "倒虹吸水力计算系统", "resources", "导入纵断面dxf示例.dxf"
    )
    plan_points, _plan_segments, _msg = DxfParser.parse_plan_polyline(sample_path)
    long_nodes, _long_msg = DxfParser.parse_longitudinal_profile(sample_path, chainage_offset=0.0)

    reversed_points, reversed_segments, total_length = DxfParser.reverse_plan_geometry(plan_points)

    assert total_length > 0
    assert len(reversed_points) == len(plan_points)
    assert any(seg.segment_type == SegmentType.BEND for seg in reversed_segments)
    assert any(seg.segment_type == SegmentType.FOLD for seg in reversed_segments)
    assert all(
        reversed_points[idx].chainage < reversed_points[idx + 1].chainage
        for idx in range(len(reversed_points) - 1)
    )

    result = SpatialMerger.merge_and_compute(reversed_points, long_nodes, verbose=False)
    assert result.nodes, "反向后的平面点仍应可参与空间合并"


def test_reverse_button_visibility_tracks_dxf_plan_source(monkeypatch):
    panel = _make_panel(monkeypatch)

    panel._refresh_plan_reverse_button()
    assert panel.btn_reverse_plan.isHidden()

    panel.plan_feature_points = _make_straight_plan_points()
    panel.plan_segments = [_make_straight_plan_segment()]
    panel.plan_total_length = 10.0
    panel._plan_source = "dxf"
    panel._refresh_plan_reverse_button()
    assert not panel.btn_reverse_plan.isHidden()

    panel._plan_source = "water_profile"
    panel._refresh_plan_reverse_button()
    assert panel.btn_reverse_plan.isHidden()

    panel.deleteLater()


def test_import_plan_dxf_success_message_mentions_reverse_action(monkeypatch):
    panel = _make_panel(monkeypatch)
    monkeypatch.setattr(
        siphon_panel_mod.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *_args, **_kwargs: ("fake-plan.dxf", "DXF文件 (*.dxf)")),
    )
    monkeypatch.setattr(
        siphon_panel_mod.DxfParser,
        "parse_plan_polyline",
        staticmethod(lambda _path: (_make_straight_plan_points(), [_make_straight_plan_segment()], "成功解析")),
    )

    panel._import_plan_dxf()

    assert _InfoBarSpy.successes, "导入成功后应给出成功提示"
    success_args, _success_kwargs = _InfoBarSpy.successes[-1]
    assert "平面反向" in success_args[1]
    assert panel._plan_source == "dxf"
    assert not panel.btn_reverse_plan.isHidden()

    panel.deleteLater()


def test_reverse_plan_rebuilds_from_feature_points_and_undo_restores_dirty_state(monkeypatch):
    panel = _make_panel(monkeypatch)
    panel.plan_feature_points = _make_straight_plan_points()
    panel.plan_segments = [
        StructureSegment(
            segment_type=SegmentType.STRAIGHT,
            direction=SegmentDirection.PLAN,
            length=9.5,
            coordinates=[(0.0, 0.0), (9.5, 0.0)],
            locked=True,
        )
    ]
    panel.plan_total_length = 10.0
    panel._plan_source = "dxf"
    panel._plan_segments_dirty_since_import = True
    panel._refresh_plan_reverse_button()

    panel._reverse_plan_dxf()

    assert math.isclose(panel.plan_feature_points[0].x, 10.0, rel_tol=0.0, abs_tol=1e-9)
    assert math.isclose(panel.plan_feature_points[-1].x, 0.0, rel_tol=0.0, abs_tol=1e-9)
    assert panel._plan_segments_dirty_since_import is False
    success_args, _success_kwargs = _InfoBarSpy.successes[-1]
    assert "手工平面段修改已被覆盖" in success_args[1]

    _InfoBarSpy.reset()
    panel._undo_plan_import()
    assert math.isclose(panel.plan_feature_points[0].x, 0.0, rel_tol=0.0, abs_tol=1e-9)
    assert panel._plan_segments_dirty_since_import is True

    panel.deleteLater()


def test_deleting_dxf_plan_segment_marks_dirty(monkeypatch):
    panel = _make_panel(monkeypatch)
    monkeypatch.setattr(siphon_panel_mod, "fluent_question", lambda *_args, **_kwargs: True)

    panel.plan_feature_points = _make_straight_plan_points()
    panel.plan_segments = [_make_straight_plan_segment()]
    panel.plan_total_length = 10.0
    panel._plan_source = "dxf"
    panel._plan_segments_dirty_since_import = False
    panel._refresh_seg_table()

    plan_row = None
    for row in range(panel.seg_table.rowCount()):
        category_item = panel.seg_table.item(row, 1)
        if category_item and category_item.text() == "平面":
            plan_row = row
            break

    assert plan_row is not None, "应存在平面段表格行"
    panel.seg_table.selectRow(plan_row)

    panel._del_segment()

    assert panel._plan_segments_dirty_since_import is True
    panel.deleteLater()


def test_reverse_button_caption_is_plainly_exposed_for_plan_reverse_entry(monkeypatch):
    panel = _make_panel(monkeypatch)

    assert panel.btn_reverse_plan.text() == "平面反向"
    assert panel.btn_reverse_plan.isHidden() is True

    panel.deleteLater()
