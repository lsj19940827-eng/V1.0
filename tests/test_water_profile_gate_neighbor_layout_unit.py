# -*- coding: utf-8 -*-
"""闸两侧水位文字须避开真实相邻水位字框，DXF和TXT采用同一空间约束。"""

from io import StringIO
import re

import ezdxf
from ezdxf import bbox
import pytest

from test_water_profile_gate_export_unit import cad_tools, _gate_texts, _node, _settings


def _roundtrip(nodes, settings=None):
    """使用正式纵断面字体设置后真实写出和回读，保留实际导出字框。"""
    document = ezdxf.new("R2010")
    cad_tools._setup_profile_dxf_document(document)
    cad_tools._draw_profile_on_msp(document.modelspace(), nodes, nodes, settings or _settings(), "")
    stream = StringIO()
    document.write(stream)
    stream.seek(0)
    return ezdxf.read(stream)


def _feilong_gate_neighbors():
    """复用2026-10-12原始飞龙Excel实算的双桥闸及实际相邻可见节点快照。"""
    # 原始Excel SHA256：49401a75d750d4efd039bbb82eb7a72da6dfa07f3ce7b6234f4d74663a2c8a2e。
    # 首个节点同样保留真实结果，避免将催龙寺误当首列而改变原文字插入位置。
    return [
        _node(0.0, 359.27, name="花朝门", bottom=358.5008288067627, top=360.5008288067627),
        _node(4458.324571588561, 356.82844100000005, name="催龙寺", bottom=356.00568120751956, top=358.00568120751956),
        _node(4468.695905710041, 356.72663700000004, gate=True, name="双桥", bottom=355.904, top=357.32, head_loss_gate=0.1,
              gate_upstream_water_level=356.82663700000006, gate_downstream_water_level=356.72663700000004),
        _node(4476.875588032072, 356.708546, name="催龙村", bottom=356.01, top=357.31),
    ]


def _assert_neighbor_water_boxes_clear(document, texts, minimum_gap=0.25):
    entities = {entity.dxf.text: entity for entity in document.modelspace().query("TEXT") if entity.dxf.text in texts}
    assert set(entities) == set(texts)
    left, first_gate, second_gate, right = [bbox.extents([entities[text]]) for text in texts]
    # 闸前/闸后在横排时上下错开，不要求二者的轴对齐字框也在水平方向分离。
    assert min(first_gate.extmin.x, second_gate.extmin.x) - left.extmax.x >= minimum_gap
    assert right.extmin.x - max(first_gate.extmax.x, second_gate.extmax.x) >= minimum_gap


def test_real_feilong_neighbor_dxf_has_clear_gate_labels_and_unchanged_water_drop():
    """原飞龙邻近普通水位与闸前标注曾重叠，正式DXF回读应留出净距。"""
    nodes = _feilong_gate_neighbors()
    document = _roundtrip(nodes)
    labels = ("356.828", "闸前356.827", "闸后356.727", "356.709")
    _assert_neighbor_water_boxes_clear(document, labels)
    gate_entities = _gate_texts(document)
    assert all(0 < entity.dxf.height < 1.666666666666667 for entity in gate_entities)
    assert {entity.dxf.rotation for entity in gate_entities} == {90}
    ordinary = [entity for entity in document.modelspace().query("TEXT") if entity.dxf.text in (labels[0], labels[-1])]
    assert {entity.dxf.height for entity in ordinary} == {3.5}
    water_line = next(entity for entity in document.modelspace().query("LWPOLYLINE") if entity.dxf.layer == "设计水位线")
    points = [(point[0], point[1]) for point in water_line]
    gate_x = nodes[2].station_MC / 2
    assert (gate_x, nodes[2].gate_upstream_water_level) in points
    assert (gate_x, nodes[2].gate_downstream_water_level) in points


def test_real_feilong_neighbor_txt_keeps_clearance_without_dxf_width_compression():
    """按TXT实际未压缩字宽重建实体，防止依赖DXF的0.7字宽系数假通过。"""
    nodes = _feilong_gate_neighbors()
    lines = cad_tools._build_standard_longitudinal_txt_lines(nodes, nodes, _settings())
    labels = ("356.828", "闸前356.827", "闸后356.727", "356.709")
    document = ezdxf.new("R2010")
    cad_tools._setup_profile_dxf_document(document)
    document.styles.get("Standard").dxf.width = 1.0
    for line in lines:
        match = re.fullmatch(r"-text ([^ ,]+),([^ ]+) ([^ ]+) ([^ ]+) (.+) ", line)
        if match and match[5] in labels:
            x, y, height, rotation = [float(match[index]) for index in range(1, 5)]
            document.modelspace().add_text(match[5], dxfattribs={"height": height, "rotation": rotation, "width": 1.0}).set_placement((x, y))
    _assert_neighbor_water_boxes_clear(document, labels)
    assert len(_gate_texts(document)) == 2
    dxf_gate_heights = {entity.dxf.height for entity in _gate_texts(_roundtrip(nodes))}
    # 两种格式普通文字原插入点相差1mm，邻居净距相同，因此自动字高也一致。
    assert next(iter(dxf_gate_heights)) == pytest.approx(_gate_texts(document)[0].dxf.height, abs=0.001)


@pytest.mark.parametrize("rotation", [0, 45, 90, 180, 270])
def test_neighbor_water_clearance_uses_rotated_text_bounds(rotation):
    """其他既有旋转角度继续在原水位行内排布，并避开前后普通水位。"""
    nodes = [_node(0, 200), _node(100, 123.456), _node(200, 123.356, gate=True, head_loss_gate=0.1), _node(300, 123.256)]
    settings = _settings(rotation=rotation)
    document = _roundtrip(nodes, settings)
    _assert_neighbor_water_boxes_clear(document, ("123.456", "闸前123.456", "闸后123.356", "123.256"))
    _, rows, _, _, _ = cad_tools._build_profile_row_layout(settings)
    water_row = rows["water_elev"]
    for entity in _gate_texts(document):
        bounds = bbox.extents([entity])
        assert water_row["bottom"] <= bounds.extmin.y < bounds.extmax.y <= water_row["top"]
