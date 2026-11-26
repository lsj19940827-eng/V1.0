"""Read-only real pipe views for unburied segments; never construction quantities."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

import numpy as np
from shapely.geometry import mapping

from .design_profiles import normalize_design_profile, clip_design_profile, evaluate_profile, profile_break_stations
from .network_alignment import NetworkAlignment
from .network_section_projection import Catalog
from .section_geometry import pipe_specs, section_structure


UNBURIED_MODES = {"exposed", "elevated", "above_ground", "open"}


def is_unburied_pipe(asset):
    pipe = asset.get("kind") in {"pipe", "pressure_pipe", "siphon"} or asset.get("section_type") in {
        "circular_culvert", "circular_channel", "circular_siphon",
    }
    return pipe and asset.get("construction", {}).get("installation_mode") in UNBURIED_MODES


def preview_identity(network, asset):
    alignment = network.get("alignment")
    if hasattr(alignment, "to_dict"):
        alignment = alignment.to_dict()
    text = json.dumps({"alignment": alignment, "asset": asset}, ensure_ascii=False,
                      sort_keys=True, default=str, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cancel(cancelled):
    if cancelled and cancelled():
        raise InterruptedError("结构预览已取消")


def _prepare(network, asset):
    if not is_unburied_pipe(asset):
        raise ValueError("只读预览仅用于明管或架空管道")
    source = deepcopy(asset)
    alignment = network.get("alignment")
    if isinstance(alignment, dict):
        alignment = NetworkAlignment.from_dict(alignment)
    if not isinstance(alignment, NetworkAlignment):
        raise ValueError("缺少真实平面轴线，不能生成结构预览")
    start, end = float(source["station_start"]), float(source["station_end"])
    alignment.get_xy_at_station(start); alignment.get_xy_at_station(end)
    source.update(station_start=start, station_end=end)
    source["preview_test_only"] = bool(network.get("test_only") or source.get("is_test") or source.get("test_only"))
    declared = (source.get("design_profile") or {}).get("reference") or source.get("alignment", {}).get("elevation_reference")
    if declared not in {"pipe_axis", "common_outer_bottom", "inner_invert"}:
        raise ValueError("需明确首管管轴、共同外管底或真实净内底高程基准")
    source["design_profile"] = clip_design_profile(normalize_design_profile(source, reference=declared), start, end)
    section = deepcopy(source["section"])
    count = len(section["pipes"]) if section.get("pipes") else float(section.get("pipe_count", 1))
    if count > 1 and section.get("pipe_spacing") is None:
        raw = section.get("pipes") or []
        if len(raw) != count or not all(p.get("offset") is not None for p in raw):
            raise ValueError("多管结构预览需明确管间净距或每根管真实偏距")
        # Material-independent dimensional normalization precedes explicit-gap derivation.
        trial = pipe_specs(section, recommended_material=None, require_lining_material=False)
        section["pipe_spacing"] = [b["offset"]-a["offset"]-(a["outer_diameter"]+b["outer_diameter"])/2
                                   for a,b in zip(trial,trial[1:])]
    pipes = pipe_specs(section, recommended_material=None, require_lining_material=False)
    proxy = deepcopy(pipes)
    for pipe in proxy:
        # The legacy section API recommends concrete when material is absent.
        # A neutral unknown token bypasses that recommendation only in this copy.
        if pipe["material_category"] == "unknown":
            pipe["material"] = "preview_unknown_material"
        if pipe["lining_thickness"] and pipe["lining_material_category"] == "unknown":
            pipe["lining_material"] = "preview_unknown_material"
    source["section"] = {**section, "pipes": proxy}
    source["workbench_geometry"] = False
    origin = np.asarray(alignment.get_xy_at_station(alignment.start_station))
    catalog = Catalog(alignment, [source], origin, {source["asset_id"]: 0.})
    return source, pipes, alignment, catalog, origin


def _section(prepared, identity, station, side, arc_segments, cancelled):
    _cancel(cancelled)
    source, pipes, alignment, catalog, origin = prepared
    station = float(station)
    pid = catalog.part_at(source["asset_id"], station, side)
    center, tangent, curvature = catalog.center_tangent_curvature(pid, station)
    z, slope = evaluate_profile(source, station, side)
    structure = section_structure(source, elevation=z, slope=slope, station=station,
                                  side=side, plan_curvature=curvature,
                                  arc_segments=4*math.ceil(max(256, int(arc_segments))/4))
    displayed = []
    for original, actual in zip(pipes, structure["pipes"]):
        pipe = deepcopy(original)
        pipe.pop("concrete_normal_area", None)
        pipe.update({key: actual[key] for key in ("axis_elevation", "vertical_slope", "outer_bottom", "outer_top")})
        for key in ("outer_bottom_offset", "outer_top_offset", "plan_curvature", "actual_plan_grade",
                    "section_model", "section_model_scope"):
            if key in actual:
                pipe[key] = deepcopy(actual[key])
        displayed.append(pipe)
    unknown = any(p["material_category"] == "unknown" or p["lining_thickness"] and
                  p["lining_material_category"] == "unknown" for p in pipes)
    mode = source["construction"]["installation_mode"]
    message = ("架空" if mode == "elevated" else "明管")+"结构预览；未计土方/基础"
    if unknown:
        message += "；管材/内衬材质未明确，仅显示真实轮廓"
    return {"section_id": f"preview-{source['asset_id']}-{station.hex()}-{side}",
            "asset_id": source["asset_id"], "station": station, "side": side,
            "view_only": True, "preview_kind": "unburied_pipe", "preview_identity": identity,
            "test_only": source["preview_test_only"],
            "quantity_status": "not_calculated", "not_in_quantity": True,
            "message": message, "installation_mode": mode,
            "source_identity": source.get("source_identity"),
            "center_xy": (center+origin).tolist(), "tangent": tangent.tolist(),
            "curvature_right": -curvature, "design_elevation": z, "vertical_slope": slope,
            "design_reference": source["design_profile"]["reference"],
            "ground_points": [], "roles": {}, "construction_geometry": {}, "material_areas": None,
            "structure_geometry": {"outer": mapping(structure["outer"]), "net_void": mapping(structure["net_void"]),
                                   "pipe_centers": deepcopy(structure["pipe_centers"]), "pipes": displayed, "materials": {}}}


def preview_unburied_section(network, asset, station, side="right", *, arc_segments=256, cancelled=None):
    """Use the real analytical axis and pipe cut, without terrain or quantity work."""
    return _section(_prepare(network, asset), preview_identity(network, asset), station, side, arc_segments, cancelled)


def preview_unburied_profile(network, asset, *, station=None, arc_segments=256, cancelled=None):
    """Sparse display-only levels, retaining all real breaks and their two limits."""
    prepared = _prepare(network, asset); source, _, alignment, _, _ = prepared
    start, end = source["station_start"], source["station_end"]
    breaks = {start, end, *profile_break_stations(source), *alignment.primitive_break_stations}
    breaks = {float(s) for s in breaks if start <= s <= end}
    samples = set(np.linspace(start, end, 81)) | breaks
    for element in source["design_profile"]["elements"]:
        if element["kind"] == "arc" and element["station_start"] < element["center_station"] < element["station_end"]:
            samples.add(element["center_station"])
    if station is not None:
        evaluate_profile(source, station); samples.add(float(station))
    identity = preview_identity(network, asset); records = []
    for s in sorted(samples):
        if s in breaks and start < s < end:
            records.append(_section(prepared, identity, s, "left", arc_segments, cancelled))
        records.append(_section(prepared, identity, s, "left" if s == end else "right", arc_segments, cancelled))
    return records
