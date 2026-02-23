# -*- coding: utf-8 -*-
"""
明渠3种断面几何公式正确性验证

验证内容:
  1. 梯形明渠: A = (b + m·h)·h,  P = b + 2h√(1+m²),  R = A/P
  2. 矩形明渠: A = b·h,  P = b + 2h,  R = A/P  (梯形 m=0 特例)
  3. 圆形明渠: θ = 2·arccos(1-2y/D),  A = D²/8·(θ-sinθ),  P = D/2·θ,  R = A/P

验证方法:
  - 手工计算值对比
  - 边界条件检验
  - 交叉一致性校验（梯形m=0 vs 矩形）
  - 圆形满管特征值校验
"""

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from 渠系建筑物断面计算.明渠设计 import (
    calculate_area,
    calculate_wetted_perimeter,
    calculate_hydraulic_radius,
    calculate_flow_rate,
    get_circular_coefficients_for_y_over_D,
    calculate_circular_hydraulic_params,
    calculate_circular_flow_capacity,
)

PASS = 0
FAIL = 0


def check(name: str, actual, expected, tol=1e-6):
    global PASS, FAIL
    diff = abs(actual - expected)
    ok = diff <= tol
    status = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{status}] {name}: 计算={actual:.8f}, 预期={expected:.8f}, 差={diff:.2e}")
    return ok


# ================================================================
# 一、梯形明渠几何公式验证
# ================================================================
print("=" * 70)
print("一、梯形明渠几何公式验证")
print("    A = (b + m·h)·h")
print("    P = b + 2·h·√(1+m²)")
print("    R = A / P")
print("=" * 70)

# --- 测试组1: 标准参数 b=2, h=1, m=1 ---
print("\n--- 测试1: b=2m, h=1m, m=1 ---")
b, h, m = 2.0, 1.0, 1.0
A_exp = (2 + 1 * 1) * 1  # = 3.0
P_exp = 2 + 2 * 1 * math.sqrt(1 + 1)  # = 2 + 2√2 ≈ 4.828427
R_exp = A_exp / P_exp

check("过水面积 A", calculate_area(b, h, m), A_exp)
check("湿周 P", calculate_wetted_perimeter(b, h, m), P_exp)
check("水力半径 R", calculate_hydraulic_radius(b, h, m), R_exp)

# --- 测试组2: 大边坡 b=3, h=2, m=1.5 ---
print("\n--- 测试2: b=3m, h=2m, m=1.5 ---")
b, h, m = 3.0, 2.0, 1.5
A_exp = (3 + 1.5 * 2) * 2  # = (3+3)*2 = 12.0
P_exp = 3 + 2 * 2 * math.sqrt(1 + 1.5**2)  # = 3 + 4√3.25 ≈ 10.211103
R_exp = A_exp / P_exp

check("过水面积 A", calculate_area(b, h, m), A_exp)
check("湿周 P", calculate_wetted_perimeter(b, h, m), P_exp)
check("水力半径 R", calculate_hydraulic_radius(b, h, m), R_exp)

# --- 测试组3: 小水深 b=1.5, h=0.3, m=0.75 ---
print("\n--- 测试3: b=1.5m, h=0.3m, m=0.75 ---")
b, h, m = 1.5, 0.3, 0.75
A_exp = (1.5 + 0.75 * 0.3) * 0.3  # = 1.725 * 0.3 = 0.5175
P_exp = 1.5 + 2 * 0.3 * math.sqrt(1 + 0.75**2)  # = 1.5 + 0.6√1.5625
R_exp = A_exp / P_exp

check("过水面积 A", calculate_area(b, h, m), A_exp)
check("湿周 P", calculate_wetted_perimeter(b, h, m), P_exp)
check("水力半径 R", calculate_hydraulic_radius(b, h, m), R_exp)

# --- 测试组4: 边界 h=0 ---
print("\n--- 测试4: 边界条件 h=0 ---")
b, h, m = 2.0, 0.0, 1.0
check("h=0时 A=0", calculate_area(b, h, m), 0.0)
check("h=0时 P=b", calculate_wetted_perimeter(b, h, m), b)
check("h=0时 R=0", calculate_hydraulic_radius(b, h, m), 0.0)

# --- 测试组5: 三角形断面 b=0, m>0 ---
print("\n--- 测试5: 三角形断面 b=0, h=2, m=1 ---")
b, h, m = 0.0, 2.0, 1.0
A_exp = m * h * h  # = 4.0
P_exp = 2 * h * math.sqrt(1 + m * m)  # = 4√2
R_exp = A_exp / P_exp

check("三角形 A = m·h²", calculate_area(b, h, m), A_exp)
check("三角形 P = 2h√(1+m²)", calculate_wetted_perimeter(b, h, m), P_exp)
check("三角形 R = A/P", calculate_hydraulic_radius(b, h, m), R_exp)


# ================================================================
# 二、矩形明渠几何公式验证 (m=0 特例)
# ================================================================
print("\n" + "=" * 70)
print("二、矩形明渠几何公式验证 (梯形 m=0 特例)")
print("    A = b·h")
print("    P = b + 2h")
print("    R = b·h / (b + 2h)")
print("=" * 70)

# --- 测试组1: b=2, h=1 ---
print("\n--- 测试1: b=2m, h=1m ---")
b, h, m = 2.0, 1.0, 0.0
A_exp = 2.0  # b*h
P_exp = 4.0  # b + 2h
R_exp = 0.5  # A/P

check("过水面积 A", calculate_area(b, h, m), A_exp)
check("湿周 P", calculate_wetted_perimeter(b, h, m), P_exp)
check("水力半径 R", calculate_hydraulic_radius(b, h, m), R_exp)

# --- 测试组2: b=4, h=3 ---
print("\n--- 测试2: b=4m, h=3m ---")
b, h, m = 4.0, 3.0, 0.0
A_exp = 12.0
P_exp = 10.0
R_exp = 1.2

check("过水面积 A", calculate_area(b, h, m), A_exp)
check("湿周 P", calculate_wetted_perimeter(b, h, m), P_exp)
check("水力半径 R", calculate_hydraulic_radius(b, h, m), R_exp)

# --- 测试组3: 正方形断面 b=h ---
print("\n--- 测试3: 正方形断面 b=h=2m ---")
b, h, m = 2.0, 2.0, 0.0
A_exp = 4.0
P_exp = 6.0
R_exp = 2.0 / 3.0  # 正方形 R = b/3 (当 b=h)

check("正方形 A = b²", calculate_area(b, h, m), A_exp)
check("正方形 P = 3b", calculate_wetted_perimeter(b, h, m), P_exp)
check("正方形 R = b/3", calculate_hydraulic_radius(b, h, m), R_exp)

# --- 交叉验证: 梯形m=0 应完全等同于矩形公式 ---
print("\n--- 交叉验证: 梯形(m=0) vs 矩形直接计算 ---")
for b_test, h_test in [(1.0, 0.5), (3.5, 2.1), (0.8, 0.2), (10.0, 5.0)]:
    A_trap = calculate_area(b_test, h_test, 0.0)
    P_trap = calculate_wetted_perimeter(b_test, h_test, 0.0)
    R_trap = calculate_hydraulic_radius(b_test, h_test, 0.0)
    A_rect = b_test * h_test
    P_rect = b_test + 2 * h_test
    R_rect = A_rect / P_rect
    check(f"A一致 b={b_test},h={h_test}", A_trap, A_rect)
    check(f"P一致 b={b_test},h={h_test}", P_trap, P_rect)
    check(f"R一致 b={b_test},h={h_test}", R_trap, R_rect)


# ================================================================
# 三、圆形明渠几何公式验证
# ================================================================
print("\n" + "=" * 70)
print("三、圆形明渠几何公式验证")
print("    θ = 2·arccos(1 - 2y/D)")
print("    A = (D²/8)·(θ - sinθ)")
print("    P = (D/2)·θ")
print("    R = A / P")
print("=" * 70)

# --- 测试组1: 半满 y/D=0.5 ---
print("\n--- 测试1: 半满管 y/D=0.5, D=2m ---")
D = 2.0
y_over_D = 0.5
# θ = 2·arccos(1-2×0.5) = 2·arccos(0) = π
theta_exp = math.pi
A_exp = (D**2 / 8) * (theta_exp - math.sin(theta_exp))  # = (4/8)*(π-0) = π/2
P_exp = (D / 2) * theta_exp  # = π
R_exp = A_exp / P_exp  # = (π/2)/π = 0.5 = D/4

k_A, k_P, k_R, theta = get_circular_coefficients_for_y_over_D(y_over_D)
A_calc = k_A * D**2
P_calc = k_P * D
R_calc = k_R * D

check("半满 θ = π", theta, theta_exp)
check("半满 A = πD²/4 / 2", A_calc, A_exp)
check("半满 P = πD/2", P_calc, P_exp)
check("半满 R = D/4", R_calc, D / 4)

# 使用 calculate_circular_hydraulic_params 交叉验证
params = calculate_circular_hydraulic_params(D, D * y_over_D)
check("半满 params.A", params["A"], A_exp, tol=1e-5)
check("半满 params.P", params["P"], P_exp, tol=1e-5)
check("半满 params.R", params["R"], R_exp, tol=1e-5)

# --- 测试组2: 满管 y/D→1 ---
print("\n--- 测试2: 满管 y/D≈1, D=1m ---")
D = 1.0
y_over_D = 0.9999999  # 接近满管
# 满管: θ = 2π, A = πD²/4, P = πD, R = D/4
theta_exp = 2 * math.pi
A_exp_full = math.pi * D**2 / 4
P_exp_full = math.pi * D
R_exp_full = D / 4

k_A, k_P, k_R, theta = get_circular_coefficients_for_y_over_D(y_over_D)
A_calc = k_A * D**2
P_calc = k_P * D
R_calc = k_R * D

check("满管 θ ≈ 2π", theta, theta_exp, tol=1e-4)
check("满管 A ≈ πD²/4", A_calc, A_exp_full, tol=1e-4)
check("满管 P ≈ πD", P_calc, P_exp_full, tol=1e-4)
check("满管 R ≈ D/4", R_calc, R_exp_full, tol=1e-4)

# --- 测试组3: 1/4满 y/D=0.25 ---
print("\n--- 测试3: y/D=0.25, D=2m ---")
D = 2.0
y_over_D = 0.25
# θ = 2·arccos(1-2×0.25) = 2·arccos(0.5) = 2×π/3 = 2π/3
theta_exp = 2 * math.pi / 3
A_exp = (D**2 / 8) * (theta_exp - math.sin(theta_exp))
P_exp = (D / 2) * theta_exp
R_exp = A_exp / P_exp

k_A, k_P, k_R, theta = get_circular_coefficients_for_y_over_D(y_over_D)
A_calc = k_A * D**2
P_calc = k_P * D
R_calc = k_R * D

check("1/4满 θ = 2π/3", theta, theta_exp)
check("1/4满 A", A_calc, A_exp)
check("1/4满 P = Dπ/3", P_calc, P_exp)
check("1/4满 R = A/P", R_calc, R_exp)

# --- 测试组4: 3/4满 y/D=0.75 ---
print("\n--- 测试4: y/D=0.75, D=2m ---")
D = 2.0
y_over_D = 0.75
# θ = 2·arccos(1-2×0.75) = 2·arccos(-0.5) = 2×2π/3 = 4π/3
theta_exp = 4 * math.pi / 3
A_exp = (D**2 / 8) * (theta_exp - math.sin(theta_exp))
P_exp = (D / 2) * theta_exp
R_exp = A_exp / P_exp

k_A, k_P, k_R, theta = get_circular_coefficients_for_y_over_D(y_over_D)
A_calc = k_A * D**2
P_calc = k_P * D
R_calc = k_R * D

check("3/4满 θ = 4π/3", theta, theta_exp)
check("3/4满 A", A_calc, A_exp)
check("3/4满 P", P_calc, P_exp)
check("3/4满 R", R_calc, R_exp)

# --- 测试组5: 空管 y/D=0 ---
print("\n--- 测试5: 空管 y/D→0 ---")
k_A, k_P, k_R, theta = get_circular_coefficients_for_y_over_D(0.0)
check("空管 k_A = 0", k_A, 0.0)
check("空管 k_P = 0", k_P, 0.0)
check("空管 k_R = 0", k_R, 0.0)
check("空管 θ = 0", theta, 0.0)

# --- 测试组6: 半满对称性 A(y/D=0.25) + A(y/D=0.75) 应关于半满对称 ---
print("\n--- 测试6: 几何对称性验证 ---")
D = 2.0
k_A_25, _, _, _ = get_circular_coefficients_for_y_over_D(0.25)
k_A_75, _, _, _ = get_circular_coefficients_for_y_over_D(0.75)
k_A_full = math.pi / 4  # 满管 k_A = π/4
# A(0.25) + A(0.75) 应等于满管面积 πD²/4
A_sum = (k_A_25 + k_A_75) * D**2
A_full = k_A_full * D**2
check("A(0.25)+A(0.75) = πD²/4 (对称性)", A_sum, A_full, tol=1e-5)

# P(0.25) + P(0.75) 应等于满管湿周 πD
k_P_25_val = get_circular_coefficients_for_y_over_D(0.25)[1]
k_P_75_val = get_circular_coefficients_for_y_over_D(0.75)[1]
P_sum = (k_P_25_val + k_P_75_val) * D
P_full_val = math.pi * D
check("P(0.25)+P(0.75) = πD (对称性)", P_sum, P_full_val, tol=1e-5)

# --- 测试组7: 不同直径下几何量的缩放关系 ---
print("\n--- 测试7: 缩放关系验证 (D₂=2D₁ 时 A₂=4A₁, P₂=2P₁) ---")
D1 = 1.0
D2 = 2.0
y_ratio = 0.4
p1 = calculate_circular_hydraulic_params(D1, y_ratio * D1)
p2 = calculate_circular_hydraulic_params(D2, y_ratio * D2)
check("A缩放: A(2D)/A(D) = 4", p2["A"] / p1["A"], 4.0, tol=1e-4)
check("P缩放: P(2D)/P(D) = 2", p2["P"] / p1["P"], 2.0, tol=1e-4)
check("R缩放: R(2D)/R(D) = 2", p2["R"] / p1["R"], 2.0, tol=1e-4)


# ================================================================
# 四、曼宁公式一致性验证
# ================================================================
print("\n" + "=" * 70)
print("四、曼宁公式一致性验证  Q = (1/n)·A·R^(2/3)·√i")
print("=" * 70)

# --- 梯形 ---
print("\n--- 梯形: b=2, h=1.5, m=1, n=0.014, i=1/3000 ---")
b, h, m, n, i = 2.0, 1.5, 1.0, 0.014, 1.0/3000
A = calculate_area(b, h, m)
R = calculate_hydraulic_radius(b, h, m)
Q_manual = (1/n) * A * R**(2.0/3.0) * math.sqrt(i)
Q_func = calculate_flow_rate(b, h, i, n, m)
check("梯形曼宁Q", Q_func, Q_manual)

# --- 矩形 ---
print("\n--- 矩形: b=3, h=1, n=0.015, i=1/2000 ---")
b, h, m, n, i = 3.0, 1.0, 0.0, 0.015, 1.0/2000
A = calculate_area(b, h, m)
R = calculate_hydraulic_radius(b, h, m)
Q_manual = (1/n) * A * R**(2.0/3.0) * math.sqrt(i)
Q_func = calculate_flow_rate(b, h, i, n, m)
check("矩形曼宁Q", Q_func, Q_manual)

# --- 圆形 ---
print("\n--- 圆形: D=1.5, y=0.6D, n=0.013, i=1/1500 ---")
D, n_c, slope_inv_c = 1.5, 0.013, 1500
y_c = 0.6 * D
params = calculate_circular_hydraulic_params(D, y_c)
A_c = params["A"]
R_c = params["R"]
i_c = 1.0 / slope_inv_c
Q_manual = (1/n_c) * A_c * R_c**(2.0/3.0) * math.sqrt(i_c)
Q_func = calculate_circular_flow_capacity(D, n_c, slope_inv_c, y_c)
check("圆形曼宁Q", Q_func, Q_manual, tol=1e-4)


# ================================================================
# 总结
# ================================================================
print("\n" + "=" * 70)
total = PASS + FAIL
print(f"验证结果: 通过 {PASS}/{total}, 失败 {FAIL}/{total}")
if FAIL == 0:
    print("结论: 3种明渠断面的所有几何公式均正确 ✓")
else:
    print(f"结论: 有 {FAIL} 项验证未通过，请检查 ✗")
print("=" * 70)
