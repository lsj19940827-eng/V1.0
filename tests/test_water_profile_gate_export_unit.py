# -*- coding: utf-8 -*-
"""闸前后水位、缺失高程及真实 DXF 导出回读回归。"""

from io import StringIO
import importlib
from pathlib import Path
import math
import re
import sys
from types import SimpleNamespace

import ezdxf
from ezdxf import bbox
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
cad_tools = importlib.import_module("app_渠系计算前端.water_profile.cad_tools")


class _Node(SimpleNamespace):
    def get_structure_type_str(self):
        return self.structure_type.value


def _node(station, water, *, gate=False, bottom=0.0, top=0.0, **kwargs):
    fields = dict(
        station_MC=station, station_BC=station, station_EC=station,
        water_level=water, bottom_elevation=bottom, top_elevation=top,
        structure_type=SimpleNamespace(value="节制闸" if gate else "明渠-矩形"),
        name="一号" if gate else "", ip_number=int(station) + 1,
        x=station, y=0.0, in_out=None, slope_i=1 / 2000,
        is_transition=False, turn_angle=0.0,
    )
    fields.update(kwargs)
    return _Node(**fields)


def _settings(**kwargs):
    settings = dict(
        text_height=3.5, rotation=90, elev_decimals=3,
        station_decimals=2, scale_x=2000, scale_y=1000,
        y_line_height=120, profile_row_items=cad_tools._default_profile_row_items(),
    )
    settings.update(kwargs)
    return settings


def _sample_nodes():
    return [
        _node(0.0, 100.0, bottom=98.8, top=101.3),
        _node(100.0, 99.9, gate=True, head_loss_gate=0.1),
        _node(200.0, 99.8, bottom=98.6, top=101.1),
    ]


def _roundtrip(nodes, settings=None):
    document = ezdxf.new("R2010")
    cad_tools._draw_profile_on_msp(document.modelspace(), nodes, nodes, settings or _settings(), "")
    stream = StringIO()
    document.write(stream)
    stream.seek(0)
    return ezdxf.read(stream)


def _gate_texts(document):
    return [entity for entity in document.modelspace().query("TEXT") if entity.dxf.text.startswith(("闸前", "闸后"))]


def test_real_dxf_roundtrip_preserves_gate_sides_and_vertical_drop():
    nodes = _sample_nodes()
    originals = [vars(node).copy() for node in nodes]
    document = _roundtrip(nodes)
    assert {entity.dxf.text for entity in _gate_texts(document)} == {"闸前100.000", "闸后99.900"}
    water_line = next(entity for entity in document.modelspace().query("LWPOLYLINE") if entity.dxf.layer == "设计水位线")
    assert [(point[0], point[1]) for point in water_line] == pytest.approx([
        (0.0, 100.0), (50.0, 100.0), (50.0, 99.9), (100.0, 99.8),
    ])
    assert [vars(node) for node in nodes] == originals
    for entity in _gate_texts(document):
        assert bbox.extents([entity]).extmax.x < 50.0


def test_full_calculation_exports_gate_bottom_top_and_both_water_levels():
    from 推求水面线.core.calculator import WaterProfileCalculator
    from 推求水面线.models.data_models import ChannelNode, ProjectSettings
    from 推求水面线.models.enums import StructureType

    nodes = []
    for index, structure in enumerate((StructureType.MINGQU_RECTANGULAR, StructureType.CHECK_GATE, StructureType.MINGQU_RECTANGULAR)):
        node = ChannelNode(name=("上游明渠", "中间闸", "下游明渠")[index], structure_type=structure, flow_section="1", x=index * 100, flow=2)
        if index != 1:
            node.water_depth = 1.2
            node.structure_height = 2.5
            node.slope_i = 0.001
            node.section_params = {"B": 2, "h": 1.2, "H": 2.5}
        nodes.append(node)
    WaterProfileCalculator(ProjectSettings(start_water_level=100, design_flows=[2])).calculate_all(nodes)
    document = _roundtrip(nodes)
    texts = [entity.dxf.text for entity in document.modelspace().query("TEXT")]
    assert all(text in texts for text in ("闸前99.900", "闸后99.800", "98.700", "101.200"))
    for layer, level in (("渠底高程线", 98.7), ("渠顶高程线", 101.2)):
        polyline = next(entity for entity in document.modelspace().query("LWPOLYLINE") if entity.dxf.layer == layer)
        assert (50.0, level) in [(point[0], point[1]) for point in polyline]


def test_full_calculation_preserves_proven_zero_gate_bottom_in_dxf_and_txt():
    from 推求水面线.core.calculator import WaterProfileCalculator
    from 推求水面线.models.data_models import ChannelNode, ProjectSettings
    from 推求水面线.models.enums import StructureType

    nodes = []
    for index, structure in enumerate((StructureType.MINGQU_RECTANGULAR, StructureType.CHECK_GATE, StructureType.MINGQU_RECTANGULAR)):
        node = ChannelNode(name=("上游明渠", "零底高程闸", "下游明渠")[index], structure_type=structure, flow_section="1", x=index * 100, flow=2)
        if index != 1:
            node.water_depth = 1.2
            node.structure_height = 2.5
            node.slope_i = 0.001
            node.section_params = {"B": 2, "h": 1.2, "H": 2.5}
        nodes.append(node)
    WaterProfileCalculator(ProjectSettings(start_water_level=1.3, design_flows=[2])).calculate_all(nodes)
    assert nodes[1].bottom_elevation == 0.0
    assert nodes[1].terminal_gate_backfill_details["bottom"]["success"] is True
    document = _roundtrip(nodes)
    texts = [entity.dxf.text for entity in document.modelspace().query("TEXT")]
    assert all(text in texts for text in ("闸前1.200", "闸后1.100", "0.000", "2.500"))
    for layer, level in (("渠底高程线", 0.0), ("渠顶高程线", 2.5)):
        polyline = next(entity for entity in document.modelspace().query("LWPOLYLINE") if entity.dxf.layer == layer)
        assert (50.0, level) in [(point[0], point[1]) for point in polyline]
    water_line = next(entity for entity in document.modelspace().query("LWPOLYLINE") if entity.dxf.layer == "设计水位线")
    water_points = [(point[0], point[1]) for point in water_line]
    assert len(water_points) == 4
    for point, expected in zip(water_points, ((0.0, 1.3), (50.0, 1.2), (50.0, 1.1), (100.0, 1.0))):
        assert point == pytest.approx(expected)
    text = "\n".join(cad_tools._build_standard_longitudinal_txt_lines(nodes, nodes, _settings()))
    assert re.search(r"-text 50,.* 0\.000 ", text)
    assert re.search(r"-text 50,.* 2\.500 ", text)
    assert "pl 50,0\n" in text and "pl 50,2.5\n" in text
    assert "闸前1.200" in text and "闸后1.100" in text
    assert "pl 50,1.2\npl 50,1.1" in text


@pytest.mark.parametrize("attr_name,detail_key", [("bottom_elevation", "bottom"), ("top_elevation", "top")])
def test_proven_zero_gate_elevation_is_shared_by_dxf_text_and_polyline(attr_name, detail_key):
    nodes = _sample_nodes()
    setattr(nodes[1], attr_name, 0.0)
    nodes[1].terminal_gate_backfill_details = {detail_key: {"success": True, "result": 0.0}}
    document = _roundtrip(nodes)
    layer = "渠底高程线" if detail_key == "bottom" else "渠顶高程线"
    polyline = next(entity for entity in document.modelspace().query("LWPOLYLINE") if entity.dxf.layer == layer)
    assert (50.0, 0.0) in [(point[0], point[1]) for point in polyline]
    assert any(entity.dxf.text == "0.000" for entity in document.modelspace().query("TEXT"))


@pytest.mark.parametrize("details", [
    {}, {"bottom": {"success": False, "result": 0.0}},
    {"bottom": {"success": True, "result": 1.0}},
    {"bottom": {"success": True, "result": float("nan")}},
])
def test_unproven_gate_zero_elevation_still_exports_as_missing(details):
    nodes = _sample_nodes()
    nodes[1].terminal_gate_backfill_details = details
    document = _roundtrip(nodes)
    texts = [entity.dxf.text for entity in document.modelspace().query("TEXT")]
    assert "0.000" not in texts and texts.count("—") == 2
    for entity in document.modelspace().query("LWPOLYLINE"):
        if entity.dxf.layer in {"渠底高程线", "渠顶高程线"}:
            assert (50.0, 0.0) not in [(point[0], point[1]) for point in entity]


def test_missing_elevations_are_dash_and_never_create_zero_elevation_points():
    nodes = _sample_nodes()
    nodes[1].bottom_elevation = None
    nodes[1].top_elevation = float("nan")
    document = _roundtrip(nodes)
    texts = [entity.dxf.text for entity in document.modelspace().query("TEXT")]
    assert texts.count("—") == 2
    assert "0.000" not in texts
    for entity in document.modelspace().query("LWPOLYLINE"):
        if entity.dxf.layer in {"渠底高程线", "渠顶高程线"}:
            assert all(point[1] != 0.0 and math.isfinite(point[1]) for point in entity)


def test_explicit_zero_and_negative_gate_water_levels_are_exported():
    nodes = [
        _node(0.0, -0.5, bottom=-2.0, top=-0.2),
        _node(100.0, -1.0, gate=True, gate_upstream_water_level=0.0, gate_downstream_water_level=-1.0),
        _node(200.0, -1.1, bottom=-2.1, top=-0.3),
    ]
    document = _roundtrip(nodes)
    assert {entity.dxf.text for entity in _gate_texts(document)} == {"闸前0.000", "闸后-1.000"}
    water_line = next(entity for entity in document.modelspace().query("LWPOLYLINE") if entity.dxf.layer == "设计水位线")
    assert (50.0, 0.0) in [(point[0], point[1]) for point in water_line]
    assert any(entity.dxf.text == "-2.000" for entity in document.modelspace().query("TEXT"))


def test_first_gate_has_no_invented_upstream_level():
    nodes = [_node(0.0, 100.0, gate=True), _node(200.0, 99.8, bottom=98.6, top=101.1)]
    document = _roundtrip(nodes)
    assert {entity.dxf.text for entity in _gate_texts(document)} == {"闸前—", "闸后100.000"}


def test_txt_preserves_both_sides_dash_and_drop_points():
    nodes = _sample_nodes()
    lines = cad_tools._build_standard_longitudinal_txt_lines(nodes, nodes, _settings())
    text = "\n".join(lines)
    assert "闸前100.000" in text and "闸后99.900" in text
    assert text.count(" — ") == 2
    assert not re.search(r"-text .* 0\.000 ", text)
    assert "pl 50,100\npl 50,99.9" in text


@pytest.mark.parametrize("rotation", [0, 45, 90, 180, 270])
@pytest.mark.parametrize("text_height", [3.5, 8.0])
def test_gate_rotated_text_boxes_fit_water_row_without_overlap(rotation, text_height):
    settings = _settings(rotation=rotation, text_height=text_height)
    nodes = _sample_nodes()
    nodes[0].water_level = -12345.678
    nodes[1].water_level = -12345.778
    document = _roundtrip(nodes, settings)
    _, row_layout, _, _, _ = cad_tools._build_profile_row_layout(settings)
    row = row_layout["water_elev"]
    entities = _gate_texts(document)
    assert len(entities) == 2
    boxes = [bbox.extents([entity]) for entity in entities]
    for box in boxes:
        assert row["bottom"] <= box.extmin.y
        assert box.extmax.y <= row["top"]
    normal = (-math.sin(math.radians(rotation)), math.cos(math.radians(rotation)))
    intervals = []
    for box in boxes:
        projected = [
            x * normal[0] + y * normal[1]
            for x in (box.extmin.x, box.extmax.x)
            for y in (box.extmin.y, box.extmax.y)
        ]
        intervals.append((min(projected), max(projected)))
    # 斜排的轴对齐字框会互相穿入，实际文字法向间距仍须大于字高加下降部。
    if rotation in (0, 90, 180, 270):
        intervals.sort()
        assert intervals[0][1] < intervals[1][0]
    assert entities[0].dxf.insert != entities[1].dxf.insert


def test_gate_same_station_sides_merge_without_ordinary_water_conflict():
    nodes = [
        _node(0.0, 100.0), _node(100.0, 100.0),
        _node(100.0, 99.9, gate=True, head_loss_gate=0.1), _node(100.0, 99.9),
        _node(200.0, 99.8),
    ]
    merged = cad_tools._build_profile_text_nodes(nodes)
    assert len(merged) == 3
    assert merged[1].gate_upstream_water_level == 100.0
    assert merged[1].gate_downstream_water_level == 99.9
    assert merged[1].water_level == 99.9
    document = _roundtrip(nodes)
    water_line = next(entity for entity in document.modelspace().query("LWPOLYLINE") if entity.dxf.layer == "设计水位线")
    points = [(point[0], point[1]) for point in water_line]
    assert points == pytest.approx([(0, 100), (50, 100), (50, 99.9), (100, 99.8)])


def test_same_station_unknown_water_conflict_still_fails():
    with pytest.raises(ValueError, match="同桩号"):
        cad_tools._build_profile_text_nodes([_node(100, 100), _node(100, 98)])
    with pytest.raises(ValueError, match="同桩号"):
        cad_tools._build_profile_text_nodes([_node(0, 100), _node(100, 99.9, gate=True), _node(100, 98)])


def test_identical_gate_zero_loss_boundary_duplicates_merge_once():
    nodes = [
        _node(0, 100), _node(100, 99.9, gate=True, head_loss_gate=0.1),
        _node(100, 99.9, gate=True, head_loss_gate=0.0), _node(200, 99.8),
    ]
    merged = cad_tools._build_profile_text_nodes(nodes)
    assert len(merged) == 3
    assert merged[1].gate_upstream_water_level == 100
    document = _roundtrip(nodes)
    assert len(_gate_texts(document)) == 2


def test_distinct_gates_or_repeated_nonzero_loss_same_station_fail_clearly():
    for kwargs in (dict(name="二号"), dict(head_loss_gate=0.1)):
        nodes = [
            _node(0, 100), _node(100, 99.9, gate=True, head_loss_gate=0.1),
            _node(100, 99.8, gate=True, **kwargs),
        ]
        with pytest.raises(ValueError, match="多个闸"):
            cad_tools._build_profile_text_nodes(nodes)
