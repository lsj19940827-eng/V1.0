# -*- coding: utf-8 -*-
"""渡槽多工况对比表字段映射。"""

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


AQUEDUCT_DIMENSION_COLUMNS = (
    ComparisonColumn("case_name", "工况", "", None),
    ComparisonColumn("section_type", "断面类型", "", None),
    ComparisonColumn("B", "槽宽 B", "m", 3),
    ComparisonColumn("H_total", "槽身总高 H(含拉杆)", "m", 3),
    ComparisonColumn("R", "内半径 R", "m", 3),
    ComparisonColumn("f", "直段高度 f", "m", 3),
    ComparisonColumn("H_B", "H/B", "", 3),
    ComparisonColumn("tie_rod_height", "拉杆高度", "m", 3),
    ComparisonColumn("tie_bottom_height", "拉杆底控制高", "m", 3),
    ComparisonColumn("chamfer_angle", "倒角角度", "°", 1),
    ComparisonColumn("chamfer_length", "倒角边长", "m", 3),
)

AQUEDUCT_HYDRAULIC_COLUMNS = COMMON_HYDRAULIC_COLUMNS + (
    ComparisonColumn("design_top_freeboard", "设计槽顶超高", "m", 3),
    ComparisonColumn("design_tie_bottom_clearance", "设计拉杆底净距", "m", 3),
    ComparisonColumn("increased_effective_freeboard", "加大有效超高", "m", 3),
)


def _section_type(params: dict, result: dict) -> str:
    """统一读取渡槽断面类型。"""
    return str(params.get("section_type") or result.get("section_type") or "U形").strip() or "U形"


def _dimension_row(case_name: str, stype: str, params: dict, result: dict) -> dict[str, Any]:
    """生成渡槽结构尺寸对比行。"""
    B = first_num(result.get("B"), params.get("B"))
    H_total = first_num(result.get("H_total"), result.get("H"), params.get("H"))
    H_B = first_num(result.get("H_B"))
    if H_B is None and B and H_total:
        H_B = H_total / B
    return {
        "case_name": case_name,
        "section_type": stype,
        "B": B or "",
        "H_total": H_total or "",
        "R": first_num(result.get("R"), params.get("R")) or "",
        "f": first_num(result.get("f"), params.get("f")) or "",
        "H_B": H_B or "",
        "tie_rod_height": first_num(result.get("tie_rod_height"), params.get("tie_rod_height")) or "",
        "tie_bottom_height": first_num(result.get("tie_bottom_height")) or "",
        "chamfer_angle": first_num(result.get("chamfer_angle")) if result.get("has_chamfer") else "",
        "chamfer_length": first_num(result.get("chamfer_length")) if result.get("has_chamfer") else "",
    }


def _design_top_freeboard(result: dict) -> Any:
    """读取或推导设计水面到槽顶的超高。"""
    explicit = first_num(result.get("Fb_design"))
    if explicit is not None:
        return explicit
    H_total = first_num(result.get("H_total"), result.get("H"))
    h_design = first_num(result.get("h_design"))
    if H_total is None or h_design is None:
        return ""
    return H_total - h_design


def _build_row(case_name: str, params: dict, result: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    """生成渡槽单个工况的两张对比表行。"""
    stype = _section_type(params, result)
    has_tie = first_num(result.get("tie_rod_height"), params.get("tie_rod_height")) not in (None, 0)
    hydraulic = standard_hydraulic_row(case_name, stype, params, result)
    hydraulic.update(
        {
            "design_top_freeboard": _design_top_freeboard(result),
            "design_tie_bottom_clearance": first_num(result.get("design_tie_bottom_clearance")) if has_tie else "",
            "increased_effective_freeboard": (
                first_num(result.get("increased_tie_bottom_clearance"), result.get("Fb"))
                if use_increase(params) and has_increase_result(result)
                else ""
            ),
        }
    )
    return (
        hydraulic,
        _dimension_row(case_name, stype, params, result),
    )


AQUEDUCT_COMPARISON_SPEC = ComparisonTableSpec(
    panel_key="aqueduct",
    hydraulic_title="渡槽水力结果对比表",
    dimension_title="渡槽结构尺寸对比表",
    hydraulic_columns=AQUEDUCT_HYDRAULIC_COLUMNS,
    dimension_columns=AQUEDUCT_DIMENSION_COLUMNS,
    row_builder=_build_row,
)


def build_aqueduct_comparison_tables(entries):
    """生成渡槽工况对比两张表。"""
    return build_section_comparison_tables(entries, AQUEDUCT_COMPARISON_SPEC)
