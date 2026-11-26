# -*- coding: utf-8 -*-
"""
TIN 高程插值查询

使用已有三角网拓扑的分片线性插值，不重新剖分或跨越约束边。

性能目标：单点查询 < 0.1ms，批量 10 万点 < 1s
"""

from __future__ import annotations
import numpy as np
from typing import Optional

from 土石方计算.models.terrain import TINModel


class TINInterpolator:
    """
    TIN 高程插值器

    'auto' 和 'matplotlib' 均使用已有三角片进行线性插值。
    不接受会重新剖分点集、丢失原有约束边的 startinpy 后端。

    Usage
    -----
    >>> interp = TINInterpolator(tin)
    >>> z = interp.query(x, y)              # 单点查询，超范围返回 None
    >>> zs = interp.query_batch(pts_xy)     # 批量查询，shape=(N,2)→shape=(N,)
    """

    def __init__(self, tin: TINModel, backend: str = "auto"):
        """
        Parameters
        ----------
        tin : 已构建的 TINModel
        backend : 'auto' / 'matplotlib'（均保留已有三角片）
        """
        if tin.is_empty or tin.num_triangles == 0:
            raise ValueError("TINModel 为空，无法构建插值器")
        self._tin = tin
        self._backend = self._resolve_backend(backend)
        points = np.asarray(tin.points, dtype=float)
        triangles = np.asarray(tin.triangles)
        if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
            raise ValueError("TIN 顶点必须是有限的三维坐标")
        if (triangles.ndim != 2 or triangles.shape[1] != 3
                or not np.issubdtype(triangles.dtype, np.integer)
                or np.any(triangles < 0) or np.any(triangles >= len(points))):
            raise ValueError("TIN 三角片索引无效")
        self._origin = points[0, :2].copy()
        # 精确剖切只需原三角片的 GEOS 索引，不先创建整网 matplotlib 查询器。
        self._engine = None
        self._section_index = None

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_backend(backend: str) -> str:
        if backend in ("auto", "matplotlib"):
            return "matplotlib"
        if backend == "startinpy":
            raise ValueError("startinpy 会重新剖分并丢失已有 TIN 约束边；请使用 auto 或 matplotlib")
        raise ValueError(f"未知的插值后端: {backend!r}")

    def _init_engine(self):
        """初始化对应后端的插值引擎对象"""
        return self._init_matplotlib()

    def _init_matplotlib(self):
        """
        初始化 matplotlib 线性三角插值器（LinearTriInterpolator）。
        """
        import matplotlib.tri as mtri
        pts = np.asarray(self._tin.points, dtype=float)
        if pts.ndim != 2 or pts.shape[1] != 3 or not np.isfinite(pts).all():
            raise ValueError("TIN 顶点必须是有限的三维坐标")
        # 平移坐标以降低大地坐标对面方程运算的影响。
        self._origin = pts[0, :2].copy()
        xy = pts[:, :2] - self._origin
        triang = mtri.Triangulation(
            xy[:, 0], xy[:, 1],
            self._tin.triangles
        )
        interp = mtri.LinearTriInterpolator(triang, pts[:, 2])
        return interp

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def query(self, x: float, y: float) -> Optional[float]:
        """
        查询单点高程。

        Returns
        -------
        float 或 None（查询点超出 TIN 范围时返回 None）
        """
        result = self.query_batch(np.array([[x, y]]))
        v = result[0]
        return None if np.isnan(v) else float(v)

    def query_batch(self, pts_xy: np.ndarray) -> np.ndarray:
        """
        批量查询高程。

        Parameters
        ----------
        pts_xy : shape=(N, 2)，dtype=float64

        Returns
        -------
        zs : shape=(N,)，超范围点为 np.nan
        """
        pts_xy = np.asarray(pts_xy, dtype=np.float64)
        if pts_xy.size == 0:
            return np.empty(0, dtype=float)
        if pts_xy.ndim == 1:
            pts_xy = pts_xy.reshape(1, 2)
        if pts_xy.ndim != 2 or pts_xy.shape[1] != 2 or not np.isfinite(pts_xy).all():
            raise ValueError("查询点必须是有限的二维坐标")
        return self._query_matplotlib(pts_xy - self._origin)

    def _query_matplotlib(self, pts_xy: np.ndarray) -> np.ndarray:
        """matplotlib 批量线性插值"""
        if self._engine is None:
            self._engine = self._init_engine()
        zs = self._engine(pts_xy[:, 0], pts_xy[:, 1])
        result = np.array(zs, dtype=np.float64)
        result[np.ma.getmaskarray(zs)] = np.nan
        return result

    def section_line(self, origin_xy, direction_xy, offset_min, offset_max,
                     sample_step=None) -> list[tuple[float, float]]:
        """精确剖切已有 TIN；保留所有三角边折点，缺测区用 NaN 分隔。"""
        return self._get_section_index().section_line(
            origin_xy, direction_xy, offset_min, offset_max, sample_step)

    def plan_elevation_bounds(self, bounds):
        """Use the original face index to bound terrain elevations locally."""
        return self._get_section_index().plan_elevation_bounds(bounds)

    def covers_plan_point(self, point_xy):
        return self._get_section_index().covers_plan_point(point_xy)

    def _get_section_index(self):
        if self._section_index is None:
            from 土石方计算.core.terrain_sections import TerrainSectionIndex
            self._section_index = TerrainSectionIndex(self._tin)
        return self._section_index

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    @property
    def backend(self) -> str:
        return self._backend

    def is_within_bounds(self, x: float, y: float) -> bool:
        """快速判断点是否在 TIN 包围盒内（非精确边界判断）"""
        xmin, ymin, xmax, ymax = self._tin.get_bbox()
        return xmin <= x <= xmax and ymin <= y <= ymax
