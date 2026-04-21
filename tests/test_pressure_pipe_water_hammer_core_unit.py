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
    assert get_water_hammer_elastic_modulus("PE管") is not None
    assert get_water_hammer_elastic_modulus("未知材质") is None


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
