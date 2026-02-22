# -*- coding: utf-8 -*-
"""渡槽计算核心公式精细数学验证"""
import sys, math, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'C:\Users\大渔\Desktop\V1.0')
from 渠系建筑物断面计算.渡槽设计 import (
    calculate_u_hydro_elements, calculate_u_total_area,
    calculate_rect_hydro_elements_with_chamfer,
    quick_calculate_u, quick_calculate_rect, get_flow_increase_percent,
)
PI = math.pi
PASS=0; FAIL=0; WARN=0
def ok(name, cond, detail=""):
    global PASS,FAIL
    if cond: PASS+=1; print(f"  [OK]   {name}")
    else:    FAIL+=1; print(f"  [FAIL] {name} | {detail}")
def warn(msg): global WARN; WARN+=1; print(f"  [WARN] {msg}")
def close(a,b,tol=1e-5):
    if abs(b)<1e-12: return abs(a)<tol
    return abs(a-b)/abs(b)<tol

# ── 1. U形面积：数值积分对比 ──────────────────────────────────────────────────
print("\n=== [1] U形面积公式（h<=R）数值积分验证 ===")
def u_area_integral(h, R, N=500000):
    """数值积分 ∫₀ʰ 2√(2Ry-y²) dy"""
    if h<=0: return 0.0
    h=min(h,R); dy=h/N; s=0.0
    for k in range(N):
        y=(k+0.5)*dy; v=2*R*y-y*y
        if v>=0: s+=2*math.sqrt(v)*dy
    return s

R=2.0
for frac in [0.05,0.1,0.3,0.5,0.7,0.9,1.0]:
    h=frac*R
    A_num=u_area_integral(h,R)
    A_code,_=calculate_u_hydro_elements(h,R,f=0.0)
    ok(f"U面积 h/R={frac}", close(A_code,A_num,1e-4),
       f"code={A_code:.6f} num={A_num:.6f} diff={abs(A_code-A_num):.2e}")

print("\n=== [2] U形湿周（h<=R）===")
R=2.0
for frac in [0.1,0.3,0.5,0.7,0.9,1.0]:
    h=frac*R
    angle=math.acos(max(-1,min(1,1-h/R)))
    P_exp=2*R*angle
    _,P_code=calculate_u_hydro_elements(h,R,f=0.0)
    ok(f"U湿周 h/R={frac}", close(P_code,P_exp),
       f"code={P_code:.6f} exp={P_exp:.6f}")

print("\n=== [3] U形面积在h=R处连续性 ===")
R,f=1.0,0.5; eps=1e-7
A_lo,_=calculate_u_hydro_elements(R-eps,R,f)
A_hi,_=calculate_u_hydro_elements(R+eps,R,f)
ok("h=R处面积连续",abs(A_hi-A_lo)<1e-4,f"lo={A_lo:.8f} hi={A_hi:.8f}")
A_at,_=calculate_u_hydro_elements(R,R,f)
ok("h=R: A=piR^2/2", close(A_at, PI*R**2/2), f"code={A_at:.8f} exp={PI*R**2/2:.8f}")

print("\n=== [4] U形 h>R：直段+半圆 ===")
R,f=1.5,0.8
for hs in [0.1,0.4,0.8]:
    h=R+hs
    A_e=PI*R**2/2+2*R*hs; P_e=PI*R+2*hs
    A_c,P_c=calculate_u_hydro_elements(h,R,f)
    ok(f"h=R+{hs} 面积", close(A_c,A_e), f"code={A_c:.5f} exp={A_e:.5f}")
    ok(f"h=R+{hs} 湿周", close(P_c,P_e), f"code={P_c:.5f} exp={P_e:.5f}")

# ── 2. 带倒角矩形公式验证 ────────────────────────────────────────────────────
print("\n=== [5] 带倒角矩形 h>=ch：面积与湿周 ===")
# 推导（h>=ch）：
#   A = B*h - cl*ch    （切去2个三角形，各面积=cl*ch/2）
#   P = (B+2h) - 2*(cl+ch) + 2*hyp
for B,h,ca,cl in [(3.0,1.5,45,0.1),(2.0,2.0,30,0.15),(4.0,1.0,60,0.05),(5.0,3.0,45,0.2)]:
    ca_r=math.radians(ca); ch=cl*math.tan(ca_r); hyp=cl/math.cos(ca_r)
    if h<ch: continue
    A_e=B*h-cl*ch; P_e=(B+2*h)-2*(cl+ch)+2*hyp
    A_c,P_c=calculate_rect_hydro_elements_with_chamfer(h,B,ca,cl)
    ok(f"倒角面积 B={B},h={h},ca={ca},cl={cl}", close(A_c,A_e),
       f"code={A_c:.6f} exp={A_e:.6f}")
    ok(f"倒角湿周 B={B},h={h},ca={ca},cl={cl}", close(P_c,P_e),
       f"code={P_c:.6f} exp={P_e:.6f}")

print("\n=== [6] 带倒角矩形 h<ch 公式缺陷分析（BUG检测）===")
# 当 h < chamfer_height 时，代码返回 A=B*h, P=B+2h（普通矩形公式）
# 实际几何：底角三角形切入，底部宽度为 B-2*cl，向上逐渐扩展至 B
# 正确面积：A_real = B*h - 2*cl*h*(1 - h/(2*ch)) = B*h - 2*cl*h + cl*h^2/ch
# 正确湿周：P_real = (B-2*cl) + 2*(h/ch)*hyp  （底部有效宽 + 两侧倒角面长度）
print("  倒角几何分析：当 h < chamfer_height 时")
for ca,cl in [(45,0.1),(30,0.15),(60,0.05)]:
    ca_r=math.radians(ca); ch=cl*math.tan(ca_r); hyp=cl/math.cos(ca_r)
    B=3.0; h=ch*0.5  # 水深=倒角高的一半
    # 代码值
    A_code,P_code=calculate_rect_hydro_elements_with_chamfer(h,B,ca,cl)
    # 正确值
    A_real=B*h - 2*cl*h + cl*h**2/ch   # 积分 ∫₀ʰ (B-2*cl*(1-y/ch)) dy
    P_real=(B-2*cl) + 2*(h/ch)*hyp     # 底部有效宽 + 2段倒角面弧长
    err_A=abs(A_code-A_real)/max(A_real,1e-9)
    err_P=abs(P_code-P_real)/max(P_real,1e-9)
    print(f"  ca={ca}, cl={cl}, ch={ch:.4f}, h={h:.4f}")
    print(f"    A: code={A_code:.6f}  real={A_real:.6f}  relErr={err_A:.1%}")
    print(f"    P: code={P_code:.6f}  real={P_real:.6f}  relErr={err_P:.1%}")
    if err_A > 0.01 or err_P > 0.01:
        warn(f"h<ch 时公式误差显著: ca={ca}, h/ch=0.5, A误差={err_A:.1%}, P误差={err_P:.1%}")
    else:
        print("    误差在可接受范围")

# ── 3. 倒角湿周公式解剖：P = (B+2h) - 2*(cl+ch) + 2*hyp 正确性 ────────────
print("\n=== [7] 倒角湿周公式几何推导验证 ===")
# 原矩形湿周 B+2h 由：底 B + 两侧各 h
# 倒角后各角：去掉底面 cl + 侧面 ch，换成斜面 hyp
# => P = B + 2h - 2*(cl+ch) + 2*hyp  ✓
# 验证特殊案例：ca=45, cl=0.1, h=1.0, B=2.0
B,h,ca,cl=2.0,1.0,45,0.1
ca_r=math.radians(ca); ch=cl*math.tan(ca_r); hyp=cl/math.cos(ca_r)
# 几何直接计算：底 (B-2cl) + 2*(h-ch) 侧面 + 2*hyp 斜面
P_geom=(B-2*cl)+2*(h-ch)+2*hyp
P_formula=(B+2*h)-2*(cl+ch)+2*hyp
ok("两种表达等价", close(P_geom,P_formula), f"geom={P_geom:.6f} formula={P_formula:.6f}")
A_c,P_c=calculate_rect_hydro_elements_with_chamfer(h,B,ca,cl)
ok("代码与几何一致", close(P_c,P_geom), f"code={P_c:.6f} geom={P_geom:.6f}")

# ── 4. 超高规则验证 ─────────────────────────────────────────────────────────
print("\n=== [8] U形超高规则（规范9.4.1-2）===")
# 规范：设计流量时超高 >= 2R/10 = R/5；加大流量时超高 >= 0.10m
for Q,n,sinv in [(2.0,0.014,2000),(5.0,0.014,3000),(10.0,0.014,5000),(20.0,0.013,8000)]:
    r=quick_calculate_u(Q,n,sinv,0.1,100.0)
    if not r['success']: print(f"  NOTE Q={Q}: {r['error_message'][:50]}"); continue
    R=r['R']; H=r['H_total']; h_d=r['h_design']; h_i=r['h_increased']
    Fb_des=H-h_d; Fb_inc=H-h_i
    ok(f"U Q={Q} 设计超高 {Fb_des:.4f} >= R/5={R/5:.4f}",
       Fb_des>=R/5-1e-6, f"Fb_des={Fb_des:.4f}")
    ok(f"U Q={Q} 加大超高 {Fb_inc:.4f} >= 0.10",
       Fb_inc>=0.10-1e-6, f"Fb_inc={Fb_inc:.4f}")

print("\n=== [9] 矩形超高规则（规范9.4.1-2）===")
# 规范：设计流量时超高 >= h/12+0.05m；加大流量时超高 >= 0.10m
for Q,n,sinv in [(2.0,0.014,2000),(5.0,0.014,3000),(10.0,0.014,5000),(20.0,0.013,8000)]:
    r=quick_calculate_rect(Q,n,sinv,0.1,100.0)
    if not r['success']: print(f"  NOTE Q={Q}: {r['error_message'][:50]}"); continue
    H=r['H_total']; h_d=r['h_design']; h_i=r['h_increased']
    Fb_des=H-h_d; Fb_inc=H-h_i; Fb_min=h_d/12+0.05
    ok(f"矩形 Q={Q} 设计超高 {Fb_des:.4f} >= h/12+0.05={Fb_min:.4f}",
       Fb_des>=Fb_min-1e-6)
    ok(f"矩形 Q={Q} 加大超高 {Fb_inc:.4f} >= 0.10",
       Fb_inc>=0.10-1e-6)

# ── 5. Manning方程：Q_calc与Q的自洽性（各参数组合） ──────────────────────────
print("\n=== [10] Manning方程自洽性精细验证 ===")
# 对计算出的断面，手动验算 Q = (1/n)*A*Rh^(2/3)*i^(1/2)
for Q,n,sinv in [(0.5,0.012,500),(1.0,0.014,1000),(5.0,0.014,3000),
                 (10.0,0.015,5000),(50.0,0.013,10000),(100.0,0.013,15000)]:
    i=1/sinv
    # U形
    ru=quick_calculate_u(Q,n,sinv,0.1,100.0)
    if ru['success']:
        A=ru['A_design']; P=ru['P_design']; Rh=A/P if P>0 else 0
        Q_manual=A*(1/n)*(Rh**(2/3))*(i**0.5) if Rh>0 else 0
        err=abs(Q_manual-Q)/Q
        ok(f"U Manning Q={Q}: 误差{err:.4%}", err<0.001, f"Qm={Q_manual:.4f}")
    # 矩形
    rr=quick_calculate_rect(Q,n,sinv,0.1,100.0)
    if rr['success']:
        A=rr['A_design']; P=rr['P_design']; Rh=A/P if P>0 else 0
        Q_manual=A*(1/n)*(Rh**(2/3))*(i**0.5) if Rh>0 else 0
        err=abs(Q_manual-Q)/Q
        ok(f"矩形 Manning Q={Q}: 误差{err:.4%}", err<0.001, f"Qm={Q_manual:.4f}")

# ── 6. 加大流量百分比分档验证（对照规范常用值）──────────────────────────────
print("\n=== [11] 加大流量百分比分档验证 ===")
# 验证边界值处于正确分档
boundaries = [
    (0.99,  30.0, "Q<1→30%"),
    (1.0,   25.0, "1<=Q<5→25%"),
    (4.99,  25.0, "Q=4.99→25%"),
    (5.0,   20.0, "5<=Q<20→20%"),
    (19.99, 20.0, "Q=19.99→20%"),
    (20.0,  15.0, "20<=Q<50→15%"),
    (49.99, 15.0, "Q=49.99→15%"),
    (50.0,  10.0, "50<=Q<100→10%"),
    (99.99, 10.0, "Q=99.99→10%"),
    (100.0,  5.0, "100<=Q<=300→5%"),
    (300.0,  5.0, "Q=300→5%"),
    (500.0,  5.0, "Q>300→5%"),
]
for Q,exp,desc in boundaries:
    got=get_flow_increase_percent(Q)
    ok(f"{desc}", abs(got-exp)<0.01, f"got={got}, exp={exp}")

# ── 7. 关键几何数值精度验证 ──────────────────────────────────────────────────
print("\n=== [12] 角度计算精度（防止 acos 域错误）===")
# cos_val 应严格在[-1,1]，边界情况
R=1.0
# h=0
cos0=max(-1,min(1,1-0/R))
ok("h=0: acos(1)=0", close(math.acos(cos0),0.0))
# h=R
cosR=max(-1,min(1,1-R/R))
ok("h=R: acos(0)=pi/2", close(math.acos(cosR),PI/2))
# 超出应被 clamp
cos_clamp=max(-1,min(1,1-1.0001))  # 1 - 1.0001 = -0.0001 → 正常
ok("超出范围被clamp到[-1,1]", -1<=cos_clamp<=1)

# ── 8. 总面积函数（calculate_u_total_area）与水力要素面积一致性 ─────────────
print("\n=== [13] U形总面积 vs 水力要素面积（h=H_total时一致）===")
for R,f in [(1.0,0.4),(1.5,0.6),(2.0,0.8)]:
    H=f+R
    A_hydro,_=calculate_u_hydro_elements(H,R,f)
    A_total=calculate_u_total_area(H,R)
    ok(f"R={R},f={f}: 总面积与水力要素面积一致",
       close(A_hydro,A_total,1e-8),
       f"hydro={A_hydro:.8f} total={A_total:.8f}")

# ── 9. 搜索逻辑：H/B约束 vs f/R约束的关系 ──────────────────────────────────
print("\n=== [14] H/B约束与f/R约束的数学等价性 ===")
# H/B = H_total/(2R) = (f+R)/(2R) = 0.5 + f/(2R) = 0.5 + fR/2
# fR in [0.4, 0.6] => H/B in [0.5+0.2, 0.5+0.3] = [0.7, 0.8]
# 规范 HB_MIN=0.7, HB_MAX=0.9
# 因此 f/R=FR_MAX=0.6 时 H/B=0.8 < HB_MAX=0.9，约束永远可满足
FR_MIN=0.4; FR_MAX=0.6; HB_MIN=0.7; HB_MAX=0.9
HB_at_FR_MIN=0.5+FR_MIN/2; HB_at_FR_MAX=0.5+FR_MAX/2
ok("f/R=0.4时 H/B=0.7 >= HB_MIN=0.7", close(HB_at_FR_MIN,0.7))
ok("f/R=0.6时 H/B=0.8 <= HB_MAX=0.9", HB_at_FR_MAX<=HB_MAX)
ok("f/R范围内H/B始终满足约束", HB_MIN<=HB_at_FR_MIN and HB_at_FR_MAX<=HB_MAX)

# ── 10. 倒角参数：chamfer_angle含义验证 ──────────────────────────────────────
print("\n=== [15] 倒角斜面长 hyp = cl/cos(ca) 验证（直角三角形） ===")
for ca_deg,cl in [(45,0.1),(30,0.15),(60,0.05)]:
    ca=math.radians(ca_deg)
    ch=cl*math.tan(ca); hyp=cl/math.cos(ca)
    # 勾股定理验证
    ok(f"ca={ca_deg}: hyp^2=cl^2+ch^2",
       close(hyp**2, cl**2+ch**2),
       f"hyp^2={hyp**2:.8f} cl^2+ch^2={cl**2+ch**2:.8f}")

# ── 汇总 ─────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"验证完成: 通过 {PASS}, 失败 {FAIL}, 警告 {WARN}")
print(f"{'='*60}")
