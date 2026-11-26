# -*- coding: utf-8 -*-
"""独立工程量服务：已有 TIN → 精确断面/施工状态 → 可复核分段量。

不调用 Rhino，也不将水力净空尺寸推定为施工断面。地形可以来自
Rhino 原生网格；其既有三角片拓扑始终保留。部分结果和取消结果
不作为成功结果返回。
"""
from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from dataclasses import dataclass, field
import math
from typing import Callable

import numpy as np
from shapely.geometry import Polygon, MultiPolygon, box, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from ..core.construction_geometry import compute_construction_state, ConstructionStateResult
from ..core.cross_section import CrossSectionCalculator, signed_line_areas, _validated_line
from ..core.profile_cutter import ProfileCutter
from ..core.tin_interpolator import TINInterpolator
from ..core.volume_calculator import VolumeCalculator
from ..core.site_excavation import SiteExcavationConfig, SiteExcavationResult, calculate_site
from ..models.alignment import Alignment
from ..models.section import DesignProfile, ExcavationSlope, CrossSectionData, SectionAreaResult, VolumeResult
from ..models.terrain import TINModel


class IndependentCalculationError(ValueError):
    def __init__(self, message, *, code="invalid_input", diagnostics=None):
        super().__init__(message)
        self.code = code
        self.diagnostics = list(diagnostics or [])


@dataclass
class ConstructionSection:
    """施工开挖线参数，所有高程均相对明确的施工底标高。

    rectangular_trench 从施工槽底放坡，bottom_width 已包含工作空间。
    trapezoidal_channel 的 height 为施工断面肩高，之后接独立开挖坡。
    explicit_surface 为完整左右施工面；可计算差分挖填但不推定渠堤。
    """
    section_type: str = "trapezoidal_channel"
    bottom_width: float = 0.0
    height: float = 0.0
    left_ratio: float = 1.0
    right_ratio: float = 1.0
    relative_points: list[tuple[float, float]] | None = None

    def points_at(self, bottom_elevation):
        if self.section_type == "explicit_surface":
            if self.relative_points is None:
                raise IndependentCalculationError("显式施工面缺少偏距/相对高程折线")
            return _validated_line([(x, z+bottom_elevation) for x, z in self.relative_points],
                                   "显式施工面", allow_vertical=True)
        values = [self.bottom_width, self.height, self.left_ratio, self.right_ratio, bottom_elevation]
        if any(not math.isfinite(v) for v in values) or self.bottom_width <= 0:
            raise IndependentCalculationError("施工底宽及断面参数必须是有限有效数值")
        if self.section_type == "rectangular_trench":
            return [(-self.bottom_width/2, bottom_elevation), (self.bottom_width/2, bottom_elevation)]
        if self.section_type != "trapezoidal_channel" or self.height <= 0 or min(self.left_ratio, self.right_ratio) < 0:
            raise IndependentCalculationError("施工断面类型或梯形尺寸无效")
        b, h = self.bottom_width, self.height
        return [(-b/2-self.left_ratio*h, bottom_elevation+h), (-b/2, bottom_elevation),
                (b/2, bottom_elevation), (b/2+self.right_ratio*h, bottom_elevation+h)]


@dataclass
class LinearCalculationConfig:
    design_profile: DesignProfile | None = None
    section: ConstructionSection | None = None
    slope_config: ExcavationSlope | None = None
    left_width: float = 30.0
    right_width: float = 30.0
    initial_interval: float = 20.0
    relative_tolerance: float = 0.001
    absolute_tolerance: float = 0.1
    max_refinements: int = 8
    max_sections: int = 50_000
    extra_stations: list[float] = field(default_factory=list)
    include_terrain_stations: bool = True
    geometry_section_provider: Callable[[float], dict] | None = None
    geometry_sections: list[dict] | None = None


@dataclass
class LinearAreaRecord:
    station: float
    excavation_area: float
    surface_fill_area: float | None
    backfill_area: float | None
    embankment_area: float | None

    def vector(self):
        return np.asarray([self.excavation_area, self.surface_fill_area or 0.0,
                           self.backfill_area or 0.0, self.embankment_area or 0.0])


@dataclass
class LinearCalculationResult:
    excavation_volume: float
    surface_fill_volume: float | None
    backfill_volume: float | None
    embankment_volume: float | None
    sections: list[CrossSectionData]
    mid_sections: list[CrossSectionData]
    area_records: list[LinearAreaRecord]
    volume_result: VolumeResult
    convergence_history: list[dict]
    diagnostics: list[dict]
    section_states: dict[float, ConstructionStateResult] = field(default_factory=dict)
    terrain_metadata: dict = field(default_factory=dict)
    calculation_input: dict = field(default_factory=dict)
    converged: bool = True
    integration_method: str = "exact_tin_sections_actual_midpoint_simpson"

    @property
    def segments(self):
        return self.volume_result.segments

    @property
    def fill_volume(self):
        return self.surface_fill_volume if self.surface_fill_volume is not None else self.total_fill_volume

    @property
    def total_fill_volume(self):
        if self.backfill_volume is None or self.embankment_volume is None:
            return None
        return self.backfill_volume+self.embankment_volume

    def to_dict(self):
        areas = {record.station: record for record in self.area_records}
        def serialize_section(section):
            record = areas[section.station]
            return {"station": section.station, "ground_points": section.ground_points,
                    "design_points": section.design_points,
                    "excavation_boundary": section.excavation_boundary,
                    "left_width": section.left_width, "right_width": section.right_width,
                    "area_result": {**section.area_result.__dict__,
                        "surface_fill_area": record.surface_fill_area,
                        "backfill_area": record.backfill_area, "embankment_area": record.embankment_area},
                    "construction_regions": None if section.station not in self.section_states else {
                        "excavation": mapping(self.section_states[section.station].excavation),
                        "backfill": mapping(self.section_states[section.station].backfill),
                        "embankment": mapping(self.section_states[section.station].embankment),
                        "excluded_occupancy": mapping(self.section_states[section.station].excluded_occupancy)}}
        quantities = {"excavation_volume": self.excavation_volume,
                "surface_fill_volume": self.surface_fill_volume, "backfill_volume": self.backfill_volume,
                "embankment_volume": self.embankment_volume, "total_fill_volume": self.total_fill_volume}
        segment_rows = []
        for segment, middle in zip(self.segments, self.mid_sections):
            a, m, b = areas[segment.station_start], areas[middle.station], areas[segment.station_end]
            amount = (segment.length/6)*(a.vector()+4*m.vector()+b.vector())
            segment_rows.append({**segment.__dict__, "start_station": segment.station_start,
                "end_station": segment.station_end, "mid_station": middle.station,
                "excavation_volume": float(amount[0]),
                "surface_fill_volume": None if self.surface_fill_volume is None else float(amount[1]),
                "backfill_volume": None if self.backfill_volume is None else float(amount[2]),
                "embankment_volume": None if self.embankment_volume is None else float(amount[3]),
                "total_fill_volume": None if self.total_fill_volume is None else float(amount[2]+amount[3]),
                "fill_volume": segment.fill_prismatoid})
        return {"schema": "1.0", "kind": "linear", **quantities, "quantities": quantities,
                "converged": self.converged,
                "terrain_metadata": self.terrain_metadata, "calculation_input": self.calculation_input,
                "integration_method": self.integration_method,
                "convergence_history": self.convergence_history, "diagnostics": self.diagnostics,
                "section_count": len(self.sections), "mid_section_count": len(self.mid_sections),
                "areas": [record.__dict__.copy() for record in self.area_records],
                "sections": [serialize_section(section) for section in self.sections],
                "mid_sections": [serialize_section(section) for section in self.mid_sections],
                "segments": segment_rows}


def _cancel(cancelled):
    if cancelled is not None and cancelled():
        raise IndependentCalculationError("计算已取消，未发布工程量结果", code="cancelled")


def _notify(progress, stage, fraction, message):
    if progress is not None:
        progress(stage, min(1.0, max(0.0, float(fraction))), message)


def _regions(value, name):
    if isinstance(value, (Polygon, MultiPolygon)):
        result = value
    else:
        try:
            parts = [Polygon(ring) for ring in (value or [])]
        except (TypeError, ValueError) as exc:
            raise IndependentCalculationError(f"{name}区域格式错误") from exc
        if any(not part.is_valid or part.has_z for part in parts):
            raise IndependentCalculationError(f"{name}存在无效或三维多边形")
        result = unary_union(parts) if parts else Polygon()
    if result.has_z or not result.is_valid or not math.isfinite(result.area):
        raise IndependentCalculationError(f"{name}必须是有效二维区域")
    return result


def _prepared_at(sections, station):
    """已明确准备的状态只在相同逐环拓扑之间插值，不自动匹配顶点。"""
    positions = [float(section["station"]) for section in sections]
    if station < positions[0]-1e-8 or station > positions[-1]+1e-8:
        raise IndependentCalculationError(f"桩号 {station:.6g} 缺少施工断面", code="missing_design")
    for position, section in zip(positions, sections):
        if abs(station-position) <= 1e-9:
            return deepcopy(section)
    index = bisect_right(positions, station)-1
    a, b = sections[index], sections[index+1]
    if a.get("target_mode") != b.get("target_mode"):
        raise IndependentCalculationError("目标施工状态变化处须分段，禁止跨状态插值", code="incompatible_sections")
    fraction = (station-positions[index])/(positions[index+1]-positions[index])
    result = deepcopy(a)
    for key in ("domain", "excavation", "target", "permanent", "measured", "open_air"):
        first, second = a.get(key, []), b.get(key, [])
        if isinstance(first, BaseGeometry) or isinstance(second, BaseGeometry):
            raise IndependentCalculationError("几何对象断面插值须提供逐桩生成provider", code="incompatible_sections")
        if len(first) != len(second) or any(len(x) != len(y) for x, y in zip(first, second)):
            raise IndependentCalculationError(f"{key}断面拓扑变化；须分段或提供逐桩生成provider", code="incompatible_sections")
        result[key] = [[[(1-fraction)*float(u)+(fraction)*float(v) for u, v in zip(p, q)]
                         for p, q in zip(x, y)] for x, y in zip(first, second)]
    if "origin" in a and "origin" in b:
        result["origin"] = [(1-fraction)*float(u)+fraction*float(v) for u, v in zip(a["origin"], b["origin"])]
    if "trench_floor_z" in a and "trench_floor_z" in b:
        result["trench_floor_z"] = (1-fraction)*float(a["trench_floor_z"])+fraction*float(b["trench_floor_z"])
    result["station"] = float(station)
    return result


def _construction_state(section, prepared):
    domain = _regions(prepared.get("domain"), "共同计算域")
    if domain.is_empty:
        raise IndependentCalculationError("显式施工断面必须给定有限共同计算域")
    x0, bottom, x1, top = domain.bounds
    ground = _validated_line(section.ground_points, "地面线")
    if ground[0][0] > x0+1e-9 or ground[-1][0] < x1-1e-9:
        raise IndependentCalculationError("地形断面未覆盖施工共同域", code="missing_terrain")
    center = CrossSectionCalculator._get_ground_elev_at_offset(ground, 0.0)
    cropped = [(x0, CrossSectionCalculator._get_ground_elev_at_offset(ground, x0))]
    cropped.extend(p for p in ground if x0 < p[0] < x1)
    cropped.append((x1, CrossSectionCalculator._get_ground_elev_at_offset(ground, x1)))
    if any(z < bottom-1e-9 or z > top+1e-9 for _, z in cropped):
        raise IndependentCalculationError("共同域上下界未完整覆盖真实地面", code="invalid_domain")
    soil = Polygon([(x0, bottom), (x1, bottom)]+list(reversed(cropped))).intersection(domain)
    shapes = {}
    for key, name in (("excavation", "开挖包络"), ("permanent", "永久外包占位"),
                      ("measured", "另列材料占位"), ("open_air", "开敞区域"), ("target", "目标土体包络")):
        shape = _regions(prepared.get(key), name)
        if shape.difference(domain).area > 1e-9:
            raise IndependentCalculationError(f"{name}超出有限计算域；禁止裁掉真实施工边界后算量", code="invalid_domain")
        shapes[key] = shape.intersection(domain)
    excavation, permanent, measured = shapes["excavation"], shapes["permanent"], shapes["measured"]
    open_air, target = shapes["open_air"], shapes["target"]
    mode = prepared.get("target_mode")
    if mode == "restore_terrain":
        target = soil
    elif mode == "union_terrain":
        target = unary_union([soil, target])
    elif mode != "finished_profile":
        raise IndependentCalculationError("显式断面须明确 target_mode")
    target = target.difference(open_air)
    state = compute_construction_state(soil, excavation, target, permanent, measured)
    floor = float(excavation.bounds[1]) if not excavation.is_empty else float(
        prepared.get("trench_floor_z", prepared.get("origin", [0, 0, bottom])[2]))
    section.design_points = []
    if not state.excavation.is_empty:
        largest = state.excavation if isinstance(state.excavation, Polygon) else max(state.excavation.geoms, key=lambda p: p.area)
        section.excavation_boundary = list(largest.exterior.coords)
    section.area_result = SectionAreaResult(section.station, state.excavation_area, fill_area=state.fill_area,
        backfill_area=state.backfill_area, embankment_area=state.embankment_area,
        excavation_width=0.0 if state.excavation.is_empty else state.excavation.bounds[2]-state.excavation.bounds[0],
        ground_elevation_center=center, design_invert_elevation=floor, cut_depth=center-floor)
    return state


def _validate_linear(alignment, config):
    if not isinstance(alignment, Alignment) or alignment.total_length <= 0:
        raise IndependentCalculationError("必须给定正长度中心线")
    points = alignment.points
    if any(not math.isfinite(v) for p in points for v in (p.x, p.y, p.station)):
        raise IndependentCalculationError("中心线坐标和桩号必须有限")
    if any(b.station <= a.station or math.hypot(b.x-a.x, b.y-a.y) <= 0 for a, b in zip(points, points[1:])):
        raise IndependentCalculationError("中心线桩号必须递增且不得含零长度段")
    first = np.asarray([points[1].x-points[0].x, points[1].y-points[0].y], dtype=float)
    first /= np.linalg.norm(first)
    for a, b in zip(points, points[1:]):
        chord, length = math.hypot(b.x-a.x, b.y-a.y), b.station-a.station
        if not math.isclose(length, chord, rel_tol=1e-8, abs_tol=1e-5):
            raise IndependentCalculationError("中心线里程与平面弦长不符；曲线或空间曲线须独立处理，不能用跳号或弧长乘直线断面",
                                              code="unsupported_alignment")
        direction = np.asarray([b.x-a.x, b.y-a.y], dtype=float)/chord
        if not np.allclose(direction, first, rtol=0, atol=1e-8):
            raise IndependentCalculationError(
                "独立断面算量仅支持共向共线的单一直线段；回折、转折、自交及曲线须按真实施工范围另行计算，防止同一沟槽重复计量",
                code="unsupported_alignment")
    if getattr(alignment, "_breaks", []):
        raise IndependentCalculationError("算量使用连续里程；断链须先明确映射，不能直接用跳号作为长度")
    for value in (config.left_width, config.right_width, config.initial_interval):
        if not math.isfinite(value) or value <= 0:
            raise IndependentCalculationError("断面左右宽度和起始间距必须为正数")
    for value in (config.relative_tolerance, config.absolute_tolerance):
        if not math.isfinite(value) or value < 0:
            raise IndependentCalculationError("误差容差必须是非负有限值")
    if config.relative_tolerance == config.absolute_tolerance == 0:
        raise IndependentCalculationError("至少给定一个正的误差容差")
    if not isinstance(config.max_refinements, int) or config.max_refinements < 1 or config.max_sections < 5:
        raise IndependentCalculationError("细化次数和最大断面数量无效")
    explicit = config.geometry_section_provider is not None or bool(config.geometry_sections)
    if not explicit and (config.section is None or config.design_profile is None):
        raise IndependentCalculationError("必须给定施工断面和施工底标高纵断面")
    if config.geometry_sections:
        values = [float(s["station"]) for s in config.geometry_sections]
        if len(values) < 2 or any(not math.isfinite(v) for v in values) or any(b <= a for a, b in zip(values, values[1:])):
            raise IndependentCalculationError("施工断面列表须按有限桩号递增且至少含起终断面")
    if not explicit and config.section.section_type != "explicit_surface":
        slope = config.slope_config
        if slope is None or slope.platform_enabled:
            raise IndependentCalculationError("自动接地面模式须明确左右放坡；施工便道须使用显式施工区域")
        if slope.start_station > alignment.start_station+1e-8 or slope.end_station < alignment.end_station-1e-8:
            raise IndependentCalculationError("放坡配置未覆盖完整线路", code="missing_design")
        for grades in (slope.left_grades, slope.right_grades):
            for i, grade in enumerate(grades):
                if (not math.isfinite(grade.ratio) or grade.ratio < 0 or math.isnan(grade.height) or grade.height <= 0
                        or not math.isfinite(grade.berm_width) or grade.berm_width < 0
                        or (math.isinf(grade.height) and i != len(grades)-1)):
                    raise IndependentCalculationError("分级放坡参数无效")
    return explicit


def _profile_at(profile, station):
    if profile.station_elevation_table:
        positions = sorted(profile.station_elevation_table)
        if station < positions[0]-1e-9 or station > positions[-1]+1e-9:
            raise IndependentCalculationError(f"桩号 {station:.6g} 缺少施工底标高；禁止端值外推", code="missing_design")
    value = profile.get_invert_at_station(station)
    if value is None or not math.isfinite(value):
        raise IndependentCalculationError(f"桩号 {station:.6g} 缺少有效施工底标高", code="missing_design")
    return float(value)


def _terrain_stations(tin, alignment, config, cancelled):
    """真实 TIN 顶点投影里程补入起始分段，防止均匀采样漏过窄地形峰。"""
    points = np.asarray(tin.points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise IndependentCalculationError("地形顶点无效", code="invalid_terrain")
    plan = np.asarray([(p.x, p.y) for p in alignment.points])
    width = max(config.left_width, config.right_width)
    minimum, maximum = plan.min(axis=0)-width, plan.max(axis=0)+width
    # 横穿线路的长边，其端点可能都在剖切宽度之外；仅按顶点距离
    # 筛选会漏掉细山脊。先筛与工程包围范围相交的三角片，再用其顶点。
    indices = np.asarray(tin.triangles)
    selected_indices = []
    for begin in range(0, len(indices), 50_000):
        _cancel(cancelled)
        chunk = indices[begin:begin+50_000]
        corners = points[chunk, :2]
        lows, highs = corners.min(axis=1), corners.max(axis=1)
        relevant = np.all((lows <= maximum) & (highs >= minimum), axis=1)
        if np.any(relevant):
            selected_indices.append(chunk[relevant].ravel())
    selected = points[np.unique(np.concatenate(selected_indices)), :2] if selected_indices else np.empty((0, 2))
    best_distance = np.full(len(selected), np.inf)
    stations = np.zeros(len(selected))
    for i, (a, b) in enumerate(zip(plan, plan[1:])):
        _cancel(cancelled)
        direction = b-a
        fractions = np.clip((selected-a) @ direction / float(direction @ direction), 0, 1)
        distances = np.sum((selected-(a+fractions[:, None]*direction))**2, axis=1)
        closer = distances < best_distance
        stations[closer] = alignment.points[i].station + fractions[closer]*(alignment.points[i+1].station-alignment.points[i].station)
        best_distance[closer] = distances[closer]
    return [float(s) for s in np.unique(stations)
            if alignment.start_station+1e-7 < s < alignment.end_station-1e-7]


def calculate_linear(tin: TINModel, alignment: Alignment, config: LinearCalculationConfig, *,
                     progress: Callable | None = None,
                     cancelled: Callable[[], bool] | None = None) -> LinearCalculationResult:
    explicit = _validate_linear(alignment, config)
    _cancel(cancelled)
    _notify(progress, "terrain", 0, "准备保留已有三角片拓扑的精确断面索引")
    try:
        cutter = ProfileCutter(TINInterpolator(tin))
    except ValueError as exc:
        raise IndependentCalculationError(str(exc), code="invalid_terrain") from exc
    start, end = alignment.start_station, alignment.end_station
    stations = {start, end, *(p.station for p in alignment.points)}
    stations.update(float(s) for s in np.arange(start, end, config.initial_interval))
    for value in config.extra_stations:
        if not math.isfinite(value) or not start <= value <= end:
            raise IndependentCalculationError("额外桩号必须为线路内的有限值")
        stations.add(float(value))
    if config.design_profile:
        stations.update(float(s) for s in config.design_profile.station_elevation_table if start < s < end)
        for segment in config.design_profile.segments:
            stations.update(s for s in (segment.start_station, segment.end_station) if start < s < end)
    if config.geometry_sections:
        stations.update(float(s["station"]) for s in config.geometry_sections if start < float(s["station"]) < end)
    if config.include_terrain_stations:
        stations.update(_terrain_stations(tin, alignment, config, cancelled))
    ordered = sorted(stations)
    stations = [ordered[0]]
    for value in ordered[1:]:
        if value-stations[-1] > 1e-7:
            stations.append(value)
    if stations[-1] != end:
        stations[-1] = end
    if len(stations) > config.max_sections:
        raise IndependentCalculationError("真实地形关键桩号超过断面上限；请缩小工程段或明确提高上限", code="section_limit")
    cache, records, states = {}, {}, {}
    history = []

    def cut(station):
        _cancel(cancelled)
        if station in cache:
            return cache[station]
        if len(cache) >= config.max_sections:
            raise IndependentCalculationError("已达最大断面数但尚未收敛，未发布工程量结果", code="section_limit", diagnostics=history)
        prepared = None
        if explicit:
            prepared = config.geometry_section_provider(station) if config.geometry_section_provider else _prepared_at(config.geometry_sections, station)
            if not isinstance(prepared, dict):
                raise IndependentCalculationError("施工断面provider必须返回已准备字典")
            domain = _regions(prepared.get("domain"), "施工域")
            if domain.is_empty:
                raise IndependentCalculationError("施工域不能为空")
            left = max(config.left_width, max(0, -domain.bounds[0]))
            right = max(config.right_width, max(0, domain.bounds[2]))
        else:
            left, right = config.left_width, config.right_width
        try:
            # 索引精确剖切已有 TIN，不以显示采样间距控制工程面积精度。
            section = cutter.cut_cross_section(alignment, station, left, right, sample_step=0.5)
            if any(not math.isfinite(v) for p in section.ground_points for v in p):
                raise IndependentCalculationError(f"桩号 {station:.6g} 断面存在缺测地形；禁止跨孔洞或外推", code="missing_terrain")
            if explicit:
                state = _construction_state(section, prepared)
                states[station] = state
                record = LinearAreaRecord(station, state.excavation_area, None, state.backfill_area, state.embankment_area)
            else:
                elevation = _profile_at(config.design_profile, station)
                design = config.section.points_at(elevation)
                difference = signed_line_areas(section.ground_points, design)
                if config.section.section_type == "explicit_surface":
                    area = difference.excavation_area
                    section.design_points = design
                    section.area_result = SectionAreaResult(station, area, fill_area=difference.fill_area,
                        ground_elevation_center=CrossSectionCalculator._get_ground_elev_at_offset(section.ground_points, 0),
                        design_invert_elevation=elevation)
                else:
                    if difference.fill_area > 1e-9:
                        raise IndependentCalculationError("半挖半填断面需要完整显式施工面或施工状态，不推定渠堤和回填边界",
                                                          code="missing_construction_state")
                    boundary = CrossSectionCalculator._build_excavation_boundary(design, section.ground_points, config.slope_config, elevation)
                    shape = Polygon(boundary)
                    area = float(shape.area)
                    section.design_points, section.excavation_boundary = design, boundary
                    section.area_result = SectionAreaResult(station, area, fill_area=0.0,
                        excavation_width=shape.bounds[2]-shape.bounds[0],
                        ground_elevation_center=CrossSectionCalculator._get_ground_elev_at_offset(section.ground_points, 0),
                        design_invert_elevation=elevation)
                record = LinearAreaRecord(station, area, difference.fill_area if config.section.section_type == "explicit_surface" else 0.0, None, None)
        except IndependentCalculationError:
            raise
        except ValueError as exc:
            raise IndependentCalculationError(f"桩号 {station:.6g}：{exc}", code="invalid_section",
                diagnostics=[{"station": station, "message": str(exc)}]) from exc
        if any(not math.isfinite(v) or v < 0 for v in record.vector()):
            raise IndependentCalculationError("断面结果包含无效面积", code="invalid_section")
        cache[station], records[station] = section, record
        if len(cache) % 16 == 0:
            _notify(progress, "sections", min(.95, len(cache)/config.max_sections), f"已完成 {len(cache)} 个真实断面")
        return section

    previous_segments = None
    previous_stations = None
    for refinement in range(config.max_refinements+1):
        _cancel(cancelled)
        midpoints = [(a+b)/2 for a, b in zip(stations, stations[1:])]
        for station in sorted(set(stations+midpoints)):
            cut(station)
        contributions = [((b-a)/6)*(records[a].vector()+4*records[m].vector()+records[b].vector())
                         for a, m, b in zip(stations, midpoints, stations[1:])]
        totals = np.asarray([math.fsum(v[i] for v in contributions) for i in range(4)])
        tolerances = config.absolute_tolerance+config.relative_tolerance*totals
        change = None
        if previous_segments is not None:
            locations = {station: i for i, station in enumerate(stations)}
            changes = [np.abs(np.sum(contributions[locations[a]:locations[b]], axis=0)-previous_segments[i])
                       for i, (a, b) in enumerate(zip(previous_stations, previous_stations[1:]))]
            change = np.asarray([math.fsum(v[i] for v in changes) for i in range(4)])
        history.append({"refinement": refinement, "section_count": len(stations), "mid_section_count": len(midpoints),
                        "excavation_volume": float(totals[0]), "surface_fill_volume": None if explicit else float(totals[1]),
                        "backfill_volume": float(totals[2]) if explicit else None,
                        "embankment_volume": float(totals[3]) if explicit else None,
                        "successive_change": None if change is None else change.tolist(), "tolerance": tolerances.tolist()})
        _notify(progress, "convergence", (refinement+1)/(config.max_refinements+1), f"断面间距细化 {refinement+1}，检查逐段挖填收敛")
        if change is not None and np.all(change <= tolerances):
            break
        previous_segments, previous_stations = contributions, stations
        # 数值上极短的关键分段保留，不反复对其二分至桩号容差以下。
        stations = sorted(stations+[m for a, m, b in zip(stations, midpoints, stations[1:]) if b-a > 1e-5])
    else:
        raise IndependentCalculationError("真实中点断面细化未达到指定误差，未发布工程量结果",
                                          code="not_converged", diagnostics=history)
    _cancel(cancelled)
    final = [cache[s] for s in stations]
    mids = [cache[s] for s in midpoints]
    volume_result = VolumeCalculator().compute_prismatoid_precise(final, mids, alignment)
    diagnostics = [{"code": "complete_sections", "message": "所有输出断面及真实中点均有完整地形覆盖；未跨越缺测区"},
                   {"code": "fill_semantics", "message": "显式施工状态分别计回填和新增填筑" if explicit
                    else "表面差填方与施工回填不同；未提供施工状态时不输出回填量"},
                   {"code": "station_basis", "message": "已核验共向共线单一直线；各连续里程差与平面弦长一致"}]
    _notify(progress, "complete", 1, "断面算量及误差收敛检查完成")
    calculation_input = {"alignment": [{"station": p.station, "x": p.x, "y": p.y} for p in alignment.points],
        "section": None if config.section is None else deepcopy(config.section.__dict__),
        "design_profile": None if config.design_profile is None else {
            "station_elevation_table": deepcopy(config.design_profile.station_elevation_table),
            "segments": [deepcopy(segment.__dict__) for segment in config.design_profile.segments]},
        "left_width": config.left_width, "right_width": config.right_width,
        "initial_interval": config.initial_interval, "relative_tolerance": config.relative_tolerance,
        "absolute_tolerance": config.absolute_tolerance, "include_terrain_stations": config.include_terrain_stations,
        "construction_mode": "explicit_states" if explicit else "construction_surface",
        "slope_config": None if config.slope_config is None else {
            side: [{"ratio": grade.ratio, "height": None if math.isinf(grade.height) else grade.height,
                    "to_ground": math.isinf(grade.height), "berm_width": grade.berm_width}
                   for grade in getattr(config.slope_config, side)] for side in ("left_grades", "right_grades")}}
    return LinearCalculationResult(float(totals[0]), None if explicit else float(totals[1]),
        float(totals[2]) if explicit else None, float(totals[3]) if explicit else None,
        final, mids, [records[s] for s in sorted(records)], volume_result, history, diagnostics, states,
        deepcopy(getattr(tin, "import_report", {})), calculation_input)
