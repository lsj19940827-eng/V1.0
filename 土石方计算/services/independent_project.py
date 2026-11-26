"""Serializable input boundary for the independent quantity workbench."""
from __future__ import annotations
import copy
import hashlib
import json
import math

from shapely.geometry import Polygon
from ..models.alignment import Alignment
from ..models.section import DesignProfile, ExcavationSlope, SlopeGrade


def input_hash(inputs, terrain_hash):
    # Portable longitudinal profile resources keep their byte identity after relocation.
    workbench = inputs.get("workbench") if isinstance(inputs, dict) else None
    if workbench and any(
        ((asset.get("siphon_axis_input") or {}).get("source") or {}).get("kind") in {"quantity_dxf", "quantity_input"}
        for network in workbench.get("networks", []) for asset in network.get("assets", [])
    ):
        inputs = copy.deepcopy(inputs)
        for network in inputs["workbench"].get("networks", []):
            for asset in network.get("assets", []):
                source = (asset.get("siphon_axis_input") or {}).get("source") or {}
                if source.get("kind") in {"quantity_dxf", "quantity_input"} and source.get("sha256"):
                    source.pop("path", None)
    text = json.dumps({"inputs": inputs, "terrain": terrain_hash}, ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def terrain_identity(report):
    """File identity plus the actual selected mesh within that file."""
    return {"source_sha256": report.get("source_sha256"),
            "mesh_index": report.get("mesh_index"), "units": report.get("units", "m")}


def _grades(values):
    if not values:
        raise ValueError("请提供至少一级施工边坡")
    return [SlopeGrade(float(v.get("ratio", v.get("slope"))), math.inf if v.get("height") is None else float(v["height"]),
                       float(v.get("berm_width", 0))) for v in values]


def calculate_request(tin, inputs, *, cancelled=None, progress=None):
    """The exact input snapshot, terrain identity, and result travel together."""
    from .independent_calculator import (ConstructionSection, LinearCalculationConfig,
                                        SiteExcavationConfig, calculate_linear, calculate_site)
    inputs = copy.deepcopy(inputs)
    accuracy = inputs.get("accuracy", {})
    kwargs = {"relative_tolerance": float(accuracy.get("relative_tolerance", .001)),
              "absolute_tolerance": float(accuracy.get("absolute_tolerance", .1)),
              "max_refinements": int(accuracy.get("max_refinements", 8))}
    mode = inputs.get("mode", "linear")
    # Keep the complete source identity while indexing only original faces
    # near the requested work. This is selection, never a new triangulation.
    from ..io.independent_terrain import select_terrain
    if mode in ("linear", "asset"):
        if mode == "linear":
            coordinates = [[row[1], row[2]] for row in inputs.get("line_rows", []) if len(row)==4]
        else:
            axis = inputs.get("asset", {}).get("alignment", {})
            coordinates = [[p["x"], p["y"]] for p in axis.get("plan_points", [])]
            coordinates += [p["origin"][:2] for p in axis.get("native_samples", []) if "origin" in p]
            if not coordinates:
                coordinates = [p["origin"][:2] for p in inputs.get("asset", {}).get("geometry_sections", [])]
        if coordinates:
            width = max(float(inputs.get("left_width",30)),float(inputs.get("right_width",30)))
            xs, ys = zip(*coordinates)
            tin = select_terrain(tin, (min(xs)-width,min(ys)-width,max(xs)+width,max(ys)+width))
    elif mode == "site" and inputs.get("site_boundary"):
        boundary = Polygon(inputs["site_boundary"],inputs.get("site_holes",[]))
        rise = max(0.0,float(tin.points[:,2].max())-float(inputs["bottom_elevation"]))
        width = 0.0
        for grade in _grades(inputs["site_grades"]):
            height = min(rise,grade.height)
            width += height*grade.ratio
            rise -= height
            if rise > 0:
                width += grade.berm_width
            else:
                break
        xmin,ymin,xmax,ymax = boundary.bounds
        tin = select_terrain(tin,(xmin-width-1e-6,ymin-width-1e-6,xmax+width+1e-6,ymax+width+1e-6))
    if mode == "asset":
        from ..adapters.independent_assets import calculate_asset
        result = calculate_asset(tin, inputs["asset"], settings=inputs.get("settings", {}),
                                 initial_interval=float(accuracy.get("initial_interval", 20)),
                                 left_width=float(inputs.get("left_width", 30)),
                                 right_width=float(inputs.get("right_width", 30)),
                                 cancelled=cancelled, progress=progress, **kwargs)
    elif mode == "linear":
        rows = inputs.get("line_rows", [])
        if len(rows) < 2:
            raise ValueError("线路至少需要两行桩号、X、Y及设计底高程")
        if any(len(row) != 4 or any(not math.isfinite(float(v)) for v in row) for row in rows):
            raise ValueError("线路必须提供完整的有限坐标和逐点设计底高程，不能用水位代替")
        if any(float(b[0]) <= float(a[0]) for a, b in zip(rows, rows[1:])):
            raise ValueError("线路桩号必须严格递增")
        alignment = Alignment.from_station_table([(float(s), float(x), float(y)) for s, x, y, z in rows])
        profile = DesignProfile(station_elevation_table={float(s): float(z) for s, x, y, z in rows})
        section = ConstructionSection(**inputs["section"])
        slopes = ExcavationSlope(alignment.start_station, alignment.end_station,
                                 _grades(inputs["left_grades"]), _grades(inputs["right_grades"]))
        config = LinearCalculationConfig(design_profile=profile, section=section, slope_config=slopes,
                                         left_width=float(inputs.get("left_width", 30)),
                                         right_width=float(inputs.get("right_width", 30)),
                                         initial_interval=float(accuracy.get("initial_interval", 20)), **kwargs)
        result = calculate_linear(tin, alignment, config, cancelled=cancelled, progress=progress)
    elif mode == "site":
        boundary = Polygon(inputs.get("site_boundary", []), inputs.get("site_holes", []))
        result = calculate_site(tin, SiteExcavationConfig(boundary, float(inputs["bottom_elevation"]),
                                                         _grades(inputs["site_grades"]), **kwargs),
                                cancelled=cancelled, progress=progress)
    else:
        raise ValueError("未知的算量类型")
    payload = result.to_dict()
    terrain = copy.deepcopy(getattr(tin, "import_report", {}))
    payload.update({"schema_version": "1.0", "kind": "site" if mode == "site" else "linear",
                    "units": "m", "inputs": inputs, "terrain": terrain,
                    "input_hash": input_hash(inputs, terrain_identity(terrain)),
                    "test_only":bool(inputs.get("test_only") or inputs.get("asset",{}).get("is_test")),
                    "status": "READY", "quantity_basis": "natural_cut_and_finished_fill_separate"})
    json.dumps(payload, allow_nan=False)
    return result, payload
