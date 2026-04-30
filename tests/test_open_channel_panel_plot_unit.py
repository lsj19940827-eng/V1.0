# -*- coding: utf-8 -*-
"""明渠断面图绘制回归测试。"""

import importlib
import inspect
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from matplotlib.figure import Figure


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "codex-mplconfig"),
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for calc_dir in ROOT.glob("calc_*"):
    calc_path = str(calc_dir)
    if calc_path not in sys.path:
        sys.path.insert(0, calc_path)

open_channel_panel_mod = importlib.import_module("app_渠系计算前端.open_channel.panel")


class _PlotAllDummy:
    """只挂载断面图所需属性和绘图方法。"""

    _multi_case_section_plot_title = (
        open_channel_panel_mod.OpenChannelPanel._multi_case_section_plot_title
    )
    _draw_case_section_plot = open_channel_panel_mod.OpenChannelPanel._draw_case_section_plot
    _draw_trapezoid = open_channel_panel_mod.OpenChannelPanel._draw_trapezoid
    _draw_circular = open_channel_panel_mod.OpenChannelPanel._draw_circular
    _draw_compound_trapezoid = open_channel_panel_mod.OpenChannelPanel._draw_compound_trapezoid
    _draw_u_section = open_channel_panel_mod.OpenChannelPanel._draw_u_section
    _compound_trapezoid_geometry = (
        open_channel_panel_mod.OpenChannelPanel._compound_trapezoid_geometry
    )
    _compound_trapezoid_water_points = (
        open_channel_panel_mod.OpenChannelPanel._compound_trapezoid_water_points
    )
    _compound_trapezoid_view_limits = (
        open_channel_panel_mod.OpenChannelPanel._compound_trapezoid_view_limits
    )

    def __init__(self, all_results):
        self.section_fig = Figure()
        self.section_canvas = SimpleNamespace(draw=lambda: None)
        self._all_results = all_results
        self.input_params = {}


def _base_trapezoid_case(section_type, q, h):
    """构造梯形或矩形明渠断面图工况。"""
    m = 1.0 if section_type == "梯形" else 0.0
    return (
        {"section_type": section_type, "Q": q, "m": m, "use_increase": True},
        {
            "success": True,
            "b_design": 1.30,
            "h_design": h,
            "h_prime": h + 0.40,
            "V_design": 1.11,
            "Q_increased": q * 1.2,
            "h_increased": h + 0.20,
            "V_increased": 1.16,
        },
    )


def _circular_case(q, diameter, water_depth):
    """构造圆形明渠断面图工况。"""
    return (
        {"section_type": "圆形", "Q": q, "use_increase": True},
        {
            "success": True,
            "D_design": diameter,
            "y_d": water_depth,
            "V_d": 1.05,
        },
    )


def _u_case(q, radius, water_depth):
    """构造 U 形明渠断面图工况。"""
    return (
        {"section_type": "U形", "Q": q, "use_increase": True},
        {
            "success": True,
            "R": radius,
            "alpha_deg": 12.0,
            "theta_deg": 120.0,
            "h_design": water_depth,
            "h_prime": water_depth + 0.60,
            "V_design": 1.08,
            "Q_increased": q * 1.2,
            "h_increased": water_depth + 0.20,
            "V_increased": 1.18,
        },
    )


def _compound_case(q, water_depth):
    """构造复式梯形明渠断面图工况。"""
    return (
        {
            "section_type": "复式梯形",
            "Q": q,
            "m1": 1.0,
            "B1": 2.0,
            "m2": 1.0,
            "B2": 1.50,
            "m3": 1.0,
            "h1": 1.0,
            "use_increase": True,
        },
        {
            "success": True,
            "b_design": 1.50,
            "h_design": water_depth,
            "h_prime": water_depth + 0.50,
            "V_design": 1.12,
            "Q_increased": q * 1.2,
            "h_increased": water_depth + 0.20,
            "V_increased": 1.22,
        },
    )


@pytest.mark.parametrize(
    ("case_factory", "expected_labels"),
    [
        (
            lambda: [
                _base_trapezoid_case("梯形", 5.0, 1.57),
                _base_trapezoid_case("梯形", 8.0, 1.70),
            ],
            ("B=", "H=", "h="),
        ),
        (
            lambda: [
                _base_trapezoid_case("矩形", 5.0, 1.40),
                _base_trapezoid_case("矩形", 8.0, 1.60),
            ],
            ("B=", "H=", "h="),
        ),
        (
            lambda: [
                _circular_case(5.0, 2.40, 1.30),
                _circular_case(8.0, 2.80, 1.50),
            ],
            ("D=", "y="),
        ),
        (
            lambda: [
                _u_case(5.0, 1.20, 1.10),
                _u_case(8.0, 1.40, 1.25),
            ],
            ("R=", "h="),
        ),
        (
            lambda: [
                _compound_case(5.0, 1.30),
                _compound_case(8.0, 1.45),
            ],
            ("B2=", "B1=", "H=", "h="),
        ),
    ],
)
def test_multi_case_section_plot_keeps_dimension_labels_for_all_open_channel_types(
    case_factory,
    expected_labels,
):
    """明渠多工况断面图应继续显示各类尺寸标注。"""
    all_results = [
        (case_idx, params, result)
        for case_idx, (params, result) in enumerate(case_factory())
    ]
    dummy = _PlotAllDummy(all_results)

    open_channel_panel_mod.OpenChannelPanel._update_section_plot_all(dummy)

    assert len(dummy.section_fig.axes) == 2
    for ax in dummy.section_fig.axes:
        labels_text = "\n".join(text.get_text() for text in ax.texts)
        for expected_label in expected_labels:
            assert expected_label in labels_text
        assert "工况" in ax.get_title()
        assert "Q=" in ax.get_title()


def test_multi_case_section_plot_has_no_simplified_fallback_branch():
    """多工况断面图不应再保留只画简图的旧分支。"""
    source = inspect.getsource(open_channel_panel_mod.OpenChannelPanel._update_section_plot_all)

    assert "多工况简单网格" not in source
    assert "ax.text(0.5, 0.5, stype" not in source
    assert "_draw_case_section_plot" in source
