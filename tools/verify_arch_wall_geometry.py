# -*- coding: utf-8 -*-
"""
圆拱直墙型隧洞 几何公式独立验证脚本

几何结构:
  底部: 矩形, 宽 B, 高 H_straight
  顶部: 圆拱, 拱半径 R_arch = (B/2)/sin(θ/2), 拱高 H_arch = R_arch·(1-cos(θ/2))
  总高: H_total = H_straight + H_arch
  θ: 拱顶圆心角 (90°~180°)

过水面积分2段:
  ① h ≤ H_straight:  A = B·h,  P = B + 2h
  ② h > H_straight:  矩形满 + 拱部弓形面积,  P = B + 2·H_straight + 拱弧长

验证方法:
  1. 几何参数推导正确性 (R_arch, H_arch, H_straight)
  2. 数值积分面积 vs 解析公式
  3. 数值弧长湿周 vs 解析公式
  4. 总面积公式验证
  5. 边界连续性 (h=H_straight 处)
  6. 特殊值 (h=0, h=H_straight, h=H_total)
  7. 单调性
  8. 不同圆心角 (90°/120°/150°/180°) 全覆盖
"""

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "渠系建筑物断面计算"))
from 隧洞设计 import (
    calculate_horseshoe_area,
    calculate_horseshoe_perimeter,
    calculate_horseshoe_total_area,
    PI,
)

# ============================================================
# 测试框架
# ============================================================
PASS_COUNT = 0
FAIL_COUNT = 0
ERRORS = []


def check(name, cond, detail=""):
    global PASS_COUNT, FAIL_COUNT
    if cond:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1
        msg = f"FAIL: {name}" + (f" | {detail}" if detail else "")
        ERRORS.append(msg)
        print(f"  ✗ {msg}")


def abs_eq(a, b, tol=0.001):
    return abs(a - b) < tol


def rel_eq(a, b, tol=0.01):
    if abs(b) < 1e-9:
        return abs(a) < tol
    return abs(a - b) / abs(b) < tol


# ============================================================
# 几何辅助: 从圆方程独立计算半宽
# ============================================================
def arch_geometry(B, H_total, theta_rad):
    """计算拱部几何参数"""
    sin_half = math.sin(theta_rad / 2)
    if abs(sin_half) < 1e-12:
        return 0, 0, H_total, 0
    R_arch = (B / 2) / sin_half
    H_arch = R_arch * (1 - math.cos(theta_rad / 2))
    H_straight = max(0, H_total - H_arch)
    # 拱圆心在拱脚线以下: cy = H_straight - R_arch·cos(θ/2)
    # 验证: 拱顶 = cy + R_arch = H_straight + R_arch·(1-cos(θ/2)) = H_straight + H_arch = H_total ✓
    # 验证: 拱脚半宽 = sqrt(R² - (H_straight-cy)²) = sqrt(R² - R²cos²(θ/2)) = R·sin(θ/2) = B/2 ✓
    cy = H_straight - R_arch * math.cos(theta_rad / 2)
    return R_arch, H_arch, H_straight, cy


def half_width_from_geometry(B, H_total, theta_rad, h):
    """从几何直接计算半宽（不使用被测公式）"""
    R_arch, H_arch, H_straight, cy = arch_geometry(B, H_total, theta_rad)
    h = min(h, H_total)
    if h <= 0:
        return 0.0
    if h <= H_straight:
        return B / 2
    else:
        # 在拱部: 圆方程 x² + (y - cy)² = R_arch²
        # x = sqrt(R_arch² - (h - cy)²)
        val = R_arch ** 2 - (h - cy) ** 2
        if val < 0:
            return 0.0
        return math.sqrt(val)


def numerical_area(B, H_total, theta_rad, h, N=50000):
    """用梯形法数值积分计算面积"""
    if h <= 0:
        return 0.0
    h = min(h, H_total)
    dy = h / N
    total = 0.0
    for i in range(N):
        y0 = i * dy
        y1 = (i + 1) * dy
        w0 = 2 * half_width_from_geometry(B, H_total, theta_rad, y0)
        w1 = 2 * half_width_from_geometry(B, H_total, theta_rad, y1)
        total += (w0 + w1) / 2 * dy
    return total


def numerical_perimeter(B, H_total, theta_rad, h, N=50000):
    """
    用数值弧长计算湿周（沿右侧轮廓，再×2加底边）
    路径: (0,0) → (B/2, 0) → 沿右墙/拱 → (half_w(h), h)
    注意: 湿周 = 底边 + 左右两侧(对称)
    """
    if h <= 0:
        return 0.0
    h = min(h, H_total)
    R_arch, H_arch, H_straight, cy = arch_geometry(B, H_total, theta_rad)

    # 底边
    perim = B

    # 右侧从 (B/2, 0) 向上
    # 直墙段: 从 y=0 到 y=min(h, H_straight)
    h_wall = min(h, H_straight)
    perim += 2 * h_wall  # 两侧直墙

    if h > H_straight:
        # 拱部弧段: 从 H_straight 到 h
        # 沿右侧拱的弧长，用数值积分
        h_in_arch = h - H_straight
        dy = h_in_arch / N
        arc_right = 0.0
        for i in range(N):
            y0 = H_straight + i * dy
            y1 = H_straight + (i + 1) * dy
            x0 = half_width_from_geometry(B, H_total, theta_rad, y0)
            x1 = half_width_from_geometry(B, H_total, theta_rad, y1)
            ds = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
            arc_right += ds
        perim += 2 * arc_right  # 左右对称

    return perim


# ============================================================
# 独立解析面积公式（不调用被测模块，直接按公式计算）
# ============================================================
def analytical_area(B, H_total, theta_rad, h):
    """独立解析计算过水面积"""
    R_arch, H_arch, H_straight, cy = arch_geometry(B, H_total, theta_rad)
    h = min(h, H_total)
    if h <= 0:
        return 0.0
    if h <= H_straight:
        return B * h
    else:
        A_rect = B * H_straight
        h_in_arch = h - H_straight
        if h_in_arch >= H_arch - 1e-12:
            # 拱部全满: 弓形面积 = R²/2 · (θ - sin θ)
            A_arch = (R_arch ** 2 / 2) * (theta_rad - math.sin(theta_rad))
            return A_rect + A_arch
        else:
            # 拱部部分充水
            A_arch_total = (R_arch ** 2 / 2) * (theta_rad - math.sin(theta_rad))
            h_dry = H_arch - h_in_arch
            d_temp = R_arch - h_dry
            acos_arg = max(-1, min(1, d_temp / R_arch))
            alpha_temp = math.acos(acos_arg)
            A_dry = R_arch ** 2 * alpha_temp - d_temp * math.sqrt(
                max(0, R_arch ** 2 - d_temp ** 2))
            return A_rect + A_arch_total - A_dry


def analytical_perimeter(B, H_total, theta_rad, h):
    """独立解析计算湿周"""
    R_arch, H_arch, H_straight, cy = arch_geometry(B, H_total, theta_rad)
    h = min(h, H_total)
    if h <= 0:
        return 0.0
    if h <= H_straight:
        return B + 2 * h
    else:
        h_in_arch = h - H_straight
        if h_in_arch >= H_arch - 1e-12:
            # 满拱
            return B + 2 * H_straight + R_arch * theta_rad
        else:
            # 部分拱
            Total_Arc = R_arch * theta_rad
            h_dry = H_arch - h_in_arch
            d_temp = R_arch - h_dry
            acos_arg = max(-1, min(1, d_temp / R_arch))
            alpha_temp = math.acos(acos_arg)
            L_dry = 2 * R_arch * alpha_temp
            return B + 2 * H_straight + Total_Arc - L_dry


# ============================================================
# 验证1: 几何参数推导
# ============================================================
def test_geometry_params():
    print("\n" + "=" * 70)
    print("验证1: 几何参数推导正确性 (R_arch, H_arch, H_straight)")
    print("=" * 70)

    configs = [
        (3.0, 4.0, 180), (3.0, 4.0, 150), (3.0, 4.0, 120), (3.0, 4.0, 90),
        (4.0, 5.5, 180), (2.0, 3.0, 150), (5.0, 6.5, 120), (6.0, 8.0, 150),
    ]
    for B, H, tdeg in configs:
        tr = math.radians(tdeg)
        R_arch, H_arch, H_straight, cy = arch_geometry(B, H, tr)

        # R_arch·sin(θ/2) = B/2
        check(f"B={B},θ={tdeg} R·sin(θ/2)=B/2",
              abs_eq(R_arch * math.sin(tr / 2), B / 2, 1e-10),
              f"R·sin={R_arch * math.sin(tr / 2):.8f}, B/2={B / 2:.8f}")

        # H_straight + H_arch = H_total
        check(f"B={B},θ={tdeg} H_straight+H_arch=H_total",
              abs_eq(H_straight + H_arch, H, 1e-10),
              f"sum={H_straight + H_arch:.8f}, H={H:.8f}")

        # H_arch = R·(1-cos(θ/2))
        check(f"B={B},θ={tdeg} H_arch=R·(1-cos(θ/2))",
              abs_eq(H_arch, R_arch * (1 - math.cos(tr / 2)), 1e-10))

        # θ=180° → R_arch = B/2, H_arch = R_arch = B/2 (半圆拱)
        if tdeg == 180:
            check(f"B={B},θ=180 R_arch=B/2", abs_eq(R_arch, B / 2, 1e-10))
            check(f"B={B},θ=180 H_arch=B/2", abs_eq(H_arch, B / 2, 1e-10))

        print(f"    B={B}, H={H}, θ={tdeg}°: R_arch={R_arch:.4f}, "
              f"H_arch={H_arch:.4f}, H_straight={H_straight:.4f}")


# ============================================================
# 验证2: 代码 vs 独立解析公式
# ============================================================
def test_code_vs_analytical():
    print("\n" + "=" * 70)
    print("验证2: 代码函数 vs 独立解析公式 一致性")
    print("=" * 70)

    configs = [
        (3.0, 4.0, 180), (3.0, 4.0, 150), (3.0, 4.0, 120), (3.0, 4.0, 90),
        (4.0, 5.5, 180), (2.0, 3.0, 150), (5.0, 6.5, 120),
        (3.5, 5.0, 160), (6.0, 8.0, 150), (2.5, 3.5, 130),
    ]
    for B, H, tdeg in configs:
        tr = math.radians(tdeg)
        R_arch, H_arch, H_straight, cy = arch_geometry(B, H, tr)

        # 采样水深: 直墙段 + 拱部段
        test_depths = [
            0.001,
            H_straight * 0.3, H_straight * 0.5, H_straight * 0.8, H_straight * 0.999,
            H_straight + H_arch * 0.01, H_straight + H_arch * 0.2,
            H_straight + H_arch * 0.5, H_straight + H_arch * 0.8,
            H_straight + H_arch * 0.99, H * 0.999,
        ]
        for h in test_depths:
            if h <= 0 or h > H:
                continue

            A_code = calculate_horseshoe_area(B, H, tr, h)
            P_code = calculate_horseshoe_perimeter(B, H, tr, h)
            A_ana = analytical_area(B, H, tr, h)
            P_ana = analytical_perimeter(B, H, tr, h)

            check(f"B={B},θ={tdeg},h={h:.3f} A一致",
                  abs_eq(A_code, A_ana, 1e-8),
                  f"code={A_code:.8f}, ana={A_ana:.8f}")
            check(f"B={B},θ={tdeg},h={h:.3f} P一致",
                  abs_eq(P_code, P_ana, 1e-8),
                  f"code={P_code:.8f}, ana={P_ana:.8f}")

        # 总面积
        At_code = calculate_horseshoe_total_area(B, H, tr)
        At_ana_rect = B * H_straight
        At_ana_arch = (R_arch ** 2 / 2) * (tr - math.sin(tr))
        At_ana = At_ana_rect + At_ana_arch
        check(f"B={B},θ={tdeg} 总面积一致",
              abs_eq(At_code, At_ana, 1e-8),
              f"code={At_code:.8f}, ana={At_ana:.8f}")


# ============================================================
# 验证3: 面积 — 数值积分交叉验证
# ============================================================
def test_numerical_area():
    print("\n" + "=" * 70)
    print("验证3: 面积公式 vs 数值积分 (N=50000)")
    print("=" * 70)

    N_INTEG = 50000
    configs = [
        (3.0, 4.0, 180), (3.0, 4.0, 150), (3.0, 4.0, 120), (3.0, 4.0, 90),
        (4.0, 5.5, 180), (2.0, 3.0, 150), (5.0, 6.5, 120),
    ]
    for B, H, tdeg in configs:
        tr = math.radians(tdeg)
        R_arch, H_arch, H_straight, cy = arch_geometry(B, H, tr)

        test_depths = [
            H_straight * 0.5, H_straight,
            H_straight + H_arch * 0.3, H_straight + H_arch * 0.7,
            H * 0.99,
        ]
        max_err = 0.0
        for h in test_depths:
            if h <= 0.001 or h > H:
                continue
            A_ana = analytical_area(B, H, tr, h)
            A_num = numerical_area(B, H, tr, h, N_INTEG)
            err = abs(A_ana - A_num)
            rel = err / A_num * 100 if A_num > 1e-9 else 0
            max_err = max(max_err, rel)
            check(f"B={B},θ={tdeg},h={h:.3f} 面积数值验证",
                  rel < 0.01,  # 相对误差 < 0.01%
                  f"解析={A_ana:.6f}, 数值={A_num:.6f}, 相对误差={rel:.5f}%")
        print(f"    B={B},θ={tdeg}°: 最大相对误差 = {max_err:.6f}%")


# ============================================================
# 验证4: 湿周 — 数值弧长交叉验证
# ============================================================
def test_numerical_perimeter():
    print("\n" + "=" * 70)
    print("验证4: 湿周公式 vs 数值弧长 (N=50000)")
    print("=" * 70)

    N_INTEG = 50000
    configs = [
        (3.0, 4.0, 180), (3.0, 4.0, 150), (3.0, 4.0, 120), (3.0, 4.0, 90),
        (4.0, 5.5, 180), (2.0, 3.0, 150), (5.0, 6.5, 120),
    ]
    for B, H, tdeg in configs:
        tr = math.radians(tdeg)
        R_arch, H_arch, H_straight, cy = arch_geometry(B, H, tr)

        test_depths = [
            H_straight * 0.5, H_straight,
            H_straight + H_arch * 0.3, H_straight + H_arch * 0.7,
            H * 0.99,
        ]
        max_err = 0.0
        for h in test_depths:
            if h <= 0.001 or h > H:
                continue
            P_ana = analytical_perimeter(B, H, tr, h)
            P_num = numerical_perimeter(B, H, tr, h, N_INTEG)
            err = abs(P_ana - P_num)
            rel = err / P_num * 100 if P_num > 1e-9 else 0
            max_err = max(max_err, rel)
            check(f"B={B},θ={tdeg},h={h:.3f} 湿周数值验证",
                  rel < 0.05,  # 弧长积分精度要求略放宽
                  f"解析={P_ana:.6f}, 数值={P_num:.6f}, 相对误差={rel:.5f}%")
        print(f"    B={B},θ={tdeg}°: 最大相对误差 = {max_err:.6f}%")


# ============================================================
# 验证5: 边界连续性 (h=H_straight 处)
# ============================================================
def test_boundary_continuity():
    print("\n" + "=" * 70)
    print("验证5: h=H_straight 处边界连续性 (直墙→拱部)")
    print("=" * 70)

    eps = 1e-7
    configs = [
        (3.0, 4.0, 180), (3.0, 4.0, 150), (3.0, 4.0, 120), (3.0, 4.0, 90),
        (4.0, 5.5, 180), (2.0, 3.0, 150), (5.0, 6.5, 120),
        (3.5, 5.0, 160), (6.0, 8.0, 150),
    ]
    for B, H, tdeg in configs:
        tr = math.radians(tdeg)
        R_arch, H_arch, H_straight, cy = arch_geometry(B, H, tr)
        if H_straight < 0.001:
            continue

        A_lo = calculate_horseshoe_area(B, H, tr, H_straight - eps)
        A_hi = calculate_horseshoe_area(B, H, tr, H_straight + eps)
        P_lo = calculate_horseshoe_perimeter(B, H, tr, H_straight - eps)
        P_hi = calculate_horseshoe_perimeter(B, H, tr, H_straight + eps)

        # 宽度连续: 直墙段始终=B, 拱部起始也应=B
        w_lo = B
        w_hi = 2 * half_width_from_geometry(B, H, tr, H_straight + eps)

        check(f"B={B},θ={tdeg} A连续@H_straight",
              abs_eq(A_lo, A_hi, 1e-4),
              f"A_lo={A_lo:.8f}, A_hi={A_hi:.8f}, diff={abs(A_lo - A_hi):.2e}")
        check(f"B={B},θ={tdeg} P连续@H_straight",
              abs_eq(P_lo, P_hi, 1e-4),
              f"P_lo={P_lo:.8f}, P_hi={P_hi:.8f}, diff={abs(P_lo - P_hi):.2e}")
        check(f"B={B},θ={tdeg} 宽度连续@H_straight",
              abs_eq(w_lo, w_hi, 1e-3),
              f"w_lo={w_lo:.6f}, w_hi={w_hi:.6f}")


# ============================================================
# 验证6: 特殊值检验
# ============================================================
def test_special_values():
    print("\n" + "=" * 70)
    print("验证6: 特殊值检验")
    print("=" * 70)

    configs = [
        (3.0, 4.0, 180), (3.0, 4.0, 150), (4.0, 5.5, 120),
        (2.0, 3.0, 90), (5.0, 6.5, 150),
    ]
    for B, H, tdeg in configs:
        tr = math.radians(tdeg)
        R_arch, H_arch, H_straight, cy = arch_geometry(B, H, tr)

        # h=0: A=0, P=0
        check(f"B={B},θ={tdeg} h=0 A=0",
              calculate_horseshoe_area(B, H, tr, 0) == 0.0)
        check(f"B={B},θ={tdeg} h=0 P=0",
              calculate_horseshoe_perimeter(B, H, tr, 0) == 0.0)

        # h=H_straight: A=B·H_straight, P=B+2·H_straight
        if H_straight > 0.001:
            A_hs = calculate_horseshoe_area(B, H, tr, H_straight)
            P_hs = calculate_horseshoe_perimeter(B, H, tr, H_straight)
            check(f"B={B},θ={tdeg} h=H_s A=B·H_s",
                  abs_eq(A_hs, B * H_straight, 0.001),
                  f"A={A_hs:.6f}, exp={B * H_straight:.6f}")
            check(f"B={B},θ={tdeg} h=H_s P=B+2H_s",
                  abs_eq(P_hs, B + 2 * H_straight, 0.001),
                  f"P={P_hs:.6f}, exp={B + 2 * H_straight:.6f}")

        # h=H (满水): A ≈ 总面积, P = B + 2·H_straight + R·θ
        A_full = calculate_horseshoe_area(B, H, tr, H)
        P_full = calculate_horseshoe_perimeter(B, H, tr, H)
        A_total = calculate_horseshoe_total_area(B, H, tr)
        P_full_exp = B + 2 * H_straight + R_arch * tr

        check(f"B={B},θ={tdeg} h=H A=A_total",
              abs_eq(A_full, A_total, 0.01),
              f"A_full={A_full:.6f}, A_total={A_total:.6f}")
        check(f"B={B},θ={tdeg} h=H P=B+2H_s+Rθ",
              abs_eq(P_full, P_full_exp, 0.01),
              f"P_full={P_full:.6f}, exp={P_full_exp:.6f}")

        # θ=180° (半圆拱): 总面积 = B·H_straight + π·(B/2)²/2
        if tdeg == 180:
            A_total_exp = B * H_straight + math.pi * (B / 2) ** 2 / 2
            check(f"B={B},θ=180 A_total=B·H_s+π(B/2)²/2",
                  abs_eq(A_total, A_total_exp, 0.001),
                  f"A_total={A_total:.6f}, exp={A_total_exp:.6f}")

        # 水力半径 R_hyd = A/P
        if P_full > 0:
            R_hyd = A_full / P_full
            print(f"    B={B},θ={tdeg}°: A_total={A_total:.4f}, P_full={P_full:.4f}, "
                  f"R_hyd={R_hyd:.4f}")


# ============================================================
# 验证7: 单调性
# ============================================================
def test_monotonicity():
    print("\n" + "=" * 70)
    print("验证7: 面积/湿周 单调性")
    print("=" * 70)

    configs = [
        (3.0, 4.0, 180), (3.0, 4.0, 150), (3.0, 4.0, 120), (3.0, 4.0, 90),
        (4.0, 5.5, 180), (5.0, 6.5, 120),
    ]
    for B, H, tdeg in configs:
        tr = math.radians(tdeg)
        N = 500
        prev_A = -1
        prev_P = -1
        A_ok = True
        P_ok = True
        fail_h_A = None
        fail_h_P = None
        for i in range(1, N):
            h = i / N * H
            A = calculate_horseshoe_area(B, H, tr, h)
            P = calculate_horseshoe_perimeter(B, H, tr, h)
            if A < prev_A - 1e-9:
                A_ok = False
                fail_h_A = h
            if P < prev_P - 1e-9:
                P_ok = False
                fail_h_P = h
            prev_A = A
            prev_P = P
        check(f"B={B},θ={tdeg} 面积单调递增", A_ok,
              f"失败于h={fail_h_A}" if fail_h_A else "")
        check(f"B={B},θ={tdeg} 湿周单调递增", P_ok,
              f"失败于h={fail_h_P}" if fail_h_P else "")


# ============================================================
# 验证8: 半宽一致性 — 从圆方程 vs 代码中隐含的宽度
# ============================================================
def test_halfwidth_consistency():
    print("\n" + "=" * 70)
    print("验证8: 水面宽 — 圆方程直接推导 vs 面积微分")
    print("=" * 70)

    configs = [
        (3.0, 4.0, 180), (3.0, 4.0, 150), (3.0, 4.0, 120), (3.0, 4.0, 90),
        (4.0, 5.5, 180), (2.0, 3.0, 150),
    ]
    for B, H, tdeg in configs:
        tr = math.radians(tdeg)
        R_arch, H_arch, H_straight, cy = arch_geometry(B, H, tr)
        max_err = 0.0
        N = 200
        for i in range(1, N):
            h = i / N * H
            w_circle = half_width_from_geometry(B, H, tr, h)

            # 从面积的数值微分估算宽度: dA/dh ≈ B(h) = 2·w(h)
            dh = 1e-6
            A1 = analytical_area(B, H, tr, h - dh)
            A2 = analytical_area(B, H, tr, h + dh)
            w_from_area = (A2 - A1) / (2 * dh) / 2  # dA/dh = B = 2w

            err = abs(w_circle - w_from_area)
            max_err = max(max_err, err)
            check(f"B={B},θ={tdeg},h={h:.3f} 半宽一致",
                  abs_eq(w_circle, w_from_area, 1e-3),
                  f"圆方程={w_circle:.6f}, 面积微分={w_from_area:.6f}, diff={err:.2e}")

        print(f"    B={B},θ={tdeg}°: 最大绝对误差 = {max_err:.2e}")


# ============================================================
# 验证9: 拱部面积公式的独立数学推导验证
# ============================================================
def test_arch_area_formula():
    print("\n" + "=" * 70)
    print("验证9: 拱部面积公式的数学推导验证")
    print("=" * 70)
    print("  弓形面积 = R²/2·(θ - sinθ)")
    print("  部分充水时用 全弓形 - 干燥弓形 来计算")

    configs = [
        (3.0, 4.0, 180), (3.0, 4.0, 150), (3.0, 4.0, 120),
        (4.0, 5.5, 180), (5.0, 6.5, 120),
    ]
    for B, H, tdeg in configs:
        tr = math.radians(tdeg)
        R_arch, H_arch, H_straight, cy = arch_geometry(B, H, tr)

        # 全弓形面积验证: R²/2·(θ - sinθ)
        A_bow = (R_arch ** 2 / 2) * (tr - math.sin(tr))
        # 数值积分验证
        A_bow_num = numerical_area(B, H, tr, H) - B * H_straight
        check(f"B={B},θ={tdeg} 弓形面积",
              rel_eq(A_bow, A_bow_num, 0.001),
              f"公式={A_bow:.6f}, 数值={A_bow_num:.6f}")

        # 部分充水: 多个水深
        for frac in [0.2, 0.4, 0.6, 0.8]:
            h_in_arch = H_arch * frac
            h = H_straight + h_in_arch
            A_code = calculate_horseshoe_area(B, H, tr, h) - B * H_straight
            A_num = numerical_area(B, H, tr, h, 50000) - B * H_straight
            check(f"B={B},θ={tdeg} 拱部{frac * 100:.0f}%充水",
                  rel_eq(A_code, A_num, 0.001),
                  f"代码={A_code:.6f}, 数值={A_num:.6f}")

        print(f"    B={B},θ={tdeg}°: 弓形面积={A_bow:.4f} ✓")


# ============================================================
# 验证10: 湿周公式的拱部弧长推导
# ============================================================
def test_arch_perimeter_formula():
    print("\n" + "=" * 70)
    print("验证10: 湿周公式 — 拱部弧长推导验证")
    print("=" * 70)
    print("  全拱弧长 = R·θ")
    print("  部分拱弧长 = 全弧 - 干燥段弧长")
    print("  干燥段弧长 = 2R·arccos(d/R), d=R-h_dry")

    configs = [
        (3.0, 4.0, 180), (3.0, 4.0, 150), (3.0, 4.0, 120),
        (4.0, 5.5, 180), (5.0, 6.5, 120),
    ]
    for B, H, tdeg in configs:
        tr = math.radians(tdeg)
        R_arch, H_arch, H_straight, cy = arch_geometry(B, H, tr)

        # 全弧长
        full_arc = R_arch * tr
        # 满水时湿周 = B + 2·H_s + R·θ
        P_full = calculate_horseshoe_perimeter(B, H, tr, H)
        P_full_exp = B + 2 * H_straight + full_arc
        check(f"B={B},θ={tdeg} 满水湿周",
              abs_eq(P_full, P_full_exp, 0.001),
              f"code={P_full:.6f}, exp={P_full_exp:.6f}")

        # 部分充水的弧长
        for frac in [0.2, 0.4, 0.6, 0.8]:
            h_in_arch = H_arch * frac
            h = H_straight + h_in_arch
            P_code = calculate_horseshoe_perimeter(B, H, tr, h)
            # 减去底边和直墙后的弧段
            arc_code = P_code - B - 2 * H_straight

            # 独立计算: 用角度算弧长
            h_dry = H_arch - h_in_arch
            d_temp = R_arch - h_dry
            acos_arg = max(-1, min(1, d_temp / R_arch))
            alpha_temp = math.acos(acos_arg)
            arc_dry = 2 * R_arch * alpha_temp
            arc_wet = full_arc - arc_dry

            check(f"B={B},θ={tdeg} 拱弧{frac * 100:.0f}%",
                  abs_eq(arc_code, arc_wet, 0.001),
                  f"code_arc={arc_code:.6f}, calc_arc={arc_wet:.6f}")

        print(f"    B={B},θ={tdeg}°: 全弧长={full_arc:.4f} ✓")


# ============================================================
# 主函数
# ============================================================
if __name__ == '__main__':
    print("=" * 70)
    print(" 圆拱直墙型隧洞 几何公式 正确性全面验证")
    print("=" * 70)

    test_geometry_params()
    test_code_vs_analytical()
    test_numerical_area()
    test_numerical_perimeter()
    test_boundary_continuity()
    test_special_values()
    test_monotonicity()
    test_halfwidth_consistency()
    test_arch_area_formula()
    test_arch_perimeter_formula()

    print("\n" + "=" * 70)
    print(f" 验证完成: PASS={PASS_COUNT}, FAIL={FAIL_COUNT}")
    print("=" * 70)
    if ERRORS:
        print("\n失败项:")
        for e in ERRORS:
            print(f"  {e}")
    else:
        print("\n✓ 所有几何公式验证通过!")

    sys.exit(1 if FAIL_COUNT > 0 else 0)
