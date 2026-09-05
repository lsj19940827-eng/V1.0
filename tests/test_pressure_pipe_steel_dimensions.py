# -*- coding: utf-8 -*-
"""核验钢管构造最小壁厚、选径影响、历史工况兼容与成果导出。"""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import math
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pandas as pd
import pytest
from docx import Document
from PySide6.QtWidgets import QApplication

from app_渠系计算前端.pressure_pipe.panel import PressurePipePanel, _pressure_pipe_report_references
from app_渠系计算前端.pressure_pipe.diameter_explanation import explain_diameter
from calc_渠系计算算法内核.steel_pipe_design import get_steel_pipe_spec
from calc_渠系计算算法内核.有压管道设计 import (
    PressurePipeInput, BatchScanConfig, recommend_diameter, evaluate_single_diameter, run_batch_scan,
)


@pytest.fixture(scope='module')
def qapp():
    """提供唯一离屏Qt应用。"""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(qapp, monkeypatch):
    """创建钢管输入与项目恢复测试面板。"""
    monkeypatch.setattr('app_渠系计算前端.pressure_pipe.panel.load_formula_page', lambda *args, **kwargs: None)
    monkeypatch.setattr(PressurePipePanel, '_show_initial_help', lambda self: None)
    widget = PressurePipePanel()
    yield widget
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


def _input(**changes):
    """构造默认启用最小壁厚的新钢管工况。"""
    return PressurePipeInput(Q=0.3, material_key='钢管', steel_dimensions_enabled=True, **changes)


@pytest.mark.parametrize('basis,diameter,wall,outer,inner', [
    ('outer', 800, 6, 800, 788), ('inner', 800, 6, 812, 800),
    ('inner', 1600, 6, 1612, 1600), ('inner', 1600.1, 7, 1614.1, 1600.1),
    ('outer', 1612, 6, 1612, 1600), ('outer', 1612.1, 7, 1612.1, 1598.1),
    ('inner', 2400, 7, 2414, 2400), ('inner', 2400.1, 8, 2416.1, 2400.1),
    ('inner', 10000, 17, 10034, 10000),
])
def test_standard_ceiling_minimum_and_fixed_dimension_boundaries(basis, diameter, wall, outer, inner):
    """锁定原文6mm下限、整数进位和固定外径联立计算的临界值。"""
    spec = get_steel_pipe_spec(diameter, basis)
    assert spec.nominal_wall_thickness_mm == wall
    assert spec.outer_diameter_mm == pytest.approx(outer)
    assert spec.hydraulic_inner_diameter_mm == pytest.approx(inner)
    assert wall >= inner / 800 + 4
    # 减少1mm后必须违反6mm下限或原规范不等式，证明采用最小整数解。
    previous_inner = diameter - 2 * (wall - 1) if basis == 'outer' else diameter
    assert wall - 1 < 6 or wall - 1 < previous_inner / 800 + 4


@pytest.mark.parametrize('diameter,basis,lining', [
    (float('nan'), 'outer', 0), (0, 'outer', 0), (12, 'outer', 0),
    (10001, 'inner', 0), (800, 'outer', -1), (800, 'outer', float('inf')),
    (800, 'wrong', 0), (800, 'outer', 394),
])
def test_invalid_or_outside_standard_dimensions_are_not_silently_used(diameter, basis, lining):
    """非有限、负值、非正净空及超过10m适用边界必须明确拦截。"""
    with pytest.raises(ValueError):
        get_steel_pipe_spec(diameter, basis, lining)


def test_lining_is_separate_and_all_hydraulics_use_clear_inner_diameter():
    """800外径、6mm钢壁、3mm内衬应按782mm内径计算流速和水损。"""
    inp = _input(manual_steel_diameter_mm=800, steel_lining_thickness_mm=3)
    result = recommend_diameter(inp)
    c = result.recommended
    assert result.category == '指定'
    assert c.nominal_wall_thickness_mm == 6
    assert c.D == pytest.approx(0.782)
    assert c.V_press == pytest.approx(0.3 / (math.pi * 0.782 ** 2 / 4))
    expected_friction = 625000 * 1000 * (c.Q_increased * 3600) ** 1.9 / 782 ** 5.1
    assert c.hf_friction_km == pytest.approx(expected_friction)
    assert c.hf_total_km == pytest.approx(expected_friction * 1.15)
    assert c.nominal_outer_diameter_mm is None
    assert c.product_family == 'STEEL'
    assert '782 mm' in result.calc_steps
    assert '构造最小壁厚' in result.calc_steps


def test_wall_thickness_changes_automatic_selection_and_custom_candidates():
    """流量0.3时原600内径与600外径不等价，新选径应改为700外径。"""
    old = recommend_diameter(PressurePipeInput(Q=0.3, material_key='钢管'))
    new = recommend_diameter(_input())
    assert old.recommended.D == 0.6
    assert old.recommended.product_family is None
    assert new.recommended.nominal_diameter_mm == 700
    assert new.recommended.D == pytest.approx(0.688)
    with pytest.raises(ValueError, match='100 mm整数倍'):
        recommend_diameter(_input(steel_diameter_candidates_mm=(650, 750)))


def test_manual_non_catalog_size_is_allowed_but_legacy_d_conflict_is_rejected():
    """钢管候选不冒充产品目录；指定可制造尺寸可单独计算，旧D不得被默默忽略。"""
    rec = recommend_diameter(_input(manual_steel_diameter_mm=805.5)).recommended
    assert rec.D == pytest.approx(0.7935)
    with pytest.raises(ValueError, match='旧水力内径'):
        recommend_diameter(_input(manual_D=0.8))
    with pytest.raises(ValueError, match='规格一致'):
        evaluate_single_diameter(_input(), 0.8, product_spec=get_steel_pipe_spec(800))


def test_batch_uses_same_geometry_and_exports_traceable_wall_fields():
    """批量与单次必须完全一致，CSV带钢管壁厚且不能污染PE专用壁厚列。"""
    tmp_path = Path(__file__).resolve().parents[1] / 'tmp' / 'steel_batch_tests' / uuid4().hex
    config = BatchScanConfig(
        q_values=np.array([0.3]), slope_denominators=[], diameter_values=None,
        materials=['钢管'], output_dir=str(tmp_path / 'steel'),
        output_pdf_charts=False, output_merged_pdf=False, output_subplot_png=False,
        steel_dimensions_enabled=True, steel_lining_thickness_mm=3,
        steel_diameter_candidates_mm=(800, 1800),
    )
    output = run_batch_scan(config)
    frame = pd.read_csv(output.csv_path)
    assert len(frame) == 2
    row = frame.loc[frame['产品外径 (mm)'] == 800].iloc[0]
    c = recommend_diameter(_input(manual_steel_diameter_mm=800, steel_lining_thickness_mm=3)).recommended
    assert row['D (m)'] == pytest.approx(c.D)
    assert row['hf_total_press (m/km)'] == pytest.approx(c.hf_total_km)
    assert row['产品公称壁厚 (mm)'] == 6
    assert pd.isna(row['公称壁厚 en (mm)'])
    assert '第8.1.1条' in row['钢管尺寸计算过程']
    assert '结构验算另行完成' in row['钢管尺寸计算过程']
    assert frame.loc[frame['产品外径 (mm)'] == 1800, '产品公称壁厚 (mm)'].iloc[0] == 7
    invalid_dir = tmp_path / 'invalid'
    with pytest.raises(ValueError):
        run_batch_scan(replace(config, output_dir=str(invalid_dir), steel_diameter_candidates_mm=(800, 0)))
    assert not invalid_dir.exists()
    with pytest.raises(ValueError, match='旧水力内径序列'):
        run_batch_scan(replace(config, diameter_values=np.array([0.8])))


def test_new_case_ui_parse_round_trip_and_dirty_tracking(panel):
    """新工况仅外径选管，尺寸、内衬与计算过程随项目保存并使结果失效。"""
    panel.material_combo.setCurrentIndex(panel._mat_keys.index('钢管'))
    assert panel.D_edit.isHidden()
    assert not panel.steel_controls.isHidden()
    panel.steel_controls.diameter_edit.setText('800')
    panel.steel_controls.lining_edit.setText('3')
    assert not hasattr(panel.steel_controls, 'candidates_edit')
    assert not hasattr(panel.steel_controls, 'basis_combo')
    assert '公称外径 DN' in panel.steel_controls.diameter_label.text()
    panel._save_current_case()
    inp = panel._parse_case(panel._cases[0], 1)
    result = recommend_diameter(inp)
    assert result.recommended.D == pytest.approx(0.782)
    panel._all_results = [(0, inp, result)]
    panel.current_result = result
    panel._mark_results_fresh()
    payload = panel.to_project_dict()
    panel.from_project_dict(payload)
    assert panel.steel_controls.diameter_edit.text() == '800'
    assert panel._all_results[0][2].recommended.nominal_wall_thickness_mm == 6
    assert panel._all_results[0][1].steel_dimensions_enabled
    panel.steel_controls.lining_edit.setText('4')
    assert panel._results_dirty
    assert panel._copy_case_parameters(panel._cases[0], target := {}) is None
    assert target['steel_candidates_mm'] == ''
    assert target['steel_schema_version'] == 2
    assert panel._all_results[0][2].recommended.steel_sizing_trace == result.recommended.steel_sizing_trace


def test_old_steel_case_is_converted_to_equivalent_outer_without_shrinking_clear_bore(panel):
    """旧800mm净内径自动补成812mm外径，重开及重新计算均保留原过水尺寸。"""
    panel.from_project_dict({'cases': [{'material_key': '钢管', 'Q': '0.3', 'length': '1000', 'D': '0.8', 'local_ratio': '0.15'}]})
    assert panel.steel_controls.dimensions_enabled
    assert panel.D_edit.isHidden()
    assert panel.steel_controls.diameter_edit.text() == '812'
    assert '保留原净内径 800 mm' in panel.steel_controls.hint.text()
    inp = panel._parse_case(panel._cases[0], 1)
    assert inp.steel_dimension_basis == 'outer' and inp.manual_D is None
    c = recommend_diameter(inp).recommended
    assert c.D == pytest.approx(0.8)
    assert c.outer_diameter_mm == 812
    payload = panel.to_project_dict()
    panel.from_project_dict(payload)
    assert panel.steel_controls.diameter_edit.text() == '812'
    assert payload['cases'][0]['steel_legacy_input']['D'] == '0.8'


def test_results_and_word_show_each_wall_calculation_and_correct_reference(panel):
    """真实HTML和Word同时列出各候选壁厚、内衬及原文公式，报告使用钢管依据。"""
    inp = replace(_input(), Q=3)
    result = recommend_diameter(inp)
    panel._all_results = [(0, inp, result)]
    html = panel._build_result_card_html(0, inp, result)
    assert '推荐最小公称外径（构造最小壁厚）' in html
    assert '自动选径依据：从最小水力内径到公称外径' in html
    assert '不是规范表列产品系列' in html
    for c in result.top_candidates:
        info = explain_diameter(c)
        assert info.substitution_text in html
        assert info.wall_calculation_text in html
    assert '\\left' not in html and '\\times' not in html
    assert html.count('<svg') >= 2 * len(result.top_candidates) + 2
    folder = Path(__file__).resolve().parents[1] / 'tmp' / 'steel_test_reports'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'steel_{uuid4().hex}.docx'
    panel._build_word_report(str(target))
    doc = Document(target)
    text = '\n'.join(p.text for p in doc.paragraphs)
    assert '结构验算另行完成' in text
    assert len(doc._element.xpath('.//m:oMath')) >= 2 * len(result.top_candidates) + 5
    refs = _pressure_pipe_report_references([], False, {'STEEL'}, panel._all_results)
    assert refs == ['《水利水电工程压力钢管设计规范》(SL/T 281-2020)']


@pytest.mark.parametrize('q', [0.001, 0.01, 0.05, 0.1, 0.3, 0.5, 1, 2, 3, 5, 10, 20])
def test_automatic_outer_is_smallest_hundred_meeting_upper_limits(q):
    """独立按水力公式检查本档合格、下档必有上限超标，并覆盖旧3m范围以外。"""
    inp = replace(_input(), Q=q)
    result = recommend_diameter(inp)
    c = result.recommended
    assert c.outer_diameter_mm % 100 == 0
    assert c.V_press <= 1.5 + 1e-9
    assert c.hf_total_km <= 5 + 1e-9
    trace = c.steel_sizing_trace
    v_min = 1000 * math.sqrt(4 * q / (math.pi * 1.5))
    h_min = (625000 * 1000 * (c.Q_increased * 3600) ** 1.9 * 1.15 / 5) ** (1 / 5.1)
    assert trace['required_hydraulic_inner_mm'] == pytest.approx(max(v_min, h_min))
    assert c.hydraulic_inner_diameter_mm >= max(v_min, h_min) - 1e-7
    if c.outer_diameter_mm > 100:
        previous = get_steel_pipe_spec(c.outer_diameter_mm - 100)
        old = evaluate_single_diameter(inp, previous.inner_diameter_m, product_spec=previous)
        assert old.V_press > 1.5 or old.hf_total_km > 5
    if q == 20:
        assert c.outer_diameter_mm > 3000
    if q == 0.001:
        assert result.category == '兜底' and '参考' in result.reason


@pytest.mark.parametrize('target,lining,expected', [(788, 0, 800), (788.01, 0, 900), (782, 3, 800), (782.01, 3, 900), (1588, 0, 1600), (1588.01, 0, 1700)])
def test_rounding_boundaries_use_clear_inner_and_recheck_wall(target, lining, expected):
    """外径恰好整百不得多跳一档；增加净空需求和内衬占用后须上取。"""
    from calc_渠系计算算法内核.steel_hydraulic_sizing import select_steel_outer_diameter
    trace, spec = select_steel_outer_diameter({'required_hydraulic_inner_mm': target}, lining)
    assert spec.outer_diameter_mm == expected
    assert spec.hydraulic_inner_diameter_mm >= target - 1e-7
    assert trace['final_wall_mm'] == spec.nominal_wall_thickness_mm


@pytest.mark.parametrize('basis,diameter,lining,expected_outer,expected_inner', [
    ('inner', '1800', '3', 1814, 1794), ('outer', '805.5', '3', 805.5, 787.5),
])
def test_old_dimension_case_migration_is_idempotent(panel, basis, diameter, lining, expected_outer, expected_inner):
    """旧内径补厚、旧外径保持不动，原自定义候选留档而不限制自动推荐。"""
    case = panel._default_case()
    case.update(material_key='钢管', steel_schema_version=1, steel_dimension_basis=basis,
                steel_diameter_mm=diameter, steel_lining_mm=lining, steel_candidates_mm='800,1800')
    normalized = panel._normalized_case_data(case)
    assert float(normalized['steel_diameter_mm']) == expected_outer
    assert normalized['steel_dimension_basis'] == 'outer'
    assert normalized['steel_candidates_mm'] == ''
    assert normalized['steel_legacy_input']['steel_candidates_mm'] == '800,1800'
    assert panel._normalized_case_data(normalized) == normalized
    c = recommend_diameter(panel._parse_case(normalized, 1)).recommended
    assert c.hydraulic_inner_diameter_mm == expected_inner


def test_bad_legacy_inner_remains_blocked_until_outer_is_edited(panel):
    """旧无效值必须提示并留档，不能因自动迁移而变成无声自动推荐。"""
    panel.from_project_dict({'cases': [{'material_key': '钢管', 'Q': '0.3', 'length': '1000', 'D': 'abc', 'local_ratio': '0.15'}]})
    with pytest.raises(ValueError, match='旧内径'):
        panel._parse_case(panel._cases[0], 1)
    assert 'abc' in panel.steel_controls.hint.text()
    panel.steel_controls.diameter_edit.setText('800')
    panel._save_current_case()
    assert panel._parse_case(panel._cases[0], 1).manual_steel_diameter_mm == 800
    assert panel._cases[0]['steel_legacy_input']['D'] == 'abc'


def test_new_calculation_rejects_inner_basis_and_shows_manual_versus_auto(panel):
    """接口不能继续按内径解释新输入，手动尺寸必须和自动整百结论分别显示。"""
    with pytest.raises(ValueError, match='只接受外径'):
        recommend_diameter(_input(steel_dimension_basis='inner'))
    result = recommend_diameter(_input(manual_steel_diameter_mm=805.5))
    html = panel._build_result_card_html(0, _input(manual_steel_diameter_mm=805.5), result)
    assert '本次按用户指定外径 805.5 mm 计算' in html
    assert result.auto_recommended.outer_diameter_mm == 700
    assert result.recommended.outer_diameter_mm == 805.5
    low_flow = replace(_input(), Q=0.001)
    reference = recommend_diameter(low_flow)
    html = panel._build_result_card_html(0, low_flow, reference)
    assert '★ 参考' in html and '★ 推荐' not in html
    assert '就近流速' not in html and '就近流速' not in reference.calc_steps


def test_batch_default_outer_sequence_reaches_continuous_minimum_above_three_metres():
    """批量整百序列自动扩展到反算所需尺寸，CSV与单次最小外径一致。"""
    folder = Path(__file__).resolve().parents[1] / 'tmp' / 'steel_batch_tests' / uuid4().hex
    config = BatchScanConfig(q_values=np.array([20.]), slope_denominators=[], diameter_values=None,
        materials=['钢管'], output_dir=str(folder), output_pdf_charts=False, output_merged_pdf=False,
        output_subplot_png=False, steel_dimensions_enabled=True)
    frame = pd.read_csv(run_batch_scan(config).csv_path)
    assert all(frame['产品外径 (mm)'] % 100 == 0)
    c = recommend_diameter(replace(_input(), Q=20)).recommended
    selected = frame[frame['钢管最小推荐档']]
    assert len(selected) == 1
    assert selected.iloc[0]['产品外径 (mm)'] == c.outer_diameter_mm
    assert selected.iloc[0]['钢管所需最小水力内径 (mm)'] == pytest.approx(c.steel_sizing_trace['required_hydraulic_inner_mm'])


def test_restored_old_steel_result_is_preserved_and_marked_stale(panel):
    """历史结果不重新计算或改写，输入转外径后旧结果必须明确待重算。"""
    old_input = PressurePipeInput(Q=0.3, material_key='钢管', manual_D=0.8)
    old_result = recommend_diameter(old_input)
    payload = {
        'cases': [{'material_key': '钢管', 'Q': '0.3', 'length': '1000', 'D': '0.8', 'local_ratio': '0.15'}],
        'result_state': {'results_dirty': False, 'has_rendered_results': True},
    }
    # 使用正式序列化通路生成结果列表，避免依赖内部JSON字段命名。
    panel._all_results = [(0, old_input, old_result)]
    payload['all_results'] = panel._all_results_to_project_list()
    panel.from_project_dict(payload)
    assert panel._all_results[0][2].recommended.D == 0.8
    assert panel.steel_controls.diameter_edit.text() == '812'
    assert panel._results_dirty and 0 in panel._stale_result_case_indexes
