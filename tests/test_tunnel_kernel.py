# -*- coding: utf-8 -*-
"""
隧洞设计计算内核 - 全面测试脚本

测试范围:
1.  圆形断面基础几何 (面积、湿周)
2.  圆形断面水力要素 (R_hyd, V, Q, 净空)
3.  圆形断面水深反算精度
4.  圆形断面完整设计 quick_calculate_circular - 大量参数
5.  圆拱直墙型基础几何
6.  圆拱直墙型水深反算
7.  圆拱直墙型完整设计 quick_calculate_horseshoe - 大量参数
8.  马蹄形标准Ⅰ/Ⅱ型基础几何 (含分段连续性)
9.  马蹄形水深反算
10. 马蹄形完整设计 quick_calculate_horseshoe_std - 大量参数
11. 加大流量比例查表
12. 边界条件与异常输入
"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calc_渠系计算算法内核"))

from 隧洞设计 import (
    calculate_circular_area, calculate_circular_perimeter,
    calculate_circular_outputs, solve_water_depth_circular, quick_calculate_circular,
    calculate_horseshoe_area, calculate_horseshoe_perimeter,
    calculate_horseshoe_total_area, calculate_horseshoe_outputs,
    solve_water_depth_horseshoe, quick_calculate_horseshoe,
    calculate_horseshoe_std_elements, calculate_horseshoe_std_outputs,
    solve_water_depth_horseshoe_std, quick_calculate_horseshoe_std,
    get_flow_increase_percent,
    PI, HORSESHOE_T1, HORSESHOE_THETA1, HORSESHOE_C1,
    HORSESHOE_T2, HORSESHOE_THETA2, HORSESHOE_C2,
    MIN_FREEBOARD_PCT_TUNNEL, MIN_FREEBOARD_HGT_TUNNEL,
)

# ============================================================
# 测试辅助
# ============================================================
PASS_COUNT = 0; FAIL_COUNT = 0; WARN_COUNT = 0
ERRORS = []; WARNINGS = []

def check(name, cond, detail=""):
    global PASS_COUNT, FAIL_COUNT
    if cond:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1
        msg = f"FAIL: {name}" + (f" | {detail}" if detail else "")
        ERRORS.append(msg); print(f"  ✗ {msg}")

def warn(name, detail=""):
    global WARN_COUNT; WARN_COUNT += 1
    msg = f"WARN: {name}" + (f" | {detail}" if detail else "")
    WARNINGS.append(msg); print(f"  ⚠ {msg}")

def rel_eq(a, b, tol=0.01):
    return abs(a - b) / max(abs(b), 1e-9) < tol if abs(b) >= 1e-9 else abs(a) < tol

def abs_eq(a, b, tol=0.001): return abs(a - b) < tol


# ============================================================
# 独立验算函数 (不依赖被测模块)
# ============================================================
def _circ_area(D, h):
    if D <= 0 or h <= 0: return 0.0
    R = D / 2; h = min(h, D)
    if h >= D: return math.pi * R ** 2
    theta = 2 * math.acos((R - h) / R)
    return R ** 2 * (theta - math.sin(theta)) / 2

def _circ_perim(D, h):
    if D <= 0 or h <= 0: return 0.0
    R = D / 2; h = min(h, D)
    if h >= D: return math.pi * D
    theta = 2 * math.acos((R - h) / R)
    return R * theta

def _manning(A, P, n, slope):
    if A <= 0 or P <= 0 or n <= 0 or slope <= 0: return 0.0
    return (1 / n) * A * (A / P) ** (2 / 3) * slope ** 0.5

def _hs_total_area(B, H, tr):
    if abs(math.sin(tr / 2)) < 1e-9: return 0.0
    Ra = (B / 2) / math.sin(tr / 2)
    Ha = Ra * (1 - math.cos(tr / 2))
    Hs = max(0, H - Ha)
    return B * Hs + (Ra ** 2 / 2) * (tr - math.sin(tr))

def _hs_area(B, H, tr, h):
    if abs(math.sin(tr / 2)) < 1e-9: return 0.0
    Ra = (B / 2) / math.sin(tr / 2)
    Ha = Ra * (1 - math.cos(tr / 2))
    Hs = max(0, H - Ha); he = min(h, H)
    if he <= Hs: return B * he
    Ar = B * Hs; hi = he - Hs
    if hi >= Ha: return Ar + (Ra ** 2 / 2) * (tr - math.sin(tr))
    At = (Ra ** 2 / 2) * (tr - math.sin(tr))
    hd = Ha - hi; dt = Ra - hd
    at = math.acos(max(-1, min(1, dt / Ra)))
    Ad = Ra ** 2 * at - dt * math.sqrt(max(0, Ra ** 2 - dt ** 2))
    return Ar + At - Ad

def _hs_perim(B, H, tr, h):
    if abs(math.sin(tr / 2)) < 1e-9: return 0.0
    Ra = (B / 2) / math.sin(tr / 2)
    Ha = Ra * (1 - math.cos(tr / 2))
    Hs = max(0, H - Ha); he = min(h, H)
    if he <= Hs: return B + 2 * he
    hi = he - Hs; base = B + 2 * Hs
    if hi >= Ha: return base + Ra * tr
    hd = Ha - hi; dt = Ra - hd
    at = math.acos(max(-1, min(1, dt / Ra)))
    return base + Ra * tr - 2 * Ra * at

def _shoe_elems(stype, r, h):
    """独立计算马蹄形要素，返回 (A, B_width, P)"""
    t = HORSESHOE_T1 if stype == 1 else HORSESHOE_T2
    theta = HORSESHOE_THETA1 if stype == 1 else HORSESHOE_THETA2
    c = HORSESHOE_C1 if stype == 1 else HORSESHOE_C2
    Ra = t * r; e = Ra * (1 - math.cos(theta))
    if h <= 0: return 0.0, 0.0, 0.0
    if h <= e:
        cv = max(-1, min(1, 1 - h / Ra)); beta = math.acos(cv)
        return Ra**2*(beta - 0.5*math.sin(2*beta)), 2*Ra*math.sin(beta), 2*Ra*beta
    elif h <= r:
        sv = max(-1, min(1, (1 - h/r) / t)); alpha = math.asin(sv)
        A = Ra**2 * (c - alpha - 0.5*math.sin(2*alpha) + ((2*t-2)/t)*math.sin(alpha))
        return A, 2*r*(t*math.cos(alpha)-t+1), 2*t*r*(2*theta-alpha)
    elif h <= 2 * r:
        cv = max(-1, min(1, h/r - 1)); ph = math.acos(cv); phi = 2*ph
        A = r**2 * (t**2*c + 0.5*(math.pi - phi + math.sin(phi)))
        return A, 2*r*math.sin(ph), 4*t*r*theta + r*(math.pi - phi)
    return 0.0, 0.0, 0.0


# ============================================================
# 测试1: 圆形断面基础几何
# ============================================================
def test_circular_geometry():
    print("\n" + "="*60)
    print("测试1: 圆形断面基础几何 (面积、湿周)")
    print("="*60)

    cases = [(4.0, 0.5), (4.0, 1.0), (4.0, 2.0), (4.0, 3.0), (4.0, 3.99),
             (2.0, 1.0), (3.0, 1.5), (5.0, 2.5), (6.0, 3.0), (2.41, 1.6),
             (3.0, 0.75), (8.0, 5.0), (10.0, 6.0)]
    for D, h in cases:
        A = calculate_circular_area(D, h); P = calculate_circular_perimeter(D, h)
        Ae = _circ_area(D, h); Pe = _circ_perim(D, h)
        check(f"圆形面积 D={D},h={h}", abs_eq(A, Ae, 1e-6), f"got={A:.6f},exp={Ae:.6f}")
        check(f"圆形湿周 D={D},h={h}", abs_eq(P, Pe, 1e-6), f"got={P:.6f},exp={Pe:.6f}")

    # 半满：A=πR²/2, P=πR
    for D in [2.0, 3.0, 4.0, 5.0, 6.0]:
        R = D / 2
        check(f"圆形半满面积 D={D}", abs_eq(calculate_circular_area(D, D/2), math.pi*R**2/2, 0.001),
              f"got={calculate_circular_area(D,D/2):.4f},exp={math.pi*R**2/2:.4f}")
        check(f"圆形半满湿周 D={D}", abs_eq(calculate_circular_perimeter(D, D/2), math.pi*R, 0.001))

    # 满管
    for D in [2.0, 3.0, 4.0]:
        R = D / 2
        check(f"圆形满管面积 D={D}", abs_eq(calculate_circular_area(D, D), math.pi*R**2, 0.001))

    # 边界 h=0
    check("圆形面积 h=0 → 0", calculate_circular_area(4.0, 0) == 0.0)
    check("圆形湿周 h=0 → 0", calculate_circular_perimeter(4.0, 0) == 0.0)


# ============================================================
# 测试2: 圆形断面水力要素
# ============================================================
def test_circular_outputs():
    print("\n" + "="*60)
    print("测试2: 圆形断面水力要素 (R_hyd, V, Q, 净空)")
    print("="*60)

    cases = [(4.0, 2.0, 0.014, 1/2000), (3.0, 1.5, 0.013, 1/3000),
             (5.0, 2.5, 0.016, 1/5000), (2.0, 1.0, 0.012, 1/1000),
             (6.0, 3.0, 0.020, 1/4000), (2.41, 1.6, 0.014, 1/2000),
             (8.0, 4.0, 0.018, 1/6000), (10.0, 6.0, 0.022, 1/8000)]
    for D, h, n, slope in cases:
        o = calculate_circular_outputs(D, h, n, slope)
        Ae = _circ_area(D, h); Pe = _circ_perim(D, h)
        Re = Ae / Pe if Pe > 0 else 0
        Qe = _manning(Ae, Pe, n, slope)
        Ve = Qe / Ae if Ae > 0 else 0
        Ate = math.pi * (D/2)**2
        fb_pct_e = (Ate - Ae) / Ate * 100 if Ate > 0 else 100

        check(f"圆形outputs A D={D},h={h}", abs_eq(o['A'], Ae, 1e-6))
        check(f"圆形outputs P D={D},h={h}", abs_eq(o['P'], Pe, 1e-6))
        check(f"圆形outputs R_hyd D={D},h={h}", abs_eq(o['R_hyd'], Re, 1e-6))
        check(f"圆形outputs Q D={D},h={h}", rel_eq(o['Q'], Qe, 0.001),
              f"got={o['Q']:.4f},exp={Qe:.4f}")
        check(f"圆形outputs V*A=Q D={D},h={h}", rel_eq(o['V'] * o['A'], o['Q'], 0.001))
        check(f"圆形outputs A_total=πR² D={D}", abs_eq(o['A_total'], Ate, 0.001))
        check(f"圆形outputs fb_hgt=D-h D={D},h={h}", abs_eq(o['freeboard_hgt'], D - h, 1e-6))
        check(f"圆形outputs fb_pct D={D},h={h}", abs_eq(o['freeboard_pct'], fb_pct_e, 0.001))


# ============================================================
# 测试3: 圆形断面水深反算精度
# ============================================================
def test_circular_solver():
    print("\n" + "="*60)
    print("测试3: 圆形断面水深反算精度")
    print("="*60)

    cases = [
        (4.0, 0.014, 2000, 5.0), (3.0, 0.013, 3000, 3.0),
        (5.0, 0.016, 5000, 8.0), (2.0, 0.012, 1000, 1.5),
        (6.0, 0.020, 4000, 12.0), (2.41, 0.014, 2000, 4.0),
        (8.0, 0.025, 8000, 20.0), (10.0, 0.017, 6000, 50.0),
        (3.5, 0.014, 2500, 6.0), (4.5, 0.016, 3500, 9.0),
        (3.0, 0.015, 2000, 4.0), (7.0, 0.020, 5000, 15.0),
    ]
    for D, n, si, Qt in cases:
        slope = 1.0 / si
        h, ok = solve_water_depth_circular(D, n, slope, Qt)
        if not ok:
            warn(f"圆形求解 D={D},Q={Qt}", "失败"); continue
        o = calculate_circular_outputs(D, h, n, slope)
        err = abs(o['Q'] - Qt) / Qt * 100
        check(f"圆形水深反算 D={D},Q={Qt}",
              rel_eq(o['Q'], Qt, 0.01),
              f"h={h:.4f},Q_back={o['Q']:.4f},误差={err:.3f}%")
        check(f"圆形水深反算 h∈(0,D) D={D},Q={Qt}",
              0 < h < D, f"h={h:.4f},D={D}")


# ============================================================
# 测试4: 圆形断面完整设计 - 大量参数
# ============================================================
def test_circular_design():
    print("\n" + "="*60)
    print("测试4: 圆形断面完整设计 - 大量参数")
    print("="*60)

    cases = [
        (4.0, 0.014, 2000, 0.1, 100.0, "截图参数"),
        (1.0, 0.014, 2000, 0.1, 100.0, "小流量"),
        (0.5, 0.012, 1500, 0.1, 100.0, "极小流量"),
        (5.0, 0.014, 3000, 0.5, 3.0,   "标准"),
        (10.0, 0.016, 5000, 0.5, 3.0,  "中等"),
        (20.0, 0.020, 4000, 0.5, 2.5,  "较大"),
        (50.0, 0.025, 8000, 0.5, 2.0,  "大流量"),
        (0.8, 0.013, 1000, 0.2, 5.0,   "小陡坡"),
        (3.0, 0.015, 3000, 0.4, 3.0,   "中等2"),
        (8.0, 0.014, 2000, 0.5, 3.5,   "中大"),
        (15.0, 0.017, 5000, 0.5, 2.5,  "较大2"),
        (0.3, 0.012, 800,  0.1, 10.0,  "微小"),
        (30.0, 0.022, 6000, 0.5, 2.0,  "大2"),
        (2.5, 0.014, 2500, 0.3, 4.0,   "中等3"),
        (7.0, 0.016, 4000, 0.4, 3.0,   "中大2"),
        (12.0, 0.018, 5500, 0.5, 2.5,  "较大3"),
        (2.0, 0.014, 1500, 0.2, 5.0,   "小中"),
        (40.0, 0.022, 7000, 0.5, 2.0,  "大3"),
    ]
    for Q, n, si, vmin, vmax, desc in cases:
        slope = 1.0 / si
        r = quick_calculate_circular(Q=Q, n=n, slope_inv=si, v_min=vmin, v_max=vmax)
        if not r['success']:
            warn(f"圆形[{desc}]", r['error_message'][:60]); continue

        D = r['D']; hd = r['h_design']; hinc = r['h_increased']
        Vd = r['V_design']; Ad = r['A_design']; Pd = r['P_design']
        Qi = r['Q_increased']; inc = r['increase_percent']

        check(f"[{desc}] D>0", D > 0)
        check(f"[{desc}] hd<D", hd < D, f"hd={hd:.3f},D={D:.3f}")
        check(f"[{desc}] hinc<D", hinc < D, f"hinc={hinc:.3f},D={D:.3f}")

        # 独立验算几何
        Ae = _circ_area(D, hd); Pe = _circ_perim(D, hd)
        check(f"[{desc}] A一致", abs_eq(Ad, Ae, 0.001), f"Ad={Ad:.4f},exp={Ae:.4f}")
        check(f"[{desc}] P一致", abs_eq(Pd, Pe, 0.001))

        # 曼宁公式反算流量
        Qm = _manning(Ae, Pe, n, slope)
        check(f"[{desc}] 曼宁反算Q", rel_eq(Qm, Q, 0.02),
              f"Q_man={Qm:.4f},Q={Q},误差={abs(Qm-Q)/Q*100:.2f}%")
        check(f"[{desc}] V*A≈Q", rel_eq(Vd * Ad, Q, 0.02))

        # 流速约束
        check(f"[{desc}] V≥vmin", Vd >= vmin - 0.01, f"V={Vd:.3f}")
        check(f"[{desc}] V≤vmax", Vd <= vmax + 0.01, f"V={Vd:.3f}")

        # 净空高度
        check(f"[{desc}] 净空高=D-h", abs_eq(r['freeboard_hgt_design'], D - hd, 0.001))
        check(f"[{desc}] A_total=πR²",
              abs_eq(r['A_total'], math.pi * (D/2)**2, 0.001))

        # 加大流量
        check(f"[{desc}] Q_inc", rel_eq(Qi, Q * (1 + inc/100), 0.001))

        # 加大工况反算
        Ai_e = _circ_area(D, hinc); Pi_e = _circ_perim(D, hinc)
        check(f"[{desc}] 加大Q反算",
              rel_eq(_manning(Ai_e, Pi_e, n, slope), Qi, 0.02))

        # 净空约束
        check(f"[{desc}] 净空%≥15",
              r['freeboard_pct_inc'] >= 15.0 - 0.1,
              f"fb%={r['freeboard_pct_inc']:.1f}")
        check(f"[{desc}] 净空高≥0.4",
              r['freeboard_hgt_inc'] >= 0.4 - 0.001,
              f"fb_hgt={r['freeboard_hgt_inc']:.3f}")

    # 手动直径
    print("  -- 手动直径 --")
    for Dm in [2.5, 3.0, 4.0, 5.0, 6.0]:
        r = quick_calculate_circular(Q=5.0, n=0.014, slope_inv=3000,
                                     v_min=0.1, v_max=100.0, manual_D=Dm)
        if r['success']:
            check(f"手动D={Dm}匹配", abs_eq(r['D'], Dm, 0.001))
            check(f"手动D={Dm} h<D", r['h_design'] < Dm)
        else:
            warn(f"手动D={Dm}", r['error_message'][:50])


# ============================================================
# 测试5: 圆拱直墙型基础几何
# ============================================================
def test_horseshoe_geometry():
    print("\n" + "="*60)
    print("测试5: 圆拱直墙型基础几何")
    print("="*60)

    configs = [
        (3.0, 4.0, 180), (3.0, 4.0, 150), (3.0, 4.0, 120),
        (4.0, 5.5, 180), (2.0, 3.0, 150), (5.0, 6.5, 120),
        (3.5, 5.0, 160), (6.0, 8.0, 150), (2.5, 3.5, 130),
    ]
    for B, H, tdeg in configs:
        tr = math.radians(tdeg)
        Ra = (B/2) / math.sin(tr/2)
        Ha = Ra * (1 - math.cos(tr/2))
        Hs = max(0, H - Ha)

        test_h = [Hs * 0.3, Hs * 0.8, Hs + Ha * 0.3, Hs + Ha * 0.7, H * 0.96]
        for h in test_h:
            if h < 0.001: continue
            Am = calculate_horseshoe_area(B, H, tr, h)
            Pm = calculate_horseshoe_perimeter(B, H, tr, h)
            Ae = _hs_area(B, H, tr, h)
            Pe = _hs_perim(B, H, tr, h)
            check(f"圆拱面积 B={B},θ={tdeg},h={h:.2f}",
                  abs_eq(Am, Ae, 0.001), f"mod={Am:.4f},exp={Ae:.4f}")
            check(f"圆拱湿周 B={B},θ={tdeg},h={h:.2f}",
                  abs_eq(Pm, Pe, 0.001), f"mod={Pm:.4f},exp={Pe:.4f}")

        # 总面积
        At_mod = calculate_horseshoe_total_area(B, H, tr)
        At_exp = _hs_total_area(B, H, tr)
        check(f"圆拱总面积 B={B},θ={tdeg}", abs_eq(At_mod, At_exp, 0.001),
              f"mod={At_mod:.4f},exp={At_exp:.4f}")

        # 满水时面积 ≈ 总面积
        Af = calculate_horseshoe_area(B, H, tr, H)
        check(f"圆拱满水=总面积 B={B},θ={tdeg}",
              abs_eq(Af, At_mod, 0.01), f"A_full={Af:.4f},A_total={At_mod:.4f}")

        # 单调性：水深越大面积越大
        h_vals = sorted([h for h in test_h if h > 0.001])
        for i in range(len(h_vals) - 1):
            A1 = calculate_horseshoe_area(B, H, tr, h_vals[i])
            A2 = calculate_horseshoe_area(B, H, tr, h_vals[i+1])
            check(f"圆拱面积单调 B={B},θ={tdeg},h↑",
                  A2 >= A1 - 1e-6, f"A({h_vals[i]:.2f})={A1:.4f}>A({h_vals[i+1]:.2f})={A2:.4f}")


# ============================================================
# 测试6: 圆拱直墙型水深反算
# ============================================================
def test_horseshoe_solver():
    print("\n" + "="*60)
    print("测试6: 圆拱直墙型水深反算")
    print("="*60)

    cases = [
        (3.0, 4.5, 180, 0.014, 2000, 5.0),
        (4.0, 5.5, 150, 0.016, 3000, 10.0),
        (2.5, 3.5, 120, 0.013, 2500, 3.0),
        (5.0, 7.0, 180, 0.020, 5000, 20.0),
        (3.5, 5.0, 150, 0.015, 3500, 8.0),
        (2.0, 3.2, 150, 0.013, 2000, 2.0),
        (4.5, 6.5, 120, 0.018, 4000, 12.0),
        (6.0, 8.5, 180, 0.022, 6000, 30.0),
    ]
    for B, H, tdeg, n, si, Qt in cases:
        tr = math.radians(tdeg); slope = 1.0 / si
        h, ok = solve_water_depth_horseshoe(B, H, tr, n, slope, Qt)
        if not ok:
            warn(f"圆拱求解 B={B},θ={tdeg},Q={Qt}", "失败"); continue
        o = calculate_horseshoe_outputs(B, H, tr, h, n, slope)
        err = abs(o['Q'] - Qt) / Qt * 100
        check(f"圆拱水深反算 B={B},θ={tdeg},Q={Qt}",
              rel_eq(o['Q'], Qt, 0.01),
              f"h={h:.4f},Q_back={o['Q']:.4f},误差={err:.3f}%")
        check(f"圆拱反算 h∈(0,H) B={B},θ={tdeg},Q={Qt}",
              0 < h < H, f"h={h:.4f},H={H}")


# ============================================================
# 测试7: 圆拱直墙型完整设计 - 大量参数
# ============================================================
def test_horseshoe_design():
    print("\n" + "="*60)
    print("测试7: 圆拱直墙型完整设计 - 大量参数")
    print("="*60)

    cases = [
        (5.0,  0.014, 3000, 0.5, 3.0, 180, "默认θ=180"),
        (5.0,  0.014, 3000, 0.5, 3.0, 150, "θ=150"),
        (5.0,  0.014, 3000, 0.5, 3.0, 120, "θ=120"),
        (10.0, 0.016, 4000, 0.5, 3.0, 150, "中等θ150"),
        (2.0,  0.013, 2000, 0.3, 4.0, 150, "小流量"),
        (20.0, 0.020, 5000, 0.5, 2.5, 150, "大流量"),
        (3.0,  0.014, 2500, 0.4, 3.5, 120, "小中θ120"),
        (8.0,  0.016, 3500, 0.5, 3.0, 150, "中大"),
        (15.0, 0.018, 5000, 0.5, 2.5, 150, "较大"),
        (1.0,  0.013, 1500, 0.2, 5.0, 150, "小流量2"),
        (30.0, 0.022, 6000, 0.5, 2.0, 150, "大2"),
        (6.0,  0.015, 3000, 0.4, 3.0, 160, "θ=160"),
        (4.0,  0.014, 2500, 0.4, 3.5, 130, "θ=130"),
        (12.0, 0.017, 4500, 0.5, 2.5, 150, "较大2"),
    ]
    for Q, n, si, vmin, vmax, tdeg, desc in cases:
        slope = 1.0 / si
        r = quick_calculate_horseshoe(Q=Q, n=n, slope_inv=si, v_min=vmin, v_max=vmax, theta_deg=tdeg)
        if not r['success']:
            warn(f"圆拱[{desc}]", r['error_message'][:60]); continue

        B = r['B']; H = r['H_total']; hd = r['h_design']; hinc = r['h_increased']
        Vd = r['V_design']; Ad = r['A_design']; Pd = r['P_design']
        Qi = r['Q_increased']; inc = r['increase_percent']
        tr_res = math.radians(r['theta_deg'])

        check(f"圆拱[{desc}] B>0", B > 0)
        check(f"圆拱[{desc}] H>0", H > 0)
        check(f"圆拱[{desc}] hd<H", hd < H, f"hd={hd:.3f},H={H:.3f}")
        check(f"圆拱[{desc}] hinc<H", hinc < H)

        # 独立验算几何
        Ae = _hs_area(B, H, tr_res, hd); Pe = _hs_perim(B, H, tr_res, hd)
        check(f"圆拱[{desc}] A一致", abs_eq(Ad, Ae, 0.01), f"Ad={Ad:.4f},exp={Ae:.4f}")
        check(f"圆拱[{desc}] P一致", abs_eq(Pd, Pe, 0.01))

        # 曼宁反算
        Qm = _manning(Ae, Pe, n, slope)
        check(f"圆拱[{desc}] 曼宁反算Q", rel_eq(Qm, Q, 0.02),
              f"Q_man={Qm:.4f},Q={Q},误差={abs(Qm-Q)/Q*100:.2f}%")
        check(f"圆拱[{desc}] V*A≈Q", rel_eq(Vd * Ad, Q, 0.02))

        # 流速约束
        check(f"圆拱[{desc}] V≥vmin", Vd >= vmin - 0.01)
        check(f"圆拱[{desc}] V≤vmax", Vd <= vmax + 0.01)

        # 加大流量
        check(f"圆拱[{desc}] Q_inc", rel_eq(Qi, Q * (1 + inc/100), 0.001))
        Ai_e = _hs_area(B, H, tr_res, hinc); Pi_e = _hs_perim(B, H, tr_res, hinc)
        check(f"圆拱[{desc}] 加大Q反算", rel_eq(_manning(Ai_e, Pi_e, n, slope), Qi, 0.02))

        # 净空约束
        check(f"圆拱[{desc}] 净空%≥15", r['freeboard_pct_inc'] >= 15.0 - 0.1,
              f"fb%={r['freeboard_pct_inc']:.1f}")
        check(f"圆拱[{desc}] 净空高≥0.4", r['freeboard_hgt_inc'] >= 0.4 - 0.001)

        # A_total 一致
        At_exp = _hs_total_area(B, H, tr_res)
        check(f"圆拱[{desc}] A_total", abs_eq(r['A_total'], At_exp, 0.01))

        # HB_ratio = H/B
        check(f"圆拱[{desc}] HB_ratio=H/B",
              abs_eq(r['HB_ratio'], H / B, 0.001))


# ============================================================
# 测试8: 马蹄形标准Ⅰ/Ⅱ型基础几何 (含分段连续性)
# ============================================================
def test_horseshoe_std_geometry():
    print("\n" + "="*60)
    print("测试8: 马蹄形标准Ⅰ/Ⅱ型基础几何")
    print("="*60)

    for stype in [1, 2]:
        t = HORSESHOE_T1 if stype == 1 else HORSESHOE_T2
        theta = HORSESHOE_THETA1 if stype == 1 else HORSESHOE_THETA2
        label = f"Ⅰ型" if stype == 1 else f"Ⅱ型"

        for r in [1.0, 1.5, 2.0, 2.5, 3.0]:
            Ra = t * r; e = Ra * (1 - math.cos(theta))

            # 各段典型水深
            depths = [e*0.3, e*0.7, e*0.999, (e+r)*0.5, r*0.999, r*1.001, r*1.5, 2*r*0.98]
            for h in depths:
                if h <= 0 or h > 2 * r: continue
                A_m, Bw_m, P_m, ok = calculate_horseshoe_std_elements(stype, r, h)
                if not ok:
                    warn(f"马蹄{label} r={r},h={h:.3f}", "返回失败"); continue
                Ae, Bwe, Pe = _shoe_elems(stype, r, h)
                check(f"马蹄{label} r={r} A h={h:.3f}",
                      abs_eq(A_m, Ae, 0.001), f"mod={A_m:.5f},exp={Ae:.5f}")
                check(f"马蹄{label} r={r} P h={h:.3f}",
                      abs_eq(P_m, Pe, 0.001), f"mod={P_m:.5f},exp={Pe:.5f}")
                check(f"马蹄{label} r={r} A≥0", A_m >= 0)
                check(f"马蹄{label} r={r} P≥0", P_m >= 0)

            # 分段边界连续性 (A在 h=e 和 h=r 处连续)
            eps = 1e-5
            for hb, label_b in [(e, "h=e"), (r, "h=r")]:
                if hb <= 0 or hb > 2*r: continue
                A_lo, _, _, ok_lo = calculate_horseshoe_std_elements(stype, r, hb - eps)
                A_hi, _, _, ok_hi = calculate_horseshoe_std_elements(stype, r, hb + eps)
                if ok_lo and ok_hi:
                    check(f"马蹄{label} r={r} A连续@{label_b}",
                          abs_eq(A_lo, A_hi, 0.01),
                          f"A_lo={A_lo:.5f},A_hi={A_hi:.5f}")

            # 满管时面积（h=2r）
            A_full, _, _, ok_f = calculate_horseshoe_std_elements(stype, r, 2*r - 1e-6)
            if ok_f:
                check(f"马蹄{label} r={r} 满管A>0", A_full > 0)

            # 单调性：水深越大，面积越大
            prev_A = 0.0
            for hh in [e*0.5, e*0.99, (e+r)*0.5, r*0.99, r*1.01, r*1.5, 2*r*0.97]:
                if hh <= 0 or hh > 2*r: continue
                A_cur, _, _, ok_c = calculate_horseshoe_std_elements(stype, r, hh)
                if ok_c:
                    check(f"马蹄{label} r={r} 面积单调 h={hh:.3f}",
                          A_cur >= prev_A - 0.01,
                          f"A_cur={A_cur:.4f} < prev={prev_A:.4f}")
                    prev_A = A_cur


# ============================================================
# 测试9: 马蹄形水深反算
# ============================================================
def test_horseshoe_std_solver():
    print("\n" + "="*60)
    print("测试9: 马蹄形水深反算精度")
    print("="*60)

    cases = [
        (1, 2.0, 0.014, 2000, 5.0),
        (1, 3.0, 0.016, 3000, 12.0),
        (1, 1.5, 0.013, 1500, 3.0),
        (1, 4.0, 0.020, 5000, 25.0),
        (2, 2.0, 0.014, 2000, 5.0),
        (2, 3.0, 0.016, 3000, 12.0),
        (2, 1.5, 0.013, 1500, 3.0),
        (2, 4.0, 0.020, 5000, 25.0),
        (1, 2.5, 0.015, 2500, 8.0),
        (2, 2.5, 0.015, 2500, 8.0),
    ]
    for stype, r, n, si, Qt in cases:
        slope = 1.0 / si
        h, ok = solve_water_depth_horseshoe_std(stype, r, n, slope, Qt)
        label = "Ⅰ型" if stype == 1 else "Ⅱ型"
        if not ok:
            warn(f"马蹄{label} r={r},Q={Qt}", "求解失败"); continue
        o = calculate_horseshoe_std_outputs(stype, r, h, n, slope)
        err = abs(o['Q'] - Qt) / Qt * 100
        check(f"马蹄{label} r={r} 水深反算 Q={Qt}",
              rel_eq(o['Q'], Qt, 0.01),
              f"h={h:.4f},Q_back={o['Q']:.4f},误差={err:.3f}%")
        check(f"马蹄{label} r={r} h∈(0,2r)",
              0 < h < 2 * r, f"h={h:.4f},2r={2*r}")


# ============================================================
# 测试10: 马蹄形完整设计 - 大量参数
# ============================================================
def test_horseshoe_std_design():
    print("\n" + "="*60)
    print("测试10: 马蹄形完整设计 - 大量参数")
    print("="*60)

    cases = [
        (5.0,  0.014, 3000, 0.5, 3.0, 1, "Ⅰ型标准"),
        (5.0,  0.014, 3000, 0.5, 3.0, 2, "Ⅱ型标准"),
        (1.0,  0.013, 2000, 0.2, 5.0, 1, "Ⅰ型小流量"),
        (1.0,  0.013, 2000, 0.2, 5.0, 2, "Ⅱ型小流量"),
        (10.0, 0.016, 4000, 0.5, 3.0, 1, "Ⅰ型中等"),
        (10.0, 0.016, 4000, 0.5, 3.0, 2, "Ⅱ型中等"),
        (20.0, 0.020, 5000, 0.5, 2.5, 1, "Ⅰ型较大"),
        (20.0, 0.020, 5000, 0.5, 2.5, 2, "Ⅱ型较大"),
        (3.0,  0.014, 2500, 0.3, 4.0, 1, "Ⅰ型小中"),
        (3.0,  0.014, 2500, 0.3, 4.0, 2, "Ⅱ型小中"),
        (8.0,  0.016, 3500, 0.5, 3.0, 1, "Ⅰ型中大"),
        (8.0,  0.016, 3500, 0.5, 3.0, 2, "Ⅱ型中大"),
        (15.0, 0.018, 4500, 0.5, 2.5, 1, "Ⅰ型较大2"),
        (2.0,  0.013, 1500, 0.2, 5.0, 1, "Ⅰ型小2"),
        (30.0, 0.022, 6000, 0.5, 2.0, 1, "Ⅰ型大"),
    ]
    for Q, n, si, vmin, vmax, stype, desc in cases:
        slope = 1.0 / si
        r = quick_calculate_horseshoe_std(Q=Q, n=n, slope_inv=si, v_min=vmin, v_max=vmax,
                                          section_type=stype)
        if not r['success']:
            warn(f"马蹄[{desc}]", r['error_message'][:60]); continue

        rv = r['r']; hd = r['h_design']; hinc = r['h_increased']
        Vd = r['V_design']; Ad = r['A_design']; Pd = r['P_design']
        Qi = r['Q_increased']; inc = r['increase_percent']

        check(f"[{desc}] r>0", rv > 0)
        check(f"[{desc}] hd<2r", hd < 2*rv, f"hd={hd:.3f},2r={2*rv:.3f}")
        check(f"[{desc}] hinc<2r", hinc < 2*rv)
        check(f"[{desc}] D_equiv=2r", abs_eq(r['D_equiv'], 2*rv, 0.001))

        # 独立验算几何
        Ae, _, Pe = _shoe_elems(stype, rv, hd)
        check(f"[{desc}] A一致", abs_eq(Ad, Ae, 0.01), f"Ad={Ad:.4f},exp={Ae:.4f}")
        check(f"[{desc}] P一致", abs_eq(Pd, Pe, 0.01))

        # 曼宁反算
        Qm = _manning(Ae, Pe, n, slope)
        check(f"[{desc}] 曼宁反算Q", rel_eq(Qm, Q, 0.02),
              f"Q_man={Qm:.4f},Q={Q},误差={abs(Qm-Q)/Q*100:.2f}%")
        check(f"[{desc}] V*A≈Q", rel_eq(Vd * Ad, Q, 0.02))

        # 流速约束
        check(f"[{desc}] V≥vmin", Vd >= vmin - 0.01)
        check(f"[{desc}] V≤vmax", Vd <= vmax + 0.01)

        # 加大流量
        check(f"[{desc}] Q_inc", rel_eq(Qi, Q * (1 + inc/100), 0.001))
        Ai_e, _, Pi_e = _shoe_elems(stype, rv, hinc)
        check(f"[{desc}] 加大Q反算", rel_eq(_manning(Ai_e, Pi_e, n, slope), Qi, 0.02))

        # 净空约束
        check(f"[{desc}] 净空%≥15", r['freeboard_pct_inc'] >= 15.0 - 0.1,
              f"fb%={r['freeboard_pct_inc']:.1f}")
        check(f"[{desc}] 净空高≥0.4", r['freeboard_hgt_inc'] >= 0.4 - 0.001)

        # A_total 验证 (满管面积)
        A_full, _, _, ok_f = calculate_horseshoe_std_elements(stype, rv, 2*rv - 1e-6)
        if ok_f:
            check(f"[{desc}] A_total≈满管A",
                  abs_eq(r['A_total'], A_full, 0.01),
                  f"A_total={r['A_total']:.4f},A_full={A_full:.4f}")

    # 手动半径
    print("  -- 手动半径 --")
    for rm in [2.0, 2.5, 3.0]:
        for stype in [1, 2]:
            r = quick_calculate_horseshoe_std(Q=5.0, n=0.014, slope_inv=3000,
                                              v_min=0.1, v_max=100.0,
                                              section_type=stype, manual_r=rm)
            if r['success']:
                check(f"手动r={rm} stype={stype} 匹配",
                      abs_eq(r['r'], rm, 0.001))
            else:
                warn(f"手动r={rm} stype={stype}", r['error_message'][:50])


# ============================================================
# 测试11: 加大流量比例查表
# ============================================================
def test_flow_increase():
    print("\n" + "="*60)
    print("测试11: 加大流量比例查表")
    print("="*60)

    # 规范表: Q<1→30%, 1≤Q<5→25%, 5≤Q<20→20%, 20≤Q<50→15%,
    #          50≤Q<100→10%, Q≥100→5%
    expected = [
        (0.1, 30.0), (0.5, 30.0), (0.99, 30.0),
        (1.0, 25.0), (3.0, 25.0), (4.99, 25.0),
        (5.0, 20.0), (10.0, 20.0), (19.99, 20.0),
        (20.0, 15.0), (35.0, 15.0), (49.99, 15.0),
        (50.0, 10.0), (75.0, 10.0), (99.99, 10.0),
        (100.0, 5.0), (200.0, 5.0), (300.0, 5.0), (500.0, 5.0),
    ]
    for Q, exp_pct in expected:
        pct = get_flow_increase_percent(Q)
        check(f"加大比例 Q={Q}", abs_eq(pct, exp_pct, 0.01),
              f"got={pct}%,expected={exp_pct}%")

    # 边界
    check("Q=0 → 0%", abs_eq(get_flow_increase_percent(0), 0.0, 0.01))
    check("Q<0 → 0%", abs_eq(get_flow_increase_percent(-1), 0.0, 0.01))


# ============================================================
# 测试12: 边界条件与异常输入
# ============================================================
def test_boundary_conditions():
    print("\n" + "="*60)
    print("测试12: 边界条件与异常输入")
    print("="*60)

    # 圆形: Q=0 → 失败
    r = quick_calculate_circular(Q=0, n=0.014, slope_inv=3000, v_min=0.5, v_max=3.0)
    check("圆形 Q=0 应失败", not r['success'])

    # 圆形: n=0 → 失败
    r = quick_calculate_circular(Q=5.0, n=0, slope_inv=3000, v_min=0.5, v_max=3.0)
    check("圆形 n=0 应失败", not r['success'])

    # 圆形: slope_inv=0 → 不应崩溃
    try:
        r = quick_calculate_circular(Q=5.0, n=0.014, slope_inv=0, v_min=0.5, v_max=3.0)
        check("圆形 slope_inv=0 不崩溃", not r['success'])
    except ZeroDivisionError:
        check("圆形 slope_inv=0 不应ZeroDivisionError", False, "抛出ZeroDivisionError")

    # 圆拱直墙: theta超出范围 → 失败
    r = quick_calculate_horseshoe(Q=5.0, n=0.014, slope_inv=3000, v_min=0.5, v_max=3.0, theta_deg=200)
    check("圆拱 θ=200 应失败", not r['success'])
    r = quick_calculate_horseshoe(Q=5.0, n=0.014, slope_inv=3000, v_min=0.5, v_max=3.0, theta_deg=80)
    check("圆拱 θ=80 应失败", not r['success'])

    # 圆拱直墙: Q=0 → 失败
    r = quick_calculate_horseshoe(Q=0, n=0.014, slope_inv=3000, v_min=0.5, v_max=3.0)
    check("圆拱 Q=0 应失败", not r['success'])

    # 马蹄形: section_type无效 → 失败
    r = quick_calculate_horseshoe_std(Q=5.0, n=0.014, slope_inv=3000, v_min=0.5, v_max=3.0,
                                      section_type=3)
    check("马蹄 type=3 应失败", not r['success'])

    # 马蹄形: Q=0 → 失败
    r = quick_calculate_horseshoe_std(Q=0, n=0.014, slope_inv=3000, v_min=0.5, v_max=3.0,
                                      section_type=1)
    check("马蹄 Q=0 应失败", not r['success'])

    # 基础几何：h=0 → 0
    check("calculate_circular_area h=0 → 0",
          calculate_circular_area(4.0, 0) == 0.0)
    check("calculate_circular_perimeter h=0 → 0",
          calculate_circular_perimeter(4.0, 0) == 0.0)
    check("calculate_horseshoe_area h=0 → 0",
          calculate_horseshoe_area(3.0, 4.0, math.radians(150), 0) == 0.0)
    A_std, _, _, ok_std = calculate_horseshoe_std_elements(1, 2.0, 0)
    check("calculate_horseshoe_std_elements h=0 ok", ok_std)
    check("calculate_horseshoe_std_elements h=0 A=0", abs_eq(A_std, 0.0, 1e-6))

    # calculate_horseshoe_std_elements: h > 2r → 失败
    _, _, _, ok_over = calculate_horseshoe_std_elements(1, 2.0, 5.0)
    check("马蹄h>2r 应返回 ok=False", not ok_over)


# ============================================================
# 测试13: calculate_horseshoe_outputs / calculate_horseshoe_std_outputs 字段独立验证
# ============================================================
def test_outputs_field_validation():
    print("\n" + "="*60)
    print("测试13: 圆拱/马蹄形 outputs 字段独立验证")
    print("="*60)

    # --- 圆拱直墙型 ---
    hs_cases = [
        (3.0, 4.5, 180, 2.0, 0.014, 1/2000),
        (4.0, 5.5, 150, 3.0, 0.016, 1/3000),
        (2.5, 3.5, 120, 1.5, 0.013, 1/2500),
        (5.0, 7.0, 150, 4.0, 0.020, 1/5000),
    ]
    for B, H, tdeg, h, n, slope in hs_cases:
        tr = math.radians(tdeg)
        o = calculate_horseshoe_outputs(B, H, tr, h, n, slope)
        Ae = _hs_area(B, H, tr, h); Pe = _hs_perim(B, H, tr, h)
        Re = Ae / Pe if Pe > 0 else 0
        Qe = _manning(Ae, Pe, n, slope)
        Ve = Qe / Ae if Ae > 0 else 0
        Ate = _hs_total_area(B, H, tr)
        fb_hgt_e = H - h
        fb_pct_e = (Ate - Ae) / Ate * 100 if Ate > 0 else 100

        check(f"圆拱outputs A B={B},θ={tdeg},h={h}", abs_eq(o['A'], Ae, 0.001))
        check(f"圆拱outputs P B={B},θ={tdeg},h={h}", abs_eq(o['P'], Pe, 0.001))
        check(f"圆拱outputs R_hyd B={B},θ={tdeg},h={h}", abs_eq(o['R_hyd'], Re, 0.001))
        check(f"圆拱outputs Q B={B},θ={tdeg},h={h}", rel_eq(o['Q'], Qe, 0.001))
        check(f"圆拱outputs V*A=Q B={B},θ={tdeg},h={h}",
              rel_eq(o['V'] * o['A'], o['Q'], 0.001))
        check(f"圆拱outputs A_total B={B},θ={tdeg}", abs_eq(o['A_total'], Ate, 0.001))
        check(f"圆拱outputs fb_hgt=H-h B={B},θ={tdeg},h={h}",
              abs_eq(o['freeboard_hgt'], fb_hgt_e, 1e-6))
        check(f"圆拱outputs fb_pct B={B},θ={tdeg},h={h}",
              abs_eq(o['freeboard_pct'], fb_pct_e, 0.001))

    # --- 马蹄形标准 ---
    shoe_cases = [
        (1, 2.0, 1.2, 0.014, 1/2000),
        (1, 3.0, 2.5, 0.016, 1/3000),
        (2, 2.0, 1.5, 0.014, 1/2000),
        (2, 3.0, 2.0, 0.016, 1/3000),
        (1, 1.5, 0.8, 0.013, 1/1500),
        (2, 2.5, 3.5, 0.015, 1/2500),
    ]
    for stype, r, h, n, slope in shoe_cases:
        label = "Ⅰ型" if stype == 1 else "Ⅱ型"
        o = calculate_horseshoe_std_outputs(stype, r, h, n, slope)
        Ae, _, Pe = _shoe_elems(stype, r, h)
        if Pe <= 0: continue
        Re = Ae / Pe
        Qe = _manning(Ae, Pe, n, slope)
        Ve = Qe / Ae if Ae > 0 else 0
        A_full_e, _, _, _ = calculate_horseshoe_std_elements(stype, r, 2*r - 1e-9)
        fb_hgt_e = 2*r - h
        fb_pct_e = (A_full_e - Ae) / A_full_e * 100 if A_full_e > 0 else 100

        check(f"马蹄{label}outputs A r={r},h={h}", abs_eq(o['A'], Ae, 0.001))
        check(f"马蹄{label}outputs P r={r},h={h}", abs_eq(o['P'], Pe, 0.001))
        check(f"马蹄{label}outputs R_hyd r={r},h={h}", abs_eq(o['R_hyd'], Re, 0.001))
        check(f"马蹄{label}outputs Q r={r},h={h}", rel_eq(o['Q'], Qe, 0.001))
        check(f"马蹄{label}outputs V*A=Q r={r},h={h}",
              rel_eq(o['V'] * o['A'], o['Q'], 0.001))
        check(f"马蹄{label}outputs fb_hgt=2r-h r={r},h={h}",
              abs_eq(o['freeboard_hgt'], fb_hgt_e, 1e-6))
        check(f"马蹄{label}outputs fb_pct r={r},h={h}",
              abs_eq(o['freeboard_pct'], fb_pct_e, 0.01))


# ============================================================
# 测试14: manual_increase_percent + manual_B 参数
# ============================================================
def test_manual_params():
    print("\n" + "="*60)
    print("测试14: manual_increase_percent 及 manual_B 参数")
    print("="*60)

    base = dict(n=0.014, slope_inv=3000, v_min=0.1, v_max=100.0)

    # 手动加大比例 - 圆形
    print("  -- 手动加大比例 (圆形) --")
    for inc_manual in [0, 10, 20, 30, 50]:
        r = quick_calculate_circular(Q=5.0, manual_increase_percent=inc_manual, **base)
        if r['success']:
            check(f"圆形 manual_inc={inc_manual}% 比例匹配",
                  abs_eq(r['increase_percent'], inc_manual, 0.01),
                  f"got={r['increase_percent']}")
            check(f"圆形 manual_inc={inc_manual}% Q_inc",
                  rel_eq(r['Q_increased'], 5.0 * (1 + inc_manual/100), 0.001))

    # 手动加大比例 - 圆拱直墙
    print("  -- 手动加大比例 (圆拱) --")
    for inc_manual in [0, 15, 25]:
        r = quick_calculate_horseshoe(Q=5.0, theta_deg=150,
                                      manual_increase_percent=inc_manual, **base)
        if r['success']:
            check(f"圆拱 manual_inc={inc_manual}% 比例匹配",
                  abs_eq(r['increase_percent'], inc_manual, 0.01))
            check(f"圆拱 manual_inc={inc_manual}% Q_inc",
                  rel_eq(r['Q_increased'], 5.0 * (1 + inc_manual/100), 0.001))

    # 手动加大比例 - 马蹄形
    print("  -- 手动加大比例 (马蹄形) --")
    for stype in [1, 2]:
        for inc_manual in [0, 20, 30]:
            r = quick_calculate_horseshoe_std(Q=5.0, section_type=stype,
                                              manual_increase_percent=inc_manual, **base)
            if r['success']:
                label = "Ⅰ型" if stype == 1 else "Ⅱ型"
                check(f"马蹄{label} manual_inc={inc_manual}% 比例匹配",
                      abs_eq(r['increase_percent'], inc_manual, 0.01))
                check(f"马蹄{label} manual_inc={inc_manual}% Q_inc",
                      rel_eq(r['Q_increased'], 5.0 * (1 + inc_manual/100), 0.001))

    # 手动底宽 manual_B - 圆拱直墙型
    print("  -- manual_B (圆拱直墙型) --")
    for B_manual in [3.0, 4.0, 5.0, 6.0]:
        r = quick_calculate_horseshoe(Q=10.0, n=0.016, slope_inv=3000,
                                      v_min=0.1, v_max=100.0,
                                      theta_deg=150, manual_B=B_manual)
        if r['success']:
            check(f"圆拱 manual_B={B_manual} 底宽匹配",
                  abs_eq(r['B'], B_manual, 0.001), f"got={r['B']}")
            check(f"圆拱 manual_B={B_manual} hd<H",
                  r['h_design'] < r['H_total'])
            # 流量反算
            tr = math.radians(r['theta_deg'])
            Ae = _hs_area(B_manual, r['H_total'], tr, r['h_design'])
            Pe = _hs_perim(B_manual, r['H_total'], tr, r['h_design'])
            Qm = _manning(Ae, Pe, 0.016, 1/3000)
            check(f"圆拱 manual_B={B_manual} 曼宁反算Q",
                  rel_eq(Qm, 10.0, 0.02), f"Q_man={Qm:.4f}")
        else:
            warn(f"圆拱 manual_B={B_manual}", r['error_message'][:50])


# ============================================================
# 测试15: h_design < h_increased / design_method / get_required_freeboard_height
# ============================================================
def test_consistency_and_misc():
    print("\n" + "="*60)
    print("测试15: 一致性检查 & 杂项")
    print("="*60)

    # --- get_required_freeboard_height ---
    print("  -- get_required_freeboard_height --")
    from 隧洞设计 import get_required_freeboard_height
    for H in [2.0, 3.0, 5.0, 10.0]:
        fb = get_required_freeboard_height(H)
        check(f"get_required_freeboard_height H={H}",
              abs_eq(fb, MIN_FREEBOARD_HGT_TUNNEL, 0.001),
              f"got={fb}, expected={MIN_FREEBOARD_HGT_TUNNEL}")

    # --- h_design < h_increased 一致性 ---
    print("  -- h_design < h_increased 一致性 --")
    cases_circ = [(5.0,0.014,3000,0.5,3.0),(10.0,0.016,4000,0.5,3.0),(2.0,0.013,2000,0.2,5.0)]
    for Q, n, si, vmin, vmax in cases_circ:
        r = quick_calculate_circular(Q=Q, n=n, slope_inv=si, v_min=vmin, v_max=vmax)
        if r['success']:
            check(f"圆形 hd<hinc Q={Q}",
                  r['h_design'] < r['h_increased'],
                  f"hd={r['h_design']:.4f}, hinc={r['h_increased']:.4f}")

    cases_hs = [(5.0,0.014,3000,0.5,3.0,150),(10.0,0.016,4000,0.5,3.0,150)]
    for Q, n, si, vmin, vmax, tdeg in cases_hs:
        r = quick_calculate_horseshoe(Q=Q, n=n, slope_inv=si, v_min=vmin, v_max=vmax, theta_deg=tdeg)
        if r['success']:
            check(f"圆拱 hd<hinc Q={Q}",
                  r['h_design'] < r['h_increased'],
                  f"hd={r['h_design']:.4f}, hinc={r['h_increased']:.4f}")

    cases_shoe = [(5.0,0.014,3000,0.5,3.0,1),(5.0,0.014,3000,0.5,3.0,2)]
    for Q, n, si, vmin, vmax, stype in cases_shoe:
        r = quick_calculate_horseshoe_std(Q=Q, n=n, slope_inv=si, v_min=vmin, v_max=vmax,
                                          section_type=stype)
        if r['success']:
            label = "Ⅰ型" if stype == 1 else "Ⅱ型"
            check(f"马蹄{label} hd<hinc Q={Q}",
                  r['h_design'] < r['h_increased'],
                  f"hd={r['h_design']:.4f}, hinc={r['h_increased']:.4f}")

    # --- design_method 非空 ---
    print("  -- design_method 字段非空 --")
    r_c = quick_calculate_circular(Q=5.0, n=0.014, slope_inv=3000, v_min=0.5, v_max=3.0)
    if r_c['success']:
        check("圆形 design_method非空", bool(r_c.get('design_method', '')))

    r_h = quick_calculate_horseshoe(Q=5.0, n=0.014, slope_inv=3000,
                                     v_min=0.5, v_max=3.0, theta_deg=150)
    if r_h['success']:
        check("圆拱 design_method非空", bool(r_h.get('design_method', '')))

    r_s = quick_calculate_horseshoe_std(Q=5.0, n=0.014, slope_inv=3000,
                                        v_min=0.5, v_max=3.0, section_type=1)
    if r_s['success']:
        check("马蹄Ⅰ型 design_method非空", bool(r_s.get('design_method', '')))

    # --- R_hyd_design = A_design / P_design ---
    print("  -- R_hyd_design = A/P 一致性 --")
    if r_c['success']:
        check("圆形 R_hyd=A/P",
              abs_eq(r_c['R_hyd_design'],
                     r_c['A_design'] / r_c['P_design'], 0.001))
    if r_h['success']:
        check("圆拱 R_hyd=A/P",
              abs_eq(r_h['R_hyd_design'],
                     r_h['A_design'] / r_h['P_design'], 0.001))
    if r_s['success']:
        check("马蹄Ⅰ型 R_hyd=A/P",
              abs_eq(r_s['R_hyd_design'],
                     r_s['A_design'] / r_s['P_design'], 0.001))

    # --- 加大工况 V_increased ≥ V_design (流量增大→流速增大) ---
    print("  -- V_increased ≥ V_design --")
    if r_c['success']:
        check("圆形 Vinc≥Vd", r_c['V_increased'] >= r_c['V_design'] - 0.001)
    if r_h['success']:
        check("圆拱 Vinc≥Vd", r_h['V_increased'] >= r_h['V_design'] - 0.001)
    if r_s['success']:
        check("马蹄Ⅰ型 Vinc≥Vd", r_s['V_increased'] >= r_s['V_design'] - 0.001)


# ============================================================
# 主程序
# ============================================================
def run_all():
    print("\n" + "#"*70)
    print("  隧洞设计计算内核 - 全面测试")
    print("#"*70)

    test_circular_geometry()
    test_circular_outputs()
    test_circular_solver()
    test_circular_design()
    test_horseshoe_geometry()
    test_horseshoe_solver()
    test_horseshoe_design()
    test_horseshoe_std_geometry()
    test_horseshoe_std_solver()
    test_horseshoe_std_design()
    test_flow_increase()
    test_boundary_conditions()
    test_outputs_field_validation()
    test_manual_params()
    test_consistency_and_misc()

    print("\n" + "="*70)
    print(f"  测试完成: {PASS_COUNT} 通过, {FAIL_COUNT} 失败, {WARN_COUNT} 警告")
    print("="*70)
    if ERRORS:
        print("\n失败列表:")
        for e in ERRORS:
            print(f"  {e}")
    if WARNINGS:
        print("\n警告列表:")
        for w in WARNINGS:
            print(f"  {w}")
    return FAIL_COUNT == 0


if __name__ == '__main__':
    ok = run_all()
    sys.exit(0 if ok else 1)
