"""Restore public failure locations without altering the backend evidence."""
from __future__ import annotations

from copy import deepcopy
import math
import re

from .contracts import ConstructionInputError


class TerrainSourceChanged(ConstructionInputError):
    """The bytes of an adopted terrain source or cache have changed."""


class TerrainUnavailable(ConstructionInputError):
    """No verified survey is available for the requested calculation."""


_STATIONS = ("station", "station_start", "station_end", "mid_station")
_ROLES = {"excavation": "挖方", "backfill": "周边回填", "embankment": "新增填筑",
          "concrete": "混凝土", "bedding": "垫层", "overburden":"覆盖层挖方",
          "bedrock":"基岩挖方", "unclassified_excavation":"未分层挖方"}
_REASONS = {
    "not_converged": "断面工程量复算未通过，未发布成果",
    "material_conflict": "实际材料占位冲突",
    "material_overlap_unresolved": "弯管材料部分重叠的空间归属尚不能精确解析",
    "unsupported_coupled_pipe_curve": "算法尚不支持水平圆弧与真实竖向圆弧耦合的管面剖切",
    "unsupported_pipe_curvature_radius": "算法不支持管面跨越水平曲率中心",
    "missing_profile": "缺少完整真实设计纵断面",
}


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _find_asset(assets, identifier):
    if identifier is None or identifier == "GLOBAL":
        return None, None
    matches = [a for a in assets if a.get("asset_id") == identifier]
    if not matches:
        matches = [a for a in assets if a.get("original_asset_id") == identifier]
    if len(matches) == 1:
        return matches[0], None
    return None, "ambiguous_asset_identity" if matches else "unknown_asset_identity"


def _restore_location(row, assets, prefix, basis):
    asset, issue = _find_asset(assets, row.get(prefix+"asset_id"))
    if asset is None:
        has_station = any(prefix+key in row for key in _STATIONS)
        if issue or has_station and row.get(prefix+"asset_id") != "GLOBAL":
            row[prefix+"coordinate_restoration_issue"] = issue or "unknown_asset_identity"
            row[prefix+"station_basis"] = "internal_unresolved" if basis == "internal" else "source"
        return
    row[prefix+"original_asset_id"] = asset.get("original_asset_id", asset["asset_id"])
    row[prefix+"asset_name"] = asset.get("name") or row[prefix+"original_asset_id"]
    for key in ("route_id", "route_name", "source_identity"):
        if asset.get(key) is not None:
            row[prefix+key] = deepcopy(asset[key])
    offset = _number(asset.get("station_offset", 0.))
    if offset is None:
        row[prefix+"coordinate_restoration_issue"] = "invalid_station_offset"
        row[prefix+"station_basis"] = "internal_unresolved" if basis == "internal" else "source"
        return
    for key in _STATIONS:
        field = prefix+key
        if field in row:
            value = _number(row[field])
            if value is None:
                row[prefix+"coordinate_restoration_issue"] = "invalid_station_value"
            elif basis == "internal":
                row[field] = value-offset
    row[prefix+"station_basis"] = "source"


def _location(row, prefix=""):
    identifier = row.get(prefix+"asset_id")
    if identifier == "GLOBAL":
        return "全线"
    label = str(row.get(prefix+"asset_name") or identifier or "工程")
    route = row.get(prefix+"route_name") or row.get(prefix+"route_id")
    if route:
        label += f"（线路 {route}）"
    station = _number(row.get(prefix+"station"))
    start, end = (_number(row.get(prefix+k)) for k in ("station_start", "station_end"))
    marker = "内部K" if row.get(prefix+"station_basis") == "internal_unresolved" else "K"
    if station is not None:
        label += f" {marker}{station:.6f}"
    elif start is not None and end is not None:
        label += f" {marker}{start:.6f}～{marker}{end:.6f}"
    side = row.get(prefix+"side")
    if side:
        label += "（"+{"left": "桩前侧", "right": "桩后侧"}.get(side, str(side))+"）"
    return label


def _body(row, code, fallback):
    if "difference_m3" in row and "allowed_m3" in row:
        difference, allowed = _number(row["difference_m3"]), _number(row["allowed_m3"])
        if difference is not None and allowed is not None:
            return f"{_ROLES.get(row.get('role'), row.get('role', '工程量'))}复算差 {difference:.12g}m³，允许 {allowed:.12g}m³"
    if row.get("material") and row.get("other_material"):
        return f"{_ROLES.get(row['material'],row['material'])}/{_ROLES.get(row['other_material'],row['other_material'])}占位冲突"
    message = row.get("message") or _REASONS.get(code) or fallback
    # A wrapped exact-section exception can include its internal K prefix.
    # The location above replaces it; the untouched full text remains evidence.
    match = re.match(r"^.*?\sK[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*[:：]\s*(.*)$", str(message), re.S)
    return match.group(1) if match else str(message)


def restore_workbench_diagnostics(diagnostics, prepared_assets, *, coordinate_basis="internal",
                                  asset_id=None, station=None, side=None, code=None, message=""):
    """Return new records in each asset's own source chainage, retaining raw records.

    ``source`` is required for support errors raised after successful records
    were restored. Unknown/ambiguous IDs stay explicitly internal, never guessed.
    """
    if coordinate_basis not in {"internal", "source"}:
        raise ValueError("coordinate_basis must be internal or source")
    assets = list(prepared_assets)
    raw = diagnostics if isinstance(diagnostics, (list, tuple)) else ([] if diagnostics is None else [diagnostics])
    if not raw and asset_id is not None:
        raw = [None]
    result = []
    for original in raw:
        if isinstance(original, dict) and original.get("workbench_diagnostics_restored"):
            result.append(deepcopy(original)); continue
        row = deepcopy(original) if isinstance(original, dict) else {}
        row["backend_diagnostic"] = deepcopy(original)
        if original is None:
            row["diagnostic_origin"] = "public_query_context"
        elif not isinstance(original, dict):
            row["message"] = str(original)
        if row.get("asset_id") is None and asset_id is not None:
            row["asset_id"] = asset_id
        if row.get("station") is None and station is not None and not any(k in row for k in ("station_start", "station_end")):
            row["station"] = station
        if row.get("side") is None and side is not None:
            row["side"] = side
        _restore_location(row, assets, "", coordinate_basis)
        _restore_location(row, assets, "other_", coordinate_basis)
        body = _body(row, code, message)
        label = _location(row)
        if row.get("other_asset_id") is not None:
            label += " 与 "+_location(row, "other_")
        row["message"] = label+"："+body
        row["backend_station_basis"] = coordinate_basis
        row["workbench_diagnostics_restored"] = True
        result.append(row)
    return result


def restore_workbench_error(error, prepared_assets, *, coordinate_basis="internal",
                             asset_id=None, station=None, side=None):
    """Return the same exception/type/code with public text and copied diagnostics.

    No constructor is called, so specialized exceptions keep their attributes,
    traceback and cause. Shared convergence-history checks are never mutated.
    """
    if getattr(error, "workbench_diagnostics_restored", False):
        return error
    error.backend_message = str(error)
    error.backend_args = deepcopy(error.args)
    error.backend_diagnostics = deepcopy(getattr(error, "diagnostics", None))
    error.backend_station_basis = coordinate_basis
    restored = restore_workbench_diagnostics(error.backend_diagnostics, prepared_assets,
        coordinate_basis=coordinate_basis, asset_id=asset_id, station=station, side=side,
        code=getattr(error, "code", None), message=error.backend_message)
    error.diagnostics = restored
    if restored:
        texts = list(dict.fromkeys(item["message"] for item in restored))
        reason = _REASONS.get(getattr(error, "code", None))
        error.args = ((reason+"；" if reason else "")+"；".join(texts[:3]),)
    error.workbench_diagnostics_restored = True
    return error
