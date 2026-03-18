# -*- coding: utf-8 -*-
"""Regression tests for formula-rendered result pages."""

import importlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "codex-mplconfig"))

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for calc_dir in ROOT.glob("calc_*"):
    calc_path = str(calc_dir)
    if calc_path not in sys.path:
        sys.path.insert(0, calc_path)

renderer = importlib.import_module("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.formula_renderer")
result_nav = importlib.import_module("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.result_navigation")
aqueduct_panel_mod = importlib.import_module("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.aqueduct.panel")
tunnel_panel_mod = importlib.import_module("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.tunnel.panel")
culvert_panel_mod = importlib.import_module("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.culvert.panel")
aqueduct_kernel = importlib.import_module("\u6e21\u69fd\u8bbe\u8ba1")
tunnel_kernel = importlib.import_module("\u96a7\u6d1e\u8bbe\u8ba1")
culvert_kernel = importlib.import_module("\u77e9\u5f62\u6697\u6db5\u8bbe\u8ba1")


def _capture_formula_page(monkeypatch, panel_module):
    captured = {}

    def _fake_load_formula_page(_view, html, base_path=None):
        captured["html"] = html
        captured["base_path"] = base_path

    monkeypatch.setattr(panel_module, "load_formula_page", _fake_load_formula_page)
    return captured


def _assert_wrapped_result_page_html(html, *, expect_nav, min_svg, min_case_blocks):
    stripped = html.lstrip()

    assert stripped.startswith("<html>")
    assert "<body>" in html
    assert "</html>" in html
    assert ".section-banner {" in html
    assert ".step-card {" in html
    assert ".formula-line {" in html
    assert ".codex-case-nav {" in html
    assert ".codex-case-block {" in html
    assert html.count("<svg") >= min_svg
    assert html.count('class="codex-case-block') >= min_case_blocks
    if expect_nav:
        assert 'class="codex-case-nav"' in html


@pytest.mark.parametrize(
    ("text", "min_svg", "min_subtitle"),
    [
        ("\u8bbe\u8ba1\u6d41\u91cf Q = 10.000 m\u00b3/s", 1, 1),
        ("\u65ad\u9762\u603b\u9762\u79ef A\u603b = \u03c0\u00d7D\u00b2/4 = 8.762 m\u00b2", 1, 1),
        ("\u7cdf\u7387 n = 0.014, \u6c34\u529b\u5761\u964d = 1/2000", 2, 1),
        (
            "\u51c0\u7a7a\u9ad8\u5ea6 Fb\u52a0\u5927 = H - h\u52a0\u5927 = 2.700 - 2.300 = 0.400 m, "
            "\u51c0\u7a7a\u6bd4 PA\u52a0\u5927 = 18.0%",
            2,
            2,
        ),
        ("\u8bef\u5dee = 0.04%", 1, 0),
    ],
)
def test_formula_renderer_handles_prefixed_and_parallel_engineering_formulas(text, min_svg, min_subtitle):
    body = renderer.plain_text_to_formula_body(text)

    assert body.count("<svg") >= min_svg
    assert body.count("info-subtitle") >= min_subtitle
    assert "content-line" not in body


@pytest.mark.parametrize(
    ("text", "expected_tokens"),
    [
        ("A总 = π × D² / 4", [r"\pi", r"\times", r"^{2}"]),
        ("\u0041\u603b = \u87fa\u8133D\u864f/4", [r"\pi", r"\times", r"^{2}"]),
        ("χ加大 = (D/2) × θ加大", [r"\chi_{\text{加大}}", r"\times", r"\theta_{\text{加大}}"]),
    ],
)
def test_text_to_latex_normalizes_engineering_symbols_without_leaking_legacy_placeholders(
    text,
    expected_tokens,
):
    latex = renderer.text_to_latex(text)

    assert latex is not None
    for token in expected_tokens:
        assert token in latex
    for legacy in ("蠂", "尾", "胃", "蟺", "味", "脑", "梅", "鈭", "虏", "鲁", "掳"):
        assert legacy not in latex


def test_aqueduct_u_detail_result_page_renders_svg_cards():
    result = aqueduct_kernel.quick_calculate_u(
        Q=5.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=100.0,
        manual_R=None,
        manual_increase_percent=None,
    )

    class _Dummy:
        pass

    dummy = _Dummy()
    dummy.input_params = {
        "Q": 5.0,
        "n": 0.014,
        "slope_inv": 3000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "manual_increase": None,
        "use_increase": True,
    }
    dummy._export_plain_text = ""
    dummy.html = ""
    dummy._render_result_html = lambda html: setattr(dummy, "html", html)

    aqueduct_panel_mod.AqueductPanel._show_u_detail(dummy, result)

    assert dummy.html.count("<svg") >= 20
    assert "section-banner" in dummy.html
    assert "step-card" in dummy.html


def test_tunnel_circular_detail_result_page_renders_svg_cards(monkeypatch):
    captured = _capture_formula_page(monkeypatch, tunnel_panel_mod)
    result = tunnel_kernel.quick_calculate_circular(
        Q=10.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        manual_D=None,
        manual_increase_percent=None,
    )

    class _Dummy:
        pass

    dummy = _Dummy()
    dummy.input_params = {
        "Q": 10.0,
        "n": 0.014,
        "slope_inv": 2000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "use_increase": True,
        "manual_increase": None,
        "section_type": "\u5706\u5f62",
    }
    dummy.result_text = object()
    dummy._export_plain_text = ""

    tunnel_panel_mod.TunnelPanel._show_result(dummy, result, "\u5706\u5f62", True)
    html = captured["html"]

    assert html.count("<svg") >= 15
    assert "section-banner" in html
    assert "step-card" in html


def test_culvert_detail_result_page_renders_svg_cards():
    params = {
        "Q": 5.0,
        "n": 0.014,
        "slope_inv": 2000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "use_increase": True,
        "manual_increase": None,
        "target_HB_ratio": None,
    }
    result = culvert_kernel.quick_calculate_rectangular_culvert(
        Q=5.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        target_BH_ratio=None,
        target_HB_ratio=None,
        manual_B=None,
        manual_increase_percent=None,
    )

    detail_text = culvert_panel_mod.CulvertPanel._build_culvert_result_text(object(), params, result, True)
    detail_html = renderer.plain_text_to_formula_html(detail_text)

    assert detail_html.count("<svg") >= 20
    assert "section-banner" in detail_html
    assert "step-card" in detail_html


def test_brief_results_across_modules_keep_formula_svg(monkeypatch):
    aqueduct_result = aqueduct_kernel.quick_calculate_u(
        Q=5.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=100.0,
        manual_R=None,
        manual_increase_percent=None,
    )
    tunnel_result = tunnel_kernel.quick_calculate_circular(
        Q=10.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        manual_D=None,
        manual_increase_percent=None,
    )
    culvert_result = culvert_kernel.quick_calculate_rectangular_culvert(
        Q=5.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        target_BH_ratio=None,
        target_HB_ratio=None,
        manual_B=None,
        manual_increase_percent=None,
    )

    class _Dummy:
        pass

    aqueduct_dummy = _Dummy()
    aqueduct_dummy.input_params = {
        "Q": 5.0,
        "n": 0.014,
        "slope_inv": 3000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "manual_increase": None,
        "use_increase": True,
    }
    aqueduct_dummy.html = ""
    aqueduct_dummy._export_plain_text = ""
    aqueduct_dummy._render_result_html = lambda html: setattr(aqueduct_dummy, "html", html)
    aqueduct_panel_mod.AqueductPanel._show_u_brief(aqueduct_dummy, aqueduct_result)

    tunnel_capture = _capture_formula_page(monkeypatch, tunnel_panel_mod)
    tunnel_dummy = _Dummy()
    tunnel_dummy.input_params = {
        "Q": 10.0,
        "n": 0.014,
        "slope_inv": 2000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "use_increase": True,
        "manual_increase": None,
        "section_type": "\u5706\u5f62",
    }
    tunnel_dummy.result_text = object()
    tunnel_dummy._export_plain_text = ""
    tunnel_panel_mod.TunnelPanel._show_result(tunnel_dummy, tunnel_result, "\u5706\u5f62", False)

    culvert_params = {
        "Q": 5.0,
        "n": 0.014,
        "slope_inv": 2000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "use_increase": True,
        "manual_increase": None,
        "target_HB_ratio": None,
    }
    culvert_brief_text = culvert_panel_mod.CulvertPanel._build_culvert_result_text(
        object(),
        culvert_params,
        culvert_result,
        False,
    )
    culvert_brief_html = renderer.plain_text_to_formula_html(culvert_brief_text)

    assert aqueduct_dummy.html.count("<svg") >= 8
    assert tunnel_capture["html"].count("<svg") >= 6
    assert culvert_brief_html.count("<svg") >= 8


def test_culvert_multi_case_page_keeps_navigation_and_formula_svg(monkeypatch):
    captured = _capture_formula_page(monkeypatch, culvert_panel_mod)
    result_a = culvert_kernel.quick_calculate_rectangular_culvert(
        Q=5.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        target_BH_ratio=None,
        target_HB_ratio=None,
        manual_B=None,
        manual_increase_percent=None,
    )
    result_b = culvert_kernel.quick_calculate_rectangular_culvert(
        Q=8.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        target_BH_ratio=None,
        target_HB_ratio=None,
        manual_B=None,
        manual_increase_percent=None,
    )
    params_a = {
        "Q": 5.0,
        "n": 0.014,
        "slope_inv": 2000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "use_increase": True,
        "manual_increase": None,
        "target_HB_ratio": None,
    }
    params_b = {
        "Q": 8.0,
        "n": 0.014,
        "slope_inv": 2000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "use_increase": True,
        "manual_increase": None,
        "target_HB_ratio": None,
    }

    class _Dummy:
        pass

    dummy = _Dummy()
    dummy._cases = [{"detail_checked": True}, {"detail_checked": False}]
    dummy._all_results = [(0, params_a, result_a), (1, params_b, result_b)]
    dummy._panel_key = "culvert"
    dummy._current_case_idx = 1
    dummy.result_text = object()
    dummy._export_plain_text = ""
    dummy._has_rendered_results = True
    dummy._results_dirty = False
    dummy._build_culvert_result_text = (
        lambda params, result, detail, case_num=None: culvert_panel_mod.CulvertPanel._build_culvert_result_text(
            object(),
            params,
            result,
            detail,
            case_num,
        )
    )
    dummy._case_result_nav_label = lambda idx: f"\u5de5\u51b5 {idx + 1}"
    dummy._build_case_nav_items = lambda: [
        {
            "anchor_id": result_nav.make_case_result_anchor(dummy._panel_key, case_idx),
            "label": f"\u5de5\u51b5 {case_idx + 1}",
            "summary": f"Q={params['Q']:.3f}",
            "is_error": False,
        }
        for case_idx, params, _result in dummy._all_results
    ]
    dummy._mark_results_fresh = lambda: setattr(dummy, "_results_dirty", False)
    dummy._jump_to_case_result = lambda *_args, **_kwargs: True
    dummy._update_section_plot_all = lambda: None

    culvert_panel_mod.CulvertPanel._display_all_results(dummy)
    html = captured["html"]

    _assert_wrapped_result_page_html(html, expect_nav=True, min_svg=12, min_case_blocks=2)


def test_aqueduct_single_case_result_page_wraps_full_formula_html(monkeypatch):
    captured = _capture_formula_page(monkeypatch, aqueduct_panel_mod)
    result = aqueduct_kernel.quick_calculate_u(
        Q=5.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=100.0,
        manual_R=None,
        manual_increase_percent=None,
    )
    params = {
        "Q": 5.0,
        "n": 0.014,
        "slope_inv": 3000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "manual_increase": None,
        "use_increase": True,
        "section_type": "\u0055\u5f62",
    }

    class _Dummy:
        pass

    dummy = _Dummy()
    dummy.input_params = params
    dummy.current_result = result
    dummy._panel_key = "aqueduct"
    dummy._all_results = [(0, params, result)]
    dummy._current_case_idx = 0
    dummy._export_plain_text = ""
    dummy._suppress_result_render = False
    dummy.result_text = object()
    dummy._case_result_nav_label = lambda idx: f"\u5de5\u51b5 {idx + 1} U\u5f62 \u00b7 Q={params['Q']:.3f}"
    dummy._build_case_nav_items = lambda: [
        {
            "anchor_id": result_nav.make_case_result_anchor(dummy._panel_key, 0),
            "label": "\u5de5\u51b5 1",
            "summary": f"Q={params['Q']:.3f}",
            "is_error": False,
        }
    ]
    dummy._mark_results_fresh = lambda: None
    dummy._jump_to_case_result = lambda *_args, **_kwargs: True
    dummy._update_section_plot_all = lambda: None
    dummy._render_result_html = lambda html: aqueduct_panel_mod.AqueductPanel._render_result_html(dummy, html)
    dummy._update_result_display = lambda current_result: aqueduct_panel_mod.AqueductPanel._show_u_detail(
        dummy, current_result
    )

    aqueduct_panel_mod.AqueductPanel._display_all_results(dummy)

    _assert_wrapped_result_page_html(
        captured["html"],
        expect_nav=False,
        min_svg=20,
        min_case_blocks=1,
    )


def test_aqueduct_multi_case_result_page_keeps_navigation_and_formula_css(monkeypatch):
    captured = _capture_formula_page(monkeypatch, aqueduct_panel_mod)
    params_a = {
        "Q": 5.0,
        "n": 0.014,
        "slope_inv": 3000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "manual_increase": None,
        "use_increase": True,
        "section_type": "\u0055\u5f62",
    }
    params_b = {
        "Q": 8.0,
        "n": 0.014,
        "slope_inv": 3000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "manual_increase": None,
        "use_increase": True,
        "section_type": "\u0055\u5f62",
    }
    result_a = aqueduct_kernel.quick_calculate_u(
        Q=5.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=100.0,
        manual_R=None,
        manual_increase_percent=None,
    )
    result_b = aqueduct_kernel.quick_calculate_u(
        Q=8.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=100.0,
        manual_R=None,
        manual_increase_percent=None,
    )

    class _Dummy:
        pass

    dummy = _Dummy()
    dummy.input_params = params_a
    dummy.current_result = result_a
    dummy._panel_key = "aqueduct"
    dummy._all_results = [(0, params_a, result_a), (1, params_b, result_b)]
    dummy._current_case_idx = 1
    dummy._export_plain_text = ""
    dummy._suppress_result_render = False
    dummy.result_text = object()
    dummy._case_result_nav_label = lambda idx: (
        f"\u5de5\u51b5 {idx + 1} U\u5f62 \u00b7 Q={dummy._all_results[idx][1]['Q']:.3f}"
    )
    dummy._build_case_nav_items = lambda: [
        {
            "anchor_id": result_nav.make_case_result_anchor(dummy._panel_key, case_idx),
            "label": f"\u5de5\u51b5 {case_idx + 1}",
            "summary": f"Q={params['Q']:.3f}",
            "is_error": False,
        }
        for case_idx, params, _result in dummy._all_results
    ]
    dummy._mark_results_fresh = lambda: None
    dummy._jump_to_case_result = lambda *_args, **_kwargs: True
    dummy._update_section_plot_all = lambda: None
    dummy._render_result_html = lambda html: aqueduct_panel_mod.AqueductPanel._render_result_html(dummy, html)
    dummy._update_result_display = lambda current_result: aqueduct_panel_mod.AqueductPanel._show_u_detail(
        dummy, current_result
    )

    aqueduct_panel_mod.AqueductPanel._display_all_results(dummy)

    _assert_wrapped_result_page_html(
        captured["html"],
        expect_nav=True,
        min_svg=30,
        min_case_blocks=2,
    )


def test_tunnel_single_case_result_page_wraps_full_formula_html(monkeypatch):
    captured = _capture_formula_page(monkeypatch, tunnel_panel_mod)
    params = {
        "Q": 10.0,
        "n": 0.014,
        "slope_inv": 2000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "use_increase": True,
        "manual_increase": None,
        "section_type": "\u5706\u5f62",
        "detail_checked": True,
    }
    result = tunnel_kernel.quick_calculate_circular(
        Q=10.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        manual_D=None,
        manual_increase_percent=None,
    )

    class _Dummy:
        pass

    dummy = _Dummy()
    dummy._panel_key = "tunnel"
    dummy._all_results = [{"input": params, "result": result, "case": {"section_type": "\u5706\u5f62", "Q": 10.0}}]
    dummy._current_case_idx = 0
    dummy._export_plain_text = ""
    dummy.result_text = object()
    dummy._case_result_nav_label = lambda idx: f"\u5de5\u51b5 {idx + 1} \u5706\u5f62 \u00b7 Q=10.000"
    dummy._build_case_nav_items = lambda: [
        {
            "anchor_id": result_nav.make_case_result_anchor(dummy._panel_key, 0),
            "label": "\u5de5\u51b5 1",
            "summary": "Q=10.000",
            "is_error": False,
        }
    ]
    dummy._mark_results_fresh = lambda: None
    dummy._jump_to_case_result = lambda *_args, **_kwargs: True
    dummy._build_result_text = lambda res, type_label, detail, p: tunnel_panel_mod.TunnelPanel._build_result_text(
        dummy,
        res,
        type_label,
        detail,
        p,
    )

    tunnel_panel_mod.TunnelPanel._display_all_results(dummy)

    _assert_wrapped_result_page_html(
        captured["html"],
        expect_nav=False,
        min_svg=8,
        min_case_blocks=1,
    )


def test_tunnel_multi_case_result_page_keeps_navigation_and_formula_css(monkeypatch):
    captured = _capture_formula_page(monkeypatch, tunnel_panel_mod)
    params_a = {
        "Q": 10.0,
        "n": 0.014,
        "slope_inv": 2000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "use_increase": True,
        "manual_increase": None,
        "section_type": "\u5706\u5f62",
        "detail_checked": True,
    }
    params_b = {
        "Q": 12.0,
        "n": 0.014,
        "slope_inv": 2000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "use_increase": True,
        "manual_increase": None,
        "section_type": "\u5706\u5f62",
        "detail_checked": False,
    }
    result_a = tunnel_kernel.quick_calculate_circular(
        Q=10.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        manual_D=None,
        manual_increase_percent=None,
    )
    result_b = tunnel_kernel.quick_calculate_circular(
        Q=12.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        manual_D=None,
        manual_increase_percent=None,
    )

    class _Dummy:
        pass

    dummy = _Dummy()
    dummy._panel_key = "tunnel"
    dummy._all_results = [
        {"input": params_a, "result": result_a, "case": {"section_type": "\u5706\u5f62", "Q": 10.0}},
        {"input": params_b, "result": result_b, "case": {"section_type": "\u5706\u5f62", "Q": 12.0}},
    ]
    dummy._current_case_idx = 1
    dummy._export_plain_text = ""
    dummy.result_text = object()
    dummy._case_result_nav_label = lambda idx: (
        f"\u5de5\u51b5 {idx + 1} \u5706\u5f62 \u00b7 Q={dummy._all_results[idx]['input']['Q']:.3f}"
    )
    dummy._build_case_nav_items = lambda: [
        {
            "anchor_id": result_nav.make_case_result_anchor(dummy._panel_key, idx),
            "label": f"\u5de5\u51b5 {idx + 1}",
            "summary": f"Q={item['input']['Q']:.3f}",
            "is_error": False,
        }
        for idx, item in enumerate(dummy._all_results)
    ]
    dummy._mark_results_fresh = lambda: None
    dummy._jump_to_case_result = lambda *_args, **_kwargs: True
    dummy._build_result_text = lambda res, type_label, detail, p: tunnel_panel_mod.TunnelPanel._build_result_text(
        dummy,
        res,
        type_label,
        detail,
        p,
    )

    tunnel_panel_mod.TunnelPanel._display_all_results(dummy)

    _assert_wrapped_result_page_html(
        captured["html"],
        expect_nav=True,
        min_svg=12,
        min_case_blocks=2,
    )


def test_culvert_single_case_result_page_wraps_full_formula_html(monkeypatch):
    captured = _capture_formula_page(monkeypatch, culvert_panel_mod)
    result = culvert_kernel.quick_calculate_rectangular_culvert(
        Q=5.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        target_BH_ratio=None,
        target_HB_ratio=None,
        manual_B=None,
        manual_increase_percent=None,
    )
    params = {
        "Q": 5.0,
        "n": 0.014,
        "slope_inv": 2000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "use_increase": True,
        "manual_increase": None,
        "target_HB_ratio": None,
    }

    class _Dummy:
        pass

    dummy = _Dummy()
    dummy._cases = [{"detail_checked": True}]
    dummy._all_results = [(0, params, result)]
    dummy._panel_key = "culvert"
    dummy._current_case_idx = 0
    dummy.result_text = object()
    dummy._export_plain_text = ""
    dummy._has_rendered_results = True
    dummy._results_dirty = False
    dummy._build_culvert_result_text = (
        lambda current_params, current_result, detail, case_num=None: culvert_panel_mod.CulvertPanel._build_culvert_result_text(
            object(),
            current_params,
            current_result,
            detail,
            case_num,
        )
    )
    dummy._case_result_nav_label = lambda idx: f"\u5de5\u51b5 {idx + 1} \u77e9\u5f62\u6697\u6db5 \u00b7 Q={params['Q']:.3f}"
    dummy._build_case_nav_items = lambda: [
        {
            "anchor_id": result_nav.make_case_result_anchor(dummy._panel_key, 0),
            "label": "\u5de5\u51b5 1",
            "summary": f"Q={params['Q']:.3f}",
            "is_error": False,
        }
    ]
    dummy._mark_results_fresh = lambda: setattr(dummy, "_results_dirty", False)
    dummy._jump_to_case_result = lambda *_args, **_kwargs: True
    dummy._update_section_plot_all = lambda: None

    culvert_panel_mod.CulvertPanel._display_all_results(dummy)

    _assert_wrapped_result_page_html(
        captured["html"],
        expect_nav=False,
        min_svg=12,
        min_case_blocks=1,
    )


def test_culvert_multi_case_result_page_wraps_full_formula_html(monkeypatch):
    captured = _capture_formula_page(monkeypatch, culvert_panel_mod)
    result_a = culvert_kernel.quick_calculate_rectangular_culvert(
        Q=5.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        target_BH_ratio=None,
        target_HB_ratio=None,
        manual_B=None,
        manual_increase_percent=None,
    )
    result_b = culvert_kernel.quick_calculate_rectangular_culvert(
        Q=8.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        target_BH_ratio=None,
        target_HB_ratio=None,
        manual_B=None,
        manual_increase_percent=None,
    )
    params_a = {
        "Q": 5.0,
        "n": 0.014,
        "slope_inv": 2000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "use_increase": True,
        "manual_increase": None,
        "target_HB_ratio": None,
    }
    params_b = {
        "Q": 8.0,
        "n": 0.014,
        "slope_inv": 2000.0,
        "v_min": 0.1,
        "v_max": 100.0,
        "use_increase": True,
        "manual_increase": None,
        "target_HB_ratio": None,
    }

    class _Dummy:
        pass

    dummy = _Dummy()
    dummy._cases = [{"detail_checked": True}, {"detail_checked": False}]
    dummy._all_results = [(0, params_a, result_a), (1, params_b, result_b)]
    dummy._panel_key = "culvert"
    dummy._current_case_idx = 1
    dummy.result_text = object()
    dummy._export_plain_text = ""
    dummy._has_rendered_results = True
    dummy._results_dirty = False
    dummy._build_culvert_result_text = (
        lambda current_params, current_result, detail, case_num=None: culvert_panel_mod.CulvertPanel._build_culvert_result_text(
            object(),
            current_params,
            current_result,
            detail,
            case_num,
        )
    )
    dummy._case_result_nav_label = lambda idx: f"\u5de5\u51b5 {idx + 1}"
    dummy._build_case_nav_items = lambda: [
        {
            "anchor_id": result_nav.make_case_result_anchor(dummy._panel_key, case_idx),
            "label": f"\u5de5\u51b5 {case_idx + 1}",
            "summary": f"Q={params['Q']:.3f}",
            "is_error": False,
        }
        for case_idx, params, _result in dummy._all_results
    ]
    dummy._mark_results_fresh = lambda: setattr(dummy, "_results_dirty", False)
    dummy._jump_to_case_result = lambda *_args, **_kwargs: True
    dummy._update_section_plot_all = lambda: None

    culvert_panel_mod.CulvertPanel._display_all_results(dummy)

    _assert_wrapped_result_page_html(
        captured["html"],
        expect_nav=True,
        min_svg=12,
        min_case_blocks=2,
    )
