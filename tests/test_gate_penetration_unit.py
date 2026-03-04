# -*- coding: utf-8 -*-
"""
闸穿透处理 - 单元测试

**Validates: Requirements 5.1, 5.2, 5.4**

测试闸穿透处理函数对有压管道的支持：
- 测试有压管道出口 → 分水闸
- 测试节制闸 → 有压管道进口
- 测试倒虹吸出口 → 分水闸
- 测试节制闸 → 倒虹吸进口
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.calculator import WaterProfileCalculator


def test_pressure_pipe_outlet_to_diversion_gate():
    """
    测试有压管道出口 → 分水闸
    
    **Validates: Requirement 5.1**
    
    验证：
    - 应识别需要插入出口渐变段
    - 有压管道侧渐变段标记 skip_loss=True
    - 里程差计算正确
    - 可用长度计算正确
    """
    # 创建有压管道出口节点
    pressure_pipe_outlet = ChannelNode()
    pressure_pipe_outlet.structure_type = StructureType.from_string("有压管道")
    pressure_pipe_outlet.name = "有压管道1"
    pressure_pipe_outlet.in_out = InOutType.OUTLET
    pressure_pipe_outlet.section_params = {"D": 1.5}
    pressure_pipe_outlet.station_MC = 100.0
    
    # 创建分水闸节点
    diversion_gate = ChannelNode()
    diversion_gate.structure_type = StructureType.from_string("分水闸")
    diversion_gate.name = "分水闸1"
    diversion_gate.station_MC = 120.0
    
    # 调用闸穿透检查函数
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_exit_to_gate(pressure_pipe_outlet, diversion_gate)
    
    # 验证结果
    assert result['need_transition_1'] == True, "应识别需要插入有压管道出口渐变段"
    assert result['skip_loss_transition_1'] == True, "有压管道侧渐变段应标记 skip_loss=True"
    assert result['distance'] == 20.0, f"里程差应为 20.0，实际为 {result['distance']}"
    assert result['transition_length_1'] > 0, "渐变段长度应大于 0"
    
    expected_available = 20.0 - result['transition_length_1']
    assert abs(result['available_length'] - expected_available) < 0.001, \
        f"可用长度计算错误: 期望{expected_available}，实际为 {result['available_length']}"
    
    if result['available_length'] > 0:
        assert result['need_open_channel'] == True, "可用长度 > 0 时应需要明渠段"


def test_control_gate_to_pressure_pipe_inlet():
    """
    测试节制闸 → 有压管道进口
    
    **Validates: Requirement 5.2**
    
    验证：
    - 应识别需要插入进口渐变段
    - 有压管道侧渐变段标记 skip_loss=True
    - 里程差计算正确
    - 可用长度计算正确
    """
    # 创建节制闸节点
    control_gate = ChannelNode()
    control_gate.structure_type = StructureType.from_string("节制闸")
    control_gate.name = "节制闸1"
    control_gate.station_MC = 200.0
    
    # 创建有压管道进口节点
    pressure_pipe_inlet = ChannelNode()
    pressure_pipe_inlet.structure_type = StructureType.from_string("有压管道")
    pressure_pipe_inlet.name = "有压管道2"
    pressure_pipe_inlet.in_out = InOutType.INLET
    pressure_pipe_inlet.section_params = {"D": 1.8}
    pressure_pipe_inlet.station_MC = 225.0
    
    # 调用闸穿透检查函数
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_gate_to_entry(control_gate, pressure_pipe_inlet)
    
    # 验证结果
    assert result['need_transition_2'] == True, "应识别需要插入有压管道进口渐变段"
    assert result['skip_loss_transition_2'] == True, "有压管道侧渐变段应标记 skip_loss=True"
    assert result['distance'] == 25.0, f"里程差应为 25.0，实际为 {result['distance']}"
    assert result['transition_length_2'] > 0, "渐变段长度应大于 0"
    
    expected_available = 25.0 - result['transition_length_2']
    assert abs(result['available_length'] - expected_available) < 0.001, \
        f"可用长度计算错误: 期望{expected_available}，实际为 {result['available_length']}"
    
    if result['available_length'] > 0:
        assert result['need_open_channel'] == True, "可用长度 > 0 时应需要明渠段"


def test_siphon_outlet_to_diversion_gate():
    """
    测试倒虹吸出口 → 分水闸
    
    **Validates: Requirement 5.1**
    
    验证：
    - 应识别需要插入出口渐变段（倒虹吸也是有压流建筑物）
    - 倒虹吸侧渐变段标记 skip_loss=True
    - 里程差计算正确
    """
    # 创建倒虹吸出口节点
    siphon_outlet = ChannelNode()
    siphon_outlet.structure_type = StructureType.from_string("倒虹吸")
    siphon_outlet.name = "倒虹吸1"
    siphon_outlet.in_out = InOutType.OUTLET
    siphon_outlet.section_params = {"D": 1.2}
    siphon_outlet.station_MC = 300.0
    
    # 创建分水闸节点
    diversion_gate = ChannelNode()
    diversion_gate.structure_type = StructureType.from_string("分水闸")
    diversion_gate.name = "分水闸2"
    diversion_gate.station_MC = 315.0
    
    # 调用闸穿透检查函数
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_exit_to_gate(siphon_outlet, diversion_gate)
    
    # 验证结果
    assert result['need_transition_1'] == True, "应识别需要插入倒虹吸出口渐变段"
    assert result['skip_loss_transition_1'] == True, "倒虹吸侧渐变段应标记 skip_loss=True"
    assert result['distance'] == 15.0, f"里程差应为 15.0，实际为 {result['distance']}"


def test_control_gate_to_siphon_inlet():
    """
    测试节制闸 → 倒虹吸进口
    
    **Validates: Requirement 5.2**
    
    验证：
    - 应识别需要插入进口渐变段（倒虹吸也是有压流建筑物）
    - 倒虹吸侧渐变段标记 skip_loss=True
    - 里程差计算正确
    """
    # 创建节制闸节点
    control_gate = ChannelNode()
    control_gate.structure_type = StructureType.from_string("节制闸")
    control_gate.name = "节制闸2"
    control_gate.station_MC = 400.0
    
    # 创建倒虹吸进口节点
    siphon_inlet = ChannelNode()
    siphon_inlet.structure_type = StructureType.from_string("倒虹吸")
    siphon_inlet.name = "倒虹吸2"
    siphon_inlet.in_out = InOutType.INLET
    siphon_inlet.section_params = {"D": 1.5}
    siphon_inlet.station_MC = 420.0
    
    # 调用闸穿透检查函数
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_gate_to_entry(control_gate, siphon_inlet)
    
    # 验证结果
    assert result['need_transition_2'] == True, "应识别需要插入倒虹吸进口渐变段"
    assert result['skip_loss_transition_2'] == True, "倒虹吸侧渐变段应标记 skip_loss=True"
    assert result['distance'] == 20.0, f"里程差应为 20.0，实际为 {result['distance']}"


def test_pressure_pipe_outlet_to_spillway_gate():
    """
    测试有压管道出口 → 泄水闸
    
    **Validates: Requirement 5.1**
    
    验证：
    - 应识别需要插入出口渐变段
    - 有压管道侧渐变段标记 skip_loss=True
    """
    # 创建有压管道出口节点
    pressure_pipe_outlet = ChannelNode()
    pressure_pipe_outlet.structure_type = StructureType.from_string("有压管道")
    pressure_pipe_outlet.name = "有压管道3"
    pressure_pipe_outlet.in_out = InOutType.OUTLET
    pressure_pipe_outlet.section_params = {"D": 2.0}
    pressure_pipe_outlet.station_MC = 500.0
    
    # 创建泄水闸节点
    spillway_gate = ChannelNode()
    spillway_gate.structure_type = StructureType.from_string("泄水闸")
    spillway_gate.name = "泄水闸1"
    spillway_gate.station_MC = 530.0
    
    # 调用闸穿透检查函数
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_exit_to_gate(pressure_pipe_outlet, spillway_gate)
    
    # 验证结果
    assert result['need_transition_1'] == True, "应识别需要插入有压管道出口渐变段"
    assert result['skip_loss_transition_1'] == True, "有压管道侧渐变段应标记 skip_loss=True"
    assert result['distance'] == 30.0, f"里程差应为 30.0，实际为 {result['distance']}"


def test_zero_distance_no_insertion():
    """
    测试里程差为零时不插入渐变段
    
    验证：
    - 当里程差 <= 0 时，不应插入渐变段
    """
    # 创建有压管道出口节点
    pressure_pipe_outlet = ChannelNode()
    pressure_pipe_outlet.structure_type = StructureType.from_string("有压管道")
    pressure_pipe_outlet.name = "有压管道4"
    pressure_pipe_outlet.in_out = InOutType.OUTLET
    pressure_pipe_outlet.section_params = {"D": 1.5}
    pressure_pipe_outlet.station_MC = 100.0
    
    # 创建分水闸节点（里程相同）
    diversion_gate = ChannelNode()
    diversion_gate.structure_type = StructureType.from_string("分水闸")
    diversion_gate.name = "分水闸3"
    diversion_gate.station_MC = 100.0
    
    # 调用闸穿透检查函数
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_exit_to_gate(pressure_pipe_outlet, diversion_gate)
    
    # 验证结果
    assert result['distance'] == 0.0, "里程差应为 0"
    assert result['need_open_channel'] == False, "里程差为 0 时不应需要明渠段"


def test_insufficient_space_no_open_channel():
    """
    测试里程差不足时不插入明渠段
    
    验证：
    - 当里程差 < 渐变段长度时，不应插入明渠段
    - 但仍应识别需要渐变段
    """
    # 创建有压管道出口节点
    pressure_pipe_outlet = ChannelNode()
    pressure_pipe_outlet.structure_type = StructureType.from_string("有压管道")
    pressure_pipe_outlet.name = "有压管道5"
    pressure_pipe_outlet.in_out = InOutType.OUTLET
    pressure_pipe_outlet.section_params = {"D": 1.5}
    pressure_pipe_outlet.station_MC = 100.0
    
    # 创建分水闸节点（里程差很小）
    diversion_gate = ChannelNode()
    diversion_gate.structure_type = StructureType.from_string("分水闸")
    diversion_gate.name = "分水闸4"
    diversion_gate.station_MC = 101.0  # 只有 1m 的里程差
    
    # 调用闸穿透检查函数
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._check_gap_exit_to_gate(pressure_pipe_outlet, diversion_gate)
    
    # 验证结果
    assert result['distance'] == 1.0, "里程差应为 1.0"
    assert result['need_transition_1'] == True, "应识别需要插入渐变段"
    
    # 如果可用长度 <= 0，不应插入明渠段
    if result['available_length'] <= 0:
        assert result['need_open_channel'] == False, "可用长度 <= 0 时不应需要明渠段"


if __name__ == "__main__":
    print("运行闸穿透处理单元测试...")
    
    test_pressure_pipe_outlet_to_diversion_gate()
    print("✓ 测试有压管道出口 → 分水闸")
    
    test_control_gate_to_pressure_pipe_inlet()
    print("✓ 测试节制闸 → 有压管道进口")
    
    test_siphon_outlet_to_diversion_gate()
    print("✓ 测试倒虹吸出口 → 分水闸")
    
    test_control_gate_to_siphon_inlet()
    print("✓ 测试节制闸 → 倒虹吸进口")
    
    test_pressure_pipe_outlet_to_spillway_gate()
    print("✓ 测试有压管道出口 → 泄水闸")
    
    test_zero_distance_no_insertion()
    print("✓ 测试里程差为零时不插入渐变段")
    
    test_insufficient_space_no_open_channel()
    print("✓ 测试里程差不足时不插入明渠段")
    
    print("\n所有单元测试通过！")
