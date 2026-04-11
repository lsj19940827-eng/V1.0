# -*- coding: utf-8 -*-
"""水面线面板渠道名称输入框宽度回归测试。"""

import importlib.util
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtWidgets import QApplication


def _get_qapp():
    """获取测试使用的 Qt 应用实例。"""
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 4):
    """刷新事件循环，保证界面尺寸已经稳定。"""
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _load_panel_class():
    """按文件路径加载水面线面板类。"""
    panel_path = next(Path(".").glob("**/water_profile/panel.py")).resolve()
    spec = importlib.util.spec_from_file_location("wp_channel_name_width_regression", panel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WaterProfilePanel


def _build_panel(width: int = 1400, height: int = 900):
    """创建一个用于布局回归验证的水面线面板。"""
    _get_qapp()
    panel_cls = _load_panel_class()
    panel = panel_cls()
    panel.resize(width, height)
    panel.show()
    _flush_events()
    return panel


def test_channel_name_input_reserves_room_for_five_chinese_characters():
    """渠道名称输入框应能一次性容纳 5 个汉字和基础留白。"""
    panel = _build_panel()
    try:
        edit = panel.channel_name_edit
        sample_name = "九龙水库右"
        # 预留文字宽度之外，再给输入光标和左右留白留出缓冲。
        required_width = edit.fontMetrics().horizontalAdvance(sample_name) + 34

        assert edit.width() >= required_width
        assert edit.minimumWidth() >= required_width
    finally:
        panel.close()
        panel.deleteLater()
