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

# 水的体积弹性模量（按 10℃ 固定取值）
WATER_BULK_MODULUS = 2.025e9

# 基础水锤验算默认弹性模量（来自手册常见材质近似值）
WATER_HAMMER_ELASTIC_MODULUS = {
    "钢管": 206.0e9,
    "钢": 206.0e9,
    "球墨铸铁管": 108.0e9,
    "铸铁管": 108.0e9,
    "铸铁": 108.0e9,
    "预应力钢筒混凝土管": 20.6e9,
    "预应力钢筒混凝土管_n014": 20.6e9,
    "钢筋混凝土管": 20.6e9,
    "钢筋混凝土": 20.6e9,
    "玻璃钢夹砂管": 20.6e9,
    "HDPE管": 1.4e9,
    "PE": 1.4e9,
    "PE管": 1.4e9,
    "聚乙烯": 1.4e9,
    "PVC": 0.8e9,
    "PVC管": 0.8e9,
    "聚氯乙烯": 0.8e9,
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


def get_water_hammer_elastic_modulus(material_key: str) -> Optional[float]:
    """返回基础水锤验算的默认管材弹性模量。"""
    key = str(material_key or "").strip()
    if not key:
        return None
    return WATER_HAMMER_ELASTIC_MODULUS.get(key)


def calc_basic_water_hammer(
    *,
    length_m: float,
    diameter_m: float,
    wall_thickness_m: float,
    elastic_modulus_pa: float,
    velocity_mps: float,
    initial_head_m: Optional[float],
    closing_time_s: float,
    water_bulk_modulus_pa: float = WATER_BULK_MODULUS,
) -> Dict[str, object]:
    """计算基础直接关阀水锤，只覆盖全关场景。"""
    inputs = {
        "length_m": float(length_m or 0.0),
        "diameter_m": float(diameter_m or 0.0),
        "wall_thickness_m": float(wall_thickness_m or 0.0),
        "elastic_modulus_pa": float(elastic_modulus_pa or 0.0),
        "velocity_mps": float(velocity_mps or 0.0),
        "initial_head_m": None if initial_head_m is None else float(initial_head_m),
        "closing_time_s": float(closing_time_s or 0.0),
        "water_bulk_modulus_pa": float(water_bulk_modulus_pa or 0.0),
    }
    result: Dict[str, object] = {
        "status": "输入缺失",
        "reason": "",
        "a": None,
        "mu": None,
        "ts_to_mu_ratio": None,
        "delta_h": None,
        "hmax": None,
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
    if inputs["initial_head_m"] is None:
        missing_items.append("Hc")
    if inputs["closing_time_s"] <= 0:
        missing_items.append("关阀时间 Ts")
    if inputs["water_bulk_modulus_pa"] <= 0:
        missing_items.append("体积弹性模量 K")
    if missing_items:
        result["reason"] = f"缺少必要输入：{'、'.join(missing_items)}"
        return result

    denominator = 1.0 + (inputs["water_bulk_modulus_pa"] / inputs["elastic_modulus_pa"]) * (
        inputs["diameter_m"] / inputs["wall_thickness_m"]
    )
    if denominator <= 0:
        result["reason"] = "输入组合无效，无法计算水锤波速"
        return result

    a = 1425.0 / math.sqrt(denominator)
    mu = 2.0 * inputs["length_m"] / a if a > 0 else 0.0
    ts_ratio = inputs["closing_time_s"] / mu if mu > 0 else None
    steps = [
        f"a = 1425 / sqrt(1 + (K/E) * (d/e)) = {a:.6f} m/s",
        f"μ = 2L / a = {mu:.6f} s",
    ]

    result["a"] = a
    result["mu"] = mu
    result["ts_to_mu_ratio"] = ts_ratio

    if mu <= 0:
        result["reason"] = "水锤相时 μ 无效，无法继续验算"
        result["calc_steps"] = "\n".join(steps)
        return result

    if inputs["closing_time_s"] > mu:
        result["status"] = "不适用"
        result["reason"] = (
            f"当前仅支持直接关阀水锤（Ts <= μ）。当前 Ts = {inputs['closing_time_s']:.6f} s，"
            f"μ = {mu:.6f} s。"
        )
        steps.append("Ts > μ，本版不输出 ΔH 与 Hmax。")
        result["calc_steps"] = "\n".join(steps)
        return result

    delta_h = a * inputs["velocity_mps"] / GRAVITY
    hmax = float(inputs["initial_head_m"]) + delta_h
    steps.append(f"ΔH = a * v0 / g = {delta_h:.6f} m")
    steps.append(f"Hmax = Hc + ΔH = {hmax:.6f} m")

    result["status"] = "可计算"
    result["delta_h"] = delta_h
    result["hmax"] = hmax
    result["calc_steps"] = "\n".join(steps)
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
    xi = _calc_fold_xi(turn_angle_deg)
    hj = xi * V_pipe ** 2 / (2 * GRAVITY)
    details = {
        "formula": "ξ = 0.9457 × sin²(θ/2) + 2.047 × sin⁴(θ/2), hj = ξ × V² / (2g)",
        "source": source,
        "turn_type": "FOLD",
        "turn_angle_deg": turn_angle_deg,
        "xi_bend": xi,
        "V_m_s": V_pipe,
        "hj": hj,
    }
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
