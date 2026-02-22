# -*- coding: utf-8 -*-
"""
隧洞水力设计计算模块

本模块提供隧洞断面的水力计算功能，支持：
1. 圆形断面
2. 圆拱直墙型断面
3. 马蹄形1（标准Ⅰ型）
4. 马蹄形2（标准Ⅱ型）

注意：矩形暗涵计算功能已分离至独立模块"矩形暗涵设计.py"

版本: V1.0
"""

import math
from typing import Dict, Any, Tuple

# ============================================================
# 常量定义
# ============================================================

PI = 3.14159265358979

# 圆形断面
MIN_DIAMETER_CIRC = 2.0     # 最小直径 (m)

# 圆拱直墙型断面
MIN_HEIGHT_HS = 2.0         # 最小高度 (m)
MIN_WIDTH_HS = 1.8          # 最小宽度 (m)
HB_RATIO_MIN = 1.0          # 推荐高宽比下限
HB_RATIO_MAX = 1.5          # 推荐高宽比上限

# 马蹄形断面
MIN_RADIUS_HORSESHOE_STD = 1.0    # 马蹄形最小半径 (m)，对应最小高度2.0m，最小宽度2.0m
# 标准Ⅰ型参数
HORSESHOE_T1 = 3.0                # t参数
HORSESHOE_THETA1 = 0.294515       # θ参数 (16.874467°)
HORSESHOE_C1 = 0.201996           # c参数
# 标准Ⅱ型参数
HORSESHOE_T2 = 2.0                # t参数
HORSESHOE_THETA2 = 0.424031       # θ参数 (24.295187°)
HORSESHOE_C2 = 0.436624           # c参数

# 净空要求 - 隧洞断面（圆形、圆拱直墙、马蹄形）
MIN_FREEBOARD_PCT_TUNNEL = 0.15    # 隧洞最小净空面积百分比 (15%)
MIN_FREEBOARD_HGT_TUNNEL = 0.4     # 隧洞最小净空高度 (m)

# 向后兼容的别名
MIN_FREEBOARD_PCT = MIN_FREEBOARD_PCT_TUNNEL
MIN_FREEBOARD_HGT = MIN_FREEBOARD_HGT_TUNNEL

# 计算参数
SOLVER_TOLERANCE = 0.0001
MAX_ITERATIONS = 100
DIM_INCREMENT = 0.01


# ============================================================
# 加大流量百分比
# ============================================================

def get_flow_increase_percent(design_Q: float) -> float:
    """隧洞加大流量百分比"""
    if design_Q <= 0:
        return 0.0
    elif design_Q < 1:
        return 30.0
    elif design_Q < 5:
        return 25.0
    elif design_Q < 20:
        return 20.0
    elif design_Q < 50:
        return 15.0
    elif design_Q < 100:
        return 10.0
    elif design_Q <= 300:
        return 5.0
    else:
        return 5.0


def get_required_freeboard_height(H_total: float) -> float:
    """
    计算隧洞所需最小净空高度（通用函数，用于圆形、圆拱直墙、马蹄形断面）
    """
    return MIN_FREEBOARD_HGT_TUNNEL


# ============================================================
# 圆形断面计算
# ============================================================

def calculate_circular_area(D: float, h: float) -> float:
    """计算圆形断面过水面积"""
    if D <= 0 or h <= 0:
        return 0.0
    
    R = D / 2
    h = min(h, D)
    
    if h >= D:
        return PI * R**2
    
    # 弓形面积计算
    theta = 2 * math.acos((R - h) / R)
    return R**2 * (theta - math.sin(theta)) / 2


def calculate_circular_perimeter(D: float, h: float) -> float:
    """计算圆形断面湿周"""
    if D <= 0 or h <= 0:
        return 0.0
    
    R = D / 2
    h = min(h, D)
    
    if h >= D:
        return PI * D
    
    theta = 2 * math.acos((R - h) / R)
    return R * theta


def calculate_circular_outputs(D: float, h: float, n: float, slope: float) -> Dict[str, float]:
    """计算圆形断面所有水力要素"""
    A = calculate_circular_area(D, h)
    P = calculate_circular_perimeter(D, h)
    R_hyd = A / P if P > 0 else 0
    
    if R_hyd > 0 and n > 0 and slope >= 0:
        Q_calc = (1/n) * A * (R_hyd ** (2/3)) * (slope ** 0.5)
    else:
        Q_calc = 0
    
    V = Q_calc / A if A > 0 else 0
    
    A_total = PI * (D/2)**2
    freeboard_pct = (A_total - A) / A_total * 100 if A_total > 0 else 100
    freeboard_hgt = D - h
    
    return {
        'A': A,
        'P': P,
        'R_hyd': R_hyd,
        'V': V,
        'Q': Q_calc,
        'A_total': A_total,
        'freeboard_pct': freeboard_pct,
        'freeboard_hgt': freeboard_hgt
    }


def solve_water_depth_circular(D: float, n: float, slope: float, Q_target: float) -> Tuple[float, bool]:
    """求解圆形断面水深"""
    if D <= 0 or n <= 0 or slope < 0 or Q_target <= 0.0000001:
        return (0.0, True) if Q_target <= 0.0000001 else (0.0, False)
    
    h_low = 0.00001
    h_high = D
    
    # 检查边界
    outputs_low = calculate_circular_outputs(D, h_low, n, slope)
    outputs_high = calculate_circular_outputs(D, h_high * 0.99999, n, slope)
    
    if Q_target <= outputs_low['Q'] * 1.001:
        return (h_low, True)
    if Q_target >= outputs_high['Q'] * 0.999:
        return (h_high * 0.99999, Q_target <= outputs_high['Q'] * 1.001)
    
    # 二分法求解
    h_mid = 0
    for _ in range(MAX_ITERATIONS):
        h_mid = (h_low + h_high) / 2
        if h_mid <= h_low or h_mid >= h_high:
            break
        
        outputs = calculate_circular_outputs(D, h_mid, n, slope)
        Q_mid = outputs['Q']
        
        if Q_mid > 0 and abs(Q_mid - Q_target) / Q_target < SOLVER_TOLERANCE:
            return (h_mid, True)
        
        if Q_mid < Q_target:
            h_low = h_mid
        else:
            h_high = h_mid
    
    # 最终检查
    outputs = calculate_circular_outputs(D, h_mid, n, slope)
    if outputs['Q'] > 0 and abs(outputs['Q'] - Q_target) / Q_target < SOLVER_TOLERANCE * 1.5:
        return (h_mid, True)
    
    return (h_mid, False)


# ============================================================
# 圆拱直墙型断面计算
# ============================================================

def calculate_horseshoe_area(B: float, H_total: float, theta_rad: float, h: float) -> float:
    """计算圆拱直墙型过水面积"""
    if B <= 0 or H_total <= 0 or h <= 0 or theta_rad <= 0 or theta_rad > PI + 0.001:
        return 0.0
    
    if abs(math.sin(theta_rad / 2)) < 0.000000001:
        return 0.0
    
    R_arch = (B / 2) / math.sin(theta_rad / 2)
    H_arch = R_arch * (1 - math.cos(theta_rad / 2))
    H_straight = max(0, H_total - H_arch)
    
    calc_depth = min(h, H_total)
    if calc_depth <= 0.000000001:
        return 0.0
    
    if calc_depth <= H_straight:
        # 水在直墙部分
        return B * calc_depth
    else:
        # 水进入拱部
        Area_rect = B * H_straight
        h_in_arch = calc_depth - H_straight
        
        if h_in_arch <= 0.000000001:
            return Area_rect
        elif h_in_arch >= H_arch - 0.000000001:
            # 拱部全满
            Area_arch = (R_arch**2 / 2) * (theta_rad - math.sin(theta_rad))
            return Area_rect + Area_arch
        else:
            # 拱部部分充水
            Area_arch_total = (R_arch**2 / 2) * (theta_rad - math.sin(theta_rad))
            h_dry = H_arch - h_in_arch
            
            d_temp = R_arch - h_dry
            acos_arg = max(-1, min(1, d_temp / R_arch))
            alpha_temp = math.acos(acos_arg)
            Area_dry = R_arch**2 * alpha_temp - d_temp * math.sqrt(max(0, R_arch**2 - d_temp**2))
            
            return Area_rect + Area_arch_total - Area_dry


def calculate_horseshoe_perimeter(B: float, H_total: float, theta_rad: float, h: float) -> float:
    """计算圆拱直墙型湿周"""
    if B <= 0 or H_total <= 0 or h <= 0 or theta_rad <= 0 or theta_rad > PI + 0.001:
        return 0.0
    
    if abs(math.sin(theta_rad / 2)) < 0.000000001:
        return 0.0
    
    R_arch = (B / 2) / math.sin(theta_rad / 2)
    H_arch = R_arch * (1 - math.cos(theta_rad / 2))
    H_straight = max(0, H_total - H_arch)
    
    calc_depth = min(h, H_total)
    if calc_depth <= 0.000000001:
        return 0.0
    
    if calc_depth <= H_straight:
        return B + 2 * calc_depth
    else:
        Perim_base = B
        Perim_wall = 2 * H_straight
        h_in_arch = calc_depth - H_straight
        
        if h_in_arch <= 0.000000001:
            return Perim_base + Perim_wall
        elif h_in_arch >= H_arch - 0.000000001:
            return Perim_base + Perim_wall + R_arch * theta_rad
        else:
            Total_Arc = R_arch * theta_rad
            h_dry = H_arch - h_in_arch
            
            d_temp = R_arch - h_dry
            acos_arg = max(-1, min(1, d_temp / R_arch))
            alpha_temp = math.acos(acos_arg)
            L_dry = 2 * R_arch * alpha_temp
            
            return Perim_base + Perim_wall + Total_Arc - L_dry


def calculate_horseshoe_total_area(B: float, H_total: float, theta_rad: float) -> float:
    """计算圆拱直墙型总断面面积"""
    if B <= 0 or H_total <= 0 or theta_rad <= 0 or theta_rad > PI + 0.001:
        return 0.0
    
    if abs(math.sin(theta_rad / 2)) < 0.000000001:
        return 0.0
    
    R_arch = (B / 2) / math.sin(theta_rad / 2)
    H_arch = R_arch * (1 - math.cos(theta_rad / 2))
    H_straight = max(0, H_total - H_arch)
    
    Area_rect = B * H_straight
    Area_arch = (R_arch**2 / 2) * (theta_rad - math.sin(theta_rad))
    
    return Area_rect + Area_arch


def calculate_horseshoe_outputs(B: float, H_total: float, theta_rad: float, 
                                h: float, n: float, slope: float) -> Dict[str, float]:
    """计算圆拱直墙型所有水力要素"""
    A = calculate_horseshoe_area(B, H_total, theta_rad, h)
    P = calculate_horseshoe_perimeter(B, H_total, theta_rad, h)
    R_hyd = A / P if P > 0.000000001 else 0
    
    if R_hyd > 0 and n > 0 and slope >= 0:
        try:
            Q_calc = (1/n) * A * (R_hyd ** (2/3)) * (slope ** 0.5)
        except:
            Q_calc = 0
    else:
        Q_calc = 0
    
    V = Q_calc / A if A > 0.000000001 else 0
    
    A_total = calculate_horseshoe_total_area(B, H_total, theta_rad)
    freeboard_pct = (A_total - A) / A_total * 100 if A_total > 0.000000001 else 100
    freeboard_hgt = H_total - h
    
    return {
        'A': A,
        'P': P,
        'R_hyd': R_hyd,
        'V': V,
        'Q': Q_calc,
        'A_total': A_total,
        'freeboard_pct': freeboard_pct,
        'freeboard_hgt': freeboard_hgt
    }


def solve_water_depth_horseshoe(B: float, H_total: float, theta_rad: float,
                                 n: float, slope: float, Q_target: float) -> Tuple[float, bool]:
    """求解圆拱直墙型水深"""
    if B <= 0 or H_total <= 0 or theta_rad <= 0 or theta_rad > PI + 0.001:
        return (0.0, False)
    if n <= 0 or slope < 0 or Q_target <= 0.0000001:
        return (0.0, True) if Q_target <= 0.0000001 else (0.0, False)
    
    h_low = 0.00001
    h_high = H_total
    
    # 检查边界
    outputs_low = calculate_horseshoe_outputs(B, H_total, theta_rad, h_low, n, slope)
    outputs_high = calculate_horseshoe_outputs(B, H_total, theta_rad, h_high * 0.99999, n, slope)
    
    if Q_target <= outputs_low['Q'] * 1.001:
        return (h_low, True)
    if Q_target >= outputs_high['Q'] * 0.999:
        return (h_high * 0.99999, Q_target <= outputs_high['Q'] * 1.001)
    
    # 二分法
    h_mid = 0
    for _ in range(MAX_ITERATIONS):
        h_mid = (h_low + h_high) / 2
        if h_mid <= h_low or h_mid >= h_high:
            break
        
        outputs = calculate_horseshoe_outputs(B, H_total, theta_rad, h_mid, n, slope)
        Q_mid = outputs['Q']
        
        if Q_mid > 0 and abs(Q_mid - Q_target) / Q_target < SOLVER_TOLERANCE:
            return (h_mid, True)
        
        if Q_mid < Q_target:
            h_low = h_mid
        else:
            h_high = h_mid
    
    outputs = calculate_horseshoe_outputs(B, H_total, theta_rad, h_mid, n, slope)
    if outputs['Q'] > 0 and abs(outputs['Q'] - Q_target) / Q_target < SOLVER_TOLERANCE * 1.5:
        return (h_mid, True)
    
    return (h_mid, False)


# ============================================================
# 马蹄形断面计算（标准Ⅰ型和标准Ⅱ型）
# ============================================================

def calculate_horseshoe_std_elements(section_type: int, r: float, h: float) -> Tuple[float, float, float, bool]:
    """
    计算标准马蹄形断面的水力要素
    
    参数:
        section_type: 1=标准Ⅰ型, 2=标准Ⅱ型
        r: 马蹄形半径 (m)
        h: 水深 (m)
    
    返回:
        (A, B, P, success): 过水面积, 水面宽度, 湿周, 是否成功
    """
    try:
        # 设定几何参数
        if section_type == 1:
            t = HORSESHOE_T1
            theta = HORSESHOE_THETA1
            c = HORSESHOE_C1
        elif section_type == 2:
            t = HORSESHOE_T2
            theta = HORSESHOE_THETA2
            c = HORSESHOE_C2
        else:
            return (0, 0, 0, False)
        
        R_arch = t * r
        e = R_arch * (1 - math.cos(theta))
        
        A = 0
        B = 0
        P = 0
        
        if h >= 0 and h <= e:
            # --- 底拱段 ---
            if h < 0.000000001:
                return (0, 0, 0, True)
            
            # 反算 β
            cos_val = 1 - h / R_arch
            cos_val = max(-1, min(1, cos_val))
            beta = math.acos(cos_val)
            
            # 计算 A, B, P
            A = (t * r) ** 2 * (beta - 0.5 * math.sin(2 * beta))
            B = 2 * t * r * math.sin(beta)
            P = 2 * R_arch * beta
            
        elif h > e and h <= r:
            # --- 侧拱段 ---
            
            # 反算 α
            sin_val = (1 - h / r) / t
            sin_val = max(-1, min(1, sin_val))
            alpha = math.asin(sin_val)
            
            # 计算 A, B, P
            A = R_arch ** 2 * (c - alpha - 0.5 * math.sin(2 * alpha) + ((2 * t - 2) / t) * math.sin(alpha))
            B = 2 * r * (t * math.cos(alpha) - t + 1)
            P = 2 * t * r * (2 * theta - alpha)
            
        elif h > r and h <= 2 * r:
            # --- 顶拱段 ---
            
            # 反算 φ
            cos_val = h / r - 1
            cos_val = max(-1, min(1, cos_val))
            phi_half = math.acos(cos_val)
            phi = 2 * phi_half
            
            # 计算 A, B, P
            A = r ** 2 * (t ** 2 * c + 0.5 * (PI - phi + math.sin(phi)))
            B = 2 * r * math.sin(phi_half)
            P = 4 * t * r * theta + r * (PI - phi)
            
        else:
            # 超出范围
            return (0, 0, 0, False)
        
        # 检查结果有效性
        if A < 0 or B < 0 or P < 0:
            return (0, 0, 0, False)
        
        return (A, B, P, True)
        
    except:
        return (0, 0, 0, False)


def calculate_horseshoe_std_outputs(section_type: int, r: float, h: float, 
                                     n: float, slope: float) -> Dict[str, float]:
    """计算标准马蹄形断面所有水力要素"""
    A, B_width, P, success = calculate_horseshoe_std_elements(section_type, r, h)
    
    if not success or P <= 0.000000001:
        return {
            'A': 0, 'P': 0, 'R_hyd': 0, 'V': 0, 'Q': 0,
            'A_total': 0, 'freeboard_pct': 100, 'freeboard_hgt': 0, 'B_width': 0
        }
    
    R_hyd = A / P
    
    if R_hyd > 0 and n > 0 and slope >= 0:
        try:
            Q_calc = (1/n) * A * (R_hyd ** (2/3)) * (slope ** 0.5)
        except:
            Q_calc = 0
    else:
        Q_calc = 0
    
    V = Q_calc / A if A > 0.000000001 else 0
    
    # 计算总断面面积（h=2r时的过水面积）
    A_total_elem, _, _, success_total = calculate_horseshoe_std_elements(section_type, r, 2 * r)
    A_total = A_total_elem if success_total else PI * r ** 2  # 备用圆形近似
    
    freeboard_pct = (A_total - A) / A_total * 100 if A_total > 0.000000001 else 100
    freeboard_hgt = 2 * r - h
    
    return {
        'A': A,
        'P': P,
        'R_hyd': R_hyd,
        'V': V,
        'Q': Q_calc,
        'A_total': A_total,
        'freeboard_pct': freeboard_pct,
        'freeboard_hgt': freeboard_hgt,
        'B_width': B_width
    }


def solve_water_depth_horseshoe_std(section_type: int, r: float, n: float, 
                                     slope: float, Q_target: float) -> Tuple[float, bool]:
    """求解标准马蹄形断面水深"""
    if r <= 0 or n <= 0 or slope < 0 or Q_target <= 0.0000001:
        return (0.0, True) if Q_target <= 0.0000001 else (0.0, False)
    
    h_min = 0.000001
    h_max = 2 * r
    h_mid = 0
    
    # 二分法求解
    for _ in range(MAX_ITERATIONS):
        h_mid = (h_min + h_max) / 2
        if (h_max - h_min) < 0.000001:
            break
        
        outputs = calculate_horseshoe_std_outputs(section_type, r, h_mid, n, slope)
        Q_mid = outputs['Q']
        
        if Q_mid > 0 and abs(Q_mid - Q_target) / Q_target < SOLVER_TOLERANCE:
            return (h_mid, True)
        
        if Q_mid < Q_target:
            h_min = h_mid
        else:
            h_max = h_mid
    
    # 最终检查
    outputs = calculate_horseshoe_std_outputs(section_type, r, h_mid, n, slope)
    if outputs['Q'] > 0 and abs(outputs['Q'] - Q_target) / Q_target < SOLVER_TOLERANCE * 1.5:
        return (h_mid, True)
    
    return (h_mid, False)


def quick_calculate_horseshoe_std(Q: float, n: float, slope_inv: float,
                                   v_min: float, v_max: float,
                                   section_type: int,
                                   manual_r: float = None,
                                   manual_increase_percent: float = None) -> Dict[str, Any]:
    """
    标准马蹄形隧洞快速计算
    
    参数:
        section_type: 1=标准Ⅰ型, 2=标准Ⅱ型
        manual_r: 手动指定半径 (m)
    """
    type_name = '马蹄形标准Ⅰ型' if section_type == 1 else '马蹄形标准Ⅱ型'
    
    result = {
        'success': False,
        'error_message': '',
        'section_type': type_name,
        'design_method': '',
        'r': 0,
        'D_equiv': 0,  # 等效直径 (2r)
        'h_design': 0,
        'V_design': 0,
        'A_design': 0,
        'P_design': 0,
        'R_hyd_design': 0,
        'Q_calc': 0,
        'freeboard_pct_design': 0,
        'freeboard_hgt_design': 0,
        'increase_percent': 0,
        'Q_increased': 0,
        'h_increased': 0,
        'V_increased': 0,
        'freeboard_pct_inc': 0,
        'freeboard_hgt_inc': 0,
        'A_total': 0,
    }
    
    if Q <= 0 or n <= 0 or slope_inv <= 0:
        result['error_message'] = '输入参数无效'
        return result
    
    slope = 1.0 / slope_inv
    
    if section_type not in [1, 2]:
        result['error_message'] = '断面类型无效，必须为1(标准Ⅰ型)或2(标准Ⅱ型)'
        return result
    
    # 加大流量
    if manual_increase_percent is not None and manual_increase_percent >= 0:
        increase_percent = manual_increase_percent
    else:
        increase_percent = get_flow_increase_percent(Q)
    
    Q_increased = Q * (1 + increase_percent / 100)
    result['increase_percent'] = increase_percent
    result['Q_increased'] = Q_increased
    
    # 搜索半径
    found_solution = False
    best_r = 0
    
    if manual_r and manual_r > 0:
        r_start = manual_r
        r_end = manual_r + 0.01
    else:
        r_start = MIN_RADIUS_HORSESHOE_STD
        r_end = 10.0
    
    r = r_start
    while r < r_end:
        # 设计水深
        h_design, success_design = solve_water_depth_horseshoe_std(section_type, r, n, slope, Q)
        if not success_design or h_design >= 2 * r:
            r += DIM_INCREMENT
            continue
        
        outputs_design = calculate_horseshoe_std_outputs(section_type, r, h_design, n, slope)
        
        # 验证设计流速
        if outputs_design['V'] < v_min or outputs_design['V'] > v_max:
            r += DIM_INCREMENT
            continue
            
        if outputs_design['freeboard_hgt'] < MIN_FREEBOARD_HGT:
            r += DIM_INCREMENT
            continue
        if outputs_design['freeboard_pct'] < MIN_FREEBOARD_PCT * 100:
            r += DIM_INCREMENT
            continue
        
        # 加大水深
        h_inc, success_inc = solve_water_depth_horseshoe_std(section_type, r, n, slope, Q_increased)
        if not success_inc or h_inc >= 2 * r:
            r += DIM_INCREMENT
            continue
        
        outputs_inc = calculate_horseshoe_std_outputs(section_type, r, h_inc, n, slope)
        
        # 验证加大流速
        if outputs_inc['V'] > v_max:
            r += DIM_INCREMENT
            continue
            
        if (outputs_inc['freeboard_hgt'] >= MIN_FREEBOARD_HGT and
            outputs_inc['freeboard_pct'] >= MIN_FREEBOARD_PCT * 100):
            
            best_r = r
            found_solution = True
            break
        
        r += DIM_INCREMENT
    
    if not found_solution:
        if manual_r:
            result['error_message'] = (
                f"计算失败：手动指定的半径 r={manual_r:.3f} m 无法满足要求。\n\n"
                "可能原因及建议：\n"
                "1. 半径过小，导致加大流量工况下无净空；\n"
                "2. 流速超出限制；\n"
                "建议：增大半径，或者留空半径输入框由系统计算。"
            )
        else:
            result['error_message'] = '计算失败：在搜索范围内（半径1.0m~10.0m）未找到满足流速及净空约束的尺寸。建议检查流量及坡降设置。'
        return result
    
    # 最终计算
    r = best_r
    h_design, _ = solve_water_depth_horseshoe_std(section_type, r, n, slope, Q)
    h_inc, _ = solve_water_depth_horseshoe_std(section_type, r, n, slope, Q_increased)
    
    outputs_design = calculate_horseshoe_std_outputs(section_type, r, h_design, n, slope)
    outputs_inc = calculate_horseshoe_std_outputs(section_type, r, h_inc, n, slope)
    
    result['success'] = True
    result['design_method'] = f'{type_name}; r={r:.2f}m'
    result['r'] = r
    result['D_equiv'] = 2 * r
    result['h_design'] = h_design
    result['V_design'] = outputs_design['V']
    result['A_design'] = outputs_design['A']
    result['P_design'] = outputs_design['P']
    result['R_hyd_design'] = outputs_design['R_hyd']
    result['Q_calc'] = outputs_design['Q']
    result['freeboard_pct_design'] = outputs_design['freeboard_pct']
    result['freeboard_hgt_design'] = outputs_design['freeboard_hgt']
    result['h_increased'] = h_inc
    result['V_increased'] = outputs_inc['V']
    result['A_increased'] = outputs_inc['A']
    result['P_increased'] = outputs_inc['P']
    result['R_hyd_increased'] = outputs_inc['R_hyd']
    result['freeboard_pct_inc'] = outputs_inc['freeboard_pct']
    result['freeboard_hgt_inc'] = outputs_inc['freeboard_hgt']
    result['A_total'] = outputs_design['A_total']
    
    return result


# ============================================================
# 主计算函数
# ============================================================

def quick_calculate_circular(Q: float, n: float, slope_inv: float,
                              v_min: float, v_max: float,
                              manual_D: float = None,
                              manual_increase_percent: float = None) -> Dict[str, Any]:
    """
    圆形隧洞快速计算
    """
    result = {
        'success': False,
        'error_message': '',
        'section_type': '圆形',
        'design_method': '',
        'D': 0,
        'h_design': 0,
        'V_design': 0,
        'A_design': 0,
        'P_design': 0,
        'R_hyd_design': 0,
        'Q_calc': 0,
        'freeboard_pct_design': 0,
        'freeboard_hgt_design': 0,
        'increase_percent': 0,
        'Q_increased': 0,
        'h_increased': 0,
        'V_increased': 0,
        'freeboard_pct_inc': 0,
        'freeboard_hgt_inc': 0,
        'A_total': 0,
    }
    
    if Q <= 0 or n <= 0 or slope_inv <= 0:
        result['error_message'] = '输入参数无效'
        return result
    
    slope = 1.0 / slope_inv
    
    # 加大流量
    if manual_increase_percent is not None and manual_increase_percent >= 0:
        increase_percent = manual_increase_percent
    else:
        increase_percent = get_flow_increase_percent(Q)
    
    Q_increased = Q * (1 + increase_percent / 100)
    result['increase_percent'] = increase_percent
    result['Q_increased'] = Q_increased
    
    # 搜索直径
    found_solution = False
    best_D = 0
    
    if manual_D and manual_D > 0:
        D_start = manual_D
        D_end = manual_D + 0.01
    else:
        D_start = MIN_DIAMETER_CIRC
        D_end = 20.0
    
    D = D_start
    while D < D_end:
        # 设计水深
        h_design, success_design = solve_water_depth_circular(D, n, slope, Q)
        if not success_design or h_design >= D:
            D += DIM_INCREMENT
            continue
        
        outputs_design = calculate_circular_outputs(D, h_design, n, slope)
        
        # 验证设计流速
        if outputs_design['V'] < v_min or outputs_design['V'] > v_max:
            D += DIM_INCREMENT
            continue
            
        if outputs_design['freeboard_hgt'] < MIN_FREEBOARD_HGT:
            D += DIM_INCREMENT
            continue
        
        # 加大水深
        h_inc, success_inc = solve_water_depth_circular(D, n, slope, Q_increased)
        if not success_inc or h_inc >= D:
            D += DIM_INCREMENT
            continue
        
        outputs_inc = calculate_circular_outputs(D, h_inc, n, slope)
        
        # 验证加大流速
        if outputs_inc['V'] > v_max:
            D += DIM_INCREMENT
            continue
            
        if (outputs_inc['freeboard_hgt'] >= MIN_FREEBOARD_HGT and 
            outputs_inc['freeboard_pct'] >= MIN_FREEBOARD_PCT * 100 and
            outputs_design['freeboard_pct'] >= MIN_FREEBOARD_PCT * 100):
            
            best_D = D
            found_solution = True
            break
        
        D += DIM_INCREMENT
    
    if not found_solution:
        if manual_D:
            result['error_message'] = (
                f"计算失败：手动指定的直径 D={manual_D:.3f} m 无法满足要求。\n\n"
                "可能原因及建议：\n"
                "1. 直径过小，导致加大流量工况下无净空或水深超出管径；\n"
                "2. 流速超出不冲/不淤限制；\n"
                "建议：增大直径，或者留空直径由系统自动计算。"
            )
        else:
            result['error_message'] = '计算失败：在搜索范围内（2.0m~20.0m）未找到满足流速及净空要求的直径。建议检查流量及坡降设置。'
        return result
    
    # 最终计算
    D = best_D
    h_design, _ = solve_water_depth_circular(D, n, slope, Q)
    h_inc, _ = solve_water_depth_circular(D, n, slope, Q_increased)
    
    outputs_design = calculate_circular_outputs(D, h_design, n, slope)
    outputs_inc = calculate_circular_outputs(D, h_inc, n, slope)
    
    result['success'] = True
    result['design_method'] = f'圆形断面; D={D:.2f}m'
    result['D'] = D
    result['h_design'] = h_design
    result['V_design'] = outputs_design['V']
    result['A_design'] = outputs_design['A']
    result['P_design'] = outputs_design['P']
    result['R_hyd_design'] = outputs_design['R_hyd']
    result['Q_calc'] = outputs_design['Q']
    result['freeboard_pct_design'] = outputs_design['freeboard_pct']
    result['freeboard_hgt_design'] = outputs_design['freeboard_hgt']
    result['h_increased'] = h_inc
    result['V_increased'] = outputs_inc['V']
    result['A_increased'] = outputs_inc['A']
    result['P_increased'] = outputs_inc['P']
    result['R_hyd_increased'] = outputs_inc['R_hyd']
    result['freeboard_pct_inc'] = outputs_inc['freeboard_pct']
    result['freeboard_hgt_inc'] = outputs_inc['freeboard_hgt']
    result['A_total'] = outputs_design['A_total']
    
    return result


def quick_calculate_horseshoe(Q: float, n: float, slope_inv: float,
                               v_min: float, v_max: float,
                               theta_deg: float = 180.0,
                               manual_B: float = None,
                               manual_increase_percent: float = None) -> Dict[str, Any]:
    """
    圆拱直墙型隧洞快速计算
    """
    # 处理默认圆心角
    if theta_deg is None or theta_deg <= 0:
        theta_deg = 180.0
        
    result = {
        'success': False,
        'error_message': '',
        'section_type': '圆拱直墙型',
        'design_method': '',
        'B': 0,
        'H_total': 0,
        'H_straight': 0,
        'theta_deg': theta_deg,
        'HB_ratio': 0,
        'h_design': 0,
        'V_design': 0,
        'A_design': 0,
        'P_design': 0,
        'R_hyd_design': 0,
        'Q_calc': 0,
        'freeboard_pct_design': 0,
        'freeboard_hgt_design': 0,
        'increase_percent': 0,
        'Q_increased': 0,
        'h_increased': 0,
        'V_increased': 0,
        'freeboard_pct_inc': 0,
        'freeboard_hgt_inc': 0,
        'A_total': 0,
    }
    
    if Q <= 0 or n <= 0 or slope_inv <= 0:
        result['error_message'] = '输入参数无效'
        return result
    
    slope = 1.0 / slope_inv
    theta_rad = math.radians(theta_deg)
    
    if theta_deg < 90 or theta_deg > 180:
        result['error_message'] = '圆心角必须在90~180度之间'
        return result
    
    # 加大流量
    if manual_increase_percent is not None and manual_increase_percent >= 0:
        increase_percent = manual_increase_percent
    else:
        increase_percent = get_flow_increase_percent(Q)
    
    Q_increased = Q * (1 + increase_percent / 100)
    result['increase_percent'] = increase_percent
    result['Q_increased'] = Q_increased
    
    # 搜索最优解
    best_found = False
    best_B = 0
    best_H = 0
    best_A_total = 1e99
    
    if manual_B and manual_B > 0:
        B_start = manual_B
        B_end = manual_B + 0.01
        B_step = DIM_INCREMENT
        # 手动指定底宽时，使用精细的高宽比步长以获得最优H_total
        HB_step = 0.01
    else:
        B_start = MIN_WIDTH_HS
        B_end = 20.0
        # 优化1：粗搜索步长增大到0.1m，减少90%的搜索次数
        B_step = 0.1
        # 优化2：减少高宽比搜索次数，步长从0.01增大到0.05
        HB_step = 0.05
    
    B = B_start
    while B < B_end:
        # 优化3：如果已找到解，进行局部精细搜索后提前退出
        if best_found and B > best_B + 0.5:
            break
            
        # 遍历高宽比
        HB_start = int(HB_RATIO_MIN * 100)
        HB_end = int(HB_RATIO_MAX * 100) + 1
        HB_increment = int(HB_step * 100)
        
        for HB_int in range(HB_start, HB_end, HB_increment):
            HB_ratio = HB_int / 100.0
            H_trial = max(MIN_HEIGHT_HS, B * HB_ratio)
            
            if abs(math.sin(theta_rad / 2)) < 0.000000001:
                continue
            
            R_arch = (B / 2) / math.sin(theta_rad / 2)
            H_arch = R_arch * (1 - math.cos(theta_rad / 2))
            H_straight = H_trial - H_arch
            
            if H_straight < -0.000000001:
                continue
            
            # 设计水深
            h_design, success_design = solve_water_depth_horseshoe(B, H_trial, theta_rad, n, slope, Q)
            
            if not success_design or h_design >= H_trial:
                continue
            
            outputs_design = calculate_horseshoe_outputs(B, H_trial, theta_rad, h_design, n, slope)
            
            # 验证设计流速
            if outputs_design['V'] < v_min or outputs_design['V'] > v_max:
                continue
                
            if outputs_design['freeboard_hgt'] < MIN_FREEBOARD_HGT:
                continue
            if outputs_design['freeboard_pct'] < MIN_FREEBOARD_PCT * 100:
                continue
            
            # 加大水深
            h_inc, success_inc = solve_water_depth_horseshoe(B, H_trial, theta_rad, n, slope, Q_increased)
            
            if not success_inc or h_inc >= H_trial:
                continue
            
            outputs_inc = calculate_horseshoe_outputs(B, H_trial, theta_rad, h_inc, n, slope)
            
            # 验证加大流速
            if outputs_inc['V'] > v_max:
                continue
                
            if (outputs_inc['freeboard_hgt'] >= MIN_FREEBOARD_HGT and
                outputs_inc['freeboard_pct'] >= MIN_FREEBOARD_PCT * 100):
                
                A_total = outputs_design['A_total']
                if A_total < best_A_total:
                    best_A_total = A_total
                    best_B = B
                    best_H = H_trial
                    best_found = True
        
        B += B_step
    
    # 优化4：如果找到解，在最优解附近进行精细搜索
    if best_found and manual_B is None:
        fine_search_range = 0.3  # 在最优解±0.3m范围内精细搜索
        fine_B_step = DIM_INCREMENT
        fine_HB_step = 0.01
        
        fine_B_start = max(MIN_WIDTH_HS, best_B - fine_search_range)
        fine_B_end = min(B_end, best_B + fine_search_range)
        
        B = fine_B_start
        while B < fine_B_end:
            HB_start = int(HB_RATIO_MIN * 100)
            HB_end = int(HB_RATIO_MAX * 100) + 1
            HB_increment = int(fine_HB_step * 100)
            
            for HB_int in range(HB_start, HB_end, HB_increment):
                HB_ratio = HB_int / 100.0
                H_trial = max(MIN_HEIGHT_HS, B * HB_ratio)
                
                if abs(math.sin(theta_rad / 2)) < 0.000000001:
                    continue
                
                R_arch = (B / 2) / math.sin(theta_rad / 2)
                H_arch = R_arch * (1 - math.cos(theta_rad / 2))
                H_straight = H_trial - H_arch
                
                if H_straight < -0.000000001:
                    continue
                
                h_design, success_design = solve_water_depth_horseshoe(B, H_trial, theta_rad, n, slope, Q)
                
                if not success_design or h_design >= H_trial:
                    continue
                
                outputs_design = calculate_horseshoe_outputs(B, H_trial, theta_rad, h_design, n, slope)
                
                if outputs_design['V'] < v_min or outputs_design['V'] > v_max:
                    continue
                    
                if outputs_design['freeboard_hgt'] < MIN_FREEBOARD_HGT:
                    continue
                if outputs_design['freeboard_pct'] < MIN_FREEBOARD_PCT * 100:
                    continue
                
                h_inc, success_inc = solve_water_depth_horseshoe(B, H_trial, theta_rad, n, slope, Q_increased)
                
                if not success_inc or h_inc >= H_trial:
                    continue
                
                outputs_inc = calculate_horseshoe_outputs(B, H_trial, theta_rad, h_inc, n, slope)
                
                if outputs_inc['V'] > v_max:
                    continue
                    
                if (outputs_inc['freeboard_hgt'] >= MIN_FREEBOARD_HGT and
                    outputs_inc['freeboard_pct'] >= MIN_FREEBOARD_PCT * 100):
                    
                    A_total = outputs_design['A_total']
                    if A_total < best_A_total:
                        best_A_total = A_total
                        best_B = B
                        best_H = H_trial
            
            B += fine_B_step
    
    if not best_found:
        if manual_B:
            result['error_message'] = (
                f"计算失败：手动指定的底宽 B={manual_B:.3f} m 无法满足要求。\n\n"
                "可能原因及建议：\n"
                "1. 尺寸过小，导致加大流量工况下无净空或水深超出洞高；\n"
                "2. 流速超出限制；\n"
                "建议：增大底宽，或者留空底宽由系统自动计算。"
            )
        # 如果是使用默认圆心角180°，给出更友好的提示
        elif abs(theta_deg - 180.0) < 0.1:  # 默认值
            result['error_message'] = '计算失败：未找到满足约束条件的断面尺寸。建议：1. 尝试调整圆心角（如120°、150°等）；2. 检查流量及坡降是否合理。'
        else:
            result['error_message'] = '计算失败：未找到满足约束条件的断面尺寸。'
        return result
    
    # 最终计算
    B = best_B
    H_total = best_H
    
    R_arch = (B / 2) / math.sin(theta_rad / 2)
    H_arch = R_arch * (1 - math.cos(theta_rad / 2))
    H_straight = H_total - H_arch
    
    h_design, _ = solve_water_depth_horseshoe(B, H_total, theta_rad, n, slope, Q)
    h_inc, _ = solve_water_depth_horseshoe(B, H_total, theta_rad, n, slope, Q_increased)
    
    outputs_design = calculate_horseshoe_outputs(B, H_total, theta_rad, h_design, n, slope)
    outputs_inc = calculate_horseshoe_outputs(B, H_total, theta_rad, h_inc, n, slope)
    
    result['success'] = True
    result['design_method'] = f'圆拱直墙型; B={B:.2f}m, H={H_total:.2f}m, θ={theta_deg}°'
    result['B'] = B
    result['H_total'] = H_total
    result['H_straight'] = H_straight
    result['HB_ratio'] = H_total / B if B > 0 else 0
    result['h_design'] = h_design
    result['V_design'] = outputs_design['V']
    result['A_design'] = outputs_design['A']
    result['P_design'] = outputs_design['P']
    result['R_hyd_design'] = outputs_design['R_hyd']
    result['Q_calc'] = outputs_design['Q']
    result['freeboard_pct_design'] = outputs_design['freeboard_pct']
    result['freeboard_hgt_design'] = outputs_design['freeboard_hgt']
    result['h_increased'] = h_inc
    result['V_increased'] = outputs_inc['V']
    result['A_increased'] = outputs_inc['A']
    result['P_increased'] = outputs_inc['P']
    result['R_hyd_increased'] = outputs_inc['R_hyd']
    result['freeboard_pct_inc'] = outputs_inc['freeboard_pct']
    result['freeboard_hgt_inc'] = outputs_inc['freeboard_hgt']
    result['A_total'] = outputs_design['A_total']
    
    return result


# ============================================================
# 测试
# ============================================================

if __name__ == '__main__':
    print("=" * 70)
    print("Tunnel Hydraulic Design Module Test")
    print("=" * 70)
    
    # 圆形断面测试
    print("\n--- Circular Section Test ---")
    result = quick_calculate_circular(Q=10.0, n=0.014, slope_inv=3000, v_min=0.5, v_max=3.0)
    if result['success']:
        print(f"D = {result['D']:.2f} m")
        print(f"h_design = {result['h_design']:.3f} m")
        print(f"V_design = {result['V_design']:.3f} m/s")
        print(f"freeboard_pct = {result['freeboard_pct_design']:.1f}%")
    else:
        print(f"Failed: {result['error_message']}")
    
    # 圆拱直墙型测试
    print("\n--- Horseshoe Section Test ---")
    result = quick_calculate_horseshoe(Q=10.0, n=0.014, slope_inv=3000, v_min=0.5, v_max=3.0, theta_deg=120)
    if result['success']:
        print(f"B = {result['B']:.2f} m")
        print(f"H_total = {result['H_total']:.2f} m")
        print(f"h_design = {result['h_design']:.3f} m")
        print(f"V_design = {result['V_design']:.3f} m/s")
    else:
        print(f"Failed: {result['error_message']}")
    
    print("\n" + "=" * 70)
    print("Test completed")
