# -*- coding: utf-8 -*-
"""断面选型约束回归：加大不冲、渡槽输入限值、拱涵净空表。"""

import sys
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "calc_渠系计算算法内核"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

import 明渠设计 as channel
import 渡槽设计 as aqueduct
import 圆拱直墙型暗涵设计 as culvert


@pytest.mark.parametrize("m", [0.0, 1.5])
def test_open_channel_auto_checks_increased_velocity(m):
    result = channel.quick_calculate_trapezoidal(
        5.0, m, 0.014, 2000, 0.1, 1.30, manual_increase_percent=30,
    )
    if result["success"]:
        assert result["velocity_increased_check_passed"] is True
        assert result["V_increased_check"] <= 1.30
    else:
        assert "流速" in result["error_message"]


def test_open_channel_fixed_width_rejects_increased_erosion():
    result = channel.quick_calculate_trapezoidal(
        5.0, 1.5, 0.014, 2000, 0.1, 1.30,
        manual_b=0.836, manual_increase_percent=30,
    )
    assert result["success"] is False
    assert "加大流速" in result["error_message"]


def test_open_channel_preserved_width_reports_failed_check():
    result = channel.quick_calculate_trapezoidal(
        5.0, 1.5, 0.014, 2000, 0.1, 1.30,
        manual_b=0.836, manual_increase_percent=30, preserve_manual_b=True,
    )
    assert result["success"] is True
    assert result["b_design"] == 0.836
    assert result["velocity_increased_check_passed"] is False
    assert result["validation_passed"] is False
    assert any("加大流速" in text for text in result["constraint_warnings"])


@pytest.mark.parametrize("kind", ["u", "rect"])
def test_aqueduct_auto_obeys_both_velocity_conditions(kind):
    calculate = getattr(aqueduct, "quick_calculate_" + kind)
    result = calculate(5.0, 0.014, 2000, 0.1, 1.30, manual_increase_percent=30)
    assert result["success"] is True, result["error_message"]
    assert 0.1 <= result["V_design"] <= 1.30
    assert result["V_increased"] <= 1.30


@pytest.mark.parametrize("kind,geometry", [("u", {"manual_R": 1.33}), ("rect", {"manual_B": 2.54})])
def test_aqueduct_fixed_size_rejects_velocity_limit(kind, geometry):
    calculate = getattr(aqueduct, "quick_calculate_" + kind)
    result = calculate(5.0, 0.014, 2000, 0.1, 1.30, manual_increase_percent=30, **geometry)
    assert result["success"] is False
    assert "流速" in result["error_message"]


@pytest.mark.parametrize("kind", ["u", "rect"])
def test_aqueduct_fixed_size_checks_lower_velocity_limit(kind):
    geometry = {"manual_R": 2.4} if kind == "u" else {"manual_B": 5.0}
    result = getattr(aqueduct, "quick_calculate_" + kind)(
        1.0, 0.014, 3000, 1.5, 3.0, manual_increase_percent=0, **geometry,
    )
    assert result["success"] is False
    assert "设计流速" in result["error_message"]


def test_arch_culvert_rejects_rectangular_freeboard_at_three_meters():
    q_design = 5.467143278905981
    q_increased = 6.143252333542182
    result = culvert.quick_calculate_arch_culvert(
        q_design, 0.014, 2000, 0.1, 100.0, theta_deg=180,
        manual_B=2.0, manual_H_straight=2.0,
        manual_increase_percent=(q_increased / q_design - 1) * 100,
    )
    assert result["success"] is False


@pytest.mark.parametrize("height,required", [(1.0, 0.4), (2.0, 0.5), (3.0, 0.75), (3.01, 0.75), (8.0, 0.75)])
def test_arch_culvert_clearance_table(height, required):
    assert culvert.get_required_freeboard_height_arch(height) == pytest.approx(required)


@pytest.mark.parametrize("kind", ["u", "rect"])
@pytest.mark.parametrize("detail", ["brief", "detail"])
def test_aqueduct_report_rejects_legacy_velocity_violation(kind, detail):
    """旧结果即使保存为成功，报告也不能绕过输入流速限值。"""
    from types import SimpleNamespace
    from app_渠系计算前端.aqueduct.panel import AqueductPanel

    result = getattr(aqueduct, "quick_calculate_" + kind)(
        5.0, 0.014, 2000, 0.1, 100.0, manual_increase_percent=30,
    )
    params = dict(Q=5.0, n=0.014, slope_inv=2000, v_min=0.1, v_max=1.3, use_increase=True)
    dummy = SimpleNamespace(input_params=params, _render_result_html=lambda html: None)
    getattr(AqueductPanel, f"_show_{kind}_{detail}")(dummy, result)
    assert "加大流速不冲校核" in dummy._export_plain_text
    assert "综合验证结果: 未通过" in dummy._export_plain_text


@pytest.mark.parametrize("detail", ["brief", "detail"])
def test_open_channel_report_includes_increased_velocity_in_overall_check(detail):
    from types import SimpleNamespace, MethodType
    from app_渠系计算前端.open_channel.panel import OpenChannelPanel

    result = channel.quick_calculate_trapezoidal(
        5.0, 1.5, 0.014, 2000, 0.1, 1.3, manual_b=0.836,
        manual_increase_percent=30, preserve_manual_b=True,
    )
    params = dict(Q=5.0, m=1.5, n=0.014, slope_inv=2000,
                  v_min=0.1, v_max=1.3, use_increase=True, section_type='梯形')
    dummy = SimpleNamespace(input_params=params, _render_result_html=lambda html: None)
    dummy._get_increase_summary_lines = MethodType(OpenChannelPanel._get_increase_summary_lines, dummy)
    getattr(OpenChannelPanel, f"_show_trapezoid_{detail}")(dummy, result)
    assert "加大流速不冲校核" in dummy._export_plain_text
    assert "综合验证结果: 未通过" in dummy._export_plain_text


def test_velocity_check_does_not_round_away_small_violation():
    from app_渠系计算前端.velocity_validation import velocity_checks

    params = dict(v_min=0.1, v_max=1.3, use_increase=True)
    result = dict(V_design=1.2, V_increased=1.3, V_increased_check=1.3000001)
    design_ok, increased_ok, _ = velocity_checks(params, result)
    assert design_ok and not increased_ok
    params['use_increase'] = False
    assert velocity_checks(params, result)[:2] == (True, True)


def test_appendix_e_table_marks_increased_velocity_violation():
    from app_渠系计算前端.open_channel.appendix_e_table import make_appendix_e_payload

    result = channel.quick_calculate_trapezoidal(
        5.0, 1.5, 0.014, 2000, 0.1, 1.3, manual_increase_percent=30,
    )
    assert result['success'] is True
    schemes = result['appendix_e_schemes']
    assert all('velocity_check_passed' in scheme for scheme in schemes)
    payload = make_appendix_e_payload(schemes, result['b_design'], result['h_design'], 0.1, 1.3)
    assert payload['rows'][0]['statusCode'] == 'warning'
    assert payload['rows'][0]['statusLabel'] == '加大流速不符'


def test_arch_culvert_summary_rechecks_old_rectangular_clearance():
    from app_渠系计算前端.result_summary import _status_group

    group = _status_group('culvert', {'section_type': '圆拱直墙型', 'use_increase': True}, {
        'H_total': 3.0, 'h_increased': 2.45, 'V_increased': 1.4, 'Q_increased': 6.2,
        'freeboard_hgt_inc': 0.55, 'freeboard_pct_inc': 15.0,
        'fb_min_required': 0.5, 'fb_check_passed': True,
    })
    assert next(item for item in group.items if item.label == '净空校核').status == '需注意'


@pytest.mark.parametrize('section_type', ['明渠-梯形', '渡槽-矩形'])
def test_batch_report_includes_increased_velocity_failure(section_type):
    from types import SimpleNamespace, MethodType
    import app_渠系计算前端.batch.panel as batch

    row = [''] * len(batch.INPUT_HEADERS)
    for column, value in ((batch.COL_Q, 5), (batch.COL_N, 0.014), (batch.COL_SLOPE, 2000),
                          (batch.COL_V_MIN, 0.1), (batch.COL_V_MAX, 1.3),
                          (batch.COL_SECTION_TYPE, section_type)):
        row[column] = str(value)
    dummy = SimpleNamespace(_channel_info_lines=lambda values: [])
    dummy._sf = MethodType(batch.BatchPanel._sf, dummy)
    if section_type.startswith('明渠'):
        result = channel.quick_calculate_trapezoidal(5, 1.5, 0.014, 2000, 0.1, 1.3,
                 manual_b=0.836, manual_increase_percent=30, preserve_manual_b=True)
        text = batch.BatchPanel._fmt_mingqu_report(dummy, row, result)
    else:
        result = aqueduct.quick_calculate_rect(5, 0.014, 2000, 0.1, 100, manual_increase_percent=30)
        text = batch.BatchPanel._fmt_ducao_report(dummy, row, result)
    assert '加大流速不冲校核' in text
    assert '综合验证结果: 未通过' in text


@pytest.mark.parametrize("kind,extra", [
    ('u', {}), ('u', {'tie_rod_height': 0.3}),
    ('u', {'v_max': 1.3}), ('u', {'manual_increase_percent': 0}),
    ('rect', {}), ('rect', {'tie_rod_height': 0.3}),
    ('rect', {'v_max': 1.3}), ('rect', {'manual_increase_percent': 0}),
    ('rect', {'chamfer_angle': 45, 'chamfer_length': 0.2}),
    ('rect', {'chamfer_angle': 60, 'chamfer_length': 0.4}),
    ('rect', {'Q': 2000}), ('u', {'Q': 100000}),
])
def test_optimized_aqueduct_matches_full_grid_search(monkeypatch, kind, extra):
    params = dict(Q=5.0, n=0.014, slope_inv=2000, v_min=0.1, v_max=100.0,
                  manual_increase_percent=30)
    params.update(extra)
    calculate = getattr(aqueduct, 'quick_calculate_' + kind)
    optimized = calculate(**params)
    # 关闭跳过候选与缓存，参照仍执行同一求解器及所有工程约束。
    monkeypatch.setattr(aqueduct, '_u_area_lower_bound', lambda radius: -float('inf'))
    monkeypatch.setattr(aqueduct, '_rect_search_start', lambda *args: 50)
    monkeypatch.setattr(aqueduct, 'lru_cache', lambda **kwargs: lambda function: function)
    assert calculate(**params) == optimized
