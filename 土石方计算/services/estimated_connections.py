"""Build provisional connections from known water-profile beds and sections."""
from bisect import bisect_left
from copy import deepcopy
import hashlib
from itertools import groupby
import math

from .construction_rules import is_circular_culvert
from .design_profiles import clip_alignment, normalize_design_profile
from .network_alignment import NetworkAlignment
from .pipe_dimensions import DN_ENVELOPE_BASIS
from .transition_connections import (
    _connection_profile, _finite, _same_plan, _station, _uncovered, connection_channel_inputs,
    connection_design_flow, connection_flow_section, connection_source_inverts,
)

_TOL = 1e-7
_SURFACE = {"rectangular_channel", "rectangular_culvert"}
_PRESSURE = {"有压管道", "倒虹吸", "顶管", "定向钻"}
_TRENCHLESS = {"顶管", "定向钻"}


def _bounds(asset):
    return asset["station_start"], asset["station_end"]


def _records(asset):
    return (asset.get("original_fields") or {}).get("records") or []


def _section(asset):
    data = asset.get("section") or {}
    width, height = (_finite(data.get(key)) for key in ("inner_width", "inner_height"))
    if not width or not height or width <= 0 or height <= 0:
        return None
    kind = asset.get("section_type")
    if kind not in _SURFACE:
        if asset.get("kind") != "tunnel":
            return None
        kind = "rectangular_channel"
    return kind, {"inner_width": width, "inner_height": height}


def _bed(node):
    value = _finite(node.get("bottom_elevation"))
    source_type = node.get("structure_type") or ""
    if value == 0 and (source_type in _PRESSURE or "闸" in source_type) and not node.get("structure_height"):
        return None
    return value


def _height(station, beds, stations):
    index = bisect_left(stations, station)
    for neighbor in (index, index - 1):
        if 0 <= neighbor < len(stations) and abs(stations[neighbor] - station) <= _TOL:
            return beds[stations[neighbor]]
    if not 0 < index < len(stations):
        return None
    a, b = stations[index-1:index+1]
    return beds[a] + (beds[b] - beds[a]) * (station - a) / (b - a)


def _clip_local_alignment(alignment, a, b):
    clipped = clip_alignment(alignment, a, b)
    # The connector keeps its geometry and local IP records. The hydraulic
    # source still owns the complete route's IP records.
    ips = [point for point in clipped.ip_points
           if (station := _finite(point.get("route_station"))) is not None and a-_TOL <= station <= b+_TOL]
    return NetworkAlignment(clipped.elements, ips, start_station=a)


def _estimate_span(alignment, a, b, reference, profile, start_label, end_label):
    from .construction_defaults import apply_assumed_construction
    section_type, section = _section(reference)
    kind = "culvert" if section_type == "rectangular_culvert" else "open_channel"
    owner = reference["asset_id"]
    identifier = "estimate-" + hashlib.sha256(f"{owner}|{a:.7f}|{b:.7f}".encode()).hexdigest()[:16]
    name = f"{start_label}至{end_label}连接段（估算）"
    points = [{"station": station, "elevation": elevation} for station, elevation in profile]
    basis = "继承原表单点矩形暗涵净宽和净高" if reference.get("station_start") is None else (
        "按相邻矩形断面净宽和净高" if reference.get("section_type") in _SURFACE
        else "取相邻隧洞净宽和净高作为矩形明渠的估算尺寸")
    record = {"asset_id": identifier, "name": name, "station_start": a, "station_end": b, "length_m": b-a,
              "reference_asset_id": owner, "reference_name": reference.get("name"),
              "reference_node_ids": [r.get("profile_row_id") for r in _records(reference) if r.get("profile_row_id")],
              "section_type": section_type, **section, "basis": basis,
              "bottom_start_m": points[0]["elevation"], "bottom_end_m": points[-1]["elevation"]}
    asset = {"asset_id": identifier, "name": name, "kind": kind, "section_type": section_type,
             "source_type": "自动估算连接段", "source_identity": identifier, "section": section,
             "station_start": a, "station_end": b, "construction": {}, "enabled": True,
             "design_profile": normalize_design_profile(points, reference="inner_invert"),
             "profile_points": points, "alignment": {"profile_points": deepcopy(points),
                                                    "elevation_reference": "inner_invert"},
             "original_fields": {"estimated_connection": deepcopy(record)}, "geometry_sections": [],
             "parameter_source": "adjacent_hydraulic_section_estimate",
             "quantity_scope_notes": [basis + "，渠底按已算水面线节点。该连接工程量单列为估算。"]}
    if flow := connection_flow_section(reference, *_records(reference)):
        asset["flow_section"] = flow
    network = {"schema_version": "1.0", "network_id": identifier, "name": name,
               "source_identity": identifier, "source": {"kind": "estimated_water_profile_connection"},
               "alignment": _clip_local_alignment(alignment, a, b), "assets": [asset],
               "status": "DRAFT", "test_only": False}
    assumptions = apply_assumed_construction({"networks": [network]})["assumptions"]
    return network, record, assumptions


def _gap_context(inputs, nodes, alignment):
    existing, singletons, connections = [], [], []
    for network in inputs.get("networks", []):
        for asset in network.get("assets", []):
            if asset.get("station_start") is None:
                records = _records(asset)
                if len(records) == 1 and asset.get("section_type") == "rectangular_culvert":
                    station = _station(records[0])
                    if station is not None:
                        singletons.append((station, asset))
            elif asset.get("station_end") is not None and _same_plan(network.get("alignment"), alignment, *_bounds(asset)):
                if asset.get("transition_candidate_id") or (asset.get("original_fields") or {}).get("estimated_connection"):
                    connections.append(_bounds(asset))
                else:
                    existing.append(asset)
    real_nodes = [n for n in nodes if not n.get("is_transition") and _station(n) is not None]
    by_station = {_station(n): n for n in real_nodes}
    exclusions = [r for r in inputs.get("excluded", []) if r.get("station_start") is not None
                  and r.get("station_end") is not None and (r.get("route_id") == "water_profile"
                  or str(r.get("source_identity") or "").startswith("water_profile:"))]
    occupied = [_bounds(r) for r in (*existing, *exclusions) if r["station_end"] > r["station_start"]]
    for (source_type, _), group in groupby(real_nodes, key=lambda n: (n.get("structure_type"), n.get("name"))):
        if source_type in _TRENCHLESS:
            positions = [_station(n) for n in group]
            if positions[-1] > positions[0]:
                occupied.append((positions[0], positions[-1]))
    return existing, singletons, by_station, occupied, connections


def _gap_parts(alignment, existing, singletons, by_station, occupied, *, extra_cuts=()):
    for lo, hi in _uncovered(alignment.start_station, alignment.end_station, occupied):
        if lo <= alignment.start_station + _TOL or hi >= alignment.end_station - _TOL:
            continue
        edges = [lo, *sorted(s for s, n in by_station.items()
                            if lo+_TOL < s < hi-_TOL and "闸" in (n.get("structure_type") or "")), hi]
        for a, b in zip(edges, edges[1:]):
            local = sorted([(s, asset) for s, asset in singletons
                            if a-_TOL <= s <= b+_TOL and _section(asset)],
                           key=lambda entry: entry[0])
            neighbors = [r for r in existing if abs(r["station_end"]-a) <= _TOL
                         or abs(r["station_start"]-b) <= _TOL]
            compatible = [r for r in neighbors if _section(r)]
            if local:
                # Multiple source dimension controls divide at their midpoint.
                cuts = [a, *((left[0]+right[0])/2 for left, right in zip(local, local[1:])), b]
                choices = [(x, y, asset) for (x, y), (_, asset) in zip(zip(cuts, cuts[1:]), local)]
            elif any(is_circular_culvert(asset) for asset in neighbors):
                # A mixed or uncertain round-culvert gap belongs to the
                # round-envelope rule, never the rectangular fallback.
                choices = [(a, b, None)]
            else:
                # Prefer a local open channel or culvert before using a tunnel's net size.
                reference = min(compatible, key=lambda r: r["section_type"] not in _SURFACE, default=None)
                choices = [(a, b, reference)]
            for number, (start, end, reference) in enumerate(choices):
                cuts = [start, *[s for s in extra_cuts if start+_TOL < s < end-_TOL], end]
                for first, last in zip(cuts, cuts[1:]):
                    if last > first + _TOL:
                        yield a, b, number, first, last, reference


def _source_end(by_station, station):
    return by_station.get(station) or next((node for key, node in by_station.items()
                                           if abs(key-station) <= _TOL), {})


def _elevation_points(start, end, beds, stations):
    points = [(s, _height(s, beds, stations)) for s in
              [start, *[s for s in stations if start+_TOL < s < end-_TOL], end]]
    return points if all(z is not None and math.isfinite(z) for _, z in points) else None


def _circular_envelope(asset):
    from .section_geometry import pipe_specs

    if (not is_circular_culvert(asset) or not asset.get("enabled", True)
            or asset.get("calculation_deferred")):
        return None
    try:
        pipe, = pipe_specs(asset.get("section") or {})
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return None
    outer = pipe["outer_diameter"]
    inner = (pipe.get("reference_inner_diameter_m") if pipe.get("earthwork_envelope_only")
             else pipe["inner_diameter"])
    if inner is None or not 0 < inner <= outer:
        return None
    section = {"inner_diameter": inner, "outer_diameter": outer, "offset": pipe["offset"],
               "earthwork_envelope_only": True, "diameter_basis": "explicit_outer_construction_envelope"}
    if pipe.get("diameter_basis") == DN_ENVELOPE_BASIS:
        section.update(nominal_diameter_m=outer, dn_envelope_diameter_m=outer,
                       diameter_basis=DN_ENVELOPE_BASIS)
    return section


def _touching_sections(inputs, candidate):
    """Find directly adjoining source objects, using shared survey XY and source rows."""
    try:
        plan = NetworkAlignment.from_dict(candidate["plan_alignment"])
    except (ValueError, TypeError, KeyError, IndexError, ArithmeticError):
        return []
    source_nodes = candidate.get("source_node_ids") or (None, None)
    sides = ((candidate["station_start"], "station_end", source_nodes[0]),
             (candidate["station_end"], "station_start", source_nodes[-1]))
    touching = []
    for station, boundary, source_node in sides:
        matches = []
        for network in inputs.get("networks", ()):
            if (network.get("source") or {}).get("kind") == "estimated_water_profile_connection":
                continue
            assets = [asset for asset in network.get("assets", ())
                      if not asset.get("transition_candidate_id")
                      and (position := _finite(asset.get(boundary))) is not None
                      and abs(position-station) <= _TOL]
            if not assets or not network.get("alignment"):
                continue
            try:
                alignment = network["alignment"]
                if isinstance(alignment, dict):
                    alignment = NetworkAlignment.from_dict(alignment)
                if not alignment.start_station-_TOL <= station <= alignment.end_station+_TOL:
                    continue
                if math.dist(plan.get_xy_at_station(station), alignment.get_xy_at_station(station)) > 1e-4:
                    continue
            except (ValueError, TypeError, KeyError, IndexError, ArithmeticError):
                continue
            for asset in assets:
                node_ids = {row.get("profile_row_id") for row in _records(asset)} - {None, ""}
                if not source_node or not node_ids or source_node in node_ids:
                    matches.append(asset)
        touching.extend(matches)
    return touching


def estimate_circular_connection_gaps(inputs):
    """Fill known same-line gaps using the adjacent culvert's soil envelope."""
    from .transition_connections import adopt_edited_round_estimates, apply_transition_candidates, connection_needs_settings

    adopt_edited_round_estimates(inputs)
    candidate_ids = [row["candidate_id"] for row in inputs.get("transition_candidates", ())
                     if row.get("source_kind") == "missing_ip_gap" and row.get("extent_confirmed")
                     and connection_needs_settings(row)]
    for identifier in candidate_ids:
        candidate = next(row for row in inputs["transition_candidates"] if row["candidate_id"] == identifier)
        neighbors = _touching_sections(inputs, candidate)
        round_neighbors = [asset for asset in neighbors if is_circular_culvert(asset)]
        if not round_neighbors:
            continue
        reasons = [reason for reason in candidate.get("reasons", ())
                   if reason not in {"缺少连接段施工断面", "相邻断面不一致，需设置连接断面",
                                     "相邻圆管涵施工包络或净内底换算尺寸待补"}]
        sections = [_circular_envelope(asset) for asset in round_neighbors]
        if len(round_neighbors) != len(neighbors) or (all(sections) and any(
                any(abs(section[key]-sections[0][key]) > _TOL for key in ("outer_diameter", "inner_diameter", "offset"))
                for section in sections[1:])):
            candidate["reasons"] = [*reasons, "相邻断面不一致，需设置连接断面"]
            continue
        if not all(sections):
            candidate["reasons"] = [*reasons, "相邻圆管涵施工包络或净内底换算尺寸待补"]
            continue

        # When both ends agree geometrically, prefer a known outside envelope over a DN placeholder.
        index = next((i for i, section in enumerate(sections)
                      if section["diameter_basis"] != DN_ENVELOPE_BASIS), 0)
        reference, section = round_neighbors[index], sections[index]
        candidate["suggested_section"] = {"kind": "culvert", "section_type": "circular_culvert",
                                          "section": section, "diameter_m": section["outer_diameter"],
                                          "construction": {"target_mode": "restore_terrain"}}
        candidate["reasons"] = reasons
        profile = candidate.get("profile")
        if not profile or profile.get("reference") != "inner_invert":
            if "填写连接两端净内底高程" not in reasons:
                reasons.append("填写连接两端净内底高程")
            continue
        updated, report = apply_transition_candidates(inputs, [identifier], confirmed=True)
        if not report["valid"]:
            candidate["reasons"] = list(dict.fromkeys([*reasons, *(row["message"] for row in report["failures"])]))
            continue
        if not report["applied"]:
            continue
        inputs = updated
        candidate = next(row for row in inputs["transition_candidates"] if row["candidate_id"] == identifier)
        network = next(network for network in inputs["networks"] if network["network_id"] == identifier)
        asset, = network["assets"]
        diameter = section["outer_diameter"]
        basis = ("按相邻圆管涵公称直径 DN 施工包络" if section["diameter_basis"] == DN_ENVELOPE_BASIS
                 else "按相邻圆管涵已采用的施工外包络")
        record = {
            "asset_id": identifier, "name": asset["name"], "section_type": "circular_culvert",
            "station_start": candidate["station_start"], "station_end": candidate["station_end"],
            "length_m": candidate["station_end"]-candidate["station_start"],
            "reference_asset_id": reference["asset_id"], "reference_name": reference.get("name"),
            "reference_station_start": reference.get("station_start"), "reference_station_end": reference.get("station_end"),
            "reference_node_ids": [row["profile_row_id"] for row in _records(reference) if row.get("profile_row_id")],
            "envelope_diameter_m": diameter, "diameter_basis": section["diameter_basis"], "basis": basis,
            "profile_basis": profile.get("basis"), "bottom_start_m": asset["profile_points"][0]["elevation"],
            "bottom_end_m": asset["profile_points"][-1]["elevation"],
        }
        asset.update(source_type="自动估算连接段", parameter_source="adjacent_hydraulic_section_estimate",
                     quantity_scope_notes=[basis + "，沿用连接段净内底高程，工程量按估算列示。"])
        asset.pop("transition_candidate_id", None)
        asset["original_fields"]["estimated_connection"] = deepcopy(record)
        network["source"]["kind"] = "estimated_water_profile_connection"
        inputs.setdefault("connector_estimates", []).append(record)
        candidate.update(status="estimated", auto_applied=False, estimated_asset_ids=[identifier])
    return inputs


def collect_missing_ip_candidates(inputs, nodes, alignment, native_candidates, *, settings=None):
    """List bounded unassigned spans, including those without an explicit transition row."""
    if alignment is None:
        return []
    existing, singletons, by_station, occupied, connections = _gap_context(inputs, nodes, alignment)
    native_ranges = [_bounds(row) for row in native_candidates]
    extra_cuts = sorted({s for span in native_ranges for s in span})
    beds = {s: z for s, node in by_station.items() if (z := _bed(node)) is not None}
    stations = sorted(beds)
    candidates = []
    for lo, hi, part, start, end, reference in _gap_parts(
            alignment, existing, singletons, by_station, [*occupied, *connections], extra_cuts=extra_cuts):
        if not _uncovered(start, end, native_ranges):
            continue
        left, right = (_source_end(by_station, s) for s in (lo, hi))
        identity = [left.get("profile_row_id"), right.get("profile_row_id"), start, end]
        identifier = "gap-connection-" + hashlib.sha256(repr(identity).encode()).hexdigest()[:16]
        section_type, section = _section(reference) if reference is not None else (
            "rectangular_channel", {})
        suggestion = {"section_type": section_type, "section": section, "diameter_m": None,
                      "kind": "culvert" if section_type == "rectangular_culvert" else "open_channel",
                      "construction": {}}
        points = _elevation_points(start, end, beds, stations)
        profile = None
        if points is not None:
            profile = {"reference": "inner_invert", "basis": "按现有水面线渠底高程插值",
                       "points": [{"station": s, "elevation": z} for s, z in points]}
        elif left and right and (boundary := _connection_profile(left, right, lo, hi)):
            a, b = (row["elevation"] for row in boundary["points"])
            profile = {**boundary, "points": [{"station": s, "elevation": a+(b-a)*(s-lo)/(hi-lo)}
                                               for s in (start, end)]}
        names = [node.get("name") or node.get("structure_type") for node in (left, right)]
        left_name = names[0] if names[0] and names[0] != "-" else f"K{start:.3f}"
        right_name = names[1] if names[1] and names[1] != "-" else f"K{end:.3f}"
        reasons = ["缺少连接段施工断面"] if reference is None else []
        if profile is None:
            reasons.append("填写连接两端净内底高程")
        flow = connection_flow_section(left, right)
        design_flow = connection_design_flow(left, right)
        channel_inputs = connection_channel_inputs(flow, design_flow, (left, right), profile, settings=settings)
        source_inverts = connection_source_inverts(start, end, left, right)
        candidates.append({"candidate_id": identifier, "name": f"{left_name}至{right_name}连接段",
            "station_start": start, "station_end": end, "length_m": end-start,
            "source_node_ids": identity[:2], "source_types": [n.get("structure_type") for n in (left, right)],
            "source_kind": "missing_ip_gap", "source_partition": part,
            **({"flow_section": flow} if flow else {}),
            **({"design_flow": design_flow} if design_flow is not None else {}),
            **({"channel_inputs": channel_inputs} if channel_inputs else {}),
            **({"source_inverts": source_inverts} if source_inverts else {}),
            "plan_alignment": _clip_local_alignment(alignment, start, end).to_dict(),
            "profile": profile, "suggested_section": suggestion, "status": "needs_parameters",
            "reasons": reasons, "extent_confirmed": True, "auto_applicable": False, "auto_applied": False})
    return candidates


def add_estimated_connections(inputs, nodes, alignment):
    """Estimate bounded gaps with source grade and section controls."""
    if alignment is None:
        return inputs
    existing, singletons, by_station, occupied, connections = _gap_context(inputs, nodes, alignment)
    beds = {s: z for s, node in by_station.items() if (z := _bed(node)) is not None}
    stations = sorted(beds)
    cuts = sorted({s for candidate in inputs.get("transition_candidates", []) for s in _bounds(candidate)})
    used = set()
    additions, records, assumptions = [], [], []
    for lo, hi, _, piece_start, piece_end, reference in _gap_parts(
            alignment, existing, singletons, by_station, occupied, extra_cuts=cuts):
        if reference is None:
            continue
        remainder = _uncovered(piece_start, piece_end, connections)
        if not remainder:
            used.add(reference["asset_id"])
        for start, end in remainder:
            profile = _elevation_points(start, end, beds, stations)
            if profile is None:
                continue
            left_name = _source_end(by_station, lo).get("name")
            right_name = _source_end(by_station, hi).get("name")
            network, record, filled = _estimate_span(alignment, start, end, reference, profile,
                left_name if left_name not in ("-", None, "") else f"K{start:.3f}",
                right_name if right_name not in ("-", None, "") else f"K{end:.3f}")
            used.add(reference["asset_id"])
            additions.append(network)
            records.append(record)
            assumptions.extend(filled)
    # Single-point rows with no defensible extent remain visible in the
    # pending scope without becoming invalid, enabled calculation assets.
    singleton_ids = {asset["asset_id"] for _, asset in singletons}
    for station, asset in singletons:
        if asset["asset_id"] in used:
            continue
        inputs.setdefault("excluded", []).append({
            "code": "estimated_connection_pending", "asset_id": asset["asset_id"],
            "source_identity": asset.get("source_identity"), "name": asset.get("name"),
            "source_type": asset.get("source_type"), "station_start": station, "station_end": station,
            "reason": "单点暗涵缺少可核对的起止范围、断面尺寸或渠底高程",
            "original_asset_snapshot": asset})
    filled_ranges = [_bounds(record) for record in records]
    pending = _uncovered(alignment.start_station, alignment.end_station, [*occupied, *connections, *filled_ranges])
    for item in inputs.get("diagnostics", []):
        station = item.get("station")
        if (item.get("asset_id") in used and item.get("code") in {"missing_segment_extent", "missing_design_profile",
                "missing_construction"}) or (
                item.get("code") == "unassigned_design_range" and station is not None
                and not any(a-_TOL <= station <= b+_TOL for a, b in pending)):
            item.update(resolved=True, resolution="adjacent_hydraulic_section_estimate")
    for a, b in pending:
        if not any(item.get("code") == "unassigned_design_range" and not item.get("resolved")
                   and abs((item.get("station") if item.get("station") is not None else math.inf)-a) <= _TOL
                   for item in inputs.get("diagnostics", [])):
            inputs.setdefault("diagnostics", []).append({
                "code": "unassigned_design_range", "severity": "error", "station": a,
                "station_end": b, "message": f"桩号 {a:.3f}—{b:.3f} 缺少可沿用的施工断面或渠底高程"})
    for network in inputs["networks"]:
        network["assets"] = [a for a in network["assets"] if a["asset_id"] not in singleton_ids]
    inputs["networks"] = [n for n in inputs["networks"] if n["assets"]] + additions
    if records:
        inputs.setdefault("connector_estimates", []).extend(records)
        inputs.setdefault("construction_assumptions", []).extend(assumptions)
    for item in inputs.get("transition_candidates", []):
        if item.get("status") in {"automatic", "applied"}:
            continue
        a, b = _bounds(item)
        estimates = [r["asset_id"] for r in records if r["station_start"] < b-_TOL and r["station_end"] > a+_TOL]
        if estimates:
            item["estimated_asset_ids"] = estimates
        if estimates and not _uncovered(a, b, filled_ranges):
            item.update(status="estimated", auto_applicable=False)
            if len(estimates) == 1:
                asset = next(n["assets"][0] for n in additions if n["assets"][0]["asset_id"] == estimates[0])
                item.update(adopted_section_type=asset["section_type"], adopted_section=deepcopy(asset["section"]),
                            adopted_construction=deepcopy(asset["construction"]),
                            adopted_profile={"reference": "inner_invert", "points": deepcopy(asset["profile_points"]),
                                             "basis": "按现有水面线渠底高程插值"})
    return inputs
