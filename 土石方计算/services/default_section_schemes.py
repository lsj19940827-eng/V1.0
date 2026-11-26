"""General buried sections fill only ranges without an explicit section choice.

The persisted binding is the same binding consumed by preview and calculation;
no saved result is rewritten and no hydraulic dimensions are invented here.
"""
from __future__ import annotations

from copy import deepcopy

from .earthwork_scope import trenchless_method
from .section_scheme_catalog import is_selectable_section_scheme
from .section_scheme_bindings import (
    _get, _root, _route, _targets, _restore, _overrides, _scheme_fields,
    apply_section_scheme, hydraulic_dimensions, validate_section_scheme_bindings,
)

_DEFAULT_IDS = {"circular_siphon": "tzk_siphon_a",
                "circular_culvert": "tzk_pipe_b", "circular_channel": "tzk_pipe_b"}


def default_section_scheme(asset, schemes=None):
    """Recommend the general family, with the siphon family before pipe families."""
    identifier = _DEFAULT_IDS.get(asset.get("section_type"))
    if identifier is None or asset.get("kind") == "tunnel":
        return None
    if schemes is None:
        from .section_scheme_catalog import load_section_schemes
        schemes = load_section_schemes()
    candidates = [s for s in schemes if asset.get("section_type") in s.get("section_types", [])
                  and is_selectable_section_scheme(s, asset.get("section_type"))
                  and s.get("condition") == "general" and s.get("calculation_status") != "not_in_scope"]
    selected = deepcopy(next((s for s in candidates if s.get("scheme_id") == identifier), None)
                        or (candidates[0] if candidates else None))
    if selected and selected.get("scheme_id") == identifier:
        from .pipe_construction_defaults import POLICY
        # Mark only a newly requested general default. Saved source snapshots
        # without this marker keep their original exact-table interpretation.
        selected["pipe_construction_default_policy"] = POLICY
    return selected


def _explicit_construction(asset):
    """Unbound historical custom foundations are already engineering decisions."""
    c, section = asset.get("construction") or {}, asset.get("section") or {}
    seat = c.get("pipe_seat") or c.get("pipe_support") or {}
    encasement = c.get("encasement") or c.get("pipe_encasement") or {}
    return (bool(encasement) and encasement.get("enabled", True)
            or bool(seat) and (not seat.get("enabled", True) or seat.get("material_role", "concrete") != "bedding")
            or c.get("excavation_base_mode") == "offset"
            or bool(c.get("foundation_replacement") or c.get("foundation_replacement_thickness")
                    or c.get("floor_steps") or section.get("gabion_profile") or section.get("rockfill_profile")
                    or section.get("discrete_components")))


def needs_default_section_scheme(asset):
    """Cheap read-only predicate, also used to invalidate affected old results."""
    return (asset.get("section_type") in _DEFAULT_IDS and asset.get("kind") != "tunnel"
            and not asset.get("calculation_deferred")
            and asset.get("enabled", True)
            and (asset.get("construction") or {}).get("installation_mode", "buried") in {None, "buried"}
            and not trenchless_method(asset)
            and not (asset.get("section_scheme_binding") or asset.get("section_scheme_id")
                     or asset.get("drawing_binding") or asset.get("drawing_bindings"))
            and not _explicit_construction(asset))


def _has_global_binding(inputs, network, asset):
    route, root = _route(network), _root(asset)
    start, end = asset.get("station_start"), asset.get("station_end")
    for record in [*inputs.get("section_scheme_bindings", []), *inputs.get("drawing_bindings", [])]:
        if str(record.get("route_id") or record.get("network_id") or "") not in {route, str(network.get("network_id") or "")}:
            continue
        if str(record.get("asset_id") or "") != root:
            continue
        a, b = record.get("station_start"), record.get("station_end")
        if any(v is None for v in (a, b, start, end)) or (b > start + 1e-7 and a < end - 1e-7):
            return True
    return False


def pending_default_section_assets(inputs):
    return [(network, asset) for network in inputs.get("networks", []) for asset in network.get("assets", [])
            if needs_default_section_scheme(asset) and not _has_global_binding(inputs, network, asset)]


def _general_fields(asset, scheme):
    """A family supplies shape; existing project dimensions remain authoritative."""
    from .section_scheme_catalog import resolve_section_scheme_fields
    fields = resolve_section_scheme_fields(scheme, hydraulic_dimensions=hydraulic_dimensions(asset))
    overrides = {}
    for path in set(fields) | {p for p in scheme.get("required_fields", []) if p.startswith("construction.")}:
        current = _get(asset, path)
        if current is not None:
            overrides[path] = deepcopy(current)
    # The same base depth now belongs to the full-width 120-degree sand bed.
    # Geometry unions the former rectangular bed with this region exactly once.
    base = "construction.pipe_seat.base_thickness"
    flat = _get(asset, "construction.bedding_thickness")
    automatic_flat = asset.get("pipe_construction_default_source_values", {}).get("construction.bedding_thickness") or {}
    no_extra_flat_layer = (automatic_flat and automatic_flat.get("value") is None
                          and flat == automatic_flat.get("adopted_value"))
    if _get(asset, base) is None and flat is not None and not no_extra_flat_layer:
        overrides[base] = deepcopy(_get(asset, "construction.bedding_thickness"))
    return overrides


def ensure_default_section_schemes(inputs, schemes=None, *, cancelled=None):
    """Return a new input and report; preserve every explicit range and parameter."""
    result = deepcopy(inputs)
    report = {"changed": False, "applied_count": 0, "applied": [], "errors": []}
    pending = pending_default_section_assets(result)
    if not pending:
        return result, report
    validation = validate_section_scheme_bindings(result)
    if not validation["valid"]:
        report["errors"] = validation["errors"]
        return result, report
    if schemes is None:
        from .section_scheme_catalog import load_section_schemes
        schemes = load_section_schemes()
    identities = {(_route(n), _root(a), a.get("station_start"), a.get("station_end")): a.get("asset_id")
                  for n in result.get("networks", []) for a in n.get("assets", [])}
    for network, asset in pending:
        if cancelled and cancelled():
            raise InterruptedError("已取消施工断面准备")
        scheme = default_section_scheme(asset, schemes)
        # Supplied test/custom catalogs are selectable in the UI, but are never
        # silently promoted into the program's default construction convention.
        if not scheme or scheme.get("scheme_id") != _DEFAULT_IDS[asset["section_type"]]:
            continue
        route, root = _route(network), _root(asset)
        try:
            attempt = deepcopy(result)
            actual = next(a for n in attempt["networks"] if _route(n) == route
                          for a in n["assets"] if _root(a) == root and a["station_start"] == asset["station_start"]
                          and a["station_end"] == asset["station_end"])
            # This is an exact conversion of supplied wall/bore dimensions.
            # DN-only inputs are resolved by their explicit envelope contract.
            if _get(asset, "section.outer_diameter") is None:
                from .section_geometry import pipe_specs
                pipes = pipe_specs(asset.get("section") or {})
                diameters = {p["outer_diameter"] for p in pipes}
                if len(diameters) == 1:
                    actual.setdefault("section", {})["outer_diameter"] = diameters.pop()
                    actual.setdefault("parameter_sources", {})["section.outer_diameter"] = "由现有管道内外径、已输入壁厚及内衬核算"
            from .pipe_construction_defaults import apply_pipe_construction_defaults
            # Existing rectangular bedding remains the input's stated support
            # depth; new imports already hold the current table's sand depth.
            original_defaults = deepcopy(actual)
            depth = (_get(actual, "construction.bedding_thickness")
                     if _get(actual, "construction.pipe_seat.base_thickness") is None else None)
            filled = apply_pipe_construction_defaults(actual, support_mode="sand_bedding")
            if depth is not None:
                actual.setdefault("construction", {}).setdefault("pipe_seat", {})["base_thickness"] = depth
            # A later special family must restore the actual design source,
            # not mistake an automatically added default for an explicit input.
            saved_sources = actual.setdefault("section_scheme_source_values", {})
            common_controls = {"construction.working_space_left", "construction.working_space_right",
                               "construction.working_space_reference", "construction.bedding_thickness",
                               "construction.bedding_extension"}
            for path, record in actual.get("pipe_construction_default_source_values", {}).items():
                if (path not in common_controls and _get(actual, path) == record.get("adopted_value")
                        and str(actual.get("parameter_sources", {}).get(path, "")).startswith("管道施工默认值：")):
                    saved_sources.setdefault(path, {"present": bool(record.get("present")),
                        "value": deepcopy(record.get("value"))})
            for path in filled["applied_fields"]:
                if path in common_controls:
                    continue
                parent, _, key = path.rpartition(".")
                container = _get(original_defaults, parent)
                saved_sources.setdefault(path, {"present": isinstance(container, dict) and key in container,
                    "value": deepcopy(_get(original_defaults, path))})
            result = apply_section_scheme(attempt, route_id=route, asset_id=root, scheme=scheme,
                station_start=asset.get("station_start"), station_end=asset.get("station_end"),
                inherited_fields=_general_fields(actual, scheme))
        except (ValueError, KeyError, TypeError) as error:
            report["errors"].append(f"{asset.get('name') or root}：一般埋管段待补齐：{error}")
            continue
        report["applied"].append({"route_id": route, "asset_id": root,
            "station_start": asset["station_start"], "station_end": asset["station_end"],
            "scheme_id": scheme["scheme_id"]})
    report["applied_count"] = len(report["applied"])
    report["changed"] = bool(report["applied"])
    for network in result.get("networks", []):
        for asset in network.get("assets", []):
            identity = identities.get((_route(network), _root(asset), asset.get("station_start"), asset.get("station_end")))
            if identity:
                asset["asset_id"] = identity
    return result, report


def restore_default_section_range(inputs, *, route_id, asset_id, station_start, station_end, schemes=None):
    """Remove a local exception without leaking its overridden support components."""
    result = deepcopy(inputs)
    _, parts, start, end = _targets(result, route_id, asset_id, station_start, station_end)
    for original in parts:
        scheme = default_section_scheme(original, schemes)
        if scheme is None:
            raise ValueError("当前结构没有一般埋管断面")
        source = deepcopy(original)
        prior = original.get("section_scheme_binding") or {}
        old_fields = set(original.get("section_scheme_applied_fields", []))
        if prior:
            old_fields.update(_scheme_fields(prior.get("scheme_snapshot") or {})[2])
            old_fields.update(prior.get("resolved_fields", {}))
        retained = _overrides(original)
        # Pipe sizes and ordinary excavation controls survive removal of a
        # special foundation; the old family's component fields are restored.
        common = {"construction.working_space_left", "construction.working_space_right"}
        clear = {path for path in old_fields | set(retained)
                 if path not in common and (path in old_fields or path.startswith((
                     "construction.pipe_seat.", "construction.encasement.", "construction.foundation_replacement",
                     "section.gabion_profile", "section.rockfill_profile", "section.discrete_components")))}
        # Never erase dimensions explicitly supplied in the parameter editor.
        clear = {path for path in clear if not path.startswith(("section.inner_", "section.outer_",
                 "section.nominal_", "section.wall_thickness", "section.pipes["))}
        _restore(source, clear | ((old_fields & common) - set(retained)))
        overrides = {path: None for path in clear}
        # A bridge's installation override must return to the buried family.
        overrides["construction.installation_mode"] = "buried"
        result = apply_section_scheme(result, route_id=route_id, asset_id=asset_id, scheme=scheme,
            station_start=max(start, original["station_start"]), station_end=min(end, original["station_end"]),
            overrides=overrides, inherited_fields=_general_fields(source, scheme))
    return result
