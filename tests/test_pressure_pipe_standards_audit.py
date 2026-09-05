# -*- coding: utf-8 -*-
"""用独立规范表快照审计目录及全规格计算，关联 PE/通用目录和有压管道内核。"""

import json
import math
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from calc_渠系计算算法内核.pe_pipe_catalog import (
    get_pe_pipe_spec, get_pe_pipe_specs, get_pe_sdr,
)
from calc_渠系计算算法内核.pipe_product_catalog import (
    get_ductile_iron_specs, get_frpm_inner_specs, get_pccp_specs,
    get_pipe_product_spec, PCCP_MATERIAL_KEYS,
)
from calc_渠系计算算法内核.有压管道设计 import (
    BatchScanConfig, PressurePipeInput, evaluate_single_diameter,
    recommend_diameter, run_batch_scan,
)

DATA = json.loads((Path(__file__).parent / 'fixtures/pressure_pipe_standard_tables.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('grade', ['PE80', 'PE100'])
def test_all_pe_source_cells_and_blank_cells(grade):
    """独立表3快照逐格约束两种牌号，空白不得补算，所有合法规格须能算出有限水损。"""
    for column, (sdr, pn) in enumerate(zip(DATA['pe_sdr_columns'], DATA['pe_pn_by_grade'][grade]), 1):
        assert get_pe_sdr(grade, pn) == sdr
        expected_dns = []
        for row in DATA['pe_dn_wall_rows']:
            dn, wall = row[0], row[column]
            if wall is None:
                with pytest.raises(ValueError):
                    get_pe_pipe_spec(grade, pn, dn)
                continue
            expected_dns.append(dn)
            spec = get_pe_pipe_spec(grade, pn, dn)
            assert spec.nominal_wall_thickness_mm == wall
            inner = (dn - 2 * wall) / 1000
            result = recommend_diameter(PressurePipeInput(
                Q=math.pi * inner ** 2 / 4, material_key='HDPE管',
                pe_material_grade=grade, pe_nominal_pressure_mpa=pn,
                manual_nominal_diameter_mm=dn,
            ))
            assert result.category == '指定'
            assert result.recommended.D == pytest.approx(inner)
            assert result.recommended.V_press == pytest.approx(1)
            assert math.isfinite(result.recommended.h_loss_total_m)
        assert [s.nominal_outer_diameter_mm for s in get_pe_pipe_specs(grade, pn)] == expected_dns


@pytest.mark.parametrize('class_code', DATA['di_class_columns'])
def test_all_di_source_cells_and_blank_cells(class_code):
    """原表影像横行快照逐格验证140个壁厚组合，覆盖OCR丢列及全部空白。"""
    column = DATA['di_class_columns'].index(class_code) + 2
    expected_dns = []
    for row in DATA['di_dn_de_wall_rows']:
        dn, de, wall = row[0], row[1], row[column]
        if wall is None:
            with pytest.raises(ValueError):
                get_pipe_product_spec('球墨铸铁管', dn, ductile_iron_class=class_code)
            continue
        expected_dns.append(dn)
        spec = get_pipe_product_spec('球墨铸铁管', dn, ductile_iron_class=class_code)
        assert spec.outer_diameter_mm == de
        assert spec.nominal_wall_thickness_mm == wall
        expected_inner = (de - 2 * (wall + spec.lining_thickness_mm)) / 1000
        result = recommend_diameter(PressurePipeInput(
            Q=math.pi * expected_inner ** 2 / 4, material_key='球墨铸铁管',
            ductile_iron_class=class_code, manual_product_diameter_mm=dn,
        ))
        assert result.category == '指定'
        assert result.recommended.D == pytest.approx(expected_inner)
        assert result.recommended.V_press == pytest.approx(1)
        assert math.isfinite(result.recommended.h_loss_total_m)
    assert [s.nominal_diameter_mm for s in get_ductile_iron_specs(class_code)] == expected_dns


def test_all_frpm_source_ranges_and_pccp_variants():
    """按原表逐项约束FRPM公差与PCCP型式，三档摩阻预设都应使用各型式完整系列。"""
    assert [[s.nominal_diameter_mm, s.minimum_inner_diameter_mm,
             s.maximum_inner_diameter_mm, s.selected_inner_diameter_tolerance_mm]
            for s in get_frpm_inner_specs()] == DATA['frpm_dn_min_max_tolerance_rows']
    for dn, minimum, maximum, tolerance in DATA['frpm_dn_min_max_tolerance_rows']:
        result = recommend_diameter(PressurePipeInput(
            Q=1, material_key='玻璃钢夹砂管', manual_product_diameter_mm=dn,
        ))
        assert result.recommended.D == pytest.approx(dn / 1000)
        assert result.recommended.minimum_inner_diameter_mm == minimum
        assert result.recommended.maximum_inner_diameter_mm == maximum
        assert result.recommended.selected_inner_diameter_tolerance_mm == tolerance
    for material in PCCP_MATERIAL_KEYS:
        for variant in ('PCCPL', 'PCCPE'):
            diameters = DATA[f'{variant.lower()}_diameters']
            assert [s.nominal_diameter_mm for s in get_pccp_specs(material, variant)] == diameters
            for dn in diameters:
                result = recommend_diameter(PressurePipeInput(
                    Q=1, material_key=material, pccp_variant=variant, manual_product_diameter_mm=dn,
                ))
                assert result.recommended.D == pytest.approx(dn / 1000)
                assert result.recommended.product_variant == variant


@pytest.mark.parametrize('field', ['Q', 'length_m', 'local_loss_ratio', 'manual_increase_percent', 'manual_D'])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_recommendation_and_evaluation_reject_nonfinite_inputs(field, value):
    """非有限输入必须明确阻断，不能被候选扫描吞掉或输出无效的指定规格。"""
    inp = replace(PressurePipeInput(Q=0.1, material_key='球墨铸铁管', manual_product_diameter_mm=300), **{field: value})
    for calculate in (recommend_diameter, lambda p: evaluate_single_diameter(p, 0.3056)):
        with pytest.raises(ValueError, match='有限数值'):
            calculate(inp)


@pytest.mark.parametrize('field,value', [
    ('q_values', np.array([0.1, float('nan')])),
    ('diameter_values', np.array([0.3, float('inf')])),
    ('length_m', float('inf')),
    ('local_loss_ratio', float('nan')),
    ('slope_denominators', [0]),
    ('n_unpr', float('nan')),
])
def test_batch_rejects_invalid_values_before_creating_output(field, value):
    """批量入口须先校验整批输入，不能生成混有无效行的文件。"""
    destination = Path(__file__).resolve().parents[1] / 'tmp' / f'invalid_batch_{uuid4().hex}'
    config = BatchScanConfig(q_values=np.array([0.1]), slope_denominators=[1000],
                             diameter_values=None, materials=['球墨铸铁管'], output_dir=str(destination))
    with pytest.raises(ValueError, match='有限数值'):
        run_batch_scan(replace(config, **{field: value}))
    assert not destination.exists()
