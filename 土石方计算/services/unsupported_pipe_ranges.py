"""Locate unsupported closed-pipe intervals on the unchanged original TIN.

The detector returns scope records; it never edits an alignment, a profile, or
the terrain.  Triangle-edge and profile events prevent short interior islands
from disappearing between the ordinary two-metre search stations.
"""
from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from functools import lru_cache
import math
from time import monotonic

import numpy as np
from scipy.spatial import cKDTree

from .contracts import ConstructionInputError

STATION_TOLERANCE_M = .001
_ROOT_WIDTH_M = 1e-6
_CLOSED = {"circular_culvert", "circular_channel", "circular_siphon", "rectangular_culvert", "arch_culvert"}


class _RangeScanProgress:
    """Report completed objects and the active survey station at bounded frequency."""

    def __init__(self, notify, stage, label, count):
        self.notify = notify
        self.stage = stage
        self.label = label
        self.count = count
        self.next_update = 0.
        if self.notify:
            self.notify(self.stage, 0., f"正在准备{self.label} · {self.count} 个对象")

    def select_object(self, index, asset):
        if not self.notify:
            return
        from .construction_rules import is_circular_culvert
        from ..io.network_exporter import SECTION_NAMES

        self.index = index
        names = (str(asset.get(field) or "").strip() for field in ("base_name", "name"))
        name = next((value for value in names if value not in {"", "-", "—", "/", "未命名"}), "")
        if not name:
            kind = asset.get("kind")
            if is_circular_culvert(asset):
                name = "圆管涵"
            elif kind in {"pipe", "pressure_pipe"}:
                name = "有压管道"
            elif kind == "siphon":
                name = "倒虹吸"
            else:
                name = SECTION_NAMES.get(asset.get("section_type"), "管涵")
        self.name = name

    def checkpoint(self, station):
        if not self.notify:
            return
        now = monotonic()
        if now < self.next_update:
            return
        self.next_update = now + 2.
        self.notify(self.stage, self.index / self.count,
                    f"正在{self.label} · {self.index + 1}/{self.count} {self.name} · 桩号 {station:.3f} m")

    def finish(self):
        if self.notify:
            self.notify(self.stage, 1., f"{self.label}完成 · {self.count}/{self.count} 个对象")


class UnsupportedPipeTerrainError(ConstructionInputError):
    """A support footprint crosses a missing part of the original terrain."""
    code = "section_terrain_unavailable"

    def __init__(self, x, y):
        super().__init__(f"管道支承足迹缺少原地形：X={x:.6f}，Y={y:.6f}")
        self.diagnostics = [{"code": self.code, "x": float(x), "y": float(y)}]


def _check(cancelled):
    if cancelled and cancelled():
        raise InterruptedError("管道支承区间检测已取消")


class _OriginalTIN:
    """An index of original faces, without new triangulation or GEOS faces."""
    def __init__(self, tin, cancelled):
        self.cancelled = cancelled
        self.points = np.asarray(tin.points)
        self.faces = np.asarray(tin.triangles)
        if (self.points.ndim != 2 or self.points.shape[1] != 3 or not len(self.points)
                or self.faces.ndim != 2 or self.faces.shape[1] != 3 or not len(self.faces)
                or not np.issubdtype(self.faces.dtype, np.integer)):
            raise ConstructionInputError("原始TIN顶点或三角片无效")
        centers = np.empty((len(self.faces), 2), dtype=float)
        self.bounds = np.empty((len(self.faces), 4), dtype=float)
        for start in range(0, len(self.faces), 100000):
            _check(cancelled)
            end = min(len(self.faces), start + 100000)
            ids = self.faces[start:end]
            if np.any(ids < 0) or np.any(ids >= len(self.points)):
                raise ConstructionInputError("原始TIN三角片索引无效")
            corners = self.points[ids]
            if not np.isfinite(corners).all():
                raise ConstructionInputError("原始TIN顶点坐标缺测")
            xy = corners[:, :, :2]
            centers[start:end] = xy.mean(axis=1)
            self.bounds[start:end, :2] = xy.min(axis=1)
            self.bounds[start:end, 2:] = xy.max(axis=1)
        _check(cancelled)
        self.tree = cKDTree(centers)
        self._face_blocks = None

    def _candidate_blocks(self, bounds):
        """Find spatial blocks before applying the exact original box test."""
        from shapely import box
        from shapely.strtree import STRtree

        block_size = 128
        ordered_ids = self.tree.indices
        if self._face_blocks is None:
            # KD-tree indices group nearby face centers. Each block box covers
            # complete faces, including triangles with an unusually long edge.
            starts = np.arange(0, len(ordered_ids), block_size)
            ordered_bounds = self.bounds[ordered_ids]
            low = np.minimum.reduceat(ordered_bounds[:, :2], starts, axis=0)
            high = np.maximum.reduceat(ordered_bounds[:, 2:], starts, axis=0)
            self._face_blocks = STRtree(box(low[:, 0], low[:, 1], high[:, 0], high[:, 1]))
        lo_x, lo_y, hi_x, hi_y = bounds
        blocks = self._face_blocks.query(box(lo_x - 1e-8, lo_y - 1e-8, hi_x + 1e-8, hi_y + 1e-8))
        positions = (blocks[:, None] * block_size + np.arange(block_size)).ravel()
        return ordered_ids[positions[positions < len(ordered_ids)]]

    def _face_elevations(self, points, ids):
        corners = self.points[self.faces[ids]]
        a = corners[..., 0, :2]
        e1, e2 = corners[..., 1, :2] - a, corners[..., 2, :2] - a
        d = points[..., None, :] - a
        den = e1[..., 0] * e2[..., 1] - e1[..., 1] * e2[..., 0]
        with np.errstate(divide="ignore", invalid="ignore"):
            u = (d[..., 0] * e2[..., 1] - d[..., 1] * e2[..., 0]) / den
            v = (e1[..., 0] * d[..., 1] - e1[..., 1] * d[..., 0]) / den
            inside = (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & np.isfinite(u) & np.isfinite(v)
            heights = corners[..., 0, 2] + u * (corners[..., 1, 2] - corners[..., 0, 2]) + v * (corners[..., 2, 2] - corners[..., 0, 2])
        return heights, inside

    def _in_faces(self, x, y, ids):
        heights, inside = self._face_elevations(np.asarray((x, y)), ids)
        hits = np.flatnonzero(inside)
        if not len(hits):
            return None
        j = int(hits[0])
        return float(heights[j]), int(ids[j])

    def query(self, x, y):
        _check(self.cancelled)
        for count in (24, 96, 384, 1536):
            _, ids = self.tree.query([x, y], k=min(count, len(self.faces)))
            found = self._in_faces(x, y, np.atleast_1d(ids))
            if found is not None:
                return found
        ids = self.candidates((x, y, x, y))
        if len(ids):
            found = self._in_faces(x, y, ids)
            if found is not None:
                return found
        raise UnsupportedPipeTerrainError(x, y)

    def query_many(self, points):
        _check(self.cancelled)
        points = np.asarray(points)
        _, ids = self.tree.query(points, k=min(24, len(self.faces)))
        if ids.ndim == 1:
            ids = ids[:, None]
        heights, inside = self._face_elevations(points, ids)
        choices = inside.argmax(axis=1)
        rows = np.arange(len(points))
        return [(float(heights[i, j]), int(ids[i, j])) if inside[i, j] else self.query(*points[i])
                for i, j in zip(rows, choices)]

    def candidates(self, bounds, ids=None):
        _check(self.cancelled)
        all_faces = ids is None
        if all_faces:
            ids = self._candidate_blocks(bounds)
        b = self.bounds[ids]
        lo_x, lo_y, hi_x, hi_y = bounds
        mask = ((b[:, 0] <= hi_x + 1e-8) & (b[:, 1] <= hi_y + 1e-8)
                & (b[:, 2] >= lo_x - 1e-8) & (b[:, 3] >= lo_y - 1e-8))
        return np.sort(ids[mask]) if all_faces else ids[mask]

    def line_events(self, start, end, ids=None):
        a, b = np.asarray(start), np.asarray(end)
        low, high = np.minimum(a, b), np.maximum(a, b)
        ids = self.candidates((*low, *high), ids)
        if not len(ids):
            return []
        xy = self.points[self.faces[ids], :2]
        p, v1, v2 = xy[:, 0], xy[:, 1] - xy[:, 0], xy[:, 2] - xy[:, 0]
        den = v1[:, 0] * v2[:, 1] - v1[:, 1] * v2[:, 0]
        def bary(q):
            d = q - p
            with np.errstate(divide="ignore", invalid="ignore"):
                u = (d[:, 0] * v2[:, 1] - d[:, 1] * v2[:, 0]) / den
                v = (v1[:, 0] * d[:, 1] - v1[:, 1] * d[:, 0]) / den
            return np.column_stack((u, v, 1 - u - v))
        first, last = bary(a), bary(b)
        delta = last - first
        left, right = np.zeros(len(ids)), np.ones(len(ids))
        valid = np.isfinite(first).all(axis=1) & np.isfinite(delta).all(axis=1)
        for i in range(3):
            d, c = delta[:, i], first[:, i]
            nonzero = abs(d) > 1e-15
            roots = np.divide(-c, d, out=np.zeros_like(c), where=nonzero)
            left = np.where(d > 1e-15, np.maximum(left, roots), left)
            right = np.where(d < -1e-15, np.minimum(right, roots), right)
            valid &= nonzero | (c >= -1e-9)
        valid &= (left <= right + 1e-10) & (right >= 0) & (left <= 1)
        return [*np.clip(left[valid], 0, 1), *np.clip(right[valid], 0, 1)]

    def arc_events(self, element, lo, hi, offset, ids=None):
        sign = math.copysign(1., element["sweep_angle"])
        radius = element["radius"] + sign * offset
        if radius <= 0:
            raise ConstructionInputError("管道支承足迹跨越平面曲率中心")
        center = np.asarray(element["center_xy"])
        ids = self.candidates((center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius), ids)
        if not len(ids):
            return []
        p, q = self.edges(ids)
        d, v = q[:, :2] - p[:, :2], p[:, :2] - center
        aa, bb, cc = (d*d).sum(axis=1), 2*(v*d).sum(axis=1), (v*v).sum(axis=1) - radius*radius
        disc = bb*bb - 4*aa*cc
        good = (disc >= 0) & (aa > 0)
        stations = []
        for mult in (-1, 1):
            roots = (-bb[good] + mult*np.sqrt(disc[good])) / (2*aa[good])
            keep = (roots >= -1e-9) & (roots <= 1 + 1e-9)
            hits = p[good][keep, :2] + roots[keep, None]*d[good][keep]
            theta = np.arctan2(hits[:, 1] - center[1], hits[:, 0] - center[0])
            for position, angle in enumerate(theta):
                if position % 256 == 0:
                    _check(self.cancelled)
                for s in _angle_stations(element, float(angle)):
                    if lo - 1e-8 <= s <= hi + 1e-8:
                        stations.append(s)
        return stations

    def edges(self, ids):
        triangles = self.points[self.faces[ids]]
        return triangles[:, [0, 1, 2]].reshape(-1, 3), triangles[:, [1, 2, 0]].reshape(-1, 3)

    def gradient(self, face):
        p = self.points[self.faces[face]]
        return np.linalg.solve(p[1:, :2] - p[0, :2], p[1:, 2] - p[0, 2])


def _angle_stations(element, angle):
    sign = math.copysign(1., element["sweep_angle"])
    delta = (sign*(angle - element["start_angle"])) % (2*math.pi)
    if abs(delta - 2*math.pi) < 1e-10:
        delta = 0.
    extent = abs(element["sweep_angle"])
    while delta <= extent + 1e-10:
        yield element["station_start"] + delta/extent*element["length"]
        delta += 2*math.pi


def _xy(element, station, offset=0.):
    fraction = (station - element["station_start"])/element["length"]
    if element["kind"] == "line":
        x = element["start_xy"][0] + fraction*(element["end_xy"][0] - element["start_xy"][0])
        y = element["start_xy"][1] + fraction*(element["end_xy"][1] - element["start_xy"][1])
        theta = element["tangent_angle"]
        return x + math.sin(theta)*offset, y - math.cos(theta)*offset
    theta = element["start_angle"] + fraction*element["sweep_angle"]
    radius = element["radius"] + math.copysign(1., element["sweep_angle"])*offset
    return element["center_xy"][0] + radius*math.cos(theta), element["center_xy"][1] + radius*math.sin(theta)


def _flat_feet(region):
    if region.is_empty:
        return []
    parts = [region] if region.geom_type == "Polygon" else list(region.geoms)
    feet = []
    for part in parts:
        if part.is_empty or part.geom_type != "Polygon":
            continue
        coords = list(part.exterior.coords)
        bottom = min(z for _, z in coords)
        for (x0, z0), (x1, z1) in zip(coords, coords[1:]):
            if z0 == bottom and z1 == bottom and x0 != x1:
                feet.append({"lo": min(x0, x1), "hi": max(x0, x1), "bottom": bottom, "pipe_index": None})
    if not feet:
        raise ConstructionInputError("埋管或闭合暗涵实际底部没有平底支承足迹")
    return feet


class _Feet:
    def __init__(self, asset, profile):
        self.asset = deepcopy(asset)
        self.asset["design_profile"] = profile
        self.profile = profile
        self.templates = {}

    def at(self, station, side, element, profile_element):
        from .construction_rules import effective_construction
        from .design_profiles import evaluate_profile, pipe_profile_circle
        from .section_geometry import section_structure, add_foundation_materials
        z, slope = evaluate_profile(self.profile, station, side)
        key = (element["station_start"], profile_element["station_start"])
        if profile_element["kind"] == "line" and key in self.templates:
            old_s, feet = self.templates[key]
            return [{**f, "bottom": f["bottom"] + slope*(station - old_s)} for f in feet]
        curvature = 0. if element["kind"] == "line" else math.copysign(1/element["radius"], element["sweep_angle"])
        structure = section_structure(self.asset, elevation=z, slope=slope, arc_segments=64,
            station=station, side=side, plan_curvature=curvature)
        structure = add_foundation_materials(structure, effective_construction(self.asset), arc_segments=64)
        measured = structure["measured"]
        pipes = structure.get("pipes")
        if not measured.is_empty:
            feet = _flat_feet(measured)
        elif pipes:
            feet = [{"lo": p.get("outer_bottom_offset", p["offset"]),
                "hi": p.get("outer_bottom_offset", p["offset"]), "bottom": p["outer_bottom"],
                "pipe_index": i + 1} for i, p in enumerate(pipes)]
        else:
            feet = _flat_feet(structure["materials"]["concrete"])
        if pipes and element["kind"] == "line" and profile_element["kind"] == "arc":
            first = pipes[0]["outer_diameter"] / 2
            middle = (profile_element["station_start"] + profile_element["station_end"]) / 2
            radius = pipe_profile_circle(self.asset, first, first, middle)["support_radius"]
            for foot in feet:
                foot["support_radius"] = radius
        if profile_element["kind"] == "line":
            self.templates[key] = station, feet
        return feet


def _eligible(asset):
    from .earthwork_scope import trenchless_method
    if (not asset.get("enabled", True) or asset.get("calculation_deferred")
            or asset.get("kind") in {"tunnel", "aqueduct", "open_channel", "pit"}
            or asset.get("section_type") not in _CLOSED or trenchless_method(asset)):
        return False
    c = asset.get("construction") or {}
    return c.get("target_mode") == "restore_terrain" and c.get("installation_mode", "buried") not in {
        "exposed", "elevated", "above_ground", "open"}


def _cell_candidates(index, element, lo, hi, feet):
    offsets = [f[k] for f in feet for k in ("lo", "hi")]
    if element["kind"] == "line":
        points = [_xy(element, s, x) for s in (lo, hi) for x in offsets]
        xs, ys = zip(*points)
        return index.candidates((min(xs), min(ys), max(xs), max(ys)))
    radius = element["radius"] + max(abs(x) for x in offsets)
    x, y = element["center_xy"]
    return index.candidates((x - radius, y - radius, x + radius, y + radius))


def _events(index, element, lo, hi, feet, ids):
    events = {lo, hi}
    for foot in feet:
        for offset in {foot["lo"], foot["hi"]}:
            if element["kind"] == "line":
                events.update(lo + t*(hi - lo) for t in index.line_events(_xy(element, lo, offset), _xy(element, hi, offset), ids))
            else:
                events.update(index.arc_events(element, lo, hi, offset, ids))
        if foot["hi"] == foot["lo"]:
            continue
        # Interior terrain vertices also change the minimum under a flat foot.
        points = index.points[np.unique(index.faces[ids])]
        if element["kind"] == "line":
            origin = np.asarray(_xy(element, lo))
            tangent = np.array([math.cos(element["tangent_angle"]), math.sin(element["tangent_angle"])])
            normal = np.array([tangent[1], -tangent[0]])
            projected = (points[:, :2] - origin) @ tangent
            lateral = (points[:, :2] - origin) @ normal
            events.update(lo + float(s) for s, u in zip(projected, lateral)
                if -1e-8 <= s <= hi - lo + 1e-8 and foot["lo"] - 1e-8 <= u <= foot["hi"] + 1e-8)
        else:
            center = np.asarray(element["center_xy"])
            radial = np.linalg.norm(points[:, :2] - center, axis=1)
            sign = math.copysign(1., element["sweep_angle"])
            offsets = sign*(radial - element["radius"])
            for position, (point, u) in enumerate(zip(points, offsets)):
                if position % 256 == 0:
                    _check(index.cancelled)
                if foot["lo"] - 1e-8 <= u <= foot["hi"] + 1e-8:
                    for s in _angle_stations(element, math.atan2(point[1] - center[1], point[0] - center[0])):
                        if lo <= s <= hi:
                            events.add(s)
    return sorted(min(hi, max(lo, s)) for s in events)


def _ground_under(index, element, station, foot, ids):
    start, end = _xy(element, station, foot["lo"]), _xy(element, station, foot["hi"])
    if foot["lo"] == foot["hi"]:
        ground, face = index.query(*start)
        return ground, face, *start
    parameters = {0., 1., *index.line_events(start, end, ids)}
    ordered = sorted(parameters)
    # A missing strip between valid edge contacts is missing terrain, too.
    probes = [*ordered, *[(a + b)/2 for a, b in zip(ordered, ordered[1:])]]
    points = [(start[0] + t*(end[0] - start[0]), start[1] + t*(end[1] - start[1])) for t in probes]
    samples = index.query_many(points)
    winner = min(range(len(samples)), key=lambda i: samples[i][0])
    return (*samples[winner], *points[winner])


def _critical_stations(index, element, profile_element, lo, hi, feet, ids, evaluate):
    """Interior extrema on each original planar face or terrain edge."""
    if element["kind"] == profile_element["kind"] == "line":
        return []
    stations = []
    mid = (lo + hi)/2
    for foot in feet:
        if element["kind"] == "line" and profile_element["kind"] == "arc":
            radius = foot.get("support_radius", profile_element["radius"])
            branch = profile_element["branch"]
            gradients = []
            for offset in {foot["lo"], foot["hi"]}:
                x, y = _xy(element, mid, offset)
                _, face = index.query(x, y)
                gx, gy = index.gradient(face)
                gradients.append(gx*math.cos(element["tangent_angle"]) + gy*math.sin(element["tangent_angle"]))
            if foot["lo"] != foot["hi"]:
                p, q = index.edges(ids)
                tangent = np.array([math.cos(element["tangent_angle"]), math.sin(element["tangent_angle"])])
                normal = np.array([tangent[1], -tangent[0]])
                origin = np.asarray(_xy(element, lo))
                ps, qs = (p[:, :2] - origin) @ tangent + lo, (q[:, :2] - origin) @ tangent + lo
                pu, qu = (p[:, :2] - origin) @ normal, (q[:, :2] - origin) @ normal
                for position, (a, b, u0, u1, z0, z1) in enumerate(zip(ps, qs, pu, qu, p[:, 2], q[:, 2])):
                    if position % 256 == 0:
                        _check(index.cancelled)
                    if abs(b - a) < 1e-12:
                        continue
                    m = (z1 - z0)/(b - a)
                    s = profile_element["center_station"] - branch*m*radius/math.hypot(1., m)
                    t = (s - a)/(b - a)
                    if lo < s < hi and 0 <= t <= 1 and foot["lo"] <= u0 + t*(u1 - u0) <= foot["hi"]:
                        stations.append(s)
            for gradient in gradients:
                s = profile_element["center_station"] - branch*gradient*radius/math.hypot(1., gradient)
                if lo < s < hi:
                    stations.append(s)
        elif element["kind"] == "arc" and profile_element["kind"] == "line":
            slope = profile_element["slope"]
            omega = element["sweep_angle"]/element["length"]
            for offset in {foot["lo"], foot["hi"]}:
                x, y = _xy(element, mid, offset)
                _, face = index.query(x, y)
                gx, gy = index.gradient(face)
                radial = element["radius"] + math.copysign(1., element["sweep_angle"])*offset
                amplitude = math.hypot(gx, gy)
                if amplitude:
                    value = -slope/(omega*radial*amplitude)
                    if abs(value) <= 1:
                        phase = math.atan2(-gy, gx)
                        for angle in (math.asin(value) - phase, math.pi - math.asin(value) - phase):
                            stations.extend(s for s in _angle_stations(element, angle) if lo < s < hi)
            if foot["lo"] != foot["hi"] and slope:
                p, q = index.edges(ids)
                center = np.asarray(element["center_xy"])
                for position, (a, b) in enumerate(zip(p, q)):
                    if position % 256 == 0:
                        _check(index.cancelled)
                    direction = b[:2] - a[:2]
                    origin = center - a[:2]
                    cross = origin[0]*direction[1] - origin[1]*direction[0]
                    target = -(b[2] - a[2])*cross*omega/slope
                    amplitude = float(np.linalg.norm(direction))
                    if target < 0 or not amplitude or math.sqrt(target) > amplitude:
                        continue
                    phase = math.atan2(-direction[1], direction[0])
                    for value in {math.sqrt(target)/amplitude, -math.sqrt(target)/amplitude}:
                        for angle in (math.asin(value) - phase, math.pi - math.asin(value) - phase):
                            for s in _angle_stations(element, angle):
                                if not lo < s < hi:
                                    continue
                                unit = np.array([math.cos(angle), math.sin(angle)])
                                den = direction[0]*unit[1] - direction[1]*unit[0]
                                if abs(den) < 1e-15:
                                    continue
                                t = (origin[0]*unit[1] - origin[1]*unit[0])/den
                                hit = a[:2] + t*direction
                                offset = math.copysign(1., omega)*(float(np.linalg.norm(hit - center)) - element["radius"])
                                if 0 <= t <= 1 and foot["lo"] <= offset <= foot["hi"]:
                                    stations.append(s)
        else:
            # Closed culvert floors can follow a vertical arc on a plan arc.
            # Circular pipes use the common geometry's explicit coupled-arc
            # handling, including its existing input error for unsupported data.
            from scipy.optimize import minimize_scalar
            for sign in (-1., 1.):
                result = minimize_scalar(lambda s: sign*evaluate(float(s))["effective_gap"], bounds=(lo, hi), method="bounded",
                    options={"xatol": _ROOT_WIDTH_M/8})
                if lo < result.x < hi:
                    stations.append(float(result.x))
    return stations


def detect_unsupported_ranges(tin, inputs, *, cancelled=None, progress=None):
    """Return neutral scope records for unsupported parts of closed conduits.

    Missing/invalid design profiles are left to the existing calculation
    validation. Missing original terrain is reported as missing terrain; it
    never becomes an automatically excluded interval.
    """
    from .design_profiles import normalize_design_profile
    from .network_alignment import NetworkAlignment
    _check(cancelled)
    networks = inputs.get("networks")
    if networks is None:
        networks = [inputs] if "assets" in inputs and "alignment" in inputs else []
    prepared = []
    for ni, network in enumerate(networks):
        try:
            raw = network["alignment"]
            alignment = NetworkAlignment.from_dict(raw) if isinstance(raw, dict) else raw
            if (not getattr(alignment, "elements", None)
                    or not math.isfinite(alignment.start_station + alignment.end_station)
                    or alignment.end_station <= alignment.start_station
                    or any(e.get("kind") not in {"line", "arc"} or float(e.get("length", 0.)) <= 0
                           for e in alignment.elements)):
                continue
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            continue
        for asset in network.get("assets", []):
            if not _eligible(asset):
                continue
            try:
                profile = normalize_design_profile(asset)
                a, b = float(asset["station_start"]), float(asset["station_end"])
                if (not math.isfinite(a + b) or b <= a or a < profile["station_start"] - 1e-7
                        or b > profile["station_end"] + 1e-7 or a < alignment.start_station - 1e-7
                        or b > alignment.end_station + 1e-7):
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            identity = network.get("network_id") or network.get("route_id") or network.get("source_identity")
            prepared.append((identity, alignment, asset, profile, a, b))
    if not prepared:
        return []
    feedback = _RangeScanProgress(progress, "unsupported_pipe_ranges", "检测管道支承区间", len(prepared))
    index = _OriginalTIN(tin, cancelled)
    result = []
    for ai, (network_id, alignment, asset, profile, start, end) in enumerate(prepared):
        _check(cancelled)
        feedback.select_object(ai, asset)
        feedback.checkpoint(start)
        model = _Feet(asset, profile)
        spans = []
        for pe in alignment.elements:
            for ve in profile["elements"]:
                lo, hi = max(start, pe["station_start"], ve["station_start"]), min(end, pe["station_end"], ve["station_end"])
                if hi <= lo:
                    continue
                _check(cancelled)
                feedback.checkpoint(lo)
                initial_feet = model.at((lo + hi)/2, "right", pe, ve)
                ids = _cell_candidates(index, pe, lo, hi, initial_feet)
                @lru_cache(maxsize=16384)
                def evaluate(station, side="right"):
                    _check(cancelled)
                    worst = None
                    unsupported_pipes = set()
                    feet = model.at(float(station), side, pe, ve)
                    for foot in feet:
                        try:
                            ground, face, x, y = _ground_under(index, pe, station, foot, ids)
                        except UnsupportedPipeTerrainError as error:
                            for row in error.diagnostics:
                                row.update(asset_id=asset["asset_id"],route_id=network_id,station=float(station),
                                    message=str(error))
                            raise
                        gap = foot["bottom"] - ground
                        rounding = 256*max(math.ulp(ground), math.ulp(foot["bottom"]), math.ulp(1.))
                        value = {"effective_gap": gap - rounding, "gap_m": gap, "station": station,
                            "pipe_index": foot["pipe_index"], "ground_elevation_m": ground, "support_elevation_m": foot["bottom"],
                            "x": x, "y": y, "face_index": face}
                        if value["effective_gap"] > 0 and foot["pipe_index"] is not None:
                            unsupported_pipes.add(foot["pipe_index"])
                        if worst is None or value["effective_gap"] > worst["effective_gap"]:
                            worst = value
                    worst["unsupported_pipe_indices"] = sorted(unsupported_pipes)
                    return worst
                events = _events(index, pe, lo, hi, initial_feet, ids)
                events += [lo + i*2. for i in range(1, math.ceil((hi - lo)/2.)) if lo + i*2. < hi]
                events = sorted(set(events))
                critical = []
                for left, right in zip(events, events[1:]):
                    _check(cancelled)
                    if right - left < 1e-10:
                        continue
                    mid = (left + right)/2
                    feedback.checkpoint(mid)
                    evaluate(mid)  # Also exposes a terrain hole between valid edges.
                    feet = model.at(mid, "right", pe, ve)
                    critical += _critical_stations(index, pe, ve, left, right, feet, ids, evaluate)
                events = sorted(set([*events, *critical]))
                def root(left, right, fl, fr):
                    if fl == 0:
                        return left
                    if fr == 0:
                        return right
                    while right - left > _ROOT_WIDTH_M:
                        mid = (left + right)/2
                        fm = evaluate(mid)["effective_gap"]
                        if (fm > 0) == (fl > 0):
                            left, fl = mid, fm
                        else:
                            right, fr = mid, fm
                    return left if fl <= 0 else right
                for left, right in zip(events, events[1:]):
                    _check(cancelled)
                    if right - left < 1e-10:
                        continue
                    feedback.checkpoint(left)
                    vl, vr = evaluate(left), evaluate(right, "left")
                    fl, fr = vl["effective_gap"], vr["effective_gap"]
                    if fl > 0 and fr > 0:
                        spans.append((left, right, [vl, vr]))
                    elif (fl > 0) != (fr > 0):
                        boundary = root(left, right, fl, fr)
                        spans.append((left, boundary, [vl]) if fl > 0 else (boundary, right, [vr]))
        merged = []
        for left, right, samples in sorted(spans, key=lambda r: r[0]):
            if right - left <= 1e-10:
                continue
            if merged and left <= merged[-1][1] + 1e-8:
                a, b, old = merged[-1]
                merged[-1] = a, max(b, right), old + samples
            else:
                merged.append((left, right, samples))
        for left, right, samples in merged:
            peak = max(samples, key=lambda x: x["gap_m"])
            result.append({"network_id": network_id, "asset_id": asset["asset_id"], "name": asset.get("name", ""),
                "station_start": left, "station_end": right, "length_m": right - left, "reason": "管道悬空",
                "pipe_indices": sorted({p for s in samples for p in s["unsupported_pipe_indices"]}),
                "maximum_support_gap_m": peak["gap_m"], "maximum_gap_station_m": peak["station"],
                "maximum_gap_sample": {k: v for k, v in peak.items() if k != "effective_gap"},
                "station_boundary_tolerance_m": STATION_TOLERANCE_M,
                "source_axis_and_terrain_preserved": True})
    _check(cancelled)
    feedback.finish()
    return result
