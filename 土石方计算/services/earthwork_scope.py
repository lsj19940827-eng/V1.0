"""Mandatory earthwork scope shared by source imports and every calculator.

Trenchless methods keep their original design facts. Their circular bore is
measured separately from open-cut sections, cover generation and support.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import math
import re

from .contracts import ConstructionInputError


TRENCHLESS_EXCLUSION_RULE = "trenchless_no_earthwork_v1"
LEGACY_TRENCHLESS_EXCAVATION_RULE = "trenchless_single_circular_bore_v1"
NOMINAL_TRENCHLESS_EXCAVATION_RULE = "trenchless_single_circular_bore_nominal_diameter_v2"
TRENCHLESS_EXCAVATION_RULE = "trenchless_single_circular_bore_editable_diameter_v3"
TRENCHLESS_RADIAL_CLEARANCE_M = .2
TRENCHLESS_SECTION_OVERRIDE = "trenchless_section_override"
_FACT_FIELDS = (
    "structure_type", "source_type", "segment_type", "section_type", "kind",
    "construction_method", "construction_type", "construction_mode", "installation_mode",
    "method", "name", "base_name", "display_name", "remarks", "remark", "notes", "note",
    "施工方式", "施工方法", "施工工法", "工法", "结构形式", "建筑物名称", "备注",
)
_FACT_CONTAINERS = ("construction", "original_fields", "records")
_ALIASES = (
    ("顶管", {"pipejacking", "jacking", "jackedpipe", "pipejack"}),
    ("定向钻", {"directionaldrill", "directionaldrilling", "hdd", "horizontaldirectionaldrilling"}),
)
_CONTEXT_FIELDS = {"name","base_name","display_name","建筑物名称","remarks","remark","notes","note","备注"}


def _method_text(raw, label, *, contextual):
    if not contextual:
        return label in raw
    # “定向钻后段”“与顶管相接” describe an adjacent open-cut pipe. Names
    # and free text must not turn these relational references into a method.
    escaped=re.escape(label)
    cleaned=re.sub(r"(?:非|不采用|不用|不使用|取消)\s*"+escaped,"",raw)
    cleaned=re.sub(r"(?:邻近|附近|相邻|衔接|连接|相接|接|与)\s*"+escaped,"",cleaned)
    cleaned=re.sub(escaped+r"(?:施工)?(?:管)?(?:区)?(?:段)?(?:之前|之后|前后|前|后|邻近|附近|相邻|接头|连接段|进口|出口)","",cleaned)
    return label in cleaned


def trenchless_method(value):
    """Return the explicit method and matched source field; do not inspect caches.

    Historical workbench assets can retain the construction method only in the
    original source records or remarks while their hydraulic type is 有压管道.
    Restrict traversal to those source/construction facts, never saved results,
    unrelated component metadata or general quantity-scope explanations.
    """
    def facts(item, path=""):
        if isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                yield from facts(child, f"{path}[{index}]")
        elif isinstance(item, dict):
            for key in _FACT_FIELDS:
                raw = item.get(key)
                if isinstance(raw, str):
                    yield f"{path}.{key}".lstrip("."), key, raw
            for key in _FACT_CONTAINERS:
                if isinstance(item.get(key), (dict, list, tuple)):
                    yield from facts(item[key], f"{path}.{key}".lstrip("."))

    # Explicit engineering fields take priority over display names and notes.
    values=list(facts(value))
    values.sort(key=lambda item:item[1] in _CONTEXT_FIELDS)
    for path, key, raw in values:
        normalized = re.sub(r"[\s_\-]+", "", raw).lower()
        for label, aliases in _ALIASES:
            if _method_text(raw,label,contextual=key in _CONTEXT_FIELDS) or (label == "定向钻" and "定向穿越" in raw) or normalized in aliases:
                return {"method": label, "field": path, "value": raw}
    return None


def trenchless_exclusion(asset, *, route_id=None):
    """Return an open-cut exclusion; its original facts can also define a bore."""
    matched = trenchless_method(asset)
    if matched is None:
        return None
    result = {"code": TRENCHLESS_EXCLUSION_RULE, "rule": TRENCHLESS_EXCLUSION_RULE,
              "asset_id": asset.get("asset_id"), "source_identity": asset.get("source_identity"),
              "name": asset.get("name") or asset.get("base_name") or matched["method"],
              "section_type": asset.get("section_type"),
              "source_type": asset.get("source_type") or asset.get("structure_type") or asset.get("segment_type"),
              "station_start": asset.get("station_start", asset.get("start_mc")),
              "station_end": asset.get("station_end", asset.get("end_mc")),
              "construction_method": matched["method"], "matched_source_field": matched["field"],
              "matched_source_value": matched["value"],
              "reason": _scope_reason(matched["method"]),
              "original_asset_snapshot": deepcopy(asset)}
    if route_id is not None:
        result["route_id"] = route_id
    if TRENCHLESS_SECTION_OVERRIDE in asset:
        result[TRENCHLESS_SECTION_OVERRIDE] = result["original_asset_snapshot"].pop(TRENCHLESS_SECTION_OVERRIDE)
    return serializable_trenchless_facts(result)


def _scope_reason(method):
    return f"{method}段不计明挖、一般回填及新增填筑，按单圆孔另计洞挖量"


def _record_method(record):
    source = record.get("original_asset_snapshot") or record
    match = trenchless_method(source) or trenchless_method(record)
    return (match or {}).get("method")


def is_trenchless_exclusion(record):
    source = record.get("original_asset_snapshot") or record
    return (source.get("enabled", True) and record.get("enabled", True)
            and (record.get("code") == TRENCHLESS_EXCLUSION_RULE
                 or _record_method(record) is not None))


def current_exclusion_records(records):
    """Use current scope notes in new results while retaining saved input facts."""
    current = deepcopy(records)
    for i, record in enumerate(current):
        if (method := _record_method(record)) is not None:
            current[i] = serializable_trenchless_facts({**record, "reason":_scope_reason(method)})
    return current


def serializable_trenchless_facts(value):
    """Keep invalid entered numbers inspectable without allowing invalid JSON."""
    if isinstance(value, dict):
        return {key:serializable_trenchless_facts(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(serializable_trenchless_facts(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def trenchless_live_route_id(network):
    return network.get("route_id") or network.get("source_identity") or network.get("network_id")


def trenchless_exclusions(inputs):
    """Recognize both saved import records and live route assets."""
    networks = (inputs.get("networks") or []) if "networks" in inputs else [inputs]
    records = [record for record in inputs.get("excluded", []) if is_trenchless_exclusion(record)]
    for network in networks:
        route_id = trenchless_live_route_id(network)
        for asset in network.get("assets", []):
            if asset.get("enabled", True):
                record = trenchless_exclusion(asset, route_id=route_id)
                if record:
                    records.append(record)
    return records


def _exclusion_matches_source(exclusion, owner):
    from .imported_design_profiles import _alignment_points, _route_namespace

    route_id = exclusion.get("route_id")
    namespace = _route_namespace(owner)[0]
    if not namespace or route_id not in {None, namespace}:
        return False
    points = defaultdict(set)
    for point in _alignment_points(owner):
        xy = point.get("x"), point.get("y")
        row_id = point.get("profile_row_id")
        if None not in xy and row_id:
            points[xy].add(str(row_id))
    original = exclusion.get("original_asset_snapshot") or {}
    rows = (original.get("original_fields") or {}).get("records") or original.get("records") or []
    # Coincident boundary rows can lose an ID when the alignment is built.
    # The source coordinates and at least one surviving row still identify it.
    coordinates = [(row.get("x"), row.get("y")) for row in rows]
    return (len(rows) >= 2 and all(xy in points for xy in coordinates)
            and any(str(row.get("profile_row_id")) in points[xy]
                    for xy, row in zip(coordinates, rows)))


def _route_trenchless_intervals(exclusions, owner, start, end, *, allow_partial, tolerance=1e-6):
    from .section_scheme_bindings import _route

    route_id = _route(owner)
    source = owner.get("source") or {}
    managed_route = ("pressure_route:" + str(source["route_key"])
                     if source.get("kind") == "pressure_pipe_manager_data" and source.get("route_key") else None)
    for exclusion in exclusions:
        left = _number(exclusion.get("station_start"))
        right = _number(exclusion.get("station_end"))
        if left is None or right is None or right <= left:
            continue
        if allow_partial:
            left, right = max(start, left), min(end, right)
            if right <= left:
                continue
        elif left < start - tolerance or right > end + tolerance:
            continue
        if (exclusion.get("route_id") in {route_id, managed_route} - {None, ""}
                or _exclusion_matches_source(exclusion, owner)):
            yield left, right


def trenchless_intersections(exclusions, owner, start, end):
    """Return this route's non-open-cut ranges clipped to the requested interval."""
    return sorted(_route_trenchless_intervals(exclusions, owner, start, end, allow_partial=True))


def trenchless_range_covered(exclusions, owner, start, end, *, allow_partial=False):
    """Return whether the station range is covered by this route's trenchless records."""
    tolerance = 1e-6
    if start is None or end is None or end <= start + tolerance:
        return False
    intervals = sorted(_route_trenchless_intervals(exclusions, owner, start, end, allow_partial=allow_partial))
    boundary = start
    for left, right in intervals:
        if left > boundary + tolerance:
            return False
        boundary = max(boundary, right)
    return boundary >= end - tolerance


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def trenchless_edit_key(record_or_row):
    """Identify one source span by explicit route, method and exact chainages."""
    route = record_or_row.get("route_id")
    identifier = record_or_row.get("source_identity") or record_or_row.get("asset_id")
    if not route or not identifier:
        return None
    start = _number(record_or_row.get("station_start", record_or_row.get("start_mc")))
    end = _number(record_or_row.get("station_end", record_or_row.get("end_mc")))
    if start is None or end is None or end <= start:
        return None
    method = _record_method(record_or_row)
    if method not in ("顶管", "定向钻"):
        return None
    return str(route), str(identifier), method, start, end


def _bore_options(radial_clearance_m, bore_diameter_override_m):
    clearance = TRENCHLESS_RADIAL_CLEARANCE_M if radial_clearance_m is None else _number(radial_clearance_m)
    if clearance is None or clearance < 0:
        raise ConstructionInputError("单侧预留须为有限非负数。")
    override = _number(bore_diameter_override_m)
    if bore_diameter_override_m is not None and (override is None or override <= 0):
        raise ConstructionInputError("开挖直径须为有限正数。")
    return clearance, override


def trenchless_bore_values(nominal_diameter_m, length_m, radial_clearance_m, bore_diameter_override_m):
    """Return effective diameter, area and volume for the edited circular bore."""
    clearance, override = _bore_options(radial_clearance_m, bore_diameter_override_m)
    diameter, length = _number(nominal_diameter_m), _number(length_m)
    bore = override
    if bore is None and diameter is not None and diameter > 0:
        bore = _number(diameter + 2 * clearance)
    radius = bore / 2 if bore is not None else None
    area = _number(math.pi * (radius * radius)) if radius is not None else None
    volume = _number(area * length) if area is not None and length is not None and length > 0 else None
    return bore, area, volume


def _with_bore_options(record, options):
    if (record.get(TRENCHLESS_SECTION_OVERRIDE) or {}) == options:
        return record
    updated = dict(record)
    if options:
        updated[TRENCHLESS_SECTION_OVERRIDE] = options
    else:
        updated.pop(TRENCHLESS_SECTION_OVERRIDE, None)
    return updated


def update_trenchless_section(inputs, key, *, bore_diameter_override_m, radial_clearance_m):
    """Save bore options to the exact live span, using its archive only if needed."""
    clearance, override = _bore_options(radial_clearance_m, bore_diameter_override_m)
    if not isinstance(key, tuple) or len(key) != 5:
        raise ConstructionInputError("本施工段缺少稳定的线路或区段标识。")
    options = {}
    if clearance != TRENCHLESS_RADIAL_CLEARANCE_M:
        options["radial_clearance_m"] = clearance
    if override is not None:
        options["bore_diameter_override_m"] = override

    networks = inputs.get("networks") if "networks" in inputs else [inputs]
    for network_index in reversed(range(len(networks or ()))):
        network = networks[network_index]
        route = trenchless_live_route_id(network)
        if route is None or str(route) != key[0]:
            continue
        assets = network.get("assets", ())
        for asset_index in reversed(range(len(assets))):
            asset = assets[asset_index]
            if (str(asset.get("source_identity") or asset.get("asset_id")) != key[1]
                    or not asset.get("enabled", True) or asset.get("calculation_deferred")
                    or asset.get("pipe_profile_choice") == "pending_gap"
                    or trenchless_edit_key({**asset, "route_id": route}) != key):
                continue
            updated = _with_bore_options(asset, options)
            if updated is asset:
                return inputs
            assets = list(assets)
            assets[asset_index] = updated
            network = {**network, "assets": assets}
            if "networks" not in inputs:
                return network
            networks = list(networks)
            networks[network_index] = network
            return {**inputs, "networks": networks}

    records = inputs.get("excluded", ())
    for index in reversed(range(len(records))):
        record = records[index]
        if trenchless_edit_key(record) != key or not is_trenchless_exclusion(record):
            continue
        updated = _with_bore_options(record, options)
        if updated is record:
            return inputs
        records = list(records)
        records[index] = updated
        return {**inputs, "excluded": records}
    raise ConstructionInputError("当前工程找不到该非开挖施工段。")


def _legacy_diameter(source):
    section = source.get("section") or {}
    params = source.get("section_params") or {}
    pipes = section.get("pipes") or []
    pipe = pipes[0] if len(pipes) == 1 else {}
    explicit = (section.get("outer_diameter"), source.get("outer_diameter"), pipe.get("outer_diameter"))
    nominal = (source.get("D"), section.get("nominal_diameter_m"), params.get("D"),
               params.get("直径D"), section.get("inner_diameter"))
    return next((number for value in (*explicit, *nominal)
                 if (number := _number(value)) is not None and number > 0), None)


def _legacy_source_diameter(source):
    direct = _legacy_diameter(source)
    if direct is not None:
        return direct
    original = source.get("original_fields") or {}
    direct = _legacy_diameter(original)
    if direct is not None:
        return direct
    records = original.get("records") or source.get("records") or []
    diameters = {d for record in records if (d := _legacy_diameter(record)) is not None}
    return next(iter(diameters)) if len(diameters) == 1 else None


def _nominal_diameter(source):
    section = source.get("section") or {}
    params = source.get("section_params") or {}
    pipes = section.get("pipes") or []
    pipe = pipes[0] if len(pipes) == 1 else {}
    values = (params.get("D"), params.get("直径D"), source.get("D"),
              section.get("nominal_diameter_m"), pipe.get("nominal_diameter_m"))
    return next((number for value in values if (number := _number(value)) is not None and number > 0), None)


def trenchless_source_nominal_diameter(source):
    """Read the matched batch value or an older project's recorded nominal diameter."""
    if "source_nominal_diameter_m" in source:
        diameter = _number(source["source_nominal_diameter_m"])
        return diameter if diameter is not None and diameter > 0 else None
    original = source.get("original_fields") or {}
    records = original.get("records") or source.get("records") or []
    diameters = {d for record in records if (d := _nominal_diameter(record)) is not None}
    if diameters:
        return next(iter(diameters)) if len(diameters) == 1 else None
    return _nominal_diameter(original) or _nominal_diameter(source)


def _bore_length(source, start, end):
    from .design_profiles import profile_spatial_length

    construction = source.get("construction") or {}
    is_assumed = (construction.get("burial_mode") == "cover_depth"
        or source.get("axis_source") == "terrain_and_user_cover_depth"
        or source.get("longitudinal_is_example") or source.get("test_only"))
    if not is_assumed:
        for owner in (source, source.get("original_fields") or {},
                      {"design_profile":source.get("trenchless_route_profile")}):
            if any(owner.get(key) for key in ("design_profile", "raw_profile_polyline", "longitudinal_nodes",
                                              "profile_points")):
                try:
                    length = _number(profile_spatial_length(owner, start, end))
                    if length is not None and length > 0:
                        return length, "design_profile_spatial"
                except (ValueError, TypeError, KeyError):
                    # Incomplete legacy design lines cannot supply the bore length.
                    continue
    length = _number(end-start)
    return length, "plan_chainage" if length is not None else None


def trenchless_excavation_quantities(records, open_cut_volume=0., *, policy=TRENCHLESS_EXCAVATION_RULE):
    """Calculate a single circular bore per explicitly declared construction span."""
    if policy not in (TRENCHLESS_EXCAVATION_RULE, NOMINAL_TRENCHLESS_EXCAVATION_RULE,
                      LEGACY_TRENCHLESS_EXCAVATION_RULE):
        return {}
    legacy = policy == LEGACY_TRENCHLESS_EXCAVATION_RULE
    editable = policy == TRENCHLESS_EXCAVATION_RULE
    rows = []
    positions = {}
    for record in records:
        if not is_trenchless_exclusion(record):
            continue
        source = record.get("original_asset_snapshot") or record
        method = _record_method(record)
        if method not in ("顶管", "定向钻"):
            continue
        start, end = (_number(record.get(k)) for k in ("station_start", "station_end"))
        identifier = record.get("source_identity") or record.get("asset_id")
        identity = (record.get("route_id"), identifier, method, start, end)
        diameter = _legacy_source_diameter(source) if legacy else trenchless_source_nominal_diameter(source)
        length, length_basis = (None, None)
        if start is not None and end is not None and end > start:
            length, length_basis = _bore_length(source, start, end)
        override = None
        clearance = TRENCHLESS_RADIAL_CLEARANCE_M
        issue = None
        if editable:
            try:
                config = record.get(TRENCHLESS_SECTION_OVERRIDE, {})
                if not isinstance(config, dict):
                    raise ConstructionInputError("开挖直径和单侧预留设置无效。")
                clearance, override = _bore_options(config.get("radial_clearance_m"),
                                                     config.get("bore_diameter_override_m"))
                bore_diameter, area, volume = trenchless_bore_values(diameter, length, clearance, override)
            except ConstructionInputError as error:
                bore_diameter = area = volume = None
                issue = str(error)
        else:
            bore_diameter = diameter + 2*TRENCHLESS_RADIAL_CLEARANCE_M if diameter is not None else None
            radius = bore_diameter/2 if bore_diameter is not None else None
            area = _number(math.pi*(radius*radius)) if radius is not None else None
            volume = _number(area*length) if area is not None and length is not None else None
        diameter_label = "有效管径" if legacy else "批量计算表公称直径"
        missing = [label for value, label in ((diameter if override is None else override, diameter_label),
                                              (length, "有效起止桩号")) if value is None]
        row = {**{k:record.get(k) for k in ("asset_id", "route_id", "source_identity", "name")},
            "construction_method":method, "station_start":start, "station_end":end,
            "pipe_diameter_m":diameter, "bore_diameter_m":bore_diameter, "bore_area_m2":area,
            "length_m":length, "length_basis":length_basis, "trenchless_excavation_volume":volume,
            "status":"calculated" if volume is not None else "pending",
            "issue":issue or ("缺少"+"、".join(missing) if missing else
                              "管径或长度超出有效计量范围" if volume is None else None)}
        if editable:
            row.update(bore_diameter_override_m=override, radial_clearance_m=clearance)
            identity = trenchless_edit_key(row)
        elif not identifier:
            identity = None
        if identity is not None and identity in positions:
            rows[positions[identity]] = row
        else:
            if identity is not None:
                positions[identity] = len(rows)
            rows.append(row)
    if not rows:
        return {}
    volumes = [r["trenchless_excavation_volume"] for r in rows if r["status"] == "calculated"]
    try:
        subtotal = math.fsum(volumes) if volumes else None
    except OverflowError:
        if not editable:
            raise
        subtotal = None
    complete = len(volumes) == len(rows) and subtotal is not None
    total = open_cut_volume + subtotal if complete else None
    if editable:
        total = _number(total)
    return {"trenchless_excavation_policy":policy,
            "trenchless_excavation_rows":rows, "trenchless_excavation_complete":complete,
            "trenchless_excavation_volume":subtotal, "total_excavation_volume":total}


def require_disjoint_trenchless_ranges(assets):
    """Reject a broad open-cut pipe that would also cover a trenchless span.

    The engine integrates each asset separately. It must never silently count
    a trenchless range through an overlapping ordinary pipe declaration.
    Different routes and endpoint-only contacts are independent.
    """
    excluded=[a for a in assets if a.get("enabled",True) and trenchless_method(a)]
    for asset in assets:
        pressure=(asset.get("kind") in {"pipe","pressure_pipe","siphon"}
                  or asset.get("source_type") in {"有压管道","倒虹吸"}
                  or asset.get("section_type")=="circular_siphon")
        if not pressure or not asset.get("enabled",True) or trenchless_method(asset):
            continue
        for other in excluded:
            if asset.get("route_id")==other.get("route_id"):
                try:
                    start=max(float(asset["station_start"]),float(other["station_start"]))
                    end=min(float(asset["station_end"]),float(other["station_end"]))
                except (KeyError,TypeError,ValueError):
                    continue
                if math.isfinite(start+end) and end>start+1e-7:
                    record=trenchless_exclusion(other)
                    message=(f"{asset.get('name',asset.get('asset_id','管道'))} 的开挖范围与{record['construction_method']}段"
                             f" K{start:.3f}～K{end:.3f} 重叠；须按非开挖起止桩拆分普通有压管道，防止重复计算挖填量")
                    error=ConstructionInputError(message)
                    error.code="trenchless_open_cut_scope_overlap"
                    error.diagnostics=[{"code":error.code,"severity":"error","message":message,
                        "asset_id":asset.get("asset_id"),"excluded_asset_id":other.get("asset_id"),
                        "station_start":start,"station_end":end}]
                    raise error
