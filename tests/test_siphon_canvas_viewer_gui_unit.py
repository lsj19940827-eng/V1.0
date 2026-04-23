# -*- coding: utf-8 -*-
"""倒虹吸画布适配与详情查看器 GUI 单元测试。"""

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "倒虹吸水力计算系统"))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

import app_渠系计算前端.siphon.panel as siphon_panel_mod
from app_渠系计算前端.siphon.canvas_view import PipelineCanvas, build_profile_footer_info
from dxf_parser import DxfParser
from siphon_models import PlanFeaturePoint, SegmentType, TurnType


class _FakeWebView(QWidget):
    def setHtml(self, *_args, **_kwargs):
        return None


def _fake_web_view_factory(parent=None):
    return _FakeWebView(parent)


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _make_vertical_plan_points():
    return [
        PlanFeaturePoint(
            chainage=0.0,
            x=0.0,
            y=0.0,
            azimuth_meas_deg=0.0,
            turn_type=TurnType.NONE,
            ip_index=0,
        ),
        PlanFeaturePoint(
            chainage=150.0,
            x=5.0,
            y=150.0,
            azimuth_meas_deg=90.0,
            turn_type=TurnType.NONE,
            ip_index=1,
        ),
        PlanFeaturePoint(
            chainage=300.0,
            x=10.0,
            y=300.0,
            azimuth_meas_deg=90.0,
            turn_type=TurnType.NONE,
            ip_index=2,
        ),
    ]


def _make_horizontal_plan_points():
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
            chainage=160.0,
            x=160.0,
            y=8.0,
            azimuth_meas_deg=90.0,
            turn_type=TurnType.NONE,
            ip_index=1,
        ),
        PlanFeaturePoint(
            chainage=320.0,
            x=320.0,
            y=14.0,
            azimuth_meas_deg=90.0,
            turn_type=TurnType.NONE,
            ip_index=2,
        ),
    ]


def _make_panel(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    panel.show()
    _flush_events(4)
    return panel


def _sample_dxf_path() -> str:
    return str(ROOT / "倒虹吸水力计算系统" / "resources" / "导入纵断面dxf示例.dxf")


def test_preview_toolbar_buttons_are_tall_enough_for_text(monkeypatch):
    """预览工具栏按钮高度要能完整显示中文文字。"""
    panel = _make_panel(monkeypatch)
    toolbar_texts = ["纵断面", "平面图", "＋", "－", "适配", "展开"]

    for text in toolbar_texts:
        button = next(
            (btn for btn in panel.findChildren(QPushButton) if btn.text() == text),
            None,
        )
        assert button is not None
        required_height = max(32, button.sizeHint().height(), button.minimumSizeHint().height())
        assert button.height() >= required_height

    panel.close()
    panel.deleteLater()


def test_fit_to_content_resets_navigation_for_vertical_plan_data():
    _get_qapp()
    canvas = PipelineCanvas()
    canvas.resize(640, 220)
    canvas.set_view_mode("plan")
    canvas.set_data(plan_feature_points=_make_vertical_plan_points(), plan_total_length=300.0)

    bounds_getter = getattr(canvas, "content_bounds", None)
    assert callable(bounds_getter)
    bounds = bounds_getter()
    assert bounds is not None
    assert bounds[:2] == (0.0, 10.0)
    assert bounds[2:] == (0.0, 300.0)

    canvas._zoom = 3.2
    canvas._pan_x = 120.0
    canvas._pan_y = -85.0

    fit_to_content = getattr(canvas, "fit_to_content", None)
    assert callable(fit_to_content)
    fit_to_content()

    assert canvas._zoom < 3.2
    assert math.isclose(canvas._pan_x, 0.0, abs_tol=1e-6)
    assert math.isclose(canvas._pan_y, 0.0, abs_tol=1e-6)

    canvas.deleteLater()


def test_content_bounds_support_horizontal_plan_data():
    _get_qapp()
    canvas = PipelineCanvas()
    canvas.resize(640, 220)
    canvas.set_view_mode("plan")
    canvas.set_data(plan_feature_points=_make_horizontal_plan_points(), plan_total_length=320.0)

    bounds_getter = getattr(canvas, "content_bounds", None)
    assert callable(bounds_getter)
    bounds = bounds_getter()

    assert bounds is not None
    assert bounds[:2] == (0.0, 320.0)
    assert bounds[2:] == (0.0, 14.0)

    canvas.deleteLater()


def test_double_click_requests_detail_view():
    _get_qapp()
    canvas = PipelineCanvas()
    canvas.resize(640, 220)
    canvas.show()
    _flush_events(2)

    signal = getattr(canvas, "open_detail_requested", None)
    assert signal is not None

    triggered = []
    signal.connect(lambda: triggered.append("open"))

    QTest.mouseDClick(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(80, 80))
    _flush_events(4)

    assert triggered == ["open"]

    canvas.deleteLater()


def test_panel_expand_button_reuses_single_non_modal_viewer_and_inherits_mode(monkeypatch):
    panel = _make_panel(monkeypatch)
    panel.plan_feature_points = _make_vertical_plan_points()
    panel.plan_total_length = 300.0
    panel._do_update_canvas()
    panel._switch_view("plan")
    _flush_events(6)

    expand_button = next(
        (btn for btn in panel.findChildren(QPushButton) if btn.text() == "展开"),
        None,
    )
    assert expand_button is not None

    QTest.mouseClick(expand_button, Qt.LeftButton)
    _flush_events(8)

    viewer = getattr(panel, "canvas_viewer", None)
    assert viewer is not None
    assert viewer.isVisible() is True
    assert viewer.isModal() is False
    assert viewer.canvas.get_view_mode() == "plan"

    first_viewer = viewer

    QTest.mouseClick(expand_button, Qt.LeftButton)
    _flush_events(6)

    assert getattr(panel, "canvas_viewer", None) is first_viewer

    if viewer is not None:
        viewer.close()
    panel.close()
    panel.deleteLater()


def test_profile_footer_counts_fold_for_rebuilt_longitudinal_segments(monkeypatch):
    panel = _make_panel(monkeypatch)
    sample_path = _sample_dxf_path()
    long_nodes, _msg = DxfParser.parse_longitudinal_profile(sample_path, chainage_offset=0.0)
    rebuilt_segments = panel._nodes_to_segments(long_nodes)

    canvas = PipelineCanvas()
    canvas.set_data(
        segments=rebuilt_segments,
        longitudinal_nodes=long_nodes,
        longitudinal_is_example=False,
    )
    pipe_segs = canvas._get_profile_pipe_segments()
    text = build_profile_footer_info(
        total_len=sum(seg.length for seg in pipe_segs if seg.length > 0),
        segment_count=len(pipe_segs),
        bend_count=sum(
            1 for seg in pipe_segs
            if seg.segment_type in (SegmentType.BEND, SegmentType.FOLD)
        ),
        min_elev=min(y for _, y in canvas._get_profile_coords_for_draw()),
        zoom=1.0,
    )

    assert "弯/折管: 6" in text
    assert "结构段: 11" in text

    canvas.deleteLater()
    panel.close()
    panel.deleteLater()
