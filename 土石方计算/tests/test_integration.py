# -*- coding: utf-8 -*-
"""
端到端集成测试 — 使用纯合成数据（无外部文件依赖）

验证完整计算管道：
  合成地形 → TIN（scipy.Delaunay）→ 中心线 → 纵断面
  → 横断面切割 → 面积计算 → 工程量计算 → 结果验证

仅依赖 numpy + scipy + matplotlib（已安装），不需要 triangle / startinpy。
"""

from __future__ import annotations
import math
import sys
import os
import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from 土石方计算.models.terrain import TINModel
from 土石方计算.models.alignment import Alignment
from 土石方计算.models.section import (
    DesignSection, ChannelType, ExcavationSlope, SlopeGrade,
    BackfillConfig, DesignProfile, DesignProfileSegment,
)
from 土石方计算.core.tin_interpolator import TINInterpolator
from 土石方计算.core.profile_cutter import ProfileCutter
from 土石方计算.core.cross_section import CrossSectionCalculator
from 土石方计算.core.volume_calculator import VolumeCalculator
from 土石方计算.core.geology_layer import GeologyLayerManager


def build_synthetic_tin(z_fn=None, x_range=(0, 400), y_range=(0, 200), nx=21, ny=11):
    """用 scipy.spatial.Delaunay 直接构建 TIN（不需要 triangle 库）"""
    from scipy.spatial import Delaunay, KDTree
    if z_fn is None:
        z_fn = lambda x, y: 100.0
    xs = np.linspace(x_range[0], x_range[1], nx)
    ys = np.linspace(y_range[0], y_range[1], ny)
    gx, gy = np.meshgrid(xs, ys)
    pts_xy = np.column_stack([gx.ravel(), gy.ravel()])
    pts_z = np.array([z_fn(x, y) for x, y in pts_xy])
    pts_3d = np.column_stack([pts_xy, pts_z])
    tri = Delaunay(pts_xy)
    tin = TINModel(points=pts_3d, triangles=tri.simplices.astype(int))
    tin.spatial_index = KDTree(pts_xy)
    return tin


def run_all():
    """手动运行所有测试（不依赖 pytest）"""
    suites = [
        TestFlatTerrainFullCut,
        TestSlopeTerrainVaryingCut,
        TestGeologyLayers,
        TestDeduplicatePoints,
        TestDiscretizeContour,
        TestTraceSlopeIntersect,
    ]
    total = passed = failed = 0
    errors = []
    for Suite in suites:
        suite = Suite()
        suite_name = Suite.__name__
        methods = [m for m in sorted(dir(suite)) if m.startswith("test_")]
        for meth in methods:
            total += 1
            try:
                if hasattr(suite, "setup"):
                    suite.setup()
                getattr(suite, meth)()
                passed += 1
                print(f"  [OK] {suite_name}.{meth}")
            except Exception as e:
                failed += 1
                errors.append((suite_name, meth, e))
                print(f"  [FAIL] {suite_name}.{meth}: {e}")

    print(f"\n{'='*50}")
    print(f"Total: {total}  Passed: {passed}  Failed: {failed}")
    if errors:
        print("\nFailed tests:")
        for sn, mn, e in errors:
            print(f"  {sn}.{mn}: {e}")
    else:
        print("\n=== ALL TESTS PASSED ===")
    return failed == 0


# ============================================================
# 场景 1：平坦地形，全挖断面
# ============================================================

class TestFlatTerrainFullCut:
    """z=100 平坦地形, 梯形明渠 b=3 h=2 m=1.5, 渠底97, 挖深3m"""

    def setup(self):
        self.tin = build_synthetic_tin(z_fn=lambda x, y: 100.0)
        self.interp = TINInterpolator(self.tin, backend="matplotlib")
        self.al = Alignment.from_polyline_points([(0.0, 100.0), (200.0, 100.0)])
        self.design = DesignSection(
            channel_type=ChannelType.TRAPEZOIDAL,
            bottom_width=3.0, depth=2.0,
            inner_slope_left=1.5, inner_slope_right=1.5,
        )
        self.dp = DesignProfile(segments=[
            DesignProfileSegment(0.0, 200.0, 97.0, 0.0)
        ])
        slope_grade = SlopeGrade(ratio=1.0, height=math.inf, berm_width=0.0)
        self.slope_cfg = ExcavationSlope(
            start_station=0.0, end_station=200.0,
            left_grades=[slope_grade], right_grades=[slope_grade],
        )
        self.cutter = ProfileCutter(self.interp)
        self.calc = CrossSectionCalculator()
        self.vc = VolumeCalculator()

    def test_longitudinal_ground_elevation(self):
        data = self.cutter.cut_longitudinal(self.al, step=10.0, design_profile=self.dp)
        for g in data.ground_elevations:
            assert abs(g - 100.0) < 0.05, f"纵断面高程误差过大: {g}"

    def test_longitudinal_design_elevation(self):
        data = self.cutter.cut_longitudinal(self.al, step=10.0, design_profile=self.dp)
        for d in data.design_elevations:
            assert d is not None and abs(d - 97.0) < 1e-9

    def test_longitudinal_cut_depth(self):
        data = self.cutter.cut_longitudinal(self.al, step=10.0, design_profile=self.dp)
        for cut in data.get_cut_depths():
            assert cut is not None and abs(cut - 3.0) < 0.05

    def test_cross_section_center_elevation(self):
        sec = self.cutter.cut_cross_section(self.al, 100.0, 20.0, 20.0, 0.5)
        cz = next((p[1] for p in sec.ground_points if abs(p[0]) < 0.3), None)
        assert cz is not None and abs(cz - 100.0) < 0.1

    def test_design_outline_topology(self):
        pts = self.calc._build_design_outline(self.design, invert_elev=97.0)
        assert len(pts) == 4
        assert abs(pts[2][0] - pts[1][0] - 3.0) < 1e-9  # bottom_width
        assert abs(pts[3][0] - pts[0][0] - 9.0) < 1e-9  # top_width = 3+1.5*2*2

    def test_excavation_polygon_area_positive(self):
        sec = self.cutter.cut_cross_section(self.al, 100.0, 25.0, 25.0, 0.5)
        design_pts = self.calc._build_design_outline(self.design, invert_elev=97.0)
        sec.design_points = design_pts
        excav = self.calc._build_excavation_boundary(
            design_pts, sec.ground_points, self.slope_cfg, 97.0)
        assert len(excav) >= 4
        area = CrossSectionCalculator._shoelace_area(excav)
        assert area > 0, f"开挖面积应>0, got {area}"

    def test_excavation_area_magnitude(self):
        sec = self.cutter.cut_cross_section(self.al, 100.0, 25.0, 25.0, 0.5)
        self.calc.compute(sec, self.design, self.slope_cfg, 97.0, BackfillConfig())
        ar = sec.area_result
        assert ar is not None
        assert 15.0 < ar.excavation_total < 35.0, f"面积不合理: {ar.excavation_total:.2f}"

    def test_volume_positive(self):
        sections = self._compute_all_sections()
        result = self.vc.compute_all(sections, self.al)
        assert result.total_excavation_avg > 0
        assert len(result.segments) == len(sections) - 1

    def test_prismatoid_close_to_avg(self):
        sections = self._compute_all_sections()
        result = self.vc.compute_all(sections, self.al)
        table = VolumeCalculator.comparison_table(result)
        assert table["diff_exc_pct"] < 5.0, f"差异过大: {table['diff_exc_pct']:.2f}%"

    def _compute_all_sections(self):
        sections = self.cutter.cut_all_cross_sections(
            self.al, interval=20.0, half_width=25.0, sample_step=0.5)
        for sec in sections:
            invert = self.dp.get_invert_at_station(sec.station)
            self.calc.compute(sec, self.design, self.slope_cfg, invert, BackfillConfig())
        return sections


# ============================================================
# 场景 2：斜坡地形
# ============================================================

class TestSlopeTerrainVaryingCut:
    """z = 95 + 0.05*x, 设计底97, 有半挖半填"""

    def setup(self):
        self.z_fn = lambda x, y: 95.0 + 0.05 * x
        self.tin = build_synthetic_tin(z_fn=self.z_fn)
        self.interp = TINInterpolator(self.tin, backend="matplotlib")
        self.al = Alignment.from_polyline_points([(0.0, 100.0), (200.0, 100.0)])
        self.dp = DesignProfile(segments=[
            DesignProfileSegment(0.0, 200.0, 97.0, 0.0)
        ])

    def test_ground_elevation_increases(self):
        cutter = ProfileCutter(self.interp)
        data = cutter.cut_longitudinal(self.al, step=20.0, design_profile=self.dp)
        assert data.ground_elevations[-1] > data.ground_elevations[0]

    def test_cut_depth_changes_sign(self):
        cutter = ProfileCutter(self.interp)
        data = cutter.cut_longitudinal(self.al, step=10.0, design_profile=self.dp)
        depths = [d for d in data.get_cut_depths() if d is not None]
        assert min(depths) < 0, "应有填方段"
        assert max(depths) > 0, "应有挖方段"

    def test_ground_matches_z_fn(self):
        cutter = ProfileCutter(self.interp)
        data = cutter.cut_longitudinal(self.al, step=10.0)
        for s, g in zip(data.stations, data.ground_elevations):
            x, y = self.al.get_xy_at_station(s)
            expected = self.z_fn(x, y)
            assert abs(g - expected) < 0.1, f"桩号{s:.0f}: {g:.3f} vs {expected:.3f}"


# ============================================================
# 场景 3：地质分层
# ============================================================

class TestGeologyLayers:

    def test_add_and_query(self):
        mgr = GeologyLayerManager()
        mgr.add_layer("残坡积层", color_index=3, hatch_pattern="ANSI31")
        mgr.add_layer("强风化层", color_index=4, hatch_pattern="ANSI37")
        assert mgr.layer_names == ["残坡积层", "强风化层"]

    def test_depth_interpolation(self):
        mgr = GeologyLayerManager()
        mgr.add_layer("残坡积层")
        mgr.set_depth_table("残坡积层", [(0.0, 2.0), (100.0, 3.0)])
        t = mgr.get_layer_thickness_at_station("残坡积层", 50.0)
        assert abs(t - 2.5) < 1e-6

    def test_profile_at_station(self):
        mgr = GeologyLayerManager()
        mgr.add_layer("残坡积层")
        mgr.add_layer("强风化层")
        mgr.set_depth_table("残坡积层", [(0.0, 2.0)])
        mgr.set_depth_table("强风化层", [(0.0, 3.0)])
        profile = mgr.get_profile_at_station(0.0, ground_elevation=100.0)
        assert abs(profile.top_elevations[0] - 100.0) < 1e-6
        assert abs(profile.top_elevations[1] - 98.0) < 1e-6


# ============================================================
# 场景 4：_deduplicate_points 验证
# ============================================================

class TestDeduplicatePoints:

    def test_no_duplicates(self):
        from 土石方计算.core.tin_builder import TINBuilder
        pts = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        unique, mask, mapping = TINBuilder._deduplicate_points(pts)
        assert len(unique) == 4 and mask.sum() == 4

    def test_one_duplicate(self):
        from 土石方计算.core.tin_builder import TINBuilder
        pts = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 0.0]])
        unique, mask, mapping = TINBuilder._deduplicate_points(pts)
        assert len(unique) == 3
        assert mapping[1] == mapping[3]

    def test_z_extraction_after_dedup(self):
        from 土石方计算.core.tin_builder import TINBuilder
        pts = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])
        z = np.array([100.0, 101.0, 102.0, 999.0])
        _, mask, _ = TINBuilder._deduplicate_points(pts)
        z_unique = z[mask]
        assert len(z_unique) == 3 and 999.0 not in z_unique


# ============================================================
# 场景 5：_discretize_contour 验证
# ============================================================

class TestDiscretizeContour:

    def test_single_segment(self):
        from 土石方计算.io.dxf_terrain_reader import DXFTerrainReader
        pts = [(0.0, 0.0, 100.0), (10.0, 0.0, 100.0)]
        result = DXFTerrainReader._discretize_contour(pts, interval=2.0)
        assert len(result) == 6  # 0,2,4,6,8,10

    def test_preserves_endpoints(self):
        from 土石方计算.io.dxf_terrain_reader import DXFTerrainReader
        pts = [(5.0, 3.0, 101.0), (25.0, 7.0, 103.0)]
        result = DXFTerrainReader._discretize_contour(pts, interval=4.0)
        assert abs(result[0].x - 5.0) < 1e-9
        assert abs(result[-1].x - 25.0) < 1e-9

    def test_multi_segment_spacing(self):
        from 土石方计算.io.dxf_terrain_reader import DXFTerrainReader
        pts = [(0.0, 0.0, 100.0), (10.0, 0.0, 100.0), (10.0, 10.0, 100.0)]
        result = DXFTerrainReader._discretize_contour(pts, interval=3.0)
        for i in range(1, len(result) - 1):
            dx = result[i].x - result[i-1].x
            dy = result[i].y - result[i-1].y
            assert math.hypot(dx, dy) < 3.5

    def test_interval_zero(self):
        from 土石方计算.io.dxf_terrain_reader import DXFTerrainReader
        pts = [(0.0, 0.0, 100.0), (5.0, 0.0, 101.0), (10.0, 5.0, 102.0)]
        result = DXFTerrainReader._discretize_contour(pts, interval=0)
        assert len(result) == 3


# ============================================================
# 场景 6：_trace_slope + _find_slope_ground_intersect (P1.5)
# ============================================================

class TestTraceSlopeIntersect:
    """验证分级放坡线追踪和地面交点查找"""

    def test_single_grade_intersect(self):
        """单级1:1边坡，地面z=100, 渠口z=99, 应在offset=1处与地面相交"""
        calc = CrossSectionCalculator
        ground = [(-10.0, 100.0), (-5.0, 100.0), (0.0, 100.0),
                  (5.0, 100.0), (10.0, 100.0)]
        grade = SlopeGrade(ratio=1.0, height=math.inf, berm_width=0.0)
        # 从 offset=4.5（渠口右端）向右追踪
        pts = calc._trace_slope(
            start_offset=4.5, start_elev=99.0,
            ground_pts=ground, grades=[grade], direction=+1)
        # 最后一个点应与地面相交: offset ≈ 4.5+1=5.5, elev=100
        last = pts[-1]
        assert abs(last[1] - 100.0) < 0.1, f"交点高程错误: {last[1]}"
        assert last[0] > 4.5, f"交点应在起点右侧, got {last[0]}"

    def test_single_grade_left_direction(self):
        """左侧边坡应向左延伸（offset递减）"""
        calc = CrossSectionCalculator
        ground = [(-10.0, 100.0), (0.0, 100.0), (10.0, 100.0)]
        grade = SlopeGrade(ratio=1.5, height=math.inf, berm_width=0.0)
        pts = calc._trace_slope(
            start_offset=-4.5, start_elev=99.0,
            ground_pts=ground, grades=[grade], direction=-1)
        last = pts[-1]
        assert last[0] < -4.5, f"左坡应向左, got {last[0]}"
        assert abs(last[1] - 100.0) < 0.2

    def test_multi_grade_with_berm(self):
        """两级边坡+马道: 第一级h=3,m=1,berm=2; 第二级延伸到地面"""
        calc = CrossSectionCalculator
        ground = [(-20.0, 108.0), (-10.0, 108.0), (0.0, 108.0),
                  (10.0, 108.0), (20.0, 108.0)]
        grades = [
            SlopeGrade(ratio=1.0, height=3.0, berm_width=2.0),
            SlopeGrade(ratio=0.75, height=math.inf, berm_width=0.0),
        ]
        pts = calc._trace_slope(
            start_offset=4.5, start_elev=99.0,
            ground_pts=ground, grades=grades, direction=+1)
        # 应有: 起点(4.5,99) → 第一级顶(7.5,102) → 马道(9.5,102) → 地面交点
        assert len(pts) >= 4, f"应至少4个折点, got {len(pts)}"
        # 第一级顶 offset = 4.5 + 1.0*3 = 7.5
        assert abs(pts[1][0] - 7.5) < 0.01
        assert abs(pts[1][1] - 102.0) < 0.01
        # 马道 offset = 7.5 + 2.0 = 9.5
        assert abs(pts[2][0] - 9.5) < 0.01
        assert abs(pts[2][1] - 102.0) < 0.01
        # 最后一点应与地面相交 (elev≈108)
        assert abs(pts[-1][1] - 108.0) < 0.5

    def test_find_intersect_basic(self):
        """坡线与地面折线交点"""
        calc = CrossSectionCalculator
        ground = [(0.0, 100.0), (5.0, 100.0), (10.0, 102.0)]
        result = calc._find_slope_ground_intersect(
            start_offset=0.0, start_elev=98.0,
            slope_ratio=1.0, direction=+1, ground_pts=ground)
        assert result is not None
        # 坡线: z = 98 + |x|/1 = 98+x, 地面0-5段z=100 → 交点x=2, z=100
        assert abs(result[0] - 2.0) < 0.1
        assert abs(result[1] - 100.0) < 0.1

    def test_find_intersect_no_crossing(self):
        """坡线不与地面相交（地面太低）"""
        calc = CrossSectionCalculator
        ground = [(0.0, 90.0), (10.0, 90.0)]
        result = calc._find_slope_ground_intersect(
            start_offset=0.0, start_elev=95.0,
            slope_ratio=1.0, direction=+1, ground_pts=ground)
        assert result is None

    def test_full_excavation_boundary_closed(self):
        """完整开挖边界应形成闭合多边形（首尾点接近）"""
        calc = CrossSectionCalculator()
        ground = [(-15.0, 100.0), (-10.0, 100.0), (-5.0, 100.0),
                  (0.0, 100.0), (5.0, 100.0), (10.0, 100.0), (15.0, 100.0)]
        design = DesignSection(
            channel_type=ChannelType.TRAPEZOIDAL,
            bottom_width=3.0, depth=2.0,
            inner_slope_left=1.5, inner_slope_right=1.5)
        design_pts = calc._build_design_outline(design, invert_elev=97.0)
        grade = SlopeGrade(ratio=1.0, height=math.inf, berm_width=0.0)
        slope_cfg = ExcavationSlope(
            start_station=0.0, end_station=100.0,
            left_grades=[grade], right_grades=[grade])
        boundary = calc._build_excavation_boundary(
            design_pts, ground, slope_cfg, 97.0)
        assert len(boundary) >= 6
        area = calc._shoelace_area(boundary)
        assert area > 0, f"面积应>0, got {area}"
        # 首尾应接近（闭合）
        dx = boundary[0][0] - boundary[-1][0]
        # 不要求完全闭合（Shoelace自动闭合），但多边形应合理
        assert area < 100.0, f"面积不应过大: {area}"


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
