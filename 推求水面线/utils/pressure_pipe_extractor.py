# -*- coding: utf-8 -*-
"""
有压管道数据提取模块

从推求水面线表格数据中识别和提取有压管道分组信息。
有压管道结构：进口行 + 多个IP点行 + 出口行，通过"进出口标识"列区分。
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from collections import defaultdict

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.data_models import ChannelNode
from models.enums import StructureType, InOutType
from core.pressure_pipe_calc import calc_turn_angle, calc_segment_length
from config.constants import XXPIPE_CHANNEL_LEVEL_OPTIONS
from utils.pressure_pipe_result_helpers import make_pressure_pipe_identity

NO_TRANSITION_REASON = "紧邻有压同类结构，无渐变段"


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
    group_mode: str = "named_group"             # 分组模式：named_group / unnamed_row_segment
    display_name: str = ""                      # 界面展示名称
    storage_key: str = ""                       # 存储键
    identity: str = ""                          # 稳定身份键
    target_row_index: int = -1                  # 匿名段目标行索引
    upstream_row_index: int = -1                # 匿名段上一普通行索引
    route_key: str = ""                         # 所属整线键
    route_display_name: str = ""                # 整线展示名称
    route_start_row_index: int = -1             # 整线起始行索引
    route_end_row_index: int = -1               # 整线结束行索引
    route_start_mc: float = 0.0                 # 整线起点桩号
    route_end_mc: float = 0.0                   # 整线终点桩号
    route_ip_points: List[Dict] = field(default_factory=list)  # 整线平面点
    route_member_keys: List[str] = field(default_factory=list)  # 整线成员键
    segment_start_mc: float = 0.0               # 当前子段起点桩号
    segment_end_mc: float = 0.0                 # 当前子段终点桩号
    has_inlet_transition: bool = True           # 进口侧是否存在渐变段
    has_outlet_transition: bool = True          # 出口侧是否存在渐变段
    inlet_transition_reason: str = ""           # 进口侧无渐变段原因
    outlet_transition_reason: str = ""          # 出口侧无渐变段原因
    
    def is_valid(self) -> bool:
        """检查有压管道数据是否有效"""
        if self.group_mode == "unnamed_row_segment":
            return (
                self.target_row_index >= 0 and
                self.upstream_row_index >= 0 and
                self.design_flow > 0 and
                self.diameter > 0 and
                len(self.ip_points) >= 2
            )
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
        label = self.display_name or self.name or "未命名有压管道"
        if self.group_mode == "unnamed_row_segment":
            if self.upstream_row_index < 0:
                issues.append("缺少上一普通行")
            if len(self.ip_points) < 2:
                issues.append("缺少有效平面坐标")
            if self.design_flow <= 0:
                issues.append("设计流量无效")
            if self.diameter <= 0:
                issues.append("管径无效")
            if issues:
                return f"{label}: " + ", ".join(issues)
            return ""
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
            return f"{label}: " + ", ".join(issues)
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
        2. 仅提取带有建筑物名称的组；空名称行视为表3逐行独立管段，不参与外部有压管道分组
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
            
            name = (node.name or "").strip()
            if not name:
                continue
            in_out_raw = PressurePipeDataExtractor._get_in_out_raw(node)
            group_key = name
            
            # 创建或获取分组
            if group_key not in groups_dict:
                groups_dict[group_key] = PressurePipeGroup(name=name)
                group_order.append(group_key)
            
            group = groups_dict[group_key]
            group.rows.append(node)
            group.row_indices.append(idx)
            
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
        for group_key in group_order:
            group = groups_dict[group_key]
            
            # 如果没有明确的进出口标记，仅在存在多行时尝试根据位置推断
            if group.inlet_row_index < 0 and len(group.row_indices) >= 2:
                group.inlet_row_index = group.row_indices[0]
                first_node = group.rows[0]
                group.design_flow = first_node.flow if first_node.flow > 0 else 0
                sp = first_node.section_params or {}
                group.diameter = sp.get('D', 0) or sp.get('直径D', 0)
                group.material_key = sp.get('pipe_material', '')
            
            if group.outlet_row_index < 0 and len(group.row_indices) >= 2:
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
    def extract_dialog_pipe_groups(nodes: List[ChannelNode], settings=None) -> List[PressurePipeGroup]:
        """
        提取“有压管道水力计算配置”窗口专用分组。

        返回两类对象：
        1. 原有命名有压管道/定向钻/顶管组；
        2. xx管渠道级别下的空名称普通“有压管道”匿名段。
        """
        if not nodes:
            return []

        ordered_groups: List[Tuple[int, PressurePipeGroup]] = []

        for group in PressurePipeDataExtractor.extract_pipes(nodes, settings=settings):
            flow_section = PressurePipeDataExtractor._resolve_group_flow_section(group)
            group.group_mode = "named_group"
            group.display_name = group.name or "未命名"
            group.storage_key = group.name or ""
            group.identity = make_pressure_pipe_identity(flow_section or "-", group.name or "")
            group.target_row_index = group.outlet_row_index
            group.upstream_row_index = group.inlet_row_index
            ordered_groups.append((PressurePipeDataExtractor._group_order_index(group), group))

        if PressurePipeDataExtractor._is_xxpipe_channel_level(settings):
            for idx, node in enumerate(nodes):
                if not PressurePipeDataExtractor._is_unnamed_regular_pressure_pipe(node):
                    continue
                anonymous_group = PressurePipeDataExtractor._build_unnamed_row_group(nodes, idx, settings=settings)
                ordered_groups.append((idx, anonymous_group))

        ordered_groups.sort(key=lambda item: item[0])
        groups = [group for _, group in ordered_groups]

        for group in groups:
            PressurePipeDataExtractor._apply_default_route_context(group, nodes)

        if PressurePipeDataExtractor._is_xxpipe_channel_level(settings):
            route_contexts = PressurePipeDataExtractor._build_xxpipe_route_contexts(nodes, groups)
            for group in groups:
                PressurePipeDataExtractor._apply_route_context(group, route_contexts)

        return groups
    
    @staticmethod
    def _is_pressure_pipe(node: ChannelNode) -> bool:
        """判断节点是否为有压管道"""
        if node.structure_type and StructureType.is_pressure_pipe_like(node.structure_type):
            return True
        if getattr(node, 'is_pressure_pipe', False):
            return True
        return False

    @staticmethod
    def _is_regular_pressure_pipe(node: Optional[ChannelNode]) -> bool:
        """判断是否为普通有压管道行。"""
        if node is None or getattr(node, "is_transition", False):
            return False
        structure_value = node.structure_type.value if getattr(node, "structure_type", None) else ""
        return structure_value == StructureType.PRESSURE_PIPE.value

    @staticmethod
    def _is_unnamed_regular_pressure_pipe(node: Optional[ChannelNode]) -> bool:
        """判断是否为空名称普通有压管道行。"""
        if not PressurePipeDataExtractor._is_regular_pressure_pipe(node):
            return False
        return not str(getattr(node, "name", "") or "").strip()

    @staticmethod
    def _is_xxpipe_channel_level(settings) -> bool:
        """判断当前是否为 xx管 渠道级别。"""
        channel_level = str(getattr(settings, "channel_level", "") or "").strip()
        return channel_level in set(XXPIPE_CHANNEL_LEVEL_OPTIONS)

    @staticmethod
    def _resolve_group_flow_section(group: PressurePipeGroup) -> str:
        """解析分组所属流量段。"""
        for node in getattr(group, "rows", []) or []:
            flow_section = str(getattr(node, "flow_section", "") or "").strip()
            if flow_section:
                return flow_section
        return ""

    @staticmethod
    def _group_order_index(group: PressurePipeGroup) -> int:
        """返回分组在表3中的排序位置。"""
        indices = [idx for idx in (getattr(group, "row_indices", []) or []) if isinstance(idx, int)]
        if indices:
            return min(indices)
        return max(0, int(getattr(group, "target_row_index", 0) or 0))

    @staticmethod
    def _resolve_node_station_mc(node: Optional[ChannelNode]) -> float:
        """提取节点桩号。"""
        try:
            value = float(getattr(node, "station_MC", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return value if math.isfinite(value) else 0.0

    @staticmethod
    def _append_unique_plan_point(points: List[Dict[str, Any]], point: Dict[str, Any]):
        """追加整线平面点，避免连续重复点。"""
        if not points:
            points.append(point)
            return
        last = points[-1]
        if (
            abs(float(last.get("x", 0.0) or 0.0) - float(point.get("x", 0.0) or 0.0)) <= 1e-9
            and abs(float(last.get("y", 0.0) or 0.0) - float(point.get("y", 0.0) or 0.0)) <= 1e-9
        ):
            return
        points.append(point)

    @staticmethod
    def _is_xxpipe_route_candidate(node: Optional[ChannelNode]) -> bool:
        """判断节点是否属于 xx管 整线候选结构。"""
        if node is None:
            return False
        if getattr(node, "is_transition", False):
            return False
        if getattr(node, "is_auto_inserted_channel", False):
            return False
        structure_value = node.structure_type.value if getattr(node, "structure_type", None) else ""
        if not structure_value:
            return False
        return (
            StructureType.is_pressure_pipe_like_str(structure_value)
            or "隧洞" in structure_value
        )

    @staticmethod
    def _build_xxpipe_route_contexts(
        nodes: List[ChannelNode],
        groups: List[PressurePipeGroup],
    ) -> Dict[str, Dict[str, Any]]:
        """构造 xx管 连续承压整线上下文。"""
        route_contexts: Dict[str, Dict[str, Any]] = {}
        row_to_route_key: Dict[int, str] = {}
        flow_route_seq: Dict[str, int] = defaultdict(int)
        idx = 0
        total_nodes = len(nodes)

        while idx < total_nodes:
            node = nodes[idx]
            if not PressurePipeDataExtractor._is_xxpipe_route_candidate(node):
                idx += 1
                continue

            flow_section = str(getattr(node, "flow_section", "") or "").strip()
            start_idx = idx
            end_idx = idx
            while end_idx + 1 < total_nodes:
                next_node = nodes[end_idx + 1]
                if not PressurePipeDataExtractor._is_xxpipe_route_candidate(next_node):
                    break
                next_flow_section = str(getattr(next_node, "flow_section", "") or "").strip()
                if next_flow_section != flow_section:
                    break
                end_idx += 1

            flow_key = flow_section or "-"
            flow_route_seq[flow_key] += 1
            route_no = flow_route_seq[flow_key]
            route_key = f"flow{flow_key}-route{route_no}"
            route_display_name = f"流量段{flow_key} 整线{route_no}"

            route_nodes = nodes[start_idx : end_idx + 1]
            route_ip_points: List[Dict[str, Any]] = []
            for route_node in route_nodes:
                if not PressurePipeDataExtractor._can_use_plan_point(route_node):
                    continue
                point = PressurePipeDataExtractor._make_plan_point(route_node)
                point["station_mc"] = PressurePipeDataExtractor._resolve_node_station_mc(route_node)
                PressurePipeDataExtractor._append_unique_plan_point(route_ip_points, point)

            route_context = {
                "route_key": route_key,
                "route_display_name": route_display_name,
                "route_start_row_index": start_idx,
                "route_end_row_index": end_idx,
                "route_start_mc": PressurePipeDataExtractor._resolve_node_station_mc(nodes[start_idx]),
                "route_end_mc": PressurePipeDataExtractor._resolve_node_station_mc(nodes[end_idx]),
                "route_ip_points": route_ip_points,
            }
            route_contexts[route_key] = route_context
            for row_idx in range(start_idx, end_idx + 1):
                row_to_route_key[row_idx] = route_key
            idx = end_idx + 1

        route_member_keys: Dict[str, List[str]] = defaultdict(list)
        for group in groups or []:
            candidate_indices = [
                idx for idx in (getattr(group, "row_indices", []) or []) if isinstance(idx, int) and idx >= 0
            ]
            if not candidate_indices:
                target_row_index = int(getattr(group, "target_row_index", -1) or -1)
                if target_row_index >= 0:
                    candidate_indices.append(target_row_index)
            route_key = ""
            for row_idx in candidate_indices:
                route_key = row_to_route_key.get(row_idx, "")
                if route_key:
                    break
            if not route_key:
                continue
            member_key = str(getattr(group, "identity", "") or getattr(group, "storage_key", "") or "").strip()
            if member_key and member_key not in route_member_keys[route_key]:
                route_member_keys[route_key].append(member_key)

        for route_key, route_context in route_contexts.items():
            route_context["route_member_keys"] = list(route_member_keys.get(route_key, []))

        return route_contexts

    @staticmethod
    def _build_default_route_points(group: PressurePipeGroup, nodes: List[ChannelNode]) -> List[Dict[str, Any]]:
        """构造默认整线平面点。"""
        if getattr(group, "ip_points", None):
            return [dict(point) for point in (group.ip_points or [])]
        points: List[Dict[str, Any]] = []
        candidate_indices = []
        upstream_idx = int(getattr(group, "upstream_row_index", -1) or -1)
        target_idx = int(getattr(group, "target_row_index", -1) or -1)
        if upstream_idx >= 0:
            candidate_indices.append(upstream_idx)
        if target_idx >= 0:
            candidate_indices.append(target_idx)
        for row_idx in candidate_indices:
            if row_idx < 0 or row_idx >= len(nodes):
                continue
            node = nodes[row_idx]
            if not PressurePipeDataExtractor._can_use_plan_point(node):
                continue
            point = PressurePipeDataExtractor._make_plan_point(node)
            point["station_mc"] = PressurePipeDataExtractor._resolve_node_station_mc(node)
            PressurePipeDataExtractor._append_unique_plan_point(points, point)
        return points

    @staticmethod
    def _resolve_named_group_segment_range(group: PressurePipeGroup, nodes: List[ChannelNode]) -> Tuple[float, float]:
        """解析命名组子段范围。"""
        start_idx = int(getattr(group, "inlet_row_index", -1) or -1)
        end_idx = int(getattr(group, "outlet_row_index", -1) or -1)
        indices = [idx for idx in (start_idx, end_idx) if 0 <= idx < len(nodes)]
        if not indices:
            indices = [
                idx for idx in (getattr(group, "row_indices", []) or [])
                if isinstance(idx, int) and 0 <= idx < len(nodes)
            ]
        if not indices:
            return 0.0, 0.0
        start_mc = PressurePipeDataExtractor._resolve_node_station_mc(nodes[min(indices)])
        end_mc = PressurePipeDataExtractor._resolve_node_station_mc(nodes[max(indices)])
        return start_mc, end_mc

    @staticmethod
    def _resolve_group_segment_range(group: PressurePipeGroup, nodes: List[ChannelNode]) -> Tuple[float, float]:
        """解析当前分组自身桩号范围。"""
        if str(getattr(group, "group_mode", "") or "").strip() == "unnamed_row_segment":
            upstream_idx = int(getattr(group, "upstream_row_index", -1) or -1)
            target_idx = int(getattr(group, "target_row_index", -1) or -1)
            start_node = nodes[upstream_idx] if 0 <= upstream_idx < len(nodes) else None
            end_node = nodes[target_idx] if 0 <= target_idx < len(nodes) else None
            return (
                PressurePipeDataExtractor._resolve_node_station_mc(start_node),
                PressurePipeDataExtractor._resolve_node_station_mc(end_node),
            )
        return PressurePipeDataExtractor._resolve_named_group_segment_range(group, nodes)

    @staticmethod
    def _apply_default_route_context(group: PressurePipeGroup, nodes: List[ChannelNode]):
        """为分组补默认的整线与子段范围。"""
        segment_start_mc, segment_end_mc = PressurePipeDataExtractor._resolve_group_segment_range(group, nodes)
        route_points = PressurePipeDataExtractor._build_default_route_points(group, nodes)
        route_key = str(getattr(group, "identity", "") or getattr(group, "storage_key", "") or "").strip()
        if not route_key:
            route_key = str(getattr(group, "display_name", "") or getattr(group, "name", "") or "route").strip()
        group.route_key = route_key
        group.route_display_name = str(getattr(group, "display_name", "") or getattr(group, "name", "") or "整线").strip()
        group.route_start_row_index = PressurePipeDataExtractor._group_order_index(group)
        group.route_end_row_index = max(
            [int(idx) for idx in (getattr(group, "row_indices", []) or []) if isinstance(idx, int)] or
            [int(getattr(group, "target_row_index", -1) or -1)]
        )
        group.route_start_mc = segment_start_mc
        group.route_end_mc = segment_end_mc
        group.route_ip_points = route_points
        member_key = str(getattr(group, "identity", "") or getattr(group, "storage_key", "") or "").strip()
        group.route_member_keys = [member_key] if member_key else []
        group.segment_start_mc = segment_start_mc
        group.segment_end_mc = segment_end_mc

    @staticmethod
    def _apply_route_context(group: PressurePipeGroup, route_contexts: Dict[str, Dict[str, Any]]):
        """将整线上下文写入分组。"""
        row_candidates = [
            idx for idx in (getattr(group, "row_indices", []) or []) if isinstance(idx, int) and idx >= 0
        ]
        if not row_candidates:
            target_row_index = int(getattr(group, "target_row_index", -1) or -1)
            if target_row_index >= 0:
                row_candidates.append(target_row_index)

        selected_route = None
        for route_context in route_contexts.values():
            route_start = int(route_context.get("route_start_row_index", -1) or -1)
            route_end = int(route_context.get("route_end_row_index", -1) or -1)
            if any(route_start <= row_idx <= route_end for row_idx in row_candidates):
                selected_route = route_context
                break
        if not selected_route:
            return

        route_start_row_index = selected_route.get("route_start_row_index", group.route_start_row_index)
        route_end_row_index = selected_route.get("route_end_row_index", group.route_end_row_index)
        route_start_mc = selected_route.get("route_start_mc", group.route_start_mc)
        route_end_mc = selected_route.get("route_end_mc", group.route_end_mc)
        group.route_key = str(selected_route.get("route_key", "") or group.route_key).strip()
        group.route_display_name = str(selected_route.get("route_display_name", "") or group.route_display_name).strip()
        group.route_start_row_index = int(route_start_row_index) if route_start_row_index is not None else -1
        group.route_end_row_index = int(route_end_row_index) if route_end_row_index is not None else -1
        group.route_start_mc = float(route_start_mc) if route_start_mc is not None else 0.0
        group.route_end_mc = float(route_end_mc) if route_end_mc is not None else 0.0
        group.route_ip_points = [dict(point) for point in (selected_route.get("route_ip_points", []) or [])]
        group.route_member_keys = list(selected_route.get("route_member_keys", []) or [])

    @staticmethod
    def _build_pressure_pipe_row_identity(node: ChannelNode, row_index: int) -> str:
        """构造匿名有压管道行稳定标识。"""
        identity = str(getattr(node, "pressure_pipe_row_identity", "") or "").strip()
        if identity:
            return identity
        flow_section = str(getattr(node, "flow_section", "") or "").strip()
        row_part = f"row{int(row_index) + 1}"
        if flow_section:
            return f"flow{flow_section}-{row_part}"
        return row_part

    @staticmethod
    def _build_unnamed_display_name(node: ChannelNode, row_index: int) -> str:
        """构造匿名段展示名称。"""
        flow_section = str(getattr(node, "flow_section", "") or "").strip() or "-"
        return f"流量段{flow_section} 第{int(row_index) + 1}行有压管道"

    @staticmethod
    def _find_previous_regular_row_index(nodes: List[ChannelNode], target_index: int) -> int:
        """查找当前行之前最近的普通行。"""
        for idx in range(target_index - 1, -1, -1):
            node = nodes[idx]
            if getattr(node, "is_transition", False):
                continue
            if getattr(node, "is_auto_inserted_channel", False):
                continue
            return idx
        return -1

    @staticmethod
    def _can_use_plan_point(node: Optional[ChannelNode]) -> bool:
        """判断节点是否具备可用于平面预览的坐标。"""
        if node is None:
            return False
        try:
            x_val = float(getattr(node, "x", 0.0) or 0.0)
            y_val = float(getattr(node, "y", 0.0) or 0.0)
        except (TypeError, ValueError):
            return False
        return math.isfinite(x_val) and math.isfinite(y_val)

    @staticmethod
    def _make_plan_point(node: ChannelNode, in_out_text: str = "") -> Dict[str, Any]:
        """构造平面点字典。"""
        return {
            "x": float(getattr(node, "x", 0.0) or 0.0),
            "y": float(getattr(node, "y", 0.0) or 0.0),
            "turn_radius": float(getattr(node, "turn_radius", 0.0) or 0.0),
            "turn_angle": float(getattr(node, "turn_angle", 0.0) or 0.0),
            "in_out": in_out_text,
            "name": str(getattr(node, "name", "") or ""),
        }

    @staticmethod
    def _build_unnamed_row_group(nodes: List[ChannelNode], row_index: int, settings=None) -> PressurePipeGroup:
        """构造匿名普通有压管道段对象。"""
        node = nodes[row_index]
        upstream_index = PressurePipeDataExtractor._find_previous_regular_row_index(nodes, row_index)
        upstream_node = nodes[upstream_index] if 0 <= upstream_index < len(nodes) else None
        section_params = getattr(node, "section_params", {}) or {}
        flow_section = str(getattr(node, "flow_section", "") or "").strip()
        storage_key = PressurePipeDataExtractor._build_pressure_pipe_row_identity(node, row_index)
        display_name = PressurePipeDataExtractor._build_unnamed_display_name(node, row_index)

        group = PressurePipeGroup(
            name="",
            rows=[node],
            row_indices=[row_index],
            inlet_row_index=upstream_index,
            outlet_row_index=row_index,
            ip_row_indices=[],
            design_flow=float(getattr(node, "flow", 0.0) or 0.0),
            diameter=section_params.get("D", 0.0) or section_params.get("直径D", 0.0) or 0.0,
            material_key=str(section_params.get("pipe_material", "") or ""),
            local_loss_ratio=section_params.get("local_loss_ratio", 0.15) or 0.15,
            plan_segments=[],
            plan_total_length=0.0,
            group_mode="unnamed_row_segment",
            display_name=display_name,
            storage_key=storage_key,
            identity=storage_key,
            target_row_index=row_index,
            upstream_row_index=upstream_index,
        )

        ip_points: List[Dict[str, Any]] = []
        if PressurePipeDataExtractor._can_use_plan_point(upstream_node):
            ip_points.append(PressurePipeDataExtractor._make_plan_point(upstream_node, in_out_text="进"))
        if PressurePipeDataExtractor._can_use_plan_point(node):
            ip_points.append(PressurePipeDataExtractor._make_plan_point(node, in_out_text="出"))
        group.ip_points = ip_points

        if len(ip_points) >= 2:
            PressurePipeDataExtractor._calc_plan_segments(group)

        PressurePipeDataExtractor._extract_adjacent_node_data_for_unnamed_segment(group, nodes)
        if settings is not None:
            PressurePipeDataExtractor._extract_transition_forms(group, settings)
        return group

    @staticmethod
    def _get_in_out_raw(node: ChannelNode) -> str:
        """统一提取进出口原始标记。"""
        raw = node.section_params.get('in_out_raw', '') if node.section_params else ''
        raw = str(raw or "").strip()
        if raw:
            return raw
        in_out = getattr(node, 'in_out', None)
        if in_out is None:
            return ""
        return str(getattr(in_out, "value", in_out) or "").strip()

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
        
        上游：进口行往前跳过渐变段后，判断第一个非渐变节点
        下游：出口行往后跳过渐变段后，判断第一个非渐变节点
        """
        if group.inlet_row_index < 0 or group.outlet_row_index < 0:
            return

        PressurePipeDataExtractor._extract_one_side_adjacent_data(
            group=group,
            nodes=nodes,
            start_index=group.inlet_row_index - 1,
            step=-1,
            is_inlet=True,
        )
        PressurePipeDataExtractor._extract_one_side_adjacent_data(
            group=group,
            nodes=nodes,
            start_index=group.outlet_row_index + 1,
            step=1,
            is_inlet=False,
        )

    @staticmethod
    def _extract_one_side_adjacent_data(
        group: PressurePipeGroup,
        nodes: List[ChannelNode],
        start_index: int,
        step: int,
        is_inlet: bool,
    ):
        """提取单侧相邻节点信息，必要时标记该侧无渐变段。"""
        index = start_index
        while 0 <= index < len(nodes):
            adjacent_node = nodes[index]

            if getattr(adjacent_node, "is_transition", False):
                index += step
                continue

            if PressurePipeDataExtractor._is_pressure_pipe(adjacent_node):
                PressurePipeDataExtractor._mark_transition_missing(group, is_inlet=is_inlet)
                return

            PressurePipeDataExtractor._assign_adjacent_node_data(group, adjacent_node, is_inlet=is_inlet)
            return

    @staticmethod
    def _extract_adjacent_node_data_for_unnamed_segment(group: PressurePipeGroup, nodes: List[ChannelNode]):
        """
        提取匿名段专项的上下游参照流速。

        规则：
        - 上游：若上一普通行为非有压流结构，直接使用该行；
        - 下游：从目标行之后寻找第一个非渐变普通行，且仅在其为非有压流结构时使用。
        """
        upstream_idx = getattr(group, "upstream_row_index", -1)
        target_idx = getattr(group, "target_row_index", -1)

        if 0 <= upstream_idx < len(nodes):
            upstream_node = nodes[upstream_idx]
            if PressurePipeDataExtractor._is_pressure_pipe(upstream_node):
                PressurePipeDataExtractor._mark_transition_missing(group, is_inlet=True)
            else:
                PressurePipeDataExtractor._assign_adjacent_node_data(group, upstream_node, is_inlet=True)

        if target_idx >= 0:
            for idx in range(target_idx + 1, len(nodes)):
                downstream_node = nodes[idx]
                if getattr(downstream_node, "is_transition", False):
                    continue
                if getattr(downstream_node, "is_auto_inserted_channel", False):
                    continue
                if PressurePipeDataExtractor._is_pressure_pipe(downstream_node):
                    PressurePipeDataExtractor._mark_transition_missing(group, is_inlet=False)
                else:
                    PressurePipeDataExtractor._assign_adjacent_node_data(group, downstream_node, is_inlet=False)
                break

    @staticmethod
    def _mark_transition_missing(group: PressurePipeGroup, is_inlet: bool):
        """标记某一侧紧邻有压同类结构，因此不存在渐变段。"""
        if is_inlet:
            group.has_inlet_transition = False
            group.inlet_transition_reason = NO_TRANSITION_REASON
            return
        group.has_outlet_transition = False
        group.outlet_transition_reason = NO_TRANSITION_REASON

    @staticmethod
    def _assign_adjacent_node_data(group: PressurePipeGroup, node: ChannelNode, is_inlet: bool):
        """写入单侧相邻渠道节点数据。"""
        section_params = PressurePipeDataExtractor._build_section_params(node)
        structure_type = node.structure_type.value if node.structure_type else ""
        velocity = node.velocity if node.velocity > 0 else 0.0

        if is_inlet:
            group.upstream_velocity = velocity
            group.upstream_structure_type = structure_type
            group.upstream_section_params = section_params
            return

        group.downstream_velocity = velocity
        group.downstream_structure_type = structure_type
        group.downstream_section_params = section_params

    @staticmethod
    def _build_section_params(node: ChannelNode) -> Dict:
        """提取节点断面参数。"""
        sp = node.section_params or {}
        return {
            'B': sp.get('B', 0) or sp.get('底宽b', 0) or sp.get('底宽B', 0),
            'h': node.water_depth,
            'm': sp.get('m', 0) or sp.get('边坡m', 0),
            'D': sp.get('D', 0) or sp.get('直径D', 0),
            'R': sp.get('R', 0) or sp.get('R_circle', 0) or sp.get('半径R', 0),
        }
    
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
