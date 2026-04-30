# -*- coding: utf-8 -*-
"""明渠多工况对比表字段映射。"""

from __future__ import annotations

from typing import Any

from app_渠系计算前端.section_comparison import (
    COMMON_HYDRAULIC_COLUMNS,
    ComparisonColumn,
    ComparisonTableSpec,
    build_section_comparison_tables,
    first_num,
    has_increase_result,
    num,
    standard_hydraulic_row,
    use_increase,
)


OPEN_CHANNEL_DIMENSION_COLUMNS = (
    ComparisonColumn("case_name", "工况", "", None),
    ComparisonColumn("section_type", "断面类型", "", None),
    ComparisonColumn("B", "底宽/主宽 B", "m", 3),
    ComparisonColumn("H", "渠道高度 H", "m", 3),
    ComparisonColumn("D", "直径 D", "m", 3),
    ComparisonColumn("R", "半径 R", "m", 3),
    ComparisonColumn("m", "边坡 m", "", 3),
    ComparisonColumn("theta_deg", "圆心角 θ", "°", 1),
    ComparisonColumn("m1", "m1", "", 3),
    ComparisonColumn("B1", "B1", "m", 3),
    ComparisonColumn("m2", "m2", "", 3),
    ComparisonColumn("B2", "B2", "m", 3),
    ComparisonColumn("m3", "m3", "", 3),
    ComparisonColumn("h1", "h1", "m", 3),
)


def _section_type(params: dict, result: dict) -> str:
    """统一读取明渠断面类型。"""
    return str(params.get("section_type") or result.get("section_type") or "梯形").strip() or "梯形"


def _control_margin(params: dict, result: dict, stype: str) -> tuple[str, Any]:
    """读取明渠控制超高。"""
    if use_increase(params) and has_increase_result(result):
        return "加大渠道超高", first_num(result.get("Fb"), result.get("FB_i"))
    return "设计渠道超高", first_num(result.get("Fb"), result.get("FB_d"))


def _dimension_row(case_name: str, stype: str, params: dict, result: dict) -> dict[str, Any]:
    """生成明渠结构尺寸对比行。"""
    row = {
        "case_name": case_name,
        "section_type": stype,
        "B": "",
        "H": first_num(result.get("h_prime")),
        "D": "",
        "R": "",
        "m": first_num(params.get("m"), result.get("m")),
        "theta_deg": first_num(result.get("theta_deg"), params.get("theta_deg")),
        "m1": "",
        "B1": "",
        "m2": "",
        "B2": "",
        "m3": "",
        "h1": "",
    }
    if stype == "复式梯形":
        for key in ("m1", "B1", "m2", "B2", "m3", "h1"):
            row[key] = first_num(params.get(key), result.get(key)) or ""
        row["B"] = row["B2"]
        return row
    if stype == "圆形":
        d_value = first_num(result.get("D_design"), result.get("D"), params.get("D"))
        row["D"] = d_value or ""
        row["H"] = d_value or row["H"]
        return row
    if stype == "U形":
        row["R"] = first_num(result.get("R"), params.get("R")) or ""
        row["B"] = first_num(result.get("b_arc"), result.get("B"), params.get("b")) or ""
        return row
    row["B"] = first_num(result.get("b_design"), result.get("B"), params.get("b")) or ""
    return row


def _build_row(case_name: str, params: dict, result: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    """生成明渠单个工况的两张对比表行。"""
    stype = _section_type(params, result)
    margin_type, control_margin = _control_margin(params, result, stype)
    return (
        standard_hydraulic_row(case_name, stype, params, result, margin_type, control_margin),
        _dimension_row(case_name, stype, params, result),
    )


OPEN_CHANNEL_COMPARISON_SPEC = ComparisonTableSpec(
    panel_key="open_channel",
    hydraulic_title="明渠水力结果对比表",
    dimension_title="明渠结构尺寸对比表",
    hydraulic_columns=COMMON_HYDRAULIC_COLUMNS,
    dimension_columns=OPEN_CHANNEL_DIMENSION_COLUMNS,
    row_builder=_build_row,
)


def build_open_channel_comparison_tables(entries):
    """生成明渠工况对比两张表。"""
    return build_section_comparison_tables(entries, OPEN_CHANNEL_COMPARISON_SPEC)
