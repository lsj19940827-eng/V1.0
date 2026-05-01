# -*- coding: utf-8 -*-
"""隧洞多工况参数对比表回归测试。"""

import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端.dxf_multi_export import DxfExportCaseEntry
from app_渠系计算前端.tunnel.comparison import (
    TUNNEL_COMPARISON_SPEC,
    build_tunnel_comparison_tables,
    build_tunnel_comparison_rows,
    compute_tunnel_total_geometry_metrics,
)


@pytest.fixture
def local_tmp_path():
    """使用仓库内临时目录，避开系统临时目录权限问题。"""
    base_dir = ROOT / ".pytest_tmp" / "tunnel_comparison_unit"
    base_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(dir=base_dir))
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _get_qapp():
    """获取测试用 Qt 应用。"""
    return QApplication.instance() or QApplication([])


def test_tunnel_comparison_omits_control_margin_columns():
    """隧洞工况对比不再展示控制余量摘要列。"""
    titles = [column.title for column in TUNNEL_COMPARISON_SPEC.hydraulic_columns]
    keys = [column.key for column in TUNNEL_COMPARISON_SPEC.hydraulic_columns]

    assert "控制余量类型" not in titles
    assert "控制余量" not in titles
    assert "margin_type" not in keys
    assert "control_margin" not in keys


def test_arch_metrics_use_total_tunnel_geometry_not_wetted_geometry():
    """圆拱直墙型周长和面积应按完整洞身几何计算。"""
    metrics = compute_tunnel_total_geometry_metrics(
        {"section_type": "圆拱直墙型"},
        {
            "B": 4.0,
            "H_total": 3.0,
            "H_straight": 1.0,
            "theta_deg": 180.0,
            "A_design": 6.0,
            "P_design": 7.0,
        },
    )

    assert metrics["B"] == pytest.approx(4.0)
    assert metrics["H_total"] == pytest.approx(3.0)
    assert metrics["H_straight"] == pytest.approx(1.0)
    assert metrics["total_perimeter"] == pytest.approx(4.0 + 2.0 + math.pi * 2.0)
    assert metrics["total_area"] == pytest.approx(4.0 + math.pi * 2.0)


def test_flat_bottom_circle_metrics_include_flat_bottom_and_major_arc():
    """平底圆形周长应等于平底宽加顶部大圆弧长度。"""
    metrics = compute_tunnel_total_geometry_metrics(
        {"section_type": "平底圆形"},
        {
            "D": 4.0,
            "B": 2.0,
            "h_design": 2.0,
            "P_design": 5.0,
        },
    )

    expected_arc = 2.0 * math.radians(300.0)
    assert metrics["D"] == pytest.approx(4.0)
    assert metrics["B"] == pytest.approx(2.0)
    assert metrics["H_total"] == pytest.approx(2.0 + math.sqrt(3.0))
    assert metrics["total_perimeter"] == pytest.approx(2.0 + expected_arc)
    assert metrics["total_area"] > 12.0


def test_build_comparison_rows_outputs_design_and_increase_fields():
    """对比行应同时包含设计工况、加大工况和洞身几何指标。"""
    entries = [
        DxfExportCaseEntry(
            case_idx=0,
            label="低流量",
            input_params={"section_type": "圆形", "Q": 5.0, "use_increase": False},
            result={
                "success": True,
                "D": 3.0,
                "h_design": 1.5,
                "V_design": 1.2,
                "A_total": math.pi * 1.5 * 1.5,
            },
            is_valid=True,
        ),
        DxfExportCaseEntry(
            case_idx=1,
            label="高流量",
            input_params={"section_type": "圆拱直墙型", "Q": 8.0, "use_increase": True},
            result={
                "success": True,
                "B": 4.0,
                "H_total": 3.0,
                "H_straight": 1.0,
                "theta_deg": 180.0,
                "h_design": 2.0,
                "V_design": 1.7,
                "Q_increased": 9.2,
                "h_increased": 2.25,
                "V_increased": 1.9,
                "freeboard_hgt_design": 1.00,
                "freeboard_pct_design": 18.0,
                "freeboard_hgt_inc": 0.75,
                "freeboard_pct_inc": 15.0,
                "A_total": 10.28,
            },
            is_valid=True,
        ),
    ]

    rows = build_tunnel_comparison_rows(entries)

    assert len(rows) == 2
    assert rows[0]["case_name"] == "工况 1｜低流量"
    assert rows[0]["Q_increased"] == ""
    assert rows[0]["h_increased"] == ""
    assert rows[0]["total_perimeter"] == pytest.approx(math.pi * 3.0)
    assert rows[1]["case_name"] == "工况 2｜高流量"
    assert rows[1]["Q_increased"] == pytest.approx(9.2)
    assert rows[1]["h_increased"] == pytest.approx(2.25)
    assert rows[1]["H_straight"] == pytest.approx(1.0)


def test_build_tunnel_comparison_tables_splits_hydraulic_and_dimension_rows():
    """隧洞新对比口径应拆成水力结果表和结构尺寸表。"""
    entries = [
        DxfExportCaseEntry(
            case_idx=0,
            label="圆形",
            input_params={"section_type": "圆形", "Q": 5.0, "use_increase": False},
            result={
                "success": True,
                "D": 3.0,
                "h_design": 1.5,
                "V_design": 1.2,
                "A_total": math.pi * 1.5 * 1.5,
            },
            is_valid=True,
        ),
        DxfExportCaseEntry(
            case_idx=1,
            label="圆拱",
            input_params={"section_type": "圆拱直墙型", "Q": 8.0, "use_increase": True},
            result={
                "success": True,
                "B": 4.0,
                "H_total": 3.0,
                "H_straight": 1.0,
                "theta_deg": 180.0,
                "h_design": 2.0,
                "V_design": 1.7,
                "Q_increased": 9.2,
                "h_increased": 2.25,
                "V_increased": 1.9,
                "freeboard_hgt_design": 1.00,
                "freeboard_pct_design": 18.0,
                "freeboard_hgt_inc": 0.75,
                "freeboard_pct_inc": 15.0,
                "A_total": 10.28,
            },
            is_valid=True,
        ),
    ]

    tables = build_tunnel_comparison_tables(entries)

    assert len(tables.hydraulic_rows) == 2
    assert tables.hydraulic_rows[0]["Q_increased"] == ""
    assert tables.hydraulic_rows[1]["Q_increased"] == pytest.approx(9.2)
    assert tables.hydraulic_rows[1]["freeboard_hgt_design"] == pytest.approx(1.00)
    assert tables.hydraulic_rows[1]["freeboard_pct_design"] == pytest.approx(18.0)
    assert tables.hydraulic_rows[1]["freeboard_hgt_inc"] == pytest.approx(0.75)
    assert tables.hydraulic_rows[1]["freeboard_pct_inc"] == pytest.approx(15.0)
    assert tables.dimension_rows[0]["D"] == pytest.approx(3.0)
    assert tables.dimension_rows[1]["B"] == pytest.approx(4.0)
    assert tables.dimension_rows[1]["theta_deg"] == pytest.approx(180.0)
    assert tables.dimension_rows[1]["R_arch"] == pytest.approx(2.0)
    assert tables.dimension_rows[1]["H_arch"] == pytest.approx(2.0)
    assert tables.dimension_rows[1]["total_perimeter"] == pytest.approx(4.0 + 2.0 + math.pi * 2.0)


def test_comparison_clipboard_text_includes_headers_and_empty_cells_for_excel():
    """工况对比表全选复制时应生成 Excel 可识别的带表头文本。"""
    _get_qapp()
    import app_渠系计算前端.tunnel.panel as tunnel_panel_mod

    table = QTableWidget(2, 3)
    table.setHorizontalHeaderLabels(["工况", "设计流量(m³/s)", "加大流量(m³/s)"])
    values = [
        ["工况 1｜圆形-Q1=10.0", "10.000", "12.000"],
        ["工况 2｜圆形-Q2=11", "11.000", ""],
    ]
    for row_idx, row_values in enumerate(values):
        for col_idx, text in enumerate(row_values):
            table.setItem(row_idx, col_idx, QTableWidgetItem(text))
    table.selectAll()

    dummy = SimpleNamespace(comparison_table=table)

    text, row_count, col_count = tunnel_panel_mod.TunnelPanel._build_comparison_clipboard_text(dummy)

    assert row_count == 2
    assert col_count == 3
    assert text == (
        "工况\t设计流量(m³/s)\t加大流量(m³/s)\n"
        "工况 1｜圆形-Q1=10.0\t10.000\t12.000\n"
        "工况 2｜圆形-Q2=11\t11.000\t"
    )


def test_tunnel_panel_combined_dxf_passes_comparison_table_callback(monkeypatch, local_tmp_path):
    """隧洞面板合并 DXF 导出应把对比表回调传给公共导出器。"""
    import app_渠系计算前端.tunnel.panel as tunnel_panel_mod

    captured = {}

    def _fake_export(filepath, entries, scale_denom, draw_case, draw_summary_table=None):
        captured.update(
            {
                "filepath": filepath,
                "entries": entries,
                "scale_denom": scale_denom,
                "draw_case": draw_case,
                "draw_summary_table": draw_summary_table,
            }
        )
        return filepath

    monkeypatch.setattr(tunnel_panel_mod, "export_combined_case_dxf", _fake_export)

    dummy = SimpleNamespace()
    dummy._combined_dxf_default_name = lambda count: f"隧洞断面_{count}个工况_合并.dxf"
    dummy._choose_dxf_filepath = lambda _name: str(local_tmp_path / "combined.dxf")
    entries = [
        DxfExportCaseEntry(0, "工况A", {"section_type": "圆形"}, {"success": True}, True),
        DxfExportCaseEntry(1, "工况B", {"section_type": "圆形"}, {"success": True}, True),
    ]

    result_path = tunnel_panel_mod.TunnelPanel._export_combined_dxf_entries(dummy, entries, 100)

    assert result_path == str(local_tmp_path / "combined.dxf")
    assert captured["entries"] == entries
    assert captured["scale_denom"] == 100
    assert captured["draw_case"] is tunnel_panel_mod.draw_tunnel_dxf_on_msp
    assert captured["draw_summary_table"] is tunnel_panel_mod.draw_tunnel_comparison_table
