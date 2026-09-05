# -*- coding: utf-8 -*-
"""验证双工况展示数值、开关、材料指数及保存恢复，关联结果面板与计算内核。"""

from dataclasses import asdict, replace
from types import SimpleNamespace
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication

from app_渠系计算前端.pressure_pipe.flow_comparison import (
    compare_flows, flow_summary_html, loss_value,
)
from app_渠系计算前端.pressure_pipe.panel import PressurePipePanel
from calc_渠系计算算法内核.有压管道设计 import (
    PIPE_MATERIALS, PressurePipeInput, evaluate_single_diameter, recommend_diameter,
)


@pytest.mark.parametrize('material', list(PIPE_MATERIALS))
@pytest.mark.parametrize('pct', [0, 25, 13.1234567])
def test_both_conditions_match_independent_kernel_calculations(material, pct):
    """各材料以原公式独立计算两工况，防止统一套平方、舍入反算或更改原候选。"""
    inp = PressurePipeInput(Q=2, material_key=material, manual_increase_percent=pct, length_m=2300)
    candidate = evaluate_single_diameter(inp, 1.4)
    original = asdict(candidate)
    design = evaluate_single_diameter(replace(inp, manual_increase_percent=0), 1.4)
    increased = evaluate_single_diameter(replace(inp, Q=candidate.Q_increased, manual_increase_percent=0), 1.4)
    flow = compare_flows(inp, candidate)
    assert flow.design_velocity == pytest.approx(design.V_press)
    assert flow.loss_velocity == pytest.approx(increased.V_press)
    for field, lower in [
        ('hf_friction_km', 'hf_friction_lower_km'), ('hf_local_km', 'hf_local_lower_km'),
        ('hf_total_km', 'hf_total_lower_km'), ('h_loss_total_m', 'h_loss_total_lower_m'),
    ]:
        assert getattr(candidate, field) * flow.design_loss_scale == pytest.approx(getattr(design, field))
        assert getattr(candidate, field) == pytest.approx(getattr(increased, field))
        if getattr(candidate, lower) is not None:
            assert getattr(candidate, lower) * flow.design_loss_scale == pytest.approx(getattr(design, lower))
        assert loss_value(candidate, field, lower, flow.design_loss_scale).startswith(f'{getattr(design, field):.4f}')
    assert asdict(candidate) == original


@pytest.fixture(scope='module')
def qapp():
    """提供结果显示和项目恢复所需的离屏Qt应用。"""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(qapp, monkeypatch):
    """跳过帮助页加载以聚焦实际计算结果展示。"""
    monkeypatch.setattr(PressurePipePanel, '_show_initial_help', lambda self: None)
    widget = PressurePipePanel()
    yield widget
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize('enabled,mode,pct,q_text', [
    (False, 'percent', '', ''), (True, 'percent', '', ''),
    (True, 'percent', '25', ''), (True, 'q_increased', '', '2.5'),
])
def test_screenshot_inputs_and_restore_keep_consistent_columns(panel, enabled, mode, pct, q_text):
    """真实输入入口、开关及保存恢复均明确列出各自工况，原推荐与顺序保持一致。"""
    case = panel._default_case()
    case.update(Q='2', material_key='预应力钢筒混凝土管',
                material_idx=panel._mat_keys.index('预应力钢筒混凝土管'),
                inc_checked=enabled, inc_mode=mode, inc_pct=pct, inc_q_text=q_text)
    inp = panel._parse_case(case, 1)
    result = recommend_diameter(inp)
    before = panel._result_to_project_dict(result)
    panel._all_results = [(0, inp, result)]
    html = panel._build_result_card_html(0, inp, result)
    assert result.recommended.nominal_diameter_mm == 1400
    assert '推荐管径 DN 1400' in html
    assert '按设计流速分类' in html and '1.2992' in html and '1.3318' in html
    table = html.split('class="candidate-comparison"', 1)[1].split('</table>', 1)[0]
    if enabled:
        assert '加大工况 · 25.000%' in html
        assert '1.6240' in html and '2.0809' in html and '高于经济流速上限' in html
        assert '加大流速' in table and '加大工况总水损' in table
    else:
        assert '未启用加大流量' in html
        assert '加大流速' not in table and '设计工况总水损' in table
        assert '加大工况 ·' not in html
    assert before == panel._result_to_project_dict(result)
    restored_input = panel._input_from_project_dict(panel._input_to_project_dict(inp))
    restored_result = panel._result_from_project_dict(before)
    assert panel._build_result_card_html(0, restored_input, restored_result) == html


def test_manual_size_uses_its_own_flow_values_and_keeps_auto_comparison(panel):
    """指定规格与自动推荐规格不同时，各自采用对应管径流速。"""
    inp = PressurePipeInput(Q=2, material_key='预应力钢筒混凝土管', manual_product_diameter_mm=1600)
    result = recommend_diameter(inp)
    panel._all_results = [(0, inp, result)]
    html = panel._build_result_card_html(0, inp, result)
    summary = html.split('class="result-summary', 1)[1].split('<!--', 1)[0]
    assert '指定管径 DN 1600' in summary
    assert '0.9947' in summary and '1.2434' in summary
    assert '设计流速 = 1.2992' in html
    assert '加大工况总水损 = 2.0809' in html


def test_missing_old_flow_keeps_stored_losses_without_fabricating_design_loss():
    """缺少流量的旧结果保留原水损，并明确标记未知工况。"""
    inp = PressurePipeInput(Q=2, material_key='预应力钢筒混凝土管')
    candidate = recommend_diameter(inp).recommended
    saved = asdict(candidate)
    del saved['Q_increased']
    del saved['increase_pct']
    old = SimpleNamespace(**saved)
    flow = compare_flows(inp, old)
    assert flow.loss_flow is None and flow.design_loss_scale is None
    html = flow_summary_html(inp, old, '旧结果', 'PCCPE', '#2e7d32')
    assert '原结果工况' in html and '原结果未保存工况流量' in html
    assert '2.0809' in html and '1.3318' not in html


def test_zero_percent_enabled_does_not_pretend_flow_was_increased():
    """显式零加大比例保留两列相同结果，但标清零比例。"""
    inp = PressurePipeInput(Q=2, material_key='预应力钢筒混凝土管', manual_increase_percent=0)
    inp.use_increase = True
    candidate = recommend_diameter(inp).recommended
    html = flow_summary_html(inp, candidate, '推荐', 'PCCPE', '#2e7d32')
    assert '加大工况 · 0.000%' in html
    assert html.count('1.2992') == 2
    assert html.count('1.3318') == 4
