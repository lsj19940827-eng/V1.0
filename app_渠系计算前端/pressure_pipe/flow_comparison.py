# -*- coding: utf-8 -*-
"""由有压计算快照构建双工况展示，供结果面板使用；不改变选径、分类或保存数据。"""

from dataclasses import dataclass
from html import escape
import math

from calc_渠系计算算法内核.有压管道设计 import ECONOMIC_RULE, PIPE_MATERIALS


@dataclass(frozen=True)
class FlowComparison:
    """同一候选管径的设计工况及原水损计算工况。"""

    design_flow: float
    loss_flow: float | None
    design_velocity: float
    loss_velocity: float | None
    design_loss_scale: float | None
    show_increased: bool
    increase_percent: float | None

    @property
    def loss_label(self):
        """明确保存水损对应的工况，旧结果缺少流量时不猜测。"""
        if self.loss_flow is None:
            return '原结果工况'
        return '加大工况' if self.show_increased else '设计工况'


def compare_flows(inp, candidate):
    """按材料的流量指数换算设计水损，始终保留原水损值及计算精度。"""
    q = float(inp.Q)
    q_loss = getattr(candidate, 'Q_increased', None)
    pct = getattr(candidate, 'increase_pct', None)
    if q_loss is None and pct is not None:
        q_loss = q * (1 + float(pct) / 100)
    if q_loss is None or not math.isfinite(float(q_loss)) or float(q_loss) <= 0:
        return FlowComparison(q, None, candidate.V_press, None, None, True, None)
    q_loss = float(q_loss)
    # 以结果快照为准，避免用户修改输入但未重算时混入新工况。
    increased = q_loss != q or bool(getattr(inp, 'use_increase', False))
    return FlowComparison(
        q, q_loss, candidate.V_press, candidate.V_press * q_loss / q,
        (q / q_loss) ** PIPE_MATERIALS[inp.material_key]['m'],
        increased, (q_loss / q - 1) * 100,
    )


def velocity_note(velocity):
    """仅描述经济流速区间，不把超出经济区间表述为运行不安全。"""
    if velocity is None:
        return '原结果未保存工况流量', '#65758a'
    if velocity > ECONOMIC_RULE['v_max']:
        return '高于经济流速上限', '#a85d0c'
    if velocity < ECONOMIC_RULE['v_min']:
        return '低于经济流速下限', '#a85d0c'
    return '处于经济流速区间', '#2e7d32'


def loss_value(candidate, field, lower_field, scale=1.0):
    """统一格式化上下限水损，缺失工况时明确保留未知。"""
    if scale is None:
        return '—'
    value = getattr(candidate, field) * scale
    lower = getattr(candidate, lower_field, None)
    return f'{value:.4f}' if lower is None else f'{value:.4f} / {lower * scale:.4f}'


def _value_html(value, unit, *, large=False, note='', color='#65758a'):
    """生成带独立单位和可选流速状态的数值单元格。"""
    cls = 'flow-number' if large else 'flow-value'
    status = f'<div class="flow-note" style="color:{color};">{escape(note)}</div>' if note else ''
    return f'<span class="{cls}">{value}</span> <span class="flow-unit">{unit}</span>{status}'


def flow_summary_html(inp, candidate, heading, material_name, category_color):
    """绘制经用户确认的设计/加大工况并列表，关闭加大时收为单列。"""
    flow = compare_flows(inp, candidate)
    dual = flow.show_increased
    upper_lower = getattr(candidate, 'hf_total_lower_km', None) is not None
    suffix = '（f 上限 / 下限）' if upper_lower else ''
    badge = candidate.category + ' · 按设计流速分类'
    right_heading = flow.loss_label
    if flow.increase_percent is not None:
        right_heading += f' · {flow.increase_percent:.3f}%'
    style = '''
    <style>
    .pressure-flow-summary{font-family:'Microsoft YaHei',sans-serif;color:#233347;margin:6px 0 12px;}
    .pressure-flow-summary .flow-title{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin:0 0 7px;}
    .pressure-flow-summary .flow-heading{font-size:23px;font-weight:700;}
    .pressure-flow-summary .flow-badge{font-size:12px;padding:4px 10px;background:#eef9ef;border-radius:6px;}
    .pressure-flow-summary .flow-spec{font-size:12px;color:#65758a;margin-bottom:15px;}
    .pressure-flow-summary .flow-frame{border:1px solid #dfe7ef;border-radius:9px;overflow:hidden;}
    .pressure-flow-summary table{border-collapse:collapse;width:100%;table-layout:fixed;margin:0;}
    .pressure-flow-summary th,.pressure-flow-summary td{padding:10px 14px;text-align:left;border:0;border-top:1px solid #dfe7ef;font-size:14px;vertical-align:middle;overflow-wrap:anywhere;}
    .pressure-flow-summary thead th{border-top:0;font-weight:600;padding-top:12px;padding-bottom:12px;}
    .pressure-flow-summary th:first-child{width:28%;font-weight:400;color:#65758a;font-size:12px;}
    .pressure-flow-summary .flow-increased{background:#f3f8fe;border-left:1px solid #dfe7ef;}
    .pressure-flow-summary .flow-number{font-size:21px;font-weight:600;}
    .pressure-flow-summary .flow-range .flow-number{font-size:17px;}
    .pressure-flow-summary .flow-unit,.pressure-flow-summary .flow-note{font-size:12px;color:#65758a;}
    .pressure-flow-summary .flow-note{margin-top:3px;}
    .pressure-flow-summary .flow-rule{display:flex;gap:6px 20px;flex-wrap:wrap;font-size:12px;color:#65758a;margin-top:10px;}
    @media(max-width:600px){.pressure-flow-summary th,.pressure-flow-summary td{padding:9px 8px;}.pressure-flow-summary .flow-number{font-size:18px;}.pressure-flow-summary .flow-range .flow-number{font-size:15px;}}
    </style>'''
    rows = []

    # 两列分别采用各自流量，沿用快照的精度，不从四位小数显示值反算。
    def append_row(label, design, increased):
        """向同一指标行加入两种工况，未启用加大时隐藏第二列。"""
        right = f'<td class="flow-increased">{increased}</td>' if dual else ''
        rows.append(f'<tr><th scope="row">{label}</th><td>{design}</td>{right}</tr>')

    append_row('流量', _value_html(f'{flow.design_flow:.3f}', 'm³/s', large=True),
               _value_html('—' if flow.loss_flow is None else f'{flow.loss_flow:.3f}', 'm³/s', large=True))
    design_note, design_color = velocity_note(flow.design_velocity)
    loss_note, loss_color = velocity_note(flow.loss_velocity)
    append_row('流速',
               _value_html(f'{flow.design_velocity:.4f}', 'm/s', large=True, note=design_note, color=design_color),
               _value_html('—' if flow.loss_velocity is None else f'{flow.loss_velocity:.4f}', 'm/s',
                           large=True, note=loss_note, color=loss_color))
    for label, field, lower, unit, large in [
        ('沿程水损', 'hf_friction_km', 'hf_friction_lower_km', 'm/km', False),
        ('局部水损', 'hf_local_km', 'hf_local_lower_km', 'm/km', False),
        ('总水损', 'hf_total_km', 'hf_total_lower_km', 'm/km', True),
        ('全管长水损', 'h_loss_total_m', 'h_loss_total_lower_m', 'm', False),
    ]:
        append_row(label + suffix,
                   _value_html(loss_value(candidate, field, lower, flow.design_loss_scale), unit, large=large),
                   _value_html(loss_value(candidate, field, lower), unit, large=large))
    right_header = (f'<th class="flow-increased" scope="col" style="color:#1976d2;">{right_heading}'
                    '<div class="flow-note">水损筛选依据</div></th>') if dual else ''
    design_basis = '经济流速分类依据' if dual else '经济流速分类与水损筛选依据'
    disabled = '<span>未启用加大流量</span>' if not dual else ''
    range_class = ' flow-range' if upper_lower else ''
    return style + f'''
    <div class="result-summary pressure-flow-summary{range_class}">
      <div class="flow-title"><div class="flow-heading" style="color:{category_color};">{escape(heading)}</div>
        <span class="flow-badge" style="color:{category_color};">{escape(badge)}</span></div>
      <div class="flow-spec">{escape(material_name)} · 水力内径 {candidate.D * 1000:g} mm · 管长 {inp.length_m:g} m</div>
      <div class="flow-frame"><table class="flow-condition-table" aria-label="{'设计与加大工况对比' if dual else '设计工况水力指标'}">
        <thead><tr><th scope="col">计算指标</th><th scope="col">设计工况<div class="flow-note">{design_basis}</div></th>{right_header}</tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table></div>
      <div class="flow-rule"><span>经济流速区间：{ECONOMIC_RULE['v_min']:g}～{ECONOMIC_RULE['v_max']:g} m/s</span>
        <span>{flow.loss_label}总水损上限：{ECONOMIC_RULE['hf_max']:g} m/km</span>{disabled}</div>
    </div>'''
