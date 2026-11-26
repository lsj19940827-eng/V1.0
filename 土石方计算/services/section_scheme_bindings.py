"""Explicit, replayable section schemes on real ranges of a design asset.

All public mutations return a copy.  A drawing's example hydraulic dimensions
never replace live design values; only explicit user overrides may do that.
Terrain variants are retained for the calculator to choose at each section.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata

from .drawing_bindings import _get, _set, _slice, _HYDRAULIC
from .earthwork_scope import (
    require_disjoint_trenchless_ranges, trenchless_exclusions, trenchless_intersections, trenchless_method,
)
from .pipe_dimensions import is_pipe_asset
from .section_scheme_catalog import is_selectable_section_scheme
from .sluice_gate import is_sluice_gate
from .replacement_geometry import (WIDTH, WIDTH_ALIAS, OUTLINE, WORK_SPACES, derived_replacement_fields, effective_replacement,
    replacement_geometry_paths, replacement_basis, replacement_overrides, adopt_replacement_geometry)

SCHEMA = "section_scheme_binding_1.0"
_EPS = 1e-7
_PATH = re.compile(r"(?:section|construction)\.[A-Za-z_]\w*(?:\[[1-9]\d*\])?(?:\.[A-Za-z_]\w*)*")


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf8")).hexdigest()


def _finite(value, label="桩号"):
    if isinstance(value, bool):
        raise ValueError(f"{label}须为有限数字")
    try:
        result = float(value)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{label}须为有限数字") from error
    if not math.isfinite(result):
        raise ValueError(f"{label}须为有限数字")
    return result


def parse_station(text, prefix=None):
    """Parse metres or a labelled chainage; conversion of broken chains is external."""
    if isinstance(text, (int, float)):
        return _finite(text)
    value = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or "")))
    value = re.sub(r"(?:米|m)$", "", value, flags=re.I)
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value):
        return _finite(value)
    match = re.fullmatch(r"([^\d+\-.]*)(-?\d+)\+(\d+(?:\.\d*)?)", value)
    if not match:
        raise ValueError("请输入米数（如 180）或桩号（如 K0+180）")
    label, kilometre, metres = match.groups()
    if prefix is not None and label and label.casefold() != str(prefix).strip().casefold():
        raise ValueError(f"桩号前缀应为 {prefix}，请核对所属线路")
    remainder = _finite(metres)
    if remainder >= 1000:
        raise ValueError("加号后的米数须小于1000；例如 1+020 表示1020米")
    sign = -1 if kilometre.startswith("-") else 1
    return sign * (abs(int(kilometre)) * 1000 + remainder)


def format_station(value, prefix="K"):
    number = _finite(value)
    # Millimetres also handle rounding across a kilometre boundary correctly.
    millimetres = round(abs(number) * 1000)
    kilometres, rest = divmod(millimetres, 1000000)
    metres, fraction = divmod(rest, 1000)
    suffix = (f".{fraction:03d}".rstrip("0") if fraction else "")
    return f"{prefix or ''}{'-' if number < 0 else ''}{kilometres}+{metres:03d}{suffix}"


def _route(network):
    return str(network.get("route_id") or network.get("network_id") or "")


def _root(asset):
    return str(asset.get("section_scheme_root_asset_id") or asset.get("drawing_root_asset_id")
               or asset.get("parent_asset_id") or asset.get("asset_id") or "")


def list_asset_groups(inputs, *, skip_incomplete=False):
    groups = {}
    for network in inputs.get("networks", []):
        route = _route(network)
        for asset in network.get("assets", []):
            if is_sluice_gate(asset):
                continue
            root = _root(asset)
            if not route or not root:
                continue
            try:
                start, end = _finite(asset.get("station_start")), _finite(asset.get("station_end"))
            except ValueError:
                if skip_incomplete:
                    continue
                raise
            key = (route, root)
            row = groups.setdefault(key, {"route_id": route, "asset_id": root,
                "name": asset.get("base_name") or asset.get("name") or root,
                "route_name": network.get("name", route), "section_type": asset.get("section_type"),
                "station_start": start, "station_end": end, "parts": []})
            row["station_start"] = min(row["station_start"], start)
            row["station_end"] = max(row["station_end"], end)
            row["parts"].append(deepcopy(asset))
    for row in groups.values():
        row["parts"].sort(key=lambda part: part["station_start"])
    return list(groups.values())


def scheme_candidates(asset, schemes):
    """Recommend compatible structure families; never select a terrain condition."""
    return [deepcopy(scheme) for scheme in schemes
            if asset.get("section_type") in scheme.get("section_types", [])
            and is_selectable_section_scheme(scheme, asset.get("section_type"))
            and scheme.get("calculation_status") != "not_in_scope"]


def _field_paths(fields, *, template=False):
    if not isinstance(fields, dict):
        raise ValueError("参数须为字段路径到取值的字典")
    result, ignored = {}, []
    for path, value in fields.items():
        if not isinstance(path, str) or not _PATH.fullmatch(path):
            raise ValueError(f"断面参数路径不受支持：{path}")
        key = path.split(".")[1].split("[", 1)[0]
        if template and key in _HYDRAULIC and path.startswith("section."):
            ignored.append(path)
        else:
            # Reject non-finite nested values before editing engineering input.
            try:
                _digest(value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"参数值无效：{path}") from error
            result[path] = deepcopy(value)
    return result, ignored


def hydraulic_dimensions(asset):
    """Flatten actual dimensions for exact source-table lookup, without DN guesses."""
    result = {"section_type": asset.get("section_type"), "asset_kind": asset.get("kind")}
    def visit(value, path):
        if isinstance(value, dict):
            for name, child in value.items():
                visit(child, path + "." + name)
        elif isinstance(value, list):
            for index, child in enumerate(value, 1):
                visit(child, f"{path}[{index}]")
        else:
            result[path] = value
    visit(asset.get("section", {}), "section")
    pipes = (asset.get("section") or {}).get("pipes")
    if pipes and all(isinstance(pipe, dict) for pipe in pipes):
        result["pipe_row_count"] = len(pipes)
        for name in ("nominal_diameter_m", "inner_diameter"):
            rows = [pipe.get(name) for pipe in pipes]
            if result.get("section." + name) is None and rows[0] is not None and all(v == rows[0] for v in rows):
                result["section." + name] = rows[0]
        if any(pipe.get("outer_diameter") is None for pipe in pipes):
            from .section_geometry import pipe_specs
            try:
                adopted = pipe_specs(asset["section"])
            except (TypeError, KeyError, ValueError):
                adopted = []
            for index, pipe in enumerate(adopted, 1):
                result[f"section.pipes[{index}].outer_diameter"] = pipe["outer_diameter"]
    if result.get("section.outer_diameter") is None:
        from .section_parameter_decisions import parameter_value
        outside, _ = parameter_value(asset, "section.outer_diameter")
        if isinstance(outside, (int, float)):
            result["section.outer_diameter"] = outside
    return result


def _remove(asset, path):
    parent, _, key = path.rpartition(".")
    container = _get(asset, parent)
    if isinstance(container, dict):
        container.pop(key, None)


def _capture(asset, paths):
    saved = asset.setdefault("section_scheme_source_values", {})
    for path in paths:
        if path not in saved:
            parent, _, key = path.rpartition(".")
            container = _get(asset, parent)
            saved[path] = {"present": isinstance(container, dict) and key in container,
                           "value": deepcopy(_get(asset, path))}


def _restore(asset, paths):
    sources = asset.get("section_scheme_source_values", {})
    for path in paths:
        if path not in sources:
            continue
        item = sources[path]
        if item["present"]:
            _set(asset, path, item["value"])
        else:
            _remove(asset, path)


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b


def _matches_user_override(asset,path):
    """A saved parent-object edit also owns its nested scheme fields."""
    sources=asset.get("parameter_sources") or {}
    for user_path,user_value in (asset.get("drawing_user_overrides") or {}).items():
        if path!=user_path and not path.startswith(user_path+"."):
            continue
        if str(sources.get(user_path,"")).startswith("用户") and _same(_get(asset,user_path),user_value):
            return True
    return False


def _overrides(asset):
    saved = deepcopy(asset.get("drawing_user_overrides", {}))
    saved.update(deepcopy(asset.get("section_scheme_user_overrides", {})))
    # Also capture edits made in the existing parameter editor after binding.
    for path, record in asset.get("section_scheme_parameter_sources", {}).items():
        current = _get(asset, path)
        if not _same(current, record.get("adopted_value")):
            saved[path] = deepcopy(current)
    for path, source in asset.get("parameter_sources", {}).items():
        if _PATH.fullmatch(path) and str(source).startswith("用户"):
            saved[path] = deepcopy(_get(asset, path))
    return _field_paths(saved)[0]


def _scheme_fields(scheme):
    common, ignored = _field_paths(scheme.get("fields") or {}, template=True)
    variants = deepcopy(scheme.get("terrain_variants") or {})
    if not isinstance(variants, dict):
        raise ValueError("地形工况方案须以 cut、mixed、fill 登记")
    all_paths = set(common)
    for condition, variant in variants.items():
        if condition not in {"cut", "mixed", "fill"} or not isinstance(variant, dict):
            raise ValueError("地形工况方案仅支持 cut、mixed、fill")
        fields, skipped = _field_paths(variant.get("fields") or {}, template=True)
        variant["fields"] = fields
        ignored.extend(skipped)
        all_paths.update(fields)
    return common, variants, all_paths, sorted(set(ignored))


def _check_constraints(asset, scheme):
    constraints = scheme.get("constraints") or {}
    if not isinstance(constraints, dict):
        raise ValueError("方案适用条件须为字典")
    required = set(scheme.get("required_fields") or []) | set(constraints.get("required_fields") or [])
    if scheme.get("calculation_status") == "requires_parameters" and not required:
        raise ValueError("本方案尚未具备可执行参数，请先补齐对应断面的构造资料")
    from .section_parameter_decisions import parameter_value, parameter_missing
    missing = [path for path in sorted(required) if not path.endswith("_confirmed")
               and parameter_missing(path, parameter_value(asset, path, scheme)[0])]
    if missing:
        if "section.outer_diameter" in missing and (asset.get("section") or {}).get("pipes"):
            from .section_geometry import pipe_specs
            pipe_specs(asset["section"])
        raise ValueError("本区段采用方案仍需补齐参数：" + "、".join(missing))
    if replacement_geometry_paths(scheme):
        construction = asset.get("construction") or {}
        if (asset.get("section_scheme_binding") or {}).get("scheme_id") == scheme.get("scheme_id"):
            construction = effective_replacement(asset, construction)
        replacement = construction.get("foundation_replacement") or {}
        width = _finite(replacement.get("width", construction.get("foundation_replacement_width")), "石渣换填上宽")
        slope = _finite(replacement.get("side_slope"), "石渣换填收坡")
        depth = _finite(replacement.get("thickness", _get(asset, "construction.foundation_replacement_thickness")), "石渣换填厚度")
        if width <= 0 or depth < 0 or slope < 0 or width <= 2 * slope * depth:
            raise ValueError("石渣换填厚度及收坡须非负，上宽和收坡后底宽须大于0")
    if scheme.get("source_review_required") and _get(asset, "section.source_review_confirmed") is not True:
        raise ValueError("须先核定本工程可采用此原图：" + str(scheme["source_review_required"]))
    for path in required:
        if path.endswith("_confirmed") and _get(asset, path) is not True:
            raise ValueError("须明确确认原图疑点：" + path)
    for field, bounds in (constraints.get("field_ranges") or {}).items():
        actual, _ = parameter_value(asset, field, scheme)
        values = [_finite(item, field) for item in (actual if isinstance(actual, list) else [actual])]
        if bounds.get("min") is not None and min(values) < float(bounds["min"]):
            raise ValueError(f"{field} 小于方案适用下限")
        if bounds.get("max") is not None and max(values) > float(bounds["max"]):
            raise ValueError(f"{field} 超过方案适用上限")


def _targets(inputs, route_id, asset_id, start, end, *, special_pipe_scheme=False):
    networks = [network for network in inputs.get("networks", [])
                if str(route_id) in {_route(network), str(network.get("network_id") or "")}]
    if len(networks) != 1:
        raise ValueError("无法唯一确定所属线路，请重新选择工程对象")
    network = networks[0]
    prefix = network.get("station_prefix")
    start, end = parse_station(start, prefix), parse_station(end, prefix)
    if start >= end - _EPS:
        raise ValueError("起桩必须小于止桩；单桩调整请先明确实际影响区间")
    family = [asset for asset in network.get("assets", []) if _root(asset) == str(asset_id)]
    if special_pipe_scheme and any(is_pipe_asset(asset) for asset in family):
        excluded = trenchless_intersections(trenchless_exclusions(inputs), network, -math.inf, math.inf)
        crossed = dict.fromkeys((left, right) for left, right in excluded if min(end, right) - max(start, left) > _EPS)
        if crossed:
            ranges = "、".join(f"{format_station(left, prefix or 'K')} ～ {format_station(right, prefix or 'K')}"
                             for left, right in crossed)
            raise ValueError(f"所选范围包含非开挖区段 {ranges}，请按两侧明挖范围分行填写")
    targets = sorted((asset for asset in family if asset["station_end"] > start + _EPS
                      and asset["station_start"] < end - _EPS), key=lambda asset: asset["station_start"])
    if not targets or start < min(asset["station_start"] for asset in targets) - _EPS:
        raise ValueError("起止桩号超出所选工程对象范围")
    cursor = start
    for asset in targets:
        left, right = max(start, asset["station_start"]), min(end, asset["station_end"])
        if left > cursor + _EPS:
            raise ValueError("所选范围跨越不连续区段，请分别设置")
        if left < cursor - _EPS:
            raise ValueError("所选工程对象已有重叠区段，须先核对")
        if not asset.get("enabled", True):
            raise ValueError("所选范围包含已停用区段")
        if trenchless_method(asset):
            raise ValueError("所选范围包含顶管或定向钻等非开挖段，不能套用普通开挖断面")
        cursor = right
    if cursor < end - _EPS:
        raise ValueError("起止桩号超出所选工程对象范围")
    require_disjoint_trenchless_ranges(network.get("assets", []))
    return network, targets, start, end


def _record_hash(record):
    return _digest({key: value for key, value in record.items() if key != "binding_sha256"})


def _clip_record(record, start, end):
    result = deepcopy(record)
    result.update(station_start=start, station_end=end)
    result["binding_sha256"] = _record_hash(result)
    return result


def _trim_records(records, route, root, start, end):
    result = []
    for record in records:
        a, b = record["station_start"], record["station_end"]
        if (record.get("route_id"), record.get("asset_id")) != (route, root) or b <= start + _EPS or a >= end - _EPS:
            result.append(deepcopy(record))
        else:
            if a < start - _EPS:
                result.append(_clip_record(record, a, start))
            if b > end + _EPS:
                result.append(_clip_record(record, end, b))
    return result


def _trim_legacy_records(records, network, root, start, end):
    """A new explicit scheme replaces old project-bound templates on this span."""
    result = []
    routes = {_route(network), str(network.get("network_id") or "")}
    for record in records:
        a, b = record.get("station_start"), record.get("station_end")
        if (str(record.get("network_id", record.get("route_id", ""))) not in routes
                or str(record.get("asset_id")) != root or a is None or b is None
                or b <= start + _EPS or a >= end - _EPS):
            result.append(deepcopy(record))
            continue
        for left, right in ((a, min(b, start)), (max(a, end), b)):
            if right > left + _EPS:
                kept = deepcopy(record)
                kept.update(station_start=left, station_end=right)
                result.append(kept)
    return result


def _restore_legacy_fields(asset, retained):
    if asset.get("section_scheme_binding") or not asset.get("drawing_bindings"):
        return
    for path, evidence in asset.get("drawing_parameter_sources", {}).items():
        if path in retained or not _PATH.fullmatch(path):
            continue
        if "original_value" not in evidence:
            continue
        if evidence["original_value"] is None:
            _remove(asset, path)
        else:
            _set(asset, path, evidence["original_value"])
        asset.setdefault("parameter_sources", {}).pop(path, None)


def _metadata(asset, record):
    scheme = record["scheme_snapshot"]
    asset["section_scheme_binding"] = deepcopy(record)
    asset["section_scheme_id"] = scheme["scheme_id"]
    asset["section_scheme_terrain_variants"] = deepcopy(scheme.get("terrain_variants") or {})
    asset["section_scheme_selectors"] = deepcopy(scheme.get("selectors") or [])
    asset["section_scheme_user_overrides"] = deepcopy(record["overrides"])
    source = {"schema": SCHEMA, "scheme_id": scheme["scheme_id"], "template_id": scheme["scheme_id"],
        "template_version": str(scheme.get("version", "1")), "title": scheme.get("title", scheme["scheme_id"]),
        "drawing_id": scheme.get("drawing_id", ""), "source_sha256": scheme.get("source_sha256", ""),
        "source_handles": deepcopy(scheme.get("source_handles") or []),
        "station_start": asset["station_start"], "station_end": asset["station_end"],
        "scope_label": scheme.get("condition", ""), "scheme_sha256": record["scheme_sha256"]}
    asset["drawing_binding"] = source
    existing = [row for row in asset.get("drawing_bindings", []) if row.get("schema") != SCHEMA]
    asset["drawing_bindings"] = existing + [deepcopy(source)]
    asset["section_scheme_material_sources"] = deepcopy(source)


def _preview_names(scheme):
    names = set()
    def visit(value):
        if isinstance(value, dict):
            if value.get("source_preview"):
                names.add(str(value["source_preview"]))
            for key in ("terrain_variants", "selectors"):
                child = value.get(key)
                if isinstance(child, dict):
                    for item in child.values():
                        visit(item)
                elif isinstance(child, list):
                    for item in child:
                        visit(item)
    visit(scheme)
    return sorted(names)


def _preserve_previews(inputs, scheme):
    from .section_scheme_catalog import section_scheme_catalog_path
    from .drawing_bindings import _file_digest
    root = section_scheme_catalog_path().parent.resolve()
    files = inputs.setdefault("input_files", [])
    for name in _preview_names(scheme):
        existing = next((row for row in files if row.get("role") == "section_scheme_preview"
            and row.get("scheme_id") == scheme["scheme_id"] and row.get("source_preview") == name), None)
        if existing:
            # Loaded projects resolve portable paths before entering this service.
            source = Path(existing.get("path") or "")
            if source.is_file() and _file_digest(source) != existing.get("sha256"):
                raise ValueError("已采用的原图预览字节已改变：" + source.name)
            continue
        source = (root / name).resolve()
        if not source.is_relative_to(root):
            raise ValueError("原图预览路径越出资料目录")
        if source.is_file():
            files.append({"role": "section_scheme_preview", "scheme_id": scheme["scheme_id"],
                "source_preview": name, "path": str(source), "sha256": _file_digest(source), "portable": True})


def _resolve_part_fields(current, scheme, common, paths, explicit, inherited):
    """Resolve one part before checking completeness, shared by drafting and adoption."""
    from .pipe_dimensions import CONSTRUCTION_WALL, MATERIAL_OUTER, normalize_pipe_dimensions
    prior = current.get("section_scheme_binding") or {}
    original_support = {key: deepcopy(value) for key, value in (current.get("construction") or {}).items()
                        if key in {"pipe_seat", "pipe_support", "encasement", "pipe_encasement"}}
    retained = _overrides(current)
    geometry_paths = replacement_geometry_paths(scheme)
    explicit = replacement_overrides(current, scheme, explicit, retained)
    for path, value in tuple(explicit.items()):
        if path.endswith(".outer_diameter") and value is not None:
            prefix = path.rpartition(".")[0] + "."
            wall_path = prefix + CONSTRUCTION_WALL
            if wall_path not in explicit and _get(current, wall_path) is not None:
                explicit = {**explicit, wall_path: None, prefix + MATERIAL_OUTER: None}
    if geometry_paths:
        paths = set(paths) | set(geometry_paths) | {OUTLINE, WIDTH_ALIAS}
        if scheme.get("scheme_id") == "tzk_box_paddy":
            common = {**dict.fromkeys(WORK_SPACES, .5), **common}
            paths.update(WORK_SPACES)
    if prior and (prior.get("scheme_id") != scheme["scheme_id"] or prior.get("source_sha256") != scheme["source_sha256"]):
        # A review of one source is not approval of another source's conflict.
        for path in ("section.source_review_confirmed", "section.fill_membrane_confirmed", "section.fill_membrane_mode"):
            if path not in explicit:
                retained.pop(path, None)
                current.get("drawing_user_overrides", {}).pop(path, None)
                _remove(current, path)
    _restore_legacy_fields(current, retained)
    current["drawing_bindings"] = []
    current["drawing_parameter_sources"] = {}
    _capture(current, paths | set(explicit) | set(retained) | set(inherited))
    previous_values = {path: deepcopy(_get(current, path)) for path in paths | set(explicit) | set(retained) | set(inherited)}
    _restore(current, current.get("section_scheme_applied_fields", []))
    for path, value in explicit.items():
        if value is None:
            retained.pop(path, None)
            current.setdefault("drawing_user_overrides", {}).pop(path, None)
            _restore(current, [path])
            if path.rpartition(".")[2] in {CONSTRUCTION_WALL, MATERIAL_OUTER}:
                _remove(current, path)
        else:
            retained[path] = deepcopy(value)
    resolved = common
    if scheme.get("dimension_schedules"):
        from .section_scheme_catalog import resolve_section_scheme_fields
        dimension_asset = deepcopy(current)
        for path, value in retained.items():
            _set(dimension_asset, path, value)
        normalize_pipe_dimensions(dimension_asset)
        dimensions=hydraulic_dimensions(dimension_asset)
        # The pipe editor displays the first pipe's dimensions in the section
        # summary. Its automatic outside diameter lives in the pipe list.
        first_outer=dimensions.get("section.pipes[1].outer_diameter")
        if "section.pipes" in retained and "section.outer_diameter" not in retained and first_outer is not None:
            dimensions["section.outer_diameter"]=first_outer
        resolved, _ = _field_paths(resolve_section_scheme_fields(scheme,
            hydraulic_dimensions=dimensions), template=True)
        _capture(current, set(resolved))
        for path in resolved:
            previous_values.setdefault(path, deepcopy(_get(current, path)))
    from .section_parameter_decisions import drawing_support_transition
    replace_support, reuse_support = drawing_support_transition(current, scheme, resolved)
    incompatible, _ = drawing_support_transition({"construction": original_support}, scheme, resolved)
    for path in incompatible:
        if path not in explicit:
            retained.pop(path, None)
            (current.get("drawing_user_overrides") or {}).pop(path, None)
    for path in set(replace_support) | set(reuse_support):
        _capture(current, [path])
        previous_values.setdefault(path, deepcopy(_get(current, path)))
    for path, value in reuse_support.items():
        if _get(current, path) is None:
            _set(current, path, value)
    resolved = {**replace_support, **resolved, **inherited}
    adopted = {**resolved, **retained}
    for path, value in adopted.items():
        _set(current, path, value)
    normalize_pipe_dimensions(current)
    for path in resolved:
        if path.endswith(".outer_diameter") and path not in retained:
            prefix = path.rpartition(".")[0] + "."
            wall = _get(current, prefix + CONSTRUCTION_WALL)
            if wall is None and path == "section.outer_diameter" and len(_get(current, "section.pipes") or ()) == 1:
                wall = _get(current, "section.pipes[1]." + CONSTRUCTION_WALL)
            if wall is not None:
                resolved[path] = _get(current, path)
    adopt_replacement_geometry(current, scheme, resolved, retained)
    adopted.update(resolved)
    adopted.update(retained)
    return resolved, retained, adopted, previous_values


def draft_section_scheme_fields(asset, scheme, overrides):
    """Return the editable candidate, even when its required values are still blank."""
    current = deepcopy(asset)
    common, _, paths, _ = _scheme_fields(scheme)
    explicit, _ = _field_paths(overrides)
    resolved, retained, _, _ = _resolve_part_fields(current, scheme, common, paths, explicit, {})
    current["section_scheme_user_overrides"] = retained
    return current, resolved


def _apply(inputs, *, route_id, asset_id, scheme, station_start, station_end, overrides=None, inherited_fields=None,
           saved_binding=None, replay_part=None):
    from .pipe_dimensions import CONSTRUCTION_DIAMETER_SOURCE

    result = deepcopy(inputs)
    if not isinstance(scheme, dict) or not scheme.get("scheme_id"):
        raise ValueError("未选择有效的断面方案")
    if scheme.get("calculation_status") == "not_in_scope":
        raise ValueError("所选项目不属于本轮断面算量范围")
    network, targets, start, end = _targets(
        result, route_id, asset_id, station_start, station_end,
        special_pipe_scheme=saved_binding is None and scheme.get("condition") != "general",
    )
    if saved_binding is None:
        if not is_selectable_section_scheme(scheme):
            raise ValueError("该图纸已从断面选型中撤下，请重新选择施工做法")
        if any(not is_selectable_section_scheme(scheme, part.get("section_type")) for part in targets):
            raise ValueError("倒虹管请选择亭子口 A～E 型断面")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(scheme.get("source_sha256", ""))):
        raise ValueError("断面方案缺少有效原图 SHA256 来源")
    scheme = deepcopy(scheme)
    common, variants, paths, ignored = _scheme_fields(scheme)
    scheme["fields"], scheme["terrain_variants"] = common, variants
    _preserve_previews(result, scheme)
    explicit = _field_paths(overrides or {})[0]
    requested_inherited = _field_paths(inherited_fields or {})[0]
    route, root = _route(network), str(asset_id)
    report = {"valid": True, "errors": [], "warnings": [], "affected_parts": [],
        "replaced_ranges": [], "preserved_ranges": [], "field_changes": [], "ignored_fields": ignored,
        "pending_terrain_requirements": [],
        "route_id": route, "asset_id": root, "station_start": start, "station_end": end,
        "length": end-start, "requires_recalculation": True}
    if ignored:
        report["warnings"].append("原图例图净尺寸仅作参考，已保留当前设计值：" + "、".join(ignored))
    for notes in ((scheme.get("constraints") or {}).get("source_conditions"), scheme.get("applicability_notes")):
        if notes:
            report["warnings"].extend([notes] if isinstance(notes, str) else notes)
    records = _trim_records(result.get("section_scheme_bindings", []), route, root, start, end)
    for original in targets:
        if original.get("section_type") not in scheme.get("section_types", []):
            raise ValueError("所选方案与当前结构形式不匹配")
        a, b = max(start, original["station_start"]), min(end, original["station_end"])
        prior = original.get("section_scheme_binding") or {}
        inherited = requested_inherited
        if (inherited_fields is None and prior.get("scheme_id") == scheme["scheme_id"]
                and prior.get("source_sha256") == scheme.get("source_sha256")):
            inherited = _field_paths(prior.get("inherited_fields") or {})[0]
        report["replaced_ranges"].append({"station_start": a, "station_end": b,
            "scheme_id": prior.get("scheme_id"), "title": (prior.get("scheme_snapshot") or {}).get("title", "尚未匹配")})
        for left, right in ((original["station_start"], a), (b, original["station_end"])):
            if right > left + _EPS:
                report["preserved_ranges"].append({"station_start": left, "station_end": right})
        current = _slice(network, original, a, b)
        current["section_scheme_root_asset_id"] = root
        part_explicit = explicit
        if replay_part is not None and "section.pipes" in explicit:
            from .pipe_general_section import rebase_pipe_layout
            part_explicit = rebase_pipe_layout(current, replay_part, explicit)
        resolved, retained, adopted, previous_values = _resolve_part_fields(
            current, scheme, common, paths, part_explicit, inherited)
        _check_constraints(current, scheme)
        branches = [(code, variant, variant.get("required_fields", [])) for code, variant in variants.items()]
        branches.extend((code, {**variant, "fields": {**variant.get("fields", {}), **selector.get("fields", {})}},
                         selector.get("required_fields", []))
            for code, variant in variants.items() for selector in variant.get("selectors", []))
        branches.extend(("selector", selector, selector.get("required_fields", []))
                        for selector in scheme.get("selectors", []))
        for code, variant, required in branches:
            prospective = deepcopy(current)
            for path, value in {**variant.get("fields", {}), **retained}.items():
                _set(prospective, path, value)
            missing = [path for path in required
                if _get(prospective, path) is None or (path.endswith("_confirmed") and _get(prospective, path) is not True)]
            if missing:
                label = {"cut": "全挖", "mixed": "半挖半填", "fill": "全填", "selector": "原图条件分支"}[code]
                report["pending_terrain_requirements"].append({"code": code, "label": label,
                    "fields": missing, "station_start": a, "station_end": b,
                    "unresolved_conditions": deepcopy(variant.get("unresolved_conditions") or [])})
                warning = f"实际地形判为{label}时，仍须补齐或确认：" + "、".join(missing)
                if warning not in report["warnings"]:
                    report["warnings"].append(warning)
        if trenchless_method(current):
            raise ValueError("断面方案不能改变非开挖施工身份，请从工程施工方式入口设置")
        applied = paths | set(resolved)
        if replacement_geometry_paths(scheme):
            applied.update(replacement_geometry_paths(scheme))
            if (current.get("section_scheme_source_values", {}).get(WIDTH_ALIAS) or {}).get("present"):
                applied.add(WIDTH_ALIAS)
        current["section_scheme_applied_fields"] = sorted(applied)
        current["geometry_sections"] = []
        sources = current.setdefault("parameter_sources", {})
        provenance = {}
        for path, value in adopted.items():
            is_user = path in retained
            is_inherited = path in inherited and not is_user
            formula_outer = not is_user and sources.get(path) == CONSTRUCTION_DIAMETER_SOURCE
            if not formula_outer:
                sources[path] = ("用户覆盖：" if is_user else "沿用当前工程参数：" if is_inherited else "图纸断面方案：") + scheme.get("title", scheme["scheme_id"])
            provenance[path] = {"scheme_id": scheme["scheme_id"], "drawing_id": scheme.get("drawing_id"),
                "source_sha256": scheme["source_sha256"], "source_handles": deepcopy(scheme.get("source_handles") or []),
                "original_value": previous_values.get(path), "adopted_value": deepcopy(value), "user_override": is_user,
                "inherited": is_inherited}
            if formula_outer:
                provenance[path].update(geometry_derived=True, geometry_basis=CONSTRUCTION_DIAMETER_SOURCE)
            mode = (current.get("replacement_parameter_modes") or {}).get(path)
            if mode:
                automatic = mode == "automatic"
                basis = replacement_basis(scheme, path) if automatic else "本段手动设定"
                provenance[path].update(geometry_derived=automatic, geometry_basis=basis)
                if automatic:
                    sources[path] = "依据本段构造计算：" + basis
            if not _same(previous_values.get(path), value):
                report["field_changes"].append({"station_start": a, "station_end": b, "field": path,
                    "before": previous_values.get(path), "after": deepcopy(value), "user_override": is_user})
        for path, value in part_explicit.items():
            if (value is None and path not in adopted
                    and sources.get(path) != CONSTRUCTION_DIAMETER_SOURCE):
                sources[path] = "当前水面线/设计来源：已恢复"
        current["section_scheme_parameter_sources"] = provenance
        current.setdefault("drawing_user_overrides", {}).update(deepcopy(retained))
        current.setdefault("drawing_parameter_sources", {}).update(deepcopy(provenance))
        record = {"schema": SCHEMA, "route_id": route, "network_id": network.get("network_id", route),
            "asset_id": root, "scheme_id": scheme["scheme_id"], "station_start": a, "station_end": b,
            "source_identity": deepcopy(current.get("source_identity")), "source_sha256": scheme["source_sha256"],
            "scheme_snapshot": deepcopy(scheme), "scheme_sha256": _digest(scheme),
            "resolved_fields": deepcopy(resolved), "overrides": deepcopy(retained)}
        if inherited:
            record["inherited_fields"] = deepcopy(inherited)
        if saved_binding and saved_binding.get("positioned_special_segment"):
            record["positioned_special_segment"] = True
        record["binding_sha256"] = _record_hash(record)
        records.append(record)
        _metadata(current, record)
        report["affected_parts"].append(deepcopy(current))
    # The legacy slicer names children to 1mm; preserve distinct legal sub-mm boundaries.
    for current in network["assets"]:
        if _root(current) != root:
            continue
        if current.get("parent_asset_id") or current.get("section_scheme_root_asset_id"):
            current["asset_id"] = f"{root}-{current['station_start']:.12g}-{current['station_end']:.12g}"
        if current.get("section_scheme_binding"):
            clipped = _clip_record(current["section_scheme_binding"], current["station_start"], current["station_end"])
            _metadata(current, clipped)
    result["section_scheme_bindings"] = sorted(records, key=lambda row: (row["route_id"], row["asset_id"], row["station_start"]))
    if "drawing_bindings" in result:
        result["drawing_bindings"] = _trim_legacy_records(result["drawing_bindings"], network, root, start, end)
    basis = result.setdefault("quantity_basis", {})
    basis["section_scheme_binding_sha256"] = _digest(result["section_scheme_bindings"])
    basis["section_scheme_binding_count"] = len(result["section_scheme_bindings"])
    unresolved = [issue for issue in result.get("section_scheme_binding_issues", [])
        if not (isinstance(issue, dict) and issue.get("route_id") == route and issue.get("asset_id") == root
                and issue.get("station_start", -math.inf) >= start - _EPS
                and issue.get("station_end", math.inf) <= end + _EPS)]
    if unresolved:
        result["section_scheme_binding_issues"] = unresolved
    else:
        result.pop("section_scheme_binding_issues", None)
    return result, report


def preview_scheme_application(inputs, *, route_id, asset_id, scheme, station_start, station_end, overrides=None):
    try:
        _, report = _apply(inputs, route_id=route_id, asset_id=asset_id, scheme=scheme,
            station_start=station_start, station_end=station_end, overrides=overrides)
        return report
    except (ValueError, TypeError, KeyError) as error:
        return {"valid": False, "errors": [str(error)], "warnings": [], "affected_parts": [],
            "replaced_ranges": [], "preserved_ranges": [], "field_changes": [], "requires_recalculation": False}


def apply_section_scheme(inputs, *, route_id, asset_id, scheme, station_start, station_end, overrides=None, inherited_fields=None):
    return _apply(inputs, route_id=route_id, asset_id=asset_id, scheme=scheme,
        station_start=station_start, station_end=station_end, overrides=overrides, inherited_fields=inherited_fields)[0]


def _edit_unbound_section_parameters(asset, overrides):
    from .construction_rules import normalize_asset_construction

    sources = asset.setdefault("parameter_sources", {})
    user = asset.setdefault("drawing_user_overrides", {})
    _capture(asset, (path for path, value in overrides.items() if value is not None))
    for path, value in overrides.items():
        if value is not None:
            _set(asset, path, value)
            user[path] = deepcopy(value)
            sources[path] = "用户覆盖：施工参数编辑"
        elif path in user and path in asset.get("section_scheme_source_values", {}):
            _restore(asset, (path,))
            user.pop(path, None)
            sources.pop(path, None)
    normalize_asset_construction(asset)
    asset.update(geometry_sections=[], workbench_geometry=True, parameter_source="user_confirmed")


def draft_current_section_parameters(asset, overrides):
    scheme = (asset.get("section_scheme_binding") or {}).get("scheme_snapshot")
    if scheme:
        return draft_section_scheme_fields(asset, scheme, overrides)
    candidate = deepcopy(asset)
    _edit_unbound_section_parameters(candidate, _field_paths(overrides)[0])
    return candidate, None


def edit_current_section_parameters(inputs, *, route_id, asset_id, station_start, station_end, overrides):
    """Apply overrides to each covered part's currently adopted construction."""
    result = deepcopy(inputs)
    network, targets, start, end = _targets(result, route_id, asset_id, station_start, station_end)
    explicit = _field_paths(overrides)[0]
    report = {"valid": True, "field_changes": [], "warnings": [], "affected_parts": [],
              "pending_terrain_requirements": []}
    for original in targets:
        left, right = max(start, original["station_start"]), min(end, original["station_end"])
        original = next(part for part in network["assets"] if _root(part) == str(asset_id)
                        and part["station_start"] == original["station_start"]
                        and part["station_end"] == original["station_end"])
        prior = original.get("section_scheme_binding") or {}
        scheme = prior.get("scheme_snapshot")
        if scheme:
            result, adopted = _apply(result, route_id=route_id, asset_id=asset_id, scheme=scheme,
                station_start=left, station_end=right, overrides=explicit, saved_binding=prior)
            network = next(row for row in result["networks"] if _route(row) == _route(network))
            for key in ("field_changes", "warnings", "affected_parts", "pending_terrain_requirements"):
                report[key].extend(adopted[key])
            continue
        current = _slice(network, original, left, right)
        if current is not original:
            for part in network["assets"]:
                if _root(part) == str(asset_id) and part.get("parent_asset_id"):
                    part["asset_id"] = f"{asset_id}-{part['station_start']:.12g}-{part['station_end']:.12g}"
        before = {path: deepcopy(_get(current, path)) for path in explicit}
        _edit_unbound_section_parameters(current, explicit)
        report["affected_parts"].append(current)
        for path, value in before.items():
            after = _get(current, path)
            if not _same(value, after):
                report["field_changes"].append({"station_start": left, "station_end": right,
                    "field": path, "before": value, "after": deepcopy(after)})
    return result, report


def validate_section_scheme_bindings(inputs, raise_on_error=False):
    errors = [str(item.get("reason") or item) if isinstance(item, dict) else str(item)
              for item in inputs.get("section_scheme_binding_issues", [])]
    records = inputs.get("section_scheme_bindings", [])
    from .drawing_bindings import _file_digest
    active_ids = {record.get("scheme_id") for record in records}
    for resource in inputs.get("input_files", []):
        if resource.get("role") != "section_scheme_preview" or resource.get("scheme_id") not in active_ids:
            continue
        path = Path(resource.get("path") or "")
        if path.is_file():
            try:
                if _file_digest(path) != resource.get("sha256"):
                    errors.append("已采用的原图预览字节已改变：" + path.name)
            except OSError as error:
                errors.append("无法核对原图预览：" + str(error))
    for record in records:
        try:
            scheme = record["scheme_snapshot"]
            if record.get("schema") != SCHEMA or record.get("binding_sha256") != _record_hash(record):
                raise ValueError("保存的区段绑定记录已变化，须重新确认方案")
            if record.get("scheme_sha256") != _digest(scheme) or record.get("scheme_id") != scheme.get("scheme_id"):
                raise ValueError("保存的断面方案快照已变化，须重新确认方案")
            if record.get("source_sha256") != scheme.get("source_sha256"):
                raise ValueError("方案原图来源与绑定记录不一致")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", str(record.get("source_sha256", ""))):
                raise ValueError("方案原图来源摘要无效")
            _, targets, start, end = _targets(inputs, record["route_id"], record["asset_id"],
                                             record["station_start"], record["station_end"])
            for asset in targets:
                actual = asset.get("section_scheme_binding") or {}
                if actual.get("binding_sha256") != _record_hash(actual):
                    raise ValueError("实际区段保存的方案快照已变化")
                if actual.get("scheme_sha256") != record["scheme_sha256"] or actual.get("scheme_id") != record["scheme_id"]:
                    raise ValueError("实际区段与已保存的断面方案不一致")
                if asset["station_start"] < start - _EPS or asset["station_end"] > end + _EPS:
                    raise ValueError("实际计算区段未按已采用方案的边界拆分")
                if record.get("source_identity") != asset.get("source_identity"):
                    raise ValueError("工程对象来源变化，须先重放并核对断面方案")
                _check_constraints(asset, scheme)
                if asset.get("section_scheme_terrain_variants", {}) != scheme.get("terrain_variants", {}):
                    raise ValueError("实际区段自动地形构造与已采用方案不一致")
                if asset.get("section_scheme_selectors", []) != scheme.get("selectors", []):
                    raise ValueError("实际区段地形适用条件与已采用方案不一致")
                expected = {**record.get("resolved_fields", scheme.get("fields", {})), **record.get("overrides", {})}
                for path, target in expected.items():
                    current = _get(asset, path)
                    if _same(current, target):
                        continue
                    if _matches_user_override(asset,path):
                        continue
                    # Calculation-time terrain selection may legitimately adopt
                    # a different member of this same saved construction family.
                    variants = scheme.get("terrain_variants") or {}
                    if path not in record.get("overrides", {}) and any(
                            path in variant.get("fields", {}) and _same(current, variant["fields"][path])
                            for variant in variants.values()):
                        continue
                    raise ValueError(f"实际区段参数与已采用方案不一致：{path}")
        except (ValueError, KeyError, TypeError) as error:
            errors.append(str(error))
    # Every adopted asset must have a corresponding top-level persisted record.
    try:
        groups = list_asset_groups(inputs)
    except (ValueError, TypeError, KeyError) as error:
        groups = []
        errors.append(str(error))
    for group in groups:
        for asset in group["parts"]:
            binding = asset.get("section_scheme_binding")
            if binding and not any(row.get("binding_sha256") == binding.get("binding_sha256") for row in records):
                errors.append("实际区段的断面方案未完整保存")
    result = {"valid": not errors, "errors": list(dict.fromkeys(errors)), "checked_count": len(records)}
    if errors and raise_on_error:
        raise ValueError("；".join(result["errors"]))
    return result


def replay_section_schemes(inputs, previous_inputs):
    """Reapply exact range choices to refreshed designs; failed spans stay explicit."""
    from ..adapters.workbench_sources import crosses_legacy_flow_sections, flow_section_parameter_targets

    result = deepcopy(inputs)
    records = previous_inputs.get("section_scheme_bindings", [])
    issues = []
    validation = validate_section_scheme_bindings(previous_inputs)
    if not validation["valid"]:
        result["section_scheme_binding_issues"] = deepcopy(validation["errors"])
        return result
    files = result.setdefault("input_files", [])
    for resource in previous_inputs.get("input_files", []):
        if resource.get("role") == "section_scheme_preview" and resource not in files:
            files.append(deepcopy(resource))
    for record in records:
        try:
            # Existing parameter-editor changes are recovered per real source part.
            previous_owner, parts, start, end = _targets(previous_inputs, record["route_id"], record["asset_id"],
                                                         record["station_start"], record["station_end"])
            for part in parts:
                left, right = max(start, part["station_start"]), min(end, part["station_end"])
                targets = (flow_section_parameter_targets(result, previous_owner, part)
                           if crosses_legacy_flow_sections(part) else [])
                if not targets:
                    targets = [(record["route_id"], record["asset_id"], left, right)]
                for route, root, a, b in targets:
                    if min(b, right) <= max(a, left) + _EPS:
                        continue
                    result, _ = _apply(result, route_id=route, asset_id=root, scheme=record["scheme_snapshot"],
                        station_start=max(a, left), station_end=min(b, right), overrides=_overrides(part),
                        inherited_fields=record.get("inherited_fields"), saved_binding=record, replay_part=part)
        except (ValueError, KeyError, TypeError) as error:
            issues.append({"route_id": record.get("route_id"), "asset_id": record.get("asset_id"),
                "station_start": record.get("station_start"), "station_end": record.get("station_end"), "reason": str(error)})
    if issues:
        result["section_scheme_binding_issues"] = issues
    return result


def replay_unbound_flow_section_parameters(inputs, previous_inputs):
    """Carry explicit edits onto the exact intersections with current flow sections."""
    from ..adapters.workbench_sources import crosses_legacy_flow_sections, flow_section_parameter_targets

    result = inputs
    positioned = ("section.discrete_components", "section.aqueduct_frame_layout", "construction.cover_segments")
    for owner in previous_inputs.get("networks", []):
        for part in owner.get("assets", []):
            if (part.get("section_scheme_binding")
                    or not part.get("flow_section") and not crosses_legacy_flow_sections(part)):
                continue
            overrides = {path: value for path, value in _overrides(part).items()
                         if value is not None and not path.startswith(positioned)}
            if not overrides:
                continue
            for route, root, start, end in flow_section_parameter_targets(result, owner, part):
                result, _ = edit_current_section_parameters(result, route_id=route, asset_id=root,
                    station_start=start, station_end=end, overrides=overrides)
    return result
