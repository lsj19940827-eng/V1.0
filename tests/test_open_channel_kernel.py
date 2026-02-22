# -*- coding: utf-8 -*-
"""
明渠设计计算内核 - 全面测试脚本

测试范围:
1. 基础几何计算 (面积、湿周、水力半径)
2. 曼宁公式流量计算
3. 附录E 水力最佳断面和实用经济断面公式
4. 梯形明渠完整设计流程 (多参数组合)
5. 矩形明渠完整设计流程
6. 圆形明渠完整设计流程
7. 加大流量比例查表
8. 超高计算
9. 手动参数 (宽深比/底宽) 模式
10. 边界条件和异常输入
"""

import sys
import os
import math

# 添加计算模块路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "渠系建筑物断面计算"))

from 明渠设计 import (
    # 基础几何
    calculate_area, calculate_wetted_perimeter, calculate_hydraulic_radius,
    calculate_flow_rate, calculate_velocity,
    # 附录E
    calculate_optimal_hydraulic_section, calculate_eta_from_alpha,
    calculate_beta_from_alpha_eta, calculate_all_appendix_e_schemes,
    calculate_economic_section_appendix_e,
    # 水深反算
    calculate_depth_for_flow, calculate_depth_for_flow_and_bottom_width,
    calculate_dimensions_for_flow_and_beta,
    # 主计算函数
    quick_calculate_trapezoidal, quick_calculate_rectangular, quick_calculate_circular,
    # 加大比例
    get_flow_increase_percent,
    # 圆形
    get_circular_coefficients_for_y_over_D, calculate_circular_hydraulic_params,
    calculate_circular_flow_capacity,
    # 常量
    ALPHA_VALUES, PI,
)


# ============================================================
# 测试辅助
# ============================================================
PASS_COUNT = 0
FAIL_COUNT = 0
WARN_COUNT = 0
ERRORS = []
WARNINGS = []

def check(test_name, condition, detail=""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1
        msg = f"FAIL: {test_name}"
        if detail:
            msg += f" | {detail}"
        ERRORS.append(msg)
        print(f"  ✗ {msg}")

def warn(test_name, detail=""):
    global WARN_COUNT
    WARN_COUNT += 1
    msg = f"WARN: {test_name}"
    if detail:
        msg += f" | {detail}"
    WARNINGS.append(msg)
    print(f"  ⚠ {msg}")

def approx_eq(a, b, tol=0.01):
    """相对容差比较"""
    if abs(b) < 1e-9:
        return abs(a) < tol
    return abs(a - b) / max(abs(b), 1e-9) < tol

def abs_eq(a, b, tol=0.005):
    """绝对容差比较"""
    return abs(a - b) < tol


# ============================================================
# 独立验算函数 (不依赖被测模块)
# ============================================================
def independent_manning_Q(b, h, m, n, i):
    """独立计算曼宁公式流量"""
    A = (b + m * h) * h
    X = b + 2 * h * math.sqrt(1 + m * m)
    R = A / X if X > 0 else 0
    if R <= 0 or n <= 0 or i <= 0:
        return 0
    return (1.0 / n) * A * (R ** (2.0/3.0)) * (i ** 0.5)

def independent_appendix_e_h0(Q, n, i, m):
    """独立计算附录E水力最佳断面水深
    
    推导: 水力最佳断面 A=K·h², P=2K·h, R=h/2
    曼宁公式: Q = (1/n)·K·h²·(h/2)^(2/3)·√i
    解出: h0 = [nQ·2^(2/3) / (K·√i)]^(3/8)
    """
    K = 2 * math.sqrt(1 + m*m) - m
    h0 = (n * Q * (2.0 ** (2.0/3.0)) / (K * math.sqrt(i))) ** (3.0/8.0)
    b0 = 2 * (math.sqrt(1 + m*m) - m) * h0
    beta0 = b0 / h0 if h0 > 0 else 0
    return h0, b0, beta0, K

def independent_eta(alpha):
    """独立计算η"""
    if abs(alpha - 1.0) < 1e-9:
        return 1.0
    alpha_2_5 = alpha ** 2.5
    alpha_5 = alpha ** 5
    disc = alpha_5 - alpha
    if disc < 0:
        return 1.0
    return alpha_2_5 - math.sqrt(disc)

def independent_circular_coefficients(y_over_D):
    """独立计算圆形明渠无量纲系数"""
    alpha = y_over_D
    if alpha <= 0:
        return 0, 0, 0, 0
    if alpha >= 1.0:
        alpha = 0.9999999
    acos_arg = max(-1.0, min(1.0, 1 - 2 * alpha))
    theta = 2 * math.acos(acos_arg)
    k_A = (theta - math.sin(theta)) / 8
    k_P = theta / 2
    k_R = k_A / k_P if k_P > 0 else 0
    return k_A, k_P, k_R, theta


# ============================================================
# 测试1: 基础几何计算
# ============================================================
def test_basic_geometry():
    print("\n" + "=" * 70)
    print("测试1: 基础几何计算 (面积、湿周、水力半径)")
    print("=" * 70)

    test_cases = [
        # (b, h, m, expected_A, expected_X, expected_R)
        (2.0, 1.0, 1.0, 3.0, 2 + 2*math.sqrt(2), 3.0/(2+2*math.sqrt(2))),
        (3.0, 2.0, 1.5, (3+3)*2, 3+2*2*math.sqrt(1+2.25), None),
        (1.0, 0.5, 0.0, 0.5, 2.0, 0.25),  # 矩形
        (5.0, 3.0, 2.0, (5+6)*3, 5+2*3*math.sqrt(5), None),
        (0.5, 0.2, 0.75, (0.5+0.75*0.2)*0.2, 0.5+2*0.2*math.sqrt(1+0.5625), None),
        (10.0, 5.0, 1.0, (10+5)*5, 10+2*5*math.sqrt(2), None),
        (0.0, 1.0, 1.5, 1.5*1.0, 0+2*1.0*math.sqrt(1+2.25), None),  # b=0 三角形
    ]

    for idx, (b, h, m, exp_A, exp_X, exp_R) in enumerate(test_cases):
        A = calculate_area(b, h, m)
        X = calculate_wetted_perimeter(b, h, m)
        R = calculate_hydraulic_radius(b, h, m)

        if exp_R is None:
            exp_R = exp_A / exp_X if exp_X > 0 else 0

        check(f"面积 case{idx} (b={b},h={h},m={m})",
              abs_eq(A, exp_A, 0.001),
              f"got={A:.6f}, expected={exp_A:.6f}")
        check(f"湿周 case{idx} (b={b},h={h},m={m})",
              abs_eq(X, exp_X, 0.001),
              f"got={X:.6f}, expected={exp_X:.6f}")
        check(f"水力半径 case{idx} (b={b},h={h},m={m})",
              abs_eq(R, exp_R, 0.001),
              f"got={R:.6f}, expected={exp_R:.6f}")


# ============================================================
# 测试2: 曼宁公式流量计算
# ============================================================
def test_manning_formula():
    print("\n" + "=" * 70)
    print("测试2: 曼宁公式流量计算")
    print("=" * 70)

    test_cases = [
        # (b, h, i, n, m)
        (2.0, 1.0, 1/3000, 0.014, 1.0),
        (3.0, 2.0, 1/5000, 0.016, 1.5),
        (1.5, 0.8, 1/2000, 0.013, 0.0),  # 矩形
        (5.0, 3.0, 1/4000, 0.020, 2.0),
        (0.5, 0.3, 1/1000, 0.011, 0.5),
        (10.0, 4.0, 1/8000, 0.025, 1.0),
        (1.0, 1.0, 1/500, 0.014, 1.0),
        (0.8, 0.5, 1/1500, 0.012, 0.75),
    ]

    for idx, (b, h, i, n, m) in enumerate(test_cases):
        Q_module = calculate_flow_rate(b, h, i, n, m)
        Q_expected = independent_manning_Q(b, h, m, n, i)

        check(f"曼宁流量 case{idx} (b={b},h={h},n={n},i=1/{1/i:.0f},m={m})",
              approx_eq(Q_module, Q_expected, 0.001),
              f"module={Q_module:.6f}, independent={Q_expected:.6f}")

        # 验证 V = Q/A
        A = calculate_area(b, h, m)
        V = calculate_velocity(Q_module, A)
        V_expected = Q_module / A if A > 0 else 0
        check(f"流速一致性 case{idx}",
              abs_eq(V, V_expected, 0.0001),
              f"V={V:.6f}, Q/A={V_expected:.6f}")


# ============================================================
# 测试3: 附录E 水力最佳断面公式
# ============================================================
def test_appendix_e_formulas():
    print("\n" + "=" * 70)
    print("测试3: 附录E 水力最佳断面公式")
    print("=" * 70)

    test_params = [
        # (Q, n, i, m)
        (5.0, 0.014, 1/3000, 1.0),
        (10.0, 0.016, 1/5000, 1.5),
        (1.0, 0.013, 1/2000, 0.75),
        (20.0, 0.020, 1/4000, 2.0),
        (0.5, 0.011, 1/1000, 0.5),
        (50.0, 0.025, 1/8000, 1.0),
        (2.0, 0.014, 1/1500, 1.25),
        (100.0, 0.017, 1/6000, 1.5),
    ]

    for idx, (Q, n, i, m) in enumerate(test_params):
        h0, b0, beta0, K = calculate_optimal_hydraulic_section(Q, n, i, m)
        h0_exp, b0_exp, beta0_exp, K_exp = independent_appendix_e_h0(Q, n, i, m)

        check(f"K值 case{idx} (Q={Q},m={m})",
              abs_eq(K, K_exp, 0.0001),
              f"module={K:.6f}, expected={K_exp:.6f}")
        check(f"h0 case{idx}",
              abs_eq(h0, h0_exp, 0.001),
              f"module={h0:.6f}, expected={h0_exp:.6f}")
        check(f"b0 case{idx}",
              abs_eq(b0, b0_exp, 0.001),
              f"module={b0:.6f}, expected={b0_exp:.6f}")
        check(f"beta0 case{idx}",
              abs_eq(beta0, beta0_exp, 0.001),
              f"module={beta0:.6f}, expected={beta0_exp:.6f}")

        # 核心验证: 用h0和b0反算流量，应该等于Q
        Q_check = independent_manning_Q(b0, h0, m, n, i)
        check(f"h0/b0反算流量 case{idx}",
              approx_eq(Q_check, Q, 0.01),
              f"Q_check={Q_check:.6f}, Q_target={Q:.6f}, 误差={abs(Q_check-Q)/Q*100:.3f}%")


# ============================================================
# 测试4: 附录E η和β计算
# ============================================================
def test_appendix_e_eta_beta():
    print("\n" + "=" * 70)
    print("测试4: 附录E η(水深比)和β(宽深比)计算")
    print("=" * 70)

    # 测试η计算
    for alpha in ALPHA_VALUES:
        eta_module = calculate_eta_from_alpha(alpha)
        eta_expected = independent_eta(alpha)
        check(f"η(α={alpha:.2f})",
              abs_eq(eta_module, eta_expected, 0.0001),
              f"module={eta_module:.6f}, expected={eta_expected:.6f}")

    # η的数学性质验证
    # 1. α=1.00 时 η=1.0
    check("η(1.00)=1.0", abs_eq(calculate_eta_from_alpha(1.00), 1.0, 1e-9))
    # 2. α增大时 η应该单调递减 (水深减小)
    etas = [calculate_eta_from_alpha(a) for a in ALPHA_VALUES]
    for j in range(len(etas) - 1):
        check(f"η单调递减 α={ALPHA_VALUES[j]:.2f}→{ALPHA_VALUES[j+1]:.2f}",
              etas[j] >= etas[j+1],
              f"η[{j}]={etas[j]:.6f}, η[{j+1}]={etas[j+1]:.6f}")

    # 验证η满足方程: η² - 2α^2.5 × η + α = 0
    print("  --- 验证η满足二次方程 ---")
    for alpha in ALPHA_VALUES:
        eta = calculate_eta_from_alpha(alpha)
        residual = eta**2 - 2 * alpha**2.5 * eta + alpha
        check(f"η方程残差 α={alpha:.2f}",
              abs(residual) < 0.001,
              f"η²-2α^2.5η+α = {residual:.8f}")

    # 验证β = (α/η²)×K - m 的一致性
    print("  --- 验证β公式 ---")
    for m in [0.5, 1.0, 1.5, 2.0]:
        K = 2 * math.sqrt(1 + m*m) - m
        for alpha in ALPHA_VALUES:
            eta = calculate_eta_from_alpha(alpha)
            beta = calculate_beta_from_alpha_eta(alpha, eta, K, m)
            beta_expected = (alpha / (eta * eta)) * K - m
            check(f"β公式 (m={m},α={alpha:.2f})",
                  abs_eq(beta, beta_expected, 0.0001),
                  f"module={beta:.6f}, expected={beta_expected:.6f}")


# ============================================================
# 测试5: 附录E 所有方案的流量一致性
# ============================================================
def test_appendix_e_schemes_consistency():
    print("\n" + "=" * 70)
    print("测试5: 附录E方案流量一致性 (各α方案的流量应都等于Q)")
    print("=" * 70)

    test_params = [
        (5.0, 0.014, 1/3000, 1.0),
        (10.0, 0.016, 1/5000, 1.5),
        (1.0, 0.013, 1/2000, 0.0),   # 矩形 m=0
        (20.0, 0.020, 1/4000, 2.0),
        (0.3, 0.011, 1/800, 0.75),
        (50.0, 0.017, 1/6000, 1.0),
    ]

    for idx, (Q, n, i, m) in enumerate(test_params):
        schemes = calculate_all_appendix_e_schemes(Q, n, i, m)
        check(f"方案列表非空 case{idx}", len(schemes) == 6, f"count={len(schemes)}")

        for scheme in schemes:
            alpha = scheme['alpha']
            b_s = scheme['b']
            h_s = scheme['h']
            V_s = scheme['V']
            A_s = scheme['A']

            # 独立反算流量
            Q_check = independent_manning_Q(b_s, h_s, m, n, i)
            check(f"方案流量一致 case{idx} α={alpha:.2f}",
                  approx_eq(Q_check, Q, 0.02),
                  f"Q_check={Q_check:.4f}, Q={Q:.4f}, 误差={abs(Q_check-Q)/Q*100:.2f}%")

            # 验证 V = Q/A
            V_check = Q / A_s if A_s > 0 else 0
            check(f"方案流速 case{idx} α={alpha:.2f}",
                  abs_eq(V_s, V_check, 0.01),
                  f"V_scheme={V_s:.4f}, Q/A={V_check:.4f}")

            # 验证面积增加确实约为 α 倍
            A_optimal = schemes[0]['A']  # α=1.00 的面积
            area_ratio = A_s / A_optimal if A_optimal > 0 else 0
            check(f"面积比 case{idx} α={alpha:.2f}",
                  approx_eq(area_ratio, alpha, 0.02),
                  f"A/A0={area_ratio:.4f}, α={alpha:.2f}")


# ============================================================
# 测试6: 梯形明渠完整设计 - 多参数试算
# ============================================================
def test_trapezoidal_full_design():
    print("\n" + "=" * 70)
    print("测试6: 梯形明渠完整设计 - 大量参数组合试算")
    print("=" * 70)

    # 广泛的参数组合
    test_cases = [
        # (Q, m, n, slope_inv, v_min, v_max, desc)
        (5.0, 1.0, 0.014, 3000, 0.1, 100.0, "标准案例-截图参数"),
        (5.0, 1.0, 0.014, 3000, 0.5, 3.0, "截图参数-严格流速"),
        (1.0, 1.0, 0.014, 2000, 0.3, 2.0, "小流量"),
        (0.5, 0.75, 0.013, 1500, 0.2, 2.5, "极小流量"),
        (10.0, 1.5, 0.016, 5000, 0.5, 3.0, "中等流量"),
        (20.0, 1.5, 0.020, 4000, 0.6, 2.5, "较大流量"),
        (50.0, 2.0, 0.025, 8000, 0.5, 2.0, "大流量"),
        (100.0, 1.0, 0.017, 6000, 0.6, 3.0, "特大流量"),
        (0.1, 1.0, 0.011, 500, 0.1, 5.0, "微小流量陡坡"),
        (3.0, 0.5, 0.014, 2500, 0.3, 3.0, "小边坡"),
        (3.0, 2.5, 0.014, 2500, 0.3, 3.0, "大边坡"),
        (5.0, 1.0, 0.030, 3000, 0.1, 2.0, "高糙率"),
        (5.0, 1.0, 0.010, 3000, 0.5, 5.0, "低糙率"),
        (5.0, 1.0, 0.014, 500, 0.5, 5.0, "陡坡"),
        (5.0, 1.0, 0.014, 10000, 0.1, 2.0, "缓坡"),
        (200.0, 1.5, 0.020, 10000, 0.5, 2.0, "超大流量缓坡"),
        (0.05, 0.5, 0.012, 800, 0.1, 3.0, "极微流量"),
        (15.0, 1.0, 0.015, 3500, 0.4, 2.5, "中等参数"),
    ]

    for idx, (Q, m, n, slope_inv, v_min, v_max, desc) in enumerate(test_cases):
        result = quick_calculate_trapezoidal(Q, m, n, slope_inv, v_min, v_max)
        i = 1.0 / slope_inv

        if not result['success']:
            warn(f"case{idx} ({desc})", f"计算未成功: {result.get('error_message','')}")
            continue

        b = result['b_design']
        h = result['h_design']
        V = result['V_design']
        A = result['A_design']
        X = result['X_design']
        R = result['R_design']
        beta = result['Beta_design']

        # --- 独立验算: 面积 ---
        A_exp = (b + m * h) * h
        check(f"[{desc}] 面积", abs_eq(A, A_exp, 0.01),
              f"A={A}, expected={A_exp:.3f}")

        # --- 独立验算: 湿周 ---
        X_exp = b + 2 * h * math.sqrt(1 + m*m)
        check(f"[{desc}] 湿周", abs_eq(X, X_exp, 0.01),
              f"X={X}, expected={X_exp:.3f}")

        # --- 独立验算: 水力半径 ---
        R_exp = A_exp / X_exp if X_exp > 0 else 0
        check(f"[{desc}] 水力半径", abs_eq(R, R_exp, 0.01),
              f"R={R}, expected={R_exp:.3f}")

        # --- 独立验算: 流速 ---
        V_exp = Q / A_exp if A_exp > 0 else 0
        check(f"[{desc}] 流速=Q/A", approx_eq(V, V_exp, 0.02),
              f"V={V}, Q/A={V_exp:.4f}")

        # --- 独立验算: 曼宁公式反算流量 ---
        Q_check = independent_manning_Q(b, h, m, n, i)
        check(f"[{desc}] 流量反算",
              approx_eq(Q_check, Q, 0.03),
              f"Q_manning={Q_check:.4f}, Q_design={Q}, 误差={abs(Q_check-Q)/Q*100:.2f}%")

        # --- 宽深比验证 ---
        beta_exp = b / h if h > 0 else 0
        check(f"[{desc}] 宽深比", abs_eq(beta, beta_exp, 0.01),
              f"beta={beta}, b/h={beta_exp:.3f}")

        # --- 流速约束验证 ---
        check(f"[{desc}] 流速>v_min", V > v_min or approx_eq(V, v_min, 0.05),
              f"V={V:.3f}, v_min={v_min}")
        check(f"[{desc}] 流速<v_max", V < v_max or approx_eq(V, v_max, 0.05),
              f"V={V:.3f}, v_max={v_max}")

        # --- 加大流量工况验证 ---
        inc = result['increase_percent']
        Q_inc = result['Q_increased']
        Q_inc_exp = Q * (1 + inc / 100)
        check(f"[{desc}] 加大流量", approx_eq(Q_inc, Q_inc_exp, 0.01),
              f"Q_inc={Q_inc}, expected={Q_inc_exp:.3f}")

        h_inc = result['h_increased']
        if h_inc > 0:
            # 用加大水深反算流量
            Q_inc_check = independent_manning_Q(b, h_inc, m, n, i)
            check(f"[{desc}] 加大水深反算流量",
                  approx_eq(Q_inc_check, Q_inc, 0.03),
                  f"Q_check={Q_inc_check:.4f}, Q_inc={Q_inc}, 误差={abs(Q_inc_check-Q_inc)/Q_inc*100:.2f}%")

            # 超高验证
            Fb = result['Fb']
            Fb_exp = 0.25 * h_inc + 0.2
            check(f"[{desc}] 超高", abs_eq(Fb, Fb_exp, 0.01),
                  f"Fb={Fb}, expected={Fb_exp:.3f}")

            # 渠道高度
            H = result['h_prime']
            H_exp = h_inc + Fb
            check(f"[{desc}] 渠道高度", abs_eq(H, H_exp, 0.01),
                  f"H={H}, expected={H_exp:.3f}")

            # 加大流速
            V_inc = result['V_increased']
            A_inc_exp = (b + m * h_inc) * h_inc
            V_inc_exp = Q_inc / A_inc_exp if A_inc_exp > 0 else 0
            check(f"[{desc}] 加大流速",
                  approx_eq(V_inc, V_inc_exp, 0.03),
                  f"V_inc={V_inc}, Q_inc/A_inc={V_inc_exp:.4f}")


# ============================================================
# 测试7: 矩形明渠 (m=0 特例)
# ============================================================
def test_rectangular_design():
    print("\n" + "=" * 70)
    print("测试7: 矩形明渠 (m=0 特例)")
    print("=" * 70)

    test_cases = [
        (2.0, 0.014, 2000, 0.3, 3.0, "小流量"),
        (5.0, 0.014, 3000, 0.5, 3.0, "标准"),
        (10.0, 0.016, 5000, 0.6, 2.5, "中等流量"),
        (0.5, 0.012, 1000, 0.2, 5.0, "微小流量"),
        (30.0, 0.020, 6000, 0.5, 2.0, "大流量"),
    ]

    for idx, (Q, n, slope_inv, v_min, v_max, desc) in enumerate(test_cases):
        result = quick_calculate_rectangular(Q, n, slope_inv, v_min, v_max)
        i = 1.0 / slope_inv

        if not result['success']:
            warn(f"矩形[{desc}]", f"计算未成功: {result.get('error_message','')}")
            continue

        b = result['b_design']
        h = result['h_design']
        V = result['V_design']
        A = result['A_design']
        m = 0.0

        # 面积 = b*h (矩形)
        A_exp = b * h
        check(f"矩形[{desc}] 面积=b*h", abs_eq(A, A_exp, 0.01),
              f"A={A}, b*h={A_exp:.3f}")

        # 湿周 = b + 2h
        X = result['X_design']
        X_exp = b + 2 * h
        check(f"矩形[{desc}] 湿周=b+2h", abs_eq(X, X_exp, 0.01),
              f"X={X}, b+2h={X_exp:.3f}")

        # 流量反算
        Q_check = independent_manning_Q(b, h, 0, n, i)
        check(f"矩形[{desc}] 流量反算",
              approx_eq(Q_check, Q, 0.03),
              f"Q_check={Q_check:.4f}, Q={Q}")

        # 矩形水力最佳断面: b = 2h (宽深比=2)
        # 对于 m=0: K = 2*sqrt(1+0) - 0 = 2, b0 = 2*(1-0)*h0 = 2*h0
        beta = result['Beta_design']
        if not result.get('used_manual_beta') and not result.get('used_manual_b'):
            # 自动计算时，α=1.00的最佳断面宽深比应为2
            # 但实际选择可能是其他α值
            pass

        # 与梯形 m=0 结果对比
        result_trap = quick_calculate_trapezoidal(Q, 0.0, n, slope_inv, v_min, v_max)
        if result_trap['success']:
            check(f"矩形[{desc}] 与梯形m=0一致 (b)",
                  abs_eq(b, result_trap['b_design'], 0.001),
                  f"rect_b={b}, trap_b={result_trap['b_design']}")
            check(f"矩形[{desc}] 与梯形m=0一致 (h)",
                  abs_eq(h, result_trap['h_design'], 0.001),
                  f"rect_h={h}, trap_h={result_trap['h_design']}")


# ============================================================
# 测试8: 加大流量比例查表
# ============================================================
def test_flow_increase_percent():
    print("\n" + "=" * 70)
    print("测试8: 加大流量比例查表")
    print("=" * 70)

    # 规范表: Q<1→30%, 1≤Q<5→25%, 5≤Q<20→20%, 20≤Q<50→15%, 50≤Q<100→10%, Q≥100→5%
    expected = [
        (0.1, 30.0), (0.5, 30.0), (0.99, 30.0),
        (1.0, 25.0), (3.0, 25.0), (4.99, 25.0),
        (5.0, 20.0), (10.0, 20.0), (19.99, 20.0),
        (20.0, 15.0), (35.0, 15.0), (49.99, 15.0),
        (50.0, 10.0), (75.0, 10.0), (99.99, 10.0),
        (100.0, 5.0), (200.0, 5.0), (500.0, 5.0),
    ]

    for Q, exp_pct in expected:
        pct = get_flow_increase_percent(Q)
        check(f"加大比例 Q={Q}", abs_eq(pct, exp_pct, 0.01),
              f"got={pct}%, expected={exp_pct}%")


# ============================================================
# 测试9: 手动参数模式
# ============================================================
def test_manual_params():
    print("\n" + "=" * 70)
    print("测试9: 手动参数模式 (手动宽深比/手动底宽)")
    print("=" * 70)

    # 手动宽深比
    for beta_manual in [1.0, 1.5, 2.0, 3.0, 4.0]:
        result = quick_calculate_trapezoidal(
            5.0, 1.0, 0.014, 3000, 0.1, 100.0, manual_beta=beta_manual)
        if result['success']:
            b = result['b_design']
            h = result['h_design']
            beta_actual = b / h if h > 0 else 0
            check(f"手动β={beta_manual} 宽深比匹配",
                  approx_eq(beta_actual, beta_manual, 0.05),
                  f"actual_beta={beta_actual:.3f}")
            # 流量反算
            Q_check = independent_manning_Q(b, h, 1.0, 0.014, 1/3000)
            check(f"手动β={beta_manual} 流量",
                  approx_eq(Q_check, 5.0, 0.03),
                  f"Q_check={Q_check:.4f}")

    # 手动底宽
    for b_manual in [1.0, 1.5, 2.0, 3.0, 5.0]:
        result = quick_calculate_trapezoidal(
            5.0, 1.0, 0.014, 3000, 0.1, 100.0, manual_b=b_manual)
        if result['success']:
            b = result['b_design']
            check(f"手动b={b_manual} 底宽匹配",
                  abs_eq(b, b_manual, 0.01),
                  f"actual_b={b}")
            h = result['h_design']
            Q_check = independent_manning_Q(b, h, 1.0, 0.014, 1/3000)
            check(f"手动b={b_manual} 流量",
                  approx_eq(Q_check, 5.0, 0.03),
                  f"Q_check={Q_check:.4f}")

    # 手动加大比例
    for inc_manual in [0, 10, 20, 30, 50]:
        result = quick_calculate_trapezoidal(
            5.0, 1.0, 0.014, 3000, 0.1, 100.0, manual_increase_percent=inc_manual)
        if result['success']:
            check(f"手动加大{inc_manual}% 比例匹配",
                  abs_eq(result['increase_percent'], inc_manual, 0.01),
                  f"got={result['increase_percent']}")
            Q_inc_exp = 5.0 * (1 + inc_manual / 100)
            check(f"手动加大{inc_manual}% 流量",
                  approx_eq(result['Q_increased'], Q_inc_exp, 0.01),
                  f"Q_inc={result['Q_increased']}, expected={Q_inc_exp:.3f}")


# ============================================================
# 测试10: 圆形明渠无量纲系数
# ============================================================
def test_circular_coefficients():
    print("\n" + "=" * 70)
    print("测试10: 圆形明渠无量纲系数")
    print("=" * 70)

    test_ratios = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

    for y_D in test_ratios:
        kA, kP, kR, theta = get_circular_coefficients_for_y_over_D(y_D)
        kA_exp, kP_exp, kR_exp, theta_exp = independent_circular_coefficients(y_D)

        check(f"圆形k_A (y/D={y_D})", abs_eq(kA, kA_exp, 0.0001),
              f"got={kA:.6f}, exp={kA_exp:.6f}")
        check(f"圆形k_P (y/D={y_D})", abs_eq(kP, kP_exp, 0.0001),
              f"got={kP:.6f}, exp={kP_exp:.6f}")
        check(f"圆形k_R (y/D={y_D})", abs_eq(kR, kR_exp, 0.0001),
              f"got={kR:.6f}, exp={kR_exp:.6f}")

    # y/D = 0.5 时 theta = π, A = πD²/8, P = πD/2
    kA_half, kP_half, kR_half, theta_half = get_circular_coefficients_for_y_over_D(0.5)
    check("圆形半满 theta=π", abs_eq(theta_half, math.pi, 0.001),
          f"theta={theta_half:.6f}")
    check("圆形半满 kA=π/8", abs_eq(kA_half, math.pi/8, 0.001),
          f"kA={kA_half:.6f}, π/8={math.pi/8:.6f}")
    check("圆形半满 kP=π/2", abs_eq(kP_half, math.pi/2, 0.001),
          f"kP={kP_half:.6f}, π/2={math.pi/2:.6f}")


# ============================================================
# 测试11: 圆形明渠完整设计
# ============================================================
def test_circular_full_design():
    print("\n" + "=" * 70)
    print("测试11: 圆形明渠完整设计 - 多参数组合")
    print("=" * 70)

    test_cases = [
        # (Q, n, slope_inv, v_min, v_max, desc)
        (5.0, 0.014, 1000, 0.6, 3.0, "标准"),
        (1.0, 0.013, 2000, 0.4, 3.0, "小流量"),
        (0.5, 0.012, 1500, 0.3, 4.0, "微小流量"),
        (10.0, 0.016, 3000, 0.5, 2.5, "较大流量"),
        (2.0, 0.014, 800, 0.5, 5.0, "中等流量陡坡"),
        (0.1, 0.011, 500, 0.3, 5.0, "极小流量"),
        (3.0, 0.015, 2000, 0.4, 3.0, "中等参数"),
    ]

    for idx, (Q, n, slope_inv, v_min, v_max, desc) in enumerate(test_cases):
        result = quick_calculate_circular(Q, n, slope_inv, v_min, v_max)

        if not result.get('success'):
            warn(f"圆形[{desc}]", f"计算未成功: {result.get('error_message','')}")
            continue

        D = result['D_design']
        y = result['y_d']
        V = result['V_d']
        A = result['A_d']

        # 验证 D > 0 且 y < D
        check(f"圆形[{desc}] D>0", D > 0, f"D={D}")
        check(f"圆形[{desc}] y<D", y < D, f"y={y}, D={D}")

        # 独立计算水力参数
        if D > 0 and y > 0 and y < D:
            y_D = y / D
            kA, kP, kR, theta = independent_circular_coefficients(y_D)
            A_exp = kA * D**2
            P_exp = kP * D
            R_exp = kR * D

            check(f"圆形[{desc}] 面积", approx_eq(A, A_exp, 0.02),
                  f"A={A}, expected={A_exp:.4f}")

            # V = Q/A
            V_exp = Q / A_exp if A_exp > 0 else 0
            check(f"圆形[{desc}] 流速=Q/A", approx_eq(V, V_exp, 0.03),
                  f"V={V}, Q/A={V_exp:.4f}")

            # 曼宁公式反算流量
            slope = 1.0 / slope_inv
            if R_exp > 0:
                Q_check = (1/n) * A_exp * R_exp**(2/3) * math.sqrt(slope)
                check(f"圆形[{desc}] 流量反算",
                      approx_eq(Q_check, Q, 0.05),
                      f"Q_check={Q_check:.4f}, Q={Q}")

        # 流速约束
        check(f"圆形[{desc}] 流速≥v_min", V >= v_min or approx_eq(V, v_min, 0.05),
              f"V={V}, v_min={v_min}")
        check(f"圆形[{desc}] 流速≤v_max", V <= v_max or approx_eq(V, v_max, 0.05),
              f"V={V}, v_max={v_max}")

        # 超高
        FB = result.get('FB_d', 0)
        if FB is not None:
            check(f"圆形[{desc}] 超高=D-y", abs_eq(FB, D - y, 0.01),
                  f"FB={FB}, D-y={D-y:.4f}")


# ============================================================
# 测试12: 圆形明渠手动直径
# ============================================================
def test_circular_manual_D():
    print("\n" + "=" * 70)
    print("测试12: 圆形明渠手动直径模式")
    print("=" * 70)

    for D_manual in [1.0, 1.5, 2.0, 3.0]:
        result = quick_calculate_circular(
            Q=2.0, n=0.014, slope_inv=1500,
            v_min=0.3, v_max=5.0, manual_D=D_manual)
        if result.get('success'):
            D = result['D_design']
            check(f"手动D={D_manual} 直径匹配",
                  abs_eq(D, D_manual, 0.01),
                  f"D_design={D}")
            y = result['y_d']
            check(f"手动D={D_manual} y<D", y < D_manual,
                  f"y={y}, D={D_manual}")
            # 流量反算
            A = result['A_d']
            V = result['V_d']
            if A and V:
                Q_check = A * V
                check(f"手动D={D_manual} Q=A*V",
                      approx_eq(Q_check, 2.0, 0.05),
                      f"A*V={Q_check:.4f}")


# ============================================================
# 测试13: 水深反算一致性
# ============================================================
def test_depth_inversion():
    print("\n" + "=" * 70)
    print("测试13: 水深反算一致性 (给定Q和b，反算h应与正算一致)")
    print("=" * 70)

    test_cases = [
        # (Q_target, b, i, n, m)
        (5.0, 1.179, 1/3000, 0.014, 1.0),
        (10.0, 2.5, 1/5000, 0.016, 1.5),
        (1.0, 1.0, 1/2000, 0.013, 0.0),
        (20.0, 3.0, 1/4000, 0.020, 2.0),
        (0.5, 0.5, 1/1000, 0.011, 0.5),
    ]

    for idx, (Q, b, i, n, m) in enumerate(test_cases):
        h_inv = calculate_depth_for_flow(Q, b, i, n, m)
        if h_inv > 0:
            Q_check = independent_manning_Q(b, h_inv, m, n, i)
            check(f"水深反算 case{idx}",
                  approx_eq(Q_check, Q, 0.02),
                  f"h_inv={h_inv:.4f}, Q_back={Q_check:.4f}, Q_target={Q}")

    # 二分法水深反算
    for idx, (Q, b, i, n, m) in enumerate(test_cases):
        success, h_inv = calculate_depth_for_flow_and_bottom_width(Q, i, n, m, b)
        if success and h_inv > 0:
            Q_check = independent_manning_Q(b, h_inv, m, n, i)
            check(f"二分法水深反算 case{idx}",
                  approx_eq(Q_check, Q, 0.02),
                  f"h={h_inv:.4f}, Q_back={Q_check:.4f}, Q_target={Q}")


# ============================================================
# 测试14: 边界条件和异常输入
# ============================================================
def test_boundary_conditions():
    print("\n" + "=" * 70)
    print("测试14: 边界条件和异常输入")
    print("=" * 70)

    # Q=0
    r = quick_calculate_trapezoidal(0, 1.0, 0.014, 3000, 0.1, 100.0)
    check("Q=0 应失败", not r['success'])

    # n=0
    r = quick_calculate_trapezoidal(5.0, 1.0, 0, 3000, 0.1, 100.0)
    check("n=0 应失败", not r['success'])

    # slope_inv=0 (should fail gracefully, not crash)
    try:
        r = quick_calculate_trapezoidal(5.0, 1.0, 0.014, 0, 0.1, 100.0)
        check("slope_inv=0 应失败", not r['success'])
    except ZeroDivisionError:
        check("slope_inv=0 不应ZeroDivisionError", False, "抛出了ZeroDivisionError")

    # v_min >= v_max
    r = quick_calculate_trapezoidal(5.0, 1.0, 0.014, 3000, 5.0, 3.0)
    check("v_min>=v_max 应失败", not r['success'])

    # 负边坡
    r = quick_calculate_trapezoidal(5.0, -1.0, 0.014, 3000, 0.1, 100.0)
    check("m<0 应失败", not r['success'])

    # 面积计算: h<0 应返回0
    A = calculate_area(1.0, -1.0, 1.0)
    check("h<0 面积=0", A == 0.0, f"A={A}")

    # 流量计算: h=0 应返回0
    Q = calculate_flow_rate(1.0, 0, 1/3000, 0.014, 1.0)
    check("h=0 流量=0", Q == 0.0 or Q < 1e-9, f"Q={Q}")


# ============================================================
# 测试15: 截图参数精确验证
# ============================================================
def test_screenshot_params():
    print("\n" + "=" * 70)
    print("测试15: 截图参数精确验证 (Q=5, m=1, n=0.014, 1/3000)")
    print("=" * 70)

    # 截图中的参数
    result = quick_calculate_trapezoidal(
        Q=5.0, m=1.0, n=0.014, slope_inv=3000,
        v_min=0.1, v_max=100.0)

    check("截图参数计算成功", result['success'])

    if result['success']:
        b = result['b_design']
        h = result['h_design']
        V = result['V_design']
        beta = result['Beta_design']

        # 修正后的正确值 (旧截图值因h0公式bug而错误)
        # 旧截图显示: B=1.179, h=1.423 (错误，曼宁反算Q仅≈3.85)
        # 修正后: B=1.300, h=1.570 (曼宁反算Q≈5.0)
        print(f"  计算结果: B={b:.3f}, h={h:.3f}, β={beta:.3f}, V={V:.3f}")

        # 最重要的验证: 用曼宁公式反算流量应≈5.0
        Q_manning = independent_manning_Q(b, h, 1.0, 0.014, 1/3000)
        check("截图参数 曼宁反算流量≈5.0",
              approx_eq(Q_manning, 5.0, 0.03),
              f"Q_manning={Q_manning:.4f}")

        # 验证附录E表格: 所有α方案都应反算出Q≈5.0
        schemes = result.get('appendix_e_schemes', [])
        if schemes:
            for si, s in enumerate(schemes):
                alpha = s['alpha']
                Q_check = independent_manning_Q(s['b'], s['h'], 1.0, 0.014, 1/3000)
                check(f"表格α={alpha:.2f} 曼宁流量≈5.0",
                      approx_eq(Q_check, 5.0, 0.03),
                      f"Q_check={Q_check:.4f}")
                # β应一致
                beta_check = s['b'] / s['h'] if s['h'] > 0 else 0
                check(f"表格α={alpha:.2f} β=b/h",
                      abs_eq(s['beta'], beta_check, 0.01),
                      f"beta={s['beta']:.3f}, b/h={beta_check:.3f}")


# ============================================================
# 测试16: 圆形明渠流量容量计算
# ============================================================
def test_circular_flow_capacity():
    print("\n" + "=" * 70)
    print("测试16: 圆形明渠流量容量计算")
    print("=" * 70)

    test_cases = [
        # (D, n, slope_inv, y)
        (1.0, 0.014, 1000, 0.5),
        (2.0, 0.016, 2000, 1.0),
        (1.5, 0.013, 1500, 0.75),
        (0.8, 0.012, 800, 0.4),
        (3.0, 0.020, 3000, 1.5),
    ]

    for idx, (D, n, slope_inv, y) in enumerate(test_cases):
        Q = calculate_circular_flow_capacity(D, n, slope_inv, y)
        if Q > 0:
            # 独立验算
            slope = 1.0 / slope_inv
            kA, kP, kR, theta = independent_circular_coefficients(y / D)
            A_exp = kA * D**2
            R_exp = kR * D
            if R_exp > 0:
                Q_exp = (1/n) * A_exp * R_exp**(2/3) * math.sqrt(slope)
                check(f"圆形流量 case{idx} (D={D},y={y})",
                      approx_eq(Q, Q_exp, 0.02),
                      f"Q={Q:.4f}, Q_exp={Q_exp:.4f}")


# ============================================================
# 测试17: 大规模随机参数试算
# ============================================================
def test_mass_random_params():
    print("\n" + "=" * 70)
    print("测试17: 大规模参数扫描 (系统性参数组合)")
    print("=" * 70)

    import itertools
    Q_list = [0.5, 1.0, 5.0, 10.0, 30.0, 100.0]
    m_list = [0.0, 0.5, 1.0, 1.5, 2.0]
    n_list = [0.012, 0.014, 0.020]
    slope_inv_list = [1000, 3000, 8000]

    total = 0
    fail_cases = []

    for Q, m, n, slope_inv in itertools.product(Q_list, m_list, n_list, slope_inv_list):
        total += 1
        i = 1.0 / slope_inv
        result = quick_calculate_trapezoidal(Q, m, n, slope_inv, 0.01, 100.0)

        if not result['success']:
            fail_cases.append((Q, m, n, slope_inv, result.get('error_message', '')))
            continue

        b = result['b_design']
        h = result['h_design']
        V = result['V_design']
        A = result['A_design']

        # 核心检查1: 流量一致性
        Q_check = independent_manning_Q(b, h, m, n, i)
        if not approx_eq(Q_check, Q, 0.05):
            check(f"批量 Q={Q},m={m},n={n},1/{slope_inv} 流量不一致",
                  False, f"Q_back={Q_check:.4f}, Q={Q}, err={abs(Q_check-Q)/Q*100:.1f}%")

        # 核心检查2: 面积一致
        A_exp = (b + m * h) * h
        if not abs_eq(A, A_exp, 0.05):
            check(f"批量 Q={Q},m={m},n={n},1/{slope_inv} 面积不一致",
                  False, f"A={A}, exp={A_exp:.3f}")

        # 核心检查3: V = Q/A
        V_exp = Q / A_exp if A_exp > 0 else 0
        if not approx_eq(V, V_exp, 0.05):
            check(f"批量 Q={Q},m={m},n={n},1/{slope_inv} 流速不一致",
                  False, f"V={V}, Q/A={V_exp:.4f}")

    print(f"  批量测试: 共 {total} 组参数, {len(fail_cases)} 组计算未成功")
    for fc in fail_cases[:5]:
        print(f"    Q={fc[0]}, m={fc[1]}, n={fc[2]}, 1/{fc[3]}: {fc[4]}")


# ============================================================
# 测试18: 附录E公式数学验证 (面积确实为α倍)
# ============================================================
def test_appendix_e_area_ratio():
    print("\n" + "=" * 70)
    print("测试18: 附录E面积比验证 (A_α 应约等于 α × A_最佳)")
    print("=" * 70)

    for m in [0.0, 0.5, 1.0, 1.5, 2.0]:
        Q, n, i = 5.0, 0.014, 1/3000
        h0, b0, beta0, K = calculate_optimal_hydraulic_section(Q, n, i, m)
        A0 = (b0 + m * h0) * h0

        for alpha in ALPHA_VALUES:
            eta = calculate_eta_from_alpha(alpha)
            h = h0 * eta
            beta = calculate_beta_from_alpha_eta(alpha, eta, K, m)
            b = beta * h
            A = (b + m * h) * h
            ratio = A / A0 if A0 > 0 else 0

            check(f"面积比 m={m} α={alpha:.2f}",
                  approx_eq(ratio, alpha, 0.01),
                  f"A/A0={ratio:.4f}, α={alpha}")


# ============================================================
# 测试19: 设计结果round精度验证
# ============================================================
def test_rounding_consistency():
    print("\n" + "=" * 70)
    print("测试19: 设计结果四舍五入精度验证")
    print("=" * 70)

    result = quick_calculate_trapezoidal(5.0, 1.0, 0.014, 3000, 0.1, 100.0)
    if result['success']:
        b = result['b_design']
        h = result['h_design']
        A = result['A_design']
        X = result['X_design']
        R = result['R_design']
        V = result['V_design']

        # 用round后的b,h重新独立计算，应和结果一致
        A_recalc = round((b + 1.0 * h) * h, 3)
        X_recalc = round(b + 2 * h * math.sqrt(2), 3)
        R_recalc = round(A_recalc / X_recalc, 3) if X_recalc > 0 else 0
        V_recalc = round(5.0 / A_recalc, 3) if A_recalc > 0 else 0

        check("round后 面积一致", abs_eq(A, A_recalc, 0.002),
              f"A={A}, recalc={A_recalc}")
        check("round后 湿周一致", abs_eq(X, X_recalc, 0.002),
              f"X={X}, recalc={X_recalc}")
        check("round后 水力半径一致", abs_eq(R, R_recalc, 0.002),
              f"R={R}, recalc={R_recalc}")
        check("round后 流速一致", abs_eq(V, V_recalc, 0.005),
              f"V={V}, recalc={V_recalc}")


# ============================================================
# 测试20: 加大水深时的连续性
# ============================================================
def test_increased_flow_continuity():
    print("\n" + "=" * 70)
    print("测试20: 加大水深应大于设计水深")
    print("=" * 70)

    test_cases = [
        (5.0, 1.0, 0.014, 3000),
        (10.0, 1.5, 0.016, 5000),
        (1.0, 0.75, 0.013, 2000),
        (20.0, 2.0, 0.020, 4000),
        (50.0, 1.0, 0.017, 6000),
    ]

    for Q, m, n, slope_inv in test_cases:
        result = quick_calculate_trapezoidal(Q, m, n, slope_inv, 0.1, 100.0)
        if result['success']:
            h = result['h_design']
            h_inc = result['h_increased']
            if h_inc > 0:
                check(f"h_inc > h_design (Q={Q},m={m})",
                      h_inc > h,
                      f"h_inc={h_inc:.3f}, h_design={h:.3f}")

                # 加大流速应大于设计流速 (相同底宽，水深增大，流速增大)
                # 注意: 这个性质并不一定成立，因为面积增大比例可能大于流量增大比例
                # 但流量增大了，如果底宽不变，一般流速也应该变化
                # 这里仅验证加大水深 > 设计水深


# ============================================================
# 主测试入口
# ============================================================
if __name__ == '__main__':
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║           明渠设计计算内核 - 全面测试                              ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    test_basic_geometry()
    test_manning_formula()
    test_appendix_e_formulas()
    test_appendix_e_eta_beta()
    test_appendix_e_schemes_consistency()
    test_trapezoidal_full_design()
    test_rectangular_design()
    test_flow_increase_percent()
    test_manual_params()
    test_circular_coefficients()
    test_circular_full_design()
    test_circular_manual_D()
    test_depth_inversion()
    test_boundary_conditions()
    test_screenshot_params()
    test_circular_flow_capacity()
    test_mass_random_params()
    test_appendix_e_area_ratio()
    test_rounding_consistency()
    test_increased_flow_continuity()

    # 总结
    print("\n")
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║                        测试结果总结                                ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print(f"  通过: {PASS_COUNT}")
    print(f"  失败: {FAIL_COUNT}")
    print(f"  警告: {WARN_COUNT}")
    total = PASS_COUNT + FAIL_COUNT
    if total > 0:
        print(f"  通过率: {PASS_COUNT/total*100:.1f}%")

    if ERRORS:
        print(f"\n{'='*70}")
        print(f"  失败详情 ({len(ERRORS)} 项):")
        print(f"{'='*70}")
        for e in ERRORS:
            print(f"  {e}")

    if WARNINGS:
        print(f"\n{'='*70}")
        print(f"  警告详情 ({len(WARNINGS)} 项):")
        print(f"{'='*70}")
        for w in WARNINGS:
            print(f"  {w}")

    print(f"\n{'='*70}")
    if FAIL_COUNT == 0:
        print("  所有测试通过! ✓")
    else:
        print(f"  有 {FAIL_COUNT} 项测试失败，请检查上述详情。")
    print(f"{'='*70}")
