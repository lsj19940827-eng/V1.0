"""Import main-project design facts into the section workbench as editable drafts.

No TEST construction defaults, inferred water-level axes, or chord replacements
are introduced. Missing data stays attached to its object and source identity.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

from 推求水面线.shared.section_lining import SECTION_SUMMARY_LINING_TYPES, gate_reference_lining, lining_number

from .source_adapters import _as_dict, adapt_profile_nodes
from ..services.construction_rules import normalize_asset_construction, normalize_construction_inputs
from ..services.pipe_dimensions import is_pipe_asset, mark_imported_pipe_diameter
from ..services.earthwork_scope import (
    is_trenchless_exclusion, trenchless_exclusion, trenchless_exclusions, trenchless_method,
    trenchless_source_nominal_diameter,
)
from ..services.network_alignment import NetworkAlignment, build_ip_alignment
from ..services.design_profiles import (
    normalize_design_profile, clip_design_profile, evaluate_profile,
    profile_break_stations, DesignProfileError,
)
from ..services.siphon_axis_choices import DEFAULT_SIPHON_COVER_M, configure_siphon_axis


TYPE_MAP = {"明渠-梯形": ("open_channel", "trapezoidal_channel"),
            "明渠-矩形": ("open_channel", "rectangular_channel"),
            "明渠-U形": ("open_channel", "u_channel"),
            "暗涵-矩形": ("culvert", "rectangular_culvert"),
            "暗涵-圆拱直墙型": ("culvert", "arch_culvert"),
            "暗涵-圆形": ("culvert", "circular_culvert"),
            "明渠-圆形": ("culvert", "circular_culvert"),
            "有压管道": ("pipe", "circular_culvert"),
            "倒虹吸": ("siphon", "circular_siphon"),
            "渡槽-U形": ("aqueduct", "aqueduct_u"),
            "渡槽-矩形": ("aqueduct", "aqueduct_rectangular"),
            "隧洞-圆形": ("tunnel", "circular_tunnel"),
            "隧洞-平底圆形": ("tunnel", "flat_bottom_tunnel"),
            "隧洞-圆拱直墙型": ("tunnel", "arch_tunnel"),
            "隧洞-马蹄形Ⅰ型": ("tunnel", "horseshoe_tunnel"),
            "隧洞-马蹄形Ⅱ型": ("tunnel", "horseshoe_tunnel")}

_FLOW_SECTION_TYPES = TYPE_MAP.keys() - {"有压管道"}
SOURCE_ROUTE_ENDPOINT_TOLERANCE_M = 1e-5


def _snap_route_endpoint(station, endpoint):
    if station is None or endpoint is None:
        return station
    value = _float(station, "来源桩号")
    if abs(value - endpoint) <= SOURCE_ROUTE_ENDPOINT_TOLERANCE_M:
        return endpoint
    return value


def _source_range_on_plan(start, end, alignment, *, records=None, source=None):
    adopted = [_snap_route_endpoint(start, alignment.start_station if alignment else None),
               _snap_route_endpoint(end, alignment.end_station if alignment else None)]
    if records is not None:
        for label, original, value in zip(("station_start", "station_end"), (start, end), adopted):
            if original is not None and value != original:
                records.append({"source": source, "field": label, "original_station_m": float(original),
                    "adopted_station_m": value, "difference_m": value - float(original),
                    "tolerance_m": SOURCE_ROUTE_ENDPOINT_TOLERANCE_M,
                    "basis": "仅归并真实平面路线起终点的微量桩号差，原始节点桩号保留"})
    return adopted


def _is_sluice_gate(source_type):
    return str(source_type or "").strip().endswith("闸")


def _deferred_pit(source_type):
    """New source imports defer foundations; saved historical inputs are untouched."""
    raw = str(source_type or "")
    normalized = raw.lower().replace("_", "").replace("-", "").replace(" ", "")
    return "闸" in raw or "基坑" in raw or normalized in {
        "boxfoundation", "pit", "rectangularpit", "foundation", "gatefoundation", "gate",
    }


def _exclude_pit(result, identity, name, source_type, original_fields, start=None, end=None):
    result["excluded"].append({
        "source_identity": identity, "name": name or source_type,
        "source_type": source_type, "station_start": start, "station_end": end,
        "reason": "首版暂不计算闸基及独立基坑土石方，原始设计字段保留供后续使用",
        "original_fields": deepcopy(original_fields),
    })


def _float(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}缺失或无效") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name}必须为有限值")
    return number


def _station(row):
    for key in ("station_MC", "station_mc", "chainage", "station", "route_station"):
        if row.get(key) is not None:
            try: return _float(row[key], key)
            except ValueError: return None
    return None


def _flow_section(row):
    from 推求水面线.core.connection_channel import flow_section_key

    return flow_section_key(row.get("flow_section"))


def crosses_legacy_flow_sections(asset):
    """Identify saved construction that predates flow-section grouping."""
    records = (asset.get("original_fields") or {}).get("records") or []
    return not asset.get("flow_section") and len({_flow_section(row) for row in records} - {""}) > 1


def flow_section_parameter_targets(inputs, old_owner, old_asset):
    """Map already-applied scope to unchanged source rows and plan geometry."""
    from ..services.transition_connections import _same_plan

    legacy = crosses_legacy_flow_sections(old_asset)
    old_flow_section = old_asset.get("flow_section")
    if (not legacy and not old_flow_section) or old_asset.get("source_type") not in _FLOW_SECTION_TYPES:
        return []
    start, end = old_asset.get("station_start"), old_asset.get("station_end")
    if start is None or end is None:
        return []
    prior_records = (old_asset.get("original_fields") or {}).get("records") or []
    prior_row_ids = {row.get("profile_row_id") for row in prior_records} - {None, ""}
    prior_route = old_owner.get("source_identity")
    prior_plan = old_owner.get("alignment")
    fields = ("name", "source_type", "section_type")
    scopes = set()
    for owner in inputs.get("networks", []):
        if not prior_route or owner.get("source_identity") != prior_route:
            continue
        route_match = owner.get("route_id") or owner.get("network_id")
        for asset in owner.get("assets", []):
            a, b = asset.get("station_start"), asset.get("station_end")
            if a is None or b is None or not asset.get("flow_section"):
                continue
            if any(asset.get(key) != old_asset.get(key) for key in fields):
                continue
            if legacy:
                records = (asset.get("original_fields") or {}).get("records") or []
                source_ids = {row.get("profile_row_id") for row in records}
                if not source_ids or not source_ids.issubset(prior_row_ids):
                    continue
            elif (asset["flow_section"] != old_flow_section or not old_asset.get("source_identity")
                  or asset.get("source_identity") != old_asset["source_identity"]):
                continue
            left, right = max(start, a), min(end, b)
            if right <= left + 1e-7 or not _same_plan(prior_plan, owner.get("alignment"), left, right):
                continue
            asset_root = (asset.get("section_scheme_root_asset_id") or asset.get("drawing_root_asset_id")
                          or asset.get("parent_asset_id") or asset["asset_id"])
            scopes.add((str(route_match), str(asset_root), left, right))
    sorted_scopes = sorted(scopes, key=lambda scope: (scope[2], scope[3]))
    if any(first[3] > second[2] + 1e-7 for first, second in zip(sorted_scopes, sorted_scopes[1:])):
        return []
    return sorted_scopes


def _batch_pipe_kind(value):
    from app_渠系计算前端.batch.schema import normalize_project_section_type

    raw_type = normalize_project_section_type(value)
    return (trenchless_method({"structure_type": raw_type}) or {}).get("method", raw_type)


def _batch_input_rows(project, panel):
    batch = panel.get("batch_panel_compat") or {}
    if not batch.get("input_rows"):
        batch = project.get("batch_panel") or {}
    from app_渠系计算前端.batch.schema import (
        _INPUT_HEADERS_BEFORE_RECT_CULVERT_VISIBLE_COLUMNS, _map_input_row_by_header_order,
    )

    headers = batch.get("input_header_order")
    for index, row in enumerate(batch.get("input_rows") or (), 3):
        if not isinstance(row, (list, tuple)):
            continue
        if headers:
            row = _map_input_row_by_header_order(row, headers)
        elif len(row) == len(_INPUT_HEADERS_BEFORE_RECT_CULVERT_VISIBLE_COLUMNS):
            row = _map_input_row_by_header_order(row, _INPUT_HEADERS_BEFORE_RECT_CULVERT_VISIBLE_COLUMNS)
        yield index, row


def _batch_trenchless_inputs(project, panel):
    """Index the declared diameter column against real batch input points."""
    from app_渠系计算前端.batch.schema import COL_BUILDING_NAME, COL_D, COL_SECTION_TYPE, COL_X, COL_Y

    by_point = {}
    had_rows = False
    for index, row in _batch_input_rows(project, panel):
        had_rows = True
        if len(row) <= COL_Y:
            continue
        kind = _batch_pipe_kind(row[COL_SECTION_TYPE])
        if kind not in {"有压管道", "顶管", "定向钻"}:
            continue
        try:
            point = (_float(row[COL_X], "批量计算表 X"), _float(row[COL_Y], "批量计算表 Y"))
        except (ValueError, OverflowError):
            continue
        value = row[COL_D] if len(row) > COL_D else None
        try:
            diameter = _float(value, "批量计算表直径D(m)") if not isinstance(value, bool) else None
        except (ValueError, OverflowError):
            diameter = None
        name = str(row[COL_BUILDING_NAME] or "").strip()
        by_point.setdefault((kind, *point), []).append(
            (f"xlsx-row-{index}", name, diameter if diameter is not None and diameter > 0 else None))
    return by_point if had_rows else None


def _match_batch_bore_diameter(batch, nodes):
    """Return the diameter and whether the batch includes any linked row."""
    matched = False
    diameters = set()
    for node in nodes:
        if node.get("is_transition") or node.get("is_auto_inserted_channel"):
            continue
        kind = _batch_pipe_kind(node.get("structure_type"))
        try:
            point = (_float(node.get("x"), "水面线 X"), _float(node.get("y"), "水面线 Y"))
        except (ValueError, OverflowError):
            diameters.add(None)
            continue
        name = _name(node).strip()
        candidates = [item for item in batch.get((kind, *point), ())
                      if not name or not item[1] or item[1] == name]
        exact = [item for item in candidates if item[0] == node.get("profile_row_id")]
        chosen = exact or candidates
        matched |= bool(chosen)
        diameters.add(chosen[0][2] if len(chosen) == 1 else None)
    return (next(iter(diameters)) if len(diameters) == 1 else None), matched


def _specialist_bore_nodes(config, nodes, source_type, segment):
    """Only use batch rows for a specialist with matching source membership."""
    kind = _batch_pipe_kind(source_type)
    eligible = [node for node in nodes if _batch_pipe_kind(node.get("structure_type")) == kind]
    if segment is not None:
        return eligible
    if not eligible or not _name(config) or any(_name(node) != _name(config) for node in eligible):
        return None
    # A saved span and its plan endpoints provide independent checks against
    # names or row numbers that can recur on unrelated routes.
    points = config.get("ip_points") or config.get("plan_feature_points") or []
    if len(points) < 2 or not all(isinstance(point, dict) for point in (points[0], points[-1])):
        return None
    start, end = _station(eligible[0]), _station(eligible[-1])
    try:
        declared = [_float(config.get(key), key) for key in ("start_mc", "end_mc")]
        positions = [
            (_float(node.get(axis), axis), _float(point.get(axis), axis))
            for node, point in ((eligible[0], points[0]), (eligible[-1], points[-1]))
            for axis in ("x", "y")
        ]
    except (ValueError, OverflowError):
        return None
    if start is None or end is None or end <= start or not all(
            math.isclose(a, b, rel_tol=0., abs_tol=SOURCE_ROUTE_ENDPOINT_TOLERANCE_M)
            for a, b in (*zip((start, end), declared), *positions)):
        return None
    return eligible


def _name(row):
    return str(row.get("name") or row.get("base_name") or row.get("dxf_display_name") or "")


def _identity(value, prefix):
    return prefix+hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _issue(result, message, *, code="missing_source", asset=None, field=None, station=None, severity="error"):
    row = {"code": code, "severity": severity, "message": message}
    if asset is not None:
        row.update(asset_id=asset["asset_id"], source_identity=asset.get("source_identity"))
        if field:
            asset.setdefault("missing_fields", []).append(field)
    if field: row["field"] = field
    if station is not None: row["station"] = station
    result["diagnostics"].append(row)
    return row


def _validate_elements(elements):
    if not elements:
        raise ValueError("缺少真实平面线元")
    values = []
    for i, raw in enumerate(elements):
        row = deepcopy(_as_dict(raw))
        kind = str(row.get("kind", row.get("seg_type", "line"))).lower()
        a = _float(row.get("station_start", row.get("s_start")), "平面起桩")
        b = _float(row.get("station_end", row.get("s_end")), "平面止桩")
        length = b-a
        if length <= 0:
            raise ValueError("真实平面线元桩号必须递增")
        made = {"kind": kind, "station_start": a, "station_end": b, "length": length}
        if kind == "line":
            start = row.get("start_xy", row.get("p_start"))
            if start is None: raise ValueError("平面直线缺少真实起点")
            start = [_float(v, "平面坐标") for v in start]
            end = row.get("end_xy")
            if end is None:
                direction = row.get("direction")
                if direction is None: raise ValueError("平面直线缺少方向或终点")
                norm = math.hypot(*map(float, direction))
                if abs(norm-1.) > 1e-6: raise ValueError("平面线元方向不是单位向量")
                end = [start[j]+float(direction[j])*length for j in (0,1)]
            end = [_float(v, "平面坐标") for v in end]
            if abs(math.hypot(end[0]-start[0], end[1]-start[1])-length) > max(1e-4, length*1e-7):
                raise ValueError("直线桩号与真实平面长度不一致，禁止把曲线当弦线")
            made.update(start_xy=start, end_xy=end, tangent_angle=math.atan2(end[1]-start[1], end[0]-start[0]))
        elif kind == "arc":
            center = row.get("center_xy", row.get("center"))
            radius = _float(row.get("radius", row.get("R_h")), "平面圆弧半径")
            theta = _float(row.get("start_angle", row.get("theta_0")), "平面圆弧起角")
            sweep = row.get("sweep_angle")
            if sweep is None: sweep = float(row.get("epsilon", 1))*length/radius
            sweep = _float(sweep, "平面圆弧转角")
            if radius <= 0 or abs(abs(sweep)*radius-length) > max(1e-4,length*1e-7):
                raise ValueError("圆弧桩号、半径与转角不一致")
            center = [_float(v, "平面弧心") for v in center]
            start = [center[0]+radius*math.cos(theta), center[1]+radius*math.sin(theta)]
            end = [center[0]+radius*math.cos(theta+sweep), center[1]+radius*math.sin(theta+sweep)]
            for key, expected in (("start_xy", start),("end_xy", end)):
                if row.get(key) is not None and math.dist(row[key],expected) > 1e-5:
                    raise ValueError("圆弧坐标与真源半径/转角不一致")
            made.update(center_xy=center, radius=radius, start_angle=theta, sweep_angle=sweep,
                        start_xy=start, end_xy=end)
        else: raise ValueError(f"不支持的真实线元：{kind}")
        if i and (abs(values[-1]["station_end"]-a) > 1e-7 or math.dist(values[-1]["end_xy"],made["start_xy"]) > 1e-5):
            raise ValueError("真实平面线元存在缺段、重叠或坐标不连续")
        values.append(made)
    return values


def import_plan_alignment(source, *, fallback_points=None):
    """Read explicit line/arc elements, saved DXF arc facts, or verified IP fillets."""
    source = deepcopy(source or {})
    alignment = source.get("alignment") or {}
    if isinstance(alignment, NetworkAlignment): return deepcopy(alignment)
    for values in (alignment.get("elements"), source.get("plan_elements"), source.get("analytic_plan_segments")):
        if values:
            elements = _validate_elements(values)
            return NetworkAlignment(elements, [], start_station=elements[0]["station_start"])
    # plan_segments in hydraulic snapshots can also be loss components rather
    # than analytic segments; accept only elements carrying actual coordinates.
    segments = source.get("plan_segments") or []
    if segments and all((p.get("p_start") is not None or p.get("center") is not None or p.get("start_xy") is not None) for p in segments):
        elements = _validate_elements(segments)
        return NetworkAlignment(elements, [], start_station=elements[0]["station_start"])
    points = source.get("plan_feature_points") or source.get("ip_points") or alignment.get("plan_points") or fallback_points or []
    points = [_as_dict(p) for p in points]
    if len(points) < 2: raise ValueError("缺少至少两个真实平面点")
    unique = []
    for point in points:
        if unique and (point.get("x"),point.get("y"),_station(point)) == (unique[-1].get("x"),unique[-1].get("y"),_station(unique[-1])):
            continue
        unique.append(point)
    points = unique
    if any(p.get("arc_geometry") for p in points):
        events, arcs = [], []
        for p in points:
            g = p.get("arc_geometry")
            if not g:
                s = _station(p)
                if s is None: raise ValueError("平面圆弧来源缺少对应桩号")
                events.append((s, [float(p["x"]),float(p["y"])]))
                continue
            a,b = _float(g.get("start_chainage"),"弧起桩"),_float(g.get("end_chainage"),"弧止桩")
            begin, finish, center = g["start"],g["end"],g["center"]
            arcs.append({"kind":"arc","station_start":a,"station_end":b,"center_xy":center,
                         "radius":g["radius"],"start_angle":math.atan2(begin[1]-center[1],begin[0]-center[0]),
                         "sweep_angle":(-1 if g.get("clockwise") else 1)*g["sweep_rad"],
                         "start_xy":begin,"end_xy":finish})
            events.extend([(a,begin),(b,finish)])
        # ARC endpoint rows also occur in saved feature lists. Merge only
        # identical positions at the same station, not geometrically different IPs.
        by_station = {}
        for s,xy in events:
            if s in by_station and math.dist(by_station[s],xy)>1e-5:
                raise ValueError("真圆弧与平面点在同桩坐标冲突")
            by_station[s]=xy
        elements=[]
        events=sorted(by_station.items())
        for (a,xy),(b,endxy) in zip(events,events[1:]):
            arc=next((g for g in arcs if abs(g["station_start"]-a)<1e-7 and abs(g["station_end"]-b)<1e-7),None)
            if arc: elements.append(arc)
            elif any(g["station_start"]<a<g["station_end"] or g["station_start"]<b<g["station_end"] for g in arcs):
                raise ValueError("平面点侵入真实圆弧区间，需核对来源")
            else: elements.append({"kind":"line","station_start":a,"station_end":b,"start_xy":xy,"end_xy":endxy})
        elements=_validate_elements(elements)
        return NetworkAlignment(elements,points,start_station=elements[0]["station_start"])
    stations = [_station(p) for p in points]
    if any(s is None for s in stations): raise ValueError("真实路线缺少桩号，须补录或读取主程序计算成果")
    if any(b<=a for a,b in zip(stations,stations[1:])): raise ValueError("平面桩号不递增或包含断链")
    built = build_ip_alignment(points,start_station=stations[0],allow_test_radius_adjustment=False,minimum_straight=0.0)
    for original, generated in zip(stations,built.ip_points):
        if abs(original-generated["route_station"]) > 1e-3:
            raise ValueError("原始桩号与真实线形不一致，禁止改用弦长或调整转弯半径")
    _validate_elements(built.elements)
    return built



def _hydraulic_original_ip_points(panel, nodes):
    """Read original batch IPs; inserted hydraulic nodes are never IPs."""
    rows=(panel.get("batch_panel_compat") or {}).get("input_rows") or []
    originals=[n for n in nodes if not n.get("is_transition") and not n.get("is_auto_inserted_channel")]
    if not rows:
        return originals
    by_xy={}
    for node in originals:
        if node.get("profile_row_id") and node.get("x") is not None and node.get("y") is not None:
            by_xy.setdefault((float(node["x"]),float(node["y"])),[]).append(node)
    points=[]
    for index,row in enumerate(rows):
        if not isinstance(row,(list,tuple)) or len(row)<=24:
            raise ValueError("原始IP输入行缺少坐标或转弯半径列")
        x,y=_float(row[4],"原始IP X"),_float(row[5],"原始IP Y")
        candidates=by_xy.get((x,y),[])
        node=next((n for n in candidates if n.get("profile_row_id")==f"xlsx-row-{index+3}"),None)
        if node is None and len(candidates)==1:node=candidates[0]
        if node is None:raise ValueError(f"原始IP第{index+1}行未匹配真实计算节点")
        radius_text="" if row[24] is None else str(row[24]).strip()
        radius=_float(radius_text or 0,"原始IP转弯半径")
        # Official entry/exit boundaries carry no fillet even when the input
        # radius column is populated. Preserve that explicit geometry fact.
        # Geometry comes from the completed water-profile calculation. A blank
        # input can now have an adopted nD radius, or a later UI override. Read
        # that frozen value instead of recomputing defaults on historical data.
        adopted_metadata=bool(node.get("turn_radius_source") or node.get("turn_radius_is_explicit")
                              or str(node.get("turn_radius_text") or "").strip())
        effective=_float(node.get("turn_radius",radius) if adopted_metadata or not radius_text else radius,
                         "已计算IP转弯半径")
        if "turn_angle" in node and abs(float(node.get("turn_angle") or 0))<=1e-9:
            effective=0.0
        # A clipped route carries these IP facts into each workbench group.
        # Hydraulic results stay with their source nodes instead of repeating
        # the full water-loss record at every copy of the plan alignment.
        point={key:deepcopy(node[key]) for key in ("profile_row_id","name","structure_type",
            "station_MC","station_mc","station","chainage","turn_angle","arc_geometry",
            "turn_radius_source","turn_radius_is_explicit","turn_radius_text",
            "turn_radius_default_value","turn_radius_default_diameter","turn_radius_default_multiplier") if key in node}
        point.update(x=x,y=y,turn_radius=effective,source_row=index+3,
                     original_input_turn_radius=radius,original_input_turn_radius_text=radius_text,
                     plan_point_source="batch_panel_compat.input_rows",
                     boundary_radius_rule=("official_zero_turn_has_no_fillet" if "turn_angle" in node
                         and abs(float(node.get("turn_angle") or 0))<=1e-9 else "calculated_effective_radius"))
        points.append(point)
    return points


def _hydraulic_group_ranges(groups, alignment, *, adjustment_records=None):
    """Keep buried inlet/outlet MCs; surface canals follow source MC boundaries."""
    spans=[]
    for (rawtype,_name_value),members in groups:
        values=[node for _,node in members]
        spans.append([_station(values[0]),_station(values[-1])])
    for index,((rawtype,_name_value),members) in enumerate(groups):
        if rawtype not in TYPE_MAP or not rawtype.startswith("明渠"):continue
        start,end=spans[index]
        is_open_channel = TYPE_MAP[rawtype][0] == "open_channel"
        if index==0 and alignment is not None:start=alignment.start_station
        if index>0:
            previous_type=groups[index-1][0][0]
            if ((is_open_channel and _is_sluice_gate(previous_type))
                    or (previous_type in TYPE_MAP and not previous_type.startswith("明渠"))):
                start=spans[index-1][1]
        if index+1<len(groups):
            next_type=groups[index+1][0][0]
            if (next_type in TYPE_MAP or (is_open_channel and _is_sluice_gate(next_type))) and spans[index+1][0] is not None:
                end=spans[index+1][0]
        elif alignment is not None:end=alignment.end_station
        spans[index]=[start,end]
    # A continuous named building changes its construction parameters at the
    # first node of the next flow section. Separate outlet/inlet pairs have
    # their own physical endpoints even when the names are identical.
    for index, ((key, before), (next_key, after)) in enumerate(zip(groups, groups[1:])):
        rawtype, _ = key
        if key != next_key or rawtype not in _FLOW_SECTION_TYPES:
            continue
        upstream, downstream = before[-1][1], after[0][1]
        boundary = spans[index + 1][0]
        if (boundary is not None and _flow_section(upstream) != _flow_section(downstream)
                and not _new_structure_entry(upstream, downstream)):
            spans[index][1] = boundary
    # Consecutive ordinary/trenchless pressure rows belong to one physical
    # line. The ordinary pipe runs to the stated jacking/drilling boundary.
    # Keep the non-open-cut interval itself unchanged.
    for index, ((rawtype, _), members) in enumerate(groups):
        if rawtype != "有压管道":
            continue
        diameter = _pressure_group_diameter(members)
        if diameter is None:
            continue
        for neighbor, side in ((index - 1, 0), (index + 1, 1)):
            if not 0 <= neighbor < len(groups):
                continue
            (other_type, _), other_members = groups[neighbor]
            if other_type not in {"顶管", "定向钻"}:
                continue
            other_diameter = _pressure_group_diameter(other_members)
            if other_diameter is None or not math.isclose(diameter, other_diameter, abs_tol=1e-8):
                continue
            boundary = spans[neighbor][1 - side]
            if boundary is not None:
                spans[index][side] = boundary
    return [_source_range_on_plan(*span, alignment, records=adjustment_records,
                                  source={"source_type": key[0], "name": key[1]})
            for (key, _), span in zip(groups, spans)]


def _pressure_group_diameter(members):
    diameters = set()
    for _, node in members:
        parameters = node.get("section_params") or {}
        value = parameters.get("D", parameters.get("直径D"))
        if value is None:
            value = (node.get("section") or {}).get("inner_diameter")
        try:
            diameter = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(diameter) or diameter <= 0:
            return None
        diameters.add(diameter)
    return next(iter(diameters)) if len(diameters) == 1 else None


def _source_pressure_ranges(nodes):
    groups = _node_groups([node for node in nodes if not node.get("is_transition")])
    spans = _hydraulic_group_ranges(groups, None)
    return [dict(name=name, source_type=rawtype, diameter=_pressure_group_diameter(members),
                 original_range=[_station(members[0][1]), _station(members[-1][1])],
                 connected_range=span)
            for ((rawtype, name), members), span in zip(groups, spans)
            if rawtype == "有压管道"]


def _inherited_pressure_range(ranges, start, end, diameter):
    try:
        start, end, diameter = (_float(value, "来源管段范围或管径") for value in (start, end, diameter))
    except ValueError:
        return None
    matches = [row for row in ranges if all(value is not None for value in row["original_range"])
        and abs(start - row["original_range"][0]) < 1e-5
        and abs(end - row["original_range"][1]) < 1e-5
        and row["diameter"] is not None and math.isclose(row["diameter"], diameter, abs_tol=1e-8)]
    return matches[0]["connected_range"] if len(matches) == 1 else None


def _hydraulic_profile_for_range(values, nodes, start, end, boundary_extensions=None):
    """Use actual hydraulic bottom elevations, including adjacent boundary nodes."""
    own=[n for n in values if n.get("bottom_elevation") is not None]
    if len(own)!=len(values) or start is None or end is None:return None
    eligible=[n for n in nodes if not n.get("is_transition") and _station(n) is not None
              and n.get("bottom_elevation") is not None
              and (n.get("structure_height") or n.get("top_elevation")
                   or _is_sluice_gate(n.get("structure_type")) or _deferred_pit(n.get("structure_type")))]
    positions={_station(n):float(n["bottom_elevation"]) for n in eligible}
    positions.update({_station(n):float(n["bottom_elevation"]) for n in own})
    ordered=sorted(positions)
    if not ordered:return None
    own_sorted=sorted(own,key=_station)
    def height(station):
        if station in positions:return positions[station]
        if abs(station-ordered[0])<=1e-7:return positions[ordered[0]]
        if abs(station-ordered[-1])<=1e-7:return positions[ordered[-1]]
        # A following pressure-pipe entry may have no hydraulic bed field.
        # Continue this channel's explicitly stored design grade to that real
        # boundary, anchored at its last calculated bed; never use terrain or
        # a fictitious pipe elevation to complete an ordinary channel profile.
        if station<_station(own_sorted[0]) or station>_station(own_sorted[-1]):
            anchor=own_sorted[0] if station<_station(own_sorted[0]) else own_sorted[-1]
            if anchor.get("slope_i") is not None:
                grade=_float(anchor["slope_i"],"实际设计底坡")
                elevation=float(anchor["bottom_elevation"])-grade*(station-_station(anchor))
                if boundary_extensions is not None:
                    boundary_extensions.append({"station":station,"elevation":elevation,
                        "anchor_profile_row_id":anchor.get("profile_row_id"),"anchor_station":_station(anchor),
                        "anchor_bottom_elevation":anchor["bottom_elevation"],"source_slope_i":grade,
                        "basis":"actual_hydraulic_bottom_plus_declared_channel_design_grade"})
                return elevation
        for a,b in zip(ordered,ordered[1:]):
            if a<=station<=b:return positions[a]+(positions[b]-positions[a])*(station-a)/(b-a)
        raise ValueError("施工分界没有水力计算高程或明确设计底坡支撑")
    selected={start,end,*[_station(n) for n in own if start<=_station(n)<=end]}
    return [{"station":station,"elevation":height(station)} for station in sorted(selected)]

def _profile_source(config, route=None):
    route = route or {}
    for row in (config,route):
        for key in ("design_profile","raw_profile_polyline","longitudinal_nodes","profile_points"):
            if row.get(key): return row[key]
    if config.get("alignment",{}).get("profile_points"): return config["alignment"]["profile_points"]
    return None


def _pressure_profile_source(route, identity, member=None):
    """Use original design geometry ahead of hydraulic nodes sampled from it."""
    def actual(row):
        return row and not (row.get("longitudinal_is_example") or row.get("test_only") or row.get("is_test")
                            or row.get("source_kind") == "generated_tunnel")
    member = member if actual(member) else {}
    route = route if actual(route) else {}
    exact = next((row for row in route.get("profile_segments") or []
                  if identity and actual(row) and (row.get("segment_identity") or row.get("identity")) == identity), {})
    return (member.get("design_profile") or exact.get("design_profile") or exact.get("raw_profile_polyline")
            or member.get("raw_profile_polyline") or route.get("design_profile") or route.get("raw_profile_polyline")
            or _profile_source(exact) or _profile_source(route) or _profile_source(member))


def _table_pressure_source(values, membership, stored):
    memberships = [membership.get(id(row)) for row in values]
    if not all(memberships):
        return None, None
    owners = set.union(*memberships)
    keys = {key for key, _ in owners}
    if len(keys) != 1:
        return None, None
    route = stored[next(iter(keys))]
    if len(owners) == 1:
        return route, _pressure_profile_source(route, next(iter(owners))[1])
    axis = _pressure_profile_source(route, None)
    if axis:
        return route, axis
    # Some hydraulic tables keep several adjacent unnamed members together as
    # one earthwork object; individual saved axes still retain their true spans.
    axes = [source for _, identity in sorted(owners)
            if (source := _pressure_profile_source(route, identity)) is not None]
    if not axes:
        return route, None
    references = {source.get("reference") or "pipe_axis" if isinstance(source, dict) else "pipe_axis" for source in axes}
    return route, {"parts": axes, "reference": next(iter(references)) if len(references) == 1 else "mixed_references"}


def _pressure_axis_origin(route, member=None):
    for source in (member or {}, route):
        if source.get("axis_source") == "terrain_and_user_cover_depth":
            return "terrain_and_user_cover_depth"
    return "water_profile_real_elevation"


def _legacy_points(profile):
    return [{"station":s,"elevation":evaluate_profile(profile,s)[0]} for s in profile_break_stations(profile)]


def clip_plan_alignment(alignment, station_start, station_end):
    """Retain exact line/arc geometry for one supported continuous range."""
    start,end=_float(station_start,"起桩"),_float(station_end,"止桩")
    start,end=_source_range_on_plan(start,end,alignment)
    if start<alignment.start_station-1e-7 or end>alignment.end_station+1e-7 or end<=start:
        raise ValueError("裁切范围越出真实路线")
    values=[]
    for original in alignment.elements:
        a,b=max(start,original["station_start"]),min(end,original["station_end"])
        if b<=a: continue
        row=deepcopy(original)
        row.update(station_start=a,station_end=b,length=b-a,
                   start_xy=list(alignment.get_xy_at_station(a)),end_xy=list(alignment.get_xy_at_station(b)))
        if row["kind"]=="arc":
            sign=math.copysign(1.,original["sweep_angle"])
            row["start_angle"]=original["start_angle"]+sign*(a-original["station_start"])/original["radius"]
            row["sweep_angle"]=sign*(b-a)/original["radius"]
        values.append(row)
    return NetworkAlignment(_validate_elements(values),deepcopy(alignment.ip_points),start_station=start)


def trenchless_plan_alignment(record, alignment=None):
    """Read the actual plan geometry for one imported non-open-cut span."""
    start, end = record.get("station_start"), record.get("station_end")
    if alignment is not None:
        try:
            return clip_plan_alignment(alignment, start, end)
        except (ValueError, TypeError, KeyError):
            pass
    source = record if record.get("plan_elements") else record.get("original_asset_snapshot") or record
    points = (source.get("original_fields") or {}).get("records")
    try:
        alignment = import_plan_alignment(source, fallback_points=points)
        return clip_plan_alignment(alignment, start, end)
    except (ValueError, TypeError, KeyError):
        return None


def restore_source_plan_alignment(network):
    """Recover the original plan from IPs retained on an older cropped route."""
    alignment = network.get("alignment")
    extent = network.get("source_route_extent")
    if (not isinstance(alignment, NetworkAlignment) or not alignment.ip_points
            or not isinstance(extent, (list, tuple)) or len(extent) != 2):
        return None
    try:
        source_plan = import_plan_alignment({"ip_points": alignment.ip_points})
        start, end = _source_range_on_plan(*extent, source_plan)
    except (ValueError, TypeError, KeyError):
        return None
    if (start, end) == (source_plan.start_station, source_plan.end_station):
        return source_plan
    return None


def _construction_missing(asset, result):
    from ..services.section_parameter_decisions import parameter_value
    mark_imported_pipe_diameter(asset, source="当前水面线/专项计算管径D(m)")
    normalize_asset_construction(asset)
    section, construction = asset["section"],asset["construction"]
    if asset["kind"] == "tunnel":
        required = ["section.lining_thickness", "section.shotcrete_thickness", "construction.excavation_clearance"]
        if asset.get("source_tunnel_parameters") and asset.get("section_type") in {"arch_tunnel", "flat_bottom_tunnel"}:
            required.append("section.base_thickness")
        if asset.get("source_tunnel_lining_selection_required"):
            required.append("section.rock_class")
        required += {
            "arch_tunnel": ["section.inner_width", "section.inner_height", "section.wall_height", "section.arch_angle_degrees"],
            "circular_tunnel": ["section.inner_diameter"],
            "flat_bottom_tunnel": ["section.inner_diameter", "section.bottom_width"],
            "horseshoe_tunnel": ["section.inner_radius"],
        }.get(asset.get("section_type"), [])
    else:
        required = ["construction.working_space_left","construction.working_space_right",
                "construction.bedding_thickness","construction.bedding_extension"]
    if is_pipe_asset(asset):
        if not section.get("pipes") and not section.get("outer_diameter"):
            required.append("section.outer_diameter")
        if section.get("pipe_count",1)>1 and section.get("pipe_spacing") is None: required.append("section.pipe_spacing")
        if asset["kind"] in {"pipe","siphon"}: required.append("construction.installation_mode")
    elif asset["kind"] != "tunnel":
        required += ["section.base_thickness","section.wall_thickness_left","section.wall_thickness_right"]
        if asset["kind"]=="culvert": required.append("section.roof_thickness")
    for side in (() if asset["kind"] == "tunnel" else ("left","right")):
        if not construction.get("excavation_stages_"+side): required.append("construction.excavation_slope_"+side)
        if asset["kind"]=="open_channel":
            required += ["construction.bank_top_width_"+side,"construction.bank_slope_"+side]
    if asset["kind"] != "tunnel" and construction.get("target_mode") is None: required.append("construction.target_mode")
    for path in required:
        if parameter_value(asset, path)[0] is None:
            _issue(result,f"{asset['name']}：需补充 {path}",asset=asset,field=path,code="missing_construction")


def _base_asset(identity,name,kind,stype,config):
    flow_section = _flow_section(config)
    return {"asset_id":_identity(identity,"design-"),"name":name,"kind":kind,"section_type":stype,
            **({"flow_section": flow_section} if flow_section else {}),
            "source_identity":identity,"enabled":True,"section":deepcopy(config.get("section") or {}),
            "construction":deepcopy(config.get("construction") or {}),"missing_fields":[],
            "geometry_sections":[],"original_fields":deepcopy(config),
            "is_test":bool(config.get("is_test") or config.get("test_only") or config.get("longitudinal_is_example"))}


def _gate_asset(identity, name, source_type, node, station):
    from ..services.sluice_gate import DEFAULT_GATE_LINING_MULTIPLIER, GATE_SECTION_FIELDS

    asset = _base_asset(identity, name or source_type, "gate", "sluice_gate", node)
    asset.update(source_type=source_type, gate_station=station)
    params = node.get("section_params") or {}
    for group, keys in (("section", (*GATE_SECTION_FIELDS, "concrete_grade")),
                        ("construction", ("gate_length", "gate_lining_multiplier"))):
        target = asset[group]
        for key in keys:
            value = node.get(key)
            if value in (None, ""):
                value = params.get(key)
            if target.get(key) in (None, "") and value not in (None, ""):
                target[key] = value
    if asset["construction"].get("gate_lining_multiplier") in (None, ""):
        asset["construction"]["gate_lining_multiplier"] = DEFAULT_GATE_LINING_MULTIPLIER
    asset["gate_source_parameters"] = deepcopy(_gate_parameter_paths(asset))
    return asset


def _gate_parameter_paths(asset):
    from ..services.sluice_gate import GATE_SECTION_FIELDS

    return {**{f"section.{key}": value for key, value in (asset.get("section") or {}).items()
               if key in (*GATE_SECTION_FIELDS, "concrete_grade")},
            **{f"construction.{key}": value for key, value in (asset.get("construction") or {}).items()
               if key != "gate_lining_basis"}}


def gate_user_override_paths(previous):
    """Identify user-adopted fields, including projects saved before these were tracked."""
    values = _gate_parameter_paths(previous)
    overrides = previous.get("gate_user_overrides")
    if isinstance(overrides, list):
        return {path for path in overrides if isinstance(path, str) and path in values}
    baseline = previous.get("gate_source_parameters")
    original = previous.get("original_fields")
    if not isinstance(baseline, dict) and isinstance(original, dict) and _is_sluice_gate(original.get("structure_type")):
        baseline = _gate_asset(previous.get("source_identity"), previous.get("name"), previous.get("source_type"),
                               original, previous.get("gate_station"))["gate_source_parameters"]
    baseline = baseline if isinstance(baseline, dict) else {}
    return {path for path, value in values.items() if value != baseline.get(path)}


def replay_gate_user_parameters(asset, previous):
    """Carry applied gate edits to refreshed source parameters for the same gate."""
    values = _gate_parameter_paths(previous)
    overrides = gate_user_override_paths(previous)
    for path in overrides:
        group, key = path.split(".", 1)
        asset[group][key] = deepcopy(values[path])
    asset["gate_user_overrides"] = sorted(overrides)
    asset["enabled"] = previous.get("enabled", True)


def _water_profile_lining(nodes, kind, section_type, saved):
    """Keep source-node thickness separate from workbench construction assumptions."""
    aliases = {
        "base_thickness": ("u_bottom_thickness", "base_thickness", "t0", "lining_thickness"),
        "wall_thickness_left": ("wall_thickness_left", "wall_thickness", "wall_t", "t1", "t", "lining_thickness"),
        "wall_thickness_right": ("wall_thickness_right", "wall_thickness", "wall_t", "t1", "t", "lining_thickness"),
    }
    if kind == "open_channel" or section_type == "circular_culvert":
        aliases["base_thickness"] += ("wall_thickness", "wall_t", "t")
    lining = {}
    for node in nodes:
        layers = (node.get("section") or {}, node.get("section_params") or {}, node)
        for field, keys in aliases.items():
            if field not in lining:
                value = next((value for key in keys for layer in layers
                              if (value := lining_number(layer.get(key))) is not None), None)
                if value is not None:
                    lining[field] = value
    summary_kind = SECTION_SUMMARY_LINING_TYPES.get(nodes[0].get("structure_type"))
    return {**gate_reference_lining(summary_kind, saved), **lining}


def _gate_batch_key(node):
    try:
        return (node.get("structure_type"), _flow_section(node),
                _float(node.get("x"), "闸点 X"), _float(node.get("y"), "闸点 Y"))
    except (ValueError, OverflowError):
        return None


def _gate_batch_inputs(project, panel):
    from app_渠系计算前端.batch.schema import (
        COL_B, COL_BUILDING_NAME, COL_N, COL_Q, COL_SECTION_TYPE, COL_SEGMENT, COL_SLOPE,
        COL_V_MAX, COL_V_MIN, COL_X, COL_Y, infer_gate_section_type, normalize_project_section_type,
    )

    fields = {"flow": COL_Q, "roughness": COL_N, "slope_inverse": COL_SLOPE,
              "minimum_velocity": COL_V_MIN, "maximum_velocity": COL_V_MAX, "bottom_width": COL_B}
    indexed = {}
    for index, row in _batch_input_rows(project, panel):
        if len(row) <= COL_Y:
            continue
        source_type = normalize_project_section_type(infer_gate_section_type(row[COL_SECTION_TYPE], row[COL_BUILDING_NAME]))
        if not _is_sluice_gate(source_type):
            continue
        key = _gate_batch_key({"structure_type": source_type, "flow_section": row[COL_SEGMENT],
                               "x": row[COL_X], "y": row[COL_Y]})
        if key is not None:
            values = {field: row[col] for field, col in fields.items() if col < len(row)}
            indexed.setdefault(key, []).append((f"xlsx-row-{index}", str(row[COL_BUILDING_NAME] or source_type).strip(), values))
    return indexed


def _gate_hydraulic_inputs(gate, reference, nodes, batch, settings):
    from ..services.workbench_hydraulics import channel_calculator_defaults

    source = gate["original_fields"]
    matches = [row for row in batch.get(_gate_batch_key(source), ()) if row[1] == gate["name"]]
    exact = [row for row in matches if row[0] == source.get("profile_row_id")]
    matches = exact or matches
    parsed_batch = channel_calculator_defaults(matches[0][2]) if len(matches) == 1 else {}
    current = {**source, **parsed_batch, **channel_calculator_defaults(source), "flow_section": gate.get("flow_section")}
    if gate["section"].get("inner_width") is not None:
        current["bottom_width"] = gate["section"]["inner_width"]
    nearby = ((reference or {}).get("original_fields") or {}).get("records") or ()
    primary = channel_calculator_defaults(current, settings=settings, references=nearby)
    full = channel_calculator_defaults({**current, **primary}, settings=settings, references=nodes)
    if full:
        gate["gate_channel_inputs"] = full
    if full.get("flow") is not None:
        gate["gate_design_flow"] = full["flow"]


def _network(identity,name,alignment,assets,source):
    return {"schema_version":"1.0","network_id":_identity(identity,"network-"),"name":name,
            "alignment":alignment,"assets":assets,"source_identity":identity,"source":deepcopy(source),
            "test_only":any(a.get("is_test") for a in assets),"status":"DRAFT"}


def _bind_profile(asset, source, result, reference="inner_invert", *, pipe_source="water_profile_real_elevation"):
    try:
        declared=source.get("design_profile",source) if isinstance(source,dict) else source
        declared=declared.get("reference") if isinstance(declared,dict) else None
        if declared and declared not in {"inner_invert","pipe_axis","common_outer_bottom"}:
            raise DesignProfileError("来源高程基准未识别，须明确净内底、首管管轴或共同外管底后再计算",code="invalid_profile_reference")
        start, end = asset.get("station_start"), asset.get("station_end")
        if reference == "pipe_axis" and pipe_source == "water_profile_real_elevation" and start is not None and end is not None:
            from ..services.pipe_profile_sources import water_profile_runs
            runs = water_profile_runs(source, start, end, reference=declared or reference)
            if not runs:
                raise DesignProfileError("水面线设计线未覆盖当前管段", code="missing_design_profile")
            if len(runs) != 1 or runs[0]["station_start"] > start + 1e-7 or runs[0]["station_end"] < end - 1e-7:
                asset["water_profile_parts"] = runs
                _issue(result,"水面线分段待确认，请核对设计线覆盖范围",asset=asset,field="design_profile",
                       code="missing_design_profile")
                return
            profile = runs[0]
        elif isinstance(source, dict) and source.get("parts") and start is not None and end is not None:
            from ..services.pipe_profile_sources import clip_water_profile_parts
            profile = clip_water_profile_parts(source, start, end, reference=declared or reference)
        else:
            profile=normalize_design_profile(source,reference=declared or reference)
            if asset.get("station_start") is not None and asset.get("station_end") is not None:
                profile=clip_design_profile(profile,asset["station_start"],asset["station_end"])
        asset["design_profile"]=profile
        asset["profile_points"]=_legacy_points(profile)
        asset.setdefault("alignment",{})["profile_points"]=deepcopy(asset["profile_points"])
        asset["alignment"]["elevation_reference"]=profile["reference"]
        if reference == "pipe_axis" and pipe_source:
            if pipe_source == "water_profile_real_elevation":
                asset["water_profile_design_profile"] = deepcopy(profile)
            mode = "cover_depth" if pipe_source == "terrain_and_user_cover_depth" else "actual_axis"
            asset.update(axis_source=pipe_source, profile_source=pipe_source)
            asset.setdefault("construction", {}).update(burial_mode=mode, axis_confirmed=True)
    except (ValueError,TypeError) as exc:
        _issue(result,str(exc),asset=asset,field="design_profile",code=getattr(exc,"code","missing_design_profile"),station=getattr(exc,"station",None))


def _new_structure_entry(previous, current):
    return (previous.get("in_out") in ("出", "出口")
            and current.get("in_out") in ("进", "进口"))


def _node_groups(nodes, claimed=None, *, split_flow_sections=False):
    groups=[]
    previous_claim, previous_node = None, None
    for i,node in enumerate(nodes):
        key=(str(node.get("structure_type", "")),_name(node))
        owned = (node.get("profile_row_id") or id(node)) in claimed if claimed else False
        new_siphon = key[0] == "倒虹吸" and previous_node is not None and _new_structure_entry(previous_node, node)
        new_flow = (split_flow_sections and key[0] in _FLOW_SECTION_TYPES and previous_node is not None
                    and _flow_section(previous_node) != _flow_section(node))
        if (not groups or groups[-1][0] != key or owned != previous_claim or new_siphon
                or new_flow or _is_sluice_gate(key[0])):
            groups.append((key, []))
        groups[-1][1].append((i,node))
        previous_claim, previous_node = owned, node
    return groups


def _matching_nodes(nodes,names):
    names={str(n) for n in names if n}
    return [p for p in nodes if _name(p) in names]


def _indexed_nodes(nodes, config, names):
    """Prefer saved stable row spans over ambiguous human display names."""
    a,b=config.get("start_row_index"),config.get("end_row_index")
    if isinstance(a,int) and isinstance(b,int) and 0<=a<b<len(nodes):
        return nodes[a:b+1]
    return _matching_nodes(nodes,names)


def _siphon_source_nodes(nodes, config, key, name):
    """Match one continuous source span when a name occurs more than once."""
    groups = _node_groups([row for row in nodes if not row.get("is_transition")])
    matches = [[row for _, row in members] for (kind, label), members in groups
               if kind == "倒虹吸" and label in {str(key), name}]
    a, b = config.get("start_row_index"), config.get("end_row_index")
    if isinstance(a, int) and isinstance(b, int) and 0 <= a < b < len(nodes):
        indexed = [row for row in nodes[a:b + 1] if row.get("structure_type") == "倒虹吸"
                   and not row.get("is_transition")]
        selected = {id(row) for row in indexed}
        if len(selected) >= 2 and any(selected.issubset(map(id, group)) for group in matches):
            return indexed
    if len(matches) < 2:
        return matches[0] if matches else []
    points = config.get("plan_feature_points") or config.get("ip_points") or []
    if len(points) >= 2:
        def same_xy(left, right):
            return all(left.get(field) is not None and right.get(field) is not None
                       and abs(float(left[field]) - float(right[field])) <= .001 for field in ("x", "y"))
        try:
            exact = [group for group in matches
                     if same_xy(group[0], points[0]) and same_xy(group[-1], points[-1])]
        except (TypeError, ValueError):
            exact = []
        if len(exact) == 1:
            return exact[0]
    return None


def _matched_pressure_routes(project, panel, nodes):
    """Resolve saved route membership against the current hydraulic table."""
    if panel.get("water_result_current") is False or (panel.get("merged_section") or {}).get("sync_ready") is False:
        return {}
    manager = project.get("pressure_pipe_manager_data") or {}
    child_ids = {}
    for bucket in ("pipes", "segments"):
        for key, row in (manager.get(bucket) or {}).items():
            if row.get("route_key"):
                child_ids.setdefault(row["route_key"], set()).add(row.get("identity") or key)
    candidates = {key: row for key, row in (manager.get("routes") or {}).items()
                  if row.get("segment_identities") or key in child_ids}
    if not candidates or not nodes:
        return {}

    from 推求水面线.models.data_models import ChannelNode, ProjectSettings
    from 推求水面线.utils.pressure_pipe_extractor import PressurePipeDataExtractor

    try:
        settings = ProjectSettings.from_dict(panel.get("project_settings") or {})
        routes = PressurePipeDataExtractor.extract_pressure_routes(
            [ChannelNode.from_project_dict(node) for node in nodes], settings=settings)
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        return {}

    matched = {}
    for route in routes:
        saved = candidates.get(route.route_key)
        if not saved:
            continue
        identities = [segment.identity for segment in route.segments]
        if not saved.get("segment_identities"):
            # The water-profile DXF dialog immediately persists a route axis and
            # stable member keys, before the next hydraulic calculation writes
            # the route's complete identity/MC manifest.
            if child_ids.get(route.route_key) and child_ids[route.route_key].issubset(identities):
                matched[route.route_key] = route
            continue
        if saved["segment_identities"] != identities:
            continue
        start, end = saved.get("start_mc"), saved.get("end_mc")
        if (isinstance(start, (int, float)) and isinstance(end, (int, float)) and start < end
                and math.isclose(start, route.start_mc, rel_tol=0., abs_tol=SOURCE_ROUTE_ENDPOINT_TOLERANCE_M)
                and math.isclose(end, route.end_mc, rel_tol=0., abs_tol=SOURCE_ROUTE_ENDPOINT_TOLERANCE_M)):
            matched[route.route_key] = route
    return matched


def _pressure_profile_only_route_keys(project, panel, nodes):
    """Untouched profile-only hydraulic entries eligible for legacy draft cleanup."""
    manager = project.get("pressure_pipe_manager_data") or {}
    member_routes = {str(row.get("route_key") or key)
                     for bucket in ("pipes", "segments")
                     for key, row in (manager.get(bucket) or {}).items()}
    profile_fields = {"route_key", "display_name", "channel_level", "start_row_index", "end_row_index",
                      "entered_pressurized_at_row", "start_mc", "end_mc", "profile_state", "segment_identities",
                      "longitudinal_nodes", "raw_profile_polyline", "profile_segments", "design_profile",
                      "profile_points"}
    return {key for key in _matched_pressure_routes(project, panel, nodes)
            if key not in member_routes and manager["routes"][key].keys() <= profile_fields}


def _siphon_construction_parts(asset, matched):
    """Partition construction while using one already aligned specialist axis."""
    groups = [members for _, members in _node_groups(matched, split_flow_sections=True)]
    if len(groups) <= 1 or asset.get("station_start") is None or asset.get("station_end") is None:
        if matched and (flow_section := _flow_section(matched[0])):
            asset["flow_section"] = flow_section
        return [asset]

    start, end = asset["station_start"], asset["station_end"]
    bounds = [start, *(_station(group[0][1]) for group in groups[1:]), end]
    if any(station is None for station in bounds):
        return [asset]
    parts = []
    axis = asset.get("design_profile")
    provenance = (asset.get("siphon_axis_input") or {}).get("source")
    mode = asset["siphon_axis_choice"]["mode"]
    for members, begin, finish in zip(groups, bounds, bounds[1:]):
        if not start <= begin < finish <= end:
            continue
        part = deepcopy(asset)
        nodes = [node for _, node in members]
        first = nodes[0]
        if parts:
            identity = f"{asset['source_identity']}:{first.get('profile_row_id') or members[0][0]}"
            part.update(source_identity=identity, asset_id=_identity(identity, "design-"))
        part.update(station_start=begin, station_end=finish, flow_section=_flow_section(first))
        part["original_fields"]["records"] = deepcopy(nodes)
        part["alignment"]["plan_points"] = deepcopy(nodes)
        if part["section"].get("inner_diameter") is None and (diameter := _pressure_group_diameter(members)):
            part["section"]["inner_diameter"] = diameter
            mark_imported_pipe_diameter(part, diameter=diameter, source="本流量段水面线管径(m)")
        if axis:
            part_axis = clip_design_profile(axis, begin, finish)
            configure_siphon_axis(part, mode=mode, profile=part_axis, source=provenance)
            part["water_profile_design_profile"] = deepcopy(part_axis)
        parts.append(part)
    return parts or [asset]


def _special_networks(project,nodes,result,common,siphon_cover_depth,matched_routes,batch_bore_inputs):
    claimed=set()
    source_pressure_ranges = _source_pressure_ranges(nodes)
    siphons=(project.get("siphon_manager_data") or {}).get("siphons",{})
    for key,raw in siphons.items():
        config=deepcopy(raw); name=_name(config) or str(key)
        source_type=str(config.get("structure_type") or config.get("segment_type") or "倒虹吸")
        if _deferred_pit(source_type):
            _exclude_pit(result,"siphon:"+str(key),name,source_type,config,config.get("start_mc"),config.get("end_mc"))
            continue
        matched = _siphon_source_nodes(nodes, config, key, name)
        if matched is None or any((p.get("profile_row_id") or id(p)) in claimed for p in matched):
            _issue(result, f"{name}：专项纵断面未能对应到唯一倒虹吸区段",
                   code="siphon_axis_source_ambiguous", severity="warning")
            continue
        claimed.update(p.get("profile_row_id") or id(p) for p in matched)
        asset=_base_asset("siphon:"+str(key),name,"siphon","circular_siphon",config)
        if matched:
            asset["original_fields"]["records"] = deepcopy(matched)
            asset["is_test"] = bool(config.get("is_test") or config.get("test_only"))
        diameter = config.get("diameter") or _pressure_group_diameter([(None, p) for p in matched])
        for field, value in {"inner_diameter":diameter,"pipe_count":config.get("num_pipes")}.items():
            if value is not None: asset["section"].setdefault(field, value)
        mark_imported_pipe_diameter(asset, diameter=diameter, source="倒虹吸专项或水面线管径(m)")
        try:
            start, end = (_source_range_on_plan(_station(matched[0]), _station(matched[-1]), common)
                          if matched else (None, None))
            if common is not None and start is not None and end is not None and end > start:
                alignment = clip_plan_alignment(common, start, end)
            else:
                alignment = import_plan_alignment(config,fallback_points=matched)
        except (ValueError,TypeError,KeyError) as exc:
            alignment=None;_issue(result,str(exc),asset=asset,field="alignment",code="invalid_plan_alignment")
        if alignment:
            asset.update(station_start=alignment.start_station,station_end=alignment.end_station)
        asset["alignment"]={"plan_points":deepcopy(matched or config.get("plan_feature_points") or []),"elevation_reference":"pipe_axis"}
        asset["source_type"] = source_type
        axis = None if config.get("longitudinal_is_example") else _profile_source(config)
        provenance = {"kind": "water_profile", "siphon_key": str(key)} if axis else None
        requested_mode = "cover_depth" if asset["construction"].get("burial_mode") == "cover_depth" else "auto"
        state = configure_siphon_axis(asset, mode="auto", profile=axis, source=provenance,
                                      cover_depth_m=asset["construction"].get("cover_depth", siphon_cover_depth))
        if asset.get("axis_source") == "water_profile_real_elevation":
            asset["water_profile_design_profile"] = deepcopy(asset["design_profile"])
        if requested_mode == "cover_depth":
            state = configure_siphon_axis(asset, mode=requested_mode)
        parts = _siphon_construction_parts(asset, matched)
        for part in parts:
            if state["status"] in {"mismatch", "pending", "cover_estimate"}:
                result["diagnostics"].append({"code": "missing_design_profile", "severity": "warning",
                    "message": f"{name}：{state['message']}", "asset_id": part["asset_id"],
                    "source_identity": part["source_identity"], "field": "design_profile"})
            _construction_missing(part,result)
        result["networks"].append(_network("siphon:"+str(key),name,alignment,parts,{"kind":"siphon_manager_data","key":key}))
    manager=project.get("pressure_pipe_manager_data") or {}
    routes=manager.get("routes") or {}
    # The pipe bucket is the latest user-facing config; segment facts fill gaps.
    configs=deepcopy(manager.get("segments") or {})
    for key,row in (manager.get("pipes") or {}).items(): configs[key]={**configs.get(key,{}),**deepcopy(row)}
    # Retain a real saved route even when its child configuration is absent.
    # It remains an editable missing-dimension draft, never silently disappears.
    member_routes={str(c.get("route_key") or k) for k,c in configs.items()}
    for key,row in routes.items():
        if str(key) not in member_routes and key not in matched_routes:
            configs[str(key)]={**deepcopy(row),"route_key":str(key),"name":row.get("display_name") or str(key)}
    grouped={}
    for key,cfg in configs.items(): grouped.setdefault(str(cfg.get("route_key") or key),[]).append((key,cfg))
    for route_key,members in grouped.items():
        route=routes.get(route_key) or {}
        names=[route_key,route.get("display_name")]+[n for key,c in members for n in (key,_name(c),c.get("base_name"))]
        matched=_indexed_nodes(nodes,route,names)
        table_route = matched_routes.get(route_key)
        if table_route is None and not route.get("segment_identities"):
            claimed.update(p.get("profile_row_id") or id(p) for p in matched
                           if p.get("structure_type") in {"有压管道","顶管","定向钻"})
        configs_with_plan=[cfg for _,cfg in members if cfg.get("ip_points") or cfg.get("plan_elements") or cfg.get("alignment")]
        plan_source=next((cfg for cfg in configs_with_plan if len(cfg.get("ip_points") or [])>=2), route)
        assets=[]
        try:
            alignment = (clip_plan_alignment(common, table_route.start_mc, table_route.end_mc) if table_route
                         else import_plan_alignment(plan_source,fallback_points=matched))
        except (ValueError,TypeError,KeyError) as exc:
            alignment=None
            _issue(result,f"{route_key}：{exc}",code="invalid_plan_alignment",field="alignment")
        for key,cfg in members:
            label=_name(cfg) or str(key)
            source_type=str(cfg.get("structure_type") or cfg.get("segment_type") or "有压管道")
            member_nodes=_indexed_nodes(nodes,cfg,[key,label,cfg.get("base_name")])
            segment = None
            if table_route:
                segment = next((s for s in table_route.segments
                                if s.identity in (key, cfg.get("identity"), cfg.get("segment_identity"))), None)
                if segment and 0 <= segment.start_row_index <= segment.end_row_index < len(nodes):
                    member_nodes = nodes[segment.start_row_index:segment.end_row_index + 1]
                    source_type = segment.structure_type or source_type
                identified = bool(segment or (isinstance(cfg.get("start_row_index"), int)
                    and isinstance(cfg.get("end_row_index"), int)
                    and 0 <= cfg["start_row_index"] <= cfg["end_row_index"] < len(nodes)))
                if identified:
                    claimed.update(p.get("profile_row_id") or id(p) for p in member_nodes
                                   if p.get("structure_type") == source_type and source_type in {"有压管道","顶管","定向钻"})
                    if source_type == "有压管道" and cfg.get("D") is None:
                        cfg["D"] = _pressure_group_diameter([(None, p) for p in member_nodes
                                                             if p.get("structure_type") == source_type])
            a,b=cfg.get("start_mc"),cfg.get("end_mc")
            if segment and (a is None or b is None or (a == b == 0 and segment.end_mc > segment.start_mc)):
                a,b = segment.start_mc, segment.end_mc
            if a is None and member_nodes: a=_station(member_nodes[0])
            if b is None and member_nodes: b=_station(member_nodes[-1])
            if (a is None or b is None) and len(members)==1 and alignment:
                a,b=alignment.start_station,alignment.end_station
            if source_type == "有压管道" and a is not None and b is not None and alignment:
                connected = _inherited_pressure_range(source_pressure_ranges, a, b, cfg.get("D"))
                if connected is not None:
                    if (alignment.start_station - 1e-7 <= connected[0]
                            and connected[1] <= alignment.end_station + 1e-7):
                        if abs(float(a) - connected[0]) > 1e-7 or abs(float(b) - connected[1]) > 1e-7:
                            cfg["source_group_range"] = [a, b]
                            cfg["station_range_basis"] = "普通有压管延伸至相邻同径非开挖段的实际边界"
                            a,b=connected
            if alignment is not None:
                original_range = [a, b]
                a,b = _source_range_on_plan(a,b,alignment,
                    records=result.setdefault("station_boundary_adjustments", []), source="pressure:" + str(key))
                if [a, b] != original_range:
                    cfg["original_source_station_range"] = original_range
            non_open_cut=trenchless_exclusion({**cfg,"name":label,"source_type":source_type,
                "source_identity":"pressure:"+str(key),"station_start":a,"station_end":b},
                route_id="pressure_route:"+route_key)
            if non_open_cut:
                if batch_bore_inputs is not None:
                    source_nodes = _specialist_bore_nodes(cfg, member_nodes, source_type, segment)
                    if source_nodes is not None:
                        non_open_cut["original_asset_snapshot"]["source_nominal_diameter_m"] = (
                            _match_batch_bore_diameter(batch_bore_inputs, source_nodes)[0])
                plan = trenchless_plan_alignment(non_open_cut, alignment)
                if plan is not None:
                    non_open_cut["plan_elements"] = plan.elements
                exact = next((p for p in route.get("profile_segments", [])
                    if str(p.get("identity") or p.get("segment_identity") or "") == str(key)), {})
                profile = next((_profile_source(owner) for owner in (exact, route)
                    if not (owner.get("longitudinal_is_example") or owner.get("test_only"))
                    and _profile_source(owner)), None)
                if profile:
                    non_open_cut["original_asset_snapshot"]["trenchless_route_profile"] = deepcopy(profile)
                result["excluded"].append(non_open_cut)
                continue
            if _deferred_pit(source_type):
                _exclude_pit(result,"pressure:"+str(key),label,source_type,cfg,cfg.get("start_mc"),cfg.get("end_mc"))
                continue
            if any(word in source_type for word in ("隧洞","盾构")):
                result["excluded"].append({"source_identity":"pressure:"+str(key),"name":label,"source_type":source_type,
                                           "station_start":cfg.get("start_mc"),"station_end":cfg.get("end_mc"),"reason":"首版不支持该施工类型"})
                continue
            asset=_base_asset("pressure:"+str(key),label,"pipe","circular_culvert",cfg)
            for field,rawfield in (("inner_diameter","D"),("material","material_key"),("outer_diameter","outer_diameter")):
                if cfg.get(rawfield) is not None: asset["section"].setdefault(field,cfg[rawfield])
            mark_imported_pipe_diameter(asset, diameter=cfg.get("D"), source="有压管道专项管径D(m)")
            if cfg.get("wall_thickness_m") is not None:
                asset["source_water_hammer_wall_thickness_m"]=cfg["wall_thickness_m"]
            asset["construction"].setdefault("burial_mode","actual_axis")
            try:
                a,b=_float(a,"管段起桩"),_float(b,"管段止桩")
                if b<=a: raise ValueError("管段起止范围未明确或只有单点")
                if alignment and (a<alignment.start_station-1e-7 or b>alignment.end_station+1e-7): raise ValueError("子管段越出真实整线路线范围")
                asset.update(station_start=a,station_end=b)
                if cfg.get("station_range_basis"):
                    asset["station_range_basis"] = cfg["station_range_basis"]
            except ValueError as exc: _issue(result,str(exc),asset=asset,field="station_range",code="missing_segment_extent")
            asset["alignment"]={"plan_points":deepcopy(cfg.get("ip_points") or member_nodes),"elevation_reference":"pipe_axis"}
            # Whole-route actual profile takes precedence over any approximate
            # child nodes, unless an explicit child design profile is supplied.
            source = _pressure_profile_source(route, key, cfg)
            pipe_source = _pressure_axis_origin(route, cfg)
            _bind_profile(asset,source,result,"pipe_axis",pipe_source=pipe_source if alignment else None)
            if alignment is None: _issue(result,"整线真实平面路线未核对",asset=asset,field="alignment",code="invalid_plan_alignment")
            _construction_missing(asset,result);assets.append(asset)
        if assets: result["networks"].append(_network("pressure_route:"+route_key,str(route.get("display_name") or route_key),alignment,assets,{"kind":"pressure_pipe_manager_data","route_key":route_key}))
    return claimed


def _source_panel(project):
    panels = [project.get("merged_panel") or {}, project.get("water_profile_panel") or {}]
    return next((p for p in panels if p.get("calculated_nodes") or p.get("nodes")), panels[0] or panels[1])


def _saved_specialist_bore_nodes(record, source, identity, nodes, matched_routes):
    key = identity.removeprefix("pressure:")
    route_key = source.get("route_key") or str(record.get("route_id") or "").removeprefix("pressure_route:")
    route = matched_routes.get(route_key)
    source_type = source.get("source_type") or source.get("structure_type") or source.get("segment_type")
    if route is not None:
        segment = next((item for item in route.segments
                        if item.identity in (key, source.get("identity"), source.get("segment_identity"))), None)
        if segment is not None and 0 <= segment.start_row_index <= segment.end_row_index < len(nodes):
            for endpoint, value in (("station_start", segment.start_mc), ("station_end", segment.end_mc)):
                try:
                    archived = _float(record.get(endpoint), endpoint)
                except (ValueError, OverflowError):
                    return None
                if not math.isclose(archived, value, rel_tol=0., abs_tol=SOURCE_ROUTE_ENDPOINT_TOLERANCE_M):
                    return None
            members = nodes[segment.start_row_index:segment.end_row_index + 1]
            return _specialist_bore_nodes(source, members, segment.structure_type, segment)
    members = _indexed_nodes(nodes, source, [key, _name(source), source.get("base_name")])
    return _specialist_bore_nodes(source, members, source_type, None)


def with_saved_batch_bore_diameters(project):
    """Attach linked batch diameters to editable archived inputs without rebuilding the project."""
    earthwork = project.get("earthwork_panel") or {}
    inputs = earthwork.get("workbench_inputs") or {}
    excluded = inputs.get("excluded") or []
    pending = [(index, record, source) for index, record in enumerate(excluded)
               if "source_nominal_diameter_m" not in (source := record.get("original_asset_snapshot") or record)
               and is_trenchless_exclusion(record)]
    if not pending:
        return project
    panel = _source_panel(project)
    batch = _batch_trenchless_inputs(project, panel)
    if not batch:
        return project

    updated = None
    nodes = None
    for index, record, source in pending:
        source_rows = (source.get("original_fields") or {}).get("records") or source.get("records")
        identity = str(record.get("source_identity") or source.get("source_identity") or "")
        if not source_rows and identity.startswith("pressure:"):
            if nodes is None:
                nodes = [_as_dict(row) for row in (panel.get("calculated_nodes") or panel.get("nodes") or ())]
                matched_routes = _matched_pressure_routes(project, panel, nodes)
            source_rows = _saved_specialist_bore_nodes(record, source, identity, nodes, matched_routes)
        if not source_rows:
            continue
        nominal, matched = _match_batch_bore_diameter(batch, source_rows)
        if not matched or (nominal is not None and nominal == trenchless_source_nominal_diameter(source)):
            continue
        if updated is None:
            updated = list(excluded)
        updated[index] = {**record, "original_asset_snapshot": {**source, "source_nominal_diameter_m": nominal}}
    if updated is None:
        return project
    return {**project, "earthwork_panel": {**earthwork, "workbench_inputs": {**inputs, "excluded": updated}}}


def merge_workbench_profile_routes(networks, project_snapshot=None, *, saved_alignment=None, route_name=""):
    """Restore the complete hydraulic alignment in serialized viewer networks."""
    candidates = [
        (index, network) for index, network in enumerate(networks)
        if network.get("source_identity") == "water_profile"
        and (network.get("source") or {}).get("kind") == "water_profile_panel"
        and isinstance(network.get("source_route_extent"), (list, tuple))
    ]
    if not candidates:
        return networks

    if saved_alignment is None:
        from app_渠系计算前端.earthwork.project_state import source_channel_name

        panel = _source_panel(_as_dict(project_snapshot))
        if (not panel.get("calculated_nodes") or panel.get("water_result_current") is False
                or (panel.get("merged_section") or {}).get("sync_ready") is False):
            return networks
        nodes = [_as_dict(node) for node in panel["calculated_nodes"]]
        try:
            common = import_plan_alignment(panel, fallback_points=_hydraulic_original_ip_points(panel, nodes))
        except (ValueError, TypeError, KeyError):
            return networks
        saved_alignment = common.to_dict()
        route_name = source_channel_name(panel)

    extent = [saved_alignment.get("start_station"), saved_alignment.get("end_station")]
    matched = {
        index: network for index, network in candidates
        if list(network["source_route_extent"]) == extent
    }
    if not matched:
        return networks
    first = next(iter(matched))
    representative = matched[first]
    segment = representative.get("alignment") or {}
    if len(matched) == 1 and [segment.get("start_station"), segment.get("end_station")] == extent:
        return networks

    merged = deepcopy(representative)
    merged["name"] = route_name or merged.get("name") or "当前渠道工程"
    merged["alignment"] = deepcopy(saved_alignment)
    merged["assets"] = [deepcopy(asset) for network in matched.values() for asset in network.get("assets", [])]
    merged["profile_segment_ids"] = [network["network_id"] for network in matched.values()]
    merged["test_only"] = any(network.get("test_only") for network in matched.values())
    return [merged if index == first else network for index, network in enumerate(networks)
            if index == first or index not in matched]


def estimate_workbench_project_connections(inputs, project_snapshot, *, estimate_circular=True):
    """Estimate gaps from a current water profile after explicit choices are restored."""
    panel = _source_panel(_as_dict(project_snapshot))
    if (not panel.get("calculated_nodes") or panel.get("water_result_current") is False
            or (panel.get("merged_section") or {}).get("sync_ready") is False):
        return inputs
    nodes = [_as_dict(node) for node in panel["calculated_nodes"]]
    try:
        alignment = import_plan_alignment(panel, fallback_points=_hydraulic_original_ip_points(panel, nodes))
    except (ValueError, TypeError, KeyError):
        return inputs
    from ..services.estimated_connections import add_estimated_connections, estimate_circular_connection_gaps
    inputs = add_estimated_connections(inputs, nodes, alignment)
    return estimate_circular_connection_gaps(inputs) if estimate_circular else inputs


def import_batch_centerline(project_snapshot):
    project = _as_dict(project_snapshot)
    panel = _source_panel(project)
    batch = panel.get("batch_panel_compat") or project.get("batch_panel") or {}
    rows = [(index, row) for index, row in enumerate(batch.get("input_rows") or [], 3)
            if any(str(value or "").strip() for value in row)]
    if not rows:
        return None
    settings = panel.get("ui_settings") or {}
    station_text = str(settings.get("start_station_text") or batch.get("start_station")
                       or batch.get("start_station_text") or "0").strip() or "0"
    if "+" in station_text.lstrip("+"):
        kilometer, meters = station_text.split("+", 1)
        start = _float(kilometer, "起始桩号") * 1000 + _float(meters, "起始桩号")
    else:
        start = _float(station_text, "起始桩号")
    name = str(batch.get("channel_name") or settings.get("channel_name") or "批量计算表格线路")
    project_settings = panel.get("project_settings") or {}
    multiplier = project_settings.get("管道默认转弯半径倍数n", project_settings.get("pipe_turn_radius_n"))
    return _build_batch_centerline(rows, start, name, {"kind": "batch_centerline"},
                                  radius_multiplier=multiplier)


def import_batch_centerline_file(path):
    """Read an independent batch workbook and return its original plan alignment."""
    from ..services.batch_water_profile import read_batch_workbook

    rows, metadata = read_batch_workbook(path, for_centerline=True)
    source = {"kind": "batch_centerline", "path": metadata["source_path"],
              "sha256": metadata["source_sha256"], "sheet": metadata["source_sheet"]}
    start = _float(metadata["start_station"], "起始桩号")
    return _build_batch_centerline(list(zip(metadata["source_rows"], rows)), start,
                                   metadata["channel_name"], source)


def _build_batch_centerline(rows, start, name, source, *, radius_multiplier=None):
    from app_渠系计算前端.batch.schema import (COL_BUILDING_NAME, COL_D, COL_SECTION_TYPE,
        COL_SEGMENT, COL_TURN_RADIUS, COL_X, COL_Y, normalize_project_section_type)
    from 推求水面线.shared.turn_radius import (DEFAULT_PIPE_TURN_RADIUS_N, apply_default_turn_radii,
        is_pipe_radius_node)

    if len(rows) < 2:
        raise ValueError("批量计算表格至少需要两个中心轴线坐标点。")
    points = []
    for index, row in rows:
        if len(row) <= COL_TURN_RADIUS:
            raise ValueError(f"批量计算表格第 {index} 行缺少坐标或转弯半径列。")
        points.append({
            "x": _float(row[COL_X], f"第 {index} 行 X 坐标"),
            "y": _float(row[COL_Y], f"第 {index} 行 Y 坐标"),
            "turn_radius": _float(str(row[COL_TURN_RADIUS] or "0").strip() or "0", f"第 {index} 行转弯半径"),
            "source_row": index,
            "structure_type": normalize_project_section_type(row[COL_SECTION_TYPE]),
            "name": str(row[COL_BUILDING_NAME] or ""),
            "flow_section": str(row[COL_SEGMENT] or ""),
            "D": row[COL_D],
        })
    multiplier = DEFAULT_PIPE_TURN_RADIUS_N if radius_multiplier is None else radius_multiplier
    apply_default_turn_radii(points, multiplier=multiplier)
    for offset, point in enumerate(points[1:-1], 1):
        if point["turn_radius"]:
            continue
        raw_type = str(point["structure_type"] or "")
        if not (is_pipe_radius_node(point) or "管" in raw_type or "倒虹吸" in raw_type):
            continue
        before, after = points[offset - 1], points[offset + 1]
        incoming = math.atan2(point["y"]-before["y"], point["x"]-before["x"])
        outgoing = math.atan2(after["y"]-point["y"], after["x"]-point["x"])
        if abs(math.remainder(outgoing-incoming, math.tau)) > 1e-9:
            raise ValueError(f"第 {point['source_row']} 行管道转角缺少转弯半径，请填写管径或转弯半径。")
    alignment = build_ip_alignment(points, start_station=start, minimum_straight=0.0)
    return _network("batch-centerline:" + name, name, alignment, [], source)


def import_workbench_project(project_snapshot, *, siphon_cover_depth=DEFAULT_SIPHON_COVER_M):
    """Return networks/pits/excluded/diagnostics; incomplete objects remain drafts."""
    project=deepcopy(_as_dict(project_snapshot))
    result={"networks":[],"pits":[],"excluded":[],"diagnostics":[]}
    panel=_source_panel(project)
    saved_lining = (panel.get("extra_caches") or {}).get("custom_struct_thickness")
    batch_bore_inputs = _batch_trenchless_inputs(project, panel)
    nodes=[_as_dict(n) for n in (panel.get("calculated_nodes") or panel.get("nodes") or [])]
    # Build the entire source route before grouping structures, preserving the
    # original MC convention and all transitions/curves between groups.
    try:
        source_ips=_hydraulic_original_ip_points(panel,nodes)
        common=import_plan_alignment(panel,fallback_points=source_ips)
    except (ValueError,TypeError,KeyError) as exc:
        common=None
        if nodes: _issue(result,str(exc),code="invalid_plan_alignment",field="alignment")
    matched_routes = _matched_pressure_routes(project, panel, nodes) if common is not None else {}
    claimed=_special_networks(project,nodes,result,common,siphon_cover_depth,matched_routes,batch_bore_inputs)
    stored_routes = (project.get("pressure_pipe_manager_data") or {}).get("routes") or {}
    member_sources = {}
    for route_key, route in matched_routes.items():
        for segment in route.segments:
            if segment.structure_type not in {"有压管道", "顶管", "定向钻"}:
                continue
            if 0 <= segment.start_row_index <= segment.end_row_index < len(nodes):
                for row in nodes[segment.start_row_index:segment.end_row_index + 1]:
                    if row.get("structure_type") == segment.structure_type:
                        member_sources.setdefault(id(row), set()).add((route_key, segment.identity))
    # Keep specialist rows as boundaries between ordinary source groups, even
    # when the specialist object itself has already been created.
    groups=_node_groups([n for n in nodes if not n.get("is_transition")], claimed, split_flow_sections=True)
    source_ranges=_hydraulic_group_ranges(groups,common,
        adjustment_records=result.setdefault("station_boundary_adjustments", []))
    channel_assets=[]
    gate_assets = []
    for group_index,((rawtype,name),members) in enumerate(groups):
        values=[p for _,p in members]
        if all((p.get("profile_row_id") or id(p)) in claimed for p in values):
            continue
        identity="water_profile:"+str(values[0].get("profile_row_id") or (rawtype+":"+name+":"+str(members[0][0])))
        a,b=source_ranges[group_index]
        route, source = None, None
        if rawtype in {"有压管道", "顶管", "定向钻"}:
            route, source = _table_pressure_source(values, member_sources, stored_routes)
        non_open_cut=trenchless_exclusion({"name":name or rawtype,"source_type":rawtype,
            "source_identity":identity,"station_start":a,"station_end":b,"original_fields":{"records":values}},
            route_id="water_profile")
        if non_open_cut:
            if batch_bore_inputs is not None:
                non_open_cut["original_asset_snapshot"]["source_nominal_diameter_m"] = (
                    _match_batch_bore_diameter(batch_bore_inputs, values)[0])
            if source:
                non_open_cut["original_asset_snapshot"]["trenchless_route_profile"] = deepcopy(source)
            plan = trenchless_plan_alignment(non_open_cut, common)
            if plan is not None:
                non_open_cut["plan_elements"] = plan.elements
            result["excluded"].append(non_open_cut)
            continue
        if _is_sluice_gate(rawtype):
            if a is None:
                _issue(result, f"{name or rawtype}缺少闸中心桩号", code="missing_gate_station")
            else:
                gate_assets.append(_gate_asset(identity, name, rawtype, values[0], a))
            continue
        if _deferred_pit(rawtype):
            _exclude_pit(result,identity,name,rawtype,values,_station(values[0]),_station(values[-1]))
            continue
        if rawtype not in TYPE_MAP:
            result["excluded"].append({"source_identity":identity,"name":name or rawtype,"source_type":rawtype,
                                       "station_start":_station(values[0]),"station_end":_station(values[-1]),"reason":"首版未纳入该结构类型"})
            continue
        kind,stype=TYPE_MAP[rawtype]
        try:
            converted=adapt_profile_nodes(values,source={"kind":"workbench_source"})
            section=deepcopy(converted["assets"][0]["section"]) if converted.get("assets") else {}
        except (ValueError,TypeError) as exc:
            # One unresolved source row must not hide the other editable objects.
            section={}
            _issue(result,f"{name or rawtype}：设计节点尚未完整核对：{exc}",code="invalid_source_node")
        section.update(deepcopy(values[0].get("section") or {}))
        params = values[0].get("section_params") or {}
        if stype == "aqueduct_u":
            for key, source_key in (("u_arc_angle_degrees", "theta_deg"), ("u_side_angle_degrees", "alpha_deg")):
                if params.get(source_key) is not None: section.setdefault(key, params[source_key])
        if stype == "flat_bottom_tunnel":
            if section.get("inner_width") is not None: section.setdefault("bottom_width", section["inner_width"])
        if stype == "horseshoe_tunnel":
            section.setdefault("horseshoe_type", 2 if "Ⅱ" in rawtype else 1)
        if stype == "arch_tunnel":
            if params.get("theta_deg") is not None: section.setdefault("arch_angle_degrees", params["theta_deg"])
        if stype in {"circular_tunnel", "flat_bottom_tunnel"} and not section.get("inner_diameter") and section.get("inner_radius"):
            section["inner_diameter"] = 2*section["inner_radius"]
        asset=_base_asset(identity,name or rawtype,kind,stype,values[0]);asset["section"]=section
        if kind in {"open_channel", "culvert"}:
            asset["water_profile_lining"] = _water_profile_lining(values, kind, stype, saved_lining)
        if kind == "tunnel":
            from ..services.tunnel_source_parameters import inherit_tunnel_parameters
            inherit_tunnel_parameters(asset, values[0], panel)
        mark_imported_pipe_diameter(asset, diameter=params.get("D", params.get("直径D")), source="水面线节点管径D(m)")
        asset["source_type"]=rawtype
        if kind == "aqueduct":
            asset["quantity_scope_notes"] = ["槽身按水面线净空和用户厚度计量；拉杆、支承、墩台及基础按离散构件输入计量，未输入的构件仍属缺项"]
        if kind == "tunnel":
            asset["quantity_scope_notes"] = ["洞挖、衬砌和喷护按用户施工层厚计量；超挖环隙列入回填量，具体填充材质须按设计设置；排水孔、锚杆和灌浆按独立计量规则输入"]
        asset["original_fields"]={"records":deepcopy(values),"kind":"water_profile_panel"}
        # Keep an explicit independent copy of actual design top, never water depth.
        tops=[{"station":_station(v),"elevation":v.get("top_elevation"),"reference":v.get("top_elevation_reference")} for v in values if v.get("top_elevation") is not None]
        asset["source_top_elevations"]=tops
        # The main node's structure_height defines the stored top. Retain this
        # source semantic until the section template resolves net/outer top.
        asset["top_elevation_reference"]=values[0].get("top_elevation_reference") or "source_structure_height_top"
        a,b=source_ranges[group_index]
        if a is not None and b is not None and b>a:
            asset.update(station_start=a,station_end=b)
        else: _issue(result,"对象只有单个桩号或范围不完整，须明确施工区段",asset=asset,field="station_range",code="missing_segment_extent")
        asset["alignment"]={"plan_points":deepcopy(values),"elevation_reference":"pipe_axis" if kind in {"pipe","siphon"} else "inner_invert"}
        if kind == "siphon":
            mode = "cover_depth" if asset["construction"].get("burial_mode") == "cover_depth" else "auto"
            state = configure_siphon_axis(asset, mode=mode,
                                          cover_depth_m=asset["construction"].get("cover_depth", siphon_cover_depth))
            result["diagnostics"].append({"code": "missing_design_profile", "severity": "warning",
                "message": f"{asset['name']}：{state['message']}", "asset_id": asset["asset_id"],
                "source_identity": asset["source_identity"], "field": "design_profile"})
        elif kind == "pipe":
            if source:
                pipe_source = _pressure_axis_origin(route)
                _bind_profile(asset, source, result, "pipe_axis", pipe_source=pipe_source)
            else:
                _issue(result,"请选择导入设计纵断面或按管顶覆土生成",asset=asset,field="design_profile",code="missing_design_profile")
            if "design_profile" not in asset:
                asset["construction"].setdefault("burial_mode","cover_depth")
        else:
            boundary_extensions=[]
            try:
                explicit=_hydraulic_profile_for_range(values,nodes,a,b,boundary_extensions)
            except (ValueError,TypeError) as exc:
                explicit=None
                _issue(result,str(exc),asset=asset,field="design_profile",code="missing_design_profile")
            _bind_profile(asset,explicit,result)
            if boundary_extensions:asset["profile_boundary_extensions"]=boundary_extensions
            asset["profile_boundary_basis"]="actual_hydraulic_bottom_elevations_at_source_structure_boundaries"
        asset["station_range_basis"]="surface_canals_follow_source_MC_boundaries_buried_inlets_outlets_preserved"
        original_range = [_station(values[0]), _station(values[-1])]
        if rawtype == "有压管道" and [a, b] != original_range:
            asset["original_fields"]["source_group_range"] = original_range
            asset["station_range_basis"] = "普通有压管延伸至相邻同径非开挖段的实际边界"
        asset["source_transitions"]=[deepcopy(n) for n in nodes if n.get("is_transition")
            and a is not None and b is not None and _station(n) is not None and a<=_station(n)<=b]
        if asset["source_transitions"]:
            asset["transition_treatment"]="渐变长度保留水面线计算结果；渠底高程连接相邻实际水力节点；施工断面按对应渠段分段计量，渐变局部异形构造未另计"
        if rawtype=="明渠-圆形":
            _issue(result,"完整圆形管渠已按封闭施工外包导入；保留原明流水力分类",asset=asset,code="circular_source_semantics",severity="info")
        if common is None: _issue(result,"主工程真实平面路线未核对",asset=asset,field="alignment",code="invalid_plan_alignment")
        _construction_missing(asset,result);channel_assets.append(asset)
    if channel_assets or gate_assets:
        from ..services.sluice_gate import select_gate_reference

        if gate_assets:
            gate_batch = _gate_batch_inputs(project, panel)
            settings = panel.get("project_settings")
            source_nodes = []
            for node in nodes:
                source_type = str(node.get("structure_type") or "")
                if node.get("is_transition") or node.get("is_auto_inserted_channel") or _is_sluice_gate(source_type):
                    continue
                if source_type.startswith(("明渠", "暗涵")):
                    source_nodes.append(node)
                else:
                    source_nodes.append({key: node.get(key) for key in ("flow_section", "flow", "Q")})
        for gate in gate_assets:
            reference = select_gate_reference(gate, channel_assets)
            if reference:
                gate["gate_reference_asset_id"] = reference["asset_id"]
            gate["water_profile_lining"] = gate_reference_lining("rect_channel", saved_lining)
            _gate_hydraulic_inputs(gate, reference, source_nodes, gate_batch, settings)
        result["networks"].insert(0,_network("water_profile",str(panel.get("project_settings",{}).get("project_name") or "当前渠道工程"),common,channel_assets + gate_assets,{"kind":"water_profile_panel"}))
    for network in result["networks"]:
        spans=sorted((a.get("station_start"),a.get("station_end")) for a in network["assets"] if a.get("station_start") is not None and a.get("station_end") is not None)
        if network["alignment"] and spans:
            start,end=network["alignment"].start_station,network["alignment"].end_station
            cursor=start
            for a,b in spans:
                if a>cursor+1e-7:
                    known=[e for e in result["excluded"] if e.get("station_start") is not None and e.get("station_end") is not None
                           and e["station_start"]<=cursor+1e-7 and e["station_end"]>=a-1e-7]
                    if known:
                        _issue(result,f"{network['name']} 桩号 {cursor:.3f}—{a:.3f} 为已明示排除的 {known[0].get('source_type','施工对象')}",
                               code="excluded_design_range",station=cursor,severity="info")
                    else:
                        _issue(result,f"{network['name']} 桩号 {cursor:.3f}—{a:.3f} 缺少结构/过渡设计",code="unassigned_design_range",station=cursor)
                cursor=max(cursor,b)
            if cursor<end-1e-7: _issue(result,f"{network['name']} 末段 {cursor:.3f}—{end:.3f} 尚未分配施工范围",code="unassigned_design_range",station=cursor)
        network["missing_fields"]=sorted({f for a in network["assets"] for f in a.get("missing_fields",[])})
        network["test_only"]=bool(network["test_only"] or project.get("test_only"))
    if not result["networks"] and not result["pits"] and not trenchless_exclusions(result):
        _issue(result,"当前工程没有可导入的渠道、暗涵、压力管道、倒虹吸、渡槽、隧洞或闸设计成果",code="no_design_sources")
    cropped=[]
    for network in result["networks"]:
        complete=[a for a in network["assets"] if a.get("station_start") is not None and a.get("station_end") is not None]
        point_gates = [a for a in network["assets"] if a.get("section_type") == "sluice_gate"]
        incomplete=[a for a in network["assets"] if a not in complete and a not in point_gates]
        if network["alignment"] is None or not complete:
            cropped.append(network);continue
        ranges=[]
        for asset in sorted(complete,key=lambda a:a["station_start"]):
            if not ranges or asset["station_start"]>ranges[-1]["end"]+1e-7:
                ranges.append({"start":asset["station_start"],"end":asset["station_end"],"assets":[asset]})
            else:
                ranges[-1]["end"]=max(ranges[-1]["end"],asset["station_end"]);ranges[-1]["assets"].append(asset)
        unmatched_gates = []
        for gate in point_gates:
            station = gate["gate_station"]
            span = next((item for item in ranges if item["start"] - 1e-7 <= station <= item["end"] + 1e-7), None)
            if span is None:
                unmatched_gates.append(gate)
            else:
                span["assets"].append(gate)
        for i,span in enumerate(ranges):
            copy=deepcopy(network);copy["assets"]=span["assets"]
            copy["alignment"]=clip_plan_alignment(network["alignment"],span["start"],span["end"])
            copy["source_route_extent"]=[network["alignment"].start_station,network["alignment"].end_station]
            if len(ranges)>1: copy["network_id"]+=f"-{i+1}"
            cropped.append(copy)
        if unmatched_gates:
            copy = deepcopy(network)
            copy["assets"] = unmatched_gates
            copy["network_id"] += "-gates"
            cropped.append(copy)
        if incomplete:
            copy=deepcopy(network);copy["alignment"]=None;copy["assets"]=incomplete;copy["network_id"]+="-unresolved";cropped.append(copy)
    result["networks"]=cropped
    from ..services.transition_connections import (
        collect_transition_candidates, automatically_apply_same_section_connections,
    )
    result["transition_candidates"] = collect_transition_candidates(result, nodes, common, settings=panel.get("project_settings"))
    result = automatically_apply_same_section_connections(result)
    normalize_construction_inputs(result)
    return result
