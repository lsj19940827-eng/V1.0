# -*- coding: utf-8 -*-
"""渡槽设计计算核心综合测试脚本"""
import sys, math, traceback, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'C:\Users\大渔\Desktop\V1.0')

from calc_渠系计算算法内核.渡槽设计 import (
    calculate_u_hydro_elements, calculate_u_total_area,
    calculate_u_water_depth, calculate_rect_hydro_elements,
    calculate_rect_hydro_elements_with_chamfer, calculate_rect_water_depth,
    quick_calculate_u, quick_calculate_rect, get_flow_increase_percent,
)

PI = math.pi
PASS = 0; FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  [OK]   {name}")
    else:    FAIL += 1; print(f"  [FAIL] {name}  | {detail}")

def close(a, b, tol=1e-4):
    if abs(b) < 1e-12: return abs(a) < tol
    return abs(a - b) / abs(b) < tol

# ─── 1. U形水力要素 ───────────────────────────────────────────────────────────
print("\n=== [1] U形断面水力要素 ===")
R, f = 1.0, 0.5
A, P = calculate_u_hydro_elements(1.0, R, f)
check("h=R: A=piR^2/2", close(A, PI/2), f"A={A:.6f}")
check("h=R: P=πR",    close(P, PI),   f"P={P:.6f}")
A, P = calculate_u_hydro_elements(1.5, R, f)
check("h>R: A正确", close(A, PI/2+1.0), f"A={A:.6f}")
check("h>R: P正确", close(P, PI+1.0),   f"P={P:.6f}")
A0, P0 = calculate_u_hydro_elements(0, 1.0, 0.5)
check("h=0 返回(0,0)", A0==0 and P0==0)

# ─── 2. U形总面积 ────────────────────────────────────────────────────────────
print("\n=== [2] U形总面积 ===")
check("h=R: 总面积=piR^2/2", close(calculate_u_total_area(1.0, 1.0), PI/2))
check("h=R+0.5: 总面积",   close(calculate_u_total_area(1.5, 1.0), PI/2+1.0))

# ─── 3. U形反算水深一致性 ───────────────────────────────────────────────────
print("\n=== [3] U形反算水深一致性 ===")
for Q, n, sinv, R, f in [(5.0,0.014,3000,1.46,0.87),(2.0,0.013,2000,1.0,0.4),
                          (10.0,0.015,5000,2.0,0.8),(0.5,0.012,1000,0.5,0.2),
                          (50.0,0.014,8000,5.0,2.0)]:
    i = 1/sinv
    h = calculate_u_water_depth(Q, R, n, i, f)
    if h <= 0: check(f"Q={Q}: h>0", False, f"h={h}"); continue
    A, P = calculate_u_hydro_elements(h, R, f)
    Rh = A/P; Q2 = A*(1/n)*(Rh**(2/3))*(i**0.5)
    check(f"Q={Q} 反算误差<0.1%", abs(Q2-Q)/Q < 0.001, f"Q2={Q2:.4f}")

# ─── 4. 矩形水力要素 ──────────────────────────────────────────────────────────
print("\n=== [4] 矩形水力要素 ===")
for B, h in [(2.0,1.0),(3.5,2.0),(5.0,3.0)]:
    A, P = calculate_rect_hydro_elements(h, B)
    check(f"B={B},h={h}: A=Bh", close(A, B*h))
    check(f"B={B},h={h}: P=B+2h", close(P, B+2*h))

# ─── 5. 带倒角矩形 ────────────────────────────────────────────────────────────
print("\n=== [5] 带倒角矩形 ===")
B, h, ca, cl = 2.0, 1.5, 45.0, 0.1
ch = cl*math.tan(math.radians(ca)); ca_area=0.5*cl*ch; ch_hyp=cl/math.cos(math.radians(ca))
A_exp = B*h - 2*ca_area
P_exp = B+2*h - 2*(cl+ch) + 2*ch_hyp
A, P = calculate_rect_hydro_elements_with_chamfer(h, B, ca, cl)
check("带倒角面积", close(A, A_exp), f"A={A:.6f},exp={A_exp:.6f}")
check("带倒角湿周", close(P, P_exp), f"P={P:.6f},exp={P_exp:.6f}")

# ─── 6. 矩形反算水深一致性 ──────────────────────────────────────────────────
print("\n=== [6] 矩形反算水深一致性 ===")
for Q, n, sinv, B in [(5.0,0.014,3000,3.0),(2.0,0.013,2000,2.0),
                       (10.0,0.015,5000,4.0),(0.5,0.012,1000,1.0),(20.0,0.014,6000,5.0)]:
    i = 1/sinv
    h = calculate_rect_water_depth(Q, B, n, i)
    if h<=0: check(f"矩形Q={Q}: h>0", False, f"h={h}"); continue
    A, P = calculate_rect_hydro_elements(h, B)
    Rh=A/P; Q2=A*(1/n)*(Rh**(2/3))*(i**0.5)
    check(f"矩形Q={Q} 误差<0.1%", abs(Q2-Q)/Q < 0.001, f"Q2={Q2:.4f}")

# ─── 7. quick_calculate_u 大量参数 ───────────────────────────────────────────
print("\n=== [7] quick_calculate_u 综合 ===")
u_cases = [
    (1.0,0.014,1000,0.1,100,"小流量1000"),
    (2.0,0.014,2000,0.1,100,"小流量2000"),
    (5.0,0.014,3000,0.1,100,"中流量3000"),
    (10.0,0.014,5000,0.1,100,"大流量5000"),
    (20.0,0.014,8000,0.1,100,"大流量8000"),
    (50.0,0.013,10000,0.1,100,"大流量10k"),
    (100.0,0.013,15000,0.1,100,"超大流量"),
    (0.5,0.012,500,0.1,100,"极小流量"),
    (5.0,0.016,3000,0.1,100,"大糙率"),
    (5.0,0.011,3000,0.1,100,"小糙率"),
    (5.0,0.014,500,0.1,100,"大坡度500"),
    (5.0,0.014,10000,0.1,100,"小坡度10k"),
]
for Q, n, sinv, vmin, vmax, desc in u_cases:
    try: r = quick_calculate_u(Q, n, sinv, vmin, vmax)
    except Exception as e: check(f"U[{desc}]无崩溃", False, str(e)); continue
    if not r['success']: print(f"    NOTE U[{desc}]: {r['error_message'][:70]}"); continue
    R=r['R']; f=r['f']; H=r['H_total']; h_d=r['h_design']; h_i=r['h_increased']
    Q_c=r['Q_calc']; i=1/sinv
    check(f"U[{desc}] B=2R",           close(r['B'], 2*R, 1e-5))
    check(f"U[{desc}] Q_calc≈Q",       abs(Q_c-Q)/Q < 0.001, f"Qc={Q_c:.4f}")
    check(f"U[{desc}] h_d<H",          h_d < H, f"h_d={h_d:.3f},H={H:.3f}")
    check(f"U[{desc}] 加大超高≥0.10",  H-h_i >= 0.10-1e-6, f"Fb={H-h_i:.4f}")
    check(f"U[{desc}] 设计超高≥R/5",   H-h_d >= R/5-1e-6,  f"Fb={H-h_d:.4f},R/5={R/5:.4f}")
    check(f"U[{desc}] h_i>h_d",        h_i > h_d)
    A_m,P_m = calculate_u_hydro_elements(h_d,R,f)
    if P_m>0:
        Rh_m=A_m/P_m; Q_m=A_m*(1/n)*(Rh_m**(2/3))*(i**0.5)
        check(f"U[{desc}] 手动验算Q", abs(Q_m-Q)/Q<0.001, f"Qm={Q_m:.4f}")

# ─── 8. quick_calculate_u 手动指定R ─────────────────────────────────────────
print("\n=== [8] quick_calculate_u 手动指定R ===")
for Q, n, sinv, manual_R, desc in [
    (5.0,0.014,3000,1.46,"标准R"),
    (5.0,0.014,3000,2.0,"偏大R"),
    (10.0,0.014,5000,2.5,"大Q大R"),
]:
    try: r = quick_calculate_u(Q, n, sinv, 0.1, 100, manual_R=manual_R)
    except Exception as e: check(f"U手动R[{desc}]无崩溃", False, str(e)); continue
    if not r['success']: print(f"    NOTE U手动R[{desc}]: {r['error_message'][:70]}"); continue
    H=r['H_total']; h_d=r['h_design']; h_i=r['h_increased']; R_r=r['R']
    check(f"U手动R[{desc}] R保持", close(R_r, manual_R, 1e-4), f"R={R_r}")
    check(f"U手动R[{desc}] 加大超高≥0.10", H-h_i>=0.10-1e-6, f"{H-h_i:.4f}")
    check(f"U手动R[{desc}] 设计超高≥R/5",  H-h_d>=R_r/5-1e-6, f"{H-h_d:.4f}")

# ─── 9. quick_calculate_rect 综合 ────────────────────────────────────────────
print("\n=== [9] quick_calculate_rect 综合 ===")
rect_cases = [
    (1.0,0.014,1000,0.8,"小流量"),
    (5.0,0.014,3000,0.8,"中流量dwr0.8"),
    (5.0,0.014,3000,0.6,"中流量dwr0.6"),
    (5.0,0.014,3000,1.0,"中流量dwr1.0"),
    (10.0,0.014,5000,0.8,"大流量"),
    (20.0,0.014,8000,0.8,"更大流量"),
    (50.0,0.013,10000,0.8,"超大流量"),
    (100.0,0.013,15000,0.8,"超大流量2"),
    (0.5,0.012,500,0.8,"极小流量"),
    (5.0,0.016,3000,0.8,"大糙率"),
    (5.0,0.011,3000,0.8,"小糙率"),
]
for Q, n, sinv, dwr, desc in rect_cases:
    try: r = quick_calculate_rect(Q, n, sinv, 0.1, 100, depth_width_ratio=dwr)
    except Exception as e: check(f"矩形[{desc}]无崩溃", False, str(e)); continue
    if not r['success']: print(f"    NOTE 矩形[{desc}]: {r['error_message'][:70]}"); continue
    B=r['B']; H=r['H_total']; h_d=r['h_design']; h_i=r['h_increased']
    Q_c=r['Q_calc']; i=1/sinv
    check(f"矩形[{desc}] Q_calc≈Q", abs(Q_c-Q)/Q<0.001, f"Qc={Q_c:.4f}")
    check(f"矩形[{desc}] h_d<H",    h_d<H)
    check(f"矩形[{desc}] 加大超高≥0.10", H-h_i>=0.10-1e-6, f"{H-h_i:.4f}")
    Fb_min=h_d/12+0.05
    check(f"矩形[{desc}] 设计超高≥h/12+0.05", H-h_d>=Fb_min-1e-6, f"{H-h_d:.4f},min={Fb_min:.4f}")
    check(f"矩形[{desc}] h_i>h_d",  h_i>h_d)
    check(f"矩形[{desc}] 深宽比H/B≤dwr+0.02", H/B<=dwr+0.02, f"H/B={H/B:.3f}")
    A_m,P_m=calculate_rect_hydro_elements(h_d,B)
    Rh_m=A_m/P_m; Q_m=A_m*(1/n)*(Rh_m**(2/3))*(i**0.5)
    check(f"矩形[{desc}] 手动验算Q", abs(Q_m-Q)/Q<0.001, f"Qm={Q_m:.4f}")

# ─── 10. quick_calculate_rect 手动指定B ──────────────────────────────────────
print("\n=== [10] quick_calculate_rect 手动指定B ===")
for Q, n, sinv, mB, desc in [
    (5.0,0.014,3000,3.0,"标准B"),
    (5.0,0.014,3000,2.0,"偏小B"),
    (5.0,0.014,3000,5.0,"偏大B"),
    (10.0,0.014,5000,4.0,"大Q大B"),
]:
    try: r = quick_calculate_rect(Q, n, sinv, 0.1, 100, manual_B=mB)
    except Exception as e: check(f"矩形手动B[{desc}]无崩溃", False, str(e)); continue
    if not r['success']: print(f"    NOTE 矩形手动B[{desc}]: {r['error_message'][:70]}"); continue
    B=r['B']; H=r['H_total']; h_d=r['h_design']; h_i=r['h_increased']
    check(f"矩形手动B[{desc}] B保持", close(B,mB,1e-4))
    check(f"矩形手动B[{desc}] 加大超高≥0.10", H-h_i>=0.10-1e-6, f"{H-h_i:.4f}")
    Fb_min=h_d/12+0.05
    check(f"矩形手动B[{desc}] 设计超高≥h/12+0.05", H-h_d>=Fb_min-1e-6, f"{H-h_d:.4f}")

# ─── 11. 加大流量百分比 ──────────────────────────────────────────────────────
print("\n=== [11] 加大流量百分比规则 ===")
for Q, exp in [(0.5,30),(3.0,25),(5.0,20),(10.0,20),(20.0,15),
               (50.0,10),(100.0,5),(300.0,5),(500.0,5)]:
    check(f"Q={Q}→{exp}%", close(get_flow_increase_percent(Q),exp))

# ─── 12. 边界/异常输入 ───────────────────────────────────────────────────────
print("\n=== [12] 边界与异常输入 ===")
check("U Q=0 → error",         not quick_calculate_u(0,0.014,3000,0.1,100)['success'])
check("U n=0 → error",         not quick_calculate_u(5,0,3000,0.1,100)['success'])
check("U slope=0 → error",     not quick_calculate_u(5,0.014,0,0.1,100)['success'])
check("U vmin>=vmax → error",  not quick_calculate_u(5,0.014,3000,5.0,3.0)['success'])
check("矩形 Q=0 → error",      not quick_calculate_rect(0,0.014,3000,0.1,100)['success'])
check("矩形 n=0 → error",      not quick_calculate_rect(5,0,3000,0.1,100)['success'])
check("矩形 slope=0 → error",  not quick_calculate_rect(5,0.014,0,0.1,100)['success'])

# ─── 13. 加大流量工况水深一定大于设计水深 ───────────────────────────────────
print("\n=== [13] h_increased > h_design (多参数) ===")
for Q in [0.5,1,2,5,10,20,50]:
    r = quick_calculate_u(Q,0.014,3000,0.1,100)
    if r['success']:
        check(f"U Q={Q}: h_inc>h_des", r['h_increased']>r['h_design'])
    r2 = quick_calculate_rect(Q,0.014,3000,0.1,100)
    if r2['success']:
        check(f"矩形 Q={Q}: h_inc>h_des", r2['h_increased']>r2['h_design'])

# ─── 14. 带倒角矩形主计算 ────────────────────────────────────────────────────
print("\n=== [14] 带倒角矩形主计算 ===")
r = quick_calculate_rect(5.0,0.014,3000,0.1,100,
                          depth_width_ratio=0.8,
                          chamfer_angle=45.0, chamfer_length=0.1)
if r['success']:
    H=r['H_total']; h_d=r['h_design']; h_i=r['h_increased']
    check("带倒角 加大超高≥0.10", H-h_i>=0.10-1e-6, f"{H-h_i:.4f}")
    check("带倒角 设计超高≥h/12+0.05", H-h_d>=h_d/12+0.05-1e-6)
    check("带倒角 h_inc>h_des", h_i>h_d)
else:
    print(f"    NOTE 带倒角: {r['error_message'][:70]}")

# ─── 汇总 ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"测试完成: 通过 {PASS}, 失败 {FAIL}, 合计 {PASS+FAIL}")
print(f"{'='*60}")
