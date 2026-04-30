# -*- coding: utf-8 -*-
"""明渠工况对比表数据口径测试。"""

import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端.dxf_multi_export import DxfExportCaseEntry
from app_渠系计算前端.open_channel.comparison import build_open_channel_comparison_tables


def test_open_channel_comparison_expands_compound_trapezoid_and_blanks_increase():
    """复式梯形应展开 6 个专用参数，未启用加大流量时加大列为空。"""
    entries = [
        DxfExportCaseEntry(
            case_idx=0,
            label="复式低流量",
            input_params={
                "section_type": "复式梯形",
                "Q": 5.0,
                "use_increase": False,
                "m1": 1.5,
                "B1": 1.0,
                "m2": 1.0,
                "B2": 4.0,
                "m3": 1.5,
                "h1": 0.8,
            },
            result={
                "success": True,
                "h_design": 1.35,
                "V_design": 1.12,
                "h_prime": 2.10,
                "Fb": 0.45,
            },
            is_valid=True,
        )
    ]

    tables = build_open_channel_comparison_tables(entries)

    assert len(tables.hydraulic_rows) == 1
    assert tables.hydraulic_rows[0]["case_name"] == "工况 1｜复式低流量"
    assert tables.hydraulic_rows[0]["Q_increased"] == ""
    assert tables.hydraulic_rows[0]["h_increased"] == ""
    assert tables.hydraulic_rows[0]["margin_type"] == "设计渠道超高"
    assert tables.hydraulic_rows[0]["control_margin"] == pytest.approx(0.45)
    assert tables.dimension_rows[0]["m1"] == pytest.approx(1.5)
    assert tables.dimension_rows[0]["B1"] == pytest.approx(1.0)
    assert tables.dimension_rows[0]["m2"] == pytest.approx(1.0)
    assert tables.dimension_rows[0]["B2"] == pytest.approx(4.0)
    assert tables.dimension_rows[0]["m3"] == pytest.approx(1.5)
    assert tables.dimension_rows[0]["h1"] == pytest.approx(0.8)


def test_open_channel_comparison_maps_circular_section_dimensions():
    """圆形明渠应把采用直径映射到结构尺寸表。"""
    entries = [
        DxfExportCaseEntry(
            case_idx=1,
            label="圆形",
            input_params={"section_type": "圆形", "Q": 8.0, "use_increase": True},
            result={
                "success": True,
                "D_design": 3.2,
                "h_design": 1.8,
                "V_design": 1.42,
                "Q_increased": 9.6,
                "h_increased": 2.05,
                "V_increased": 1.55,
                "FB_i": 0.36,
            },
            is_valid=True,
        )
    ]

    tables = build_open_channel_comparison_tables(entries)

    assert tables.hydraulic_rows[0]["margin_type"] == "加大渠道超高"
    assert tables.hydraulic_rows[0]["control_margin"] == pytest.approx(0.36)
    assert tables.dimension_rows[0]["D"] == pytest.approx(3.2)
    assert tables.dimension_rows[0]["H"] == pytest.approx(3.2)
