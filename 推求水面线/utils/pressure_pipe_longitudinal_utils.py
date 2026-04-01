# -*- coding: utf-8 -*-
"""
有压管道纵断面辅助工具。

负责：
1. 规范化纵断面节点
2. 按桩号采样中心线高程
3. 按子段桩号裁切整线纵断面
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, List

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
