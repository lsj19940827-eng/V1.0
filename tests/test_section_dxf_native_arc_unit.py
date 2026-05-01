# -*- coding: utf-8 -*-
"""验证断面 DXF 中几何圆弧使用 AutoCAD 原生实体。"""

from collections import Counter
from pathlib import Path
import sys

import pytest

ezdxf = pytest.importorskip("ezdxf")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端.aqueduct.dxf_export import draw_aqueduct_dxf_on_msp  # noqa: E402
from app_渠系计算前端.culvert.dxf_export import draw_culvert_dxf_on_msp  # noqa: E402
from app_渠系计算前端.dxf_common import setup_section_dxf_document  # noqa: E402
from app_渠系计算前端.open_channel.dxf_export import draw_open_channel_dxf_on_msp  # noqa: E402
from app_渠系计算前端.tunnel.dxf_export import draw_tunnel_dxf_on_msp  # noqa: E402


def _draw_outline_type_counts(draw_func, result, params):
    """绘制断面并统计轮廓线图层上的 DXF 实体类型。"""
    doc = ezdxf.new("R2010")
    setup_section_dxf_document(doc, scale_denom=100)
    msp = doc.modelspace()

    draw_func(msp, result, params, scale_denom=100)

    return Counter(
        entity.dxftype()
        for entity in msp
        if "轮廓线" in str(getattr(entity.dxf, "layer", ""))
    )


def test_aqueduct_u_section_dxf_uses_native_arc_for_bottom():
    """渡槽 U 形弧底应使用原生 ARC，不再用 40 段直线拼接。"""
    counts = _draw_outline_type_counts(
        draw_aqueduct_dxf_on_msp,
        {
            "success": True,
            "section_type": "U形",
            "R": 1.39,
            "f": 0.84,
            "B": 2.78,
            "H_total": 2.23,
            "h_design": 1.872,
            "V_design": 1.143,
            "A_design": 4.374,
            "Q_increased": 6.0,
            "h_increased": 2.116,
            "V_increased": 1.2,
            "Fb": 0.114,
            "Fb_design": 0.358,
        },
        {"section_type": "U形", "Q": 5.0, "n": 0.014, "slope_inv": 3000, "use_increase": True},
    )

    assert counts["ARC"] == 1
    assert counts["LINE"] == 3


def test_open_channel_u_section_dxf_uses_native_arc_for_bottom():
    """明渠 U 形弧底应使用原生 ARC，不再用 48 段直线拼接。"""
    counts = _draw_outline_type_counts(
        draw_open_channel_dxf_on_msp,
        {
            "success": True,
            "section_type": "U形",
            "R": 1.5,
            "alpha_deg": 60.0,
            "theta_deg": 180.0,
            "m": 0.5,
            "h0": 1.5,
            "b_arc": 3.0,
            "h_design": 1.2,
            "h_prime": 2.0,
            "h_increased": 1.5,
            "V_design": 1.2,
            "Q_increased": 6.0,
            "V_increased": 1.3,
            "increase_percent": 20.0,
            "Fb": 0.5,
        },
        {"section_type": "U形", "Q": 5.0, "n": 0.014, "slope_inv": 3000, "use_increase": True},
    )

    assert counts["ARC"] == 1
    assert counts["LINE"] == 3


def test_arch_culvert_dxf_keeps_native_arc_outline():
    """暗涵圆拱直墙型继续使用原生 ARC。"""
    counts = _draw_outline_type_counts(
        draw_culvert_dxf_on_msp,
        {
            "success": True,
            "section_type": "圆拱直墙型",
            "B": 3.0,
            "H_total": 3.0,
            "theta_deg": 180.0,
            "h_design": 1.5,
            "A_design": 3.0,
            "V_design": 1.0,
            "Q_increased": 6.0,
            "h_increased": 2.0,
            "V_increased": 1.1,
        },
        {"section_type": "圆拱直墙型", "Q": 5.0, "n": 0.014, "slope_inv": 3000, "use_increase": True},
    )

    assert counts["ARC"] == 1
    assert counts["LWPOLYLINE"] == 1


@pytest.mark.parametrize(
    ("name", "result", "params", "expected"),
    [
        (
            "圆形",
            {
                "success": True,
                "D": 3.0,
                "h_design": 1.5,
                "A_design": 3.0,
                "V_design": 1.0,
                "Q_increased": 6.0,
                "h_increased": 2.0,
                "V_increased": 1.1,
            },
            {"section_type": "圆形", "Q": 5.0, "n": 0.014, "slope_inv": 3000, "use_increase": True},
            {"CIRCLE": 1},
        ),
        (
            "平底圆形",
            {
                "success": True,
                "D": 3.0,
                "B": 2.0,
                "h_design": 1.4,
                "A_design": 3.0,
                "V_design": 1.0,
                "Q_increased": 6.0,
                "h_increased": 1.8,
                "V_increased": 1.1,
            },
            {"section_type": "平底圆形", "Q": 5.0, "n": 0.014, "slope_inv": 3000, "use_increase": True},
            {"ARC": 1, "LWPOLYLINE": 1},
        ),
        (
            "圆拱直墙型",
            {
                "success": True,
                "B": 3.0,
                "H_total": 3.0,
                "theta_deg": 180.0,
                "h_design": 1.5,
                "A_design": 3.0,
                "V_design": 1.0,
                "Q_increased": 6.0,
                "h_increased": 2.0,
                "V_increased": 1.1,
            },
            {"section_type": "圆拱直墙型", "Q": 5.0, "n": 0.014, "slope_inv": 3000, "use_increase": True},
            {"ARC": 1, "LWPOLYLINE": 1},
        ),
        (
            "马蹄形",
            {
                "success": True,
                "r": 1.5,
                "h_design": 1.4,
                "A_design": 3.0,
                "V_design": 1.0,
                "Q_increased": 6.0,
                "h_increased": 1.8,
                "V_increased": 1.1,
            },
            {"section_type": "马蹄形", "sec_type_int": 1, "Q": 5.0, "n": 0.014, "slope_inv": 3000, "use_increase": True},
            {"ARC": 4},
        ),
    ],
)
def test_tunnel_dxf_keeps_native_round_outline_entities(name, result, params, expected):
    """隧洞已有圆弧或整圆轮廓保持原生实体。"""
    counts = _draw_outline_type_counts(draw_tunnel_dxf_on_msp, result, params)

    for entity_type, expected_count in expected.items():
        assert counts[entity_type] == expected_count, name
