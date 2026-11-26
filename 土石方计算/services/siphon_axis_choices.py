"""Choose a construction longitudinal profile for each inverted siphon."""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path

from .design_profiles import (
    DesignProfileError,
    clip_design_profile,
    evaluate_profile,
    normalize_design_profile,
    profile_break_stations,
    sync_bound_axis_controls,
)


DEFAULT_SIPHON_COVER_M = 2.0
SIPHON_AXIS_MODES = {"auto", "exact", "align_start", "align_end", "cover_depth", "pending"}
_ROUNDING_M = .001
_UNITS = {"m": 1., "mm": .001, "cm": .01, "in": .0254, "ft": .3048}
_COVER_AXIS = "terrain_and_user_cover_depth"
_SOURCE_LABELS = {
    "water_profile": "水面线专项纵断面",
    "quantity_dxf": "算量导入DXF",
    "quantity_input": "算量纵断面",
}


def is_siphon_axis_asset(asset):
    if asset.get("kind") == "siphon" or asset.get("source_type") == "倒虹吸":
        return True
    if asset.get("kind") in {"pipe", "pressure_pipe"} or asset.get("source_type") == "有压管道":
        return False
    return asset.get("section_type") == "circular_siphon"


def siphon_source_boundary(asset):
    """Identify the same siphon before and after a specialist profile is saved."""
    if is_siphon_axis_asset(asset):
        rows = (asset.get("original_fields") or {}).get("records") or []
        if len(rows) >= 2:
            endpoints = (rows[0].get("profile_row_id"), rows[-1].get("profile_row_id"))
            if all(endpoints) and endpoints[0] != endpoints[1]:
                return endpoints
    return None


def _normalized_source(profile, units):
    reference = profile.get("reference") if isinstance(profile, dict) else None
    if reference and reference not in {"pipe_axis", "common_outer_bottom", "inner_invert"}:
        raise DesignProfileError("纵断面高程基准须为管中心、共同外管底或净内底", code="invalid_profile_reference")
    result = normalize_design_profile(profile, reference=reference or "pipe_axis")
    factor = _UNITS[units]
    if factor != 1.:
        for element in result["elements"]:
            for field in ("station_start", "station_end", "z_start", "center_station", "center_elevation", "radius"):
                if field in element:
                    element[field] *= factor
        result = normalize_design_profile(result)
    return result


def _station_range(asset):
    try:
        start, end = float(asset["station_start"]), float(asset["station_end"])
        if math.isfinite(start) and math.isfinite(end) and end > start:
            return [start, end]
    except (KeyError, TypeError, ValueError):
        pass
    return None


def _legacy_source(asset):
    construction = asset.get("construction") or {}
    if asset.get("axis_source") == _COVER_AXIS or construction.get("burial_mode") == "cover_depth":
        return None
    raw = asset.get("design_profile")
    if not raw:
        return None
    try:
        profile = _normalized_source(raw, "m")
    except (TypeError, ValueError, KeyError):
        return None
    source = deepcopy(asset.get("profile_source_file") or {})
    identity = str(asset.get("source_identity") or "")
    if asset.get("axis_source") == "water_profile_real_elevation" or (
            identity.startswith("siphon:") and not asset.get("axis_source") and not source):
        source.update(kind="water_profile", siphon_key=identity.removeprefix("siphon:"))
    else:
        source.setdefault("kind", "quantity_dxf" if source.get("path") else "quantity_input")
    return {"profile": deepcopy(profile), "source": source, "source_units": "m", "station_offset_m": None}


def describe_siphon_axis(asset):
    """Describe the object preference and current source using plain project fields."""
    stored = asset.get("siphon_axis_choice") or {}
    source = asset.get("siphon_axis_input") or _legacy_source(asset) or {}
    provenance = deepcopy(source.get("source") or {})
    profile = source.get("profile") or {}
    asset_range = _station_range(asset)
    native_range = [profile["station_start"], profile["station_end"]] if profile else None
    construction = asset.get("construction") or {}
    mode = stored.get("mode", "auto")
    status = stored.get("status", "actual" if profile else "cover_estimate")
    if construction.get("burial_mode") == "cover_depth" and status in {"actual", "aligned"}:
        mode, status = "cover_depth", "cover_estimate"
    if status == "cover_estimate" and asset.get("axis_source") == _COVER_AXIS and asset.get("design_profile"):
        status = "cover_generated"
    depth = construction.get("cover_depth")
    return {
        "mode": mode, "status": status, "source": provenance,
        "source_label": provenance.get("label") or _SOURCE_LABELS.get(provenance.get("kind"), "缺少纵断面"),
        "cover_depth_m": DEFAULT_SIPHON_COVER_M if depth is None else float(depth),
        "axis_station_range_m": native_range, "asset_station_range_m": asset_range,
        "length_difference_m": ((native_range[1] - native_range[0]) - (asset_range[1] - asset_range[0])
                                if native_range and asset_range else None),
        "adjustment": deepcopy(stored.get("adjustment") or {}),
        "message": stored.get("message", ""),
    }


def _cover_depth(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("管顶覆土须为有限非负数") from exc
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError("管顶覆土须为有限非负数")
    return numeric


def _map_axis(profile, bounds, mode, prescribed_offset):
    start, end = bounds
    a, b = profile["station_start"], profile["station_end"]
    covers = a <= start + _ROUNDING_M and b >= end - _ROUNDING_M
    length_matches = abs((b - a) - (end - start)) <= _ROUNDING_M
    if mode == "align_end":
        offset, strategy = end - b, mode
    elif mode == "align_start":
        offset, strategy = start - a, mode
    elif prescribed_offset is not None:
        offset, strategy = prescribed_offset, "manual_offset"
    elif covers:
        offset, strategy = 0., "source_chainage"
    elif length_matches:
        offset, strategy = start - a, "matching_length"
    elif mode == "auto":
        offset, strategy = start - a, "align_start"
    else:
        raise DesignProfileError("轴线桩号未覆盖施工区段，可选择起点或终点对齐",
                                 code="siphon_axis_station_mismatch")

    mapped = deepcopy(profile["elements"])
    for element in mapped:
        for field in ("station_start", "station_end", "center_station"):
            if field in element:
                element[field] += offset
    a, b = mapped[0]["station_start"], mapped[-1]["station_end"]
    if a >= end or b <= start:
        raise DesignProfileError("对齐后的纵断面与施工区段没有重合",
                                 code="siphon_axis_station_mismatch")
    extend_start, extend_end = max(0., a - start), max(0., end - b)
    if mode == "exact" and max(extend_start, extend_end) > _ROUNDING_M:
        raise DesignProfileError("轴线桩号未覆盖施工区段，可选择起点或终点对齐",
                                 code="siphon_axis_station_mismatch")
    if extend_start:
        z, slope = evaluate_profile(profile, profile["station_start"])
        mapped.insert(0, {"kind": "line", "station_start": start, "station_end": a,
                          "z_start": z - slope * extend_start, "slope": slope})
    if extend_end:
        z, slope = evaluate_profile(profile, profile["station_end"], "left")
        mapped.append({"kind": "line", "station_start": b, "station_end": end,
                       "z_start": z, "slope": slope})
    adjustment = {
        "strategy": strategy, "station_offset_m": offset,
        "extend_start_m": extend_start, "extend_end_m": extend_end,
        "trim_start_m": max(0., start - a), "trim_end_m": max(0., b - end),
    }
    return clip_design_profile({"reference": profile["reference"], "elements": mapped}, start, end), adjustment


def _clear_active_axis(asset):
    for key in ("design_profile", "profile_points", "axis_source", "profile_source",
                "profile_source_file", "profile_import_mapping", "cover_preview_confirmed",
                "axis_cover_samples", "axis_preview_sha256", "cover_confirmation",
                "cover_generation_options", "cover_actual_cover_summary"):
        asset.pop(key, None)
    asset.setdefault("alignment", {}).pop("profile_points", None)
    asset["construction"].pop("axis_confirmed", None)


def configure_siphon_axis(asset, *, mode, cover_depth_m=None, profile=None, source=None,
                          source_units="m", station_offset=None, strict=False):
    """Apply one preference to an editable asset and preserve its unshifted source."""
    if not is_siphon_axis_asset(asset):
        raise ValueError("请选择倒虹吸")
    if mode not in SIPHON_AXIS_MODES:
        raise ValueError("请选择倒虹吸纵断面处理方式")
    if source_units not in _UNITS:
        raise ValueError("纵断面坐标单位无效")
    if station_offset is not None:
        station_offset = float(station_offset)
        if not math.isfinite(station_offset):
            raise ValueError("纵断面桩号平移量须为有限值")
    construction = asset.get("construction") or {}
    requested_depth = construction.get("cover_depth") if cover_depth_m is None else cover_depth_m
    depth = _cover_depth(DEFAULT_SIPHON_COVER_M if requested_depth is None else requested_depth)
    axis = deepcopy(asset.get("siphon_axis_input") or _legacy_source(asset) or {})
    source_error = None
    if profile is not None:
        axis = {"source": deepcopy(source or {"kind": "quantity_input"}), "source_units": source_units,
                "station_offset_m": station_offset}
        try:
            axis["profile"] = _normalized_source(profile, source_units)
        except (ValueError, TypeError, KeyError) as exc:
            axis["error"] = source_error = str(exc)
    elif source is not None and not axis:
        axis = {"source": deepcopy(source)}

    active = None
    adjustment = {}
    status, message = "pending", ""
    raw = axis.get("profile")
    if mode == "pending":
        message = "本次倒虹吸纵断面待补"
    elif mode == "cover_depth" or (mode == "auto" and not raw):
        status = "cover_estimate"
        previous_error = axis.get("error")
        if previous_error:
            message = f"{previous_error}；现按管顶覆土{depth:g}m估算"
        else:
            message = f"按管顶覆土{depth:g}m估算"
    elif not raw:
        message = axis.get("error") or "缺少纵断面轴线"
    elif _station_range(asset) is None:
        message = "缺少实际平面施工起止桩号"
    else:
        try:
            active, adjustment = _map_axis(raw, _station_range(asset), mode, axis.get("station_offset_m"))
        except (ValueError, TypeError, KeyError) as exc:
            status, message = "mismatch", str(exc)
        else:
            start_delta = adjustment["extend_start_m"] + adjustment["trim_start_m"]
            end_delta = adjustment["extend_end_m"] + adjustment["trim_end_m"]
            status = "aligned" if max(start_delta, end_delta) > _ROUNDING_M else "actual"
            if status == "aligned" or abs(adjustment["station_offset_m"]) > _ROUNDING_M:
                message = {"align_start": "起点对齐", "align_end": "终点对齐", "manual_offset": "按指定起桩对齐",
                           "matching_length": "平移等长轴线", "source_chainage": "按原桩号裁取"}[adjustment["strategy"]]
                if max(adjustment["extend_start_m"], adjustment["extend_end_m"]) > _ROUNDING_M:
                    message += "，未覆盖端按末端切线延伸"
    if strict and (source_error or status in {"pending", "mismatch"}):
        raise DesignProfileError(source_error or message, code="siphon_axis_station_mismatch")

    keep_cover = (status == "cover_estimate" and construction.get("burial_mode") == "cover_depth"
                  and construction.get("cover_depth") == depth and asset.get("axis_source") == _COVER_AXIS)
    construction = asset.setdefault("construction", {})
    if cover_depth_m is not None and construction.get("cover_depth") != depth:
        construction.pop("cover_segments", None)
    if not keep_cover:
        _clear_active_axis(asset)
    asset.pop("calculation_deferred", None)
    construction.update(cover_depth=depth, burial_mode="cover_depth" if status == "cover_estimate" else "actual_axis")
    if active is not None:
        points = [{"station": s, "elevation": evaluate_profile(active, s)[0]} for s in profile_break_stations(active)]
        provenance = axis.get("source") or {}
        source_kind = "water_profile_real_elevation" if provenance.get("kind") == "water_profile" else "user_input_real_elevation"
        asset.update(design_profile=active, profile_points=points, axis_source=source_kind,
                     profile_source=source_kind, cover_preview_confirmed=True)
        asset.setdefault("alignment", {}).update(profile_points=deepcopy(points), elevation_reference=active["reference"])
        construction["axis_confirmed"] = True
        asset["profile_import_mapping"] = {**adjustment, "source_units": axis.get("source_units", "m"),
            "source_station_range_m": [raw["station_start"], raw["station_end"]],
            "selected_station_range_m": _station_range(asset), "reference": active["reference"],
            "mapping_basis": message or "采用来源纵断面桩号"}
        if provenance.get("path"):
            file_details = {key: deepcopy(value) for key, value in provenance.items() if key != "path"}
            file_details.setdefault("filename", Path(provenance["path"]).name)
            asset["profile_source_file"] = {**file_details, **asset["profile_import_mapping"]}
    missing = [item for item in asset.get("missing_fields", []) if item != "design_profile"]
    if not asset.get("design_profile"):
        missing.append("design_profile")
    asset["missing_fields"] = missing
    asset["siphon_axis_choice"] = {"mode": mode, "status": status, "adjustment": adjustment, "message": message}
    if axis:
        asset["siphon_axis_input"] = axis
    sync_bound_axis_controls(asset)
    return describe_siphon_axis(asset)


def refresh_siphon_axis_choices(inputs, previous_inputs):
    """Reapply saved choices to the latest main-project plan and embedded axes."""
    previous = {
        (network.get("source_identity") or network.get("network_id"), asset.get("asset_id")): asset
        for network in previous_inputs.get("networks", []) for asset in network.get("assets", [])
        if is_siphon_axis_asset(asset)
    }
    old_boundaries = {}
    for asset in previous.values():
        boundary = siphon_source_boundary(asset)
        if boundary:
            old_boundaries.setdefault(boundary, []).append(asset)
    current_boundaries = {}
    for network in inputs.get("networks", []):
        for asset in network.get("assets", []):
            boundary = siphon_source_boundary(asset)
            if boundary:
                current_boundaries[boundary] = current_boundaries.get(boundary, 0) + 1
    for network in inputs.get("networks", []):
        route = network.get("source_identity") or network.get("network_id")
        for asset in network.get("assets", []):
            if not is_siphon_axis_asset(asset):
                continue
            old = previous.get((route, asset.get("asset_id")))
            if old is not None and old.get("source_identity") != asset.get("source_identity"):
                old = None
            if old is None:
                boundary = siphon_source_boundary(asset)
                matches = old_boundaries.get(boundary, [])
                if current_boundaries.get(boundary) == 1 and len(matches) == 1:
                    old = matches[0]
            if old is None:
                continue
            state = describe_siphon_axis(old)
            old_input = old.get("siphon_axis_input") or _legacy_source(old)
            if old_input and (old_input.get("source") or {}).get("kind") != "water_profile":
                asset["siphon_axis_input"] = deepcopy(old_input)
            configure_siphon_axis(asset, mode=state["mode"], cover_depth_m=state["cover_depth_m"])
