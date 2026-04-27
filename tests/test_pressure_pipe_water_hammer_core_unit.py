# -*- coding: utf-8 -*-
"""基础水锤验算核心与持久化单元测试。"""

import math
import os
import shutil
import sys
import uuid

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
PRESSURE_ROOT = os.path.join(ROOT, "推求水面线")
if PRESSURE_ROOT not in sys.path:
    sys.path.insert(0, PRESSURE_ROOT)

from managers.pressure_pipe_manager import PressurePipeConfig, PressurePipeManager  # noqa: E402
from core.pressure_pipe_calc import (  # noqa: E402
    GRAVITY,
    WATER_BULK_MODULUS,
    WATER_HAMMER_DISTRIBUTION_SAMPLE_INTERVAL_M,
    WATER_HAMMER_DEFAULT_ALLOWABLE_PRESSURE_MPA,
    WATER_HAMMER_WATER_DENSITY,
    calc_basic_water_hammer,
    calc_distributed_water_hammer_check,
    get_water_hammer_elastic_modulus,
)


def _expected_gbt_wave_speed(diameter_m: float, wall_thickness_m: float, elastic_modulus_pa: float, cp: float = 1.0) -> float:
    """按GB/T 20203-2017水击波速公式计算测试期望值。"""
    return 1425.0 / math.sqrt(
        1.0 + (WATER_BULK_MODULUS / elastic_modulus_pa) * (diameter_m / wall_thickness_m) * cp
    )


def _expected_pressure_head(pressure_mpa: float) -> float:
    """把MPa换算成工程水头。"""
    return pressure_mpa * 1_000_000.0 / (WATER_HAMMER_WATER_DENSITY * GRAVITY)


def test_calc_basic_water_hammer_returns_expected_values_for_direct_closure():
    """直接关阀场景应返回可计算结果。"""
    result = calc_basic_water_hammer(
        length_m=1200.0,
        diameter_m=1.2,
        wall_thickness_m=0.014,
        elastic_modulus_pa=206.0e9,
        velocity_mps=1.8,
        initial_head_m=98.5,
        closing_time_s=1.0,
    )

    expected_a = _expected_gbt_wave_speed(1.2, 0.014, 206.0e9)
    expected_mu = 2.0 * 1200.0 / expected_a
    expected_delta_h = expected_a * 1.8 / GRAVITY

    assert result["status"] == "可计算"
    assert result["reason"] == ""
    assert result["a"] == pytest.approx(expected_a, rel=1e-6)
    assert result["mu"] == pytest.approx(expected_mu, rel=1e-6)
    assert result["ts_to_mu_ratio"] == pytest.approx(1.0 / expected_mu, rel=1e-6)
    assert result["delta_h"] == pytest.approx(expected_delta_h, rel=1e-6)
    assert result["hmax"] == pytest.approx(98.5 + expected_delta_h, rel=1e-6)
    assert result["pipe_coefficient_cp"] == pytest.approx(1.0)
    assert result["wave_speed_formula_source"] == "GB/T 20203-2017 5.1.7.4"
    assert result["gbt_positive_delta_h"] == pytest.approx(expected_delta_h, rel=1e-6)
    assert result["linear_positive_delta_h"] == pytest.approx(expected_delta_h, rel=1e-6)
    assert result["positive_governing_method"] in {"GB/T 20203-2017 式(19)", "双重验算一致"}
    assert result["inputs"]["wall_thickness_m"] == pytest.approx(0.014)
    diagram = result["diagram_type_check"]
    assert diagram["source"] == "图1-3-3"
    assert diagram["positive_region"].startswith("V区")
    assert "直接正水击" in diagram["positive_region"]
    assert diagram["note"] == "仅作图1-3-3对照，不参与控制值计算"


def test_calc_basic_water_hammer_returns_indirect_closure_when_ts_exceeds_phase_time():
    """关闭时间超过水击相时应按线性关阀间接水击计算。"""
    result = calc_basic_water_hammer(
        length_m=200.0,
        diameter_m=1.0,
        wall_thickness_m=0.012,
        elastic_modulus_pa=108.0e9,
        velocity_mps=1.6,
        initial_head_m=88.0,
        closing_time_s=5.0,
    )

    expected_c = _expected_gbt_wave_speed(1.0, 0.012, 108.0e9)
    expected_phase_time = 2.0 * 200.0 / expected_c
    expected_sigma = 200.0 * 1.6 / (GRAVITY * 88.0 * 5.0)
    expected_terminal_zeta = expected_sigma / 2.0 * (
        expected_sigma + math.sqrt(4.0 + expected_sigma ** 2)
    )

    assert result["status"] == "可计算"
    assert result["reason"] == ""
    assert result["a"] > 0
    assert result["phase_time_s"] == pytest.approx(expected_phase_time, rel=1e-6)
    assert result["mu"] == pytest.approx(expected_phase_time, rel=1e-6)
    assert result["sigma"] == pytest.approx(expected_sigma, rel=1e-6)
    assert result["positive_delta_h"] >= expected_terminal_zeta * 88.0 - 1e-6
    assert result["delta_h"] == pytest.approx(result["positive_delta_h"], rel=1e-6)
    assert result["positive_control_type"] in {"第一相正水击", "末相正水击"}
    assert result["hmax"] == pytest.approx(88.0 + result["positive_delta_h"], rel=1e-6)
    diagram = result["diagram_type_check"]
    assert diagram["tau0"] == pytest.approx(1.0)
    assert diagram["mu_tau0"] == pytest.approx(result["section_mu"], rel=1e-6)
    assert diagram["sigma"] == pytest.approx(expected_sigma, rel=1e-6)
    assert diagram["line_sigma"] == pytest.approx(result["section_mu"], rel=1e-6)
    assert diagram["positive_region"] == "II区：第一相正水击"
    assert diagram["negative_region"] in {"III区：负末相水击", "IV区：第一相负水击"}


def test_calc_basic_water_hammer_reports_diagram_region_for_terminal_positive_control():
    """末相正水击控制时应给出图1-3-3的I区对照。"""
    result = calc_basic_water_hammer(
        length_m=200.0,
        diameter_m=1.0,
        wall_thickness_m=0.012,
        elastic_modulus_pa=108.0e9,
        velocity_mps=3.0,
        initial_head_m=50.0,
        closing_time_s=5.0,
    )

    assert result["status"] == "可计算"
    assert result["positive_control_type"] == "末相正水击"
    assert result["negative_control_type"] in {"第一相负水击", "负末相水击"}
    assert result["positive_delta_h"] == pytest.approx(result["delta_h"], rel=1e-6)
    diagram = result["diagram_type_check"]
    assert diagram["positive_region"] == "I区：末相正水击"
    assert "不参与控制值计算" in diagram["note"]


def test_calc_basic_water_hammer_reports_negative_pressure_risk():
    """线性开启负水击后最低压强水头小于0时应标记负压风险。"""
    result = calc_basic_water_hammer(
        length_m=800.0,
        diameter_m=1.0,
        wall_thickness_m=0.02,
        elastic_modulus_pa=206.0e9,
        velocity_mps=2.0,
        initial_head_m=20.0,
        closing_time_s=0.3,
    )

    assert result["status"] == "可计算"
    assert result["negative_delta_h"] > 0
    assert result["hmin"] == pytest.approx(20.0 - result["negative_delta_h"], rel=1e-6)
    assert result["negative_margin_m"] == pytest.approx(result["hmin"], rel=1e-6)
    assert result["negative_pressure_status"] == "有负压风险"
    assert result["negative_control_type"] in {"直接负水击", "第一相负水击", "负末相水击"}


def test_calc_basic_water_hammer_uses_reinforced_pipe_cp_with_a0():
    """钢筋混凝土和PCCP类管材应按a0折减cp后计算波速。"""
    a0 = 0.2
    cp = 1.0 / (1.0 + 0.95 * a0)
    result = calc_basic_water_hammer(
        length_m=500.0,
        diameter_m=1.0,
        wall_thickness_m=0.08,
        elastic_modulus_pa=20.6e9,
        velocity_mps=1.2,
        initial_head_m=80.0,
        closing_time_s=0.5,
        material_key="PCCP管",
        reinforcement_ratio_a0=a0,
    )

    assert result["status"] == "可计算"
    assert result["pipe_coefficient_cp"] == pytest.approx(cp)
    assert result["reinforcement_ratio_a0"] == pytest.approx(a0)
    assert result["a"] == pytest.approx(_expected_gbt_wave_speed(1.0, 0.08, 20.6e9, cp), rel=1e-6)
    assert result["a"] > _expected_gbt_wave_speed(1.0, 0.08, 20.6e9, 1.0)


def test_calc_basic_water_hammer_defaults_cp_when_reinforced_pipe_a0_missing():
    """钢筋混凝土和PCCP类管材缺少a0时应按cp=1继续验算并提示。"""
    result = calc_basic_water_hammer(
        length_m=500.0,
        diameter_m=1.0,
        wall_thickness_m=0.08,
        elastic_modulus_pa=20.6e9,
        velocity_mps=1.2,
        initial_head_m=80.0,
        closing_time_s=0.5,
        material_key="钢筋混凝土管",
    )

    assert result["status"] == "可计算"
    assert "未填写 a0" in result["reason"]
    assert "cp=1" in result["reason"]
    assert result["pipe_coefficient_note"] == "未填写 a0，已按 cp=1 简化计算。"
    assert result["pipe_coefficient_cp"] == pytest.approx(1.0)
    assert result["reinforcement_ratio_a0"] is None
    assert result["requires_reinforcement_ratio_a0"] is True
    assert result["a"] == pytest.approx(_expected_gbt_wave_speed(1.0, 0.08, 20.6e9, 1.0), rel=1e-6)


def test_calc_basic_water_hammer_rejects_negative_a0_for_reinforced_pipe():
    """a0为负值时仍应阻止验算，避免错误配筋参数进入计算。"""
    result = calc_basic_water_hammer(
        length_m=500.0,
        diameter_m=1.0,
        wall_thickness_m=0.08,
        elastic_modulus_pa=20.6e9,
        velocity_mps=1.2,
        initial_head_m=80.0,
        closing_time_s=0.5,
        material_key="PCCP管",
        reinforcement_ratio_a0=-0.1,
    )

    assert result["status"] == "输入缺失"
    assert result["reason"] == "a0 不能为负值"
    assert result["a"] is None
    assert result["pipe_coefficient_cp"] is None


def test_calc_basic_water_hammer_takes_gbt_indirect_when_it_is_larger():
    """Ts>Tt且GB/T式(21)更大时，正水击控制值应取规范式结果。"""
    length = 1000.0
    diameter = 1.0
    wall_thickness = 0.02
    elastic = 206.0e9
    velocity = 1.5
    phase_time = 2.0 * length / _expected_gbt_wave_speed(diameter, wall_thickness, elastic)
    closing_time = 5.0 * phase_time

    result = calc_basic_water_hammer(
        length_m=length,
        diameter_m=diameter,
        wall_thickness_m=wall_thickness,
        elastic_modulus_pa=elastic,
        velocity_mps=velocity,
        initial_head_m=100.0,
        closing_time_s=closing_time,
        material_key="钢管",
    )

    expected_gbt = 2.0 * length * velocity / (GRAVITY * (phase_time + closing_time))
    assert result["status"] == "可计算"
    assert result["phase_time_s"] == pytest.approx(phase_time, rel=1e-6)
    assert result["gbt_positive_delta_h"] == pytest.approx(expected_gbt, rel=1e-6)
    assert result["gbt_positive_delta_h"] > result["linear_positive_delta_h"]
    assert result["positive_delta_h"] == pytest.approx(result["gbt_positive_delta_h"], rel=1e-6)
    assert result["delta_h"] == pytest.approx(result["gbt_positive_delta_h"], rel=1e-6)
    assert result["positive_governing_method"] == "GB/T 20203-2017 式(21)"
    assert result["hmax"] == pytest.approx(100.0 + expected_gbt, rel=1e-6)


def test_calc_basic_water_hammer_takes_linear_indirect_when_it_is_larger():
    """Ts略大于Tt且线性启闭更大时，正水击控制值应取现有理论结果。"""
    length = 1000.0
    diameter = 1.0
    wall_thickness = 0.02
    elastic = 206.0e9
    velocity = 1.5
    phase_time = 2.0 * length / _expected_gbt_wave_speed(diameter, wall_thickness, elastic)
    closing_time = 1.01 * phase_time

    result = calc_basic_water_hammer(
        length_m=length,
        diameter_m=diameter,
        wall_thickness_m=wall_thickness,
        elastic_modulus_pa=elastic,
        velocity_mps=velocity,
        initial_head_m=100.0,
        closing_time_s=closing_time,
        material_key="钢管",
    )

    assert result["status"] == "可计算"
    assert result["linear_positive_delta_h"] > result["gbt_positive_delta_h"]
    assert result["positive_delta_h"] == pytest.approx(result["linear_positive_delta_h"], rel=1e-6)
    assert result["delta_h"] == pytest.approx(result["linear_positive_delta_h"], rel=1e-6)
    assert result["positive_governing_method"] == "线性启闭理论"


def test_calc_basic_water_hammer_reports_missing_inputs():
    """缺少必要输入时应直接返回输入缺失。"""
    result = calc_basic_water_hammer(
        length_m=200.0,
        diameter_m=1.0,
        wall_thickness_m=0.0,
        elastic_modulus_pa=0.0,
        velocity_mps=1.6,
        initial_head_m=None,
        closing_time_s=0.5,
    )

    assert result["status"] == "输入缺失"
    assert "壁厚" in result["reason"]
    assert "弹性模量" in result["reason"]
    assert "H0" in result["reason"]
    assert result["a"] is None
    assert result["mu"] is None


def test_get_water_hammer_elastic_modulus_supports_known_materials_and_aliases():
    """默认弹模应覆盖常见承压管材，并对未知材质返回空值。"""
    assert get_water_hammer_elastic_modulus("钢管") == pytest.approx(206.0e9)
    assert get_water_hammer_elastic_modulus("球墨铸铁管") == pytest.approx(160.0e9)
    assert get_water_hammer_elastic_modulus("硬聚氯乙烯管") == pytest.approx(2.8e9)
    assert get_water_hammer_elastic_modulus("PVC-U") == pytest.approx(2.8e9)
    assert get_water_hammer_elastic_modulus("玻璃钢夹砂管") == pytest.approx(14.7e9)
    assert get_water_hammer_elastic_modulus("PCCP管") == pytest.approx(20.6e9)
    assert get_water_hammer_elastic_modulus("预应力钢筒混凝土管") == pytest.approx(20.6e9)
    assert get_water_hammer_elastic_modulus("钢筋混凝土管") == pytest.approx(20.6e9)
    assert get_water_hammer_elastic_modulus("预应力钢筒混凝土管_n015") == pytest.approx(20.6e9)
    assert get_water_hammer_elastic_modulus("PE管") is not None
    assert get_water_hammer_elastic_modulus("未知材质") is None


def test_calc_basic_water_hammer_exempts_when_ts_meets_gbt_threshold():
    """Ts达到40L/a时应直接按规范免验算，不再给出水击增压。"""
    length = 100.0
    diameter = 1.0
    wall_thickness = 0.02
    elastic = 206.0e9
    wave_speed = _expected_gbt_wave_speed(diameter, wall_thickness, elastic)
    closing_time = 40.0 * length / wave_speed

    result = calc_basic_water_hammer(
        length_m=length,
        diameter_m=diameter,
        wall_thickness_m=wall_thickness,
        elastic_modulus_pa=elastic,
        velocity_mps=1.0,
        initial_head_m=120.0,
        closing_time_s=closing_time,
    )

    assert result["status"] == "可不验算"
    assert result["is_exempt"] is True
    assert result["exemption_threshold_s"] == pytest.approx(closing_time)
    assert result["delta_h"] is None
    assert result["positive_delta_h"] is None
    assert result["negative_delta_h"] is None
    assert result["hmax"] is None
    assert result["hmin"] is None
    assert result["gbt_positive_delta_h"] is None
    assert result["linear_positive_delta_h"] is None
    assert result["positive_governing_method"] == ""
    assert "GB/T 20203-2017 5.1.7.4" in result["reason"]


def test_calc_distributed_water_hammer_check_passes_when_all_points_have_margin():
    """默认分布采样应为5m，并保留起终点。"""
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "pipe-a",
                "start_station_m": 0.0,
                "end_station_m": 10.0,
                "diameter_m": 1.0,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 0.1,
            }
        ],
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 100.0},
            {"station_m": 10.0, "elevation_m": 100.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 120.0},
            {"station_m": 10.0, "water_level_m": 120.0},
        ],
        wall_thickness_m=0.02,
        closing_time_s=0.01,
    )

    expected_a = _expected_gbt_wave_speed(1.0, 0.02, 206.0e9)
    expected_delta_h = expected_a * 0.1 / GRAVITY
    expected_allow_head = _expected_pressure_head(1.0)

    assert WATER_HAMMER_DISTRIBUTION_SAMPLE_INTERVAL_M == pytest.approx(5.0)
    assert WATER_HAMMER_DEFAULT_ALLOWABLE_PRESSURE_MPA == pytest.approx(1.0)
    assert result["status"] == "通过"
    assert result["inputs"]["sample_interval_m"] == pytest.approx(5.0)
    assert result["inputs"]["allowable_pressure_mpa"] == pytest.approx(1.0)
    assert result["pressure_allow_head_m"] == pytest.approx(expected_allow_head, rel=1e-6)
    assert result["pressure_check_basis"] == "pipe_bottom"
    assert result["delta_h"] == pytest.approx(expected_delta_h, rel=1e-6)
    assert result["sample_count"] == 3
    assert [item["station_m"] for item in result["details"]] == pytest.approx([0.0, 5.0, 10.0])
    assert result["exceed_count"] == 0
    assert result["min_margin_m"] == pytest.approx(expected_allow_head - (120.0 + expected_delta_h - 99.5), rel=1e-6)
    assert result["critical_point"]["station_m"] == pytest.approx(0.0)
    assert result["critical_point"]["h_st_m"] == pytest.approx(120.0)
    assert result["critical_point"]["hmax_m"] == pytest.approx(120.0 + expected_delta_h, rel=1e-6)
    assert result["critical_point"]["pipe_bottom_elevation_m"] == pytest.approx(99.5)
    assert result["critical_point"]["pressure_head_max_m"] == pytest.approx(120.0 + expected_delta_h - 99.5, rel=1e-6)
    assert result["critical_point"]["pressure_margin_m"] == pytest.approx(result["min_margin_m"], rel=1e-6)
    assert result["pipe_coefficient_cp"] == pytest.approx(1.0)
    assert result["wave_speed_formula_source"] == "GB/T 20203-2017 5.1.7.4"
    assert result["gbt_positive_delta_h"] == pytest.approx(result["positive_delta_h"], rel=1e-6)
    assert result["linear_positive_delta_h"] == pytest.approx(result["positive_delta_h"], rel=1e-6)


def test_calc_distributed_water_hammer_check_uses_custom_allowable_pressure_for_pipe_bottom():
    """允许压力应按MPa换算成管底承压水头并参与判定。"""
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "pipe-a",
                "start_station_m": 0.0,
                "end_station_m": 10.0,
                "diameter_m": 1.0,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 0.1,
            }
        ],
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 100.0},
            {"station_m": 10.0, "elevation_m": 100.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 160.0},
            {"station_m": 10.0, "water_level_m": 160.0},
        ],
        wall_thickness_m=0.02,
        closing_time_s=0.01,
        allowable_pressure_mpa=0.6,
        sample_interval_m=10.0,
    )

    detail = result["details"][0]
    expected_allow_head = _expected_pressure_head(0.6)

    assert result["status"] == "不通过"
    assert result["inputs"]["allowable_pressure_mpa"] == pytest.approx(0.6)
    assert result["allowable_pressure_mpa"] == pytest.approx(0.6)
    assert result["pressure_allow_head_m"] == pytest.approx(expected_allow_head, rel=1e-6)
    assert detail["hmax_m"] == pytest.approx(detail["h_st_m"] + detail["positive_delta_h_m"], rel=1e-6)
    assert detail["pressure_head_max_m"] == pytest.approx(detail["hmax_m"] - detail["pipe_bottom_elevation_m"], rel=1e-6)
    assert detail["pressure_margin_m"] == pytest.approx(expected_allow_head - detail["pressure_head_max_m"], rel=1e-6)
    assert detail["margin_m"] == pytest.approx(detail["pressure_margin_m"], rel=1e-6)
    assert detail["status"] == "承压超限"
    assert result["exceed_count"] > 0


def test_calc_distributed_water_hammer_check_checks_negative_pressure_at_pipe_top():
    """负压/满管风险应按管顶最低压力水头判断，比旧管中心口径更严格。"""
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "pipe-a",
                "start_station_m": 0.0,
                "end_station_m": 10.0,
                "diameter_m": 4.0,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 0.02,
            }
        ],
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 100.0},
            {"station_m": 10.0, "elevation_m": 100.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 102.5},
            {"station_m": 10.0, "water_level_m": 102.5},
        ],
        wall_thickness_m=0.02,
        closing_time_s=0.001,
        sample_interval_m=10.0,
    )

    detail = result["negative_critical_point"]
    old_centerline_margin = detail["hmin_m"] - detail["centerline_elevation_m"]

    assert old_centerline_margin > 0
    assert detail["top_min_pressure_head_m"] == pytest.approx(
        detail["hmin_m"] - detail["pipe_top_elevation_m"],
        rel=1e-6,
    )
    assert detail["negative_margin_m"] == pytest.approx(detail["top_min_pressure_head_m"], rel=1e-6)
    assert detail["negative_margin_m"] < 0
    assert detail["negative_status"] == "管顶负压风险"
    assert result["status"] == "不通过"


def test_calc_distributed_water_hammer_check_uses_equivalent_line_parameters():
    """整线类型参数应按L、am、vm等价管计算，局部校核仍用采样点所属成员尺寸。"""
    members = [
        {
            "key": "pipe-a",
            "start_station_m": 0.0,
            "end_station_m": 10.0,
            "diameter_m": 1.0,
            "elastic_modulus_pa": 206.0e9,
            "velocity_mps": 1.0,
        },
        {
            "key": "pipe-b",
            "start_station_m": 10.0,
            "end_station_m": 30.0,
            "diameter_m": 0.8,
            "elastic_modulus_pa": 2.8e9,
            "velocity_mps": 2.0,
        },
    ]
    wall_thickness = 0.02
    a1 = _expected_gbt_wave_speed(1.0, wall_thickness, 206.0e9)
    a2 = _expected_gbt_wave_speed(0.8, wall_thickness, 2.8e9)
    expected_l = 30.0
    expected_am = expected_l / (10.0 / a1 + 20.0 / a2)
    expected_vm = (10.0 * 1.0 + 20.0 * 2.0) / expected_l
    expected_h0 = 200.0 - 100.0
    expected_rho = expected_am * expected_vm / (2.0 * GRAVITY * expected_h0)
    expected_sigma = expected_l * expected_vm / (GRAVITY * expected_h0 * 0.05)

    result = calc_distributed_water_hammer_check(
        members=members,
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 100.0},
            {"station_m": 30.0, "elevation_m": 100.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 200.0},
            {"station_m": 30.0, "water_level_m": 200.0},
        ],
        wall_thickness_m=wall_thickness,
        closing_time_s=0.05,
        sample_interval_m=10.0,
    )

    pipe_b_detail = next(item for item in result["details"] if item["member_key"] == "pipe-b")

    assert result["equivalent_length_m"] == pytest.approx(expected_l)
    assert result["equivalent_wave_speed_mps"] == pytest.approx(expected_am, rel=1e-6)
    assert result["equivalent_velocity_mps"] == pytest.approx(expected_vm, rel=1e-6)
    assert result["section_mu"] == pytest.approx(expected_rho, rel=1e-6)
    assert result["sigma"] == pytest.approx(expected_sigma, rel=1e-6)
    assert pipe_b_detail["section_mu"] == pytest.approx(expected_rho, rel=1e-6)
    assert pipe_b_detail["sigma"] == pytest.approx(expected_sigma, rel=1e-6)
    assert pipe_b_detail["pipe_bottom_elevation_m"] == pytest.approx(99.6)
    assert pipe_b_detail["pressure_head_max_m"] == pytest.approx(
        pipe_b_detail["hmax_m"] - 99.6,
        rel=1e-6,
    )


def test_calc_distributed_water_hammer_check_keeps_breakpoints_with_5m_default():
    """5m基础采样仍应强制保留纵断面折点、表3水位点和成员分界点。"""
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "pipe-a",
                "start_station_m": 0.0,
                "end_station_m": 10.0,
                "diameter_m": 1.0,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 0.1,
            },
            {
                "key": "pipe-b",
                "start_station_m": 10.0,
                "end_station_m": 20.0,
                "diameter_m": 1.0,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 0.1,
            },
        ],
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 100.0},
            {"station_m": 2.5, "elevation_m": 100.5},
            {"station_m": 20.0, "elevation_m": 100.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 120.0},
            {"station_m": 7.5, "water_level_m": 119.5},
            {"station_m": 20.0, "water_level_m": 120.0},
        ],
        wall_thickness_m=0.02,
        closing_time_s=0.01,
    )

    stations = sorted({round(float(item["station_m"]), 6) for item in result["details"]})
    assert result["status"] == "通过"
    assert result["inputs"]["sample_interval_m"] == pytest.approx(5.0)
    assert stations == pytest.approx([0.0, 2.5, 5.0, 7.5, 10.0, 15.0, 20.0])


def test_calc_distributed_water_hammer_check_fails_at_lowest_margin_point():
    """任一采样点余量小于0时应判定不通过并给出最危险点。"""
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "pipe-a",
                "start_station_m": 0.0,
                "end_station_m": 10.0,
                "diameter_m": 1.0,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 1.0,
            }
        ],
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 100.0},
            {"station_m": 10.0, "elevation_m": 110.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 210.0},
            {"station_m": 10.0, "water_level_m": 210.0},
        ],
        wall_thickness_m=0.02,
        closing_time_s=0.01,
        sample_interval_m=5.0,
    )

    assert result["status"] == "不通过"
    assert result["exceed_count"] >= 1
    assert result["critical_point"]["station_m"] == pytest.approx(0.0)
    assert result["critical_point"]["margin_m"] == pytest.approx(result["min_margin_m"])
    assert result["critical_point"]["status"] == "承压超限"


def test_calc_distributed_water_hammer_check_uses_most_dangerous_member_delta_h():
    """混合参数段应逐成员计算并取最大附加水头校核整段。"""
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "pipe-a",
                "start_station_m": 0.0,
                "end_station_m": 10.0,
                "diameter_m": 1.0,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 0.5,
            },
            {
                "key": "pipe-b",
                "start_station_m": 10.0,
                "end_station_m": 20.0,
                "diameter_m": 0.5,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 2.0,
            },
        ],
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 100.0},
            {"station_m": 20.0, "elevation_m": 100.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 400.0},
            {"station_m": 20.0, "water_level_m": 400.0},
        ],
        wall_thickness_m=0.02,
        closing_time_s=0.01,
        allowable_pressure_mpa=5.0,
        sample_interval_m=10.0,
    )

    member_deltas = [item["delta_h"] for item in result["member_results"]]
    assert result["status"] == "通过"
    assert result["delta_h"] == pytest.approx(max(member_deltas), rel=1e-6)
    assert result["equivalent_velocity_mps"] == pytest.approx(1.25)
    pipe_b_boundary = next(
        item for item in result["details"]
        if item["station_m"] == pytest.approx(10.0) and item["member_key"] == "pipe-b"
    )
    assert pipe_b_boundary["pipe_top_elevation_m"] == pytest.approx(100.25)
    assert pipe_b_boundary["diameter_m"] == pytest.approx(0.5)
    assert pipe_b_boundary["velocity_mps"] == pytest.approx(2.0)
    assert pipe_b_boundary["a"] > 0


def test_calc_distributed_water_hammer_check_uses_member_cp_and_a0_independently():
    """混合整线中每个成员应独立使用自己的cp、a0和波速。"""
    a0 = 0.2
    pccp_cp = 1.0 / (1.0 + 0.95 * a0)
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "steel",
                "start_station_m": 0.0,
                "end_station_m": 10.0,
                "diameter_m": 1.0,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 0.1,
                "material_key": "钢管",
            },
            {
                "key": "pccp",
                "start_station_m": 10.0,
                "end_station_m": 20.0,
                "diameter_m": 1.0,
                "elastic_modulus_pa": 20.6e9,
                "velocity_mps": 0.1,
                "material_key": "PCCP管",
                "reinforcement_ratio_a0": a0,
            },
        ],
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 100.0},
            {"station_m": 20.0, "elevation_m": 100.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 400.0},
            {"station_m": 20.0, "water_level_m": 400.0},
        ],
        wall_thickness_m=0.08,
        closing_time_s=0.01,
        allowable_pressure_mpa=5.0,
        sample_interval_m=10.0,
    )

    members = {item["key"]: item for item in result["member_results"]}
    pccp_detail = next(item for item in result["details"] if item["member_key"] == "pccp")

    assert result["status"] == "通过"
    assert members["steel"]["pipe_coefficient_cp"] == pytest.approx(1.0)
    assert members["pccp"]["pipe_coefficient_cp"] == pytest.approx(pccp_cp)
    assert members["pccp"]["reinforcement_ratio_a0"] == pytest.approx(a0)
    assert members["pccp"]["a"] == pytest.approx(_expected_gbt_wave_speed(1.0, 0.08, 20.6e9, pccp_cp), rel=1e-6)
    assert pccp_detail["pipe_coefficient_cp"] == pytest.approx(pccp_cp)
    assert pccp_detail["reinforcement_ratio_a0"] == pytest.approx(a0)
    assert pccp_detail["gbt_positive_delta_h_m"] is not None
    assert pccp_detail["linear_positive_delta_h_m"] is not None
    assert pccp_detail["positive_governing_method"] in {
        "GB/T 20203-2017 式(19)",
        "GB/T 20203-2017 式(21)",
        "线性启闭理论",
        "双重验算一致",
    }


def test_calc_distributed_water_hammer_check_defaults_member_cp_when_a0_missing():
    """整线中PCCP或钢筋混凝土成员缺少a0时应按cp=1继续验算并提示。"""
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "pccp",
                "start_station_m": 0.0,
                "end_station_m": 10.0,
                "diameter_m": 1.0,
                "elastic_modulus_pa": 20.6e9,
                "velocity_mps": 1.0,
                "material_key": "PCCP管",
            }
        ],
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 100.0},
            {"station_m": 10.0, "elevation_m": 100.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 400.0},
            {"station_m": 10.0, "water_level_m": 400.0},
        ],
        wall_thickness_m=0.08,
        closing_time_s=0.01,
        sample_interval_m=10.0,
    )

    assert result["status"] != "数据缺失"
    assert "未填写 a0" in result["reason"]
    assert "cp=1" in result["reason"]
    assert result["pipe_coefficient_note"] == "未填写 a0，已按 cp=1 简化计算。"
    assert len(result["member_results"]) == 1
    assert result["member_results"][0]["pipe_coefficient_cp"] == pytest.approx(1.0)
    assert result["member_results"][0]["reinforcement_ratio_a0"] is None
    assert result["member_results"][0]["pipe_coefficient_note"] == "未填写 a0，已按 cp=1 简化计算。"


def test_calc_distributed_water_hammer_check_handles_indirect_closure_when_ts_exceeds_phase_time():
    """关阀时间大于水击相时时仍应按线性关阀给出分布判定。"""
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "pipe-a",
                "start_station_m": 0.0,
                "end_station_m": 10.0,
                "diameter_m": 1.0,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 1.0,
            }
        ],
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 100.0},
            {"station_m": 10.0, "elevation_m": 100.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 230.0},
            {"station_m": 10.0, "water_level_m": 230.0},
        ],
        wall_thickness_m=0.02,
        closing_time_s=0.05,
        allowable_pressure_mpa=3.0,
        sample_interval_m=1.0,
    )

    assert result["status"] == "通过"
    assert result["details"]
    assert result["phase_time_s"] > 0
    assert result["positive_delta_h"] == pytest.approx(result["delta_h"], rel=1e-6)
    assert result["positive_control_type"] in {"第一相正水击", "末相正水击"}
    assert result["negative_delta_h"] > 0
    assert result["negative_pressure_risk_count"] == 0
    diagram = result["diagram_type_check"]
    assert diagram["source"] == "图1-3-3"
    assert diagram["positive_region"] in {"I区：末相正水击", "II区：第一相正水击"}
    assert result["details"][0]["diagram_type_check"]["source"] == "图1-3-3"


def test_calc_distributed_water_hammer_check_exempts_multi_member_route_at_gbt_threshold():
    """多成员整线Ts达到40倍传播时间累计值时应免验算且不生成明细。"""
    members = [
        {
            "key": "pipe-a",
            "start_station_m": 0.0,
            "end_station_m": 10.0,
            "diameter_m": 1.0,
            "elastic_modulus_pa": 206.0e9,
            "velocity_mps": 1.0,
        },
        {
            "key": "pipe-b",
            "start_station_m": 10.0,
            "end_station_m": 25.0,
            "diameter_m": 0.8,
            "elastic_modulus_pa": 2.8e9,
            "velocity_mps": 0.8,
        },
    ]
    wall_thickness = 0.02
    member_speeds = [
        _expected_gbt_wave_speed(float(member["diameter_m"]), wall_thickness, float(member["elastic_modulus_pa"]))
        for member in members
    ]
    closing_time = 40.0 * sum(
        abs(float(member["end_station_m"]) - float(member["start_station_m"])) / speed
        for member, speed in zip(members, member_speeds)
    )

    result = calc_distributed_water_hammer_check(
        members=members,
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 100.0},
            {"station_m": 25.0, "elevation_m": 100.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 120.0},
            {"station_m": 25.0, "water_level_m": 230.0},
        ],
        wall_thickness_m=wall_thickness,
        closing_time_s=closing_time,
        sample_interval_m=1.0,
    )

    assert result["status"] == "可不验算"
    assert result["is_exempt"] is True
    assert result["details"] == []
    assert result["sample_count"] == 0
    assert result["a_min"] == pytest.approx(min(member_speeds), rel=1e-6)
    assert result["a_max"] == pytest.approx(max(member_speeds), rel=1e-6)
    assert result["phase_time_s"] == pytest.approx(2.0 * sum(
        abs(float(member["end_station_m"]) - float(member["start_station_m"])) / speed
        for member, speed in zip(members, member_speeds)
    ))
    assert result["exemption_threshold_s"] == pytest.approx(closing_time)
    assert result["delta_h"] is None
    assert result["positive_delta_h"] is None
    assert result["negative_delta_h"] is None
    assert result["gbt_positive_delta_h"] is None
    assert result["linear_positive_delta_h"] is None
    assert result["positive_governing_method"] == ""


def test_calc_distributed_water_hammer_check_marks_failed_for_negative_pressure_risk():
    """任一采样点出现负压风险时整线结论应为不通过。"""
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "pipe-a",
                "start_station_m": 0.0,
                "end_station_m": 10.0,
                "diameter_m": 1.0,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 2.0,
            }
        ],
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 100.0},
            {"station_m": 10.0, "elevation_m": 100.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 110.0},
            {"station_m": 10.0, "water_level_m": 110.0},
        ],
        wall_thickness_m=0.02,
        closing_time_s=0.001,
        sample_interval_m=5.0,
    )

    assert result["status"] == "不通过"
    assert result["negative_pressure_risk_count"] > 0
    assert result["min_negative_margin_m"] < 0
    assert result["negative_critical_point"]["negative_status"] == "管顶负压风险"


def test_calc_distributed_water_hammer_check_reports_missing_profile_data():
    """缺少纵断面或水位线数据时应返回数据缺失。"""
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "pipe-a",
                "start_station_m": 0.0,
                "end_station_m": 10.0,
                "diameter_m": 1.0,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 1.0,
            }
        ],
        centerline_nodes=[],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 230.0},
            {"station_m": 10.0, "water_level_m": 230.0},
        ],
        wall_thickness_m=0.02,
        closing_time_s=0.01,
    )

    assert result["status"] == "数据缺失"
    assert "纵断面" in result["reason"]


def test_calc_distributed_water_hammer_check_accepts_millimeter_endpoint_gap():
    """纵断面端点与成员端点只有毫米内尾差时应夹紧计算。"""
    route_end = 10501.426
    imported_end = 10501.4257607283
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "pipe-a",
                "start_station_m": 0.0,
                "end_station_m": route_end,
                "diameter_m": 0.4,
                "elastic_modulus_pa": 1.4e9,
                "velocity_mps": 0.7958,
            }
        ],
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 380.0},
            {"station_m": imported_end, "elevation_m": 379.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 430.0},
            {"station_m": imported_end, "water_level_m": 429.0},
        ],
        wall_thickness_m=0.1,
        closing_time_s=60.0,
        sample_interval_m=5000.0,
    )

    assert result["status"] != "数据缺失"
    assert "覆盖不足" not in result["reason"]
    assert result["sample_count"] > 0
    end_detail = [item for item in result["details"] if item["station_m"] == pytest.approx(route_end)][0]
    assert end_detail["centerline_elevation_m"] == pytest.approx(379.0)
    assert end_detail["water_level_m"] == pytest.approx(429.0)


def test_calc_distributed_water_hammer_check_reports_true_endpoint_gap_with_range():
    """真正超出覆盖容差时应说明采样桩号和覆盖范围。"""
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "pipe-a",
                "start_station_m": 0.0,
                "end_station_m": 10501.428,
                "diameter_m": 0.4,
                "elastic_modulus_pa": 1.4e9,
                "velocity_mps": 0.7958,
            }
        ],
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 380.0},
            {"station_m": 10501.4257607283, "elevation_m": 379.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 430.0},
            {"station_m": 10501.4257607283, "water_level_m": 429.0},
        ],
        wall_thickness_m=0.1,
        closing_time_s=60.0,
        sample_interval_m=5000.0,
    )

    assert result["status"] == "数据缺失"
    assert "10501.428" in result["reason"]
    assert "0.000" in result["reason"]
    assert "10501.426" in result["reason"]


def test_calc_distributed_water_hammer_check_reports_zero_length_member_plainly():
    """零长度成员应给出面向用户的桩号提示。"""
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "anchor",
                "start_station_m": 0.0,
                "end_station_m": 0.0,
                "diameter_m": 1.0,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 1.0,
            }
        ],
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 100.0},
            {"station_m": 10.0, "elevation_m": 100.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 230.0},
            {"station_m": 10.0, "water_level_m": 230.0},
        ],
        wall_thickness_m=0.02,
        closing_time_s=0.01,
    )

    assert result["status"] == "数据缺失"
    assert "起终点相同" in result["reason"]
    assert "成员长度必须大于0" not in result["reason"]


def test_calc_distributed_water_hammer_check_checks_upstream_pipe_top_at_boundary():
    """成员分界点应同时校核上游大管径，避免漏掉更高管顶。"""
    result = calc_distributed_water_hammer_check(
        members=[
            {
                "key": "wide-upstream",
                "start_station_m": 0.0,
                "end_station_m": 10.0,
                "diameter_m": 4.0,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 0.05,
            },
            {
                "key": "narrow-downstream",
                "start_station_m": 10.0,
                "end_station_m": 20.0,
                "diameter_m": 1.0,
                "elastic_modulus_pa": 206.0e9,
                "velocity_mps": 0.005,
            },
        ],
        centerline_nodes=[
            {"station_m": 0.0, "elevation_m": 100.0},
            {"station_m": 20.0, "elevation_m": 100.0},
        ],
        water_level_nodes=[
            {"station_m": 0.0, "water_level_m": 105.0},
            {"station_m": 20.0, "water_level_m": 105.0},
        ],
        wall_thickness_m=0.02,
        closing_time_s=0.001,
        sample_interval_m=10.0,
    )

    boundary_rows = [item for item in result["details"] if item["station_m"] == pytest.approx(10.0)]
    assert result["status"] in {"通过", "不通过"}
    assert len(boundary_rows) == 2
    assert {item["member_key"] for item in boundary_rows} == {"wide-upstream", "narrow-downstream"}
    assert any(item["pipe_top_elevation_m"] == pytest.approx(102.0) for item in boundary_rows)


def test_pressure_pipe_manager_round_trip_preserves_basic_water_hammer_fields():
    """管理器应持久化壁厚和基础水锤结果。"""
    base_dir = os.path.join(os.path.dirname(__file__), "_tmp_test_data")
    os.makedirs(base_dir, exist_ok=True)
    case_dir = os.path.join(base_dir, f"ppipe_{uuid.uuid4().hex}")
    os.makedirs(case_dir, exist_ok=True)
    project_path = os.path.join(case_dir, "demo.qxproj")

    try:
        manager = PressurePipeManager(project_path)
        cfg = PressurePipeConfig(
            name="流量段1 第3行有压管道",
            Q=1.6,
            D=1.2,
            material_key="钢管",
            pipe_velocity=1.42,
            plan_total_length=180.0,
            wall_thickness_m=0.016,
            water_hammer_basic={
                "status": "可计算",
                "reason": "",
                "a": 1032.5,
                "mu": 0.3487,
                "ts_to_mu_ratio": 0.86,
                "delta_h": 149.4,
                "hmax": 252.7,
                "inputs": {
                    "length_m": 180.0,
                    "diameter_m": 1.2,
                    "wall_thickness_m": 0.016,
                    "elastic_modulus_pa": 206.0e9,
                    "velocity_mps": 1.42,
                    "initial_head_m": 103.3,
                    "closing_time_s": 0.3,
                },
            },
        )

        manager.set_pipe_config("flow1-row3", cfg)

        loaded = manager.get_pipe_config("flow1-row3")
        assert loaded is not None
        assert loaded.wall_thickness_m == pytest.approx(0.016)
        assert loaded.water_hammer_basic["status"] == "可计算"
        assert loaded.water_hammer_basic["inputs"]["closing_time_s"] == pytest.approx(0.3)

        reloaded = PressurePipeManager(project_path).get_pipe_config("flow1-row3")
        assert reloaded is not None
        assert reloaded.wall_thickness_m == pytest.approx(0.016)
        assert reloaded.water_hammer_basic["hmax"] == pytest.approx(252.7)
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)
