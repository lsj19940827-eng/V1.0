# -*- coding: utf-8 -*-
"""共享断面图绘制底座的单元测试。"""

from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Polygon
from matplotlib.text import Annotation
import pytest

from app_渠系计算前端.section_plotting import draw_section
from app_渠系计算前端.section_shapes import (
    WaterState,
    build_arch_wall_shape,
    build_aqueduct_u_shape,
    build_rectangular_shape,
    build_trapezoid_shape,
)


def _ccw(a, b, c):
    """判断三个点的方向。"""
    return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(a, b, c, d):
    """判断两条线段是否相交。"""
    return _ccw(a, c, d) != _ccw(b, c, d) and _ccw(a, b, c) != _ccw(a, b, d)


def _polygon_self_intersects(points):
    """判断多边形是否存在自交。"""
    clean = [tuple(point) for point in points]
    if len(clean) > 1 and clean[0] == clean[-1]:
        clean = clean[:-1]
    for idx, a in enumerate(clean):
        b = clean[(idx + 1) % len(clean)]
        for jdx in range(idx + 1, len(clean)):
            if abs(idx - jdx) <= 1 or {idx, jdx} == {0, len(clean) - 1}:
                continue
            c = clean[jdx]
            d = clean[(jdx + 1) % len(clean)]
            if _segments_intersect(a, b, c, d):
                return True
    return False


def _render_short_axis_section(shape, water_depth):
    """按并排小图比例渲染断面图，返回画布和坐标轴。"""
    fig = Figure(figsize=(12, 2.6), dpi=100)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(121)
    draw_section(ax, shape, WaterState(depth=water_depth, flow=5.0, velocity=1.2), "设计流量")
    fig.tight_layout()
    fig.canvas.draw()
    return fig.canvas, ax


def _horizontal_dimension_arrow_y_pixels(ax):
    """提取水平尺寸箭头所在的屏幕纵坐标。"""
    pixels = []
    for text in ax.texts:
        if text.get_text() != "" or not isinstance(text, Annotation):
            continue
        xy = getattr(text, "xy", None)
        xyann = getattr(text, "xyann", None)
        if xy is None or xyann is None:
            continue
        if abs(xy[1] - xyann[1]) < 1e-9:
            pixels.append(ax.transData.transform((0, xy[1]))[1])
    return pixels


def _dimension_label_gap_pixels(canvas, ax, label_prefix):
    """计算水平尺寸文字顶部与最近水平箭头之间的像素间距。"""
    renderer = canvas.get_renderer()
    labels = [text for text in ax.texts if text.get_text().startswith(label_prefix)]
    assert len(labels) == 1
    arrow_y_pixels = _horizontal_dimension_arrow_y_pixels(ax)
    assert arrow_y_pixels

    bbox = labels[0].get_window_extent(renderer=renderer)
    return min(arrow_y - bbox.y1 for arrow_y in arrow_y_pixels)


def test_draw_section_renders_rectangle_water_and_dimensions():
    """共享绘图器应能绘制矩形轮廓、水域和尺寸文字。"""
    fig = Figure()
    ax = fig.subplots()
    shape = build_rectangular_shape(3.0, 2.0, closed=True)

    draw_section(ax, shape, WaterState(depth=1.2, flow=5.0, velocity=1.1), "设计流量")

    water_patches = [patch for patch in ax.patches if isinstance(patch, Polygon)]
    labels = "\n".join(text.get_text() for text in ax.texts)

    assert len(water_patches) == 1
    assert "B=3.00m" in labels
    assert "H=2.00m" in labels
    assert "h=1.20m" in labels
    assert any(abs(line.get_ydata()[0] - 1.2) < 1e-9 for line in ax.lines)


def test_trapezoid_water_span_matches_side_slope():
    """梯形断面的水面宽度应由共享几何统一计算。"""
    shape = build_trapezoid_shape(bottom_width=2.0, height=3.0, side_slope=0.5)

    left, right = shape.water_span(1.6)

    assert left == pytest.approx(-1.8)
    assert right == pytest.approx(1.8)


def test_arch_wall_water_fill_is_single_non_intersecting_polygon():
    """圆拱直墙型水位进入拱部时，共享水域多边形不能自交。"""
    fig = Figure()
    ax = fig.subplots()
    shape = build_arch_wall_shape(2.41, 2.43, math.radians(180.0))

    draw_section(ax, shape, WaterState(depth=1.67, flow=5.0, velocity=1.25), "设计流量")

    water_patches = [patch for patch in ax.patches if isinstance(patch, Polygon)]

    assert len(water_patches) == 1
    assert not _polygon_self_intersects(water_patches[0].get_xy())


@pytest.mark.parametrize(
    ("shape", "water_depth", "label_prefix"),
    [
        (build_trapezoid_shape(1.30, 2.34, 1.0), 1.57, "B="),
        (build_aqueduct_u_shape(1.38, 0.85, 2.23), 1.87, "B="),
        (build_arch_wall_shape(3.60, 3.85, math.radians(180.0)), 2.53, "B="),
        (build_rectangular_shape(2.33, 2.38, closed=True), 1.71, "B="),
    ],
)
def test_horizontal_dimension_label_keeps_pixel_gap_from_arrow(shape, water_depth, label_prefix):
    """水平尺寸文字应与尺寸箭头保持像素留白，避免小图里重叠。"""
    canvas, ax = _render_short_axis_section(shape, water_depth)

    gap_pixels = _dimension_label_gap_pixels(canvas, ax, label_prefix)

    assert gap_pixels >= 4.0
