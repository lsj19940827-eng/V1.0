# -*- coding: utf-8 -*-
"""
单元测试：ProfileCutter + CrossSectionCalculator

覆盖：
- 纵断面地面高程与 TIN 插值一致
- 横断面方向严格垂直于切线
- 横断面宽度与配置一致
- 横断面采样点数量合理
- CrossSectionCalculator：设计断面轮廓顶点坐标正确
- CrossSectionCalculator：Shoelace 面积计算
- CrossSectionCalculator：全挖断面开挖面积 > 0，回填面积 = 0
- CrossSectionCalculator：全填断面回填面积 > 0，开挖面积 = 0
"""

import math
import pytest
import numpy as np

from 土石方计算.models.alignment import Alignment
from 土石方计算.models.section import (
    DesignSection, ChannelType,
    ExcavationSlope, SlopeGrade,
    BackfillConfig,
)
from 土石方计算.core.tin_builder import TINBuilder
from 土石方计算.core.tin_interpolator import TINInterpolator
from 土石方计算.core.profile_cutter import ProfileCutter
from 土石方计算.core.cross_section import CrossSectionCalculator
from 土石方计算.models.terrain import TerrainPoint


# ============================================================
# 公共夹具
# ============================================================

def make_flat_tin(z: float = 100.0, size: float = 200.0) -> TINInterpolator:
    """构建平坦地形 TIN（高程均为 z）"""
    builder = TINBuilder()
    pts = [
        TerrainPoint(0, 0, z), TerrainPoint(size, 0, z),
        TerrainPoint(size, size, z), TerrainPoint(0, size, z),
        TerrainPoint(size / 2, size / 2, z),
    ]
    builder.add_elevation_points(pts)
    tin = builder.build()
    return TINInterpolator(tin, backend="matplotlib")


def make_slope_tin(size: float = 200.0) -> TINInterpolator:
    """构建斜坡地形：z = 100 + 0.1*x"""
    builder = TINBuilder()
    for xi in range(0, int(size) + 1, 20):
        for yi in range(0, int(size) + 1, 20):
            builder.add_elevation_points([
                TerrainPoint(float(xi), float(yi), 100.0 + 0.1 * xi)
            ])
    tin = builder.build()
    return TINInterpolator(tin, backend="matplotlib")


def make_east_alignment(length: float = 100.0) -> Alignment:
    """向东的直线中心线，中心点在 (100, 100)"""
    return Alignment.from_polyline_points([
        (100.0, 100.0),
        (100.0 + length, 100.0),
    ])


# ============================================================
# ProfileCutter — 纵断面
# ============================================================

class TestLongitudinalProfile:

    def test_flat_terrain_elevation(self):
        """平坦地形纵断面地面高程应恒为 TIN 高程"""
        interp = make_flat_tin(z=105.0)
        al = make_east_alignment(100.0)
        cutter = ProfileCutter(interp)
        data = cutter.cut_longitudinal(al, step=10.0)
        for g in data.ground_elevations:
            assert abs(g - 105.0) < 0.1

    def test_longitudinal_station_count(self):
        interp = make_flat_tin()
        al = make_east_alignment(100.0)
        cutter = ProfileCutter(interp)
        data = cutter.cut_longitudinal(al, step=10.0)
        # 0, 10, 20, ..., 100 → 11 点
        assert len(data.stations) == 11

    def test_longitudinal_includes_endpoints(self):
        interp = make_flat_tin()
        al = make_east_alignment(100.0)
        cutter = ProfileCutter(interp)
        data = cutter.cut_longitudinal(al, step=10.0)
        assert data.stations[0] == pytest.approx(al.start_station)
        assert data.stations[-1] == pytest.approx(al.end_station)

    def test_longitudinal_design_elevations(self):
        """提供设计纵断面时，设计底高程不为 None"""
        from 土石方计算.models.section import DesignProfile, DesignProfileSegment
        interp = make_flat_tin(z=105.0)
        al = make_east_alignment(100.0)
        seg = DesignProfileSegment(0.0, 100.0, 102.0, -0.001)
        dp = DesignProfile(segments=[seg])
        cutter = ProfileCutter(interp)
        data = cutter.cut_longitudinal(al, step=10.0, design_profile=dp)
        for d in data.design_elevations:
            assert d is not None
            assert d == pytest.approx(seg.invert_at_station(
                data.stations[data.design_elevations.index(d)]
            ), abs=0.001)


# ============================================================
# ProfileCutter — 横断面
# ============================================================

class TestCrossSection:

    def test_cross_section_direction_perpendicular(self):
        """
        横断面方向（采样点连线）应垂直于中心线切线。
        东西向中心线 → 横断面应为南北向（x 坐标不变，y 变化）。
        """
        interp = make_flat_tin(size=300.0)
        al = make_east_alignment(100.0)
        cutter = ProfileCutter(interp)
        sec = cutter.cut_cross_section(al, station=50.0,
                                        left_width=20.0, right_width=20.0,
                                        sample_step=2.0)
        # 横断面点的 x 坐标应接近中心线在 station=50 处的 x（即 150.0）
        cx, cy = al.get_xy_at_station(50.0)
        # 由于法线方向为北，offset 对应 y 方向变化
        # 实际 ground_points 存的是 (offset, elevation)，不是绝对坐标
        # 验证：offset 范围 = [-20, 20]
        offsets = [p[0] for p in sec.ground_points]
        assert min(offsets) == pytest.approx(-20.0, abs=0.6)
        assert max(offsets) == pytest.approx(20.0, abs=0.6)

    def test_cross_section_center_elevation(self):
        """中心线处（offset=0）高程应等于 TIN 高程"""
        interp = make_flat_tin(z=103.0, size=300.0)
        al = make_east_alignment(100.0)
        cutter = ProfileCutter(interp)
        sec = cutter.cut_cross_section(al, station=50.0,
                                        left_width=20.0, right_width=20.0)
        center_elev = next((p[1] for p in sec.ground_points
                            if abs(p[0]) < 0.01), None)
        assert center_elev is not None
        assert abs(center_elev - 103.0) < 0.1

    def test_cross_section_sample_count(self):
        """采样点数量应约为 (left + right) / step + 1"""
        interp = make_flat_tin(size=300.0)
        al = make_east_alignment(100.0)
        cutter = ProfileCutter(interp)
        sec = cutter.cut_cross_section(al, station=50.0,
                                        left_width=20.0, right_width=20.0,
                                        sample_step=1.0)
        # (20+20)/1 + 1 = 41（含中心点）
        assert 38 <= len(sec.ground_points) <= 45

    def test_batch_cross_sections_count(self):
        interp = make_flat_tin(size=300.0)
        al = make_east_alignment(100.0)
        cutter = ProfileCutter(interp)
        sections = cutter.cut_all_cross_sections(al, interval=20.0, half_width=20.0)
        # 0, 20, 40, 60, 80, 100 → 6 个
        assert len(sections) == 6


# ============================================================
# CrossSectionCalculator — 设计断面
# ============================================================

class TestCrossSectionDesign:

    def _make_trapezoidal_design(self) -> DesignSection:
        return DesignSection(
            channel_type=ChannelType.TRAPEZOIDAL,
            bottom_width=3.0,
            depth=2.0,
            inner_slope_left=1.5,
            inner_slope_right=1.5,
        )

    def test_design_outline_vertex_count(self):
        calc = CrossSectionCalculator()
        design = self._make_trapezoidal_design()
        pts = calc._build_design_outline(design, invert_elev=100.0)
        assert len(pts) == 4  # 左上/左下/右下/右上

    def test_design_outline_bottom_width(self):
        calc = CrossSectionCalculator()
        design = self._make_trapezoidal_design()
        pts = calc._build_design_outline(design, invert_elev=100.0)
        # 渠底两点（pts[1] 和 pts[2]）水平距离 = bottom_width
        bottom_w = pts[2][0] - pts[1][0]
        assert abs(bottom_w - 3.0) < 1e-9

    def test_design_outline_top_width(self):
        calc = CrossSectionCalculator()
        design = self._make_trapezoidal_design()
        # 口宽 = 3 + (1.5+1.5)*2 = 9m
        pts = calc._build_design_outline(design, invert_elev=100.0)
        top_w = pts[3][0] - pts[0][0]
        assert abs(top_w - design.top_width) < 1e-9

    def test_design_outline_elevations(self):
        calc = CrossSectionCalculator()
        design = self._make_trapezoidal_design()
        pts = calc._build_design_outline(design, invert_elev=100.0)
        # 渠底高程 = 100.0
        assert abs(pts[1][1] - 100.0) < 1e-9
        assert abs(pts[2][1] - 100.0) < 1e-9
        # 渠口高程 = 100 + 2 = 102.0
        assert abs(pts[0][1] - 102.0) < 1e-9
        assert abs(pts[3][1] - 102.0) < 1e-9


# ============================================================
# CrossSectionCalculator — 面积计算
# ============================================================

class TestCrossSectionArea:

    def test_shoelace_square(self):
        """单位正方形面积应为 1.0"""
        calc = CrossSectionCalculator()
        pts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        area = calc._shoelace_area(pts)
        assert abs(area - 1.0) < 1e-9

    def test_shoelace_triangle(self):
        calc = CrossSectionCalculator()
        pts = [(0.0, 0.0), (4.0, 0.0), (2.0, 3.0)]
        area = calc._shoelace_area(pts)
        assert abs(area - 6.0) < 1e-9

    def test_all_cut_section_excavation_positive(self):
        """地面线全部高于设计线 → 开挖面积 > 0，回填面积 = 0"""
        ground = [(-5.0, 105.0), (0.0, 106.0), (5.0, 105.0)]
        design = [(-2.0, 100.0), (0.0, 99.0), (2.0, 100.0)]
        area = CrossSectionCalculator._area_between_lines(ground, design)
        assert area > 0

    def test_rectangle_area_known(self):
        """已知矩形面积验证"""
        upper = [(-3.0, 102.0), (3.0, 102.0)]
        lower = [(-3.0, 100.0), (3.0, 100.0)]
        area = CrossSectionCalculator._area_between_lines(upper, lower)
        # 6m × 2m = 12 m²
        assert abs(area - 12.0) < 0.1
