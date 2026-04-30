# -*- coding: utf-8 -*-
"""渡槽 DXF 导出的拉杆高度标注回归测试。"""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_渠系计算前端.aqueduct.dxf_export import draw_aqueduct_dxf_on_msp


class _FakeTextEntity:
    """模拟 DXF 文本实体的定位接口。"""

    def set_placement(self, *_args, **_kwargs):
        return self


class _FakeDimEntity:
    """模拟 DXF 标注实体的渲染接口。"""

    def render(self):
        return self


class _FakeMsp:
    """记录 DXF 绘图调用，避免依赖 ezdxf。"""

    def __init__(self):
        self.lines = []
        self.texts = []
        self.polylines = []
        self.dims = []

    def add_line(self, start, end, dxfattribs=None):
        self.lines.append({"start": start, "end": end, "attrs": dict(dxfattribs or {})})

    def add_lwpolyline(self, points, dxfattribs=None):
        self.polylines.append({"points": list(points), "attrs": dict(dxfattribs or {})})

    def add_text(self, text, dxfattribs=None):
        self.texts.append({"text": str(text), "attrs": dict(dxfattribs or {})})
        return _FakeTextEntity()

    def add_linear_dim(self, *args, **kwargs):
        self.dims.append({"args": args, "kwargs": kwargs})
        return _FakeDimEntity()


@pytest.mark.parametrize(
    ("section_type", "result"),
    [
        (
            "U形",
            {
                "success": True,
                "section_type": "U形",
                "R": 1.4,
                "f": 0.95,
                "B": 2.8,
                "H_total": 2.35,
                "h_design": 1.65,
                "h_increased": 1.70,
                "V_design": 1.10,
                "V_increased": 1.20,
                "A_design": 2.0,
                "Fb": 0.30,
                "Fb_design": 0.70,
                "design_tie_bottom_clearance": 0.35,
                "tie_rod_height": 0.35,
                "tie_bottom_height": 2.0,
                "top_clearance": 0.65,
            },
        ),
        (
            "矩形",
            {
                "success": True,
                "section_type": "矩形",
                "B": 2.8,
                "H_total": 2.35,
                "h_design": 1.65,
                "h_increased": 1.70,
                "V_design": 1.10,
                "V_increased": 1.20,
                "A_design": 4.6,
                "Fb": 0.30,
                "Fb_design": 0.70,
                "design_tie_bottom_clearance": 0.35,
                "tie_rod_height": 0.35,
                "tie_bottom_height": 2.0,
                "top_clearance": 0.65,
            },
        ),
    ],
)
def test_aqueduct_dxf_marks_tie_rod_control_height(section_type, result):
    fake_msp = _FakeMsp()

    draw_aqueduct_dxf_on_msp(
        fake_msp,
        result,
        {
            "section_type": section_type,
            "Q": 5.0,
            "n": 0.014,
            "slope_inv": 3000,
            "use_increase": True,
        },
        scale_denom=100,
    )

    texts = [item["text"] for item in fake_msp.texts]
    dim_texts = [item["kwargs"].get("text", "") for item in fake_msp.dims]
    layers = [item["attrs"].get("layer", "") for item in fake_msp.lines + fake_msp.polylines]

    assert any("拉杆高度" in text for text in texts + dim_texts)
    assert any("拉杆底" in text for text in texts)
    assert any("设计拉杆底净距" in text for text in texts + dim_texts)
    assert any("加大有效超高" in text for text in texts + dim_texts)
    assert any("拉杆" in layer for layer in layers)


def test_aqueduct_dxf_hides_increase_when_disabled():
    fake_msp = _FakeMsp()

    draw_aqueduct_dxf_on_msp(
        fake_msp,
        {
            "success": True,
            "section_type": "U形",
            "R": 1.4,
            "f": 0.95,
            "B": 2.8,
            "H_total": 2.35,
            "h_design": 1.65,
            "h_increased": 1.65,
            "V_design": 1.10,
            "V_increased": 1.10,
            "A_design": 2.0,
            "Fb": 0.70,
            "Fb_design": 0.70,
            "tie_rod_height": 0.0,
        },
        {
            "section_type": "U形",
            "Q": 5.0,
            "n": 0.014,
            "slope_inv": 3000,
            "use_increase": False,
        },
        scale_denom=100,
    )

    texts = [item["text"] for item in fake_msp.texts]
    dim_texts = [item["kwargs"].get("text", "") for item in fake_msp.dims]
    all_text = texts + dim_texts

    assert not any("加大水位" in text for text in texts)
    assert not any("[加大流量]" in text for text in texts)
    assert not any("加大有效超高" in text for text in all_text)
