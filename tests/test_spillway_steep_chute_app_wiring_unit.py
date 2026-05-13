# -*- coding: utf-8 -*-
"""泄水渠与陡坡试验模块的主窗口和报告元数据接入测试。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_main_window_registers_spillway_steep_chute_panel():
    """主窗口注册表应包含泄水渠与陡坡独立试验模块。"""
    source = (ROOT / "app_渠系计算前端" / "app.py").read_text(encoding="utf-8")

    assert '"spillway_steep_chute":' in source
    assert 'def _create_spillway_steep_chute_panel()' in source
    assert 'key="spillway_steep_chute"' in source
    assert 'title="泄水渠与陡坡"' in source
    assert 'attr_name="spillway_steep_chute_panel"' in source
    assert 'project_slot="spillway_steep_chute_panel"' in source


def test_project_manager_default_payload_has_spillway_slot():
    """项目保存默认载荷应包含泄水渠与陡坡面板槽位。"""
    source = (ROOT / "app_渠系计算前端" / "project_manager.py").read_text(encoding="utf-8")

    assert '"spillway_steep_chute_panel": None' in source


def test_project_manager_reset_calls_spillway_panel_reset():
    """新建项目时，项目管理器应重置泄水渠与陡坡面板。"""
    source = (ROOT / "app_渠系计算前端" / "project_manager.py").read_text(encoding="utf-8")

    assert 'reset_to_default' in source


def test_report_meta_supports_spillway_steep_chute_defaults():
    """报告元数据应提供新模块默认计算目的和依据。"""
    source = (ROOT / "app_渠系计算前端" / "report_meta.py").read_text(encoding="utf-8")

    assert '"spillway_steep_chute": [' in source
    assert '"spillway_steep_chute": (' in source
    assert "泄水渠" in source
    assert "陡坡" in source
    assert "GB 50288-2018" in source
