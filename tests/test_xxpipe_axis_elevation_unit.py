# -*- coding: utf-8 -*-
"""xx管轴线高程采样纯函数单元测试。"""

import importlib.util
import math
import os
from pathlib import Path
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")


def _load_cad_tools():
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "未找到 cad_tools.py"
    spec = importlib.util.spec_from_file_location("cad_tools_xxpipe_axis_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cad_tools = _load_cad_tools()


def _node(
    chainage,
    elevation,
    *,
    turn_type="NONE",
    vertical_curve_radius=0.0,
    arc_center_s=None,
    arc_center_z=None,
    arc_end_chainage=None,
    arc_theta_rad=None,
):
    return {
        "chainage": float(chainage),
        "elevation": float(elevation),
        "turn_type": turn_type,
        "vertical_curve_radius": float(vertical_curve_radius),
        "arc_center_s": arc_center_s,
        "arc_center_z": arc_center_z,
        "arc_end_chainage": arc_end_chainage,
        "arc_theta_rad": arc_theta_rad,
    }


def _sample_nodes():
    return [
        _node(0.0, 100.0),
        _node(
            10.0,
            90.0,
            turn_type="ARC",
            vertical_curve_radius=10.0,
            arc_center_s=10.0,
            arc_center_z=100.0,
            arc_end_chainage=20.0,
            arc_theta_rad=math.pi / 2,
        ),
        _node(20.0, 100.0),
        _node(30.0, 110.0),
    ]


def test_sample_xxpipe_centerline_elevation_hits_exact_node_chainage():
    assert cad_tools.sample_xxpipe_centerline_elevation(_sample_nodes(), 10.0) == pytest.approx(90.0)
    assert cad_tools.sample_xxpipe_centerline_elevation(_sample_nodes(), 20.0) == pytest.approx(100.0)


def test_sample_xxpipe_centerline_elevation_interpolates_linear_segment():
    assert cad_tools.sample_xxpipe_centerline_elevation(_sample_nodes(), 5.0) == pytest.approx(95.0)
    assert cad_tools.sample_xxpipe_centerline_elevation(_sample_nodes(), 25.0) == pytest.approx(105.0)


def test_sample_xxpipe_centerline_elevation_evaluates_arc_segment():
    actual = cad_tools.sample_xxpipe_centerline_elevation(_sample_nodes(), 16.0)
    expected = 100.0 - math.sqrt(10.0 ** 2 - (16.0 - 10.0) ** 2)
    assert actual == pytest.approx(expected)


def test_sample_xxpipe_centerline_elevation_rejects_out_of_coverage_station():
    with pytest.raises(ValueError, match="station .* 超出 xx管轴线高程覆盖范围"):
        cad_tools.sample_xxpipe_centerline_elevation(_sample_nodes(), -0.1)

    with pytest.raises(ValueError, match="station .* 超出 xx管轴线高程覆盖范围"):
        cad_tools.sample_xxpipe_centerline_elevation(_sample_nodes(), 30.1)


def test_find_xxpipe_axis_elevation_coverage_gaps_returns_missing_stations():
    missing = cad_tools.find_xxpipe_axis_elevation_coverage_gaps(
        _sample_nodes(),
        [0.0, 5.0, 16.0, -1.0, 25.0, 31.0],
    )
    assert missing == [-1.0, 31.0]


def test_resolve_ordered_node_stations_falls_back_to_plan_distance_without_station_anchor():
    station_data = cad_tools.resolve_ordered_node_stations(
        [
            {"label": "起点", "x": 0.0, "y": 0.0},
            {"label": "中点", "x": 3.0, "y": 4.0},
            {"label": "终点", "x": 6.0, "y": 8.0},
        ]
    )

    assert station_data["stations"] == pytest.approx([0.0, 5.0, 10.0])
    assert station_data["fallback_indices"] == [1, 2]
    assert station_data["missing_items"] == []


def test_resolve_ordered_node_stations_falls_back_to_plan_distance_between_anchors():
    nodes = [
        {"station_MC": 0.0, "x": 0.0, "y": 0.0, "ip_number": 1, "name": "起点"},
        {"x": 30.0, "y": 40.0, "ip_number": 2, "name": "中点"},
        {"station_MC": 100.0, "x": 60.0, "y": 80.0, "ip_number": 3, "name": "终点"},
    ]

    station_data = cad_tools.resolve_ordered_node_stations(nodes)

    assert station_data["stations"] == pytest.approx([0.0, 50.0, 100.0])
    assert station_data["fallback_indices"] == [1]
    assert station_data["missing_items"] == []


def test_resolve_ordered_node_stations_reports_missing_when_anchor_and_distance_both_unavailable():
    nodes = [
        {"x": 0.0, "y": 0.0, "ip_number": 1, "name": "起点"},
        {"ip_number": 2, "name": "中点"},
        {"x": 60.0, "y": 80.0, "ip_number": 3, "name": "终点"},
    ]

    station_data = cad_tools.resolve_ordered_node_stations(nodes)

    assert station_data["stations"] == [None, None, None]
    assert len(station_data["missing_items"]) == 3
    assert any("缺少可用桩号锚点" in item["reason"] for item in station_data["missing_items"])
