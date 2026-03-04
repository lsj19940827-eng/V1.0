# -*- coding: utf-8 -*-
"""
闸穿透处理 - 属性测试

**Validates: Requirements 5.1, 5.2, 5.3, 5.4**

Property 16: 闸穿透延迟插入

For any 有压管道出口后跟随闸群的情况，系统应将明渠段和渐变段添加到延迟队列，
在闸群结束后、下一个非闸节点前插入。
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from hypothesis import given, strategies as st, settings, assume
from typing import List

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.calculator import WaterProfileCalculator


# ============================================================================
# Hypothesis 策略：生成测试数据
# ============================================================================

@st.composite
def pressurized_flow_outlet_strategy(draw):
    """生成有压流建筑物（倒虹吸或有压管道）出口节点"""
    is_siphon = draw(st.booleans())
    
    node = ChannelNode()
    if is_siphon:
        node.structure_type = StructureType.from_string("倒虹吸")
        node.name = draw(st.text(min_size=1, max_size=10, alphabet="倒虹吸123"))
    else:
        node.structure_type = StructureType.from_string("有压管道")
        node.name = draw(st.text(min_size=1, max_size=10, alphabet="有压管道ABC"))
    
    node.in_out = InOutType.OUTLET
    node.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
    node.station_MC = draw(st.floats(min_value=0, max_value=5000))
    
    return node


@st.composite
def gate_node_strategy(draw):
    """生成闸类节点（分水闸、节制闸、泄水闸）"""
    gate_types = ["分水闸", "节制闸", "泄水闸"]
    gate_type = draw(st.sampled_from(gate_types))
    
    node = ChannelNode()
    node.structure_type = StructureType.from_string(gate_type)
    node.name = draw(st.text(min_size=1, max_size=10, alphabet="闸123"))
    node.station_MC = draw(st.floats(min_value=0, max_value=5000))
    
    return node


@st.composite
def pressurized_flow_inlet_strategy(draw):
    """生成有压流建筑物（倒虹吸或有压管道）进口节点"""
    is_siphon = draw(st.booleans())
    
    node = ChannelNode()
    if is_siphon:
        node.structure_type = StructureType.from_string("倒虹吸")
        node.name = draw(st.text(min_size=1, max_size=10, alphabet="倒虹吸123"))
    else:
        node.structure_type = StructureType.from_string("有压管道")
        node.name = draw(st.text(min_size=1, max_size=10, alphabet="有压管道ABC"))
    
    node.in_out = InOutType.INLET
    node.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
    node.station_MC = draw(st.floats(min_value=0, max_value=5000))
    
    return node


# ============================================================================
# 属性测试
# ============================================================================

@settings(max_examples=100, deadline=None)
@given(
    exit_node=pressurized_flow_outlet_strategy(),
    gate_node=gate_node_strategy()
)
def test_property_16_pressurized_exit_to_gate(
    exit_node: ChannelNode,
    gate_node: ChannelNode
):
    """
    **Property 16a: 有压流出口 → 闸的延迟插入**
    
    **Validates: Requirements 5.1, 5.3**
    
    For any 有压流建筑物出口节点后跟随闸类节点，系统应：
    1. 识别需要插入明渠段和渐变段
    2. 有压流侧渐变段标记 skip_loss=True
    3. 返回正确的里程差和可用长度
    
    验证点：
    1. 当里程差 > 0 时，应识别需要插入渐变段
    2. 有压流侧渐变段标记 skip_loss=True
    3. 里程差计算正确
    4. 可用长度 = 里程差 - 渐变段长度
    """
    # 确保闸的里程大于出口里程
    if gate_node.station_MC <= exit_node.station_MC:
        gate_node.station_MC = exit_node.station_MC + 10.0
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 调用闸穿透检查函数
    result = calculator._check_gap_exit_to_gate(exit_node, gate_node)
    
    # 验证点 1: 应识别需要插入渐变段
    is_pressurized = calculator.is_pressurized_flow_structure(exit_node)
    if is_pressurized:
        assert result['need_transition_1'] == True, \
            f"有压流出口 → 闸应识别需要插入出口渐变段"
    
    # 验证点 2: 有压流侧渐变段标记 skip_loss=True
    if is_pressurized and result['need_transition_1']:
        assert result['skip_loss_transition_1'] == True, \
            f"有压流侧渐变段应标记 skip_loss=True"
    
    # 验证点 3: 里程差计算正确
    expected_distance = gate_node.station_MC - exit_node.station_MC
    assert abs(result['distance'] - expected_distance) < 0.001, \
        f"里程差计算错误: 期望{expected_distance}，实际{result['distance']}"
    
    # 验证点 4: 可用长度计算正确
    expected_available = expected_distance - result['transition_length_1']
    assert abs(result['available_length'] - expected_available) < 0.001, \
        f"可用长度计算错误: 期望{expected_available}，实际{result['available_length']}"
    
    # 验证点 5: 需要明渠段的判断
    if result['available_length'] > 0:
        assert result['need_open_channel'] == True, \
            f"可用长度 > 0 时应需要明渠段"
    else:
        assert result['need_open_channel'] == False, \
            f"可用长度 <= 0 时不应需要明渠段"


@settings(max_examples=100, deadline=None)
@given(
    gate_node=gate_node_strategy(),
    entry_node=pressurized_flow_inlet_strategy()
)
def test_property_16_gate_to_pressurized_entry(
    gate_node: ChannelNode,
    entry_node: ChannelNode
):
    """
    **Property 16b: 闸 → 有压流进口的延迟插入**
    
    **Validates: Requirements 5.2, 5.4**
    
    For any 闸类节点后跟随有压流建筑物进口节点，系统应：
    1. 识别需要插入明渠段和渐变段
    2. 有压流侧渐变段标记 skip_loss=True
    3. 返回正确的里程差和可用长度
    
    验证点：
    1. 当里程差 > 0 时，应识别需要插入渐变段
    2. 有压流侧渐变段标记 skip_loss=True
    3. 里程差计算正确
    4. 可用长度 = 里程差 - 渐变段长度
    """
    # 确保进口里程大于闸的里程
    if entry_node.station_MC <= gate_node.station_MC:
        entry_node.station_MC = gate_node.station_MC + 10.0
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 调用闸穿透检查函数
    result = calculator._check_gap_gate_to_entry(gate_node, entry_node)
    
    # 验证点 1: 应识别需要插入渐变段
    is_pressurized = calculator.is_pressurized_flow_structure(entry_node)
    if is_pressurized:
        assert result['need_transition_2'] == True, \
            f"闸 → 有压流进口应识别需要插入进口渐变段"
    
    # 验证点 2: 有压流侧渐变段标记 skip_loss=True
    if is_pressurized and result['need_transition_2']:
        assert result['skip_loss_transition_2'] == True, \
            f"有压流侧渐变段应标记 skip_loss=True"
    
    # 验证点 3: 里程差计算正确
    expected_distance = entry_node.station_MC - gate_node.station_MC
    assert abs(result['distance'] - expected_distance) < 0.001, \
        f"里程差计算错误: 期望{expected_distance}，实际{result['distance']}"
    
    # 验证点 4: 可用长度计算正确
    expected_available = expected_distance - result['transition_length_2']
    assert abs(result['available_length'] - expected_available) < 0.001, \
        f"可用长度计算错误: 期望{expected_available}，实际{result['available_length']}"
    
    # 验证点 5: 需要明渠段的判断
    if result['available_length'] > 0:
        assert result['need_open_channel'] == True, \
            f"可用长度 > 0 时应需要明渠段"
    else:
        assert result['need_open_channel'] == False, \
            f"可用长度 <= 0 时不应需要明渠段"


if __name__ == "__main__":
    import pytest
    
    print("运行闸穿透处理属性测试...")
    print("\n注意：属性测试需要 pytest 和 hypothesis 库")
    print("运行命令: pytest tests/test_gate_penetration_property.py -v")
    print("\n如果直接运行此文件，将执行简单的冒烟测试...")
    
    # 简单的冒烟测试
    try:
        # 测试 Property 16a: 有压管道出口 → 分水闸
        pressure_pipe_outlet = ChannelNode()
        pressure_pipe_outlet.structure_type = StructureType.from_string("有压管道")
        pressure_pipe_outlet.name = "有压管道1"
        pressure_pipe_outlet.in_out = InOutType.OUTLET
        pressure_pipe_outlet.section_params = {"D": 1.5}
        pressure_pipe_outlet.station_MC = 100.0
        
        gate = ChannelNode()
        gate.structure_type = StructureType.from_string("分水闸")
        gate.name = "分水闸1"
        gate.station_MC = 120.0
        
        settings = ProjectSettings()
        calculator = WaterProfileCalculator(settings)
        result = calculator._check_gap_exit_to_gate(pressure_pipe_outlet, gate)
        
        assert result['need_transition_1'] == True, "应识别需要插入渐变段"
        assert result['skip_loss_transition_1'] == True, "有压管道侧应标记 skip_loss=True"
        assert result['distance'] == 20.0, f"里程差应为 20.0，实际为 {result['distance']}"
        print("✓ Property 16a 冒烟测试通过（有压管道出口 → 闸）")
        
        # 测试 Property 16b: 节制闸 → 有压管道进口
        gate2 = ChannelNode()
        gate2.structure_type = StructureType.from_string("节制闸")
        gate2.name = "节制闸1"
        gate2.station_MC = 200.0
        
        pressure_pipe_inlet = ChannelNode()
        pressure_pipe_inlet.structure_type = StructureType.from_string("有压管道")
        pressure_pipe_inlet.name = "有压管道2"
        pressure_pipe_inlet.in_out = InOutType.INLET
        pressure_pipe_inlet.section_params = {"D": 1.8}
        pressure_pipe_inlet.station_MC = 225.0
        
        result = calculator._check_gap_gate_to_entry(gate2, pressure_pipe_inlet)
        
        assert result['need_transition_2'] == True, "应识别需要插入渐变段"
        assert result['skip_loss_transition_2'] == True, "有压管道侧应标记 skip_loss=True"
        assert result['distance'] == 25.0, f"里程差应为 25.0，实际为 {result['distance']}"
        print("✓ Property 16b 冒烟测试通过（闸 → 有压管道进口）")
        
        print("\n冒烟测试全部通过！")
        print("运行完整属性测试请使用: pytest tests/test_gate_penetration_property.py -v")
        
    except Exception as e:
        print(f"\n✗ 冒烟测试失败: {e}")
        import traceback
        traceback.print_exc()
