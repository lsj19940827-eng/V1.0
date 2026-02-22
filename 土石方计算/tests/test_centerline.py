# -*- coding: utf-8 -*-
"""
单元测试：Alignment（渠道中心线）

覆盖：
- 从折点列表构建（累计桩号正确）
- 从桩号坐标表构建
- get_xy_at_station 插值精度
- get_tangent_angle_at_station 方向角正确性
- get_normal_direction 与切线垂直
- get_station_at_xy 近似投影
- sample_stations 间距均匀 + 边界处理
- 不足 2 点时抛异常
"""

import math
import pytest
import numpy as np

from 土石方计算.models.alignment import Alignment, AlignmentPoint, ChainageBreak
from 土石方计算.io.csv_reader import CSVTerrainReader


# ============================================================
# 测试数据工厂
# ============================================================

def make_straight_alignment(
    length: float = 1000.0,
    n_pts: int = 5,
    angle_deg: float = 0.0
) -> Alignment:
    """生成一条直线中心线（沿 angle 方向）"""
    angle = math.radians(angle_deg)
    pts = []
    for i in range(n_pts):
        s = length / (n_pts - 1) * i
        x = s * math.cos(angle)
        y = s * math.sin(angle)
        pts.append((x, y))
    return Alignment.from_polyline_points(pts)


def make_l_shape_alignment() -> Alignment:
    """生成 L 形中心线：先向东 500m，再向北 500m"""
    pts = [(0, 0), (500, 0), (500, 500)]
    return Alignment.from_polyline_points(pts)


# ============================================================
# 构建测试
# ============================================================

class TestAlignmentConstruction:

    def test_from_polyline_total_length(self):
        al = make_straight_alignment(length=1000.0, n_pts=6)
        assert abs(al.total_length - 1000.0) < 1e-6

    def test_from_station_table(self):
        rows = [(0.0, 0.0, 0.0), (100.0, 100.0, 0.0), (200.0, 200.0, 100.0)]
        al = Alignment.from_station_table(rows)
        assert al.start_station == 0.0
        assert al.end_station == 200.0

    def test_too_few_points_raises(self):
        with pytest.raises(ValueError):
            Alignment.from_polyline_points([(0, 0)])

    def test_start_station_offset(self):
        al = Alignment.from_polyline_points([(0, 0), (100, 0)],
                                              start_station=500.0)
        assert al.start_station == pytest.approx(500.0)
        assert al.end_station == pytest.approx(600.0)


# ============================================================
# 坐标查询
# ============================================================

class TestAlignmentQuery:

    def test_xy_at_start(self):
        al = make_straight_alignment(length=500.0, angle_deg=0.0)
        x, y = al.get_xy_at_station(0.0)
        assert abs(x) < 1e-6 and abs(y) < 1e-6

    def test_xy_at_end(self):
        al = make_straight_alignment(length=500.0, angle_deg=0.0)
        x, y = al.get_xy_at_station(500.0)
        assert abs(x - 500.0) < 1e-6
        assert abs(y) < 1e-6

    def test_xy_midpoint(self):
        al = make_straight_alignment(length=500.0, angle_deg=0.0)
        x, y = al.get_xy_at_station(250.0)
        assert abs(x - 250.0) < 1e-6
        assert abs(y) < 1e-6

    def test_xy_l_shape_corner(self):
        al = make_l_shape_alignment()
        # 桩号 500 恰好在拐角
        x, y = al.get_xy_at_station(500.0)
        assert abs(x - 500.0) < 1e-6
        assert abs(y) < 1e-6

    def test_xy_l_shape_after_corner(self):
        al = make_l_shape_alignment()
        # 桩号 750 应在竖段中点
        x, y = al.get_xy_at_station(750.0)
        assert abs(x - 500.0) < 1e-6
        assert abs(y - 250.0) < 1e-6

    def test_xy_beyond_end_clamps(self):
        al = make_straight_alignment(length=100.0)
        x, y = al.get_xy_at_station(9999.0)
        x_end, y_end = al.get_xy_at_station(100.0)
        assert abs(x - x_end) < 1e-6
        assert abs(y - y_end) < 1e-6


# ============================================================
# 方向角
# ============================================================

class TestAlignmentTangent:

    def test_tangent_east(self):
        """向东水平线，切线方向应为 0 弧度"""
        al = make_straight_alignment(angle_deg=0.0)
        angle = al.get_tangent_angle_at_station(500.0)
        assert abs(angle) < 0.01

    def test_tangent_northeast_45(self):
        """45° 斜线，切线应为 π/4"""
        al = make_straight_alignment(angle_deg=45.0)
        angle = al.get_tangent_angle_at_station(200.0)
        assert abs(angle - math.pi / 4) < 0.05

    def test_normal_perpendicular_to_tangent(self):
        """法线方向 = 切线 + π/2"""
        al = make_straight_alignment(angle_deg=30.0)
        for s in [100.0, 300.0, 500.0]:
            tang = al.get_tangent_angle_at_station(s)
            norm = al.get_normal_direction(s)
            assert abs(abs(norm - tang) - math.pi / 2) < 0.01

    def test_tangent_l_shape_horizontal_segment(self):
        al = make_l_shape_alignment()
        angle = al.get_tangent_angle_at_station(250.0)
        assert abs(angle) < 0.05  # 接近 0（向东）

    def test_tangent_l_shape_vertical_segment(self):
        al = make_l_shape_alignment()
        angle = al.get_tangent_angle_at_station(600.0)
        assert abs(angle - math.pi / 2) < 0.05  # 接近 π/2（向北）


# ============================================================
# 反查桩号
# ============================================================

class TestAlignmentReverseQuery:

    def test_get_station_at_origin(self):
        al = make_straight_alignment(length=1000.0, angle_deg=0.0)
        s = al.get_station_at_xy(0.0, 0.0)
        assert abs(s) < 1.0

    def test_get_station_at_midpoint(self):
        al = make_straight_alignment(length=1000.0, angle_deg=0.0)
        s = al.get_station_at_xy(500.0, 0.0)
        assert abs(s - 500.0) < 1.0

    def test_get_station_offset_point(self):
        """偏离中心线的点，投影到最近位置"""
        al = make_straight_alignment(length=1000.0, angle_deg=0.0)
        s = al.get_station_at_xy(300.0, 50.0)  # 偏离 50m
        assert abs(s - 300.0) < 5.0


# ============================================================
# 桩号采样
# ============================================================

class TestAlignmentSampling:

    def test_sample_includes_endpoints(self):
        al = make_straight_alignment(length=1000.0)
        stations = al.sample_stations(100.0)
        assert stations[0] == pytest.approx(al.start_station)
        assert stations[-1] == pytest.approx(al.end_station)

    def test_sample_interval(self):
        al = make_straight_alignment(length=1000.0)
        stations = al.sample_stations(100.0)
        # 连续间距应约为 100m
        diffs = np.diff(stations)
        assert all(d <= 100.01 for d in diffs)

    def test_sample_extra_stations(self):
        al = make_straight_alignment(length=1000.0)
        extra = [150.0, 350.0, 750.0]
        stations = al.sample_stations(100.0, extra_stations=extra)
        for s in extra:
            assert any(abs(st - s) < 1e-6 for st in stations)


# ============================================================
# 桩号格式解析
# ============================================================

class TestStationParsing:

    @pytest.mark.parametrize("s_str, expected", [
        ("1500.0", 1500.0),
        ("K1+500", 1500.0),
        ("K0+100.5", 100.5),
        ("k0+050", 50.0),
        ("0+000", 0.0),
        ("2+300.25", 2300.25),
    ])
    def test_parse_station_formats(self, s_str, expected):
        result = CSVTerrainReader._parse_station(s_str)
        assert abs(result - expected) < 1e-6

    def test_invalid_station_raises(self):
        with pytest.raises(ValueError):
            CSVTerrainReader._parse_station("ABC")
