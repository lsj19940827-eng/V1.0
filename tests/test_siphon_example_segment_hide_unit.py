# -*- coding: utf-8 -*-
"""倒虹吸启动空白态相关单元测试。"""

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


@pytest.fixture
def panel(monkeypatch):
    """创建关闭自动加载后的倒虹吸面板。"""
    _get_qapp()
    monkeypatch.setattr(siphon_panel_mod, "create_web_view", _fake_web_view_factory)
    widget = siphon_panel_mod.SiphonPanel(
        show_case_management=False,
        disable_autosave_load=True,
    )
    yield widget
    widget.deleteLater()


def _display_sources(panel):
    """提取结构段表实际展示的数据来源。"""
    return [source for _, source in panel._get_all_display_segments()]


def test_new_panel_starts_blank_without_example_longitudinal_nodes(panel):
    """新建面板后不应再自动带入 13 个示例纵断面节点。"""
    panel._update_data_status()

    assert panel.longitudinal_nodes == []
    assert panel.plan_feature_points == []
    assert panel.plan_segments == []
    assert panel.plan_total_length == 0.0
    assert panel._has_real_longitudinal_data() is False
    assert "无平面/纵断面数据" in panel.lbl_data_status.text()


def test_blank_panel_does_not_display_plan_or_longitudinal_segments(panel):
    """空白面板的结构段展示里不应混入平面段或纵断面段。"""
    panel._refresh_seg_table()

    sources = _display_sources(panel)

    assert "plan" not in sources
    assert "longitudinal" not in sources
