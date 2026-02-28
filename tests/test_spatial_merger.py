# -*- coding: utf-8 -*-
"""
空间轴线合并算法 - 解析真值测试 (v5.0)

测试类：
  TestCase1_PureStraight            — 纯直线（无弯、无坡）
  TestCase2_PlanArcConstSlope       — 纯平面圆弧 + 恒定坡度
  TestCase3_PureVerticalCurve       — 纯竖曲线圆弧 + 平面直线
  TestCase4_IdealComposite          — 理想复合段（平面弧区间 ∩ 竖曲线区间）
  TestAssertions                    — 运行时几何一致性断言
  TestV5SegmentedGeometry           — v5.0 新增：分段解析几何与 BendEvent 精度验证
"""

import sys
import os
import math
import unittest

# 添加项目根目录和倒虹吸模块路径
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, '倒虹吸水力计算系统'))

from siphon_models import PlanFeaturePoint, LongitudinalNode, TurnType, BendEvent
from spatial_merger import SpatialMerger


class TestCase1_PureStraight(unittest.TestCase):
    """用例1：纯直线（无弯、无坡）—— 最简单的退化场景"""

    def test_straight_line_no_slope(self):
        """水平直线：θ_3D=0, L=Δs, β=0"""
        # 3个IP点在一条直线上（正东方向），无转弯
        plan_points = [
            PlanFeaturePoint(chainage=0.0,   x=0.0,   y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE),
            PlanFeaturePoint(chainage=100.0, x=100.0, y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE),
            PlanFeaturePoint(chainage=200.0, x=200.0, y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE),
        ]
        # 纵断面：等高程（β=0）
        long_nodes = [
            LongitudinalNode(chainage=0.0,   elevation=100.0, turn_type=TurnType.NONE, slope_after=0.0),
            LongitudinalNode(chainage=200.0, elevation=100.0, turn_type=TurnType.NONE, slope_before=0.0),
        ]

        result = SpatialMerger.merge_and_compute(plan_points, long_nodes, verbose=True)

        # 空间长度 = 水平长度
        self.assertAlmostEqual(result.total_spatial_length, 200.0, places=2)
        # 无转弯
        for nd in result.nodes:
            self.assertAlmostEqual(nd.spatial_turn_angle, 0.0, places=2)
            self.assertAlmostEqual(nd.slope_before, 0.0, places=4)
            self.assertAlmostEqual(nd.slope_after, 0.0, places=4)

    def test_straight_line_with_slope(self):
        """倾斜直线：θ_3D=0, L=Δs/cosβ, β=const"""
        slope_deg = 10.0
        slope_rad = math.radians(slope_deg)
        L_horizontal = 200.0
        dz = L_horizontal * math.tan(slope_rad)

        plan_points = [
            PlanFeaturePoint(chainage=0.0,   x=0.0,   y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE),
            PlanFeaturePoint(chainage=200.0, x=200.0, y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE),
        ]
        long_nodes = [
            LongitudinalNode(chainage=0.0,   elevation=100.0,      turn_type=TurnType.NONE, slope_after=slope_rad),
            LongitudinalNode(chainage=200.0, elevation=100.0 + dz, turn_type=TurnType.NONE, slope_before=slope_rad),
        ]

        result = SpatialMerger.merge_and_compute(plan_points, long_nodes, verbose=True)

        expected_L = math.sqrt(L_horizontal**2 + dz**2)
        self.assertAlmostEqual(result.total_spatial_length, expected_L, places=2)
        # 无转弯
        for nd in result.nodes:
            self.assertAlmostEqual(nd.spatial_turn_angle, 0.0, places=2)


class TestCase2_PlanArcConstSlope(unittest.TestCase):
    """用例2：纯平面圆弧 + 恒定坡度（螺旋线/斜坡圆弧）"""

    def test_plan_arc_with_constant_slope(self):
        """
        平面：3个IP，中间IP有R=500m、α=30°的圆弧
        纵断面：恒定坡度 k=0.05 (β=atan(0.05)≈2.86°)

        期望：
        - β 常数且等于 atan(k)
        - R_eff 在 R_v→∞ 极限应满足 R_eff = R_h/cos²β
        - L_spatial = (s_end - s_start)/cosβ（近似，因为只有一个弯道段）
        """
        R_h = 500.0
        alpha_deg = 30.0
        alpha_rad = math.radians(alpha_deg)
        k = 0.05  # 坡度
        beta_rad = math.atan(k)

        T = R_h * math.tan(alpha_rad / 2)  # 切线长
        L_arc = R_h * alpha_rad             # 弧长

        # IP 坐标构造：正东方向入射，30°左转
        # IP0 在原点，IP1 在 (500, 0)，IP2 需要偏转30°
        ip0 = (0.0, 0.0)
        ip1 = (500.0, 0.0)
        # 入射方向 d_in = (1, 0)，出射方向偏转30°（左转）
        d_out = (math.cos(math.radians(30)), math.sin(math.radians(30)))
        ip2 = (ip1[0] + 500.0 * d_out[0], ip1[1] + 500.0 * d_out[1])

        # QZ 桩号 = IP1 桩号 = 500（简化）
        # 但精确：bc_ch = 500 - L_arc/2, ec_ch = 500 + L_arc/2
        ch0 = 0.0
        ch1 = 500.0  # QZ 桩号
        ch2 = ch1 + 500.0  # 近似

        plan_points = [
            PlanFeaturePoint(chainage=ch0, x=ip0[0], y=ip0[1], azimuth_meas_deg=90.0,
                             turn_type=TurnType.NONE),
            PlanFeaturePoint(chainage=ch1, x=ip1[0], y=ip1[1], azimuth_meas_deg=90.0,
                             turn_angle=alpha_deg, turn_radius=R_h, turn_type=TurnType.ARC),
            PlanFeaturePoint(chainage=ch2, x=ip2[0], y=ip2[1], azimuth_meas_deg=60.0,
                             turn_type=TurnType.NONE),
        ]

        # 纵断面：恒坡，无竖曲线
        z0 = 100.0
        z_end = z0 + k * ch2
        long_nodes = [
            LongitudinalNode(chainage=ch0,  elevation=z0,    turn_type=TurnType.NONE, slope_after=beta_rad),
            LongitudinalNode(chainage=ch2,  elevation=z_end, turn_type=TurnType.NONE, slope_before=beta_rad),
        ]

        result = SpatialMerger.merge_and_compute(plan_points, long_nodes, verbose=True)

        # 找到弯道节点
        bend_nodes = [nd for nd in result.nodes if nd.has_plan_turn]
        self.assertTrue(len(bend_nodes) >= 1, "应至少有1个平面转弯节点")

        bend = bend_nodes[0]
        # v5.0: R_eff = L/θ，与 R_h 误差极小（小坡度时）
        if not bend.has_long_turn:
            self.assertAlmostEqual(bend.effective_radius, R_h, delta=5.0,
                                   msg=f"R_eff={bend.effective_radius:.3f} 应接近 R_h={R_h}")

        # θ_3D 应接近 α（因为β很小，cosβ≈1）
        # cos(θ_3D) = cos²β·cos(Δα) + sin²β ≈ cos(Δα) when β small
        expected_theta = math.degrees(math.acos(
            math.cos(beta_rad)**2 * math.cos(alpha_rad) + math.sin(beta_rad)**2
        ))
        self.assertAlmostEqual(bend.spatial_turn_angle, expected_theta, delta=1.0)


class TestCase3_PureVerticalCurve(unittest.TestCase):
    """用例3：纯竖曲线圆弧 + 平面直线"""

    def test_vertical_curve_only(self):
        """
        平面：直线（正东方向），无水平转弯
        纵断面：R_v=500m 的竖曲线，圆心角 θ=20°

        期望：
        - Z 插值满足 (s-Sc)²+(z-Zc)²=R_v²
        - θ_3D ≈ |β_after - β_before|
        - L 用精确弧长 R_v×θ
        """
        R_v = 500.0
        theta_deg = 20.0
        theta_rad = math.radians(theta_deg)

        # 竖曲线起终坡角
        beta_before = math.radians(-10.0)  # 下坡 10°
        beta_after = math.radians(10.0)    # 上坡 10°（谷底弧，Δβ=20°）

        # 弧起点/终点桩号
        arc_start_s = 100.0
        arc_len = R_v * theta_rad  # ~174.5m
        arc_end_s = arc_start_s + arc_len

        # 弧心坐标：谷底弧，弧心在弧段上方
        # 起点角度：tan(β_before) = -(S_start - Sc)/(Z_start - Zc)
        # 对于圆弧在 (s,Z) 平面：弧心 Sc = arc_start_s + R_v*sin(|β_before|)
        # 这里手工精确计算弧心
        Sc = arc_start_s - R_v * math.sin(beta_before)  # sin(-10°) < 0, so Sc > arc_start_s
        # 弧起点在弧心下方（谷底弧）
        Z_start = 50.0
        Zc = Z_start + R_v * math.cos(beta_before)  # cos(-10°)=cos(10°)

        # 弧终点
        Z_end = Zc - R_v * math.cos(beta_after)  # 终点也在弧心下方

        # 全线桩号
        s0 = 0.0
        s_end = 300.0

        plan_points = [
            PlanFeaturePoint(chainage=s0,    x=s0,    y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE),
            PlanFeaturePoint(chainage=s_end, x=s_end, y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE),
        ]

        # 纵断面节点
        Z0 = Z_start + (arc_start_s - s0) * math.tan(beta_before)
        Z_final = Z_end + (s_end - arc_end_s) * math.tan(beta_after)

        long_nodes = [
            LongitudinalNode(chainage=s0, elevation=Z0, turn_type=TurnType.NONE,
                             slope_after=beta_before),
            LongitudinalNode(chainage=arc_start_s, elevation=Z_start, turn_type=TurnType.ARC,
                             vertical_curve_radius=R_v, turn_angle=theta_deg,
                             slope_before=beta_before, slope_after=beta_after,
                             arc_center_s=Sc, arc_center_z=Zc,
                             arc_end_chainage=arc_end_s, arc_theta_rad=theta_rad),
            LongitudinalNode(chainage=arc_end_s, elevation=Z_end, turn_type=TurnType.NONE,
                             slope_before=beta_after, slope_after=beta_after),
            LongitudinalNode(chainage=s_end, elevation=Z_final, turn_type=TurnType.NONE,
                             slope_before=beta_after),
        ]

        result = SpatialMerger.merge_and_compute(plan_points, long_nodes, verbose=True)

        # 验证弧起点圆方程一致性
        for nd in result.nodes:
            if abs(nd.chainage - arc_start_s) < 0.05:
                r2 = (nd.chainage - Sc)**2 + (nd.z - Zc)**2
                self.assertAlmostEqual(math.sqrt(r2), R_v, delta=0.2)
            if abs(nd.chainage - arc_end_s) < 0.05:
                r2 = (nd.chainage - Sc)**2 + (nd.z - Zc)**2
                self.assertAlmostEqual(math.sqrt(r2), R_v, delta=0.2)

        # 找到弯道节点，验证 θ_3D ≈ |Δβ|
        bend_nodes = [nd for nd in result.nodes if nd.has_long_turn]
        self.assertTrue(len(bend_nodes) >= 1)
        bend = bend_nodes[0]
        expected_theta_3d = theta_deg  # 纯竖向弯道
        self.assertAlmostEqual(bend.spatial_turn_angle, expected_theta_3d, delta=2.0)

        # 验证精确弧长被使用（R_v×θ vs √(Δs²+ΔZ²) 割线近似）
        exact_arc_len = R_v * theta_rad
        ds_arc = arc_end_s - arc_start_s
        dz_arc = Z_end - Z_start
        chord_approx = math.sqrt(ds_arc**2 + dz_arc**2)
        # 精确弧长 ≥ 割线近似（弧长≥弦长），对大圆心角差异明显
        self.assertGreaterEqual(exact_arc_len + 1e-9, chord_approx)
        # 空间总长度应包含精确弧长而非割线近似
        L_before = math.sqrt((arc_start_s - s0)**2 + (Z_start - Z0)**2)
        L_after = math.sqrt((s_end - arc_end_s)**2 + (Z_final - Z_end)**2)
        expected_total = L_before + exact_arc_len + L_after
        self.assertAlmostEqual(result.total_spatial_length, expected_total, delta=1.0)


class TestCase4_IdealComposite(unittest.TestCase):
    """用例4：理想复合段 — 平面圆弧+竖曲线完全重叠"""

    def test_composite_detection_interval_overlap(self):
        """
        平面弧 [bc=400, ec=600]，QZ=500, R_h=500, α=20°
        纵断面弧 [arc_start=420, arc_end=580]，R_v=800, θ=15°

        区间重叠 = [420, 580] = 160m >> 1m 阈值
        旧版点窗口（2m）：|500-420|=80m → 遗漏 ← 风险点B的核心场景

        期望：能正确检测为复合弯道
        """
        R_h = 500.0
        alpha_deg = 20.0
        alpha_rad = math.radians(alpha_deg)
        L_arc_plan = R_h * alpha_rad  # ≈174.5m
        qz_ch = 500.0
        bc_ch = qz_ch - L_arc_plan / 2  # ≈412.7
        ec_ch = qz_ch + L_arc_plan / 2  # ≈587.3

        T = R_h * math.tan(alpha_rad / 2)

        # IP 坐标构造
        ip0 = (0.0, 0.0)
        ip1 = (500.0, 0.0)
        d_out = (math.cos(math.radians(20)), math.sin(math.radians(20)))
        ip2 = (ip1[0] + 500.0 * d_out[0], ip1[1] + 500.0 * d_out[1])

        plan_points = [
            PlanFeaturePoint(chainage=0.0,    x=ip0[0], y=ip0[1], azimuth_meas_deg=90.0,
                             turn_type=TurnType.NONE),
            PlanFeaturePoint(chainage=qz_ch,  x=ip1[0], y=ip1[1], azimuth_meas_deg=90.0,
                             turn_angle=alpha_deg, turn_radius=R_h, turn_type=TurnType.ARC),
            PlanFeaturePoint(chainage=1000.0, x=ip2[0], y=ip2[1], azimuth_meas_deg=70.0,
                             turn_type=TurnType.NONE),
        ]

        # 纵断面弧：起点在 420，终点在 580
        R_v = 800.0
        theta_v_deg = 15.0
        theta_v_rad = math.radians(theta_v_deg)
        beta_before = math.radians(-5.0)
        beta_after = math.radians(10.0)
        arc_start_s = 420.0
        arc_end_s = 580.0

        Sc = arc_start_s - R_v * math.sin(beta_before)
        Z_start = 50.0
        Zc = Z_start + R_v * math.cos(beta_before)
        Z_end = Zc - R_v * math.cos(beta_after)

        Z0 = Z_start + (arc_start_s - 0.0) * math.tan(beta_before)
        Z_final = Z_end + (1000.0 - arc_end_s) * math.tan(beta_after)

        long_nodes = [
            LongitudinalNode(chainage=0.0,         elevation=Z0,      turn_type=TurnType.NONE,
                             slope_after=beta_before),
            LongitudinalNode(chainage=arc_start_s,  elevation=Z_start, turn_type=TurnType.ARC,
                             vertical_curve_radius=R_v, turn_angle=theta_v_deg,
                             slope_before=beta_before, slope_after=beta_after,
                             arc_center_s=Sc, arc_center_z=Zc,
                             arc_end_chainage=arc_end_s, arc_theta_rad=theta_v_rad),
            LongitudinalNode(chainage=arc_end_s,    elevation=Z_end,   turn_type=TurnType.NONE,
                             slope_before=beta_after, slope_after=beta_after),
            LongitudinalNode(chainage=1000.0,       elevation=Z_final, turn_type=TurnType.NONE,
                             slope_before=beta_after),
        ]

        result = SpatialMerger.merge_and_compute(plan_points, long_nodes, verbose=True)

        # v5.0: 复合弯道检测通过 bend_events（区间级），不再依赖 QZ 节点
        # 核心验证：应存在 COMPOSITE 类型的弯道事件
        composite_evts = [ev for ev in result.bend_events if ev.event_type == 'COMPOSITE']
        self.assertTrue(len(composite_evts) >= 1,
                        f"应检测到复合弯道事件，实际 bend_events={[(ev.event_type, ev.s_a, ev.s_b) for ev in result.bend_events]}")

        # 复合事件应覆盖平面弧与竖曲线的重叠区间 [420, 580]
        comp = composite_evts[0]
        self.assertLessEqual(comp.s_a, 420.0 + 1.0, "复合事件起点应 ≤ 420")
        self.assertGreaterEqual(comp.s_b, 580.0 - 1.0, "复合事件终点应 ≥ 580")

        # 复合事件的 R_eff 应有效（> 0）
        self.assertGreater(comp.R_eff, 0)

        # 验证 turn_style 为 ARC（双 ARC）
        self.assertEqual(comp.turn_style, TurnType.ARC)

        # 验证回填：弯道内的节点应被标记为 has_plan_turn 和 has_long_turn
        nodes_in_composite = [nd for nd in result.nodes
                               if comp.s_a - 1.0 <= nd.chainage <= comp.s_b + 1.0]
        self.assertTrue(len(nodes_in_composite) >= 1, "复合事件区间内应有节点")
        flagged = [nd for nd in nodes_in_composite if nd.has_plan_turn and nd.has_long_turn]
        self.assertTrue(len(flagged) >= 1,
                        "复合事件区间内应至少有1个节点同时标记 has_plan_turn 和 has_long_turn")

    def test_fold_plus_arc_conservative_type(self):
        """
        风险点C验证：平面FOLD + 纵断面ARC → effective_turn_type 应为 FOLD（保守规则）
        """
        plan_points = [
            PlanFeaturePoint(chainage=0.0,   x=0.0,   y=0.0,   azimuth_meas_deg=90.0, turn_type=TurnType.NONE),
            PlanFeaturePoint(chainage=100.0, x=100.0, y=0.0,   azimuth_meas_deg=90.0,
                             turn_angle=15.0, turn_radius=0.0, turn_type=TurnType.FOLD),
            PlanFeaturePoint(chainage=200.0, x=185.0, y=51.76, azimuth_meas_deg=75.0, turn_type=TurnType.NONE),
        ]

        beta_rad = math.radians(-3.0)
        long_nodes = [
            LongitudinalNode(chainage=0.0,   elevation=100.0, turn_type=TurnType.NONE, slope_after=beta_rad),
            LongitudinalNode(chainage=90.0,  elevation=100.0 + 90*math.tan(beta_rad),
                             turn_type=TurnType.ARC, vertical_curve_radius=300.0,
                             turn_angle=6.0, slope_before=beta_rad, slope_after=math.radians(3.0),
                             arc_center_s=95.0, arc_center_z=100.0+90*math.tan(beta_rad)+300.0,
                             arc_end_chainage=110.0, arc_theta_rad=math.radians(6.0)),
            LongitudinalNode(chainage=110.0, elevation=100.0+90*math.tan(beta_rad)+0.5,
                             turn_type=TurnType.NONE, slope_before=math.radians(3.0),
                             slope_after=math.radians(3.0)),
            LongitudinalNode(chainage=200.0, elevation=100.0+90*math.tan(beta_rad)+0.5+90*math.tan(math.radians(3.0)),
                             turn_type=TurnType.NONE, slope_before=math.radians(3.0)),
        ]

        result = SpatialMerger.merge_and_compute(plan_points, long_nodes, verbose=True)

        # 找到桩号100附近的折管节点
        fold_node = None
        for nd in result.nodes:
            if nd.has_plan_turn and nd.plan_turn_type == TurnType.FOLD:
                fold_node = nd
                break

        if fold_node is not None and fold_node.has_long_turn:
            # 如果被检测为复合事件，effective_turn_type 应为 FOLD（保守规则）
            self.assertEqual(fold_node.effective_turn_type, TurnType.FOLD,
                             "平面FOLD+纵断面ARC → 应按FOLD处理（保守规则）")


class TestAssertions(unittest.TestCase):
    """验证运行时断言不会对正常数据产生误报"""

    def test_no_assertion_warnings_on_clean_data(self):
        """干净数据应该通过所有断言"""
        plan_points = [
            PlanFeaturePoint(chainage=0.0,   x=0.0,   y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE),
            PlanFeaturePoint(chainage=100.0, x=100.0, y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE),
        ]
        long_nodes = [
            LongitudinalNode(chainage=0.0,   elevation=100.0, turn_type=TurnType.NONE, slope_after=0.0),
            LongitudinalNode(chainage=100.0, elevation=100.0, turn_type=TurnType.NONE, slope_before=0.0),
        ]

        result = SpatialMerger.merge_and_compute(plan_points, long_nodes, verbose=True)

        # 检查 steps 中不应有 "⚠" 警告
        warning_lines = [s for s in result.computation_steps if '⚠' in s]
        self.assertEqual(len(warning_lines), 0,
                         f"干净数据不应有断言警告，但发现: {warning_lines}")

        # 应有 "全部通过" 信息
        passed_lines = [s for s in result.computation_steps if '全部通过' in s]
        self.assertTrue(len(passed_lines) > 0, "应输出'全部通过'")


class TestV5SegmentedGeometry(unittest.TestCase):
    """v5.0 新增测试：分段解析几何精度、BendEvent 区间定义、R_eff=L/θ 自洽性"""

    def _make_plan_arc(self, R_h=500., alpha_deg=30., qz_s=500.):
        """辅助：构造含单个平面圆弧的最小输入（无纵断面竖曲线）"""
        ar = math.radians(alpha_deg)
        Lh = R_h * ar
        dout = (math.cos(ar), math.sin(ar))
        ip2 = (500. + 600.*dout[0], 600.*dout[1])
        return [
            PlanFeaturePoint(chainage=0., x=0., y=0., azimuth_meas_deg=90., turn_type=TurnType.NONE),
            PlanFeaturePoint(chainage=qz_s, x=500., y=0., azimuth_meas_deg=90.,
                             turn_angle=alpha_deg, turn_radius=R_h, turn_type=TurnType.ARC),
            PlanFeaturePoint(chainage=1100., x=ip2[0], y=ip2[1],
                             azimuth_meas_deg=90., turn_type=TurnType.NONE),
        ]

    def _make_flat_long(self, s0=0., s1=1100., z=100.):
        """辅助：构造平坡纵断面"""
        return [
            LongitudinalNode(chainage=s0, elevation=z, turn_type=TurnType.NONE),
            LongitudinalNode(chainage=s1, elevation=z, turn_type=TurnType.NONE),
        ]

    def test_plan_segments_coverage(self):
        """§4: 分段序列全覆盖无重叠"""
        pps  = self._make_plan_arc()
        lns  = self._make_flat_long()
        r    = SpatialMerger.merge_and_compute(pps, lns, verbose=False)
        segs = r.plan_segments
        self.assertTrue(len(segs) >= 3, "至少应有 LINE-ARC-LINE 三段")
        # 全线覆盖
        self.assertAlmostEqual(segs[0].s_start, 0., places=3)
        self.assertAlmostEqual(segs[-1].s_end, 1100., places=3)
        # 相邻段首尾衔接
        for i in range(len(segs)-1):
            self.assertAlmostEqual(segs[i].s_end, segs[i+1].s_start, places=3,
                                   msg=f"段{i}终点 != 段{i+1}起点")
        # 至少一段为 ARC
        arc_segs = [sg for sg in segs if sg.seg_type == 'ARC']
        self.assertEqual(len(arc_segs), 1, "应恰好有1个平面圆弧段")

    def test_profile_segments_coverage(self):
        """§5: 纵断面分段序列全覆盖"""
        R_v  = 500.
        th   = math.radians(30.)
        bb   = math.radians(-15.)
        ba   = math.radians(15.)
        arc_s = 100.
        Sc    = arc_s - R_v * math.sin(bb)
        Z_s   = 50.
        Zc    = Z_s + R_v * math.cos(bb)
        arc_e = arc_s + R_v * 2 * math.sin(th/2)
        Z_e   = Zc - R_v * math.cos(ba)
        lns = [
            LongitudinalNode(chainage=0., elevation=Z_s + (arc_s-0.)*math.tan(bb),
                             turn_type=TurnType.NONE, slope_after=bb),
            LongitudinalNode(chainage=arc_s, elevation=Z_s, turn_type=TurnType.ARC,
                             vertical_curve_radius=R_v, turn_angle=math.degrees(th),
                             slope_before=bb, slope_after=ba,
                             arc_center_s=Sc, arc_center_z=Zc,
                             arc_end_chainage=arc_e, arc_theta_rad=th),
            LongitudinalNode(chainage=arc_e, elevation=Z_e, turn_type=TurnType.NONE,
                             slope_before=ba, slope_after=ba),
            LongitudinalNode(chainage=arc_e+100., elevation=Z_e+(arc_e+100.-arc_e)*math.tan(ba),
                             turn_type=TurnType.NONE, slope_before=ba),
        ]
        pps = [
            PlanFeaturePoint(chainage=0., x=0., y=0., azimuth_meas_deg=90., turn_type=TurnType.NONE),
            PlanFeaturePoint(chainage=arc_e+100., x=arc_e+100., y=0.,
                             azimuth_meas_deg=90., turn_type=TurnType.NONE),
        ]
        r    = SpatialMerger.merge_and_compute(pps, lns, verbose=False)
        segs = r.profile_segments
        self.assertTrue(len(segs) >= 3, "应至少有 LINE-ARC-LINE 三段")
        self.assertAlmostEqual(segs[0].s_start, 0., places=2)
        self.assertAlmostEqual(segs[-1].s_end, arc_e+100., places=2)
        arc_segs = [sg for sg in segs if sg.seg_type == 'ARC']
        self.assertEqual(len(arc_segs), 1, "应恰好有1个纵断圆弧段")
        # 圆弧段圆方程验证：z(arc_s)^2 满足圆方程
        from spatial_merger import SpatialMerger as SM
        arc = arc_segs[0]
        z_check, _ = SM._eval_profile([arc], arc_s)
        err = abs(math.sqrt((arc_s - arc.Sc)**2 + (z_check - arc.Zc)**2) - arc.R_v)
        self.assertLess(err, 1e-6, f"圆弧段起点圆方程误差 {err:.2e}")

    def test_arc_tangent_continuous(self):
        """§4.3: 平面圆弧段切线连续性（BC/EC处 α 不跳变）"""
        pps = self._make_plan_arc(R_h=500., alpha_deg=30.)
        lns = self._make_flat_long()
        r   = SpatialMerger.merge_and_compute(pps, lns, verbose=False)
        # 找 ARC 段
        arc_seg = next(sg for sg in r.plan_segments if sg.seg_type == 'ARC')
        # 在 BC 处：LINE 的右极限 alpha == ARC 的右极限 alpha
        _, _, al_bc = SpatialMerger._eval_plan(r.plan_segments, arc_seg.s_start, 'L')
        _, _, ar_bc = SpatialMerger._eval_plan(r.plan_segments, arc_seg.s_start, 'R')
        self.assertAlmostEqual(al_bc, ar_bc, places=4,
                               msg=f"BC处切线不连续: α_L={math.degrees(al_bc):.4f}° vs α_R={math.degrees(ar_bc):.4f}°")
        # 在 EC 处同理
        _, _, al_ec = SpatialMerger._eval_plan(r.plan_segments, arc_seg.s_end, 'L')
        _, _, ar_ec = SpatialMerger._eval_plan(r.plan_segments, arc_seg.s_end, 'R')
        self.assertAlmostEqual(al_ec, ar_ec, places=4,
                               msg=f"EC处切线不连续")

    def test_spatial_length_arc_formula(self):
        """§9.2: 纵断圆弧段 L = R_v·|β(b)-β(a)|"""
        R_v  = 500.
        th   = math.radians(30.)   # β: -15° → +15°
        bb, ba = math.radians(-15.), math.radians(15.)
        arc_s = 100.
        Sc = arc_s - R_v * math.sin(bb)
        Z_s = 50.
        Zc = Z_s + R_v * math.cos(bb)
        arc_e = arc_s + R_v * 2 * math.sin(th/2)
        Z_e = Zc - R_v * math.cos(ba)
        lns = [
            LongitudinalNode(chainage=0., elevation=Z_s, turn_type=TurnType.NONE),
            LongitudinalNode(chainage=arc_s, elevation=Z_s, turn_type=TurnType.ARC,
                             vertical_curve_radius=R_v, turn_angle=math.degrees(th),
                             slope_before=bb, slope_after=ba,
                             arc_center_s=Sc, arc_center_z=Zc,
                             arc_end_chainage=arc_e, arc_theta_rad=th),
            LongitudinalNode(chainage=arc_e, elevation=Z_e,
                             turn_type=TurnType.NONE, slope_before=ba, slope_after=ba),
            LongitudinalNode(chainage=arc_e+100., elevation=Z_e+(100.)*math.tan(ba),
                             turn_type=TurnType.NONE, slope_before=ba),
        ]
        pps = [
            PlanFeaturePoint(chainage=0., x=0., y=0., azimuth_meas_deg=90., turn_type=TurnType.NONE),
            PlanFeaturePoint(chainage=arc_e+100., x=arc_e+100., y=0.,
                             azimuth_meas_deg=90., turn_type=TurnType.NONE),
        ]
        r = SpatialMerger.merge_and_compute(pps, lns, verbose=False)
        arc_prof = next(sg for sg in r.profile_segments if sg.seg_type == 'ARC')
        L_exact = arc_prof.R_v * abs(ba - bb)   # = 500 * rad(30°) ≈ 261.80m
        L_computed = SpatialMerger._compute_spatial_length(r.profile_segments, arc_s, arc_e)
        self.assertAlmostEqual(L_computed, L_exact, places=4,
                               msg=f"弧段长度 {L_computed:.6f} != R_v·|Δβ| {L_exact:.6f}")

    def test_bend_event_R_eff_consistency(self):
        """§11: R_eff = L_event / θ_event（几何自洽）"""
        pps = self._make_plan_arc(R_h=500., alpha_deg=20.)
        lns = self._make_flat_long()
        r   = SpatialMerger.merge_and_compute(pps, lns, verbose=False)
        self.assertTrue(len(r.bend_events) >= 1, "应有弯道事件")
        for ev in r.bend_events:
            if ev.theta_event < 1e-6:
                continue
            expected_R = ev.L_event / ev.theta_event
            self.assertAlmostEqual(ev.R_eff, expected_R, places=6,
                                   msg=f"R_eff={ev.R_eff:.6f} != L/θ={expected_R:.6f}")

    def test_bend_events_in_result(self):
        """§10-§11: SpatialMergeResult 包含正确的 bend_events"""
        pps = self._make_plan_arc(R_h=500., alpha_deg=30.)
        lns = self._make_flat_long()
        r   = SpatialMerger.merge_and_compute(pps, lns, verbose=False)
        # 应有 plan_segments 和 bend_events
        self.assertIsNotNone(r.plan_segments)
        self.assertIsNotNone(r.bend_events)
        plan_evts = [ev for ev in r.bend_events if ev.event_type == 'PLAN']
        self.assertTrue(len(plan_evts) >= 1, "平面弧应产生至少1个 PLAN 事件")
        for ev in plan_evts:
            self.assertGreater(ev.theta_event, 0., "事件转角应 > 0")
            self.assertGreater(ev.L_event, 0., "事件长度应 > 0")
            self.assertGreater(ev.R_eff, 0., "R_eff 应 > 0")
            self.assertIsInstance(ev, BendEvent)

    def test_T_vector_unit_length(self):
        """§6.2: 所有节点的 T_before / T_after 应为单位向量"""
        pps = self._make_plan_arc(R_h=500., alpha_deg=25.)
        lns = self._make_flat_long()
        r   = SpatialMerger.merge_and_compute(pps, lns, verbose=False)
        for nd in r.nodes:
            for T, label in [(nd.T_before, 'T_before'), (nd.T_after, 'T_after')]:
                mag = math.sqrt(T[0]**2 + T[1]**2 + T[2]**2)
                self.assertAlmostEqual(mag, 1.0, places=10,
                                       msg=f"桩号{nd.chainage:.2f} {label} |T|={mag:.12f}")

    def test_station_set_includes_plan_qz(self):
        """§7: S_biz 含平面特征点桩号（QZ应进入节点集）"""
        qz = 500.0
        pps = self._make_plan_arc(R_h=500., alpha_deg=30., qz_s=qz)
        lns = self._make_flat_long()
        r = SpatialMerger.merge_and_compute(pps, lns, verbose=False)
        has_qz = any(abs(nd.chainage - qz) <= SpatialMerger.STATION_EPS for nd in r.nodes)
        self.assertTrue(has_qz, f"节点集应包含QZ桩号 {qz}")

    def test_fold_fold_same_station_becomes_composite(self):
        """§10: 同桩号 PLAN-FOLD 与 VERTICAL-FOLD 应聚合为 COMPOSITE FOLD 事件"""
        pps = [
            PlanFeaturePoint(chainage=0.0, x=0.0, y=0.0, azimuth_meas_deg=90.0, turn_type=TurnType.NONE),
            PlanFeaturePoint(chainage=100.0, x=100.0, y=0.0, azimuth_meas_deg=90.0,
                             turn_angle=20.0, turn_type=TurnType.FOLD),
            PlanFeaturePoint(chainage=200.0, x=193.97, y=34.20, azimuth_meas_deg=70.0, turn_type=TurnType.NONE),
        ]
        lns = [
            LongitudinalNode(chainage=0.0, elevation=100.0, turn_type=TurnType.NONE, slope_after=0.0),
            LongitudinalNode(chainage=100.0, elevation=100.0, turn_type=TurnType.FOLD,
                             turn_angle=8.0, slope_before=math.radians(-4.0), slope_after=math.radians(4.0)),
            LongitudinalNode(chainage=200.0, elevation=100.0, turn_type=TurnType.NONE, slope_before=0.0),
        ]
        r = SpatialMerger.merge_and_compute(pps, lns, verbose=False)
        fold_events = [ev for ev in r.bend_events
                       if ev.turn_style == TurnType.FOLD and abs(ev.s_a - 100.0) <= SpatialMerger.STATION_EPS]
        self.assertEqual(len(fold_events), 1, f"同桩号FOLD应聚合为1个事件，实际={len(fold_events)}")
        self.assertEqual(fold_events[0].event_type, 'COMPOSITE')

    def test_R3d_mid_plan_arc_Rv_inf_limit(self):
        """§12: 仅平面ARC时，R_3d_mid 满足 R_h/cos²β（R_v→∞极限）"""
        R_h = 400.0
        beta = math.radians(20.0)
        pps = self._make_plan_arc(R_h=R_h, alpha_deg=25.0, qz_s=500.0)
        s1 = 1100.0
        z0 = 100.0
        z1 = z0 + s1 * math.tan(beta)
        lns = [
            LongitudinalNode(chainage=0.0, elevation=z0, turn_type=TurnType.NONE, slope_after=beta),
            LongitudinalNode(chainage=s1, elevation=z1, turn_type=TurnType.NONE, slope_before=beta),
        ]
        r = SpatialMerger.merge_and_compute(pps, lns, verbose=False)
        plan_arc_events = [ev for ev in r.bend_events if ev.event_type == 'PLAN' and ev.turn_style == TurnType.ARC]
        self.assertTrue(plan_arc_events, "应存在PLAN-ARC事件")
        ev = plan_arc_events[0]
        expected = R_h / (math.cos(beta) ** 2)
        self.assertAlmostEqual(ev.R_3d_mid, expected, delta=1e-6)


if __name__ == '__main__':
    unittest.main()
