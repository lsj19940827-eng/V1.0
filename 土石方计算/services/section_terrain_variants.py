"""Choose channel construction from the actual ground at the requested section.

No extra station is requested here.  The same operation serves batch sections
and a single-station view and never changes the persisted source asset.
"""
from __future__ import annotations

from copy import deepcopy
import math

from shapely.geometry import Polygon
from shapely.ops import unary_union

from .contracts import ConstructionInputError
from .drawing_bindings import _get, _set

_LABELS = {"cut": "全挖", "mixed": "半挖半填", "fill": "全填"}


def _soil(ground, floor):
    rows = [(float(x), float(z)) for x, z in ground]
    if len(rows) < 2 or any(not math.isfinite(value) for point in rows for value in point):
        raise ConstructionInputError("实际地形缺测，不能判别填挖工况")
    if any(right[0] <= left[0] for left, right in zip(rows, rows[1:])):
        raise ConstructionInputError("实际地面线横向位置不递增")
    bottom = min(floor, *(z for _, z in rows)) - 1.
    return Polygon([*rows, (rows[-1][0], bottom), (rows[0][0], bottom)])


def classify_terrain_case(outer, ground):
    """Classify the filled permanent envelope relative to real terrain."""
    if outer.is_empty or outer.area <= 0:
        raise ConstructionInputError("缺少有效永久结构轮廓，不能判别填挖工况")
    left, floor, right, _ = outer.bounds
    if len(ground) == 0 or ground[0][0] > left + 1e-8 or ground[-1][0] < right - 1e-8:
        raise ConstructionInputError("实际地面线未覆盖结构宽度，不能判别填挖工况")
    soil = _soil(ground, floor)
    below = outer.intersection(soil).area
    above = outer.difference(soil).area
    tolerance = max(1e-8, outer.area * 1e-8)
    code = "cut" if above <= tolerance else "fill" if below <= tolerance else "mixed"
    return {"code": code, "label": _LABELS[code], "source": "actual_terrain",
            "rule": "permanent_outer_relative_to_actual_ground",
            "below_ground_area_m2": float(below), "above_ground_area_m2": float(above)}


def selector_metrics(asset, structure, terrain_case, ground):
    """Measure source-defined thresholds at the centre or actual permanent toe."""
    from ..adapters.independent_assets import _ground_at
    from .section_geometry import slope_grades, trace_to_ground
    from .construction_rules import effective_construction
    result = deepcopy(terrain_case)
    variant = (asset.get("section_scheme_terrain_variants") or {}).get(result["code"], {})
    selectors = [*(asset.get("section_scheme_selectors") or []), *variant.get("selectors", [])]
    wanted = {row.get("metric") for row in selectors}
    outer = structure["outer"]
    if "cover_depth_m" in wanted:
        result["cover_depth_m"] = _ground_at(ground, 0.) - outer.bounds[3]
    if "max_outer_drop_m" in wanted:
        construction = effective_construction(asset)
        crown = outer.bounds[3]
        bounds = structure.get("occupancy", outer).bounds
        measurements = []
        for side, direction, index in (("left", -1, 0), ("right", 1, 2)):
            x = bounds[index] + direction * float(construction.get("bank_top_width_" + side, 0.))
            if _ground_at(ground, x) >= crown - 1e-9:
                continue
            try:
                grades = slope_grades(construction, side, filling=True)
            except (ValueError, TypeError, KeyError) as error:
                raise ConstructionInputError("临空高度判别缺少实际永久边坡参数，不能用渠边地面代替坡脚") from error
            trace = trace_to_ground((x, crown), ground, grades, direction, filling=True)
            toe = trace[-1]
            if abs(toe[1] - _ground_at(ground, toe[0])) > 1e-6:
                raise ConstructionInputError("未找到永久边坡与实际地面交点，不能判别临空高度")
            measurements.append({"side": side, "crown": [x, crown], "toe": list(toe), "drop_m": crown-toe[1]})
        result["max_outer_drop_m"] = max((row["drop_m"] for row in measurements), default=0.)
        result["outer_drop_measurements"] = measurements
    return result


def _select(selectors, terrain_case):
    if not selectors:
        return None
    choices = []
    for selector in selectors:
        metric = selector.get("metric")
        actual = terrain_case.get(metric) if isinstance(terrain_case, dict) else None
        if actual is None:
            raise ConstructionInputError(f"缺少实际地形判别指标：{metric}，不能套用任意构造分支")
        minimum, maximum = selector.get("min"), selector.get("max")
        if minimum is not None and (actual < minimum or actual == minimum and not selector.get("min_inclusive", True)):
            continue
        if maximum is not None and (actual > maximum or actual == maximum and not selector.get("max_inclusive", True)):
            continue
        choices.append(selector)
    if len(choices) != 1:
        raise ConstructionInputError("实际地形没有唯一匹配的原图构造分支，请核对适用范围")
    return choices[0]


def terrain_variant_asset(asset, terrain_case, *, validate=True, apply_selectors=True):
    """Apply the selected construction, with explicit edits taking precedence."""
    from .section_scheme_bindings import _field_paths, hydraulic_dimensions
    code = terrain_case["code"] if isinstance(terrain_case, dict) else terrain_case
    variants = asset.get("section_scheme_terrain_variants") or {}
    if variants and code not in variants:
        raise ConstructionInputError(f"缺少{_LABELS.get(code, code)}工况的断面构造，不能套用其他填挖方案")
    variant = deepcopy(variants.get(code, {}))
    chosen = []
    if apply_selectors:
        for selectors in (asset.get("section_scheme_selectors"), variant.get("selectors")):
            selected = _select(selectors, terrain_case)
            if selected:
                chosen.append(selected)
    result = deepcopy(asset)
    fields = _field_paths(variant.get("fields") or {}, template=True)[0]
    overrides = deepcopy(asset.get("section_scheme_user_overrides") or {})
    overrides.update(deepcopy(asset.get("drawing_user_overrides") or {}))
    snapshot = (asset.get("section_scheme_binding") or {}).get("scheme_snapshot")
    if snapshot:
        from .section_scheme_catalog import resolve_section_scheme_fields
        if asset.get("replacement_parameter_modes"):
            from .section_scheme_bindings import _overrides
            overrides.update(_overrides(asset))
        dimensions = deepcopy(asset)
        for path, value in overrides.items():
            if value is not None:
                _set(dimensions, path, value)
        fields = _field_paths(resolve_section_scheme_fields(snapshot, terrain_case=code,
            hydraulic_dimensions=hydraulic_dimensions(dimensions)), template=True)[0]
        # General-section defaults retain the project's existing construction
        # dimensions without turning them into overrides of a later family.
        fields.update(_field_paths((asset.get("section_scheme_binding") or {}).get("inherited_fields") or {})[0])
    required = list(variant.get("required_fields", []))
    for selected in chosen:
        fields.update(_field_paths(selected.get("fields") or {}, template=True)[0])
        required.extend(selected.get("required_fields", []))
    for path, value in fields.items():
        _set(result, path, value)
    for path, value in overrides.items():
        if value is not None:
            _set(result, path, value)
    from .pipe_dimensions import normalize_pipe_dimensions
    normalize_pipe_dimensions(result)
    if validate:
        missing = [path for path in required if _get(result, path) is None]
        if missing:
            raise ConstructionInputError(f"{_LABELS.get(code, code)}工况缺少已确认参数：" + "、".join(missing))
        for path in required:
            if path.endswith("_confirmed") and _get(result, path) is not True:
                raise ConstructionInputError(f"{_LABELS.get(code, code)}工况需确认原图疑点：{path}")
        if "section.fill_membrane_mode" in required and _get(result, "section.fill_membrane_mode") not in {"with_membrane", "without_membrane"}:
            raise ConstructionInputError("全填工况须明确选择保留膜层或不采用膜层，不能只勾选确认")
    if isinstance(terrain_case, dict):
        result["terrain_case"] = deepcopy(terrain_case)
    else:
        result["terrain_case"] = {"code": code, "label": _LABELS.get(code, code), "source": "actual_terrain"}
    if chosen:
        from .section_scheme_bindings import _digest
        result["section_scheme_selector_key"] = _digest(chosen)
        result["terrain_case"]["selected_conditions"] = [
            {key: deepcopy(row[key]) for key in ("metric", "min", "max", "min_inclusive", "max_inclusive", "title", "source_preview") if key in row}
            for row in chosen]
        result["terrain_case"]["source_preview"] = chosen[-1].get("source_preview")
    source = result.get("drawing_binding") or {}
    if source:
        source["terrain_case"] = code
        source["source_handles"] = list(dict.fromkeys([*source.get("source_handles", []), *variant.get("source_handles", []),
            *(handle for row in chosen for handle in row.get("source_handles", []))]))
        result["drawing_binding"] = source
    return result


def clip_fill_contact_components(structure, ground):
    """Restrict specified mortar/layers to actual fill contact, keeping full membranes."""
    collections = ("component_regions", "component_surfaces")
    if not any(spec.get("placement_condition") == "on_fill_contact_only"
               for name in collections for spec in structure.get(name, {}).values()):
        return structure
    result = deepcopy(structure)
    soil = _soil(ground, min(structure["outer"].bounds[1], structure["occupancy"].bounds[1]))
    previous = [spec["geometry"] for spec in structure.get("component_regions", {}).values()]
    for name in collections:
        for spec in result.get(name, {}).values():
            if spec.get("placement_condition") != "on_fill_contact_only":
                continue
            geometry = spec["geometry"].difference(soil)
            spec["geometry"] = geometry
            spec["section_measure"] = float(geometry.area if name == "component_regions" else geometry.length)
            spec["placement_source"] = "actual_terrain_fill_contact"
    current = [spec["geometry"] for spec in result.get("component_regions", {}).values()]
    base_measured = structure["measured"].difference(unary_union(previous))
    result["measured"] = unary_union([base_measured, *current])
    result["occupancy"] = unary_union([result["outer"], result["measured"]])
    return result
