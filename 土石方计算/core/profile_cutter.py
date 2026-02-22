# -*- coding: utf-8 -*-
"""
断面切割器

负责：
1. 纵断面切割 — 沿中心线按指定步长采样 TIN 高程，生成纵断面地面线
2. 横断面切割 — 在指定桩号处，垂直中心线切割 TIN，生成横断面地面线

返回结构均使用 models.section 中的数据类。
"""

from __future__ import annotations
import math
import numpy as np
from typing import Optional

from 土石方计算.models.alignment import Alignment
from 土石方计算.models.section import (
    CrossSectionData,
    LongitudinalData,
    DesignProfile,
    ExcavationSlope,
    SlopeGrade,
    GeologySectionProfile,
)
from 土石方计算.core.tin_interpolator import TINInterpolator


class ProfileCutter:
    """
    断面切割器

    Usage
    -----
    >>> cutter = ProfileCutter(interpolator)
    >>> long_data = cutter.cut_longitudinal(alignment, step=1.0)
    >>> sections = cutter.cut_all_cross_sections(
    ...     alignment, interval=20.0, extra_stations=[150.0],
    ...     half_width=30.0, sample_step=0.5
    ... )
    """

    def __init__(self, interpolator: TINInterpolator):
        self._interp = interpolator

    # ------------------------------------------------------------------
    # 纵断面
    # ------------------------------------------------------------------

    def cut_longitudinal(
        self,
        alignment: Alignment,
        step: float = 1.0,
        design_profile: Optional[DesignProfile] = None,
        extra_stations: Optional[list[float]] = None,
    ) -> LongitudinalData:
        """
        沿中心线生成纵断面地面线。

        Parameters
        ----------
        alignment : 中心线对象
        step : 采样步长（m），默认 1.0m
        design_profile : 设计纵断面（可选），若提供则同时计算设计底高程
        extra_stations : 额外必须包含的桩号

        Returns
        -------
        LongitudinalData — 包含桩号列表、地面高程、设计底高程
        """
        stations = alignment.sample_stations(step, extra_stations)
        coords_xy = np.array([alignment.get_xy_at_station(s) for s in stations])
        ground_elevs = self._interp.query_batch(coords_xy)

        design_elevs: list[Optional[float]] = []
        for s in stations:
            if design_profile is not None:
                design_elevs.append(design_profile.get_invert_at_station(s))
            else:
                design_elevs.append(None)

        return LongitudinalData(
            stations=list(stations),
            ground_elevations=[
                float(z) if not np.isnan(z) else float("nan")
                for z in ground_elevs
            ],
            design_elevations=design_elevs,
        )

    # ------------------------------------------------------------------
    # 横断面（单个）
    # ------------------------------------------------------------------

    def cut_cross_section(
        self,
        alignment: Alignment,
        station: float,
        left_width: float,
        right_width: float,
        sample_step: float = 0.5,
        geology_profile: Optional[GeologySectionProfile] = None,
    ) -> CrossSectionData:
        """
        在指定桩号处切割横断面地面线。

        断面方向：垂直于中心线切线（法线方向）。
        offset 坐标系：中心线处为 0，左侧为负，右侧为正。

        Parameters
        ----------
        station : 桩号（m）
        left_width : 左半宽（m，正值）
        right_width : 右半宽（m，正值）
        sample_step : 采样间距（m），默认 0.5m
        geology_profile : 该桩号处的地质分层数据（可选）

        Returns
        -------
        CrossSectionData — ground_points 为 [(offset, elevation), ...]
        """
        cx, cy = alignment.get_xy_at_station(station)
        normal_angle = alignment.get_normal_direction(station)
        cos_n = math.cos(normal_angle)
        sin_n = math.sin(normal_angle)

        # 生成采样点（以偏距 offset 为主坐标）
        offsets = np.arange(-left_width, right_width + 1e-9, sample_step)
        # 确保中心点在内
        if 0.0 not in offsets:
            offsets = np.sort(np.append(offsets, 0.0))

        xs = cx + offsets * cos_n
        ys = cy + offsets * sin_n
        pts_xy = np.column_stack([xs, ys])
        elevs = self._interp.query_batch(pts_xy)

        ground_points = [
            (float(off), float(z))
            for off, z in zip(offsets, elevs)
        ]

        return CrossSectionData(
            station=station,
            ground_points=ground_points,
            design_points=[],          # 由 CrossSectionCalculator 填充
            excavation_boundary=[],    # 由 CrossSectionCalculator 填充
            geology_profile=geology_profile,
            left_width=float(left_width),
            right_width=float(right_width),
        )

    # ------------------------------------------------------------------
    # 横断面（批量）
    # ------------------------------------------------------------------

    def cut_all_cross_sections(
        self,
        alignment: Alignment,
        interval: float = 20.0,
        extra_stations: Optional[list[float]] = None,
        half_width: Optional[float] = None,
        left_widths: Optional[dict[float, float]] = None,
        right_widths: Optional[dict[float, float]] = None,
        sample_step: float = 0.5,
        geology_profiles: Optional[dict[float, GeologySectionProfile]] = None,
    ) -> list[CrossSectionData]:
        """
        批量生成全线横断面地面线。

        Parameters
        ----------
        interval : 断面间距（m）
        extra_stations : 额外桩号（关键位置）
        half_width : 统一半宽（左右相同），若 None 则使用 left/right_widths
        left_widths : {station: left_width} 字典（逐断面覆盖）
        right_widths : {station: right_width} 字典
        sample_step : 横断面采样间距（m）
        geology_profiles : {station: GeologySectionProfile} 字典

        Returns
        -------
        list[CrossSectionData]
        """
        stations = alignment.sample_stations(interval, extra_stations)
        results: list[CrossSectionData] = []

        _lw = left_widths or {}
        _rw = right_widths or {}
        _geo = geology_profiles or {}
        _hw = half_width or 30.0

        for s in stations:
            lw = _lw.get(s, _hw)
            rw = _rw.get(s, _hw)
            geo = _geo.get(s)
            cs = self.cut_cross_section(
                alignment, s, lw, rw, sample_step, geo
            )
            results.append(cs)

        return results

    # ------------------------------------------------------------------
    # 横断面宽度自动估算
    # ------------------------------------------------------------------

    @staticmethod
    def estimate_section_width(
        design_top_width: float,
        excavation_slope_config: Optional[ExcavationSlope] = None,
        margin_factor: float = 2.0,
        extra_margin: float = 5.0,
    ) -> float:
        """
        根据设计断面口宽自动估算横断面半宽。

        Parameters
        ----------
        design_top_width : 设计断面口宽（m）
        excavation_slope_config : 开挖边坡配置（可选，用于估算开挖范围）
        margin_factor : 扩展系数（默认 2.0）
        extra_margin : 额外余量（m，默认 5.0）

        Returns
        -------
        估算的半宽（m）
        """
        base = design_top_width * margin_factor / 2.0
        if excavation_slope_config:
            # 估算最大开挖延伸宽度（按最大坡比 × 总高估算）
            max_ext = _estimate_slope_extension(
                excavation_slope_config.left_grades
            )
            base = max(base, design_top_width / 2.0 + max_ext)
        return base + extra_margin


def _estimate_slope_extension(grades: list[SlopeGrade]) -> float:
    """估算多级边坡从坡脚到坡顶的水平延伸距离（m）"""
    total = 0.0
    for g in grades:
        h = g.height if g.height != float("inf") else 20.0  # 无穷大时用 20m 估算
        total += g.ratio * h + g.berm_width
    return total
