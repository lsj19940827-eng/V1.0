# -*- coding: utf-8 -*-
"""倒虹吸通用构件补齐逻辑单元测试。"""

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


def _reset_blank_state(panel):
    """把面板整理成空白态，便于单独验证补齐逻辑。"""
    panel.segments = []
    panel.plan_segments = []
    panel.plan_feature_points = []
    panel.plan_total_length = 0.0
    panel.longitudinal_nodes = []
    panel._longitudinal_is_example = False
    if hasattr(panel, "long_table"):
        panel.long_table.setRowCount(0)


def _common_segments(panel):
    """提取当前所有通用构件。"""
    return [
        seg for seg in panel.segments
        if seg.direction == siphon_panel_mod.SegmentDirection.COMMON
    ]


def _common_types(panel):
    """提取当前通用构件类型顺序。"""
    return [seg.segment_type for seg in _common_segments(panel)]


def _segment_by_type(panel, segment_type):
    """按类型获取单个通用构件。"""
    matches = [seg for seg in _common_segments(panel) if seg.segment_type == segment_type]
    assert len(matches) == 1
    return matches[0]


def test_init_default_segments_fills_exactly_seven_common_types(panel):
    """补齐通用构件后，应得到且只得到 7 类默认通用构件。"""
    _reset_blank_state(panel)

    panel._init_default_segments()

    assert _common_types(panel) == [
        siphon_panel_mod.SegmentType.INLET,
        siphon_panel_mod.SegmentType.TRASH_RACK,
        siphon_panel_mod.SegmentType.GATE_SLOT,
        siphon_panel_mod.SegmentType.BYPASS_PIPE,
        siphon_panel_mod.SegmentType.PIPE_TRANSITION,
        siphon_panel_mod.SegmentType.OTHER,
        siphon_panel_mod.SegmentType.OUTLET,
    ]
    assert len(_common_segments(panel)) == 7


def test_init_default_segments_is_idempotent_and_preserves_existing_values(panel):
    """重复补齐时，不应重复插入，也不应覆盖已改过的通用构件值。"""
    _reset_blank_state(panel)
    panel._init_default_segments()

    gate_slot = _segment_by_type(panel, siphon_panel_mod.SegmentType.GATE_SLOT)
    other = _segment_by_type(panel, siphon_panel_mod.SegmentType.OTHER)
    pipe_transition = _segment_by_type(panel, siphon_panel_mod.SegmentType.PIPE_TRANSITION)

    gate_slot.xi_user = 0.42
    other.xi_user = 1.23
    other.custom_label = "保留原值"
    pipe_transition.xi_user = 0.77

    panel._init_default_segments()

    assert len(_common_segments(panel)) == 7
    assert _segment_by_type(panel, siphon_panel_mod.SegmentType.GATE_SLOT).xi_user == 0.42
    assert _segment_by_type(panel, siphon_panel_mod.SegmentType.OTHER).xi_user == 1.23
    assert _segment_by_type(panel, siphon_panel_mod.SegmentType.OTHER).custom_label == "保留原值"
    assert _segment_by_type(panel, siphon_panel_mod.SegmentType.PIPE_TRANSITION).xi_user == 0.77
