# -*- coding: utf-8 -*-
"""
矩形暗涵水力设计计算模块

本模块提供矩形暗涵断面的水力计算功能，从隧洞设计.py分离而来。

支持功能：
1. 矩形暗涵水力要素计算
2. 全局经济最优断面自动搜索与计算
3. 净空约束验证

设计说明：
- 当底宽（B）和宽深比（B/h）同时为空时，自动搜索全局经济最优断面（B×H最小）
- 高宽比H/B（或B/H）建议不超过1.2（提醒，不作为强制约束），参考 GB 50288-2018 第11.2.5条

版本: V1.0
"""

import math
from typing import Dict, Any, Tuple

# ============================================================
# 常量定义
# ============================================================

PI = 3.14159265358979

# 矩形暗涵尺寸约束
MIN_WIDTH_RECT = 0.2        # 最小宽度 (m)
MIN_HEIGHT_RECT = 0.5       # 最小高度 (m)
BH_RATIO_MIN_RECT = 0.5     # 推荐宽深比下限 (B/h)
BH_RATIO_MAX_RECT = 2.5     # 推荐宽深比上限 (B/h)
OPTIMAL_BH_RATIO = 2.0      # 保留用于向后兼容（不再为最优断面的搜索目标）
HB_RATIO_LIMIT = 1.2        # 高宽比限值H/B（或B/H）一般不超过1.2

# 净空要求 - 矩形暗涵（参考《灌溉与排水工程设计标准》 GB 50288-2018）
MIN_FREEBOARD_PCT_RECT = 0.10      # 矩形暗涵最小净空面积百分比 (10%)
MAX_FREEBOARD_PCT_RECT = 0.30      # 矩形暗涵最大净空面积百分比 (30%)
MIN_FREEBOARD_HGT_RECT = 0.4       # 矩形暗涵最小净空高度 (m)

# 计算参数
SOLVER_TOLERANCE = 0.0001
MAX_ITERATIONS = 100
DIM_INCREMENT = 0.01


# ============================================================
# 加大流量百分比
# ============================================================

def get_flow_increase_percent(design_Q: float) -> float:
    """
    根据设计流量获取加大流量百分比
    
    参数:
        design_Q: 设计流量 (m³/s)
    
    返回:
        加大流量百分比 (%)
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


def get_flow_increase_percent_rect(design_Q: float) -> float:
    """矩形暗涵加大流量百分比"""
    return get_flow_increase_percent(design_Q)


# ============================================================
# 净空高度计算
# ============================================================

def get_required_freeboard_height_rect(H_total: float) -> float:
    """
    计算矩形暗涵所需最小净空高度
    
    根据《灌溉与排水工程设计标准》GB 50288-2018 第11.2.5条 表11.2.5：
    - 在任何情况下，净空高度均不得小于0.4米
    - 矩形涵洞进口净高D≤3m时，净空高度应不小于D/6
    - 矩形涵洞进口净高D>3m时，净空高度应不小于0.5米
    
    参数:
        H_total: 涵洞内侧总高度 (m)
    
    返回:
        所需最小净空高度 (m)
    """
    if H_total <= 3.0:
        # H≤3m时，净空高度≥H/6，但不小于0.4m
        return max(MIN_FREEBOARD_HGT_RECT, H_total / 6.0)
    else:
        # H>3m时，净空高度≥0.5m
        return 0.5


# ============================================================
# H 解析计算（净空约束）
# ============================================================

def compute_H_min_optimal(h_inc: float, B: float) -> float:
    """
    给定加大流量工况水深 h_inc 和底宽 B，解析计算满足全部净空约束的最小洞高 H。

    约束来源：
      1. PA_inc ≥ 10%  → H ≥ h_inc / 0.9
      2. 净空高度要求（分段，消除 H/6 的循环依赖）
      3. 最小洞高常量   → H ≥ MIN_HEIGHT_RECT
    注：H/B 和 B/H 为建议值（≤1.2），不作为 H_min 的强制约束
    """
    # 各约束下限
    H_pa   = h_inc / 0.9                        # PA_inc ≥ 10%
    H_abs  = MIN_HEIGHT_RECT                      # 绝对最小值

    # 净空高度约束（分段处理 H/6 的循环依赖）
    # 初始假设：0.4m 控制
    H_clear = h_inc + 0.4
    # 若此时 H/6 > 0.4（即 H > 2.4m），则 H/6 接管
    # H - h_inc ≥ H/6  →  (5/6)H ≥ h_inc  →  H ≥ 1.2 × h_inc
    if H_clear > 2.4 and H_clear <= 3.0:
        H_clear = max(H_clear, 1.2 * h_inc)
    # 若 H > 3m，0.5m 接管
    if H_clear > 3.0:
        H_clear = max(H_clear, h_inc + 0.5)

    return max(H_pa, H_clear, H_abs)


def compute_H_max_optimal(h_inc: float, B: float) -> float:
    """
    给定加大流量工况水深 h_inc 和底宽 B，解析计算满足净空约束的最大洞高 H。

    约束来源：
      1. PA_inc ≤ 30%  → H ≤ h_inc / 0.7
    注：H/B ≤ 1.2 为建议值，不作为 H_max 的强制约束
    """
    H_pa_max = h_inc / 0.7        # PA_inc ≤ 30%
    return H_pa_max


# ============================================================
# 矩形暗涵水力计算
# ============================================================

def calculate_rectangular_outputs(B: float, H: float, h: float, n: float, slope: float) -> Dict[str, float]:
    """
    计算矩形暗涵水力要素
    
    参数:
        B: 底宽 (m)
        H: 涵洞内侧总高度 (m)
        h: 水深 (m)
        n: 糙率
        slope: 水力坡降 (i)
    
    返回:
        包含以下键的字典:
        - A: 过水面积 (m²)
        - P: 湿周 (m)
        - R_hyd: 水力半径 (m)
        - V: 流速 (m/s)
        - Q: 流量 (m³/s)
        - A_total: 总断面面积 (m²)
        - freeboard_pct: 净空面积百分比 (%)
        - freeboard_hgt: 净空高度 (m)
    """
    if B <= 0 or H <= 0 or h <= 0:
        return {'A': 0, 'P': 0, 'R_hyd': 0, 'V': 0, 'Q': 0, 
                'A_total': 0, 'freeboard_pct': 100, 'freeboard_hgt': 0}
    
    h = min(h, H)
    A = B * h
    P = B + 2 * h
    R_hyd = A / P if P > 0 else 0
    
    if R_hyd > 0 and n > 0 and slope >= 0:
        Q_calc = (1/n) * A * (R_hyd ** (2/3)) * (slope ** 0.5)
    else:
        Q_calc = 0
    
    V = Q_calc / A if A > 0 else 0
    A_total = B * H
    freeboard_pct = (A_total - A) / A_total * 100 if A_total > 0 else 100
    freeboard_hgt = H - h
    
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


def solve_water_depth_rectangular(B: float, H: float, n: float, slope: float, Q_target: float) -> Tuple[float, bool]:
    """
    求解矩形暗涵水深（二分法）
    
    参数:
        B: 底宽 (m)
        H: 涵洞内侧总高度 (m)
        n: 糙率
        slope: 水力坡降 (i)
        Q_target: 目标流量 (m³/s)
    
    返回:
        (水深, 是否求解成功)
    """
    if B <= 0 or H <= 0 or n <= 0 or slope < 0 or Q_target <= 0.0000001:
        return (0.0, True) if Q_target <= 0.0000001 else (0.0, False)
    
    h_low = 0.00001
    h_high = H
    
    h_mid = 0
    for _ in range(MAX_ITERATIONS):
        h_mid = (h_low + h_high) / 2
        if h_mid <= h_low or h_mid >= h_high:
            break
        
        outputs = calculate_rectangular_outputs(B, H, h_mid, n, slope)
        Q_mid = outputs['Q']
        
        if Q_mid > 0 and abs(Q_mid - Q_target) / Q_target < SOLVER_TOLERANCE:
            return (h_mid, True)
        
        if Q_mid < Q_target:
            h_low = h_mid
        else:
            h_high = h_mid
    
    outputs = calculate_rectangular_outputs(B, H, h_mid, n, slope)
    if outputs['Q'] > 0 and abs(outputs['Q'] - Q_target) / Q_target < SOLVER_TOLERANCE * 1.5:
        return (h_mid, True)
    
    return (h_mid, False)


# ============================================================
# β 参数化解析解与加大工况快速求解（经济最优断面专用）
# ============================================================

def _h_design_from_beta(beta: float, Q: float, n: float, slope: float) -> float:
    """
    β 参数化解析解：给定宽深比 β=B/h，直接计算设计水深（无需迭代）。
    推导：Q=(1/n)·β^(5/3)/(β+2)^(2/3)·h^(8/3)·√i
    解得：h=(Q·n/√i·(β+2)^(2/3)/β^(5/3))^(3/8)
    """
    if beta <= 0 or Q <= 0 or n <= 0 or slope <= 0:
        return 0.0
    try:
        return (Q * n / math.sqrt(slope) * ((beta + 2.0) ** (2.0/3.0)) / (beta ** (5.0/3.0))) ** (3.0/8.0)
    except (ValueError, ZeroDivisionError, OverflowError):
        return 0.0


def _solve_h_inc_fast(Q_inc: float, B: float, n: float, slope: float,
                      h_init: float = None) -> Tuple[float, bool]:
    """
    快速求解加大工况水深（热启动割线法 + 二分回退）。

    参数:
        Q_inc:  加大流量 (m³/s)
        B:      底宽 (m)
        n:      糙率
        slope:  水力坡降 (i)
        h_init: 热启动初值（上一个 β 的 h_inc），None 表示无初值
    返回:
        (h_inc, success)
    """
    if B <= 0 or Q_inc <= 0 or n <= 0 or slope <= 0:
        return 0.0, False

    def _Q(h: float) -> float:
        if h <= 0:
            return 0.0
        A = B * h
        P = B + 2.0 * h
        R = A / P
        return (1.0 / n) * A * (R ** (2.0/3.0)) * (slope ** 0.5)

    def _f(h: float) -> float:
        return _Q(h) - Q_inc

    # ── 割线法（热启动）──
    if h_init is not None and h_init > 0:
        x0 = max(h_init * 0.9, 1e-5)
        x1 = h_init
        try:
            for _ in range(25):
                f0, f1 = _f(x0), _f(x1)
                denom = f1 - f0
                if abs(denom) < 1e-15:
                    break
                x2 = x1 - f1 * (x1 - x0) / denom
                if x2 <= 0:
                    break
                if abs(x2 - x1) < SOLVER_TOLERANCE and abs(_f(x2)) / Q_inc < SOLVER_TOLERANCE * 2:
                    return (x2, True)
                x0, x1 = x1, x2
            if x1 > 0 and abs(_f(x1)) / Q_inc < SOLVER_TOLERANCE * 2:
                return (x1, True)
        except (ValueError, ZeroDivisionError, OverflowError):
            pass

    # ── 二分回退（倍增构造括号）──
    h_low = 1e-5
    h_high = (h_init * 1.5) if (h_init and h_init > 0) else max(B, 1.0)
    for _ in range(30):
        try:
            if _Q(h_high) >= Q_inc:
                break
        except Exception:
            pass
        h_high *= 2.0
        if h_high > 500:
            return 0.0, False

    if _Q(h_low) > Q_inc or _Q(h_high) < Q_inc:
        return 0.0, False

    for _ in range(MAX_ITERATIONS):
        h_mid = (h_low + h_high) / 2.0
        if h_mid <= h_low or h_mid >= h_high:
            break
        fm = _f(h_mid)
        if abs(fm) / Q_inc < SOLVER_TOLERANCE:
            return (h_mid, True)
        if fm < 0:
            h_low = h_mid
        else:
            h_high = h_mid

    h_mid = (h_low + h_high) / 2.0
    if abs(_f(h_mid)) / Q_inc < SOLVER_TOLERANCE * 1.5:
        return (h_mid, True)
    return (h_mid, False)


# ============================================================
# 主计算函数
# ============================================================

def quick_calculate_rectangular_culvert(Q: float, n: float, slope_inv: float,
                                         v_min: float, v_max: float,
                                         target_HB_ratio: float = None,
                                         target_BH_ratio: float = None,
                                         manual_B: float = None,
                                         manual_increase_percent: float = None) -> Dict[str, Any]:
    """
    矩形暗涵快速计算
    
    参数:
        Q: 设计流量 (m³/s)
        n: 糙率
        slope_inv: 水力坡降倒数 (1/i)
        v_min: 最小流速 (m/s)
        v_max: 最大流速 (m/s)
        target_HB_ratio: 目标高宽比 H/B (可选，指定后程序搜索满足约束的最小 B，H = target_HB_ratio × B)
        target_BH_ratio: 目标宽深比 B/h (可选，优先使用)
        manual_B: 指定底宽 (m) (可选)
        manual_increase_percent: 指定加大流量百分比 (可选)
    
    说明:
        - 当同时留空底宽（manual_B）和宽深比（target_BH_ratio）时，
          自动搜索全局经济最优断面（B×H 最小，β 无硬约束）
        - 高宽比限值H/B（或B/H）一般不超过1.2
    
    返回:
        包含计算结果的字典
    """
    result = {
        'success': False,
        'error_message': '',
        'section_type': '矩形暗涵',
        'design_method': '',
        'is_optimal_section': False,  # 是否为经济最优断面
        'B': 0,
        'H': 0,
        'HB_ratio': 0,
        'BH_ratio': 0,
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
        # 净空验证详情
        'fb_min_required': 0,
        'fb_check_passed': False,
        'fb_check_details': '',
    }
    
    if Q <= 0 or n <= 0 or slope_inv <= 0:
        result['error_message'] = '输入参数无效'
        return result

    # 验证通过后再计算坡度，避免除零崩溃
    slope = 1.0 / slope_inv
    
    # 加大流量
    if manual_increase_percent is not None and manual_increase_percent >= 0:
        increase_percent = manual_increase_percent
    else:
        increase_percent = get_flow_increase_percent_rect(Q)
    
    Q_increased = Q * (1 + increase_percent / 100)
    result['increase_percent'] = increase_percent
    result['Q_increased'] = Q_increased
    
    # 判断是否使用经济最优断面
    # 当同时未指定底宽、宽深比和高宽比时，自动搜索全局经济最优断面（B×H 最小）
    use_optimal_section = (manual_B is None or manual_B <= 0) and (target_BH_ratio is None or target_BH_ratio <= 0) and (target_HB_ratio is None or target_HB_ratio <= 0)
    
    # 判断是否指定了目标宽深比
    use_target_BH_ratio = target_BH_ratio is not None and target_BH_ratio > 0
    
    # 判断是否指定了目标高宽比
    use_target_HB_ratio = target_HB_ratio is not None and target_HB_ratio > 0
    
    # 搜索最优解
    best_found = False
    best_B = 0
    best_H = 0
    best_A_total = 1e99
    best_BH_diff = 1e99  # 宽深比偏差
    
    if manual_B and manual_B > 0:
        B_start = manual_B
        B_end = manual_B + 0.01
    else:
        B_start = MIN_WIDTH_RECT
        B_end = 20.0
    
    # 经济最优断面模式（全部留空）
    # 算法：遍历宽深比 β → 解析得 h_design/B → 热启动快速求 h_inc → 解析求 H_min → 全局面积最小
    if use_optimal_section:
        result['is_optimal_section'] = True

        def _scan_beta_range(b_start, b_end, b_step, h_inc_init=None):
            """扫描 β 区间，返回 (best_B, best_H, best_A, best_beta, found)"""
            bB = 0.0; bH = 0.0; bA = 1e99; b_beta = 0.0; bfound = False
            prev_h_inc = h_inc_init
            beta = b_start
            while beta <= b_end + b_step * 0.5:
                # 1. 解析计算 h_design 和 B
                h_des = _h_design_from_beta(beta, Q, n, slope)
                if h_des <= 0:
                    beta += b_step; continue
                B_t = beta * h_des
                if B_t < MIN_WIDTH_RECT:
                    beta += b_step; continue

                # 2. 流速约束
                V_des = Q / (B_t * h_des)
                if V_des < v_min or V_des > v_max:
                    beta += b_step; continue

                # 3. 加大工况水深（热启动快速求解）
                if increase_percent > 0:
                    h_inc_t, ok_i = _solve_h_inc_fast(Q_increased, B_t, n, slope, prev_h_inc)
                    if not ok_i or h_inc_t <= h_des:
                        beta += b_step; continue
                    prev_h_inc = h_inc_t
                else:
                    h_inc_t = h_des  # 无加大流量时，加大水深 = 设计水深

                # 4. 解析求 H_min / H_max
                H_mn = compute_H_min_optimal(h_inc_t, B_t)
                H_mx = compute_H_max_optimal(h_inc_t, B_t)
                if H_mn > H_mx:
                    beta += b_step; continue
                H_t = H_mn

                # 5. 水深须在洞高以内
                if h_des >= H_t or h_inc_t >= H_t:
                    beta += b_step; continue

                # 6. 净空验证
                req_fb = get_required_freeboard_height_rect(H_t)
                if increase_percent > 0:
                    out_inc = calculate_rectangular_outputs(B_t, H_t, h_inc_t, n, slope)
                    if out_inc['freeboard_hgt'] < req_fb:
                        beta += b_step; continue
                    if not (MIN_FREEBOARD_PCT_RECT * 100
                            <= out_inc['freeboard_pct']
                            <= MAX_FREEBOARD_PCT_RECT * 100):
                        beta += b_step; continue
                    if out_inc['V'] > v_max:
                        beta += b_step; continue
                out_des = calculate_rectangular_outputs(B_t, H_t, h_des, n, slope)
                if out_des['freeboard_pct'] < MIN_FREEBOARD_PCT_RECT * 100:
                    beta += b_step; continue
                if increase_percent == 0 and out_des['freeboard_pct'] > MAX_FREEBOARD_PCT_RECT * 100:
                    beta += b_step; continue
                if out_des['freeboard_hgt'] < req_fb:
                    beta += b_step; continue

                # 7. 全局最小面积记录（不提前 break）
                A_t = B_t * H_t
                if A_t < bA:
                    bA = A_t; bB = B_t; bH = H_t; b_beta = beta; bfound = True
                beta += b_step
            return bB, bH, bA, b_beta, bfound

        # 阶段1：粗扫 β ∈ [BH_RATIO_MIN_RECT, BH_RATIO_MAX_RECT]，步长 0.02
        c_B, c_H, c_A, c_beta, c_found = _scan_beta_range(
            BH_RATIO_MIN_RECT, BH_RATIO_MAX_RECT, 0.02)

        if c_found:
            # 阶段2：在粗扫最优 β 附近细扫，步长 0.002
            f_B, f_H, f_A, _, f_found = _scan_beta_range(
                max(BH_RATIO_MIN_RECT, c_beta - 0.06),
                min(BH_RATIO_MAX_RECT, c_beta + 0.06),
                0.002)
            if f_found:
                best_B = f_B; best_H = f_H; best_A_total = f_A; best_found = True
            else:
                best_B = c_B; best_H = c_H; best_A_total = c_A; best_found = True
        else:
            # 扩展 β 范围 [0.3, 3.5] 重试
            c_B, c_H, c_A, c_beta, c_found = _scan_beta_range(0.3, 3.5, 0.02)
            if c_found:
                f_B, f_H, f_A, _, f_found = _scan_beta_range(
                    max(0.3, c_beta - 0.06), min(3.5, c_beta + 0.06), 0.002)
                best_B = f_B if f_found else c_B
                best_H = f_H if f_found else c_H
                best_A_total = f_A if f_found else c_A
                best_found = True

        # 如果仍未找到，退回到普通搜索模式
        if not best_found:
            result['is_optimal_section'] = False
            use_optimal_section = False
    
    # 非经济最优断面模式，或经济最优搜索失败后退回到普通搜索模式
    if not best_found:
        if use_target_HB_ratio:
            # H/B 指定模式：对每个候选 B，令 H = target_HB_ratio × B
            B = B_start
            while B < B_end:
                H_trial = round(target_HB_ratio * B, 4)
                if H_trial < MIN_HEIGHT_RECT:
                    B += DIM_INCREMENT
                    continue

                h_design, success_design = solve_water_depth_rectangular(B, H_trial, n, slope, Q)
                if not success_design or h_design >= H_trial:
                    B += DIM_INCREMENT
                    continue

                outputs_design = calculate_rectangular_outputs(B, H_trial, h_design, n, slope)

                if outputs_design['V'] < v_min or outputs_design['V'] > v_max:
                    B += DIM_INCREMENT
                    continue

                req_fb_hgt = get_required_freeboard_height_rect(H_trial)
                if outputs_design['freeboard_hgt'] < req_fb_hgt:
                    B += DIM_INCREMENT
                    continue
                if outputs_design['freeboard_pct'] < MIN_FREEBOARD_PCT_RECT * 100:
                    B += DIM_INCREMENT
                    continue
                if increase_percent == 0 and outputs_design['freeboard_pct'] > MAX_FREEBOARD_PCT_RECT * 100:
                    B += DIM_INCREMENT
                    continue

                if increase_percent > 0:
                    h_inc, success_inc = solve_water_depth_rectangular(B, H_trial, n, slope, Q_increased)
                    if not success_inc or h_inc >= H_trial:
                        B += DIM_INCREMENT
                        continue

                    outputs_inc = calculate_rectangular_outputs(B, H_trial, h_inc, n, slope)

                    if outputs_inc['V'] > v_max:
                        B += DIM_INCREMENT
                        continue

                    # 加大流量工况净空验证（关键约束）
                    if not (outputs_inc['freeboard_hgt'] >= req_fb_hgt and
                            outputs_inc['freeboard_pct'] >= MIN_FREEBOARD_PCT_RECT * 100 and
                            outputs_inc['freeboard_pct'] <= MAX_FREEBOARD_PCT_RECT * 100):
                        B += DIM_INCREMENT
                        continue

                A_total = outputs_design['A_total']
                if A_total < best_A_total:
                    best_A_total = A_total
                    best_B = B
                    best_H = H_trial
                    best_found = True

                B += DIM_INCREMENT
        else:
            # 宽深比搜索范围
            if use_target_BH_ratio:
                bh_ratio_start = max(BH_RATIO_MIN_RECT, target_BH_ratio - 0.2)
                bh_ratio_end = min(BH_RATIO_MAX_RECT, target_BH_ratio + 0.2)
            else:
                bh_ratio_start = BH_RATIO_MIN_RECT
                bh_ratio_end = BH_RATIO_MAX_RECT
            bh_ratio_step = 0.01

            B = B_start
            while B < B_end:
                bh_ratio = bh_ratio_start
                while bh_ratio <= bh_ratio_end:
                    h_target = B / bh_ratio

                    req_fb_hgt = get_required_freeboard_height_rect(h_target * 1.5)
                    H_trial = max(MIN_HEIGHT_RECT, h_target + req_fb_hgt + 0.1)

                    h_design, success_design = solve_water_depth_rectangular(B, H_trial, n, slope, Q)

                    if not success_design or h_design >= H_trial:
                        bh_ratio += bh_ratio_step
                        continue

                    actual_BH_ratio = B / h_design if h_design > 0 else 0

                    if actual_BH_ratio < BH_RATIO_MIN_RECT or actual_BH_ratio > BH_RATIO_MAX_RECT:
                        bh_ratio += bh_ratio_step
                        continue

                    outputs_design = calculate_rectangular_outputs(B, H_trial, h_design, n, slope)

                    if outputs_design['V'] < v_min or outputs_design['V'] > v_max:
                        bh_ratio += bh_ratio_step
                        continue

                    req_fb_hgt = get_required_freeboard_height_rect(H_trial)
                    if outputs_design['freeboard_hgt'] < req_fb_hgt:
                        bh_ratio += bh_ratio_step
                        continue
                    if outputs_design['freeboard_pct'] < MIN_FREEBOARD_PCT_RECT * 100:
                        bh_ratio += bh_ratio_step
                        continue
                    if increase_percent == 0 and outputs_design['freeboard_pct'] > MAX_FREEBOARD_PCT_RECT * 100:
                        bh_ratio += bh_ratio_step
                        continue

                    if increase_percent > 0:
                        h_inc, success_inc = solve_water_depth_rectangular(B, H_trial, n, slope, Q_increased)

                        if not success_inc or h_inc >= H_trial:
                            bh_ratio += bh_ratio_step
                            continue

                        outputs_inc = calculate_rectangular_outputs(B, H_trial, h_inc, n, slope)

                        if outputs_inc['V'] > v_max:
                            bh_ratio += bh_ratio_step
                            continue

                        # 加大流量工况净空验证（关键约束）
                        if not (outputs_inc['freeboard_hgt'] >= req_fb_hgt and
                                outputs_inc['freeboard_pct'] >= MIN_FREEBOARD_PCT_RECT * 100 and
                                outputs_inc['freeboard_pct'] <= MAX_FREEBOARD_PCT_RECT * 100):
                            bh_ratio += bh_ratio_step
                            continue

                    A_total = outputs_design['A_total']

                    if use_target_BH_ratio:
                        BH_diff = abs(actual_BH_ratio - target_BH_ratio)
                        if BH_diff < best_BH_diff or (abs(BH_diff - best_BH_diff) < 0.01 and A_total < best_A_total):
                            best_BH_diff = BH_diff
                            best_A_total = A_total
                            best_B = B
                            best_H = H_trial
                            best_found = True
                    else:
                        if A_total < best_A_total:
                            best_A_total = A_total
                            best_B = B
                            best_H = H_trial
                            best_found = True

                    bh_ratio += bh_ratio_step

                B += DIM_INCREMENT
    
    if not best_found:
        if manual_B:
            if increase_percent > 0:
                result['error_message'] = (
                    f"计算失败：指定的底宽 B={manual_B:.3f} m 无法满足要求。\n\n"
                    "可能原因及建议：\n"
                    "1. 底宽过小，导致加大流量工况下无净空或水深超出洞高；\n"
                    "2. 流速超出限制；\n"
                    "建议：增大底宽，或者留空底宽由系统自动计算。"
                )
            else:
                result['error_message'] = (
                    f"计算失败：指定的底宽 B={manual_B:.3f} m 无法满足要求。\n\n"
                    "可能原因及建议：\n"
                    "1. 底宽过小，导致设计流量工况下净空或水深不满足要求；\n"
                    "2. 流速超出限制；\n"
                    "建议：增大底宽，或者留空底宽由系统自动计算。"
                )
        elif use_target_HB_ratio:
            result['error_message'] = (
                f"计算失败：指定的高宽比 H/B={target_HB_ratio:.2f} 无法找到满足要求的断面尺寸。\n\n"
                "可能原因：\n"
                "1. 在此 H/B 下净空约束与流速约束无法同时满足；\n"
                "2. H/B 过小导致涌洞高度过低，净空不足；\n"
                "建议：适当增大 H/B，或留空由系统自动计算。"
            )
        elif use_optimal_section:
            result['error_message'] = (
                '计算失败：自动搜索经济最优断面未找到满足要求的断面尺寸。\n\n'
                '可能原因：\n'
                '1. 流速约束过严；\n'
                '2. 净空约束无法满足；\n'
                '建议：适当放宽流速范围，或指定宽深比/底宽。'
            )
        else:
            result['error_message'] = '计算失败：未找到满足流速及净空要求的矩形断面尺寸。'
        return result
    
    # 最终计算
    B = best_B
    H = best_H
    
    h_design, _ = solve_water_depth_rectangular(B, H, n, slope, Q)
    h_inc, _ = solve_water_depth_rectangular(B, H, n, slope, Q_increased)
    
    outputs_design = calculate_rectangular_outputs(B, H, h_design, n, slope)
    outputs_inc = calculate_rectangular_outputs(B, H, h_inc, n, slope)
    
    # 计算净空验证详情（使用矩形暗涵专用约束）
    req_fb_hgt = get_required_freeboard_height_rect(H)
    fb_hgt_design = outputs_design['freeboard_hgt']
    fb_pct_design = outputs_design['freeboard_pct']
    fb_hgt_inc = outputs_inc['freeboard_hgt']
    fb_pct_inc = outputs_inc['freeboard_pct']
    
    # 生成净空验证详情文字
    fb_details = []
    fb_details.append(f"涵洞高度 H = {H:.2f}m")
    if H <= 3.0:
        fb_details.append(f"H≤3m，净空高度应≥H/6 = {H/6:.3f}m，且≥0.4m")
        fb_details.append(f"要求净空高度≥{req_fb_hgt:.3f}m")
    else:
        fb_details.append(f"H>3m，净空高度应≥0.5m")
        fb_details.append(f"要求净空高度≥{req_fb_hgt:.3f}m")
    fb_details.append(f"净空面积应为总面积的10%~30%")
    
    fb_check_passed = (fb_hgt_inc >= req_fb_hgt - 1e-3 and
                       MIN_FREEBOARD_PCT_RECT * 100 - 0.1 <= fb_pct_inc <= MAX_FREEBOARD_PCT_RECT * 100 + 0.1)
    
    result['success'] = True
    
    # 设计方法标识
    if use_optimal_section:
        result['design_method'] = f'经济最优断面; B={B:.2f}m, H={H:.2f}m'
        result['is_optimal_section'] = True
    elif use_target_HB_ratio:
        result['design_method'] = f'指定高宽比; B={B:.2f}m, H={H:.2f}m (H/B={target_HB_ratio:.2f})'
        result['is_optimal_section'] = False
    else:
        result['design_method'] = f'矩形暗涵; B={B:.2f}m, H={H:.2f}m'
        result['is_optimal_section'] = False
    
    result['B'] = B
    result['H'] = H
    HB_ratio_val = H / B if B > 0 else 0
    BH_box_ratio_val = B / H if H > 0 else 0
    result['HB_ratio'] = HB_ratio_val
    result['BH_ratio'] = B / h_design if h_design > 0 else 0
    result['hb_ratio_ok'] = (HB_ratio_val <= HB_RATIO_LIMIT)         # H/B ≤ 1.2 建议值
    result['bh_box_ratio_ok'] = (BH_box_ratio_val <= HB_RATIO_LIMIT) # B/H ≤ 1.2 建议值
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
    result['freeboard_pct_inc'] = outputs_inc['freeboard_pct']
    result['freeboard_hgt_inc'] = outputs_inc['freeboard_hgt']
    result['A_total'] = outputs_design['A_total']
    
    # 净空验证结果
    result['fb_min_required'] = req_fb_hgt
    result['fb_check_passed'] = fb_check_passed
    result['fb_check_details'] = '\n'.join(fb_details)
    
    return result


# ============================================================
# 测试
# ============================================================

if __name__ == '__main__':
    print("=" * 70)
    print("矩形暗涵水力设计计算模块测试")
    print("=" * 70)
    
    # 矩形暗涵测试 - 经济最优断面（留空B和宽深比）
    print("\n--- 测试1: 经济最优断面（全部留空）---")
    result = quick_calculate_rectangular_culvert(
        Q=5.0, n=0.014, slope_inv=3000, 
        v_min=0.5, v_max=3.0
    )
    if result['success']:
        print(f"B = {result['B']:.2f} m")
        print(f"H = {result['H']:.2f} m")
        print(f"h设计 = {result['h_design']:.3f} m")
        print(f"V设计 = {result['V_design']:.3f} m/s")
        print(f"宽深比 β = {result['BH_ratio']:.2f}")
        print(f"是否经济最优断面: {result['is_optimal_section']}")
        print(f"净空验证: {result['fb_check_passed']}")
    else:
        print(f"失败: {result['error_message']}")
    
    # 矩形暗涵测试 - 指定底宽
    print("\n--- 测试2: 指定底宽 B=2.0m ---")
    result = quick_calculate_rectangular_culvert(
        Q=5.0, n=0.014, slope_inv=3000, 
        v_min=0.5, v_max=3.0,
        manual_B=2.0
    )
    if result['success']:
        print(f"B = {result['B']:.2f} m")
        print(f"H = {result['H']:.2f} m")
        print(f"h设计 = {result['h_design']:.3f} m")
        print(f"V设计 = {result['V_design']:.3f} m/s")
        print(f"宽深比 β = {result['BH_ratio']:.2f}")
    else:
        print(f"失败: {result['error_message']}")
    
    # 矩形暗涵测试 - 指定宽深比
    print("\n--- 测试3: 指定宽深比 β=1.5 ---")
    result = quick_calculate_rectangular_culvert(
        Q=5.0, n=0.014, slope_inv=3000, 
        v_min=0.5, v_max=3.0,
        target_BH_ratio=1.5
    )
    if result['success']:
        print(f"B = {result['B']:.2f} m")
        print(f"H = {result['H']:.2f} m")
        print(f"h设计 = {result['h_design']:.3f} m")
        print(f"V设计 = {result['V_design']:.3f} m/s")
        print(f"宽深比 β = {result['BH_ratio']:.2f}")
    else:
        print(f"失败: {result['error_message']}")
    
    print("\n" + "=" * 70)
    print("测试完成")
