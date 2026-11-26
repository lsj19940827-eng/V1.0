# CAD station/elevation axes and route stationing.
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os


def _alignment_points(network):
    alignment = network.get("alignment")
    return (alignment.get("ip_points", []) if isinstance(alignment, dict)
            else getattr(alignment, "ip_points", []))


def _route_fingerprint(network):
    """Identify the original route, including its uncut source IP coordinates."""
    points = _alignment_points(network)
    facts = []
    for point in points:
        if point.get("x") is None or point.get("y") is None:
            return None
        facts.append([str(point.get("profile_row_id") or ""), float(point["x"]), float(point["y"]),
            point.get("route_station", point.get("station_MC")), point.get("turn_radius", 0.)])
    if len(facts) < 2:
        return None
    return hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _route_namespace(network):
    source = network.get("source") or {}
    return (network.get("source_route_id") or network.get("source_identity") or network.get("route_id"),
            source.get("kind"), source.get("source_sha256"), source.get("source_path"))


def _same_source_route(network, selected):
    if network is selected:
        return True
    fingerprint = _route_fingerprint(selected)
    return (fingerprint is not None and _route_fingerprint(network) == fingerprint
            and _route_namespace(network) == _route_namespace(selected))


def _find_selected_network(inputs, asset, selected_network=None):
    networks = inputs.get("networks", [])
    if selected_network is not None:
        for network in networks:
            if network is selected_network:
                return network
        matches = [n for n in networks if n.get("network_id") == selected_network.get("network_id")
                   and _same_source_route(n, selected_network)]
    else:
        matches = [n for n in networks if any(a is asset for a in n.get("assets", []))]
        if not matches:
            matches = [n for n in networks if any(a.get("asset_id") == asset.get("asset_id")
                                                  for a in n.get("assets", []))]
    if len(matches) != 1:
        return None
    return matches[0]

def read_quantity_profile(path, *, coordinate_units="m", reference="pipe_axis"):
    """Read an explicitly declared station/elevation polyline, retaining arcs."""
    import ezdxf
    from .design_profiles import normalize_design_profile
    from ..io.independent_terrain import file_sha256
    if coordinate_units != "m":
        raise ValueError("纵断面坐标单位请选择米")
    path = Path(path).resolve()
    source_hash = file_sha256(path)
    doc = ezdxf.readfile(path)
    curves = [e for e in doc.modelspace() if e.dxftype() in {"LWPOLYLINE", "POLYLINE"}]
    if len(curves) != 1:
        raise ValueError("纵断面DXF应保留一条桩号—高程轴线")
    curve = curves[0]
    if bool(getattr(curve, "closed", False)) or bool(getattr(curve, "is_closed", False)):
        raise ValueError("纵断面轴线应为有起止点的开口线")
    if tuple(curve.dxf.get("extrusion", (0, 0, 1))) != (0, 0, 1):
        raise ValueError("纵断面轴线须位于桩号—高程坐标平面")
    if curve.dxftype() == "POLYLINE":
        if not curve.is_2d_polyline:
            raise ValueError("纵断面轴线须为二维桩号—高程线")
        points = [(v.dxf.location.x, v.dxf.location.y, v.dxf.get("bulge", 0)) for v in curve.vertices]
    else:
        points = list(curve.get_points("xyb"))
    profile = normalize_design_profile({"vertices": [p[:2] for p in points],
        "bulges": [p[2] for p in points]}, reference=reference)
    if file_sha256(path) != source_hash:
        raise ValueError("纵断面文件读取期间发生变化，请重新计算")
    return profile, {"path": str(path), "sha256": source_hash,
        "source_insunits": doc.header.get("$INSUNITS", 0), "coordinate_units": "m",
        "coordinate_unit_basis": "工作流明确声明桩号及高程坐标为米", "reference": reference,
        "vertex_count": len(points)}


def prepare_imported_profile(profile, asset, *, inputs=None, station_offset=None, source_units="m", selected_network=None):
    """Map a local CAD profile to its uniquely matching route and clip a selection.

    Matching tolerates 1 mm of terminal decimal rounding. Lines keep their
    gradient; circular arcs keep their centre and radius.
    """
    from .batch_cover_profiles import is_pressure_cover_asset
    from .design_profiles import clip_design_profile, normalize_design_profile
    from .workbench_calculator import _shift_profile
    profile = normalize_design_profile(profile)
    factors = {"m": 1., "mm": .001, "cm": .01, "in": .0254, "ft": .3048}
    if source_units not in factors:
        raise ValueError("纵断面坐标单位无效")
    factor = factors[source_units]
    if factor != 1.:
        for element in profile["elements"]:
            for key in ("station_start", "station_end", "z_start", "center_station", "center_elevation", "radius"):
                if key in element:
                    element[key] *= factor
        profile = normalize_design_profile(profile)
    start, end = float(asset["station_start"]), float(asset["station_end"])
    a, b = profile["station_start"], profile["station_end"]
    ranges = [(start, end)]
    if inputs:
        selected = _find_selected_network(inputs, asset, selected_network)
        networks = [n for n in inputs.get("networks", []) if selected is not None and _same_source_route(n, selected)]
        all_assets = [x for n in networks for x in n.get("assets", [])
                      if is_pressure_cover_asset(x)]
        for members in ([x for x in all_assets if x.get("kind") != "siphon"], all_assets):
            if members:
                ranges.append((min(x["station_start"] for x in members),
                               max(x["station_end"] for x in members)))
    mapping_basis = "来源全局桩号"
    if station_offset is None:
        matches = {(left-a, left, right) for left, right in ranges
                   if abs((b-a)-(right-left)) <= .001
                   and left <= start+.001 and right >= end-.001}
        offsets = {round(row[0], 6) for row in matches}
        if len(offsets) == 1:
            station_offset, _, _ = next(iter(matches))
            mapping_basis = "纵线长度与所选管道路线范围相符"
        elif a <= start+.001 and b >= end-.001:
            station_offset = 0.
        else:
            raise ValueError("纵断面范围与所选管段不符，请填写真实起始桩号")
    shifted = {"design_profile": deepcopy(profile)}
    _shift_profile(shifted, float(station_offset))
    mapped = shifted["design_profile"]
    adjustments = []
    first, last = mapped["elements"][0], mapped["elements"][-1]
    if 0 < first["station_start"]-start <= .001:
        delta = start-first["station_start"]
        if first["kind"] == "line":
            first["z_start"] += first["slope"]*delta
        first["station_start"] = start
        mapped["station_start"] = start
        adjustments.append(delta)
    if 0 < end-last["station_end"] <= .001:
        adjustments.append(end-last["station_end"])
        last["station_end"] = end
        mapped["station_end"] = end
    clipped = clip_design_profile(mapped, start, end)
    return clipped, {"station_offset_m": float(station_offset), "mapping_basis": mapping_basis,
        "source_units": source_units, "coordinate_scale_to_m": factor,
        "source_station_range_m": [a, b], "selected_station_range_m": [start, end],
        "terminal_rounding_m": adjustments}


def _exclusion_on_route(record, selected):
    """A generic route label alone cannot identify a non-open-cut interval."""
    namespace = _route_namespace(selected)[0]
    if record.get("route_id") not in {None, namespace, selected.get("route_id"), selected.get("network_id")}:
        return False
    points = {str(p.get("profile_row_id")): p for p in _alignment_points(selected) if p.get("profile_row_id")}
    original = record.get("original_asset_snapshot") or {}
    records = (original.get("original_fields") or {}).get("records") or original.get("records") or []
    if len(records) < 2 or not points:
        return False
    for row in records:
        point = points.get(str(row.get("profile_row_id")))
        if point is None or any(row.get(key) is None or abs(float(row[key])-float(point[key])) > 1e-6 for key in ("x", "y")):
            return False
    return True


def apply_asset_profile(target, clipped, provenance, *, axis_source="user_input_real_elevation",
                       terminal_rounding=()):
    """Apply a reviewed, mapped profile to one asset and its section inputs."""
    from .design_profiles import evaluate_profile, profile_break_stations, sync_bound_axis_controls

    if target.get("axis_source") == "water_profile_real_elevation" and target.get("design_profile"):
        target.setdefault("water_profile_design_profile", deepcopy(target["design_profile"]))
    if target.get("design_profile") and not target.get("original_design_profile"):
        target["original_design_profile"] = deepcopy(target["design_profile"])
    target.pop("siphon_axis_choice", None)
    target.pop("siphon_axis_input", None)
    target["design_profile"] = clipped
    points = [{"station": s, "elevation": evaluate_profile(clipped, s)[0]} for s in profile_break_stations(clipped)]
    target["profile_points"] = points
    target.setdefault("alignment", {}).update(profile_points=deepcopy(points), elevation_reference=clipped["reference"])
    target.setdefault("construction", {}).update(burial_mode="actual_axis", axis_confirmed=True)
    sync_bound_axis_controls(target)
    target["pipe_profile_choice"] = "water_profile" if axis_source == "water_profile_real_elevation" else "quantity_dxf"
    target.update(axis_source=axis_source, profile_source=axis_source, cover_preview_confirmed=True,
                  profile_import_mapping=deepcopy(provenance))
    target.pop("profile_source_file", None)
    if provenance.get("path"):
        target["profile_source_file"] = {**deepcopy(provenance), "terminal_rounding_m": list(terminal_rounding)}
    for key in ("axis_cover_samples", "axis_preview_sha256", "cover_confirmation", "cover_generation_options",
                "cover_actual_cover_summary"):
        target.pop(key, None)
    target["missing_fields"] = [f for f in target.get("missing_fields", []) if f != "design_profile"]


def apply_trenchless_route_profile(target, profile, provenance):
    target["trenchless_route_profile"] = profile
    original = target.setdefault("original_asset_snapshot", {})
    original.update(design_profile=profile, axis_source="user_input_real_elevation",
                    profile_import_mapping=deepcopy(provenance))
    original.setdefault("construction", {}).update(burial_mode="actual_axis", axis_confirmed=True)
    if provenance.get("path"):
        target["profile_source_file"] = deepcopy(provenance)
        original["profile_source_file"] = deepcopy(provenance)


def bind_imported_route_profile(inputs, selected_network, selected_asset, profile, *,
        source=None, mapping=None, source_units="m", scope="covered_route"):
    """Return a draft applying one real axis to covered parts of its source route.

    Networks split by excluded construction spans retain a common original-IP
    fingerprint. Other routes, even with identical station ranges and labels,
    receive no updates. Source parameters and the caller's input are preserved.
    """
    from .batch_cover_profiles import is_pressure_cover_asset
    from .design_profiles import normalize_design_profile
    from ..io.independent_terrain import file_sha256
    if scope not in {"current", "covered_route"}:
        raise ValueError("请选择当前对象或纵线覆盖的同线管段")
    selected = _find_selected_network(inputs, selected_asset, selected_network)
    if selected is None:
        raise ValueError("所选路线已变化，请重新选择管段")
    selected_matches = [a for a in selected.get("assets", []) if a is selected_asset]
    if not selected_matches:
        selected_matches = [a for a in selected.get("assets", []) if a.get("asset_id") == selected_asset.get("asset_id")]
    if len(selected_matches) != 1:
        raise ValueError("所选管段已变化，请重新选择")
    selected_asset = selected_matches[0]
    if not is_pressure_cover_asset(selected_asset):
        raise ValueError("同线导入请选择有压管道或倒虹吸")
    source = deepcopy(source or {})
    if source.get("path"):
        source["path"] = str(Path(source["path"]).resolve())
        digest = file_sha256(source["path"])
        if source.get("sha256") and source["sha256"] != digest:
            raise ValueError("纵断面源文件已变化，请重新导入")
        source["sha256"] = digest
    mapping = deepcopy(mapping or {})
    units = mapping.get("source_units", source_units)
    if "station_offset_m" not in mapping:
        _, mapping = prepare_imported_profile(profile, selected_asset, inputs=inputs,
            source_units=units, selected_network=selected)
    offset = float(mapping["station_offset_m"])
    factors = {"m": 1., "mm": .001, "cm": .01, "in": .0254, "ft": .3048}
    if units not in factors:
        raise ValueError("纵断面坐标单位无效")
    raw = normalize_design_profile(profile)
    start, end = (raw["station_start"]*factors[units]+offset, raw["station_end"]*factors[units]+offset)
    full, _ = prepare_imported_profile(raw, {"station_start": start, "station_end": end},
        station_offset=offset, source_units=units)
    updated = deepcopy(inputs)
    report = {"scope": scope, "assets": [], "trenchless": [], "skipped": [],
        "route_fingerprint": _route_fingerprint(selected), "mapping": deepcopy(mapping),
        "source": deepcopy(source), "source_profile_range_m": [start, end]}
    provenance = {**source, "coordinate_units": units, "coordinate_scale_to_m": factors[units],
                  "station_offset_m": offset, "reference": full["reference"],
                  "mapping_basis": mapping.get("mapping_basis", "来源全局桩号"),
                  "route_fingerprint": report["route_fingerprint"]}
    for index, network in enumerate(inputs.get("networks", [])):
        if not _same_source_route(network, selected):
            continue
        for j, asset in enumerate(network.get("assets", [])):
            if scope == "current" and asset is not selected_asset:
                continue
            if not is_pressure_cover_asset(asset):
                continue
            a, b = asset.get("station_start"), asset.get("station_end")
            if a is None or b is None or a < start-.001 or b > end+.001:
                report["skipped"].append(asset.get("asset_id")); continue
            clipped, rounding = prepare_imported_profile(full, asset, station_offset=0.)
            target = updated["networks"][index]["assets"][j]
            apply_asset_profile(target, clipped, provenance, terminal_rounding=rounding["terminal_rounding_m"])
            report["assets"].append(asset["asset_id"])
    if selected_asset["asset_id"] not in report["assets"]:
        raise ValueError("纵线未完整覆盖所选管段")
    if scope == "covered_route":
        for i, excluded in enumerate(inputs.get("excluded", [])):
            if excluded.get("construction_method") not in {"顶管", "定向钻"} or not _exclusion_on_route(excluded, selected):
                continue
            a, b = excluded.get("station_start"), excluded.get("station_end")
            if a is None or b is None or a < start-.001 or b > end+.001:
                continue
            clipped, _ = prepare_imported_profile(full, excluded, station_offset=0.)
            target = updated["excluded"][i]
            apply_trenchless_route_profile(target, clipped, provenance)
            report["trenchless"].append(target.get("source_identity") or target.get("asset_id"))
    if source.get("path"):
        files = updated.setdefault("input_files", [])
        files[:] = [f for f in files if os.path.normcase(str(f.get("path", ""))) != os.path.normcase(source["path"])]
        files.append(deepcopy(provenance))
    for diagnostic in updated.get("diagnostics", []):
        if diagnostic.get("asset_id") in report["assets"] and diagnostic.get("field") == "design_profile":
            diagnostic.update(resolved=True, resolution="user_input_real_elevation")
    report["asset_ids"] = list(report["assets"])
    report["applied_count"] = len(report["assets"])
    return updated, report
