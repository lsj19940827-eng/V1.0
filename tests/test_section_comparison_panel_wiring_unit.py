# -*- coding: utf-8 -*-
"""四类面板工况对比页签和 DXF 接线测试。"""

import importlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from app_渠系计算前端.dxf_multi_export import DxfExportCaseEntry


def _get_qapp():
    """获取测试用 Qt 应用。"""
    return QApplication.instance() or QApplication([])


def _flush_events(rounds=4):
    """处理 Qt 待执行事件。"""
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _load_panel_module(folder):
    """加载面板模块并强制使用轻量 WebView。"""
    webview_compat = importlib.import_module("app_渠系计算前端.webview_compat")
    webview_compat._QtWebEngineView = None
    webview_compat._WEB_ENGINE_IMPORT_ERROR = RuntimeError("forced fallback web view in comparison wiring test")
    module = importlib.import_module(f"app_渠系计算前端.{folder}.panel")
    if hasattr(module, "QWebEngineView"):
        module.QWebEngineView = None
        module._WEB_ENGINE_IMPORT_ERROR = RuntimeError("forced fallback web view in comparison wiring test")
    return module


@pytest.mark.parametrize(
    ("folder", "class_name"),
    [
        ("open_channel", "OpenChannelPanel"),
        ("aqueduct", "AqueductPanel"),
        ("tunnel", "TunnelPanel"),
        ("culvert", "CulvertPanel"),
    ],
)
def test_four_panels_have_comparison_tab_with_two_tables(folder, class_name):
    """四类设计面板右侧输出区应统一为三页签和两张对比表。"""
    _get_qapp()
    module = _load_panel_module(folder)
    panel = getattr(module, class_name)()
    panel.resize(1280, 820)
    panel.show()
    _flush_events(6)

    tab_texts = [panel.notebook.tabText(index) for index in range(panel.notebook.count())]

    assert tab_texts == ["计算结果", "断面图", "工况对比"]
    assert hasattr(panel, "comparison_hydraulic_table")
    assert hasattr(panel, "comparison_dimension_table")
    assert panel.comparison_hydraulic_table.columnCount() > 0
    assert panel.comparison_dimension_table.columnCount() > 0

    panel.close()
    panel.deleteLater()
    _flush_events(4)


@pytest.mark.parametrize(
    ("folder", "class_name", "draw_case_name", "draw_summary_name"),
    [
        ("open_channel", "OpenChannelPanel", "draw_open_channel_dxf_on_msp", "draw_open_channel_comparison_table"),
        ("aqueduct", "AqueductPanel", "draw_aqueduct_dxf_on_msp", "draw_aqueduct_comparison_table"),
        ("culvert", "CulvertPanel", "draw_culvert_dxf_on_msp", "draw_culvert_comparison_table"),
        ("tunnel", "TunnelPanel", "draw_tunnel_dxf_on_msp", "draw_tunnel_comparison_table"),
    ],
)
def test_panel_combined_dxf_passes_section_comparison_callback(
    monkeypatch,
    tmp_path,
    folder,
    class_name,
    draw_case_name,
    draw_summary_name,
):
    """多工况 DXF 导出应把本面板对比表回调传给公共导出器。"""
    module = _load_panel_module(folder)
    panel_cls = getattr(module, class_name)
    captured = {}

    def _fake_export(filepath, entries, scale_denom, draw_case, draw_summary_table=None):
        captured.update(
            filepath=filepath,
            entries=entries,
            scale_denom=scale_denom,
            draw_case=draw_case,
            draw_summary_table=draw_summary_table,
        )
        return filepath

    monkeypatch.setattr(module, "export_combined_case_dxf", _fake_export)
    dummy = SimpleNamespace(
        _combined_dxf_default_name=lambda count: f"{count}.dxf",
        _choose_dxf_filepath=lambda _name: str(tmp_path / f"{folder}.dxf"),
    )
    entries = [
        DxfExportCaseEntry(0, "工况A", {"section_type": "矩形", "Q": 1.0}, {"success": True}, True),
        DxfExportCaseEntry(1, "工况B", {"section_type": "矩形", "Q": 2.0}, {"success": True}, True),
    ]

    result_path = panel_cls._export_combined_dxf_entries(dummy, entries, 100)

    assert result_path == str(tmp_path / f"{folder}.dxf")
    assert captured["entries"] == entries
    assert captured["scale_denom"] == 100
    assert captured["draw_case"] is getattr(module, draw_case_name)
    assert captured["draw_summary_table"] is getattr(module, draw_summary_name)
