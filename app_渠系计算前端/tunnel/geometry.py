# -*- coding: utf-8 -*-
"""隧洞断面共享几何辅助。"""

import math


HORSESHOE_STD_TYPE_1 = 1
HORSESHOE_STD_TYPE_2 = 2
HORSESHOE_T1 = 3.0
HORSESHOE_THETA1 = 0.294515
HORSESHOE_T2 = 2.0
HORSESHOE_THETA2 = 0.424031
_EPS = 1e-9


def _clamp(value, low, high):
    return max(low, min(high, value))


def dedupe_points(points, tol=_EPS):
    """移除连续重复点，避免生成零长度多段线段。"""
    unique = []
    for point in points:
        if not unique:
            unique.append(point)
            continue
        px, py = unique[-1]
        cx, cy = point
        if abs(px - cx) > tol or abs(py - cy) > tol:
            unique.append(point)
    return unique


def build_arch_geometry(B, H_total, theta_rad):
    """构造圆拱直墙型共享几何。"""
    half_theta = theta_rad / 2.0
    sin_half = math.sin(half_theta)
    R_arch = (B / 2.0) / sin_half if abs(sin_half) > _EPS else B / 2.0
    cos_half = math.cos(half_theta)
    H_arch = R_arch * (1.0 - cos_half)
    H_straight = max(0.0, H_total - H_arch)
    center_y = H_straight - R_arch * cos_half
    theta_deg = math.degrees(theta_rad)
    left_spring = (-B / 2.0, H_straight)
    right_spring = (B / 2.0, H_straight)
    return {
        "B": B,
        "H_total": H_total,
        "theta_rad": theta_rad,
        "theta_deg": theta_deg,
        "R_arch": R_arch,
        "H_arch": H_arch,
        "H_straight": H_straight,
        "center": (0.0, center_y),
        "center_y": center_y,
        "left_spring": left_spring,
        "right_spring": right_spring,
        "start_angle": math.pi / 2.0 - half_theta,
        "end_angle": math.pi / 2.0 + half_theta,
        "start_deg": 90.0 - theta_deg / 2.0,
        "end_deg": 90.0 + theta_deg / 2.0,
    }


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


def build_arch_outline_polyline(geom):
    """圆拱直墙型的非圆弧边界，按左拱脚 -> 左墙底 -> 右墙底 -> 右拱脚输出。"""
    B = geom["B"]
    H_straight = geom["H_straight"]
    points = [
        geom["left_spring"],
        (-B / 2.0, 0.0),
        (B / 2.0, 0.0),
        geom["right_spring"],
    ]
    if H_straight <= _EPS:
        points = [(-B / 2.0, 0.0), (B / 2.0, 0.0)]
    return dedupe_points(points)


def arch_half_width(geom, h):
    """圆拱直墙型指定水深的半宽。"""
    h_clamped = min(max(h, 0.0), geom["H_total"])
    if h_clamped <= 0.0:
        return 0.0
    if h_clamped <= geom["H_straight"] + _EPS:
        return geom["B"] / 2.0
    if h_clamped >= geom["H_total"] - _EPS:
        return 0.0
    dy = h_clamped - geom["center_y"]
    if abs(dy) > geom["R_arch"]:
        return 0.0
    return math.sqrt(max(0.0, geom["R_arch"] ** 2 - dy ** 2))


def build_standard_horseshoe_geometry(section_type, r):
    """构造标准马蹄形的真实圆弧几何。"""
    if section_type == HORSESHOE_STD_TYPE_1:
        t = HORSESHOE_T1
        theta = HORSESHOE_THETA1
        type_name = "标准Ⅰ型"
    elif section_type == HORSESHOE_STD_TYPE_2:
        t = HORSESHOE_T2
        theta = HORSESHOE_THETA2
        type_name = "标准Ⅱ型"
    else:
        raise ValueError("section_type must be 1 or 2")

    theta_deg = math.degrees(theta)
    R_arch = t * r
    e = R_arch * (1.0 - math.cos(theta))
    right_bottom = (R_arch * math.sin(theta), e)
    left_bottom = (-right_bottom[0], right_bottom[1])
    right_top = (r, r)
    left_top = (-r, r)

    arcs = [
        {
            "name": "bottom",
            "center": (0.0, R_arch),
            "radius": R_arch,
            "start_deg": 270.0 - theta_deg,
            "end_deg": 270.0 + theta_deg,
            "start_point": left_bottom,
            "end_point": right_bottom,
        },
        {
            "name": "right_side",
            "center": (-(t - 1.0) * r, r),
            "radius": R_arch,
            "start_deg": 360.0 - theta_deg,
            "end_deg": 360.0,
            "start_point": right_bottom,
            "end_point": right_top,
        },
        {
            "name": "top",
            "center": (0.0, r),
            "radius": r,
            "start_deg": 0.0,
            "end_deg": 180.0,
            "start_point": right_top,
            "end_point": left_top,
        },
        {
            "name": "left_side",
            "center": ((t - 1.0) * r, r),
            "radius": R_arch,
            "start_deg": 180.0,
            "end_deg": 180.0 + theta_deg,
            "start_point": left_top,
            "end_point": left_bottom,
        },
    ]
    return {
        "section_type": section_type,
        "type_name": type_name,
        "r": r,
        "t": t,
        "theta": theta,
        "theta_deg": theta_deg,
        "R_arch": R_arch,
        "e": e,
        "height": 2.0 * r,
        "arcs": arcs,
    }


def standard_horseshoe_half_width(geom, h):
    """标准马蹄形指定水深的半宽。"""
    h_clamped = _clamp(h, 0.0, geom["height"])
    if h_clamped <= 0.0:
        return 0.0
    r = geom["r"]
    t = geom["t"]
    R_arch = geom["R_arch"]
    e = geom["e"]

    if h_clamped <= e + _EPS:
        cos_val = _clamp(1.0 - h_clamped / R_arch, -1.0, 1.0)
        beta = math.acos(cos_val)
        return R_arch * math.sin(beta)
    if h_clamped <= r + _EPS:
        sin_val = _clamp((1.0 - h_clamped / r) / t, -1.0, 1.0)
        alpha = math.asin(sin_val)
        return r * (t * math.cos(alpha) - t + 1.0)
    if h_clamped <= 2.0 * r + _EPS:
        cos_val = _clamp(h_clamped / r - 1.0, -1.0, 1.0)
        phi_half = math.acos(cos_val)
        return r * math.sin(phi_half)
    return 0.0


def sample_arc(arc, samples=60):
    """按给定采样数返回圆弧离散点，供 matplotlib 预览使用。"""
    samples = max(int(samples), 2)
    start_rad = math.radians(arc["start_deg"])
    end_rad = math.radians(arc["end_deg"])
    if end_rad < start_rad:
        end_rad += math.tau
    step = (end_rad - start_rad) / (samples - 1)
    cx, cy = arc["center"]
    radius = arc["radius"]
    points = []
    for idx in range(samples):
        angle = start_rad + step * idx
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points
