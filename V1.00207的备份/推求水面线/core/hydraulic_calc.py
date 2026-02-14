# -*- coding: utf-8 -*-
"""
水力计算模块

提供水力学相关计算功能，包括流速、水力半径、水头损失、水位衔接等。
注意：具体计算公式将在后续完善。
"""

import math
from typing import List, Dict, Optional
import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from config.constants import (
    GRAVITY, ZERO_TOLERANCE, VELOCITY_PRECISION, 
    ELEVATION_PRECISION, LOCAL_LOSS_COEFFICIENTS,
    TRANSITION_ZETA_COEFFICIENTS, TRANSITION_TWISTED_ZETA_RANGE,
    TRANSITION_LENGTH_COEFFICIENTS, TRANSITION_LENGTH_CONSTRAINTS
)


class HydraulicCalculator:
    """
    水力计算器
    
    负责水力学相关计算，包括：
    - 流速计算
    - 水力半径计算
    - 沿程水头损失
    - 局部水头损失
    - 水位衔接（水面线推求）
    """
    
    def __init__(self, settings: ProjectSettings):
        """
        初始化水力计算器
        
        Args:
            settings: 项目设置（包含流量、糙率等参数）
        """
        self.settings = settings
        self.design_flow = settings.design_flow
        self.max_flow = settings.max_flow
        self.roughness = settings.roughness
        
        # 倒虹吸水头损失字典（按名称匹配）
        self.inverted_siphon_losses: Dict[str, float] = {}
    
    def import_inverted_siphon_losses(self, losses: Dict[str, float]) -> None:
        """
        导入倒虹吸水头损失数据
        
        Args:
            losses: 倒虹吸名称到水头损失的映射 {"名称1": 损失值1, ...}
        """
        self.inverted_siphon_losses = losses.copy()
    
    def get_cross_section_area(self, node: ChannelNode) -> float:
        """
        计算过水断面面积
        
        根据断面形式和参数计算
        
        Args:
            node: 渠道节点
            
        Returns:
            过水断面面积（m²）
        """
        # TODO: 根据实际断面参数完善计算
        params = node.section_params
        structure_type = node.structure_type
        
        if not structure_type:
            return 0.0
        
        # 获取水深
        h = params.get('水深', params.get('h', node.water_depth))
        if h <= 0:
            return 0.0
        
        if structure_type == StructureType.RECTANGULAR_CHANNEL:
            # 矩形：A = b × h
            b = params.get('底宽', params.get('b', 0))
            return b * h
        
        elif structure_type == StructureType.TRAPEZOIDAL_CHANNEL:
            # 梯形：A = (b + m×h) × h
            b = params.get('底宽', params.get('b', 0))
            m = params.get('边坡', params.get('m', 1.0))
            return (b + m * h) * h
        
        elif structure_type == StructureType.CIRCULAR_CHANNEL:
            # 圆形（非满流）：需要更复杂的计算
            # 简化处理：假设已知面积
            return params.get('面积', params.get('A', 0))
        
        else:
            # 其他类型：尝试从参数获取
            return params.get('面积', params.get('A', 0))
    
    def get_wetted_perimeter(self, node: ChannelNode) -> float:
        """
        计算湿周
        
        根据断面形式和参数计算
        
        Args:
            node: 渠道节点
            
        Returns:
            湿周（m）
        """
        # TODO: 根据实际断面参数完善计算
        params = node.section_params
        structure_type = node.structure_type
        
        if not structure_type:
            return 0.0
        
        h = params.get('水深', params.get('h', node.water_depth))
        if h <= 0:
            return 0.0
        
        if structure_type == StructureType.RECTANGULAR_CHANNEL:
            # 矩形：χ = b + 2h
            b = params.get('底宽', params.get('b', 0))
            return b + 2 * h
        
        elif structure_type == StructureType.TRAPEZOIDAL_CHANNEL:
            # 梯形：χ = b + 2h√(1+m²)
            b = params.get('底宽', params.get('b', 0))
            m = params.get('边坡', params.get('m', 1.0))
            return b + 2 * h * math.sqrt(1 + m * m)
        
        elif structure_type == StructureType.CIRCULAR_CHANNEL:
            # 圆形：需要更复杂的计算
            return params.get('湿周', params.get('P', 0))
        
        else:
            return params.get('湿周', params.get('P', 0))
    
    def calculate_hydraulic_radius(self, node: ChannelNode) -> float:
        """
        计算水力半径
        
        R = A / χ
        
        Args:
            node: 渠道节点
            
        Returns:
            水力半径（m）
        """
        A = self.get_cross_section_area(node)
        P = self.get_wetted_perimeter(node)
        
        if P <= ZERO_TOLERANCE:
            return 0.0
        
        return A / P
    
    def calculate_velocity(self, node: ChannelNode, flow: Optional[float] = None) -> float:
        """
        计算流速
        
        v = Q / A
        
        Args:
            node: 渠道节点
            flow: 流量（m³/s），默认使用设计流量
            
        Returns:
            流速（m/s）
        """
        if flow is None:
            flow = self.design_flow
        
        A = self.get_cross_section_area(node)
        
        if A <= ZERO_TOLERANCE:
            return 0.0
        
        v = flow / A
        return round(v, VELOCITY_PRECISION)
    
    def calculate_friction_slope(self, node: ChannelNode) -> float:
        """
        计算水力坡降（曼宁公式反算）
        
        J = (v × n / R^(2/3))²
        
        Args:
            node: 渠道节点
            
        Returns:
            水力坡降
        """
        # TODO: 根据实际需求完善计算
        v = node.velocity
        R = self.calculate_hydraulic_radius(node)
        n = self.roughness
        
        if R <= ZERO_TOLERANCE or v <= 0:
            return 0.0
        
        # 曼宁公式反算坡降
        J = (v * n / (R ** (2.0 / 3.0))) ** 2
        
        return J
    
    def calculate_friction_loss(self, node1: ChannelNode, node2: ChannelNode, 
                                transition_length: float = 0.0) -> float:
        """
        计算沿程水头损失
        
        hf = slope_i × 有效长度
        
        有效长度 = (node2.station_MC - node1.station_MC) 
                 - 渐变段长度（若两行之间有渐变段）
                 - node1.arc_length / 2 
                 - node2.arc_length / 2
        
        Args:
            node1: 起点
            node2: 终点
            transition_length: 两节点间的渐变段总长度（默认0）
            
        Returns:
            沿程水头损失（m）
        """
        # 计算里程MC差
        L_mc = node2.station_MC - node1.station_MC
        
        # 扣除渐变段长度
        L_mc -= transition_length
        
        # 扣除弧长的一半
        arc1 = node1.arc_length if node1.arc_length else 0.0
        arc2 = node2.arc_length if node2.arc_length else 0.0
        L_mc -= (arc1 / 2.0)
        L_mc -= (arc2 / 2.0)
        
        # 防止负值
        effective_length = max(0.0, L_mc)
        
        if effective_length <= 0:
            return 0.0
        
        # 优先使用node2的底坡（下游点），如果没有则使用node1的
        slope_i = node2.slope_i if node2.slope_i and node2.slope_i > 0 else node1.slope_i
        
        if slope_i and slope_i > 0:
            # 使用底坡计算: hf = slope_i × 有效长度
            hf = slope_i * effective_length
            
            # 保存计算详情到下游节点（与损失值保存位置一致）
            node2.friction_calc_details = {
                'method': 'slope',
                'slope_i': slope_i,
                'L_effective': effective_length,
                'hf': round(hf, ELEVATION_PRECISION)
            }
            
            return round(hf, ELEVATION_PRECISION)
        else:
            # 底坡缺失时，回退到曼宁公式
            return self._calculate_friction_loss_manning(node1, node2, effective_length)
    
    def _calculate_friction_loss_manning(self, node1: ChannelNode, node2: ChannelNode, 
                                         length: float) -> float:
        """
        备用方法：使用曼宁公式计算沿程损失（当底坡数据缺失时）
        
        hf = J_avg × L
        
        Args:
            node1: 起点
            node2: 终点
            length: 计算长度
            
        Returns:
            沿程水头损失（m）
        """
        J1 = self.calculate_friction_slope(node1)
        J2 = self.calculate_friction_slope(node2)
        J_avg = (J1 + J2) / 2 if J2 > 0 else J1
        
        hf = J_avg * length
        
        # 保存计算详情到下游节点（与损失值保存位置一致）
        n = node1.roughness if node1.roughness > 0 else self.roughness
        v1 = node1.velocity if node1.velocity > 0 else 0
        v2 = node2.velocity if node2.velocity > 0 else 0
        R1 = node1.section_params.get('R', node1.section_params.get('水力半径', 0))
        R2 = node2.section_params.get('R', node2.section_params.get('水力半径', 0))
        
        node2.friction_calc_details = {
            'method': 'manning',
            'n': n,
            'v1': v1,
            'v2': v2,
            'R1': R1,
            'R2': R2,
            'J1': J1,
            'J2': J2,
            'J_avg': J_avg,
            'L': length,
            'hf': round(hf, ELEVATION_PRECISION)
        }
        
        return round(hf, ELEVATION_PRECISION)
    
    def calculate_local_loss(self, node: ChannelNode) -> float:
        """
        计算局部水头损失
        
        hj = ζ × v²/(2g)
        
        Args:
            node: 渠道节点
            
        Returns:
            局部水头损失（m）
        """
        # TODO: 根据实际需求完善计算
        
        # 分水闸/分水口：局部损失为0（过闸损失在head_loss_gate中单独计算）
        if getattr(node, 'is_diversion_gate', False):
            return 0.0
        
        # 倒虹吸：使用外部导入的水头损失
        if node.structure_type == StructureType.INVERTED_SIPHON:
            if node.name in self.inverted_siphon_losses:
                return self.inverted_siphon_losses[node.name]
            if node.external_head_loss is not None:
                return node.external_head_loss
            return 0.0
        
        # 其他建筑物：根据进出口标识和类型查找系数
        structure_name = node.structure_type.value if node.structure_type else ""
        
        if structure_name in LOCAL_LOSS_COEFFICIENTS:
            coeffs = LOCAL_LOSS_COEFFICIENTS[structure_name]
            
            if node.in_out == InOutType.INLET:
                zeta = coeffs.get("进口", 0.0)
            elif node.in_out == InOutType.OUTLET:
                zeta = coeffs.get("出口", 0.0)
            else:
                zeta = 0.0
            
            v = node.velocity
            hj = zeta * v * v / (2 * GRAVITY)
            return round(hj, ELEVATION_PRECISION)
        
        return 0.0
    
    def calculate_bend_loss(self, node: ChannelNode) -> float:
        """
        计算弯道水头损失
        
        公式：h_w = (n² × L × v²) / R^(4/3) × (3/4) × √(B / R_c)
        
        物理逻辑：弯道总损失 = 基础沿程损失 × 弯道影响修正系数
        
        其中：
        - 基本沿程阻力部分：n²·L·v² / R^(4/3) 基于曼宁公式
        - 弯道修正系数部分：(3/4)·√(B/R_c) 反映水面宽度与弯道半径之比对能量损失的影响
        
        Args:
            node: 渠道节点（包含弯道长度、流速、水力半径、转弯半径等参数）
            
        Returns:
            弯道水头损失（m）
        """
        # 获取弯道长度（使用弧长）
        L = node.arc_length
        if L <= ZERO_TOLERANCE:
            return 0.0
        
        # 获取糙率
        n = node.roughness if node.roughness > 0 else self.roughness
        if n <= ZERO_TOLERANCE:
            return 0.0
        
        # 获取流速
        v = node.velocity
        if v <= ZERO_TOLERANCE:
            return 0.0
        
        # 获取水力半径
        R = node.section_params.get('R', node.section_params.get('水力半径', 0))
        if R <= ZERO_TOLERANCE:
            return 0.0
        
        # 获取转弯半径（弯道半径）
        Rc = node.turn_radius
        if Rc <= ZERO_TOLERANCE:
            Rc = self.settings.turn_radius
        if Rc <= ZERO_TOLERANCE:
            return 0.0
        
        # 计算水面宽度 B = b + 2mh
        h = node.water_depth
        
        # 对于圆形断面，水面宽度需要单独计算
        D = node.section_params.get('D', node.section_params.get('直径', 0))
        if D > 0 and h > 0:
            # 圆形断面水面宽度: B = 2 × √(D×h - h²)，当 h < D/2 时
            if h <= D:
                r = D / 2
                if h <= r:
                    B = 2 * math.sqrt(r * r - (r - h) ** 2)
                else:
                    B = 2 * math.sqrt(r * r - (h - r) ** 2)
            else:
                B = D  # 满流时水面宽度为直径
        else:
            # 检查是否只有半径参数（马蹄形隧洞、U形渡槽等）
            # 这些断面类型存储的是"半径"而非"底宽"或"直径"
            R_circle = node.section_params.get('R_circle', node.section_params.get('半径', node.section_params.get('内半径', node.section_params.get('r', 0))))
            if R_circle > ZERO_TOLERANCE:
                # 对于马蹄形等断面，底宽 = 2 × 半径
                b = 2 * R_circle
            else:
                b = node.section_params.get('B', node.section_params.get('底宽', node.section_params.get('b', 0)))
            
            m = node.section_params.get('m', node.section_params.get('边坡系数', node.section_params.get('边坡', 0)))
            # 梯形/矩形断面: B = b + 2mh
            B = b + 2 * m * h
        
        if B <= ZERO_TOLERANCE:
            return 0.0
        
        # 计算弯道水头损失
        # h_w = (n² × L × v²) / R^(4/3) × (3/4) × √(B / R_c)
        hw = (n ** 2 * L * v ** 2) / (R ** (4.0 / 3.0)) * 0.75 * math.sqrt(B / Rc)
        
        # 保存计算详情（用于双击展示）
        node.bend_calc_details = {
            'n': n,
            'L': L,
            'v': v,
            'R': R,
            'Rc': Rc,
            'B': B,
            'hw': round(hw, ELEVATION_PRECISION)
        }
        
        return round(hw, ELEVATION_PRECISION)
    
    def calculate_water_profile(self, nodes: List[ChannelNode], 
                                method: str = "backward") -> None:
        """
        推求水面线
        
        Args:
            nodes: 节点列表（原地修改）
            method: 推算方法
                - "backward": 逆推法（从下游向上游）
                - "forward": 顺推法（从上游向下游）
        """
        # TODO: 根据实际需求完善水面线推求逻辑
        
        if not nodes:
            return
        
        if method == "forward":
            self._calculate_forward(nodes)
        else:
            self._calculate_backward(nodes)
    
    def _calculate_forward(self, nodes: List[ChannelNode]) -> None:
        """
        顺推法：从上游向下游计算
        
        Z_下 = Z_上 - hf - hj - hw - h_transition
        
        渐变段行处理规则（方案B）：
        - 渐变段行不显示水位和底高程
        - 渐变段损失计入下游节点的水位计算
        """
        # 设置起点水位（第一个非渐变段节点）
        first_regular_node = None
        first_regular_node_idx = 0
        for idx, node in enumerate(nodes):
            if not node.is_transition:
                first_regular_node = node
                first_regular_node_idx = idx
                break
        
        if first_regular_node:
            first_regular_node.water_level = self.settings.start_water_level
            if first_regular_node.water_depth > 0:
                first_regular_node.bottom_elevation = first_regular_node.water_level - first_regular_node.water_depth
            # 计算第一个节点的流速和弯道损失
            if first_regular_node.velocity <= 0:
                first_regular_node.velocity = self.calculate_velocity(first_regular_node)
            if first_regular_node.arc_length > ZERO_TOLERANCE:
                first_regular_node.head_loss_bend = self.calculate_bend_loss(first_regular_node)
        
        # 遍历计算水位
        prev_regular_node = first_regular_node
        prev_regular_node_idx = first_regular_node_idx
        
        for i in range(len(nodes)):
            curr_node = nodes[i]
            
            # 跳过第一个节点（已设置水位）和渐变段
            if curr_node == first_regular_node:
                continue
            if curr_node.is_transition:
                continue
            
            # ===== 分水闸/分水口特殊处理 =====
            # 分水闸是点状结构，仅产生过闸水头损失，不计算沿程/弯道/局部损失
            if getattr(curr_node, 'is_diversion_gate', False):
                head_loss_gate = getattr(curr_node, 'head_loss_gate', 0.0) or 0.0
                
                # 水位 = 前一节点水位 - 过闸水头损失
                curr_node.water_level = prev_regular_node.water_level - head_loss_gate
                
                # 各项损失清零（仅过闸损失有效）
                curr_node.head_loss_friction = 0.0
                curr_node.head_loss_bend = 0.0
                curr_node.head_loss_local = 0.0
                curr_node.head_loss_total = head_loss_gate
                
                # 更新状态
                prev_regular_node = curr_node
                prev_regular_node_idx = i
                continue
            
            # ===== 常规节点处理 =====
            # 计算当前节点的流速（如果未设置）
            if curr_node.velocity <= 0:
                curr_node.velocity = self.calculate_velocity(curr_node)
            
            # 计算当前节点的弯道损失（如果有弧长且未计算）
            if curr_node.arc_length > ZERO_TOLERANCE and curr_node.head_loss_bend == 0:
                curr_node.head_loss_bend = self.calculate_bend_loss(curr_node)
            hw = curr_node.head_loss_bend or 0.0
            
            # 查找前一个非渐变段节点到当前节点之间的渐变段损失
            accumulated_transition_loss = 0.0
            transition_len_between = 0.0
            for j in range(prev_regular_node_idx + 1, i):
                if nodes[j].is_transition:
                    transition_loss = self._estimate_transition_loss(prev_regular_node, curr_node)
                    accumulated_transition_loss += transition_loss
                    if nodes[j].transition_length:
                        transition_len_between += nodes[j].transition_length
            
            # 计算沿程损失
            hf = self.calculate_friction_loss(prev_regular_node, curr_node, transition_len_between)
            curr_node.head_loss_friction = hf
            
            # 计算局部损失
            hj = self.calculate_local_loss(curr_node)
            curr_node.head_loss_local = hj
            
            # 计算当前节点水位
            curr_node.water_level = prev_regular_node.water_level - hf - hj - hw - accumulated_transition_loss
            
            # 获取预留、过闸、倒虹吸损失
            head_loss_reserve = getattr(curr_node, 'head_loss_reserve', 0.0) or 0.0
            head_loss_gate = getattr(curr_node, 'head_loss_gate', 0.0) or 0.0
            head_loss_siphon = getattr(curr_node, 'head_loss_siphon', 0.0) or 0.0
            
            # 计算总水头损失（不含渐变段损失）
            curr_node.head_loss_total = hw + hf + head_loss_reserve + head_loss_gate + head_loss_siphon
            
            # 计算底高程
            if curr_node.water_depth > 0:
                curr_node.bottom_elevation = curr_node.water_level - curr_node.water_depth
            
            # 更新状态
            prev_regular_node = curr_node
            prev_regular_node_idx = i
    
    def _estimate_transition_loss(self, prev_node: ChannelNode, next_node: ChannelNode) -> float:
        """
        预估渐变段损失（用于水位推求）
        
        Args:
            prev_node: 前一节点
            next_node: 后一节点
            
        Returns:
            渐变段损失估算值（m）
        """
        from config.constants import TRANSITION_ZETA_COEFFICIENTS, TRANSITION_LENGTH_COEFFICIENTS, ZERO_TOLERANCE, GRAVITY, ELEVATION_PRECISION
        
        # 获取流速
        v1 = prev_node.velocity if prev_node.velocity > 0 else 0
        v2 = next_node.velocity if next_node.velocity > 0 else 0
        
        if v1 <= ZERO_TOLERANCE and v2 <= ZERO_TOLERANCE:
            return 0.0
        
        # 默认出口渐变段
        transition_type = "出口"
        transition_form = getattr(self.settings, 'transition_outlet_form', "曲线形反弯扭曲面") or "曲线形反弯扭曲面"
        
        # 获取ζ系数
        if transition_type in TRANSITION_ZETA_COEFFICIENTS:
            zeta_table = TRANSITION_ZETA_COEFFICIENTS[transition_type]
            zeta = zeta_table.get(transition_form, 0.2)
        else:
            zeta = 0.2
        
        # 计算局部水头损失
        h_j1 = zeta * abs(v2 * v2 - v1 * v1) / (2 * GRAVITY)
        
        # 计算水面宽度
        B1 = self.get_water_surface_width(prev_node)
        B2 = self.get_water_surface_width(next_node)
        
        # 计算渐变段长度
        coefficient = TRANSITION_LENGTH_COEFFICIENTS.get(transition_type, 3.5)
        length = coefficient * abs(B1 - B2)
        
        # 计算沿程损失（平均值法）
        R1 = prev_node.section_params.get('R', 0) if prev_node.section_params else 0
        R2 = next_node.section_params.get('R', 0) if next_node.section_params else 0
        R_avg = (R1 + R2) / 2 if (R1 > 0 and R2 > 0) else max(R1, R2)
        v_avg = (v1 + v2) / 2 if (v1 > 0 and v2 > 0) else max(v1, v2)
        
        n = prev_node.roughness if prev_node.roughness > 0 else self.roughness
        
        if R_avg > ZERO_TOLERANCE and v_avg > ZERO_TOLERANCE:
            i = (v_avg * n / (R_avg ** (2.0 / 3.0))) ** 2
            h_f = i * length
        else:
            h_f = 0.0
        
        return round(h_j1 + h_f, ELEVATION_PRECISION)
    
    def _calculate_backward(self, nodes: List[ChannelNode]) -> None:
        """
        逆推法：从下游向上游计算
        
        Z_上 = Z_下 + hf + hj
        """
        # 设置起点水位（此处起点是计算的起始点，即最上游）
        nodes[0].water_level = self.settings.start_water_level
        
        # 实际应用中，逆推法通常是已知下游水位，向上游推算
        # 这里简化为顺推处理，后续根据需求调整
        self._calculate_forward(nodes)
    
    # ========== 渐变段水头损失计算方法 ==========
    
    def get_water_surface_width(self, node: ChannelNode) -> float:
        """
        计算水面宽度B
        
        - 梯形/矩形: B = b + 2mh
        - 圆形: B = 2√(r² - (r-h)²)，当 h <= r 时
        - 马蹄形/U形等只有半径的断面: 底宽 = 2 × 半径
        
        Args:
            node: 渠道节点
            
        Returns:
            水面宽度（m）
        """
        h = node.water_depth
        if h <= ZERO_TOLERANCE:
            h = node.section_params.get('水深', node.section_params.get('h', 0))
        if h <= ZERO_TOLERANCE:
            return 0.0
        
        params = node.section_params
        
        # 检查是否为圆形断面（有直径参数）
        D = params.get('D', params.get('直径', 0))
        if D > 0:
            r = D / 2
            if h <= D:
                if h <= r:
                    B = 2 * math.sqrt(r * r - (r - h) ** 2)
                else:
                    B = 2 * math.sqrt(r * r - (h - r) ** 2)
            else:
                B = D
            return B
        
        # 检查是否只有半径参数（马蹄形隧洞、U形渡槽等）
        # 这些断面类型存储的是"半径"而非"底宽"或"直径"
        # 需要将半径换算为底宽：底宽 = 2 × 半径
        R_circle = params.get('R_circle', params.get('半径', params.get('内半径', params.get('r', 0))))
        if R_circle > ZERO_TOLERANCE:
            # 对于马蹄形等断面，底宽 = 2 × 半径
            b = 2 * R_circle
        else:
            # 梯形/矩形断面，直接获取底宽
            b = params.get('B', params.get('底宽', params.get('b', 0)))
        
        m = params.get('m', params.get('边坡系数', params.get('边坡', 0)))
        
        B = b + 2 * m * h
        return B
    
    def get_channel_design_depth(self, flow_section: str, nodes: List[ChannelNode]) -> float:
        """
        获取同一流量段内明渠结构的设计水深
        
        在nodes中查找同一flow_section的明渠节点，返回其设计水深（若多个取最大值）
        
        Args:
            flow_section: 流量段标识
            nodes: 节点列表
            
        Returns:
            设计水深（m）
        """
        max_depth = 0.0
        
        for node in nodes:
            # 检查是否为同一流量段
            if node.flow_section != flow_section:
                continue
            
            # 检查是否为明渠结构
            if node.structure_type is None:
                continue
            
            struct_name = node.structure_type.value
            if "明渠" not in struct_name:
                continue
            
            # 获取水深
            depth = node.water_depth
            if depth <= 0:
                depth = node.section_params.get('水深', node.section_params.get('h', 0))
            
            if depth > max_depth:
                max_depth = depth
        
        # 如果没找到，返回默认值
        if max_depth <= 0:
            max_depth = 2.0  # 默认2米
        
        return max_depth
    
    def get_transition_zeta(self, transition_node: ChannelNode) -> float:
        """
        获取渐变段局部损失系数ζ
        
        从TRANSITION_ZETA_COEFFICIENTS表查找，支持手动修改和直线形扭曲面插值
        
        Args:
            transition_node: 渐变段节点
            
        Returns:
            ζ系数
        """
        transition_type = transition_node.transition_type  # "进口"或"出口"
        form = transition_node.transition_form
        
        # 如果用户手动设置了ζ值，直接使用
        if transition_node.transition_zeta > ZERO_TOLERANCE:
            return transition_node.transition_zeta
        
        # 从表K.1.2查找
        if transition_type in TRANSITION_ZETA_COEFFICIENTS:
            zeta_table = TRANSITION_ZETA_COEFFICIENTS[transition_type]
            
            if form in zeta_table:
                return zeta_table[form]
            
            elif form == "直线形扭曲面":
                # 根据θ角度线性插值
                theta = transition_node.transition_theta
                range_config = TRANSITION_TWISTED_ZETA_RANGE.get(transition_type, {})
                
                min_theta = range_config.get("min_theta", 15)
                max_theta = range_config.get("max_theta", 37)
                min_zeta = range_config.get("min_zeta", 0.0)
                max_zeta = range_config.get("max_zeta", 0.1)
                
                if theta <= min_theta:
                    return min_zeta
                elif theta >= max_theta:
                    return max_zeta
                else:
                    # 线性插值
                    ratio = (theta - min_theta) / (max_theta - min_theta)
                    return min_zeta + ratio * (max_zeta - min_zeta)
        
        # 默认值
        return 0.1 if transition_type == "进口" else 0.2
    
    def calculate_transition_length(self, transition_node: ChannelNode,
                                    prev_node: ChannelNode,
                                    next_node: ChannelNode,
                                    all_nodes: List[ChannelNode]) -> float:
        """
        计算渐变段长度L
        
        基本公式：
        - 进口: L = 2.5 × |B1 - B2|
        - 出口: L = 3.5 × |B1 - B2|
        
        约束条件：
        - 渡槽进口: max(计算值, 6倍渠道设计水深)
        - 渡槽出口: max(计算值, 8倍渠道设计水深)
        - 隧洞进出口: max(计算值, 5倍渠道水深, 3倍洞径或洞宽)
        
        Args:
            transition_node: 渐变段节点
            prev_node: 前一节点（渐变段起始端）
            next_node: 后一节点（渐变段末端）
            all_nodes: 所有节点列表（用于查找渠道水深）
            
        Returns:
            渐变段长度L（m）
        """
        # 计算水面宽度
        B1 = self.get_water_surface_width(prev_node)
        B2 = self.get_water_surface_width(next_node)
        
        transition_node.transition_water_width_1 = B1
        transition_node.transition_water_width_2 = B2
        
        # 基本公式
        transition_type = transition_node.transition_type
        coefficient = TRANSITION_LENGTH_COEFFICIENTS.get(transition_type, 2.5)
        L_basic = coefficient * abs(B1 - B2)
        
        # 应用约束条件
        L_result = L_basic
        
        # 确定结构类型（从前一节点获取）
        structure_type = prev_node.structure_type
        if structure_type is None:
            return L_result
        
        struct_name = structure_type.value
        
        # 获取相邻明渠的水深（而非整个流量段的最大水深）
        # - 出口渐变段（建筑物出口→明渠）：使用 next_node（下游明渠）的水深
        # - 进口渐变段（明渠→建筑物进口）：使用 prev_node（上游明渠）的水深
        channel_depth = 0.0
        if transition_type == "出口":
            # 出口渐变段：使用下游节点（next_node）的水深
            if next_node and next_node.water_depth > 0:
                channel_depth = next_node.water_depth
            elif next_node and next_node.section_params:
                channel_depth = next_node.section_params.get('水深', next_node.section_params.get('h', 0))
        else:
            # 进口渐变段：使用上游节点（prev_node）的水深
            if prev_node and prev_node.water_depth > 0:
                channel_depth = prev_node.water_depth
            elif prev_node and prev_node.section_params:
                channel_depth = prev_node.section_params.get('水深', prev_node.section_params.get('h', 0))
        
        # 如果相邻节点水深无效，回退到查找同一流量段的明渠水深
        if channel_depth <= 0:
            channel_depth = self.get_channel_design_depth(
                transition_node.flow_section, all_nodes
            )
        
        # 渡槽约束
        if "渡槽" in struct_name:
            constraints = TRANSITION_LENGTH_CONSTRAINTS.get("渡槽", {})
            type_constraint = constraints.get(transition_type, {})
            depth_multiplier = type_constraint.get("depth_multiplier", 6)
            L_min = depth_multiplier * channel_depth
            L_result = max(L_result, L_min)
        
        # 隧洞约束
        elif "隧洞" in struct_name:
            constraints = TRANSITION_LENGTH_CONSTRAINTS.get("隧洞", {})
            type_constraint = constraints.get(transition_type, {})
            
            # 5倍渠道水深
            depth_multiplier = type_constraint.get("depth_multiplier", 5)
            L_depth = depth_multiplier * channel_depth
            
            # 3倍洞径或洞宽
            tunnel_multiplier = type_constraint.get("tunnel_multiplier", 3)
            D = prev_node.section_params.get('D', prev_node.section_params.get('直径', 0))
            B = prev_node.section_params.get('B', prev_node.section_params.get('底宽', 0))
            # 对于马蹄形隧洞等只有半径的断面，需要将半径换算为直径
            R_circle = prev_node.section_params.get('R_circle', prev_node.section_params.get('半径', prev_node.section_params.get('内半径', 0)))
            if R_circle > 0 and D == 0:
                D = 2 * R_circle  # 半径换算为直径
            tunnel_size = max(D, B)
            L_tunnel = tunnel_multiplier * tunnel_size
            
            L_result = max(L_result, L_depth, L_tunnel)
        
        return L_result
    
    def calculate_transition_friction_loss(self, transition_node: ChannelNode,
                                           prev_node: ChannelNode,
                                           next_node: ChannelNode,
                                           length: float) -> float:
        """
        计算渐变段沿程水头损失（平均值法）
        
        步骤：
        1. 计算两断面的R和v平均值
        2. 代入曼宁公式求平均水力坡降i
        3. h_f = i × L
        
        Args:
            transition_node: 渐变段节点
            prev_node: 前一节点
            next_node: 后一节点
            length: 渐变段长度
            
        Returns:
            沿程水头损失（m）
        """
        # 获取水力半径
        R1 = prev_node.section_params.get('R', prev_node.section_params.get('水力半径', 0))
        R2 = next_node.section_params.get('R', next_node.section_params.get('水力半径', 0))
        
        if R1 <= 0:
            R1 = self.calculate_hydraulic_radius(prev_node)
        if R2 <= 0:
            R2 = self.calculate_hydraulic_radius(next_node)
        
        R_avg = (R1 + R2) / 2 if (R1 > 0 and R2 > 0) else max(R1, R2)
        transition_node.transition_avg_R = R_avg
        
        # 获取流速
        v1 = prev_node.velocity
        v2 = next_node.velocity
        v_avg = (v1 + v2) / 2 if (v1 > 0 and v2 > 0) else max(v1, v2)
        transition_node.transition_avg_v = v_avg
        
        # 糙率
        n = transition_node.roughness if transition_node.roughness > 0 else self.roughness
        
        # 曼宁公式反算水力坡降
        if R_avg > ZERO_TOLERANCE and v_avg > ZERO_TOLERANCE:
            i = (v_avg * n / (R_avg ** (2.0 / 3.0))) ** 2
        else:
            i = 0.0
        
        # 沿程损失
        h_f = i * length
        
        return round(h_f, ELEVATION_PRECISION)
    
    def calculate_transition_loss(self, transition_node: ChannelNode,
                                  prev_node: ChannelNode,
                                  next_node: ChannelNode,
                                  all_nodes: List[ChannelNode]) -> float:
        """
        计算渐变段水头损失
        
        包括：
        1. 局部水头损失 h_j1 = ξ₁ × |v₂² - v₁²| / (2g)
        2. 沿程水头损失 h_f = i × L（使用平均值法）
        
        Args:
            transition_node: 渐变段节点
            prev_node: 前一节点（渐变段起始端）
            next_node: 后一节点（渐变段末端）
            all_nodes: 所有节点列表（用于查找渠道水深）
            
        Returns:
            总水头损失（m）
        """
        # 1. 获取ζ系数
        zeta = self.get_transition_zeta(transition_node)
        transition_node.transition_zeta = zeta
        
        # 2. 计算渐变段长度
        length = self.calculate_transition_length(
            transition_node, prev_node, next_node, all_nodes
        )
        transition_node.transition_length = length
        
        # 3. 获取起始和末端流速
        v1 = prev_node.velocity
        v2 = next_node.velocity
        transition_node.transition_velocity_1 = v1
        transition_node.transition_velocity_2 = v2
        
        # 4. 计算局部水头损失: h_j1 = ξ × |v₂² - v₁²| / (2g)
        h_j1 = zeta * abs(v2 * v2 - v1 * v1) / (2 * GRAVITY)
        h_j1 = round(h_j1, ELEVATION_PRECISION)
        transition_node.transition_head_loss_local = h_j1
        
        # 5. 计算沿程水头损失（使用平均值法）
        h_f = self.calculate_transition_friction_loss(
            transition_node, prev_node, next_node, length
        )
        transition_node.transition_head_loss_friction = h_f
        
        # 6. 总损失
        total_loss = h_j1 + h_f
        transition_node.head_loss_transition = round(total_loss, ELEVATION_PRECISION)
        
        # 7. 记录计算详细过程（用于LaTeX显示）
        transition_node.transition_calc_details = {
            "transition_type": transition_node.transition_type,
            "transition_form": transition_node.transition_form,
            "zeta": zeta,
            "v1": v1,
            "v2": v2,
            "B1": transition_node.transition_water_width_1,
            "B2": transition_node.transition_water_width_2,
            "length": length,
            "R_avg": transition_node.transition_avg_R,
            "v_avg": transition_node.transition_avg_v,
            "h_j1": h_j1,
            "h_f": h_f,
            "total": total_loss,
        }
        
        return total_loss

    def calculate_transition_loss_inline(self, prev_node: ChannelNode,
                                         next_node: ChannelNode,
                                         settings: ProjectSettings) -> tuple:
        """
        计算渐变段水头损失（内联方式，不依赖专用渐变段节点）
        
        将计算结果返回，供调用方累加到相邻节点的总损失中。
        
        Args:
            prev_node: 前一节点（出口侧）
            next_node: 后一节点（进口侧）
            settings: 项目设置（用于获取渐变段形式等参数）
            
        Returns:
            tuple: (total_loss, details_dict)
                - total_loss: 总水头损失（m）
                - details_dict: 详细计算信息字典（用于双击显示）
        """
        # 1. 确定渐变段类型和形式
        transition_type = "出口"  # 从prev_node出口到next_node
        transition_form = getattr(settings, 'transition_outlet_form', "曲线形反弯扭曲面") or "曲线形反弯扭曲面"
        
        # 2. 获取ζ系数
        if transition_type in TRANSITION_ZETA_COEFFICIENTS:
            zeta_table = TRANSITION_ZETA_COEFFICIENTS[transition_type]
            zeta = zeta_table.get(transition_form, 0.2)
        else:
            zeta = 0.2  # 默认出口系数
        
        # 3. 计算水面宽度
        B1 = self.get_water_surface_width(prev_node)
        B2 = self.get_water_surface_width(next_node)
        
        # 4. 计算渐变段长度
        coefficient = TRANSITION_LENGTH_COEFFICIENTS.get(transition_type, 3.5)
        L_basic = coefficient * abs(B1 - B2)
        
        # 应用约束条件
        length = L_basic
        structure_type = prev_node.structure_type
        if structure_type:
            struct_name = structure_type.value
            
            # 渡槽约束
            if "渡槽" in struct_name:
                constraints = TRANSITION_LENGTH_CONSTRAINTS.get("渡槽", {})
                type_constraint = constraints.get(transition_type, {})
                depth_multiplier = type_constraint.get("depth_multiplier", 8)
                # 出口渐变段使用下游节点（next_node）的水深
                channel_depth = next_node.water_depth if next_node.water_depth > 0 else 0
                L_min = depth_multiplier * channel_depth
                length = max(length, L_min)
            
            # 隧洞约束
            elif "隧洞" in struct_name:
                constraints = TRANSITION_LENGTH_CONSTRAINTS.get("隧洞", {})
                type_constraint = constraints.get(transition_type, {})
                depth_multiplier = type_constraint.get("depth_multiplier", 5)
                tunnel_multiplier = type_constraint.get("tunnel_multiplier", 3)
                
                # 出口渐变段使用下游节点（next_node）的水深
                channel_depth = next_node.water_depth if next_node.water_depth > 0 else 0
                L_depth = depth_multiplier * channel_depth
                
                # 获取洞径
                params = prev_node.section_params or {}
                D = params.get('D', params.get('直径', 0))
                R = params.get('R_circle', params.get('半径', 0))
                tunnel_size = D if D > 0 else (2 * R if R > 0 else 0)
                L_tunnel = tunnel_multiplier * tunnel_size
                
                length = max(length, L_depth, L_tunnel)
        
        # 5. 获取流速
        v1 = prev_node.velocity
        v2 = next_node.velocity
        
        # 6. 计算局部水头损失: h_j1 = ξ × |v₂² - v₁²| / (2g)
        h_j1 = zeta * abs(v2 * v2 - v1 * v1) / (2 * GRAVITY)
        h_j1 = round(h_j1, ELEVATION_PRECISION)
        
        # 7. 计算沿程水头损失（平均值法）
        # 获取水力半径
        R1 = prev_node.section_params.get('R', prev_node.section_params.get('水力半径', 0)) if prev_node.section_params else 0
        R2 = next_node.section_params.get('R', next_node.section_params.get('水力半径', 0)) if next_node.section_params else 0
        
        if R1 <= 0:
            R1 = self.calculate_hydraulic_radius(prev_node)
        if R2 <= 0:
            R2 = self.calculate_hydraulic_radius(next_node)
        
        R_avg = (R1 + R2) / 2 if (R1 > 0 and R2 > 0) else max(R1, R2)
        v_avg = (v1 + v2) / 2 if (v1 > 0 and v2 > 0) else max(v1, v2)
        
        # 糙率
        n = prev_node.roughness if prev_node.roughness > 0 else self.roughness
        
        # 曼宁公式反算水力坡降
        if R_avg > ZERO_TOLERANCE and v_avg > ZERO_TOLERANCE:
            i = (v_avg * n / (R_avg ** (2.0 / 3.0))) ** 2
        else:
            i = 0.0
        
        h_f = i * length
        h_f = round(h_f, ELEVATION_PRECISION)
        
        # 8. 总损失
        total_loss = round(h_j1 + h_f, ELEVATION_PRECISION)
        
        # 9. 构建详细计算信息
        details = {
            "transition_type": transition_type,
            "transition_form": transition_form,
            "zeta": zeta,
            "v1": v1,
            "v2": v2,
            "B1": B1,
            "B2": B2,
            "length": length,
            "R_avg": R_avg,
            "v_avg": v_avg,
            "h_j1": h_j1,
            "h_f": h_f,
            "total": total_loss,
        }
        
        return total_loss, details
