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
    "HDPE管":           {"f": 0.948e5, "m": 1.77, "b": 4.77, "name": "HDPE管"},
    "玻璃钢夹砂管":     {"f": 0.948e5, "m": 1.77, "b": 4.77, "name": "玻璃钢夹砂管"},
    "球墨铸铁管":       {"f": 2.232e5, "m": 1.852, "b": 4.87, "name": "球墨铸铁管"},
    "预应力钢筒混凝土管": {"f": 1.312e6, "m": 2.0,  "b": 5.33, "name": "预应力钢筒混凝土管(n=0.013)"},
    "预应力钢筒混凝土管_n014": {"f": 1.516e6, "m": 2.0, "b": 5.33, "name": "预应力钢筒混凝土管(n=0.014)"},
    "钢管":             {"f": 6.25e5,  "m": 1.9,  "b": 5.1,  "name": "钢管"},
}

# ============================================================
# 2. 渐变段型式与ζ值（表L.1.2）
# ============================================================

TRANSITION_FORMS = {
    "反弯扭曲面":   {"inlet_zeta": 0.10, "outlet_zeta": 0.20},
    "直线扭曲面":   {"inlet_zeta": 0.20, "outlet_zeta": 0.30},
    "1/4圆弧":      {"inlet_zeta": 0.25, "outlet_zeta": 0.35},
    "方头型":       {"inlet_zeta": 0.30, "outlet_zeta": 0.75},
}

# 重力加速度
GRAVITY = 9.81


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
    if D_m <= 0 or turn_radius_m <= 0 or turn_angle_deg <= 0:
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
    
    # cos(θ) = dot / (|v_in| × |v_out|)
    cos_theta = dot / (len_in * len_out)
    cos_theta = max(-1.0, min(1.0, cos_theta))  # 防止浮点误差
    
    # 转角 = 180° - 夹角（因为转角是方向改变量）
    angle_rad = math.acos(cos_theta)
    turn_angle = 180.0 - math.degrees(angle_rad)
    
    return abs(turn_angle)


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
    inlet_transition_loss: float = 0.0  # 进口渐变段损失 (m)
    outlet_transition_loss: float = 0.0 # 出口渐变段损失 (m)
    
    # 总水头损失
    total_head_loss: float = 0.0        # 总水头损失 (m)
    
    # 计算详情
    calc_steps: str = ""                # 计算过程文本
    friction_details: Dict = field(default_factory=dict)
    bend_details: List[Dict] = field(default_factory=list)
    inlet_transition_details: Dict = field(default_factory=dict)
    outlet_transition_details: Dict = field(default_factory=dict)


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
        
        turn_angle = ip.get('turn_angle', 0)
        turn_radius = ip.get('turn_radius', 0)
        
        if turn_angle > 0 and turn_radius > 0:
            xi, hj, details = calc_bend_local_loss(D, turn_radius, turn_angle, V_pipe)
            bend_losses.append(hj)
            bend_details.append(details)
            total_bend_loss += hj
            steps.append(f"   IP{i}: R={turn_radius:.2f}m, θ={turn_angle:.1f}°, ξ={xi:.4f}, hj={hj:.4f}m")
    
    result.bend_losses = bend_losses
    result.total_bend_loss = total_bend_loss
    result.bend_details = bend_details
    steps.append(f"   弯头局部损失合计: Σhj_弯 = {total_bend_loss:.4f} m")
    steps.append("")
    
    # 5. 进口渐变段损失
    steps.append(f"5. 进口渐变段水头损失")
    if inlet_transition_zeta is not None and inlet_transition_zeta > 0:
        inlet_zeta = inlet_transition_zeta
    else:
        inlet_zeta = get_transition_zeta(inlet_transition_form, is_inlet=True)
    hj_inlet, inlet_details = calc_transition_loss(V_pipe, upstream_velocity, inlet_zeta, is_inlet=True)
    result.inlet_transition_loss = hj_inlet
    result.inlet_transition_details = inlet_details
    steps.append(f"   型式: {inlet_transition_form}, ζ₁ = {inlet_zeta:.2f}")
    steps.append(f"   V_渠道 = {upstream_velocity:.4f} m/s, V_管道 = {V_pipe:.4f} m/s")
    steps.append(f"   hj₁ = ζ₁ × (V²_管道 - V²_渠道) / (2g) = {hj_inlet:.4f} m")
    steps.append("")
    
    # 6. 出口渐变段损失
    steps.append(f"6. 出口渐变段水头损失")
    if outlet_transition_zeta is not None and outlet_transition_zeta > 0:
        outlet_zeta = outlet_transition_zeta
    else:
        outlet_zeta = get_transition_zeta(outlet_transition_form, is_inlet=False)
    hj_outlet, outlet_details = calc_transition_loss(V_pipe, downstream_velocity, outlet_zeta, is_inlet=False)
    result.outlet_transition_loss = hj_outlet
    result.outlet_transition_details = outlet_details
    steps.append(f"   型式: {outlet_transition_form}, ζ₃ = {outlet_zeta:.2f}")
    steps.append(f"   V_管道 = {V_pipe:.4f} m/s, V_渠道 = {downstream_velocity:.4f} m/s")
    steps.append(f"   hj₃ = ζ₃ × (V²_渠道 - V²_管道) / (2g) = {hj_outlet:.4f} m")
    steps.append("")
    
    # 7. 总水头损失
    total = hf + total_bend_loss + hj_inlet + hj_outlet
    result.total_head_loss = total
    steps.append(f"7. 总水头损失")
    steps.append(f"   ΔH = hf + Σhj_弯 + hj₁ + hj₃")
    steps.append(f"      = {hf:.4f} + {total_bend_loss:.4f} + {hj_inlet:.4f} + {hj_outlet:.4f}")
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
