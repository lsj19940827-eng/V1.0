# -*- coding: utf-8 -*-
"""
算法对比测试：v4.0（现有 SpatialMerger）vs v5.0（严格数学版，内联实现）

不修改主体代码。v5.0 算法完整内联于本文件。

五组算例：
  C1. 水平直线            — 两版应完全一致（基线验证）
  C2. 均匀纵坡直线        — 两版应完全一致（带β基线）
  C3. 平面圆弧 + 恒坡     — R_eff 略有差异（β小时接近）
  C4. 纯竖曲线（含中间插值点）— 空间长度差异：v4.0割线，v5.0 R_v·|Δβ|
  C5. 复合弯道（平面弧+竖曲线完全重叠）— R_eff 差异最显著

运行：python tests/test_algorithm_comparison.py
"""

import sys, os, math, unittest

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, '倒虹吸水力计算系统'))

from siphon_models import PlanFeaturePoint, LongitudinalNode, TurnType
from spatial_merger import SpatialMerger   # v4.0

# ==============================================================================
# v5.0 内联实现（严格数学版各节公式）
# ==============================================================================

class _PS:  # PlanSegment
    def __init__(self, t, s0, s1, **kw):
        self.t = t        # 'L'(LINE) / 'A'(ARC)
        self.s0 = s0; self.s1 = s1
        self.p0  = kw.get('p0', (0.,0.))
        self.dir = kw.get('dir',(1.,0.))
        self.cen = kw.get('cen',(0.,0.))
        self.Rh  = kw.get('Rh', 0.)
        self.eps = kw.get('eps', 1)     # +1=CCW(左转),-1=CW(右转)
        self.th0 = kw.get('th0', 0.)   # BC点极角

class _VS:  # ProfileSegment
    def __init__(self, t, s0, s1, **kw):
        self.t  = t   # 'L'(LINE) / 'A'(ARC)
        self.s0 = s0; self.s1 = s1
        self.z0 = kw.get('z0', 0.)
        self.k  = kw.get('k',  0.)     # dz/ds
        self.Rv = kw.get('Rv', 0.)
        self.Sc = kw.get('Sc', 0.)
        self.Zc = kw.get('Zc', 0.)
        self.eta= kw.get('eta', 1)     # ±1

def _n2(dx, dy):
    d = math.hypot(dx, dy)
    return (dx/d, dy/d) if d > 1e-12 else (1., 0.)

def _na(a):
    while a >  math.pi: a -= 2*math.pi
    while a <= -math.pi: a += 2*math.pi
    return a

# §4 — 平面分段构建
def build_plan_segs(pps):
    n = len(pps)
    if n < 2: return []

    arcs = {}
    for i in range(1, n-1):
        pp = pps[i]
        if pp.turn_type != TurnType.ARC or pp.turn_radius <= 0 or pp.turn_angle < 0.1:
            continue
        din  = _n2(pp.x - pps[i-1].x, pp.y - pps[i-1].y)
        dout = _n2(pps[i+1].x - pp.x,  pps[i+1].y - pp.y)
        left = din[0]*dout[1] - din[1]*dout[0] > 0
        eps  = 1 if left else -1
        Rh   = pp.turn_radius
        ar   = math.radians(pp.turn_angle)
        T    = Rh * math.tan(ar/2)
        Lh   = Rh * ar
        bc   = (pp.x - T*din[0],  pp.y - T*din[1])
        ec   = (pp.x + T*dout[0], pp.y + T*dout[1])
        nin  = (-din[1], din[0]) if left else (din[1], -din[0])
        cen  = (bc[0]+Rh*nin[0], bc[1]+Rh*nin[1])
        bc_s = pp.chainage - Lh/2
        ec_s = pp.chainage + Lh/2
        th0  = math.atan2(bc[1]-cen[1], bc[0]-cen[0])
        arcs[i] = dict(bc=bc,ec=ec,bc_s=bc_s,ec_s=ec_s,cen=cen,Rh=Rh,eps=eps,th0=th0)

    evts = [(pps[0].chainage,(pps[0].x,pps[0].y),'P',-1)]
    for i,g in arcs.items():
        evts += [(g['bc_s'],g['bc'],'B',i),(g['ec_s'],g['ec'],'E',i)]
    evts.append((pps[-1].chainage,(pps[-1].x,pps[-1].y),'P',-1))
    evts.sort(key=lambda e:e[0])

    segs=[]; ps=evts[0][0]; pxy=evts[0][1]; ia=None
    for s,xy,k,idx in evts[1:]:
        if k=='B':
            if s>ps+1e-6:
                dx,dy=xy[0]-pxy[0],xy[1]-pxy[1]
                segs.append(_PS('L',ps,s,p0=pxy,dir=_n2(dx,dy)))
            ps,pxy,ia=s,xy,idx
        elif k=='E' and ia==idx:
            g=arcs[idx]
            segs.append(_PS('A',g['bc_s'],g['ec_s'],cen=g['cen'],Rh=g['Rh'],eps=g['eps'],th0=g['th0']))
            ps,pxy,ia=s,xy,None
        elif k=='P' and ia is None and s>ps+1e-6:
            dx,dy=xy[0]-pxy[0],xy[1]-pxy[1]
            segs.append(_PS('L',ps,s,p0=pxy,dir=_n2(dx,dy)))
            ps,pxy=s,xy
    return segs

# §5 — 纵断面分段构建
def build_prof_segs(lns):
    n=len(lns)
    if n<2: return []
    segs=[]; ps=lns[0].chainage; pz=lns[0].elevation; i=0
    while i<n:
        ln=lns[i]
        ok=(ln.turn_type==TurnType.ARC and ln.arc_end_chainage is not None
            and ln.arc_center_s is not None and ln.arc_center_z is not None
            and ln.vertical_curve_radius>0)
        if ok:
            if ln.chainage>ps+1e-6:
                ds=ln.chainage-ps
                segs.append(_VS('L',ps,ln.chainage,z0=pz,k=(ln.elevation-pz)/ds))
            Sc,Zc,Rv=ln.arc_center_s,ln.arc_center_z,ln.vertical_curve_radius
            sq=math.sqrt(max(0.,Rv**2-(ln.chainage-Sc)**2))
            eta=1 if abs(Zc+sq-ln.elevation)<=abs(Zc-sq-ln.elevation) else -1
            ae=ln.arc_end_chainage
            segs.append(_VS('A',ln.chainage,ae,Rv=Rv,Sc=Sc,Zc=Zc,eta=eta))
            sq_e=math.sqrt(max(0.,Rv**2-(ae-Sc)**2))
            pz=Zc+eta*sq_e; ps=ae
            j=i+1
            while j<n and lns[j].chainage<ae-1e-3: j+=1
            if j<n and abs(lns[j].chainage-ae)<0.1: pz=lns[j].elevation; i=j
            else: i=j
            continue
        i+=1
    last=lns[-1]
    if last.chainage>ps+1e-6:
        ds=last.chainage-ps
        segs.append(_VS('L',ps,last.chainage,z0=pz,k=(last.elevation-pz)/ds))
    return segs

# §4.3 / §5.2 — 解析求值
def _fseg(segs,s,side):
    idx=0
    for k,sg in enumerate(segs):
        if sg.s0<=s+1e-9 and s<=sg.s1+1e-9: idx=k; break
    else:
        idx=0 if s<segs[0].s0 else len(segs)-1
    if side=='L' and idx>0 and abs(s-segs[idx].s0)<1e-9: idx-=1
    elif side=='R' and idx<len(segs)-1 and abs(s-segs[idx].s1)<1e-9: idx+=1
    return segs[idx]

def ep(ps,s,side='M'):  # eval_plan → (x,y,α)
    if not ps: return (s,0.,0.)
    sg=_fseg(ps,s,side)
    if sg.t=='L':
        ds=s-sg.s0
        return sg.p0[0]+ds*sg.dir[0], sg.p0[1]+ds*sg.dir[1], math.atan2(sg.dir[1],sg.dir[0])
    th=sg.th0+sg.eps*(s-sg.s0)/sg.Rh
    return sg.cen[0]+sg.Rh*math.cos(th), sg.cen[1]+sg.Rh*math.sin(th), _na(th+sg.eps*math.pi/2)

def ev(vs,s,side='M'):  # eval_profile → (z,β)
    if not vs: return (0.,0.)
    sg=_fseg(vs,s,side)
    if sg.t=='L':
        return sg.z0+sg.k*(s-sg.s0), math.atan(sg.k)
    ins=max(0.,sg.Rv**2-(s-sg.Sc)**2)
    z=sg.Zc+sg.eta*math.sqrt(ins)
    dz=-(s-sg.Sc)/(z-sg.Zc) if abs(z-sg.Zc)>1e-12 else 0.
    return z, math.atan(dz)   # §5.2: atan (not atan2)

# §6.2 — 三维单位切向量
def T3(a,b): cb=math.cos(b); return (cb*math.cos(a),cb*math.sin(a),math.sin(b))
def d3(a,b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]

# §9 — 空间长度解析积分
def _sl(sg,sa,sb):
    a,b=max(sg.s0,sa),min(sg.s1,sb)
    if b<=a+1e-12: return 0.
    if sg.t=='L': return (b-a)*math.sqrt(1+sg.k**2)   # §9.1
    _,ba=ev([sg],a); _,bb=ev([sg],b)
    return sg.Rv*abs(bb-ba)   # §9.2: R_v·|Δβ|

def slen(vs,sa,sb): return sum(_sl(sg,sa,sb) for sg in vs)

# §10-§11 — 弯道事件分析
def bends_v5(ps,vs):
    res=[]
    s_min=ps[0].s0 if ps else (vs[0].s0 if vs else 0)
    s_max=ps[-1].s1 if ps else (vs[-1].s1 if vs else 0)
    # 平面 ARC 弯道事件
    for sg in ps:
        if sg.t!='A': continue
        _,_,aa=ep(ps,sg.s0,'R'); _,_,ab=ep(ps,sg.s1,'L')
        _,ba=ev(vs,sg.s0);       _,bb=ev(vs,sg.s1)
        Ta=T3(aa,ba); Tb=T3(ab,bb)
        dot=max(-1.,min(1.,d3(Ta,Tb)))
        th=math.acos(dot)
        L=slen(vs,sg.s0,sg.s1) if vs else (sg.s1-sg.s0)
        Reff=L/th if th>1e-9 else float('inf')
        res.append(dict(kind='PLAN_ARC',sa=sg.s0,sb=sg.s1,Rh=sg.Rh,Rv=0.,
                        theta=math.degrees(th),L=L,Reff=Reff))
    # 纵断 ARC 弯道事件
    for sg in vs:
        if sg.t!='A': continue
        _,_,aa=ep(ps,sg.s0) if ps else (0,0,0)
        _,_,ab=ep(ps,sg.s1) if ps else (0,0,0)
        _,ba=ev(vs,sg.s0,'R'); _,bb=ev(vs,sg.s1,'L')
        Ta=T3(aa,ba); Tb=T3(ab,bb)
        dot=max(-1.,min(1.,d3(Ta,Tb)))
        th=math.acos(dot)
        L=slen(vs,sg.s0,sg.s1)
        Reff=L/th if th>1e-9 else float('inf')
        res.append(dict(kind='VERT_ARC',sa=sg.s0,sb=sg.s1,Rh=0.,Rv=sg.Rv,
                        theta=math.degrees(th),L=L,Reff=Reff))
    return res


# ==============================================================================
# 运行两版算法
# ==============================================================================

def run_v5(plan_pts, long_ns):
    """完整运行 v5.0，返回 {L, bends}"""
    ps = build_plan_segs(plan_pts)
    vs = build_prof_segs(long_ns)
    if not ps and not vs:
        return dict(L=0., bends=[])
    s0 = ps[0].s0 if ps else vs[0].s0
    s1 = ps[-1].s1 if ps else vs[-1].s1
    L  = slen(vs, s0, s1) if vs else (s1 - s0)
    return dict(L=L, bends=bends_v5(ps, vs), ps=ps, vs=vs)


def run_v4(plan_pts, long_ns):
    """调用现有 SpatialMerger（v4.0），提取对比指标"""
    r = SpatialMerger.merge_and_compute(plan_pts, long_ns, verbose=False)
    bends = []
    for nd in r.nodes:
        if nd.has_turn and nd.spatial_turn_angle > 0.1:
            kind = ('PLAN_ARC' if (nd.has_plan_turn and not nd.has_long_turn) else
                    'VERT_ARC' if (nd.has_long_turn and not nd.has_plan_turn) else
                    'COMPOSITE')
            bends.append(dict(kind=kind, sa=nd.chainage, sb=nd.chainage,
                               Rh=nd.plan_turn_radius, Rv=nd.long_turn_radius,
                               theta=nd.spatial_turn_angle, L=None,
                               Reff=nd.effective_radius))
    return dict(L=r.total_spatial_length, bends=bends)


# ==============================================================================
# 打印对比表
# ==============================================================================

def _fmt_bend(b, ver):
    sa = f"[{b['sa']:.1f},{b['sb']:.1f}]" if ver == 'v5' else f"{b['sa']:.1f}"
    L  = f"{b['L']:.3f}m" if b['L'] is not None else "N/A"
    return (f"  {ver} {b['kind']:<10} s={sa:<18} "
            f"θ={b['theta']:7.3f}°  R_eff={b['Reff']:>9.2f}m"
            + (f"  L_event={L}" if ver == 'v5' else ""))


def print_cmp(label, r4, r5):
    print(f"\n{'='*68}")
    print(f"  {label}")
    print(f"{'='*68}")
    dL = r5['L'] - r4['L']
    pct = dL / r4['L'] * 100 if r4['L'] > 1e-3 else 0.
    print(f"  空间总长 L:  v4.0={r4['L']:.4f}m   v5.0={r5['L']:.4f}m   "
          f"Δ={dL:+.4f}m ({pct:+.4f}%)")
    if not r4['bends'] and not r5['bends']:
        print("  弯道：无")
        return
    print("  弯道：")
    for b in r4['bends']:
        print(_fmt_bend(b, 'v4'))
    for b in r5['bends']:
        print(_fmt_bend(b, 'v5'))
    # 逐对差值
    for b4, b5 in zip(r4['bends'], r5['bends']):
        dt = b5['theta'] - b4['theta']
        dR = b5['Reff'] - b4['Reff']
        ratio = b5['Reff']/b4['Reff'] if b4['Reff'] > 1e-3 else float('nan')
        print(f"  ▶ 对比差：Δθ={dt:+.4f}°  ΔR_eff={dR:+.2f}m"
              + (f"  (比值={ratio:.4f})" if not math.isnan(ratio) else ""))


# ==============================================================================
# 五组算例构造
# ==============================================================================

def _pp(s, x, y, az=90., tt=TurnType.NONE, angle=0., radius=0.):
    return PlanFeaturePoint(chainage=s, x=x, y=y, azimuth_meas_deg=az,
                             turn_angle=angle, turn_radius=radius, turn_type=tt)

def _ln(s, z, tt=TurnType.NONE, sb=0., sa=0.,
        Rv=0., ac_s=None, ac_z=None, ae=None, atr=None, ta=0.):
    return LongitudinalNode(chainage=s, elevation=z, turn_type=tt,
                             slope_before=sb, slope_after=sa,
                             vertical_curve_radius=Rv, turn_angle=ta,
                             arc_center_s=ac_s, arc_center_z=ac_z,
                             arc_end_chainage=ae, arc_theta_rad=atr)


def case1_horizontal_straight():
    """C1: 水平直线（基线）"""
    pps = [_pp(0,0,0), _pp(200,200,0)]
    lns = [_ln(0,100.), _ln(200,100.)]
    return "C1: 水平直线（无弯无坡）", pps, lns


def case2_sloped_straight():
    """C2: 均匀纵坡直线（β=10°）"""
    b = math.radians(10.)
    dz = 200.*math.tan(b)
    pps = [_pp(0,0,0), _pp(200,200,0)]
    lns = [_ln(0,100.,sa=b), _ln(200,100.+dz,sb=b)]
    return "C2: 纵坡直线（β=10°，无弯）", pps, lns


def case3_plan_arc_const_slope():
    """C3: 平面圆弧（R=500,α=30°）+ 恒定纵坡（k=0.05）"""
    Rh = 500.; alpha = 30.; k = 0.05
    ar = math.radians(alpha)
    Lh = Rh * ar
    dout = (math.cos(ar), math.sin(ar))
    ip2  = (500.+500.*dout[0], 500.*dout[1])
    ch2  = 500.+500.
    pps = [_pp(0,0,0), _pp(500,500,0,angle=alpha,radius=Rh,tt=TurnType.ARC),
           _pp(ch2,ip2[0],ip2[1])]
    z0=100.; z2=z0+k*ch2
    b=math.atan(k)
    lns = [_ln(0,z0,sa=b), _ln(ch2,z2,sb=b)]
    return f"C3: 平面弧(R={Rh},α={alpha}°)+恒坡(k={k})", pps, lns


def case4_vert_curve_with_midpoint():
    """C4: 纯竖曲线（含弧中点节点，强制v4.0用割线近似）"""
    Rv=500.; th_deg=30.; th_rad=math.radians(th_deg)
    bb=-math.radians(15.); ba=math.radians(15.)   # 谷底弧：β: -15°→+15°
    arc_s=100.
    arc_e=arc_s + Rv*2*math.sin(th_rad/2)   # = 100 + 500*2*sin(15°) ≈ 358.83
    s_end=arc_e+100.

    # 弧心（谷底弧，圆心在弧上方）
    Sc = arc_s - Rv*math.sin(bb)   # sin(-15°)<0 → Sc > arc_s
    Z_start=50.
    Zc = Z_start + Rv*math.cos(bb)
    Z_end = Zc - Rv*math.cos(ba)
    Z_mid = Zc - Rv                # 弧谷底最低点（t=0）
    s_mid = Sc                     # 谷底桩号

    Z0    = Z_start + (arc_s-0.)*math.tan(bb)
    Z_fin = Z_end   + (s_end-arc_e)*math.tan(ba)

    pps = [_pp(0.,0.,0.), _pp(s_end,s_end,0.)]
    lns = [
        _ln(0.,    Z0,      sa=bb),
        _ln(arc_s, Z_start, TurnType.ARC, sb=bb, sa=ba, Rv=Rv,
            ac_s=Sc, ac_z=Zc, ae=arc_e, atr=th_rad, ta=th_deg),
        _ln(s_mid, Z_mid),           # 弧中间点 → 迫使v4.0分割成两段割线
        _ln(arc_e, Z_end,   sb=ba, sa=ba),
        _ln(s_end, Z_fin,   sb=ba),
    ]
    return (f"C4: 纯竖曲线(R={Rv},θ={th_deg}°,含弧中点→v4.0割线近似)",
            pps, lns)


def case5_composite():
    """C5: 复合弯道（平面弧[bc≈413,ec≈587] 与竖曲线[420,580] 完全重叠）"""
    Rh=500.; alpha_h=20.; ar_h=math.radians(alpha_h)
    Lh=Rh*ar_h; qz_s=500.
    bc_s=qz_s-Lh/2; ec_s=qz_s+Lh/2   # ≈412.7 / 587.3

    dout=(math.cos(ar_h), math.sin(ar_h))
    ip2=(500.+600.*dout[0], 600.*dout[1])
    pps=[_pp(0.,0.,0.), _pp(qz_s,500.,0.,angle=alpha_h,radius=Rh,tt=TurnType.ARC),
         _pp(1100.,ip2[0],ip2[1])]

    Rv=800.; th_v=math.radians(15.); bb_v=-math.radians(5.); ba_v=math.radians(10.)
    arc_s=420.; arc_e=580.
    Sc_v=arc_s - Rv*math.sin(bb_v)
    Z_s=50.; Zc_v=Z_s + Rv*math.cos(bb_v)
    Z_e=Zc_v - Rv*math.cos(ba_v)
    Z0=Z_s  + (arc_s-0.)*math.tan(bb_v)
    Zf=Z_e  + (1100.-arc_e)*math.tan(ba_v)

    lns=[
        _ln(0.,   Z0,  sa=bb_v),
        _ln(arc_s,Z_s, TurnType.ARC, sb=bb_v, sa=ba_v, Rv=Rv,
            ac_s=Sc_v, ac_z=Zc_v, ae=arc_e, atr=th_v, ta=math.degrees(th_v)),
        _ln(arc_e,Z_e, sb=ba_v, sa=ba_v),
        _ln(1100.,Zf,  sb=ba_v),
    ]
    return (f"C5: 复合弯道(平面弧R={Rh}α={alpha_h}° / 竖曲线R={Rv}θ=15°)",
            pps, lns)


# ==============================================================================
# unittest 测试类（带断言）
# ==============================================================================

class TestAlgorithmComparison(unittest.TestCase):

    def _cmp(self, label, pps, lns):
        r4 = run_v4(pps, lns)
        r5 = run_v5(pps, lns)
        print_cmp(label, r4, r5)
        return r4, r5

    def test_C1_horizontal_straight(self):
        label, pps, lns = case1_horizontal_straight()
        r4, r5 = self._cmp(label, pps, lns)
        self.assertAlmostEqual(r5['L'], 200., places=2)
        self.assertAlmostEqual(r4['L'], 200., places=2)
        self.assertFalse(r4['bends'])
        self.assertFalse(r5['bends'])

    def test_C2_sloped_straight(self):
        label, pps, lns = case2_sloped_straight()
        r4, r5 = self._cmp(label, pps, lns)
        dz = 200.*math.tan(math.radians(10.))
        exp = math.sqrt(200.**2 + dz**2)
        self.assertAlmostEqual(r5['L'], exp, places=2)
        self.assertAlmostEqual(r4['L'], exp, places=2)

    def test_C3_plan_arc_const_slope(self):
        label, pps, lns = case3_plan_arc_const_slope()
        r4, r5 = self._cmp(label, pps, lns)
        self.assertTrue(len(r5['bends']) >= 1)

    def test_C4_vert_curve_midpoint(self):
        """v5.0 精确弧长应 ≥ v4.0 割线近似"""
        label, pps, lns = case4_vert_curve_with_midpoint()
        r4, r5 = self._cmp(label, pps, lns)
        # 弧长 ≥ 弦长（严格数学定理）
        self.assertGreaterEqual(r5['L'], r4['L'] - 0.01,
                                "v5.0 空间长度应≥v4.0割线近似（弧长≥弦长）")
        # 两版应检测到竖向弯道
        self.assertTrue(any(b['kind']=='VERT_ARC' for b in r5['bends']),
                        "v5.0 应检测到竖向弯道事件")

    def test_C5_composite(self):
        """复合弯道：两版R_eff应都合理且差异可见"""
        label, pps, lns = case5_composite()
        r4, r5 = self._cmp(label, pps, lns)
        self.assertTrue(len(r4['bends']) >= 1, "v4.0 应检测到弯道")
        self.assertTrue(len(r5['bends']) >= 1, "v5.0 应检测到弯道")
        for b in r4['bends']:
            self.assertGreater(b['Reff'], 0.)
        for b in r5['bends']:
            self.assertGreater(b['Reff'], 0.)


# ==============================================================================
# 直接运行时输出完整对比报告
# ==============================================================================

if __name__ == '__main__':
    print("\n" + "▓"*68)
    print("  空间轴线算法对比报告：v4.0（现有） vs v5.0（严格数学版内联）")
    print("▓"*68)

    for label, pps, lns in [
        case1_horizontal_straight(),
        case2_sloped_straight(),
        case3_plan_arc_const_slope(),
        case4_vert_curve_with_midpoint(),
        case5_composite(),
    ]:
        r4 = run_v4(pps, lns)
        r5 = run_v5(pps, lns)
        print_cmp(label, r4, r5)

    print("\n" + "▓"*68)
    print("  完成。差值 = v5.0 重写后的精度改进量。")
    print("▓"*68)
