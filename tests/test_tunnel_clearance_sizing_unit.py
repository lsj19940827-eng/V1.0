# -*- coding: utf-8 -*-
"""测试隧洞-圆拱直墙型按加大流量净空比例反推尺寸。"""

import os
import sys

import pytest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "calc_渠系计算算法内核",
    ),
)

from 隧洞设计 import design_horseshoe_by_freeboard_target


def _default_kwargs(**overrides):
    """构造一组稳定通过的圆拱直墙反推输入。"""
    data = {
        "Q_design": 10.0,
        "Q_increased": 12.0,
        "n": 0.014,
        "slope_inv": 3000.0,
        "v_min": 0.1,
        "v_max": 3.0,
        "theta_deg": 120.0,
        "hb_ratio": 1.2,
        "target_freeboard_pct": 20.0,
    }
    data.update(overrides)
    return data


def test_clearance_target_sizing_returns_valid_horseshoe_dimensions():
    """典型参数应反推出满足目标净空比例的断面尺寸。"""
    result = design_horseshoe_by_freeboard_target(**_default_kwargs())

    assert result["success"] is True
    assert result["B"] == pytest.approx(3.187, abs=0.01)
    assert result["H_total"] / result["B"] == pytest.approx(1.2, abs=0.001)
    assert result["H_straight"] > 0
    assert result["h_increased"] > result["h_design"]
    assert result["Q_calc_increased"] == pytest.approx(12.0, rel=0.001)
    assert result["freeboard_pct_inc"] == pytest.approx(20.0, abs=0.05)
    assert result["freeboard_hgt_inc"] >= 0.4


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("hb_ratio", 0.99, "高宽比"),
        ("hb_ratio", 1.51, "高宽比"),
        ("theta_deg", 89.9, "圆心角"),
        ("theta_deg", 180.1, "圆心角"),
        ("target_freeboard_pct", 14.9, "净空比例"),
        ("target_freeboard_pct", 100.0, "净空比例"),
        ("Q_increased", 10.0, "加大流量"),
    ],
)
def test_clearance_target_sizing_rejects_invalid_inputs(field, value, message):
    """无效输入应失败并提示对应字段。"""
    result = design_horseshoe_by_freeboard_target(**_default_kwargs(**{field: value}))

    assert result["success"] is False
    assert message in result["error_message"]


def test_clearance_target_sizing_rejects_velocity_out_of_range():
    """反推结果若不满足主流程流速限制，应禁止采用。"""
    result = design_horseshoe_by_freeboard_target(**_default_kwargs(v_max=0.5))

    assert result["success"] is False
    assert "流速" in result["error_message"]
