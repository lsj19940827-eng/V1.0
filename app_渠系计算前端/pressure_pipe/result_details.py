# -*- coding: utf-8 -*-
"""精简结果页的重复过程，保留原始计算快照供报告和历史结果使用。"""

import re

from app_渠系计算前端.pressure_pipe.diameter_explanation import explain_diameter


def concise_process_text(result):
    """仅精简已知完整格式；缺失尺寸或未知历史格式原样展示，避免误删依据。"""
    original = getattr(result, 'calc_steps', '') or ''
    info = explain_diameter(getattr(result, 'recommended', None))
    if not info or not info.formula:
        return original
    text = original.replace('\r\n', '\n')
    sections = list(re.finditer(r'^【([^】]+)】[ \t]*$', text, re.MULTILINE))
    expected = [
        '一、输入参数', '二、加大流量计算',
        '三、指定管径计算' if result.category == '指定' else '三、推荐管径计算',
        '四、筛选判定',
        '五、指定管径结果' if result.category == '指定' else '五、推荐管径结果',
    ]
    titles = [match.group(1) for match in sections]
    if titles not in (expected, expected + ['六、自动推荐对比']):
        return original
    bodies = [text[match.end():sections[i + 1].start() if i + 1 < len(sections) else len(text)]
              for i, match in enumerate(sections)]
    area = re.search(r'^  2\. 过水面积计算:', bodies[2], re.MULTILINE)
    if not area:
        return original
    # 面积、流速及上下限水损逐行沿用快照；仅删去前面已完整展示的尺寸推导。
    hydraulic = re.sub(
        r'^  ([2-7])\.', lambda match: f'  {int(match.group(1)) - 1}.',
        bodies[2][area.start():], flags=re.MULTILINE,
    )
    # 结果数值已在摘要和候选表展示，汇总中的提示与标记仍须保留。
    notes = [line.strip() for line in bodies[4].splitlines()
             if line.strip().startswith(('工程提示:', '尺寸边界:', '标记:'))]
    parts = [
        '【输入参数】' + bodies[0],
        '【加大流量计算】' + bodies[1],
        '【流速与水头损失计算】\n' + hydraulic,
        '【筛选判定】' + bodies[3],
    ]
    if notes:
        parts.append('【补充说明】\n' + '\n'.join('  ' + line for line in notes))
    return '\n\n'.join(parts)
