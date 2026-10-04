# -*- coding: utf-8 -*-
"""按教材的临界条件、能量平衡与渐近性质独立校核陡槽计算。"""

import importlib
import math

import pytest
from scipy.integrate import quad
from scipy.optimize import brentq


core = importlib.import_module("calc_渠系计算算法内核.泄水渠与陡坡设计")
BASE = {"section_type": "trapezoidal", "Q": 20.0, "b": 1.0,
        "m": 1.5, "n": 0.014, "i": 0.02, "L": 80.0}


def _quick(**extra):
    return core.quick_calculate_spillway_steep_chute({**BASE, **extra})


def _independent_metrics(depth, data=BASE):
    """直接依据断面几何、曼宁公式和比能定义计算，不调用内核辅助函数。"""
    q, b, side, n = (data[k] for k in ("Q", "b", "m", "n"))
    area = (b + side * depth) * depth
    radius = area / (b + 2.0 * depth * math.sqrt(1.0 + side * side))
    width = b + 2.0 * side * depth
    alpha = data.get("alpha_profile", 1.1)
    energy = depth + alpha * (q / area) ** 2 / (2.0 * 9.81)
    friction = (n * q / (area * radius ** (2.0 / 3.0))) ** 2
    derivative = 1.0 - alpha * q * q * width / (9.81 * area ** 3)
    return energy, friction, derivative


def test_critical_depth_uses_same_energy_alpha_and_matches_textbook():
    """熊启钧例1-8临界深约1.788m，且比能在该点取极小值。"""
    result = _quick()
    critical = result["hydraulic"]["critical_depth_m"]
    assert critical == pytest.approx(1.788, abs=0.0005)
    assert abs(_independent_metrics(critical)[2]) < 2e-6
    assert result["hydraulic"]["critical"]["energy_froude"] == pytest.approx(1.0, abs=1e-6)
    # 旧工程的临界系数不能把同一能量模型拆成两个不同临界边界。
    migrated = _quick(critical_alpha=1.0)
    assert migrated["hydraulic"]["critical_depth_m"] == critical
    assert migrated["input_params"]["critical_alpha"] == 1.1
    assert any("临界水深系数" in warning and "已统一" in warning for warning in migrated["warnings"])


@pytest.mark.parametrize("length", [0.013, 80.0, 1000.0, 10000.0])
def test_specified_length_keeps_real_endpoint_and_energy_balance(length):
    """短末段及长渐近段均到真实末端，逐段守恒而非对末段水深线性插值。"""
    result = _quick(L=length, start_station=500.0, start_bed_elevation=100.0)
    profile = result["profile"]
    assert profile["available"]
    assert profile["end_reason"] == "reached_length"
    assert profile["length_m"] == pytest.approx(length)
    points = profile["points"]
    assert points[-1]["station_m"] == pytest.approx(500.0 + length)
    assert points[-1]["bed_elevation_m"] == pytest.approx(100.0 - 0.02 * length)
    for up, down in zip(points, points[1:]):
        e1, j1, derivative1 = _independent_metrics(up["depth_m"])
        e2, j2, derivative2 = _independent_metrics(down["depth_m"])
        distance = down["distance_m"] - up["distance_m"]
        residual = e2 - e1 - (0.02 - (j1 + j2) / 2.0) * distance
        # 按水深、距离各保留六位所产生的实际敏感性确定舍入误差上界。
        friction_derivatives = []
        for point in (up, down):
            h = point["depth_m"]
            friction_derivatives.append(abs((_independent_metrics(h + 1e-5)[1]
                                             - _independent_metrics(h - 1e-5)[1]) / 2e-5))
        rounding_bound = 0.5e-6 * (abs(derivative1) + abs(derivative2)
                                  + distance / 2.0 * sum(friction_derivatives))
        rounding_bound += 1e-6 * abs(0.02 - (j1 + j2) / 2.0)
        assert abs(residual) < 1.05 * rounding_bound + 1e-8


def test_endpoint_matches_independent_continuous_energy_integration():
    """与独立积分渐变流微分方程比较，检查平均摩坡分段算法的数值精度。"""
    critical = brentq(lambda h: _independent_metrics(h)[2], 1.0, 3.0, xtol=1e-13)
    normal = brentq(lambda h: _independent_metrics(h)[1] - 0.02, 0.5, 2.0, xtol=1e-13)

    def distance_to(depth):
        return quad(lambda h: _independent_metrics(h)[2] / (0.02 - _independent_metrics(h)[1]),
                    critical, depth, epsabs=1e-9)[0]

    independent_end = brentq(lambda h: distance_to(h) - 80.0, normal + 0.01, critical, xtol=1e-12)
    result = _quick()
    assert result["profile"]["end_depth_m"] == pytest.approx(independent_end, abs=0.0003)
    assert result["hydraulic"]["hydraulic_slope_at_normal"] == pytest.approx(0.02, abs=1e-8)


def test_full_curve_reports_approach_with_stable_tolerance():
    """全曲线终点由接近正常深的误差定义，与输入水深步长解耦。"""
    coarse = _quick(profile_mode="FULL_CURVE_TO_NORMAL", depth_step=0.03)["profile"]
    fine = _quick(profile_mode="FULL_CURVE_TO_NORMAL", depth_step=0.001)["profile"]
    assert coarse["end_reason"] == fine["end_reason"] == "approached_normal_depth"
    assert coarse["end_depth_m"] == fine["end_depth_m"]
    assert coarse["length_m"] == pytest.approx(fine["length_m"], rel=0.002)
    assert coarse["normal_depth_tolerance_m"] > 0


def test_uniform_flow_and_c2_flow_are_computed_without_false_drawdown():
    """均匀流水深恒定，c2急流从低于正常深一侧向下游增水。"""
    normal = brentq(lambda h: _independent_metrics(h)[1] - 0.02, 0.5, 2.0, xtol=1e-13)
    uniform = _quick(control_depth_mode="manual", start_depth=normal, L=1000.0)["profile"]
    assert uniform["available"]
    assert uniform["water_profile_type"] == "uniform"
    assert uniform["points"][0]["depth_m"] == uniform["points"][-1]["depth_m"]
    c2 = _quick(control_depth_mode="manual", start_depth=0.8)["profile"]
    assert c2["available"]
    assert c2["water_profile_type"] == "c_2"
    assert 0.8 < c2["end_depth_m"] < normal
    assert all(a["depth_m"] < b["depth_m"] for a, b in zip(c2["points"], c2["points"][1:]))


@pytest.mark.parametrize("start,end", [(1.788, 1.0), (0.8, 1.2), (2.0, 1.2), (1.2, 1.3)])
def test_two_depths_do_not_clamp_or_cross_profile_boundaries(start, end):
    """不能通过改写目标水深或越过流态/正常深边界伪造连续解。"""
    result = _quick(profile_mode="LENGTH_BY_TWO_DEPTHS", start_depth=start, end_depth=end)
    assert not result["profile"]["available"]
    assert result["start_control"]["depth_m"] == pytest.approx(start)


def test_two_depths_allow_c2_and_reject_exact_normal_as_finite_target():
    normal = brentq(lambda h: _independent_metrics(h)[1] - 0.02, 0.5, 2.0, xtol=1e-13)
    c2 = _quick(profile_mode="LENGTH_BY_TWO_DEPTHS", start_depth=0.8, end_depth=0.9)["profile"]
    assert c2["available"] and c2["length_m"] > 0
    assert c2["end_depth_m"] == pytest.approx(0.9)
    invalid = _quick(profile_mode="LENGTH_BY_TWO_DEPTHS", start_depth=1.788, end_depth=normal)
    assert not invalid["profile"]["available"]
