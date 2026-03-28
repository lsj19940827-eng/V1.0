# -*- coding: utf-8 -*-
"""Kernel-level regression coverage for rectangular aqueduct manual width priority."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calc_渠系计算算法内核.渡槽设计 import quick_calculate_rect


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
