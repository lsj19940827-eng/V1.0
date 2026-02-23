# -*- coding: utf-8 -*-
"""
最优断面批量搜索：Q=0.10~2.00 m3/s，步长0.01，9种结构形式，生成matplotlib对比图。
运行: cd V1.0项目根目录  &&  python tools/optimal_section_sweep.py
"""
import sys, math
import numpy as np
import matplotlib, matplotlib.pyplot as plt, matplotlib.ticker as ticker

matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

sys.path.insert(0, r'C:\Users\大渔\Desktop\V1.0')

from 渠系建筑物断面计算.明渠设计 import (
    quick_calculate_trapezoidal, quick_calculate_rectangular,
    quick_calculate_circular as oc_circular,
)
from 渠系建筑物断面计算.渡槽设计 import quick_calculate_u, quick_calculate_rect as aq_rect
from 渠系建筑物断面计算.矩形暗涵设计 import quick_calculate_rectangular_culvert
import 渠系建筑物断面计算.隧洞设计 as tunnel

Q_LIST = [round(0.10 + i * 0.01, 2) for i in range(191)]

# 典型参数
P_OC  = dict(n=0.015, slope_inv=3000, v_min=0.3, v_max=2.5)   # 明渠梯形/矩形
P_OCC = dict(n=0.015, slope_inv=3000, v_min=0.5, v_max=3.0)   # 圆形明渠
P_AQ  = dict(n=0.014, slope_inv=3000, v_min=1.0, v_max=2.5)   # 渡槽
P_CU  = dict(n=0.014, slope_inv=2000, v_min=0.5, v_max=3.0)   # 暗涵/隧洞
M_TRAP = 1.0

STYLE = {
    '梯形明渠':   dict(c='#2196F3', ls='-',  lw=2.0),
    '矩形明渠':   dict(c='#03A9F4', ls='--', lw=1.8),
    '圆形明渠':   dict(c='#00BCD4', ls=':',  lw=1.8),
    'U形渡槽':    dict(c='#4CAF50', ls='-',  lw=2.0),
    '矩形渡槽':   dict(c='#8BC34A', ls='--', lw=1.8),
    '矩形暗涵':   dict(c='#FF9800', ls='-',  lw=2.0),
    '隧洞圆形':   dict(c='#F44336', ls='-',  lw=2.0),
    '马蹄形Ⅰ型': dict(c='#E91E63', ls='--', lw=1.8),
    '圆拱直墙型': dict(c='#9C27B0', ls=':',  lw=1.8),
}

def _trap_area(b, hp, m):
    return (b + m * hp) * hp if b and hp else None

def run_sweep():
    data = {k: [] for k in STYLE}
    total = len(Q_LIST)
    for idx, Q in enumerate(Q_LIST):
        if idx % 30 == 0:
            print(f"  {idx+1}/{total}  Q={Q:.2f}")

        # 1 梯形明渠
        try:
            r = quick_calculate_trapezoidal(Q, M_TRAP, P_OC['n'], P_OC['slope_inv'], P_OC['v_min'], P_OC['v_max'])
            if r.get('success'):
                b, hp = r['b_design'], r['h_prime']
                data['梯形明渠'].append({'Q':Q,'dim':b,'dim_label':'b(m)','h':r['h_design'],'V':r['V_design'],'A':_trap_area(b,hp,M_TRAP)})
            else:
                data['梯形明渠'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})
        except:
            data['梯形明渠'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})

        # 2 矩形明渠
        try:
            r = quick_calculate_rectangular(Q, P_OC['n'], P_OC['slope_inv'], P_OC['v_min'], P_OC['v_max'])
            if r.get('success'):
                b, hp = r['b_design'], r['h_prime']
                data['矩形明渠'].append({'Q':Q,'dim':b,'dim_label':'b(m)','h':r['h_design'],'V':r['V_design'],'A':_trap_area(b,hp,0.0)})
            else:
                data['矩形明渠'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})
        except:
            data['矩形明渠'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})

        # 3 圆形明渠
        try:
            r = oc_circular(Q, P_OCC['n'], P_OCC['slope_inv'], P_OCC['v_min'], P_OCC['v_max'])
            if r.get('success') and r.get('check_passed'):
                D = r.get('D_design')
                data['圆形明渠'].append({'Q':Q,'dim':D,'dim_label':'D(m)','h':r.get('y_d'),'V':r.get('V_d'),'A':r.get('section_total_area')})
            else:
                data['圆形明渠'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})
        except:
            data['圆形明渠'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})

        # 4 U形渡槽
        try:
            r = quick_calculate_u(Q, P_AQ['n'], P_AQ['slope_inv'], P_AQ['v_min'], P_AQ['v_max'])
            if r.get('success'):
                data['U形渡槽'].append({'Q':Q,'dim':r['R'],'dim_label':'R(m)','h':r['h_design'],'V':r['V_design'],'A':r['A_total']})
            else:
                data['U形渡槽'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})
        except:
            data['U形渡槽'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})

        # 5 矩形渡槽
        try:
            r = aq_rect(Q, P_AQ['n'], P_AQ['slope_inv'], P_AQ['v_min'], P_AQ['v_max'])
            if r.get('success'):
                data['矩形渡槽'].append({'Q':Q,'dim':r['B'],'dim_label':'B(m)','h':r['h_design'],'V':r['V_design'],'A':r['A_total']})
            else:
                data['矩形渡槽'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})
        except:
            data['矩形渡槽'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})

        # 6 矩形暗涵
        try:
            r = quick_calculate_rectangular_culvert(Q, P_CU['n'], P_CU['slope_inv'], P_CU['v_min'], P_CU['v_max'])
            if r.get('success'):
                data['矩形暗涵'].append({'Q':Q,'dim':r['B'],'dim_label':'B(m)','h':r['h_design'],'V':r['V_design'],'A':r['A_total']})
            else:
                data['矩形暗涵'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})
        except:
            data['矩形暗涵'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})

        # 7 隧洞圆形
        try:
            r = tunnel.quick_calculate_circular(Q, P_CU['n'], P_CU['slope_inv'], P_CU['v_min'], P_CU['v_max'])
            if r.get('success'):
                D = r['D']
                data['隧洞圆形'].append({'Q':Q,'dim':D,'dim_label':'D(m)','h':r['h_design'],'V':r['V_design'],'A':math.pi*D*D/4})
            else:
                data['隧洞圆形'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})
        except:
            data['隧洞圆形'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})

        # 8 马蹄形Ⅰ型
        try:
            r = tunnel.quick_calculate_horseshoe_std(Q, P_CU['n'], P_CU['slope_inv'], P_CU['v_min'], P_CU['v_max'], section_type=1)
            if r.get('success'):
                data['马蹄形Ⅰ型'].append({'Q':Q,'dim':r['r'],'dim_label':'r(m)','h':r['h_design'],'V':r['V_design'],'A':r['A_total']})
            else:
                data['马蹄形Ⅰ型'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})
        except:
            data['马蹄形Ⅰ型'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})

        # 9 圆拱直墙型 θ=120°
        try:
            r = tunnel.quick_calculate_horseshoe(Q, P_CU['n'], P_CU['slope_inv'], P_CU['v_min'], P_CU['v_max'], theta_deg=120.0)
            if r.get('success'):
                data['圆拱直墙型'].append({'Q':Q,'dim':r['B'],'dim_label':'B(m)','h':r['h_design'],'V':r['V_design'],'A':r['A_total']})
            else:
                data['圆拱直墙型'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})
        except:
            data['圆拱直墙型'].append({'Q':Q,'dim':None,'h':None,'V':None,'A':None})

    return data

def _arr(records, key):
    return np.array([float(r[key]) if r.get(key) is not None else float('nan') for r in records])

def _plot_lines(ax, data, Q_arr, key):
    for name, st in STYLE.items():
        y = _arr(data[name], key); mask = ~np.isnan(y)
        if mask.any():
            ax.plot(Q_arr[mask], y[mask], label=name, color=st['c'], ls=st['ls'], lw=st['lw'])

def _fmt(ax):
    ax.legend(loc='upper left', fontsize=8, ncol=2)
    ax.grid(True, alpha=0.35)
    ax.xaxis.set_minor_locator(ticker.MultipleLocator(0.1))
    ax.grid(which='minor', alpha=0.12)

def plot_results(data):
    Q_arr = np.array(Q_LIST)
    figs = []

    # 图1 断面总面积
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_title('Q vs 断面总面积 A_total  (各结构最优断面)', fontsize=13, fontweight='bold')
    ax.set_xlabel('设计流量 Q (m3/s)', fontsize=11); ax.set_ylabel('断面总面积 A_total (m2)', fontsize=11)
    _plot_lines(ax, data, Q_arr, 'A'); _fmt(ax); fig.tight_layout(); figs.append(('图1_断面总面积', fig))

    # 图2 设计流速
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_title('Q vs 设计流速 V  (各结构最优断面)', fontsize=13, fontweight='bold')
    ax.set_xlabel('设计流量 Q (m3/s)', fontsize=11); ax.set_ylabel('设计流速 V (m/s)', fontsize=11)
    _plot_lines(ax, data, Q_arr, 'V'); _fmt(ax); fig.tight_layout(); figs.append(('图2_设计流速', fig))

    # 图3 关键尺寸
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_title('Q vs 关键控制尺寸  (底宽/直径/半径)', fontsize=13, fontweight='bold')
    ax.set_xlabel('设计流量 Q (m3/s)', fontsize=11); ax.set_ylabel('尺寸 (m)', fontsize=11)
    for name, st in STYLE.items():
        y = _arr(data[name], 'dim'); mask = ~np.isnan(y)
        lbl0 = data[name][0].get('dim_label','?') if data[name] else '?'
        if mask.any():
            ax.plot(Q_arr[mask], y[mask], label=f"{name}({lbl0})", color=st['c'], ls=st['ls'], lw=st['lw'])
    _fmt(ax); fig.tight_layout(); figs.append(('图3_关键尺寸', fig))

    # 图4 设计水深
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_title('Q vs 设计水深 h  (各结构最优断面)', fontsize=13, fontweight='bold')
    ax.set_xlabel('设计流量 Q (m3/s)', fontsize=11); ax.set_ylabel('设计水深 h (m)', fontsize=11)
    _plot_lines(ax, data, Q_arr, 'h'); _fmt(ax); fig.tight_layout(); figs.append(('图4_设计水深', fig))

    # 图5 分组断面面积
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle('各结构分组断面面积对比  (Q vs A_total)', fontsize=13, fontweight='bold')
    groups = [
        ('明渠', ['梯形明渠','矩形明渠','圆形明渠']),
        ('渡槽', ['U形渡槽','矩形渡槽']),
        ('暗涵/隧洞', ['矩形暗涵','隧洞圆形','马蹄形Ⅰ型','圆拱直墙型']),
    ]
    for ax, (gname, names) in zip(axes, groups):
        ax.set_title(gname, fontsize=11); ax.set_xlabel('Q (m3/s)', fontsize=9); ax.set_ylabel('A_total (m2)', fontsize=9)
        for name in names:
            st = STYLE[name]; y = _arr(data[name], 'A'); mask = ~np.isnan(y)
            if mask.any():
                ax.plot(Q_arr[mask], y[mask], label=name, color=st['c'], ls=st['ls'], lw=st['lw'])
        ax.legend(fontsize=8); ax.grid(True, alpha=0.35)
    fig.tight_layout(); figs.append(('图5_分组面积对比', fig))

    return figs

def print_summary(data):
    print('\n' + '='*72)
    print('  有效计算点数（共191点）')
    print('='*72)
    for name, records in data.items():
        ok = sum(1 for r in records if r.get('A') is not None)
        print(f"  {name:<12s}  {ok:3d}/191")

    print('\n' + '='*72)
    print('  Q=1.00 m³/s 各结构断面对比')
    print('='*72)
    print(f"  {'结构':<12s}  {'尺寸':>12s}  {'h(m)':>8s}  {'V(m/s)':>8s}  {'A_total(m²)':>11s}")
    print('  '+'-'*58)
    idx = Q_LIST.index(1.00)
    for name, records in data.items():
        rec = records[idx]
        lbl = rec.get('dim_label','?'); d = rec.get('dim'); h = rec.get('h'); V = rec.get('V'); A = rec.get('A')
        ds = f"{lbl}={d:.3f}" if d else '—'
        hs = f"{h:.3f}" if h else '—'; Vs = f"{V:.3f}" if V else '—'; As = f"{A:.3f}" if A else '—'
        print(f"  {name:<12s}  {ds:>12s}  {hs:>8s}  {Vs:>8s}  {As:>11s}")
    print('='*72)

def main():
    print('='*72)
    print('  最优断面批量搜索  Q=0.10~2.00 m³/s  步长0.01  共191点')
    print('='*72)
    data = run_sweep()
    print_summary(data)
    print('\n生成图表中…')
    figs = plot_results(data)
    save_dir = r'C:\Users\大渔\Desktop\V1.0\tools'
    for title, fig in figs:
        path = f"{save_dir}\\最优断面_{title}.png"
        fig.savefig(path, dpi=150, bbox_inches='tight')
        print(f"  已保存: {path}")
    print('\n完成！正在打开图表…')
    plt.show()

if __name__ == '__main__':
    main()
