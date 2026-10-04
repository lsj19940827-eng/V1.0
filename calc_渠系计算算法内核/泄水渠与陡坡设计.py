# -*- coding: utf-8 -*-
"""泄水渠与陡坡水力计算内核，复用明渠断面能力并提供前端快速调用接口。"""

import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Tuple

from calc_渠系计算算法内核.明渠设计 import (
    calculate_area,
    calculate_depth_for_flow,
    calculate_flow_rate,
    calculate_hydraulic_radius,
    calculate_wetted_perimeter,
)

G = 9.81
SLOPE_TOLERANCE = 0.005
DEFAULT_DEPTH_STEP = 0.02
DEFAULT_PROFILE_ALPHA = 1.1


class ChuteSectionType(str, Enum):
    """泄水渠与陡坡第一版支持的断面类型。"""

    RECTANGULAR = "rectangular"
    TRAPEZOIDAL = "trapezoidal"


class ChuteProfileCalcMode(str, Enum):
    """陡槽水面线三种计算模式。"""

    END_DEPTH_BY_LENGTH = "END_DEPTH_BY_LENGTH"
    LENGTH_BY_TWO_DEPTHS = "LENGTH_BY_TWO_DEPTHS"
    FULL_CURVE_TO_NORMAL = "FULL_CURVE_TO_NORMAL"


class ChuteSlopeClass(str, Enum):
    """底坡与临界底坡的相对关系。"""

    MILD = "mild"
    CRITICAL = "critical"
    STEEP = "steep"


class ChuteStartControlMode(str, Enum):
    """陡槽起点水深控制方式。"""

    CRITICAL_DEPTH = "critical_depth"
    MANUAL = "manual"
    INLET_CONTROL = "inlet_control"
    MODEL_TEST = "model_test"


class InletConnectionType(str, Enum):
    """跌口或陡坡入口连接形式，用于按规范确定流量系数。"""

    WARPED_SURFACE = "扭曲面连接"
    SPLAY_WALL = "八字墙连接"
    DIAPHRAGM_WALL = "横隔墙连接"
    MANUAL_COEFFICIENT = "手动输入流量系数"


@dataclass
class ChuteInputData:
    """保存一次泄水渠与陡坡计算输入，字段保持 JSON 友好。"""

    structure_name: str = "泄水渠与陡坡"
    section_type: str = ChuteSectionType.TRAPEZOIDAL.value
    Q: float = 0.0
    b: float = 0.0
    m: float = 0.0
    n: float = 0.0
    i: float = 0.0
    L: float = 0.0
    start_station: float = 0.0
    start_bed_elevation: float = 0.0
    start_depth: float | None = None
    end_depth: float | None = None
    depth_step: float = DEFAULT_DEPTH_STEP
    profile_mode: str = ChuteProfileCalcMode.END_DEPTH_BY_LENGTH.value
    inlet_weir_width: float | None = None
    inlet_head: float | None = None
    inlet_connection_type: str | None = InletConnectionType.WARPED_SURFACE.value
    weir_coefficient: float | None = None
    contraction_coefficient: float = 1.0
    upstream_straight_length: float | None = None
    downstream_straight_length: float | None = None
    critical_alpha: float = 1.0
    alpha_profile: float = DEFAULT_PROFILE_ALPHA


@dataclass
class ChuteProfilePoint:
    """保存陡槽沿程一个计算断面的主要水力结果。"""

    distance_m: float
    station_m: float
    bed_elevation_m: float
    water_elevation_m: float
    depth_m: float
    area_m2: float
    wetted_perimeter_m: float
    hydraulic_radius_m: float
    water_top_width_m: float
    velocity_ms: float
    froude: float
    hydraulic_slope: float
    specific_energy_m: float


@dataclass
class ChuteCaseResult:
    """保存单工况结果，便于前端保存恢复和后续多工况对比。"""

    h0_m: float
    hk_m: float
    ik: float
    slope_class: str
    start_depth_m: float
    end_depth_m: float | None
    max_velocity_ms: float
    max_froude: float
    inlet_capacity_ratio: float | None
    profile_points: List[Dict[str, Any]] = field(default_factory=list)
    code_checks: List[Dict[str, Any]] = field(default_factory=list)
    formula_cards: List[Dict[str, str]] = field(default_factory=list)
    risk_tips: List[str] = field(default_factory=list)

def _as_float(data: Dict[str, Any], key: str, default: float = 0.0) -> float:
    """把输入字段转为浮点数，失败时返回默认值。"""
    value = data.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _has_value(data: Dict[str, Any], key: str) -> bool:
    """判断输入字典中某个字段是否填了有效值。"""
    return key in data and data.get(key) not in (None, "")


def _first_float(data: Dict[str, Any], keys: Tuple[str, ...], default: float = 0.0) -> float:
    """按候选字段顺序读取第一个有效浮点数。"""
    for key in keys:
        if key in data and data.get(key) not in (None, ""):
            return _as_float(data, key, default)
    return default


def _first_optional_float(data: Dict[str, Any], keys: Tuple[str, ...]) -> float | None:
    """按候选字段顺序读取第一个有效浮点数；缺失时返回 None。"""
    for key in keys:
        if key in data and data.get(key) not in (None, ""):
            try:
                return float(data.get(key))
            except (TypeError, ValueError):
                return None
    return None


def _profile_energy_alpha(data: Dict[str, Any]) -> float:
    """读取水面线动能修正系数，兼容旧字段名。"""
    alpha = _first_float(data, ("alpha_profile", "profile_energy_alpha", "alpha_e"), DEFAULT_PROFILE_ALPHA)
    return alpha if alpha > 0 else DEFAULT_PROFILE_ALPHA


def _normalize_section_type(section_type: Any) -> str:
    """统一断面类型名称。"""
    if isinstance(section_type, ChuteSectionType):
        return section_type.value
    text = str(section_type or "trapezoidal").strip().lower()
    if text in {"rect", "rectangle", "rectangular", "矩形", ChuteSectionType.RECTANGULAR.value}:
        return ChuteSectionType.RECTANGULAR.value
    return ChuteSectionType.TRAPEZOIDAL.value


def _normalize_inlet_connection_type(value: Any) -> str:
    """统一入口连接形式名称，兼容旧英文枚举和值。"""
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    mapping = {
        "warped_surface": InletConnectionType.WARPED_SURFACE.value,
        "warped": InletConnectionType.WARPED_SURFACE.value,
        "扭曲面": InletConnectionType.WARPED_SURFACE.value,
        "扭曲面连接": InletConnectionType.WARPED_SURFACE.value,
        "splay_wall": InletConnectionType.SPLAY_WALL.value,
        "splayed_wall": InletConnectionType.SPLAY_WALL.value,
        "wing_wall": InletConnectionType.SPLAY_WALL.value,
        "八字墙": InletConnectionType.SPLAY_WALL.value,
        "八字墙连接": InletConnectionType.SPLAY_WALL.value,
        "diaphragm_wall": InletConnectionType.DIAPHRAGM_WALL.value,
        "cross_wall": InletConnectionType.DIAPHRAGM_WALL.value,
        "横隔墙": InletConnectionType.DIAPHRAGM_WALL.value,
        "横隔墙连接": InletConnectionType.DIAPHRAGM_WALL.value,
        "manual": InletConnectionType.MANUAL_COEFFICIENT.value,
        "manual_coefficient": InletConnectionType.MANUAL_COEFFICIENT.value,
        "人工流量系数": InletConnectionType.MANUAL_COEFFICIENT.value,
        "手动输入流量系数": InletConnectionType.MANUAL_COEFFICIENT.value,
    }
    return mapping.get(lowered, mapping.get(text, text))

def _top_width(b: float, h: float, m: float) -> float:
    """计算矩形或梯形断面的水面宽。"""
    return b + 2.0 * m * max(h, 0.0)

def _section_metrics(Q: float, b: float, h: float, m: float, n: float, alpha_profile: float = 1.0) -> Dict[str, float]:
    """计算给定水深下的断面水力要素。"""
    area = calculate_area(b, h, m)
    perimeter = calculate_wetted_perimeter(b, h, m)
    radius = calculate_hydraulic_radius(b, h, m)
    top_width = _top_width(b, h, m)
    velocity = Q / area if area > 0 else 0.0
    hydraulic_depth = area / top_width if top_width > 0 else 0.0
    froude = velocity / math.sqrt(G * hydraulic_depth) if hydraulic_depth > 0 else 0.0
    specific_energy = h + alpha_profile * velocity * velocity / (2.0 * G)
    hydraulic_slope = _hydraulic_slope(Q, area, radius, n)
    return {
        "depth_m": h,
        "area_m2": area,
        "wetted_perimeter_m": perimeter,
        "hydraulic_radius_m": radius,
        "water_top_width_m": top_width,
        "velocity_ms": velocity,
        "froude": froude,
        "energy_froude": math.sqrt(alpha_profile) * froude,
        "specific_energy_m": specific_energy,
        "hydraulic_slope": hydraulic_slope,
    }

def _hydraulic_slope(Q: float, area: float, radius: float, n: float) -> float:
    """用曼宁公式反算水力坡度。"""
    if Q <= 0 or area <= 0 or radius <= 0 or n <= 0:
        return 0.0
    return (n * Q / (area * radius ** (2.0 / 3.0))) ** 2

def _solve_critical_depth(Q: float, b: float, m: float, alpha: float = 1.0) -> float:
    """按临界流条件求矩形或梯形临界水深。"""
    if Q <= 0 or b <= 0:
        return -1.0
    if abs(m) < 1e-12:
        return (alpha * (Q / b) ** 2 / G) ** (1.0 / 3.0)

    target = alpha * Q * Q / G
    low = 1e-6
    high = max(1.0, (Q / b) ** (2.0 / 3.0))

    def critical_value(depth: float) -> float:
        """计算临界方程左端值。"""
        area = calculate_area(b, depth, m)
        width = _top_width(b, depth, m)
        return area ** 3 / width if width > 0 else 0.0

    while critical_value(high) < target and high < 1000:
        high *= 2.0
    if high >= 1000:
        return -1.0

    for _ in range(100):
        mid = (low + high) / 2.0
        if critical_value(mid) < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _solve_profile_normal_depth(Q: float, b: float, m: float, n: float, i: float) -> float:
    """用严密流量平衡求正常水深，避免渐近段放大通用设计精度误差。"""
    low, high = 0.0, 1.0
    while calculate_flow_rate(b, high, i, n, m) < Q and high < 10000.0:
        high *= 2.0
    if calculate_flow_rate(b, high, i, n, m) < Q:
        return -1.0
    for _ in range(100):
        mid = (low + high) / 2.0
        if calculate_flow_rate(b, mid, i, n, m) < Q:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _critical_slope(Q: float, b: float, m: float, n: float, critical_depth: float) -> float:
    """计算临界水深对应的临界底坡。"""
    area = calculate_area(b, critical_depth, m)
    radius = calculate_hydraulic_radius(b, critical_depth, m)
    return _hydraulic_slope(Q, area, radius, n)


def _slope_type(i: float, critical_slope: float) -> str:
    """根据实际底坡和临界底坡判断坡型。"""
    if critical_slope <= 0:
        return "unknown"
    relative = (i - critical_slope) / critical_slope
    if abs(relative) <= SLOPE_TOLERANCE:
        return "critical"
    return "steep" if relative > 0 else "mild"


def _water_profile_type(
    slope_type: str,
    depth: float,
    normal_depth: float,
    critical_depth: float,
    data: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    """识别常见明渠水面线型，并生成中文说明。"""
    data = data or {}
    mode = str(data.get("profile_mode") or "").strip().upper()
    if mode in {"UPSTREAM_END_CONTROL", "UPSTREAM_B1_CONTROL"}:
        return {
            "type": "b_1",
            "name": "缓坡 b_1 型降水曲线",
            "message": "上游普通缓坡渠道以陡槽入口临界水深为下游控制边界时，末段按 b_1 型降水曲线校核。",
        }
    # 六位输出精度下的正常水深属于均匀流，不误标成增水或降水曲线。
    if abs(depth - normal_depth) <= 1e-6:
        return {"type": "uniform", "name": "均匀流水面线", "message": "水深等于正常水深，沿程按均匀流计算。"}
    if slope_type == "mild":
        if depth > normal_depth:
            profile_type, name = "a_1", "缓坡 a_1 型壅水曲线"
        elif critical_depth < depth <= normal_depth:
            profile_type, name = "b_1", "缓坡 b_1 型降水曲线"
        else:
            profile_type, name = "c_1", "缓坡 c_1 型壅水曲线"
    elif slope_type == "steep":
        if depth > critical_depth + 1e-6:
            profile_type, name = "a_2", "陡坡 a_2 型壅水曲线"
        elif normal_depth < depth <= critical_depth + 1e-6:
            profile_type, name = "b_2", "陡坡 b_2 型降水曲线"
        else:
            profile_type, name = "c_2", "陡坡 c_2 型壅水曲线"
    elif slope_type == "critical":
        profile_type, name = "a_3/c_3", "临界坡特殊水面线"
    else:
        profile_type, name = "unknown", "未识别水面线型"
    return {
        "type": profile_type,
        "name": name,
        "message": f"{name}：水面线型由底坡类型和实际水深相对正常水深、临界水深的位置共同决定。",
    }


def _resolve_start_control(data: Dict[str, Any], hydraulic: Dict[str, Any]) -> Dict[str, Any]:
    """确定陡槽起点控制水深，避免把上游正常水深直接当作陡槽起点。"""
    critical_depth = float(hydraulic.get("critical_depth_m", 0.0) or 0.0)
    mode_text = str(data.get("control_depth_mode") or data.get("start_depth_mode") or "").strip().lower()
    profile_mode = str(data.get("profile_mode") or "").strip().upper()
    manual_aliases = {"manual", "人工指定", "actual", "实际控制", "user", "specified"}
    inlet_aliases = {"inlet", "inlet_control", "进口控制", "gate", "闸门控制"}
    model_aliases = {"model", "model_test", "模型试验", "test"}

    if mode_text in inlet_aliases:
        depth = _first_float(data, ("inlet_control_depth", "gate_control_depth", "manual_start_depth", "actual_control_depth", "h_control", "start_depth"), critical_depth)
        return {
            "mode": ChuteStartControlMode.INLET_CONTROL.value,
            "depth_m": round(depth, 6),
            "source": "进口控制段计算",
            "message": "本次按进口控制段或闸门控制水深作为陡槽起点控制水深。",
        }
    if mode_text in model_aliases:
        depth = _first_float(data, ("model_test_start_depth", "manual_start_depth", "actual_control_depth", "h_control", "start_depth"), critical_depth)
        return {
            "mode": ChuteStartControlMode.MODEL_TEST.value,
            "depth_m": round(depth, 6),
            "source": "模型试验或专项复核",
            "message": "本次按模型试验或专项复核给出的控制水深作为陡槽起点。",
        }
    if mode_text in manual_aliases:
        depth = _first_float(data, ("manual_start_depth", "actual_control_depth", "h_control", "start_depth", "h_start"), critical_depth)
        return {
            "mode": ChuteStartControlMode.MANUAL.value,
            "depth_m": depth,
            "source": "人工指定",
            "message": "本次按人工指定的实际控制水深作为陡槽起点控制水深。",
        }
    if _has_value(data, "inlet_control_depth"):
        depth = _first_float(data, ("inlet_control_depth", "gate_control_depth", "h_control"), critical_depth)
        return {
            "mode": ChuteStartControlMode.INLET_CONTROL.value,
            "depth_m": round(depth, 6),
            "source": "进口控制段计算",
            "message": "本次按进口控制段或闸门控制水深作为陡槽起点控制水深。",
        }
    if _has_value(data, "model_test_start_depth"):
        depth = _first_float(data, ("model_test_start_depth", "actual_control_depth", "h_control"), critical_depth)
        return {
            "mode": ChuteStartControlMode.MODEL_TEST.value,
            "depth_m": round(depth, 6),
            "source": "模型试验或专项复核",
            "message": "本次按模型试验或专项复核给出的控制水深作为陡槽起点。",
        }
    if _has_value(data, "manual_start_depth"):
        depth = _first_float(data, ("manual_start_depth", "actual_control_depth", "h_control"), critical_depth)
        return {
            "mode": ChuteStartControlMode.MANUAL.value,
            "depth_m": round(depth, 6),
            "source": "人工指定",
            "message": "本次按人工指定的实际控制水深作为陡槽起点控制水深。",
        }
    if profile_mode == ChuteProfileCalcMode.LENGTH_BY_TWO_DEPTHS.value and _has_value(data, "start_depth"):
        depth = _first_float(data, ("start_depth", "h_start"), critical_depth)
        if depth > 0:
            return {
                "mode": ChuteStartControlMode.MANUAL.value,
                "depth_m": depth,
                "source": "已知起点水深",
                "message": "已知两端水深模式按用户输入的起点水深推求水面线长度。",
            }

    if mode_text not in {"critical_depth", "critical", "临界水深"} and any(
        _has_value(data, key) for key in ("start_depth", "h_start")
    ):
        return {
            "mode": ChuteStartControlMode.MANUAL.value,
            "depth_m": _first_float(data, ("start_depth", "h_start"), critical_depth),
            "source": "已知起点水深",
            "message": "按输入的实际起点水深计算，不自动改写为临界水深。",
        }
    return {
        "mode": ChuteStartControlMode.CRITICAL_DEPTH.value,
        "depth_m": critical_depth,
        "source": "临界水深",
        "message": "标准自由衔接时，陡槽起点按临界水深控制；上游正常水深只用于衔接校核，不直接作为陡槽起点。",
    }


def _upstream_connection_result(data: Dict[str, Any], hydraulic: Dict[str, Any], start_control: Dict[str, Any]) -> Dict[str, Any]:
    """生成上游缓坡接陡坡的衔接说明。"""
    upstream_normal = _first_float(data, ("upstream_normal_depth", "upstream_channel_normal_depth"), 0.0)
    mode = str(data.get("upstream_connection_mode") or "").strip().lower()
    is_free = mode in {"free_to_steep", "free", "自由衔接"} or str(data.get("upstream_channel_slope_type", "")).lower() in {"mild", "缓坡"}
    if not is_free and upstream_normal <= 0:
        is_free = True
    message = "上游缓坡自由接陡坡时，陡槽入口按临界水深形成控制；上游正常水深不直接作为陡槽起点。"
    if start_control.get("mode") != ChuteStartControlMode.CRITICAL_DEPTH.value:
        message = f"本次起点水深来自{start_control.get('source', '实际控制')}，上游正常水深仅用于校核衔接关系。"
    upstream_profile_type = None
    if (
        is_free
        and start_control.get("mode") == ChuteStartControlMode.CRITICAL_DEPTH.value
        and upstream_normal > hydraulic.get("critical_depth_m", 0.0)
    ):
        upstream_profile_type = "b_1"
    return {
        "type": "上游缓坡接陡坡" if is_free else "上游控制衔接",
        "start_depth_source": start_control.get("mode"),
        "control_depth_m": start_control.get("depth_m"),
        "critical_depth_m": hydraulic.get("critical_depth_m"),
        "upstream_normal_depth_m": round(upstream_normal, 6) if upstream_normal > 0 else None,
        "water_profile_type": upstream_profile_type,
        "message": message,
    }


def _validate_input(data: Dict[str, Any]) -> Tuple[Dict[str, float], List[str]]:
    """校验快速计算输入并整理基础参数。"""
    raw_m = _first_float(data, ("m", "side_slope", "slope_coefficient"), 0.0)
    section_type = _normalize_section_type(
        data.get("section_type") or (ChuteSectionType.RECTANGULAR.value if abs(raw_m) < 1e-12 else ChuteSectionType.TRAPEZOIDAL.value)
    )
    m = 0.0 if section_type == ChuteSectionType.RECTANGULAR.value else raw_m
    slope = _first_float(data, ("i", "slope", "bed_slope", "slope_i"), 0.0)
    slope_inv = _first_float(data, ("slope_inv", "slope_inverse"), 0.0)
    if slope <= 0 and slope_inv > 0:
        slope = 1.0 / slope_inv
    params = {
        "Q": _first_float(data, ("Q", "flow", "design_flow", "design_flow_m3s"), 0.0),
        "b": _first_float(data, ("b", "bottom_width", "channel_width", "bed_width"), 0.0),
        "m": m,
        "i": slope,
        "n": _first_float(data, ("n", "roughness", "manning_n"), 0.0),
        "L": _first_float(data, ("L", "length", "chute_length"), 0.0),
    }
    errors: List[str] = []
    for key in ("start_water_level", "start_bed_elevation", "start_station"):
        if _has_value(data, key):
            value = _first_optional_float(data, (key,))
            if value is None or not math.isfinite(value):
                errors.append(f"参数 {key} 必须为有限数值，高程允许为零或负值。")
    for key, value in params.items():
        if not math.isfinite(value):
            errors.append(f"参数 {key} 必须为有限数值。")
    for key in ("alpha_profile", "critical_alpha", "depth_step", "Q_increased", "increase_flow", "increased_flow_start_depth", "jump_alpha", "energy_dissipation_alpha", "alpha_j", "pool_depth_factor", "stilling_pool_factor"):
        if _has_value(data, key):
            value = _first_optional_float(data, (key,))
            if value is None or not math.isfinite(value) or value <= 0:
                errors.append(f"参数 {key} 必须为有限正数。")
    for key in ("aeration_coefficient", "sidewall_freeboard_m", "allow_backwater_m"):
        if _has_value(data, key):
            value = _first_optional_float(data, (key,))
            if value is None or not math.isfinite(value) or value < 0:
                errors.append(f"参数 {key} 必须为有限非负数。")
    if params["Q"] <= 0:
        errors.append("设计流量 Q 必须大于 0。")
    if params["b"] <= 0:
        errors.append("底宽 b 必须大于 0。")
    if params["m"] < 0:
        errors.append("边坡系数 m 不能小于 0。")
    if params["i"] <= 0:
        errors.append("底坡 i 必须大于 0。")
    if params["n"] <= 0:
        errors.append("糙率 n 必须大于 0。")
    return params, errors


def _build_error_result(errors: List[str]) -> Dict[str, Any]:
    """构造校验失败时的统一返回值。"""
    return {
        "success": False,
        "errors": errors,
        "warnings": [],
        "summary": {"计算状态": "失败", "错误": "；".join(errors)},
        "hydraulic": {},
        "profile": {"available": False, "status": "unavailable_invalid_input", "points": []},
        "profile_points": [],
        "inlet_weir": {
            "passed": None,
            "capacity_m3s": None,
            "capacity_ratio": None,
            "coefficient": None,
            "contraction_coefficient": None,
        },
        "discharge_hint": _discharge_hint(0.0),
        "code_checks": [],
        "checks": [],
        "formula_cards": _formula_cards(),
        "formulas": _formula_cards(),
        "risks": errors,
        "example": {},
    }


def _round_metrics(metrics: Dict[str, float]) -> Dict[str, float]:
    """把断面水力要素整理为前端友好的精度。"""
    return {key: round(value, 6) for key, value in metrics.items()}


def _build_hydraulic_summary(
    section_type: str,
    Q: float,
    b: float,
    m: float,
    i: float,
    n: float,
    normal_depth: float,
    critical_depth: float,
    critical_slope: float,
    start_depth: float,
    alpha_profile: float,
) -> Dict[str, Any]:
    """汇总基础水力计算结果。"""
    normal_metrics = _section_metrics(Q, b, normal_depth, m, n, alpha_profile)
    critical_metrics = _section_metrics(Q, b, critical_depth, m, n, alpha_profile)
    start_metrics = _section_metrics(Q, b, start_depth, m, n, alpha_profile)
    return {
        "section_type": section_type,
        "normal_depth_m": round(normal_depth, 6),
        "critical_depth_m": round(critical_depth, 6),
        "critical_slope": round(critical_slope, 8),
        "slope_type": _slope_type(i, critical_slope),
        "normal": _round_metrics(normal_metrics),
        "critical": _round_metrics(critical_metrics),
        "start": _round_metrics(start_metrics),
        "froude_at_start": round(start_metrics["froude"], 6),
        "specific_energy_start_m": round(start_metrics["specific_energy_m"], 6),
        "hydraulic_slope_at_normal": round(normal_metrics["hydraulic_slope"], 8),
        "water_top_width_at_critical_m": round(critical_metrics["water_top_width_m"], 6),
        "water_profile_energy_alpha": round(alpha_profile, 6),
    }


def _segment_length(Q: float, b: float, m: float, n: float, i: float, h1: float, h2: float, alpha_profile: float) -> Tuple[float, str]:
    """按固定水深步长反推相邻两水深间的距离。"""
    metrics_1 = _section_metrics(Q, b, h1, m, n, alpha_profile)
    metrics_2 = _section_metrics(Q, b, h2, m, n, alpha_profile)
    energy_diff = metrics_2["specific_energy_m"] - metrics_1["specific_energy_m"]
    avg_j = (metrics_1["hydraulic_slope"] + metrics_2["hydraulic_slope"]) / 2.0
    denominator = i - avg_j
    if abs(denominator) < 1e-15:
        return 0.0, "invalid_energy_slope"
    if energy_diff / denominator <= 0:
        return 0.0, "invalid_energy_change"
    return energy_diff / denominator, ""


def _append_profile_point(
    points: List[Dict[str, float]],
    distance: float,
    Q: float,
    b: float,
    m: float,
    n: float,
    i: float,
    depth: float,
    start_bed_elevation: float = 0.0,
    start_station: float = 0.0,
    alpha_profile: float = DEFAULT_PROFILE_ALPHA,
) -> None:
    """追加一个水面线计算点。"""
    metrics = _section_metrics(Q, b, depth, m, n, alpha_profile)
    bed_elevation = start_bed_elevation - i * distance
    point = ChuteProfilePoint(
        distance_m=round(distance, 6),
        station_m=round(start_station + distance, 6),
        bed_elevation_m=round(bed_elevation, 6),
        water_elevation_m=round(bed_elevation + depth, 6),
        depth_m=round(depth, 6),
        area_m2=round(metrics["area_m2"], 6),
        wetted_perimeter_m=round(metrics["wetted_perimeter_m"], 6),
        hydraulic_radius_m=round(metrics["hydraulic_radius_m"], 6),
        water_top_width_m=round(metrics["water_top_width_m"], 6),
        velocity_ms=round(metrics["velocity_ms"], 6),
        froude=round(metrics["froude"], 6),
        hydraulic_slope=round(metrics["hydraulic_slope"], 8),
        specific_energy_m=round(metrics["specific_energy_m"], 6),
    )
    points.append(
        asdict(point)
    )


def _curve_to_depth(
    Q: float,
    b: float,
    m: float,
    n: float,
    i: float,
    start_depth: float,
    end_depth: float,
    depth_step: float,
    start_bed_elevation: float,
    start_station: float,
    alpha_profile: float,
) -> Dict[str, Any]:
    """计算从起点水深到目标水深的完整距离曲线。"""
    normal_depth = _solve_profile_normal_depth(Q, b, m, n, i)
    critical_depth = _solve_critical_depth(Q, b, m, alpha_profile)
    depth_tol = max(1e-10, normal_depth * 1e-10)
    if (
        min(start_depth, end_depth) <= 0
        or max(start_depth, end_depth) > critical_depth + 1e-6
        or (start_depth - normal_depth) * (end_depth - normal_depth) <= 0
        or abs(end_depth - normal_depth) <= depth_tol
        or abs(end_depth - normal_depth) >= abs(start_depth - normal_depth)
    ):
        return {
            "available": False,
            "status": "invalid_profile_branch",
            "points": [],
            "length_m": None,
            "start_depth_m": round(start_depth, 6),
            "end_depth_m": None,
            "target_depth_m": round(end_depth, 6),
            "message": "两端水深须在同一急流分支并沿程趋近正常水深；不能跨越正常水深、临界水深，也不能在有限距离精确到达正常水深。",
        }
    points: List[Dict[str, float]] = []
    distance = 0.0
    _append_profile_point(points, distance, Q, b, m, n, i, start_depth, start_bed_elevation, start_station, alpha_profile)
    h1 = start_depth
    direction = 1.0 if end_depth > start_depth else -1.0
    depth_step = depth_step if depth_step > 0 else DEFAULT_DEPTH_STEP
    for _ in range(20000):
        step = min(depth_step, 0.05 * h1, 0.1 * abs(h1 - normal_depth), abs(end_depth - h1))
        h2 = h1 + direction * step
        ds, status = _segment_length(Q, b, m, n, i, h1, h2, alpha_profile)
        if status:
            return {
                "available": False,
                "status": status,
                "points": points,
                "length_m": round(distance, 6),
                "end_depth_m": round(h1, 6),
            }
        distance += ds
        _append_profile_point(points, distance, Q, b, m, n, i, h2, start_bed_elevation, start_station, alpha_profile)
        if abs(h2 - end_depth) < 1e-12:
            break
        h1 = h2
    else:
        return {"available": False, "status": "iteration_limit", "points": points,
                "message": "水面线未在迭代上限内达到目标水深。"}
    return {
        "available": True,
        "status": "ok",
        "points": points,
        "length_m": round(distance, 6),
        "end_depth_m": round(end_depth, 6),
        "end_reason": "reached_target_depth",
    }


def _end_depth_by_length(
    Q: float,
    b: float,
    m: float,
    n: float,
    i: float,
    start_depth: float,
    normal_depth: float,
    length: float,
    depth_step: float,
    start_bed_elevation: float,
    start_station: float,
    alpha_profile: float,
) -> Dict[str, Any]:
    """急流沿程趋近正常水深，末段以能量方程求根到指定长度。"""
    if length <= 0:
        return {"available": False, "status": "missing_length", "points": []}
    points: List[Dict[str, float]] = []
    distance = 0.0
    _append_profile_point(points, distance, Q, b, m, n, i, start_depth, start_bed_elevation, start_station, alpha_profile)
    normal_depth = _solve_profile_normal_depth(Q, b, m, n, i)
    depth_step = depth_step if depth_step > 0 else DEFAULT_DEPTH_STEP
    direction = 1.0 if start_depth < normal_depth else -1.0
    h1 = start_depth
    near_normal_tolerance = max(1e-10, normal_depth * 1e-10)
    normal_approximation = False
    for _ in range(20000):
        gap = abs(h1 - normal_depth)
        if gap <= near_normal_tolerance:
            # 余下距离内的水深差已小于数值精度，以均匀流延伸到真实末端。
            normal_approximation = True
            _append_profile_point(points, length, Q, b, m, n, i, normal_depth, start_bed_elevation, start_station, alpha_profile)
            break
        h2 = h1 + direction * min(depth_step, 0.05 * h1, 0.1 * gap)
        ds, status = _segment_length(Q, b, m, n, i, h1, h2, alpha_profile)
        if status:
            return {"available": False, "status": status, "points": points}
        if distance + ds >= length:
            # 水深与距离并非线性，末段须重解能量平衡而非线性插值。
            remaining = length - distance
            low, high = 0.0, 1.0
            for _ in range(70):
                ratio = (low + high) / 2.0
                trial_depth = h1 + (h2 - h1) * ratio
                trial_distance, trial_status = _segment_length(Q, b, m, n, i, h1, trial_depth, alpha_profile)
                if trial_status or trial_distance < remaining:
                    low = ratio
                else:
                    high = ratio
            end_depth = h1 + (h2 - h1) * ((low + high) / 2.0)
            _append_profile_point(points, length, Q, b, m, n, i, end_depth, start_bed_elevation, start_station, alpha_profile)
            return {
                "available": True,
                "status": "ok",
                "points": points,
                "length_m": round(length, 6),
                "end_depth_m": round(end_depth, 6),
                "end_reason": "reached_length",
            }
        distance += ds
        _append_profile_point(points, distance, Q, b, m, n, i, h2, start_bed_elevation, start_station, alpha_profile)
        h1 = h2
    else:
        return {"available": False, "status": "iteration_limit", "points": points,
                "message": "水面线未在迭代上限内达到指定长度。"}
    return {
        "available": True,
        "status": "ok",
        "points": points,
        "length_m": round(length, 6),
        "end_depth_m": round(normal_depth, 6),
        "end_reason": "reached_length",
        "normal_depth_approximation": normal_approximation,
        "normal_depth_tolerance_m": near_normal_tolerance,
    }


def _profile_result(
    data: Dict[str, Any],
    params: Dict[str, float],
    hydraulic: Dict[str, Any],
    start_control: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """根据水面线模式计算陡槽水面线。"""
    start_control = start_control or _resolve_start_control(data, hydraulic)
    profile_type_info = _water_profile_type(
        hydraulic["slope_type"],
        float(start_control.get("depth_m") or hydraulic["critical_depth_m"]),
        hydraulic["normal_depth_m"],
        hydraulic["critical_depth_m"],
        data,
    )
    if hydraulic["slope_type"] != "steep":
        return {
            "available": False,
            "status": "unavailable_non_steep_slope",
            "points": [],
            "message": "非陡坡工况不按 b2 型降水曲线计算水面线。",
            "water_profile_type": profile_type_info["type"],
            "profile_type": profile_type_info["type"],
            "water_profile_name": profile_type_info["name"],
            "water_profile_message": profile_type_info["message"],
            "start_control": start_control,
            "water_profile_energy_alpha": _profile_energy_alpha(data),
        }

    mode = str(data.get("profile_mode", ChuteProfileCalcMode.END_DEPTH_BY_LENGTH.value)).strip().upper()
    Q, b, m, n, i = params["Q"], params["b"], params["m"], params["n"], params["i"]
    start_depth = float(start_control.get("depth_m", hydraulic["critical_depth_m"]))
    normal_depth = _solve_profile_normal_depth(Q, b, m, n, i)
    depth_step = _as_float(data, "depth_step", DEFAULT_DEPTH_STEP)
    start_bed_elevation = _first_float(data, ("start_bed_elevation", "start_z", "bed_elevation_start"), 0.0)
    start_station = _first_float(data, ("start_station", "station_start"), 0.0)
    alpha_profile = _profile_energy_alpha(data)
    critical_depth = _solve_critical_depth(Q, b, m, alpha_profile)
    if start_control.get("mode") == ChuteStartControlMode.CRITICAL_DEPTH.value:
        start_depth = critical_depth
        start_control["depth_m"] = critical_depth
    if start_depth <= 0 or start_depth > critical_depth + 1e-6:
        return {
            "available": False, "status": "unsupported_start_branch", "points": [],
            "message": "入口水深必须大于零且位于急流分支；缓流须由下游边界反推，不能按陡槽急流向下游计算。",
            "start_control": start_control, "water_profile_type": profile_type_info["type"],
            "water_profile_energy_alpha": alpha_profile,
        }

    if mode == ChuteProfileCalcMode.LENGTH_BY_TWO_DEPTHS.value:
        end_depth = _first_float(data, ("end_depth", "target_depth", "h_end"), normal_depth)
        result = _curve_to_depth(Q, b, m, n, i, start_depth, end_depth, depth_step, start_bed_elevation, start_station, alpha_profile)
        result["mode"] = mode
        result["water_profile_type"] = profile_type_info["type"]
        result["profile_type"] = profile_type_info["type"]
        result["water_profile_name"] = profile_type_info["name"]
        result["water_profile_message"] = profile_type_info["message"]
        result["start_control"] = start_control
        result["water_profile_energy_alpha"] = alpha_profile
        return result

    if mode == ChuteProfileCalcMode.FULL_CURVE_TO_NORMAL.value:
        # 正常水深是渐近线；终点定义为距正常水深不超过千分之一且至少一毫米。
        normal_tolerance = max(0.001, normal_depth * 0.001)
        gap = start_depth - normal_depth
        if abs(gap) <= normal_tolerance:
            points: List[Dict[str, float]] = []
            _append_profile_point(points, 0.0, Q, b, m, n, i, start_depth, start_bed_elevation, start_station, alpha_profile)
            result = {"available": True, "status": "ok", "points": points, "length_m": 0.0,
                      "end_depth_m": round(start_depth, 6)}
        else:
            target_depth = normal_depth + math.copysign(normal_tolerance, gap)
            result = _curve_to_depth(Q, b, m, n, i, start_depth, target_depth, depth_step, start_bed_elevation, start_station, alpha_profile)
        result["mode"] = mode
        if result.get("available"):
            result["end_reason"] = "approached_normal_depth"
            result["normal_depth_tolerance_m"] = normal_tolerance
            result["message"] = "已计算至接近正常水深；正常水深为渐近线，该长度是达到给定近似精度的距离。"
        result["water_profile_type"] = profile_type_info["type"]
        result["profile_type"] = profile_type_info["type"]
        result["water_profile_name"] = profile_type_info["name"]
        result["water_profile_message"] = profile_type_info["message"]
        result["start_control"] = start_control
        result["water_profile_energy_alpha"] = alpha_profile
        return result

    result = _end_depth_by_length(Q, b, m, n, i, start_depth, normal_depth, params["L"], depth_step, start_bed_elevation, start_station, alpha_profile)
    result["mode"] = ChuteProfileCalcMode.END_DEPTH_BY_LENGTH.value
    result["water_profile_type"] = profile_type_info["type"]
    result["profile_type"] = profile_type_info["type"]
    result["water_profile_name"] = profile_type_info["name"]
    result["water_profile_message"] = profile_type_info["message"]
    result["start_control"] = start_control
    result["water_profile_energy_alpha"] = alpha_profile
    return result


def _inlet_coefficient(data: Dict[str, Any], width: float, head: float) -> Dict[str, Any]:
    """根据入口连接形式或手动输入确定跌口流量系数。"""
    connection = _normalize_inlet_connection_type(
        data.get("inlet_connection_type")
        or data.get("inlet_connection_type_label")
        or data.get("inlet_connection")
        or data.get("connection_type")
    )
    manual_mu = _first_optional_float(data, ("weir_coefficient", "inlet_discharge_coefficient", "mu"))
    if connection == InletConnectionType.MANUAL_COEFFICIENT.value or (not connection and manual_mu is not None):
        return {
            "connection_type": InletConnectionType.MANUAL_COEFFICIENT.value,
            "coefficient": manual_mu,
            "coefficient_source": "用户手动输入",
            "coefficient_formula": "手动输入",
        }
    if connection == InletConnectionType.WARPED_SURFACE.value:
        return {
            "connection_type": connection,
            "coefficient": 0.474 - 0.018 * width / head,
            "coefficient_source": "GB 50288-2018 附录 N",
            "coefficient_formula": "0.474-0.018b_c/H_0",
        }
    if connection == InletConnectionType.SPLAY_WALL.value:
        return {
            "connection_type": connection,
            "coefficient": 0.470 - 0.017 * width / head,
            "coefficient_source": "GB 50288-2018 附录 N",
            "coefficient_formula": "0.470-0.017b_c/H_0",
        }
    if connection == InletConnectionType.DIAPHRAGM_WALL.value:
        return {
            "connection_type": connection,
            "coefficient": 0.402 - 0.008 * width / head,
            "coefficient_source": "GB 50288-2018 附录 N",
            "coefficient_formula": "0.402-0.008b_c/H_0",
        }
    return {
        "connection_type": connection,
        "coefficient": None,
        "coefficient_source": "",
        "coefficient_formula": "",
    }


def _inlet_weir(data: Dict[str, Any], Q: float, b: float) -> Dict[str, Any]:
    """按 GB 50288-2018 附录 N 的宽顶堰公式计算入口过流能力。"""
    width = _first_float(data, ("inlet_weir_width", "weir_width", "notch_width", "bc"), b)
    head = _first_float(data, ("inlet_head", "H0", "upstream_weir_depth"), 0.0)
    epsilon = _first_float(data, ("contraction_coefficient", "inlet_contraction_coefficient", "epsilon"), 1.0)
    base = {
        "passed": None,
        "capacity_m3s": None,
        "capacity_ratio": None,
        "width_m": width,
        "head_m": head,
        "head_source": "用户直接输入堰上总水头 H0",
        "head_note": "本版本不自动由堰前水深和流速水头推导 H0。",
        "contraction_coefficient": epsilon,
        "supported_scope": "当前支持矩形跌口或等底宽陡坡入口校核",
        "connection_type": "",
        "coefficient": None,
        "coefficient_source": "",
        "coefficient_formula": "",
    }
    if width <= 0 or head <= 0 or epsilon <= 0 or Q <= 0:
        base["message"] = "未提供完整入口宽顶堰参数，暂不校核过流能力。"
        return base
    coefficient = _inlet_coefficient(data, width, head)
    base.update(coefficient)
    mu = coefficient.get("coefficient")
    if mu is None:
        base["message"] = "入口流量系数缺失，暂不校核过流能力。"
        return base
    if mu <= 0:
        base["message"] = "入口流量系数计算值无效，暂不校核过流能力。"
        return base
    capacity = epsilon * mu * width * math.sqrt(2.0 * G) * head ** 1.5
    ratio = capacity / Q
    base.update(
        {
            "passed": ratio >= 1.0,
            "capacity_m3s": round(capacity, 6),
            "capacity_ratio": round(ratio, 6),
            "coefficient": round(mu, 6),
            "message": "入口过流能力满足设计流量。" if ratio >= 1.0 else "入口过流能力不足，应调整跌口宽度、堰上水头或建筑物形式。",
        }
    )
    return base


def _discharge_hint(Q: float) -> Dict[str, Any]:
    """生成泄退水流量提示。"""
    return {
        "title": "泄(退)水设计流量提示",
        "design_flow_m3s": round(Q, 6) if Q > 0 else None,
        "message": "本内核按用户输入的泄(退)水设计流量进行水力计算；多工况时宜取控制工况复核。",
    }


def _code_checks(data: Dict[str, Any], params: Dict[str, float], hydraulic: Dict[str, Any], profile: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """生成可程序化的规范布置校核提示。"""
    b = params["b"]
    checks: List[Dict[str, Any]] = []
    upstream = _first_float(data, ("upstream_straight_length", "upstream_length"), -1.0)
    downstream = _first_float(data, ("downstream_straight_length", "downstream_length"), -1.0)
    if upstream >= 0:
        width = _first_optional_float(data, ("upstream_channel_width",))
        passed = upstream > 10.0 * width if width is not None and width > 0 else None
        checks.append({"item": "上游直线段", "name": "上游直线段", "passed": passed, "result": "通过" if passed else "待核渠宽" if passed is None else "需复核", "message": "GB 50288-2018 第12.1.5条：连接处上游直线段应大于上游渠道底宽的10倍；未提供渠宽时不以陡槽宽代替。"})
    if downstream >= 0:
        width = _first_optional_float(data, ("downstream_channel_width",))
        passed = downstream > 10.0 * width if width is not None and width > 0 else None
        checks.append({"item": "下游直线段", "name": "下游直线段", "passed": passed, "result": "通过" if passed else "待核渠宽" if passed is None else "需复核", "message": "GB 50288-2018 第12.1.5条：连接处下游直线段应大于下游渠道底宽的10倍；未提供渠宽时不以陡槽宽代替。"})
    profile_points = (profile or {}).get("points") or []
    velocities = [float(hydraulic.get("start", {}).get("velocity_ms", 0.0) or 0.0)]
    velocities.extend(float(point.get("velocity_ms", 0.0) or 0.0) for point in profile_points)
    velocity = max(velocities, default=0.0)
    velocity_passed = velocity <= 10.0
    checks.append(
        {
            "item": "高流速措施",
            "name": "高流速措施",
            "passed": velocity_passed,
            "result": "未触发高速措施提示" if velocity_passed else "需复核",
            "message": "GB 50288-2018 第12.2.4条：流速大于10米/秒时需考虑掺气、加糙或台阶等措施；未触发该阈值不代表材料抗冲验算已通过。",
        }
    )
    allow_velocity = _first_float(data, ("material_allow_velocity", "allow_velocity", "permissible_velocity"), 0.0)
    if allow_velocity > 0:
        passed = velocity <= allow_velocity
        checks.append(
            {
                "item": "材料允许流速",
                "name": "材料允许流速",
                "passed": passed,
                "result": "通过" if passed else "需复核",
                "message": f"沿程最大流速为 {velocity:.3f} 米/秒，材料允许流速为 {allow_velocity:.3f} 米/秒。",
            }
        )
    if _has_value(data, "axis_bend_angle_deg"):
        angle = abs(_as_float(data, "axis_bend_angle_deg", 0.0))
        checks.append(
            {
                "item": "轴线转折",
                "name": "轴线转折",
                "passed": None,
                "result": "需专项复核",
                "message": f"轴线转折角为 {angle:.2f}°。GB 50288-2018 第12.1.5条要求采取措施克服折冲波；仅凭角度不能判定通过。",
            }
        )
    if _has_value(data, "inlet_contraction_angle_deg"):
        angle = abs(_as_float(data, "inlet_contraction_angle_deg", 0.0))
        checks.append(
            {
                "item": "进口收缩",
                "name": "进口收缩",
                "passed": None,
                "result": "待核进口形式",
                "message": f"进口收缩角为 {angle:.2f}°。GB 50288-2018 第12.2.3条对不同进口形式规定不同角度，未确定形式时不以统一20°判定。",
            }
        )
    if params["i"] > 0:
        checks.append(
            {
                "item": "底坡范围",
                "name": "底坡范围",
                "passed": None,
                "result": "条件提示",
                "message": "GB 50288-2018 第12.2.4条的陡槽坡度取决于地形、地基及材料；本水面线采用小坡角渐变流近似，几何陡坡需复核法向水深和重力分量，不能用固定0.35阈值判定规范通过。",
            }
        )
    if params["i"] > 0.02:
        depths = [float(point["depth_m"]) for point in profile_points] or [hydraulic.get("normal_depth_m", 0.0)]
        perimeter_passed = all(depth > 0 and calculate_wetted_perimeter(params["b"], depth, params["m"]) < 10.0 * depth for depth in depths)
        checks.append(
            {
                "item": "湿周限制",
                "name": "湿周限制",
                "passed": perimeter_passed,
                "result": "通过" if perimeter_passed else "需复核",
                "message": "GB 50288-2018 第12.2.4条：陡槽纵坡大于0.02时，湿周宜小于10倍水深。" + ("已逐点检查沿程水深。" if profile_points else "当前仅有正常水深初查，尚无沿程结果。"),
            }
        )
    return checks


def _formula_cards() -> List[Dict[str, str]]:
    """返回前端公式卡片。"""
    return [
        {
            "title": "曼宁公式",
            "name": "曼宁公式",
            "latex": r"Q=\frac{1}{n}AR^{2/3}i^{1/2}",
            "expression": r"Q=\frac{1}{n}AR^{2/3}i^{1/2}",
            "source": "GB 50288-2018 与明渠均匀流理论",
        },
        {
            "title": "临界水深",
            "name": "临界水深",
            "latex": r"\frac{\alpha Q^2}{g}=\frac{A_k^3}{B_k}",
            "expression": r"\frac{\alpha Q^2}{g}=\frac{A_k^3}{B_k}",
            "source": "教材断面比能和临界流理论",
        },
        {
            "title": "临界底坡",
            "name": "临界底坡",
            "latex": r"i_k=\left(\frac{nQ}{A_kR_k^{2/3}}\right)^2",
            "expression": r"i_k=\left(\frac{nQ}{A_kR_k^{2/3}}\right)^2",
            "source": "教材临界底坡理论",
        },
        {
            "title": "断面比能",
            "name": "断面比能",
            "latex": r"E_s=h+\alpha_e\frac{v^2}{2g}",
            "expression": r"E_s=h+\alpha_e\frac{v^2}{2g}",
            "source": "明渠恒定非均匀流理论",
        },
        {
            "title": "水力坡度",
            "name": "水力坡度",
            "latex": r"J=\left(\frac{nQ}{AR^{2/3}}\right)^2",
            "expression": r"J=\left(\frac{nQ}{AR^{2/3}}\right)^2",
            "source": "曼宁公式反算",
        },
        {
            "title": "逐段距离",
            "name": "逐段能量方程",
            "latex": r"\Delta s=\frac{E_{s,j+1}-E_{s,j}}{i-\overline{J}}",
            "expression": r"E_{s,j+1}-E_{s,j}=(i-\overline{J})\Delta s",
            "source": "逐段试算法",
        },
        {
            "title": "宽顶堰过流能力",
            "name": "宽顶堰过流能力",
            "latex": r"Q_{\text{cap}}=\varepsilon\mu b_c\sqrt{2g}H_0^{3/2}",
            "expression": r"Q_{\text{cap}}=\varepsilon\mu b_c\sqrt{2g}H_0^{3/2}",
            "source": "GB 50288-2018 附录 N",
        },
        {
            "title": "掺气水深",
            "name": "掺气水深",
            "latex": r"h_b=\left(1+\frac{\zeta v}{100}\right)h",
            "expression": r"h_b=\left(1+\frac{\zeta v}{100}\right)h",
            "source": "GB 50288-2018 附录 N",
        },
        {
            "title": "矩形断面共轭水深",
            "name": "矩形断面共轭水深",
            "latex": r"h_c''=\frac{h_c'}{2}\left(\sqrt{1+8Fr_1^2}-1\right)",
            "expression": r"h_c''=\frac{h_c'}{2}\left(\sqrt{1+8Fr_1^2}-1\right)",
            "source": "水跃理论",
        },
        {
            "title": "消力池初拟尺寸",
            "name": "消力池初拟尺寸",
            "latex": r"L_d=4.5h_c'',\quad d_d\geq \lambda h_c''-h_s,\quad 1.10\leq\lambda\leq1.15",
            "expression": r"L_d=4.5h_c'', d_d\geq \lambda h_c''-h_s",
            "source": "GB 50288-2018 N.2.5：单级等底宽陡坡、同宽矩形池；hs为实际池后水深",
        },
        {
            "title": "出口整流段",
            "name": "出口整流段",
            "latex": r"L_r=\max\left(L_{\Delta b},\eta h_c'',L_{\min}\right)",
            "expression": r"L_r=max(L_{\Delta b},\eta h_c'',L_{\min})",
            "source": "出口连接段整流布置校核口径",
        },
    ]


def _example_info(params: Dict[str, float]) -> Dict[str, Any]:
    """识别并返回内置教学算例信息。"""
    is_xiong = (
        abs(params["Q"] - 20.0) < 1e-9
        and abs(params["b"] - 1.0) < 1e-9
        and abs(params["m"] - 1.5) < 1e-9
        and abs(params["i"] - 0.02) < 1e-9
        and abs(params["n"] - 0.014) < 1e-9
    )
    if not is_xiong:
        return {}
    return {"name": "熊启钧棱柱体陡坡算例", "reference_end_depth_m": 1.199, "reference_length_m": 80.0}


def _build_summary(data: Dict[str, Any], params: Dict[str, float], hydraulic: Dict[str, Any], profile: Dict[str, Any], inlet: Dict[str, Any]) -> Dict[str, Any]:
    """生成前端汇总页和导出使用的中文摘要。"""
    points = profile.get("points") or []
    max_velocity = max((point.get("velocity_ms", 0.0) for point in points), default=hydraulic.get("start", {}).get("velocity_ms", 0.0))
    max_froude = max((point.get("froude", 0.0) for point in points), default=hydraulic.get("start", {}).get("froude", 0.0))
    slope_label = {"steep": "陡坡", "mild": "缓坡", "critical": "临界坡", "unknown": "未识别"}.get(hydraulic.get("slope_type"), "未识别")
    summary = {
        "工程名称": data.get("project_name") or data.get("structure_name") or "泄水渠与陡坡",
        "设计流量": f"{params['Q']:.3f} 立方米/秒",
        "正常水深": f"{hydraulic['normal_depth_m']:.3f} 米",
        "临界水深": f"{hydraulic['critical_depth_m']:.3f} 米",
        "临界底坡": f"{hydraulic['critical_slope']:.6f}",
        "实际底坡": f"{params['i']:.6f}",
        "坡型": slope_label,
        "起点水深": f"{hydraulic['start']['depth_m']:.3f} 米",
        "末端水深": f"{profile.get('end_depth_m', '')} 米" if profile.get("available") else "未计算",
        "最大流速": f"{max_velocity:.3f} 米/秒",
        "最大弗劳德数": f"{max_froude:.3f}",
        "水面线动能修正系数": f"{float(hydraulic.get('water_profile_energy_alpha', DEFAULT_PROFILE_ALPHA)):.3f}",
        "入口过流能力比": f"{inlet['capacity_ratio']:.3f}" if inlet.get("capacity_ratio") is not None else "未校核",
    }
    if inlet.get("connection_type"):
        summary["入口连接形式"] = str(inlet.get("connection_type"))
    if inlet.get("coefficient") is not None:
        summary["入口流量系数"] = f"{float(inlet['coefficient']):.3f}"
    if inlet.get("coefficient_source"):
        summary["入口流量系数来源"] = str(inlet.get("coefficient_source"))
    if inlet.get("contraction_coefficient") is not None:
        summary["入口侧收缩系数"] = f"{float(inlet['contraction_coefficient']):.3f}"
    return summary


def _profile_points_for_view(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把内核沿程点补充为前端和导出兼容字段。"""
    rows: List[Dict[str, Any]] = []
    for point in profile.get("points") or []:
        row = dict(point)
        row.setdefault("x", point.get("distance_m", 0.0))
        row.setdefault("distance", point.get("distance_m", 0.0))
        row.setdefault("bed_elevation", point.get("bed_elevation_m", ""))
        row.setdefault("water_elevation", point.get("water_elevation_m", ""))
        row.setdefault("depth", point.get("depth_m", ""))
        rows.append(row)
    return rows


def _add_aeration_and_sidewall(data: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """为沿程点补充掺气水深、掺气水位和侧墙顶线。"""
    points = (profile.get("points") or []) if profile.get("available") else []
    zeta = _first_float(data, ("aeration_coefficient", "zeta", "ζ"), 1.2)
    backwater = _first_float(data, ("allow_backwater_m", "backwater_allowance_m"), 0.0)
    freeboard = _first_float(data, ("sidewall_freeboard_m", "freeboard_m", "Fb"), 0.4)
    max_aerated_depth = 0.0
    max_sidewall_height = 0.0
    for point in points:
        depth = float(point.get("depth_m", 0.0) or 0.0)
        velocity = float(point.get("velocity_ms", 0.0) or 0.0)
        bed_elevation = float(point.get("bed_elevation_m", 0.0) or 0.0)
        aerated_depth = depth * (1.0 + zeta * velocity / 100.0)
        aeration_increment = max(0.0, aerated_depth - depth)
        sidewall_height = aerated_depth + backwater + freeboard
        point["aerated_depth_m"] = round(aerated_depth, 6)
        point["aeration_increment_m"] = round(aeration_increment, 6)
        point["aerated_water_elevation_m"] = round(bed_elevation + aerated_depth, 6)
        point["sidewall_height_m"] = round(sidewall_height, 6)
        point["sidewall_top_elevation_m"] = round(bed_elevation + sidewall_height, 6)
        max_aerated_depth = max(max_aerated_depth, aerated_depth)
        max_sidewall_height = max(max_sidewall_height, sidewall_height)
    return {
        "enabled": bool(profile.get("available") and points),
        "aeration_coefficient": round(zeta, 6),
        "allow_backwater_m": round(backwater, 6),
        "freeboard_m": round(freeboard, 6),
        "max_aerated_depth_m": round(max_aerated_depth, 6),
        "recommended_sidewall_height_m": round(max_sidewall_height, 6),
        "message": "已按掺气水深计算侧墙建议高度，侧墙高度包含掺气增量、允许壅水和安全超高。" if points else "水面线未完成，尚未形成可用的侧墙高度。",
    }


def _sidewall_increased_flow(data: Dict[str, Any], params: Dict[str, float], profile: Dict[str, Any], aeration: Dict[str, Any]) -> None:
    """按加大流量复核墙高，以两个工况的最大值给出统一侧墙高度。"""
    q_increased = _first_optional_float(data, ("Q_increased", "increase_flow"))
    aeration["control_flow_m3s"] = params["Q"]
    aeration["increased_flow_checked"] = False
    if q_increased is None or q_increased <= params["Q"]:
        return
    unavailable_reason = ""
    if not profile.get("available") or not profile.get("points"):
        unavailable_reason = "设计流量水面线未完成，侧墙高度尚未完成校核。"
    elif data.get("increased_flow_boundary_missing"):
        unavailable_reason = "上游子段的加大流量水面线未完成，当前子段不能重新假定临界控制；全链侧墙尚未完成校核。"
    elif (data.get("increased_flow_independent_control") and _has_value(data, "manual_start_depth")
          and not _has_value(data, "increased_flow_start_depth")):
        unavailable_reason = "已指定设计工况入口水深；请补充加大工况实际入口水深后再校核侧墙。"
    if unavailable_reason:
        aeration.update(enabled=False, recommended_sidewall_height_m=None, control_flow_m3s=None,
                        message=unavailable_reason)
        for point in profile.get("points", []):
            point.pop("sidewall_height_m", None)
            point.pop("sidewall_top_elevation_m", None)
        return
    increased_data = dict(data)
    # 复用完整内核且去掉再加大与多流量入口，避免递归重复计算。
    for key in ("Q_increased", "increase_flow", "flow_cases", "staged_flows", "multi_flows"):
        increased_data.pop(key, None)
    increased_data["Q"] = q_increased
    if data.get("increased_flow_independent_control"):
        # 表3连续变坡的加大工况独立传递水深，不能继承设计流量水深。
        for key in ("manual_start_depth", "actual_control_depth", "h_control", "start_depth", "h_start",
                    "inlet_control_depth", "gate_control_depth", "model_test_start_depth"):
            increased_data.pop(key, None)
        increased_data["start_bed_elevation"] = profile["points"][0]["bed_elevation_m"]
        inherited_depth = _first_optional_float(data, ("increased_flow_start_depth",))
        if inherited_depth is None:
            increased_data["control_depth_mode"] = "critical_depth"
        else:
            increased_data["control_depth_mode"] = "manual"
            increased_data["manual_start_depth"] = inherited_depth
    # 比较同一座建筑物，反算长度或全曲线模式先锁定主工况形成的实际长度。
    increased_data["profile_mode"] = ChuteProfileCalcMode.END_DEPTH_BY_LENGTH.value
    increased_data["L"] = profile.get("length_m", params["L"])
    increased = quick_calculate_spillway_steep_chute(increased_data)
    increased_aeration = increased.get("aeration_and_sidewall", {})
    if not increased.get("profile", {}).get("available") or not aeration.get("enabled"):
        aeration["enabled"] = False
        aeration["recommended_sidewall_height_m"] = None
        aeration["control_flow_m3s"] = None
        aeration["message"] = "设计或加大流量未形成可用水面线，侧墙高度尚未完成加大流量校核。"
        for point in profile.get("points", []):
            point.pop("sidewall_height_m", None)
            point.pop("sidewall_top_elevation_m", None)
        return
    aeration["increased_flow_checked"] = True
    aeration["increased_flow_m3s"] = q_increased
    aeration["increased_flow_profile_points"] = increased.get("profile_points", [])
    height = max(aeration["recommended_sidewall_height_m"], increased_aeration["recommended_sidewall_height_m"])
    if increased_aeration["recommended_sidewall_height_m"] > aeration["recommended_sidewall_height_m"]:
        aeration["control_flow_m3s"] = q_increased
    aeration["max_aerated_depth_m"] = max(aeration["max_aerated_depth_m"], increased_aeration["max_aerated_depth_m"])
    aeration["recommended_sidewall_height_m"] = height
    aeration["message"] = f"已比较设计和加大流量；按控制流量 {aeration['control_flow_m3s']:.3f} 立方米/秒的最大掺气水深、壅水及超高，统一采用侧墙高度 {height:.3f} 米。"
    for point in profile.get("points", []):
        point["sidewall_height_m"] = height
        point["sidewall_top_elevation_m"] = round(point["bed_elevation_m"] + height, 6)


def _centroid_to_water_surface(b: float, m: float, h: float) -> float:
    """计算梯形或矩形断面形心到水面的距离。"""
    if h <= 0:
        return 0.0
    if abs(m) < 1e-12:
        return h / 2.0
    top_width = b + 2.0 * m * h
    centroid_from_bottom = h * (2.0 * top_width + b) / (3.0 * (top_width + b))
    return max(0.0, h - centroid_from_bottom)


def _momentum_function(Q: float, b: float, m: float, h: float, beta: float = 1.0) -> float:
    """计算明渠水跃动量函数。"""
    area = calculate_area(b, h, m)
    if area <= 0:
        return 0.0
    return beta * Q * Q / (G * area) + area * _centroid_to_water_surface(b, m, h)


def _solve_conjugate_depth(Q: float, b: float, m: float, h1: float, critical_depth: float, froude: float) -> float:
    """计算跃后共轭水深；矩形断面用显式式，梯形断面用动量函数试算。"""
    if h1 <= 0:
        return 0.0
    if abs(m) < 1e-12:
        return 0.5 * h1 * (math.sqrt(1.0 + 8.0 * froude * froude) - 1.0)
    target = _momentum_function(Q, b, m, h1)
    # 本动量函数取动量修正系数1；其极小点不可借用含能量系数的临界深。
    momentum_critical_depth = _solve_critical_depth(Q, b, m, 1.0)
    low = max(h1, momentum_critical_depth, 1e-6)
    high = max(low * 2.0, low + 1.0)
    for _ in range(80):
        if _momentum_function(Q, b, m, high) >= target:
            break
        high *= 1.5
        if high > 1000:
            return high
    for _ in range(100):
        mid = (low + high) / 2.0
        if _momentum_function(Q, b, m, mid) < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _resolve_tailwater_depth(data: Dict[str, Any], params: Dict[str, float], hydraulic: Dict[str, Any]) -> float | None:
    """只使用实际下游边界；未填尾水与明确填写零水深不同。"""
    if _has_value(data, "downstream_water_level") and _has_value(data, "downstream_bed_elevation"):
        return _as_float(data, "downstream_water_level") - _as_float(data, "downstream_bed_elevation")
    return _first_optional_float(
        data,
        (
            "downstream_tailwater_depth",
            "tailwater_depth",
            "downstream_channel_depth",
            "downstream_channel_normal_depth",
            "downstream_depth",
            "hs",
        ),
    )


def _bool_value(value: Any) -> bool:
    """把常见中文或数字开关转成布尔值。"""
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "是", "有", "采用", "启用"}


def _outlet_rectification_result(data: Dict[str, Any], params: Dict[str, float], h2: float) -> Dict[str, Any]:
    """计算出口整流段建议长度和渐变控制值。"""
    pool_width = _first_float(data, ("stilling_pool_width", "pool_width", "outlet_pool_width"), params["b"])
    downstream_width = _first_float(data, ("downstream_channel_width", "outlet_channel_width", "tail_channel_width", "downstream_width"), params["b"])
    angle = abs(_first_float(data, ("outlet_transition_angle_deg", "transition_angle_deg", "outlet_rectification_angle_deg"), 12.0))
    safe_angle = min(max(angle, 1.0), 20.0)
    factor = _first_float(data, ("outlet_rectification_factor", "transition_length_factor", "rectification_length_factor"), 10.0)
    safe_factor = min(max(factor, 8.0), 15.0)
    auxiliary = _bool_value(data.get("auxiliary_energy_dissipator") or data.get("has_auxiliary_dissipator"))
    minimum_factor = 3.0 if auxiliary else 8.0
    width_diff = abs(pool_width - downstream_width)
    width_transition_length = 0.0
    if width_diff > 1e-9:
        width_transition_length = width_diff / (2.0 * math.tan(math.radians(safe_angle)))
    energy_length = safe_factor * h2
    minimum_length = minimum_factor * h2
    recommended = max(width_transition_length, energy_length, minimum_length)
    tailwater = _resolve_tailwater_depth(data, params, {})
    downstream_minimum = 3.0 * tailwater if tailwater is not None and math.isfinite(tailwater) and tailwater >= 0 else 0.0
    # 第12.2.7条对整流段自身还有大于3倍下游水深的独立要求。
    if downstream_minimum > 0:
        recommended = max(recommended, downstream_minimum + 0.001)
    protection = str(data.get("downstream_protection_condition") or "").strip()
    needs_rectification = width_diff > 1e-9 or protection in {"差", "薄弱", "不明", "需复核"}
    return {
        "needed": needs_rectification,
        "pool_width_m": round(pool_width, 6),
        "downstream_width_m": round(downstream_width, 6),
        "transition_angle_deg": round(safe_angle, 6),
        "length_factor": round(safe_factor, 6),
        "minimum_factor": round(minimum_factor, 6),
        "width_transition_length_m": round(width_transition_length, 6),
        "energy_length_m": round(energy_length, 6),
        "minimum_length_m": round(minimum_length, 6),
        "downstream_depth_minimum_m": round(downstream_minimum, 6),
        "recommended_length_m": round(recommended, 6),
        "message": "出口连接整流总长度按宽度渐变、跃后水深倍数及大于3倍实际下游水深取控制值；布置时整流段自身也应满足后者。",
    }


def _hydraulic_jump_result(data: Dict[str, Any], params: Dict[str, float], hydraulic: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """计算陡坡出口水跃和消力池初拟结果。"""
    points = profile.get("points") or []
    end_point = points[-1] if points else hydraulic.get("start", {})
    h1 = float(end_point.get("depth_m", hydraulic.get("critical_depth_m", 0.0)) or 0.0)
    metrics = _section_metrics(params["Q"], params["b"], h1, params["m"], params["n"])
    froude = metrics["froude"]
    tailwater = _resolve_tailwater_depth(data, params, hydraulic)
    pool_factor = _first_float(data, ("pool_depth_factor", "stilling_pool_factor"), 1.10)
    base_unavailable = {
        "applicable": False,
        "design_available": False,
        "design_method": "GB 50288-2018 N.2.5：单级等底宽陡坡、同宽矩形消力池初拟",
        "pre_jump_depth_m": round(h1, 6) if h1 > 0 else None,
        "pre_jump_velocity_ms": round(metrics["velocity_ms"], 6) if h1 > 0 else None,
        "pre_jump_froude": round(froude, 6) if h1 > 0 else None,
        "conjugate_depth_m": None,
        "tailwater_depth_m": round(tailwater, 6) if tailwater is not None else None,
        "outlet_critical_depth_m": None,
        "control_depth_m": None,
        "tailwater_judgement": "不适用",
        "recommended_pool_length_m": None,
        "recommended_pool_depth_m": None,
        "calculated_pool_depth_m": None,
        "tailwater_deficit_m": None,
        "control_depth_difference_m": None,
        "positive_control_deficit_m": None,
        "control_metric": None,
        "recommended_transition_length_m": None,
        "outlet_rectification_length_m": None,
        "outlet_rectification": {},
        "pool_depth_factor": round(pool_factor, 6),
    }
    if not profile.get("available") or not points:
        return {
            **base_unavailable,
            "status": "profile_unavailable",
            "message": "水面线未形成可用出口断面，暂不计算水跃和消力池尺寸。",
        }
    if froude <= 1.0:
        return {
            **base_unavailable,
            "status": "not_supercritical",
            "message": "出口断面未达到急流条件，水跃和消力池尺寸不适用。",
        }
    h2 = _solve_conjugate_depth(params["Q"], params["b"], params["m"], h1, hydraulic["critical_depth_m"], froude)
    jump_only = {
        **base_unavailable,
        "applicable": True,
        "conjugate_depth_m": round(h2, 6),
        "conjugate_depth_scope": "同一断面、水平底床上的自由水跃动量计算；变宽或变断面入池需另算",
    }
    if tailwater is None:
        return {
            **jump_only, "status": "missing_tailwater", "tailwater_judgement": "待补尾水",
            "message": "已计算同断面理论共轭水深。补充下游尾水深后可判断衔接；未用陡槽正常水深代替尾水，暂不输出消力池尺寸。",
        }
    if not math.isfinite(tailwater) or tailwater < 0:
        return {
            **jump_only, "status": "invalid_tailwater", "tailwater_judgement": "尾水输入无效",
            "message": "下游尾水深必须是有限非负值；干沟可明确填写 0。",
        }
    pool_width = _first_float(data, ("stilling_pool_width", "pool_width", "outlet_pool_width"), params["b"])
    if abs(params["m"]) > 1e-12 or not math.isclose(pool_width, params["b"], rel_tol=1e-6):
        return {
            **jump_only, "status": "unsupported_pool_geometry", "tailwater_judgement": "需另算入池衔接",
            "message": "已计算同断面理论共轭水深。现有池长、池深初拟式只用于同宽矩形陡槽接矩形池；梯形或变宽入池需另算，不套用矩形尺寸。",
        }
    if not 1.10 <= pool_factor <= 1.15:
        return {
            **jump_only, "status": "invalid_pool_factor", "tailwater_judgement": "池深系数需调整",
            "message": "GB 50288-2018 N.2.5 的池深系数范围为 1.10～1.15，请调整后重算。",
        }
    q_out = params["Q"] / params["b"] if params["b"] > 0 else 0.0
    alpha_j = _first_float(data, ("jump_alpha", "energy_dissipation_alpha", "alpha_j"), 1.05)
    h_out_critical = (alpha_j * q_out * q_out / G) ** (1.0 / 3.0) if q_out > 0 else 0.0
    # 规范 N.2.5 中 hs 是池后实际水深，不混入另一套自由跌落控制算法。
    control_depth = tailwater
    pool_length = 4.5 * h2
    calculated_pool_depth = max(0.0, pool_factor * h2 - control_depth)
    tailwater_deficit = max(0.0, h2 - tailwater)
    pool_depth = calculated_pool_depth
    control_depth_difference = h2 - control_depth
    outlet_rectification = _outlet_rectification_result(data, params, h2)
    tolerance = max(0.05, 0.05 * h2)
    if tailwater < h2 - tolerance:
        judgement = "尾水不足"
        message = "下游尾水不足，自由水跃可能被推向下游，应设置或复核消力池。"
    elif tailwater > h2 + tolerance:
        judgement = "尾水过高"
        message = "下游尾水偏高，可能形成淹没水跃，应复核池内流态和消能效率。"
    else:
        judgement = "尾水适宜"
        message = "下游尾水与跃后水深接近，可形成较合适水跃，仍需复核防冲。"
    return {
        "applicable": True,
        "design_available": True,
        "design_method": base_unavailable["design_method"],
        "status": "ok",
        "pre_jump_depth_m": round(h1, 6),
        "pre_jump_velocity_ms": round(metrics["velocity_ms"], 6),
        "pre_jump_froude": round(froude, 6),
        "conjugate_depth_m": round(h2, 6),
        "tailwater_depth_m": round(tailwater, 6),
        "outlet_critical_depth_m": round(h_out_critical, 6),
        "control_depth_m": round(control_depth, 6),
        "tailwater_judgement": judgement,
        "recommended_pool_length_m": round(pool_length, 6),
        "recommended_pool_depth_m": round(pool_depth, 6),
        "calculated_pool_depth_m": round(calculated_pool_depth, 6),
        "tailwater_deficit_m": round(tailwater_deficit, 6),
        "control_depth_difference_m": round(control_depth_difference, 6),
        "positive_control_deficit_m": round(max(0.0, control_depth_difference), 6),
        "control_metric": round(control_depth_difference, 6),
        "recommended_transition_length_m": outlet_rectification["recommended_length_m"],
        "outlet_rectification_length_m": outlet_rectification["recommended_length_m"],
        "outlet_rectification": outlet_rectification,
        "pool_depth_factor": round(pool_factor, 6),
        "message": f"水跃与消力池：{message} 尺寸按 GB 50288-2018 N.2.5 同宽矩形池初拟，池深采用实际池后水深；未进行挖深池后的入池水流迭代。",
    }


TAILWATER_KEYS = (
    "downstream_tailwater_depth", "tailwater_depth", "downstream_channel_depth",
    "downstream_channel_normal_depth", "downstream_depth", "hs",
    "downstream_water_level", "downstream_bed_elevation",
)


def _flow_case_candidates(raw_cases: Any) -> List[Dict[str, Any]]:
    """把用户或前端传入的多流量工况整理为去重候选。"""
    cases: List[Dict[str, Any]] = []
    seen: set[tuple] = set()
    for idx, item in enumerate(raw_cases or []):
        if isinstance(item, dict):
            q_value = _first_float(item, ("Q", "flow", "design_flow"), 0.0)
            name = str(item.get("name") or item.get("case") or f"流量{idx + 1}")
        else:
            q_value = float(item or 0.0)
            name = f"流量{idx + 1}"
        if q_value <= 0:
            continue
        rounded_q = round(q_value, 6)
        boundary = {key: item[key] for key in TAILWATER_KEYS if _has_value(item, key)} if isinstance(item, dict) else {}
        identity = (rounded_q, tuple(sorted((key, str(value)) for key, value in boundary.items())))
        if identity in seen:
            continue
        seen.add(identity)
        cases.append({"name": name, "Q": rounded_q, **boundary})
    return cases


def _evaluate_multi_flow_cases(data: Dict[str, Any], params: Dict[str, float], flow_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """逐个流量计算消力池控制指标。"""
    cases: List[Dict[str, Any]] = []
    alpha_profile = _profile_energy_alpha(data)
    per_case_tailwater = any(any(_has_value(item, key) for key in TAILWATER_KEYS) for item in flow_cases)
    for item in flow_cases:
        q_value = float(item["Q"])
        name = str(item["name"])
        local_params = dict(params)
        local_params["Q"] = q_value
        normal_depth = calculate_depth_for_flow(q_value, params["b"], params["i"], params["n"], params["m"])
        critical_depth = _solve_critical_depth(q_value, params["b"], params["m"], _profile_energy_alpha(data))
        critical_slope = _critical_slope(q_value, params["b"], params["m"], params["n"], critical_depth)
        start_control_data = dict(data)
        start_control_data.pop("flow_cases", None)
        boundary = {key: item[key] for key in TAILWATER_KEYS if _has_value(item, key)}
        if per_case_tailwater:
            # 逐工况边界优先，清除主工况其他别名，防止优先级覆盖新尾水。
            for key in TAILWATER_KEYS:
                start_control_data.pop(key, None)
            start_control_data.update(boundary)
        hydraulic = _build_hydraulic_summary(
            _normalize_section_type(data.get("section_type")),
            q_value,
            params["b"],
            params["m"],
            params["i"],
            params["n"],
            normal_depth,
            critical_depth,
            critical_slope,
            critical_depth,
            alpha_profile,
        )
        start_control = _resolve_start_control(start_control_data, hydraulic)
        profile = _profile_result(start_control_data, local_params, hydraulic, start_control)
        jump = _hydraulic_jump_result(start_control_data, local_params, hydraulic, profile)
        cases.append(
            {
                "name": name,
                "Q": round(q_value, 6),
                "status": jump.get("status", "ok"),
                "tailwater_depth_m": jump.get("tailwater_depth_m"),
                "message": jump.get("message", ""),
                "pre_jump_depth_m": jump["pre_jump_depth_m"],
                "conjugate_depth_m": jump["conjugate_depth_m"],
                "control_depth_m": jump["control_depth_m"],
                "control_depth_difference_m": jump["control_depth_difference_m"],
                "control_depth_deficit_m": jump["control_depth_difference_m"],
                "positive_control_deficit_m": jump["positive_control_deficit_m"],
                "tailwater_deficit_m": jump["tailwater_deficit_m"],
                "recommended_pool_length_m": jump["recommended_pool_length_m"],
                "recommended_pool_depth_m": jump["recommended_pool_depth_m"],
                "recommended_transition_length_m": jump["recommended_transition_length_m"],
            }
        )
    return cases


def _select_multi_flow_control_case(cases: List[Dict[str, Any]], metric: str) -> Dict[str, Any]:
    """按控制差值、池深、池长和流量选择控制工况。"""
    return max(
        cases,
        key=lambda row: (
            row.get(metric) if row.get(metric) is not None else -1.0e30,
            row.get("recommended_pool_depth_m") or 0.0,
            row.get("recommended_pool_length_m") or 0.0,
            row.get("Q", 0.0),
        ),
    )


def _refined_flow_candidates(flow_cases: List[Dict[str, Any]], control_case: Dict[str, Any], params: Dict[str, float], refinement: Dict[str, Any]) -> tuple[List[Dict[str, Any]], Dict[str, Any] | None]:
    """在初筛控制工况邻近区间按设计流量比例加密。"""
    if not refinement.get("enabled"):
        return flow_cases, None
    design_flow = float(params.get("Q") or 0.0)
    refine_ratio = float(refinement.get("refine_step_ratio") or 0.0)
    coarse_ratio = float(refinement.get("coarse_step_ratio") or 0.0)
    refine_step = round(design_flow * refine_ratio, 6)
    if design_flow <= 0 or refine_step <= 0:
        return flow_cases, None

    sorted_cases = sorted(flow_cases, key=lambda item: item["Q"])
    control_q = float(control_case.get("Q") or 0.0)
    control_idx = next((idx for idx, item in enumerate(sorted_cases) if abs(item["Q"] - control_q) <= 1.0e-6), -1)
    if control_idx < 0:
        return flow_cases, None

    if control_idx == len(sorted_cases) - 1 and control_q > design_flow:
        start_q = max(design_flow, sorted_cases[control_idx - 1]["Q"] if control_idx > 0 else design_flow)
        end_q = control_q
    else:
        start_q = sorted_cases[max(0, control_idx - 1)]["Q"]
        end_q = sorted_cases[min(len(sorted_cases) - 1, control_idx + 1)]["Q"]
    if end_q <= start_q:
        return flow_cases, None

    seen = {round(item["Q"], 6) for item in flow_cases}
    combined = list(flow_cases)
    added = 0
    step_count = int(round((end_q - start_q) / refine_step))
    for step in range(step_count + 1):
        q_value = round(start_q + step * refine_step, 6)
        if q_value < start_q - 1.0e-6 or q_value > end_q + 1.0e-6:
            continue
        if q_value in seen:
            continue
        seen.add(q_value)
        added += 1
        combined.append({"name": f"自动细化流量 {q_value:.3f}", "Q": q_value})
    rounded_end = round(end_q, 6)
    if rounded_end not in seen:
        combined.append({"name": f"自动细化流量 {rounded_end:.3f}", "Q": rounded_end})
        added += 1

    metadata = {
        "coarse_step_ratio": round(coarse_ratio, 6),
        "refine_step_ratio": round(refine_ratio, 6),
        "interval_start_flow_m3s": round(start_q, 6),
        "interval_end_flow_m3s": round(end_q, 6),
        "refine_step_flow_m3s": refine_step,
        "initial_control_flow_m3s": round(control_q, 6),
        "added_case_count": added,
        "candidate_case_count": len(combined),
    }
    return sorted(combined, key=lambda item: item["Q"]), metadata


def _multi_flow_control(data: Dict[str, Any], params: Dict[str, float]) -> Dict[str, Any]:
    """按多个流量计算消力池控制工况。"""
    raw_cases = data.get("flow_cases") or data.get("staged_flows") or data.get("multi_flows") or []
    flow_cases = _flow_case_candidates(raw_cases)
    cases = _evaluate_multi_flow_cases(data, params, flow_cases)
    if not cases:
        return {"cases": [], "control_case": None, "control_flow_m3s": None, "control_metric": "control_depth_difference_m", "message": "未提供分级流量，未形成多流量控制工况。"}
    metric = "control_depth_difference_m"
    valid_cases = [case for case in cases if case.get(metric) is not None]
    if not valid_cases:
        return {"cases": cases, "control_case": None, "control_flow_m3s": None,
                "control_metric": metric, "complete": False,
                "message": "分级流量已计算；缺少尾水或工况不满足同宽矩形池条件，尚不能确定消力池控制流量。"}
    control_case = _select_multi_flow_control_case(valid_cases, metric)
    refinement_config = data.get("flow_case_refinement") if isinstance(data.get("flow_case_refinement"), dict) else {}
    individual_tailwater = any(any(_has_value(item, key) for key in TAILWATER_KEYS) for item in flow_cases)
    if individual_tailwater:
        # 没有尾水流量关系时，不能为新加密流量虚构尾水边界。
        refinement_config = {}
    refined_cases, refinement_info = _refined_flow_candidates(flow_cases, control_case, params, refinement_config)
    if refinement_info:
        cases = _evaluate_multi_flow_cases(data, params, refined_cases)
        valid_cases = [case for case in cases if case.get(metric) is not None]
        control_case = _select_multi_flow_control_case(valid_cases, metric)
        refinement_info["candidate_case_count"] = len(cases)
    message = f"控制流量为 {control_case['Q']:.3f} 立方米/秒，按 GB 50288-2018 第12.3.5条比较跃后水深与实际池后水深差。"
    message += " 采用各工况给定尾水，未对缺少尾水的流量自动加密。" if individual_tailwater else " 各流量沿用同一尾水输入，结果为固定尾水情景比较。"
    if len(valid_cases) < len(cases):
        message += " 部分流量未形成有效结果，当前控制值仅覆盖已算工况。"
    if refinement_info and refinement_info.get("added_case_count", 0) > 0:
        message += (
            f" 已按 {refinement_info.get('coarse_step_ratio', 0.1) * 100:.0f}% 初筛，"
            f"并在 {refinement_info['interval_start_flow_m3s']:.3f}～{refinement_info['interval_end_flow_m3s']:.3f} 立方米/秒控制区间"
            f"按 {refinement_info.get('refine_step_ratio', 0.01) * 100:.0f}% 设计流量自动加密。"
        )
    return {
        "cases": cases,
        "control_case": control_case,
        "control_flow_m3s": control_case["Q"],
        "control_metric": metric,
        "complete": len(valid_cases) == len(cases),
        "tailwater_assumption": "per_case" if individual_tailwater else "constant",
        "pool_depth_control_case": _select_multi_flow_control_case(valid_cases, "recommended_pool_depth_m"),
        "pool_length_control_case": _select_multi_flow_control_case(valid_cases, "recommended_pool_length_m"),
        "max_pool_depth_m": max(case.get("recommended_pool_depth_m") or 0.0 for case in valid_cases),
        "max_pool_length_m": max(case.get("recommended_pool_length_m") or 0.0 for case in valid_cases),
        "refinement": refinement_info or {},
        "message": message,
    }


def _water_profile_export(data: Dict[str, Any], profile: Dict[str, Any], profile_points: List[Dict[str, Any]], risks: List[str]) -> Dict[str, Any]:
    """生成供推求水面线轻量接入的结构化结果。"""
    if not profile.get("available") or profile.get("status") != "ok" or len(profile_points) < 2:
        warnings = list(risks)
        if not any("水面线" in str(item) for item in warnings):
            warnings.append("未形成可用沿程水面线，表3轻量接口仅记录不可用状态。")
        return {
            "结构名称": data.get("structure_name") or data.get("project_name") or "泄水渠与陡坡",
            "available": False,
            "入口水位_m": None,
            "出口水位_m": None,
            "points": [],
            "warnings": warnings,
            "说明": "表3轻量接口未获得可用沿程水面线；当前仅标记入口、出口和采样点不可用，不把空结果伪装为 0 水位。",
        }
    inlet = profile_points[0]
    outlet = profile_points[-1]
    inlet_level = inlet.get("water_elevation_m") or inlet.get("water_elevation") or 0.0
    outlet_level = outlet.get("water_elevation_m") or outlet.get("water_elevation") or 0.0
    points = [
        {
            "桩号_m": point.get("station_m", point.get("distance_m", 0.0)),
            "渠底高程_m": point.get("bed_elevation_m", ""),
            "水深_m": point.get("depth_m", ""),
            "水位_m": point.get("water_elevation_m", ""),
            "流速_m_s": point.get("velocity_ms", ""),
            "弗劳德数": point.get("froude", ""),
        }
        for point in profile_points
    ]
    return {
        "结构名称": data.get("structure_name") or data.get("project_name") or "泄水渠与陡坡",
        "available": True,
        "入口水位_m": round(float(inlet_level or 0.0), 6),
        "出口水位_m": round(float(outlet_level or 0.0), 6),
        "points": points,
        "warnings": list(risks),
        "说明": "表3轻量接口仅提供入口、出口和沿程采样点，不把每个沿程点拆成正式表3节点。",
    }


def quick_calculate_spillway_steep_chute(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """前端快速调用入口，输入 dict 并返回完整计算结果 dict。"""
    data = dict(input_data or {})
    params, errors = _validate_input(data)
    if errors:
        return _build_error_result(errors)

    section_type = _normalize_section_type(data.get("section_type"))
    Q, b, m, i, n = params["Q"], params["b"], params["m"], params["i"], params["n"]
    alpha_profile = _profile_energy_alpha(data)
    params["alpha_profile"] = alpha_profile
    params["critical_alpha"] = alpha_profile
    data["alpha_profile"] = alpha_profile
    normal_depth = _solve_profile_normal_depth(Q, b, m, n, i)
    critical_depth = _solve_critical_depth(Q, b, m, alpha_profile)
    if normal_depth <= 0 or critical_depth <= 0:
        return _build_error_result(["正常水深或临界水深求解失败。"])

    critical_slope = _critical_slope(Q, b, m, n, critical_depth)
    provisional_hydraulic = _build_hydraulic_summary(section_type, Q, b, m, i, n, normal_depth, critical_depth, critical_slope, critical_depth, alpha_profile)
    provisional_hydraulic["critical_depth_m"] = critical_depth
    start_control = _resolve_start_control(data, provisional_hydraulic)
    start_depth = float(start_control.get("depth_m", critical_depth))
    explicit_bed_elevation = any(
        _has_value(data, key)
        for key in ("start_bed_elevation", "start_z", "bed_elevation_start")
    )
    start_water_level = _first_optional_float(data, ("start_water_level", "inlet_water_level", "入口水位"))
    if start_water_level is not None and not explicit_bed_elevation:
        # 表3联算只知道入口水位，需要用起点控制水深反推起点渠底高程。
        data["start_bed_elevation"] = start_water_level - start_depth
        data["bed_elevation_start"] = data["start_bed_elevation"]
    hydraulic = _build_hydraulic_summary(section_type, Q, b, m, i, n, normal_depth, critical_depth, critical_slope, start_depth, alpha_profile)
    profile_type_info = _water_profile_type(hydraulic["slope_type"], start_depth, normal_depth, critical_depth, data)
    hydraulic["water_profile_type"] = profile_type_info["type"]
    hydraulic["water_profile_name"] = profile_type_info["name"]
    hydraulic["water_profile_message"] = profile_type_info["message"]
    warnings: List[str] = []
    if _has_value(data, "critical_alpha") and not math.isclose(
        _as_float(data, "critical_alpha", alpha_profile), alpha_profile, rel_tol=1e-12, abs_tol=1e-12
    ):
        warnings.append("旧输入中的临界水深系数与水面线动能修正系数不同，已统一采用水面线动能修正系数计算临界水深和流态边界。")
    if hydraulic["slope_type"] != "steep":
        warnings.append("当前工况为非陡坡，不按陡槽 b2 型水面线静默计算。")
    if hydraulic["start"]["velocity_ms"] > 10.0:
        warnings.append("起点流速较高，应关注掺气、抗冲和消能措施。")

    upstream_connection = _upstream_connection_result(data, hydraulic, start_control)
    profile = _profile_result(data, params, hydraulic, start_control)
    profile["upstream_connection"] = upstream_connection
    inlet = _inlet_weir(data, Q, b)
    code_checks = _code_checks(data, params, hydraulic, profile)
    formula_cards = _formula_cards()
    aeration_and_sidewall = _add_aeration_and_sidewall(data, profile)
    _sidewall_increased_flow(data, params, profile, aeration_and_sidewall)
    hydraulic_jump = _hydraulic_jump_result(data, params, hydraulic, profile)
    multi_data = dict(data)
    multi_params = dict(params)
    if profile.get("available") and profile.get("length_m") is not None:
        multi_data["profile_mode"] = ChuteProfileCalcMode.END_DEPTH_BY_LENGTH.value
        multi_data["L"] = profile["length_m"]
        multi_params["L"] = profile["length_m"]
    multi_flow_control = _multi_flow_control(multi_data, multi_params)
    summary = _build_summary(data, params, hydraulic, profile, inlet)
    profile_points = _profile_points_for_view(profile)
    summary["掺气系数"] = f"{aeration_and_sidewall.get('aeration_coefficient', 1.2):.3f}"
    summary["侧墙安全超高"] = f"{aeration_and_sidewall.get('freeboard_m', 0.4):.3f} 米"
    summary["池深系数"] = f"{hydraulic_jump.get('pool_depth_factor', _first_float(data, ('pool_depth_factor', 'stilling_pool_factor'), 1.10)):.3f}"
    summary["出口整流长度系数"] = f"{_first_float(data, ('outlet_rectification_factor', 'transition_length_factor', 'rectification_length_factor'), 10.0):.3f}"
    if aeration_and_sidewall.get("enabled") and aeration_and_sidewall.get("max_aerated_depth_m", 0.0) > 0:
        summary["最大掺气水深"] = f"{aeration_and_sidewall['max_aerated_depth_m']:.3f} 米"
        summary["建议侧墙高度"] = f"{aeration_and_sidewall['recommended_sidewall_height_m']:.3f} 米"
    if hydraulic_jump.get("applicable"):
        summary["跃后共轭水深"] = f"{hydraulic_jump['conjugate_depth_m']:.3f} 米"
    if hydraulic_jump.get("design_available"):
        summary["建议消力池长度"] = f"{hydraulic_jump['recommended_pool_length_m']:.3f} 米"
        summary["建议消力池深度"] = f"{hydraulic_jump['recommended_pool_depth_m']:.3f} 米"
        summary["建议出口整流段"] = f"{hydraulic_jump['recommended_transition_length_m']:.3f} 米"
    else:
        summary["消力池计算状态"] = hydraulic_jump.get("message", "未计算")
    summary["水面线计算状态"] = "已完成" if profile.get("available") else profile.get("message", "未形成可用水面线")
    pending_checks = [item["message"] for item in code_checks if item.get("passed") is None]
    summary["布置校核状态"] = "存在待核条件" if pending_checks else "已完成已输入项目的检查"
    risks = list(warnings)
    if not profile.get("available"):
        risks.append(profile.get("message") or "水面线未完成，不输出出口设计成果。")
    if not hydraulic_jump.get("design_available"):
        risks.append(hydraulic_jump.get("message") or "消力池尚未完成初拟。")
    if not aeration_and_sidewall.get("enabled"):
        risks.append(aeration_and_sidewall.get("message") or "侧墙高度尚未完成计算。")
    if inlet.get("passed") is False:
        risks.append(inlet.get("message") or "入口过流能力不足。")
    if data.get("legacy_inlet_coefficient_migrated"):
        risks.append("本版本已按 GB 50288-2018 附录 N 自动计算入口流量系数，旧版隐藏默认 0.42 不再使用。")
    if data.get("legacy_alpha_profile_migrated"):
        risks.append("本版本已按计算原理启用水面线动能修正系数 alpha_e=1.1，旧版实际未使用该系数，重算结果可能与旧版略有差异。")
    risks.extend(item["message"] for item in code_checks if item.get("passed") is False)
    if hydraulic_jump.get("applicable") and hydraulic_jump.get("tailwater_judgement") == "尾水不足":
        risks.append("下游尾水不足，应复核水跃位置、消力池和出口防冲。")
    water_profile_export = _water_profile_export(data, profile, profile_points, risks)
    case_result = ChuteCaseResult(
        h0_m=hydraulic["normal_depth_m"],
        hk_m=hydraulic["critical_depth_m"],
        ik=hydraulic["critical_slope"],
        slope_class=hydraulic["slope_type"],
        start_depth_m=hydraulic["start"]["depth_m"],
        end_depth_m=profile.get("end_depth_m") if profile.get("available") else None,
        max_velocity_ms=max((point.get("velocity_ms", 0.0) for point in profile.get("points", [])), default=hydraulic["start"]["velocity_ms"]),
        max_froude=max((point.get("froude", 0.0) for point in profile.get("points", [])), default=hydraulic["start"]["froude"]),
        inlet_capacity_ratio=inlet.get("capacity_ratio"),
        profile_points=profile_points,
        code_checks=code_checks,
        formula_cards=formula_cards,
        risk_tips=risks,
    )

    return {
        "success": True,
        "errors": [],
        "warnings": warnings,
        "input_params": dict(params),
        "summary": summary,
        "hydraulic": hydraulic,
        "profile": profile,
        "profile_points": profile_points,
        "start_control": start_control,
        "upstream_connection": upstream_connection,
        "hydraulic_jump": hydraulic_jump,
        "downstream_energy_dissipation": hydraulic_jump,
        "aeration_and_sidewall": aeration_and_sidewall,
        "multi_flow_control": multi_flow_control,
        "water_profile_export": water_profile_export,
        "water_profile_type": profile_type_info["type"],
        "inlet_weir": inlet,
        "discharge_hint": _discharge_hint(Q),
        "code_checks": code_checks,
        "checks": code_checks,
        "formula_cards": formula_cards,
        "formulas": formula_cards,
        "risks": risks,
        "case_results": [asdict(case_result)],
        "case_result": asdict(case_result),
        "comparison": [
            {
                "case": summary["工程名称"],
                "Q": params["Q"],
                "max_v": case_result.max_velocity_ms,
                "status": "需复核" if risks else "计算完成，存在待核条件" if pending_checks else "计算完成",
            }
        ],
        "example": _example_info(params),
    }
