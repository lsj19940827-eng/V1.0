"""Tabular views of measured earthwork, grouped by original structure form."""
from __future__ import annotations

import csv
import math

from ..services.structure_quantities import classified_earthwork
from ..services.earthwork_scope import NOMINAL_TRENCHLESS_EXCAVATION_RULE, TRENCHLESS_EXCAVATION_RULE


BACKFILL_SPLIT_COLUMNS = (
    ("manual_backfill_volume", "土石回填"),
    ("mechanical_backfill_volume", "土石填筑"),
)
CLASSIFICATION_NOTE = (
    "按原始结构形式归类；明渠按断面类型分别列项，圆形按圆管涵列项；"
    "暗渠、倒虹吸、有压管道、渡槽、隧洞及自动估算连接段分别汇总。附属基础土方随所属结构归类；"
    "未识别结构单列其他结构，不漏计。仅汇总已计对象，未计对象不按零量理解。"
    "计量长度为各对象（含基础）计算范围长度之和，不代表去重后的线路长度。"
    "基础起止位置为局部剖切位置。"
)
_TRENCHLESS_QUANTITY_NOTE = (
    "定向钻及顶管按单个圆孔计量，洞径＝{diameter}＋2×0.20m，洞挖量＝圆孔面积×计量长度。"
    "明挖、周边回填及新增填筑分别按原口径统计。"
)


def trenchless_quantity_note(payload):
    if payload.get("trenchless_excavation_policy") == TRENCHLESS_EXCAVATION_RULE:
        return ("定向钻及顶管按单个圆孔计量。开挖直径自动取公称直径＋2×每侧预留（默认每侧0.20m），"
                "有手填值时采用本段手填的开挖直径。洞挖量＝圆孔面积×计量长度。")
    return _TRENCHLESS_QUANTITY_NOTE.format(diameter=trenchless_diameter_label(payload))


def trenchless_diameter_label(payload):
    return "公称直径" if payload.get("trenchless_excavation_policy") in (
        NOMINAL_TRENCHLESS_EXCAVATION_RULE, TRENCHLESS_EXCAVATION_RULE) else "管径"


def trenchless_summary_columns(payload):
    if not payload.get("trenchless_excavation_rows"):
        return []
    bore_label = "非开挖洞挖量" if payload.get("trenchless_excavation_complete") else "已计非开挖洞挖量"
    total_label = "本次已计挖方（含洞挖）" if payload.get("calculation_deferred_assets") else "合计挖方（含洞挖）"
    return [("trenchless_excavation_volume", bore_label), ("total_excavation_volume", total_label)]


def trenchless_excavation_table(payload, *, channel_name=""):
    title = "非开挖洞挖明细"
    diameter_label = trenchless_diameter_label(payload) + "m"
    headers = ["线路", "对象编号", "名称", "施工方式", "起点m", "终点m", diameter_label, "洞径m", "洞面积m²",
               "计量长度m", "长度依据", "洞挖量m³", "计量状态", "说明"]
    length_basis = {"plan_chainage": "平面桩号差", "design_profile_spatial": "设计纵断面空间长度"}
    rows = []
    for item in payload.get("trenchless_excavation_rows", []):
        basis = item.get("length_basis")
        measured = item.get("trenchless_excavation_volume") is not None
        rows.append([_route_name(payload, item, channel_name=channel_name), item.get("asset_id"), item.get("name"), item.get("construction_method"),
                     item.get("station_start"), item.get("station_end"), item.get("pipe_diameter_m"),
                     item.get("bore_diameter_m"), item.get("bore_area_m2"), item.get("length_m"),
                     length_basis.get(basis, basis), item.get("trenchless_excavation_volume"),
                     "已计" if measured else "待补资料", item.get("issue")])
    return title, headers, rows


def trenchless_csv_rows(payload, *, include_summary=False):
    title, headers, rows = trenchless_excavation_table(payload)
    if not rows:
        return []
    summary = [[label + "m³", payload.get(key)] for key, label in trenchless_summary_columns(payload)] if include_summary else []
    return [*summary, [title, trenchless_quantity_note(payload)], headers, *rows, []]


def exclusion_label(payload):
    return "未计明挖对象" if payload.get("trenchless_excavation_volume") is not None else "未计对象"


def remaining_exclusion_table(payload, *, channel_name=""):
    """Keep exclusions that have no dedicated schedule in the quantity workbook."""
    from ..services.earthwork_scope import is_trenchless_exclusion
    from ..services.unmeasured_terrain_scope import AUTOMATIC_TERRAIN_GAP_CODE
    from ..services.unsupported_pipe_scope import AUTOMATIC_UNSUPPORTED_PIPE_CODE

    scheduled_codes = {AUTOMATIC_TERRAIN_GAP_CODE, AUTOMATIC_UNSUPPORTED_PIPE_CODE}
    pending = payload.get("calculation_deferred_assets") or []
    has_bores = bool(payload.get("trenchless_excavation_rows"))
    rows = [
        [_route_name(payload, item, channel_name=channel_name), item.get("name") or item.get("asset_id"),
         item.get("station_start"), item.get("station_end"), item.get("reason")]
        for item in payload.get("excluded_assets", [])
        if item.get("code") not in scheduled_codes and item not in pending
        and not (has_bores and is_trenchless_exclusion(item))
    ]
    return "未计对象", ["线路", "建筑物", "起桩 m", "终桩 m", "处理说明"], rows


def _sum(values):
    numbers = [float(value) for value in values
               if isinstance(value, (int, float)) and not isinstance(value, bool)
               and math.isfinite(value)]
    return math.fsum(numbers) if numbers else None


def earthwork_columns(payload):
    rows = payload.get("rows", payload.get("assets", [])) or []
    has_split = any(row.get(key) is not None for row in rows for key, _ in BACKFILL_SPLIT_COLUMNS)
    return [
        ("excavation_volume", "天然开挖"),
        ("backfill_volume", "周边回填合计" if has_split else "周边回填"),
        *(BACKFILL_SPLIT_COLUMNS if has_split else ()),
        ("embankment_volume", "新增填筑"),
    ]


def _length(row):
    if row.get("length") is not None:
        return row["length"]
    if row.get("station_start") is not None and row.get("station_end") is not None:
        return row["station_end"] - row["station_start"]
    return None


def _route_name(payload, row, *, channel_name=""):
    route = row.get("parent_route_id") if row.get("generated_aqueduct_foundation") else None
    route = route or row.get("route_id") or row.get("network_id") or ""
    if route == "water_profile" and channel_name and channel_name != route:
        return channel_name
    explicit_name = row.get("route_name") or row.get("network_name")
    if explicit_name and explicit_name != route:
        return explicit_name
    inputs = payload.get("inputs") or {}
    work = inputs.get("workbench") or inputs.get("workbench_inputs") or {}
    networks = ([inputs["network"]] if inputs.get("network") else []) + list(work.get("networks") or ())
    exact = [network for network in networks if route and any(
        identity is not None and str(identity) == str(route)
        for identity in (network.get("route_id"), network.get("network_id") or network.get("name")))]
    candidates = exact or [network for network in networks if route and network.get("source_identity") == route]
    names = {network.get("source_route_name") or network.get("name") or network.get("network_name")
             for network in candidates} - {None, "", route}

    if route == "water_profile":
        # Older exports can use the panel key while the network has a generated ID.
        names.discard("当前渠道工程")
        if len(names) == 1:
            return names.pop()
        project_name = work.get("project_name")
        return project_name if project_name and project_name != route else "当前渠道工程"
    if isinstance(route, str) and route.startswith("pressure_route:"):
        # A route with only trenchless spans may survive only in the exclusions.
        names.discard(route.removeprefix("pressure_route:"))
        for item in payload.get("excluded_assets") or work.get("excluded") or ():
            if item.get("route_id") == route:
                display = item.get("route_display_name") or (item.get("original_asset_snapshot") or {}).get("route_display_name")
                if display and display != route:
                    names.add(display)
        return names.pop() if len(names) == 1 else "有压管道线路"
    if len(names) == 1:
        return names.pop()
    return "独立基坑" if route == "independent_pits" else route


def structure_tables(payload, layer_columns=(), *, include_details=True):
    """Return the summary and optional detail tables per measured category.

    All quantities come from saved result rows. Materials and drawings have
    their own schedules and are deliberately outside these earthwork totals.
    """
    columns = [(key, name + "m³") for key, name in
               (*earthwork_columns(payload), ("total_fill_volume", "总填方"), *layer_columns)]
    groups = classified_earthwork(payload, columns)
    keys = [key for key, _ in columns]
    summary_rows = [[group["category"], group["asset_count"], group["length"],
                     *[group["totals"][key] for key in keys]] for group in groups]
    total="本次已计合计" if payload.get("calculation_deferred_assets") else "全线合计"
    summary_rows.append([total, sum(group["asset_count"] for group in groups),
                         _sum(group["length"] for group in groups),
                         *[_sum(group["totals"][key] for group in groups) for key in keys]])
    tables = [("结构分类汇总", ["结构分类", "区段数", "计量长度m", *[name for _, name in columns]], summary_rows)]
    if include_details:
        headers = ["线路", "对象", "名称", "起点m", "终点m", "计量长度m", *[name for _, name in columns]]
        for group in groups:
            records = [[_route_name(payload, row), row.get("asset_id", ""),
                        row.get("name", ""), row.get("station_start"), row.get("station_end"), _length(row),
                        *[row.get(key) for key in keys]] for row in group["rows"]]
            records.append(["本类小计", None, None, None, None, group["length"],
                            *[group["totals"][key] for key in keys]])
            tables.append((group["category"], headers, records))
    # Every saved result row appears once, including unrecognised structures.
    source_rows = payload.get("rows", payload.get("assets", []))
    if sum(group["asset_count"] for group in groups) != len(source_rows):
        raise ValueError("结构分类条目数与原分项工程量不一致")
    for key in keys:
        original = _sum(row.get(key) for row in source_rows)
        classified = _sum(group["totals"][key] for group in groups)
        if original != classified and (original is None or classified is None or
                not math.isclose(original, classified, rel_tol=1e-12, abs_tol=1e-8)):
            raise ValueError("结构分类汇总与原分项工程量不一致：" + key)
    return tables


def style_structure_tables(workbook, tables):
    from openpyxl.styles import Alignment, Font, PatternFill

    for name, _, _ in tables:
        sheet = workbook[name]
        sheet.row_dimensions[1].height = 32
        for cell in sheet[1]:
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        for cell in sheet[sheet.max_row]:
            cell.fill = PatternFill("solid", fgColor="E2ECF5")
            cell.font = Font(bold=True, color="234E70")
        sheet.column_dimensions["A"].width = 29 if name == "结构分类汇总" else 24
        if name == "结构分类汇总":
            for cell in sheet["B"][1:]:
                cell.number_format = "0"
        else:
            sheet.column_dimensions["B"].width = 30
            sheet.column_dimensions["C"].width = 30
        sheet.auto_filter.ref = f"A1:{sheet.cell(max(1, sheet.max_row - 1), sheet.max_column).coordinate}"


def save_structure_csv(payload, path):
    """Save a standalone classification summary and verify its actual bytes."""
    from .quantity_policy import overlap_policy_note
    from .workbench_drawings import layered_scope_note, layered_volume_columns, section_sampling_note

    name, headers, records = structure_tables(payload, layered_volume_columns(payload), include_details=False)[0]
    content = [
        ["TEST结构分类工程量" if payload.get("test_only") else name, "单位：m³；长度m"],
        ["输入摘要", payload.get("input_hash", "")],
        ["分类说明", CLASSIFICATION_NOTE],
        ["重叠计量口径", overlap_policy_note(payload)],
        ["断面间距与方法", section_sampling_note(payload)],
    ]
    layer_note = layered_scope_note(payload)
    if layer_note:
        content.append(["简化分层及计量范围", layer_note])
    from ..services.workbench_scope import deferred_scope_note
    if scope_note := deferred_scope_note(payload):
        content.append(["计量范围", scope_note])
    for item in payload.get("excluded_assets", []):
        row=[exclusion_label(payload), item.get("name", item.get("asset_id", "")), item.get("reason", "")]
        if item.get("scope_status")=="automatic_deferred":
            row.extend([item.get("route_id"),item.get("station_start"),item.get("station_end")])
        content.append(row)
    content.extend(trenchless_csv_rows(payload, include_summary=True))
    content.extend([[], headers, *records])
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream).writerows(content)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        saved = list(csv.reader(stream))
    expected = [["" if value is None else str(value) for value in row] for row in content]
    if saved != expected:
        raise ValueError("结构分类CSV保存回读不一致")
    return {"table": "structure_summary", "record_count": len(records) - 1,
            "saved_reopened": True, "saved_record_count_exact": True,
            "structure_totals_verified": True}
