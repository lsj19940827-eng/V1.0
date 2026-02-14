# -*- coding: utf-8 -*-
"""
倒虹吸水力计算软件 - 水力计算核心
依据《倒虹吸管设计计算》附录L规范
执行设计截面计算、水头损失求解及校验

水头损失分三部分：
  ΔZ1 - 进口渐变段水面落差
  ΔZ2 - 管身段总水头损失 (沿程损失 hf + 局部损失 hj)
  ΔZ3 - 出口渐变段水面落差
  总水面落差 ΔZ = ΔZ1 + ΔZ2 - ΔZ3
"""

import math
from typing import List, Optional
from siphon_models import (
    GlobalParameters, StructureSegment, CalculationResult, SegmentType, SegmentDirection,
    PlanFeaturePoint, LongitudinalNode, SpatialMergeResult, TurnType
)
from siphon_coefficients import CoefficientService
from spatial_merger import SpatialMerger


class HydraulicCore:
    """水力计算核心类（依据附录L规范）"""
    
    # 重力加速度
    GRAVITY = 9.81
    
    @staticmethod
    def round_diameter(d_theory: float) -> float:
        """
        根据工程习惯对管径取整
        管径≤1m，按照0.05m取整
        管径≤1.6m，按照0.1m取整
        管径≤5m，按照0.2m取整
        
        Args:
            d_theory: 理论直径 (m)
            
        Returns:
            取整后的管径 (m)
        """
        if d_theory <= 1.0:
            step = 0.05
        elif d_theory <= 1.6:
            step = 0.1
        else:
            step = 0.2
        
        # 向上取整
        return math.ceil(d_theory / step) * step
    
    @staticmethod
    def execute_calculation(global_params: GlobalParameters,
                           segments: List[StructureSegment],
                           diameter_override: Optional[float] = None,
                           verbose: bool = False,
                           plan_segments: List[StructureSegment] = None,
                           plan_total_length: float = 0.0,
                           plan_feature_points: List[PlanFeaturePoint] = None,
                           longitudinal_nodes: List[LongitudinalNode] = None,
                           ) -> CalculationResult:
        """
        执行核心计算（依据附录L规范）
        
        支持三种计算模式：
        A. 三维空间合并模式（优先）：当同时有 plan_feature_points 和 longitudinal_nodes 时
           使用 SpatialMerger 计算空间长度和空间转角 θ_3D
        B. 平面+纵断面独立模式（退化）：分别计算平面弯道和纵向弯道损失
        C. 单数据源模式（退化）：仅有平面或仅有纵断面时的简化计算
        
        Args:
            global_params: 全局参数
            segments: 特殊结构段列表（进水口/出水口/拦污栅/闸门槽等，仅贡献ξ）
            diameter_override: 用户指定的管径
            verbose: 是否输出详细计算过程
            plan_segments: 平面段列表（旧接口，向后兼容）
            plan_total_length: 平面总水平长度 (m)
            plan_feature_points: 平面IP特征点列表（新接口，用于三维空间合并）
            longitudinal_nodes: 纵断面变坡点列表（新接口，来自DXF导入）
            
        Returns:
            计算结果对象
        """
        if plan_segments is None:
            plan_segments = []
        if plan_feature_points is None:
            plan_feature_points = []
        if longitudinal_nodes is None:
            longitudinal_nodes = []
        result = CalculationResult()
        steps = []
        
        Q = global_params.Q
        v_guess = global_params.v_guess
        n = global_params.roughness_n
        H_up = global_params.H_up
        H_down = global_params.H_down
        g = HydraulicCore.GRAVITY
        
        # 进出口渐变段流速
        v_1 = global_params.v_channel_in if global_params.v_channel_in > 0 else 0.0   # 进口渐变段始端流速 v₁
        v_2 = global_params.v_pipe_in if global_params.v_pipe_in > 0 else 0.0         # 进口渐变段末端流速 v₂
        v_out = global_params.v_channel_out if global_params.v_channel_out > 0 else 0.0  # 出口渐变段始端流速 v
        v_3 = global_params.v_pipe_out if global_params.v_pipe_out > 0 else 0.0       # 出口渐变段末端流速 v₃
        result.velocity_channel_in = v_1
        result.velocity_channel_out = v_3
        
        # ========== 步骤1：几何设计与流速计算 (Geometry & Velocity) ==========
        steps.append("=" * 50)
        steps.append("步骤1：几何设计与流速计算 (Geometry & Velocity)")
        steps.append("=" * 50)
        
        # 管道断面积 ω = Q / v_guess
        omega = Q / v_guess
        steps.append(f"管道断面积 ω = Q / v_guess = {Q:.4f} / {v_guess:.4f} = {omega:.4f} m²")
        
        # 理论直径 D = sqrt(4ω / π)
        D_theory = math.sqrt(4 * omega / math.pi)
        steps.append(f"理论直径 D = √(4ω/π) = √(4×{omega:.4f}/π) = {D_theory:.4f} m")
        
        # 管径取整或使用用户指定值
        if diameter_override is not None:
            D = diameter_override
            steps.append(f"使用用户指定的自定义设计管径: D = {D:.4f} m")
        else:
            D = HydraulicCore.round_diameter(D_theory)
            steps.append(f"管径取整: D = {D:.4f} m (理论值 {D_theory:.4f} m)")
        
        result.diameter = D
        result.diameter_theory = D_theory
        
        # 实际断面积
        A_actual = math.pi * D ** 2 / 4
        result.area = A_actual
        steps.append(f"实际断面积 A = πD²/4 = π×{D:.4f}²/4 = {A_actual:.4f} m²")
        
        # 实际流速 v = Q/A = 4Q/(πD²)
        v = Q / A_actual
        result.velocity = v
        steps.append(f"实际流速 v = Q/A = {Q:.4f}/{A_actual:.4f} = {v:.4f} m/s")
        
        # 水力半径 R_h = D / 4 (圆管满流)
        R_h = D / 4
        result.hydraulic_radius = R_h
        steps.append(f"水力半径 R_h = D/4 = {D:.4f}/4 = {R_h:.4f} m")
        
        # ========== 步骤2：阻力参数初始化 (Resistance Setup) ==========
        steps.append("")
        steps.append("=" * 50)
        steps.append("步骤2：阻力参数初始化 (Resistance Setup)")
        steps.append("=" * 50)
        
        # 谢才系数 C = (1/n) * R^(1/6) (依据 L.1.4)
        C = (1 / n) * (R_h ** (1/6))
        result.chezy_c = C
        steps.append(f"谢才系数 C = (1/n) × R_h^(1/6) = (1/{n:.4f}) × {R_h:.4f}^(1/6) = {C:.4f}")
        
        # 更新局部阻力系数
        steps.append("")
        steps.append("局部阻力系数计算：")
        
        xi_sum_middle = 0.0  # 管身段局部阻力系数和（不含进出口）
        L_friction = 0.0     # 沿程损失计算长度
        length_source = ""
        
        # ===== 判断计算模式 =====
        has_spatial_data = (len(plan_feature_points) >= 2 or len(longitudinal_nodes) >= 2)
        
        if has_spatial_data:
            # ===== 模式A：三维空间合并计算 =====
            steps.append("")
            steps.append("【三维空间合并计算】")
            
            spatial_result = SpatialMerger.merge_and_compute(
                plan_feature_points, longitudinal_nodes,
                pipe_diameter=D, verbose=verbose
            )
            
            # 添加空间合并的详细步骤
            if verbose:
                steps.extend(spatial_result.computation_steps)
            
            # 空间弯道损失系数
            xi_spatial_bends = 0.0
            steps.append("")
            steps.append("【空间弯道损失系数查表】")
            for nd in spatial_result.nodes:
                if nd.has_turn and nd.spatial_turn_angle > 0.1:
                    if nd.effective_turn_type == TurnType.ARC and nd.effective_radius > 0:
                        xi_b, b_steps = CoefficientService.calculate_bend_coeff(
                            nd.effective_radius, D, nd.spatial_turn_angle, verbose=True
                        )
                        xi_spatial_bends += xi_b
                        steps.append(f"  桩号{nd.chainage:.1f}m 空间弯管: "
                                   f"R={nd.effective_radius:.2f}m, θ_3D={nd.spatial_turn_angle:.1f}°")
                        steps.append(f"    {b_steps.replace(chr(10), chr(10) + '    ')}")
                    elif nd.effective_turn_type == TurnType.FOLD:
                        xi_f, f_steps = CoefficientService.calculate_fold_coeff(
                            nd.spatial_turn_angle, verbose=True
                        )
                        xi_spatial_bends += xi_f
                        steps.append(f"  桩号{nd.chainage:.1f}m 空间折管: "
                                   f"θ_3D={nd.spatial_turn_angle:.1f}°")
                        steps.append(f"    {f_steps.replace(chr(10), chr(10) + '    ')}")
            
            xi_sum_middle += xi_spatial_bends
            steps.append(f"  空间弯道损失系数合计 Σξ_空间弯 = {xi_spatial_bends:.4f}")
            
            # 空间长度
            L_friction = spatial_result.total_spatial_length
            length_source = "三维空间合并计算"
        else:
            # ===== 模式B：旧模式（向后兼容） =====
            steps.append("")
            steps.append("【传统模式（无空间合并数据）】")
            
            total_length = 0.0
            total_spatial_length = 0.0
            has_longitudinal_length = False
            
            # 平面弯道损失
            xi_plan_bends = 0.0
            if plan_segments:
                steps.append("")
                steps.append("平面段（水平转弯）：")
                for j, pseg in enumerate(plan_segments):
                    if pseg.segment_type == SegmentType.BEND and pseg.radius > 0 and pseg.angle > 0:
                        xi_pb, pb_steps = CoefficientService.calculate_bend_coeff(
                            pseg.radius, D, pseg.angle, verbose=True
                        )
                        pseg.xi_calc = xi_pb
                        xi_plan_bends += xi_pb
                        steps.append(f"  平面弯管{j}: R={pseg.radius:.2f}m, θ={pseg.angle:.1f}°")
                        steps.append(f"    {pb_steps.replace(chr(10), chr(10) + '    ')}")
                xi_sum_middle += xi_plan_bends
            
            # 确定长度
            if plan_total_length > 0:
                L_friction = plan_total_length
                length_source = "平面总长度(MC出-MC进)"
            else:
                L_friction = total_length
                length_source = "纵断面段水平长度之和"
        
        # ===== 2.5 特殊结构段（进水口/出水口/拦污栅/闸门槽等）：仅贡献ξ =====
        steps.append("")
        steps.append("【特殊结构段】")
        for i, seg in enumerate(segments):
            if seg.segment_type == SegmentType.TRASH_RACK:
                xi = seg.get_xi()
                xi_sum_middle += xi
                steps.append(f"  拦污栅{i}: ξ={xi:.4f}")
            elif seg.segment_type == SegmentType.GATE_SLOT:
                xi = seg.get_xi()
                xi_sum_middle += xi
                steps.append(f"  闸门槽{i}: ξ={xi:.4f}")
            elif seg.segment_type == SegmentType.BYPASS_PIPE:
                xi = seg.get_xi()
                xi_sum_middle += xi
                steps.append(f"  旁通管{i}: ξ={xi:.4f}")
            elif seg.segment_type == SegmentType.OTHER:
                xi = seg.get_xi()
                xi_sum_middle += xi
                if seg.length > 0:
                    L_friction += seg.length
                steps.append(f"  其他段{i}: L={seg.length:.2f}m, ξ={xi:.4f}")
        
        result.total_length = L_friction
        result.xi_sum_middle = xi_sum_middle
        steps.append("")
        steps.append(f"沿程损失计算采用: {length_source} = {L_friction:.4f} m")
        steps.append(f"管身段局部阻力系数和 Σξ_middle = {xi_sum_middle:.4f}")
        
        # 进出口系数
        xi_1 = global_params.xi_inlet   # 进口局部损失系数
        xi_2 = global_params.xi_outlet  # 出口局部损失系数
        result.xi_inlet = xi_1
        result.xi_outlet = xi_2
        steps.append(f"进口系数 ξ_1 = {xi_1:.4f} (表 L.1.2)")
        steps.append(f"出口系数 ξ_2 = {xi_2:.4f} (表 L.1.4-5 或 L.1.3)")
        
        # ========== 步骤3：水头损失求解 (Head Loss Calculation) ==========
        steps.append("")
        steps.append("=" * 50)
        steps.append("步骤3：水头损失求解 (Head Loss Calculation)")
        steps.append("=" * 50)
        steps.append("依据规范 L.1.6: ΔZ = ΔZ1 + ΔZ2 - ΔZ3")
        steps.append("")
        
        # ---------- 3.1 进口渐变段水面落差 ΔZ1 (公式 L.1.2-2) ----------
        steps.append("【3.1 进口渐变段水面落差 ΔZ1】")
        steps.append("  公式 L.1.2-2: ΔZ1 = (1 + ξ1) × (v₂² - v₁²) / (2g)")
        steps.append("  注: v₁ = 进口渐变段始端流速，v₂ = 进口渐变段末端流速")
        
        delta_Z1 = (1 + xi_1) * (v_2**2 - v_1**2) / (2 * g)
        result.loss_inlet = delta_Z1
        steps.append(f"  ΔZ1 = (1 + {xi_1:.4f}) × ({v_2:.4f}² - {v_1:.4f}²) / (2×{g})")
        steps.append(f"      = {1 + xi_1:.4f} × ({v_2**2:.4f} - {v_1**2:.4f}) / {2*g:.2f}")
        steps.append(f"      = {delta_Z1:.4f} m")
        steps.append("")
        
        # ---------- 3.2 管身段总水头损失 ΔZ2 (公式 L.1.4-7) ----------
        steps.append("【3.2 管身段总水头损失 ΔZ2】")
        steps.append("  公式 L.1.4-7: ΔZ2 = hf + hj")
        steps.append("")
        
        # 沿程损失 hf = L × v² / (C² × R_h)
        # 使用空间长度（已在步骤2确定为 L_friction）
        h_f = (v ** 2 * L_friction) / (C ** 2 * R_h)
        result.loss_friction = h_f
        steps.append("  沿程损失 hf = L × v² / (C² × R_h)")
        steps.append(f"    = {L_friction:.4f} × {v:.4f}² / ({C:.4f}² × {R_h:.4f})")
        steps.append(f"    = {h_f:.4f} m")
        steps.append("")
        
        # 管身局部损失 hj = Σξ_middle × v² / (2g)
        h_j = xi_sum_middle * v ** 2 / (2 * g)
        result.loss_local = h_j
        steps.append("  管身局部损失 hj = Σξ_middle × v² / (2g)")
        steps.append(f"    = {xi_sum_middle:.4f} × {v:.4f}² / (2×{g})")
        steps.append(f"    = {h_j:.4f} m")
        steps.append("")
        
        # ΔZ2 = hf + hj
        delta_Z2 = h_f + h_j
        result.loss_pipe = delta_Z2
        steps.append(f"  ΔZ2 = hf + hj = {h_f:.4f} + {h_j:.4f} = {delta_Z2:.4f} m")
        steps.append("")
        
        # ---------- 3.3 出口渐变段水面落差 ΔZ3 (公式 L.1.3-2) ----------
        steps.append("【3.3 出口渐变段水面落差 ΔZ3】")
        steps.append("  公式 L.1.3-2: ΔZ3 = (1 - ξ2) × (v² - v₃²) / (2g)")
        steps.append("  注: v = 出口渐变段始端流速，v₃ = 出口渐变段末端流速")
        
        delta_Z3 = (1 - xi_2) * (v_out**2 - v_3**2) / (2 * g)
        result.loss_outlet = delta_Z3
        steps.append(f"  ΔZ3 = (1 - {xi_2:.4f}) × ({v_out:.4f}² - {v_3:.4f}²) / (2×{g})")
        steps.append(f"      = {1 - xi_2:.4f} × ({v_out**2:.4f} - {v_3**2:.4f}) / {2*g:.2f}")
        steps.append(f"      = {delta_Z3:.4f} m")
        steps.append("")
        
        # ---------- 3.4 总水面落差 ΔZ ----------
        steps.append("【3.4 总水面落差 ΔZ】")
        steps.append("  公式 L.1.6: ΔZ = ΔZ1 + ΔZ2 - ΔZ3")
        
        delta_Z = delta_Z1 + delta_Z2 - delta_Z3
        result.total_head_loss = delta_Z
        steps.append(f"  ΔZ = {delta_Z1:.4f} + {delta_Z2:.4f} - {delta_Z3:.4f}")
        steps.append(f"     = {delta_Z:.4f} m")
        
        # ========== 步骤4：校验与结果生成 (Verification) ==========
        steps.append("")
        steps.append("=" * 50)
        steps.append("步骤4：校验与结果生成 (Verification)")
        steps.append("=" * 50)
        
        # 可用水位差
        available_head = H_up - H_down
        result.available_head_diff = available_head
        steps.append(f"可用水位差 (H_up - H_down) = {H_up:.4f} - {H_down:.4f} = {available_head:.4f} m")
        
        # 所需水位差 = 总水面落差 ΔZ
        result.required_head_diff = delta_Z
        steps.append(f"所需水位差 ΔZ = {delta_Z:.4f} m")
        
        # 校验: (H_up - H_down) >= ΔZ
        if available_head >= delta_Z:
            result.is_verified = True
            margin = available_head - delta_Z
            result.message = f"校验通过！可用水位差 {available_head:.4f}m >= 所需落差 {delta_Z:.4f}m，安全裕度 {margin:.4f}m"
            steps.append(f"✓ {result.message}")
        else:
            result.is_verified = False
            deficit = delta_Z - available_head
            result.message = f"校验失败！可用水位差 {available_head:.4f}m < 所需落差 {delta_Z:.4f}m，差额 {deficit:.4f}m"
            steps.append(f"✗ {result.message}")
        
        if verbose:
            result.calculation_steps = steps
        
        return result
    
    @staticmethod
    def format_result(result: CalculationResult, show_steps: bool = False) -> str:
        """
        格式化计算结果
        
        Args:
            result: 计算结果对象
            show_steps: 是否显示详细计算过程
            
        Returns:
            格式化的结果字符串
        """
        lines = []
        lines.append("=" * 60)
        lines.append("                    计算结果汇总")
        lines.append("=" * 60)
        lines.append(f"理论管径: {result.diameter_theory:.4f} m")
        lines.append(f"设计管径: {result.diameter:.4f} m")
        lines.append(f"断面积: {result.area:.4f} m²")
        lines.append(f"管内流速 v: {result.velocity:.4f} m/s")
        lines.append(f"进口渐变段始端流速 v₁: {result.velocity_channel_in:.4f} m/s")
        lines.append(f"出口渐变段末端流速 v₃: {result.velocity_channel_out:.4f} m/s")
        lines.append(f"水力半径: {result.hydraulic_radius:.4f} m")
        lines.append(f"谢才系数: {result.chezy_c:.4f}")
        lines.append("-" * 60)
        lines.append("水头损失分解（附录L规范）：")
        lines.append(f"  进口渐变段落差 ΔZ1: {result.loss_inlet:.4f} m")
        lines.append(f"  管身段水头损失 ΔZ2: {result.loss_pipe:.4f} m")
        lines.append(f"    └ 沿程损失 hf: {result.loss_friction:.4f} m")
        lines.append(f"    └ 局部损失 hj: {result.loss_local:.4f} m")
        lines.append(f"  出口渐变段落差 ΔZ3: {result.loss_outlet:.4f} m")
        lines.append(f"  总水面落差 ΔZ: {result.total_head_loss:.4f} m")
        lines.append("-" * 60)
        lines.append(f"管道总长: {result.total_length:.4f} m")
        lines.append(f"可用水位差: {result.available_head_diff:.4f} m")
        lines.append(f"所需水位差: {result.required_head_diff:.4f} m")
        lines.append("-" * 60)
        lines.append(f"校验结果: {'通过' if result.is_verified else '失败'}")
        lines.append(f"详细信息: {result.message}")
        lines.append("=" * 60)
        
        if show_steps and result.calculation_steps:
            lines.append("")
            lines.append("详细计算过程：")
            lines.append("")
            lines.extend(result.calculation_steps)
        
        return "\n".join(lines)


if __name__ == "__main__":
    # 测试代码
    from siphon_models import GradientType
    
    # 创建测试参数
    params = GlobalParameters(
        Q=10.0,           # 10 m³/s
        v_guess=2.0,      # 2 m/s
        H_up=100.0,       # 上游水位 100m
        H_down=98.0,      # 下游水位 98m
        roughness_n=0.014,
        inlet_type=GradientType.QUARTER_ARC,
        outlet_type=GradientType.QUARTER_ARC,
        v_channel_in=1.0,   # 进口渐变段始端流速 v₁
        v_pipe_in=1.5,      # 进口渐变段末端流速 v₂
        v_channel_out=1.5,  # 出口渐变段始端流速 v
        v_pipe_out=1.0,     # 出口渐变段末端流速 v₃
        xi_inlet=0.15,
        xi_outlet=0.25
    )
    
    # 创建测试结构段
    segments = [
        StructureSegment(segment_type=SegmentType.INLET),
        StructureSegment(segment_type=SegmentType.STRAIGHT, length=50.0),
        StructureSegment(segment_type=SegmentType.BEND, length=10.0, radius=5.0, angle=90.0),
        StructureSegment(segment_type=SegmentType.STRAIGHT, length=100.0),
        StructureSegment(segment_type=SegmentType.BEND, length=10.0, radius=5.0, angle=90.0),
        StructureSegment(segment_type=SegmentType.STRAIGHT, length=50.0),
        StructureSegment(segment_type=SegmentType.OUTLET)
    ]
    
    # 执行计算
    result = HydraulicCore.execute_calculation(params, segments, verbose=True)
    
    # 输出结果
    print(HydraulicCore.format_result(result, show_steps=True))
