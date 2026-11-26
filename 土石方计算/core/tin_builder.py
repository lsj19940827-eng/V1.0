# -*- coding: utf-8 -*-
"""
TIN 构建器

使用 triangle 库实现约束 Delaunay 三角剖分（CDT）：
- 等高线离散点作为顶点 + 约束边（保证等高线作为三角形的边）
- 高程点作为额外顶点
- 构建 KDTree 空间索引加速高程查询
- 支持按输入点、约束边、构建参数及源文件状态校验的 .npz 缓存
"""

from __future__ import annotations
import os
import hashlib
import json
import numpy as np
from typing import Optional
from pathlib import Path

from 土石方计算.models.terrain import TerrainPoint, ConstraintEdge, TINModel


class TINBuilder:
    """
    约束 Delaunay 三角网构建器

    Usage
    -----
    >>> builder = TINBuilder()
    >>> builder.add_contour_points(pts, edges)   # 等高线离散点 + 约束边
    >>> builder.add_elevation_points(pts)         # 散点高程
    >>> tin = builder.build()                     # 执行 CDT
    >>> tin = builder.build(cache_path=".cache/terrain.npz")  # 带缓存
    """

    _CACHE_VERSION = 6
    _POINT_TOLERANCE = 1e-6

    def __init__(self):
        self._terrain_points: list[TerrainPoint] = []
        self._constraint_edges: list[ConstraintEdge] = []
        self._elevation_indices: set[int] = set()
        self.quality_report: dict = {}

    # ------------------------------------------------------------------
    # 数据积累
    # ------------------------------------------------------------------

    def reset(self):
        """清空所有已添加的数据"""
        self._terrain_points.clear()
        self._constraint_edges.clear()
        self._elevation_indices.clear()
        self.quality_report = {}

    def add_contour_points(
        self,
        points: list[TerrainPoint],
        edges: list[ConstraintEdge]
    ) -> None:
        """
        添加等高线离散化后的点集 + 约束边。

        边的索引是相对于本次 add 操作中 points 列表的局部索引，
        内部会自动转换为全局索引。
        """
        offset = len(self._terrain_points)
        self._terrain_points.extend(points)
        for e in edges:
            self._constraint_edges.append(
                ConstraintEdge(i=e.i + offset, j=e.j + offset)
            )

    def add_elevation_points(self, points: list[TerrainPoint]) -> None:
        """添加散点高程（无约束边）"""
        self._elevation_indices.update(range(len(self._terrain_points), len(self._terrain_points) + len(points)))
        self._terrain_points.extend(points)

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def filter_outliers(
        self,
        iqr_factor: float = 3.0,
        z_score_threshold: float = 4.0,
        *,
        absolute_error_m: Optional[float] = None,
    ) -> int:
        """用附近测量资料筛查高程，整条处理异常等高线。

        保留原接口的两个宽松程度参数；默认对应 20 m 的明显高程偏差。
        不再按全域高程分位数删除真实山坡、零高程或负高程。
        """
        if (not np.isfinite(iqr_factor) or iqr_factor <= 0
                or not np.isfinite(z_score_threshold) or z_score_threshold <= 0):
            raise ValueError("异常高程过滤系数必须有限且大于零")
        if absolute_error_m is None:
            absolute_error_m = 20.0 * iqr_factor / 3.0 * z_score_threshold / 4.0
        if not np.isfinite(absolute_error_m) or absolute_error_m <= 0:
            raise ValueError("明显高程偏差必须有限且大于零")
        points = self._terrain_points
        if not all(np.isfinite((p.x, p.y, p.z)).all() for p in points):
            raise ValueError("地形点坐标和高程必须有限")

        # 原读入器以约束边表示等高线；连通分量恢复完整来源，避免留下坏线残段。
        parents = list(range(len(points)))
        constrained = set()

        def root(index):
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        for edge in self._constraint_edges:
            if not (0 <= edge.i < len(points) and 0 <= edge.j < len(points)):
                raise ValueError("约束边引用了无效地形点索引")
            constrained.update((edge.i, edge.j))
            parents[root(edge.j)] = root(edge.i)
        groups: dict[int, list[int]] = {}
        for index in range(len(points)):
            groups.setdefault(root(index), []).append(index)
        source_indices = sorted(groups.values(), key=lambda group: group[0])
        sources = [{
            "kind": "polyline" if any(i in constrained for i in group) else "point",
            "layer": "SQX" if any(i in constrained for i in group) else "GCD",
            "points": [[points[i].x, points[i].y, points[i].z] for i in group],
            "source_handle": "TIN:" + str(group[0]),
        } for group in source_indices]
        from 土石方计算.io.terrain_quality import clean_terrain_sources
        cleaned = clean_terrain_sources(sources, policy={"absolute_error_m": float(absolute_error_m)})
        self.quality_report = cleaned["report"]
        retained_sources = set(self.quality_report["accepted_entity_indices"])
        kept_indices = sorted(i for source_index in retained_sources for i in source_indices[source_index])
        remap = {old: new for new, old in enumerate(kept_indices)}
        removed_count = len(points) - len(kept_indices)
        if removed_count:
            self._terrain_points = [points[index] for index in kept_indices]
            self._elevation_indices = {remap[index] for index in self._elevation_indices if index in remap}
            self._constraint_edges = [ConstraintEdge(remap[edge.i], remap[edge.j])
                                      for edge in self._constraint_edges
                                      if edge.i in remap and edge.j in remap]
        return removed_count

    def build(
        self,
        cache_path: Optional[str] = None,
        source_files: Optional[list[str]] = None,
        filter_outliers: bool = True,
        outlier_iqr_factor: float = 3.0,
        auto_boundary: bool = True,
        boundary_gap_factor: float = 4.0,
        outlier_absolute_error_m: float = 20.0,
        allow_constraint_intersections: bool = False,
    ) -> TINModel:
        """
        执行约束 Delaunay 三角剖分，返回 TINModel。

        Parameters
        ----------
        cache_path : 缓存文件路径（.npz），若指定则先检查缓存是否有效
        source_files : 源数据文件路径列表（用于缓存失效检测）
        filter_outliers : 默认按附近测量资料剔除明显异常高程点及整条等高线
        outlier_iqr_factor : 兼容旧接口的宽松程度（默认 3.0，越大越宽松）
        auto_boundary : 默认按局部测量点距从外边界裁掉跨越无资料区的三角面
        boundary_gap_factor : 允许边长相对于局部点距的倍数（默认 4.0）
        outlier_absolute_error_m : 默认 20 m 的明显高程偏差

        Returns
        -------
        TINModel（已构建空间索引）
        """
        if not np.isfinite(outlier_iqr_factor) or outlier_iqr_factor <= 0:
            raise ValueError("异常高程过滤系数必须有限且大于零")
        if not np.isfinite(boundary_gap_factor) or boundary_gap_factor < 2:
            raise ValueError("自动范围点距倍数必须有限且不小于 2")
        if not np.isfinite(outlier_absolute_error_m) or outlier_absolute_error_m <= 0:
            raise ValueError("明显高程偏差必须有限且大于零")
        files = list(source_files or [])
        if cache_path:
            signature = self._build_signature(filter_outliers, outlier_iqr_factor,
                                              auto_boundary, boundary_gap_factor, outlier_absolute_error_m)
            if allow_constraint_intersections:
                signature = hashlib.sha256((signature + ":consistent_constraint_intersections_v1").encode()).hexdigest()
            if self._cache_is_valid(cache_path, files, signature):
                return self._load_cache(cache_path)

        working = self
        if filter_outliers:
            # 构建时不覆盖原始输入，否则同一设置再次构建会改变缓存签名。
            working = TINBuilder()
            working._terrain_points = list(self._terrain_points)
            working._constraint_edges = list(self._constraint_edges)
            working._elevation_indices = set(self._elevation_indices)
            working.filter_outliers(iqr_factor=outlier_iqr_factor,
                                    absolute_error_m=outlier_absolute_error_m * outlier_iqr_factor / 3.0)

        tin = working._run_cdt(allow_constraint_intersections=allow_constraint_intersections)
        tin.quality_report = working.quality_report if filter_outliers else {"enabled": False}
        if auto_boundary:
            support = None
            if 3 <= len(working._elevation_indices) < len(working._terrain_points):
                scatter = TINBuilder()
                scatter.add_elevation_points([working._terrain_points[i] for i in sorted(working._elevation_indices)])
                xy = np.asarray([[p.x, p.y] for p in scatter._terrain_points])
                if np.linalg.matrix_rank(xy - xy[0]) >= 2:
                    support = scatter._run_cdt()
                    self._clip_automatic_boundary(support, boundary_gap_factor)
            self._clip_automatic_boundary(tin, boundary_gap_factor, support)
        else:
            tin.boundary_report = {"mode": "convex_hull", "removed_face_count": 0}
        tin.source_files = files
        tin.source_mtimes = self._get_source_mtimes(files)
        self._build_spatial_index(tin)

        if cache_path:
            self._save_cache(tin, cache_path, files, signature)

        return tin

    def _run_cdt(self, *, allow_constraint_intersections=False) -> TINModel:
        """
        执行约束 Delaunay 三角剖分。
        有约束边时必须使用 triangle；仅散点允许回退到 scipy Delaunay。
        """
        if len(self._terrain_points) < 3:
            raise ValueError(f"点数不足，无法构建 TIN（当前 {len(self._terrain_points)} 点）")

        pts_xy = np.array([[p.x, p.y] for p in self._terrain_points], dtype=float)
        pts_z = np.array([p.z for p in self._terrain_points], dtype=float)
        if not np.isfinite(pts_xy).all() or not np.isfinite(pts_z).all():
            raise ValueError("地形点坐标和高程必须有限")

        # 去重（triangle / Delaunay 对完全重复点都会报错）
        pts_xy, keep_mask, idx_mapping = self._deduplicate_points(pts_xy, self._POINT_TOLERANCE)
        if np.any(np.abs(pts_z - pts_z[keep_mask][idx_mapping]) > self._POINT_TOLERANCE):
            raise ValueError("相同或重合平面位置存在冲突高程，不能自动取舍")
        pts_z = pts_z[keep_mask]   # 仅保留唯一点的 Z 值
        if len(pts_xy) < 3:
            raise ValueError(f"点数不足，无法构建 TIN（当前 {len(pts_xy)} 点）")

        # 约束边（映射到去重后的索引）
        n_orig = len(keep_mask)
        segs = []
        for e in self._constraint_edges:
            if not (0 <= e.i < n_orig and 0 <= e.j < n_orig):
                raise ValueError("约束边引用了无效地形点索引")
            ni = int(idx_mapping[e.i])
            nj = int(idx_mapping[e.j])
            if ni != nj:
                segs.append([ni, nj])

        try:
            import triangle as tr
        except ImportError:
            tr = None

        if tr is None and self._constraint_edges:
            raise ImportError("带约束边的 TIN 需要 triangle，不能降级为无约束 Delaunay")

        if tr is not None:
            tri_input: dict = {"vertices": pts_xy}
            if segs:
                tri_input["segments"] = np.array(segs, dtype=int)
                # 标记原始约束；c 封闭凸包，使开放等高线也能覆盖测区。
                tri_input["segment_markers"] = np.full((len(segs), 1), 2, dtype=np.int32)
                options = "pc"
            else:
                options = ""

            result = tr.triangulate(tri_input, options)
            if "triangles" not in result or len(result["triangles"]) == 0:
                raise ValueError("triangle 三角剖分失败：未返回 triangles")

            vertices_xy = np.asarray(result["vertices"], dtype=np.float64)    # shape=(N', 2)
            triangles = result["triangles"]      # shape=(M, 3)

            # 按真实返回坐标匹配高程，不能假设返回顺序或凭最近邻猜新增点高程。
            if (len(vertices_xy) >= len(pts_xy)
                    and np.array_equal(vertices_xy[:len(pts_xy)], pts_xy)):
                # Verify the entire returned prefix before reusing source order;
                # appended intersections still require original-edge heights.
                result_indices = np.full(len(vertices_xy), -1, dtype=np.int64)
                result_indices[:len(pts_xy)] = np.arange(len(pts_xy))
            else:
                source_indices = {tuple(xy): i for i, xy in enumerate(pts_xy)}
                result_indices = np.asarray([source_indices.get(tuple(xy), -1) for xy in vertices_xy], dtype=np.int64)
            missing = np.flatnonzero(result_indices < 0)
            if len(missing) and not allow_constraint_intersections:
                raise ValueError("约束三角剖分生成新增顶点，缺少可靠高程；请先处理交叉约束")
            pts_z_full = np.empty(len(vertices_xy), dtype=np.float64)
            known = result_indices >= 0
            pts_z_full[known] = pts_z[result_indices[known]]
            if len(missing):
                pts_z_full[missing] = self._constraint_intersection_heights(
                    vertices_xy[missing], pts_xy, pts_z, np.asarray(segs, dtype=np.int64))
            result_edges = []
            if segs:
                returned_segments = np.asarray(result.get("segments", []), dtype=int).reshape(-1, 2)
                returned_markers = np.asarray(result.get("segment_markers", []), dtype=int).reshape(-1)
                if len(returned_segments) != len(returned_markers) or not np.any(returned_markers == 2):
                    raise ValueError("约束三角剖分未返回可追溯的约束边")
                result_edges = [ConstraintEdge(int(i), int(j))
                                for (i, j), marker in zip(returned_segments, returned_markers)
                                if marker == 2]

            points_3d = np.column_stack([vertices_xy, pts_z_full])
            return TINModel(
                points=points_3d,
                triangles=triangles.astype(int),
                constraint_edges=result_edges,
                source_files=[],
                source_mtimes=[],
            )

        # fallback：triangle 不可用时使用 scipy Delaunay（不强制约束边）
        try:
            from scipy.spatial import Delaunay
            triangles = Delaunay(pts_xy).simplices.astype(int)
        except Exception as exc:
            raise ValueError("Delaunay 三角剖分失败，当前点集可能退化") from exc

        points_3d = np.column_stack([pts_xy, pts_z])
        return TINModel(
            points=points_3d,
            triangles=triangles,
            constraint_edges=[],
            source_files=[],
            source_mtimes=[],
        )

    @staticmethod
    def _constraint_intersection_heights(vertices, xy, z, segments):
        """Interpolate only on actual source edges with consistent heights.

        A small index over groups of adjacent source segments limits memory for
        dense survey contours. No nearest-neighbor elevation is invented.
        """
        import shapely
        from shapely.strtree import STRtree
        if not len(segments):
            raise ValueError("三角剖分新增顶点没有可靠约束高程")
        origin = xy[0].copy()
        local_xy = xy - origin
        first, last = local_xy[segments[:, 0]], local_xy[segments[:, 1]]
        starts = np.arange(0, len(segments), 256)
        boxes = []
        for start in starts:
            values = np.vstack((first[start:start+256], last[start:start+256]))
            low, high = values.min(axis=0)-1e-6, values.max(axis=0)+1e-6
            boxes.append(shapely.box(*low, *high))
        tree = STRtree(boxes)
        output = []
        for world_point in vertices:
            point = world_point-origin
            heights = []
            for group in tree.query(shapely.Point(point)):
                begin = starts[int(group)]
                end = min(begin+256, len(segments))
                a, b = first[begin:end], last[begin:end]
                d = b-a
                lengths2 = np.einsum("ij,ij->i", d, d)
                ratio = np.divide(np.einsum("ij,ij->i", point-a, d), lengths2,
                                  out=np.zeros(len(a)), where=lengths2 > 0)
                projections = a+ratio[:, None]*d
                valid = ((ratio >= -1e-8) & (ratio <= 1+1e-8)
                         & (np.linalg.norm(projections-point, axis=1) <= 1e-6) & (lengths2 > 0))
                ids = segments[begin:end][valid]
                t = ratio[valid]
                heights.extend((z[ids[:, 0]] + t*(z[ids[:, 1]]-z[ids[:, 0]])).tolist())
            if not heights or max(heights)-min(heights) > 1e-6:
                raise ValueError(f"相交约束高程无法一致确定，位置 {world_point.tolist()}")
            output.append(heights[0])
        return np.asarray(output, dtype=np.float64)

    @staticmethod
    def _deduplicate_points(
        pts: np.ndarray, tol: float = 1e-6
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        去除距离小于 tol 的重复点。

        Returns
        -------
        unique_pts   : shape=(N_unique, 2)  去重后点集
        keep_mask    : shape=(N,) bool      True 表示该原始点被保留
        idx_mapping  : shape=(N,) int       原始索引 → 去重后新索引的映射
        """
        n = len(pts)
        if n == 0:
            return pts.copy(), np.empty(0, dtype=bool), np.empty(0, dtype=int)
        # 用 lexsort 对点排序，相邻比较距离，O(N log N)
        order = np.lexsort((pts[:, 1], pts[:, 0]))
        sorted_pts = pts[order]
        diff = np.diff(sorted_pts, axis=0)
        dists = np.hypot(diff[:, 0], diff[:, 1])
        # dup_flags[i]: sorted_pts[i] 是否与 sorted_pts[i-1] 重复
        dup_flags = np.concatenate([[False], dists < tol])

        # keep_mask 和 sorted_to_kept 映射（在排序序列中）
        keep_in_sorted = ~dup_flags                           # shape=(N,)
        # 每个排序位置对应的 kept 索引（重复点指向前一个保留点）
        kept_cumsum = np.cumsum(keep_in_sorted) - 1          # shape=(N,)

        # 从排序空间映射回原始空间
        keep_mask = np.zeros(n, dtype=bool)
        keep_mask[order[keep_in_sorted]] = True
        # 输出点按原始输入顺序保留，必须将排序分组号再次映射到此顺序。
        kept_original_indices = order[keep_in_sorted]
        sorted_group_to_output = np.empty(len(kept_original_indices), dtype=int)
        sorted_group_to_output[np.argsort(kept_original_indices)] = np.arange(len(kept_original_indices))
        idx_mapping = np.empty(n, dtype=int)
        idx_mapping[order] = sorted_group_to_output[kept_cumsum]

        unique_pts = pts[keep_mask]
        return unique_pts, keep_mask, idx_mapping

    # ------------------------------------------------------------------
    # 空间索引
    # ------------------------------------------------------------------

    @staticmethod
    def _clip_automatic_boundary(tin: TINModel, gap_factor: float, independent_support: Optional[TINModel] = None) -> None:
        """从外边界剥除超过局部测量间距的跨接面，保留原拓扑与高程。

        与 Rhino 原生入口采用相同的邻接尺度；单次邻域限制防止孤立点
        自己的长边抬高尺度，同时允许真正的稀疏测区使用自己的点距。
        """
        triangles = np.asarray(tin.triangles, dtype=int)
        xy = np.asarray(tin.points[:, :2], dtype=float)
        all_edges = np.concatenate((triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]))
        all_edges.sort(axis=1)
        edges, edge_ids, incidences = np.unique(all_edges, axis=0, return_inverse=True, return_counts=True)
        lengths = np.linalg.norm(xy[edges[:, 0]] - xy[edges[:, 1]], axis=1)
        scales = TINBuilder._boundary_spacing_scales(edges, lengths, len(xy))
        keep = np.ones(len(triangles), dtype=bool)
        for first_column, last_column in ((0, 1), (1, 2), (2, 0)):
            first, last = triangles[:, first_column], triangles[:, last_column]
            length = np.linalg.norm(xy[first] - xy[last], axis=1)
            keep &= length <= gap_factor * np.maximum(scales[first], scales[last])
        unsupported = ~keep
        # 自动范围只由原始外裸边向内剥除。密闭等高线中央的合法扇形
        # 可以有长边；内部孤立候选不能自行制造孔洞或漏掉测量点。
        if np.any(incidences > 2):
            raise ValueError("地形三角网存在非流形共边，不能自动识别测量外边界")
        order = np.argsort(edge_ids, kind="stable")
        starts = np.concatenate(([0], np.cumsum(incidences)[:-1]))
        incident_faces = np.tile(np.arange(len(triangles)), 3)[order]
        first_faces = incident_faces[starts]
        second_faces = np.full(len(edges), -1, dtype=int)
        paired = incidences == 2
        second_faces[paired] = incident_faces[starts[paired] + 1]
        face_edges = edge_ids.reshape(3, len(triangles)).T
        seeds = np.unique(first_faces[incidences == 1])
        seeds = seeds[unsupported[seeds]]
        excluded = np.zeros(len(triangles), dtype=bool)
        excluded[seeds] = True
        pending = seeds.tolist()
        while pending:
            face = pending.pop()
            for edge_id in face_edges[face]:
                neighbor = second_faces[edge_id] if first_faces[edge_id] == face else first_faces[edge_id]
                if neighbor >= 0 and unsupported[neighbor] and not excluded[neighbor]:
                    excluded[neighbor] = True
                    pending.append(int(neighbor))
        supported_faces = 0
        if independent_support is not None and np.any(excluded):
            import shapely
            origin = np.asarray(independent_support.points[0, :2])
            support_xy = np.asarray(independent_support.points[:, :2]) - origin
            domain = shapely.coverage_union_all(shapely.polygons(support_xy[independent_support.triangles]))
            candidates = np.flatnonzero(excluded)
            footprints = shapely.polygons((xy - origin)[triangles[candidates]])
            areas = shapely.area(footprints)
            uncovered = shapely.area(shapely.difference(footprints, domain))
            tolerance = np.finfo(float).eps * np.maximum(1.0, areas) * 4096
            protected = candidates[uncovered <= tolerance]
            excluded[protected] = False
            supported_faces = len(protected)
        retained = triangles[~excluded]
        if not len(retained):
            raise ValueError("自动识别测量范围后没有有效三角面，请检查地形点分布或范围点距倍数")
        used = np.unique(retained)
        remap = np.full(len(xy), -1, dtype=int)
        remap[used] = np.arange(len(used))
        original_constraint_count = len(tin.constraint_edges)
        tin.constraint_edges = TINBuilder._filter_retained_constraint_edges(
            tin.constraint_edges, edges, first_faces, second_faces, excluded, remap)
        tin.boundary_report = {
            "mode": "automatic_local_spacing",
            "gap_factor": float(gap_factor),
            "spacing_neighbors": 6,
            "neighbor_scale_limit": 2.0,
            "input_face_count": int(len(triangles)),
            "output_face_count": int(len(retained)),
            "removed_face_count": int(np.count_nonzero(excluded)),
            "unsupported_candidate_face_count": int(np.count_nonzero(unsupported)),
            "retained_internal_candidate_face_count": int(np.count_nonzero(unsupported & ~excluded)),
            "automatic_boundary_rule": "unsupported_faces_reachable_from_original_naked_edges",
            "independent_scatter_support_rule": "restore_only_original_faces_fully_covered_by_independently_trimmed_scatter_domain",
            "independent_scatter_supported_face_count": int(supported_faces),
            "independent_scatter_support_face_count": int(len(independent_support.triangles)) if independent_support is not None else 0,
            "removed_unreferenced_point_count": int(len(xy) - len(used)),
            "removed_constraint_edge_count": original_constraint_count - len(tin.constraint_edges),
        }
        tin.points = tin.points[used]
        tin.triangles = remap[retained]

    @staticmethod
    def _boundary_spacing_scales(edges, lengths, point_count):
        """Compute the original neighbor medians without per-edge Python objects."""
        initial = np.zeros(point_count, dtype=float)
        scales = np.zeros(point_count, dtype=float)
        positive = lengths > 0
        if not positive.all():
            edges, lengths = edges[positive], lengths[positive]
        if not len(edges):
            return scales
        # Endpoints are interleaved: each edge contributes its length once to
        # each owner. Group sizes also cover isolated vertices without padding
        # every vertex out to the maximum degree of a high-order contour fan.
        owners = edges.reshape(-1)
        degree = np.bincount(owners, minlength=point_count)
        vertices = np.flatnonzero(degree)
        degree = degree[vertices]
        starts = np.r_[0, np.cumsum(degree)[:-1]]
        order = np.lexsort((np.repeat(lengths, 2), owners))
        nearest_count = np.minimum(degree, 6)
        upper = starts + nearest_count // 2
        medians = lengths[order[upper] // 2].copy()
        even = nearest_count % 2 == 0
        lower = upper[even] - 1
        medians[even] = (lengths[order[lower] // 2] + medians[even]) / 2.0
        initial[vertices] = medians
        del order
        # Reversing each endpoint pair selects the opposite vertex's initial
        # scale. Sorting numeric arrays preserves statistics.median's exact
        # odd/even arithmetic while avoiding millions of adjacency tuples.
        neighbor_initial = initial[edges[:, ::-1]].reshape(-1)
        order = np.lexsort((neighbor_initial, owners))
        upper = starts + degree // 2
        medians = neighbor_initial[order[upper]].copy()
        even = degree % 2 == 0
        lower = upper[even] - 1
        medians[even] = (neighbor_initial[order[lower]] + medians[even]) / 2.0
        scales[vertices] = np.minimum(initial[vertices], 2.0 * medians)
        return scales

    @staticmethod
    def _filter_retained_constraint_edges(constraints, edges, first_faces, second_faces, excluded, remap):
        """Reuse original edge incidence without rebuilding all retained edges."""
        if not constraints:
            return []
        # An original edge survives exactly when at least one incident face does.
        retained_edges = ~excluded[first_faces]
        paired = second_faces >= 0
        retained_edges[paired] |= ~excluded[second_faces[paired]]
        pairs = np.asarray([[min(edge.i, edge.j), max(edge.i, edge.j)]
                            for edge in constraints], dtype=np.int64)
        # np.unique(axis=0) already sorted edges lexicographically. Structured
        # integer keys preserve that order without multiplying vertex indices.
        key_dtype = np.dtype([("first", np.int64), ("last", np.int64)])
        edge_keys = np.ascontiguousarray(edges, dtype=np.int64).view(key_dtype).reshape(-1)
        positions = np.searchsorted(edge_keys, pairs.view(key_dtype).reshape(-1))
        present = positions < len(edges)
        candidates = np.flatnonzero(present)
        if len(candidates):
            edge_positions = positions[candidates]
            present[candidates] = (np.all(edges[edge_positions] == pairs[candidates], axis=1)
                                   & retained_edges[edge_positions])
        # Preserve source orientation, duplicates and ordering after remapping.
        return [ConstraintEdge(int(remap[edge.i]), int(remap[edge.j]))
                for edge, keep in zip(constraints, present) if keep]

    @staticmethod
    def _build_spatial_index(tin: TINModel) -> None:
        """构建 KDTree 空间索引，写入 tin.spatial_index"""
        from scipy.spatial import KDTree
        tin.spatial_index = KDTree(tin.points[:, :2])

    # ------------------------------------------------------------------
    # 缓存
    # ------------------------------------------------------------------

    def _build_signature(self, filter_outliers: bool, outlier_iqr_factor: float,
                         auto_boundary: bool = True, boundary_gap_factor: float = 4.0,
                         outlier_absolute_error_m: float = 20.0) -> str:
        """对原始输入及算法参数签名，防止数据未改源文件却错误复用旧网格。"""
        from 土石方计算.io.terrain_quality import DEFAULT_POLICY
        try:
            import triangle
            backend = "triangle:" + str(getattr(triangle, "__version__", "unknown"))
        except ImportError:
            backend = "scipy-delaunay"
        parameters = {
            "version": self._CACHE_VERSION,
            "backend": backend,
            "triangle_options": "pc",
            "point_tolerance": self._POINT_TOLERANCE,
            "new_vertex_policy": "reject",
            "filter_outliers": bool(filter_outliers),
            "outlier_iqr_factor": float(outlier_iqr_factor),
            "quality_policy": "local_reference_whole_constraint_component_v1",
            "quality_parameters": {**DEFAULT_POLICY, "absolute_error_m":
                                   float(outlier_absolute_error_m * outlier_iqr_factor / 3.0)},
            "outlier_absolute_error_m": float(outlier_absolute_error_m),
            "auto_boundary": bool(auto_boundary),
            "boundary_gap_factor": float(boundary_gap_factor),
            "boundary_spacing_neighbors": 6,
            "boundary_neighbor_scale_limit": 2.0,
            "automatic_boundary_rule": "unsupported_faces_reachable_from_original_naked_edges",
            "independent_scatter_support_rule": "restore_only_original_faces_fully_covered_by_independently_trimmed_scatter_domain",
        }
        digest = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode("utf-8"))
        points = np.asarray([[p.x, p.y, p.z] for p in self._terrain_points], dtype="<f8").reshape(-1, 3)
        edges = np.asarray([[edge.i, edge.j] for edge in self._constraint_edges], dtype="<i8").reshape(-1, 2)
        elevation_indices = np.asarray(sorted(self._elevation_indices), dtype="<i8")
        for array in (points, edges, elevation_indices):
            digest.update(np.asarray(array.shape, dtype="<i8").tobytes())
            digest.update(array.tobytes())
        return digest.hexdigest()

    @staticmethod
    def _get_source_mtimes(source_files: list[str]) -> list[float]:
        return [os.path.getmtime(f) if os.path.exists(f) else -1.0
                for f in source_files]

    def _cache_is_valid(
        self, cache_path: str, source_files: list[str], signature: str
    ) -> bool:
        if not os.path.exists(cache_path):
            return False
        try:
            with np.load(cache_path, allow_pickle=False) as data:
                required = {"cache_version", "cache_signature", "constraint_edges",
                            "points", "triangles", "source_files", "source_mtimes",
                            "quality_report", "boundary_report"}
                if not required.issubset(data.files):
                    return False
                if int(data["cache_version"].item()) != self._CACHE_VERSION:
                    return False
                if str(data["cache_signature"].item()) != signature:
                    return False
                cached_files = list(data["source_files"])
                cached_mtimes = list(data["source_mtimes"])
                return (cached_files == source_files
                        and cached_mtimes == self._get_source_mtimes(source_files))
        except Exception:
            return False

    def _save_cache(
        self, tin: TINModel, cache_path: str, source_files: list[str], signature: str
    ) -> None:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        mtimes = self._get_source_mtimes(source_files)
        np.savez_compressed(
            cache_path,
            points=tin.points,
            triangles=tin.triangles,
            constraint_edges=np.asarray([[e.i, e.j] for e in tin.constraint_edges], dtype=np.int64).reshape(-1, 2),
            cache_version=np.array(self._CACHE_VERSION),
            cache_signature=np.array(signature),
            source_files=np.array(source_files, dtype=str),
            source_mtimes=np.array(mtimes),
            quality_report=np.array(json.dumps(getattr(tin, "quality_report", {}), ensure_ascii=False)),
            boundary_report=np.array(json.dumps(getattr(tin, "boundary_report", {}), ensure_ascii=False)),
        )

    def _load_cache(self, cache_path: str) -> TINModel:
        with np.load(cache_path, allow_pickle=False) as data:
            tin = TINModel(
                points=data["points"],
                triangles=data["triangles"],
                constraint_edges=[ConstraintEdge(int(i), int(j)) for i, j in data["constraint_edges"]],
                source_files=list(data["source_files"]),
                source_mtimes=list(data["source_mtimes"]),
            )
            tin.quality_report = json.loads(str(data["quality_report"].item()))
            tin.boundary_report = json.loads(str(data["boundary_report"].item()))
        self._build_spatial_index(tin)
        return tin
