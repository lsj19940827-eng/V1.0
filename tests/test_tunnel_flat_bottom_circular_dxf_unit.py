# -*- coding: utf-8 -*-
"""平底圆形隧洞 DXF 导出回归测试。"""

from collections import Counter
import importlib
import math
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
tunnel_geometry_mod = importlib.import_module("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.tunnel.geometry")
tunnel_kernel_mod = importlib.import_module("calc_\u6e20\u7cfb\u8ba1\u7b97\u7b97\u6cd5\u5185\u6838.\u96a7\u6d1e\u8bbe\u8ba1")


@pytest.fixture
def local_tmp_path():
    base_dir = ROOT / ".pytest_tmp" / "tunnel_flat_bottom_circle_dxf_unit"
    base_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(dir=base_dir))
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _outline_entities(path):
    doc = ezdxf.readfile(str(path))
    return [entity for entity in doc.modelspace() if entity.dxf.layer == "轮廓线"]


def _all_text_entities(path):
    doc = ezdxf.readfile(str(path))
    return [
        entity.dxf.text
        for entity in doc.modelspace()
        if entity.dxftype() == "TEXT"
    ]


def _poly_points(polyline):
    return [(float(x), float(y)) for x, y in polyline.get_points("xy")]


def _round_point(point, ndigits=4):
    return (round(float(point[0]), ndigits), round(float(point[1]), ndigits))


def test_flat_bottom_circle_exports_as_bottom_polyline_plus_major_arc(local_tmp_path):
    """平底圆形 DXF 应导出为 1 条底边多段线 + 1 条原生圆弧。"""
    path = local_tmp_path / "flat_bottom_circle.dxf"
    result = {
        "section_type": "平底圆形",
        "B": 2.0,
        "D": 4.0,
        "H_total": 2.0 + math.sqrt(3.0),
        "h_design": 1.2,
        "V_design": 1.42,
        "A_design": 5.30,
        "freeboard_hgt_design": (2.0 + math.sqrt(3.0)) - 1.2,
        "Q_increased": 6.0,
        "h_increased": 1.45,
        "V_increased": 1.55,
        "freeboard_hgt_inc": (2.0 + math.sqrt(3.0)) - 1.45,
        "increase_percent": 20.0,
    }
    input_params = {
        "section_type": "平底圆形",
        "Q": 5.0,
        "n": 0.014,
        "slope_inv": 2000.0,
    }

    tunnel_dxf_mod.export_tunnel_dxf(str(path), result, input_params, scale_denom=50)

    outline = _outline_entities(path)
    counts = Counter(entity.dxftype() for entity in outline)

    assert counts["LWPOLYLINE"] == 1
    assert counts["ARC"] == 1
    assert counts["LINE"] == 0

    polyline = next(entity for entity in outline if entity.dxftype() == "LWPOLYLINE")
    arc = next(entity for entity in outline if entity.dxftype() == "ARC")
    points = _poly_points(polyline)

    assert len(points) == 2
    assert _round_point(points[0]) == _round_point(arc.end_point)
    assert _round_point(points[-1]) == _round_point(arc.start_point)


def test_flat_bottom_circle_dxf_prefers_geometry_derived_height_when_result_height_is_stale(local_tmp_path):
    """DXF 的总高文字与标注应以 D/B 推导值为准，不跟随过期 H_total。"""
    path = local_tmp_path / "flat_bottom_circle_stale_height.dxf"
    derived_height = 2.0 + math.sqrt(3.0)
    result = {
        "section_type": "平底圆形",
        "B": 2.0,
        "D": 4.0,
        "H_total": 5.0,
        "h_design": 1.2,
        "V_design": 1.42,
        "A_design": 5.30,
        "freeboard_hgt_design": derived_height - 1.2,
        "Q_increased": 6.0,
        "h_increased": 1.45,
        "V_increased": 1.55,
        "freeboard_hgt_inc": derived_height - 1.45,
        "increase_percent": 20.0,
    }
    input_params = {
        "section_type": "平底圆形",
        "Q": 5.0,
        "n": 0.014,
        "slope_inv": 2000.0,
    }

    tunnel_dxf_mod.export_tunnel_dxf(str(path), result, input_params, scale_denom=50)

    texts = _all_text_entities(path)

    assert any("H=3.732 m" in text for text in texts)
    assert all("H=5.000 m" not in text for text in texts)


def test_flat_bottom_circle_dxf_height_dimension_uses_geometry_height(local_tmp_path):
    """DXF 总高标注应以 D/B 推导几何为准，不应直接采用外部旧 H_total。"""
    path = local_tmp_path / "flat_bottom_circle_height_sync.dxf"
    derived_height = 2.0 + math.sqrt(3.0)
    result = {
        "section_type": "平底圆形",
        "B": 2.0,
        "D": 4.0,
        "H_total": 9.999,
        "h_design": 1.2,
        "V_design": 1.42,
        "A_design": 5.30,
        "freeboard_hgt_design": derived_height - 1.2,
        "Q_increased": 6.0,
        "h_increased": 1.45,
        "V_increased": 1.55,
        "freeboard_hgt_inc": derived_height - 1.45,
        "increase_percent": 20.0,
    }
    input_params = {
        "section_type": "平底圆形",
        "Q": 5.0,
        "n": 0.014,
        "slope_inv": 2000.0,
    }

    tunnel_dxf_mod.export_tunnel_dxf(str(path), result, input_params, scale_denom=50)

    doc = ezdxf.readfile(str(path))
    dim_texts = [entity.dxf.text for entity in doc.modelspace() if entity.dxftype() == "DIMENSION"]

    assert f"H={derived_height:.3f} m" in dim_texts
    assert "H=9.999 m" not in dim_texts


def test_flat_bottom_circle_surface_width_matches_kernel_near_zero_depth():
    """极小正水深下，前端几何与内核应使用同一条水面宽边界口径。"""
    geom = tunnel_geometry_mod.build_flat_bottom_circle_geometry(4.0, 2.0)
    tiny_depth = 1e-10

    front_width = tunnel_geometry_mod.flat_bottom_circle_surface_width(geom, tiny_depth)
    kernel_width = tunnel_kernel_mod.calculate_flat_bottom_circular_surface_width(4.0, 2.0, tiny_depth)

    assert front_width == pytest.approx(kernel_width)
