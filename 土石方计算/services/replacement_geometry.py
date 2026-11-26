"""Drawing-defined stone replacement below a pipe seat in the Tingzikou sections."""
from __future__ import annotations

import math

from .section_geometry import pipe_specs
from .drawing_bindings import _get, _set


WIDTH = "construction.foundation_replacement_width"
WIDTH_ALIAS = "construction.foundation_replacement.width"
SLOPE = "construction.foundation_replacement.side_slope"
_SLOPES = ("construction.excavation_slope_left", "construction.excavation_slope_right")
WORK_SPACES = ("construction.working_space_left", "construction.working_space_right")
_TZK_DRAWING = "6ed245d8e5261051cbe34d50e0520cbcfda28c336274d24a971cf4914b35d6a9"


def replacement_geometry_paths(scheme):
    if scheme.get("source_sha256") != _TZK_DRAWING:
        return ()
    if scheme.get("scheme_id") in {"tzk_pipe_c", "tzk_box_paddy"}:
        return WIDTH, SLOPE
    if scheme.get("scheme_id") == "tzk_pipe_paddy":
        return (WIDTH,)
    return ()


def replacement_basis(scheme, path):
    if scheme.get("scheme_id") == "tzk_box_paddy":
        return "涵身外宽加左右工作面" if path == WIDTH else "原图换填侧边竖直，上下等宽"
    return "管座底宽加左右工作面" if path == WIDTH else "沿用本段已核定的左右沟槽坡比"


def _number(value):
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if not isinstance(value, bool) and math.isfinite(number) and number >= 0 else None


def confirmed_slope(asset, path, explicit=None):
    """A persisted design value or its drawing can establish an excavation slope."""
    if (explicit or {}).get(path) is not None:
        return True
    if path in asset.get("unconfirmed_group_slopes", ()):
        return False
    if any((fields or {}).get(path) is not None for fields in (asset.get("drawing_user_overrides"),
            asset.get("section_scheme_user_overrides"))):
        return True
    provenance = str((asset.get("parameter_sources") or {}).get(path) or "")
    if provenance.startswith(("用户", "原图", "图纸", "设计", "工程设计", "项目设计", "工程输入", "勘察")):
        return True
    if any(word in provenance for word in ("默认", "假定", "临时", "推荐", "估算")):
        return False
    record = (asset.get("drawing_parameter_sources") or {}).get(path) or {}
    return bool(record and not record.get("inherited") or asset.get("parameter_source") == "user_confirmed")


def project_work_space(asset, path):
    if any((asset.get(key) or {}).get(path) is not None for key in ("drawing_user_overrides", "section_scheme_user_overrides")):
        return True
    label = str((asset.get("parameter_sources") or {}).get(path) or "")
    if label.startswith(("用户", "工程设计", "项目设计", "设计", "工程输入")):
        return True
    default = (asset.get("pipe_construction_default_source_values") or {}).get(path) or {}
    if default and default.get("value") is None and default.get("adopted_value") == _get(asset, path):
        return False
    return asset.get("parameter_source") == "user_confirmed" and not any(
        word in label for word in ("图纸", "默认", "假定", "推荐", "估算"))


def _seat_width(construction, section):
    seat = construction.get("pipe_seat") or construction.get("pipe_support") or {}
    if not seat or not seat.get("enabled", True) or seat.get("bottom_width_mode") not in {
            "support_chord", "support_chord_plus_sides", "explicit", "inner_diameter_offset"}:
        return None
    left, right = (_number(construction.get("working_space_" + side)) for side in ("left", "right"))
    if left is None or right is None:
        return None
    raw = section.get("pipes") or []
    if not isinstance(raw, list) or not all(isinstance(p, dict) for p in raw):
        return None
    if section.get("pipe_spacing") is None and (len(raw) > 1 and not all(p.get("offset") is not None for p in raw)
            or not raw and _number(section.get("pipe_count", 1)) != 1):
        return None
    try:
        pipes = pipe_specs(section)
    except (ValueError, TypeError, KeyError):
        return None
    mode = seat["bottom_width_mode"]
    if mode == "explicit":
        width = _number(seat.get("bottom_width"))
        if not width:
            return None
        widths = [width] * len(pipes)
    elif mode == "inner_diameter_offset":
        extension = _number(seat.get("extension"))
        if extension is None:
            return None
        widths = [p["inner_diameter"] + 2 * extension for p in pipes]
    else:
        angle = _number(seat.get("support_angle"))
        extension = _number(seat.get("extension")) if mode == "support_chord_plus_sides" else 0.
        if angle is None or not 0 < angle < 180 or extension is None:
            return None
        widths = [p["outer_diameter"] * math.sin(math.radians(angle) / 2) + 2 * extension for p in pipes]
    bounds = [(p["offset"] - w / 2, p["offset"] + w / 2) for p, w in zip(pipes, widths)]
    return max(b for a, b in bounds) - min(a for a, b in bounds) + left + right


def derived_replacement_fields(asset, scheme, explicit=None):
    paths = replacement_geometry_paths(scheme)
    if not paths:
        return {}
    c = asset.get("construction") or {}
    values = {}
    section = asset.get("section") or {}
    if scheme.get("scheme_id") == "tzk_box_paddy":
        from .construction_rules import side_wall_thickness
        net = _number(section.get("inner_width"))
        parts = [net, *(_number(side_wall_thickness(section, side)) for side in ("left", "right")),
                 *(_number(c.get("working_space_" + side, .5)) for side in ("left", "right"))]
        if net and all(value is not None for value in parts):
            values[WIDTH] = sum(parts)
        values[SLOPE] = 0.  # Both CAD edges connect the top corners straight to the bottom (1FB5B).
        return values
    width = _seat_width(c, section)
    unresolved_space = any((explicit or {}).get(path) is None for path in asset.get("mixed_group_work_spaces", ()))
    if width is not None and not unresolved_space:
        values[WIDTH] = width
    if SLOPE in paths and not any(c.get("excavation_stages_" + side) for side in ("left", "right")) and c.get("excavation_layer_mode") != "surface_thickness":
        left, right = (_number(c.get(path.split(".")[-1])) for path in _SLOPES)
        if left is not None and right is not None and math.isclose(left, right, rel_tol=0, abs_tol=1e-10):
            if all(confirmed_slope(asset, path, explicit) for path in _SLOPES):
                values[SLOPE] = left
    return values


OUTLINE = "construction.foundation_replacement.excavation_follows_outline"


def replacement_overrides(asset, scheme, explicit, retained):
    """Normalize historical width aliases and identify previously entered dimensions."""
    from .section_scheme_catalog import drawing_workspace_dimension

    paths = replacement_geometry_paths(scheme)
    siphon_work_spaces = (scheme.get("structure_group") == "倒虹管" and
                          any(path in (scheme.get("fields") or {}) for path in WORK_SPACES))
    if not paths and not drawing_workspace_dimension(scheme) and not siphon_work_spaces:
        return explicit
    explicit = dict(explicit)
    for path in WORK_SPACES:
        if project_work_space(asset, path) and path not in asset.get("mixed_group_work_spaces", ()):
            value = _get(asset, path)
            if value is not None:
                retained.setdefault(path, value)
    if not paths:
        return explicit
    # Older parameter editors could record the entire construction group at
    # once. Split that container before resolving its individually linked fields.
    parent = "construction.foundation_replacement"
    for fields in (explicit, retained):
        if isinstance(fields.get(parent), dict):
            for key, value in fields.pop(parent).items():
                fields.setdefault(parent + "." + key, value)
    modes = asset.get("replacement_parameter_modes") or {}
    for path in paths:
        aliases = (WIDTH_ALIAS, WIDTH) if path == WIDTH else (path,)
        # A current canonical edit wins over the old nested width. Otherwise the
        # nested width has the same precedence as the historical geometry.
        edited = path if path in explicit else next((p for p in aliases if p in explicit), None)
        prior = next((retained[p] for p in aliases if retained.get(p) is not None), None)
        current = next((_get(asset, p) for p in aliases if _get(asset, p) is not None), None)
        if current is not None and (modes.get(path) != "automatic" or
                current != (asset.get("replacement_parameter_auto_values") or {}).get(path, current)):
            prior = current
        if path == WIDTH:
            retained.pop(WIDTH_ALIAS, None)
        if edited is not None:
            explicit[path] = explicit[edited]
            if path == WIDTH and (WIDTH_ALIAS in explicit or _get(asset, WIDTH_ALIAS) is not None):
                explicit[WIDTH_ALIAS] = None
        elif prior is not None:
            retained[path] = prior
    return explicit


def adopt_replacement_geometry(asset, scheme, resolved, retained):
    paths = replacement_geometry_paths(scheme)
    if not paths:
        asset.pop("replacement_parameter_modes", None)
        asset.pop("replacement_parameter_auto_values", None)
        asset.pop("replacement_schedule_dimensions", None)
        return
    suggestions = derived_replacement_fields(asset, scheme, retained)
    c = asset["construction"]
    replacement = c.setdefault("foundation_replacement", {})
    replacement.pop("width", None)
    resolved[OUTLINE] = True
    _set(asset, OUTLINE, True)
    modes = {}
    auto = {}
    for path in paths:
        manual = retained.get(path) is not None
        modes[path] = "manual" if manual else "automatic"
        if manual:
            _set(asset, path, retained[path])
        elif path in suggestions:
            value = suggestions[path]
            _set(asset, path, value)
            auto[path] = resolved[path] = value
        else:
            node, key = (c, "foundation_replacement_width") if path == WIDTH else (replacement, "side_slope")
            node.pop(key, None)
    asset["replacement_parameter_modes"] = modes
    asset["replacement_parameter_auto_values"] = auto
    if scheme.get("dimension_schedules"):
        asset["replacement_schedule_dimensions"] = _schedule_dimensions(asset)
    else:
        asset.pop("replacement_schedule_dimensions", None)


def _schedule_dimensions(asset):
    section = asset.get("section") or {}
    rows = section.get("pipes") or [{}]
    return [[section.get(key), *(pipe.get(key) for pipe in rows)]
            for key in ("nominal_diameter_m", "inner_diameter", "outer_diameter")]


def effective_replacement(asset, construction):
    """Re-evaluate linked dimensions for preliminary sections and each earthwork cut."""
    scheme = (asset.get("section_scheme_binding") or {}).get("scheme_snapshot") or {}
    active = replacement_geometry_paths(scheme)
    modes = asset.get("replacement_parameter_modes") or {}
    if not active or not modes:
        return construction
    recorded = asset.get("replacement_schedule_dimensions")
    if recorded is not None and recorded != _schedule_dimensions(asset):
        # An ordinary pipe-table edit can change the drawing's size row. Use
        # the same full resolution as adoption before preview or terrain cuts.
        from .section_scheme_bindings import draft_section_scheme_fields
        source = {**asset, "construction": construction}
        for key in ("geometry_sections", "design_profile", "alignment"):
            source.pop(key, None)
        drafted, _ = draft_section_scheme_fields(source, scheme, {})
        resolved = drafted["construction"]
        if any(_get(drafted, path) is None for path in active):
            from .contracts import ConstructionInputError
            raise ConstructionInputError("新管径的石渣换填尺寸需要补齐")
        return resolved
    previous = asset.get("replacement_parameter_auto_values") or {}
    overrides = {**(asset.get("drawing_user_overrides") or {}), **(asset.get("section_scheme_user_overrides") or {})}
    result = dict(construction)
    result["foundation_replacement"] = dict(construction.get("foundation_replacement") or {})
    linked = []
    for path in active:
        # Keep a subsequent ordinary-editor edit, including explicit values
        # that happen to be numerically equal to the old calculated size.
        if modes.get(path) != "automatic" or path not in previous or overrides.get(path) is not None:
            continue
        if _get(asset, path) != previous.get(path):
            continue
        linked.append(path)
    if linked:
        suggested = derived_replacement_fields({**asset, "construction": result}, scheme, overrides)
        for path in linked:
            if path not in suggested:
                from .contracts import ConstructionInputError
                raise ConstructionInputError("请核定石渣换填" + ("上宽" if path == WIDTH else "收坡"))
            _set({"construction": result}, path, suggested[path])
    return result
