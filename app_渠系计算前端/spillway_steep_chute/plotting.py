# -*- coding: utf-8 -*-
"""泄水渠与陡坡纵断面图绘制，只负责 matplotlib 图形。"""

from typing import Any

from matplotlib import rcParams
from matplotlib.figure import Figure

from app_渠系计算前端.matplotlib_text_layout import apply_single_axis_text_safe_layout

from .models import normalize_result

rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS", "DejaVu Sans"]
rcParams["axes.unicode_minus"] = False


def _float_or_none(value: Any) -> float | None:
    """把表格值安全转换为浮点数。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    """按顺序读取第一个存在且非空的字段，保留 0 值。"""
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def draw_longitudinal_profile(fig: Figure, result: Any) -> Figure:
    """在给定 Figure 上绘制渠底线、水面线、掺气水面线和侧墙顶线。"""
    fig.clear()
    ax = fig.add_subplot(111)
    view_data = normalize_result(result)
    points = view_data.profile_points

    xs: list[float] = []
    bed: list[float] = []
    water: list[float] = []
    aerated_xs: list[float] = []
    aerated: list[float] = []
    wall_xs: list[float] = []
    wall: list[float] = []
    for point in points:
        x = _float_or_none(_first_present(point, "x", "distance_m", "distance", "L"))
        bed_elevation = _float_or_none(
            _first_present(point, "bed_elevation", "bed_elevation_m", "渠底高程", "z_bed")
        )
        water_elevation = _float_or_none(
            _first_present(point, "water_elevation", "water_elevation_m", "水面高程", "z_water")
        )
        aerated_elevation = _float_or_none(
            _first_present(point, "aerated_water_elevation_m", "掺气水位", "z_aerated")
        )
        aerated_depth = _float_or_none(_first_present(point, "aerated_depth_m", "掺气水深"))
        wall_elevation = _float_or_none(
            _first_present(point, "sidewall_top_elevation_m", "侧墙顶高程", "z_wall")
        )
        if x is None or bed_elevation is None or water_elevation is None:
            continue
        xs.append(x)
        bed.append(bed_elevation)
        water.append(water_elevation)
        if aerated_elevation is None and aerated_depth is not None:
            aerated_elevation = bed_elevation + aerated_depth
        if aerated_elevation is not None:
            aerated_xs.append(x)
            aerated.append(aerated_elevation)
        if wall_elevation is not None:
            wall_xs.append(x)
            wall.append(wall_elevation)

    if xs:
        ax.plot(xs, bed, color="#7a4f2a", linewidth=2.0, label="渠底线")
        ax.plot(xs, water, color="#1f77b4", linewidth=2.0, label="水面线")
        if aerated_xs:
            ax.plot(aerated_xs, aerated, color="#00a6d6", linewidth=1.8, linestyle="--", label="掺气水面线")
        if wall_xs:
            ax.plot(wall_xs, wall, color="#d1495b", linewidth=1.8, linestyle="-.", label="侧墙顶线")
    else:
        ax.text(0.5, 0.5, "暂无沿程水面线数据", ha="center", va="center", transform=ax.transAxes)

    ax.set_title("泄水渠与陡坡纵断面图")
    ax.set_xlabel("沿程距离（米）")
    ax.set_ylabel("高程（米）")
    ax.grid(True, linestyle="--", alpha=0.35)
    if xs:
        ax.margins(x=0.02, y=0.08)
        ax.legend(loc="best")
    apply_single_axis_text_safe_layout(
        fig,
        ax,
        base_margins={"left": 0.10, "right": 0.94, "top": 0.88, "bottom": 0.14},
        padding_px=8.0,
    )
    return fig


def create_longitudinal_profile_figure(result: Any) -> Figure:
    """创建并返回纵断面图 Figure。"""
    fig = Figure(figsize=(7.0, 4.2), dpi=100)
    return draw_longitudinal_profile(fig, result)
