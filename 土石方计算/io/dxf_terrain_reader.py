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
        read_text: bool = False,
        z_min: float = -math.inf,
        z_max: float = math.inf,
    ) -> list[TerrainPoint]:
        """
        读取离散高程点，支持三种实体类型：

        - POINT 实体：高程直接从 Z 坐标获取
        - TEXT / MTEXT 实体：高程从文字内容解析（需为纯数字），
          XY 坐标取文字插入点，Z 取解析出的高程值
        - INSERT（块参照）：若块名含数字则尝试解析为高程（适配部分测量软件）

        Parameters
        ----------
        layer : 指定图层名（None 读全部）
        layer_filter : 图层白名单列表
        read_text : 是否读取 TEXT/MTEXT 实体（默认 True）
        z_min / z_max : 有效高程范围过滤（默认 -1000 ~ 9000 m）
        """
        self._ensure_loaded()
        result: list[TerrainPoint] = []

        for entity in self._doc.modelspace():
            if not self._match_layer(entity, layer, layer_filter):
                continue

            etype = entity.dxftype()

            if etype == "POINT":
                loc = entity.dxf.location
                z = float(loc.z)
                if z_min <= z <= z_max:
                    result.append(TerrainPoint(
                        x=float(loc.x), y=float(loc.y), z=z,
                        source="elevation_point"
                    ))

            elif read_text and (layer or layer_filter) and etype in ("TEXT", "MTEXT"):
                try:
                    if etype == "TEXT":
                        text_str = entity.dxf.text.strip()
                        ins = entity.dxf.insert
                        x, y = float(ins.x), float(ins.y)
                    else:  # MTEXT
                        text_str = entity.plain_mtext().strip()
                        ins = entity.dxf.insert
                        x, y = float(ins.x), float(ins.y)
                    z = float(text_str)
                    if z_min <= z <= z_max:
                        result.append(TerrainPoint(
                            x=x, y=y, z=z, source="text_elevation"
                        ))
                except (ValueError, AttributeError):
                    pass  # 文字内容不是纯数字，跳过

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
                if entity.has_arc:
                    from ezdxf.path import make_path
                    pts = [tuple(map(float, p)) for p in make_path(entity).flattening(0.05)]
                else:
                    pts = [tuple(map(float, p)) for p in entity.vertices_in_wcs()]
                    if entity.closed and pts:
                        pts.append(pts[0])
            elif entity.dxftype() == "POLYLINE":
                if entity.is_2d_polyline and any(v.dxf.get("bulge", 0) for v in entity.vertices):
                    from ezdxf.path import make_path
                    pts = [tuple(map(float, p)) for p in make_path(entity).flattening(0.05)]
                else:
                    pts = [tuple(map(float, p)) for p in entity.points_in_wcs()]
                    if entity.is_closed and pts:
                        pts.append(pts[0])
            elif entity.dxftype() == "SPLINE":
                pts = [tuple(map(float, p)) for p in entity.flattening(0.05)]
        except Exception:
            pass
        return pts

    def read_terrain_sources(self, *, terrain_options=None, cancelled=None, corridor=None, on_scanned=None):
        """Read source identities and WCS heights for the independent workbench.

        Layer selection is conservative: unknown survey layers are returned as
        confirmation items. Numeric labels never become independent XYZ points.
        A caller may explicitly pair labels with selected point markers.
        """
        options = dict(terrain_options or {})
        point_names = {"GCD", "高程点", "测点", "测量点", "ELEVATION", "SPOT_HEIGHT", "SURVEY_POINTS"}
        contour_names = {"SQX", "JQX", "等高线", "计曲线", "首曲线", "CONTOUR", "CONTOURS"}
        explicit_points = options.get("point_layers")
        explicit_contours = options.get("contour_layers")
        if isinstance(explicit_points, str) or isinstance(explicit_contours, str):
            raise ValueError("测点/等高线图层应为图层名称列表")
        point_layers = {str(v).upper() for v in explicit_points} if explicit_points is not None else point_names
        contour_layers = {str(v).upper() for v in explicit_contours} if explicit_contours is not None else contour_names
        tolerance = float(options.get("curve_tolerance", 0.05))
        if not math.isfinite(tolerance) or tolerance <= 0:
            raise ValueError("地形曲线离散误差必须有限且大于零")
        if corridor is not None:
            return self._stream_terrain_sources(
                point_layers, contour_layers, options, tolerance, corridor, cancelled, on_scanned)
        from .terrain_preprocessor import _gcd_circle_markers

        self._ensure_loaded()
        model = self._doc.modelspace()
        circles = _gcd_circle_markers(model, point_layers=point_layers)
        return self._collect_terrain_sources(
            model, self._doc.units, {layer.dxf.name.upper() for layer in self._doc.layers},
            point_layers, contour_layers, options, tolerance, circles, None, cancelled)

    def _stream_terrain_sources(self, point_layers, contour_layers, options, tolerance, corridor, cancelled, on_scanned):
        from ezdxf.addons.iterdxf import modelspace
        from ezdxf.filemanagement import dxf_file_info
        from .terrain_preprocessor import _gcd_circle_markers

        units = dxf_file_info(self._path).insert_units
        data = self._collect_terrain_sources(modelspace(self._path), units, set(), point_layers,
            contour_layers, options, tolerance, {}, corridor, cancelled, on_scanned)
        if data["report"]["possible_point_circles"]:
            # Check the less common marker/label schema only when the first
            # scan actually encountered candidate marker circles.
            circles = _gcd_circle_markers(modelspace(self._path, types=("CIRCLE", "TEXT")),
                                           point_layers=point_layers)
            if circles:
                del data
                corridor.counts.clear()
                data = self._collect_terrain_sources(modelspace(self._path), units, set(), point_layers,
                    contour_layers, options, tolerance, circles, corridor, cancelled, on_scanned)
        return data

    @staticmethod
    def _collect_terrain_sources(model, units, layers, point_layers, contour_layers, options,
                                 tolerance, circles, corridor, cancelled, on_scanned=None):
        from collections import Counter
        from ezdxf.path import make_path
        from .terrain_preprocessor import _original_handle

        def add(entity, kind, source_kind, positions):
            source = {"kind": kind, "layer": entity.dxf.layer, "source_handle": _original_handle(entity),
                      "source_kind": source_kind, "points": positions}
            if kind == "polyline":
                source["cad_source"] = {
                    "color": entity.dxf.get("color", 256),
                    "true_color": entity.dxf.get("true_color"),
                    "xdata_apps": sorted(entity.xdata.data) if entity.xdata else [],
                }
            sources.extend(corridor.select(source) if corridor is not None else [source])

        # The second source drawing uses GCD circles and GCD contours. Enable
        # that schema only after the original circle/label correspondence is proven.
        explicit_points = options.get("point_layers")
        explicit_contours = options.get("contour_layers")
        standard_contour_layers = {"SQX", "JQX", "等高线", "计曲线", "首曲线", "CONTOUR", "CONTOURS"}
        if circles and explicit_contours is None:
            contour_layers = contour_layers | point_layers
        sources, counts, candidates, ignored_labels, invalid = [], Counter(), Counter(), 0, []
        possible_circles = 0
        curve_kinds = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"}
        for index, entity in enumerate(model):
            if cancelled and index % 256 == 0 and cancelled():
                raise InterruptedError("已取消地形读取")
            if on_scanned and index and index % 20000 == 0:
                on_scanned(index, len(sources))
            kind, layer = entity.dxftype(), entity.dxf.layer
            upper = layer.upper()
            counts[f"{layer}/{kind}"] += 1
            xyz = None
            source_kind = kind
            if upper in point_layers:
                if kind == "CIRCLE" and 0 < entity.dxf.radius <= 0.5:
                    possible_circles += 1
                if kind == "POINT":
                    xyz = list(entity.dxf.location)
                elif kind == "INSERT":
                    xyz = list(entity.ocs().to_wcs(entity.dxf.insert))
                elif kind == "CIRCLE" and entity.dxf.handle in circles:
                    xyz = list(entity.ocs().to_wcs(entity.dxf.center))
                    source_kind = "CIRCLE_CENTER_WITH_LABEL"
            if xyz is not None:
                if not all(math.isfinite(float(v)) for v in xyz):
                    invalid.append({"source_handle": _original_handle(entity), "layer": layer,
                                    "reason": "测点坐标或高程非有限数"})
                    continue
                add(entity, "point", source_kind, [list(map(float, xyz))])
                continue
            if (upper in contour_layers and kind in curve_kinds
                    and not (upper in point_layers and upper not in standard_contour_layers
                             and explicit_contours is None and kind not in ("LWPOLYLINE", "POLYLINE"))):
                if kind == "CIRCLE" and entity.dxf.handle in circles:
                    continue
                if kind == "POLYLINE" and not (entity.is_2d_polyline or entity.is_3d_polyline):
                    continue
                try:
                    if kind == "POLYLINE" and entity.is_3d_polyline:
                        positions = list(entity.points_in_wcs())
                        if entity.is_closed and positions:
                            positions.append(positions[0])
                    elif kind == "LWPOLYLINE" and not entity.has_arc:
                        positions = list(entity.vertices_in_wcs())
                        if entity.closed and positions:
                            positions.append(positions[0])
                    else:
                        positions = list(make_path(entity).flattening(tolerance))
                    values = [list(map(float, p)) for p in positions]
                    if len(values) < 2 or not np.isfinite(values).all():
                        raise ValueError("等高线没有有效三维线形")
                    add(entity, "polyline", kind, values)
                except (ValueError, TypeError, AttributeError) as exc:
                    invalid.append({"source_handle": _original_handle(entity), "layer": layer,
                                    "reason": str(exc)})
            elif kind in ("TEXT", "MTEXT"):
                ignored_labels += 1
            elif kind in ("POINT", "INSERT") or kind in curve_kinds:
                candidates[f"{layer}/{kind}"] += 1
        selected = {str(v).upper() for v in list(explicit_points or []) + list(explicit_contours or [])}
        existing = layers | {v.rsplit("/", 1)[0].upper() for v in counts}
        report = {"reader": "ezdxf_streaming_wcs_sources" if corridor is not None else "ezdxf_wcs_sources",
                  "source_insunits": units,
                  "source_layer_types": dict(counts), "point_layers": sorted(point_layers & existing),
                  "contour_layers": sorted(contour_layers & existing),
                  "point_entity_count": sum(v["kind"] == "point" for v in sources),
                  "contour_entity_count": sum(v["kind"] == "polyline" for v in sources),
                  "ignored_label_count": ignored_labels, "numeric_text_policy": "labels_only_never_independent_points",
                  "candidate_layer_types": dict(candidates), "invalid_entities": invalid,
                  "missing_selected_layers": sorted(selected - existing), "curve_tolerance_m": tolerance,
                  "ambiguous_layers": [], "automatic_noise_filter": True,
                  "recognized_entity_count": len(sources),
                  "ignored_entity_count": sum(counts.values()) - len(sources),
                  "source_layout": "gcd_circle_markers_with_gcd_contours" if circles else "survey_points_and_contours"}
        if corridor is not None:
            report.update(corridor_preparation=corridor.report(), possible_point_circles=possible_circles,
                          source_has_3dface=any(key.endswith("/3DFACE") for key in counts),
                          stream_reader="ezdxf.addons.iterdxf.modelspace")
        # A valid standard survey schema need not ask about unrelated map layers.
        # Unknown layers are shown when no supported measurement source exists.
        if not sources and candidates:
            report["ambiguous_layers"] = sorted({v.rsplit("/", 1)[0] for v in candidates})
        return {"sources": sources, "report": report}

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

        for i in range(len(pts_3d) - 1):
            x0, y0, z0 = pts_3d[i]
            x1, y1, z1 = pts_3d[i + 1]
            seg_len = math.hypot(x1 - x0, y1 - y0)
            if seg_len < 1e-10:
                continue
            # Retain every surveyed corner; optional refinement only inserts
            # points on its original segments rather than cutting corners.
            count = max(1, int(math.ceil(seg_len / interval)))
            for at in range(1, count+1):
                t = at / count
                px = x0 + t * (x1 - x0)
                py = y0 + t * (y1 - y0)
                pz = z0 + t * (z1 - z0)
                result.append(TerrainPoint(x=px, y=py, z=pz, source="contour"))

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
