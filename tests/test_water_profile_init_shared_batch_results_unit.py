# -*- coding: utf-8 -*-
"""水面线面板初始化时保留共享批量结果的回归测试。"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WATER_PROFILE_ROOT = (ROOT / "推求水面线").resolve()
if str(WATER_PROFILE_ROOT) not in sys.path:
    sys.path.insert(0, str(WATER_PROFILE_ROOT))

from shared.shared_data_manager import get_shared_data_manager


def _get_qapp():
    """获取测试用 Qt 应用实例。"""
    return QApplication.instance() or QApplication([])


def _load_panel_module():
    """按文件路径加载水面线面板模块。"""
    panel_path = (ROOT / "app_渠系计算前端" / "water_profile" / "panel.py").resolve()
    spec = importlib.util.spec_from_file_location("wp_init_shared_batch_results_test", panel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mute_infobar(module):
    """屏蔽测试中的 InfoBar 弹窗。"""
    for attr in ("success", "warning", "error", "info"):
        setattr(module.InfoBar, attr, staticmethod(lambda *args, **kwargs: None))


def test_water_profile_panel_init_keeps_existing_shared_batch_results():
    module = _load_panel_module()
    _mute_infobar(module)

    manager = get_shared_data_manager()
    manager.clear_batch_results()
    manager.register_batch_results(
        [
            {
                "success": True,
                "section_type": "有压管道",
                "building_name": "测试管段",
                "flow_section": "1",
                "coord_X": 0.0,
                "coord_Y": 0.0,
                "D": 1.4,
                "Q": 1.2,
                "n": 0.014,
                "V": 0.8,
                "A": 1.0,
                "X": 1.0,
                "R_hydraulic": 1.0,
                "Q_max": 1.2,
                "h_max": 1.4,
                "V_max": 0.8,
                "start_water_level": 339.09,
                "start_station": 0.0,
                "channel_name": "广罗",
                "channel_level": "支渠",
                "use_increase": True,
            }
        ]
    )
    assert len(manager.get_batch_results()) == 1

    _get_qapp()
    panel = module.WaterProfilePanel()
    try:
        assert len(manager.get_batch_results()) == 1
        assert manager.get_batch_results()[0].building_name == "测试管段"
    finally:
        panel.close()
        manager.clear_batch_results()


def test_import_from_batch_prefers_shared_max_flows_per_segment():
    """从共享结果导入表3时，应优先使用各流量段已有的最终加大流量。"""
    module = _load_panel_module()
    _mute_infobar(module)

    manager = get_shared_data_manager()
    manager.clear_batch_results()
    manager.register_batch_results(
        [
            {
                "success": True,
                "section_type": "矩形渠道",
                "building_name": "一",
                "flow_section": "1",
                "coord_X": 0.0,
                "coord_Y": 0.0,
                "Q": 4.0,
                "Q_max": 5.1,
                "n": 0.014,
                "V": 0.8,
                "A": 1.0,
                "X": 1.0,
                "R_hydraulic": 1.0,
                "h": 1.2,
                "h_max": 1.4,
                "V_max": 1.0,
                "start_water_level": 339.09,
                "start_station": 0.0,
                "channel_name": "广罗",
                "channel_level": "支渠",
                "use_increase": True,
            },
            {
                "success": True,
                "section_type": "矩形渠道",
                "building_name": "二",
                "flow_section": "2",
                "coord_X": 1.0,
                "coord_Y": 0.0,
                "Q": 20.0,
                "Q_increased": 22.6,
                "n": 0.014,
                "V": 0.9,
                "A": 1.1,
                "X": 1.2,
                "R_hydraulic": 1.0,
                "h": 1.3,
                "h_increased": 1.5,
                "V_increased": 1.1,
                "start_water_level": 339.09,
                "start_station": 0.0,
                "channel_name": "广罗",
                "channel_level": "支渠",
                "use_increase": True,
            },
        ]
    )

    _get_qapp()
    panel = module.WaterProfilePanel()
    try:
        panel._import_from_batch()

        assert panel._parse_flow_values(panel.design_flow_edit.text()) == pytest.approx([4.0, 20.0])
        assert panel._parse_flow_values(panel.max_flow_edit.text()) == pytest.approx([5.1, 22.6])
    finally:
        panel.close()
        manager.clear_batch_results()


def test_import_from_batch_keeps_auto_rules_when_shared_max_flows_are_empty():
    """共享结果里没有 Q加大 时，表3行为应与当前自动换算规则一致。"""
    module = _load_panel_module()
    _mute_infobar(module)

    manager = get_shared_data_manager()
    manager.clear_batch_results()
    manager.register_batch_results(
        [
            {
                "success": True,
                "section_type": "矩形渠道",
                "building_name": "一",
                "flow_section": "1",
                "coord_X": 0.0,
                "coord_Y": 0.0,
                "Q": 4.0,
                "n": 0.014,
                "V": 0.8,
                "A": 1.0,
                "X": 1.0,
                "R_hydraulic": 1.0,
                "h": 1.2,
                "start_water_level": 339.09,
                "start_station": 0.0,
                "channel_name": "广罗",
                "channel_level": "支渠",
                "use_increase": True,
            },
            {
                "success": True,
                "section_type": "矩形渠道",
                "building_name": "二",
                "flow_section": "2",
                "coord_X": 1.0,
                "coord_Y": 0.0,
                "Q": 20.0,
                "n": 0.014,
                "V": 0.9,
                "A": 1.1,
                "X": 1.2,
                "R_hydraulic": 1.0,
                "h": 1.3,
                "start_water_level": 339.09,
                "start_station": 0.0,
                "channel_name": "广罗",
                "channel_level": "支渠",
                "use_increase": True,
            },
        ]
    )

    _get_qapp()
    panel = module.WaterProfilePanel()
    try:
        panel._import_from_batch()

        assert panel._parse_flow_values(panel.design_flow_edit.text()) == pytest.approx([4.0, 20.0])
        assert panel._parse_flow_values(panel.max_flow_edit.text()) == pytest.approx([5.0, 23.0])
    finally:
        panel.close()
        manager.clear_batch_results()
