# -*- coding: utf-8 -*-
"""
倒虹吸数据提取模块

从推求水面线表格数据中识别和提取倒虹吸分组信息。
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional
from collections import defaultdict

import sys
import os

_water_profile_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _water_profile_dir not in sys.path:
    sys.path.insert(0, _water_profile_dir)

_repo_root = os.path.dirname(_water_profile_dir)
_kernel_dir = os.path.join(_repo_root, "calc_渠系计算算法内核")
if _kernel_dir not in sys.path:
    sys.path.insert(0, _kernel_dir)

from models.data_models import ChannelNode
from models.enums import StructureType, InOutType

from 明渠设计 import (
    get_flow_increase_percent,
    quick_calculate_circular,
    quick_calculate_rectangular,
    quick_calculate_trapezoidal,
    quick_calculate_u_section,
    search_minimum_u_section_radius,
)
from 矩形暗涵设计 import (
    calculate_rectangular_outputs,
    quick_calculate_rectangular_culvert,
    solve_water_depth_rectangular,
)


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
    upstream_velocity_source: str = "missing"   # 上游流速来源: same_section_donor / cross_section_donor / missing
    downstream_velocity_source: str = "missing"  # 下游流速来源: same_section_donor / cross_section_donor / missing
    upstream_velocity_provenance: Dict[str, Any] = field(default_factory=dict)    # 上游 donor 命中来源详情
    downstream_velocity_provenance: Dict[str, Any] = field(default_factory=dict)  # 下游 donor 命中来源详情
    
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


@dataclass
class _VelocityDonorCandidate:
    node: ChannelNode
    index: int
    level: str
    scan_direction: str


class SiphonDataExtractor:
    """
    倒虹吸数据提取器
    
    从渠道节点列表中识别和提取倒虹吸分组。
    """

    VELOCITY_SOURCE_SAME_SECTION = "same_section_donor"
    VELOCITY_SOURCE_CROSS_SECTION = "cross_section_donor"
    VELOCITY_SOURCE_MISSING = "missing"
    DONOR_LEVEL_SAME_SECTION = "same_section"
    DONOR_LEVEL_CROSS_SECTION = "cross_section"
    DONOR_SCAN_UPSTREAM = "upstream"
    DONOR_SCAN_DOWNSTREAM = "downstream"
    OPEN_CHANNEL_V_MIN = 0.5
    OPEN_CHANNEL_V_MAX = 3.0
    DONOR_FAMILY_OPEN_CHANNEL = "open_channel"
    DONOR_FAMILY_CULVERT = "culvert"
    
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
        为倒虹吸两侧提取 donor 流速与断面参数。

        donor 搜索顺序统一为：
        1. 同流量段上游
        2. 同流量段下游
        3. 跨流量段上游
        4. 跨流量段下游

        同流量段 donor 直接复用现成 velocity / velocity_increased；
        跨流量段 donor 使用倒虹吸所在流量段 Q / Q加大 重算，必要时允许重设计。
        """
        group.upstream_velocity_source = SiphonDataExtractor.VELOCITY_SOURCE_MISSING
        group.downstream_velocity_source = SiphonDataExtractor.VELOCITY_SOURCE_MISSING
        group.upstream_velocity_provenance = {}
        group.downstream_velocity_provenance = {}

        candidates = list(SiphonDataExtractor._iter_velocity_donor_candidates(group, nodes))

        upstream_resolution = SiphonDataExtractor._resolve_velocity_donor(group, candidates)
        SiphonDataExtractor._apply_velocity_resolution(group, upstream_resolution, side="upstream")

        downstream_resolution = SiphonDataExtractor._resolve_velocity_donor(group, candidates)
        SiphonDataExtractor._apply_velocity_resolution(group, downstream_resolution, side="downstream")

    @staticmethod
    def _iter_velocity_donor_candidates(
        group: SiphonGroup,
        nodes: List[ChannelNode]
    ) -> Iterator[_VelocityDonorCandidate]:
        target_section = SiphonDataExtractor._get_group_flow_section(group, nodes)
        if not target_section:
            return

        inlet_index = group.inlet_row_index if group.inlet_row_index >= 0 else min(group.row_indices or [-1])
        outlet_index = group.outlet_row_index if group.outlet_row_index >= 0 else max(group.row_indices or [-1])
        if inlet_index < 0 or outlet_index < 0:
            return

        yield from SiphonDataExtractor._iter_same_section_candidates(
            nodes=nodes,
            target_flow_section=target_section,
            start_index=inlet_index - 1,
            step=-1,
            scan_direction=SiphonDataExtractor.DONOR_SCAN_UPSTREAM,
        )
        yield from SiphonDataExtractor._iter_same_section_candidates(
            nodes=nodes,
            target_flow_section=target_section,
            start_index=outlet_index + 1,
            step=1,
            scan_direction=SiphonDataExtractor.DONOR_SCAN_DOWNSTREAM,
        )
        yield from SiphonDataExtractor._iter_cross_section_candidates(
            nodes=nodes,
            target_flow_section=target_section,
            start_index=inlet_index - 1,
            step=-1,
            scan_direction=SiphonDataExtractor.DONOR_SCAN_UPSTREAM,
        )
        yield from SiphonDataExtractor._iter_cross_section_candidates(
            nodes=nodes,
            target_flow_section=target_section,
            start_index=outlet_index + 1,
            step=1,
            scan_direction=SiphonDataExtractor.DONOR_SCAN_DOWNSTREAM,
        )

    @staticmethod
    def _iter_same_section_candidates(
        nodes: List[ChannelNode],
        target_flow_section: str,
        start_index: int,
        step: int,
        scan_direction: str,
    ) -> Iterator[_VelocityDonorCandidate]:
        target_section = SiphonDataExtractor._normalize_flow_section(target_flow_section)
        idx = start_index
        while 0 <= idx < len(nodes):
            node = nodes[idx]
            node_section = SiphonDataExtractor._normalize_flow_section(getattr(node, "flow_section", ""))
            if node_section != target_section:
                break
            if SiphonDataExtractor._is_velocity_donor_candidate_node(node):
                yield _VelocityDonorCandidate(
                    node=node,
                    index=idx,
                    level=SiphonDataExtractor.DONOR_LEVEL_SAME_SECTION,
                    scan_direction=scan_direction,
                )
            idx += step

    @staticmethod
    def _iter_cross_section_candidates(
        nodes: List[ChannelNode],
        target_flow_section: str,
        start_index: int,
        step: int,
        scan_direction: str,
    ) -> Iterator[_VelocityDonorCandidate]:
        target_section = SiphonDataExtractor._normalize_flow_section(target_flow_section)
        idx = start_index
        while 0 <= idx < len(nodes):
            node = nodes[idx]
            node_section = SiphonDataExtractor._normalize_flow_section(getattr(node, "flow_section", ""))
            if node_section == target_section:
                idx += step
                continue
            if SiphonDataExtractor._is_velocity_donor_candidate_node(node):
                yield _VelocityDonorCandidate(
                    node=node,
                    index=idx,
                    level=SiphonDataExtractor.DONOR_LEVEL_CROSS_SECTION,
                    scan_direction=scan_direction,
                )
            idx += step

    @staticmethod
    def _is_velocity_donor_candidate_node(node: ChannelNode) -> bool:
        if getattr(node, 'is_transition', False):
            return False
        if SiphonDataExtractor._is_inverted_siphon(node):
            return False
        if getattr(node, 'is_auto_inserted_channel', False):
            return False
        if SiphonDataExtractor._is_gate_node(node):
            return False
        return SiphonDataExtractor._is_velocity_donor_section_node(node)

    @staticmethod
    def _resolve_velocity_donor(
        group: SiphonGroup,
        candidates: List[_VelocityDonorCandidate]
    ) -> Dict[str, Any]:
        for candidate in candidates:
            if candidate.level == SiphonDataExtractor.DONOR_LEVEL_SAME_SECTION:
                return {
                    "source": SiphonDataExtractor.VELOCITY_SOURCE_SAME_SECTION,
                    "node": candidate.node,
                    "provenance": SiphonDataExtractor._build_velocity_provenance(
                        candidate,
                        applied_node=candidate.node,
                        redesigned=False,
                    ),
                }

            computed_node, redesigned, redesign_mode = SiphonDataExtractor._build_cross_section_donor_node(group, candidate)
            if computed_node is None:
                continue
            return {
                "source": SiphonDataExtractor.VELOCITY_SOURCE_CROSS_SECTION,
                "node": computed_node,
                "provenance": SiphonDataExtractor._build_velocity_provenance(
                    candidate,
                    applied_node=computed_node,
                    redesigned=redesigned,
                    redesign_mode=redesign_mode,
                ),
            }

        return {
            "source": SiphonDataExtractor.VELOCITY_SOURCE_MISSING,
            "node": None,
            "provenance": {
                "level": "missing",
                "scan_direction": "",
                "donor_name": "",
                "donor_flow_section": "",
                "redesigned": False,
                "redesign_mode": "",
                "structure_type": "",
                "section_family": "",
                "dimensions": {},
            },
        }

    @staticmethod
    def _build_velocity_provenance(
        candidate: _VelocityDonorCandidate,
        applied_node: ChannelNode,
        redesigned: bool,
        redesign_mode: str = "",
    ) -> Dict[str, Any]:
        return {
            "level": candidate.level,
            "scan_direction": candidate.scan_direction,
            "donor_name": getattr(candidate.node, "name", ""),
            "donor_flow_section": SiphonDataExtractor._normalize_flow_section(
                getattr(candidate.node, "flow_section", "")
            ),
            "donor_index": candidate.index,
            "redesigned": redesigned,
            "redesign_mode": redesign_mode,
            "structure_type": SiphonDataExtractor._get_structure_type_str(applied_node),
            "section_family": SiphonDataExtractor._get_velocity_donor_family(applied_node),
            "dimensions": SiphonDataExtractor._extract_section_dimensions(applied_node),
        }

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
    def _get_group_flow_section(group: SiphonGroup, nodes: List[ChannelNode]) -> str:
        if group.inlet_row_index >= 0:
            section = SiphonDataExtractor._get_flow_section(nodes, group.inlet_row_index)
            if section:
                return section
        if group.outlet_row_index >= 0:
            section = SiphonDataExtractor._get_flow_section(nodes, group.outlet_row_index)
            if section:
                return section
        for row_index in group.row_indices:
            section = SiphonDataExtractor._get_flow_section(nodes, row_index)
            if section:
                return section
        return ""

    @staticmethod
    def _get_structure_type_str(node: ChannelNode) -> str:
        st = getattr(node, "structure_type", None)
        if st is None:
            return ""
        return st.value if hasattr(st, "value") else str(st)

    @staticmethod
    def _extract_section_dimensions(node: ChannelNode) -> Dict[str, float]:
        sp = getattr(node, "section_params", None) or {}
        dims: Dict[str, float] = {}
        for key in ("B", "m", "D", "R_circle", "theta_deg", "chamfer_angle", "slope_inv", "H_total"):
            val = sp.get(key)
            if isinstance(val, (int, float)) and (val > 0 or key == "m"):
                dims[key] = float(val)
        water_depth = getattr(node, "water_depth", 0.0)
        if water_depth and water_depth > 0:
            dims["h"] = float(water_depth)
        structure_height = getattr(node, "structure_height", 0.0)
        if structure_height and structure_height > 0 and "H_total" not in dims:
            dims["H_total"] = float(structure_height)
        return dims

    @staticmethod
    def _build_cross_section_donor_node(
        group: SiphonGroup,
        candidate: _VelocityDonorCandidate
    ) -> tuple[Optional[ChannelNode], bool, str]:
        donor_node = candidate.node
        calc_result = SiphonDataExtractor._calculate_cross_section_channel(
            group=group,
            donor_node=donor_node,
            redesign=False,
        )
        if calc_result is not None:
            return calc_result["node"], False, calc_result.get("redesign_mode", "")

        calc_result = SiphonDataExtractor._calculate_cross_section_channel(
            group=group,
            donor_node=donor_node,
            redesign=True,
        )
        if calc_result is not None:
            return calc_result["node"], True, calc_result.get("redesign_mode", "")

        return None, False, ""

    @staticmethod
    def _calculate_cross_section_channel(
        group: SiphonGroup,
        donor_node: ChannelNode,
        redesign: bool,
    ) -> Optional[Dict[str, Any]]:
        structure_type = SiphonDataExtractor._get_structure_type_str(donor_node)
        target_flow = getattr(group, "design_flow", 0.0) or 0.0
        if target_flow <= 0:
            return None

        n_value = getattr(donor_node, "roughness", 0.0) or group.roughness or 0.014
        slope_inv = SiphonDataExtractor._get_donor_slope_inv(donor_node)
        if n_value <= 0 or slope_inv <= 0:
            return None

        increase_percent = get_flow_increase_percent(target_flow)
        sp = donor_node.section_params or {}
        v_min = SiphonDataExtractor.OPEN_CHANNEL_V_MIN
        v_max = SiphonDataExtractor.OPEN_CHANNEL_V_MAX

        if structure_type == "明渠-梯形":
            result = quick_calculate_trapezoidal(
                Q=target_flow,
                m=sp.get("m", 0.0),
                n=n_value,
                slope_inv=slope_inv,
                v_min=v_min,
                v_max=v_max,
                manual_b=None if redesign else sp.get("B"),
                manual_increase_percent=increase_percent,
            )
            if not result.get("success"):
                return None
            return {
                "node": SiphonDataExtractor._build_virtual_open_channel_node(
                    donor_node=donor_node,
                    velocity=result.get("V_design", 0.0),
                    velocity_increased=result.get("V_increased", 0.0),
                    water_depth=result.get("h_design", 0.0),
                    section_params={
                        "B": result.get("b_design", 0.0),
                        "m": sp.get("m", 0.0),
                        "slope_inv": slope_inv,
                    },
                )
            }

        if structure_type in {"明渠-矩形", "矩形"}:
            result = quick_calculate_rectangular(
                Q=target_flow,
                n=n_value,
                slope_inv=slope_inv,
                v_min=v_min,
                v_max=v_max,
                manual_b=None if redesign else sp.get("B"),
                manual_increase_percent=increase_percent,
            )
            if not result.get("success"):
                return None
            return {
                "node": SiphonDataExtractor._build_virtual_open_channel_node(
                    donor_node=donor_node,
                    velocity=result.get("V_design", 0.0),
                    velocity_increased=result.get("V_increased", 0.0),
                    water_depth=result.get("h_design", 0.0),
                    section_params={
                        "B": result.get("b_design", 0.0),
                        "m": 0.0,
                        "slope_inv": slope_inv,
                    },
                )
            }

        if structure_type == "明渠-圆形":
            result = quick_calculate_circular(
                Q=target_flow,
                n=n_value,
                slope_inv=slope_inv,
                v_min=v_min,
                v_max=v_max,
                increase_percent=increase_percent,
                manual_D=None if redesign else sp.get("D"),
            )
            if not result.get("success"):
                return None
            return {
                "node": SiphonDataExtractor._build_virtual_open_channel_node(
                    donor_node=donor_node,
                    velocity=result.get("V_d", 0.0),
                    velocity_increased=result.get("V_i", 0.0),
                    water_depth=result.get("y_d", 0.0),
                    section_params={
                        "D": result.get("D_design", 0.0),
                        "slope_inv": slope_inv,
                    },
                )
            }

        if structure_type == "明渠-U形":
            alpha_deg = sp.get("chamfer_angle", 0.0)
            theta_deg = sp.get("theta_deg", 0.0)
            if redesign:
                result = search_minimum_u_section_radius(
                    Q=target_flow,
                    alpha_deg=alpha_deg,
                    theta_deg=theta_deg,
                    n=n_value,
                    slope_inv=slope_inv,
                    v_min=v_min,
                    v_max=v_max,
                    manual_increase_percent=increase_percent,
                    start_R=sp.get("R_circle", 0.1),
                )
            else:
                result = quick_calculate_u_section(
                    Q=target_flow,
                    R=sp.get("R_circle", 0.0),
                    alpha_deg=alpha_deg,
                    theta_deg=theta_deg,
                    n=n_value,
                    slope_inv=slope_inv,
                    v_min=v_min,
                    v_max=v_max,
                    manual_increase_percent=increase_percent,
                )
            if not result.get("success"):
                return None
            return {
                "node": SiphonDataExtractor._build_virtual_open_channel_node(
                    donor_node=donor_node,
                    velocity=result.get("V_design", 0.0),
                    velocity_increased=result.get("V_increased", 0.0),
                    water_depth=result.get("h_design", 0.0),
                    section_params={
                        "R_circle": result.get("R", 0.0),
                        "theta_deg": theta_deg,
                        "chamfer_angle": alpha_deg,
                        "slope_inv": slope_inv,
                    },
                )
            }

        return None

    @staticmethod
    def _get_donor_slope_inv(node: ChannelNode) -> float:
        sp = getattr(node, "section_params", None) or {}
        slope_inv = sp.get("slope_inv", 0.0) or 0.0
        if slope_inv > 0:
            return float(slope_inv)

        slope_i = getattr(node, "slope_i", 0.0) or 0.0
        if slope_i > 0:
            return 1.0 / slope_i

        return 0.0

    @staticmethod
    def _build_virtual_open_channel_node(
        donor_node: ChannelNode,
        velocity: float,
        velocity_increased: float,
        water_depth: float,
        section_params: Dict[str, float],
    ) -> ChannelNode:
        return ChannelNode(
            name=getattr(donor_node, "name", ""),
            structure_type=getattr(donor_node, "structure_type", None),
            in_out=InOutType.NORMAL,
            flow_section=getattr(donor_node, "flow_section", ""),
            flow=getattr(donor_node, "flow", 0.0),
            roughness=getattr(donor_node, "roughness", 0.014),
            section_params=section_params,
            water_depth=water_depth or 0.0,
            velocity=velocity or 0.0,
            velocity_increased=velocity_increased or 0.0,
            slope_i=getattr(donor_node, "slope_i", 0.0),
        )

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
    def _apply_velocity_resolution(group: SiphonGroup, resolution: Dict[str, Any], side: str):
        source = resolution.get("source", SiphonDataExtractor.VELOCITY_SOURCE_MISSING)
        provenance = resolution.get("provenance", {}) or {}
        donor_node = resolution.get("node")

        if side == "upstream":
            group.upstream_velocity_source = source
            group.upstream_velocity_provenance = provenance
            if donor_node is not None:
                SiphonDataExtractor._apply_upstream_node_data(group, donor_node)
            return

        group.downstream_velocity_source = source
        group.downstream_velocity_provenance = provenance
        if donor_node is not None:
            SiphonDataExtractor._apply_downstream_node_data(group, donor_node)

    @staticmethod
    def _apply_upstream_node_data(group: SiphonGroup, upstream_node: ChannelNode):
        SiphonDataExtractor._apply_group_side_node_data(group, upstream_node, side="upstream")

    @staticmethod
    def _apply_downstream_node_data(group: SiphonGroup, downstream_node: ChannelNode):
        SiphonDataExtractor._apply_group_side_node_data(group, downstream_node, side="downstream")

    @staticmethod
    def _apply_group_side_node_data(group: SiphonGroup, donor_node: ChannelNode, side: str):
        velocity_attr = f"{side}_velocity"
        velocity_inc_attr = f"{side}_velocity_increased"
        struct_attr = f"{side}_structure_type"
        section_b_attr = f"{side}_section_B"
        section_h_attr = f"{side}_section_h"
        section_m_attr = f"{side}_section_m"
        section_d_attr = f"{side}_section_D"
        section_r_attr = f"{side}_section_R"

        velocity = getattr(donor_node, "velocity", 0.0)
        if velocity and velocity > 0:
            setattr(group, velocity_attr, velocity)

        velocity_increased = getattr(donor_node, "velocity_increased", 0.0)
        if velocity_increased and velocity_increased > 0:
            setattr(group, velocity_inc_attr, velocity_increased)

        structure_type = SiphonDataExtractor._get_structure_type_str(donor_node)
        if structure_type:
            setattr(group, struct_attr, structure_type)

        sp = donor_node.section_params or {}
        B = sp.get("B", 0.0)
        h = getattr(donor_node, "water_depth", 0.0)
        m = sp.get("m", 0.0)
        D = sp.get("D", 0.0)
        R_circle = sp.get("R_circle", 0.0)

        if B > 0 and h > 0:
            setattr(group, section_b_attr, B)
            setattr(group, section_h_attr, h)
            setattr(group, section_m_attr, m)
        elif D > 0 and h > 0:
            setattr(group, section_b_attr, D)
            setattr(group, section_h_attr, h)
            setattr(group, section_m_attr, 0.0)
        elif R_circle > 0 and h > 0:
            setattr(group, section_b_attr, 2 * R_circle)
            setattr(group, section_h_attr, h)
            setattr(group, section_m_attr, 0.0)

        if D > 0:
            setattr(group, section_d_attr, D)
        if R_circle > 0:
            setattr(group, section_r_attr, R_circle)
        if h > 0 and getattr(group, section_h_attr) is None:
            setattr(group, section_h_attr, h)

    @staticmethod
    def _calculate_cross_section_channel(
        group: SiphonGroup,
        donor_node: ChannelNode,
        redesign: bool,
    ) -> Optional[Dict[str, Any]]:
        structure_type = SiphonDataExtractor._get_structure_type_str(donor_node)
        target_flow = getattr(group, "design_flow", 0.0) or 0.0
        if target_flow <= 0:
            return None

        n_value = getattr(donor_node, "roughness", 0.0) or group.roughness or 0.014
        slope_inv = SiphonDataExtractor._get_donor_slope_inv(donor_node)
        if n_value <= 0 or slope_inv <= 0:
            return None

        increase_percent = get_flow_increase_percent(target_flow)
        sp = donor_node.section_params or {}
        v_min = SiphonDataExtractor.OPEN_CHANNEL_V_MIN
        v_max = SiphonDataExtractor.OPEN_CHANNEL_V_MAX

        if structure_type == "明渠-梯形":
            result = quick_calculate_trapezoidal(
                Q=target_flow,
                m=sp.get("m", 0.0),
                n=n_value,
                slope_inv=slope_inv,
                v_min=v_min,
                v_max=v_max,
                manual_b=None if redesign else sp.get("B"),
                manual_increase_percent=increase_percent,
            )
            if not result.get("success"):
                return None
            return {
                "node": SiphonDataExtractor._build_virtual_section_node(
                    donor_node=donor_node,
                    velocity=result.get("V_design", 0.0),
                    velocity_increased=result.get("V_increased", 0.0),
                    water_depth=result.get("h_design", 0.0),
                    section_params={
                        "B": result.get("b_design", 0.0),
                        "m": sp.get("m", 0.0),
                        "slope_inv": slope_inv,
                    },
                ),
                "redesign_mode": "auto_redesign" if redesign else "",
            }

        if structure_type in {"明渠-矩形", "矩形"}:
            result = quick_calculate_rectangular(
                Q=target_flow,
                n=n_value,
                slope_inv=slope_inv,
                v_min=v_min,
                v_max=v_max,
                manual_b=None if redesign else sp.get("B"),
                manual_increase_percent=increase_percent,
            )
            if not result.get("success"):
                return None
            return {
                "node": SiphonDataExtractor._build_virtual_section_node(
                    donor_node=donor_node,
                    velocity=result.get("V_design", 0.0),
                    velocity_increased=result.get("V_increased", 0.0),
                    water_depth=result.get("h_design", 0.0),
                    section_params={
                        "B": result.get("b_design", 0.0),
                        "m": 0.0,
                        "slope_inv": slope_inv,
                    },
                ),
                "redesign_mode": "auto_redesign" if redesign else "",
            }

        if structure_type == "明渠-圆形":
            result = quick_calculate_circular(
                Q=target_flow,
                n=n_value,
                slope_inv=slope_inv,
                v_min=v_min,
                v_max=v_max,
                increase_percent=increase_percent,
                manual_D=None if redesign else sp.get("D"),
            )
            if not result.get("success"):
                return None
            return {
                "node": SiphonDataExtractor._build_virtual_section_node(
                    donor_node=donor_node,
                    velocity=result.get("V_d", 0.0),
                    velocity_increased=result.get("V_i", 0.0),
                    water_depth=result.get("y_d", 0.0),
                    section_params={
                        "D": result.get("D_design", 0.0),
                        "slope_inv": slope_inv,
                    },
                ),
                "redesign_mode": "auto_redesign" if redesign else "",
            }

        if structure_type == "明渠-U形":
            alpha_deg = sp.get("chamfer_angle", 0.0)
            theta_deg = sp.get("theta_deg", 0.0)
            if redesign:
                result = search_minimum_u_section_radius(
                    Q=target_flow,
                    alpha_deg=alpha_deg,
                    theta_deg=theta_deg,
                    n=n_value,
                    slope_inv=slope_inv,
                    v_min=v_min,
                    v_max=v_max,
                    manual_increase_percent=increase_percent,
                    start_R=sp.get("R_circle", 0.1),
                )
            else:
                result = quick_calculate_u_section(
                    Q=target_flow,
                    R=sp.get("R_circle", 0.0),
                    alpha_deg=alpha_deg,
                    theta_deg=theta_deg,
                    n=n_value,
                    slope_inv=slope_inv,
                    v_min=v_min,
                    v_max=v_max,
                    manual_increase_percent=increase_percent,
                )
            if not result.get("success"):
                return None
            return {
                "node": SiphonDataExtractor._build_virtual_section_node(
                    donor_node=donor_node,
                    velocity=result.get("V_design", 0.0),
                    velocity_increased=result.get("V_increased", 0.0),
                    water_depth=result.get("h_design", 0.0),
                    section_params={
                        "R_circle": result.get("R", 0.0),
                        "theta_deg": theta_deg,
                        "chamfer_angle": alpha_deg,
                        "slope_inv": slope_inv,
                    },
                ),
                "redesign_mode": "auto_redesign" if redesign else "",
            }

        if SiphonDataExtractor._is_rect_culvert_structure_type(structure_type):
            if redesign:
                result = quick_calculate_rectangular_culvert(
                    Q=target_flow,
                    n=n_value,
                    slope_inv=slope_inv,
                    v_min=v_min,
                    v_max=v_max,
                    manual_B=sp.get("B"),
                    manual_increase_percent=increase_percent,
                )
                if not result.get("success"):
                    return None
                return {
                    "node": SiphonDataExtractor._build_virtual_section_node(
                        donor_node=donor_node,
                        velocity=result.get("V_design", 0.0),
                        velocity_increased=result.get("V_increased", 0.0),
                        water_depth=result.get("h_design", 0.0),
                        section_params={
                            "B": result.get("B", 0.0),
                            "H_total": result.get("H", 0.0),
                            "slope_inv": slope_inv,
                        },
                        structure_height=result.get("H", 0.0),
                    ),
                    "redesign_mode": "keep_bottom_width_raise_height",
                }

            fixed_node = SiphonDataExtractor._try_rectangular_culvert_with_fixed_box(
                donor_node=donor_node,
                target_flow=target_flow,
                n_value=n_value,
                slope_inv=slope_inv,
                increase_percent=increase_percent,
                v_min=v_min,
                v_max=v_max,
            )
            if fixed_node is None:
                return None
            return {
                "node": fixed_node,
                "redesign_mode": "",
            }

        return None

    @staticmethod
    def _try_rectangular_culvert_with_fixed_box(
        donor_node: ChannelNode,
        target_flow: float,
        n_value: float,
        slope_inv: float,
        increase_percent: float,
        v_min: float,
        v_max: float,
    ) -> Optional[ChannelNode]:
        sp = donor_node.section_params or {}
        width = sp.get("B", 0.0) or 0.0
        total_height = sp.get("H_total", 0.0) or getattr(donor_node, "structure_height", 0.0) or 0.0
        if width <= 0 or total_height <= 0:
            return None

        slope = 1.0 / slope_inv
        increased_flow = target_flow * (1 + increase_percent / 100.0)

        h_design, success_design = solve_water_depth_rectangular(width, total_height, n_value, slope, target_flow)
        if not success_design or h_design >= total_height:
            return None
        outputs_design = calculate_rectangular_outputs(width, total_height, h_design, n_value, slope)
        velocity_design = outputs_design.get("V", 0.0)
        if velocity_design < v_min or velocity_design > v_max:
            return None

        h_increased, success_increased = solve_water_depth_rectangular(
            width,
            total_height,
            n_value,
            slope,
            increased_flow,
        )
        if not success_increased or h_increased >= total_height:
            return None
        outputs_increased = calculate_rectangular_outputs(width, total_height, h_increased, n_value, slope)
        velocity_increased = outputs_increased.get("V", 0.0)
        if velocity_increased < v_min or velocity_increased > v_max:
            return None

        return SiphonDataExtractor._build_virtual_section_node(
            donor_node=donor_node,
            velocity=velocity_design,
            velocity_increased=velocity_increased,
            water_depth=h_design,
            section_params={
                "B": width,
                "H_total": total_height,
                "slope_inv": slope_inv,
            },
            structure_height=total_height,
        )

    @staticmethod
    def _build_virtual_section_node(
        donor_node: ChannelNode,
        velocity: float,
        velocity_increased: float,
        water_depth: float,
        section_params: Dict[str, float],
        structure_height: float = 0.0,
    ) -> ChannelNode:
        return ChannelNode(
            name=getattr(donor_node, "name", ""),
            structure_type=getattr(donor_node, "structure_type", None),
            in_out=InOutType.NORMAL,
            flow_section=getattr(donor_node, "flow_section", ""),
            flow=getattr(donor_node, "flow", 0.0),
            roughness=getattr(donor_node, "roughness", 0.014),
            section_params=section_params,
            water_depth=water_depth or 0.0,
            velocity=velocity or 0.0,
            velocity_increased=velocity_increased or 0.0,
            slope_i=getattr(donor_node, "slope_i", 0.0),
            structure_height=structure_height or getattr(donor_node, "structure_height", 0.0),
        )

    @staticmethod
    def _is_velocity_donor_section_node(node: ChannelNode) -> bool:
        structure_type = SiphonDataExtractor._get_structure_type_str(node)
        return (
            SiphonDataExtractor._is_open_channel_structure_type(structure_type)
            or SiphonDataExtractor._is_rect_culvert_structure_type(structure_type)
        )

    @staticmethod
    def _is_open_channel_structure_type(structure_type: str) -> bool:
        normalized = SiphonDataExtractor._normalize_structure_type(structure_type)
        return normalized in {"明渠-梯形", "明渠-矩形", "明渠-圆形", "明渠-U形", "矩形"}

    @staticmethod
    def _is_rect_culvert_structure_type(structure_type: str) -> bool:
        normalized = SiphonDataExtractor._normalize_structure_type(structure_type)
        return normalized == "矩形暗涵"

    @staticmethod
    def _normalize_structure_type(structure_type: str) -> str:
        text = str(structure_type or "").strip()
        if text in {"暗渠", "矩形暗渠", "矩形暗涵"}:
            return "矩形暗涵"
        return text

    @staticmethod
    def _get_velocity_donor_family(node: ChannelNode) -> str:
        structure_type = SiphonDataExtractor._get_structure_type_str(node)
        if SiphonDataExtractor._is_rect_culvert_structure_type(structure_type):
            return SiphonDataExtractor.DONOR_FAMILY_CULVERT
        if SiphonDataExtractor._is_open_channel_structure_type(structure_type):
            return SiphonDataExtractor.DONOR_FAMILY_OPEN_CHANNEL
        return ""
    
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
                        "description": f"{prev_node.get_ip_str()}→{node.get_ip_str()}",
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
                        "description": f"{node.get_ip_str()}处水平转弯",
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
