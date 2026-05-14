# -*- coding: utf-8 -*-
"""泄水渠与陡坡纵断面图中文化和第二版线型测试。"""

import sys
from pathlib import Path

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端.spillway_steep_chute.plotting import draw_longitudinal_profile


def _profile_result():
    """生成典型泄水渠纵断面图测试数据。"""
    return {
        "profile_points": [
            {
                "distance_m": 0.0,
                "bed_elevation_m": 100.0,
                "water_elevation_m": 101.8,
                "aerated_water_elevation_m": 102.0,
                "sidewall_top_elevation_m": 102.2,
            },
            {
                "distance_m": 80.0,
                "bed_elevation_m": 98.4,
                "water_elevation_m": 99.6,
                "aerated_water_elevation_m": 99.8,
                "sidewall_top_elevation_m": 100.1,
            },
        ]
    }


def _visible_text_artists(ax):
    """收集纵断面图上需要防裁切的可见文字对象。"""
    artists = [ax.title, ax.xaxis.label, ax.yaxis.label]
    artists.extend(label for label in ax.get_xticklabels() if label.get_visible())
    artists.extend(label for label in ax.get_yticklabels() if label.get_visible())
    legend = ax.get_legend()
    if legend is not None:
        artists.extend(text for text in legend.get_texts() if text.get_visible())
    return artists


def _assert_text_inside_canvas(fig: Figure, *, min_padding_px: float = 2.0) -> None:
    """断言标题、坐标轴、刻度和图例文字完整位于画布内。"""
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    renderer = canvas.get_renderer()
    width, height = fig.bbox.width, fig.bbox.height
    for artist in _visible_text_artists(fig.axes[0]):
        bounds = artist.get_window_extent(renderer=renderer)
        assert bounds.x0 >= min_padding_px
        assert bounds.y0 >= min_padding_px
        assert bounds.x1 <= width - min_padding_px
        assert bounds.y1 <= height - min_padding_px


def test_longitudinal_profile_uses_chinese_labels_and_v2_lines():
    """纵断面图应使用中文标题、坐标和图例，并显示掺气水面线与侧墙顶线。"""
    fig = Figure()
    draw_longitudinal_profile(fig, _profile_result())

    ax = fig.axes[0]
    legend_labels = [item.get_text() for item in ax.get_legend().texts]
    line_xs = [list(line.get_xdata()) for line in ax.lines]
    assert ax.get_title() == "泄水渠与陡坡纵断面图"
    assert ax.get_xlabel() == "沿程距离（米）"
    assert ax.get_ylabel() == "高程（米）"
    assert legend_labels == ["渠底线", "水面线", "掺气水面线", "侧墙顶线"]
    assert line_xs[0] == [0.0, 80.0]


def test_longitudinal_profile_keeps_text_inside_narrow_and_normal_canvas():
    """纵断面图应按文字真实边界留白，窄窗口和正常窗口都不裁切文字。"""
    for width_px in (520, 900):
        fig = Figure(figsize=(width_px / 100, 6.0), dpi=100)
        draw_longitudinal_profile(fig, _profile_result())

        _assert_text_inside_canvas(fig)


def test_longitudinal_profile_empty_state_keeps_text_inside_canvas():
    """无沿程数据时，空状态提示和坐标轴文字也不应被裁切。"""
    fig = Figure(figsize=(520 / 100, 6.0), dpi=100)
    draw_longitudinal_profile(fig, {"profile_points": []})

    _assert_text_inside_canvas(fig)
