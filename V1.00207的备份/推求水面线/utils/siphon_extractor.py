# -*- coding: utf-8 -*-
"""
倒虹吸数据提取模块

从推求水面线表格数据中识别和提取倒虹吸分组信息。
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
from collections import defaultdict

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.data_models import ChannelNode
from models.enums import StructureType, InOutType


@dataclass
class SiphonGroup:
    """
    倒虹吸分组数据
    
    表示一个完整的倒虹吸，包含所有相关行的数据。
    """
    name: str                                   # 建筑物名称（如"沪蓉倒虹吸"）
    rows: List[ChannelNode] = field(default_factory=list)  # 该倒虹吸的所有行数据
    row_indices: List[int] = field(default_factory=list)   # 各行在原始列表中的索引
    inlet_row_index: int = -1                   # 进口行索引（在原始列表中）
    outlet_row_index: int = -1                  # 出口行索引（在原始列表中）
    design_flow: float = 0.0                    # 设计流量（取第一行的flow）
    upstream_level: Optional[float] = None      # 上游水位（进口行的water_level）
    downstream_level: Optional[float] = None    # 下游水位（出口行的water_level）
    upstream_bottom_elev: Optional[float] = None  # 上游渠底高程
    roughness: float = 0.014                    # 糙率
    
    # ========== 平面段信息（从推求水面线表格自动提取） ==========
    plan_segments: List[Dict] = field(default_factory=list)   # 平面段列表
    plan_total_length: float = 0.0              # 平面总水平长度 (MC出 - MC进)
    
    # ========== 平面IP特征点（用于三维空间合并计算） ==========
    plan_feature_points: List[Dict] = field(default_factory=list)  # IP点特征信息列表

    def is_valid(self) -> bool:
        """检查倒虹吸数据是否有效"""
        return (
            len(self.rows) >= 1 and
            self.name and
            (self.inlet_row_index >= 0 or self.outlet_row_index >= 0)
        )
    
    def get_validation_message(self) -> str:
        """获取验证信息"""
        issues = []
        if not self.name:
            issues.append("缺少建筑物名称")
        if len(self.rows) < 1:
            issues.append("没有数据行")
        if self.inlet_row_index < 0:
            issues.append("未识别到进口行")
        if self.outlet_row_index < 0:
            issues.append("未识别到出口行")
        if self.design_flow <= 0:
            issues.append("设计流量无效")
        
        if issues:
            return f"{self.name}: " + ", ".join(issues)
        return ""


class SiphonDataExtractor:
    """
    倒虹吸数据提取器
    
    从渠道节点列表中识别和提取倒虹吸分组。
    """
    
    @staticmethod
    def extract_siphons(nodes: List[ChannelNode]) -> List[SiphonGroup]:
        """
        从节点列表中识别所有倒虹吸
        
        识别规则：
        1. structure_type == StructureType.INVERTED_SIPHON（结构形式为"倒虹吸"）
        2. 按 name（建筑物名称）分组，相同名称的行属于同一倒虹吸
        3. 识别进出口（in_out == INLET/OUTLET）
        
        Args:
            nodes: 渠道节点列表
            
        Returns:
            倒虹吸分组列表，按在表格中出现的顺序排列
        """
        if not nodes:
            return []
        
        # 按名称分组，同时记录索引
        groups_dict: Dict[str, SiphonGroup] = {}
        group_order: List[str] = []  # 记录出现顺序
        
        for idx, node in enumerate(nodes):
            # 检查是否为倒虹吸
            if not SiphonDataExtractor._is_inverted_siphon(node):
                continue
            
            name = node.name.strip()
            if not name:
                continue
            
            # 创建或获取分组
            if name not in groups_dict:
                groups_dict[name] = SiphonGroup(name=name)
                group_order.append(name)
            
            group = groups_dict[name]
            group.rows.append(node)
            group.row_indices.append(idx)
            
            # 识别进出口
            if node.in_out == InOutType.INLET:
                group.inlet_row_index = idx
                group.upstream_level = node.water_level if node.water_level > 0 else None
                group.upstream_bottom_elev = node.bottom_elevation if node.bottom_elevation > 0 else None
            elif node.in_out == InOutType.OUTLET:
                group.outlet_row_index = idx
                group.downstream_level = node.water_level if node.water_level > 0 else None
        
        # 处理每个分组，提取参数
        result = []
        for name in group_order:
            group = groups_dict[name]
            
            # 设置设计流量（取第一行的flow）
            if group.rows:
                group.design_flow = group.rows[0].flow
                group.roughness = group.rows[0].roughness if group.rows[0].roughness > 0 else 0.014
            
            # 如果没有明确的进出口标记，尝试根据位置推断
            if group.inlet_row_index < 0 and group.row_indices:
                group.inlet_row_index = group.row_indices[0]
                first_node = group.rows[0]
                group.upstream_level = first_node.water_level if first_node.water_level > 0 else None
                group.upstream_bottom_elev = first_node.bottom_elevation if first_node.bottom_elevation > 0 else None
            
            if group.outlet_row_index < 0 and group.row_indices:
                group.outlet_row_index = group.row_indices[-1]
                last_node = group.rows[-1]
                group.downstream_level = last_node.water_level if last_node.water_level > 0 else None
            
            # 提取平面段信息
            SiphonDataExtractor._extract_plan_segments(group)
            
            # 提取平面IP特征点（供三维空间合并使用）
            SiphonDataExtractor._extract_plan_feature_points(group)
            
            result.append(group)
        
        return result
    
    @staticmethod
    def _is_inverted_siphon(node: ChannelNode) -> bool:
        """
        判断节点是否为倒虹吸
        
        Args:
            node: 渠道节点
            
        Returns:
            是否为倒虹吸
        """
        if node.structure_type is None:
            return False
        
        # 检查枚举类型
        if node.structure_type == StructureType.INVERTED_SIPHON:
            return True
        
        # 兼容字符串比较
        struct_str = str(node.structure_type.value) if hasattr(node.structure_type, 'value') else str(node.structure_type)
        return "倒虹吸" in struct_str
    
    @staticmethod
    def _extract_plan_segments(group: SiphonGroup):
        """
        从倒虹吸分组的行数据中提取平面段信息
        
        平面段包括:
        - 相邻IP点之间的直管段（水平距离）
        - 每个中间IP点处的弯管段（水平转弯，有转弯半径和转角）
        
        平面总长度 = MC_出 - MC_进
        """
        rows = group.rows
        if len(rows) < 2:
            # 至少需要2个IP点（进口和出口）才能提取平面段
            group.plan_segments = []
            group.plan_total_length = 0.0
            return
        
        # 计算平面总长度 = MC_出 - MC_进
        mc_inlet = rows[0].station_MC
        mc_outlet = rows[-1].station_MC
        if mc_outlet > mc_inlet:
            group.plan_total_length = mc_outlet - mc_inlet
        else:
            group.plan_total_length = 0.0
        
        plan_segments = []
        
        for i in range(len(rows)):
            node = rows[i]
            
            # 1. 在每个IP点前添加直管段（从上一个IP到当前IP的直线距离）
            #    使用 straight_distance - 前后弯道占用的切线长 来获取纯直线长度
            #    但更简单的方式：利用相邻MC之差减去弯道弧长
            if i > 0:
                prev_node = rows[i - 1]
                # 两相邻IP之间的MC差值
                mc_diff = node.station_MC - prev_node.station_MC
                
                if mc_diff > 0:
                    # 减去前一个IP处弯道的后半切线长 + 当前IP处弯道的前半切线长
                    # 近似方法：直管长度 ≈ MC差 - 前IP弯道弧长/2 - 当前IP弯道弧长/2
                    # 更精确：使用 check_total_length（夹直线长度）如果可用
                    # 最简方式：先按 IP直线间距 - 前后切线长计算
                    prev_half_curve = prev_node.tangent_length if (i - 1) > 0 else 0
                    curr_half_curve = node.tangent_length if i < len(rows) - 1 else 0
                    straight_len = mc_diff - prev_half_curve - curr_half_curve
                    
                    # 容错：如果计算出负值，直接使用MC差值
                    if straight_len <= 0:
                        straight_len = mc_diff
                    
                    plan_segments.append({
                        "segment_type": "直管",
                        "direction": "平面",
                        "length": round(straight_len, 3),
                        "radius": 0.0,
                        "angle": 0.0,
                        "source_ip_index": node.ip_number,
                        "description": f"IP{prev_node.ip_number}→IP{node.ip_number}",
                    })
            
            # 2. 在中间IP点处添加弯管段（不在首尾IP处添加，因为首尾为进出口）
            if 0 < i < len(rows) - 1:
                if node.turn_angle > 0 and node.turn_radius > 0:
                    arc_len = node.arc_length if node.arc_length > 0 else 0.0
                    plan_segments.append({
                        "segment_type": "弯管",
                        "direction": "平面",
                        "length": round(arc_len, 3),
                        "radius": round(node.turn_radius, 3),
                        "angle": round(node.turn_angle, 3),
                        "source_ip_index": node.ip_number,
                        "description": f"IP{node.ip_number}处水平转弯",
                    })
        
        group.plan_segments = plan_segments
    
    @staticmethod
    def _extract_plan_feature_points(group: SiphonGroup):
        """
        从倒虹吸分组中提取平面IP特征点信息（供三维空间合并计算使用）
        
        每个IP点提取: MC桩号, X, Y, 方位角, 转弯半径, 转角
        """
        rows = group.rows
        if len(rows) < 2:
            group.plan_feature_points = []
            return
        
        feature_points = []
        for i, node in enumerate(rows):
            # 确定转弯类型
            turn_type = "无"
            if 0 < i < len(rows) - 1 and node.turn_angle > 0:
                turn_type = "圆弧" if node.turn_radius > 0 else "折线"
            
            fp = {
                "chainage": node.station_MC,
                "x": node.x,
                "y": node.y,
                "azimuth": node.azimuth,
                "turn_radius": node.turn_radius if (0 < i < len(rows) - 1) else 0.0,
                "turn_angle": node.turn_angle if (0 < i < len(rows) - 1) else 0.0,
                "turn_type": turn_type,
                "ip_index": node.ip_number,
            }
            feature_points.append(fp)
        
        group.plan_feature_points = feature_points
    
    @staticmethod
    def validate_siphons(groups: List[SiphonGroup]) -> tuple:
        """
        验证倒虹吸分组数据
        
        Args:
            groups: 倒虹吸分组列表
            
        Returns:
            (是否全部有效, 验证消息列表)
        """
        messages = []
        all_valid = True
        
        for group in groups:
            if not group.is_valid():
                all_valid = False
                msg = group.get_validation_message()
                if msg:
                    messages.append(msg)
        
        return all_valid, messages
    
    @staticmethod
    def get_siphon_names(nodes: List[ChannelNode]) -> List[str]:
        """
        快速获取所有倒虹吸的名称
        
        Args:
            nodes: 渠道节点列表
            
        Returns:
            倒虹吸名称列表（去重，保持顺序）
        """
        names = []
        seen = set()
        
        for node in nodes:
            if SiphonDataExtractor._is_inverted_siphon(node):
                name = node.name.strip()
                if name and name not in seen:
                    names.append(name)
                    seen.add(name)
        
        return names
