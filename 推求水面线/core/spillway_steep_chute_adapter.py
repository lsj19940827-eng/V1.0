# -*- coding: utf-8 -*-
"""泄水渠与陡坡表3成组节点与专项内核之间的适配层。"""

from __future__ import annotations

import copy
import importlib
import math
import os
import sys
from typing import Any, Dict, List, Optional

if __package__ and __package__.startswith("推求水面线."):
    from ..models.data_models import ChannelNode
    from ..models.enums import InOutType
else:
    from models.data_models import ChannelNode
    from models.enums import InOutType


SPILLWAY_STEEP_CHUTE_TEXT = "泄水渠与陡坡"
SPILLWAY_STEEP_CHUTE_PARAM_KEY = "spillway_steep_chute"
_GROUP_KEY_ATTR = "_spillway_steep_chute_group_key"
_ROLE_ATTR = "_spillway_steep_chute_role"
_GROUP_INDEXES_ATTR = "_spillway_steep_chute_group_indexes"
SPILLWAY_STEEP_CHUTE_ADVANCED_DEFAULTS = {
    "inlet_connection_type_label": "扭曲面连接",
    "contraction_coefficient": 1.0,
    "alpha_profile": 1.1,
    "aeration_coefficient": 1.2,
    "sidewall_freeboard_m": 0.4,
    "pool_depth_factor": 1.10,
    "outlet_rectification_factor": 10.0,
}
SPILLWAY_STEEP_CHUTE_ADVANCED_LABELS = {
    "inlet_weir_width": "泄水渠入口宽度(m)",
    "inlet_head": "泄水渠堰上总水头(m)",
    "inlet_connection_type_label": "泄水渠入口连接形式",
    "weir_coefficient": "泄水渠手动流量系数",
    "contraction_coefficient": "泄水渠侧收缩系数",
    "alpha_profile": "泄水渠动能修正系数",
    "aeration_coefficient": "泄水渠掺气系数",
    "sidewall_freeboard_m": "泄水渠侧墙安全超高(m)",
    "pool_depth_factor": "泄水渠池深系数",
    "outlet_rectification_factor": "泄水渠整流长度系数",
    "manual_start_depth": "泄水渠实际起点水深(m)",
    "downstream_tailwater_depth": "泄水渠末端尾水深(m)",
    "Q_increased": "泄水渠加大流量(m³/s)",
    "increased_flow_start_depth": "泄水渠加大工况实际入口水深(m)",
}
SPILLWAY_STEEP_CHUTE_ADVANCED_KEYS = tuple(SPILLWAY_STEEP_CHUTE_ADVANCED_LABELS.keys())
SPILLWAY_STEEP_CHUTE_ADVANCED_NUMERIC_KEYS = {
    key for key in SPILLWAY_STEEP_CHUTE_ADVANCED_KEYS
    if key != "inlet_connection_type_label"
}

_ALIASES = {
    SPILLWAY_STEEP_CHUTE_TEXT,
    "充水渠",
    "泄水渠",
    "陡坡",
    "泄槽",
    "陡槽",
    "泄水渠及陡坡",
}


def normalize_spillway_steep_chute_text(value: Any) -> str:
    """统一泄水渠与陡坡结构名称。"""
    text = str(value or "").strip()
    return SPILLWAY_STEEP_CHUTE_TEXT if text in _ALIASES else text


def is_spillway_steep_chute_value(value: Any) -> bool:
    """判断结构形式文本是否为泄水渠与陡坡。"""
    if hasattr(value, "value"):
        value = value.value
    return normalize_spillway_steep_chute_text(value) == SPILLWAY_STEEP_CHUTE_TEXT


def is_spillway_steep_chute_node(node: Optional[ChannelNode]) -> bool:
    """判断节点是否为泄水渠与陡坡。"""
    if node is None or getattr(node, "is_transition", False):
        return False
    structure_type = getattr(node, "structure_type", None)
    return is_spillway_steep_chute_value(structure_type)


def is_spillway_steep_chute_inlet(node: Optional[ChannelNode]) -> bool:
    """判断节点是否为泄水渠与陡坡进口行。"""
    if not is_spillway_steep_chute_node(node):
        return False
    return _node_role(node) == "inlet"


def is_spillway_steep_chute_outlet(node: Optional[ChannelNode]) -> bool:
    """判断节点是否为泄水渠与陡坡出口行。"""
    if not is_spillway_steep_chute_node(node):
        return False
    return _node_role(node) == "outlet"


def _node_role(node: Optional[ChannelNode]) -> str:
    """读取专项链内部角色，不复用表3进出口显示字段。"""
    if node is None:
        return ""
    role = str(getattr(node, _ROLE_ATTR, "") or "").strip()
    if role:
        return role
    payload = (getattr(node, "section_params", {}) or {}).get(SPILLWAY_STEEP_CHUTE_PARAM_KEY, {}) or {}
    return str(payload.get("role", "") or "").strip()


def _coerce_float(value: Any, default: float = 0.0) -> float:
    """把值转成浮点数，失败时返回默认值。"""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _node_station(node: ChannelNode) -> float:
    """读取节点里程。"""
    return _coerce_float(getattr(node, "station_MC", 0.0), 0.0)


def _node_name(node: ChannelNode) -> str:
    """读取建筑物名称。"""
    name = str(getattr(node, "name", "") or "").strip()
    # 批量表常用 “-” 表示该专项不填建筑物名称，后续展示按空名称处理。
    return "" if name == "-" else name


def _is_real_node(node: ChannelNode) -> bool:
    """判断是否为真实表3节点。"""
    return not getattr(node, "is_transition", False) and not getattr(node, "is_auto_inserted_channel", False)


def _compute_group_length(inlet: ChannelNode, outlet: ChannelNode) -> tuple[float, str]:
    """按里程优先、坐标兜底计算成组长度。"""
    length_by_station = _node_station(outlet) - _node_station(inlet)
    if length_by_station > 1e-9:
        return length_by_station, "station"

    dx = _coerce_float(getattr(outlet, "x", 0.0), 0.0) - _coerce_float(getattr(inlet, "x", 0.0), 0.0)
    dy = _coerce_float(getattr(outlet, "y", 0.0), 0.0) - _coerce_float(getattr(inlet, "y", 0.0), 0.0)
    length_by_coord = math.hypot(dx, dy)
    if length_by_coord > 1e-9:
        return length_by_coord, "coordinate"
    return 0.0, ""


def _node_slope_inv_for_grouping(node: ChannelNode) -> float:
    """读取节点底坡倒数。"""
    slope_i = _coerce_float(getattr(node, "slope_i", 0.0), 0.0)
    if slope_i > 0:
        return 1.0 / slope_i
    params = getattr(node, "section_params", {}) or {}
    for key in ("slope_inv", "slope_inverse", "底坡倒数"):
        value = _coerce_float(params.get(key), 0.0)
        if value > 0:
            return value
    for key in ("i", "slope", "slope_i", "底坡"):
        value = _coerce_float(params.get(key), 0.0)
        if value > 0:
            return 1.0 / value
    return 0.0


def _same_slope_inv(left: float, right: float) -> bool:
    """判断两个底坡倒数是否可视为相同。"""
    return math.isclose(float(left or 0.0), float(right or 0.0), rel_tol=1e-9, abs_tol=1e-9)


def _node_flow_section(node: ChannelNode) -> str:
    """读取节点所属流量段。"""
    return str(getattr(node, "flow_section", "") or "").strip()


def _new_group(key: str, first_index: int, node: ChannelNode, chain_number: int) -> Dict[str, Any]:
    """创建连续专项链记录。"""
    name = _node_name(node)
    display_name = name if name and name != "-" else f"第{first_index + 1}行专项链"
    return {
        "key": key,
        "name": name,
        "display_name": display_name,
        "chain_number": chain_number,
        "structure_type": SPILLWAY_STEEP_CHUTE_TEXT,
        "flow_section": _node_flow_section(node),
        "indexes": [],
        "nodes": [],
    }


def _append_group_node(group: Dict[str, Any], index: int, node: ChannelNode) -> None:
    """向成组记录追加节点。"""
    group["indexes"].append(index)
    group["nodes"].append(node)


def _should_continue_chain(group: Optional[Dict[str, Any]], index: int, node: ChannelNode) -> bool:
    """判断当前节点是否可接续上一条专项链。"""
    if group is None:
        return False
    if index != int(group["indexes"][-1]) + 1:
        return False
    return _node_flow_section(node) == str(group.get("flow_section", ""))


def _collect_groups(nodes: List[ChannelNode]) -> Dict[str, Dict[str, Any]]:
    """从节点列表收集连续泄水渠与陡坡专项链。"""
    groups: Dict[str, Dict[str, Any]] = {}
    current_group: Optional[Dict[str, Any]] = None
    chain_count = 0

    for index, node in enumerate(nodes):
        if not _is_real_node(node) or not is_spillway_steep_chute_node(node):
            current_group = None
            continue

        if not _should_continue_chain(current_group, index, node):
            chain_count += 1
            key = f"{SPILLWAY_STEEP_CHUTE_TEXT}:chain:{chain_count}:row{index + 1}"
            current_group = _new_group(key, index, node, chain_count)
            groups[key] = current_group
        _append_group_node(current_group, index, node)
    return groups


def get_spillway_steep_chute_chain_indexes(nodes: List[ChannelNode], index: int) -> List[int]:
    """供界面复用连续专项链边界，允许参数尚未填写完整。"""
    for group in _collect_groups(nodes).values():
        if index in group["indexes"]:
            return list(group["indexes"])
    return []


def resolve_spillway_steep_chute_chain_advanced_params(nodes: List[ChannelNode], index: int) -> Dict[str, Any]:
    """读取当前连续链显式参数，与内核共用冲突及清空规则。"""
    for group in _collect_groups(nodes).values():
        if index in group["indexes"]:
            return _existing_advanced_params(group)
    return {}


def invalidate_spillway_steep_chute_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """参数变化或重算时撤销旧结果，保留用户参数和导入工况。"""
    clean = copy.deepcopy(payload or {})
    output_keys = (
        "input", "inputs", "result", "profile_points", "display_point", "risks",
        "head_loss_total", "chain_head_loss_total", "segment_head_loss_m",
        "chain_inlet_water_level_m", "chain_outlet_water_level_m",
        "inlet_water_level_m", "outlet_water_level_m", "chain_water_level_drop_m",
        "segment_water_level_drop_m", "inlet_interface", "calculation_error",
    )
    # 兼容仅将参数存在 input 的旧工程；连续子段生成的起点深不能迁作首段输入。
    if "advanced_params" not in clean:
        legacy = clean.get("inputs", clean.get("input", {}))
        clean["advanced_params"] = {key: copy.deepcopy(value) for key, value in legacy.items()
                                    if key in SPILLWAY_STEEP_CHUTE_ADVANCED_KEYS} if isinstance(legacy, dict) else {}
        if clean.get("result") and int(clean.get("segment_index", 1)) > 1:
            clean["advanced_params"].pop("manual_start_depth", None)
    for key in output_keys:
        clean.pop(key, None)
    clean.update(success=False, params_dirty=True)
    return clean


def _invalidate_chain_nodes(nodes: List[ChannelNode]) -> None:
    """整链一旦已有显式参数容器，其余节点不得从历史结果恢复被清空字段。"""
    authoritative = any("advanced_params" in node.section_params.get(SPILLWAY_STEEP_CHUTE_PARAM_KEY, {}) for node in nodes)
    for node in nodes:
        payload = dict(node.section_params.get(SPILLWAY_STEEP_CHUTE_PARAM_KEY, {}))
        if authoritative:
            payload.setdefault("advanced_params", {})
        node.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY] = invalidate_spillway_steep_chute_payload(payload)


def _clear_failed_chain(nodes: List[ChannelNode], message: str) -> None:
    """校验或求解失败时一并撤销对象中的旧数值，避免表格继续引用。"""
    for node in nodes:
        payload = invalidate_spillway_steep_chute_payload(node.section_params.get(SPILLWAY_STEEP_CHUTE_PARAM_KEY, {}))
        payload["calculation_error"] = message
        node.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY] = payload
        if "auto_structure_height_m" in payload:
            node.structure_height = float(payload.get("supplied_structure_height_m", 0.0))
        node.water_level = node.bottom_elevation = node.top_elevation = 0.0
        node.velocity = node.water_depth = node.head_loss_total = node.head_loss_cumulative = 0.0


def _chain_display_name(group: Dict[str, Any]) -> str:
    """生成错误提示使用的专项链名称。"""
    return str(group.get("display_name") or group.get("name") or "专项链").strip()


def _segment_distance(inlet: ChannelNode, node: ChannelNode, length_source: str) -> float:
    """计算节点在当前子段中的沿程距离。"""
    if length_source == "station":
        return _node_station(node) - _node_station(inlet)
    dx = _coerce_float(getattr(node, "x", 0.0), 0.0) - _coerce_float(getattr(inlet, "x", 0.0), 0.0)
    dy = _coerce_float(getattr(node, "y", 0.0), 0.0) - _coerce_float(getattr(inlet, "y", 0.0), 0.0)
    return math.hypot(dx, dy)


def _subsegment_summary(segment: Dict[str, Any]) -> Dict[str, Any]:
    """生成可存入节点载荷的子段摘要。"""
    return {
        "key": segment.get("key", ""),
        "segment_index": int(segment.get("segment_index", 0)),
        "first_index": int(segment.get("first_index", 0)),
        "last_index": int(segment.get("last_index", 0)),
        "length_m": _coerce_float(segment.get("length", 0.0), 0.0),
        "length_source": segment.get("length_source", ""),
        "slope_i": _coerce_float(segment.get("slope_i", 0.0), 0.0),
        "slope_inv": _coerce_float(segment.get("slope_inv", 0.0), 0.0),
        "roughness": _coerce_float(segment.get("roughness", 0.0), 0.0),
        "node_count": len(segment.get("nodes", []) or []),
        "indexes": list(segment.get("indexes", []) or []),
    }


def _build_chain_subsegments(group: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按上游节点底坡和糙率拆段，沿程距离统一使用递增里程或累计折线。"""
    nodes = group.get("nodes", []) or []
    indexes = group.get("indexes", []) or []
    if len(nodes) < 2:
        display_name = _chain_display_name(group)
        raise ValueError(f"泄水渠与陡坡「{display_name}」缺少相邻下游节点，无法按专项水面线计算。")

    stations = [_node_station(node) for node in nodes]
    use_station = any(abs(value) > 1e-9 for value in stations)
    edge_lengths = []
    for left, right in zip(nodes, nodes[1:]):
        if use_station:
            distance = _node_station(right) - _node_station(left)
            if distance <= 1e-9:
                raise ValueError(f"泄水渠与陡坡「{_chain_display_name(group)}」里程必须沿水流方向逐点递增，请检查重复、倒序或缺失里程。")
        else:
            distance = math.hypot(float(right.x) - float(left.x), float(right.y) - float(left.y))
            if not math.isfinite(distance) or distance <= 1e-9:
                raise ValueError(f"泄水渠与陡坡「{_chain_display_name(group)}」长度无效，请补齐相邻 IP 的里程或坐标。")
        edge_lengths.append(distance)
    length_source = "station" if use_station else "coordinate"
    subsegments: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for edge_offset in range(len(nodes) - 1):
        inlet = nodes[edge_offset]
        outlet = nodes[edge_offset + 1]
        inlet_index = indexes[edge_offset]
        outlet_index = indexes[edge_offset + 1]
        slope_inv = _node_slope_inv_for_grouping(inlet)
        slope_i = 1.0 / slope_inv if slope_inv > 0 else 0.0
        roughness = _resolve_group_param({"nodes": [inlet]}, ("n", "roughness", "manning_n", "糙率"), attr_name="roughness")
        if roughness <= 0:
            raise ValueError(f"泄水渠与陡坡第{inlet_index + 1}行糙率必须大于 0。")
        if slope_i <= 0 or slope_inv <= 0:
            display_name = _chain_display_name(group)
            raise ValueError(f"泄水渠与陡坡「{display_name}」参数不完整：底坡倒数必须大于 0。")

        edge_length = edge_lengths[edge_offset]
        if (current is not None and _same_slope_inv(current.get("slope_inv", 0.0), slope_inv)
                and math.isclose(current["roughness"], roughness, rel_tol=1e-9, abs_tol=1e-12)):
            current["outlet"] = outlet
            current["last_index"] = outlet_index
            current["indexes"].append(outlet_index)
            current["nodes"].append(outlet)
            current["length"] += edge_length
            current["node_distances"].append(current["length"])
            continue

        segment_index = len(subsegments) + 1
        current = {
            "key": f"{group.get('key', '')}:segment:{segment_index}",
            "chain_key": group.get("key", ""),
            "segment_index": segment_index,
            "name": group.get("name", ""),
            "display_name": _chain_display_name(group),
            "structure_type": SPILLWAY_STEEP_CHUTE_TEXT,
            "flow_section": group.get("flow_section", ""),
            "indexes": [inlet_index, outlet_index],
            "nodes": [inlet, outlet],
            "inlet": inlet,
            "outlet": outlet,
            "first_index": inlet_index,
            "last_index": outlet_index,
            "slope_i": slope_i,
            "slope_inv": slope_inv,
            "roughness": roughness,
            "length": edge_length,
            "length_source": length_source,
            "node_distances": [0.0, edge_length],
            "advanced_nodes": nodes,
        }
        subsegments.append(current)

    return subsegments


def _complete_chain_group(group: Dict[str, Any]) -> Dict[str, Any]:
    """补齐专项链的长度、首尾和子段信息。"""
    nodes = group.get("nodes", []) or []
    indexes = group.get("indexes", []) or []
    _validate_prismatic_chain(group)
    subsegments = _build_chain_subsegments(group)
    length = sum(segment["length"] for segment in subsegments)
    length_source = subsegments[0]["length_source"]
    group.update(
        {
            "inlet": nodes[0],
            "outlet": nodes[-1],
            "length": length,
            "length_source": length_source,
            "first_index": indexes[0],
            "last_index": indexes[-1],
            "subsegments": subsegments,
            "chain_subsegments": [_subsegment_summary(segment) for segment in subsegments],
        }
    )
    return group


def prepare_spillway_steep_chute_groups(nodes: List[ChannelNode]) -> Dict[str, Dict[str, Any]]:
    """校验并标记表3中的连续泄水渠与陡坡专项链。"""
    groups = _collect_groups(nodes)
    for key, group in groups.items():
        _invalidate_chain_nodes(group["nodes"])
        try:
            _complete_chain_group(group)
        except Exception as exc:
            _clear_failed_chain(group["nodes"], str(exc))
            raise
        group_nodes: List[ChannelNode] = group["nodes"]
        summaries = copy.deepcopy(group.get("chain_subsegments", []))

        for offset, node in enumerate(group_nodes):
            role = "inlet" if offset == 0 else "outlet" if offset == len(group_nodes) - 1 else "middle"
            if str(getattr(node, "name", "") or "").strip() == "-":
                node.name = ""
            # 专项内部用 role 记录首尾，不占用表3“进/出”显示口径。
            node.in_out = InOutType.NORMAL
            setattr(node, _GROUP_KEY_ATTR, key)
            setattr(node, _ROLE_ATTR, role)
            setattr(node, _GROUP_INDEXES_ATTR, tuple(group["indexes"]))
            payload = invalidate_spillway_steep_chute_payload(getattr(node, "section_params", {}).get(SPILLWAY_STEEP_CHUTE_PARAM_KEY, {}) or {})
            payload.update(
                {
                    "group_key": key,
                    "chain_key": key,
                    "role": role,
                    "prepared": True,
                    "group_length_m": group.get("length", 0.0),
                    "chain_length_m": group.get("length", 0.0),
                    "length_source": group.get("length_source", ""),
                    "chain_segment_count": len(group.get("subsegments", []) or []),
                    "chain_subsegments": summaries,
                }
            )
            node.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY] = payload
    return groups


def find_spillway_steep_chute_group(nodes: List[ChannelNode], index: int) -> Optional[Dict[str, Any]]:
    """按当前节点索引查找泄水渠与陡坡连续专项链。"""
    if index < 0 or index >= len(nodes):
        return None
    target = nodes[index]
    if not is_spillway_steep_chute_node(target):
        return None
    groups = _collect_groups(nodes)
    target_key = getattr(target, _GROUP_KEY_ATTR, "")
    if target_key and target_key in groups and index in groups[target_key]["indexes"]:
        return _complete_chain_group(groups[target_key])
    for group in groups.values():
        if index in group.get("indexes", []):
            return _complete_chain_group(group)
    return None


def _first_param(node: ChannelNode, keys: tuple[str, ...], default: float = 0.0) -> float:
    """按候选键读取断面参数。"""
    params = getattr(node, "section_params", {}) or {}
    for key in keys:
        if key in params and params.get(key) not in (None, ""):
            return _coerce_float(params.get(key), default)
    return default


def _resolve_group_param(group: Dict[str, Any], keys: tuple[str, ...], attr_name: str = "", default: float = 0.0) -> float:
    """从组内节点按进口优先、出口兜底读取参数。"""
    for node in group.get("nodes", []) or []:
        value = _first_param(node, keys, default)
        if value > 0 or (default == 0.0 and value != 0.0):
            return value
        if attr_name:
            attr_value = _coerce_float(getattr(node, attr_name, 0.0), 0.0)
            if attr_value > 0:
                return attr_value
    return default


def _resolve_flow(group: Dict[str, Any]) -> float:
    """读取泄水渠与陡坡设计流量。"""
    for node in group.get("nodes", []) or []:
        flow = _coerce_float(getattr(node, "flow", 0.0), 0.0)
        if flow > 0:
            return flow
        design_flow = _coerce_float(getattr(node, "design_flow", 0.0), 0.0)
        if design_flow > 0:
            return design_flow
        param_flow = _first_param(node, ("Q", "flow", "design_flow", "设计流量"), 0.0)
        if param_flow > 0:
            return param_flow
    return 0.0


def _validate_prismatic_chain(group: Dict[str, Any]) -> None:
    """连续变坡只适用于同流量、同断面渠槽，阻止把渐变段静默当作等断面。"""
    nodes = group.get("nodes", []) or []
    comparisons = (
        ("底宽", ("B", "b", "bottom_width", "底宽")),
        ("边坡系数", ("m", "side_slope", "slope_coefficient", "边坡系数", "边坡")),
    )
    for label, keys in comparisons:
        values = []
        for node in nodes:
            params = getattr(node, "section_params", {}) or {}
            if any(key in params and params[key] not in (None, "") for key in keys):
                values.append(_first_param(node, keys))
        if values and any(not math.isclose(value, values[0], rel_tol=1e-9, abs_tol=1e-9) for value in values[1:]):
            raise ValueError(f"泄水渠与陡坡「{_chain_display_name(group)}」的{label}沿程变化；当前连续变坡计算仅支持同一断面，变断面须另算过渡段及局部损失。")
    flows = [_resolve_flow({"nodes": [node]}) for node in nodes]
    flows = [value for value in flows if value > 0]
    if flows and any(not math.isclose(value, flows[0], rel_tol=1e-9, abs_tol=1e-9) for value in flows[1:]):
        raise ValueError(f"泄水渠与陡坡「{_chain_display_name(group)}」沿程流量不一致，当前连续变坡计算未包含分流或汇流。")


def _resolve_slope(group: Dict[str, Any]) -> tuple[float, float]:
    """读取底坡和底坡倒数。"""
    slope_i = _coerce_float(group.get("slope_i", 0.0), 0.0)
    slope_inv = _coerce_float(group.get("slope_inv", 0.0), 0.0)
    if slope_i > 0:
        return slope_i, 1.0 / slope_i
    if slope_inv > 0:
        return 1.0 / slope_inv, slope_inv
    for node in group.get("nodes", []) or []:
        slope_i = _coerce_float(getattr(node, "slope_i", 0.0), 0.0)
        if slope_i > 0:
            return slope_i, 1.0 / slope_i
        slope_i = _first_param(node, ("i", "slope", "slope_i", "底坡"), 0.0)
        if slope_i > 0:
            return slope_i, 1.0 / slope_i
        slope_inv = _first_param(node, ("slope_inv", "slope_inverse", "底坡倒数"), 0.0)
        if slope_inv > 0:
            return 1.0 / slope_inv, slope_inv
    return 0.0, 0.0


def _normalize_advanced_value(key: str, value: Any) -> tuple[Any, Any]:
    """把专项参数转成可比较、可传给内核的值。"""
    if value is None:
        return None, None
    if isinstance(value, str) and not value.strip():
        return None, None
    if key in SPILLWAY_STEEP_CHUTE_ADVANCED_NUMERIC_KEYS:
        number = _coerce_float(value, float("nan"))
        if not math.isfinite(number):
            return str(value).strip(), str(value).strip()
        return round(number, 10), number
    text = str(value).strip()
    if not text:
        return None, None
    return text, text


def _advanced_values_from_payload(payload: Dict[str, Any], container_key: str, key: str) -> Optional[Any]:
    """从指定容器读取一个专项参数值。"""
    value = payload.get(container_key)
    if isinstance(value, dict) and key in value:
        return value.get(key)
    return None


def _collect_advanced_values_for_key(group: Dict[str, Any], key: str, container_key: str) -> List[tuple[ChannelNode, Any, Any]]:
    """按组内节点收集某个专项参数，保留节点顺序用于进口优先取值。"""
    values: List[tuple[ChannelNode, Any, Any]] = []
    for node in group.get("advanced_nodes", None) or group.get("nodes", []) or []:
        payload = (getattr(node, "section_params", {}) or {}).get(SPILLWAY_STEEP_CHUTE_PARAM_KEY, {}) or {}
        if not isinstance(payload, dict):
            continue
        if (container_key in ("input", "inputs") and key == "manual_start_depth"
                and payload.get("result") and int(payload.get("segment_index", 1)) > 1):
            continue
        raw_value = _advanced_values_from_payload(payload, container_key, key)
        normalized, value = _normalize_advanced_value(key, raw_value)
        if normalized is None:
            continue
        values.append((node, normalized, value))
    return values


def _resolve_advanced_value(group: Dict[str, Any], key: str) -> tuple[bool, Any]:
    """解析同名组内的一个专项参数，发现冲突时直接阻止计算。"""
    values: List[tuple[ChannelNode, Any, Any]] = []
    source_nodes = group.get("advanced_nodes") or group.get("nodes", [])
    authoritative = any("advanced_params" in (getattr(node, "section_params", {}) or {}).get(SPILLWAY_STEEP_CHUTE_PARAM_KEY, {})
                        for node in source_nodes)
    for container_key in (("advanced_params",) if authoritative else ("inputs", "input")):
        values = _collect_advanced_values_for_key(group, key, container_key)
        if values:
            break
    if not values:
        return False, None

    distinct = {item[1] for item in values}
    if len(distinct) > 1:
        label = SPILLWAY_STEEP_CHUTE_ADVANCED_LABELS.get(key, key)
        name = group.get("name", "")
        raise ValueError(f"泄水渠与陡坡「{name}」专项参数冲突：{label} 在同组多行填写不一致。")

    inlet = group.get("inlet")
    for node, _normalized, value in values:
        if node is inlet:
            return True, value
    return True, values[0][2]


def _existing_advanced_params(group: Dict[str, Any]) -> Dict[str, Any]:
    """读取用户在 Excel 或详情入口保存的专项参数，并校验同组冲突。"""
    advanced: Dict[str, Any] = {}
    for key in SPILLWAY_STEEP_CHUTE_ADVANCED_KEYS:
        has_value, value = _resolve_advanced_value(group, key)
        if has_value:
            advanced[key] = value
    return advanced


def build_spillway_steep_chute_input(
    group: Dict[str, Any], inlet_water_level: float, inlet_state: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """把表3成组节点转换为专项内核输入。"""
    length = _coerce_float(group.get("length", 0.0), 0.0)
    Q = _resolve_flow(group)
    b = _resolve_group_param(group, ("B", "b", "bottom_width", "底宽"), default=0.0)
    m = _resolve_group_param(group, ("m", "side_slope", "slope_coefficient", "边坡系数", "边坡"), default=0.0)
    n = group.get("roughness") or _resolve_group_param(group, ("n", "roughness", "manning_n", "糙率"), attr_name="roughness", default=0.0)
    slope_i, slope_inv = _resolve_slope(group)

    errors: List[str] = []
    if Q <= 0:
        errors.append("设计流量 Q 必须大于 0")
    if b <= 0:
        errors.append("底宽 B 必须大于 0")
    if m < 0:
        errors.append("边坡系数 m 不能小于 0")
    if n <= 0:
        errors.append("糙率 n 必须大于 0")
    if slope_i <= 0:
        errors.append("底坡倒数必须大于 0")
    if length <= 0:
        errors.append("进出口长度必须大于 0")
    if not math.isfinite(float(inlet_water_level)):
        errors.append("入口水位必须为有限高程值")
    if errors:
        raise ValueError(f"泄水渠与陡坡「{group.get('name', '')}」参数不完整：{'；'.join(errors)}。")

    payload = dict(SPILLWAY_STEEP_CHUTE_ADVANCED_DEFAULTS)
    payload.update(_existing_advanced_params(group))
    runtimes = [node.section_params.get(SPILLWAY_STEEP_CHUTE_PARAM_KEY, {})
                for node in group.get("advanced_nodes") or group.get("nodes", [])]
    flags = {runtime["use_increase"] for runtime in runtimes if isinstance(runtime.get("use_increase"), bool)}
    if len(flags) > 1:
        raise ValueError("同一泄水渠连续链的加大流量开关不一致，请统一当前流量段工况。")
    if flags == {False}:
        payload.pop("Q_increased", None)
    if flags != {False} and "Q_increased" not in payload:
        for runtime in runtimes:
            if runtime.get("use_increase") is False:
                continue
            increased = _coerce_float(runtime.get("Q_increased"), 0.0)
            if increased > Q:
                payload["Q_increased"] = increased
                break
    if "Q_increased" in payload and float(payload["Q_increased"]) < Q:
        raise ValueError("泄水渠加大流量不能小于设计流量。")
    payload.update(
        {
            "structure_name": group.get("name") or SPILLWAY_STEEP_CHUTE_TEXT,
            "section_type": "矩形" if abs(m) <= 1e-12 else "梯形",
            "Q": Q,
            "b": b,
            "B": b,
            "m": m,
            "n": n,
            "i": slope_i,
            "slope_inv": slope_inv,
            "L": length,
            "length": length,
            "profile_mode": "END_DEPTH_BY_LENGTH",
            "start_station": _node_station(group["inlet"]),
            "start_water_level": inlet_water_level,
        }
    )
    chain_nodes = group.get("advanced_nodes") or group.get("nodes", [])
    if chain_nodes and group.get("outlet") is not chain_nodes[-1]:
        # 尾水只控制整条链末端，不能在变坡交界虚构消力池。
        payload.pop("downstream_tailwater_depth", None)
    if int(group.get("segment_index", 1)) > 1:
        for key in ("inlet_weir_width", "inlet_head", "weir_coefficient"):
            payload.pop(key, None)
    if inlet_state is not None:
        # 变坡衔接处继承上一段实际水深和渠底，不再重复形成临界控制。
        payload.update({
            "control_depth_mode": "manual",
            "manual_start_depth": _point_float(inlet_state, "depth_m", "depth", "水深_m"),
            "start_bed_elevation": _point_float(inlet_state, "bed_elevation_m", "bed_elevation", "渠底高程_m"),
        })
    return payload


def compute_spillway_inlet_state(nodes: List[ChannelNode], index: int) -> Dict[str, float]:
    """确定专项入口控制断面，供主流程按能量方程衔接上游水位。"""
    group = find_spillway_steep_chute_group(nodes, index)
    if not group:
        raise ValueError("泄水渠与陡坡连续链不存在。")
    data = build_spillway_steep_chute_input(group["subsegments"][0], 0.0)
    calculator = _load_kernel_calculator()
    kernel = sys.modules[calculator.__module__]
    _params, errors = kernel._validate_input(data)
    if errors:
        raise ValueError("泄水渠入口参数无效：" + "；".join(errors))
    depth = data.get("manual_start_depth")
    if depth is None:
        depth = kernel._solve_critical_depth(data["Q"], data["b"], data["m"], data["alpha_profile"])
    depth = float(depth)
    if not math.isfinite(depth) or depth <= 0:
        raise ValueError("泄水渠实际起点水深必须大于 0。")
    velocity = data["Q"] / (depth * (data["b"] + data["m"] * depth))
    return {"depth_m": depth, "velocity_ms": velocity, "alpha_profile": data["alpha_profile"]}


def _load_kernel_calculator():
    """加载泄水渠与陡坡专项内核入口。"""
    water_profile_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_root = os.path.dirname(water_profile_dir)
    kernel_dir = os.path.join(repo_root, "calc_渠系计算算法内核")
    if kernel_dir not in sys.path:
        sys.path.insert(0, kernel_dir)
    module = importlib.import_module("泄水渠与陡坡设计")
    return getattr(module, "quick_calculate_spillway_steep_chute")


def calculate_spillway_steep_chute(
    group: Dict[str, Any], inlet_water_level: float, inlet_state: Optional[Dict[str, Any]] = None,
    increased_inlet_state: Optional[Dict[str, Any]] = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """调用专项内核并校验水面线结果可用。"""
    input_payload = build_spillway_steep_chute_input(group, inlet_water_level, inlet_state)
    if input_payload.get("Q_increased"):
        input_payload["increased_flow_independent_control"] = True
        if increased_inlet_state is not None:
            if increased_inlet_state.get("unavailable"):
                input_payload["increased_flow_boundary_missing"] = True
            else:
                input_payload["increased_flow_start_depth"] = increased_inlet_state["depth_m"]
    quick_calculate = _load_kernel_calculator()
    result = quick_calculate(input_payload)
    if not result.get("success"):
        errors = result.get("errors") or result.get("risks") or ["专项内核计算失败"]
        raise ValueError(f"泄水渠与陡坡「{group.get('name', '')}」计算失败：{'；'.join(str(item) for item in errors)}")

    profile = result.get("profile") or {}
    points = result.get("profile_points") or profile.get("points") or []
    export = result.get("water_profile_export") or {}
    if not profile.get("available") or profile.get("status") != "ok" or len(points) < 2:
        message = (
            profile.get("message")
            or export.get("说明")
            or "未形成可用沿程水面线"
        )
        raise ValueError(f"泄水渠与陡坡「{group.get('name', '')}」水面线不可用：{message}")
    distances = [_point_distance(point) for point in points]
    length = float(group["length"])
    if (abs(distances[0]) > 2e-6 or abs(distances[-1] - length) > max(2e-6, length * 1e-8)
            or any(right <= left for left, right in zip(distances, distances[1:]))):
        raise ValueError("泄水渠水面线未完整覆盖实际渠长或沿程距离不递增，不能回填表3。")
    for point in points:
        for key in ("distance_m", "depth_m", "water_elevation_m", "bed_elevation_m", "velocity_ms"):
            if not math.isfinite(_coerce_float(point.get(key), float("nan"))):
                raise ValueError(f"泄水渠水面线 {key} 不是有效有限数值，不能回填表3。")
        if float(point["depth_m"]) <= 0:
            raise ValueError("泄水渠水面线包含非正水深，不能回填表3。")
    chain_nodes = group.get("advanced_nodes") or group.get("nodes", [])
    if chain_nodes and group.get("outlet") is not chain_nodes[-1]:
        jump = result.get("hydraulic_jump", {})
        old_message = jump.get("message")
        message = "本子段末端属于连续链内部衔接，消能仅在整条链末端评价。"
        jump.update(status="internal_chain_connection", applicable=False, design_available=False,
                    message=message, recommended_pool_length_m=None, recommended_pool_depth_m=None)
        result.setdefault("summary", {})["消力池计算状态"] = message
        result["risks"] = [risk for risk in result.get("risks", []) if risk != old_message]
    return result, input_payload


def _point_distance(point: Dict[str, Any]) -> float:
    """读取水面线点的沿程距离。"""
    return _coerce_float(point.get("distance_m", point.get("distance", point.get("x", 0.0))), 0.0)


def _interpolate_point(points: List[Dict[str, Any]], distance: float, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """插值基本水深和高程后重算断面与流速，保持连续方程。"""
    point = _interpolate_raw_point(points, distance)
    if not point or data is None:
        return point
    h = float(point["depth_m"])
    b, m, Q, n = (float(data[key]) for key in ("b", "m", "Q", "n"))
    alpha = float(data.get("alpha_profile", 1.1))
    area = (b + m * h) * h
    wetted = b + 2.0 * h * math.sqrt(1.0 + m * m)
    radius = area / wetted
    velocity = Q / area
    width = b + 2.0 * m * h
    point.update(area_m2=area, wetted_perimeter_m=wetted, hydraulic_radius_m=radius,
                 water_top_width_m=width, velocity_ms=velocity,
                 froude=velocity / math.sqrt(9.81 * area / width),
                 hydraulic_slope=n * n * velocity * velocity / radius ** (4.0 / 3.0),
                 specific_energy_m=h + alpha * velocity * velocity / (2.0 * 9.81),
                 water_elevation_m=point["bed_elevation_m"] + h)
    return point


def _interpolate_raw_point(points: List[Dict[str, Any]], distance: float) -> Dict[str, Any]:
    """按沿程距离插值水面线点。"""
    if not points:
        return {}
    sorted_points = sorted(points, key=_point_distance)
    if distance <= _point_distance(sorted_points[0]):
        return dict(sorted_points[0])
    if distance >= _point_distance(sorted_points[-1]):
        return dict(sorted_points[-1])

    for left, right in zip(sorted_points, sorted_points[1:]):
        dl = _point_distance(left)
        dr = _point_distance(right)
        if dl <= distance <= dr:
            if abs(dr - dl) <= 1e-12:
                return dict(right)
            ratio = (distance - dl) / (dr - dl)
            row: Dict[str, Any] = {}
            keys = set(left.keys()) | set(right.keys())
            for key in keys:
                lv = left.get(key)
                rv = right.get(key)
                if isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
                    row[key] = lv + (rv - lv) * ratio
                else:
                    row[key] = lv if ratio < 0.5 else rv
            return row
    return dict(sorted_points[-1])


def _point_total_head(point: Dict[str, Any]) -> float:
    """总能头等于渠底高程与断面比能之和。"""
    return float(point["bed_elevation_m"]) + float(point["specific_energy_m"])


def _point_float(point: Dict[str, Any], *keys: str) -> float:
    """从水面线点读取浮点字段。"""
    for key in keys:
        if key in point and point.get(key) not in (None, ""):
            return _coerce_float(point.get(key), 0.0)
    return 0.0


def _apply_point_to_node(node: ChannelNode, point: Dict[str, Any]) -> None:
    """把一个水面线点回填到表3节点。"""
    depth = _point_float(point, "depth_m", "depth", "水深_m")
    water_level = _point_float(point, "water_elevation_m", "water_elevation", "水位_m")
    velocity = _point_float(point, "velocity_ms", "流速_m_s")
    bed_elevation = _point_float(point, "bed_elevation_m", "bed_elevation", "渠底高程_m")

    node.water_depth = depth
    node.water_level = water_level
    node.velocity = velocity
    node.bottom_elevation = bed_elevation
    # 采用含掺气、加大工况和安全超高的内核墙高；已指定更高结构时保留。
    metadata = node.section_params.setdefault(SPILLWAY_STEEP_CHUTE_PARAM_KEY, {})
    previous_auto = metadata.get("auto_structure_height_m")
    if previous_auto is None or not math.isclose(node.structure_height, float(previous_auto), abs_tol=1e-3):
        metadata["supplied_structure_height_m"] = node.structure_height
    supplied_height = float(metadata.get("supplied_structure_height_m", 0.0))
    wall_height = _point_float(point, "sidewall_height_m")
    if wall_height > 0:
        node.structure_height = max(supplied_height, wall_height)
        metadata["auto_structure_height_m"] = node.structure_height
    else:
        node.structure_height = supplied_height
        metadata.pop("auto_structure_height_m", None)
    if node.structure_height > 0:
        node.top_elevation = node.bottom_elevation + node.structure_height
    else:
        node.top_elevation = 0.0

    area = _point_float(point, "area_m2")
    wetted = _point_float(point, "wetted_perimeter_m")
    radius = _point_float(point, "hydraulic_radius_m")
    if area > 0:
        node.section_params["A"] = area
    if wetted > 0:
        node.section_params["X"] = wetted
    if radius > 0:
        node.section_params["R"] = radius
    if depth > 0:
        node.section_params["h"] = depth
        node.section_params["水深"] = depth


def _chain_role_for_index(chain: Dict[str, Any], index: int) -> str:
    """按整条专项链判断节点角色。"""
    if index == int(chain.get("first_index", -1)):
        return "inlet"
    if index == int(chain.get("last_index", -1)):
        return "outlet"
    return "middle"


def _withdraw_chain_wall_design(result: Dict[str, Any], reason: str = "") -> None:
    """全链加大工况失败后，同时撤销各展示、导出副本中的设计墙高。"""
    message = "连续链的加大工况尚未全部完成，侧墙高度待校核。请检查各子段加大工况入口及水面线条件。"
    if reason:
        message += " " + reason
    result["aeration_and_sidewall"].update(enabled=False, recommended_sidewall_height_m=None,
        increased_flow_checked=False, control_flow_m3s=None, message=message)

    def clear_points(value):
        if isinstance(value, dict):
            for key in ("sidewall_height_m", "sidewall_top_elevation_m", "建议侧墙高度"):
                value.pop(key, None)
            for child in value.values():
                clear_points(child)
        elif isinstance(value, list):
            for child in value:
                clear_points(child)

    clear_points(result)
    result.setdefault("summary", {})["侧墙计算状态"] = message
    if message not in result.setdefault("risks", []):
        result["risks"].append(message)


def _apply_spillway_steep_chute_segment_result(
    chain: Dict[str, Any],
    segment: Dict[str, Any],
    result: Dict[str, Any],
    input_payload: Dict[str, Any],
    inlet_water_level: float,
) -> float:
    """把一个固定底坡子段结果回填到子段节点，并返回出口水位。"""
    points = result.get("profile_points") or (result.get("profile") or {}).get("points") or []
    inlet = segment["inlet"]
    outlet = segment["outlet"]
    length = _coerce_float(segment.get("length", 0.0), 0.0)
    length_source = str(segment.get("length_source", "") or "")
    outlet_point = _interpolate_point(points, length, input_payload)
    outlet_water_level = _point_float(outlet_point, "water_elevation_m", "water_elevation", "水位_m")
    inlet_point = _interpolate_point(points, 0.0, input_payload)
    segment_loss = max(0.0, _point_total_head(inlet_point) - _point_total_head(outlet_point))
    summaries = copy.deepcopy(chain.get("chain_subsegments", []))

    for offset, node in enumerate(segment.get("nodes", []) or []):
        node_index = int(segment.get("indexes", [])[offset])
        role = _chain_role_for_index(chain, node_index)
        distances = segment.get("node_distances")
        distance = distances[offset] if distances else _segment_distance(inlet, node, length_source)
        if node is outlet:
            distance = length
        point = _interpolate_point(points, distance, input_payload)
        _apply_point_to_node(node, point)

        node.head_loss_friction = 0.0
        node.head_loss_bend = 0.0
        node.head_loss_local = 0.0
        node.head_loss_siphon = 0.0
        node.external_head_loss = None
        node.head_loss_total = 0.0

        payload = dict(node.section_params.get(SPILLWAY_STEEP_CHUTE_PARAM_KEY, {}) or {})
        payload.update(
            {
                "success": True,
                "params_dirty": False,
                "role": role,
                "group_key": chain.get("key", ""),
                "chain_key": chain.get("key", ""),
                "group_length_m": chain.get("length", 0.0),
                "chain_length_m": chain.get("length", 0.0),
                "chain_segment_count": len(chain.get("subsegments", []) or []),
                "chain_subsegments": summaries,
                "segment_key": segment.get("key", ""),
                "segment_index": int(segment.get("segment_index", 0)),
                "segment_length_m": length,
                "segment_slope_inv": _coerce_float(segment.get("slope_inv", 0.0), 0.0),
                "segment_slope_i": _coerce_float(segment.get("slope_i", 0.0), 0.0),
                "inlet_water_level_m": inlet_water_level,
                "outlet_water_level_m": outlet_water_level,
                "segment_head_loss_m": segment_loss,
                "segment_water_level_drop_m": inlet_water_level - outlet_water_level,
                "head_loss_total": 0.0,
                "input": copy.deepcopy(input_payload),
                "result": copy.deepcopy(result),
                "profile_points": copy.deepcopy(points),
                "risks": copy.deepcopy(result.get("risks", [])),
                "display_point": copy.deepcopy(point),
            }
        )
        node.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY] = payload
        setattr(node, _GROUP_KEY_ATTR, chain.get("key", ""))
        setattr(node, _ROLE_ATTR, role)
        setattr(node, _GROUP_INDEXES_ATTR, tuple(chain.get("indexes", ())))
    return outlet_water_level


def apply_spillway_steep_chute_result(
    group: Dict[str, Any],
    result: Dict[str, Any],
    input_payload: Dict[str, Any],
    inlet_water_level: float,
) -> int:
    """兼容旧调用：把单个子段结果回填到整组节点。"""
    group = _complete_chain_group(group)
    segment = dict(group)
    segment.update(
        {
            "key": f"{group.get('key', '')}:segment:1",
            "segment_index": 1,
            "slope_i": input_payload.get("i", 0.0),
            "slope_inv": input_payload.get("slope_inv", 0.0),
        }
    )
    _apply_spillway_steep_chute_segment_result(group, segment, result, input_payload, inlet_water_level)
    return int(group.get("last_index", 0))


def calculate_and_apply_spillway_steep_chute_group(
    nodes: List[ChannelNode],
    inlet_index: int,
    inlet_water_level: float,
) -> int:
    """从入口行开始计算并回填整条连续专项链。"""
    raw_indexes = get_spillway_steep_chute_chain_indexes(nodes, inlet_index)
    _invalidate_chain_nodes([nodes[index] for index in raw_indexes])
    try:
        group = find_spillway_steep_chute_group(nodes, inlet_index)
    except Exception as exc:
        _clear_failed_chain([nodes[index] for index in raw_indexes], str(exc))
        raise
    if not group:
        raise ValueError("泄水渠与陡坡成组信息缺失，无法接入表3水面线。")
    if group["first_index"] != inlet_index:
        return int(group["last_index"])
    subsegments = group.get("subsegments", []) or []
    if not subsegments:
        raise ValueError(f"泄水渠与陡坡「{_chain_display_name(group)}」缺少可计算子段。")

    initial_water_level = inlet_water_level
    current_water_level = inlet_water_level
    current_state: Optional[Dict[str, Any]] = None
    increased_state: Optional[Dict[str, Any]] = None
    pending = []
    chain_loss = 0.0
    try:
        # 整链成功后再提交回填，后段失败不会留下半条新结果。
        for segment in subsegments:
            result, input_payload = calculate_spillway_steep_chute(
                segment, current_water_level, current_state, increased_state)
            points = result.get("profile_points") or (result.get("profile") or {}).get("points") or []
            start = _interpolate_point(points, 0.0, input_payload)
            current_state = _interpolate_point(points, float(segment["length"]), input_payload)
            energy_loss = _point_total_head(start) - _point_total_head(current_state)
            if energy_loss < -1e-5:
                raise ValueError("泄水渠分段结果出现无外加能量的总能头上升，不能回填。")
            chain_loss += max(0.0, energy_loss)
            pending.append((segment, result, input_payload, current_water_level))
            current_water_level = current_state["water_elevation_m"]
            increased_points = result.get("aeration_and_sidewall", {}).get("increased_flow_profile_points", [])
            increased_state = increased_points[-1] if increased_points else (
                {"unavailable": True} if input_payload.get("Q_increased", 0) > input_payload["Q"] else None)
        if increased_state and increased_state.get("unavailable"):
            reason = next((result["aeration_and_sidewall"].get("message", "")
                           for _, result, _, _ in pending if not result["aeration_and_sidewall"].get("enabled")), "")
            for _segment, result, _inputs, _inlet in pending:
                _withdraw_chain_wall_design(result, reason)
        for segment, result, input_payload, segment_inlet in pending:
            _apply_spillway_steep_chute_segment_result(group, segment, result, input_payload, segment_inlet)
    except Exception as exc:
        _clear_failed_chain(group["nodes"], str(exc))
        raise
    for index, node in zip(group.get("indexes", []) or [], group.get("nodes", []) or []):
        role = _chain_role_for_index(group, int(index))
        node.head_loss_total = chain_loss if role == "outlet" else 0.0
        payload = dict(node.section_params.get(SPILLWAY_STEEP_CHUTE_PARAM_KEY, {}) or {})
        payload.update(
            {
                "role": role,
                "chain_head_loss_total": chain_loss,
                "chain_water_level_drop_m": initial_water_level - current_water_level,
                "head_loss_total": chain_loss if role == "outlet" else 0.0,
                "chain_inlet_water_level_m": initial_water_level,
                "chain_outlet_water_level_m": current_water_level,
            }
        )
        node.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY] = payload
    return int(group["last_index"])


def get_spillway_steep_chute_total_loss(node: ChannelNode) -> Optional[float]:
    """读取专项真实能量损失；入口接口和出口整链损失分别计入一次。"""
    if not is_spillway_steep_chute_node(node):
        return None
    payload = (getattr(node, "section_params", {}) or {}).get(SPILLWAY_STEEP_CHUTE_PARAM_KEY, {}) or {}
    if not isinstance(payload, dict) or not payload.get("success") or payload.get("params_dirty"):
        return 0.0
    if "head_loss_total" not in payload:
        return None
    return max(0.0, _coerce_float(payload.get("head_loss_total"), 0.0))
