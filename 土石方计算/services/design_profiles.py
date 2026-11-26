"""Serializable design elevations and pipe-cover previews, without a 3D backend.

Stations are true plan chainage. Profile arcs live in the (chainage, elevation)
plane; they are not replaced by chords. Cover previews explicitly retain their
axis/support datum and never modify an imported hydraulic axis implicitly.
"""
from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from dataclasses import asdict, is_dataclass
import hashlib
import json
import math


class DesignProfileError(ValueError):
    def __init__(self, message, *, code="invalid_design_profile", station=None):
        super().__init__(message)
        self.code, self.station = code, station


class DesignProfile(dict):
    """JSON-compatible validated profile with an in-memory station index."""
    def __init__(self, value):
        super().__init__(value)
        self.starts=tuple(e["station_start"] for e in self["elements"])


def _number(value, label):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DesignProfileError(f"{label}未提供或不是有效数值") from exc
    if not math.isfinite(result):
        raise DesignProfileError(f"{label}必须是有限数值")
    return result


def _dict(value):
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value)


def _source(value):
    if isinstance(value, dict):
        if value.get("design_profile"):
            return value["design_profile"]
        if value.get("elements"):
            return value
        if value.get("profile_elements"):
            return {"elements": value["profile_elements"], "reference": value.get("reference", "inner_invert")}
        if value.get("raw_profile_polyline"):
            return value["raw_profile_polyline"]
        if value.get("longitudinal_nodes"):
            return value["longitudinal_nodes"]
        if value.get("profile_points"):
            return value["profile_points"]
        if value.get("alignment", {}).get("profile_points"):
            return value["alignment"]["profile_points"]
    return value


def _at(element, station):
    if element["kind"] == "line":
        return element["z_start"] + element["slope"] * (station-element["station_start"]), element["slope"]
    x = station-element["center_station"]
    inside = element["radius"]**2-x*x
    if inside <= 1e-14:
        raise DesignProfileError("竖曲线接近竖直切线，须补充可解析的实际过渡轴线", code="near_vertical_profile", station=station)
    root = math.sqrt(inside)
    return element["center_elevation"]+element["branch"]*root, -element["branch"]*x/root


def _canonical_element(raw):
    row = _dict(raw)
    start = _number(row.get("station_start", row.get("s_start")), "纵断面起桩")
    end = _number(row.get("station_end", row.get("s_end")), "纵断面止桩")
    if end <= start:
        raise DesignProfileError("纵断面线元桩号必须递增", station=start)
    kind = str(row.get("kind", row.get("seg_type", "line"))).lower()
    result = {"kind": kind, "station_start": start, "station_end": end}
    if kind == "line":
        result.update(z_start=_number(row.get("z_start", row.get("elevation_start")), "起点高程"),
                      slope=_number(row.get("slope", row.get("k", 0.)), "纵坡"))
    elif kind == "arc":
        result.update(center_station=_number(row.get("center_station", row.get("Sc")), "竖弧弧心桩号"),
                      center_elevation=_number(row.get("center_elevation", row.get("Zc")), "竖弧弧心高程"),
                      radius=_number(row.get("radius", row.get("R_v")), "竖曲线半径"),
                      branch=_number(row.get("branch", row.get("eta", 1)), "竖弧方向"))
        if result["radius"] <= 0 or result["branch"] not in (-1., 1.):
            raise DesignProfileError("竖曲线半径或弧支无效", station=start)
    else:
        raise DesignProfileError(f"不支持的纵断面线元：{kind}", station=start)
    _at(result, start); _at(result, end)
    return result


def _from_raw_polyline(raw):
    if raw.get("parts"):
        return [e for part in raw["parts"] for e in _from_raw_polyline(part)]
    vertices = raw.get("vertices") or []
    points = []
    for value in vertices:
        if isinstance(value, dict):
            points.append((_number(value.get("chainage", value.get("x")), "纵断面桩号"),
                           _number(value.get("elevation", value.get("y")), "纵断面高程")))
        else:
            points.append((_number(value[0], "纵断面桩号"), _number(value[1], "纵断面高程")))
    bulges = list(raw.get("bulges") or [])
    if len(points) > 1 and points[-1][0] < points[0][0]:
        # DXF entity orientation does not change the station/elevation graph.
        # Reversing a curved segment also reverses its signed bulge.
        points.reverse()
        bulges = [-_number(bulges[i], "纵弧凸度") if i < len(bulges) else 0.
                  for i in range(len(points) - 2, -1, -1)]
    elements = []
    for i, (a, b) in enumerate(zip(points, points[1:])):
        if b[0] <= a[0]:
            raise DesignProfileError("原始纵断面包含倒向/竖直区段，不能按单值高程查询", station=a[0])
        bulge = _number(bulges[i] if i < len(bulges) else 0., "纵弧凸度")
        if abs(bulge) < 1e-14:
            elements.append({"kind": "line", "station_start": a[0], "station_end": b[0],
                             "z_start": a[1], "slope": (b[1]-a[1])/(b[0]-a[0])})
            continue
        dx, dz = b[0]-a[0], b[1]-a[1]
        factor = (1-bulge*bulge)/(4*bulge)
        cs, cz = (a[0]+b[0])/2-dz*factor, (a[1]+b[1])/2+dx*factor
        radius = math.hypot(a[0]-cs, a[1]-cz)
        # A graph arc must stay on one branch and contain no vertical tangent.
        if (a[1]-cz)*(b[1]-cz) <= 0 or abs(4*math.atan(bulge)) >= math.pi:
            raise DesignProfileError("纵断面圆弧跨越竖直切线，不能转为假直线", code="near_vertical_profile", station=a[0])
        elements.append({"kind": "arc", "station_start": a[0], "station_end": b[0],
                         "center_station": cs, "center_elevation": cz, "radius": radius,
                         "branch": 1 if a[1] > cz else -1})
    return elements


def _from_nodes(nodes):
    rows = [_dict(row) if not isinstance(row, (tuple, list)) else {"station": row[0], "elevation": row[1]} for row in nodes]
    points = [(_number(row.get("station", row.get("chainage")), "设计桩号"),
               _number(row.get("elevation"), "设计高程"), row) for row in rows]
    if any(b[0] <= a[0] for a, b in zip(points, points[1:])):
        raise DesignProfileError("设计高程节点必须按桩号严格递增")
    elements = []
    index = 0
    while index < len(points)-1:
        s0,z0,row=points[index]
        s1,z1,_=points[index+1]
        radius = _number(row.get("vertical_curve_radius") or 0., "竖曲线半径")
        turn = str(getattr(row.get("turn_type"), "value", row.get("turn_type") or ""))
        is_arc = radius > 0 and (turn not in ("折线","FOLD") or row.get("arc_end_chainage") is not None)
        if is_arc:
            cs, cz = row.get("arc_center_s"), row.get("arc_center_z")
            end = row.get("arc_end_chainage")
            if cs is None or cz is None or end is None:
                raise DesignProfileError("竖曲线缺少真实弧心或弧终桩号，禁止按节点弦线替代", station=s0)
            cs,cz=_number(cs,"竖弧弧心桩号"),_number(cz,"竖弧弧心高程")
            end = _number(end, "竖弧终桩号")
            if end > points[-1][0]+1e-7 or end <= s0:
                raise DesignProfileError("竖弧范围超出实际纵断面", station=s0)
            arc = {"kind": "arc", "station_start": s0, "station_end": end,
                   "center_station": cs, "center_elevation": cz, "radius": radius,
                   "branch": 1 if z0 > float(cz) else -1}
            if abs(_at(arc, s0)[0]-z0) > 1e-6:
                raise DesignProfileError("竖弧起点与节点高程不一致", station=s0)
            elements.append(arc)
            end_z = _at(arc, end)[0]
            j=index+1
            while j < len(points) and points[j][0] <= end+1e-7:
                if abs(_at(arc,points[j][0])[0]-points[j][1]) > 1e-6:
                    raise DesignProfileError("真实竖弧与弧内/终点节点高程不一致",station=points[j][0])
                j+=1
            if j and abs(points[j-1][0]-end)<=1e-7:
                index=j-1
                continue
            if j<len(points):
                next_s,next_z,_=points[j]
                elements.append({"kind":"line","station_start":end,"station_end":next_s,
                                 "z_start":end_z,"slope":(next_z-end_z)/(next_s-end)})
                index=j
                continue
            index=len(points)-1
        else:
            elements.append({"kind": "line", "station_start": s0, "station_end": s1,
                             "z_start": z0, "slope": (z1-z0)/(s1-s0)})
            index+=1
    return elements


def normalize_design_profile(profile_or_asset, *, reference=None):
    """Normalize line/arc elements, DXF bulges, or saved longitudinal nodes."""
    source = _source(profile_or_asset)
    inherited = source.get("reference") if isinstance(source, dict) else None
    if isinstance(source, dict) and source.get("elements"):
        raw = source["elements"]
    elif isinstance(source, dict) and (source.get("vertices") or source.get("parts")):
        raw = _from_raw_polyline(source)
    elif isinstance(source, (list, tuple)):
        raw = _from_nodes(source)
    else:
        raise DesignProfileError("缺少真实设计纵断面", code="missing_design_profile")
    elements = [_canonical_element(row) for row in raw]
    if not elements:
        raise DesignProfileError("设计纵断面至少需要两个节点", code="missing_design_profile")
    for previous, current in zip(elements, elements[1:]):
        if abs(previous["station_end"]-current["station_start"]) > 1e-7:
            raise DesignProfileError("设计纵断面存在缺段或重叠", station=current["station_start"])
        if abs(_at(previous, previous["station_end"])[0]-_at(current, current["station_start"])[0]) > 1e-6:
            raise DesignProfileError("设计轴线高程跳跃，须补充连续过渡", code="profile_jump", station=current["station_start"])
    return DesignProfile({"schema_version": "1.0", "reference": reference or inherited or "inner_invert",
            "station_basis": "true_plan_arclength", "elements": elements,
            "station_start": elements[0]["station_start"], "station_end": elements[-1]["station_end"]})


def evaluate_profile(profile_or_asset, station, side="right"):
    """Return (absolute elevation, dz/ds), with explicit one-sided break values."""
    source=_source(profile_or_asset)
    profile = source if isinstance(source,DesignProfile) else normalize_design_profile(source)
    station = _number(station, "查询桩号")
    if side not in ("left", "right", "L", "R", "M"):
        raise DesignProfileError("断面侧别须为 left 或 right")
    if station < profile["station_start"]-1e-7 or station > profile["station_end"]+1e-7:
        raise DesignProfileError("设计纵断面未覆盖查询桩号，禁止外推", code="missing_design_profile", station=station)
    elements = profile["elements"]
    station = min(max(station, profile["station_start"]), profile["station_end"])
    index = min(bisect_right(profile.starts, station)-1, len(elements)-1)
    if side in ("left", "L") and index > 0 and abs(elements[index]["station_start"]-station) < 1e-8:
        index -= 1
    return _at(elements[index], station)


def profile_break_stations(profile_or_asset):
    profile = normalize_design_profile(profile_or_asset)
    return sorted({e[k] for e in profile["elements"] for k in ("station_start", "station_end")})


def clip_design_profile(profile_or_asset, station_start, station_end):
    profile = normalize_design_profile(profile_or_asset)
    start, end = _number(station_start, "起桩"), _number(station_end, "止桩")
    evaluate_profile(profile, start); evaluate_profile(profile, end)
    if end <= start:
        raise DesignProfileError("裁切范围必须递增")
    pieces = []
    for element in profile["elements"]:
        a, b = max(start, element["station_start"]), min(end, element["station_end"])
        if b > a:
            row = deepcopy(element)
            row.update(station_start=a, station_end=b)
            if row["kind"] == "line":
                row["z_start"] = _at(element, a)[0]
            pieces.append(row)
    return normalize_design_profile({"reference": profile["reference"], "elements": pieces})


def profile_spatial_length(profile_or_asset, station_start=None, station_end=None):
    profile = normalize_design_profile(profile_or_asset)
    if station_start is not None or station_end is not None:
        profile = clip_design_profile(profile, profile["station_start"] if station_start is None else station_start,
                                      profile["station_end"] if station_end is None else station_end)
    total = 0.
    for row in profile["elements"]:
        a, b = row["station_start"], row["station_end"]
        if row["kind"] == "line":
            total += (b-a)*math.hypot(1., row["slope"])
        else:
            total += row["radius"]*abs(math.asin((b-row["center_station"])/row["radius"])-
                                         math.asin((a-row["center_station"])/row["radius"]))
    return total


def prepare_pipe_layout(pipes, spacing=0.):
    """Place unequal pipes side by side; outer bottoms share one support datum."""
    values = [deepcopy(_dict(p)) for p in pipes]
    if not values:
        raise DesignProfileError("缺少施工外径及管道布置", code="missing_pipe_dimensions")
    for pipe in values:
        if pipe.get("outer_diameter") is None:
            raise DesignProfileError("缺少施工外径", code="missing_pipe_dimensions")
        pipe["outer_diameter"] = _number(pipe.get("outer_diameter"), "施工外径")
        if pipe["outer_diameter"] <= 0:
            raise DesignProfileError("施工外径必须为正")
        for field in ("wall_thickness", "lining_thickness"):
            if pipe.get(field) is not None and _number(pipe[field], field) < 0:
                raise DesignProfileError("管壁及内衬厚度不能为负")
        if pipe.get("inner_diameter") is not None and _number(pipe["inner_diameter"], "水力内径") > pipe["outer_diameter"]:
            raise DesignProfileError("水力内径大于施工外径")
        if all(pipe.get(k) is not None for k in ("inner_diameter", "wall_thickness")):
            expected = float(pipe["inner_diameter"])+2*float(pipe["wall_thickness"])+2*float(pipe.get("lining_thickness") or 0.)
            if abs(expected-pipe["outer_diameter"]) > 1e-6:
                raise DesignProfileError("管道内径、外径、壁厚及内衬尺寸关系不一致")
    gaps = list(spacing) if isinstance(spacing, (list, tuple)) else [spacing]*(len(values)-1)
    if len(gaps) != len(values)-1 or any(_number(g, "管间净距") < 0 for g in gaps):
        raise DesignProfileError("管间净距须为非负数或逐相邻管净距列表")
    if any(p.get("offset") is not None for p in values):
        if not all(p.get("offset") is not None for p in values):
            raise DesignProfileError("逐管偏距须完整提供")
        for p in values:
            p["offset"] = _number(p["offset"], "管轴横向偏距")
        for a, b in zip(values, values[1:]):
            if b["offset"]-a["offset"] < (a["outer_diameter"]+b["outer_diameter"])/2-1e-8:
                raise DesignProfileError("并排管道外包相互重叠")
    else:
        width = sum(p["outer_diameter"] for p in values)+sum(float(g) for g in gaps)
        edge = -width/2
        for i, pipe in enumerate(values):
            pipe["offset"] = edge+pipe["outer_diameter"]/2
            edge += pipe["outer_diameter"]+(float(gaps[i]) if i < len(gaps) else 0.)
    return values


def _arc_terrain_breaks(tin, element, pipe):
    """Exact triangle-edge intersections of one circular pipe footprint.

    Also return a bound on |d² ground/ds²| within each original planar face.
    The bound permits a conservative linear design preview between samples.
    """
    import numpy as np
    direction=math.copysign(1.,element["sweep_angle"])
    radius=element["radius"]+direction*pipe["offset"]
    if abs(radius)<1e-7 or abs(element["sweep_angle"])>2*math.pi+1e-8:
        raise DesignProfileError("多管横向布置在平面圆弧出现不可解析回折，请调整真实布置",code="singular_pipe_footprint")
    center=np.asarray(element["center_xy"],dtype=float)
    xyz=np.asarray(tin.points,dtype=float)
    faces=np.asarray(tin.triangles,dtype=np.int64)
    tri=xyz[faces]
    low,high=tri[:,:,:2].min(axis=1),tri[:,:,:2].max(axis=1)
    r=abs(radius)
    mask=((high[:,0]>=center[0]-r)&(low[:,0]<=center[0]+r)&
          (high[:,1]>=center[1]-r)&(low[:,1]<=center[1]+r))
    local=faces[mask]
    if not len(local): return [],0.
    edge_ids=np.unique(np.sort(np.vstack([local[:,[0,1]],local[:,[1,2]],local[:,[2,0]]]),axis=1),axis=0)
    a=xyz[edge_ids[:,0],:2]-center
    vector=xyz[edge_ids[:,1],:2]-xyz[edge_ids[:,0],:2]
    aa=np.sum(vector*vector,axis=1)
    bb=2*np.sum(a*vector,axis=1)
    cc=np.sum(a*a,axis=1)-r*r
    disc=bb*bb-4*aa*cc
    valid=(aa>1e-16)&(disc>=-1e-8)
    roots=np.sqrt(np.maximum(0.,disc[valid]))
    base=a[valid];vec=vector[valid];den=2*aa[valid];bterm=bb[valid]
    stations=[]
    for t in ((-bterm-roots)/den,(-bterm+roots)/den):
        inside=(t>=-1e-9)&(t<=1+1e-9)
        xy=base[inside]+t[inside,None]*vec[inside]
        angles=np.arctan2(xy[:,1],xy[:,0])-(math.pi if radius<0 else 0.)
        delta=(direction*(angles-element["start_angle"]))%(2*math.pi)
        delta=np.where(np.abs(delta-2*math.pi)<1e-8,0.,delta)
        stations.extend(element["station_start"]+element["radius"]*float(d)
                        for d in delta if d<=abs(element["sweep_angle"])+1e-8)
    # Face gradients bound the second derivative along this circular path.
    t=xyz[local]
    dx1,dy1=t[:,1,0]-t[:,0,0],t[:,1,1]-t[:,0,1]
    dx2,dy2=t[:,2,0]-t[:,0,0],t[:,2,1]-t[:,0,1]
    dz1,dz2=t[:,1,2]-t[:,0,2],t[:,2,2]-t[:,0,2]
    determinant=dx1*dy2-dx2*dy1
    valid=np.abs(determinant)>1e-12
    gx=(dz1[valid]*dy2[valid]-dz2[valid]*dy1[valid])/determinant[valid]
    gy=(dx1[valid]*dz2[valid]-dx2[valid]*dz1[valid])/determinant[valid]
    bound=float(np.max(np.hypot(gx,gy),initial=0.))*r/element["radius"]**2
    return stations,bound


def _check_cover_cancelled(cancelled):
    if cancelled and cancelled():
        raise InterruptedError("已取消生成覆土纵断面")


def generate_cover_profile(tin, alignment, pipes, *, cover_depth=3., cover_segments=None,
                           sample_step=20., spacing=0., max_abs_slope=20., sampling_policy="exact", cancelled=None):
    """Generate a conservative sampled preview, checking every pipe's own ground.

    The result must be reviewed/confirmed before calculation. A depth change
    without a continuous transition is returned as a diagnostic, never joined
    into a fabricated vertical pipe. Missing terrain is never extrapolated.
    """
    _check_cover_cancelled(cancelled)
    if sampling_policy == "engineering":
        from .engineering_cover_profile import generate_engineering_cover_profile
        return generate_engineering_cover_profile(tin, alignment, pipes, cover_depth=cover_depth,
            cover_segments=cover_segments, sample_step=sample_step, spacing=spacing,max_abs_slope=max_abs_slope,
            cancelled=cancelled)
    if sampling_policy != "exact":
        raise DesignProfileError("未知覆土纵断面生成方式")
    import numpy as np
    from ..core.tin_interpolator import TINInterpolator
    from .workbench_identity import COMPUTATION_CONTRACT
    layout = prepare_pipe_layout(pipes, spacing)
    depth = _number(cover_depth, "管顶埋深")
    step = _number(sample_step, "预览间距")
    if depth < 0 or step <= 0:
        raise DesignProfileError("埋深不得为负，预览间距必须为正")
    start, end = alignment.start_station, alignment.end_station
    segments = sorted(deepcopy(cover_segments or [{"station_start": start, "station_end": end, "cover_depth": depth}]), key=lambda p: p["station_start"])
    cursor, issues = start, []
    for i, row in enumerate(segments):
        a, b, d = (_number(row.get(k), k) for k in ("station_start", "station_end", "cover_depth"))
        if abs(a-cursor) > 1e-7 or b <= a or b > end+1e-7 or d < 0:
            raise DesignProfileError("分段埋深须按桩号完整覆盖路线且不重叠", station=a)
        if i and abs(d-float(segments[i-1]["cover_depth"])) > 1e-8:
            issues.append({"code": "cover_depth_jump", "severity": "error", "station": a,
                           "message": "分段埋深跳变；请提供连续控制高程或实际过渡轴线"})
        cursor = b
    if abs(cursor-end) > 1e-7:
        raise DesignProfileError("分段埋深未覆盖路线末端", station=cursor)
    if issues:
        return {"design_profile": None, "pipes": layout, "samples": [], "diagnostics": issues,
                "confirmed": False, "valid": False, "source": "terrain_and_user_cover_depth"}
    interp=TINInterpolator(tin)
    extras=[r[k] for r in segments for k in ("station_start", "station_end")]
    # A straight pipe footprint has an exact piecewise-linear terrain profile.
    # Retain every real TIN edge break, including a small valley or hole that
    # would otherwise lie between coarse preview stations.
    arc_bounds=[]
    for element in alignment.elements:
        _check_cover_cancelled(cancelled)
        if element["kind"]=="arc":
            bounds=[]
            for pipe in layout:
                breaks,bound=_arc_terrain_breaks(tin,element,pipe)
                extras.extend(breaks);bounds.append(bound)
            arc_bounds.append((element,bounds))
            continue
        theta=element["tangent_angle"]
        tangent=(math.cos(theta),math.sin(theta))
        for pipe in layout:
            xy=(element["start_xy"][0]+pipe["offset"]*math.sin(theta),
                element["start_xy"][1]-pipe["offset"]*math.cos(theta))
            ground_line=interp.section_line(xy,tangent,0.,element["length"])
            extras.extend(element["station_start"]+float(p[0]) for p in ground_line)
            # Midpoints ensure a missing interval cannot be hidden by two valid
            # boundary points on opposite sides of a terrain hole.
            extras.extend(element["station_start"]+(float(a[0])+float(b[0]))/2
                          for a,b in zip(ground_line,ground_line[1:]))
    stations = alignment.sample_stations(step, extras)
    merged=[]
    for station in stations:
        if not merged or station-merged[-1]>1e-7: merged.append(station)
    if abs(merged[-1]-end)<1e-7: merged[-1]=end
    stations=merged
    if arc_bounds:
        # Split each actual face interval before coverage checks; a narrow hole
        # bounded by two valid edges cannot become a valid sampled preview.
        mids=[(a+b)/2 for a,b in zip(stations,stations[1:])]
        stations=alignment.sample_stations(step,[*stations,*mids])
    coords = []
    for s in stations:
        _check_cover_cancelled(cancelled)
        x, y = alignment.get_xy_at_station(s)
        theta = alignment.get_tangent_angle_at_station(s)
        coords.extend([[x+pipe["offset"]*math.sin(theta), y-pipe["offset"]*math.cos(theta)] for pipe in layout])
    ground = interp.query_batch(np.asarray(coords)).reshape(len(stations), len(layout))
    if not np.isfinite(ground).all():
        missing = np.argwhere(~np.isfinite(ground))
        raise DesignProfileError(f"桩号 {stations[missing[0][0]]:.3f} 第 {missing[0][1]+1} 管上方缺测地形", code="missing_terrain", station=stations[missing[0][0]])
    ds = np.diff(np.asarray(stations))
    diameters = np.asarray([p["outer_diameter"] for p in layout])
    depths = np.asarray([next(float(r["cover_depth"]) for r in segments if r["station_start"]-1e-7 <= s <= r["station_end"]+1e-7) for s in stations])
    safety=np.zeros_like(ground)
    for element,bounds in arc_bounds:
        for i,(a,b) in enumerate(zip(stations,stations[1:])):
            if element["station_start"]-1e-7<=a and b<=element["station_end"]+1e-7:
                error=np.asarray(bounds)*(b-a)**2/8
                safety[i]=np.maximum(safety[i],error);safety[i+1]=np.maximum(safety[i+1],error)
    bottom = np.min(ground-safety-depths[:,None]-diameters, axis=1)
    element_starts=[e["station_start"] for e in alignment.elements]
    def one_sided_element(station,side):
        j=max(0,min(len(element_starts)-1,bisect_right(element_starts,station)-1))
        if side=="left" and j>0 and station==element_starts[j]:j-=1
        return alignment.elements[j]
    def one_sided_curvature(station,side):
        element=one_sided_element(station,side)
        return math.copysign(1/element["radius"],element["sweep_angle"]) if element["kind"]=="arc" else 0.
    def footprint_xy(station,offset,element):
        if element["kind"]=="line":
            theta=element["tangent_angle"];distance=station-element["station_start"]
            x=element["start_xy"][0]+distance*math.cos(theta)
            y=element["start_xy"][1]+distance*math.sin(theta)
        else:
            sign=math.copysign(1.,element["sweep_angle"])
            angle=element["start_angle"]+sign*(station-element["station_start"])/element["radius"]
            x=element["center_xy"][0]+element["radius"]*math.cos(angle)
            y=element["center_xy"][1]+element["radius"]*math.sin(angle)
            theta=angle+sign*math.pi/2
        return [x+offset*math.sin(theta),y-offset*math.cos(theta)]
    def real_envelopes(slopes):
        from .finite_pipe_sections import pipe_top_envelope
        heights=np.empty((2,*ground.shape));offsets=np.empty_like(heights);coords=[]
        # Each side is a real one-sided profile/plan limit. A maximum height
        # from one side must never be paired with the other side's ground XY.
        for side_index,side in enumerate(("left","right")):
            for i,s in enumerate(stations):
                _check_cover_cancelled(cancelled)
                slope=slopes[max(0,i-1)] if side=="left" else slopes[min(len(slopes)-1,i)]
                element=one_sided_element(s,side);k=one_sided_curvature(s,side)
                for j,p in enumerate(layout):
                    heights[side_index,i,j],offsets[side_index,i,j]=pipe_top_envelope(p["outer_diameter"]/2,p["offset"],k,slope)
                    coords.append(footprint_xy(s,offsets[side_index,i,j],element))
        actual_ground=interp.query_batch(np.asarray(coords)).reshape(heights.shape)
        if not np.isfinite(actual_ground).all():
            side_index,i,j=np.argwhere(~np.isfinite(actual_ground))[0]
            raise DesignProfileError(f"桩号 {stations[i]:.3f} 第 {j+1} 管真实管顶上方缺测地形",code="missing_terrain",station=stations[i])
        return heights,offsets,actual_ground
    def certify_curved_cells(slopes):
        """Check actual top circles at every original TIN edge and face gap.

        On each design line/constant-curvature cell the top footprint is an
        exact offset circle. Between its TIN-edge events, the original planar
        face gradient bounds interpolation error. No nominal-axis terrain is
        substituted for that footprint, including at holes.
        """
        from .finite_pipe_sections import pipe_top_envelope
        from .network_section_calculator import _arc_terrain_events
        from ..core.terrain_sections import TerrainSectionIndex
        if interp._section_index is None:interp._section_index=TerrainSectionIndex(tin)
        reductions=np.zeros(len(stations));checked=0
        for i,(a,b) in enumerate(zip(stations,stations[1:])):
            _check_cover_cancelled(cancelled)
            element=one_sided_element((a+b)/2,"right")
            if element["kind"]!="arc":continue
            sign=math.copysign(1.,element["sweep_angle"]);k=sign/element["radius"]
            bounds=next(values for e,values in arc_bounds if e is element)
            for j,p in enumerate(layout):
                height,offset=pipe_top_envelope(p["outer_diameter"]/2,p["offset"],k,slopes[i])
                radius=element["radius"]+sign*offset
                sub={"kind":"arc","station_start":0.,"station_end":(b-a)*radius/element["radius"],
                     "radius":radius,"center_xy":element["center_xy"],
                     "start_angle":element["start_angle"]+sign*(a-element["station_start"])/element["radius"],
                     "sweep_angle":sign*(b-a)/element["radius"]}
                events=[a,b]
                events.extend(a+s*element["radius"]/radius for s in _arc_terrain_events(interp._section_index,sub)
                              if 0.<s<sub["station_end"])
                events=sorted(set(events))
                mids=[(x+y)/2 for x,y in zip(events,events[1:])]
                values=interp.query_batch(np.asarray([footprint_xy(s,offset,element) for s in [*events,*mids]]))
                if not np.isfinite(values).all():
                    locations=[*events,*mids];s=locations[int(np.flatnonzero(~np.isfinite(values))[0])]
                    raise DesignProfileError(f"桩号 {s:.3f} 第 {j+1} 管真实管顶路径穿过缺测地形",code="missing_terrain",station=s)
                top=bottom[i]+slopes[i]*(np.asarray(events)-a)+2*height
                covers=values[:len(events)]-top
                for n,(x,y) in enumerate(zip(events,events[1:])):
                    # The actual top radius is inward from the nominal pipe
                    # radius. Its original-face curvature bound is therefore
                    # no larger than the already retained nominal bound.
                    lower=min(covers[n:n+2])-bounds[j]*(y-x)**2/8
                    if lower<depths[i]-1e-7:
                        reduction=depths[i]-lower+1e-8
                        reductions[i]=max(reductions[i],reduction)
                        reductions[i+1]=max(reductions[i+1],reduction)
                    checked+=1
        return reductions,checked
    # Both neighboring one-sided slopes constrain the vertical pipe截形.
    for _ in range(100):
        _check_cover_cancelled(cancelled)
        slopes = np.diff(bottom)/ds
        if np.max(np.abs(slopes)) > max_abs_slope:
            raise DesignProfileError("埋深生成轴线出现近竖直过渡，请调整连续控制高程", code="near_vertical_profile")
        factors = np.hypot(1., slopes)
        factors = np.maximum(np.r_[factors[0], factors], np.r_[factors, factors[-1]])
        if arc_bounds:
            heights,top_offsets,top_ground=real_envelopes(slopes)
            limits=top_ground-safety[None,:,:]-depths[None,:,None]-2*heights
            # A common vertical translation preserves every preview line's
            # grade and therefore its exact helix footprint. Repeated local
            # lowering would create artificial grade spikes at closely spaced
            # terrain events, which then change that footprint again.
            drop=max(0.,float(np.max(bottom-np.min(limits,axis=(0,2)))))
            revised=bottom-drop
        else:
            spans=factors[:,None]*diameters
            revised=np.minimum(bottom,np.min(ground-safety-depths[:,None]-spans,axis=1))
        if np.max(np.abs(revised-bottom)) < 1e-7:
            bottom = revised
            if arc_bounds:
                reductions,checked=certify_curved_cells(np.diff(bottom)/ds)
                if np.max(reductions)>0:
                    bottom-=float(np.max(reductions))
                    continue
            break
        bottom = revised
    else:
        raise DesignProfileError("埋深轴线与斜管截形未收敛，请调整控制高程", code="cover_profile_not_converged")
    profile = normalize_design_profile([{"station": s, "elevation": float(z)} for s,z in zip(stations,bottom)], reference="common_outer_bottom")
    if arc_bounds:heights,top_offsets,top_ground=real_envelopes(np.diff(bottom)/ds)
    samples = []
    for i,s in enumerate(stations):
        _check_cover_cancelled(cancelled)
        _, slope_l = evaluate_profile(profile, s, "left")
        _, slope_r = evaluate_profile(profile, s, "right")
        factor = max(math.hypot(1., slope_l), math.hypot(1., slope_r))
        side_index=0 if s==end else 1
        hs=heights[side_index,i] if arc_bounds else [p["outer_diameter"]*factor/2 for p in layout]
        gs=top_ground[side_index,i] if arc_bounds else ground[i]
        pipe_rows=[]
        for j,p in enumerate(layout):
            row={"pipe_index":j,"offset":p["offset"],"ground_elevation":float(gs[j]),
                 "outer_bottom":float(bottom[i]),"axis_elevation":float(bottom[i]+hs[j]),
                 "outer_top":float(bottom[i]+2*hs[j]),"actual_cover":float(gs[j]-bottom[i]-2*hs[j])}
            if arc_bounds:
                row.update(outer_top_offset=float(top_offsets[side_index,i,j]),
                           ground_xy=footprint_xy(s,top_offsets[side_index,i,j],one_sided_element(s,"left" if side_index==0 else "right")),
                           side="left" if side_index==0 else "right")
                row["side_limits"]=[{"side":side,"outer_top_offset":float(top_offsets[n,i,j]),
                    "ground_xy":footprint_xy(s,top_offsets[n,i,j],one_sided_element(s,side)),
                    "ground_elevation":float(top_ground[n,i,j]),"axis_elevation":float(bottom[i]+heights[n,i,j]),
                    "outer_bottom":float(bottom[i]),"outer_top":float(bottom[i]+2*heights[n,i,j]),
                    "actual_cover":float(top_ground[n,i,j]-bottom[i]-2*heights[n,i,j])}
                    for n,side in enumerate(("left","right"))]
                row["minimum_actual_cover"]=min(v["actual_cover"] for v in row["side_limits"])
            pipe_rows.append(row)
        control = min(pipe_rows, key=lambda p:p["actual_cover"])
        samples.append({"station": s, "common_outer_bottom": float(bottom[i]), "requested_cover": float(depths[i]),
                        "controlling_pipe_index": control["pipe_index"], "pipes": pipe_rows,
                        "curved_terrain_interpolation_allowance":safety[i].tolist()})
    identity = hashlib.sha256(json.dumps({"profile": profile, "pipes": layout, "depths": segments,"calculation_contract":COMPUTATION_CONTRACT}, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return {"design_profile": profile, "profile_points": [{"station": s, "elevation": float(z)} for s,z in zip(stations,bottom)],
            "pipes": layout, "samples": samples, "diagnostics": [{"code": "sampled_cover_preview", "severity": "info",
            "message": "地形与用户埋深生成的待确认轴线；显示采样点逐管实际覆土，未替换原水力轴线"}],
            "confirmed": False, "valid": True, "source": "terrain_and_user_cover_depth", "preview_sha256": identity,"calculation_contract":COMPUTATION_CONTRACT}


PIPE_AXIS_CONTROLS = ("burial_mode", "axis_confirmed", "cover_depth", "cover_segments")


def sync_bound_axis_controls(asset):
    """Keep legacy section overrides in step with the adopted profile source."""
    construction = asset.get("construction") or {}
    binding = asset.get("section_scheme_binding") or {}
    bound = {**(binding.get("resolved_fields") or {}), **(binding.get("overrides") or {})}
    overrides = asset.get("drawing_user_overrides") or {}
    for key in PIPE_AXIS_CONTROLS:
        path = "construction." + key
        value = construction.get(key)
        if (path in bound and value != bound[path]) or (path in overrides and value != overrides[path]):
            asset.setdefault("drawing_user_overrides", {})[path] = deepcopy(value)
            asset.setdefault("parameter_sources", {})[path] = "用户确认的管轴高程来源"


def apply_cover_preview(asset, preview, *, confirmed=False):
    """Return a new calculation asset only after the user confirms its preview."""
    if not confirmed:
        raise DesignProfileError("请先确认生成轴线预览，不能直接用于正式算量",code="axis_confirmation_required")
    if not preview.get("valid") or not preview.get("design_profile"):
        raise DesignProfileError("生成轴线尚有未解决问题，不能应用",code="invalid_axis_preview")
    from .workbench_identity import COMPUTATION_CONTRACT
    if preview.get("calculation_contract")!=COMPUTATION_CONTRACT:
        raise DesignProfileError("生成轴线来自旧计算模型，请按当前真实管截形重新预览后确认",code="axis_preview_model_changed")
    result=deepcopy(asset)
    if result.get("design_profile") and not result.get("original_design_profile"):
        result["original_design_profile"]=deepcopy(result["design_profile"])
    reference=preview["design_profile"].get("reference","common_outer_bottom")
    result["design_profile"]=normalize_design_profile(preview["design_profile"],reference=reference)
    result["profile_points"]=deepcopy(preview["profile_points"])
    result.setdefault("section",{})["pipes"]=deepcopy(preview["pipes"])
    result["section"]["pipe_count"]=len(preview["pipes"])
    result.setdefault("alignment",{}).update(profile_points=deepcopy(result["profile_points"]),elevation_reference=reference)
    construction = result.setdefault("construction", {})
    construction.update(burial_mode="cover_depth", axis_confirmed=True)
    sync_bound_axis_controls(result)
    result["axis_source"]="terrain_and_user_cover_depth"
    result["axis_preview_sha256"]=preview["preview_sha256"]
    result["axis_cover_samples"]=deepcopy(preview["samples"])
    result["missing_fields"]=[f for f in result.get("missing_fields",[]) if f!="design_profile"]
    return result


def clip_alignment(alignment, station_start, station_end):
    """Crop a true plan alignment without changing source chainage or arcs."""
    from ..adapters.workbench_sources import clip_plan_alignment
    return clip_plan_alignment(alignment,station_start,station_end)


def _pipe_profile_element(asset,station,side):
    source=_source(asset)
    profile=source if isinstance(source,DesignProfile) else normalize_design_profile(source)
    station=_number(station,"管道查询桩号")
    # Reuse the same coverage and side validation as elevation queries.
    evaluate_profile(profile,station,side)
    index=min(bisect_right(profile.starts,station)-1,len(profile["elements"])-1)
    if side in ("left","L") and index>0 and abs(profile.starts[index]-station)<1e-8:index-=1
    return profile,profile["elements"][index]


def _first_pipe_inner_radius(asset,first_outer_radius,explicit=None):
    """Hydraulic clear radius includes the actual declared internal lining."""
    if explicit is not None:inner=_number(explicit,"首管真实净内半径")
    else:
        from .pipe_dimensions import effective_pipe_section
        section=effective_pipe_section(asset.get("section",{})) if isinstance(asset,dict) else {}
        entries=section.get("pipes") or []
        first=entries[0] if entries else section
        diameter=first.get("construction_inner_diameter_m", first.get("inner_diameter",section.get("construction_inner_diameter_m", section.get("inner_diameter"))))
        if diameter is None and first.get("earthwork_envelope_only", section.get("earthwork_envelope_only")):
            diameter=first.get("nominal_diameter_m",section.get("nominal_diameter_m"))
        net_radius=first.get("inner_radius",section.get("inner_radius"))
        wall=first.get("wall_thickness",section.get("wall_thickness"))
        lining=first.get("lining_thickness",section.get("lining_thickness",0.))
        if diameter is not None:inner=_number(diameter,"首管真实净内径")/2
        elif net_radius is not None:inner=_number(net_radius,"首管真实净内半径")
        elif wall is not None:
            inner=first_outer_radius-_number(wall,"首管壁厚")-_number(lining,"首管内衬厚度")
        else:raise DesignProfileError("内底高程换算须有首管真实净内径，或明确的施工外径、壁厚及内衬",code="missing_pipe_inner_diameter")
        if wall is not None:
            wall_value,lining_value=_number(wall,"首管壁厚"),_number(lining,"首管内衬厚度")
            if min(wall_value,lining_value)<0:raise DesignProfileError("首管壁厚及内衬不能为负",code="invalid_pipe_dimensions")
            thickness=wall_value+lining_value
            if abs(inner+thickness-first_outer_radius)>1e-6:
                raise DesignProfileError("首管净内径、壁厚、内衬与施工外径不一致",code="inconsistent_pipe_dimensions")
    if inner<=0 or inner>first_outer_radius+1e-7:
        raise DesignProfileError("首管真实净内半径须为正且不大于施工外半径",code="invalid_pipe_inner_diameter")
    return inner


def pipe_profile_circle(asset,pipe_radius,first_radius,station,side="right",*,first_inner_radius=None):
    """Return the exact concentric vertical-arc datum for this pipe, or None.

    Positive ``q`` is the upward pipe-normal offset. Thus a material circle of
    radius r has meridian radius ``axis_radius + branch*q`` and its outer
    bottom is the common circle ``axis_radius - branch*r``.
    """
    radius=_number(pipe_radius,"该管施工外半径")
    first=_number(first_radius,"首根管施工外半径")
    if min(radius,first)<=0:raise DesignProfileError("管道施工外半径须为正")
    profile,element=_pipe_profile_element(asset,station,side)
    if element["kind"]!="arc":return None
    reference=profile["reference"]
    branch=element["branch"]
    if reference=="common_outer_bottom":
        support=element["radius"]
        axis=support+branch*radius
    elif reference=="pipe_axis":
        support=element["radius"]-branch*first
        axis=element["radius"]+branch*(radius-first)
    elif reference=="inner_invert":
        inner=_first_pipe_inner_radius(asset,first,first_inner_radius)
        support=element["radius"]+branch*(inner-first)
        axis=element["radius"]+branch*(inner+radius-first)
    else:
        raise DesignProfileError("真实管道竖曲线须明确首管管轴、净内底或共同外底基准",code="invalid_pipe_axis_reference")
    if min(axis,support)<=0:
        raise DesignProfileError("管径与竖曲线半径不相容",code="singular_pipe_profile",station=station)
    return {"center_station":element["center_station"],"center_elevation":element["center_elevation"],
            "radius":axis,"support_radius":support,"branch":branch,"station_start":element["station_start"],
            "station_end":element["station_end"],"reference":reference}


def evaluate_pipe_axis(asset,pipe_radius,first_radius,station,side="right",*,first_inner_radius=None):
    """Actual unequal-pipe axis (z,dz/ds), preserving a common outer bottom."""
    radius=_number(pipe_radius,"该管施工外半径")
    first=_number(first_radius,"首根管施工外半径")
    if min(radius,first)<=0:raise DesignProfileError("管道施工外半径须为正")
    profile,element=_pipe_profile_element(asset,station,side)
    circle=pipe_profile_circle(asset,radius,first,station,side,first_inner_radius=first_inner_radius)
    if circle is not None:
        return _at({"kind":"arc",**circle},_number(station,"管道查询桩号"))
    z,slope=evaluate_profile(profile,station,side)
    if profile["reference"]=="common_outer_bottom":return z+radius*math.hypot(1.,slope),slope
    if profile["reference"]=="pipe_axis":return z+(radius-first)*math.hypot(1.,slope),slope
    if profile["reference"]=="inner_invert":
        inner=_first_pipe_inner_radius(asset,first,first_inner_radius)
        return z+(inner+radius-first)*math.hypot(1.,slope),slope
    raise DesignProfileError("管道须明确首管管轴、净内底或共同外底基准",code="invalid_pipe_axis_reference")


def pipe_axis_profile(asset,pipe_radius,first_radius,*,first_inner_radius=None):
    """Return a read-only derived actual axis profile, preserving every true arc.

    The original design profile stays unchanged. profile_spatial_length of the
    returned profile is its station/elevation length; a laterally offset plan
    curve still requires its actual plan metric when measuring the full 3D axis.
    """
    source=normalize_design_profile(asset);elements=[]
    for row in source["elements"]:
        if row["kind"]=="line":
            z,slope=evaluate_pipe_axis(asset,pipe_radius,first_radius,row["station_start"],first_inner_radius=first_inner_radius)
            elements.append({"kind":"line","station_start":row["station_start"],"station_end":row["station_end"],"z_start":z,"slope":slope})
        else:
            s=(row["station_start"]+row["station_end"])/2
            circle=pipe_profile_circle(asset,pipe_radius,first_radius,s,first_inner_radius=first_inner_radius)
            elements.append({"kind":"arc","station_start":row["station_start"],"station_end":row["station_end"],
                             **{key:circle[key] for key in ("center_station","center_elevation","radius","branch")}})
    profile=normalize_design_profile({"reference":"pipe_axis","elements":elements})
    profile["source_reference"]=source["reference"]
    profile["derivation"]="normal_offset_of_actual_design_profile"
    return profile
