# -*- coding: utf-8 -*-
"""复式梯形明渠 DXF 导出的单元测试。"""

import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ezdxf = pytest.importorskip("ezdxf")

from app_渠系计算前端.open_channel.dxf_export import draw_open_channel_dxf_on_msp  # noqa: E402


def test_compound_trapezoid_dxf_export_branch_outputs_geometry_labels():
    """复式梯形导出应走专用分支，并带出关键几何文字。"""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    result = {
        "success": True,
        "b_design": 3.0,
        "h_design": 1.6,
        "h_increased": 1.8,
        "h_prime": 2.45,
        "V_design": 0.97,
        "Q_increased": 10.069,
        "V_increased": 1.01,
        "A_design": 8.65,
        "R_design": 1.13,
        "Beta_design": 1.875,
        "Fb": 0.65,
    }
    params = {
        "section_type": "复式梯形",
        "Q": 8.391,
        "n": 0.014,
        "slope_inv": 3000,
        "m1": 1.5,
        "B1": 2.0,
        "m2": 1.0,
        "B2": 3.0,
        "m3": 1.0,
        "h1": 1.0,
    }

    draw_open_channel_dxf_on_msp(msp, result, params, scale_denom=100)
    texts = [
        entity.dxf.text
        for entity in msp
        if entity.dxftype() == "TEXT"
    ]
    assert any("复式梯形" in text for text in texts)
    assert any("B1 = 2.000 m" in text for text in texts)
    assert any("h1 = 1.000 m" in text for text in texts)
    assert any("1:1.5" in text for text in texts)
    assert any("1:1" in text for text in texts)
