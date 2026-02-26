# -*- coding: utf-8 -*-
"""
渡槽水力设计计算模块

本模块提供渡槽断面的水力计算功能，支持：
1. U形断面
2. 矩形断面（可带倒角）

水力设计依据:
--------------------------------------------------
规范条款 9.4.1：水力设计内容应包括选择槽身纵向底坡、确定槽身过水断面尺寸、
通过水面衔接计算确定渡槽底部纵向各部高程，具体应符合下列规定：

规范条款 9.4.1-1（流速推荐值）：
槽身底坡应为缓坡（排洪渡槽除外），槽内设计流速宜为 1.0m/s～2.5m/s。
【实现方式】：如果计算出来的流速不在推荐范围内，需要向用户提供明确的提示信息。
流速作为推荐值，超出范围时仅作提示但允许继续计算。

规范条款 9.4.1-2（超高控制条件）：
槽身过水断面通过设计流量时矩形断面的超高不应小于槽内水深的1/12加0.05m，
U形断面超高不应小于槽身直径的1/10。通过加大流量时槽中水面与无拉杆槽身顶部
或有拉杆槽身的拉杆底部高差不应小于0.10m，平面中轴线为曲线的槽内水深应取弯
道处槽内横向最大水深值。
【实现方式】：超高作为控制条件之一，必须严格符合超高要求，不符合时应标记为计算失败。

矩形渡槽深宽比说明：
--------------------------------------------------
槽身横断面主要尺寸是净宽(水面宽)B和净深(满槽水深)H。
深宽比定义：H/B = 槽身总高度 / 槽宽
矩形渡槽常用深宽比推荐值：0.6 ~ 0.8
【实现方式】：用户可指定深宽比，若留空则默认使用0.8。
--------------------------------------------------

版本: V1.0
"""

import math
from typing import Dict, Any, Tuple

# ============================================================
# 常量定义
# ============================================================

PI = 3.14159265358979

# U形断面参数
FR_MIN = 0.4      # f/R 最小推荐值
FR_MAX = 0.6      # f/R 最大推荐值
HB_MIN = 0.7      # H/(2R) 最小推荐值
HB_MAX = 0.9      # H/(2R) 最大推荐值

# 搜索参数
R_SEARCH_MIN = 0.2   # 搜索半径最小值
R_SEARCH_MAX = 15.0  # 搜索半径最大值
R_STEP = 0.01        # 搜索步长

# 计算容差
TOLERANCE = 0.0001
MAX_ITERATIONS = 1000
ZERO_TOL = 1e-9


# ============================================================
# U形断面计算函数
# ============================================================

def calculate_u_hydro_elements(h: float, r: float, f: float) -> Tuple[float, float]:
    """
    计算U形断面水力要素
    
    参数:
        h: 水深 (m)
        r: 内半径 (m)
        f: 直段高度 (m)
    
    返回:
        (过水面积A, 湿周P)
    """
    if h <= 0 or r <= 0:
        return 0.0, 0.0
    
    max_h = f + r  # 最大水深
    
    if h <= r:
        # 水深在半圆部分
        cos_val = max(-1, min(1, 1 - h / r))
        try:
            angle = math.acos(cos_val)
        except:
            angle = PI if cos_val <= -1 else 0
        
        A = r**2 * angle - (r - h) * r * math.sin(angle)
        P = 2 * r * angle
    else:
        # 水深超过半圆
        h_eff = min(h, max_h)
        h_straight = h_eff - r
        
        A = PI * r**2 / 2 + 2 * r * h_straight
        P = PI * r + 2 * h_straight
    
    return A, P


def calculate_u_total_area(h: float, r: float) -> float:
    """
    计算U形断面总面积（槽身面积）
    
    参数:
        h: 总高度 (m)
        r: 内半径 (m)
    
    返回:
        总断面面积 (m²)
    """
    if h <= 0 or r <= 0:
        return 0.0
    
    if h <= r:
        cos_val = max(-1, min(1, 1 - h / r))
        try:
            angle = math.acos(cos_val)
        except:
            angle = PI if cos_val <= -1 else 0
        return r**2 * angle - (r - h) * r * math.sin(angle)
    else:
        return PI * r**2 / 2 + 2 * r * (h - r)


def calculate_u_water_depth(target_Q: float, r: float, n: float, i: float, f: float) -> float:
    """
    反算U形断面水深
    
    参数:
        target_Q: 目标流量 (m³/s)
        r: 内半径 (m)
        n: 糙率
        i: 坡度
        f: 直段高度 (m)
    
    返回:
        水深 (m)，失败返回 -1
    """
    if target_Q <= 0 or r <= 0 or n <= 0 or i <= 0:
        return 0.0 if target_Q == 0 else -1.0
    
    max_h = f + r
    h_low = 0.000001
    h_high = max_h
    
    for _ in range(MAX_ITERATIONS):
        current_h = (h_low + h_high) / 2
        
        A, P = calculate_u_hydro_elements(current_h, r, f)
        
        if P <= 0 or A <= 0:
            Q_calc = 0
        else:
            Rh = A / P
            if Rh >= 0:
                try:
                    Q_calc = A * (1/n) * (Rh ** (2/3)) * (i ** 0.5)
                except:
                    Q_calc = 1e18
            else:
                Q_calc = 0
        
        if Q_calc == 0:
            h_low = current_h
            continue
        
        rel_error = abs(Q_calc - target_Q) / target_Q
        if rel_error < TOLERANCE:
            return current_h
        
        if Q_calc < target_Q:
            h_low = current_h
        else:
            h_high = current_h
        
        if abs(h_high - h_low) < 0.000001:
            if rel_error < TOLERANCE * 100:
                return current_h
            else:
                return -1.0
    
    return -1.0


# ============================================================
# 矩形断面计算函数
# ============================================================

def calculate_rect_hydro_elements(h: float, width: float) -> Tuple[float, float]:
    """
    计算矩形断面水力要素
    
    参数:
        h: 水深 (m)
        width: 槽宽 (m)
    
    返回:
        (过水面积A, 湿周P)
    """
    if h <= 0 or width <= 0:
        return 0.0, 0.0
    
    A = width * h
    P = width + 2 * h
    return A, P


def calculate_rect_hydro_elements_with_chamfer(h: float, width: float, 
                                                chamfer_angle: float, 
                                                chamfer_length: float) -> Tuple[float, float]:
    """
    计算带倒角矩形断面水力要素
    
    参数:
        h: 水深 (m)
        width: 槽宽 (m)
        chamfer_angle: 倒角角度 (度)
        chamfer_length: 倒角底边长 (m)
    
    返回:
        (过水面积A, 湿周P)
    """
    if h <= 0 or width <= 0 or chamfer_angle <= 0 or chamfer_length <= 0:
        return 0.0, 0.0
    
    # 计算倒角几何参数
    chamfer_height = chamfer_length * math.tan(math.radians(chamfer_angle))
    chamfer_hypotenuse = chamfer_length / math.cos(math.radians(chamfer_angle))
    
    if h >= chamfer_height:
        # 水深超过倒角高度：矩形部分 + 倒角已全部淹没
        # A = B*h - 2*(0.5*cl*ch)  = B*h - cl*ch
        # P = (B+2h) - 2*(cl+ch) + 2*hyp
        A = width * h - chamfer_length * chamfer_height
        P = (width + 2 * h) - 2 * (chamfer_length + chamfer_height) + 2 * chamfer_hypotenuse
    else:
        # 水深在倒角区域内（h < chamfer_height）
        # 在高度 y 处有效宽度 w(y) = B - 2*cl*(1 - y/ch)
        # A = ∫₀ʰ w(y) dy = B*h - 2*cl*h + cl*h²/ch
        # P = (B-2*cl) + 2*(h/ch)*hyp  （底部有效宽 + 两侧倒角面长度）
        A = width * h - 2 * chamfer_length * h + chamfer_length * h**2 / chamfer_height
        P = (width - 2 * chamfer_length) + 2 * (h / chamfer_height) * chamfer_hypotenuse
    
    return A, P


def calculate_rect_water_depth(target_Q: float, width: float, n: float, i: float,
                               chamfer_angle: float = 0, chamfer_length: float = 0) -> float:
    """
    反算矩形断面水深
    
    参数:
        target_Q: 目标流量 (m³/s)
        width: 槽宽 (m)
        n: 糙率
        i: 坡度
        chamfer_angle: 倒角角度 (度)，0表示无倒角
        chamfer_length: 倒角底边长 (m)
    
    返回:
        水深 (m)，失败返回 -1
    """
    if target_Q <= 0:
        return 0.0 if target_Q == 0 else -1.0
    if width <= 0 or n <= 0 or i <= 0:
        return -1.0
    
    has_chamfer = chamfer_angle > 0 and chamfer_length > 0
    
    h_low = 0.000001
    h_high = 20.0
    
    for _ in range(MAX_ITERATIONS):
        current_h = (h_low + h_high) / 2
        
        if has_chamfer:
            A, P = calculate_rect_hydro_elements_with_chamfer(current_h, width, 
                                                              chamfer_angle, chamfer_length)
        else:
            A, P = calculate_rect_hydro_elements(current_h, width)
        
        if P <= 0 or A <= 0:
            Q_calc = 0
        else:
            Rh = A / P
            if Rh >= 0:
                try:
                    Q_calc = A * (1/n) * (Rh ** (2/3)) * (i ** 0.5)
                except:
                    Q_calc = 1e18
            else:
                Q_calc = 0
        
        if Q_calc == 0:
            h_low = current_h
            continue
        
        rel_error = abs(Q_calc - target_Q) / target_Q
        if rel_error < TOLERANCE:
            return current_h
        
        if Q_calc < target_Q:
            h_low = current_h
        else:
            h_high = current_h
        
        if abs(h_high - h_low) < 0.000001:
            if rel_error < TOLERANCE * 100:
                return current_h
            else:
                return -1.0
    
    return -1.0


# ============================================================
# 加大流量百分比
# ============================================================

def get_flow_increase_percent(design_Q: float) -> float:
    """
    根据设计流量查找加大流量百分比
    """
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


def round_up_to_2_decimals(value: float) -> float:
    """向上保留2位小数"""
    return math.ceil(value * 100) / 100


# ============================================================
# U形渡槽主计算函数
# ============================================================

def quick_calculate_u(Q: float, n: float, slope_inv: float,
                      v_min: float, v_max: float,
                      manual_R: float = None,
                      manual_increase_percent: float = None) -> Dict[str, Any]:
    """
    U形渡槽快速计算主函数
    
    参数:
        Q: 设计流量 (m³/s)
        n: 糙率
        slope_inv: 坡度倒数 (1/i)
        v_min: 不淤流速 (m/s)
        v_max: 不冲流速 (m/s)
        manual_R: 指定内半径 (m)，可选
        manual_increase_percent: 指定加大百分比 (%)，可选
    
    返回:
        计算结果字典
    """
    result = {
        'success': False,
        'error_message': '',
        'warning_message': '',  # 新增：警告信息（流速超出推荐范围）
        'section_type': 'U形',
        'design_method': '',
        
        # U形断面尺寸
        'R': 0,             # 内半径
        'f': 0,             # 直段高度
        'B': 0,             # 槽宽 = 2R
        'f_R': 0,           # f/R比值
        'H_B': 0,           # 槽高/槽宽比
        
        # 设计工况
        'h_design': 0,      # 设计水深
        'V_design': 0,      # 设计流速
        'A_design': 0,      # 过水面积
        'P_design': 0,      # 湿周
        'R_hyd_design': 0,  # 水力半径
        'Q_calc': 0,        # 计算流量
        
        # 加大流量工况
        'increase_percent': 0,
        'Q_increased': 0,
        'h_increased': 0,
        'V_increased': 0,
        
        # 渡槽尺寸
        'Fb': 0,            # 超高
        'H_total': 0,       # 槽身总高
        'A_total': 0,       # 槽身总面积
    }
    
    # 输入验证
    if Q <= 0:
        result['error_message'] = '流量必须大于0'
        return result
    if n <= 0:
        result['error_message'] = '糙率必须大于0'
        return result
    if slope_inv <= 0:
        result['error_message'] = '坡度倒数必须大于0'
        return result
    if v_min >= v_max:
        result['error_message'] = '不淤流速必须小于不冲流速'
        return result
    
    i = 1.0 / slope_inv
    
    # 加大流量
    if manual_increase_percent is not None and manual_increase_percent >= 0:
        increase_percent = manual_increase_percent
    else:
        increase_percent = get_flow_increase_percent(Q)
    
    Q_increased = Q * (1 + increase_percent / 100)
    
    result['increase_percent'] = increase_percent
    result['Q_increased'] = Q_increased
    
    check_increase = (increase_percent > 0)
    Fb_inc_min = 0.10 if check_increase else 0.0
    
    # 设计变量
    best_R = 0
    best_f = 0
    best_total_area = 1e99
    found_solution = False
    design_method = ''
    
    _design_fb_warning = ''
    
    if manual_R is not None and manual_R > 0:
        # 指定R
        R = manual_R
        design_method = f'给定R={R:.2f}m'
        
        # 初拟f/R=0.4
        initial_fR = 0.4
        f = initial_fR * R
        total_height = f + R
        
        # 计算加大水深
        h_inc = calculate_u_water_depth(Q_increased, R, n, i, f)
        if h_inc <= 0 and FR_MAX * R > f:
            # 初始f/R=0.4不足以通过流量，尝试最大f/R
            f = FR_MAX * R
            total_height = f + R
            h_inc = calculate_u_water_depth(Q_increased, R, n, i, f)
        
        if h_inc > 0:
            # 计算安全超高: max(R/5, 0.1m)
            safety_height = max(R / 5, Fb_inc_min)
            required_height = h_inc + safety_height
            
            # 【规范 9.4.1-2】验证超高：U形断面加大流量时超高不应小于 0.10m
            Fb_min_required = Fb_inc_min
            
            if required_height <= total_height:
                # f/R=0.4满足要求
                total_height = round_up_to_2_decimals(total_height)
                final_fR = (total_height - R) / R
                f = final_fR * R
                
                # 验证超高
                Fb_check = total_height - h_inc
                if Fb_check < Fb_min_required:
                    result['error_message'] = (
                        f"计算失败：不符合规范 9.4.1-2 超高要求。\n\n"
                        f"加大流量工况下超高 Fb = {Fb_check:.3f} m < 最小需求 {Fb_min_required:.2f} m\n"
                        f"根据规范，U形断面加大流量时超高不应小于 0.10m。\n\n"
                        f"建议解决方案：\n"
                        f"1. 增大半径 R\n"
                        f"2. 或者留空半径输入框，由系统自动计算最优半径"
                    )
                    return result
                
                # 【规范 9.4.1-2】验证设计流量工况下的超高：U形断面超高不应小于槽身直径的1/10 (R/5)
                h_design_check = calculate_u_water_depth(Q, R, n, i, f)
                if h_design_check > 0:
                    Fb_design_check = total_height - h_design_check
                    Fb_design_min = R / 5
                    if Fb_design_check < Fb_design_min:
                        _design_fb_warning = (
                            f"【超高警告】设计流量工况下超高 Fb={Fb_design_check:.3f}m < 规范要求 {Fb_design_min:.3f}m（槽径/10），建议增大半径 R 或留空由系统自动计算"
                        )
                
                design_method += f'; 初拟f/R=0.4, 实际f/R={final_fR:.2f}'
            else:
                # 需要调整
                # 考虑超高需求，取较大值
                required_height_with_freeboard = h_inc + Fb_min_required
                total_height = max(required_height, required_height_with_freeboard)
                total_height = round_up_to_2_decimals(total_height)
                final_fR = (total_height - R) / R
                
                if final_fR < FR_MIN:
                    final_fR = FR_MIN
                    f = final_fR * R
                    total_height = f + R
                    total_height = round_up_to_2_decimals(total_height)
                    
                    # 再次验证超高（加大流量工况）
                    Fb_check = total_height - h_inc
                    if Fb_check < Fb_min_required:
                        result['error_message'] = (
                            f"计算失败：指定的半径 R={manual_R:.3f} m 过小，无法同时满足 f/R 比值约束和超高要求。\n\n"
                            f"加大流量工况下超高 Fb = {Fb_check:.3f} m < 最小需求 {Fb_min_required:.2f} m\n\n"
                            f"建议解决方案：\n"
                            f"1. 增大半径\n"
                            f"2. 或者留空半径输入框，由系统自动计算最优半径"
                        )
                        return result
                    
                    # 【规范 9.4.1-2】验证设计流量工况下的超高
                    h_design_check = calculate_u_water_depth(Q, R, n, i, f)
                    if h_design_check > 0:
                        Fb_design_check = total_height - h_design_check
                        Fb_design_min = R / 5
                        if Fb_design_check < Fb_design_min:
                            _design_fb_warning = (
                                f"【超高警告】设计流量工况下超高 Fb={Fb_design_check:.3f}m < 规范要求 {Fb_design_min:.3f}m（槽径/10），建议增大半径 R"
                            )
                elif final_fR > FR_MAX:
                    # 先尝试钳位到推荐最大值
                    clamped_f = FR_MAX * R
                    clamped_total = round_up_to_2_decimals(clamped_f + R)
                    
                    # 检查钳位后是否仍满足全部超高要求
                    h_design_tmp = calculate_u_water_depth(Q, R, n, i, clamped_f)
                    Fb_inc_ok = (clamped_total - h_inc) >= Fb_min_required
                    Fb_design_ok = (h_design_tmp <= 0) or ((clamped_total - h_design_tmp) >= R / 5)
                    
                    if Fb_inc_ok and Fb_design_ok:
                        # 钳位后仍满足超高，采用推荐最大值
                        final_fR = FR_MAX
                        f = clamped_f
                        total_height = clamped_total
                    else:
                        # 钳位到FR_MAX会导致超高不足，保留计算f/R以满足规范强制超高
                        f = total_height - R
                        _design_fb_warning = (
                            f"【提示】f/R = {final_fR:.2f} 略超推荐范围 [{FR_MIN:.1f}, {FR_MAX:.1f}]，"
                            f"为满足规范 9.4.1-2 超高要求而采用。如需降低 f/R，请增大半径 R。"
                        )
                else:
                    f = final_fR * R
                
                # --- 用最终f重新校核设计超高（初始h_inc可能受限于较小f而偏低） ---
                h_recheck = calculate_u_water_depth(Q, R, n, i, f)
                if h_recheck > 0:
                    Fb_recheck = total_height - h_recheck
                    Fb_design_min = R / 5
                    if Fb_recheck < Fb_design_min:
                        total_height = round_up_to_2_decimals(h_recheck + Fb_design_min)
                        final_fR = (total_height - R) / R
                        f = total_height - R
                        if final_fR > FR_MAX:
                            _design_fb_warning = (
                                f"【提示】f/R = {final_fR:.2f} 略超推荐范围 [{FR_MIN:.1f}, {FR_MAX:.1f}]，"
                                f"为满足规范 9.4.1-2 超高要求而采用。如需降低 f/R，请增大半径 R。"
                            )
                
                design_method += f'; 反算f/R={final_fR:.2f}'
            
            best_R = R
            best_f = f
            found_solution = True
    else:
        # 搜索最小面积的R
        design_method = '搜索R(求最小槽身面积)'
        
        # 超高最小需求
        Fb_min_required = Fb_inc_min
        
        R_current = R_SEARCH_MIN
        while R_current <= R_SEARCH_MAX:
            # 初拟f/R=0.4
            initial_fR = 0.4
            f_current = initial_fR * R_current
            total_height_current = f_current + R_current
            
            # 计算加大水深
            h_inc = calculate_u_water_depth(Q_increased, R_current, n, i, f_current)
            if h_inc <= 0 and FR_MAX * R_current > f_current:
                # 初始f/R不足，尝试最大f/R
                f_current = FR_MAX * R_current
                total_height_current = f_current + R_current
                h_inc = calculate_u_water_depth(Q_increased, R_current, n, i, f_current)
            
            if h_inc > 0:
                # 计算安全超高
                safety_height = max(R_current / 5, Fb_inc_min)
                required_height = h_inc + safety_height
                
                # 【规范 9.4.1-2】考虑超高需求
                required_height_with_freeboard = h_inc + Fb_min_required
                required_height = max(required_height, required_height_with_freeboard)
                
                if required_height <= total_height_current:
                    final_fR = initial_fR
                    total_height_current = round_up_to_2_decimals(total_height_current)
                    final_fR = (total_height_current - R_current) / R_current
                    f_current = final_fR * R_current
                else:
                    total_height_current = round_up_to_2_decimals(required_height)
                    final_fR = (total_height_current - R_current) / R_current
                    
                    if final_fR < FR_MIN:
                        final_fR = FR_MIN
                        f_current = final_fR * R_current
                        total_height_current = f_current + R_current
                        total_height_current = round_up_to_2_decimals(total_height_current)
                    elif final_fR > FR_MAX:
                        final_fR = FR_MAX
                        f_current = final_fR * R_current
                        total_height_current = f_current + R_current
                        total_height_current = round_up_to_2_decimals(total_height_current)
                    else:
                        f_current = final_fR * R_current
                
                # 验证超高是否满足（加大流量工况）
                Fb_check = total_height_current - h_inc
                if Fb_check < Fb_min_required:
                    # 不满足超高要求，跳过此R
                    R_current += R_STEP
                    continue
                
                # 【规范 9.4.1-2】验证设计流量工况下的超高：U形断面超高不应小于槽身直径的1/10 (R/5)
                h_design_temp = calculate_u_water_depth(Q, R_current, n, i, f_current)
                if h_design_temp > 0:
                    Fb_design_check = total_height_current - h_design_temp
                    Fb_design_min = R_current / 5
                    if Fb_design_check < Fb_design_min:
                        # 不满足设计流量工况下的超高要求，跳过此R
                        R_current += R_STEP
                        continue
                
                # 检查H/B比
                B_current = 2 * R_current
                actual_HB = total_height_current / B_current if B_current > 0 else 0
                
                if HB_MIN <= actual_HB <= HB_MAX:
                    # 计算总面积
                    total_area = calculate_u_total_area(total_height_current, R_current)
                    
                    if total_area < best_total_area:
                        best_total_area = total_area
                        best_R = R_current
                        best_f = f_current
                        found_solution = True
            
            R_current += R_STEP
        
        if found_solution:
            design_method += f'; 最小面积对应R={best_R:.2f}m'
    
    if not found_solution:
        if manual_R:
            fail_reason = "加大流量工况" if check_increase else "设计流量"
            result['error_message'] = (
                f"计算失败：指定的半径 R={manual_R:.3f} m 过小，无法满足{fail_reason}的要求。\n\n"
                "建议解决方案：\n"
                "1. 增大半径\n"
                "2. 或者留空半径输入框，由系统自动计算最优半径"
            )
        else:
            result['error_message'] = '未找到满足约束条件的设计方案（包括超高要求）'
        return result
    
    # 计算最终结果
    R = best_R
    f = best_f
    B = 2 * R
    total_height = f + R
    total_height = round_up_to_2_decimals(total_height)
    f = total_height - R
    
    # 设计水深
    h_design = calculate_u_water_depth(Q, R, n, i, f)
    if h_design < 0:
        result['error_message'] = '设计水深计算失败'
        return result
    
    # 加大水深
    h_increased = calculate_u_water_depth(Q_increased, R, n, i, f)
    if h_increased < 0:
        result['error_message'] = '加大水深计算失败'
        return result
    
    # 水力要素
    A_design, P_design = calculate_u_hydro_elements(h_design, R, f)
    R_hyd_design = A_design / P_design if P_design > 0 else 0
    V_design = Q / A_design if A_design > 0 else 0
    Q_calc = (1/n) * A_design * (R_hyd_design ** (2/3)) * (i ** 0.5) if R_hyd_design > 0 else 0
    
    # 加大流量水力要素
    A_inc, P_inc = calculate_u_hydro_elements(h_increased, R, f)
    V_increased = Q_increased / A_inc if A_inc > 0 else 0
    
    # 超高（基于加大流量）
    Fb = total_height - h_increased
    
    # 【规范 9.4.1-2】验证设计流量工况下的超高：U形断面超高不应小于槽身直径的1/10
    # 槽身直径 = 2R，因此超高不应小于 2R/10 = R/5
    Fb_design = total_height - h_design
    Fb_design_min_required = R / 5  # 设计流量时的最小超高要求
    
    if Fb_design < Fb_design_min_required:
        if manual_R is not None and manual_R > 0:
            _design_fb_warning = (
                f"【超高警告】设计流量工况下超高 Fb={Fb_design:.3f}m < 规范要求 {Fb_design_min_required:.3f}m（槽径/10），建议增大半径 R"
            )
        else:
            result['error_message'] = (
                f"计算失败：不符合规范 9.4.1-2 设计流量工况下的超高要求。\n\n"
                f"设计流量工况下超高 Fb = {Fb_design:.3f} m < 最小需求 {Fb_design_min_required:.3f} m\n"
                f"根据规范 9.4.1-2，U形断面设计流量时超高不应小于槽身直径的1/10（即2R/10 = R/5 = {Fb_design_min_required:.3f} m）。\n\n"
                f"建议解决方案：增大R或调整f/R比值"
            )
            return result
    
    # 总面积
    A_total = calculate_u_total_area(total_height, R)
    
    # 【规范 9.3.3-4】检查深宽比 H/(2R) 是否在推荐范围内（仅手动指定R时警告）
    actual_HB = total_height / B if B > 0 else 0
    if manual_R is not None and manual_R > 0:
        if actual_HB < HB_MIN or actual_HB > HB_MAX:
            # 反算满足深宽比的近似R范围: H/(2R)=0.7~0.9 → R=H/1.8 ~ H/1.4
            R_suggest_min = total_height / (2 * HB_MAX)  # H/(2×0.9)
            R_suggest_max = total_height / (2 * HB_MIN)  # H/(2×0.7)
            if actual_HB < HB_MIN:
                direction = f"当前 H/(2R) = {actual_HB:.2f} < {HB_MIN:.1f}，槽身偏浅偏宽，R 偏大，建议减小 R"
            else:
                direction = f"当前 H/(2R) = {actual_HB:.2f} > {HB_MAX:.1f}，槽身偏深偏窄，R 偏小，建议增大 R"
            _hb_warning = (
                f"【深宽比警告】{direction}\n"
                f"根据规范 9.3.3-4，梁式渡槽 U 形槽身深宽比 H/(2R) 宜采用 {HB_MIN:.1f}~{HB_MAX:.1f}。\n"
                f"深宽比 = H/(2R) = (R+f)/(2R)，减小 R 使深宽比增大，增大 R 使深宽比减小。\n"
                f"建议 R 取 {R_suggest_min:.2f}~{R_suggest_max:.2f} m（近似值，实际需验证超高）"
            )
            if _design_fb_warning:
                _design_fb_warning += '\n' + _hb_warning
            else:
                _design_fb_warning = _hb_warning
    
    # 【规范 9.4.1-1】检查设计流速是否在推荐范围内
    v_recommended_min = 1.0  # m/s
    v_recommended_max = 2.5  # m/s
    warning_msg = _design_fb_warning
    _sep = '\n' if _design_fb_warning else ''
    
    if V_design < v_recommended_min:
        warning_msg = (
            _design_fb_warning + _sep +
            f"【流速提示】设计流速 V = {V_design:.3f} m/s < 推荐范围 [{v_recommended_min:.1f}, {v_recommended_max:.1f}] m/s\n"
            f"根据规范 9.4.1-1，槽内设计流速宜为 1.0～2.5 m/s。\n"
            f"当前流速过小，可能造成淤积，建议考虑调整断面尺寸。"
        )
    elif V_design > v_recommended_max:
        warning_msg = (
            _design_fb_warning + _sep +
            f"【流速提示】设计流速 V = {V_design:.3f} m/s > 推荐范围 [{v_recommended_min:.1f}, {v_recommended_max:.1f}] m/s\n"
            f"根据规范 9.4.1-1，槽内设计流速宜为 1.0～2.5 m/s。\n"
            f"当前流速过大，可能造成冲刷，建议考虑调整断面尺寸。"
        )
    
    # 填充结果
    result['success'] = True
    result['warning_message'] = warning_msg
    result['design_method'] = design_method
    result['R'] = R
    result['f'] = f
    result['B'] = B
    result['f_R'] = f / R if R > 0 else 0
    result['H_B'] = total_height / B if B > 0 else 0
    result['h_design'] = h_design
    result['V_design'] = V_design
    result['A_design'] = A_design
    result['P_design'] = P_design
    result['R_hyd_design'] = R_hyd_design
    result['Q_calc'] = Q_calc
    result['h_increased'] = h_increased
    result['V_increased'] = V_increased
    result['A_increased'] = A_inc
    result['P_increased'] = P_inc
    result['R_hyd_increased'] = A_inc / P_inc if P_inc > 0 else 0
    result['Fb'] = Fb
    result['H_total'] = total_height
    result['A_total'] = A_total
    
    return result


# ============================================================
# 矩形渡槽主计算函数
# ============================================================

def quick_calculate_rect(Q: float, n: float, slope_inv: float,
                         v_min: float, v_max: float,
                         depth_width_ratio: float = None,
                         chamfer_angle: float = 0,
                         chamfer_length: float = 0,
                         manual_increase_percent: float = None,
                         manual_B: float = None) -> Dict[str, Any]:
    """
    矩形渡槽快速计算主函数
    
    参数:
        Q: 设计流量 (m³/s)
        n: 糙率
        slope_inv: 坡度倒数 (1/i)
        v_min: 不淤流速 (m/s)
        v_max: 不冲流速 (m/s)
        depth_width_ratio: 深宽比 (高度/宽度)，可选，若留空且未指定manual_B则默认0.8
        chamfer_angle: 倒角角度 (度)，0表示无倒角
        chamfer_length: 倒角底边长 (m)
        manual_increase_percent: 指定加大百分比 (%)，可选
        manual_B: 指定槽宽 (m)，可选
    
    返回:
        计算结果字典
    """
    result = {
        'success': False,
        'error_message': '',
        'warning_message': '',  # 新增：警告信息（流速超出推荐范围）
        'section_type': '矩形',
        'design_method': '',
        
        # 矩形断面尺寸
        'B': 0,             # 槽宽
        'H_total': 0,       # 槽高
        'depth_width_ratio': depth_width_ratio if depth_width_ratio else 0.8,
        'has_chamfer': False,
        'chamfer_angle': chamfer_angle,
        'chamfer_length': chamfer_length,
        
        # 设计工况
        'h_design': 0,
        'V_design': 0,
        'A_design': 0,
        'P_design': 0,
        'R_hyd_design': 0,
        'Q_calc': 0,
        
        # 加大流量工况
        'increase_percent': 0,
        'Q_increased': 0,
        'h_increased': 0,
        'V_increased': 0,
        
        # 渡槽尺寸
        'Fb': 0,
        'A_total': 0,
    }
    
    has_chamfer = chamfer_angle > 0 and chamfer_length > 0
    result['has_chamfer'] = has_chamfer
    
    # 输入验证
    if Q <= 0:
        result['error_message'] = '流量必须大于0'
        return result
    if n <= 0:
        result['error_message'] = '糙率必须大于0'
        return result
    if slope_inv <= 0:
        result['error_message'] = '坡度倒数必须大于0'
        return result
    
    i = 1.0 / slope_inv
    
    # 处理深宽比和槽宽B的逻辑
    # 若都留空，则使用默认深宽比0.8
    if depth_width_ratio is None and manual_B is None:
        depth_width_ratio = 0.8
        result['depth_width_ratio'] = depth_width_ratio
    elif depth_width_ratio is not None and depth_width_ratio <= 0:
        result['error_message'] = '深宽比必须大于0'
        return result
    elif manual_B is not None and manual_B <= 0:
        result['error_message'] = '槽宽B必须大于0'
        return result
    
    # 加大流量
    if manual_increase_percent is not None and manual_increase_percent >= 0:
        increase_percent = manual_increase_percent
    else:
        increase_percent = get_flow_increase_percent(Q)
    
    Q_increased = Q * (1 + increase_percent / 100)
    
    result['increase_percent'] = increase_percent
    result['Q_increased'] = Q_increased
    
    check_increase = (increase_percent > 0)
    
    # 搜索合适的矩形尺寸
    found_solution = False
    best_width = 0
    best_height = 0
    
    # 【规范 9.4.1-2】矩形断面超高要求：
    # - 设计流量：超高不应小于 h/12 + 0.05m
    # - 加大流量：超高不应小于 0.10m
    Fb_inc_min = 0.10 if check_increase else 0.0  # 加大流量超高最小值（不勾选时不约束）
    
    if manual_B is not None and manual_B > 0:
        # 用户指定了槽宽B，直接使用该值
        width = manual_B
        
        # 计算设计水深和加大水深
        h_design_calc = calculate_rect_water_depth(Q, width, n, i, chamfer_angle, chamfer_length)
        h_inc = calculate_rect_water_depth(Q_increased, width, n, i, chamfer_angle, chamfer_length)
        
        if h_design_calc > 0 and h_inc > 0:
            # 设计流量超高要求: h/12 + 0.05
            Fb_design_min = h_design_calc / 12 + 0.05
            H_design_required = h_design_calc + Fb_design_min
            
            # 加大流量超高要求: 0.10m
            H_inc_required = h_inc + Fb_inc_min
            
            # 取两者最大值作为总高
            total_height = max(H_design_required, H_inc_required)
            total_height = round_up_to_2_decimals(total_height)
            
            best_width = width
            best_height = total_height
            found_solution = True
            result['depth_width_ratio'] = total_height / width if width > 0 else 0
        else:
            result['error_message'] = f'指定槽宽 B={manual_B:.2f} m 无法计算水深'
            return result
    else:
        # 未指定槽宽B，使用深宽比搜索
        if depth_width_ratio is None:
            depth_width_ratio = 0.8
        result['depth_width_ratio'] = depth_width_ratio
        
        for width in [x * 0.01 for x in range(50, 2001)]:  # 0.5m to 20m
            target_height = width * depth_width_ratio
            
            # 计算设计水深和加大水深
            h_design_calc = calculate_rect_water_depth(Q, width, n, i, chamfer_angle, chamfer_length)
            h_inc = calculate_rect_water_depth(Q_increased, width, n, i, chamfer_angle, chamfer_length)
            
            if h_design_calc > 0 and h_inc > 0:
                # 设计流量超高要求: h/12 + 0.05
                Fb_design_min = h_design_calc / 12 + 0.05
                H_design_required = h_design_calc + Fb_design_min
                
                # 加大流量超高要求: 0.10m
                H_inc_required = h_inc + Fb_inc_min
                
                # 取两者最大值作为总高
                total_height = max(H_design_required, H_inc_required)
                total_height = round_up_to_2_decimals(total_height)
                
                # 检查是否满足深宽比约束
                if total_height <= target_height:
                    best_width = width
                    best_height = total_height
                    found_solution = True
                    break
    
    if not found_solution:
        result['error_message'] = '未找到满足约束条件的矩形尺寸（包括超高要求）'
        return result
    
    # 计算设计水深
    h_design = calculate_rect_water_depth(Q, best_width, n, i, chamfer_angle, chamfer_length)
    if h_design < 0:
        result['error_message'] = '设计水深计算失败'
        return result
    
    # 计算加大水深
    h_increased = calculate_rect_water_depth(Q_increased, best_width, n, i, chamfer_angle, chamfer_length)
    if h_increased < 0:
        result['error_message'] = '加大水深计算失败'
        return result
    
    # 水力要素
    if has_chamfer:
        A_design, P_design = calculate_rect_hydro_elements_with_chamfer(h_design, best_width, 
                                                                         chamfer_angle, chamfer_length)
        A_inc, P_inc = calculate_rect_hydro_elements_with_chamfer(h_increased, best_width,
                                                                   chamfer_angle, chamfer_length)
    else:
        A_design, P_design = calculate_rect_hydro_elements(h_design, best_width)
        A_inc, P_inc = calculate_rect_hydro_elements(h_increased, best_width)
    
    R_hyd_design = A_design / P_design if P_design > 0 else 0
    V_design = Q / A_design if A_design > 0 else 0
    Q_calc = (1/n) * A_design * (R_hyd_design ** (2/3)) * (i ** 0.5) if R_hyd_design > 0 else 0
    
    V_increased = Q_increased / A_inc if A_inc > 0 else 0
    
    # 超高
    Fb = best_height - h_increased
    
    # 总面积
    A_total = best_width * best_height
    
    # 设计方法描述
    actual_ratio = result['depth_width_ratio']
    design_method = f'矩形断面; 深宽比={actual_ratio:.2f}'
    if has_chamfer:
        design_method += f'; 倒角角度={chamfer_angle}°, 倒角底边长={chamfer_length}m'
    
    # 【规范 9.4.1-1】检查设计流速是否在推荐范围内
    v_recommended_min = 1.0  # m/s
    v_recommended_max = 2.5  # m/s
    warning_msg = ''
    
    if V_design < v_recommended_min:
        warning_msg = (
            f"【流速提示】设计流速 V = {V_design:.3f} m/s < 推荐范围 [{v_recommended_min:.1f}, {v_recommended_max:.1f}] m/s\n"
            f"根据规范 9.4.1-1，槽内设计流速宜为 1.0～2.5 m/s。\n"
            f"当前流速过小，可能造成淤积，建议考虑调整断面尺寸。"
        )
    elif V_design > v_recommended_max:
        warning_msg = (
            f"【流速提示】设计流速 V = {V_design:.3f} m/s > 推荐范围 [{v_recommended_min:.1f}, {v_recommended_max:.1f}] m/s\n"
            f"根据规范 9.4.1-1，槽内设计流速宜为 1.0～2.5 m/s。\n"
            f"当前流速过大，可能造成冲刷，建议考虑调整断面尺寸。"
        )
    
    # 填充结果
    result['success'] = True
    result['warning_message'] = warning_msg
    result['design_method'] = design_method
    result['B'] = best_width
    result['H_total'] = best_height
    result['h_design'] = h_design
    result['V_design'] = V_design
    result['A_design'] = A_design
    result['P_design'] = P_design
    result['R_hyd_design'] = R_hyd_design
    result['Q_calc'] = Q_calc
    result['h_increased'] = h_increased
    result['V_increased'] = V_increased
    result['A_increased'] = A_inc
    result['P_increased'] = P_inc
    result['R_hyd_increased'] = A_inc / P_inc if P_inc > 0 else 0
    result['Fb'] = Fb
    result['A_total'] = A_total
    
    return result


# ============================================================
# 测试
# ============================================================

if __name__ == '__main__':
    print("=" * 70)
    print("Aqueduct (Flume) Hydraulic Design Module Test")
    print("=" * 70)
    
    # U形断面测试
    print("\n--- U-shaped Section Test ---")
    result_u = quick_calculate_u(Q=5.0, n=0.014, slope_inv=3000, 
                                  v_min=0.5, v_max=3.0)
    if result_u['success']:
        print(f"Design Method: {result_u['design_method']}")
        print(f"R = {result_u['R']:.3f} m")
        print(f"f = {result_u['f']:.3f} m")
        print(f"B = {result_u['B']:.3f} m")
        print(f"f/R = {result_u['f_R']:.3f}")
        print(f"H/B = {result_u['H_B']:.3f}")
        print(f"H_total = {result_u['H_total']:.3f} m")
        print(f"h_design = {result_u['h_design']:.3f} m")
        print(f"V_design = {result_u['V_design']:.3f} m/s")
        print(f"h_increased = {result_u['h_increased']:.3f} m")
        print(f"Fb = {result_u['Fb']:.3f} m")
    else:
        print(f"Failed: {result_u['error_message']}")
    
    # 矩形断面测试
    print("\n--- Rectangular Section Test ---")
    result_rect = quick_calculate_rect(Q=5.0, n=0.014, slope_inv=3000,
                                        v_min=0.5, v_max=3.0,
                                        depth_width_ratio=0.8)
    if result_rect['success']:
        print(f"Design Method: {result_rect['design_method']}")
        print(f"B = {result_rect['B']:.3f} m")
        print(f"H_total = {result_rect['H_total']:.3f} m")
        print(f"h_design = {result_rect['h_design']:.3f} m")
        print(f"V_design = {result_rect['V_design']:.3f} m/s")
        print(f"h_increased = {result_rect['h_increased']:.3f} m")
        print(f"Fb = {result_rect['Fb']:.3f} m")
    else:
        print(f"Failed: {result_rect['error_message']}")
    
    print("\n" + "=" * 70)
    print("Test completed")
