# -*- coding: utf-8 -*-
"""
有压管道共用归一化工具。

负责统一处理管材别名和行索引值，供计算、结果展示和导出复用。
"""

from typing import Any, Dict


PRESSURE_PIPE_MATERIAL_ALIASES = {
    "PE管": "HDPE管",
    "PCCP管": "预应力钢筒混凝土管",
    "钢筋混凝土管": "预应力钢筒混凝土管",
    "预应力钢筒混凝土管(n=0.013)": "预应力钢筒混凝土管",
    "预应力钢筒混凝土管(n=0.014)": "预应力钢筒混凝土管_n014",
}


def coerce_row_index(value: Any, default: int = -1) -> int:
    """将行索引安全转换为整数，保留合法的 0。"""
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_material_display_lookup(materials: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """构造材质展示名到 canonical key 的映射。"""
    lookup: Dict[str, str] = {}
    for key, params in (materials or {}).items():
        display_name = str((params or {}).get("name") or "").strip()
        if display_name:
            lookup[display_name] = key
    return lookup


def resolve_pressure_pipe_material(
    material_value: Any,
    materials: Dict[str, Dict[str, Any]],
    default_material: str,
) -> Dict[str, Any]:
    """解析有压管道材质，返回展示值、canonical key 和是否回退。"""
    raw_text = str(material_value or "").strip()
    material_map = materials or {}
    fallback_key = default_material if default_material in material_map else next(iter(material_map), "")
    display_lookup = _build_material_display_lookup(material_map)

    if raw_text in material_map:
        return {
            "raw_input": raw_text,
            "display_value": raw_text,
            "canonical_key": raw_text,
            "recognized": True,
            "used_default": False,
            "matched_alias": False,
        }

    display_key = display_lookup.get(raw_text, "")
    if display_key in material_map:
        return {
            "raw_input": raw_text,
            "display_value": raw_text,
            "canonical_key": display_key,
            "recognized": True,
            "used_default": False,
            "matched_alias": True,
        }

    alias_key = PRESSURE_PIPE_MATERIAL_ALIASES.get(raw_text, "")
    if alias_key in material_map:
        return {
            "raw_input": raw_text,
            "display_value": raw_text,
            "canonical_key": alias_key,
            "recognized": True,
            "used_default": False,
            "matched_alias": True,
        }

    return {
        "raw_input": raw_text,
        "display_value": raw_text or fallback_key,
        "canonical_key": fallback_key,
        "recognized": False,
        "used_default": True,
        "matched_alias": False,
    }


def normalize_pressure_pipe_material_key(
    material_value: Any,
    materials: Dict[str, Dict[str, Any]],
    default_material: str,
) -> str:
    """仅返回 canonical key，供历史接口直接复用。"""
    return str(
        resolve_pressure_pipe_material(
            material_value,
            materials,
            default_material=default_material,
        ).get("canonical_key", "")
    )
