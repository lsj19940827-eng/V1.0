# -*- coding: utf-8 -*-
"""平底圆形纯几何真源；计算、表3和断面绘图共同使用。"""

import math

_EPS = 1e-9


def _clamp(value, low, high):
    """保持几何反三角函数和水深的原有截断范围。"""
    return max(low, min(high, value))


def _circular_segment_area(diameter, depth):
    """按完整圆计算从最低点起的弓形面积。"""
    if diameter <= 0 or depth <= 0:
        return 0.0
    radius = diameter / 2.0
    depth = _clamp(depth, 0.0, diameter)
    if depth >= diameter - _EPS:
        return math.pi * radius * radius
    theta = 2.0 * math.acos(_clamp((radius - depth) / radius, -1.0, 1.0))
    return radius * radius * (theta - math.sin(theta)) / 2.0


def build_flat_bottom_circle_geometry(D, B):
    """构造平底圆形共享几何。"""
    if D <= 0:
        raise ValueError("平底圆形直径 D 必须大于 0")
    if B <= 0:
        raise ValueError("平底圆形底宽 B 必须大于 0")
    if B > D + _EPS:
        raise ValueError("平底圆形底宽 B 不能大于直径 D")

    radius = D / 2.0
    half_bottom = B / 2.0
    center_y = math.sqrt(max(radius * radius - half_bottom * half_bottom, 0.0))
    cut_height = radius - center_y
    H_total = radius + center_y
    cut_theta = 2.0 * math.asin(_clamp(B / D, -1.0, 1.0))
    cut_area = radius * radius * (cut_theta - math.sin(cut_theta)) / 2.0
    A_total = math.pi * radius * radius - cut_area
    bottom_angle_deg = math.degrees(math.asin(_clamp(center_y / radius, -1.0, 1.0)))
    start_deg = 360.0 - bottom_angle_deg
    end_deg = 180.0 + bottom_angle_deg
    major_arc_angle_deg = (end_deg - start_deg) % 360.0
    if major_arc_angle_deg <= 0:
        major_arc_angle_deg += 360.0

    top_arc = {
        "name": "top_arc",
        "center": (0.0, center_y),
        "radius": radius,
        "start_deg": start_deg,
        "end_deg": end_deg,
        "start_point": (half_bottom, 0.0),
        "end_point": (-half_bottom, 0.0),
    }
    return {
        "D": D,
        "B": B,
        "radius": radius,
        "center": (0.0, center_y),
        "center_y": center_y,
        "cut_height": cut_height,
        "H_total": H_total,
        "A_total": A_total,
        "cut_theta_rad": cut_theta,
        "cut_theta_deg": math.degrees(cut_theta),
        "major_arc_angle_deg": major_arc_angle_deg,
        "major_arc_angle_rad": math.radians(major_arc_angle_deg),
        "bottom_left": (-half_bottom, 0.0),
        "bottom_right": (half_bottom, 0.0),
        "top_arc": top_arc,
    }


def flat_bottom_circle_full_depth(geom, h):
    """将平底圆形水深换算为完整圆从最低点起的深度。"""
    h_clamped = _clamp(h, 0.0, geom["H_total"])
    return geom["cut_height"] + h_clamped


def flat_bottom_circle_area(geom, h):
    """计算平底圆形指定水深的过水面积。"""
    h_clamped = _clamp(h, 0.0, geom["H_total"])
    if h_clamped <= 0.0:
        return 0.0
    full_depth = flat_bottom_circle_full_depth(geom, h_clamped)
    return _circular_segment_area(geom["D"], full_depth) - _circular_segment_area(geom["D"], geom["cut_height"])


def flat_bottom_circle_perimeter(geom, h):
    """计算平底圆形指定水深的湿周。"""
    h_clamped = _clamp(h, 0.0, geom["H_total"])
    if h_clamped <= 0.0:
        return 0.0
    radius = geom["radius"]
    center_y = geom["center_y"]
    start_angle = -math.asin(_clamp(center_y / radius, -1.0, 1.0))
    water_angle = math.asin(_clamp((h_clamped - center_y) / radius, -1.0, 1.0))
    return geom["B"] + 2.0 * radius * (water_angle - start_angle)


def flat_bottom_circle_half_width(geom, h):
    """计算平底圆形指定水深处的半宽。"""
    h_clamped = _clamp(h, 0.0, geom["H_total"])
    if h_clamped <= _EPS:
        return 0.0
    if h_clamped >= geom["H_total"] - _EPS:
        return 0.0
    radius = geom["radius"]
    return math.sqrt(max(0.0, radius * radius - (h_clamped - geom["center_y"]) ** 2))


def flat_bottom_circle_surface_width(geom, h):
    """计算平底圆形指定水深的水面宽度。"""
    h_clamped = _clamp(h, 0.0, geom["H_total"])
    if h_clamped <= _EPS or h_clamped >= geom["H_total"] - _EPS:
        return 0.0
    return 2.0 * flat_bottom_circle_half_width(geom, h_clamped)


