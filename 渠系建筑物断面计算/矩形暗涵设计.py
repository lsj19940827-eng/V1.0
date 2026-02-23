# -*- coding: utf-8 -*-
"""
矩形暗涵水力设计计算模块

本模块提供矩形暗涵断面的水力计算功能，从隧洞设计.py分离而来。

支持功能：
1. 矩形暗涵水力要素计算
2. 水力最佳断面自动识别与计算
3. 净空约束验证

设计说明：
- 当底宽（B）和宽深比（B/h）同时为空时，强制按B/h=2条件搜索最优尺寸
- 高宽比限值H/B（或B/H）一般不超过1.2，参考《涵洞》（熊启钧 编著）

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
OPTIMAL_BH_RATIO = 2.0      # 水力最佳断面宽深比 β = B/h = 2
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
    
    根据《涵洞》（熊启钧 编著）要求：
    - 在任何情况下，净空高度均不得小于0.4米
    - 当涵洞内侧高度H≤3m时，净空高度应不小于H/6
    - 当涵洞内侧高度H>3m时，净空高度则应不小于0.5米
    
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
        target_HB_ratio: 目标高宽比 H/B (可选，已废弃，保留向后兼容)
        target_BH_ratio: 目标宽深比 B/h (可选，优先使用)
        manual_B: 指定底宽 (m) (可选)
        manual_increase_percent: 指定加大流量百分比 (可选)
    
    说明:
        - 当同时留空底宽（manual_B）和宽深比（target_BH_ratio）时，
          按水力最佳断面原则计算（β = B/h = 2）
        - 高宽比限值H/B（或B/H）一般不超过1.2
    
    返回:
        包含计算结果的字典
    """
    result = {
        'success': False,
        'error_message': '',
        'section_type': '矩形暗涵',
        'design_method': '',
        'is_optimal_section': False,  # 是否为水力最佳断面
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
    
    # 判断是否使用水力最佳断面
    # 当同时未指定底宽和宽深比时，使用水力最佳断面（β = B/h = 2）
    use_optimal_section = (manual_B is None or manual_B <= 0) and (target_BH_ratio is None or target_BH_ratio <= 0)
    
    # 判断是否指定了目标宽深比
    use_target_BH_ratio = target_BH_ratio is not None and target_BH_ratio > 0
    
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
    
    # 水力最佳断面模式：直接搜索使β接近2的解
    if use_optimal_section:
        result['is_optimal_section'] = True
        
        # 对于水力最佳断面，以B为主变量，寻找使actual_beta接近2的解
        B = B_start
        while B < B_end:
            # 对于给定的B，水力最佳断面期望 h = B/2
            # 但实际h由曼宁公式决定，所以需要调整H来满足净空要求
            
            # 多个H试算，找到合适的H使actual_beta接近2
            # 有效H_mult范围: H/B=H_mult/2∈[1/1.2,1.2]=[0.833,1.2] → H_mult∈[1.667,2.4]
            for H_mult in [1.7, 1.75, 1.8, 1.85, 1.9, 1.95, 2.0, 2.1, 2.2, 2.3, 2.4]:
                h_expected = B / OPTIMAL_BH_RATIO  # 期望水深 B/2
                H_trial = max(MIN_HEIGHT_RECT, h_expected * H_mult)
                
                # 检查高宽比限值: max(H/B, B/H) 均不超过 1.2
                HB_ratio_trial = H_trial / B if B > 0 else 0
                if HB_ratio_trial > HB_RATIO_LIMIT or (B / H_trial) > HB_RATIO_LIMIT:
                    continue
                
                # 求解设计水深
                h_design, success_design = solve_water_depth_rectangular(B, H_trial, n, slope, Q)
                
                if not success_design or h_design >= H_trial:
                    continue
                
                # 计算实际宽深比
                actual_BH_ratio = B / h_design if h_design > 0 else 0
                
                # 检查是否接近水力最佳断面（放宽到0.5）
                if abs(actual_BH_ratio - OPTIMAL_BH_RATIO) > 0.5:
                    continue
                
                outputs_design = calculate_rectangular_outputs(B, H_trial, h_design, n, slope)
                
                # 验证设计流速
                if outputs_design['V'] < v_min or outputs_design['V'] > v_max:
                    continue
                
                # 净空验证（设计流量工况）- 使用矩形暗涵专用约束
                req_fb_hgt = get_required_freeboard_height_rect(H_trial)
                if outputs_design['freeboard_hgt'] < req_fb_hgt:
                    continue
                if outputs_design['freeboard_pct'] < MIN_FREEBOARD_PCT_RECT * 100:
                    continue
                # 设计流量工况净空面积上限可适当放宽（因为加大流量工况更关键）
                if outputs_design['freeboard_pct'] > MAX_FREEBOARD_PCT_RECT * 100 + 20:
                    continue
                
                # 加大水深验证
                h_inc, success_inc = solve_water_depth_rectangular(B, H_trial, n, slope, Q_increased)
                
                if not success_inc or h_inc >= H_trial:
                    continue
                
                outputs_inc = calculate_rectangular_outputs(B, H_trial, h_inc, n, slope)
                
                if outputs_inc['V'] > v_max:
                    continue
                
                # 加大流量工况净空验证（这是关键约束）
                if outputs_inc['freeboard_hgt'] < req_fb_hgt:
                    continue
                if outputs_inc['freeboard_pct'] < MIN_FREEBOARD_PCT_RECT * 100:
                    continue
                if outputs_inc['freeboard_pct'] > MAX_FREEBOARD_PCT_RECT * 100:
                    continue
                
                # 找到满足条件的解，选择β最接近2的
                A_total = outputs_design['A_total']
                BH_diff = abs(actual_BH_ratio - OPTIMAL_BH_RATIO)
                
                if BH_diff < best_BH_diff or (abs(BH_diff - best_BH_diff) < 0.05 and A_total < best_A_total):
                    best_BH_diff = BH_diff
                    best_A_total = A_total
                    best_B = B
                    best_H = H_trial
                    best_found = True
            
            B += DIM_INCREMENT
        
        # 如果水力最佳断面搜索失败，自动退回到普通搜索模式
        if not best_found:
            result['is_optimal_section'] = False
            use_optimal_section = False
    
    # 非水力最佳断面模式或退回到普通搜索模式
    if not best_found:
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
                
                HB_ratio_trial = H_trial / B if B > 0 else 0
                BH_ratio_trial = B / H_trial if H_trial > 0 else 0
                if HB_ratio_trial > HB_RATIO_LIMIT or BH_ratio_trial > HB_RATIO_LIMIT:
                    bh_ratio += bh_ratio_step
                    continue
                
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
                # 设计流量工况净空面积上限可适当放宽（关键约束在加大流量工况）
                if outputs_design['freeboard_pct'] > MAX_FREEBOARD_PCT_RECT * 100 + 20:
                    bh_ratio += bh_ratio_step
                    continue
                
                h_inc, success_inc = solve_water_depth_rectangular(B, H_trial, n, slope, Q_increased)
                
                if not success_inc or h_inc >= H_trial:
                    bh_ratio += bh_ratio_step
                    continue
                
                outputs_inc = calculate_rectangular_outputs(B, H_trial, h_inc, n, slope)
                
                if outputs_inc['V'] > v_max:
                    bh_ratio += bh_ratio_step
                    continue
                
                # 加大流量工况净空验证（这是关键约束）
                if (outputs_inc['freeboard_hgt'] >= req_fb_hgt and
                    outputs_inc['freeboard_pct'] >= MIN_FREEBOARD_PCT_RECT * 100 and
                    outputs_inc['freeboard_pct'] <= MAX_FREEBOARD_PCT_RECT * 100):
                    
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
            result['error_message'] = (
                f"计算失败：指定的底宽 B={manual_B:.3f} m 无法满足要求。\n\n"
                "可能原因及建议：\n"
                "1. 底宽过小，导致加大流量工况下无净空或水深超出洞高；\n"
                "2. 流速超出限制；\n"
                "建议：增大底宽，或者留空底宽由系统自动计算。"
            )
        elif use_optimal_section:
            result['error_message'] = (
                '计算失败：使用水力最佳断面（β=2）未找到满足要求的断面尺寸。\n\n'
                '可能原因：\n'
                '1. 流速约束过严；\n'
                '2. 净空约束无法满足；\n'
                '建议：指定宽深比或底宽。'
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
    
    fb_check_passed = (fb_hgt_inc >= req_fb_hgt and 
                       MIN_FREEBOARD_PCT_RECT * 100 <= fb_pct_inc <= MAX_FREEBOARD_PCT_RECT * 100)
    
    result['success'] = True
    
    # 设计方法标识
    if use_optimal_section:
        result['design_method'] = f'水力最佳断面; B={B:.2f}m, H={H:.2f}m (β=2)'
        result['is_optimal_section'] = True
    else:
        result['design_method'] = f'矩形暗涵; B={B:.2f}m, H={H:.2f}m'
        result['is_optimal_section'] = False
    
    result['B'] = B
    result['H'] = H
    result['HB_ratio'] = H / B if B > 0 else 0
    result['BH_ratio'] = B / h_design if h_design > 0 else 0
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
    
    # 矩形暗涵测试 - 水力最佳断面（留空B和宽深比）
    print("\n--- 测试1: 水力最佳断面（β=2） ---")
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
        print(f"是否水力最佳断面: {result['is_optimal_section']}")
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
