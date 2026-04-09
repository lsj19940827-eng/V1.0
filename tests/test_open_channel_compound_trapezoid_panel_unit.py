# -*- coding: utf-8 -*-
"""复式梯形明渠面板的单元测试。"""

import importlib
import math
import os
import sys
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE_PACKAGE = "app_渠系计算前端"


def _get_qapp():
    return QApplication.instance() or QApplication([])


def _flush_events(rounds=4):
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _force_fallback_webview(monkeypatch):
    webview_compat = importlib.import_module(BASE_PACKAGE + ".webview_compat")
    monkeypatch.setattr(webview_compat, "_QtWebEngineView", None)
    monkeypatch.setattr(
        webview_compat,
        "_WEB_ENGINE_IMPORT_ERROR",
        RuntimeError("forced fallback web view in tests"),
    )


def _load_panel_module(monkeypatch):
    _force_fallback_webview(monkeypatch)
    return importlib.import_module(BASE_PACKAGE + ".open_channel.panel")


def _build_compound_panel(monkeypatch):
    """创建并切到复式梯形工况的测试面板。"""
    _get_qapp()
    panel_mod = _load_panel_module(monkeypatch)
    panel = panel_mod.OpenChannelPanel()
    panel.resize(1400, 900)
    panel.show()
    _flush_events(6)
    panel.section_combo.setCurrentText("复式梯形")
    _flush_events(2)
    return panel


def _configure_compound_inputs(
    panel,
    *,
    q="5.0",
    n="0.014",
    slope_inv="3000",
    v_min="0.1",
    v_max="100",
    m1="1",
    B1="3",
    m2="1",
    B2="2",
    m3="1",
    h1="1",
    increase_percent="20",
):
    """填入复式梯形复现场景参数。"""
    panel.Q_edit.setText(q)
    panel.n_edit.setText(n)
    panel.slope_edit.setText(slope_inv)
    panel.vmin_edit.setText(v_min)
    panel.vmax_edit.setText(v_max)
    panel.m1_edit.setText(m1)
    panel.B1_edit.setText(B1)
    panel.m2_edit.setText(m2)
    panel.B2_edit.setText(B2)
    panel.m3_edit.setText(m3)
    panel.h1_edit.setText(h1)
    panel.inc_cb.setChecked(True)
    panel.inc_edit.setText(increase_percent)
    _flush_events(2)


def _rounded_patch_vertices(ax, digits=3):
    """读取单个坐标轴首个填充多边形的顶点，并做小数规整。"""
    assert ax.patches, "当前坐标轴没有填充多边形"
    verts = []
    for x, y in ax.patches[0].get_path().vertices:
        point = (round(float(x), digits), round(float(y), digits))
        if not verts or verts[-1] != point:
            verts.append(point)
    if len(verts) > 1 and verts[0] == verts[-1]:
        verts.pop()
    return verts


def test_open_channel_panel_supports_compound_trapezoid_switch_save_and_result(monkeypatch):
    """复式梯形应支持切换、保存回填和结果文本。"""
    panel = _build_compound_panel(monkeypatch)

    assert panel.section_combo.findText("复式梯形") >= 0

    _configure_compound_inputs(
        panel,
        q="8.391",
        m1="1.5",
        B1="2.0",
        m2="1.0",
        B2="3.0",
        m3="1.0",
        h1="1.0",
        increase_percent="20",
    )
    panel.detail_cb.setChecked(False)

    panel._save_current_case()
    panel.m1_edit.setText("")
    panel._load_case(0)
    _flush_events(2)

    assert panel.m1_edit.text() == "1.5"
    assert panel.B1_edit.text() == "2.0"
    assert panel.B2_edit.text() == "3.0"

    panel._calculate()
    _flush_events(6)

    assert panel.current_result["success"] is True
    assert "复式梯形" in panel._export_plain_text
    assert "左上坡" in panel._export_plain_text
    assert "平台宽" in panel._export_plain_text
    assert "平台高差" in panel._export_plain_text

    panel.deleteLater()


def test_open_channel_panel_initial_help_includes_compound_trapezoid(monkeypatch):
    """初始帮助页应说明复式梯形的固定参数和公式口径。"""
    _get_qapp()
    panel_mod = _load_panel_module(monkeypatch)
    panel = panel_mod.OpenChannelPanel()
    panel.resize(1400, 900)
    panel.show()
    _flush_events(6)

    help_html = panel.result_text.toHtml()
    assert "复式梯形断面" in help_html
    assert "m1/B1/m2/B2/m3/h1" in help_html
    assert "固定几何" in help_html

    panel.deleteLater()


def test_compound_trapezoid_water_patch_keeps_platform_breakpoints_after_overtopping(monkeypatch):
    """水深越过平台后，填充轮廓必须显式经过平台拐点，不能斜切跨过去。"""
    panel = _build_compound_panel(monkeypatch)
    _configure_compound_inputs(panel)

    panel._calculate()
    _flush_events(6)

    assert panel.current_result["success"] is True
    axes = panel.section_fig.axes
    assert len(axes) == 2

    expected_breakpoints = {(-5.0, 1.0), (-2.0, 1.0)}
    for ax in axes:
        rounded_points = set(_rounded_patch_vertices(ax))
        assert expected_breakpoints.issubset(rounded_points)

    panel.deleteLater()


def test_compound_trapezoid_water_patch_stays_simple_below_platform(monkeypatch):
    """平台以下水位仍应保持简单梯形填充，不应引入平台转折点。"""
    panel = _build_compound_panel(monkeypatch)
    ax = panel.section_fig.add_subplot(111)

    panel._draw_compound_trapezoid(
        ax,
        B2=2.0,
        m1=1.0,
        B1=3.0,
        m2=1.0,
        m3=1.0,
        h1=1.0,
        h_ch=2.0,
        V=0.8,
        Q=2.0,
        h_w=0.8,
        title="设计流量",
    )

    rounded_points = set(_rounded_patch_vertices(ax))
    assert rounded_points == {(-1.0, 0.0), (1.0, 0.0), (1.8, 0.8), (-1.8, 0.8)}
    assert (-5.0, 1.0) not in rounded_points
    assert (-2.0, 1.0) not in rounded_points

    panel.deleteLater()


def test_compound_trapezoid_default_view_keeps_true_aspect_and_tighter_xlim(monkeypatch):
    """默认视图应保持真实比例，同时收紧无意义的横向留白。"""
    panel = _build_compound_panel(monkeypatch)
    _configure_compound_inputs(panel)

    panel._calculate()
    _flush_events(6)

    assert panel.current_result["success"] is True
    outline_width = (panel.current_result["h_prime"] + 5.0) - (-(panel.current_result["h_prime"] + 5.0))
    max_reasonable_width = 2.0 + 2 * panel.current_result["h_prime"] + 3.0 + 4.0

    for ax in panel.section_fig.axes:
        x_min, x_max = ax.get_xlim()
        assert ax.get_aspect() == pytest.approx(1.0)
        assert (x_max - x_min) < max_reasonable_width
        assert (x_max - x_min) < outline_width

    panel.deleteLater()
