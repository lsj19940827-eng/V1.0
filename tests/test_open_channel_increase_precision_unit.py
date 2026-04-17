# -*- coding: utf-8 -*-
"""明渠加大流量链路的精度回归测试。"""

import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, os.path.join(str(ROOT), "calc_渠系计算算法内核"))

from 明渠设计 import quick_calculate_trapezoidal  # noqa: E402


def test_trapezoidal_manual_increase_keeps_full_precision_q_increased():
    """手动加大比例换算后的 Q加大 不应在进入后续计算前被截成 3 位。"""
    result = quick_calculate_trapezoidal(
        Q=5.0,
        m=1.0,
        n=0.014,
        slope_inv=3000,
        v_min=0.1,
        v_max=100.0,
        manual_increase_percent=18.2468,
    )

    assert result["success"] is True
    assert result["increase_percent"] == pytest.approx(18.2468)
    assert result["Q_increased"] == pytest.approx(5.91234)
    assert result["h_increased"] > result["h_design"]
