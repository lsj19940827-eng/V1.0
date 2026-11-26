"""Map selected CAD polylines to construction objects in true route stationing."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from 土石方计算.services.batch_cover_profiles import is_pressure_cover_asset
from 土石方计算.services.design_profiles import normalize_design_profile
from 土石方计算.services.earthwork_scope import trenchless_method
from 土石方计算.services.imported_design_profiles import (
    _exclusion_on_route, _same_source_route, apply_asset_profile, apply_trenchless_route_profile,
    prepare_imported_profile,
)
from 土石方计算.services.siphon_axis_choices import configure_siphon_axis, is_siphon_axis_asset
from 土石方计算.services.pipe_profile_partitions import partition_piece, resolve_profile_gap

FACTORS = {"m": 1., "mm": .001, "cm": .01, "in": .0254, "ft": .3048}
ROUTE = "route"


@dataclass
class ProfileCoverage:
    runs: list = field(default_factory=list)
    gaps: list = field(default_factory=list)


def profile_key(network, asset):
    return (str(network.get("network_id") or network.get("route_id") or network.get("source_identity") or ""),
            str(asset["asset_id"]))


def profile_objects(inputs):
    return {profile_key(n, a): (n, a) for n in inputs.get("networks", [])
            for a in n.get("assets", []) if is_pressure_cover_asset(a)}


def eligible_objects(objects, selected):
    network, asset = objects[selected]
    siphon = is_siphon_axis_asset(asset)
    return {key: (n, a) for key, (n, a) in objects.items()
            if is_siphon_axis_asset(a) == siphon and (siphon or _same_source_route(n, network))
            and a.get("station_start") is not None and a.get("station_end") is not None}


def trenchless_targets(inputs, network):
    targets={}
    for i,row in enumerate(inputs.get("excluded",[])):
        method=row.get("construction_method")
        if method not in {"顶管","定向钻"} or not _exclusion_on_route(row,network):continue
        if row.get("station_start") is None or row.get("station_end") is None:continue
        original=row.get("original_asset_snapshot") or {}
        targets[(None,i)]=(network,dict(row,asset_id=row.get("asset_id") or row.get("source_identity"),
            name=row.get("name") or original.get("name") or method,kind="trenchless",source_type=method))
    return targets


def source_bounds(curve, units):
    p = curve["profile"]
    return p["station_start"] * FACTORS[units], p["station_end"] * FACTORS[units]


_STATION_TOL = .001


@dataclass(frozen=True)
class _DrawingLine:
    row: int
    left: float
    right: float
    tunnel_layer: bool


def _ordered_panel_mapping(groups, slots):
    """Align drawing panels with non-overlapping route intervals using translation only."""
    slots = sorted(slots, key=lambda slot: (slot[0], slot[1]))
    if len(groups) != len(slots) or any(b > a + _STATION_TOL
            for (_, b, _), (a, _, _) in zip(slots, slots[1:])):
        return None
    mapping = {}
    complete = True
    for group, (a, b, key) in zip(groups, slots):
        left, right = group[0].left, group[-1].right
        length = right - left
        exact = abs(length - (b - a)) <= _STATION_TOL
        named_tunnel = any(line.tunnel_layer for line in group)
        if length > b - a + _STATION_TOL or (key is not None and named_tunnel):
            return None
        # A generic line can identify an optional tunnel or bore by its full span.
        if (key is None or key[0] is None) and not (exact or named_tunnel):
            return None
        complete = complete and (key is None or exact)
        origin = left if a <= left and right <= b else a
        for line in group:
            mapping[line.row] = (key, origin + (line.left - left))
    return mapping, complete


def _drawing_panels(lines):
    panels = []
    for line in lines:
        if not panels or line.left > panels[-1][-1].right + _STATION_TOL:
            panels.append([])
        panels[-1].append(line)
    return panels


def _shared_pipe_offset(lines, targets):
    """Use a full pipe as an anchor when one translation explains every drawing interval."""
    pipes = [(a["station_start"], a["station_end"], key) for key, (_, a) in targets.items() if key[0] is not None]
    if len(pipes) < 2 or any(line.tunnel_layer for line in lines):
        return None
    extents = {(line.left, line.right) for line in lines}
    extents.update((panel[0].left, panel[-1].right) for panel in _drawing_panels(lines))
    offsets = {start - left for left, right in extents for start, end, _ in pipes
               if abs((end - start) - (right - left)) <= _STATION_TOL}
    result = None
    first_offset = None
    for offset in sorted(offsets):
        mapping = {}
        for line in lines:
            start, end = line.left + offset, line.right + offset
            fits = [key for a, b, key in pipes if a - _STATION_TOL <= start and end <= b + _STATION_TOL]
            if len(fits) != 1:
                break
            mapping[line.row] = (fits[0], start)
        if len(mapping) != len(lines) or len({key for key, _ in mapping.values()}) < 2:
            continue
        if first_offset is None:
            result, first_offset = mapping, offset
        elif offset - first_offset > _STATION_TOL:
            return None
    return result


def _ordered_pressure_mapping(lines, targets, tunnels):
    pipes, bores = [], []
    for key, (_, asset) in targets.items():
        span = (asset["station_start"], asset["station_end"], key)
        (bores if key[0] is None else pipes).append(span)
    if len(pipes) < 2:
        return None

    # One panel may consist of several adjacent polylines sharing a drawing origin.
    # Try single entities too: separate objects sometimes touch on the drawing.
    panels = _drawing_panels(lines)
    groupings = [[[line] for line in lines]]
    if len(panels) != len(lines):
        groupings.append(panels)

    layouts = [pipes]
    if bores:
        layouts.append(pipes + bores)
    if tunnels:
        optional_tunnels = [(a, b, None) for a, b in sorted(set(tunnels))]
        layouts += [slots + optional_tunnels for slots in layouts]
    options = []
    for groups in groupings:
        for slots in layouts:
            mapping = _ordered_panel_mapping(groups, slots)
            if mapping is not None and mapping not in options:
                options.append(mapping)
    return options[0] if len(options) == 1 else None


def _pressure_assignments(lines, targets, tunnels, competing):
    first = min(asset["station_start"] for _, asset in targets.values())
    last = max(asset["station_end"] for _, asset in targets.values())
    left, right = lines[0].left, max(line.right for line in lines)
    offset = first - left if abs((right - left) - (last - first)) <= _STATION_TOL else 0.
    if (len(targets) == 1 and len(lines) > 1 and not competing
            and (right < first or left > last) and right - left <= last - first):
        # There is only one possible receiving object. Translate the drawing as
        # a whole, preserving the measured empty distances between its parts.
        offset = first - left
    mapping = {}
    all_located = True
    tunnel_only = set()
    whole_tunnels = set()
    for line in lines:
        a, b = line.left + offset, line.right + offset
        hits = [k for k, (_, asset) in targets.items()
                if min(b, asset["station_end"]) - max(a, asset["station_start"]) > 1e-7]
        key = hits[0] if len(hits) == 1 else ROUTE if hits else None
        mapping[line.row] = (None if line.row in competing or line.tunnel_layer else key, a)
        fits = any(asset["station_start"] - _STATION_TOL <= a and b <= asset["station_end"] + _STATION_TOL
                   for _, asset in targets.values())
        in_tunnel = any(start - _STATION_TOL <= a and b <= end + _STATION_TOL for start, end in tunnels)
        if in_tunnel and not hits:
            tunnel_only.add(line.row)
            if any(abs(a - start) <= _STATION_TOL and abs(b - end) <= _STATION_TOL for start, end in tunnels):
                whole_tunnels.add(line.row)
        all_located = all_located and (fits or in_tunnel)
    if len(lines) == 1 or competing or (all_located and not tunnel_only):
        return mapping
    if not all_located and not whole_tunnels:
        shared = _shared_pipe_offset(lines, targets)
        if shared is not None:
            return shared
    ordered = _ordered_pressure_mapping(lines, targets, tunnels)
    if ordered is None and any(line.tunnel_layer for line in lines):
        # The drawing may include just some of the known tunnels. Their labelled
        # entities do not take up any of the upstream-to-downstream pipe slots.
        axes = [line for line in lines if not line.tunnel_layer]
        ordered = _ordered_pressure_mapping(axes, targets, ())
        if ordered is not None:
            ordered[0].update({line.row: mapping[line.row] for line in lines if line.tunnel_layer})
    if ordered is None:
        return mapping
    proposal, complete = ordered
    if any(proposal[row][0] is not None for row in whole_tunnels):
        return mapping
    # A panel's drawing X can fall inside a much longer tunnel on the real
    # route. An exact ordered set of pipe lengths resolves that coincidence.
    if all_located and not (complete and any(proposal[row][0] is not None for row in tunnel_only)):
        return mapping
    return proposal


def _siphon_assignment(curve, line, targets):
    start, end = line.left, line.right
    stem = Path(curve["source"]["path"]).stem.casefold()
    names = [k for k, (_, a) in targets.items() if a.get("name") and a["name"].casefold() in stem]
    exact = [k for k, (_, a) in targets.items() if abs(a["station_start"]-start)<=_STATION_TOL
             and abs(a["station_end"]-end)<=_STATION_TOL]
    lengths = [k for k, (_, a) in targets.items()
               if abs((a["station_end"]-a["station_start"])-(end-start))<=_STATION_TOL]
    matches = names or exact or lengths or list(targets)
    key = matches[0] if len(matches)==1 else None
    if key:
        _, a = targets[key]
        if start > a["station_start"]+_STATION_TOL or end < a["station_end"]-_STATION_TOL:
            start = a["station_start"]
    return key, start


def suggest_assignments(curves, targets, *, siphon, tunnel_ranges=()):
    """Suggest an object and real starting station for each original drawing row."""
    proposals = [(None, 0.)] * len(curves)
    if not targets:
        return proposals
    tunnels = tuple(tunnel_ranges)
    by_file = defaultdict(list)
    for row, curve in enumerate(curves):
        if "profile" in curve:
            left, right = source_bounds(curve, curve.get("units", "m"))
            layer = curve.get("layer", "").lower()
            names_tunnel = "无压隧洞" in layer or (bool(tunnels) and ("隧洞" in layer or "tunnel" in layer))
            tunnel_layer = names_tunnel and "管" not in layer and "pipe" not in layer
            by_file[curve["source"]["path"]].append(_DrawingLine(row, left, right, tunnel_layer))
    for lines in by_file.values():
        lines.sort(key=lambda line: (line.left, line.right))
        competing = set()
        furthest = lines[0]
        for line in lines[1:]:
            if line.left < furthest.right - _STATION_TOL:
                competing.update((line.row, furthest.row))
            if line.right > furthest.right:
                furthest = line
        if siphon:
            for line in lines:
                proposals[line.row] = ((None, line.left) if line.row in competing else
                                       _siphon_assignment(curves[line.row], line, targets))
        else:
            for row, value in _pressure_assignments(lines, targets, tunnels, competing).items():
                proposals[row] = value
    return proposals


def mapped_profiles(curves, assignments, targets, *, target_groups=None):
    """Clip each line to its chosen assets before combining adjacent pieces."""
    pieces = defaultdict(list)
    target_groups = target_groups or {}
    for curve, assignment in zip(curves, assignments, strict=True):
        key, units, origin, reference = assignment
        if key is None:
            continue
        destinations = targets if key == ROUTE else target_groups.get(key, (key,) if key in targets else ())
        scope = "covered_route" if key == ROUTE or key in target_groups else "current"
        start, end = source_bounds(curve, units)
        offset = origin-start
        bounds = {"station_start": origin, "station_end": origin+(end-start)}
        raw = normalize_design_profile(curve["profile"], reference=reference)
        profile, _ = prepare_imported_profile(raw, bounds, station_offset=offset, source_units=units)
        hits = 0
        for destination in destinations:
            _, asset = targets[destination]
            a, b = asset["station_start"], asset["station_end"]
            left, right = max(a, bounds["station_start"]), min(b, bounds["station_end"])
            if right-left <= 1e-7:
                continue
            piece_bounds = {"station_start": a if left-a<=.001 else left,
                            "station_end": b if b-right<=.001 else right}
            piece, _ = prepare_imported_profile(profile, piece_bounds, station_offset=0.)
            provenance = {**curve["source"], "layer": curve["layer"], "handle": curve["handle"],
                          "coordinate_units": units, "station_offset_m": offset, "reference": reference,
                          "source_station_range_m": [start,end],"mapping_scope":scope}
            pieces[destination].append((piece, provenance))
            hits += 1
        if not hits:
            raise ValueError(f"{curve['source']['filename']} / {curve['layer']} 与所选对象桩号没有交集，请核对对应起桩。")
    result = {}
    for key, parts in pieces.items():
        _, asset = targets[key]
        name = asset.get("name") or key[1]
        parts.sort(key=lambda item: item[0]["station_start"])
        expected = asset["station_start"]
        coverage = ProfileCoverage()
        current = []
        for part, source in parts:
            if part["station_start"] > expected+1e-7:
                coverage.gaps.append((expected,part["station_start"]))
                current=[]
            if part["station_start"] < expected-1e-7:
                raise ValueError(f"{name} 在 {part['station_start']:.3f} m 的设计线重叠，请选择要采用的多段线。")
            if part["reference"] != parts[0][0]["reference"]:
                raise ValueError(f"{name} 的各段需采用同一高程基准。")
            if not current:
                coverage.runs.append(current)
            current.append((part,source))
            expected = part["station_end"]
        if expected < asset["station_end"]-1e-7:
            coverage.gaps.append((expected,asset["station_end"]))
        if coverage.gaps and (asset.get("kind") == "trenchless" or trenchless_method(asset)):
            if all(source["mapping_scope"]=="covered_route" for _,source in parts):continue
            raise ValueError(f"{name} 需要覆盖完整非开挖区段的纵断面。")
        if is_siphon_axis_asset(asset) and coverage.gaps:
            start,end=coverage.gaps[0]
            raise ValueError(f"{name} 在 {start:.3f}～{end:.3f} m 缺少设计线，请核对对应桩号。")
        try:
            coverage.runs=[(normalize_design_profile({"elements":[e for p,_ in run for e in p["elements"]]},
                                reference=run[0][0]["reference"]),[source for _,source in run])
                           for run in coverage.runs]
        except ValueError as error:
            raise ValueError(f"{name}：{error}") from error
        result[key] = coverage
    if not result:
        raise ValueError("请选择要采用的多段线及其工程对象。")
    return result


def apply_mapped_profiles(inputs, result, *, confirmed_gaps=False):
    """Return an atomic edit; keep the user's selection and source file hashes."""
    from 土石方计算.io.independent_terrain import file_sha256
    from 土石方计算.services.pipe_axis_continuity import inspect_pipe_axis_continuity, PipeAxisContinuityError

    files = {line["path"]: line for coverage in result.values() for _,lines in coverage.runs for line in lines}
    for path, line in files.items():
        if file_sha256(path) != line["sha256"]:
            raise ValueError(f"{Path(path).name} 已改变，请重新导入。")
    updated = deepcopy(inputs)
    targets = profile_objects(updated)
    for key, coverage in result.items():
        if key[0] is None:
            profile,lines=coverage.runs[0]
            source=dict(lines[0],kind="quantity_dxf",curves=deepcopy(lines))
            apply_trenchless_route_profile(updated["excluded"][key[1]],profile,source)
            continue
        network, asset = targets[key]
        if asset.get("axis_source")=="water_profile_real_elevation" and asset.get("design_profile"):
            asset.setdefault("water_profile_design_profile", deepcopy(asset["design_profile"]))
        if coverage.gaps and not confirmed_gaps:raise ValueError("请核对缺口并选择仅采用已覆盖管段。")
        parts=[]
        for profile,lines in coverage.runs:
            target=partition_piece(asset,profile["station_start"],profile["station_end"],"mapped") if coverage.gaps else asset
            resolve_profile_gap(target)
            source = dict(lines[0], kind="quantity_dxf", curves=deepcopy(lines))
            if is_siphon_axis_asset(target):
                configure_siphon_axis(target, mode="exact", profile=profile, source=source, strict=True)
            else:
                apply_asset_profile(target, profile, source)
            target["pipe_profile_choice"] = "quantity_dxf"
            parts.append(target)
        report = inspect_pipe_axis_continuity({"networks":[{**network, "assets":parts}]}, scope="all")
        if any(d["code"] != "pipe_axis_validation_input" for d in report["diagnostics"]):
            raise PipeAxisContinuityError(report)
        if coverage.gaps:
            evidence=[{k:source[k] for k in ("filename","sha256","handle","layer")}
                      for _,lines in coverage.runs for source in lines]
            for start,end in coverage.gaps:
                gap=partition_piece(asset,start,end,"pending")
                gap["pipe_profile_partition"]["source_curves"]=evidence
                parts.append(gap)
            index=network["assets"].index(asset)
            network["assets"][index:index+1]=sorted(parts,key=lambda p:p["station_start"])
    entries=updated.setdefault("input_files",[])
    listed = {entry["path"]: entry for entry in entries if entry.get("path")}
    for path, source in files.items():
        metadata = {k:source[k] for k in ("path","filename","sha256","declared_dxf_units")}
        if path in listed:listed[path].update(metadata)
        else:entries.append(metadata)
    return updated
