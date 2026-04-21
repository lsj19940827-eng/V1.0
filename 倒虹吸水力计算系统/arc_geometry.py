# -*- coding: utf-8 -*-
"""倒虹吸圆弧几何工具，统一构建、复制和采样圆弧真源。"""

import math
from typing import Iterable, Optional, Tuple


def _to_float(value, default: float = 0.0) -> float:
    """把输入安全转成浮点数。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_point(point) -> Optional[Tuple[float, float]]:
    """把点统一成二维浮点坐标。"""
    if point is None:
        return None
    if isinstance(point, dict):
        if "x" in point and "y" in point:
            return (_to_float(point.get("x")), _to_float(point.get("y")))
        return None
    try:
        x, y = point
    except (TypeError, ValueError):
        return None
    return (_to_float(x), _to_float(y))


def _normalize_bool(value) -> bool:
    """统一布尔值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _unit_vector(dx: float, dy: float) -> Optional[Tuple[float, float]]:
    """计算单位向量。"""
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return None
    return (dx / length, dy / length)


def _positive_angle(angle_rad: float) -> float:
    """把角度归一化到 [0, 2π)。"""
    while angle_rad < 0.0:
        angle_rad += 2.0 * math.pi
    while angle_rad >= 2.0 * math.pi:
        angle_rad -= 2.0 * math.pi
    return angle_rad


def clone_arc_geometry(arc_geometry):
    """复制圆弧真源字典，避免原地串改。"""
    if not isinstance(arc_geometry, dict):
        return None
    start = _normalize_point(arc_geometry.get("start"))
    end = _normalize_point(arc_geometry.get("end"))
    center = _normalize_point(arc_geometry.get("center"))
    if start is None or end is None or center is None:
        return None
    return {
        "kind": str(arc_geometry.get("kind", "") or ""),
        "mode": str(arc_geometry.get("mode", "") or ""),
        "start": [start[0], start[1]],
        "end": [end[0], end[1]],
        "center": [center[0], center[1]],
        "radius": _to_float(arc_geometry.get("radius")),
        "sweep_rad": _to_float(arc_geometry.get("sweep_rad")),
        "clockwise": _normalize_bool(arc_geometry.get("clockwise", False)),
        "start_chainage": _to_float(arc_geometry.get("start_chainage")),
        "end_chainage": _to_float(arc_geometry.get("end_chainage")),
    }


def build_arc_geometry(
    *,
    kind: str,
    mode: str,
    start,
    end,
    center,
    radius: float,
    sweep_rad: float,
    clockwise: bool,
    start_chainage: float,
    end_chainage: float,
):
    """构建统一格式的圆弧真源字典。"""
    start_pt = _normalize_point(start)
    end_pt = _normalize_point(end)
    center_pt = _normalize_point(center)
    radius_val = _to_float(radius)
    sweep_val = abs(_to_float(sweep_rad))
    if start_pt is None or end_pt is None or center_pt is None:
        return None
    if radius_val <= 0 or sweep_val <= 0:
        return None
    return {
        "kind": str(kind or ""),
        "mode": str(mode or ""),
        "start": [start_pt[0], start_pt[1]],
        "end": [end_pt[0], end_pt[1]],
        "center": [center_pt[0], center_pt[1]],
        "radius": radius_val,
        "sweep_rad": sweep_val,
        "clockwise": bool(clockwise),
        "start_chainage": _to_float(start_chainage),
        "end_chainage": _to_float(end_chainage),
    }


def infer_arc_clockwise(start, end, center, sweep_rad: float) -> bool:
    """根据首尾点和圆心推断圆弧方向。"""
    start_pt = _normalize_point(start)
    end_pt = _normalize_point(end)
    center_pt = _normalize_point(center)
    if start_pt is None or end_pt is None or center_pt is None:
        return False
    theta_start = math.atan2(start_pt[1] - center_pt[1], start_pt[0] - center_pt[0])
    theta_end = math.atan2(end_pt[1] - center_pt[1], end_pt[0] - center_pt[0])
    sweep_val = abs(_to_float(sweep_rad))
    ccw_delta = _positive_angle(theta_end - theta_start)
    cw_delta = _positive_angle(theta_start - theta_end)
    return abs(cw_delta - sweep_val) < abs(ccw_delta - sweep_val)


def build_plan_arc_geometry_from_context(
    *,
    start,
    end,
    radius: float,
    sweep_rad: float,
    start_chainage: float,
    end_chainage: float,
    prev_point=None,
    next_point=None,
    mode: str = "manual_rebuilt",
):
    """按首尾点、半径和上下文方向重建平面圆弧真源。"""
    start_pt = _normalize_point(start)
    end_pt = _normalize_point(end)
    if start_pt is None or end_pt is None:
        return None
    radius_val = _to_float(radius)
    sweep_val = abs(_to_float(sweep_rad))
    chord_dx = end_pt[0] - start_pt[0]
    chord_dy = end_pt[1] - start_pt[1]
    chord = math.hypot(chord_dx, chord_dy)
    if radius_val <= 0 or sweep_val <= 0 or chord <= 1e-9:
        return None
    half_chord = chord / 2.0
    if radius_val + 1e-9 < half_chord:
        return None

    chord_dir = _unit_vector(chord_dx, chord_dy)
    if chord_dir is None:
        return None
    normal = (-chord_dir[1], chord_dir[0])
    midpoint = ((start_pt[0] + end_pt[0]) / 2.0, (start_pt[1] + end_pt[1]) / 2.0)
    center_offset = math.sqrt(max(0.0, radius_val * radius_val - half_chord * half_chord))

    prev_dir = None
    prev_pt = _normalize_point(prev_point)
    if prev_pt is not None:
        prev_dir = _unit_vector(start_pt[0] - prev_pt[0], start_pt[1] - prev_pt[1])

    next_dir = None
    next_pt = _normalize_point(next_point)
    if next_pt is not None:
        next_dir = _unit_vector(next_pt[0] - end_pt[0], next_pt[1] - end_pt[1])

    best = None
    best_score = float("inf")
    for sign in (1.0, -1.0):
        center = (
            midpoint[0] + sign * center_offset * normal[0],
            midpoint[1] + sign * center_offset * normal[1],
        )
        theta_start = math.atan2(start_pt[1] - center[1], start_pt[0] - center[0])
        theta_end = math.atan2(end_pt[1] - center[1], end_pt[0] - center[0])
        for clockwise in (False, True):
            if clockwise:
                delta = _positive_angle(theta_start - theta_end)
                tangent_start = (math.sin(theta_start), -math.cos(theta_start))
                tangent_end = (math.sin(theta_end), -math.cos(theta_end))
            else:
                delta = _positive_angle(theta_end - theta_start)
                tangent_start = (-math.sin(theta_start), math.cos(theta_start))
                tangent_end = (-math.sin(theta_end), math.cos(theta_end))

            score = abs(delta - sweep_val)
            if prev_dir is not None:
                dot_start = max(-1.0, min(1.0, prev_dir[0] * tangent_start[0] + prev_dir[1] * tangent_start[1]))
                score += 0.5 * (1.0 - dot_start)
            if next_dir is not None:
                dot_end = max(-1.0, min(1.0, next_dir[0] * tangent_end[0] + next_dir[1] * tangent_end[1]))
                score += 0.5 * (1.0 - dot_end)

            if score < best_score:
                best_score = score
                best = (center, clockwise)

    if best is None:
        return None

    return build_arc_geometry(
        kind="plan",
        mode=mode,
        start=start_pt,
        end=end_pt,
        center=best[0],
        radius=radius_val,
        sweep_rad=sweep_val,
        clockwise=best[1],
        start_chainage=start_chainage,
        end_chainage=end_chainage,
    )


def build_profile_arc_geometry_from_context(
    *,
    start,
    end,
    radius: float,
    sweep_rad: float,
    start_chainage: float,
    end_chainage: float,
    slope_before_rad,
    slope_after_rad,
    mode: str = "manual_rebuilt",
):
    """按前后切线坡角重建纵断面圆弧真源。"""
    start_pt = _normalize_point(start)
    end_pt = _normalize_point(end)
    radius_val = _to_float(radius)
    sweep_val = abs(_to_float(sweep_rad))
    beta_before = _to_float(slope_before_rad)
    beta_after = _to_float(slope_after_rad)
    if start_pt is None or end_pt is None:
        return None
    if radius_val <= 0 or sweep_val <= 0:
        return None

    tangent_start = _unit_vector(math.cos(beta_before), math.sin(beta_before))
    tangent_end = _unit_vector(math.cos(beta_after), math.sin(beta_after))
    if tangent_start is None or tangent_end is None:
        return None

    left_normal_start = (-tangent_start[1], tangent_start[0])
    left_normal_end = (-tangent_end[1], tangent_end[0])

    best = None
    best_score = float("inf")
    best_mismatch = float("inf")
    for sign_start in (1.0, -1.0):
        center_start = (
            start_pt[0] + sign_start * radius_val * left_normal_start[0],
            start_pt[1] + sign_start * radius_val * left_normal_start[1],
        )
        for sign_end in (1.0, -1.0):
            center_end = (
                end_pt[0] + sign_end * radius_val * left_normal_end[0],
                end_pt[1] + sign_end * radius_val * left_normal_end[1],
            )
            mismatch = math.hypot(
                center_start[0] - center_end[0],
                center_start[1] - center_end[1],
            )
            center = (
                (center_start[0] + center_end[0]) / 2.0,
                (center_start[1] + center_end[1]) / 2.0,
            )
            theta_start = math.atan2(start_pt[1] - center[1], start_pt[0] - center[0])
            theta_end = math.atan2(end_pt[1] - center[1], end_pt[0] - center[0])
            ccw_delta = _positive_angle(theta_end - theta_start)
            cw_delta = _positive_angle(theta_start - theta_end)
            for clockwise, actual_sweep in ((False, ccw_delta), (True, cw_delta)):
                score = mismatch + abs(actual_sweep - sweep_val) * radius_val
                if score < best_score:
                    best_score = score
                    best_mismatch = mismatch
                    best = (center, clockwise)

    if best is None:
        return None
    if best_mismatch > max(radius_val * 0.2, 1.0):
        return None

    return build_arc_geometry(
        kind="profile",
        mode=mode,
        start=start_pt,
        end=end_pt,
        center=best[0],
        radius=radius_val,
        sweep_rad=sweep_val,
        clockwise=best[1],
        start_chainage=start_chainage,
        end_chainage=end_chainage,
    )


def reverse_arc_geometry(arc_geometry, *, start_chainage: Optional[float] = None, end_chainage: Optional[float] = None):
    """反向圆弧真源，供平面反向等场景复用。"""
    data = clone_arc_geometry(arc_geometry)
    if data is None:
        return None
    orig_start = list(data["start"])
    data["start"] = list(data["end"])
    data["end"] = orig_start
    data["clockwise"] = not bool(data["clockwise"])
    if start_chainage is None:
        start_chainage = data.get("end_chainage", 0.0)
    if end_chainage is None:
        end_chainage = data.get("start_chainage", 0.0)
    data["start_chainage"] = _to_float(start_chainage)
    data["end_chainage"] = _to_float(end_chainage)
    return data


def sample_arc_geometry_points(arc_geometry, max_step_rad: float = math.radians(6.0)) -> list[Tuple[float, float]]:
    """把圆弧真源采样成折线点列，供画布绘制和边界计算。"""
    data = clone_arc_geometry(arc_geometry)
    if data is None:
        return []

    start_pt = _normalize_point(data["start"])
    end_pt = _normalize_point(data["end"])
    center_pt = _normalize_point(data["center"])
    radius_val = _to_float(data["radius"])
    sweep_val = abs(_to_float(data["sweep_rad"]))
    clockwise = _normalize_bool(data["clockwise"])
    if start_pt is None or end_pt is None or center_pt is None:
        return []
    if radius_val <= 0 or sweep_val <= 0:
        return [start_pt, end_pt]

    theta_start = math.atan2(start_pt[1] - center_pt[1], start_pt[0] - center_pt[0])
    step_limit = max(math.radians(2.0), abs(_to_float(max_step_rad, math.radians(6.0))))
    segment_count = max(8, int(math.ceil(sweep_val / step_limit)))
    direction = -1.0 if clockwise else 1.0
    step = direction * sweep_val / segment_count

    points = [start_pt]
    for index in range(1, segment_count):
        theta = theta_start + step * index
        points.append((
            center_pt[0] + radius_val * math.cos(theta),
            center_pt[1] + radius_val * math.sin(theta),
        ))
    points.append(end_pt)
    return points


def arc_midpoint(arc_geometry) -> Optional[Tuple[float, float]]:
    """返回圆弧中点，用于标签锚点等场景。"""
    data = clone_arc_geometry(arc_geometry)
    if data is None:
        return None
    start_pt = _normalize_point(data["start"])
    center_pt = _normalize_point(data["center"])
    radius_val = _to_float(data["radius"])
    sweep_val = abs(_to_float(data["sweep_rad"]))
    clockwise = _normalize_bool(data["clockwise"])
    if start_pt is None or center_pt is None or radius_val <= 0 or sweep_val <= 0:
        return None
    theta_start = math.atan2(start_pt[1] - center_pt[1], start_pt[0] - center_pt[0])
    direction = -1.0 if clockwise else 1.0
    theta_mid = theta_start + direction * sweep_val / 2.0
    return (
        center_pt[0] + radius_val * math.cos(theta_mid),
        center_pt[1] + radius_val * math.sin(theta_mid),
    )
