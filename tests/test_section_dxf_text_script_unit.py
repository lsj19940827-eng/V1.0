# -*- coding: utf-8 -*-
"""验证断面 DXF 参数文字中的上下标单位使用 CAD 稳定写法。"""

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


def _draw_and_collect_entities(draw_func, result, params):
    """绘制断面并收集普通文字与多行文字实体。"""
    doc = ezdxf.new("R2010")
    setup_section_dxf_document(doc, scale_denom=100)
    msp = doc.modelspace()

    draw_func(msp, result, params, scale_denom=100)

    text_entities = [entity for entity in msp if entity.dxftype() == "TEXT"]
    mtext_entities = [entity for entity in msp if entity.dxftype() == "MTEXT"]
    return text_entities, mtext_entities


def _assert_script_units_are_mtext(draw_func, result, params):
    """断言 m³/s、m² 不再以普通 TEXT 形式写入 DXF，且不会向下压行。"""
    text_entities, mtext_entities = _draw_and_collect_entities(draw_func, result, params)
    text_values = [entity.dxf.text for entity in text_entities]
    mtext_values = [entity.text for entity in mtext_entities]

    assert not any("³" in text or "²" in text for text in text_values)
    joined_mtext = "".join(mtext_values)
    assert "\\S3^" in joined_mtext
    assert "\\S2^" in joined_mtext
    for entity in mtext_entities:
        assert entity.dxf.attachment_point == 7


def test_aqueduct_single_case_dxf_script_units_use_mtext():
    """渡槽单工况参数块中的流量和面积单位应使用 MTEXT 上标。"""
    _assert_script_units_are_mtext(
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


def test_open_channel_single_case_dxf_script_units_use_mtext():
    """明渠单工况参数块中的流量和面积单位应使用 MTEXT 上标。"""
    _assert_script_units_are_mtext(
        draw_open_channel_dxf_on_msp,
        {
            "success": True,
            "section_type": "梯形",
            "b_design": 2.0,
            "h_design": 1.0,
            "H": 1.3,
            "A_design": 3.0,
            "R_design": 0.8,
            "V_design": 1.5,
            "h_increased": 1.1,
            "V_increased": 1.6,
            "Fb": 0.2,
            "Q_increased": 6.0,
        },
        {"section_type": "梯形", "Q": 5.0, "n": 0.014, "slope_inv": 3000, "m": 1.5, "use_increase": True},
    )


def test_tunnel_single_case_dxf_script_units_use_mtext():
    """隧洞单工况参数块中的流量和面积单位应使用 MTEXT 上标。"""
    _assert_script_units_are_mtext(
        draw_tunnel_dxf_on_msp,
        {
            "success": True,
            "section_type": "圆形",
            "D": 3.0,
            "h_design": 1.5,
            "V_design": 1.2,
            "A_design": 3.1,
            "fb_design": 1.5,
            "Q_increased": 6.0,
            "h_increased": 1.7,
            "V_increased": 1.3,
            "fb_increased": 1.3,
        },
        {"section_type": "圆形", "Q": 5.0, "n": 0.014, "slope_inv": 3000, "use_increase": True},
    )


def test_culvert_single_case_dxf_script_units_use_mtext():
    """暗涵单工况参数块中的流量和面积单位应使用 MTEXT 上标。"""
    _assert_script_units_are_mtext(
        draw_culvert_dxf_on_msp,
        {
            "success": True,
            "section_type": "矩形",
            "B": 2.0,
            "H": 1.5,
            "h_design": 1.0,
            "V_design": 1.2,
            "A_design": 2.0,
            "Fb_design": 0.5,
            "Q_increased": 6.0,
            "h_increased": 1.1,
            "V_increased": 1.3,
            "Fb": 0.4,
        },
        {"section_type": "矩形", "Q": 5.0, "n": 0.014, "slope_inv": 3000, "use_increase": True},
    )
