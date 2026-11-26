"""Traceable construction families and individually cropped original sections.

Hydraulic dimensions are reference data, never defaults in ``fields``.  Terrain
variants belong to a family and are selected from the actual section terrain.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import sys

from .engineering_drawings import ARCHIVED_DRAWING_IDS

SCHEMA = "engineering_section_schemes_1.0"
_RESOURCE = Path("土石方计算/resources/engineering_drawings/section_schemes.json")
_TZK_SOURCE = "6ed245d8e5261051cbe34d50e0520cbcfda28c336274d24a971cf4914b35d6a9"
_RETIRED_SIPHON_SOURCE = "d1a69035bf37d014ad51de2a63f2d1d539f1aa022b5d80a00480a84be1605fc0"
_SIPHON_SCHEME_IDS = frozenset("tzk_siphon_" + letter for letter in "abcde")
_NET_FIELDS = {"inner_width", "inner_height", "inner_radius", "inner_diameter",
               "bottom_width", "wall_height", "arch_angle_degrees",
               "inner_side_slope", "u_arc_angle_degrees", "u_side_angle_degrees"}


def _parameter_nodes(value):
    if isinstance(value, dict):
        if "fields" in value or "source_preview" in value:
            yield value
        for child in value.values():
            yield from _parameter_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _parameter_nodes(child)


class SectionSchemeCatalogError(ValueError):
    pass


def is_selectable_section_scheme(scheme, section_type=None):
    """Apply the current drawing selection policy to library and project snapshots."""
    if not scheme:
        return False
    identity = str(scheme.get("scheme_id", ""))
    if (identity.startswith("tangniwan_") or scheme.get("drawing_id") in ARCHIVED_DRAWING_IDS
            or scheme.get("source_sha256") == _RETIRED_SIPHON_SOURCE):
        return False
    if section_type == "circular_siphon" or scheme.get("structure_group") == "倒虹管":
        return identity in _SIPHON_SCHEME_IDS
    return True


def section_scheme_catalog_path():
    roots = [Path(__file__).resolve().parents[2], Path(sys.executable).resolve().parent]
    if getattr(sys, "_MEIPASS", None):
        roots.insert(0, Path(sys._MEIPASS))
    return next((root / _RESOURCE for root in roots if (root / _RESOURCE).is_file()),
                roots[0] / _RESOURCE)


def load_section_scheme_catalog(path=None):
    source = Path(path or section_scheme_catalog_path())
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise SectionSchemeCatalogError("工程断面方案库无法读取：" + str(error)) from error
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise SectionSchemeCatalogError("工程断面方案库格式不受支持")
    schemes = data.get("schemes")
    if not isinstance(schemes, list) or not schemes:
        raise SectionSchemeCatalogError("工程断面方案库没有有效方案")
    seen = set()
    for scheme in schemes:
        if not isinstance(scheme, dict) or not scheme.get("scheme_id") or scheme["scheme_id"] in seen:
            raise SectionSchemeCatalogError("工程断面方案编号缺失或重复")
        seen.add(scheme["scheme_id"])
        for key in ("title", "structure_group", "section_types", "drawing_id", "source_sha256",
                    "source_preview", "source_bounds", "source_layout", "source_handles"):
            if not scheme.get(key):
                raise SectionSchemeCatalogError(scheme["scheme_id"] + " 缺少 " + key)
        if len(scheme["source_sha256"]) != 64:
            raise SectionSchemeCatalogError("原图校验标识无效")
        variants = scheme.get("terrain_variants", {})
        if not isinstance(variants, dict) or set(variants) - {"cut", "mixed", "fill"}:
            raise SectionSchemeCatalogError("地形变体须按 cut/mixed/fill 组织")
        for item in _parameter_nodes(scheme):
            fields = item.get("fields", {})
            if not isinstance(fields, dict):
                raise SectionSchemeCatalogError("断面参数必须是点路径字典")
            if any(key.startswith("section.") and key.split(".")[-1] in _NET_FIELDS for key in fields):
                raise SectionSchemeCatalogError("原图方案不能覆盖水面线净尺寸")
            preview = Path(item.get("source_preview", scheme["source_preview"]))
            resolved = (source.parent / preview).resolve()
            if preview.is_absolute() or not resolved.is_relative_to(source.parent.resolve()):
                raise SectionSchemeCatalogError("原图预览必须位于随程序提供的资料目录")
    data["schemes"] = [scheme for scheme in schemes if is_selectable_section_scheme(scheme)]
    if "source_drawings" in data:
        data["source_drawings"] = [drawing for drawing in data["source_drawings"]
                                   if drawing.get("drawing_id") not in ARCHIVED_DRAWING_IDS]
    coverage = data.get("coverage", {})
    if "source_sections" in coverage:
        coverage["source_sections"] = {key: crop for key, crop in coverage["source_sections"].items()
                                       if is_selectable_section_scheme(crop)}
        coverage["original_section_count"] = len(coverage["source_sections"])
        coverage["scheme_count"] = len(data["schemes"])
        for drawing_id in ARCHIVED_DRAWING_IDS:
            coverage.get("source_counts", {}).pop(drawing_id, None)
    return deepcopy(data)


def load_section_schemes(path=None):
    """Return independent dictionaries; selecting a scheme cannot mutate the library."""
    return load_section_scheme_catalog(path)["schemes"]


def encasement_uniform_dimension(scheme):
    """Recognize b1 on the three verified CAD sections, including saved snapshots."""
    if not scheme:
        return None
    if scheme.get("encasement_uniform_dimension"):
        return scheme["encasement_uniform_dimension"]
    if (scheme.get("scheme_id") in {"tzk_pipe_d", "tzk_pipe_e", "tzk_siphon_d"}
            and scheme.get("source_sha256") == _TZK_SOURCE):
        return "b1"
    return None


def drawing_workspace_dimension(scheme):
    """These reviewed pipe drawings label both working spaces with the same b."""
    if not scheme or scheme.get("source_sha256") != _TZK_SOURCE:
        return None
    if scheme.get("scheme_id") in {
        "tzk_pipe_a", "tzk_pipe_b", "tzk_pipe_c", "tzk_pipe_d", "tzk_pipe_e", "tzk_pipe_hillside", "tzk_pipe_paddy",
        "tzk_siphon_a", "tzk_siphon_b", "tzk_siphon_c", "tzk_siphon_d", "tzk_siphon_e",
    }:
        return "b"
    return None


def section_scheme_preview_path(scheme, *, terrain_case=None, path=None):
    if not is_selectable_section_scheme(scheme):
        raise SectionSchemeCatalogError("请选择当前图纸库中的断面型号")
    source = Path(path or section_scheme_catalog_path())
    item = (scheme.get("terrain_variants") or {}).get(terrain_case, scheme)
    preview = (source.parent / item.get("source_preview", scheme["source_preview"])).resolve()
    if not preview.is_relative_to(source.parent.resolve()):
        raise SectionSchemeCatalogError("原图预览路径越出资料目录")
    return preview


def match_section_scheme_size(scheme, dimensions):
    """Identify the exact table and size used to resolve and display drawing dimensions."""
    schedules = []
    for schedule in scheme.get("dimension_schedules", []):
        section_type = dimensions.get("section_type")
        kind = dimensions.get("asset_kind")
        if section_type and schedule.get("section_types") and section_type not in schedule["section_types"]:
            continue
        if kind and schedule.get("asset_kinds") and kind not in schedule["asset_kinds"]:
            continue
        schedules.append(schedule)
    # A circular hydraulic shape alone does not identify pressure-pipe versus
    # culvert construction. Ambiguous tables must not overwrite one another.
    if len(schedules) != 1:
        return None, None, None, None
    schedule = schedules[0]
    field = schedule["match_field"]
    # Nominal diameter identifies pressure pipe rows. Older projects store only inner diameter.
    raw_value = dimensions.get(field)
    if (field == "section.inner_diameter" and dimensions.get("asset_kind") != "tunnel"
            and "tunnel" not in str(dimensions.get("section_type", ""))):
        count = dimensions.get("pipe_row_count")
        if count is None:
            indices = [key.partition("[")[2].partition("]")[0] for key in dimensions if key.startswith("section.pipes[")]
            count = max((int(index) for index in indices if index.isdecimal()), default=0)
        nominal = [dimensions.get(f"section.pipes[{i}].nominal_diameter_m") for i in range(1, count + 1)]
        bores = [dimensions.get(f"section.pipes[{i}].inner_diameter") for i in range(1, count + 1)]
        if dimensions.get("section.nominal_diameter_m") is not None or any(v is not None for v in nominal):
            field = "section.nominal_diameter_m"
        raw_value = dimensions.get(field)
        if count > 1 and any(v is not None for v in nominal + bores):
            # A section summary may mirror the first pipe. Only equal individual
            # sizes establish a common drawing row for a parallel installation.
            rows = [dn if dn is not None else bore for dn, bore in zip(nominal, bores)]
            try:
                values = [float(v) for v in rows]
            except (TypeError, ValueError):
                return schedule, field, None, None
            if not all(math.isfinite(v) and v > 0 for v in values):
                return schedule, field, None, None
            if any(abs(v - values[0]) > 1e-8 for v in values[1:]):
                return schedule, "section.pipes", None, None
            raw_value = values[0]
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return schedule, field, None, None
    if not math.isfinite(value) or value <= 0:
        return schedule, field, None, None
    row = next((item for item in schedule.get("rows", []) if abs(value - float(item["match_value"])) <= 1e-8), None)
    return schedule, field, value, row


def resolve_section_scheme_fields(scheme, *, terrain_case=None, hydraulic_dimensions=None):
    """Use the selected size row, retaining family defaults for an unlisted size."""
    fields = deepcopy(scheme.get("fields", {}))
    dimensions = hydraulic_dimensions or {}
    _, _, _, row = match_section_scheme_size(scheme, dimensions)
    if row is not None:
        fields.update(deepcopy(row["fields"]))
        for name, expression in row.get("derived_fields", {}).items():
            if expression.get("formula") == "support_chord_plus_sides":
                outer = dimensions.get("section.outer_diameter")
                if outer is not None:
                    fields[name] = float(outer) * math.sin(math.radians(expression["support_angle"])/2) + 2*expression["side_width"]
    if terrain_case:
        variant = (scheme.get("terrain_variants") or {}).get(terrain_case)
        if variant is None and scheme.get("terrain_variants"):
            raise SectionSchemeCatalogError("本构造族尚无该地形工况的已核对参数")
        if variant:
            fields.update(deepcopy(variant.get("fields", {})))
            choice = variant.get("field_choices", {})
            for input_name, options in choice.items():
                selected = dimensions.get(input_name)
                if selected in options:
                    fields.update(deepcopy(options[selected].get("fields", {})))
    from .pipe_construction_defaults import POLICY, GENERAL_SCHEME_IDS, pipe_construction_recommendations
    if (scheme.get("pipe_construction_default_policy") == POLICY
            and scheme.get("scheme_id") in GENERAL_SCHEME_IDS and scheme.get("condition") == "general"):
        diameter = dimensions.get("section.outer_diameter")
        pipe_diameters = [value for key, value in dimensions.items()
                          if key.startswith("section.pipes[") and key.endswith(".outer_diameter")]
        if pipe_diameters:
            try:
                diameter = (max(float(value) for value in pipe_diameters)
                            if len(pipe_diameters) == dimensions.get("pipe_row_count", len(pipe_diameters)) else None)
            except (TypeError, ValueError):
                diameter = None
        recommendations = pipe_construction_recommendations(diameter)
        # The current general family measures one sand support through
        # pipe_seat. Persist the absence of an extra rectangular layer so
        # restoring this family after a special support remains complete.
        fields.update({"construction.bedding_thickness": 0., "construction.bedding_extension": 0.})
        paths = ("construction.working_space_left", "construction.working_space_right",
                 "construction.pipe_seat.base_thickness")
        # Historical drawing tables stay intact in the source resource. The
        # current, explicitly marked general default uses the supplied bands.
        for path in paths:
            fields.pop(path, None)
        if recommendations["status"] == "READY":
            fields.update({paths[0]: recommendations["working_space_m"],
                           paths[1]: recommendations["working_space_m"],
                           paths[2]: recommendations["sand_bedding_thickness_m"]})
    return fields


def section_scheme_missing_fields(scheme, effective_fields, *, terrain_case=None):
    """List unresolved explicit inputs after construction defaults/overrides merge."""
    required = list(scheme.get("required_fields", []))
    if terrain_case:
        required.extend((scheme.get("terrain_variants") or {}).get(terrain_case, {}).get("required_fields", []))
    return list(dict.fromkeys(name for name in required if effective_fields.get(name) in (None, "")))
