import os
import sys
from pathlib import Path
from types import SimpleNamespace


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "倒虹吸水力计算系统"))

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import app_渠系计算前端.siphon.panel as siphon_panel_mod  # noqa: E402
from siphon_models import PlanFeaturePoint, SegmentDirection, SegmentType, StructureSegment, TurnType  # noqa: E402


class _FakeWebView(QWidget):
    def setHtml(self, *_args, **_kwargs):
        return None


def _fake_web_view_factory(parent=None):
    return _FakeWebView(parent)


class _InfoBarSpy:
    successes = []

    @classmethod
    def reset(cls):
        cls.successes = []

    @staticmethod
    def success(*args, **kwargs):
        _InfoBarSpy.successes.append((args, kwargs))


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _make_plan_points():
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


def _make_plan_segment():
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


def test_reverse_plan_success_message_uses_three_decimals(monkeypatch):
    panel = _make_panel(monkeypatch)
    panel.plan_feature_points = _make_plan_points()
    panel.plan_segments = [_make_plan_segment()]
    panel.plan_total_length = 10.0
    panel._plan_source = "dxf"

    panel._reverse_plan_dxf()

    success_args, _success_kwargs = _InfoBarSpy.successes[-1]
    assert "平面总长: 10.000m。" in success_args[1]

    panel.deleteLater()


def test_import_plan_success_message_uses_three_decimals(monkeypatch):
    panel = _make_panel(monkeypatch)
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

    panel._import_plan_dxf()

    success_args, _success_kwargs = _InfoBarSpy.successes[-1]
    assert "平面总长: 10.000m" in success_args[1]

    panel.deleteLater()
