# -*- coding: utf-8 -*-
"""连接明渠的断面复算与参数来源，供推荐、补段窗口和工程恢复共用。"""

import copy
import math

if __package__ and __package__.startswith("推求水面线."):
    from ..models.data_models import ChannelNode, OpenChannelParams, ProjectSettings
    from ..models.enums import StructureType
else:
    from models.data_models import ChannelNode, OpenChannelParams, ProjectSettings
    from models.enums import StructureType
from .hydraulic_calc import HydraulicCalculator


OPEN_CHANNEL_TYPES = {"明渠-矩形", "明渠-梯形", "明渠-圆形", "明渠-U形"}


def positive(value):
    """只接受有限的正数，缺失参数不替换成设计值。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def flow_section_key(value):
    """兼容旧工程把流量段保存为数字或字符串的情况。"""
    text = str(value or "").strip()
    try:
        number = float(text)
        if math.isfinite(number) and number.is_integer():
            return str(int(number))
    except ValueError:
        pass
    return text


def max_flow_for_section(settings, flow_section, flow):
    """加大流量取项目当前工况；未启用时按设计工况复算。"""
    try:
        _, maximum = settings.get_flow_for_segment(int(flow_section_key(flow_section)))
    except (ValueError, TypeError, AttributeError):
        maximum = 0.0
    return max(float(flow), float(maximum)) if positive(maximum) else float(flow)


def recalculate_open_channel(reference, flow, flow_section, max_flow=0.0, *, require_subcritical=True):
    """保留指定几何，重算两工况水深、流速与渠高，不沿用建筑物旧水深。"""
    from 明渠设计 import (
        calculate_depth_for_flow, calculate_flow_rate, calculate_u_depth_for_flow,
        calculate_water_depth_y_circular,
    )

    result = copy.deepcopy(reference)
    result.pop("recalculation_error", None)
    structure = result.get("structure_type", "")
    if structure == "矩形":
        structure = "明渠-矩形"
    if structure not in OPEN_CHANNEL_TYPES:
        return None
    n, inverse = result.get("roughness"), result.get("slope_inv")
    if not all(positive(v) for v in (flow, n, inverse)):
        return None
    flow, n, inverse = float(flow), float(n), float(inverse)
    width = float(result.get("bottom_width", 0) or 0)
    radius = float(result.get("arc_radius", 0) or 0)
    side = float(result.get("side_slope", 0) or 0)
    theta = float(result.get("theta_deg", 0) or 0)
    if not all(math.isfinite(v) for v in (width, radius, side, theta)) or side < 0:
        return None
    if not positive(radius if structure == "明渠-U形" else width):
        return None
    node = ChannelNode(structure_type=StructureType.from_string(structure))
    node.roughness, node.slope_i = n, 1.0 / inverse
    node.section_params = {"B": width, "m": side}
    if structure == "明渠-矩形":
        node.section_params["m"] = side = 0.0
    elif structure == "明渠-圆形":
        node.section_params = {"D": width, "m": 0.0}
    elif structure == "明渠-U形":
        node.section_params = {"R_circle": radius, "m": side, "theta_deg": theta}
    hydraulic = HydraulicCalculator(ProjectSettings())

    def solve(discharge):
        if structure == "明渠-圆形":
            h = calculate_water_depth_y_circular(width, discharge * n / math.sqrt(node.slope_i))[0]
        elif structure == "明渠-U形":
            h = calculate_u_depth_for_flow(discharge, radius, math.degrees(math.atan(side)), theta, n, node.slope_i)
        else:
            h = calculate_depth_for_flow(discharge, width, node.slope_i, n, side)
            if positive(h):
                # 原内核按工程精度终止；补段复核继续收敛，避免临界流态及长度受舍入影响。
                low, high = 0.0, 2 * h
                for _ in range(80):
                    h = (low + high) / 2
                    computed = calculate_flow_rate(width, h, node.slope_i, n, side)
                    if abs(computed - discharge) <= discharge * 1e-9:
                        break
                    if computed < discharge:
                        low = h
                    else:
                        high = h
        if not positive(h):
            return None
        node.flow, node.water_depth = discharge, h
        node.section_params["h"] = node.section_params["水深"] = h
        area = hydraulic.get_cross_section_area(node)
        top_width = hydraulic.get_water_surface_width(node)
        if not all(positive(v) for v in (area, top_width)):
            return None
        velocity = discharge / area
        froude = velocity / math.sqrt(9.81 * area / top_width)
        if require_subcritical and froude >= 1.0 - 1e-12:
            return None
        return h, velocity, froude

    design = solve(flow)
    increased_flow = max(flow, float(max_flow)) if positive(max_flow) else flow
    increased = solve(increased_flow) if increased_flow != flow else design
    if design is None or increased is None:
        return None
    result.update(
        structure_type=structure, section_family="open_channel", flow=flow,
        flow_section=flow_section_key(flow_section), bottom_width=0.0 if structure == '明渠-U形' else width,
        side_slope=side, roughness=n, slope_inv=inverse,
        water_depth=design[0], velocity=design[1], reference_froude=design[2],
        max_flow=increased_flow, water_depth_increased=increased[0],
        velocity_increased=increased[1], froude_increased=increased[2],
        auto_calculated=True,
    )
    # 沿用现有明渠模块的渠高规则；圆形断面总高由直径确定。
    if structure == "明渠-圆形":
        result.update(structure_height=width, freeboard=width - increased[0], height_source="圆形断面直径")
    else:
        freeboard = round(0.25 * increased[0] + 0.2, 3)
        result.update(
            freeboard=freeboard, structure_height=round(increased[0] + freeboard, 3),
            height_source="沿用明渠模块超高规则（适用于4、5级渠道）",
        )
    return result


def reference_to_params(reference):
    """把完整推荐转换为补段参数，保留来源及加大工况。"""
    fields = (
        "structure_type", "bottom_width", "water_depth", "side_slope", "roughness",
        "slope_inv", "flow", "flow_section", "structure_height", "arc_radius", "theta_deg",
    )
    return OpenChannelParams(
        **{key: reference[key] for key in fields if key in reference},
        reference_details=copy.deepcopy(reference),
    )


def params_to_reference(params):
    """保存输入几何和来源；使用时必须按当前流量重算水深。"""
    result = copy.deepcopy(getattr(params, "reference_details", {}) or {})
    for key in (
        "structure_type", "bottom_width", "water_depth", "side_slope", "roughness",
        "slope_inv", "flow", "flow_section", "structure_height", "arc_radius", "theta_deg",
    ):
        result[key] = getattr(params, key)
    return result


def describe_connection_reference(reference):
    """供窗口展示的具体来源及复算结果。"""
    if not reference:
        return ""
    parts = []
    if reference.get("recalculation_error"):
        parts.append(reference["recalculation_error"])
    source = reference.get("source_kind")
    if source == "user_override":
        parts.append("采用本位置已保存的断面参数，按当前流量重新计算。")
    elif source == "user_template":
        parts.append("采用本流量段连接明渠模板，按当前流量重新计算。")
    elif source == "inferred_rectangular":
        parts.append(f"矩形明渠底宽取 {reference.get('geometry_source_name', '')}（{reference.get('geometry_source_type', '')}）。")
    elif source == "economic_rectangular":
        parts.append("缺少可用底宽，按矩形水力最佳断面条件 B=2h 拟定底宽后重新计算。")
    if reference.get("slope_source_name"):
        parts.append(f"坡降取 {reference['slope_source_name']}，1/{reference.get('slope_inv', '')}。")
    if reference.get("roughness_source"):
        parts.append(f"糙率取{reference['roughness_source']}。")
    if reference.get("auto_calculated"):
        parts.append(
            f"正常水深 {reference['water_depth']:.3f} m，流速 {reference['velocity']:.3f} m/s，"
            f"Fr={reference['reference_froude']:.3f}；"
            f"校核流量 {reference['max_flow']:.3f} m³/s，水深 {reference['water_depth_increased']:.3f} m，"
            f"渠高 {reference['structure_height']:.3f} m。"
        )
        parts.append(reference.get("height_source", ""))
    return "\n".join(parts)
