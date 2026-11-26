# -*- coding: utf-8 -*-
"""既有建筑物资料 → 独立断面算量；复用施工模板，不依赖 Rhino。"""
from __future__ import annotations

from ..services.construction_rules import effective_construction, normalize_asset_construction

from bisect import bisect_right
from copy import deepcopy
from dataclasses import fields
import math
import numpy as np
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union

from ..core.cross_section import CrossSectionCalculator
from ..core.tin_interpolator import TINInterpolator
from ..models.alignment import Alignment
from ..models.section import SlopeGrade
from ..services.construction_templates import build_construction_section, _section_outer, _number
from ..services.contracts import ConstructionInputError, SECTION_TYPES, finite_number


REGION_KEYS = ("domain", "excavation", "target", "permanent", "measured", "open_air")
TARGET_MODES = {"restore_terrain", "union_terrain", "finished_profile"}


def _regions(rings, name):
    if isinstance(rings, (Polygon, MultiPolygon)):
        result = rings
    else:
        parts = []
        for ring in rings or []:
            if len(ring) < 4 or list(ring[0]) != list(ring[-1]):
                raise ConstructionInputError(f"{name}轮廓必须显式闭合")
            if any(len(p) != 2 or any(not math.isfinite(float(v)) for v in p) for p in ring):
                raise ConstructionInputError(f"{name}必须是有限二维断面坐标")
            part = Polygon(ring)
            if not part.is_valid or part.area <= 0:
                raise ConstructionInputError(f"{name}轮廓无效，不自动修复")
            parts.append(part)
        result = unary_union(parts) if parts else Polygon()
    if result.has_z or not result.is_valid or not math.isfinite(result.area):
        raise ConstructionInputError(f"{name}必须是有效二维断面区域")
    return result


def _alignment(asset, prepared):
    data = asset.get("alignment") or {}
    if (data.get("curves_require_resolution") or data.get("source") == "rhino_curve"
            or data.get("native_samples") is not None
            or any(p.get("turn_radius", 0) for p in data.get("plan_points", []))
            or any(p.get("vertical_curve_radius", 0) for p in data.get("profile_points", []))):
        raise ConstructionInputError("真实曲线尚无独立参数化解析；请先明确直线工程段，不把曲线采样折线冒充原曲线")
    if data.get("chainage_breaks"):
        raise ConstructionInputError("断链须先明确连续里程映射，不能用跳号作为长度")
    points = data.get("plan_points")
    if not points and prepared:
        if any(len(s.get("origin", [])) != 3 for s in prepared):
            raise ConstructionInputError("已准备断面缺少三维 origin，不能恢复线路")
        points = [{"station": s.get("station"), "x": s["origin"][0], "y": s["origin"][1]} for s in prepared]
    if not points or len(points) < 2:
        raise ConstructionInputError("平面线路至少需要两个真实坐标点")
    rows = [(finite_number(p.get("station"), "平面桩号"), finite_number(p.get("x"), "线路X"),
             finite_number(p.get("y"), "线路Y")) for p in points]
    for a, b in zip(rows, rows[1:]):
        length = math.hypot(b[1]-a[1], b[2]-a[2])
        if b[0] <= a[0] or length <= 0:
            raise ConstructionInputError("平面桩号必须递增且不得含零长度段")
        if not math.isclose(b[0]-a[0], length, rel_tol=1e-8, abs_tol=1e-5):
            raise ConstructionInputError("桩号间距与平面长度不一致；须明确曲线或连续里程，不能直接算量")
    result = Alignment.from_station_table(rows)
    # 此接口的横断面采用平面法线；弯道需单独处理外侧长度与走廊交叠。
    first = np.asarray(rows[1][1:])-np.asarray(rows[0][1:])
    first /= np.linalg.norm(first)
    for a, b in zip(rows, rows[1:]):
        vector = np.asarray(b[1:])-np.asarray(a[1:])
        vector /= np.linalg.norm(vector)
        if not np.allclose(vector, first, rtol=0, atol=1e-8):
            raise ConstructionInputError("当前独立建筑物适配器要求单一直线段；转折或弯道请按真实施工边界分段复核")
    return result


def _profile(asset, alignment, metadata):
    data = asset.get("alignment") or {}
    points = data.get("profile_points")
    if not points or len(points) < 2:
        raise ConstructionInputError("缺少逐桩设计纵断面；水位不能代替渠底、管轴或基础底高程")
    values = [(finite_number(p.get("station"), "纵断面桩号"), finite_number(p.get("elevation"), "设计高程"))
              for p in points]
    if any(b[0] <= a[0] for a, b in zip(values, values[1:])):
        raise ConstructionInputError("设计纵断面桩号必须严格递增")
    if values[0][0] > alignment.start_station or values[-1][0] < alignment.end_station:
        raise ConstructionInputError("设计纵断面未覆盖完整线路，禁止端值外推")
    reference = data.get("elevation_reference")
    if metadata["reference"] == "pipe_axis" and reference == "inner_invert":
        shift = _number(asset["section"], "inner_diameter", positive=True)/2
        values = [(s, z+shift) for s, z in values]
    elif reference != metadata["reference"]:
        raise ConstructionInputError(f"设计高程含义须明确为 {metadata['reference']}，当前为 {reference}")
    return values


def _profile_at(values, station):
    positions = [v[0] for v in values]
    if station < positions[0]-1e-9 or station > positions[-1]+1e-9:
        raise ConstructionInputError("计算桩号缺少设计高程，禁止外推")
    i = min(max(bisect_right(positions, station)-1, 0), len(values)-2)
    a, b = values[i], values[i+1]
    ratio = (station-a[0])/(b[0]-a[0])
    return a[1]+ratio*(b[1]-a[1]), (b[1]-a[1])/(b[0]-a[0])


def _ground_component(interp, origin, lateral, required):
    xmin, ymin, xmax, ymax = interp._tin.get_bbox()
    corners = np.asarray([(xmin, ymin), (xmin, ymax), (xmax, ymin), (xmax, ymax)])-origin
    projections = corners @ lateral
    data = interp.section_line(origin, lateral, float(projections.min()), float(projections.max()))
    parts, current = [], []
    for point in data:
        if math.isfinite(point[1]):
            current.append(point)
        elif current:
            parts.append(current)
            current = []
    if current:
        parts.append(current)
    left, right = min(0, required[0]), max(0, required[1])
    for part in parts:
        if len(part) > 1 and part[0][0] <= left+1e-9 and part[-1][0] >= right-1e-9:
            return part
    raise ConstructionInputError("结构、工作面或目标范围存在缺测地形；禁止跨孔洞或外推")


def _ground_at(ground, offset):
    if not ground[0][0]-1e-9 <= offset <= ground[-1][0]+1e-9:
        raise ConstructionInputError("施工边坡超出有效地形范围，未生成工程量")
    return CrossSectionCalculator._get_ground_elev_at_offset(ground, offset)


def _grades(construction, side):
    stages = construction.get("excavation_stages_"+side)
    if stages is None:
        return [SlopeGrade(_number(construction, "excavation_slope_"+side, nonnegative=True), math.inf, 0)]
    if not isinstance(stages, list) or not stages:
        raise ConstructionInputError("分级开挖坡必须为非空级段列表")
    return [SlopeGrade(_number(s, "slope", nonnegative=True),
                       math.inf if i == len(stages)-1 else _number(s, "height", positive=True),
                       _number(s, "berm_width", nonnegative=True)) for i, s in enumerate(stages)]


def _dynamic_provider(tin, asset, alignment, settings):
    rings, metadata = _section_outer(asset["section_type"], asset["section"], settings["arc_segments"])
    profile = _profile(asset, alignment, metadata)
    construction = effective_construction(asset)
    mode = construction.get("target_mode")
    if mode not in TARGET_MODES:
        raise ConstructionInputError("必须明确 target_mode：恢复原地面、明确渠堤或目标土面")
    interp = TINInterpolator(tin)
    unburied = metadata["reference"] == "pipe_axis" and construction.get("installation_mode", "buried") in {"exposed", "elevated"}
    side_grades = {} if unburied else {side: _grades(construction, side) for side in ("left", "right")}
    is_channel = asset["section_type"].endswith("channel")
    is_open = is_channel and asset["section_type"] != "circular_channel"

    def provider(station):
        z, slope = _profile_at(profile, station)
        origin = np.asarray(alignment.get_xy_at_station(station))
        angle = alignment.get_tangent_angle_at_station(station)
        tangent = np.asarray([math.cos(angle), math.sin(angle)])
        tangent[np.abs(tangent) < 1e-15] = 0
        lateral = np.asarray([tangent[1], -tangent[0]])
        vertical = math.hypot(1, slope) if metadata["reference"] == "pipe_axis" else 1.0
        permanent = unary_union([Polygon([(x, zz*vertical+z) for x, zz in ring]) for ring in rings])
        p_left, p_bottom, p_right, p_top = permanent.bounds
        bedding = 0.0 if unburied else _number(construction, "bedding_thickness", nonnegative=True)
        extension = 0.0 if unburied else _number(construction, "bedding_extension", nonnegative=True)
        left = p_left-extension-(0.0 if unburied else _number(construction, "working_space_left", nonnegative=True))
        right = p_right+extension+(0.0 if unburied else _number(construction, "working_space_right", nonnegative=True))
        floor = p_bottom-bedding
        required = [left, right]
        if mode == "finished_profile":
            target_profile = construction.get("target_profile")
            if not target_profile or len(target_profile) < 2:
                raise ConstructionInputError("finished_profile 必须提供偏距递增的明确 target_profile")
            required.extend([finite_number(p[0], "目标土面偏距") for p in target_profile])
        if mode == "union_terrain":
            required.extend([p_left-_number(construction, "bank_top_width_left", nonnegative=True),
                             p_right+_number(construction, "bank_top_width_right", nonnegative=True)])
        ground = _ground_component(interp, origin, lateral, (min(required), max(required)))
        if is_channel and mode == "restore_terrain":
            heights = [_ground_at(ground, p_left), _ground_at(ground, p_right)]
            heights.extend(h for x, h in ground if p_left < x < p_right)
            if min(heights) < p_top-1e-8:
                raise ConstructionInputError("明渠存在半挖半填或露出地面；须提供明确渠堤边界 union_terrain 或目标土面 finished_profile")
        ground_low, ground_high = min(p[1] for p in ground), max(p[1] for p in ground)
        stage_top = max([floor]+[floor+sum(g.height for g in gs[:-1]) for gs in side_grades.values()])
        target_heights = [finite_number(p[1], "目标土面高程") for p in construction.get("target_profile", [])]
        provisional = {**settings, "base_z": min([floor, ground_low, *target_heights])-1,
                       "clip_top_z": max([p_top, ground_high, stage_top, *target_heights])+1}
        prepared = build_construction_section(asset, station=station, origin=[*origin, z], tangent=[*tangent, 0],
                                               settings=provisional, vertical_slope=slope)
        daylight = [left, right]
        if not unburied:
            for i, side in enumerate(("left", "right")):
                x = daylight[i]
                if _ground_at(ground, x) >= floor-1e-9:
                    trace = CrossSectionCalculator._trace_slope(x, floor, ground, side_grades[side], -1 if side == "left" else 1)
                    daylight[i] = trace[-1][0]
        soil = Polygon([(ground[0][0], provisional["base_z"]), (ground[-1][0], provisional["base_z"])]
                       +list(reversed(ground)))
        excavation = _regions(prepared["excavation"], "开挖").intersection(soil).intersection(
            box(daylight[0], provisional["base_z"], daylight[1], provisional["clip_top_z"]))
        target = _regions(prepared["target"], "目标土体")
        if mode == "union_terrain":
            crest = p_top
            crown = [p_left-_number(construction, "bank_top_width_left", nonnegative=True),
                     p_right+_number(construction, "bank_top_width_right", nonnegative=True)]
            ratios = [_number(construction, "bank_slope_"+side, nonnegative=True) for side in ("left", "right")]
            # 圆管斜轴在竖直剖面中的实际外包为椭圆，渠堤顶按真实外包顶高程。
            target = Polygon([(crown[0]-ratios[0]*(crest-provisional["base_z"]), provisional["base_z"]),
                              (crown[1]+ratios[1]*(crest-provisional["base_z"]), provisional["base_z"]),
                              (crown[1], crest), (crown[0], crest)])
            for i, side in enumerate(("left", "right")):
                if _ground_at(ground, crown[i]) < crest-1e-9:
                    ratio = ratios[i]
                    hit = CrossSectionCalculator._ray_ground_hit((crown[i], crest), ((-1 if i == 0 else 1)*ratio, -1), ground)
                    if hit is None:
                        raise ConstructionInputError("渠堤外边坡在有效地形内未接地，未生成工程量")
                    crown[i] = hit[1][0]
            target = target.intersection(box(crown[0], provisional["base_z"], crown[1], provisional["clip_top_z"]))
        measured = _regions(prepared["measured"], "垫层")
        bounds = [g.bounds for g in (excavation, permanent, measured, target) if not g.is_empty]
        x0, x1 = min(b[0] for b in bounds), max(b[2] for b in bounds)
        local_ground = [_ground_at(ground, x0), _ground_at(ground, x1)]
        local_ground.extend(h for x, h in ground if x0 < x < x1)
        top = max([max(local_ground), p_top, *(b[3] for b in bounds)])+1
        # 目标包络旧辅助底面不决定工程下界；裁到局部地面/真实槽底下方即可。
        bottom = min(min(local_ground), floor, min(target_heights or [floor]))-1
        domain = box(x0, bottom, x1, top)
        prepared.update(domain=domain, excavation=excavation.intersection(domain), permanent=permanent,
                        measured=measured, target=target.intersection(domain),
                        open_air=excavation.intersection(box(x0, p_top, x1, top)) if is_open else Polygon(),
                        independent_domain_basis="exact_fixed_TIN_daylight_and_explicit_occupancy")
        return prepared

    return provider, [s for s, _ in profile if alignment.start_station <= s <= alignment.end_station]


def _prepared_provider(tin, asset, alignment, sections):
    from ..services.independent_calculator import _prepared_at
    if len(sections) < 2:
        raise ConstructionInputError("已准备施工断面至少需要两项")
    positions = [finite_number(s.get("station"), "施工断面桩号") for s in sections]
    if any(b <= a for a, b in zip(positions, positions[1:])):
        raise ConstructionInputError("施工断面桩号必须严格递增")
    if positions[0] > alignment.start_station or positions[-1] < alignment.end_station:
        raise ConstructionInputError("已准备施工断面未覆盖完整线路")
    for s in sections:
        if s.get("coordinate_mode") != "offset_absolute_elevation":
            raise ConstructionInputError("已准备断面须明确 coordinate_mode=offset_absolute_elevation")
        if s.get("target_mode") not in TARGET_MODES:
            raise ConstructionInputError("已准备施工断面缺少明确 target_mode")
        xy = s.get("origin", [])
        if len(xy) != 3 or any(not math.isfinite(float(v)) for v in xy):
            raise ConstructionInputError("已准备断面缺少有限 origin")
        if np.linalg.norm(np.asarray(xy[:2])-np.asarray(alignment.get_xy_at_station(s["station"]))) > 1e-5:
            raise ConstructionInputError("已准备断面位置与当前线路不一致，不使用旧几何")
        angle = alignment.get_tangent_angle_at_station(s["station"])
        expected = np.asarray([math.sin(angle), -math.cos(angle)])
        lateral = s.get("lateral", [])
        if len(lateral) != 3 or not np.allclose(lateral, [*expected, 0], rtol=0, atol=1e-8):
            raise ConstructionInputError("已准备断面左右偏距方向与当前线路不一致")
        domain = _regions(s.get("domain"), "共同域")
        if domain.is_empty:
            raise ConstructionInputError("已准备施工断面必须提供有限共同域")
        for key in REGION_KEYS[1:]:
            if key not in s:
                raise ConstructionInputError(f"已准备施工断面缺少 {key}，无区域须明确给空列表")
            region = _regions(s[key], key)
            if not region.is_empty and not domain.covers(region):
                raise ConstructionInputError(f"已准备 {key} 超出共同域")
        if s["target_mode"] in {"union_terrain", "finished_profile"} and _regions(s["target"], "目标包络").is_empty:
            raise ConstructionInputError("已准备施工断面缺少明确目标土体包络")
    for a, b in zip(sections, sections[1:]):
        if a["target_mode"] != b["target_mode"]:
            raise ConstructionInputError("目标施工状态改变处须显式分段")
        for key in REGION_KEYS:
            if not isinstance(a[key], list) or not isinstance(b[key], list):
                raise ConstructionInputError("已准备几何对象不能逐顶点插值，请提供逐桩模板参数")
            if len(a[key]) != len(b[key]) or any(len(x) != len(y) for x, y in zip(a[key], b[key])):
                raise ConstructionInputError("已准备断面拓扑改变处须显式分段")
    is_channel = asset["section_type"].endswith("channel")
    interp = TINInterpolator(tin)
    def provider(station):
        value = _prepared_at(sections, station)
        angle = alignment.get_tangent_angle_at_station(station)
        value["origin"] = [*alignment.get_xy_at_station(station),
                            float(np.interp(station, positions, [s["origin"][2] for s in sections]))]
        value["tangent"] = [math.cos(angle), math.sin(angle), 0.0]
        value["lateral"] = [math.sin(angle), -math.cos(angle), 0.0]
        if all("trench_floor_z" in s for s in sections):
            value["trench_floor_z"] = float(np.interp(station, positions, [s["trench_floor_z"] for s in sections]))
        if is_channel and value["target_mode"] == "restore_terrain":
            permanent = _regions(value["permanent"], "永久占位")
            if permanent.is_empty:
                raise ConstructionInputError("明渠已准备断面缺少永久外包占位")
            left, _, right, top = permanent.bounds
            angle = alignment.get_tangent_angle_at_station(station)
            lateral = np.asarray([math.sin(angle), -math.cos(angle)])
            ground = _ground_component(interp, np.asarray(alignment.get_xy_at_station(station)), lateral, (left, right))
            heights = [_ground_at(ground, left), _ground_at(ground, right)]
            heights.extend(z for x, z in ground if left < x < right)
            if min(heights) < top-1e-8:
                raise ConstructionInputError("明渠存在半挖半填或露出地面；已准备断面仍须给明确目标土面或渠堤边界")
        return value
    return provider, positions


def prepare_asset_config(tin, asset, settings=None, **config_overrides):
    """返回 (Alignment, LinearCalculationConfig)，输入资料始终保持原值。

    辅助上下界由实际 TIN 和施工接地范围确定，不作为设计高程。
    弯道、未解析曲线、断链或不一致的断面拓扑明确拒绝，不暗中近似。
    """
    from ..services.independent_calculator import LinearCalculationConfig
    data = deepcopy(asset)
    normalize_asset_construction(data)
    if not isinstance(data, dict) or not data.get("enabled", True):
        raise ConstructionInputError("所选建筑物未纳入计算")
    if data.get("section_type") not in SECTION_TYPES:
        raise ConstructionInputError("所选建筑物没有已支持的施工模板")
    if data.get("section_variation_requires_resolution"):
        raise ConstructionInputError("来源段内断面尺寸冲突，须明确分段或统一已核定施工参数")
    options = deepcopy(settings or {})
    options.setdefault("arc_segments", 256)
    segments = finite_number(options["arc_segments"], "弧段数量 arc_segments")
    if not segments.is_integer() or not 16 <= segments <= 2048:
        raise ConstructionInputError("弧段数量 arc_segments 必须为16至2048的整数")
    options["arc_segments"] = int(segments)
    prepared = deepcopy(data.get("geometry_sections") or [])
    alignment = _alignment(data, prepared)
    if prepared:
        provider, extra = _prepared_provider(tin, data, alignment, prepared)
    else:
        provider, extra = _dynamic_provider(tin, data, alignment, options)
    # 只用真实接地范围和显式占位确定横断面初始宽度。
    keys = sorted({alignment.start_station, alignment.end_station, *extra, *(p.station for p in alignment.points)})
    key_sections = [provider(s) for s in keys]
    bounds = [_regions(s["domain"], "共同域").bounds for s in key_sections]
    kwargs = {"left_width": max(1e-6, max(-b[0] for b in bounds)),
              "right_width": max(1e-6, max(b[2] for b in bounds)),
              "initial_interval": options.get("section_max_spacing", 20.0),
              "extra_stations": extra, "geometry_section_provider": provider}
    for key in ("initial_interval", "relative_tolerance", "absolute_tolerance", "max_refinements",
                "max_sections", "include_terrain_stations"):
        if key in options:
            kwargs[key] = options[key]
    allowed = {f.name for f in fields(LinearCalculationConfig)}
    if any(k not in allowed for k in config_overrides):
        raise ConstructionInputError("未知独立算量配置："+", ".join(k for k in config_overrides if k not in allowed))
    if any(k in config_overrides for k in ("geometry_section_provider", "geometry_sections", "section", "design_profile")):
        raise ConstructionInputError("施工状态由所选建筑物资料生成，不能用配置覆盖其来源")
    kwargs.update(config_overrides)
    return alignment, LinearCalculationConfig(**kwargs)


def calculate_asset(tin, asset, settings=None, *, progress=None, cancelled=None, **config_overrides):
    """计算一项已明确施工资料的建筑物，返回独立服务结果。"""
    from ..services.independent_calculator import calculate_linear
    alignment, config = prepare_asset_config(tin, asset, settings, **config_overrides)
    result = calculate_linear(tin, alignment, config, progress=progress, cancelled=cancelled)
    result.diagnostics.append({"code": "existing_asset_adapter", "asset_id": asset.get("asset_id"),
                               "section_type": asset.get("section_type"), "is_test": bool(asset.get("is_test")),
                               "geometry_basis": "explicit_occupancy_and_fixed_TIN_sections",
                               "geometry_source": "prepared_sections" if asset.get("geometry_sections") else "construction_templates",
                               "curved_outline_segments": None if asset.get("geometry_sections") else int((settings or {}).get("arc_segments", 256)),
                               "curved_outline_is_polygonal": "circular" in asset.get("section_type", "")
                                   or asset.get("section_type") in {"u_channel", "arch_culvert"}})
    return result
