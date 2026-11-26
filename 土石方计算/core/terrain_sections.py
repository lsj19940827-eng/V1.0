# -*- coding: utf-8 -*-
"""按已有 TIN 三角片精确剖切；GEOS 只在局部平面坐标中求交。"""

from __future__ import annotations

import math
from fractions import Fraction
import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.strtree import STRtree

from 土石方计算.models.terrain import TINModel


class TerrainSectionIndex:
    """冻结三角片的平面空间索引，不重建拓扑，也不跨越缺测区。"""

    def __init__(self, tin: TINModel):
        points = np.asarray(tin.points, dtype=float)
        triangles = np.asarray(tin.triangles)
        if (points.ndim != 2 or points.shape[1] != 3 or len(points) < 3
                or not np.isfinite(points).all()):
            raise ValueError("TIN 顶点必须是有限的三维坐标")
        if (triangles.ndim != 2 or triangles.shape[1] != 3 or len(triangles) == 0
                or not np.issubdtype(triangles.dtype, np.integer)
                or np.any(triangles < 0) or np.any(triangles >= len(points))):
            raise ValueError("TIN 三角片索引无效")
        self._origin = points[0, :2].copy()
        self._points = points.copy()
        self._points[:, :2] -= self._origin
        self._triangles = triangles.copy()
        footprints = shapely.polygons(self._points[triangles, :2])
        if np.any(~shapely.is_valid(footprints)) or np.any(shapely.area(footprints) <= 0):
            raise ValueError("TIN 含无效或退化的平面三角片")
        self._areas = shapely.area(footprints)
        self._tree = STRtree(footprints)
        self._checked_faces = set()

    def plan_elevation_bounds(self, bounds):
        """Conservatively bound elevations from all original faces meeting a box."""
        corners = np.asarray(bounds, dtype=float).reshape(2, 2) - self._origin
        ids = self._tree.query(shapely.box(*corners.flat))
        if not len(ids):
            return None
        heights = self._points[self._triangles[ids], 2]
        return float(heights.min()), float(heights.max())

    def covers_plan_point(self, point_xy):
        """Test membership in the original faces without rebuilding topology."""
        point = shapely.points(np.asarray(point_xy, dtype=float)-self._origin)
        return bool(len(self._tree.query(point, predicate="intersects")))

    def section_line(self, origin_xy, direction_xy, offset_min, offset_max,
                     sample_step=None) -> list[tuple[float, float]]:
        """返回全部三角边折点，缺测区以 NaN 分隔，禁止端值外推。

        direction_xy 是偏距增大方向的水平单位向量。sample_step 仅增加
        显示点，不替代真实折点；省略时只保留折点、两端及偏距零点。
        """
        origin = np.asarray(origin_xy, dtype=float)
        direction = np.asarray(direction_xy, dtype=float)
        if (origin.shape != (2,) or direction.shape != (2,)
                or not np.isfinite(origin).all() or not np.isfinite(direction).all()):
            raise ValueError("剖切原点和方向必须是有限二维坐标")
        norm = float(np.linalg.norm(direction))
        if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-10):
            raise ValueError("剖切方向必须为水平单位向量")
        direction = direction / norm
        lower, upper = float(offset_min), float(offset_max)
        if not math.isfinite(lower) or not math.isfinite(upper) or upper <= lower:
            raise ValueError("剖切偏距必须有限，且终点大于起点")
        if sample_step is not None and (not math.isfinite(sample_step) or sample_step <= 0):
            raise ValueError("显示采样间距必须为正有限值")
        local_origin = origin - self._origin
        endpoints = local_origin + np.asarray([lower, upper])[:, None] * direction
        line = LineString(endpoints)
        indices = self._query_indices(line)
        self._check_topology(indices)
        hits = shapely.intersection(self._tree.geometries[indices], line)
        # 仅按局部浮点舍入合并同一交点，不用工程容差吞掉细小峰谷或孔洞。
        scale = max(1.0, upper-lower, float(np.max(np.abs(endpoints))))
        tolerance = np.finfo(float).eps * scale * 32
        anchors = [lower, upper] + ([0.0] if lower <= 0 <= upper else [])
        offsets = list(anchors)
        if sample_step is not None:
            offsets.extend(np.arange(lower, upper, sample_step).tolist())
        pieces, point_hits = [], []
        for index, hit in zip(indices, hits):
            corners = self._points[self._triangles[int(index)]]
            delta = corners[1:, :2] - corners[0, :2]
            gradient = np.linalg.solve(delta, corners[1:, 2]-corners[0, 2])
            for part in self._parts(hit):
                xy = np.asarray(part.coords, dtype=float)
                projected = (xy-local_origin) @ direction
                projected = np.clip(projected, lower, upper)
                for anchor in anchors:
                    projected[np.abs(projected-anchor) <= tolerance] = anchor
                heights = corners[0, 2] + (xy-corners[0, :2]) @ gradient
                offsets.extend(projected.tolist())
                if part.geom_type == "Point":
                    point_hits.append((float(projected[0]), float(heights[0])))
                    continue
                first, last = int(np.argmin(projected)), int(np.argmax(projected))
                a, b = float(projected[first]), float(projected[last])
                if b > a:
                    pieces.append((a, b, float(heights[first]), float(heights[last])))
        offsets = self._unique_offsets(offsets, tolerance)
        try:
            values = self._values(offsets, pieces, point_hits, tolerance)
        except ValueError as error:
            if "互相矛盾" not in str(error):
                raise
            # Ill-conditioned thin faces and near-vertex intersections may
            # amplify a rounded XY hit into inconsistent plane evaluations.
            # Recompute the same binary input line against canonical original
            # edges exactly; no elevation averaging or engineering tolerance.
            return self._exact_edge_section(indices,endpoints,lower,upper,sample_step)
        # 每个未覆盖的开区间保留明确的缺测标记，即使间隙小于显示采样步长。
        covered = np.zeros(max(0, len(offsets)-1), dtype=bool)
        middles = (offsets[:-1]+offsets[1:])/2
        for a, b, _, _ in pieces:
            start = np.searchsorted(middles, a, side="left")
            finish = np.searchsorted(middles, b, side="right")
            covered[start:finish] = True
        result = []
        for i, (offset, value) in enumerate(zip(offsets, values)):
            result.append((float(offset), float(value)))
            if i < len(covered) and not covered[i]:
                result.append((float(middles[i]), float("nan")))
        return result

    def _exact_edge_section(self,indices,endpoints,lower,upper,sample_step):
        """Binary-rational line/edge intersections and exact shared-edge Z."""
        def cross(a,b):return a[0]*b[1]-a[1]*b[0]
        def sub(a,b):return (a[0]-b[0],a[1]-b[1])
        p=tuple(Fraction(float(x)) for x in endpoints[0])
        end=tuple(Fraction(float(x)) for x in endpoints[1]);v=sub(end,p)
        length_squared=v[0]*v[0]+v[1]*v[1]
        lo,hi=Fraction(lower),Fraction(upper)
        vertices={};edges={};pieces=[];point_hits={}
        def vertex(i):
            if i not in vertices:vertices[i]=tuple(Fraction(float(x)) for x in self._points[i])
            return vertices[i]
        def edge_hits(i,j):
            i,j=sorted((int(i),int(j)));key=(i,j)
            if key in edges:return edges[key]
            a,b=vertex(i),vertex(j);w=sub(b,a);delta=sub(a,p)
            determinant=cross(v,w);hits=[]
            if determinant:
                t=cross(delta,w)/determinant;u=cross(delta,v)/determinant
                if 0<=t<=1 and 0<=u<=1:hits.append((t,a[2]+u*(b[2]-a[2])))
            elif cross(delta,v)==0:
                for q in (a,b):
                    d=sub(q,p);t=(d[0]*v[0]+d[1]*v[1])/length_squared
                    if 0<=t<=1:hits.append((t,q[2]))
            edges[key]=hits;return hits
        for index in indices:
            ids=self._triangles[int(index)];corners=[vertex(int(i)) for i in ids]
            hits=[]
            for i,j in ((0,1),(1,2),(2,0)):hits.extend(edge_hits(ids[i],ids[j]))
            a,b,c=corners;den=cross(sub(b,a),sub(c,a))
            if not den:raise ValueError("TIN 原始三角面在精确坐标中退化")
            for t,q in ((Fraction(0),p),(Fraction(1),end)):
                signs=[cross(sub(second,first),sub(q,first)) for first,second in ((a,b),(b,c),(c,a))]
                if all(k>=0 for k in signs) or all(k<=0 for k in signs):
                    wb=cross(sub(q,a),sub(c,a))/den;wc=cross(sub(b,a),sub(q,a))/den
                    hits.append((t,a[2]+wb*(b[2]-a[2])+wc*(c[2]-a[2])))
            if not hits:continue
            hits=sorted(set(hits));first,last=hits[0],hits[-1]
            if first[0]==last[0]:point_hits.setdefault(first[0],[]).extend(z for t,z in hits)
            else:pieces.append((first[0],last[0],first[1],last[1]))
        events={Fraction(0),Fraction(1),*point_hits}
        if lower<=0<=upper:events.add(-lo/(hi-lo))
        if sample_step is not None:
            events.update((Fraction(float(s))-lo)/(hi-lo) for s in np.arange(lower,upper,sample_step))
        starts={};ends={}
        for i,(a,b,za,zb) in enumerate(pieces):
            events.update((a,b));starts.setdefault(a,[]).append(i);ends.setdefault(b,[]).append(i)
        ordered=sorted(events);active=set();result=[];previous=None
        for position,t in enumerate(ordered):
            active.update(starts.get(t,()))
            zs=list(point_hits.get(t,()))
            for i in active:
                a,b,za,zb=pieces[i]
                zs.append(za+(t-a)/(b-a)*(zb-za))
            if zs and any(z!=zs[0] for z in zs[1:]):
                raise ValueError("互相矛盾的 TIN 高程；精确共享边复核确认不连续，不能生成单值地面线")
            offset=float(lo+t*(hi-lo));height=float(zs[0]) if zs else float("nan")
            if previous is not None and offset<=previous:
                raise ValueError("不同真实剖切交点低于浮点表达分辨率，不能吞掉细小峰谷或孔洞")
            result.append((offset,height));previous=offset
            active.difference_update(ends.get(t,()))
            if position+1<len(ordered) and not active:
                middle=float(lo+(t+ordered[position+1])/2*(hi-lo))
                if middle>offset:result.append((middle,float("nan")))
        return result

    def _query_indices(self, line):
        """用分块外包框加速完整原剖线查询，保留原命中面及其顺序。

        长斜线的整个bbox可能覆盖大片地形。分块只筛候选，完整旧
        LineString仍参与predicate/求交，远端拓扑及高程校验均保留。
        """
        # 与原predicate查询使用相同的GEOS visitor顺序，只把其
        # expensive predicate延后；不能按面索引重排后改变共享点取值。
        original_order = self._tree.query(line)
        if len(original_order) <= 256:
            return self._tree.query(line, predicate="intersects")
        a, b = [[Fraction(float(x)) for x in point] for point in line.coords]
        vertices = [[a[j]+Fraction(i, 64)*(b[j]-a[j]) for j in range(2)]
                    for i in range(65)]
        envelopes = []
        for first, last in zip(vertices, vertices[1:]):
            bounds = []
            for operation, destination in ((min, -math.inf), (max, math.inf)):
                for axis in range(2):
                    exact = operation(first[axis], last[axis])
                    stored = float(exact)
                    if ((destination < 0 and Fraction(stored) > exact)
                            or (destination > 0 and Fraction(stored) < exact)):
                        stored = np.nextafter(stored, destination)
                    bounds.append(float(np.nextafter(stored, destination)))
            envelopes.append(bounds)
        envelopes = np.asarray(envelopes)
        covered = self._tree.query(shapely.box(envelopes[:, 0], envelopes[:, 1],
                                             envelopes[:, 2], envelopes[:, 3]))
        selected = np.zeros(len(self._tree.geometries), dtype=bool)
        selected[covered[1]] = True
        candidates = original_order[selected[original_order]]
        # 原Shapely STRtree predicate同样先准备输入line，再按visitor
        # 顺序过滤。本次仅减少必须执行predicate的候选数。
        shapely.prepare(line)
        return candidates[shapely.intersects(line, self._tree.geometries[candidates])]

    def _check_topology(self, indices):
        """逐步核对实际访问的原三角片，共享边允许，正面积重叠拒绝。"""
        unchecked = np.asarray([int(i) for i in indices if int(i) not in self._checked_faces], dtype=int)
        if not len(unchecked):
            return
        pairs = self._tree.query(self._tree.geometries[unchecked], predicate="intersects")
        first, second = unchecked[pairs[0]], pairs[1]
        distinct = first != second
        first, second = first[distinct], second[distinct]
        if len(first):
            overlap = shapely.area(shapely.intersection(
                self._tree.geometries[first], self._tree.geometries[second]))
            limit = np.finfo(float).eps * np.maximum(self._areas[first], self._areas[second]) * 64
            if np.any(overlap > limit):
                raise ValueError("TIN 三角片平面覆盖重叠，禁止重复覆盖计量")
        self._checked_faces.update(unchecked.tolist())

    @staticmethod
    def _parts(geometry):
        if geometry.is_empty:
            return
        if geometry.geom_type in {"LineString", "Point"}:
            yield geometry
        else:
            for child in geometry.geoms:
                yield from TerrainSectionIndex._parts(child)

    @staticmethod
    def _unique_offsets(offsets, tolerance):
        ordered = np.sort(np.asarray(offsets, dtype=float))
        keep = np.ones(len(ordered), dtype=bool)
        last = ordered[0]
        for i in range(1, len(ordered)):
            if ordered[i]-last <= tolerance:
                keep[i] = False
            else:
                last = ordered[i]
        return ordered[keep]

    @staticmethod
    def _values(offsets, pieces, point_hits, tolerance):
        values = np.full(len(offsets), np.nan, dtype=float)
        for a, b, za, zb in pieces:
            start = np.searchsorted(offsets, a-tolerance, side="left")
            finish = np.searchsorted(offsets, b+tolerance, side="right")
            sample = np.clip(offsets[start:finish], a, b)
            heights = za+(sample-a)/(b-a)*(zb-za)
            existing = values[start:finish]
            known = np.isfinite(existing)
            z_tolerance = (np.finfo(float).eps * max(1.0, abs(za), abs(zb)) * 256
                           + abs((zb-za)/(b-a))*tolerance*4)
            if np.any(np.abs(existing[known]-heights[known]) > z_tolerance):
                raise ValueError("剖切位置存在互相矛盾的 TIN 高程，不能生成单值地面线")
            existing[~known] = heights[~known]
        for offset, height in point_hits:
            pos = int(np.searchsorted(offsets, offset-tolerance, side="left"))
            if pos < len(offsets) and abs(offsets[pos]-offset) <= tolerance:
                if np.isfinite(values[pos]):
                    limit = np.finfo(float).eps*max(1.0, abs(height), abs(values[pos]))*256
                    if abs(values[pos]-height) > limit:
                        raise ValueError("剖切位置存在互相矛盾的 TIN 高程，不能生成单值地面线")
                else:
                    values[pos] = height
        return values
