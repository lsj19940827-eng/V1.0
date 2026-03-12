# -*- coding: utf-8 -*-
"""
倒虹吸数据提取模块

从推求水面线表格数据中识别和提取倒虹吸分组信息。
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
    upstream_bottom_elev: Optional[float] = None  # 上游渠底高程（仅供参考，不参与计算）
    roughness: float = 0.014                    # 糙率
    
    # ========== 平面段信息（从推求水面线表格自动提取） ==========
    plan_segments: List[Dict] = field(default_factory=list)   # 平面段列表
    plan_total_length: float = 0.0              # 平面总水平长度 (MC出 - MC进)
    
    # ========== 平面IP特征点（用于三维空间合并计算） ==========
    plan_feature_points: List[Dict] = field(default_factory=list)  # IP点特征信息列表
    
    # ========== 从表格自动提取的额外参数（供倒虹吸计算窗口使用） ==========
    upstream_velocity: float = 0.0              # 上游渠道流速 → 进口渐变段始端流速 v₁
    downstream_velocity: float = 0.0            # 下游渠道流速 → 出口渐变段末端流速 v₃
    upstream_velocity_increased: float = 0.0    # 上游渠道加大流速 → v₁加大
    downstream_velocity_increased: float = 0.0  # 下游渠道加大流速 → v₃加大
    upstream_velocity_source: str = "missing"   # 上游流速来源: adjacent / same_section_nearest_channel_fallback / missing
    downstream_velocity_source: str = "missing"  # 下游流速来源: adjacent / same_section_nearest_channel_fallback / missing
    
    # 上游渠道断面参数（用于自动计算进口渐变段末端流速 v₂）
    upstream_structure_type: Optional[str] = None  # 上游渠道结构类型（如"明渠-梯形"、"明渠-圆形"等）
    upstream_section_B: Optional[float] = None  # 上游渠道底宽 B
    upstream_section_h: Optional[float] = None  # 上游渠道水深 h
    upstream_section_m: Optional[float] = None  # 上游渠道边坡系数 m
    upstream_section_D: Optional[float] = None  # 上游渠道直径 D（圆形断面）
    upstream_section_R: Optional[float] = None  # 上游渠道半径 R（U形/马蹄形断面）
    
    # 下游渠道断面参数（用于出水口局部阻力系数自动计算）
    downstream_structure_type: Optional[str] = None  # 下游渠道结构类型（如"明渠-梯形"、"隧洞-圆形"等）
    downstream_section_B: Optional[float] = None  # 下游渠道底宽 B
    downstream_section_h: Optional[float] = None  # 下游渠道水深 h
    downstream_section_m: Optional[float] = None  # 下游渠道边坡系数 m
    downstream_section_D: Optional[float] = None  # 下游渠道直径 D（圆形断面）
    downstream_section_R: Optional[float] = None  # 下游渠道半径 R（U形/马蹄形断面）
    
    # 渐变段型式（从基础设置读取）
    inlet_transition_form: str = ""             # 进口渐变段型式
    outlet_transition_form: str = ""            # 出口渐变段型式
    
    # 倒虹吸渐变段局部损失系数（从基础设置读取，表L.1.2）
    siphon_transition_inlet_zeta: float = 0.10   # 倒虹吸进口渐变段局部损失系数
    siphon_transition_outlet_zeta: float = 0.20  # 倒虹吸出口渐变段局部损失系数

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

    VELOCITY_SOURCE_ADJACENT = "adjacent"
    VELOCITY_SOURCE_SAME_SECTION_FALLBACK = "same_section_nearest_channel_fallback"
    VELOCITY_SOURCE_MISSING = "missing"
    
    @staticmethod
    def extract_siphons(nodes: List[ChannelNode], settings=None) -> List[SiphonGroup]:
        """
        从节点列表中识别所有倒虹吸
        
        识别规则：
        1. structure_type == StructureType.INVERTED_SIPHON（结构形式为"倒虹吸"）
        2. 按 name（建筑物名称）分组，相同名称的行属于同一倒虹吸
        3. 识别进出口（in_out == INLET/OUTLET）
        4. 提取上下游渠道节点的流速、断面参数等（供倒虹吸计算窗口自动填充）
        
        Args:
            nodes: 渠道节点列表
            settings: 项目基础设置（ProjectSettings），用于获取渐变段型式等全局参数
            
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
            
            # 提取上下游渠道节点数据（流速、断面参数等）
            SiphonDataExtractor._extract_adjacent_node_data(group, nodes)
            
            # 提取渐变段型式（从基础设置）
            if settings is not None:
                SiphonDataExtractor._extract_transition_forms(group, settings)
            
            # 提取平面段信息
            SiphonDataExtractor._extract_plan_segments(group)
            
            # 提取平面IP特征点（供三维空间合并使用）
            SiphonDataExtractor._extract_plan_feature_points(group)
            
            result.append(group)
        
        return result
    
    @staticmethod
    def _extract_adjacent_node_data(group: SiphonGroup, nodes: List[ChannelNode]):
        """
        从倒虹吸进口的上游节点和出口的下游节点中提取流速、断面参数
        
        - 上游节点：进口行索引 - 1（跳过渐变段行）
        - 下游节点：出口行索引 + 1（跳过渐变段行）
        
        提取数据用途：
        - upstream_velocity → 进口渐变段始端流速 v₁
        - upstream_section_B/h/m → 自动计算进口渐变段末端流速 v₂
        - downstream_velocity → 出口渐变段末端流速 v₃
        """
        group.upstream_velocity_source = SiphonDataExtractor.VELOCITY_SOURCE_MISSING
        group.downstream_velocity_source = SiphonDataExtractor.VELOCITY_SOURCE_MISSING

        # === 提取上游渠道节点数据 ===
        if group.inlet_row_index >= 0:
            inlet_section = SiphonDataExtractor._get_flow_section(nodes, group.inlet_row_index)
            upstream_node = SiphonDataExtractor._find_adjacent_channel_node(
                nodes=nodes,
                start_index=group.inlet_row_index - 1,
                step=-1,
                target_flow_section=inlet_section
            )
            if upstream_node is None:
                upstream_node = SiphonDataExtractor._find_nearest_channel_node_in_same_section(
                    nodes=nodes,
                    anchor_index=group.inlet_row_index,
                    flow_section=inlet_section,
                    preferred_step=-1
                )
                if upstream_node is not None:
                    group.upstream_velocity_source = SiphonDataExtractor.VELOCITY_SOURCE_SAME_SECTION_FALLBACK
            else:
                group.upstream_velocity_source = SiphonDataExtractor.VELOCITY_SOURCE_ADJACENT

            if upstream_node is not None:
                SiphonDataExtractor._apply_upstream_node_data(group, upstream_node)

        # === 提取下游渠道节点数据 ===
        if group.outlet_row_index >= 0:
            outlet_section = SiphonDataExtractor._get_flow_section(nodes, group.outlet_row_index)
            downstream_node = SiphonDataExtractor._find_adjacent_channel_node(
                nodes=nodes,
                start_index=group.outlet_row_index + 1,
                step=1,
                target_flow_section=outlet_section
            )
            if downstream_node is None:
                downstream_node = SiphonDataExtractor._find_nearest_channel_node_in_same_section(
                    nodes=nodes,
                    anchor_index=group.outlet_row_index,
                    flow_section=outlet_section,
                    preferred_step=1
                )
                if downstream_node is not None:
                    group.downstream_velocity_source = SiphonDataExtractor.VELOCITY_SOURCE_SAME_SECTION_FALLBACK
            else:
                group.downstream_velocity_source = SiphonDataExtractor.VELOCITY_SOURCE_ADJACENT

            if downstream_node is not None:
                SiphonDataExtractor._apply_downstream_node_data(group, downstream_node)

    @staticmethod
    def _find_adjacent_channel_node(
        nodes: List[ChannelNode],
        start_index: int,
        step: int,
        target_flow_section: str
    ) -> Optional[ChannelNode]:
        """
        查找倒虹吸相邻同流量段明渠节点（闸穿透，不跨段）。
        """
        target_section = SiphonDataExtractor._normalize_flow_section(target_flow_section)
        i = start_index
        while 0 <= i < len(nodes):
            node = nodes[i]
            node_section = SiphonDataExtractor._normalize_flow_section(getattr(node, "flow_section", ""))
            if node_section != target_section:
                break

            if getattr(node, 'is_transition', False):
                i += step
                continue
            if SiphonDataExtractor._is_inverted_siphon(node):
                i += step
                continue
            if getattr(node, 'is_auto_inserted_channel', False):
                i += step
                continue
            if SiphonDataExtractor._is_gate_node(node):
                i += step
                continue
            if not SiphonDataExtractor._is_open_channel_node(node):
                i += step
                continue

            return node

        return None

    @staticmethod
    def _find_nearest_channel_node_in_same_section(
        nodes: List[ChannelNode],
        anchor_index: int,
        flow_section: str,
        preferred_step: int
    ) -> Optional[ChannelNode]:
        """
        在同一流量段内查找距离 anchor 最近的明渠节点。
        若距离相同，优先选择原扫描方向（preferred_step）上的节点。
        """
        target_section = SiphonDataExtractor._normalize_flow_section(flow_section)
        best_node: Optional[ChannelNode] = None
        best_score = None

        for idx, node in enumerate(nodes):
            if idx == anchor_index:
                continue

            node_section = SiphonDataExtractor._normalize_flow_section(getattr(node, "flow_section", ""))
            if node_section != target_section:
                continue
            if getattr(node, 'is_transition', False):
                continue
            if SiphonDataExtractor._is_inverted_siphon(node):
                continue
            if getattr(node, 'is_auto_inserted_channel', False):
                continue
            if SiphonDataExtractor._is_gate_node(node):
                continue
            if not SiphonDataExtractor._is_open_channel_node(node):
                continue

            distance = abs(idx - anchor_index)
            same_direction = (idx - anchor_index) * preferred_step > 0
            score = (distance, 0 if same_direction else 1, idx)
            if best_score is None or score < best_score:
                best_score = score
                best_node = node

        return best_node

    @staticmethod
    def _normalize_flow_section(flow_section) -> str:
        if flow_section is None:
            return ""
        return str(flow_section).strip()

    @staticmethod
    def _get_flow_section(nodes: List[ChannelNode], row_index: int) -> str:
        if row_index < 0 or row_index >= len(nodes):
            return ""
        return SiphonDataExtractor._normalize_flow_section(getattr(nodes[row_index], "flow_section", ""))

    @staticmethod
    def _is_open_channel_node(node: ChannelNode) -> bool:
        st = getattr(node, "structure_type", None)
        if st is None:
            return False
        st_val = st.value if hasattr(st, "value") else str(st)
        return st_val in {"明渠-梯形", "明渠-矩形", "明渠-圆形", "明渠-U形", "矩形"}

    @staticmethod
    def _is_gate_node(node: ChannelNode) -> bool:
        if getattr(node, "is_diversion_gate", False):
            return True
        st = getattr(node, "structure_type", None)
        if st is None:
            return False
        if hasattr(st, "value"):
            return StructureType.is_diversion_gate(st)
        return StructureType.is_diversion_gate_str(str(st))

    @staticmethod
    def _apply_upstream_node_data(group: SiphonGroup, upstream_node: ChannelNode):
        # 提取上游流速
        if upstream_node.velocity > 0:
            group.upstream_velocity = upstream_node.velocity
        # 提取上游加大流速（批量计算的加大流量工况流速）
        _v_inc = getattr(upstream_node, 'velocity_increased', 0.0)
        if _v_inc and _v_inc > 0:
            group.upstream_velocity_increased = _v_inc

        # 提取上游结构类型
        if upstream_node.structure_type is not None:
            st_val = (upstream_node.structure_type.value
                      if hasattr(upstream_node.structure_type, 'value')
                      else str(upstream_node.structure_type))
            group.upstream_structure_type = st_val

        # 提取上游断面参数（B、h、m、D、R_circle）
        # 注意：m=0 对矩形断面是有效值，需要一并传递
        sp = upstream_node.section_params or {}
        B = sp.get("B", 0.0)
        h = upstream_node.water_depth
        m = sp.get("m", 0.0)
        D = sp.get("D", 0.0)
        R_circle = sp.get("R_circle", 0.0)

        if B > 0 and h > 0:
            group.upstream_section_B = B
            group.upstream_section_h = h
            group.upstream_section_m = m  # m=0 表示矩形断面，也是有效值
        elif D > 0 and h > 0:
            # 圆形断面：B=0 但 D>0，用 D 作为特征宽度
            group.upstream_section_B = D  # 以直径作为等效宽度供渐变段计算
            group.upstream_section_h = h
            group.upstream_section_m = 0
        elif R_circle > 0 and h > 0:
            # U形/马蹄形断面：用 2R 作为特征宽度
            group.upstream_section_B = 2 * R_circle
            group.upstream_section_h = h
            group.upstream_section_m = 0

        # 额外存储上游 D 和 R_circle（供精确计算使用）
        if D > 0:
            group.upstream_section_D = D
        if R_circle > 0:
            group.upstream_section_R = R_circle
        # 对于圆形/U形等，水深也需要提取
        if h > 0 and group.upstream_section_h is None:
            group.upstream_section_h = h

    @staticmethod
    def _apply_downstream_node_data(group: SiphonGroup, downstream_node: ChannelNode):
        # 提取下游流速
        if downstream_node.velocity > 0:
            group.downstream_velocity = downstream_node.velocity
        # 提取下游加大流速（批量计算的加大流量工况流速）
        _v_inc = getattr(downstream_node, 'velocity_increased', 0.0)
        if _v_inc and _v_inc > 0:
            group.downstream_velocity_increased = _v_inc

        # 提取下游结构类型
        if downstream_node.structure_type is not None:
            st_val = (downstream_node.structure_type.value
                      if hasattr(downstream_node.structure_type, 'value')
                      else str(downstream_node.structure_type))
            group.downstream_structure_type = st_val

        # 提取下游断面参数（B、h、m、D、R）
        # 注意：m=0 对矩形断面是有效值，需要一并传递
        sp = downstream_node.section_params or {}
        B = sp.get("B", 0.0)
        h = downstream_node.water_depth
        m = sp.get("m", 0.0)
        D = sp.get("D", 0.0)
        R_circle = sp.get("R_circle", 0.0)

        if B > 0 and h > 0:
            group.downstream_section_B = B
            group.downstream_section_h = h
            group.downstream_section_m = m  # m=0 表示矩形断面，也是有效值
        elif D > 0 and h > 0:
            # 圆形断面：B=0 但 D>0，用 D 作为特征宽度
            group.downstream_section_B = D
            group.downstream_section_h = h
            group.downstream_section_m = 0
        elif R_circle > 0 and h > 0:
            # U形/马蹄形断面：用 2R 作为特征宽度
            group.downstream_section_B = 2 * R_circle
            group.downstream_section_h = h
            group.downstream_section_m = 0

        if D > 0:
            group.downstream_section_D = D
        if R_circle > 0:
            group.downstream_section_R = R_circle
        # 对于圆形/U形等，水深也需要提取
        if h > 0 and group.downstream_section_h is None:
            group.downstream_section_h = h
    
    @staticmethod
    def _extract_transition_forms(group: SiphonGroup, settings):
        """
        从项目基础设置中提取倒虹吸专用渐变段型式和局部损失系数（表L.1.2）
        
        注意：倒虹吸使用表L.1.2的型式名称（如"反弯扭曲面"），
        而非表K.1.2的型式名称（如"曲线形反弯扭曲面"）。
        
        Args:
            group: 倒虹吸分组
            settings: ProjectSettings 对象
        """
        # 使用倒虹吸专用的渐变段型式（表L.1.2）
        if hasattr(settings, 'siphon_transition_inlet_form') and settings.siphon_transition_inlet_form:
            group.inlet_transition_form = settings.siphon_transition_inlet_form
        if hasattr(settings, 'siphon_transition_outlet_form') and settings.siphon_transition_outlet_form:
            group.outlet_transition_form = settings.siphon_transition_outlet_form
        
        # 提取倒虹吸渐变段局部损失系数（表L.1.2）
        if hasattr(settings, 'siphon_transition_inlet_zeta'):
            group.siphon_transition_inlet_zeta = settings.siphon_transition_inlet_zeta
        if hasattr(settings, 'siphon_transition_outlet_zeta'):
            group.siphon_transition_outlet_zeta = settings.siphon_transition_outlet_zeta
    
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
            # 注意：此处转角来自 geometry_calc 的坐标计算，< 0.1° 视为直线通过（坐标噪声），不生成弯管段
            if 0 < i < len(rows) - 1:
                if node.turn_angle >= 0.1:
                    radius = node.turn_radius if node.turn_radius > 0 else 0.0
                    arc_len = radius * math.radians(node.turn_angle) if radius > 0 else 0.0
                    plan_segments.append({
                        "segment_type": "弯管",
                        "direction": "平面",
                        "length": round(arc_len, 3),
                        "radius": round(radius, 3),
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
            # 注意：此处转角来自坐标计算，< 0.1° 视为直线通过（坐标噪声），turn_type 设为"无"
            turn_type = "无"
            if 0 < i < len(rows) - 1 and node.turn_angle >= 0.1:
                turn_type = "圆弧" if node.turn_radius > 0 else "折线"
            
            fp = {
                "chainage": node.station_MC,
                "x": node.x,
                "y": node.y,
                "azimuth": node.azimuth,  # 测量方位角(度)，PlanFeaturePoint.from_dict 映射到 azimuth_meas_deg
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
