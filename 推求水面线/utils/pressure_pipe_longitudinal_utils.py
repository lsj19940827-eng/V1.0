# -*- coding: utf-8 -*-
"""
有压管道纵断面辅助工具。

负责：
1. 规范化纵断面节点
2. 按桩号采样中心线高程
3. 按子段桩号裁切整线纵断面
4. 规范化/裁切导入原始纵断面多段线
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Tuple

_LONGITUDINAL_STATION_TOL = 1e-3
_LONGITUDINAL_GEOMETRY_TOL = 1e-9


def normalize_longitudinal_nodes(longitudinal_nodes) -> List[Dict[str, Any]]:
    """将纵断面节点整理为按桩号升序的字典列表。"""
    normalized: List[Dict[str, Any]] = []
    for raw in longitudinal_nodes or []:
        if not isinstance(raw, dict):
            continue
        try:
            chainage = float(raw.get("chainage", 0.0))
            elevation = float(raw.get("elevation", 0.0))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(chainage) or not math.isfinite(elevation):
            continue
        node = dict(raw)
        node["chainage"] = chainage
        node["elevation"] = elevation
        normalized.append(node)
    normalized.sort(key=lambda item: item["chainage"])
    return normalized


def _normalize_raw_polyline_direction(
    vertices: List[Tuple[float, float]],
    bulges: List[float],
) -> Tuple[List[Tuple[float, float]], List[float]]:
    """把原始纵断面多段线统一成桩号递增方向。"""
    if len(vertices) < 2:
        return vertices, bulges
    if vertices[-1][0] >= vertices[0][0]:
        return vertices, bulges

    reversed_vertices = list(reversed(vertices))
    segment_bulges = [
        float(bulges[index]) if index < len(bulges) else 0.0
        for index in range(len(vertices) - 1)
    ]
    reversed_bulges = [-segment_bulges[index] for index in range(len(segment_bulges) - 1, -1, -1)]
    reversed_bulges.append(0.0)
    return reversed_vertices, reversed_bulges


def normalize_raw_profile_polyline(raw_profile_polyline) -> Dict[str, Any]:
    """把导入原线几何整理成统一结构。"""
    vertices_source = []
    bulges_source = []
    source_kind = "selected_raw_polyline"

    if isinstance(raw_profile_polyline, dict):
        vertices_source = list(raw_profile_polyline.get("vertices", []) or [])
        bulges_source = list(raw_profile_polyline.get("bulges", []) or [])
        source_kind = str(raw_profile_polyline.get("source_kind", "") or source_kind).strip() or source_kind
    elif isinstance(raw_profile_polyline, (list, tuple)):
        vertices_source = list(raw_profile_polyline or [])
    else:
        return {}

    vertices: List[Tuple[float, float]] = []
    for raw in vertices_source:
        if isinstance(raw, dict):
            station = raw.get("chainage", raw.get("x"))
            elevation = raw.get("elevation", raw.get("y"))
        elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
            station, elevation = raw[0], raw[1]
        else:
            continue
        try:
            station_value = float(station)
            elevation_value = float(elevation)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(station_value) or not math.isfinite(elevation_value):
            continue
        vertices.append((station_value, elevation_value))

    if len(vertices) < 2:
        return {}

    bulges = [
        float(bulges_source[index]) if index < len(bulges_source) else 0.0
        for index in range(len(vertices))
    ]
    vertices, bulges = _normalize_raw_polyline_direction(vertices, bulges)
    return {
        "vertices": vertices,
        "bulges": bulges,
        "source_kind": source_kind,
    }


def _same_raw_profile_point(
    left: Tuple[float, float],
    right: Tuple[float, float],
    tol: float = _LONGITUDINAL_STATION_TOL,
) -> bool:
    """判断两个原线点是否可视为同一点。"""
    return (
        abs(float(left[0]) - float(right[0])) <= tol
        and abs(float(left[1]) - float(right[1])) <= tol
    )


def _compute_raw_profile_arc_center(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    bulge: float,
) -> Tuple[float, float]:
    """根据 DXF bulge 计算圆弧圆心。"""
    s1, z1 = p1
    s2, z2 = p2
    ds = s2 - s1
    dz = z2 - z1
    chord = math.hypot(ds, dz)
    if chord < _LONGITUDINAL_GEOMETRY_TOL:
        return (s1 + s2) / 2.0, (z1 + z2) / 2.0
    theta = 4.0 * math.atan(abs(bulge))
    sin_half = math.sin(theta / 2.0)
    if sin_half < _LONGITUDINAL_GEOMETRY_TOL:
        return (s1 + s2) / 2.0, (z1 + z2) / 2.0
    radius = chord / (2.0 * sin_half)
    sm = (s1 + s2) / 2.0
    zm = (z1 + z2) / 2.0
    perp_s = -dz / chord
    perp_z = ds / chord
    offset = math.sqrt(max(0.0, radius ** 2 - (chord / 2.0) ** 2))
    sign = 1.0 if bulge > 0 else -1.0
    return sm + sign * offset * perp_s, zm + sign * offset * perp_z


def _sample_raw_profile_segment_point(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    bulge: float,
    station_mc: float,
) -> Tuple[float, float]:
    """在原始多段线单段上按桩号采样点坐标。"""
    station_value = float(station_mc)
    if abs(float(bulge)) <= 1e-8 or abs(p2[0] - p1[0]) <= _LONGITUDINAL_GEOMETRY_TOL:
        if abs(p2[0] - p1[0]) <= _LONGITUDINAL_GEOMETRY_TOL:
            return station_value, float(p1[1])
        ratio = (station_value - float(p1[0])) / (float(p2[0]) - float(p1[0]))
        return station_value, float(p1[1]) + (float(p2[1]) - float(p1[1])) * ratio

    center_s, center_z = _compute_raw_profile_arc_center(p1, p2, float(bulge))
    radius = math.hypot(float(p1[0]) - center_s, float(p1[1]) - center_z)
    inside = radius ** 2 - (station_value - center_s) ** 2
    if inside < -1e-8:
        raise ValueError("原始纵断面圆弧裁切超出几何范围")
    root = math.sqrt(max(0.0, inside))
    linear_ratio = (station_value - float(p1[0])) / (float(p2[0]) - float(p1[0]))
    linear_z = float(p1[1]) + (float(p2[1]) - float(p1[1])) * linear_ratio
    candidate_up = center_z + root
    candidate_down = center_z - root
    elevation_value = candidate_up if abs(candidate_up - linear_z) <= abs(candidate_down - linear_z) else candidate_down
    return station_value, elevation_value


def _compute_clipped_arc_bulge(
    original_start: Tuple[float, float],
    original_end: Tuple[float, float],
    original_bulge: float,
    clipped_start: Tuple[float, float],
    clipped_end: Tuple[float, float],
) -> float:
    """按原圆弧方向计算裁切后子弧的 bulge。"""
    if abs(float(original_bulge)) <= 1e-8:
        return 0.0
    if _same_raw_profile_point(clipped_start, clipped_end, tol=_LONGITUDINAL_GEOMETRY_TOL):
        return 0.0

    center_s, center_z = _compute_raw_profile_arc_center(original_start, original_end, float(original_bulge))

    def _angle(point: Tuple[float, float]) -> float:
        return math.atan2(float(point[1]) - center_z, float(point[0]) - center_s)

    start_angle = _angle(clipped_start)
    end_angle = _angle(clipped_end)
    if float(original_bulge) > 0:
        delta = end_angle - start_angle
    else:
        delta = start_angle - end_angle
    while delta < 0:
        delta += 2.0 * math.pi
    if delta > math.pi * 2.0:
        delta = delta % (2.0 * math.pi)
    if delta <= 1e-8:
        return 0.0
    sign = 1.0 if float(original_bulge) > 0 else -1.0
    return sign * math.tan(delta / 4.0)


def clip_raw_profile_polyline_to_range(raw_profile_polyline, start_mc: float, end_mc: float) -> Dict[str, Any]:
    """按桩号裁切导入原线，并尽量保留 bulge。"""
    normalized = normalize_raw_profile_polyline(raw_profile_polyline)
    vertices = list(normalized.get("vertices", []) or [])
    bulges = list(normalized.get("bulges", []) or [])
    if len(vertices) < 2:
        raise ValueError("原始纵断面多段线顶点不足")

    start_value = float(start_mc)
    end_value = float(end_mc)
    if end_value < start_value:
        start_value, end_value = end_value, start_value

    coverage_start = float(vertices[0][0])
    coverage_end = float(vertices[-1][0])
    tol = _LONGITUDINAL_STATION_TOL
    if start_value < coverage_start - tol or end_value > coverage_end + tol:
        raise ValueError("原始纵断面多段线覆盖范围不足")

    clipped_vertices: List[Tuple[float, float]] = []
    clipped_segment_bulges: List[float] = []

    for index in range(len(vertices) - 1):
        p1 = (float(vertices[index][0]), float(vertices[index][1]))
        p2 = (float(vertices[index + 1][0]), float(vertices[index + 1][1]))
        segment_bulge = float(bulges[index]) if index < len(bulges) else 0.0
        segment_start = min(p1[0], p2[0])
        segment_end = max(p1[0], p2[0])
        if end_value < segment_start - tol or start_value > segment_end + tol:
            continue

        clipped_start_station = max(start_value, segment_start)
        clipped_end_station = min(end_value, segment_end)
        if clipped_end_station < clipped_start_station - tol:
            continue

        start_point = (
            p1 if abs(clipped_start_station - p1[0]) <= tol
            else _sample_raw_profile_segment_point(p1, p2, segment_bulge, clipped_start_station)
        )
        end_point = (
            p2 if abs(clipped_end_station - p2[0]) <= tol
            else _sample_raw_profile_segment_point(p1, p2, segment_bulge, clipped_end_station)
        )
        if _same_raw_profile_point(start_point, end_point, tol=_LONGITUDINAL_GEOMETRY_TOL):
            continue

        if not clipped_vertices:
            clipped_vertices.append(start_point)
        elif not _same_raw_profile_point(clipped_vertices[-1], start_point):
            clipped_vertices.append(start_point)

        new_bulge = _compute_clipped_arc_bulge(
            p1,
            p2,
            segment_bulge,
            clipped_vertices[-1],
            end_point,
        )
        clipped_segment_bulges.append(new_bulge)
        clipped_vertices.append(end_point)

    if len(clipped_vertices) < 2:
        raise ValueError("原始纵断面多段线裁切后不足两点")

    clipped_bulges = list(clipped_segment_bulges) + [0.0]
    return {
        "vertices": clipped_vertices,
        "bulges": clipped_bulges,
        "source_kind": str(normalized.get("source_kind", "") or "selected_raw_polyline").strip() or "selected_raw_polyline",
    }


def _concat_raw_profile_polyline_parts(parts) -> Dict[str, Any]:
    """把多段连续原线拼成一条多段线。"""
    result_vertices: List[Tuple[float, float]] = []
    result_segment_bulges: List[float] = []
    source_kind = "selected_raw_polyline"

    for part in list(parts or []):
        normalized = normalize_raw_profile_polyline(part)
        part_vertices = list(normalized.get("vertices", []) or [])
        part_bulges = list(normalized.get("bulges", []) or [])
        if len(part_vertices) < 2:
            continue
        source_kind = str(normalized.get("source_kind", "") or source_kind).strip() or source_kind

        if not result_vertices:
            result_vertices.extend(part_vertices)
            result_segment_bulges.extend(part_bulges[:-1])
            continue

        if not _same_raw_profile_point(result_vertices[-1], part_vertices[0]):
            raise ValueError("原始纵断面多段线片段不连续，无法直接拼接")
        result_vertices.extend(part_vertices[1:])
        result_segment_bulges.extend(part_bulges[:-1])

    if len(result_vertices) < 2:
        return {}
    return {
        "vertices": result_vertices,
        "bulges": result_segment_bulges + [0.0],
        "source_kind": source_kind,
    }


def merge_raw_profile_polylines(existing_raw_profile_polyline, imported_raw_profile_polyline) -> Dict[str, Any]:
    """按覆盖范围合并多次导入的原始纵断面多段线。"""
    existing = normalize_raw_profile_polyline(existing_raw_profile_polyline)
    imported = normalize_raw_profile_polyline(imported_raw_profile_polyline)
    if not existing:
        return imported
    if not imported:
        return existing

    existing_start = float(existing["vertices"][0][0])
    existing_end = float(existing["vertices"][-1][0])
    imported_start = float(imported["vertices"][0][0])
    imported_end = float(imported["vertices"][-1][0])

    parts = []
    if existing_start < imported_start - _LONGITUDINAL_STATION_TOL:
        parts.append(clip_raw_profile_polyline_to_range(existing, existing_start, imported_start))
    parts.append(imported)
    if existing_end > imported_end + _LONGITUDINAL_STATION_TOL:
        parts.append(clip_raw_profile_polyline_to_range(existing, imported_end, existing_end))

    try:
        return _concat_raw_profile_polyline_parts(parts)
    except ValueError:
        existing_span = existing_end - existing_start
        imported_span = imported_end - imported_start
        return imported if imported_span >= existing_span else existing


def _is_arc_segment_start(node: Dict[str, Any]) -> bool:
    """判断节点是否为圆弧段起点。"""
    try:
        radius = float(node.get("vertical_curve_radius", 0.0) or 0.0)
        arc_end = float(node.get("arc_end_chainage", 0.0) or 0.0)
    except (TypeError, ValueError):
        return False
    return (
        radius > 0
        and str(node.get("turn_type", "NONE") or "NONE").upper() == "ARC"
        and arc_end > float(node.get("chainage", 0.0) or 0.0)
    )


def _resolve_arc_eta(node: Dict[str, Any]) -> float:
    """确定圆弧应取圆心上方还是下方的解。"""
    center_z = node.get("arc_center_z")
    center_s = node.get("arc_center_s")
    if center_z is None or center_s is None:
        return 1.0
    radius = float(node.get("vertical_curve_radius", 0.0) or 0.0)
    chainage = float(node.get("chainage", 0.0) or 0.0)
    elevation = float(node.get("elevation", 0.0) or 0.0)
    inside_start = max(0.0, radius ** 2 - (chainage - float(center_s)) ** 2)
    root_start = math.sqrt(inside_start)
    return 1.0 if abs(float(center_z) + root_start - elevation) <= abs(float(center_z) - root_start - elevation) else -1.0


def _sample_arc_segment_elevation(node: Dict[str, Any], station_mc: float) -> float:
    """在圆弧段内按桩号采样高程。"""
    center_s = node.get("arc_center_s")
    center_z = node.get("arc_center_z")
    if center_s is None or center_z is None:
        raise ValueError("圆弧节点缺少圆心信息，无法按桩号采样")
    radius = float(node.get("vertical_curve_radius", 0.0) or 0.0)
    inside_station = radius ** 2 - (station_mc - float(center_s)) ** 2
    if inside_station < -1e-8:
        raise ValueError(
            f"station {station_mc:.6f} 超出纵断面圆弧几何定义，无法根据节点求高程"
        )
    return float(center_z) + _resolve_arc_eta(node) * math.sqrt(max(0.0, inside_station))


def sample_longitudinal_elevation(longitudinal_nodes, station_mc: float) -> float:
    """按桩号采样纵断面高程；超出覆盖范围时拒绝外推。"""
    nodes = normalize_longitudinal_nodes(longitudinal_nodes)
    if len(nodes) < 2:
        raise ValueError("纵断面节点不足，无法按桩号采样")

    station_value = float(station_mc)
    tol = _LONGITUDINAL_STATION_TOL

    for node in nodes:
        if abs(node["chainage"] - station_value) <= tol:
            return node["elevation"]

    coverage_start = nodes[0]["chainage"]
    coverage_end = nodes[-1]["chainage"]
    if station_value < coverage_start - tol or station_value > coverage_end + tol:
        raise ValueError(
            f"station {station_value:.6f} 超出纵断面覆盖范围 "
            f"[{coverage_start:.6f}, {coverage_end:.6f}]，不允许外推"
        )

    for index, current in enumerate(nodes[:-1]):
        nxt = nodes[index + 1]
        segment_start = current["chainage"]
        if _is_arc_segment_start(current):
            segment_end = float(current.get("arc_end_chainage", segment_start) or segment_start)
            if segment_start - tol <= station_value <= segment_end + tol:
                return _sample_arc_segment_elevation(current, station_value)
            continue

        segment_end = nxt["chainage"]
        if segment_start - tol <= station_value <= segment_end + tol:
            ds = segment_end - segment_start
            if abs(ds) <= _LONGITUDINAL_GEOMETRY_TOL:
                return current["elevation"]
            ratio = (station_value - segment_start) / ds
            return current["elevation"] + (nxt["elevation"] - current["elevation"]) * ratio

    raise ValueError(
        f"station {station_value:.6f} 超出纵断面覆盖范围 "
        f"[{coverage_start:.6f}, {coverage_end:.6f}]，不允许外推"
    )


def _clear_arc_metadata(node: Dict[str, Any]) -> None:
    """将节点重置为普通点，避免把边界点误当成新的圆弧起点。"""
    node["vertical_curve_radius"] = 0.0
    node["turn_type"] = "NONE"
    node["turn_angle"] = 0.0
    node["arc_center_s"] = None
    node["arc_center_z"] = None
    node["arc_end_chainage"] = None
    node["arc_theta_rad"] = None


def _build_boundary_node(base_node: Dict[str, Any], station_mc: float, *, keep_arc: bool) -> Dict[str, Any]:
    """基于原节点生成裁切边界点。"""
    node = copy.deepcopy(base_node)
    node["chainage"] = float(station_mc)
    node["elevation"] = sample_longitudinal_elevation([base_node, node], station_mc)
    if not keep_arc:
        _clear_arc_metadata(node)
    return node


def _clone_boundary_node(nodes: List[Dict[str, Any]], station_mc: float, *, is_start: bool) -> Dict[str, Any]:
    """生成起止裁切边界点。"""
    tol = _LONGITUDINAL_STATION_TOL
    for node in nodes:
        if abs(node["chainage"] - station_mc) <= tol:
            return copy.deepcopy(node)

    sampled_elevation = sample_longitudinal_elevation(nodes, station_mc)
    for index, current in enumerate(nodes[:-1]):
        nxt = nodes[index + 1]
        if _is_arc_segment_start(current):
            arc_end = float(current.get("arc_end_chainage", current["chainage"]) or current["chainage"])
            if current["chainage"] - tol <= station_mc <= arc_end + tol:
                node = copy.deepcopy(current)
                node["chainage"] = float(station_mc)
                node["elevation"] = float(sampled_elevation)
                if not is_start:
                    _clear_arc_metadata(node)
                return node
        if current["chainage"] - tol <= station_mc <= nxt["chainage"] + tol:
            node = copy.deepcopy(current)
            node["chainage"] = float(station_mc)
            node["elevation"] = float(sampled_elevation)
            _clear_arc_metadata(node)
            return node

    node = copy.deepcopy(nodes[0] if is_start else nodes[-1])
    node["chainage"] = float(station_mc)
    node["elevation"] = float(sampled_elevation)
    _clear_arc_metadata(node)
    return node


def _trim_arc_theta(node: Dict[str, Any], new_end_chainage: float) -> None:
    """在裁切圆弧终点后同步刷新弧长角。"""
    center_s = node.get("arc_center_s")
    center_z = node.get("arc_center_z")
    if center_s is None or center_z is None:
        return
    radius = float(node.get("vertical_curve_radius", 0.0) or 0.0)
    if radius <= 0:
        return
    eta = _resolve_arc_eta(node)

    def _point_angle(chainage_value: float) -> float:
        x = (float(chainage_value) - float(center_s)) / radius
        x = max(-1.0, min(1.0, x))
        y = eta * math.sqrt(max(0.0, 1.0 - x * x))
        return math.atan2(y, x)

    start_angle = _point_angle(float(node.get("chainage", 0.0) or 0.0))
    end_angle = _point_angle(float(new_end_chainage))
    theta = abs(end_angle - start_angle)
    if theta > math.pi:
        theta = 2 * math.pi - theta
    node["arc_theta_rad"] = theta


def clip_longitudinal_nodes_to_range(longitudinal_nodes, start_mc: float, end_mc: float) -> List[Dict[str, Any]]:
    """按子段桩号裁切整线纵断面；覆盖不足时抛出错误。"""
    nodes = normalize_longitudinal_nodes(longitudinal_nodes)
    if len(nodes) < 2:
        raise ValueError("纵断面节点不足，无法按子段裁切")

    start_value = float(start_mc)
    end_value = float(end_mc)
    if end_value < start_value:
        start_value, end_value = end_value, start_value

    coverage_start = nodes[0]["chainage"]
    coverage_end = nodes[-1]["chainage"]
    tol = _LONGITUDINAL_STATION_TOL
    if start_value < coverage_start - tol or end_value > coverage_end + tol:
        raise ValueError(
            f"纵断面覆盖不足，子段桩号范围 [{start_value:.3f}, {end_value:.3f}] "
            f"超出覆盖 [{coverage_start:.3f}, {coverage_end:.3f}]"
        )

    clipped: List[Dict[str, Any]] = []
    start_boundary = _clone_boundary_node(nodes, start_value, is_start=True)
    clipped.append(start_boundary)

    for node in nodes:
        chainage = node["chainage"]
        if start_value + tol < chainage < end_value - tol:
            clipped.append(copy.deepcopy(node))

    if end_value - start_value > tol:
        end_boundary = _clone_boundary_node(nodes, end_value, is_start=False)
        if abs(end_boundary["chainage"] - clipped[-1]["chainage"]) > tol:
            clipped.append(end_boundary)

    deduped: List[Dict[str, Any]] = []
    for node in clipped:
        if deduped and abs(deduped[-1]["chainage"] - node["chainage"]) <= tol:
            deduped[-1] = node
            continue
        deduped.append(node)

    for index, node in enumerate(deduped[:-1]):
        if not _is_arc_segment_start(node):
            continue
        next_chainage = deduped[index + 1]["chainage"]
        arc_end = float(node.get("arc_end_chainage", next_chainage) or next_chainage)
        if arc_end > next_chainage + tol:
            node["arc_end_chainage"] = float(next_chainage)
            _trim_arc_theta(node, float(next_chainage))

    return deduped
