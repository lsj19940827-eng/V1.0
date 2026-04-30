# -*- coding: utf-8 -*-
"""暗涵多工况对比表字段映射。"""

from __future__ import annotations

from typing import Any

from app_渠系计算前端.section_comparison import (
    COMMON_HYDRAULIC_COLUMNS,
    ComparisonColumn,
    ComparisonTableSpec,
    build_section_comparison_tables,
    first_num,
    has_increase_result,
    standard_hydraulic_row,
    use_increase,
)


CULVERT_DIMENSION_COLUMNS = (
    ComparisonColumn("case_name", "工况", "", None),
    ComparisonColumn("section_type", "断面类型", "", None),
    ComparisonColumn("B", "宽度 B", "m", 3),
    ComparisonColumn("H", "高度 H/总高 H", "m", 3),
    ComparisonColumn("H_straight", "直墙高度 H直", "m", 3),
    ComparisonColumn("H_straight_source", "H直来源", "", None),
    ComparisonColumn("theta_deg", "拱顶圆心角 θ", "°", 1),
    ComparisonColumn("BH_ratio", "宽深比 β", "", 3),
    ComparisonColumn("HB_ratio", "高宽比 H/B", "", 3),
    ComparisonColumn("A_total", "断面总面积 A总", "m²", 3),
)


def _normalize_section_type(value) -> str:
    """统一暗涵子类型名称。"""
    text = str(value or "").strip()
    if "圆拱直墙" in text:
        return "圆拱直墙型"
    return "矩形"


def _section_type(params: dict, result: dict) -> str:
    """读取暗涵断面类型。"""
    return _normalize_section_type(params.get("section_type") or result.get("section_type"))


def _control_margin(params: dict, result: dict) -> tuple[str, Any]:
    """读取暗涵控制净空。"""
    if use_increase(params) and has_increase_result(result):
        return "加大净空高度", first_num(result.get("freeboard_hgt_inc"), result.get("Fb"))
    return "设计净空高度", first_num(result.get("freeboard_hgt_design"), result.get("Fb_design"))


def _wall_source(params: dict, result: dict) -> str:
    """判断 H直 是手填还是自动推导。"""
    if result.get("used_manual_H_straight") or params.get("manual_H_straight") or params.get("arch_H_straight"):
        return "手填"
    return "自动推导"


def _dimension_row(case_name: str, stype: str, params: dict, result: dict) -> dict[str, Any]:
    """生成暗涵结构尺寸对比行。"""
    is_arch = stype == "圆拱直墙型"
    return {
        "case_name": case_name,
        "section_type": f"暗涵-{stype}",
        "B": first_num(result.get("B"), params.get("B"), params.get("arch_B")) or "",
        "H": first_num(result.get("H_total"), result.get("H")) or "",
        "H_straight": first_num(result.get("H_straight")) if is_arch else "",
        "H_straight_source": _wall_source(params, result) if is_arch else "",
        "theta_deg": first_num(result.get("theta_deg"), params.get("theta_deg")) if is_arch else "",
        "BH_ratio": first_num(result.get("BH_ratio"), params.get("bh")) or "",
        "HB_ratio": first_num(result.get("HB_ratio"), params.get("hb")) or "",
        "A_total": first_num(result.get("A_total")) or "",
    }


def _build_row(case_name: str, params: dict, result: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    """生成暗涵单个工况的两张对比表行。"""
    stype = _section_type(params, result)
    margin_type, control_margin = _control_margin(params, result)
    hydraulic = standard_hydraulic_row(case_name, f"暗涵-{stype}", params, result, margin_type, control_margin)
    return hydraulic, _dimension_row(case_name, stype, params, result)


CULVERT_COMPARISON_SPEC = ComparisonTableSpec(
    panel_key="culvert",
    hydraulic_title="暗涵水力结果对比表",
    dimension_title="暗涵结构尺寸对比表",
    hydraulic_columns=COMMON_HYDRAULIC_COLUMNS,
    dimension_columns=CULVERT_DIMENSION_COLUMNS,
    row_builder=_build_row,
)


def build_culvert_comparison_tables(entries):
    """生成暗涵工况对比两张表。"""
    return build_section_comparison_tables(entries, CULVERT_COMPARISON_SPEC)
