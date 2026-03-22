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
