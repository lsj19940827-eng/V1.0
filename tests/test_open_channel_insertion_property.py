# -*- coding: utf-8 -*-
"""
明渠段插入逻辑 - 属性测试

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6**

Property 9: 明渠段插入条件
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
def structure_pair_with_distance_strategy(draw):
    """
    生成建筑物节点对（出口和进口）及其里程差
    
    返回: (outlet_node, inlet_node, distance)
    """
    # 生成出口节点（有压管道或其他建筑物）
    is_outlet_pressure_pipe = draw(st.booleans())
    
    outlet = ChannelNode()
    if is_outlet_pressure_pipe:
        outlet.structure_type = StructureType.from_string("有压管道")
        # Use simpler alphabet to avoid character encoding issues
        outlet.name = "PP" + str(draw(st.integers(min_value=1, max_value=999)))
        outlet.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
    else:
        structure_types = ["隧洞-圆形", "渡槽-U形", "矩形暗涵"]
        structure_type_str = draw(st.sampled_from(structure_types))
        outlet.structure_type = StructureType.from_string(structure_type_str)
        outlet.name = "S" + str(draw(st.integers(min_value=1, max_value=999)))
        
        if "隧洞" in structure_type_str or "渡槽" in structure_type_str:
            outlet.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
        else:
            outlet.section_params = {"b": draw(st.floats(min_value=0.5, max_value=3.0)),
                                    "h": draw(st.floats(min_value=0.5, max_value=2.0))}
    
    outlet.in_out = InOutType.OUTLET
    outlet.station_MC = draw(st.floats(min_value=0, max_value=5000))
    outlet.water_depth = draw(st.floats(min_value=0.5, max_value=3.0))
    
    # 生成进口节点（有压管道或其他建筑物）
    is_inlet_pressure_pipe = draw(st.booleans())
    
    inlet = ChannelNode()
    if is_inlet_pressure_pipe:
        inlet.structure_type = StructureType.from_string("有压管道")
        inlet.name = "PP" + str(draw(st.integers(min_value=1, max_value=999)))
        inlet.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
    else:
        structure_types = ["隧洞-圆形", "渡槽-U形", "矩形暗涵"]
        structure_type_str = draw(st.sampled_from(structure_types))
        inlet.structure_type = StructureType.from_string(structure_type_str)
        inlet.name = "S" + str(draw(st.integers(min_value=1, max_value=999)))
        
        if "隧洞" in structure_type_str or "渡槽" in structure_type_str:
            inlet.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
        else:
            inlet.section_params = {"b": draw(st.floats(min_value=0.5, max_value=3.0)),
                                   "h": draw(st.floats(min_value=0.5, max_value=2.0))}
    
    inlet.in_out = InOutType.INLET
    inlet.water_depth = draw(st.floats(min_value=0.5, max_value=3.0))
    
    # 生成里程差（范围从很小到很大）
    distance = draw(st.floats(min_value=1.0, max_value=200.0))
    inlet.station_MC = outlet.station_MC + distance
    
    return outlet, inlet, distance


@st.composite
def pressure_pipe_outlet_and_other_inlet_strategy(draw):
    """生成有压管道出口和其他建筑物进口节点对"""
    # 有压管道出口
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "PP" + str(draw(st.integers(min_value=1, max_value=999)))
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
    outlet.station_MC = draw(st.floats(min_value=0, max_value=5000))
    outlet.water_depth = draw(st.floats(min_value=0.5, max_value=3.0))
    
    # 其他建筑物进口
    structure_types = ["隧洞-圆形", "渡槽-U形", "矩形暗涵"]
    structure_type_str = draw(st.sampled_from(structure_types))
    
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string(structure_type_str)
    inlet.name = "S" + str(draw(st.integers(min_value=1, max_value=999)))
    inlet.in_out = InOutType.INLET
    
    if "隧洞" in structure_type_str or "渡槽" in structure_type_str:
        inlet.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
    else:
        inlet.section_params = {"b": draw(st.floats(min_value=0.5, max_value=3.0)),
                               "h": draw(st.floats(min_value=0.5, max_value=2.0))}
    
    inlet.water_depth = draw(st.floats(min_value=0.5, max_value=3.0))
    
    # 生成里程差
    distance = draw(st.floats(min_value=1.0, max_value=200.0))
    inlet.station_MC = outlet.station_MC + distance
    
    return outlet, inlet, distance


# ============================================================================
# 属性测试
# ============================================================================

@settings(max_examples=100, deadline=None)
@given(data=structure_pair_with_distance_strategy())
def test_property_9_open_channel_insertion_condition(data):
    """
    **Property 9: 明渠段插入条件**
    
    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6**
    
    For any 有压管道出口和下一个建筑物进口，当里程差大于两侧渐变段长度之和时，
    系统应插入明渠段，并在有压管道侧插入标记 skip_loss=True 的出口渐变段。
    
    验证点：
    1. 当里程差 > 渐变段长度之和时，need_open_channel=True
    2. 当里程差 <= 渐变段长度之和时，need_open_channel=False
    3. 插入明渠段时，应同时插入出口渐变段和进口渐变段
    4. 有压管道侧的渐变段标记 skip_loss=True
    5. 明渠段可用长度 = 里程差 - 渐变段长度之和
    """
    outlet, inlet, distance = data
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 调用判断函数
    result = calculator._should_insert_open_channel(outlet, inlet)
    
    # 计算渐变段长度之和
    total_transition_length = result['transition_length_1'] + result['transition_length_2']
    
    # 特殊情况：同名同径有压管道不插入渐变段（Property 6）
    is_outlet_pressure_pipe = calculator.is_pressure_pipe(outlet)
    is_inlet_pressure_pipe = calculator.is_pressure_pipe(inlet)
    
    if is_outlet_pressure_pipe and is_inlet_pressure_pipe:
        name1 = outlet.name if outlet.name else ""
        name2 = inlet.name if inlet.name else ""
        diameter1 = outlet.section_params.get("D", 0) if outlet.section_params else 0
        diameter2 = inlet.section_params.get("D", 0) if inlet.section_params else 0
        
        if name1 == name2 and abs(diameter1 - diameter2) < 0.001:
            # 同名同径有压管道不插入渐变段
            assert result['need_transition_1'] == False
            assert result['need_transition_2'] == False
            assert result['need_open_channel'] == False
            return  # Skip further checks for this case
    
    # 验证点 1 & 2: 明渠段插入条件
    if distance > total_transition_length:
        assert result['need_open_channel'] == True, \
            f"里程差 {distance}m > 渐变段长度之和 {total_transition_length}m 时应插入明渠段"
        
        # 验证点 3: 应同时插入出口渐变段和进口渐变段
        assert result['need_transition_1'] == True, \
            f"插入明渠段时应插入出口渐变段"
        assert result['need_transition_2'] == True, \
            f"插入明渠段时应插入进口渐变段"
        
        # 验证点 5: 明渠段可用长度计算
        expected_available_length = distance - total_transition_length
        assert abs(result['available_length'] - expected_available_length) < 0.001, \
            f"明渠段可用长度计算错误: 期望 {expected_available_length}m, 实际 {result['available_length']}m"
        
        # 验证可用长度为正数
        assert result['available_length'] > 0, \
            f"明渠段可用长度应为正数: {result['available_length']}m"
    else:
        assert result['need_open_channel'] == False, \
            f"里程差 {distance}m <= 渐变段长度之和 {total_transition_length}m 时不应插入明渠段"
    
    # 验证点 4: 有压管道侧的渐变段标记 skip_loss=True
    if is_outlet_pressure_pipe:
        if result['need_transition_1']:
            assert result['skip_loss_transition_1'] == True, \
                f"有压管道出口侧的渐变段应标记 skip_loss=True"
    
    if is_inlet_pressure_pipe:
        if result['need_transition_2']:
            assert result['skip_loss_transition_2'] == True, \
                f"有压管道进口侧的渐变段应标记 skip_loss=True"


@settings(max_examples=100, deadline=None)
@given(data=pressure_pipe_outlet_and_other_inlet_strategy())
def test_property_9_pressure_pipe_outlet_skip_loss(data):
    """
    **Property 9: 有压管道出口侧渐变段跳过损失**
    
    **Validates: Requirements 6.2, 6.6**
    
    For any 有压管道出口和其他建筑物进口，当插入明渠段时，
    有压管道侧的出口渐变段应标记 skip_loss=True。
    
    验证点：
    1. 有压管道出口侧渐变段标记 skip_loss=True
    2. 其他建筑物进口侧渐变段标记 skip_loss=False
    """
    outlet, inlet, distance = data
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 调用判断函数
    result = calculator._should_insert_open_channel(outlet, inlet)
    
    # 验证点 1: 有压管道出口侧渐变段标记 skip_loss=True
    assert result['skip_loss_transition_1'] == True, \
        f"有压管道出口侧的渐变段应标记 skip_loss=True"
    
    # 验证点 2: 其他建筑物进口侧渐变段标记 skip_loss=False
    assert result['skip_loss_transition_2'] == False, \
        f"其他建筑物进口侧的渐变段应标记 skip_loss=False"


@settings(max_examples=100, deadline=None)
@given(
    outlet_water_depth=st.floats(min_value=0.5, max_value=3.0),
    inlet_water_depth=st.floats(min_value=0.5, max_value=3.0),
    distance_multiplier=st.floats(min_value=1.5, max_value=3.0)  # Ensure distance is large enough
)
def test_property_9_available_length_calculation(
    outlet_water_depth: float,
    inlet_water_depth: float,
    distance_multiplier: float
):
    """
    **Property 9: 明渠段可用长度计算**
    
    **Validates: Requirements 6.5**
    
    验证明渠段可用长度的计算公式：
    available_length = distance - (transition_length_1 + transition_length_2)
    """
    # 创建有压管道出口节点
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "有压管道1"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.5}
    outlet.station_MC = 100.0
    outlet.water_depth = outlet_water_depth
    
    # 创建隧洞进口节点
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("隧洞-圆形")
    inlet.name = "隧洞1"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 2.0}
    inlet.water_depth = inlet_water_depth
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 使用实际的渐变段长度计算函数
    transition_length_1 = calculator._estimate_transition_length(outlet, "出口")
    transition_length_2 = calculator._estimate_transition_length(inlet, "进口")
    total_transition_length = transition_length_1 + transition_length_2
    
    # 设置里程差（确保大于渐变段长度之和）
    distance = total_transition_length * distance_multiplier + 10.0
    inlet.station_MC = outlet.station_MC + distance
    
    # 调用判断函数
    result = calculator._should_insert_open_channel(outlet, inlet)
    
    # 验证可用长度计算
    expected_available_length = distance - total_transition_length
    
    if distance > total_transition_length:
        assert result['need_open_channel'] == True, \
            f"里程差 {distance}m > 渐变段长度之和 {total_transition_length}m 时应插入明渠段"
        
        assert abs(result['available_length'] - expected_available_length) < 0.001, \
            f"明渠段可用长度计算错误: 期望 {expected_available_length}m, 实际 {result['available_length']}m"
        
        assert result['available_length'] > 0, \
            f"明渠段可用长度应为正数: {result['available_length']}m"


@settings(max_examples=50, deadline=None)
@given(
    water_depth=st.floats(min_value=0.5, max_value=3.0)
)
def test_property_9_no_open_channel_when_distance_too_small(water_depth: float):
    """
    **Property 9: 里程差过小时不插入明渠段**
    
    **Validates: Requirements 6.1**
    
    验证当里程差小于或等于渐变段长度之和时，不插入明渠段。
    """
    # 创建有压管道出口节点
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "有压管道1"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.5}
    outlet.station_MC = 100.0
    outlet.water_depth = water_depth
    
    # 创建隧洞进口节点
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("隧洞-圆形")
    inlet.name = "隧洞1"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 2.0}
    inlet.water_depth = water_depth
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 计算渐变段长度之和
    transition_length_1 = 6 * water_depth  # 出口渐变段
    transition_length_2 = 5 * water_depth  # 进口渐变段
    total_transition_length = transition_length_1 + transition_length_2
    
    # 设置里程差（小于渐变段长度之和）
    distance = total_transition_length * 0.8  # 80% of total transition length
    inlet.station_MC = outlet.station_MC + distance
    
    # 调用判断函数
    result = calculator._should_insert_open_channel(outlet, inlet)
    
    # 验证不插入明渠段
    assert result['need_open_channel'] == False, \
        f"里程差 {distance}m <= 渐变段长度之和 {total_transition_length}m 时不应插入明渠段"
    
    # 验证可用长度为负数或零
    assert result['available_length'] <= 0, \
        f"里程差过小时，可用长度应为负数或零: {result['available_length']}m"


if __name__ == "__main__":
    import pytest
    
    print("运行明渠段插入逻辑属性测试...")
    print("\n注意：属性测试需要 pytest 和 hypothesis 库")
    print("运行命令: pytest tests/test_open_channel_insertion_property.py -v")
    print("\n如果直接运行此文件，将执行简单的冒烟测试...")
    
    # 简单的冒烟测试
    try:
        # 测试明渠段插入条件
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = "有压管道1"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.5}
        outlet.station_MC = 100.0
        outlet.water_depth = 2.0
        
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("隧洞-圆形")
        inlet.name = "隧洞1"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 2.0}
        inlet.station_MC = 150.0  # 距离 50m
        inlet.water_depth = 2.0
        
        settings = ProjectSettings()
        calculator = WaterProfileCalculator(settings)
        result = calculator._should_insert_open_channel(outlet, inlet)
        
        # 渐变段长度：出口 6*2.0=12m, 进口 5*2.0=10m, 总计 22m
        # 里程差 50m > 22m，应插入明渠段
        assert result['need_open_channel'] == True, "里程差大于渐变段长度之和时应插入明渠段"
        assert result['skip_loss_transition_1'] == True, "有压管道侧渐变段应标记 skip_loss=True"
        assert result['skip_loss_transition_2'] == False, "隧洞侧渐变段应标记 skip_loss=False"
        
        expected_available = 50.0 - 22.0
        assert abs(result['available_length'] - expected_available) < 0.001, \
            f"明渠段可用长度应为 {expected_available}m, 实际 {result['available_length']}m"
        
        print("✓ 明渠段插入条件测试通过")
        
        # 测试里程差过小时不插入明渠段
        inlet.station_MC = 115.0  # 距离 15m < 22m
        result = calculator._should_insert_open_channel(outlet, inlet)
        
        assert result['need_open_channel'] == False, "里程差小于渐变段长度之和时不应插入明渠段"
        assert result['available_length'] < 0, "可用长度应为负数"
        
        print("✓ 里程差过小不插入明渠段测试通过")
        
        print("\n冒烟测试全部通过！")
        print("运行完整属性测试请使用: pytest tests/test_open_channel_insertion_property.py -v")
        
    except Exception as e:
        print(f"\n✗ 冒烟测试失败: {e}")
        import traceback
        traceback.print_exc()
