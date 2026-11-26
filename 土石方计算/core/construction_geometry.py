# -*- coding: utf-8 -*-
"""显式二维施工状态算子，不推定结构外轮廓、地形或施工模板。"""

from __future__ import annotations
from dataclasses import dataclass
import math
from shapely.geometry import Polygon, MultiPolygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import explain_validity


class ConstructionGeometryError(ValueError):
    """输入区域无效或施工前后状态不一致。"""


@dataclass(frozen=True)
class ConstructionStateResult:
    """同一有限计算域中的二维区域；挖、填对应不同施工阶段。"""
    excavation: BaseGeometry
    retained_soil: BaseGeometry
    fill: BaseGeometry
    excluded_occupancy: BaseGeometry

    @property
    def excavation_area(self) -> float:
        return float(self.excavation.area)

    @property
    def retained_area(self) -> float:
        return float(self.retained_soil.area)

    @property
    def fill_area(self) -> float:
        return float(self.fill.area)

    @property
    def backfill(self) -> BaseGeometry:
        """回填是本次开挖区域内重新填入的土体。"""
        return _polygonal(self.fill.intersection(self.excavation))

    @property
    def embankment(self) -> BaseGeometry:
        """新增填筑位于本次开挖区域之外。"""
        return _polygonal(self.fill.difference(self.excavation))

    @property
    def backfill_area(self) -> float:
        return float(self.backfill.area)

    @property
    def embankment_area(self) -> float:
        return float(self.embankment.area)


def _validate_region(region: BaseGeometry, name: str) -> None:
    """仅接受有效二维多边形，拒绝自动修复和高程维度的隐式丢弃。"""
    if not isinstance(region, (Polygon, MultiPolygon)):
        raise ConstructionGeometryError(f"{name}必须是 Polygon 或 MultiPolygon；无区域须显式传空 Polygon")
    if region.has_z:
        raise ConstructionGeometryError(f"{name}必须为二维断面区域")
    parts = list(region.geoms) if isinstance(region, MultiPolygon) else [region]
    for part in parts:
        if part.is_empty:
            continue
        for ring in [part.exterior, *part.interiors]:
            if any(not math.isfinite(v) for point in ring.coords for v in point):
                raise ConstructionGeometryError(f"{name}坐标必须为有限值")
    if not region.is_valid or not math.isfinite(region.area):
        raise ConstructionGeometryError(f"{name}无效：{explain_validity(region)}")


def _polygonal(region: BaseGeometry) -> BaseGeometry:
    """去除相切产生的线、点，面积结果始终保留为多边形。"""
    if isinstance(region, (Polygon, MultiPolygon)):
        return region
    parts = []
    for child in getattr(region, "geoms", []):
        part = _polygonal(child)
        if not part.is_empty:
            parts.append(part)
    return unary_union(parts) if parts else Polygon()


def compute_construction_state(
    original_soil: BaseGeometry,
    excavation_envelope: BaseGeometry,
    target_soil: BaseGeometry,
    permanent_occupancy: BaseGeometry,
    measured_occupancy: BaseGeometry | None = None,
    *, area_tolerance: float = 1e-9,
) -> ConstructionStateResult:
    """显式计算施工区域，面积单位为输入长度单位的平方。

    所有输入在同一有限计算域中，目标土体包络包含应保留的原状土。
    永久占位须使用结构外包区域（包括管、涵内部空腔），单独计量占位
    用于垫层等另列材料。占位先取并集，避免重叠部分重复扣减。
    开挖为原状土与开挖包络的交集；回填为目标包络扣除保留土与占位。
    保留土超出最终土体时拒绝输出，不能把漏挖区域隐去。
    """
    if not math.isfinite(area_tolerance) or area_tolerance < 0:
        raise ConstructionGeometryError("面积容差必须为非负有限值")
    regions = {
        "原状土区域": original_soil,
        "开挖包络": excavation_envelope,
        "目标土体包络": target_soil,
        "永久外包占位": permanent_occupancy,
        "单独计量占位": Polygon() if measured_occupancy is None else measured_occupancy,
    }
    for name, region in regions.items():
        _validate_region(region, name)
    occupancy = _polygonal(unary_union([permanent_occupancy, regions["单独计量占位"]]))
    excavation = _polygonal(original_soil.intersection(excavation_envelope))
    retained = _polygonal(original_soil.difference(excavation))
    final_soil = _polygonal(target_soil.difference(occupancy))
    conflict_area = retained.difference(final_soil).area
    if conflict_area > area_tolerance:
        raise ConstructionGeometryError(
            f"仍有应挖未挖土体（面积 {conflict_area:.12g}）："
            "占位与保留土相交，或保留土超出目标土体包络"
        )
    fill = _polygonal(final_soil.difference(retained))
    return ConstructionStateResult(excavation, retained, fill, occupancy)
