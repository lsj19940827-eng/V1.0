# -*- coding: utf-8 -*-
"""渡槽内核回归测试，覆盖矩形宽度优先和拉杆高度口径。"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calc_渠系计算算法内核.渡槽设计 import quick_calculate_rect, quick_calculate_u


def test_quick_calculate_rect_prefers_manual_b_over_depth_width_ratio():
    result = quick_calculate_rect(
        Q=1.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        depth_width_ratio=0.8,
        manual_B=1.5,
        manual_increase_percent=0,
    )

    assert result["success"] is True
    assert result["B"] == 1.5
    assert abs(result["depth_width_ratio"] - (0.91 / 1.5)) < 1e-9


def test_u_aqueduct_tie_rod_height_reports_effective_freeboard_to_tie_bottom():
    tied = quick_calculate_u(
        Q=20.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=100.0,
        manual_R=2.4,
        manual_increase_percent=10,
        tie_rod_height=0.35,
    )

    assert tied["success"] is True
    assert tied["tie_rod_height"] == pytest.approx(0.35)
    assert tied["tie_bottom_height"] == pytest.approx(tied["H_total"] - 0.35)
    assert tied["Fb"] == pytest.approx(tied["tie_bottom_height"] - tied["h_increased"])
    assert tied["Fb"] >= 0.10
    assert tied["Fb_design"] == pytest.approx(tied["H_total"] - tied["h_design"])
    assert tied["H_B"] == pytest.approx(tied["H_total"] / tied["B"])


def test_u_aqueduct_rejects_increased_freeboard_below_min_after_final_recalculation():
    """加大有效超高必须按原始值校核，不能按显示四舍五入后的 0.1m 放行。"""
    result = quick_calculate_u(
        Q=17.0,
        n=0.014,
        slope_inv=2500,
        v_min=0.6,
        v_max=100.0,
        manual_R=2.35,
        manual_increase_percent=20.0,
        tie_rod_height=0.3,
    )

    assert result["success"] is False
    assert "加大有效超高" in result["error_message"]
    assert "0.097" in result["error_message"]
    assert "0.10" in result["error_message"]
    assert "四舍五入" not in result["error_message"]


def test_u_aqueduct_tie_rod_counts_as_design_freeboard_when_no_increase():
    base = quick_calculate_u(
        Q=5.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=100.0,
        manual_R=2.4,
        manual_increase_percent=0,
    )
    tied = quick_calculate_u(
        Q=5.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=100.0,
        manual_R=2.4,
        manual_increase_percent=0,
        tie_rod_height=0.05,
    )

    assert base["success"] is True
    assert tied["success"] is True
    assert tied["H_total"] == pytest.approx(base["H_total"])
    assert tied["tie_bottom_height"] == pytest.approx(tied["H_total"] - 0.05)
    assert tied["H_total"] - tied["h_design"] + 1e-9 >= tied["R"] / 5
    assert tied["design_tie_bottom_clearance"] + 1e-9 >= 0.10


def test_u_aqueduct_design_only_raises_height_when_tie_rod_exceeds_freeboard():
    result = quick_calculate_u(
        Q=5.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=100.0,
        manual_R=2.4,
        manual_increase_percent=0,
        tie_rod_height=0.7,
    )

    assert result["success"] is True
    assert result["Fb_design"] == pytest.approx(result["H_total"] - result["h_design"])
    assert result["Fb_design"] + 1e-9 >= result["tie_rod_height"] + 0.10
    assert result["design_tie_bottom_clearance"] == pytest.approx(
        result["tie_bottom_height"] - result["h_design"]
    )
    assert result["design_tie_bottom_clearance"] + 1e-9 >= 0.10


def test_rect_aqueduct_tie_rod_height_uses_final_height_for_depth_width_ratio():
    base = quick_calculate_rect(
        Q=1.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        manual_B=1.5,
        manual_increase_percent=10,
    )
    tied = quick_calculate_rect(
        Q=1.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        manual_B=1.5,
        manual_increase_percent=10,
        tie_rod_height=0.2,
    )

    assert base["success"] is True
    assert tied["success"] is True
    assert tied["tie_bottom_height"] == pytest.approx(base["H_total"])
    assert tied["H_total"] == pytest.approx(base["H_total"] + 0.2)
    assert tied["Fb"] == pytest.approx(tied["tie_bottom_height"] - tied["h_increased"])
    assert tied["depth_width_ratio"] == pytest.approx(tied["H_total"] / tied["B"])


def test_rect_aqueduct_tie_rod_counts_as_design_freeboard_when_no_increase():
    base = quick_calculate_rect(
        Q=1.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        manual_B=1.5,
        manual_increase_percent=0,
    )
    tied = quick_calculate_rect(
        Q=1.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        manual_B=1.5,
        manual_increase_percent=0,
        tie_rod_height=0.05,
    )

    assert base["success"] is True
    assert tied["success"] is True
    design_freeboard_min = tied["h_design"] / 12 + 0.05
    assert tied["tie_bottom_height"] == pytest.approx(tied["H_total"] - 0.05)
    assert tied["H_total"] - tied["h_design"] + 1e-9 >= design_freeboard_min
    assert tied["design_tie_bottom_clearance"] == pytest.approx(
        tied["tie_bottom_height"] - tied["h_design"]
    )
    assert tied["design_tie_bottom_clearance"] + 1e-9 >= 0.10


def test_rect_aqueduct_design_only_raises_height_when_tie_rod_exceeds_freeboard():
    result = quick_calculate_rect(
        Q=1.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        manual_B=1.5,
        manual_increase_percent=0,
        tie_rod_height=0.25,
    )

    assert result["success"] is True
    assert result["Fb_design"] == pytest.approx(result["H_total"] - result["h_design"])
    assert result["Fb_design"] + 1e-9 >= result["tie_rod_height"] + 0.10
    assert result["design_tie_bottom_clearance"] == pytest.approx(
        result["tie_bottom_height"] - result["h_design"]
    )
    assert result["design_tie_bottom_clearance"] + 1e-9 >= 0.10


def test_rect_aqueduct_design_freeboard_controls_when_larger_than_tie_clearance():
    result = quick_calculate_rect(
        Q=20.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        manual_B=3.0,
        manual_increase_percent=0,
        tie_rod_height=0.05,
    )

    assert result["success"] is True
    design_freeboard_min = result["h_design"] / 12 + 0.05
    assert result["Fb_design"] + 1e-9 >= design_freeboard_min
    assert result["design_tie_bottom_clearance"] + 1e-9 >= 0.10
    assert design_freeboard_min > result["tie_rod_height"] + 0.10


def test_aqueduct_tie_rod_height_rejects_negative_values():
    result = quick_calculate_rect(
        Q=1.0,
        n=0.014,
        slope_inv=2000,
        v_min=0.1,
        v_max=100.0,
        manual_B=1.5,
        manual_increase_percent=10,
        tie_rod_height=-0.1,
    )

    assert result["success"] is False
    assert "拉杆高度" in result["error_message"]
