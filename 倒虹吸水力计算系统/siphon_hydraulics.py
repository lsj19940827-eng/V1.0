# -*- coding: utf-8 -*-
"""
倒虹吸水力计算软件 - 水力计算核心
依据《倒虹吸管设计计算》附录L规范
执行设计截面计算、水头损失求解及校验

水头损失分三部分：
  ΔZ1 - 进口渐变段水面落差
  ΔZ2 - 管道段总水头损失 (沿程损失 hf + 局部损失 hj)
  ΔZ3 - 出口渐变段水面落差
  总水面落差 ΔZ = ΔZ1 + ΔZ2 - ΔZ3
"""

import math
from typing import Dict, List, Optional, Tuple
from siphon_models import (
    GlobalParameters, StructureSegment, CalculationResult, SegmentType, SegmentDirection,
    PlanFeaturePoint, LongitudinalNode, SpatialMergeResult, TurnType, V2Strategy,
    is_common_type, GEOMETRY_DISPLAY_DECIMALS
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
        
        # 向上取整（用 round 消除浮点误差，避免 1.0/0.05=20.000...004 导致 ceil 多进一位）
        ratio = d_theory / step
        if abs(ratio - round(ratio)) < 1e-9:
            return round(ratio) * step
        return math.ceil(ratio) * step

    @staticmethod
    def _build_manual_turn_segment_lookups(
        plan_segments: List[StructureSegment],
        segments: List[StructureSegment],
    ) -> Tuple[Dict[int, List[StructureSegment]], Dict[int, List[StructureSegment]]]:
        """按来源索引收集带手工局部系数的平面/纵断面转弯段。"""
        plan_lookup: Dict[int, List[StructureSegment]] = {}
        long_lookup: Dict[int, List[StructureSegment]] = {}

        for seg in plan_segments or []:
            if seg.segment_type not in (SegmentType.BEND, SegmentType.FOLD):
                continue
            if seg.xi_user is None or seg.source_ip_index is None:
                continue
            plan_lookup.setdefault(seg.source_ip_index, []).append(seg)

        for seg in segments or []:
            if seg.direction != SegmentDirection.LONGITUDINAL:
                continue
            if seg.segment_type not in (SegmentType.BEND, SegmentType.FOLD):
                continue
            if seg.xi_user is None or seg.source_long_node_index is None:
                continue
            long_lookup.setdefault(seg.source_long_node_index, []).append(seg)

        return plan_lookup, long_lookup

    @staticmethod
    def _collect_manual_turn_segments(
        plan_segments: List[StructureSegment],
        segments: List[StructureSegment],
    ) -> Tuple[List[StructureSegment], List[StructureSegment]]:
        """收集所有带手工局部系数的平面/纵断面转弯段。"""
        plan_manual_segments = [
            seg for seg in (plan_segments or [])
            if seg.segment_type in (SegmentType.BEND, SegmentType.FOLD)
            and seg.xi_user is not None
        ]
        long_manual_segments = [
            seg for seg in (segments or [])
            if seg.direction == SegmentDirection.LONGITUDINAL
            and seg.segment_type in (SegmentType.BEND, SegmentType.FOLD)
            and seg.xi_user is not None
        ]
        return plan_manual_segments, long_manual_segments

    @staticmethod
    def _match_manual_turn_segment(
        lookup: Dict[int, List[StructureSegment]],
        source_index: Optional[int],
    ) -> Tuple[Optional[StructureSegment], Optional[str]]:
        """按来源索引匹配唯一手工局部系数段。"""
        if source_index is None:
            return None, None
        matches = lookup.get(source_index, [])
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, "存在多条手工局部系数，无法一一对应，仍按自动值计算。"
        return None, None

    @staticmethod
    def _segment_matches_event_geometry(
        seg: StructureSegment,
        turn_style: TurnType,
        effective_radius: float,
        theta_deg: float,
    ) -> bool:
        """用几何信息做保守兜底匹配，仅在唯一时采用。"""
        if turn_style == TurnType.ARC:
            if seg.segment_type != SegmentType.BEND or effective_radius <= 0:
                return False
            radius_tol = max(1e-3, 0.05 * max(seg.radius, effective_radius))
            angle_tol = max(0.2, 0.02 * max(abs(seg.angle), abs(theta_deg), 1.0))
            return (
                abs(seg.radius - effective_radius) <= radius_tol
                and abs(seg.angle - theta_deg) <= angle_tol
            )
        if seg.segment_type != SegmentType.FOLD:
            return False
        angle_tol = max(0.2, 0.02 * max(abs(seg.angle), abs(theta_deg), 1.0))
        return abs(seg.angle - theta_deg) <= angle_tol

    @staticmethod
    def _format_turn_segment_label(scope: str, seg: StructureSegment) -> str:
        """生成人类可读的转弯段标签。"""
        scope_text = "平面" if scope == "PLAN" else "纵断面"
        label = f"{scope_text}{seg.segment_type.value}"
        if scope == "PLAN" and seg.source_ip_index is not None:
            label += f"(IP#{seg.source_ip_index})"
        elif scope == "VERTICAL" and seg.source_long_node_index is not None:
            label += f"(节点#{seg.source_long_node_index})"
        elif seg.segment_type == SegmentType.BEND:
            label += f"(R={seg.radius:.3f}m, θ={seg.angle:.3f}°)"
        elif seg.segment_type == SegmentType.FOLD:
            label += f"(θ={seg.angle:.3f}°)"
        return label

    @staticmethod
    def _build_ignored_manual_message(scope: str, seg: StructureSegment, reason: str) -> str:
        """生成未采用手工局部系数的统一提示文案。"""
        return (
            f"{HydraulicCore._format_turn_segment_label(scope, seg)}手工局部系数 "
            f"ξ={seg.xi_user:.4f}，{reason}"
        )

    @staticmethod
    def _build_ignored_manual_entry(scope: str, seg: StructureSegment, reason: str):
        """生成未采用手工值的去重键和值文本。"""
        key = (
            scope,
            seg.segment_type.value,
            seg.source_ip_index if scope == "PLAN" else seg.source_long_node_index,
            round(seg.radius, 6),
            round(seg.angle, 6),
            round(seg.xi_user or 0.0, 6),
            reason,
        )
        return key, HydraulicCore._build_ignored_manual_message(scope, seg, reason)

    @staticmethod
    def _get_event_source_indices(ev, scope: str) -> List[int]:
        """读取事件关联的全部来源索引。"""
        if scope == "PLAN":
            if getattr(ev, "plan_source_ip_indices", None):
                return list(ev.plan_source_ip_indices)
            if getattr(ev, "plan_source_ip_index", None) is not None:
                return [ev.plan_source_ip_index]
            return []
        if getattr(ev, "long_source_node_indices", None):
            return list(ev.long_source_node_indices)
        if getattr(ev, "long_source_node_index", None) is not None:
            return [ev.long_source_node_index]
        return []

    @staticmethod
    def _collect_segments_for_source_indices(
        lookup: Dict[int, List[StructureSegment]],
        source_indices: List[int],
    ) -> List[StructureSegment]:
        """按多个来源索引收集手工局部系数段。"""
        collected: List[StructureSegment] = []
        seen = set()
        for source_index in source_indices:
            for seg in lookup.get(source_index, []):
                seg_key = id(seg)
                if seg_key in seen:
                    continue
                seen.add(seg_key)
                collected.append(seg)
        return collected

    @staticmethod
    def _matching_turn_candidates(
        fallback_segments: List[StructureSegment],
        turn_style: TurnType,
    ) -> List[StructureSegment]:
        """筛出与事件类型一致的手工转弯段候选。"""
        return [
            seg for seg in fallback_segments
            if (
                (turn_style == TurnType.ARC and seg.segment_type == SegmentType.BEND)
                or (turn_style == TurnType.FOLD and seg.segment_type == SegmentType.FOLD)
            )
        ]

    @staticmethod
    def _get_segment_source_index(scope: str, seg: StructureSegment) -> Optional[int]:
        """读取指定作用域下结构段的来源索引。"""
        if scope == "PLAN":
            return seg.source_ip_index
        return seg.source_long_node_index

    @staticmethod
    def _collect_available_legacy_turn_candidates(
        scope: str,
        fallback_segments: List[StructureSegment],
        turn_style: TurnType,
        adopted_manual_ids: set,
    ) -> List[StructureSegment]:
        """收集仍可参与旧项目兼容匹配的手工转弯段。"""
        candidates = []
        for seg in HydraulicCore._matching_turn_candidates(fallback_segments, turn_style):
            if HydraulicCore._get_segment_source_index(scope, seg) is not None:
                continue
            if id(seg) in adopted_manual_ids:
                continue
            candidates.append(seg)
        return candidates

    @staticmethod
    def _resolve_event_manual_override(
        ev,
        scope: str,
        lookup: Dict[int, List[StructureSegment]],
        fallback_segments: List[StructureSegment],
        turn_style: TurnType,
        effective_radius: float,
        theta_deg: float,
        adopted_manual_ids: set,
    ) -> Tuple[Optional[StructureSegment], List[StructureSegment], Optional[str]]:
        """解析单个 PLAN/VERTICAL 事件是否可采用手工局部系数。"""
        source_indices = HydraulicCore._get_event_source_indices(ev, scope)
        if len(source_indices) > 1:
            return (
                None,
                HydraulicCore._collect_segments_for_source_indices(lookup, source_indices),
                "因同一空间弯道覆盖多个原始转弯段，无法一一对应，仍按自动值计算。",
            )

        source_index = source_indices[0] if source_indices else None
        if source_index is not None:
            matched_seg, reason = HydraulicCore._match_manual_turn_segment(
                lookup, source_index
            )
            if matched_seg is not None:
                if id(matched_seg) in adopted_manual_ids:
                    return None, [], None
                return matched_seg, [], None
            if reason is not None:
                return (
                    None,
                    HydraulicCore._collect_segments_for_source_indices(
                        lookup, [source_index]
                    ),
                    reason,
                )

        legacy_candidates = HydraulicCore._collect_available_legacy_turn_candidates(
            scope,
            fallback_segments,
            turn_style,
            adopted_manual_ids,
        )
        if not legacy_candidates:
            return None, [], None

        geometry_matches = [
            seg for seg in legacy_candidates
            if HydraulicCore._segment_matches_event_geometry(
                seg, turn_style, effective_radius, theta_deg
            )
        ]
        if len(geometry_matches) == 1:
            return geometry_matches[0], [], None
        if len(geometry_matches) > 1 or len(legacy_candidates) > 1:
            return (
                None,
                legacy_candidates,
                "存在多条手工局部系数，无法一一对应，仍按自动值计算。",
            )
        return None, [], None

    @staticmethod
    def _collect_composite_manual_segments(
        ev,
        scope: str,
        lookup: Dict[int, List[StructureSegment]],
        fallback_segments: List[StructureSegment],
        turn_style: TurnType,
        effective_radius: float,
        theta_deg: float,
    ) -> List[StructureSegment]:
        """收集 COMPOSITE 事件中被忽略的手工局部系数段。"""
        source_indices = HydraulicCore._get_event_source_indices(ev, scope)
        if source_indices:
            return HydraulicCore._collect_segments_for_source_indices(
                lookup, source_indices
            )
        # COMPOSITE 事件必须以明确来源为准，不做全局兜底猜测，避免误报别处手工值。
        _ = (fallback_segments, turn_style, effective_radius, theta_deg)
        return []

    @staticmethod
    def _calculate_turn_auto_xi(
        segment_type: SegmentType,
        radius: float,
        angle_deg: float,
        diameter: float,
    ) -> Tuple[Optional[float], str]:
        """按弯管/折管类型计算自动局部系数及明细文本。"""
        if segment_type == SegmentType.BEND and radius > 0 and angle_deg > 0:
            return CoefficientService.calculate_bend_coeff(
                radius, diameter, angle_deg, verbose=True
            )
        if segment_type == SegmentType.FOLD and angle_deg > 0:
            return CoefficientService.calculate_fold_coeff(
                angle_deg, verbose=True
            )
        return None, ""

    @staticmethod
    def _append_manual_adoption_step(
        steps: List[str],
        auto_xi: float,
        adopted_xi: float,
    ) -> None:
        """在详细过程里追加“最终采用值”说明。"""
        steps.append(
            f"    本次采用手工局部系数 ξ={adopted_xi:.4f}，覆盖自动值 ξ={auto_xi:.4f}"
        )
    
    @staticmethod
    def execute_calculation(global_params: GlobalParameters,
                           segments: List[StructureSegment],
                           diameter_override: Optional[float] = None,
                           verbose: bool = False,
                           plan_segments: List[StructureSegment] = None,
                           plan_total_length: float = 0.0,
                           plan_feature_points: List[PlanFeaturePoint] = None,
                           longitudinal_nodes: List[LongitudinalNode] = None,
                           increase_percent: Optional[float] = None,
                           v1_inc: Optional[float] = None,
                           v2_inc: Optional[float] = None,
                           v3_inc: Optional[float] = None,
                           ) -> CalculationResult:
        """
        执行核心计算（依据附录L规范）
        
        支持三种计算模式：
        A. 三维空间合并模式（优先）：当同时有 plan_feature_points 和 longitudinal_nodes 时
           使用 SpatialMerger 计算空间长度，并按 bend_events 逐事件查表空间弯道局损
        B. 平面+纵断面独立模式（退化）：分别计算平面弯道和纵向弯道损失
        C. 单数据源模式（退化）：仅有平面或仅有纵断面时的简化计算
        
        Args:
            global_params: 全局参数
            segments: 结构段列表（包含通用构件和管身段）
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
        num_pipes = getattr(global_params, 'num_pipes', 1) or 1
        Q_single = Q / num_pipes  # 单管流量（并联时每管分摊）
        v_guess = global_params.v_guess
        n = global_params.roughness_n
        g = HydraulicCore.GRAVITY
        v2_strategy = global_params.v2_strategy
        
        # 进出口渐变段流速（v_2 可能在步骤1之后被策略覆盖）
        v_1 = global_params.v_channel_in if global_params.v_channel_in > 0 else 0.0   # 进口渐变段始端流速 v₁
        v_2 = global_params.v_pipe_in if global_params.v_pipe_in > 0 else 0.0         # 进口渐变段末端流速 v₂
        v_out = global_params.v_channel_out if global_params.v_channel_out > 0 else 0.0  # 出口渐变段始端流速 v
        v_3 = global_params.v_pipe_out if global_params.v_pipe_out > 0 else 0.0       # 出口渐变段末端流速 v₃
        result.velocity_channel_in = v_1
        result.velocity_channel_out = v_3
        
        # ========== 步骤1：几何设计与流速计算 ==========
        steps.append("=" * 50)
        steps.append("步骤1：几何设计与流速计算")
        steps.append("=" * 50)
        
        if num_pipes > 1:
            steps.append(f"管道根数 N = {num_pipes}，总流量 Q = {Q:.4f} m³/s")
            steps.append(f"单管流量 Q_单 = Q / N = {Q:.4f} / {num_pipes} = {Q_single:.4f} m³/s")
            steps.append("")
        
        # 管道断面积 ω = Q_single / v_guess
        omega = Q_single / v_guess
        if num_pipes > 1:
            steps.append(f"单管断面积 ω = Q_单 / v_guess = {Q_single:.4f} / {v_guess:.4f} = {omega:.4f} m²")
        else:
            steps.append(f"管道断面积 ω = Q / v_guess = {Q:.4f} / {v_guess:.4f} = {omega:.4f} m²")
        
        # 理论直径 D = sqrt(4ω / π)
        D_theory = math.sqrt(4 * omega / math.pi)
        steps.append(f"理论直径 D = √(4ω/π) = √(4×{omega:.4f}/π) = {D_theory:.4f} m")
        
        # 管径取整或使用用户指定值
        if diameter_override is not None:
            D = diameter_override
            if D < D_theory:
                steps.append(f"⚠ 警告: 用户指定管径 D={D:.4f}m 小于理论最小值 D_theory={D_theory:.4f}m，"
                             f"管内流速将超过拟定流速，结果仅供参考！")
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
        
        # 实际流速 v = Q_single/A = 4Q_single/(πD²)
        v = Q_single / A_actual
        result.velocity = v
        if num_pipes > 1:
            steps.append(f"单管实际流速 v = Q_单/A = {Q_single:.4f}/{A_actual:.4f} = {v:.4f} m/s")
        else:
            steps.append(f"实际流速 v = Q/A = {Q:.4f}/{A_actual:.4f} = {v:.4f} m/s")
        
        # 水力半径 R_h = D / 4 (圆管满流)
        R_h = D / 4
        result.hydraulic_radius = R_h
        steps.append(f"水力半径 R_h = D/4 = {D:.4f}/4 = {R_h:.4f} m")
        
        # ===== 根据策略确定 v₂ =====
        if v2_strategy == V2Strategy.AUTO_PIPE:
            v_2 = v  # 渐变段末端即管道入口，v₂ = 管道流速
            steps.append("")
            steps.append(f"v₂ 策略: {v2_strategy.value}")
            steps.append(f"  进口渐变段末端流速 v₂ = 管道流速 v = {v_2:.4f} m/s")
        elif v2_strategy == V2Strategy.V1_PLUS_02:
            v_2 = v_1 + 0.2
            steps.append("")
            steps.append(f"v₂ 策略: {v2_strategy.value}")
            steps.append(f"  进口渐变段末端流速 v₂ = v₁ + 0.2 = {v_1:.4f} + 0.2 = {v_2:.4f} m/s")
        else:
            # SECTION_CALC 或 MANUAL：使用已传入的 v_2 值
            steps.append("")
            steps.append(f"v₂ 策略: {v2_strategy.value}")
            steps.append(f"  进口渐变段末端流速 v₂ = {v_2:.4f} m/s")
        
        # 安全兜底：若 v₂ ≤ v₁，自动回退到管道流速
        if v_2 <= v_1 and v_1 > 0:
            v_2_old = v_2
            v_2 = v
            steps.append(f"  ⚠ 检测到 v₂({v_2_old:.4f}) ≤ v₁({v_1:.4f})，自动回退: v₂ = 管道流速 = {v_2:.4f} m/s")
        
        # 存储实际使用的 v₂
        result.velocity_pipe_in = v_2
        
        # ===== 出口渐变段始端流速 v_out 使用实际管道流速 =====
        v_out = v  # 出口渐变段始端流速 = 管道实际流速（而非拟定流速）
        result.velocity_outlet_start = v_out
        steps.append("")
        steps.append(f"  出口渐变段始端流速 v = 管道实际流速 = {v_out:.4f} m/s")
        
        # ========== 步骤2：阻力参数初始化 ==========
        steps.append("")
        steps.append("=" * 50)
        steps.append("步骤2：阻力参数初始化")
        steps.append("=" * 50)
        
        # 谢才系数 C = (1/n) * R^(1/6) (依据 L.1.4)
        C = (1 / n) * (R_h ** (1/6))
        result.chezy_c = C
        steps.append(f"谢才系数 C = (1/n) × R_h^(1/6) = (1/{n:.4f}) × {R_h:.4f}^(1/6) = {C:.4f}")
        
        # 更新局部阻力系数
        steps.append("")
        steps.append("局部阻力系数计算：")
        
        xi_sum_middle = 0.0  # 管道局部损失系数和（不含渐变段 ξ1/ξ2，含进出水口构件）
        L_friction = 0.0     # 沿程损失计算长度
        length_source = ""
        
        # ===== 判断计算模式 =====
        has_plan_points = len(plan_feature_points) >= 2
        has_long_nodes = len(longitudinal_nodes) >= 2
        has_plan_length = (plan_total_length > 0) or (plan_segments is not None and len(plan_segments) > 0)
        has_spatial_data = (has_plan_points or has_long_nodes)
        plan_manual_lookup, long_manual_lookup = HydraulicCore._build_manual_turn_segment_lookups(
            plan_segments, segments
        )
        plan_manual_segments, long_manual_segments = HydraulicCore._collect_manual_turn_segments(
            plan_segments, segments
        )
        adopted_manual_ids = set()
        ignored_manual_overrides: List[str] = []
        ignored_manual_seen = set()
        ignored_manual_segment_ids = set()
        
        if has_spatial_data:
            # ===== 模式A：三维空间合并计算 =====
            steps.append("")
            steps.append("【三维空间合并计算】")
            
            spatial_result = SpatialMerger.merge_and_compute(
                plan_feature_points, longitudinal_nodes,
                pipe_diameter=D, verbose=verbose
            )
            
            if has_plan_points and has_long_nodes:
                result.data_mode = "平面+纵断面（空间合并）"
                result.data_note = "已同时检测到平面与纵断面数据"
            elif has_plan_points:
                result.data_mode = "仅平面（空间合并退化）"
                result.data_note = "未导入纵断面，按平面估算（β=0）"
            else:
                result.data_mode = "仅纵断面（空间合并退化）"
                result.data_note = "未检测到平面数据，按纵断面估算（α=常数）"
            
            # 添加空间合并的详细步骤
            if verbose:
                steps.extend(spatial_result.computation_steps)
            
            # 空间弯道损失系数
            xi_spatial_bends = 0.0
            steps.append("")
            steps.append("【空间弯道损失系数查表】")
            counted_events = [
                ev for ev in spatial_result.bend_events
                if math.degrees(ev.theta_event) > SpatialMerger.TURN_ANGLE_THRESH
            ]
            for ev in counted_events:
                theta_deg = math.degrees(ev.theta_event)
                if ev.turn_style == TurnType.ARC and ev.R_eff > 0:
                    xi_auto, auto_steps = CoefficientService.calculate_bend_coeff(
                        ev.R_eff, D, theta_deg, verbose=True
                    )
                    adopted_xi = xi_auto
                    adopted_seg = None
                    ignored_records = []
                    if ev.event_type == 'PLAN':
                        adopted_seg, ignored_segments, match_reason = HydraulicCore._resolve_event_manual_override(
                            ev,
                            'PLAN',
                            plan_manual_lookup,
                            plan_manual_segments,
                            ev.turn_style,
                            ev.R_h if ev.R_h > 0 else ev.R_eff,
                            theta_deg,
                            adopted_manual_ids,
                        )
                        if adopted_seg is not None and adopted_seg.xi_user is not None:
                            adopted_xi = adopted_seg.xi_user
                            adopted_manual_ids.add(id(adopted_seg))
                        elif match_reason:
                            ignored_records.extend(
                                ('PLAN', seg, match_reason) for seg in ignored_segments
                            )
                    elif ev.event_type == 'VERTICAL':
                        adopted_seg, ignored_segments, match_reason = HydraulicCore._resolve_event_manual_override(
                            ev,
                            'VERTICAL',
                            long_manual_lookup,
                            long_manual_segments,
                            ev.turn_style,
                            ev.R_v if ev.R_v > 0 else ev.R_eff,
                            theta_deg,
                            adopted_manual_ids,
                        )
                        if adopted_seg is not None and adopted_seg.xi_user is not None:
                            adopted_xi = adopted_seg.xi_user
                            adopted_manual_ids.add(id(adopted_seg))
                        elif match_reason:
                            ignored_records.extend(
                                ('VERTICAL', seg, match_reason) for seg in ignored_segments
                            )
                    else:
                        plan_segs = HydraulicCore._collect_composite_manual_segments(
                            ev,
                            'PLAN',
                            plan_manual_lookup,
                            plan_manual_segments,
                            ev.turn_style,
                            ev.R_h if ev.R_h > 0 else ev.R_eff,
                            theta_deg,
                        )
                        long_segs = HydraulicCore._collect_composite_manual_segments(
                            ev,
                            'VERTICAL',
                            long_manual_lookup,
                            long_manual_segments,
                            ev.turn_style,
                            ev.R_v if ev.R_v > 0 else ev.R_eff,
                            theta_deg,
                        )
                        for plan_seg in plan_segs:
                            ignored_records.append(
                                (
                                    'PLAN',
                                    plan_seg,
                                    "因 3D 复合弯道无法一一对应，仍按自动值计算。",
                                )
                            )
                        for long_seg in long_segs:
                            ignored_records.append(
                                (
                                    'VERTICAL',
                                    long_seg,
                                    "因 3D 复合弯道无法一一对应，仍按自动值计算。",
                                )
                            )
                    xi_spatial_bends += adopted_xi
                    steps.append(
                        f"  s=[{ev.s_a:.{GEOMETRY_DISPLAY_DECIMALS}f},{ev.s_b:.{GEOMETRY_DISPLAY_DECIMALS}f}] 空间弯管: "
                        f"R_eff={ev.R_eff:.{GEOMETRY_DISPLAY_DECIMALS}f}m, "
                        f"θ_3D={theta_deg:.{GEOMETRY_DISPLAY_DECIMALS}f}°"
                    )
                    steps.append(f"    {auto_steps.replace(chr(10), chr(10) + '    ')}")
                    if adopted_seg is not None and adopted_seg.xi_user is not None:
                        HydraulicCore._append_manual_adoption_step(
                            steps, xi_auto, adopted_xi
                        )
                    for ignored_scope, ignored_seg, ignored_reason in ignored_records:
                        ignored_key, message = HydraulicCore._build_ignored_manual_entry(
                            ignored_scope, ignored_seg, ignored_reason
                        )
                        steps.append(f"    {message}")
                        if ignored_key not in ignored_manual_seen:
                            ignored_manual_seen.add(ignored_key)
                            ignored_manual_segment_ids.add(id(ignored_seg))
                            ignored_manual_overrides.append(message)
                elif ev.turn_style == TurnType.FOLD:
                    xi_auto, auto_steps = CoefficientService.calculate_fold_coeff(
                        theta_deg, verbose=True
                    )
                    adopted_xi = xi_auto
                    adopted_seg = None
                    ignored_records = []
                    if ev.event_type == 'PLAN':
                        adopted_seg, ignored_segments, match_reason = HydraulicCore._resolve_event_manual_override(
                            ev,
                            'PLAN',
                            plan_manual_lookup,
                            plan_manual_segments,
                            ev.turn_style,
                            ev.R_h if ev.R_h > 0 else ev.R_eff,
                            theta_deg,
                            adopted_manual_ids,
                        )
                        if adopted_seg is not None and adopted_seg.xi_user is not None:
                            adopted_xi = adopted_seg.xi_user
                            adopted_manual_ids.add(id(adopted_seg))
                        elif match_reason:
                            ignored_records.extend(
                                ('PLAN', seg, match_reason) for seg in ignored_segments
                            )
                    elif ev.event_type == 'VERTICAL':
                        adopted_seg, ignored_segments, match_reason = HydraulicCore._resolve_event_manual_override(
                            ev,
                            'VERTICAL',
                            long_manual_lookup,
                            long_manual_segments,
                            ev.turn_style,
                            ev.R_v if ev.R_v > 0 else ev.R_eff,
                            theta_deg,
                            adopted_manual_ids,
                        )
                        if adopted_seg is not None and adopted_seg.xi_user is not None:
                            adopted_xi = adopted_seg.xi_user
                            adopted_manual_ids.add(id(adopted_seg))
                        elif match_reason:
                            ignored_records.extend(
                                ('VERTICAL', seg, match_reason) for seg in ignored_segments
                            )
                    else:
                        plan_segs = HydraulicCore._collect_composite_manual_segments(
                            ev,
                            'PLAN',
                            plan_manual_lookup,
                            plan_manual_segments,
                            ev.turn_style,
                            ev.R_h if ev.R_h > 0 else ev.R_eff,
                            theta_deg,
                        )
                        long_segs = HydraulicCore._collect_composite_manual_segments(
                            ev,
                            'VERTICAL',
                            long_manual_lookup,
                            long_manual_segments,
                            ev.turn_style,
                            ev.R_v if ev.R_v > 0 else ev.R_eff,
                            theta_deg,
                        )
                        for plan_seg in plan_segs:
                            ignored_records.append(
                                (
                                    'PLAN',
                                    plan_seg,
                                    "因 3D 复合弯道无法一一对应，仍按自动值计算。",
                                )
                            )
                        for long_seg in long_segs:
                            ignored_records.append(
                                (
                                    'VERTICAL',
                                    long_seg,
                                    "因 3D 复合弯道无法一一对应，仍按自动值计算。",
                                )
                            )
                    xi_spatial_bends += adopted_xi
                    steps.append(
                        f"  s={ev.s_a:.{GEOMETRY_DISPLAY_DECIMALS}f}m 空间折管: "
                        f"θ_3D={theta_deg:.{GEOMETRY_DISPLAY_DECIMALS}f}°"
                    )
                    steps.append(f"    {auto_steps.replace(chr(10), chr(10) + '    ')}")
                    if adopted_seg is not None and adopted_seg.xi_user is not None:
                        HydraulicCore._append_manual_adoption_step(
                            steps, xi_auto, adopted_xi
                        )
                    for ignored_scope, ignored_seg, ignored_reason in ignored_records:
                        ignored_key, message = HydraulicCore._build_ignored_manual_entry(
                            ignored_scope, ignored_seg, ignored_reason
                        )
                        steps.append(f"    {message}")
                        if ignored_key not in ignored_manual_seen:
                            ignored_manual_seen.add(ignored_key)
                            ignored_manual_segment_ids.add(id(ignored_seg))
                            ignored_manual_overrides.append(message)

            xi_sum_middle += xi_spatial_bends
            steps.append(f"  空间弯道损失系数合计 Σξ_空间弯 = {xi_spatial_bends:.4f}")

            # 空间长度
            L_friction = spatial_result.total_spatial_length
            length_source = "三维空间合并计算"

            remaining_legacy_segments = [
                ('PLAN', seg)
                for seg in plan_manual_segments
                if seg.xi_user is not None
                and seg.source_ip_index is None
                and id(seg) not in adopted_manual_ids
            ] + [
                ('VERTICAL', seg)
                for seg in long_manual_segments
                if seg.xi_user is not None
                and seg.source_long_node_index is None
                and id(seg) not in adopted_manual_ids
            ]
            for scope, seg in remaining_legacy_segments:
                if id(seg) in ignored_manual_segment_ids:
                    continue
                ignored_key, message = HydraulicCore._build_ignored_manual_entry(
                    scope,
                    seg,
                    "缺少来源索引且几何无法唯一匹配，仍按自动值计算。",
                )
                if ignored_key not in ignored_manual_seen:
                    ignored_manual_seen.add(ignored_key)
                    ignored_manual_overrides.append(message)
        else:
            # ===== 模式B：旧模式（向后兼容） =====
            steps.append("")
            steps.append("【传统模式（无空间合并数据）】")
            
            total_length = sum(
                seg.spatial_length
                for seg in segments
                if seg.direction == SegmentDirection.LONGITUDINAL
            )
            
            result.data_mode = "传统模式（无空间合并数据）"
            if has_plan_length:
                result.data_note = "未导入纵断面，沿程长度取平面总长度"
            else:
                result.data_note = "平面/纵断面数据不足，结果仅供参考"
            
            # 平面弯道损失
            xi_plan_bends = 0.0
            if plan_segments:
                steps.append("")
                steps.append("平面段（水平转弯）：")
                for j, pseg in enumerate(plan_segments):
                    xi_auto, auto_steps = HydraulicCore._calculate_turn_auto_xi(
                        pseg.segment_type, pseg.radius, pseg.angle, D
                    )
                    if xi_auto is None:
                        continue
                    pseg.xi_calc = xi_auto
                    adopted_xi = pseg.xi_user if pseg.xi_user is not None else xi_auto
                    xi_plan_bends += adopted_xi
                    if pseg.segment_type == SegmentType.BEND:
                        steps.append(
                            f"  平面弯管{j}: R={pseg.radius:.2f}m, θ={pseg.angle:.1f}°"
                        )
                    else:
                        steps.append(f"  平面折管{j}: θ={pseg.angle:.1f}°")
                    steps.append(f"    {auto_steps.replace(chr(10), chr(10) + '    ')}")
                    if pseg.xi_user is not None:
                        HydraulicCore._append_manual_adoption_step(
                            steps, xi_auto, adopted_xi
                        )
                xi_sum_middle += xi_plan_bends

            xi_long_turns = 0.0
            long_turn_segments = [
                seg for seg in segments
                if seg.direction == SegmentDirection.LONGITUDINAL
                and seg.segment_type in (SegmentType.BEND, SegmentType.FOLD)
            ]
            if long_turn_segments:
                steps.append("")
                steps.append("纵断面段（竖向转弯）：")
                for j, seg in enumerate(long_turn_segments):
                    xi_auto, auto_steps = HydraulicCore._calculate_turn_auto_xi(
                        seg.segment_type, seg.radius, seg.angle, D
                    )
                    if xi_auto is None:
                        continue
                    seg.xi_calc = xi_auto
                    adopted_xi = seg.xi_user if seg.xi_user is not None else xi_auto
                    xi_long_turns += adopted_xi
                    if seg.segment_type == SegmentType.BEND:
                        steps.append(
                            f"  纵断面弯管{j}: R={seg.radius:.2f}m, θ={seg.angle:.1f}°"
                        )
                    else:
                        steps.append(f"  纵断面折管{j}: θ={seg.angle:.1f}°")
                    steps.append(f"    {auto_steps.replace(chr(10), chr(10) + '    ')}")
                    if seg.xi_user is not None:
                        HydraulicCore._append_manual_adoption_step(
                            steps, xi_auto, adopted_xi
                        )
                xi_sum_middle += xi_long_turns
            
            # 确定长度
            if plan_total_length > 0:
                L_friction = plan_total_length
                length_source = "平面总长度(MC出-MC进)"
            elif total_length > 0:
                L_friction = total_length
                length_source = "纵断面空间长度之和"
            else:
                L_friction = total_length
                length_source = "纵断面段水平长度之和"
        
        # ===== 2.5 通用构件（进水口/出水口/拦污栅/闸门槽等）：计入 ΔZ2 的局部损失 =====
        steps.append("")
        steps.append("【通用构件（计入 ΔZ2 的局部损失）】")
        for i, seg in enumerate(segments):
            # 使用 direction==COMMON 统一判断通用构件（兼容按类型判断）
            if seg.direction == SegmentDirection.COMMON or is_common_type(seg.segment_type):
                xi = seg.get_xi()
                xi_sum_middle += xi
                type_name = seg.segment_type.value
                component_note = ""
                if seg.segment_type == SegmentType.INLET:
                    component_note = "（进水口构件局部损失，计入ΔZ2；不替代 ξ_1）"
                elif seg.segment_type == SegmentType.OUTLET:
                    component_note = "（出水口构件局部损失，计入ΔZ2；不替代 ξ_2）"
                if seg.length > 0:
                    L_friction += seg.length
                    steps.append(
                        f"  {type_name}{i}{component_note}: L={seg.length:.3f}m, ξ={xi:.4f}"
                    )
                else:
                    steps.append(f"  {type_name}{i}{component_note}: ξ={xi:.4f}")
        
        result.total_length = L_friction
        result.xi_sum_middle = xi_sum_middle
        steps.append("")
        steps.append(f"沿程损失计算采用: {length_source} = {L_friction:.4f} m")
        steps.append(f"管道局部损失系数和 Σξ_local = {xi_sum_middle:.4f}")
        
        # 渐变段系数
        xi_1 = global_params.xi_inlet   # 进口渐变段系数
        xi_2 = global_params.xi_outlet  # 出口渐变段系数
        result.xi_inlet = xi_1
        result.xi_outlet = xi_2
        steps.append(f"进口渐变段系数 ξ_1 = {xi_1:.4f} (用于 ΔZ1，表 L.1.2)")
        steps.append(f"出口渐变段系数 ξ_2 = {xi_2:.4f} (用于 ΔZ3，表 L.1.4-5 或 L.1.3)")
        
        # ========== 步骤3：水头损失求解 ==========
        steps.append("")
        steps.append("=" * 50)
        steps.append("步骤3：水头损失求解")
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
        
        # ---------- 3.2 管道段总水头损失 ΔZ2 (公式 L.1.4-7) ----------
        steps.append("【3.2 管道段总水头损失 ΔZ2】")
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
        
        # 管道局部损失 hj = Σξ_local × v² / (2g)
        h_j = xi_sum_middle * v ** 2 / (2 * g)
        result.loss_local = h_j
        steps.append("  管道局部损失 hj = Σξ_local × v² / (2g)")
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

        result.ignored_manual_overrides = ignored_manual_overrides

        result.num_pipes = num_pipes

        # ========== 加大流量工况（一次完成，与其他模块保持一致）==========
        if increase_percent is not None and increase_percent > 0:
            result.increase_percent = increase_percent
            Q_inc_total = global_params.Q * (1 + increase_percent / 100.0)
            result.Q_increased = Q_inc_total
            Q_single_inc = Q_inc_total / num_pipes
            v_inc = Q_single_inc / A_actual
            result.velocity_increased = v_inc
            
            # 使用用户输入的加大工况流速（若未提供则使用设计值）
            v_1_inc_use = v1_inc if v1_inc is not None and v1_inc > 0 else v_1
            v_3_inc_use = v3_inc if v3_inc is not None and v3_inc > 0 else v_3
            
            # v_2_inc: 根据策略确定进口渐变段末端流速
            if v2_strategy == V2Strategy.AUTO_PIPE:
                v_2_inc_use = v_inc  # 加大管道流速
            elif v2_strategy == V2Strategy.V1_PLUS_02:
                v_2_inc_use = v_1_inc_use + 0.2  # v₁加大 + 0.2
            else:  # SECTION_CALC / MANUAL
                v_2_inc_use = v2_inc if v2_inc is not None and v2_inc > 0 else v_2
            
            v_out_inc = v_inc  # 出口渐变段始端 = 加大管道流速
            
            # 计算水头损失（使用加大工况流速）
            dZ1_inc = (1 + xi_1) * (v_2_inc_use ** 2 - v_1_inc_use ** 2) / (2 * g)
            h_f_inc = (v_inc ** 2 * L_friction) / (C ** 2 * R_h)
            h_j_inc = xi_sum_middle * v_inc ** 2 / (2 * g)
            dZ2_inc = h_f_inc + h_j_inc
            dZ3_inc = (1 - xi_2) * (v_out_inc ** 2 - v_3_inc_use ** 2) / (2 * g)
            
            # 记录结果
            result.v1_inc_used = v_1_inc_use
            result.v2_inc_used = v_2_inc_use
            result.v3_inc_used = v_3_inc_use
            result.loss_inlet_inc = dZ1_inc
            result.loss_pipe_inc = dZ2_inc
            result.loss_outlet_inc = dZ3_inc
            result.total_head_loss_inc = dZ1_inc + dZ2_inc - dZ3_inc

            if verbose:
                steps.append("")
                steps.append("=" * 50)
                steps.append("步骤4：加大流量工况水头损失求解")
                steps.append("=" * 50)
                steps.append(
                    f"Q加大 = Q × (1 + increase_percent/100) = {global_params.Q:.4f} × "
                    f"(1 + {increase_percent:.4f}/100) = {Q_inc_total:.4f} m³/s"
                )
                if num_pipes > 1:
                    steps.append(
                        f"单管加大流量 Q单管加大 = Q加大 / N = {Q_inc_total:.4f} / {num_pipes} = "
                        f"{Q_single_inc:.4f} m³/s"
                    )
                steps.append(f"加大流速 v加大 = Q单管加大 / A = {Q_single_inc:.4f} / {A_actual:.4f} = {v_inc:.4f} m/s")
                steps.append(f"v₁加大 = {v_1_inc_use:.4f} m/s")
                steps.append(f"v₂加大 = {v_2_inc_use:.4f} m/s")
                steps.append(f"v₃加大 = {v_3_inc_use:.4f} m/s")
                steps.append("")
                steps.append("【4.1 进口渐变段水面落差 ΔZ1加大】")
                steps.append("  公式 L.1.2-2: ΔZ1加大 = (1 + ξ1) × (v₂加大² - v₁加大²) / (2g)")
                steps.append(
                    f"  ΔZ1加大 = (1 + {xi_1:.4f}) × ({v_2_inc_use:.4f}² - {v_1_inc_use:.4f}²) / (2×{g})"
                )
                steps.append(
                    f"          = {1 + xi_1:.4f} × ({v_2_inc_use ** 2:.4f} - {v_1_inc_use ** 2:.4f}) / {2 * g:.2f}"
                )
                steps.append(f"          = {dZ1_inc:.4f} m")
                steps.append("")
                steps.append("【4.2 管道段总水头损失 ΔZ2加大】")
                steps.append("  公式 L.1.4-7: ΔZ2加大 = hf加大 + hj加大")
                steps.append("  沿程损失 hf加大 = L × v加大² / (C² × R_h)")
                steps.append(
                    f"           = {L_friction:.4f} × {v_inc:.4f}² / ({C:.4f}² × {R_h:.4f})"
                )
                steps.append(f"           = {h_f_inc:.4f} m")
                steps.append("  管道局部损失 hj加大 = Σξ_local × v加大² / (2g)")
                steps.append(
                    f"             = {xi_sum_middle:.4f} × {v_inc:.4f}² / (2×{g})"
                )
                steps.append(f"             = {h_j_inc:.4f} m")
                steps.append(
                    f"  ΔZ2加大 = hf加大 + hj加大 = {h_f_inc:.4f} + {h_j_inc:.4f} = {dZ2_inc:.4f} m"
                )
                steps.append("")
                steps.append("【4.3 出口渐变段水面落差 ΔZ3加大】")
                steps.append("  公式 L.1.3-2: ΔZ3加大 = (1 - ξ2) × (v加大² - v₃加大²) / (2g)")
                steps.append(
                    f"  ΔZ3加大 = (1 - {xi_2:.4f}) × ({v_out_inc:.4f}² - {v_3_inc_use:.4f}²) / (2×{g})"
                )
                steps.append(
                    f"          = {1 - xi_2:.4f} × ({v_out_inc ** 2:.4f} - {v_3_inc_use ** 2:.4f}) / {2 * g:.2f}"
                )
                steps.append(f"          = {dZ3_inc:.4f} m")
                steps.append("")
                steps.append("【4.4 总水面落差 ΔZ加大】")
                steps.append("  公式 L.1.6: ΔZ加大 = ΔZ1加大 + ΔZ2加大 - ΔZ3加大")
                steps.append(f"  ΔZ加大 = {dZ1_inc:.4f} + {dZ2_inc:.4f} - {dZ3_inc:.4f}")
                steps.append(f"         = {result.total_head_loss_inc:.4f} m")

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
        if result.num_pipes > 1:
            lines.append(f"管道根数 (并联): {result.num_pipes} 根")
            Q_total = result.velocity * result.area * result.num_pipes
            lines.append(f"总设计流量 Q: {Q_total:.4f} m³/s")
        lines.append(f"断面积: {result.area:.4f} m²")
        if result.num_pipes > 1:
            lines.append(f"单管流速 v: {result.velocity:.4f} m/s")
        else:
            lines.append(f"管内流速 v: {result.velocity:.4f} m/s")
        lines.append(f"进口渐变段始端流速 v₁: {result.velocity_channel_in:.4f} m/s")
        lines.append(f"出口渐变段末端流速 v₃: {result.velocity_channel_out:.4f} m/s")
        lines.append(f"水力半径: {result.hydraulic_radius:.4f} m")
        lines.append(f"谢才系数: {result.chezy_c:.4f}")
        if result.data_mode:
            lines.append(f"数据模式: {result.data_mode}")
        if result.data_note:
            lines.append(f"说明: {result.data_note}")
        lines.append("-" * 60)
        lines.append("水头损失分解（附录L规范）：")
        lines.append(f"  进口渐变段落差 ΔZ1: {result.loss_inlet:.4f} m")
        lines.append(f"  管道段水头损失 ΔZ2: {result.loss_pipe:.4f} m")
        lines.append(f"    └ 沿程损失 hf: {result.loss_friction:.4f} m")
        lines.append(f"    └ 局部损失 hj: {result.loss_local:.4f} m")
        lines.append(f"  出口渐变段落差 ΔZ3: {result.loss_outlet:.4f} m")
        lines.append(f"  总水面落差 ΔZ: {result.total_head_loss:.4f} m")
        lines.append("-" * 60)
        lines.append(f"管道总长: {result.total_length:.4f} m")
        lines.append("=" * 60)
        if result.increase_percent > 0:
            lines.append("")
            lines.append(f"【加大流量工况（加大比例 {result.increase_percent:.1f}%）】")
            lines.append(f"  加大流量 Q加大 = {result.Q_increased:.4f} m³/s")
            lines.append(f"  加大流速 v加大 = {result.velocity_increased:.4f} m/s")
            lines.append(f"  进口始端流速 v₁加大 = {result.v1_inc_used:.4f} m/s")
            lines.append(f"  进口末端流速 v₂加大 = {result.v2_inc_used:.4f} m/s")
            lines.append(f"  出口末端流速 v₃加大 = {result.v3_inc_used:.4f} m/s")
            lines.append(f"  进口落差 ΔZ1加大 = {result.loss_inlet_inc:.4f} m")
            lines.append(f"  管道段损失 ΔZ2加大 = {result.loss_pipe_inc:.4f} m")
            lines.append(f"  出口落差 ΔZ3加大 = {result.loss_outlet_inc:.4f} m")
            lines.append(f"  总水面落差 ΔZ加大 = {result.total_head_loss_inc:.4f} m")
            lines.append("=" * 60)
        
        if show_steps and result.calculation_steps:
            lines.append("")
            lines.append("详细计算过程：")
            lines.append("")
            lines.extend(result.calculation_steps)
        
        return "\n".join(lines)


if __name__ == "__main__":
    # 测试代码
    from siphon_models import GradientType, V2Strategy
    
    # 创建测试参数（使用默认 AUTO_PIPE 策略，v_pipe_in 将被管道流速覆盖）
    params = GlobalParameters(
        Q=10.0,           # 10 m³/s
        v_guess=2.0,      # 2 m/s
        roughness_n=0.014,
        inlet_type=GradientType.QUARTER_ARC,
        outlet_type=GradientType.QUARTER_ARC,
        v_channel_in=1.0,   # 进口渐变段始端流速 v₁
        v_pipe_in=1.5,      # 进口渐变段末端流速 v₂（AUTO_PIPE 策略下会被覆盖）
        v_channel_out=1.5,  # 出口渐变段始端流速 v
        v_pipe_out=1.0,     # 出口渐变段末端流速 v₃
        xi_inlet=0.15,
        xi_outlet=0.25,
        v2_strategy=V2Strategy.AUTO_PIPE
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
