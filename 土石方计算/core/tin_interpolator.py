# -*- coding: utf-8 -*-
"""
TIN 高程插值查询

主引擎：startinpy（Rust 高性能，支持自然邻域/Laplace/IDW）
备选引擎：matplotlib.tri.LinearTriInterpolator（线性重心坐标插值）

性能目标：单点查询 < 0.1ms，批量 10 万点 < 1s
"""

from __future__ import annotations
import numpy as np
from typing import Optional

from 土石方计算.models.terrain import TINModel


class TINInterpolator:
    """
    TIN 高程插值器

    支持两种后端（Backend）：
    - 'startinpy' : 主引擎，Rust 实现，精度高，速度快
    - 'matplotlib' : 备选，纯 Python，依赖较轻

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
        backend : 'auto'（优先 startinpy）/ 'startinpy' / 'matplotlib'
        """
        if tin.is_empty:
            raise ValueError("TINModel 为空，无法构建插值器")
        self._tin = tin
        self._backend = self._resolve_backend(backend)
        self._engine = self._init_engine()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_backend(backend: str) -> str:
        if backend == "auto":
            try:
                import startinpy  # noqa: F401
                return "startinpy"
            except ImportError:
                return "matplotlib"
        return backend

    def _init_engine(self):
        """初始化对应后端的插值引擎对象"""
        if self._backend == "startinpy":
            return self._init_startinpy()
        elif self._backend == "matplotlib":
            return self._init_matplotlib()
        else:
            raise ValueError(f"未知的插值后端: {self._backend!r}")

    def _init_startinpy(self):
        """
        初始化 startinpy DT（Delaunay Triangulation）。

        startinpy 接口：
            dt = startinpy.DT()
            dt.insert(pts_xyz)          # pts_xyz: [[x,y,z], ...]
            z = dt.interpolate({"method": "NaturalNeighbour"}, [[x, y]])
        """
        import startinpy
        dt = startinpy.DT()
        dt.insert(self._tin.points.tolist())
        return dt

    def _init_matplotlib(self):
        """
        初始化 matplotlib 线性三角插值器（LinearTriInterpolator）。
        """
        import matplotlib.tri as mtri
        pts = self._tin.points
        triang = mtri.Triangulation(
            pts[:, 0], pts[:, 1],
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
        if pts_xy.ndim == 1:
            pts_xy = pts_xy.reshape(1, 2)

        if self._backend == "startinpy":
            return self._query_startinpy(pts_xy)
        else:
            return self._query_matplotlib(pts_xy)

    def _query_startinpy(self, pts_xy: np.ndarray) -> np.ndarray:
        """startinpy 批量插值（自然邻域法）"""
        pts_list = pts_xy.tolist()
        try:
            results = self._engine.interpolate(
                {"method": "NaturalNeighbour"},
                pts_list
            )
            zs = np.array(results, dtype=np.float64)
            # startinpy 对超范围点返回特殊值（通常是 nan 或极值），统一为 nan
            zs[~np.isfinite(zs)] = np.nan
            return zs
        except Exception:
            # 退化到 IDW
            results = self._engine.interpolate(
                {"method": "IDW", "pow": 2, "radius": 100.0},
                pts_list
            )
            zs = np.array(results, dtype=np.float64)
            zs[~np.isfinite(zs)] = np.nan
            return zs

    def _query_matplotlib(self, pts_xy: np.ndarray) -> np.ndarray:
        """matplotlib 批量线性插值"""
        zs = self._engine(pts_xy[:, 0], pts_xy[:, 1])
        result = np.array(zs, dtype=np.float64)
        result[np.ma.getmaskarray(zs)] = np.nan
        return result

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
