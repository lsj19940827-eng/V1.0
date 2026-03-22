# -*- coding: utf-8 -*-
"""Unit tests for aqueduct section-plot titles and plot routing."""

import importlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from matplotlib.figure import Figure

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

aqueduct_panel_mod = importlib.import_module("app_渠系计算前端.aqueduct.panel")


def _u_result():
    return {
        "success": True,
        "section_type": "U形",
        "R": 1.4,
        "f": 0.6,
        "H_total": 2.0,
        "h_design": 1.2,
        "V_design": 1.1,
        "Q_increased": 6.0,
        "h_increased": 1.45,
        "V_increased": 1.2,
    }


def _rect_result(*, has_chamfer=False, custom_label=None):
    result = {
        "success": True,
        "section_type": "矩形",
        "B": 3.41,
        "H_total": 2.72,
        "h_design": 2.27,
        "V_design": 1.30,
        "Q_increased": 12.0,
        "h_increased": 2.62,
        "V_increased": 1.35,
        "has_chamfer": has_chamfer,
        "chamfer_angle": 30 if has_chamfer else 0,
        "chamfer_length": 0.2 if has_chamfer else 0,
    }
    if custom_label is not None:
        result["custom_label"] = custom_label
    return result


class _PlotAllDummy:
    _section_plot_title = staticmethod(aqueduct_panel_mod.AqueductPanel._section_plot_title)

    def __init__(self, all_results, cases):
        self.section_fig = Figure()
        self.section_canvas = SimpleNamespace(draw=lambda: None)
        self._all_results = all_results
        self._cases = cases
        self.calls = []

    def _draw_u_section(self, _ax, R, f, H_total, h_w, V, Q, title):
        self.calls.append(
            {
                "kind": "U形",
                "R": R,
                "f": f,
                "H_total": H_total,
                "h_w": h_w,
                "V": V,
                "Q": Q,
                "title": title,
            }
        )

    def _draw_rect_section(self, _ax, B, H_total, h_w, V, Q, title, result=None):
        self.calls.append(
            {
                "kind": "矩形",
                "B": B,
                "H_total": H_total,
                "h_w": h_w,
                "V": V,
                "Q": Q,
                "title": title,
                "result": result,
            }
        )


class _SinglePlotDummy:
    def __init__(self, input_params):
        self.section_fig = Figure()
        self.section_canvas = SimpleNamespace(draw=lambda: None)
        self.input_params = input_params
        self.titles = []

    def _draw_u_section(self, *_args):
        self.titles.append(_args[-1])

    def _draw_rect_section(self, *_args, **_kwargs):
        self.titles.append(_args[6])


class _DrawDummy:
    _apply_section_plot_title = staticmethod(aqueduct_panel_mod.AqueductPanel._apply_section_plot_title)


def test_update_section_plot_all_uses_original_case_numbered_titles_and_h_total():
    rect_result = _rect_result()
    dummy = _PlotAllDummy(
        [
            (0, {"section_type": "U形", "Q": 5.0}, _u_result()),
            (1, {"section_type": "矩形", "Q": 8.0}, {"success": False, "error_message": "缺少参数"}),
            (2, {"section_type": "矩形", "Q": 10.0}, rect_result),
        ],
        [
            {"section_type": "U形"},
            {"section_type": "矩形"},
            {"section_type": "矩形"},
        ],
    )

    aqueduct_panel_mod.AqueductPanel._update_section_plot_all(dummy)

    assert [call["title"] for call in dummy.calls] == ["工况 1｜U形", "工况 3｜矩形"]
    assert dummy.calls[0]["kind"] == "U形"
    assert dummy.calls[1]["kind"] == "矩形"
    assert dummy.calls[1]["H_total"] == pytest.approx(rect_result["H_total"])


def test_update_section_plot_all_prefers_custom_label_and_passes_rect_result_through():
    rect_result = _rect_result(has_chamfer=True)
    dummy = _PlotAllDummy(
        [
            (0, {"section_type": "U形", "Q": 5.0}, _u_result()),
            (1, {"section_type": "矩形", "Q": 10.0}, rect_result),
        ],
        [
            {"section_type": "U形"},
            {"section_type": "矩形", "custom_label": "北干槽试算"},
        ],
    )

    aqueduct_panel_mod.AqueductPanel._update_section_plot_all(dummy)

    assert [call["title"] for call in dummy.calls] == ["工况 1｜U形", "北干槽试算"]
    assert dummy.calls[1]["result"] is rect_result
    assert dummy.calls[1]["result"]["has_chamfer"] is True


@pytest.mark.parametrize(
    ("section_type", "result_factory"),
    [("U形", _u_result), ("矩形", _rect_result)],
)
def test_update_section_plot_uses_single_subplot_when_increase_disabled(section_type, result_factory):
    dummy = _SinglePlotDummy({"Q": 5.0, "use_increase": False, "section_type": section_type})

    aqueduct_panel_mod.AqueductPanel._update_section_plot(dummy, result_factory())

    assert len(dummy.section_fig.axes) == 1
    assert dummy.titles == ["设计流量"]


@pytest.mark.parametrize(
    ("section_type", "result_factory"),
    [("U形", _u_result), ("矩形", _rect_result)],
)
def test_update_section_plot_uses_two_subplots_when_increase_enabled(section_type, result_factory):
    dummy = _SinglePlotDummy({"Q": 5.0, "use_increase": True, "section_type": section_type})

    aqueduct_panel_mod.AqueductPanel._update_section_plot(dummy, result_factory())

    assert len(dummy.section_fig.axes) == 2
    assert dummy.titles == ["设计流量", "加大流量"]


def test_draw_u_section_spans_negative_and_positive_x_coordinates():
    dummy = _DrawDummy()
    fig = Figure()
    ax = fig.subplots()

    aqueduct_panel_mod.AqueductPanel._draw_u_section(
        dummy,
        ax,
        R=1.4,
        f=0.6,
        H_total=2.0,
        h_w=1.2,
        V=1.1,
        Q=5.0,
        title="工况 1｜U形",
    )

    all_x = []
    for line in ax.lines:
        all_x.extend(list(line.get_xdata()))

    assert min(all_x) < -1.35
    assert max(all_x) > 1.35

    title = ax.get_title()
    assert "工况 1｜U形" in title
    assert r"\mathregular{m^{3}/s}" in title
    assert r"\mathregular{m/s}" in title
