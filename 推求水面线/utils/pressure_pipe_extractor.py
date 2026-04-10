# -*- coding: utf-8 -*-
"""
有压管道数据提取模块

从推求水面线表格数据中识别和提取有压管道分组信息。
有压管道结构：进口行 + 多个IP点行 + 出口行，通过"进出口标识"列区分。
"""

import copy
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
from utils.pressure_pipe_common import coerce_row_index
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
    group_mode: str = "named_group"             # 分组模式：named_group / unnamed_row_segment / named_row_segment
    display_name: str = ""                      # 界面展示名称
    storage_key: str = ""                       # 存储键
    identity: str = ""                          # 稳定身份键
    legacy_storage_key: str = ""                # 兼容旧版的存储键
    legacy_identity: str = ""                   # 兼容旧版的身份键
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
    segment_geometry_source: str = ""           # 子段几何来源
    tunnel_invert_inlet: Optional[float] = None  # 隧洞进口底高
    tunnel_slope_i: Optional[float] = None      # 隧洞坡降 i
    tunnel_invert_outlet_check: Optional[float] = None  # 隧洞出口底高校核值
    tunnel_section_type: str = ""               # 隧洞断面类型
    tunnel_section_params: Dict[str, Any] = field(default_factory=dict)  # 隧洞断面参数
    has_inlet_transition: bool = True           # 进口侧是否存在渐变段
    has_outlet_transition: bool = True          # 出口侧是否存在渐变段
    inlet_transition_reason: str = ""           # 进口侧无渐变段原因
    outlet_transition_reason: str = ""          # 出口侧无渐变段原因
    member_role: str = ""                       # 链内角色：anchor / prefix_segment / regular_segment / special_segment
    is_anchor_member: bool = False              # 是否为流量段起点锚点成员
    should_generate_row_loss: bool = True       # 是否需要生成本行损失
    prefix_target_row_index: int = -1           # 前缀段起点行
    prefix_end_row_index: int = -1              # 前缀段终点边界行（下一特殊承压段进口）
    split_to_row_members: bool = False          # 是否改按逐段成员正式计损
    split_row_member_identities: List[str] = field(default_factory=list)  # 逐段成员身份列表
    
    def is_valid(self) -> bool:
        """检查有压管道数据是否有效"""
        if self.group_mode in {"unnamed_row_segment", "named_row_segment"}:
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
        if self.group_mode in {"unnamed_row_segment", "named_row_segment"}:
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


@dataclass
class PressurePipeChainMember:
    """
    连续承压链成员。

    命名有压组保留整组信息，匿名承压行和隧洞普通行按单行成员记录。
    """

    member_type: str = ""                       # named_group / single_row
    display_name: str = ""                      # 展示名称
    flow_section: str = ""                      # 所属流量段
    structure_type: str = ""                    # 结构形式字符串
    row_indices: List[int] = field(default_factory=list)  # 成员覆盖的原始行索引
    start_row_index: int = -1                   # 成员起始行
    end_row_index: int = -1                     # 成员结束行
    identity: str = ""                          # 成员稳定标识
    storage_key: str = ""                       # 成员存储键
    target_row_index: int = -1                  # 成员结果落点行
    upstream_row_index: int = -1                # 成员上一普通行
    group: Optional[PressurePipeGroup] = None   # 命名有压组对象
    node: Optional[ChannelNode] = None          # 单行成员原始节点
    base_display_name: str = ""                 # 未加后缀的原始展示名称
    identity_aliases: List[str] = field(default_factory=list)  # 历史身份别名
    source_identity_aliases: List[str] = field(default_factory=list)  # 原命名组身份别名
    member_role: str = ""                       # 链内角色：anchor / regular_segment / special_segment
    is_anchor_member: bool = False              # 是否为流量段起点锚点成员
    should_generate_row_loss: bool = True       # 是否需要生成本行损失
    prefix_target_row_index: int = -1           # 前缀段起点行
    prefix_end_row_index: int = -1              # 前缀段终点边界行（下一特殊承压段进口）
    parent_group_identity: str = ""             # 原命名组稳定身份
    parent_group_storage_key: str = ""          # 原命名组存储键
    split_from_named_group: bool = False        # 是否由命名组拆出的逐段成员
    route_key: str = ""                         # 所属整线键
    route_display_name: str = ""                # 所属整线展示名称


@dataclass
class PressurePipeChain:
    """
    连续承压链。

    表内连续出现的承压结构会被组织成一条链。

    当结构本身保持连续时，允许跨流量段延续，`flow_section` 记录链起始流量段。
    """

    flow_section: str = ""                                # 所属流量段
    members: List[PressurePipeChainMember] = field(default_factory=list)  # 链成员
    start_row_index: int = -1                             # 链起始行
    end_row_index: int = -1                               # 链结束行


class ProfileCoverageState:
    """连续承压纵断面覆盖状态常量。"""

    NOT_IMPORTED = "not_imported"
    IDENTITY_UNMATCHED = "identity_unmatched"
    COVERAGE_MISSING = "coverage_missing"
    OK = "ok"


@dataclass
class PressureResult:
    """连续承压单段正式结果。"""

    identity: str
    route_key: str = ""
    status: str = "pending"
    friction_loss: Optional[float] = None
    bend_loss: Optional[float] = None
    local_loss: Optional[float] = None
    total_loss: Optional[float] = None
    applied_to_row_index: int = -1
    note: str = ""
    computed_from_profile_source: str = ""


@dataclass
class PressureSegment:
    """连续承压整线中的单个可计算子段。"""

    identity: str
    route_key: str = ""
    base_name: str = ""
    member_display_name: str = ""
    dxf_display_name: str = ""
    structure_type: str = ""
    member_role: str = ""
    start_row_index: int = -1
    end_row_index: int = -1
    target_row_index: int = -1
    upstream_row_index: int = -1
    start_mc: float = 0.0
    end_mc: float = 0.0
    is_pressurized_tail_member: bool = True


@dataclass
class PressureRoute:
    """连续承压整线对象。"""

    route_key: str
    route_display_name: str = ""
    channel_level: str = ""
    start_row_index: int = -1
    end_row_index: int = -1
    start_mc: float = 0.0
    end_mc: float = 0.0
    entered_pressurized_at_row: int = -1
    segments: List[PressureSegment] = field(default_factory=list)
    profile_state: str = ProfileCoverageState.NOT_IMPORTED


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

        result: List[PressurePipeGroup] = []
        current_group: Optional[PressurePipeGroup] = None

        for idx, node in enumerate(nodes):
            if getattr(node, "is_transition", False) or getattr(node, "is_auto_inserted_channel", False):
                continue

            if not PressurePipeDataExtractor._is_pressure_pipe(node):
                if current_group is not None:
                    PressurePipeDataExtractor._finalize_named_pressure_group(
                        current_group,
                        nodes,
                        settings=settings,
                    )
                    result.append(current_group)
                    current_group = None
                continue

            name = str(getattr(node, "name", "") or "").strip()
            if not name:
                if current_group is not None:
                    PressurePipeDataExtractor._finalize_named_pressure_group(
                        current_group,
                        nodes,
                        settings=settings,
                    )
                    result.append(current_group)
                    current_group = None
                continue

            if not PressurePipeDataExtractor._can_append_to_named_pressure_group(current_group, node):
                if current_group is not None:
                    PressurePipeDataExtractor._finalize_named_pressure_group(
                        current_group,
                        nodes,
                        settings=settings,
                    )
                    result.append(current_group)
                current_group = PressurePipeGroup(name=name)

            PressurePipeDataExtractor._append_named_pressure_group_row(current_group, node, idx)

        if current_group is not None:
            PressurePipeDataExtractor._finalize_named_pressure_group(
                current_group,
                nodes,
                settings=settings,
            )
            result.append(current_group)

        return result

    @staticmethod
    def extract_dialog_pipe_groups(nodes: List[ChannelNode], settings=None) -> List[PressurePipeGroup]:
        """
        提取“有压管道水力计算配置”窗口专用分组。

        返回两类对象：
        1. 原有命名有压管道/定向钻/顶管组；
        2. 连续承压整线场景下需要单独计算的空名称有压同类匿名段。
        """
        if not nodes:
            return []

        ordered_groups: List[Tuple[int, PressurePipeGroup]] = []
        continuous_pressure_chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(
            nodes,
            settings=settings,
        )
        continuous_route_row_indices = PressurePipeDataExtractor._collect_chain_row_indices(
            continuous_pressure_chains
        )
        is_xxpipe_channel = PressurePipeDataExtractor._is_xxpipe_channel_level(settings)

        for group in PressurePipeDataExtractor.extract_pipes(nodes, settings=settings):
            group.group_mode = "named_group"
            group.display_name = group.display_name or group.name or "未命名"
            group.target_row_index = coerce_row_index(
                getattr(group, "target_row_index", group.outlet_row_index),
                group.outlet_row_index,
            )
            group.upstream_row_index = coerce_row_index(
                getattr(group, "upstream_row_index", group.inlet_row_index),
                group.inlet_row_index,
            )
            ordered_groups.append((PressurePipeDataExtractor._group_order_index(group), group))

        for idx, node in enumerate(nodes):
            if not PressurePipeDataExtractor._is_unnamed_pressure_pipe_like(node):
                continue
            if (not is_xxpipe_channel) and idx not in continuous_route_row_indices:
                continue
            anonymous_group = PressurePipeDataExtractor._build_single_row_pressure_like_group(
                nodes,
                idx,
                settings=settings,
            )
            if anonymous_group is None:
                continue
            ordered_groups.append((idx, anonymous_group))

        ordered_groups.sort(key=lambda item: item[0])
        groups = [group for _, group in ordered_groups]

        route_contexts = {}
        chain_member_metadata = PressurePipeDataExtractor._build_chain_member_metadata_map(
            continuous_pressure_chains
        )
        chain_split_metadata = PressurePipeDataExtractor._build_chain_split_metadata_map(
            continuous_pressure_chains
        )
        if is_xxpipe_channel or continuous_pressure_chains:
            route_contexts = PressurePipeDataExtractor._build_xxpipe_route_contexts(
                nodes,
                groups,
                chains=continuous_pressure_chains,
                tighten_to_active_bounds=PressurePipeDataExtractor._should_tighten_branch_pressure_chain(settings),
            )
        for group in groups:
            if PressurePipeDataExtractor._find_route_context_for_group(group, route_contexts) is None:
                PressurePipeDataExtractor._apply_chain_member_metadata_to_group(
                    group,
                    chain_member_metadata,
                )
                PressurePipeDataExtractor._apply_chain_split_metadata_to_group(
                    group,
                    chain_split_metadata,
                )
                continue
            PressurePipeDataExtractor._apply_default_route_context(group, nodes)
            PressurePipeDataExtractor._apply_route_context(group, route_contexts)
            PressurePipeDataExtractor._apply_chain_member_metadata_to_group(
                group,
                chain_member_metadata,
            )
            PressurePipeDataExtractor._apply_chain_split_metadata_to_group(
                group,
                chain_split_metadata,
            )

        return groups

    @staticmethod
    def extract_continuous_pressure_chains(nodes: List[ChannelNode], settings=None) -> List[PressurePipeChain]:
        """
        提取连续承压链。

        规则：
        1. xx管 继续保留原有整线口径；
        2. xx渠 只在真正形成连续承压线时返回链；
        3. 命名有压组沿用现有整组识别；
        4. 空名称有压同类结构、隧洞普通行按单行成员处理；
        5. 遇到非链结构即断开；若结构本身连续，允许跨流量段延续。
        """
        if not nodes:
            return []

        chains = PressurePipeDataExtractor._build_continuous_pressure_chains(
            nodes,
            settings=settings,
        )
        if PressurePipeDataExtractor._is_xxpipe_channel_level(settings):
            PressurePipeDataExtractor._apply_route_contexts_to_chain_members(
                nodes,
                chains,
                PressurePipeDataExtractor._build_xxpipe_route_contexts(
                    nodes,
                    [],
                    chains=chains,
                    tighten_to_active_bounds=PressurePipeDataExtractor._should_tighten_branch_pressure_chain(settings),
                ),
            )
            return chains

        filtered_chains = [
            chain
            for chain in chains
            if PressurePipeDataExtractor._is_supported_continuous_pressure_chain(chain)
        ]
        PressurePipeDataExtractor._apply_route_contexts_to_chain_members(
            nodes,
            filtered_chains,
            PressurePipeDataExtractor._build_xxpipe_route_contexts(
                nodes,
                [],
                chains=filtered_chains,
                tighten_to_active_bounds=PressurePipeDataExtractor._should_tighten_branch_pressure_chain(settings),
            ),
        )
        return filtered_chains

    @staticmethod
    def extract_pressure_routes(nodes: List[ChannelNode], settings=None) -> List[PressureRoute]:
        """提取连续承压整线与子段对象，供保存、导出和提示共用。"""
        chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(nodes, settings=settings)
        if not chains:
            return []

        routes_by_key: Dict[str, PressureRoute] = {}
        route_order: List[str] = []
        channel_level = str(getattr(settings, "channel_level", "") or "").strip()

        for chain_index, chain in enumerate(chains, start=1):
            route_key = PressurePipeDataExtractor._resolve_pressure_route_key(chain, chain_index)
            if not route_key:
                continue
            route_display_name = PressurePipeDataExtractor._resolve_pressure_route_display_name(chain, route_key)
            route = routes_by_key.get(route_key)
            if route is None:
                route = PressureRoute(
                    route_key=route_key,
                    route_display_name=route_display_name,
                    channel_level=channel_level,
                    start_row_index=PressurePipeDataExtractor._safe_int(
                        getattr(chain, "start_row_index", -1),
                        default=-1,
                    ),
                    end_row_index=PressurePipeDataExtractor._safe_int(
                        getattr(chain, "end_row_index", -1),
                        default=-1,
                    ),
                    entered_pressurized_at_row=PressurePipeDataExtractor._resolve_route_entered_pressurized_at_row(chain),
                )
                routes_by_key[route_key] = route
                route_order.append(route_key)
            else:
                route.start_row_index = PressurePipeDataExtractor._merge_index_min(
                    route.start_row_index,
                    getattr(chain, "start_row_index", -1),
                )
                route.end_row_index = PressurePipeDataExtractor._merge_index_max(
                    route.end_row_index,
                    getattr(chain, "end_row_index", -1),
                )
                route.entered_pressurized_at_row = PressurePipeDataExtractor._merge_index_min(
                    route.entered_pressurized_at_row,
                    PressurePipeDataExtractor._resolve_route_entered_pressurized_at_row(chain),
                )
                if not route.route_display_name:
                    route.route_display_name = route_display_name

            for member in list(getattr(chain, "members", []) or []):
                segment = PressurePipeDataExtractor._build_pressure_route_segment(member, nodes, route_key)
                if segment is not None:
                    route.segments.append(segment)

        routes: List[PressureRoute] = []
        for route_key in route_order:
            route = routes_by_key.get(route_key)
            if route is None:
                continue
            route.segments.sort(key=lambda item: (item.start_row_index, item.end_row_index, item.identity))
            PressurePipeDataExtractor._finalize_pressure_route_geometry(route, nodes)
            routes.append(route)
        return routes

    @staticmethod
    def _build_continuous_pressure_chains(nodes: List[ChannelNode], settings=None) -> List[PressurePipeChain]:
        """
        构造完整的连续承压链候选。

        这里先按拓扑连续性识别全部候选，再由上层决定是否对 xx渠 暴露整线模式。
        """
        if not nodes:
            return []

        named_groups = PressurePipeDataExtractor.extract_pipes(nodes, settings=settings)
        named_group_start_map: Dict[int, PressurePipeGroup] = {}
        named_group_row_indices = set()

        for group in named_groups:
            order_index = PressurePipeDataExtractor._group_order_index(group)
            named_group_start_map[order_index] = group
            named_group_row_indices.update(
                idx for idx in (group.row_indices or []) if isinstance(idx, int) and idx >= 0
            )

        chains: List[PressurePipeChain] = []
        current_chain: Optional[PressurePipeChain] = None
        index = 0

        while index < len(nodes):
            node = nodes[index]
            if getattr(node, "is_transition", False) or getattr(node, "is_auto_inserted_channel", False):
                index += 1
                continue

            member = None
            next_index = index + 1

            named_group = named_group_start_map.get(index)
            if named_group is not None:
                member = PressurePipeDataExtractor._build_named_chain_member(named_group)
                next_index = max(index + 1, member.end_row_index + 1)
            elif index not in named_group_row_indices:
                member = PressurePipeDataExtractor._build_single_row_chain_member(
                    nodes,
                    index,
                    settings=settings,
                )

            if member is None:
                if current_chain is not None:
                    chains.append(current_chain)
                    current_chain = None
                index = next_index
                continue

            if (
                current_chain is None
                and PressurePipeDataExtractor._should_tighten_branch_pressure_chain(settings)
                and not PressurePipeDataExtractor._can_start_branch_pressure_chain(member)
            ):
                # 支渠连续承压链必须先进入真正的有压段，
                # 起点前连续出现的隧洞直接忽略，不进入链成员。
                index = next_index
                continue

            if current_chain is None:
                if current_chain is not None:
                    chains.append(current_chain)
                current_chain = PressurePipeChain(
                    flow_section=member.flow_section,
                    members=[],
                    start_row_index=member.start_row_index,
                    end_row_index=member.end_row_index,
                )

            if (
                not current_chain.members
                and member.member_type == "single_row"
                and PressurePipeDataExtractor._is_flow_section_anchor_member(nodes, member.start_row_index)
            ):
                member.is_anchor_member = True
                member.should_generate_row_loss = False

            current_chain.members.append(member)
            current_chain.end_row_index = member.end_row_index
            index = next_index

        if current_chain is not None:
            chains.append(current_chain)

        for chain in chains:
            PressurePipeDataExtractor._post_process_continuous_pressure_chain(chain, settings=settings)
            PressurePipeDataExtractor._expand_named_tail_chain_members(
                chain,
                nodes,
                settings=settings,
            )

        return chains

    @staticmethod
    def _is_supported_continuous_pressure_chain(chain: Optional[PressurePipeChain]) -> bool:
        """判断当前承压链是否足以启用连续承压整线。"""
        if chain is None:
            return False
        members = list(getattr(chain, "members", []) or [])
        return len(members) >= 2

    @staticmethod
    def _can_start_branch_pressure_chain(member: Optional[PressurePipeChainMember]) -> bool:
        """判断支渠连续承压链是否可以从当前成员起链。"""
        if member is None:
            return False
        structure_type = str(getattr(member, "structure_type", "") or "").strip()
        return structure_type in {
            StructureType.PRESSURE_PIPE.value,
            StructureType.DIRECTIONAL_DRILL.value,
            StructureType.PIPE_JACKING.value,
        }

    @staticmethod
    def _should_tighten_branch_pressure_chain(settings) -> bool:
        """判断当前是否需要启用支渠前置隧洞收紧规则。"""
        channel_level = str(getattr(settings, "channel_level", "") or "").strip()
        return channel_level == "支渠"
    
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
    def _is_tunnel_structure(node: Optional[ChannelNode]) -> bool:
        """判断节点是否为隧洞结构。"""
        if node is None:
            return False
        structure_type = getattr(node, "structure_type", None)
        structure_value = structure_type.value if hasattr(structure_type, "value") else str(structure_type or "")
        return "隧洞" in structure_value

    @staticmethod
    def _is_unnamed_pressure_pipe_like(node: Optional[ChannelNode]) -> bool:
        """判断是否为空名称有压同类结构。"""
        if node is None or getattr(node, "is_transition", False):
            return False
        if not PressurePipeDataExtractor._is_pressure_pipe(node):
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
    def _resolve_node_structure_text(node: Optional[ChannelNode]) -> str:
        """提取节点结构形式文本。"""
        if node is None:
            return ""
        structure_type = getattr(node, "structure_type", None)
        return str(getattr(structure_type, "value", structure_type) or "").strip()

    @staticmethod
    def _resolve_group_structure_text(group: Optional[PressurePipeGroup]) -> str:
        """提取分组首行结构形式文本。"""
        rows = getattr(group, "rows", []) or []
        if not rows:
            return ""
        return PressurePipeDataExtractor._resolve_node_structure_text(rows[0])

    @staticmethod
    def _can_append_to_named_pressure_group(
        group: Optional[PressurePipeGroup],
        node: Optional[ChannelNode],
    ) -> bool:
        """判断当前命名有压行是否仍属于同一连续段。"""
        if group is None or node is None:
            return False

        node_name = str(getattr(node, "name", "") or "").strip()
        if not node_name or node_name != str(getattr(group, "name", "") or "").strip():
            return False

        if (
            PressurePipeDataExtractor._resolve_group_structure_text(group)
            != PressurePipeDataExtractor._resolve_node_structure_text(node)
        ):
            return False

        if coerce_row_index(getattr(group, "outlet_row_index", -1)) >= 0:
            return False

        in_out_raw = PressurePipeDataExtractor._get_in_out_raw(node)
        if (in_out_raw == "进" or getattr(node, "in_out", None) == InOutType.INLET) and coerce_row_index(
            getattr(group, "inlet_row_index", -1)
        ) >= 0:
            return False

        return True

    @staticmethod
    def _append_named_pressure_group_row(group: PressurePipeGroup, node: ChannelNode, row_index: int):
        """向连续命名段追加一行，并同步基础参数。"""
        group.rows.append(node)
        group.row_indices.append(row_index)

        in_out_raw = PressurePipeDataExtractor._get_in_out_raw(node)
        section_params = getattr(node, "section_params", {}) or {}

        if in_out_raw == "进" or getattr(node, "in_out", None) == InOutType.INLET:
            group.inlet_row_index = row_index
            group.design_flow = node.flow if node.flow > 0 else group.design_flow
            group.diameter = section_params.get("D", 0) or section_params.get("直径D", 0) or group.diameter
            group.material_key = section_params.get("pipe_material", "") or group.material_key
            group.local_loss_ratio = section_params.get("local_loss_ratio", 0.15)
            return

        if in_out_raw == "出" or getattr(node, "in_out", None) == InOutType.OUTLET:
            group.outlet_row_index = row_index
            if group.design_flow <= 0:
                group.design_flow = node.flow
            if group.diameter <= 0:
                group.diameter = section_params.get("D", 0) or section_params.get("直径D", 0)
            if not group.material_key:
                group.material_key = section_params.get("pipe_material", "")
            return

        if in_out_raw == "IP":
            group.ip_row_indices.append(row_index)

    @staticmethod
    def _build_named_group_row_range_key(group: PressurePipeGroup) -> str:
        """根据表3行号构造连续段范围键。"""
        row_indices = [idx for idx in (getattr(group, "row_indices", []) or []) if isinstance(idx, int)]
        if not row_indices:
            return "rows0"
        start_row = min(row_indices) + 1
        end_row = max(row_indices) + 1
        if start_row == end_row:
            return f"rows{start_row}"
        return f"rows{start_row}-{end_row}"

    @staticmethod
    def _build_named_group_segment_identity(group: PressurePipeGroup) -> str:
        """构造连续段优先的命名有压身份键。"""
        flow_section = PressurePipeDataExtractor._resolve_group_flow_section(group) or "-"
        name = str(getattr(group, "name", "") or "").strip() or "未命名"
        row_range_key = PressurePipeDataExtractor._build_named_group_row_range_key(group)
        return f"{flow_section}::{name}::{row_range_key}"

    @staticmethod
    def _build_pressure_pipe_row_identity_from_flow_section(flow_section, row_index: int) -> str:
        """按流量段和行号构造稳定行身份。"""
        flow_section_text = str(flow_section or "").strip()
        row_part = f"row{int(row_index) + 1}"
        if flow_section_text:
            return f"flow{flow_section_text}-{row_part}"
        return row_part

    @staticmethod
    def _apply_named_group_identity_fields(group: PressurePipeGroup):
        """为命名有压段写入新旧两套身份字段。"""
        flow_section = PressurePipeDataExtractor._resolve_group_flow_section(group) or "-"
        name = str(getattr(group, "name", "") or "").strip()
        legacy_identity = make_pressure_pipe_identity(flow_section, name or "")
        segment_identity = PressurePipeDataExtractor._build_named_group_segment_identity(group)

        group.group_mode = "named_group"
        group.display_name = name or "未命名"
        group.legacy_storage_key = name or ""
        group.legacy_identity = legacy_identity
        group.storage_key = segment_identity
        group.identity = segment_identity
        group.target_row_index = coerce_row_index(getattr(group, "outlet_row_index", -1))
        group.upstream_row_index = coerce_row_index(getattr(group, "inlet_row_index", -1))

    @staticmethod
    def _finalize_named_pressure_group(group: PressurePipeGroup, nodes: List[ChannelNode], settings=None):
        """收口连续命名段，补齐推断字段和身份键。"""
        if group.inlet_row_index < 0 and len(group.row_indices) >= 2:
            group.inlet_row_index = group.row_indices[0]
            first_node = group.rows[0]
            group.design_flow = first_node.flow if first_node.flow > 0 else group.design_flow
            section_params = getattr(first_node, "section_params", {}) or {}
            group.diameter = section_params.get("D", 0) or section_params.get("直径D", 0) or group.diameter
            group.material_key = section_params.get("pipe_material", "") or group.material_key

        if group.outlet_row_index < 0 and len(group.row_indices) >= 2:
            group.outlet_row_index = group.row_indices[-1]

        PressurePipeDataExtractor._extract_ip_points(group)
        PressurePipeDataExtractor._calc_turn_angles(group)
        PressurePipeDataExtractor._calc_plan_segments(group)
        PressurePipeDataExtractor._extract_adjacent_node_data(group, nodes)

        if settings is not None:
            PressurePipeDataExtractor._extract_transition_forms(group, settings)

        PressurePipeDataExtractor._apply_named_group_identity_fields(group)

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
    def _build_xxpipe_route_display_name(
        route_nodes: List[ChannelNode],
        flow_key: str,
        route_no: int,
    ) -> str:
        """生成人能看懂的 xx管 整线名称。"""
        flow_sections: List[str] = []
        for route_node in route_nodes or []:
            flow_section = str(getattr(route_node, "flow_section", "") or "").strip()
            if flow_section and flow_section not in flow_sections:
                flow_sections.append(flow_section)

        if len(flow_sections) <= 1:
            return f"流量段{flow_key} 整线{route_no}"

        for route_node in route_nodes or []:
            name = str(getattr(route_node, "name", "") or "").strip()
            if name:
                return f"{name}连续整线"

        return f"连续整线{route_no}"

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
    def _collect_chain_row_indices(chains: List[PressurePipeChain]) -> set[int]:
        """收集连续承压链覆盖的行号。"""
        row_indices: set[int] = set()
        for chain in list(chains or []):
            for member in list(getattr(chain, "members", []) or []):
                member_rows = [
                    idx for idx in (getattr(member, "row_indices", []) or [])
                    if isinstance(idx, int) and idx >= 0
                ]
                if member_rows:
                    row_indices.update(member_rows)
                    continue
                start_idx = coerce_row_index(getattr(member, "start_row_index", -1))
                end_idx = coerce_row_index(getattr(member, "end_row_index", start_idx))
                if start_idx >= 0 and end_idx >= start_idx:
                    row_indices.update(range(start_idx, end_idx + 1))
        return row_indices

    @staticmethod
    def _build_xxpipe_route_contexts(
        nodes: List[ChannelNode],
        groups: List[PressurePipeGroup],
        chains: Optional[List[PressurePipeChain]] = None,
        tighten_to_active_bounds: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """构造连续承压整线上下文。"""
        route_contexts: Dict[str, Dict[str, Any]] = {}
        row_to_route_key: Dict[int, str] = {}
        flow_route_seq: Dict[str, int] = defaultdict(int)
        active_row_indices = PressurePipeDataExtractor._collect_chain_row_indices(chains or [])
        route_member_keys: Dict[str, List[str]] = defaultdict(list)
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
                end_idx += 1

            active_indices_in_range = [
                row_idx for row_idx in range(start_idx, end_idx + 1)
                if row_idx in active_row_indices
            ]
            if active_row_indices and not active_indices_in_range:
                idx = end_idx + 1
                continue

            effective_start_idx = start_idx
            effective_end_idx = end_idx
            if tighten_to_active_bounds and active_indices_in_range:
                # 支渠 route 上下文只覆盖收紧后的链成员区间，
                # 不再把首个真正有压段之前的前置隧洞带进去。
                effective_start_idx = active_indices_in_range[0]
                effective_end_idx = active_indices_in_range[-1]

            flow_key = flow_section or "-"
            flow_route_seq[flow_key] += 1
            route_no = flow_route_seq[flow_key]
            route_key = f"flow{flow_key}-route{route_no}"
            route_nodes = nodes[effective_start_idx : effective_end_idx + 1]
            route_display_name = PressurePipeDataExtractor._build_xxpipe_route_display_name(
                route_nodes,
                flow_key,
                route_no,
            )
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
                "route_start_row_index": effective_start_idx,
                "route_end_row_index": effective_end_idx,
                "route_start_mc": PressurePipeDataExtractor._resolve_node_station_mc(nodes[effective_start_idx]),
                "route_end_mc": PressurePipeDataExtractor._resolve_node_station_mc(nodes[effective_end_idx]),
                "route_ip_points": route_ip_points,
            }
            route_contexts[route_key] = route_context
            for row_idx in range(effective_start_idx, effective_end_idx + 1):
                row_to_route_key[row_idx] = route_key
            idx = end_idx + 1

        for group in groups or []:
            candidate_indices = [
                idx for idx in (getattr(group, "row_indices", []) or []) if isinstance(idx, int) and idx >= 0
            ]
            if not candidate_indices:
                target_row_index = coerce_row_index(getattr(group, "target_row_index", -1))
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
        upstream_idx = coerce_row_index(getattr(group, "upstream_row_index", -1))
        target_idx = coerce_row_index(getattr(group, "target_row_index", -1))
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
        start_idx = coerce_row_index(getattr(group, "inlet_row_index", -1))
        end_idx = coerce_row_index(getattr(group, "outlet_row_index", -1))
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
    def _resolve_unnamed_segment_start_node(group: PressurePipeGroup, nodes: List[ChannelNode]) -> Optional[ChannelNode]:
        """解析匿名普通有压段的起点节点。"""
        upstream_idx = coerce_row_index(getattr(group, "upstream_row_index", -1))
        target_idx = coerce_row_index(getattr(group, "target_row_index", -1))
        target_node = nodes[target_idx] if 0 <= target_idx < len(nodes) else None
        upstream_node = nodes[upstream_idx] if 0 <= upstream_idx < len(nodes) else None
        if upstream_node is None:
            return target_node
        # 跨流量段时，匿名普通段的自身范围应从本段首点开始，
        # 不能把上一流量段尾点到本段首点的边界距离带进来。
        target_flow_section = str(getattr(target_node, "flow_section", "") or "").strip() if target_node else ""
        upstream_flow_section = str(getattr(upstream_node, "flow_section", "") or "").strip()
        if target_flow_section and upstream_flow_section and target_flow_section != upstream_flow_section:
            return target_node
        if PressurePipeDataExtractor._is_tunnel_structure(upstream_node) and getattr(upstream_node, "in_out", None) == InOutType.NORMAL:
            return target_node
        return upstream_node

    @staticmethod
    def _resolve_group_segment_range(group: PressurePipeGroup, nodes: List[ChannelNode]) -> Tuple[float, float]:
        """解析当前分组自身桩号范围。"""
        if str(getattr(group, "group_mode", "") or "").strip() in {"unnamed_row_segment", "named_row_segment"}:
            target_idx = coerce_row_index(getattr(group, "target_row_index", -1))
            start_node = PressurePipeDataExtractor._resolve_unnamed_segment_start_node(group, nodes)
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
            [coerce_row_index(getattr(group, "target_row_index", -1))]
        )
        group.route_start_mc = segment_start_mc
        group.route_end_mc = segment_end_mc
        group.route_ip_points = route_points
        member_key = str(getattr(group, "identity", "") or getattr(group, "storage_key", "") or "").strip()
        group.route_member_keys = [member_key] if member_key else []
        group.segment_start_mc = segment_start_mc
        group.segment_end_mc = segment_end_mc

    @staticmethod
    def _find_route_context_for_group(
        group: PressurePipeGroup,
        route_contexts: Dict[str, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """按行号范围找到当前分组所属的整线上下文。"""
        row_candidates = [
            idx for idx in (getattr(group, "row_indices", []) or []) if isinstance(idx, int) and idx >= 0
        ]
        if not row_candidates:
            target_row_index = coerce_row_index(getattr(group, "target_row_index", -1))
            if target_row_index >= 0:
                row_candidates.append(target_row_index)

        for route_context in route_contexts.values():
            route_start = coerce_row_index(route_context.get("route_start_row_index", -1))
            route_end = coerce_row_index(route_context.get("route_end_row_index", -1))
            if any(route_start <= row_idx <= route_end for row_idx in row_candidates):
                return route_context
        return None

    @staticmethod
    def _apply_route_context(group: PressurePipeGroup, route_contexts: Dict[str, Dict[str, Any]]):
        """将整线上下文写入分组。"""
        selected_route = PressurePipeDataExtractor._find_route_context_for_group(group, route_contexts)
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
    def _apply_route_contexts_to_chain_members(
        nodes: List[ChannelNode],
        chains: List[PressurePipeChain],
        route_contexts: Dict[str, Dict[str, Any]],
    ):
        """把整线上下文同步到连续承压链成员。"""
        if not route_contexts:
            return
        for chain in list(chains or []):
            for member in list(getattr(chain, "members", []) or []):
                group = getattr(member, "group", None)
                if group is not None:
                    PressurePipeDataExtractor._apply_default_route_context(group, nodes)
                    PressurePipeDataExtractor._apply_route_context(group, route_contexts)
                    member.route_key = str(getattr(group, "route_key", "") or "").strip()
                    member.route_display_name = str(getattr(group, "route_display_name", "") or "").strip()
                    continue

                row_candidates = [
                    idx for idx in (getattr(member, "row_indices", []) or [])
                    if isinstance(idx, int) and idx >= 0
                ]
                if not row_candidates:
                    target_row_index = coerce_row_index(getattr(member, "target_row_index", -1))
                    if target_row_index >= 0:
                        row_candidates.append(target_row_index)
                for route_context in route_contexts.values():
                    route_start = coerce_row_index(route_context.get("route_start_row_index", -1))
                    route_end = coerce_row_index(route_context.get("route_end_row_index", -1))
                    if any(route_start <= row_idx <= route_end for row_idx in row_candidates):
                        member.route_key = str(route_context.get("route_key", "") or "").strip()
                        member.route_display_name = str(
                            route_context.get("route_display_name", "") or ""
                        ).strip()
                        break

    @staticmethod
    def _build_chain_member_metadata_map(chains: List[PressurePipeChain]) -> Dict[str, Dict[str, Any]]:
        """按身份键汇总链成员元数据，供对话框分组复用。"""
        metadata_map: Dict[str, Dict[str, Any]] = {}
        for chain in list(chains or []):
            for member in list(getattr(chain, "members", []) or []):
                identity = str(getattr(member, "identity", "") or "").strip()
                storage_key = str(getattr(member, "storage_key", "") or "").strip()
                identity_aliases = [
                    str(alias or "").strip()
                    for alias in list(getattr(member, "identity_aliases", []) or [])
                    if str(alias or "").strip()
                ]
                metadata = {
                    "identity": identity,
                    "storage_key": storage_key or identity,
                    "display_name": str(getattr(member, "display_name", "") or "").strip(),
                    "member_role": str(getattr(member, "member_role", "") or "").strip(),
                    "is_anchor_member": bool(getattr(member, "is_anchor_member", False)),
                    "should_generate_row_loss": bool(getattr(member, "should_generate_row_loss", True)),
                    "prefix_target_row_index": coerce_row_index(
                        getattr(member, "prefix_target_row_index", -1)
                    ),
                    "prefix_end_row_index": coerce_row_index(
                        getattr(member, "prefix_end_row_index", -1)
                    ),
                }
                for key in [identity, storage_key, *identity_aliases]:
                    if key:
                        metadata_map[key] = dict(metadata)
        return metadata_map

    @staticmethod
    def _build_chain_split_metadata_map(chains: List[PressurePipeChain]) -> Dict[str, List[str]]:
        """按原命名组身份键汇总逐段成员身份列表。"""
        split_map: Dict[str, List[str]] = {}
        for chain in list(chains or []):
            for member in list(getattr(chain, "members", []) or []):
                member_identity = str(getattr(member, "identity", "") or "").strip()
                if not member_identity:
                    continue
                source_aliases = []
                for candidate in (
                    *list(getattr(member, "source_identity_aliases", []) or []),
                    getattr(member, "parent_group_identity", ""),
                    getattr(member, "parent_group_storage_key", ""),
                ):
                    candidate_text = str(candidate or "").strip()
                    if candidate_text and candidate_text not in source_aliases:
                        source_aliases.append(candidate_text)
                for alias in source_aliases:
                    split_map.setdefault(alias, [])
                    if member_identity not in split_map[alias]:
                        split_map[alias].append(member_identity)
        return split_map

    @staticmethod
    def _apply_chain_split_metadata_to_group(
        group: PressurePipeGroup,
        split_map: Dict[str, List[str]],
    ):
        """把逐段回写标记同步到分组对象。"""
        identity = str(getattr(group, "identity", "") or "").strip()
        storage_key = str(getattr(group, "storage_key", "") or "").strip()
        split_ids = split_map.get(identity) or split_map.get(storage_key) or []
        group.split_to_row_members = bool(split_ids)
        group.split_row_member_identities = list(split_ids)

    @staticmethod
    def _apply_chain_member_metadata_to_group(
        group: PressurePipeGroup,
        metadata_map: Dict[str, Dict[str, Any]],
    ):
        """把链成员判定结果同步回分组对象。"""
        identity = str(getattr(group, "identity", "") or "").strip()
        storage_key = str(getattr(group, "storage_key", "") or "").strip()
        metadata = metadata_map.get(identity) or metadata_map.get(storage_key)
        if not metadata:
            return

        normalized_identity = str(metadata.get("identity", "") or "").strip()
        if normalized_identity:
            group.identity = normalized_identity
        normalized_storage_key = str(
            metadata.get("storage_key", "")
            or normalized_identity
            or getattr(group, "storage_key", "")
        ).strip()
        if normalized_storage_key:
            group.storage_key = normalized_storage_key

        display_name = str(metadata.get("display_name", "") or "").strip()
        if display_name:
            group.display_name = display_name

        group.member_role = str(metadata.get("member_role", "") or "").strip()
        group.is_anchor_member = bool(metadata.get("is_anchor_member", False))
        group.should_generate_row_loss = bool(metadata.get("should_generate_row_loss", True))
        group.prefix_target_row_index = coerce_row_index(
            metadata.get("prefix_target_row_index", -1)
        )
        group.prefix_end_row_index = coerce_row_index(
            metadata.get("prefix_end_row_index", -1)
        )

        if group.target_row_index < 0 and group.prefix_target_row_index >= 0:
            group.target_row_index = group.prefix_target_row_index

    @staticmethod
    def _coerce_segment_row_index(value, default: int = -1) -> int:
        """将 route / segment 行号安全转成整数。"""
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        return number if number >= 0 else default

    @staticmethod
    def _resolve_pressure_segment_base_name(group: PressurePipeGroup) -> str:
        """解析子段基础名称，避免把展示后缀写进 DXF 名称。"""
        base_name = str(getattr(group, "name", "") or "").strip()
        if base_name:
            return base_name
        for row in list(getattr(group, "rows", []) or []):
            row_name = str(getattr(row, "name", "") or "").strip()
            if row_name:
                return row_name
        return ""

    @staticmethod
    def _build_pressure_segment_from_group(group: PressurePipeGroup) -> PressureSegment:
        """把现有分组对象转换成稳定子段对象。"""
        row_indices = [
            idx for idx in (getattr(group, "row_indices", []) or [])
            if isinstance(idx, int) and idx >= 0
        ]
        start_row_index = min(row_indices) if row_indices else PressurePipeDataExtractor._coerce_segment_row_index(
            getattr(group, "target_row_index", -1)
        )
        end_row_index = max(row_indices) if row_indices else start_row_index
        base_name = PressurePipeDataExtractor._resolve_pressure_segment_base_name(group)
        member_display_name = str(
            getattr(group, "display_name", "")
            or base_name
            or getattr(group, "storage_key", "")
            or getattr(group, "identity", "")
        ).strip()
        structure_type = PressurePipeDataExtractor._resolve_group_structure_type(group)
        try:
            start_mc = float(getattr(group, "segment_start_mc", 0.0) or 0.0)
        except (TypeError, ValueError):
            start_mc = 0.0
        try:
            end_mc = float(getattr(group, "segment_end_mc", start_mc) or start_mc)
        except (TypeError, ValueError):
            end_mc = start_mc
        return PressureSegment(
            identity=str(getattr(group, "identity", "") or getattr(group, "storage_key", "") or "").strip(),
            route_key=str(getattr(group, "route_key", "") or "").strip(),
            base_name=base_name,
            member_display_name=member_display_name,
            dxf_display_name=base_name,
            structure_type=structure_type,
            member_role=str(getattr(group, "member_role", "") or "").strip(),
            start_row_index=start_row_index,
            end_row_index=end_row_index,
            target_row_index=PressurePipeDataExtractor._coerce_segment_row_index(
                getattr(group, "target_row_index", -1)
            ),
            upstream_row_index=PressurePipeDataExtractor._coerce_segment_row_index(
                getattr(group, "upstream_row_index", -1)
            ),
            start_mc=start_mc,
            end_mc=end_mc,
            is_pressurized_tail_member=bool(str(getattr(group, "route_key", "") or "").strip()),
        )

    @staticmethod
    def _build_pressure_pipe_row_identity(node: ChannelNode, row_index: int) -> str:
        """构造匿名有压管道行稳定标识。"""
        identity = str(getattr(node, "pressure_pipe_row_identity", "") or "").strip()
        if identity:
            return identity
        return PressurePipeDataExtractor._build_pressure_pipe_row_identity_from_flow_section(
            getattr(node, "flow_section", ""),
            row_index,
        )

    @staticmethod
    def _build_unnamed_display_name(node: ChannelNode, row_index: int) -> str:
        """构造匿名段展示名称。"""
        flow_section = str(getattr(node, "flow_section", "") or "").strip() or "-"
        return f"流量段{flow_section} 第{int(row_index) + 1}行有压管道"

    @staticmethod
    def _build_single_row_pressure_like_display_name(node: ChannelNode, row_index: int) -> str:
        """构造匿名有压同类结构展示名称。"""
        structure_type = getattr(node, "structure_type", None)
        structure_text = getattr(structure_type, "value", structure_type) or ""
        structure_text = str(structure_text).strip() or "有压管道"
        flow_section = str(getattr(node, "flow_section", "") or "").strip() or "-"
        if structure_text == StructureType.PRESSURE_PIPE.value:
            return PressurePipeDataExtractor._build_unnamed_display_name(node, row_index)
        return f"流量段{flow_section} 第{int(row_index) + 1}行{structure_text}"

    @staticmethod
    def _build_single_row_chain_identity(node: ChannelNode, row_index: int) -> str:
        """构造单行链成员稳定标识。"""
        if PressurePipeDataExtractor._is_unnamed_pressure_pipe_like(node):
            return PressurePipeDataExtractor._build_pressure_pipe_row_identity(node, row_index)
        flow_section = str(getattr(node, "flow_section", "") or "").strip()
        structure_type = getattr(node, "structure_type", None)
        structure_text = getattr(structure_type, "value", structure_type) or "row"
        structure_slug = (
            str(structure_text)
            .replace(" ", "")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
        row_part = f"row{int(row_index) + 1}"
        if flow_section:
            return f"flow{flow_section}-{row_part}-{structure_slug}"
        return f"{row_part}-{structure_slug}"

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
            "station_mc": PressurePipeDataExtractor._resolve_node_station_mc(node),
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
    def _build_single_row_pressure_like_group(nodes: List[ChannelNode], row_index: int, settings=None) -> Optional[PressurePipeGroup]:
        """构造匿名有压同类单行成员的分组对象。"""
        node = nodes[row_index]
        if not PressurePipeDataExtractor._is_unnamed_pressure_pipe_like(node):
            return None
        if PressurePipeDataExtractor._is_unnamed_regular_pressure_pipe(node):
            return PressurePipeDataExtractor._build_unnamed_row_group(nodes, row_index, settings=settings)

        upstream_index = PressurePipeDataExtractor._find_previous_regular_row_index(nodes, row_index)
        upstream_node = nodes[upstream_index] if 0 <= upstream_index < len(nodes) else None
        section_params = getattr(node, "section_params", {}) or {}
        storage_key = PressurePipeDataExtractor._build_single_row_chain_identity(node, row_index)
        display_name = PressurePipeDataExtractor._build_single_row_pressure_like_display_name(node, row_index)
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
    def _is_named_pressure_tail_structure_text(structure_type: str) -> bool:
        """判断该结构是否属于本次需要逐段拆分的命名承压结构。"""
        return str(structure_type or "").strip() in {
            StructureType.PRESSURE_PIPE.value,
            StructureType.DIRECTIONAL_DRILL.value,
            StructureType.PIPE_JACKING.value,
        }

    @staticmethod
    def _build_named_tail_row_segment_group(
        nodes: List[ChannelNode],
        parent_group: PressurePipeGroup,
        target_row_index: int,
        upstream_row_index: int,
        settings=None,
    ) -> Optional[PressurePipeGroup]:
        """按“上一承压/普通行 -> 当前行”口径构造命名承压逐段分组。"""
        if not (0 <= target_row_index < len(nodes)):
            return None

        target_node = nodes[target_row_index]
        upstream_node = nodes[upstream_row_index] if 0 <= upstream_row_index < len(nodes) else None
        section_params = getattr(target_node, "section_params", {}) or {}
        display_name = str(
            getattr(parent_group, "display_name", "")
            or getattr(parent_group, "name", "")
            or getattr(target_node, "name", "")
            or "未命名承压段"
        ).strip()
        storage_key = PressurePipeDataExtractor._build_pressure_pipe_row_identity(
            target_node,
            target_row_index,
        )
        design_flow = float(
            getattr(target_node, "flow", 0.0)
            or getattr(parent_group, "design_flow", 0.0)
            or 0.0
        )
        diameter = (
            section_params.get("D", 0.0)
            or section_params.get("直径D", 0.0)
            or getattr(parent_group, "diameter", 0.0)
            or 0.0
        )
        material_key = str(
            section_params.get("pipe_material", "")
            or getattr(parent_group, "material_key", "")
            or ""
        )
        group = PressurePipeGroup(
            name=str(getattr(parent_group, "name", "") or getattr(target_node, "name", "") or "").strip(),
            rows=[target_node],
            row_indices=[target_row_index],
            inlet_row_index=upstream_row_index,
            outlet_row_index=target_row_index,
            ip_row_indices=[],
            design_flow=design_flow,
            diameter=float(diameter or 0.0),
            material_key=material_key,
            local_loss_ratio=float(
                getattr(parent_group, "local_loss_ratio", section_params.get("local_loss_ratio", 0.15))
                or 0.15
            ),
            plan_segments=[],
            plan_total_length=0.0,
            inlet_transition_form=str(getattr(parent_group, "inlet_transition_form", "") or "反弯扭曲面"),
            outlet_transition_form=str(getattr(parent_group, "outlet_transition_form", "") or "反弯扭曲面"),
            inlet_transition_zeta=float(getattr(parent_group, "inlet_transition_zeta", 0.10) or 0.10),
            outlet_transition_zeta=float(getattr(parent_group, "outlet_transition_zeta", 0.20) or 0.20),
            group_mode="named_row_segment",
            display_name=display_name,
            storage_key=storage_key,
            identity=storage_key,
            target_row_index=target_row_index,
            upstream_row_index=upstream_row_index,
            route_key=str(getattr(parent_group, "route_key", "") or "").strip(),
            route_display_name=str(getattr(parent_group, "route_display_name", "") or "").strip(),
            route_start_row_index=coerce_row_index(getattr(parent_group, "route_start_row_index", -1)),
            route_end_row_index=coerce_row_index(getattr(parent_group, "route_end_row_index", -1)),
            route_start_mc=float(getattr(parent_group, "route_start_mc", 0.0) or 0.0),
            route_end_mc=float(getattr(parent_group, "route_end_mc", 0.0) or 0.0),
            route_ip_points=[dict(point) for point in (getattr(parent_group, "route_ip_points", []) or [])],
            route_member_keys=list(getattr(parent_group, "route_member_keys", []) or []),
            segment_start_mc=PressurePipeDataExtractor._resolve_node_station_mc(upstream_node),
            segment_end_mc=PressurePipeDataExtractor._resolve_node_station_mc(target_node),
            has_inlet_transition=bool(getattr(parent_group, "has_inlet_transition", True)),
            has_outlet_transition=bool(getattr(parent_group, "has_outlet_transition", True)),
            inlet_transition_reason=str(getattr(parent_group, "inlet_transition_reason", "") or "").strip(),
            outlet_transition_reason=str(getattr(parent_group, "outlet_transition_reason", "") or "").strip(),
        )

        ip_points: List[Dict[str, Any]] = []
        if PressurePipeDataExtractor._can_use_plan_point(upstream_node):
            ip_points.append(PressurePipeDataExtractor._make_plan_point(upstream_node, in_out_text="进"))
        if PressurePipeDataExtractor._can_use_plan_point(target_node):
            ip_points.append(PressurePipeDataExtractor._make_plan_point(target_node, in_out_text="出"))
        group.ip_points = ip_points
        if len(ip_points) >= 2:
            PressurePipeDataExtractor._calc_plan_segments(group)

        PressurePipeDataExtractor._extract_adjacent_node_data_for_unnamed_segment(group, nodes)
        if settings is not None:
            PressurePipeDataExtractor._extract_transition_forms(group, settings)
        return group

    @staticmethod
    def _build_named_tail_row_segment_member(
        nodes: List[ChannelNode],
        parent_group: PressurePipeGroup,
        row_index: int,
        settings=None,
    ) -> Optional[PressurePipeChainMember]:
        """把命名承压组中的单行拆成连续承压逐段成员。"""
        if not (0 <= row_index < len(nodes)):
            return None
        target_node = nodes[row_index]
        upstream_index = PressurePipeDataExtractor._find_previous_regular_row_index(nodes, row_index)
        segment_group = PressurePipeDataExtractor._build_named_tail_row_segment_group(
            nodes,
            parent_group,
            row_index,
            upstream_index,
            settings=settings,
        )
        if segment_group is None:
            return None

        display_name = str(
            getattr(parent_group, "display_name", "")
            or getattr(parent_group, "name", "")
            or getattr(target_node, "name", "")
            or "未命名承压段"
        ).strip()
        parent_identity = str(getattr(parent_group, "identity", "") or "").strip()
        parent_storage_key = str(getattr(parent_group, "storage_key", "") or "").strip()
        identity = str(getattr(segment_group, "identity", "") or "").strip()
        storage_key = str(getattr(segment_group, "storage_key", "") or identity).strip() or identity
        return PressurePipeChainMember(
            member_type="single_row",
            display_name=display_name,
            flow_section=PressurePipeDataExtractor._resolve_group_flow_section(parent_group),
            structure_type=PressurePipeDataExtractor._resolve_node_structure_text(target_node),
            row_indices=[row_index],
            start_row_index=row_index,
            end_row_index=row_index,
            identity=identity,
            storage_key=storage_key,
            target_row_index=row_index,
            upstream_row_index=upstream_index,
            group=segment_group,
            node=target_node,
            base_display_name=display_name,
            member_role=PressurePipeDataExtractor._resolve_chain_member_role(
                PressurePipeDataExtractor._resolve_node_structure_text(target_node)
            ),
            should_generate_row_loss=upstream_index >= 0,
            source_identity_aliases=[
                alias for alias in [parent_identity, parent_storage_key]
                if str(alias or "").strip()
            ],
            parent_group_identity=parent_identity,
            parent_group_storage_key=parent_storage_key,
            split_from_named_group=True,
            route_key=str(getattr(segment_group, "route_key", "") or "").strip(),
            route_display_name=str(getattr(segment_group, "route_display_name", "") or "").strip(),
        )

    @staticmethod
    def _should_split_named_chain_member_into_row_members(
        chain: Optional[PressurePipeChain],
        member: Optional[PressurePipeChainMember],
        settings=None,
    ) -> bool:
        """判断 xx渠 连续承压尾段中的命名承压组是否要改成逐段成员。"""
        if member is None or getattr(member, "member_type", "") != "named_group":
            return False
        members = list(getattr(chain, "members", []) or []) if chain is not None else []
        if not members or members[-1] is not member:
            return False
        if PressurePipeDataExtractor._is_xxpipe_channel_level(settings):
            return False
        if bool(getattr(member, "is_anchor_member", False)) or not bool(
            getattr(member, "should_generate_row_loss", True)
        ):
            return False
        if str(getattr(member, "member_role", "") or "").strip() == "prefix_segment":
            return False
        structure_type = str(getattr(member, "structure_type", "") or "").strip()
        if not PressurePipeDataExtractor._is_named_pressure_tail_structure_text(structure_type):
            return False
        row_indices = [
            idx for idx in (getattr(member, "row_indices", []) or [])
            if isinstance(idx, int) and idx >= 0
        ]
        if len(row_indices) < 3:
            return False
        entered_pressurized_at_row = PressurePipeDataExtractor._resolve_route_entered_pressurized_at_row(chain)
        if entered_pressurized_at_row >= 0 and min(row_indices) < entered_pressurized_at_row:
            return False
        return getattr(member, "group", None) is not None

    @staticmethod
    def _expand_named_tail_chain_members(
        chain: Optional[PressurePipeChain],
        nodes: List[ChannelNode],
        settings=None,
    ) -> None:
        """把 xx渠 连续承压尾段中的命名承压组展开成逐段链成员。"""
        if chain is None:
            return
        original_members = list(getattr(chain, "members", []) or [])
        if not original_members:
            return

        expanded_members: List[PressurePipeChainMember] = []
        changed = False
        for member in original_members:
            if not PressurePipeDataExtractor._should_split_named_chain_member_into_row_members(
                chain,
                member,
                settings=settings,
            ):
                expanded_members.append(member)
                continue

            parent_group = getattr(member, "group", None)
            row_indices = [
                idx for idx in (getattr(member, "row_indices", []) or [])
                if isinstance(idx, int) and idx >= 0
            ]
            split_members = []
            for row_index in row_indices:
                row_member = PressurePipeDataExtractor._build_named_tail_row_segment_member(
                    nodes,
                    parent_group,
                    row_index,
                    settings=settings,
                )
                if row_member is not None:
                    split_members.append(row_member)
            if split_members:
                expanded_members.extend(split_members)
                changed = True
                continue
            expanded_members.append(member)

        if not changed:
            return

        for member in original_members:
            parent_group = getattr(member, "group", None)
            if parent_group is None:
                continue
            split_member_identities = [
                str(getattr(split_member, "identity", "") or "").strip()
                for split_member in expanded_members
                if bool(getattr(split_member, "split_from_named_group", False))
                and (
                    str(getattr(split_member, "parent_group_identity", "") or "").strip()
                    == str(getattr(parent_group, "identity", "") or "").strip()
                    or str(getattr(split_member, "parent_group_storage_key", "") or "").strip()
                    == str(getattr(parent_group, "storage_key", "") or "").strip()
                )
            ]
            parent_group.split_to_row_members = bool(split_member_identities)
            parent_group.split_row_member_identities = list(split_member_identities)

        chain.members = expanded_members
        valid_start_indices = [
            int(getattr(member, "start_row_index", -1))
            for member in expanded_members
            if int(getattr(member, "start_row_index", -1)) >= 0
        ]
        valid_end_indices = [
            int(getattr(member, "end_row_index", -1))
            for member in expanded_members
            if int(getattr(member, "end_row_index", -1)) >= 0
        ]
        if valid_start_indices:
            chain.start_row_index = min(valid_start_indices)
        if valid_end_indices:
            chain.end_row_index = max(valid_end_indices)
        PressurePipeDataExtractor._apply_chain_member_display_labels(chain)
        for member in expanded_members:
            PressurePipeDataExtractor._sync_chain_member_metadata_to_group(member)

    @staticmethod
    def _build_named_chain_member(group: PressurePipeGroup) -> PressurePipeChainMember:
        """把命名有压组包装成链成员。"""
        row_indices = [idx for idx in (group.row_indices or []) if isinstance(idx, int)]
        start_row_index = min(row_indices) if row_indices else -1
        end_row_index = max(row_indices) if row_indices else start_row_index
        display_name = group.display_name or group.name or "未命名"
        structure_type = PressurePipeDataExtractor._resolve_group_structure_type(group)
        identity_aliases = []
        for candidate in (
            getattr(group, "identity", ""),
            getattr(group, "storage_key", ""),
            getattr(group, "legacy_identity", ""),
            getattr(group, "legacy_storage_key", ""),
        ):
            candidate_text = str(candidate or "").strip()
            if candidate_text and candidate_text not in identity_aliases:
                identity_aliases.append(candidate_text)
        return PressurePipeChainMember(
            member_type="named_group",
            display_name=display_name,
            flow_section=PressurePipeDataExtractor._resolve_group_flow_section(group),
            structure_type=structure_type,
            row_indices=row_indices,
            start_row_index=start_row_index,
            end_row_index=end_row_index,
            identity=str(getattr(group, "identity", "") or ""),
            storage_key=str(getattr(group, "storage_key", "") or ""),
            target_row_index=coerce_row_index(getattr(group, "target_row_index", group.outlet_row_index), group.outlet_row_index),
            upstream_row_index=coerce_row_index(getattr(group, "upstream_row_index", group.inlet_row_index), group.inlet_row_index),
            group=group,
            base_display_name=display_name,
            identity_aliases=identity_aliases,
            member_role=PressurePipeDataExtractor._resolve_chain_member_role(structure_type),
            should_generate_row_loss=True,
            parent_group_identity=str(getattr(group, "identity", "") or "").strip(),
            parent_group_storage_key=str(getattr(group, "storage_key", "") or "").strip(),
        )

    @staticmethod
    def _build_single_row_chain_member(
        nodes: List[ChannelNode],
        row_index: int,
        settings=None,
    ) -> Optional[PressurePipeChainMember]:
        """按单行规则构造链成员。"""
        node = nodes[row_index]
        structure_type = node.structure_type.value if node.structure_type else ""
        upstream_index = PressurePipeDataExtractor._find_previous_regular_row_index(nodes, row_index)
        group = PressurePipeDataExtractor._build_single_row_pressure_like_group(nodes, row_index, settings=settings)

        if PressurePipeDataExtractor._is_unnamed_pressure_pipe_like(node):
            display_name = PressurePipeDataExtractor._build_single_row_pressure_like_display_name(node, row_index)
        elif PressurePipeDataExtractor._is_tunnel_structure(node) and node.in_out == InOutType.NORMAL:
            display_name = str(getattr(node, "name", "") or "").strip() or f"流量段{node.flow_section or '-'} 第{row_index + 1}行隧洞"
        else:
            return None

        identity = (
            str(getattr(group, "identity", "") or "").strip()
            if group is not None
            else PressurePipeDataExtractor._build_single_row_chain_identity(node, row_index)
        )
        storage_key = (
            str(getattr(group, "storage_key", "") or "").strip()
            if group is not None
            else identity
        )

        return PressurePipeChainMember(
            member_type="single_row",
            display_name=display_name,
            flow_section=str(getattr(node, "flow_section", "") or "").strip(),
            structure_type=structure_type,
            row_indices=[row_index],
            start_row_index=row_index,
            end_row_index=row_index,
            identity=identity,
            storage_key=storage_key,
            target_row_index=row_index,
            upstream_row_index=upstream_index,
            group=group,
            node=node,
            base_display_name=display_name,
            member_role=PressurePipeDataExtractor._resolve_chain_member_role(structure_type),
            should_generate_row_loss=True,
        )

    @staticmethod
    def _collect_named_group_identity_aliases(group: Optional[PressurePipeGroup]) -> List[str]:
        """收集命名有压组的历史身份键，供逐段成员回溯原组。"""
        if group is None:
            return []
        aliases: List[str] = []
        for candidate in (
            getattr(group, "identity", ""),
            getattr(group, "storage_key", ""),
            getattr(group, "legacy_identity", ""),
            getattr(group, "legacy_storage_key", ""),
        ):
            candidate_text = str(candidate or "").strip()
            if candidate_text and candidate_text not in aliases:
                aliases.append(candidate_text)
        return aliases

    @staticmethod
    def _resolve_chain_member_role(structure_type: str) -> str:
        """按结构形式归类链成员角色。"""
        if str(structure_type or "").strip() == StructureType.PRESSURE_PIPE.value:
            return "regular_segment"
        return "special_segment"

    @staticmethod
    def _get_chain_member_base_display_name(member: Optional[PressurePipeChainMember]) -> str:
        """返回链成员未加后缀的基础展示名称。"""
        if member is None:
            return ""
        return str(
            getattr(member, "base_display_name", "")
            or getattr(member, "display_name", "")
            or ""
        ).strip()

    @staticmethod
    def _set_chain_member_display_name(member: Optional[PressurePipeChainMember], display_name: str):
        """只更新链成员展示名称，避免污染整线和分组展示名称。"""
        if member is None:
            return
        text = str(display_name or "").strip()
        if not text:
            return
        member.display_name = text

    @staticmethod
    def _safe_int(value, default: int = -1) -> int:
        """将任意索引安全转成整数。"""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        """将任意桩号安全转成浮点数。"""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if math.isnan(number) or math.isinf(number):
            return default
        return number

    @staticmethod
    def _merge_index_min(current, candidate) -> int:
        """合并起点索引。"""
        current_value = PressurePipeDataExtractor._safe_int(current, default=-1)
        candidate_value = PressurePipeDataExtractor._safe_int(candidate, default=-1)
        if current_value < 0:
            return candidate_value
        if candidate_value < 0:
            return current_value
        return min(current_value, candidate_value)

    @staticmethod
    def _merge_index_max(current, candidate) -> int:
        """合并终点索引。"""
        current_value = PressurePipeDataExtractor._safe_int(current, default=-1)
        candidate_value = PressurePipeDataExtractor._safe_int(candidate, default=-1)
        return max(current_value, candidate_value)

    @staticmethod
    def _resolve_pressure_route_key(chain: Optional[PressurePipeChain], chain_index: int) -> str:
        """解析连续承压整线稳定键。"""
        for member in list(getattr(chain, "members", []) or []):
            group = getattr(member, "group", None)
            route_key = str(getattr(group, "route_key", "") or "").strip()
            if route_key:
                return route_key
        start_row_index = PressurePipeDataExtractor._safe_int(getattr(chain, "start_row_index", -1), default=-1)
        end_row_index = PressurePipeDataExtractor._safe_int(getattr(chain, "end_row_index", start_row_index), default=start_row_index)
        return f"pressure-route-{chain_index}-r{start_row_index + 1}-{end_row_index + 1}"

    @staticmethod
    def _resolve_pressure_route_display_name(chain: Optional[PressurePipeChain], route_key: str) -> str:
        """解析连续承压整线展示名称。"""
        for member in list(getattr(chain, "members", []) or []):
            group = getattr(member, "group", None)
            route_display_name = str(getattr(group, "route_display_name", "") or "").strip()
            if route_display_name:
                return route_display_name
        for member in list(getattr(chain, "members", []) or []):
            base_name = PressurePipeDataExtractor._get_chain_member_base_display_name(member)
            if base_name:
                return base_name
        return str(route_key or "").strip()

    @staticmethod
    def _resolve_route_entered_pressurized_at_row(chain: Optional[PressurePipeChain]) -> int:
        """解析真正进入承压尾链的起始行。"""
        members = list(getattr(chain, "members", []) or [])
        for member in members:
            structure_type = str(getattr(member, "structure_type", "") or "").strip()
            if structure_type in {"有压管道", "定向钻", "顶管"}:
                return PressurePipeDataExtractor._safe_int(
                    getattr(member, "start_row_index", -1),
                    default=-1,
                )
        if members:
            return PressurePipeDataExtractor._safe_int(getattr(members[0], "start_row_index", -1), default=-1)
        return -1

    @staticmethod
    def _resolve_pressure_segment_base_name(member: Optional[PressurePipeChainMember]) -> str:
        """返回用于 DXF 与业务归属的基础名称。"""
        base_name = PressurePipeDataExtractor._get_chain_member_base_display_name(member)
        if base_name:
            return base_name
        group = getattr(member, "group", None)
        if group is not None:
            group_name = str(getattr(group, "name", "") or "").strip()
            if group_name:
                return group_name
        node = getattr(member, "node", None)
        node_name = str(getattr(node, "name", "") or "").strip()
        if node_name:
            return node_name
        structure_type = str(getattr(member, "structure_type", "") or "").strip()
        return structure_type or "未命名承压段"

    @staticmethod
    def _resolve_pressure_segment_mc_range(
        member: Optional[PressurePipeChainMember],
        nodes: List[ChannelNode],
    ) -> Tuple[float, float]:
        """解析连续承压子段真实桩号范围。"""
        group = getattr(member, "group", None)
        member_role = str(getattr(member, "member_role", "") or "").strip()
        start_mc = None
        end_mc = None

        if group is not None:
            start_mc = getattr(group, "segment_start_mc", None)
            end_mc = getattr(group, "segment_end_mc", None)

        start_row_index = PressurePipeDataExtractor._safe_int(getattr(member, "start_row_index", -1), default=-1)
        end_row_index = PressurePipeDataExtractor._safe_int(getattr(member, "end_row_index", start_row_index), default=start_row_index)
        if member_role == "prefix_segment":
            start_row_index = PressurePipeDataExtractor._safe_int(
                getattr(member, "prefix_target_row_index", start_row_index),
                default=start_row_index,
            )
            end_row_index = PressurePipeDataExtractor._safe_int(
                getattr(member, "prefix_end_row_index", end_row_index),
                default=end_row_index,
            )
            start_mc = None
            end_mc = None

        if start_mc in (None, "") and 0 <= start_row_index < len(nodes):
            start_mc = getattr(nodes[start_row_index], "station_MC", None)
        if end_mc in (None, "") and 0 <= end_row_index < len(nodes):
            end_mc = getattr(nodes[end_row_index], "station_MC", None)

        start_value = PressurePipeDataExtractor._safe_float(start_mc, default=0.0)
        end_value = PressurePipeDataExtractor._safe_float(end_mc, default=start_value)
        if end_value < start_value:
            start_value, end_value = end_value, start_value
        return start_value, end_value

    @staticmethod
    def _build_pressure_route_segment(
        member: Optional[PressurePipeChainMember],
        nodes: List[ChannelNode],
        route_key: str,
    ) -> Optional[PressureSegment]:
        """把链成员翻译成稳定的 Route/Segment 对象。"""
        if member is None:
            return None
        identity = str(getattr(member, "identity", "") or "").strip()
        if not identity:
            return None
        base_name = PressurePipeDataExtractor._resolve_pressure_segment_base_name(member)
        member_display_name = str(getattr(member, "display_name", "") or base_name).strip() or base_name
        dxf_display_name = base_name
        structure_type = str(getattr(member, "structure_type", "") or "").strip()
        start_mc, end_mc = PressurePipeDataExtractor._resolve_pressure_segment_mc_range(member, nodes)
        return PressureSegment(
            identity=identity,
            route_key=str(route_key or "").strip(),
            base_name=base_name,
            member_display_name=member_display_name,
            dxf_display_name=dxf_display_name,
            structure_type=structure_type,
            member_role=str(getattr(member, "member_role", "") or "").strip(),
            start_row_index=PressurePipeDataExtractor._safe_int(getattr(member, "start_row_index", -1), default=-1),
            end_row_index=PressurePipeDataExtractor._safe_int(getattr(member, "end_row_index", -1), default=-1),
            target_row_index=PressurePipeDataExtractor._safe_int(getattr(member, "target_row_index", -1), default=-1),
            upstream_row_index=PressurePipeDataExtractor._safe_int(getattr(member, "upstream_row_index", -1), default=-1),
            start_mc=start_mc,
            end_mc=end_mc,
            is_pressurized_tail_member=True,
        )

    @staticmethod
    def _finalize_pressure_route_geometry(route: PressureRoute, nodes: List[ChannelNode]) -> None:
        """补齐整线起终点桩号与边界行。"""
        if not route.segments:
            return
        route.start_row_index = PressurePipeDataExtractor._merge_index_min(
            route.start_row_index,
            min(segment.start_row_index for segment in route.segments if segment.start_row_index >= 0),
        )
        route.end_row_index = PressurePipeDataExtractor._merge_index_max(
            route.end_row_index,
            max(segment.end_row_index for segment in route.segments if segment.end_row_index >= 0),
        )
        route.start_mc = min(segment.start_mc for segment in route.segments)
        route.end_mc = max(segment.end_mc for segment in route.segments)
        if not route.route_display_name:
            route.route_display_name = route.route_key

    @staticmethod
    def _is_regular_pressure_chain_member(member: Optional[PressurePipeChainMember]) -> bool:
        """判断链成员是否为普通有压子段。"""
        if member is None:
            return False
        return str(getattr(member, "structure_type", "") or "").strip() == StructureType.PRESSURE_PIPE.value

    @staticmethod
    def _is_branch_named_pressure_leading_boundary_member(
        member: Optional[PressurePipeChainMember],
    ) -> bool:
        """判断是否为支渠链首那种仅进口的命名普通有压边界行。"""
        if member is None:
            return False
        if member.member_type != "named_group":
            return False
        if not PressurePipeDataExtractor._is_regular_pressure_chain_member(member):
            return False

        group = getattr(member, "group", None)
        if group is None or group.is_valid():
            return False

        row_indices = [idx for idx in (getattr(group, "row_indices", []) or []) if isinstance(idx, int)]
        if len(row_indices) != 1:
            return False

        first_row = (getattr(group, "rows", []) or [None])[0]
        in_out_raw = PressurePipeDataExtractor._get_in_out_raw(first_row) if first_row is not None else ""
        return in_out_raw == "进" or getattr(first_row, "in_out", None) == InOutType.INLET

    @staticmethod
    def _is_branch_prefix_following_special_member(
        member: Optional[PressurePipeChainMember],
    ) -> bool:
        """判断前缀段后面紧跟的是否为可承接前缀长度的特殊承压段。"""
        structure_type = str(getattr(member, "structure_type", "") or "").strip()
        if not structure_type:
            return False
        if structure_type in {"定向钻", "顶管"}:
            return True
        return "隧洞" in structure_type

    @staticmethod
    def _should_mark_branch_named_pressure_prefix(
        chain: Optional[PressurePipeChain],
        member: Optional[PressurePipeChainMember],
    ) -> bool:
        """判断支渠链首命名普通有压是否应改记为前缀段。"""
        if chain is None or not PressurePipeDataExtractor._is_branch_named_pressure_leading_boundary_member(member):
            return False

        members = list(getattr(chain, "members", []) or [])
        if len(members) < 2:
            return False
        next_member = members[1]
        if not PressurePipeDataExtractor._is_branch_prefix_following_special_member(next_member):
            return False

        base_name = PressurePipeDataExtractor._get_chain_member_base_display_name(member)
        if not base_name:
            return False

        for later_member in members[1:]:
            if not PressurePipeDataExtractor._is_regular_pressure_chain_member(later_member):
                continue
            if PressurePipeDataExtractor._get_chain_member_base_display_name(later_member) == base_name:
                return True
        return False

    @staticmethod
    def _should_mark_branch_named_pressure_anchor(
        chain: Optional[PressurePipeChain],
        member: Optional[PressurePipeChainMember],
    ) -> bool:
        """判断支渠链首命名普通有压是否应降级为起点锚点。"""
        if chain is None or not PressurePipeDataExtractor._is_branch_named_pressure_leading_boundary_member(member):
            return False

        base_name = PressurePipeDataExtractor._get_chain_member_base_display_name(member)
        if not base_name:
            return False

        for later_member in list(getattr(chain, "members", []) or [])[1:]:
            if not PressurePipeDataExtractor._is_regular_pressure_chain_member(later_member):
                continue
            if PressurePipeDataExtractor._get_chain_member_base_display_name(later_member) == base_name:
                return True
        return False

    @staticmethod
    def _sync_chain_member_metadata_to_group(member: Optional[PressurePipeChainMember]):
        """把链成员角色与边界信息同步到命名分组对象。"""
        if member is None:
            return
        group = getattr(member, "group", None)
        if group is None:
            return

        identity = str(getattr(member, "identity", "") or "").strip()
        storage_key = str(getattr(member, "storage_key", "") or identity).strip()
        if identity:
            group.identity = identity
        if storage_key:
            group.storage_key = storage_key
        group.member_role = str(getattr(member, "member_role", "") or "").strip()
        group.is_anchor_member = bool(getattr(member, "is_anchor_member", False))
        group.should_generate_row_loss = bool(getattr(member, "should_generate_row_loss", True))
        group.prefix_target_row_index = coerce_row_index(
            getattr(member, "prefix_target_row_index", -1)
        )
        group.prefix_end_row_index = coerce_row_index(
            getattr(member, "prefix_end_row_index", -1)
        )
        display_name = str(getattr(member, "display_name", "") or "").strip()
        if display_name:
            group.display_name = display_name
        if group.target_row_index < 0 and group.prefix_target_row_index >= 0:
            group.target_row_index = group.prefix_target_row_index

    @staticmethod
    def _rewrite_branch_chain_member_identities(chain: Optional[PressurePipeChain]):
        """支渠连续承压命名成员统一改写为行身份。"""
        if chain is None:
            return
        for member in list(getattr(chain, "members", []) or []):
            if str(getattr(member, "member_type", "") or "").strip() != "named_group":
                continue
            start_row_index = coerce_row_index(getattr(member, "start_row_index", -1))
            if start_row_index < 0:
                continue
            aliases = []
            for candidate in [
                *list(getattr(member, "identity_aliases", []) or []),
                getattr(member, "identity", ""),
                getattr(member, "storage_key", ""),
            ]:
                candidate_text = str(candidate or "").strip()
                if candidate_text and candidate_text not in aliases:
                    aliases.append(candidate_text)
            member.identity_aliases = aliases
            new_identity = PressurePipeDataExtractor._build_pressure_pipe_row_identity_from_flow_section(
                getattr(member, "flow_section", ""),
                start_row_index,
            )
            member.identity = new_identity
            member.storage_key = new_identity

    @staticmethod
    def _apply_chain_member_display_labels(chain: Optional[PressurePipeChain]):
        """为链内成员追加可区分的展示后缀。"""
        if chain is None:
            return

        grouped_members: Dict[str, List[PressurePipeChainMember]] = defaultdict(list)
        for member in list(getattr(chain, "members", []) or []):
            base_name = PressurePipeDataExtractor._get_chain_member_base_display_name(member)
            if not base_name:
                continue
            grouped_members[base_name].append(member)

        for base_name, members in grouped_members.items():
            if len(members) == 1:
                member = members[0]
                member_role = str(getattr(member, "member_role", "") or "").strip()
                if member_role == "anchor":
                    PressurePipeDataExtractor._set_chain_member_display_name(
                        member, f"{base_name}（起点锚点）"
                    )
                elif member_role == "prefix_segment":
                    PressurePipeDataExtractor._set_chain_member_display_name(
                        member, f"{base_name}（前缀段）"
                    )
                else:
                    PressurePipeDataExtractor._set_chain_member_display_name(member, base_name)
                continue

            middle_index = 1
            for idx, member in enumerate(members):
                member_role = str(getattr(member, "member_role", "") or "").strip()
                if member_role == "anchor":
                    label = f"{base_name}（起点锚点）"
                elif member_role == "prefix_segment":
                    label = f"{base_name}（前缀段）"
                elif idx == len(members) - 1:
                    label = f"{base_name}（后段）"
                elif idx == 0:
                    label = f"{base_name}（前段）"
                else:
                    label = f"{base_name}（中段{middle_index}）"
                    middle_index += 1
                PressurePipeDataExtractor._set_chain_member_display_name(member, label)

    @staticmethod
    def _post_process_continuous_pressure_chain(chain: Optional[PressurePipeChain], settings=None):
        """对连续承压链做链首锚点和重名标签收口。"""
        if chain is None:
            return
        members = list(getattr(chain, "members", []) or [])
        if not members:
            return

        first_member = members[0]
        if (
            PressurePipeDataExtractor._should_tighten_branch_pressure_chain(settings)
            and PressurePipeDataExtractor._should_mark_branch_named_pressure_prefix(chain, first_member)
        ):
            first_member.is_anchor_member = False
            first_member.should_generate_row_loss = True
            first_member.member_role = "prefix_segment"
            first_member.prefix_target_row_index = coerce_row_index(
                getattr(first_member, "start_row_index", getattr(first_member, "target_row_index", -1))
            )
            first_member.prefix_end_row_index = coerce_row_index(
                getattr(members[1], "start_row_index", -1)
            )
            if first_member.target_row_index < 0 and first_member.prefix_target_row_index >= 0:
                first_member.target_row_index = first_member.prefix_target_row_index
        elif (
            PressurePipeDataExtractor._should_tighten_branch_pressure_chain(settings)
            and PressurePipeDataExtractor._should_mark_branch_named_pressure_anchor(chain, first_member)
        ):
            first_member.is_anchor_member = True
            first_member.should_generate_row_loss = False
            first_member.member_role = "anchor"

        for member in members:
            if getattr(member, "is_anchor_member", False) or not bool(
                getattr(member, "should_generate_row_loss", True)
            ):
                member.member_role = "anchor"
                continue
            if not str(getattr(member, "member_role", "") or "").strip():
                member.member_role = PressurePipeDataExtractor._resolve_chain_member_role(
                    str(getattr(member, "structure_type", "") or "").strip()
                )

        if PressurePipeDataExtractor._should_tighten_branch_pressure_chain(settings):
            PressurePipeDataExtractor._rewrite_branch_chain_member_identities(chain)

        PressurePipeDataExtractor._apply_chain_member_display_labels(chain)
        for member in members:
            PressurePipeDataExtractor._sync_chain_member_metadata_to_group(member)

    @staticmethod
    def _resolve_group_structure_type(group: PressurePipeGroup) -> str:
        """解析命名组的结构形式。"""
        rows = getattr(group, "rows", []) or []
        if not rows:
            return ""
        node = rows[0]
        return node.structure_type.value if getattr(node, "structure_type", None) else ""

    @staticmethod
    def _is_flow_section_anchor_member(nodes: List[ChannelNode], row_index: int) -> bool:
        """判断单行成员是否位于本流量段起点。"""
        if not (0 <= row_index < len(nodes)):
            return False

        current_flow_section = str(getattr(nodes[row_index], "flow_section", "") or "").strip()
        for index in range(row_index - 1, -1, -1):
            node = nodes[index]
            if getattr(node, "is_transition", False):
                continue
            if getattr(node, "is_auto_inserted_channel", False):
                continue
            previous_flow_section = str(getattr(node, "flow_section", "") or "").strip()
            return previous_flow_section != current_flow_section
        return True

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
            
            point = PressurePipeDataExtractor._make_plan_point(node, in_out_text=in_out_raw)
            point['turn_angle'] = 0  # 稍后统一计算
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
