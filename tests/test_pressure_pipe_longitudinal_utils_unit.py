# -*- coding: utf-8 -*-
"""有压管道纵断面裁切工具单元测试。"""

import math
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
UTILS_ROOT = ROOT / "推求水面线"
if str(UTILS_ROOT) not in sys.path:
    sys.path.insert(0, str(UTILS_ROOT))

from utils.pressure_pipe_longitudinal_utils import (  # noqa: E402
    clip_longitudinal_nodes_to_range,
    sample_longitudinal_elevation,
)


def _node(chainage, elevation, **extra):
    data = {
        "chainage": float(chainage),
        "elevation": float(elevation),
        "vertical_curve_radius": 0.0,
        "turn_type": "NONE",
        "turn_angle": 0.0,
        "arc_center_s": None,
        "arc_center_z": None,
        "arc_end_chainage": None,
        "arc_theta_rad": None,
    }
    data.update(extra)
    return data


def test_clip_longitudinal_nodes_to_range_rebuilds_linear_boundaries():
    nodes = [
        _node(0.0, 100.0),
        _node(50.0, 90.0),
        _node(100.0, 80.0),
    ]

    clipped = clip_longitudinal_nodes_to_range(nodes, 10.0, 70.0)

    assert [item["chainage"] for item in clipped] == pytest.approx([10.0, 50.0, 70.0])
    assert [item["elevation"] for item in clipped] == pytest.approx([98.0, 90.0, 86.0])


def test_clip_longitudinal_nodes_to_range_preserves_arc_sampling():
    nodes = [
        _node(
            0.0,
            100.0,
            vertical_curve_radius=10.0,
            turn_type="ARC",
            arc_center_s=0.0,
            arc_center_z=110.0,
            arc_end_chainage=10.0,
            arc_theta_rad=math.pi / 2,
        ),
        _node(10.0, 110.0),
        _node(20.0, 120.0),
    ]

    clipped = clip_longitudinal_nodes_to_range(nodes, 4.0, 10.0)

    assert clipped[0]["chainage"] == pytest.approx(4.0)
    assert clipped[-1]["chainage"] == pytest.approx(10.0)
    assert clipped[0]["arc_end_chainage"] == pytest.approx(10.0)
    assert sample_longitudinal_elevation(clipped, 6.0) == pytest.approx(
        sample_longitudinal_elevation(nodes, 6.0)
    )


def test_sample_longitudinal_elevation_accepts_millimeter_level_endpoint_gap():
    nodes = [
        _node(0.0, 100.0),
        _node(10501.42576073, 90.0),
    ]

    assert sample_longitudinal_elevation(nodes, 10501.426) == pytest.approx(90.0)


def test_clip_longitudinal_nodes_to_range_rejects_out_of_coverage_range():
    nodes = [
        _node(10.0, 100.0),
        _node(20.0, 95.0),
    ]

    with pytest.raises(ValueError, match="纵断面覆盖不足"):
        clip_longitudinal_nodes_to_range(nodes, 0.0, 20.0)
