"""Compact schedules and section captions from the saved calculation snapshot."""
from __future__ import annotations

from collections import defaultdict
import math
import unicodedata

from ..services.pipe_dimensions import DN_ENVELOPE_BASIS
from .structure_quantity_tables import BACKFILL_SPLIT_COLUMNS, earthwork_columns


UNITS = {"m3": "m³", "m2": "m²", "m": "m", "kg": "kg", "t": "t", "count": "个"}


def _number(value):
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) else None)


def _item_name(item, asset=None):
    name = str(item.get("name") or item.get("component_id") or "材料")
    name = {"衬砌/结构混凝土": "结构混凝土", "垫层/找平": "垫层"}.get(name, name)
    construction=(asset or {}).get("construction") or {}
    seat=construction.get("pipe_seat") or construction.get("pipe_support") or {}
    sand_seat=(seat.get("enabled",True) and seat.get("material_role")=="bedding" and
               seat.get("material") in {"sand","砂","砂垫层"})
    if name == "垫层" and (item.get("material") in {"sand", "砂", "砂垫层"} or
                           item.get("component_id")=="bedding" and sand_seat):
        name = "砂垫层"
    grade = str(item.get("grade") or "")
    if grade and grade not in name:
        name = grade + name
    return name


def station_label(value):
    millimetres=round(float(value)*1000)
    kilometres,remainder=divmod(millimetres,1000000)
    return f"K{kilometres}+{remainder/1000:07.3f}"


def connection_estimate_note(estimate):
    parts = [str(estimate.get("basis") or "")]
    name = str(estimate.get("reference_name") or "").strip()
    start = _number(estimate.get("reference_station_start"))
    end = _number(estimate.get("reference_station_end"))
    reference = name if name not in {"", "-", "—", "/", "未命名"} else ""
    if start is not None and end is not None:
        span = f"{station_label(start)}～{station_label(end)}"
        reference = f"{reference} {span}".strip()
    if reference:
        parts.append(f"参考断面 {reference}")
    if estimate.get("section_type") == "circular_culvert":
        diameter = _number(estimate.get("envelope_diameter_m") or estimate.get("outer_diameter"))
        if diameter is not None:
            basis_label = {
                DN_ENVELOPE_BASIS: "公称直径 DN",
                "explicit_outer_construction_envelope": "相邻涵施工外径",
            }.get(estimate.get("diameter_basis"))
            parts.append(f"施工包络直径 {diameter:g} m" + (f"（{basis_label}）" if basis_label else ""))
    else:
        for key, label in (("inner_width", "净宽"), ("inner_height", "净高")):
            value = _number(estimate.get(key))
            if value is not None:
                parts.append(f"{label} {value:g} m")
    return "，".join(filter(None, parts))


def building_label(row, category, *, name=None, duplicate=False):
    name=str(name or row.get("name") or row.get("asset_name") or "").strip()
    placeholder=name in {"","-","—","/","未命名"}
    if placeholder:name=category
    if flow_section := str(row.get("flow_section") or "").strip():
        name += f"（流量段 {flow_section}）"
    start,end=_number(row.get("station_start")),_number(row.get("station_end"))
    if (placeholder or duplicate) and start is not None and end is not None:
        name+=f" {station_label(start)}～{station_label(end)}"
    return name


def section_quantity_labels(section, asset=None):
    """Show measured area/length only; construction parameters stay in the project."""
    asset = asset or {}
    labels = []
    for role, name in (("excavation", "天然开挖"), ("backfill", "周边回填"),
                       ("embankment", "新增填筑")):
        value = _number((section.get("roles", {}).get(role) or {}).get("area"))
        if value is not None and value > 1e-9:
            labels.append(f"{name}{value:.2f}m2")
    components = section.get("quantity_components") or []
    component_ids = {item.get("component_id") for item in components}
    for item in components:
        value = _number(item.get("section_measure"))
        if value is None or value <= 1e-9:
            continue
        unit = {"m3": "m2", "m2": "m"}.get(item.get("unit"), UNITS.get(item.get("unit"), item.get("unit", "")))
        labels.append(f"{_item_name(item,asset)}{value:.2f}{unit}")
    for role, name in (("concrete", "结构混凝土"), ("bedding", "垫层")):
        if role in component_ids:
            continue
        value = _number(section.get("material_areas", {}).get(role))
        if value is not None and value > 1e-9:
            if role == "bedding" and (asset.get("construction", {}).get("pipe_seat") or {}).get("material_role") == "bedding":
                name = "砂垫层"
            labels.append(f"{name}{value:.2f}m2")
    return ["；".join(labels[index:index + 2]) for index in range(0, len(labels), 2)]


def quantity_records(payload):
    """One row per measured project and unit; never add material subtotals twice."""
    from ..services.structure_quantities import _Classifier

    classifier = _Classifier(payload)
    rows = payload.get("rows", payload.get("assets", [])) or []
    by_id = defaultdict(list)
    for row in rows:
        by_id[str(row.get("asset_id", ""))].append(row)
    names=defaultdict(int)
    for row in rows:
        names[str(row.get("name") or "")]+=1
    items = payload.get("quantity_items")
    if items is None:
        items = [{"asset_id": row.get("asset_id"), "asset_name": row.get("name"), **item}
                 for row in rows for item in row.get("quantity_items", [])]
    items = items or []
    components = defaultdict(set)
    for item in items:
        components[str(item.get("asset_id", ""))].add(item.get("component_id"))
    records = []

    def append(row, project, unit, value, name=None):
        category=row.get("construction_method") or classifier.category(row)
        display=building_label(row,category,name=name,duplicate=names[str(row.get("name") or "")]>1)
        records.append([display,category,project,unit,_number(value)])

    earthwork = earthwork_columns(payload)
    split_keys = {key for key, _ in BACKFILL_SPLIT_COLUMNS}
    for row in rows:
        for key, label in earthwork:
            if key in row and (key not in split_keys or row[key] is not None):
                append(row, label, "m³", row.get(key))
        for key, label in (("overburden_volume", "覆盖层开挖"), ("bedrock_volume", "基岩开挖"),
                           ("unclassified_excavation_volume", "未分层开挖")):
            if key in row:
                append(row, label, "m³", row.get(key))
        for role, label in (("concrete", "结构混凝土"), ("bedding", "垫层")):
            key = role + "_volume"
            if row.get("material_quantity_basis") == "soil_geometry_reference":
                continue
            if role not in components[str(row.get("asset_id", ""))] and key in row:
                if _number(row.get(key))==0:continue
                asset=classifier._lookup(row,classifier.inputs) or row
                label=_item_name({"name":label,"component_id":role},asset)
                append(row, label, "m³", row.get(key))

    for item in items:
        candidates = by_id.get(str(item.get("asset_id", "")), [])
        route = item.get("route_id")
        matching = [row for row in candidates if not row.get("route_id") or row.get("route_id") == route] if route else candidates
        row = matching[0] if len(matching) == 1 else item
        if _number(item.get("quantity"))==0:continue
        asset=classifier._lookup(row,classifier.inputs) or row
        append(row, _item_name(item,asset), UNITS.get(item.get("unit"), item.get("unit", "")),
               item.get("quantity"), name=item.get("asset_name"))
    for item in payload.get("trenchless_excavation_rows", []):
        append(item, "非开挖洞挖", "m³", item.get("trenchless_excavation_volume"))
    # Engineering diagnostics retain missing scope and excluded construction
    # spans. This schedule lists actual measured projects; an explicitly
    # requested bore with missing diameter remains blank in the bore row above.
    return records


def _adoption_tables(payload):
    """Record selected ways of completing source gaps beside measured quantities."""
    workbench = (payload.get("inputs") or {}).get("workbench") or {}
    candidates = [item for item in workbench.get("transition_candidates", []) if item.get("source_kind")]
    networks = workbench.get("networks", [])
    siphons = [(network, asset) for network in networks for asset in network.get("assets", [])
               if "siphon_axis_choice" in asset or "siphon_axis_input" in asset]
    pending = payload.get("calculation_deferred_assets") or []
    if not candidates and not siphons and not pending:
        return []

    earthwork = earthwork_columns(payload)
    assets = {asset["asset_id"]: asset for network in networks for asset in network.get("assets", [])}
    measured = defaultdict(list)
    for row in payload.get("rows", payload.get("assets", [])):
        measured[row.get("original_asset_id") or row.get("asset_id")].append(row)
    exclusions = defaultdict(list)
    for row in payload.get("excluded_assets", []):
        exclusions[row.get("original_asset_id") or row.get("asset_id")].append(row)

    def measured_state(ids, *, estimated=False, enabled=True):
        rows = [row for aid in ids for row in measured[aid]]
        omitted = [row for aid in ids for row in exclusions[aid]]
        reasons = "；".join(dict.fromkeys(row["reason"] for row in omitted if row.get("reason")))
        status = "未纳入" if not enabled else "待计"
        if rows:
            status = "估算已计" if estimated else "已计"
            if omitted or any(not measured[aid] for aid in ids):
                status = "估算部分已计" if estimated else "部分已计"
        quantities = [math.fsum(row[key] for row in rows) if rows and all(row.get(key) is not None for row in rows)
                      else None for key, _ in earthwork]
        return status, reasons, quantities

    tables = []
    if siphons:
        from ..services.siphon_axis_choices import describe_siphon_axis

        alignment_modes = {"auto": "自动", "exact": "原桩号", "align_start": "对齐起点",
                           "align_end": "对齐终点", "cover_depth": "管顶覆土", "pending": "待补轴线",
                           "source_chainage": "按原桩号", "matching_length": "等长平移", "manual_offset": "按指定起桩"}
        rows = []
        for network, asset in siphons:
            report = describe_siphon_axis(asset)
            use_cover = report["status"] in {"cover_estimate", "cover_generated"}
            route = (network.get("source_route_name") or network.get("name") or network.get("network_id"))
            status, reasons, quantities = measured_state([asset["asset_id"]], estimated=use_cover,
                                                          enabled=asset.get("enabled", True))
            adjustment = report.get("adjustment") or {}
            strategy = adjustment.get("strategy")
            note = "；".join(dict.fromkeys(filter(None, (report.get("message"), reasons))))
            rows.append([route, building_label(asset, "倒虹吸"), asset.get("station_start"),
                         asset.get("station_end"), alignment_modes.get(report.get("mode"), report.get("mode")),
                         "地形推算轴线" if use_cover else report.get("source_label"),
                         report.get("cover_depth_m") if use_cover else None,
                         report.get("length_difference_m"), alignment_modes.get(strategy, strategy),
                         adjustment.get("station_offset_m"), status, *quantities, note])
        tables.append(("倒虹吸纵断面", ["线路", "建筑物", "起桩 m", "终桩 m", "设置", "采用依据", "管顶覆土 m",
                                     "轴线与区段长度差 m", "对齐处理", "桩号平移 m", "计量状态",
                                     *[name + " m³" for _, name in earthwork], "处理说明"], rows))

    if candidates:
        structures = {"circular_channel": "圆形明渠", "u_channel": "U形明渠", "rectangular_channel": "矩形明渠",
                      "trapezoidal_channel": "梯形明渠", "compound_trapezoidal_channel": "复式梯形明渠",
                      "rectangular_culvert": "矩形暗涵", "circular_culvert": "圆管涵", "arch_culvert": "拱形暗涵"}
        fill_modes = {"cover_above_terrain": "覆土填筑", "restore_terrain": "回填至原地面"}
        estimates = {item["asset_id"]: item for item in workbench.get("connector_estimates") or []}
        rows = []
        for candidate in candidates:
            ids = candidate.get("asset_ids") or candidate.get("estimated_asset_ids") or [candidate.get("asset_id")]
            ids = list(dict.fromkeys(aid for aid in ids if aid))
            installed = [assets[aid] for aid in ids if aid in assets]
            status, reasons, quantities = measured_state(ids, estimated=candidate.get("status") == "estimated",
                                                          enabled=not installed or any(a.get("enabled", True) for a in installed))
            current = installed[0] if len(installed) == 1 else {}
            construction = current.get("construction") or candidate.get("adopted_construction") or {}
            profile = candidate.get("adopted_profile") or candidate.get("profile") or {}
            shape = current.get("section_type") or candidate.get("adopted_section_type")
            estimate_notes = [connection_estimate_note(estimates[aid]) for aid in ids if aid in estimates]
            note = "；".join(dict.fromkeys(filter(None, (*estimate_notes, profile.get("basis"),
                                                        *(candidate.get("reasons") or []), reasons))))
            rows.append([candidate.get("name"), "缺少IP点" if candidate["source_kind"] == "missing_ip_gap" else "水面线渐变",
                         candidate.get("station_start"), candidate.get("station_end"), candidate.get("length_m"),
                         structures.get(shape, shape), fill_modes.get(construction.get("target_mode")),
                         construction.get("final_cover_depth"), construction.get("bank_slope_left"),
                         construction.get("bank_slope_right"), status, *quantities, note])
        tables.append(("连接段", ["建筑物", "来源", "起桩 m", "终桩 m", "长度 m", "采用断面", "回填方式",
                                  "涵顶覆土 m", "左填坡 1:m", "右填坡 1:m", "计量状态",
                                  *[name + " m³" for _, name in earthwork], "处理说明"], rows))

    if pending:
        route_names = {network.get("route_id") or network.get("network_id"):
                       network.get("source_route_name") or network.get("name") for network in networks}
        rows = []
        for row in pending:
            route = row.get("route_id")
            start, end = row.get("station_start"), row.get("station_end")
            length = row.get("length_m")
            if length is None and start is not None and end is not None:
                length = end - start
            rows.append([route_names.get(route) or row.get("route_name") or route, row.get("name"),
                         start, end, length, row.get("reason") or "施工资料待核"])
        tables.append(("待计区段", ["线路", "建筑物", "起桩 m", "终桩 m", "长度 m", "处理说明"], rows))
    return tables


def _compact_trenchless_table(payload, channel_name):
    from .structure_quantity_tables import trenchless_diameter_label, trenchless_excavation_table

    title, _, details = trenchless_excavation_table(payload, channel_name=channel_name)
    headers = ["线路", "建筑物", "施工方式", "起桩m", "终桩m", "计量长度m", "洞挖量m³",
               trenchless_diameter_label(payload) + "m", "洞径m", "洞面积m²", "长度依据"]
    rows = []
    notes = []
    for line, _asset_id, name, method, start, end, pipe, bore, area, length, basis, volume, status, issue in details:
        rows.append([line or channel_name or "未命名线路", name or method, method, start, end, length, volume,
                     pipe, bore, area, basis])
        note = issue
        if status == "待补资料":
            note = f"{status}：{issue}" if issue else status
        notes.append(note)
    if any(notes):
        headers.append("计量说明")
        for row, note in zip(rows, notes):
            row.append(note)
    return title, headers, rows


def _write_quantity_block(sheet, headers, rows, *, header_row=1):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    sheet.row_dimensions[header_row].height = 28
    for index, header in enumerate(headers, 1):
        cell = sheet.cell(header_row, index, header)
        cell.font = Font(name="微软雅黑", bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="234E70")
        cell.alignment = Alignment(vertical="center", wrap_text=True if header_row > 1 else None)
        width = {
            "建筑物": 38, "结构形式": 28, "项目": 34, "单位": 10, "数量": 20, "线路": 24,
            "长度依据": 26, "采用依据": 34, "处理说明": 52, "计量说明": 34,
        }.get(header, 17)
        dimension = sheet.column_dimensions[cell.column_letter]
        dimension.width = width if header_row == 1 else max(width, dimension.width)

    split_labels = {label for _, label in BACKFILL_SPLIT_COLUMNS}
    for row_number, values in enumerate(rows, header_row + 1):
        line_count = 1
        for index, (header, value) in enumerate(zip(headers, values), 1):
            cell = sheet.cell(row_number, index, value)
            if isinstance(value, str):
                # Imported names must be stored as text even when they start with '='.
                cell.data_type = "s"
                width = max(1., sheet.column_dimensions[cell.column_letter].width - 2.)
                wrapped = sum(max(1, math.ceil(sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
                                                  for char in paragraph) / width))
                              for paragraph in value.split("\n"))
                line_count = max(line_count, wrapped)
            cell.font = Font(name="微软雅黑", size=11)
            quantity_part = header == "项目" and value in split_labels
            cell.alignment = Alignment(vertical="center", wrap_text=True, indent=1 if quantity_part else 0)
            cell.border = Border(bottom=Side(style="hair", color="DCE6EF"))
            if isinstance(value, (float, int)):
                cell.number_format = "#,##0.000" if header.endswith(("m", "m²", " 1:m")) else "#,##0.00"
            if row_number % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="F1F6FA")
        sheet.row_dimensions[row_number].height = max(22., 16. * line_count + 2.)


def _append_trenchless_block(sheet, summary_rows, detail_table):
    from openpyxl.styles import Alignment, Font

    title, headers, rows = detail_table
    width = max(sheet.max_column, len(headers))
    title_row = sheet.max_row + 2
    cell = sheet.cell(title_row, 1, title)
    cell.font = Font(name="微软雅黑", size=11, bold=True, color="234E70")
    cell.alignment = Alignment(vertical="center")
    sheet.row_dimensions[title_row].height = 24
    _write_quantity_block(sheet, headers, rows, header_row=title_row + 1)
    sheet.print_title_rows = None
    # Verify the complete sheet, including the two different table widths.
    return [row + [None] * (width - len(row)) for row in [*summary_rows, [], [title], headers, *rows]]


def save_concise_xlsx(payload, path, *, channel_name=""):
    """Save and reopen a quantity-only workbook used by all production exports."""
    from filesystem_paths import filesystem_path
    from openpyxl import Workbook, load_workbook
    from .structure_quantity_tables import (
        remaining_exclusion_table, structure_tables, style_structure_tables, trenchless_summary_columns,
    )
    from .unsupported_range_tables import append_range_sheets, cache_range_totals, verify_range_sheets
    from .workbench_drawings import _verify_table, layered_volume_columns

    path = filesystem_path(path, extended=True)
    records = quantity_records(payload)
    grouped = {}
    for _name, category, project, unit, value in records:
        grouped.setdefault((category, project, unit), []).append(value)
    summary = [[category, project, unit,
                math.fsum(values) if all(value is not None for value in values) else None]
               for (category, project, unit), values in grouped.items()]
    summary.extend(["合计", label, "m³", _number(payload.get(key))]
                   for key, label in trenchless_summary_columns(payload))
    wb = Workbook()
    wb.remove(wb.active)
    classification_tables = []
    if payload.get("rows", payload.get("assets", [])):
        classification_tables = structure_tables(payload, layered_volume_columns(payload), include_details=False)
    trenchless = _compact_trenchless_table(payload, channel_name)
    detail_tables = [remaining_exclusion_table(payload, channel_name=channel_name)]
    if not classification_tables:
        detail_tables.insert(0, trenchless)
    adoption_tables = _adoption_tables(payload)
    tables = [("结构形式汇总", ["结构形式", "项目", "单位", "数量"], summary),
              ("分建筑物工程量", ["建筑物", "结构形式", "项目", "单位", "数量"], records),
              *classification_tables, *(table for table in detail_tables if table[2]),
              *adoption_tables]
    for title, headers, rows in tables:
        sheet = wb.create_sheet(title)
        _write_quantity_block(sheet, headers, rows)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        sheet.sheet_view.showGridLines = False
        sheet.print_title_rows = "1:1"
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
    style_structure_tables(wb, classification_tables)
    expected = {title: rows for title, _, rows in tables}
    if classification_tables and trenchless[2]:
        title, _, summary_rows = classification_tables[0]
        expected[title] = _append_trenchless_block(wb[title], summary_rows, trenchless)
    range_tables = append_range_sheets(wb, payload, channel_name=channel_name)
    wb.save(path)
    cache_range_totals(path, range_tables)
    saved = load_workbook(path, read_only=True, data_only=True)
    try:
        for title, rows in expected.items():
            _verify_table(saved, title, rows)
        range_audit = verify_range_sheets(saved, path, range_tables)
    finally:
        saved.close()
    return {"saved_reopened": True, "numeric_quantities_verified": True,
            "concise": True, "quantity_record_count": len(records),
            "structure_summary_count": len(summary), "structure_totals_verified": True,
            "section_count": len(payload.get("sections", [])),
            "segment_count": len(payload.get("segments", [])), **range_audit,
            **({"adoption_sheets": {title: len(rows) for title, _, rows in adoption_tables}} if adoption_tables else {})}
