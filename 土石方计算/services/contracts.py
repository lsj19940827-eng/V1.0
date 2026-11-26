# -*- coding: utf-8 -*-
"""Rhino 挖填联动的纯数据合同；不导入界面或地形计算器。"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

SCHEMA_VERSION = "1.0"
SECTION_TYPES = frozenset({
    "trapezoidal_channel", "rectangular_channel", "u_channel",
    "compound_trapezoidal_channel", "circular_culvert", "rectangular_culvert",
    "arch_culvert", "circular_siphon", "circular_channel", "box_foundation",
})


class ConstructionInputError(ValueError):
    """输入不足或相互矛盾，不能准备施工实体。"""


def finite_number(value: Any, field: str) -> float:
    """拒绝空值、布尔值和非有限值，不把缺失高程补成零。"""
    if value is None or isinstance(value, bool) or value == "":
        raise ConstructionInputError(f"缺少有效参数：{field}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConstructionInputError(f"参数 {field} 必须为数值") from exc
    if not math.isfinite(number):
        raise ConstructionInputError(f"参数 {field} 必须为有限数值")
    return number


def content_hash(value: Any) -> str:
    """对可传输输入生成稳定摘要，拒绝 NaN 和无限值。"""
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_snapshot(snapshot: dict) -> dict:
    """返回可展示问题，不替代 Rhino 对闭合体和布尔结果的验证。"""
    issues = []
    def error(path: str, message: str) -> None:
        issues.append({"severity": "error", "path": path, "message": message})
    for key in ("project_id", "snapshot_id", "input_hash", "revisions",
                "coordinate_reference", "terrain", "assets", "settings"):
        if key not in snapshot:
            error(key, "缺少快照字段")
    if snapshot.get("schema", snapshot.get("schema_version")) != SCHEMA_VERSION:
        error("schema", "仅支持快照版本 1.0")
    coordinate_reference = snapshot.get("coordinate_reference")
    if not isinstance(coordinate_reference, dict):
        error("coordinate_reference", "UNSUPPORTED_UNITS：coordinate_reference 必须为含 units='m' 的对象")
    elif "units" not in coordinate_reference:
        error("coordinate_reference.units", "UNSUPPORTED_UNITS：缺少单位；必须明确指定米制单位 'm'")
    elif not isinstance(coordinate_reference["units"], str):
        error("coordinate_reference.units", "UNSUPPORTED_UNITS：单位必须为字符串 'm'")
    elif coordinate_reference["units"] != "m":
        error("coordinate_reference.units", "UNSUPPORTED_UNITS：仅接受米制单位 'm'，当前不提供单位换算")
    assets = snapshot.get("assets", [])
    if not isinstance(assets, list) or not assets:
        error("assets", "至少需要一个施工对象")
        assets = []
    identifiers = set()
    for index, asset in enumerate(assets):
        prefix = f"assets[{index}]"
        if not isinstance(asset, dict):
            error(prefix, "施工对象必须为字典")
            continue
        identifier = asset.get("asset_id")
        if not identifier or identifier in identifiers:
            error(prefix + ".asset_id", "对象标识为空或重复")
        identifiers.add(identifier)
        if not asset.get("enabled", True):
            continue
        if asset.get("section_type") not in SECTION_TYPES:
            error(prefix + ".section_type", "不支持的施工断面")
        sections = asset.get("geometry_sections", [])
        if len(sections) < 2:
            error(prefix + ".geometry_sections", "至少需要两个已准备的施工断面")
        previous = None
        for section_index, section in enumerate(sections):
            section_path = f"{prefix}.geometry_sections[{section_index}]"
            try:
                station = finite_number(section.get("station"), section_path + ".station")
                if previous is not None and station <= previous:
                    error(section_path, "施工断面桩号必须严格递增")
                previous = station
                for field in ("origin", "tangent", "lateral", "up"):
                    values = section.get(field, [])
                    if len(values) != 3:
                        error(section_path + "." + field, "必须是三个数值")
                    for value in values:
                        finite_number(value, section_path + "." + field)
                for field in ("excavation", "target", "permanent", "measured", "open_air", "domain"):
                    for ring in section.get(field, []):
                        if len(ring) < 4 or ring[0] != ring[-1]:
                            error(section_path + "." + field, "轮廓必须显式闭合")
                        for point in ring:
                            if len(point) != 2:
                                error(section_path + "." + field, "断面点必须为偏距与绝对高程")
                            for value in point:
                                finite_number(value, section_path + "." + field)
            except (ConstructionInputError, TypeError) as exc:
                error(section_path, str(exc))
    try:
        content_hash(snapshot)
    except (ValueError, TypeError):
        error("snapshot", "快照含不可序列化或非有限数值")
    return {"valid": not issues, "issues": issues}
