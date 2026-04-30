# -*- coding: utf-8 -*-
"""隧洞 DXF 导出回归测试。"""

from collections import Counter
import importlib
import sys
from pathlib import Path
import shutil
import tempfile

import pytest

ezdxf = pytest.importorskip("ezdxf")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

tunnel_dxf_mod = importlib.import_module("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.tunnel.dxf_export")
dxf_multi_export = importlib.import_module("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.dxf_multi_export")
dxf_common = importlib.import_module("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.dxf_common")


@pytest.fixture
def local_tmp_path():
    base_dir = ROOT / ".pytest_tmp" / "tunnel_dxf_export_unit"
    base_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(dir=base_dir))
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _outline_entities(path):
    doc = ezdxf.readfile(str(path))
    return [entity for entity in doc.modelspace() if entity.dxf.layer == "轮廓线"]


def _poly_points(polyline):
    return [(float(x), float(y)) for x, y in polyline.get_points("xy")]


def _point2(point):
    return (float(point[0]), float(point[1]))


def _round_point(point, ndigits=4):
    return (round(float(point[0]), ndigits), round(float(point[1]), ndigits))


def _export_arch_dxf(path, theta_deg, H_total):
    result = {
        "B": 3.99 if theta_deg != 180 else 4.0,
        "H_total": H_total,
        "theta_deg": theta_deg,
        "h_design": min(2.835, H_total - 0.2),
        "V_design": 1.77,
        "A_design": 11.298,
        "freeboard_hgt_design": max(0.0, H_total - min(2.835, H_total - 0.2)),
        "Q_increased": 23.0,
        "h_increased": min(3.223, H_total - 0.05),
        "V_increased": 1.95,
        "freeboard_hgt_inc": max(0.0, H_total - min(3.223, H_total - 0.05)),
        "increase_percent": 15.0,
    }
    input_params = {
        "section_type": "圆拱直墙型",
        "Q": 20.0,
        "n": 0.014,
        "slope_inv": 2000.0,
    }
    tunnel_dxf_mod.export_tunnel_dxf(str(path), result, input_params, scale_denom=50)


def _export_std_horseshoe_dxf(path, section_type):
    result = {
        "r": 1.34,
        "h_design": 1.72,
        "V_design": 1.58,
        "A_design": 4.91,
        "freeboard_hgt_design": 0.96,
        "Q_increased": 7.2,
        "h_increased": 1.94,
        "V_increased": 1.66,
        "freeboard_hgt_inc": 0.74,
        "increase_percent": 20.0,
    }
    input_params = {
        "section_type": "马蹄形标准Ⅰ型" if section_type == 1 else "马蹄形标准Ⅱ型",
        "sec_type_int": section_type,
        "Q": 6.0,
        "n": 0.014,
        "slope_inv": 2000.0,
    }
    tunnel_dxf_mod.export_tunnel_dxf(str(path), result, input_params, scale_denom=50)


def test_arch_150_degree_uses_open_polyline_and_native_arc(local_tmp_path):
    path = local_tmp_path / "arch_150.dxf"
    _export_arch_dxf(path, theta_deg=150.0, H_total=4.15)

    outline = _outline_entities(path)
    counts = Counter(entity.dxftype() for entity in outline)

    assert counts["LWPOLYLINE"] == 1
    assert counts["ARC"] == 1
    assert counts["LINE"] == 0

    polyline = next(entity for entity in outline if entity.dxftype() == "LWPOLYLINE")
    arc = next(entity for entity in outline if entity.dxftype() == "ARC")
    points = _poly_points(polyline)

    assert len(points) == 4
    assert _round_point(points[0]) == _round_point(arc.end_point)
    assert _round_point(points[-1]) == _round_point(arc.start_point)


def test_arch_180_degree_handles_zero_straight_wall_without_gaps(local_tmp_path):
    path = local_tmp_path / "arch_180.dxf"
    _export_arch_dxf(path, theta_deg=180.0, H_total=2.0)

    outline = _outline_entities(path)
    counts = Counter(entity.dxftype() for entity in outline)

    assert counts["LWPOLYLINE"] == 1
    assert counts["ARC"] == 1
    assert counts["LINE"] == 0

    polyline = next(entity for entity in outline if entity.dxftype() == "LWPOLYLINE")
    arc = next(entity for entity in outline if entity.dxftype() == "ARC")
    points = _poly_points(polyline)

    assert len(points) == 2
    assert len({_round_point(point) for point in points}) == 2
    assert _round_point(points[0]) == _round_point(arc.end_point)
    assert _round_point(points[-1]) == _round_point(arc.start_point)


@pytest.mark.parametrize(
    ("section_type", "label"),
    [
        (1, "std_type_1"),
        (2, "std_type_2"),
    ],
)
def test_standard_horseshoe_exports_as_four_connected_arcs(local_tmp_path, section_type, label):
    path = local_tmp_path / f"{label}.dxf"
    _export_std_horseshoe_dxf(path, section_type)

    outline = _outline_entities(path)
    counts = Counter(entity.dxftype() for entity in outline)

    assert counts["ARC"] == 4
    assert counts["LINE"] == 0
    assert counts["LWPOLYLINE"] == 0

    arcs = [entity for entity in outline if entity.dxftype() == "ARC"]
    endpoint_counts = Counter()
    for arc in arcs:
        endpoint_counts[_round_point(_point2(arc.start_point))] += 1
        endpoint_counts[_round_point(_point2(arc.end_point))] += 1

    assert len(endpoint_counts) == 4
    assert set(endpoint_counts.values()) == {2}

    sf = 1000.0 / 50.0
    expected_r = 1.34 * sf
    top_arc = min(arcs, key=lambda entity: abs(float(entity.dxf.radius) - expected_r))

    assert float(top_arc.dxf.radius) == pytest.approx(expected_r, abs=1e-6)
    assert float(top_arc.dxf.center[1]) + float(top_arc.dxf.radius) == pytest.approx(2.0 * expected_r, abs=1e-6)


def test_tunnel_comparison_table_draws_expected_dxf_headers(local_tmp_path):
    """隧洞多工况 DXF 对比表应写出标题和核心列名。"""
    path = local_tmp_path / "comparison_table.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    entries = [
        dxf_multi_export.DxfExportCaseEntry(
            case_idx=0,
            label="低流量",
            input_params={"section_type": "圆形", "Q": 5.0, "use_increase": False},
            result={
                "success": True,
                "D": 3.0,
                "h_design": 1.5,
                "V_design": 1.2,
                "A_total": 7.069,
            },
            is_valid=True,
        ),
        dxf_multi_export.DxfExportCaseEntry(
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
                "A_total": 10.28,
            },
            is_valid=True,
        ),
    ]

    height = tunnel_dxf_mod.draw_tunnel_comparison_table(doc, msp, entries, 0.0, 0.0)
    doc.saveas(str(path))

    assert height > 0
    loaded = ezdxf.readfile(str(path))
    texts = [
        entity.dxf.text
        for entity in loaded.modelspace()
        if entity.dxftype() == "TEXT"
    ]
    mtexts = [
        entity.text
        for entity in loaded.modelspace()
        if entity.dxftype() == "MTEXT"
    ]
    assert "隧洞多工况参数对比表" in texts
    assert any(text.startswith("设计流速") for text in texts)
    assert any(text.startswith("洞身周长") for text in texts)
    assert any(text.startswith("洞身断面积") for text in texts)
    assert any("工况 2｜高流量" in text for text in texts)
    assert "(m3/s)" not in texts
    assert "(m2)" not in texts
    joined_mtexts = "".join(mtexts)
    assert "\\H0.7x" in joined_mtexts
    assert "\\S3^" in joined_mtexts
    assert "\\S2^" in joined_mtexts


def test_tunnel_comparison_table_expands_columns_for_long_content(local_tmp_path):
    """DXF 对比表列宽应按表头和内容自动适配。"""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    long_label = "圆拱直墙型超长工况名称用于验证列宽自动适配"
    entries = [
        dxf_multi_export.DxfExportCaseEntry(
            case_idx=0,
            label=long_label,
            input_params={"section_type": "圆拱直墙型", "Q": 10.0, "use_increase": True},
            result={
                "success": True,
                "B": 4.0,
                "H_total": 3.0,
                "H_straight": 1.0,
                "theta_deg": 180.0,
                "h_design": 2.0,
                "V_design": 1.7,
                "Q_increased": 12.0,
                "h_increased": 2.25,
                "V_increased": 1.9,
                "A_total": 10.28,
            },
            is_valid=True,
        ),
    ]

    tunnel_dxf_mod.draw_tunnel_comparison_table(doc, msp, entries, 0.0, 0.0)

    vertical_xs = sorted(
        {
            round(float(entity.dxf.start[0]), 6)
            for entity in msp
            if entity.dxftype() == "LINE"
            and abs(float(entity.dxf.start[0]) - float(entity.dxf.end[0])) < 1e-9
            and float(entity.dxf.start[0]) > 0.0
        }
    )

    assert vertical_xs
    assert vertical_xs[0] > 42.0


def test_tunnel_comparison_table_uses_default_dxf_text_width_factor(local_tmp_path):
    """共享 DXF 中文文字样式默认宽度因子应为 0.7。"""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    entries = [
        dxf_multi_export.DxfExportCaseEntry(
            case_idx=0,
            label="默认宽度",
            input_params={"section_type": "圆形", "Q": 5.0, "use_increase": False},
            result={"success": True, "D": 3.0, "h_design": 1.5, "V_design": 1.2, "A_total": 7.069},
            is_valid=True,
        ),
    ]

    tunnel_dxf_mod.draw_tunnel_comparison_table(doc, msp, entries, 0.0, 0.0)

    assert doc.styles.get("FANGSONG").dxf.width == pytest.approx(0.7)
    assert any(
        entity.dxftype() == "TEXT" and entity.dxf.width == pytest.approx(0.7)
        for entity in msp
    )
    assert any(
        entity.dxftype() == "MTEXT" and "\\H0.7x" in entity.text
        for entity in msp
    )


def test_dxf_common_converts_unicode_units_to_mtext_superscript():
    """DXF 共享工具应按 CAD MTEXT 规则转换上标单位。"""
    assert dxf_common.has_dxf_script_chars("m³/s")
    assert dxf_common.to_dxf_mtext_script("m³/s") == "m{\\H0.7x;\\S3^ ;}/s"
    assert dxf_common.to_dxf_mtext_script("m²") == "m{\\H0.7x;\\S2^ ;}"
