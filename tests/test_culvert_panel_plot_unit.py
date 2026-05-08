# -*- coding: utf-8 -*-
"""暗涵断面图绘制回归测试。"""

import importlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from matplotlib.patches import Polygon
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


def _segments_cross(a, b, c, d):
    """判断两条线段是否交叉。"""
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on_segment(p, q, r):
        return (
            min(p[0], r[0]) <= q[0] <= max(p[0], r[0])
            and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])
        )

    o1 = orient(a, b, c)
    o2 = orient(a, b, d)
    o3 = orient(c, d, a)
    o4 = orient(c, d, b)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    eps = 1e-9
    return (
        abs(o1) <= eps and on_segment(a, c, b)
        or abs(o2) <= eps and on_segment(a, d, b)
        or abs(o3) <= eps and on_segment(c, a, d)
        or abs(o4) <= eps and on_segment(c, b, d)
    )


def _polygon_self_intersects(points):
    """判断多边形边界是否自交。"""
    cleaned = []
    for point in points:
        xy = (float(point[0]), float(point[1]))
        if not cleaned or xy != cleaned[-1]:
            cleaned.append(xy)
    if len(cleaned) > 1 and cleaned[0] == cleaned[-1]:
        cleaned.pop()
    count = len(cleaned)
    for i in range(count):
        a = cleaned[i]
        b = cleaned[(i + 1) % count]
        for j in range(i + 1, count):
            if j == i or j == (i + 1) % count or i == (j + 1) % count:
                continue
            c = cleaned[j]
            d = cleaned[(j + 1) % count]
            if _segments_cross(a, b, c, d):
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


def test_arch_water_fill_is_single_non_intersecting_polygon_above_wall():
    """圆拱直墙型水位进入拱部时，水域填充不应自交成三角形。"""
    dummy = _PlotDummy()
    ax = dummy.section_fig.subplots()

    culvert_panel_mod.CulvertPanel._draw_arch(
        dummy,
        ax,
        2.41,
        2.43,
        3.141592653589793,
        1.67,
        1.25,
        5.0,
        "设计流量",
    )

    water_patches = [patch for patch in ax.patches if isinstance(patch, Polygon)]

    assert len(water_patches) == 1
    assert not _polygon_self_intersects(water_patches[0].get_xy())


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
def test_single_case_section_plot_overlays_increased_waterline_when_enabled(params, result):
    """单工况启用加大流量时，应只有一张图并同图叠加加大水位。"""
    dummy = _PlotDummy(input_params=params)

    culvert_panel_mod.CulvertPanel._update_section_plot(dummy, result)

    assert len(dummy.section_fig.axes) == 1
    ax = dummy.section_fig.axes[0]
    assert "设计流量" in ax.get_title()
    assert "加大流量" not in ax.get_title()
    assert _increased_level_line_count(ax, result["h_increased"]) == 1
    labels = "\n".join(text.get_text() for text in ax.texts)
    assert "加大水位" in labels
    assert f"h加大={result['h_increased']:.2f}m" in labels
    assert _has_increased_depth_dimension(ax, result["h_increased"])


@pytest.mark.parametrize(
    ("params", "result"),
    [
        ({"section_type": "暗涵-矩形", "Q": 5.0, "use_increase": True}, _rect_result()),
        ({"section_type": "暗涵-圆拱直墙型", "Q": 7.0, "use_increase": True}, _arch_result()),
    ],
)
def test_single_success_result_plot_all_overlays_increased_waterline(params, result):
    """只有一个成功工况的汇总入口也应显示单图叠加。"""
    dummy = _PlotDummy(all_results=[(0, params, result)])

    culvert_panel_mod.CulvertPanel._update_section_plot_all(dummy)

    assert len(dummy.section_fig.axes) == 1
    ax = dummy.section_fig.axes[0]
    assert _increased_level_line_count(ax, result["h_increased"]) == 1
    labels = "\n".join(text.get_text() for text in ax.texts)
    assert "加大水位" in labels
    assert f"h加大={result['h_increased']:.2f}m" in labels
