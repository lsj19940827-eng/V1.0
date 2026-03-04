# -*- coding: utf-8 -*-
"""
有压管道数据提取模块

从推求水面线表格数据中识别和提取有压管道分组信息。
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.data_models import ChannelNode
from models.enums import StructureType, InOutType


@dataclass
class PressurePipeGroup:
    """
    有压管道分组数据
    
    表示一个完整的有压管道，包含进口和出口节点的数据。
    """
    name: str                                   # 建筑物名称（如"有压管道1"）
    inlet_node: Optional[ChannelNode] = None    # 进口节点
    outlet_node: Optional[ChannelNode] = None   # 出口节点
    inlet_row_index: int = -1                   # 进口节点在原列表中的索引
    outlet_row_index: int = -1                  # 出口节点在原列表中的索引
    diameter_D: float = 0.0                     # 管径 (m)
    roughness: float = 0.014                    # 糙率
    flow: float = 0.0                           # 流量 (m³/s)
    
    def is_valid(self) -> bool:
        """检查有压管道数据是否有效"""
        return (
            self.name and
            self.inlet_node is not None and
            self.outlet_node is not None and
            self.inlet_row_index >= 0 and
            self.outlet_row_index >= 0 and
            self.diameter_D > 0
        )
    
    def get_validation_message(self) -> str:
        """获取验证信息"""
        issues = []
        if not self.name:
            issues.append("缺少建筑物名称")
        if self.inlet_node is None:
            issues.append("未识别到进口节点")
        if self.outlet_node is None:
            issues.append("未识别到出口节点")
        if self.diameter_D <= 0:
            issues.append("管径无效")
        if self.flow <= 0:
            issues.append("流量无效")
        
        if issues:
            return f"{self.name}: " + ", ".join(issues)
        return ""


class PressurePipeDataExtractor:
    """
    有压管道数据提取器
    
    从渠道节点列表中识别和提取有压管道分组。
    """
    
    @staticmethod
    def extract_pressure_pipe_groups(nodes: List[ChannelNode]) -> List[PressurePipeGroup]:
        """
        从节点列表中识别所有有压管道并按建筑物名称分组
        
        识别规则：
        1. structure_type 包含"有压管道"文本
        2. 按 name（建筑物名称）分组，相同名称的进出口属于同一有压管道
        3. 识别进出口（in_out == INLET/OUTLET）
        4. 提取管径、糙率、流量等参数
        5. 验证每组有唯一的进口和出口
        6. 对于没有名称的节点，每个进出口对分配一个唯一的默认名称
        
        Args:
            nodes: 渠道节点列表
            
        Returns:
            有压管道分组列表，按在表格中出现的顺序排列
        """
        if not nodes:
            return []
        
        # 按名称分组，同时记录索引
        groups_dict: Dict[str, PressurePipeGroup] = {}
        group_order: List[str] = []  # 记录出现顺序
        unnamed_counter = 1  # 用于生成默认名称
        unnamed_pending_inlet = None  # 待配对的无名进口节点
        unnamed_pending_inlet_idx = -1
        
        for idx, node in enumerate(nodes):
            # 检查是否为有压管道
            if not PressurePipeDataExtractor._is_pressure_pipe(node):
                continue
            
            # 获取建筑物名称
            name = node.name.strip()
            
            # 处理无名节点：为每个进出口对分配唯一的默认名称
            if not name:
                if node.in_out == InOutType.INLET:
                    # 保存待配对的进口节点
                    unnamed_pending_inlet = node
                    unnamed_pending_inlet_idx = idx
                    continue
                elif node.in_out == InOutType.OUTLET and unnamed_pending_inlet is not None:
                    # 找到配对的出口节点，分配默认名称
                    name = f"有压管道{unnamed_counter}"
                    unnamed_counter += 1
                    
                    # 创建分组
                    groups_dict[name] = PressurePipeGroup(name=name)
                    group_order.append(name)
                    
                    group = groups_dict[name]
                    group.inlet_node = unnamed_pending_inlet
                    group.inlet_row_index = unnamed_pending_inlet_idx
                    group.outlet_node = node
                    group.outlet_row_index = idx
                    
                    # 清空待配对节点
                    unnamed_pending_inlet = None
                    unnamed_pending_inlet_idx = -1
                    
                    # 提取参数
                    source_node = group.inlet_node
                    sp = source_node.section_params or {}
                    group.diameter_D = sp.get("D", 0.0)
                    group.roughness = source_node.roughness if source_node.roughness > 0 else 0.014
                    group.flow = source_node.flow
                    
                    continue
                else:
                    # 单独的无名出口节点，分配默认名称
                    name = f"有压管道{unnamed_counter}"
                    unnamed_counter += 1
            
            # 创建或获取分组（有名称的节点）
            if name not in groups_dict:
                groups_dict[name] = PressurePipeGroup(name=name)
                group_order.append(name)
            
            group = groups_dict[name]
            
            # 识别进出口
            if node.in_out == InOutType.INLET:
                group.inlet_node = node
                group.inlet_row_index = idx
            elif node.in_out == InOutType.OUTLET:
                group.outlet_node = node
                group.outlet_row_index = idx
        
        # 处理剩余的待配对进口节点
        if unnamed_pending_inlet is not None:
            name = f"有压管道{unnamed_counter}"
            groups_dict[name] = PressurePipeGroup(name=name)
            group_order.append(name)
            
            group = groups_dict[name]
            group.inlet_node = unnamed_pending_inlet
            group.inlet_row_index = unnamed_pending_inlet_idx
        
        # 处理每个分组，提取参数（仅处理有名称的分组，无名分组已在上面处理）
        result = []
        for name in group_order:
            group = groups_dict[name]
            
            # 如果参数还未提取（有名称的节点），则提取
            if group.diameter_D == 0.0:
                # 提取管径、糙率、流量（优先从进口节点提取）
                source_node = group.inlet_node if group.inlet_node else group.outlet_node
                if source_node:
                    # 提取管径 D
                    sp = source_node.section_params or {}
                    group.diameter_D = sp.get("D", 0.0)
                    
                    # 提取糙率
                    group.roughness = source_node.roughness if source_node.roughness > 0 else 0.014
                    
                    # 提取流量
                    group.flow = source_node.flow
            
            result.append(group)
        
        return result
    
    @staticmethod
    def _is_pressure_pipe(node: ChannelNode) -> bool:
        """
        判断节点是否为有压管道
        
        Args:
            node: 渠道节点
            
        Returns:
            是否为有压管道
        """
        if node.structure_type is None:
            return False
        
        # 检查结构形式字符串是否包含"有压管道"
        struct_str = str(node.structure_type.value) if hasattr(node.structure_type, 'value') else str(node.structure_type)
        return "有压管道" in struct_str
    
    @staticmethod
    def validate_pressure_pipe_groups(groups: List[PressurePipeGroup]) -> tuple:
        """
        验证有压管道分组数据
        
        Args:
            groups: 有压管道分组列表
            
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
    def get_pressure_pipe_names(nodes: List[ChannelNode]) -> List[str]:
        """
        快速获取所有有压管道的名称
        
        Args:
            nodes: 渠道节点列表
            
        Returns:
            有压管道名称列表（去重，保持顺序）
        """
        names = []
        seen = set()
        unnamed_counter = 1
        
        for node in nodes:
            if PressurePipeDataExtractor._is_pressure_pipe(node):
                name = node.name.strip()
                if not name:
                    name = f"有压管道{unnamed_counter}"
                    unnamed_counter += 1
                if name and name not in seen:
                    names.append(name)
                    seen.add(name)
        
        return names


def validate_pressure_pipe_node(node: ChannelNode, row_index: int) -> tuple:
    """
    验证单个有压管道节点的数据
    
    验证规则：
    1. 管径 D > 0
    2. 糙率 > 0
    3. 流量 > 0
    4. 进出口标识存在（INLET 或 OUTLET）
    
    Args:
        node: 有压管道节点
        row_index: 节点在表格中的行号（用于错误报告）
        
    Returns:
        (是否有效, 错误消息列表)
    """
    errors = []
    
    # 验证管径 D
    section_params = node.section_params or {}
    diameter_D = section_params.get("D", 0.0)
    
    if diameter_D <= 0:
        if diameter_D == 0:
            errors.append(f"第 {row_index} 行：缺少管径 D 值")
        else:
            errors.append(f"第 {row_index} 行：管径 D = {diameter_D} 无效（必须 > 0）")
    
    # 验证糙率
    roughness = node.roughness if node.roughness else 0.0
    if roughness <= 0:
        errors.append(f"第 {row_index} 行：糙率 n = {roughness} 无效（必须 > 0）")
    
    # 验证流量
    flow = node.flow if node.flow else 0.0
    if flow <= 0:
        errors.append(f"第 {row_index} 行：流量 Q = {flow} 无效（必须 > 0）")
    
    # 验证进出口标识
    if node.in_out not in [InOutType.INLET, InOutType.OUTLET]:
        errors.append(f"第 {row_index} 行：缺少进出口标识（应为'进'或'出'）")
    
    is_valid = len(errors) == 0
    return is_valid, errors


def validate_pressure_pipe_group(group: PressurePipeGroup) -> tuple:
    """
    验证有压管道分组的数据
    
    验证规则：
    1. 有进口节点
    2. 有出口节点
    3. 管径 D > 0
    4. 糙率 > 0
    5. 流量 > 0
    6. 进口里程 < 出口里程
    
    Args:
        group: 有压管道分组
        
    Returns:
        (是否有效, 错误消息列表)
    """
    errors = []
    
    # 验证进出口节点存在
    if group.inlet_node is None:
        errors.append(f"'{group.name}'：只有出口，缺少进口")
    
    if group.outlet_node is None:
        errors.append(f"'{group.name}'：只有进口，缺少出口")
    
    # 如果缺少进出口节点，直接返回
    if group.inlet_node is None or group.outlet_node is None:
        return False, errors
    
    # 验证管径
    if group.diameter_D <= 0:
        errors.append(f"'{group.name}'：管径 D = {group.diameter_D} 无效（必须 > 0）")
    
    # 验证糙率
    if group.roughness <= 0:
        errors.append(f"'{group.name}'：糙率 n = {group.roughness} 无效（必须 > 0）")
    
    # 验证流量
    if group.flow <= 0:
        errors.append(f"'{group.name}'：流量 Q = {group.flow} 无效（必须 > 0）")
    
    # 验证里程顺序
    inlet_station = group.inlet_node.station_MC if group.inlet_node.station_MC else 0.0
    outlet_station = group.outlet_node.station_MC if group.outlet_node.station_MC else 0.0
    
    if inlet_station >= outlet_station:
        errors.append(
            f"'{group.name}'：进口里程 ({inlet_station:.2f}) "
            f"大于等于出口里程 ({outlet_station:.2f})，里程顺序错误"
        )
    
    is_valid = len(errors) == 0
    return is_valid, errors
