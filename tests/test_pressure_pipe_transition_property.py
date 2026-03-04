# -*- coding: utf-8 -*-
"""
有压管道渐变段插入 - 属性测试

**Validates: Requirements 2.1, 2.2, 2.4, 2.5, 4.1-4.6**

Property 2: 有压流建筑物渐变段插入
Property 3: 有压流建筑物进口渐变段插入
Property 6: 同一有压管道不插入渐变段
Property 7: 不同有压管道插入渐变段
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
def other_structure_inlet_strategy(draw):
    """生成其他建筑物（隧洞/渡槽/暗涵）进口节点"""
    structure_types = ["隧洞-圆形", "渡槽-U形", "矩形暗涵"]
    structure_type_str = draw(st.sampled_from(structure_types))
    
    node = ChannelNode()
    node.structure_type = StructureType.from_string(structure_type_str)
    node.name = draw(st.text(min_size=1, max_size=10))
    node.in_out = InOutType.INLET
    
    if "隧洞" in structure_type_str or "渡槽" in structure_type_str:
        node.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
    else:
        node.section_params = {"b": draw(st.floats(min_value=0.5, max_value=3.0)),
                              "h": draw(st.floats(min_value=0.5, max_value=2.0))}
    
    node.station_MC = draw(st.floats(min_value=0, max_value=5000))
    
    return node


@st.composite
def other_structure_outlet_strategy(draw):
    """生成其他建筑物（隧洞/渡槽/暗涵）出口节点"""
    structure_types = ["隧洞-圆形", "渡槽-U形", "矩形暗涵"]
    structure_type_str = draw(st.sampled_from(structure_types))
    
    node = ChannelNode()
    node.structure_type = StructureType.from_string(structure_type_str)
    node.name = draw(st.text(min_size=1, max_size=10))
    node.in_out = InOutType.OUTLET
    
    if "隧洞" in structure_type_str or "渡槽" in structure_type_str:
        node.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
    else:
        node.section_params = {"b": draw(st.floats(min_value=0.5, max_value=3.0)),
                              "h": draw(st.floats(min_value=0.5, max_value=2.0))}
    
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


@st.composite
def pressure_pipe_pair_strategy(draw):
    """生成有压管道节点对（出口和进口）"""
    # 决定是否同名
    same_name = draw(st.booleans())
    
    # 出口节点
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = draw(st.text(min_size=1, max_size=10, alphabet="有压管道ABC"))
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
    outlet.station_MC = draw(st.floats(min_value=0, max_value=5000))
    
    # 进口节点
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    
    if same_name:
        inlet.name = outlet.name
        # 决定是否同径
        same_diameter = draw(st.booleans())
        if same_diameter:
            inlet.section_params = {"D": outlet.section_params["D"]}
        else:
            inlet.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
    else:
        inlet.name = draw(st.text(min_size=1, max_size=10, alphabet="有压管道XYZ"))
        inlet.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
    
    inlet.in_out = InOutType.INLET
    inlet.station_MC = outlet.station_MC + draw(st.floats(min_value=1, max_value=100))
    
    return outlet, inlet


# ============================================================================
# 属性测试
# ============================================================================

@settings(max_examples=100, deadline=None)
@given(
    outlet=pressurized_flow_outlet_strategy(),
    inlet=other_structure_inlet_strategy()
)
def test_property_2_pressurized_outlet_to_other_inlet(
    outlet: ChannelNode, 
    inlet: ChannelNode
):
    """
    **Property 2: 有压流建筑物渐变段插入**
    
    **Validates: Requirements 2.1, 4.1, 4.2, 4.3**
    
    For any 有压流建筑物（倒虹吸或有压管道）出口节点和其他建筑物进口节点，
    当两者相邻且里程差大于零时，系统应在两者之间插入出口渐变段。
    
    验证点：
    1. 应插入出口渐变段 (need_transition_1=True)
    2. 应插入进口渐变段 (need_transition_2=True)
    3. 有压流侧渐变段标记 skip_loss=True
    4. 其他建筑物侧渐变段标记 skip_loss=False
    """
    # 确保进口里程大于出口里程
    if inlet.station_MC <= outlet.station_MC:
        inlet.station_MC = outlet.station_MC + 10.0
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 调用判断函数
    result = calculator._should_insert_open_channel(outlet, inlet)
    
    # 验证点 1 & 2: 应插入渐变段
    assert result['need_transition_1'] == True, \
        f"有压流出口 → 其他建筑物进口应插入出口渐变段"
    assert result['need_transition_2'] == True, \
        f"有压流出口 → 其他建筑物进口应插入进口渐变段"
    
    # 验证点 3: 有压流侧渐变段标记 skip_loss=True
    assert result['skip_loss_transition_1'] == True, \
        f"有压流侧渐变段应标记 skip_loss=True"
    
    # 验证点 4: 其他建筑物侧渐变段标记 skip_loss=False
    assert result['skip_loss_transition_2'] == False, \
        f"其他建筑物侧渐变段应标记 skip_loss=False"
    
    # 验证里程差计算
    expected_distance = inlet.station_MC - outlet.station_MC
    assert abs(result['distance'] - expected_distance) < 0.001, \
        f"里程差计算错误: 期望{expected_distance}，实际{result['distance']}"


@settings(max_examples=100, deadline=None)
@given(
    outlet=other_structure_outlet_strategy(),
    inlet=pressurized_flow_inlet_strategy()
)
def test_property_3_other_outlet_to_pressurized_inlet(
    outlet: ChannelNode, 
    inlet: ChannelNode
):
    """
    **Property 3: 有压流建筑物进口渐变段插入**
    
    **Validates: Requirements 2.2, 4.6**
    
    For any 其他建筑物出口节点和有压流建筑物（倒虹吸或有压管道）进口节点，
    当两者相邻且里程差大于零时，系统应在两者之间插入进口渐变段。
    
    验证点：
    1. 应插入出口渐变段 (need_transition_1=True)
    2. 应插入进口渐变段 (need_transition_2=True)
    3. 其他建筑物侧渐变段标记 skip_loss=False
    4. 有压流侧渐变段标记 skip_loss=True
    """
    # 确保进口里程大于出口里程
    if inlet.station_MC <= outlet.station_MC:
        inlet.station_MC = outlet.station_MC + 10.0
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 调用判断函数
    result = calculator._should_insert_open_channel(outlet, inlet)
    
    # 验证点 1 & 2: 应插入渐变段
    assert result['need_transition_1'] == True, \
        f"其他建筑物出口 → 有压流进口应插入出口渐变段"
    assert result['need_transition_2'] == True, \
        f"其他建筑物出口 → 有压流进口应插入进口渐变段"
    
    # 验证点 3: 其他建筑物侧渐变段标记 skip_loss=False
    assert result['skip_loss_transition_1'] == False, \
        f"其他建筑物侧渐变段应标记 skip_loss=False"
    
    # 验证点 4: 有压流侧渐变段标记 skip_loss=True
    assert result['skip_loss_transition_2'] == True, \
        f"有压流侧渐变段应标记 skip_loss=True"
    
    # 验证里程差计算
    expected_distance = inlet.station_MC - outlet.station_MC
    assert abs(result['distance'] - expected_distance) < 0.001, \
        f"里程差计算错误: 期望{expected_distance}，实际{result['distance']}"


@settings(max_examples=100, deadline=None)
@given(pair=pressure_pipe_pair_strategy())
def test_property_6_and_7_pressure_pipe_to_pressure_pipe(pair):
    """
    **Property 6: 同一有压管道不插入渐变段**
    **Property 7: 不同有压管道插入渐变段**
    
    **Validates: Requirements 2.4, 2.5, 4.4, 4.5**
    
    For any 两个连续的有压管道节点：
    - 如果它们属于同一建筑物（名称相同）且管径 D 相同，系统不应在两者之间插入渐变段
    - 如果它们属于不同建筑物（名称不同），系统应在两者之间插入渐变段，且两侧都标记 skip_loss=True
    
    验证点：
    1. 同名同径 → 不插入渐变段
    2. 不同名 → 插入渐变段，两侧都标记 skip_loss=True
    3. 同名不同径 → 插入渐变段，两侧都标记 skip_loss=True
    """
    outlet, inlet = pair
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 调用判断函数
    result = calculator._should_insert_open_channel(outlet, inlet)
    
    # 判断是否同名同径
    same_name = (outlet.name == inlet.name)
    diameter1 = outlet.section_params.get("D", 0)
    diameter2 = inlet.section_params.get("D", 0)
    same_diameter = abs(diameter1 - diameter2) < 0.001
    
    if same_name and same_diameter:
        # 验证点 1: 同名同径 → 不插入渐变段
        assert result['need_transition_1'] == False, \
            f"同名同径有压管道之间不应插入出口渐变段 (名称:{outlet.name}, 管径:{diameter1})"
        assert result['need_transition_2'] == False, \
            f"同名同径有压管道之间不应插入进口渐变段 (名称:{outlet.name}, 管径:{diameter1})"
        assert result['need_open_channel'] == False, \
            f"同名同径有压管道之间不应插入明渠段"
    else:
        # 验证点 2 & 3: 不同名或不同径 → 插入渐变段
        assert result['need_transition_1'] == True, \
            f"不同名或不同径有压管道之间应插入出口渐变段 (名称:{outlet.name}/{inlet.name}, 管径:{diameter1}/{diameter2})"
        assert result['need_transition_2'] == True, \
            f"不同名或不同径有压管道之间应插入进口渐变段 (名称:{outlet.name}/{inlet.name}, 管径:{diameter1}/{diameter2})"
        
        # 两侧都应标记 skip_loss=True
        assert result['skip_loss_transition_1'] == True, \
            f"有压管道侧渐变段应标记 skip_loss=True"
        assert result['skip_loss_transition_2'] == True, \
            f"有压管道侧渐变段应标记 skip_loss=True"


if __name__ == "__main__":
    import pytest
    
    print("运行有压管道渐变段插入属性测试...")
    print("\n注意：属性测试需要 pytest 和 hypothesis 库")
    print("运行命令: pytest tests/test_pressure_pipe_transition_property.py -v")
    print("\n如果直接运行此文件，将执行简单的冒烟测试...")
    
    # 简单的冒烟测试
    try:
        # 测试 Property 2
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = "有压管道1"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.5}
        outlet.station_MC = 100.0
        
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("隧洞-圆形")
        inlet.name = "隧洞1"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 2.0}
        inlet.station_MC = 120.0
        
        settings = ProjectSettings()
        calculator = WaterProfileCalculator(settings)
        result = calculator._should_insert_open_channel(outlet, inlet)
        
        assert result['need_transition_1'] == True
        assert result['skip_loss_transition_1'] == True
        print("✓ Property 2 冒烟测试通过")
        
        # 测试 Property 6
        pipe1_outlet = ChannelNode()
        pipe1_outlet.structure_type = StructureType.from_string("有压管道")
        pipe1_outlet.name = "有压管道1"
        pipe1_outlet.in_out = InOutType.OUTLET
        pipe1_outlet.section_params = {"D": 1.5}
        pipe1_outlet.station_MC = 100.0
        
        pipe1_inlet = ChannelNode()
        pipe1_inlet.structure_type = StructureType.from_string("有压管道")
        pipe1_inlet.name = "有压管道1"
        pipe1_inlet.in_out = InOutType.INLET
        pipe1_inlet.section_params = {"D": 1.5}
        pipe1_inlet.station_MC = 150.0
        
        result = calculator._should_insert_open_channel(pipe1_outlet, pipe1_inlet)
        assert result['need_transition_1'] == False
        print("✓ Property 6 冒烟测试通过")
        
        print("\n冒烟测试全部通过！")
        print("运行完整属性测试请使用: pytest tests/test_pressure_pipe_transition_property.py -v")
        
    except Exception as e:
        print(f"\n✗ 冒烟测试失败: {e}")
        import traceback
        traceback.print_exc()
