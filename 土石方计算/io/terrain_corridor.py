"""Scope large survey imports to a buffered, surveyed construction alignment."""
from collections import Counter
import hashlib
import math

import numpy as np
import shapely
from shapely.geometry import LineString, Point
from shapely.prepared import prep


def automatic_terrain_corridor(path, networks):
    """Use a bounded source read for large drawings when a real route is available."""
    limits = {".dwg": 64 * 1024**2, ".dxf": 128 * 1024**2}
    limit = limits.get(path.suffix.lower())
    if limit is None or not path.is_file() or path.stat().st_size < limit:
        return None
    scope = route_corridor_for_networks(networks)
    if scope is not None:
        scope["automatic"] = True
    return scope


def route_corridor_for_networks(networks, previous=None):
    """Recreate the required footprint from live geometry using the saved policy."""
    lines = []
    for network in networks:
        alignment = network.get("alignment")
        if not alignment or network.get("test_only"):
            continue
        elements = alignment["elements"] if isinstance(alignment, dict) else alignment.elements
        for element in elements:
            if element["kind"] == "line":
                lines.append([list(element["start_xy"]), list(element["end_xy"])])
                continue
            # Max 2 m along the curve and max 0.10 m sagitta.
            radius, sweep = element["radius"], element["sweep_angle"]
            max_angle = 4 * math.asin(min(1., math.sqrt(.10 / (2 * radius))))
            count = max(1, math.ceil(max(element["length"] / 2., abs(sweep) / max_angle)))
            angles = np.linspace(element["start_angle"], element["start_angle"] + sweep, count + 1)
            xy = np.asarray(element["center_xy"]) + radius * np.column_stack((np.cos(angles), np.sin(angles)))
            lines.append(xy.tolist())
    if lines:
        defaults = {"half_width_m": 150., "curve_margin_m": 1., "constant_z_xy_tolerance_m": .05}
        return {**(previous if previous is not None else defaults), "paths": lines}
    return None


def _lines(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type == "LineString":
        yield geometry
    elif geometry.geom_type in ("MultiLineString", "GeometryCollection"):
        for part in geometry.geoms:
            yield from _lines(part)


class TerrainCorridor:
    """Retain full measured XYZ and trace contour fragments to the original handles."""

    def __init__(self, options):
        self.width = float(options["half_width_m"])
        self.margin = float(options.get("curve_margin_m", 0.))
        self.tolerance = float(options.get("constant_z_xy_tolerance_m", 0.))
        if (not all(math.isfinite(value) for value in (self.width, self.margin, self.tolerance))
                or self.width <= 0 or self.margin < 0 or self.tolerance < 0):
            raise ValueError("地形施工走廊宽度或平面简化容差无效")
        paths = [LineString(path) for path in options["paths"]]
        if not paths or any(not np.isfinite(path.coords).all() or path.length <= 0 for path in paths):
            raise ValueError("地形施工走廊缺少有效工程路线")
        self.geometry = shapely.union_all([path.buffer(self.width + self.margin) for path in paths])
        self.prepared = prep(self.geometry)
        self.bounds = self.geometry.bounds
        self.counts = Counter()

    def select(self, source):
        self.counts["original_" + source["kind"] + "_entities"] += 1
        points = source["points"]
        if source["kind"] == "point":
            x, y, _ = points[0]
            xmin, ymin, xmax, ymax = self.bounds
            if xmin <= x <= xmax and ymin <= y <= ymax and self.prepared.covers(Point(x, y)):
                self.counts["retained_measured_points"] += 1
                yield source
            return
        vertices = np.asarray(points, dtype=np.float64)
        self.counts["original_contour_vertices"] += len(vertices)
        geometry = LineString(vertices[:, :2])
        if not self.prepared.intersects(geometry):
            return
        self.counts["intersecting_contour_entities"] += 1
        # Variable elevations cannot safely be recreated from a single contour Z.
        if not np.all(vertices[:, 2] == vertices[0, 2]):
            self.counts["variable_z_curves_kept_whole"] += 1
            self.counts["retained_contour_vertices"] += len(vertices)
            yield source
            return
        clipped = not self.prepared.covers(geometry)
        scope = geometry.intersection(self.geometry) if clipped else geometry
        self.counts["clipped_contour_entities"] += clipped
        for index, part in enumerate(_lines(scope), 1):
            compact = part.simplify(self.tolerance, preserve_topology=True) if self.tolerance else part
            self.counts["retained_contour_vertices"] += len(compact.coords)
            self.counts["simplified_contour_vertices_removed"] += len(part.coords) - len(compact.coords)
            if not clipped and compact.equals_exact(geometry, 0.):
                yield source
                continue
            xyz = [[x, y, float(vertices[0, 2])] for x, y in compact.coords]
            yield {**source, "fragment_id": f"/corridor:{index}", "points": xyz}

    def report(self):
        return {"kind": "route_scoped_streaming_survey_sources", "half_width_m": self.width,
                "curve_margin_m": self.margin, "constant_z_xy_tolerance_m": self.tolerance,
                "measured_xyz_unchanged": True, "constant_contour_z_unchanged": True,
                "variable_z_curves_kept_whole": True,
                "geometry_bounds": list(self.bounds),
                "footprint_sha256": hashlib.sha256(shapely.normalize(self.geometry).wkb).hexdigest(),
                "counts": dict(self.counts)}


def terrain_corridor_covers(saved, required):
    """Keep the saved mesh when the current construction corridor fits inside."""
    if required is None or saved == required:
        return True
    # Preserve the nominal design corridor and the 0.10 m arc sampling bound.
    current = TerrainCorridor({**required, "curve_margin_m": .10})
    return TerrainCorridor(saved).prepared.covers(current.geometry)
