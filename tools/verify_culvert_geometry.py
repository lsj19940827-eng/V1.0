# -*- coding: utf-8 -*-
"""
矩形暗渠 —— 几何公式正确性独立验证

验证范围:
  1. 过水面积  A = B × h
  2. 湿周      P = B + 2h  (三面湿润: 底 + 两侧壁, 水面不计)
  3. 水力半径  R = A / P = Bh / (B + 2h)
  4. 总断面积  A_total = B × H
  5. 净空面积百分比  (A_total - A) / A_total × 100%
  6. 净空高度  H - h
  7. 曼宁公式  Q = (1/n) A R^(2/3) i^(1/2)
  8. 流速      V = Q / A = (1/n) R^(2/3) i^(1/2)
  9. 水力最佳断面理论  β = B/h = 2 → R = h/2
 10. 二分法反算水深一致性
"""

import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "渠系建筑物断面计算"))
from 矩形暗涵设计 import (
    calculate_rectangular_outputs,
    solve_water_depth_rectangular,
    quick_calculate_rectangular_culvert,
    OPTIMAL_BH_RATIO,
)

PASS = FAIL = 0
ERRORS = []

def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        msg = f"FAIL: {name}" + (f"  →  {detail}" if detail else "")
        ERRORS.append(msg)
        print(f"  ✗ {msg}")

def rel_err(a, b):
    """相对误差"""
    return abs(a - b) / max(abs(b), 1e-15)

def abs_err(a, b):
    return abs(a - b)

# ====================================================================
# 手算参考函数 —— 每一步完全独立实现
# ====================================================================

def hand_A(B, h):
    """矩形过水面积"""
    return B * h

def hand_P(B, h):
    """矩形湿周 (三面: 底+两侧)"""
    return B + 2.0 * h

def hand_R(B, h):
    """水力半径 R = Bh/(B+2h)"""
    A = B * h
    P = B + 2.0 * h
    return A / P if P > 0 else 0.0

def hand_Q(B, h, n, i):
    """曼宁公式"""
    A = hand_A(B, h)
    R = hand_R(B, h)
    if R <= 0 or n <= 0 or i <= 0:
        return 0.0
    return (1.0 / n) * A * (R ** (2.0 / 3.0)) * (i ** 0.5)

def hand_V(B, h, n, i):
    """流速 = Q / A"""
    A = hand_A(B, h)
    Q = hand_Q(B, h, n, i)
    return Q / A if A > 0 else 0.0

def hand_freeboard_pct(B, H, h):
    """净空面积百分比"""
    A_total = B * H
    A_water = B * h
    return (A_total - A_water) / A_total * 100.0 if A_total > 0 else 100.0

def hand_freeboard_hgt(H, h):
    """净空高度"""
    return H - h


# ====================================================================
print("=" * 72)
print("  矩形暗渠几何公式正确性验证")
print("=" * 72)

# ------------------------------------------------------------------
# 验证 1: 过水面积  A = B × h
# ------------------------------------------------------------------
print("\n■ 验证1: 过水面积  A = B × h")
cases_Ah = [
    (2.0, 1.5, 1.0),   # 标准
    (1.0, 0.8, 0.6),   # 小断面
    (3.5, 2.5, 2.0),   # 大断面
    (0.5, 0.6, 0.35),  # 窄小
    (10.0, 5.0, 3.0),  # 特大
    (1.0, 1.0, 1.0),   # h=H 极限
    (2.0, 1.5, 0.001), # h→0
]
for B, H, h in cases_Ah:
    out = calculate_rectangular_outputs(B, H, h, 0.014, 1/3000)
    expected = hand_A(B, min(h, H))
    ok(f"A: B={B}, H={H}, h={h}",
       abs_err(out['A'], expected) < 1e-10,
       f"代码={out['A']:.10f}, 手算={expected:.10f}")

# ------------------------------------------------------------------
# 验证 2: 湿周  P = B + 2h
# ------------------------------------------------------------------
print("\n■ 验证2: 湿周  P = B + 2h  (底+两侧, 不含顶/水面)")
for B, H, h in cases_Ah:
    out = calculate_rectangular_outputs(B, H, h, 0.014, 1/3000)
    h_eff = min(h, H)
    expected = hand_P(B, h_eff)
    ok(f"P: B={B}, h_eff={h_eff}",
       abs_err(out['P'], expected) < 1e-10,
       f"代码={out['P']:.10f}, 手算={expected:.10f}")

print("  说明: 矩形暗渠为非满流(有净空)，水面自由，湿润面仅底+两壁 → P=B+2h 正确")

# ------------------------------------------------------------------
# 验证 3: 水力半径  R = A/P = Bh/(B+2h)
# ------------------------------------------------------------------
print("\n■ 验证3: 水力半径  R = Bh / (B+2h)")
cases_R = [
    (2.0, 3.0, 1.0),
    (1.0, 1.5, 0.5),
    (4.0, 3.0, 2.0),
    (0.5, 0.8, 0.3),
    (2.0, 3.0, 2.0),  # h较大
    (10.0, 6.0, 5.0), # 水力最佳附近
]
for B, H, h in cases_R:
    out = calculate_rectangular_outputs(B, H, h, 0.014, 1/3000)
    expected = hand_R(B, min(h, H))
    ok(f"R: B={B}, h={min(h,H)}",
       abs_err(out['R_hyd'], expected) < 1e-10,
       f"代码={out['R_hyd']:.10f}, 手算={expected:.10f}")

# 特别验证: 水力最佳断面时 R = h/2
print("\n  ★ 特别验证: 当 B=2h 时, R 应恰好等于 h/2")
for h in [0.5, 1.0, 1.5, 2.0, 3.0]:
    B = 2.0 * h
    R_code = calculate_rectangular_outputs(B, B, h, 0.014, 1/3000)['R_hyd']
    R_theory = h / 2.0
    R_formula = B * h / (B + 2 * h)  # = 2h*h/(2h+2h) = 2h²/4h = h/2
    ok(f"R=h/2: h={h}, B=2h={B}",
       abs_err(R_code, R_theory) < 1e-10,
       f"代码R={R_code:.10f}, h/2={R_theory:.10f}, 公式={R_formula:.10f}")

# ------------------------------------------------------------------
# 验证 4: 总断面积  A_total = B × H
# ------------------------------------------------------------------
print("\n■ 验证4: 总断面积  A_total = B × H")
for B, H, h in cases_Ah:
    out = calculate_rectangular_outputs(B, H, h, 0.014, 1/3000)
    expected = B * H
    ok(f"A_total: B={B}, H={H}",
       abs_err(out['A_total'], expected) < 1e-10,
       f"代码={out['A_total']:.10f}, 手算={expected:.10f}")

# ------------------------------------------------------------------
# 验证 5: 净空面积百分比  (A_total - A) / A_total × 100
# ------------------------------------------------------------------
print("\n■ 验证5: 净空面积百分比  = (B·H - B·h) / (B·H) × 100 = (H-h)/H × 100")
for B, H, h in cases_Ah:
    out = calculate_rectangular_outputs(B, H, h, 0.014, 1/3000)
    h_eff = min(h, H)
    expected = hand_freeboard_pct(B, H, h_eff)
    ok(f"净空%: B={B}, H={H}, h={h_eff}",
       abs_err(out['freeboard_pct'], expected) < 1e-8,
       f"代码={out['freeboard_pct']:.6f}%, 手算={expected:.6f}%")

# 等价性验证: (B·H - B·h)/(B·H) = (H-h)/H  (B 可约分)
print("  等价性: (B·H-B·h)/(B·H) 化简后 = (H-h)/H, 与B无关")
for B in [0.5, 1.0, 2.0, 5.0]:
    H, h = 2.0, 1.2
    pct1 = (B*H - B*h) / (B*H) * 100
    pct2 = (H - h) / H * 100
    ok(f"等价性: B={B}",
       abs_err(pct1, pct2) < 1e-12,
       f"完整式={pct1:.10f}, 化简式={pct2:.10f}")

# ------------------------------------------------------------------
# 验证 6: 净空高度  = H - h
# ------------------------------------------------------------------
print("\n■ 验证6: 净空高度  = H - h")
for B, H, h in cases_Ah:
    out = calculate_rectangular_outputs(B, H, h, 0.014, 1/3000)
    h_eff = min(h, H)
    expected = hand_freeboard_hgt(H, h_eff)
    ok(f"净空高: H={H}, h={h_eff}",
       abs_err(out['freeboard_hgt'], expected) < 1e-10,
       f"代码={out['freeboard_hgt']:.10f}, 手算={expected:.10f}")

# ------------------------------------------------------------------
# 验证 7: 曼宁公式  Q = (1/n) · A · R^(2/3) · i^(1/2)
# ------------------------------------------------------------------
print("\n■ 验证7: 曼宁公式  Q = (1/n) · A · R^(2/3) · √i")
cases_Q = [
    # (B, H, h, n, i)
    (2.0, 1.5, 1.0, 0.014, 1/3000),
    (1.5, 1.2, 0.8, 0.013, 1/2000),
    (3.0, 2.5, 1.5, 0.016, 1/5000),
    (1.0, 0.8, 0.6, 0.012, 1/1000),
    (0.5, 0.6, 0.35, 0.011, 1/800),
    (4.0, 3.0, 2.0, 0.020, 1/8000),
    (2.5, 2.0, 1.2, 0.015, 1/4000),
    (0.8, 0.8, 0.5, 0.014, 1/1500),
]
for B, H, h, n, i in cases_Q:
    out = calculate_rectangular_outputs(B, H, h, n, i)
    Q_hand = hand_Q(B, h, n, i)
    ok(f"Q: B={B}, h={h}, n={n}, i=1/{1/i:.0f}",
       rel_err(out['Q'], Q_hand) < 1e-10,
       f"代码={out['Q']:.12f}, 手算={Q_hand:.12f}, 相对误差={rel_err(out['Q'], Q_hand):.2e}")

# ------------------------------------------------------------------
# 验证 8: 流速  V = Q / A = (1/n) · R^(2/3) · i^(1/2)
# ------------------------------------------------------------------
print("\n■ 验证8: 流速  V = Q/A = (1/n) · R^(2/3) · √i")
for B, H, h, n, i in cases_Q:
    out = calculate_rectangular_outputs(B, H, h, n, i)
    V_hand = hand_V(B, h, n, i)
    # 也验证 V = (1/n) R^(2/3) √i 的等价形式
    R = hand_R(B, h)
    V_manning_direct = (1.0/n) * (R ** (2.0/3.0)) * (i ** 0.5)
    ok(f"V=Q/A: B={B}, h={h}",
       rel_err(out['V'], V_hand) < 1e-10,
       f"代码={out['V']:.10f}, Q/A={V_hand:.10f}")
    ok(f"V=Manning: B={B}, h={h}",
       rel_err(out['V'], V_manning_direct) < 1e-10,
       f"代码={out['V']:.10f}, (1/n)R^(2/3)√i={V_manning_direct:.10f}")

# ------------------------------------------------------------------
# 验证 9: 水力最佳断面理论  β = B/h = 2
# ------------------------------------------------------------------
print("\n■ 验证9: 水力最佳断面理论推导验证")

# 理论: 对于矩形断面, 面积 A 一定时, 使湿周 P 最小(水力半径 R 最大) 的条件:
#   A = Bh,  P = B + 2h,  B = A/h
#   P(h) = A/h + 2h
#   dP/dh = -A/h² + 2 = 0  →  A = 2h²  →  B = 2h²/h = 2h  →  β = B/h = 2
#   此时 R = Bh/(B+2h) = 2h²/(4h) = h/2

print("  理论推导:")
print("    A = Bh, P = B+2h, 令 dP/dh=0: -A/h²+2=0 → A=2h² → B=2h → β=2")
print("    R_max = 2h·h/(2h+2h) = h/2")

# 数值验证: 给定 A, 遍历不同 B/h 比, 验证 β=2 时 R 最大
print("\n  数值验证: 固定 A, 变化 β, 验证 β=2 时 R 最大")
for A_fixed in [1.0, 2.0, 4.0, 8.0]:
    # h = sqrt(A/β),  B = β*h
    R_max = 0
    beta_best = 0
    for beta_int in range(50, 400):  # β from 0.5 to 4.0
        beta = beta_int / 100.0
        h = math.sqrt(A_fixed / beta)
        B = beta * h
        R = hand_R(B, h)
        if R > R_max:
            R_max = R
            beta_best = beta
    ok(f"A={A_fixed}: β_best≈2",
       abs_err(beta_best, 2.0) < 0.02,
       f"β_best={beta_best:.2f}")

# 理论最佳水深公式验证
# Q = (1/n) · 2h² · (h/2)^(2/3) · √i
# → h = [Q·n / (2^(1/3) · √i)]^(3/8)
print("\n  理论最佳水深公式: h = [Qn / (2^(1/3)·√i)]^(3/8)")
test_cases_opt = [
    (5.0, 0.014, 1/3000),
    (1.0, 0.013, 1/2000),
    (10.0, 0.016, 1/5000),
    (2.0, 0.014, 1/2500),
    (0.5, 0.012, 1/1000),
    (20.0, 0.020, 1/6000),
]
for Q, n, i in test_cases_opt:
    h_opt = (Q * n / (2.0**(1.0/3.0) * i**0.5)) ** (3.0/8.0)
    B_opt = 2.0 * h_opt
    Q_back = hand_Q(B_opt, h_opt, n, i)
    ok(f"最佳h反算Q: Q={Q}, n={n}",
       rel_err(Q_back, Q) < 1e-6,
       f"Q_back={Q_back:.8f}, Q={Q}, 误差={rel_err(Q_back, Q):.2e}")

# ------------------------------------------------------------------
# 验证 10: 二分法水深反算的几何一致性
# ------------------------------------------------------------------
print("\n■ 验证10: 二分法水深反算 → 几何量一致性")
cases_solve = [
    (2.0, 1.5, 0.014, 1/3000, 2.0),
    (1.5, 1.2, 0.013, 1/2000, 1.0),
    (3.0, 2.5, 0.016, 1/5000, 3.0),
    (1.0, 0.8, 0.012, 1/1000, 0.4),
    (4.0, 3.0, 0.020, 1/8000, 5.0),
]
for B, H, n, i, Q_target in cases_solve:
    h_solved, success = solve_water_depth_rectangular(B, H, n, i, Q_target)
    if not success:
        print(f"  ⚠ 跳过: B={B}, Q={Q_target} 求解失败")
        continue
    # 用求解出的 h 重新手算所有几何量
    A_h = hand_A(B, h_solved)
    P_h = hand_P(B, h_solved)
    R_h = hand_R(B, h_solved)
    Q_h = hand_Q(B, h_solved, n, i)
    V_h = hand_V(B, h_solved, n, i)
    fb_pct_h = hand_freeboard_pct(B, H, h_solved)
    fb_hgt_h = hand_freeboard_hgt(H, h_solved)

    # 与 calculate_rectangular_outputs 对比
    out = calculate_rectangular_outputs(B, H, h_solved, n, i)
    ok(f"反算A: Q={Q_target}", abs_err(out['A'], A_h) < 1e-10)
    ok(f"反算P: Q={Q_target}", abs_err(out['P'], P_h) < 1e-10)
    ok(f"反算R: Q={Q_target}", abs_err(out['R_hyd'], R_h) < 1e-10)
    ok(f"反算Q: Q={Q_target}", rel_err(out['Q'], Q_target) < 0.0002,
       f"Q_calc={out['Q']:.6f}, Q_target={Q_target}")
    ok(f"反算fb%: Q={Q_target}", abs_err(out['freeboard_pct'], fb_pct_h) < 1e-8)
    ok(f"反算fb高: Q={Q_target}", abs_err(out['freeboard_hgt'], fb_hgt_h) < 1e-10)

# ------------------------------------------------------------------
# 验证 11: h > H 截断逻辑
# ------------------------------------------------------------------
print("\n■ 验证11: h > H 截断 → h 取 H")
for B, H, h_input in [(2.0, 1.5, 3.0), (1.0, 0.8, 5.0), (0.5, 0.5, 0.6)]:
    out = calculate_rectangular_outputs(B, H, h_input, 0.014, 1/3000)
    h_eff = min(h_input, H)
    ok(f"截断A: h_in={h_input}>H={H}", abs_err(out['A'], B * h_eff) < 1e-10,
       f"A={out['A']}, 应={B*h_eff}")
    ok(f"截断fb=0: h_in={h_input}>H={H}", abs_err(out['freeboard_hgt'], 0.0) < 1e-10)
    ok(f"截断fb%=0: h_in={h_input}>H={H}", abs_err(out['freeboard_pct'], 0.0) < 1e-8)

# ------------------------------------------------------------------
# 验证 12: 主函数几何输出一致性
# ------------------------------------------------------------------
print("\n■ 验证12: quick_calculate 主函数几何输出一致性")
main_cases = [
    (5.0, 0.014, 3000, 0.5, 3.0, None, None, "经济最优(默认)"),
    (5.0, 0.014, 3000, 0.1, 10.0, 2.0, None, "指定B=2.0"),
    (5.0, 0.014, 3000, 0.1, 10.0, None, 1.5, "指定β=1.5"),
    (1.0, 0.013, 2000, 0.3, 2.5, None, None, "小Q经济最优"),
    (10.0, 0.016, 5000, 0.5, 2.5, None, None, "中Q经济最优"),
]
for Q, n, si, vl, vh, mB, mBH, desc in main_cases:
    i = 1.0 / si
    r = quick_calculate_rectangular_culvert(Q, n, si, vl, vh,
                                            manual_B=mB, target_BH_ratio=mBH)
    if not r['success']:
        print(f"  ⚠ [{desc}] 跳过: {r['error_message'][:40]}")
        continue

    B, H, h = r['B'], r['H'], r['h_design']

    # 逐项验证
    ok(f"[{desc}] A=B*h",
       abs_err(r['A_design'], B * h) < 1e-6,
       f"A={r['A_design']:.6f}, B*h={B*h:.6f}")

    ok(f"[{desc}] P=B+2h",
       abs_err(r['P_design'], B + 2*h) < 1e-6,
       f"P={r['P_design']:.6f}, B+2h={B+2*h:.6f}")

    ok(f"[{desc}] R=A/P",
       abs_err(r['R_hyd_design'], (B*h)/(B+2*h)) < 1e-6,
       f"R={r['R_hyd_design']:.6f}, Bh/(B+2h)={(B*h)/(B+2*h):.6f}")

    ok(f"[{desc}] A_total=B*H",
       abs_err(r['A_total'], B * H) < 1e-6)

    ok(f"[{desc}] HB_ratio=H/B",
       abs_err(r['HB_ratio'], H / B) < 1e-6)

    ok(f"[{desc}] BH_ratio=B/h",
       abs_err(r['BH_ratio'], B / h) < 1e-6 if h > 0 else True)

    ok(f"[{desc}] fb_hgt_design=H-h",
       abs_err(r['freeboard_hgt_design'], H - h) < 1e-6)

    ok(f"[{desc}] fb_pct_design=(H-h)/H*100",
       abs_err(r['freeboard_pct_design'], (H-h)/H*100) < 1e-4)

    # 曼宁公式正向验证
    Q_check = hand_Q(B, h, n, i)
    ok(f"[{desc}] Q_calc≈Q",
       rel_err(r['Q_calc'], Q) < 0.005,
       f"Q_calc={r['Q_calc']:.6f}, Q={Q}")
    ok(f"[{desc}] Q_calc=Manning(B,h)",
       rel_err(r['Q_calc'], Q_check) < 1e-6)

    # V = Q/A
    ok(f"[{desc}] V=Q/A",
       rel_err(r['V_design'], r['Q_calc'] / r['A_design']) < 1e-6 if r['A_design'] > 0 else True)

    # 加大工况几何一致性
    h_inc = r['h_increased']
    if h_inc > 0:
        out_inc = calculate_rectangular_outputs(B, H, h_inc, n, i)
        ok(f"[{desc}] h_inc>h_design", h_inc > h)
        ok(f"[{desc}] h_inc<H", h_inc < H)
        ok(f"[{desc}] inc fb_hgt=H-h_inc",
           abs_err(r['freeboard_hgt_inc'], H - h_inc) < 1e-6)
        ok(f"[{desc}] inc fb_pct=(H-h_inc)/H*100",
           abs_err(r['freeboard_pct_inc'], (H-h_inc)/H*100) < 1e-4)

# ------------------------------------------------------------------
# 验证 13: 教科书算例手算对照
# ------------------------------------------------------------------
print("\n■ 验证13: 教科书级手算对照")

# 算例: B=2.0m, h=1.0m, n=0.014, i=1/3000
B, H, h, n, i = 2.0, 1.5, 1.0, 0.014, 1.0/3000.0
A = 2.0 * 1.0             # = 2.0 m²
P = 2.0 + 2*1.0           # = 4.0 m
R = 2.0 / 4.0             # = 0.5 m
Q = (1/0.014) * 2.0 * (0.5**(2.0/3.0)) * ((1/3000)**0.5)
V = Q / A

out = calculate_rectangular_outputs(B, H, h, n, i)
print(f"  手算: A={A}, P={P}, R={R}, Q={Q:.8f}, V={V:.8f}")
print(f"  代码: A={out['A']}, P={out['P']}, R={out['R_hyd']}, Q={out['Q']:.8f}, V={out['V']:.8f}")

ok("教科书A", out['A'] == 2.0)
ok("教科书P", out['P'] == 4.0)
ok("教科书R", out['R_hyd'] == 0.5)
ok("教科书Q", rel_err(out['Q'], Q) < 1e-12, f"误差={rel_err(out['Q'], Q):.2e}")
ok("教科书V", rel_err(out['V'], V) < 1e-12)
ok("教科书fb高", out['freeboard_hgt'] == 0.5)
ok("教科书fb%", abs_err(out['freeboard_pct'], (1.5-1.0)/1.5*100) < 1e-10)

# 算例2: B=1.0, h=0.5, n=0.013, i=1/2000
B2, H2, h2, n2, i2 = 1.0, 1.0, 0.5, 0.013, 1.0/2000.0
A2 = 1.0 * 0.5            # = 0.5
P2 = 1.0 + 2*0.5          # = 2.0
R2 = 0.5 / 2.0            # = 0.25
Q2 = (1/0.013) * 0.5 * (0.25**(2.0/3.0)) * ((1/2000.0)**0.5)
V2 = Q2 / A2
out2 = calculate_rectangular_outputs(B2, H2, h2, n2, i2)

print(f"\n  手算: A={A2}, P={P2}, R={R2}, Q={Q2:.8f}, V={V2:.8f}")
print(f"  代码: A={out2['A']}, P={out2['P']}, R={out2['R_hyd']}, Q={out2['Q']:.8f}, V={out2['V']:.8f}")

ok("教科书2 A", out2['A'] == 0.5)
ok("教科书2 P", out2['P'] == 2.0)
ok("教科书2 R", out2['R_hyd'] == 0.25)
ok("教科书2 Q", rel_err(out2['Q'], Q2) < 1e-12)
ok("教科书2 V", rel_err(out2['V'], V2) < 1e-12)

# ------------------------------------------------------------------
# 验证 14: 零值/负值保护
# ------------------------------------------------------------------
print("\n■ 验证14: 零值/负值输入保护")
for desc, args in [
    ("B=0", (0, 1.5, 1.0, 0.014, 1/3000)),
    ("H=0", (2.0, 0, 1.0, 0.014, 1/3000)),
    ("h=0", (2.0, 1.5, 0, 0.014, 1/3000)),
    ("B<0", (-1, 1.5, 1.0, 0.014, 1/3000)),
]:
    out = calculate_rectangular_outputs(*args)
    ok(f"{desc} → Q=0", out['Q'] == 0)
    ok(f"{desc} → V=0", out['V'] == 0)

# slope=0 → Q=0 (i^0.5 = 0)
out_s0 = calculate_rectangular_outputs(2.0, 1.5, 1.0, 0.014, 0)
ok("slope=0 → Q=0", out_s0['Q'] == 0)

# n=0 → Q=0 (保护)
out_n0 = calculate_rectangular_outputs(2.0, 1.5, 1.0, 0, 1/3000)
ok("n=0 → Q=0", out_n0['Q'] == 0)


# ====================================================================
# 结果汇总
# ====================================================================
total = PASS + FAIL
print("\n" + "=" * 72)
print(f"  验证结果:  通过 {PASS}  |  失败 {FAIL}  |  共 {total}")
if total > 0:
    print(f"  通过率: {PASS/total*100:.1f}%")
if ERRORS:
    print(f"\n  失败详情 ({len(ERRORS)} 项):")
    for e in ERRORS:
        print(f"    {e}")
print("=" * 72)
if FAIL == 0:
    print("  ✓ 所有几何公式验证通过，与手算/理论完全一致。")
else:
    print(f"  ✗ 有 {FAIL} 项验证失败，请检查。")
print("=" * 72)
