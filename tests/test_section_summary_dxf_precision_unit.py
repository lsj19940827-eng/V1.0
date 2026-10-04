"""断面汇总 DXF 的实际文字、合并单元格及列宽精度回归。"""

import copy
import importlib
import re
from types import SimpleNamespace

import ezdxf
import pytest

summary = importlib.import_module('calc_渠系计算算法内核.生成断面汇总表')


def _texts(doc):
    """读取最终写入图纸的文字，兼容上下标多行文字。"""
    return [e.dxf.text if e.dxftype() == 'TEXT' else e.plain_text()
            for e in doc.modelspace().query('TEXT MTEXT')]


def test_dxf_table_rounds_screenshot_values_and_sizes_columns_from_display(tmp_path):
    """两张截图的数据、合并流量及特殊列精度在落盘后同时正确。"""
    headers = [('流量段', None), ('设计流量', 'm³/s'), ('糙率', None),
               ('设计水深H₁', 'm'), ('加大水深H₂', 'm'), ('设计流速', 'm/s'),
               ('直径DN', 'mm'), ('隧洞座数', None), ('隧洞长度（km）', None)]
    rows = [
        ['001', 2.88 * 1.25, 0.014, 1.541898106689453, 1.87, 0.9341829324344467, 1400, 2, 0.123],
        ['001', 2.88 * 1.25, 0.014, 1.5410743545426986, 1.84, 0.9343626800968099, 1400, 2, 0.123],
    ]
    original = copy.deepcopy(rows)
    shown = [['001', '3.60', '0.014', '1.54', '1.87', '0.93', '1400', '2', '0.123'],
             ['001', '3.60', '0.014', '1.54', '1.84', '0.93', '1400', '2', '0.123']]
    assert summary._dxf_auto_col_widths(headers, rows) == summary._dxf_auto_col_widths(headers, shown)
    doc = ezdxf.new('R2010')
    summary._dxf_draw_table(doc.modelspace(), 0, 0, '精度验证', headers, [1] * len(headers),
                            rows, merge_groups=[([0, 1], 2)])
    path = tmp_path / 'precision.dxf'
    doc.saveas(path)
    restored = ezdxf.readfile(path)
    texts = _texts(restored)
    assert texts.count('3.60') == 1
    assert texts.count('1.54') == texts.count('0.93') == 2
    assert {'001', '0.014', '1400', '2', '0.123', '1.87', '1.84'} <= set(texts)
    assert not any(re.search(r'\d+\.\d{5,}', text) for text in texts)
    assert not restored.audit().has_errors
    assert rows == original


@pytest.mark.parametrize('key,compute,defaults', [
    ('rect_channel', 'compute_rect_channel', '_default_segments_rect_channel'),
    ('trap_channel', 'compute_trapezoid_channel', '_default_segments_trap_channel'),
    ('u_channel', 'compute_u_channel', '_default_segments_u_channel'),
    ('tunnel_arch', 'compute_tunnel', '_default_segments_tunnel'),
    ('tunnel_circular', 'compute_tunnel_circular', '_default_segments_tunnel_circular'),
    ('tunnel_flat_bottom_circular', 'compute_tunnel_flat_bottom_circular', '_default_segments_tunnel_flat_bottom_circular'),
    ('tunnel_horseshoe', 'compute_tunnel_horseshoe', '_default_segments_tunnel_horseshoe'),
    ('aqueduct_u', 'compute_aqueduct_u', '_default_segments_aqueduct'),
    ('aqueduct_rect', 'compute_aqueduct_rect', '_default_segments_aqueduct_rect'),
    ('rect_culvert', 'compute_rect_culvert', '_default_segments_rect_culvert'),
    ('rect_culvert_arch', 'compute_rect_culvert_arch', '_default_segments_rect_culvert_arch'),
    ('circular_channel', 'compute_circular_pipe', '_default_segments_circular_pipe'),
    ('siphon', 'compute_siphon', '_default_segments_siphon'),
    ('pressure_pipe', 'compute_pressure_pipe', '_default_segments_pressure_pipe'),
])
def test_all_summary_families_write_short_numbers_without_changing_results(key, compute, defaults):
    """各类表统一通过最终写字路径，不在计算结果字典中提前舍入。"""
    data = getattr(summary, compute)(getattr(summary, defaults)()[:1])
    if isinstance(data, tuple):
        data = data[0]
    original = copy.deepcopy(data)
    title, headers, widths, rows, merge = summary._DXF_BUILDERS[key](data)
    doc = ezdxf.new('R2010')
    summary._dxf_draw_table(doc.modelspace(), 0, 0, title, headers, widths, rows, merge)
    texts = _texts(doc)
    assert not any(re.fullmatch(r'-?\d+\.\d{5,}', text) for text in texts)
    assert data == original


def test_standalone_and_combined_summary_exports_use_the_same_display(tmp_path):
    """单独导出和合并导出的真实公共路径均不能带出长小数。"""
    from app_渠系计算前端.water_profile import cad_tools

    segment = dict(name='第一流量段', Q=2.88, B=2.0, n=0.014, slope_inv=3000)
    path = tmp_path / 'standalone.dxf'
    summary.generate_dxf(str(path), rect_channel_segs=[segment], table_order=['rect_channel'])
    standalone = ezdxf.readfile(path)
    node = SimpleNamespace(is_transition=False, is_auto_inserted_channel=False,
                           is_inverted_siphon=False, is_pressure_pipe=False,
                           structure_type=SimpleNamespace(value='明渠-矩形'), name='',
                           flow_section='1', flow=2.88, roughness=0.014, slope_i=1/3000,
                           section_params={'B': 2.0, 'm': 0.0}, water_depth=1.5410743545426986,
                           velocity=0.9343626800968099, structure_height=2.504)
    doc = ezdxf.new('R2010')
    cad_tools._draw_section_summary_on_msp(SimpleNamespace(), doc.modelspace(), [node], None,
                                         {'siphon': [], 'pressure_pipe': []}, 0, 'SUMMARY')
    combined_path = tmp_path / 'combined.dxf'
    doc.saveas(combined_path)
    for result in [standalone, ezdxf.readfile(combined_path)]:
        texts = _texts(result)
        assert '1.54' in texts and '0.93' in texts and '2.88' in texts
        assert not any(re.fullmatch(r'-?\d+\.\d{5,}', text) for text in texts)
        assert not result.audit().has_errors
