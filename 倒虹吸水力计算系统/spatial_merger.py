# -*- coding: utf-8 -*-
"""
倒虹吸水力计算软件 - 三维空间合并引擎 (v2.0 严格几何修订版)

核心算法：将平面图(X,Y)和纵断面(S,Z)数据按桩号合并为三维空间曲线 R(s)=[x(s),y(s),z(s)]，
计算空间长度 L_spatial 和空间转角 θ_3D，用于精确的水头损失计算。

数学基础：
  单位切向量 T(s) = (cosβ·cosα, cosβ·sinα, sinβ)
    α = 数学方位角（正东=0°，逆时针），β = 纵断面坡角
  
  空间转角 θ_3D = arccos(T_before · T_after)
  
  空间长度 L = Σ√(Δs² + ΔZ²)
    其中 Δs = 桩号差（平面轴线弧长参数增量），非 XY 弦长

v2.0 关键变更：
  1. 移除桩号吸附(Snap)，改为纯桩号并集 + 复合弯道事件检测
  2. 坡角 β 用桩号差 Δs 计算（非 XY 弦长 dH），消除圆弧段系统性偏差
  3. 空间长度用 √(Δs²+ΔZ²)（非 √(ΔX²+ΔY²+ΔZ²)），消除弦代弧误差
  4. 角度体系硬隔离：azimuth_meas_deg（测量角）/ azimuth_math_rad（数学角）
  5. R_3D β_avg 直接平均（不取绝对值），添加极限校核
"""

import math
from typing import List, Optional, Tuple
from siphon_models import (
    PlanFeaturePoint, LongitudinalNode, SpatialNode,
    SpatialMergeResult, TurnType
)


class SpatialMerger:
    """三维空间合并引擎"""
    
    # 邻近弯道吸附容差 (m)
    # 当纵断面弯道与平面弯道桩号差距小于此值时，视为同一位置的重叠弯道
    SNAP_TOLERANCE = 2.0
    
    @staticmethod
    def merge_and_compute(plan_points: List[PlanFeaturePoint],
                          long_nodes: List[LongitudinalNode],
                          pipe_diameter: float = 0.0,
                          verbose: bool = True) -> SpatialMergeResult:
        """
        合并平面和纵断面数据，计算三维空间属性
        
        支持三种退化场景：
        1. 仅平面数据：β=0, θ_3D=α, L=L_plan
        2. 仅纵断面数据：α=常数, θ_3D=竖向角, L=√(L²+ΔH²)
        3. 两者都有：完整三维空间计算
        
        Args:
            plan_points: 平面IP特征点列表
            long_nodes: 纵断面变坡点节点列表
            pipe_diameter: 管径 D (m)，用于弯道损失系数查表
            verbose: 是否输出详细计算步骤
        
        Returns:
            SpatialMergeResult
        """
        result = SpatialMergeResult()
        steps = []
        
        has_plan = bool(plan_points) and len(plan_points) >= 2
        has_long = bool(long_nodes) and len(long_nodes) >= 2
        result.has_plan_data = has_plan
        result.has_longitudinal_data = has_long
        
        if not has_plan and not has_long:
            steps.append("警告：无平面数据和纵断面数据，无法进行空间合并计算")
            result.computation_steps = steps
            return result
        
        steps.append("=" * 50)
        steps.append("三维空间合并计算")
        steps.append("=" * 50)
        
        if has_plan and has_long:
            steps.append("模式：完整三维空间计算（平面+纵断面）")
            spatial_nodes = SpatialMerger._merge_full_3d(plan_points, long_nodes, steps)
        elif has_plan:
            steps.append("模式：仅平面数据（假设 β=0，无竖向坡度）")
            spatial_nodes = SpatialMerger._merge_plan_only(plan_points, steps)
        else:
            steps.append("模式：仅纵断面数据（假设 α=常数，无水平偏转）")
            spatial_nodes = SpatialMerger._merge_long_only(long_nodes, steps)
        
        result.nodes = spatial_nodes
        
        # 计算空间长度（v2.0: 用 √(Δs²+ΔZ²) 替代 √(ΔX²+ΔY²+ΔZ²)）
        # Δs = 桩号差（平面弧长参数增量），精确表示水平路径长度
        # 数学依据：dℓ = √(1 + (dZ/ds)²) ds → Δℓ ≈ √(Δs² + ΔZ²)
        steps.append("")
        steps.append("【空间长度计算】")
        total_L = 0.0
        seg_lengths = []
        for i in range(len(spatial_nodes) - 1):
            n1 = spatial_nodes[i]
            n2 = spatial_nodes[i + 1]
            ds = n2.chainage - n1.chainage  # 桩号差（平面弧长参数增量）
            dz = n2.z - n1.z
            L_seg = math.sqrt(ds**2 + dz**2)
            seg_lengths.append(L_seg)
            total_L += L_seg
            if verbose:
                steps.append(f"  段{i}: 桩号 {n1.chainage:.2f}→{n2.chainage:.2f}, "
                           f"Δs={ds:.3f}, ΔZ={dz:.3f}, "
                           f"L_空间={L_seg:.3f}m")
        
        result.total_spatial_length = total_L
        result.segment_lengths = seg_lengths
        steps.append(f"空间总长度 L_spatial = {total_L:.4f} m")
        
        # 计算空间转角和弯道损失系数
        steps.append("")
        steps.append("【空间转角计算】")
        SpatialMerger._compute_spatial_angles(spatial_nodes, steps, verbose)
        
        # 汇总弯道损失
        xi_total = 0.0
        bend_count = 0
        for nd in spatial_nodes:
            if nd.has_turn and nd.spatial_turn_angle > 0.1:
                bend_count += 1
                steps.append(f"  空间转弯: 桩号={nd.chainage:.2f}m, "
                           f"θ_3D={nd.spatial_turn_angle:.2f}°, "
                           f"R={nd.effective_radius:.2f}m, "
                           f"类型={nd.effective_turn_type.value}")
        
        # xi_spatial_bends 此处保持 0.0 —— siphon_hydraulics 会直接遍历 spatial_result.nodes
        # 按实际管径 D 查表计算每个转弯的 ξ，不依赖本字段，此字段仅作预留。
        result.xi_spatial_bends = xi_total
        steps.append(f"共 {bend_count} 个空间转弯")
        
        result.computation_steps = steps
        return result
    
    # ==================================================================
    # 三种合并模式
    # ==================================================================
    
    @staticmethod
    def _merge_full_3d(plan_points: List[PlanFeaturePoint],
                       long_nodes: List[LongitudinalNode],
                       steps: List[str]) -> List[SpatialNode]:
        """完整三维合并：按桩号合并平面和纵断面特征点"""
        steps.append("")
        steps.append("【步骤1：桩号并集（不修改任何原始桩号）】")
        
        # 收集所有特征点桩号，同时预计算圆弧精确几何
        plan_dict = {}
        for pp in plan_points:
            plan_dict[round(pp.chainage, 3)] = pp

        plan_geom = SpatialMerger._build_plan_geometry(plan_points)
        plan_geom_dict = {round(plan_points[i].chainage, 3): plan_geom[i]
                          for i in range(len(plan_points))}

        # v2.0: 不做桩号吸附/平移，直接按原始桩号构建 long_dict
        long_dict = {}
        for ln in long_nodes:
            long_dict[round(ln.chainage, 3)] = ln
        
        all_stations = sorted(set(
            list(plan_dict.keys()) + list(long_dict.keys())
        ))
        
        steps.append(f"  平面IP点: {len(plan_points)} 个")
        steps.append(f"  纵断面变坡点: {len(long_nodes)} 个")
        steps.append(f"  合并后特征点: {len(all_stations)} 个")
        
        # 构建空间节点
        spatial_nodes = []
        for s in all_stations:
            pp = plan_dict.get(s)
            ln = long_dict.get(s)
            
            # 插值 X, Y（平面）
            if pp:
                g = plan_geom_dict.get(s, {})
                if pp.turn_type == TurnType.ARC and g.get('qz') is not None:
                    x, y = g['qz']   # 精确弧中点坐标（QZ点），避免 IP 坐标的外距偏差
                else:
                    x, y = pp.x, pp.y
                azimuth = pp.azimuth
            else:
                x, y, azimuth = SpatialMerger._interpolate_plan(plan_points, s, plan_geom)
            
            # 插值 Z（纵断面）
            if ln:
                z = ln.elevation
                slope = ln.slope_before if ln.slope_before != 0 else ln.slope_after
            else:
                z, slope = SpatialMerger._interpolate_long(long_nodes, s)
            
            node = SpatialNode(
                chainage=s,
                x=x, y=y, z=z,
                azimuth_before=azimuth,
                azimuth_after=azimuth,
                slope_before=slope,
                slope_after=slope,
            )
            
            # 标记转弯信息
            if pp and pp.turn_angle > 0.1 and pp.turn_type != TurnType.NONE:
                node.has_plan_turn = True
                node.plan_turn_radius = pp.turn_radius
                node.plan_turn_angle = pp.turn_angle
                node.plan_turn_type = pp.turn_type
            
            if ln and ln.turn_angle > 0.1 and ln.turn_type != TurnType.NONE:
                node.has_long_turn = True
                node.long_turn_radius = ln.vertical_curve_radius
                node.long_turn_angle = ln.turn_angle
                node.long_turn_type = ln.turn_type
                node.slope_before = ln.slope_before
                node.slope_after = ln.slope_after
            
            spatial_nodes.append(node)
        
        # 填充相邻节点的方位角/坡角
        SpatialMerger._fill_adjacent_angles(spatial_nodes, plan_points, long_nodes, plan_geom_dict)
        
        # v2.0 步骤1b：复合弯道事件检测（不改桩号，仅标记近邻事件用于 R_3D 合成和局损查表）
        SpatialMerger._detect_composite_events(spatial_nodes, plan_points, long_nodes, steps)
        
        return spatial_nodes
    
    @staticmethod
    def _merge_plan_only(plan_points: List[PlanFeaturePoint],
                         steps: List[str]) -> List[SpatialNode]:
        """仅平面数据：假设 β=0（无纵坡），Z=0"""
        steps.append("")
        plan_geom = SpatialMerger._build_plan_geometry(plan_points)
        plan_geom_dict = {round(plan_points[i].chainage, 3): plan_geom[i]
                          for i in range(len(plan_points))}
        spatial_nodes = []
        for i, pp in enumerate(plan_points):
            g = plan_geom[i]
            if pp.turn_type == TurnType.ARC and g.get('qz') is not None:
                xp, yp = g['qz']   # 精确弧中点坐标（QZ点）
            else:
                xp, yp = pp.x, pp.y
            node = SpatialNode(
                chainage=pp.chainage,
                x=xp, y=yp, z=0.0,
                azimuth_before=pp.azimuth,
                azimuth_after=pp.azimuth,
                slope_before=0.0,
                slope_after=0.0,
            )
            if pp.turn_angle > 0.1 and pp.turn_type != TurnType.NONE:
                node.has_plan_turn = True
                node.plan_turn_radius = pp.turn_radius
                node.plan_turn_angle = pp.turn_angle
                node.plan_turn_type = pp.turn_type
            spatial_nodes.append(node)

        # 填充方位角（坐标差推算），再用精确切线方向覆盖圆弧转弯节点
        SpatialMerger._fill_azimuths_from_plan(spatial_nodes, plan_points)
        for nd in spatial_nodes:
            if nd.has_plan_turn and nd.plan_turn_type == TurnType.ARC:
                g = plan_geom_dict.get(round(nd.chainage, 3))
                if g and g.get('d_in') is not None:
                    nd.azimuth_before = math.degrees(
                        math.atan2(g['d_in'][1],  g['d_in'][0]))
                    nd.azimuth_after  = math.degrees(
                        math.atan2(g['d_out'][1], g['d_out'][0]))

        steps.append(f"  生成 {len(spatial_nodes)} 个空间节点（β=0 退化模式）")
        return spatial_nodes
    
    @staticmethod
    def _merge_long_only(long_nodes: List[LongitudinalNode],
                         steps: List[str]) -> List[SpatialNode]:
        """仅纵断面数据：假设 α=常数（无水平偏转），用桩号差作水平距离"""
        steps.append("")
        spatial_nodes = []
        
        # 假设平面走向为正X方向（方位角α=0），X=桩号，Y=0
        for ln in long_nodes:
            node = SpatialNode(
                chainage=ln.chainage,
                x=ln.chainage, y=0.0, z=ln.elevation,
                azimuth_before=0.0,
                azimuth_after=0.0,
                slope_before=ln.slope_before,
                slope_after=ln.slope_after,
            )
            if ln.turn_angle > 0.1 and ln.turn_type != TurnType.NONE:
                node.has_long_turn = True
                node.long_turn_radius = ln.vertical_curve_radius
                node.long_turn_angle = ln.turn_angle
                node.long_turn_type = ln.turn_type
                node.slope_before = ln.slope_before
                node.slope_after = ln.slope_after
            spatial_nodes.append(node)
        
        steps.append(f"  生成 {len(spatial_nodes)} 个空间节点（α=0 退化模式）")
        return spatial_nodes
    
    # ==================================================================
    # 插值和辅助方法
    # ==================================================================

    @staticmethod
    def _build_plan_geometry(plan_points: List[PlanFeaturePoint]) -> List[dict]:
        """
        预计算每个圆弧型IP点的精确几何参数。

        对圆弧型（TurnType.ARC）的内部IP（非首尾），计算：
          bc_chainage, ec_chainage : 始/终曲点里程
          bc, ec                   : 始/终曲点坐标 (x,y)
          center                   : 弧心坐标 (x,y)
          qz                       : 弧中点坐标 (x,y)，对应桩号 = pp.chainage
          d_in, d_out              : 入/出切线单位向量（数学坐标系）
          left_turn                : 是否左转 (逆时针)

        折管型或首尾IP：所有字段为 None（IP 本身即在轴线上）。
        """
        n = len(plan_points)
        geom = [dict(bc=None, ec=None, center=None, qz=None,
                     bc_chainage=None, ec_chainage=None,
                     d_in=None, d_out=None, left_turn=True)
                for _ in range(n)]
        for i in range(1, n - 1):
            pp = plan_points[i]
            if pp.turn_type != TurnType.ARC or pp.turn_angle < 0.1 or pp.turn_radius <= 0:
                continue
            pp_prev = plan_points[i - 1]
            pp_next = plan_points[i + 1]
            dx_in  = pp.x - pp_prev.x;  dy_in  = pp.y - pp_prev.y
            dx_out = pp_next.x - pp.x;  dy_out = pp_next.y - pp.y
            len_in  = math.sqrt(dx_in**2  + dy_in**2)
            len_out = math.sqrt(dx_out**2 + dy_out**2)
            if len_in < 1e-9 or len_out < 1e-9:
                continue
            d_in  = (dx_in  / len_in,  dy_in  / len_in)
            d_out = (dx_out / len_out, dy_out / len_out)
            R         = pp.turn_radius
            alpha_rad = math.radians(pp.turn_angle)
            T         = R * math.tan(alpha_rad / 2)
            L_arc     = R * alpha_rad
            bc = (pp.x - T * d_in[0],  pp.y - T * d_in[1])
            ec = (pp.x + T * d_out[0], pp.y + T * d_out[1])
            # 转向：d_in × d_out 的 Z 分量 > 0 → 左转（逆时针）
            left_turn = (d_in[0] * d_out[1] - d_in[1] * d_out[0]) > 0
            # 弧心：从 BC 沿法向量偏移 R（左转→左侧，右转→右侧）
            if left_turn:
                center = (bc[0] - R * d_in[1], bc[1] + R * d_in[0])
            else:
                center = (bc[0] + R * d_in[1], bc[1] - R * d_in[0])
            bc_ch = pp.chainage - L_arc / 2.0
            ec_ch = pp.chainage + L_arc / 2.0
            qz = SpatialMerger._arc_point(center, R, bc, alpha_rad / 2.0, left_turn)
            geom[i] = dict(bc=bc, ec=ec, center=center, qz=qz,
                           bc_chainage=bc_ch, ec_chainage=ec_ch,
                           d_in=d_in, d_out=d_out, left_turn=left_turn)
        return geom

    @staticmethod
    def _arc_point(center: Tuple[float, float], R: float,
                   bc: Tuple[float, float], delta: float,
                   left_turn: bool) -> Tuple[float, float]:
        """
        从始曲点 bc 沿圆弧行进 delta 弧度（delta ≥ 0），返回弧上坐标。
        left_turn=True  → 逆时针（角度递增）
        left_turn=False → 顺时针（角度递减）
        """
        theta_bc = math.atan2(bc[1] - center[1], bc[0] - center[0])
        theta = theta_bc + delta if left_turn else theta_bc - delta
        return (center[0] + R * math.cos(theta),
                center[1] + R * math.sin(theta))

    @staticmethod
    def _interpolate_plan(plan_points: List[PlanFeaturePoint],
                          s: float,
                          plan_geom: Optional[List[dict]] = None) -> Tuple[float, float, float]:
        """
        在桩号 s 处精确插值平面坐标 (X, Y, math_azimuth_deg)。

        plan_geom 由 _build_plan_geometry() 预计算时，使用精确圆弧几何：
          - 弧段内（bc_chainage ≤ s ≤ ec_chainage）：沿圆弧插值，坐标在真实轴线上。
          - 切线段（EC_i ≤ s ≤ BC_{i+1}）：在切线方向上线性插值（真实轴线）。
        plan_geom 为 None 时退化为 IP-IP 线性插值（向后兼容）。
        """
        if not plan_points:
            return 0.0, 0.0, 0.0
        if s <= plan_points[0].chainage:
            pp = plan_points[0]
            return pp.x, pp.y, pp.azimuth
        if s >= plan_points[-1].chainage:
            pp = plan_points[-1]
            return pp.x, pp.y, pp.azimuth

        if plan_geom is None:
            for i in range(len(plan_points) - 1):
                p1, p2 = plan_points[i], plan_points[i + 1]
                if p1.chainage <= s <= p2.chainage:
                    ds = p2.chainage - p1.chainage
                    if ds < 1e-6:
                        return p1.x, p1.y, p1.azimuth
                    t = (s - p1.chainage) / ds
                    return (p1.x + t * (p2.x - p1.x),
                            p1.y + t * (p2.y - p1.y),
                            p1.azimuth)
            pp = plan_points[-1]
            return pp.x, pp.y, pp.azimuth

        n = len(plan_points)

        # 1. 弧段内精确插值
        for i in range(n):
            g = plan_geom[i]
            if g['bc_chainage'] is None:
                continue
            if g['bc_chainage'] <= s <= g['ec_chainage']:
                pp  = plan_points[i]
                delta = (s - g['bc_chainage']) / pp.turn_radius
                pt  = SpatialMerger._arc_point(
                    g['center'], pp.turn_radius, g['bc'], delta, g['left_turn'])
                # 切线方向 = 径向方向 ± 90°
                theta_r = math.atan2(pt[1] - g['center'][1],
                                     pt[0] - g['center'][0])
                az = theta_r + math.pi / 2 if g['left_turn'] else theta_r - math.pi / 2
                return pt[0], pt[1], math.degrees(az)

        # 2. 切线段精确插值（EC_i → BC_{i+1}）
        for i in range(n - 1):
            p1, p2 = plan_points[i], plan_points[i + 1]
            g1, g2 = plan_geom[i], plan_geom[i + 1]
            ts_pt = g1['ec']          if g1['ec']          is not None else (p1.x, p1.y)
            ts_ch = g1['ec_chainage'] if g1['ec_chainage'] is not None else p1.chainage
            te_pt = g2['bc']          if g2['bc']          is not None else (p2.x, p2.y)
            te_ch = g2['bc_chainage'] if g2['bc_chainage'] is not None else p2.chainage
            if ts_ch <= s <= te_ch:
                dch = te_ch - ts_ch
                az  = math.atan2(te_pt[1] - ts_pt[1], te_pt[0] - ts_pt[0])
                if dch < 1e-6:
                    return ts_pt[0], ts_pt[1], math.degrees(az)
                t = (s - ts_ch) / dch
                x = ts_pt[0] + t * (te_pt[0] - ts_pt[0])
                y = ts_pt[1] + t * (te_pt[1] - ts_pt[1])
                return x, y, math.degrees(az)

        pp = plan_points[-1]
        return pp.x, pp.y, pp.azimuth
    
    @staticmethod
    def _interpolate_long(long_nodes: List[LongitudinalNode],
                          s: float) -> Tuple[float, float]:
        """
        在桩号 s 处插值纵断面高程 (Z, slope_angle)。

        v2.1 变更（漏洞A修复）：
        - 若区间起点 n1 为 ARC 类型且已存储弧心 (arc_center_s, arc_center_z)，
          使用圆弧精确公式 Z = Zc ± √(Rv² - (s - Sc)²) 代替线性插值。
        - 直线段仍使用线性插值。
        """
        if not long_nodes:
            return 0.0, 0.0
        if s <= long_nodes[0].chainage:
            return long_nodes[0].elevation, long_nodes[0].slope_after
        if s >= long_nodes[-1].chainage:
            return long_nodes[-1].elevation, long_nodes[-1].slope_before
        
        for i in range(len(long_nodes) - 1):
            n1 = long_nodes[i]
            n2 = long_nodes[i + 1]
            if n1.chainage <= s <= n2.chainage:
                ds = n2.chainage - n1.chainage
                if ds < 1e-6:
                    return n1.elevation, n1.slope_after
                
                # 检查是否在竖曲线弧段内
                if (n1.turn_type == TurnType.ARC and
                        n1.arc_center_s is not None and n1.arc_center_z is not None and
                        n1.vertical_curve_radius > 0):
                    Sc = n1.arc_center_s
                    Zc = n1.arc_center_z
                    Rv = n1.vertical_curve_radius
                    r2 = Rv**2 - (s - Sc)**2
                    if r2 >= 0:
                        # 符号取决于起点在弧心的上方还是下方
                        sign = 1.0 if n1.elevation > Zc else -1.0
                        z = Zc + sign * math.sqrt(r2)
                        # 坡角：dZ/ds = -(s-Sc)/(z-Zc) = tanβ，须经 math.atan 转为 β 弧度
                        # 注：不用 atan2，当 z<Zc（谷底弧）时 atan2 会加 ±π 导致错误
                        denom = z - Zc
                        slope = 0.0 if abs(denom) < 1e-9 else math.atan(-(s - Sc) / denom)
                        return z, slope
                    # r2 < 0 说明 s 超出弧段范围，退化为线性
                
                # 直线段：线性插值
                t = (s - n1.chainage) / ds
                z = n1.elevation + t * (n2.elevation - n1.elevation)
                slope = math.atan2(n2.elevation - n1.elevation, ds)
                return z, slope
        
        return long_nodes[-1].elevation, long_nodes[-1].slope_before
    
    @staticmethod
    def _detect_composite_events(spatial_nodes: List[SpatialNode],
                                  plan_points: List[PlanFeaturePoint],
                                  long_nodes: List[LongitudinalNode],
                                  steps: List[str]):
        """
        v2.0 复合弯道事件检测。
        
        在 EVENT_WINDOW 内配对近邻的平面/纵断面转弯事件，
        仅用于 R_3D 合成和局损查表，不修改任何桩号。
        """
        event_window = SpatialMerger.SNAP_TOLERANCE
        
        for nd in spatial_nodes:
            # 有平面转弯但无纵断面转弯：查找近邻纵断面转弯
            if nd.has_plan_turn and not nd.has_long_turn:
                best_ln = None
                best_dist = float('inf')
                for ln in long_nodes:
                    if ln.turn_angle <= 0.1 or ln.turn_type == TurnType.NONE:
                        continue
                    dist = abs(ln.chainage - nd.chainage)
                    if dist <= event_window and dist < best_dist:
                        best_dist = dist
                        best_ln = ln
                if best_ln is not None:
                    nd.has_long_turn = True
                    nd.long_turn_radius = best_ln.vertical_curve_radius
                    nd.long_turn_angle = best_ln.turn_angle
                    nd.long_turn_type = best_ln.turn_type
                    steps.append(f"  复合事件: 平面转弯(桩号{nd.chainage:.3f}m) "
                                 f"配对纵断面转弯(桩号{best_ln.chainage:.3f}m), "
                                 f"距离{best_dist:.3f}m")
            
            # 有纵断面转弯但无平面转弯：查找近邻平面转弯（选最近的）
            if nd.has_long_turn and not nd.has_plan_turn:
                best_pp = None
                best_dist = float('inf')
                for pp in plan_points:
                    if pp.turn_angle <= 0.1 or pp.turn_type == TurnType.NONE:
                        continue
                    dist = abs(pp.chainage - nd.chainage)
                    if dist <= event_window and dist < best_dist:
                        best_dist = dist
                        best_pp = pp
                if best_pp is not None:
                    nd.has_plan_turn = True
                    nd.plan_turn_radius = best_pp.turn_radius
                    nd.plan_turn_angle = best_pp.turn_angle
                    nd.plan_turn_type = best_pp.turn_type
                    steps.append(f"  复合事件: 纵断面转弯(桩号{nd.chainage:.3f}m) "
                                 f"配对平面转弯(桩号{best_pp.chainage:.3f}m), "
                                 f"距离{best_dist:.3f}m")

    @staticmethod
    def _fill_adjacent_angles(spatial_nodes: List[SpatialNode],
                              plan_points: List[PlanFeaturePoint],
                              long_nodes: List[LongitudinalNode],
                              plan_geom_dict: Optional[dict] = None):
        """
        填充各空间节点的前后方位角和坡角。
        
        v2.0 变更：
        - 方位角：atan2(ΔY, ΔX) → 数学方位角（度），正东=0°，逆时针
        - 坡角 β：用 Δs（桩号差 = 平面弧长参数增量）替代 dH（XY 弦长），
          消除圆弧段上弦长 < 弧长导致的 β 系统性偏陡
        - before/after 分别用各自方向的 Δs 计算
        """
        n = len(spatial_nodes)
        if n < 2:
            return
        
        # 从坐标差推算方位角，用桩号差推算坡角
        for i in range(n):
            nd = spatial_nodes[i]
            
            # 后方位角和坡角（从当前点到下一个点）
            if i < n - 1:
                nx = spatial_nodes[i + 1]
                dx = nx.x - nd.x
                dy = nx.y - nd.y
                dz = nx.z - nd.z
                ds = nx.chainage - nd.chainage  # 桩号差（平面弧长参数增量）
                dh = math.sqrt(dx**2 + dy**2)
                
                if dh > 1e-6:
                    nd.azimuth_after = math.degrees(math.atan2(dy, dx))
                if abs(ds) > 1e-6:
                    nd.slope_after = math.atan2(dz, ds)
            
            # 前方位角和坡角（从上一个点到当前点）
            if i > 0:
                px = spatial_nodes[i - 1]
                dx = nd.x - px.x
                dy = nd.y - px.y
                dz = nd.z - px.z
                ds = nd.chainage - px.chainage  # 桩号差
                dh = math.sqrt(dx**2 + dy**2)
                
                if dh > 1e-6:
                    nd.azimuth_before = math.degrees(math.atan2(dy, dx))
                if abs(ds) > 1e-6:
                    nd.slope_before = math.atan2(dz, ds)
        
        # 首尾节点补齐
        if n >= 2:
            spatial_nodes[0].azimuth_before = spatial_nodes[0].azimuth_after
            spatial_nodes[0].slope_before = spatial_nodes[0].slope_after
            spatial_nodes[-1].azimuth_after = spatial_nodes[-1].azimuth_before
            spatial_nodes[-1].slope_after = spatial_nodes[-1].slope_before
        
        # 对有纵断面转弯的节点，用纵断面数据覆盖坡角（精确坡角，优于坐标差近似）
        for nd in spatial_nodes:
            if nd.has_long_turn:
                best_ln = None
                best_dist = float('inf')
                for ln in long_nodes:
                    dist = abs(ln.chainage - nd.chainage)
                    if dist <= SpatialMerger.SNAP_TOLERANCE and dist < best_dist:
                        best_dist = dist
                        best_ln = ln
                if best_ln is not None:
                    nd.slope_before = best_ln.slope_before
                    nd.slope_after = best_ln.slope_after

        # 对圆弧型平面转弯节点，用入/出切线精确方向覆盖坐标差推算值。
        if plan_geom_dict:
            for nd in spatial_nodes:
                if nd.has_plan_turn and nd.plan_turn_type == TurnType.ARC:
                    g = plan_geom_dict.get(round(nd.chainage, 3))
                    if g and g.get('d_in') is not None:
                        nd.azimuth_before = math.degrees(
                            math.atan2(g['d_in'][1],  g['d_in'][0]))
                        nd.azimuth_after  = math.degrees(
                            math.atan2(g['d_out'][1], g['d_out'][0]))
    
    @staticmethod
    def _fill_azimuths_from_plan(spatial_nodes: List[SpatialNode],
                                  plan_points: List[PlanFeaturePoint]):
        """仅平面模式：从IP点方位角填充空间节点"""
        for i, nd in enumerate(spatial_nodes):
            # 找对应的 plan_point
            for pp in plan_points:
                if abs(pp.chainage - nd.chainage) < 0.1:
                    nd.azimuth_before = pp.azimuth
                    nd.azimuth_after = pp.azimuth
                    break
        
        # 从坐标差推算方位角
        n = len(spatial_nodes)
        for i in range(n):
            nd = spatial_nodes[i]
            if i < n - 1:
                nx = spatial_nodes[i + 1]
                dx = nx.x - nd.x
                dy = nx.y - nd.y
                if math.sqrt(dx**2 + dy**2) > 1e-6:
                    nd.azimuth_after = math.degrees(math.atan2(dy, dx))
            if i > 0:
                px = spatial_nodes[i - 1]
                dx = nd.x - px.x
                dy = nd.y - px.y
                if math.sqrt(dx**2 + dy**2) > 1e-6:
                    nd.azimuth_before = math.degrees(math.atan2(dy, dx))
        
        if n >= 2:
            spatial_nodes[0].azimuth_before = spatial_nodes[0].azimuth_after
            spatial_nodes[-1].azimuth_after = spatial_nodes[-1].azimuth_before
    
    # ==================================================================
    # 空间转角计算
    # ==================================================================
    
    @staticmethod
    def _compute_spatial_angles(spatial_nodes: List[SpatialNode],
                                steps: List[str],
                                verbose: bool = True):
        """
        计算每个转弯节点的三维空间转角 θ_3D
        
        数学公式：
        折线型: cos(θ_3D) = cos(β₁)·cos(β₂)·cos(Δα) + sin(β₁)·sin(β₂)
        圆弧型: θ_3D = arccos(T_start · T_end)
           T(s) = (cos(β)·cos(α), cos(β)·sin(α), sin(β))
        """
        for nd in spatial_nodes:
            if not nd.has_turn:
                continue
            
            α_before = math.radians(nd.azimuth_before)
            α_after = math.radians(nd.azimuth_after)
            β_before = nd.slope_before
            β_after = nd.slope_after
            
            # 计算三维单位切向量
            T_before = (
                math.cos(β_before) * math.cos(α_before),
                math.cos(β_before) * math.sin(α_before),
                math.sin(β_before),
            )
            T_after = (
                math.cos(β_after) * math.cos(α_after),
                math.cos(β_after) * math.sin(α_after),
                math.sin(β_after),
            )
            
            # 点积
            dot = (T_before[0] * T_after[0] + 
                   T_before[1] * T_after[1] + 
                   T_before[2] * T_after[2])
            
            # 防止浮点误差超出 [-1, 1]
            dot = max(-1.0, min(1.0, dot))
            
            theta_3d_rad = math.acos(dot)
            theta_3d_deg = math.degrees(theta_3d_rad)
            
            nd.spatial_turn_angle = theta_3d_deg
            
            # 确定有效半径和类型
            if nd.has_plan_turn and nd.has_long_turn:
                # 重叠弯道：微分几何精确曲率合成公式
                # κ² = 1/R_v² + cos⁴β/R_h²
                # R_3D = R_h·R_v / √(R_h² + R_v²·cos⁴β)
                R_h = nd.plan_turn_radius if nd.plan_turn_radius > 0 else 0.0
                R_v = nd.long_turn_radius if nd.long_turn_radius > 0 else 0.0
                if R_h > 0 and R_v > 0:
                    # 取绝对值平均：对于U形管底部β变号的情况，|β_before|+|β_after| 正确代表弯道坡度赠，直接平均会其近与0（错误）
                    β_avg = (abs(β_before) + abs(β_after)) / 2.0
                    cos_β = math.cos(β_avg)
                    cos4_β = cos_β ** 4
                    # 极限校核短路：R_v 极大时退化为 R_h/cos²β，R_h 极大时退化为 R_v
                    if R_v > 1e6:
                        nd.effective_radius = R_h / (cos_β ** 2) if abs(cos_β) > 1e-9 else R_h
                    elif R_h > 1e6:
                        nd.effective_radius = R_v
                    else:
                        nd.effective_radius = (R_h * R_v) / math.sqrt(
                            R_h**2 + R_v**2 * cos4_β
                        )
                elif R_h > 0:
                    nd.effective_radius = R_h
                elif R_v > 0:
                    nd.effective_radius = R_v
                else:
                    nd.effective_radius = 0.0
                # 如果任一为圆弧，整体视为圆弧
                if nd.plan_turn_type == TurnType.ARC or nd.long_turn_type == TurnType.ARC:
                    nd.effective_turn_type = TurnType.ARC
                else:
                    nd.effective_turn_type = TurnType.FOLD
            elif nd.has_plan_turn:
                nd.effective_radius = nd.plan_turn_radius
                nd.effective_turn_type = nd.plan_turn_type
            elif nd.has_long_turn:
                nd.effective_radius = nd.long_turn_radius
                nd.effective_turn_type = nd.long_turn_type
            
            if verbose and theta_3d_deg > 0.1:
                delta_alpha = math.degrees(α_after - α_before)
                radius_detail = f"R={nd.effective_radius:.2f}m"
                if nd.has_plan_turn and nd.has_long_turn:
                    R_h = nd.plan_turn_radius
                    R_v = nd.long_turn_radius
                    β_avg_deg = math.degrees((abs(β_before) + abs(β_after)) / 2.0)
                    radius_detail = (f"R_3D={nd.effective_radius:.2f}m "
                                     f"(精确曲率合成: R_h={R_h:.1f}, R_v={R_v:.1f}, "
                                     f"β_avg={β_avg_deg:.2f}°)")
                steps.append(
                    f"  桩号 {nd.chainage:.2f}m: "
                    f"Δα={delta_alpha:.2f}°, "
                    f"β前={math.degrees(β_before):.2f}°, β后={math.degrees(β_after):.2f}°"
                    f" → θ_3D={theta_3d_deg:.2f}°"
                    f" | {radius_detail} ({nd.effective_turn_type.value})"
                )
