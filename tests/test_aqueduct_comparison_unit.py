# -*- coding: utf-8 -*-
"""渡槽工况对比表数据口径测试。"""

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端.dxf_multi_export import DxfExportCaseEntry
from app_渠系计算前端.aqueduct.comparison import AQUEDUCT_COMPARISON_SPEC, build_aqueduct_comparison_tables


def test_aqueduct_comparison_omits_control_margin_columns():
    """渡槽工况对比不再展示控制余量摘要列。"""
    titles = [column.title for column in AQUEDUCT_COMPARISON_SPEC.hydraulic_columns]
    keys = [column.key for column in AQUEDUCT_COMPARISON_SPEC.hydraulic_columns]

    assert "控制余量类型" not in titles
    assert "控制余量" not in titles
    assert "margin_type" not in keys
    assert "control_margin" not in keys


def test_aqueduct_comparison_keeps_tie_rod_clearance_and_total_height():
    """有拉杆时应展示含拉杆总高和加大有效超高。"""
    entries = [
        DxfExportCaseEntry(
            case_idx=0,
            label="U形拉杆",
            input_params={"section_type": "U形", "Q": 10.0, "use_increase": True},
            result={
                "success": True,
                "R": 1.2,
                "B": 2.4,
                "f": 0.8,
                "H_total": 2.35,
                "tie_rod_height": 0.25,
                "tie_bottom_height": 2.10,
                "design_tie_bottom_clearance": 0.42,
                "increased_tie_bottom_clearance": 0.31,
                "h_design": 1.68,
                "V_design": 1.35,
                "Q_increased": 12.0,
                "h_increased": 1.79,
                "V_increased": 1.48,
            },
            is_valid=True,
        )
    ]

    tables = build_aqueduct_comparison_tables(entries)

    assert tables.hydraulic_rows[0]["design_top_freeboard"] == pytest.approx(0.67)
    assert tables.hydraulic_rows[0]["design_tie_bottom_clearance"] == pytest.approx(0.42)
    assert tables.hydraulic_rows[0]["increased_effective_freeboard"] == pytest.approx(0.31)
    assert tables.dimension_rows[0]["H_total"] == pytest.approx(2.35)
    assert tables.dimension_rows[0]["tie_rod_height"] == pytest.approx(0.25)
    assert tables.dimension_rows[0]["tie_bottom_height"] == pytest.approx(2.10)


def test_aqueduct_comparison_maps_rect_chamfer_columns():
    """矩形渡槽带倒角时应保留倒角角度和边长。"""
    entries = [
        DxfExportCaseEntry(
            case_idx=1,
            label="矩形倒角",
            input_params={"section_type": "矩形", "Q": 6.0, "use_increase": False},
            result={
                "success": True,
                "B": 3.0,
                "H_total": 2.4,
                "h_design": 1.6,
                "V_design": 1.21,
                "Fb_design": 0.8,
                "has_chamfer": True,
                "chamfer_angle": 45.0,
                "chamfer_length": 0.3,
            },
            is_valid=True,
        )
    ]

    tables = build_aqueduct_comparison_tables(entries)

    assert tables.hydraulic_rows[0]["Q_increased"] == ""
    assert tables.hydraulic_rows[0]["design_top_freeboard"] == pytest.approx(0.8)
    assert tables.hydraulic_rows[0]["design_tie_bottom_clearance"] == ""
    assert tables.hydraulic_rows[0]["increased_effective_freeboard"] == ""
    assert tables.dimension_rows[0]["H_B"] == pytest.approx(0.8)
    assert tables.dimension_rows[0]["chamfer_angle"] == pytest.approx(45.0)
    assert tables.dimension_rows[0]["chamfer_length"] == pytest.approx(0.3)
