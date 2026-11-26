# -*- coding: utf-8 -*-
"""
土石方工程量体积计算器

支持三种方法（已在 PRD 中确认）：
1. 平均断面法  V = Σ[(A_i + A_{i+1}) / 2 × L_i]
2. 棱台法      V = Σ[L_i / 6 × (A_i + A_{i+1} + 4×A_m)]
3. TIN 体积法  V = 地面 TIN 与设计面 TIN 之间的三维体积差
"""

from __future__ import annotations
import math
import numpy as np
from typing import Optional

from 土石方计算.models.section import (
    CrossSectionData,
    SectionAreaResult,
    SegmentVolume,
    VolumeResult,
)
from 土石方计算.models.alignment import Alignment
from 土石方计算.models.terrain import TINModel


class VolumeCalculator:
    """
    土石方体积计算器

    Usage
    -----
    >>> calc = VolumeCalculator()
    >>> result = calc.compute_all(sections, alignment)
    """

    def compute_all(
        self,
        sections: list[CrossSectionData],
        alignment: Alignment,
        compute_tin_volume: bool = False,
        ground_tin: Optional[TINModel] = None,
        design_tin: Optional[TINModel] = None,
    ) -> VolumeResult:
        """
        计算全线土石方工程量（平均断面法 + 棱台法，可选 TIN 体积法）。

        Parameters
        ----------
        sections : 已计算面积的横断面列表，按桩号升序排列
        alignment : 中心线（用于计算断面间中心线距离）
        compute_tin_volume : 是否同时计算 TIN 体积法
        ground_tin : 地面 TIN（TIN 体积法需要）
        design_tin : 设计面 TIN（TIN 体积法需要）

        Returns
        -------
        VolumeResult
        """
        valid = self._validated_sections(sections)
        if compute_tin_volume and (ground_tin is None or design_tin is None):
            raise ValueError("TIN 体积计算必须同时提供地面和设计 TIN")

        segments: list[SegmentVolume] = []
        for i in range(len(valid) - 1):
            seg = self._compute_segment(valid[i], valid[i + 1], alignment)
            segments.append(seg)

        result = VolumeResult(segments=segments, prismatoid_source="endpoint_average",
                              prismatoid_independent=False)

        if compute_tin_volume and ground_tin and design_tin:
            exc_vol, fill_vol = self._tin_volume_method(
                ground_tin, design_tin, alignment
            )
            result.tin_volume_excavation = exc_vol
            result.tin_volume_fill = fill_vol

        return result

    @staticmethod
    def _validated_sections(sections: list[CrossSectionData]) -> list[CrossSectionData]:
        """拒绝缺失断面，避免静默跨越无效区间；允许输入乱序后排序。"""
        for sec in sections:
            if not math.isfinite(sec.station):
                raise ValueError("断面桩号必须有限")
            ar = sec.area_result
            if ar is None:
                raise ValueError(f"桩号 {sec.station} 缺少面积结果，不能跳过区间")
            if not math.isfinite(ar.station) or not math.isclose(
                    sec.station, ar.station, rel_tol=0.0, abs_tol=1e-8):
                raise ValueError("面积结果桩号与断面桩号不一致")
            areas = [ar.excavation_total, ar.fill_area, *ar.excavation_by_layer.values()]
            if any(not math.isfinite(value) or value < 0 for value in areas):
                raise ValueError(f"桩号 {sec.station} 的面积必须有限且非负")
            components = (ar.backfill_area, ar.embankment_area)
            if any(value is not None for value in components):
                if any(value is None for value in components):
                    raise ValueError(f"桩号 {sec.station} 的恢复回填与设计填筑面积须同时给定")
                if any(not math.isfinite(value) or value < 0 for value in components):
                    raise ValueError(f"桩号 {sec.station} 的填方分项面积必须有限且非负")
                if not math.isclose(math.fsum(components), ar.fill_area, rel_tol=1e-9, abs_tol=1e-9):
                    raise ValueError(f"桩号 {sec.station} 的恢复回填与设计填筑之和不等于填方总面积")
        ordered = sorted(sections, key=lambda sec: sec.station)
        if any(b.station - a.station <= 1e-8 for a, b in zip(ordered, ordered[1:])):
            raise ValueError("断面桩号重复或间距过小")
        return ordered

    @staticmethod
    def _fill_component(area: SectionAreaResult, name: str) -> Optional[float]:
        value = getattr(area, name)
        # 无填方的断面可确定两项均为零；有填方却未分类时保留未知。
        return 0.0 if value is None and area.fill_area == 0 else value

    def _component_volumes(self, areas, length, *, actual_midpoint=False):
        result = {}
        for area_name, prefix in (("backfill_area", "backfill"), ("embankment_area", "embankment")):
            values = [self._fill_component(area, area_name) for area in areas]
            endpoint_values = (values[0], values[-1])
            result[prefix+"_avg"] = None if any(value is None for value in endpoint_values) else (
                self._average_section(*endpoint_values, length))
            result[prefix+"_prismatoid"] = None if any(value is None for value in values) else (
                self._prismatoid(values[0], values[-1], values[1] if actual_midpoint else
                                 (values[0]+values[-1])/2, length))
        return result

    # ------------------------------------------------------------------
    # 平均断面法 & 棱台法（逐段计算）
    # ------------------------------------------------------------------

    def _compute_segment(
        self,
        sec_a: CrossSectionData,
        sec_b: CrossSectionData,
        alignment: Alignment,
    ) -> SegmentVolume:
        """计算相邻两断面之间的工程量（平均断面法 + 棱台法）"""
        s0, s1 = sec_a.station, sec_b.station
        length = abs(s1 - s0)

        ar_a = sec_a.area_result
        ar_b = sec_b.area_result

        # --- 平均断面法 ---
        exc_avg = self._average_section(ar_a.excavation_total,
                                         ar_b.excavation_total, length)
        fill_avg = self._average_section(ar_a.fill_area,
                                          ar_b.fill_area, length)

        exc_by_layer_avg: dict[str, float] = {}
        exc_by_layer_prism: dict[str, float] = {}
        all_layers = set(ar_a.excavation_by_layer) | set(ar_b.excavation_by_layer)
        for layer in all_layers:
            a_area = ar_a.excavation_by_layer.get(layer, 0.0)
            b_area = ar_b.excavation_by_layer.get(layer, 0.0)
            exc_by_layer_avg[layer] = self._average_section(a_area, b_area, length)
            a_m_layer = (a_area + b_area) / 2.0
            exc_by_layer_prism[layer] = self._prismatoid(a_area, b_area, a_m_layer, length)

        # 兼容旧结果：中点为端面积均值，不能作为独立棱台法复核。
        a_m_exc = (ar_a.excavation_total + ar_b.excavation_total) / 2.0
        a_m_fill = (ar_a.fill_area + ar_b.fill_area) / 2.0
        exc_prism = self._prismatoid(ar_a.excavation_total,
                                      ar_b.excavation_total, a_m_exc, length)
        fill_prism = self._prismatoid(ar_a.fill_area,
                                       ar_b.fill_area, a_m_fill, length)

        return SegmentVolume(
            station_start=s0,
            station_end=s1,
            length=length,
            excavation_avg=exc_avg,
            excavation_prismatoid=exc_prism,
            excavation_by_layer_avg=exc_by_layer_avg,
            excavation_by_layer_prismatoid=exc_by_layer_prism,
            fill_avg=fill_avg,
            fill_prismatoid=fill_prism,
            **self._component_volumes([ar_a, ar_b], length),
        )

    @staticmethod
    def _average_section(a0: float, a1: float, length: float) -> float:
        """平均断面法：V = (A0 + A1) / 2 × L"""
        return (a0 + a1) / 2.0 * length

    @staticmethod
    def _prismatoid(a0: float, a1: float, am: float, length: float) -> float:
        """棱台法：V = L / 6 × (A0 + A1 + 4×Am)"""
        return length / 6.0 * (a0 + a1 + 4.0 * am)

    # ------------------------------------------------------------------
    # 棱台法（精确：在中点重新切割断面）
    # ------------------------------------------------------------------

    def compute_prismatoid_precise(
        self,
        sections: list[CrossSectionData],
        mid_sections: list[CrossSectionData],
        alignment: Alignment,
    ) -> VolumeResult:
        """
        精确棱台法：中间断面 A_m 由中点处实际切割的断面面积提供。

        Parameters
        ----------
        sections : 端部断面列表
        mid_sections : 中点断面列表（len = len(sections) - 1）
        """
        valid = self._validated_sections(sections)
        valid_mid = self._validated_sections(mid_sections)

        if len(valid) < 2 or len(valid_mid) != len(valid) - 1:
            raise ValueError("端部断面数量与中点断面数量不匹配")

        segments: list[SegmentVolume] = []
        for i in range(len(valid) - 1):
            midpoint = (valid[i].station + valid[i + 1].station) / 2.0
            if not math.isclose(valid_mid[i].station, midpoint, rel_tol=0.0, abs_tol=1e-8):
                raise ValueError(f"中点断面桩号不匹配：应为 {midpoint}")
            ar_a = valid[i].area_result
            ar_b = valid[i + 1].area_result
            ar_m = valid_mid[i].area_result
            length = abs(valid[i + 1].station - valid[i].station)

            exc_prism = self._prismatoid(ar_a.excavation_total,
                                          ar_b.excavation_total,
                                          ar_m.excavation_total, length)
            fill_prism = self._prismatoid(ar_a.fill_area,
                                           ar_b.fill_area,
                                           ar_m.fill_area, length)

            # 平均断面法作为对比
            exc_avg = self._average_section(ar_a.excavation_total,
                                             ar_b.excavation_total, length)
            fill_avg = self._average_section(ar_a.fill_area,
                                              ar_b.fill_area, length)

            layers = set(ar_a.excavation_by_layer) | set(ar_b.excavation_by_layer) | set(ar_m.excavation_by_layer)
            layer_avg = {name: self._average_section(
                ar_a.excavation_by_layer.get(name, 0.0),
                ar_b.excavation_by_layer.get(name, 0.0), length) for name in layers}
            layer_prism = {name: self._prismatoid(
                ar_a.excavation_by_layer.get(name, 0.0),
                ar_b.excavation_by_layer.get(name, 0.0),
                ar_m.excavation_by_layer.get(name, 0.0), length) for name in layers}

            segments.append(SegmentVolume(
                station_start=valid[i].station,
                station_end=valid[i + 1].station,
                length=length,
                excavation_avg=exc_avg,
                excavation_prismatoid=exc_prism,
                fill_avg=fill_avg,
                fill_prismatoid=fill_prism,
                excavation_by_layer_avg=layer_avg,
                excavation_by_layer_prismatoid=layer_prism,
                **self._component_volumes([ar_a, ar_m, ar_b], length, actual_midpoint=True),
            ))

        return VolumeResult(segments=segments, prismatoid_source="actual_mid_sections",
                            prismatoid_independent=True)

    # ------------------------------------------------------------------
    # TIN 体积法
    # ------------------------------------------------------------------

    @staticmethod
    def _tin_volume_method(
        ground_tin: TINModel,
        design_tin: TINModel,
        alignment: Alignment,
    ) -> tuple[float, float]:
        """
        两个分片线性高程面的共同有效域体积差，不代表埋管施工实体量。

        先求两套三角片的平面交集，使每片内两个高程面均为平面，
        再按零高差线分开挖填区域并精确积分。部分覆盖只计算交集，
        调用方必须另行检查工程范围覆盖完整性；无正面积交集则报错。

        Returns
        -------
        (excavation_volume, fill_volume) 单位 m³
        """
        from shapely.strtree import STRtree

        # 两个模型使用同一局部原点，避免大地坐标引起几何求交精度损失。
        if ground_tin.is_empty or design_tin.is_empty:
            raise ValueError("TIN 体积计算不接受空模型")
        origin = np.asarray(ground_tin.points, dtype=float)[0, :2]
        ground = VolumeCalculator._prepare_tin_faces(ground_tin, origin, "地面")
        design = VolumeCalculator._prepare_tin_faces(design_tin, origin, "设计")
        tree = STRtree([face[0] for face in design])
        excavation, fill = [], []
        common_area = 0.0
        for g_polygon, g_xy0, g_z0, g_gradient in ground:
            for index in tree.query(g_polygon, predicate="intersects"):
                d_polygon, d_xy0, d_z0, d_gradient = design[int(index)]
                overlap = g_polygon.intersection(d_polygon)
                if overlap.is_empty or overlap.area == 0:
                    continue
                # 两个非退化三角形的正面积交集必为凸多边形。
                if overlap.geom_type != "Polygon":
                    raise ValueError("三角片交集不是有效多边形")
                common_area += overlap.area
                xy = np.asarray(overlap.exterior.coords[:-1], dtype=float)
                difference = (g_z0 - d_z0
                              + (xy - g_xy0) @ g_gradient
                              - (xy - d_xy0) @ d_gradient)
                vertices = np.column_stack([xy, difference])
                excavation.append(VolumeCalculator._positive_piece_volume(vertices))
                vertices[:, 2] *= -1.0
                fill.append(VolumeCalculator._positive_piece_volume(vertices))
        if common_area <= 0:
            raise ValueError("地面和设计 TIN 没有正面积共同有效域")
        return math.fsum(excavation), math.fsum(fill)

    @staticmethod
    def _prepare_tin_faces(tin: TINModel, origin: np.ndarray, label: str):
        """校验单值高程网格，返回三角片及局部平面系数，拒绝重复覆盖。"""
        from shapely.geometry import Polygon
        from shapely.strtree import STRtree

        points = np.asarray(tin.points, dtype=float)
        triangles = np.asarray(tin.triangles)
        if (points.ndim != 2 or points.shape[1] != 3
                or not np.isfinite(points).all()):
            raise ValueError(f"{label} TIN 顶点必须是有限的三维坐标")
        if (triangles.ndim != 2 or triangles.shape[1] != 3 or len(triangles) == 0
                or not np.issubdtype(triangles.dtype, np.integer)
                or np.any(triangles < 0) or np.any(triangles >= len(points))):
            raise ValueError(f"{label} TIN 三角片索引无效")
        faces = []
        xy = points[:, :2] - origin
        for indices in triangles:
            corners, heights = xy[indices], points[indices, 2]
            polygon = Polygon(corners)
            delta = corners[1:] - corners[0]
            determinant = float(np.linalg.det(delta))
            if (not polygon.is_valid or polygon.area <= 0
                    or abs(determinant) <= np.finfo(float).eps * np.max(np.abs(delta)) ** 2 * 8):
                raise ValueError(f"{label} TIN 存在退化三角片")
            gradient = np.linalg.solve(delta, heights[1:] - heights[0])
            if not np.isfinite(gradient).all():
                raise ValueError(f"{label} TIN 面方程无效")
            faces.append((polygon, corners[0], heights[0], gradient))
        polygons = [face[0] for face in faces]
        tree = STRtree(polygons)
        for i, polygon in enumerate(polygons):
            for j in tree.query(polygon, predicate="intersects"):
                if j <= i:
                    continue
                # 共享边允许；正面积重叠会导致重复计量，不能自动修复。
                overlap = polygon.intersection(polygons[int(j)]).area
                tolerance = np.finfo(float).eps * max(polygon.area, polygons[int(j)].area) * 64
                if overlap > tolerance:
                    raise ValueError(f"{label} TIN 三角片平面覆盖重叠")
        return faces

    @staticmethod
    def _positive_piece_volume(vertices: np.ndarray) -> float:
        """将凸多边形按线性高差非负半平面裁切，再按三角扇积分。"""
        clipped = []
        previous = vertices[-1]
        for current in vertices:
            previous_inside, current_inside = previous[2] >= 0, current[2] >= 0
            if previous_inside != current_inside:
                fraction = previous[2] / (previous[2] - current[2])
                crossing = previous + fraction * (current - previous)
                crossing[2] = 0.0
                clipped.append(crossing)
            if current_inside:
                clipped.append(current)
            previous = current
        if len(clipped) < 3:
            return 0.0
        contributions = []
        first = clipped[0]
        for left, right in zip(clipped[1:-1], clipped[2:]):
            a, b = left[:2] - first[:2], right[:2] - first[:2]
            area = abs(a[0] * b[1] - a[1] * b[0]) / 2.0
            contributions.append(area * (first[2] + left[2] + right[2]) / 3.0)
        return max(0.0, math.fsum(contributions))

    # ------------------------------------------------------------------
    # 汇总统计辅助
    # ------------------------------------------------------------------

    @staticmethod
    def summarize_by_layer(result: VolumeResult) -> dict[str, float]:
        """按地质层汇总平均断面法开挖量"""
        return result.total_by_layer_avg()

    @staticmethod
    def comparison_table(result: VolumeResult) -> dict[str, float | str | bool | None]:
        """
        生成三种方法的对比汇总。

        Returns
        -------
        dict with keys: 'avg_section_exc', 'prismatoid_exc', 'tin_exc',
                        'avg_section_fill', 'prismatoid_fill', 'tin_fill',
                        'diff_exc_pct'（棱台法与平均断面法差异百分比）
        """
        avg_exc = result.total_excavation_avg
        prism_exc = result.total_excavation_prismatoid
        avg_fill = result.total_fill_avg
        prism_fill = result.total_fill_prismatoid

        diff_pct = (
            abs(prism_exc - avg_exc) / avg_exc * 100.0
            if avg_exc > 1e-6 else 0.0
        )

        return {
            "avg_section_exc": avg_exc,
            "prismatoid_exc": prism_exc,
            "tin_exc": result.tin_volume_excavation,
            "avg_section_fill": avg_fill,
            "prismatoid_fill": prism_fill,
            "avg_section_backfill": result.total_backfill_avg,
            "prismatoid_backfill": result.total_backfill_prismatoid,
            "avg_section_embankment": result.total_embankment_avg,
            "prismatoid_embankment": result.total_embankment_prismatoid,
            "tin_fill": result.tin_volume_fill,
            "diff_exc_pct": diff_pct,
            "prismatoid_source": result.prismatoid_source,
            "prismatoid_independent": result.prismatoid_independent,
        }
