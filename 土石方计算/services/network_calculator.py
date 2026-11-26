"""全线施工实体算量：解析线形扫掠、原 TIN 土体、全局三维布尔去重。

圆弧只通过解析线形查询坐标；三角面离散以外侧弦高和分项体积加密控制。
此模块不从水力尺寸补造设计参数，也不将未去重逐段量称为全线量。
"""
from __future__ import annotations

from .construction_rules import effective_construction, normalize_construction_inputs

from bisect import bisect_right
from copy import deepcopy
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
from functools import lru_cache
import math
import time

import numpy as np
import shapely
from shapely.geometry import Polygon, MultiPolygon, LineString, Point, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from ..core.tin_interpolator import TINInterpolator
from ..core.cross_section import CrossSectionCalculator
from .construction_templates import build_construction_section, _section_outer
from .contracts import ConstructionInputError


class NetworkCalculationError(ConstructionInputError):
    def __init__(self, message, *, code="invalid_network", diagnostics=None):
        super().__init__(message)
        self.code = code
        self.diagnostics = diagnostics or []


@dataclass
class NetworkCalculationResult:
    quantities: dict
    assets: list[dict]
    convergence_history: list[dict]
    validation: dict
    origin: tuple[float, float, float]
    solids: dict = field(default_factory=dict, repr=False)
    diagnostics: list = field(default_factory=list)
    test_only: bool = False
    terrain_metadata: dict = field(default_factory=dict)
    input_metadata: dict = field(default_factory=dict)

    @property
    def converged(self):
        return self.validation["converged"]

    def to_dict(self):
        return {"schema": "network_1.0", "kind": "network", "status": "READY" if self.converged else "FAILED",
                "converged": self.converged, "test_only": self.test_only, "units": "m",
                **self.quantities, "quantities": self.quantities.copy(), "assets": deepcopy(self.assets),
                "segments": deepcopy(self.assets), "convergence_history": deepcopy(self.convergence_history),
                "rows": deepcopy(self.assets),
                "validation": deepcopy(self.validation), "local_origin": list(self.origin),
                "diagnostics": deepcopy(self.diagnostics), "terrain_metadata": deepcopy(self.terrain_metadata),
                "input_metadata": deepcopy(self.input_metadata),
                "integration_method": "original_TIN_solid_and_analytic_route_sweeps_Manifold64_global_boolean",
                "allocation_policy": "role_station_order_first_owner"}


def _backend():
    try:
        import manifold3d as m
    except ImportError as exc:
        raise NetworkCalculationError("全线实体算量缺少 manifold3d>=3.5.4,<4", code="missing_backend") from exc
    return m


def _cancel(cancelled):
    if cancelled is not None and cancelled():
        raise NetworkCalculationError("已取消全线计算，未发布部分成果", code="cancelled")


def _checked(solid, label):
    m = _backend()
    if solid.status() != m.Error.NoError:
        raise NetworkCalculationError(f"{label}实体无效：{solid.status()}", code="invalid_solid")
    volume = solid.volume()
    if not math.isfinite(volume) or volume < -1e-7:
        raise NetworkCalculationError(f"{label}实体体积无效：{volume}", code="invalid_solid")
    return solid


def _union(solids):
    m = _backend()
    values = [s for s in solids if not s.is_empty()]
    return _checked(m.Manifold.batch_boolean(values, m.OpType.Add), "并集") if values else m.Manifold()


def _mesh(vertices, triangles, label):
    """输入必须已经封闭；仅合并完全相同顶点，不修洞、不补自交。"""
    m = _backend()
    vertices = np.ascontiguousarray(vertices, dtype=np.float64)
    triangles = np.asarray(triangles, dtype=np.int64)
    if not len(triangles):
        return m.Manifold()
    unique, inverse = np.unique(vertices, axis=0, return_inverse=True)
    triangles = inverse[triangles]
    triangles = triangles[np.asarray([len(set(t)) == 3 for t in triangles])]
    # 每个小单元已沿曲率奇异偏距拆开，允许统一翻转其外向。
    # 极短事件间单元的厚度可远小于其全线局部坐标；用自身重心判方向并建体，
    # 避免大坐标四面体项消减而误翻转。所有真实事件保留，不按桩号舍入删段。
    center = unique.mean(axis=0)
    centered = unique-center
    p = centered[triangles]
    signed = float(np.einsum("ij,ij->i", p[:, 0], np.cross(p[:, 1], p[:, 2])).sum()/6)
    if signed < 0:
        triangles = triangles[:, [0, 2, 1]]
    return _checked(m.Manifold(m.Mesh64(np.ascontiguousarray(centered),
                                       np.ascontiguousarray(triangles, dtype=np.uint64))).translate(center), label)


def _terrain_solids(tin, base, top, origin):
    """沿原三角片封底；孔洞和分离测区保留原边界，不重新三角剖分。"""
    points = np.asarray(tin.points, dtype=float)-origin
    triangles = np.asarray(tin.triangles, dtype=np.int64).copy()
    if (points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all()
            or triangles.ndim != 2 or triangles.shape[1] != 3 or not len(triangles)
            or np.any(triangles < 0) or np.any(triangles >= len(points))):
        raise NetworkCalculationError("原TIN顶点或三角片无效", code="invalid_terrain")
    used = np.unique(triangles)
    remap = np.full(len(points), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    points, triangles = points[used], remap[triangles]
    corners = points[triangles]
    cross = np.cross(corners[:, 1]-corners[:, 0], corners[:, 2]-corners[:, 0])[:, 2]
    if np.any(np.abs(cross) < 1e-12):
        raise NetworkCalculationError("原TIN存在零平面面积三角片", code="invalid_terrain")
    triangles[cross < 0] = triangles[cross < 0][:, [0, 2, 1]]
    edges = {}
    for tri in triangles:
        for a, b in zip(tri, np.roll(tri, -1)):
            key = (min(a, b), max(a, b))
            edges.setdefault(key, []).append((int(a), int(b)))
    if any(len(group) > 2 or (len(group) == 2 and group[0] != group[1][::-1]) for group in edges.values()):
        raise NetworkCalculationError("原TIN边拓扑非流形或覆盖重复", code="invalid_terrain")
    boundary = [group[0] for group in edges.values() if len(group) == 1]
    n = len(points)
    floor = points.copy(); floor[:, 2] = base-origin[2]
    faces = [*triangles.tolist(), *(triangles[:, [0, 2, 1]]+n).tolist()]
    for a, b in boundary:
        faces.extend([[a, a+n, b+n], [a, b+n, b]])
    soil = _mesh(np.vstack([points, floor]), faces, "原TIN土体")
    ceiling = points.copy(); ceiling[:, 2] = top-origin[2]
    domain = _mesh(np.vstack([ceiling, floor]), faces, "原TIN有效域柱体")
    return soil, domain


def _profile(asset, network):
    values = asset.get("profile_points") or network.get("profile_points")
    if not values or len(values) < 2:
        raise NetworkCalculationError(f"{asset.get('name')}缺少明确逐桩纵断面", code="missing_profile")
    values = [(float(p["station"]), float(p["elevation"])) for p in values]
    if any(not math.isfinite(v) for p in values for v in p) or any(b[0] <= a[0] for a, b in zip(values, values[1:])):
        raise NetworkCalculationError("纵断面桩号须递增且高程有限", code="missing_profile")
    start, end = float(asset["station_start"]), float(asset["station_end"])
    if values[0][0] > start+1e-8 or values[-1][0] < end-1e-8:
        raise NetworkCalculationError("纵断面未覆盖结构全长，禁止外推", code="missing_profile")
    return values


def _profile_at(values, station):
    index = min(max(bisect_right([p[0] for p in values], station)-1, 0), len(values)-2)
    a, b = values[index], values[index+1]
    slope = (b[1]-a[1])/(b[0]-a[0])
    return a[1]+slope*(station-a[0]), slope


def _polygons(geometry):
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [orient(geometry)]
    if isinstance(geometry, MultiPolygon):
        return [orient(p) for p in geometry.geoms]
    if isinstance(geometry, shapely.GeometryCollection):
        # 半空间裁剪多片区域时可同时返回二维片和零面积接触线。
        # 后者不是施工实体，不修洞、不补面；二维并集仍须保持原区域。
        return [p for part in geometry.geoms if part.area > 0 for p in _polygons(part)]
    raise NetworkCalculationError("施工区域必须为二维多边形")


def _rings_geometry(rings):
    return unary_union([Polygon(ring) for ring in rings]) if rings else Polygon()


def _relative_regions(asset, slope, relative_base, relative_top, arc_segments):
    """每个纵坡不变的小段共用相对断面，保证放样逐环拓扑一致。"""
    if asset["section_type"] == "arch_tunnel":
        rings, _ = _section_outer("arch_culvert", asset["section"], arc_segments)
        permanent = _rings_geometry(rings)
        clearance = float(asset.get("construction", {}).get("excavation_clearance", -1))
        if not math.isfinite(clearance) or clearance < 0:
            raise NetworkCalculationError("暗挖隧洞须明确非负开挖预留厚度")
        excavation = permanent.buffer(clearance, quad_segs=max(8, arc_segments//4), join_style="round")
        return {"excavation": excavation, "permanent": permanent, "measured": Polygon(),
                "open_air": Polygon(), "target": Polygon(), "removal": Polygon()}
    prepared = build_construction_section(asset, station=0, origin=[0, 0, 0], tangent=[1, 0, 0],
        settings={"base_z": relative_base, "clip_top_z": relative_top, "arc_segments": arc_segments}, vertical_slope=slope)
    regions = {key: _rings_geometry(prepared[key]) for key in ("excavation", "permanent", "measured", "open_air", "target")}
    regions["removal"] = Polygon()
    if prepared["target_mode"] == "finished_profile":
        regions["removal"] = _rings_geometry(prepared["domain"]).difference(regions["target"])
    return regions


def _cell_element(alignment, s0, s1):
    midpoint = s0+(s1-s0)/2
    return next(e for e in alignment.elements if e["station_start"] <= midpoint < e["station_end"])


def _singular_offset(element):
    return -math.copysign(float(element["radius"]), element["sweep_angle"])


def _cell_tangent(alignment, station, s0, s1):
    """已知解析单元的一侧切向；纳米单元也不靠浮点eps探针。"""
    element = _cell_element(alignment, s0, s1)
    if element["kind"] == "line":
        inside = float(element["tangent_angle"])
    else:
        inside = (element["start_angle"] + element["sweep_angle"]*(station-element["station_start"])/element["length"]
                  + math.copysign(math.pi/2, element["sweep_angle"]))
    exact = alignment.get_tangent_angle_at_station(station)
    next_element = next((e for e in alignment.elements if e["station_start"] <= station < e["station_end"]), alignment.elements[-1])
    if next_element is element:
        return exact
    delta = math.atan2(math.sin(inside-exact), math.cos(inside-exact))
    # 解析圆弧与直线的相切端统一用同一station切向；真折线的任意小转角仍保留两侧。
    return exact if (element["kind"] == "arc" or next_element["kind"] == "arc") and abs(delta) < 1e-7 else inside


def _world_offsets(alignment, station, offsets, s0, s1):
    """放样和接地裁剪共用相同运算顺序与曲率中心端点。"""
    offsets = np.asarray(offsets, dtype=float)
    angle = _cell_tangent(alignment, station, s0, s1)
    lateral = np.array([math.sin(angle), -math.cos(angle)])
    result = np.asarray(alignment.get_xy_at_station(station))+offsets[:, None]*lateral
    element = _cell_element(alignment, s0, s1)
    arcs = [e for e in alignment.elements if e["kind"] == "arc" and
            (e is element or station == e["station_start"] or station == e["station_end"])]
    for arc in arcs:
        result[offsets == _singular_offset(arc)] = arc["center_xy"]
    return result


@lru_cache(maxsize=512)
def _node_shared_edges(items):
    """只给真实共线边加入已有角色顶点，二维区域严格保持相等。"""
    points = []
    for _, geometry in items:
        for poly in _polygons(geometry):
            points.extend(poly.exterior.coords[:-1])
            for ring in poly.interiors:
                points.extend(ring.coords[:-1])
    points = np.unique(np.asarray(points, dtype=float), axis=0)
    result = []
    for role, geometry in items:
        polygons = []
        for poly in _polygons(geometry):
            rings = []
            for ring in [poly.exterior, *poly.interiors]:
                coords = np.asarray(ring.coords[:-1]); expanded = []
                coords = coords[np.r_[True, np.any(np.diff(coords, axis=0) != 0, axis=1)]]
                if len(coords) > 1 and np.array_equal(coords[0], coords[-1]):
                    coords = coords[:-1]
                for a, b in zip(coords, np.roll(coords, -1, axis=0)):
                    edge = b-a; relative = points-a
                    parameter = relative@edge/float(edge@edge)
                    cross = relative[:, 0]*edge[1]-relative[:, 1]*edge[0]
                    candidates = np.where((cross == 0) & (parameter > 0) & (parameter < 1))[0]
                    line = LineString([a, b])
                    candidates = [i for i in candidates if not np.array_equal(points[i], a)
                                  and not np.array_equal(points[i], b) and line.covers(Point(points[i]))]
                    expanded.append(a)
                    expanded.extend(points[i] for i in sorted(candidates, key=lambda i: parameter[i]))
                rings.append(expanded)
            polygons.append(Polygon(rings[0], rings[1:]))
        noded = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons) if polygons else Polygon()
        if not noded.equals(geometry):
            raise NetworkCalculationError("公共边节点化改变了真实二维施工区域", code="invalid_section")
        result.append((role, noded))
    return tuple(result)


@lru_cache(maxsize=1024)
def _band_refinement(geometry, offsets):
    """用原binary64端点精确有理求交，再正确舍入一次，共用同一切点。

    非轴斜边的数学交点未必能由double精确表示，不能要求GEOS equals
    把舍入后的折边识别为原直边。每新坐标误差须不超过0.5 ULP；
    面积表示误差界由各原边和新增点的精确有理三角形面积给出。
    """
    polygons, maximum_error, area_bound, inserted = [], Fraction(0), Fraction(0), 0
    for poly in _polygons(geometry):
        rings = []
        for ring in [poly.exterior, *poly.interiors]:
            coords = list(ring.coords[:-1]); refined = []
            for a, b in zip(coords, coords[1:]+coords[:1]):
                refined.append(a)
                if a[0] == b[0]:
                    continue
                ax, az, bx, bz = map(Fraction, (*a, *b))
                intersections = []
                for x in offsets:
                    if min(a[0], b[0]) < x < max(a[0], b[0]):
                        t = (Fraction(x)-ax)/(bx-ax)
                        exact_z = az+t*(bz-az)
                        z = float(exact_z)
                        error = abs(Fraction(z)-exact_z)
                        if error > Fraction(math.ulp(z))/2:
                            raise NetworkCalculationError("切点未正确舍入到binary64", code="invalid_section")
                        maximum_error = max(maximum_error, error)
                        intersections.append((t, (float(x), z)))
                points = [p for _, p in sorted(intersections)]
                refined.extend(points); inserted += len(points)
                chain = [a, *points, b]
                for p, q in zip(chain, chain[1:]):
                    area_bound += abs((Fraction(p[0])-ax)*(Fraction(q[1])-az)
                                      -(Fraction(p[1])-az)*(Fraction(q[0])-ax))/2
            rings.append(refined)
        polygons.append(Polygon(rings[0], rings[1:]))
    refined = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons) if polygons else Polygon()
    if not refined.is_valid:
        raise NetworkCalculationError("正确舍入后的公共切点使二维区域无效", code="invalid_section")
    return refined, {"inserted_point_count": inserted, "maximum_coordinate_roundoff": float(maximum_error),
                     "area_roundoff_bound": float(area_bound)}


def _boundary_edges(geometry):
    edges = Counter()
    for poly in _polygons(geometry):
        for ring in [poly.exterior, *poly.interiors]:
            coords = list(ring.coords)
            for a, b in zip(coords, coords[1:]):
                if a != b:
                    edges[(a, b) if a < b else (b, a)] += 1 if a < b else -1
    return {key: count for key, count in edges.items() if count}


def _validate_band_partition(refined, parts):
    # 共同精确共线节点使长短边可逐条比较；原外边必须完整保留，
    # 所有内部切边须正反抵消。正向有效多边形的绕数和因此等于原区域，
    # 既证明无缺口也证明无正面积重叠，不用工程距离/面积容差。
    noded = _node_shared_edges(tuple([("original", refined), *[(str(i), p) for i, p in enumerate(parts)]]))
    actual = Counter()
    for _, part in noded[1:]:
        if not part.is_valid:
            raise NetworkCalculationError("公共偏距分带产生无效区域", code="invalid_section")
        actual.update(_boundary_edges(part))
    if _boundary_edges(noded[0][1]) != {key: count for key, count in actual.items() if count}:
        raise NetworkCalculationError("公共偏距分带改变了边拓扑、产生缺口或重叠", code="invalid_section")
    return tuple(p for _, p in noded[1:])


@lru_cache(maxsize=1024)
def _common_bands(geometry, offsets):
    refined, _ = _band_refinement(geometry, offsets)
    parts = [refined]
    for offset in offsets:
        split_parts = []
        for part in parts:
            x0, zmin, x1, zmax = part.bounds
            if x0 < offset < x1:
                split_parts.extend(_polygons(part.intersection(box(x0-1, zmin-1, offset, zmax+1))))
                split_parts.extend(_polygons(part.intersection(box(offset, zmin-1, x1+1, zmax+1))))
            else:
                split_parts.append(part)
        parts = split_parts
    return _validate_band_partition(refined, parts)


def _loft_polygon(polygon, s0, s1, z0, z1, alignment, origin, label):
    m = _backend()
    rings = [np.asarray(polygon.exterior.coords[:-1], dtype=float)]
    rings += [np.asarray(ring.coords[:-1], dtype=float) for ring in polygon.interiors]
    local = np.vstack(rings)
    n = len(local)
    vertices = []
    for station, elevation in ((s0, z0), (s1, z1)):
        world_xy = _world_offsets(alignment, station, local[:, 0], s0, s1)
        vertices.extend(np.column_stack([world_xy, local[:, 1]+elevation])-origin)
    caps = np.asarray(m.triangulate(rings), dtype=np.int64)
    faces = [*caps.tolist(), *(caps[:, [0, 2, 1]]+n).tolist()]
    offset = 0
    for ring in rings:
        for j in range(len(ring)):
            a, b = offset+j, offset+(j+1)%len(ring)
            # 曲线且有纵坡时侧壁四点不共面；单对角线会引入一阶有向体积偏置。
            # 双线性面中心四分，保持两种对角线对称，并随弦高/间距加密收敛。
            quad = (a, a+n, b+n, b)
            center = len(vertices)
            vertices.append(np.mean([vertices[i] for i in quad], axis=0))
            faces.extend([[quad[i], quad[(i+1)%4], center] for i in range(4)])
        offset += len(ring)
    return _mesh(vertices, faces, label)


def _sweep_regions(regions, s0, s1, z0, z1, alignment, origin, *, partition_offsets=None):
    element = _cell_element(alignment, s0, s1)
    if partition_offsets is None:
        partition_offsets = [_singular_offset(e) for e in alignment.elements if e["kind"] == "arc" and
                             (e is element or s0 == e["station_end"] or s1 == e["station_start"])]
    partition_offsets = tuple(sorted(set(partition_offsets)))
    result = {}
    for role, geometry in _node_shared_edges(tuple(regions.items())):
        if geometry.is_empty:
            result[role] = _backend().Manifold(); continue
        # 相邻直线也使用同一奇异偏距分带，端环节点/边分割保持一致。
        parts = _common_bands(geometry, partition_offsets)
        result[role] = _union([_loft_polygon(poly, s0, s1, z0, z1, alignment, origin, role)
                               for part in parts for poly in _polygons(part)])
    return result


def _stations(alignment, asset, profile, step, chord, extent):
    a, b = float(asset["station_start"]), float(asset["station_end"])
    breaks = {a, b, *(p[0] for p in profile if a < p[0] < b)}
    breaks.update(e[key] for e in alignment.elements for key in ("station_start", "station_end") if a < e[key] < b)
    breaks = sorted(breaks)
    result = []
    for left, right in zip(breaks, breaks[1:]):
        curvature = abs(alignment.get_curvature_at_station((left+right)/2))
        spacing = step
        if curvature:
            radius = 1/curvature
            outer = radius+extent
            angle = min(math.pi/12, 2*math.acos(max(-1., 1-min(chord/outer, 2))))
            spacing = min(step, radius*angle)
        count = max(1, math.ceil((right-left)/spacing))
        result.extend(left+(right-left)*i/count for i in range(count))
    result.append(b)
    return result


def _coverage(interp, alignment, asset, station, regions, elevation, *, tangent_station=None, tangent_angle=None):
    """实际原TIN剖面检查结构/槽底及填坡接地，不能借裁剪掩盖缺测。"""
    from ..adapters.independent_assets import _ground_component, _ground_at, _grades
    permanent = regions["permanent"]
    if permanent.is_empty:
        raise NetworkCalculationError("结构永久外包为空")
    construction = effective_construction(asset)
    underground = asset["section_type"] == "arch_tunnel"
    l, floor, r, crest = permanent.bounds
    if underground:
        l, floor, r, crest = regions["excavation"].bounds
        left, right = l, r
    else:
        ext = float(construction.get("bedding_extension", 0))
        left = l-ext-float(construction.get("working_space_left", 0))
        right = r+ext+float(construction.get("working_space_right", 0))
        floor -= float(construction.get("bedding_thickness", 0))
    angle = (alignment.get_tangent_angle_at_station(station if tangent_station is None else tangent_station)
             if tangent_angle is None else tangent_angle)
    lateral = np.array([math.sin(angle), -math.cos(angle)])
    origin = np.asarray(alignment.get_xy_at_station(station))
    try:
        ground = _ground_component(interp, origin, lateral, (left, right))
        excavation_bounds = [left, right]
        target_bounds = [l, r]
        if underground:
            # 暗挖口低于地面才有围岩；出露处须划为明洞或明确洞口施工。
            for offset, relative_z in regions["excavation"].exterior.coords:
                if relative_z+elevation > _ground_at(ground, offset)+1e-7:
                    raise ConstructionInputError("暗挖隧洞外包高于真实地面，须明确洞口/明洞过渡设计")
        elif construction.get("installation_mode", "buried") == "buried":
            for index, (side, offset, direction) in enumerate((("left", left, -1), ("right", right, 1))):
                if _ground_at(ground, offset) >= floor+elevation-1e-9:
                    trace = CrossSectionCalculator._trace_slope(offset, floor+elevation, ground, _grades(construction, side), direction)
                    excavation_bounds[index] = trace[-1][0]
        if construction.get("target_mode") == "union_terrain" and not underground:
            for index, (side, edge, direction) in enumerate((("left", l, -1), ("right", r, 1))):
                crown = edge+direction*float(construction["bank_top_width_"+side])
                target_bounds[index] = crown
                if _ground_at(ground, crown) < crest+elevation-1e-9:
                    ratio = float(construction["bank_slope_"+side])
                    hit = CrossSectionCalculator._ray_ground_hit((crown, crest+elevation), (direction*ratio, -1), ground)
                    if hit is None:
                        raise ConstructionInputError("填筑外边坡在原TIN有效范围内未接地")
                    target_bounds[index] = hit[1][0]
        active_left = min(l, *excavation_bounds, *target_bounds)
        active_right = max(r, *excavation_bounds, *target_bounds)
        heights = [_ground_at(ground, active_left), _ground_at(ground, active_right)]
        heights += [zz for x, zz in ground if active_left < x < active_right]
        return {"excavation": excavation_bounds, "target": target_bounds,
                "support": (active_left, active_right), "ground_min": min(heights), "ground_max": max(heights)}
    except (ValueError, ConstructionInputError) as exc:
        raise NetworkCalculationError(f"{asset.get('name', asset.get('asset_id'))} 桩号 {station:.3f}：{exc}",
            code="missing_terrain_or_invalid_daylight", diagnostics=[{"asset_id": asset.get("asset_id"), "station": station,
                                                                    "message": str(exc)}]) from exc


def _footprint(alignment, stations, coverages, key, origin):
    rings = []
    for index in range(len(stations)-1):
        points = []
        for j in (index, index+1):
            station = stations[j]
            points.extend(_world_offsets(alignment, station, coverages[j][key], stations[0], stations[-1])-origin[:2])
        # 小半径内侧可越过曲率中心；凸包是该小单元覆盖的保守检查域。
        rings.append(shapely.MultiPoint(points).convex_hull)
    return unary_union(rings)


def _plan_prism(geometry, base, top):
    values = []
    for polygon in _polygons(geometry):
        rings = [np.asarray(polygon.exterior.coords[:-1])]
        rings += [np.asarray(r.coords[:-1]) for r in polygon.interiors]
        xy = np.vstack(rings)
        n = len(xy)
        vertices = np.vstack([np.column_stack([xy, np.full(n, base)]), np.column_stack([xy, np.full(n, top)])])
        caps = np.asarray(_backend().triangulate(rings), dtype=np.int64)
        faces = [*caps[:, [0, 2, 1]].tolist(), *(caps+n).tolist()]
        offset = 0
        for ring in rings:
            for index in range(len(ring)):
                a, b = offset+index, offset+(index+1)%len(ring)
                faces.extend([[a, b, b+n], [a, b+n, a+n]])
            offset += len(ring)
        values.append(_mesh(vertices, faces, "实际首次接地施工范围"))
    return _union(values)


def _volumes(solids):
    values = {name+"_volume": max(0., _checked(solid, name).volume()) for name, solid in solids.items()
              if name in ("excavation", "backfill", "embankment")}
    values["total_fill_volume"] = values["backfill_volume"]+values["embankment_volume"]
    return values


def _hierarchy_measurement(roles):
    """只测已构造包含的两正体，不为诊断再制造近共面差集实体。

    每cell E=union(同一个RawE,P_clip,M_clip,O_clip)，随后分别并集并
    裁同一原TIN域，故RawE⊂E。此统计不参与任何开挖、回填或填筑布尔。
    """
    corrected = _checked(roles["excavation"], "层级修正后开挖包络")
    raw = _checked(roles["excavation_unadjusted"], "层级修正前开挖包络")
    corrected_volume, raw_volume = corrected.volume(), raw.volume()
    delta = math.fsum((corrected_volume, -raw_volume))
    if not math.isfinite(delta) or delta < -1e-7:
        raise NetworkCalculationError(f"三维施工层级修正体积差无效：{delta}", code="invalid_solid")
    return {"method": "constructive_inclusion_signed_volume_difference",
            "corrected_excavation_volume_m3": corrected_volume,
            "unadjusted_excavation_volume_m3": raw_volume,
            "volume_delta_m3": delta, "negative_volume_rejection_m3": -1e-7,
            "inclusion_proof": "per_cell_union_contains_same_raw_operand_then_global_unions_and_common_TIN_domain"}


def _bbox_overlap(a, b):
    """仅剔除严格分离的原实体包围盒，不用工程容差删去真实交集。"""
    if a.is_empty() or b.is_empty():
        return False
    aa, bb = a.bounding_box(), b.bounding_box()
    return all(aa[k] <= bb[k+3] and bb[k] <= aa[k+3] for k in range(3))


def _allocate(assets, role_parts, final, absolute_tolerance, *, soil, void, cancelled=None, progress=None):
    """各施工角色先按桩号扣除全部更早范围，再剖切原土，保留全局独立量核验。

    E净_i=E_i-并(早E)，T净_i=T_i-并(早T)；C_i=G∩E净_i，
    B_i=C_i-V全局，F_i=(T净_i-G)-V全局。净域在同role内互斥，
    不能把未经扣重的逐资产gross量相加。回填随开挖归属，填筑随T归属。
    """
    roles = ("excavation", "backfill", "embankment")
    limit = max(1e-6, absolute_tolerance*.001)
    components = {role: [] for role in roles}
    rows, net_checks = [], []
    for index, asset in enumerate(assets):
        _cancel(cancelled)
        if progress:
            progress("allocation", .8*index/max(1, len(assets)),
                     f"逐结构分项 {index+1}/{len(assets)}，{asset.get('name', '')}")
        net_parts = {}
        for role in ("excavation", "target"):
            raw = role_parts[role][index]
            earlier_indices = [j for j, part in enumerate(role_parts[role][:index]) if _bbox_overlap(raw, part)]
            if earlier_indices:
                earlier = _union([role_parts[role][j] for j in earlier_indices])
                net = _checked(raw-earlier, "角色首归属净域")
                common = _checked(raw ^ earlier, "角色已归属交域")
                partition_error = abs(math.fsum((net.volume(), common.volume(), -raw.volume())))
            else:
                net, common, partition_error = raw, _backend().Manifold(), 0.
            if partition_error > limit:
                raise NetworkCalculationError(f"角色首归属净域分割不守恒：{partition_error:.9g} m³",
                    code="invalid_partition", diagnostics=[{"asset_id": asset.get("asset_id"), "role": role,
                    "partition_error_m3": partition_error}])
            net_checks.append({"asset_id": asset.get("asset_id"), "role": role,
                "earlier_asset_ids": [assets[j].get("asset_id") for j in earlier_indices],
                "raw_volume_m3": raw.volume(), "net_volume_m3": net.volume(),
                "common_volume_m3": common.volume(), "partition_error_m3": partition_error})
            net_parts[role] = net
        natural = _checked(soil ^ net_parts["excavation"], "结构净域天然开挖")
        allocated = {"excavation": natural,
                     "backfill": _checked(natural-void, "结构净域周边回填"),
                     "embankment": _checked((net_parts["target"]-soil)-void, "结构净域新增填筑")}
        for role, solid in allocated.items():
            components[role].append(solid)
        rows.append({"asset_id": asset.get("asset_id"), "name": asset.get("name", ""),
                     "section_type": asset["section_type"], "station_start": asset["station_start"],
                     "station_end": asset["station_end"], "length": asset["station_end"]-asset["station_start"],
                     **_volumes(allocated), "allocation_policy": "role_station_order_first_owner"})
    # 净域公式外再核实际闭合分体：所有bbox相交同role对，以及全部B/F跨role对。
    pairs = []
    for role in roles:
        for ia, a in enumerate(components[role]):
            pairs.extend((role, ia, role, ib, a, b) for ib, b in enumerate(components[role][:ia]) if _bbox_overlap(a, b))
    for ia, a in enumerate(components["backfill"]):
        pairs.extend(("backfill", ia, "embankment", ib, a, b) for ib, b in enumerate(components["embankment"]) if _bbox_overlap(a, b))
    maximum_overlap = 0.
    for pair_index, (role_a, ia, role_b, ib, a, b) in enumerate(pairs):
        _cancel(cancelled)
        cross = _checked(a ^ b, "首归属分体互斥核验")
        maximum_overlap = max(maximum_overlap, abs(cross.volume()))
        if abs(cross.volume()) > limit:
            raise NetworkCalculationError(f"首归属分体存在重复量：{cross.volume():.9g} m³", code="invalid_partition",
                diagnostics=[{"asset_a": assets[ia].get("asset_id"), "role_a": role_a,
                              "asset_b": assets[ib].get("asset_id"), "role_b": role_b}])
        if progress and (pair_index % 10 == 0 or pair_index+1 == len(pairs)):
            progress("allocation", .8+.2*(pair_index+1)/max(1, len(pairs)), "核验逐结构分体互斥")
    quantities = _volumes(final)
    residuals = {}
    for key in ("excavation_volume", "backfill_volume", "embankment_volume", "total_fill_volume"):
        assigned = math.fsum(row[key] for row in rows)
        residuals[key] = quantities[key]-assigned
        if not math.isclose(assigned, quantities[key], rel_tol=1e-8, abs_tol=1e-5):
            raise NetworkCalculationError(f"逐结构互斥归属量与全局量不一致：{key}，{assigned} / {quantities[key]}", code="allocation_incomplete")
        if key != "total_fill_volume" and abs(residuals[key]) > limit:
            raise NetworkCalculationError(f"存在未归属或超额归属施工量：{key}，{residuals[key]:.9g} m³", code="allocation_incomplete")
    validation = {"allocation_policy": "role_station_order_first_owner",
                  "net_role_partition_checks": net_checks,
                  "maximum_net_role_partition_error_m3": max((c["partition_error_m3"] for c in net_checks), default=0.),
                  "component_pairwise_intersection_check_count": len(pairs),
                  "maximum_component_pairwise_overlap_m3": maximum_overlap,
                  "component_volume_sum_residual_m3": residuals,
                  "net_role_partitions_verified": True, "component_pairwise_disjoint_verified": True,
                  "global_component_sums_verified": True}
    # 保留有符号数值残差供审查，不能平摊到行或把超额归属夹为零。
    return rows, {role: residuals[role+"_volume"] for role in roles}, validation


def calculate_network(tin, network, *, chord_tolerance=.02, profile_step=10., relative_tolerance=.002,
                      absolute_tolerance=1., max_refinements=3, cancelled=None, progress=None, keep_solids=True,
                      checkpoint=None):
    """原TIN + 解析路线 + 明确施工结构 → 去重的全线挖、回填、填筑。

    任何加密失败、非流形、缺测或未收敛均抛异常，不能输出 READY。
    返回 solids 使用 origin 平移后的局部米制坐标，导出时须加回 origin。
    """
    _cancel(cancelled)
    m = _backend()
    alignment = network["alignment"]
    if isinstance(alignment, dict):
        from .network_alignment import NetworkAlignment
        alignment = NetworkAlignment.from_dict(alignment)
    assets = sorted(deepcopy(network.get("assets") or []), key=lambda a: (float(a["station_start"]), str(a.get("asset_id"))))
    normalize_construction_inputs(assets)
    if not assets:
        raise NetworkCalculationError("全线网络没有施工结构")
    if (not math.isfinite(chord_tolerance) or chord_tolerance <= 0 or not math.isfinite(profile_step) or profile_step <= 0
            or not all(math.isfinite(v) and v >= 0 for v in (relative_tolerance, absolute_tolerance))
            or not isinstance(max_refinements, int) or max_refinements < 1):
        raise NetworkCalculationError("离散精度、体积容差或加密次数无效")
    profiles = [_profile(a, network) for a in assets]
    for a in assets:
        if not alignment.start_station-1e-8 <= a["station_start"] < a["station_end"] <= alignment.end_station+1e-8:
            raise NetworkCalculationError("结构桩号范围超出解析路线")
        if a.get("construction", {}).get("target_mode") == "finished_profile":
            raise NetworkCalculationError("全线 finished_profile 需逐桩三维目标土面，当前入口仅支持明确渠堤或恢复原地面")
    points = np.asarray(tin.points, dtype=float)
    profile_z = [p[1] for values in profiles for p in values]
    ground_min, ground_max = float(points[:, 2].min()), float(points[:, 2].max())
    rel_base = min(ground_min-max(profile_z)-10, -20.)
    rel_top = max(ground_max-min(profile_z)+10, 20.)
    world_base = min(ground_min, min(profile_z)+rel_base)-5
    world_top = max(ground_max, max(profile_z)+rel_top)+5
    origin = np.array([points[0, 0], points[0, 1], ground_min], dtype=float)
    soil, domain = _terrain_solids(tin, world_base, world_top, origin)
    support = shapely.union_all(shapely.polygons(points[np.asarray(tin.triangles), :2]-origin[:2]))
    corners = points[np.asarray(tin.triangles), :2]-origin[:2]
    v1, v2 = corners[:, 1]-corners[:, 0], corners[:, 2]-corners[:, 0]
    summed_area = np.abs(v1[:, 0]*v2[:, 1]-v1[:, 1]*v2[:, 0]).sum()/2
    if summed_area-support.area > max(1e-6, summed_area*1e-10):
        raise NetworkCalculationError("原TIN三角片存在平面覆盖重叠，不能重复计量", code="invalid_terrain")
    interp = TINInterpolator(tin)
    history, previous, final = [], None, None
    previous_rows, rows, unallocated = None, None, None
    start_time = time.perf_counter()
    checked_coverage = {}
    asset_limits = {}
    for refinement in range(max_refinements+1):
        _cancel(cancelled)
        chord, step = chord_tolerance/(2**refinement), profile_step/(2**refinement)
        arc_segments = min(2048, 4*math.ceil(max(32, math.pi/math.acos(max(-1., 1-min(chord/10, 1))))/4))
        role_parts = {key: [] for key in ("excavation", "excavation_unadjusted", "permanent", "measured", "open_air", "target", "removal")}
        scopes, cells = [], 0
        for index, (asset, profile) in enumerate(zip(assets, profiles)):
            _cancel(cancelled)
            if index not in asset_limits:
                # 先以真实剖面求各结构物理接地宽和局部上下界，不能拿全线极差扩大的辅助域控制圆弧细分。
                coarse = _stations(alignment, asset, profile, profile_step, profile_step, 0)
                minimum, maximum, extent = math.inf, -math.inf, 0.
                for station in coarse:
                    z, slope = _profile_at(profile, station)
                    proto = _relative_regions(asset, slope, rel_base, rel_top, arc_segments)
                    info = _coverage(interp, alignment, asset, station, proto, z)
                    minimum = min(minimum, info["ground_min"]-z, proto["permanent"].bounds[1]-float(asset.get("construction", {}).get("bedding_thickness", 0)))
                    maximum = max(maximum, info["ground_max"]-z, proto["permanent"].bounds[3])
                    extent = max(extent, *(abs(v) for v in info["support"]))
                asset_limits[index] = (minimum-1, maximum+1, extent)
            local_base, local_top, extent = asset_limits[index]
            stations = _stations(alignment, asset, profile, step, chord, extent)
            partition_offsets = tuple(sorted({_singular_offset(e) for e in alignment.elements
                if e["kind"] == "arc" and e["station_start"] < asset["station_end"] and e["station_end"] > asset["station_start"]}))
            local_parts = {key: [] for key in role_parts}
            region_cache = {}
            for s0, s1 in zip(stations, stations[1:]):
                _cancel(cancelled)
                # 端环共用同一解析高程，不从不同中点反算共同端点。
                # 坡度仍取原控制区间固定斜率，禁止对纳米级小段做高程差商。
                _, slope = _profile_at(profile, (s0+s1)/2)
                z0 = _profile_at(profile, s0)[0]
                z1 = _profile_at(profile, s1)[0]
                if slope not in region_cache:
                    region_cache[slope] = _relative_regions(asset, slope, local_base, local_top, arc_segments)
                regions = region_cache[slope]
                sample_stations = (s0, (s0+s1)/2, s1)
                coverages = []
                for s, z in zip(sample_stations, (z0, (z0+z1)/2, z1)):
                    angle = _cell_tangent(alignment, s, s0, s1)
                    coverage_key = (index, s, angle, slope, arc_segments)
                    if coverage_key not in checked_coverage:
                        checked_coverage[coverage_key] = _coverage(interp, alignment, asset, s, regions, z, tangent_angle=angle)
                    coverages.append(checked_coverage[coverage_key])
                elevations = (z0, (z0+z1)/2, z1)
                needed_base = min(info["ground_min"]-z for info, z in zip(coverages, elevations))-1
                needed_top = max(info["ground_max"]-z for info, z in zip(coverages, elevations))+1
                if needed_base < local_base or needed_top > local_top:
                    # 初始粗剖面之间的山峰/谷底不能被辅助上下界裁掉。
                    regions = _relative_regions(asset, slope, min(local_base, needed_base),
                                                max(local_top, needed_top), arc_segments)
                if not regions["excavation"].is_empty:
                    for role in ("permanent", "measured", "open_air"):
                        outside_2d = regions[role].difference(regions["excavation"]).area
                        if outside_2d > 1e-9:
                            raise NetworkCalculationError(f"二维{role}超出开挖包络{outside_2d:.9g} m²，不能以三维层级修正掩盖真实漏挖",
                                code="insufficient_excavation", diagnostics=[{"asset_id": asset.get("asset_id"),
                                    "station_start": s0, "station_end": s1, "outside_2d_area": outside_2d}])
                cell_support = _footprint(alignment, sample_stations, coverages, "support", origin)
                missing_area = cell_support.difference(support).area
                if missing_area > 1e-6:
                    raise NetworkCalculationError(f"{asset.get('name')} 桩号{s0:.3f}至{s1:.3f}施工范围跨越原TIN孔洞或边界（{missing_area:.6g} m²）",
                        code="missing_terrain", diagnostics=[{"asset_id": asset.get("asset_id"), "station_start": s0,
                                                             "station_end": s1, "missing_plan_area": missing_area}])
                swept = _sweep_regions(regions, s0, s1, z0, z1, alignment, origin, partition_offsets=partition_offsets)
                excavation_clip = _plan_prism(_footprint(alignment, sample_stations, coverages, "excavation", origin),
                                              world_base-origin[2], world_top-origin[2])
                for role in ("excavation", "open_air"):
                    swept[role] = _checked(swept[role] ^ excavation_clip, "首次接地开挖裁剪")
                swept["excavation_unadjusted"] = swept["excavation"]
                if not regions["excavation"].is_empty:
                    children = []
                    for role in ("permanent", "measured", "open_air"):
                        outside_daylight = _checked(swept[role]-excavation_clip, "实际接地范围外的施工子层")
                        if outside_daylight.volume() > 1e-6:
                            raise NetworkCalculationError(f"{role}离散体超出首次接地范围{outside_daylight.volume():.9g} m³，不能恢复域外土方岛",
                                code="invalid_daylight", diagnostics=[{"asset_id": asset.get("asset_id"),
                                    "station_start": s0, "station_end": s1, "role": role}])
                        children.append(_checked(swept[role] ^ excavation_clip, "接地范围内施工子层"))
                    # 二维已证实包含，三维离散须维持同一施工层级；修正只在实测首次接地域内。
                    swept["excavation"] = _union([swept["excavation"], *children])
                if not swept["target"].is_empty():
                    target_clip = _plan_prism(_footprint(alignment, sample_stations, coverages, "target", origin),
                                             world_base-origin[2], world_top-origin[2])
                    swept["target"] = _checked(swept["target"] ^ target_clip, "首次接地填坡裁剪")
                for role, solid in swept.items():
                    local_parts[role].append(solid)
                cells += 1
            local_union = {role: _union(values) for role, values in local_parts.items()}
            # 生产归属使用各role净域；混合scope仅供显式checkpoint复现旧诊断。
            if checkpoint is not None:
                scopes.append(_union([local_union["excavation"], local_union["target"], local_union["removal"]]))
            for role, solid in local_union.items():
                role_parts[role].append(solid)
            if progress:
                progress("sweep", index/max(1, len(assets)), f"第{refinement+1}轮，{asset.get('name', index)}")
        roles = {key: _checked(_union(values) ^ domain, key) for key, values in role_parts.items()}
        if checkpoint is not None:
            checkpoint("roles", {"refinement": refinement, "origin": origin, "assets": assets,
                "soil": soil, "domain": domain, "roles": roles, "role_parts": role_parts, "scopes": scopes})
        hierarchy_measurement = _hierarchy_measurement(roles)
        cut = _checked(soil ^ roles["excavation"], "天然开挖")
        # G-(G∩E)=G-E。直接用E裁保留土，减少已经含原TIN顶面的C
        # 再参与共面差集/求交的运算链；真实Ma反例中旧R本身点内关系
        # 正确，但(R∩V)输出了R外的伪交集，独立原面绕数已核实。
        retained = _checked(soil-roles["excavation"], "保留原土")
        occupancy = _union([roles["permanent"], roles["measured"]])
        void = _union([occupancy, roles["open_air"], roles["removal"]])
        # C=G∩E，故(G∩V)-C = G∩(V-E) = (G-E)∩V。
        # 不再对已含同一TIN顶面的Q/C近等体求差；真实第三轮中旧Q-C
        # 在Q1/C1内点产生winding=-1伪壳。两等价式仍独立核验原门槛。
        natural_void = _checked(soil ^ void, "原土内结构及不填空间")
        conflict = _checked(soil ^ (void-roles["excavation"]), "应挖未挖")
        conflict_alternative = _checked(retained ^ void, "应挖未挖独立核验")
        conflict_volume = max(conflict.volume(), conflict_alternative.volume())
        if conflict_volume > max(1e-6, absolute_tolerance*.01):
            raise NetworkCalculationError(f"仍有应挖未挖土体 {conflict_volume:.9g} m³", code="insufficient_excavation")
        # 填方按原土内外正交分区：B=C-V，F=(T-G)-V，避免再减整片原土。
        # 两个漏挖等价式已验证 G∩V⊂C，因此 C∩V=G∩V。
        # 不再用同界面C.split(V)的交集侧重复切割这一已知子集；实际反例中
        # 其交集侧丢失薄层，而差集侧与独立G∩V仍严格守恒。
        occupied_cut = natural_void
        backfill = _checked(cut-void, "结构周边回填")
        cut_partition_error = abs(math.fsum((cut.volume(), -occupied_cut.volume(), -backfill.volume())))
        if cut_partition_error > max(1e-6, absolute_tolerance*.001):
            raise NetworkCalculationError("开挖与结构周边回填分割不守恒", code="invalid_partition")
        embankment = _checked((roles["target"]-soil)-void, "新增填筑")
        # B在原土内，F在原土外；总填方保留这两个可导出的闭合成分。
        # 真实Ma例中便利B∪F再次布尔漏掉F，故核真实互斥而不制造合并体。
        overlap = _checked(backfill ^ embankment, "回填与填筑互斥核验")
        partition_error = abs(overlap.volume())
        if partition_error > max(1e-6, absolute_tolerance*.001):
            raise NetworkCalculationError("回填与填筑实体存在重复量", code="invalid_partition")
        final = {"excavation": cut, "backfill": backfill, "embankment": embankment,
                 "permanent": roles["permanent"], "measured": roles["measured"],
                 "occupancy": occupancy}
        quantities = _volumes(final)
        if checkpoint is not None:
            checkpoint("global", {"refinement": refinement, "origin": origin, "assets": assets,
                "soil": soil, "roles": roles, "role_parts": role_parts, "scopes": scopes, "final": final,
                "retained": retained, "void": void, "conflict": conflict,
                "conflict_alternative": conflict_alternative, "quantities": quantities})
        current = np.array([quantities[k] for k in ("excavation_volume", "backfill_volume", "embankment_volume")])
        difference = None if previous is None else np.abs(current-previous)
        global_passed = difference is not None and bool(np.all(difference <= absolute_tolerance+relative_tolerance*np.abs(current)))
        passed = False
        asset_changes = None
        _cancel(cancelled)
        if progress:
            progress("allocation", 0., "计算本轮逐结构互斥归属量")
        rows, unallocated, allocation_validation = _allocate(assets, role_parts, final, absolute_tolerance,
            soil=soil, void=void, cancelled=cancelled, progress=progress)
        if previous_rows is not None:
            asset_changes = []
            for old, new in zip(previous_rows, rows):
                keys = ("excavation_volume", "backfill_volume", "embankment_volume")
                delta = {key: abs(new[key]-old[key]) for key in keys}
                asset_passed = all(delta[key] <= absolute_tolerance+relative_tolerance*abs(new[key]) for key in keys)
                asset_changes.append({"asset_id": new["asset_id"], "passed": asset_passed, **delta})
            passed = global_passed and all(change["passed"] for change in asset_changes)
        history.append({"refinement": refinement, "chord_tolerance_m": chord, "profile_step_m": step,
                        "arc_segments": arc_segments, "sweep_cell_count": cells, **quantities,
                        "hierarchy_correction_volume_m3": hierarchy_measurement["volume_delta_m3"],
                        "hierarchy_correction_measurement": hierarchy_measurement,
                        "excavation_conflict_volume_m3": conflict.volume(),
                        "excavation_conflict_alternative_volume_m3": conflict_alternative.volume(),
                        "cut_void_backfill_partition_error_m3": cut_partition_error,
                        "backfill_embankment_overlap_m3": overlap.volume(),
                        "allocation_validation": allocation_validation,
                        "successive_change_m3": None if difference is None else difference.tolist(),
                        "global_volume_converged": global_passed, "asset_volume_converged": passed,
                        "asset_successive_changes_m3": asset_changes,
                        "converged": passed, "elapsed_seconds": time.perf_counter()-start_time})
        if progress:
            progress("refinement", (refinement+1)/(max_refinements+1),
                     f"第{refinement+1}轮完成：挖方{quantities['excavation_volume']:.6f} m³，"
                     f"回填{quantities['backfill_volume']:.6f} m³，填筑{quantities['embankment_volume']:.6f} m³；"
                     f"全局{'已' if global_passed else '未'}收敛，逐结构{'已' if passed else '未'}收敛")
        if passed:
            break
        previous = current
        previous_rows = rows
        # 下轮只保存逐结构数值，不把两轮数百万面CSG同时留在内存。
        final = None
        del roles, role_parts, scopes, cut, retained, occupancy, void, conflict, conflict_alternative
        del occupied_cut, natural_void, backfill, embankment, overlap, hierarchy_measurement
        del local_parts, local_union, swept
    else:
        raise NetworkCalculationError("全线挖填实体离散加密未达到体积容差", code="not_converged", diagnostics=history)
    _cancel(cancelled)
    validation = {"converged": True, "global_volume_converged": True, "asset_volume_converged": True,
                  "closed_manifold_solids": True, "original_TIN_topology_preserved": True,
                  "global_overlap_resolved": True, "unallocated_volume": unallocated,
                  "volume_partition_error": partition_error,
                  "backfill_embankment_overlap_m3": overlap.volume(),
                  "allocation_validation": allocation_validation,
                  "unallocated_volume_interpretation": "signed_global_minus_assigned_numerical_residual",
                  "local_origin_and_float64": True, "terrain_daylight_check_count": len(checked_coverage)}
    validation.update(hierarchy_2d_containment_verified=True, first_daylight_preserved=True,
                      hierarchy_correction_volume_m3=hierarchy_measurement["volume_delta_m3"],
                      hierarchy_correction_measurement=hierarchy_measurement,
                      hierarchy_constructive_inclusion_verified=True,
                      orthogonal_fill_partition=True, conflict_two_equivalent_formulas_verified=True,
                      excavation_coverage_formulas=["G_intersection_(V_minus_E)", "(G_minus_E)_intersection_V"],
                      allocation_each_refinement=True, allocation_policy="role_station_order_first_owner",
                      total_fill_representation="sum_of_disjoint_backfill_and_embankment_solids")
    return NetworkCalculationResult(quantities, rows, history, validation, tuple(origin),
        {**final, "cut": final["excavation"]} if keep_solids else {}, test_only=bool(network.get("test_only")),
        terrain_metadata=deepcopy(getattr(tin, "import_report", {})),
        input_metadata={"asset_count": len(assets), "route": alignment.to_dict(),
                        "tunnel_method": "underground_outer_envelope_clearance_no_surface_trench"})
