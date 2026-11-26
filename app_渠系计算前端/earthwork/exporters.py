# -*- coding: utf-8 -*-
"""从已发布快照导出挖填量表，保留完整数值和成果状态。"""

from __future__ import annotations

import csv
import math
import os
from pathlib import Path
import uuid


COLUMNS = (
    ("name", "建筑物 / 公共工程单元"), ("segment_id", "区段标识"),
    ("station_start", "起点桩号(m)"), ("station_end", "终点桩号(m)"),
    ("cut_volume", "挖方天然体积(m³)"), ("backfill_volume", "结构周边回填成型体积(m³)"),
    ("embankment_volume", "新增填筑成型体积(m³)"), ("fill_volume", "总填方成型体积(m³)"),
    ("ref_cut_volume", "断面复核挖方(m³)"), ("ref_backfill_volume", "断面复核周边回填(m³)"),
    ("ref_embankment_volume", "断面复核新增填筑(m³)"), ("ref_fill_volume", "断面复核总填方(m³)"),
    ("validation_status", "区段核验状态"), ("participants", "公共单元参与建筑物"),
    ("diagnostics", "核验信息"),
)
_VOLUME_KEYS = ("cut_volume", "backfill_volume", "embankment_volume", "fill_volume")


def _safe_cell(value):
    """名称保持文本，防止 Excel 把来源名称解释为公式。"""
    if isinstance(value, (list, tuple)):
        value = "；".join(str(item) for item in value)
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _checked_rows(result):
    if not isinstance(result, dict) or not result.get("result_id") or not result.get("rows"):
        raise ValueError("尚无已发布的工程量快照，不能导出数量表")
    rows = result["rows"]
    for row in rows:
        for key in _VOLUME_KEYS:
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{row.get('name', '区段')} 缺少有效的 {key}，不把缺量填为零")
        if not math.isclose(row["fill_volume"], row["backfill_volume"] + row["embankment_volume"], rel_tol=1e-10, abs_tol=1e-8):
            raise ValueError("总填方与回填、填筑分项不一致，停止导出")
    for key in _VOLUME_KEYS:
        total = result.get("totals", {}).get(key)
        if (isinstance(total, bool) or not isinstance(total, (float, int)) or not math.isfinite(total)
                or not math.isclose(total, math.fsum(row[key] for row in rows), rel_tol=1e-10, abs_tol=1e-8)):
            raise ValueError("工程量明细与汇总不一致，停止导出")
    return rows


def export_quantity_table(result, path, *, result_status, test_only=False, cancel_check=None):
    """原子生成 CSV 或 Excel；实际计算只使用已保存的未取整数量。"""
    rows = _checked_rows(result)
    target = Path(path).resolve()
    if target.suffix.lower() not in (".csv", ".xlsx"):
        raise ValueError("量表导出仅支持 CSV 或 XLSX")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tmp{target.suffix}")
    state = "当前已发布结果" if result_status == "READY" else "历史结果 / " + str(result_status)
    if "test_only" in result:
        test_only = result["test_only"]
    purpose = ("来源用途未验证" if test_only is None else
               "测试参数验收，不能作为工程设计成果" if test_only else "工程输入参数")
    metadata = [("成果状态", state), ("参数来源", purpose), ("结果标识", result["result_id"]),
                ("输入指纹", result.get("input_hash", "")), ("模型文件", result.get("model_path", "")),
                ("计算时间", result.get("created_at", "")),
                ("数量说明", "挖方按天然状态、填方按设计成型状态；未进行土石分类或松方换算。")]
    try:
        if cancel_check:
            cancel_check()
        if target.suffix.lower() == ".csv":
            with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["成果状态", "参数来源", "结果标识"] + [label for _key, label in COLUMNS])
                for item in rows:
                    if cancel_check:
                        cancel_check()
                    writer.writerow([state, purpose, result["result_id"]] + [_safe_cell(item.get(key)) for key, _label in COLUMNS])
                total = {"name": "全线汇总", **result["totals"]}
                writer.writerow([state, purpose, result["result_id"]] + [_safe_cell(total.get(key)) for key, _label in COLUMNS])
        else:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font, PatternFill
            from openpyxl.utils import get_column_letter
            book = Workbook()
            table = book.active
            table.title = "挖填工程量"
            table.append(["成果状态", "参数来源"] + [label for _key, label in COLUMNS])
            for item in rows:
                if cancel_check:
                    cancel_check()
                table.append([state, purpose] + [_safe_cell(item.get(key)) for key, _label in COLUMNS])
            total = {"name": "全线汇总", **result["totals"]}
            table.append([state, purpose] + [_safe_cell(total.get(key)) for key, _label in COLUMNS])
            for cell in table[1]:
                cell.fill = PatternFill("solid", fgColor="17365D")
                cell.font = Font(name="微软雅黑", color="FFFFFF", bold=True)
                cell.alignment = Alignment(wrap_text=True, vertical="center")
            table.row_dimensions[1].height = 44
            for column in range(1, table.max_column + 1):
                table.column_dimensions[get_column_letter(column)].width = 23 if column < 5 else 19
            for row in table.iter_rows(min_row=2):
                for cell in row:
                    cell.font = Font(name="微软雅黑", size=10)
                    if isinstance(cell.value, (float, int)):
                        cell.number_format = "#,##0.000"
            table.freeze_panes = "E2"
            table.auto_filter.ref = f"A1:{get_column_letter(table.max_column)}{table.max_row - 1}"
            table.sheet_properties.pageSetUpPr.fitToPage = True
            table.page_setup.orientation = "landscape"
            table.page_setup.paperSize = table.PAPERSIZE_A3
            table.page_setup.fitToWidth = 1
            table.page_setup.fitToHeight = 0
            table.print_title_rows = "1:1"
            info = book.create_sheet("成果依据与状态")
            for key, value in metadata:
                info.append([key, _safe_cell(value)])
            info.column_dimensions["A"].width = 20
            info.column_dimensions["B"].width = 100
            for row in info:
                row[1].alignment = Alignment(wrap_text=True, vertical="top")
            book.save(temporary)
            book.close()
        if cancel_check:
            cancel_check()
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return str(target)
