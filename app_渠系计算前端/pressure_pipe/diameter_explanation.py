# -*- coding: utf-8 -*-
"""解释结果快照中的公称尺寸、壁厚与内径，供有压管道结果页和Word共用。"""

from dataclasses import dataclass
from html import escape
import math

from app_渠系计算前端.formula_renderer import render_latex_svg
from calc_渠系计算算法内核.steel_pipe_design import STEEL_SCOPE, steel_wall_calculation


@dataclass(frozen=True)
class DiameterExplanation:
    """一个已计算规格的中文尺寸说明与可渲染公式，不反查或改写历史目录。"""

    nominal_text: str
    dimensions: tuple[tuple[str, str], ...]
    meaning: str
    wall_text: str
    method: str
    formula: str
    substitution: str
    substitution_text: str
    source: str
    wall_formula: str = ''
    wall_substitution: str = ''
    wall_calculation_text: str = ''


def _number(candidate, field):
    """读取有限的快照数值，缺失时保留未知，不用现行目录补造壁厚。"""
    value = getattr(candidate, field, None)
    try:
        return float(value) if value is not None and math.isfinite(float(value)) else None
    except (TypeError, ValueError):
        return None


def explain_diameter(candidate):
    """按各管材的公称尺寸基准生成解释；旧任意内径结果没有采购换算说明。"""
    family = getattr(candidate, 'product_family', None)
    outer = _number(candidate, 'nominal_outer_diameter_mm')
    if outer is not None:
        family = 'PE'
    if family not in {'PE', 'DI', 'PCCP', 'FRPM', 'STEEL'}:
        return None
    nominal = outer if family == 'PE' else _number(candidate, 'nominal_diameter_mm')
    inner = _number(candidate, 'hydraulic_inner_diameter_mm')
    if nominal is None or inner is None:
        return None
    nominal_text = f'DN{nominal:g}'
    dimensions = [('公称外径 DN' if family == 'PE' else '公称尺寸 DN', f'{nominal:g} mm')]
    wall = _number(candidate, 'nominal_wall_thickness_mm')
    source = getattr(candidate, 'product_source_locator', None) or getattr(candidate, 'product_standard', None) or '原结果未保存标准定位'
    if family == 'PE' and wall is not None:
        if not getattr(candidate, 'product_source_locator', None):
            source += ' 表3'
        dimensions += [('单侧壁厚', f'{wall:g} mm'), ('水力内径', f'{inner:g} mm')]
        return DiameterExplanation(
            nominal_text, tuple(dimensions),
            'PE 管的 DN 表示公称外径；单侧壁厚指一侧管壁的厚度。水流通过中间的净空，两侧管壁各扣一次。',
            f'单侧壁厚 {wall:g} mm', '水力内径 = 公称外径 − 2 × 单侧壁厚',
            r'd_i = \mathrm{DN} - 2e_n',
            rf'd_i = {nominal:g} - 2\times {wall:g} = {inner:g}\,\mathrm{{mm}}',
            f'{nominal:g} − 2 × {wall:g} = {inner:g} mm',
            f'{source}；公称外径对应行、所选 SDR 对应列的表列壁厚。壁厚直接查表，不用外径除以 SDR 替代表值。',
        )
    de = _number(candidate, 'outer_diameter_mm')
    lining = _number(candidate, 'lining_thickness_mm')
    if family == 'STEEL' and all(value is not None for value in (wall, de, lining)):
        basis = getattr(candidate, 'nominal_basis', '选径尺寸')
        wall_formula, wall_substitution, wall_text = steel_wall_calculation(candidate)
        return DiameterExplanation(
            f'{basis}{nominal:g}',
            (('钢管外径', f'{de:g} mm'), ('构造最小壁厚（单侧）', f'{wall:g} mm'),
             ('钢管内径（未扣内衬）', f'{de - 2 * wall:g} mm'),
             ('单侧内衬', f'{lining:g} mm'), ('水力内径', f'{inner:g} mm')),
            f'本次按{basis}选管。规范壁厚公式中的 D 是钢管内径；水力内径还要扣除两侧内衬。'
            '公式单位为毫米，小数向上取整，最少6 mm；最小值已包括壁厚裕量，不重复加2 mm。',
            f'构造最小壁厚 {wall:g} mm；单侧内衬 {lining:g} mm',
            '水力内径 = 钢管外径 − 2 ×（单侧钢板壁厚 + 单侧内衬厚）',
            r'd_i=D_e-2(t+e_c)',
            rf'd_i={de:g}-2\times({wall:g}+{lining:g})={inner:g}\,\mathrm{{mm}}',
            f'{de:g} − 2 × ({wall:g} + {lining:g}) = {inner:g} mm',
            f'{source}。{STEEL_SCOPE}', wall_formula, wall_substitution, wall_text,
        )
    if family == 'DI' and all(value is not None for value in (wall, de, lining)):
        dimensions += [('插口外径 DE', f'{de:g} mm'), ('单侧管壁厚', f'{wall:g} mm'),
                       ('单侧内衬厚', f'{lining:g} mm'), ('水力内径', f'{inner:g} mm')]
        return DiameterExplanation(
            nominal_text, tuple(dimensions),
            '球墨铸铁管的 DN 是规格名称。按该规格和等级查得插口外径、管壁厚及内衬厚，再从外径扣除两侧管壁和内衬。',
            f'单侧管壁 {wall:g} mm；单侧内衬 {lining:g} mm',
            '水力内径 = 插口外径 − 2 ×（单侧管壁厚 + 单侧内衬厚）',
            r'd_i = DE - 2(e_{\mathrm{nom}} + e_c)',
            rf'd_i = {de:g} - 2\times({wall:g}+{lining:g}) = {inner:g}\,\mathrm{{mm}}',
            f'{de:g} − 2 × ({wall:g} + {lining:g}) = {inner:g} mm', source,
        )
    if family in {'PCCP', 'FRPM'}:
        dimensions = [('公称内径 DN', f'{nominal:g} mm'), ('水力内径', f'{inner:g} mm')]
        pipe_name = 'PCCP 管' if family == 'PCCP' else '本次玻璃钢夹砂管内径系列'
        wall_text = '壁厚未由本尺寸目录确定'
        return DiameterExplanation(
            nominal_text, tuple(dimensions),
            f'{pipe_name}的 DN 表示公称内径，已经是内部通水尺寸，本次直接作为名义水力内径，不再扣两次壁厚。',
            wall_text, '水力内径 = 公称内径；壁厚由具体产品结构及供货资料确定。',
            r'd_i = \mathrm{DN}', rf'd_i = \mathrm{{DN}} = {inner:g}\,\mathrm{{mm}}',
            f'直接采用公称内径 {nominal:g} mm，水力内径为 {inner:g} mm', source,
        )
    return DiameterExplanation(
        nominal_text, tuple(dimensions + [('水力内径', f'{inner:g} mm')]),
        '该历史结果缺少完整管壁或内衬尺寸，保留已保存的水力内径。',
        '壁厚信息未完整保存', '缺少尺寸记录，无法展示完整换算；可重新选径计算。',
        '', '', f'已保存水力内径 {inner:g} mm', source,
    )


def _formula_html(latex, fallback, fontsize=13):
    """使用现有SVG渲染器显示公式，失败时显示中文算式而不暴露LaTeX源码。"""
    svg = render_latex_svg(latex, fontsize=fontsize) if latex else None
    return svg or f'<span>{escape(fallback)}</span>'


def diameter_summary_html(candidate):
    """在结果摘要旁显示参数身份、取值、查表来源和完整数值代入。"""
    info = explain_diameter(candidate)
    if info is None:
        return ''
    values = ''.join(
        f'<div aria-label="{escape(label)} {escape(value)}" style="padding:7px 12px;background:#fff;border:1px solid #dbe7f3;border-radius:6px;">'
        f'<div style="font-size:12px;color:#586777;">{escape(label)}</div>'
        f'<strong style="font-size:16px;color:#164e7a;">{escape(value)}</strong></div>'
        for label, value in info.dimensions
    )
    wall_html = ''
    if info.wall_formula:
        wall_html = (
            '<div style="font-size:13px;margin-top:8px;">构造最小壁厚计算（D 为钢管内径，单位 mm）：</div>'
            '<div style="overflow-x:auto;">' + _formula_html(r't\geq D/800+4,\quad t\geq6', '壁厚至少为钢管内径除以800再加4，且至少6 mm') + '</div>'
            f'<div style="overflow-x:auto;" aria-label="{escape(info.wall_calculation_text)}">'
            + _formula_html(info.wall_substitution, info.wall_calculation_text) + '</div>'
        )
    title = '钢管尺寸、最小壁厚与水力内径' if info.wall_formula else '公称直径、壁厚与水力内径'
    return f'''<div class="diameter-explanation" style="margin:10px 0;padding:14px 16px;
        border:1px solid #cbddec;border-radius:8px;background:#f5f9fd;color:#34495e;">
        <div style="font-size:14px;font-weight:700;margin-bottom:8px;">{title}</div>
        <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px;">{values}</div>
        <div style="font-size:13px;line-height:1.7;">{escape(info.meaning)}</div>
        {wall_html}
        <div style="font-size:13px;line-height:1.7;margin-top:4px;">{escape(info.method) if not info.formula else ""}</div>
        <div style="max-width:100%;overflow-x:auto;" aria-label="{escape(info.method)}">{_formula_html(info.formula, info.method)}</div>
        <div style="max-width:100%;overflow-x:auto;" aria-label="{escape(info.substitution_text)}">{_formula_html(info.substitution, info.substitution_text)}</div>
        <div style="font-size:12px;color:#607080;line-height:1.6;margin-top:4px;">取值依据：{escape(info.source)}</div>
        </div>'''


def diameter_candidate_row_html(candidate, colspan, recommended=False):
    """用通栏说明行逐档展示壁厚和代入过程，避免继续挤宽水损对比列。"""
    info = explain_diameter(candidate)
    if info is None:
        return ''
    background = '#f1f8ec' if recommended else '#f7f9fc'
    wall_html = ''
    if info.wall_substitution:
        wall_html = f'<div style="overflow-x:auto;" aria-label="{escape(info.wall_calculation_text)}">' + _formula_html(info.wall_substitution, info.wall_calculation_text, 11) + '</div>'
    return f'''<tr class="candidate-diameter-explanation" style="background:{background};">
        <td colspan="{colspan}" style="padding:6px 12px 10px;border-bottom:1px solid #dce4ec;text-align:left;">
        <div style="display:flex;flex-wrap:wrap;align-items:center;gap:6px 18px;font-size:12px;color:#526478;">
        <span>{escape(info.nominal_text)} · {escape(info.wall_text)}</span>
        <span aria-label="{escape(info.substitution_text)}">{_formula_html(info.substitution, info.substitution_text, 11)}</span>
        </div>{wall_html}</td></tr>'''


def add_diameter_summary_to_word(doc, candidate):
    """将同一快照的中文解释和可编辑公式写入Word结果汇总。"""
    from app_渠系计算前端.export_utils import doc_add_eng_body, doc_add_formula

    info = explain_diameter(candidate)
    if info is None:
        return
    doc_add_eng_body(doc, '钢管尺寸、最小壁厚与水力内径' if info.wall_formula else '公称直径、壁厚与水力内径')
    doc_add_eng_body(doc, '；'.join(f'{label}：{value}' for label, value in info.dimensions))
    doc_add_eng_body(doc, info.meaning)
    if info.wall_formula:
        doc_add_formula(doc, r't\geq D/800+4,\quad t\geq6')
        doc_add_eng_body(doc, info.wall_calculation_text)
        doc_add_formula(doc, info.wall_formula)
        doc_add_formula(doc, info.wall_substitution)
    doc_add_eng_body(doc, info.method)
    if info.formula:
        doc_add_formula(doc, info.formula)
        doc_add_formula(doc, info.substitution)
    doc_add_eng_body(doc, f'取值依据：{info.source}')


def add_candidate_diameters_to_word(doc, candidates):
    """用独立的三列表逐档保留换算过程，数学单元格写成Word可编辑公式。"""
    from app_渠系计算前端.export_utils import doc_add_eng_body, doc_add_styled_table, latex_to_omml, doc_add_formula

    infos = [info for candidate in candidates if (info := explain_diameter(candidate)) is not None]
    if not infos:
        return
    doc_add_eng_body(doc, '候选规格的壁厚与内径换算（与上表顺序一致）')
    table = doc_add_styled_table(
        doc, ['候选规格', '管壁与内衬', '水力内径计算（mm）'],
        [[info.nominal_text, info.wall_text, info.substitution_text] for info in infos],
        with_full_border=True,
    )
    # 将主要宽度留给完整代入式，避免三列等宽挤压Word数学公式。
    section = doc.sections[-1]
    available_width = section.page_width - section.left_margin - section.right_margin
    table.autofit = False
    for column, ratio in zip(table.columns, (0.17, 0.28, 0.55)):
        column.width = int(available_width * ratio)
        for cell in column.cells:
            cell.width = column.width
    for index, info in enumerate(infos, 1):
        omml = latex_to_omml(info.substitution) if info.substitution else None
        if omml is not None:
            paragraph = table.cell(index, 2).paragraphs[0]
            paragraph.clear()
            paragraph._element.append(omml)
    # 壁厚进位式较宽，单列全文宽的可编辑公式，避免挤入尺寸换算表的小单元格。
    for info in infos:
        if info.wall_substitution:
            doc_add_eng_body(doc, f'{info.nominal_text}：构造最小壁厚计算')
            doc_add_formula(doc, info.wall_substitution)
