# -*- coding: utf-8 -*-
"""表3流量段选择器回归测试。"""

import importlib.util
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtWidgets import QApplication, QWidget


def _get_qapp():
    """获取测试使用的 Qt 应用实例。"""
    return QApplication.instance() or QApplication([])


def _flush_events(rounds: int = 4):
    """刷新事件循环，确保界面状态稳定。"""
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _load_panel_class():
    """按文件路径加载水面线面板类。"""
    panel_path = next(Path(".").glob("**/water_profile/panel.py")).resolve()
    spec = importlib.util.spec_from_file_location("wp_flow_selector_regression", panel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WaterProfilePanel


def _load_project_manager_class():
    """按文件路径加载项目管理器类。"""
    manager_path = next(Path(".").glob("**/project_manager.py")).resolve()
    spec = importlib.util.spec_from_file_location("project_manager_flow_selector_regression", manager_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ProjectManager


def _build_panel(width: int = 1400, height: int = 900):
    """创建用于流量段选择器验证的水面线面板。"""
    _get_qapp()
    panel_cls = _load_panel_class()
    panel = panel_cls()
    panel.resize(width, height)
    panel.show()
    _flush_events()
    panel._adjust_splitter_for_settings()
    _flush_events()
    return panel


def test_flow_selector_defaults_to_first_segment_and_shows_summary():
    """多流量段写入后，主界面默认显示第一流量段，且不再显示段数提示。"""
    panel = _build_panel()
    try:
        panel.design_flow_edit.setText("120.8, 78.8, 9.8")
        panel.max_flow_edit.setText("150.9, 98.5, 12.25")
        panel._sync_flow_segment_widgets(reset_index=True)
        _flush_events()

        assert panel._flow_segment_current_index == 0
        assert panel.design_flow_edit.summary_text() == "第一流量段 · 120.8"
        assert panel.max_flow_edit.summary_text() == "第一流量段 · 150.9"
        assert panel.design_flow_edit.count_text() == ""
        assert panel.max_flow_edit.count_text() == ""
        assert not panel.design_flow_edit._inline_hint_label.isVisible()
        assert not panel.max_flow_edit._inline_hint_label.isVisible()
    finally:
        panel.close()
        panel.deleteLater()


def test_flow_selector_switch_keeps_design_and_max_on_same_segment():
    """切换任一流量段时，设计流量和加大流量应同步显示同一段。"""
    panel = _build_panel()
    try:
        panel.design_flow_edit.setText("120.8, 78.8, 9.8")
        panel.max_flow_edit.setText("150.9, 98.5, 12.25")
        panel._sync_flow_segment_widgets(reset_index=True)

        panel._set_flow_segment_current_index(1)
        _flush_events()

        assert panel._flow_segment_current_index == 1
        assert panel.design_flow_edit.summary_text() == "第二流量段 · 78.8"
        assert panel.max_flow_edit.summary_text() == "第二流量段 · 98.5"
    finally:
        panel.close()
        panel.deleteLater()


def test_design_flow_change_recomputes_all_max_flows():
    """设计流量变化后，应整体重算并覆盖加大流量。"""
    panel = _build_panel()
    try:
        panel.design_flow_edit.setText("0.3, 78.8, 120.8")
        panel.max_flow_edit.setText("1, 2, 3")
        panel._sync_flow_segment_widgets(reset_index=True)
        panel._set_flow_segment_current_index(2)

        panel._on_design_flow_changed()
        _flush_events()

        assert panel.max_flow_edit.text() == "0.39, 86.68, 126.84"
        assert panel.max_flow_edit.summary_text() == "第三流量段 · 126.84"
    finally:
        panel.close()
        panel.deleteLater()


def test_programmatic_flow_values_refresh_main_view():
    """程序侧更新流量列表后，主界面摘要应立即刷新。"""
    panel = _build_panel()
    try:
        panel.design_flow_edit.setText("120.8, 78.8")
        panel.max_flow_edit.setText("150.9, 98.5")
        panel._sync_flow_segment_widgets(reset_index=True)
        panel._set_flow_segment_current_index(1)

        panel.design_flow_edit.setText("110.5, 66.6")
        panel.max_flow_edit.setText("132.6, 83.25")
        panel._sync_flow_segment_widgets(reset_index=False)
        _flush_events()

        assert panel.design_flow_edit.text() == "110.5, 66.6"
        assert panel.max_flow_edit.text() == "132.6, 83.25"
        assert panel.design_flow_edit.summary_text() == "第二流量段 · 66.6"
        assert panel.max_flow_edit.summary_text() == "第二流量段 · 83.25"
    finally:
        panel.close()
        panel.deleteLater()


def test_project_reset_panels_clears_flow_selector_values():
    """新建项目重置时，应真正清空新的流量段选择器。"""
    panel = _build_panel()
    project_manager_cls = _load_project_manager_class()
    manager = project_manager_cls()
    try:
        panel.channel_name_edit.setText("旧项目")
        panel.start_wl_edit.setText("123.4")
        panel.design_flow_edit.setText("120.8, 78.8")
        panel.max_flow_edit.setText("150.9, 98.5")
        panel.start_station_edit.setText("12+345.678")
        panel.roughness_edit.setText("0.014")
        panel.channel_level_combo.setCurrentIndex(max(0, panel.channel_level_combo.count() - 1))
        panel._sync_flow_segment_widgets(reset_index=True)
        _flush_events()

        manager._get_panel = lambda project_slot, **kwargs: panel if project_slot == "water_profile_panel" else None
        manager._reset_panels()
        _flush_events()

        assert panel.design_flow_edit.text() == ""
        assert panel.max_flow_edit.text() == ""
        assert panel.start_station_edit.text() == "0"
        assert panel.roughness_edit.text() == "0.017"
        assert panel.channel_level_combo.currentIndex() == 0
    finally:
        panel.close()
        panel.deleteLater()


def test_main_view_no_longer_exposes_flow_segment_editor_entry():
    """主界面不再提供“编辑全部”入口。"""
    panel = _build_panel()
    try:
        texts = []
        for widget in panel._settings_group.findChildren(QWidget):
            getter = getattr(widget, "text", None)
            if callable(getter):
                try:
                    texts.append(getter())
                except TypeError:
                    continue
        assert "编辑全部" not in texts
    finally:
        panel.close()
        panel.deleteLater()
