# -*- coding: utf-8 -*-
"""
固定长度渐变段压缩 - 单元测试

测试当使用固定长度估算时，渐变段长度仍然不能超过IP点间距
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.calculator import WaterProfileCalculator


def test_fixed_length_compressed_to_distance():
    """测试固定长度（15m）被压缩到实际距离（5m）"""
    tunnel_outlet = ChannelNode()
    tunnel_outlet.structure_type = StructureType.from_string("隧洞-圆形")
    tunnel_outlet.name = "隧洞1"
    tunnel_outlet.in_out = InOutType.OUTLET
    tunnel_outlet.section_params = {"D": 2.0}
    tunnel_outlet.station_MC = 100.0

    gate = ChannelNode()
    gate.structure_type = StructureType.from_string("节制闸")
    gate.name = "节制闸1"
    gate.station_MC = 105.0  # 只有5m距离

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)

    # 不传入all_nodes，会使用固定长度15m
    result = calculator._check_gap_exit_to_gate(tunnel_outlet, gate)

    assert result['need_transition_1'] == True
    assert result['distance'] == 5.0
    # 即使固定长度是15m，也应该被压缩到5m
    assert result['transition_length_1'] == 5.0, f"Expected 5.0, got {result['transition_length_1']}"
    assert result['available_length'] == 0.0


def test_fixed_length_not_exceed_3m():
    """测试固定长度不超过3m的极小距离"""
    aqueduct_outlet = ChannelNode()
    aqueduct_outlet.structure_type = StructureType.from_string("渡槽-U形")
    aqueduct_outlet.name = "渡槽1"
    aqueduct_outlet.in_out = InOutType.OUTLET
    aqueduct_outlet.section_params = {"B": 2.0, "H": 2.5}
    aqueduct_outlet.station_MC = 200.0

    gate = ChannelNode()
    gate.structure_type = StructureType.from_string("分水闸")
    gate.name = "分水闸1"
    gate.station_MC = 203.0  # 只有3m距离

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_exit_to_gate(aqueduct_outlet, gate)

    assert result['need_transition_1'] == True
    assert result['distance'] == 3.0
    # 渐变段长度不能超过3m
    assert result['transition_length_1'] <= 3.0
    assert result['transition_length_1'] == 3.0


if __name__ == "__main__":
    print("Running fixed length compression tests...")

    test_fixed_length_compressed_to_distance()
    print("PASS: fixed_length_compressed_to_distance")

    test_fixed_length_not_exceed_3m()
    print("PASS: fixed_length_not_exceed_3m")

    print("\nAll fixed length compression tests passed!")
