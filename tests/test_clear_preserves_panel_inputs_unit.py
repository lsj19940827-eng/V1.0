# -*- coding: utf-8 -*-
"""验证 5 个水力计算面板点击“清空”时保留用户输入。"""

import copy
import importlib
import os
import sys
import tempfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication


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

BASE_PACKAGE = "app_渠系计算前端"


def _get_qapp():
    """获取或创建测试用 Qt 应用。"""
    return QApplication.instance() or QApplication([])


def _flush_events(rounds=4):
    """处理 Qt 事件，确保控件状态完成刷新。"""
    app = _get_qapp()
    for _ in range(max(1, rounds)):
        app.processEvents()


def _force_fallback_webview():
    """禁用 WebEngine，避免离屏测试依赖浏览器内核。"""
    webview_compat = importlib.import_module(BASE_PACKAGE + ".webview_compat")
    webview_compat._QtWebEngineView = None
    webview_compat._WEB_ENGINE_IMPORT_ERROR = RuntimeError(
        "forced fallback web view in clear tests"
    )


def _new_panel(folder, class_name):
    """创建指定面板并显示到离屏环境。"""
    _get_qapp()
    _force_fallback_webview()
    module = importlib.import_module(f"{BASE_PACKAGE}.{folder}.panel")
    if hasattr(module, "QWebEngineView"):
        module.QWebEngineView = None
        module._WEB_ENGINE_IMPORT_ERROR = RuntimeError(
            "forced fallback web view in clear tests"
        )
    panel = getattr(module, class_name)()
    panel.resize(1400, 900)
    panel.show()
    _flush_events(6)
    return panel


def _set_text(panel, attr, value):
    """给输入框写入文本。"""
    getattr(panel, attr).setText(value)


def _set_combo_text(panel, attr, value):
    """给下拉框写入指定文本。"""
    combo = getattr(panel, attr)
    index = combo.findText(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def _set_increase_by_q(panel, value):
    """切换到按加大流量输入，并填入用户值。"""
    panel.inc_cb.setChecked(True)
    panel.inc_mode_q_rb.setChecked(True)
    panel.inc_q_edit.setText(value)
    _flush_events(3)


def _snapshot(panel, fields):
    """记录当前用户可见输入值。"""
    values = {}
    for attr in fields:
        widget = getattr(panel, attr)
        if hasattr(widget, "text"):
            values[attr] = widget.text()
        elif hasattr(widget, "currentText"):
            values[attr] = widget.currentText()
        elif hasattr(widget, "isChecked"):
            values[attr] = widget.isChecked()
    return values


def _seed_common_result_state(panel):
    """放入旧结果，验证清空只清结果不清输入。"""
    panel.current_result = {"success": True}
    panel._all_results = [(0, {"Q": 1.0}, {"success": True})]
    panel._results_dirty = True
    panel._has_rendered_results = True
    if hasattr(panel, "_export_plain_text"):
        panel._export_plain_text = "旧导出内容"


PANEL_CASES = [
    (
        "open_channel",
        "OpenChannelPanel",
        [
            ("text", "Q_edit", "9.99"),
            ("text", "m_edit", "2.22"),
            ("text", "n_edit", "0.033"),
            ("text", "slope_edit", "777"),
            ("text", "vmin_edit", "0.44"),
            ("text", "vmax_edit", "8.88"),
            ("increase_q", None, "10.50"),
        ],
        ["Q_edit", "m_edit", "n_edit", "slope_edit", "vmin_edit", "vmax_edit", "inc_q_edit"],
    ),
    (
        "aqueduct",
        "AqueductPanel",
        [
            ("combo", "section_combo", "矩形"),
            ("text", "Q_edit", "8.88"),
            ("text", "n_edit", "0.032"),
            ("text", "slope_edit", "888"),
            ("text", "B_edit", "2.40"),
            ("increase_q", None, "9.25"),
        ],
        ["section_combo", "Q_edit", "n_edit", "slope_edit", "B_edit", "inc_q_edit"],
    ),
    (
        "tunnel",
        "TunnelPanel",
        [
            ("combo", "section_combo", "圆拱直墙型"),
            ("text", "Q_edit", "12.34"),
            ("text", "n_edit", "0.031"),
            ("text", "slope_edit", "999"),
            ("text", "theta_edit", "135"),
            ("text", "B_hs_edit", "2.60"),
            ("increase_q", None, "13.00"),
        ],
        ["section_combo", "Q_edit", "n_edit", "slope_edit", "theta_edit", "B_hs_edit", "inc_q_edit"],
    ),
    (
        "culvert",
        "CulvertPanel",
        [
            ("combo", "section_combo", "圆拱直墙型"),
            ("text", "Q_edit", "7.77"),
            ("text", "n_edit", "0.030"),
            ("text", "slope_edit", "666"),
            ("text", "theta_edit", "150"),
            ("text", "arch_B_edit", "2.10"),
            ("increase_q", None, "8.10"),
        ],
        ["section_combo", "Q_edit", "n_edit", "slope_edit", "theta_edit", "arch_B_edit", "inc_q_edit"],
    ),
    (
        "pressure_pipe",
        "PressurePipePanel",
        [
            ("text", "Q_edit", "1.23"),
            ("text", "length_edit", "2345"),
            ("text", "local_ratio_edit", "0.33"),
            ("text", "D_edit", "0.80"),
            ("increase_q", None, "1.40"),
        ],
        ["Q_edit", "length_edit", "local_ratio_edit", "D_edit", "inc_q_edit"],
    ),
]


@pytest.mark.parametrize(("folder", "class_name", "edits", "fields"), PANEL_CASES)
def test_clear_preserves_user_inputs_and_cases(folder, class_name, edits, fields):
    """清空只应清结果，不应恢复默认输入或删除多工况。"""
    panel = _new_panel(folder, class_name)

    try:
        panel._add_case()
        _flush_events(4)
        assert len(panel._cases) == 2
        assert panel._current_case_idx == 1

        for kind, attr, value in edits:
            if kind == "text":
                _set_text(panel, attr, value)
            elif kind == "combo":
                _set_combo_text(panel, attr, value)
            elif kind == "increase_q":
                _set_increase_by_q(panel, value)
        _flush_events(4)

        expected_inputs = _snapshot(panel, fields)
        expected_case_count = len(panel._cases)
        expected_case_idx = panel._current_case_idx
        previous_cases = copy.deepcopy(panel._cases)

        _seed_common_result_state(panel)
        panel._clear()
        _flush_events(6)

        assert _snapshot(panel, fields) == expected_inputs
        assert len(panel._cases) == expected_case_count
        assert panel._current_case_idx == expected_case_idx
        assert panel._cases[0] == previous_cases[0]
        assert panel._cases[expected_case_idx] != previous_cases[expected_case_idx]
        assert panel._all_results == []
        assert panel.current_result is None
        assert panel._has_rendered_results is False
        assert panel._results_dirty is False
        if hasattr(panel, "_export_plain_text"):
            assert panel._export_plain_text == ""
    finally:
        panel.close()
        panel.deleteLater()
        _flush_events(4)
