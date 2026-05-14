# -*- coding: utf-8 -*-
"""Matplotlib 图形文字安全布局工具，供需要防止中文标签裁切的图形复用。"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from matplotlib.backends.backend_agg import FigureCanvasAgg


def _get_canvas(fig):
    """获取可用于测量文字边界的画布，没有绑定画布时创建 Agg 画布。"""
    canvas = getattr(fig, "canvas", None)
    if canvas is None or not callable(getattr(canvas, "get_renderer", None)):
        canvas = FigureCanvasAgg(fig)
    return canvas


def _safe_draw(canvas) -> bool:
    """执行一次绘制，用于让 Matplotlib 计算文字真实边界。"""
    draw = getattr(canvas, "draw", None)
    if not callable(draw):
        return False
    try:
        draw()
    except Exception:
        return False
    return True


def _artist_visible(artist: Any) -> bool:
    """判断文字或图例对象是否可见。"""
    visible = getattr(artist, "get_visible", None)
    if callable(visible):
        try:
            return bool(visible())
        except Exception:
            return False
    return True


def _valid_bbox(bbox) -> bool:
    """判断边界框是否可用于布局计算。"""
    try:
        values = (bbox.x0, bbox.y0, bbox.x1, bbox.y1)
    except Exception:
        return False
    return all(math.isfinite(float(value)) for value in values)


def _iter_axis_text_artists(ax) -> Iterable[Any]:
    """遍历单坐标轴图中需要防裁切的文字和图例对象。"""
    for artist in (getattr(ax, "title", None), getattr(ax.xaxis, "label", None), getattr(ax.yaxis, "label", None)):
        if artist is not None:
            yield artist
    for label in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
        yield label
    for offset_text in (ax.xaxis.get_offset_text(), ax.yaxis.get_offset_text()):
        yield offset_text
    for text in getattr(ax, "texts", []):
        yield text
    legend = ax.get_legend()
    if legend is not None:
        yield legend
        for text in legend.get_texts():
            yield text


def _visible_bboxes(fig, ax, renderer) -> list[Any]:
    """收集当前图中所有可见文字对象的边界框。"""
    bboxes = []
    for artist in _iter_axis_text_artists(ax):
        if artist is None or not _artist_visible(artist):
            continue
        try:
            bbox = artist.get_window_extent(renderer=renderer)
        except Exception:
            continue
        if _valid_bbox(bbox):
            bboxes.append(bbox)
    return bboxes


def apply_single_axis_text_safe_layout(
    fig,
    ax=None,
    *,
    base_margins: dict[str, float] | None = None,
    padding_px: float = 8.0,
    max_iterations: int = 4,
    min_axis_width_fraction: float = 0.35,
    min_axis_height_fraction: float = 0.35,
) -> None:
    """按真实文字边界自动调整单坐标轴图边距，避免标题、刻度和图例被裁切。"""
    axes = list(getattr(fig, "axes", []))
    if ax is None:
        if not axes:
            return
        ax = axes[0]

    if base_margins:
        try:
            fig.subplots_adjust(**base_margins)
        except Exception:
            pass

    canvas = _get_canvas(fig)
    for _ in range(max(1, int(max_iterations))):
        if not _safe_draw(canvas):
            return
        renderer = getattr(canvas, "get_renderer", lambda: None)()
        if renderer is None:
            return

        width_px = float(getattr(fig.bbox, "width", 0.0) or 0.0)
        height_px = float(getattr(fig.bbox, "height", 0.0) or 0.0)
        if width_px <= 0 or height_px <= 0:
            return

        params = fig.subplotpars
        left = float(params.left)
        right = float(params.right)
        bottom = float(params.bottom)
        top = float(params.top)

        changed = False
        for bbox in _visible_bboxes(fig, ax, renderer):
            if bbox.x0 < padding_px:
                left += (padding_px - float(bbox.x0)) / width_px
                changed = True
            if bbox.x1 > width_px - padding_px:
                right -= (float(bbox.x1) - (width_px - padding_px)) / width_px
                changed = True
            if bbox.y0 < padding_px:
                bottom += (padding_px - float(bbox.y0)) / height_px
                changed = True
            if bbox.y1 > height_px - padding_px:
                top -= (float(bbox.y1) - (height_px - padding_px)) / height_px
                changed = True

        if not changed:
            return

        min_width = max(float(min_axis_width_fraction), 0.05)
        min_height = max(float(min_axis_height_fraction), 0.05)
        left = max(0.01, min(left, 0.98 - min_width))
        right = min(0.99, max(right, left + min_width))
        bottom = max(0.01, min(bottom, 0.98 - min_height))
        top = min(0.99, max(top, bottom + min_height))

        try:
            fig.subplots_adjust(left=left, right=right, bottom=bottom, top=top)
        except Exception:
            return
