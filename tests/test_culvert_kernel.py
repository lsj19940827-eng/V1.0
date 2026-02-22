# -*- coding: utf-8 -*-
"""矩形暗涵计算内核 - 全面测试脚本"""

import sys, os, math, itertools
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "渠系建筑物断面计算"))
from 矩形暗涵设计 import (
    calculate_rectangular_outputs, solve_water_depth_rectangular,
    get_required_freeboard_height_rect, get_flow_increase_percent_rect,
    quick_calculate_rectangular_culvert,
    MIN_FREEBOARD_HGT_RECT, MIN_FREEBOARD_PCT_RECT, OPTIMAL_BH_RATIO,
)

PASS_COUNT = FAIL_COUNT = WARN_COUNT = 0
ERRORS = []; WARNINGS = []

def check(name, cond, detail=""):
    global PASS_COUNT, FAIL_COUNT
    if cond: PASS_COUNT += 1
    else:
        FAIL_COUNT += 1
        msg = f"FAIL: {name}" + (f" | {detail}" if detail else "")
        ERRORS.append(msg); print(f"  ✗ {msg}")

def warn(name, detail=""):
    global WARN_COUNT
    WARN_COUNT += 1
    WARNINGS.append(f"WARN: {name}" + (f" | {detail}" if detail else ""))
    print(f"  ⚠ WARN: {name}" + (f" | {detail}" if detail else ""))

def approx(a, b, tol=0.01): return abs(a-b)/max(abs(b),1e-9) < tol if abs(b)>1e-9 else abs(a)<tol
def close(a, b, tol=0.005): return abs(a-b) < tol

def ref_Q(B, h, n, slope):
    A=B*h; P=B+2*h; R=A/P if P>0 else 0
    return (1/n)*A*R**(2/3)*slope**0.5 if R>0 and n>0 and slope>0 else 0

def ref_opt_h(Q, n, slope):
    """矩形最佳断面(β=2): Q=(1/n)*2h²*(h/2)^(2/3)*√i → h=(Qn/(2^(1/3)*√i))^(3/8)"""
    return (Q*n / (2**(1/3)*slope**0.5))**(3/8)


def test_basic_hydraulics():
    print("\n" + "="*70 + "\n测试1: 基础水力要素 (A, P, R, Q, V, 净空)\n" + "="*70)
    cases = [
        (2.0, 1.5, 1.0, 0.014, 1/3000), (1.5, 1.2, 0.8, 0.013, 1/2000),
        (3.0, 2.0, 1.5, 0.016, 1/5000), (1.0, 1.0, 0.6, 0.012, 1/1000),
        (0.8, 0.8, 0.5, 0.014, 1/1500), (4.0, 3.0, 2.0, 0.020, 1/8000),
        (0.5, 0.6, 0.35, 0.011, 1/800), (2.5, 2.0, 1.2, 0.015, 1/4000),
    ]
    for idx, (B, H, h, n, slope) in enumerate(cases):
        out = calculate_rectangular_outputs(B, H, h, n, slope)
        A_e=B*h; P_e=B+2*h; R_e=A_e/P_e; Q_e=ref_Q(B,h,n,slope)
        check(f"c{idx} A=B*h",      close(out['A'],      A_e,   0.001), f"{out['A']:.4f} vs {A_e:.4f}")
        check(f"c{idx} P=B+2h",     close(out['P'],      P_e,   0.001), f"{out['P']:.4f} vs {P_e:.4f}")
        check(f"c{idx} R=A/P",      close(out['R_hyd'],  R_e,   0.001), f"{out['R_hyd']:.4f} vs {R_e:.4f}")
        check(f"c{idx} Q(曼宁)",    approx(out['Q'],     Q_e,   0.001), f"{out['Q']:.6f} vs {Q_e:.6f}")
        V_e=Q_e/A_e if A_e>0 else 0
        check(f"c{idx} V=Q/A",      approx(out['V'],     V_e,   0.001), f"{out['V']:.4f} vs {V_e:.4f}")
        check(f"c{idx} 净空高=H-h", close(out['freeboard_hgt'], H-h,   0.001))
        fb_pct_e=(B*H-A_e)/(B*H)*100
        check(f"c{idx} 净空%",      close(out['freeboard_pct'], fb_pct_e, 0.01))


def test_manning_formula():
    print("\n" + "="*70 + "\n测试2: 曼宁公式精度独立验证\n" + "="*70)
    cases = [
        (2.0, 1.0, 0.014, 1/3000), (1.0, 0.5, 0.013, 1/2000),
        (3.0, 1.5, 0.016, 1/5000), (0.5, 0.25, 0.012, 1/800),
        (5.0, 2.5, 0.020, 1/8000), (1.5, 0.75, 0.014, 1/1500),
    ]
    for B, h, n, slope in cases:
        out = calculate_rectangular_outputs(B, B*2, h, n, slope)
        A=B*h; P=B+2*h; R=A/P
        Q_man = (1/n)*A*R**(2/3)*slope**0.5
        V_man = (1/n)*R**(2/3)*slope**0.5
        check(f"Q精度 B={B},h={h}", approx(out['Q'], Q_man, 1e-4), f"{out['Q']:.8f} vs {Q_man:.8f}")
        check(f"V=Manning速度 B={B}", approx(out['V'], V_man, 1e-4), f"{out['V']:.6f} vs {V_man:.6f}")
        check(f"Q=V*A B={B}", approx(out['Q'], out['V']*out['A'], 1e-4))


def test_depth_solver():
    print("\n" + "="*70 + "\n测试3: 水深反算精度 (二分法)\n" + "="*70)
    cases = [
        (2.0, 1.5, 0.014, 1/3000, 2.0), (2.0, 1.5, 0.014, 1/3000, 1.0),  # Q=2.0<Q_max≈2.78
        (1.5, 1.2, 0.013, 1/2000, 1.5), (3.0, 2.5, 0.016, 1/5000, 5.0),
        (1.0, 0.8, 0.012, 1/1000, 0.5), (0.8, 0.7, 0.014, 1/1500, 0.3),
        (4.0, 3.0, 0.020, 1/8000, 6.0), (0.5, 0.6, 0.011, 1/800,  0.15),  # Q=6.0<Q_max≈7.57
    ]
    for idx, (B, H, n, slope, Q_t) in enumerate(cases):
        h_s, ok = solve_water_depth_rectangular(B, H, n, slope, Q_t)
        check(f"反算成功 c{idx} Q={Q_t}", ok, f"h={h_s:.4f}")
        if ok and h_s > 0:
            Q_back = ref_Q(B, h_s, n, slope)
            check(f"反算精度 c{idx}", approx(Q_back, Q_t, 0.002),
                  f"Q_back={Q_back:.5f}, target={Q_t}, err={abs(Q_back-Q_t)/Q_t*100:.3f}%")
            check(f"h<H c{idx}", h_s < H)


def test_freeboard_req():
    print("\n" + "="*70 + "\n测试4: 净空高度需求公式\n" + "="*70)
    for H in [0.6, 1.2, 2.4, 2.7, 3.0]:
        req = get_required_freeboard_height_rect(H)
        exp = max(0.4, H/6.0)
        check(f"H={H}≤3m", close(req, exp, 0.001), f"got={req:.4f}, max(0.4,H/6)={exp:.4f}")
    for H in [3.1, 4.0, 6.0]:
        req = get_required_freeboard_height_rect(H)
        check(f"H={H}>3m → 0.5", close(req, 0.5, 0.001), f"got={req:.4f}")


def test_increase_percent():
    print("\n" + "="*70 + "\n测试5: 加大流量比例查表\n" + "="*70)
    tbl = [(0.5,30),(0.99,30),(1.0,25),(4.9,25),(5.0,20),(19.9,20),
           (20.0,15),(49.9,15),(50.0,10),(99.9,10),(100.0,5),(300.0,5)]
    for Q, exp in tbl:
        check(f"Q={Q}", close(get_flow_increase_percent_rect(Q), exp, 0.01), f"got={get_flow_increase_percent_rect(Q)}")


def test_full_design():
    print("\n" + "="*70 + "\n测试6: 完整设计流程 - 核心一致性\n" + "="*70)
    cases = [
        (5.0,0.014,3000,0.5,3.0,"标准"), (1.0,0.014,2000,0.3,2.5,"小流量"),
        (0.5,0.013,1500,0.2,3.0,"微小"), (10.0,0.016,5000,0.5,2.5,"中等"),
        (20.0,0.020,4000,0.6,2.0,"较大"), (2.0,0.014,2500,0.4,3.0,"中小"),
        (0.3,0.012,1000,0.2,4.0,"极小"), (8.0,0.016,3500,0.5,2.5,"中大"),
        (3.0,0.014,2000,0.4,3.0,"常规"), (50.0,0.025,8000,0.5,2.0,"大"),
        (5.0,0.014,500,0.5,5.0,"陡坡"), (5.0,0.014,8000,0.3,2.0,"缓坡"),
        (5.0,0.030,3000,0.3,2.0,"高糙"), (5.0,0.011,3000,0.5,5.0,"低糙"),
        (15.0,0.018,6000,0.5,2.5,"大缓坡"),
    ]
    for Q,n,si,vl,vh,desc in cases:
        slope = 1/si
        r = quick_calculate_rectangular_culvert(Q,n,si,vl,vh)
        if not r['success']:
            warn(f"[{desc}]", r.get('error_message','')); continue

        B,H,h = r['B'],r['H'],r['h_design']
        A,P,R = r['A_design'],r['P_design'],r['R_hyd_design']

        check(f"[{desc}] A=B*h",   close(A, B*h, 0.01))
        check(f"[{desc}] P=B+2h",  close(P, B+2*h, 0.01))
        check(f"[{desc}] R=A/P",   close(R, A/P if P>0 else 0, 0.01))
        check(f"[{desc}] V=Q/A",   approx(r['V_design'], Q/A if A>0 else 0, 0.02))
        check(f"[{desc}] 曼宁反算Q", approx(ref_Q(B,h,n,slope), Q, 0.03),
              f"Q_back={ref_Q(B,h,n,slope):.4f}, Q={Q}")
        check(f"[{desc}] h<H",     h < H)
        req = get_required_freeboard_height_rect(H)
        check(f"[{desc}] 净空高≥要求(加大)", r['freeboard_hgt_inc'] >= req-0.005,
              f"fb={r['freeboard_hgt_inc']:.3f}, req={req:.3f}")
        check(f"[{desc}] 净空%≥10%(加大)", r['freeboard_pct_inc'] >= MIN_FREEBOARD_PCT_RECT*100-0.5)
        # 加大水深反算
        h_inc,Q_inc = r['h_increased'],r['Q_increased']
        if h_inc > 0:
            check(f"[{desc}] h_inc>h", h_inc > h)
            check(f"[{desc}] h_inc<H", h_inc < H)
            check(f"[{desc}] 加大曼宁反算Q_inc",
                  approx(ref_Q(B,h_inc,n,slope), Q_inc, 0.03),
                  f"Q_back={ref_Q(B,h_inc,n,slope):.4f}, Q_inc={Q_inc:.4f}")


def test_optimal_section():
    print("\n" + "="*70 + "\n测试7: 水力最佳断面 β=B/h=2\n" + "="*70)
    cases = [
        (5.0,0.014,3000,0.5,3.0), (1.0,0.013,2000,0.3,2.5),
        (10.0,0.016,5000,0.5,2.5), (2.0,0.014,2500,0.3,3.0),
    ]
    for Q,n,si,vl,vh in cases:
        slope=1/si
        r = quick_calculate_rectangular_culvert(Q,n,si,vl,vh)
        if not r['success']:
            warn(f"最佳断面 Q={Q}"); continue
        check(f"标识is_optimal Q={Q}", r['is_optimal_section'])
        check(f"β≈2 Q={Q}", abs(r['BH_ratio']-OPTIMAL_BH_RATIO)<=0.6,
              f"β={r['BH_ratio']:.3f}")
        # 理论验证: 对β=2最佳断面，h和b应满足Q
        h_opt = ref_opt_h(Q,n,slope)
        Q_back = ref_Q(2*h_opt, h_opt, n, slope)
        check(f"理论最佳断面反算Q Q={Q}", approx(Q_back,Q,0.005),
              f"Q_back={Q_back:.4f}")


def test_manual_B():
    print("\n" + "="*70 + "\n测试8: 手动底宽 manual_B\n" + "="*70)
    for B_m in [1.0, 1.5, 2.0, 2.5, 3.0]:
        r = quick_calculate_rectangular_culvert(5.0,0.014,3000,0.1,10.0,manual_B=B_m)
        if not r['success']:
            warn(f"manual_B={B_m}"); continue
        check(f"B匹配 B={B_m}", close(r['B'],B_m,0.015), f"B={r['B']:.3f}")
        check(f"Q一致 B={B_m}", approx(ref_Q(r['B'],r['h_design'],0.014,1/3000),5.0,0.03))


def test_manual_beta():
    print("\n" + "="*70 + "\n测试9: 手动宽深比 target_BH_ratio\n" + "="*70)
    for beta in [1.0, 1.5, 2.0, 2.5]:
        r = quick_calculate_rectangular_culvert(5.0,0.014,3000,0.1,10.0,target_BH_ratio=beta)
        if not r['success']:
            warn(f"target_BH_ratio={beta}"); continue
        check(f"β≈target β={beta}", abs(r['BH_ratio']-beta)<=0.35,
              f"actual={r['BH_ratio']:.3f}")
        check(f"Q一致 β={beta}", approx(ref_Q(r['B'],r['h_design'],0.014,1/3000),5.0,0.03))


def test_boundary():
    print("\n" + "="*70 + "\n测试10: 边界条件与异常输入\n" + "="*70)

    # Q=0 → 失败
    r = quick_calculate_rectangular_culvert(0,0.014,3000,0.5,3.0)
    check("Q=0 应失败", not r['success'])

    # n=0 → 失败
    r = quick_calculate_rectangular_culvert(5.0,0,3000,0.5,3.0)
    check("n=0 应失败", not r['success'])

    # slope_inv=0 → 不应ZeroDivisionError
    try:
        r = quick_calculate_rectangular_culvert(5.0,0.014,0,0.5,3.0)
        check("slope_inv=0 应失败", not r['success'])
    except ZeroDivisionError:
        check("slope_inv=0 不应崩溃", False, "ZeroDivisionError")

    # calculate_rectangular_outputs: h=0
    out = calculate_rectangular_outputs(2.0, 1.5, 0, 0.014, 1/3000)
    check("h=0 → A=0", out['A'] == 0 or out['A'] < 1e-9)

    # h > H → 应截断
    out = calculate_rectangular_outputs(2.0, 1.0, 2.0, 0.014, 1/3000)
    check("h>H 截断 h=H", close(out['freeboard_hgt'], 0.0, 0.001))

    # solve_water_depth: Q很大超出范围
    h_s, ok = solve_water_depth_rectangular(0.5, 0.6, 0.014, 1/3000, 1000.0)
    check("超大Q 求解应失败", not ok or h_s >= 0.6 or h_s <= 0)

    # solve_water_depth: Q=0
    h_s, ok = solve_water_depth_rectangular(2.0, 1.5, 0.014, 1/3000, 0.0)
    check("Q=0 水深=0", ok and close(h_s, 0.0, 0.01))


def test_freeboard_geometry():
    print("\n" + "="*70 + "\n测试11: 净空几何逻辑\n" + "="*70)
    # freeboard_pct = (H-h)/H*100
    cases = [(2.0,2.0,1.0), (2.0,2.0,1.5), (2.0,2.0,0.5), (1.5,1.5,1.2)]
    for B,H,h in cases:
        out = calculate_rectangular_outputs(B,H,h,0.014,1/3000)
        exp_pct = (H-h)/H*100
        exp_hgt = H-h
        check(f"净空% B={B},H={H},h={h}", close(out['freeboard_pct'],exp_pct,0.01),
              f"got={out['freeboard_pct']:.3f}%, exp={exp_pct:.3f}%")
        check(f"净空高 B={B},H={H},h={h}", close(out['freeboard_hgt'],exp_hgt,0.001))
        # 总面积
        check(f"A_total=B*H B={B}", close(out['A_total'],B*H,0.001))


def test_mass_scan():
    print("\n" + "="*70 + "\n测试12: 大规模参数扫描 (系统性组合)\n" + "="*70)
    Q_list   = [0.5, 1.0, 3.0, 5.0, 10.0, 20.0]
    n_list   = [0.012, 0.014, 0.020]
    si_list  = [1000, 3000, 6000]
    total = fail = 0
    for Q,n,si in itertools.product(Q_list,n_list,si_list):
        slope = 1/si
        r = quick_calculate_rectangular_culvert(Q,n,si,0.01,100.0)
        total += 1
        if not r['success']: continue
        B,h = r['B'],r['h_design']
        Q_back = ref_Q(B,h,n,slope)
        if not approx(Q_back, Q, 0.05):
            check(f"批量 Q={Q},n={n},1/{si} 流量一致", False,
                  f"Q_back={Q_back:.4f}, Q={Q}, err={abs(Q_back-Q)/Q*100:.1f}%")
            fail += 1
        A_exp = B*h
        if not close(r['A_design'], A_exp, 0.05):
            check(f"批量 Q={Q},n={n},1/{si} 面积", False,
                  f"A={r['A_design']:.3f}, B*h={A_exp:.3f}")
            fail += 1
        P_exp = B+2*h
        if not close(r['P_design'], P_exp, 0.05):
            check(f"批量 Q={Q},n={n},1/{si} 湿周", False,
                  f"P={r['P_design']:.3f}, B+2h={P_exp:.3f}")
            fail += 1
    print(f"  批量扫描: {total}组参数, {fail}项不一致")


if __name__ == '__main__':
    print("╔"+"═"*68+"╗")
    print("║       矩形暗涵计算内核 - 全面测试                              ║")
    print("╚"+"═"*68+"╝")

    test_basic_hydraulics()
    test_manning_formula()
    test_depth_solver()
    test_freeboard_req()
    test_increase_percent()
    test_full_design()
    test_optimal_section()
    test_manual_B()
    test_manual_beta()
    test_boundary()
    test_freeboard_geometry()
    test_mass_scan()

    total = PASS_COUNT + FAIL_COUNT
    print("\n" + "╔"+"═"*68+"╗")
    print("║                       测试结果总结                            ║")
    print("╚"+"═"*68+"╝")
    print(f"  通过: {PASS_COUNT}   失败: {FAIL_COUNT}   警告: {WARN_COUNT}")
    if total > 0: print(f"  通过率: {PASS_COUNT/total*100:.1f}%")
    if ERRORS:
        print(f"\n{'='*70}\n  失败详情 ({len(ERRORS)} 项):\n{'='*70}")
        for e in ERRORS: print(f"  {e}")
    if WARNINGS:
        print(f"\n{'='*70}\n  警告详情 ({len(WARNINGS)} 项):\n{'='*70}")
        for w in WARNINGS: print(f"  {w}")
    print(f"\n{'='*70}")
    print("  所有测试通过! ✓" if FAIL_COUNT == 0 else f"  有 {FAIL_COUNT} 项测试失败。")
    print("="*70)
