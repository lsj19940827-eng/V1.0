# -*- coding: utf-8 -*-
"""
TIN 构建器

使用 triangle 库实现约束 Delaunay 三角剖分（CDT）：
- 等高线离散点作为顶点 + 约束边（保证等高线作为三角形的边）
- 高程点作为额外顶点
- 构建 KDTree 空间索引加速高程查询
- 支持 .npz 缓存（源文件 mtime 变化时自动重建）
"""

from __future__ import annotations
import os
import time
import hashlib
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

    def __init__(self):
        self._terrain_points: list[TerrainPoint] = []
        self._constraint_edges: list[ConstraintEdge] = []

    # ------------------------------------------------------------------
    # 数据积累
    # ------------------------------------------------------------------

    def reset(self):
        """清空所有已添加的数据"""
        self._terrain_points.clear()
        self._constraint_edges.clear()

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
        self._terrain_points.extend(points)

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def filter_outliers(
        self,
        iqr_factor: float = 3.0,
        z_score_threshold: float = 4.0,
    ) -> int:
        """
        过滤异常高程点（IQR + Z-score 双重校验）。

        Strategy
        --------
        1. 计算所有点 Z 的 IQR（四分位距）
        2. 超出 [Q1 - k*IQR, Q3 + k*IQR] 范围的点视为异常值
        3. 同时排除 Z-score > z_score_threshold 的点
        4. 约束边引用的点不被删除（避免破坏等高线约束）

        Returns
        -------
        删除的点数量
        """
        if len(self._terrain_points) < 8:
            return 0

        zs = np.array([p.z for p in self._terrain_points])
        q1, q3 = float(np.percentile(zs, 25)), float(np.percentile(zs, 75))
        iqr = q3 - q1
        if iqr < 1e-6:
            return 0  # 所有点高程相同，无法过滤

        lo = q1 - iqr_factor * iqr
        hi = q3 + iqr_factor * iqr
        z_mean = float(np.mean(zs))
        z_std = float(np.std(zs))

        # 约束边引用的原始索引（不能删除）
        protected = set()
        for e in self._constraint_edges:
            protected.add(e.i)
            protected.add(e.j)

        kept: list = []
        removed_count = 0
        old_to_new: list[int] = []
        new_idx = 0
        for i, p in enumerate(self._terrain_points):
            is_outlier = p.z < lo or p.z > hi
            if z_std > 1e-6:
                z_score = abs(p.z - z_mean) / z_std
                is_outlier = is_outlier or z_score > z_score_threshold
            if is_outlier and i not in protected:
                old_to_new.append(-1)  # 被删除
                removed_count += 1
            else:
                kept.append(p)
                old_to_new.append(new_idx)
                new_idx += 1

        if removed_count > 0:
            # 更新约束边索引
            new_edges = []
            for e in self._constraint_edges:
                ni = old_to_new[e.i]
                nj = old_to_new[e.j]
                if ni >= 0 and nj >= 0 and ni != nj:
                    new_edges.append(ConstraintEdge(i=ni, j=nj))
            self._terrain_points = kept
            self._constraint_edges = new_edges

        return removed_count

    def build(
        self,
        cache_path: Optional[str] = None,
        source_files: Optional[list[str]] = None,
        filter_outliers: bool = False,
        outlier_iqr_factor: float = 3.0,
    ) -> TINModel:
        """
        执行约束 Delaunay 三角剖分，返回 TINModel。

        Parameters
        ----------
        cache_path : 缓存文件路径（.npz），若指定则先检查缓存是否有效
        source_files : 源数据文件路径列表（用于缓存失效检测）
        filter_outliers : 构建前是否过滤异常高程点（IQR法）
        outlier_iqr_factor : IQR 倍数阈值（默认 3.0，越大越宽松）

        Returns
        -------
        TINModel（已构建空间索引）
        """
        if cache_path and self._cache_is_valid(cache_path, source_files or []):
            return self._load_cache(cache_path)

        if filter_outliers:
            self.filter_outliers(iqr_factor=outlier_iqr_factor)

        tin = self._run_cdt()
        self._build_spatial_index(tin)

        if cache_path:
            self._save_cache(tin, cache_path, source_files or [])

        return tin

    def _run_cdt(self) -> TINModel:
        """
        执行约束 Delaunay 三角剖分。
        优先使用 triangle（支持约束边）；若未安装则回退到 scipy Delaunay。
        """
        if len(self._terrain_points) < 3:
            raise ValueError(f"点数不足，无法构建 TIN（当前 {len(self._terrain_points)} 点）")

        pts_xy = np.array([[p.x, p.y] for p in self._terrain_points], dtype=float)
        pts_z = np.array([p.z for p in self._terrain_points], dtype=float)

        # 去重（triangle / Delaunay 对完全重复点都会报错）
        pts_xy, keep_mask, idx_mapping = self._deduplicate_points(pts_xy)
        pts_z = pts_z[keep_mask]   # 仅保留唯一点的 Z 值
        if len(pts_xy) < 3:
            raise ValueError(f"点数不足，无法构建 TIN（当前 {len(pts_xy)} 点）")

        # 约束边（映射到去重后的索引）
        n_orig = len(keep_mask)
        segs = []
        for e in self._constraint_edges:
            if e.i >= n_orig or e.j >= n_orig:
                continue
            ni = int(idx_mapping[e.i])
            nj = int(idx_mapping[e.j])
            if ni != nj:
                segs.append([ni, nj])

        try:
            import triangle as tr
        except ImportError:
            tr = None

        if tr is not None:
            tri_input: dict = {"vertices": pts_xy}
            if segs:
                tri_input["segments"] = np.array(segs, dtype=int)
                options = "p"   # PSLG 模式（强制约束边）
            else:
                options = ""

            result = tr.triangulate(tri_input, options)
            if "triangles" not in result or len(result["triangles"]) == 0:
                raise ValueError("triangle 三角剖分失败：未返回 triangles")

            vertices_xy = result["vertices"]    # shape=(N', 2)
            triangles = result["triangles"]      # shape=(M, 3)

            # 构建带 Z 的点集（Steiner 点 Z 由最近邻插值补充）
            n_new = len(vertices_xy)
            n_base = len(pts_xy)
            pts_z_full = np.zeros(n_new)
            pts_z_full[:n_base] = pts_z
            if n_new > n_base:
                # Steiner 点：用最近原始点的 Z 值近似
                from scipy.spatial import KDTree
                kd = KDTree(pts_xy)
                _, idx = kd.query(vertices_xy[n_base:])
                pts_z_full[n_base:] = pts_z[idx]

            points_3d = np.column_stack([vertices_xy, pts_z_full])
            return TINModel(
                points=points_3d,
                triangles=triangles.astype(int),
                constraint_edges=list(self._constraint_edges),
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
            constraint_edges=list(self._constraint_edges),
            source_files=[],
            source_mtimes=[],
        )

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
        # 重复点的 kept_cumsum 修正为其对应的保留点
        for i in range(1, n):
            if dup_flags[i]:
                kept_cumsum[i] = kept_cumsum[i - 1]

        # 从排序空间映射回原始空间
        keep_mask = np.zeros(n, dtype=bool)
        keep_mask[order[keep_in_sorted]] = True
        idx_mapping = np.empty(n, dtype=int)
        idx_mapping[order] = kept_cumsum

        unique_pts = pts[keep_mask]
        return unique_pts, keep_mask, idx_mapping

    # ------------------------------------------------------------------
    # 空间索引
    # ------------------------------------------------------------------

    @staticmethod
    def _build_spatial_index(tin: TINModel) -> None:
        """构建 KDTree 空间索引，写入 tin.spatial_index"""
        from scipy.spatial import KDTree
        tin.spatial_index = KDTree(tin.points[:, :2])

    # ------------------------------------------------------------------
    # 缓存
    # ------------------------------------------------------------------

    @staticmethod
    def _get_source_mtimes(source_files: list[str]) -> list[float]:
        return [os.path.getmtime(f) if os.path.exists(f) else -1.0
                for f in source_files]

    def _cache_is_valid(
        self, cache_path: str, source_files: list[str]
    ) -> bool:
        if not os.path.exists(cache_path):
            return False
        try:
            data = np.load(cache_path, allow_pickle=True)
            cached_files = list(data.get("source_files", []))
            cached_mtimes = list(data.get("source_mtimes", []))
            if cached_files != source_files:
                return False
            current_mtimes = self._get_source_mtimes(source_files)
            return cached_mtimes == current_mtimes
        except Exception:
            return False

    def _save_cache(
        self, tin: TINModel, cache_path: str, source_files: list[str]
    ) -> None:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        mtimes = self._get_source_mtimes(source_files)
        np.savez_compressed(
            cache_path,
            points=tin.points,
            triangles=tin.triangles,
            source_files=np.array(source_files),
            source_mtimes=np.array(mtimes),
        )

    def _load_cache(self, cache_path: str) -> TINModel:
        data = np.load(cache_path, allow_pickle=True)
        tin = TINModel(
            points=data["points"],
            triangles=data["triangles"],
            source_files=list(data["source_files"]),
            source_mtimes=list(data["source_mtimes"]),
        )
        self._build_spatial_index(tin)
        return tin
