# -*- coding: utf-8 -*-
"""Regression coverage for open-channel multi-case result refresh."""

import importlib
import os
import sys
import tempfile
from pathlib import Path

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


def _result_text(panel):
    exported = getattr(panel, "_export_plain_text", "") or ""
    if exported:
        return exported
    if hasattr(panel, "result_text") and hasattr(panel.result_text, "toPlainText"):
        return panel.result_text.toPlainText()
    return ""


def _set_case(panel, case_index, q_value, section_type="梯形"):
    panel._switch_case(case_index)
    _flush_events()
    panel.section_combo.setCurrentText(section_type)
    _flush_events()
    panel.Q_edit.setText(q_value)
    _flush_events()


def _add_cases(panel, target_count):
    while len(panel._cases) < target_count:
        panel._add_case()
        _flush_events()


def test_open_channel_second_recalc_refreshes_visible_summary(monkeypatch):
    _get_qapp()
    panel_mod = _load_panel_module(monkeypatch)
    panel = panel_mod.OpenChannelPanel()
    panel.resize(1400, 900)
    panel.show()
    _flush_events(6)

    for _ in range(2):
        panel._add_case()
        _flush_events()

    for idx, q_value in enumerate(("5", "4", "3")):
        _set_case(panel, idx, q_value)

    panel._calc_btn.click()
    _flush_events(6)
    first_text = _result_text(panel)

    panel._add_case()
    _flush_events(4)
    _set_case(panel, 3, "2")

    panel._calc_btn.click()
    _flush_events(6)
    second_text = _result_text(panel)

    assert "共 3 个工况" in first_text
    assert len(panel._all_results) == 4
    assert "共 4 个工况" in second_text
    assert second_text != first_text
    assert ("工况4" in second_text) or ("工况 4" in second_text)
    assert panel.notebook.currentIndex() == 0

    panel.deleteLater()


def test_open_channel_multi_case_summary_counts_successes_and_failures(monkeypatch):
    _get_qapp()
    panel_mod = _load_panel_module(monkeypatch)
    panel = panel_mod.OpenChannelPanel()
    panel.resize(1400, 900)
    panel.show()
    _flush_events(6)

    panel._add_case()
    _flush_events()
    _set_case(panel, 0, "5")
    panel._switch_case(1)
    _flush_events()
    panel.section_combo.setCurrentText("梯形")
    _flush_events()
    panel.Q_edit.setText("")
    _flush_events()

    panel._calc_btn.click()
    _flush_events(6)
    text = _result_text(panel)

    assert len(panel._all_results) == 2
    assert "共 2 个工况，成功 1 个，失败 1 个" in text
    assert "请输入设计流量 Q" in text
    assert panel.notebook.currentIndex() == 0

    panel.deleteLater()


def test_open_channel_calculate_surfaces_render_failures(monkeypatch):
    _get_qapp()
    panel_mod = _load_panel_module(monkeypatch)

    class _InfoBarSpy:
        calls = []

        @classmethod
        def error(cls, **kwargs):
            cls.calls.append(kwargs)

        @classmethod
        def warning(cls, **kwargs):
            cls.calls.append(kwargs)

    monkeypatch.setattr(panel_mod, "InfoBar", _InfoBarSpy)

    panel = panel_mod.OpenChannelPanel()
    panel.resize(1400, 900)
    panel.show()
    _flush_events(6)
    _set_case(panel, 0, "5")

    def _raise_render_failure():
        raise RuntimeError("boom")

    monkeypatch.setattr(panel, "_display_all_results", _raise_render_failure)

    panel._calculate()
    _flush_events(4)

    assert len(panel._all_results) == 1
    assert panel._all_results[0][2]["success"] is True
    assert _InfoBarSpy.calls
    assert _InfoBarSpy.calls[-1]["title"] == "结果显示失败"
    assert "本次计算已完成，但结果渲染失败。" in panel._export_plain_text
    assert "错误信息：boom" in panel._export_plain_text
    assert panel.notebook.currentIndex() == 0

    panel.deleteLater()


def test_open_channel_multi_case_render_contains_case_anchors(monkeypatch):
    _get_qapp()
    panel_mod = _load_panel_module(monkeypatch)
    panel = panel_mod.OpenChannelPanel()
    panel.resize(1400, 900)
    panel.show()
    _flush_events(6)

    panel._add_case()
    _flush_events()
    _set_case(panel, 0, "5")
    _set_case(panel, 1, "4")

    panel._calc_btn.click()
    _flush_events(6)
    html = panel.result_text.toHtml()

    assert "case-result-open-channel-0" in html
    assert "case-result-open-channel-1" in html

    panel.deleteLater()


def test_open_channel_four_case_nav_renders_unique_anchors_and_jumps(monkeypatch):
    _get_qapp()
    panel_mod = _load_panel_module(monkeypatch)

    scroll_calls = []
    captured_html = {}

    def _spy_scroll(*args, **kwargs):
        scroll_calls.append((args, kwargs))
        return True

    monkeypatch.setattr(panel_mod, "scroll_view_to_anchor", _spy_scroll)

    panel = panel_mod.OpenChannelPanel()
    panel.resize(1400, 900)
    panel.show()
    _flush_events(6)

    original_render = panel._render_result_html

    def _capture_render(html, *args, **kwargs):
        captured_html["value"] = html
        return original_render(html, *args, **kwargs)

    panel._render_result_html = _capture_render

    _add_cases(panel, 4)
    for idx, (q_value, section_type) in enumerate(
        (("5", "梯形"), ("6", "梯形"), ("10", "矩形"), ("10", "圆形"))
    ):
        _set_case(panel, idx, q_value, section_type=section_type)

    panel._calc_btn.click()
    _flush_events(8)

    html = captured_html["value"]

    assert len(panel._all_results) == 4
    for case_idx in range(4):
        anchor = f"case-result-open-channel-{case_idx}"
        assert html.count(f'id="{anchor}"') == 1
    assert panel._result_case_nav.chip_count() == 4

    scroll_calls.clear()
    panel._result_case_nav.chips()[2].click()
    _flush_events(2)
    panel._result_case_nav.chips()[3].click()
    _flush_events(2)

    anchors = [args[1] for args, _kwargs in scroll_calls]
    assert "case-result-open-channel-2" in anchors
    assert "case-result-open-channel-3" in anchors

    panel.deleteLater()


def test_open_channel_switching_cases_without_fresh_results_skips_jump_warning(monkeypatch):
    _get_qapp()
    panel_mod = _load_panel_module(monkeypatch)

    scroll_calls = []

    def _spy_scroll(*args, **kwargs):
        scroll_calls.append((args, kwargs))
        return True

    class _InfoBarSpy:
        warnings = []

        @classmethod
        def warning(cls, **kwargs):
            cls.warnings.append(kwargs)

        @classmethod
        def error(cls, **kwargs):
            pass

    monkeypatch.setattr(panel_mod, "scroll_view_to_anchor", _spy_scroll)
    monkeypatch.setattr(panel_mod, "InfoBar", _InfoBarSpy)

    panel = panel_mod.OpenChannelPanel()
    panel.resize(1400, 900)
    panel.show()
    _flush_events(6)

    _add_cases(panel, 4)
    _set_case(panel, 0, "5")
    _set_case(panel, 1, "6")
    _set_case(panel, 2, "10", section_type="矩形")
    _set_case(panel, 3, "10", section_type="圆形")

    scroll_calls.clear()
    _InfoBarSpy.warnings.clear()
    panel._switch_case(2)
    _flush_events(2)
    panel._switch_case(3)
    _flush_events(2)

    assert panel._current_case_idx == 3
    assert scroll_calls == []
    assert _InfoBarSpy.warnings == []

    panel._calc_btn.click()
    _flush_events(8)

    scroll_calls.clear()
    _InfoBarSpy.warnings.clear()
    panel.Q_edit.setText("12")
    _flush_events(2)
    panel._switch_case(1)
    _flush_events(2)

    assert panel._results_dirty is True
    assert scroll_calls == []
    assert _InfoBarSpy.warnings == []

    panel.deleteLater()


def test_open_channel_result_nav_click_warns_when_results_are_stale(monkeypatch):
    _get_qapp()
    panel_mod = _load_panel_module(monkeypatch)

    scroll_calls = []

    def _spy_scroll(*args, **kwargs):
        scroll_calls.append((args, kwargs))
        return True

    class _InfoBarSpy:
        warnings = []

        @classmethod
        def warning(cls, **kwargs):
            cls.warnings.append(kwargs)

        @classmethod
        def error(cls, **kwargs):
            pass

    monkeypatch.setattr(panel_mod, "scroll_view_to_anchor", _spy_scroll)
    monkeypatch.setattr(panel_mod, "InfoBar", _InfoBarSpy)

    panel = panel_mod.OpenChannelPanel()
    panel.resize(1400, 900)
    panel.show()
    _flush_events(6)

    _add_cases(panel, 2)
    _set_case(panel, 0, "5")
    _set_case(panel, 1, "4")

    panel._calc_btn.click()
    _flush_events(6)

    panel._switch_case(0)
    _flush_events(2)
    scroll_calls.clear()
    _InfoBarSpy.warnings.clear()
    panel.Q_edit.setText("6")
    _flush_events(2)
    panel._result_case_nav.chips()[1].click()
    _flush_events(2)

    assert panel._results_dirty is True
    assert scroll_calls == []
    assert _InfoBarSpy.warnings
    assert "重新计算" in _InfoBarSpy.warnings[-1]["content"]

    panel.deleteLater()
