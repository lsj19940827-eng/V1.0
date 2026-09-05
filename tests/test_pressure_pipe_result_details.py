# -*- coding: utf-8 -*-
"""核验结果精简不丢失水力过程、双限值、工程提示与旧结果内容。"""

from dataclasses import replace
import pickle

import pytest

from app_渠系计算前端.pressure_pipe.result_details import concise_process_text
from calc_渠系计算算法内核.有压管道设计 import PressurePipeInput, recommend_diameter


@pytest.mark.parametrize('manual', [False, True])
@pytest.mark.parametrize('material,options,manual_field', [
    ('钢管', {'steel_dimensions_enabled': True}, 'manual_steel_diameter_mm'),
    ('HDPE管', {}, 'manual_nominal_diameter_mm'),
    ('球墨铸铁管', {}, 'manual_product_diameter_mm'),
    ('预应力钢筒混凝土管', {}, 'manual_product_diameter_mm'),
    ('玻璃钢夹砂管', {}, 'manual_product_diameter_mm'),
])
def test_deduplication_preserves_hydraulics_and_snapshot(material, options, manual_field, manual):
    """五类管材自动/指定过程去除重复尺寸与结果，实际运算行及提示完整保留。"""
    kwargs = dict(options)
    if manual:
        kwargs[manual_field] = 1000
    result = recommend_diameter(PressurePipeInput(Q=0.5, material_key=material, **kwargs))
    original = pickle.dumps(result)
    compact = concise_process_text(result)
    label = '指定管径' if manual else '推荐管径'
    assert f'【五、{label}结果】' not in compact
    assert f'1. {label}:' not in compact
    assert '【流速与水头损失计算】' in compact
    hydraulic = result.calc_steps.split('  2. 过水面积计算:', 1)[1].split('【四、筛选判定】', 1)[0]
    for line in hydraulic.splitlines():
        if line.startswith('     ') and line.strip():
            assert line in compact
    for line in result.calc_steps.splitlines():
        if line.strip().startswith(('工程提示:', '尺寸边界:', '标记:')):
            assert line.strip() in compact
    if material == '球墨铸铁管':
        assert 'f 上限:' in compact and 'f 下限:' in compact
    assert pickle.dumps(result) == original


@pytest.mark.parametrize('q', [0.001, 0.5])
def test_steel_reference_and_selection_reason_remain(q):
    """钢管不满足条件的参考标记和原筛选结论不得因精简丢失。"""
    result = recommend_diameter(PressurePipeInput(Q=q, material_key='钢管', steel_dimensions_enabled=True))
    compact = concise_process_text(result)
    selection = result.calc_steps.split('【四、筛选判定】', 1)[1].split('【五、', 1)[0]
    assert selection in compact
    if q == 0.001:
        assert '仅作参考' in compact


def test_unrecognized_or_incomplete_history_remains_verbatim():
    """未知章节、缺失步骤和残缺尺寸快照均原样保留，不用当前格式强行裁剪。"""
    result = recommend_diameter(PressurePipeInput(Q=0.5, material_key='HDPE管'))
    for changed in [
        replace(result, calc_steps=result.calc_steps + '\n【补充现场条件】\n特殊条件'),
        replace(result, calc_steps=result.calc_steps.replace('  2. 过水面积计算:', '旧版过水面积:')),
        replace(result, recommended=replace(result.recommended, nominal_wall_thickness_mm=None)),
    ]:
        assert concise_process_text(changed) == changed.calc_steps
