# -*- coding: utf-8 -*-
"""
圆形隧洞 几何公式独立验证脚本

几何结构:
  圆形断面, 直径 D, 半径 R = D/2
  过水面积: 弓形面积 A = R²·(θ - sinθ)/2, θ = 2·arccos((R-h)/R)
  湿周: χ = R·θ (弧长)
  总面积: π·R²

验证方法:
  1. 解析公式独立推导验证
  2. 数值积分面积 vs 解析公式
  3. 数值弧长湿周 vs 解析公式
  4. 特殊值 (h=0, h=R(半满), h=D(满管))
  5. 单调性
  6. 水面宽一致性 (圆方程 vs dA/dh)
"""

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "渠系建筑物断面计算"))
from 隧洞设计 import (
    calculate_circular_area,
    calculate_circular_perimeter,
    calculate_circular_outputs,
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
# 独立计算函数 (不调用被测模块)
# ============================================================
def independent_area(D, h):
    """从弓形面积公式独立计算"""
    if D <= 0 or h <= 0:
        return 0.0
    R = D / 2
    h = min(h, D)
    if h >= D:
        return math.pi * R ** 2
    theta = 2 * math.acos((R - h) / R)
    return R ** 2 * (theta - math.sin(theta)) / 2


def independent_perimeter(D, h):
    """从弧长公式独立计算"""
    if D <= 0 or h <= 0:
        return 0.0
    R = D / 2
    h = min(h, D)
    if h >= D:
        return math.pi * D
    theta = 2 * math.acos((R - h) / R)
    return R * theta


def half_width_circle(D, h):
    """从圆方程直接计算半宽"""
    if D <= 0 or h <= 0 or h >= D:
        return 0.0
    R = D / 2
    # 圆心在 (0, R), 圆方程: x² + (y-R)² = R²
    val = R ** 2 - (h - R) ** 2
    if val < 0:
        return 0.0
    return math.sqrt(val)


def numerical_area(D, h, N=50000):
    """用梯形法数值积分计算面积"""
    if h <= 0:
        return 0.0
    h = min(h, D)
    dy = h / N
    total = 0.0
    for i in range(N):
        y0 = i * dy
        y1 = (i + 1) * dy
        w0 = 2 * half_width_circle(D, y0)
        w1 = 2 * half_width_circle(D, y1)
        total += (w0 + w1) / 2 * dy
    return total


def numerical_perimeter(D, h, N=50000):
    """用数值弧长计算湿周"""
    if h <= 0:
        return 0.0
    h = min(h, D)
    dy = h / N
    total = 0.0
    for i in range(N):
        y0 = i * dy
        y1 = (i + 1) * dy
        x0 = half_width_circle(D, y0)
        x1 = half_width_circle(D, y1)
        ds = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
        total += ds
    return 2 * total  # 左右对称


# ============================================================
# 验证1: 代码 vs 独立解析公式
# ============================================================
def test_code_vs_independent():
    print("\n" + "=" * 70)
    print("验证1: 代码函数 vs 独立解析公式 一致性")
    print("=" * 70)

    diameters = [2.0, 2.41, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
    for D in diameters:
        R = D / 2
        test_depths = [
            0.001,
            D * 0.1, D * 0.2, D * 0.3, D * 0.4,
            D * 0.5,  # 半满
            D * 0.6, D * 0.7, D * 0.8, D * 0.9,
            D * 0.99,
        ]
        for h in test_depths:
            A_code = calculate_circular_area(D, h)
            P_code = calculate_circular_perimeter(D, h)
            A_ind = independent_area(D, h)
            P_ind = independent_perimeter(D, h)

            check(f"D={D},h={h:.3f} A一致",
                  abs_eq(A_code, A_ind, 1e-10),
                  f"code={A_code:.10f}, ind={A_ind:.10f}")
            check(f"D={D},h={h:.3f} P一致",
                  abs_eq(P_code, P_ind, 1e-10),
                  f"code={P_code:.10f}, ind={P_ind:.10f}")


# ============================================================
# 验证2: 面积 — 数值积分交叉验证
# ============================================================
def test_numerical_area():
    print("\n" + "=" * 70)
    print("验证2: 面积公式 vs 数值积分 (N=50000)")
    print("=" * 70)

    N_INTEG = 50000
    diameters = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
    for D in diameters:
        test_depths = [D * 0.2, D * 0.5, D * 0.8, D * 0.95]
        max_err = 0.0
        for h in test_depths:
            A_ana = independent_area(D, h)
            A_num = numerical_area(D, h, N_INTEG)
            err = abs(A_ana - A_num)
            rel = err / A_num * 100 if A_num > 1e-9 else 0
            max_err = max(max_err, rel)
            check(f"D={D},h={h:.2f} 面积数值验证",
                  rel < 0.01,
                  f"解析={A_ana:.6f}, 数值={A_num:.6f}, 相对误差={rel:.5f}%")
        print(f"    D={D}: 最大相对误差 = {max_err:.6f}%")


# ============================================================
# 验证3: 湿周 — 数值弧长交叉验证
# ============================================================
def test_numerical_perimeter():
    print("\n" + "=" * 70)
    print("验证3: 湿周公式 vs 数值弧长 (N=50000)")
    print("=" * 70)

    N_INTEG = 50000
    diameters = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
    for D in diameters:
        test_depths = [D * 0.2, D * 0.5, D * 0.8, D * 0.95]
        max_err = 0.0
        for h in test_depths:
            P_ana = independent_perimeter(D, h)
            P_num = numerical_perimeter(D, h, N_INTEG)
            err = abs(P_ana - P_num)
            rel = err / P_num * 100 if P_num > 1e-9 else 0
            max_err = max(max_err, rel)
            check(f"D={D},h={h:.2f} 湿周数值验证",
                  rel < 0.05,
                  f"解析={P_ana:.6f}, 数值={P_num:.6f}, 相对误差={rel:.5f}%")
        print(f"    D={D}: 最大相对误差 = {max_err:.6f}%")


# ============================================================
# 验证4: 特殊值检验
# ============================================================
def test_special_values():
    print("\n" + "=" * 70)
    print("验证4: 特殊值检验")
    print("=" * 70)

    diameters = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
    for D in diameters:
        R = D / 2

        # h=0: A=0, P=0
        check(f"D={D} h=0 A=0", calculate_circular_area(D, 0) == 0.0)
        check(f"D={D} h=0 P=0", calculate_circular_perimeter(D, 0) == 0.0)

        # h=R (半满): A=πR²/2, P=πR
        A_half = calculate_circular_area(D, R)
        P_half = calculate_circular_perimeter(D, R)
        check(f"D={D} h=R A=πR²/2",
              abs_eq(A_half, math.pi * R ** 2 / 2, 0.001),
              f"A={A_half:.6f}, exp={math.pi * R ** 2 / 2:.6f}")
        check(f"D={D} h=R P=πR",
              abs_eq(P_half, math.pi * R, 0.001),
              f"P={P_half:.6f}, exp={math.pi * R:.6f}")

        # h=D (满管): A=πR², P=2πR
        A_full = calculate_circular_area(D, D)
        P_full = calculate_circular_perimeter(D, D)
        check(f"D={D} h=D A=πR²",
              abs_eq(A_full, math.pi * R ** 2, 0.001),
              f"A={A_full:.6f}, exp={math.pi * R ** 2:.6f}")
        check(f"D={D} h=D P=2πR",
              abs_eq(P_full, math.pi * D, 0.001),
              f"P={P_full:.6f}, exp={math.pi * D:.6f}")

        # 水力半径验证: 半满时 R_hyd = R/2
        R_hyd_half = A_half / P_half if P_half > 0 else 0
        check(f"D={D} 半满 R_hyd=R/2",
              abs_eq(R_hyd_half, R / 2, 0.001),
              f"R_hyd={R_hyd_half:.6f}, R/2={R / 2:.6f}")

        # 满管时 R_hyd = R/2 (也是 D/4)
        R_hyd_full = A_full / P_full if P_full > 0 else 0
        check(f"D={D} 满管 R_hyd=R/2",
              abs_eq(R_hyd_full, R / 2, 0.001),
              f"R_hyd={R_hyd_full:.6f}, R/2={R / 2:.6f}")

        print(f"    D={D}: 半满面积={A_half:.4f}, 满管面积={A_full:.4f}, "
              f"半满R_hyd={R_hyd_half:.4f}")


# ============================================================
# 验证5: outputs 字段一致性
# ============================================================
def test_outputs_consistency():
    print("\n" + "=" * 70)
    print("验证5: calculate_circular_outputs 字段一致性")
    print("=" * 70)

    cases = [
        (4.0, 2.0, 0.014, 1 / 2000),
        (3.0, 1.5, 0.013, 1 / 3000),
        (5.0, 2.5, 0.016, 1 / 5000),
        (2.0, 1.0, 0.012, 1 / 1000),
        (6.0, 3.0, 0.020, 1 / 4000),
        (2.41, 1.6, 0.014, 1 / 2000),
        (8.0, 4.0, 0.018, 1 / 6000),
        (10.0, 6.0, 0.022, 1 / 8000),
        (4.0, 0.5, 0.014, 1 / 2000),
        (4.0, 3.5, 0.014, 1 / 2000),
    ]
    for D, h, n, slope in cases:
        R = D / 2
        o = calculate_circular_outputs(D, h, n, slope)

        # A, P 独立验算
        A_exp = independent_area(D, h)
        P_exp = independent_perimeter(D, h)
        check(f"D={D},h={h} A一致", abs_eq(o['A'], A_exp, 1e-8))
        check(f"D={D},h={h} P一致", abs_eq(o['P'], P_exp, 1e-8))

        # R_hyd = A/P
        R_hyd_exp = A_exp / P_exp if P_exp > 0 else 0
        check(f"D={D},h={h} R_hyd=A/P",
              abs_eq(o['R_hyd'], R_hyd_exp, 1e-8),
              f"o={o['R_hyd']:.8f}, exp={R_hyd_exp:.8f}")

        # 曼宁公式 Q = (1/n)·A·R^(2/3)·i^(1/2)
        Q_exp = (1 / n) * A_exp * (R_hyd_exp ** (2 / 3)) * (slope ** 0.5)
        check(f"D={D},h={h} Q曼宁",
              rel_eq(o['Q'], Q_exp, 0.001),
              f"o={o['Q']:.6f}, exp={Q_exp:.6f}")

        # V = Q/A
        V_exp = Q_exp / A_exp if A_exp > 0 else 0
        check(f"D={D},h={h} V=Q/A",
              abs_eq(o['V'], V_exp, 1e-6),
              f"o={o['V']:.8f}, exp={V_exp:.8f}")

        # V·A = Q
        check(f"D={D},h={h} V·A=Q",
              rel_eq(o['V'] * o['A'], o['Q'], 0.001))

        # A_total = πR²
        check(f"D={D},h={h} A_total=πR²",
              abs_eq(o['A_total'], math.pi * R ** 2, 0.001))

        # freeboard_hgt = D - h
        check(f"D={D},h={h} fb_hgt=D-h",
              abs_eq(o['freeboard_hgt'], D - h, 1e-8))

        # freeboard_pct = (A_total - A) / A_total * 100
        fb_pct_exp = (math.pi * R ** 2 - A_exp) / (math.pi * R ** 2) * 100
        check(f"D={D},h={h} fb_pct",
              abs_eq(o['freeboard_pct'], fb_pct_exp, 0.001),
              f"o={o['freeboard_pct']:.4f}, exp={fb_pct_exp:.4f}")


# ============================================================
# 验证6: 单调性
# ============================================================
def test_monotonicity():
    print("\n" + "=" * 70)
    print("验证6: 面积/湿周 单调性")
    print("=" * 70)

    diameters = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
    for D in diameters:
        N = 500
        prev_A = -1
        prev_P = -1
        A_ok = True
        P_ok = True
        fail_h_A = None
        fail_h_P = None
        for i in range(1, N):
            h = i / N * D
            A = calculate_circular_area(D, h)
            P = calculate_circular_perimeter(D, h)
            if A < prev_A - 1e-9:
                A_ok = False
                fail_h_A = h
            if P < prev_P - 1e-9:
                P_ok = False
                fail_h_P = h
            prev_A = A
            prev_P = P
        check(f"D={D} 面积单调递增", A_ok,
              f"失败于h={fail_h_A}" if fail_h_A else "")
        check(f"D={D} 湿周单调递增", P_ok,
              f"失败于h={fail_h_P}" if fail_h_P else "")


# ============================================================
# 验证7: 水面宽一致性 (圆方程 vs dA/dh)
# ============================================================
def test_halfwidth_consistency():
    print("\n" + "=" * 70)
    print("验证7: 水面宽 — 圆方程 vs dA/dh")
    print("=" * 70)

    diameters = [2.0, 3.0, 4.0, 5.0, 6.0]
    for D in diameters:
        max_err = 0.0
        N = 200
        for i in range(1, N):
            h = i / N * D
            if h <= 0.01 or h >= D - 0.01:
                continue
            w_circle = half_width_circle(D, h)

            # dA/dh ≈ B = 2w
            dh = 1e-6
            A1 = independent_area(D, h - dh)
            A2 = independent_area(D, h + dh)
            w_from_dA = (A2 - A1) / (2 * dh) / 2

            err = abs(w_circle - w_from_dA)
            max_err = max(max_err, err)
            check(f"D={D},h={h:.3f} 半宽一致",
                  abs_eq(w_circle, w_from_dA, 1e-3),
                  f"圆方程={w_circle:.6f}, dA/dh={w_from_dA:.6f}, diff={err:.2e}")
        print(f"    D={D}: 最大绝对误差 = {max_err:.2e}")


# ============================================================
# 验证8: 弓形面积公式数学推导
# ============================================================
def test_bow_area_derivation():
    print("\n" + "=" * 70)
    print("验证8: 弓形面积公式 A=R²(θ-sinθ)/2 数学推导验证")
    print("=" * 70)
    print("  圆心 (0, R), 半径 R")
    print("  水深 h, 圆心角 θ = 2·arccos((R-h)/R)")
    print("  面积 = ∫₀ʰ 2·√(R²-(y-R)²) dy = R²(θ-sinθ)/2")

    for D in [2.0, 3.0, 4.0, 5.0, 6.0]:
        R = D / 2
        for h_frac in [0.1, 0.3, 0.5, 0.7, 0.9]:
            h = D * h_frac
            # 解析
            theta = 2 * math.acos((R - h) / R)
            A_formula = R ** 2 * (theta - math.sin(theta)) / 2

            # 对称性: A(h) + A(D-h) = πR²
            A_complement = independent_area(D, D - h)
            A_sum = A_formula + A_complement

            check(f"D={D},h={h:.1f} A(h)+A(D-h)=πR²",
                  abs_eq(A_sum, math.pi * R ** 2, 0.001),
                  f"sum={A_sum:.6f}, πR²={math.pi * R ** 2:.6f}")

            # θ(h) + θ(D-h) = 2π
            theta_comp = 2 * math.acos((R - (D - h)) / R)
            check(f"D={D},h={h:.1f} θ(h)+θ(D-h)=2π",
                  abs_eq(theta + theta_comp, 2 * math.pi, 0.001),
                  f"sum={theta + theta_comp:.6f}, 2π={2 * math.pi:.6f}")

    # 半满: θ=π, A=πR²/2
    for D in [2.0, 4.0, 6.0, 10.0]:
        R = D / 2
        theta_half = 2 * math.acos(0)
        check(f"D={D} 半满θ=π", abs_eq(theta_half, math.pi, 1e-10))
        A_half = R ** 2 * (math.pi - 0) / 2
        check(f"D={D} 半满A=πR²/2", abs_eq(A_half, math.pi * R ** 2 / 2, 1e-10))


# ============================================================
# 验证9: 湿周公式数学推导
# ============================================================
def test_perimeter_derivation():
    print("\n" + "=" * 70)
    print("验证9: 湿周公式 χ=R·θ 数学推导验证")
    print("=" * 70)
    print("  弧长 = R·θ, θ为对应的圆心角")

    for D in [2.0, 4.0, 6.0, 8.0]:
        R = D / 2
        # 半满: χ = πR
        P_half = independent_perimeter(D, R)
        check(f"D={D} 半满χ=πR", abs_eq(P_half, math.pi * R, 1e-6))

        # 满管: χ = 2πR
        P_full = independent_perimeter(D, D)
        check(f"D={D} 满管χ=2πR", abs_eq(P_full, 2 * math.pi * R, 1e-6))

        # 对称性: P(h) + P(D-h) = 2πR
        for h_frac in [0.2, 0.4]:
            h = D * h_frac
            P1 = independent_perimeter(D, h)
            P2 = independent_perimeter(D, D - h)
            check(f"D={D},h={h:.1f} P(h)+P(D-h)=2πR",
                  abs_eq(P1 + P2, 2 * math.pi * R, 0.001),
                  f"sum={P1 + P2:.6f}, 2πR={2 * math.pi * R:.6f}")


# ============================================================
# 验证10: 边界与异常输入
# ============================================================
def test_boundary_conditions():
    print("\n" + "=" * 70)
    print("验证10: 边界与异常输入")
    print("=" * 70)

    # D<=0
    check("D=0 A=0", calculate_circular_area(0, 1) == 0.0)
    check("D<0 A=0", calculate_circular_area(-1, 1) == 0.0)
    check("D=0 P=0", calculate_circular_perimeter(0, 1) == 0.0)
    check("D<0 P=0", calculate_circular_perimeter(-1, 1) == 0.0)

    # h<=0
    check("h=0 A=0", calculate_circular_area(4, 0) == 0.0)
    check("h<0 A=0", calculate_circular_area(4, -1) == 0.0)
    check("h=0 P=0", calculate_circular_perimeter(4, 0) == 0.0)
    check("h<0 P=0", calculate_circular_perimeter(4, -1) == 0.0)

    # h>D (应裁切到D)
    A_over = calculate_circular_area(4, 5)
    A_full = calculate_circular_area(4, 4)
    check("h>D A=满管A", abs_eq(A_over, A_full, 1e-6),
          f"A_over={A_over:.6f}, A_full={A_full:.6f}")

    P_over = calculate_circular_perimeter(4, 5)
    P_full = calculate_circular_perimeter(4, 4)
    check("h>D P=满管P", abs_eq(P_over, P_full, 1e-6),
          f"P_over={P_over:.6f}, P_full={P_full:.6f}")

    # 极小水深
    A_tiny = calculate_circular_area(4, 0.001)
    check("极小水深 A>0", A_tiny > 0, f"A={A_tiny:.10f}")
    P_tiny = calculate_circular_perimeter(4, 0.001)
    check("极小水深 P>0", P_tiny > 0, f"P={P_tiny:.10f}")

    # 接近满管
    A_near = calculate_circular_area(4, 3.999)
    check("接近满管 A<πR²", A_near < math.pi * 4, f"A={A_near:.6f}")


# ============================================================
# 主函数
# ============================================================
if __name__ == '__main__':
    print("=" * 70)
    print(" 圆形隧洞 几何公式 正确性全面验证")
    print("=" * 70)

    test_code_vs_independent()
    test_numerical_area()
    test_numerical_perimeter()
    test_special_values()
    test_outputs_consistency()
    test_monotonicity()
    test_halfwidth_consistency()
    test_bow_area_derivation()
    test_perimeter_derivation()
    test_boundary_conditions()

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
