# -*- coding: utf-8 -*-
"""有压管道专项结果契约及旧工程迁移；运行期以节点独立字段为唯一真源。"""

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class PressurePipeOverride:
    """专项计算采用结果；数值、来源与可追溯详情使用固定字段。"""

    identity: str
    enabled: bool = True
    storage_key: str = ""
    display_name: str = ""
    group_mode: str = "unnamed_row_segment"
    data_mode: str = ""
    applied_at: str = ""
    calc_steps: str = ""
    target_row_index: int = -1
    upstream_row_index: int = -1
    Q: float = 0.0
    D: float = 0.0
    total_length: float = 0.0
    pipe_velocity: float = 0.0
    friction_loss: float = 0.0
    total_bend_loss: float = 0.0
    local_loss: float = 0.0
    inlet_transition_loss: float = 0.0
    outlet_transition_loss: float = 0.0
    total_head_loss: float = 0.0
    manual_total_head_loss: Optional[float] = None
    manual_override_source: str = ""
    manual_override_updated_at: str = ""
    friction_details: dict[str, Any] = field(default_factory=dict)
    bend_details: dict[str, Any] = field(default_factory=dict)
    local_details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value) -> Optional["PressurePipeOverride"]:
        """按旧工程既有规则转换字段；无效或禁用记录返回空。"""
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            return None
        identity = str(value.get("identity", "") or "").strip()
        if not bool(value.get("enabled", False)) or not identity:
            return None
        fields = {"identity": identity}
        for key in ("storage_key", "display_name", "data_mode", "applied_at", "calc_steps",
                    "manual_override_source", "manual_override_updated_at"):
            fields[key] = str(value.get(key, "") or "").strip()
        fields["storage_key"] = fields["storage_key"] or identity
        fields["group_mode"] = str(value.get("group_mode", "") or "unnamed_row_segment").strip()
        for key in ("target_row_index", "upstream_row_index"):
            try:
                fields[key] = int(value.get(key, -1))
            except (TypeError, ValueError):
                fields[key] = -1
        for key in ("Q", "D", "total_length", "pipe_velocity", "friction_loss", "total_bend_loss",
                    "local_loss", "inlet_transition_loss", "outlet_transition_loss", "total_head_loss"):
            try:
                fields[key] = float(value.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                fields[key] = 0.0
        manual_value = value.get("manual_total_head_loss")
        if manual_value is not None and str(manual_value).strip():
            try:
                fields["manual_total_head_loss"] = float(manual_value)
            except (TypeError, ValueError):
                pass
        for key in ("friction_details", "bend_details", "local_details"):
            detail = value.get(key, {})
            fields[key] = copy.deepcopy(detail) if isinstance(detail, dict) else {}
        return cls(**fields)

    def to_dict(self) -> dict:
        """输出历史字段布局，保留可选人工采用字段的缺省规则。"""
        result = asdict(self)
        if self.manual_total_head_loss is None:
            result.pop("manual_total_head_loss")
        for key in ("manual_override_source", "manual_override_updated_at"):
            if not result[key]:
                result.pop(key)
        return result


def normalize_pressure_pipe_window_override(value) -> dict:
    """供旧字典调用方使用同一份有类型契约。"""
    override = PressurePipeOverride.from_mapping(value)
    return override.to_dict() if override is not None else {}


def get_pressure_pipe_window_override(node) -> dict:
    """一次性迁移旧断面参数副本，之后仅从节点独立字段读取。"""
    if node is None:
        return {}
    override = normalize_pressure_pipe_window_override(getattr(node, "pressure_pipe_window_override", {}))
    params = getattr(node, "section_params", None)
    if isinstance(params, dict) and "pressure_pipe_window_override" in params:
        if not override:
            override = normalize_pressure_pipe_window_override(params["pressure_pipe_window_override"])
        # 先复制再移除，不能修改调用方传入的历史工程字典。
        node.section_params = dict(params)
        node.section_params.pop("pressure_pipe_window_override", None)
    node.pressure_pipe_window_override = copy.deepcopy(override)
    return override


def set_pressure_pipe_window_override(node, value) -> None:
    """写入唯一运行期结果；清除任何遗留断面参数副本。"""
    node.pressure_pipe_window_override = normalize_pressure_pipe_window_override(value)
    params = getattr(node, "section_params", None)
    if isinstance(params, dict) and "pressure_pipe_window_override" in params:
        node.section_params = dict(params)
        node.section_params.pop("pressure_pipe_window_override", None)


def pressure_pipe_section_params_for_project(node) -> dict:
    """仅序列化时生成旧字段镜像，保证旧版工程读取兼容。"""
    override = get_pressure_pipe_window_override(node)
    result = copy.deepcopy(getattr(node, "section_params", {}) or {})
    if override:
        result["pressure_pipe_window_override"] = copy.deepcopy(override)
    return result
