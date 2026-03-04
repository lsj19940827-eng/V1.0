# -*- coding: utf-8 -*-
"""Regression tests for per-case detail/brief toggle in multi-case display."""

import importlib
from types import MethodType


class _FakeCheckBox:
    def __init__(self, checked):
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked


def _make_open_channel_dummy(panel_cls):
    class _Dummy:
        pass

    d = _Dummy()
    d.detail_cb = _FakeCheckBox(False)  # Opposite of case1 detail flag on purpose
    d._suppress_result_render = False
    d._export_plain_text = ""
    d._rendered_html = ""

    d._all_results = [
        (
            0,
            {"section_type": "\u68af\u5f62", "Q": 1.0, "detail_checked": True},
            {"success": True},
        ),
        (
            1,
            {"section_type": "\u68af\u5f62", "Q": 2.0, "detail_checked": False},
            {"success": True},
        ),
    ]

    d._show_error = lambda title, msg: setattr(d, "_export_plain_text", f"ERR:{title}:{msg}")
    d._show_trapezoid_detail = lambda result: setattr(d, "_export_plain_text", "DETAIL")
    d._show_trapezoid_brief = lambda result: setattr(d, "_export_plain_text", "BRIEF")
    d._show_u_detail = lambda result: setattr(d, "_export_plain_text", "U-DETAIL")
    d._show_u_brief = lambda result: setattr(d, "_export_plain_text", "U-BRIEF")
    d._show_circular_detail = lambda result: setattr(d, "_export_plain_text", "C-DETAIL")
    d._show_circular_brief = lambda result: setattr(d, "_export_plain_text", "C-BRIEF")
    d._render_result_html = lambda html: setattr(d, "_rendered_html", html)
    d._update_section_plot_all = lambda: None

    d._update_result_display = MethodType(panel_cls._update_result_display, d)
    return d


def _make_aqueduct_dummy(panel_cls):
    class _Dummy:
        pass

    d = _Dummy()
    d.detail_cb = _FakeCheckBox(True)  # Opposite of case2 detail flag on purpose
    d._suppress_result_render = False
    d._export_plain_text = ""
    d._rendered_html = ""

    d._all_results = [
        (
            0,
            {"section_type": "U\u5f62", "Q": 1.0, "detail_checked": True},
            {"success": True, "section_type": "U\u5f62"},
        ),
        (
            1,
            {"section_type": "U\u5f62", "Q": 2.0, "detail_checked": False},
            {"success": True, "section_type": "U\u5f62"},
        ),
    ]

    d._show_error = lambda title, msg: setattr(d, "_export_plain_text", f"ERR:{title}:{msg}")
    d._show_u_detail = lambda result: setattr(d, "_export_plain_text", "DETAIL")
    d._show_u_brief = lambda result: setattr(d, "_export_plain_text", "BRIEF")
    d._show_rect_detail = lambda result: setattr(d, "_export_plain_text", "R-DETAIL")
    d._show_rect_brief = lambda result: setattr(d, "_export_plain_text", "R-BRIEF")
    d._render_result_html = lambda html: setattr(d, "_rendered_html", html)
    d._update_section_plot_all = lambda: None

    d._update_result_display = MethodType(panel_cls._update_result_display, d)
    return d


def test_open_channel_reads_detail_toggle_per_case():
    mod = importlib.import_module(
        "\u6e20\u7cfb\u65ad\u9762\u8bbe\u8ba1.open_channel.panel"
    )
    panel_cls = mod.OpenChannelPanel
    dummy = _make_open_channel_dummy(panel_cls)

    panel_cls._display_all_results(dummy)

    assert "DETAIL" in dummy._export_plain_text
    assert "BRIEF" in dummy._export_plain_text
    assert dummy._export_plain_text.index("DETAIL") < dummy._export_plain_text.index("BRIEF")


def test_aqueduct_reads_detail_toggle_per_case():
    mod = importlib.import_module(
        "\u6e20\u7cfb\u65ad\u9762\u8bbe\u8ba1.aqueduct.panel"
    )
    panel_cls = mod.AqueductPanel
    dummy = _make_aqueduct_dummy(panel_cls)

    panel_cls._display_all_results(dummy)

    assert "DETAIL" in dummy._export_plain_text
    assert "BRIEF" in dummy._export_plain_text
    assert dummy._export_plain_text.index("DETAIL") < dummy._export_plain_text.index("BRIEF")
