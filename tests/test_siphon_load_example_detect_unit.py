# -*- coding: utf-8 -*-
"""倒虹吸旧示例数据识别为空白态的单元测试。"""

import os

import pytest
from PySide6.QtWidgets import QApplication, QWidget

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

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


def _make_panel(monkeypatch):
    """创建关闭自动加载后的倒虹吸面板。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    return siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )


def _assert_blank_longitudinal_state(panel):
    """断言当前被识别为空白而不是已导入真实纵断面。"""
    panel._update_data_status()

    assert panel.longitudinal_nodes == []
    assert panel._has_real_longitudinal_data() is False
    assert "无平面/纵断面数据" in panel.lbl_data_status.text()
    assert "longitudinal_nodes" not in panel.to_dict()
    assert all(source != "longitudinal" for _, source in panel._get_all_display_segments())


def test_loading_payload_without_longitudinal_nodes_stays_blank(monkeypatch):
    """旧内置示例工况这类未保存纵断面节点的数据，加载后应保持空白。"""
    panel = _make_panel(monkeypatch)

    try:
        panel.from_dict(
            {
                "Q": 1.0,
                "segments": [],
                "plan_segments": [],
                "plan_feature_points": [],
                "plan_total_length": 0.0,
            }
        )

        _assert_blank_longitudinal_state(panel)
    finally:
        panel.deleteLater()


def test_loading_saved_example_longitudinal_is_treated_as_blank(monkeypatch):
    """旧版被保存下来的示例纵断面数据，重新加载后应被识别为空白。"""
    target_panel = _make_panel(monkeypatch)

    try:
        legacy_payload = {
            "Q": 1.0,
            "segments": [],
            "plan_segments": [],
            "plan_feature_points": [],
            "plan_total_length": 0.0,
            "longitudinal_nodes": [
                {"chainage": 0.0, "elevation": 113.843926, "slope_before": 0.0, "slope_after": -0.356123},
                {"chainage": 45.712018, "elevation": 96.839824, "turn_type": "圆弧", "vertical_curve_radius": 5.0, "turn_angle": 25.455508, "slope_before": -0.356123, "slope_after": -0.800406, "arc_center_s": 43.968801, "arc_center_z": 92.153546, "arc_end_chainage": 47.556994, "arc_theta_rad": 0.444282},
                {"chainage": 47.556994, "elevation": 95.635625, "slope_before": -0.800406, "slope_after": -0.800406},
                {"chainage": 79.544004, "elevation": 62.673827, "turn_type": "折线", "turn_angle": 13.905975, "slope_before": -0.800406, "slope_after": -0.557701},
                {"chainage": 100.454474, "elevation": 49.630903, "turn_type": "圆弧", "vertical_curve_radius": 5.0, "turn_angle": 31.953888, "slope_before": -0.557701, "slope_after": 0.0, "arc_center_s": 103.100657, "arc_center_z": 53.873275, "arc_end_chainage": 103.100657, "arc_theta_rad": 0.557701},
                {"chainage": 103.100657, "elevation": 48.873275, "slope_before": -0.0, "slope_after": -0.0},
                {"chainage": 145.103537, "elevation": 48.873275, "turn_type": "圆弧", "vertical_curve_radius": 5.0, "turn_angle": 37.384346, "slope_before": 0.0, "slope_after": 0.65248, "arc_center_s": 145.103537, "arc_center_z": 53.873275, "arc_end_chainage": 148.139331, "arc_theta_rad": 0.65248},
                {"chainage": 148.139331, "elevation": 49.900372, "slope_before": 0.65248, "slope_after": 0.65248},
                {"chainage": 180.860185, "elevation": 74.903192, "turn_type": "圆弧", "vertical_curve_radius": 5.0, "turn_angle": 10.329722, "slope_before": 0.65248, "slope_after": 0.472192, "arc_center_s": 183.895979, "arc_center_z": 70.930289, "arc_end_chainage": 181.62178, "arc_theta_rad": 0.180288},
                {"chainage": 181.62178, "elevation": 75.383155, "slope_before": 0.472192, "slope_after": 0.472192},
                {"chainage": 211.582699, "elevation": 90.685004, "turn_type": "圆弧", "vertical_curve_radius": 5.0, "turn_angle": 10.128511, "slope_before": 0.472192, "slope_after": 0.295416, "arc_center_s": 213.856898, "arc_center_z": 86.232137, "arc_end_chainage": 212.401207, "arc_theta_rad": 0.176776},
                {"chainage": 212.401207, "elevation": 91.015542, "slope_before": 0.295416, "slope_after": 0.295416},
                {"chainage": 249.872603, "elevation": 102.41888, "slope_before": 0.295416, "slope_after": 0.0},
            ],
        }

        target_panel.from_dict(legacy_payload)

        _assert_blank_longitudinal_state(target_panel)
    finally:
        target_panel.deleteLater()


def test_loading_payload_marked_as_example_clears_even_when_nodes_drift(monkeypatch):
    """只要旧数据标记为示例纵断面，即使节点有漂移也应按空白处理。"""
    source_panel = _make_panel(monkeypatch)
    target_panel = _make_panel(monkeypatch)

    try:
        source_panel._add_example_longitudinal()
        source_panel._longitudinal_is_example = False
        legacy_payload = source_panel.to_dict()
        legacy_payload["longitudinal_is_example"] = True
        legacy_payload["longitudinal_nodes"][3]["elevation"] += 1.0

        target_panel.from_dict(legacy_payload)

        _assert_blank_longitudinal_state(target_panel)
    finally:
        source_panel.deleteLater()
        target_panel.deleteLater()
