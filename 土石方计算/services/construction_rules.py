"""Construction rules shared by imports, editors and calculation boundaries."""
from __future__ import annotations

U_CHANNEL_NO_BEDDING_RULE = "u_channel_no_bedding_v1"
CIRCULAR_CULVERT_RESTORE_RULE = "circular_culvert_restore_terrain_v1"
BEDDING_FIELDS = ("bedding_thickness", "bedding_extension")
U_ANGLE_DEFAULTS = {"section.u_arc_angle_degrees": 180.0, "section.u_side_angle_degrees": 0.0}


def side_wall_thickness(section, side):
    value = section.get("wall_thickness_" + side)
    return section.get("wall_thickness") if value is None else value


def structural_lining_thicknesses(asset):
    if asset is None:
        return {}
    section = asset.get("section") or {}
    base = section.get("base_thickness")
    if asset.get("section_type") == "u_channel" and section.get("u_bottom_thickness") is not None:
        base = section["u_bottom_thickness"]
    uniform = section.get("wall_thickness") if asset.get("section_type") == "circular_culvert" else None
    return {"base_thickness": uniform if base is None else base,
            "wall_thickness_left": side_wall_thickness(section, "left"),
            "wall_thickness_right": side_wall_thickness(section, "right"),
            "roof_thickness": section.get("roof_thickness")}


def validate_u_angle(path, value):
    if path == "section.u_arc_angle_degrees" and not 0 < value <= 360:
        raise ValueError("U形底圆弧圆心角须大于0°且不超过360°")
    if path == "section.u_side_angle_degrees" and not 0 <= value < 90:
        raise ValueError("U形直墙外倾角须大于等于0°且小于90°")


def is_circular_culvert(asset):
    """The hydraulic form 明渠-圆形 denotes a closed, buried round culvert.

    Keep tunnels and pressure-pipe/siphon installation choices independent.
    Historical imports used circular_channel for the same hydraulic form.
    """
    if asset.get("kind") in {"tunnel", "pipe", "pressure_pipe", "siphon"}:
        return False
    return asset.get("section_type") == "circular_culvert" or (
        asset.get("section_type") == "circular_channel" and asset.get("source_type") == "明渠-圆形")


def bedding_applicable(asset_or_type):
    section_type = asset_or_type.get("section_type") if isinstance(asset_or_type, dict) else asset_or_type
    return section_type != "u_channel"


def normalized_construction(section_type, construction):
    """Return effective parameters; U-channel structural lining stays intact."""
    result = dict(construction or {})
    if not bedding_applicable(section_type):
        result.update(bedding_thickness=0.0, bedding_extension=0.0)
    return result


def effective_construction(asset):
    result = normalized_construction(asset.get("section_type"), asset.get("construction"))
    if is_circular_culvert(asset) and result.get("target_mode") in {None, "union_terrain"}:
        result["target_mode"] = "restore_terrain"
    if asset.get("replacement_parameter_modes"):
        from .replacement_geometry import effective_replacement
        result = effective_replacement(asset, result)
    return result


def _normalize_circular_culvert(asset):
    if not is_circular_culvert(asset):
        return None
    old = dict(asset.get("construction") or {})
    previous_type, previous_kind = asset.get("section_type"), asset.get("kind")
    alias = previous_type == "circular_channel"
    changed = old.get("target_mode") in {None, "union_terrain"}
    if not alias and not changed:
        return None
    if alias:
        asset.update(section_type="circular_culvert", kind="culvert")
    asset["construction"] = effective_construction(asset)
    if changed:
        asset.setdefault("parameter_sources", {})["construction.target_mode"] = (
            "施工规则：圆管涵（程序结构形式：明渠-圆形）安装后回填至原地面")
        asset["missing_fields"] = [field for field in asset.get("missing_fields", [])
                                   if field != "construction.target_mode"]
    stale = bool(asset.get("geometry_sections"))
    if stale:
        asset["geometry_sections"] = []
    return {"code": CIRCULAR_CULVERT_RESTORE_RULE, "rule": CIRCULAR_CULVERT_RESTORE_RULE,
            "asset_id": asset.get("asset_id"), "name": asset.get("name"),
            "section_type": "circular_culvert",
            "previous": {"section_type": previous_type, "kind": previous_kind,
                         "target_mode": old.get("target_mode")},
            "current": {"section_type": asset["section_type"], "kind": asset.get("kind"),
                        "target_mode": asset["construction"].get("target_mode")},
            "prepared_geometry_invalidated": stale, "requires_recalculation": True}


def normalize_asset_construction(asset):
    """Normalize one live input in place; return a migration record if changed.

    Source snapshots remain in original_fields. Returned records let project
    loaders invalidate saved quantities and explain the one-time migration.
    """
    from .pipe_dimensions import normalize_pipe_dimensions
    normalize_pipe_dimensions(asset)
    circular = _normalize_circular_culvert(asset)
    if circular:
        return circular
    if bedding_applicable(asset):
        return None
    old = dict(asset.get("construction") or {})
    changed = any(old.get(key) != 0.0 for key in BEDDING_FIELDS)
    asset["construction"] = effective_construction(asset)
    asset["missing_fields"] = [field for field in asset.get("missing_fields", [])
                               if field not in {"construction." + key for key in BEDDING_FIELDS}]
    sources = asset.setdefault("parameter_sources", {})
    for key in BEDDING_FIELDS:
        sources["construction." + key] = "施工规则：U形明渠不设垫层；保留结构底板及底弧衬砌"
    prepared = asset.get("geometry_sections") or []
    stale_prepared = bool(prepared) and (changed or any(
        isinstance(section, dict) and bool(section.get("measured")) for section in prepared))
    if not changed and not stale_prepared:
        return None
    # Old prepared sections may contain a lower trench floor and bedding
    # polygons. They must be regenerated from the unchanged structural section.
    if stale_prepared:
        asset["geometry_sections"] = []
    return {"code": U_CHANNEL_NO_BEDDING_RULE, "rule": U_CHANNEL_NO_BEDDING_RULE,
            "asset_id": asset.get("asset_id"), "name": asset.get("name"),
            "section_type": "u_channel", "previous": {key: old.get(key) for key in BEDDING_FIELDS},
            "current": {key: 0.0 for key in BEDDING_FIELDS},
            "prepared_geometry_invalidated": stale_prepared, "requires_recalculation": True}


def normalize_construction_inputs(value):
    """Normalize live asset/network collections in place, returning migrations."""
    changes = []
    if isinstance(value, list):
        for item in value:
            changes.extend(normalize_construction_inputs(item))
    elif isinstance(value, dict):
        if value.get("section_type"):
            record = normalize_asset_construction(value)
            if record:
                changes.append(record)
        # Do not traverse original_fields, source snapshots or stored results.
        for key in ("assets", "networks", "pits", "workbench", "workbench_inputs", "network", "inputs", "independent"):
            nested = value.get(key)
            if isinstance(nested, (dict, list)):
                changes.extend(normalize_construction_inputs(nested))
    return changes
