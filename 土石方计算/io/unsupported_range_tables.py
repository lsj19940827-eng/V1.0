"""Numeric skipped ranges in the standard quantity workbook."""
from __future__ import annotations

import math
from pathlib import Path
import posixpath
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from .network_exporter import SECTION_NAMES
from ..services.construction_rules import is_circular_culvert
from ..services.unmeasured_terrain_scope import AUTOMATIC_TERRAIN_GAP_CODE, AUTOMATIC_TERRAIN_GAP_FIELD
from ..services.unsupported_pipe_scope import AUTOMATIC_UNSUPPORTED_PIPE_CODE, AUTOMATIC_UNSUPPORTED_PIPE_FIELD

SHEET_NAME = "悬空区段"
TERRAIN_GAP_SHEET = "地形缺测区段"
HEADERS = ("线路", "建筑物", "起桩(m)", "终桩(m)", "长度(m)")
_TABLES = (
    (SHEET_NAME, AUTOMATIC_UNSUPPORTED_PIPE_CODE, "unsupported"),
    (TERRAIN_GAP_SHEET, AUTOMATIC_TERRAIN_GAP_CODE, "terrain_unmeasured"),
)
_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _text(value):
    return str(value or "").strip()


def _saved_range_asset(record, inputs):
    work = inputs.get("workbench") or inputs.get("workbench_inputs") or {}
    field = (AUTOMATIC_TERRAIN_GAP_FIELD if record.get("code") == AUTOMATIC_TERRAIN_GAP_CODE
             else AUTOMATIC_UNSUPPORTED_PIPE_FIELD)
    reference = record.get("source_asset_ref")
    if reference:
        for source in (work.get(field) or {}).get("source_assets", ()):
            if source.get("source_asset_ref") == reference:
                return source.get("asset") or {}

    route = record.get("route_id") or record.get("network_id")
    source_id = record.get("source_asset_id") or record.get("parent_asset_id") or record.get("asset_id")
    if route and source_id:
        networks = ([inputs["network"]] if inputs.get("network") else []) + list(work.get("networks") or [])
        for network in networks:
            if route in (network.get("route_id"), network.get("network_id")):
                for asset in network.get("assets", ()):
                    if asset.get("asset_id") == source_id:
                        return asset
    return {}


def skipped_range_building_name(record, inputs):
    """Use a saved building name or the actual structure type for an unnamed range."""
    source = _saved_range_asset(record, inputs) if not record.get("section_type") or not record.get("kind") else {}
    for item in (record, source):
        for field in ("base_name", "name", "building_name"):
            name = _text(item.get(field))
            if name not in {"", "-", "—", "/", "未命名"}:
                return name

    section = {field: record.get(field) or source.get(field)
               for field in ("section_type", "kind", "source_type")}
    if section["kind"] in {"pipe", "pressure_pipe"}:
        return "有压管道"
    if section["kind"] == "siphon":
        return "倒虹吸"
    if is_circular_culvert(section) or (not section["section_type"]
            and section["source_type"] in {"明渠-圆形", "明渠-圆形（圆管涵）"}):
        return "圆管涵"
    return (SECTION_NAMES.get(section["section_type"]) or _text(section["source_type"])
            or ("暗涵" if section["kind"] == "culvert" else "未命名建筑物"))


def _station(value, label):
    if value is None or isinstance(value, bool):
        raise ValueError(label + "起止桩号无效")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(label + "起止桩号无效") from exc
    if not math.isfinite(number):
        raise ValueError(label + "起止桩号无效")
    return number


def unsupported_range_rows(payload):
    return _range_rows(payload, SHEET_NAME, AUTOMATIC_UNSUPPORTED_PIPE_CODE)


def _range_rows(payload, label, code, *, channel_name=""):
    """Resolve line names and retain equal chainages on different routes."""
    inputs = payload.get("inputs") or {}
    work = inputs.get("workbench") or inputs.get("workbench_inputs") or {}
    networks = ([inputs["network"]] if inputs.get("network") else []) + list(work.get("networks") or [])
    channel_name = _text(channel_name) or _text(work.get("project_name"))
    names = {}
    for network in networks:
        identity = _text(network.get("route_id") or network.get("network_id") or network.get("name"))
        name = _text(network.get("name") or network.get("network_name")) or identity
        if channel_name and (network.get("source") or {}).get("kind") == "water_profile_panel":
            name = channel_name
        names[identity] = name
    duplicate_names = {name for name in names.values() if list(names.values()).count(name) > 1}
    # A completed result owns its scope. Input snapshots may still describe
    # an earlier calculation, including ranges that have since disappeared.
    candidates = payload.get("excluded_assets") if "excluded_assets" in payload else work.get("excluded")
    candidates = candidates or []
    seen = set()
    rows = []
    for item in candidates:
        if item.get("code") != code:
            continue
        route = _text(item.get("route_id") or item.get("network_id"))
        start = _station(item.get("station_start"), label)
        end = _station(item.get("station_end"), label)
        if end <= start:
            raise ValueError(label + "终桩应大于起桩")
        source = _text(item.get("source_asset_id") or item.get("parent_asset_id") or item.get("asset_id") or item.get("name"))
        key = (route, source, start, end)
        if key in seen:
            continue
        seen.add(key)
        line = names.get(route) or _text(item.get("route_name") or item.get("network_name")) or route
        if route and line in duplicate_names:
            line = f"{line}（{route}）"
        name = skipped_range_building_name(item, inputs)
        rows.append((route, source, [line, name, start, end, end - start]))
    rows.sort(key=lambda item: (item[0], item[2][2], item[2][3], item[1]))
    return [row for _route, _source, row in rows]


def append_range_sheets(workbook, payload, *, channel_name=""):
    """Add only the schedules present in the calculation's saved scope."""
    tables = {}
    for title, code, audit_prefix in _TABLES:
        rows = _range_rows(payload, title, code, channel_name=channel_name)
        if rows:
            tables[title] = _append_range_sheet(workbook, title, rows, audit_prefix)
    return tables


def _append_range_sheet(workbook, title, rows, audit_prefix):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    sheet = workbook.create_sheet(title)
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
        for cell in sheet[sheet.max_row][:2]:
            cell.data_type = "s"
    total_row = len(rows) + 2
    formula = f"=SUM(E2:E{total_row - 1})"
    sheet.append(["合计", None, None, None, formula])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:E{total_row - 1}"
    sheet.sheet_view.showGridLines = False
    sheet.print_title_rows = "1:1"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    for column, width in zip("ABCDE", (30, 38, 20, 20, 20)):
        sheet.column_dimensions[column].width = width
    sheet.row_dimensions[1].height = 28
    for cell in sheet[1]:
        cell.font = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="234E70")
        cell.alignment = Alignment(vertical="center")
    for row in sheet.iter_rows(min_row=2):
        sheet.row_dimensions[row[0].row].height = 24
        for cell in row:
            cell.font = Font(name="微软雅黑", size=11, bold=cell.row == total_row)
            cell.alignment = Alignment(vertical="center", wrap_text=cell.column <= 2)
            if cell.column >= 3:
                cell.number_format = "#,##0.000"
            if cell.row == total_row:
                cell.border = Border(top=Side(style="thin", color="7F9DB9"))
    return {"rows": rows, "total_row": total_row, "total_formula": formula,
            "total_length": math.fsum(row[4] for row in rows), "audit_prefix": audit_prefix}


def cache_range_totals(path, tables):
    """Store the numeric SUM caches so saved-file readers see the same totals."""
    if not tables:
        return
    path = Path(path)
    tag = lambda name: f"{{{_MAIN}}}{name}"
    with ZipFile(path) as source:
        book = ET.fromstring(source.read("xl/workbook.xml"))
        relationships = ET.fromstring(source.read("xl/_rels/workbook.xml.rels"))
        targets = {node.get("Id"): node.get("Target") for node in relationships}
        replacements = {}
        for sheet in book.find(tag("sheets")):
            title = sheet.get("name")
            if title not in tables:
                continue
            table = tables[title]
            target = targets[sheet.get(f"{{{_REL}}}id")]
            member = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
            document = ET.fromstring(source.read(member))
            cell = next(node for node in document.iter(tag("c")) if node.get("r") == f"E{table['total_row']}")
            formula = cell.find(tag("f"))
            if formula is None or formula.text != table["total_formula"].removeprefix("="):
                raise ValueError(title + "合计公式保存不一致")
            value = cell.find(tag("v"))
            if value is None:
                value = ET.SubElement(cell, tag("v"))
            value.text = repr(table["total_length"])
            replacements[member] = ET.tostring(document, encoding="utf-8", xml_declaration=True)
        with TemporaryDirectory(prefix=".quantity-range-", dir=path.parent) as temporary:
            staged = Path(temporary) / path.name
            with ZipFile(staged, "w") as destination:
                destination.comment = source.comment
                for info in source.infolist():
                    data = replacements.get(info.filename)
                    destination.writestr(info, data if data is not None else source.read(info.filename))
            # Close the original archive before replacing it on Windows.
            source.close()
            staged.replace(path)


def verify_range_sheets(saved, path, tables):
    """Check saved typed rows, cached totals and live SUM formulas."""
    if not tables:
        return {}
    from openpyxl import load_workbook

    audit = {}
    formulas = load_workbook(path, read_only=True, data_only=False)
    try:
        for title, table in tables.items():
            _verify_range_sheet(saved[title], formulas[title], title, table)
            key = table["audit_prefix"]
            audit.update({f"{key}_range_count": len(table["rows"]),
                          f"{key}_length_total_m": table["total_length"],
                          f"{key}_ranges_saved_verified": True})
    finally:
        formulas.close()
    return audit


def _verify_range_sheet(sheet, formulas, title, table):
    rows = list(sheet.iter_rows(min_row=2, max_row=table["total_row"] - 1, values_only=True))
    if sheet.max_row != table["total_row"] or len(rows) != len(table["rows"]):
        raise ValueError(title + "保存回读条目数改变")
    for actual, expected in zip(rows, table["rows"]):
        if list(actual[:2]) != expected[:2]:
            raise ValueError(title + "保存回读线路或建筑物改变")
        for value, target in zip(actual[2:], expected[2:]):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isclose(value, target, rel_tol=1e-14, abs_tol=1e-10):
                raise ValueError(title + "保存回读桩号或长度改变")
    actual_total = sheet.cell(table["total_row"], 5).value
    if not isinstance(actual_total, (int, float)) or not math.isclose(actual_total, table["total_length"], rel_tol=1e-14, abs_tol=1e-10):
        raise ValueError(title + "保存回读合计长度改变")
    if formulas.cell(table["total_row"], 5).value != table["total_formula"]:
        raise ValueError(title + "合计公式保存不一致")
