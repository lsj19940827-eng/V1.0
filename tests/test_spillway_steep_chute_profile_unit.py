# -*- coding: utf-8 -*-
"""泄水渠与陡坡水面线三种计算模式单元测试。"""

import importlib

import pytest


def _quick(extra):
    """按熊启钧棱柱体陡坡基础参数调用快速计算。"""
    core = importlib.import_module("calc_渠系计算算法内核.泄水渠与陡坡设计")
    data = {
        "section_type": "trapezoidal",
        "Q": 20.0,
        "b": 1.0,
        "m": 1.5,
        "i": 0.02,
        "n": 0.014,
    }
    data.update(extra)
    return core.quick_calculate_spillway_steep_chute(data)


def test_end_depth_by_length_uses_fixed_depth_step_distance_method():
    """已知长度求终点水深时，沿程距离应递增且水深向正常水深递减。"""
    result = _quick({"L": 40.0, "profile_mode": "END_DEPTH_BY_LENGTH", "depth_step": 0.02})

    assert result["profile"]["available"] is True
    points = result["profile"]["points"]
    assert len(points) >= 3
    assert points[0]["distance_m"] == pytest.approx(0.0)
    assert points[-1]["distance_m"] == pytest.approx(40.0, abs=0.2)
    assert points[0]["depth_m"] > points[-1]["depth_m"]
    assert result["hydraulic"]["normal_depth_m"] < points[-1]["depth_m"] < points[0]["depth_m"]


def test_length_by_two_depths_returns_distance_between_given_depths():
    """已知两端水深时，应反算两断面之间的水面线长度。"""
    result = _quick(
        {
            "profile_mode": "LENGTH_BY_TWO_DEPTHS",
            "start_depth": 1.788,
            "end_depth": 1.2,
            "depth_step": 0.02,
        }
    )

    assert result["profile"]["available"] is True
    assert result["profile"]["length_m"] > 0
    assert result["profile"]["end_depth_m"] == pytest.approx(1.2, abs=0.02)


def test_full_curve_to_normal_stops_near_normal_depth():
    """全段曲线模式应从临界水深推到接近正常水深。"""
    result = _quick({"profile_mode": "FULL_CURVE_TO_NORMAL", "depth_step": 0.03})

    assert result["profile"]["available"] is True
    assert result["profile"]["length_m"] > 0
    assert result["profile"]["end_reason"] == "reached_normal_depth"
    assert result["profile"]["end_depth_m"] == pytest.approx(
        result["hydraulic"]["normal_depth_m"],
        abs=max(0.05, result["hydraulic"]["normal_depth_m"] * 0.08),
    )
