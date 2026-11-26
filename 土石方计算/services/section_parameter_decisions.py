"""Effective construction values and their provenance for the editor and binding checks."""
from __future__ import annotations

from copy import deepcopy
import math

from .drawing_bindings import _get
from .pipe_dimensions import is_pipe_asset
from .replacement_geometry import WIDTH, WIDTH_ALIAS, replacement_geometry_paths


ORIGIN_LABELS = {"drawing": "图纸取值", "project_default": "工程默认", "imported": "导入设计",
                 "derived": "按本段计算", "manual": "手动设定", "missing": "待填写"}
_CONDITIONS = {"cut": "全挖", "mixed": "半挖半填", "fill": "全填"}
_OUTER = "section.outer_diameter"
_BOTH_SIDES = "construction.encasement.side_thickness"


def unresolved_pipe_size_field(asset, scheme, decisions):
    """Locate one upstream input when the drawing table is waiting for the pipe size."""
    outside = decisions.get(_OUTER) or {}
    section = asset.get("section") or {}
    if (not outside.get("missing") or not outside.get("required") or not is_pipe_asset(asset)
            or len(section.get("pipes") or ()) > 1 or not scheme.get("dimension_schedules")):
        return None
    from .section_scheme_bindings import hydraulic_dimensions
    from .section_scheme_catalog import match_section_scheme_size
    schedule, field, value, _ = match_section_scheme_size(scheme, hydraulic_dimensions(asset))
    if schedule and field in {"section.inner_diameter", "section.nominal_diameter_m"} and value is None:
        return "section.nominal_diameter_m"
    return None


def drawing_support_transition(asset, scheme, fields):
    """Identify incompatible supports and reusable sizes before applying a reviewed pipe drawing."""
    from .section_scheme_catalog import drawing_workspace_dimension
    if not drawing_workspace_dimension(scheme):
        return {}, {}
    construction = asset.get("construction") or {}
    seat = construction.get("pipe_seat") or construction.get("pipe_support") or {}
    encasement = construction.get("encasement") or construction.get("pipe_encasement") or {}
    selected_seat = fields.get("construction.pipe_seat.enabled") is True
    selected_wrap = fields.get("construction.encasement.enabled") is True
    if selected_seat == selected_wrap:
        return {}, {}
    required = set(scheme.get("required_fields") or ())
    replace, reuse = {}, {}
    if selected_seat:
        if encasement and encasement.get("enabled", True):
            replace["construction.encasement.enabled"] = False
        same = seat.get("material_role", "concrete") == fields.get("construction.pipe_seat.material_role", "concrete")
        for key in ("base_thickness", "extension"):
            path = "construction.pipe_seat." + key
            if path not in required or seat.get(key) is None:
                continue
            if same and seat.get("enabled", True) and (key != "extension"
                    or seat.get("bottom_width_mode") == fields.get("construction.pipe_seat.bottom_width_mode")):
                if path not in fields:
                    reuse[path] = seat[key]
            else:
                # The bed below a sand cradle is not the thickness of a concrete seat.
                replace[path] = None
    else:
        if seat and seat.get("enabled", True):
            replace["construction.pipe_seat.enabled"] = False
        if encasement.get("enabled", True):
            for key in ("side_thickness", "left_thickness", "right_thickness", "bottom_thickness", "top_thickness"):
                path = "construction.encasement." + key
                if encasement.get(key) is not None and path not in fields:
                    reuse[path] = encasement[key]
    return replace, reuse


def _scalar_or_list(values):
    return values[0] if all(v == values[0] for v in values) else values


def parameter_value(asset, path, scheme=None):
    """Return (value, alternate basis). Unequal per-pipe/per-side sizes stay distinct."""
    value = _get(asset, path)
    if isinstance(value, float) and not math.isfinite(value):
        return None, ""
    if path == "section.pipe_spacing" and value is None:
        section = asset.get("section") or {}
        pipes = section.get("pipes") or []
        if len(pipes) > 1 and all(isinstance(p, dict) and p.get("offset") is not None for p in pipes):
            from .section_geometry import clearance_from_pipe_offsets, pipe_specs
            try:
                gaps = clearance_from_pipe_offsets(pipe_specs(section))
            except (TypeError, KeyError, ValueError):
                return None, ""
            return gaps, "由逐管横偏距和施工外径计算净距"
    if path == _OUTER and is_pipe_asset(asset) and (value is None or (asset.get("section") or {}).get("pipes")):
        from .section_geometry import pipe_specs
        try:
            pipes = pipe_specs(asset.get("section") or {})
        except (ValueError, TypeError, KeyError):
            return None, ""
        diameters = [p["outer_diameter"] for p in pipes]
        return _scalar_or_list(diameters), "采用逐管施工外径" if (asset.get("section") or {}).get("pipes") else "由管道净径、壁厚及内衬核算"
    if path == _BOTH_SIDES:
        encasement = (asset.get("construction") or {}).get("encasement") or {}
        sides = [encasement.get(name) for name in ("left_thickness", "right_thickness")]
        if all(v is not None for v in sides):
            return _scalar_or_list(sides), "采用已设左侧、右侧厚度"
    if value is None and path in {"section.wall_thickness_left", "section.wall_thickness_right"}:
        wall = _get(asset, "section.wall_thickness")
        if wall is not None:
            return wall, "沿用断面统一墙厚"
    if value is None and path == WIDTH and replacement_geometry_paths(scheme or {}):
        width = _get(asset, WIDTH_ALIAS)
        if width is not None:
            return width, "沿用本段已设换填上宽"
    return value, ""


def parameter_missing(path, value):
    if path.endswith("_confirmed"):
        return value is not True
    if value is None or (isinstance(value, str) and not value.strip()):
        return True
    if path.split(".")[-1].endswith("_profile") or path == "construction.floor_steps":
        return not (value.get("points") if isinstance(value, dict) else value)
    return path == "section.discrete_components" and not value


def _condition_fields(scheme):
    conditions = {}
    def add(node, label):
        for path in node.get("required_fields") or ():
            names = conditions.setdefault(path, [])
            if label not in names:
                names.append(label)
    for key, variant in (scheme.get("terrain_variants") or {}).items():
        label = _CONDITIONS.get(key, key)
        add(variant, label)
        for selector in variant.get("selectors") or ():
            add(selector, label + " · " + (selector.get("title") or "图纸条件分支"))
    for selector in scheme.get("selectors") or ():
        add(selector, selector.get("title") or "图纸条件分支")
    return conditions


def _owner(mapping, path):
    """Find an explicit field or parent object, including edits to a pipe list."""
    owner = path
    while owner:
        if owner in mapping:
            return owner
        owner = owner.rpartition("[")[0] if owner.endswith("]") else owner.rpartition(".")[0]
    return None


def _imported_value(asset, path, value):
    original = asset.get("original_fields") or {}
    records = original.get("records") or []
    first = records[0] if records and isinstance(records[0], dict) else {}
    if _get(original, path) == value or _get(first, path) == value:
        return True
    if not path.startswith("section."):
        return False
    # Older workbench imports kept the frozen hydraulic node, not the
    # translated field name. Use the same source keys as the importer.
    from ..adapters.source_adapters import PROFILE_SIZE_FIELDS
    name = path.removeprefix("section.")
    params = first.get("section_params") or {}
    inputs = [params.get(k) for k in PROFILE_SIZE_FIELDS.get(name, ())]
    if name == "inner_height":
        inputs.append(first.get("structure_height"))
    if name in {"inner_diameter", "nominal_diameter_m", "hydraulic_inner_diameter_m"}:
        inputs.append(original.get("D"))
    for candidate in inputs:
        try:
            if candidate is not None and float(candidate) == float(value):
                return True
        except (TypeError, ValueError):
            continue
    return False


def _origin(asset, scheme, path, value, alternate, overrides, fields):
    data = asset.get("parameter_sources") or {}
    label = str(data.get(_owner(data, path)) or "")
    user = _owner(overrides, path)
    if alternate:
        return "derived", alternate
    if user is not None and overrides[user] is not None:
        return "manual", "本段已设置"
    mode = (asset.get("replacement_parameter_modes") or {}).get(path)
    if mode:
        from .replacement_geometry import replacement_basis
        if mode == "automatic":
            return "derived", replacement_basis(scheme, path)
        return "manual", "本段已设置"
    evidence = (asset.get("section_scheme_parameter_sources") or {}).get(path) or {}
    if evidence.get("scheme_id") == scheme.get("scheme_id") and evidence.get("adopted_value") == value:
        if evidence.get("geometry_derived"):
            return "derived", evidence.get("geometry_basis") or label
        if evidence.get("user_override"):
            return "manual", label
        if evidence.get("inherited"):
            return "project_default", "沿用工程参数"
    if path in fields and value == fields[path]:
        from .pipe_construction_defaults import POLICY
        if scheme.get("pipe_construction_default_policy") == POLICY and path in (
                "construction.working_space_left", "construction.working_space_right", "construction.pipe_seat.base_thickness"):
            return "project_default", "工程表7.2"
        return "drawing", scheme.get("source_title") or scheme.get("title") or "图纸断面"
    if label.startswith("用户"):
        return "manual", label
    if label.startswith(("图纸", "原图")):
        return "drawing", label
    if label.startswith(("施工占位", "明确水力内径", "由设计", "由现有", "水力内径＋", "水力设计内半径", "依据本段")):
        return "derived", label
    if any(token in label for token in ("默认", "假定", "沿用当前工程")):
        return "project_default", label
    if ("管径D(m)" in label or label.startswith(("Excel", "水面线", "设计来源", "当前水面线", "导入", "专项设计"))
            or _imported_value(asset, path, value)):
        return "imported", label or "导入设计断面"
    if asset.get("parameter_source") == "user_confirmed":
        return "manual", label or "本工程已确认"
    return "project_default", label or "工程已有参数"


def section_parameter_decisions(asset, scheme, required=None, overrides=None, resolved_fields=None):
    """Use a drafted candidate when supplied. Conditional inputs are separate from adoption requirements.

    With no resolved_fields, resolve the selected drawing against the asset; a saved
    binding is read as adopted. The input, source drawing and saved history stay intact.
    """
    scheme = scheme or {}
    explicit = overrides or {}
    if resolved_fields is None:
        binding = asset.get("section_scheme_binding") or {}
        if scheme.get("scheme_id") and (binding.get("scheme_id") != scheme["scheme_id"] or explicit):
            from .section_scheme_bindings import draft_section_scheme_fields
            asset, resolved_fields = draft_section_scheme_fields(asset, scheme, explicit)
        else:
            resolved_fields = binding.get("resolved_fields") or scheme.get("fields") or {}
    unconditional = set(scheme.get("required_fields") or ()) | set((scheme.get("constraints") or {}).get("required_fields") or ())
    if scheme.get("source_review_required"):
        unconditional.add("section.source_review_confirmed")
    conditional = _condition_fields(scheme)
    if required is not None:
        unconditional.update(set(required) - conditional.keys())
    specified = {**(asset.get("drawing_user_overrides") or {}), **(asset.get("section_scheme_user_overrides") or {}), **explicit}
    paths = set(resolved_fields) | unconditional | conditional.keys() | specified.keys()
    for group in ("section", "construction"):
        paths.update(group + "." + name for name, val in (asset.get(group) or {}).items()
                     if isinstance(val, (float, int, str)) or val is None)
    section = asset.get("section") or {}
    for index, pipe in enumerate(section.get("pipes") or [], 1):
        if isinstance(pipe, dict):
            paths.update(f"section.pipes[{index}].{key}" for key in pipe)
    if section.get("pipes"):
        paths.add("section.pipe_spacing")
    for name in ("pipe_seat", "encasement", "foundation_replacement"):
        component = (asset.get("construction") or {}).get(name)
        if isinstance(component, dict):
            paths.update("construction." + name + "." + key for key in component)
    decisions = {}
    for path in sorted(paths):
        value, alternate = parameter_value(asset, path, scheme)
        missing = parameter_missing(path, value)
        origin, basis = ("missing", "") if missing else _origin(asset, scheme, path, value, alternate, specified, resolved_fields)
        title = "工程已有值" if origin == "project_default" and basis == "工程已有参数" else ORIGIN_LABELS[origin]
        decisions[path] = {"value": deepcopy(value), "origin": origin, "origin_label": title,
                           "basis": basis, "required": path in unconditional, "missing": missing,
                           "conditional": path in conditional and path not in unconditional,
                           "conditions": list(conditional.get(path, ()))}
    return decisions
