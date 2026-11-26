"""Unlocated special-pipe materials, independent of the adopted earthwork.

Length records never become station bindings.  Mutations return copies and the
quantity overlay changes continuous foundation materials only; the existing
terrain sections and their excavation/backfill geometry remain authoritative.
"""
from __future__ import annotations

from copy import deepcopy
import math

from shapely.geometry import mapping

from .contracts import ConstructionInputError
from .pipe_dimensions import CONSTRUCTION_WALL, MATERIAL_OUTER
from .section_scheme_catalog import is_selectable_section_scheme
from .replacement_geometry import (
    WORK_SPACES, confirmed_slope, project_work_space, replacement_overrides, adopt_replacement_geometry,
)
from .section_scheme_bindings import (
    _check_constraints, _digest, _field_paths, _get, _overrides, _root, _route, _set,
    hydraulic_dimensions,
)

SCHEMA = "special_pipe_materials_1.0"
KEY = "special_pipe_materials"
MODES = frozenset({"length", "station"})
SUPPORT_COMPONENTS = frozenset({"bedding", "pipe_seat", "pipe_encasement", "foundation_replacement"})
SCOPE_NOTE = "特殊管段材料按长度简算；土方保留原施工构造及实际地形，未随长度材料变化修正。"
_SECTION_KEYS = (
    "inner_diameter", "outer_diameter", "wall_thickness", "lining_thickness",
    "material", "material_grade", "lining_material", "lining_grade", "pipes",
    "pipe_count", "pipe_spacing", "nominal_diameter_m", "hydraulic_inner_diameter_m",
    "earthwork_envelope_only", "diameter_basis", "construction_inner_diameter_m",
    CONSTRUCTION_WALL, MATERIAL_OUTER,
)
_CONSTRUCTION_KEYS = (
    "bedding_thickness", "bedding_extension", "bedding_reference", "bedding_material", "bedding_grade",
    "pipe_seat", "pipe_support", "encasement", "pipe_encasement", "foundation_replacement",
    "foundation_replacement_thickness", "foundation_replacement_width", "foundation_replacement_material",
    "working_space_left", "working_space_right", "working_space_reference",
    "excavation_slope_left", "excavation_slope_right", "excavation_slopes_left", "excavation_slopes_right",
)


def _number(value, label, *, positive=False):
    if isinstance(value, bool) or value is None or value == "":
        raise ConstructionInputError(f"{label}须为有效数字")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ConstructionInputError(f"{label}须为有效数字") from exc
    if not math.isfinite(result) or result < 0 or positive and result <= 0:
        raise ConstructionInputError(f"{label}须为{'正' if positive else '非负'}有限数字")
    return result


def _collection(inputs):
    if "networks" in inputs:
        return deepcopy(inputs)
    config = deepcopy(inputs.get(KEY))
    result = {"networks": [deepcopy(inputs)]}
    if config is not None:
        result[KEY] = config
    return result


def _prepared(inputs, *, return_errors=False):
    from .construction_rules import normalize_construction_inputs
    from .default_section_schemes import ensure_default_section_schemes
    result = _collection(inputs)
    normalize_construction_inputs(result)
    result, report = ensure_default_section_schemes(result)
    if report["errors"] and not return_errors:
        raise ConstructionInputError("；".join(report["errors"]))
    return (result, report["errors"]) if return_errors else result


def _binding_scheme(asset):
    return (asset.get("section_scheme_binding") or {}).get("scheme_snapshot") or {}


def _special(asset):
    scheme = _binding_scheme(asset)
    binding = asset.get("section_scheme_binding") or {}
    return bool(scheme and (scheme.get("condition") != "general" or binding.get("positioned_special_segment")))


def is_segment_scheme(group, scheme):
    return (group.get("section_type") in scheme.get("section_types", ())
            and is_selectable_section_scheme(scheme, group["section_type"])
            and scheme.get("condition") != "general" and scheme.get("calculation_status") != "not_in_scope"
            and not (group["section_type"] != "circular_siphon" and scheme["scheme_id"].startswith("tzk_siphon_")))


def _eligible(asset):
    from .earthwork_scope import trenchless_method
    from .pipe_dimensions import is_pipe_asset
    return (is_pipe_asset(asset) and asset.get("section_type") in
            {"circular_culvert", "circular_siphon", "circular_channel"}
            and asset.get("enabled", True) and not trenchless_method(asset)
            and (asset.get("construction") or {}).get("installation_mode", "buried") in {None, "buried"})


def _general_part(inputs, network, asset):
    """Recover the actual pre-special construction using recorded source values."""
    if not _special(asset):
        if _binding_scheme(asset).get("condition") == "general":
            return deepcopy(asset)
        from .default_section_schemes import _explicit_construction
        if _explicit_construction(asset):
            raise ConstructionInputError("当前自定义基础缺少可追溯的一般构造，请核定一般断面后再按长度填写")
        return deepcopy(asset)
    if not asset.get("section_scheme_source_values"):
        raise ConstructionInputError("原特殊断面缺少一般构造来源，不能自动将其当作一般材料基准")
    from .default_section_schemes import restore_default_section_range
    restored = restore_default_section_range(inputs, route_id=_route(network), asset_id=_root(asset),
        station_start=asset["station_start"], station_end=asset["station_end"])
    return next(deepcopy(part) for route in restored["networks"] if _route(route) == _route(network)
        for part in route.get("assets", []) if _root(part) == _root(asset)
        and abs(part["station_start"]-asset["station_start"]) < 1e-8
        and abs(part["station_end"]-asset["station_end"]) < 1e-8)


def _specification(asset):
    section, construction = asset.get("section") or {}, asset.get("construction") or {}
    general = {key: deepcopy(construction[key]) for key in _CONSTRUCTION_KEYS
               if key in construction and construction[key] not in ({}, None)}
    # A full-trench sand seat uses outside-pipe workspaces with or without the
    # historical explicit flag. Empty restored family dictionaries do not
    # define a different engineering specification.
    if (general.get("pipe_seat") or {}).get("bottom_width_mode") == "trench_bottom":
        general["working_space_reference"] = "pipe_outer"
    return {"section_type": asset.get("section_type"),
        "section": {key: deepcopy(section[key]) for key in _SECTION_KEYS if key in section},
        "general_construction": general,
        "general_material_specs": deepcopy((section.get("material_specs") or {}).get("bedding") or {})}


def _axis_length(asset, start=None, end=None):
    from .design_profiles import normalize_design_profile, pipe_axis_profile, profile_spatial_length
    from .section_geometry import pipe_specs
    pipes = pipe_specs(asset.get("section") or {})
    first = pipes[0]
    radius = first["outer_diameter"]/2
    # Terrain-derived axes may have thousands of controls. Share the validated
    # station index for every element evaluation while deriving the pipe axis.
    profile = normalize_design_profile(asset)
    if profile["reference"] != "pipe_axis" or any(row["kind"] == "arc" for row in profile["elements"]):
        indexed = {**asset, "design_profile": profile}
        profile = pipe_axis_profile(indexed, radius, radius, first_inner_radius=first["inner_diameter"]/2)
    return profile_spatial_length(profile, asset["station_start"] if start is None else start,
                                  asset["station_end"] if end is None else end)


def _config(inputs):
    raw = inputs.get(KEY)
    if raw is None:
        return {"schema": SCHEMA, "groups": {}}
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA or not isinstance(raw.get("groups"), dict):
        raise ConstructionInputError("特殊管段材料配置格式无效，请重新核对计量方式")
    _digest(raw)
    return raw


def _is_pipe_scope_id(identifier):
    return str(identifier).rpartition("::")[2].startswith("pipe-")


def list_special_material_groups(inputs, *, include_pipe_scopes=False):
    """List homogeneous, eligible length pools; retain station bindings untouched."""
    source, preparation_errors = _prepared(inputs, return_errors=True)
    configured = _config(source)["groups"]
    groups = {}
    named_prefixes = [str(asset.get("name") or _root(asset))+"：" for network in source.get("networks", [])
                      for asset in network.get("assets", [])]
    from .pipe_dimensions import is_pipe_asset
    object_lengths, axis_lengths, missing_axis, pending_gaps = {}, {}, set(), set()
    for network in source.get("networks", []):
        for asset in network.get("assets", []):
            if not is_pipe_asset(asset):
                continue
            identity = (_route(network), _root(asset))
            if asset.get("pipe_profile_choice") == "pending_gap":
                pending_gaps.add(identity)
                continue
            axis_error = "起止桩号重合"
            try:
                length = _axis_length(asset)
                axis_lengths[id(asset)] = length
                object_lengths[identity] = object_lengths.get(identity, 0.) + length
            except (ValueError, KeyError) as exc:
                missing_axis.add(identity)
                length, axis_error = 0., str(exc)
            if not _eligible(asset):
                continue
            prefix = str(asset.get("name") or _root(asset))+"："
            errors = [error for error in preparation_errors if str(error).startswith(prefix)
                      or not any(str(error).startswith(name) for name in named_prefixes)]
            try:
                general = _general_part(source, network, asset)
            except (ValueError, KeyError, StopIteration) as exc:
                general = deepcopy(asset)
                errors.append(str(exc) or "缺少可追溯一般断面")
            if not length:
                errors.append("实际管轴长度待补："+axis_error)
            signature = _specification(general)
            route, root = _route(network), _root(asset)
            identifier = route+"::"+root+"::"+_digest(signature)[:16]
            group = groups.setdefault(identifier, {"group_id": identifier, "route_id": route,
                "asset_id": root, "name": asset.get("base_name") or asset.get("name") or root,
                "route_name": network.get("name", route), "section_type": asset.get("section_type"),
                "specification": signature, "parts": [], "general_parts": [], "part_asset_ids": [],
                "available_length_m": 0., "general_asset": deepcopy(general), "errors": [],
                "has_station_specials": False, "has_selectable_station_specials": False})
            group["parts"].append(deepcopy(asset))
            group["general_parts"].append(deepcopy(general))
            group["part_asset_ids"].append(str(asset["asset_id"]))
            group["available_length_m"] += length
            group["has_station_specials"] |= _special(asset)
            group["has_selectable_station_specials"] |= is_segment_scheme(group, _binding_scheme(asset))
            group["errors"].extend(e for e in errors if e not in group["errors"])

    if not groups:
        return []

    from .earthwork_scope import trenchless_exclusions
    from .pipe_construction_objects import pipe_objects_by_scope

    exclusions = trenchless_exclusions(source)
    pipe_scopes = []
    whole_pipe_axes = {}
    for members in pipe_objects_by_scope(source).values():
        identities = tuple(dict.fromkeys((_route(owner), _root(part)) for owner, part in members))
        axis = _continuous_pipe_axis_length(exclusions, members, axis_lengths)
        pipe_scopes.append((members, identities, axis))
        overlapping = axis[0] is not None and any(
            float(after["station_start"]) < float(before["station_end"]) - 1e-6
            for (_, before), (_, after) in zip(members, members[1:]))
        whole_axis = (None, None) if overlapping or pending_gaps.intersection(identities) else axis
        whole_pipe_axes.update(dict.fromkeys(identities, whole_axis))

    for identifier, group in groups.items():
        saved = configured.get(identifier) or {}
        # Equal numeric specifications share the same saved group ID. A slope
        # can stand in for the entire unlocated length only when each member
        # supplies that design basis, including members with staged slopes.
        unconfirmed = []
        for side in ("left", "right"):
            path = "construction.excavation_slope_" + side
            if any(not confirmed_slope(part, path) or
                   (part.get("construction") or {}).get("excavation_stages_" + side) or
                   (part.get("construction") or {}).get("excavation_layer_mode") == "surface_thickness"
                   for part in group["general_parts"]):
                unconfirmed.append(path)
        group["general_asset"]["unconfirmed_group_slopes"] = unconfirmed
        group["general_asset"]["mixed_group_work_spaces"] = [
            path for path in WORK_SPACES if len({project_work_space(p, path) for p in group["general_parts"]}) > 1]
        group["mode"] = saved.get("mode", "station" if group["has_station_specials"] else "length")
        identity = (group["route_id"], group["asset_id"])
        group["object_axis_length_m"] = None if identity in missing_axis else object_lengths.get(identity)
        whole_length, whole_basis = whole_pipe_axes.get(identity, (
            (None, None) if identity in pending_gaps or identity in missing_axis
            else (object_lengths.get(identity), "actual_pipe_axis_length")))
        group.update(whole_pipe_axis_length_m=whole_length, whole_pipe_axis_basis=whole_basis)
        group["has_pending_profile_gap"] = identity in pending_gaps
        group["keep_positioned_sections"] = bool(saved.get("keep_positioned_sections"))
        group["soil_only_ranges"] = deepcopy(saved.get("soil_only_ranges", []))
        group["rows"] = deepcopy(saved.get("rows", []))
        group["configured"] = identifier in configured
        group["soil_basis_label"] = ("已有桩号特殊构造＋实际地形" if group["has_station_specials"]
                                     else "当前一般断面＋实际地形")
        group["parts"].sort(key=lambda part: part["station_start"])
        _refresh_group_lengths(group)
    has_saved_scope = any(map(_is_pipe_scope_id, configured))
    scopes = (_continuous_pipe_material_groups(groups, configured, pipe_scopes, exclusions)
              if include_pipe_scopes or has_saved_scope else [])
    return [*groups.values(), *(group for group in scopes if include_pipe_scopes or group["configured"])]


def _continuous_pipe_material_groups(groups, configured, pipe_scopes, exclusions):
    """Add one length pool per compatible construction specification on a pipe."""
    from .earthwork_scope import trenchless_range_covered

    result = []
    for members, identities, (total, basis) in pipe_scopes:
        if len(identities) < 2 and not any(
            trenchless_range_covered(exclusions, owner, before.get("station_end"), after.get("station_start"))
            for (owner, before), (_, after) in zip(members, members[1:])
        ):
            continue
        by_spec = {}
        for group in groups.values():
            if (group["route_id"], group["asset_id"]) in identities and (
                    not group["configured"] or group["mode"] == "station"):
                by_spec.setdefault(_digest(group["specification"]), []).append(group)
        if not by_spec:
            continue
        for signature, local_groups in by_spec.items():
            local_groups.sort(key=lambda group: (group["parts"][0]["station_start"], group["group_id"]))
            first = local_groups[0]
            local_ids = [group["group_id"] for group in local_groups]
            identifier = first["route_id"] + "::" + first["asset_id"] + "::pipe-" + _digest([signature, local_ids])[:16]
            saved = configured.get(identifier) or {}
            entries = sorted(((group["route_id"], group["asset_id"], part, general)
                              for group in local_groups for part, general in
                              zip(group["parts"], sorted(group["general_parts"], key=lambda p: p["station_start"]), strict=True)),
                             key=lambda item: item[2]["station_start"])
            general_asset = deepcopy(first["general_asset"])
            for key in ("unconfirmed_group_slopes", "mixed_group_work_spaces"):
                general_asset[key] = list(dict.fromkeys(value for group in local_groups for value in group["general_asset"][key]))
            available = math.fsum(group["available_length_m"] for group in local_groups)
            pending = any(part.get("pipe_profile_choice") == "pending_gap" for _, part in members)
            group = {**first, "group_id": identifier, "mode": saved.get("mode", "length"), "configured": identifier in configured,
                "parts": [p for _, _, p, _ in entries], "general_parts": [p for _, _, _, p in entries],
                "general_asset": general_asset, "part_asset_ids": [p["asset_id"] for _, _, p, _ in entries],
                "part_scopes": [(route, root, p["asset_id"]) for route, root, p, _ in entries],
                "source_groups": local_ids, "available_length_m": available, "object_axis_length_m": total,
                "object_axis_basis": basis, "has_pending_profile_gap": pending, "keep_positioned_sections": True,
                "has_station_specials": any(g["has_station_specials"] for g in local_groups),
                "has_selectable_station_specials": any(g["has_selectable_station_specials"] for g in local_groups),
                "errors": list(dict.fromkeys(error for g in local_groups for error in g["errors"])),
                "rows": deepcopy(saved.get("rows", []))}
            _refresh_group_lengths(group)
            result.append(group)
    return result


def _continuous_pipe_axis_length(exclusions, members, axis_lengths):
    from .earthwork_scope import _bore_length, _number as _station_number, trenchless_intersections

    try:
        lengths = [axis_lengths[id(part)] for _, part in members if part.get("pipe_profile_choice") != "pending_gap"]
    except KeyError:
        return None, None
    if not lengths:
        return None, None
    uses_plan = False
    for (owner, before), (_, after) in zip(members, members[1:]):
        cursor, stop = _station_number(before.get("station_end")), _station_number(after.get("station_start"))
        if cursor is None or stop is None:
            return None, None
        if stop <= cursor + 1e-6:
            continue
        candidates = [(left, right, record) for record in exclusions
                      for left, right in trenchless_intersections([record], owner, cursor, stop)]
        candidates.sort(key=lambda hit: (hit[0], -hit[1]))
        for left, right, record in candidates:
            left = max(left, cursor)
            if right <= left + 1e-6:
                continue
            original = record.get("original_asset_snapshot") or record
            length, basis = _bore_length({**original, "trenchless_route_profile": record.get("trenchless_route_profile")},
                                        left, right)
            lengths.append(length)
            uses_plan |= basis == "plan_chainage"
            cursor = right
        if cursor < stop - 1e-6:
            return None, None
    return math.fsum(lengths), "plan_chainage_in_trenchless" if uses_plan else "actual_pipe_axis_length"


def _percentage_axis(group, row):
    """Resolve the saved basis without converting an old local allowance."""
    basis = row.get("percent_basis")
    if basis == "whole_pipe":
        return group.get("whole_pipe_axis_length_m"), group.get("whole_pipe_axis_basis")
    if basis is not None:
        raise ConstructionInputError("特殊段占比的管轴依据无效")
    return group.get("object_axis_length_m"), group.get("object_axis_basis")


def _refresh_group_lengths(group):
    for row in group["rows"]:
        if "object_percent" in row and _percentage_axis(group, row)[0] is not None:
            row["length_m"] = _percentage_length(group, row)
    group["special_length_m"] = math.fsum(float(row.get("length_m") or 0.) for row in group["rows"])
    group["general_length_m"] = group["available_length_m"] - group["special_length_m"]


def _percentage_length(group, row):
    percent = _number(row["object_percent"], "占整条管轴的比例", positive=True)
    if percent > 100:
        raise ConstructionInputError("特殊段比例须在 0 至 100% 之间")
    length, _ = _percentage_axis(group, row)
    if length is None and row.get("percent_basis") == "whole_pipe":
        raise ConstructionInputError("整条管轴长度待补，请补齐纵断面或按实际长度填写")
    total = _number(length, "当前对象的完整管轴长度", positive=True)
    return total * (percent / 100.)


def _positioned_material(group, part):
    """Historical length-mode sections can remain soil-only after a new addition."""
    return group["keep_positioned_sections"] and _special(part) and not any(
        start <= part["station_start"] + 1e-8 and end >= part["station_end"] - 1e-8
        for start, end in group.get("soil_only_ranges", []))


def _material_pool(group):
    if not group["keep_positioned_sections"] or not group["has_station_specials"]:
        return group
    indices = [index for index, part in enumerate(group["parts"]) if not _positioned_material(group, part)]
    parts = [group["parts"][index] for index in indices]
    scopes = group.get("part_scopes")
    return {**group, "parts": parts, "part_asset_ids": [str(part["asset_id"]) for part in parts],
            **({"part_scopes": [scopes[index] for index in indices]} if scopes is not None else {}),
            "available_length_m": math.fsum(_axis_length(part) for part in parts),
            "has_station_specials": any(_special(part) for part in parts)}


def _group(inputs, group_id):
    matches = [group for group in list_special_material_groups(inputs, include_pipe_scopes=_is_pipe_scope_id(group_id))
               if group["group_id"] == group_id]
    if len(matches) != 1:
        raise ConstructionInputError("管道规格或一般构造已变化，请重新选择规格组并核对特殊长度")
    return matches[0]


def _fixed_terrain_materials(group, scheme):
    variants = scheme.get("terrain_variants") or {}
    if not variants:
        return True
    if scheme["scheme_id"] != "tzk_pipe_hillside" or set(variants) != {"cut", "mixed"}:
        return False
    # F/G share one concrete seat. Only their positioned ground section is
    # terrain-specific. Compare resolved size-table fields as a variant may
    # overwrite one of those dimensions even if family defaults agree.
    from .section_scheme_catalog import resolve_section_scheme_fields

    required = set(scheme.get("required_fields") or ()) | set((scheme.get("constraints") or {}).get("required_fields") or ())
    dimensions = hydraulic_dimensions(group["general_asset"])
    fields = resolve_section_scheme_fields(scheme, hydraulic_dimensions=dimensions)
    return all(
        not any(variant.get(key) for key in ("selectors", "field_choices", "constraints", "source_review_required"))
        and set(variant.get("required_fields") or ()).issubset(required)
        and resolve_section_scheme_fields(scheme, terrain_case=case, hydraulic_dimensions=dimensions) == fields
        for case, variant in variants.items()
    )


def special_material_schemes(group, schemes=None):
    """Only finite, constant construction templates can be unlocated."""
    if schemes is None:
        from .section_scheme_catalog import load_section_schemes
        schemes = load_section_schemes()
    return [deepcopy(scheme) for scheme in schemes
        if is_segment_scheme(group, scheme) and _fixed_terrain_materials(group, scheme)
        and not scheme.get("selectors")
        and scheme.get("fields", {}).get("construction.installation_mode", "buried") == "buried"
        and "镇墩" not in str(scheme.get("title", ""))
        and "anchor" not in str(scheme.get("scheme_id", "")).lower()
        and not any(str(path).startswith("section.discrete_components") for path in
                    [*scheme.get("fields", {}), *scheme.get("required_fields", [])])
        and any(str(path).startswith(("construction.pipe_seat.", "construction.encasement.",
                                     "construction.foundation_replacement")) for path in scheme.get("fields", {}))]


def draft_special_material_fields(general_asset, scheme, overrides):
    """Resolve the material cross-section before requiring all design dimensions."""
    from .section_scheme_catalog import resolve_section_scheme_fields
    from .section_parameter_decisions import drawing_support_transition

    asset = deepcopy(general_asset)
    construction = asset.setdefault("construction", {})
    for key in ("pipe_seat", "pipe_support", "encasement", "pipe_encasement", "foundation_replacement",
                "foundation_replacement_thickness", "foundation_replacement_width", "foundation_replacement_material"):
        construction.pop(key, None)
    # The selected special support replaces the ordinary sand bed, never sits
    # on a silently inherited second bed inside the same material region.
    construction.update(bedding_thickness=0., bedding_extension=0.)
    fields = resolve_section_scheme_fields(scheme, hydraulic_dimensions=hydraulic_dimensions(asset))
    fields = _field_paths(fields, template=True)[0]
    _, reuse_support = drawing_support_transition(general_asset, scheme, fields)
    for path, value in reuse_support.items():
        _set(asset, path, value)
    overrides = _field_paths(overrides or {})[0]
    if any(not path.startswith("construction.") for path in overrides):
        raise ConstructionInputError("长度材料参数不能改变管径、管材或管身，请改到所属规格组设置")
    retained = {}
    if fields.get("construction.bedding_reference") == "pipe_seat_bottom":
        specified = _overrides(general_asset)
        # A project-defined independent layer remains beneath the special
        # support. The ordinary sand cradle itself was removed above.
        if specified.get("construction.bedding_thickness") is not None:
            for path in ("construction.bedding_thickness", "construction.bedding_extension"):
                if specified.get(path) is not None:
                    retained[path] = specified[path]
    overrides = replacement_overrides(general_asset, scheme, overrides, retained)
    retained.update({p: v for p, v in overrides.items() if v is not None})
    for p, v in overrides.items():
        if v is None:
            retained.pop(p, None)
    for path, value in {**fields, **retained}.items():
        if value is not None:
            _set(asset, path, value)
    adopt_replacement_geometry(asset, scheme, fields, retained)
    asset["section_scheme_user_overrides"] = retained
    return asset, fields


def _retained_material_row(group, row, scheme):
    """A retired drawing can still supply its previously adopted material quantity."""
    if group.get("mode") != "length":
        return False
    saved = next((previous for previous in group["rows"] if previous.get("record_id")
                  and previous["record_id"] == row.get("record_id")), None)
    if not saved or saved.get("scheme_sha256") != _digest(scheme):
        return False
    basis = "object_percent" if "object_percent" in saved else "length_m"
    return (saved.get("scheme_id") == row.get("scheme_id")
            and saved.get("overrides", {}) == row.get("overrides", {})
            and saved.get("percent_basis") == row.get("percent_basis")
            and ("object_percent" in saved) == ("object_percent" in row)
            and saved[basis] == row[basis])


def _special_asset(group, row):
    from .section_scheme_catalog import load_section_schemes
    scheme = deepcopy(row.get("scheme_snapshot"))
    if not scheme:
        scheme = next((scheme for scheme in load_section_schemes() if scheme["scheme_id"] == row.get("scheme_id")), None)
    if not scheme or scheme.get("scheme_id") != row.get("scheme_id"):
        raise ConstructionInputError("特殊管段断面方案不存在")
    if not is_selectable_section_scheme(scheme, group["section_type"]):
        if not _retained_material_row(group, row, scheme):
            raise ConstructionInputError("原断面图已停用，请选择当前可用的施工做法")
    elif not special_material_schemes(group, [scheme]):
        raise ConstructionInputError("该断面依赖实际地形或不具备连续构造，不能只按长度套用")
    if row.get("scheme_sha256") and row["scheme_sha256"] != _digest(scheme):
        raise ConstructionInputError("特殊管段断面快照改变，请重新核定")
    asset, _ = draft_special_material_fields(group["general_asset"], scheme, row.get("overrides"))
    _check_constraints(asset, scheme)
    asset["section_scheme_id"] = scheme["scheme_id"]
    return asset, scheme


def _standard_rates(asset):
    from .construction_rules import effective_construction
    from .section_geometry import section_structure, add_foundation_materials
    reference = deepcopy(asset)
    reference.pop("design_profile", None)
    reference["alignment"] = {"elevation_reference": "pipe_axis"}
    reference["workbench_geometry"] = True
    reference.setdefault("section", {}).pop("discrete_components", None)
    structure = add_foundation_materials(section_structure(reference, elevation=0., slope=0.,
        arc_segments=128), effective_construction(reference), arc_segments=128)
    items = []
    bed = structure["materials"].get("bedding")
    if bed is not None and not bed.is_empty:
        spec = (reference["section"].get("material_specs") or {}).get("bedding", {})
        construction = reference.get("construction") or {}
        items.append({"component_id": "bedding", "name": spec.get("name", "垫层/找平"),
            "material": spec.get("material", construction.get("bedding_material", "bedding")),
            "grade": spec.get("grade", construction.get("bedding_grade", "")), "unit": "m3", "rate": float(bed.area)})
    for identifier, spec in structure.get("component_regions", {}).items():
        if identifier in SUPPORT_COMPONENTS:
            items.append({key: deepcopy(spec.get(key, "")) for key in
                ("component_id", "name", "material", "grade", "unit")} | {"rate": float(spec["geometry"].area)})
    # Old general snapshots may not have split material roles. Preserve their
    # finite support area as a separate reference, never include the pipe wall.
    extra = structure["materials"].get("concrete").difference(structure.get("pipe_concrete"))
    if not extra.is_empty and extra.area > 1e-9:
        seat = (reference.get("construction") or {}).get("pipe_seat") or {}
        items.append({"component_id": "pipe_seat", "name": seat.get("name", "混凝土管座"),
            "material": seat.get("material", "concrete"), "grade": seat.get("grade", ""),
            "unit": "m3", "rate": float(extra.area)})
    geometry = {"outer": mapping(structure["outer"]), "net_void": mapping(structure["net_void"])}
    if bed is not None and not bed.is_empty:
        geometry["bedding"] = mapping(bed)
    geometry.update({identifier: mapping(spec["geometry"]) for identifier, spec in
        structure.get("component_regions", {}).items() if identifier in SUPPORT_COMPONENTS})
    return items, geometry


def _validated_rows(group, rows):
    if group["errors"]:
        raise ConstructionInputError("；".join(group["errors"]))
    if not isinstance(rows, list):
        raise ConstructionInputError("特殊长度记录须为列表")
    total = _number(_material_pool(group)["available_length_m"], "本规格可分配的实际长度")
    result, seen = [], set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ConstructionInputError("特殊长度记录格式无效")
        row = deepcopy(raw)
        row["length_m"] = (_percentage_length(group, row) if "object_percent" in row else
            _number(row.get("length_m"), f"第{index+1}条特殊长度", positive=True))
        if "object_percent" in row:
            row["object_percent"] = float(row["object_percent"])
            axis_length, axis_basis = _percentage_axis(group, row)
            basis = "非开挖按平面桩长" if axis_basis == "plan_chainage_in_trenchless" else ""
            row["length_source"] = f"整条管轴 {axis_length:.3f} m × {row['object_percent']:g}%"
            if basis:
                row["length_source"] += "（" + basis + "）"
        else:
            row.pop("percent_basis", None)
        identifier = str(row.get("record_id") or "length-"+_digest([group["group_id"], index, row])[:16])
        if identifier in seen:
            raise ConstructionInputError("特殊长度记录编号重复，请合并或重新添加")
        seen.add(identifier)
        row["record_id"] = identifier
        asset, scheme = _special_asset(group, row)
        _standard_rates(asset)
        row.update(scheme_snapshot=scheme, scheme_id=scheme["scheme_id"], scheme_sha256=_digest(scheme),
                   scheme_title=scheme["title"], length_source=row.get("length_source") or "用户填写实际管轴长度")
        result.append(row)
    special = math.fsum(row["length_m"] for row in result)
    if special > total + max(1e-8, total*1e-12):
        raise ConstructionInputError(f"特殊长度合计{special:g}m超过本组可用长度{total:g}m")
    return result


def validate_length_material_rows(group, rows):
    """Validate a current group snapshot without traversing the whole project.

    This is the lightweight draft check used while typing. Formal application
    still resolves the group against current inputs before adopting anything.
    """
    return _validated_rows(group, rows)


def apply_length_materials(inputs, group_id, rows, *, keep_positioned=False):
    """Apply validated material-only rows. Existing soil assets are not edited."""
    group = _group(inputs, group_id)
    result = deepcopy(inputs)
    config = deepcopy(_config(result))
    if not group.get("source_groups") and any(map(_is_pipe_scope_id, config["groups"])):
        if any(group_id in scope.get("source_groups", ()) for scope in list_special_material_groups(inputs)):
            raise ConstructionInputError("当前管线已有全线特殊施工设置，请在特殊施工段清单修改")
    saved = config["groups"].get(group_id, {})
    if group["mode"] == "station" and not group["keep_positioned_sections"]:
        positioned = [part for part in group["parts"] if _special(part)]
        convertible = [part for part in positioned if is_segment_scheme(group, _binding_scheme(part))]
        if keep_positioned or len(convertible) != len(positioned):
            # Archived station materials remain measured in place when switching to lengths.
            spans = [] if keep_positioned else [[part["station_start"], part["station_end"]] for part in convertible]
            saved.update(keep_positioned_sections=True, soil_only_ranges=spans)
            group = {**group, "keep_positioned_sections": True, "soil_only_ranges": spans}
    values = _validated_rows(group, rows)
    config["groups"][group_id] = {**saved,
        "mode": "length", "rows": values, "route_id": group["route_id"], "asset_id": group["asset_id"],
        "specification_sha256": _digest(group["specification"]),
        "length_basis": group.get("object_axis_basis") or "actual_pipe_axis_length"}
    result[KEY] = config
    return result


def summarize_station_material_rows(inputs, group_id):
    group = _group(inputs, group_id)
    result = {}
    for asset in group["parts"]:
        if not _special(asset):
            continue
        scheme = _binding_scheme(asset)
        if not is_selectable_section_scheme(scheme, group["section_type"]):
            continue
        overrides = deepcopy((asset.get("section_scheme_binding") or {}).get("overrides") or {})
        # Record the actually adopted source parameters, including an exact
        # size-table row, before material-only editing becomes independent.
        required = set(scheme.get("required_fields", []))
        for path in required:
            if path.startswith("construction.") and _get(asset, path) is not None:
                overrides[path] = deepcopy(_get(asset, path))
        key = _digest([scheme, overrides])
        row = result.setdefault(key, {"record_id": "from-station-"+key[:16], "scheme_id": scheme["scheme_id"],
            "scheme_snapshot": deepcopy(scheme), "scheme_sha256": _digest(scheme), "scheme_title": scheme["title"],
            "overrides": overrides, "length_m": 0., "length_source": "由保留的实际桩号及管轴汇总"})
        row["length_m"] += _axis_length(asset)
    return list(result.values())


def set_special_material_mode(inputs, group_id, mode):
    if mode not in MODES:
        raise ConstructionInputError("特殊材料填写方式只能选择按长度或按桩号")
    group = _group(inputs, group_id)
    result = deepcopy(inputs)
    config = deepcopy(_config(result))
    saved = deepcopy(config["groups"].get(group_id, {}))
    if mode == "length":
        rows = saved.get("rows")
        if rows is None:
            rows = summarize_station_material_rows(inputs, group_id)
        return apply_length_materials(inputs, group_id, rows)
    saved.update(mode=mode, route_id=group["route_id"], asset_id=group["asset_id"],
                 specification_sha256=_digest(group["specification"]), length_basis="actual_pipe_axis_length")
    config["groups"][group_id] = saved
    result[KEY] = config
    return result


def validate_special_pipe_materials(inputs, *, raise_on_error=False):
    errors = []
    try:
        config = _config(inputs)
        groups = {group["group_id"]: group for group in list_special_material_groups(inputs)}
        for identifier, saved in config["groups"].items():
            if identifier not in groups:
                raise ConstructionInputError("特殊材料原规格组已变化或移除，请重新核对："+str(identifier))
            group = groups[identifier]
            if not isinstance(saved, dict) or saved.get("mode") not in MODES:
                raise ConstructionInputError("特殊材料填写方式无效")
            if saved.get("specification_sha256") != _digest(group["specification"]):
                raise ConstructionInputError("特殊材料规格或一般构造已变化，请重新核对")
            if saved["mode"] == "length":
                _validated_rows(group, saved.get("rows", []))
    except (ValueError, TypeError, KeyError) as exc:
        errors.append(str(exc))
    if errors and raise_on_error:
        raise ConstructionInputError("；".join(errors))
    return {"valid": not errors, "errors": errors, "schema": SCHEMA}


def invalid_special_material_groups(inputs, route_id=None, asset_id=None):
    """Describe stale configurations so they can be explicitly recovered.

    A changed diameter or ordinary foundation defines a new group. The old
    length record remains engineering evidence, but must not silently move to
    that new specification or leave the UI with an unresolvable hidden error.
    """
    config = _config(inputs)
    current = {group["group_id"]: group for group in list_special_material_groups(inputs)}
    result = []
    for identifier, saved in config["groups"].items():
        group = current.get(identifier)
        source = saved if isinstance(saved, dict) else {}
        route = str(source.get("route_id") or (group or {}).get("route_id") or "")
        root = str(source.get("asset_id") or (group or {}).get("asset_id") or "")
        if route_id is not None and route != str(route_id):
            continue
        if asset_id is not None and root != str(asset_id):
            continue
        reason = None
        if group is None:
            reason = "所属管道规格或一般构造已变化，原长度配置不再属于当前规格组"
        elif source.get("specification_sha256") != _digest(group["specification"]):
            reason = "原长度配置的规格与当前一般构造签名不一致"
        elif source.get("mode") not in MODES:
            reason = "原材料填写方式配置无效"
        if reason:
            result.append({"group_id": identifier, "route_id": route, "asset_id": root,
                "reason": reason, "configuration": deepcopy(saved)})
    return result


def archive_invalid_material_groups(inputs, route_id, asset_id):
    """Explicitly archive only stale records belonging to this route/root.

    No station binding, soil configuration or record on another pipe is
    deleted. The caller can use its existing undo stack to restore the copy.
    """
    stale = invalid_special_material_groups(inputs, route_id=route_id, asset_id=asset_id)
    result = deepcopy(inputs)
    if not stale:
        return result
    config = deepcopy(_config(result))
    archived = config.setdefault("archived_groups", [])
    if not isinstance(archived, list):
        raise ConstructionInputError("原材料归档记录格式无效，不能覆盖既有记录")
    for item in stale:
        identifier = item["group_id"]
        record = config["groups"].pop(identifier)
        archived.append({"archive_id": "archived-"+_digest([identifier, record, len(archived)])[:16],
            "old_group_id": identifier, "route_id": item["route_id"], "asset_id": item["asset_id"],
            "reason": item["reason"], "configuration": deepcopy(record)})
    result[KEY] = config
    return result


def build_special_material_baseline_inputs(inputs):
    """Return a detached material-reference input; never change the soil source."""
    source = _prepared(inputs)
    source.pop(KEY, None)
    changed = False
    groups = list_special_material_groups(inputs)
    from .default_section_schemes import restore_default_section_range
    for group in groups:
        if not group["configured"] or group["mode"] != "length":
            continue
        if group["errors"]:
            raise ConstructionInputError("；".join(group["errors"]))
        for part in group["parts"]:
            if not _special(part) or _positioned_material(group, part):
                continue
            source = restore_default_section_range(source, route_id=group["route_id"], asset_id=group["asset_id"],
                station_start=part["station_start"], station_end=part["station_end"])
            changed = True
    source.pop(KEY, None)
    return source, changed


def _identity(item):
    return tuple(str(item.get(key) or "") for key in ("component_id", "material", "grade", "unit"))


def _belongs(item, group):
    route = str(item.get("route_id") or "")
    identifier = str(item.get("original_asset_id") or item.get("asset_id") or "")
    if "part_scopes" in group:
        return any((route, identifier) == (member_route, asset_id)
                   for member_route, _, asset_id in group["part_scopes"])
    return route == group["route_id"] and identifier in set(group["part_asset_ids"])


def _support_items(payload, group):
    return [item for item in payload.get("quantity_items", [])
            if item.get("component_id") in SUPPORT_COMPONENTS and _belongs(item, group)]


def _is_concrete(item):
    value = str(item.get("material") or "").lower()
    return item.get("unit") == "m3" and any(word in value for word in ("concrete", "shotcrete", "混凝土"))


def apply_special_material_quantities(inputs, payload, baseline_payload=None):
    """Return adopted materials and audit tables while preserving all soil data."""
    if not inputs.get(KEY):
        return deepcopy(payload)
    validate_special_pipe_materials(inputs, raise_on_error=True)
    config = _config(inputs)
    if payload.get("special_pipe_materials_policy") == SCHEMA:
        if payload.get("special_pipe_materials_input_hash") == _digest(config):
            return deepcopy(payload)
        prior_applied = (payload.get(KEY) or {}).get("length_mode_active", False)
        if prior_applied and payload.get("soil_basis_quantity_items") is None:
            raise ConstructionInputError("已有长度材料成果缺少原材料基准，须重新计算后应用新配置")
        # Retained sampling or a subsequent edit must overlay the original
        # soil-basis materials, never scale already reduced sand for a second
        # time. This data remains separate from the adopted material totals.
        original = deepcopy(payload)
        if prior_applied:
            original["quantity_items"] = original.pop("soil_basis_quantity_items")
        original_totals = original.pop("soil_basis_material_totals", {})
        for key in list(original):
            if prior_applied and key.startswith("component__") and key.endswith("_volume") and key not in original_totals:
                original.pop(key, None)
        for key, value in original_totals.items():
            if value is not None:
                original[key] = value
                if isinstance(original.get("quantities"), dict) and key in original["quantities"]:
                    original["quantities"][key] = deepcopy(value)
        for key in (KEY, "special_pipe_materials_policy", "special_pipe_materials_input_hash",
                    "special_pipe_material_items", "special_pipe_material_sections", "material_quantity_basis"):
            original.pop(key, None)
        for table in ("assets", "rows"):
            for item in original.get(table, []):
                for key in ("material_quantity_basis", "special_material_group_id", "material_scope_note"):
                    item.pop(key, None)
        return apply_special_material_quantities(inputs, original, baseline_payload)
    result = deepcopy(payload)
    reference = baseline_payload if baseline_payload is not None else payload
    block = {"schema": SCHEMA, "groups": [], "rows": [], "adjustments": [], "scope_note": SCOPE_NOTE,
             "applied": False, "length_mode_active": False, "input_hash": _digest(config)}
    adopted, standard_sections = [], []
    for group in list_special_material_groups(inputs):
        if not group["configured"]:
            continue
        record = {key: deepcopy(group[key]) for key in ("group_id", "route_id", "asset_id", "name", "mode",
            "available_length_m", "soil_basis_label", "part_asset_ids")}
        record.update(scope_note=SCOPE_NOTE, rows=[], items=[], applied=group["mode"] == "length")
        block["groups"].append(record)
        if group["mode"] != "length":
            continue
        block["applied"] = True
        block["length_mode_active"] = True
        rows = _validated_rows(group, group["rows"])
        group_axis_length = group["available_length_m"]
        group = _material_pool(group)
        record.update(available_length_m=group["available_length_m"], group_axis_length_m=group_axis_length,
            positioned_length_m=group_axis_length-group["available_length_m"],
            object_axis_length_m=group["object_axis_length_m"],
            whole_pipe_axis_length_m=group["whole_pipe_axis_length_m"])
        members = group.get("part_scopes")
        if members is not None:
            record["member_scopes"] = [{"route_id": route, "asset_id": root}
                                       for route, root in dict.fromkeys((route, root) for route, root, _ in members)]
        if group["has_station_specials"] and baseline_payload is None:
            raise ConstructionInputError("原桩号特殊构造须先形成独立的一般材料参照，不能重复增加特殊材料")
        total = group["available_length_m"]
        if total == 0:
            record.update(special_length_m=0., general_length_m=0.)
            continue
        special = math.fsum(row["length_m"] for row in rows)
        remaining = max(0., total-special)
        ratio = remaining/total
        record.update(special_length_m=special, general_length_m=remaining)
        aggregate, general_shares = {}, {}
        local_lengths = {}
        part_owners = {}
        if members is not None:
            for (route, root, asset_id), part in zip(members, group["parts"], strict=True):
                part_owners[(route, asset_id)] = route, root
                local_lengths[(route, root)] = local_lengths.get((route, root), 0.) + _axis_length(part)
        for item in _support_items(reference, group):
            identity = _identity(item)
            target = aggregate.setdefault(identity, {key: deepcopy(item.get(key, "")) for key in
                ("component_id", "name", "material", "grade", "unit")})
            value = float(item["quantity"])
            target["baseline_quantity"] = target.get("baseline_quantity", 0.) + value
            owner = part_owners.get((str(item.get("route_id") or ""), str(item.get("original_asset_id") or item.get("asset_id") or "")),
                                   (group["route_id"], group["asset_id"]))
            share = owner, identity
            general_shares[share] = general_shares.get(share, 0.) + value
        if not aggregate:
            rates, _ = _standard_rates(group["general_asset"])
            if any(row["rate"] > 1e-9 for row in rates):
                raise ConstructionInputError("一般材料参照未包含本规格组的管座/垫层，请核对材料来源")
        result["quantity_items"] = [item for item in result.get("quantity_items", [])
            if not (item.get("component_id") in SUPPORT_COMPONENTS and _belongs(item, group))]
        common = {"measurement_mode": "length", "station_start": None, "station_end": None,
            "group_id": group["group_id"], "route_id": group["route_id"], "asset_id": group["asset_id"],
            "asset_name": group["name"], "scope_note": SCOPE_NOTE, "soil_basis_preserved": True}
        for values in aggregate.values():
            baseline = values["baseline_quantity"]
            if baseline < -1e-8:
                raise ConstructionInputError("一般材料基准出现负数，请核对")
            values.update(deducted_quantity=baseline*(1-ratio), added_quantity=0., final_quantity=baseline*ratio)
        for (owner, identity), baseline in general_shares.items():
            values = aggregate[identity]
            local_length = local_lengths.get(owner, total)
            item = {**common, "route_id": owner[0], "asset_id": owner[1], **{key: deepcopy(values[key]) for key in
                ("component_id", "name", "material", "grade", "unit")}, "record_id": "general",
                "scheme_title": "剩余一般构造（按长度比例分摊）", "length_m": local_length*ratio,
                "rate": baseline/local_length, "quantity": baseline*ratio, "baseline_quantity": baseline,
                "general_deduction_quantity": baseline*(1-ratio), "special_addition_quantity": 0.,
                "method": "general_material_baseline_length_proportion", "status": "length_simplified"}
            adopted.append(item)
        for row in rows:
            asset, scheme = _special_asset(group, row)
            rates, geometry = _standard_rates(asset)
            display = {**common, "record_id": row["record_id"], "scheme_id": scheme["scheme_id"],
                "scheme_title": scheme["title"], "title": scheme["title"], "length_m": row["length_m"],
                "length_source": row["length_source"], "overrides": deepcopy(row.get("overrides", {})),
                "components": [], "standard_section": geometry}
            if "object_percent" in row:
                denominator, _ = _percentage_axis(group, row)
                display.update(object_percent=row["object_percent"], object_axis_length_m=denominator)
                if row.get("percent_basis") == "whole_pipe":
                    display["percent_basis"] = "whole_pipe"
            for rate in rates:
                item = {**common, **deepcopy(rate), "record_id": row["record_id"],
                    "scheme_id": scheme["scheme_id"], "scheme_title": scheme["title"],
                    "length_m": row["length_m"], "length_source": row["length_source"],
                    "quantity": rate["rate"]*row["length_m"], "baseline_quantity": 0.,
                    "general_deduction_quantity": 0., "special_addition_quantity": rate["rate"]*row["length_m"],
                    "method": "standard_normal_section_actual_length", "status": "length_simplified",
                    "drawing_id": scheme.get("drawing_id"), "source_sha256": scheme.get("source_sha256")}
                if "object_percent" in row:
                    item.update(object_percent=row["object_percent"], object_axis_length_m=denominator)
                    if row.get("percent_basis") == "whole_pipe":
                        item["percent_basis"] = "whole_pipe"
                adopted.append(item)
                display["components"].append(deepcopy(item))
                identity = _identity(item)
                target = aggregate.setdefault(identity, {key: deepcopy(item[key]) for key in
                    ("component_id", "name", "material", "grade", "unit")} |
                    {"baseline_quantity": 0., "deducted_quantity": 0., "added_quantity": 0., "final_quantity": 0.})
                target["added_quantity"] += item["quantity"]
                target["final_quantity"] += item["quantity"]
            display["unit_rates"] = deepcopy(display["components"])
            record["rows"].append(display)
            block["rows"].append(deepcopy(display))
            standard_sections.append({"group_id": group["group_id"], "record_id": row["record_id"],
                "scheme_id": scheme["scheme_id"], "title": scheme["title"], "length_m": row["length_m"],
                "geometry": geometry, "pipe_material": asset.get("section", {}).get("material")})
        for values in aggregate.values():
            final = {**common, **values, "quantity": values["final_quantity"],
                "general_deduction_quantity": values["deducted_quantity"],
                "special_addition_quantity": values["added_quantity"]}
            record["items"].append(final)
            block["adjustments"].append(deepcopy(final))
        for table in ("assets", "rows"):
            for asset in result.get(table, []):
                if _belongs(asset, group):
                    asset.update(material_quantity_basis="soil_geometry_reference",
                        special_material_group_id=group["group_id"], material_scope_note=SCOPE_NOTE)
    result.setdefault("quantity_items", []).extend(deepcopy(adopted))
    result[KEY] = block
    result["special_pipe_material_items"] = deepcopy(adopted)
    result["special_pipe_material_sections"] = standard_sections
    result["special_pipe_materials_policy"] = SCHEMA
    result["special_pipe_materials_input_hash"] = _digest(config)
    if block["applied"]:
        result["soil_basis_quantity_items"] = deepcopy(payload.get("quantity_items", []))
        material_keys = {"concrete_volume", "bedding_volume", "all_concrete_volume", "materials"}
        material_keys.update(key for key in payload if key.startswith("component__") and key.endswith("_volume"))
        result["soil_basis_material_totals"] = {key: deepcopy(payload.get(key)) for key in material_keys}
        result["all_concrete_volume"] = math.fsum(float(item.get("quantity", 0.))
            for item in result["quantity_items"] if _is_concrete(item))
        result["bedding_volume"] = math.fsum(float(item.get("quantity", 0.)) for item in
            result["quantity_items"] if item.get("component_id") == "bedding" and item.get("unit") == "m3")
        result.setdefault("materials", {})["bedding"] = result["bedding_volume"]
        result["materials"]["all_concrete"] = result["all_concrete_volume"]
        for identifier in SUPPORT_COMPONENTS-{"bedding"}:
            result["component__"+identifier+"_volume"] = math.fsum(float(item.get("quantity", 0.))
                for item in result["quantity_items"] if item.get("component_id") == identifier and item.get("unit") == "m3")
        result["material_quantity_basis"] = "length_materials_with_preserved_soil_basis"
    return result
