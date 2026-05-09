# -*- coding: utf-8 -*-
"""四类水工建筑物工况对比表的共享数据整理工具。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class ComparisonColumn:
    """描述对比表中的一列。"""

    key: str
    title: str
    unit: str = ""
    digits: int | None = 3


@dataclass(frozen=True)
class ComparisonRowSet:
    """保存水力结果表和结构尺寸表的行数据。"""

    hydraulic_rows: list[dict[str, Any]]
    dimension_rows: list[dict[str, Any]]


@dataclass(frozen=True)
class ComparisonTableSpec:
    """描述某类面板的对比表列和行构造函数。"""

    panel_key: str
    hydraulic_title: str
    dimension_title: str
    hydraulic_columns: tuple[ComparisonColumn, ...]
    dimension_columns: tuple[ComparisonColumn, ...]
    row_builder: Callable[[str, dict, dict], tuple[dict[str, Any], dict[str, Any]]]


COMMON_HYDRAULIC_COLUMNS = (
    ComparisonColumn("case_name", "工况", "", None),
    ComparisonColumn("section_type", "断面类型", "", None),
    ComparisonColumn("Q_design", "设计流量 Q", "m³/s", 3),
    ComparisonColumn("Q_increased", "加大流量 Q加大", "m³/s", 3),
    ComparisonColumn("h_design", "设计水深 h", "m", 3),
    ComparisonColumn("V_design", "设计流速 V", "m/s", 3),
    ComparisonColumn("h_increased", "加大水深 h加大", "m", 3),
    ComparisonColumn("V_increased", "加大流速 V加大", "m/s", 3),
)


def num(value: Any) -> float | None:
    """把输入安全转换为有限浮点数。"""
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def positive(value: Any) -> float | None:
    """读取正数，非正数按缺失处理。"""
    number = num(value)
    return number if number is not None and number > 0 else None


def first_num(*values: Any) -> float | None:
    """按顺序读取第一个有效数字。"""
    for value in values:
        number = num(value)
        if number is not None:
            return number
    return None


def use_increase(params: dict) -> bool:
    """判断当前工况是否启用加大流量。"""
    return bool(params.get("use_increase", True))


def has_increase_result(result: dict) -> bool:
    """判断加大流量工况是否有可展示结果。"""
    return positive(result.get("h_increased")) is not None and positive(result.get("V_increased")) is not None


def increase_value(params: dict, result: dict, key: str) -> Any:
    """启用加大流量且有结果时读取字段，否则留空。"""
    if not use_increase(params):
        return ""
    return num(result.get(key)) if num(result.get(key)) is not None else ""


def format_comparison_cell(value: Any, digits: int | None = 3) -> str:
    """按对比表显示口径格式化单元格。"""
    if value is None or value == "":
        return ""
    if digits is None:
        return str(value)
    number = num(value)
    if number is None:
        return str(value)
    return f"{number:.{digits}f}"


def comparison_header_text(column: ComparisonColumn) -> str:
    """生成包含单位的表头文本。"""
    return f"{column.title}({column.unit})" if column.unit else column.title


def entry_payload(entry: Any, index: int) -> tuple[str, dict, dict, bool]:
    """从多种工况结果结构中提取统一字段，兼容 JSON 恢复后的列表。"""
    if isinstance(entry, (tuple, list)) and len(entry) >= 3:
        case_idx, params, result = entry[:3]
        label = f"工况{int(case_idx) + 1}"
        valid = bool(result and result.get("success", True))
        case_name = f"工况 {int(case_idx) + 1}｜{label}"
        return case_name, params or {}, result or {}, valid

    if isinstance(entry, dict):
        label = str(entry.get("label") or f"工况{index + 1}")
        params = entry.get("input") or entry.get("input_params") or {}
        result = entry.get("result") or {}
        valid = bool(result and result.get("success", True))
        case_idx = int(entry.get("case_idx", index))
        return f"工况 {case_idx + 1}｜{label}", params, result, valid

    label = str(getattr(entry, "label", "") or f"工况{index + 1}")
    params = getattr(entry, "input_params", {}) or {}
    result = getattr(entry, "result", None) or {}
    valid = bool(getattr(entry, "is_valid", True)) and bool(result and result.get("success", True))
    case_idx = int(getattr(entry, "case_idx", index))
    return f"工况 {case_idx + 1}｜{label}", params, result, valid


def build_section_comparison_tables(entries: Iterable[Any], spec: ComparisonTableSpec) -> ComparisonRowSet:
    """按指定面板口径生成两张工况对比表。"""
    hydraulic_rows: list[dict[str, Any]] = []
    dimension_rows: list[dict[str, Any]] = []
    for index, entry in enumerate(entries or []):
        case_name, params, result, valid = entry_payload(entry, index)
        if not valid:
            continue
        hydraulic_row, dimension_row = spec.row_builder(case_name, params or {}, result or {})
        hydraulic_rows.append(hydraulic_row)
        dimension_rows.append(dimension_row)
    return ComparisonRowSet(hydraulic_rows=hydraulic_rows, dimension_rows=dimension_rows)


def standard_hydraulic_row(
    case_name: str,
    section_type: str,
    params: dict,
    result: dict,
) -> dict[str, Any]:
    """生成四类面板通用的水力结果对比行。"""
    return {
        "case_name": case_name,
        "section_type": section_type,
        "Q_design": num(params.get("Q")) or "",
        "Q_increased": increase_value(params, result, "Q_increased"),
        "h_design": num(result.get("h_design")) or "",
        "V_design": num(result.get("V_design")) or "",
        "h_increased": increase_value(params, result, "h_increased"),
        "V_increased": increase_value(params, result, "V_increased"),
    }


def fill_comparison_table(table, columns: tuple[ComparisonColumn, ...], rows: list[dict[str, Any]]):
    """把对比行填入 Qt 表格控件。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTableWidgetItem

    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels([comparison_header_text(column) for column in columns])
    table.setRowCount(len(rows))
    for row_idx, row in enumerate(rows):
        for col_idx, column in enumerate(columns):
            text = format_comparison_cell(row.get(column.key), column.digits)
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row_idx, col_idx, item)
    table.resizeColumnsToContents()


def build_table_clipboard_text(table) -> tuple[str, int, int]:
    """把 Qt 表格选区整理为可粘贴到 Excel 的文本。"""
    if table is None:
        return "", 0, 0
    indexes = table.selectedIndexes()
    if not indexes:
        return "", 0, 0
    rows = sorted({idx.row() for idx in indexes})
    cols = sorted({idx.column() for idx in indexes})
    selected = {(idx.row(), idx.column()) for idx in indexes}

    header_cells = []
    for col in cols:
        header_item = table.horizontalHeaderItem(col)
        header_cells.append(header_item.text() if header_item else "")

    lines = ["\t".join(header_cells)]
    for row in rows:
        row_cells = []
        for col in cols:
            if (row, col) not in selected:
                row_cells.append("")
                continue
            item = table.item(row, col)
            row_cells.append(item.text() if item else "")
        lines.append("\t".join(row_cells))
    return "\n".join(lines), len(rows), len(cols)


def _dxf_header_lines(column: ComparisonColumn) -> list[str]:
    """生成 DXF 表头分行。"""
    return [column.title, f"({column.unit})"] if column.unit else [column.title]


def _dxf_text_weight(text: object) -> float:
    """估算 DXF 单行文字宽度权重。"""
    weight = 0.0
    for char in str(text):
        code = ord(char)
        if char.isspace():
            weight += 0.35
        elif code > 0x2E80:
            weight += 1.05
        elif char.isupper():
            weight += 0.68
        else:
            weight += 0.58
    return max(weight, 1.0)


def _estimate_dxf_text_width(text: object, height: float) -> float:
    """估算 DXF 文字宽度。"""
    from app_渠系计算前端.dxf_common import DXF_TEXT_WIDTH_FACTOR

    return _dxf_text_weight(text) * float(height) * DXF_TEXT_WIDTH_FACTOR


def _dxf_col_width(column: ComparisonColumn, rows: list[dict[str, Any]], text_h: float) -> float:
    """根据表头和内容估算安全列宽。"""
    candidates = [_estimate_dxf_text_width(line, text_h) for line in _dxf_header_lines(column)]
    for row in rows:
        candidates.append(_estimate_dxf_text_width(format_comparison_cell(row.get(column.key), column.digits), text_h))
    return max(18.0, max(candidates, default=0.0) + text_h * 2.2)


def _add_table_text(msp, text: object, cx: float, cy: float, height: float):
    """在 DXF 表格单元格中心写入文字。"""
    from app_渠系计算前端.dxf_common import add_centered_dxf_text

    add_centered_dxf_text(msp, text, cx, cy, height, layer="参数文字", style="FANGSONG")


def _draw_one_dxf_table(msp, title: str, columns, rows, origin_x: float, origin_y: float) -> float:
    """绘制单张 DXF 对比表并返回高度。"""
    if not rows:
        return 0.0
    title_h = 9.0
    header_h = 10.0
    row_h = 7.0
    title_text_h = 5.0
    text_h = 3.2
    widths = [_dxf_col_width(column, rows, text_h) for column in columns]
    table_w = sum(widths)
    table_h = title_h + header_h + row_h * len(rows)
    x_left = float(origin_x)
    y_top = float(origin_y)
    y_title_bottom = y_top - title_h
    y_header_bottom = y_title_bottom - header_h
    y_bottom = y_top - table_h
    x_right = x_left + table_w

    for y in (y_top, y_title_bottom, y_header_bottom, y_bottom):
        msp.add_line((x_left, y), (x_right, y), dxfattribs={"layer": "参数文字"})
    msp.add_line((x_left, y_top), (x_left, y_bottom), dxfattribs={"layer": "参数文字"})
    msp.add_line((x_right, y_top), (x_right, y_bottom), dxfattribs={"layer": "参数文字"})
    for idx in range(1, len(rows)):
        y = y_header_bottom - row_h * idx
        msp.add_line((x_left, y), (x_right, y), dxfattribs={"layer": "参数文字"})

    _add_table_text(msp, title, x_left + table_w / 2.0, y_top - title_h / 2.0, title_text_h)

    x = x_left
    for col_idx, column in enumerate(columns):
        width = widths[col_idx]
        if col_idx > 0:
            msp.add_line((x, y_title_bottom), (x, y_bottom), dxfattribs={"layer": "参数文字"})
        lines = _dxf_header_lines(column)
        if len(lines) == 1:
            _add_table_text(msp, lines[0], x + width / 2.0, y_title_bottom - header_h / 2.0, text_h)
        else:
            _add_table_text(msp, lines[0], x + width / 2.0, y_title_bottom - header_h * 0.35, text_h)
            _add_table_text(msp, lines[1], x + width / 2.0, y_title_bottom - header_h * 0.70, text_h)
        x += width

    for row_idx, row in enumerate(rows):
        y_center = y_header_bottom - row_h * (row_idx + 0.5)
        x = x_left
        for col_idx, column in enumerate(columns):
            width = widths[col_idx]
            text = format_comparison_cell(row.get(column.key), column.digits)
            _add_table_text(msp, text, x + width / 2.0, y_center, text_h)
            x += width
    return table_h


def draw_section_comparison_tables(
    doc,
    msp,
    entries,
    spec: ComparisonTableSpec,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    overall_title: str | None = None,
) -> float:
    """把水力结果和结构尺寸两张对比表绘入 DXF。"""
    from app_渠系计算前端.dxf_common import ensure_section_dxf_layers

    ensure_section_dxf_layers(doc)
    tables = build_section_comparison_tables(entries, spec)
    if not tables.hydraulic_rows and not tables.dimension_rows:
        return 0.0

    y = float(origin_y)
    total_h = 0.0
    if overall_title:
        title_h = 9.0
        _add_table_text(msp, overall_title, float(origin_x) + 120.0, y - title_h / 2.0, 5.0)
        y -= title_h + 4.0
        total_h += title_h + 4.0
    first_h = _draw_one_dxf_table(
        msp, spec.hydraulic_title, spec.hydraulic_columns, tables.hydraulic_rows, origin_x, y
    )
    y -= first_h + 12.0
    total_h += first_h + 12.0
    second_h = _draw_one_dxf_table(
        msp, spec.dimension_title, spec.dimension_columns, tables.dimension_rows, origin_x, y
    )
    total_h += second_h
    return total_h


def _word_table_data(columns: tuple[ComparisonColumn, ...], rows: list[dict[str, Any]]):
    """生成 Word 表格表头和数据。"""
    headers = [comparison_header_text(column) for column in columns]
    data = [
        [format_comparison_cell(row.get(column.key), column.digits) for column in columns]
        for row in rows
    ]
    return headers, data


def add_section_comparison_word_tables(
    doc,
    entries,
    spec: ComparisonTableSpec,
    *,
    heading_func=None,
    table_func=None,
) -> bool:
    """把两张工况对比表写入 Word 文档。"""
    if heading_func is None or table_func is None:
        from app_渠系计算前端.export_utils import doc_add_eng_h, doc_add_styled_table

        heading_func = heading_func or doc_add_eng_h
        table_func = table_func or doc_add_styled_table

    tables = build_section_comparison_tables(entries, spec)
    if not tables.hydraulic_rows and not tables.dimension_rows:
        return False
    for title, columns, rows in (
        (spec.hydraulic_title, spec.hydraulic_columns, tables.hydraulic_rows),
        (spec.dimension_title, spec.dimension_columns, tables.dimension_rows),
    ):
        if not rows:
            continue
        heading_func(doc, title)
        headers, data = _word_table_data(columns, rows)
        table_func(doc, headers, data, with_full_border=True)
    return True
