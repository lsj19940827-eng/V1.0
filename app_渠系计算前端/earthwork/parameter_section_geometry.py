"""Geometry used by the parameter editor, in the local construction section."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import math

from shapely.errors import GEOSException
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry

from 土石方计算.core.construction_geometry import _polygonal
from 土石方计算.services.construction_rules import effective_construction, normalized_construction
from 土石方计算.services.dedicated_structure_geometry import DEDICATED_TYPES, TUNNEL_TYPES, tunnel_void
from 土石方计算.services.pipe_construction_defaults import DEFAULT_MANUAL_BACKFILL_HEIGHT_M, PIPE_BACKFILL_HEIGHT_PATH
from 土石方计算.services.section_geometry import (
    _close_bedding_to_actual_excavation, add_foundation_materials, channel_crown_excavation_path, construction_floor_steps,
    number, section_structure, slope_grades, trace_to_ground,
)
from 土石方计算.services.section_parameter_decisions import parameter_missing, parameter_value
from 土石方计算.services.section_scheme_bindings import _get

from .pipe_standard_drawing_details import PipeStandardDrawingDetails, pipe_standard_drawing_details


_TYPES = DEDICATED_TYPES | {
    "circular_culvert", "circular_channel", "circular_siphon", "rectangular_culvert",
    "arch_culvert", "box_foundation", "u_channel", "rectangular_channel",
    "trapezoidal_channel", "compound_trapezoidal_channel",
}
_INPUT_ERRORS = (ValueError, TypeError, KeyError, ArithmeticError, GEOSException)
PIPE_COVER_TARGETS = frozenset({"cover_depth", "cover_above_terrain"})


def supports_parameter_section(asset):
    return isinstance(asset, dict) and asset.get("section_type") in _TYPES


@dataclass
class PipeCompletion:
    cover: tuple[tuple[float, float], tuple[float, float]]
    platforms: dict[str, tuple[tuple[float, float], tuple[float, float]]]
    fill_slopes: dict[str, tuple[tuple[float, float], tuple[float, ...]]] = field(default_factory=dict)


@dataclass
class PipeBackfill:
    regions: dict[str, BaseGeometry]
    interface: BaseGeometry
    dimension: tuple[tuple[float, float], tuple[float, float]]
    height: float
    original_surface: tuple[tuple[float, float], ...]
    finished_surface: tuple[tuple[float, float], ...]
    fill_slope: tuple[tuple[float, float], float] | None = None
    encasement_interface: BaseGeometry | None = None
    completion: PipeCompletion | None = None


@dataclass
class ParameterGeometry:
    structure: dict = field(default_factory=dict)
    construction: dict = field(default_factory=dict)
    pending: set = field(default_factory=set)
    notices: list = field(default_factory=list)
    floor: list = field(default_factory=list)
    work_spaces: dict = field(default_factory=dict)
    slopes: dict = field(default_factory=dict)
    trench_top: list = field(default_factory=list)
    pipe_backfill: PipeBackfill | None = None
    drawing_details: PipeStandardDrawingDetails | None = None


def _partial_structure(asset, result):
    section = asset.get("section") or {}
    kind = asset["section_type"]
    if kind in TUNNEL_TYPES:
        try:
            opening = tunnel_void(asset)
        except _INPUT_ERRORS:
            return {}
        result.notices.append("当前显示已知净空")
        return {"net_void": opening, "section_type": kind}
    if kind in {"circular_culvert", "circular_channel", "circular_siphon"}:
        # The outside envelope can be drawn even while pipe materials are being entered.
        sec = deepcopy(section)
        for pipe in [sec, *(sec.get("pipes") or [])]:
            pipe["earthwork_envelope_only"] = True
        try:
            structure = section_structure({**asset, "section": sec})
        except _INPUT_ERRORS:
            return {}
        result.notices.append("当前显示已知管外轮廓")
        return structure
    if kind == "rectangular_culvert":
        try:
            w, h = float(section["inner_width"]), float(section["inner_height"])
            if not (math.isfinite(w) and w > 0 and math.isfinite(h) and h > 0):
                return {}
            from 土石方计算.services.section_geometry import _chamfered_rectangular_void
            opening = _chamfered_rectangular_void(section, w, h)
        except _INPUT_ERRORS:
            return {}
        result.notices.append("当前显示已知净空")
        return {"net_void": opening, "section_type": kind}
    channel_kind = {"aqueduct_rectangular": "rectangular_channel", "aqueduct_u": "u_channel"}.get(kind, kind)
    if channel_kind.endswith("channel"):
        from 土石方计算.services.construction_templates import _section_outer
        try:
            rings, _ = _section_outer(channel_kind, {**section, "wall_thickness":0, "base_thickness":0}, 64)
            opening = Polygon(rings[0])
        except _INPUT_ERRORS:
            return {}
        result.notices.append("当前显示已知净空")
        return {"net_void": opening, "section_type": kind}
    return {}


def _construction_edges(asset, result, *, floor_known, show_pipe_trench):
    """Use the same anchor, working-space reference and profile as construction_on_ground."""
    s, c, pending = result.structure, result.construction, result.pending
    if s.get("dedicated_construction") or c.get("installation_mode") in {"exposed", "elevated", "open", "above_ground"}:
        return
    if not s.get("occupancy") or s["occupancy"].is_empty:
        return
    if "retaining_wall" in (s.get("component_regions") or {}) and not c.get("floor_steps"):
        return
    left, floor, right, top = s["occupancy"].bounds
    seat = c.get("pipe_seat") or c.get("pipe_support") or {}
    reference = c.get("working_space_reference")
    if s.get("pipes") and seat.get("enabled", True) and seat.get("bottom_width_mode") == "trench_bottom":
        reference = "pipe_outer"
    if reference == "pipe_outer":
        left, _, right, _ = s["outer"].bounds
    elif reference == "pipe_foundation":
        left, right = s.get("pipe_foundation_span", s["outer"].bounds[::2])
    replacement = (s.get("component_regions") or {}).get("foundation_replacement")
    outline = s.get("replacement_excavation_floor")
    full_replacement = replacement and (c.get("foundation_replacement") or {}).get("width_reference", "excavation_bottom") == "excavation_bottom"
    work_left, work_right = left, right
    if full_replacement:
        seat_region = s["component_regions"].get("pipe_seat")
        if outline and seat_region:
            work_left, work_right = seat_region["geometry"].bounds[::2]
        elif reference != "pipe_outer":
            # Workspaces were included when building the replacement upper rim.
            # Recover their original anchors before the replacement was added.
            bodies = [s["outer"], *s["materials"].values(),
                      *(v["geometry"] for k,v in s["component_regions"].items() if k != "foundation_replacement")]
            bounds = [part.bounds for part in bodies if not part.is_empty]
            work_left, work_right = min(b[0] for b in bounds), max(b[2] for b in bounds)
    available = {}
    for side, origin, sign in (("left", work_left, -1), ("right", work_right, 1)):
        key = "working_space_" + side
        width = c.get(key)
        if width is not None and "construction." + key not in pending:
            width = float(width)
            if math.isfinite(width) and width >= 0:
                available[side] = (origin, origin + sign * width)
    crown = asset["section_type"] in {"u_channel", "trapezoidal_channel"}
    if not crown:
        for side, span in available.items():
            result.work_spaces[side] = (*span, floor)
    if not floor_known:
        return
    path = construction_floor_steps(c, s)
    if not path and outline and c.get("excavation_base_mode", "flat") == "flat":
        path = outline
    elif not path and crown:
        path = channel_crown_excavation_path(asset, s)
    elif not path and c.get("excavation_base_mode", "flat") == "flat" and len(available) == 2:
        if full_replacement and reference != "pipe_outer":
            path = [(left, floor), (right, floor)]
        else:
            path = [(available["left"][1], floor), (available["right"][1], floor)]
    if path:
        result.floor = list(path)
        if not crown:
            for side, (_, z) in (("left", path[0]), ("right", path[-1])):
                if side in available:
                    result.work_spaces[side] = (*available[side], z)
        if c.get("excavation_layer_mode") == "surface_thickness":
            result.notices.append("分层坡脚按地表与基岩界线确定")
            return
        sides = []
        for side, start, sign in (("left", path[0], -1), ("right", path[-1], 1)):
            if "construction.excavation_slope_" + side in pending:
                continue
            try:
                grades = slope_grades(c, side)
            except _INPUT_ERRORS:
                continue
            sides.append((side, start, sign, grades))
        trench_top = None
        if show_pipe_trench and s.get("pipes") and sides:
            _, pipe_bottom, _, pipe_top = s["outer"].bounds
            highest_bench = max(start[1] + math.fsum(grade.height for grade in grades if math.isfinite(grade.height))
                                for _, start, _, grades in sides)
            crown = max(pipe["outer_top"] for pipe in s["pipes"])
            height = _pipe_backfill_height(c)
            split = crown + height if height is not None else crown
            # The drawn ground is schematic. Headroom above the split keeps
            # both zones visible without altering the adopted slope grades.
            trench_top = max(s["occupancy"].bounds[3], split, highest_bench) + (pipe_top - pipe_bottom) / 2
        for side, start, sign, grades in sides:
            x, z = start
            points = [(x, z)]
            for grade in grades:
                if math.isfinite(grade.height):
                    dh = grade.height
                elif trench_top is not None:
                    dh = trench_top - z
                else:
                    dh = max(top-floor, right-left) * .24 / math.hypot(1, grade.ratio)
                x, z = x + sign * dh * grade.ratio, z + dh
                points.append((x, z))
                if math.isfinite(grade.height) and grade.berm_width:
                    x += sign * grade.berm_width
                    points.append((x, z))
            result.slopes[side] = (points, [grade.ratio for grade in grades])
        if trench_top is not None and len(result.slopes) == 2:
            result.trench_top = [result.slopes[side][0][-1] for side in ("left", "right")]


def _pipe_backfill_height(construction):
    height = _get({"construction": construction}, PIPE_BACKFILL_HEIGHT_PATH)
    if height is None:
        return DEFAULT_MANUAL_BACKFILL_HEIGHT_M
    if isinstance(height, bool):
        return None
    try:
        height = float(height)
    except (TypeError, ValueError):
        return None
    return height if math.isfinite(height) and height >= 0 else None


def _pipe_surfaces(trench_top, structure, details):
    ground = tuple(trench_top)
    if details is None:
        return ground, ground, Polygon(), None
    (left, level), (right, _) = ground
    width = right - left
    _, bottom, _, top = structure["outer"].bounds
    diameter = top - bottom
    if details.surface == "restore_ground":
        # The source draws original terrain and the restored profile separately.
        # Small schematic undulations keep them legible without implying fill.
        relief = min(diameter * .11, width * .02)
        natural = tuple((left + at * width, level + offset * relief) for at, offset in (
            (0., .32), (.18, .82), (.34, .10), (.52, -.22), (.71, .20), (.85, .66), (1., .40),
        ))
        return natural, ground, Polygon(), None
    if details.surface == "roadbed":
        # The original drawing distinguishes pavement from subgrade, but the
        # restored pavement buildup is supplied by the local road design.
        gap = min(diameter * .2, width * .055)
        pavement = ((left, level + gap), (right, level + gap))
        return pavement, ground, Polygon(), None
    if details.surface == "hillside_cut":
        rise = min(diameter, width * .26)
        natural = (
            (left, level + rise * .18),
            (left + width * .28, level + rise * .31),
            (left + width * .64, level + rise * .63),
            (right, level + rise),
        )
        return natural, ground, Polygon(), None
    ratio = details.new_fill_slope_ratio
    if details.surface == "raised_fill" and ratio:
        # This is a schematic rise for the drawn upper embankment, not a design
        # height. The source's slope ratio and centerline limit are shown separately.
        rise = min(diameter / 6, width / (5 * ratio), .15)
        inset = rise * ratio
        finished = (ground[0], (left + inset, level + rise), (right - inset, level + rise), ground[1])
        slope = ((right - inset / 2, level + rise / 2), ratio)
        return ground, finished, _polygonal(Polygon(finished)), slope
    if details.surface == "hillside_mixed" and ratio:
        rise = min(diameter, width / (4 * ratio))
        inset = rise * ratio
        middle = (left + right) / 2
        toe = (left - inset, level - rise)
        raw = (toe, (middle, level), ground[1])
        finished = (toe, *ground)
        wedge = Polygon([toe, ground[0], (middle, level)])
        slope = ((left - inset / 2, level - rise / 2), ratio)
        return raw, finished, _polygonal(wedge), slope
    return ground, ground, Polygon(), None


def _cover_pipe_surfaces(trench_top, structure, construction):
    """Trace the adopted completion surface against the flat schematic ground."""
    ground = tuple(trench_top)
    level = ground[0][1]
    left, _, right, crown = structure["outer"].bounds
    crest = crown + number(construction, "final_cover_depth", construction.get("cover_depth", 0))
    change = crest - level
    filling = change > 0
    if construction["target_mode"] == "cover_above_terrain" and change < -1e-9:
        return ground, ground, Polygon(), Polygon(), None

    highest = max(range(len(structure["pipes"])), key=lambda i: structure["pipes"][i]["outer_top"])
    crown_x = structure["pipes"][highest].get("outer_top_offset", structure["pipe_centers"][highest][0])
    completion = PipeCompletion(((crown_x, crown), (crown_x, crest)), {})
    traces = []
    for side, edge, direction in (("left", left, -1), ("right", right, 1)):
        start = (edge + direction * number(construction, "bank_top_width_" + side, 0), crest)
        completion.platforms[side] = ((edge, crest), start)
        if abs(change) <= 1e-9:
            continue
        grades = slope_grades(construction, side, filling=filling)
        reach = abs(change) * max(grade.ratio for grade in grades) + math.fsum(grade.berm_width for grade in grades) + 1.
        schematic_ground = [(start[0] - reach, level), (start[0] + reach, level)]
        trace = trace_to_ground(start, schematic_ground, grades, direction, filling=filling)
        traces.append(trace)
        if filling:
            legs = [(a, b) for a, b in zip(trace, trace[1:]) if a[1] != b[1]]
            if legs:
                a, b = max(legs, key=lambda leg: leg[0][1] - leg[1][1])
                completion.fill_slopes[side] = (((a[0] + b[0]) / 2, (a[1] + b[1]) / 2),
                                                tuple(grade.ratio for grade in grades[:len(legs)]))
    if not traces:
        return ground, ground, Polygon(), Polygon(), completion
    surface = (*reversed(traces[0]), *traces[1])
    ground = ((min(ground[0][0], surface[0][0]), level),
              (max(ground[-1][0], surface[-1][0]), level))
    final = (ground[0], *surface, ground[-1])
    final = tuple(point for i, point in enumerate(final) if i == 0 or point != final[i - 1])
    changed_soil = _polygonal(Polygon(surface))
    if filling:
        return ground, final, changed_soil, Polygon(), completion
    return ground, final, Polygon(), changed_soil, completion


def _pipe_backfill(result):
    if not result.trench_top:
        return
    height = _pipe_backfill_height(result.construction)
    if height is None:
        result.pending.add(PIPE_BACKFILL_HEIGHT_PATH)
        return
    left_slope, right_slope = (result.slopes[side][0] for side in ("left", "right"))
    trench = Polygon([*result.floor, *right_slope[1:], *reversed(left_slope[1:])])
    if trench.is_empty or not trench.is_valid:
        return
    structure = result.structure
    if structure.get("bedding_excavation_closure"):
        # Use the adopted bedding closure with the drawn trench as its
        # reference. This is a detached, schematic view of the same rule.
        structure = _close_bedding_to_actual_excavation(dict(structure), trench, trench)
        structure.pop("bedding_excavation_closure")
        structure.pop("bedding_side_boundary")
        result.structure = structure
    completion = None
    if result.construction.get("target_mode") in PIPE_COVER_TARGETS:
        original, finished, fill, removed, completion = _cover_pipe_surfaces(
            result.trench_top, structure, result.construction,
        )
        slope = None
    else:
        original, finished, fill, slope = _pipe_surfaces(result.trench_top, structure, result.drawing_details)
        removed = Polygon()
    fill = _polygonal(fill.difference(structure["occupancy"]))
    surrounding = _polygonal(trench.difference(structure["occupancy"]).difference(
        fill if removed.is_empty else removed
    ))
    crown = max(pipe["outer_top"] for pipe in structure["pipes"])
    elevation = crown + height
    left, bottom, right, _ = trench.bounds
    lower = box(left, bottom, right, elevation)
    manual = _polygonal(surrounding.intersection(lower))
    mechanical = _polygonal(surrounding.difference(lower))
    interface = surrounding.intersection(LineString([(left, elevation), (right, elevation)]))
    _, _, outer_right, _ = structure["outer"].bounds
    anchor = outer_right + (right - outer_right) * .30
    encasement_interface = None
    details = result.drawing_details
    encasement = structure.get("component_regions", {}).get("pipe_encasement")
    if details and not details.shows_crown_partition and encasement:
        enc_left, _, enc_right, enc_top = encasement["geometry"].bounds
        if not math.isclose(enc_top, elevation, abs_tol=1e-7):
            line = LineString([(left, enc_top), (right, enc_top)])
            encasement_interface = line.intersection(trench).difference(
                box(enc_left, enc_top - 1e-7, enc_right, enc_top + 1e-7)
            )
    result.pipe_backfill = PipeBackfill(
        {"manual_backfill": manual, "mechanical_backfill": mechanical, "embankment": fill},
        interface, ((anchor, crown), (anchor, elevation)), height, original, finished, slope, encasement_interface,
        completion,
    )


def parameter_geometry(asset, scheme=None, pending_paths=(), *, show_pipe_trench=False, pipe_terrain_case=None):
    result = ParameterGeometry(pending=set(pending_paths or ()))
    if not supports_parameter_section(asset):
        return result
    try:
        c = effective_construction(asset)
    except _INPUT_ERRORS:
        c = normalized_construction(asset["section_type"], asset.get("construction"))
        result.pending.update(path for path, mode in (asset.get("replacement_parameter_modes") or {}).items()
                              if mode == "automatic")
    adopted = {**asset, "construction": c}
    for path in (scheme or {}).get("required_fields", ()):
        value, _basis = parameter_value(adopted, path, scheme)
        if parameter_missing(path, value):
            result.pending.add(path)
    try:
        structure = section_structure(adopted)
    except _INPUT_ERRORS:
        # A malformed additional member does not change the dimensions of the
        # hydraulic body. Retry without those members before dropping to net space.
        from 土石方计算.services.section_scheme_components import PROFILE_FIELDS
        optional = (*PROFILE_FIELDS, "component_specs", "discrete_components")
        section = adopted.get("section") or {}
        structure = {}
        if any(section.get(key) for key in optional):
            reduced = {k:v for k,v in section.items() if k not in optional}
            try:
                structure = section_structure({**adopted, "section":reduced})
            except _INPUT_ERRORS:
                pass
            else:
                result.notices.append("附属构件轮廓待核对")
        if not structure:
            structure = _partial_structure(adopted, result)
    result.structure = structure
    if "outer" not in structure:
        return result
    result.construction = deepcopy(c)
    if structure.get("dedicated_construction"):
        return result
    # Classify the seats and jackets in their own display layers. Separate-material
    # classification changes aggregation only; it preserves the actual cut polygons.
    for key in ("pipe_seat", "pipe_support", "encasement", "pipe_encasement"):
        if result.construction.get(key):
            result.construction[key]["separate_material"] = True
    replacement_pending = any("foundation_replacement" in path for path in result.pending)
    base_pending = any(path.startswith(("construction.pipe_seat.", "construction.encasement.")) for path in result.pending)
    if replacement_pending or base_pending:
        result.construction["foundation_replacement"] = {"enabled": False}
    if base_pending:
        for key in ("pipe_seat", "encasement"):
            if any(path.startswith("construction." + key + ".") for path in result.pending):
                result.construction[key] = {"enabled": False}
                if result.construction.get("bedding_reference") == "pipe_seat_bottom":
                    result.construction["bedding_thickness"] = 0.
    try:
        result.structure = add_foundation_materials(dict(structure), result.construction)
    except _INPUT_ERRORS:
        result.notices.append("请核对基础构造尺寸")
        # A replacement whose lower rim collapses must not hide its known support.
        try:
            result.structure = add_foundation_materials(dict(structure), {**result.construction, "foundation_replacement": {"enabled": False}})
        except _INPUT_ERRORS:
            return result
        return result
    if not base_pending:
        if show_pipe_trench and result.structure.get("pipes"):
            result.drawing_details = pipe_standard_drawing_details(scheme, pipe_terrain_case)
        try:
            _construction_edges(adopted, result, floor_known=not replacement_pending, show_pipe_trench=show_pipe_trench)
            _pipe_backfill(result)
        except _INPUT_ERRORS:
            pass
    if result.structure.get("bedding_excavation_closure"):
        result.notices.append("垫层侧边随实际地形闭合")
    return result
