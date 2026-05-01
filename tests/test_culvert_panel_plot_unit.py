# -*- coding: utf-8 -*-
"""暗涵断面图绘制回归测试。"""

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

culvert_panel_mod = importlib.import_module("app_渠系计算前端.culvert.panel")


class _PlotDummy:
    """只挂载暗涵断面图所需属性和绘图方法。"""

    _draw_case_section = culvert_panel_mod.CulvertPanel._draw_case_section
    _draw_rect = culvert_panel_mod.CulvertPanel._draw_rect
    _draw_arch = culvert_panel_mod.CulvertPanel._draw_arch

    def __init__(self, all_results=None, input_params=None):
        self.section_fig = Figure()
        self.section_canvas = SimpleNamespace(draw=lambda: None)
        self._all_results = all_results or []
        self.input_params = input_params or {}


def _rect_result(*, h_increased=1.60):
    """构造矩形暗涵结果。"""
    return {
        "success": True,
        "B": 2.40,
        "H": 2.20,
        "h_design": 1.30,
        "V_design": 1.10,
        "Q_increased": 6.00,
        "h_increased": h_increased,
        "V_increased": 1.20,
    }


def _arch_result(*, h_increased=1.75):
    """构造圆拱直墙型暗涵结果。"""
    return {
        "success": True,
        "B": 2.80,
        "H_total": 2.60,
        "theta_deg": 140.0,
        "h_design": 1.35,
        "V_design": 1.15,
        "Q_increased": 8.40,
        "h_increased": h_increased,
        "V_increased": 1.25,
    }


def _increased_level_line_count(ax, expected_y):
    """统计指定高程上的加大水位虚线。"""
    count = 0
    for line in ax.lines:
        y_data = list(line.get_ydata())
        if (
            len(y_data) >= 2
            and all(float(y) == pytest.approx(expected_y) for y in y_data)
            and line.get_linestyle() in {"--", "dashed"}
        ):
            count += 1
    return count


def _has_increased_depth_dimension(ax, expected_y):
    """判断是否存在加大水深竖向尺寸箭头。"""
    for text in ax.texts:
        if text.get_text() != "":
            continue
        arrow_patch = getattr(text, "arrow_patch", None)
        xy = getattr(text, "xy", None)
        xyann = getattr(text, "xyann", None)
        if arrow_patch is None or xy is None or xyann is None:
            continue
        if (
            float(xy[1]) == pytest.approx(expected_y)
            and float(xyann[1]) == pytest.approx(0.0)
            and float(xy[0]) == pytest.approx(float(xyann[0]))
        ):
            return True
    return False


@pytest.mark.parametrize(
    ("params", "result"),
    [
        ({"section_type": "矩形", "Q": 5.0, "use_increase": True}, _rect_result()),
        (
            {"section_type": "圆拱直墙型", "Q": 7.0, "use_increase": True},
            _arch_result(),
        ),
    ],
)
def test_multi_case_section_plot_overlays_increased_waterline(params, result):
    """多工况同图应叠加加大水位线。"""
    dummy = _PlotDummy(
        all_results=[
            (0, params, result),
            (1, params | {"Q": params["Q"] + 1.0}, result),
        ]
    )

    culvert_panel_mod.CulvertPanel._update_section_plot_all(dummy)

    assert len(dummy.section_fig.axes) == 2
    for ax in dummy.section_fig.axes:
        assert _increased_level_line_count(ax, result["h_increased"]) == 1
        labels = "\n".join(text.get_text() for text in ax.texts)
        assert "加大水位" in labels
        assert f"h加大={result['h_increased']:.2f}m" in labels
        assert _has_increased_depth_dimension(ax, result["h_increased"])


@pytest.mark.parametrize(
    ("params", "result"),
    [
        ({"section_type": "矩形", "Q": 5.0, "use_increase": False}, _rect_result()),
        (
            {"section_type": "圆拱直墙型", "Q": 7.0, "use_increase": False},
            _arch_result(),
        ),
        (
            {"section_type": "矩形", "Q": 5.0, "use_increase": True},
            _rect_result(h_increased=0.0),
        ),
        (
            {"section_type": "圆拱直墙型", "Q": 7.0, "use_increase": True},
            _arch_result(h_increased=None),
        ),
    ],
)
def test_multi_case_section_plot_skips_increased_waterline_when_disabled_or_invalid(
    params,
    result,
):
    """未启用加大流量或加大水深无效时不画加大水位线。"""
    dummy = _PlotDummy(
        all_results=[
            (0, params, result),
            (1, params | {"Q": params["Q"] + 1.0}, result),
        ]
    )

    culvert_panel_mod.CulvertPanel._update_section_plot_all(dummy)

    assert len(dummy.section_fig.axes) == 2
    for ax in dummy.section_fig.axes:
        labels = "\n".join(text.get_text() for text in ax.texts)
        assert "h加大" not in labels
        assert not _has_increased_depth_dimension(ax, result.get("h_increased") or 0.0)


@pytest.mark.parametrize(
    ("params", "result"),
    [
        ({"section_type": "矩形", "Q": 5.0, "use_increase": False}, _rect_result()),
        (
            {"section_type": "圆拱直墙型", "Q": 7.0, "use_increase": False},
            _arch_result(),
        ),
    ],
)
def test_single_case_section_plot_hides_increased_subplot_when_increase_disabled(
    params,
    result,
):
    """单工况未勾选加大流量时不显示加大流量图。"""
    dummy = _PlotDummy(input_params=params)

    culvert_panel_mod.CulvertPanel._update_section_plot(dummy, result)

    assert len(dummy.section_fig.axes) == 1
    assert "加大流量" not in dummy.section_fig.axes[0].get_title()


@pytest.mark.parametrize(
    ("params", "result"),
    [
        ({"section_type": "矩形", "Q": 5.0, "use_increase": True}, _rect_result()),
        (
            {"section_type": "圆拱直墙型", "Q": 7.0, "use_increase": True},
            _arch_result(),
        ),
    ],
)
def test_single_case_section_plot_shows_increased_subplot_when_enabled(params, result):
    """单工况启用加大流量时继续显示设计和加大两张图。"""
    dummy = _PlotDummy(input_params=params)

    culvert_panel_mod.CulvertPanel._update_section_plot(dummy, result)

    assert len(dummy.section_fig.axes) == 2
    titles = [ax.get_title() for ax in dummy.section_fig.axes]
    assert any("设计流量" in title for title in titles)
    assert any("加大流量" in title for title in titles)
