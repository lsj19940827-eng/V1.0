"""Read-only longitudinal cuts along an existing analytical plan centerline.

This is a terrain/profile query, independent of transverse quantity sampling.
Original TIN faces, line/arc geometry and actual design datums are preserved.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math

import numpy as np
import shapely

from ..core.terrain_sections import TerrainSectionIndex
from .design_profiles import normalize_design_profile, evaluate_profile, DesignProfileError
from .network_alignment import NetworkAlignment


_LABELS = {"inner_invert": "设计内底", "pipe_axis": "首管管轴",
           "common_outer_bottom": "共同外管底", "foundation_base": "基础底"}


def _cancel(cancelled):
    if cancelled and cancelled():
        raise InterruptedError("中心轴线纵断面剖切已取消")


def _number(value, label):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label}必须是有限数值")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label}必须是有限数值") from error
    if not math.isfinite(result):
        raise ValueError(f"{label}必须是有限数值")
    return result


def _unique(values, start, end):
    tolerance = np.finfo(float).eps * max(1., abs(start), abs(end), end-start) * 16
    result = []
    for value in sorted(float(v) for v in values if start <= v <= end):
        if not result or value-result[-1] > tolerance:
            result.append(value)
    if not result or result[0] > start:
        result.insert(0, start)
    else:
        result[0] = start
    if end-result[-1] <= tolerance:
        result[-1] = end
    else:
        result.append(end)
    return result


def _design_source(network, asset, reference):
    original = asset.get("original_fields") or {}
    raw_profile = asset.get("design_profile") or {}
    if not isinstance(raw_profile, dict):
        raw_profile = {}
    test = bool(network.get("test_only") or network.get("is_test") or asset.get("test_only")
                or asset.get("is_test") or asset.get("longitudinal_is_example")
                or original.get("longitudinal_is_example")
                or raw_profile.get("test_only") or raw_profile.get("is_test"))
    profile_source = asset.get("profile_source")
    kind = profile_source.get("kind", "") if isinstance(profile_source, dict) else str(profile_source or "")
    generated = bool(asset.get("axis_source") == "terrain_and_user_cover_depth"
                     or kind == "terrain_with_user_pipe_top_cover" or asset.get("cover_generation_options"))
    assumed = bool(generated or asset.get("is_assumed") or asset.get("assumptions"))
    source_label = "TEST设计纵断面" if test else "地形与用户埋深生成" if generated else "假定设计来源" if assumed else "已有设计纵断面" if reference else "已有设计高程-基准未明确"
    source = {key: deepcopy(asset[key]) for key in (
        "profile_source", "axis_source", "profile_source_file", "source_identity", "cover_generation_options",
        "axis_preview_sha256", "test_overrides", "assumptions") if key in asset}
    return {"test_only": test, "is_assumed": assumed, "source_label": source_label, "source": source}


def _designs(network, start, end):
    series, issues, extras = [], [], {start, end}
    for index, asset in enumerate(network.get("assets") or []):
        if not asset.get("enabled", True):
            continue
        a = _number(asset.get("station_start"), "对象起桩")
        b = _number(asset.get("station_end"), "对象止桩")
        if b <= a or b < start or a > end:
            continue
        extras.update((max(start, a), min(end, b)))
        identity = str(asset.get("asset_id") or f"asset-{index+1}")
        raw_profile = asset.get("design_profile") or {}
        declared = (raw_profile.get("reference") if isinstance(raw_profile, dict) else None) or asset.get("alignment", {}).get("elevation_reference")
        try:
            profile = normalize_design_profile(asset, reference=declared)
        except (DesignProfileError, TypeError, KeyError) as error:
            issues.append({"asset_id": identity, "message": str(error)})
            continue
        a, b = max(start, a, profile["station_start"]), min(end, b, profile["station_end"])
        if b <= a:
            continue
        reference = str(declared) if declared else None
        provenance = _design_source(network, asset, reference)
        label = _LABELS.get(reference, "设计高程（基准未明确）" if reference is None else f"设计高程（{reference}）")
        if provenance["test_only"]:
            label += "（TEST）"
        elif provenance["is_assumed"]:
            label += "（假定/生成来源）"
        row = {"run_id": f"design-{index+1}", "asset_id": identity, "reference": reference,
               "label": label, "station_start": a, "station_end": b, "profile": profile, **provenance}
        series.append(row)
        extras.update((a, b))
        for element in profile["elements"]:
            extras.update(s for s in (element["station_start"], element["station_end"]) if a <= s <= b)
            if element["kind"] == "arc" and a < element["center_station"] < b:
                extras.add(element["center_station"])
    return series, issues, extras


def _line_cut(index, element, start, end, step, extras):
    direction = np.asarray(element["end_xy"], dtype=float)-element["start_xy"]
    length = float(np.linalg.norm(direction))
    if length <= 0:
        raise ValueError("平面中心轴线含零长度直线")
    direction /= length
    rows = index.section_line(element["start_xy"], direction,
                              start-element["station_start"], end-element["station_start"], step)
    points = [(element["station_start"]+s, float(z) if math.isfinite(z) else None) for s, z in rows]
    points[0] = (start, points[0][1])
    points[-1] = (end, points[-1][1])
    positions = [s for s, _ in points]
    inserted = []
    for s in extras:
        if not start < s < end:
            continue
        i = bisect_left(positions, s)
        if i < len(points) and positions[i] == s:
            continue
        a, za = points[i-1]
        b, zb = points[i]
        z = za+(s-a)/(b-a)*(zb-za) if za is not None and zb is not None else None
        inserted.append((s, z))
    return sorted(points+inserted)


def _ground_at_xy(index, xy):
    """Query one canonical binary XY on the original faces, without averaging.

    Adjacent line/arc formulas can round their shared WCS endpoint differently.
    Their two Z values therefore are not a same-point consistency comparison.
    Resolve the authoritative alignment XY once, with exact binary-rational
    plane interpolation; truly different elevations at that XY remain errors.
    """
    local = np.asarray(xy, dtype=float)-index._origin
    ids = index._tree.query(shapely.Point(local), predicate="intersects")
    index._check_topology(ids)
    value = None
    px, py = map(Fraction.from_float, map(float, local))
    for face in ids:
        corners = index._points[index._triangles[face]]
        a, b, c = [tuple(Fraction.from_float(float(v)) for v in row) for row in corners]
        ux, uy, vx, vy = b[0]-a[0], b[1]-a[1], c[0]-a[0], c[1]-a[1]
        denominator = ux*vy-uy*vx
        weight_b = ((px-a[0])*vy-(py-a[1])*vx)/denominator
        weight_c = (ux*(py-a[1])-uy*(px-a[0]))/denominator
        z = a[2]+weight_b*(b[2]-a[2])+weight_c*(c[2]-a[2])
        if value is not None and abs(float(z-value)) > np.finfo(float).eps*max(1., abs(float(z)), abs(float(value)))*256:
            raise ValueError("中心轴线规范接点存在互相矛盾的 TIN 高程")
        value = z if value is None else value
    return float(value) if value is not None else None


def _arc_xy(element, stations, local_origin=None):
    values = np.asarray(stations, dtype=float)
    sign = math.copysign(1., element["sweep_angle"])
    angles = element["start_angle"]+sign*(values-element["station_start"])/element["radius"]
    center = np.asarray(element["center_xy"])
    if local_origin is not None:
        center = center-np.asarray(local_origin)
    return center+element["radius"]*np.column_stack((np.cos(angles), np.sin(angles)))


def _arc_cut(index, element, start, end, step, extras, cancelled):
    """Split the real arc at every original triangle edge, including tiny gaps.

    Within each covered interval Z is the original triangle plane evaluated
    at the true circle. Sampling only adds display vertices; it never chooses
    terrain topology or turns the plan arc into a chord.
    """
    radius = _number(element.get("radius"), "平面圆弧半径")
    if radius <= 0:
        raise ValueError("平面圆弧半径必须为正")
    sign = math.copysign(1., element["sweep_angle"])
    aa = element["start_angle"]+sign*(start-element["station_start"])/radius
    bb = element["start_angle"]+sign*(end-element["station_start"])/radius
    low, high = sorted((aa, bb))
    cardinal = [i*math.pi/2 for i in range(math.ceil(low/(math.pi/2)), math.floor(high/(math.pi/2))+1)]
    angles = np.asarray([aa, bb, *cardinal])
    center = np.asarray(element["center_xy"])-index._origin
    xy = center+radius*np.column_stack((np.cos(angles), np.sin(angles)))
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    pad = np.finfo(float).eps*max(1., *abs(lo), *abs(hi), radius)*32
    ids = index._tree.query(shapely.box(*(lo-pad), *(hi+pad)))
    index._check_topology(ids)
    _cancel(cancelled)
    faces = index._triangles[ids]
    events = [start, end]
    if len(faces):
        edges = np.unique(np.sort(np.vstack((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])), axis=1), axis=0)
        origin = index._points[edges[:, 0], :2]-center
        vector = index._points[edges[:, 1], :2]-index._points[edges[:, 0], :2]
        aq = np.sum(vector*vector, axis=1)
        bq = 2*np.sum(origin*vector, axis=1)
        cq = np.sum(origin*origin, axis=1)-radius*radius
        disc = bq*bq-4*aq*cq
        disc_limit = np.finfo(float).eps*(bq*bq+abs(4*aq*cq))*32
        valid = (aq > 0) & (disc >= -disc_limit)
        root = np.sqrt(np.maximum(0., disc[valid]))
        # Stable quadratic roots prevent cancellation near tiny terrain gaps.
        q = -.5*(bq[valid]+np.copysign(root, bq[valid]))
        first = np.divide(q, aq[valid])
        second = np.divide(cq[valid], q, out=np.zeros_like(q), where=q != 0)
        for ratios in (first, second):
            inside = (ratios >= -np.finfo(float).eps*32) & (ratios <= 1+np.finfo(float).eps*32)
            hit = origin[valid][inside]+np.clip(ratios[inside], 0., 1.)[:, None]*vector[valid][inside]
            delta = np.mod(sign*(np.arctan2(hit[:, 1], hit[:, 0])-element["start_angle"]), 2*math.pi)
            delta[np.abs(delta-2*math.pi) < np.finfo(float).eps*64] = 0.
            stations = element["station_start"]+radius*delta
            events.extend(float(s) for s in stations if start < s < end)
    breaks = _unique(events, start, end)
    middles = (np.asarray(breaks[:-1])+breaks[1:])/2
    local = _arc_xy(element, middles, index._origin)
    pairs = index._tree.query(shapely.points(local), predicate="intersects")
    owners = np.full(len(middles), -1, dtype=int)
    if len(pairs[0]):
        owners[pairs[0]] = pairs[1]
    plane_ids = np.unique(owners[owners >= 0])
    gradients = {}
    for face in plane_ids:
        corners = index._points[index._triangles[face]]
        gradients[int(face)] = (corners[0], np.linalg.solve(corners[1:, :2]-corners[0, :2], corners[1:, 2]-corners[0, 2]))
    samples = [start+i*step for i in range(math.floor((end-start)/step)+1)]
    samples += breaks+[s for s in extras if start <= s <= end]
    # Keep an exact high/low point even when the whole rise fits one face.
    for a, b, owner in zip(breaks, breaks[1:], owners):
        if owner < 0:
            continue
        gradient = gradients[int(owner)][1]
        theta = math.atan2(gradient[1], gradient[0])
        for angle in (theta, theta+math.pi):
            delta = (sign*(angle-element["start_angle"])) % (2*math.pi)
            s = element["station_start"]+radius*delta
            if a < s < b:
                samples.append(s)
    positions = _unique(samples, start, end)
    elevations = [None]*len(positions)
    gaps = []
    for i, (a, b, owner) in enumerate(zip(breaks, breaks[1:], owners)):
        if i % 128 == 0:
            _cancel(cancelled)
        if owner < 0:
            gaps.append((a, b))
            continue
        first, last = bisect_left(positions, a), bisect_right(positions, b)
        coords = _arc_xy(element, positions[first:last], index._origin)
        corner, gradient = gradients[int(owner)]
        heights = corner[2]+(coords-corner[:2])@gradient
        for j, height in enumerate(heights, first):
            old = elevations[j]
            limit = np.finfo(float).eps*max(1., abs(height))*512+float(np.linalg.norm(gradient))*pad*8
            if old is not None and abs(old-height) > limit:
                raise ValueError("中心轴线剖切位置存在互相矛盾的 TIN 高程")
            elevations[j] = float(height)
    # Missing open intervals always have a null sentinel, even below step.
    rows = list(zip(positions, elevations))
    for a, b in gaps:
        middle = (a+b)/2
        first, last = bisect_right(positions, a), bisect_left(positions, b)
        if not any(z is None for z in elevations[first:last]):
            rows.append((middle, None))
    return sorted(rows)


def _missing_ranges(points):
    result, first = [], None
    for i, (station, elevation) in enumerate(points):
        if elevation is None and first is None:
            first = points[i-1][0] if i else station
        if elevation is not None and first is not None:
            if station > first:
                result.append({"station_start": first, "station_end": station})
            first = None
    if first is not None and points[-1][0] > first:
        result.append({"station_start": first, "station_end": points[-1][0]})
    return result


def cut_centerline_profile(tin, network, *, station_start=None, station_end=None,
                           sample_step=1.0, cancelled=None, progress=None):
    """Cut natural ground and available design datum along one existing route.

    Consumers must group ground/design polylines by their respective run IDs.
    Shared asset boundaries may contain two rows at the same station, retaining
    both actual design endpoints without joining different objects/datums.
    """
    _cancel(cancelled)
    alignment = network.get("alignment")
    if isinstance(alignment, dict):
        alignment = NetworkAlignment.from_dict(alignment)
    if not isinstance(alignment, NetworkAlignment) or not alignment.elements:
        raise ValueError("请先提供已有的真实平面中心轴线")
    step = _number(sample_step, "纵断面显示采样间距")
    if step <= 0:
        raise ValueError("纵断面显示采样间距必须为正")
    start = _number(alignment.start_station if station_start is None else station_start, "剖切起桩")
    end = _number(alignment.end_station if station_end is None else station_end, "剖切止桩")
    if end <= start:
        raise ValueError("剖切止桩必须大于起桩")
    if start < alignment.start_station or end > alignment.end_station:
        raise ValueError("剖切桩号超出真实中心轴线，禁止外推")
    if (end-start)/step > 2_000_000:
        raise ValueError("纵断面显示点超过200万，请增大采样间距或缩短范围")
    designs, issues, extras = _designs(network, start, end)
    if progress:
        progress("profile_prepare", 0., "正在准备原地形与真实平面中心轴线")
    selected_tin = tin
    selection = {"original_face_count": int(len(tin.triangles)), "selected_face_count": int(len(tin.triangles)),
                 "retriangulated": False, "method": "original_faces"}
    if len(tin.triangles) > 100_000:
        from .network_project import select_network_terrain
        if progress:
            progress("profile_prepare", .05, "正在筛选中心轴线附近的完整原地形三角片")
        # Selection only. The existing conservative buffer is 10 m with
        # width=5, including arc-chord deviation and whole intersecting faces.
        try:
            selected_tin = select_network_terrain(tin, {**network, "alignment": alignment}, width=5., cancelled=cancelled)
        except ValueError as error:
            _cancel(cancelled)
            if "没有原地形三角片" not in str(error):
                raise
            selected_tin = None
        selection.update(selected_face_count=int(len(selected_tin.triangles)) if selected_tin is not None else 0,
                         method="whole_original_faces_near_exact_route", conservative_margin_m=10.)
    index = TerrainSectionIndex(selected_tin) if selected_tin is not None else None
    _cancel(cancelled)
    elements = [e for e in alignment.elements if e["station_end"] > start and e["station_start"] < end]
    ground = []
    for i, element in enumerate(elements):
        _cancel(cancelled)
        a, b = max(start, element["station_start"]), min(end, element["station_end"])
        if ground:
            if abs(a-ground[-1][0]) > 1e-7:
                raise ValueError("中心轴线存在缺段，请分别选择实际连续线路")
            previous = elements[i-1]
            if not np.allclose(previous["end_xy"], element["start_xy"], rtol=0., atol=1e-7):
                raise ValueError("中心轴线包含不同实际线路，请分别剖切")
        if index is None:
            rows = [(s, None) for s in _unique([a+j*step for j in range(math.floor((b-a)/step)+1)]
                                              +[s for s in extras if a <= s <= b], a, b)]
        elif element["kind"] == "line":
            rows = _line_cut(index, element, a, b, step, extras)
        elif element["kind"] == "arc":
            rows = _arc_cut(index, element, a, b, step, extras, cancelled)
        else:
            raise ValueError("中心轴线含不支持的平面线元")
        if ground and rows[0][0] == ground[-1][0]:
            # Both formulas refer to the same nominal station, but an arc
            # evaluated near a large WCS endpoint may differ by an XY ULP.
            # The public analytical alignment supplies one authoritative XY.
            canonical = _ground_at_xy(index, alignment.get_xy_at_station(a)) if index is not None else None
            ground[-1] = (a, canonical)
            rows = rows[1:]
        ground.extend(rows)
        if progress:
            progress("profile_cut", (i+1)/len(elements), f"已剖切 {i+1}/{len(elements)} 个真实线元")
    if not ground:
        raise ValueError("剖切范围没有有效的真实中心轴线")
    missing = _missing_ranges(ground)
    points, run, inside = [], 0, False
    for i, (station, elevation) in enumerate(ground):
        if i % 512 == 0:
            _cancel(cancelled)
        if elevation is None:
            inside = False
            ground_run = None
        else:
            if not inside:
                run += 1
            inside = True
            ground_run = f"ground-{run}"
        x, y = alignment.get_xy_at_station(station)
        matching = [row for row in designs if row["station_start"] <= station <= row["station_end"]]
        base = {"station": float(station), "x": float(x), "y": float(y),
                "ground_elevation": elevation, "ground_run_id": ground_run}
        if not matching:
            points.append({**base, "design_elevation": None, "design_reference": None,
                           "asset_id": None, "design_run_id": None, "design_label": None,
                           "design_is_test": False, "design_is_assumed": False})
        for row in matching:
            points.append({**base, "design_elevation": float(evaluate_profile(row["profile"], station)[0]),
                           "design_reference": row["reference"], "asset_id": row["asset_id"],
                           "design_run_id": row["run_id"], "design_label": row["label"],
                           "design_is_test": row["test_only"], "design_is_assumed": row["is_assumed"]})
    terrain_hash = hashlib.sha256()
    for array in (tin.points, tin.triangles):
        contiguous = np.ascontiguousarray(array)
        terrain_hash.update(str((contiguous.shape, contiguous.dtype.str)).encode("ascii"))
        # Chunking allows cancellation while fingerprinting a large original TIN.
        data = memoryview(contiguous).cast("B")
        for offset in range(0, len(data), 4_194_304):
            _cancel(cancelled)
            terrain_hash.update(data[offset:offset+4_194_304])
    terrain_digest = terrain_hash.hexdigest()
    source = {"alignment": alignment.to_dict(), "terrain_sha256": terrain_digest,
              "design_series": [{**r, "profile": dict(r["profile"])} for r in designs]}
    digest = hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()
    metadata = {"station_basis": "true_plan_arclength", "units": "m", "quantity_calculated": False,
                "terrain_method": "original_tin_faces_exact_edge_events", "source_identity": digest,
                "terrain_sha256": terrain_digest,
                "terrain_selection": selection,
                "design_series": [{k: v for k, v in row.items() if k != "profile"} for row in designs],
                "design_issues": issues, "ground_point_count": len(ground),
                "test_only": bool(network.get("test_only") or network.get("is_test") or any(row["test_only"] for row in designs)),
                "is_test": bool(network.get("is_test")),
                "contains_assumed_design": any(row["is_assumed"] for row in designs),
                "network_source": {key: deepcopy(network[key]) for key in ("source_identity", "source", "assumptions") if key in network},
                "missing_length": sum(row["station_end"]-row["station_start"] for row in missing)}
    for key in ("design_source", "quantity_basis", "construction_assumptions"):
        if key in network:
            metadata[key] = deepcopy(network[key])
    result = {"schema_version": "1.0", "kind": "centerline_longitudinal",
              "route_id": str(network.get("route_id") or network.get("network_id") or network.get("id") or "route"),
              "route_name": str(network.get("route_name") or network.get("name") or network.get("route_id") or "当前线路"),
              "station_start": start, "station_end": end, "sample_step": step,
              "points": points, "missing_ranges": missing, "metadata": metadata}
    _cancel(cancelled)
    if progress:
        progress("profile_complete", 1., f"中心轴线纵断面已生成，共 {len(ground)} 个剖切点")
    return result
