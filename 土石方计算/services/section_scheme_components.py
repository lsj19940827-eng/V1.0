"""Explicit project profiles for source details without a universal foundation level."""
from __future__ import annotations

from copy import deepcopy
import math

from shapely import affinity
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .contracts import ConstructionInputError


PROFILE_FIELDS = {
    "retaining_wall_profile": ("retaining_wall", "挡墙", "masonry"),
    "foundation_replacement_profile": ("foundation_replacement_profile", "基础换填", "concrete"),
    "gabion_profile": ("gabion", "格宾石笼填石", "rockfill"),
    "rockfill_profile": ("rockfill", "大块石回填", "rockfill"),
}


def validate_scheme_profile(value, *, field="retaining_wall_profile"):
    """Return normalized local profile and polygon; never repair invalid input."""
    identifier, label, default_material = PROFILE_FIELDS[field]
    if isinstance(value, (list, tuple)):
        value = {"points": value, "reference": "inner_invert", "material": default_material}
    if not isinstance(value, dict):
        raise ConstructionInputError(f"{label}请填写横偏距与相对内底高程坐标表")
    spec = deepcopy(value)
    if spec.get("reference", "inner_invert") != "inner_invert":
        raise ConstructionInputError(f"{label}高程基准须为当前断面内底高程")
    raw = spec.get("points")
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        raise ConstructionInputError(f"{label}轮廓至少需要三个不同顶点")
    points = []
    for index, point in enumerate(raw, 1):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ConstructionInputError(f"{label}第{index}点请填写横偏距和相对高程两列")
        try:
            if any(isinstance(v, bool) for v in point):
                raise ValueError
            x, z = map(float, point)
            if not math.isfinite(x) or not math.isfinite(z):
                raise ValueError
        except (ValueError, TypeError):
            raise ConstructionInputError(f"{label}第{index}点须为有限数值，单位为米") from None
        points.append([x, z])
    polygon = Polygon(points)
    if not polygon.is_valid or polygon.is_empty or polygon.area <= 1e-10:
        raise ConstructionInputError(f"{label}轮廓自交、退化或面积为零；请按轮廓顺序逐点填写")
    material = spec.get("material", default_material)
    if material not in {"masonry", "concrete", "rockfill"}:
        raise ConstructionInputError(f"{label}材料请选择浆砌石、混凝土或石笼填石")
    spec.update(points=points, reference="inner_invert", material=material,
                grade=str(spec.get("grade") or ""), name=str(spec.get("name") or label),
                component_id=identifier, unit="m3", occupies_space=True)
    return spec, polygon


def apply_scheme_profiles(structure, asset, elevation=0.):
    """Attach actual material regions and occupied space using explicit local points."""
    try:
        level = float(elevation)
        if not math.isfinite(level):
            raise ValueError
    except (TypeError, ValueError):
        raise ConstructionInputError("断面内底设计高程无效") from None
    section = asset.get("section", {})
    requested = [(field, section.get(field)) for field in PROFILE_FIELDS if section.get(field) is not None]
    if not requested:
        return structure
    result = deepcopy(structure)
    if asset.get("section_type") in {"circular_culvert", "circular_siphon", "circular_channel"}:
        # Circular assets use the pipe axis as their design-profile datum.
        # The editor contract is still explicitly the actual inner invert.
        void = result.get("net_void")
        if void is None or void.is_empty:
            raise ConstructionInputError("管道净空尚未明确，无法确定轮廓输入的管内底高程基准")
        level = float(void.bounds[1])
    regions = result.setdefault("component_regions", {})
    occupied = unary_union([result["outer"], result.get("occupancy", Polygon()),
                            *result.get("materials", {}).values(),
                            *(spec["geometry"] for spec in regions.values())])
    additions = []
    for field, value in requested:
        spec, local = validate_scheme_profile(value, field=field)
        identifier = spec["component_id"]
        if identifier in regions:
            raise ConstructionInputError(spec["name"] + "与现有独立材料编号重复")
        geometry = affinity.translate(local, yoff=level)
        if geometry.intersection(occupied).area > 1e-8:
            raise ConstructionInputError(spec["name"] + "与结构净空、衬砌或其他材料占位重叠，请核对轮廓坐标")
        regions[identifier] = {**spec, "geometry": geometry, "section_measure": float(geometry.area)}
        occupied = unary_union([occupied, geometry])
        additions.append(geometry)
    result["measured"] = unary_union([result.get("measured", Polygon()), *(spec["geometry"] for spec in regions.values())])
    result["occupancy"] = occupied
    return result
