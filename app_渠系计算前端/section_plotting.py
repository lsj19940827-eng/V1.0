# -*- coding: utf-8 -*-
"""共享断面图绘制器，统一 Matplotlib 断面图的视觉规则。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from matplotlib.transforms import offset_copy

from app_渠系计算前端.plot_title_utils import apply_flow_velocity_title
from app_渠系计算前端.section_shapes import (
    ArcPath,
    DimensionSpec,
    HorizontalDimension,
    SectionShape,
    TextLabel,
    VerticalDimension,
    WaterState,
)


@dataclass(frozen=True)
class SectionPlotOptions:
    """控制共享断面图的可选显示项。"""

    show_ground_line: bool = True
    show_grid: bool = True
    show_dimensions: bool = True
    closed_top_band: bool = False


def _fmt_m(label: str, value: float) -> str:
    """生成尺寸文字。"""
    return f"{label}={value:.2f}m"


def _draw_arc(ax, arc: ArcPath):
    """绘制圆弧轮廓。"""
    import math

    count = max(int(arc.samples), 8)
    start = arc.start_angle
    end = arc.end_angle
    if end < start:
        end += math.tau
    xs = []
    ys = []
    for idx in range(count):
        angle = start + (end - start) * idx / (count - 1)
        xs.append(arc.center[0] + arc.radius * math.cos(angle))
        ys.append(arc.center[1] + arc.radius * math.sin(angle))
    ax.plot(xs, ys, color=arc.color, linestyle=arc.linestyle, lw=arc.linewidth)


def _draw_horizontal_dimension(ax, dim: HorizontalDimension, text_offset: float):
    """绘制水平尺寸标注。"""
    ax.annotate(
        "",
        xy=(dim.x1, dim.y),
        xytext=(dim.x0, dim.y),
        arrowprops=dict(arrowstyle="<->", color=dim.color, lw=1.5),
    )
    # 水平尺寸文字用固定像素偏移，避免小图中因数据比例过扁而压到箭头。
    text_transform = offset_copy(ax.transData, fig=ax.figure, x=0, y=-6, units="points")
    ax.text(
        (dim.x0 + dim.x1) / 2.0,
        dim.y,
        dim.label,
        ha="center",
        va="top",
        fontsize=9,
        color=dim.color,
        transform=text_transform,
    )


def _draw_vertical_dimension(ax, dim: VerticalDimension, text_offset: float):
    """绘制竖向尺寸标注。"""
    ax.annotate(
        "",
        xy=(dim.x, dim.y1),
        xytext=(dim.x, dim.y0),
        arrowprops=dict(arrowstyle="<->", color=dim.color, lw=1.5),
    )
    if dim.text_side == "left":
        ha = "right"
        x_text = dim.x - text_offset
    else:
        ha = "left"
        x_text = dim.x + text_offset
    ax.text(
        x_text,
        (dim.y0 + dim.y1) / 2.0,
        dim.label,
        fontsize=9,
        color=dim.color,
        rotation=90,
        va="center",
        ha=ha,
    )


def _draw_text_label(ax, text: TextLabel):
    """绘制普通文字标注。"""
    ax.text(
        text.x,
        text.y,
        text.text,
        fontsize=text.fontsize,
        color=text.color,
        rotation=text.rotation,
        ha=text.ha,
        va=text.va,
    )


def draw_section_grid(ax, bounds: tuple[float, float, float, float], style: SectionPlotOptions | None = None):
    """统一设置断面图网格、坐标范围和比例。"""
    options = style or SectionPlotOptions()
    x_min, x_max, y_min, y_max = bounds
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    ax.set_aspect("equal")
    if options.show_grid:
        ax.grid(True, alpha=0.3)
    if options.show_ground_line:
        ax.axhline(y=0, color="brown", lw=3)


def draw_water_state(
    ax,
    shape: SectionShape,
    water_depth: float,
    label: str = "设计水位",
    style: WaterState | None = None,
):
    """绘制水域填充和水面线。"""
    water = style or WaterState(depth=water_depth, label=label)
    if water.depth <= 0:
        return None
    polygon = shape.water_polygon(water.depth)
    if polygon:
        xs = [point[0] for point in polygon]
        ys = [point[1] for point in polygon]
        ax.fill(xs, ys, color="lightblue", alpha=0.7)
    span = shape.water_span(water.depth)
    if span is None:
        return None
    left, right = span
    line = ax.plot(
        [left, right],
        [water.depth, water.depth],
        color=water.color,
        lw=1.5,
        linestyle=water.linestyle,
    )[0]
    return line


def draw_dimension_annotations(
    ax,
    shape: SectionShape,
    water_depth: float,
    options: SectionPlotOptions | None = None,
):
    """统一绘制底宽、总高、水深及断面自定义尺寸标注。"""
    opts = options or SectionPlotOptions()
    if not opts.show_dimensions:
        return
    dims: DimensionSpec = shape.dimensions
    H = max(float(shape.total_height), 1e-9)
    B = max(float(shape.base_width), 1e-9)
    x_min, x_max, y_min, y_max = shape.bounds
    x_span = max(x_max - x_min, B, 1.0)
    y_span = max(y_max - y_min, H, 1.0)
    h_gap = max(y_span * 0.035, 0.04)
    x_gap = max(x_span * 0.025, 0.04)

    if dims.show_width and dims.width_label:
        y = -max(H * 0.08, y_span * 0.04)
        _draw_horizontal_dimension(
            ax,
            HorizontalDimension(-B / 2.0, B / 2.0, y, _fmt_m(dims.width_label, B), color="gray"),
            h_gap,
        )

    if dims.show_height and dims.height_label:
        x = max(B / 2.0, x_max - x_span * 0.18) + x_span * 0.05
        _draw_vertical_dimension(
            ax,
            VerticalDimension(x, 0.0, H, _fmt_m(dims.height_label, H), color="purple"),
            x_gap,
        )

    if dims.show_water_depth and water_depth > 0 and dims.water_label:
        x = x_min + x_span * 0.10
        _draw_vertical_dimension(
            ax,
            VerticalDimension(x, 0.0, water_depth, _fmt_m(dims.water_label, water_depth), color="blue", text_side="left"),
            x_gap,
        )

    for dim in dims.extra_horizontal:
        _draw_horizontal_dimension(ax, dim, h_gap)
    for dim in dims.extra_vertical:
        _draw_vertical_dimension(ax, dim, x_gap)
    for text in dims.extra_texts:
        _draw_text_label(ax, text)


def draw_section(
    ax,
    spec: SectionShape,
    water: WaterState,
    title: str,
    metrics: dict[str, Any] | None = None,
    style: SectionPlotOptions | None = None,
):
    """绘制一个完整断面图。"""
    options = style or SectionPlotOptions()

    for line in spec.lines:
        if not line.points:
            continue
        ax.plot(
            [point[0] for point in line.points],
            [point[1] for point in line.points],
            color=line.color,
            linestyle=line.linestyle,
            lw=line.linewidth,
        )
    for arc in spec.arcs:
        _draw_arc(ax, arc)

    draw_water_state(ax, spec, water.depth, water.label, water)
    if options.closed_top_band:
        B = spec.base_width
        H = spec.total_height
        ax.fill_between([-B / 2.0, B / 2.0], H, H + 0.05 * H, color="gray", alpha=0.4)

    draw_dimension_annotations(ax, spec, water.depth, options)
    draw_section_grid(ax, spec.bounds, options)
    q = water.flow
    v = water.velocity
    if metrics:
        q = metrics.get("Q", metrics.get("flow", q))
        v = metrics.get("V", metrics.get("velocity", v))
    apply_flow_velocity_title(ax, title, q, v, fontsize=10)
