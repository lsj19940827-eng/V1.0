"""Vertical surface-thickness geology for ordinary open-cut sections.

The interface follows every ground vertex at ``ground_z - thickness``.  A
side may change from bedrock to overburden once; geometry that would enter
bedrock again is rejected rather than silently using the wrong material slope.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from shapely.geometry import Polygon

from ..core.construction_geometry import _polygonal, _validate_region
from ..core.cross_section import CrossSectionCalculator, _validated_line
from .contracts import ConstructionInputError, finite_number


SURFACE_THICKNESS_MODE = "surface_thickness"
LAYERED_SECTION_TYPES = frozenset({
    "trapezoidal_channel", "rectangular_channel", "u_channel",
    "rectangular_culvert", "circular_culvert", "arch_culvert",
    "circular_siphon", "circular_channel",
})
_TOL = 1e-9
_SIDES = ("left", "right")


@dataclass(frozen=True)
class LayerConfig:
    overburden_thickness: float
    overburden_slope_left: float
    overburden_slope_right: float
    bedrock_slope_left: float
    bedrock_slope_right: float

    def slope(self, material, side):
        if material not in {"overburden", "bedrock"} or side not in _SIDES:
            raise ConstructionInputError("分层边坡材料或左右侧无效")
        return getattr(self, material + "_slope_" + side)


def layer_config(construction):
    """Return validated config only for the explicitly selected layer mode.

    Historical/disabled modes retain their existing single-layer semantics.
    Stage parameters cannot be combined with the two material slopes.
    """
    construction = construction or {}
    mode=construction.get("excavation_layer_mode")
    if mode not in (None,"","none",SURFACE_THICKNESS_MODE):
        raise ConstructionInputError("未知开挖分层方式，请选择原单层/分级或覆盖层厚度简化分层")
    if mode != SURFACE_THICKNESS_MODE:
        return None
    if any(construction.get("excavation_stages_" + side) is not None
           for side in ("left", "right", "front", "back")):
        raise ConstructionInputError("覆盖层/基岩分层放坡不能同时设置分级边坡或马道，请先清除分级设置")
    labels = {"overburden_thickness": "覆盖层竖直厚度",
              "overburden_slope_left": "覆盖层左坡比", "overburden_slope_right": "覆盖层右坡比",
              "bedrock_slope_left": "基岩左坡比", "bedrock_slope_right": "基岩右坡比"}
    values = {}
    for field, label in labels.items():
        value = finite_number(construction.get(field), label)
        if value < 0:
            raise ConstructionInputError(f"{label}必须为非负数")
        values[field] = value
    return LayerConfig(**values)


def validate_layer_asset(asset):
    """Reject unsupported enabled assets before independent paths can bypass it."""
    construction = asset.get("construction") or {}
    if construction.get("excavation_layer_mode") != SURFACE_THICKNESS_MODE:
        return layer_config(construction)
    if asset.get("section_type") not in LAYERED_SECTION_TYPES:
        raise ConstructionInputError("覆盖层/基岩分层放坡仅适用于普通线性明挖结构；基坑、隧洞及专用结构暂不支持")
    if construction.get("installation_mode", "buried") in {"exposed", "elevated", "open", "above_ground"}:
        raise ConstructionInputError("覆盖层/基岩分层放坡不适用于明设或架空安装，请关闭分层放坡")
    return layer_config(construction)


def interface_points(ground, construction):
    """Return the vertical-offset interface, preserving all ground breakpoints."""
    config = layer_config(construction)
    if config is None:
        raise ConstructionInputError("尚未启用覆盖层/基岩分层放坡")
    ground = _validated_line(ground, "地面线")
    return _offset_interface(ground, config)


def _offset_interface(ground, config):
    interface = [(x, z - config.overburden_thickness) for x, z in ground]
    if any(not math.isfinite(z) for _, z in interface):
        raise ConstructionInputError("覆盖层厚度与地面高程产生无效基覆界面，请核对数值及单位")
    return interface


def _line_at(ground, offset):
    return CrossSectionCalculator._get_ground_elev_at_offset(ground, offset)


def _check_cover_trace(start, end, interface, ratio, direction):
    """Check every linear interval, including the side of an interface vertex.

    The difference of a ray and the interface is piecewise linear, so its
    signs at the endpoints and intervening interface vertices are sufficient.
    Tangential touches are allowed; an interval inside rock is not.
    """
    offsets = [start[0]]
    offsets.extend(sorted((x for x, _ in interface
                           if min(start[0], end[0]) < x < max(start[0], end[0])),
                          reverse=direction < 0))
    offsets.append(end[0])
    was_in_cover = start[1] - _line_at(interface, start[0]) > _TOL
    for index, offset in enumerate(offsets):
        # A vertical edge has no horizontal interior; rising from a valid
        # start cannot enter a lower material along the same XY position.
        elevation = end[1] if ratio == 0 and index else start[1]
        if ratio:
            elevation = start[1] + abs(offset - start[0]) / ratio
        difference = elevation - _line_at(interface, offset)
        if difference < -_TOL:
            if not was_in_cover:
                raise ConstructionInputError("覆盖层边坡在基覆界面处无法向覆盖层延伸，请复核地形与两层坡比")
            raise ConstructionInputError("覆盖层边坡再次穿入基岩，超出一次变坡的简化规则，请复核地形与两层坡比")
        if difference > _TOL:
            was_in_cover = True


def trace_layered_to_ground(start, ground, construction, side, direction=None):
    """Trace a real side from its existing toe to the first ground intersection.

    Slope ratios are horizontal/vertical.  At zero thickness every point is
    bedrock.  At positive thickness a toe on/above the interface starts in
    overburden; a lower toe first uses bedrock until the interface intersection.
    No endpoint extrapolation or repeated crossing of the interface is allowed.
    """
    config = layer_config(construction)
    if config is None:
        raise ConstructionInputError("尚未启用覆盖层/基岩分层放坡")
    if side not in _SIDES:
        raise ConstructionInputError("分层边坡必须明确左侧或右侧")
    expected_direction = -1 if side == "left" else 1
    if direction is None:
        direction = expected_direction
    if direction != expected_direction:
        raise ConstructionInputError("分层边坡左右侧与向外方向不一致")
    try:
        x, z = start
    except (TypeError, ValueError) as error:
        raise ConstructionInputError("坡脚必须为偏距、高程两个坐标") from error
    point = (finite_number(x, "坡脚偏距"), finite_number(z, "坡脚高程"))
    ground = _validated_line(ground, "地面线")
    ground_start = _line_at(ground, point[0])
    if ground_start < point[1] - _TOL:
        raise ConstructionInputError("坡脚高于地面，需要明确填方边界")
    points = [point]
    if abs(ground_start - point[1]) <= _TOL:
        return points
    interface = _offset_interface(ground, config)
    in_bedrock = config.overburden_thickness == 0 or point[1] < _line_at(interface, point[0]) - _TOL
    if in_bedrock:
        ratio = config.slope("bedrock", side)
        target = ground if config.overburden_thickness == 0 else interface
        hit = CrossSectionCalculator._ray_ground_hit(point, (direction * ratio, 1.), target)
        if hit is None:
            raise ConstructionInputError("基岩边坡在有效地形范围内未与基覆界面或地面相交，请扩大地形范围或复核坡比")
        point = hit[1]
        if hit[0] > _TOL:
            points.append(point)
        if config.overburden_thickness == 0:
            return points
    ratio = config.slope("overburden", side)
    hit = CrossSectionCalculator._ray_ground_hit(point, (direction * ratio, 1.), ground)
    if hit is None:
        raise ConstructionInputError("覆盖层边坡在有效地形范围内未与地面相交，请扩大地形范围或复核坡比")
    _check_cover_trace(point, hit[1], interface, ratio, direction)
    if hit[0] > _TOL:
        points.append(hit[1])
    return points


def split_excavation_layers(excavation, ground, construction):
    """Partition an actual (optionally ownership-corrected) excavation polygon.

    Returned geometries are mutually disjoint in area and sum to the supplied
    excavation.  This function does not construct a slope or label fill as rock.
    It must be called only when the surface-thickness mode is enabled.
    """
    config = layer_config(construction)
    if config is None:
        raise ConstructionInputError("尚未启用覆盖层/基岩分层放坡")
    _validate_region(excavation, "分层所用实际开挖区域")
    ground = _validated_line(ground, "地面线")
    if excavation.is_empty:
        return {"overburden": Polygon(), "bedrock": Polygon()}
    left, floor, right, _ = excavation.bounds
    # Endpoint interpolation validates full measured coverage, even at h=0.
    cropped = [(left, _line_at(ground, left)),
               *((x, z) for x, z in ground if left < x < right),
               (right, _line_at(ground, right))]
    base = min(floor, *(z for _, z in cropped)) - 1.
    soil = Polygon([(left, base), (right, base), *reversed(cropped)])
    if excavation.difference(soil).area > max(1e-8, excavation.area * 1e-10):
        raise ConstructionInputError("分层计量必须使用原地面以下的实际开挖区域，不能包含地面以上区域")
    if config.overburden_thickness == 0:
        return {"overburden": Polygon(), "bedrock": excavation}
    interface = _offset_interface(cropped, config)
    covering = Polygon([*cropped, *reversed(interface)])
    cover = _polygonal(excavation.intersection(covering))
    rock = _polygonal(excavation.difference(cover))
    return {"overburden": cover, "bedrock": rock}
