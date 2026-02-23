# -*- coding: utf-8 -*-
"""
马蹄形标准Ⅰ型/Ⅱ型 几何公式独立验证脚本

验证方法:
1. 常量自洽性: θ 满足 cos(θ)-sin(θ)=(t-1)/t, c=2θ-2(t-1)/t·sin(θ)
2. 解析推导验证: 从圆方程出发独立推导每段面积/湿周/水面宽公式
3. 数值积分交叉验证: 用高精度梯形积分独立计算面积，与解析公式对比
4. 数值弧长交叉验证: 用数值积分独立计算湿周，与解析公式对比
5. 边界连续性: A, B, P 在 h=e 和 h=r 处连续
6. 特殊值检验: h=0, h=e, h=r, h=2r
7. 单调性: 面积/湿周随水深单调递增
"""

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "渠系建筑物断面计算"))
from 隧洞设计 import (
    calculate_horseshoe_std_elements,
    HORSESHOE_T1, HORSESHOE_THETA1, HORSESHOE_C1,
    HORSESHOE_T2, HORSESHOE_THETA2, HORSESHOE_C2,
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
# 第一部分: 几何形状定义 — 从圆方程出发独立计算半宽
# ============================================================
#
# 马蹄形断面由3段圆弧组成(以r为基本参数):
#   ① 底拱(倒拱): 圆心(0, t·r), 半径 t·r — 从 h=0 到 h=e
#   ② 侧拱: 左圆心((t-1)·r, r), 右圆心(-(t-1)·r, r), 半径 t·r — 从 h=e 到 h=r
#   ③ 顶拱: 圆心(0, r), 半径 r — 从 h=r 到 h=2r
#
# 其中 e = t·r·(1-cos θ), θ 是底拱在连接点处的半角

def half_width_from_circles(t, theta, r, h):
    """从圆方程直接计算半宽(不使用被测公式)"""
    Ra = t * r
    e = Ra * (1 - math.cos(theta))

    if h <= 0:
        return 0.0
    elif h <= e:
        # 底拱: x² + (h - Ra)² = Ra²  =>  x = sqrt(Ra² - (h-Ra)²)
        val = Ra ** 2 - (h - Ra) ** 2
        return math.sqrt(max(0, val))
    elif h <= r:
        # 右侧拱: (x + (t-1)·r)² + (h - r)² = (t·r)²
        # x = -(t-1)·r + sqrt((t·r)² - (h-r)²)
        val = (t * r) ** 2 - (h - r) ** 2
        return -(t - 1) * r + math.sqrt(max(0, val))
    elif h <= 2 * r:
        # 顶拱: x² + (h - r)² = r²  =>  x = sqrt(r² - (h-r)²)
        val = r ** 2 - (h - r) ** 2
        return math.sqrt(max(0, val))
    return 0.0


def numerical_area(t, theta, r, h, N=10000):
    """用梯形法对半宽函数进行数值积分计算面积"""
    if h <= 0:
        return 0.0
    dy = h / N
    total = 0.0
    for i in range(N):
        y0 = i * dy
        y1 = (i + 1) * dy
        w0 = 2 * half_width_from_circles(t, theta, r, y0)
        w1 = 2 * half_width_from_circles(t, theta, r, y1)
        total += (w0 + w1) / 2 * dy
    return total


def numerical_perimeter(t, theta, r, h, N=10000):
    """
    用数值微分+积分计算湿周(沿轮廓的弧长, 不含水面宽)
    从 (0,0) 底部开始, 沿右侧轮廓到 (w(h), h), 再对称加上左侧
    """
    if h <= 0:
        return 0.0
    dy = h / N
    total = 0.0
    for i in range(N):
        y0 = i * dy
        y1 = (i + 1) * dy
        x0 = half_width_from_circles(t, theta, r, y0)
        x1 = half_width_from_circles(t, theta, r, y1)
        ds = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
        total += ds
    return 2 * total  # 左右对称


def analytical_elements(t, theta, c, r, h):
    """从代码公式计算 A, B, P (独立于被测模块的纯公式复现)"""
    Ra = t * r
    e = Ra * (1 - math.cos(theta))

    if h <= 0:
        return 0.0, 0.0, 0.0
    elif h <= e:
        cos_val = max(-1, min(1, 1 - h / Ra))
        beta = math.acos(cos_val)
        A = Ra ** 2 * (beta - 0.5 * math.sin(2 * beta))
        B = 2 * Ra * math.sin(beta)
        P = 2 * Ra * beta
        return A, B, P
    elif h <= r:
        sin_val = max(-1, min(1, (1 - h / r) / t))
        alpha = math.asin(sin_val)
        A = Ra ** 2 * (c - alpha - 0.5 * math.sin(2 * alpha)
                       + ((2 * t - 2) / t) * math.sin(alpha))
        B = 2 * r * (t * math.cos(alpha) - t + 1)
        P = 2 * t * r * (2 * theta - alpha)
        return A, B, P
    elif h <= 2 * r:
        cos_val = max(-1, min(1, h / r - 1))
        phi_half = math.acos(cos_val)
        phi = 2 * phi_half
        A = r ** 2 * (t ** 2 * c + 0.5 * (math.pi - phi + math.sin(phi)))
        B = 2 * r * math.sin(phi_half)
        P = 4 * t * r * theta + r * (math.pi - phi)
        return A, B, P
    return 0.0, 0.0, 0.0


# ============================================================
# 第一组: 常量自洽性验证
# ============================================================
def test_constants():
    print("\n" + "=" * 70)
    print("验证1: 常量自洽性 (θ, t, c 的数学关系)")
    print("=" * 70)

    for label, t, theta, c in [
        ("Ⅰ型", HORSESHOE_T1, HORSESHOE_THETA1, HORSESHOE_C1),
        ("Ⅱ型", HORSESHOE_T2, HORSESHOE_THETA2, HORSESHOE_C2),
    ]:
        print(f"\n  --- 马蹄形{label} (t={t}, θ={theta:.6f} rad = {math.degrees(theta):.4f}°) ---")

        # 约束: cos(θ) - sin(θ) = (t-1)/t
        lhs = math.cos(theta) - math.sin(theta)
        rhs = (t - 1) / t
        print(f"    cos(θ)-sin(θ) = {lhs:.10f}")
        print(f"    (t-1)/t       = {rhs:.10f}")
        print(f"    差值          = {abs(lhs - rhs):.2e}")
        check(f"{label} cos(θ)-sin(θ)=(t-1)/t", abs(lhs - rhs) < 1e-5,
              f"lhs={lhs:.10f}, rhs={rhs:.10f}")

        # c = 2θ - 2(t-1)/t·sin(θ)
        c_calc = 2 * theta - 2 * (t - 1) / t * math.sin(theta)
        print(f"    c(代码)       = {c:.6f}")
        print(f"    c(计算)       = {c_calc:.6f}")
        print(f"    差值          = {abs(c - c_calc):.2e}")
        check(f"{label} c=2θ-2(t-1)/t·sin(θ)", abs(c - c_calc) < 1e-4,
              f"c_code={c:.6f}, c_calc={c_calc:.6f}")

        # θ 的度数验证
        theta_deg = math.degrees(theta)
        if label == "Ⅰ型":
            check(f"{label} θ≈16.874°", abs(theta_deg - 16.874) < 0.01,
                  f"θ={theta_deg:.4f}°")
        else:
            check(f"{label} θ≈24.295°", abs(theta_deg - 24.295) < 0.01,
                  f"θ={theta_deg:.4f}°")

        # 底拱高度 e = t·r·(1-cos θ)
        # 当 r=1 时:
        e = t * (1 - math.cos(theta))
        print(f"    底拱高度 e/r  = {e:.6f}")
        print(f"    总高度/r      = 2.0")
        print(f"    e/2r 比例     = {e / 2:.4f} ({e / 2 * 100:.2f}%)")


# ============================================================
# 第二组: 代码 vs 解析公式一致性
# ============================================================
def test_code_vs_analytical():
    print("\n" + "=" * 70)
    print("验证2: 代码函数 vs 解析公式 一致性")
    print("=" * 70)

    for label, stype, t, theta, c in [
        ("Ⅰ型", 1, HORSESHOE_T1, HORSESHOE_THETA1, HORSESHOE_C1),
        ("Ⅱ型", 2, HORSESHOE_T2, HORSESHOE_THETA2, HORSESHOE_C2),
    ]:
        print(f"\n  --- 马蹄形{label} ---")
        for r in [1.0, 1.5, 2.0, 3.0]:
            Ra = t * r
            e = Ra * (1 - math.cos(theta))
            # 采样各段
            test_depths = [
                0.001,
                e * 0.3, e * 0.5, e * 0.8, e * 0.999,  # 底拱段
                e * 1.001, (e + r) * 0.5, r * 0.5, r * 0.8, r * 0.999,  # 侧拱段
                r * 1.001, r * 1.3, r * 1.5, r * 1.8, 2 * r * 0.99,  # 顶拱段
            ]
            for h in test_depths:
                if h <= 0 or h > 2 * r:
                    continue
                A_code, B_code, P_code, ok = calculate_horseshoe_std_elements(stype, r, h)
                A_ana, B_ana, P_ana = analytical_elements(t, theta, c, r, h)
                if not ok:
                    check(f"{label} r={r} h={h:.4f} 代码返回ok",
                          False, "calculate_horseshoe_std_elements 返回 ok=False")
                    continue
                check(f"{label} r={r} h={h:.4f} A一致",
                      abs_eq(A_code, A_ana, 1e-8),
                      f"code={A_code:.8f}, ana={A_ana:.8f}")
                check(f"{label} r={r} h={h:.4f} B一致",
                      abs_eq(B_code, B_ana, 1e-8),
                      f"code={B_code:.8f}, ana={B_ana:.8f}")
                check(f"{label} r={r} h={h:.4f} P一致",
                      abs_eq(P_code, P_ana, 1e-8),
                      f"code={P_code:.8f}, ana={P_ana:.8f}")


# ============================================================
# 第三组: 数值积分交叉验证面积
# ============================================================
def test_numerical_area():
    print("\n" + "=" * 70)
    print("验证3: 面积公式 vs 数值积分 (高精度梯形法, N=50000)")
    print("=" * 70)

    N_INTEG = 50000  # 高精度

    for label, stype, t, theta, c in [
        ("Ⅰ型", 1, HORSESHOE_T1, HORSESHOE_THETA1, HORSESHOE_C1),
        ("Ⅱ型", 2, HORSESHOE_T2, HORSESHOE_THETA2, HORSESHOE_C2),
    ]:
        print(f"\n  --- 马蹄形{label} ---")
        for r in [1.0, 2.0, 3.0]:
            Ra = t * r
            e = Ra * (1 - math.cos(theta))
            test_depths = [
                e * 0.5, e, (e + r) / 2, r, r * 1.5, 2 * r * 0.99,
            ]
            max_err = 0.0
            for h in test_depths:
                if h <= 0 or h > 2 * r:
                    continue
                A_ana, _, _ = analytical_elements(t, theta, c, r, h)
                A_num = numerical_area(t, theta, r, h, N_INTEG)
                err = abs(A_ana - A_num)
                rel = err / A_num * 100 if A_num > 1e-9 else 0
                max_err = max(max_err, rel)
                check(f"{label} r={r} h={h:.3f} 面积数值验证",
                      rel < 0.01,  # 相对误差 < 0.01%
                      f"解析={A_ana:.6f}, 数值={A_num:.6f}, 相对误差={rel:.4f}%")
            print(f"    r={r}: 最大相对误差 = {max_err:.6f}%")


# ============================================================
# 第四组: 数值弧长交叉验证湿周
# ============================================================
def test_numerical_perimeter():
    print("\n" + "=" * 70)
    print("验证4: 湿周公式 vs 数值弧长 (N=50000)")
    print("=" * 70)

    N_INTEG = 50000

    for label, stype, t, theta, c in [
        ("Ⅰ型", 1, HORSESHOE_T1, HORSESHOE_THETA1, HORSESHOE_C1),
        ("Ⅱ型", 2, HORSESHOE_T2, HORSESHOE_THETA2, HORSESHOE_C2),
    ]:
        print(f"\n  --- 马蹄形{label} ---")
        for r in [1.0, 2.0, 3.0]:
            Ra = t * r
            e = Ra * (1 - math.cos(theta))
            test_depths = [
                e * 0.5, e, (e + r) / 2, r, r * 1.5, 2 * r * 0.99,
            ]
            max_err = 0.0
            for h in test_depths:
                if h <= 0 or h > 2 * r:
                    continue
                _, _, P_ana = analytical_elements(t, theta, c, r, h)
                P_num = numerical_perimeter(t, theta, r, h, N_INTEG)
                err = abs(P_ana - P_num)
                rel = err / P_num * 100 if P_num > 1e-9 else 0
                max_err = max(max_err, rel)
                check(f"{label} r={r} h={h:.3f} 湿周数值验证",
                      rel < 0.05,  # 相对误差 < 0.05% (弧长积分精度略低)
                      f"解析={P_ana:.6f}, 数值={P_num:.6f}, 相对误差={rel:.4f}%")
            print(f"    r={r}: 最大相对误差 = {max_err:.6f}%")


# ============================================================
# 第五组: 边界连续性验证
# ============================================================
def test_boundary_continuity():
    print("\n" + "=" * 70)
    print("验证5: 分段边界连续性 (h=e 和 h=r 处)")
    print("=" * 70)

    eps = 1e-7

    for label, stype, t, theta, c in [
        ("Ⅰ型", 1, HORSESHOE_T1, HORSESHOE_THETA1, HORSESHOE_C1),
        ("Ⅱ型", 2, HORSESHOE_T2, HORSESHOE_THETA2, HORSESHOE_C2),
    ]:
        print(f"\n  --- 马蹄形{label} ---")
        for r in [1.0, 1.5, 2.0, 3.0, 5.0]:
            Ra = t * r
            e = Ra * (1 - math.cos(theta))

            for h_bnd, bnd_name in [(e, "h=e (底拱→侧拱)"), (r, "h=r (侧拱→顶拱)")]:
                if h_bnd <= 0 or h_bnd >= 2 * r:
                    continue
                A_lo, B_lo, P_lo = analytical_elements(t, theta, c, r, h_bnd - eps)
                A_hi, B_hi, P_hi = analytical_elements(t, theta, c, r, h_bnd + eps)

                check(f"{label} r={r} {bnd_name} A连续",
                      abs_eq(A_lo, A_hi, 1e-4),
                      f"A_lo={A_lo:.8f}, A_hi={A_hi:.8f}, diff={abs(A_lo - A_hi):.2e}")
                check(f"{label} r={r} {bnd_name} B连续",
                      abs_eq(B_lo, B_hi, 1e-4),
                      f"B_lo={B_lo:.8f}, B_hi={B_hi:.8f}, diff={abs(B_lo - B_hi):.2e}")
                check(f"{label} r={r} {bnd_name} P连续",
                      abs_eq(P_lo, P_hi, 1e-4),
                      f"P_lo={P_lo:.8f}, P_hi={P_hi:.8f}, diff={abs(P_lo - P_hi):.2e}")


# ============================================================
# 第六组: 特殊值检验
# ============================================================
def test_special_values():
    print("\n" + "=" * 70)
    print("验证6: 特殊值检验")
    print("=" * 70)

    for label, stype, t, theta, c in [
        ("Ⅰ型", 1, HORSESHOE_T1, HORSESHOE_THETA1, HORSESHOE_C1),
        ("Ⅱ型", 2, HORSESHOE_T2, HORSESHOE_THETA2, HORSESHOE_C2),
    ]:
        print(f"\n  --- 马蹄形{label} ---")
        for r in [1.0, 2.0, 3.0]:
            Ra = t * r
            e = Ra * (1 - math.cos(theta))

            # h=0: A=0, B=0, P=0
            A0, B0, P0, ok0 = calculate_horseshoe_std_elements(stype, r, 0)
            check(f"{label} r={r} h=0 A=0", abs_eq(A0, 0.0, 1e-9))
            check(f"{label} r={r} h=0 B=0", abs_eq(B0, 0.0, 1e-9))
            check(f"{label} r={r} h=0 P=0", abs_eq(P0, 0.0, 1e-9))

            # h=r: B=2r (最宽处在springline)
            Ar, Br, Pr, okr = calculate_horseshoe_std_elements(stype, r, r)
            check(f"{label} r={r} h=r B=2r", abs_eq(Br, 2 * r, 0.001),
                  f"B={Br:.6f}, 2r={2 * r:.6f}")

            # h=2r: B=0 (顶部闭合), A=总面积
            A2r, B2r, P2r, ok2r = calculate_horseshoe_std_elements(stype, r, 2 * r)
            check(f"{label} r={r} h=2r B→0", abs_eq(B2r, 0.0, 0.01),
                  f"B={B2r:.6f}")

            # 满管面积: A = r²·(t²·c + π/2)
            A_full_expected = r ** 2 * (t ** 2 * c + math.pi / 2)
            check(f"{label} r={r} h=2r A=r²(t²c+π/2)",
                  abs_eq(A2r, A_full_expected, 0.001),
                  f"A={A2r:.6f}, exp={A_full_expected:.6f}")

            # 满管湿周: P = r·(4tθ + π)
            P_full_expected = r * (4 * t * theta + math.pi)
            check(f"{label} r={r} h=2r P=r(4tθ+π)",
                  abs_eq(P2r, P_full_expected, 0.001),
                  f"P={P2r:.6f}, exp={P_full_expected:.6f}")

            # h=e 处: B = 2·t·r·sin(θ), P = 2·t·r·θ
            Ae, Be, Pe, oke = calculate_horseshoe_std_elements(stype, r, e)
            Be_exp = 2 * t * r * math.sin(theta)
            Pe_exp = 2 * t * r * theta
            check(f"{label} r={r} h=e B=2tR·sinθ", abs_eq(Be, Be_exp, 0.001),
                  f"B={Be:.6f}, exp={Be_exp:.6f}")
            check(f"{label} r={r} h=e P=2tR·θ", abs_eq(Pe, Pe_exp, 0.001),
                  f"P={Pe:.6f}, exp={Pe_exp:.6f}")

            print(f"    r={r}: 满管面积={A2r:.4f}, 满管湿周={P2r:.4f}, "
                  f"水力半径R={A2r / P2r:.4f}")


# ============================================================
# 第七组: 单调性验证
# ============================================================
def test_monotonicity():
    print("\n" + "=" * 70)
    print("验证7: 面积/湿周/水面宽 单调性")
    print("=" * 70)

    for label, stype, t, theta, c in [
        ("Ⅰ型", 1, HORSESHOE_T1, HORSESHOE_THETA1, HORSESHOE_C1),
        ("Ⅱ型", 2, HORSESHOE_T2, HORSESHOE_THETA2, HORSESHOE_C2),
    ]:
        for r in [1.0, 2.0, 3.0]:
            N = 500
            prev_A = -1
            prev_P = -1
            A_monotone = True
            P_monotone = True
            fail_h_A = None
            fail_h_P = None
            for i in range(1, N):
                h = i / N * 2 * r
                A, B, P = analytical_elements(t, theta, c, r, h)
                if A < prev_A - 1e-9:
                    A_monotone = False
                    fail_h_A = h
                if P < prev_P - 1e-9:
                    P_monotone = False
                    fail_h_P = h
                prev_A = A
                prev_P = P
            check(f"{label} r={r} 面积单调递增", A_monotone,
                  f"失败于 h={fail_h_A}" if fail_h_A else "")
            check(f"{label} r={r} 湿周单调递增", P_monotone,
                  f"失败于 h={fail_h_P}" if fail_h_P else "")


# ============================================================
# 第八组: 半宽函数从圆方程推导 vs 解析公式中的 B/2
# ============================================================
def test_halfwidth_vs_circles():
    print("\n" + "=" * 70)
    print("验证8: 水面宽 B — 圆方程直接计算 vs 解析公式")
    print("=" * 70)

    for label, stype, t, theta, c in [
        ("Ⅰ型", 1, HORSESHOE_T1, HORSESHOE_THETA1, HORSESHOE_C1),
        ("Ⅱ型", 2, HORSESHOE_T2, HORSESHOE_THETA2, HORSESHOE_C2),
    ]:
        print(f"\n  --- 马蹄形{label} ---")
        max_err = 0
        for r in [1.0, 2.0, 3.0]:
            N = 200
            for i in range(1, N):
                h = i / N * 2 * r
                w_circle = half_width_from_circles(t, theta, r, h)
                _, B_ana, _ = analytical_elements(t, theta, c, r, h)
                w_ana = B_ana / 2
                err = abs(w_circle - w_ana)
                max_err = max(max_err, err)
                check(f"{label} r={r} h={h:.4f} 半宽一致",
                      abs_eq(w_circle, w_ana, 1e-6),
                      f"circle={w_circle:.8f}, formula={w_ana:.8f}, diff={err:.2e}")
        print(f"    最大绝对误差: {max_err:.2e}")


# ============================================================
# 第九组: 圆弧相切/衔接关系验证
# ============================================================
def test_arc_tangency():
    print("\n" + "=" * 70)
    print("验证9: 圆弧衔接点处的切线方向(光滑性)")
    print("=" * 70)
    print("  注: 标准马蹄形不要求各段圆弧相切，此处仅记录衔接角度差异")

    for label, t, theta, c in [
        ("Ⅰ型", HORSESHOE_T1, HORSESHOE_THETA1, HORSESHOE_C1),
        ("Ⅱ型", HORSESHOE_T2, HORSESHOE_THETA2, HORSESHOE_C2),
    ]:
        r = 1.0
        Ra = t * r
        e = Ra * (1 - math.cos(theta))

        # 在 h=e 处, 底拱的切线斜率 vs 侧拱的切线斜率
        # 底拱在 β=θ 处: 切线方向 (cos θ, sin θ) → dy/dx = tan θ
        slope_bottom = math.tan(theta)

        # 侧拱在 α=θ 处: 参数角 φ=-θ
        # 切线方向 (t*r*sin θ, t*r*cos θ) → dy/dx = cos θ / sin θ = cot θ
        slope_side = 1.0 / math.tan(theta)

        angle_bottom = math.degrees(math.atan(slope_bottom))
        angle_side = math.degrees(math.atan(slope_side))
        angle_diff = abs(angle_bottom - angle_side)

        print(f"\n  {label} h=e 衔接点:")
        print(f"    底拱切线角度: {angle_bottom:.2f}° (tan θ = {slope_bottom:.4f})")
        print(f"    侧拱切线角度: {angle_side:.2f}° (cot θ = {slope_side:.4f})")
        print(f"    角度差: {angle_diff:.2f}°")
        print(f"    (这是标准马蹄形几何固有的角度跳变，非计算错误)")

        # 在 h=r 处, 侧拱的切线斜率 vs 顶拱的切线斜率
        # 侧拱在 α=0 处: 切线方向 (0, t*r) → 垂直 (dy/dx = ∞)
        # 顶拱在 φ=π 处: 切线方向 (0, r) → 垂直 (dy/dx = ∞)
        print(f"  {label} h=r 衔接点:")
        print(f"    侧拱切线方向: 垂直 (α=0)")
        print(f"    顶拱切线方向: 垂直 (φ/2=π/2)")
        print(f"    完美衔接 ✓")


# ============================================================
# 第十组: 横截面形状合理性
# ============================================================
def test_shape_reasonableness():
    print("\n" + "=" * 70)
    print("验证10: 横截面形状合理性")
    print("=" * 70)

    for label, stype, t, theta, c in [
        ("Ⅰ型", 1, HORSESHOE_T1, HORSESHOE_THETA1, HORSESHOE_C1),
        ("Ⅱ型", 2, HORSESHOE_T2, HORSESHOE_THETA2, HORSESHOE_C2),
    ]:
        r = 1.0
        Ra = t * r
        e = Ra * (1 - math.cos(theta))
        A_full, _, P_full = analytical_elements(t, theta, c, r, 2 * r)

        # 总面积应小于外接矩形面积 (2r × 2r)
        A_rect = 2 * r * 2 * r
        check(f"{label} 总面积<外接矩形", A_full < A_rect,
              f"A={A_full:.4f}, 矩形={A_rect:.4f}")

        # 总面积应大于圆面积的某个比例
        A_circle = math.pi * r ** 2
        ratio = A_full / A_circle
        print(f"\n  {label}: A_total/πr² = {ratio:.4f}")
        print(f"    总面积 = {A_full:.6f} r²")
        print(f"    总湿周 = {P_full:.6f} r")
        print(f"    满管水力半径 R = {A_full / P_full:.6f} r")
        print(f"    底拱高度 e = {e:.6f} r ({e / (2 * r) * 100:.2f}% of H)")

        check(f"{label} 面积/圆面积>1.0", ratio > 1.0,
              f"ratio={ratio:.4f}")
        check(f"{label} 面积/圆面积<4/π≈1.273", ratio < 4 / math.pi,
              f"ratio={ratio:.4f}")


# ============================================================
# 主函数
# ============================================================
if __name__ == '__main__':
    print("=" * 70)
    print(" 马蹄形标准Ⅰ型/Ⅱ型 几何公式 正确性全面验证")
    print("=" * 70)

    test_constants()
    test_code_vs_analytical()
    test_numerical_area()
    test_numerical_perimeter()
    test_boundary_continuity()
    test_special_values()
    test_monotonicity()
    test_halfwidth_vs_circles()
    test_arc_tangency()
    test_shape_reasonableness()

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
