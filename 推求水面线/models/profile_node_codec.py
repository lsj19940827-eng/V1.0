"""表3数据契约和节点值规则；不导入 Qt，不读取界面控件。"""

import copy
import datetime
import math
import re

from 推求水面线.models.data_models import ChannelNode, restore_gate_water_levels
from 推求水面线.models.enums import StructureType, InOutType
from 推求水面线.models.profile_state import SnapshotTable, USER_DATA_ROLE
from 推求水面线.models.pressure_pipe_override import (
    normalize_pressure_pipe_window_override, get_pressure_pipe_window_override,
    set_pressure_pipe_window_override,
)
from 推求水面线.config.constants import (
    DEFAULT_GATE_HEAD_LOSS, DEFAULT_ROUGHNESS, DEFAULT_SIPHON_ROUGHNESS,
    XXPIPE_CHANNEL_LEVEL_OPTIONS, ZERO_TOLERANCE,
)
from 推求水面线.shared.shared_data_manager import normalize_section_type_name
from 推求水面线.utils.pressure_pipe_result_helpers import make_pressure_pipe_identity

SPILLWAY_STEEP_CHUTE_PARAM_KEY = "spillway_steep_chute"


def is_spillway_steep_chute_value(value):
    text = str(getattr(value, "value", value) or "").strip()
    return text in _SPILLWAY_STEEP_CHUTE_DISPLAY_TYPES

_SPILLWAY_STEEP_CHUTE_DISPLAY_TYPES = {
    "充水渠",
    "泄水渠",
    "陡坡",
    "泄槽",
    "陡槽",
    "泄水渠及陡坡",
    "泄水渠与陡坡",
}

PRESSURE_PIPE_LIKE_STRUCTURE_TEXTS = {"有压管道", "定向钻", "顶管"}

CULVERT_FAMILY_TYPE_KEY = "culvert_family_type"

ARCH_CULVERT_THETA_ROLE_KEY = "_arch_culvert_theta_deg"

ARCH_CULVERT_SOURCE_ROLE_KEY = "_arch_culvert_source_allowed"

ARCH_CULVERT_H_STRAIGHT_ROLE_KEY = "_arch_culvert_H_straight"

ARCH_CULVERT_MANUAL_H_STRAIGHT_ROLE_KEY = "_arch_culvert_manual_H_straight"

ARCH_CULVERT_USED_MANUAL_H_STRAIGHT_ROLE_KEY = "_arch_culvert_used_manual_H_straight"

TUNNEL_ARCH_THETA_ROLE_KEY = "_tunnel_arch_theta_deg"

TUNNEL_ARCH_H_STRAIGHT_ROLE_KEY = "_tunnel_arch_H_straight"

TUNNEL_ARCH_MANUAL_H_STRAIGHT_ROLE_KEY = "_tunnel_arch_manual_H_straight"

TUNNEL_ARCH_USED_MANUAL_H_STRAIGHT_ROLE_KEY = "_tunnel_arch_used_manual_H_straight"

RECT_CULVERT_FAMILY_TEXT = "暗涵-矩形"

ARCH_CULVERT_FAMILY_TEXT = "暗涵-圆拱直墙型"

SOURCE_COORD_X_ROLE_KEY = "_source_x_text"

SOURCE_COORD_Y_ROLE_KEY = "_source_y_text"

FLAT_BOTTOM_TUNNEL_SOURCE_ROLE_KEY = "_flat_bottom_tunnel_source_allowed"

USE_INCREASE_ROLE_KEY = "_use_increase"

PRESSURE_PIPE_ROW_ID_ROLE_KEY = "_pressure_pipe_row_identity"

PRESSURE_PIPE_WINDOW_OVERRIDE_ROLE_KEY = "_pressure_pipe_window_override"

PRESSURE_PIPE_NAMED_GROUP_RESULT_ROLE_KEY = "_pressure_pipe_named_group_result"

PRESSURE_PIPE_LOSS_OVERRIDE_ROLE_KEY = "_pressure_pipe_loss_override_m"

SPILLWAY_STEEP_CHUTE_ROLE_KEY = "_spillway_steep_chute"

GATE_HEAD_LOSS_USER_SET_ROLE_KEY = "_gate_head_loss_user_set"

GATE_HEAD_LOSS_USER_SET_PARAM_KEY = "gate_head_loss_user_set"

GATE_UPSTREAM_WATER_LEVEL_ROLE_KEY = "_gate_upstream_water_level"

GATE_DOWNSTREAM_WATER_LEVEL_ROLE_KEY = "_gate_downstream_water_level"

GATE_ELEVATION_REFERENCE_DETAILS_ROLE_KEY = "_gate_elevation_reference_details"

COMPOUND_TRAPEZOID_PARAMS_ROLE_KEY = "_compound_trapezoid_params"

COMPOUND_TRAPEZOID_PARAM_KEYS = ("m1", "B1", "m2", "B2", "m3", "h1")


def _resolve_spillway_steep_chute_display_structure_type(raw_value, fallback="") -> str:
    """读取用户填写的泄水渠类结构名，导出显示用，不影响计算归一。"""
    for value in (raw_value, fallback):
        text = str(getattr(value, "value", value) or "").strip()
        if text in _SPILLWAY_STEEP_CHUTE_DISPLAY_TYPES:
            return text
    return ""


def normalize_culvert_family_type_name(structure_type) -> str:
    """统一暗涵家族子类型名称。"""
    text = normalize_section_type_name(structure_type)
    if not text:
        return ""
    if "暗涵" not in text and "暗渠" not in text and text != "矩形暗涵":
        return ""
    if "圆拱直墙" in text or "圆弧直墙" in text:
        return ARCH_CULVERT_FAMILY_TEXT
    return RECT_CULVERT_FAMILY_TEXT


def normalize_use_increase_flag(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return bool(value)


def normalize_compound_trapezoid_params(source):
    """统一整理复式梯形隐藏参数，避免在表格刷新时丢失。"""
    if not isinstance(source, dict):
        return {}

    params = {}
    for key in COMPOUND_TRAPEZOID_PARAM_KEYS:
        value = source.get(key, None)
        if value is None or str(value).strip() == "":
            continue
        try:
            params[key] = float(value)
        except (TypeError, ValueError):
            continue
    return params


def parse_flow_values_text(flow_text: str) -> list:
    """把逗号分隔流量文本解析为浮点列表。"""
    if not flow_text or not str(flow_text).strip():
        return []
    text = str(flow_text).replace("，", ",")
    values = []
    for item in text.split(","):
        piece = str(item or "").strip()
        if not piece:
            continue
        try:
            values.append(float(piece))
        except (TypeError, ValueError):
            continue
    return values


class ProfileNodeRules:
    """界面适配器与纯节点解码器共用的领域值规则。"""

    @staticmethod
    def _is_pressure_pipe_like_structure_text(struct_text: str) -> bool:
        text = normalize_section_type_name(struct_text)
        if not text:
            return False
        structure_type_cls = globals().get("StructureType")
        helper = getattr(structure_type_cls, "is_pressure_pipe_like_str", None)
        if callable(helper):
            try:
                return bool(helper(text))
            except Exception:
                pass
        return text in PRESSURE_PIPE_LIKE_STRUCTURE_TEXTS

    @classmethod
    def _is_pressure_pipe_like_node(cls, node) -> bool:
        if getattr(node, "is_pressure_pipe", False):
            return True
        struct_type = getattr(node, "structure_type", None)
        structure_type_cls = globals().get("StructureType")
        helper = getattr(structure_type_cls, "is_pressure_pipe_like", None)
        if callable(helper):
            try:
                return bool(helper(struct_type))
            except Exception:
                pass
        value = getattr(struct_type, "value", struct_type)
        return cls._is_pressure_pipe_like_structure_text(value)

    @classmethod
    def _get_node_structure_type_text(cls, node) -> str:
        getter = getattr(node, "get_structure_type_str", None)
        if callable(getter):
            try:
                text = normalize_section_type_name(getter())
                if text:
                    return text
            except Exception:
                pass
        struct_type = getattr(node, "structure_type", None)
        value = getattr(struct_type, "value", struct_type)
        return normalize_section_type_name(value)

    @staticmethod
    def _is_xxpipe_channel_level_text(channel_level: str | None) -> bool:
        return str(channel_level or "").strip() in XXPIPE_CHANNEL_LEVEL_OPTIONS

    @classmethod
    def _is_regular_pressure_pipe_node(cls, node) -> bool:
        return cls._get_node_structure_type_text(node) == "有压管道"

    @classmethod
    def _is_unnamed_pressure_pipe_row_node(cls, node, channel_level: str | None = None) -> bool:
        if not cls._is_regular_pressure_pipe_node(node):
            return False
        if str(getattr(node, "name", "") or "").strip():
            return False
        if cls._is_xxpipe_channel_level_text(channel_level):
            return True
        return bool(cls._get_pressure_pipe_window_override(node))

    @classmethod
    def _is_named_pressure_pipe_group_node(cls, node) -> bool:
        if not cls._is_pressure_pipe_like_node(node):
            return False
        return bool(str(getattr(node, "name", "") or "").strip())

    @staticmethod
    def _build_pressure_pipe_row_identity_from_flow_section(flow_section, row_index: int) -> str:
        flow_section = str(flow_section or "").strip()
        row_part = f"row{int(row_index) + 1}"
        if flow_section:
            return f"flow{flow_section}-{row_part}"
        return row_part

    @classmethod
    def _build_pressure_pipe_row_identity(cls, node, row_index: int) -> str:
        return cls._build_pressure_pipe_row_identity_from_flow_section(
            getattr(node, "flow_section", ""),
            row_index,
        )

    @classmethod
    def _ensure_pressure_pipe_row_identity(cls, node, row_index: int | None = None) -> str:
        identity = str(getattr(node, "pressure_pipe_row_identity", "") or "").strip()
        if not identity and row_index is not None:
            identity = cls._build_pressure_pipe_row_identity(node, row_index)
            setattr(node, "pressure_pipe_row_identity", identity)
        return identity

    @staticmethod
    def _get_pressure_pipe_group_storage_key(group) -> str:
        """返回有压管道窗口分组稳定存储键。"""
        storage_key = str(getattr(group, "storage_key", "") or "").strip()
        if storage_key:
            return storage_key
        identity = str(getattr(group, "identity", "") or "").strip()
        if identity:
            return identity
        return str(getattr(group, "name", "") or "").strip()

    @staticmethod
    def _get_pressure_pipe_group_display_name(group) -> str:
        """返回有压管道窗口分组展示名称。"""
        display_name = str(getattr(group, "display_name", "") or "").strip()
        if display_name:
            return display_name
        return str(getattr(group, "name", "") or "").strip() or "未命名有压管道"

    @staticmethod
    def _get_pressure_pipe_group_structure_text(group) -> str:
        """返回分组结构形式文本。"""
        value = getattr(group, "structure_type", "")
        value = getattr(value, "value", value)
        return str(value or "").strip()

    @staticmethod
    def _coerce_pressure_pipe_row_index(value, default: int = -1) -> int:
        """将有压管道相关行索引安全转换为整数，保留合法的 0。"""
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_pressure_pipe_window_override(value) -> dict:
        return normalize_pressure_pipe_window_override(value)

    @staticmethod
    def _normalize_pressure_pipe_named_group_result(value) -> dict:
        """规范化命名承压组隐藏结果元数据。"""
        if not isinstance(value, dict):
            return {}
        identity = str(value.get("identity", "") or "").strip()
        storage_key = str(value.get("storage_key", "") or identity).strip() or identity
        display_name = str(value.get("display_name", "") or "").strip()
        structure_type = str(value.get("structure_type", "") or "").strip()
        applied_at = str(value.get("applied_at", "") or "").strip()
        calc_steps = str(value.get("calc_steps", "") or "").strip()
        target_row_index = ProfileNodeRules._coerce_pressure_pipe_row_index(
            value.get("target_row_index", -1)
        )
        total_head_loss_raw = value.get("total_head_loss", None)
        total_head_loss = None
        if total_head_loss_raw is not None and str(total_head_loss_raw).strip() != "":
            try:
                total_head_loss = float(total_head_loss_raw)
            except (TypeError, ValueError):
                total_head_loss = None
        if not any((identity, storage_key, display_name, structure_type, applied_at, calc_steps)) and total_head_loss is None:
            return {}
        return {
            "identity": identity,
            "storage_key": storage_key,
            "display_name": display_name,
            "structure_type": structure_type,
            "total_head_loss": total_head_loss,
            "applied_at": applied_at,
            "calc_steps": calc_steps,
            "target_row_index": target_row_index,
        }

    @classmethod
    def _get_pressure_pipe_window_override(cls, node) -> dict:
        return get_pressure_pipe_window_override(node)

    @staticmethod
    def _normalize_pressure_pipe_loss_override_value(value):
        """标准化表3第38列人工采用值。"""
        if value in ("", None):
            return None
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric_value) or numeric_value < 0:
            return None
        return numeric_value

    @classmethod
    def _get_pressure_pipe_loss_override(cls, node):
        """读取表3第38列人工采用值。"""
        override_value = cls._normalize_pressure_pipe_loss_override_value(
            getattr(node, "pressure_pipe_loss_override_m", None)
        )
        if override_value is not None:
            setattr(node, "pressure_pipe_loss_override_m", override_value)
        return override_value

    @classmethod
    def _set_pressure_pipe_loss_override(cls, node, value):
        """写入或清空表3第38列人工采用值。"""
        override_value = cls._normalize_pressure_pipe_loss_override_value(value)
        setattr(node, "pressure_pipe_loss_override_m", override_value)
        if override_value is None and hasattr(node, "_pressure_pipe_display_loss"):
            setattr(node, "_pressure_pipe_display_loss", 0.0)
        return override_value

    @staticmethod
    def _is_gate_like_structure_text(structure_text) -> bool:
        """判断结构形式是否属于需要默认过闸损失的闸/分水口。"""
        text = str(structure_text or "").strip()
        return bool(text and ("闸" in text or "分水" in text))

    @classmethod
    def _is_gate_loss_user_set_node(cls, node) -> bool:
        """判断节点是否已有用户明确设置过闸损失的标记。"""
        section_params = getattr(node, "section_params", {}) or {}
        return bool(section_params.get(GATE_HEAD_LOSS_USER_SET_PARAM_KEY, False))

    @classmethod
    def _set_gate_loss_user_set(cls, node, user_set: bool):
        """写入或清空过闸损失用户设置标记。"""
        section_params = getattr(node, "section_params", None)
        if not isinstance(section_params, dict):
            section_params = {}
            setattr(node, "section_params", section_params)
        if user_set:
            section_params[GATE_HEAD_LOSS_USER_SET_PARAM_KEY] = True
        else:
            section_params.pop(GATE_HEAD_LOSS_USER_SET_PARAM_KEY, None)

    def _is_gate_loss_user_set_for_row(self, row: int, node=None) -> bool:
        """判断表3某行过闸损失是否由用户明确设置。"""
        payload = self._get_row_payload(row)
        if GATE_HEAD_LOSS_USER_SET_ROLE_KEY in payload:
            return bool(payload.get(GATE_HEAD_LOSS_USER_SET_ROLE_KEY))
        table = getattr(self, "node_table", None)
        item = table.item(row, 37) if table and 0 <= row < table.rowCount() else None
        raw_text = str(item.text() if item else "").strip()
        if raw_text and raw_text != "-":
            try:
                return abs(float(raw_text)) <= ZERO_TOLERANCE
            except (TypeError, ValueError):
                return False
        if node is not None:
            return self._is_gate_loss_user_set_node(node)
        return False

    @classmethod
    def _get_pressure_pipe_named_group_result(cls, node) -> dict:
        """读取命名承压组隐藏结果元数据。"""
        result = cls._normalize_pressure_pipe_named_group_result(
            getattr(node, "pressure_pipe_named_group_result", {})
        )
        if not result:
            section_params = getattr(node, "section_params", {}) or {}
            result = cls._normalize_pressure_pipe_named_group_result(
                section_params.get("pressure_pipe_named_group_result", {})
            )
        if result:
            setattr(node, "pressure_pipe_named_group_result", copy.deepcopy(result))
            section_params = getattr(node, "section_params", None)
            if isinstance(section_params, dict):
                section_params["pressure_pipe_named_group_result"] = copy.deepcopy(result)
        return result

    @classmethod
    def _set_pressure_pipe_named_group_result(cls, node, result) -> dict:
        """写入命名承压组隐藏结果元数据。"""
        normalized = cls._normalize_pressure_pipe_named_group_result(result)
        setattr(node, "pressure_pipe_named_group_result", copy.deepcopy(normalized))
        section_params = getattr(node, "section_params", None)
        if isinstance(section_params, dict):
            if normalized:
                section_params["pressure_pipe_named_group_result"] = copy.deepcopy(normalized)
            else:
                section_params.pop("pressure_pipe_named_group_result", None)
        return normalized

    @classmethod
    def _is_named_pressure_pipe_outlet_with_hidden_result(cls, node) -> bool:
        """判断是否为带隐藏结果元数据的命名承压组出口行。"""
        if not cls._is_named_pressure_pipe_group_node(node):
            return False
        in_out = getattr(node, "in_out", None)
        if getattr(in_out, "value", "") != "出":
            return False
        return bool(cls._get_pressure_pipe_named_group_result(node))

    @classmethod
    def _get_named_pressure_pipe_group_total_head_loss(cls, node):
        """读取命名承压组整组总损失。"""
        result = cls._get_pressure_pipe_named_group_result(node)
        if not result:
            return None
        return result.get("total_head_loss", None)

    @classmethod
    def _get_named_pressure_pipe_outlet_display_loss(cls, node) -> float:
        """计算命名承压组出口行在表3列38的显示值。"""
        total_head_loss = cls._get_named_pressure_pipe_group_total_head_loss(node)
        stored_display = float(getattr(node, "_pressure_pipe_display_loss", 0.0) or 0.0)
        if stored_display > 0:
            return stored_display

        siphon_loss = float(getattr(node, "head_loss_siphon", 0.0) or 0.0)
        if siphon_loss > 0 and (
            total_head_loss is None or abs(siphon_loss - float(total_head_loss)) > 1e-6
        ):
            setattr(node, "_pressure_pipe_display_loss", siphon_loss)
            return siphon_loss

        hydraulic_loss = (
            float(getattr(node, "head_loss_bend", 0.0) or 0.0)
            + float(getattr(node, "head_loss_friction", 0.0) or 0.0)
            + float(getattr(node, "head_loss_local", 0.0) or 0.0)
        )
        if hydraulic_loss > 0:
            setattr(node, "_pressure_pipe_display_loss", hydraulic_loss)
            return hydraulic_loss
        return 0.0

    @classmethod
    def _rebuild_named_pressure_pipe_outlet_total_loss(cls, node) -> float:
        """按逐行口径重建命名承压组出口行总损失。"""
        display_loss = cls._get_named_pressure_pipe_outlet_display_loss(node)
        total_loss = (
            display_loss
            + float(getattr(node, "head_loss_reserve", 0.0) or 0.0)
            + float(getattr(node, "head_loss_gate", 0.0) or 0.0)
        )
        node.head_loss_total = total_loss
        return total_loss

    @classmethod
    def _build_pressure_pipe_named_group_result_payload(
        cls,
        *,
        node=None,
        group=None,
        record: dict | None = None,
        row_index: int = -1,
        total_head_loss=None,
        calc_steps: str = "",
        applied_at: str = "",
    ) -> dict:
        """构造命名承压组隐藏结果元数据。"""
        record = record or {}
        identity = str(record.get("identity", "") or "").strip()
        if not identity and group is not None:
            identity = cls._build_pressure_pipe_group_identity(group)
        if not identity and node is not None:
            identity = make_pressure_pipe_identity(
                getattr(node, "flow_section", ""),
                getattr(node, "name", ""),
            )

        storage_key = str(record.get("storage_key", "") or "").strip()
        if not storage_key and group is not None:
            storage_key = cls._get_pressure_pipe_group_storage_key(group)
        storage_key = storage_key or identity

        display_name = str(record.get("display_name", "") or "").strip()
        if not display_name and group is not None:
            display_name = cls._get_pressure_pipe_group_display_name(group)
        if not display_name and node is not None:
            display_name = str(getattr(node, "name", "") or "").strip()

        structure_type = str(record.get("structure_type", "") or "").strip()
        if not structure_type and group is not None:
            structure_type = cls._get_pressure_pipe_group_structure_text(group)
        if not structure_type and node is not None:
            structure_type = cls._get_node_structure_type_text(node)

        if total_head_loss is None:
            total_head_loss = record.get("total_head_loss", None)
        if total_head_loss is not None and str(total_head_loss).strip() != "":
            try:
                total_head_loss = float(total_head_loss)
            except (TypeError, ValueError):
                total_head_loss = None
        else:
            total_head_loss = None

        if not applied_at:
            applied_at = str(record.get("applied_at", "") or "").strip()
        if not applied_at:
            applied_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not calc_steps:
            calc_steps = str(record.get("calc_steps", "") or "").strip()

        target_row_index = cls._coerce_pressure_pipe_row_index(
            record.get(
                "target_row_index",
                getattr(group, "target_row_index", getattr(group, "outlet_row_index", row_index))
                if group is not None else row_index,
            )
        )

        return cls._normalize_pressure_pipe_named_group_result({
            "identity": identity,
            "storage_key": storage_key,
            "display_name": display_name,
            "structure_type": structure_type,
            "total_head_loss": total_head_loss,
            "applied_at": applied_at,
            "calc_steps": calc_steps,
            "target_row_index": target_row_index,
        })

    @classmethod
    def _migrate_named_pressure_pipe_outlet_visible_group_loss(
        cls,
        node,
        row_index: int = -1,
    ) -> bool:
        """把旧版命名承压组出口行的可见整组损失迁入隐藏元数据。"""
        if not cls._is_named_pressure_pipe_group_node(node):
            return False
        in_out = getattr(node, "in_out", None)
        if getattr(in_out, "value", "") != "出":
            return False

        changed = False
        hidden_result = cls._get_pressure_pipe_named_group_result(node)
        hidden_total = hidden_result.get("total_head_loss", None) if hidden_result else None

        external_loss = getattr(node, "external_head_loss", None)
        legacy_total = None
        if external_loss is not None and str(external_loss).strip() != "":
            try:
                legacy_total = float(external_loss)
            except (TypeError, ValueError):
                legacy_total = None

        if hidden_total is None:
            siphon_loss = float(getattr(node, "head_loss_siphon", 0.0) or 0.0)
            if legacy_total is None and siphon_loss > 0:
                legacy_total = siphon_loss
            if legacy_total is not None and legacy_total > 0:
                payload = cls._build_pressure_pipe_named_group_result_payload(
                    node=node,
                    row_index=row_index,
                    total_head_loss=legacy_total,
                    calc_steps="legacy-visible-migration",
                )
                if payload:
                    cls._set_pressure_pipe_named_group_result(node, payload)
                    hidden_result = payload
                    hidden_total = payload.get("total_head_loss", None)
                    changed = True

        if external_loss is not None:
            node.external_head_loss = None
            changed = True

        if hidden_total is not None:
            siphon_loss = float(getattr(node, "head_loss_siphon", 0.0) or 0.0)
            if siphon_loss > 0 and abs(siphon_loss - float(hidden_total)) <= 1e-6:
                node.head_loss_siphon = 0.0
                changed = True
            stored_display = float(getattr(node, "_pressure_pipe_display_loss", 0.0) or 0.0)
            if stored_display > 0 and abs(stored_display - float(hidden_total)) <= 1e-6:
                setattr(node, "_pressure_pipe_display_loss", 0.0)
                changed = True

        if hidden_result:
            cls._rebuild_named_pressure_pipe_outlet_total_loss(node)
        return changed

    @staticmethod
    def _get_pressure_pipe_row_override_group_modes() -> set[str]:
        """返回按 row override 展示/回写的有压结果模式。"""
        return {
            "unnamed_row_segment",
            "named_row_segment",
            "chain_row_member",
            "chain_tunnel_member",
            "chain_prefix_member",
        }

    @classmethod
    def _is_pressure_pipe_row_override_node(cls, node, channel_level: str | None = None) -> bool:
        """判断当前行是否应按 row override 口径展示有压结果。"""
        if cls._is_unnamed_pressure_pipe_row_node(node, channel_level):
            return True
        if not cls._is_pressure_pipe_like_node(node):
            return False
        override = cls._get_pressure_pipe_window_override(node)
        if not override:
            return False
        group_mode = str(override.get("group_mode", "") or "").strip()
        return group_mode in cls._get_pressure_pipe_row_override_group_modes()

    @classmethod
    def _set_pressure_pipe_window_override(cls, node, override):
        set_pressure_pipe_window_override(node, override)

    @classmethod
    def _get_pressure_pipe_row_manual_override_loss(cls, override: dict | None):
        """读取逐行承压手动采用值。"""
        if not isinstance(override, dict):
            return None
        raw_value = override.get("manual_total_head_loss", None)
        if raw_value is None or str(raw_value).strip() == "":
            return None
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _rebuild_pressure_pipe_row_override_total_loss(
        cls,
        node,
        fallback_display_loss: float | None = None,
    ) -> float:
        """把逐行承压覆盖结果同步回正式损失字段。"""
        override = cls._get_pressure_pipe_window_override(node)
        manual_override = cls._get_pressure_pipe_loss_override(node)
        row_override_modes = cls._get_pressure_pipe_row_override_group_modes()
        friction_loss = float(getattr(node, "head_loss_friction", 0.0) or 0.0)
        bend_loss = float(getattr(node, "head_loss_bend", 0.0) or 0.0)
        local_loss = float(getattr(node, "head_loss_local", 0.0) or 0.0)
        display_loss = None
        manual_override_applied = False

        if override and str(override.get("group_mode", "") or "").strip() in row_override_modes:
            friction_loss = float(override.get("friction_loss", 0.0) or 0.0)
            bend_loss = float(override.get("total_bend_loss", 0.0) or 0.0)
            local_loss = float(override.get("local_loss", 0.0) or 0.0)
            if local_loss <= ZERO_TOLERANCE:
                local_loss = (
                    float(override.get("inlet_transition_loss", 0.0) or 0.0)
                    + float(override.get("outlet_transition_loss", 0.0) or 0.0)
                )
            manual_total = cls._get_pressure_pipe_row_manual_override_loss(override)
            if manual_total is not None:
                display_loss = manual_total
                manual_override_applied = True
            elif manual_override is None:
                display_loss = float(override.get("total_head_loss", 0.0) or 0.0)
            node.head_loss_friction = friction_loss
            node.head_loss_bend = bend_loss
            node.head_loss_local = local_loss

        if manual_override is not None:
            display_loss = manual_override
            manual_override_applied = True
        elif display_loss is None:
            try:
                display_loss = float(fallback_display_loss or 0.0)
            except (TypeError, ValueError):
                display_loss = 0.0
        if display_loss <= ZERO_TOLERANCE and not manual_override_applied:
            display_loss = max(friction_loss + bend_loss + local_loss, 0.0)

        node.head_loss_siphon = 0.0
        node.external_head_loss = None
        setattr(node, "_pressure_pipe_display_loss", display_loss)
        node.head_loss_total = (
            display_loss
            + float(getattr(node, "head_loss_reserve", 0.0) or 0.0)
            + float(getattr(node, "head_loss_gate", 0.0) or 0.0)
        )
        return display_loss

    @classmethod
    def _apply_pressure_pipe_loss_cell_to_node(
        cls,
        node,
        value,
        channel_level: str | None = None,
    ) -> float:
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            numeric_value = 0.0

        manual_override = cls._get_pressure_pipe_loss_override(node)
        effective_value = manual_override if manual_override is not None else numeric_value

        if cls._is_pressure_pipe_row_override_node(node, channel_level):
            cls._ensure_pressure_pipe_row_identity(node)
            return cls._rebuild_pressure_pipe_row_override_total_loss(
                node,
                fallback_display_loss=effective_value,
            )

        if cls._is_regular_pressure_pipe_node(node) and not str(getattr(node, "name", "") or "").strip():
            node.head_loss_siphon = 0.0
            setattr(node, "_pressure_pipe_display_loss", 0.0)
            return 0.0

        if cls._is_named_pressure_pipe_outlet_with_hidden_result(node):
            node.head_loss_siphon = 0.0
            node.external_head_loss = None
            if manual_override is None:
                setattr(node, "_pressure_pipe_display_loss", numeric_value)
            cls._rebuild_named_pressure_pipe_outlet_total_loss(node)
            return effective_value

        if manual_override is None and hasattr(node, "_pressure_pipe_display_loss"):
            setattr(node, "_pressure_pipe_display_loss", 0.0)
        if manual_override is None:
            node.head_loss_siphon = numeric_value
        if manual_override is None and numeric_value > 0 and getattr(node, "external_head_loss", None) is not None:
            node.external_head_loss = None
        node.head_loss_total = (
            float(getattr(node, "head_loss_bend", 0.0) or 0.0)
            + float(getattr(node, "head_loss_friction", 0.0) or 0.0)
            + float(getattr(node, "head_loss_local", 0.0) or 0.0)
            + float(getattr(node, "head_loss_reserve", 0.0) or 0.0)
            + float(getattr(node, "head_loss_gate", 0.0) or 0.0)
            + effective_value
        )
        return effective_value

    @staticmethod
    def _is_flat_bottom_circle_source_payload(payload) -> bool:
        """读取平底圆形来源标记，缺失时按不允许处理。"""
        if not isinstance(payload, dict):
            return False
        if FLAT_BOTTOM_TUNNEL_SOURCE_ROLE_KEY in payload:
            return bool(payload.get(FLAT_BOTTOM_TUNNEL_SOURCE_ROLE_KEY))
        if "_from_table1_source" in payload:
            return bool(payload.get("_from_table1_source"))
        return False

    @staticmethod
    def _is_arch_culvert_source_payload(payload) -> bool:
        """读取圆拱直墙型暗涵来源标记，兼容旧带入行。"""
        if not isinstance(payload, dict):
            return False
        if ARCH_CULVERT_SOURCE_ROLE_KEY in payload:
            return bool(payload.get(ARCH_CULVERT_SOURCE_ROLE_KEY))
        family_type = normalize_culvert_family_type_name(payload.get(CULVERT_FAMILY_TYPE_KEY, ""))
        if family_type == ARCH_CULVERT_FAMILY_TEXT and "_from_table1_source" in payload:
            return bool(payload.get("_from_table1_source"))
        return False

    def _normalize_coord_text(self, value) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text or text == "-":
            return ""
        return text

    def _node_is_source_row(self, node) -> bool:
        if bool(getattr(node, "from_table1_source", False)):
            return True
        return not getattr(node, "is_transition", False) and not getattr(node, "is_auto_inserted_channel", False)

    @staticmethod
    def _get_pressure_pipe_group_flow_section(group) -> str:
        rows = getattr(group, "rows", None) or []
        for node in rows:
            fs = str(getattr(node, "flow_section", "") or "").strip()
            if fs:
                return fs
        return "-"

    @classmethod
    def _build_pressure_pipe_group_identity(cls, group) -> str:
        identity = str(getattr(group, "identity", "") or "").strip()
        if identity:
            return identity
        return make_pressure_pipe_identity(
            cls._get_pressure_pipe_group_flow_section(group),
            getattr(group, "name", "") or ""
        )


class ProfileNodeCodec(ProfileNodeRules):
    """只消费独立快照，把历史表3语义转换为领域节点。"""

    def __init__(self, state, *, design_flows_text="", roughness_text="", channel_level="", fallback_groups=None,
                 node_factory=ChannelNode, structure_type=StructureType, in_out_type=InOutType):
        self.node_table = SnapshotTable(state)
        self._state = state
        self._node_factory = node_factory
        self._structure_type = structure_type
        self._in_out_type = in_out_type
        self._channel_level = channel_level
        self.design_flow_edit = _TextValue(design_flows_text)
        self.roughness_edit = _TextValue(roughness_text)
        self._pressure_turn_radius_fallback_groups = set(fallback_groups or ())
        self._node_structure_heights = state.parameter_values('structure_heights')
        self._node_chamfer_params = state.parameter_values('chamfer_params')
        self._node_u_params = state.parameter_values('u_params')
        self._node_velocity_increased = state.parameter_values('velocity_increased')

    def _get_current_channel_level_text(self, settings=None):
        return str(getattr(settings, 'channel_level', '') or self._channel_level).strip()

    def _get_node_row_data(self, row):
        return list(self._state.rows[row].cells)

    def _get_row_payload(self, row):
        if not 0 <= row < len(self._state.rows):
            return {}
        value = self._state.rows[row].cell_data.get(0)
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _fval(item, default=0.0):
        try:
            return float(item.text()) if item is not None else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _sf(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_flow_values(text):
        return parse_flow_values_text(text)

    def decode(self):
        """从节点表格构建ChannelNode列表（与原版Tkinter get_nodes完全对齐）"""

        # 辅助函数提到循环外避免每行重复定义（#16）
        table = self.node_table

        def _precise_value(row, col):
            first = table.item(row, 0)
            item = table.item(row, col)
            payload = first.data(USER_DATA_ROLE) if first else None
            stored = (payload.get('_numeric_display_values') if isinstance(payload.get('_numeric_display_values'), dict) else {}).get(str(col)) if isinstance(payload, dict) else None
            if isinstance(stored, dict) and item and item.text() == stored.get('text'):
                value = stored.get('value')
                if isinstance(value, (int, float)) and math.isfinite(value):
                    return value
            return None

        def _read_float(row, col):
            precise = _precise_value(row, col)
            if precise is not None:
                return precise
            item = table.item(row, col)
            if item:
                try:
                    return float(item.text())
                except (ValueError, TypeError):
                    pass
            return 0.0

        def _read_gate_water_level(row, key):
            """读取水位单元格的两侧隐藏值，保留零值并兼容旧工程缺失。"""
            value = self._get_row_payload(row).get(key)
            if value is None or isinstance(value, bool):
                return None
            try:
                value = float(value)
            except (TypeError, ValueError):
                return None
            return value if math.isfinite(value) else None

        def _read_text(row, col):
            item = table.item(row, col)
            if item:
                t = item.text().strip()
                if t and t != '-':
                    return t
            return ""

        def _parse_station(text):
            """解析格式化桩号文本（如 '南支0+123.456'）为浮点数"""
            if not text:
                return 0.0
            if '+' in text:
                parts = text.split('+')
                if len(parts) == 2:
                    km_digits = ''.join(c for c in parts[0] if c.isdigit())
                    try:
                        km = int(km_digits) if km_digits else 0
                        m = float(parts[1])
                        return km * 1000 + m
                    except (ValueError, TypeError):
                        pass
            try:
                return float(text)
            except (ValueError, TypeError):
                return 0.0

        def _read_ip_metadata(row):
            """读取 IP 单元格保存的原始/显示编号元数据。"""
            item = table.item(row, 4)
            if not item:
                return {}
            data = item.data(USER_DATA_ROLE)
            return data if isinstance(data, dict) else {}

        def _parse_ip_number(row, text):
            """解析IP编号，支持复合格式如 'IP3 沪蓉倒进'（#11）"""
            meta = _read_ip_metadata(row)
            raw_ip_number = meta.get("_raw_ip_number", None)
            if raw_ip_number not in ("", None):
                try:
                    return int(raw_ip_number)
                except (ValueError, TypeError):
                    pass
            if not text:
                return 0
            # 先尝试直接转int
            try:
                return int(text)
            except (ValueError, TypeError):
                pass
            # 从 "IPxx" 或 "IP xx ..." 中提取数字
            m = re.match(r'IP\s*(\d+)', text)
            if m:
                return int(m.group(1))
            return 0

        def _parse_display_ip_number(row, text):
            """解析显示用 IP 编号；特殊建筑进出口允许为空。"""
            meta = _read_ip_metadata(row)
            display_ip_number = meta.get("_display_ip_number", None)
            if display_ip_number not in ("", None):
                try:
                    return int(display_ip_number)
                except (ValueError, TypeError):
                    pass
            if not text:
                return None
            m = re.match(r'IP\s*(\d+)', text)
            if m:
                return int(m.group(1))
            return None

        nodes = []
        channel_level = self._get_current_channel_level_text()
        _default_q = (self._parse_flow_values(self.design_flow_edit.text()) or [5.0])[0]
        self._pressure_turn_radius_fallback_groups = set()

        for r in range(table.rowCount()):
            data = self._get_node_row_data(r)
            # data[0-7]: 流量段,建筑物名称,结构形式,进出口,IP,X,Y,转弯半径
            # data[8-19]: 几何结果列
            # data[20-26]: 底宽B,直径D,半径R,边坡m,糙率n,底坡1/i,流量Q
            # data[27-31]: 水力结果列
            # data[32-40]: 水头损失列
            # data[41-43]: 水位,渠底高程,渠顶高程
            node = self._node_factory()
            node.flow_section = str(data[0]).strip()
            node.name = str(data[1]).strip()

            # 结构形式 (col 2)
            raw_struct_str = normalize_section_type_name(str(data[2]).strip())
            culvert_family_type = normalize_culvert_family_type_name(raw_struct_str)
            spillway_display_structure_type = _resolve_spillway_steep_chute_display_structure_type(
                raw_struct_str,
                "",
            )
            struct_str = raw_struct_str
            if culvert_family_type or struct_str in {"暗渠", "矩形暗渠", "矩形暗涵"}:
                struct_str = "矩形暗涵"
            if is_spillway_steep_chute_value(struct_str):
                struct_str = "泄水渠与陡坡"
            if struct_str:
                try:
                    node.structure_type = self._structure_type.from_string(struct_str)
                except ValueError:
                    pass
                if struct_str == "渐变段" or (node.structure_type and node.structure_type == self._structure_type.TRANSITION):
                    node.is_transition = True

            # 标记闸类结构（分水闸/分水口/节制闸/泄水闸等）
            if node.structure_type and self._structure_type.is_diversion_gate(node.structure_type):
                node.is_diversion_gate = True
            # 标记倒虹吸
            if node.structure_type and node.structure_type == self._structure_type.INVERTED_SIPHON:
                node.is_inverted_siphon = True
            # 标记有压管道
            if node.structure_type and self._is_pressure_pipe_like_structure_text(node.structure_type.value):
                node.is_pressure_pipe = True
            pipe_material = ""
            local_loss_ratio = None
            in_out_raw = ""
            use_increase = True
            from_table1_source = False
            explicit_table1_source_flag = False
            flat_bottom_source_allowed = False
            arch_culvert_H_straight = None
            arch_culvert_manual_H_straight = None
            arch_culvert_used_manual_H_straight = None
            tunnel_arch_theta_deg = 0.0
            tunnel_arch_H_straight = None
            tunnel_arch_manual_H_straight = None
            tunnel_arch_used_manual_H_straight = None
            pressure_pipe_row_identity = ""
            compound_trapezoid_params = {}
            spillway_steep_chute_payload = {}
            # 恢复自动插入补段标记（通过UserRole存储）
            _first_item = table.item(r, 0)
            if _first_item:
                _ur = _first_item.data(USER_DATA_ROLE)
                if isinstance(_ur, dict) and _ur.get('_auto_channel'):
                    node.is_auto_inserted_channel = True
                    _auto_channel_struct = normalize_section_type_name(
                        str(_ur.get('_auto_channel_structure_type', '') or '')
                    )
                    if _auto_channel_struct and not node.structure_type:
                        try:
                            node.structure_type = self._structure_type.from_string(_auto_channel_struct)
                        except ValueError:
                            pass
                    try:
                        node.stat_length = float(_ur.get('_stat_length', 0.0) or 0.0)
                    except (TypeError, ValueError):
                        node.stat_length = 0.0
                elif _ur == "auto_channel":  # 兼容旧格式
                    node.is_auto_inserted_channel = True
                # 恢复渐变段详细参数（#10）
                if isinstance(_ur, dict) and _ur.get('_transition_data'):
                    td = _ur['_transition_data']
                    node.transition_type = td.get('transition_type', '')
                    node.transition_form = td.get('transition_form', '')
                    node.transition_zeta = td.get('transition_zeta', 0.0)
                    node.transition_theta = td.get('transition_theta', 0.0)
                    if not node.structure_type:
                        node.structure_type = self._structure_type.TRANSITION
                        node.is_transition = True
                if isinstance(_ur, dict):
                    node.connection_source_details = copy.deepcopy(_ur.get("_connection_source_details", {}) or {})
                    if _ur.get('_aux_coords') or _ur.get('_auto_channel'):
                        try:
                            node.x = float(_ur.get('_x', 0.0) or 0.0)
                            node.y = float(_ur.get('_y', 0.0) or 0.0)
                        except (TypeError, ValueError):
                            node.x = 0.0
                            node.y = 0.0
                    _override = _ur.get("_transition_length_override_m", None)
                    if _override is not None and str(_override).strip() != "":
                        try:
                            node.transition_length_override_m = float(_override)
                        except (TypeError, ValueError):
                            node.transition_length_override_m = None
                    node.transition_length_source = str(_ur.get("_transition_length_source", "formula") or "formula")
                    node.transition_length_warning = str(_ur.get("_transition_length_warning", "") or "")
                    node.transition_rule_upstream_structure_type = str(
                        _ur.get("_transition_rule_upstream_structure_type", "") or ""
                    )
                    node.transition_rule_downstream_structure_type = str(
                        _ur.get("_transition_rule_downstream_structure_type", "") or ""
                    )
                    _length_details = _ur.get("_transition_length_calc_details", None)
                    if isinstance(_length_details, dict):
                        node.transition_length_calc_details = copy.deepcopy(_length_details)
                        if not node.transition_rule_upstream_structure_type:
                            node.transition_rule_upstream_structure_type = str(
                                _length_details.get("upstream_structure_type", "") or ""
                            )
                        if not node.transition_rule_downstream_structure_type:
                            node.transition_rule_downstream_structure_type = str(
                                _length_details.get("downstream_structure_type", "") or ""
                            )
                    _loss_details = _ur.get("_transition_loss_calc_details", None)
                    if isinstance(_loss_details, dict):
                        node.transition_calc_details = copy.deepcopy(_loss_details)
                    if "_from_table1_source" in _ur:
                        explicit_table1_source_flag = True
                        from_table1_source = bool(_ur.get("_from_table1_source"))
                    flat_bottom_source_allowed = self._is_flat_bottom_circle_source_payload(_ur)
                    arch_culvert_source_allowed = self._is_arch_culvert_source_payload(_ur)
                    pressure_pipe_row_identity = str(
                        _ur.get(PRESSURE_PIPE_ROW_ID_ROLE_KEY, "") or ""
                    ).strip()
                    pressure_pipe_window_override = self._normalize_pressure_pipe_window_override(
                        _ur.get(PRESSURE_PIPE_WINDOW_OVERRIDE_ROLE_KEY, {})
                    )
                    if pressure_pipe_window_override:
                        self._set_pressure_pipe_window_override(node, pressure_pipe_window_override)
                    pressure_pipe_named_group_result = self._normalize_pressure_pipe_named_group_result(
                        _ur.get(PRESSURE_PIPE_NAMED_GROUP_RESULT_ROLE_KEY, {})
                    )
                    if pressure_pipe_named_group_result:
                        self._set_pressure_pipe_named_group_result(node, pressure_pipe_named_group_result)
                    pressure_pipe_loss_override = self._normalize_pressure_pipe_loss_override_value(
                        _ur.get(PRESSURE_PIPE_LOSS_OVERRIDE_ROLE_KEY, None)
                    )
                    self._set_pressure_pipe_loss_override(node, pressure_pipe_loss_override)
                    _ext = _ur.get('_external_head_loss', None)
                    if _ext is not None and str(_ext).strip() != "":
                        try:
                            node.external_head_loss = float(_ext)
                        except (ValueError, TypeError):
                            node.external_head_loss = None
                    _pm = str(_ur.get('_pipe_material', '') or '').strip()
                    if _pm:
                        pipe_material = _pm
                    stored_culvert_family_type = normalize_culvert_family_type_name(
                        _ur.get(CULVERT_FAMILY_TYPE_KEY, "")
                    )
                    if stored_culvert_family_type:
                        culvert_family_type = stored_culvert_family_type
                    _ior = str(_ur.get('_in_out_raw', '') or '').strip()
                    if _ior:
                        in_out_raw = _ior
                    _llr = _ur.get('_local_loss_ratio', None)
                    if _llr is not None and str(_llr).strip() != "":
                        try:
                            local_loss_ratio = float(_llr)
                        except (ValueError, TypeError):
                            local_loss_ratio = None
                    if USE_INCREASE_ROLE_KEY in _ur:
                        use_increase = normalize_use_increase_flag(
                            _ur.get(USE_INCREASE_ROLE_KEY),
                            default=True,
                        )
                    compound_trapezoid_params = normalize_compound_trapezoid_params(
                        _ur.get(COMPOUND_TRAPEZOID_PARAMS_ROLE_KEY, {})
                    )
                    if isinstance(_ur.get(SPILLWAY_STEEP_CHUTE_ROLE_KEY), dict):
                        spillway_steep_chute_payload = copy.deepcopy(_ur.get(SPILLWAY_STEEP_CHUTE_ROLE_KEY) or {})
                        stored_display_structure_type = _resolve_spillway_steep_chute_display_structure_type(
                            spillway_steep_chute_payload.get("display_structure_type", ""),
                            "",
                        )
                        if stored_display_structure_type:
                            spillway_display_structure_type = stored_display_structure_type
                    arch_culvert_theta_deg = self._sf(_ur.get(ARCH_CULVERT_THETA_ROLE_KEY, 0), 0.0)
                    if ARCH_CULVERT_H_STRAIGHT_ROLE_KEY in _ur:
                        arch_culvert_H_straight = self._sf(_ur.get(ARCH_CULVERT_H_STRAIGHT_ROLE_KEY, 0), 0.0)
                    if ARCH_CULVERT_MANUAL_H_STRAIGHT_ROLE_KEY in _ur:
                        arch_culvert_manual_H_straight = self._sf(_ur.get(ARCH_CULVERT_MANUAL_H_STRAIGHT_ROLE_KEY, 0), 0.0)
                    if ARCH_CULVERT_USED_MANUAL_H_STRAIGHT_ROLE_KEY in _ur:
                        arch_culvert_used_manual_H_straight = bool(_ur.get(ARCH_CULVERT_USED_MANUAL_H_STRAIGHT_ROLE_KEY))
                    tunnel_arch_theta_deg = self._sf(_ur.get(TUNNEL_ARCH_THETA_ROLE_KEY, 0), 0.0)
                    if TUNNEL_ARCH_H_STRAIGHT_ROLE_KEY in _ur:
                        tunnel_arch_H_straight = self._sf(_ur.get(TUNNEL_ARCH_H_STRAIGHT_ROLE_KEY, 0), 0.0)
                    if TUNNEL_ARCH_MANUAL_H_STRAIGHT_ROLE_KEY in _ur:
                        tunnel_arch_manual_H_straight = self._sf(_ur.get(TUNNEL_ARCH_MANUAL_H_STRAIGHT_ROLE_KEY, 0), 0.0)
                    if TUNNEL_ARCH_USED_MANUAL_H_STRAIGHT_ROLE_KEY in _ur:
                        tunnel_arch_used_manual_H_straight = bool(_ur.get(TUNNEL_ARCH_USED_MANUAL_H_STRAIGHT_ROLE_KEY))
                else:
                    arch_culvert_source_allowed = False
                    arch_culvert_theta_deg = 0.0
                    arch_culvert_H_straight = None
                    arch_culvert_manual_H_straight = None
                    arch_culvert_used_manual_H_straight = None
                    tunnel_arch_theta_deg = 0.0
                    tunnel_arch_H_straight = None
                    tunnel_arch_manual_H_straight = None
                    tunnel_arch_used_manual_H_straight = None
            else:
                arch_culvert_source_allowed = False
                arch_culvert_theta_deg = 0.0
                arch_culvert_H_straight = None
                arch_culvert_manual_H_straight = None
                arch_culvert_used_manual_H_straight = None
                tunnel_arch_theta_deg = 0.0
                tunnel_arch_H_straight = None
                tunnel_arch_manual_H_straight = None
                tunnel_arch_used_manual_H_straight = None
            if (
                not explicit_table1_source_flag
                and not from_table1_source
                and not getattr(node, 'is_transition', False)
                and not getattr(node, 'is_auto_inserted_channel', False)
            ):
                from_table1_source = True
            if struct_str == "隧洞-平底圆形":
                from_table1_source = bool(flat_bottom_source_allowed)
            node.from_table1_source = from_table1_source
            if struct_str == "隧洞-平底圆形" and not from_table1_source:
                node.structure_type = None
            if culvert_family_type == ARCH_CULVERT_FAMILY_TEXT and not arch_culvert_source_allowed:
                node.structure_type = None
                culvert_family_type = ""

            source_x_text = ""
            source_y_text = ""
            if _first_item and isinstance(_ur, dict):
                source_x_text = self._normalize_coord_text(_ur.get(SOURCE_COORD_X_ROLE_KEY, ""))
                source_y_text = self._normalize_coord_text(_ur.get(SOURCE_COORD_Y_ROLE_KEY, ""))

            x_text = self._normalize_coord_text(data[5])
            y_text = self._normalize_coord_text(data[6])
            if x_text:
                node.x = self._sf(x_text)
            if y_text:
                node.y = self._sf(y_text)
            if self._node_is_source_row(node):
                node.source_x_text = x_text or source_x_text
                node.source_y_text = y_text or source_y_text
            else:
                node.source_x_text = ""
                node.source_y_text = ""
            if pressure_pipe_row_identity:
                node.pressure_pipe_row_identity = pressure_pipe_row_identity
            elif self._is_pressure_pipe_row_override_node(node, channel_level):
                self._ensure_pressure_pipe_row_identity(node, r)

            # 进出口 (col 3)
            _io_text = _read_text(r, 3)
            if _io_text:
                node.in_out = self._in_out_type.from_string(_io_text)
            # IP编号 (col 4) — 支持复合格式 (#11)
            ip_text = _read_text(r, 4)
            node.ip_number = _parse_ip_number(r, ip_text)
            node.display_ip_number = _parse_display_ip_number(r, ip_text)
            # 记录转弯半径是否来自用户/表格的显式输入；"0" 也算显式输入，不能再当成空白兜底。
            _turn_radius_text = _read_text(r, 7)
            _turn_radius_is_explicit = bool(_turn_radius_text)
            node.turn_radius_is_explicit = _turn_radius_is_explicit
            node.turn_radius_text = _turn_radius_text if _turn_radius_is_explicit else ""
            _row_turn = self._sf(_turn_radius_text, 0.0) if _turn_radius_is_explicit else 0.0
            # 新规则：转弯半径单元格留空也按 0 处理，不再回退到全局半径。
            if _turn_radius_is_explicit:
                node.turn_radius = _row_turn
            else:
                node.turn_radius = 0.0
            # 有压管道仅保留表格中的显式值；留空统一按 0 处理。
            try:
                _struct_for_turn = str(data[2]).strip()
                _is_pressure_turn = self._is_pressure_pipe_like_structure_text(_struct_for_turn)
                _is_siphon_turn = "倒虹吸" in _struct_for_turn
                if _is_pressure_turn:
                    if _turn_radius_is_explicit:
                        node.turn_radius = _row_turn
                    else:
                        node.turn_radius = 0.0
                elif _is_siphon_turn and _turn_radius_is_explicit:
                    node.turn_radius = _row_turn
            except Exception:
                pass

            # ===== 几何结果列 (8-19) =====
            # 转角 (col 8)
            _ta = _read_float(r, 8)
            if _ta > 0:
                node.turn_angle = _ta
            # 切线长 (col 9)
            _tl = _read_float(r, 9)
            if _tl > 0:
                node.tangent_length = _tl
            # 弧长 (col 10)
            _al = _read_float(r, 10)
            if _al > 0:
                node.arc_length = _al
            # 弯道长度 (col 11)
            _cl = _read_float(r, 11)
            if _cl > 0:
                node.curve_length = _cl
            # IP直线间距 (col 12)
            _sd = _read_float(r, 12)
            if _sd > 0:
                node.straight_distance = _sd
            # IP桩号 (col 13)
            node.station_ip = _precise_value(r, 13) if _precise_value(r, 13) is not None else _parse_station(_read_text(r, 13))
            # 弯前BC (col 14)
            node.station_BC = _precise_value(r, 14) if _precise_value(r, 14) is not None else _parse_station(_read_text(r, 14))
            # 里程MC (col 15)
            node.station_MC = _precise_value(r, 15) if _precise_value(r, 15) is not None else _parse_station(_read_text(r, 15))
            # 弯末EC (col 16)
            node.station_EC = _precise_value(r, 16) if _precise_value(r, 16) is not None else _parse_station(_read_text(r, 16))
            # 复核弯前 (col 17)
            _cpre = _read_float(r, 17)
            if _cpre != 0:
                node.check_pre_curve = _cpre
            # 复核弯后 (col 18)
            _cpost = _read_float(r, 18)
            if _cpost != 0:
                node.check_post_curve = _cpost
            # 复核总长 (col 19)
            _ctot = _read_float(r, 19)
            if _ctot != 0:
                node.check_total_length = _ctot

            # ===== 水力输入列 (20-26) =====
            B = self._sf(data[20])
            D = self._sf(data[21])
            R = self._sf(data[22])
            m_val = self._sf(data[23])
            # 糙率默认值：倒虹吸行用倒虹吸默认糙率常量，其他用渠道糙率输入框
            _default_n = (DEFAULT_SIPHON_ROUGHNESS
                          if struct_str and "倒虹吸" in struct_str
                          else self._fval(self.roughness_edit, DEFAULT_ROUGHNESS))
            n_val = self._sf(data[24], _default_n)
            slope_inv = self._sf(data[25])
            raw_flow = _precise_value(r, 26)
            Q = raw_flow if raw_flow is not None else self._sf(data[26], _default_q)

            # 与原版Tkinter get_nodes一致：始终写入B/D/R_circle/m（即使为0）
            # 原因：_estimate_transition_length中 section_params.get("D", 3.0)
            # 若D不在dict中会返回默认值3.0，导致隧洞渐变段长度偏大
            node.section_params['B'] = B
            node.section_params['D'] = D
            node.section_params['R_circle'] = R
            node.section_params['m'] = m_val
            node.section_params['use_increase'] = use_increase
            if culvert_family_type:
                node.section_params[CULVERT_FAMILY_TYPE_KEY] = culvert_family_type
            if struct_str == "明渠-复式梯形" and compound_trapezoid_params:
                node.section_params.update(copy.deepcopy(compound_trapezoid_params))
                if not node.section_params.get('B', 0) and compound_trapezoid_params.get('B2', 0):
                    node.section_params['B'] = compound_trapezoid_params['B2']
            node.use_increase = use_increase
            if pipe_material:
                node.section_params['pipe_material'] = pipe_material
            if in_out_raw:
                node.section_params['in_out_raw'] = in_out_raw
            if local_loss_ratio is not None and local_loss_ratio > 0:
                node.section_params['local_loss_ratio'] = local_loss_ratio
            if is_spillway_steep_chute_value(struct_str) and spillway_display_structure_type:
                if not isinstance(spillway_steep_chute_payload, dict):
                    spillway_steep_chute_payload = {}
                spillway_steep_chute_payload["display_structure_type"] = spillway_display_structure_type
            if spillway_steep_chute_payload:
                if spillway_display_structure_type:
                    spillway_steep_chute_payload["display_structure_type"] = spillway_display_structure_type
                node.section_params[SPILLWAY_STEEP_CHUTE_PARAM_KEY] = spillway_steep_chute_payload
            node.roughness = n_val
            if slope_inv > 0:
                node.slope_i = 1.0 / slope_inv
            node.flow = Q

            # ===== 水力结果列 (27-31) =====
            _h = _read_float(r, 27)
            if _h > 0:
                node.water_depth = _h
            # 断面面积A (col 28)
            _area = _read_float(r, 28)
            if _area > 0:
                node.section_params['A'] = _area
            # 湿周X (col 29)
            _wp = _read_float(r, 29)
            if _wp > 0:
                node.section_params['X'] = _wp
            # 水力半径R (col 30)
            _hr2 = _read_float(r, 30)
            if _hr2 > 0:
                node.section_params['R'] = _hr2
            # 流速v (col 31)
            _v = _read_float(r, 31)
            if _v > 0:
                node.velocity = _v

            # ===== 水头损失列 (32-40) =====
            # 渐变段长度 (col 32)
            _trl_text = _read_text(r, 32)
            _trl = _read_float(r, 32)
            if _trl_text:
                node.transition_length = _trl
            # 渐变段损失 (col 33)
            _ht = _read_float(r, 33)
            if _ht != 0:
                node.head_loss_transition = _ht
            # 弯道损失 (col 34)
            _hb = _read_float(r, 34)
            if _hb != 0:
                node.head_loss_bend = _hb
            # 沿程损失 (col 35)
            _hf = _read_float(r, 35)
            if _hf != 0:
                node.head_loss_friction = _hf
            # 预留损失 (col 36)
            _hr = _read_float(r, 36)
            if _hr > 0:
                node.head_loss_reserve = _hr
            # 过闸损失 (col 37)
            _hg = _read_float(r, 37)
            gate_loss_user_set = self._is_gate_loss_user_set_for_row(r, node)
            if gate_loss_user_set:
                node.head_loss_gate = _hg
                self._set_gate_loss_user_set(node, True)
            elif _hg > 0:
                node.head_loss_gate = _hg
            elif self._is_gate_like_structure_text(struct_str):
                node.head_loss_gate = DEFAULT_GATE_HEAD_LOSS
            # 倒虹吸/有压管道损失 (col 38)
            _hs = _read_float(r, 38)
            self._apply_pressure_pipe_loss_cell_to_node(node, _hs, channel_level=channel_level)
            # 总损失 (col 39)
            _htotal = _read_float(r, 39)
            if _htotal != 0:
                node.head_loss_total = _htotal
            # 累计损失 (col 40)
            _hcum = _read_float(r, 40)
            if _hcum != 0:
                node.head_loss_cumulative = _hcum

            # ===== 高程列 (41-43) =====
            _wl = _read_float(r, 41)
            if _wl != 0:
                node.water_level = _wl
            _be = _read_float(r, 42)
            if _be != 0:
                node.bottom_elevation = _be
            _te = _read_float(r, 43)
            if _te != 0:
                node.top_elevation = _te
            if node.is_diversion_gate and not node.is_transition:
                node.gate_upstream_water_level = _read_gate_water_level(r, GATE_UPSTREAM_WATER_LEVEL_ROLE_KEY)
                node.gate_downstream_water_level = _read_gate_water_level(r, GATE_DOWNSTREAM_WATER_LEVEL_ROLE_KEY)
                reference_details = self._get_row_payload(r).get(GATE_ELEVATION_REFERENCE_DETAILS_ROLE_KEY)
                if isinstance(reference_details, dict):
                    # 保存完整来源及上次自动结果，完整重算才能区别自动字段与人工高程。
                    node.terminal_gate_backfill_details = copy.deepcopy(reference_details)

            # 恢复结构高度（用于计算渠顶高程，与Tkinter版 data_table.py 对齐）
            if r in self._node_structure_heights:
                node.structure_height = self._node_structure_heights[r]
            if culvert_family_type and node.structure_height > 0:
                node.section_params['H_total'] = node.structure_height
            if culvert_family_type == ARCH_CULVERT_FAMILY_TEXT:
                if arch_culvert_theta_deg > 0:
                    node.section_params['theta_deg'] = arch_culvert_theta_deg
                if arch_culvert_H_straight is not None:
                    node.section_params['H_straight'] = arch_culvert_H_straight
                if arch_culvert_manual_H_straight is not None:
                    node.section_params['manual_H_straight'] = arch_culvert_manual_H_straight
                if arch_culvert_used_manual_H_straight is not None:
                    node.section_params['used_manual_H_straight'] = arch_culvert_used_manual_H_straight
            if struct_str == "隧洞-圆拱直墙型":
                if node.structure_height > 0:
                    node.section_params['H_total'] = node.structure_height
                if tunnel_arch_theta_deg > 0:
                    node.section_params['theta_deg'] = tunnel_arch_theta_deg
                if tunnel_arch_H_straight is not None:
                    node.section_params['H_straight'] = tunnel_arch_H_straight
                if tunnel_arch_manual_H_straight is not None:
                    node.section_params['manual_H_straight'] = tunnel_arch_manual_H_straight
                if tunnel_arch_used_manual_H_straight is not None:
                    node.section_params['used_manual_H_straight'] = tunnel_arch_used_manual_H_straight

            # 恢复倒角参数（渡槽-矩形精确水力计算用）
            if r in self._node_chamfer_params:
                cp = self._node_chamfer_params[r]
                node.section_params['chamfer_angle'] = cp.get('chamfer_angle', 0)
                node.section_params['chamfer_length'] = cp.get('chamfer_length', 0)

            # 恢复明渠-U形圆心角
            if r in self._node_u_params:
                node.section_params['theta_deg'] = self._node_u_params[r].get('theta_deg', 0)
            # 恢复加大流速（从批量计算导入的加大流量工况流速）
            if r in self._node_velocity_increased:
                node.velocity_increased = self._node_velocity_increased[r]

            self._migrate_named_pressure_pipe_outlet_visible_group_loss(node, row_index=r)

            node.profile_row_id = self._state.rows[r].row_id
            nodes.append(node)
        restore_gate_water_levels(nodes)
        self._pressure_turn_radius_fallback_groups = set()
        return nodes


class _TextValue:
    """兼容历史解析器的纯字符串读取接口。"""

    def __init__(self, value):
        self.value = str(value or "")

    def text(self):
        return self.value
