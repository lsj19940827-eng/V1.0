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
    calc_basic_water_hammer,
    calc_distributed_water_hammer_check,
    get_water_hammer_elastic_modulus,
)


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

    expected_a = 1425.0 / math.sqrt(1.0 + (WATER_BULK_MODULUS / 206.0e9) * (1.2 / 0.014))
    expected_mu = 2.0 * 1200.0 / expected_a
    expected_delta_h = expected_a * 1.8 / GRAVITY

    assert result["status"] == "可计算"
    assert result["reason"] == ""
    assert result["a"] == pytest.approx(expected_a, rel=1e-6)
    assert result["mu"] == pytest.approx(expected_mu, rel=1e-6)
    assert result["ts_to_mu_ratio"] == pytest.approx(1.0 / expected_mu, rel=1e-6)
    assert result["delta_h"] == pytest.approx(expected_delta_h, rel=1e-6)
    assert result["hmax"] == pytest.approx(98.5 + expected_delta_h, rel=1e-6)
    assert result["inputs"]["wall_thickness_m"] == pytest.approx(0.014)


def test_calc_basic_water_hammer_marks_not_applicable_when_ts_exceeds_mu():
    """关闭时间超过水锤相时应标记为不适用。"""
    result = calc_basic_water_hammer(
        length_m=200.0,
        diameter_m=1.0,
        wall_thickness_m=0.012,
        elastic_modulus_pa=108.0e9,
        velocity_mps=1.6,
        initial_head_m=88.0,
        closing_time_s=5.0,
    )

    assert result["status"] == "不适用"
    assert "Ts" in result["reason"]
    assert result["a"] > 0
    assert result["mu"] > 0
    assert result["delta_h"] is None
    assert result["hmax"] is None


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
    assert "Hc" in result["reason"]
    assert result["a"] is None
    assert result["mu"] is None


def test_get_water_hammer_elastic_modulus_supports_known_materials_and_aliases():
    """默认弹模应覆盖常见承压管材，并对未知材质返回空值。"""
    assert get_water_hammer_elastic_modulus("钢管") == pytest.approx(206.0e9)
    assert get_water_hammer_elastic_modulus("球墨铸铁管") == pytest.approx(108.0e9)
    assert get_water_hammer_elastic_modulus("玻璃钢夹砂管") == pytest.approx(8.728e9)
    assert get_water_hammer_elastic_modulus("预应力钢筒混凝土管_n015") == pytest.approx(20.6e9)
    assert get_water_hammer_elastic_modulus("PE管") is not None
    assert get_water_hammer_elastic_modulus("未知材质") is None


def test_calc_distributed_water_hammer_check_passes_when_all_points_have_margin():
    """全线采样点余量均不小于0时应判定通过。"""
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
        closing_time_s=0.01,
        sample_interval_m=1.0,
    )

    expected_a = 1425.0 / math.sqrt(1.0 + (WATER_BULK_MODULUS / 206.0e9) * (1.0 / 0.02))
    expected_delta_h = expected_a / GRAVITY

    assert result["status"] == "通过"
    assert result["delta_h"] == pytest.approx(expected_delta_h, rel=1e-6)
    assert result["sample_count"] == 11
    assert result["exceed_count"] == 0
    assert result["min_margin_m"] == pytest.approx(230.0 - 100.5 - expected_delta_h, rel=1e-6)
    assert result["critical_point"]["station_m"] == pytest.approx(0.0)


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
    assert result["critical_point"]["station_m"] == pytest.approx(10.0)
    assert result["critical_point"]["margin_m"] == pytest.approx(result["min_margin_m"])
    assert result["details"][-1]["status"] == "超限"


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
        sample_interval_m=10.0,
    )

    member_deltas = [item["delta_h"] for item in result["member_results"]]
    assert result["status"] == "通过"
    assert result["delta_h"] == pytest.approx(max(member_deltas), rel=1e-6)
    assert result["control_member_key"] == "pipe-b"
    pipe_b_boundary = next(
        item for item in result["details"]
        if item["station_m"] == pytest.approx(10.0) and item["member_key"] == "pipe-b"
    )
    assert pipe_b_boundary["pipe_top_elevation_m"] == pytest.approx(100.25)


def test_calc_distributed_water_hammer_check_marks_not_applicable_when_ts_exceeds_mu():
    """关阀时间大于混合段水锤相时时不做通过判定。"""
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
        closing_time_s=10.0,
        sample_interval_m=1.0,
    )

    assert result["status"] == "不适用"
    assert result["details"] == []
    assert result["min_margin_m"] is None


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
                "velocity_mps": 0.05,
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
    assert result["status"] == "不通过"
    assert len(boundary_rows) == 2
    assert {item["member_key"] for item in boundary_rows} == {"wide-upstream", "narrow-downstream"}
    assert result["critical_point"]["member_key"] == "wide-upstream"


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
