# -*- coding: utf-8 -*-
"""
圆拱直墙型暗涵水力设计模块。

本模块复用圆拱直墙型断面的几何与水力公式，但按暗涵口径做净空与搜索约束：
1. 不沿用隧洞最小尺寸限制；
2. 不沿用隧洞 15% 净空比例要求；
3. 不按隧洞 H/B 固定区间搜索；
4. 按暗涵净空规则校核最小净空高度和 10%~30% 净空面积比例。
"""

import math
from typing import Any, Dict, Optional, Tuple

from 矩形暗涵设计 import (
    DIM_INCREMENT,
    MAX_FREEBOARD_PCT_RECT,
    MIN_FREEBOARD_HGT_RECT,
    MIN_FREEBOARD_PCT_RECT,
    MIN_HEIGHT_RECT,
    MIN_WIDTH_RECT,
    SOLVER_TOLERANCE,
    get_flow_increase_percent_rect,
    get_required_freeboard_height_rect,
)
from 隧洞设计 import (
    calculate_horseshoe_outputs,
    solve_water_depth_horseshoe,
)


MIN_THETA_DEG = 90.0
MAX_THETA_DEG = 180.0
MAX_SEARCH_WIDTH = 20.0
MAX_SEARCH_HEIGHT = 20.0
COARSE_HEIGHT_STEP = 0.05
FINE_HEIGHT_STEP = 0.01
COARSE_WIDTH_STEP = 0.1


def _build_result(theta_deg: float) -> Dict[str, Any]:
    """构造统一结果字典。"""
    return {
        "success": False,
        "error_message": "",
        "section_type": "暗涵-圆拱直墙型",
        "design_method": "",
        "B": 0.0,
        "H_total": 0.0,
        "H_straight": 0.0,
        "theta_deg": theta_deg,
        "HB_ratio": 0.0,
        "h_design": 0.0,
        "V_design": 0.0,
        "A_design": 0.0,
        "P_design": 0.0,
        "R_hyd_design": 0.0,
        "Q_calc": 0.0,
        "freeboard_pct_design": 0.0,
        "freeboard_hgt_design": 0.0,
        "increase_percent": 0.0,
        "Q_increased": 0.0,
        "h_increased": 0.0,
        "V_increased": 0.0,
        "A_increased": 0.0,
        "P_increased": 0.0,
        "R_hyd_increased": 0.0,
        "freeboard_pct_inc": 0.0,
        "freeboard_hgt_inc": 0.0,
        "A_total": 0.0,
        "fb_min_required": 0.0,
        "fb_check_passed": False,
        "fb_check_details": "",
    }


def _calc_arch_height(B: float, theta_rad: float) -> float:
    """根据底宽和圆心角计算拱部高度。"""
    sin_half = math.sin(theta_rad / 2.0)
    if B <= 0 or abs(sin_half) < 1e-9:
        return 0.0
    radius = (B / 2.0) / sin_half
    return radius * (1.0 - math.cos(theta_rad / 2.0))


def _validate_theta(theta_deg: float) -> Optional[str]:
    """校验圆心角取值。"""
    if theta_deg < MIN_THETA_DEG or theta_deg > MAX_THETA_DEG:
        return f"圆心角必须在{int(MIN_THETA_DEG)}~{int(MAX_THETA_DEG)}度之间"
    return None


def _check_candidate(
    B: float,
    H_total: float,
    theta_rad: float,
    Q: float,
    Q_increased: float,
    n: float,
    slope: float,
    v_min: float,
    v_max: float,
    use_increase: bool,
) -> Optional[Dict[str, Any]]:
    """校验单个候选断面是否满足暗涵约束。"""
    if B <= 0 or H_total <= 0:
        return None

    h_design, success_design = solve_water_depth_horseshoe(B, H_total, theta_rad, n, slope, Q)
    if not success_design or h_design >= H_total:
        return None

    outputs_design = calculate_horseshoe_outputs(B, H_total, theta_rad, h_design, n, slope)
    if outputs_design["V"] < v_min or outputs_design["V"] > v_max:
        return None

    required_fb = get_required_freeboard_height_rect(H_total)
    if outputs_design["freeboard_hgt"] < required_fb:
        return None
    if outputs_design["freeboard_pct"] < MIN_FREEBOARD_PCT_RECT * 100.0:
        return None
    if not use_increase and outputs_design["freeboard_pct"] > MAX_FREEBOARD_PCT_RECT * 100.0:
        return None

    if use_increase:
        h_inc, success_inc = solve_water_depth_horseshoe(B, H_total, theta_rad, n, slope, Q_increased)
        if not success_inc or h_inc >= H_total:
            return None
        outputs_inc = calculate_horseshoe_outputs(B, H_total, theta_rad, h_inc, n, slope)
        if outputs_inc["V"] > v_max:
            return None
        if outputs_inc["freeboard_hgt"] < required_fb:
            return None
        if outputs_inc["freeboard_pct"] < MIN_FREEBOARD_PCT_RECT * 100.0:
            return None
        if outputs_inc["freeboard_pct"] > MAX_FREEBOARD_PCT_RECT * 100.0:
            return None
    else:
        h_inc = h_design
        outputs_inc = outputs_design

    return {
        "h_design": h_design,
        "outputs_design": outputs_design,
        "h_inc": h_inc,
        "outputs_inc": outputs_inc,
        "required_fb": required_fb,
        "A_total": outputs_design["A_total"],
    }


def _search_min_height_for_width(
    B: float,
    theta_rad: float,
    Q: float,
    Q_increased: float,
    n: float,
    slope: float,
    v_min: float,
    v_max: float,
    use_increase: bool,
) -> Optional[Tuple[float, Dict[str, Any]]]:
    """对固定底宽搜索满足约束的最小总高。"""
    arch_height = _calc_arch_height(B, theta_rad)
    height_min = max(MIN_HEIGHT_RECT, arch_height + 0.01)

    coarse_height = height_min
    coarse_result: Optional[Dict[str, Any]] = None
    prev_height = height_min
    while coarse_height <= MAX_SEARCH_HEIGHT + 1e-9:
        coarse_result = _check_candidate(
            B, coarse_height, theta_rad, Q, Q_increased, n, slope, v_min, v_max, use_increase
        )
        if coarse_result is not None:
            break
        prev_height = coarse_height
        coarse_height += COARSE_HEIGHT_STEP

    if coarse_result is None:
        return None

    fine_start = max(height_min, prev_height)
    fine_end = coarse_height
    best_height = coarse_height
    best_result = coarse_result
    fine_height = fine_start
    while fine_height <= fine_end + 1e-9:
        fine_result = _check_candidate(
            B, fine_height, theta_rad, Q, Q_increased, n, slope, v_min, v_max, use_increase
        )
        if fine_result is not None:
            best_height = fine_height
            best_result = fine_result
            break
        fine_height += FINE_HEIGHT_STEP

    return best_height, best_result


def _format_fb_details(H_total: float, required_fb: float) -> str:
    """生成净空校核说明。"""
    details = [f"涵洞总高 H = {H_total:.2f}m"]
    if H_total <= 3.0:
        details.append(f"H≤3m，净空高度应≥H/6 = {H_total / 6.0:.3f}m，且≥{MIN_FREEBOARD_HGT_RECT:.1f}m")
    else:
        details.append("H>3m，净空高度应≥0.5m")
    details.append(f"要求净空高度≥{required_fb:.3f}m")
    details.append("净空面积应为总面积的10%~30%")
    return "\n".join(details)


def quick_calculate_arch_culvert(
    Q: float,
    n: float,
    slope_inv: float,
    v_min: float,
    v_max: float,
    theta_deg: float = 180.0,
    manual_B: float = None,
    manual_increase_percent: float = None,
) -> Dict[str, Any]:
    """快速计算圆拱直墙型暗涵。"""
    if theta_deg is None or theta_deg <= 0:
        theta_deg = 180.0

    result = _build_result(theta_deg)
    if Q <= 0 or n <= 0 or slope_inv <= 0:
        result["error_message"] = "输入参数无效"
        return result

    theta_error = _validate_theta(theta_deg)
    if theta_error:
        result["error_message"] = theta_error
        return result

    if manual_increase_percent is not None and manual_increase_percent >= 0:
        increase_percent = manual_increase_percent
    else:
        increase_percent = get_flow_increase_percent_rect(Q)

    Q_increased = Q * (1.0 + increase_percent / 100.0)
    result["increase_percent"] = increase_percent
    result["Q_increased"] = Q_increased

    slope = 1.0 / slope_inv
    theta_rad = math.radians(theta_deg)
    use_increase = increase_percent > 0

    if manual_B is not None and manual_B > 0:
        B_start = manual_B
        B_end = manual_B + DIM_INCREMENT
        B_step = DIM_INCREMENT
    else:
        B_start = MIN_WIDTH_RECT
        B_end = MAX_SEARCH_WIDTH
        B_step = COARSE_WIDTH_STEP

    best_found = False
    best_B = 0.0
    best_H = 0.0
    best_candidate: Optional[Dict[str, Any]] = None
    best_area = float("inf")

    B = B_start
    while B <= B_end + 1e-9:
        search_result = _search_min_height_for_width(
            B, theta_rad, Q, Q_increased, n, slope, v_min, v_max, use_increase
        )
        if search_result is not None:
            H_total, candidate = search_result
            if candidate["A_total"] < best_area:
                best_found = True
                best_B = B
                best_H = H_total
                best_candidate = candidate
                best_area = candidate["A_total"]
        B += B_step

    if best_found and manual_B is None:
        fine_start = max(MIN_WIDTH_RECT, best_B - 0.3)
        fine_end = min(MAX_SEARCH_WIDTH, best_B + 0.3)
        B = fine_start
        while B <= fine_end + 1e-9:
            search_result = _search_min_height_for_width(
                B, theta_rad, Q, Q_increased, n, slope, v_min, v_max, use_increase
            )
            if search_result is not None:
                H_total, candidate = search_result
                if candidate["A_total"] < best_area:
                    best_B = B
                    best_H = H_total
                    best_candidate = candidate
                    best_area = candidate["A_total"]
            B += DIM_INCREMENT

    if not best_found or best_candidate is None:
        if manual_B is not None and manual_B > 0:
            result["error_message"] = (
                f"计算失败：指定的底宽 B={manual_B:.3f} m 无法满足要求。\n\n"
                "可能原因及建议：\n"
                "1. 底宽过小，导致流速或净空不满足要求；\n"
                "2. 圆心角过陡，导致总高不足；\n"
                "建议：增大底宽，或留空底宽由系统自动计算。"
            )
        else:
            result["error_message"] = "计算失败：未找到满足流速及暗涵净空要求的圆拱直墙型断面尺寸。"
        return result

    arch_height = _calc_arch_height(best_B, theta_rad)
    H_straight = max(0.0, best_H - arch_height)
    outputs_design = best_candidate["outputs_design"]
    outputs_inc = best_candidate["outputs_inc"]

    result["success"] = True
    result["design_method"] = f"圆拱直墙型暗涵; B={best_B:.2f}m, H={best_H:.2f}m, θ={theta_deg:.1f}°"
    result["B"] = best_B
    result["H_total"] = best_H
    result["H_straight"] = H_straight
    result["HB_ratio"] = best_H / best_B if best_B > 0 else 0.0
    result["h_design"] = best_candidate["h_design"]
    result["V_design"] = outputs_design["V"]
    result["A_design"] = outputs_design["A"]
    result["P_design"] = outputs_design["P"]
    result["R_hyd_design"] = outputs_design["R_hyd"]
    result["Q_calc"] = outputs_design["Q"]
    result["freeboard_pct_design"] = outputs_design["freeboard_pct"]
    result["freeboard_hgt_design"] = outputs_design["freeboard_hgt"]
    result["h_increased"] = best_candidate["h_inc"]
    result["V_increased"] = outputs_inc["V"]
    result["A_increased"] = outputs_inc["A"]
    result["P_increased"] = outputs_inc["P"]
    result["R_hyd_increased"] = outputs_inc["R_hyd"]
    result["freeboard_pct_inc"] = outputs_inc["freeboard_pct"]
    result["freeboard_hgt_inc"] = outputs_inc["freeboard_hgt"]
    result["A_total"] = outputs_design["A_total"]
    result["fb_min_required"] = best_candidate["required_fb"]
    result["fb_check_passed"] = (
        outputs_inc["freeboard_hgt"] >= best_candidate["required_fb"] - SOLVER_TOLERANCE
        and MIN_FREEBOARD_PCT_RECT * 100.0 - 0.1 <= outputs_inc["freeboard_pct"] <= MAX_FREEBOARD_PCT_RECT * 100.0 + 0.1
    )
    result["fb_check_details"] = _format_fb_details(best_H, best_candidate["required_fb"])
    return result
