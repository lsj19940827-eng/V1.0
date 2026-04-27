# -*- coding: utf-8 -*-
"""
有压管道水力计算核心

提供有压管道参与批量计算和水面线推求所需的水头损失计算功能。
包括：沿程损失（GB 50288）、弯头局部损失（表L.1.4-3/L.1.4-4）、渐变段损失（表L.1.2）。

所有函数均为纯函数，无全局副作用。
"""

import math
import sys
import os
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field

# 添加倒虹吸系统路径以复用系数服务
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '倒虹吸水力计算系统'))
try:
    from siphon_coefficients import CoefficientService
except ImportError:
    CoefficientService = None

# ============================================================
# 1. 管材参数（复制自有压管道设计.py，避免循环依赖）
# ============================================================

PIPE_MATERIALS = {
    "HDPE管":           {"f": 0.948e5, "m": 1.77, "b": 4.77, "name": "HDPE管 (f=94800, m=1.77, b=4.77)"},
    "玻璃钢夹砂管":     {"f": 0.948e5, "m": 1.77, "b": 4.77, "name": "玻璃钢夹砂管 (f=94800, m=1.77, b=4.77)"},
    "球墨铸铁管":       {"f": 2.232e5, "m": 1.852, "b": 4.87, "name": "球墨铸铁管 (f=223200, m=1.852, b=4.87)"},
    "预应力钢筒混凝土管": {"f": 1.312e6, "m": 2.0,  "b": 5.33, "name": "预应力钢筒混凝土管 (n=0.013, f=1312000, m=2.0, b=5.33)"},
    "预应力钢筒混凝土管_n014": {"f": 1.516e6, "m": 2.0, "b": 5.33, "name": "预应力钢筒混凝土管 (n=0.014, f=1516000, m=2.0, b=5.33)"},
    "预应力钢筒混凝土管_n015": {"f": 1.749e6, "m": 2.0, "b": 5.33, "name": "预应力钢筒混凝土管 (n=0.015, f=1749000, m=2.0, b=5.33)"},
    "钢管":             {"f": 6.25e5,  "m": 1.9,  "b": 5.1,  "name": "钢管 (f=625000, m=1.9, b=5.1)"},
}

# ============================================================
# 2. 渐变段型式与ζ值（表L.1.2）
# ============================================================

TRANSITION_FORMS = {
    "反弯扭曲面":   {"inlet_zeta": 0.10, "outlet_zeta": 0.20},
    "直线扭曲面":   {"inlet_zeta": 0.20, "outlet_zeta": 0.40},
    "1/4圆弧":      {"inlet_zeta": 0.15, "outlet_zeta": 0.25},
    "方头型":       {"inlet_zeta": 0.30, "outlet_zeta": 0.75},
}

# 重力加速度
GRAVITY = 9.81
WATER_HAMMER_WATER_DENSITY = 1000.0
WATER_HAMMER_DEFAULT_ALLOWABLE_PRESSURE_MPA = 1.0
WATER_HAMMER_PRESSURE_CHECK_BASIS_PIPE_BOTTOM = "pipe_bottom"
WATER_HAMMER_PRESSURE_CHECK_BASIS_LABELS = {
    WATER_HAMMER_PRESSURE_CHECK_BASIS_PIPE_BOTTOM: "管底",
}

# 水的体积弹性模量与声速（按 GB/T 20203-2017 水击波速公式取值）
WATER_BULK_MODULUS = 2.06e9
WATER_HAMMER_SOUND_SPEED = 1425.0
WATER_HAMMER_STATION_TOLERANCE_M = 1e-3
WATER_HAMMER_DISTRIBUTION_SAMPLE_INTERVAL_M = 5.0
WATER_HAMMER_EXEMPTION_REASON = (
    "启闭时间 Ts 满足 GB/T 20203-2017 5.1.7.4：Ts >= 40L/a，可不验算关阀水击压力"
)
WATER_HAMMER_EXEMPTION_TOLERANCE_S = 1e-12
WATER_HAMMER_WAVE_SPEED_FORMULA_SOURCE = "GB/T 20203-2017 5.1.7.4"
WATER_HAMMER_GBT_DIRECT_METHOD = "GB/T 20203-2017 式(19)"
WATER_HAMMER_GBT_INDIRECT_METHOD = "GB/T 20203-2017 式(21)"
WATER_HAMMER_LINEAR_METHOD = "线性启闭理论"
WATER_HAMMER_GOVERNING_EQUAL_METHOD = "双重验算一致"
WATER_HAMMER_DEFAULT_CP_NOTE = "未填写 a0，已按 cp=1 简化计算。"

# 水击验算默认弹性模量（按 GB/T 20203-2017 表6取值，硬聚氯乙烯按下限）
WATER_HAMMER_ELASTIC_MODULUS = {
    "钢管": 206.0e9,
    "钢": 206.0e9,
    "球墨铸铁管": 160.0e9,
    "球墨铸铁": 160.0e9,
    "铸铁管": 108.0e9,
    "铸铁": 108.0e9,
    "预应力钢筒混凝土管": 20.6e9,
    "预应力钢筒混凝土管_n014": 20.6e9,
    "预应力钢筒混凝土管_n015": 20.6e9,
    "钢筋混凝土管": 20.6e9,
    "钢筋混凝土": 20.6e9,
    "玻璃钢夹砂管": 14.7e9,
    "HDPE管": 1.4e9,
    "PE": 1.4e9,
    "PE管": 1.4e9,
    "聚乙烯": 1.4e9,
    "硬聚氯乙烯管": 2.8e9,
    "硬聚氯乙烯塑料管": 2.8e9,
    "PVC": 2.8e9,
    "PVC管": 2.8e9,
    "PVC-U": 2.8e9,
    "PVC-U管": 2.8e9,
    "聚氯乙烯": 2.8e9,
}

WATER_HAMMER_REINFORCED_CP_MATERIAL_KEYS = {
    "预应力钢筒混凝土管",
    "预应力钢筒混凝土管_n014",
    "预应力钢筒混凝土管_n015",
    "钢筋混凝土管",
    "钢筋混凝土",
}


# ============================================================
# 3. 计算函数
# ============================================================

def calc_pipe_velocity(Q_m3s: float, D_m: float) -> float:
    """
    计算管内流速
    
    Args:
        Q_m3s: 设计流量 (m³/s)
        D_m: 管径 (m)
    
    Returns:
        管内流速 V (m/s)
    """
    if D_m <= 0:
        return 0.0
    A = math.pi * D_m ** 2 / 4  # 断面积
    return Q_m3s / A


def resolve_water_hammer_material_key(material_key: str) -> str:
    """返回水击验算用的标准管材 key，未知管材保留原值。"""
    key = str(material_key or "").strip()
    if not key:
        return ""
    try:
        from utils.pressure_pipe_common import resolve_pressure_pipe_material
    except Exception:
        try:
            from 推求水面线.utils.pressure_pipe_common import resolve_pressure_pipe_material
        except Exception:
            return key
    material_info = resolve_pressure_pipe_material(key, PIPE_MATERIALS, default_material="")
    if bool(material_info.get("recognized")) and not bool(material_info.get("used_default")):
        canonical_key = str(material_info.get("canonical_key", "") or "").strip()
        if canonical_key:
            return canonical_key
    return key


def get_water_hammer_elastic_modulus(material_key: str) -> Optional[float]:
    """返回水击验算的默认管材弹性模量。"""
    key = resolve_water_hammer_material_key(material_key)
    if not key:
        return None
    return WATER_HAMMER_ELASTIC_MODULUS.get(key)


def water_hammer_material_requires_reinforcement_ratio(material_key: str) -> bool:
    """判断管材是否需要输入 a0 来计算管材系数 cp。"""
    key = resolve_water_hammer_material_key(material_key)
    raw_key = str(material_key or "").strip()
    return key in WATER_HAMMER_REINFORCED_CP_MATERIAL_KEYS or raw_key in WATER_HAMMER_REINFORCED_CP_MATERIAL_KEYS


def _resolve_water_hammer_pipe_coefficient(
    *,
    material_key: str = "",
    reinforcement_ratio_a0: Optional[float] = None,
) -> Tuple[Optional[float], Optional[float], bool, str, str, str]:
    """解析管材系数 cp，并返回必要的简化计算提示。"""
    resolved_material = resolve_water_hammer_material_key(material_key)
    requires_a0 = water_hammer_material_requires_reinforcement_ratio(material_key)
    a0 = _water_hammer_number(reinforcement_ratio_a0, None)
    if requires_a0:
        if a0 is None:
            return 1.0, None, True, resolved_material, WATER_HAMMER_DEFAULT_CP_NOTE, ""
        if a0 < 0:
            return None, None, True, resolved_material, "", "a0 不能为负值"
        return 1.0 / (1.0 + 0.95 * a0), a0, True, resolved_material, "", ""
    return 1.0, a0 if a0 is not None else None, False, resolved_material, "", ""


def _calc_water_hammer_wave_speed(
    *,
    diameter_m: float,
    wall_thickness_m: float,
    elastic_modulus_pa: float,
    water_bulk_modulus_pa: float,
    pipe_coefficient_cp: float = 1.0,
) -> Optional[float]:
    """按 GB/T 20203-2017 公式计算水击波速。"""
    if (
        diameter_m <= 0
        or wall_thickness_m <= 0
        or elastic_modulus_pa <= 0
        or water_bulk_modulus_pa <= 0
        or pipe_coefficient_cp <= 0
    ):
        return None
    denominator = (
        1.0
        + (water_bulk_modulus_pa / elastic_modulus_pa)
        * (diameter_m / wall_thickness_m)
        * pipe_coefficient_cp
    )
    if denominator <= 0:
        return None
    return WATER_HAMMER_SOUND_SPEED / math.sqrt(denominator)


def _join_water_hammer_notes(*notes: object) -> str:
    """合并水击验算提示，避免重复显示同一条说明。"""
    items: List[str] = []
    for note in notes:
        text = str(note or "").strip()
        if text and text not in items:
            items.append(text)
    return "；".join(items)


def convert_pressure_mpa_to_head_m(pressure_mpa: float) -> Optional[float]:
    """把允许压力 MPa 换算为工程水头 m。"""
    pressure = _water_hammer_number(pressure_mpa, None)
    if pressure is None or pressure <= 0:
        return None
    return pressure * 1_000_000.0 / (WATER_HAMMER_WATER_DENSITY * GRAVITY)


def _solve_water_hammer_root(func, low: float, high: float) -> Optional[float]:
    """用二分法求水击无量纲方程根。"""
    f_low = func(low)
    f_high = func(high)
    if not (math.isfinite(f_low) and math.isfinite(f_high)):
        return None
    if abs(f_low) <= 1e-12:
        return low
    if abs(f_high) <= 1e-12:
        return high
    if f_low * f_high > 0:
        return None
    left = low
    right = high
    for _ in range(80):
        mid = (left + right) / 2.0
        f_mid = func(mid)
        if not math.isfinite(f_mid):
            return None
        if abs(f_mid) <= 1e-12:
            return mid
        if f_low * f_mid <= 0:
            right = mid
            f_high = f_mid
        else:
            left = mid
            f_low = f_mid
    return (left + right) / 2.0


def _calc_positive_first_phase_zeta(section_mu: float, opening_ratio: float) -> Optional[float]:
    """计算线性关阀第一相正水击无量纲压强。"""
    if section_mu <= 0:
        return None
    tau = max(0.0, min(1.0, float(opening_ratio)))
    if tau <= 1e-12:
        return 2.0 * section_mu

    high = max(2.0 * section_mu, 1e-9)

    def equation(zeta: float) -> float:
        return tau * math.sqrt(max(0.0, 1.0 + zeta)) - (1.0 - zeta / (2.0 * section_mu))

    return _solve_water_hammer_root(equation, 0.0, high)


def _calc_negative_first_phase_zeta(section_mu: float, opening_ratio: float) -> Optional[float]:
    """计算线性开阀第一相负水击无量纲压降。"""
    if section_mu <= 0:
        return None
    tau = max(0.0, min(1.0, float(opening_ratio)))
    if tau <= 1e-12:
        return 0.0

    high = 1.0 - 1e-12

    def equation(zeta: float) -> float:
        return tau * math.sqrt(max(0.0, 1.0 - zeta)) - zeta / (2.0 * section_mu)

    return _solve_water_hammer_root(equation, 0.0, high)


def _water_hammer_candidate_zeta(candidates: List[Dict[str, float | str]], type_name: str) -> Optional[float]:
    """按候选名称取无量纲水击压强。"""
    for item in candidates:
        if str(item.get("type", "") or "") == type_name:
            try:
                return float(item.get("zeta", 0.0) or 0.0)
            except (TypeError, ValueError):
                return None
    return None


def _classify_water_hammer_type_by_diagram(
    *,
    section_mu: float,
    sigma: float,
    phase_time_s: float,
    closing_time_s: float,
    positive_control_type: str,
    negative_control_type: str,
    positive_candidates: List[Dict[str, float | str]],
    negative_candidates: List[Dict[str, float | str]],
    tau0: float = 1.0,
) -> Dict[str, object]:
    """生成图1-3-3水击类型判断对照，不参与控制值计算。"""
    mu_tau0 = section_mu * tau0
    line_sigma = mu_tau0
    denominator = 1.0 - 2.0 * mu_tau0
    curve_sigma = None
    if abs(denominator) > 1e-12:
        curve_sigma = 4.0 * mu_tau0 * (1.0 - mu_tau0) / denominator

    positive_type = str(positive_control_type or "")
    negative_type = str(negative_control_type or "")
    if closing_time_s <= phase_time_s + 1e-12 or positive_type == "直接正水击":
        positive_region = "V区：直接正水击"
    elif phase_time_s > 0 and abs(sigma - line_sigma) <= max(1e-9, abs(line_sigma) * 1e-8):
        positive_region = "直线：直接水击边界"
    else:
        first_zeta = _water_hammer_candidate_zeta(positive_candidates, "第一相正水击")
        terminal_zeta = _water_hammer_candidate_zeta(positive_candidates, "末相正水击")
        if (
            first_zeta is not None
            and terminal_zeta is not None
            and abs(first_zeta - terminal_zeta) <= max(1e-9, max(abs(first_zeta), abs(terminal_zeta)) * 1e-8)
        ):
            positive_region = "曲线：第一相=末相"
        elif positive_type == "末相正水击":
            positive_region = "I区：末相正水击"
        elif positive_type == "第一相正水击":
            positive_region = "II区：第一相正水击"
        elif curve_sigma is not None and curve_sigma > 0 and sigma < curve_sigma:
            positive_region = "I区：末相正水击"
        else:
            positive_region = "II区：第一相正水击"

    if closing_time_s <= phase_time_s + 1e-12 or negative_type == "直接负水击":
        negative_region = "直接负水击"
    elif negative_type == "负末相水击":
        negative_region = "III区：负末相水击"
    else:
        negative_region = "IV区：第一相负水击"

    return {
        "source": "图1-3-3",
        "tau0": tau0,
        "mu_tau0": mu_tau0,
        "sigma": sigma,
        "line_sigma": line_sigma,
        "curve_sigma": curve_sigma,
        "positive_region": positive_region,
        "negative_region": negative_region,
        "note": "仅作图1-3-3对照，不参与控制值计算",
    }


def _calc_linear_water_hammer_values(
    *,
    length_m: float,
    wave_speed_mps: float,
    velocity_mps: float,
    initial_head_m: float,
    closing_time_s: float,
) -> Dict[str, object]:
    """按手册线性启闭理论计算正水击和负水击控制值。"""
    phase_time = 2.0 * length_m / wave_speed_mps if wave_speed_mps > 0 else 0.0
    ts_ratio = closing_time_s / phase_time if phase_time > 0 else None
    section_mu = wave_speed_mps * velocity_mps / (2.0 * GRAVITY * initial_head_m)
    sigma = length_m * velocity_mps / (GRAVITY * initial_head_m * closing_time_s)
    direct_zeta = wave_speed_mps * velocity_mps / (GRAVITY * initial_head_m)

    positive_candidates: List[Dict[str, float | str]] = []
    if closing_time_s <= phase_time + 1e-12:
        positive_candidates.append({"type": "直接正水击", "zeta": direct_zeta})
    else:
        tau_first = max(0.0, 1.0 - phase_time / closing_time_s)
        first_zeta = _calc_positive_first_phase_zeta(section_mu, tau_first)
        if first_zeta is not None:
            positive_candidates.append({"type": "第一相正水击", "zeta": first_zeta})
        terminal_zeta = sigma / 2.0 * (sigma + math.sqrt(4.0 + sigma ** 2))
        positive_candidates.append({"type": "末相正水击", "zeta": terminal_zeta})
    positive_control = max(positive_candidates, key=lambda item: float(item["zeta"])) if positive_candidates else {}
    positive_zeta = float(positive_control.get("zeta", 0.0) or 0.0)
    positive_delta_h = positive_zeta * initial_head_m

    negative_candidates: List[Dict[str, float | str]] = []
    if closing_time_s <= phase_time + 1e-12:
        negative_candidates.append({"type": "直接负水击", "zeta": direct_zeta})
    else:
        tau_first = min(1.0, phase_time / closing_time_s)
        first_negative_zeta = _calc_negative_first_phase_zeta(section_mu, tau_first)
        if first_negative_zeta is not None:
            negative_candidates.append({"type": "第一相负水击", "zeta": first_negative_zeta})
        terminal_negative_zeta = sigma / 2.0 * (math.sqrt(4.0 + sigma ** 2) - sigma)
        negative_candidates.append({"type": "负末相水击", "zeta": terminal_negative_zeta})
    negative_control = max(negative_candidates, key=lambda item: float(item["zeta"])) if negative_candidates else {}
    negative_zeta = float(negative_control.get("zeta", 0.0) or 0.0)
    negative_delta_h = negative_zeta * initial_head_m
    positive_control_type = str(positive_control.get("type", "") or "")
    negative_control_type = str(negative_control.get("type", "") or "")
    diagram_type_check = _classify_water_hammer_type_by_diagram(
        section_mu=section_mu,
        sigma=sigma,
        phase_time_s=phase_time,
        closing_time_s=closing_time_s,
        positive_control_type=positive_control_type,
        negative_control_type=negative_control_type,
        positive_candidates=positive_candidates,
        negative_candidates=negative_candidates,
    )

    return {
        "phase_time_s": phase_time,
        "ts_to_mu_ratio": ts_ratio,
        "section_mu": section_mu,
        "sigma": sigma,
        "positive_zeta": positive_zeta,
        "positive_delta_h": positive_delta_h,
        "positive_control_type": positive_control_type,
        "positive_candidates": positive_candidates,
        "negative_zeta": negative_zeta,
        "negative_delta_h": negative_delta_h,
        "negative_control_type": negative_control_type,
        "negative_candidates": negative_candidates,
        "diagram_type_check": diagram_type_check,
        "hmax": initial_head_m + positive_delta_h,
        "hmin": initial_head_m - negative_delta_h,
        "negative_margin_m": initial_head_m - negative_delta_h,
        "negative_pressure_status": "有负压风险" if initial_head_m - negative_delta_h < -1e-9 else "无负压风险",
    }


def _calc_gbt_positive_water_hammer(
    *,
    length_m: float,
    wave_speed_mps: float,
    velocity_mps: float,
    closing_time_s: float,
) -> Tuple[float, str]:
    """按 GB/T 20203-2017 直接/间接水击公式计算正水击。"""
    phase_time = 2.0 * length_m / wave_speed_mps if wave_speed_mps > 0 else 0.0
    if closing_time_s <= phase_time + 1e-12:
        return wave_speed_mps * velocity_mps / GRAVITY, WATER_HAMMER_GBT_DIRECT_METHOD
    return (
        2.0 * length_m * velocity_mps / (GRAVITY * (phase_time + closing_time_s)),
        WATER_HAMMER_GBT_INDIRECT_METHOD,
    )


def _merge_positive_water_hammer_governing(
    values: Dict[str, object],
    *,
    length_m: float,
    wave_speed_mps: float,
    velocity_mps: float,
    initial_head_m: float,
    closing_time_s: float,
) -> Dict[str, object]:
    """合并GB/T正水击和线性启闭正水击，取较大者作为控制值。"""
    merged = dict(values)
    gbt_delta_h, gbt_method = _calc_gbt_positive_water_hammer(
        length_m=length_m,
        wave_speed_mps=wave_speed_mps,
        velocity_mps=velocity_mps,
        closing_time_s=closing_time_s,
    )
    linear_delta_h = float(values.get("positive_delta_h", 0.0) or 0.0)
    tolerance = max(1e-9, max(abs(gbt_delta_h), abs(linear_delta_h)) * 1e-9)
    if abs(gbt_delta_h - linear_delta_h) <= tolerance:
        governing_delta_h = max(gbt_delta_h, linear_delta_h)
        governing_method = WATER_HAMMER_GOVERNING_EQUAL_METHOD
    elif gbt_delta_h > linear_delta_h:
        governing_delta_h = gbt_delta_h
        governing_method = gbt_method
    else:
        governing_delta_h = linear_delta_h
        governing_method = WATER_HAMMER_LINEAR_METHOD

    merged.update(
        {
            "gbt_positive_delta_h": gbt_delta_h,
            "gbt_positive_method": gbt_method,
            "linear_positive_delta_h": linear_delta_h,
            "linear_positive_control_type": values.get("positive_control_type", ""),
            "positive_governing_method": governing_method,
            "positive_delta_h": governing_delta_h,
            "hmax": initial_head_m + governing_delta_h,
        }
    )
    return merged


def _water_hammer_diagram_curve_sigma(rho_tau0: float) -> Optional[float]:
    """计算图1-3-3分区曲线的σ值。"""
    denominator = 1.0 - 2.0 * rho_tau0
    if abs(denominator) <= 1e-12:
        return None
    curve = 4.0 * rho_tau0 * (1.0 - rho_tau0) / denominator
    return curve if math.isfinite(curve) and curve > 0 else None


def _classify_equivalent_water_hammer_region(
    *,
    rho: float,
    sigma: float,
    phase_time_s: float,
    closing_time_s: float,
    tau0: float = 1.0,
) -> Dict[str, object]:
    """按图1-3-3用ρτ0和σ判别阀端水击类型。"""
    rho_tau0 = rho * tau0
    curve_sigma = _water_hammer_diagram_curve_sigma(rho_tau0)
    direct = closing_time_s <= phase_time_s + 1e-12 or sigma >= rho_tau0 - 1e-12
    if direct:
        positive_type = "直接正水击"
        negative_type = "直接负水击"
        positive_region = "V区：直接正水击"
        negative_region = "V区：直接负水击"
    else:
        terminal_region = curve_sigma is not None and sigma <= curve_sigma + max(1e-12, curve_sigma * 1e-9)
        if terminal_region:
            positive_type = "末相正水击"
            negative_type = "负末相水击"
            positive_region = "I区：末相正水击"
            negative_region = "III区：负末相水击"
        else:
            positive_type = "第一相正水击"
            negative_type = "第一相负水击"
            positive_region = "II区：第一相正水击"
            negative_region = "IV区：第一相负水击"
    return {
        "source": "图1-3-3",
        "tau0": tau0,
        "mu_tau0": rho_tau0,
        "rho": rho,
        "sigma": sigma,
        "line_sigma": rho_tau0,
        "curve_sigma": curve_sigma,
        "positive_control_type": positive_type,
        "negative_control_type": negative_type,
        "positive_region": positive_region,
        "negative_region": negative_region,
        "note": "按图1-3-3分区参与本次整线控制值计算",
    }


def _safe_ratio(value: float, denominator: float) -> float:
    """安全计算0到1之间的比例。"""
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, value / denominator))


def _calc_equivalent_distribution_water_hammer_values(
    *,
    equivalent_length_m: float,
    equivalent_wave_speed_mps: float,
    equivalent_velocity_mps: float,
    initial_head_m: float,
    closing_time_s: float,
    distance_from_upstream_m: float,
) -> Dict[str, object]:
    """按等价管参数计算采样点的正、负水击水头增量。"""
    phase_time = (
        2.0 * equivalent_length_m / equivalent_wave_speed_mps
        if equivalent_wave_speed_mps > 0
        else 0.0
    )
    rho = equivalent_wave_speed_mps * equivalent_velocity_mps / (2.0 * GRAVITY * initial_head_m)
    sigma = equivalent_length_m * equivalent_velocity_mps / (GRAVITY * initial_head_m * closing_time_s)
    diagram = _classify_equivalent_water_hammer_region(
        rho=rho,
        sigma=sigma,
        phase_time_s=phase_time,
        closing_time_s=closing_time_s,
    )
    positive_type = str(diagram["positive_control_type"])
    negative_type = str(diagram["negative_control_type"])
    upstream_ratio = _safe_ratio(distance_from_upstream_m, equivalent_length_m)
    downstream_distance = max(0.0, equivalent_length_m - max(0.0, distance_from_upstream_m))
    downstream_ratio = _safe_ratio(downstream_distance, equivalent_length_m)

    direct_zeta = 2.0 * rho
    terminal_positive_zeta = sigma / 2.0 * (sigma + math.sqrt(sigma ** 2 + 4.0))
    terminal_negative_zeta = sigma / 2.0 * (math.sqrt(sigma ** 2 + 4.0) - sigma)
    positive_candidates: List[Dict[str, float | str]] = []
    negative_candidates: List[Dict[str, float | str]] = []

    if positive_type == "直接正水击":
        positive_terminal_zeta = direct_zeta
        positive_zeta = direct_zeta
        distribution_note = "直接水击简化分布"
        positive_candidates.append({"type": "直接正水击", "zeta": direct_zeta})
    elif positive_type == "末相正水击":
        positive_terminal_zeta = terminal_positive_zeta
        positive_zeta = terminal_positive_zeta * upstream_ratio
        distribution_note = "末相水击线性分布"
        positive_candidates.append({"type": "末相正水击", "zeta": terminal_positive_zeta})
    else:
        denominator = 1.0 + rho - sigma
        first_terminal_zeta = 2.0 * sigma / denominator if denominator > 1e-12 else direct_zeta
        sigma_x = downstream_distance * equivalent_velocity_mps / (GRAVITY * initial_head_m * closing_time_s)
        tau_x = downstream_ratio
        local_denominator = 1.0 + rho * tau_x - sigma_x
        local_reduction = 2.0 * sigma_x / local_denominator if local_denominator > 1e-12 else first_terminal_zeta
        positive_terminal_zeta = max(0.0, first_terminal_zeta)
        positive_zeta = max(0.0, min(positive_terminal_zeta, positive_terminal_zeta - local_reduction))
        distribution_note = "一相正水击近似分布"
        positive_candidates.append({"type": "第一相正水击", "zeta": positive_terminal_zeta})

    if negative_type == "直接负水击":
        negative_terminal_zeta = direct_zeta
        negative_zeta = direct_zeta
        negative_distribution_note = "直接水击简化分布"
        negative_candidates.append({"type": "直接负水击", "zeta": direct_zeta})
    elif negative_type == "负末相水击":
        negative_terminal_zeta = terminal_negative_zeta
        negative_zeta = terminal_negative_zeta * upstream_ratio
        negative_distribution_note = "负末相水击线性分布"
        negative_candidates.append({"type": "负末相水击", "zeta": terminal_negative_zeta})
    else:
        sigma_s = max(0.0, distance_from_upstream_m) * equivalent_velocity_mps / (
            GRAVITY * initial_head_m * closing_time_s
        )
        tau_s = upstream_ratio
        negative_terminal_zeta = 2.0 * sigma / (1.0 + rho + sigma)
        negative_zeta = 2.0 * sigma_s / (1.0 + rho * tau_s + sigma_s)
        negative_zeta = max(0.0, min(negative_terminal_zeta, negative_zeta))
        negative_distribution_note = "一相负水击近似分布"
        negative_candidates.append({"type": "第一相负水击", "zeta": negative_terminal_zeta})

    return {
        "phase_time_s": phase_time,
        "ts_to_mu_ratio": closing_time_s / phase_time if phase_time > 0 else None,
        "section_mu": rho,
        "rho": rho,
        "sigma": sigma,
        "positive_zeta": positive_zeta,
        "positive_terminal_zeta": positive_terminal_zeta,
        "positive_delta_h": positive_zeta * initial_head_m,
        "positive_terminal_delta_h": positive_terminal_zeta * initial_head_m,
        "positive_control_type": positive_type,
        "positive_candidates": positive_candidates,
        "negative_zeta": negative_zeta,
        "negative_terminal_zeta": negative_terminal_zeta,
        "negative_delta_h": negative_zeta * initial_head_m,
        "negative_terminal_delta_h": negative_terminal_zeta * initial_head_m,
        "negative_control_type": negative_type,
        "negative_candidates": negative_candidates,
        "distribution_note": distribution_note,
        "negative_distribution_note": negative_distribution_note,
        "diagram_type_check": diagram,
    }


def calc_basic_water_hammer(
    *,
    length_m: float,
    diameter_m: float,
    wall_thickness_m: float,
    elastic_modulus_pa: float,
    velocity_mps: float,
    initial_head_m: Optional[float],
    closing_time_s: float,
    material_key: str = "",
    reinforcement_ratio_a0: Optional[float] = None,
    allowable_pressure_mpa: float = WATER_HAMMER_DEFAULT_ALLOWABLE_PRESSURE_MPA,
    water_bulk_modulus_pa: float = WATER_BULK_MODULUS,
) -> Dict[str, object]:
    """计算简单管道线性启闭水击。"""
    inputs = {
        "length_m": float(length_m or 0.0),
        "diameter_m": float(diameter_m or 0.0),
        "wall_thickness_m": float(wall_thickness_m or 0.0),
        "elastic_modulus_pa": float(elastic_modulus_pa or 0.0),
        "velocity_mps": float(velocity_mps or 0.0),
        "initial_head_m": None if initial_head_m is None else float(initial_head_m),
        "closing_time_s": float(closing_time_s or 0.0),
        "material_key": str(material_key or ""),
        "reinforcement_ratio_a0": None if reinforcement_ratio_a0 is None else float(reinforcement_ratio_a0),
        "allowable_pressure_mpa": float(allowable_pressure_mpa or WATER_HAMMER_DEFAULT_ALLOWABLE_PRESSURE_MPA),
        "water_bulk_modulus_pa": float(water_bulk_modulus_pa or 0.0),
    }
    result: Dict[str, object] = {
        "status": "输入缺失",
        "reason": "",
        "a": None,
        "mu": None,
        "phase_time_s": None,
        "ts_to_mu_ratio": None,
        "section_mu": None,
        "sigma": None,
        "delta_h": None,
        "positive_delta_h": None,
        "positive_control_type": "",
        "positive_candidates": [],
        "gbt_positive_delta_h": None,
        "gbt_positive_method": "",
        "linear_positive_delta_h": None,
        "linear_positive_control_type": "",
        "positive_governing_method": "",
        "negative_delta_h": None,
        "negative_control_type": "",
        "negative_candidates": [],
        "diagram_type_check": {},
        "hmax": None,
        "hmin": None,
        "negative_margin_m": None,
        "negative_pressure_status": "",
        "allowable_pressure_mpa": None,
        "pressure_allow_head_m": None,
        "pressure_margin_m": None,
        "pressure_check_basis": "single_pipe_hmax",
        "pressure_check_basis_label": "单管Hmax",
        "pressure_status": "",
        "is_exempt": False,
        "exemption_threshold_s": None,
        "pipe_coefficient_cp": None,
        "reinforcement_ratio_a0": None,
        "requires_reinforcement_ratio_a0": False,
        "resolved_material_key": "",
        "pipe_coefficient_note": "",
        "wave_speed_formula_source": WATER_HAMMER_WAVE_SPEED_FORMULA_SOURCE,
        "inputs": inputs,
        "calc_steps": "",
    }

    missing_items = []
    if inputs["length_m"] <= 0:
        missing_items.append("L")
    if inputs["diameter_m"] <= 0:
        missing_items.append("D")
    if inputs["wall_thickness_m"] <= 0:
        missing_items.append("壁厚 e")
    if inputs["elastic_modulus_pa"] <= 0:
        missing_items.append("弹性模量 E")
    if inputs["velocity_mps"] <= 0:
        missing_items.append("流速 v0")
    if inputs["initial_head_m"] is None or inputs["initial_head_m"] <= 0:
        missing_items.append("H0")
    if inputs["closing_time_s"] <= 0:
        missing_items.append("启闭时间 Ts")
    if inputs["water_bulk_modulus_pa"] <= 0:
        missing_items.append("体积弹性模量 K")
    if missing_items:
        result["reason"] = f"缺少必要输入：{'、'.join(missing_items)}"
        return result

    pressure_allow_head = convert_pressure_mpa_to_head_m(inputs["allowable_pressure_mpa"])
    if pressure_allow_head is None:
        result["reason"] = "缺少有效允许压力 MPa"
        return result
    result["allowable_pressure_mpa"] = inputs["allowable_pressure_mpa"]
    result["pressure_allow_head_m"] = pressure_allow_head

    pipe_cp, a0, requires_a0, resolved_material, cp_note, cp_error = _resolve_water_hammer_pipe_coefficient(
        material_key=inputs["material_key"],
        reinforcement_ratio_a0=inputs["reinforcement_ratio_a0"],
    )
    result.update(
        {
            "pipe_coefficient_cp": pipe_cp,
            "reinforcement_ratio_a0": a0,
            "requires_reinforcement_ratio_a0": requires_a0,
            "resolved_material_key": resolved_material,
            "pipe_coefficient_note": cp_note,
        }
    )
    if cp_error:
        result["reason"] = cp_error
        return result

    a = _calc_water_hammer_wave_speed(
        diameter_m=inputs["diameter_m"],
        wall_thickness_m=inputs["wall_thickness_m"],
        elastic_modulus_pa=inputs["elastic_modulus_pa"],
        water_bulk_modulus_pa=inputs["water_bulk_modulus_pa"],
        pipe_coefficient_cp=float(pipe_cp or 0.0),
    )
    if a is None or a <= 0:
        result["reason"] = "输入组合无效，无法计算水锤波速"
        return result

    phase_time = 2.0 * inputs["length_m"] / a
    exemption_threshold = 20.0 * phase_time
    result.update(
        {
            "a": a,
            "mu": phase_time,
            "phase_time_s": phase_time,
            "ts_to_mu_ratio": inputs["closing_time_s"] / phase_time if phase_time > 0 else None,
            "exemption_threshold_s": exemption_threshold,
        }
    )
    if inputs["closing_time_s"] + WATER_HAMMER_EXEMPTION_TOLERANCE_S >= exemption_threshold:
        result.update(
            {
                "status": "可不验算",
                "reason": _join_water_hammer_notes(WATER_HAMMER_EXEMPTION_REASON, cp_note),
                "is_exempt": True,
                "allowable_pressure_mpa": inputs["allowable_pressure_mpa"],
                "pressure_allow_head_m": pressure_allow_head,
                "calc_steps": "\n".join(
                    [
                        f"a = 1425 / sqrt(1 + (K/E) * (D/t) * cp) = {a:.6f} m/s",
                        f"cp = {float(pipe_cp or 0.0):.6f}",
                        *([cp_note] if cp_note else []),
                        f"水击相 tr = 2L / c = {phase_time:.6f} s",
                        f"免验算阈值 Ts_limit = 40L / c = {exemption_threshold:.6f} s",
                        "Ts >= Ts_limit，按 GB/T 20203-2017 5.1.7.4 可不验算关阀水击压力",
                    ]
                ),
            }
        )
        return result

    values = _calc_linear_water_hammer_values(
        length_m=inputs["length_m"],
        wave_speed_mps=a,
        velocity_mps=inputs["velocity_mps"],
        initial_head_m=float(inputs["initial_head_m"]),
        closing_time_s=inputs["closing_time_s"],
    )
    values = _merge_positive_water_hammer_governing(
        values,
        length_m=inputs["length_m"],
        wave_speed_mps=a,
        velocity_mps=inputs["velocity_mps"],
        initial_head_m=float(inputs["initial_head_m"]),
        closing_time_s=inputs["closing_time_s"],
    )
    steps = [
        f"a = 1425 / sqrt(1 + (K/E) * (D/t) * cp) = {a:.6f} m/s",
        f"cp = {float(pipe_cp or 0.0):.6f}",
        *([cp_note] if cp_note else []),
        f"水击相 tr = 2L / c = {values['phase_time_s']:.6f} s",
        f"断面系数 μ = c * v0 / (2gH0) = {values['section_mu']:.6f}",
        f"系统系数 σ = L * v0 / (gH0Ts) = {values['sigma']:.6f}",
    ]

    result.update(values)
    result["a"] = a
    result["mu"] = values["phase_time_s"]
    result["is_exempt"] = False
    result["exemption_threshold_s"] = exemption_threshold
    result["delta_h"] = values["positive_delta_h"]
    steps.append(f"GB/T正水击：{values['gbt_positive_method']}，ΔH+ = {values['gbt_positive_delta_h']:.6f} m")
    steps.append(f"线性启闭正水击：{values['positive_control_type']}，ΔH+ = {values['linear_positive_delta_h']:.6f} m")
    steps.append(f"正水击控制：{values['positive_governing_method']}，ΔH+ = {values['positive_delta_h']:.6f} m")
    steps.append(f"负水击控制：{values['negative_control_type']}，ΔH- = {values['negative_delta_h']:.6f} m")
    steps.append(f"Hmax = H0 + ΔH+ = {values['hmax']:.6f} m")
    steps.append(f"Hmin = H0 - ΔH- = {values['hmin']:.6f} m")
    diagram = values.get("diagram_type_check", {}) if isinstance(values.get("diagram_type_check", {}), dict) else {}
    if diagram:
        steps.append(
            "图1-3-3对照："
            f"正={diagram.get('positive_region', '-')}；负={diagram.get('negative_region', '-')}"
        )

    result["status"] = "可计算"
    result["pressure_margin_m"] = pressure_allow_head - float(values["hmax"])
    result["pressure_status"] = "承压通过" if float(result["pressure_margin_m"]) >= -1e-9 else "承压超限"
    result["reason"] = cp_note
    result["calc_steps"] = "\n".join(steps)
    return result


def _water_hammer_number(value, default=None):
    """把输入值安全转为有限浮点数。"""
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _water_hammer_first_number(source: Dict[str, object], keys: List[str], default=None):
    """按多个候选键读取第一个有效数字。"""
    for key in keys:
        if key not in source:
            continue
        number = _water_hammer_number(source.get(key), None)
        if number is not None:
            return number
    return default


def _normalize_water_hammer_line_points(
    points: List[Dict[str, object]],
    *,
    value_keys: List[str],
    value_label: str,
) -> Tuple[List[Dict[str, float]], str]:
    """规范化纵断面或水位线点，返回排序后的桩号-数值列表。"""
    normalized: List[Dict[str, float]] = []
    for point in list(points or []):
        if not isinstance(point, dict):
            continue
        station = _water_hammer_first_number(
            point,
            ["station_m", "station", "station_mc", "station_MC", "chainage", "s"],
            None,
        )
        value = _water_hammer_first_number(point, value_keys, None)
        if station is None or value is None:
            continue
        normalized.append({"station_m": float(station), value_label: float(value)})

    if len(normalized) < 2:
        return [], f"缺少可插值的{value_label}数据"

    normalized.sort(key=lambda item: item["station_m"])
    deduped: List[Dict[str, float]] = []
    for point in normalized:
        if deduped and abs(point["station_m"] - deduped[-1]["station_m"]) <= 1e-9:
            deduped[-1] = point
        else:
            deduped.append(point)
    if len(deduped) < 2:
        return [], f"缺少可插值的{value_label}数据"
    return deduped, ""


def _interpolate_water_hammer_line(
    points: List[Dict[str, float]],
    station_m: float,
    value_label: str,
) -> float:
    """按桩号在线性折线上插值。"""
    station = float(station_m)
    tol = WATER_HAMMER_STATION_TOLERANCE_M
    if station < points[0]["station_m"] - tol or station > points[-1]["station_m"] + tol:
        raise ValueError(
            f"采样点 {station:.3f} 超出数据覆盖范围 "
            f"{points[0]['station_m']:.3f}~{points[-1]['station_m']:.3f}"
        )
    for point in points:
        if abs(point["station_m"] - station) <= tol:
            return point[value_label]
    for left, right in zip(points[:-1], points[1:]):
        left_s = left["station_m"]
        right_s = right["station_m"]
        if left_s - tol <= station <= right_s + tol:
            span = right_s - left_s
            if abs(span) <= 1e-12:
                return left[value_label]
            ratio = (station - left_s) / span
            return left[value_label] + (right[value_label] - left[value_label]) * ratio
    raise ValueError(
        f"采样点 {station:.3f} 超出数据覆盖范围 "
        f"{points[0]['station_m']:.3f}~{points[-1]['station_m']:.3f}"
    )


def _normalize_water_hammer_members(
    members: List[Dict[str, object]],
    *,
    wall_thickness_m: float,
    water_bulk_modulus_pa: float,
) -> Tuple[List[Dict[str, float]], str]:
    """规范化连续有压段成员并计算每个成员的水锤基础值。"""
    normalized: List[Dict[str, float]] = []
    for index, member in enumerate(list(members or [])):
        if not isinstance(member, dict):
            continue
        start_station = _water_hammer_first_number(
            member,
            ["start_station_m", "segment_start_m", "start_mc", "segment_start_mc", "start"],
            None,
        )
        end_station = _water_hammer_first_number(
            member,
            ["end_station_m", "segment_end_m", "end_mc", "segment_end_mc", "end"],
            None,
        )
        diameter = _water_hammer_first_number(member, ["diameter_m", "D", "diameter"], None)
        elastic = _water_hammer_first_number(member, ["elastic_modulus_pa", "E"], None)
        velocity = _water_hammer_first_number(member, ["velocity_mps", "v0", "pipe_velocity"], None)
        material_key = str(member.get("material_key", member.get("pipe_material", "")) or "").strip()
        a0 = _water_hammer_first_number(
            member,
            ["water_hammer_a0", "reinforcement_ratio_a0", "a0"],
            None,
        )
        if start_station is None or end_station is None:
            return [], "缺少成员桩号范围"
        if diameter is None or diameter <= 0:
            return [], "缺少有效管径 D"
        if elastic is None or elastic <= 0:
            return [], "缺少有效弹性模量 E"
        if velocity is None or velocity <= 0:
            return [], "缺少有效流速 v0"
        length = abs(float(end_station) - float(start_station))
        if length <= 0:
            return [], "存在起终点相同的管段，请检查该行桩号或忽略起点锚点"
        pipe_cp, resolved_a0, requires_a0, resolved_material, cp_note, cp_error = _resolve_water_hammer_pipe_coefficient(
            material_key=material_key,
            reinforcement_ratio_a0=a0,
        )
        if cp_error:
            member_key = str(member.get("key", member.get("member_key", f"member-{index + 1}")) or f"member-{index + 1}")
            return [], f"成员 {member_key}：{cp_error}"
        wave_speed = _calc_water_hammer_wave_speed(
            diameter_m=float(diameter),
            wall_thickness_m=wall_thickness_m,
            elastic_modulus_pa=float(elastic),
            water_bulk_modulus_pa=water_bulk_modulus_pa,
            pipe_coefficient_cp=float(pipe_cp or 0.0),
        )
        if wave_speed is None or wave_speed <= 0:
            return [], "输入组合无效，无法计算水锤波速"
        direct_delta_h = wave_speed * float(velocity) / GRAVITY
        normalized.append(
            {
                "key": str(member.get("key", member.get("member_key", f"member-{index + 1}")) or f"member-{index + 1}"),
                "start_station_m": min(float(start_station), float(end_station)),
                "end_station_m": max(float(start_station), float(end_station)),
                "length_m": length,
                "diameter_m": float(diameter),
                "elastic_modulus_pa": float(elastic),
                "velocity_mps": float(velocity),
                "material_key": material_key,
                "resolved_material_key": resolved_material,
                "pipe_coefficient_cp": float(pipe_cp or 0.0),
                "reinforcement_ratio_a0": resolved_a0,
                "requires_reinforcement_ratio_a0": requires_a0,
                "pipe_coefficient_note": cp_note,
                "wave_speed_formula_source": WATER_HAMMER_WAVE_SPEED_FORMULA_SOURCE,
                "a": wave_speed,
                "delta_h": direct_delta_h,
            }
        )

    if not normalized:
        return [], "缺少连续有压段成员"
    normalized.sort(key=lambda item: (item["start_station_m"], item["end_station_m"]))
    return normalized, ""


def _build_water_hammer_sample_stations(
    *,
    members: List[Dict[str, float]],
    centerline_points: List[Dict[str, float]],
    water_level_points: List[Dict[str, float]],
    sample_interval_m: float,
) -> List[float]:
    """按指定步长采样，并强制纳入起终点、折点和成员分界点。"""
    start_station = min(member["start_station_m"] for member in members)
    end_station = max(member["end_station_m"] for member in members)
    interval = sample_interval_m if sample_interval_m > 0 else WATER_HAMMER_DISTRIBUTION_SAMPLE_INTERVAL_M
    stations = {round(start_station, 6), round(end_station, 6)}
    current = start_station
    guard = 0
    while current < end_station - 1e-9 and guard < 1000000:
        stations.add(round(current, 6))
        current += interval
        guard += 1
    for member in members:
        stations.add(round(member["start_station_m"], 6))
        stations.add(round(member["end_station_m"], 6))
    for point in centerline_points:
        station = point["station_m"]
        if start_station - 1e-7 <= station <= end_station + 1e-7:
            stations.add(round(station, 6))
    for point in water_level_points:
        station = point["station_m"]
        if start_station - 1e-7 <= station <= end_station + 1e-7:
            stations.add(round(station, 6))
    return sorted(float(station) for station in stations if start_station - 1e-7 <= station <= end_station + 1e-7)


def _water_hammer_member_at_station(members: List[Dict[str, float]], station_m: float) -> Dict[str, float]:
    """返回采样点所在成员，分界点优先归入下游成员。"""
    station = float(station_m)
    tol = 1e-7
    for member in members:
        if abs(station - member["start_station_m"]) <= tol:
            return member
    for index, member in enumerate(members):
        is_last = index == len(members) - 1
        if member["start_station_m"] - tol <= station < member["end_station_m"] - tol:
            return member
        if is_last and member["start_station_m"] - tol <= station <= member["end_station_m"] + tol:
            return member
    return members[-1]


def _water_hammer_members_at_station(members: List[Dict[str, float]], station_m: float) -> List[Dict[str, float]]:
    """返回采样点需要校核的成员，分界点同时校核相邻两侧。"""
    station = float(station_m)
    tol = 1e-7
    matched: List[Dict[str, float]] = []
    for member in members:
        if member["start_station_m"] - tol <= station <= member["end_station_m"] + tol:
            matched.append(member)
    return matched or [_water_hammer_member_at_station(members, station)]


def calc_distributed_water_hammer_check(
    *,
    members: List[Dict[str, object]],
    centerline_nodes: List[Dict[str, object]],
    water_level_nodes: List[Dict[str, object]],
    wall_thickness_m: float,
    closing_time_s: float,
    allowable_pressure_mpa: float = WATER_HAMMER_DEFAULT_ALLOWABLE_PRESSURE_MPA,
    sample_interval_m: float = WATER_HAMMER_DISTRIBUTION_SAMPLE_INTERVAL_M,
    water_bulk_modulus_pa: float = WATER_BULK_MODULUS,
) -> Dict[str, object]:
    """按连续有压段进行全线水锤附加水头分布校核。"""
    result: Dict[str, object] = {
        "status": "数据缺失",
        "reason": "",
        "a": None,
        "a_min": None,
        "a_max": None,
        "mu": None,
        "phase_time_s": None,
        "ts_to_mu_ratio": None,
        "section_mu": None,
        "sigma": None,
        "delta_h": None,
        "positive_delta_h": None,
        "positive_control_type": "",
        "gbt_positive_delta_h": None,
        "gbt_positive_method": "",
        "linear_positive_delta_h": None,
        "linear_positive_control_type": "",
        "positive_governing_method": "",
        "negative_delta_h": None,
        "negative_control_type": "",
        "negative_margin_m": None,
        "negative_pressure_risk_count": 0,
        "min_negative_margin_m": None,
        "negative_critical_point": None,
        "diagram_type_check": {},
        "control_member_key": "",
        "hmax": None,
        "hmin": None,
        "allowable_pressure_mpa": WATER_HAMMER_DEFAULT_ALLOWABLE_PRESSURE_MPA,
        "pressure_allow_head_m": None,
        "pressure_check_basis": WATER_HAMMER_PRESSURE_CHECK_BASIS_PIPE_BOTTOM,
        "pressure_check_basis_label": WATER_HAMMER_PRESSURE_CHECK_BASIS_LABELS[WATER_HAMMER_PRESSURE_CHECK_BASIS_PIPE_BOTTOM],
        "equivalent_length_m": None,
        "equivalent_wave_speed_mps": None,
        "equivalent_velocity_mps": None,
        "min_margin_m": None,
        "critical_point": None,
        "exceed_count": 0,
        "sample_count": 0,
        "member_results": [],
        "details": [],
        "is_exempt": False,
        "exemption_threshold_s": None,
        "pipe_coefficient_cp": None,
        "reinforcement_ratio_a0": None,
        "pipe_coefficient_note": "",
        "wave_speed_formula_source": WATER_HAMMER_WAVE_SPEED_FORMULA_SOURCE,
        "inputs": {
            "wall_thickness_m": _water_hammer_number(wall_thickness_m, 0.0),
            "closing_time_s": _water_hammer_number(closing_time_s, 0.0),
            "sample_interval_m": _water_hammer_number(
                sample_interval_m,
                WATER_HAMMER_DISTRIBUTION_SAMPLE_INTERVAL_M,
            ),
            "allowable_pressure_mpa": _water_hammer_number(
                allowable_pressure_mpa,
                WATER_HAMMER_DEFAULT_ALLOWABLE_PRESSURE_MPA,
            ),
        },
    }

    wall_thickness = _water_hammer_number(wall_thickness_m, 0.0)
    closing_time = _water_hammer_number(closing_time_s, 0.0)
    allowable_pressure = _water_hammer_number(allowable_pressure_mpa, WATER_HAMMER_DEFAULT_ALLOWABLE_PRESSURE_MPA)
    water_bulk_modulus = _water_hammer_number(water_bulk_modulus_pa, 0.0)
    if wall_thickness <= 0:
        result["reason"] = "缺少有效壁厚 e"
        return result
    if closing_time <= 0:
        result["reason"] = "缺少有效启闭时间 Ts"
        return result
    if allowable_pressure <= 0:
        result["reason"] = "缺少有效允许压力 MPa"
        return result
    if water_bulk_modulus <= 0:
        result["reason"] = "缺少有效水体体积弹性模量 K"
        return result
    pressure_allow_head = convert_pressure_mpa_to_head_m(allowable_pressure)
    if pressure_allow_head is None:
        result["reason"] = "允许压力无法换算为工程水头"
        return result
    result["allowable_pressure_mpa"] = allowable_pressure
    result["pressure_allow_head_m"] = pressure_allow_head
    result["inputs"]["allowable_pressure_mpa"] = allowable_pressure

    normalized_members, member_error = _normalize_water_hammer_members(
        members,
        wall_thickness_m=wall_thickness,
        water_bulk_modulus_pa=water_bulk_modulus,
    )
    if member_error:
        result["reason"] = member_error
        return result

    centerline_points, centerline_error = _normalize_water_hammer_line_points(
        centerline_nodes,
        value_keys=["elevation_m", "elevation", "centerline_elevation_m", "centerline_elevation", "z"],
        value_label="centerline_elevation_m",
    )
    if centerline_error:
        result["reason"] = f"缺少纵断面中心线数据：{centerline_error}"
        return result

    water_level_points, water_level_error = _normalize_water_hammer_line_points(
        water_level_nodes,
        value_keys=["water_level_m", "water_level", "level_m", "allowed_head_elevation_m"],
        value_label="water_level_m",
    )
    if water_level_error:
        result["reason"] = f"缺少表3水位线数据：{water_level_error}"
        return result

    equivalent_length = sum(member["length_m"] for member in normalized_members)
    wave_travel_sum = sum(member["length_m"] / member["a"] for member in normalized_members if member["a"] > 0)
    equivalent_wave_speed = equivalent_length / wave_travel_sum if wave_travel_sum > 0 else 0.0
    equivalent_velocity = (
        sum(member["length_m"] * member["velocity_mps"] for member in normalized_members) / equivalent_length
        if equivalent_length > 0
        else 0.0
    )
    phase_time = 2.0 * wave_travel_sum
    ts_ratio = closing_time / phase_time if phase_time > 0 else None
    a_values = [member["a"] for member in normalized_members]
    cp_values = [float(member.get("pipe_coefficient_cp", 0.0) or 0.0) for member in normalized_members]
    cp_summary = cp_values[0] if cp_values and all(abs(value - cp_values[0]) <= 1e-12 for value in cp_values) else None
    cp_note = _join_water_hammer_notes(*(member.get("pipe_coefficient_note", "") for member in normalized_members))
    a0_values = [
        member.get("reinforcement_ratio_a0")
        for member in normalized_members
        if member.get("reinforcement_ratio_a0") is not None
    ]
    a0_summary = a0_values[0] if len(a0_values) == 1 else None
    result.update(
        {
            "a_min": min(a_values),
            "a_max": max(a_values),
            "mu": phase_time,
            "phase_time_s": phase_time,
            "ts_to_mu_ratio": ts_ratio,
            "equivalent_length_m": equivalent_length,
            "equivalent_wave_speed_mps": equivalent_wave_speed,
            "equivalent_velocity_mps": equivalent_velocity,
            "pipe_coefficient_cp": cp_summary,
            "reinforcement_ratio_a0": a0_summary,
            "pipe_coefficient_note": cp_note,
        }
    )

    if phase_time <= 0:
        result["reason"] = "水锤相时 μ 无效，无法继续验算"
        return result

    exemption_threshold = 20.0 * phase_time
    result["exemption_threshold_s"] = exemption_threshold
    if closing_time + WATER_HAMMER_EXEMPTION_TOLERANCE_S >= exemption_threshold:
        result.update(
            {
                "status": "可不验算",
                "reason": _join_water_hammer_notes(WATER_HAMMER_EXEMPTION_REASON, cp_note),
                "is_exempt": True,
                "sample_count": 0,
                "member_results": [
                    {
                        "key": member["key"],
                        "start_station_m": member["start_station_m"],
                        "end_station_m": member["end_station_m"],
                        "length_m": member["length_m"],
                        "diameter_m": member["diameter_m"],
                        "velocity_mps": member["velocity_mps"],
                        "a": member["a"],
                        "material_key": member.get("material_key", ""),
                        "resolved_material_key": member.get("resolved_material_key", ""),
                        "pipe_coefficient_cp": member.get("pipe_coefficient_cp"),
                        "reinforcement_ratio_a0": member.get("reinforcement_ratio_a0"),
                        "pipe_coefficient_note": member.get("pipe_coefficient_note", ""),
                        "wave_speed_formula_source": member.get("wave_speed_formula_source"),
                        "delta_h": None,
                        "positive_delta_h": None,
                        "positive_control_type": "",
                        "gbt_positive_delta_h": None,
                        "gbt_positive_method": "",
                        "linear_positive_delta_h": None,
                        "linear_positive_control_type": "",
                        "positive_governing_method": "",
                        "negative_delta_h": None,
                        "negative_control_type": "",
                    }
                    for member in normalized_members
                ],
                "details": [],
            }
        )
        return result

    stations = _build_water_hammer_sample_stations(
        members=normalized_members,
        centerline_points=centerline_points,
        water_level_points=water_level_points,
        sample_interval_m=(
            _water_hammer_number(sample_interval_m, WATER_HAMMER_DISTRIBUTION_SAMPLE_INTERVAL_M)
            or WATER_HAMMER_DISTRIBUTION_SAMPLE_INTERVAL_M
        ),
    )
    details: List[Dict[str, object]] = []
    member_summary: Dict[str, Dict[str, object]] = {
        member["key"]: {
            "key": member["key"],
            "start_station_m": member["start_station_m"],
            "end_station_m": member["end_station_m"],
            "length_m": member["length_m"],
            "diameter_m": member["diameter_m"],
            "velocity_mps": member["velocity_mps"],
            "material_key": member.get("material_key", ""),
            "resolved_material_key": member.get("resolved_material_key", ""),
            "pipe_coefficient_cp": member.get("pipe_coefficient_cp"),
            "reinforcement_ratio_a0": member.get("reinforcement_ratio_a0"),
            "pipe_coefficient_note": member.get("pipe_coefficient_note", ""),
            "wave_speed_formula_source": member.get("wave_speed_formula_source"),
            "a": member["a"],
            "delta_h": 0.0,
            "positive_delta_h": 0.0,
            "positive_control_type": "",
            "gbt_positive_delta_h": 0.0,
            "gbt_positive_method": "",
            "linear_positive_delta_h": 0.0,
            "linear_positive_control_type": "",
            "positive_governing_method": "",
            "negative_delta_h": 0.0,
            "negative_control_type": "",
        }
        for member in normalized_members
    }
    route_start = min(member["start_station_m"] for member in normalized_members)
    try:
        for station in stations:
            centerline_elevation = _interpolate_water_hammer_line(
                centerline_points,
                station,
                "centerline_elevation_m",
            )
            water_level = _interpolate_water_hammer_line(
                water_level_points,
                station,
                "water_level_m",
            )
            for member in _water_hammer_members_at_station(normalized_members, station):
                pipe_top = centerline_elevation + member["diameter_m"] / 2.0
                pipe_bottom = centerline_elevation - member["diameter_m"] / 2.0
                initial_pressure_head = water_level - centerline_elevation
                h_st = water_level
                if initial_pressure_head <= 0:
                    values = {
                        "positive_delta_h": 0.0,
                        "positive_terminal_delta_h": 0.0,
                        "positive_control_type": "初始压强水头不足",
                        "gbt_positive_delta_h": 0.0,
                        "gbt_positive_method": "初始压强水头不足",
                        "linear_positive_delta_h": 0.0,
                        "linear_positive_control_type": "初始压强水头不足",
                        "positive_governing_method": "初始压强水头不足",
                        "negative_delta_h": 0.0,
                        "negative_terminal_delta_h": 0.0,
                        "negative_control_type": "初始压强水头不足",
                        "section_mu": None,
                        "rho": None,
                        "sigma": None,
                        "diagram_type_check": {},
                        "distribution_note": "初始压强水头不足",
                        "negative_distribution_note": "初始压强水头不足",
                    }
                else:
                    values = _calc_equivalent_distribution_water_hammer_values(
                        equivalent_length_m=equivalent_length,
                        equivalent_wave_speed_mps=equivalent_wave_speed,
                        equivalent_velocity_mps=equivalent_velocity,
                        initial_head_m=initial_pressure_head,
                        closing_time_s=closing_time,
                        distance_from_upstream_m=float(station) - route_start,
                    )
                    gbt_positive_delta_h, gbt_method = _calc_gbt_positive_water_hammer(
                        length_m=equivalent_length,
                        wave_speed_mps=equivalent_wave_speed,
                        velocity_mps=equivalent_velocity,
                        closing_time_s=closing_time,
                    )
                    linear_positive_delta_h = float(values.get("positive_delta_h", 0.0) or 0.0)
                    linear_positive_terminal_delta_h = float(values.get("positive_terminal_delta_h", 0.0) or 0.0)
                    tolerance = max(1e-9, max(abs(gbt_positive_delta_h), abs(linear_positive_terminal_delta_h)) * 1e-9)
                    if abs(gbt_positive_delta_h - linear_positive_terminal_delta_h) <= tolerance:
                        positive_governing_method = WATER_HAMMER_GOVERNING_EQUAL_METHOD
                        positive_delta_h = max(linear_positive_delta_h, gbt_positive_delta_h)
                    elif gbt_positive_delta_h > linear_positive_terminal_delta_h:
                        positive_governing_method = gbt_method
                        positive_delta_h = gbt_positive_delta_h
                        values["distribution_note"] = "GB/T正水击保守同幅分布"
                    else:
                        positive_governing_method = WATER_HAMMER_LINEAR_METHOD
                        positive_delta_h = linear_positive_delta_h
                    values.update(
                        {
                            "gbt_positive_delta_h": gbt_positive_delta_h,
                            "gbt_positive_method": gbt_method,
                            "linear_positive_delta_h": linear_positive_delta_h,
                            "linear_positive_control_type": values.get("positive_control_type", ""),
                            "positive_governing_method": positive_governing_method,
                            "positive_delta_h": positive_delta_h,
                        }
                    )
                positive_delta_h = float(values["positive_delta_h"])
                negative_delta_h = float(values["negative_delta_h"])
                hmax = h_st + positive_delta_h
                hmin = h_st - negative_delta_h
                pressure_head_max = hmax - pipe_bottom
                pressure_margin = pressure_allow_head - pressure_head_max
                top_min_pressure_head = hmin - pipe_top
                negative_margin = top_min_pressure_head
                summary = member_summary[member["key"]]
                if positive_delta_h > float(summary["positive_delta_h"]):
                    summary["delta_h"] = positive_delta_h
                    summary["positive_delta_h"] = positive_delta_h
                    summary["positive_control_type"] = str(values["positive_control_type"])
                    summary["gbt_positive_delta_h"] = float(values.get("gbt_positive_delta_h", 0.0) or 0.0)
                    summary["gbt_positive_method"] = str(values.get("gbt_positive_method", "") or "")
                    summary["linear_positive_delta_h"] = float(values.get("linear_positive_delta_h", 0.0) or 0.0)
                    summary["linear_positive_control_type"] = str(values.get("linear_positive_control_type", "") or "")
                    summary["positive_governing_method"] = str(values.get("positive_governing_method", "") or "")
                if negative_delta_h > float(summary["negative_delta_h"]):
                    summary["negative_delta_h"] = negative_delta_h
                    summary["negative_control_type"] = str(values["negative_control_type"])
                details.append(
                    {
                        "station_m": station,
                        "member_key": member["key"],
                        "centerline_elevation_m": centerline_elevation,
                        "diameter_m": member["diameter_m"],
                        "velocity_mps": member["velocity_mps"],
                        "a": member["a"],
                        "material_key": member.get("material_key", ""),
                        "resolved_material_key": member.get("resolved_material_key", ""),
                        "pipe_coefficient_cp": member.get("pipe_coefficient_cp"),
                        "reinforcement_ratio_a0": member.get("reinforcement_ratio_a0"),
                        "pipe_coefficient_note": member.get("pipe_coefficient_note", ""),
                        "wave_speed_formula_source": member.get("wave_speed_formula_source"),
                        "pipe_top_elevation_m": pipe_top,
                        "pipe_centerline_elevation_m": centerline_elevation,
                        "pipe_bottom_elevation_m": pipe_bottom,
                        "water_level_m": water_level,
                        "h_st_m": h_st,
                        "hmax_m": hmax,
                        "hmin_m": hmin,
                        "initial_pressure_head_m": initial_pressure_head,
                        "allowable_delta_h_m": pressure_allow_head - (h_st - pipe_bottom),
                        "pressure_allow_head_m": pressure_allow_head,
                        "allowable_pressure_mpa": allowable_pressure,
                        "pressure_check_basis": WATER_HAMMER_PRESSURE_CHECK_BASIS_PIPE_BOTTOM,
                        "pressure_check_basis_label": WATER_HAMMER_PRESSURE_CHECK_BASIS_LABELS[
                            WATER_HAMMER_PRESSURE_CHECK_BASIS_PIPE_BOTTOM
                        ],
                        "pressure_head_max_m": pressure_head_max,
                        "pressure_margin_m": pressure_margin,
                        "top_min_pressure_head_m": top_min_pressure_head,
                        "delta_h_m": positive_delta_h,
                        "positive_delta_h_m": positive_delta_h,
                        "gbt_positive_delta_h_m": values.get("gbt_positive_delta_h"),
                        "gbt_positive_method": values.get("gbt_positive_method", ""),
                        "linear_positive_delta_h_m": values.get("linear_positive_delta_h"),
                        "linear_positive_control_type": values.get("linear_positive_control_type", ""),
                        "positive_governing_method": values.get("positive_governing_method", ""),
                        "margin_m": pressure_margin,
                        "positive_margin_m": pressure_margin,
                        "negative_delta_h_m": negative_delta_h,
                        "negative_margin_m": negative_margin,
                        "distribution_note": values.get("distribution_note", ""),
                        "negative_distribution_note": values.get("negative_distribution_note", ""),
                        "section_mu": values.get("section_mu"),
                        "rho": values.get("rho"),
                        "sigma": values.get("sigma"),
                        "positive_control_type": values.get("positive_control_type", ""),
                        "negative_control_type": values.get("negative_control_type", ""),
                        "diagram_type_check": values.get("diagram_type_check", {}),
                        "status": "通过" if pressure_margin >= -1e-9 else "承压超限",
                        "negative_status": "安全" if negative_margin >= -1e-9 else "管顶负压风险",
                    }
                )
    except ValueError as exc:
        result["reason"] = f"纵断面或表3水位线覆盖不足：{exc}"
        return result

    if not details:
        result["reason"] = "没有生成有效采样点"
        return result

    critical = min(details, key=lambda item: float(item["margin_m"]))
    negative_critical = min(details, key=lambda item: float(item["negative_margin_m"]))
    positive_control_detail = max(details, key=lambda item: float(item["positive_delta_h_m"]))
    negative_control_detail = max(details, key=lambda item: float(item["negative_delta_h_m"]))
    hmax_detail = max(details, key=lambda item: float(item["hmax_m"]))
    hmin_detail = min(details, key=lambda item: float(item["hmin_m"]))
    exceed_count = sum(1 for item in details if float(item["margin_m"]) < -1e-9)
    negative_risk_count = sum(1 for item in details if float(item["negative_margin_m"]) < -1e-9)
    critical_point = dict(critical)
    negative_critical_point = dict(negative_critical)
    control_member_key = str(positive_control_detail.get("member_key", "") or "")
    result.update(
        {
            "status": "通过" if exceed_count == 0 and negative_risk_count == 0 else "不通过",
            "reason": cp_note,
            "a": positive_control_detail.get("a"),
            "section_mu": positive_control_detail.get("section_mu"),
            "sigma": positive_control_detail.get("sigma"),
            "delta_h": float(positive_control_detail["positive_delta_h_m"]),
            "positive_delta_h": float(positive_control_detail["positive_delta_h_m"]),
            "positive_control_type": str(positive_control_detail.get("positive_control_type", "") or ""),
            "gbt_positive_delta_h": positive_control_detail.get("gbt_positive_delta_h_m"),
            "gbt_positive_method": str(positive_control_detail.get("gbt_positive_method", "") or ""),
            "linear_positive_delta_h": positive_control_detail.get("linear_positive_delta_h_m"),
            "linear_positive_control_type": str(positive_control_detail.get("linear_positive_control_type", "") or ""),
            "positive_governing_method": str(positive_control_detail.get("positive_governing_method", "") or ""),
            "negative_delta_h": float(negative_control_detail["negative_delta_h_m"]),
            "negative_control_type": str(negative_control_detail.get("negative_control_type", "") or ""),
            "negative_margin_m": float(negative_critical["negative_margin_m"]),
            "min_negative_margin_m": float(negative_critical["negative_margin_m"]),
            "negative_pressure_risk_count": negative_risk_count,
            "negative_critical_point": negative_critical_point,
            "hmax": float(hmax_detail["hmax_m"]),
            "hmin": float(hmin_detail["hmin_m"]),
            "diagram_type_check": dict(positive_control_detail.get("diagram_type_check", {}) or {}),
            "control_member_key": control_member_key,
            "pipe_coefficient_cp": positive_control_detail.get("pipe_coefficient_cp"),
            "reinforcement_ratio_a0": positive_control_detail.get("reinforcement_ratio_a0"),
            "pipe_coefficient_note": cp_note,
            "wave_speed_formula_source": positive_control_detail.get(
                "wave_speed_formula_source",
                WATER_HAMMER_WAVE_SPEED_FORMULA_SOURCE,
            ),
            "min_margin_m": float(critical["margin_m"]),
            "critical_point": critical_point,
            "exceed_count": exceed_count,
            "sample_count": len(details),
            "member_results": list(member_summary.values()),
            "details": details,
        }
    )
    return result


def calc_friction_loss(Q_m3s: float, D_m: float, L_m: float, material_key: str) -> Tuple[float, Dict]:
    """
    计算沿程水头损失（GB 50288-2018 §6.7.2）
    
    公式: hf = f × L × Q^m / d^b
    
    注意单位换算：
    - Q: m³/s → m³/h (×3600)
    - d: m → mm (×1000)
    - L: m（直接使用）
    - hf: m
    
    Args:
        Q_m3s: 设计流量 (m³/s)
        D_m: 管径 (m)
        L_m: 管长 (m)
        material_key: 管材键名
    
    Returns:
        (沿程水头损失 hf (m), 计算详情字典)
    """
    if material_key not in PIPE_MATERIALS:
        return 0.0, {"error": f"未知管材: {material_key}"}
    
    mat = PIPE_MATERIALS[material_key]
    f = mat["f"]
    m = mat["m"]
    b = mat["b"]
    
    # 单位换算
    Q_m3h = Q_m3s * 3600  # m³/s → m³/h
    d_mm = D_m * 1000      # m → mm
    
    if d_mm <= 0:
        return 0.0, {"error": "管径必须大于0"}
    
    # GB 50288 公式 6.7.2-1
    hf = f * L_m * (Q_m3h ** m) / (d_mm ** b)
    
    details = {
        "formula": "hf = f × L × Q^m / d^b",
        "material": mat["name"],
        "f": f,
        "m": m,
        "b": b,
        "Q_m3s": Q_m3s,
        "Q_m3h": Q_m3h,
        "D_m": D_m,
        "d_mm": d_mm,
        "L_m": L_m,
        "hf": hf,
    }
    
    return hf, details


def calc_bend_local_loss(D_m: float, turn_radius_m: float, turn_angle_deg: float, 
                         V_m_s: float) -> Tuple[float, float, Dict]:
    """
    计算弯头局部水头损失（参考倒虹吸表L.1.4-3/L.1.4-4）
    
    Args:
        D_m: 管径 (m)
        turn_radius_m: 转弯半径 (m)
        turn_angle_deg: 转角 (度)
        V_m_s: 管内流速 (m/s)
    
    Returns:
        (局部损失系数 ξ, 局部水头损失 hj (m), 计算详情字典)
    """
    # < 0.1° 视为直线通过（坐标噪声），>= 180° 为旧版错误存档值，均不计损失
    if D_m <= 0 or turn_radius_m <= 0 or turn_angle_deg < 0.1 or turn_angle_deg >= 180:
        return 0.0, 0.0, {"error": "参数无效"}
    
    R_D = turn_radius_m / D_m
    
    # 使用倒虹吸的系数服务查表
    if CoefficientService:
        xi_90 = CoefficientService.get_xi_90(R_D)
        gamma = CoefficientService.get_gamma(turn_angle_deg)
    else:
        # 如果无法导入，使用简化公式
        xi_90 = _lookup_xi90_simplified(R_D)
        gamma = _lookup_gamma_simplified(turn_angle_deg)
    
    xi_bend = xi_90 * gamma
    hj = xi_bend * V_m_s ** 2 / (2 * GRAVITY)
    
    details = {
        "formula": "ξ = ξ_90 × γ, hj = ξ × V² / (2g)",
        "D_m": D_m,
        "turn_radius_m": turn_radius_m,
        "turn_angle_deg": turn_angle_deg,
        "R_D": R_D,
        "xi_90": xi_90,
        "gamma": gamma,
        "xi_bend": xi_bend,
        "V_m_s": V_m_s,
        "hj": hj,
    }
    
    return xi_bend, hj, details


def _lookup_xi90_simplified(R_D: float) -> float:
    """简化的直角弯道系数查表（备用）"""
    table = [
        (0.5, 1.20), (1.0, 0.80), (1.5, 0.60), (2.0, 0.48),
        (3.0, 0.36), (4.0, 0.30), (5.0, 0.29), (6.0, 0.28),
        (7.0, 0.27), (8.0, 0.26), (9.0, 0.25), (10.0, 0.24),
    ]
    return _linear_interpolate(table, R_D)


def _lookup_gamma_simplified(angle: float) -> float:
    """简化的角度修正系数查表（备用）"""
    table = [
        (5, 0.125), (10, 0.23), (20, 0.40), (30, 0.55),
        (40, 0.65), (50, 0.75), (60, 0.83), (70, 0.88),
        (80, 0.95), (90, 1.00), (100, 1.05), (120, 1.13), (140, 1.20),
    ]
    return _linear_interpolate(table, angle)


def _linear_interpolate(table: List[Tuple[float, float]], x: float) -> float:
    """线性插值"""
    if x <= table[0][0]:
        return table[0][1]
    if x >= table[-1][0]:
        return table[-1][1]
    
    for i in range(len(table) - 1):
        x1, y1 = table[i]
        x2, y2 = table[i + 1]
        if x1 <= x <= x2:
            return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    
    return table[-1][1]


def calc_transition_loss(V_pipe: float, V_channel: float, zeta: float, 
                        is_inlet: bool = True) -> Tuple[float, Dict]:
    """
    计算渐变段水头损失
    
    进口（收缩）: hj = ζ × (V_pipe² - V_channel²) / (2g)
    出口（扩散）: hj = ζ × (V_channel² - V_pipe²) / (2g)
    
    Args:
        V_pipe: 管内流速 (m/s)
        V_channel: 渠道流速 (m/s)
        zeta: 局部损失系数 ζ
        is_inlet: 是否为进口渐变段
    
    Returns:
        (渐变段水头损失 hj (m), 计算详情字典)
    """
    if is_inlet:
        # 进口：渠道→管道（收缩，流速增大）
        delta_v2 = V_pipe ** 2 - V_channel ** 2
        formula = "hj = ζ × (V_pipe² - V_channel²) / (2g)"
    else:
        # 出口：管道→渠道（扩散，流速减小）
        delta_v2 = V_channel ** 2 - V_pipe ** 2
        formula = "hj = ζ × (V_channel² - V_pipe²) / (2g)"
    
    hj = zeta * delta_v2 / (2 * GRAVITY)
    hj = max(0, hj)  # 负值取零
    
    details = {
        "formula": formula,
        "is_inlet": is_inlet,
        "V_pipe": V_pipe,
        "V_channel": V_channel,
        "zeta": zeta,
        "delta_v2": delta_v2,
        "hj": hj,
    }
    
    return hj, details


def get_transition_zeta(form: str, is_inlet: bool) -> float:
    """
    获取渐变段局部损失系数
    
    Args:
        form: 渐变段型式
        is_inlet: 是否为进口渐变段
    
    Returns:
        局部损失系数 ζ
    """
    if form not in TRANSITION_FORMS:
        form = "反弯扭曲面"  # 默认
    
    if is_inlet:
        return TRANSITION_FORMS[form]["inlet_zeta"]
    else:
        return TRANSITION_FORMS[form]["outlet_zeta"]


def _resolve_transition_zeta(form: str, zeta_override: Optional[float], is_inlet: bool) -> float:
    """解析渐变段局部损失系数，优先使用显式传入值。"""
    if zeta_override is not None and zeta_override > 0:
        return zeta_override
    return get_transition_zeta(form, is_inlet=is_inlet)


def _build_skipped_transition_details(
    *,
    V_pipe: float,
    V_channel: float,
    zeta: float,
    form: str,
    is_inlet: bool,
    reason: str,
) -> Dict:
    """构造“无渐变段，跳过计算”时的详情字典。"""
    formula = "hj = ζ × (V_pipe² - V_channel²) / (2g)" if is_inlet else "hj = ζ × (V_channel² - V_pipe²) / (2g)"
    return {
        "formula": formula,
        "is_inlet": is_inlet,
        "V_pipe": V_pipe,
        "V_channel": V_channel,
        "zeta": zeta,
        "delta_v2": 0.0,
        "hj": 0.0,
        "form": form,
        "skipped": True,
        "reason": reason,
    }


# ============================================================
# 4. 转角计算
# ============================================================

def calc_turn_angle(p_prev: Tuple[float, float], p_curr: Tuple[float, float], 
                   p_next: Tuple[float, float]) -> float:
    """
    计算中间IP点的转角
    
    Args:
        p_prev: 前一个点坐标 (x, y)
        p_curr: 当前点坐标 (x, y)
        p_next: 后一个点坐标 (x, y)
    
    Returns:
        转角 (度)
    """
    # 进入方向向量
    v_in = (p_curr[0] - p_prev[0], p_curr[1] - p_prev[1])
    # 离开方向向量
    v_out = (p_next[0] - p_curr[0], p_next[1] - p_curr[1])
    
    # 向量模
    len_in = math.sqrt(v_in[0]**2 + v_in[1]**2)
    len_out = math.sqrt(v_out[0]**2 + v_out[1]**2)
    
    if len_in < 1e-9 or len_out < 1e-9:
        return 0.0
    
    # 点积
    dot = v_in[0] * v_out[0] + v_in[1] * v_out[1]
    
    # cos(θ) = dot / (|v_in| × |v_out|)，θ 是两方向向量的夹角
    cos_theta = dot / (len_in * len_out)
    cos_theta = max(-1.0, min(1.0, cos_theta))  # 防止浮点误差
    
    # 转角（偏角）= 两方向向量的夹角本身
    # 注意：不能用 180° - acos()；该公式仅适用于余弦定理中的"内角"定义。
    # 当 v_in、v_out 同向（直线）时 cos=1，acos=0°，转角=0°（正确）
    # 当 v_in、v_out 垂直（90°弯）时 cos=0，acos=90°，转角=90°（正确）
    angle_rad = math.acos(cos_theta)
    turn_angle = math.degrees(angle_rad)
    
    # 小于0.1°的转角视为坐标噪声/直线通过，返回0以免产生虚假弯头损失
    _MIN_MEANINGFUL_ANGLE = 0.1
    return turn_angle if turn_angle >= _MIN_MEANINGFUL_ANGLE else 0.0


def calc_segment_length(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """
    计算两点之间的距离
    
    Args:
        p1: 点1坐标 (x, y)
        p2: 点2坐标 (x, y)
    
    Returns:
        距离 (m)
    """
    return math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)


# ============================================================
# 5. 总水头损失计算
# ============================================================

@dataclass
class PressurePipeCalcResult:
    """有压管道水头损失计算结果"""
    name: str                           # 管道名称
    Q: float                            # 设计流量 (m³/s)
    D: float                            # 管径 (m)
    material_key: str                   # 管材
    total_length: float                 # 总管长 (m)
    pipe_velocity: float                # 管内流速 (m/s)
    
    # 各项水头损失
    friction_loss: float = 0.0          # 沿程水头损失 (m)
    bend_losses: List[float] = field(default_factory=list)  # 各弯头局部损失列表 (m)
    total_bend_loss: float = 0.0        # 弯头局部损失合计 (m)
    local_loss: float = 0.0             # 通用构件局部损失 (m)
    inlet_transition_loss: float = 0.0  # 进口渐变段损失 (m)
    outlet_transition_loss: float = 0.0 # 出口渐变段损失 (m)
    has_inlet_transition: bool = True   # 进口侧是否存在渐变段
    has_outlet_transition: bool = True  # 出口侧是否存在渐变段
    inlet_transition_reason: str = ""   # 进口侧无渐变段原因
    outlet_transition_reason: str = ""  # 出口侧无渐变段原因
    
    # 总水头损失
    total_head_loss: float = 0.0        # 总水头损失 (m)
    
    # 计算详情
    calc_steps: str = ""                # 计算过程文本
    friction_details: Dict = field(default_factory=dict)
    bend_details: List[Dict] = field(default_factory=list)
    local_details: Dict = field(default_factory=dict)
    inlet_transition_details: Dict = field(default_factory=dict)
    outlet_transition_details: Dict = field(default_factory=dict)

    # 数据模式
    data_mode: str = ""                 # 数据模式（独立计算 / 独立叠加）


def calc_total_head_loss(
    name: str,
    Q: float,
    D: float,
    material_key: str,
    ip_points: List[Dict],
    upstream_velocity: float,
    downstream_velocity: float,
    inlet_transition_form: str = "反弯扭曲面",
    outlet_transition_form: str = "反弯扭曲面",
    inlet_transition_zeta: Optional[float] = None,
    outlet_transition_zeta: Optional[float] = None,
    has_inlet_transition: bool = True,
    has_outlet_transition: bool = True,
    inlet_transition_reason: str = "",
    outlet_transition_reason: str = "",
    common_local_loss: float = 0.0,
    common_local_details: Optional[dict] = None,
) -> PressurePipeCalcResult:
    """
    计算有压管道总水头损失
    
    Args:
        name: 管道名称
        Q: 设计流量 (m³/s)
        D: 管径 (m)
        material_key: 管材键名
        ip_points: IP点列表，每个字典包含 {x, y, turn_radius, turn_angle}
        upstream_velocity: 上游渠道流速 v₁ (m/s)
        downstream_velocity: 下游渠道流速 v₃ (m/s)
        inlet_transition_form: 进口渐变段型式
        outlet_transition_form: 出口渐变段型式
    
    Returns:
        PressurePipeCalcResult 计算结果对象
    """
    result = PressurePipeCalcResult(
        name=name,
        Q=Q,
        D=D,
        material_key=material_key,
        total_length=0.0,
        pipe_velocity=0.0,
        has_inlet_transition=has_inlet_transition,
        has_outlet_transition=has_outlet_transition,
        inlet_transition_reason=inlet_transition_reason,
        outlet_transition_reason=outlet_transition_reason,
    )
    result.data_mode = "仅平面（独立计算）"
    
    steps = []
    steps.append(f"【有压管道水头损失计算】")
    steps.append(f"管道名称: {name}")
    steps.append(f"设计流量 Q = {Q:.4f} m³/s")
    steps.append(f"管径 D = {D:.4f} m")
    steps.append(f"管材: {material_key}")
    steps.append("")
    
    # 1. 管内流速
    V_pipe = calc_pipe_velocity(Q, D)
    result.pipe_velocity = V_pipe
    steps.append(f"1. 管内流速")
    steps.append(f"   V = Q / (π×D²/4) = {Q:.4f} / (π×{D:.4f}²/4) = {V_pipe:.4f} m/s")
    steps.append("")
    
    # 2. 计算总管长（通过IP点坐标）
    total_length = 0.0
    if len(ip_points) >= 2:
        for i in range(len(ip_points) - 1):
            p1 = (ip_points[i].get('x', 0), ip_points[i].get('y', 0))
            p2 = (ip_points[i+1].get('x', 0), ip_points[i+1].get('y', 0))
            seg_len = calc_segment_length(p1, p2)
            total_length += seg_len
    
    result.total_length = total_length
    steps.append(f"2. 管道总长度")
    steps.append(f"   L = {total_length:.2f} m（通过IP点坐标计算）")
    steps.append("")
    
    # 3. 沿程水头损失
    hf, friction_details = calc_friction_loss(Q, D, total_length, material_key)
    result.friction_loss = hf
    result.friction_details = friction_details
    steps.append(f"3. 沿程水头损失（GB 50288-2018 §6.7.2）")
    steps.append(f"   公式: hf = f × L × Q^m / d^b")
    if "error" not in friction_details:
        # Display the configured coefficients as-is to avoid rounding confusion.
        steps.append(f"   f = {friction_details['f']}, m = {friction_details['m']}, b = {friction_details['b']}")
        steps.append(f"   Q = {friction_details['Q_m3h']:.2f} m³/h, d = {friction_details['d_mm']:.0f} mm")
        steps.append(f"   hf = {hf:.4f} m")
    steps.append("")
    
    # 4. 弯头局部水头损失
    steps.append(f"4. 弯头局部水头损失")
    total_bend_loss = 0.0
    bend_losses = []
    bend_details = []
    
    # 中间IP点才有转角
    for i, ip in enumerate(ip_points):
        if i == 0 or i == len(ip_points) - 1:
            continue  # 进出口点无转角
        
        turn_angle = float(ip.get('turn_angle', 0) or 0.0)
        turn_radius = float(ip.get('turn_radius', 0) or 0.0)
        
        # turn_angle >= 180 表示直线通过（无弯折），不计弯头损失
        if 0 < turn_angle < 180 and turn_radius > 0:
            xi, hj, details = calc_bend_local_loss(D, turn_radius, turn_angle, V_pipe)
            bend_losses.append(hj)
            bend_details.append(details)
            total_bend_loss += hj
            steps.append(f"   IP{i}: R={turn_radius:.2f}m, θ={turn_angle:.1f}°, ξ={xi:.4f}, hj={hj:.4f}m")
        elif 0.1 <= turn_angle < 180 and turn_radius <= 0:
            xi, hj, details = _build_fold_loss_details(
                turn_angle_deg=turn_angle,
                V_pipe=V_pipe,
                source="plan",
                point_index=i,
                turn_radius_m=turn_radius,
            )
            bend_losses.append(hj)
            bend_details.append(details)
            total_bend_loss += hj
            steps.append(f"   IP{i}: θ={turn_angle:.1f}°（按折管）, ξ={xi:.4f}, hj={hj:.4f}m")
        else:
            if turn_angle < 0.1:
                steps.append(f"   IP{i}: R={turn_radius:.2f}m, θ={turn_angle:.1f}°（直线通过，不计弯头损失）")
            elif turn_radius <= 0:
                steps.append(f"   IP{i}: θ={turn_angle:.1f}°，未设转弯半径（不计弯头损失）")
    
    result.bend_losses = bend_losses
    result.total_bend_loss = total_bend_loss
    result.bend_details = bend_details
    steps.append(f"   弯头局部损失合计: Σhj_弯 = {total_bend_loss:.4f} m")
    steps.append("")

    # 4.2 通用构件局部损失
    common_local_loss_value = float(common_local_loss or 0.0)
    result.local_loss = common_local_loss_value
    result.local_details = _build_common_local_details(common_local_loss_value, common_local_details)
    steps.append(f"   通用构件局部损失: hj_通用 = {common_local_loss_value:.4f} m")
    steps.append("")
    
    # 5. 进口渐变段损失
    steps.append(f"5. 进口渐变段水头损失")
    inlet_zeta = _resolve_transition_zeta(inlet_transition_form, inlet_transition_zeta, is_inlet=True)
    if has_inlet_transition:
        hj_inlet, inlet_details = calc_transition_loss(V_pipe, upstream_velocity, inlet_zeta, is_inlet=True)
    else:
        hj_inlet = 0.0
        inlet_details = _build_skipped_transition_details(
            V_pipe=V_pipe,
            V_channel=upstream_velocity,
            zeta=inlet_zeta,
            form=inlet_transition_form,
            is_inlet=True,
            reason=inlet_transition_reason,
        )
    result.inlet_transition_loss = hj_inlet
    result.inlet_transition_details = inlet_details
    steps.append(f"   型式: {inlet_transition_form}, ζ₁ = {inlet_zeta:.2f}")
    if has_inlet_transition:
        steps.append(f"   V_渠道 = {upstream_velocity:.4f} m/s, V_管道 = {V_pipe:.4f} m/s")
        steps.append(f"   hj₁ = ζ₁ × (V²_管道 - V²_渠道) / (2g) = {hj_inlet:.4f} m")
    else:
        steps.append(f"   该侧{inlet_transition_reason or '无渐变段'}，hj=0")
        steps.append(f"   hj₁ = {hj_inlet:.4f} m")
    steps.append("")
    
    # 6. 出口渐变段损失
    steps.append(f"6. 出口渐变段水头损失")
    outlet_zeta = _resolve_transition_zeta(outlet_transition_form, outlet_transition_zeta, is_inlet=False)
    if has_outlet_transition:
        hj_outlet, outlet_details = calc_transition_loss(V_pipe, downstream_velocity, outlet_zeta, is_inlet=False)
    else:
        hj_outlet = 0.0
        outlet_details = _build_skipped_transition_details(
            V_pipe=V_pipe,
            V_channel=downstream_velocity,
            zeta=outlet_zeta,
            form=outlet_transition_form,
            is_inlet=False,
            reason=outlet_transition_reason,
        )
    result.outlet_transition_loss = hj_outlet
    result.outlet_transition_details = outlet_details
    steps.append(f"   型式: {outlet_transition_form}, ζ₃ = {outlet_zeta:.2f}")
    if has_outlet_transition:
        steps.append(f"   V_管道 = {V_pipe:.4f} m/s, V_渠道 = {downstream_velocity:.4f} m/s")
        steps.append(f"   hj₃ = ζ₃ × (V²_渠道 - V²_管道) / (2g) = {hj_outlet:.4f} m")
    else:
        steps.append(f"   该侧{outlet_transition_reason or '无渐变段'}，hj=0")
        steps.append(f"   hj₃ = {hj_outlet:.4f} m")
    steps.append("")
    
    # 7. 总水头损失
    total = hf + total_bend_loss + common_local_loss_value + hj_inlet + hj_outlet
    result.total_head_loss = total
    steps.append(f"7. 总水头损失")
    steps.append(f"   ΔH = hf + Σhj_弯 + hj_通用 + hj₁ + hj₃")
    steps.append(f"      = {hf:.4f} + {total_bend_loss:.4f} + {common_local_loss_value:.4f} + {hj_inlet:.4f} + {hj_outlet:.4f}")
    steps.append(f"      = {total:.4f} m")
    
    result.calc_steps = "\n".join(steps)
    return result


# ============================================================
# 7. 独立叠加模式计算
# ============================================================

# 导入倒虹吸兼容模型和系数表；保留历史兼容对象，不在本计算入口调用三维空间合并。
import sys
import os
_siphon_dir = os.path.join(os.path.dirname(__file__), '..', '..', '倒虹吸水力计算系统')
if _siphon_dir not in sys.path:
    sys.path.insert(0, _siphon_dir)

try:
    from siphon_models import PlanFeaturePoint, LongitudinalNode, TurnType
    from siphon_coefficients import CoefficientService
    SPATIAL_AVAILABLE = True
except ImportError:
    SPATIAL_AVAILABLE = False


def _convert_ip_points_to_plan_features(ip_points: List[Dict]) -> List[PlanFeaturePoint]:
    """
    将ip_points转换为PlanFeaturePoint列表

    Args:
        ip_points: IP点列表 [{x, y, turn_radius, turn_angle}, ...]

    Returns:
        PlanFeaturePoint对象列表
    """
    if not ip_points:
        return []

    plan_points = []
    cumulative_chainage = 0.0

    for i, ip in enumerate(ip_points):
        x = ip.get('x', 0.0)
        y = ip.get('y', 0.0)
        turn_radius = ip.get('turn_radius', 0.0)
        turn_angle = ip.get('turn_angle', 0.0)

        # 计算累计桩号（通过IP点间距离）
        if i > 0:
            prev_x = ip_points[i-1].get('x', 0.0)
            prev_y = ip_points[i-1].get('y', 0.0)
            dx = x - prev_x
            dy = y - prev_y
            dist = math.sqrt(dx*dx + dy*dy)
            cumulative_chainage += dist

        # 计算方位角（通过相邻IP点坐标）
        azimuth_meas_deg = 0.0
        if i < len(ip_points) - 1:
            next_x = ip_points[i+1].get('x', 0.0)
            next_y = ip_points[i+1].get('y', 0.0)
            dx = next_x - x
            dy = next_y - y
            if abs(dx) > 1e-9 or abs(dy) > 1e-9:
                # 数学方位角（正东=0°逆时针）
                azimuth_math = math.atan2(dy, dx) * 180.0 / math.pi
                # 转换为测量方位角（正北=0°顺时针）
                azimuth_meas_deg = 90.0 - azimuth_math
                if azimuth_meas_deg < 0:
                    azimuth_meas_deg += 360.0
        elif i > 0:
            # 最后一个点使用前一段的方位角
            prev_x = ip_points[i-1].get('x', 0.0)
            prev_y = ip_points[i-1].get('y', 0.0)
            dx = x - prev_x
            dy = y - prev_y
            if abs(dx) > 1e-9 or abs(dy) > 1e-9:
                azimuth_math = math.atan2(dy, dx) * 180.0 / math.pi
                azimuth_meas_deg = 90.0 - azimuth_math
                if azimuth_meas_deg < 0:
                    azimuth_meas_deg += 360.0

        # 判断转弯类型
        turn_type = TurnType.NONE
        if turn_angle > 0.1 and turn_radius > 0:
            turn_type = TurnType.ARC

        plan_points.append(PlanFeaturePoint(
            chainage=cumulative_chainage,
            x=x,
            y=y,
            azimuth_meas_deg=azimuth_meas_deg,
            turn_radius=turn_radius,
            turn_angle=turn_angle,
            turn_type=turn_type,
            ip_index=i
        ))

    return plan_points


def _convert_long_nodes_dict_to_objects(long_nodes: List[Dict]) -> List[LongitudinalNode]:
    """
    将字典列表转换为LongitudinalNode对象列表

    Args:
        long_nodes: 纵断面节点字典列表

    Returns:
        LongitudinalNode对象列表
    """
    if not long_nodes:
        return []

    result = []
    for node_dict in long_nodes:
        # 转换turn_type字符串为枚举
        turn_type_str = node_dict.get('turn_type', 'NONE')
        if isinstance(turn_type_str, str):
            if turn_type_str == 'ARC' or turn_type_str == '圆弧':
                turn_type = TurnType.ARC
            elif turn_type_str == 'FOLD' or turn_type_str == '折线':
                turn_type = TurnType.FOLD
            else:
                turn_type = TurnType.NONE
        else:
            turn_type = turn_type_str  # 已经是枚举类型

        result.append(LongitudinalNode(
            chainage=node_dict.get('chainage', 0.0),
            elevation=node_dict.get('elevation', 0.0),
            vertical_curve_radius=node_dict.get('vertical_curve_radius', 0.0),
            turn_type=turn_type,
            turn_angle=node_dict.get('turn_angle', 0.0),
            slope_before=node_dict.get('slope_before', 0.0),
            slope_after=node_dict.get('slope_after', 0.0),
            arc_center_s=node_dict.get('arc_center_s'),
            arc_center_z=node_dict.get('arc_center_z'),
            arc_end_chainage=node_dict.get('arc_end_chainage'),
            arc_theta_rad=node_dict.get('arc_theta_rad'),
        ))

    return result


def _calc_plan_path_length(ip_points: List[Dict]) -> float:
    """计算平面点坐标长度。"""
    total_length = 0.0
    if len(ip_points) < 2:
        return total_length

    for index in range(len(ip_points) - 1):
        start = ip_points[index]
        end = ip_points[index + 1]
        total_length += calc_segment_length(
            (start.get("x", 0.0), start.get("y", 0.0)),
            (end.get("x", 0.0), end.get("y", 0.0)),
        )
    return total_length


def _calc_longitudinal_actual_length(longitudinal_nodes: List[Dict]) -> float:
    """计算纵断面实长。"""
    total_length = 0.0
    if len(longitudinal_nodes) < 2:
        return total_length

    for index in range(len(longitudinal_nodes) - 1):
        start = longitudinal_nodes[index]
        end = longitudinal_nodes[index + 1]
        segment_length = _calc_longitudinal_segment_length(start, end)
        if segment_length > 0:
            total_length += segment_length
    return total_length


def _to_float(value, default: float = 0.0) -> float:
    """将输入安全转换为浮点数。"""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _score_longitudinal_node(node: Dict) -> int:
    """为重复桩号节点打分，优先保留几何信息更完整的节点。"""
    score = 0
    turn_type = _normalize_longitudinal_turn_type(node.get("turn_type"))
    if turn_type == "ARC":
        score += 4
    elif turn_type == "FOLD":
        score += 3
    if abs(_to_float(node.get("arc_theta_rad"))) > 1e-9:
        score += 2
    if _to_float(node.get("vertical_curve_radius")) > 0:
        score += 1
    if abs(_to_float(node.get("turn_angle"))) >= 0.1:
        score += 1
    return score


def _normalize_longitudinal_nodes_for_calc(longitudinal_nodes: List[Dict]) -> List[Dict]:
    """按桩号排序并折叠重复桩号节点，避免零长度段放大或清零总长。"""
    if not longitudinal_nodes:
        return []

    ordered_nodes = sorted(
        (dict(node) for node in longitudinal_nodes),
        key=lambda node: (_to_float(node.get("chainage")), _to_float(node.get("elevation"))),
    )

    normalized_nodes: List[Dict] = []
    for node in ordered_nodes:
        if not normalized_nodes:
            normalized_nodes.append(node)
            continue

        prev_node = normalized_nodes[-1]
        if abs(_to_float(node.get("chainage")) - _to_float(prev_node.get("chainage"))) <= 1e-9:
            if _score_longitudinal_node(node) > _score_longitudinal_node(prev_node):
                normalized_nodes[-1] = node
            continue

        normalized_nodes.append(node)

    return normalized_nodes


def _calc_longitudinal_segment_length(start: Dict, end: Dict) -> float:
    """计算纵断面相邻节点之间的有效实长。"""
    start_chainage = _to_float(start.get("chainage"))
    end_chainage = _to_float(end.get("chainage"))
    ds = end_chainage - start_chainage
    if ds <= 1e-9:
        return 0.0

    turn_type = _normalize_longitudinal_turn_type(start.get("turn_type"))
    curve_radius = _to_float(start.get("vertical_curve_radius"))
    if turn_type == "ARC" and curve_radius > 0:
        arc_theta_raw = start.get("arc_theta_rad")
        arc_theta_rad = _to_float(arc_theta_raw)
        if arc_theta_raw is not None and abs(arc_theta_rad) > 1e-9:
            return abs(curve_radius * arc_theta_rad)

        arc_end_chainage_raw = start.get("arc_end_chainage")
        turn_angle_deg = _to_float(start.get("turn_angle"))
        if (
            arc_end_chainage_raw is not None
            and _to_float(arc_end_chainage_raw) - start_chainage > 1e-9
            and abs(turn_angle_deg) > 1e-9
        ):
            return abs(curve_radius * math.radians(turn_angle_deg))

    dz = _to_float(end.get("elevation")) - _to_float(start.get("elevation"))
    return math.hypot(ds, dz)


def _normalize_longitudinal_turn_type(turn_type_value) -> str:
    """将纵断面转角类型归一化为字符串。"""
    if turn_type_value is None:
        return "NONE"

    raw_value = str(turn_type_value)
    if hasattr(turn_type_value, "value"):
        raw_value = str(turn_type_value.value)

    normalized = raw_value.strip().upper()
    if normalized == "圆弧":
        return "ARC"
    if normalized == "折线":
        return "FOLD"
    if normalized == "NONE":
        return "NONE"
    return normalized


def _calc_plan_local_losses(
    D: float,
    ip_points: List[Dict],
    V_pipe: float,
) -> Tuple[List[float], List[Dict], float]:
    """按现有平面 IP 点口径计算平面局部损失。"""
    losses: List[float] = []
    details: List[Dict] = []
    total_loss = 0.0

    for index, ip in enumerate(ip_points):
        if index == 0 or index == len(ip_points) - 1:
            continue

        turn_angle = float(ip.get("turn_angle", 0.0) or 0.0)
        turn_radius = float(ip.get("turn_radius", 0.0) or 0.0)
        if 0 < turn_angle < 180 and turn_radius > 0:
            xi, hj, bend_details = calc_bend_local_loss(D, turn_radius, turn_angle, V_pipe)
            bend_details["source"] = "plan"
            bend_details["point_index"] = index
            losses.append(hj)
            details.append(bend_details)
            total_loss += hj
        elif 0.1 <= turn_angle < 180 and turn_radius <= 0:
            xi, hj, fold_details = _build_fold_loss_details(
                turn_angle_deg=turn_angle,
                V_pipe=V_pipe,
                source="plan",
                point_index=index,
                turn_radius_m=turn_radius,
            )
            losses.append(hj)
            details.append(fold_details)
            total_loss += hj

    return losses, details, total_loss


def _calc_fold_xi(angle_deg: float) -> float:
    """计算折管局部损失系数。"""
    if CoefficientService:
        xi_value = CoefficientService.calculate_fold_coeff(angle_deg, verbose=False)
        if isinstance(xi_value, tuple):
            return float(xi_value[0])
        return float(xi_value)

    half_angle_rad = math.radians(angle_deg) / 2
    sin_half = math.sin(half_angle_rad)
    return 0.9457 * sin_half ** 2 + 2.047 * sin_half ** 4


def calc_fold_local_loss(turn_angle_deg: float, V_pipe: float) -> Tuple[float, float, Dict]:
    """按折管公式计算局部损失。"""
    turn_angle_deg = float(turn_angle_deg or 0.0)
    V_pipe = float(V_pipe or 0.0)
    details = {
        "formula": "ξ = 0.9457 × sin²(θ/2) + 2.047 × sin⁴(θ/2), hj = ξ × V² / (2g)",
        "turn_type": "FOLD",
        "turn_angle_deg": turn_angle_deg,
        "V_m_s": V_pipe,
    }
    if turn_angle_deg < 0.1 or turn_angle_deg >= 180:
        details.update({
            "xi_bend": 0.0,
            "hj": 0.0,
            "error": "转角不在折管局部损失有效范围内",
        })
        return 0.0, 0.0, details

    xi = _calc_fold_xi(turn_angle_deg)
    hj = xi * V_pipe ** 2 / (2 * GRAVITY)
    details.update({
        "xi_bend": xi,
        "hj": hj,
    })
    return xi, hj, details


def _build_fold_loss_details(
    *,
    turn_angle_deg: float,
    V_pipe: float,
    source: str,
    point_index: Optional[int] = None,
    node_index: Optional[int] = None,
    node_chainage: Optional[float] = None,
    turn_radius_m: Optional[float] = None,
) -> Tuple[float, float, Dict]:
    """按折管公式构造局部损失详情。"""
    xi, hj, details = calc_fold_local_loss(turn_angle_deg, V_pipe)
    details["source"] = source
    if point_index is not None:
        details["point_index"] = point_index
    if node_index is not None:
        details["node_index"] = node_index
    if node_chainage is not None:
        details["node_chainage"] = node_chainage
    if turn_radius_m is not None:
        details["turn_radius_m"] = turn_radius_m
    return xi, hj, details


def _build_common_local_details(common_local_loss: float, common_local_details: Optional[dict]) -> Dict:
    """构造通用构件局部损失详情。"""
    if isinstance(common_local_details, dict):
        return dict(common_local_details)
    if abs(common_local_loss) > 1e-12:
        return {"hj": common_local_loss}
    return {}


def _calc_longitudinal_local_losses(
    D: float,
    longitudinal_nodes: List[Dict],
    V_pipe: float,
) -> Tuple[List[float], List[Dict], float]:
    """按纵断面节点独立计算竖向局部损失。"""
    losses: List[float] = []
    details: List[Dict] = []
    total_loss = 0.0

    for index, node in enumerate(longitudinal_nodes):
        turn_angle = float(node.get("turn_angle", 0.0) or 0.0)
        if turn_angle < 0.1 or turn_angle >= 180:
            continue

        turn_type = _normalize_longitudinal_turn_type(node.get("turn_type"))
        chainage = float(node.get("chainage", 0.0) or 0.0)

        if turn_type == "ARC":
            curve_radius = float(node.get("vertical_curve_radius", 0.0) or 0.0)
            if curve_radius <= 0:
                continue
            xi, hj, bend_details = calc_bend_local_loss(D, curve_radius, turn_angle, V_pipe)
            bend_details["source"] = "longitudinal"
            bend_details["node_index"] = index
            bend_details["node_chainage"] = chainage
            bend_details["turn_type"] = "ARC"
            bend_details["vertical_curve_radius"] = curve_radius
        elif turn_type == "FOLD":
            xi, hj, bend_details = _build_fold_loss_details(
                turn_angle_deg=turn_angle,
                V_pipe=V_pipe,
                source="longitudinal",
                node_index=index,
                node_chainage=chainage,
            )
        else:
            continue

        losses.append(hj)
        details.append(bend_details)
        total_loss += hj

    return losses, details, total_loss


def calc_total_head_loss_with_spatial(
    name: str,
    Q: float,
    D: float,
    material_key: str,
    ip_points: List[Dict],
    longitudinal_nodes: List[Dict],
    upstream_velocity: float,
    downstream_velocity: float,
    inlet_transition_form: str = "反弯扭曲面",
    outlet_transition_form: str = "反弯扭曲面",
    inlet_transition_zeta: Optional[float] = None,
    outlet_transition_zeta: Optional[float] = None,
    has_inlet_transition: bool = True,
    has_outlet_transition: bool = True,
    inlet_transition_reason: str = "",
    outlet_transition_reason: str = "",
    common_local_loss: float = 0.0,
    common_local_details: Optional[dict] = None,
) -> PressurePipeCalcResult:
    """
    旧接口名，新独立叠加口径的有压管道总水头损失计算。

    Args:
        name: 管道名称
        Q: 设计流量 (m³/s)
        D: 管径 (m)
        material_key: 管材键名
        ip_points: IP点列表，每个字典包含 {x, y, turn_radius, turn_angle}
        longitudinal_nodes: 纵断面节点列表（字典格式）
        upstream_velocity: 上游渠道流速 v₁ (m/s)
        downstream_velocity: 下游渠道流速 v₃ (m/s)
        inlet_transition_form: 进口渐变段型式
        outlet_transition_form: 出口渐变段型式

    Returns:
        PressurePipeCalcResult 计算结果对象
    """
    result = PressurePipeCalcResult(
        name=name,
        Q=Q,
        D=D,
        material_key=material_key,
        total_length=0.0,
        pipe_velocity=0.0,
        has_inlet_transition=has_inlet_transition,
        has_outlet_transition=has_outlet_transition,
        inlet_transition_reason=inlet_transition_reason,
        outlet_transition_reason=outlet_transition_reason,
    )

    steps = []
    steps.append(f"【有压管道水头损失计算】")
    steps.append(f"管道名称: {name}")
    steps.append(f"设计流量 Q = {Q:.4f} m³/s")
    steps.append(f"管径 D = {D:.4f} m")
    steps.append(f"管材: {material_key}")
    steps.append("")

    # 1. 管内流速
    V_pipe = calc_pipe_velocity(Q, D)
    result.pipe_velocity = V_pipe
    steps.append(f"1. 管内流速")
    steps.append(f"   V = Q / (π×D²/4) = {Q:.4f} / (π×{D:.4f}²/4) = {V_pipe:.4f} m/s")
    steps.append("")

    # 2. 判断数据模式与沿程长度来源
    normalized_longitudinal_nodes = _normalize_longitudinal_nodes_for_calc(longitudinal_nodes)
    has_long_nodes = bool(longitudinal_nodes) and len(longitudinal_nodes) > 0
    has_plan_points = bool(ip_points) and len(ip_points) >= 2
    longitudinal_length = _calc_longitudinal_actual_length(normalized_longitudinal_nodes)
    has_valid_longitudinal_length = len(normalized_longitudinal_nodes) >= 2 and longitudinal_length > 0

    if has_plan_points and has_long_nodes:
        result.data_mode = "平面+纵断面（独立叠加）"
        if has_valid_longitudinal_length:
            friction_length = longitudinal_length
            length_source = "纵断面实长"
        else:
            friction_length = _calc_plan_path_length(ip_points)
            length_source = "平面点坐标长度（纵断面无有效实长，已回退）"
    elif has_plan_points:
        result.data_mode = "仅平面（独立计算）"
        friction_length = _calc_plan_path_length(ip_points)
        length_source = "平面点坐标长度"
    elif has_long_nodes:
        result.data_mode = "仅纵断面（独立计算）"
        if has_valid_longitudinal_length:
            friction_length = longitudinal_length
            length_source = "纵断面实长"
        else:
            friction_length = 0.0
            length_source = "无有效纵断面长度数据"
    else:
        result.data_mode = "无有效线形数据"
        friction_length = 0.0
        length_source = "无有效长度数据"

    result.total_length = friction_length
    steps.append(f"【数据模式：{result.data_mode}】")
    steps.append("   未采用三维空间合并，平面弯头与纵断面转角按各自数据独立计算。")
    steps.append("")
    steps.append(f"2. 管道总长度")
    steps.append(f"   沿程长度来源：{length_source}")
    steps.append(f"   L = {friction_length:.2f} m")
    steps.append("")

    # 3. 沿程水头损失
    hf, friction_details = calc_friction_loss(Q, D, friction_length, material_key)
    result.friction_loss = hf
    result.friction_details = friction_details
    steps.append(f"3. 沿程水头损失（GB 50288-2018 §6.7.2）")
    steps.append(f"   公式: hf = f × L × Q^m / d^b")
    if "error" not in friction_details:
        steps.append(f"   f = {friction_details['f']}, m = {friction_details['m']}, b = {friction_details['b']}")
        steps.append(f"   Q = {friction_details['Q_m3h']:.2f} m³/h, d = {friction_details['d_mm']:.0f} mm")
        steps.append(f"   hf = {hf:.4f} m")
    steps.append("")

    # 4. 局部损失（平面与纵断面独立叠加）
    plan_losses, plan_details, total_plan_loss = _calc_plan_local_losses(D, ip_points, V_pipe)
    long_losses, long_details, total_longitudinal_loss = _calc_longitudinal_local_losses(D, normalized_longitudinal_nodes, V_pipe)
    total_bend_loss = total_plan_loss + total_longitudinal_loss

    result.bend_losses = plan_losses + long_losses
    result.bend_details = plan_details + long_details
    result.total_bend_loss = total_bend_loss

    steps.append(f"4. 局部水头损失（独立叠加）")
    steps.append(f"   4.1 平面弯头局部水头损失")
    if plan_details:
        for detail in plan_details:
            steps.append(
                f"   IP{detail['point_index']}: R={detail['turn_radius_m']:.2f}m, "
                f"θ={detail['turn_angle_deg']:.1f}°, ξ={detail['xi_bend']:.4f}, hj={detail['hj']:.4f}m"
            )
    steps.append(f"   平面局部损失合计: {total_plan_loss:.4f} m")
    steps.append(f"   4.2 纵断面局部水头损失")
    if long_details:
        for detail in long_details:
            if detail["turn_type"] == "ARC":
                steps.append(
                    f"   桩号{detail['node_chainage']:.2f}m 圆弧竖向弯管: "
                    f"R={detail['vertical_curve_radius']:.2f}m, "
                    f"θ={detail['turn_angle_deg']:.1f}°, ξ={detail['xi_bend']:.4f}, hj={detail['hj']:.4f}m"
                )
            else:
                steps.append(
                    f"   桩号{detail['node_chainage']:.2f}m 纵断面折管: "
                    f"θ={detail['turn_angle_deg']:.1f}°, ξ={detail['xi_bend']:.4f}, hj={detail['hj']:.4f}m"
                )
    steps.append(f"   纵断面局部损失合计: {total_longitudinal_loss:.4f} m")
    steps.append(f"   局部损失合计: {total_bend_loss:.4f} m")
    steps.append("")

    # 4.3 通用构件局部损失
    common_local_loss_value = float(common_local_loss or 0.0)
    result.local_loss = common_local_loss_value
    result.local_details = _build_common_local_details(common_local_loss_value, common_local_details)
    steps.append(f"   4.3 通用构件局部损失")
    steps.append(f"   hj_通用 = {common_local_loss_value:.4f} m")
    steps.append("")

    # 5. 进口渐变段损失
    steps.append(f"5. 进口渐变段水头损失")
    inlet_zeta = _resolve_transition_zeta(inlet_transition_form, inlet_transition_zeta, is_inlet=True)
    if has_inlet_transition:
        hj_inlet, inlet_details = calc_transition_loss(V_pipe, upstream_velocity, inlet_zeta, is_inlet=True)
    else:
        hj_inlet = 0.0
        inlet_details = _build_skipped_transition_details(
            V_pipe=V_pipe,
            V_channel=upstream_velocity,
            zeta=inlet_zeta,
            form=inlet_transition_form,
            is_inlet=True,
            reason=inlet_transition_reason,
        )
    result.inlet_transition_loss = hj_inlet
    result.inlet_transition_details = inlet_details
    steps.append(f"   型式: {inlet_transition_form}, ζ₁ = {inlet_zeta:.2f}")
    if has_inlet_transition:
        steps.append(f"   V_渠道 = {upstream_velocity:.4f} m/s, V_管道 = {V_pipe:.4f} m/s")
        steps.append(f"   hj₁ = ζ₁ × (V²_管道 - V²_渠道) / (2g) = {hj_inlet:.4f} m")
    else:
        steps.append(f"   该侧{inlet_transition_reason or '无渐变段'}，hj=0")
        steps.append(f"   hj₁ = {hj_inlet:.4f} m")
    steps.append("")

    # 6. 出口渐变段损失
    steps.append(f"6. 出口渐变段水头损失")
    outlet_zeta = _resolve_transition_zeta(outlet_transition_form, outlet_transition_zeta, is_inlet=False)
    if has_outlet_transition:
        hj_outlet, outlet_details = calc_transition_loss(V_pipe, downstream_velocity, outlet_zeta, is_inlet=False)
    else:
        hj_outlet = 0.0
        outlet_details = _build_skipped_transition_details(
            V_pipe=V_pipe,
            V_channel=downstream_velocity,
            zeta=outlet_zeta,
            form=outlet_transition_form,
            is_inlet=False,
            reason=outlet_transition_reason,
        )
    result.outlet_transition_loss = hj_outlet
    result.outlet_transition_details = outlet_details
    steps.append(f"   型式: {outlet_transition_form}, ζ₃ = {outlet_zeta:.2f}")
    if has_outlet_transition:
        steps.append(f"   V_管道 = {V_pipe:.4f} m/s, V_渠道 = {downstream_velocity:.4f} m/s")
        steps.append(f"   hj₃ = ζ₃ × (V²_渠道 - V²_管道) / (2g) = {hj_outlet:.4f} m")
    else:
        steps.append(f"   该侧{outlet_transition_reason or '无渐变段'}，hj=0")
        steps.append(f"   hj₃ = {hj_outlet:.4f} m")
    steps.append("")

    # 7. 总水头损失
    total = hf + total_bend_loss + common_local_loss_value + hj_inlet + hj_outlet
    result.total_head_loss = total
    steps.append(f"7. 总水头损失")
    steps.append(f"   ΔH = hf + Σhj_弯 + hj_通用 + hj₁ + hj₃")
    steps.append(f"      = {hf:.4f} + {total_bend_loss:.4f} + {common_local_loss_value:.4f} + {hj_inlet:.4f} + {hj_outlet:.4f}")
    steps.append(f"      = {total:.4f} m")

    result.calc_steps = "\n".join(steps)
    return result


# ============================================================
# 6. 测试代码
# ============================================================

if __name__ == "__main__":
    # 测试沿程损失计算
    print("=== 沿程损失计算测试 ===")
    hf, details = calc_friction_loss(
        Q_m3s=2.0,
        D_m=1.0,
        L_m=1000.0,
        material_key="预应力钢筒混凝土管"
    )
    print(f"沿程损失: {hf:.4f} m")
    print(f"详情: {details}")
    
    # 测试弯头损失计算
    print("\n=== 弯头损失计算测试 ===")
    xi, hj, details = calc_bend_local_loss(
        D_m=1.0,
        turn_radius_m=3.0,
        turn_angle_deg=45.0,
        V_m_s=2.5
    )
    print(f"弯头系数: {xi:.4f}")
    print(f"弯头损失: {hj:.4f} m")
    
    # 测试总水头损失计算
    print("\n=== 总水头损失计算测试 ===")
    ip_points = [
        {"x": 0, "y": 0, "turn_radius": 0, "turn_angle": 0},      # 进口
        {"x": 100, "y": 0, "turn_radius": 3.0, "turn_angle": 45}, # IP1
        {"x": 200, "y": 100, "turn_radius": 3.0, "turn_angle": 30}, # IP2
        {"x": 300, "y": 100, "turn_radius": 0, "turn_angle": 0},  # 出口
    ]
    result = calc_total_head_loss(
        name="测试管道",
        Q=2.0,
        D=1.0,
        material_key="预应力钢筒混凝土管",
        ip_points=ip_points,
        upstream_velocity=1.0,
        downstream_velocity=1.0,
    )
    print(result.calc_steps)
    print(f"\n总水头损失: {result.total_head_loss:.4f} m")
