# -*- coding: utf-8 -*-
"""倒虹吸空白启动态计算模式单元测试。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtWidgets import QApplication, QWidget

import app_渠系计算前端.siphon.panel as siphon_panel_mod


class _FakeWebEngineView(QWidget):
    """测试替身：避免无头环境下 QWebEngineView 崩溃。"""

    def setHtml(self, *_args, **_kwargs):
        return None


def _fake_web_view_factory(parent=None):
    """返回假的网页视图。"""
    return _FakeWebEngineView(parent)


def _get_qapp():
    """获取或创建 QApplication。"""
    return QApplication.instance() or QApplication([])


def _make_two_plan_points():
    """构造两个人工平面特征点。"""
    return [
        siphon_panel_mod.PlanFeaturePoint(chainage=0.0, x=0.0, y=0.0),
        siphon_panel_mod.PlanFeaturePoint(chainage=100.0, x=100.0, y=0.0),
    ]


def test_blank_longitudinal_state_is_not_counted_as_real_data(monkeypatch):
    """空白启动态不应被识别成可参与叠加计算的真实纵断面。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)

    assert panel.longitudinal_nodes == []
    assert panel._has_real_longitudinal_data() is False
    assert "longitudinal" not in [
        source for _, source in panel._get_all_display_segments()
    ]

    panel.deleteLater()


def test_data_status_shows_blank_without_plan_or_longitudinal_data(monkeypatch):
    """新建空白面板时，状态栏应明确显示没有平面和纵断面数据。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)

    panel._update_data_status()

    status_text = panel.lbl_data_status.text()
    assert "无平面/纵断面数据" in status_text
    assert "仅平面（独立计算）" not in status_text
    assert "仅纵断面（独立计算）" not in status_text

    panel.deleteLater()


def test_data_status_shows_plan_only_when_only_plan_data_exists(monkeypatch):
    """只有平面特征点时，状态栏仍应显示仅平面模式。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)

    panel = siphon_panel_mod.SiphonPanel(show_case_management=False, disable_autosave_load=True)
    panel.plan_feature_points = _make_two_plan_points()

    panel._update_data_status()

    status_text = panel.lbl_data_status.text()
    assert "仅平面（独立计算）" in status_text
    assert "平面+纵断面（独立叠加）" not in status_text
    assert "仅纵断面（独立计算）" not in status_text

    panel.deleteLater()
