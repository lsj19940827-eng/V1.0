# -*- coding: utf-8 -*-
"""
有压管道数据提取模块

从推求水面线表格数据中识别和提取有压管道分组信息。
有压管道结构：进口行 + 多个IP点行 + 出口行，通过"进出口标识"列区分。
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from collections import defaultdict

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.data_models import ChannelNode
from models.enums import StructureType, InOutType
from core.pressure_pipe_calc import calc_turn_angle, calc_segment_length


@dataclass
class PressurePipeGroup:
    """
    有压管道分组数据
    
    表示一个完整的有压管道，包含进口、IP点、出口所有行的数据。
    """
    name: str                                   # 建筑物名称（如"1号有压管道"）
    rows: List[ChannelNode] = field(default_factory=list)  # 该管道的所有行数据
    row_indices: List[int] = field(default_factory=list)   # 各行在原始列表中的索引
    inlet_row_index: int = -1                   # 进口行索引（在原始列表中）
    outlet_row_index: int = -1                  # 出口行索引（在原始列表中）
    ip_row_indices: List[int] = field(default_factory=list)  # 中间IP点行索引列表
    
    # ========== 管道参数 ==========
    design_flow: float = 0.0                    # 设计流量 Q（m³/s）
    diameter: float = 0.0                       # 管径 D（m）
    material_key: str = ""                      # 管材键名
    local_loss_ratio: float = 0.15              # 局部损失比例（简化模式用）
    
    # ========== IP点信息 ==========
    ip_points: List[Dict] = field(default_factory=list)  # IP点列表 [{x, y, turn_radius, turn_angle}, ...]
    plan_segments: List[Dict] = field(default_factory=list)  # 平面段列表（直管+弯管交替）
    plan_total_length: float = 0.0              # 平面总水平投影长度 (m)
    
    # ========== 上下游渠道信息（自动提取） ==========
    upstream_velocity: float = 0.0              # 上游渠道流速 v₁ (m/s)
    downstream_velocity: float = 0.0            # 下游渠道流速 v₃ (m/s)
    upstream_structure_type: Optional[str] = None  # 上游渠道结构类型
    downstream_structure_type: Optional[str] = None  # 下游渠道结构类型
    upstream_section_params: Dict = field(default_factory=dict)   # 上游断面参数
    downstream_section_params: Dict = field(default_factory=dict) # 下游断面参数
    
    # ========== 渐变段型式 ==========
    inlet_transition_form: str = "反弯扭曲面"   # 进口渐变段型式
    outlet_transition_form: str = "反弯扭曲面"  # 出口渐变段型式
    inlet_transition_zeta: float = 0.10         # 进口渐变段局部损失系数
    outlet_transition_zeta: float = 0.20        # 出口渐变段局部损失系数
    
    def is_valid(self) -> bool:
        """检查有压管道数据是否有效"""
        return (
            len(self.rows) >= 2 and  # 至少有进口和出口
            self.name and
            self.inlet_row_index >= 0 and
            self.outlet_row_index >= 0 and
            self.design_flow > 0 and
            self.diameter > 0
        )
    
    def get_validation_message(self) -> str:
        """获取验证信息"""
        issues = []
        if not self.name:
            issues.append("缺少建筑物名称")
        if len(self.rows) < 2:
            issues.append("至少需要进口和出口两行")
        if self.inlet_row_index < 0:
            issues.append("未识别到进口行（进出口标识='进'）")
        if self.outlet_row_index < 0:
            issues.append("未识别到出口行（进出口标识='出'）")
        if self.design_flow <= 0:
            issues.append("设计流量无效")
        if self.diameter <= 0:
            issues.append("管径无效")
        if not self.material_key:
            issues.append("未指定管材")
        
        if issues:
            return f"{self.name}: " + ", ".join(issues)
        return ""


class PressurePipeDataExtractor:
    """
    有压管道数据提取器
    
    从渠道节点列表中识别和提取有压管道分组。
    """
    
    @staticmethod
    def extract_pipes(nodes: List[ChannelNode], settings=None) -> List[PressurePipeGroup]:
        """
        从节点列表中识别所有有压管道
        
        识别规则：
        1. structure_type == StructureType.PRESSURE_PIPE（结构形式为"有压管道"）
        2. 按 name（建筑物名称）分组，相同名称的行属于同一管道
        3. 通过 section_params['in_out_raw'] 识别进口("进")/IP点("IP")/出口("出")
        4. 提取上下游渠道节点的流速、断面参数等
        
        Args:
            nodes: 渠道节点列表
            settings: 项目基础设置（ProjectSettings），用于获取渐变段型式等全局参数
            
        Returns:
            有压管道分组列表，按在表格中出现的顺序排列
        """
        if not nodes:
            return []
        
        # 按名称分组，同时记录索引
        groups_dict: Dict[str, PressurePipeGroup] = {}
        group_order: List[str] = []  # 记录出现顺序
        
        for idx, node in enumerate(nodes):
            # 检查是否为有压管道
            if not PressurePipeDataExtractor._is_pressure_pipe(node):
                continue
            
            name = node.name.strip()
            if not name:
                continue
            
            # 创建或获取分组
            if name not in groups_dict:
                groups_dict[name] = PressurePipeGroup(name=name)
                group_order.append(name)
            
            group = groups_dict[name]
            group.rows.append(node)
            group.row_indices.append(idx)
            
            # 获取进出口标识
            in_out_raw = node.section_params.get('in_out_raw', '') if node.section_params else ''
            
            # 识别进口/IP/出口
            if in_out_raw == "进" or node.in_out == InOutType.INLET:
                group.inlet_row_index = idx
                # 从进口行提取管道参数
                group.design_flow = node.flow if node.flow > 0 else group.design_flow
                sp = node.section_params or {}
                group.diameter = sp.get('D', 0) or sp.get('直径D', 0) or group.diameter
                group.material_key = sp.get('pipe_material', '') or group.material_key
                group.local_loss_ratio = sp.get('local_loss_ratio', 0.15)
            elif in_out_raw == "出" or node.in_out == InOutType.OUTLET:
                group.outlet_row_index = idx
                # 出口行也可能有参数，作为备用
                if group.design_flow <= 0:
                    group.design_flow = node.flow
                sp = node.section_params or {}
                if group.diameter <= 0:
                    group.diameter = sp.get('D', 0) or sp.get('直径D', 0)
                if not group.material_key:
                    group.material_key = sp.get('pipe_material', '')
            elif in_out_raw == "IP":
                group.ip_row_indices.append(idx)
        
        # 处理每个分组，提取参数
        result = []
        for name in group_order:
            group = groups_dict[name]
            
            # 如果没有明确的进出口标记，尝试根据位置推断
            if group.inlet_row_index < 0 and group.row_indices:
                group.inlet_row_index = group.row_indices[0]
                first_node = group.rows[0]
                group.design_flow = first_node.flow if first_node.flow > 0 else 0
                sp = first_node.section_params or {}
                group.diameter = sp.get('D', 0) or sp.get('直径D', 0)
                group.material_key = sp.get('pipe_material', '')
            
            if group.outlet_row_index < 0 and group.row_indices:
                group.outlet_row_index = group.row_indices[-1]
            
            # 提取IP点信息
            PressurePipeDataExtractor._extract_ip_points(group)
            
            # 计算转角
            PressurePipeDataExtractor._calc_turn_angles(group)
            
            # 计算平面段
            PressurePipeDataExtractor._calc_plan_segments(group)
            
            # 提取上下游渠道节点数据
            PressurePipeDataExtractor._extract_adjacent_node_data(group, nodes)
            
            # 提取渐变段型式（从基础设置）
            if settings is not None:
                PressurePipeDataExtractor._extract_transition_forms(group, settings)
            
            result.append(group)
        
        return result
    
    @staticmethod
    def _is_pressure_pipe(node: ChannelNode) -> bool:
        """判断节点是否为有压管道"""
        if node.structure_type == StructureType.PRESSURE_PIPE:
            return True
        if node.structure_type and node.structure_type.value == "有压管道":
            return True
        # 检查is_pressure_pipe标记
        if getattr(node, 'is_pressure_pipe', False):
            return True
        return False
    
    @staticmethod
    def _extract_ip_points(group: PressurePipeGroup):
        """
        提取IP点信息（坐标、转弯半径等）
        
        IP点顺序：进口 → 中间IP点 → 出口
        """
        ip_points = []
        
        for node in group.rows:
            in_out_raw = node.section_params.get('in_out_raw', '') if node.section_params else ''
            
            point = {
                'x': node.x,
                'y': node.y,
                'turn_radius': node.turn_radius,
                'turn_angle': 0,  # 稍后计算
                'in_out': in_out_raw,
                'name': node.name,
            }
            ip_points.append(point)
        
        group.ip_points = ip_points
    
    @staticmethod
    def _calc_turn_angles(group: PressurePipeGroup):
        """计算各中间IP点的转角"""
        if len(group.ip_points) < 3:
            return
        
        for i in range(1, len(group.ip_points) - 1):
            p_prev = (group.ip_points[i-1]['x'], group.ip_points[i-1]['y'])
            p_curr = (group.ip_points[i]['x'], group.ip_points[i]['y'])
            p_next = (group.ip_points[i+1]['x'], group.ip_points[i+1]['y'])
            
            turn_angle = calc_turn_angle(p_prev, p_curr, p_next)
            group.ip_points[i]['turn_angle'] = turn_angle
    
    @staticmethod
    def _calc_plan_segments(group: PressurePipeGroup):
        """
        计算平面段（直管+弯管交替）
        
        简化处理：只计算各段的水平投影长度，弯管弧长根据转弯半径和转角计算。
        """
        if len(group.ip_points) < 2:
            return
        
        segments = []
        total_length = 0.0
        
        for i in range(len(group.ip_points) - 1):
            p1 = (group.ip_points[i]['x'], group.ip_points[i]['y'])
            p2 = (group.ip_points[i+1]['x'], group.ip_points[i+1]['y'])
            
            # 直线距离
            straight_dist = calc_segment_length(p1, p2)
            
            # TODO: 扣除弯管切线长修正（简化版本暂不处理）
            seg_length = straight_dist
            
            segment = {
                'type': 'straight',
                'start_ip': i,
                'end_ip': i + 1,
                'length': seg_length,
            }
            segments.append(segment)
            total_length += seg_length
        
        group.plan_segments = segments
        group.plan_total_length = total_length
    
    @staticmethod
    def _extract_adjacent_node_data(group: PressurePipeGroup, nodes: List[ChannelNode]):
        """
        提取上下游渠道节点数据（流速、断面参数等）
        
        上游：进口行往前找第一个非有压管道节点
        下游：出口行往后找第一个非有压管道节点
        """
        if group.inlet_row_index < 0 or group.outlet_row_index < 0:
            return
        
        # 提取上游节点数据
        for i in range(group.inlet_row_index - 1, -1, -1):
            upstream_node = nodes[i]
            
            # 跳过渐变段
            if getattr(upstream_node, 'is_transition', False):
                continue
            
            # 跳过同名有压管道行
            if PressurePipeDataExtractor._is_pressure_pipe(upstream_node):
                continue
            
            # 找到上游节点
            group.upstream_velocity = upstream_node.velocity if upstream_node.velocity > 0 else 0.0
            group.upstream_structure_type = upstream_node.structure_type.value if upstream_node.structure_type else ""
            
            sp = upstream_node.section_params or {}
            group.upstream_section_params = {
                'B': sp.get('B', 0) or sp.get('底宽b', 0) or sp.get('底宽B', 0),
                'h': upstream_node.water_depth,
                'm': sp.get('m', 0) or sp.get('边坡m', 0),
                'D': sp.get('D', 0) or sp.get('直径D', 0),
                'R': sp.get('R', 0) or sp.get('R_circle', 0) or sp.get('半径R', 0),
            }
            break
        
        # 提取下游节点数据
        for i in range(group.outlet_row_index + 1, len(nodes)):
            downstream_node = nodes[i]
            
            # 跳过渐变段
            if getattr(downstream_node, 'is_transition', False):
                continue
            
            # 跳过同名有压管道行
            if PressurePipeDataExtractor._is_pressure_pipe(downstream_node):
                continue
            
            # 找到下游节点
            group.downstream_velocity = downstream_node.velocity if downstream_node.velocity > 0 else 0.0
            group.downstream_structure_type = downstream_node.structure_type.value if downstream_node.structure_type else ""
            
            sp = downstream_node.section_params or {}
            group.downstream_section_params = {
                'B': sp.get('B', 0) or sp.get('底宽b', 0) or sp.get('底宽B', 0),
                'h': downstream_node.water_depth,
                'm': sp.get('m', 0) or sp.get('边坡m', 0),
                'D': sp.get('D', 0) or sp.get('直径D', 0),
                'R': sp.get('R', 0) or sp.get('R_circle', 0) or sp.get('半径R', 0),
            }
            break
    
    @staticmethod
    def _extract_transition_forms(group: PressurePipeGroup, settings):
        """
        从基础设置中提取渐变段型式
        
        有压管道复用倒虹吸的渐变段设置
        """
        # 渐变段型式（复用倒虹吸设置）
        group.inlet_transition_form = getattr(settings, 'siphon_transition_inlet_form', '反弯扭曲面')
        group.outlet_transition_form = getattr(settings, 'siphon_transition_outlet_form', '反弯扭曲面')
        group.inlet_transition_zeta = getattr(settings, 'siphon_transition_inlet_zeta', 0.10)
        group.outlet_transition_zeta = getattr(settings, 'siphon_transition_outlet_zeta', 0.20)


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    print("=== 有压管道数据提取器测试 ===")
    
    # 创建测试节点
    from models.data_models import ChannelNode
    from models.enums import StructureType, InOutType
    
    nodes = [
        # 上游明渠
        ChannelNode(
            name="-",
            structure_type=StructureType.MINGQU_TRAPEZOIDAL,
            x=0, y=0,
            flow=2.0,
            velocity=1.0,
            water_depth=1.5,
            section_params={'B': 2.0, 'm': 1.5}
        ),
        # 有压管道进口
        ChannelNode(
            name="1号管道",
            structure_type=StructureType.PRESSURE_PIPE,
            in_out=InOutType.INLET,
            x=100, y=0,
            flow=2.0,
            section_params={'D': 1.0, 'pipe_material': 'HDPE管', 'in_out_raw': '进'}
        ),
        # IP点1
        ChannelNode(
            name="1号管道",
            structure_type=StructureType.PRESSURE_PIPE,
            x=200, y=50,
            turn_radius=3.0,
            section_params={'in_out_raw': 'IP'}
        ),
        # IP点2
        ChannelNode(
            name="1号管道",
            structure_type=StructureType.PRESSURE_PIPE,
            x=300, y=100,
            turn_radius=3.0,
            section_params={'in_out_raw': 'IP'}
        ),
        # 有压管道出口
        ChannelNode(
            name="1号管道",
            structure_type=StructureType.PRESSURE_PIPE,
            in_out=InOutType.OUTLET,
            x=400, y=100,
            flow=2.0,
            section_params={'D': 1.0, 'pipe_material': 'HDPE管', 'in_out_raw': '出'}
        ),
        # 下游明渠
        ChannelNode(
            name="-",
            structure_type=StructureType.MINGQU_TRAPEZOIDAL,
            x=500, y=100,
            flow=2.0,
            velocity=1.0,
            water_depth=1.5,
            section_params={'B': 2.0, 'm': 1.5}
        ),
    ]
    
    # 提取有压管道
    pipes = PressurePipeDataExtractor.extract_pipes(nodes)
    
    for pipe in pipes:
        print(f"\n管道名称: {pipe.name}")
        print(f"设计流量: {pipe.design_flow} m³/s")
        print(f"管径: {pipe.diameter} m")
        print(f"管材: {pipe.material_key}")
        print(f"进口行索引: {pipe.inlet_row_index}")
        print(f"出口行索引: {pipe.outlet_row_index}")
        print(f"IP点数量: {len(pipe.ip_points)}")
        print(f"平面总长度: {pipe.plan_total_length:.2f} m")
        print(f"上游流速: {pipe.upstream_velocity} m/s")
        print(f"下游流速: {pipe.downstream_velocity} m/s")
        print(f"验证: {pipe.get_validation_message() or '通过'}")
        
        print("\nIP点详情:")
        for i, ip in enumerate(pipe.ip_points):
            print(f"  IP{i}: x={ip['x']}, y={ip['y']}, R={ip['turn_radius']}, θ={ip['turn_angle']:.1f}°")
