# -*- coding: utf-8 -*-
"""
主计算引擎

整合几何计算和水力计算，提供完整的水面线推求功能。
"""

from typing import List, Dict, Optional
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
            if node.structure_type and StructureType.is_special_structure(node.structure_type):
                structure_total[node.name] = structure_total.get(node.name, 0) + 1
        
        # 第二轮遍历：分配IP编号和进出口标识
        structure_count: Dict[str, int] = {}  # 当前出现次数
        
        for i, node in enumerate(nodes):
            # 1. 分配IP编号（从0开始）
            node.ip_number = i
            
            # 2. 自动判断进出口标识
            if node.structure_type and StructureType.is_special_structure(node.structure_type):
                # 特殊建筑物需要标识进出口
                count = structure_count.get(node.name, 0) + 1
                structure_count[node.name] = count
                total = structure_total.get(node.name, 2)
                
                # 根据当前次数和总次数判断进出口
                # 第1次=进口，最后1次=出口，中间=普通断面
                in_out_result = InOutType.from_count(count, total)
                node.in_out = in_out_result[0]
                
                # 标记倒虹吸
                if node.structure_type == StructureType.INVERTED_SIPHON:
                    node.is_inverted_siphon = True
            else:
                # 普通明渠、分水闸等不标识进出口
                node.in_out = InOutType.NORMAL
            
            # 标记分水闸/分水口并设置默认过闸水头损失
            if node.structure_type and StructureType.is_diversion_gate(node.structure_type):
                node.is_diversion_gate = True
                # 若用户未手动设置过闸损失，则自动设为默认值0.2m
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
    
    def calculate_all(self, nodes: List[ChannelNode], 
                      open_channel_callback=None) -> List[ChannelNode]:
        """
        执行完整计算流程
        
        步骤：
        1. 预处理节点（IP编号、进出口标识、断面参数）
        2. 识别并插入渐变段专用行和明渠段
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
        
        # 1. 预处理
        self.preprocess_nodes(nodes)
        
        # 2. 识别并插入渐变段行和明渠段
        nodes = self.identify_and_insert_transitions(nodes, open_channel_callback)
        
        # 3. 几何计算
        self.calculate_geometry(nodes)
        
        # 4. 水力计算（包含渐变段损失计入下游水位）
        self.calculate_hydraulics(nodes)
        
        # 5. 渐变段水头损失计算
        self.calculate_transition_losses(nodes)
        
        # 6. 更新总水头损失（使用真正的渐变段损失值替换预估值）
        self._update_total_head_loss(nodes)
        
        # 7. 计算累计总水头损失
        self._calculate_cumulative_head_loss(nodes)
        
        return nodes
    
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
        if not is_node1_mingqu and node1.in_out != InOutType.OUTLET:
            return False
        
        # 规则1: 倒虹吸不需要渐变段
        if node1.structure_type == StructureType.INVERTED_SIPHON:
            return False
        if node2.structure_type == StructureType.INVERTED_SIPHON:
            return False
        
        # 规则1b: 分水闸/分水口不触发渐变段（点状结构，无断面变化）
        if self._is_diversion_gate_type(node1.structure_type):
            return False
        if self._is_diversion_gate_type(node2.structure_type):
            return False
        
        # 有效的结构类型（隧洞/渡槽/明渠/矩形暗涵）
        valid_types = {
            StructureType.TUNNEL_CIRCULAR, 
            StructureType.TUNNEL_ARCH,
            StructureType.TUNNEL_HORSESHOE_1, 
            StructureType.TUNNEL_HORSESHOE_2,
            StructureType.AQUEDUCT_U, 
            StructureType.AQUEDUCT_RECT,
            StructureType.MINGQU_TRAPEZOIDAL, 
            StructureType.MINGQU_RECTANGULAR,
            StructureType.MINGQU_CIRCULAR,
            StructureType.RECT_CULVERT,
        }
        
        # 检查两个节点是否都是有效类型
        if node1.structure_type not in valid_types:
            return False
        if node2.structure_type not in valid_types:
            return False
        
        # 规则2: 完全相同的结构类型不需要渐变段
        # 例如：隧洞-圆形 → 隧洞-圆形 不需要
        # 但：隧洞-圆形 → 隧洞-圆拱直墙型 需要
        if node1.structure_type == node2.structure_type:
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
        
        # 规则4: 如果前后两个建筑物的特征尺寸相同，则不需要渐变段
        if self._has_same_section_size(node1, node2):
            return False
        
        return True
    
    def _is_mingqu_type(self, structure_type: Optional[StructureType]) -> bool:
        """
        判断是否为明渠类型
        
        Args:
            structure_type: 结构类型
            
        Returns:
            是否为明渠
        """
        if structure_type is None:
            return False
        mingqu_types = {
            StructureType.MINGQU_TRAPEZOIDAL,
            StructureType.MINGQU_RECTANGULAR,
            StructureType.MINGQU_CIRCULAR,
        }
        return structure_type in mingqu_types
    
    def _is_tunnel_or_aqueduct(self, structure_type: Optional[StructureType]) -> bool:
        """
        判断是否为隧洞或渡槽类型
        
        Args:
            structure_type: 结构类型
            
        Returns:
            是否为隧洞或渡槽
        """
        if structure_type is None:
            return False
        tunnel_aqueduct_types = {
            StructureType.TUNNEL_CIRCULAR,
            StructureType.TUNNEL_ARCH,
            StructureType.TUNNEL_HORSESHOE_1,
            StructureType.TUNNEL_HORSESHOE_2,
            StructureType.AQUEDUCT_U,
            StructureType.AQUEDUCT_RECT,
        }
        return structure_type in tunnel_aqueduct_types
    
    def _is_diversion_gate_type(self, structure_type: Optional[StructureType]) -> bool:
        """
        判断是否为分水闸/分水口类型
        
        Args:
            structure_type: 结构类型
            
        Returns:
            是否为分水闸/分水口
        """
        if structure_type is None:
            return False
        return StructureType.is_diversion_gate(structure_type)
    
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
        2. 两者不能都是倒虹吸
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
            'transition_length_1': 0.0,
            'transition_length_2': 0.0,
            'distance': 0.0,
            'available_length': 0.0
        }
        
        # 检查前置条件
        # node1必须是出口
        if node1.in_out != InOutType.OUTLET:
            return result
        
        # node2必须是进口
        if node2.in_out != InOutType.INLET:
            return result
        
        # 倒虹吸与任何建筑物之间不需要渐变段
        if node1.structure_type == StructureType.INVERTED_SIPHON:
            return result
        if node2.structure_type == StructureType.INVERTED_SIPHON:
            return result
        
        # 分水闸/分水口与任何建筑物之间不插入明渠段
        if self._is_diversion_gate_type(node1.structure_type):
            return result
        if self._is_diversion_gate_type(node2.structure_type):
            return result
        
        # 判断是否需要渐变段（隧洞/渡槽需要）
        is_node1_tunnel_aqueduct = self._is_tunnel_or_aqueduct(node1.structure_type)
        is_node2_tunnel_aqueduct = self._is_tunnel_or_aqueduct(node2.structure_type)
        
        result['need_transition_1'] = is_node1_tunnel_aqueduct
        result['need_transition_2'] = is_node2_tunnel_aqueduct
        
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
                return {
                    'name': node.name,
                    'structure_type': node.structure_type.value if node.structure_type else "明渠-梯形",
                    'bottom_width': node.section_params.get("B", 0) if node.section_params else 0,
                    'water_depth': node.water_depth,
                    'side_slope': node.section_params.get("m", 0) if node.section_params else 0,
                    'roughness': node.roughness,
                    'slope_inv': 1.0 / node.slope_i if node.slope_i and node.slope_i > 0 else 3000,
                    'flow': node.flow,
                    'flow_section': node.flow_section
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
        
        # 设置断面参数
        open_channel.section_params = {
            "B": params.bottom_width,
            "m": params.side_slope
        }
        open_channel.water_depth = params.water_depth
        open_channel.roughness = params.roughness
        open_channel.slope_i = 1.0 / params.slope_inv if params.slope_inv > 0 else 0
        
        # 使用params中的流量，如果没有则使用prev_node的流量
        open_channel.flow = params.flow if params.flow > 0 else prev_node.flow
        
        # 坐标插值
        open_channel.x = (prev_node.x + next_node.x) / 2
        open_channel.y = (prev_node.y + next_node.y) / 2
        
        return open_channel
    
    def _create_merged_transition_node(self, node1: ChannelNode, 
                                       node2: ChannelNode, 
                                       distance: float) -> ChannelNode:
        """
        创建合并的渐变段节点（当里程差不足以插入明渠时）
        
        Args:
            node1: 前一建筑物出口节点
            node2: 后一建筑物进口节点
            distance: 实际里程差
            
        Returns:
            合并的渐变段节点
        """
        transition = ChannelNode()
        
        transition.is_transition = True
        transition.transition_type = "出口"
        transition.name = "-"
        transition.structure_type = StructureType.TRANSITION
        transition.flow_section = node1.flow_section
        
        # 使用实际里程差作为长度
        transition.transition_length = distance
        
        # 继承参数
        transition.x = node1.x
        transition.y = node1.y
        transition.flow = node1.flow
        transition.roughness = node1.roughness if node1.roughness > 0 else self.settings.roughness
        
        # 渐变段形式
        if hasattr(self.settings, 'transition_outlet_form') and self.settings.transition_outlet_form:
            transition.transition_form = self.settings.transition_outlet_form
        else:
            transition.transition_form = "曲线形反弯扭曲面"
        
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
        
        return transition
    
    def _create_transition_node(self, prev_node: ChannelNode, 
                                next_node: ChannelNode) -> ChannelNode:
        """
        创建渐变段专用节点
        
        Args:
            prev_node: 前一节点（渐变段起始端）
            next_node: 后一节点（渐变段末端）
            
        Returns:
            渐变段节点
        """
        transition = ChannelNode()
        
        # 标记为渐变段
        transition.is_transition = True
        transition.transition_type = "出口"  # 从prev_node出口到next_node
        
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
        
        # 默认渐变段形式（从全局设置读取）
        if hasattr(self.settings, 'transition_outlet_form') and self.settings.transition_outlet_form:
            transition.transition_form = self.settings.transition_outlet_form
        else:
            transition.transition_form = "曲线形反弯扭曲面"
        
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
        5. 倒虹吸相邻不插入渐变段（其损失已包含在倒虹吸水损中）
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
                    # 插入3行：出口渐变段 → 明渠段 → 进口渐变段
                    
                    # 1. 插入出口渐变段（如果需要）
                    if check_result['need_transition_1']:
                        transition_out = self._create_transition_node(current_node, next_node)
                        new_nodes.append(transition_out)
                    
                    # 2. 插入明渠段
                    upstream_channel = self._find_nearest_upstream_channel(nodes, i)
                    
                    # 获取当前流量段信息
                    flow_section = current_node.flow_section
                    flow = current_node.flow
                    
                    if open_channel_callback:
                        # 通过回调获取明渠参数（UI弹窗）
                        prev_struct = current_node.structure_type.value if current_node.structure_type else ""
                        next_struct = next_node.structure_type.value if next_node.structure_type else ""
                        params = open_channel_callback(
                            upstream_channel, 
                            check_result['available_length'],
                            prev_struct,
                            next_struct,
                            flow_section,
                            flow
                        )
                        if params:
                            open_channel = self._create_open_channel_node(params, current_node, next_node)
                            new_nodes.append(open_channel)
                    elif upstream_channel:
                        # 没有回调时，自动复制上游明渠参数
                        from ui.open_channel_dialog import OpenChannelParams
                        params = OpenChannelParams(
                            name="-",
                            structure_type=upstream_channel.get('structure_type', '明渠-梯形'),
                            bottom_width=upstream_channel.get('bottom_width', 0),
                            water_depth=upstream_channel.get('water_depth', 0),
                            side_slope=upstream_channel.get('side_slope', 0),
                            roughness=upstream_channel.get('roughness', 0.014),
                            slope_inv=upstream_channel.get('slope_inv', 3000),
                            flow=upstream_channel.get('flow', flow),
                            flow_section=upstream_channel.get('flow_section', flow_section)
                        )
                        open_channel = self._create_open_channel_node(params, current_node, next_node)
                        new_nodes.append(open_channel)
                    
                    # 3. 插入进口渐变段（如果需要）
                    if check_result['need_transition_2']:
                        transition_in = self._create_inlet_transition_node(next_node)
                        new_nodes.append(transition_in)
                
                elif check_result['need_transition_1'] or check_result['need_transition_2']:
                    # 不需要明渠段但需要渐变段（里程差 <= 渐变段之和）
                    # 只插入1行合并的渐变段
                    if check_result['distance'] > 0:
                        merged_transition = self._create_merged_transition_node(
                            current_node, next_node, check_result['distance']
                        )
                        new_nodes.append(merged_transition)
                
                elif self._needs_transition(current_node, next_node):
                    # 普通渐变段（非建筑物出口→进口的情况）
                    transition_node = self._create_transition_node(current_node, next_node)
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
            h_reserve = getattr(node, 'head_loss_reserve', 0.0) or 0.0
            h_gate = getattr(node, 'head_loss_gate', 0.0) or 0.0
            h_siphon = getattr(node, 'head_loss_siphon', 0.0) or 0.0
            
            # 重新计算总水头损失
            # 注：渐变段损失单独显示在渐变段行，不计入节点的总水头损失
            node.head_loss_total = h_bend + h_friction + h_reserve + h_gate + h_siphon

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
            "起点桩号": nodes[0].station_ip,
            "终点桩号": nodes[-1].station_ip,
            "总长度": nodes[-1].station_ip - nodes[0].station_ip,
            "起点水位": nodes[0].water_level,
            "终点水位": nodes[-1].water_level,
            "水位落差": nodes[0].water_level - nodes[-1].water_level,
        }
