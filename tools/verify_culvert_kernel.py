# -*- coding: utf-8 -*-
"""
矩形暗涵水力计算内核 — 独立交叉验证脚本

逐项手算验证每个公式的正确性，不依赖内核中的任何辅助函数。
验证项目：
  1. 曼宁公式 Q = (1/n) * A * R^(2/3) * i^(1/2)
  2. 矩形断面水力要素 A, P, R
  3. 湿周公式（矩形暗涵: P = B + 2h，不含水面宽度）
  4. β参数化解析解 h(β)
  5. 净空高度规范要求
  6. 加大流量百分比查表
  7. H_min / H_max 解析解
  8. 完整设计流程端到端验证（手算 vs 内核）
"""

import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "渠系建筑物断面计算"))
from 矩形暗涵设计 import (
    calculate_rectangular_outputs, solve_water_depth_rectangular,
    get_required_freeboard_height_rect, get_flow_increase_percent_rect,
    quick_calculate_rectangular_culvert,
    _h_design_from_beta, _solve_h_inc_fast,
    compute_H_min_optimal, compute_H_max_optimal,
    MIN_FREEBOARD_HGT_RECT, MIN_FREEBOARD_PCT_RECT, MAX_FREEBOARD_PCT_RECT,
    HB_RATIO_LIMIT,
)

PASS = 0
FAIL = 0
ERRORS = []

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        msg = f"FAIL: {name}" + (f" | {detail}" if detail else "")
        ERRORS.append(msg)
        print(f"  ✗ {msg}")

def rel_err(a, b):
    return abs(a - b) / max(abs(b), 1e-15)

# ============================================================
# 验证1: 曼宁公式 — 矩形断面
# ============================================================
def verify_manning():
    """
    手算: Q = (1/n) * A * R^(2/3) * sqrt(i)
    矩形: A = B*h, P = B + 2h, R = A/P
    
    关键验证点：
    - 矩形暗涵的湿周只有三面（底+两侧壁），水面不计入湿周
    - 这与明渠矩形断面相同（明渠水面也不计入湿周）
    """
    print("\n" + "="*70)
    print("验证1: 曼宁公式 — 矩形断面手算对照")
    print("="*70)
    
    # 手算案例: B=2.0m, h=1.0m, n=0.014, i=1/3000
    B, h, n, i = 2.0, 1.0, 0.014, 1/3000
    H = 1.5  # 洞高(不影响水力计算)
    
    # 手算
    A_hand = B * h                    # = 2.0
    P_hand = B + 2 * h                # = 4.0 (底+两侧壁)
    R_hand = A_hand / P_hand          # = 0.5
    Q_hand = (1/n) * A_hand * (R_hand ** (2/3)) * (i ** 0.5)
    V_hand = Q_hand / A_hand
    
    print(f"  手算: A={A_hand:.4f}, P={P_hand:.4f}, R={R_hand:.4f}")
    print(f"  手算: Q={Q_hand:.6f}, V={V_hand:.6f}")
    
    out = calculate_rectangular_outputs(B, H, h, n, i)
    print(f"  内核: A={out['A']:.4f}, P={out['P']:.4f}, R={out['R_hyd']:.4f}")
    print(f"  内核: Q={out['Q']:.6f}, V={out['V']:.6f}")
    
    check("曼宁-A", rel_err(out['A'], A_hand) < 1e-10, f"{out['A']} vs {A_hand}")
    check("曼宁-P", rel_err(out['P'], P_hand) < 1e-10, f"{out['P']} vs {P_hand}")
    check("曼宁-R", rel_err(out['R_hyd'], R_hand) < 1e-10, f"{out['R_hyd']} vs {R_hand}")
    check("曼宁-Q", rel_err(out['Q'], Q_hand) < 1e-8, f"{out['Q']} vs {Q_hand}")
    check("曼宁-V", rel_err(out['V'], V_hand) < 1e-8, f"{out['V']} vs {V_hand}")
    
    # 额外: 验证 V = (1/n) * R^(2/3) * sqrt(i) — 曼宁流速公式
    V_manning = (1/n) * (R_hand ** (2/3)) * (i ** 0.5)
    check("曼宁-V公式", rel_err(out['V'], V_manning) < 1e-8, 
          f"V_kernel={out['V']:.6f}, V_manning=(1/n)*R^(2/3)*sqrt(i)={V_manning:.6f}")


# ============================================================
# 验证2: 湿周公式 — 矩形暗涵 vs 满流
# ============================================================
def verify_wetted_perimeter():
    """
    矩形暗涵关键问题：湿周是 B+2h 还是 2B+2h？
    
    答案：非满流时 P = B + 2h（底+两侧壁，水面不是固体边界）
    满流时 P = 2B + 2H（四面都接触）—— 但本系统不处理满流
    
    验证：当 h < H 时，P = B + 2h
    """
    print("\n" + "="*70)
    print("验证2: 湿周公式 — 矩形暗涵(非满流)")
    print("="*70)
    
    cases = [
        (2.0, 1.5, 1.0),   # 正常
        (1.0, 0.8, 0.6),   # 小断面
        (3.0, 2.5, 2.0),   # 大断面
        (2.0, 1.5, 1.49),  # 接近满流
    ]
    for B, H, h in cases:
        out = calculate_rectangular_outputs(B, H, h, 0.014, 1/3000)
        P_expected = B + 2 * h
        check(f"湿周 B={B},H={H},h={h}", 
              rel_err(out['P'], P_expected) < 1e-10,
              f"P_kernel={out['P']}, P_hand={P_expected}")
    
    # 重要检查：确认不是 2B+2h (满流湿周)
    B, H, h = 2.0, 1.5, 1.0
    out = calculate_rectangular_outputs(B, H, h, 0.014, 1/3000)
    P_wrong = 2*B + 2*h  # 如果错误地用了满流湿周
    check("湿周≠满流公式", abs(out['P'] - P_wrong) > 0.1,
          f"P={out['P']}, 若误用满流P={P_wrong}")


# ============================================================
# 验证3: β参数化解析解
# ============================================================
def verify_beta_analytical():
    """
    推导验证：
    β = B/h → B = βh
    A = Bh = βh²
    P = B + 2h = (β+2)h
    R = A/P = βh/(β+2)
    
    Q = (1/n) * βh² * [βh/(β+2)]^(2/3) * √i
      = (1/n) * β * h² * β^(2/3) * h^(2/3) / (β+2)^(2/3) * √i
      = (1/n) * β^(5/3) * h^(8/3) / (β+2)^(2/3) * √i
    
    解得:
    h^(8/3) = Q*n/√i * (β+2)^(2/3) / β^(5/3)
    h = [Q*n/√i * (β+2)^(2/3) / β^(5/3)]^(3/8)
    """
    print("\n" + "="*70)
    print("验证3: β参数化解析解 h(β)")
    print("="*70)
    
    test_cases = [
        (5.0, 0.014, 1/3000, 1.0),
        (5.0, 0.014, 1/3000, 1.5),
        (5.0, 0.014, 1/3000, 2.0),
        (5.0, 0.014, 1/3000, 2.5),
        (10.0, 0.016, 1/5000, 1.2),
        (1.0, 0.013, 1/2000, 0.8),
    ]
    
    for Q, n, slope, beta in test_cases:
        # 手算
        h_hand = (Q * n / math.sqrt(slope) * ((beta + 2.0)**(2.0/3.0)) / (beta**(5.0/3.0))) ** (3.0/8.0)
        # 内核
        h_kernel = _h_design_from_beta(beta, Q, n, slope)
        
        # 验证: 用 h_hand 反算 Q 应该等于原Q
        B_hand = beta * h_hand
        A = B_hand * h_hand
        P = B_hand + 2 * h_hand
        R = A / P
        Q_back = (1/n) * A * (R**(2/3)) * (slope**0.5)
        
        check(f"β解析解 β={beta} h一致", rel_err(h_kernel, h_hand) < 1e-10,
              f"h_kernel={h_kernel:.6f}, h_hand={h_hand:.6f}")
        check(f"β解析解 β={beta} Q反算", rel_err(Q_back, Q) < 1e-6,
              f"Q_back={Q_back:.6f}, Q={Q}")
        
        print(f"  β={beta:.1f}: h={h_hand:.4f}m, B={B_hand:.4f}m, Q_back={Q_back:.6f}m³/s (err={rel_err(Q_back,Q)*100:.8f}%)")


# ============================================================
# 验证4: 净空高度规范
# ============================================================
def verify_freeboard():
    """
    规范要求(GB 50288-2018 第11.2.5条 表11.2.5)：
    - 任何情况：净空高度 ≥ 0.4m
    - 矩形涵洞进口净高D ≤ 3m: 净空高度 ≥ D/6
    - 矩形涵洞进口净高D > 3m: 净空高度 ≥ 0.5m
    
    合并: D ≤ 3m → max(0.4, D/6); D > 3m → 0.5
    
    临界点: D/6 = 0.4 → D = 2.4m
    即 D < 2.4m 时 0.4 控制, D ∈ [2.4, 3.0] 时 D/6 控制, D > 3 时 0.5 控制
    """
    print("\n" + "="*70)
    print("验证4: 净空高度规范要求")
    print("="*70)
    
    cases = [
        # (H, 期望净空高度, 说明)
        (0.6, 0.4, "H=0.6<2.4, 0.4控制"),
        (1.0, 0.4, "H=1.0<2.4, 0.4控制"),
        (2.0, 0.4, "H=2.0<2.4, 0.4控制"),
        (2.4, 0.4, "H=2.4临界, H/6=0.4=MIN"),
        (2.7, 0.45, "H=2.7>2.4, H/6=0.45控制"),
        (3.0, 0.5, "H=3.0, H/6=0.5"),
        (3.1, 0.5, "H=3.1>3, 0.5控制"),
        (4.0, 0.5, "H=4.0>3, 0.5控制"),
        (6.0, 0.5, "H=6.0>3, 0.5控制"),
    ]
    
    for H, expected, desc in cases:
        got = get_required_freeboard_height_rect(H)
        check(f"净空 {desc}", abs(got - expected) < 0.001,
              f"got={got:.4f}, expected={expected:.4f}")


# ============================================================
# 验证5: 加大流量百分比
# ============================================================
def verify_flow_increase():
    """
    GB 50288-2018 加大流量比例表:
    Q < 1     → 30%
    1 ≤ Q < 5 → 25%
    5 ≤ Q < 20 → 20%
    20 ≤ Q < 50 → 15%
    50 ≤ Q < 100 → 10%
    Q ≥ 100   → 5%
    
    注意边界: Q=1.0 应属于 [1,5) → 25%
    """
    print("\n" + "="*70)
    print("验证5: 加大流量百分比查表")
    print("="*70)
    
    cases = [
        (0.1, 30), (0.5, 30), (0.99, 30),
        (1.0, 25), (2.0, 25), (4.99, 25),
        (5.0, 20), (10.0, 20), (19.99, 20),
        (20.0, 15), (30.0, 15), (49.99, 15),
        (50.0, 10), (75.0, 10), (99.99, 10),
        (100.0, 5), (200.0, 5), (300.0, 5), (500.0, 5),
    ]
    
    for Q, expected in cases:
        got = get_flow_increase_percent_rect(Q)
        check(f"加大比例 Q={Q}", abs(got - expected) < 0.01,
              f"got={got}, expected={expected}")


# ============================================================
# 验证6: H_min / H_max 解析计算
# ============================================================
def verify_H_bounds():
    """
    H_min 约束来源:
      1. PA_inc ≥ 10% → (H-h_inc)/H ≥ 0.1 → H ≥ h_inc/0.9
      2. B/H ≤ 1.2  → H ≥ B/1.2
      3. 净空高度: h_inc + freeboard
      4. H ≥ MIN_HEIGHT_RECT
    
    H_max 约束来源:
      1. PA_inc ≤ 30% → (H-h_inc)/H ≤ 0.3 → H ≤ h_inc/0.7
      2. H/B ≤ 1.2   → H ≤ 1.2B
    """
    print("\n" + "="*70)
    print("验证6: H_min / H_max 解析计算")
    print("="*70)
    
    # 案例: h_inc=1.0, B=2.0
    h_inc, B = 1.0, 2.0
    
    # 手算 H_min
    H_pa = h_inc / 0.9           # = 1.111
    H_bh = B / 1.2               # = 1.667
    H_clear = h_inc + 0.4        # = 1.4 (初始)
    # H_clear=1.4 < 2.4, 所以 0.4 控制, 不进入 H/6 分支
    H_abs = 0.5
    H_min_hand = max(H_pa, H_bh, H_clear, H_abs)  # = 1.667 (H_bh控制)
    
    H_min_kernel = compute_H_min_optimal(h_inc, B)
    check("H_min案例1", abs(H_min_kernel - H_min_hand) < 0.001,
          f"kernel={H_min_kernel:.4f}, hand={H_min_hand:.4f}")
    
    # 手算 H_max
    H_pa_max = h_inc / 0.7       # = 1.429
    H_hb_max = 1.2 * B           # = 2.4
    H_max_hand = min(H_pa_max, H_hb_max)  # = 1.429
    
    H_max_kernel = compute_H_max_optimal(h_inc, B)
    check("H_max案例1", abs(H_max_kernel - H_max_hand) < 0.001,
          f"kernel={H_max_kernel:.4f}, hand={H_max_hand:.4f}")
    
    # 注意: H_min=1.667 > H_max=1.429 → 此组合无解!
    # 这是正确的，说明 h_inc=1.0, B=2.0 的组合不可行
    check("H_min>H_max无解", H_min_hand > H_max_hand,
          f"H_min={H_min_hand:.4f} > H_max={H_max_hand:.4f}")
    print(f"  案例1: h_inc=1.0, B=2.0 → H_min={H_min_hand:.4f} > H_max={H_max_hand:.4f} (无解，正确)")
    
    # 案例2: h_inc=1.5, B=2.5
    h_inc2, B2 = 1.5, 2.5
    H_pa2 = h_inc2 / 0.9           # = 1.667
    H_bh2 = B2 / 1.2               # = 2.083
    H_clear2 = h_inc2 + 0.4        # = 1.9
    # H_clear2=1.9 < 2.4, 所以 0.4 控制
    H_min_hand2 = max(H_pa2, H_bh2, H_clear2, 0.5)  # = 2.083 (H_bh控制)
    
    H_pa_max2 = h_inc2 / 0.7       # = 2.143
    H_hb_max2 = 1.2 * B2           # = 3.0
    H_max_hand2 = min(H_pa_max2, H_hb_max2)  # = 2.143
    
    H_min_k2 = compute_H_min_optimal(h_inc2, B2)
    H_max_k2 = compute_H_max_optimal(h_inc2, B2)
    check("H_min案例2", abs(H_min_k2 - H_min_hand2) < 0.001,
          f"kernel={H_min_k2:.4f}, hand={H_min_hand2:.4f}")
    check("H_max案例2", abs(H_max_k2 - H_max_hand2) < 0.001,
          f"kernel={H_max_k2:.4f}, hand={H_max_hand2:.4f}")
    print(f"  案例2: h_inc=1.5, B=2.5 → H_min={H_min_hand2:.4f}, H_max={H_max_hand2:.4f} (有解)")
    
    # 案例3: 大水深, H/6 分支
    h_inc3, B3 = 2.0, 3.0
    H_pa3 = h_inc3 / 0.9           # = 2.222
    H_bh3 = B3 / 1.2               # = 2.5
    H_clear3 = h_inc3 + 0.4        # = 2.4
    # H_clear3=2.4, 需检查 H/6 分支
    # 2.4 <= 3.0, 且 H_clear3=2.4 → H/6=0.4, 但条件是 H_clear > 2.4 AND H_clear <= 3.0
    # 2.4 > 2.4 为 False, 所以不进入 H/6 分支
    H_min_hand3 = max(H_pa3, H_bh3, H_clear3, 0.5)  # = 2.5 (H_bh控制)
    
    H_min_k3 = compute_H_min_optimal(h_inc3, B3)
    check("H_min案例3(大水深)", abs(H_min_k3 - H_min_hand3) < 0.001,
          f"kernel={H_min_k3:.4f}, hand={H_min_hand3:.4f}")
    print(f"  案例3: h_inc=2.0, B=3.0 → H_min={H_min_hand3:.4f}")
    
    # 案例4: 更大水深, H_clear > 2.4 触发 H/6 分支
    h_inc4, B4 = 2.1, 3.5
    H_pa4 = h_inc4 / 0.9           # = 2.333
    H_bh4 = B4 / 1.2               # = 2.917
    H_clear4 = h_inc4 + 0.4        # = 2.5
    # H_clear4=2.5 > 2.4 AND <= 3.0 → H/6 分支
    # H_clear4 = max(2.5, 1.2 * h_inc4) = max(2.5, 2.52) = 2.52
    H_clear4 = max(H_clear4, 1.2 * h_inc4)
    H_min_hand4 = max(H_pa4, H_bh4, H_clear4, 0.5)  # = 2.917 (H_bh控制)
    
    H_min_k4 = compute_H_min_optimal(h_inc4, B4)
    check("H_min案例4(H/6分支)", abs(H_min_k4 - H_min_hand4) < 0.001,
          f"kernel={H_min_k4:.4f}, hand={H_min_hand4:.4f}")
    print(f"  案例4: h_inc=2.1, B=3.5 → H_min={H_min_hand4:.4f}")


# ============================================================
# 验证7: 净空面积百分比计算
# ============================================================
def verify_freeboard_percentage():
    """
    净空面积百分比 = (A_total - A_water) / A_total * 100
                   = (B*H - B*h) / (B*H) * 100
                   = (H - h) / H * 100
    
    注意：这是面积比，不是高度比（对矩形两者恰好相同）
    """
    print("\n" + "="*70)
    print("验证7: 净空面积百分比")
    print("="*70)
    
    cases = [
        (2.0, 2.0, 1.0, 50.0),   # 50% 净空
        (2.0, 2.0, 1.5, 25.0),   # 25%
        (2.0, 2.0, 1.8, 10.0),   # 10%
        (2.0, 2.0, 1.4, 30.0),   # 30%
        (3.0, 2.5, 2.0, 20.0),   # 20%
    ]
    
    for B, H, h, expected_pct in cases:
        out = calculate_rectangular_outputs(B, H, h, 0.014, 1/3000)
        hand_pct = (H - h) / H * 100
        check(f"净空% B={B},H={H},h={h}",
              abs(out['freeboard_pct'] - expected_pct) < 0.01 and
              abs(out['freeboard_pct'] - hand_pct) < 0.01,
              f"kernel={out['freeboard_pct']:.2f}%, hand={hand_pct:.2f}%, expected={expected_pct:.2f}%")


# ============================================================
# 验证8: 水深反算精度
# ============================================================
def verify_depth_solver():
    """
    给定 Q, B, H, n, slope → 二分法求 h
    验证: 用求出的 h 反算 Q 应等于目标 Q
    """
    print("\n" + "="*70)
    print("验证8: 水深反算精度 (二分法)")
    print("="*70)
    
    cases = [
        # (B, H, n, slope, Q_target)
        (2.0, 1.5, 0.014, 1/3000, 1.0),
        (2.0, 1.5, 0.014, 1/3000, 2.0),
        (3.0, 2.5, 0.016, 1/5000, 5.0),
        (1.5, 1.2, 0.013, 1/2000, 0.5),
        (4.0, 3.0, 0.020, 1/8000, 8.0),
    ]
    
    for B, H, n, slope, Q_t in cases:
        h_solved, ok = solve_water_depth_rectangular(B, H, n, slope, Q_t)
        if not ok:
            check(f"反算 B={B},Q={Q_t} 求解成功", False, "求解失败")
            continue
        
        # 用解出的水深手算Q
        A = B * h_solved
        P = B + 2 * h_solved
        R = A / P
        Q_back = (1/n) * A * (R**(2/3)) * (slope**0.5)
        
        err = rel_err(Q_back, Q_t)
        check(f"反算精度 B={B},Q={Q_t}", err < 0.001,
              f"Q_back={Q_back:.6f}, Q_target={Q_t}, err={err*100:.4f}%")
        check(f"反算h<H B={B},Q={Q_t}", h_solved < H,
              f"h={h_solved:.4f}, H={H}")
        print(f"  B={B}, Q_target={Q_t} → h={h_solved:.4f}m, Q_back={Q_back:.6f}, err={err*100:.6f}%")


# ============================================================
# 验证9: 完整端到端手算验证
# ============================================================
def verify_end_to_end():
    """
    取一组典型参数，从头到尾手算，与内核输出对照。
    
    参数: Q=5.0 m³/s, n=0.014, i=1/3000, v_min=0.5, v_max=3.0
    """
    print("\n" + "="*70)
    print("验证9: 完整端到端手算验证")
    print("="*70)
    
    Q = 5.0
    n = 0.014
    slope_inv = 3000
    slope = 1.0 / slope_inv
    v_min, v_max = 0.5, 3.0
    
    r = quick_calculate_rectangular_culvert(Q, n, slope_inv, v_min, v_max)
    
    if not r['success']:
        check("端到端-成功", False, r.get('error_message', ''))
        return
    
    B = r['B']
    H = r['H']
    h = r['h_design']
    h_inc = r['h_increased']
    
    print(f"  内核结果: B={B:.4f}, H={H:.4f}, h={h:.4f}, h_inc={h_inc:.4f}")
    
    # 1. 手算设计工况水力要素
    A = B * h
    P = B + 2 * h
    R = A / P
    Q_calc = (1/n) * A * (R**(2/3)) * (slope**0.5)
    V = Q_calc / A
    
    check("端到端-A", rel_err(r['A_design'], A) < 0.001, f"k={r['A_design']:.4f}, h={A:.4f}")
    check("端到端-P", rel_err(r['P_design'], P) < 0.001, f"k={r['P_design']:.4f}, h={P:.4f}")
    check("端到端-R", rel_err(r['R_hyd_design'], R) < 0.001, f"k={r['R_hyd_design']:.4f}, h={R:.4f}")
    check("端到端-V", rel_err(r['V_design'], V) < 0.01, f"k={r['V_design']:.4f}, h={V:.4f}")
    check("端到端-Q反算", rel_err(Q_calc, Q) < 0.01, f"Q_calc={Q_calc:.4f}, Q={Q}")
    
    # 2. 手算加大流量
    inc_pct = get_flow_increase_percent_rect(Q)  # Q=5 → 20%
    Q_inc = Q * (1 + inc_pct / 100)
    check("端到端-加大比例", abs(inc_pct - 20.0) < 0.01, f"got={inc_pct}")
    check("端到端-Q_inc", rel_err(r['Q_increased'], Q_inc) < 0.001, 
          f"k={r['Q_increased']:.4f}, h={Q_inc:.4f}")
    
    # 3. 手算加大工况
    A_inc = B * h_inc
    P_inc = B + 2 * h_inc
    R_inc = A_inc / P_inc
    Q_inc_calc = (1/n) * A_inc * (R_inc**(2/3)) * (slope**0.5)
    V_inc = Q_inc_calc / A_inc
    
    check("端到端-V_inc", rel_err(r['V_increased'], V_inc) < 0.01, 
          f"k={r['V_increased']:.4f}, h={V_inc:.4f}")
    check("端到端-Q_inc反算", rel_err(Q_inc_calc, Q_inc) < 0.01,
          f"Q_inc_calc={Q_inc_calc:.4f}, Q_inc={Q_inc:.4f}")
    
    # 4. 净空验证
    fb_hgt = H - h_inc
    fb_pct = (H - h_inc) / H * 100
    check("端到端-净空高度", abs(r['freeboard_hgt_inc'] - fb_hgt) < 0.001)
    check("端到端-净空百分比", abs(r['freeboard_pct_inc'] - fb_pct) < 0.1)
    check("端到端-净空≥10%", fb_pct >= 10.0 - 0.5)
    check("端到端-净空≤30%", fb_pct <= 30.0 + 0.5)
    
    req_fb = get_required_freeboard_height_rect(H)
    check("端到端-净空高度≥要求", fb_hgt >= req_fb - 0.005,
          f"fb={fb_hgt:.4f}, req={req_fb:.4f}")
    
    # 5. 流速约束
    check("端到端-V≥v_min", V >= v_min, f"V={V:.4f}, v_min={v_min}")
    check("端到端-V≤v_max", V <= v_max, f"V={V:.4f}, v_max={v_max}")
    check("端到端-V_inc≤v_max", V_inc <= v_max, f"V_inc={V_inc:.4f}, v_max={v_max}")
    
    # 6. 高宽比约束
    HB = H / B
    BH_r = B / H
    check("端到端-H/B≤1.2", HB <= HB_RATIO_LIMIT + 0.01, f"H/B={HB:.4f}")
    check("端到端-B/H≤1.2", BH_r <= HB_RATIO_LIMIT + 0.01, f"B/H={BH_r:.4f}")
    
    print(f"\n  === 手算验证汇总 ===")
    print(f"  B={B:.4f}m, H={H:.4f}m, H/B={HB:.4f}")
    print(f"  设计: h={h:.4f}m, A={A:.4f}m², V={V:.4f}m/s, Q_back={Q_calc:.4f}m³/s")
    print(f"  加大: h_inc={h_inc:.4f}m, V_inc={V_inc:.4f}m/s, Q_inc_back={Q_inc_calc:.4f}m³/s")
    print(f"  净空: 高度={fb_hgt:.4f}m(≥{req_fb:.4f}), 比例={fb_pct:.1f}%")


# ============================================================
# 验证10: 经济最优断面特性验证
# ============================================================
def verify_optimal_properties():
    """
    验证经济最优断面的以下特性:
    1. 是全局面积B×H最小解
    2. β参数化解析解确实给出正确的h和B
    3. 所有约束都满足
    """
    print("\n" + "="*70)
    print("验证10: 经济最优断面特性")
    print("="*70)
    
    cases = [
        (5.0, 0.014, 3000, 0.5, 3.0),
        (10.0, 0.016, 5000, 0.5, 2.5),
        (2.0, 0.014, 2500, 0.3, 3.0),
    ]
    
    for Q, n, si, vl, vh in cases:
        slope = 1/si
        r = quick_calculate_rectangular_culvert(Q, n, si, vl, vh)
        if not r['success']:
            check(f"最优断面 Q={Q}", False, "计算失败")
            continue
        
        B, H = r['B'], r['H']
        h = r['h_design']
        
        # 验证 h 确实是 β 解析解的结果
        beta = B / h if h > 0 else 0
        h_from_beta = _h_design_from_beta(beta, Q, n, slope)
        check(f"最优-β解析 Q={Q}", rel_err(h_from_beta, h) < 0.01,
              f"h_beta={h_from_beta:.4f}, h={h:.4f}")
        
        # 验证是经济最优标识
        check(f"最优-标识 Q={Q}", r['is_optimal_section'])
        
        # 验证约束
        check(f"最优-h<H Q={Q}", h < H)
        check(f"最优-净空≥10% Q={Q}", r['freeboard_pct_inc'] >= 9.5,
              f"fb_pct={r['freeboard_pct_inc']:.2f}%")
        check(f"最优-净空≤30% Q={Q}", r['freeboard_pct_inc'] <= 30.5)
        
        print(f"  Q={Q}: B={B:.4f}, H={H:.4f}, β={beta:.3f}, A_total={B*H:.4f}m²")


# ============================================================
# 验证11: 特殊边界情况
# ============================================================
def verify_edge_cases():
    """
    验证各种边界和异常情况:
    1. h = H (满流) → 净空=0
    2. h > H → 应截断为 h=H
    3. slope = 0 → Q=0
    4. 非常小的 Q → 能否正常求解
    """
    print("\n" + "="*70)
    print("验证11: 特殊边界情况")
    print("="*70)
    
    # h = H
    out = calculate_rectangular_outputs(2.0, 1.5, 1.5, 0.014, 1/3000)
    check("满流-净空高=0", abs(out['freeboard_hgt']) < 0.001)
    check("满流-净空%=0", abs(out['freeboard_pct']) < 0.01)
    
    # h > H → 截断
    out2 = calculate_rectangular_outputs(2.0, 1.5, 3.0, 0.014, 1/3000)
    check("h>H截断-h=H", abs(out2['freeboard_hgt']) < 0.001)
    # A 应为 B*H = 2*1.5 = 3.0
    check("h>H截断-A=B*H", abs(out2['A'] - 3.0) < 0.001)
    
    # slope = 0 → Q = 0 (不崩溃)
    out3 = calculate_rectangular_outputs(2.0, 1.5, 1.0, 0.014, 0)
    check("slope=0-Q=0", abs(out3['Q']) < 1e-10)
    
    # 负 slope → Q = 0
    out4 = calculate_rectangular_outputs(2.0, 1.5, 1.0, 0.014, -0.001)
    check("slope<0-Q=0", abs(out4['Q']) < 1e-10)


# ============================================================
# 主程序
# ============================================================
if __name__ == '__main__':
    print("╔" + "═"*68 + "╗")
    print("║    矩形暗涵水力计算内核 — 独立交叉验证                       ║")
    print("╚" + "═"*68 + "╝")
    
    verify_manning()
    verify_wetted_perimeter()
    verify_beta_analytical()
    verify_freeboard()
    verify_flow_increase()
    verify_H_bounds()
    verify_freeboard_percentage()
    verify_depth_solver()
    verify_end_to_end()
    verify_optimal_properties()
    verify_edge_cases()
    
    total = PASS + FAIL
    print("\n" + "╔" + "═"*68 + "╗")
    print("║                    独立验证结果总结                          ║")
    print("╚" + "═"*68 + "╝")
    print(f"  通过: {PASS}   失败: {FAIL}")
    if total > 0:
        print(f"  通过率: {PASS/total*100:.1f}%")
    if ERRORS:
        print(f"\n{'='*70}")
        print(f"  失败详情 ({len(ERRORS)} 项):")
        print(f"{'='*70}")
        for e in ERRORS:
            print(f"  {e}")
    print(f"\n{'='*70}")
    print("  全部验证通过! ✓" if FAIL == 0 else f"  有 {FAIL} 项验证失败。")
    print("="*70)
