# -*- coding: utf-8 -*-
"""
主计算引擎

整合几何计算和水力计算，提供完整的水面线推求功能。
"""

from typing import List, Dict, Optional
import math
import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.geometry_calc import GeometryCalculator
from core.hydraulic_calc import HydraulicCalculator


class WaterProfileCalculator:
    """
    水面线推求主计算器
    
    整合几何计算和水力计算，提供完整的计算流程。
    """
    
    def __init__(self, settings: ProjectSettings):
        """
        初始化主计算器
        
        Args:
            settings: 项目设置
        """
        self.settings = settings
        self.geo_calc = GeometryCalculator(settings)
        self.hyd_calc = HydraulicCalculator(settings)
        
        # 断面参数库（从多渠段批量计算导入）
        self.section_params_library: Dict[str, Dict] = {}
    
    def import_section_params(self, params_dict: Dict[str, Dict]) -> None:
        """
        导入断面参数库
        
        Args:
            params_dict: 建筑物名称到断面参数的映射
                {"建筑物名称": {"底宽": x, "水深": y, ...}, ...}
        """
        self.section_params_library = params_dict.copy()
    
    def import_inverted_siphon_losses(self, losses: Dict[str, float]) -> None:
        """
        导入倒虹吸水头损失
        
        Args:
            losses: 倒虹吸名称到水头损失的映射
        """
        self.hyd_calc.import_inverted_siphon_losses(losses)
    
    def preprocess_nodes(self, nodes: List[ChannelNode]) -> None:
        """
        预处理节点
        
        包括：
        1. 分配IP编号
        2. 自动判断进出口标识（首尾为进出口，中间为普通断面）
        3. 应用断面参数库中的参数
        
        业务规则：同一建筑物可能出现多次（因有转弯/IP点），
        只有第1次出现为进口，最后1次出现为出口，中间都是普通断面。
        
        Args:
            nodes: 节点列表（原地修改）
        """
        # 第一轮遍历：统计每个特殊建筑物名称的总出现次数
        structure_total: Dict[str, int] = {}
        for node in nodes:
            if node.structure_type and self._is_special_structure_sv(node.structure_type):
                structure_total[node.name] = structure_total.get(node.name, 0) + 1
        
        # 第二轮遍历：分配IP编号和进出口标识
        structure_count: Dict[str, int] = {}  # 当前出现次数
        ip_counter = 0  # 独立的IP计数器，跳过渐变段和自动插入的明渠段
        
        for i, node in enumerate(nodes):
            # 1. 分配IP编号（从0开始，跳过渐变段和自动插入的明渠段）
            if getattr(node, 'is_transition', False) or getattr(node, 'is_auto_inserted_channel', False):
                pass  # 渐变段和自动插入的明渠段不分配IP编号
            else:
                node.ip_number = ip_counter
                ip_counter += 1
            
            # 2. 自动判断进出口标识
            if node.structure_type and self._is_special_structure_sv(node.structure_type):
                # 特殊建筑物需要标识进出口
                count = structure_count.get(node.name, 0) + 1
                structure_count[node.name] = count
                total = structure_total.get(node.name, 2)
                
                # 根据当前次数和总次数判断进出口
                # 第1次=进口，最后1次=出口，中间=普通断面
                in_out_result = InOutType.from_count(count, total)
                node.in_out = in_out_result[0]
                
                # 标记倒虹吸
                sv = node.structure_type.value if node.structure_type else ""
                if sv == "倒虹吸":
                    node.is_inverted_siphon = True
            else:
                # 普通明渠、分水闸等不标识进出口
                node.in_out = InOutType.NORMAL
            
            # 标记闸类型（分水闸/分水口/泄水闸/节制闸等）并设置默认过闸水头损失
            if node.structure_type and self._is_diversion_gate_sv(node.structure_type):
                node.is_diversion_gate = True
                # 若用户未手动设置过闸损失，则自动设为默认值0.1m
                if node.head_loss_gate == 0.0:
                    from config.constants import DEFAULT_GATE_HEAD_LOSS
                    node.head_loss_gate = DEFAULT_GATE_HEAD_LOSS
            
            # 3. 应用断面参数库中的参数（如果有）
            if node.name in self.section_params_library:
                # 合并参数，不覆盖已有的
                lib_params = self.section_params_library[node.name]
                for key, value in lib_params.items():
                    if key not in node.section_params:
                        node.section_params[key] = value
    
    def calculate_geometry(self, nodes: List[ChannelNode]) -> None:
        """
        执行几何计算
        
        Args:
            nodes: 节点列表（原地修改）
        """
        # 计算方位角、转角、切线长、弧长、距离
        self.geo_calc.calculate_all_geometry(nodes)
        
        # 计算桩号
        self.geo_calc.calculate_stations(nodes)
    
    def calculate_hydraulics(self, nodes: List[ChannelNode]) -> None:
        """
        执行水力计算
        
        Args:
            nodes: 节点列表（原地修改）
        """
        # 计算水面线
        self.hyd_calc.calculate_water_profile(nodes)
    
    def prepare_transitions(self, nodes: List[ChannelNode],
                            open_channel_callback=None) -> List[ChannelNode]:
        """
        预处理 + 插入渐变段/明渠段 + 几何计算（不含水力计算）
        
        用于在倒虹吸水力计算之前，先将渐变段和明渠段插入表格，
        并完成几何计算（方位角、桩号等），以便倒虹吸计算窗口
        可以准确获取上下游流速、断面参数等信息。
        
        步骤：
        1. 预处理节点（IP编号、进出口标识、断面参数）
        2. 识别并插入渐变段专用行和明渠段
        3. 几何计算（方位角、转角、桩号等）
        
        Args:
            nodes: 输入节点列表
            open_channel_callback: 可选的回调函数，用于获取明渠段参数
            
        Returns:
            插入渐变段后的节点列表（已完成几何计算）
        """
        if not nodes:
            return nodes
        
        # 1. 预处理
        self.preprocess_nodes(nodes)
        
        # 2. 识别并插入渐变段行和明渠段
        nodes = self.identify_and_insert_transitions(nodes, open_channel_callback)
        
        # 3. 几何计算
        self.calculate_geometry(nodes)
        
        return nodes
    
    def calculate_all(self, nodes: List[ChannelNode], 
                      open_channel_callback=None) -> List[ChannelNode]:
        """
        执行完整计算流程
        
        步骤：
        1. 预处理节点（IP编号、进出口标识、断面参数）
        2. 识别并插入渐变段专用行和明渠段（如果尚未插入）
        3. 几何计算（方位角、转角、桩号等）
        4. 水力计算（水位、流速、水损等）
        5. 渐变段水头损失计算
        
        Args:
            nodes: 输入节点列表
            open_channel_callback: 可选的回调函数，用于获取明渠段参数
                签名: callback(upstream_channel, available_length, prev_struct, next_struct) -> OpenChannelParams或None
            
        Returns:
            计算完成的节点列表（包含渐变段行）
        """
        if not nodes:
            return nodes
        
        # 检测渐变段是否已经插入（由 prepare_transitions 完成）
        has_transitions = any(getattr(node, 'is_transition', False) for node in nodes)
        
        # 1. 预处理
        self.preprocess_nodes(nodes)
        
        # 2. 识别并插入渐变段行和明渠段（仅在尚未插入时执行）
        if not has_transitions:
            nodes = self.identify_and_insert_transitions(nodes, open_channel_callback)
        
        # 3. 几何计算
        self.calculate_geometry(nodes)
        
        # 4. 水力计算（包含渐变段损失计入下游水位）
        self.calculate_hydraulics(nodes)
        
        # 5. 渐变段水头损失计算
        self.calculate_transition_losses(nodes)
        
        # 6. 更新总水头损失（使用真正的渐变段损失值替换预估值）
        self._update_total_head_loss(nodes)
        
        # 7. 使用已计算的渐变段损失重新递推水位
        self.hyd_calc.recalculate_water_levels_with_transition_losses(nodes)

        # 8. 应用公式10.3.6计算倒虹吸出口渐变段末端渠底高程
        self.hyd_calc.apply_siphon_outlet_elevation(nodes)
        
        # 9. 计算累计总水头损失
        self._calculate_cumulative_head_loss(nodes)
        
        return nodes
    
    def pre_scan_open_channels(self, nodes: List[ChannelNode]) -> List[Dict]:
        """
        预扫描需要插入明渠段的所有位置（不修改节点列表）
        
        用于在实际插入前确定总数量，以支持批量处理决策。
        注意：调用前需确保节点已预处理（preprocess_nodes）。
        
        Args:
            nodes: 预处理后的节点列表
            
        Returns:
            需要插入明渠段的位置信息列表，每项包含:
            - index: 节点索引
            - upstream_channel: 上游明渠参数（可能为None）
            - available_length: 可用长度
            - prev_struct/next_struct: 前/后建筑物类型
            - flow_section/flow: 流量段和流量
            - has_upstream: 是否有上游明渠可复制
        """
        gaps = []
        for i in range(len(nodes)):
            if i < len(nodes) - 1:
                current_node = nodes[i]
                next_node = nodes[i + 1]
                check_result = self._should_insert_open_channel(
                    current_node, next_node, nodes
                )
                if check_result['need_open_channel']:
                    upstream_channel = self._find_nearest_upstream_channel(nodes, i)
                    prev_struct = (current_node.structure_type.value 
                                   if current_node.structure_type else "")
                    next_struct = (next_node.structure_type.value 
                                   if next_node.structure_type else "")
                    prev_name = getattr(current_node, 'name', '') or ''
                    next_name = getattr(next_node, 'name', '') or ''
                    gaps.append({
                        'index': i,
                        'upstream_channel': upstream_channel,
                        'available_length': check_result['available_length'],
                        'prev_struct': prev_struct,
                        'next_struct': next_struct,
                        'prev_name': prev_name,
                        'next_name': next_name,
                        'flow_section': current_node.flow_section,
                        'flow': current_node.flow,
                        'has_upstream': upstream_channel is not None
                    })
        return gaps
    
    def _needs_transition(self, node1: ChannelNode, node2: ChannelNode) -> bool:
        """
        判断两个节点之间是否需要渐变段
        
        边界情况规则：
        1. 倒虹吸相邻行不应插入渐变段
        2. 完全相同的结构类型（如隧洞-圆形至隧洞-圆形）不应插入渐变段
           但不同子类型（如隧洞-圆形至隧洞-圆拱直墙型）需要渐变段
        3. 明渠→明渠应插入渐变段（梯形、矩形、圆形之间的转换）
           包括同一子类型但不同流量段的情况
        4. 如果前后两个建筑物的底宽/直径/半径相同，则不需要渐变段
        
        Args:
            node1: 前一节点（出口）
            node2: 后一节点（进口或普通断面）
            
        Returns:
            是否需要渐变段
        """
        # node1必须是出口，或者是明渠类型（明渠可能没有进出口标识）
        is_node1_mingqu = self._is_mingqu_type(node1.structure_type)
        is_node2_mingqu = self._is_mingqu_type(node2.structure_type)
        
        # 非明渠类型必须node1为出口
        io1 = node1.in_out.value if node1.in_out else ""
        io2 = node2.in_out.value if node2.in_out else ""
        if not is_node1_mingqu and io1 != "出":
            return False
        
        sv1 = node1.structure_type.value if node1.structure_type else ""
        sv2 = node2.structure_type.value if node2.structure_type else ""
        
        # 规则1: 倒虹吸内部行之间不需要渐变段
        # 但倒虹吸出口→其他结构、其他结构→倒虹吸进口需要渐变段（占位，跳过损失计算）
        if sv1 == "倒虹吸" and sv2 == "倒虹吸":
            return False
        if sv1 == "倒虹吸" and io1 != "出":
            return False
        if sv2 == "倒虹吸" and io2 != "进":
            return False
        
        # 规则1b: 分水闸/分水口不触发渐变段（点状结构，无断面变化）
        if self._is_diversion_gate_type(node1.structure_type):
            return False
        if self._is_diversion_gate_type(node2.structure_type):
            return False
        
        # 有效的结构类型（隧洞/渡槽/明渠/矩形暗涵/倒虹吸）
        valid_type_values = {
            "隧洞-圆形", "隧洞-圆拱直墙型",
            "隧洞-马蹄形Ⅰ型", "隧洞-马蹄形Ⅱ型",
            "渡槽-U形", "渡槽-矩形",
            "明渠-梯形", "明渠-矩形", "明渠-圆形",
            "矩形暗涵", "倒虹吸",
        }
        
        # 检查两个节点是否都是有效类型
        if sv1 not in valid_type_values:
            return False
        if sv2 not in valid_type_values:
            return False
        
        # 规则2: 完全相同的结构类型不需要渐变段
        # 例如：隧洞-圆形 → 隧洞-圆形 不需要
        # 但：隧洞-圆形 → 隧洞-圆拱直墙型 需要
        if sv1 == sv2:
            # 规则3的特例: 同一明渠子类型但不同流量段需要渐变段
            if is_node1_mingqu and is_node2_mingqu:
                if node1.flow_section != node2.flow_section:
                    # 不同流量段，继续检查规则4
                    pass
                else:
                    # 同一流量段、同一结构类型，不需要渐变段
                    return False
            else:
                # 非明渠的相同结构类型不需要渐变段
                return False
        
        # 规则5(新增): 隧洞/渡槽与明渠之间总是需要渐变段，跳过底宽检查
        is_node1_tunnel_aqueduct = self._is_tunnel_or_aqueduct(node1.structure_type)
        is_node2_tunnel_aqueduct = self._is_tunnel_or_aqueduct(node2.structure_type)
        
        if (is_node1_tunnel_aqueduct and is_node2_mingqu) or \
           (is_node1_mingqu and is_node2_tunnel_aqueduct):
            # 隧洞/渡槽 ↔ 明渠: 总是需要渐变段，直接返回True
            return True
        
        # 规则6(新增): 倒虹吸与明渠之间总是需要渐变段，跳过底宽检查
        is_node1_siphon = (sv1 == "倒虹吸")
        is_node2_siphon = (sv2 == "倒虹吸")
        
        if (is_node1_siphon and is_node2_mingqu) or \
           (is_node1_mingqu and is_node2_siphon):
            # 倒虹吸 ↔ 明渠: 总是需要渐变段，直接返回True
            return True
        
        # 规则4: 如果前后两个建筑物的特征尺寸相同，则不需要渐变段
        if self._has_same_section_size(node1, node2):
            return False
        
        return True
    
    def _is_mingqu_type(self, structure_type) -> bool:
        """判断是否为明渠类型（使用 .value 字符串比较）"""
        if structure_type is None:
            return False
        sv = structure_type.value if hasattr(structure_type, 'value') else str(structure_type)
        return sv in ("明渠-梯形", "明渠-矩形", "明渠-圆形")
    
    def _is_tunnel_or_aqueduct(self, structure_type) -> bool:
        """判断是否为隧洞或渡槽类型（使用 .value 字符串比较）"""
        if structure_type is None:
            return False
        sv = structure_type.value if hasattr(structure_type, 'value') else str(structure_type)
        return "隧洞" in sv or "渡槽" in sv
    
    def _is_diversion_gate_type(self, structure_type) -> bool:
        """判断是否为分水闸/分水口类型（使用 .value 字符串比较）"""
        if structure_type is None:
            return False
        sv = structure_type.value if hasattr(structure_type, 'value') else str(structure_type)
        return "闸" in sv or "分水" in sv
    
    def _is_special_structure_sv(self, structure_type) -> bool:
        """判断是否为特殊建筑物（需要进出口标识）（使用 .value 字符串比较）
        
        与原版 StructureType.get_special_structures 保持一致：
        隧洞、渡槽、倒虹吸需要进出口标识；矩形暗涵不需要。
        """
        if structure_type is None:
            return False
        sv = structure_type.value if hasattr(structure_type, 'value') else str(structure_type)
        special_keywords = ("隧洞", "渡槽", "倒虹吸")
        return any(kw in sv for kw in special_keywords)
    
    def _is_diversion_gate_sv(self, structure_type) -> bool:
        """判断是否为分水闸/分水口（使用 .value 字符串比较）"""
        return self._is_diversion_gate_type(structure_type)
    
    @staticmethod
    def _is_tunnel_or_aqueduct_str(structure_type_str: str) -> bool:
        """
        根据字符串判断是否为隧洞或渡槽类型
        
        Args:
            structure_type_str: 结构形式字符串
            
        Returns:
            是否为隧洞或渡槽
        """
        if not structure_type_str:
            return False
        return "隧洞" in structure_type_str or "渡槽" in structure_type_str
    
    def _has_same_section_size(self, node1: ChannelNode, node2: ChannelNode) -> bool:
        """
        判断两个节点的断面特征尺寸是否相同
        
        将底宽B、直径D、半径R统一换算为"特征宽度"后比较：
        - 直径D → 特征宽度 = D
        - 半径R → 特征宽度 = 2R（换算为直径）
        - 底宽B → 特征宽度 = B
        
        例如：渡槽U形半径1m 与 圆形隧洞直径2m 视为相同尺寸
        
        Args:
            node1: 前一节点
            node2: 后一节点
            
        Returns:
            断面尺寸是否相同
        """
        TOLERANCE = 1e-6  # 数值比较容差
        
        # 获取两个节点的特征宽度
        width1 = self._get_characteristic_width(node1)
        width2 = self._get_characteristic_width(node2)
        
        # 如果任一节点没有有效的特征宽度，则无法判断，认为不相同
        if width1 <= TOLERANCE or width2 <= TOLERANCE:
            return False
        
        # 比较特征宽度
        return abs(width1 - width2) < TOLERANCE
    
    def _get_characteristic_width(self, node: ChannelNode) -> float:
        """
        获取节点的特征宽度（统一换算）
        
        换算规则：
        - 直径D → 特征宽度 = D
        - 半径R → 特征宽度 = 2R（换算为直径）
        - 底宽B → 特征宽度 = B
        
        优先级：直径D > 半径R > 底宽B
        
        Args:
            node: 渠道节点
            
        Returns:
            特征宽度（m）
        """
        TOLERANCE = 1e-6
        params = node.section_params or {}
        
        # 获取直径
        D = params.get('D', params.get('直径', 0))
        if D > TOLERANCE:
            return D
        
        # 获取半径，换算为直径
        R = params.get('R_circle', params.get('半径', params.get('内半径', params.get('r', 0))))
        if R > TOLERANCE:
            return 2 * R  # 半径换算为直径
        
        # 获取底宽
        B = params.get('B', params.get('底宽', params.get('b', 0)))
        if B > TOLERANCE:
            return B
        
        return 0.0
    
    def _should_insert_open_channel(self, node1: ChannelNode, node2: ChannelNode, 
                                    all_nodes: List[ChannelNode] = None) -> Dict:
        """
        判断两个建筑物之间是否需要插入明渠段
        
        判断条件：
        1. node1必须是出口，node2必须是进口
        2. 隧洞/渡槽/倒虹吸都需要渐变段行；倒虹吸侧的渐变段为占位行
           （水头损失已含在倒虹吸水力计算中，通过 skip_loss 标记跳过计算）
        3. 里程差 > 渐变段之和 时需要插入明渠段
        
        Args:
            node1: 前一节点（应为出口）
            node2: 后一节点（应为进口）
            all_nodes: 所有节点列表（用于查找上游明渠）
            
        Returns:
            dict: {
                'need_open_channel': bool,  # 是否需要明渠段
                'need_transition_1': bool,  # 是否需要出口渐变段
                'need_transition_2': bool,  # 是否需要进口渐变段
                'skip_loss_transition_1': bool,  # 出口渐变段是否跳过损失计算（倒虹吸占位）
                'skip_loss_transition_2': bool,  # 进口渐变段是否跳过损失计算（倒虹吸占位）
                'transition_length_1': float,  # 出口渐变段长度估算
                'transition_length_2': float,  # 进口渐变段长度估算
                'distance': float,  # 里程差
                'available_length': float  # 可用于明渠的长度
            }
        """
        result = {
            'need_open_channel': False,
            'need_transition_1': False,
            'need_transition_2': False,
            'skip_loss_transition_1': False,
            'skip_loss_transition_2': False,
            'transition_length_1': 0.0,
            'transition_length_2': 0.0,
            'distance': 0.0,
            'available_length': 0.0
        }
        
        # 检查前置条件
        # node1必须是出口
        io1 = node1.in_out.value if node1.in_out else ""
        if io1 != "出":
            return result
        
        # node2必须是进口
        io2 = node2.in_out.value if node2.in_out else ""
        if io2 != "进":
            return result
        
        # 分水闸/分水口与任何建筑物之间不插入明渠段
        if self._is_diversion_gate_type(node1.structure_type):
            return result
        if self._is_diversion_gate_type(node2.structure_type):
            return result
        
        # 判断是否需要渐变段（隧洞/渡槽/倒虹吸都需要渐变段行）
        is_node1_tunnel_aqueduct = self._is_tunnel_or_aqueduct(node1.structure_type)
        is_node2_tunnel_aqueduct = self._is_tunnel_or_aqueduct(node2.structure_type)
        sv1 = node1.structure_type.value if node1.structure_type else ""
        sv2 = node2.structure_type.value if node2.structure_type else ""
        is_node1_siphon = (sv1 == "倒虹吸")
        is_node2_siphon = (sv2 == "倒虹吸")
        
        result['need_transition_1'] = is_node1_tunnel_aqueduct or is_node1_siphon
        result['need_transition_2'] = is_node2_tunnel_aqueduct or is_node2_siphon
        
        # 倒虹吸侧的渐变段为占位行，水头损失已包含在倒虹吸水力计算中
        result['skip_loss_transition_1'] = is_node1_siphon
        result['skip_loss_transition_2'] = is_node2_siphon
        
        # 估算渐变段长度
        if result['need_transition_1']:
            result['transition_length_1'] = self._estimate_transition_length(node1, "出口")
        if result['need_transition_2']:
            result['transition_length_2'] = self._estimate_transition_length(node2, "进口")
        
        total_transition_length = result['transition_length_1'] + result['transition_length_2']
        
        # 计算里程差
        result['distance'] = node2.station_MC - node1.station_MC
        
        # 可用于明渠的长度
        result['available_length'] = result['distance'] - total_transition_length
        
        # 判断是否需要插入明渠段
        result['need_open_channel'] = result['available_length'] > 0
        
        return result
    
    def _estimate_transition_length(self, node: ChannelNode, transition_type: str) -> float:
        """
        快速估算渐变段长度（用于判断是否需要插入明渠）
        
        Args:
            node: 建筑物节点
            transition_type: "进口"或"出口"
            
        Returns:
            估算的渐变段长度(m)
        """
        from config.constants import TRANSITION_LENGTH_COEFFICIENTS
        
        # 获取特征宽度
        B = self._get_characteristic_width(node)
        if B <= 0:
            B = 3.0  # 默认3m
        
        # 使用系数估算（假设明渠底宽为建筑物宽度的1.2倍）
        coefficient = TRANSITION_LENGTH_COEFFICIENTS.get(transition_type, 3.0)
        B_channel = B * 1.2
        
        L_basic = coefficient * abs(B_channel - B)
        
        # 应用约束条件
        h_design = node.water_depth if node.water_depth > 0 else 2.0
        struct_name = node.structure_type.value if node.structure_type else ""
        
        if "渡槽" in struct_name:
            L_min = 6 * h_design if transition_type == "进口" else 8 * h_design
            return max(L_basic, L_min)
        elif "隧洞" in struct_name:
            D = node.section_params.get("D", 3.0) if node.section_params else 3.0
            L_min = max(5 * h_design, 3 * D)
            return max(L_basic, L_min)
        elif "倒虹吸" in struct_name:
            # 规范10.2.4：进口取上游渠道设计水深的3~5倍（取大值5倍）
            #            出口取下游渠道设计水深的4~6倍（取大值6倍）
            # 注意：与隧洞不同，倒虹吸不使用洞径约束，仅用水深倍数
            L_min = 5 * h_design if transition_type == "进口" else 6 * h_design
            return max(L_basic, L_min)
        
        return max(L_basic, 10.0)  # 至少10m
    
    def _find_nearest_upstream_channel(self, nodes: List[ChannelNode], 
                                       current_index: int) -> Optional[Dict]:
        """
        查找上游最近的明渠节点
        
        Args:
            nodes: 节点列表
            current_index: 当前节点索引
            
        Returns:
            明渠参数字典或None
        """
        for i in range(current_index - 1, -1, -1):
            node = nodes[i]
            if self._is_mingqu_type(node.structure_type):
                # 找到明渠，提取参数
                # 圆形明渠用 D（直径）代替 B（底宽）
                if node.section_params:
                    bw = node.section_params.get("B", 0)
                    if bw == 0:
                        bw = node.section_params.get("D", 0)
                else:
                    bw = 0
                
                return {
                    'name': node.name,
                    'structure_type': node.structure_type.value if node.structure_type else "明渠-梯形",
                    'bottom_width': bw,
                    'water_depth': node.water_depth,
                    'side_slope': node.section_params.get("m", 0) if node.section_params else 0,
                    'roughness': node.roughness,
                    'slope_inv': 1.0 / node.slope_i if node.slope_i and node.slope_i > 0 else 3000,
                    'flow': node.flow,
                    'flow_section': node.flow_section,
                    'structure_height': node.structure_height,
                }
        return None
    
    def _create_open_channel_node(self, params, prev_node: ChannelNode, 
                                  next_node: ChannelNode) -> ChannelNode:
        """
        根据参数创建明渠段节点
        
        Args:
            params: OpenChannelParams对象
            prev_node: 前一节点
            next_node: 后一节点
            
        Returns:
            明渠节点
        """
        open_channel = ChannelNode()
        
        open_channel.name = params.name
        open_channel.structure_type = StructureType.from_string(params.structure_type)
        open_channel.flow_section = params.flow_section if params.flow_section else prev_node.flow_section
        
        # 设置断面参数（区分圆形和非圆形）
        is_circular = "圆形" in params.structure_type
        if is_circular:
            # 圆形明渠：bottom_width 实际存储的是直径 D
            open_channel.section_params = {
                "D": params.bottom_width,
                "m": 0
            }
        else:
            open_channel.section_params = {
                "B": params.bottom_width,
                "m": params.side_slope
            }
        open_channel.water_depth = params.water_depth
        open_channel.roughness = params.roughness
        open_channel.slope_i = 1.0 / params.slope_inv if params.slope_inv > 0 else 0
        
        # 使用params中的流量，如果没有则使用prev_node的流量
        open_channel.flow = params.flow if params.flow > 0 else prev_node.flow
        
        # 计算水力学参数（过水断面面积A、湿周X、水力半径R、流速v）
        h = params.water_depth
        if h > 0:
            if is_circular:
                # 圆形断面
                D = params.bottom_width
                if D > 0:
                    self.hyd_calc._fill_circular_section_params(open_channel, D, h)
            else:
                # 梯形/矩形断面
                b = params.bottom_width
                m = params.side_slope
                A = (b + m * h) * h
                P = b + 2 * h * math.sqrt(1 + m * m)
                R = A / P if P > 0 else 0.0
                open_channel.section_params['A'] = round(A, 3)
                open_channel.section_params['X'] = round(P, 3)
                open_channel.section_params['R'] = round(R, 3)
                
                # 计算流速 v = Q / A
                Q = open_channel.flow
                if Q > 0 and A > 0:
                    from config.constants import VELOCITY_PRECISION
                    open_channel.velocity = round(Q / A, VELOCITY_PRECISION)
        
        # 坐标插值
        open_channel.x = (prev_node.x + next_node.x) / 2
        open_channel.y = (prev_node.y + next_node.y) / 2
        
        # 标记为自动插入的明渠段（不分配IP编号）
        open_channel.is_auto_inserted_channel = True
        
        # 继承结构高度（用于计算渠顶高程 = 渠底高程 + 结构高度）
        sh = getattr(params, 'structure_height', 0.0) or 0.0
        if sh > 0:
            open_channel.structure_height = sh
        return open_channel
    
    def _create_merged_transition_node(self, node1: ChannelNode, 
                                       node2: ChannelNode, 
                                       distance: float,
                                       transition_type: str = "出口") -> ChannelNode:
        """
        创建合并的渐变段节点（当里程差不足以插入明渠时）
        
        Args:
            node1: 前一建筑物出口节点
            node2: 后一建筑物进口节点
            distance: 实际里程差
            transition_type: 渐变段类型，"进口"或"出口"（相对于特殊建筑物而言）
            
        Returns:
            合并的渐变段节点
        """
        transition = ChannelNode()
        
        transition.is_transition = True
        transition.transition_type = transition_type
        transition.name = "-"
        transition.structure_type = StructureType.TRANSITION
        transition.flow_section = node1.flow_section
        
        # 使用实际里程差作为长度
        transition.transition_length = distance
        transition.stat_length = distance
        
        # 继承参数
        transition.x = node1.x
        transition.y = node1.y
        transition.flow = node1.flow
        transition.roughness = node1.roughness if node1.roughness > 0 else self.settings.roughness
        
        # 根据渐变段类型选择对应的型式和ζ系数
        if transition_type == "进口":
            form_attr, zeta_attr = 'transition_inlet_form', 'transition_inlet_zeta'
        else:
            form_attr, zeta_attr = 'transition_outlet_form', 'transition_outlet_zeta'
        
        if hasattr(self.settings, form_attr) and getattr(self.settings, form_attr):
            transition.transition_form = getattr(self.settings, form_attr)
        else:
            transition.transition_form = "曲线形反弯扭曲面"
        
        if hasattr(self.settings, zeta_attr) and getattr(self.settings, zeta_attr) > 0:
            transition.transition_zeta = getattr(self.settings, zeta_attr)
        
        return transition
    
    def _create_inlet_transition_node(self, next_node: ChannelNode) -> ChannelNode:
        """
        创建进口渐变段节点
        
        Args:
            next_node: 后一节点（渐变段末端）
            
        Returns:
            进口渐变段节点
        """
        transition = ChannelNode()
        
        transition.is_transition = True
        transition.transition_type = "进口"
        transition.name = "-"
        transition.structure_type = StructureType.TRANSITION
        transition.flow_section = next_node.flow_section
        
        # 继承坐标（使用后一节点的坐标）
        transition.x = next_node.x
        transition.y = next_node.y
        
        # 继承水力参数
        transition.flow = next_node.flow
        transition.roughness = next_node.roughness if next_node.roughness > 0 else self.settings.roughness
        
        # 进口渐变段形式
        if hasattr(self.settings, 'transition_inlet_form') and self.settings.transition_inlet_form:
            transition.transition_form = self.settings.transition_inlet_form
        else:
            transition.transition_form = "曲线形反弯扭曲面"
        
        # 从设置中读取用户指定的ζ系数
        if hasattr(self.settings, 'transition_inlet_zeta') and self.settings.transition_inlet_zeta > 0:
            transition.transition_zeta = self.settings.transition_inlet_zeta
        
        return transition
    
    def _create_transition_node(self, prev_node: ChannelNode, 
                                next_node: ChannelNode,
                                transition_type: str = "出口") -> ChannelNode:
        """
        创建渐变段专用节点
        
        Args:
            prev_node: 前一节点（渐变段起始端）
            next_node: 后一节点（渐变段末端）
            transition_type: 渐变段类型，"进口"或"出口"（相对于特殊建筑物而言）
            
        Returns:
            渐变段节点
        """
        transition = ChannelNode()
        
        # 标记为渐变段
        transition.is_transition = True
        transition.transition_type = transition_type
        
        # 渐变段行：名称显示"-"，结构形式显示"渐变段"
        transition.name = "-"
        transition.structure_type = StructureType.TRANSITION
        
        transition.flow_section = prev_node.flow_section
        
        # 继承坐标（使用前一节点的坐标）
        transition.x = prev_node.x
        transition.y = prev_node.y
        
        # 继承水力参数
        transition.flow = prev_node.flow
        transition.roughness = prev_node.roughness if prev_node.roughness > 0 else self.settings.roughness
        
        # 根据渐变段类型选择对应的型式和ζ系数
        if transition_type == "进口":
            form_attr, zeta_attr = 'transition_inlet_form', 'transition_inlet_zeta'
        else:
            form_attr, zeta_attr = 'transition_outlet_form', 'transition_outlet_zeta'
        
        if hasattr(self.settings, form_attr) and getattr(self.settings, form_attr):
            transition.transition_form = getattr(self.settings, form_attr)
        else:
            transition.transition_form = "曲线形反弯扭曲面"
        
        if hasattr(self.settings, zeta_attr) and getattr(self.settings, zeta_attr) > 0:
            transition.transition_zeta = getattr(self.settings, zeta_attr)
        
        return transition
    
    def identify_and_insert_transitions(self, nodes: List[ChannelNode], 
                                        open_channel_callback=None) -> List[ChannelNode]:
        """
        识别并插入渐变段专用行和明渠段
        
        识别规则：
        1. 隧洞、渡槽、明渠两两过渡时存在渐变段
        2. 同一结构子类型（如隧洞-圆形→隧洞-圆形）不需要渐变段
        3. 不同结构子类型需要渐变段（如隧洞-圆形→隧洞-圆拱直墙型）
        4. 明渠不同子类型或不同流量段之间需要渐变段
        5. 倒虹吸侧也插入渐变段行（占位），但标记 transition_skip_loss=True
           跳过水头损失计算（其损失已包含在倒虹吸水力计算中）
        6. 如果前后断面特征尺寸相同则不需要渐变段
        7. 建筑物之间里程差>渐变段之和时，插入明渠段
        
        Args:
            nodes: 原始节点列表
            open_channel_callback: 可选的回调函数，用于获取明渠段参数
                签名: callback(upstream_channel, available_length, prev_struct, next_struct) -> OpenChannelParams或None
                
        Returns:
            插入渐变段行和明渠段后的新节点列表
        """
        new_nodes = []
        
        for i in range(len(nodes)):
            current_node = nodes[i]
            new_nodes.append(current_node)
            
            # 检查是否需要插入渐变段或明渠段
            if i < len(nodes) - 1:
                next_node = nodes[i + 1]
                
                # 首先检查是否需要插入明渠段（建筑物出口→进口的情况）
                check_result = self._should_insert_open_channel(current_node, next_node, nodes)
                
                if check_result['need_open_channel']:
                    # 需要插入明渠段（里程差 > 渐变段之和）
                    # 尝试插入3行：出口渐变段 → 明渠段 → 进口渐变段
                    
                    # 先尝试获取明渠段参数
                    upstream_channel = self._find_nearest_upstream_channel(nodes, i)
                    flow_section = current_node.flow_section
                    flow = current_node.flow
                    open_channel_params = None
                    
                    if open_channel_callback:
                        prev_struct = current_node.structure_type.value if current_node.structure_type else ""
                        next_struct = next_node.structure_type.value if next_node.structure_type else ""
                        open_channel_params = open_channel_callback(
                            upstream_channel, 
                            check_result['available_length'],
                            prev_struct,
                            next_struct,
                            flow_section,
                            flow
                        )
                    elif upstream_channel:
                        from models.data_models import OpenChannelParams
                        open_channel_params = OpenChannelParams(
                            name="-",
                            structure_type=upstream_channel.get('structure_type', '明渠-梯形'),
                            bottom_width=upstream_channel.get('bottom_width', 0),
                            water_depth=upstream_channel.get('water_depth', 0),
                            side_slope=upstream_channel.get('side_slope', 0),
                            roughness=upstream_channel.get('roughness', 0.014),
                            slope_inv=upstream_channel.get('slope_inv', 3000),
                            flow=upstream_channel.get('flow', flow),
                            flow_section=upstream_channel.get('flow_section', flow_section),
                            structure_height=upstream_channel.get('structure_height', 0.0),
                        )
                    
                    if open_channel_params:
                        # 明渠段参数获取成功，插入3行
                        # 渐变段的真实底坡 = 相邻明渠段的底坡
                        oc_slope_i = 1.0 / open_channel_params.slope_inv if open_channel_params.slope_inv > 0 else 0
                        # 1. 出口渐变段
                        if check_result['need_transition_1']:
                            transition_out = self._create_transition_node(current_node, next_node)
                            transition_out.slope_i = oc_slope_i
                            transition_out.transition_skip_loss = check_result.get('skip_loss_transition_1', False)
                            transition_out.stat_length = max(0.0, check_result.get('transition_length_1', 0.0))
                            new_nodes.append(transition_out)
                        # 2. 明渠段
                        open_channel = self._create_open_channel_node(open_channel_params, current_node, next_node)
                        open_channel.stat_length = max(0.0, check_result.get('available_length', 0.0))
                        new_nodes.append(open_channel)
                        # 3. 进口渐变段
                        if check_result['need_transition_2']:
                            transition_in = self._create_inlet_transition_node(next_node)
                            transition_in.slope_i = oc_slope_i
                            transition_in.transition_skip_loss = check_result.get('skip_loss_transition_2', False)
                            transition_in.stat_length = max(0.0, check_result.get('transition_length_2', 0.0))
                            new_nodes.append(transition_in)
                    else:
                        # 明渠段未能插入，回退为1行合并渐变段（避免出现两个连续渐变段）
                        if check_result['need_transition_1'] or check_result['need_transition_2']:
                            if check_result['distance'] > 0:
                                # 仅node2侧需要渐变段→进口，否则→出口
                                _mt = "进口" if check_result['need_transition_2'] and not check_result['need_transition_1'] else "出口"
                                merged_transition = self._create_merged_transition_node(
                                    current_node, next_node, check_result['distance'], _mt
                                )
                                merged_transition.transition_skip_loss = (
                                    check_result.get('skip_loss_transition_1', False) or
                                    check_result.get('skip_loss_transition_2', False)
                                )
                                # 从最近上游明渠继承底坡
                                if upstream_channel:
                                    us_sinv = upstream_channel.get('slope_inv', 0)
                                    merged_transition.slope_i = 1.0 / us_sinv if us_sinv > 0 else 0
                                new_nodes.append(merged_transition)
                
                elif check_result['need_transition_1'] or check_result['need_transition_2']:
                    # 不需要明渠段但需要渐变段（里程差 <= 渐变段之和）
                    # 只插入１行合并的渐变段
                    if check_result['distance'] > 0:
                        # 仅node2侧需要渐变段→进口，否则→出口
                        _mt = "进口" if check_result['need_transition_2'] and not check_result['need_transition_1'] else "出口"
                        merged_transition = self._create_merged_transition_node(
                            current_node, next_node, check_result['distance'], _mt
                        )
                        # 任一侧为倒虹吸时，合并行标记为跳过损失计算
                        merged_transition.transition_skip_loss = (
                            check_result.get('skip_loss_transition_1', False) or
                            check_result.get('skip_loss_transition_2', False)
                        )
                        # 从最近上游明渠继承底坡
                        us_ch = self._find_nearest_upstream_channel(nodes, i)
                        if us_ch:
                            us_sinv = us_ch.get('slope_inv', 0)
                            merged_transition.slope_i = 1.0 / us_sinv if us_sinv > 0 else 0
                        new_nodes.append(merged_transition)
                
                elif self._needs_transition(current_node, next_node):
                    # 普通渐变段（非建筑物出口→进口的情况）
                    # 确定渐变段类型：进口/出口相对于特殊建筑物而言
                    sv_curr = current_node.structure_type.value if current_node.structure_type else ""
                    sv_next = next_node.structure_type.value if next_node.structure_type else ""
                    if self._is_special_structure_sv(next_node.structure_type):
                        trans_type = "进口"  # 进入特殊建筑物
                    elif self._is_special_structure_sv(current_node.structure_type):
                        trans_type = "出口"  # 离开特殊建筑物
                    else:
                        trans_type = "出口"  # 明渠↔明渠默认出口系数（更保守）
                    transition_node = self._create_transition_node(current_node, next_node, trans_type)
                    # 继承上游节点的真实底坡
                    if current_node.slope_i and current_node.slope_i > 0:
                        transition_node.slope_i = current_node.slope_i
                    elif next_node.slope_i and next_node.slope_i > 0:
                        transition_node.slope_i = next_node.slope_i
                    # 倒虹吸相邻渐变段为占位行，跳过损失计算
                    if sv_curr == "倒虹吸" or sv_next == "倒虹吸":
                        transition_node.transition_skip_loss = True
                    new_nodes.append(transition_node)
        
        return new_nodes
    
    def calculate_transition_losses(self, nodes: List[ChannelNode]) -> None:
        """
        计算所有渐变段的水头损失
        
        Args:
            nodes: 节点列表（包含渐变段行）
        """
        for i, node in enumerate(nodes):
            if node.is_transition:
                # 查找前后节点（跳过其他渐变段）
                prev_node = None
                next_node = None
                
                # 向前查找非渐变段节点
                for j in range(i - 1, -1, -1):
                    if not nodes[j].is_transition:
                        prev_node = nodes[j]
                        break
                
                # 向后查找非渐变段节点
                for j in range(i + 1, len(nodes)):
                    if not nodes[j].is_transition:
                        next_node = nodes[j]
                        break
                
                if prev_node and next_node:
                    # 倒虹吸占位渐变段：只计算渐变段长度，不计算水头损失
                    # （水头损失已含在倒虹吸水力计算中）
                    if node.transition_skip_loss:
                        length = self.hyd_calc.calculate_transition_length(
                            node, prev_node, next_node, nodes
                        )
                        node.transition_length = length
                    else:
                        self.hyd_calc.calculate_transition_loss(
                            node, prev_node, next_node, nodes
                        )
    
    def _update_total_head_loss(self, nodes: List[ChannelNode]) -> None:
        """
        更新总水头损失（使用真正的渐变段损失值）
        
        在 calculate_transition_losses 之后调用，用真正计算的渐变段损失
        替换水面线推求时使用的预估值。
        
        Args:
            nodes: 节点列表（包含渐变段行）
        """
        for i, node in enumerate(nodes):
            # 只处理非渐变段节点
            if node.is_transition:
                continue
            
            # 获取各项损失
            h_bend = node.head_loss_bend or 0.0
            h_friction = node.head_loss_friction or 0.0
            h_local = node.head_loss_local or 0.0
            h_reserve = getattr(node, 'head_loss_reserve', 0.0) or 0.0
            h_gate = getattr(node, 'head_loss_gate', 0.0) or 0.0
            h_siphon = getattr(node, 'head_loss_siphon', 0.0) or 0.0
            
            # 重新计算总水头损失
            # 注：渐变段损失单独显示在渐变段行，不计入节点的总水头损失
            node.head_loss_total = h_bend + h_friction + h_local + h_reserve + h_gate + h_siphon

    def _calculate_cumulative_head_loss(self, nodes: List[ChannelNode]) -> None:
        """
        计算累计总水头损失
        
        从第一行开始逐行累加总水头损失。
        渐变段行的水损也计入累计，并显示累计值。
        
        Args:
            nodes: 节点列表（包含渐变段行）
        """
        cumulative = 0.0
        for node in nodes:
            if node.is_transition:
                # 渐变段行：累加渐变段水损
                cumulative += node.head_loss_transition or 0.0
            else:
                # 普通行：累加总水头损失
                cumulative += node.head_loss_total or 0.0
            node.head_loss_cumulative = cumulative

    def calculate_transition_losses_inline(self, nodes: List[ChannelNode]) -> None:
        """
        计算渐变段水头损失并内联累加到相邻节点（不插入专用行）
        
        渐变段损失将累加到前一节点（出口侧）的总水头损失中，
        详细计算信息保存在前一节点的 transition_calc_details 中供双击查看。
        
        Args:
            nodes: 节点列表（不含渐变段行）
        """
        for i in range(len(nodes) - 1):
            curr_node = nodes[i]
            next_node = nodes[i + 1]
            
            # 判断是否需要渐变段
            if self._needs_transition(curr_node, next_node):
                # 计算渐变段损失（内联方式，返回损失值和详情）
                loss, details = self.hyd_calc.calculate_transition_loss_inline(
                    curr_node, next_node, self.settings
                )
                
                # 将损失累加到前一节点（出口侧）的总水头损失
                curr_node.head_loss_total += loss
                
                # 保存详细计算信息供双击查看
                curr_node.transition_calc_details = details
    
    def validate_input(self, nodes: List[ChannelNode]) -> tuple:
        """
        验证输入数据
        
        Args:
            nodes: 节点列表
            
        Returns:
            (is_valid, error_messages): 验证结果和错误信息列表
        """
        errors = []
        
        # 验证项目设置
        is_valid, msg = self.settings.validate()
        if not is_valid:
            errors.append(f"项目设置错误: {msg}")
        
        # 验证节点数量
        if len(nodes) < 2:
            errors.append("至少需要2个节点才能进行计算")
        
        # 验证每个节点
        for i, node in enumerate(nodes):
            if not node.name:
                errors.append(f"第{i+1}行: 建筑物名称不能为空")
            if node.structure_type is None:
                errors.append(f"第{i+1}行: 请选择结构形式")
        
        return len(errors) == 0, errors
    
    def get_calculation_summary(self, nodes: List[ChannelNode]) -> Dict:
        """
        获取计算结果摘要
        
        Args:
            nodes: 计算完成的节点列表
            
        Returns:
            摘要字典
        """
        if not nodes:
            return {}
        
        return {
            "节点数量": len(nodes),
            "起点桩号": nodes[0].station_MC,
            "终点桩号": nodes[-1].station_MC,
            "总长度": nodes[-1].station_MC - nodes[0].station_MC,
            "起点水位": nodes[0].water_level,
            "终点水位": nodes[-1].water_level,
            "水位落差": nodes[0].water_level - nodes[-1].water_level,
        }
    
    def calculate_building_lengths(self, nodes: List[ChannelNode]) -> List[Dict]:
        """
        统计各个建筑物的总长度（命名建筑物边界 + 间隙填充法）
        
        算法：
        1. 沿节点序列扫描，识别所有命名建筑物的连续段落
           （name 不为 "-"、不为渐变段的节点）
        2. 每个命名建筑物的长度 = 末节点 station_MC - 首节点 station_MC
        3. 相邻两个命名建筑物之间的间隙（渐变段 + 连接明渠），
           作为"连接段"独立列出
        4. 间隙长度 = 下一个建筑物首节点 station_MC - 当前建筑物末节点 station_MC
        5. 渠道起点到第一个建筑物、最后一个建筑物到渠道终点之间的区段
           也作为连接段列出
        6. 所有段落首尾衔接、无重叠、无遗漏，保证 sum = total
        
        Args:
            nodes: 计算完成的节点列表（含渐变段行）
            
        Returns:
            有序列表，每项为字典：
            {
                'name': 建筑物名称（或连接段名称）,
                'structure_type': 结构形式字符串,
                'length': 总长度(m),
                'start_station': 起始桩号(m),
                'end_station': 终止桩号(m),
                'node_count': 节点数量,
                'note': 备注信息（可选）
            }
        """
        if not nodes:
            return []
        
        # 第一步：识别命名建筑物的连续段落
        # 只看命名建筑物节点（跳过渐变段和 name="-" 的自动插入行），
        # 相邻同名节点归为一段
        building_runs = []  # [{'name', 'structure_type', 'first_idx', 'last_idx', 'node_count'}, ...]
        
        for i, node in enumerate(nodes):
            # 跳过渐变段行
            if getattr(node, 'is_transition', False):
                continue
            # 跳过自动插入的明渠段（名称为"-"或空）
            if not node.name or node.name.strip() == "-":
                continue
            
            name = node.name.strip()
            if building_runs and building_runs[-1]['name'] == name:
                # 延续当前建筑物段落
                building_runs[-1]['last_idx'] = i
                building_runs[-1]['node_count'] += 1
            else:
                # 开始新建筑物段落
                building_runs.append({
                    'name': name,
                    'structure_type': node.get_structure_type_str(),
                    'first_idx': i,
                    'last_idx': i,
                    'node_count': 1,
                })
        
        # 第1.5步：合并被隧洞/渡槽内部分水闸拆分的段落
        # 规则：同名隧洞/渡槽 run 之间仅隔一个分水闸 run 时，
        #       合并为一个连续段落（隧洞进~隧洞出）
        merged_runs = []
        i = 0
        while i < len(building_runs):
            run = building_runs[i].copy()
            # 仅对隧洞/渡槽类型执行合并
            if self._is_tunnel_or_aqueduct_str(run['structure_type']):
                contained_gates = []
                while i + 2 <= len(building_runs) - 1:
                    gate_run = building_runs[i + 1]
                    next_same = building_runs[i + 2]
                    # 中间是分水闸/分水口 且 后面与当前同名
                    if (StructureType.is_diversion_gate_str(gate_run['structure_type'])
                            and next_same['name'] == run['name']):
                        contained_gates.append(gate_run['name'])
                        run['last_idx'] = next_same['last_idx']
                        run['node_count'] += gate_run['node_count'] + next_same['node_count']
                        i += 2  # 跳过分水闸 run 和下一个同名 run
                    else:
                        break
                if contained_gates:
                    run['note'] = f"含分水闸: {', '.join(contained_gates)}"
            merged_runs.append(run)
            i += 1
        building_runs = merged_runs
        
        # 无命名建筑物时，将整个渠道作为一个未命名段
        if not building_runs:
            total_len = nodes[-1].station_MC - nodes[0].station_MC
            if total_len > 0.001:
                return [{
                    'name': '(未命名渠段)',
                    'structure_type': '明渠',
                    'length': total_len,
                    'start_station': nodes[0].station_MC,
                    'end_station': nodes[-1].station_MC,
                    'node_count': len(nodes),
                }]
            return []
        
        channel_start_mc = nodes[0].station_MC
        channel_end_mc = nodes[-1].station_MC
        
        # 辅助函数：收集指定范围内的结构类型
        def _collect_gap_info(idx_start, idx_end):
            """收集 [idx_start, idx_end) 范围内的结构类型和节点数"""
            gap_types = set()
            gap_node_count = 0
            for k in range(idx_start, idx_end):
                n = nodes[k]
                gap_node_count += 1
                if getattr(n, 'is_transition', False):
                    gap_types.add('渐变段')
                elif n.structure_type:
                    gap_types.add(n.get_structure_type_str())
            return gap_types, gap_node_count
        
        def _decompose_gap(idx_start, idx_end, gap_start_mc, gap_end_mc, gap_name):
            """
            将间隙按节点类型分解为多行子条目（渐变段/明渠各自独立一行）
            
            扫描 nodes[idx_start:idx_end]，将连续相同类型的节点归为一段，
            使用 stat_length（如果有）作为长度，否则用桩号差。
            
            Args:
                idx_start, idx_end: 间隙节点范围 [idx_start, idx_end)
                gap_start_mc, gap_end_mc: 间隙起止桩号
                gap_name: 间隙名称（如"渠首连接段"）
            
            Returns:
                list of dict: 子条目列表
            """
            sub_entries = []
            current_mc = gap_start_mc
            
            # 将间隙节点按类型分组为连续段
            runs = []  # [{'type': str, 'nodes': [node, ...]}]
            for k in range(idx_start, idx_end):
                n = nodes[k]
                if getattr(n, 'is_transition', False):
                    t = '渐变段'
                elif n.structure_type:
                    t = n.get_structure_type_str()
                else:
                    t = ''
                if not t:
                    continue
                if runs and runs[-1]['type'] == t:
                    runs[-1]['nodes'].append(n)
                else:
                    runs.append({'type': t, 'nodes': [n]})
            
            # 为每段生成子条目
            for run_idx, run in enumerate(runs):
                # 优先使用 stat_length 累加
                stat_total = sum(
                    float(getattr(n, 'stat_length', 0.0) or 0.0)
                    for n in run['nodes']
                )
                if stat_total > 0.001:
                    seg_len = stat_total
                else:
                    # 兜底：按剩余总长度均分（不精确但不漏）
                    remaining = gap_end_mc - current_mc
                    remaining_runs = len(runs) - run_idx
                    seg_len = remaining / max(remaining_runs, 1) if remaining > 0 else 0.0
                
                if seg_len < 0.001:
                    continue
                
                sub_entries.append({
                    'name': gap_name,
                    'structure_type': run['type'],
                    'length': seg_len,
                    'start_station': current_mc,
                    'end_station': current_mc + seg_len,
                    'node_count': len(run['nodes']),
                })
                current_mc += seg_len
            
            # 处理剩余长度（stat_length 累计不足总长度时，分配给最后一个非渐变段条目）
            remaining = gap_end_mc - current_mc
            if remaining > 0.001 and sub_entries:
                # 找最后一个非渐变段条目分配剩余
                target = None
                for e in reversed(sub_entries):
                    if e['structure_type'] != '渐变段':
                        target = e
                        break
                if target is None:
                    target = sub_entries[-1]
                target['length'] += remaining
                target['end_station'] = target['start_station'] + target['length']
                # 后续条目的桩号也要顺延
                carry = 0.0
                for e in sub_entries:
                    if carry > 0:
                        e['start_station'] += carry
                        e['end_station'] += carry
                    if e is target:
                        carry = remaining
            
            # 兜底：如果没有子条目但间隙存在
            if not sub_entries:
                total_len = gap_end_mc - gap_start_mc
                if total_len > 0.001:
                    gap_types, gap_node_count = _collect_gap_info(idx_start, idx_end)
                    gap_type_str = '/'.join(sorted(gap_types)) if gap_types else '渠道段'
                    sub_entries.append({
                        'name': gap_name,
                        'structure_type': gap_type_str,
                        'length': total_len,
                        'start_station': gap_start_mc,
                        'end_station': gap_end_mc,
                        'node_count': max(1, idx_end - idx_start),
                    })
            
            return sub_entries
        
        # 第二步：计算每个建筑物长度 + 间隙（连接段）
        results = []
        
        # ===== 渠首连接段：渠道起点 → 第一个命名建筑物 =====
        first_run = building_runs[0]
        first_building_start = nodes[first_run['first_idx']].station_MC
        head_gap = first_building_start - channel_start_mc
        if head_gap > 0.001:
            head_subs = _decompose_gap(
                0, first_run['first_idx'],
                channel_start_mc, first_building_start,
                '渠首连接段'
            )
            results.extend(head_subs)
        
        # ===== 逐个建筑物 + 间隙 =====
        for j, run in enumerate(building_runs):
            start_mc = nodes[run['first_idx']].station_MC
            end_mc = nodes[run['last_idx']].station_MC
            length = end_mc - start_mc
            
            # 修复：负长度保护（数据异常时取绝对值并标记）
            note = run.get('note', '')  # 保留合并步骤中的备注（如"含分水闸: xxx"）
            if length < -0.001:
                extra = f'桩号逆序，原始值{length:.3f}m'
                note = f'{note}; {extra}' if note else extra
                length = abs(length)
            elif length < 0:
                length = 0.0
            
            # 修复：单节点非点状建筑物提示
            if run['node_count'] == 1 and length < 0.001:
                struct_str = run['structure_type']
                if '分水' not in struct_str:
                    extra = '仅1个节点，长度为0'
                    note = f'{note}; {extra}' if note else extra
            
            result_item = {
                'name': run['name'],
                'structure_type': run['structure_type'],
                'length': length,
                'start_station': start_mc,
                'end_station': end_mc,
                'node_count': run['node_count'],
            }
            if note:
                result_item['note'] = note
            
            results.append(result_item)
            
            # 检查与下一个建筑物之间是否存在间隙
            if j < len(building_runs) - 1:
                next_run = building_runs[j + 1]
                gap_start = end_mc
                gap_end = nodes[next_run['first_idx']].station_MC
                gap_length = gap_end - gap_start
                
                if gap_length > 0.001:
                    gap_name = f"连接段({run['name']}-{next_run['name']})"
                    gap_subs = _decompose_gap(
                        run['last_idx'] + 1, next_run['first_idx'],
                        gap_start, gap_end,
                        gap_name
                    )
                    results.extend(gap_subs)
        
        # ===== 渠尾连接段：最后一个命名建筑物 → 渠道终点 =====
        last_run = building_runs[-1]
        last_building_end = nodes[last_run['last_idx']].station_MC
        tail_gap = channel_end_mc - last_building_end
        if tail_gap > 0.001:
            tail_subs = _decompose_gap(
                last_run['last_idx'] + 1, len(nodes),
                last_building_end, channel_end_mc,
                '渠尾连接段'
            )
            results.extend(tail_subs)
        
        # ===== 校正：确保段落总长度精确等于桩号总长 =====
        # 微小间隙（≤0.001m）被阈值过滤后可能累积产生可见差值，
        # 将差值分配到最长段落（对相对精度影响最小）。
        if results:
            total_sum = sum(r['length'] for r in results)
            channel_total = channel_end_mc - channel_start_mc
            correction = channel_total - total_sum
            if abs(correction) > 1e-9 and abs(correction) <= 1.0:
                longest = max(results, key=lambda r: r['length'])
                longest['length'] += correction
                longest['end_station'] = longest['start_station'] + longest['length']
        
        return results
    
    @staticmethod
    def calculate_type_summary(building_lengths: List[Dict]) -> List[Dict]:
        """
        按结构类型汇总累计长度
        
        遍历建筑物长度列表，按 structure_type 分组统计数量和累计长度。
        连接段（名称含"连接"）不参与汇总。
        
        Args:
            building_lengths: calculate_building_lengths() 返回的列表
            
        Returns:
            有序列表，每项为字典：
            {
                'structure_type': 结构类型字符串,
                'count': 该类型的建筑物数量,
                'total_length': 累计长度(m)
            }
        """
        type_map = {}  # {structure_type: {'count': int, 'total_length': float}}
        for item in building_lengths:
            name = item.get('name', '')
            st = item.get('structure_type', '')
            # 跳过连接段和无结构类型的条目
            if not st or '连接' in name:
                continue
            length = item.get('length', 0.0)
            if st not in type_map:
                type_map[st] = {'count': 0, 'total_length': 0.0}
            type_map[st]['count'] += 1
            type_map[st]['total_length'] += length
        
        return [
            {
                'structure_type': k,
                'count': v['count'],
                'total_length': v['total_length'],
            }
            for k, v in sorted(type_map.items())
        ]
    
    @staticmethod
    def calculate_comprehensive_type_summary(nodes: List['ChannelNode']) -> List[Dict]:
        """
        从节点列表直接扫描，按结构类型综合统计个数和总长度。
        
        与 calculate_type_summary() 不同，此方法：
        - 包含渐变段（独立统计，不归入明渠）
        - 包含自动插入的明渠/矩形暗涵段（name="-" 的节点）
        - 包含隧洞内部的分水口/分水闸（单独计数）
        - 每种结构类型都有独立的统计行
        
        算法：
        1. 遍历所有节点，确定每个节点的有效类型
        2. 按相邻节点间距逐段统计长度：每对 (i, i+1) 的距离归入
           节点 i 的有效类型，保证总和 = 桩号总长，无遗漏无重叠
        3. 将连续同类型节点序列视为 1 个建筑物（用于计数）
        4. 被分水口/分水闸分隔的同类型隧洞/渡槽段合并为 1 个
           （仅影响个数，不影响长度归属）
        
        Args:
            nodes: 计算完成的节点列表（含渐变段行）
            
        Returns:
            有序列表，每项为字典：
            {
                'structure_type': 结构类型字符串,
                'count': 该类型的建筑物/段落数量,
                'total_length': 累计长度(m)
            }
        """
        if not nodes or len(nodes) < 2:
            return []
        
        # ── 第1步：确定每个节点的有效类型 ──
        def _get_effective_type(node) -> str:
            if getattr(node, 'is_transition', False):
                return "渐变段"
            if node.structure_type:
                return node.get_structure_type_str()
            return ""
        
        eff_types = [_get_effective_type(n) for n in nodes]
        
        # ── 第2步：按相邻节点间距逐段统计长度 ──
        # 每对相邻节点 (i, i+1) 的距离归入节点 i 的有效类型，
        # 这保证所有段距之和 = 桩号总长，无遗漏无重叠。
        type_length_map = {}  # {type_str: total_length}
        for i in range(len(nodes) - 1):
            t = eff_types[i]
            if not t:
                # 无类型节点：用下一节点的类型兜底
                t = eff_types[i + 1] if (i + 1 < len(eff_types)) else ""
            # 分水闸/分水口是点状结构，不应有长度，将其段距归入下一节点的类型
            if t and StructureType.is_diversion_gate_str(t):
                t = eff_types[i + 1] if (i + 1 < len(eff_types)) else ""
            if not t:
                continue
            seg_len = nodes[i + 1].station_MC - nodes[i].station_MC
            if seg_len > 0:
                type_length_map[t] = type_length_map.get(t, 0.0) + seg_len
        
        # ── 第5步：将连续同类型节点序列分割为段落（用于计数） ──
        # 每个段落 = 一段连续相同有效类型的节点序列
        segments = []  # [{'type': str, 'start_idx': int, 'end_idx': int}, ...]
        prev_type = None
        seg_start = 0
        
        for i, t in enumerate(eff_types):
            if not t:
                # 无类型节点：结束当前段
                if prev_type is not None:
                    segments.append({'type': prev_type, 'start_idx': seg_start, 'end_idx': i - 1})
                    prev_type = None
                continue
            if t != prev_type:
                # 类型变化：结束上一段，开始新段
                if prev_type is not None:
                    segments.append({'type': prev_type, 'start_idx': seg_start, 'end_idx': i - 1})
                prev_type = t
                seg_start = i
            # 相同类型：继续延伸当前段
        
        # 收尾：最后一个段
        if prev_type is not None:
            segments.append({'type': prev_type, 'start_idx': seg_start, 'end_idx': len(nodes) - 1})
        
        # ── 第6步：合并被分水口/分水闸分隔的同类型隧洞/渡槽段（仅影响个数） ──
        # 注意：分水口/分水闸段仍然保留在列表中（以便单独计数），
        #       仅将前后的同类型隧洞/渡槽段合并为一个。
        merged_segments = []
        i = 0
        while i < len(segments):
            seg = segments[i].copy()
            seg_type = seg['type']
            # 仅对隧洞/渡槽类型尝试合并
            if "隧洞" in seg_type or "渡槽" in seg_type:
                while i + 2 < len(segments):
                    gate_seg = segments[i + 1]
                    next_seg = segments[i + 2]
                    # 中间是分水口/分水闸 且 后面与当前同类型
                    if ("分水" in gate_seg['type'] and next_seg['type'] == seg_type):
                        # 先将分水口/分水闸段加入列表（保留其独立计数）
                        merged_segments.append(gate_seg.copy())
                        # 合并：扩展当前隧洞/渡槽段到后一个同类型段的末尾
                        seg['end_idx'] = next_seg['end_idx']
                        i += 2  # 跳过分水闸段和下一个同类型段
                    else:
                        break
            merged_segments.append(seg)
            i += 1
        
        # ── 第7步：按类型统计个数 ──
        type_count_map = {}  # {type_str: count}
        for seg in merged_segments:
            t = seg['type']
            type_count_map[t] = type_count_map.get(t, 0) + 1
        
        # ── 第8步：合并个数和长度，生成最终结果 ──
        all_types = set(type_length_map.keys()) | set(type_count_map.keys())
        
        result = []
        for t in sorted(all_types):
            if not t:
                continue
            result.append({
                'structure_type': t,
                'count': type_count_map.get(t, 0),
                'total_length': type_length_map.get(t, 0.0),
            })
        
        return result

    @staticmethod
    def validate_type_summary_total(nodes: List['ChannelNode'],
                                    type_summary: Optional[List[Dict]] = None,
                                    tolerance: float = 0.001) -> Dict[str, float]:
        """
        小型自检：校核结构类型汇总长度之和是否等于桩号总长。
        
        Args:
            nodes: 计算完成的节点列表（含渐变段行）
            type_summary: 结构类型汇总列表（可选，缺省则自动计算）
            tolerance: 允许误差（m）
        
        Returns:
            dict:
            {
                'ok': 1.0 或 0.0,
                'channel_total': 桩号总长,
                'summary_total': 汇总长度之和,
                'diff': 差值绝对值
            }
        """
        if not nodes or len(nodes) < 2:
            return {'ok': 1.0, 'channel_total': 0.0, 'summary_total': 0.0, 'diff': 0.0}
        
        if type_summary is None:
            type_summary = WaterProfileCalculator.calculate_comprehensive_type_summary(nodes)
        
        channel_total = nodes[-1].station_MC - nodes[0].station_MC
        summary_total = 0.0
        for item in type_summary:
            try:
                summary_total += float(item.get('total_length', 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
        
        diff = abs(summary_total - channel_total)
        ok = 1.0 if diff <= tolerance else 0.0
        return {
            'ok': ok,
            'channel_total': channel_total,
            'summary_total': summary_total,
            'diff': diff
        }