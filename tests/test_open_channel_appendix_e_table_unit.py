# -*- coding: utf-8 -*-
"""Unit tests for Appendix E table rendering helpers."""

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from types import MethodType


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE_PACKAGE = "app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".pytest_tmp" / "mplconfig"))


def _load_helper_module():
    helper_path = next(
        cand for cand in Path(".").glob("app_*/open_channel/appendix_e_table.py")
    ).resolve()
    spec = importlib.util.spec_from_file_location("appendix_e_table_helper", helper_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeCheckBox:
    def __init__(self, checked):
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked


class _FakeResultView:
    def __init__(self, scripted_html):
        self.supports_scripted_html = scripted_html
        self.html = ""
        self.loadFinished = None

    def setHtml(self, html, *args):
        self.html = html


def _sample_appendix_e_schemes():
    return [
        {
            "alpha": 1.0,
            "scheme_type": "水力最佳断面",
            "b": 1.3,
            "h": 1.57,
            "beta": 0.828,
            "V": 1.11,
            "area_increase": 0,
        },
        {
            "alpha": 1.01,
            "scheme_type": "实用经济断面",
            "b": 2.232,
            "h": 1.291,
            "beta": 1.729,
            "V": 1.099,
            "area_increase": 1,
        },
    ]


def _sample_trapezoid_params(q, detail_checked=False):
    return {
        "section_type": "梯形",
        "Q": q,
        "m": 1.0,
        "n": 0.014,
        "slope_inv": 3000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "detail_checked": detail_checked,
        "use_increase": True,
    }


def _sample_trapezoid_result(q, b, h):
    return {
        "success": True,
        "design_method": "附录E 水力最佳断面与实用经济断面综合比选",
        "b_design": b,
        "h_design": h,
        "V_design": 1.11,
        "A_design": 4.506,
        "R_design": 0.927,
        "Beta_design": round(b / h, 3),
        "increase_percent": 5.0,
        "Q_increased": round(q * 1.05, 3),
        "h_increased": round(h + 0.08, 3),
        "V_increased": 1.06,
        "Fb": 0.612,
        "h_prime": round(h + 0.612, 3),
        "appendix_e_schemes": _sample_appendix_e_schemes(),
    }


def _make_multi_case_dummy(panel_cls, scripted_html=True):
    class _Dummy:
        pass

    dummy = _Dummy()
    dummy.detail_cb = _FakeCheckBox(False)
    dummy.result_text = _FakeResultView(scripted_html)
    dummy._appendix_e_export_text = ""
    dummy._export_plain_text = ""
    dummy._scripted_render_token = 0
    dummy._scripted_load_probe_handler = None
    dummy._suppress_result_render = False
    dummy._captured_render_body = ""
    dummy._captured_render_head = ""
    dummy._update_section_plot_all = lambda: None

    dummy._disconnect_scripted_probe_handler = MethodType(
        panel_cls._disconnect_scripted_probe_handler, dummy
    )
    dummy._render_result_html = MethodType(panel_cls._render_result_html, dummy)
    dummy._render_appendix_e_result_html = MethodType(
        panel_cls._render_appendix_e_result_html, dummy
    )
    dummy._build_appendix_e_payload = MethodType(
        panel_cls._build_appendix_e_payload, dummy
    )
    dummy._build_appendix_e_markup = MethodType(
        panel_cls._build_appendix_e_markup, dummy
    )
    dummy._build_ae_text = MethodType(panel_cls._build_ae_text, dummy)
    dummy._show_error = MethodType(panel_cls._show_error, dummy)
    dummy._show_trapezoid_brief = MethodType(panel_cls._show_trapezoid_brief, dummy)
    dummy._update_result_display = MethodType(panel_cls._update_result_display, dummy)
    return dummy


def test_appendix_e_payload_marks_selected_and_warning_rows():
    helper = _load_helper_module()
    schemes = [
        {
            "alpha": 1.0,
            "scheme_type": "水力最佳断面",
            "b": 1.3,
            "h": 1.57,
            "beta": 0.828,
            "V": 1.11,
            "area_increase": 0,
        },
        {
            "alpha": 1.04,
            "scheme_type": "实用经济断面",
            "b": 3.301,
            "h": 1.072,
            "beta": 3.08,
            "V": 8.2,
            "area_increase": 4,
        },
    ]

    payload = helper.make_appendix_e_payload(
        schemes,
        sel_b=1.3,
        sel_h=1.57,
        v_min=0.1,
        v_max=2.0,
    )

    assert payload["selected_row"] == 1
    assert payload["rows"][0]["statusCode"] == "selected"
    assert payload["rows"][0]["statusLabel"] == "已选中"
    assert payload["rows"][1]["statusCode"] == "warning"
    assert payload["rows"][1]["areaIncreaseLabel"] == "+4%"
    assert payload["columns"][0]["minWidth"] == 70
    assert payload["columns"][1]["minWidth"] == 164
    assert payload["columns"][5]["minWidth"] == 100
    assert payload["columns"][6]["minWidth"] == 82
    assert payload["columns"][7]["minWidth"] == 90
    assert payload["summary"]["title"] == "【附录E断面方案对比表】"


def test_appendix_e_tabulator_body_includes_handshake_probe_markup():
    helper = _load_helper_module()
    payload = helper.make_appendix_e_payload(
        [
            {
                "alpha": 1.0,
                "scheme_type": "水力最佳断面",
                "b": 1.3,
                "h": 1.57,
                "beta": 0.828,
                "V": 1.11,
                "area_increase": 0,
            }
        ],
        sel_b=1.3,
        sel_h=1.57,
        v_min=0.1,
        v_max=2.0,
    )

    head_html = helper.appendix_e_tabulator_head_html()
    body_html = helper.build_appendix_e_tabulator_body(payload)
    fallback_html = helper.build_appendix_e_static_body(payload)

    assert 'vendor/tabulator/tabulator.min.css' in head_html
    assert 'src="vendor/tabulator/tabulator.min.js"' in body_html
    assert 'layout: "fitDataStretch"' in body_html
    assert 'height: payload.rows.length > 8 ? "420px" : false' in body_html
    assert "display: flex;" not in head_html
    assert 'data-appendix-e-tabulator-ready' in body_html
    assert "appendix-e-runtime-status" in body_html
    assert "Tabulator 库未正确加载" in body_html
    assert "流速约束范围 0.1 ~ 2 m/s" in fallback_html
    assert "appendix-e-static-table-wrap" in fallback_html
    assert "appendix-e-badge is-selected" in fallback_html
    assert "overflow-x: hidden;" in head_html
    assert "min-width: 1080px" not in fallback_html


def test_appendix_e_static_body_contains_expected_headers_and_note():
    helper = _load_helper_module()
    payload = helper.make_appendix_e_payload(
        [
            {
                "alpha": 1.0,
                "scheme_type": "\u6c34\u529b\u6700\u4f73\u65ad\u9762",
                "b": 1.074,
                "h": 1.296,
                "beta": 0.828,
                "V": 0.977,
                "area_increase": 0,
            },
            {
                "alpha": 1.05,
                "scheme_type": "\u5b9e\u7528\u7ecf\u6d4e\u65ad\u9762",
                "b": 2.957,
                "h": 0.848,
                "beta": 3.488,
                "V": 0.930,
                "area_increase": 5,
            },
        ],
        sel_b=1.074,
        sel_h=1.296,
        v_min=0.1,
        v_max=100.0,
    )

    head_html = helper.appendix_e_shared_head_html()
    html = helper.build_appendix_e_static_body(payload)

    assert '<table class="appendix-e-static-table">' in html
    assert "<colgroup>" in html
    assert "overflow-x: hidden;" in head_html
    assert "min-width: 1080px" not in html
    assert "table-layout: fixed;" in head_html
    for header in (
        "\u03b1\u503c",
        "\u65b9\u6848\u7c7b\u578b",
        "\u5e95\u5bbd B (m)",
        "\u6c34\u6df1 h (m)",
        "\u5bbd\u6df1\u6bd4 \u03b2",
        "\u6d41\u901f V (m/s)",
        "\u9762\u79ef\u589e\u52a0",
        "\u72b6\u6001",
    ):
        assert f"<th>{header}</th>" in html
    assert "appendix-e-badge is-selected" in html
    assert "appendix-e-badge is-normal" in html
    assert "\u6d41\u901f\u7ea6\u675f\u8303\u56f4 0.1 ~ 100 m/s" in html


def test_appendix_e_qt_compatible_body_uses_qt_friendly_table_markup():
    helper = _load_helper_module()
    payload = helper.make_appendix_e_payload(
        [
            {
                "alpha": 1.0,
                "scheme_type": "\u6c34\u529b\u6700\u4f73\u65ad\u9762",
                "b": 1.074,
                "h": 1.296,
                "beta": 0.828,
                "V": 0.977,
                "area_increase": 0,
            },
            {
                "alpha": 1.05,
                "scheme_type": "\u5b9e\u7528\u7ecf\u6d4e\u65ad\u9762",
                "b": 2.957,
                "h": 0.848,
                "beta": 3.488,
                "V": 0.930,
                "area_increase": 5,
            },
        ],
        sel_b=1.074,
        sel_h=1.296,
        v_min=0.1,
        v_max=100.0,
    )

    html = helper.build_appendix_e_qt_compatible_body(
        payload, runtime_mode="QTextBrowser \u517c\u5bb9\u8868\u683c"
    )

    assert '<table border="1" cellspacing="0" cellpadding="6" width="100%">' in html
    assert '<th width="8%">\u03b1\u503c</th>' in html
    assert 'bgcolor="#EAF3FC"' in html
    assert 'align="left"' in html
    assert 'align="right"' in html
    assert '\u6e32\u67d3\u6a21\u5f0f: QTextBrowser \u517c\u5bb9\u8868\u683c' in html
    assert "appendix-e-badge" not in html
    assert "appendix-e-static-table" not in html


def test_open_channel_panel_renders_webengine_static_table_when_supported():
    helper = _load_helper_module()
    panel_mod = importlib.import_module(BASE_PACKAGE + ".open_channel.panel")
    panel_cls = panel_mod.OpenChannelPanel

    payload = helper.make_appendix_e_payload(
        [
            {
                "alpha": 1.0,
                "scheme_type": "\u6c34\u529b\u6700\u4f73\u65ad\u9762",
                "b": 1.074,
                "h": 1.296,
                "beta": 0.828,
                "V": 0.977,
                "area_increase": 0,
            }
        ],
        sel_b=1.074,
        sel_h=1.296,
        v_min=0.1,
        v_max=100.0,
    )

    panel = SimpleNamespace(result_text=SimpleNamespace(supports_scripted_html=True))
    markup = panel_cls._build_appendix_e_markup(panel, payload)
    captured = {}
    dummy = SimpleNamespace(
        _render_result_html=lambda html: captured.setdefault("html", html)
    )

    panel_cls._render_appendix_e_result_html(dummy, "PRE1", "PRE2", payload, markup)

    html = captured["html"]
    assert markup["mode"] == "webengine-static"
    assert "appendix-e-static-table" in html
    assert 'id="appendix-e-runtime-status"' not in html
    assert "data-appendix-e-tabulator-ready" not in html
    assert 'id="appendix-e-table-shell"' not in html
    assert "vendor/tabulator/tabulator.min.css" not in html
    assert "\u6e32\u67d3\u6a21\u5f0f: QWebEngineView \u9759\u6001\u8868\u683c" in html
    assert "PRE1" in html
    assert "PRE2" in html


def test_open_channel_panel_renders_qtextbrowser_compatible_table_when_fallback():
    helper = _load_helper_module()
    panel_mod = importlib.import_module(BASE_PACKAGE + ".open_channel.panel")
    panel_cls = panel_mod.OpenChannelPanel

    payload = helper.make_appendix_e_payload(
        [
            {
                "alpha": 1.0,
                "scheme_type": "\u6c34\u529b\u6700\u4f73\u65ad\u9762",
                "b": 1.074,
                "h": 1.296,
                "beta": 0.828,
                "V": 0.977,
                "area_increase": 0,
            }
        ],
        sel_b=1.074,
        sel_h=1.296,
        v_min=0.1,
        v_max=100.0,
    )

    panel = SimpleNamespace(result_text=SimpleNamespace(supports_scripted_html=False))
    markup = panel_cls._build_appendix_e_markup(panel, payload)
    captured = {}
    dummy = SimpleNamespace(
        _render_result_html=lambda html: captured.setdefault("html", html)
    )

    panel_cls._render_appendix_e_result_html(dummy, "PRE1", "PRE2", payload, markup)

    html = captured["html"]
    assert markup["mode"] == "qtextbrowser-compatible"
    assert '<table border="1" cellspacing="0" cellpadding="6" width="100%">' in html
    assert "appendix-e-static-table" not in html
    assert "appendix-e-badge" not in html
    assert "\u6e32\u67d3\u6a21\u5f0f: QTextBrowser \u517c\u5bb9\u8868\u683c" in html


def test_appendix_e_error_body_contains_runtime_diagnostics():
    helper = _load_helper_module()
    payload = helper.make_appendix_e_payload([], sel_b=1.0, sel_h=1.0, v_min=0.1, v_max=2.0)

    error_html = helper.build_appendix_e_error_body(
        payload,
        summary_text="未能确认 Tabulator 已在当前结果页完成初始化。",
        runtime_mode="QTextBrowser 降级视图",
        reason_text="当前结果页未进入 QWebEngineView，桌面端无法执行第三方表格脚本。",
        guidance_lines=["请确认发布目录完整。"],
    )

    assert "第三方表格未成功渲染" in error_html
    assert "当前模式:" in error_html
    assert "QTextBrowser 降级视图" in error_html
    assert "请确认发布目录完整。" in error_html


def test_open_channel_panel_multi_case_keeps_static_appendix_e_tables():
    panel_mod = importlib.import_module(BASE_PACKAGE + ".open_channel.panel")
    panel_cls = panel_mod.OpenChannelPanel
    dummy = _make_multi_case_dummy(panel_cls, scripted_html=True)
    dummy._all_results = [
        (0, _sample_trapezoid_params(4.0), _sample_trapezoid_result(4.0, 1.3, 1.57)),
        (1, _sample_trapezoid_params(5.0), _sample_trapezoid_result(5.0, 1.4, 1.48)),
    ]

    panel_cls._display_all_results(dummy)

    html = dummy.result_text.html

    assert html.count('<table class="appendix-e-static-table">') == 2
    assert "【工况 1｜梯形断面｜Q = 4.000 m³/s】" in html
    assert "【工况 2｜梯形断面｜Q = 5.000 m³/s】" in html
    assert dummy._export_plain_text.count("【附录E断面方案对比表】") == 2
    assert "α值 方案类型 底宽B(m)" not in html


def test_open_channel_panel_multi_case_keeps_qtextbrowser_appendix_tables():
    panel_mod = importlib.import_module(BASE_PACKAGE + ".open_channel.panel")
    panel_cls = panel_mod.OpenChannelPanel
    dummy = _make_multi_case_dummy(panel_cls, scripted_html=False)
    dummy._all_results = [
        (0, _sample_trapezoid_params(4.0), _sample_trapezoid_result(4.0, 1.3, 1.57)),
        (1, _sample_trapezoid_params(5.0), _sample_trapezoid_result(5.0, 1.4, 1.48)),
    ]

    panel_cls._display_all_results(dummy)

    html = dummy.result_text.html

    assert html.count('<table border="1" cellspacing="0" cellpadding="6" width="100%">') >= 2
    assert "appendix-e-static-table" not in html
    assert "【工况 1｜梯形断面｜Q = 4.000 m³/s】" in dummy._export_plain_text
    assert "【工况 2｜梯形断面｜Q = 5.000 m³/s】" in dummy._export_plain_text


def test_open_channel_panel_multi_case_mixed_success_and_failure_keeps_success_table():
    panel_mod = importlib.import_module(BASE_PACKAGE + ".open_channel.panel")
    panel_cls = panel_mod.OpenChannelPanel
    dummy = _make_multi_case_dummy(panel_cls, scripted_html=True)
    dummy._all_results = [
        (0, _sample_trapezoid_params(4.0), _sample_trapezoid_result(4.0, 1.3, 1.57)),
        (
            1,
            _sample_trapezoid_params(6.0),
            {"success": False, "error_message": "工况2: 计算无解"},
        ),
    ]

    panel_cls._display_all_results(dummy)

    html = dummy.result_text.html

    assert html.count('<table class="appendix-e-static-table">') == 1
    assert "工况2: 计算无解" in html
    assert "请修正后重新计算。" in html
