"""Keep hydraulic diameters, nominal DN and construction envelopes separate.

Only newly imported/explicitly marked DN inputs opt into this rule. Existing
unmarked construction dimensions retain their historical interpretation.
"""
from __future__ import annotations

from copy import deepcopy
import math

from .contracts import ConstructionInputError

DN_ENVELOPE_BASIS = "nominal_dn_construction_envelope"
CONSTRUCTION_WALL = "construction_wall_thickness_m"
MATERIAL_OUTER = "material_outer_diameter_m"
CONSTRUCTION_DIAMETER_SOURCE = "施工占位：公称直径＋2×施工壁厚"
_SCOPE_PREFIX = "管道尺寸计量范围："


def is_pipe_asset(asset):
    return asset.get("kind") != "tunnel" and (
        asset.get("kind") in {"pipe", "pressure_pipe", "siphon"}
        or asset.get("section_type") in {"circular_culvert", "circular_channel", "circular_siphon"})


def _positive(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def _first_positive(*values):
    return next((float(value) for value in values if _positive(value)), None)


def _construction_outer(nominal, wall):
    try:
        if isinstance(wall, bool):
            raise TypeError
        thickness = float(wall)
    except (TypeError, ValueError) as error:
        raise ConstructionInputError("施工壁厚须为非负有限数") from error
    if not math.isfinite(thickness) or thickness < 0:
        raise ConstructionInputError("施工壁厚须为非负有限数")
    if not _positive(nominal):
        raise ConstructionInputError("公称直径须为正的有限数")
    outer = float(nominal) + 2 * thickness
    if not math.isfinite(outer):
        raise ConstructionInputError("施工占用直径须为有限数")
    return outer


def adopted_construction_diameter_fields(row):
    """Size overrides that are independent of a refreshed hydraulic source."""
    if row.get(CONSTRUCTION_WALL) is None:
        return ()
    return tuple(key for key in ("nominal_diameter_m", CONSTRUCTION_WALL, MATERIAL_OUTER)
                 if row.get(key) is not None)


def construction_pipe_dimension_values(asset):
    """Return the adopted sizes for each editable pipe row, including legacy outside sizes."""
    section = asset.get("section") or {}
    result = []
    for row in section.get("pipes") or [section]:
        nominal = _first_positive(row.get("nominal_diameter_m"), row.get("hydraulic_inner_diameter_m"),
                                  row.get("inner_diameter"), section.get("nominal_diameter_m"),
                                  section.get("hydraulic_inner_diameter_m"), section.get("inner_diameter"))
        construction_wall = row.get(CONSTRUCTION_WALL)
        outer = _first_positive(row.get("outer_diameter"), section.get("outer_diameter"))
        physical_outer = _first_positive(row.get(MATERIAL_OUTER))
        actual_wall = row.get("wall_thickness", section.get("wall_thickness"))
        if _positive(actual_wall):
            inner = _first_positive(row.get("construction_inner_diameter_m"), row.get("inner_diameter"),
                                    section.get("construction_inner_diameter_m"), section.get("inner_diameter"))
            lining = row.get("lining_thickness", section.get("lining_thickness")) or 0.
            if physical_outer is None:
                physical_outer = outer if construction_wall is None else None
                if physical_outer is None and inner is not None:
                    physical_outer = inner + 2 * (float(actual_wall) + float(lining))
        if construction_wall is not None:
            outer = _construction_outer(nominal, construction_wall)
        elif outer is None:
            outer = physical_outer or nominal
        legacy_outer = construction_wall is None and outer is not None and (
            nominal is None or not math.isclose(outer, nominal, abs_tol=1e-9, rel_tol=1e-9))
        result.append({"nominal_diameter_m": nominal,
                       CONSTRUCTION_WALL: 0. if construction_wall is None else construction_wall,
                       "outer_diameter": outer, MATERIAL_OUTER: physical_outer,
                       "has_legacy_outer_diameter": legacy_outer})
    return tuple(result)


def mark_imported_pipe_diameter(asset, *, diameter=None, source="Excel/水面线管径D(m)"):
    """Declare the user's DN convention on a new source import, preserving D."""
    if not is_pipe_asset(asset):
        return asset
    section = asset.setdefault("section", {})
    for row in [section, *(section.get("pipes") or [])]:
        source_d = diameter if row is section and diameter is not None else row.get("inner_diameter", section.get("inner_diameter"))
        if _positive(source_d):
            row.setdefault("nominal_diameter_m", float(source_d))
            row.setdefault("hydraulic_inner_diameter_m", float(source_d))
    if _positive(section.get("nominal_diameter_m")):
        sources = asset.setdefault("parameter_sources", {})
        sources.setdefault("section.nominal_diameter_m", source + "；本工程按公称直径DN登记，单位m")
        sources.setdefault("section.hydraulic_inner_diameter_m", source + "；保留原水力D值，未改写水力成果")
    normalize_pipe_dimensions(asset)
    return asset


def normalize_pipe_dimensions(asset):
    """Refresh opted-in envelopes in place, including explicitly adopted formulas.

    Supplying a real wall thickness exits the unknown-wall envelope. The source
    hydraulic D is retained; a construction bore may then be derived from the
    explicit outside diameter and wall for material geometry only.
    """
    if not is_pipe_asset(asset):
        return False
    section = asset.setdefault("section", {})
    raw = section.get("pipes")
    rows = raw if isinstance(raw, list) and raw else [section]
    if not (_positive(section.get("nominal_diameter_m"))
            or any(_positive(row.get("nominal_diameter_m")) for row in rows)):
        return False
    before = deepcopy(section)
    sources = asset.setdefault("parameter_sources", {})
    overrides = {**(asset.get("drawing_user_overrides") or {}),
                 **(asset.get("section_scheme_user_overrides") or {})}
    envelope_rows = []
    for index, row in enumerate(rows, 1):
        if row is not section:
            for key in ("nominal_diameter_m", "hydraulic_inner_diameter_m"):
                if row.get(key) is None:
                    inherited = row.get("inner_diameter", section.get(key))
                    if key == "hydraulic_inner_diameter_m" and row.get("nominal_diameter_m") is not None and row.get("inner_diameter") is None:
                        inherited = None
                    if inherited is not None:
                        row[key] = inherited
        nominal = row.get("nominal_diameter_m", section.get("nominal_diameter_m"))
        if not _positive(nominal):
            envelope_rows.append(row.get("earthwork_envelope_only") is True)
            continue
        path = "section.outer_diameter" if row is section else f"section.pipes[{index}].outer_diameter"
        old_auto = row.get("dn_envelope_diameter_m")
        inherited_outer = section.get("outer_diameter") if row is not section else None
        if row is not section and section.get("dn_envelope_diameter_m") is not None:
            inherited_outer = None
        outer = row.get("outer_diameter", inherited_outer)
        explicitly_edited = path in overrides or str(sources.get(path, "")).startswith("用户")
        auto_outer = _positive(old_auto) and _positive(outer) and math.isclose(
            float(outer), float(old_auto), abs_tol=1e-9, rel_tol=1e-9) and not explicitly_edited
        wall = (row.get("wall_thickness") if row is not section and row.get("earthwork_envelope_only") is True
                else row.get("wall_thickness", section.get("wall_thickness")))
        lining = row.get("lining_thickness", section.get("lining_thickness", 0.)) or 0.
        occupied_outer = None
        if row.get(CONSTRUCTION_WALL) is not None:
            occupied_outer = _construction_outer(nominal, row[CONSTRUCTION_WALL])
            if _positive(wall):
                outer = row.get(MATERIAL_OUTER)
            row["outer_diameter"] = occupied_outer
            sources[path] = CONSTRUCTION_DIAMETER_SOURCE
        if _positive(wall):
            if not _positive(outer):
                inner = row.get("inner_diameter", section.get("inner_diameter"))
                if _positive(inner):
                    outer = float(inner) + 2*(float(wall)+float(lining))
                    if occupied_outer is None:
                        row["outer_diameter"] = outer
                        sources[path] = "明确水力内径＋实际管壁及内衬厚度"
            if occupied_outer is not None and _positive(outer):
                row[MATERIAL_OUTER] = float(outer)
            # A DN envelope's source D is not silently rewritten as a pipe bore.
            # A changed actual inner input remains subject to strict consistency.
            inner = row.get("inner_diameter", section.get("inner_diameter"))
            hydraulic = row.get("hydraulic_inner_diameter_m", section.get("hydraulic_inner_diameter_m"))
            source_inner = inner is None or (_positive(hydraulic) and _positive(inner)
                and math.isclose(float(inner), float(hydraulic), abs_tol=1e-9, rel_tol=1e-9))
            if (_positive(outer) and source_inner and (occupied_outer is not None or auto_outer or row.get("diameter_basis") in {
                    DN_ENVELOPE_BASIS, "explicit_outer_construction_envelope", "actual_construction_dimensions"})):
                row["construction_inner_diameter_m"] = float(outer)-2*(float(wall)+float(lining))
            else:
                row.pop("construction_inner_diameter_m", None)
            row.pop("earthwork_envelope_only", None)
            row.pop("dn_envelope_diameter_m", None)
            row["diameter_basis"] = "actual_construction_dimensions"
            envelope_rows.append(False)
        else:
            if occupied_outer is not None:
                row["dn_envelope_diameter_m"] = occupied_outer
                row["diameter_basis"] = DN_ENVELOPE_BASIS
            elif not _positive(outer) or auto_outer:
                outer = float(nominal)
                row["outer_diameter"] = outer
                row["dn_envelope_diameter_m"] = outer
                row["diameter_basis"] = DN_ENVELOPE_BASIS
                sources[path] = "施工占位：采用本工程公称直径DN；未推定真实管壁及产品外径"
            else:
                row["outer_diameter"] = float(outer)
                row.pop("dn_envelope_diameter_m", None)
                row["diameter_basis"] = "explicit_outer_construction_envelope"
            row["earthwork_envelope_only"] = True
            row.pop("construction_inner_diameter_m", None)
            envelope_rows.append(True)
    if isinstance(raw, list) and raw:
        if all(envelope_rows):
            section["earthwork_envelope_only"] = True
        else:
            section.pop("earthwork_envelope_only", None)
        if len(rows) == 1 and rows[0].get("outer_diameter") is not None:
            section["outer_diameter"] = rows[0]["outer_diameter"]
    notes = [note for note in asset.get("quantity_scope_notes", [])
             if not str(note).startswith((_SCOPE_PREFIX, "仅按已给管外径及"))]
    if any(envelope_rows):
        notes.append(_SCOPE_PREFIX + "未提供实际管壁厚度的管道按DN或已明确施工外径计算占位、管座及沟槽回填；保留水力D与真实高程基准，管壁及内衬材料数量未计。")
    else:
        notes.append(_SCOPE_PREFIX + "采用明确施工外径、管壁及内衬厚度计算管材；原水力D和公称DN分别保留，材料须明确。")
    asset["quantity_scope_notes"] = notes
    return section != before


def effective_pipe_section(section):
    """Resolve edits for geometry without mutating persisted/source dictionaries."""
    asset = {"kind": "pipe", "section_type": "circular_culvert", "section": deepcopy(section)}
    normalize_pipe_dimensions(asset)
    return asset["section"]


def use_nominal_pipe_envelope(asset):
    """Opt an existing live input into DN without deleting actual construction.

    Only fields carrying an explicit construction-assumption source are removed.
    A previously derived outside diameter is removed only when its wall/lining
    assumption is removed. User overrides always take precedence. Historical
    result dictionaries and original_fields are never traversed or modified.
    """
    if not is_pipe_asset(asset):
        raise ValueError("按DN施工占位仅适用于管道、倒虹吸及圆管涵")
    section = asset.setdefault("section", {})
    rows = [("section", section), *[(f"section.pipes[{i}]", row)
        for i, row in enumerate(section.get("pipes") or [], 1)]]
    if not any(_positive(row.get("inner_diameter", row.get("nominal_diameter_m"))) for _, row in rows):
        raise ValueError("未找到来源管径D(m)，请先补充公称直径DN")
    sources = asset.setdefault("parameter_sources", {})
    overrides = {**(asset.get("drawing_user_overrides") or {}),
                 **(asset.get("section_scheme_user_overrides") or {})}
    removed = []
    for prefix, row in rows:
        removed_wall = False
        for key in ("wall_thickness", "lining_thickness", "material", "lining_material",
                    "base_thickness", "wall_thickness_left", "wall_thickness_right", "roof_thickness"):
            path = prefix + "." + key
            if (key in row and path not in overrides
                    and str(sources.get(path, "")).startswith("施工参数假定：")):
                removed_wall = removed_wall or key in {"wall_thickness", "lining_thickness"}
                removed.append({"field": path, "previous": deepcopy(row.pop(key)), "source": sources.pop(path)})
        outer_path = prefix + ".outer_diameter"
        source = str(sources.get(outer_path, ""))
        if ("outer_diameter" in row and outer_path not in overrides and (
                source.startswith("施工参数假定：")
                or removed_wall and source.startswith("水力内径＋"))):
            removed.append({"field": outer_path, "previous": deepcopy(row.pop("outer_diameter")),
                            "source": sources.pop(outer_path, "")})
        row.pop("construction_inner_diameter_m", None)
    mark_imported_pipe_diameter(asset, source="用户选择按DN施工占位；保留来源管径D(m)")
    removed_paths = {row["field"] for row in removed}
    # Source lists are inspectable audit metadata; discarded assumptions must
    # not continue to claim that an obsolete wall/material is still adopted.
    for key in ("drawing_parameter_sources", "section_scheme_parameter_sources"):
        if isinstance(asset.get(key), dict):
            for path in removed_paths:
                asset[key].pop(path, None)
    asset["pipe_dn_replaced_assumptions"] = removed
    asset["geometry_sections"] = []
    return asset
