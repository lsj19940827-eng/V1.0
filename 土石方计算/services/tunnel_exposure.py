"""Locate the source-chainage spans where an underground section daylights."""
from functools import lru_cache
import math

import numpy as np
from shapely.geometry import box

from .construction_rules import effective_construction
from .dedicated_structure_geometry import TUNNEL_TYPES, dedicated_break_stations
from .section_geometry import section_structure
from .network_section_calculator import (
    _Sections, _cancel, _curve_cut_stations, _profile, _terrain_knots,
)
from .network_section_projection import Catalog
from .workbench_scope import AssetDataPending


def _crest_bound(evaluator, ai, part_start, part_end, crest, profile_arc):
    start_z, start_slope = evaluator.profile_at(ai, part_start, "right")
    end_z, end_slope = evaluator.profile_at(ai, part_end, "left")
    max_z = max(start_z, end_z)
    if profile_arc and part_start < profile_arc["center_station"] < part_end:
        crest_z = profile_arc["center_elevation"] + profile_arc["branch"]*profile_arc["radius"]
        max_z = max(max_z, crest_z)
    # Each span follows one line or circular grade element. Its maximum
    # absolute slope occurs at an endpoint, including the one-sided limits.
    return max_z + max(0., crest)*math.hypot(1., max(abs(start_slope), abs(end_slope))) + 1e-6


def _retained_boundary(probe, left, right, left_exposed):
    # Keep a verified buried section at the boundary of each retained span.
    while right-left > 1e-5:
        middle = left+(right-left)/2
        exposed = probe(middle, "right")
        if exposed is None:
            return right if left_exposed else left
        if exposed == left_exposed:
            left = middle
        else:
            right = middle
    return right if left_exposed else left


class _StraightTunnelProbe:
    """Certify sections on a static straight sweep against original TIN faces.

    All terrain and contour breaks still contribute. Canonical shared edge
    identities certify continuous coverage. Uncertain intersections and signs
    fall back to the ordinary section cutter.
    """

    def __init__(self, structure, construction):
        outline = structure["tunnel_excavation_outline"]
        self.contour_u, self.contour_z = np.asarray(outline.exterior.coords).T
        u1, u2 = self.contour_u[:-1], self.contour_u[1:]
        self.edge_low, self.edge_high = np.minimum(u1, u2), np.maximum(u1, u2)
        self.edge_z = np.where(u1 <= u2, self.contour_z[:-1], self.contour_z[1:])
        widths = self.edge_high-self.edge_low
        rises = np.where(u1 <= u2, np.diff(self.contour_z), -np.diff(self.contour_z))
        self.edge_slope = np.divide(rises, widths, out=np.zeros_like(rises), where=widths > 0.)
        left, _, right, _ = structure["occupancy"].bounds
        left = min(outline.bounds[0], left-float(construction.get("working_space_left", 0))
                   -float(construction.get("bank_top_width_left", 0)))
        right = max(outline.bounds[2], right+float(construction.get("working_space_right", 0))
                    +float(construction.get("bank_top_width_right", 0)))
        margin = max(.5, (right-left)/4)
        self.left, self.right = left-margin, right+margin

    def faces(self, evaluator, part, element, start, end):
        index = evaluator.interp._get_section_index()
        first, tangent, _ = evaluator.frame(part, start)
        last, _, _ = evaluator.frame(part, end)
        normal = np.array([tangent[1], -tangent[0]])
        corners = np.array([first+self.left*normal, first+self.right*normal,
                            last+self.left*normal, last+self.right*normal]) + evaluator.catalog.origin_xy
        bounds = [*corners.min(axis=0), *corners.max(axis=0)]
        tolerance = 64*np.spacing(max(1., *map(abs, bounds)))
        x0, y0, x1, y1 = np.asarray(bounds)-np.tile(index._origin, 2)
        ids = index._tree.query(box(x0-tolerance, y0-tolerance, x1+tolerance, y1+tolerance))
        if not len(ids) or len(ids) > 1024:
            return None
        try:
            index._check_topology(ids)
        except ValueError:
            return None
        triangles = index._triangles[ids].astype(np.int64, copy=False)
        vertices = index._points[triangles]
        basis = np.array([tangent, normal])
        origin = np.asarray(element["start_xy"])-index._origin
        station, lateral = ((vertices[:, :, :2]-origin) @ basis.T).transpose(2, 0, 1)
        height = vertices[:, :, 2]
        ds = np.roll(station, -1, axis=1)-station
        du = np.roll(lateral, -1, axis=1)-lateral
        dz = np.roll(height, -1, axis=1)-height
        second = np.roll(triangles, -1, axis=1)
        edge_ids = np.minimum(triangles, second)*len(index._points)+np.maximum(triangles, second)
        determinant = ds[:, 0]*du[:, 1]-ds[:, 1]*du[:, 0]
        # Ill-conditioned planes belong to the exact fallback; their slopes
        # would otherwise amplify the world-coordinate rounding uncertainty.
        scale = np.max(np.abs(ds)+np.abs(du), axis=1)
        if np.any(np.abs(determinant) <= tolerance*scale):
            return None
        vertical_gradient = (np.abs(dz[:, 0]*du[:, 1]-dz[:, 1]*du[:, 0])
                             + np.abs(ds[:, 0]*dz[:, 1]-ds[:, 1]*dz[:, 0]))/np.abs(determinant)
        end_xy = np.asarray(element["end_xy"])-element["start_xy"]
        ds_route, du_route = basis @ end_xy / element["length"]
        return (station, lateral, height, ds, du, dz, edge_ids, ds_route, du_route,
                tolerance, float(np.max(vertical_gradient)))

    def status(self, faces, along, z, slope):
        station, lateral, height, ds, du, dz, edge_ids, ds_route, du_route, tolerance, gradient = faces
        if not math.isfinite(slope) or abs(slope) > 1e4:
            return None
        ds_start = along*ds_route-station
        if np.any(np.abs(ds_start) <= tolerance):
            return None
        end = ds_start-ds
        triangle, edge = np.nonzero((ds_start > 0.) != (end > 0.))
        if not len(triangle):
            return None
        fraction = ds_start[triangle, edge]/ds[triangle, edge]
        u = (lateral[triangle, edge]+fraction*du[triangle, edge]-along*du_route).reshape(-1, 2)
        h = (height[triangle, edge]+fraction*dz[triangle, edge]).reshape(-1, 2)
        keys = edge_ids[triangle, edge].reshape(-1, 2)
        direction = np.argsort(u, axis=1)
        u, h, keys = (np.take_along_axis(v, direction, axis=1) for v in (u, h, keys))
        hits = (u[:, 0] < self.right) & (u[:, 1] > self.left)
        u, h, keys = u[hits], h[hits], keys[hits]
        if not len(u):
            return None
        order = np.argsort(u[:, 0]); u, h, keys = u[order], h[order], keys[order]
        if (u[0, 0] > self.left-tolerance or u[-1, 1] < self.right+tolerance
                or np.any(u[:, 1]-u[:, 0] <= tolerance) or np.any(keys[:-1, 1] != keys[1:, 0])
                or np.any(np.abs(u[:-1, 1]-u[1:, 0]) > tolerance)
                or np.any(np.abs(h[:-1, 1]-h[1:, 0]) > 1e-10)):
            return None
        offsets = np.r_[u[:, 0], u[-1, 1]]
        elevations = np.r_[h[:, 0], h[-1, 1]]
        factor = math.hypot(1., slope)
        threshold = 1e-6
        # Continuous linear faces give a conservative error bound when the
        # route frame and input vertex coordinates round in world XY.
        vertical_rounding = 64*np.spacing(max(1., abs(z), np.abs(elevations).max()))
        error = max(vertical_rounding, tolerance*(1.+gradient)*8.)
        difference = z + factor*self.contour_z - np.interp(self.contour_u, offsets, elevations)
        if difference.max() > threshold+error:
            return True

        ux_padding = tolerance*(1.+np.max(np.abs(du[triangle, edge]/ds[triangle, edge])))*8.
        zx_padding = error+gradient*ux_padding
        relevant = ((offsets > self.contour_u.min()-ux_padding)
                    & (offsets < self.contour_u.max()+ux_padding))
        ground_lo, ground_hi = offsets[relevant, None]-ux_padding, offsets[relevant, None]+ux_padding
        clip_lo, clip_hi = np.maximum(ground_lo, self.edge_low), np.minimum(ground_hi, self.edge_high)
        left_z = self.edge_z+self.edge_slope*(clip_lo-self.edge_low)
        right_z = self.edge_z+self.edge_slope*(clip_hi-self.edge_low)
        reference_z = elevations[relevant, None]
        lower_gap = z + factor*np.minimum(left_z, right_z)-reference_z
        upper_gap = z + factor*np.maximum(left_z, right_z)-reference_z
        if np.any((ground_lo >= self.edge_low) & (ground_hi <= self.edge_high) & (lower_gap > threshold+zx_padding)):
            return True
        if difference.max() <= threshold-error and not np.any((clip_lo <= clip_hi) & (upper_gap > threshold-zx_padding)):
            return False
        return None


def find_tunnel_exposure(tin, network, settings, *, cancelled=None, progress=None):
    assets = [asset for asset in network["assets"] if asset["section_type"] in TUNNEL_TYPES]
    if not assets:
        return []
    alignment = network["alignment"]
    profiles = [_profile(asset, network) for asset in assets]
    evaluator = _Sections(tin, alignment, assets, profiles, int(settings["arc_segments"]))
    origin = alignment.get_xy_at_station(alignment.start_station)
    catalog = Catalog(alignment, assets, origin, dict.fromkeys((a["asset_id"] for a in assets), 0.))
    evaluator.catalog = catalog
    spans = []
    profile_step = float(settings["profile_step"])
    if not math.isfinite(profile_step) or profile_step <= 0:
        raise ValueError("断面间距须为正数")
    probe_step = min(profile_step, 10.)

    for ai, asset in enumerate(assets):
        _cancel(cancelled)
        if progress:
            name = asset.get("name") or asset["asset_id"]
            progress("tunnel_exposure", ai/len(assets), f"核查隧洞露顶范围 · {name}")
        structure = section_structure(asset, elevation=0., slope=0., arc_segments=evaluator.arc_segments)
        outline = structure["tunnel_excavation_outline"]
        crest = outline.bounds[3]
        polygons = [outline] if outline.geom_type == "Polygon" else outline.geoms
        offsets = sorted({0., *(round(x, 9) for polygon in polygons for x, _ in polygon.exterior.coords)})
        offset = asset.get("station_offset", 0.)
        breaks = set(evaluator.profile_positions[ai]) | set(dedicated_break_stations(asset))
        profile_arcs = [e for e in (asset.get("design_profile") or {}).get("elements", []) if e["kind"] == "arc"]
        terrain_variants = bool(asset.get("section_scheme_terrain_variants") or asset.get("section_scheme_selectors"))
        construction = effective_construction(asset)
        straight_probe = (_StraightTunnelProbe(structure, construction)
                          if (outline.geom_type == "Polygon" and not terrain_variants
                              and not asset["section"].get("discrete_components")
                              and construction.get("floor_steps") is None) else None)
        for part in catalog._parts_by_asset.get(asset["asset_id"], []):
            start, end = part["station_start"], part["station_end"]
            element = alignment.elements[part["primitive_id"]]
            anchors = {start, end, *(s for s in breaks if start < s < end)}
            for step in {probe_step, profile_step}:
                first, last = math.ceil((start-offset)/step), math.floor((end-offset)/step)
                anchors.update(s for i in range(first, last+1) if start < (s := offset+i*step) < end)
            curved = element["kind"] == "arc"
            if curved:
                anchors.update(s for s, _ in _curve_cut_stations(element, profile_step) if start < s < end)
            @lru_cache(maxsize=128)
            def probe(station, side):
                _cancel(cancelled)
                try:
                    return evaluator.workbench_exact(part, station, side, tunnel_probe=True)
                except AssetDataPending as error:
                    if error.code != "section_terrain_unavailable":
                        raise
                    return None

            ordered = sorted(anchors)
            for start_span, end_span in zip(ordered, ordered[1:]):
                _cancel(cancelled)
                profile_arc = next((arc for arc in profile_arcs
                                    if arc["station_start"] <= start_span < arc["station_end"]), None)
                crest_bound = None if terrain_variants else _crest_bound(
                    evaluator, ai, start_span, end_span, crest, profile_arc)
                events = _terrain_knots(evaluator, dict(part, station_start=start_span, station_end=end_span),
                                        offsets=offsets, below_elevation=crest_bound)
                if events is None:
                    continue
                knots = [start_span, *events, end_span]
                if curved or profile_arc or terrain_variants:
                    knots = sorted({*knots, *(a+(b-a)/2 for a, b in zip(knots, knots[1:]))})
                fast_faces = (straight_probe.faces(evaluator, part, element, start_span, end_span)
                              if straight_probe and not curved and not profile_arc else None)

                def station_status(station, side):
                    if fast_faces is not None:
                        z, slope = evaluator.profile_at(ai, station, side)
                        exposed = straight_probe.status(fast_faces, station-element["station_start"], z, slope)
                        if exposed is not None:
                            return exposed
                    return probe(station, side)

                before = station_status(knots[0], "right")
                for left, right in zip(knots, knots[1:]):
                    side = "left" if right == end or right in breaks else "right"
                    left_state, after = before, station_status(right, side)
                    before = after
                    if left_state is None or after is None or not (left_state or after):
                        continue
                    if left_state != after:
                        boundary = _retained_boundary(probe, left, right, left_state)
                        left, right = (left, boundary) if left_state else (boundary, right)
                    if right-left <= 1e-7:
                        continue
                    start_station, end_station = left-offset, right-offset
                    if (spans and spans[-1]["asset_id"] == asset["original_asset_id"]
                            and spans[-1]["route_id"] == asset["route_id"]
                            and abs(spans[-1]["station_end"]-start_station) <= 1e-7):
                        spans[-1]["station_end"] = end_station
                    else:
                        spans.append({"asset_id": asset["original_asset_id"], "route_id": asset["route_id"],
                                      "station_start": start_station, "station_end": end_station})
    return spans
