# -*- coding: utf-8 -*-
"""整理隧洞多工况对比表数据，供界面和 DXF 导出共用。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

from app_渠系计算前端.section_comparison import (
    COMMON_HYDRAULIC_COLUMNS,
    ComparisonTableSpec,
    build_section_comparison_tables,
    first_num,
    has_increase_result,
    standard_hydraulic_row,
    use_increase,
)
from app_渠系计算前端.tunnel.geometry import (
    build_arch_geometry,
    build_flat_bottom_circle_geometry,
    build_standard_horseshoe_geometry,
)


@dataclass(frozen=True)
class ComparisonColumn:
    """描述对比表的一列。"""

    key: str
    title: str
    unit: str = ""
    digits: int | None = 3


TUNNEL_COMPARISON_COLUMNS = (
    ComparisonColumn("case_name", "工况", "", None),
    ComparisonColumn("section_type", "断面类型", "", None),
    ComparisonColumn("Q_design", "设计流量", "m³/s", 3),
    ComparisonColumn("Q_increased", "加大流量", "m³/s", 3),
    ComparisonColumn("h_design", "设计水深", "m", 3),
    ComparisonColumn("V_design", "设计流速", "m/s", 3),
    ComparisonColumn("h_increased", "加大水深", "m", 3),
    ComparisonColumn("V_increased", "加大流速", "m/s", 3),
    ComparisonColumn("B", "底宽 B", "m", 3),
    ComparisonColumn("D", "直径 D", "m", 3),
    ComparisonColumn("r", "半径 r", "m", 3),
    ComparisonColumn("H_total", "洞总高 H", "m", 3),
    ComparisonColumn("H_straight", "直墙高度 H直", "m", 3),
    ComparisonColumn("total_perimeter", "洞身周长", "m", 3),
    ComparisonColumn("total_area", "洞身断面积", "m²", 3),
)

TUNNEL_HYDRAULIC_COMPARISON_COLUMNS = COMMON_HYDRAULIC_COLUMNS

TUNNEL_DIMENSION_COMPARISON_COLUMNS = (
    ComparisonColumn("case_name", "工况", "", None),
    ComparisonColumn("section_type", "断面类型", "", None),
    ComparisonColumn("B", "底宽 B", "m", 3),
    ComparisonColumn("D", "直径 D", "m", 3),
    ComparisonColumn("r", "半径 r", "m", 3),
    ComparisonColumn("H_total", "洞总高 H", "m", 3),
    ComparisonColumn("H_straight", "直墙高度 H直", "m", 3),
    ComparisonColumn("total_perimeter", "洞身周长", "m", 3),
    ComparisonColumn("total_area", "洞身断面积", "m²", 3),
)


def _num(value: Any) -> float | None:
    """把输入安全转换为有限浮点数。"""
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> float | None:
    """读取正数，非正数按缺失处理。"""
    number = _num(value)
    return number if number is not None and number > 0 else None


def _section_type(params: dict, result: dict) -> str:
    """统一解析隧洞断面类型。"""
    return str(params.get("section_type") or result.get("section_type") or "圆形").strip() or "圆形"


def _result_total_area(result: dict) -> float | None:
    """优先读取计算结果里的完整洞身面积。"""
    return _positive(result.get("A_total"))


def _horseshoe_section_type(params: dict, result: dict, stype: str) -> int:
    """解析标准马蹄形Ⅰ/Ⅱ型。"""
    raw = params.get("sec_type_int") or result.get("section_type_int") or result.get("horseshoe_section_type")
    try:
        number = int(raw)
    except (TypeError, ValueError):
        number = 1 if "Ⅰ" in stype or "I" in stype.upper() else 2
    return 1 if number == 1 else 2


def _arc_span_rad(arc: dict) -> float:
    """计算圆弧从起点到终点的正向角度。"""
    start = math.radians(float(arc["start_deg"]))
    end = math.radians(float(arc["end_deg"]))
    if end < start:
        end += math.tau
    return end - start


def _standard_horseshoe_area_from_geometry(geom: dict) -> float:
    """用圆弧采样兜底计算标准马蹄形完整断面积。"""
    points: list[tuple[float, float]] = []
    for arc in geom["arcs"]:
        start = math.radians(float(arc["start_deg"]))
        end = math.radians(float(arc["end_deg"]))
        if end < start:
            end += math.tau
        samples = 48
        cx, cy = arc["center"]
        radius = float(arc["radius"])
        for idx in range(samples):
            if points and idx == 0:
                continue
            angle = start + (end - start) * idx / (samples - 1)
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    if len(points) < 3:
        return 0.0
    area = 0.0
    for idx, point in enumerate(points):
        nxt = points[(idx + 1) % len(points)]
        area += point[0] * nxt[1] - nxt[0] * point[1]
    return abs(area) / 2.0


def compute_tunnel_total_geometry_metrics(params: dict | None, result: dict | None) -> dict[str, Any]:
    """计算完整洞身尺寸、周长和断面积。"""
    params = params or {}
    result = result or {}
    stype = _section_type(params, result)
    metrics: dict[str, Any] = {
        "B": "",
        "D": "",
        "r": "",
        "H_total": "",
        "H_straight": "",
        "total_perimeter": "",
        "total_area": "",
    }

    if stype == "平底圆形":
        D = _positive(result.get("D", params.get("D")))
        B = _positive(result.get("B", params.get("B")))
        if D is None or B is None:
            return metrics
        geom = build_flat_bottom_circle_geometry(D, B)
        metrics.update(
            {
                "D": D,
                "B": B,
                "H_total": geom["H_total"],
                "total_perimeter": B + geom["radius"] * geom["major_arc_angle_rad"],
                "total_area": _result_total_area(result) or geom["A_total"],
            }
        )
        return metrics

    if stype == "圆形":
        D = _positive(result.get("D", params.get("D")))
        if D is None:
            return metrics
        metrics.update(
            {
                "D": D,
                "H_total": D,
                "total_perimeter": math.pi * D,
                "total_area": _result_total_area(result) or math.pi * (D / 2.0) ** 2,
            }
        )
        return metrics

    if stype == "圆拱直墙型":
        B = _positive(result.get("B", params.get("B")))
        H_total = _positive(result.get("H_total", params.get("H_total", params.get("H"))))
        theta_deg = _num(result.get("theta_deg", params.get("theta_deg"))) or 180.0
        if B is None or H_total is None:
            return metrics
        geom = build_arch_geometry(B, H_total, math.radians(theta_deg))
        H_straight = _num(result.get("H_straight", params.get("H_straight")))
        if H_straight is None:
            H_straight = geom["H_straight"]
        H_straight = max(0.0, H_straight)
        total_area = _result_total_area(result)
        if total_area is None:
            total_area = B * H_straight + (geom["R_arch"] ** 2 / 2.0) * (
                geom["theta_rad"] - math.sin(geom["theta_rad"])
            )
        metrics.update(
            {
                "B": B,
                "H_total": H_total,
                "H_straight": H_straight,
                "total_perimeter": B + 2.0 * H_straight + geom["R_arch"] * geom["theta_rad"],
                "total_area": total_area,
            }
        )
        return metrics

    r = _positive(result.get("r", params.get("r")))
    if r is None:
        return metrics
    geom = build_standard_horseshoe_geometry(_horseshoe_section_type(params, result, stype), r)
    total_perimeter = sum(float(arc["radius"]) * _arc_span_rad(arc) for arc in geom["arcs"])
    metrics.update(
        {
            "r": r,
            "H_total": 2.0 * r,
            "total_perimeter": total_perimeter,
            "total_area": _result_total_area(result) or _standard_horseshoe_area_from_geometry(geom),
        }
    )
    return metrics


def _entry_payload(entry: Any, index: int) -> tuple[str, dict, dict, bool]:
    """从 DxfExportCaseEntry 或 _all_results 字典中提取统一字段。"""
    if isinstance(entry, dict):
        label = str(entry.get("label") or f"工况{index + 1}")
        params = entry.get("input") or entry.get("input_params") or {}
        result = entry.get("result") or {}
        valid = bool(result and result.get("success", True))
        case_idx = entry.get("case_idx", index)
    else:
        label = str(getattr(entry, "label", "") or f"工况{index + 1}")
        params = getattr(entry, "input_params", {}) or {}
        result = getattr(entry, "result", None) or {}
        valid = bool(getattr(entry, "is_valid", True)) and bool(result and result.get("success", True))
        case_idx = getattr(entry, "case_idx", index)
    case_name = f"工况 {int(case_idx) + 1}｜{label}"
    return case_name, params, result, valid


def _use_increase(params: dict) -> bool:
    """判断是否启用加大工况。"""
    return bool(params.get("use_increase", True))


def build_tunnel_comparison_rows(entries_or_results: Iterable[Any]) -> list[dict[str, Any]]:
    """生成隧洞多工况对比表行。"""
    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(entries_or_results or []):
        case_name, params, result, valid = _entry_payload(entry, index)
        if not valid:
            continue
        metrics = compute_tunnel_total_geometry_metrics(params, result)
        use_increase = _use_increase(params)
        row = {
            "case_name": case_name,
            "section_type": _section_type(params, result),
            "Q_design": _num(params.get("Q")) or "",
            "Q_increased": _num(result.get("Q_increased")) if use_increase else "",
            "h_design": _num(result.get("h_design")) or "",
            "V_design": _num(result.get("V_design")) or "",
            "h_increased": _num(result.get("h_increased")) if use_increase else "",
            "V_increased": _num(result.get("V_increased")) if use_increase else "",
            **metrics,
        }
        rows.append(row)
    return rows


def _tunnel_control_margin(params: dict, result: dict) -> tuple[str, Any]:
    """读取隧洞净空控制余量。"""
    if use_increase(params) and has_increase_result(result):
        return "加大净空高度", first_num(result.get("freeboard_hgt_inc"), result.get("freeboard_pct_inc"))
    return "设计净空高度", first_num(result.get("freeboard_hgt_design"), result.get("freeboard_pct_design"))


def _build_tunnel_table_row(case_name: str, params: dict, result: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    """生成隧洞单个工况的水力和结构对比行。"""
    stype = _section_type(params, result)
    margin_type, control_margin = _tunnel_control_margin(params, result)
    hydraulic = standard_hydraulic_row(case_name, stype, params, result, margin_type, control_margin)
    dimension = {"case_name": case_name, "section_type": stype}
    dimension.update(compute_tunnel_total_geometry_metrics(params, result))
    return hydraulic, dimension


TUNNEL_COMPARISON_SPEC = ComparisonTableSpec(
    panel_key="tunnel",
    hydraulic_title="隧洞水力结果对比表",
    dimension_title="隧洞结构尺寸对比表",
    hydraulic_columns=TUNNEL_HYDRAULIC_COMPARISON_COLUMNS,
    dimension_columns=TUNNEL_DIMENSION_COMPARISON_COLUMNS,
    row_builder=_build_tunnel_table_row,
)


def build_tunnel_comparison_tables(entries_or_results: Iterable[Any]):
    """生成隧洞工况对比两张表。"""
    return build_section_comparison_tables(entries_or_results, TUNNEL_COMPARISON_SPEC)


def format_comparison_cell(value: Any, digits: int | None = 3) -> str:
    """按对比表显示口径格式化单元格。"""
    if value is None or value == "":
        return ""
    if digits is None:
        return str(value)
    number = _num(value)
    if number is None:
        return str(value)
    return f"{number:.{digits}f}"


def comparison_header_text(column: ComparisonColumn) -> str:
    """生成包含单位的表头文本。"""
    return f"{column.title}({column.unit})" if column.unit else column.title
