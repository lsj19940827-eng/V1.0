"""Locate route intervals where the original survey cannot close a section."""
from __future__ import annotations

from bisect import bisect_right
from functools import lru_cache
import math

import numpy as np
import shapely
from shapely.strtree import STRtree

from .unsupported_pipe_ranges import (
    _CLOSED, _Feet, _OriginalTIN, _RangeScanProgress, _angle_stations, _cell_candidates,
    _eligible, _ground_under, _xy, UnsupportedPipeTerrainError,
)

BOUNDARY_TOLERANCE_M = .001
MAX_BOUNDARY_PROBE_SPACING_M = 2.
_DAYLIGHT_MESSAGES = (
    "边坡在有效地形范围内未与地面相交",
    "边坡超出有效地形范围",
    "马道超出有效地形范围",
    "填筑边坡在有效地形内未接地",
    "填筑边坡超出有效地形",
    "基岩边坡在有效地形范围内未与基覆界面或地面相交",
    "覆盖层边坡在有效地形范围内未与地面相交",
    "指定偏距超出有效地形范围",
    "实际地形缺测，不能判别填挖工况",
)


def is_unmeasured_terrain_error(error):
    """Recognize absent terrain and open daylight traces in section evaluation."""
    return getattr(error, "code", "") == "section_terrain_unavailable" or any(
        message in str(error) for message in _DAYLIGHT_MESSAGES
    )


def _check(cancelled):
    if cancelled and cancelled():
        raise InterruptedError("地形覆盖区间检测已取消")


def _cell_bounds(element, lo, hi, width):
    from .network_section_calculator import _part_plan_bounds

    bounds = np.asarray(_part_plan_bounds(element, lo, hi, -width, width))
    rounding = max(1., float(np.max(np.abs(bounds)))) * np.finfo(float).eps * 16
    return bounds + rounding * np.array([-1., -1., 1., 1.])


class _SurveyBoundary:
    def __init__(self, tin):
        faces = np.asarray(tin.triangles)
        edges = faces[:, ((0, 1), (1, 2), (2, 0))].reshape(-1, 2)
        edges.sort(axis=1)
        ids, degree = np.unique(edges, axis=0, return_counts=True)
        points = np.asarray(tin.points)
        self.origin = points[0, :2]
        self.edges = points[ids[degree == 1], :2] - self.origin
        self.tree = STRtree(shapely.linestrings(self.edges))
        self.low = float(points[:, 2].min())
        self.high = float(points[:, 2].max())
        self.extent = points[:, :2].min(axis=0), points[:, :2].max(axis=0)

    def full_width(self, element, lo, hi):
        a, b = self.extent
        corners = np.array([(a[0], a[1]), (a[0], b[1]), (b[0], a[1]), (b[0], b[1])])
        if element["kind"] == "arc":
            return float(np.linalg.norm(corners-element["center_xy"], axis=1).max()) + element["radius"] + 1.
        return float(np.linalg.norm(corners-_xy(element, (lo+hi)/2), axis=1).max()) + 1.

    def matching_edges(self, bounds):
        return self.tree.query(shapely.box(*(bounds - np.tile(self.origin, 2))))

    def spans(self, element, lo, hi, width, fixed_offsets):
        """Return projected naked-edge intervals and topology events."""
        chosen = self.matching_edges(_cell_bounds(element, lo, hi, width))
        if not len(chosen):
            return [], []
        if element["kind"] == "line":
            theta = element["tangent_angle"]
            tangent = np.array([math.cos(theta), math.sin(theta)])
            normal = np.array([tangent[1], -tangent[0]])
            points = self.edges[chosen] - (np.asarray(_xy(element, lo)) - self.origin)
            lateral = points @ normal
            length = points @ tangent
            u = lateral[:, 0]
            du = lateral[:, 1] - u
            nonzero = np.abs(du) > 1e-15
            with np.errstate(divide="ignore", invalid="ignore"):
                left = np.where(nonzero, (-width-u)/du, -np.inf)
                right = np.where(nonzero, (width-u)/du, np.inf)
            starts = np.maximum(0., np.minimum(left, right))
            ends = np.minimum(1., np.maximum(left, right))
            hits = (starts <= ends) & (nonzero | (np.abs(u) <= width))
            x = length[hits, 0]
            dx = length[hits, 1] - x
            a = x + starts[hits]*dx
            b = x + ends[hits]*dx
            first = np.maximum(lo, lo + np.minimum(a, b))
            last = np.minimum(hi, lo + np.maximum(a, b))
            spans = [(float(a), float(b)) for a, b in zip(first, last) if b >= a]
            events = [s for span in spans for s in span]
            for offset in fixed_offsets:
                with np.errstate(divide="ignore", invalid="ignore"):
                    ratio = (offset-u)/du
                cross = (0. <= ratio) & (ratio <= 1.)
                distances = lo + length[cross, 0] + ratio[cross]*np.diff(length[cross], axis=1)[:, 0]
                events.extend(float(s) for s in distances if lo <= s <= hi)
            return spans, events

        center = np.asarray(element["center_xy"]) - self.origin
        outer = element["radius"] + width
        inner = max(0., element["radius"] - width)
        points = self.edges[chosen] - center
        vertices = points.reshape(-1, 2)
        u = points[:, 0]
        d = points[:, 1] - u
        a, b = np.sum(d*d, axis=1), 2*np.sum(u*d, axis=1)
        turn_sign = math.copysign(1., element["sweep_angle"])
        radii = {inner, outer, *(abs(element["radius"]+turn_sign*u) for u in fixed_offsets)}
        for radius in radii:
            c = np.sum(u*u, axis=1) - radius*radius
            discriminant = b*b - 4*a*c
            good = (a > 0.) & (discriminant >= 0.)
            for sign in (-1, 1):
                root = (-b[good] + sign*np.sqrt(discriminant[good])) / (2*a[good])
                valid = (0. <= root) & (root <= 1.)
                vertices = np.vstack((vertices, u[good][valid] + d[good][valid]*root[valid, None]))
        angles = np.arctan2(vertices[:, 1], vertices[:, 0])
        if width >= element["radius"]:
            angles = np.r_[angles, angles+math.pi]
        events = [s for a in angles for s in _angle_stations(element, float(a)) if lo <= s <= hi]
        # Arcs are short. Probe the entire curved cell if a naked edge is
        # near it, including edges spanning the cell's entire angular range.
        return [(lo, hi)], events


def _search_width(boundary, evaluator, asset, part, element, profile_element, lo, hi):
    """Bound all ordinary cut/fill toes by geometry and surveyed elevation limits."""
    from .section_geometry import add_foundation_materials, construction_floor_steps, section_structure, slope_grades
    from .construction_rules import effective_construction
    from .layered_excavation import layer_config

    construction = effective_construction(asset)
    section = asset.get("section") or {}
    if (profile_element is not None and profile_element["kind"] != "line"
            or asset.get("section_scheme_terrain_variants") or asset.get("section_scheme_selectors")
            or section.get("discrete_components") or construction.get("excavation_base_mode") == "offset"
            or layer_config(construction) is not None
            or construction.get("target_mode") == "finished_profile"):
        return boundary.full_width(element, lo, hi), (0.,), False
    mid = (lo + hi)/2
    _, _, curvature = evaluator.frame(part, mid)
    z, slope = evaluator.profile_at(part["asset_index"], mid)
    structure = section_structure(asset, elevation=z, slope=slope, arc_segments=evaluator.arc_segments,
                                  station=mid, plan_curvature=curvature)
    if structure.get("dedicated_construction") or "retaining_wall" in structure.get("component_regions", {}):
        return boundary.full_width(element, lo, hi), (0.,), False
    structure = add_foundation_materials(structure, construction, arc_segments=evaluator.arc_segments)
    x0, z0, x1, z1 = structure["occupancy"].bounds
    seat = construction.get("pipe_seat") or construction.get("pipe_support") or {}
    pipe_outer = construction.get("working_space_reference") == "pipe_outer" or (
        seat.get("enabled", True) and seat.get("bottom_width_mode") == "trench_bottom"
    )
    left, _, right, _ = structure["outer"].bounds if pipe_outer and structure.get("pipes") else (x0, z0, x1, z1)
    offsets = {0.}
    offsets.update(p.get("outer_bottom_offset", p["offset"]) for p in structure.get("pipes", []))
    limit = max(abs(x0), abs(x1))
    rises = [z0, z1+float(construction.get("final_cover_depth") or 0.)]
    for x, h in construction_floor_steps(construction, structure) or []:
        limit = max(abs(x), limit)
        offsets.add(x)
        rises.append(h)
    variation = abs(slope)*(hi-lo)/2
    low, high = min(rises)-variation, max(rises)+variation
    sides = []
    for side, edge, direction in (("left", left, -1), ("right", right, 1)):
        margin = float(construction.get("working_space_"+side) or 0.) + float(
            construction.get("bank_top_width_"+side) or 0.
        )
        offsets.add(edge+direction*margin)
        excavation = slope_grades(construction, side)
        embankment = (slope_grades(construction, side, filling=True)
                      if construction.get("bank_slope_"+side) is not None
                      or construction.get("bank_stages_"+side) else [])
        sides.append((margin, excavation, embankment))

    def width_for_terrain(terrain_low, terrain_high):
        def reach(grades, relief):
            return max((grade.ratio for grade in grades), default=0.)*max(0., relief) + sum(
                grade.berm_width for grade in grades
            )
        return limit + max(margin + max(reach(cut, terrain_high-low), reach(fill, high-terrain_low))
                           for margin, cut, fill in sides) + .05

    width = width_for_terrain(boundary.low, boundary.high)
    window = _cell_bounds(element, lo, hi, width)
    if len(boundary.matching_edges(window)):
        extrema = evaluator.interp.plan_elevation_bounds(window)
        if extrema is not None:
            width = min(width, width_for_terrain(*extrema))
    return width, offsets, True


def _probe_stations(lo, hi, spans, events):
    """Include the topology events and constrain spacing near their influence."""
    merged = []
    for left, right in sorted(spans):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    stations = {lo, hi, *events}
    for a, b in merged:
        count = max(1, math.ceil((b-a)/MAX_BOUNDARY_PROBE_SPACING_M))
        stations.update(a + (b-a)*i/count for i in range(1, count))
    ordered = sorted(float(s) for s in stations)
    stations.update(a + (b-a)/2 for a, b in zip(ordered, ordered[1:]))
    return sorted(stations)


def detect_unmeasured_terrain_ranges(tin, inputs, *, accuracy=None, cancelled=None, progress=None,
                                     collect_deferrals=False):
    """Probe closed conduits with the same original-TIN section evaluator as calculation."""
    from .dedicated_structure_geometry import dedicated_break_stations
    from .network_section_calculator import _Sections, _curve_cut_stations, _profile
    from .network_section_projection import Catalog
    from .workbench_calculator import DEFAULT_ACCURACY, prepare_workbench_inputs

    if tin is None:
        return []
    networks = inputs.get("networks", [inputs])
    if not any(a.get("enabled", True) and a.get("section_type") in _CLOSED
               for n in networks for a in n.get("assets", [])):
        return []
    _check(cancelled)
    _, normalized, _ = prepare_workbench_inputs(tin, inputs, collect_deferrals=collect_deferrals)
    assets = normalized["assets"]
    eligible = [a for a in assets if a["section_type"] in _CLOSED]
    if not eligible:
        return []
    feedback = _RangeScanProgress(progress, "terrain_coverage", "检查地形覆盖区间", len(eligible))
    settings = {**DEFAULT_ACCURACY, **(accuracy or {})}
    alignment = normalized["alignment"]
    catalog = Catalog(alignment, eligible, alignment.get_xy_at_station(alignment.start_station),
                      dict.fromkeys((a["asset_id"] for a in eligible), 0.))
    evaluator = _Sections(tin, alignment, eligible, [_profile(a, normalized) for a in eligible],
                          settings["arc_segments"])
    evaluator.catalog = catalog
    _check(cancelled)
    boundary = _SurveyBoundary(tin)
    support_index = None
    found = []
    for asset_index, asset in enumerate(eligible):
        _check(cancelled)
        asset_id = asset["asset_id"]
        offset = asset["station_offset"]
        feedback.select_object(asset_index, asset)
        feedback.checkpoint(asset["station_start"] - offset)
        step = float(settings["profile_step"])
        construction_breaks = dedicated_break_stations(asset)
        profile = asset.get("design_profile")
        if profile:
            from .design_profiles import normalize_design_profile
            profile = normalize_design_profile(profile)
        feet_model = _Feet(asset, profile) if profile and _eligible(asset) else None
        intervals = []
        for part in catalog._parts_by_asset[asset_id]:
            element = alignment.elements[part["primitive_id"]]
            lower, upper = part["station_start"], part["station_end"]
            positions = sorted({lower, upper, *(s for s in (*evaluator.profile_knots[asset_id], *construction_breaks)
                                                 if lower < s < upper)})
            curve_stations = ([s for s, _ in _curve_cut_stations(element, step) if lower < s < upper]
                              if element["kind"] == "arc" else [])
            for lo, hi in zip(positions, positions[1:]):
                _check(cancelled)
                mid = (lo+hi)/2
                feedback.checkpoint(mid - offset)
                ve = profile["elements"][bisect_right(profile.starts, mid)-1] if profile else None
                width, offsets, bounded = _search_width(boundary, evaluator, asset, part, element, ve, lo, hi)
                risk, events = boundary.spans(element, lo, hi, width, offsets)
                if not risk and bounded:
                    # With no naked edge in the swept envelope, its middle
                    # identifies the entire cell as surveyed or uncovered.
                    if not evaluator.interp.covers_plan_point(_xy(element, mid)):
                        intervals.append((lo, hi))
                    continue

                @lru_cache(maxsize=4096)
                def known(station):
                    nonlocal support_index
                    _check(cancelled)
                    feedback.checkpoint(station - offset)
                    side = "left" if station == hi else "right"
                    try:
                        evaluator.exact(part, station, side)
                        return True
                    except ValueError as error:
                        if not is_unmeasured_terrain_error(error):
                            raise
                    if feet_model is not None:
                        if support_index is None:
                            support_index = _OriginalTIN(tin, cancelled)
                        feet = feet_model.at(station, side, element, ve)
                        faces = _cell_candidates(support_index, element, station, station, feet)
                        try:
                            ground = [_ground_under(support_index, element, station, foot, faces)[0]
                                      for foot in feet]
                        except UnsupportedPipeTerrainError:
                            return False
                        # A known positive support gap belongs to the original
                        # suspension detector, even if a fill toe also escapes.
                        if any(foot["bottom"] - height > 256*max(math.ulp(height), math.ulp(foot["bottom"]),
                                                                  math.ulp(1.))
                               for height, foot in zip(ground, feet)):
                            return True
                    return False

                first, last = math.ceil((lo-offset)/step), math.floor((hi-offset)/step)
                production_grid = (offset+i*step for i in range(first, last+1))
                events.extend(s for s in (*production_grid, *curve_stations) if lo < s < hi)
                stations = _probe_stations(lo, hi, risk, events)
                statuses = [known(s) for s in stations]
                start = lo if not statuses[0] else None
                for left, right, left_ok, right_ok in zip(stations, stations[1:], statuses, statuses[1:]):
                    if left_ok == right_ok:
                        continue
                    while right-left > BOUNDARY_TOLERANCE_M/2:
                        center = (left+right)/2
                        if known(center) == left_ok:
                            left = center
                        else:
                            right = center
                    if right_ok:
                        intervals.append((start, min(hi, right+BOUNDARY_TOLERANCE_M/4)))
                        start = None
                    else:
                        start = max(lo, left-BOUNDARY_TOLERANCE_M/4)
                if start is not None:
                    intervals.append((start, hi))
        merged = []
        for a, b in sorted(intervals):
            if b <= a:
                continue
            if merged and a <= merged[-1][1]+1e-9:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        found.extend({
            "network_id": asset["route_id"], "asset_id": asset["original_asset_id"],
            "name": asset.get("name", ""), "station_start": a-offset, "station_end": b-offset,
            "length_m": b-a, "reason": "地形缺测或施工断面超出有效地形",
            "station_boundary_tolerance_m": BOUNDARY_TOLERANCE_M,
        } for a, b in merged)
    _check(cancelled)
    feedback.finish()
    return found
