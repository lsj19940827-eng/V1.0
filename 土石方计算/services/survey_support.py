"""Describe independent measured-point support for calculated section centres."""

from collections import defaultdict
from itertools import groupby

import numpy as np


def review_survey_support(tin, sections, *, cancelled=None):
    if tin is None or not sections:
        return None
    report = tin.import_report if hasattr(tin, "import_report") else {}
    if report.get("terrain_mode") != "combined" or not report.get("used_contour_count"):
        return None
    from ..core.tin_builder import TINBuilder
    from ..core.tin_interpolator import TINInterpolator
    from ..models.terrain import TerrainPoint

    if cancelled and cancelled():
        raise InterruptedError("已取消地形来源核对")
    locations = {}
    for section in sections:
        xy = section.get("center_xy")
        if xy is None or section.get("coordinate_kind") == "pit_local_slice":
            continue
        key = (section.get("route_id"), section["asset_id"], float(section["station"]))
        locations.setdefault(key, xy)
    if not locations:
        return None

    points = getattr(tin, "used_measured_points", None)
    # A third-party/legacy mesh may retain a summary but omit survey source
    # coordinates. Report that distinction rather than declaring it contour-only.
    if points is None or not len(points) and report.get("accepted_point_count") != 0:
        return {"status": "source_unavailable", "checked_section_count": 0, "ranges": []}
    points = np.asarray(points, dtype=float)
    supported = np.zeros(len(locations), dtype=bool)
    reference_status = "insufficient_measured_points"
    if len(points) >= 3 and np.linalg.matrix_rank(points[:, :2] - points[0, :2]) == 2:
        builder = TINBuilder()
        builder.add_elevation_points([TerrainPoint(*point) for point in points])
        factor = (report.get("terrain_options") or {}).get("boundary_gap_factor", 4.0)
        try:
            reference = builder.build(filter_outliers=False, boundary_gap_factor=float(factor))
            supported = np.isfinite(TINInterpolator(reference).query_batch(np.asarray(list(locations.values()))))
        except (ValueError, RuntimeError):
            return {"status": "reference_unavailable", "checked_section_count": 0, "ranges": []}
        reference_status = "measured_point_boundary"
    if cancelled and cancelled():
        raise InterruptedError("已取消地形来源核对")

    by_asset = defaultdict(list)
    for (route, asset_id, station), covered in zip(locations, supported):
        by_asset[(route, asset_id)].append((station, bool(covered)))
    ranges = []
    for (route, asset_id), samples in by_asset.items():
        for covered, group in groupby(sorted(samples), key=lambda item: item[1]):
            if not covered:
                stations = [station for station, _ in group]
                ranges.append({"route_id": route, "asset_id": asset_id, "first_station": stations[0],
                               "last_station": stations[-1], "section_count": len(stations)})
    return {"status": reference_status, "checked_section_count": len(locations),
            "outside_measured_support_count": int(np.count_nonzero(~supported)),
            "ranges": ranges}
