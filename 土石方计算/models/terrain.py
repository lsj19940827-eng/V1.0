# -*- coding: utf-8 -*-
"""
地形数据模型

包含：
- TerrainPoint   — 单个三维地形点 (X, Y, Z)
- ConstraintEdge — 约束边（等高线离散化后的相邻点连线）
- TINModel       — 三角不规则网模型（CDT 构建结果 + 空间索引句柄）
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Any
import numpy as np


@dataclass
class TerrainPoint:
    """单个三维地形点"""
    x: float
    y: float
    z: float
    source: str = ""  # 数据来源标识，如 'contour'/'elevation_point'/'csv'

    def as_array(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z], dtype=np.float64)


@dataclass
class ConstraintEdge:
    """
    约束边（CDT 中强制存在的边）

    i, j 是点集 list[TerrainPoint] 中的索引，表示这两点之间
    必须作为三角形的边（等高线相邻采样点之间的连线）。
    """
    i: int
    j: int


@dataclass
class TINModel:
    """
    三角不规则网模型（Triangulated Irregular Network）

    由 TINBuilder 构建后填充，供 TINInterpolator 使用。

    Attributes
    ----------
    points : np.ndarray  shape=(N, 3)  所有顶点 (X, Y, Z)
    triangles : np.ndarray  shape=(M, 3)  三角形顶点索引
    constraint_edges : list[ConstraintEdge]  原始约束边
    spatial_index : Any  KDTree 或 R-tree 空间索引句柄（懒加载）
    source_files : list[str]  构建本 TIN 所用源文件路径（用于缓存失效检测）
    source_mtimes : list[float]  对应源文件的修改时间戳
    """
    points: np.ndarray = field(default_factory=lambda: np.empty((0, 3)))
    triangles: np.ndarray = field(default_factory=lambda: np.empty((0, 3), dtype=int))
    constraint_edges: list[ConstraintEdge] = field(default_factory=list)
    spatial_index: Optional[Any] = field(default=None, repr=False)
    source_files: list[str] = field(default_factory=list)
    source_mtimes: list[float] = field(default_factory=list)

    @property
    def num_points(self) -> int:
        return len(self.points)

    @property
    def num_triangles(self) -> int:
        return len(self.triangles)

    @property
    def is_empty(self) -> bool:
        return self.num_points == 0

    def get_bbox(self) -> tuple[float, float, float, float]:
        """返回 TIN 的平面包围盒 (xmin, ymin, xmax, ymax)"""
        if self.is_empty:
            return (0.0, 0.0, 0.0, 0.0)
        xs = self.points[:, 0]
        ys = self.points[:, 1]
        return (float(xs.min()), float(ys.min()),
                float(xs.max()), float(ys.max()))
