# -*- coding: utf-8 -*-
"""倒虹吸示例纵断面数据计算模式单元测试。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtWidgets import QApplication, QWidget

import app_渠系计算前端.siphon.panel as siphon_panel_mod


class _FakeWebEngineView(QWidget):
    """测试替身：避免无头环境下 QWebEngineView 崩溃。"""

    def setHtml(self, *_args, **_kwargs):
        return None


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _make_two_plan_points():
    return [
        siphon_panel_mod.PlanFeaturePoint(chainage=0.0, x=0.0, y=0.0),
        siphon_panel_mod.PlanFeaturePoint(chainage=100.0, x=100.0, y=0.0),
    ]


def test_example_longitudinal_is_ignored_in_calc(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "QWebEngineView", _FakeWebEngineView)

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)
    panel._suppress_result_display = True
    panel.plan_feature_points = _make_two_plan_points()
    panel.inc_cb.setChecked(False)
    monkeypatch.setattr(panel, "_validate_v_before_calc", lambda: True)
    monkeypatch.setattr(panel, "_validate_num_pipes_before_calc", lambda: True)
    monkeypatch.setattr(
        panel,
        "_get_global_params",
        lambda: siphon_panel_mod.GlobalParameters(Q=10.0, v_guess=2.0),
    )

    # 初始状态应为“示例纵断面”
    assert panel._longitudinal_is_example is True
    assert any(s.direction != siphon_panel_mod.SegmentDirection.COMMON for s in panel.segments)

    captured = {}

    def _fake_execute(_params, segments, **kwargs):
        captured["segments"] = segments
        captured["longitudinal_nodes"] = kwargs.get("longitudinal_nodes", None)
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

    panel._execute_calculation()

    assert captured["longitudinal_nodes"] == []
    assert all(
        s.direction == siphon_panel_mod.SegmentDirection.COMMON
        for s in captured["segments"]
    )

    panel.deleteLater()


def test_data_status_shows_plan_only_when_longitudinal_is_example(monkeypatch):
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "QWebEngineView", _FakeWebEngineView)

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)
    panel.plan_feature_points = _make_two_plan_points()

    panel._update_data_status()

    status_text = panel.lbl_data_status.text()
    assert "仅平面估算" in status_text
    assert "平面+纵断面（空间合并）" not in status_text

    panel.deleteLater()
