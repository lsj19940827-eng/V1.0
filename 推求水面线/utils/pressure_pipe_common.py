# -*- coding: utf-8 -*-
"""
有压管道共用归一化工具。

负责统一处理管材别名和行索引值，供计算、结果展示和导出复用。
"""

import re
from typing import Any, Dict, Optional


PRESSURE_PIPE_MATERIAL_ALIASES = {
    "PE管": "HDPE管",
    "PCCP管": "预应力钢筒混凝土管",
    "钢筋混凝土管": "预应力钢筒混凝土管",
    "预应力钢筒混凝土管(n=0.013)": "预应力钢筒混凝土管",
    "预应力钢筒混凝土管(n=0.014)": "预应力钢筒混凝土管_n014",
    "预应力钢筒混凝土管(n=0.015)": "预应力钢筒混凝土管_n015",
}

_PCCP_MATERIAL_PATTERN = re.compile(r"^PCCP管(?:\(?N?=?(?P<roughness>0\.\d+)\)?)?$")
_PCCP_DEFAULT_MATERIAL_KEY = "预应力钢筒混凝土管"
_PCCP_ROUGHNESS_MATERIAL_KEYS = {
    "0.013": "预应力钢筒混凝土管",
    "0.014": "预应力钢筒混凝土管_n014",
    "0.015": "预应力钢筒混凝土管_n015",
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


def _material_result(
    *,
    raw_text: str,
    display_value: str,
    canonical_key: str,
    recognized: bool,
    used_default: bool,
    matched_alias: bool,
    unsupported_pccp_roughness: bool = False,
    unsupported_pccp_roughness_value: str = "",
) -> Dict[str, Any]:
    """构造统一的管材解析结果，方便调用方读取扩展标记。"""
    return {
        "raw_input": raw_text,
        "display_value": display_value,
        "canonical_key": canonical_key,
        "recognized": recognized,
        "used_default": used_default,
        "matched_alias": matched_alias,
        "unsupported_pccp_roughness": unsupported_pccp_roughness,
        "unsupported_pccp_roughness_value": unsupported_pccp_roughness_value,
    }


def _normalize_pccp_material_text(raw_text: str) -> str:
    """把 PCCP 填写中的空格和中文括号收拢，便于识别 n 值。"""
    text = str(raw_text or "").strip().upper()
    text = text.replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", "", text)


def _resolve_pccp_material(
    raw_text: str,
    material_map: Dict[str, Dict[str, Any]],
    fallback_key: str,
) -> Optional[Dict[str, Any]]:
    """解析 PCCP管 后缀 n 值；不支持的 n 值回退到 n=0.013。"""
    normalized = _normalize_pccp_material_text(raw_text)
    match = _PCCP_MATERIAL_PATTERN.match(normalized)
    if not match:
        return None

    pccp_default_key = (
        _PCCP_DEFAULT_MATERIAL_KEY
        if _PCCP_DEFAULT_MATERIAL_KEY in material_map
        else fallback_key
    )
    roughness = match.group("roughness") or "0.013"
    canonical_key = _PCCP_ROUGHNESS_MATERIAL_KEYS.get(roughness, "")
    if canonical_key in material_map:
        return _material_result(
            raw_text=raw_text,
            display_value=raw_text,
            canonical_key=canonical_key,
            recognized=True,
            used_default=False,
            matched_alias=True,
        )

    return _material_result(
        raw_text=raw_text,
        display_value=raw_text or pccp_default_key,
        canonical_key=pccp_default_key,
        recognized=False,
        used_default=True,
        matched_alias=True,
        unsupported_pccp_roughness=True,
        unsupported_pccp_roughness_value=roughness,
    )


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

    pccp_info = _resolve_pccp_material(raw_text, material_map, fallback_key)
    if pccp_info is not None:
        return pccp_info

    if raw_text in material_map:
        return _material_result(
            raw_text=raw_text,
            display_value=raw_text,
            canonical_key=raw_text,
            recognized=True,
            used_default=False,
            matched_alias=False,
        )

    display_key = display_lookup.get(raw_text, "")
    if display_key in material_map:
        return _material_result(
            raw_text=raw_text,
            display_value=raw_text,
            canonical_key=display_key,
            recognized=True,
            used_default=False,
            matched_alias=True,
        )

    alias_key = PRESSURE_PIPE_MATERIAL_ALIASES.get(raw_text, "")
    if alias_key in material_map:
        return _material_result(
            raw_text=raw_text,
            display_value=raw_text,
            canonical_key=alias_key,
            recognized=True,
            used_default=False,
            matched_alias=True,
        )

    return _material_result(
        raw_text=raw_text,
        display_value=raw_text or fallback_key,
        canonical_key=fallback_key,
        recognized=False,
        used_default=True,
        matched_alias=False,
    )


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
