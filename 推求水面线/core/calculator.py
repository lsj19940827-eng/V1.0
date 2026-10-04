# -*- coding: utf-8 -*-
"""
主计算引擎

整合几何计算和水力计算，提供完整的水面线推求功能。
"""

from typing import Any, Dict, List, Optional, Tuple
import copy
import math
import sys
import os
import json

# 添加父目录到路径以支持相对导入
_water_profile_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _water_profile_dir not in sys.path:
    sys.path.insert(0, _water_profile_dir)

_repo_root = os.path.dirname(_water_profile_dir)
_kernel_dir = os.path.join(_repo_root, "calc_渠系计算算法内核")
if _kernel_dir not in sys.path:
    sys.path.insert(0, _kernel_dir)

if __package__ and __package__.startswith("推求水面线."):
    from ..models.data_models import ChannelNode, OpenChannelParams, ProjectSettings
    from ..models.enums import StructureType, InOutType
    from ..config.constants import (
        DEFAULT_GATE_HEAD_LOSS,
        GRAVITY,
        TRANSITION_LENGTH_COEFFICIENTS,
        VELOCITY_PRECISION,
        XXPIPE_CHANNEL_LEVEL_OPTIONS,
        ZERO_TOLERANCE,
    )
    from .geometry_calc import GeometryCalculator
    from .hydraulic_calc import HydraulicCalculator
    from .spillway_steep_chute_adapter import (
        SPILLWAY_STEEP_CHUTE_PARAM_KEY,
        SPILLWAY_STEEP_CHUTE_TEXT,
        get_spillway_steep_chute_total_loss,
        is_spillway_steep_chute_value,
        prepare_spillway_steep_chute_groups,
    )
else:
    from models.data_models import ChannelNode, OpenChannelParams, ProjectSettings
    from models.enums import StructureType, InOutType
    from config.constants import (
        DEFAULT_GATE_HEAD_LOSS,
        GRAVITY,
        TRANSITION_LENGTH_COEFFICIENTS,
        VELOCITY_PRECISION,
        XXPIPE_CHANNEL_LEVEL_OPTIONS,
        ZERO_TOLERANCE,
    )
    from core.geometry_calc import GeometryCalculator
    from core.hydraulic_calc import HydraulicCalculator
    from core.spillway_steep_chute_adapter import (
        SPILLWAY_STEEP_CHUTE_PARAM_KEY,
        SPILLWAY_STEEP_CHUTE_TEXT,
        get_spillway_steep_chute_total_loss,
        is_spillway_steep_chute_value,
        prepare_spillway_steep_chute_groups,
    )
from utils.pressure_pipe_tunnel import iter_internal_tunnel_boundaries
from 矩形暗涵设计 import calculate_rectangular_outputs
from .connection_channel import (
    flow_section_key, max_flow_for_section, positive,
    recalculate_open_channel, reference_to_params, params_to_reference,
)
from .length_statistics import build_length_records, summarize_length_records, validate_length_records

FILL_CHANNEL_TEXT = "充水渠"


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

    @staticmethod
    def _build_pressure_pipe_row_identity(node: ChannelNode, row_index: int) -> str:
        flow_section = str(getattr(node, "flow_section", "") or "").strip()
        row_part = f"row{int(row_index) + 1}"
        if flow_section:
            return f"flow{flow_section}-{row_part}"
        return row_part

    def _ensure_pressure_pipe_row_identity(self, node: ChannelNode, row_index: int) -> str:
        identity = str(getattr(node, "pressure_pipe_row_identity", "") or "").strip()
        if not identity:
            identity = self._build_pressure_pipe_row_identity(node, row_index)
            setattr(node, "pressure_pipe_row_identity", identity)
        return identity

    def _is_unnamed_pressure_pipe_node(self, node: ChannelNode) -> bool:
        if not self.is_pressure_pipe(node):
            return False
        return not str(getattr(node, "name", "") or "").strip()

    def _should_skip_pressure_pipe_like_gap(
        self,
        node1: ChannelNode,
        node2: ChannelNode,
        all_nodes=None,
    ) -> bool:
        """
        判断两个相邻节点是否属于同类承压结构，因此应直接跳过插段。

        当前统一口径：
        - 有压管道 ↔ 有压管道
        - 有压管道 ↔ 定向钻
        - 有压管道 ↔ 顶管
        - 定向钻 ↔ 顶管
        - 定向钻 ↔ 定向钻
        - 顶管 ↔ 顶管

        以上场景都不插渐变段，也不插中间连接段。
        """
        if not node1 or not node2:
            return False
        if self.is_pressure_pipe(node1) and self.is_pressure_pipe(node2):
            return True
        for inlet, outlet, before, after in iter_internal_tunnel_boundaries(all_nodes):
            if (node1 is all_nodes[before] and node2 is all_nodes[inlet] and not str(node1.name or "").strip()) or (
                node1 is all_nodes[outlet] and node2 is all_nodes[after] and not str(node2.name or "").strip()
            ):
                return True
        return False

    def _matches_gap_outlet_role(self, node: ChannelNode) -> bool:
        """判断节点在插渐变段阶段是否可临时视为出口边界。"""
        io_value = node.in_out.value if getattr(node, "in_out", None) else ""
        if io_value == "出":
            return True
        # 空名称有压管道不参与全表配对，但在相邻建筑物补渐变段时，
        # 仍需要按当前位置临时识别为边界。
        return self._is_unnamed_pressure_pipe_node(node)

    def _matches_gap_inlet_role(self, node: ChannelNode) -> bool:
        """判断节点在插渐变段阶段是否可临时视为进口边界。"""
        io_value = node.in_out.value if getattr(node, "in_out", None) else ""
        if io_value == "进":
            return True
        return self._is_unnamed_pressure_pipe_node(node)

    @staticmethod
    def _should_skip_display_ip_number(node: ChannelNode) -> bool:
        """判断节点是否应隐藏显示用 IP 编号。"""
        if getattr(node, "is_transition", False) or getattr(node, "is_auto_inserted_channel", False):
            return True
        struct_str = node.get_structure_type_str() if hasattr(node, "get_structure_type_str") else ""
        if "暗涵" in struct_str:
            return False
        io_value = node.in_out.value if getattr(node, "in_out", None) else ""
        if io_value not in ("进", "出"):
            return False
        return any(
            key in struct_str
            for key in ("隧洞", "倒虹吸", "有压管道", "渡槽", "定向钻", "顶管")
        )

    def _assign_display_ip_numbers(self, nodes: List[ChannelNode]) -> None:
        """按显示规则为节点重建连续 IP 编号。"""
        display_counter = 0
        for node in nodes:
            if self._should_skip_display_ip_number(node):
                node.display_ip_number = None
                continue
            node.display_ip_number = display_counter
            display_counter += 1
    
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
        # 使用 (名称, 类别) 复合键，避免不同类型同名建筑物合并计数
        structure_total: Dict[tuple, int] = {}
        for idx, node in enumerate(nodes):
            if node.structure_type and self._is_special_structure_sv(node.structure_type):
                if self._is_unnamed_pressure_pipe_node(node):
                    node.is_pressure_pipe = True
                    self._ensure_pressure_pipe_row_identity(node, idx)
                    continue
                key = (node.name, self._get_structure_category(node.structure_type))
                structure_total[key] = structure_total.get(key, 0) + 1
        
        # 第二轮遍历：分配IP编号和进出口标识
        structure_count: Dict[tuple, int] = {}  # 当前出现次数
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
                # 标记倒虹吸
                sv = node.structure_type.value if node.structure_type else ""
                if sv == "倒虹吸":
                    node.is_inverted_siphon = True
                # 标记有压管道
                if StructureType.is_pressure_pipe_like_str(sv):
                    node.is_pressure_pipe = True
                if self._is_unnamed_pressure_pipe_node(node):
                    self._ensure_pressure_pipe_row_identity(node, i)
                    node.in_out = InOutType.NORMAL
                else:
                    key = (node.name, self._get_structure_category(node.structure_type))
                    count = structure_count.get(key, 0) + 1
                    structure_count[key] = count
                    total = structure_total.get(key, 2)

                    # 根据当前次数和总次数判断进出口
                    # 第1次=进口，最后1次=出口，中间=普通断面
                    in_out_result = InOutType.from_count(count, total)
                    node.in_out = in_out_result[0]
            else:
                # 普通明渠、分水闸等不标识进出口
                node.in_out = InOutType.NORMAL
            
            # 标记闸类型（分水闸/分水口/泄水闸/节制闸等）并设置默认过闸水头损失
            if node.structure_type and self._is_diversion_gate_sv(node.structure_type):
                node.is_diversion_gate = True
                # 若用户未手动设置过闸损失，则自动设为默认值0.1m
                gate_loss_user_set = bool(
                    (getattr(node, "section_params", {}) or {}).get("gate_head_loss_user_set", False)
                )
                if node.head_loss_gate == 0.0 and not gate_loss_user_set:
                    node.head_loss_gate = DEFAULT_GATE_HEAD_LOSS
            
            # 3. 应用断面参数库中的参数（如果有）
            if node.name in self.section_params_library:
                # 合并参数，不覆盖已有的
                lib_params = self.section_params_library[node.name]
                for key, value in lib_params.items():
                    if key not in node.section_params:
                        node.section_params[key] = value

        # 4. 显示用 IP 编号：特殊建筑进出口不占号，其余真实节点连续编号
        self._assign_display_ip_numbers(nodes)
        
        # 5. 闸节点去重：连续同名同坐标闸节点，仅首行保留 head_loss_gate，后续行清零
        prev_gate = None
        for node in nodes:
            if not getattr(node, 'is_diversion_gate', False):
                prev_gate = None
                continue
            if (prev_gate is not None
                    and node.name == prev_gate.name
                    and abs(node.x - prev_gate.x) < 1e-6
                    and abs(node.y - prev_gate.y) < 1e-6):
                node.head_loss_gate = 0.0
            prev_gate = node
    
    def calculate_geometry(self, nodes: List[ChannelNode]) -> None:
        """
        执行几何计算
        
        Args:
            nodes: 节点列表（原地修改）
        """
        if self._has_auxiliary_geometry_nodes(nodes):
            self._refresh_geometry_preserving_auxiliary_nodes(nodes)
            return

        # 计算方位角、转角、切线长、弧长、距离
        self.geo_calc.calculate_all_geometry(nodes)
        
        # 计算桩号
        self.geo_calc.calculate_stations(nodes, self._resolve_station_start(nodes))

    def _collect_special_turn_preserve_targets(
        self, nodes: List[ChannelNode]
    ) -> Dict[int, Dict[str, Any]]:
        """收集需要在几何重算时暂时放开进出口口径的真实特殊节点。"""
        targets: Dict[int, Dict[str, Any]] = {}
        for node in nodes:
            if not self._is_real_profile_node(node):
                continue
            in_out = getattr(node, "in_out", None)
            if in_out not in (InOutType.INLET, InOutType.OUTLET):
                continue
            try:
                turn_angle = float(getattr(node, "turn_angle", 0.0) or 0.0)
            except (TypeError, ValueError):
                turn_angle = 0.0
            if abs(turn_angle) <= ZERO_TOLERANCE:
                continue
            targets[id(node)] = {
                "turn_angle": turn_angle,
                "in_out": in_out,
            }
        return targets

    def _calculate_geometry_preserving_special_turns(
        self, nodes: List[ChannelNode]
    ) -> Dict[int, Dict[str, Any]]:
        """重算几何前临时放开特殊进出口节点，避免既有非零转角被清零。"""
        targets = self._collect_special_turn_preserve_targets(nodes)
        for node in nodes:
            payload = targets.get(id(node))
            if not payload:
                continue
            node.turn_angle = float(payload["turn_angle"])
            node.in_out = InOutType.NORMAL

        self.calculate_geometry(nodes)

        for node in nodes:
            payload = targets.get(id(node))
            if not payload:
                continue
            node.in_out = payload["in_out"]
        return targets

    @staticmethod
    def _has_auxiliary_geometry_nodes(nodes: List[ChannelNode]) -> bool:
        """判断当前节点序列中是否已包含辅助拓扑行。"""
        return any(
            getattr(node, 'is_transition', False)
            or getattr(node, 'is_auto_inserted_channel', False)
            for node in nodes
        )

    def _refresh_geometry_preserving_auxiliary_nodes(self, nodes: List[ChannelNode]) -> None:
        """
        在已存在渐变段/连接段时安全刷新几何。

        只重算真实节点的转角和曲线要素，再按辅助行现有位置回补内部桩号，
        避免辅助行参与整套几何重算后把下游真实节点桩号整体带偏。
        """
        real_nodes = [node for node in nodes if self._is_real_profile_node(node)]
        if not real_nodes:
            return

        self.geo_calc.calculate_all_geometry(real_nodes)
        start_station = self._resolve_station_start(nodes)
        self.geo_calc.calculate_stations(real_nodes, start_station)

        for node in nodes:
            if not self._is_real_profile_node(node):
                node.turn_angle = 0.0
                node.tangent_length = 0.0
                node.arc_length = 0.0
                node.curve_length = 0.0
                node.check_pre_curve = 0.0
                node.check_post_curve = 0.0
                node.check_total_length = 0.0

        self._compute_auto_channel_distances(nodes)
        self.geo_calc.calculate_stations(nodes, start_station)
    
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
        
        # 3. 桩号计算
        # 原节点的 straight_distance/tangent_length/arc_length 已由 _build_nodes_from_table
        # 从表格正确读回，不可再调用 calculate_geometry（会因 in_out 已为 INLET/OUTLET
        # 而将这些节点的 T/L 重置为0，导致所有下游 station_MC 错误偏移）。
        # 只需为新插入的自动明渠段节点补算 straight_distance，再统一推算桩号即可。
        # 自动明渠/连接段仅在原区间内部落位，不参与真实IP累计，不能改变下游原始节点桩号。
        self._compute_auto_channel_distances(nodes)
        start_station = self._resolve_station_start(nodes)
        self.geo_calc.calculate_stations(nodes, start_station)
        
        return nodes

    def _resolve_station_start(self, nodes: List[ChannelNode]) -> float:
        """
        解析当前重算应使用的起始桩号。

        优先采用项目设置中的起始桩号，避免表3首行旧桩号快照反向覆盖全局设置；
        仅在 settings 未明确提供有效起点时，才回退到节点当前已有桩号。
        """
        settings_start = getattr(self.settings, "start_station", None)
        explicit_from_ui = bool(getattr(self.settings, "_start_station_from_ui", False))

        if isinstance(settings_start, (int, float)) and math.isfinite(settings_start):
            if explicit_from_ui or abs(float(settings_start)) > 1e-9:
                return float(settings_start)

        if nodes:
            first_station = getattr(nodes[0], "station_MC", None)
            if isinstance(first_station, (int, float)) and math.isfinite(first_station):
                return float(first_station)

        if isinstance(settings_start, (int, float)) and math.isfinite(settings_start):
            return float(settings_start)
        return 0.0
    
    def _compute_auto_channel_distances(self, nodes: List[ChannelNode]) -> None:
        """
        仅为新插入的自动明渠段节点（is_auto_inserted_channel=True）计算 straight_distance。

        原始节点的 straight_distance 已从表格读取，无需重算；
        渐变段节点（is_transition=True）的 straight_distance 在 calculate_stations 中
        会被置0并继承前节点桩号，也无需处理。
        """
        for i in range(1, len(nodes)):
            node = nodes[i]
            if not getattr(node, 'is_auto_inserted_channel', False):
                continue
            prev = None
            for j in range(i - 1, -1, -1):
                if (not getattr(nodes[j], 'is_transition', False)
                        and not getattr(nodes[j], 'is_auto_inserted_channel', False)):
                    prev = nodes[j]
                    break
            if prev is not None:
                dx = node.x - prev.x
                dy = node.y - prev.y
                node.straight_distance = math.sqrt(dx * dx + dy * dy)

    @staticmethod
    def _is_real_profile_node(node: ChannelNode) -> bool:
        """判断纵断面真实节点（排除渐变段和自动插入明渠段）。"""
        if getattr(node, 'is_transition', False):
            return False
        if getattr(node, 'is_auto_inserted_channel', False):
            return False
        return True

    @staticmethod
    def _profile_conflict_node_label(node: ChannelNode) -> str:
        """生成冲突报错中的节点标识。"""
        if hasattr(node, "get_ip_str"):
            ip_text = str(node.get_ip_str() or "").strip() or "IP?"
        else:
            ip_no = getattr(node, 'ip_number', None)
            ip_text = f"IP{ip_no}" if ip_no is not None else "IP?"
        name = str(getattr(node, 'name', '') or '').strip()
        if name and name not in ip_text:
            return f"{ip_text}({name})"
        return ip_text

    def _validate_real_node_station_conflicts(self, nodes: List[ChannelNode], tol: float = 1e-6) -> None:
        """校验真实节点同桩号高程非零冲突；冲突时抛异常阻断后续导出。"""
        grouped = {}
        order = []
        for node in nodes:
            if not self._is_real_profile_node(node):
                continue
            try:
                station_val = float(getattr(node, 'station_MC', 0) or 0.0)
            except (TypeError, ValueError):
                station_val = 0.0
            station_key = round(station_val, 9)
            if station_key not in grouped:
                grouped[station_key] = []
                order.append(station_key)
            grouped[station_key].append(node)

        field_labels = (
            ('bottom_elevation', '渠底高程'),
            ('top_elevation', '渠顶高程'),
            ('water_level', '设计水位'),
        )

        for station_key in order:
            group_nodes = grouped[station_key]
            station_val = float(getattr(group_nodes[0], 'station_MC', station_key))
            for attr_name, field_label in field_labels:
                unique_non_zero = []
                for node in group_nodes:
                    try:
                        value = float(getattr(node, attr_name, 0) or 0.0)
                    except (TypeError, ValueError):
                        value = 0.0
                    if abs(value) <= tol:
                        continue
                    if any(abs(value - prev_val) <= tol for prev_val, _ in unique_non_zero):
                        continue
                    unique_non_zero.append((value, node))

                if len(unique_non_zero) <= 1:
                    continue

                detail = "，".join(
                    f"{val:.6f}@{self._profile_conflict_node_label(node)}"
                    for val, node in unique_non_zero
                )
                raise ValueError(
                    f"同桩号高程冲突：桩号 {station_val:.6f} 的{field_label}存在多个非零值（{detail}）。"
                )

    def _hydrate_spillway_steep_chute_flow_context(self, nodes: List[ChannelNode]) -> None:
        """将当前流量段工况传给专项链，避免复算继续使用旧的加大流量。"""
        for node in nodes:
            if not is_spillway_steep_chute_value(getattr(node, "structure_type", None)):
                continue
            params = getattr(node, "section_params", None)
            if not isinstance(params, dict):
                params = {}
                node.section_params = params
            payload = params.get(SPILLWAY_STEEP_CHUTE_PARAM_KEY, {})
            payload = dict(payload) if isinstance(payload, dict) else {}
            use_value = params.get("use_increase", getattr(node, "use_increase", payload.get("use_increase", True)))
            if use_value is None:
                use_value = True
            use_increase = str(use_value).strip().lower() not in {"0", "false", "否", "不", "不考虑", "未勾选", "no", "n", "off"}
            payload["use_increase"] = use_increase
            if not use_increase:
                payload["Q_increased"] = float(node.flow)
            else:
                try:
                    _, current_maximum = self.settings.get_flow_for_segment(int(flow_section_key(node.flow_section)))
                except (AttributeError, TypeError, ValueError):
                    current_maximum = 0.0
                if positive(current_maximum):
                    payload["Q_increased"] = float(current_maximum)
            params[SPILLWAY_STEEP_CHUTE_PARAM_KEY] = payload

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
        has_auxiliary_nodes = self._has_auxiliary_geometry_nodes(nodes)
        
        # 1. 预处理
        self.preprocess_nodes(nodes)
        
        # 2. 识别并插入渐变段行和明渠段（仅在尚未插入时执行）
        if not has_auxiliary_nodes:
            nodes = self.identify_and_insert_transitions(nodes, open_channel_callback)

        # 3. 几何计算
        self._calculate_geometry_preserving_special_turns(nodes)

        # 3b. 泄水渠与陡坡按连续专项链标记，供表3水面线联算调用专项内核
        self._hydrate_spillway_steep_chute_flow_context(nodes)
        prepare_spillway_steep_chute_groups(nodes)
        
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

        # 9. 倒虹吸内部水位按倒进/倒出桩号线性分布（只影响展示和导出水位线）
        self.hyd_calc.apply_siphon_linear_water_level_distribution(nodes)

        # 10. 对整表末尾闸行执行高程回推（仅补缺失项）
        self.hyd_calc.apply_terminal_gate_elevation_backfill(nodes)
        
        # 11. 计算累计总水头损失
        self._calculate_cumulative_head_loss(nodes)

        # 12. 导出前约束：真实节点同桩号高程冲突校验
        self._validate_real_node_station_conflicts(nodes)
        
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

                # --- 情况1：当前节点是闸 → 检查闸→进口方向的缺口 ---
                if self._is_diversion_gate_type(current_node.structure_type):
                    check_result = self._check_gap_gate_to_entry(current_node, next_node, nodes, i)
                    if check_result['need_open_channel']:
                        ref_idx = i + 1
                        upstream_channel = self._find_reference_segment_same_section_v2(nodes, ref_idx, i, i + 1)
                        if upstream_channel is None:
                            upstream_channel = self._find_reference_segment_cross_section_v2(nodes, ref_idx, i, i + 1)
                        gaps.append({
                            'index': i,
                            'upstream_channel': upstream_channel,
                            'available_length': check_result['available_length'],
                            'prev_struct': current_node.structure_type.value if current_node.structure_type else "",
                            'next_struct': next_node.structure_type.value if next_node.structure_type else "",
                            'prev_name': getattr(current_node, 'name', '') or '',
                            'next_name': getattr(next_node, 'name', '') or '',
                            'flow_section': next_node.flow_section,
                            'flow': next_node.flow,
                            'has_upstream': upstream_channel is not None,
                            'reference_segment': upstream_channel,
                            'has_reference': upstream_channel is not None
                        })
                    continue

                # --- 情况2：下一节点是闸 → 只检查出口→闸方向的缺口 ---
                if self._is_diversion_gate_type(next_node.structure_type):
                    check_result = self._check_gap_exit_to_gate(current_node, next_node, nodes, i)
                    if check_result['need_open_channel']:
                        upstream_channel = self._find_reference_segment_same_section_v2(nodes, i, i, i + 1)
                        if upstream_channel is None:
                            upstream_channel = self._find_reference_segment_cross_section_v2(nodes, i, i, i + 1)
                        gaps.append({
                            'index': i,
                            'upstream_channel': upstream_channel,
                            'available_length': check_result['available_length'],
                            'prev_struct': current_node.structure_type.value if current_node.structure_type else "",
                            'next_struct': next_node.structure_type.value if next_node.structure_type else "",
                            'prev_name': getattr(current_node, 'name', '') or '',
                            'next_name': getattr(next_node, 'name', '') or '',
                            'flow_section': current_node.flow_section,
                            'flow': current_node.flow,
                            'has_upstream': upstream_channel is not None,
                            'reference_segment': upstream_channel,
                            'has_reference': upstream_channel is not None
                        })
                    continue

                # --- 情况3：普通 (非闸, 非闸) 对 ---
                check_result = self._should_insert_open_channel(
                    current_node, next_node, nodes
                )
                if check_result['need_open_channel']:
                    upstream_channel = self._find_reference_segment_same_section_v2(nodes, i, i, i + 1)
                    if upstream_channel is None:
                        upstream_channel = self._find_reference_segment_cross_section_v2(nodes, i, i, i + 1)
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
                        'has_upstream': upstream_channel is not None,
                        'reference_segment': upstream_channel,
                        'has_reference': upstream_channel is not None
                    })
        for gap in gaps:
            index = gap['index']
            gap['gap_key'] = self.connection_gap_key(nodes[index], nodes[index + 1])
            gap['max_flow'] = max_flow_for_section(self.settings, gap['flow_section'], gap['flow'])
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
        sv1 = self._get_effective_structure_type_value(node1)
        sv2 = self._get_effective_structure_type_value(node2)
        is_node1_mingqu = self._is_mingqu_type(sv1)
        is_node2_mingqu = self._is_mingqu_type(sv2)
        
        # 非明渠类型必须node1为出口
        io1 = node1.in_out.value if node1.in_out else ""
        io2 = node2.in_out.value if node2.in_out else ""
        if not is_node1_mingqu and io1 != "出":
            return False
        
        # 规则1: 倒虹吸内部行之间不需要渐变段
        # 但倒虹吸出口→其他结构、其他结构→倒虹吸进口需要渐变段（占位，跳过损失计算）
        if sv1 == "倒虹吸" and sv2 == "倒虹吸":
            return False
        if sv1 == "倒虹吸" and io1 != "出":
            return False
        if sv2 == "倒虹吸" and io2 != "进":
            return False
        
        # 规则1b: 分水闸/分水口不触发渐变段（点状结构，无断面变化）
        if self._is_diversion_gate_type(sv1):
            return False
        if self._is_diversion_gate_type(sv2):
            return False

        # 有效的结构类型（隧洞/渡槽/明渠/矩形暗涵/倒虹吸）
        valid_type_values = {
            "隧洞-圆形", "隧洞-圆拱直墙型",
            "隧洞-马蹄形Ⅰ型", "隧洞-马蹄形Ⅱ型",
            "渡槽-U形", "渡槽-矩形",
            "明渠-梯形", "明渠-矩形", "明渠-圆形", "明渠-U形", FILL_CHANNEL_TEXT,
            "暗涵-矩形", "暗涵-圆拱直墙型", "矩形暗涵", "倒虹吸",
            SPILLWAY_STEEP_CHUTE_TEXT,
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
        is_node1_tunnel_aqueduct = self._is_tunnel_or_aqueduct(sv1)
        is_node2_tunnel_aqueduct = self._is_tunnel_or_aqueduct(sv2)
        
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

        # 规则7(新增): 矩形暗涵与明渠之间需要渐变段
        # 特例：矩形明渠↔矩形暗涵且底宽相同时不需要渐变段
        is_node1_culvert = self._is_culvert_type(sv1)
        is_node2_culvert = self._is_culvert_type(sv2)

        # 同属暗涵家族但子类型不同，必须插入渐变段，不能再按“同宽即可跳过”处理。
        if is_node1_culvert and is_node2_culvert and sv1 != sv2:
            return True
        
        if (is_node1_culvert and is_node2_mingqu) or \
           (is_node1_mingqu and is_node2_culvert):
            # 矩形明渠↔矩形暗涵：检查底宽是否相同
            mingqu_node = node1 if is_node1_mingqu else node2
            if self._get_effective_structure_type_value(mingqu_node) == "明渠-矩形":
                if self._has_same_section_size(node1, node2):
                    return False
            return True
        
        # 规则4: 如果前后两个建筑物的特征尺寸相同，则不需要渐变段
        if self._has_same_section_size(node1, node2):
            return False
        
        return True
    
    @staticmethod
    def _normalize_structure_type_value(structure_type) -> str:
        """Normalize legacy aliases used by imports and historical tables."""
        if structure_type is None:
            return ""
        sv = structure_type.value if hasattr(structure_type, 'value') else str(structure_type)
        return {
            "矩形": "明渠-矩形",
            "暗涵": "矩形暗涵",
            "暗渠": "矩形暗涵",
            "矩形暗渠": "矩形暗涵",
            "矩形暗涵": "矩形暗涵",
            "暗涵-矩形": "矩形暗涵",
            "圆拱直墙型暗涵": "暗涵-圆拱直墙型",
            "暗涵圆拱直墙型": "暗涵-圆拱直墙型",
            "充水渠": SPILLWAY_STEEP_CHUTE_TEXT,
            "泄水渠": SPILLWAY_STEEP_CHUTE_TEXT,
            "泄水渠与陡坡": SPILLWAY_STEEP_CHUTE_TEXT,
            "陡坡": SPILLWAY_STEEP_CHUTE_TEXT,
            "泄槽": SPILLWAY_STEEP_CHUTE_TEXT,
            "陡槽": SPILLWAY_STEEP_CHUTE_TEXT,
            "泄水渠及陡坡": SPILLWAY_STEEP_CHUTE_TEXT,
        }.get(sv, sv)

    @classmethod
    def _normalize_culvert_family_type_value(cls, value) -> str:
        """统一暗涵家族子类型名称。"""
        text = cls._normalize_structure_type_value(value)
        if not text:
            return ""
        if "暗涵" not in text and "暗渠" not in text and text != "矩形暗涵":
            return ""
        if "圆拱直墙" in text or "圆弧直墙" in text:
            return cls._ARCH_CULVERT_FAMILY_TEXT
        return cls._RECT_CULVERT_FAMILY_TEXT

    @classmethod
    def _get_effective_structure_type_value(cls, structure_or_node) -> str:
        """读取节点的有效结构类型，暗涵优先使用家族子类型。"""
        node = structure_or_node if hasattr(structure_or_node, "section_params") else None
        if node is not None:
            params = getattr(node, "section_params", {}) or {}
            culvert_family_type = cls._normalize_culvert_family_type_value(
                params.get(cls._CULVERT_FAMILY_TYPE_KEY, "")
            )
            if culvert_family_type:
                return culvert_family_type
            structure_or_node = getattr(node, "structure_type", None)
        return cls._normalize_structure_type_value(structure_or_node)

    def _is_mingqu_type(self, structure_type) -> bool:
        """判断是否为明渠类型（使用 .value 字符串比较）"""
        if structure_type is None:
            return False
        sv = self._normalize_structure_type_value(structure_type)
        return sv in ("明渠-梯形", "明渠-矩形", "明渠-圆形", "明渠-U形", FILL_CHANNEL_TEXT)
    
    def _is_tunnel_or_aqueduct(self, structure_type) -> bool:
        """判断是否为隧洞或渡槽类型（使用 .value 字符串比较）"""
        if structure_type is None:
            return False
        sv = self._normalize_structure_type_value(structure_type)
        return "隧洞" in sv or "渡槽" in sv
    
    def _is_diversion_gate_type(self, structure_type) -> bool:
        """判断是否为闸类结构（分水闸/分水口/节制闸/泄水闸等）（使用 .value 字符串比较）"""
        if structure_type is None:
            return False
        sv = self._normalize_structure_type_value(structure_type)
        return "闸" in sv or "分水" in sv
    
    def _find_next_non_gate_idx(self, nodes: List[ChannelNode], start_idx: int):
        """从 start_idx 向后查找第一个非闸节点的索引，无则返回 None"""
        for j in range(start_idx, len(nodes)):
            if not self._is_diversion_gate_type(nodes[j].structure_type):
                return j
        return None
    
    def _get_structure_category(self, structure_type) -> str:
        """提取建筑物的基础类别（隧洞/渡槽/倒虹吸/暗涵）
        
        用于构建 (名称, 类别) 复合键，避免不同类型同名建筑物合并计数。
        例如隧洞"1#"和渡槽"1#"属于不同类别，应独立计数进出口。
        """
        if structure_type is None:
            return ""
        sv = self._normalize_structure_type_value(structure_type)
        if is_spillway_steep_chute_value(sv):
            return SPILLWAY_STEEP_CHUTE_TEXT
        for kw in ("倒虹吸", "隧洞", "渡槽", "暗涵"):
            if kw in sv:
                return kw
        return sv

    def _is_special_structure_sv(self, structure_type) -> bool:
        """判断是否为特殊建筑物（需要进出口标识）（使用 .value 字符串比较）
        
        与原版 StructureType.get_special_structures 保持一致：
        隧洞、渡槽、倒虹吸、有压管道、矩形暗涵需要进出口标识。
        """
        if structure_type is None:
            return False
        sv = structure_type.value if hasattr(structure_type, 'value') else str(structure_type)
        special_keywords = ("隧洞", "渡槽", "倒虹吸", "暗涵")
        return any(kw in sv for kw in special_keywords) or StructureType.is_pressure_pipe_like_str(sv)
    
    def _is_diversion_gate_sv(self, structure_type) -> bool:
        """判断是否为闸类结构（使用 .value 字符串比较）"""
        return self._is_diversion_gate_type(structure_type)
    
    def _is_culvert_type(self, structure_type) -> bool:
        """判断是否为矩形暗涵（使用 .value 字符串比较）"""
        if structure_type is None:
            return False
        sv = self._normalize_structure_type_value(structure_type)
        return sv == "矩形暗涵" or "暗涵" in sv

    def is_pressurized_flow_structure(self, node: ChannelNode) -> bool:
        """
        判断节点是否为有压流建筑物（倒虹吸或有压管道）

        有压流建筑物的渐变段水头损失已包含在其自身的水力计算中，
        因此需要在渐变段插入时标记 transition_skip_loss=True。

        Args:
            node: 渠道节点

        Returns:
            是否为有压流建筑物
        """
        if not node.structure_type:
            return False
        sv = node.structure_type.value if hasattr(node.structure_type, 'value') else str(node.structure_type)
        return sv == "倒虹吸" or StructureType.is_pressure_pipe_like_str(sv)

    def is_pressure_pipe(self, node: ChannelNode) -> bool:
        """
        判断节点是否为有压管道

        Args:
            node: 渠道节点

        Returns:
            是否为有压管道
        """
        if not node.structure_type:
            return False
        sv = node.structure_type.value if hasattr(node.structure_type, 'value') else str(node.structure_type)
        return StructureType.is_pressure_pipe_like_str(sv) or getattr(node, 'is_pressure_pipe', False)

    
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
        2. 隧洞/渡槽/倒虹吸/有压管道都需要渐变段行；有压流建筑物侧的渐变段为占位行
           （水头损失已含在有压流建筑物水力计算中，通过 skip_loss 标记跳过计算）
        3. 有压管道 / 定向钻 / 顶管 相邻时：不插入渐变段，也不插入连接段
        4. 里程差 > 渐变段之和 时需要插入明渠段
        
        Args:
            node1: 前一节点（应为出口）
            node2: 后一节点（应为进口）
            all_nodes: 所有节点列表（用于查找上游明渠）
            
        Returns:
            dict: {
                'need_open_channel': bool,  # 是否需要明渠段
                'need_transition_1': bool,  # 是否需要出口渐变段
                'need_transition_2': bool,  # 是否需要进口渐变段
                'skip_loss_transition_1': bool,  # 出口渐变段是否跳过损失计算（有压流占位）
                'skip_loss_transition_2': bool,  # 进口渐变段是否跳过损失计算（有压流占位）
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
        if not self._matches_gap_outlet_role(node1):
            return result
        
        # node2必须是进口
        if not self._matches_gap_inlet_role(node2):
            return result
        
        # 分水闸/分水口与任何建筑物之间不插入明渠段
        if self._is_diversion_gate_type(node1.structure_type):
            return result
        if self._is_diversion_gate_type(node2.structure_type):
            return result

        # 里程差作为后续判断与调试详情的基础值，提前统一写入。
        result['distance'] = node2.station_MC - node1.station_MC

        # 有压管道 / 定向钻 / 顶管 本质都按同类承压结构处理，
        # 相邻时不再额外插入渐变段或连接段。
        if self._should_skip_pressure_pipe_like_gap(node1, node2, all_nodes):
            return result

        # 判断是否需要渐变段（隧洞/渡槽/倒虹吸/有压管道都需要渐变段行）
        is_node1_tunnel_aqueduct = self._is_tunnel_or_aqueduct(node1.structure_type)
        is_node2_tunnel_aqueduct = self._is_tunnel_or_aqueduct(node2.structure_type)
        
        # 使用统一的有压流建筑物判断（倒虹吸或有压管道）
        is_node1_pressurized = self.is_pressurized_flow_structure(node1)
        is_node2_pressurized = self.is_pressurized_flow_structure(node2)
        
        is_node1_culvert = self._is_culvert_type(node1.structure_type)
        is_node2_culvert = self._is_culvert_type(node2.structure_type)
        
        result['need_transition_1'] = is_node1_tunnel_aqueduct or is_node1_pressurized or is_node1_culvert
        result['need_transition_2'] = is_node2_tunnel_aqueduct or is_node2_pressurized or is_node2_culvert
        
        # 有压流建筑物（倒虹吸/有压管道）侧的渐变段为占位行，水头损失已包含在其水力计算中
        result['skip_loss_transition_1'] = is_node1_pressurized
        result['skip_loss_transition_2'] = is_node2_pressurized
        
        # 估算渐变段长度
        gap_index = None
        if all_nodes:
            # 查找node1在all_nodes中的索引
            for idx, n in enumerate(all_nodes):
                if n is node1:
                    gap_index = idx
                    break

        if result['need_transition_1']:
            result['transition_length_1'] = self._estimate_transition_length(
                node1,
                "出口",
                all_nodes,
                gap_index,
                upstream_node=node1,
                downstream_node=node2,
            )
        if result['need_transition_2']:
            result['transition_length_2'] = self._estimate_transition_length(
                node2,
                "进口",
                all_nodes,
                gap_index,
                upstream_node=node1,
                downstream_node=node2,
            )

        total_transition_length = result['transition_length_1'] + result['transition_length_2']

        # 渐变段长度压缩处理
        if total_transition_length > result['distance'] and result['distance'] > 0:
            # 当总长度超过可用里程时，合并为单个渐变段。
            # 这里只合并采用长度，不改变两侧原本“需要渐变段”的语义，
            # 这样预扫描、直接判断和最终插入的口径保持一致。
            result['transition_length_1'] = result['distance']
            result['transition_length_2'] = 0.0
            result['use_merged_transition'] = True
        else:
            result['use_merged_transition'] = False

        # 可用于明渠的长度（基于压缩后的长度）
        result['available_length'] = max(
            0.0,
            result['distance'] - result['transition_length_1'] - result['transition_length_2'],
        )

        # 判断是否需要插入明渠段
        result['need_open_channel'] = result['available_length'] > 0

        return result

    @staticmethod
    def _transition_has_effective_length(transition: ChannelNode) -> bool:
        """判断渐变段是否具有有效长度，零长度行不再写入表格。"""
        length = float(getattr(transition, 'transition_length', 0.0) or 0.0)
        stat_length = float(getattr(transition, 'stat_length', 0.0) or 0.0)
        return max(length, stat_length) > ZERO_TOLERANCE

    def _append_effective_transition(self, container: List[ChannelNode], transition: ChannelNode) -> bool:
        """仅在渐变段长度有效时才追加到结果列表。"""
        if not self._transition_has_effective_length(transition):
            return False
        container.append(transition)
        return True
    
    def _check_gap_exit_to_gate(self, exit_node: ChannelNode, gate_node: ChannelNode, nodes=None, gap_index=None) -> Dict:
        """
        检查出口结构物→分水闸之间是否需要插入明渠段。

        规则：
        - 所有特殊建筑物（隧洞/渡槽/矩形暗涵/有压管道/倒虹吸）出口后接闸时，都需要插入出口渐变段
        - 所有闸前后的渐变段都标记 skip_loss=True
        - 渐变段长度不能超过可用里程，超过时压缩到可用里程
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
        if not self._matches_gap_outlet_role(exit_node):
            return result
        result['distance'] = gate_node.station_MC - exit_node.station_MC
        if result['distance'] <= 0:
            return result
        # 判断是否为特殊建筑物（隧洞/渡槽/矩形暗涵/有压管道/倒虹吸）
        result['need_transition_1'] = (
            self._is_tunnel_or_aqueduct(exit_node.structure_type)
            or self.is_pressurized_flow_structure(exit_node)
            or self._is_culvert_type(exit_node.structure_type)
        )
        # 所有闸前后的渐变段都标记 skip_loss=True
        result['skip_loss_transition_1'] = result['need_transition_1']
        if result['need_transition_1']:
            calculated_length = self._estimate_transition_length(
                exit_node,
                "出口",
                nodes=nodes, gap_index=gap_index,
                upstream_node=exit_node,
                downstream_node=gate_node,
            )
            # 渐变段长度不能超过可用里程
            result['transition_length_1'] = min(calculated_length, result['distance'])
        result['available_length'] = max(0.0, result['distance'] - result['transition_length_1'])
        result['need_open_channel'] = result['available_length'] > 0
        return result

    def _check_gap_gate_to_entry(self, gate_node: ChannelNode, entry_node: ChannelNode, nodes=None, gap_index=None) -> Dict:
        """
        检查分水闸→进口结构物之间是否需要插入明渠段。

        规则：
        - 闸后接特殊建筑物（隧洞/渡槽/矩形暗涵/有压管道/倒虹吸）进口时，都需要插入进口渐变段
        - 所有闸前后的渐变段都标记 skip_loss=True
        - 渐变段长度不能超过可用里程，超过时压缩到可用里程
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
        if not self._matches_gap_inlet_role(entry_node):
            return result
        result['distance'] = entry_node.station_MC - gate_node.station_MC
        if result['distance'] <= 0:
            return result
        # 判断是否为特殊建筑物（隧洞/渡槽/矩形暗涵/有压管道/倒虹吸）
        result['need_transition_2'] = (
            self._is_tunnel_or_aqueduct(entry_node.structure_type)
            or self.is_pressurized_flow_structure(entry_node)
            or self._is_culvert_type(entry_node.structure_type)
        )
        # 所有闸前后的渐变段都标记 skip_loss=True
        result['skip_loss_transition_2'] = result['need_transition_2']
        if result['need_transition_2']:
            calculated_length = self._estimate_transition_length(
                entry_node,
                "进口",
                nodes=nodes, gap_index=gap_index,
                upstream_node=gate_node,
                downstream_node=entry_node,
            )
            # 渐变段长度不能超过可用里程
            result['transition_length_2'] = min(calculated_length, result['distance'])
        result['available_length'] = max(0.0, result['distance'] - result['transition_length_2'])
        result['need_open_channel'] = result['available_length'] > 0
        return result

    @staticmethod
    def _get_structure_type_name(node: Optional[ChannelNode]) -> str:
        """获取节点结构类型字符串。"""
        if not node or not getattr(node, 'structure_type', None):
            return ""
        structure_type = node.structure_type
        return structure_type.value if hasattr(structure_type, 'value') else str(structure_type or "")

    def _set_transition_rule_context(self, transition_node: ChannelNode,
                                     upstream_node: Optional[ChannelNode],
                                     downstream_node: Optional[ChannelNode]) -> None:
        """写入渐变段规则追溯上下文。"""
        transition_node.transition_rule_upstream_structure_type = self._get_structure_type_name(upstream_node)
        transition_node.transition_rule_downstream_structure_type = self._get_structure_type_name(downstream_node)

    def _hydrate_transition_length_state(self, transition_node: ChannelNode,
                                         prev_node: ChannelNode,
                                         next_node: ChannelNode,
                                         actual_length: Optional[float] = None,
                                         preserve_existing_length: bool = False,
                                         physical_limit: Optional[float] = None) -> Dict[str, Any]:
        """补齐渐变段长度详情，并同步最终长度/来源/告警。"""
        details = self.hyd_calc.ensure_transition_length_details(
            transition_node,
            prev_node,
            next_node,
            [prev_node, transition_node, next_node],
            actual_length=actual_length,
            preserve_existing_length=preserve_existing_length,
            physical_limit=physical_limit,
        )
        transition_node.transition_length = details.get(
            "actual_length",
            getattr(transition_node, "transition_length", 0.0) or 0.0,
        )
        transition_node.stat_length = max(0.0, transition_node.transition_length or 0.0)
        transition_node.transition_length_source = details.get(
            "source",
            getattr(transition_node, "transition_length_source", "formula") or "formula",
        )
        transition_node.transition_length_warning = details.get(
            "warning",
            getattr(transition_node, "transition_length_warning", "") or "",
        )
        return details

    def _estimate_transition_length(self, node: ChannelNode, transition_type: str,
                                    nodes: List[ChannelNode] = None,
                                    gap_index: int = None,
                                    upstream_node: Optional[ChannelNode] = None,
                                    downstream_node: Optional[ChannelNode] = None) -> float:
        """
        快速估算渐变段长度（用于判断是否需要插入明渠）

        Args:
            node: 建筑物节点
            transition_type: "进口"或"出口"
            nodes: 可选，节点列表（用于查找参考明渠）
            gap_index: 可选，空隙位置索引

        Returns:
            估算的渐变段长度(m)
        """
        # 已拟定的连接断面与最终插入使用同一套长度公式及组合规则。
        if nodes and gap_index is not None:
            left, right = gap_index, min(len(nodes) - 1, gap_index + 1)
            target_index = right if self._is_diversion_gate_type(nodes[left].structure_type) else left
            reference = (self._find_reference_segment_same_section_v2(nodes, target_index, left, right)
                         or self._find_reference_segment_cross_section_v2(nodes, target_index, left, right))
            if reference and not reference.get('recalculation_error'):
                params = self._build_open_channel_params_from_reference(reference, node.flow_section, node.flow)
                return self._connection_transition_length(node, transition_type, params, nodes[left], nodes[right])
        # 获取特征宽度
        B = self._get_characteristic_width(node)
        if B <= 0:
            B = 3.0  # 默认3m

        # 尝试查找参考明渠的底宽
        B_channel = None
        if nodes and gap_index is not None:
            ref_channel = self._find_reference_segment_same_section_v2(
                nodes,
                gap_index,
                gap_index,
                min(len(nodes) - 1, gap_index + 1),
            ) or self._find_reference_segment_cross_section_v2(
                nodes, gap_index, gap_index, min(len(nodes) - 1, gap_index + 1),
            )
            if ref_channel:
                B_channel = ref_channel.get('bottom_width', 0)

        # 兜底：使用假设宽度
        if not B_channel or B_channel <= 0:
            B_channel = B * 1.2

        coefficient = TRANSITION_LENGTH_COEFFICIENTS.get(transition_type, 3.0)
        L_basic = coefficient * abs(B_channel - B)

        # 约束水深优先跟正式计算保持一致：
        # 先取渐变段相邻明渠水深，再回退同流量段参考明渠，最后才用节点自身/默认值。
        h_design = self._resolve_transition_estimate_channel_depth(
            node,
            transition_type,
            nodes=nodes,
            gap_index=gap_index,
            upstream_node=upstream_node,
            downstream_node=downstream_node,
        )
        struct_name = node.structure_type.value if node.structure_type else ""
        
        if "渡槽" in struct_name:
            L_min = 6 * h_design if transition_type == "进口" else 8 * h_design
            return max(L_basic, L_min)
        elif "隧洞" in struct_name:
            D = node.section_params.get("D", 3.0) if node.section_params else 3.0
            L_min = max(5 * h_design, 3 * D)
            return max(L_basic, L_min)
        elif "倒虹吸" in struct_name or StructureType.is_pressure_pipe_like_str(struct_name):
            # GB 50288-2018 §10.2.4：有压流建筑物（倒虹吸/有压管道）使用相同公式
            # 进口取上游渠道设计水深的3~5倍（取大值5倍）
            # 出口取下游渠道设计水深的4~6倍（取大值6倍）
            L_pressurized = 5 * h_design if transition_type == "进口" else 6 * h_design
            L_basic = L_pressurized

        preview_transition = ChannelNode()
        preview_transition.is_transition = True
        preview_transition.structure_type = StructureType.TRANSITION
        preview_transition.transition_type = transition_type
        preview_transition.flow_section = node.flow_section
        preview_transition.roughness = node.roughness if node.roughness > 0 else self.settings.roughness

        if upstream_node is None:
            upstream_node = node if transition_type == "出口" else None
        if downstream_node is None:
            downstream_node = node if transition_type == "进口" else None
        if upstream_node is None:
            upstream_node = node
        if downstream_node is None:
            downstream_node = node

        self._set_transition_rule_context(
            preview_transition,
            upstream_node,
            downstream_node,
        )
        resolved = self.hyd_calc.resolve_transition_length_from_formula(
            L_basic,
            preview_transition,
            upstream_node,
            downstream_node,
        )
        return resolved.get('selected_length', L_basic)

    def _connection_transition_length(self, structure, transition_type, params, left, right):
        """按已采用的断面计算一侧渐变段，组合规则仍按原始建筑物对匹配。"""
        channel = self._create_open_channel_node(params, left, right)
        transition = ChannelNode(is_transition=True, structure_type=StructureType.TRANSITION)
        transition.transition_type = transition_type
        transition.flow_section = params.flow_section
        self._set_transition_rule_context(transition, left, right)
        previous, following = (structure, channel) if transition_type == "出口" else (channel, structure)
        formula = self.hyd_calc.calculate_transition_length(transition, previous, following, [previous, following])
        return self.hyd_calc.resolve_transition_length_from_formula(
            formula, transition, previous, following,
        ).get("selected_length", formula)

    def _reflow_connection_layout(self, layout, left, right, params):
        """用户修改断面后重分配长度，确保各子段之和不超过真实空隙。"""
        result = dict(layout)
        for index, node, kind in ((1, left, "出口"), (2, right, "进口")):
            result[f"transition_length_{index}"] = (
                self._connection_transition_length(node, kind, params, left, right)
                if result[f"need_transition_{index}"] else 0.0
            )
        total = result["transition_length_1"] + result["transition_length_2"]
        result["use_merged_transition"] = total >= result["distance"] > 0
        if result["use_merged_transition"]:
            result["transition_length_1"] = result["distance"] if result["need_transition_1"] else 0.0
            result["transition_length_2"] = 0.0 if result["need_transition_1"] else result["distance"]
        result["available_length"] = max(0.0, result["distance"] - total)
        result["need_open_channel"] = result["available_length"] > ZERO_TOLERANCE
        return result

    def _resolve_transition_estimate_channel_depth(
        self,
        node: ChannelNode,
        transition_type: str,
        nodes: List[ChannelNode] = None,
        gap_index: int = None,
        upstream_node: Optional[ChannelNode] = None,
        downstream_node: Optional[ChannelNode] = None,
    ) -> float:
        """为插入阶段估算渐变段长度补齐与正式计算一致的渠道设计水深来源。"""
        channel_depth = 0.0

        adjacent_channel = downstream_node if transition_type == "出口" else upstream_node
        # 这里只能读取真正相邻明渠的设计水深，不能把另一侧建筑物水深误当成明渠口径。
        if adjacent_channel and self._is_any_channel_type(getattr(adjacent_channel, "structure_type", None)):
            channel_depth = float(getattr(adjacent_channel, "water_depth", 0.0) or 0.0)
            if channel_depth <= 0 and getattr(adjacent_channel, "section_params", None):
                params = adjacent_channel.section_params or {}
                channel_depth = float(params.get("水深", params.get("h", 0.0)) or 0.0)

        ref_channel = None
        if channel_depth <= 0 and nodes and gap_index is not None:
            ref_channel = self._find_reference_segment_same_section_v2(
                nodes,
                gap_index,
                gap_index,
                min(len(nodes) - 1, gap_index + 1),
            )
            if ref_channel:
                channel_depth = float(ref_channel.get("water_depth", 0.0) or 0.0)

        if channel_depth <= 0 and nodes:
            channel_depth = float(
                self.hyd_calc.get_channel_design_depth(node.flow_section, nodes) or 0.0
            )

        if channel_depth <= 0:
            channel_depth = float(getattr(node, "water_depth", 0.0) or 0.0)
            if channel_depth <= 0 and getattr(node, "section_params", None):
                params = node.section_params or {}
                channel_depth = float(params.get("水深", params.get("h", 0.0)) or 0.0)

        if channel_depth <= 0:
            channel_depth = 2.0

        return channel_depth
    
    def _find_global_nearest_channel(self, nodes: List[ChannelNode],
                                     gap_index: int) -> Optional[Dict]:
        """跨流量段查找距离空隙最近的明渠节点（用于取 i/n/m 参考值）"""
        best = None
        best_dist = float('inf')
        for idx, node in enumerate(nodes):
            if not self._is_any_channel_type(node.structure_type):
                continue
            dist = abs(idx - gap_index)
            if dist < best_dist:
                best_dist = dist
                best = node
        if best is None:
            return None
        sp = best.section_params or {}
        return {
            'slope_i': best.slope_i if best.slope_i and best.slope_i > 0 else 1.0 / 3000,
            'roughness': best.roughness if best.roughness > 0 else 0.014,
            'side_slope': sp.get('m', 1.0),
        }

    @staticmethod
    def _compute_economic_section(Q: float, slope_i: float, roughness: float,
                                   m_trapez: float = 1.0) -> Dict:
        """
        用实用经济断面公式计算4种明渠类型的断面参数。

        经济断面约束：
          矩形：B = 2h
          梯形：B = 2h(√(1+m²) - m)
          圆形：满流设计（h=D×0.75作为设计水深）
          U形： R = 等效圆直径/2（h=R+B/2 时接近经济断面）

        Returns:
            dict，键为结构类型名，值为参数字典
        """
        import math

        n = roughness
        i = slope_i
        results = {}

        def bisect(f_q, target, lo=0.001, hi=30.0, tol=1e-6, max_iter=200):
            """二分法求 f_q(x)=target 中的 x"""
            for _ in range(max_iter):
                mid = (lo + hi) / 2
                val = f_q(mid)
                if abs(val - target) / max(target, 1e-10) < tol:
                    return mid
                if val < target:
                    lo = mid
                else:
                    hi = mid
            return (lo + hi) / 2

        slope_inv = round(1.0 / i) if i > 0 else 3000

        # ── 矩形 (m=0, B=2h) ──────────────────────────────────────────
        def q_rect(h):
            B = 2 * h
            A = B * h
            P = B + 2 * h
            R = A / P
            return (1 / n) * A * R ** (2 / 3) * math.sqrt(i)

        h_r = bisect(q_rect, Q)
        B_r = 2 * h_r
        results['明渠-矩形'] = {
            'structure_type': '明渠-矩形',
            'bottom_width': round(B_r, 3),
            'water_depth': round(h_r, 3),
            'side_slope': 0.0,
            'roughness': roughness,
            'slope_inv': slope_inv,
            'arc_radius': 0.0,
            'theta_deg': 0.0,
        }

        # ── 梯形 (B = 2h(√(1+m²)-m)) ──────────────────────────────────
        m = m_trapez
        alpha = 2 * (math.sqrt(1 + m * m) - m)

        def q_trap(h):
            B = alpha * h
            A = (B + m * h) * h
            P = B + 2 * h * math.sqrt(1 + m * m)
            R = A / P if P > 0 else 0
            return (1 / n) * A * R ** (2 / 3) * math.sqrt(i)

        h_t = bisect(q_trap, Q)
        B_t = alpha * h_t
        results['明渠-梯形'] = {
            'structure_type': '明渠-梯形',
            'bottom_width': round(B_t, 3),
            'water_depth': round(h_t, 3),
            'side_slope': m_trapez,
            'roughness': roughness,
            'slope_inv': slope_inv,
            'arc_radius': 0.0,
            'theta_deg': 0.0,
        }

        # ── 圆形（调用 明渠设计.quick_calculate_circular 自动搜索最优D）──
        D_c = 0.0
        h_c = 0.0
        try:
            from 明渠设计 import quick_calculate_circular as _circ_calc
            circ_res = _circ_calc(Q=Q, n=n, slope_inv=slope_inv, v_min=0.1, v_max=100.0)
            if circ_res.get('success'):
                D_c = circ_res.get('D_design') or circ_res.get('D', 0.0)
                h_c = circ_res.get('y_d') or circ_res.get('h_design', 0.0)
        except Exception:
            pass
        if D_c <= 0:
            # 回退到简单满流公式
            def q_circ_full(D):
                r = D / 2
                A = math.pi * r * r
                R_hyd = D / 4
                return (1 / n) * A * R_hyd ** (2 / 3) * math.sqrt(i)
            D_c = bisect(q_circ_full, Q, 0.01, 30.0)
            h_c = D_c
        results['明渠-圆形'] = {
            'structure_type': '明渠-圆形',
            'bottom_width': round(D_c, 3),   # 直径 D
            'water_depth': round(h_c, 3),
            'side_slope': 0.0,
            'roughness': roughness,
            'slope_inv': slope_inv,
            'arc_radius': 0.0,
            'theta_deg': 0.0,
        }

        # ── U形（只预填 n/slope，R 和 h 由用户手动输入）─────────────────
        results['明渠-U形'] = {
            'structure_type': '明渠-U形',
            'bottom_width': 0.0,    # 用户填写
            'water_depth': 0.0,     # 用户填写
            'side_slope': 0.0,
            'roughness': roughness,
            'slope_inv': slope_inv,
            'arc_radius': 0.0,      # 用户填写
            'theta_deg': 0.0,
        }

        return results

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
                    'arc_radius': node.section_params.get('R_circle', 0) if node.section_params else 0,
                    'theta_deg': node.section_params.get('theta_deg', 0) if node.section_params else 0,
                }
        return None

    def _is_any_channel_type(self, structure_type) -> bool:
        """判断是否为任意明渠类型（含旧版'矩形'兼容值）"""
        if structure_type is None:
            return False
        sv = self._normalize_structure_type_value(structure_type)
        return sv in ("明渠-梯形", "明渠-矩形", "明渠-圆形", "明渠-U形", "矩形", FILL_CHANNEL_TEXT)

    def _find_reference_channel_same_section(self, nodes: List[ChannelNode],
                                              gap_index: int) -> Optional[Dict]:
        """
        在同一流量段内查找参考明渠，按优先级选取最佳类型，返回最近节点的参数。

        优先级：矩形/明渠-矩形 > 明渠-梯形 > 明渠-圆形 > 明渠-U形

        Args:
            nodes: 节点列表
            gap_index: 空隙所在位置（取 nodes[gap_index].flow_section 确定流量段）

        Returns:
            参数字典或None（同流量段内没有任何明渠时返回None）
        """
        flow_section = nodes[gap_index].flow_section if gap_index < len(nodes) else None

        # 优先级分组（同组内任意一种都算同等优先）
        PRIORITY_GROUPS = [
            {"明渠-矩形", "矩形", FILL_CHANNEL_TEXT},
            {"明渠-梯形"},
            {"明渠-圆形"},
            {"明渠-U形"},
        ]

        # 收集同流量段内所有明渠节点，按优先级分组
        groups: List[List] = [[] for _ in PRIORITY_GROUPS]
        for idx, node in enumerate(nodes):
            if node.flow_section != flow_section:
                continue
            if not self._is_any_channel_type(node.structure_type):
                continue
            sv = self._normalize_structure_type_value(node.structure_type)
            for g_idx, group in enumerate(PRIORITY_GROUPS):
                if sv in group:
                    groups[g_idx].append((idx, node))
                    break

        # 取最高优先级且非空的分组
        target_nodes = []
        target_type_canonical = None
        for g_idx, grp in enumerate(groups):
            if grp:
                target_nodes = grp
                # canonical type（统一旧版'矩形'→'明渠-矩形'）
                sv0 = grp[0][1].structure_type.value if grp[0][1].structure_type else ""
                target_type_canonical = "明渠-矩形" if sv0 == "矩形" else sv0
                break

        if not target_nodes:
            return None, None   # 同段无明渠，触发经济断面回退

        # 取距离 gap_index 最近的节点
        closest_idx, closest_node = min(target_nodes, key=lambda t: abs(t[0] - gap_index))

        sp = closest_node.section_params or {}
        bw = sp.get("B", 0)
        if bw == 0:
            bw = sp.get("D", 0)

        channel = {
            'name': closest_node.name,
            'structure_type': target_type_canonical,
            'bottom_width': bw,
            'water_depth': closest_node.water_depth,
            'side_slope': sp.get("m", 0),
            'roughness': closest_node.roughness,
            'slope_inv': 1.0 / closest_node.slope_i if closest_node.slope_i and closest_node.slope_i > 0 else 3000,
            'flow': closest_node.flow,
            'flow_section': closest_node.flow_section,
            'structure_height': closest_node.structure_height,
            'arc_radius': sp.get('R_circle', 0),
            'theta_deg': sp.get('theta_deg', 0),
        }
        return channel, None   # 无需经济断面选项
    
    def _reference_family_for_gap_type(self, structure_type) -> str:
        sv = self._get_effective_structure_type_value(structure_type)
        if sv == "矩形暗涵" or "暗涵" in sv:
            return "culvert"
        if sv in ("明渠-梯形", "明渠-矩形", "明渠-圆形", "明渠-U形", FILL_CHANNEL_TEXT):
            return "open_channel"
        return ""

    def _is_reference_segment_type_v2(self, structure_type) -> bool:
        return self._reference_family_for_gap_type(structure_type) in {"open_channel", "culvert"}

    def _extract_reference_segment_v2(self, node: ChannelNode) -> Dict[str, Any]:
        sp = node.section_params or {}
        structure_type = self._get_effective_structure_type_value(node)
        bottom_width = sp.get("B", 0) or sp.get("D", 0)
        if bottom_width == 0 and structure_type == "明渠-U形":
            bottom_width = sp.get("R_circle", 0)
        return {
            "name": node.name,
            "structure_type": structure_type,
            "section_family": self._reference_family_for_gap_type(structure_type),
            "bottom_width": bottom_width,
            "water_depth": node.water_depth,
            "side_slope": sp.get("m", 0),
            "roughness": node.roughness,
            "slope_inv": 1.0 / node.slope_i if node.slope_i and node.slope_i > 0 else 3000,
            "flow": node.flow,
            "flow_section": node.flow_section,
            "structure_height": node.structure_height or sp.get("H_total", 0),
            "arc_radius": sp.get("R_circle", 0),
            "theta_deg": sp.get("theta_deg", 0),
            "source_name": node.name,
        }

    def _find_reference_segment_same_section_v2(
        self,
        nodes: List[ChannelNode],
        gap_index: int,
        left_index: int,
        right_index: int,
    ) -> Optional[Dict]:
        return self._find_connection_reference(nodes, gap_index, left_index, right_index, True)

    def _reference_froude(self, node: ChannelNode) -> Optional[float]:
        """按实际断面的水力深度判别流态，缺少数据时不认定为缓流。"""
        if not math.isfinite(node.flow) or node.flow <= 0:
            return None
        area = self.hyd_calc.get_cross_section_area(node)
        width = self.hyd_calc.get_water_surface_width(node)
        if not all(math.isfinite(v) and v > 0 for v in (area, width)):
            return None
        return node.flow / area / math.sqrt(GRAVITY * area / width)

    def _open_reference_with_slope(self, template, slope_node, target):
        """明渠只借坡降，按目标流量重算水深并复核缓流，不继承隧洞形式。"""
        if not positive(slope_node.slope_i):
            return None
        ref = self._extract_reference_segment_v2(template)
        ref.update(
            slope_inv=1.0 / slope_node.slope_i,
            reference_source_flow_section=template.flow_section,
            slope_source_name=slope_node.name,
            slope_source_type=self._get_effective_structure_type_value(slope_node),
            slope_source_flow_section=slope_node.flow_section,
            slope_borrowed_from_tunnel="隧洞" in self._get_effective_structure_type_value(slope_node),
        )
        return recalculate_open_channel(
            ref, target.flow, target.flow_section,
            max_flow_for_section(self.settings, target.flow_section, target.flow),
        )

    @staticmethod
    def connection_gap_key(left, right):
        """以真实端点标识单处连接段，不依赖插入后变化的表格行号。"""
        def endpoint(node):
            coords = (round(node.x, 4), round(node.y, 4))
            location = coords if any(coords) else ("station", round(node.station_MC, 4))
            return (flow_section_key(node.flow_section), node.name, node.get_structure_type_str(), location)
        return json.dumps((endpoint(left), endpoint(right)), ensure_ascii=False, separators=(",", ":"))

    def _recalculate_saved_connection(self, reference, target, source_kind):
        """用户指定的断面保持原几何，流量改变后不使用旧水深。"""
        ref = copy.deepcopy(reference)
        ref["source_kind"] = source_kind
        ref.pop("recalculation_error", None)
        if self._reference_family_for_gap_type(ref.get("structure_type")) == "open_channel":
            result = recalculate_open_channel(
                ref, target.flow, target.flow_section,
                max_flow_for_section(self.settings, target.flow_section, target.flow),
                require_subcritical=False,
            )
        else:
            from 矩形暗涵设计 import solve_water_depth_rectangular
            from 隧洞设计 import solve_water_depth_horseshoe
            B, H, n, inverse = (ref.get(key) for key in ("bottom_width", "structure_height", "roughness", "slope_inv"))
            result = None
            if all(positive(v) for v in (B, H, n, inverse, target.flow)):
                if "圆拱直墙" in ref.get("structure_type", ""):
                    h, ok = solve_water_depth_horseshoe(B, H, math.radians(ref.get("theta_deg", 180)), n, 1 / inverse, target.flow)
                else:
                    h, ok = solve_water_depth_rectangular(B, H, n, 1 / inverse, target.flow)
                if ok and positive(h):
                    ref.update(water_depth=h, flow=target.flow, flow_section=target.flow_section)
                    result = ref
        if result is None:
            # 保留输入供补段窗口修正，不能沿用旧水深，也不能悄悄替换用户断面。
            ref.update(water_depth=0.0, flow=target.flow, flow_section=target.flow_section,
                       auto_calculated=False, recalculation_error="已存断面无法满足当前流量，请调整断面参数。")
            return ref
        return result

    def remember_connection_edits(self, nodes):
        """重新插入前识别表中人工改动，按真实端点保存单处断面输入。"""
        for node in nodes:
            previous = getattr(node, "connection_source_details", {}) or {}
            key = previous.get("gap_key")
            if not node.is_auto_inserted_channel or not key:
                continue
            current = self._extract_reference_segment_v2(node)
            if current['structure_type'] == '明渠-U形':
                current['bottom_width'] = 0.0
            current['slope_inv'] = 1.0 / node.slope_i if node.slope_i > 0 else 0.0
            changed = current['structure_type'] != previous.get('structure_type')
            precision = {'bottom_width': 3, 'arc_radius': 3, 'side_slope': 2, 'roughness': 4, 'slope_inv': 10}
            if self._reference_family_for_gap_type(node) == 'culvert':
                precision['structure_height'] = 3
            for field, digits in precision.items():
                if not math.isclose(float(current.get(field, 0) or 0), round(float(previous.get(field, 0) or 0), digits), abs_tol=1e-9):
                    changed = True
            if changed:
                saved = copy.deepcopy(previous)
                saved.update(current)
                saved.update(source_kind='user_override', user_modified=True)
                for field in ('slope_source_name', 'slope_source_type', 'slope_borrowed_from_tunnel', 'roughness_source'):
                    saved.pop(field, None)
                self.settings.connection_channel_overrides[key] = saved

    def _infer_rectangular_connection(self, candidates, target):
        """缺少明渠时借无压建筑物底宽拟定矩形明渠，缺少底宽才用经济断面。"""
        structures = [(i, node) for i, node in candidates
                      if not self.is_pressurized_flow_structure(node)
                      and (self._is_tunnel_or_aqueduct(node.structure_type) or self._is_culvert_type(node.structure_type))]
        slopes = [(i, node) for i, node in structures if positive(node.slope_i)]
        if not slopes or not positive(target.flow) or not positive(self.settings.roughness):
            return None
        geometries = [(i, node) for i, node in structures
                      if positive((node.section_params or {}).get("B"))
                      and any(label in self._get_effective_structure_type_value(node) for label in ("矩形", "圆拱直墙"))]
        # 不用倒虹吸管径或圆形隧洞直径代替矩形明渠底宽。
        for _, geometry in geometries or [(None, None)]:
            for _, slope in slopes:
                source_kind = "inferred_rectangular" if geometry else "economic_rectangular"
                if geometry:
                    width = float(geometry.section_params["B"])
                else:
                    h = (target.flow * self.settings.roughness / (2 * 0.5 ** (2 / 3) * math.sqrt(slope.slope_i))) ** (3 / 8)
                    width = math.ceil(2 * h * 100) / 100
                ref = {
                    "name": "-", "structure_type": "明渠-矩形", "bottom_width": width,
                    "side_slope": 0.0, "roughness": self.settings.roughness,
                    "slope_inv": 1.0 / slope.slope_i, "source_kind": source_kind,
                    "geometry_source_name": geometry.name if geometry else "水力最佳矩形断面",
                    "geometry_source_type": self._get_effective_structure_type_value(geometry) if geometry else "",
                    "source_name": geometry.name if geometry else slope.name,
                    "reference_source_flow_section": (geometry or slope).flow_section,
                    "slope_source_name": slope.name,
                    "slope_source_type": self._get_effective_structure_type_value(slope),
                    "slope_source_flow_section": slope.flow_section,
                    "roughness_source": "项目渠道糙率",
                }
                result = recalculate_open_channel(
                    ref, target.flow, target.flow_section,
                    max_flow_for_section(self.settings, target.flow_section, target.flow),
                )
                if result:
                    return result
        return None

    def _find_connection_reference(self, nodes, gap_index, left_index, right_index, same_section):
        """统一处理单处覆盖、明渠模板、既有参考及无明渠时的自动拟定。"""
        if not 0 <= gap_index < len(nodes):
            return None
        target = nodes[gap_index]
        gap_key = self.connection_gap_key(nodes[left_index], nodes[right_index])

        def finish(reference):
            if reference:
                reference["gap_key"] = gap_key
                reference["max_flow"] = max_flow_for_section(self.settings, target.flow_section, target.flow)
            return reference

        prepared = getattr(self, "_connection_prepared_params", {}).get(gap_key)
        if prepared is not None:
            return finish(params_to_reference(prepared))
        if same_section and gap_key in self.settings.connection_channel_overrides:
            return finish(self._recalculate_saved_connection(
                self.settings.connection_channel_overrides[gap_key], target, "user_override"))
        left, right = left_index, right_index
        while left >= 0 and self._is_diversion_gate_type(nodes[left].structure_type):
            left -= 1
        while right < len(nodes) and self._is_diversion_gate_type(nodes[right].structure_type):
            right += 1
        adjacent = [i for i in (left, right) if 0 <= i < len(nodes)]
        center = sum(nodes[i].station_MC for i in adjacent) / len(adjacent) if adjacent else 0
        use_station = len(adjacent) == 2 and nodes[adjacent[0]].station_MC != nodes[adjacent[1]].station_MC

        def distance(item):
            i, node = item
            return (abs(node.station_MC - center) if use_station else abs(i - gap_index), abs(i - gap_index), i)

        candidates = sorted(
            [(i, node) for i, node in enumerate(nodes)
             if (flow_section_key(node.flow_section) == flow_section_key(target.flow_section)) == same_section
             and not node.is_transition and not node.is_auto_inserted_channel],
            key=distance,
        )
        # 仅在连接处实际存在暗涵时延续暗涵，不从远处暗涵改变普通连接段的形式。
        for i, node in candidates:
            if i in adjacent and self._reference_family_for_gap_type(node) == "culvert":
                reference = self._extract_reference_segment_v2(node)
                reference['reference_source_flow_section'] = node.flow_section
                return finish(self._recalculate_saved_connection(reference, target, "adjacent_culvert"))

        template = self.settings.connection_channel_templates.get(flow_section_key(target.flow_section))
        if same_section and template:
            return finish(self._recalculate_saved_connection(template, target, "user_template"))

        channels = [(i, node) for i, node in candidates if self._reference_family_for_gap_type(node) == "open_channel"]
        for _, node in channels:
            froude = self._reference_froude(node)
            if froude is not None and froude < 1.0 - 1e-12:
                ref = self._open_reference_with_slope(node, node, target)
                if ref:
                    return finish(ref)

        # 没有合适明渠坡降时，仍用已有明渠的断面尺寸，只替换为邻近隧洞坡降。
        # 已有明渠换坡后仍为急流时，保留人工填写入口。
        tunnels = [node for _, node in candidates if "隧洞" in self._get_effective_structure_type_value(node)
                   and not self.is_pressurized_flow_structure(node)
                   and math.isfinite(node.slope_i) and node.slope_i > 0]
        for tunnel in tunnels:
            for _, template in channels:
                ref = self._open_reference_with_slope(template, tunnel, target)
                if ref:
                    return finish(ref)
        # 已有明渠但换坡仍不满足缓流条件时，不另造断面掩盖原有问题。
        if not channels:
            return finish(self._infer_rectangular_connection(candidates, target))
        return None

    def _find_reference_segment_cross_section_v2(
        self,
        nodes: List[ChannelNode],
        gap_index: int,
        left_index: int,
        right_index: int,
    ) -> Optional[Dict]:
        return self._find_connection_reference(nodes, gap_index, left_index, right_index, False)

    def _build_open_channel_params_from_reference(
        self,
        reference: Optional[Dict[str, Any]],
        default_flow_section: str,
        default_flow: float,
    ) -> Optional[OpenChannelParams]:
        if not reference:
            return None
        if reference.get('recalculation_error'):
            raise ValueError(reference['recalculation_error'])
        if reference.get("auto_calculated") or reference.get("source_kind") == "user_override":
            return reference_to_params(reference)
        return OpenChannelParams(
            name="-",
            structure_type=reference.get("structure_type", "明渠-梯形"),
            bottom_width=reference.get("bottom_width", 0.0),
            water_depth=reference.get("water_depth", 0.0),
            side_slope=reference.get("side_slope", 0.0),
            roughness=reference.get("roughness", 0.014),
            slope_inv=reference.get("slope_inv", 3000.0),
            flow=reference.get("flow", default_flow),
            flow_section=reference.get("flow_section", default_flow_section),
            structure_height=reference.get("structure_height", 0.0),
            arc_radius=reference.get("arc_radius", 0.0),
            theta_deg=reference.get("theta_deg", 0.0),
            reference_details=copy.deepcopy(reference),
        )

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
        structure_type = self._normalize_structure_type_value(params.structure_type)
        culvert_family_type = self._normalize_culvert_family_type_value(params.structure_type)
        enum_structure_type = culvert_family_type or structure_type
        open_channel.structure_type = StructureType.from_string(enum_structure_type)
        open_channel.flow_section = params.flow_section if params.flow_section else prev_node.flow_section
        
        # 设置断面参数（区分圆形、U形和非圆形）
        is_circular = "圆形" in params.structure_type and "U形" not in params.structure_type
        is_u_section = "U形" in params.structure_type and "明渠" in params.structure_type
        is_circular = "圆形" in structure_type and "U形" not in structure_type
        is_u_section = "U形" in structure_type and "明渠" in structure_type
        is_culvert = self._reference_family_for_gap_type(structure_type) == "culvert"
        is_arch_culvert = culvert_family_type == self._ARCH_CULVERT_FAMILY_TEXT
        if is_circular:
            # 圆形明渠：bottom_width 实际存储的是直径 D
            open_channel.section_params = {
                "D": params.bottom_width,
                "m": 0
            }
        elif is_culvert:
            open_channel.section_params = {
                "B": params.bottom_width,
                "H_total": params.structure_height,
                "m": 0,
            }
            if culvert_family_type:
                open_channel.section_params[self._CULVERT_FAMILY_TYPE_KEY] = culvert_family_type
            if is_arch_culvert and params.theta_deg > 0:
                open_channel.section_params["theta_deg"] = params.theta_deg
        elif is_u_section:
            # U形明渠：R_circle存圆弧半径，theta_deg存圆心角
            open_channel.section_params = {
                "R_circle": params.arc_radius,
                "m": params.side_slope,
                "theta_deg": params.theta_deg,
                "B": 0, "D": 0,
            }
        else:
            open_channel.section_params = {
                "B": params.bottom_width,
                "m": params.side_slope
            }
        open_channel.water_depth = params.water_depth
        open_channel.connection_source_details = copy.deepcopy(getattr(params, "reference_details", {}) or {})
        open_channel.velocity_increased = open_channel.connection_source_details.get("velocity_increased", 0.0)
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
            elif is_culvert:
                if is_arch_culvert:
                    self.hyd_calc.fill_section_params(open_channel)
                else:
                    outputs = calculate_rectangular_outputs(
                        params.bottom_width,
                        params.structure_height,
                        h,
                        params.roughness,
                        open_channel.slope_i,
                    )
                    if outputs.get("A", 0) > 0:
                        open_channel.section_params["A"] = round(outputs["A"], 3)
                        open_channel.section_params["X"] = round(outputs["P"], 3)
                        open_channel.section_params["R"] = round(outputs["R_hyd"], 3)
                        open_channel.velocity = round(outputs["V"], VELOCITY_PRECISION)
            elif is_u_section:
                # U形断面：复用 hydraulic_calc 的面积/湿周计算
                self.hyd_calc.fill_section_params(open_channel)
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
        self._set_transition_rule_context(transition, node1, node2)
        
        # 使用实际里程差作为长度
        transition.transition_length = distance
        transition.stat_length = distance
        transition.connection_source_details['merged_gap_length'] = distance
        
        # 继承参数
        transition.x = node1.x
        transition.y = node1.y
        transition.flow = node1.flow
        transition.roughness = node1.roughness if node1.roughness > 0 else self.settings.roughness
        
        # 有压流建筑物（倒虹吸/有压管道）侧复用倒虹吸渐变段配置
        is_pressurized = self.is_pressurized_flow_structure(node1) or self.is_pressurized_flow_structure(node2)
        if transition_type == "进口":
            if is_pressurized:
                form_attr, zeta_attr = 'siphon_transition_inlet_form', 'siphon_transition_inlet_zeta'
            else:
                form_attr, zeta_attr = 'transition_inlet_form', 'transition_inlet_zeta'
        else:
            if is_pressurized:
                form_attr, zeta_attr = 'siphon_transition_outlet_form', 'siphon_transition_outlet_zeta'
            else:
                form_attr, zeta_attr = 'transition_outlet_form', 'transition_outlet_zeta'
        
        if hasattr(self.settings, form_attr) and getattr(self.settings, form_attr):
            transition.transition_form = getattr(self.settings, form_attr)
        else:
            transition.transition_form = "曲线形反弯扭曲面"
        
        if hasattr(self.settings, zeta_attr) and getattr(self.settings, zeta_attr) > 0:
            transition.transition_zeta = getattr(self.settings, zeta_attr)
        
        return transition
    
    def _create_inlet_transition_node(self, next_node: ChannelNode,
                                      upstream_context_node: Optional[ChannelNode] = None) -> ChannelNode:
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
        self._set_transition_rule_context(
            transition,
            upstream_context_node,
            next_node,
        )
        
        # 继承坐标（使用后一节点的坐标）
        transition.x = next_node.x
        transition.y = next_node.y
        
        # 继承水力参数
        transition.flow = next_node.flow
        transition.roughness = next_node.roughness if next_node.roughness > 0 else self.settings.roughness
        
        # 进口渐变段形式：有压流建筑物复用倒虹吸配置
        form_attr = 'siphon_transition_inlet_form' if self.is_pressurized_flow_structure(next_node) else 'transition_inlet_form'
        zeta_attr = 'siphon_transition_inlet_zeta' if self.is_pressurized_flow_structure(next_node) else 'transition_inlet_zeta'
        if hasattr(self.settings, form_attr) and getattr(self.settings, form_attr):
            transition.transition_form = getattr(self.settings, form_attr)
        else:
            transition.transition_form = "曲线形反弯扭曲面"
        
        # 从设置中读取用户指定的ζ系数
        if hasattr(self.settings, zeta_attr) and getattr(self.settings, zeta_attr) > 0:
            transition.transition_zeta = getattr(self.settings, zeta_attr)
        
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
        self._set_transition_rule_context(transition, prev_node, next_node)
        
        # 继承坐标（使用前一节点的坐标）
        transition.x = prev_node.x
        transition.y = prev_node.y
        
        # 继承水力参数
        transition.flow = prev_node.flow
        transition.roughness = prev_node.roughness if prev_node.roughness > 0 else self.settings.roughness
        
        # 有压流建筑物（倒虹吸/有压管道）侧复用倒虹吸渐变段配置
        is_pressurized = self.is_pressurized_flow_structure(prev_node) or self.is_pressurized_flow_structure(next_node)
        if transition_type == "进口":
            if is_pressurized:
                form_attr, zeta_attr = 'siphon_transition_inlet_form', 'siphon_transition_inlet_zeta'
            else:
                form_attr, zeta_attr = 'transition_inlet_form', 'transition_inlet_zeta'
        else:
            if is_pressurized:
                form_attr, zeta_attr = 'siphon_transition_outlet_form', 'siphon_transition_outlet_zeta'
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
        deferred_nodes = []  # 闸→进口缺口：暂存待插入的节点（明渠段 + 进口渐变段），在下一个非闸节点前冲洗
        
        for i in range(len(nodes)):
            current_node = nodes[i]
            
            # 闸穿透：在闸群结束后、下一个非闸节点之前插入延迟节点
            if deferred_nodes and not self._is_diversion_gate_type(current_node.structure_type):
                new_nodes.extend(deferred_nodes)
                deferred_nodes = []
            
            new_nodes.append(current_node)
            
            if i >= len(nodes) - 1:
                continue
            
            next_node = nodes[i + 1]
            self._active_connection_gap_key = self.connection_gap_key(current_node, next_node)
            
            # --- 情况1：当前节点是闸 → 检查闸→进口方向的缺口（添加到延迟队列）---
            if self._is_diversion_gate_type(current_node.structure_type):
                gate_check = self._check_gap_gate_to_entry(current_node, next_node, nodes, i)
                if gate_check['need_open_channel']:
                    ref_idx = i + 1
                    upstream_channel = self._find_reference_segment_same_section_v2(nodes, ref_idx, i, i + 1)
                    if upstream_channel is None:
                        upstream_channel = self._find_reference_segment_cross_section_v2(nodes, ref_idx, i, i + 1)
                    open_channel_params = None
                    if open_channel_callback:
                        open_channel_params = open_channel_callback(
                            upstream_channel, gate_check['available_length'],
                            current_node.structure_type.value if current_node.structure_type else "",
                            next_node.structure_type.value if next_node.structure_type else "",
                            next_node.flow_section, next_node.flow
                        )
                    elif upstream_channel:
                        open_channel_params = self._build_open_channel_params_from_reference(
                            upstream_channel,
                            next_node.flow_section,
                            next_node.flow,
                        )
                    if open_channel_params:
                        gate_check = self._reflow_connection_layout(gate_check, current_node, next_node, open_channel_params)
                        upstream_channel = params_to_reference(open_channel_params)
                        if not gate_check['need_open_channel']:
                            open_channel_params = None
                    if open_channel_params:
                        oc_slope_i = 1.0 / open_channel_params.slope_inv if open_channel_params.slope_inv > 0 else 0
                        oc = self._create_open_channel_node(open_channel_params, current_node, next_node)
                        oc.stat_length = max(0.0, gate_check['available_length'])
                        deferred_nodes.append(oc)
                        if gate_check['need_transition_2']:
                            tr_in = self._create_inlet_transition_node(next_node, current_node)
                            tr_in.slope_i = oc_slope_i
                            tr_in.transition_skip_loss = gate_check.get('skip_loss_transition_2', False)
                            self._hydrate_transition_length_state(
                                tr_in,
                                oc,
                                next_node,
                                actual_length=gate_check.get('transition_length_2', 0.0),
                                preserve_existing_length=True,
                            )
                            self._append_effective_transition(deferred_nodes, tr_in)
                    elif gate_check['need_transition_2'] and gate_check['distance'] > 0:
                        merged = self._create_merged_transition_node(
                            current_node, next_node, gate_check['distance'], "进口")
                        merged.flow_section = next_node.flow_section
                        merged.flow = next_node.flow
                        merged.transition_skip_loss = gate_check.get('skip_loss_transition_2', False)
                        if upstream_channel:
                            us_sinv = upstream_channel.get('slope_inv', 0)
                            merged.slope_i = 1.0 / us_sinv if us_sinv > 0 else 0
                        self._hydrate_transition_length_state(
                            merged,
                            current_node,
                            next_node,
                            actual_length=gate_check['distance'],
                            preserve_existing_length=True,
                        )
                        self._append_effective_transition(deferred_nodes, merged)
                elif gate_check['need_transition_2'] and gate_check['distance'] > 0:
                    us_ch = (self._find_reference_segment_same_section_v2(nodes, i + 1, i, i + 1)
                             or self._find_reference_segment_cross_section_v2(nodes, i + 1, i, i + 1))
                    merged = self._create_merged_transition_node(
                        current_node, next_node, gate_check['distance'], "进口")
                    merged.flow_section = next_node.flow_section
                    merged.flow = next_node.flow
                    merged.transition_skip_loss = gate_check.get('skip_loss_transition_2', False)
                    if us_ch:
                        us_sinv = us_ch.get('slope_inv', 0)
                        merged.slope_i = 1.0 / us_sinv if us_sinv > 0 else 0
                    self._hydrate_transition_length_state(
                        merged,
                        current_node,
                        next_node,
                        actual_length=gate_check['distance'],
                        preserve_existing_length=True,
                    )
                    self._append_effective_transition(deferred_nodes, merged)
                continue

            # --- 情况2：下一节点是闸 → 只检查出口→闸方向的缺口（直接插入）---
            if self._is_diversion_gate_type(next_node.structure_type):
                gate_check = self._check_gap_exit_to_gate(current_node, next_node, nodes, i)
                if gate_check['need_open_channel']:
                    upstream_channel = self._find_reference_segment_same_section_v2(nodes, i, i, i + 1)
                    if upstream_channel is None:
                        upstream_channel = self._find_reference_segment_cross_section_v2(nodes, i, i, i + 1)
                    open_channel_params = None
                    if open_channel_callback:
                        open_channel_params = open_channel_callback(
                            upstream_channel, gate_check['available_length'],
                            current_node.structure_type.value if current_node.structure_type else "",
                            next_node.structure_type.value if next_node.structure_type else "",
                            current_node.flow_section, current_node.flow
                        )
                    elif upstream_channel:
                        open_channel_params = self._build_open_channel_params_from_reference(
                            upstream_channel,
                            current_node.flow_section,
                            current_node.flow,
                        )
                    if open_channel_params:
                        gate_check = self._reflow_connection_layout(gate_check, current_node, next_node, open_channel_params)
                        upstream_channel = params_to_reference(open_channel_params)
                        if not gate_check['need_open_channel']:
                            open_channel_params = None
                    if open_channel_params:
                        oc_slope_i = 1.0 / open_channel_params.slope_inv if open_channel_params.slope_inv > 0 else 0
                        oc = self._create_open_channel_node(open_channel_params, current_node, next_node)
                        oc.stat_length = max(0.0, gate_check['available_length'])
                        if gate_check['need_transition_1']:
                            tr_out = self._create_transition_node(current_node, next_node)
                            tr_out.slope_i = oc_slope_i
                            tr_out.transition_skip_loss = gate_check.get('skip_loss_transition_1', False)
                            self._hydrate_transition_length_state(
                                tr_out,
                                current_node,
                                oc,
                                actual_length=gate_check.get('transition_length_1', 0.0),
                                preserve_existing_length=True,
                            )
                            self._append_effective_transition(new_nodes, tr_out)
                        new_nodes.append(oc)
                    elif gate_check['need_transition_1'] and gate_check['distance'] > 0:
                        merged = self._create_merged_transition_node(
                            current_node, next_node, gate_check['distance'], "出口")
                        merged.transition_skip_loss = gate_check.get('skip_loss_transition_1', False)
                        self._hydrate_transition_length_state(
                            merged,
                            current_node,
                            next_node,
                            actual_length=gate_check['distance'],
                            preserve_existing_length=True,
                        )
                        self._append_effective_transition(new_nodes, merged)
                elif gate_check['need_transition_1'] and gate_check['distance'] > 0:
                    us_ch = (self._find_reference_segment_same_section_v2(nodes, i, i, i + 1)
                             or self._find_reference_segment_cross_section_v2(nodes, i, i, i + 1))
                    merged = self._create_merged_transition_node(
                        current_node, next_node, gate_check['distance'], "出口")
                    merged.transition_skip_loss = gate_check.get('skip_loss_transition_1', False)
                    if us_ch:
                        us_sinv = us_ch.get('slope_inv', 0)
                        merged.slope_i = 1.0 / us_sinv if us_sinv > 0 else 0
                    self._hydrate_transition_length_state(
                        merged,
                        current_node,
                        next_node,
                        actual_length=gate_check['distance'],
                        preserve_existing_length=True,
                    )
                    self._append_effective_transition(new_nodes, merged)
                continue

            # --- 情况3：普通 (非闸, 非闸) 对 ---
            # 用 (current_node, next_node) 进行渐变段/明渠段判断
            check_result = self._should_insert_open_channel(current_node, next_node, nodes)
            
            if check_result['need_open_channel']:
                # 需要插入明渠段（里程差 > 渐变段之和）
                
                # 获取明渠段参数（同流量段优先级匹配）
                upstream_channel = self._find_reference_segment_same_section_v2(nodes, i, i, i + 1)
                if upstream_channel is None:
                    upstream_channel = self._find_reference_segment_cross_section_v2(nodes, i, i, i + 1)
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
                    open_channel_params = self._build_open_channel_params_from_reference(
                        upstream_channel,
                        flow_section,
                        flow,
                    )
                if open_channel_params:
                    check_result = self._reflow_connection_layout(check_result, current_node, next_node, open_channel_params)
                    upstream_channel = params_to_reference(open_channel_params)
                    if not check_result['need_open_channel']:
                        open_channel_params = None
                if open_channel_params:
                    oc_slope_i = 1.0 / open_channel_params.slope_inv if open_channel_params.slope_inv > 0 else 0
                    open_channel = self._create_open_channel_node(open_channel_params, current_node, next_node)
                    open_channel.stat_length = max(0.0, check_result.get('available_length', 0.0))
                    
                    # ===== 普通模式：插入3行（出口渐变段 → 明渠段 → 进口渐变段） =====
                    if check_result['need_transition_1']:
                        transition_out = self._create_transition_node(current_node, next_node)
                        transition_out.slope_i = oc_slope_i
                        transition_out.transition_skip_loss = check_result.get('skip_loss_transition_1', False)
                        self._hydrate_transition_length_state(
                            transition_out,
                            current_node,
                            open_channel,
                            actual_length=check_result.get('transition_length_1', 0.0),
                            preserve_existing_length=True,
                        )
                        self._append_effective_transition(new_nodes, transition_out)
                    new_nodes.append(open_channel)
                    if check_result['need_transition_2']:
                        transition_in = self._create_inlet_transition_node(next_node, current_node)
                        transition_in.slope_i = oc_slope_i
                        transition_in.transition_skip_loss = check_result.get('skip_loss_transition_2', False)
                        self._hydrate_transition_length_state(
                            transition_in,
                            open_channel,
                            next_node,
                            actual_length=check_result.get('transition_length_2', 0.0),
                            preserve_existing_length=True,
                        )
                        self._append_effective_transition(new_nodes, transition_in)
                else:
                    # 明渠段未能插入，回退为1行合并渐变段（避免出现两个连续渐变段）
                    if check_result['need_transition_1'] or check_result['need_transition_2']:
                        if check_result['distance'] > 0:
                            _mt = "进口" if check_result['need_transition_2'] and not check_result['need_transition_1'] else "出口"
                            merged_transition = self._create_merged_transition_node(
                                current_node, next_node, check_result['distance'], _mt
                            )
                            merged_transition.transition_skip_loss = (
                                check_result.get('skip_loss_transition_1', False) or
                                check_result.get('skip_loss_transition_2', False)
                            )
                            if upstream_channel:
                                us_sinv = upstream_channel.get('slope_inv', 0)
                                merged_transition.slope_i = 1.0 / us_sinv if us_sinv > 0 else 0
                            self._hydrate_transition_length_state(
                                merged_transition,
                                current_node,
                                next_node,
                                actual_length=check_result['distance'],
                                preserve_existing_length=True,
                            )
                            self._append_effective_transition(new_nodes, merged_transition)
            
            elif check_result['need_transition_1'] or check_result['need_transition_2']:
                # 不需要明渠段但需要渐变段（里程差 <= 渐变段之和）
                # 只插入１行合并的渐变段
                if check_result['distance'] > 0:
                    _mt = "进口" if check_result['need_transition_2'] and not check_result['need_transition_1'] else "出口"
                    merged_transition = self._create_merged_transition_node(
                        current_node, next_node, check_result['distance'], _mt
                    )
                    # 任一侧为倒虹吸时，合并行标记为跳过损失计算
                    merged_transition.transition_skip_loss = (
                        check_result.get('skip_loss_transition_1', False) or
                        check_result.get('skip_loss_transition_2', False)
                    )
                    # 合并渐变段与普通连接段采用同一套坡降推荐，排除远处急流明渠。
                    us_ch = (self._find_reference_segment_same_section_v2(nodes, i, i, i + 1)
                             or self._find_reference_segment_cross_section_v2(nodes, i, i, i + 1))
                    if us_ch:
                        us_sinv = us_ch.get('slope_inv', 0)
                        merged_transition.slope_i = 1.0 / us_sinv if us_sinv > 0 else 0
                    self._hydrate_transition_length_state(
                        merged_transition,
                        current_node,
                        next_node,
                        actual_length=check_result['distance'],
                        preserve_existing_length=True,
                    )
                    self._append_effective_transition(new_nodes, merged_transition)
            
            elif self._needs_transition(current_node, next_node):
                # 普通渐变段（非建筑物出口→进口的情况，包括明渠→明渠）
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
                # 有压流建筑物（倒虹吸/有压管道）相邻渐变段为占位行，跳过损失计算
                if self.is_pressurized_flow_structure(current_node) or self.is_pressurized_flow_structure(next_node):
                    transition_node.transition_skip_loss = True
                # 普通单侧渐变段同样受真实节点间距约束，不能超长后再靠统计缩放。
                available_distance = next_node.station_MC - current_node.station_MC
                self._hydrate_transition_length_state(
                    transition_node,
                    current_node,
                    next_node,
                    physical_limit=max(0.0, available_distance),
                )
                self._append_effective_transition(new_nodes, transition_node)
        
        # 闸穿透：刷新残留的延迟节点（闸在节点列表末尾的情况）
        if deferred_nodes:
            new_nodes.extend(deferred_nodes)
        
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
                    # 统一走 calculate_transition_loss()，由底层兼容处理
                    # skip_loss、已有长度复用、以及详情补建逻辑。
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

            reserve_loss = float(getattr(node, 'head_loss_reserve', 0.0) or 0.0)
            gate_loss = float(getattr(node, 'head_loss_gate', 0.0) or 0.0)
            spillway_loss = get_spillway_steep_chute_total_loss(node)
            if spillway_loss is not None:
                node.head_loss_total = spillway_loss
                continue

            row_override_display_loss = self._rebuild_pressure_pipe_row_override_total_loss(node)
            if row_override_display_loss is not None:
                node.head_loss_total = row_override_display_loss + reserve_loss + gate_loss
                continue
            
            # 获取各项损失
            h_bend = node.head_loss_bend or 0.0
            h_friction = node.head_loss_friction or 0.0
            h_local = node.head_loss_local or 0.0
            h_reserve = reserve_loss
            h_gate = gate_loss
            h_siphon = self.hyd_calc._resolve_pressure_pipe_formula_term_loss(node)
            
            # 重新计算总水头损失
            # 注：渐变段损失单独显示在渐变段行，不计入节点的总水头损失
            node.head_loss_total = h_bend + h_friction + h_local + h_reserve + h_gate + h_siphon

    def _rebuild_pressure_pipe_row_override_total_loss(self, node: ChannelNode) -> Optional[float]:
        """把逐行承压覆盖同步回正式损失字段，供静默重算复用。"""
        window_override = self.hyd_calc._get_pressure_pipe_window_override(node)
        if not window_override:
            return None
        group_mode = str(window_override.get("group_mode", "") or "").strip()
        if not self.hyd_calc._is_pressure_pipe_row_override_mode(group_mode):
            return None

        friction_loss = float(window_override.get("friction_loss", 0.0) or 0.0)
        bend_loss = float(window_override.get("total_bend_loss", 0.0) or 0.0)
        local_loss = float(window_override.get("local_loss", 0.0) or 0.0)
        if local_loss <= ZERO_TOLERANCE:
            local_loss = (
                float(window_override.get("inlet_transition_loss", 0.0) or 0.0)
                + float(window_override.get("outlet_transition_loss", 0.0) or 0.0)
            )

        node.head_loss_friction = friction_loss
        node.head_loss_bend = bend_loss
        node.head_loss_local = local_loss
        node.head_loss_siphon = 0.0
        node.external_head_loss = None

        display_loss = float(window_override.get("total_head_loss", 0.0) or 0.0)
        if display_loss <= ZERO_TOLERANCE:
            display_loss = max(friction_loss + bend_loss + local_loss, 0.0)
        setattr(node, "_pressure_pipe_display_loss", display_loss)
        return display_loss

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
            
            # 当前节点是闸 → 跳过（闸为点状结构，无需渐变段损失）
            if self._is_diversion_gate_type(curr_node.structure_type):
                continue
            # 下一节点是闸 → 跳过（闸侧渐变段损失已由 identify_and_insert_transitions 处理）
            if self._is_diversion_gate_type(next_node.structure_type):
                continue
            
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
        
        missing_required_name_rows = []

        # 验证每个节点
        for i, node in enumerate(nodes):
            # 跳过渐变段和自动插入的连接段（这些行由系统自动生成，无需用户填写结构形式）
            if getattr(node, 'is_transition', False) or getattr(node, 'is_auto_inserted_channel', False):
                continue
            if node.structure_type is None:
                errors.append(f"第{i+1}行: 请选择结构形式")
                continue
            if not str(getattr(node, "name", "") or "").strip() and not StructureType.allows_empty_name(node.structure_type):
                missing_required_name_rows.append((i + 1, node.get_structure_type_str() or "当前结构"))

        if missing_required_name_rows:
            errors.append(
                "建筑物名称规则：明渠可留空；暗涵建议填写但可留空；"
                "倒虹吸、隧洞、渡槽等仍需填写。"
            )
            for row_index, struct_name in missing_required_name_rows:
                errors.append(f"第{row_index}行: {struct_name} 需要填写建筑物名称")
        
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
        """按真实边界生成长度明细；辅助节点落位不代表区段起止位置。"""
        return build_length_records(nodes, self._get_effective_structure_type_value)

    @staticmethod
    def calculate_type_summary(building_lengths: List[Dict]) -> List[Dict]:
        """从完整明细统一汇总，包含渐变段、连接段及零长度点状建筑物。"""
        return summarize_length_records(building_lengths)

    @staticmethod
    def calculate_comprehensive_type_summary(nodes: List['ChannelNode']) -> List[Dict]:
        """类型汇总与建筑物明细使用同一份区段划分。"""
        records = build_length_records(nodes, WaterProfileCalculator._get_effective_structure_type_value)
        return summarize_length_records(records)

    @staticmethod
    def validate_type_summary_total(nodes: List['ChannelNode'],
                                    type_summary: Optional[List[Dict]] = None,
                                    tolerance: float = 0.001) -> Dict[str, Any]:
        """验证总长、逐项边界和类型归属；各类分错但总长相同也不能通过。"""
        try:
            records = build_length_records(nodes, WaterProfileCalculator._get_effective_structure_type_value)
            return validate_length_records(nodes, records, type_summary, tolerance)
        except ValueError as exc:
            return {'ok': 0.0, 'channel_total': 0.0, 'summary_total': 0.0,
                    'diff': 0.0, 'errors': [str(exc)]}

    _CULVERT_FAMILY_TYPE_KEY = "culvert_family_type"
    _RECT_CULVERT_FAMILY_TEXT = "暗涵-矩形"
    _ARCH_CULVERT_FAMILY_TEXT = "暗涵-圆拱直墙型"
