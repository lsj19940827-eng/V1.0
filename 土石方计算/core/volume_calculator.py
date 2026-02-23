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
        # 过滤无面积结果的断面
        valid = [s for s in sections if s.area_result is not None]
        if len(valid) < 2:
            return VolumeResult()

        # 按桩号排序
        valid.sort(key=lambda s: s.station)

        segments: list[SegmentVolume] = []
        for i in range(len(valid) - 1):
            seg = self._compute_segment(valid[i], valid[i + 1], alignment)
            segments.append(seg)

        result = VolumeResult(segments=segments)

        if compute_tin_volume and ground_tin and design_tin:
            exc_vol, fill_vol = self._tin_volume_method(
                ground_tin, design_tin, alignment
            )
            result.tin_volume_excavation = exc_vol
            result.tin_volume_fill = fill_vol

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

        # --- 棱台法 ---
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
        sections : 端部断面列表（偶数下标对应 mid_sections）
        mid_sections : 中点断面列表（len = len(sections) - 1）
        """
        valid = [s for s in sections if s.area_result is not None]
        valid_mid = [s for s in mid_sections if s.area_result is not None]

        if len(valid) < 2 or len(valid_mid) != len(valid) - 1:
            raise ValueError("端部断面数量与中点断面数量不匹配")

        segments: list[SegmentVolume] = []
        for i in range(len(valid) - 1):
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

            segments.append(SegmentVolume(
                station_start=valid[i].station,
                station_end=valid[i + 1].station,
                length=length,
                excavation_avg=exc_avg,
                excavation_prismatoid=exc_prism,
                fill_avg=fill_avg,
                fill_prismatoid=fill_prism,
            ))

        return VolumeResult(segments=segments)

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
        TIN 体积法：地面 TIN 与设计面 TIN 之间的三维体积差。

        方法：遍历地面 TIN 的三角形，对每个三角形的三个顶点
        分别查询设计面高程，计算三角棱柱体积（正值为挖，负值为填）。

        Returns
        -------
        (excavation_volume, fill_volume) 单位 m³
        """
        from 土石方计算.core.tin_interpolator import TINInterpolator

        if design_tin.is_empty or ground_tin.is_empty:
            return 0.0, 0.0

        design_interp = TINInterpolator(design_tin)
        g_pts = ground_tin.points      # shape=(N, 3)
        g_tris = ground_tin.triangles  # shape=(M, 3)

        total_exc = 0.0
        total_fill = 0.0

        # 批量查询所有地面 TIN 顶点在设计面的高程
        design_z = design_interp.query_batch(g_pts[:, :2])
        # nan 表示超出设计面范围，跳过
        diff_z = g_pts[:, 2] - np.where(np.isnan(design_z), g_pts[:, 2], design_z)

        for tri in g_tris:
            i0, i1, i2 = tri
            d0, d1, d2 = diff_z[i0], diff_z[i1], diff_z[i2]
            # 跳过任何顶点在设计面范围外的三角形
            if any(np.isnan([d0, d1, d2])):
                continue
            # 三角形面积
            p0 = g_pts[i0, :2]
            p1 = g_pts[i1, :2]
            p2 = g_pts[i2, :2]
            tri_area = 0.5 * abs(
                (p1[0] - p0[0]) * (p2[1] - p0[1])
                - (p2[0] - p0[0]) * (p1[1] - p0[1])
            )
            # 棱柱体积（顶部平均高差 × 底面积）
            avg_diff = (d0 + d1 + d2) / 3.0
            vol = tri_area * avg_diff
            if vol > 0:
                total_exc += vol
            else:
                total_fill += abs(vol)

        return total_exc, total_fill

    # ------------------------------------------------------------------
    # 汇总统计辅助
    # ------------------------------------------------------------------

    @staticmethod
    def summarize_by_layer(result: VolumeResult) -> dict[str, float]:
        """按地质层汇总平均断面法开挖量"""
        return result.total_by_layer_avg()

    @staticmethod
    def comparison_table(result: VolumeResult) -> dict[str, float]:
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
        prism_fill = result.total_fill_avg  # 棱台法回填

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
            "tin_fill": result.tin_volume_fill,
            "diff_exc_pct": diff_pct,
        }
