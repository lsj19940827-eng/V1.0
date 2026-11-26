# -*- coding: utf-8 -*-
"""有限测量范围内的放坡基坑算量，不构造或相减三维实体。

底边界为施工开挖底面，孔洞表示明确排除的区域。每一级边坡采用
GEOS 的直线斜接偏移；马道在该级顶高程处形成水平平台。开挖量由
逐地形三角片裁切后的水平层面积积分，保留原 TIN 拓扑及高程。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
import math
from typing import Callable

import numpy as np
import shapely
from shapely.affinity import translate
from shapely.geometry import Polygon, MultiPolygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from ..models.section import SlopeGrade
from ..models.terrain import TINModel


class SiteExcavationError(ValueError):
    def __init__(self, message, *, code="invalid_input", diagnostics=None):
        super().__init__(message)
        self.code = code
        self.diagnostics = list(diagnostics or [])


@dataclass
class SiteExcavationConfig:
    bottom_boundary: BaseGeometry
    bottom_elevation: float
    grades: list[SlopeGrade]
    relative_tolerance: float = 0.001
    absolute_tolerance: float = 0.1
    max_refinements: int = 8
    max_evaluations: int = 100_000
    # 孔洞是排除区；不得通过填洞或凸包改变用户给定计算范围。
    excluded_regions: BaseGeometry | None = None


@dataclass
class SiteExcavationResult:
    excavation_volume: float
    surface_fill_volume: float
    bottom_area: float
    calculation_area: float
    terrain_triangle_count: int
    bottom_boundary: BaseGeometry
    calculation_boundary: BaseGeometry
    convergence_history: list[dict] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)
    terrain_metadata: dict = field(default_factory=dict)
    calculation_input: dict = field(default_factory=dict)
    converged: bool = True
    backfill_volume: None = None
    embankment_volume: None = None
    integration_method: str = "tin_horizontal_layers_simpson"

    def to_dict(self):
        quantities = {"excavation_volume": self.excavation_volume,
                "surface_fill_volume": self.surface_fill_volume,
                "backfill_volume": None, "embankment_volume": None}
        return {"schema": "1.0", "kind": "site", **quantities, "quantities": quantities,
                "terrain_metadata": self.terrain_metadata, "calculation_input": self.calculation_input,
                "bottom_area": self.bottom_area, "calculation_area": self.calculation_area,
                "terrain_triangle_count": self.terrain_triangle_count,
                "bottom_boundary": mapping(self.bottom_boundary),
                "calculation_boundary": mapping(self.calculation_boundary),
                "converged": self.converged, "integration_method": self.integration_method,
                "convergence_history": self.convergence_history,
                "diagnostics": self.diagnostics,
                "fill_semantics": "bottom_surface_difference_only_not_construction_backfill"}


def _check_cancel(cancelled):
    if cancelled is not None and cancelled():
        raise SiteExcavationError("计算已取消，未发布工程量结果", code="cancelled")


def _progress(callback, stage, fraction, message):
    if callback is not None:
        callback(stage, max(0.0, min(1.0, float(fraction))), message)


def _region(region, name, *, empty=False):
    if not isinstance(region, (Polygon, MultiPolygon)):
        raise SiteExcavationError(f"{name}必须是 Polygon 或 MultiPolygon")
    if region.has_z or not region.is_valid or (region.is_empty and not empty):
        raise SiteExcavationError(f"{name}必须为有效的二维多边形，不自动修复或填洞")
    for part in ([region] if isinstance(region, Polygon) else region.geoms):
        if part.is_empty:
            continue
        for ring in [part.exterior, *part.interiors]:
            if any(not math.isfinite(v) for point in ring.coords for v in point):
                raise SiteExcavationError(f"{name}含非有限坐标")
    return region


def _validate_config(config):
    _region(config.bottom_boundary, "开挖底边界")
    if not math.isfinite(config.bottom_elevation):
        raise SiteExcavationError("开挖底标高必须为有限值")
    if not config.grades:
        raise SiteExcavationError("必须明确各级放坡及最后一级至地面的坡率")
    for i, grade in enumerate(config.grades):
        if (not math.isfinite(grade.ratio) or grade.ratio < 0
                or not math.isfinite(grade.berm_width) or grade.berm_width < 0
                or math.isnan(grade.height) or grade.height <= 0):
            raise SiteExcavationError("坡率、分级高度和马道参数无效")
        if math.isinf(grade.height) and (i != len(config.grades)-1 or grade.berm_width != 0):
            raise SiteExcavationError("无限高边坡只能作为无马道的最后一级")
    if not math.isinf(config.grades[-1].height):
        raise SiteExcavationError("最后一级边坡须明确延伸到地面（height=inf）")
    for value in (config.relative_tolerance, config.absolute_tolerance):
        if not math.isfinite(value) or value < 0:
            raise SiteExcavationError("收敛容差必须是非负有限值")
    if config.relative_tolerance == config.absolute_tolerance == 0:
        raise SiteExcavationError("至少设置一个正的收敛容差")
    if (not isinstance(config.max_refinements, int) or config.max_refinements < 1
            or not isinstance(config.max_evaluations, int) or config.max_evaluations < 5):
        raise SiteExcavationError("细化次数和积分求值上限无效")
    if config.excluded_regions is not None:
        _region(config.excluded_regions, "排除区域", empty=True)


def _offset_for_height(grades, height, *, upper_side=True):
    """马道的上侧与下侧偏移独立；积分不跨越平台的面积跳变。"""
    accumulated_height = offset = 0.0
    for grade in grades:
        top = accumulated_height + grade.height
        if height < top or (height == top and not upper_side):
            return offset + grade.ratio * (height-accumulated_height)
        offset += grade.ratio * grade.height + grade.berm_width
        accumulated_height = top
    raise SiteExcavationError("分级边坡未覆盖积分高程")


def _clip_triangle(points, level, *, above=True):
    """在单个已有线性三角片内按水平高程裁切，保留真实边交点。"""
    clipped = []
    previous = points[-1]
    before = previous[2] >= level if above else previous[2] <= level
    for current in points:
        inside = current[2] >= level if above else current[2] <= level
        if before != inside:
            t = (level-previous[2]) / (current[2]-previous[2])
            crossing = previous + t*(current-previous)
            clipped.append((float(crossing[0]), float(crossing[1])))
        if inside:
            clipped.append((float(current[0]), float(current[1])))
        previous, before = current, inside
    return Polygon(clipped) if len(clipped) >= 3 else Polygon()


class _TerrainFaces:
    def __init__(self, tin, footprint, origin, cancelled, progress):
        points, indices = np.asarray(tin.points, dtype=float), np.asarray(tin.triangles)
        if (points.ndim != 2 or points.shape[1] != 3 or len(points) == 0
                or not np.isfinite(points).all() or indices.ndim != 2
                or indices.shape[1] != 3 or len(indices) == 0
                or not np.issubdtype(indices.dtype, np.integer)
                or np.any(indices < 0) or np.any(indices >= len(points))):
            raise SiteExcavationError("地形顶点或三角面索引无效", code="invalid_terrain")
        xmin, ymin, xmax, ymax = footprint.bounds
        self.polygons, self.corners, self.gradients = [], [], []
        for begin in range(0, len(indices), 50_000):
            _check_cancel(cancelled)
            corners = points[indices[begin:begin+50_000]].copy()
            corners[:, :, :2] -= origin
            lows, highs = corners[:, :, :2].min(axis=1), corners[:, :, :2].max(axis=1)
            relevant = ((lows[:, 0] <= xmax) & (highs[:, 0] >= xmin)
                        & (lows[:, 1] <= ymax) & (highs[:, 1] >= ymin))
            for face in corners[relevant]:
                polygon = Polygon(face[:, :2])
                if polygon.is_empty or polygon.area <= 0 or not polygon.is_valid:
                    raise SiteExcavationError("计算范围内含退化地形面", code="invalid_terrain")
                if not polygon.intersects(footprint):
                    continue
                delta = face[1:, :2]-face[0, :2]
                try:
                    gradient = np.linalg.solve(delta, face[1:, 2]-face[0, 2])
                except np.linalg.LinAlgError as exc:
                    raise SiteExcavationError("地形面方程无效", code="invalid_terrain") from exc
                self.polygons.append(polygon)
                self.corners.append(face)
                self.gradients.append(gradient)
            _progress(progress, "terrain", min(1, (begin+50_000)/len(indices)), "筛选基坑范围内的已有地形三角片")
        if not self.polygons:
            raise SiteExcavationError("开挖范围内没有有效地形", code="missing_terrain")
        self.polygons = np.asarray(self.polygons, dtype=object)
        self.corners = np.asarray(self.corners)
        self.gradients = np.asarray(self.gradients)
        self.minimum = self.corners[:, :, 2].min(axis=1)
        self.maximum = self.corners[:, :, 2].max(axis=1)
        # 成熟空间索引过滤，正面积覆盖重叠不可通过取并集悄悄掩盖。
        tree = STRtree(self.polygons)
        for i, polygon in enumerate(self.polygons):
            if i % 512 == 0:
                _check_cancel(cancelled)
            for j in tree.query(polygon, predicate="intersects"):
                if j <= i:
                    continue
                other = self.polygons[int(j)]
                tolerance = np.finfo(float).eps * max(polygon.area, other.area) * 64
                if polygon.intersection(other).area > tolerance:
                    raise SiteExcavationError("地形三角片存在正面积重复覆盖", code="overlapping_terrain")
        _check_cancel(cancelled)
        clipped_faces = shapely.intersection(self.polygons, footprint)
        coverage = shapely.union_all(clipped_faces)
        # 计算边界切过倾斜三角片时也产生真实高程折点，不能仅用原顶点高程。
        self.boundary_heights = []
        for i, clipped in enumerate(clipped_faces):
            parts = [clipped] if isinstance(clipped, Polygon) else getattr(clipped, "geoms", [])
            for part in parts:
                if not isinstance(part, Polygon) or part.is_empty or part.area <= 0:
                    continue
                for ring in [part.exterior, *part.interiors]:
                    xy = np.asarray(ring.coords)[:, :2]
                    self.boundary_heights.extend((self.corners[i, 0, 2]
                        + (xy-self.corners[i, 0, :2]) @ self.gradients[i]).tolist())
        missing = footprint.difference(coverage)
        tolerance = max(1e-9, np.finfo(float).eps * max(1, footprint.area)*1024)
        if missing.area > tolerance:
            raise SiteExcavationError(
                f"地形未覆盖完整放坡计算范围，缺测面积 {missing.area:.6g} m²；不得忽略孔洞或以端值外推",
                code="missing_terrain", diagnostics=[{"code": "missing_terrain", "missing_area": float(missing.area),
                                                     "required_area": float(footprint.area)}])

    def area_above(self, level, envelope, cancelled):
        _check_cancel(cancelled)
        all_above = self.minimum >= level
        contributions = []
        if np.any(all_above):
            contributions.append(float(np.sum(shapely.area(shapely.intersection(self.polygons[all_above], envelope)))))
        crossing = np.flatnonzero((self.minimum < level) & (self.maximum > level))
        if len(crossing):
            parts = np.asarray([_clip_triangle(self.corners[i], level) for i in crossing], dtype=object)
            contributions.append(float(np.sum(shapely.area(shapely.intersection(parts, envelope)))))
        return max(0.0, math.fsum(contributions))

    def bottom_fill(self, bottom, level, cancelled):
        amounts = []
        for i in np.flatnonzero(self.minimum < level):
            if len(amounts) % 256 == 0:
                _check_cancel(cancelled)
            part = bottom.intersection(_clip_triangle(self.corners[i], level, above=False))
            if part.is_empty or part.area <= 0:
                continue
            centroid = np.asarray(part.centroid.coords[0])
            ground = self.corners[i, 0, 2] + (centroid-self.corners[i, 0, :2]) @ self.gradients[i]
            amounts.append(max(0.0, float(part.area*(level-ground))))
        return math.fsum(amounts)


def calculate_site(tin: TINModel, config: SiteExcavationConfig, *,
                   progress: Callable | None = None,
                   cancelled: Callable[[], bool] | None = None) -> SiteExcavationResult:
    """计算平底、多级直线放坡基坑；失败或取消时不返回总量。

    从底面附近真实高程逐次扩张放坡范围，每次扩张都要求完整测量
    覆盖，直到最高开挖层在局部地面之上，避免远处山峰扩大计算域。
    底面以下的差分填方单独报告，不是施工回填。
    """
    _validate_config(config)
    _check_cancel(cancelled)
    points = np.asarray(tin.points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or not len(points) or not np.isfinite(points).all():
        raise SiteExcavationError("地形顶点无效", code="invalid_terrain")
    origin = np.asarray(config.bottom_boundary.bounds[:2], dtype=float)
    bottom = translate(config.bottom_boundary, xoff=-origin[0], yoff=-origin[1])
    parts = [bottom] if isinstance(bottom, Polygon) else list(bottom.geoms)
    excluded = unary_union([Polygon(ring) for part in parts for ring in part.interiors])
    if config.excluded_regions is not None:
        excluded = unary_union([excluded, translate(config.excluded_regions, xoff=-origin[0], yoff=-origin[1])])
    bottom = bottom.difference(excluded)
    if bottom.is_empty or bottom.area <= 0:
        raise SiteExcavationError("排除区覆盖全部开挖底面")
    def envelope(height, upper_side=True):
        offset = _offset_for_height(config.grades, height, upper_side=upper_side)
        if not math.isfinite(offset):
            raise SiteExcavationError("放坡范围溢出，请核对坡率、高程及单位")
        return bottom.buffer(offset, join_style="mitre", mitre_limit=1e9).difference(excluded)

    max_height = 0.0
    footprint = bottom
    extent_history = []
    faces = None
    for extent_iteration in range(64):
        _check_cancel(cancelled)
        _progress(progress, "extent", min(.95, extent_iteration/64), f"核验局部放坡接地范围 {extent_iteration+1}")
        faces = _TerrainFaces(tin, footprint, origin, cancelled, progress)
        needed = max(0.0, max(faces.boundary_heights)-config.bottom_elevation)
        extent_history.append({"iteration": extent_iteration, "height": max_height,
                               "local_required_height": needed, "required_area": float(footprint.area)})
        if needed <= max_height+1e-9:
            break
        # 上取整只为避免渐近扩张无休止；高程积分仍使用原始精确高程。
        max_height = math.ceil(needed*1000)/1000
        enlarged = envelope(max_height)
        if enlarged.equals(footprint):
            break
        footprint = enlarged
    else:
        raise SiteExcavationError("局部放坡扩张未闭合；请核对边坡是否能够接地、扩大测量范围或使用明确支护边界",
                                  code="extent_not_closed", diagnostics=extent_history)
    fill = faces.bottom_fill(bottom, config.bottom_elevation, cancelled)
    diagnostics = [{"code": "complete_terrain", "required_area": float(footprint.area), "missing_area": 0.0},
                   {"code": "daylight_extent", "extent_history": extent_history,
                    "message": "从底面局部地形逐次扩张，并验证整个放坡范围测量覆盖及最高层接地"},
                   {"code": "fill_semantics", "message": "表面填方仅统计底面范围低于底标高的差值，不推定回填或填筑施工"},
                   {"code": "boundary_semantics", "message": "底边界孔洞及显式排除区在各高程层均保留；外侧采用直线斜接放坡"}]
    history = []
    cache = {}
    total_evaluations = 0

    def layer_area(height, upper_side=True):
        nonlocal total_evaluations
        _check_cancel(cancelled)
        key = (float(height), bool(upper_side))
        if key not in cache:
            total_evaluations += 1
            if total_evaluations > config.max_evaluations:
                raise SiteExcavationError("达到积分求值上限，未发布工程量结果", code="evaluation_limit", diagnostics=history)
            cache[key] = faces.area_above(config.bottom_elevation+height, envelope(height, upper_side), cancelled)
        return cache[key]

    if max_height == 0:
        history = [{"refinement": 0, "excavation_volume": 0.0, "successive_change": 0.0,
                    "tolerance": config.absolute_tolerance, "evaluation_count": 0}]
        excavation = 0.0
    else:
        # 所有局部地形顶点高程作为积分分段点，避免漏过窄高程带。
        levels = {0.0, max_height}
        heights = faces.corners[:, :, 2].ravel()-config.bottom_elevation
        levels.update(float(h) for h in np.unique(heights) if 0 < h < max_height)
        levels.update(float(z-config.bottom_elevation) for z in faces.boundary_heights
                      if 0 < z-config.bottom_elevation < max_height)
        cumulative = 0.0
        berm_levels = set()
        for grade in config.grades[:-1]:
            cumulative += grade.height
            if cumulative < max_height:
                levels.add(cumulative)
                if grade.berm_width:
                    berm_levels.add(cumulative)
        levels = sorted(levels)
        previous = None
        for refinement in range(config.max_refinements+1):
            _check_cancel(cancelled)
            panels = 2**(refinement+1)
            contributions = []
            for number, (left, right) in enumerate(zip(levels, levels[1:])):
                step = (right-left)/panels
                values = [layer_area(left+i*step, upper_side=(i != panels or right not in berm_levels))
                          for i in range(panels+1)]
                contributions.append(step/3*(values[0]+values[-1]
                    + 4*math.fsum(values[1:-1:2])+2*math.fsum(values[2:-1:2])))
                if number % 32 == 0:
                    _progress(progress, "integration", (refinement+(number+1)/max(1, len(levels)-1))/(config.max_refinements+1),
                              f"水平层积分细化 {refinement+1}，已求值 {total_evaluations} 层")
            excavation = max(0.0, math.fsum(contributions))
            change = None if previous is None else math.fsum(abs(a-b) for a, b in zip(contributions, previous))
            tolerance = config.absolute_tolerance+config.relative_tolerance*excavation
            history.append({"refinement": refinement, "panels_per_height_interval": panels,
                            "excavation_volume": excavation, "successive_change": change,
                            "tolerance": tolerance, "evaluation_count": total_evaluations,
                            "height_interval_count": len(levels)-1})
            if change is not None and change <= tolerance:
                break
            previous = contributions
        else:
            raise SiteExcavationError("水平层积分未达到指定误差收敛要求，未发布工程量结果",
                                      code="not_converged", diagnostics=history)
    _check_cancel(cancelled)
    _progress(progress, "complete", 1.0, "基坑计算及覆盖检查完成")
    return SiteExcavationResult(excavation, fill, float(bottom.area), float(footprint.area), len(faces.polygons),
        translate(bottom, xoff=origin[0], yoff=origin[1]),
        translate(footprint, xoff=origin[0], yoff=origin[1]), history, diagnostics,
        deepcopy(getattr(tin, "import_report", {})),
        {"bottom_boundary": mapping(config.bottom_boundary), "bottom_elevation": config.bottom_elevation,
         "grades": [{"ratio": grade.ratio, "height": None if math.isinf(grade.height) else grade.height,
                     "to_ground": math.isinf(grade.height), "berm_width": grade.berm_width} for grade in config.grades],
         "relative_tolerance": config.relative_tolerance, "absolute_tolerance": config.absolute_tolerance,
         "excluded_regions": None if config.excluded_regions is None else mapping(config.excluded_regions)})
