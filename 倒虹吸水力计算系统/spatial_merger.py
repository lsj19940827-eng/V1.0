# -*- coding: utf-8 -*-
"""
倒虹吸水力计算软件 - 三维空间合并引擎

核心算法：将平面图(X,Y)和纵断面(S,Z)数据按桩号合并为三维空间曲线 R(s)=[x(s),y(s),z(s)]，
计算空间长度 L_spatial 和空间转角 θ_3D，用于精确的水头损失计算。

数学基础：
  单位切向量 T(s) = (cosβ·cosα, cosβ·sinα, sinβ)
    α = 平面方位角, β = 纵断面坡角
  
  空间转角 θ_3D = arccos(T_before · T_after)
    折线型: cos(θ_3D) = cosβ₁·cosβ₂·cos(Δα) + sinβ₁·sinβ₂
    圆弧型: θ_3D = arccos(T_start · T_end)
  
  空间长度 L = Σ√(ΔX² + ΔY² + ΔZ²)
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
        
        # 计算空间长度
        steps.append("")
        steps.append("【空间长度计算】")
        total_L = 0.0
        seg_lengths = []
        for i in range(len(spatial_nodes) - 1):
            n1 = spatial_nodes[i]
            n2 = spatial_nodes[i + 1]
            dx = n2.x - n1.x
            dy = n2.y - n1.y
            dz = n2.z - n1.z
            L_seg = math.sqrt(dx**2 + dy**2 + dz**2)
            seg_lengths.append(L_seg)
            total_L += L_seg
            if verbose:
                steps.append(f"  段{i}: 桩号 {n1.chainage:.2f}→{n2.chainage:.2f}, "
                           f"ΔX={dx:.3f}, ΔY={dy:.3f}, ΔZ={dz:.3f}, "
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
        
        result.xi_spatial_bends = xi_total  # 损失系数在 hydraulics 中按 D 查表计算
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
        steps.append("【步骤1：按桩号合并特征点】")
        
        # 收集所有特征点桩号
        plan_dict = {}
        for pp in plan_points:
            plan_dict[round(pp.chainage, 3)] = pp
        
        # 构建平面转弯桩号列表（用于邻近吸附判定）
        plan_turn_chainages = [round(pp.chainage, 3)
                               for pp in plan_points
                               if pp.turn_angle > 0.1 and pp.turn_type != TurnType.NONE]
        
        long_dict = {}
        snap_tol = SpatialMerger.SNAP_TOLERANCE
        for ln in long_nodes:
            ln_ch = round(ln.chainage, 3)
            # 邻近吸附：当纵断面弯道与某平面弯道桩号接近（但不完全重合）时，
            # 将纵断面弯道吸附到平面弯道的桩号上，使两者被识别为同一位置的重叠弯道
            if ln.turn_angle > 0.1 and ln.turn_type != TurnType.NONE:
                for pt_ch in plan_turn_chainages:
                    dist = abs(pt_ch - ln_ch)
                    if 0.001 < dist <= snap_tol:
                        steps.append(f"  邻近吸附: 纵断面弯(桩号{ln_ch:.3f}m) "
                                     f"→ 平面弯(桩号{pt_ch:.3f}m), "
                                     f"距离{dist:.3f}m < 容差{snap_tol}m")
                        ln_ch = pt_ch
                        break
            long_dict[ln_ch] = ln
        
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
                x, y = pp.x, pp.y
                azimuth = pp.azimuth
            else:
                x, y, azimuth = SpatialMerger._interpolate_plan(plan_points, s)
            
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
        SpatialMerger._fill_adjacent_angles(spatial_nodes, plan_points, long_nodes)
        
        return spatial_nodes
    
    @staticmethod
    def _merge_plan_only(plan_points: List[PlanFeaturePoint],
                         steps: List[str]) -> List[SpatialNode]:
        """仅平面数据：假设 β=0（无纵坡），Z=0"""
        steps.append("")
        spatial_nodes = []
        for pp in plan_points:
            node = SpatialNode(
                chainage=pp.chainage,
                x=pp.x, y=pp.y, z=0.0,
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
        
        # 填充方位角
        SpatialMerger._fill_azimuths_from_plan(spatial_nodes, plan_points)
        
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
    def _interpolate_plan(plan_points: List[PlanFeaturePoint], 
                          s: float) -> Tuple[float, float, float]:
        """在桩号 s 处插值平面坐标 (X, Y, azimuth)"""
        if not plan_points:
            return 0.0, 0.0, 0.0
        
        # 边界处理
        if s <= plan_points[0].chainage:
            pp = plan_points[0]
            return pp.x, pp.y, pp.azimuth
        if s >= plan_points[-1].chainage:
            pp = plan_points[-1]
            return pp.x, pp.y, pp.azimuth
        
        # 查找插值区间
        for i in range(len(plan_points) - 1):
            p1 = plan_points[i]
            p2 = plan_points[i + 1]
            if p1.chainage <= s <= p2.chainage:
                ds = p2.chainage - p1.chainage
                if ds < 1e-6:
                    return p1.x, p1.y, p1.azimuth
                t = (s - p1.chainage) / ds
                x = p1.x + t * (p2.x - p1.x)
                y = p1.y + t * (p2.y - p1.y)
                azimuth = p1.azimuth  # 方位角在两IP之间保持不变（直线段）
                return x, y, azimuth
        
        pp = plan_points[-1]
        return pp.x, pp.y, pp.azimuth
    
    @staticmethod
    def _interpolate_long(long_nodes: List[LongitudinalNode],
                          s: float) -> Tuple[float, float]:
        """在桩号 s 处插值纵断面高程 (Z, slope_angle)"""
        if not long_nodes:
            return 0.0, 0.0
        
        # 边界处理
        if s <= long_nodes[0].chainage:
            return long_nodes[0].elevation, long_nodes[0].slope_after
        if s >= long_nodes[-1].chainage:
            return long_nodes[-1].elevation, long_nodes[-1].slope_before
        
        # 查找插值区间
        for i in range(len(long_nodes) - 1):
            n1 = long_nodes[i]
            n2 = long_nodes[i + 1]
            if n1.chainage <= s <= n2.chainage:
                ds = n2.chainage - n1.chainage
                if ds < 1e-6:
                    return n1.elevation, n1.slope_after
                t = (s - n1.chainage) / ds
                z = n1.elevation + t * (n2.elevation - n1.elevation)
                # 坡角：取该段的坡角
                dz = n2.elevation - n1.elevation
                slope = math.atan2(dz, ds)
                return z, slope
        
        return long_nodes[-1].elevation, long_nodes[-1].slope_before
    
    @staticmethod
    def _fill_adjacent_angles(spatial_nodes: List[SpatialNode],
                              plan_points: List[PlanFeaturePoint],
                              long_nodes: List[LongitudinalNode]):
        """填充各空间节点的前后方位角和坡角"""
        n = len(spatial_nodes)
        if n < 2:
            return
        
        # 从坐标差推算方位角和坡角
        for i in range(n):
            nd = spatial_nodes[i]
            
            # 后方位角（从当前点到下一个点）
            if i < n - 1:
                nx = spatial_nodes[i + 1]
                dx = nx.x - nd.x
                dy = nx.y - nd.y
                dz = nx.z - nd.z
                dh = math.sqrt(dx**2 + dy**2)
                
                if dh > 1e-6:
                    nd.azimuth_after = math.degrees(math.atan2(dy, dx))
                    nd.slope_after = math.atan2(dz, dh)
            
            # 前方位角（从上一个点到当前点）
            if i > 0:
                px = spatial_nodes[i - 1]
                dx = nd.x - px.x
                dy = nd.y - px.y
                dz = nd.z - px.z
                dh = math.sqrt(dx**2 + dy**2)
                
                if dh > 1e-6:
                    nd.azimuth_before = math.degrees(math.atan2(dy, dx))
                    nd.slope_before = math.atan2(dz, dh)
        
        # 首尾节点补齐
        if n >= 2:
            spatial_nodes[0].azimuth_before = spatial_nodes[0].azimuth_after
            spatial_nodes[0].slope_before = spatial_nodes[0].slope_after
            spatial_nodes[-1].azimuth_after = spatial_nodes[-1].azimuth_before
            spatial_nodes[-1].slope_after = spatial_nodes[-1].slope_before
        
        # 对有纵断面转弯的节点，用纵断面数据覆盖坡角
        for nd in spatial_nodes:
            if nd.has_long_turn:
                # 从 long_nodes 查找匹配节点获取精确坡角
                for ln in long_nodes:
                    if abs(ln.chainage - nd.chainage) < 0.1:
                        if ln.slope_before != 0 or ln.slope_after != 0:
                            nd.slope_before = ln.slope_before
                            nd.slope_after = ln.slope_after
                        break
    
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
                # 平面和纵断面同时转弯（重叠弯道）：微分几何精确曲率合成公式
                #
                # 推导：T(s) = (cosβ·cosα, cosβ·sinα, sinβ)
                #   κ² = |dT/ds|² = (dβ/ds)² + cos²β·(dα/ds)²
                # 工程半径 R_h, R_v 基于水平投影距离定义，换算到弧长参数：
                #   dα/ds = cosβ/R_h, dβ/ds = cosβ/R_v
                # 代入得：
                #   κ_3D = cosβ · √(1/R_v² + cos²β/R_h²)
                #   R_3D = R_h·R_v / (cosβ · √(R_h² + R_v²·cos²β))
                #
                # β=0 时退化为 R_3D = R_h·R_v / √(R_h² + R_v²)
                R_h = nd.plan_turn_radius if nd.plan_turn_radius > 0 else 0.0
                R_v = nd.long_turn_radius if nd.long_turn_radius > 0 else 0.0
                if R_h > 0 and R_v > 0:
                    β_avg = (abs(β_before) + abs(β_after)) / 2.0
                    cos_β = math.cos(β_avg)
                    cos2_β = cos_β ** 2
                    nd.effective_radius = (R_h * R_v) / (
                        cos_β * math.sqrt(R_h**2 + R_v**2 * cos2_β)
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
