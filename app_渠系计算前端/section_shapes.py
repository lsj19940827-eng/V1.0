# -*- coding: utf-8 -*-
"""共享断面几何适配层，供明渠、渡槽、暗涵和隧洞断面图调用。"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Callable

from app_渠系计算前端.tunnel.geometry import (
    arch_half_width,
    build_arch_geometry,
    build_arch_water_fill_polygon,
    build_flat_bottom_circle_geometry,
    build_standard_horseshoe_geometry,
    flat_bottom_circle_half_width,
    flat_bottom_circle_surface_width,
    standard_horseshoe_half_width,
)


Point = tuple[float, float]
WaterPolygonBuilder = Callable[[float], list[Point]]
WaterSpanBuilder = Callable[[float], tuple[float, float] | None]


@dataclass(frozen=True)
class LinePath:
    """描述一组连续直线段。"""

    points: list[Point]
    linestyle: str = "-"
    color: str = "k"
    linewidth: float = 2.0


@dataclass(frozen=True)
class ArcPath:
    """描述一段圆弧轮廓。"""

    center: Point
    radius: float
    start_angle: float
    end_angle: float
    linestyle: str = "-"
    color: str = "k"
    linewidth: float = 2.0
    samples: int = 80


@dataclass(frozen=True)
class HorizontalDimension:
    """描述水平尺寸标注。"""

    x0: float
    x1: float
    y: float
    label: str
    color: str = "gray"


@dataclass(frozen=True)
class VerticalDimension:
    """描述竖向尺寸标注。"""

    x: float
    y0: float
    y1: float
    label: str
    color: str = "purple"
    text_side: str = "right"


@dataclass(frozen=True)
class TextLabel:
    """描述普通文字标注。"""

    x: float
    y: float
    text: str
    color: str = "gray"
    rotation: float = 0.0
    ha: str = "center"
    va: str = "center"
    fontsize: int = 9


@dataclass(frozen=True)
class DimensionSpec:
    """描述共享绘图器需要显示的尺寸项。"""

    width_label: str = "B"
    height_label: str = "H"
    water_label: str = "h"
    show_width: bool = True
    show_height: bool = True
    show_water_depth: bool = True
    extra_horizontal: list[HorizontalDimension] = field(default_factory=list)
    extra_vertical: list[VerticalDimension] = field(default_factory=list)
    extra_texts: list[TextLabel] = field(default_factory=list)


@dataclass(frozen=True)
class SectionShape:
    """断面图统一绘图所需的几何数据。"""

    kind: str
    name: str
    total_height: float
    base_width: float
    bounds: tuple[float, float, float, float]
    lines: list[LinePath]
    arcs: list[ArcPath]
    water_polygon: WaterPolygonBuilder
    water_span: WaterSpanBuilder
    dimensions: DimensionSpec = field(default_factory=DimensionSpec)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WaterState:
    """单个水位状态。"""

    depth: float
    flow: float = 0.0
    velocity: float = 0.0
    label: str = "设计水位"
    linestyle: str = "-"
    color: str = "b"


def _clamp(value: float, low: float, high: float) -> float:
    """把数值限制在指定范围内。"""
    return max(low, min(high, value))


def _positive(value: Any, default: float = 0.0) -> float:
    """把输入安全转换为非负浮点数。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number if number > 0 else default


def _dedupe(points: list[Point], tol: float = 1e-9) -> list[Point]:
    """去除连续重复点，避免 Matplotlib 生成零长度边。"""
    result: list[Point] = []
    for point in points:
        if not result:
            result.append(point)
            continue
        px, py = result[-1]
        if abs(px - point[0]) > tol or abs(py - point[1]) > tol:
            result.append(point)
    return result


def _sample_arc(center: Point, radius: float, start_angle: float, end_angle: float, samples: int = 80) -> list[Point]:
    """按弧度采样圆弧点。"""
    count = max(int(samples), 8)
    if end_angle < start_angle:
        end_angle += math.tau
    return [
        (
            center[0] + radius * math.cos(start_angle + (end_angle - start_angle) * idx / (count - 1)),
            center[1] + radius * math.sin(start_angle + (end_angle - start_angle) * idx / (count - 1)),
        )
        for idx in range(count)
    ]


def _bounds_from_points(points: list[Point], pad_x: float, pad_y: float) -> tuple[float, float, float, float]:
    """根据点集计算绘图范围。"""
    xs = [point[0] for point in points] or [0.0]
    ys = [point[1] for point in points] or [0.0]
    return min(xs) - pad_x, max(xs) + pad_x, min(ys) - pad_y, max(ys) + pad_y


def build_rectangular_shape(
    width: float,
    height: float,
    *,
    closed: bool = False,
    chamfer_angle: float = 0.0,
    chamfer_length: float = 0.0,
    water_label: str = "h",
) -> SectionShape:
    """构造矩形、封闭矩形或带倒角矩形断面。"""
    B = _positive(width)
    H = _positive(height)
    half = B / 2.0
    angle = _positive(chamfer_angle)
    chamfer = _positive(chamfer_length)
    chamfer_h = chamfer * math.tan(math.radians(angle)) if angle > 0 and chamfer > 0 else 0.0
    has_chamfer = chamfer_h > 0 and chamfer * 2 < B
    top_style = "-" if closed else "--"

    if has_chamfer:
        lines = [
            LinePath([(-half, chamfer_h), (-half, H)]),
            LinePath([(half, chamfer_h), (half, H)]),
            LinePath([(-half + chamfer, 0.0), (half - chamfer, 0.0)]),
            LinePath([(-half, chamfer_h), (-half + chamfer, 0.0)]),
            LinePath([(half - chamfer, 0.0), (half, chamfer_h)]),
            LinePath([(-half, H), (half, H)], linestyle=top_style, linewidth=1.0 if not closed else 2.0),
        ]
    else:
        lines = [
            LinePath([(-half, 0.0), (-half, H)]),
            LinePath([(half, 0.0), (half, H)]),
            LinePath([(-half, 0.0), (half, 0.0)]),
            LinePath([(-half, H), (half, H)], linestyle=top_style, linewidth=1.0 if not closed else 2.0),
        ]

    def water_polygon(depth: float) -> list[Point]:
        h = _clamp(_positive(depth), 0.0, H)
        if h <= 0:
            return []
        if has_chamfer and h <= chamfer_h:
            offset = chamfer * (h / chamfer_h)
            return [(-half + chamfer, 0.0), (half - chamfer, 0.0), (half - offset, h), (-half + offset, h)]
        if has_chamfer:
            return [
                (-half + chamfer, 0.0),
                (half - chamfer, 0.0),
                (half, chamfer_h),
                (half, h),
                (-half, h),
                (-half, chamfer_h),
            ]
        return [(-half, 0.0), (half, 0.0), (half, h), (-half, h)]

    def water_span(depth: float) -> tuple[float, float] | None:
        h = _clamp(_positive(depth), 0.0, H)
        if h <= 0:
            return None
        if has_chamfer and h <= chamfer_h:
            offset = chamfer * (h / chamfer_h)
            return -half + offset, half - offset
        return -half, half

    all_points = [point for line in lines for point in line.points]
    return SectionShape(
        kind="rectangle",
        name="矩形",
        total_height=H,
        base_width=B,
        bounds=_bounds_from_points(all_points, max(B * 0.4, 0.3), max(H * 0.35, 0.25)),
        lines=lines,
        arcs=[],
        water_polygon=water_polygon,
        water_span=water_span,
        dimensions=DimensionSpec(water_label=water_label),
        metadata={"closed": closed, "has_chamfer": has_chamfer, "chamfer_angle": angle, "chamfer_height": chamfer_h},
    )


def build_trapezoid_shape(bottom_width: float, height: float, side_slope: float, *, water_label: str = "h") -> SectionShape:
    """构造梯形或明渠矩形断面。"""
    b = _positive(bottom_width)
    h = _positive(height)
    m = max(float(side_slope or 0.0), 0.0)
    top_width = b + 2.0 * m * h
    lines = [
        LinePath([(-b / 2.0, 0.0), (b / 2.0, 0.0)]),
        LinePath([(-b / 2.0, 0.0), (-top_width / 2.0, h)]),
        LinePath([(b / 2.0, 0.0), (top_width / 2.0, h)]),
        LinePath([(-top_width / 2.0, h), (top_width / 2.0, h)], linestyle="--", linewidth=1.0),
    ]

    def water_polygon(depth: float) -> list[Point]:
        wd = _clamp(_positive(depth), 0.0, h)
        if wd <= 0:
            return []
        water_width = b + 2.0 * m * wd
        return [(-b / 2.0, 0.0), (b / 2.0, 0.0), (water_width / 2.0, wd), (-water_width / 2.0, wd)]

    def water_span(depth: float) -> tuple[float, float] | None:
        wd = _clamp(_positive(depth), 0.0, h)
        if wd <= 0:
            return None
        water_width = b + 2.0 * m * wd
        return -water_width / 2.0, water_width / 2.0

    return SectionShape(
        kind="trapezoid",
        name="梯形",
        total_height=h,
        base_width=b,
        bounds=(-top_width * 0.85, top_width * 0.85, -h * 0.4, h * 1.2),
        lines=lines,
        arcs=[],
        water_polygon=water_polygon,
        water_span=water_span,
        dimensions=DimensionSpec(water_label=water_label),
        metadata={"side_slope": m, "top_width": top_width},
    )


def build_compound_trapezoid_shape(
    B2: float,
    m1: float,
    B1: float,
    m2: float,
    m3: float,
    h1: float,
    height: float,
) -> SectionShape:
    """构造复式梯形明渠断面。"""
    B2 = _positive(B2)
    B1 = _positive(B1)
    h1 = _positive(h1)
    H = _positive(height)
    m1 = max(float(m1 or 0.0), 0.0)
    m2 = max(float(m2 or 0.0), 0.0)
    m3 = max(float(m3 or 0.0), 0.0)
    left_break_x = -(B2 / 2.0 + m2 * h1)
    left_platform_x = left_break_x - B1
    left_top_x = left_platform_x - m1 * max(H - h1, 0.0)
    right_top_x = B2 / 2.0 + m3 * H
    outline = [
        (-B2 / 2.0, 0.0),
        (B2 / 2.0, 0.0),
        (right_top_x, H),
        (left_top_x, H),
        (left_platform_x, h1),
        (left_break_x, h1),
        (-B2 / 2.0, 0.0),
    ]
    width_ref = max(right_top_x - left_top_x, B2, 1.0)

    def water_polygon(depth: float) -> list[Point]:
        h = _clamp(_positive(depth), 0.0, H)
        if h <= 0:
            return []
        if h <= h1:
            left_water = -(B2 / 2.0 + m2 * h)
            right_water = B2 / 2.0 + m3 * h
            return [(-B2 / 2.0, 0.0), (B2 / 2.0, 0.0), (right_water, h), (left_water, h)]
        hs = h - h1
        left_water = left_platform_x - m1 * hs
        right_water = B2 / 2.0 + m3 * h
        return [
            (-B2 / 2.0, 0.0),
            (B2 / 2.0, 0.0),
            (right_water, h),
            (left_water, h),
            (left_platform_x, h1),
            (left_break_x, h1),
        ]

    def water_span(depth: float) -> tuple[float, float] | None:
        points = water_polygon(depth)
        if not points:
            return None
        h = _clamp(_positive(depth), 0.0, H)
        if h <= h1:
            return points[-1][0], points[2][0]
        return points[3][0], points[2][0]

    dim_offset = max(H * 0.12, 0.15)
    dimensions = DimensionSpec(
        width_label="B2",
        water_label="h",
        extra_horizontal=[
            HorizontalDimension(left_platform_x, left_break_x, h1 + dim_offset * 0.6, f"B1={B1:.2f}m"),
        ],
        extra_vertical=[
            VerticalDimension(left_top_x - width_ref * 0.08, 0.0, h1, f"h1={h1:.2f}m", text_side="left"),
        ],
        extra_texts=[
            TextLabel((left_top_x + left_platform_x) / 2.0, h1 + max(H - h1, 0.0) * 0.55, f"1:{m1:g}", color="dimgray"),
            TextLabel((left_break_x - B2 / 2.0) / 2.0, h1 * 0.5, f"1:{m2:g}", color="dimgray"),
            TextLabel((B2 / 2.0 + right_top_x) / 2.0, H * 0.55, f"1:{m3:g}", color="dimgray"),
        ],
    )
    bounds = _bounds_from_points(outline, max(width_ref * 0.25, 0.3), max(H * 0.35, 0.25))
    return SectionShape(
        kind="compound_trapezoid",
        name="复式梯形",
        total_height=H,
        base_width=B2,
        bounds=bounds,
        lines=[LinePath(outline)],
        arcs=[],
        water_polygon=water_polygon,
        water_span=water_span,
        dimensions=dimensions,
        metadata={"B1": B1, "h1": h1, "width_ref": width_ref},
    )


def build_aqueduct_u_shape(radius: float, wall_height: float, total_height: float | None = None) -> SectionShape:
    """构造渡槽 U 形断面。"""
    R = _positive(radius)
    f = _positive(wall_height)
    H = _positive(total_height, R + f)
    half = R
    arc = ArcPath((0.0, R), R, math.pi, math.tau, samples=80)
    lines = [
        LinePath([(-half, R), (-half, H)]),
        LinePath([(half, R), (half, H)]),
        LinePath([(-half, H), (half, H)], linestyle="--", linewidth=1.0),
    ]

    def half_width(depth: float) -> float:
        h = _clamp(_positive(depth), 0.0, H)
        if h <= R:
            return math.sqrt(max(0.0, R * R - (R - h) ** 2))
        return R

    def water_polygon(depth: float) -> list[Point]:
        h = _clamp(_positive(depth), 0.0, H)
        if h <= 0:
            return []
        samples = 80
        ys = [h * idx / (samples - 1) for idx in range(samples)]
        left = [(-half_width(y), y) for y in ys]
        right = [(half_width(y), y) for y in reversed(ys)]
        return _dedupe(left + right)

    def water_span(depth: float) -> tuple[float, float] | None:
        h = _clamp(_positive(depth), 0.0, H)
        if h <= 0:
            return None
        hw = half_width(h)
        return -hw, hw

    return SectionShape(
        kind="aqueduct_u",
        name="U形",
        total_height=H,
        base_width=2.0 * R,
        bounds=(-R * 2.2, R * 2.2, -R * 0.6, H * 1.2),
        lines=lines,
        arcs=[arc],
        water_polygon=water_polygon,
        water_span=water_span,
        dimensions=DimensionSpec(extra_texts=[TextLabel(R * 0.75, R * 0.15, f"R={R:.2f}m", color="green", ha="left")]),
        metadata={"R": R, "wall_height": f},
    )


def build_open_channel_u_shape(radius: float, alpha_deg: float, theta_deg: float, height: float) -> SectionShape:
    """构造明渠 U 形断面。"""
    R = _positive(radius)
    H = _positive(height)
    theta_rad = math.radians(float(theta_deg or 0.0))
    alpha = math.radians(float(alpha_deg or 0.0))
    m = math.tan(alpha)
    half_theta = theta_rad / 2.0
    h0 = R * (1.0 - math.cos(half_theta))
    b_arc = 2.0 * R * math.sin(half_theta)
    x_arc_r = b_arc / 2.0
    x_arc_l = -x_arc_r
    x_top_r = x_arc_r + m * max(H - h0, 0.0)
    x_top_l = -x_top_r
    arc = ArcPath((0.0, R), R, math.pi * 1.5 - half_theta, math.pi * 1.5 + half_theta, samples=80)
    lines = [
        LinePath([(x_arc_r, h0), (x_top_r, H)]),
        LinePath([(x_arc_l, h0), (x_top_l, H)]),
        LinePath([(x_top_l, H), (x_top_r, H)], linestyle="--", linewidth=1.0),
    ]

    def half_width(depth: float) -> float:
        h = _clamp(_positive(depth), 0.0, H)
        if h <= h0:
            return math.sqrt(max(0.0, R * R - (R - h) ** 2))
        return (b_arc + 2.0 * m * (h - h0)) / 2.0

    def water_polygon(depth: float) -> list[Point]:
        h = _clamp(_positive(depth), 0.0, H)
        if h <= 0:
            return []
        if h <= h0:
            angle = math.acos(_clamp((R - h) / R, -1.0, 1.0))
            arc_points = _sample_arc((0.0, R), R, math.pi * 1.5 - angle, math.pi * 1.5 + angle, 50)
            hw = half_width(h)
            return _dedupe([(-hw, h)] + arc_points + [(hw, h)])
        arc_points = _sample_arc((0.0, R), R, math.pi * 1.5 - half_theta, math.pi * 1.5 + half_theta, 80)
        hw = half_width(h)
        return _dedupe(arc_points + [(x_arc_r, h0), (hw, h), (-hw, h), (x_arc_l, h0)])

    def water_span(depth: float) -> tuple[float, float] | None:
        h = _clamp(_positive(depth), 0.0, H)
        if h <= 0:
            return None
        hw = half_width(h)
        return -hw, hw

    max_x = max(abs(x_top_r), R, 1.0)
    return SectionShape(
        kind="open_channel_u",
        name="U形",
        total_height=H,
        base_width=2.0 * R,
        bounds=(-max_x * 1.3, max_x * 1.3, -H * 0.3, H * 1.3),
        lines=lines,
        arcs=[arc],
        water_polygon=water_polygon,
        water_span=water_span,
        dimensions=DimensionSpec(
            show_width=False,
            show_height=False,
            water_label="h",
            extra_texts=[TextLabel(0.0, -H * 0.15, f"R={R:.2f}m, θ={float(theta_deg):.0f}°", color="gray", fontsize=8)],
        ),
        metadata={"R": R, "alpha_deg": alpha_deg, "theta_deg": theta_deg, "h0": h0},
    )


def build_circular_shape(diameter: float, *, water_label: str = "h") -> SectionShape:
    """构造圆形断面。"""
    D = _positive(diameter)
    R = D / 2.0
    arc = ArcPath((0.0, R), R, 0.0, math.tau, samples=120)

    def half_width(depth: float) -> float:
        h = _clamp(_positive(depth), 0.0, D)
        if h <= 0 or h >= D:
            return 0.0
        return math.sqrt(max(0.0, R * R - (h - R) ** 2))

    def water_polygon(depth: float) -> list[Point]:
        h = _clamp(_positive(depth), 0.0, D)
        if h <= 0:
            return []
        if h >= D:
            return _sample_arc((0.0, R), R, 0.0, math.tau, 120)
        samples = 80
        ys = [h * idx / (samples - 1) for idx in range(samples)]
        left = [(-half_width(y), y) for y in ys]
        right = [(half_width(y), y) for y in reversed(ys)]
        return _dedupe(left + right)

    def water_span(depth: float) -> tuple[float, float] | None:
        h = _clamp(_positive(depth), 0.0, D)
        if h <= 0 or h >= D:
            return None
        hw = half_width(h)
        return -hw, hw

    return SectionShape(
        kind="circle",
        name="圆形",
        total_height=D,
        base_width=D,
        bounds=(-R * 1.7, R * 1.7, -R * 0.4, D * 1.2),
        lines=[],
        arcs=[arc],
        water_polygon=water_polygon,
        water_span=water_span,
        dimensions=DimensionSpec(width_label="D", height_label="", water_label=water_label, show_height=False),
        metadata={"D": D, "R": R},
    )


def build_flat_bottom_circle_shape(diameter: float, bottom_width: float) -> SectionShape:
    """构造平底圆形隧洞断面。"""
    D = _positive(diameter)
    B = _positive(bottom_width)
    geom = build_flat_bottom_circle_geometry(D, B)
    arc_info = geom["top_arc"]
    arc = ArcPath(
        arc_info["center"],
        arc_info["radius"],
        math.radians(arc_info["start_deg"]),
        math.radians(arc_info["end_deg"]),
        samples=100,
    )
    H = geom["H_total"]
    lines = [LinePath([geom["bottom_left"], geom["bottom_right"]])]

    def water_polygon(depth: float) -> list[Point]:
        h = _clamp(_positive(depth), 0.0, H)
        if h <= 0:
            return []
        samples = 80
        ys = [h * idx / (samples - 1) for idx in range(samples)]
        left = [(-flat_bottom_circle_half_width(geom, y), y) for y in ys]
        right = [(flat_bottom_circle_half_width(geom, y), y) for y in reversed(ys)]
        return _dedupe(left + right)

    def water_span(depth: float) -> tuple[float, float] | None:
        h = _clamp(_positive(depth), 0.0, H)
        if h <= 0:
            return None
        width = flat_bottom_circle_surface_width(geom, h)
        if width <= 0:
            return None
        return -width / 2.0, width / 2.0

    return SectionShape(
        kind="flat_bottom_circle",
        name="平底圆形",
        total_height=H,
        base_width=B,
        bounds=(-D * 0.95, D * 0.9, -H * 0.42, H * 1.2),
        lines=lines,
        arcs=[arc],
        water_polygon=water_polygon,
        water_span=water_span,
        dimensions=DimensionSpec(
            width_label="B",
            extra_horizontal=[HorizontalDimension(-D / 2.0, D / 2.0, -0.22 * H, f"D={D:.2f}m")],
        ),
        metadata=geom,
    )


def build_arch_wall_shape(width: float, total_height: float, theta_rad: float) -> SectionShape:
    """构造圆拱直墙型断面。"""
    B = _positive(width)
    H = _positive(total_height)
    geom = build_arch_geometry(B, H, theta_rad)
    Hs = geom["H_straight"]
    half = B / 2.0
    lines = [
        LinePath([(-half, 0.0), (-half, Hs)]),
        LinePath([(half, 0.0), (half, Hs)]),
        LinePath([(-half, 0.0), (half, 0.0)]),
    ]
    arc = ArcPath(
        geom["center"],
        geom["R_arch"],
        geom["start_angle"],
        geom["end_angle"],
        samples=101,
    )

    def water_polygon(depth: float) -> list[Point]:
        xs, ys = build_arch_water_fill_polygon(geom, depth)
        return _dedupe(list(zip(xs, ys)))

    def water_span(depth: float) -> tuple[float, float] | None:
        h = _clamp(_positive(depth), 0.0, H)
        if h <= 0:
            return None
        hw = arch_half_width(geom, h)
        if hw <= 0:
            return None
        return -hw, hw

    dimensions = DimensionSpec(
        extra_vertical=[
            VerticalDimension(-half - 0.1 * B, 0.0, Hs, f"H直={Hs:.2f}m", color="darkgreen", text_side="left")
            for _ in [0]
            if Hs > 1e-9
        ],
        extra_texts=[
            TextLabel(0.04 * B, H * 0.98, f"θ={math.degrees(theta_rad):.0f}°", color="purple", ha="left")
        ],
    )
    return SectionShape(
        kind="arch_wall",
        name="圆拱直墙型",
        total_height=H,
        base_width=B,
        bounds=(-B * 1.05, B * 0.9, -H * 0.3, H * 1.2),
        lines=lines,
        arcs=[arc],
        water_polygon=water_polygon,
        water_span=water_span,
        dimensions=dimensions,
        metadata=geom,
    )


def build_standard_horseshoe_shape(section_type: int, radius: float) -> SectionShape:
    """构造标准马蹄形隧洞断面。"""
    r = _positive(radius)
    geom = build_standard_horseshoe_geometry(section_type, r)
    arcs = [
        ArcPath(
            arc["center"],
            arc["radius"],
            math.radians(arc["start_deg"]),
            math.radians(arc["end_deg"]),
            samples=80,
        )
        for arc in geom["arcs"]
    ]

    def water_polygon(depth: float) -> list[Point]:
        h = _clamp(_positive(depth), 0.0, 2.0 * r)
        if h <= 0:
            return []
        samples = 80
        ys = [h * idx / (samples - 1) for idx in range(samples)]
        left = [(-standard_horseshoe_half_width(geom, y), y) for y in ys]
        right = [(standard_horseshoe_half_width(geom, y), y) for y in reversed(ys)]
        return _dedupe(left + right)

    def water_span(depth: float) -> tuple[float, float] | None:
        h = _clamp(_positive(depth), 0.0, 2.0 * r)
        if h <= 0:
            return None
        hw = standard_horseshoe_half_width(geom, h)
        if hw <= 0:
            return None
        return -hw, hw

    return SectionShape(
        kind="standard_horseshoe",
        name=geom["type_name"],
        total_height=2.0 * r,
        base_width=2.0 * r,
        bounds=(-r * 2.2, r * 2.2, -r * 0.3, 2.3 * r),
        lines=[],
        arcs=arcs,
        water_polygon=water_polygon,
        water_span=water_span,
        dimensions=DimensionSpec(
            show_width=False,
            show_height=False,
            extra_texts=[TextLabel(r / 2.0, r + 0.15 * r, f"r={r:.2f}m", color="gray")],
        ),
        metadata=geom,
    )
