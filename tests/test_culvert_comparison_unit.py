# -*- coding: utf-8 -*-
"""暗涵工况对比表数据口径测试。"""

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端.dxf_multi_export import DxfExportCaseEntry
from app_渠系计算前端.culvert.comparison import build_culvert_comparison_tables


def test_culvert_comparison_maps_rect_dimensions_and_design_clearance():
    """矩形暗涵应展示 B/H 和设计净空控制余量。"""
    entries = [
        DxfExportCaseEntry(
            case_idx=0,
            label="矩形",
            input_params={"section_type": "矩形", "Q": 4.0, "use_increase": False},
            result={
                "success": True,
                "B": 2.4,
                "H": 1.8,
                "BH_ratio": 1.333,
                "HB_ratio": 0.75,
                "A_total": 4.32,
                "h_design": 1.20,
                "V_design": 1.38,
                "freeboard_hgt_design": 0.60,
                "freeboard_pct_design": 33.3,
            },
            is_valid=True,
        )
    ]

    tables = build_culvert_comparison_tables(entries)

    assert tables.hydraulic_rows[0]["margin_type"] == "设计净空高度"
    assert tables.hydraulic_rows[0]["control_margin"] == pytest.approx(0.60)
    assert tables.dimension_rows[0]["B"] == pytest.approx(2.4)
    assert tables.dimension_rows[0]["H"] == pytest.approx(1.8)
    assert tables.dimension_rows[0]["A_total"] == pytest.approx(4.32)


def test_culvert_comparison_keeps_arch_wall_height_source():
    """圆拱直墙型暗涵应区分手填和自动推导 H直 来源。"""
    entries = [
        DxfExportCaseEntry(
            case_idx=1,
            label="圆拱",
            input_params={"section_type": "圆拱直墙型", "Q": 7.0, "use_increase": True},
            result={
                "success": True,
                "B": 3.2,
                "H_total": 2.6,
                "H_straight": 1.0,
                "theta_deg": 180.0,
                "used_manual_H_straight": True,
                "A_total": 7.1,
                "h_design": 1.55,
                "V_design": 1.46,
                "Q_increased": 8.4,
                "h_increased": 1.72,
                "V_increased": 1.57,
                "freeboard_hgt_inc": 0.88,
                "freeboard_pct_inc": 33.8,
            },
            is_valid=True,
        )
    ]

    tables = build_culvert_comparison_tables(entries)

    assert tables.hydraulic_rows[0]["margin_type"] == "加大净空高度"
    assert tables.hydraulic_rows[0]["control_margin"] == pytest.approx(0.88)
    assert tables.dimension_rows[0]["H_straight"] == pytest.approx(1.0)
    assert tables.dimension_rows[0]["H_straight_source"] == "手填"
    assert tables.dimension_rows[0]["theta_deg"] == pytest.approx(180.0)
