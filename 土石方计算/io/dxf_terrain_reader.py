# -*- coding: utf-8 -*-
"""
DXF 地形数据读取器

支持：
- 等高线（3D LWPOLYLINE / POLYLINE / SPLINE）→ 离散采样点 + 约束边
- 高程点（POINT / TEXT / INSERT）→ 散点
- 渠道中心线（LWPOLYLINE）→ 平面折点列表
- 地质分层线（按图层区分）→ 3D 折点列表

已确认决策（PRD 9.1）：等高线高程直接从 Z 坐标读取（3D 多段线）
"""

from __future__ import annotations
import os
import math
import numpy as np
from typing import Optional

from 土石方计算.models.terrain import TerrainPoint, ConstraintEdge


class DXFTerrainReader:
    """
    DXF 地形数据读取器

    Usage
    -----
    >>> reader = DXFTerrainReader("terrain.dxf")
    >>> points, edges = reader.read_contours(layer="等高线", interval=1.0)
    >>> elev_pts = reader.read_elevation_points(layer="高程点")
    >>> cl_pts = reader.read_centerline(layer="中心线")
    """

    def __init__(self, dxf_path: str):
        if not os.path.exists(dxf_path):
            raise FileNotFoundError(f"DXF 文件不存在: {dxf_path}")
        self._path = dxf_path
        self._doc = None   # 懒加载，调用 _ensure_loaded() 后填充

    # ------------------------------------------------------------------
    # 等高线读取
    # ------------------------------------------------------------------

    def read_contours(
        self,
        layer: Optional[str] = None,
        interval: float = 1.0,
        layer_filter: Optional[list[str]] = None,
    ) -> tuple[list[TerrainPoint], list[ConstraintEdge]]:
        """
        读取等高线并离散化为采样点 + 约束边。

        Parameters
        ----------
        layer : 指定图层名（None 表示读取所有图层）
        interval : 离散化间距（m），默认 1.0m，0 表示只取折点不加密
        layer_filter : 图层名列表（白名单过滤），优先于 layer 参数

        Returns
        -------
        (points, edges) — 所有等高线的采样点和约束边
        """
        self._ensure_loaded()
        all_points: list[TerrainPoint] = []
        all_edges: list[ConstraintEdge] = []

        entity_types = ["LWPOLYLINE", "POLYLINE", "SPLINE"]
        for entity in self._doc.modelspace():
            if entity.dxftype() not in entity_types:
                continue
            if not self._match_layer(entity, layer, layer_filter):
                continue

            pts_3d = self._extract_polyline_3d(entity)
            if not pts_3d or len(pts_3d) < 2:
                continue

            sampled = self._discretize_contour(pts_3d, interval)
            offset = len(all_points)
            all_points.extend(sampled)
            # 连接相邻采样点为约束边
            for i in range(len(sampled) - 1):
                all_edges.append(ConstraintEdge(i=offset + i, j=offset + i + 1))

        return all_points, all_edges

    def read_elevation_points(
        self,
        layer: Optional[str] = None,
        layer_filter: Optional[list[str]] = None,
    ) -> list[TerrainPoint]:
        """
        读取离散高程点（POINT 实体，高程从 Z 坐标获取）。
        """
        self._ensure_loaded()
        result: list[TerrainPoint] = []
        for entity in self._doc.modelspace():
            if entity.dxftype() != "POINT":
                continue
            if not self._match_layer(entity, layer, layer_filter):
                continue
            loc = entity.dxf.location
            if abs(loc.z) < 1e-9:
                continue   # Z=0 通常是平面图中的无效高程
            result.append(TerrainPoint(
                x=float(loc.x), y=float(loc.y), z=float(loc.z),
                source="elevation_point"
            ))
        return result

    # ------------------------------------------------------------------
    # 中心线读取
    # ------------------------------------------------------------------

    def read_centerline(
        self,
        layer: Optional[str] = None,
    ) -> list[tuple[float, float]]:
        """
        读取渠道中心线（LWPOLYLINE）的平面折点列表。

        若有多条多段线，取最长的一条。

        Returns
        -------
        list of (x, y)
        """
        self._ensure_loaded()
        best: list[tuple[float, float]] = []
        best_len = 0.0

        for entity in self._doc.modelspace():
            if entity.dxftype() not in ("LWPOLYLINE", "POLYLINE"):
                continue
            if layer and entity.dxf.layer.upper() != layer.upper():
                continue
            pts = self._extract_polyline_xy(entity)
            if len(pts) < 2:
                continue
            total = sum(
                math.hypot(pts[i + 1][0] - pts[i][0],
                           pts[i + 1][1] - pts[i][1])
                for i in range(len(pts) - 1)
            )
            if total > best_len:
                best_len = total
                best = pts

        return best

    # ------------------------------------------------------------------
    # 地质分层线读取
    # ------------------------------------------------------------------

    def read_geology_layers(
        self,
        layer_map: dict[str, str],
    ) -> dict[str, list[list[tuple[float, float, float]]]]:
        """
        读取地质分层线（3D 多段线），按图层分组。

        Parameters
        ----------
        layer_map : {dxf_layer_name: geology_layer_name}
            DXF 图层名到地质层名的映射

        Returns
        -------
        {geology_layer_name: [polyline_pts, ...]}
            每条线是 [(x, y, z), ...] 列表
        """
        self._ensure_loaded()
        result: dict[str, list[list[tuple[float, float, float]]]] = {
            v: [] for v in layer_map.values()
        }
        for entity in self._doc.modelspace():
            if entity.dxftype() not in ("LWPOLYLINE", "POLYLINE"):
                continue
            dxf_layer = entity.dxf.layer
            if dxf_layer not in layer_map:
                continue
            geo_name = layer_map[dxf_layer]
            pts_3d = self._extract_polyline_3d(entity)
            if pts_3d:
                result[geo_name].append(pts_3d)
        return result

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _ensure_loaded(self):
        if self._doc is None:
            try:
                import ezdxf
            except ImportError as exc:
                raise ImportError("未安装 ezdxf 库，请执行: pip install ezdxf") from exc
            self._doc = ezdxf.readfile(self._path)

    @staticmethod
    def _match_layer(
        entity,
        layer: Optional[str],
        layer_filter: Optional[list[str]],
    ) -> bool:
        ent_layer = entity.dxf.layer
        if layer_filter:
            return ent_layer in layer_filter
        if layer:
            return ent_layer.upper() == layer.upper()
        return True

    @staticmethod
    def _extract_polyline_3d(entity) -> list[tuple[float, float, float]]:
        """从多段线实体提取 3D 折点（X, Y, Z）"""
        pts: list[tuple[float, float, float]] = []
        try:
            if entity.dxftype() == "LWPOLYLINE":
                # LWPOLYLINE 本身是 2D，Z 来自 dxf.elevation 或折点扩展数据
                elev = getattr(entity.dxf, "elevation", 0.0)
                for v in entity.vertices():
                    pts.append((float(v[0]), float(v[1]), float(elev)))
            elif entity.dxftype() == "POLYLINE":
                for v in entity.vertices:
                    loc = v.dxf.location
                    pts.append((float(loc.x), float(loc.y), float(loc.z)))
            elif entity.dxftype() == "SPLINE":
                for pt in entity.control_points:
                    pts.append((float(pt[0]), float(pt[1]), float(pt[2])))
        except Exception:
            pass
        return pts

    @staticmethod
    def _extract_polyline_xy(entity) -> list[tuple[float, float]]:
        """从多段线提取 2D 折点（X, Y）"""
        pts: list[tuple[float, float]] = []
        try:
            if entity.dxftype() == "LWPOLYLINE":
                for v in entity.vertices():
                    pts.append((float(v[0]), float(v[1])))
            elif entity.dxftype() == "POLYLINE":
                for v in entity.vertices:
                    loc = v.dxf.location
                    pts.append((float(loc.x), float(loc.y)))
        except Exception:
            pass
        return pts

    @staticmethod
    def _discretize_contour(
        pts_3d: list[tuple[float, float, float]],
        interval: float,
    ) -> list[TerrainPoint]:
        """
        将等高线折点序列按间距 interval 加密采样。

        若 interval <= 0，仅返回折点本身（不加密）。
        """
        if not pts_3d:
            return []

        result: list[TerrainPoint] = []
        # 始终保留第一个折点
        result.append(TerrainPoint(
            x=pts_3d[0][0], y=pts_3d[0][1], z=pts_3d[0][2],
            source="contour"
        ))

        if interval <= 0:
            for x, y, z in pts_3d[1:]:
                result.append(TerrainPoint(x=x, y=y, z=z, source="contour"))
            return result

        accumulated = 0.0
        for i in range(len(pts_3d) - 1):
            x0, y0, z0 = pts_3d[i]
            x1, y1, z1 = pts_3d[i + 1]
            seg_len = math.hypot(x1 - x0, y1 - y0)
            if seg_len < 1e-10:
                continue
            # 在此段上按 interval 插入点
            t = (interval - accumulated) / seg_len
            while t <= 1.0 + 1e-9:
                t_clamped = min(t, 1.0)
                px = x0 + t_clamped * (x1 - x0)
                py = y0 + t_clamped * (y1 - y0)
                pz = z0 + t_clamped * (z1 - z0)
                result.append(TerrainPoint(x=px, y=py, z=pz, source="contour"))
                t += interval / seg_len
            # 本段走完后剩余的累积距离（供下一段续接）
            accumulated = seg_len - (t - interval / seg_len) * seg_len

        # 始终保留最后一个折点
        last = pts_3d[-1]
        if result and (abs(result[-1].x - last[0]) > 1e-9
                       or abs(result[-1].y - last[1]) > 1e-9):
            result.append(TerrainPoint(
                x=last[0], y=last[1], z=last[2], source="contour"
            ))
        return result

    # ------------------------------------------------------------------
    # 图层预览辅助（UI 用）
    # ------------------------------------------------------------------

    def list_layers(self) -> list[str]:
        """列出 DXF 文件中所有图层名"""
        self._ensure_loaded()
        return [layer.dxf.name for layer in self._doc.layers]

    def preview_layer_entities(
        self, layer: str
    ) -> dict[str, int]:
        """
        统计指定图层中各类型实体的数量，用于 UI 预览确认。

        Returns
        -------
        {'LWPOLYLINE': 12, 'POINT': 5, ...}
        """
        self._ensure_loaded()
        counts: dict[str, int] = {}
        for entity in self._doc.modelspace():
            if entity.dxf.layer.upper() == layer.upper():
                t = entity.dxftype()
                counts[t] = counts.get(t, 0) + 1
        return counts
