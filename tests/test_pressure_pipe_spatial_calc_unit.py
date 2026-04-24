"""
有压管道独立叠加口径单元测试

覆盖有压管道在平面点、纵断面节点组合下的长度来源、
局部损失拆分和数据模式文本。
"""

import math
import os
import sys

import pytest

# 添加项目路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "推求水面线"))

from core.pressure_pipe_calc import (
    calc_bend_local_loss,
    calc_friction_loss,
    calc_total_head_loss,
    calc_total_head_loss_with_spatial,
    calc_transition_loss,
)


def _calc_plan_length(ip_points):
    """计算平面点坐标长度。"""
    total = 0.0
    for index in range(len(ip_points) - 1):
        start = ip_points[index]
        end = ip_points[index + 1]
        total += math.hypot(end["x"] - start["x"], end["y"] - start["y"])
    return total


def _calc_longitudinal_actual_length(longitudinal_nodes):
    """计算纵断面实长。"""
    total = 0.0
    for index in range(len(longitudinal_nodes) - 1):
        start = longitudinal_nodes[index]
        end = longitudinal_nodes[index + 1]
        total += math.hypot(
            end["chainage"] - start["chainage"],
            end["elevation"] - start["elevation"],
        )
    return total


def _calc_fold_loss(angle_deg, velocity):
    """按折管公式计算纵断面折角局损。"""
    half_angle_rad = math.radians(angle_deg) / 2
    sin_half = math.sin(half_angle_rad)
    xi = 0.9457 * sin_half ** 2 + 2.047 * sin_half ** 4
    return xi * velocity ** 2 / (2 * 9.81)


def test_independent_sum_mode_uses_longitudinal_length_and_separate_local_losses():
    """平面和纵断面同时存在时，按独立叠加口径计算。"""

    ip_points = [
        {"x": 0.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 0.0},
        {"x": 120.0, "y": 0.0, "turn_radius": 6.0, "turn_angle": 45.0},
        {"x": 220.0, "y": 100.0, "turn_radius": 0.0, "turn_angle": 0.0},
    ]
    longitudinal_nodes = [
        {"chainage": 0.0, "elevation": 100.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
        {"chainage": 100.0, "elevation": 96.0, "vertical_curve_radius": 8.0, "turn_type": "ARC", "turn_angle": 30.0},
        {"chainage": 200.0, "elevation": 94.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
    ]

    result = calc_total_head_loss_with_spatial(
        name="独立叠加测试管道",
        Q=2.0,
        D=1.0,
        material_key="预应力钢筒混凝土管",
        ip_points=ip_points,
        longitudinal_nodes=longitudinal_nodes,
        upstream_velocity=1.0,
        downstream_velocity=1.0,
    )

    expected_length = _calc_longitudinal_actual_length(longitudinal_nodes)
    expected_friction, _ = calc_friction_loss(2.0, 1.0, expected_length, "预应力钢筒混凝土管")
    plan_loss = calc_bend_local_loss(1.0, 6.0, 45.0, result.pipe_velocity)[1]
    longitudinal_loss = calc_bend_local_loss(1.0, 8.0, 30.0, result.pipe_velocity)[1]
    inlet_loss = calc_transition_loss(result.pipe_velocity, 1.0, 0.10, is_inlet=True)[0]
    outlet_loss = calc_transition_loss(result.pipe_velocity, 1.0, 0.20, is_inlet=False)[0]

    assert result.data_mode == "平面+纵断面（独立叠加）"
    assert result.total_length == pytest.approx(expected_length, rel=1e-9)
    assert result.friction_loss == pytest.approx(expected_friction, rel=1e-9)
    assert result.total_bend_loss == pytest.approx(plan_loss + longitudinal_loss, rel=1e-9)
    assert result.total_head_loss == pytest.approx(
        expected_friction + plan_loss + longitudinal_loss + inlet_loss + outlet_loss,
        rel=1e-9,
    )
    assert "未采用三维空间合并" in result.calc_steps
    assert "沿程长度来源：纵断面实长" in result.calc_steps
    assert "平面局部损失合计" in result.calc_steps
    assert "纵断面局部损失合计" in result.calc_steps


def test_plan_only_mode_uses_plan_length():
    """仅有平面点时，沿程长度取平面点坐标长度。"""

    ip_points = [
        {"x": 0.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 0.0},
        {"x": 100.0, "y": 0.0, "turn_radius": 5.0, "turn_angle": 45.0},
        {"x": 200.0, "y": 100.0, "turn_radius": 0.0, "turn_angle": 0.0},
    ]

    result = calc_total_head_loss_with_spatial(
        name="仅平面测试管道",
        Q=2.0,
        D=1.0,
        material_key="预应力钢筒混凝土管",
        ip_points=ip_points,
        longitudinal_nodes=[],
        upstream_velocity=1.0,
        downstream_velocity=1.0,
    )

    expected_length = _calc_plan_length(ip_points)
    expected_friction, _ = calc_friction_loss(2.0, 1.0, expected_length, "预应力钢筒混凝土管")
    expected_plan_loss = calc_bend_local_loss(1.0, 5.0, 45.0, result.pipe_velocity)[1]

    assert result.data_mode == "仅平面（独立计算）"
    assert result.total_length == pytest.approx(expected_length, rel=1e-9)
    assert result.friction_loss == pytest.approx(expected_friction, rel=1e-9)
    assert result.total_bend_loss == pytest.approx(expected_plan_loss, rel=1e-9)
    assert "沿程长度来源：平面点坐标长度" in result.calc_steps
    assert "纵断面局部损失合计: 0.0000 m" in result.calc_steps


def test_longitudinal_only_mode_uses_vertical_fold_loss():
    """仅有纵断面节点时，按纵断面实长和折管局损计算。"""

    longitudinal_nodes = [
        {"chainage": 0.0, "elevation": 100.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
        {"chainage": 80.0, "elevation": 98.0, "vertical_curve_radius": 0.0, "turn_type": "FOLD", "turn_angle": 20.0},
        {"chainage": 160.0, "elevation": 92.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
    ]

    result = calc_total_head_loss_with_spatial(
        name="仅纵断面测试管道",
        Q=1.5,
        D=0.8,
        material_key="预应力钢筒混凝土管",
        ip_points=[],
        longitudinal_nodes=longitudinal_nodes,
        upstream_velocity=0.8,
        downstream_velocity=0.9,
    )

    expected_length = _calc_longitudinal_actual_length(longitudinal_nodes)
    expected_friction, _ = calc_friction_loss(1.5, 0.8, expected_length, "预应力钢筒混凝土管")
    expected_vertical_loss = _calc_fold_loss(20.0, result.pipe_velocity)

    assert result.data_mode == "仅纵断面（独立计算）"
    assert result.total_length == pytest.approx(expected_length, rel=1e-9)
    assert result.friction_loss == pytest.approx(expected_friction, rel=1e-9)
    assert result.total_bend_loss == pytest.approx(expected_vertical_loss, rel=1e-9)
    assert "平面局部损失合计: 0.0000 m" in result.calc_steps
    assert "沿程长度来源：纵断面实长" in result.calc_steps


def test_independent_sum_mode_skips_marked_missing_outlet_transition_once():
    """出口无渐变段时，出口损失只按缺失逻辑处理一次。"""

    ip_points = [
        {"x": 0.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 0.0},
        {"x": 100.0, "y": 0.0, "turn_radius": 4.0, "turn_angle": 30.0},
        {"x": 200.0, "y": 80.0, "turn_radius": 0.0, "turn_angle": 0.0},
    ]
    longitudinal_nodes = [
        {"chainage": 0.0, "elevation": 100.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
        {"chainage": 100.0, "elevation": 97.0, "vertical_curve_radius": 6.0, "turn_type": "ARC", "turn_angle": 25.0},
        {"chainage": 200.0, "elevation": 95.0, "vertical_curve_radius": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
    ]

    result = calc_total_head_loss_with_spatial(
        name="缺失出口渐变段测试管道",
        Q=1.2,
        D=0.8,
        material_key="预应力钢筒混凝土管",
        ip_points=ip_points,
        longitudinal_nodes=longitudinal_nodes,
        upstream_velocity=0.92,
        downstream_velocity=1.039,
        has_outlet_transition=False,
        outlet_transition_reason="紧邻有压同类结构，无渐变段",
    )

    expected_length = _calc_longitudinal_actual_length(longitudinal_nodes)
    expected_friction, _ = calc_friction_loss(1.2, 0.8, expected_length, "预应力钢筒混凝土管")
    plan_loss = calc_bend_local_loss(0.8, 4.0, 30.0, result.pipe_velocity)[1]
    vertical_loss = calc_bend_local_loss(0.8, 6.0, 25.0, result.pipe_velocity)[1]
    inlet_loss = calc_transition_loss(result.pipe_velocity, 0.92, 0.10, is_inlet=True)[0]

    assert result.data_mode == "平面+纵断面（独立叠加）"
    assert result.outlet_transition_loss == 0.0
    assert result.has_outlet_transition is False
    assert result.outlet_transition_details["reason"] == "紧邻有压同类结构，无渐变段"
    assert result.total_head_loss == pytest.approx(
        expected_friction + plan_loss + vertical_loss + inlet_loss,
        rel=1e-9,
    )
    assert result.calc_steps.count("6. 出口渐变段水头损失") == 1
    assert "紧邻有压同类结构，无渐变段" in result.calc_steps


def test_spatial_falls_back_to_plan_length_when_longitudinal_invalid_and_common_local_loss_is_added():
    """纵断面无效时回退平面长度，并把通用局损单独叠加。"""

    ip_points = [
        {"x": 0.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 0.0},
        {"x": 100.0, "y": 0.0, "turn_radius": 5.0, "turn_angle": 45.0},
        {"x": 200.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 0.0},
    ]
    longitudinal_nodes = [
        {"chainage": 20.0, "elevation": 100.0, "turn_type": "NONE", "turn_angle": 0.0},
        {"chainage": 20.0, "elevation": 100.0, "turn_type": "NONE", "turn_angle": 0.0},
    ]

    baseline_result = calc_total_head_loss_with_spatial(
        name="纵断面无效回退测试管道",
        Q=1.0,
        D=0.8,
        material_key="预应力钢筒混凝土管",
        ip_points=ip_points,
        longitudinal_nodes=longitudinal_nodes,
        upstream_velocity=0.8,
        downstream_velocity=0.8,
        has_inlet_transition=False,
        has_outlet_transition=False,
    )

    zero_common_result = calc_total_head_loss_with_spatial(
        name="纵断面无效回退测试管道",
        Q=1.0,
        D=0.8,
        material_key="预应力钢筒混凝土管",
        ip_points=ip_points,
        longitudinal_nodes=longitudinal_nodes,
        upstream_velocity=0.8,
        downstream_velocity=0.8,
        has_inlet_transition=False,
        has_outlet_transition=False,
        common_local_loss=0.0,
        common_local_details=None,
    )

    common_local_details = {"method": "manual_override", "hj": 0.12}
    result = calc_total_head_loss_with_spatial(
        name="纵断面无效回退测试管道",
        Q=1.0,
        D=0.8,
        material_key="预应力钢筒混凝土管",
        ip_points=ip_points,
        longitudinal_nodes=longitudinal_nodes,
        upstream_velocity=0.8,
        downstream_velocity=0.8,
        has_inlet_transition=False,
        has_outlet_transition=False,
        common_local_loss=0.12,
        common_local_details=common_local_details,
    )

    expected_length = _calc_plan_length(ip_points)
    expected_friction, _ = calc_friction_loss(1.0, 0.8, expected_length, "预应力钢筒混凝土管")
    expected_plan_loss = calc_bend_local_loss(0.8, 5.0, 45.0, result.pipe_velocity)[1]

    assert baseline_result.total_length == pytest.approx(expected_length, rel=1e-9)
    assert zero_common_result.total_head_loss == pytest.approx(baseline_result.total_head_loss, rel=1e-9)
    assert result.total_length == pytest.approx(expected_length, rel=1e-9)
    assert result.friction_loss == pytest.approx(expected_friction, rel=1e-9)
    assert result.total_bend_loss == pytest.approx(expected_plan_loss, rel=1e-9)
    assert result.local_loss == pytest.approx(0.12, rel=1e-9)
    assert result.local_details == common_local_details
    assert result.total_head_loss == pytest.approx(expected_friction + expected_plan_loss + 0.12, rel=1e-9)
    assert "沿程长度来源：平面点坐标长度" in result.calc_steps


def test_spatial_longitudinal_length_sorts_nodes_ignores_duplicates_and_uses_arc_length():
    """纵断面实长应按桩号排序、忽略零长度重复段，并对圆弧使用弧长。"""

    longitudinal_nodes = [
        {"chainage": 100.0, "elevation": 2.0, "turn_type": "NONE", "turn_angle": 0.0},
        {
            "chainage": 50.0,
            "elevation": 0.0,
            "turn_type": "ARC",
            "turn_angle": math.degrees(0.5),
            "vertical_curve_radius": 10.0,
            "arc_end_chainage": 55.0,
            "arc_theta_rad": 0.5,
        },
        {"chainage": 0.0, "elevation": 0.0, "turn_type": "NONE", "turn_angle": 0.0},
        {"chainage": 55.0, "elevation": 2.0, "turn_type": "NONE", "turn_angle": 0.0},
        {"chainage": 55.0, "elevation": 2.0, "turn_type": "NONE", "turn_angle": 0.0},
    ]

    result = calc_total_head_loss_with_spatial(
        name="纵断面排序圆弧测试管道",
        Q=1.0,
        D=0.8,
        material_key="预应力钢筒混凝土管",
        ip_points=[],
        longitudinal_nodes=longitudinal_nodes,
        upstream_velocity=0.0,
        downstream_velocity=0.0,
        has_inlet_transition=False,
        has_outlet_transition=False,
    )

    expected_length = 50.0 + 10.0 * 0.5 + 45.0
    expected_friction, _ = calc_friction_loss(1.0, 0.8, expected_length, "预应力钢筒混凝土管")

    assert result.data_mode == "仅纵断面（独立计算）"
    assert result.total_length == pytest.approx(expected_length, rel=1e-9)
    assert result.friction_loss == pytest.approx(expected_friction, rel=1e-9)
    assert result.total_bend_loss == pytest.approx(
        calc_bend_local_loss(0.8, 10.0, math.degrees(0.5), result.pipe_velocity)[1],
        rel=1e-9,
    )


def test_spatial_counts_plan_fold_and_skips_invalid_longitudinal_fold_angles():
    """平面无半径转角按折管计损，纵断面异常折角不应计损。"""

    ip_points = [
        {"x": 0.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 0.0},
        {"x": 80.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 30.0},
        {"x": 160.0, "y": 20.0, "turn_radius": 0.0, "turn_angle": 0.0},
    ]
    longitudinal_nodes = [
        {"chainage": 0.0, "elevation": 100.0, "turn_type": "NONE", "turn_angle": 0.0},
        {"chainage": 40.0, "elevation": 99.5, "turn_type": "FOLD", "turn_angle": 0.05},
        {"chainage": 80.0, "elevation": 98.0, "turn_type": "FOLD", "turn_angle": 20.0},
        {"chainage": 120.0, "elevation": 97.5, "turn_type": "FOLD", "turn_angle": 180.0},
        {"chainage": 160.0, "elevation": 97.0, "turn_type": "NONE", "turn_angle": 0.0},
    ]

    result = calc_total_head_loss_with_spatial(
        name="平面折管与异常纵断面角度测试管道",
        Q=1.1,
        D=0.8,
        material_key="预应力钢筒混凝土管",
        ip_points=ip_points,
        longitudinal_nodes=longitudinal_nodes,
        upstream_velocity=0.0,
        downstream_velocity=0.0,
        has_inlet_transition=False,
        has_outlet_transition=False,
    )

    expected_plan_fold_loss = _calc_fold_loss(30.0, result.pipe_velocity)
    expected_longitudinal_fold_loss = _calc_fold_loss(20.0, result.pipe_velocity)

    assert result.total_bend_loss == pytest.approx(
        expected_plan_fold_loss + expected_longitudinal_fold_loss,
        rel=1e-9,
    )
    assert len(result.bend_details) == 2


def test_plan_entry_accepts_common_local_loss_and_zero_radius_turn():
    """平面入口应支持通用局损，并把无半径转角按折管计损。"""

    ip_points = [
        {"x": 0.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 0.0},
        {"x": 60.0, "y": 0.0, "turn_radius": 0.0, "turn_angle": 25.0},
        {"x": 120.0, "y": 20.0, "turn_radius": 0.0, "turn_angle": 0.0},
    ]
    common_local_details = {"method": "valve_group", "hj": 0.07}

    result = calc_total_head_loss(
        name="平面入口通用局损测试管道",
        Q=0.9,
        D=0.8,
        material_key="预应力钢筒混凝土管",
        ip_points=ip_points,
        upstream_velocity=0.0,
        downstream_velocity=0.0,
        has_inlet_transition=False,
        has_outlet_transition=False,
        common_local_loss=0.07,
        common_local_details=common_local_details,
    )

    expected_length = _calc_plan_length(ip_points)
    expected_friction, _ = calc_friction_loss(0.9, 0.8, expected_length, "预应力钢筒混凝土管")
    expected_plan_fold_loss = _calc_fold_loss(25.0, result.pipe_velocity)

    assert result.total_length == pytest.approx(expected_length, rel=1e-9)
    assert result.total_bend_loss == pytest.approx(expected_plan_fold_loss, rel=1e-9)
    assert result.local_loss == pytest.approx(0.07, rel=1e-9)
    assert result.local_details == common_local_details
    assert result.total_head_loss == pytest.approx(expected_friction + expected_plan_fold_loss + 0.07, rel=1e-9)
