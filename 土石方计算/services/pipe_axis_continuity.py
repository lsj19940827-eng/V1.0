"""Read-only guards for undefined jumps between actual one-sided pipe axes.

This module does not create transitions or alter quantity geometry. The frozen
bare quantity APIs remain unchanged; callers needing this guard use the checked
boundary below. No terrain is required, including when reopening a saved result.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math

from .contracts import ConstructionInputError
from .design_profiles import (normalize_design_profile, clip_design_profile,
                              evaluate_profile, evaluate_pipe_axis, pipe_axis_profile,
                              pipe_profile_circle)
from .finite_pipe_sections import pipe_height
from .network_alignment import NetworkAlignment
from .section_geometry import pipe_specs, section_structure
from .workbench_scope import AssetDataPending


# Section quantities use an engineering joint tolerance of one millimetre.
# Invert-to-axis conversion at a grade change can differ by micrometres;
# retain both recorded limits without inventing an extra bend or blocking use.
AXIS_ELEVATION_TOLERANCE = 1e-3
ROUND_PIPE_TYPES = {"circular_culvert", "circular_channel", "circular_siphon"}
OUTSIDE_MODES = {"exposed", "elevated", "above_ground", "open"}


class PipeAxisContinuityError(ConstructionInputError):
    def __init__(self, report):
        self.report = deepcopy(report)
        self.diagnostics = deepcopy(report["diagnostics"])
        self.code = self.diagnostics[0]["code"]
        super().__init__("；".join(d["message"] for d in self.diagnostics[:6]))


def is_in_calculation_scope(asset):
    """Match the frozen first-version preparation exclusions, without TIN."""
    from .workbench_calculator import SUPPORTED
    from .earthwork_scope import trenchless_method
    if trenchless_method(asset):
        return False
    if not asset.get("enabled", True) or asset.get("calculation_deferred") or asset.get("section_type") not in SUPPORTED:
        return False
    if asset.get("section_type") in {"box_foundation", "rectangular_pit"} or asset.get("kind") == "pit":
        return False
    pressure = asset.get("kind") in {"pipe", "pressure_pipe", "siphon"} or asset.get("section_type") == "circular_siphon"
    return not (pressure and asset.get("construction", {}).get("installation_mode") in OUTSIDE_MODES)


def _included(asset, scope):
    if (asset.get("section_type") not in ROUND_PIPE_TYPES or not asset.get("enabled", True)
            or asset.get("pipe_profile_choice") == "pending_gap"):
        return False
    return scope == "all" or is_in_calculation_scope(asset)


def _context(network, asset):
    return {"route_id": str(network.get("route_id", network.get("network_id", network.get("name", "")))),
            "route_name": network.get("name"), "asset_id": asset.get("asset_id"),
            "name": asset.get("name", asset.get("asset_id", "管道")),
            "source_identity": deepcopy(asset.get("source_identity")), "coordinate_basis": "source"}


def _issue(context, code, message, **values):
    row = {**deepcopy(context), "severity": "error", "code": code, **values}
    station = row.get("station")
    where = f" K{station:.9f}" if station is not None else ""
    pipe = f" 第{row['pipe_number']}根管" if row.get("pipe_number") else ""
    route = f"线路{row['route_id']} / " if row["route_id"] else ""
    row["message"] = f"{route}{row['name']}{where}{pipe}：{message}"
    return row


def _prepare(network, asset):
    alignment = network.get("alignment")
    if isinstance(alignment, dict):
        alignment = NetworkAlignment.from_dict(alignment)
    if not isinstance(alignment, NetworkAlignment):
        raise ConstructionInputError("缺少真实平面轴线，无法校核管轴连接")
    proxy = deepcopy(asset)
    start, end = float(asset["station_start"]), float(asset["station_end"])
    alignment.get_xy_at_station(start); alignment.get_xy_at_station(end)
    # Legacy points follow the same explicit datum used by the frozen section
    # API. Canonical profiles retain their own reference, never relabel values.
    if not proxy.get("design_profile"):
        points = proxy.get("profile_points") or proxy.get("alignment", {}).get("profile_points") or network.get("profile_points")
        if not points:
            from .design_profiles import DesignProfileError
            raise DesignProfileError("缺少完整设计纵断面", code="missing_profile")
        proxy["design_profile"] = normalize_design_profile(points, reference=proxy.get("alignment", {}).get("elevation_reference", "pipe_axis"))
    profile = clip_design_profile(proxy, start, end)
    if profile["reference"] not in {"pipe_axis", "common_outer_bottom", "inner_invert"}:
        raise ConstructionInputError("管道高程基准未识别，须明确首管管轴、共同外底或净内底")
    proxy["design_profile"] = profile
    section = deepcopy(proxy.get("section", {}))
    count = len(section["pipes"]) if section.get("pipes") else float(section.get("pipe_count", 1))
    if count > 1 and section.get("pipe_spacing") is None:
        raw = section.get("pipes") or []
        if len(raw) != count or not all(p.get("offset") is not None for p in raw):
            raise AssetDataPending("多管缺少管间净距或逐管真实偏距，无法校核派生轴线", code="missing_pipe_dimensions")
    try:
        pipes = pipe_specs(section, recommended_material=None, require_lining_material=False)
    except ConstructionInputError as error:
        raise AssetDataPending(str(error), code="missing_pipe_dimensions") from error
    for p in pipes:
        if p["material_category"] == "unknown": p["material"] = "continuity_unknown_material"
        if p["lining_thickness"] and p["lining_material_category"] == "unknown": p["lining_material"] = "continuity_unknown_material"
    proxy["section"] = {**section, "pipes": pipes}
    proxy["workbench_geometry"] = False
    return proxy, alignment, pipes


def _plan_endpoint_station(alignment, station):
    # Match NetworkAlignment._element's existing endpoint tolerance without
    # changing side selection at any interior line/arc interface.
    if alignment.start_station - 1e-7 <= station < alignment.start_station:
        return alignment.start_station
    if alignment.end_station < station <= alignment.end_station + 1e-7:
        return alignment.end_station
    return station


def _plan_element(alignment, station, side):
    station = _plan_endpoint_station(alignment, station)
    matches = [e for e in alignment.elements if (e["station_start"] <= station < e["station_end"] if side == "right"
                                               else e["station_start"] < station <= e["station_end"])]
    if not matches:
        matches = [e for e in alignment.elements if e["station_start"] <= station <= e["station_end"]]
    if not matches: raise ValueError("管轴连接桩号未被真实平面轴线覆盖")
    return matches[0] if side == "right" else matches[-1]


def _limit(prepared, station, side):
    proxy, alignment, pipes = prepared
    station = _plan_endpoint_station(alignment, station)
    z, slope = evaluate_profile(proxy, station, side)
    element = _plan_element(alignment, station, side)
    fraction = (station - element["station_start"]) / element["length"]
    if element["kind"] == "line":
        plan_center = [a + (b - a) * fraction for a, b in zip(element["start_xy"], element["end_xy"])]
        tangent, curvature = element["tangent_angle"], 0.
    else:
        angle = element["start_angle"] + element["sweep_angle"] * fraction
        plan_center = [element["center_xy"][0] + element["radius"] * math.cos(angle),
                  element["center_xy"][1] + element["radius"] * math.sin(angle)]
        tangent = angle + math.copysign(math.pi / 2, element["sweep_angle"])
        curvature = math.copysign(1 / element["radius"], element["sweep_angle"])
    first_radius = pipes[0]["outer_diameter"] / 2
    first_inner = pipes[0]["inner_diameter"] / 2
    # Genuine vertical arcs keep the existing full geometric validation. Line
    # cells need only the frozen exact axis/height helpers, not hundreds of
    # polygon vertices on every generated TIN-control knot in a UI callback.
    circle = pipe_profile_circle(proxy, first_radius, first_radius, station, side,
                                 first_inner_radius=first_inner)
    if circle:
        actual_pipes = section_structure(proxy, elevation=z, slope=slope, station=station,
            side=side, plan_curvature=curvature, arc_segments=256)["pipes"]
    else:
        actual_pipes = []
        reference = proxy["design_profile"]["reference"]
        first_height = pipe_height(first_radius, pipes[0]["offset"], curvature, slope)
        if reference == "common_outer_bottom": bottom = z
        elif reference == "inner_invert":
            bottom = z + pipe_height(first_inner, pipes[0]["offset"], curvature, slope) - first_height
        else: bottom = z - first_height
        for p in pipes:
            radius = p["outer_diameter"] / 2
            if curvature and slope:
                height = pipe_height(radius, p["offset"], curvature, slope)
                axis_elevation = bottom + height
            else:
                axis_elevation, pipe_slope = evaluate_pipe_axis(proxy, radius, first_radius, station, side,
                                                        first_inner_radius=first_inner)
                height = pipe_height(radius, p["offset"], curvature, pipe_slope)
            actual_pipes.append({**p, "axis_elevation": axis_elevation, "outer_bottom": axis_elevation - height, "outer_top": axis_elevation + height})
    return {"station": station, "side": side, "design_elevation": z, "vertical_slope": slope,
            "plan_curvature": curvature, "center_xy": plan_center, "tangent_angle": tangent,
            "pipes": [{"pipe_number": i + 1,
                "axis_xy": [plan_center[0] + p["offset"] * math.sin(tangent), plan_center[1] - p["offset"] * math.cos(tangent)],
                **{k: p[k] for k in ("axis_elevation", "offset", "outer_diameter", "outer_top", "outer_bottom")}}
                for i, p in enumerate(actual_pipes)]}


def _compare(context, left, right, *, other_asset_id=None):
    diagnostics = []
    if len(left["pipes"]) != len(right["pipes"]):
        return [_issue(context, "pipe_axis_transition_undefined", "相邻同源区段管数不同，未定义连接段；请补充真实轴线", station=left["station"],
                       left=deepcopy(left), right=deepcopy(right), other_asset_id=other_asset_id)]
    for l, r in zip(left["pipes"], right["pipes"]):
        jump = r["axis_elevation"] - l["axis_elevation"]
        offset_jump = r["offset"] - l["offset"]
        plan_jump = math.dist(l["axis_xy"], r["axis_xy"])
        if abs(jump) > AXIS_ELEVATION_TOLERANCE or plan_jump > AXIS_ELEVATION_TOLERANCE:
            diagnostics.append(_issue(context, "pipe_axis_transition_undefined",
                f"左右实际管轴高程 {l['axis_elevation']:.9f} / {r['axis_elevation']:.9f}m，跳变 {jump:+.9f}m"
                + (f"，横向偏距跳变 {offset_jump:+.9f}m" if abs(offset_jump) > AXIS_ELEVATION_TOLERANCE else "")
                + (f"，平面实际管轴位置跳变 {plan_jump:.9f}m" if plan_jump > AXIS_ELEVATION_TOLERANCE else "")
                + "；当前只定义两侧局部断面，未定义连续连接段。请调整控制高程或导入真实轴线",
                station=left["station"], side="left/right", pipe_number=l["pipe_number"],
                left_axis_elevation=l["axis_elevation"], right_axis_elevation=r["axis_elevation"], axis_jump=jump,
                left_offset=l["offset"], right_offset=r["offset"], offset_jump=offset_jump,
                left_axis_xy=deepcopy(l["axis_xy"]), right_axis_xy=deepcopy(r["axis_xy"]), plan_axis_jump=plan_jump,
                left=deepcopy(left), right=deepcopy(right), other_asset_id=other_asset_id))
    return diagnostics


def _family(asset, assets):
    if asset.get("source_identity") is not None:
        return "source:" + json.dumps(asset["source_identity"], sort_keys=True, ensure_ascii=False)
    # Only explicit edit ancestry establishes continuity between assets. A
    # shared route/name or merely touching stations never invents a pipe joint.
    parent = asset.get("parent_asset_id")
    if not parent and not any(a.get("parent_asset_id") == asset.get("asset_id") for a in assets): return None
    indexed = {a.get("asset_id"): a for a in assets}
    root = parent or asset.get("asset_id"); seen = set()
    while root in indexed and indexed[root].get("parent_asset_id") and root not in seen:
        seen.add(root); root = indexed[root]["parent_asset_id"]
    # Repeated UI splits preserve their ancestor in the ID even after the
    # intermediate asset was replaced. Exact ID-prefix ancestry is explicit.
    ancestors = [a.get("parent_asset_id") for a in assets if a.get("parent_asset_id") and
                 (root == a["parent_asset_id"] or str(root).startswith(str(a["parent_asset_id"]) + "-"))]
    return "parent:" + str(min(ancestors, key=len) if ancestors else root)


def inspect_pipe_axis_continuity(inputs, *, scope="calculation", cancelled=None):
    """Return source-station limits/errors without TIN, mutation, or quantities.

    ``calculation`` matches first-version enabled buried-pipe scope. ``all``
    also checks exposed pipes for truthful read-only/cover-preview display.
    This verifies C0 axis elevation/placement only, not global pipe-joint solids.
    """
    if scope not in {"calculation", "all"}: raise ValueError("invalid continuity scope")
    networks = inputs.get("networks", [inputs] if "assets" in inputs else [])
    report = {"schema_version": "1.0", "valid": True, "scope": scope, "diagnostics": [], "limits": [],
              "elevation_identity_tolerance": AXIS_ELEVATION_TOLERANCE,
              "validation_scope": "existing_actual_one_sided_axis_C0; no inferred transition or global solid-joint test"}
    for network in networks:
        prepared_assets = []
        assets = network.get("assets", [])
        for asset in assets:
            if not _included(asset, scope): continue
            if cancelled and cancelled(): raise InterruptedError("管轴连接校核已取消")
            context = _context(network, asset)
            try:
                prepared = _prepare(network, asset)
                proxy, alignment, pipes = prepared
                start, end = float(asset["station_start"]), float(asset["station_end"])
                positions = sorted({start, end, *[e[k] for e in proxy["design_profile"]["elements"] for k in ("station_start", "station_end")],
                                    *[s for s in alignment.primitive_break_stations if start < s < end]})
                limits = {}
                for s in positions:
                    if cancelled and cancelled(): raise InterruptedError("管轴连接校核已取消")
                    sides = ["right"] if s == start else ["left"] if s == end else ["left", "right"]
                    for side in sides:
                        limits[(s, side)] = _limit(prepared, s, side)
                        report["limits"].append({**deepcopy(context), **deepcopy(limits[(s, side)])})
                    if len(sides) == 2:
                        report["diagnostics"].extend(_compare(context, limits[(s, "left")], limits[(s, "right")]))
                # Reuse the existing true vertical-offset profile validation
                # on each actual cell; never force a jumped derived profile to
                # normalize into one falsely continuous line.
                for element in proxy["design_profile"]["elements"]:
                    if element["kind"] == "arc":
                        one = {**proxy, "design_profile": {"reference": proxy["design_profile"]["reference"], "elements": [element]}}
                        for p in pipes:
                            pipe_axis_profile(one, p["outer_diameter"] / 2, pipes[0]["outer_diameter"] / 2,
                                              first_inner_radius=pipes[0]["inner_diameter"] / 2)
                prepared_assets.append((asset, context, limits[(start, "right")], limits[(end, "left")]))
            except (ValueError, TypeError, KeyError) as exc:
                pending = getattr(exc, "code", None) if isinstance(exc, AssetDataPending) else None
                code = "pipe_axis_validation_input" if pending else getattr(exc, "code", "pipe_axis_validation_input")
                diagnostic = _issue(context, code, str(exc), station=getattr(exc, "station", None),
                    original_error_type=type(exc).__name__, original_error_message=str(exc),
                    original_diagnostics=deepcopy(getattr(exc, "diagnostics", [])))
                if pending:
                    diagnostic["calculation_pending_code"] = pending
                report["diagnostics"].append(diagnostic)
        families = {}
        for item in prepared_assets:
            family = _family(item[0], assets)
            if family: families.setdefault(family, []).append(item)
        for members in families.values():
            members.sort(key=lambda item: float(item[0]["station_start"]))
            for a, b in zip(members, members[1:]):
                if abs(a[3]["station"] - b[2]["station"]) <= 1e-7:
                    report["diagnostics"].extend(_compare(a[1], a[3], b[2], other_asset_id=b[0].get("asset_id")))
    report["valid"] = not report["diagnostics"]
    return report


def require_pipe_axis_continuity(inputs, **kwargs):
    report = inspect_pipe_axis_continuity(inputs, **kwargs)
    if not report["valid"]: raise PipeAxisContinuityError(report)
    return report


def siphon_axis_deferral_diagnostics(inputs, report):
    """Identify continuity issues the partial-scope calculation may defer."""
    configured = {
        asset["asset_id"]
        for network in inputs.get("networks", []) for asset in network.get("assets", [])
        if asset.get("siphon_axis_choice") and asset.get("asset_id")
    }
    pending = []
    for issue in report["diagnostics"]:
        identities = [issue["asset_id"]]
        if issue.get("other_asset_id"):
            identities.append(issue["other_asset_id"])
        if any(identity not in configured for identity in identities):
            return []
        pending.extend({**issue, "asset_id": identity, "code": "missing_profile"} for identity in identities)
    return pending


def partial_axis_deferral_diagnostics(inputs, report):
    """Recognize scope-safe local axis issues and retain the existing siphon rule."""
    lookup = {
        "missing_profile": "missing_profile",
        "missing_design_profile": "missing_profile",
        "invalid_design_profile": "missing_profile",
        "profile_jump": "missing_profile",
        "missing_pipe_dimensions": "missing_pipe_dimensions",
        "near_vertical_profile": "unsupported_section_geometry",
        "unsupported_coupled_pipe_curve": "unsupported_section_geometry",
        "unsupported_pipe_curvature_radius": "unsupported_section_geometry",
    }
    pending, remaining = [], []
    for issue in report["diagnostics"]:
        code = lookup.get(issue.get("calculation_pending_code", issue["code"]))
        if code and not issue.get("other_asset_id"):
            pending.append({**issue, "code": code})
        else:
            remaining.append(issue)
    if remaining:
        siphons = siphon_axis_deferral_diagnostics(inputs, {"diagnostics": remaining})
        if not siphons:
            return []
        pending.extend(siphons)
    return pending


def assess_cover_preview(network, asset, preview):
    """Keep all original preview samples; add real limits and block undefined joins."""
    result = deepcopy(preview)
    if not preview.get("design_profile"): return result
    candidate = deepcopy(asset)
    candidate["design_profile"] = deepcopy(preview["design_profile"])
    candidate.setdefault("section", {})["pipes"] = deepcopy(preview["pipes"])
    candidate["section"]["pipe_count"] = len(preview["pipes"])
    candidate["enabled"] = True
    report = inspect_pipe_axis_continuity({"networks": [{**network, "assets": [candidate]}]}, scope="all")
    result["axis_continuity"] = report
    result["diagnostics"] = deepcopy(preview.get("diagnostics", [])) + deepcopy(report["diagnostics"])
    result["valid"] = bool(preview.get("valid")) and report["valid"]
    return result


def apply_checked_cover_preview(network, asset, preview, *, confirmed=False):
    from .design_profiles import apply_cover_preview
    checked = assess_cover_preview(network, asset, preview)
    if checked.get("axis_continuity", {}).get("valid") is False:
        raise PipeAxisContinuityError(checked["axis_continuity"])
    return apply_cover_preview(asset, checked, confirmed=confirmed)


def _assumed_trench_range(inputs,error):
    """Only the program's unedited draft pipe slopes may change automatically."""
    if (inputs.get("quantity_basis") or {}).get("construction_parameters")!="assumed":return None
    search=getattr(error,"terrain_search",None)
    if not search or search.get("terrain_scope")=="source_corridor":return None
    text=str(error)
    if not any(term in text for term in ("未接地","未与地面相交")):return None
    if any(term in text for term in ("工作面跨越","结构/工作面跨越")):return None
    from .batch_cover_profiles import is_pressure_cover_asset
    for row in getattr(error,"diagnostics",[]) or []:
        if row.get("station") is None:continue
        ids={row.get("asset_id"),row.get("original_asset_id")}
        for network in inputs.get("networks",[]):
            for asset in network.get("assets",[]):
                if asset.get("asset_id") not in ids or not is_pressure_cover_asset(asset):continue
                c=asset.get("construction",{});sources=asset.get("parameter_sources",{})
                if (asset.get("parameter_source")=="user_confirmed" or c.get("burial_mode")!="cover_depth"
                        or float(c.get("cover_depth",99))>3.):continue
                if not all(float(c.get("excavation_slope_"+side,-1))==1.
                           and str(sources.get("construction.excavation_slope_"+side,"")).startswith("施工参数假定")
                           and not c.get("excavation_stages_"+side) for side in ("left","right")):continue
                alignment=network.get("alignment")
                if isinstance(alignment,dict):alignment=NetworkAlignment.from_dict(alignment)
                station=float(row["station"])
                elements=alignment.elements
                candidates=[e for e in elements if e["station_start"]-1e-7<=station<=e["station_end"]+1e-7]
                if not candidates:continue
                element=candidates[0] if row.get("side")=="left" else candidates[-1]
                start=max(float(asset["station_start"]),element["station_start"])
                end=min(float(asset["station_end"]),element["station_end"])
                if end>start+1e-7:return network,asset,start,end
    return None


def calculate_checked_workbench(tin, inputs, *, terrain_request=None, allow_partial_scope=False,
                                cover_failures=(), terrain_unavailable_reason=None, **kwargs):
    """Calculate draft construction continuously, recording any local support assumption."""
    from .workbench_calculator import calculate_workbench
    from .workbench_scope import (RECOVERABLE_CODES, clear_calculation_deferrals, defer_calculation_assets,
                                  preflight_calculation_assets, recorded_calculation_deferrals,
                                  supports_partial_calculation)
    allow_partial_scope = (allow_partial_scope and supports_partial_calculation(inputs)
                           and not kwargs.get("include_independent_pits"))
    prepared=inputs;resolutions=[]
    if allow_partial_scope or recorded_calculation_deferrals(inputs):
        prepared=deepcopy(inputs)
        clear_calculation_deferrals(prepared)
    if cover_failures and (not allow_partial_scope or not defer_calculation_assets(prepared,cover_failures)):
        raise ConstructionInputError("覆土纵断面未完成，须核对各对象的生成条件")
    if allow_partial_scope:
        preflight_calculation_assets(prepared,require_profile=True)
    if terrain_unavailable_reason:
        from .workbench_calculator import asset_requires_section_terrain
        from .earthwork_scope import trenchless_exclusions, trenchless_excavation_quantities
        from .sluice_gate import workbench_has_ready_gates
        from .workbench_scope import AssetDataPending

        if tin is not None or not allow_partial_scope:
            raise ConstructionInputError(terrain_unavailable_reason)
        bores = trenchless_excavation_quantities(trenchless_exclusions(prepared))
        if bores.get("trenchless_excavation_volume") is None and not workbench_has_ready_gates(prepared):
            diagnostics = [{**row, "message": f"{row.get('name') or row.get('asset_id')}：{row['issue']}"}
                           for row in bores.get("trenchless_excavation_rows", []) if row.get("issue")]
            raise AssetDataPending(terrain_unavailable_reason + "非开挖洞段资料待补。",
                                   code="no_ready_assets", diagnostics=diagnostics)
        deferred = []
        for index, network in enumerate(prepared.get("networks", []), 1):
            route = network.get("route_id", network.get("network_id", network.get("name", f"route-{index}")))
            for asset in network.get("assets", []):
                if asset_requires_section_terrain(asset):
                    deferred.append({"route_id": str(route), "asset_id": asset["asset_id"], "code": "missing_terrain",
                                     "message": terrain_unavailable_reason})
        if deferred and not defer_calculation_assets(prepared, deferred):
            raise ConstructionInputError(terrain_unavailable_reason)
    while True:
        try:
            require_pipe_axis_continuity(prepared, cancelled=kwargs.get("cancelled"))
        except PipeAxisContinuityError as error:
            if not allow_partial_scope or not defer_calculation_assets(
                    prepared, partial_axis_deferral_diagnostics(prepared, error.report)):
                raise
            continue
        try:
            result,payload=calculate_workbench(tin,prepared,collect_deferrals=allow_partial_scope,**kwargs)
            if resolutions:
                payload["automatic_construction_resolutions"]=resolutions
            if terrain_unavailable_reason:
                payload["terrain_deferred_reason"] = terrain_unavailable_reason
            return result,payload
        except ValueError as error:
            candidate=_assumed_trench_range(prepared,error)
            if candidate is None or len(resolutions)>=8:
                code=getattr(error,"code",None)
                if not allow_partial_scope or code not in RECOVERABLE_CODES|{"recoverable_asset_inputs"}:
                    raise
                diagnostics=[{**row,"code":row.get("code",code)} for row in getattr(error,"diagnostics",[])
                             if isinstance(row,dict)]
                deferred=defer_calculation_assets(prepared,diagnostics)
                if not deferred:raise
                progress=kwargs.get("progress")
                if progress:
                    progress("construction",0.,f"{len(deferred)} 个对象待核，已保留原设置并继续计算其余对象。")
                continue
            network,asset,start,end=candidate
            from .assumed_pipe_trench import apply_assumed_supported_trench
            prepared,report=apply_assumed_supported_trench(prepared,asset["asset_id"],start,end,
                network_id=network.get("route_id",network.get("network_id")),reason=str(error),
                terrain_request=terrain_request,tin=tin)
            resolutions.append(report)
            progress=kwargs.get("progress")
            if progress:progress("construction",0.,f"{asset.get('name','管道')} K{start:.3f}～{end:.3f}：默认放坡未能在原测区接地，该局部暂按支护直槽计算；支护结构量另计。")


def require_result_pipe_axis_continuity(payload, *, current_inputs=None):
    """Validate saved source inputs again; never trust READY/valid cache flags."""
    source = payload.get("inputs", {}).get("workbench")
    if source is None:
        # Historical single-network quantity payloads retain this older key.
        source = payload.get("inputs", {}).get("network")
    if source is not None: require_pipe_axis_continuity(source)
    if current_inputs is not None: require_pipe_axis_continuity(current_inputs)


def disconnected_series(rows, key, *, station_key="station"):
    """Retain same-K left/right values but never draw a vertical fake connection."""
    xs, ys = [], []
    previous = None
    for row in rows:
        station, height = float(row[station_key]), row.get(key)
        if previous is not None and abs(station - previous[0]) <= 1e-7:
            xs.append(math.nan); ys.append(math.nan)
        xs.append(station); ys.append(math.nan if height is None else float(height))
        previous = (station, height)
    return xs, ys


def cover_preview_series(preview, pipe_index, key):
    """Use actual two-sided displayed heights, retaining original cover samples."""
    samples = {float(r["station"]): r for r in preview.get("samples", [])}
    rows = []
    continuity = preview.get("axis_continuity", {})
    limits = continuity.get("limits", [])
    jumps = {issue.get("station") for issue in continuity.get("diagnostics", [])
             if issue.get("code") == "pipe_axis_transition_undefined"
             and issue.get("pipe_number") in (None, pipe_index + 1)}
    for limit in sorted(limits, key=lambda r: (r["station"], 0 if r["side"] == "left" else 1)):
        pipe = limit["pipes"][pipe_index]
        value = pipe.get(key)
        if key == "ground_elevation":
            original = samples.get(float(limit["station"]), {}).get("pipes", [])
            original = original[pipe_index] if len(original) > pipe_index else {}
            side = next((p for p in original.get("side_limits", []) if p["side"] == limit["side"]), original)
            value = side.get(key)
        station = limit["station"]
        if key == "axis_elevation" and rows and station == rows[-1]["station"] and station not in jumps:
            previous = rows[-1][key]
            if value is not None and previous is not None and math.isclose(value, previous, rel_tol=0., abs_tol=1e-8):
                continue
        rows.append({"station": station, key: value})
    if not rows:
        rows = [{"station": s["station"], key: s["pipes"][pipe_index].get(key)} for s in preview.get("samples", [])]
    return disconnected_series(rows, key)
