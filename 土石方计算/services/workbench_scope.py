"""Track pending objects and station ranges for section calculation."""
from copy import deepcopy

from .contracts import ConstructionInputError, finite_number


DEFERRED_SCOPE = "partial_assets"
DEFERRED_FIELD = "calculation_deferred"
RECOVERABLE_CODES = frozenset({
    "missing_terrain", "section_terrain_unavailable",
    "missing_alignment", "missing_station_range", "missing_profile", "missing_construction",
    "missing_pipe_dimensions", "unsupported_section_geometry",
    "unsupported_coupled_pipe_curve", "unsupported_pipe_curvature_radius",
})


class AssetDataPending(ConstructionInputError):
    """A known data condition whose owning object can be deferred."""

    def __init__(self, message, *, code, diagnostics=None):
        self.code = code
        self.diagnostics = diagnostics or []
        super().__init__(message)


def supports_partial_calculation(inputs):
    """Keep schedules tied to the entire adopted scope strict."""
    return not any(inputs.get(key) for key in ("special_pipe_materials", "slope_support_rows", "slope_support_templates"))


def missing_construction_fields(asset, *, check_tunnel_section):
    from .layered_excavation import validate_layer_asset

    construction = asset.get("construction") or {}
    layer = validate_layer_asset(asset)
    tunnel = asset.get("kind") == "tunnel" or asset.get("section_type") in {
        "arch_tunnel", "circular_tunnel", "flat_bottom_tunnel", "horseshoe_tunnel"}
    required = ["excavation_clearance"] if tunnel else [
        "working_space_left", "working_space_right", "bedding_thickness", "bedding_extension", "target_mode"]
    if not tunnel and layer is None:
        required.extend("excavation_slope_" + side for side in ("left", "right")
                        if construction.get("excavation_stages_" + side) is None)
    if construction.get("target_mode") in {"union_terrain", "cover_depth", "cover_above_terrain"}:
        required.extend("bank_top_width_" + side for side in ("left", "right"))
        required.extend("bank_slope_" + side for side in ("left", "right")
                        if construction.get("bank_stages_" + side) is None)
    if construction.get("target_mode") in {"cover_depth", "cover_above_terrain"}:
        required.append("final_cover_depth")
    missing = ["construction." + field for field in required if construction.get(field) is None]
    if check_tunnel_section and tunnel:
        section = asset.get("section") or {}
        fields = ["lining_thickness", "shotcrete_thickness"]
        if asset.get("source_tunnel_parameters") and asset.get("section_type") in {"arch_tunnel", "flat_bottom_tunnel"}:
            fields.append("base_thickness")
        missing.extend("section." + field for field in fields if section.get(field) is None)
    return missing


def _assets(inputs):
    for index, network in enumerate(inputs.get("networks", []), 1):
        route = str(network.get("route_id", network.get("network_id", network.get("name", f"route-{index}"))))
        for asset in network.get("assets", []):
            yield route, asset


def clear_calculation_deferrals(inputs):
    """A new run rechecks every selected object against current source data."""
    for _, asset in _assets(inputs):
        asset.pop(DEFERRED_FIELD, None)


def recorded_calculation_deferrals(inputs):
    return ([asset[DEFERRED_FIELD] for _, asset in _assets(inputs)
             if asset.get("enabled", True) and asset.get(DEFERRED_FIELD)]
            + tunnel_deferrals(inputs.get("excluded", [])))


def tunnel_deferrals(excluded):
    return [row for row in excluded if row.get("code") == "tunnel_exposed"
            and row.get("scope_status") == "automatic_excluded_interval"]


def calculation_asset_data_issue(network, asset, *, require_profile):
    """Identify missing route and design facts for an in-scope object."""
    from .pipe_profile_partitions import awaiting_water_profile_parts
    if awaiting_water_profile_parts(asset):
        return "missing_profile", "水面线纵断面分段待确认"
    if asset.get("pipe_profile_choice") == "pending_gap":
        return "missing_profile", "设计纵断面缺口待补，补齐后可纳入本次计算"
    alignment = network.get("alignment")
    if alignment is None:
        return "missing_alignment", "缺少实际平面轴线"
    if asset.get("station_start") is None or asset.get("station_end") is None:
        return "missing_station_range", "缺少施工区段起止桩号"
    try:
        start = finite_number(asset["station_start"], "施工起桩")
        end = finite_number(asset["station_end"], "施工终桩")
    except ConstructionInputError as error:
        return "missing_station_range", str(error)
    if isinstance(asset["station_start"], str) or isinstance(asset["station_end"], str):
        return "missing_station_range", "施工区段起止桩号需要数值格式"
    if start >= end:
        return "missing_station_range", "施工终桩应大于起桩"
    if isinstance(alignment, dict):
        elements = alignment.get("elements") or []
        bounds = (alignment.get("start_station"), elements[-1].get("station_end")) if elements else ()
    else:
        bounds = (alignment.start_station, alignment.end_station)
    if bounds and all(value is not None for value in bounds):
        first, last = map(float, bounds)
        if start < first - 1e-7 or end > last + 1e-7:
            return "missing_alignment", f"施工区段超出实际平面轴线 K{first:.3f}～K{last:.3f}，待补轴线或核对桩号"
    siphon = asset.get("siphon_axis_choice") or {}
    if siphon.get("status") in {"pending", "mismatch"}:
        return "missing_profile", siphon.get("message") or "倒虹吸纵断面待补"
    if require_profile:
        design = asset.get("design_profile")
        profile = asset.get("profile_points") or (asset.get("alignment") or {}).get("profile_points")
        if not design and len(profile or []) < 2:
            return "missing_profile", "缺少完整设计纵断面"
        if isinstance(design, dict) and design.get("elements"):
            first = design["elements"][0].get("station_start")
            last = design["elements"][-1].get("station_end")
        elif not design:
            first, last = profile[0].get("station"), profile[-1].get("station")
        else:
            first = last = None
        first, last = _record_station(first), _record_station(last)
        if first is not None and last is not None and (start < first - 1e-7 or end > last + 1e-7):
            return "missing_profile", f"实际纵断面现有 K{first:.3f}～K{last:.3f}，待补施工范围内的设计高程"
    return None


def preflight_calculation_assets(inputs, *, require_profile):
    from .pipe_axis_continuity import is_in_calculation_scope

    pending = []
    for index, network in enumerate(inputs.get("networks", []), 1):
        route = str(network.get("route_id", network.get("network_id", network.get("name", f"route-{index}"))))
        for asset in network.get("assets", []):
            if not is_in_calculation_scope(asset):
                continue
            network.setdefault("alignment", None)
            issue = calculation_asset_data_issue(network, asset, require_profile=require_profile)
            if issue:
                pending.append({"route_id": route, "asset_id": asset["asset_id"],
                                "code": issue[0],"message": issue[1]})
    return defer_calculation_assets(inputs, pending)


def _record_station(value):
    try:
        return finite_number(value, "桩号")
    except ConstructionInputError:
        return None


def defer_calculation_assets(inputs, diagnostics):
    """Record a known missing input only when every supplied owner is unambiguous."""
    if not diagnostics:return []
    by_id = {}
    for route, asset in _assets(inputs):
        if asset.get("enabled", True) and not asset.get(DEFERRED_FIELD):
            by_id.setdefault(asset.get("asset_id"), []).append((route, asset))
    matches = []
    for row in diagnostics:
        if row.get("code") not in RECOVERABLE_CODES or not row.get("asset_id"):
            return []
        identities = {row.get("asset_id"), row.get("original_asset_id")}-{None}
        route = row.get("route_id")
        owners = [(key, asset) for identity in identities for key, asset in by_id.get(identity, [])
                  if route is None or key == str(route)]
        if len(owners) != 1:
            return []
        key, asset = owners[0]
        if any(previous is asset for previous, _ in matches):
            continue
        start = _record_station(asset.get("station_start"))
        end = _record_station(asset.get("station_end"))
        if start is not None and end is not None and end <= start:
            start = end = None
        record = {"asset_id": asset["asset_id"], "route_id": key,
                  "name": asset.get("name") or asset["asset_id"], "section_type": asset.get("section_type"),
                  "source_type": asset.get("source_type"), "station_start": start,
                  "station_end": end, "station": _record_station(row.get("station")),
                  "code": row["code"], "reason": row.get("message") or "施工资料待核",
                  "scope_status": "automatic_deferred"}
        matches.append((asset, record))
    for asset, record in matches:
        asset[DEFERRED_FIELD] = record
    return [deepcopy(record) for _, record in matches]


def deferred_scope_note(payload):
    rows = payload.get("calculation_deferred_assets") or []
    spans = tunnel_deferrals(rows)
    objects = len(rows)-len(spans)
    notes = [f"{objects} 个对象待补"] if objects else []
    if spans:
        notes.append(f"{len(spans)} 处隧洞待计，共 {sum(row['length_m'] for row in spans):.3f} m")
    prefix = "本次无已计断面" if (payload.get("validation") or {}).get("automatic_tunnel_exposed_only") else "部分计量"
    return "，".join([prefix, *notes]) if notes else ""


def deferred_scope_metadata(payload):
    records = payload.get("calculation_deferred_assets") or []
    if not records:
        return {}
    return {"calculation_scope": DEFERRED_SCOPE, "deferred_asset_count": len(records),
            "calculation_deferred_assets": deepcopy(records)}


def deferred_scope_matches_snapshot(payload, inputs):
    expected = recorded_calculation_deferrals(inputs)
    records = payload.get("calculation_deferred_assets") or []
    exclusions = payload.get("excluded_assets", [])
    excluded = [row for row in exclusions if row.get("scope_status") == "automatic_deferred"] + tunnel_deferrals(exclusions)
    if not expected:
        return not records and not excluded and payload.get("calculation_scope") != DEFERRED_SCOPE
    return (payload.get("calculation_scope") == DEFERRED_SCOPE
            and len(expected) == len(records) == len(excluded)
            and all(row in records and row in excluded for row in expected))
