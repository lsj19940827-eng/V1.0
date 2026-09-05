"""无压改版的独立水力核算、参数边界、批量口径及结果输出验证。"""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'calc_渠系计算算法内核'))
from 有压管道设计 import BatchScanConfig, run_batch_scan, PressurePipeInput, evaluate_single_diameter
from calc_渠系计算算法内核.unpressurized_comparison import (
    normal_flow, parse_slope_text, generate_slopes, FLOW_BASES,
)


@pytest.mark.parametrize('fraction', [0.05, 0.25, 0.5, 0.8, 0.93])
def test_recover_known_depth(fraction):
    """从独立圆管几何构造流量，验证求回的水深和连续方程。"""
    diameter, n, slope = 1.2, 0.014, 0.001
    theta = 2 * math.acos(1 - 2 * fraction)
    area = diameter ** 2 / 8 * (theta - math.sin(theta))
    perimeter = diameter * theta / 2
    q = area / n * (area / perimeter) ** (2 / 3) * math.sqrt(slope)
    result = normal_flow(q, diameter, n, slope)
    assert result['depth'] == pytest.approx(fraction * diameter, abs=1e-9)
    assert result['velocity'] * area == pytest.approx(q)
    assert result['status'] == '可形成均匀流'


def test_capacity_boundary_and_shallow_branch():
    """最大点可解、略超能力明确失败，多解区稳定落在较浅水深支。"""
    base = normal_flow(0.2, 1.0, 0.014, 0.001)
    peak = normal_flow(base['capacity'], 1.0, 0.014, 0.001)
    assert peak['filling'] == pytest.approx(0.938181, abs=1e-6)
    above = normal_flow(base['capacity'] * 1.00001, 1.0, 0.014, 0.001)
    assert above['status'] == '能力不足'
    assert above['depth'] is None
    assert above['capacity'] > 0
    shallow = normal_flow((base['capacity'] + base['full_capacity']) / 2, 1.0, 0.014, 0.001)
    assert shallow['filling'] < peak['filling']


def test_solver_failure_is_not_capacity_failure(monkeypatch):
    """数值例外必须保留求解失败身份，不能伪称能力不足。"""
    import calc_渠系计算算法内核.unpressurized_comparison as module
    module.peak_angle()
    def fail(*args, **kwargs):
        """模拟有限区间求解器报告失败。"""
        raise RuntimeError('模拟不收敛')
    monkeypatch.setattr(module, 'brentq', fail)
    result = module.normal_flow(0.1, 1.0, 0.014, 0.001)
    assert result['status'] == '求解失败'
    assert '模拟不收敛' in result['reason']


@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf'), True])
def test_invalid_hydraulics(value):
    """无效输入必须在求解前拒绝。"""
    with pytest.raises(ValueError):
        normal_flow(value, 1, .014, .001)


def test_parser_keeps_errors_and_deduplicates():
    """中文分隔符可识别，错误词保留且排序仅作用于有效预览。"""
    assert parse_slope_text('2000，500 500\n750;abc;0;1.5') == ([500, 750, 2000], ['abc', '0', '1.5'], 1)
    assert generate_slopes('500', '1800', '500') == [500, 1000, 1500]


@pytest.mark.parametrize('values', [('0', '100', '1'), ('100', '50', '10'), ('1', '999999', '1'), ('1', '100', '0'), ('1.5', '100', '1')])
def test_invalid_ranges(values):
    """无效范围和超量生成必须先拒绝。"""
    with pytest.raises(ValueError):
        generate_slopes(*values)


@pytest.fixture
def scan(tmp_path):
    """生成两种材料、两个相近流量、两个内径和两个底坡的真实批量结果。"""
    config = BatchScanConfig(q_values=np.array([0.51, 0.54]), slope_denominators=[500, 4000],
        diameter_values=np.array([0.5, 1.2]), materials=['钢管', '球墨铸铁管'], output_dir=str(tmp_path),
        output_pdf_charts=False, output_subplot_png=False, output_merged_pdf=False,
        unpr_clearance_height=0.4, unpr_clearance_area=15.0)
    return config, run_batch_scan(config)


def test_batch_flow_basis_and_exports(scan):
    """专用明细完整覆盖两种流量，与独立同流量有压计算逐项一致。"""
    config, result = scan
    assert len(result.comparison_rows) == 2 * 2 * 2 * 2 * 2
    assert len(pd.read_csv(result.csv_path)) == 2 * 2 * 2 * 2
    detail = pd.read_csv(result.comparison_csv_path)
    assert set(detail['流量口径']) == set(FLOW_BASES)
    assert set(detail['设计流量 (m³/s)']) == {0.51, 0.54}
    for row in result.comparison_rows:
        key = '钢管' if row['material'] == '钢管' else '球墨铸铁管'
        expected = evaluate_single_diameter(PressurePipeInput(Q=row['flow'], material_key=key, manual_increase_percent=0), row['diameter'])
        assert row['pressure_loss'] == pytest.approx(expected.hf_total_km)
        assert row['pressure_velocity'] == pytest.approx(expected.V_press)
        if row['pressure_loss_lower'] is not None:
            assert row['pressure_loss_lower'] == pytest.approx(expected.hf_total_lower_km)
    assert any(row['status'] == '能力不足' for row in result.comparison_rows)
    assert any(row['status'] == '可形成均匀流' for row in result.comparison_rows)


def test_default_has_no_implied_clearance_standard(tmp_path):
    """默认只显示数值，不把旧净空阈值冒充为工程规范。"""
    config = BatchScanConfig(q_values=np.array([0.1]), slope_denominators=[500],
        diameter_values=np.array([1.0]), materials=['钢管'], output_dir=str(tmp_path),
        output_csv=False, output_pdf_charts=False, output_subplot_png=False)
    result = run_batch_scan(config)
    assert result.comparison_csv_path == ''
    assert all(row['criteria'] == '未设置净空判据' for row in result.comparison_rows)


def test_project_clearance_and_no_unpressurized(tmp_path):
    """显式启用判据才校核；关闭无压对比时不生成比较明细。"""
    config = BatchScanConfig(q_values=np.array([0.1]), slope_denominators=[500],
        diameter_values=np.array([0.8]), materials=['钢管'], output_dir=str(tmp_path),
        output_csv=False, output_pdf_charts=False, output_subplot_png=False, unpr_clearance_height=1.0)
    result = run_batch_scan(config)
    assert all('低于项目设定' in row['criteria'] for row in result.comparison_rows)
    config.slope_denominators = []
    assert run_batch_scan(config).comparison_rows == []


def test_close_flows_have_distinct_charts_and_merged_pdf(tmp_path):
    """相近流量不得在图表分组或文件名中四舍五入合并、覆盖。"""
    from pypdf import PdfReader
    config = BatchScanConfig(q_values=np.array([0.51, 0.54]), slope_denominators=[500, 2000],
        diameter_values=np.array([0.8, 1.2]), materials=['钢管'], output_dir=str(tmp_path))
    result = run_batch_scan(config)
    assert len(result.generated_pngs) == len(set(result.generated_pngs))
    assert any('Q0.51' in path for path in result.generated_pngs)
    assert any('Q0.54' in path for path in result.generated_pngs)
    assert len(PdfReader(result.merged_pdf).pages) == sum(len(PdfReader(path).pages) for path in result.generated_pdfs)
