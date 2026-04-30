# -*- coding: utf-8 -*-
"""测试隧洞圆拱直墙型按净空反推尺寸弹窗入口。"""

import importlib
import os
import sys
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import PrimaryPushButton


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_PANELS = []


def _get_qapp():
    """获取测试用 Qt 应用。"""
    return QApplication.instance() or QApplication([])


def _flush_events(rounds=4):
    """刷新 Qt 事件队列。"""
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _force_fallback_webview():
    """禁用 WebEngine，避免离屏测试依赖浏览器内核。"""
    webview_compat = importlib.import_module("app_渠系计算前端.webview_compat")
    webview_compat._QtWebEngineView = None
    webview_compat._WEB_ENGINE_IMPORT_ERROR = RuntimeError("forced fallback web view")


def _new_tunnel_panel(show=False):
    """创建隧洞面板。"""
    _get_qapp()
    _force_fallback_webview()
    panel_mod = importlib.import_module("app_渠系计算前端.tunnel.panel")
    panel = panel_mod.TunnelPanel()
    panel.resize(1200, 800)
    if show:
        panel.show()
        _flush_events(6)
    _PANELS.append(panel)
    return panel


def test_clearance_sizing_button_only_shows_for_arch_section():
    """反推尺寸入口只应在圆拱直墙型下显示。"""
    panel = _new_tunnel_panel()

    panel.section_combo.setCurrentText("圆形")
    assert panel.hs_grp.isHidden() is True

    panel.section_combo.setCurrentText("圆拱直墙型")
    assert panel.hs_grp.isHidden() is False
    assert panel.clearance_sizing_btn.parent() is panel.hs_grp
    assert panel.clearance_sizing_btn.text() == "按加大流量净空比例反推断面尺寸"
    assert isinstance(panel.clearance_sizing_btn, PrimaryPushButton)


def test_clearance_sizing_context_reads_current_case_inputs():
    """弹窗上下文应从当前工况读取 Q加大、θ 和通用水力参数。"""
    panel = _new_tunnel_panel()
    panel.section_combo.setCurrentText("圆拱直墙型")
    panel.Q_edit.setText("10")
    panel.n_edit.setText("0.014")
    panel.slope_edit.setText("3000")
    panel.vmin_edit.setText("0.1")
    panel.vmax_edit.setText("3.0")
    panel.theta_edit.setText("120")
    panel.inc_cb.setChecked(True)
    panel.inc_mode_q_rb.setChecked(True)
    panel.inc_q_edit.setText("12.5")

    context = panel._build_clearance_sizing_context()

    assert context["Q_design"] == pytest.approx(10.0)
    assert context["Q_increased"] == pytest.approx(12.5)
    assert context["n"] == pytest.approx(0.014)
    assert context["slope_inv"] == pytest.approx(3000.0)
    assert context["v_min"] == pytest.approx(0.1)
    assert context["v_max"] == pytest.approx(3.0)
    assert context["theta_deg"] == pytest.approx(120.0)


def test_clearance_sizing_context_uses_auto_increase_when_percent_empty():
    """按比例留空时，弹窗 Q加大 应使用自动查表值。"""
    panel = _new_tunnel_panel()
    panel.section_combo.setCurrentText("圆拱直墙型")
    panel.Q_edit.setText("38")
    panel.n_edit.setText("0.014")
    panel.slope_edit.setText("2500")
    panel.vmin_edit.setText("0.1")
    panel.vmax_edit.setText("100")
    panel.inc_cb.setChecked(True)
    panel.inc_mode_percent_rb.setChecked(True)
    panel.inc_edit.setText("")

    context = panel._build_clearance_sizing_context()

    assert context["Q_design"] == pytest.approx(38.0)
    assert context["Q_increased"] == pytest.approx(43.7)
    assert context["Q_increased_source"] == "auto_percent"


def test_clearance_sizing_context_uses_manual_percent():
    """按比例手填时，弹窗 Q加大 应使用主流程手填比例。"""
    panel = _new_tunnel_panel()
    panel.section_combo.setCurrentText("圆拱直墙型")
    panel.Q_edit.setText("38")
    panel.n_edit.setText("0.014")
    panel.slope_edit.setText("2500")
    panel.vmin_edit.setText("0.1")
    panel.vmax_edit.setText("100")
    panel.inc_cb.setChecked(True)
    panel.inc_mode_percent_rb.setChecked(True)
    panel.inc_edit.setText("20")

    context = panel._build_clearance_sizing_context()

    assert context["Q_increased"] == pytest.approx(45.6)
    assert context["Q_increased_source"] == "manual_percent"


def test_clearance_sizing_context_uses_auto_when_increase_disabled():
    """主流程未启用加大流量时，反推弹窗仍应给出自动查表建议值。"""
    panel = _new_tunnel_panel()
    panel.section_combo.setCurrentText("圆拱直墙型")
    panel.Q_edit.setText("38")
    panel.n_edit.setText("0.014")
    panel.slope_edit.setText("2500")
    panel.vmin_edit.setText("0.1")
    panel.vmax_edit.setText("100")
    panel.inc_cb.setChecked(False)

    context = panel._build_clearance_sizing_context()

    assert context["Q_increased"] == pytest.approx(43.7)
    assert context["Q_increased_source"] == "auto_when_disabled"


def test_clearance_sizing_apply_fills_arch_inputs_without_calculating():
    """采用弹窗结果只回填 θ、B、H直，并把已有结果标记为过期。"""
    panel = _new_tunnel_panel()
    panel.section_combo.setCurrentText("圆拱直墙型")
    panel._all_results = [{"result": {"success": True}}]
    panel._has_rendered_results = True
    called = {"calculate": False}
    panel._calculate = lambda: called.__setitem__("calculate", True)

    panel._apply_clearance_sizing_result({
        "theta_deg": 120.0,
        "B": 3.1866,
        "H_straight": 2.9048,
    })

    assert panel.theta_edit.text() == "120.000"
    assert panel.B_hs_edit.text() == "3.187"
    assert panel.H_straight_hs_edit.text() == "2.905"
    assert panel._results_dirty is True
    assert called["calculate"] is False
