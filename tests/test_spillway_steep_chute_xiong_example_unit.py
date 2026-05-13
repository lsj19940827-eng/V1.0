# -*- coding: utf-8 -*-
"""熊启钧棱柱体陡坡教学算例回归测试。"""

import importlib

import pytest


def test_xiong_qijun_prismatic_steep_chute_example_end_depth_is_close_to_reference():
    """熊启钧算例长度约 80m 时，末端水深应接近 1.199m。"""
    core = importlib.import_module("calc_渠系计算算法内核.泄水渠与陡坡设计")

    result = core.quick_calculate_spillway_steep_chute(
        {
            "section_type": "trapezoidal",
            "Q": 20.0,
            "b": 1.0,
            "m": 1.5,
            "i": 0.02,
            "n": 0.014,
            "L": 80.0,
            "profile_mode": "END_DEPTH_BY_LENGTH",
            "depth_step": 0.02,
        }
    )

    assert result["success"] is True
    assert result["hydraulic"]["critical_depth_m"] == pytest.approx(1.788, abs=0.05)
    assert result["profile"]["available"] is True
    assert result["profile"]["end_depth_m"] == pytest.approx(1.199, abs=0.08)
    assert result["example"]["name"] == "熊启钧棱柱体陡坡算例"
