# -*- coding: utf-8 -*-
"""
渐变段长度压缩 - 单元测试

测试当渐变段长度超过可用里程时的压缩逻辑：
- 单个渐变段超限：压缩到可用里程
- 出口+进口都需要时：合并为单个渐变段
- 明渠段判断：基于压缩后的长度
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.calculator import WaterProfileCalculator


def test_single_transition_compression():
    """测试单个渐变段被压缩到可用里程"""
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
    result = calculator._check_gap_exit_to_gate(tunnel_outlet, gate)

    assert result['need_transition_1'] == True
    assert result['distance'] == 5.0
    # 渐变段长度应该被压缩到5m（不超过可用里程）
    assert result['transition_length_1'] <= 5.0
    assert result['available_length'] >= 0


def test_merged_transition_when_both_exceed():
    """测试当出口+进口渐变段总长度超过可用里程时，合并为单个渐变段"""
    tunnel_outlet = ChannelNode()
    tunnel_outlet.structure_type = StructureType.from_string("隧洞-圆形")
    tunnel_outlet.name = "隧洞1"
    tunnel_outlet.in_out = InOutType.OUTLET
    tunnel_outlet.section_params = {"D": 2.5}
    tunnel_outlet.station_MC = 100.0

    aqueduct_inlet = ChannelNode()
    aqueduct_inlet.structure_type = StructureType.from_string("渡槽-U形")
    aqueduct_inlet.name = "渡槽1"
    aqueduct_inlet.in_out = InOutType.INLET
    aqueduct_inlet.section_params = {"B": 2.0, "H": 2.5}
    aqueduct_inlet.station_MC = 110.0  # 只有10m距离

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._should_insert_open_channel(tunnel_outlet, aqueduct_inlet)

    assert result['distance'] == 10.0

    # 如果总长度超过可用里程，应该合并为单个渐变段
    if result.get('use_merged_transition'):
        assert result['need_transition_1'] == True
        assert result['need_transition_2'] == False
        assert result['transition_length_1'] == 10.0
        assert result['transition_length_2'] == 0.0
        assert result['available_length'] == 0.0
        assert result['need_open_channel'] == False


def test_no_open_channel_when_compressed():
    """测试渐变段被压缩后，明渠段不插入"""
    culvert_outlet = ChannelNode()
    culvert_outlet.structure_type = StructureType.from_string("矩形暗涵")
    culvert_outlet.name = "矩形暗涵1"
    culvert_outlet.in_out = InOutType.OUTLET
    culvert_outlet.section_params = {"B": 2.0, "H": 2.5}
    culvert_outlet.station_MC = 200.0

    gate = ChannelNode()
    gate.structure_type = StructureType.from_string("分水闸")
    gate.name = "分水闸1"
    gate.station_MC = 203.0  # 只有3m距离

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_exit_to_gate(culvert_outlet, gate)

    assert result['need_transition_1'] == True
    assert result['distance'] == 3.0
    # 渐变段被压缩到3m
    assert result['transition_length_1'] <= 3.0
    # 可用长度应该 >= 0（基于压缩后的长度）
    assert result['available_length'] >= 0
    # 如果可用长度为0，不应插入明渠段
    if result['available_length'] == 0:
        assert result['need_open_channel'] == False


if __name__ == "__main__":
    print("Running transition length compression tests...")

    test_single_transition_compression()
    print("PASS: single_transition_compression")

    test_merged_transition_when_both_exceed()
    print("PASS: merged_transition_when_both_exceed")

    test_no_open_channel_when_compressed()
    print("PASS: no_open_channel_when_compressed")

    print("\nAll compression tests passed!")
