# -*- coding: utf-8 -*-
"""Regression tests for recalculating multi-case panels after backfilling Q."""

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


BASE_PACKAGE = "app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef"
MISSING_Q_MSG = "\u8bf7\u8f93\u5165\u8bbe\u8ba1\u6d41\u91cf Q"
STALE_HINT_MSG = "\u8bf7\u4fee\u6b63\u540e\u91cd\u65b0\u8ba1\u7b97"
ZERO_Q_HEADER = "Q = 0.000 m\u00b3/s"

PANEL_SCENARIOS = [
    (
        1,
        "aqueduct_panel",
        BASE_PACKAGE + ".aqueduct.panel",
        "AqueductPanel",
        [
            ("U\u5f62", "5"),
            ("U\u5f62", "4"),
            ("\u77e9\u5f62", "3"),
            ("U\u5f62", "2"),
        ],
    ),
    (
        0,
        "open_channel_panel",
        BASE_PACKAGE + ".open_channel.panel",
        "OpenChannelPanel",
        [
            ("\u68af\u5f62", "5"),
            ("U\u5f62", "4"),
            ("\u77e9\u5f62", "3"),
            ("U\u5f62", "2"),
        ],
    ),
    (
        3,
        "culvert_panel",
        BASE_PACKAGE + ".culvert.panel",
        "CulvertPanel",
        [
            (None, "5"),
            (None, "4"),
            (None, "3"),
            (None, "2"),
        ],
    ),
    (
        2,
        "tunnel_panel",
        BASE_PACKAGE + ".tunnel.panel",
        "TunnelPanel",
        [
            ("\u5706\u5f62", "5"),
            ("\u5706\u62f1\u76f4\u5899\u578b", "4"),
            ("\u9a6c\u8e44\u5f62\u6807\u51c6\u2160\u578b", "3"),
            ("\u5706\u5f62", "2"),
        ],
    ),
]


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


def _load_panel_class(monkeypatch, module_name, class_name):
    _force_fallback_webview(monkeypatch)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def _extract_result_rows(panel):
    rows = []
    for item in getattr(panel, "_all_results", []):
        if isinstance(item, tuple):
            _case_idx, params, result = item
            rows.append(
                {
                    "q": params.get("Q"),
                    "success": bool(result.get("success")),
                    "error_message": result.get("error_message", ""),
                }
            )
            continue

        result = item.get("result") or {}
        params = item.get("input") or {}
        case_data = item.get("case") or {}
        rows.append(
            {
                "q": params.get("Q", case_data.get("Q")),
                "success": bool(result.get("success")),
                "error_message": result.get("error_message", ""),
            }
        )
    return rows


def _result_text(panel):
    if hasattr(panel, "result_text") and hasattr(panel.result_text, "toPlainText"):
        return panel.result_text.toPlainText()
    return getattr(panel, "_export_plain_text", "") or ""


def _prepare_panel(panel):
    panel.resize(1400, 900)
    panel.show()
    _flush_events()
    for _ in range(3):
        panel._add_case()
        _flush_events()


def _set_case(panel, case_index, section_type=None, q_value=None):
    panel._case_nav._chips[case_index].click()
    _flush_events()
    if section_type is not None and hasattr(panel, "section_combo"):
        panel.section_combo.setCurrentText(section_type)
        _flush_events()
    if q_value is not None:
        panel.Q_edit.setText(q_value)
        _flush_events()


def _run_backfill_q_flow(panel, scenario):
    _prepare_panel(panel)

    for idx, (section_type, q_value) in enumerate(scenario):
        _set_case(panel, idx, section_type=section_type, q_value=q_value if idx == 0 else None)

    panel._calc_btn.click()
    _flush_events(6)

    first_rows = _extract_result_rows(panel)
    first_text = _result_text(panel)

    for idx, (section_type, q_value) in enumerate(scenario[1:], start=1):
        _set_case(panel, idx, section_type=section_type, q_value=q_value)

    panel._calc_btn.click()
    _flush_events(6)

    second_rows = _extract_result_rows(panel)
    second_text = _result_text(panel)
    return first_rows, first_text, second_rows, second_text


@pytest.mark.parametrize(("stack_index", "panel_attr", "module_name", "class_name", "scenario"), PANEL_SCENARIOS)
def test_multi_case_panels_recalculate_after_backfilling_missing_q(
    monkeypatch,
    stack_index,
    panel_attr,
    module_name,
    class_name,
    scenario,
):
    _get_qapp()
    panel_cls = _load_panel_class(monkeypatch, module_name, class_name)
    panel = panel_cls()

    first_rows, _first_text, second_rows, second_text = _run_backfill_q_flow(panel, scenario)

    assert isinstance(stack_index, int)
    assert panel_attr
    assert first_rows[0]["success"] is True
    assert all(row["success"] is False for row in first_rows[1:])
    assert all(MISSING_Q_MSG in row["error_message"] for row in first_rows[1:])

    expected_qs = [float(q) for _, q in scenario]
    actual_qs = [float(row["q"]) for row in second_rows]

    assert actual_qs == expected_qs
    assert len(second_rows) == 4
    assert all(row["success"] is True for row in second_rows)
    assert ZERO_Q_HEADER not in second_text
    assert MISSING_Q_MSG not in second_text
    assert STALE_HINT_MSG not in second_text
    if panel_attr == "open_channel_panel":
        assert "共 4 个工况" in second_text or "工况4" in second_text or "工况 4" in second_text

    panel.deleteLater()


def test_main_window_multi_case_recalc_regression_uses_latest_q_values(monkeypatch):
    _get_qapp()
    _force_fallback_webview(monkeypatch)

    project_manager_module = importlib.import_module(BASE_PACKAGE + ".project_manager")
    monkeypatch.setattr(project_manager_module.ProjectManager, "start_auto_save", lambda self: None)
    monkeypatch.setattr(project_manager_module.ProjectManager, "check_save_on_close", lambda self: True)

    app_module = importlib.import_module(BASE_PACKAGE + ".app")
    monkeypatch.setattr(app_module.MainWindow, "_start_silent_update_check", lambda self: None)
    monkeypatch.setattr(app_module.MainWindow, "_notify_optional_runtime_degradations", lambda self: None)

    from PySide6.QtWidgets import QWidget

    class DummyPanel(QWidget):
        def __init__(self, *args, **kwargs):
            super().__init__()

    monkeypatch.setattr(app_module, "SiphonPanel", DummyPanel)
    monkeypatch.setattr(app_module, "PressurePipePanel", DummyPanel)
    monkeypatch.setattr(app_module, "WaterProfilePanel", DummyPanel)

    window = app_module.MainWindow()
    window.resize(1600, 960)
    window.show()
    _flush_events(8)

    for stack_index, panel_attr, _module_name, _class_name, scenario in PANEL_SCENARIOS:
        window._switch_to(stack_index)
        _flush_events(4)
        panel = getattr(window, panel_attr)
        panel._clear()
        _flush_events(4)

        first_rows, _first_text, second_rows, second_text = _run_backfill_q_flow(panel, scenario)

        assert first_rows[0]["success"] is True
        assert all(row["success"] is False for row in first_rows[1:])
        assert all(MISSING_Q_MSG in row["error_message"] for row in first_rows[1:])

        expected_qs = [float(q) for _, q in scenario]
        actual_qs = [float(row["q"]) for row in second_rows]
        assert actual_qs == expected_qs
        assert len(second_rows) == 4
        assert all(row["success"] is True for row in second_rows)
        assert ZERO_Q_HEADER not in second_text
        assert MISSING_Q_MSG not in second_text
        assert STALE_HINT_MSG not in second_text
        if panel_attr == "open_channel_panel":
            assert "共 4 个工况" in second_text or "工况4" in second_text or "工况 4" in second_text

    window.project_manager._is_dirty = False
    window.close()
    window.deleteLater()
    _flush_events(8)
