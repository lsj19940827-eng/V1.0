"""Sample a small longitudinal preview from the original terrain triangles."""
from __future__ import annotations

import numpy as np

from 土石方计算.core.tin_interpolator import TINInterpolator


def _height_in_faces(vertices, faces, x, y):
    """Interpolate on the first containing face, using oriented areas in local XY."""
    a, b, c = (vertices[faces[:, i]] for i in range(3))
    ab = (b[:, 0]-a[:, 0]) * (y-a[:, 1]) - (b[:, 1]-a[:, 1]) * (x-a[:, 0])
    bc = (c[:, 0]-b[:, 0]) * (y-b[:, 1]) - (c[:, 1]-b[:, 1]) * (x-b[:, 0])
    ca = (a[:, 0]-c[:, 0]) * (y-c[:, 1]) - (a[:, 1]-c[:, 1]) * (x-c[:, 0])
    area = ab + bc + ca
    inside = (((ab >= 0) & (bc >= 0) & (ca >= 0)) |
              ((ab <= 0) & (bc <= 0) & (ca <= 0))) & (area != 0)
    matches = np.flatnonzero(inside)
    if matches.size:
        i = matches[0]
        return a[i, 2] + (ca[i] * (b[i, 2]-a[i, 2]) + ab[i] * (c[i, 2]-a[i, 2])) / area[i]
    return np.nan


def sample_ground_points(terrain, xy, token):
    """Return each preview point's original-face elevation, or NaN in unmeasured areas."""
    token.raise_if_cancelled()
    points = np.asarray(xy, dtype=float)
    if not points.size:
        return np.empty(0, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError("查询点必须是有限的二维坐标")
    # This checks the original points and face indices without building a spatial index.
    TINInterpolator(terrain)

    # Nearby stations usually lie in the same small box. Test individual stations
    # only against faces in that box, including large faces spanning its edges.
    groups = []
    for start in range(0, len(points), 16):
        group = points[start:start + 16]
        groups.append((start, group.min(axis=0), group.max(axis=0), group))
    vertices = np.asarray(terrain.points, dtype=float)
    faces = np.asarray(terrain.triangles)
    heights = np.full(len(points), np.nan)
    for start in range(0, len(faces), 32768):
        token.raise_if_cancelled()
        block = faces[start:start + 32768]
        a, b, c = (vertices[block[:, i], :2] for i in range(3))
        xmin, ymin = np.minimum(np.minimum(a, b), c).T
        xmax, ymax = np.maximum(np.maximum(a, b), c).T
        for group_start, low, high, group in groups:
            nearby = np.flatnonzero((xmin <= high[0]) & (xmax >= low[0]) &
                                    (ymin <= high[1]) & (ymax >= low[1]))
            if not nearby.size:
                continue
            left, right = xmin[nearby], xmax[nearby]
            bottom, top = ymin[nearby], ymax[nearby]
            for i, (x, y) in enumerate(group, group_start):
                if np.isfinite(heights[i]):
                    continue
                hits = (left <= x) & (x <= right) & (bottom <= y) & (y <= top)
                if hits.any():
                    heights[i] = _height_in_faces(vertices, block[nearby[hits]], x, y)
        if np.isfinite(heights).all():
            break

    token.raise_if_cancelled()
    return heights
