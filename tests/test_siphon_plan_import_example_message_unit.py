# -*- coding: utf-8 -*-
"""倒虹吸平面 DXF 导入提示与空白启动口径一致性测试。"""

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

import app_渠系计算前端.siphon.panel as siphon_panel_mod
from siphon_models import PlanFeaturePoint, SegmentDirection, SegmentType, StructureSegment


class _FakeWebView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.html = ""

    def setHtml(self, html, *_args, **_kwargs):
        self.html = html


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


def _fake_web_view_factory(parent=None):
    return _FakeWebView(parent)


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _make_plan_points():
    return [
        PlanFeaturePoint(chainage=0.0, x=0.0, y=0.0),
        PlanFeaturePoint(chainage=100.0, x=100.0, y=0.0),
    ]


def _make_plan_segment():
    return StructureSegment(
        segment_type=SegmentType.STRAIGHT,
        direction=SegmentDirection.PLAN,
        length=100.0,
        coordinates=[(0.0, 0.0), (100.0, 0.0)],
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
    panel = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    assert panel._longitudinal_is_example is False
    assert panel.longitudinal_nodes == []
    return panel


def _stub_plan_import(monkeypatch):
    monkeypatch.setattr(
        siphon_panel_mod.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *_args, **_kwargs: ("fake-plan.dxf", "DXF文件 (*.dxf)")),
    )
    monkeypatch.setattr(
        siphon_panel_mod.DxfParser,
        "parse_plan_polyline",
        staticmethod(lambda _path: (_make_plan_points(), [_make_plan_segment()], "成功解析")),
    )


def test_import_plan_dxf_success_message_ignores_example_longitudinal(monkeypatch):
    panel = _make_panel(monkeypatch)
    _stub_plan_import(monkeypatch)

    panel._import_plan_dxf()

    assert _InfoBarSpy.successes, "导入成功后应给出成功提示"
    success_args, _success_kwargs = _InfoBarSpy.successes[-1]
    message = success_args[1]
    assert "未检测到纵断面数据，将使用平面独立计算模式" in message
    assert "已检测到纵断面数据，将使用平面+纵断面独立叠加计算" not in message

    panel.deleteLater()


def test_import_plan_dxf_example_longitudinal_stays_consistent_with_status_and_calc(monkeypatch):
    panel = _make_panel(monkeypatch)
    _stub_plan_import(monkeypatch)
    panel._suppress_result_display = True
    panel.inc_cb.setChecked(False)
    monkeypatch.setattr(panel, "_validate_v_before_calc", lambda: True)
    monkeypatch.setattr(panel, "_validate_num_pipes_before_calc", lambda: True)
    monkeypatch.setattr(
        panel,
        "_get_global_params",
        lambda: siphon_panel_mod.GlobalParameters(Q=10.0, v_guess=2.0),
    )

    captured = {}

    def _fake_execute(_params, segments, **kwargs):
        captured["segments"] = segments
        captured["longitudinal_nodes"] = kwargs.get("longitudinal_nodes")
        return siphon_panel_mod.CalculationResult(
            diameter=1.0,
            velocity=1.0,
            total_head_loss=1.0,
            velocity_channel_in=1.0,
            velocity_pipe_in=1.0,
            velocity_outlet_start=1.0,
            velocity_channel_out=1.0,
            increase_percent=0.0,
        )

    monkeypatch.setattr(siphon_panel_mod.HydraulicCore, "execute_calculation", _fake_execute)

    panel._import_plan_dxf()
    panel._execute_calculation()

    status_text = panel.lbl_data_status.text()
    assert "仅平面（独立计算）" in status_text
    assert "仅平面估算" not in status_text
    assert "传统模式" not in status_text
    assert captured["longitudinal_nodes"] == []
    assert all(
        seg.direction == SegmentDirection.COMMON for seg in captured["segments"]
    )
    assert len(captured["segments"]) == 7

    panel.deleteLater()
