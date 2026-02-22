# -*- coding: utf-8 -*-
"""
单元测试：VolumeCalculator

覆盖：
- 平均断面法公式验证（矩形棱柱精确解）
- 棱台法公式验证
- 两方法差异百分比在合理范围
- 分层汇总累加正确
- 空断面列表返回空结果
- comparison_table 键完整
"""

import math
import pytest
import numpy as np

from 土石方计算.models.section import (
    CrossSectionData,
    SectionAreaResult,
    VolumeResult,
    SegmentVolume,
)
from 土石方计算.models.alignment import Alignment
from 土石方计算.core.volume_calculator import VolumeCalculator


# ============================================================
# 构造辅助
# ============================================================

def make_section(
    station: float,
    exc_area: float,
    fill_area: float = 0.0,
    exc_by_layer: dict = None,
    ground_elev: float = 105.0,
    invert_elev: float = 100.0,
) -> CrossSectionData:
    ar = SectionAreaResult(
        station=station,
        excavation_total=exc_area,
        excavation_by_layer=exc_by_layer or {},
        fill_area=fill_area,
        ground_elevation_center=ground_elev,
        design_invert_elevation=invert_elev,
        cut_depth=ground_elev - invert_elev,
    )
    sec = CrossSectionData(
        station=station,
        ground_points=[],
        design_points=[],
        excavation_boundary=[],
        area_result=ar,
    )
    return sec


def make_straight_alignment(length: float = 1000.0) -> Alignment:
    return Alignment.from_polyline_points([(0, 0), (length, 0)])


# ============================================================
# 平均断面法验证
# ============================================================

class TestAverageSectionMethod:

    def test_rectangle_exact(self):
        """
        两个相同断面（矩形棱柱），精确解 = A × L。
        A = 10 m², L = 50 m → V = 500 m³
        """
        sec_a = make_section(0.0, exc_area=10.0)
        sec_b = make_section(50.0, exc_area=10.0)
        al = make_straight_alignment(50.0)
        calc = VolumeCalculator()
        result = calc.compute_all([sec_a, sec_b], al)
        assert len(result.segments) == 1
        seg = result.segments[0]
        assert abs(seg.excavation_avg - 500.0) < 1e-6

    def test_trapezoid_average_formula(self):
        """
        两断面面积不同（A0=10, A1=20）：V = (10+20)/2 × 100 = 1500 m³
        """
        sec_a = make_section(0.0, exc_area=10.0)
        sec_b = make_section(100.0, exc_area=20.0)
        al = make_straight_alignment(100.0)
        calc = VolumeCalculator()
        result = calc.compute_all([sec_a, sec_b], al)
        assert abs(result.total_excavation_avg - 1500.0) < 1e-6

    def test_zero_area_section(self):
        sec_a = make_section(0.0, exc_area=0.0)
        sec_b = make_section(100.0, exc_area=0.0)
        al = make_straight_alignment(100.0)
        calc = VolumeCalculator()
        result = calc.compute_all([sec_a, sec_b], al)
        assert result.total_excavation_avg == pytest.approx(0.0)

    def test_fill_volume_computed(self):
        sec_a = make_section(0.0, exc_area=5.0, fill_area=3.0)
        sec_b = make_section(50.0, exc_area=5.0, fill_area=3.0)
        al = make_straight_alignment(50.0)
        calc = VolumeCalculator()
        result = calc.compute_all([sec_a, sec_b], al)
        assert abs(result.total_fill_avg - 150.0) < 1e-6  # (3+3)/2 × 50


# ============================================================
# 棱台法验证
# ============================================================

class TestPrismatoidMethod:

    def test_rectangle_prismatoid_equals_avg(self):
        """
        矩形棱柱（两端面积相等）：棱台法 = 平均断面法。
        V = L/6 × (A + A + 4A) = L × A
        """
        sec_a = make_section(0.0, exc_area=10.0)
        sec_b = make_section(100.0, exc_area=10.0)
        al = make_straight_alignment(100.0)
        calc = VolumeCalculator()
        result = calc.compute_all([sec_a, sec_b], al)
        seg = result.segments[0]
        assert abs(seg.excavation_prismatoid - seg.excavation_avg) < 1e-6

    def test_prismatoid_formula(self):
        """
        A0=10, A1=20, A_m=(10+20)/2=15, L=100
        V = 100/6 × (10 + 20 + 4×15) = 100/6 × 90 = 1500
        （与平均断面法一致，因为 A_m 取了平均值）
        """
        sec_a = make_section(0.0, exc_area=10.0)
        sec_b = make_section(100.0, exc_area=20.0)
        al = make_straight_alignment(100.0)
        calc = VolumeCalculator()
        result = calc.compute_all([sec_a, sec_b], al)
        seg = result.segments[0]
        expected = 100.0 / 6.0 * (10.0 + 20.0 + 4.0 * 15.0)
        assert abs(seg.excavation_prismatoid - expected) < 1e-6

    def test_prismatoid_not_greater_than_avg_for_linear_area(self):
        """对于线性变化面积，棱台法结果 <= 平均断面法（保守估算）"""
        sec_a = make_section(0.0, exc_area=5.0)
        sec_b = make_section(100.0, exc_area=25.0)
        al = make_straight_alignment(100.0)
        calc = VolumeCalculator()
        result = calc.compute_all([sec_a, sec_b], al)
        seg = result.segments[0]
        # 线性变化时，棱台法 = 平均断面法（A_m 取平均）
        assert abs(seg.excavation_prismatoid - seg.excavation_avg) < 1e-6


# ============================================================
# 分层汇总
# ============================================================

class TestLayerSummary:

    def test_layer_totals_sum_to_total_approx(self):
        """各层之和应约等于开挖总量"""
        layers = {"土方": 6.0, "软石": 4.0}
        sec_a = make_section(0.0, exc_area=10.0, exc_by_layer=layers)
        sec_b = make_section(100.0, exc_area=10.0,
                              exc_by_layer={"土方": 7.0, "软石": 3.0})
        al = make_straight_alignment(100.0)
        calc = VolumeCalculator()
        result = calc.compute_all([sec_a, sec_b], al)
        layer_totals = result.total_by_layer_avg()
        total = sum(layer_totals.values())
        assert abs(total - result.total_excavation_avg) < 1e-6

    def test_layer_names_preserved(self):
        layers = {"残坡积层": 8.0, "强风化层": 2.0}
        sec_a = make_section(0.0, exc_area=10.0, exc_by_layer=layers)
        sec_b = make_section(50.0, exc_area=10.0, exc_by_layer=layers)
        al = make_straight_alignment(50.0)
        calc = VolumeCalculator()
        result = calc.compute_all([sec_a, sec_b], al)
        totals = result.total_by_layer_avg()
        assert "残坡积层" in totals
        assert "强风化层" in totals


# ============================================================
# 边界情况
# ============================================================

class TestVolumeEdgeCases:

    def test_empty_sections_returns_empty(self):
        calc = VolumeCalculator()
        al = make_straight_alignment()
        result = calc.compute_all([], al)
        assert result.total_excavation_avg == pytest.approx(0.0)
        assert len(result.segments) == 0

    def test_single_section_returns_empty(self):
        sec = make_section(0.0, exc_area=10.0)
        al = make_straight_alignment()
        calc = VolumeCalculator()
        result = calc.compute_all([sec], al)
        assert len(result.segments) == 0

    def test_multiple_segments_sum(self):
        """4 个断面 → 3 段，总量应等于各段之和"""
        sections = [
            make_section(0.0,   exc_area=10.0),
            make_section(100.0, exc_area=15.0),
            make_section(200.0, exc_area=12.0),
            make_section(300.0, exc_area=8.0),
        ]
        al = make_straight_alignment(300.0)
        calc = VolumeCalculator()
        result = calc.compute_all(sections, al)
        assert len(result.segments) == 3
        total = sum(s.excavation_avg for s in result.segments)
        assert abs(total - result.total_excavation_avg) < 1e-9


# ============================================================
# comparison_table
# ============================================================

class TestComparisonTable:

    def test_comparison_table_keys(self):
        sec_a = make_section(0.0, exc_area=10.0)
        sec_b = make_section(100.0, exc_area=20.0)
        al = make_straight_alignment(100.0)
        calc = VolumeCalculator()
        result = calc.compute_all([sec_a, sec_b], al)
        table = VolumeCalculator.comparison_table(result)
        required_keys = [
            "avg_section_exc", "prismatoid_exc",
            "avg_section_fill", "prismatoid_fill",
            "diff_exc_pct",
        ]
        for k in required_keys:
            assert k in table, f"缺少键: {k}"

    def test_diff_pct_zero_for_equal_areas(self):
        """两端面积相等时，棱台法与平均断面法差异为 0%"""
        sec_a = make_section(0.0, exc_area=10.0)
        sec_b = make_section(100.0, exc_area=10.0)
        al = make_straight_alignment(100.0)
        calc = VolumeCalculator()
        result = calc.compute_all([sec_a, sec_b], al)
        table = VolumeCalculator.comparison_table(result)
        assert abs(table["diff_exc_pct"]) < 1e-6
