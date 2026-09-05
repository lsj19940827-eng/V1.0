# -*- coding: utf-8 -*-
"""将钢管水力反算及外径上取快照渲染为界面公式和Word可编辑公式。"""

from html import escape
from app_渠系计算前端.pressure_pipe.diameter_explanation import _formula_html


def steel_result_heading(result):
    """区分历史结果、指定尺寸、合格最小外径与未满足条件的参考尺寸。"""
    if not getattr(result.recommended, 'steel_sizing_trace', None):
        return '历史钢管尺寸（旧计算结果）'
    label = ('指定公称外径' if result.category == '指定' else
             '整百外径参考（未满足全部水力条件）' if result.category == '兜底' else
             '推荐最小公称外径')
    return label + '（构造最小壁厚）'


def sizing_explanation(candidate):
    """只读结果快照，分步解释流速、水损、补壁厚及公称外径上取。"""
    t = getattr(candidate, 'steel_sizing_trace', None)
    if not t:
        return []
    rows = [
        ('1. 按流速上限求内径下限（设计流量）',
         rf"d_v=1000\sqrt{{\frac{{4\times {t['design_q']:g}}}{{\pi\times {t['velocity_limit']:g}}}}}={t['velocity_min_inner_mm']:.4f}\,\mathrm{{mm}}",
         f"流速上限 {t['velocity_limit']:g} m/s，要求净内径至少 {t['velocity_min_inner_mm']:.4f} mm。"),
        ('2. 按总水损上限求内径下限（加大流量）',
         rf"d_h=\left[\frac{{{t['f']:g}\times 1000\times({t['increased_q']:g}\times 3600)^{{{t['m']:g}}}\times(1+{t['local_ratio']:g})}}{{{t['loss_limit']:g}}}\right]^{{1/{t['b']:g}}}={t['loss_min_inner_mm']:.4f}\,\mathrm{{mm}}",
         f"总水损上限 {t['loss_limit']:g} m/km；流量由立方米每秒乘3600换为立方米每小时，管长取1000 m，内径单位为mm。"),
        ('3. 取满足两项上限的最小净内径',
         rf"d_{{\min}}=\max({t['velocity_min_inner_mm']:.4f},{t['loss_min_inner_mm']:.4f})={t['required_hydraulic_inner_mm']:.4f}\,\mathrm{{mm}}",
         f"所需最小水力内径 {t['required_hydraulic_inner_mm']:.4f} mm。"),
    ]
    if 'recommended_outer_mm' not in t:
        return rows + [('自动上取结果', '', t.get('selection_error', '未得到可用外径'))]
    rows += [
        ('4. 补两侧内衬和构造最小壁厚，得到初算外径',
         rf"D_{{o,0}}={t['required_hydraulic_inner_mm']:.4f}+2\times {t['lining_mm']:g}+2\times {t['preliminary_wall_mm']:g}={t['theoretical_outer_mm']:.4f}\,\mathrm{{mm}}",
         f"按初算钢管内径 {t['required_steel_inner_mm']:.4f} mm，构造最小壁厚进位为 {t['preliminary_wall_mm']:g} mm。"),
        ('5. 公称外径按100 mm整数倍向上取值',
         rf"\mathrm{{DN}}_0=100\left\lceil\frac{{{t['theoretical_outer_mm']:.4f}}}{{100}}\right\rceil={t['first_rounded_outer_mm']:g}\,\mathrm{{mm}}",
         t['diameter_rule'] + '；上取后重新计算壁厚，若净内径不足则继续增大一档。'),
        ('6. 用最终外径对应的净内径复核',
         rf"d_i={t['recommended_outer_mm']:g}-2\times {t['final_wall_mm']:g}-2\times {t['lining_mm']:g}={t['final_hydraulic_inner_mm']:g}\,\mathrm{{mm}}\geq d_{{\min}}",
         f"自动上取外径 DN{t['recommended_outer_mm']:g} mm，单侧壁厚 {t['final_wall_mm']:g} mm。流速下限仍需满足；不满足时标为参考，不标为合格推荐。"),
    ]
    if '用户指定' in candidate.flags:
        rows += [('当前结果采用用户指定外径', '',
                  f"以上为自动选径依据；本次按用户指定外径 {candidate.outer_diameter_mm:g} mm 计算，其壁厚、净内径和水力评价见本工况结果。")]
    return rows


def steel_sizing_html(candidate):
    """把每步公式渲染成SVG，避免界面展示未解析的LaTeX文本。"""
    rows = sizing_explanation(candidate)
    if not rows:
        return ''
    content = ['<div class="steel-sizing-explanation" style="margin:10px 0;padding:14px 16px;border:1px solid #cbddec;border-radius:8px;background:#f5f9fd;color:#34495e;">',
               '<div style="font-size:14px;font-weight:700;">自动选径依据：从最小水力内径到公称外径</div>']
    for index, (title, formula, note) in enumerate(rows):
        # 内径扣壁厚的完整代入留在尺寸说明，本处只展示自动尺寸是否满足下限。
        if index == 5 and '用户指定' not in candidate.flags:
            trace = candidate.steel_sizing_trace
            formula = (rf"d_i={trace['final_hydraulic_inner_mm']:g}\,\mathrm{{mm}}"
                       rf"\geq d_{{\min}}={trace['required_hydraulic_inner_mm']:.4f}\,\mathrm{{mm}}")
        content += [f'<div style="margin-top:10px;font-size:13px;font-weight:600;">{escape(title)}</div>']
        if formula:
            content += ['<div style="max-width:100%;overflow-x:auto;">' + _formula_html(formula, note) + '</div>']
        if index not in (0, 2):
            content += [f'<div style="font-size:12px;line-height:1.7;color:#607080;">{escape(note)}</div>']
    return ''.join(content) + '</div>'


def add_steel_sizing_to_word(doc, candidate):
    """Word沿用同一计算快照，公式可编辑并与结果页一致。"""
    from app_渠系计算前端.export_utils import doc_add_eng_body, doc_add_formula
    rows = sizing_explanation(candidate)
    if not rows:
        return
    doc_add_eng_body(doc, '自动选径依据：从最小水力内径到公称外径')
    for title, formula, note in rows:
        doc_add_eng_body(doc, title)
        if formula:
            doc_add_formula(doc, formula)
        doc_add_eng_body(doc, note)
