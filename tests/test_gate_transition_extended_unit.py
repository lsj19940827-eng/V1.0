# -*- coding: utf-8 -*-
"""
闸与特殊建筑物渐变段插入 - 扩展单元测试

测试隧洞/渡槽/矩形暗涵与闸之间的渐变段插入逻辑：
- 隧洞出口 → 闸：需要插入出口渐变段，skip_loss=True
- 闸 → 隧洞进口：需要插入进口渐变段，skip_loss=True
- 渡槽出口 → 闸：需要插入出口渐变段，skip_loss=True
- 闸 → 渡槽进口：需要插入进口渐变段，skip_loss=True
- 矩形暗涵出口 → 闸：需要插入出口渐变段，skip_loss=True
- 闸 → 矩形暗涵进口：需要插入进口渐变段，skip_loss=True
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.calculator import WaterProfileCalculator


def test_tunnel_outlet_to_gate():
    """测试隧洞出口 → 闸"""
    tunnel_outlet = ChannelNode()
    tunnel_outlet.structure_type = StructureType.from_string("隧洞-圆形")
    tunnel_outlet.name = "隧洞1"
    tunnel_outlet.in_out = InOutType.OUTLET
    tunnel_outlet.section_params = {"D": 2.0}
    tunnel_outlet.station_MC = 100.0

    gate = ChannelNode()
    gate.structure_type = StructureType.from_string("节制闸")
    gate.name = "节制闸1"
    gate.station_MC = 120.0

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_exit_to_gate(tunnel_outlet, gate)

    assert result['need_transition_1'] == True, "应识别需要插入隧洞出口渐变段"
    assert result['skip_loss_transition_1'] == True, "隧洞侧渐变段应标记 skip_loss=True"
    assert result['distance'] == 20.0


def test_gate_to_tunnel_inlet():
    """测试闸 → 隧洞进口"""
    gate = ChannelNode()
    gate.structure_type = StructureType.from_string("分水闸")
    gate.name = "分水闸1"
    gate.station_MC = 200.0

    tunnel_inlet = ChannelNode()
    tunnel_inlet.structure_type = StructureType.from_string("隧洞-圆拱直墙型")
    tunnel_inlet.name = "隧洞2"
    tunnel_inlet.in_out = InOutType.INLET
    tunnel_inlet.section_params = {"B": 2.5, "H": 3.0}
    tunnel_inlet.station_MC = 225.0

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_gate_to_entry(gate, tunnel_inlet)

    assert result['need_transition_2'] == True, "应识别需要插入隧洞进口渐变段"
    assert result['skip_loss_transition_2'] == True, "隧洞侧渐变段应标记 skip_loss=True"
    assert result['distance'] == 25.0


def test_aqueduct_outlet_to_gate():
    """测试渡槽出口 → 闸"""
    aqueduct_outlet = ChannelNode()
    aqueduct_outlet.structure_type = StructureType.from_string("渡槽-U形")
    aqueduct_outlet.name = "渡槽1"
    aqueduct_outlet.in_out = InOutType.OUTLET
    aqueduct_outlet.section_params = {"B": 1.5, "H": 2.0}
    aqueduct_outlet.station_MC = 300.0

    gate = ChannelNode()
    gate.structure_type = StructureType.from_string("泄水闸")
    gate.name = "泄水闸1"
    gate.station_MC = 318.0

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_exit_to_gate(aqueduct_outlet, gate)

    assert result['need_transition_1'] == True, "应识别需要插入渡槽出口渐变段"
    assert result['skip_loss_transition_1'] == True, "渡槽侧渐变段应标记 skip_loss=True"
    assert result['distance'] == 18.0


def test_gate_to_aqueduct_inlet():
    """测试闸 → 渡槽进口"""
    gate = ChannelNode()
    gate.structure_type = StructureType.from_string("节制闸")
    gate.name = "节制闸2"
    gate.station_MC = 400.0

    aqueduct_inlet = ChannelNode()
    aqueduct_inlet.structure_type = StructureType.from_string("渡槽-矩形")
    aqueduct_inlet.name = "渡槽2"
    aqueduct_inlet.in_out = InOutType.INLET
    aqueduct_inlet.section_params = {"B": 2.0, "H": 2.5}
    aqueduct_inlet.station_MC = 422.0

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_gate_to_entry(gate, aqueduct_inlet)

    assert result['need_transition_2'] == True, "应识别需要插入渡槽进口渐变段"
    assert result['skip_loss_transition_2'] == True, "渡槽侧渐变段应标记 skip_loss=True"
    assert result['distance'] == 22.0


def test_culvert_outlet_to_gate():
    """测试矩形暗涵出口 → 闸"""
    culvert_outlet = ChannelNode()
    culvert_outlet.structure_type = StructureType.from_string("矩形暗涵")
    culvert_outlet.name = "矩形暗涵1"
    culvert_outlet.in_out = InOutType.OUTLET
    culvert_outlet.section_params = {"B": 1.8, "H": 2.2}
    culvert_outlet.station_MC = 500.0

    gate = ChannelNode()
    gate.structure_type = StructureType.from_string("分水口")
    gate.name = "分水口1"
    gate.station_MC = 515.0

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_exit_to_gate(culvert_outlet, gate)

    assert result['need_transition_1'] == True, "应识别需要插入矩形暗涵出口渐变段"
    assert result['skip_loss_transition_1'] == True, "矩形暗涵侧渐变段应标记 skip_loss=True"
    assert result['distance'] == 15.0


def test_gate_to_culvert_inlet():
    """测试闸 → 矩形暗涵进口"""
    gate = ChannelNode()
    gate.structure_type = StructureType.from_string("分水闸")
    gate.name = "分水闸2"
    gate.station_MC = 600.0

    culvert_inlet = ChannelNode()
    culvert_inlet.structure_type = StructureType.from_string("矩形暗涵")
    culvert_inlet.name = "矩形暗涵2"
    culvert_inlet.in_out = InOutType.INLET
    culvert_inlet.section_params = {"B": 2.0, "H": 2.5}
    culvert_inlet.station_MC = 620.0

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_gate_to_entry(gate, culvert_inlet)

    assert result['need_transition_2'] == True, "应识别需要插入矩形暗涵进口渐变段"
    assert result['skip_loss_transition_2'] == True, "矩形暗涵侧渐变段应标记 skip_loss=True"
    assert result['distance'] == 20.0


if __name__ == "__main__":
    print("Running extended gate transition tests...")

    test_tunnel_outlet_to_gate()
    print("PASS: tunnel_outlet_to_gate")

    test_gate_to_tunnel_inlet()
    print("PASS: gate_to_tunnel_inlet")

    test_aqueduct_outlet_to_gate()
    print("PASS: aqueduct_outlet_to_gate")

    test_gate_to_aqueduct_inlet()
    print("PASS: gate_to_aqueduct_inlet")

    test_culvert_outlet_to_gate()
    print("PASS: culvert_outlet_to_gate")

    test_gate_to_culvert_inlet()
    print("PASS: gate_to_culvert_inlet")

    print("\nAll extended tests passed!")
