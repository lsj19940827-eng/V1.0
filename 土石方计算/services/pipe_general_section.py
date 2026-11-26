"""Read and edit the ordinary excavation sections of selected pipe objects."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from .contracts import ConstructionInputError
from .construction_rules import normalize_asset_construction
from .default_section_schemes import _general_fields, default_section_scheme, needs_default_section_scheme
from .pipe_batch_parameters import _merged_settings, _spec_parts
from .pipe_construction_defaults import (
    DEFAULT_MANUAL_BACKFILL_HEIGHT_M, PIPE_BACKFILL_HEIGHT_PATH, apply_pipe_construction_defaults,
)
from .pipe_dimensions import (
    CONSTRUCTION_WALL, MATERIAL_OUTER, construction_pipe_dimension_values, normalize_pipe_dimensions,
)
from .section_geometry import pipe_specs
from .section_scheme_bindings import (
    _digest, _get, _overrides, _root, _route, _set, apply_section_scheme, draft_section_scheme_fields,
)
from .section_scheme_catalog import load_section_schemes
from .special_pipe_materials import (
    KEY, _binding_scheme, _eligible, _number, _special, _specification, list_special_material_groups,
    validate_length_material_rows,
)


_PIPE_COUNT = "section.pipe_count"
_PIPE_SPACING = "section.pipe_spacing"
_TARGET_MODE = "construction.target_mode"
_FINISH_DEPTH = "construction.final_cover_depth"
_FINISH_FIELDS = (
    "target_mode", "final_cover_depth", "target_profile",
    "bank_top_width_left", "bank_top_width_right",
    "bank_slope_left", "bank_slope_right", "bank_stages_left", "bank_stages_right",
)


def _ordinary(asset):
    return _eligible(asset) and not _special(asset) and asset.get("pipe_profile_choice") != "pending_gap"


def _part_key(network, asset):
    return _route(network), _root(asset), asset.get("station_start"), asset.get("station_end")


def _default_draft(asset, scheme):
    part = deepcopy(asset)
    if _get(part, "section.outer_diameter") is None:
        try:
            diameters = {pipe['outer_diameter'] for pipe in pipe_specs(part.get("section") or {})}
            if len(diameters) == 1:
                _set(part, "section.outer_diameter", diameters.pop())
        except ValueError:
            pass
    existing_depth = _get(part, "construction.bedding_thickness")
    had_seat_depth = _get(part, "construction.pipe_seat.base_thickness") is not None
    apply_pipe_construction_defaults(part, support_mode="sand_bedding")
    if existing_depth is not None and not had_seat_depth:
        _set(part, "construction.pipe_seat.base_thickness", existing_depth)
    inherited = _general_fields(part, scheme)
    return draft_section_scheme_fields(part, scheme, inherited)[0], inherited


def general_section_groups(inputs, member_identities):
    """Use the adopted section when present and prepare unbound defaults in memory."""
    members = set(member_identities)
    groups = {}
    schemes = None
    for network in inputs.get("networks", ()):
        for asset in network.get("assets", ()):
            key = _part_key(network, asset)
            if key[:2] not in members or key[2] is None or key[3] is None or not _ordinary(asset):
                continue
            part = deepcopy({key: value for key, value in asset.items() if key != "geometry_sections"})
            normalize_asset_construction(part)
            scheme = _binding_scheme(part)
            if not scheme and needs_default_section_scheme(part):
                if schemes is None:
                    schemes = load_section_schemes()
                scheme = default_section_scheme(part, schemes) or {}
                if scheme:
                    part, _ = _default_draft(part, scheme)
            specification = _specification(part)
            split_height = _get(part, PIPE_BACKFILL_HEIGHT_PATH)
            specification["general_construction"]["backfill_height_m"] = (
                DEFAULT_MANUAL_BACKFILL_HEIGHT_M if split_height is None else split_height
            )
            for field in ("excavation_stages_left", "excavation_stages_right", "excavation_layer_mode",
                          *_FINISH_FIELDS):
                value = _get(part, "construction." + field)
                if value is not None:
                    specification["general_construction"][field] = value
            identity = _digest([scheme.get("scheme_id"), specification])
            group = groups.setdefault(identity, {"id": identity, "scheme": scheme, "asset": part, "spans": []})
            group["spans"].append((key, str(asset.get("asset_id") or key[1]), network.get("station_prefix") or "K"))
    for group in groups.values():
        group["spans"].sort(key=lambda span: (span[0][2], span[0][3], span[0][0]))
    return sorted(groups.values(), key=lambda group: group["spans"][0][0][2])


def _parameter_updates(updates):
    result = {}
    for path, value in updates.items():
        if path == _TARGET_MODE:
            if value not in ("restore_terrain", "cover_depth"):
                raise ConstructionInputError("请选择恢复原地面或按指定覆土填筑。")
        elif path == _PIPE_SPACING and isinstance(value, (list, tuple)):
            value = [_number(gap, "相邻管净距") for gap in value]
        elif not (path.endswith(".outer_diameter") and value is None):
            value = _number(value, path, positive=(
                path.endswith(".support_angle") or path.startswith("section.")
                and path != _PIPE_SPACING and not path.endswith("." + CONSTRUCTION_WALL)))
            if path == _PIPE_COUNT:
                if not value.is_integer():
                    raise ConstructionInputError("管数须为正整数。")
                value = int(value)
        result[path] = value
    return result


def _dimension_updates(asset, updates):
    section = asset.get("section") or {}
    pipes = section.get("pipes") or []
    prefixes = [f"section.pipes[{index}]" for index in range(1, len(pipes) + 1)] or ["section"]
    edits = dict(updates)
    if not any(path.startswith("section.") for path in edits):
        return edits
    for prefix, sizes in zip(prefixes, construction_pipe_dimension_values(asset), strict=True):
        dn_path = prefix + ".nominal_diameter_m"
        wall_path = prefix + "." + CONSTRUCTION_WALL
        outer_path = prefix + ".outer_diameter"
        material_path = prefix + "." + MATERIAL_OUTER
        restore_formula = outer_path in edits and edits[outer_path] is None
        if dn_path in edits or wall_path in edits or restore_formula:
            if outer_path in edits and not restore_formula:
                raise ConstructionInputError("施工外径与公称直径、壁厚请分别保存。")
            edits[dn_path] = _number(edits.get(dn_path, sizes["nominal_diameter_m"]), "公称直径", positive=True)
            edits[wall_path] = _number(edits.get(wall_path, sizes[CONSTRUCTION_WALL]), "施工壁厚")
            if sizes[MATERIAL_OUTER] is not None:
                edits[material_path] = sizes[MATERIAL_OUTER]
            if any(outer_path in (asset.get(key) or {}) for key in
                   ("drawing_user_overrides", "section_scheme_user_overrides")):
                edits[outer_path] = None
        elif outer_path in edits and _get(asset, wall_path) is not None:
            edits[wall_path] = None
            edits[material_path] = None
    return edits


def _layout_updates(asset, edits):
    section = asset.get("section") or {}
    pipes = section.get("pipes") or []
    indexed = {path for path in edits if path.startswith("section.pipes[")}
    if _PIPE_COUNT not in edits and _PIPE_SPACING not in edits and not indexed:
        return edits
    old_count = len(pipes) if pipes else _number(section.get("pipe_count", 1), "管数", positive=True)
    count = edits.get(_PIPE_COUNT, old_count)
    layout_changed = count != old_count or _PIPE_SPACING in edits
    spacing = edits.get(_PIPE_SPACING, section.get("pipe_spacing"))
    if layout_changed and count == 1 and isinstance(spacing, list) and _PIPE_SPACING not in edits:
        spacing = edits[_PIPE_SPACING] = []
    if layout_changed:
        if count > 1 and spacing is None:
            raise ConstructionInputError("请填写相邻管净距。")
        if isinstance(spacing, list) and len(spacing) != count - 1:
            raise ConstructionInputError(f"{count:g} 根管须填写一个统一净距或 {count-1:g} 个相邻净距。")
    if not pipes:
        return edits

    spacing_controlled = asset.get("cover_pipe_layout_mode") == "spacing"
    reflow_offsets = layout_changed or bool(indexed and spacing_controlled and any(
        row.get("offset") is not None for row in pipes))
    retained = _overrides(asset) if reflow_offsets or indexed else {}
    if not reflow_offsets and not (indexed and "section.pipes" in retained):
        return edits

    # Keep existing individual pipe properties. A changed count extends the
    # last specification, and edited clearances define the new lateral layout.
    section = _edited_general_section(asset, edits)["section"]
    rows = section["pipes"][:int(count)]
    rows.extend(deepcopy(rows[-1]) for _ in range(int(count) - len(rows)))
    if reflow_offsets:
        have_offsets = any(row.get("offset") is not None for row in rows)
        for row in rows:
            row.pop("offset", None)
        if have_offsets and not spacing_controlled:
            placed = pipe_specs({**section, "pipes": rows})
            for row, pipe in zip(rows, placed, strict=True):
                row["offset"] = pipe["offset"]
    result = {path: value for path, value in edits.items() if path not in indexed}
    # Whole-list edits supersede the corresponding per-pipe overrides, which
    # could otherwise resurrect a removed pipe on reload or scheme replay.
    result.update({path: None for path in retained if path.startswith("section.pipes[")})
    result["section.pipes"] = rows
    return result


def rebase_pipe_layout(asset, previous, overrides):
    """Carry an edited arrangement onto the current source pipe dimensions."""
    rows = overrides.get("section.pipes")
    if not rows or not {_PIPE_COUNT, _PIPE_SPACING}.intersection(overrides):
        return overrides
    saved = previous.get("section_scheme_source_values", {}).get("section.pipes", {})
    original_rows = saved.get("value")
    section = asset.get("section") or {}
    source_rows = section.get("pipes") or [section]
    if not original_rows:
        return overrides
    rows = deepcopy(rows)
    for index, row in enumerate(rows):
        old = original_rows[min(index, len(original_rows) - 1)]
        new = source_rows[min(index, len(source_rows) - 1)]
        for field in ("inner_diameter", "hydraulic_inner_diameter_m", "nominal_diameter_m", "outer_diameter"):
            old_value = old.get(field, old.get("inner_diameter"))
            new_value = new.get(field, new.get("inner_diameter", section.get(field)))
            if row.get(field) == old_value and new_value is not None:
                row[field] = new_value
    if rows == overrides["section.pipes"]:
        return overrides
    candidate = {"kind": asset.get("kind"), "section_type": asset.get("section_type"),
                 "section": {**section, "pipes": rows}}
    normalize_pipe_dimensions(candidate)
    if any(row.get("offset") is not None for row in rows):
        for row in rows:
            row.pop("offset", None)
        spacing = overrides.get(_PIPE_SPACING, section.get("pipe_spacing"))
        for row, placed in zip(rows, pipe_specs({**candidate["section"], "pipe_spacing": spacing}), strict=True):
            row["offset"] = placed["offset"]
    return {**overrides, "section.pipes": rows}


def _edited_general_section(asset, updates):
    part = deepcopy(asset)
    for path, value in updates.items():
        if value is None:
            parent, _, field = path.rpartition(".")
            container = _get(part, parent)
            if isinstance(container, dict):
                container.pop(field, None)
            for key in ("drawing_user_overrides", "section_scheme_user_overrides", "parameter_sources"):
                (part.get(key) or {}).pop(path, None)
            continue
        _set(part, path, value)
        part.setdefault("drawing_user_overrides", {})[path] = value
        if path in (part.get("section_scheme_user_overrides") or {}):
            part["section_scheme_user_overrides"][path] = value
        part.setdefault("parameter_sources", {})[path] = "用户覆盖：一般段施工参数"
    normalize_pipe_dimensions(part)
    return part


def edited_general_section(asset, updates):
    updates = _parameter_updates(updates)
    edits = _layout_updates(asset, _dimension_updates(asset, updates))
    return _edited_general_section(asset, edits)


def _validate_update(part, updates):
    if any(path.startswith("section.") for path in updates):
        pipe_specs(part.get("section") or {})
    seat = _get(part, "construction.pipe_seat") or _get(part, "construction.pipe_support") or {}
    if any(path.endswith(".support_angle") for path in updates):
        angle = seat["support_angle"]
        if angle > 360:
            raise ValueError("砂垫层包角不能超过 360°。")
        if seat.get("bottom_width_mode") in {"support_chord", "support_chord_plus_sides"} and angle >= 180:
            raise ValueError("按包角弦宽封闭的砂垫层包角须小于 180°。")
    construction = part.get("construction") or {}
    if construction.get("target_mode") == "cover_depth" and any(
            "construction." + field in updates for field in _FINISH_FIELDS):
        _number(construction.get("final_cover_depth"), "管外顶至回填完成面高度")
        for side, label in (("left", "左"), ("right", "右")):
            if not construction.get("bank_stages_" + side):
                _number(construction.get("bank_slope_" + side), label + "填筑坡比")


def _rebind_material_settings(before, result, selected):
    """Keep length rows with the changed ordinary range and keep positioned records in place."""
    config = result.get(KEY)
    identities = {part[:2] for part in selected}
    if not config:
        return
    previous = [group for group in list_special_material_groups(before)
                if any(part[:2] in identities for part in _spec_parts(group))]
    active = {group["group_id"] for group in previous if group["configured"]}
    if not active:
        return
    current = {group["group_id"]: group for group in list_special_material_groups(result, include_pipe_scopes=True)}
    by_part = {(bool(group.get("source_groups")), part): key
               for key, group in current.items() for part in _spec_parts(group)}
    mapped, station_only = defaultdict(list), defaultdict(list)
    for group in previous:
        parts = _spec_parts(group)
        scoped = bool(group.get("source_groups"))
        destinations = {by_part.get((scoped, part)) for part in parts}
        if None in destinations:
            if group["configured"]:
                raise ValueError("原特殊材料的施工范围已变化，请核对特殊段。")
            continue
        if len(destinations) == 1:
            mapped[next(iter(destinations))].append(group)
        elif group["configured"]:
            edited = {by_part[(scoped, part)] for part in parts & selected}
            if len(edited) != 1:
                raise ValueError("原特殊材料对应多个一般段规格，请核对特殊段。")
            destination = next(iter(edited))
            mapped[destination].append(group)
            for key in destinations - {destination}:
                if current[key]["has_station_specials"]:
                    station_only[key].append(group)
    replacements = {}
    for key in set(mapped) | set(station_only):
        groups = mapped[key]
        positioned = station_only[key]
        if not positioned and not any(group["configured"] for group in groups):
            continue
        if key in config["groups"] and key not in active:
            raise ValueError("目标规格已有历史特殊材料，请核对特殊段。")
        target = current[key]
        saved = (_merged_settings(groups, config, target) if any(group["configured"] for group in groups)
                 else {"mode": "station", "rows": [], "length_basis": "actual_pipe_axis_length"})
        if positioned and any(group["mode"] == "length" for group in positioned):
            from .special_pipe_materials import _positioned_material
            soil_only = [*saved.get("soil_only_ranges", ())]
            ranges = _spec_parts(target)
            for group in positioned:
                if group["mode"] != "length":
                    continue
                soil_only.extend([part["station_start"], part["station_end"]] for part in group["parts"]
                                 if _special(part) and not _positioned_material(group, part)
                                 and (group["route_id"], group["asset_id"], part["station_start"], part["station_end"]) in ranges)
            saved.update(mode="length", keep_positioned_sections=True, soil_only_ranges=soil_only)
        saved.update(route_id=target["route_id"], asset_id=target["asset_id"],
                     specification_sha256=_digest(target["specification"]))
        replacements[key] = saved
    for key in active:
        config["groups"].pop(key)
    config["groups"].update(replacements)
    for group in list_special_material_groups(result):
        if group["group_id"] in replacements and group["mode"] == "length":
            validate_length_material_rows(group, group["rows"])


def apply_general_section(inputs, spans, updates):
    """Apply the same accepted edits to the selected ordinary ranges atomically."""
    if not updates:
        return None
    updates = _parameter_updates(updates)
    result = deepcopy(inputs)
    selected = {span[0] for span in spans}
    original_parts = {_part_key(network, asset): asset for network in inputs.get("networks", ())
                      for asset in network.get("assets", ()) if _ordinary(asset)}
    if not selected <= original_parts.keys():
        raise ValueError("一般段范围已变化，请重新选择。")
    for key in sorted(selected):
        route, root, start, end = key
        original = original_parts[key]
        resolved_updates = _layout_updates(original, _dimension_updates(original, updates))
        candidate = _edited_general_section(original, resolved_updates)
        scheme = _binding_scheme(original)
        inherited = None
        if not scheme and needs_default_section_scheme(original):
            scheme = default_section_scheme(candidate) or {}
            if scheme:
                candidate, inherited = _default_draft(candidate, scheme)
        _validate_update(candidate, updates)
        if scheme:
            result = apply_section_scheme(result, route_id=route, asset_id=root, scheme=scheme,
                station_start=start, station_end=end, overrides=resolved_updates, inherited_fields=inherited)
            # Verify the adopted representation as well as the previewed edit.
            adopted = next(asset for network in result["networks"] for asset in network.get("assets", ())
                           if _part_key(network, asset) == key)
            _validate_update(adopted, updates)
        else:
            network = next(network for network in result["networks"] if _route(network) == route)
            index = next(index for index, asset in enumerate(network["assets"]) if _part_key(network, asset) == key)
            candidate["geometry_sections"] = []
            network["assets"][index] = candidate
    # Exact-span binding edits never change the user's longitudinal object identity.
    identities = {_part_key(network, asset): asset.get("asset_id") for network in inputs.get("networks", ())
                  for asset in network.get("assets", ())}
    for network in result["networks"]:
        for asset in network.get("assets", ()):
            asset_id = identities.get(_part_key(network, asset))
            if asset_id:
                asset["asset_id"] = asset_id
    _rebind_material_settings(inputs, result, selected)
    return result
