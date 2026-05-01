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
from app_渠系计算前端.open_channel.comparison import (
    OPEN_CHANNEL_COMPARISON_SPEC,
    build_open_channel_comparison_tables,
)


def test_open_channel_comparison_omits_control_margin_columns():
    """明渠工况对比不再展示控制余量摘要列。"""
    titles = [column.title for column in OPEN_CHANNEL_COMPARISON_SPEC.hydraulic_columns]
    keys = [column.key for column in OPEN_CHANNEL_COMPARISON_SPEC.hydraulic_columns]

    assert "控制余量类型" not in titles
    assert "控制余量" not in titles
    assert "margin_type" not in keys
    assert "control_margin" not in keys


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
    assert tables.hydraulic_rows[0]["design_freeboard"] == pytest.approx(0.45)
    assert tables.hydraulic_rows[0]["increased_freeboard"] == ""
    assert tables.dimension_rows[0]["m1"] == pytest.approx(1.5)
    assert tables.dimension_rows[0]["B1"] == pytest.approx(1.0)
    assert tables.dimension_rows[0]["m2"] == pytest.approx(1.0)
    assert tables.dimension_rows[0]["B2"] == pytest.approx(4.0)
    assert tables.dimension_rows[0]["m3"] == pytest.approx(1.5)
    assert tables.dimension_rows[0]["h1"] == pytest.approx(0.8)


def test_open_channel_comparison_derives_design_freeboard_when_increase_is_enabled():
    """非圆形明渠启用加大流量时也应展示设计渠道超高。"""
    entries = [
        DxfExportCaseEntry(
            case_idx=0,
            label="梯形加大",
            input_params={"section_type": "梯形", "Q": 5.0, "use_increase": True},
            result={
                "success": True,
                "h_design": 1.20,
                "V_design": 1.10,
                "Q_increased": 6.0,
                "h_increased": 1.50,
                "V_increased": 1.25,
                "Fb": 0.575,
            },
            is_valid=True,
        )
    ]

    tables = build_open_channel_comparison_tables(entries)

    assert tables.hydraulic_rows[0]["design_freeboard"] == pytest.approx(0.50)
    assert tables.hydraulic_rows[0]["increased_freeboard"] == pytest.approx(0.575)


def test_open_channel_comparison_maps_circular_section_dimensions():
    """圆形明渠应把专用水力字段和净空指标映射到对比表。"""
    entries = [
        DxfExportCaseEntry(
            case_idx=1,
            label="圆形",
            input_params={"section_type": "圆形", "Q": 8.0, "use_increase": True},
            result={
                "success": True,
                "D_design": 3.2,
                "y_d": 1.8,
                "V_d": 1.42,
                "Q_inc": 9.6,
                "y_i": 2.05,
                "V_i": 1.55,
                "FB_d": 1.40,
                "PA_d": 43.75,
                "FB_i": 0.36,
                "PA_i": 11.25,
            },
            is_valid=True,
        )
    ]

    tables = build_open_channel_comparison_tables(entries)

    assert tables.hydraulic_rows[0]["h_design"] == pytest.approx(1.8)
    assert tables.hydraulic_rows[0]["V_design"] == pytest.approx(1.42)
    assert tables.hydraulic_rows[0]["Q_increased"] == pytest.approx(9.6)
    assert tables.hydraulic_rows[0]["h_increased"] == pytest.approx(2.05)
    assert tables.hydraulic_rows[0]["V_increased"] == pytest.approx(1.55)
    assert tables.hydraulic_rows[0]["freeboard_hgt_design"] == pytest.approx(1.40)
    assert tables.hydraulic_rows[0]["freeboard_pct_design"] == pytest.approx(43.75)
    assert tables.hydraulic_rows[0]["freeboard_hgt_inc"] == pytest.approx(0.36)
    assert tables.hydraulic_rows[0]["freeboard_pct_inc"] == pytest.approx(11.25)
    assert tables.dimension_rows[0]["D"] == pytest.approx(3.2)
    assert tables.dimension_rows[0]["H"] == pytest.approx(3.2)
