"""Evidence-gated mapping of the reviewed Mapeng drawing K stations.

This infers only an identity between source MC chainage and current true plan
arclength. It never reprojects an IP chord chainage, edits an asset, resolves a
conflicting drawing row, or treats a UI confirmation as geometric evidence.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re

from .engineering_drawings import DrawingLibraryError, load_catalog


MAPPING_CONTRACT = "mapeng_source_MC_identity_v1"
_MC_TOLERANCE = .001
_DRAWING_TOLERANCE = .01
_MINIMUM_ANCHORS = 8
_MINIMUM_ANCHOR_SPAN = 3000.


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None


def _table_rows(drawing):
    rows = []
    for fact in drawing.get("facts", []):
        values = fact.get("value")
        if isinstance(values, list):
            rows.extend(deepcopy(row) for row in values
                        if isinstance(row, dict) and "station_text" in row and "parsed_station_m" in row)
    return rows


def _scope_rows(rows, assets):
    safe, blocked = [], []
    for original in rows:
        row = deepcopy(original)
        bounds = row.get("parsed_station_m") or []
        if (row.get("status") != "verified_source" or len(bounds) != 2 or
                any(_number(v) is None for v in bounds) or bounds[1] <= bounds[0] or
                "二道" in row.get("station_text", "")):
            row.update(binding_status="blocked_source_conflict",
                       reason="原图线路前缀或起止桩号冲突，不能根据表长猜测终点")
            blocked.append(row)
            continue
        start, end = map(float, bounds)
        overlaps = []
        for asset in assets:
            a, b = _number(asset.get("station_start")), _number(asset.get("station_end"))
            if a is None or b is None:
                continue
            left, right = max(start, a), min(end, b)
            if right > left+1e-8:
                overlaps.append({"asset_id": asset.get("asset_id"),
                                 "source_identity": deepcopy(asset.get("source_identity")),
                                 "section_type": asset.get("section_type"),
                                 "station_start": left, "station_end": right,
                                 "length_m": right-left})
        row.update(station_start=start, station_end=end, overlapping_assets=overlaps)
        cursor, continuous = start, bool(overlaps)
        for part in sorted(overlaps, key=lambda part: part["station_start"]):
            if abs(part["station_start"]-cursor) > 1e-6:
                continuous = False
            cursor = part["station_end"]
        if not continuous or abs(cursor-end) > 1e-6 or any(p["section_type"] != "u_channel" for p in overlaps):
            row.update(binding_status="blocked_current_structure_conflict",
                       reason="原图U形区段与当前结构类型或完整覆盖范围冲突，不能静默截短或换型")
            blocked.append(row)
        else:
            row["binding_status"] = "scope_consistent"
            safe.append(row)
    return safe, blocked


def infer_drawing_station_mapping(inputs):
    """Return auditable confirmation only for the reviewed matching Mapeng route.

    Pending is a normal result. Manual checkboxes and stale stored mapping
    claims are deliberately ignored; every call rechecks the actual records.
    """
    result = {"contract": MAPPING_CONTRACT, "confirmed": False, "status": "pending",
              "mapping_kind": None, "reasons": [], "anchors": [],
              "safe_ranges": [], "blocked_ranges": [],
              "limitations": ["只确认本工程原K米值与当前真实平面弧长的恒等关系，不确认地质、施工左右侧或全部构造",
                              "全填方膜适用范围存在原图说明与图示歧义，映射通过不代表膜范围已确认",
                              "来源、当前轴线、断面类型或图纸资源变化后，必须重新推断映射和适用范围"]}
    def pending(reason):
        result["reasons"].append(reason)
        return result
    if not isinstance(inputs, dict):
        return pending("缺少可核对的当前工程输入")
    design = inputs.get("design_source") or {}
    if not isinstance(design, dict):
        return pending("缺少可核对的水面线来源记录")
    provenance = design.get("water_profile_provenance") or {}
    if not isinstance(provenance, dict):
        return pending("缺少可核对的水面线来源记录")
    case_name = str(inputs.get("case_name") or inputs.get("project_name") or "")
    if ("马鹏支渠" not in case_name or provenance.get("channel_name") not in {"马鹏", "马鹏支渠"} or
            provenance.get("channel_level") != "支渠"):
        return pending("当前工程名与水面线来源未同时明确指向马鹏支渠")
    sources = {"hydraulic_project_sha256": design.get("hydraulic_project_sha256"),
               "source_workbook_sha256": design.get("workbook_sha256"),
               "provenance_source_sha256": provenance.get("source_sha256")}
    if not all(_sha(value) for value in sources.values()) or sources["source_workbook_sha256"] != sources["provenance_source_sha256"]:
        return pending("水面线工程、原表及来源摘要缺失或相互不符")
    networks = inputs.get("networks") or []
    if not isinstance(networks, list) or len(networks) != 1 or not isinstance(networks[0], dict):
        return pending("本规则只确认单一明确马鹏线路，当前网络范围不唯一")
    network = networks[0]
    if network.get("source_identity") != "water_profile" or (network.get("source") or {}).get("kind") != "water_profile_panel":
        return pending("当前线路缺少来自水面线成果的稳定身份")
    alignment = network.get("alignment") or {}
    if not isinstance(alignment, dict) or alignment.get("station_basis") != "true_plan_arclength":
        return pending("当前线路不是可核对的真实平面弧长快照")
    assets, ips = network.get("assets") or [], alignment.get("ip_points") or []
    if not assets or not ips:
        return pending("缺少当前线路节点或原水面线记录")
    source_rows, route_rows = {}, {}
    fields = ("station_ip", "station_BC", "station_MC", "station_EC")
    for asset in assets:
        for record in (asset.get("original_fields") or {}).get("records", []):
            key = record.get("profile_row_id")
            values = {name: _number(record.get(name)) for name in fields}
            if not key or any(value is None for value in values.values()):
                return pending("原水面线记录缺少稳定行身份或有效BC/MC/EC桩号")
            if key in source_rows and source_rows[key] != values:
                return pending("同一来源行出现互相矛盾的桩号记录")
            source_rows[key] = values
    for point in ips:
        key, station = point.get("profile_row_id"), _number(point.get("route_station"))
        if not key or station is None or key in route_rows:
            return pending("当前线路节点缺少唯一来源行身份或实际里程")
        route_rows[key] = station
    if set(source_rows) != set(route_rows) or len(source_rows) < _MINIMUM_ANCHORS:
        return pending("原水面线节点与实际线路节点身份未一一对应")
    checks = [{"profile_row_id": key, "source_station_MC": values["station_MC"],
               "actual_route_station": route_rows[key], "difference_m": route_rows[key]-values["station_MC"]}
              for key, values in source_rows.items()]
    maximum = max(abs(check["difference_m"]) for check in checks)
    result.update(network_id=network.get("network_id"), source_hashes=sources,
                  source_MC_max_difference_m=maximum, source_record_count=len(checks), source_MC_checks=checks)
    if maximum >= _MC_TOLERANCE:
        return pending("原MC桩号与当前真实里程差达到1mm，不能采用恒等映射")
    try:
        catalog = load_catalog()
        drawing = next(row for row in catalog["drawings"] if row.get("drawing_id") == "mp")
    except (DrawingLibraryError, StopIteration, KeyError, TypeError) as error:
        return pending("马鹏图纸编译依据不可用："+str(error))
    rows = _table_rows(drawing)
    if not rows or not _sha(drawing.get("sha256")):
        return pending("缺少经审阅的马鹏图纸桩号表或原图摘要")
    result["source_hashes"].update(drawing_sha256=drawing["sha256"], drawing_catalog_sha256=_hash(drawing))
    known = [(value, key, name) for key, values in source_rows.items()
             for name, value in values.items() if name != "station_ip"]
    endpoint_hits = {}
    for row in rows:
        if row.get("status") != "verified_source":
            continue
        for station in row["parsed_station_m"]:
            value, key, field = min(known, key=lambda item: abs(item[0]-station))
            if abs(value-station) <= _DRAWING_TOLERANCE:
                endpoint_hits[station] = {"drawing_station_m": station, "source_station_m": value,
                    "profile_row_id": key, "source_station_field": field, "difference_m": station-value,
                    "source_handle": row.get("station_handle")}
    anchors = sorted(endpoint_hits.values(), key=lambda item: item["drawing_station_m"])
    result["anchors"] = anchors
    if len(anchors) < _MINIMUM_ANCHORS or anchors[-1]["drawing_station_m"]-anchors[0]["drawing_station_m"] < _MINIMUM_ANCHOR_SPAN:
        return pending("图纸端点与当前来源BC/MC/EC的分散锚点不足，不能仅凭同名或同桩号确认")
    end = _number(alignment.get("end_station"))
    start = _number(alignment.get("start_station"))
    if start is None or abs(start) > _DRAWING_TOLERANCE or end is None or abs(end-6909.82) > _DRAWING_TOLERANCE:
        return pending("当前全线起终桩与已核对马鹏图纸0～6+909.82不符")
    elements = alignment.get("elements") or []
    cursor = start
    for element in elements:
        a, b, length = (_number(element.get(key)) for key in ("station_start", "station_end", "length"))
        if any(v is None for v in (a, b, length)) or abs(a-cursor) > 1e-6 or b <= a or abs(b-a-length) > 1e-6:
            return pending("当前真实轴线存在断链或长度矛盾")
        cursor = b
    if not elements or abs(cursor-end) > 1e-6 or abs(max(route_rows.values())-end) > _MC_TOLERANCE:
        return pending("全线轴线末端与节点实际里程未闭合")
    safe, blocked = _scope_rows(rows, assets)
    result.update(confirmed=True, status="confirmed", mapping_kind="identity_source_MC",
                  station_scale=1., station_offset_m=0., drawing_station_end_m=6909.82,
                  actual_station_end_m=end, source_MC_tolerance_m=_MC_TOLERANCE,
                  drawing_anchor_tolerance_m=_DRAWING_TOLERANCE,
                  safe_ranges=safe, blocked_ranges=blocked,
                  source_snapshot_sha256=_hash({"network_id":network.get("network_id"), "alignment":alignment,
                      "source_rows":source_rows, "asset_ranges":[{key:asset.get(key) for key in
                      ("asset_id", "source_identity", "section_type", "station_start", "station_end")} for asset in assets],
                      "source_hashes":result["source_hashes"]}))
    return result
