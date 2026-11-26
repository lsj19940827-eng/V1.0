"""沿解析线路的工程断面法；只有二维施工区域与原 TIN 剖面参与算量。

弯道以横向一阶矩修正长度；跨曲率中心用绝对 Jacobian。支持逐断面
独立计量，以及按世界 XY 解析法向投影和实际 Z 区间扣重，不生成三维实体。
"""
from __future__ import annotations

from .construction_rules import effective_construction, normalize_construction_inputs
from .earthwork_scope import (trenchless_exclusion, require_disjoint_trenchless_ranges,
                              trenchless_excavation_quantities, TRENCHLESS_EXCAVATION_RULE,
                              current_exclusion_records, trenchless_live_route_id)

from bisect import bisect_left, bisect_right, insort
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
import math
import time

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon, MultiPolygon, LineString, box, mapping
from shapely.ops import unary_union

from ..core.tin_interpolator import TINInterpolator
from ..core.cross_section import CrossSectionCalculator
from ..core.construction_geometry import compute_construction_state, _polygonal
from ..adapters.independent_assets import _ground_at, _grades
from .construction_templates import build_construction_section, _section_outer
from .contracts import ConstructionInputError, finite_number
from .workbench_scope import AssetDataPending
from .network_alignment import NetworkAlignment
from .pipe_construction_defaults import DEFAULT_MANUAL_BACKFILL_HEIGHT_M
from .component_quantities import (extra_material_roles, component_role, section_components, nonconcrete_pipe_components,
    integrate_components, aggregate_components, material_identity)

ROLES = ("excavation", "backfill", "embankment")
BACKFILL_ROLES = ("manual_backfill", "mechanical_backfill")
BACKFILL_VOLUME_KEYS = tuple(role+"_volume" for role in BACKFILL_ROLES)
MATERIAL_ROLES = ("concrete", "bedding")
RAW_ROLES = ("excavation", "permanent", "measured", "open_air", "target", "removal")
LAYER_ROLES = ("overburden", "bedrock", "unclassified_excavation")
FIXED_INTEGRATION_METHOD = "exact_tin_average_end_sections"
FIXED_SAMPLING_CONTRACT = "route_grid_curves_2"
FIXED_SAMPLING_POLICY = "route_grid_with_curve_sections"
CURVE_MAX_TURN_ANGLE_DEG = 5.0
CURVE_MAX_CHORD_HEIGHT_M = 0.05
CURVE_STATION_MERGE_TOLERANCE_M = 0.001


def section_result_publishable(payload):
    """Accept converged runs or a complete, explicitly unchecked fixed run.

    A bare ``publishable`` flag cannot turn an old failed adaptive run into a
    usable result. Fixed results must carry their actual single-round records.
    """
    if not isinstance(payload,dict) or payload.get("status")!="READY":
        return False
    validation=payload.get("validation") or {}
    if not isinstance(validation,dict):return False
    if validation.get("automatic_terrain_unmeasured_only") is True:
        from .workbench_automatic_ranges import unmeasured_only_publishable
        return unmeasured_only_publishable(payload)
    if validation.get("automatic_tunnel_exposed_only") is True:
        from .tunnel_exposure_scope import exposed_tunnel_only_publishable
        return exposed_tunnel_only_publishable(payload)
    if validation.get("automatic_unsupported_only") is True:
        from .unsupported_pipe_calculation import unsupported_only_publishable
        return unsupported_only_publishable(payload)
    if validation.get("sluice_gate_only") is True:
        from .sluice_gate import gate_only_publishable
        return gate_only_publishable(payload)
    if validation.get("trenchless_only") is True:
        policy = payload.get("trenchless_excavation_policy")
        bore = trenchless_excavation_quantities(payload.get("excluded_assets") or [], policy=policy)
        return (payload.get("integration_method") == policy
                and not any(payload.get(key) for key in ("assets", "rows", "sections", "segments"))
                and all(payload.get(role+"_volume") == 0. for role in ROLES)
                and bore.get("trenchless_excavation_volume") is not None
                and all(payload.get(key) == value for key, value in bore.items()))
    inputs=payload.get("inputs") or {}
    if not isinstance(validation,dict) or not isinstance(inputs,dict):return False
    accuracy=inputs.get("accuracy") or {}
    if not isinstance(accuracy,dict):return False
    declared=[v for v in (payload.get("sampling_mode"),validation.get("sampling_mode"),
        accuracy.get("sampling_mode")) if v is not None]
    if declared and (declared[0] not in {"adaptive","fixed"} or any(v!=declared[0] for v in declared)):
        return False
    fixed=bool(declared) and declared[0]=="fixed"
    if not fixed:
        return (payload.get("converged") is True and validation.get("converged") is not False
                and not validation.get("fixed_spacing_complete"))
    history=payload.get("convergence_history") or []
    sections=payload.get("sections") or []
    segments=payload.get("segments") or []
    if any(not isinstance(v,list) for v in (history,sections,segments)):return False
    if any(not isinstance(v,dict) for v in [*history,*sections,*segments]):return False
    if not (payload.get("converged") is False and validation.get("converged") is False
            and validation.get("fixed_spacing_complete") is True
            and validation.get("convergence_checked") is False
            and validation.get("sampling_mode")=="fixed"
            and validation.get("fixed_sampling_contract")==FIXED_SAMPLING_CONTRACT
            and validation.get("sampling_policy")==FIXED_SAMPLING_POLICY
            and payload.get("integration_method")==FIXED_INTEGRATION_METHOD
            and len(history)==1 and sections and segments):
        return False
    run=history[0]
    if not (run.get("refinement")==0 and run.get("sampling_policy")==FIXED_SAMPLING_POLICY
            and run.get("fixed_sampling_contract")==FIXED_SAMPLING_CONTRACT
            and run.get("convergence_checked") is False and run.get("convergence_scope")=="not_checked"
            and run.get("passed") is False and run.get("checks")==[]
            and run.get("section_count")==len(sections) and run.get("segment_count")==len(segments)):
        return False
    curve=validation.get("curve_sampling")
    if (not isinstance(curve,dict) or curve!=run.get("curve_sampling")
            or curve.get("enabled") is not True
            or curve.get("max_turn_angle_deg")!=CURVE_MAX_TURN_ANGLE_DEG
            or curve.get("max_chord_height_m")!=CURVE_MAX_CHORD_HEIGHT_M
            or curve.get("merge_tolerance_m")!=CURVE_STATION_MERGE_TOLERANCE_M
            or any(type(curve.get(k)) is not int or curve[k]<0 for k in
                ("arc_count","curve_station_count","added_station_count","added_section_count"))):
        return False
    if any(not isinstance(s.get("asset_id"),str) or not isinstance(s.get("station"),(int,float))
        or not math.isfinite(s["station"]) or type(s.get("curve_added")) is not bool
        or type(s.get("curve_station_added")) is not bool
        or not isinstance(s.get("sampling_reasons"),list) or not s["sampling_reasons"]
        or any(not isinstance(reason,str) for reason in s["sampling_reasons"]) for s in sections):return False
    curve_stations={(s.get("asset_id"),s.get("station")) for s in sections
        if any(reason.startswith("curve_") for reason in s["sampling_reasons"])}
    added_stations={(s.get("asset_id"),s.get("station")) for s in sections if s["curve_station_added"]}
    if (curve["curve_station_count"]!=len(curve_stations)
            or curve["added_station_count"]!=len(added_stations)
            or curve["added_section_count"]!=sum(s["curve_added"] for s in sections)):
        return False
    section_ids={s.get("section_id") for s in sections}
    if any(not isinstance(s,str) or not s for s in section_ids) or len(section_ids)!=len(sections):return False
    lookup={s["section_id"]:s for s in sections}
    if not all(s.get("integration_rule")=="average_end_sections"
        and isinstance(s.get("length"),(int,float)) and math.isfinite(s["length"]) and s["length"]>0
        and not s.get("mid_section_id") and s.get("start_section_id") in section_ids
        and s.get("end_section_id") in section_ids for s in segments):return False
    for segment in segments:
        start,end=segment.get("station_start"),segment.get("station_end")
        if (not isinstance(start,(int,float)) or not isinstance(end,(int,float))
                or not math.isfinite(start) or not math.isfinite(end)
                or not math.isclose(segment["length"],end-start,rel_tol=1e-10,abs_tol=1e-7)):
            return False
        for end in ("start","end"):
            record=lookup[segment[end+"_section_id"]]
            if (record.get("asset_id")!=segment.get("asset_id")
                    or record.get("station")!=segment.get("station_"+end)
                    or record.get("part_id")!=segment.get(end+"_part_id")
                    or record.get("primitive_id")!=segment.get(end+"_primitive_id")):
                return False
    by_asset={}
    for segment in segments:by_asset.setdefault(segment["asset_id"],[]).append(segment)
    assets=payload.get("assets") or []
    if not isinstance(assets,list) or any(not isinstance(a,dict) for a in assets):return False
    if {a.get("asset_id") for a in assets}!=set(by_asset):return False
    for asset in assets:
        spans=sorted(by_asset[asset["asset_id"]],key=lambda s:s["station_start"])
        if (spans[0]["station_start"]!=asset.get("station_start")
                or spans[-1]["station_end"]!=asset.get("station_end")
                or any(a["station_end"]!=b["station_start"] for a,b in zip(spans,spans[1:]))):
            return False
    return True


class NetworkSectionCalculationError(ConstructionInputError):
    def __init__(self, message, *, code="invalid_section_network", diagnostics=None):
        super().__init__(message)
        self.code = code
        self.diagnostics = diagnostics or []


@dataclass
class NetworkSectionCalculationResult:
    quantities: dict
    assets: list
    sections: list
    segments: list
    convergence_history: list
    validation: dict
    diagnostics: list = field(default_factory=list)
    terrain_metadata: dict = field(default_factory=dict)
    input_metadata: dict = field(default_factory=dict)
    test_only: bool = False
    method: str = "exact_tin_actual_midpoint_section_integration"
    quantity_items: list = field(default_factory=list)
    layered_excavation_scope: dict = field(default_factory=dict)
    excluded_assets: list = field(default_factory=list)
    trenchless_excavation: dict = field(default_factory=dict)

    @property
    def rows(self):
        return self.assets

    @property
    def converged(self):
        return self.validation["converged"]

    @property
    def publishable(self):
        return any(self.validation.get(key) for key in (
            "trenchless_only", "automatic_unsupported_only", "automatic_terrain_unmeasured_only",
            "automatic_tunnel_exposed_only", "sluice_gate_only",
        )) or self.converged or (self.validation.get("sampling_mode")=="fixed"
            and self.validation.get("fixed_spacing_complete") is True
            and self.validation.get("convergence_checked") is False)

    def to_dict(self):
        return {"schema": "network_sections_1.0", "kind": "network", "method": self.method,
                "integration_method": self.validation.get("integration_method",self.method),
                "status": "READY" if self.publishable else "NOT_CONVERGED",
                "converged": self.converged, "publishable":self.publishable,
                "sampling_mode":self.validation.get("sampling_mode","adaptive"),
                "profile_step":self.validation.get("profile_step"),
                "units": "m", "test_only": self.test_only,
                **self.quantities, "quantities": deepcopy(self.quantities),
                "assets": deepcopy(self.assets), "rows": deepcopy(self.assets),
                "sections": deepcopy(self.sections), "segments": deepcopy(self.segments),
                "convergence_history": deepcopy(self.convergence_history),
                "validation": deepcopy(self.validation), "diagnostics": deepcopy(self.diagnostics),
                "terrain_metadata": deepcopy(self.terrain_metadata), "input_metadata": deepcopy(self.input_metadata),
                "allocation_policy": ("independent_sections_no_overlap_deduction"
                    if self.validation.get("overlap_policy")=="independent_sections"
                    else "section_Z_interval_station_first_owner"),
                "geometry_coordinate_mode": "offset_absolute_elevation",
                "quantity_items":deepcopy(self.quantity_items),
                "excluded_assets":deepcopy(self.excluded_assets),
                **deepcopy(self.trenchless_excavation),
                **({"layered_excavation_scope":deepcopy(self.layered_excavation_scope)}
                   if self.layered_excavation_scope else {})}


def _cancel(cancelled):
    if cancelled and cancelled():
        raise NetworkSectionCalculationError("断面算量已取消", code="cancelled")


def trenchless_only_result(excluded, *, test_only=False, overlap_policy="independent_sections", cancelled=None):
    _cancel(cancelled)
    bore = trenchless_excavation_quantities(excluded)
    if bore.get("trenchless_excavation_volume") is None:
        details = bore.get("trenchless_excavation_rows") or excluded
        raise NetworkSectionCalculationError("没有可计量的明挖断面或非开挖洞段，须核对管径及起止桩号",
            code="no_measurable_earthwork_assets",diagnostics=details)
    return NetworkSectionCalculationResult(_with_fill(dict.fromkeys((*ROLES, *MATERIAL_ROLES), 0.)),
        [], [], [], [], {"converged":False,"convergence_checked":False,"trenchless_only":True,
            "integration_method":TRENCHLESS_EXCAVATION_RULE,"overlap_policy":overlap_policy},
        test_only=test_only,method=TRENCHLESS_EXCAVATION_RULE,
        input_metadata={"overlap_policy":overlap_policy},excluded_assets=excluded,trenchless_excavation=bore)


class _SectionProgress:
    """Report real section work at most once a second, plus phase boundaries."""
    def __init__(self, callback, stage, label):
        self.callback = callback
        self.stage = stage
        self.label = label
        self.last_update = None

    def report(self, asset, station, done, total, fraction, *, force=False):
        if not self.callback:
            return
        now = time.monotonic()
        if not force and self.last_update is not None and now-self.last_update < 1.:
            return
        self.last_update = now
        name = asset.get("name") or asset["asset_id"]
        display_station = station-float(asset.get("station_offset",0.))
        self.callback(self.stage, fraction,
            f"{self.label}；{name} K{display_station:.3f}；已完成 {done}/{total} 张断面")


def _convergence_progress_detail(failed, assets):
    """Format failed checks, including dynamically named material roles."""
    if not failed:
        return ""
    worst=max(failed,key=lambda c:c["difference_m3"]/max(c["allowed_m3"],1e-300))
    interval=f" K{worst['station_start']:.3f}～{worst['station_end']:.3f}" if "station_start" in worst else ""
    names={"excavation":"挖方","backfill":"回填","embankment":"填筑","concrete":"混凝土","bedding":"垫层",
           "overburden":"覆盖层挖方","bedrock":"基岩挖方","unclassified_excavation":"未分层挖方"}
    role=str(worst.get("role") or "")
    label=names.get(role)
    if label is None and role.startswith("component__"):
        identifier=role[len("component__"):]
        labels=sorted({str(spec.get("name") or identifier) for asset in assets
            if worst["asset_id"]=="GLOBAL" or asset.get("asset_id")==worst["asset_id"]
            for spec in asset.get("section",{}).get("component_specs",[])
            if spec.get("component_id")==identifier})
        label="/".join(labels) if labels else "材料构件 "+identifier
    if label is None:
        label=role or "未命名分项"
    return f"；{len(failed)}项未达标，{worst['asset_id']}{interval}{label}差{worst['difference_m3']:.6g}>{worst['allowed_m3']:.6g}m³"


def _poly(rings):
    return unary_union([Polygon(r) for r in rings]) if rings else Polygon()


def _profile(asset, network):
    def unavailable(message):
        return NetworkSectionCalculationError(message, code="missing_profile", diagnostics=[{
            "asset_id": asset.get("asset_id"), "original_asset_id": asset.get("original_asset_id"),
            "route_id": asset.get("route_id"), "message": message,
        }])

    if asset.get("design_profile"):
        from .design_profiles import DesignProfileError, evaluate_profile, normalize_design_profile, profile_break_stations
        try:
            asset["design_profile"] = normalize_design_profile(asset["design_profile"])
        except DesignProfileError as error:
            raise unavailable(str(error)) from error
        knots = profile_break_stations(asset)
        if len(knots)<2 or knots[0]>asset["station_start"]+1e-8 or knots[-1]<asset["station_end"]-1e-8:
            raise unavailable("真实设计纵断面未覆盖结构，待补区段设计高程")
        return [(s,evaluate_profile(asset,s)[0]) for s in knots]
    points = asset.get("profile_points") or asset.get("alignment", {}).get("profile_points") or network.get("profile_points")
    if not points or len(points) < 2:
        raise unavailable("缺少完整设计纵断面")
    try:
        values = [(finite_number(p.get("station"), "纵断面桩号"),
                   finite_number(p.get("elevation"), "纵断面高程")) for p in points]
    except ConstructionInputError as error:
        raise unavailable(str(error)) from error
    if any(b[0] <= a[0] for a, b in zip(values, values[1:])):
        raise unavailable("纵断面必须高程有限且桩号递增")
    if values[0][0] > asset["station_start"] or values[-1][0] < asset["station_end"]:
        raise unavailable("纵断面未覆盖结构，待补区段设计高程")
    return values


def _profile_at(values, station, side="right", *, positions=None):
    positions = [p[0] for p in values] if positions is None else positions
    i = bisect_right(positions, station)-1
    if side == "left" and i > 0 and positions[i] == station:
        i -= 1
    i = min(max(i, 0), len(values)-2)
    a, b = values[i:i+2]
    slope = (b[1]-a[1])/(b[0]-a[0])
    return a[1]+slope*(station-a[0]), slope


def polygon_metrics(region, curvature=0.):
    """返回面积、一阶矩及 ∫|1+κu|dA，横偏距正向为线路右侧。"""
    if region.is_empty:
        return {"area": 0., "first_moment_u": 0., "weighted_area": 0.}
    area = float(region.area)
    moment = area*float(region.centroid.x)
    if curvature == 0:
        weighted = area
    else:
        singular = -1/curvature
        l, b, r, t = region.bounds
        weighted = 0.
        for a, z in ((l, min(r, singular)), (max(l, singular), r)):
            if z <= a:
                continue
            part = region.intersection(box(a, b-1, z, t+1))
            if not part.is_empty:
                weighted += abs(part.area+curvature*part.area*part.centroid.x)
    return {"area": area, "first_moment_u": moment, "weighted_area": float(weighted)}


class _Sections:
    def __init__(self, tin, alignment, assets, profiles, arc_segments):
        self.interp = TINInterpolator(tin)
        # This evaluator owns a read-only selected TIN for its whole lifetime.
        self._terrain_bbox = tin.get_bbox()
        self.alignment, self.assets, self.profiles = alignment, assets, profiles
        self.profile_positions=[tuple(s for s,_ in p) for p in profiles]
        self.profile_knots={a["asset_id"]:positions for a,positions in zip(assets,self.profile_positions)}
        self.arc_segments = arc_segments
        self.zmin = float(np.min(tin.points[:, 2]))
        self.zmax = float(np.max(tin.points[:, 2]))
        all_z = [z for profile in profiles for _, z in profile]
        self.relative_base = min(self.zmin-max(all_z)-2, -20.)
        self.relative_top = max(self.zmax-min(all_z)+2, 20.)
        self.cache, self.template_cache = OrderedDict(), {}
        self.cache_limit=4096
        self.structure_templates = {}
        self.arc_terrain_events = {}
        self.catalog = None
        self.material_joint_policy = "strict"
        self.overlap_policy = "spatial_union"
        self.material_roles = MATERIAL_ROLES + extra_material_roles(assets)
        self.joint_approximations = {}

    def profile_at(self, ai, station, side="right"):
        if self.assets[ai].get("design_profile"):
            from .design_profiles import evaluate_profile
            return evaluate_profile(self.assets[ai],station,side)
        return _profile_at(self.profiles[ai],station,side,positions=self.profile_positions[ai])

    def shape(self, ai, station, side="right"):
        asset = self.assets[ai]
        z, slope = self.profile_at(ai, station, side)
        base, top = self.relative_base, self.relative_top
        key = (ai, slope)
        if key not in self.template_cache:
            if asset["section_type"] == "arch_tunnel":
                rings, _ = _section_outer("arch_culvert", asset["section"], self.arc_segments)
                permanent = _poly(rings)
                clearance = float(asset.get("construction", {}).get("excavation_clearance", -1))
                if not math.isfinite(clearance) or clearance < 0:
                    raise NetworkSectionCalculationError("隧洞缺少明确暗挖预留厚度")
                roles = {k: Polygon() for k in RAW_ROLES}
                roles.update(permanent=permanent, excavation=permanent.buffer(clearance, quad_segs=self.arc_segments//4))
            else:
                prepared = build_construction_section(asset, station=station, origin=[0, 0, 0], tangent=[1, 0, 0],
                    settings={"base_z": base, "clip_top_z": top, "arc_segments": self.arc_segments}, vertical_slope=slope)
                roles = {k: _poly(prepared[k]) for k in RAW_ROLES if k != "removal"}
                roles["removal"] = Polygon()
                if prepared["target_mode"] == "finished_profile":
                    roles["removal"] = _poly(prepared["domain"]).difference(roles["target"])
                if prepared["target_mode"] == "union_terrain":
                    l, _, r, crest = roles["permanent"].bounds
                    c = asset["construction"]
                    l -= float(c["bank_top_width_left"]); r += float(c["bank_top_width_right"])
                    roles["target"] = Polygon([(l-float(c["bank_slope_left"])*(crest-base), base),
                        (r+float(c["bank_slope_right"])*(crest-base), base), (r, crest), (l, crest)])
            self.template_cache[key] = roles
        return {k: affinity.translate(v, yoff=z) for k, v in self.template_cache[key].items()}, z, slope

    def frame(self, part, station):
        if self.catalog is not None:
            return self.catalog.center_tangent_curvature(part["part_id"], station)
        e = part["element"]
        f = (station-e["station_start"])/e["length"]
        if e["kind"] == "line":
            xy = np.array(e["start_xy"])+(np.array(e["end_xy"])-e["start_xy"])*f
            angle, curvature = e["tangent_angle"], 0.
        else:
            theta = e["start_angle"]+e["sweep_angle"]*f
            xy = np.array(e["center_xy"])+e["radius"]*np.array([math.cos(theta), math.sin(theta)])
            angle = theta+math.copysign(math.pi/2, e["sweep_angle"])
            curvature = math.copysign(1/e["radius"], e["sweep_angle"])
        return xy, np.array([math.cos(angle), math.sin(angle)]), curvature

    def exact(self, part, station, side="right"):
        ai = part["asset_index"]
        key = (part["part_id"], station, side)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        asset = self.assets[ai]
        try:
            if asset.get("workbench_geometry"):
                value = self.workbench_exact(part,station,side)
                self._cache_exact(key,value)
                return value
            roles, z, slope = self.shape(ai, station, side)
            center, tangent, curvature = self.frame(part, station)
            world = np.asarray(center)+(self.catalog.origin_xy if self.catalog is not None else 0)
            normal = np.array([tangent[1], -tangent[0]])
            bounds = [g.bounds for g in roles.values() if not g.is_empty]
            safe_l = min(0., *(b[0] for b in bounds))-1
            safe_r = max(0., *(b[2] for b in bounds))+1
            data = self.interp.section_line(world, normal, safe_l, safe_r)
            p = roles["permanent"]
            l, floor, r, crest = p.bounds
            c = effective_construction(asset)
            underground = asset["section_type"] == "arch_tunnel"
            if underground:
                l, floor, r, _ = roles["excavation"].bounds
                work = [l, r]
            else:
                work = [l-float(c.get("bedding_extension", 0))-float(c.get("working_space_left", 0)),
                        r+float(c.get("bedding_extension", 0))+float(c.get("working_space_right", 0))]
                floor -= float(c.get("bedding_thickness", 0))
            required = [0., *work]
            if c.get("target_mode") == "union_terrain":
                required += [l-float(c["bank_top_width_left"]), r+float(c["bank_top_width_right"])]
            if c.get("target_mode") == "finished_profile":
                required += [float(pt[0]) for pt in c["target_profile"]]
            components, current = [], []
            for offset, height in data:
                if math.isfinite(height):
                    current.append((float(offset), float(height)))
                elif current:
                    components.append(current); current = []
            if current:
                components.append(current)
            ground = next((p for p in components if len(p)>1 and p[0][0] <= min(required)+1e-8 and p[-1][0] >= max(required)-1e-8), None)
            if ground is None:
                raise AssetDataPending("结构/工作面跨越缺测地形，禁止外推",code="section_terrain_unavailable")
            daylight = work[:]
            if underground:
                for x, zz in roles["excavation"].exterior.coords:
                    if zz > _ground_at(ground, x)+1e-6:
                        raise AssetDataPending("暗挖隧洞出露原地面，需明确洞口设计",code="tunnel_exposed")
            elif c.get("installation_mode", "buried") == "buried":
                for i, (name, direction) in enumerate((("left", -1), ("right", 1))):
                    if _ground_at(ground, work[i]) >= floor-1e-8:
                        daylight[i] = CrossSectionCalculator._trace_slope(work[i], floor, ground, _grades(c, name), direction)[-1][0]
            target_bounds = [l, r]
            if c.get("target_mode") == "union_terrain":
                for i, (name, direction, edge) in enumerate((("left", -1, l), ("right", 1, r))):
                    crown = edge+direction*float(c["bank_top_width_"+name])
                    target_bounds[i] = crown
                    if _ground_at(ground, crown) < crest-1e-8:
                        hit = CrossSectionCalculator._ray_ground_hit((crown, crest), (direction*float(c["bank_slope_"+name]), -1), ground)
                        if hit is None:
                            raise ConstructionInputError("填坡在有效地形内未首次接地")
                        target_bounds[i] = hit[1][0]
            lower, upper = min(self.zmin, floor)-2, max(self.zmax, crest)+2
            roles["excavation"] = _polygonal(roles["excavation"].intersection(box(*[daylight[0], lower, daylight[1], upper])))
            if not roles["target"].is_empty and c.get("target_mode") != "finished_profile":
                roles["target"] = _polygonal(roles["target"].intersection(box(target_bounds[0], lower, target_bounds[1], upper)))
            roles["open_air"] = _polygonal(roles["open_air"].intersection(roles["excavation"]))
            support = [g.bounds for g in roles.values() if not g.is_empty]
            left, right = min(b[0] for b in support), max(b[2] for b in support)
            cropped = [(left, _ground_at(ground, left))]+[(x,h) for x,h in ground if left<x<right]+[(right,_ground_at(ground,right))]
            soil = Polygon([(left, lower), (right, lower)]+list(reversed(cropped)))
            target = soil if c.get("target_mode") == "restore_terrain" or underground else unary_union([soil, roles["target"]])
            if c.get("target_mode") == "finished_profile":
                target = roles["target"]
            target = _polygonal(target.difference(unary_union([roles["open_air"], roles["removal"]])))
            state = compute_construction_state(soil, roles["excavation"], target, roles["permanent"], roles["measured"], area_tolerance=1e-6)
            value = dict(part=part, station=station, side=side, center=world, tangent=tangent, curvature=curvature,
                         design_elevation=z, slope=slope, ground=cropped, soil=soil, roles=roles,
                         daylight=daylight, target_bounds=target_bounds, domain=box(left, lower, right, upper),
                         gross={"excavation":state.excavation, "backfill":state.backfill, "embankment":state.embankment})
            self._cache_exact(key,value)
            return value
        except (ValueError, ConstructionInputError) as exc:
            raise NetworkSectionCalculationError(f"{asset.get('name', asset['asset_id'])} K{station:.3f}: {exc}",
                code=getattr(exc,"code","missing_terrain_or_invalid_section"), diagnostics=getattr(exc,"diagnostics",None) or [{"asset_id":asset["asset_id"],"station":station,"side":side,"message":str(exc)}]) from exc

    def _cache_exact(self,key,value):
        self.cache[key]=value
        while len(self.cache)>self.cache_limit:self.cache.popitem(last=False)

    def workbench_exact(self, part, station, side="right", *, tunnel_probe=False):
        from .section_geometry import section_structure, add_foundation_materials, construction_on_ground, translate_structure
        from ..adapters.independent_assets import _ground_component
        ai=part["asset_index"]; asset=self.assets[ai]
        if asset["section_type"]=="rectangular_pit":
            from .pit_sections import pit_slice
            center,tangent,curvature=self.frame(part,station)
            world=np.asarray(center)+(self.catalog.origin_xy if self.catalog is not None else 0)
            value=pit_slice(asset,station,world,tangent,self.interp,terrain_min=self.zmin,terrain_max=self.zmax,side=side)
            for role in self.material_roles:
                value["gross"].setdefault(role,Polygon())
                value["roles"].setdefault(role,Polygon())
            value.update(part=part,station=station,side=side,center=world,tangent=tangent,curvature=curvature)
            return value
        z,slope=self.profile_at(ai,station,side)
        center,tangent,curvature=self.frame(part,station)
        if not math.isfinite(slope) or abs(slope)>1e4:
            raise AssetDataPending("近竖直管轴需采用专用施工断面", code="unsupported_section_geometry")
        c=effective_construction(asset)
        unburied=c.get("installation_mode","buried") in {"exposed","elevated","open","above_ground"}
        profile=asset.get("design_profile")
        element_key=0
        if profile:
            element_key=max(0,min(len(profile["elements"])-1,bisect_right(profile.starts,station)-1))
            if side=="left" and element_key>0 and abs(profile.starts[element_key]-station)<1e-8:element_key-=1
        template_key=(ai,slope,element_key,curvature)
        if not asset["section_type"].startswith("circular") and asset["section_type"] not in {"arch_tunnel","flat_bottom_tunnel","horseshoe_tunnel"}:
            # The channel/box stencil depends on section parameters and
            # elevation only; retain the true profile slope on the section
            # record without regenerating this unchanged wall geometry.
            template_key=(ai,0.,0)
        dynamic=asset["section_type"] in {"aqueduct_u","aqueduct_rectangular"} or bool(asset.get("section",{}).get("discrete_components"))
        if not dynamic and template_key in self.structure_templates:
            structure=translate_structure(self.structure_templates[template_key],z)
        else:
            structure=section_structure(asset,elevation=z,slope=slope,arc_segments=self.arc_segments,station=station,side=side,plan_curvature=curvature)
            if structure.get("dedicated_construction"):
                pass
            elif unburied:
                structure.update(measured=Polygon(),occupancy=structure["outer"])
                structure["materials"]["bedding"]=Polygon()
            else:
                structure=add_foundation_materials(structure,c,arc_segments=self.arc_segments)
            if not dynamic:
                if len(self.structure_templates)>=128:self.structure_templates.pop(next(iter(self.structure_templates)))
                self.structure_templates[template_key]=translate_structure(structure,-z)
        world=np.asarray(center)+(self.catalog.origin_xy if self.catalog is not None else 0)
        normal=np.array([tangent[1],-tangent[0]])
        terrain_case=None
        if asset.get("section_scheme_terrain_variants") or asset.get("section_scheme_selectors"):
            from .section_terrain_variants import classify_terrain_case, terrain_variant_asset, selector_metrics
            probe_left,_,probe_right,_=structure["outer"].bounds
            probe=self.interp.section_line(world,normal,min(0.,probe_left)-.05,max(0.,probe_right)+.05)
            terrain_case=classify_terrain_case(structure["outer"],probe)
            preliminary=terrain_variant_asset(asset,terrain_case,validate=False,apply_selectors=False)
            variant=(asset.get("section_scheme_terrain_variants") or {}).get(terrain_case["code"],{})
            selectors=[*(asset.get("section_scheme_selectors") or []),*variant.get("selectors",[])]
            metric_ground=(_ground_component(self.interp,world,normal,(probe_left,probe_right))
                if any(row.get("metric")=="max_outer_drop_m" for row in selectors) else probe)
            terrain_case=selector_metrics(preliminary,structure,terrain_case,metric_ground)
            asset=terrain_variant_asset(asset,terrain_case)
            terrain_case=asset["terrain_case"]
            c=effective_construction(asset)
            unburied=c.get("installation_mode","buried") in {"exposed","elevated","open","above_ground"}
            case_key=(*template_key,terrain_case["code"],asset.get("section_scheme_selector_key",""))
            if not dynamic and case_key in self.structure_templates:
                structure=translate_structure(self.structure_templates[case_key],z)
            else:
                structure=section_structure(asset,elevation=z,slope=slope,arc_segments=self.arc_segments,
                    station=station,side=side,plan_curvature=curvature)
                if not structure.get("dedicated_construction"):
                    if unburied:
                        structure.update(measured=Polygon(),occupancy=structure["outer"])
                        structure["materials"]["bedding"]=Polygon()
                    else:
                        structure=add_foundation_materials(structure,c,arc_segments=self.arc_segments)
                if not dynamic:
                    if len(self.structure_templates)>=128:self.structure_templates.pop(next(iter(self.structure_templates)))
                    self.structure_templates[case_key]=translate_structure(structure,-z)
        left,floor,right,crest=structure["occupancy"].bounds
        seat=c.get("pipe_seat") or c.get("pipe_support") or {}
        full_trench=seat.get("enabled",True) and seat.get("bottom_width_mode")=="trench_bottom"
        if c.get("working_space_reference")=="pipe_outer" or full_trench:
            # The full-width base already contains the work spaces; match the
            # same outside-wall reference used by construction_on_ground.
            if structure.get("pipes"):
                left,right=structure["outer"].bounds[0],structure["outer"].bounds[2]
        elif c.get("working_space_reference") == "pipe_foundation" and structure.get("pipe_foundation_span"):
            left, right = structure["pipe_foundation_span"]
        required=(left-float(c.get("working_space_left",0))-float(c.get("bank_top_width_left",0)),
                  right+float(c.get("working_space_right",0))+float(c.get("bank_top_width_right",0)))
        replacement_floor = structure.get("replacement_excavation_floor")
        if replacement_floor and c.get("excavation_base_mode", "flat") == "flat":
            required = (min(replacement_floor[0][0], structure["outer"].bounds[0]-float(c.get("bank_top_width_left", 0))),
                        max(replacement_floor[-1][0], structure["outer"].bounds[2]+float(c.get("bank_top_width_right", 0))))
        if structure.get("tunnel_excavation_outline") is not None:
            lo, _, hi, _ = structure["tunnel_excavation_outline"].bounds
            required = min(required[0], lo), max(required[1], hi)
        from .section_geometry import construction_floor_steps
        steps=construction_floor_steps(c,structure)
        if steps:
            required=(min(required[0],steps[0][0]),max(required[1],steps[-1][0]))
        bottom=min(self.zmin,floor)-2; top=max(self.zmax,crest+float(c.get("final_cover_depth",0)))+2
        if steps:bottom=min(bottom,min(z for _,z in steps)-2.)
        # Query the physical work area first and expand only until both slopes
        # have daylighted. A whole-bbox line wastes intersections and can bring
        # unrelated distant terrain defects into a local construction section.
        bbox=self._terrain_bbox
        corners=np.asarray([(bbox[0],bbox[1]),(bbox[0],bbox[3]),(bbox[2],bbox[1]),(bbox[2],bbox[3])])-world
        projections=corners@normal;limit_l,limit_r=float(projections.min()),float(projections.max())
        margin=max(.5,(required[1]-required[0])/4)
        for search in range(24):
            ql=max(limit_l,required[0]-margin);qr=min(limit_r,required[1]+margin)
            if ql >= qr:
                raise AssetDataPending("实际结构/工作面位于有效地形外", code="section_terrain_unavailable")
            data=self.interp.section_line(world,normal,ql,qr)
            components=[];current=[]
            for u,height in data:
                if math.isfinite(height):current.append((float(u),float(height)))
                elif current:components.append(current);current=[]
            if current:components.append(current)
            ground=next((g for g in components if len(g)>1 and g[0][0]<=required[0]+1e-8 and g[-1][0]>=required[1]-1e-8),None)
            if ground is None:raise AssetDataPending("实际结构/工作面跨越地形缺测，禁止外推或跨孔洞",
                                                    code="section_terrain_unavailable")
            if tunnel_probe:
                from .dedicated_structure_geometry import tunnel_outline_exposed
                return tunnel_outline_exposed(structure["tunnel_excavation_outline"], ground)
            try:
                if terrain_case:
                    from .section_terrain_variants import clip_fill_contact_components
                    structure=clip_fill_contact_components(structure,ground)
                prepared=construction_on_ground(asset,structure,ground,bottom=bottom,top=top)
                structure=prepared.get("structure",structure)
                break
            except ValueError as error:
                expandable=any(word in str(error) for word in ("未接地","未与地面相交","超出有效地形","马道超出","有效地形范围"))
                if not expandable or (ql==limit_l and qr==limit_r):raise
                margin*=2
        else:raise ConstructionInputError("施工坡脚自动搜索未完成，未发布数量")
        if structure.get("pipes"):
            for pi,pipe in enumerate(structure["pipes"]):
                top_offset=pipe.get("outer_top_offset",pipe["offset"])
                g=_ground_at(ground,top_offset)
                pipe.update(ground_elevation=g,ground_sample_offset=top_offset,actual_cover=g-pipe["outer_top"])
                required_cover=float(c.get("cover_depth",0))
                local_station=station-float(asset.get("station_offset",0))
                for segment in c.get("cover_segments") or []:
                    if segment["station_start"]<=local_station<=segment["station_end"]:
                        required_cover=float(segment["cover_depth"]);break
                if c.get("burial_mode")=="cover_depth" and pipe["actual_cover"]<required_cover-1e-6:
                    raise ConstructionInputError(f"第{pi+1}根管实际覆土不足设定埋深；请调整并重新确认轴线")
        if min(1+curvature*structure["outer"].bounds[i] for i in (0,2))<=0:
            raise AssetDataPending("永久结构跨越曲率中心，待核实际转弯半径与结构宽度", code="unsupported_section_geometry")
        roles=prepared["roles"]
        state=compute_construction_state(prepared["soil"],roles["excavation"],prepared["target"],
                                         roles["permanent"],roles["measured"],area_tolerance=1e-6)
        roles.update(structure["materials"])
        for cid, component in structure.get("component_regions", {}).items():
            roles[component_role(cid)] = component["geometry"]
        for component in nonconcrete_pipe_components(asset, structure):
            roles[component_role(component["component_id"])] = component["geometry"]
        gross={"excavation":state.excavation,"backfill":state.backfill,"embankment":state.embankment,
               **{r:roles.get(r,Polygon()) for r in self.material_roles}}
        backfill_partition = {}
        if structure.get("pipes") and not unburied:
            height = (c.get("backfill_partition") or {}).get("above_crown_height_m")
            height = DEFAULT_MANUAL_BACKFILL_HEIGHT_M if height is None else finite_number(height, "人工夯实至管顶以上")
            if height < 0.:
                raise ConstructionInputError("人工夯实至管顶以上的高度须大于等于 0 m")
            crown = max(pipe["outer_top"] for pipe in structure["pipes"])
            backfill_partition["backfill_split_elevation"] = crown + height
        return dict(part=part,station=station,side=side,center=world,tangent=tangent,curvature=curvature,
                    design_elevation=z,slope=slope,ground=prepared["ground"],soil=prepared["soil"],roles=roles,
                    daylight=prepared["daylight"],target_bounds=prepared["target_bounds"],domain=prepared["domain"],
                    gross=gross,structure=structure,floor_path=prepared["floor_path"],
                    finished_profile=prepared["finished_profile"], **backfill_partition,
                    **({"effective_asset":asset,"terrain_case":terrain_case} if terrain_case else {}))


def _vertical_intervals(region, offset):
    if region.is_empty:
        return []
    left,bottom,right,top=region.bounds
    if offset < left or offset > right:
        return []
    q = region.intersection(LineString([(offset, bottom-1), (offset, top+1)]))
    parts = list(q.geoms) if hasattr(q, "geoms") else [q]
    intervals=[]
    for p in parts:
        if p.is_empty or p.geom_type != "LineString":
            continue
        _,low,_,high=p.bounds
        if high > low:
            intervals.append((float(low),float(high)))
    return intervals


def _interpolated_roles(evaluator, part, station, sampled):
    """模板/纵断面按解析桩号求值；仅首次接地偏距在相邻真剖面间插值。"""
    if (evaluator.assets[part["asset_index"]].get("workbench_geometry")
            or getattr(evaluator,"sampling_mode","adaptive")=="fixed"):
        return evaluator.exact(part,station)["roles"]
    values = sampled[part["part_id"]]
    stations = [v["station"] for v in values]
    j = min(max(bisect_right(stations, station)-1, 0), len(values)-2)
    a, b = values[j:j+2]
    ratio = (station-a["station"])/(b["station"]-a["station"]) if b["station"] != a["station"] else 0.
    roles, _, _ = evaluator.shape(part["asset_index"], station)
    low, high = evaluator.zmin-2, evaluator.zmax+2
    for key, bounds in (("excavation", "daylight"), ("target", "target_bounds")):
        if roles[key].is_empty:
            continue
        left, right = [a[bounds][i]+ratio*(b[bounds][i]-a[bounds][i]) for i in (0,1)]
        roles[key] = roles[key].intersection(box(left, min(low,roles[key].bounds[1]), right, max(high,roles[key].bounds[3])))
    roles["open_air"] = roles["open_air"].intersection(roles["excavation"])
    return roles


def _same_route_asset_joint(evaluator, part, station, foreign, other_station, value, other_roles):
    """Permit the existing bedding trim only at a real, local end connection."""
    own=evaluator.assets[part["asset_index"]]
    other=evaluator.assets[foreign["asset_index"]]
    route=own.get("route_id")
    if not route or route!=other.get("route_id"):return None
    if abs(own["station_end"]-other["station_start"])<1e-7:
        own_boundary,other_boundary=own["station_end"],other["station_start"]
        own_side,other_side="left","right"
    elif abs(other["station_end"]-own["station_start"])<1e-7:
        own_boundary,other_boundary=own["station_start"],other["station_end"]
        own_side,other_side="right","left"
    else:return None
    joint=(own_boundary+other_boundary)/2
    outer=value["roles"]["permanent"]
    other_outer=other_roles.get("permanent",Polygon())
    if outer.is_empty or other_outer.is_empty:return None
    bounds=outer.bounds;other_bounds=other_outer.bounds
    reach=max(1e-6,bounds[2]-bounds[0],bounds[3]-bounds[1],
              other_bounds[2]-other_bounds[0],other_bounds[3]-other_bounds[1])
    if abs(station-joint)>reach or abs(other_station-joint)>reach:return None
    catalog=evaluator.catalog
    own_id=catalog.part_at(own["asset_id"],own_boundary,own_side)
    other_id=catalog.part_at(other["asset_id"],other_boundary,other_side)
    a,_,_=catalog.center_tangent_curvature(own_id,own_boundary)
    b,_,_=catalog.center_tangent_curvature(other_id,other_boundary)
    if float(np.linalg.norm(a-b))>1e-5:return None
    return {"joint_scope":"same_route_adjacent_assets","route_id":route,
            "other_asset_id":other["asset_id"],"local_joint_reach_m":reach}


def _net_section(evaluator, value, sampled, lateral_step):
    """按指定口径独立计量，或按真实同 XY 的竖直区间扣重。"""
    if getattr(evaluator,"overlap_policy","spatial_union") == "independent_sections":
        # The local construction state has already excluded this section's
        # own permanent envelope and materials from its fill. Independent
        # takeoff keeps that complete state without consulting foreign
        # sections or assigning their earth/material quantities to an owner.
        return value["gross"], {"overlap_policy":"independent_sections",
            "overlap_deduction_applied":False,"foreign_sections_queried":False,
            "candidate_parts":0,"overlap_bands":0,"joint_material_approximations":[]}
    catalog = evaluator.catalog
    part, s = value["part"], value["station"]
    ai = part["asset_index"]
    gross = value["gross"]
    l, _, r, _ = value["domain"].bounds
    tangent = value["tangent"]
    normal = np.array([tangent[1], -tangent[0]])
    center = value["center"]-catalog.origin_xy
    candidates = catalog.query(LineString([center+l*normal, center+r*normal]))
    folded=bool(value["curvature"] and l < -1/value["curvature"] < r)
    if (candidates == [part["part_id"]] and not folded) or not candidates:
        return gross, {"candidate_parts":len(candidates), "overlap_bands":0}
    # Candidate bboxes deliberately over-cover curves. Analytic station/offset
    # boundary events partition the entire normal into constant-membership
    # intervals, so one interior preimage query proves whether each foreign
    # part can occur anywhere with positive measure. This is an exact spatial
    # rejection before material/terrain queries, not coarser lateral sampling.
    plan_events=catalog.normal_events(center,normal,l,r,candidates)
    active=set();active_images={}
    for left,right in zip(plan_events,plan_events[1:]):
        if right<=left:continue
        for image in catalog.preimages(center+(left+(right-left)/2)*normal,candidates):
            if image.get("singular"):continue
            if image["part_id"]==part["part_id"] and abs(image["station"]-s)<1e-6:continue
            foreign=catalog.parts[image["part_id"]]
            if foreign["asset_index"]==ai and abs(image["station"]-s)<1e-6:continue
            active.add(image["part_id"])
            active_images.setdefault(image["part_id"],image)
    if not active:return gross,{"candidate_parts":len(candidates),"overlap_bands":0,"analytic_foreign_parts":0}
    candidates=sorted(active|{part["part_id"]})
    events = [l, r]
    for geometry in gross.values():
        for polygon in ([geometry] if isinstance(geometry, Polygon) else getattr(geometry, "geoms", [])):
            if isinstance(polygon, Polygon):
                events.extend(float(x) for x, _ in polygon.exterior.coords)
    events += catalog.normal_events(center, normal, l, r, candidates,evaluator.profile_knots)
    events = sorted(set(min(r, max(l, float(u))) for u in events if math.isfinite(u)))
    offsets = []
    for a,b in zip(events,events[1:]):
        n = max(1, math.ceil((b-a)/lateral_step))
        offsets.extend(a+(b-a)*j/n for j in range(n))
    offsets.append(r)
    early_e, early_t, voids = [], [], []
    early_materials = {r:[] for r in evaluator.material_roles}
    bands = 0
    joint_approximations = []
    # A generated footing pit and its parent pier share actual coordinates.
    # For parallel straight routes transform the complete foreign polygons;
    # midpoint strips can erase a narrow pier's true width (e.g. 1.0 -> 1.2m).
    exact_related=set()
    own=evaluator.assets[ai]
    if abs(value["curvature"])<1e-12:
        for pid in active:
            foreign=catalog.parts[pid];other=evaluator.assets[foreign["asset_index"]]
            related=(own.get("generated_aqueduct_foundation") and own.get("parent_asset_id")==other.get("asset_id") or
                     other.get("generated_aqueduct_foundation") and other.get("parent_asset_id")==own.get("asset_id"))
            if not related:continue
            other_s=active_images[pid]["station"]
            fc,ft,fk=catalog.center_tangent_curvature(pid,other_s)
            if abs(fk)>1e-12 or abs(abs(float(np.dot(ft,tangent)))-1.)>1e-10:continue
            fn=np.array([ft[1],-ft[0]])
            sign=float(np.dot(fn,normal));shift=float(np.dot(fc-center,normal))
            roles={key:affinity.translate(affinity.scale(g,xfact=sign,yfact=1.,origin=(0.,0.)),xoff=shift)
                   for key,g in _interpolated_roles(evaluator,foreign,other_s,sampled).items()}
            earlier=other_s<s-1e-7 or abs(other_s-s)<=1e-7 and foreign["asset_index"]<ai
            for role in evaluator.material_roles:
                g=roles.get(role,Polygon())
                for other_role in evaluator.material_roles:
                    overlap=g.intersection(gross.get(other_role,Polygon())).area
                    if overlap<=1e-7:continue
                    if role!=other_role:
                        raise NetworkSectionCalculationError("基础与相邻构件材料实体重叠，须核对实际构造边界",code="material_conflict")
                    first=material_identity(own,role);second=material_identity(other,role)
                    if first[1] and second[1] and first!=second:
                        raise NetworkSectionCalculationError("相交结构的材料或等级不同，须明确实际构造归属",code="material_grade_conflict")
                if earlier:early_materials[role].append(g)
            voids.extend(roles[key] for key in ("permanent","measured","open_air","removal"))
            if earlier:
                early_e.append(roles["excavation"]);early_t.append(roles["target"])
            exact_related.add(pid)
    for a,b in zip(offsets,offsets[1:]):
        if b <= a:
            continue
        u = a+(b-a)/2
        for image in catalog.preimages(center+u*normal, candidates):
            if image.get("singular"):
                continue
            pid, other_s = image["part_id"], image["station"]
            if pid in exact_related:continue
            if pid == part["part_id"] and abs(other_s-s) < 1e-6:
                continue
            foreign = catalog.parts[pid]
            if foreign["primitive_id"]==part["primitive_id"]:
                # Angular preimages move with the same station derivative.
                # At a closed/full-turn boundary retain the actual one-sided
                # limit, rather than treating the coincident zero/end ray as
                # a finite extra ownership band.
                if (value["side"]=="left" and abs(other_s-foreign["station_start"])<1e-8 or
                    value["side"]=="right" and abs(other_s-foreign["station_end"])<1e-8):
                    continue
            if foreign["asset_index"]==ai and abs(other_s-s)<1e-6:
                # Adjacent analytic elements share this zero-length station;
                # preserve each element's one-sided material definition.
                continue
            roles = _interpolated_roles(evaluator, foreign, other_s, sampled)
            earlier = other_s < s-1e-7 or (abs(other_s-s)<=1e-7 and foreign["asset_index"]<ai)
            for role in evaluator.material_roles:
                if role not in gross:
                    continue
                for z0,z1 in _vertical_intervals(roles.get(role,Polygon()),image["offset"]):
                    band=box(a,z0,b,z1)
                    own_identity=material_identity(evaluator.assets[ai],role)
                    other_identity=material_identity(evaluator.assets[foreign["asset_index"]],role)
                    if (own_identity[1] and other_identity[1] and own_identity!=other_identity
                            and band.intersection(gross.get(role,Polygon())).area>1e-7):
                        raise NetworkSectionCalculationError("相交结构的材料或等级不同，须明确实际构造归属",code="material_grade_conflict")
                    if earlier:
                        early_materials[role].append(band)
                    for other_role in evaluator.material_roles:
                        overlap_area=band.intersection(gross.get(other_role,Polygon())).area if other_role!=role else 0.
                        if overlap_area>1e-7:
                            # At an unsmoothed bend, the two local normal
                            # sections can cross. Engineering section takeoff
                            # keeps the real two-sided geometry, allocates the
                            # concrete pipe first and trims only its bedding.
                            # Connected asset ends use the same engineering
                            # treatment only at their shared physical joint.
                            adjacent=(foreign["asset_index"]==ai and
                                (abs(foreign["station_start"]-part["station_end"])<1e-7 or
                                 abs(part["station_start"]-foreign["station_end"])<1e-7))
                            joint=None
                            if (evaluator.material_joint_policy=="section_union" and not adjacent
                                    and {other_role,role}=={"concrete","bedding"}):
                                joint=_same_route_asset_joint(evaluator,part,s,foreign,other_s,value,roles)
                            if (evaluator.material_joint_policy=="section_union"
                                    and {other_role,role}=={"concrete","bedding"}
                                    and (adjacent or joint)):
                                if other_role=="bedding" and role=="concrete":
                                    early_materials["bedding"].append(band)
                                joint_approximations.append({"asset_id":part["asset_id"],"station":s,
                                    "other_station":other_s,"part_id":part["part_id"],"other_part_id":pid,
                                    "overlap_area_m2":overlap_area,"policy":"concrete_priority_bedding_trim",
                                    **(joint or {"joint_scope":"same_asset_adjacent_elements"})})
                                continue
                            raise NetworkSectionCalculationError(
                                f"{part['asset_id']} K{s:.6f} 与 {foreign['asset_id']} K{other_s:.6f}：{other_role}/{role}占位冲突",code="material_conflict",
                                diagnostics=[{"asset_id":part['asset_id'],"station":s,"part_id":part['part_id'],
                                    "other_asset_id":foreign['asset_id'],"other_station":other_s,"other_part_id":pid,
                                    "material":other_role,"other_material":role,"offset_interval":[a,b],
                                    "overlap_area":band.intersection(gross.get(other_role,Polygon())).area}])
            for key, output in (("permanent",voids),("measured",voids),("open_air",voids),("removal",voids),
                                ("excavation",early_e),("target",early_t)):
                if key in {"excavation","target"} and not earlier:
                    continue
                for z0,z1 in _vertical_intervals(roles[key], image["offset"]):
                    output.append(box(a,z0,b,z1)); bands += 1
    e = unary_union(early_e) if early_e else Polygon()
    t = unary_union(early_t) if early_t else Polygon()
    v = unary_union(voids) if voids else Polygon()
    net = {"excavation":_polygonal(gross["excavation"].difference(e)),
           "backfill":_polygonal(gross["backfill"].difference(unary_union([e,v]))),
           "embankment":_polygonal(gross["embankment"].difference(unary_union([t,v])))}
    net.update({r:_polygonal(gross[r].difference(unary_union(early_materials[r])))
                for r in evaluator.material_roles if r in gross})
    if joint_approximations:
        key=(part["asset_id"],part["primitive_id"])
        record=evaluator.joint_approximations.setdefault(key,{"asset_id":part["asset_id"],
            "station_start":s,"station_end":s,"evaluated_overlap_count":0,"maximum_overlap_area_m2":0.})
        record["station_start"]=min(record["station_start"],s)
        record["station_end"]=max(record["station_end"],s)
        record["evaluated_overlap_count"]+=len(joint_approximations)
        others=record.setdefault("other_asset_ids",[])
        for item in joint_approximations:
            if item.get("other_asset_id") and item["other_asset_id"] not in others:others.append(item["other_asset_id"])
        if any(item.get("joint_scope")=="same_route_adjacent_assets" for item in joint_approximations):
            record["joint_scope"]="same_route_adjacent_assets"
            record["local_joint_reach_m"]=max(item.get("local_joint_reach_m",0.) for item in joint_approximations)
        record["maximum_overlap_area_m2"]=max(record["maximum_overlap_area_m2"],
            max(item["overlap_area_m2"] for item in joint_approximations))
    return net, {"candidate_parts":len(candidates),"overlap_bands":bands,
                 "joint_material_approximations":joint_approximations}


def _with_fill(values):
    values = {k+"_volume":float(v) for k,v in values.items()}
    values["total_fill_volume"] = values["backfill_volume"]+values["embankment_volume"]
    return values


def _split_backfill(value, regions):
    """Partition actual surrounding fill with the horizontal crown-height boundary."""
    elevation = value.get("backfill_split_elevation")
    if elevation is None:
        return regions
    manual, mechanical = regions["backfill"], Polygon()
    if not manual.is_empty:
        left, bottom, right, top = manual.bounds
        if elevation <= bottom:
            manual, mechanical = mechanical, manual
        elif elevation < top:
            lower = box(left, bottom, right, elevation)
            manual, mechanical = _polygonal(manual.intersection(lower)), _polygonal(manual.difference(lower))
    return {**regions, "manual_backfill": manual, "mechanical_backfill": mechanical}


def _layer_section(value, net, construction, *, include_unclassified=False):
    """Classify actual owned excavation after overlap allocation, using this ground."""
    from .layered_excavation import layer_config, interface_points, split_excavation_layers
    config=layer_config(construction)
    if config is None:
        layers={"overburden":Polygon(),"bedrock":Polygon()}
        gross=dict(layers)
    else:
        layers=split_excavation_layers(net["excavation"],value["ground"],construction)
        gross=split_excavation_layers(value["gross"]["excavation"],value["ground"],construction)
        value["geology"]={"mode":"surface_thickness",
            "thickness":float(construction["overburden_thickness"]),
            "interface_points":[list(p) for p in interface_points(value["ground"],construction)],
            "slopes":{role:{side:float(construction[role+"_slope_"+side]) for side in ("left","right")}
                      for role in ("overburden","bedrock")},
            "source":"user_assumed_vertical_thickness"}
        for regions,parent in ((layers,net["excavation"]),(gross,value["gross"]["excavation"])):
            error=abs(sum(g.area for g in regions.values())-parent.area)
            if error>max(1e-7,parent.area*1e-9):
                raise NetworkSectionCalculationError("覆盖层与基岩开挖分项面积未守恒",code="layer_area_mismatch")
    if include_unclassified:
        layers["unclassified_excavation"]=net["excavation"] if config is None else Polygon()
        gross["unclassified_excavation"]=value["gross"]["excavation"] if config is None else Polygon()
    return {**net,**layers},{**value["gross"],**gross}


def _section_structure_fields(value, net, *, geometry_mapper=mapping):
    from .section_geometry import structure_mapping
    if "structure" not in value:
        return {}
    structure=value["structure"]
    return {"structure_geometry":structure_mapping(structure,geometry_mapper=geometry_mapper),
            "material_areas":{**{r:float(net.get(r,g).area) for r,g in structure["materials"].items()},
                              **{r:float(g.area) for r,g in net.items() if r.startswith("component__")}},
            "net_material_geometry":{r:geometry_mapper(g) for r,g in net.items() if r not in ROLES+LAYER_ROLES+BACKFILL_ROLES},
            **({"backfill_split_elevation": value["backfill_split_elevation"]} if "backfill_split_elevation" in value else {}),
            **({"geology":deepcopy(value["geology"])} if value.get("geology") else {}),
            **({"terrain_case":deepcopy(value["terrain_case"]),
                "effective_asset":{key:deepcopy(value["effective_asset"][key]) for key in
                    ("asset_id","name","kind","section_type","section","construction","section_scheme_id",
                     "drawing_binding","parameter_sources","section_scheme_user_overrides")
                    if key in value["effective_asset"]}} if value.get("terrain_case") else {}),
            "quantity_components":deepcopy(value.get("quantity_components",[])),
            "vertical_slope":value["slope"],"construction_floor":value.get("floor_path",[]),
            "finished_profile":value.get("finished_profile",[])}


def _serialize_section(state):
    value,net,roles,diagnostic,gross,sid,pid=state
    cached={}
    def geometry(g):
        key=id(g)
        if key not in cached:cached[key]=mapping(g)
        return cached[key]
    return {"section_id":sid,"asset_id":value["part"]["asset_id"],"station":value["station"],
        "primitive_id":value["part"]["primitive_id"],"part_id":pid,"side":value["side"],
        "center_xy":value["center"].tolist(),"tangent":value["tangent"].tolist(),
        "curvature_right":-value["curvature"],"design_elevation":value["design_elevation"],
        "ground_points":[list(p) for p in value["ground"]],
        **({"sampling_reasons":list(value["sampling_reasons"]),"curve_added":value["curve_added"],
            "curve_station_added":value["curve_station_added"]}
            if "sampling_reasons" in value else {}),
        "roles":{r:{**metrics,"geometry":geometry(net[r])} for r,metrics in roles.items()},
        "domain":geometry(value["domain"]),"construction_geometry":{k:geometry(v) for k,v in value["roles"].items()},
        "overlap_diagnostics":diagnostic,"gross_weighted_areas":gross,
        **_section_structure_fields(value,net,geometry_mapper=geometry)}


def _terrain_knots(evaluator, part, *, offsets=None, below_elevation=None):
    """Keep real terrain events so two coarse rounds cannot miss a narrow ridge."""
    asset=evaluator.assets[part["asset_index"]]
    if not asset.get("workbench_geometry"):
        return []
    a,b=part["station_start"],part["station_end"]
    if offsets is None:
        widths=[]
        for s,side in ((a,"right"),(a+(b-a)/2,"right"),(b,"left")):
            value=evaluator.exact(part,s,side)
            widths.append((value["domain"].bounds[0],value["domain"].bounds[2]))
        lo=min(w[0] for w in widths);hi=max(w[1] for w in widths)
    else:
        lo, hi = min(offsets), max(offsets)
    element=evaluator.alignment.elements[part["primitive_id"]]
    index=evaluator.interp._get_section_index()
    bounds=_part_plan_bounds(element,a,b,lo,hi)
    pad=np.finfo(float).eps*max(1.,*map(abs,bounds))*8
    candidates=index._tree.query(box(bounds[0]-index._origin[0]-pad,bounds[1]-index._origin[1]-pad,
                                     bounds[2]-index._origin[0]+pad,bounds[3]-index._origin[1]+pad))
    if below_elevation is not None:
        elevations = index._points[index._triangles[candidates], 2]
        candidates = candidates[elevations.min(axis=1) <= below_elevation]
        if not len(candidates):
            # None of the original faces in this swept box can expose the tunnel.
            return None
    ids=np.unique(evaluator.interp._tin.triangles[candidates])
    points=np.asarray(evaluator.interp._tin.points)[ids]
    result=[]
    if element["kind"]=="line":
        tangent=np.array([math.cos(element["tangent_angle"]),math.sin(element["tangent_angle"])])
        normal=np.array([tangent[1],-tangent[0]])
        delta=points[:,:2]-np.asarray(element["start_xy"])
        ss=element["station_start"]+delta@tangent; uu=delta@normal
        mask=(ss>a+1e-8)&(ss<b-1e-8)&(uu>=lo-1e-8)&(uu<=hi+1e-8)
        result.extend(ss[mask].tolist())
        if offsets is None:
            center=np.asarray(element["start_xy"])+tangent*(a-element["station_start"])
            for offset in (lo,0.,hi):
                profile=evaluator.interp.section_line(center+offset*normal,tangent,0.,b-a)
                result.extend(a+float(ds) for ds,z in profile if 1e-8<ds<b-a-1e-8)
        else:
            # Every crossing of a terrain edge with a contour vertex's
            # longitudinal trace is a possible change in minimum cover.
            triangles = np.asarray(evaluator.interp._tin.points)[evaluator.interp._tin.triangles[candidates], :2]
            relative = triangles - np.asarray(element["start_xy"])
            station = element["station_start"] + relative @ tangent
            lateral = relative @ normal
            end_station = np.roll(station, -1, axis=1)
            end_lateral = np.roll(lateral, -1, axis=1)
            for offset in offsets:
                crosses = (np.minimum(lateral, end_lateral) < offset) & (offset < np.maximum(lateral, end_lateral))
                ratio = (offset-lateral[crosses])/(end_lateral[crosses]-lateral[crosses])
                events = station[crosses]+ratio*(end_station[crosses]-station[crosses])
                result.extend(events[(events>a+1e-8)&(events<b-1e-8)].tolist())
    else:
        sign=math.copysign(1.,element["sweep_angle"])
        delta=points[:,:2]-np.asarray(element["center_xy"])
        angles=(sign*(np.arctan2(delta[:,1],delta[:,0])-element["start_angle"]))%(2*math.pi)
        ss=element["station_start"]+element["radius"]*angles
        uu=sign*(np.hypot(delta[:,0],delta[:,1])-element["radius"])
        mask=(ss>a+1e-8)&(ss<b-1e-8)&(uu>=lo-1e-8)&(uu<=hi+1e-8)
        result.extend(ss[mask].tolist())
        primitive_id=part["primitive_id"]
        if offsets is not None:
            events = _arc_terrain_events(index, element, ids=candidates, offsets=offsets)
        else:
            if primitive_id not in evaluator.arc_terrain_events:
                evaluator.arc_terrain_events[primitive_id]=_arc_terrain_events(index,element)
            events=evaluator.arc_terrain_events[primitive_id]
        result.extend(s for s in events if a+1e-8<s<b-1e-8)
        result.extend(element["station_start"]+i*math.pi*element["radius"]
                      for i in range(1,math.ceil(abs(element["sweep_angle"])/math.pi))
                      if a<element["station_start"]+i*math.pi*element["radius"]<b)
    # Coalesce floating representations of the same measured event only.
    unique=[]
    for s in sorted(result):
        if not unique or s-unique[-1]>1e-7:unique.append(s)
    return unique


def _part_plan_bounds(element,a,b,lo,hi):
    if element["kind"]=="line":
        t=np.array([math.cos(element["tangent_angle"]),math.sin(element["tangent_angle"])])
        n=np.array([t[1],-t[0]]);origin=np.asarray(element["start_xy"])
        points=[origin+(s-element["station_start"])*t+u*n for s in (a,b) for u in (lo,hi)]
    else:
        sign=math.copysign(1.,element["sweep_angle"])
        angles=[element["start_angle"]+sign*(s-element["station_start"])/element["radius"] for s in (a,b)]
        lower,upper=sorted(angles)
        angles.extend(i*math.pi/2 for i in range(math.ceil(lower/(math.pi/2)),math.floor(upper/(math.pi/2))+1))
        center=np.asarray(element["center_xy"])
        points=[center+(element["radius"]+sign*u)*np.array([math.cos(angle),math.sin(angle)])
                for angle in angles for u in (lo,hi)]
    points=np.asarray(points);return [*points.min(axis=0),*points.max(axis=0)]


def _arc_terrain_events(index,element, *, ids=None, offsets=(0.,)):
    """Same analytic edge/circle roots, with conservative original-face selection."""
    if ids is None:
        bounds=_part_plan_bounds(element,element["station_start"],element["station_end"],0.,0.)
        pad=np.finfo(float).eps*max(1.,*map(abs,bounds))*8
        ids=index._tree.query(box(bounds[0]-index._origin[0]-pad,bounds[1]-index._origin[1]-pad,
                                 bounds[2]-index._origin[0]+pad,bounds[3]-index._origin[1]+pad))
    faces=index._triangles[ids]
    if not len(faces):return []
    edges=np.unique(np.sort(np.vstack([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]),axis=1),axis=0)
    center=np.asarray(element["center_xy"])-index._origin
    a=index._points[edges[:,0],:2]-center;v=index._points[edges[:,1],:2]-index._points[edges[:,0],:2]
    aa=np.sum(v*v,axis=1);bb=2*np.sum(a*v,axis=1);norm=np.sum(a*a,axis=1)
    result=[];sign=math.copysign(1.,element["sweep_angle"])
    for offset in offsets:
        radius = element["radius"] + sign*offset
        if radius <= 0.:
            continue
        disc=bb*bb-4*aa*(norm-radius*radius);valid=(aa>1e-16)&(disc>=-1e-8)
        roots=np.sqrt(np.maximum(0,disc[valid]));base=a[valid];vectors=v[valid];den=2*aa[valid]
        for ratio in ((-bb[valid]-roots)/den,(-bb[valid]+roots)/den):
            inside=(ratio>=-1e-9)&(ratio<=1+1e-9)
            xy=base[inside]+ratio[inside,None]*vectors[inside]
            delta=(sign*(np.arctan2(xy[:,1],xy[:,0])-element["start_angle"]))%(2*math.pi)
            delta=np.where(np.abs(delta-2*math.pi)<1e-8,0.,delta)
            result.extend(element["station_start"]+element["radius"]*float(d) for d in delta
                          if d<=abs(element["sweep_angle"])+1e-8)
    return result


def _curve_max_span(element, profile_step):
    radius=float(element["radius"])
    # 4 asin(sqrt(h/(2R))) is stable even when R is very large.
    chord_angle=4*math.asin(min(1.,math.sqrt(CURVE_MAX_CHORD_HEIGHT_M/(2*radius))))
    return min(radius*math.radians(CURVE_MAX_TURN_ANGLE_DEG),radius*chord_angle,profile_step)


def _curve_cut_stations(element, profile_step):
    """Use the saved analytic arc; no sampled polyline or second fillet."""
    radius=float(element["radius"])
    sweep=abs(float(element["sweep_angle"]))
    max_span=_curve_max_span(element,profile_step)
    merge_tolerance=min(CURVE_STATION_MERGE_TOLERANCE_M,max_span/4)
    # Reserve the possible snapping displacement at both ends of a cell.
    safe_span=max_span-2*merge_tolerance
    count=max(2,math.ceil(radius*sweep/safe_span))
    count+=count%2  # Retain the actual arc midpoint, independently of IP binding.
    start,end=element["station_start"],element["station_end"]
    for i in range(count+1):
        reason="curve_start" if i==0 else "curve_end" if i==count else "curve_midpoint" if i==count//2 else "curve_subdivision"
        station=start if i==0 else end if i==count else start+(end-start)*i/count
        yield station,reason


def _fixed_route_sampling(evaluator, catalog, assets, profile_step, *, cancelled=None, progress=None):
    """Keep the original route grid/interfaces and cut real TIN through arcs.

    Ordinary line/profile nodes still do not create cuts. Circular BC/EC,
    midpoints and bounded-angle/chord-height subdivisions do; all are used by
    the same average-end-section integration as the original grid.
    """
    from .dedicated_structure_geometry import dedicated_break_stations
    from .section_geometry import section_structure
    sampled,cells,cell_keys={},[],{}
    curve_summary={"enabled":True,"max_turn_angle_deg":CURVE_MAX_TURN_ANGLE_DEG,
        "max_chord_height_m":CURVE_MAX_CHORD_HEIGHT_M,
        "merge_tolerance_m":CURVE_STATION_MERGE_TOLERANCE_M,
        "arc_count":0,"curve_station_count":0,"added_station_count":0,"added_section_count":0}
    arc_ids=set()
    updates = _SectionProgress(progress,"sections","常规网格及弯道真实地形断面")
    for ai,asset in enumerate(assets):
        _cancel(cancelled)
        a,b=float(asset["station_start"]),float(asset["station_end"])
        original_start,original_end=a,b
        a=catalog.endpoint_station(asset["asset_id"],a)
        b=catalog.endpoint_station(asset["asset_id"],b)
        offset=float(asset.get("station_offset",0.))
        if a!=original_start or b!=original_end:
            asset.setdefault("section_endpoint_adjustments",[]).append({
                "asset_id":asset["asset_id"],
                "original_source_range":[original_start-offset,original_end-offset],
                "adopted_source_range":[a-offset,b-offset],
                "difference_m":[a-original_start,b-original_end],
                "basis":"仅将计算副本的资产端点归并到同一真实有效线元端点，省略零物理长度数值残差"})
            asset.update(station_start=a,station_end=b)
        breaks={s for s in dedicated_break_stations(asset) if a<s<b}
        parts=[p for p in catalog.parts if p["asset_index"]==ai]
        if asset.get("workbench_geometry"):
            # Validate hidden curved spans without cutting TIN or adding
            # deliverable sections. Coarse sampling cannot make unsupported
            # coupled pipe curves or an undersized turn radius admissible.
            for part in parts:
                element=catalog.alignment.elements[part["primitive_id"]]
                if element["kind"]!="arc":continue
                lo,hi=part["station_start"],part["station_end"]
                knots=sorted({lo,hi,*(s for s in evaluator.profile_positions[ai] if lo<s<hi),
                    *(s for s in breaks if lo<s<hi)})
                for left,right in zip(knots,knots[1:]):
                    _cancel(cancelled)
                    station=left+(right-left)/2
                    z,slope=evaluator.profile_at(ai,station)
                    _,_,curvature=catalog.center_tangent_curvature(part["part_id"],station)
                    try:
                        structure=section_structure(asset,elevation=z,slope=slope,station=station,
                            arc_segments=evaluator.arc_segments,plan_curvature=curvature)
                        if min(1+curvature*structure["outer"].bounds[i] for i in (0,2))<=0:
                            raise AssetDataPending("永久结构跨越曲率中心，待核实际转弯半径与结构宽度", code="unsupported_section_geometry")
                    except ValueError as error:
                        raise NetworkSectionCalculationError(f"{asset.get('name',asset['asset_id'])} K{station:.3f}: {error}",
                            code=getattr(error,"code","missing_terrain_or_invalid_section"),
                            diagnostics=getattr(error,"diagnostics",None) or [{"asset_id":asset["asset_id"],"station":station,"message":str(error)}]) from error
        if asset.get("section_type")=="rectangular_pit" or asset.get("kind")=="pit":
            # Pit primitives encode real foundation/bedding/terrace changes,
            # unlike ordinary route line/arc vertices.
            breaks.update(s for p in parts for s in (p["station_start"],p["station_end"]) if a<s<b)
        reasons={s:{"asset_boundary"} for s in (a,b)}
        for station in breaks:reasons.setdefault(station,set()).add("construction_interface")
        first=math.ceil((a-offset)/profile_step)
        last=math.floor((b-offset)/profile_step)
        grid=(s for i in range(first,last+1)
            if a<(s:=offset+i*profile_step)<b
            and not math.isclose(s,a,rel_tol=0.,abs_tol=1e-8)
            and not math.isclose(s,b,rel_tol=0.,abs_tol=1e-8))
        for station in grid:reasons.setdefault(station,set()).add("route_grid")
        base_stations=set(reasons)
        base_keys={(s,side) for s in base_stations for side in
            (("left","right") if s in breaks else ("left",) if s==b else ("right",))}
        stations=sorted(reasons)
        curve_parts=[]
        for part in parts:
            element=catalog.alignment.elements[part["primitive_id"]]
            if element["kind"]!="arc":continue
            arc_ids.add(part["primitive_id"])
            lo,hi=part["station_start"],part["station_end"]
            curve_parts.append((element,lo,hi))
            for station,reason in ((element["station_start"],"curve_start"),(element["station_end"],"curve_end")):
                if not lo<=station<=hi:continue
                if station not in reasons:
                    insort(stations,station);reasons[station]=set()
                reasons[station].add(reason)
                # Curvature jumps change A+k*M even when the geometry is
                # tangent-continuous. Preserve true BC/EC and both one-sided
                # weights; these physical interfaces must never be snapped.
                if a<station<b:breaks.add(station)
        anchor_positions=list(stations)
        for element,lo,hi in curve_parts:
            merge_tolerance=min(CURVE_STATION_MERGE_TOLERANCE_M,_curve_max_span(element,profile_step)/4)
            for station,reason in _curve_cut_stations(element,profile_step):
                if reason in {"curve_start","curve_end"} or not lo<=station<=hi:continue
                index=bisect_left(stations,station)
                neighbours=stations[max(0,index-1):index+1]
                nearest=min(neighbours,key=lambda s:abs(s-station))
                anchor_index=bisect_left(anchor_positions,station)
                anchor_nearest=min(anchor_positions[max(0,anchor_index-1):anchor_index+1],key=lambda s:abs(s-station))
                if abs(anchor_nearest-station)<=merge_tolerance:nearest=anchor_nearest
                # Representatives never move. Each new candidate is within
                # 1 mm of its retained station, with no transitive merging.
                if abs(nearest-station)<=merge_tolerance:
                    reasons[nearest].add(reason)
                else:
                    insort(stations,station);reasons[station]={reason}
        curve_summary["curve_station_count"]+=sum(any(r.startswith("curve_") for r in reasons[s]) for s in stations)
        curve_summary["added_station_count"]+=sum(s not in base_stations for s in stations)
        keys={}
        total = len(stations)+sum(station in breaks for station in stations)
        done = 0
        updates.report(asset,stations[0],done,total,.4*ai/max(1,len(assets)),force=True)
        for station in stations:
            sides=("left","right") if station in breaks else (("left",) if station==b else ("right",))
            for side in sides:
                _cancel(cancelled)
                updates.report(asset,station,done,total,
                    .4*(ai+done/max(1,total))/max(1,len(assets)))
                try:
                    pid=catalog.part_at(asset["asset_id"],station,side)
                except ValueError as error:
                    raise NetworkSectionCalculationError(
                        f"{asset.get('name',asset['asset_id'])} K{station-offset:.9f}：断面桩号未被实际施工路线覆盖",
                        code="fixed_section_outside_asset_route",diagnostics=[{
                            "asset_id":asset["asset_id"],"station":station-offset,"side":side,
                            "internal_station":station,"station_offset":offset,
                            "message":str(error)}]) from error
                part=catalog.parts[pid]
                if part["asset_index"]!=ai:
                    raise NetworkSectionCalculationError("固定断面定位到其他施工对象",code="invalid_fixed_section_owner")
                value=evaluator.exact(part,station,side)
                value["sampling_reasons"]=sorted(reasons[station])
                value["curve_station_added"]=station not in base_stations
                value["curve_added"]=(station,side) not in base_keys
                curve_summary["added_section_count"]+=int(value["curve_added"])
                sampled.setdefault(pid,[]).append(value)
                keys[(station,side)]=(pid,station,side)
                done += 1
                updates.report(asset,station,done,total,
                    .4*(ai+done/max(1,total))/max(1,len(assets)),force=done==total)
        for left,right in zip(stations,stations[1:]):
            left_key=keys[(left,"right")]
            right_key=keys[(right,"left" if right in breaks or right==b else "right")]
            cells.append((catalog.parts[left_key[0]],left,None,right))
            crossed=[p for p in parts if p["station_start"]<right and p["station_end"]>left]
            cell_keys[(ai,left,right)]=(left_key,right_key,crossed)
    curve_summary["arc_count"]=len(arc_ids)
    evaluator.curve_sampling=curve_summary
    return sampled,cells,cell_keys


def _integrate_endpoint_components(records, length, asset, start, end):
    """Apply the average-section rule to real endpoint material measures."""
    first,last=records
    if asset.get("section_scheme_terrain_variants") or asset.get("section_scheme_selectors"):
        # Actual terrain selects construction at the user's existing stations.
        # An absent material at one endpoint contributes zero endpoint area;
        # this does not assert a zero quantity for a missing required input.
        identity=lambda row:(row["component_id"],row.get("material",""),row.get("grade",""),row["unit"])
        maps=[{identity(row):row for row in group} for group in (first,last)]
        result=[]
        for key in sorted(set(maps[0])|set(maps[1]),key=str):
            left,right=(group.get(key) for group in maps)
            source=left or right
            metadata={name:deepcopy(value) for name,value in source.items() if name not in {"rate","section_measure"}}
            metadata["method"]="actual_terrain_variant_material_average_end_sections"
            metadata["endpoint_rates"]=[float((left or {}).get("rate",0.)),float((right or {}).get("rate",0.))]
            result.append({**metadata,"asset_id":asset["asset_id"],"asset_name":asset.get("name",""),
                "station_start":start,"station_end":end,"quantity":length*sum(metadata["endpoint_rates"])/2})
        return result
    maps=[{(x["component_id"],x["unit"]):x for x in group} for group in (first,last)]
    if set(maps[0])!=set(maps[1]):
        raise ConstructionInputError("积分段材料构件发生突变，须在变化桩号分段")
    result=[]
    for key in sorted(maps[0]):
        left,right=(group[key] for group in maps)
        if (left.get("material"),left.get("grade"))!=(right.get("material"),right.get("grade")):
            raise ConstructionInputError("积分段材料等级发生变化，须拆分区段")
        metadata={k:deepcopy(v) for k,v in left.items() if k not in {"rate","section_measure"}}
        method=metadata.get("method","")
        metadata["method"]=method.replace("actual_midpoint_Simpson","average_end_sections").replace("_Simpson","_average_end_sections")
        result.append({**metadata,"asset_id":asset["asset_id"],"asset_name":asset.get("name",""),
            "station_start":start,"station_end":end,"quantity":length*(left["rate"]+right["rate"])/2})
    return result


def calculate_network_sections(tin, network, *, profile_step=20., relative_tolerance=.01,
        absolute_tolerance=10., max_refinements=2, arc_segments=64, chord_tolerance=.04,
        lateral_step=1., cancelled=None, progress=None, keep_sections=True, refinement_strategy="adaptive",
        terrain_event_policy="all", material_joint_policy="strict", per_asset_relative_tolerance=None,
        per_asset_absolute_tolerance=None,
        lateral_refinement=True, sampling_mode="adaptive", overlap_policy="spatial_union", collect_deferrals=False):
    """Use adaptive refinement or explicit fixed-spacing average sections.

    max_refinements为基本轮之后最多再细分次数。每轮比较全部结构三分项，
    工程精度允许值为absolute_tolerance + relative_tolerance*分项量。
    independent_sections保留各断面完整施工量，spatial_union按空间归属扣重。
    """
    from .network_section_projection import Catalog
    if sampling_mode not in {"adaptive","fixed"}:
        raise NetworkSectionCalculationError("断面采样模式仅支持 adaptive/fixed")
    fixed=sampling_mode=="fixed"
    if (not all(math.isfinite(float(v)) for v in (profile_step,lateral_step,relative_tolerance,absolute_tolerance,max_refinements))
            or profile_step<=0 or lateral_step<=0 or relative_tolerance<0 or absolute_tolerance<0
            or max_refinements<(0 if fixed else 1)):
        raise NetworkSectionCalculationError("断面间距/精度配置无效")
    asset_tolerance=relative_tolerance if per_asset_relative_tolerance is None else float(per_asset_relative_tolerance)
    asset_absolute=absolute_tolerance if per_asset_absolute_tolerance is None else float(per_asset_absolute_tolerance)
    if not math.isfinite(asset_tolerance) or asset_tolerance<0 or not math.isfinite(asset_absolute) or asset_absolute<0:
        raise NetworkSectionCalculationError("逐对象复算允许差无效")
    if refinement_strategy not in {"adaptive","uniform"}:
        raise NetworkSectionCalculationError("复算策略仅支持 adaptive/uniform")
    if terrain_event_policy not in {"all","regular"} or material_joint_policy not in {"strict","section_union"}:
        raise NetworkSectionCalculationError("断面采样或接头计量配置无效")
    if overlap_policy not in {"spatial_union","independent_sections"}:
        raise NetworkSectionCalculationError("重叠计量口径仅支持 spatial_union/independent_sections")
    require_disjoint_trenchless_ranges(network["assets"])
    assets=[]
    excluded=current_exclusion_records(network.get("excluded_assets",[]))
    for original in network["assets"]:
        non_open_cut=trenchless_exclusion(original,route_id=trenchless_live_route_id(network))
        if non_open_cut:
            excluded.append(non_open_cut)
        else:
            assets.append(deepcopy(original))
    if not assets:
        return trenchless_only_result(excluded,test_only=bool(network.get("test_only")),
                                     overlap_policy=overlap_policy,cancelled=cancelled)
    if tin is None:
        raise NetworkSectionCalculationError("含明挖断面的工程须先读取天然地形",code="missing_terrain")
    alignment = network["alignment"]
    if isinstance(alignment, dict):
        alignment = NetworkAlignment.from_dict(alignment)
    assets.sort(key=lambda a:(a["station_start"],a["station_end"],a["asset_id"]))
    normalize_construction_inputs(assets)
    from .layered_excavation import validate_layer_asset
    layered_ids=[]
    for asset in assets:
        try:
            config=validate_layer_asset(asset)
        except ValueError as error:
            raise NetworkSectionCalculationError(f"{asset.get('name',asset['asset_id'])}：{error}",
                code="invalid_layered_excavation",diagnostics=[{"asset_id":asset["asset_id"],"message":str(error)}]) from error
        if config is not None:
            layered_ids.append(asset["asset_id"])
            asset["workbench_geometry"]=True
    unlayered_ids=[a["asset_id"] for a in assets if a["asset_id"] not in layered_ids]
    layer_roles=(LAYER_ROLES if unlayered_ids else LAYER_ROLES[:2]) if layered_ids else ()
    from .dedicated_structure_geometry import register_dedicated_components, dedicated_break_stations
    for asset in assets:register_dedicated_components(asset)
    profiles = [_profile(a,network) for a in assets]
    qroles=ROLES+MATERIAL_ROLES+extra_material_roles(assets) if any(a.get("workbench_geometry") for a in assets) else ROLES
    qroles+=layer_roles
    adaptive=not fixed and refinement_strategy=="adaptive" and MATERIAL_ROLES[0] in qroles
    evaluator = _Sections(tin, alignment, assets, profiles, int(arc_segments))
    evaluator.material_joint_policy=material_joint_policy
    evaluator.overlap_policy=overlap_policy
    evaluator.sampling_mode=sampling_mode
    origin = np.array(alignment.get_xy_at_station(alignment.start_station))
    catalog = Catalog(alignment,assets,origin,{a["asset_id"]:0. for a in assets})
    evaluator.catalog = catalog
    terrain_knots={part["part_id"]:(_terrain_knots(evaluator,part) if not fixed and terrain_event_policy=="all" else []) for part in catalog.parts}
    history, previous_rows, previous_totals, previous_segments = [], None, None, None
    final_sections, final_segments, final_rows = [], [], []
    last_refinement=0 if fixed else int(max_refinements)
    for refinement in range(last_refinement+1):
        # Only previous quantities/interval checks are needed for convergence.
        # Release the preceding drawing records before constructing the next
        # round; every returned section still belongs to the final true round.
        final_sections,final_segments,final_rows=[],[],[]
        sections=[]
        start_time = time.perf_counter()
        evaluator.joint_approximations={}
        step = profile_step/(2**refinement)
        actual_lateral_step=lateral_step/(2**refinement) if lateral_refinement else lateral_step
        sampled, cells = {}, []
        prior_by_part={};refine_all=False;refine_assets=set();ranges={}
        refined_intervals=retained_intervals=0
        fixed_keys={}
        if fixed:
            sampled,cells,fixed_keys=_fixed_route_sampling(evaluator,catalog,assets,profile_step,
                cancelled=cancelled,progress=progress)
        if adaptive and refinement>=2:
            for item in previous_segments:prior_by_part.setdefault(item["part_id"],[]).append(item)
            for check in history[-1]["checks"]:
                if check["passed"] or not check.get("admission_required",True):continue
                if check["asset_id"]=="GLOBAL":refine_all=True
                elif check.get("scope")=="interval":
                    ranges.setdefault(check["asset_id"],set()).add((check["station_start"],check["station_end"]))
                else:refine_assets.add(check["asset_id"])
            for aid,pairs in list(ranges.items()):
                merged=[]
                for left,right in sorted(pairs):
                    if merged and left<=merged[-1][1]:merged[-1]=(merged[-1][0],max(merged[-1][1],right))
                    else:merged.append((left,right))
                ranges[aid]=([left for left,right in merged],merged)
        count = len(catalog.parts)
        section_updates = _SectionProgress(progress,"sections",f"第{refinement+1}轮真实地形断面")
        for part_index, part in enumerate([] if fixed else catalog.parts):
            _cancel(cancelled)
            ai = part["asset_index"]
            a,b = part["station_start"],part["station_end"]
            if adaptive and refinement>=2:
                stations=[];starts,pairs=ranges.get(part["asset_id"],([],[]))
                for interval in prior_by_part[part["part_id"]]:
                    left,right=interval["station_start"],interval["station_end"];middle=left+(right-left)/2
                    j=bisect_right(starts,middle)-1
                    refine=refine_all or part["asset_id"] in refine_assets or (j>=0 and middle<pairs[j][1])
                    stations.append(left)
                    if refine:stations.append(middle);refined_intervals+=1
                    else:retained_intervals+=1
                stations.append(b)
            else:
                knots = sorted({a,b,*(s for s,_ in profiles[ai] if a<s<b),*terrain_knots[part["part_id"]],
                                *(s for s in dedicated_break_stations(assets[ai]) if a<s<b)})
                stations=[]
                for left,right in zip(knots,knots[1:]):
                    n=max(1,math.ceil((right-left)/profile_step))*2**refinement
                    stations.extend(left+(right-left)*i/n for i in range(n))
                stations.append(b)
            mids=[x+(y-x)/2 for x,y in zip(stations,stations[1:])]
            all_s=sorted(set(stations+mids))
            # Profile slope/section changes have two limits at one station.
            # Each interval integrates its own endpoint, avoiding a false
            # jump error that never vanishes by refining the wrong limit.
            profile_knots={s for s,_ in profiles[ai] if a<s<b} if assets[ai].get("workbench_geometry") else set()
            profile_knots.update(s for s in dedicated_break_stations(assets[ai]) if a<s<b)
            element=alignment.elements[part["primitive_id"]]
            if element["kind"]=="arc" and assets[ai].get("workbench_geometry"):
                profile_knots.update(element["station_start"]+i*math.pi*element["radius"]
                    for i in range(1,math.ceil(abs(element["sweep_angle"])/math.pi))
                    if a<element["station_start"]+i*math.pi*element["radius"]<b)
            cuts=[(s,"left" if s==b else "right") for s in all_s]
            cuts.extend((s,"left") for s in sorted(profile_knots))
            total=len(cuts)
            section_updates.report(assets[ai],cuts[0][0],0,total,
                .4*part_index/max(1,count),force=True)
            values=[]
            for done,(station,side) in enumerate(cuts,1):
                _cancel(cancelled)
                section_updates.report(assets[ai],station,done-1,total,
                    .4*(part_index+(done-1)/max(1,total))/max(1,count))
                values.append(evaluator.exact(part,station,side))
                section_updates.report(assets[ai],station,done,total,
                    .4*(part_index+done/max(1,total))/max(1,count),force=done==total)
            sampled[part["part_id"]]=values
            sampled[part["part_id"]].sort(key=lambda v:(v["station"],0 if v["side"]=="left" else 1))
            for left,right in zip(stations,stations[1:]):
                cells.append((part,left,left+(right-left)/2,right))
        widths={a["asset_id"]:[0.,0.] for a in assets}
        for values in sampled.values():
            for value in values:
                l,_,r,_=value["domain"].bounds
                w=widths[value["part"]["asset_id"]]
                w[0]=min(w[0],l); w[1]=max(w[1],r)
        if fixed and overlap_policy=="spatial_union":
            # Unsampled interior terrain can produce wider earthwork than
            # either endpoint. Keep the projection catalog conservative;
            # actual foreign regions are still evaluated and clipped exactly.
            bbox=tin.get_bbox()
            reach=math.hypot(bbox[2]-bbox[0],bbox[3]-bbox[1])
            widths={aid:[-reach-max(abs(v) for v in width),reach+max(abs(v) for v in width)]
                for aid,width in widths.items()}
        # 空间索引仅取保守候选；精确解析preimages决定是否实际相交。
        catalog=Catalog(alignment,assets,origin,widths)
        evaluator.catalog=catalog
        sections, section_states, section_lookup, weighted, gross_weighted = [], [], {}, {}, {}
        component_samples = {}
        total_evaluations=sum(len(v) for v in sampled.values())
        done=0
        integration_label = ("汇总断面工程量" if overlap_policy == "independent_sections"
                             else f"第{refinement+1}轮净断面")
        integration_updates = _SectionProgress(progress,"integration",integration_label)
        for pid,values in sampled.items():
            for value in values:
                _cancel(cancelled)
                asset=assets[value["part"]["asset_index"]]
                integration_updates.report(asset,value["station"],done,total_evaluations,
                    .4+.55*done/max(1,total_evaluations),force=done==0)
                net,diagnostic=_net_section(evaluator,value,sampled,actual_lateral_step)
                gross_regions=value["gross"]
                if layer_roles:
                    net,gross_regions=_layer_section(value,net,effective_construction(value.get("effective_asset",asset)),
                        include_unclassified=bool(unlayered_ids))
                if net is gross_regions:
                    net = gross_regions = _split_backfill(value, net)
                else:
                    net = _split_backfill(value, net)
                    gross_regions = _split_backfill(value, gross_regions)
                section_roles = qroles+tuple(role for role in BACKFILL_ROLES if role in net)
                sid=f"r{refinement}-p{pid}-s{value['station'].hex()}-{value['side']}"
                key=(pid,value["station"],value["side"])
                roles={r:polygon_metrics(net[r],value["curvature"]) for r in section_roles}
                if value.get("structure",{}).get("pipes") and "concrete" in roles:
                    # Pipe material follows its real spatial axis. A curved
                    # vertical slice is not a normal annulus; normal area and
                    # actual axis length provide its physical material volume.
                    weighted_material=0.;gross_pipe_material=0.
                    structure=value["structure"]
                    for pipe,pipe_region in zip(structure["pipes"],structure["pipe_material_regions"]):
                        if pipe_region.is_empty:continue
                        ro=pipe["outer_diameter"]/2;ri=ro-pipe["wall_thickness"]
                        normal_area=pipe.get("concrete_normal_area",math.pi*(ro*ro-ri*ri))
                        spatial_factor=math.hypot(1+value["curvature"]*pipe["offset"],pipe["vertical_slope"])
                        ownership=net["concrete"].intersection(pipe_region).area/pipe_region.area
                        if 1e-7<ownership<1-1e-7 and material_joint_policy=="strict":
                            raise NetworkSectionCalculationError("弯管材料部分重叠的空间归属尚不能精确解析",code="material_overlap_unresolved")
                        if 1e-7<ownership<1-1e-7 and material_joint_policy=="section_union":
                            aid=value["part"]["asset_id"];station=value["station"]
                            note=evaluator.joint_approximations.setdefault((aid,value["part"]["primitive_id"]),
                                {"asset_id":aid,"station_start":station,"station_end":station,
                                 "evaluated_overlap_count":0,"maximum_overlap_area_m2":0.})
                            note["station_start"]=min(note["station_start"],station)
                            note["station_end"]=max(note["station_end"],station)
                            note["evaluated_overlap_count"]+=1
                            note["maximum_overlap_area_m2"]=max(note["maximum_overlap_area_m2"],pipe_region.area*(1-ownership))
                        weighted_material+=normal_area*spatial_factor*ownership
                        gross_pipe_material+=normal_area*spatial_factor
                    pipe_concrete=structure["pipe_concrete"]
                    support_area=_polygonal(net["concrete"].difference(pipe_concrete))
                    roles["concrete"]["weighted_area"]=weighted_material+polygon_metrics(support_area,value["curvature"])["weighted_area"]
                    roles["concrete"]["quantity_method"]=("normal_material_area_endpoint_average_axis_factor" if fixed
                        else "normal_material_area_actual_spatial_axis_length")
                    value["gross_concrete_weighted_area"]=gross_pipe_material+polygon_metrics(
                        value["gross"]["concrete"].difference(pipe_concrete),value["curvature"])["weighted_area"]
                for component in nonconcrete_pipe_components(value.get("effective_asset",asset),value.get("structure",{})):
                    role=component_role(component["component_id"])
                    region=component["geometry"]
                    ownership=net[role].intersection(region).area/region.area
                    if 1e-7<ownership<1-1e-7:
                        raise NetworkSectionCalculationError("非混凝土管材发生部分空间归属，须明确实际边界",code="material_overlap_unresolved")
                    gross_rate=component["normal_area"]*math.hypot(1+value["curvature"]*component["offset"],component["vertical_slope"])
                    roles[role]["weighted_area"]=gross_rate*ownership
                    roles[role]["quantity_method"]="normal_material_area_endpoint_average_axis_factor" if fixed else "normal_material_area_actual_spatial_axis_length"
                    value.setdefault("gross_pipe_component_rates",{})[role]=gross_rate
                component_samples[key] = section_components(value.get("effective_asset",asset), value, net, roles)
                if fixed:
                    for component in component_samples[key]:
                        component["method"]=component.get("method","").replace("actual_midpoint_Simpson","average_end_sections").replace("_Simpson","_average_end_sections")
                value["quantity_components"] = component_samples[key]
                weighted[key]={r:roles[r]["weighted_area"] for r in section_roles}
                gross_weighted[key]={r:polygon_metrics(gross_regions[r],value["curvature"])["weighted_area"] for r in section_roles}
                if "gross_concrete_weighted_area" in value:gross_weighted[key]["concrete"]=value["gross_concrete_weighted_area"]
                gross_weighted[key].update(value.get("gross_pipe_component_rates",{}))
                section_lookup[key]=sid
                if keep_sections:
                    section_states.append((value,net,roles,diagnostic,gross_weighted[key],sid,pid))
                done+=1
                integration_updates.report(asset,value["station"],done,total_evaluations,
                    .4+.55*done/max(1,total_evaluations),force=done==total_evaluations)
        totals={r:0. for r in qroles}
        gross_totals={r:0. for r in qroles}
        row_values=[{r:0. for r in qroles} for a in assets]
        segments=[]
        for part,a,m,b in cells:
            pid=part["part_id"]
            crossed=[]
            if fixed:
                left_key,right_key,crossed=fixed_keys[(part["asset_index"],a,b)]
                keys=[left_key,right_key]
            else:
                keys=[(pid,a,"right"),(pid,m,"right"),(pid,b,"left" if (pid,b,"left") in weighted else "right")]
            weights=(.5,.5) if fixed else (1/6,4/6,1/6)
            segment_roles = qroles+tuple(role for role in BACKFILL_ROLES if any(role in weighted[k] for k in keys))
            volumes={r:(b-a)*sum(c*weighted[k].get(r,0.) for c,k in zip(weights,keys)) for r in segment_roles}
            gross_volumes={r:(b-a)*sum(c*gross_weighted[k].get(r,0.) for c,k in zip(weights,keys)) for r in segment_roles}
            row = row_values[part["asset_index"]]
            for r, volume in volumes.items():
                row[r] = row.get(r,0.)+volume
                totals[r] = totals.get(r,0.)+volume
                gross_totals[r] = gross_totals.get(r,0.)+gross_volumes[r]
            segments.append({"asset_id":part["asset_id"],"primitive_id":part["primitive_id"],"part_id":part["part_id"],
                **({"start_part_id":keys[0][0],"end_part_id":keys[-1][0],
                    "start_primitive_id":catalog.parts[keys[0][0]]["primitive_id"],
                    "end_primitive_id":catalog.parts[keys[-1][0]]["primitive_id"],
                    "part_ids":[p["part_id"] for p in crossed],
                    "primitive_ids":[p["primitive_id"] for p in crossed]} if fixed else {}),
                "station_start":a,"station_end":b,"length":b-a,
                "start_section_id":section_lookup[keys[0]],"end_section_id":section_lookup[keys[-1]],
                **({"mid_station":m,"mid_section_id":section_lookup[keys[1]]} if not fixed else {}),
                **_with_fill(volumes),"integration_rule":"average_end_sections" if fixed else "actual_midpoint_Simpson", "gross_volumes":_with_fill(gross_volumes),
                "quantity_items":(_integrate_endpoint_components if fixed else integrate_components)(
                    [component_samples[k] for k in keys], b-a, assets[part["asset_index"]], a, b)})
        rows=[{"asset_id":a["asset_id"],"name":a.get("name",a["asset_id"]),"kind":a.get("kind"),"section_type":a["section_type"],
               **{key:deepcopy(a[key]) for key in ("generated_aqueduct_foundation","parent_asset_id","parent_component_id",
                   "parent_route_id","parent_station_start","parent_station_end","flow_section") if key in a},
               "station_start":a["station_start"],"station_end":a["station_end"],**_with_fill(v)} for a,v in zip(assets,row_values)]
        quantity_items=aggregate_components(segments, assets)
        for item in quantity_items:
            owner=next(a for a in assets if a["asset_id"]==item["asset_id"])
            if owner.get("flow_section"):
                item["flow_section"] = owner["flow_section"]
            if owner.get("generated_aqueduct_foundation"):
                for key in ("parent_asset_id","parent_component_id","parent_route_id","parent_station_start","parent_station_end"):
                    item[key]=owner[key]
                item["scope_category"]="foundation"
        for row in rows:
            row["quantity_items"] = [x for x in quantity_items if x["asset_id"] == row["asset_id"]]
        checks=[]
        if previous_rows is not None:
            for old,new in zip(previous_rows,rows):
                for role in qroles:
                    key=role+"_volume"; error=abs(new[key]-old[key]); allowed=asset_absolute+asset_tolerance*abs(new[key])
                    checks.append({"asset_id":new["asset_id"],"role":role,"difference_m3":error,"allowed_m3":allowed,"passed":error<=allowed})
            for role in qroles:
                error=abs(totals[role]-previous_totals[role]); allowed=absolute_tolerance+relative_tolerance*abs(totals[role])
                checks.append({"asset_id":"GLOBAL","role":role,"difference_m3":error,"allowed_m3":allowed,"passed":error<=allowed})
            if MATERIAL_ROLES[0] in qroles:
                # Every previous interval is exactly tiled by the nested new
                # intervals. Local errors cannot cancel in a long asset total.
                by_part={}
                for item in segments:by_part.setdefault(item["part_id"],[]).append(item)
                indices={}
                for pid,items in by_part.items():
                    ends=[items[0]["station_start"]]+[v["station_end"] for v in items]
                    sums={r:[0.] for r in qroles}
                    for v in items:
                        for r in qroles:sums[r].append(sums[r][-1]+v[r+"_volume"])
                    indices[pid]=(ends,sums)
                for old in previous_segments:
                    ends,sums=indices[old["part_id"]]
                    ia=max(0,bisect_right(ends,old["station_start"]+1e-8)-1)
                    ib=max(0,bisect_right(ends,old["station_end"]+1e-8)-1)
                    for r in qroles:
                        fine=sums[r][ib]-sums[r][ia];error=abs(fine-old[r+"_volume"])
                        allowed=absolute_tolerance+relative_tolerance*abs(fine)
                        checks.append({"asset_id":old["asset_id"],"role":r,
                            "station_start":old["station_start"],"station_end":old["station_end"],
                            "difference_m3":error,"allowed_m3":allowed,"passed":error<=allowed,"scope":"interval",
                            "admission_required":terrain_event_policy!="regular"})
        required_checks=[c for c in checks if c.get("admission_required",True)]
        reference_checks=[c for c in checks if not c.get("admission_required",True)]
        passed=bool(required_checks) and all(c["passed"] for c in required_checks)
        if keep_sections and (passed or refinement==last_refinement):
            sections=[_serialize_section(state) for state in section_states]
        history.append({"refinement":refinement,"profile_step":step,"lateral_step":actual_lateral_step,
            **({"fixed_sampling_contract":FIXED_SAMPLING_CONTRACT} if fixed else {}),
            **({"curve_sampling":deepcopy(evaluator.curve_sampling)} if fixed else {}),
            "sampling_mode":sampling_mode,"convergence_checked":not fixed,
            "sampling_policy":FIXED_SAMPLING_POLICY if fixed else "adaptive_failed_intervals" if adaptive else "uniform_nested",
            "refined_interval_count":refined_intervals,"retained_interval_count":retained_intervals,
            "maximum_actual_interval_m":max((b-a for part,a,m,b in cells),default=0.),
            "arc_segments":int(arc_segments),**_with_fill(totals),"gross_volumes":_with_fill(gross_totals),
            "overlap_correction_volumes":_with_fill({r:gross_totals[r]-totals[r] for r in totals}),
            "section_count":len(weighted),"segment_count":len(segments),"checks":checks,"passed":passed,
            "convergence_scope":"not_checked" if fixed else "global_and_per_asset" if terrain_event_policy=="regular" else "global_per_asset_and_interval",
            "reference_interval_failed_count":sum(not c["passed"] for c in reference_checks),
            "elapsed_seconds":time.perf_counter()-start_time})
        final_sections,final_segments,final_rows=sections,segments,rows
        if progress:
            failed=[c for c in required_checks if not c["passed"]]
            detail=_convergence_progress_detail(failed,assets)
            if reference_checks:
                detail+=f"；{sum(not c['passed'] for c in reference_checks)}项局部间距差仅供参考"
            if fixed:
                progress("convergence",1.,f"常规最大间距{profile_step:g}m、弯道加密，平均断面法；挖方{totals['excavation']:.1f}m3")
            else:
                progress("convergence",1.,f"第{refinement+1}轮完成，挖方{totals['excavation']:.1f}m3，逐结构复核{'通过' if passed else '待复算'}{detail}")
        if passed:
            break
        previous_rows,previous_totals,previous_segments=rows,totals,segments
    validation={"converged":history[-1]["passed"],"global_and_per_asset_convergence":history[-1]["passed"],
        "section_endpoint_adjustments":[record for asset in assets
            for record in asset.get("section_endpoint_adjustments",[])],
        **({"fixed_sampling_contract":FIXED_SAMPLING_CONTRACT} if fixed else {}),
        **({"curve_sampling":deepcopy(evaluator.curve_sampling)} if fixed else {}),
        "sampling_mode":sampling_mode,"profile_step":profile_step,"convergence_checked":not fixed,
        "fixed_spacing_complete":fixed,
        "integration_method":FIXED_INTEGRATION_METHOD if fixed else "exact_tin_actual_midpoint_section_integration",
        "sampling_policy":FIXED_SAMPLING_POLICY if fixed else "adaptive_failed_intervals" if adaptive else "uniform_nested",
        "relative_tolerance":relative_tolerance,"absolute_tolerance_m3":absolute_tolerance,
        "per_asset_relative_tolerance":asset_tolerance,"per_asset_absolute_tolerance_m3":asset_absolute,"lateral_refinement":bool(lateral_refinement) and not fixed,
        "terrain_event_policy":"regular" if fixed else terrain_event_policy,"material_joint_policy":material_joint_policy,
        "convergence_scope":"not_checked" if fixed else "global_and_per_asset" if terrain_event_policy=="regular" else "global_per_asset_and_interval",
        "local_interval_checks_reference_only":terrain_event_policy=="regular",
        "terrain_extrapolation":False,"three_dimensional_quantity_backend":False,
        "overlap_policy":overlap_policy,"overlap_deduction_applied":overlap_policy=="spatial_union",
        "overlap_method":("none_independent_sections" if overlap_policy=="independent_sections"
            else "analytic_XY_preimages_sampled_Z_intervals_station_first_owner"),
        "overlap_approximation":("none" if overlap_policy=="independent_sections"
            else "first_daylight_offsets_interpolated_between_exact_sections; lateral_midpoint_bands"),
        "curvature_method":"area_plus_first_lateral_moment_absolute_Jacobian_split_at_curvature_center"}
    overlap_note=("各断面独立计量，不扣除前后段或其他对象的开挖、填方及材料重叠；本断面自身结构与材料占位仍按施工状态扣除。"
        if overlap_policy=="independent_sections" else "重叠按二维断面扣重。")
    diagnostics=[{"code":"engineering_section_method","severity":"info",
        "message":(f"常规最大间距{profile_step:g}m，平均断面法；保留全线原网格及结构与材料界面，圆弧起终点、弧中点及弯道加密断面参与计量（最大转角{CURVE_MAX_TURN_ANGLE_DEG:g}°、轴线弦高{CURVE_MAX_CHORD_HEIGHT_M:g}m、新增点去重{CURVE_STATION_MERGE_TOLERANCE_M:g}m）。每张断面剖切原TIN。{overlap_note}"
            if fixed else f"{profile_step:g}m基本断面、真实中点及加密复算；保留结构端点、线元与设计变坡点。{overlap_note}复算差由成果记录。") }]
    if overlap_policy=="independent_sections":
        diagnostics.append({"code":"independent_section_quantities","severity":"info",
            "message":overlap_note,"overlap_deduction_applied":False})
    layer_scope={}
    if layered_ids:
        layer_scope={"layered_asset_ids":layered_ids,"unlayered_asset_ids":unlayered_ids,
            "complete":not unlayered_ids,"source":"user_assumed_vertical_thickness",
            "interface_rule":"z_interface(u)=z_ground(u)-overburden_thickness",
            "overburden_volume":totals["overburden"],"bedrock_volume":totals["bedrock"],
            "unclassified_excavation_volume":totals.get("unclassified_excavation",0.)}
        validation["layered_excavation_scope"]=deepcopy(layer_scope)
        diagnostics.append({"code":"assumed_surface_thickness_geology","severity":"info",
            "message":"基覆界面按用户输入的覆盖层竖直厚度由原地面下移生成，属于简化分层；覆盖层、基岩和未分层挖方均为天然开挖子项，不能重复累计。"})
    if terrain_event_policy=="regular" and not fixed:
        diagnostics.append({"code":"regular_engineering_sections","severity":"info",
            "message":f"采用常规工程断面间距；每张断面均剖切原TIN，不按每个三角网顶点另加断面。全线分项按{relative_tolerance*100:g}%＋{absolute_tolerance:g}m³、逐对象分项按{asset_tolerance*100:g}%＋{asset_absolute:g}m³复核；局部积分段间距差仅供参考。"})
    if material_joint_policy=="section_union" and overlap_policy=="spatial_union":
        diagnostics.append({"code":"section_joint_approximation","severity":"warning" if evaluator.joint_approximations else "info",
            "message":"弯折接头按两侧实际断面分段积分；同一管道或同路线同物理端点的相邻对象，仅在接头附近按断面面积扣重，混凝土优先、垫层扣除重叠。异路线、非相邻或远离接头的材料冲突仍报错。弯头、接头局部构造增减量未单列。",
            "affected_locations":list(evaluator.joint_approximations.values())})
    quantities = _with_fill(totals)
    return NetworkSectionCalculationResult(quantities,final_rows,final_sections,final_segments,history,validation,
        diagnostics=diagnostics,
        input_metadata={"overlap_policy":overlap_policy},
        terrain_metadata=deepcopy(getattr(tin,"metadata",{}) or {}),test_only=bool(network.get("test_only",False)),
        quantity_items=quantity_items,layered_excavation_scope=layer_scope,excluded_assets=excluded,
        trenchless_excavation=trenchless_excavation_quantities(excluded, quantities["excavation_volume"]))
