# -*- coding: utf-8 -*-
"""
有压管道渐变段长度计算 - 属性测试

**Validates: Requirements 2.6, 3.5, 14.1, 14.2, 14.3, 14.4**

Property 8: 渐变段长度计算一致性
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
def pressurized_flow_node_strategy(draw):
    """生成有压流建筑物节点（倒虹吸或有压管道）"""
    is_siphon = draw(st.booleans())
    
    node = ChannelNode()
    if is_siphon:
        node.structure_type = StructureType.from_string("倒虹吸")
        node.name = draw(st.text(min_size=1, max_size=10, alphabet="倒虹吸123"))
    else:
        node.structure_type = StructureType.from_string("有压管道")
        node.name = draw(st.text(min_size=1, max_size=10, alphabet="有压管道ABC"))
    
    # 生成管径 D
    node.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
    
    # 生成水深（可能为0或负数，测试默认值处理）
    node.water_depth = draw(st.floats(min_value=-1.0, max_value=5.0))
    
    # 生成进出口类型
    node.in_out = draw(st.sampled_from([InOutType.INLET, InOutType.OUTLET]))
    
    node.station_MC = draw(st.floats(min_value=0, max_value=5000))
    
    return node


# ============================================================================
# 属性测试
# ============================================================================

@settings(max_examples=100, deadline=None)
@given(node=pressurized_flow_node_strategy())
def test_property_8_transition_length_consistency(node: ChannelNode):
    """
    **Property 8: 渐变段长度计算一致性**
    
    **Validates: Requirements 2.6, 3.5, 14.1, 14.2, 14.3, 14.4**
    
    For any 有压管道节点，其渐变段长度计算应使用与倒虹吸相同的公式：
    - 进口渐变段长度 = 5 × h_design
    - 出口渐变段长度 = 6 × h_design
    - 当 water_depth ≤ 0 时，使用默认水深 2.0m
    
    验证点：
    1. 进口渐变段长度 = 5 × h_design
    2. 出口渐变段长度 = 6 × h_design
    3. 倒虹吸和有压管道使用相同的公式
    4. 当 water_depth ≤ 0 时，h_design = 2.0m
    """
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 确定设计水深
    h_design = node.water_depth if node.water_depth > 0 else 2.0
    
    # 测试进口渐变段长度
    inlet_length = calculator._estimate_transition_length(node, "进口")
    expected_inlet_length = 5 * h_design
    
    # 验证点 1: 进口渐变段长度 = 5 × h_design
    assert abs(inlet_length - expected_inlet_length) < 0.001, \
        f"进口渐变段长度计算错误: 期望 {expected_inlet_length}m (5×{h_design}), 实际 {inlet_length}m"
    
    # 测试出口渐变段长度
    outlet_length = calculator._estimate_transition_length(node, "出口")
    expected_outlet_length = 6 * h_design
    
    # 验证点 2: 出口渐变段长度 = 6 × h_design
    assert abs(outlet_length - expected_outlet_length) < 0.001, \
        f"出口渐变段长度计算错误: 期望 {expected_outlet_length}m (6×{h_design}), 实际 {outlet_length}m"
    
    # 验证点 3: 倒虹吸和有压管道使用相同的公式
    # 创建对应的另一种有压流建筑物节点
    other_node = ChannelNode()
    if "倒虹吸" in node.structure_type.value:
        other_node.structure_type = StructureType.from_string("有压管道")
    else:
        other_node.structure_type = StructureType.from_string("倒虹吸")
    
    other_node.section_params = node.section_params.copy()
    other_node.water_depth = node.water_depth
    other_node.in_out = node.in_out
    
    other_inlet_length = calculator._estimate_transition_length(other_node, "进口")
    other_outlet_length = calculator._estimate_transition_length(other_node, "出口")
    
    assert abs(inlet_length - other_inlet_length) < 0.001, \
        f"倒虹吸和有压管道的进口渐变段长度应相同: {inlet_length} vs {other_inlet_length}"
    assert abs(outlet_length - other_outlet_length) < 0.001, \
        f"倒虹吸和有压管道的出口渐变段长度应相同: {outlet_length} vs {other_outlet_length}"
    
    # 验证点 4: 当 water_depth ≤ 0 时，h_design = 2.0m
    if node.water_depth <= 0:
        assert abs(inlet_length - 10.0) < 0.001, \
            f"当 water_depth ≤ 0 时，进口渐变段长度应为 10.0m (5×2.0), 实际 {inlet_length}m"
        assert abs(outlet_length - 12.0) < 0.001, \
            f"当 water_depth ≤ 0 时，出口渐变段长度应为 12.0m (6×2.0), 实际 {outlet_length}m"


@settings(max_examples=100, deadline=None)
@given(
    water_depth=st.floats(min_value=0.1, max_value=5.0),
    is_siphon=st.booleans()
)
def test_property_8_formula_correctness(water_depth: float, is_siphon: bool):
    """
    **Property 8: 渐变段长度计算公式正确性**
    
    **Validates: Requirements 14.1, 14.2, 14.3**
    
    验证渐变段长度计算公式的正确性：
    - 进口: L = 5 × h_design
    - 出口: L = 6 × h_design
    """
    # 创建节点
    node = ChannelNode()
    if is_siphon:
        node.structure_type = StructureType.from_string("倒虹吸")
    else:
        node.structure_type = StructureType.from_string("有压管道")
    
    node.section_params = {"D": 1.5}
    node.water_depth = water_depth
    node.in_out = InOutType.INLET
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 计算渐变段长度
    inlet_length = calculator._estimate_transition_length(node, "进口")
    outlet_length = calculator._estimate_transition_length(node, "出口")
    
    # 验证公式
    expected_inlet = 5 * water_depth
    expected_outlet = 6 * water_depth
    
    assert abs(inlet_length - expected_inlet) < 0.001, \
        f"进口渐变段长度公式错误: 期望 5×{water_depth}={expected_inlet}, 实际 {inlet_length}"
    assert abs(outlet_length - expected_outlet) < 0.001, \
        f"出口渐变段长度公式错误: 期望 6×{water_depth}={expected_outlet}, 实际 {outlet_length}"


@settings(max_examples=50, deadline=None)
@given(
    water_depth=st.floats(min_value=-5.0, max_value=0.0)
)
def test_property_8_default_water_depth_handling(water_depth: float):
    """
    **Property 8: 默认水深处理**
    
    **Validates: Requirements 14.4**
    
    验证当 water_depth ≤ 0 时，使用默认水深 2.0m
    """
    # 创建有压管道节点
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.section_params = {"D": 1.5}
    node.water_depth = water_depth
    node.in_out = InOutType.INLET
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 计算渐变段长度
    inlet_length = calculator._estimate_transition_length(node, "进口")
    outlet_length = calculator._estimate_transition_length(node, "出口")
    
    # 验证使用默认水深 2.0m
    assert abs(inlet_length - 10.0) < 0.001, \
        f"当 water_depth={water_depth} ≤ 0 时，进口渐变段长度应为 10.0m (5×2.0), 实际 {inlet_length}m"
    assert abs(outlet_length - 12.0) < 0.001, \
        f"当 water_depth={water_depth} ≤ 0 时，出口渐变段长度应为 12.0m (6×2.0), 实际 {outlet_length}m"


if __name__ == "__main__":
    import pytest
    
    print("运行有压管道渐变段长度计算属性测试...")
    print("\n注意：属性测试需要 pytest 和 hypothesis 库")
    print("运行命令: pytest tests/test_transition_length_property.py -v")
    print("\n如果直接运行此文件，将执行简单的冒烟测试...")
    
    # 简单的冒烟测试
    try:
        # 测试有压管道进口渐变段长度
        node = ChannelNode()
        node.structure_type = StructureType.from_string("有压管道")
        node.section_params = {"D": 1.5}
        node.water_depth = 2.5
        node.in_out = InOutType.INLET
        
        settings = ProjectSettings()
        calculator = WaterProfileCalculator(settings)
        
        inlet_length = calculator._estimate_transition_length(node, "进口")
        outlet_length = calculator._estimate_transition_length(node, "出口")
        
        assert abs(inlet_length - 12.5) < 0.001, f"进口渐变段长度应为 12.5m (5×2.5), 实际 {inlet_length}m"
        assert abs(outlet_length - 15.0) < 0.001, f"出口渐变段长度应为 15.0m (6×2.5), 实际 {outlet_length}m"
        print("✓ 有压管道渐变段长度计算测试通过")
        
        # 测试倒虹吸渐变段长度（应与有压管道相同）
        siphon_node = ChannelNode()
        siphon_node.structure_type = StructureType.from_string("倒虹吸")
        siphon_node.section_params = {"D": 1.5}
        siphon_node.water_depth = 2.5
        siphon_node.in_out = InOutType.INLET
        
        siphon_inlet_length = calculator._estimate_transition_length(siphon_node, "进口")
        siphon_outlet_length = calculator._estimate_transition_length(siphon_node, "出口")
        
        assert abs(siphon_inlet_length - inlet_length) < 0.001, "倒虹吸和有压管道进口渐变段长度应相同"
        assert abs(siphon_outlet_length - outlet_length) < 0.001, "倒虹吸和有压管道出口渐变段长度应相同"
        print("✓ 倒虹吸与有压管道公式一致性测试通过")
        
        # 测试默认水深处理
        node_zero_depth = ChannelNode()
        node_zero_depth.structure_type = StructureType.from_string("有压管道")
        node_zero_depth.section_params = {"D": 1.5}
        node_zero_depth.water_depth = 0.0
        node_zero_depth.in_out = InOutType.INLET
        
        inlet_length_default = calculator._estimate_transition_length(node_zero_depth, "进口")
        outlet_length_default = calculator._estimate_transition_length(node_zero_depth, "出口")
        
        assert abs(inlet_length_default - 10.0) < 0.001, f"默认水深进口渐变段长度应为 10.0m, 实际 {inlet_length_default}m"
        assert abs(outlet_length_default - 12.0) < 0.001, f"默认水深出口渐变段长度应为 12.0m, 实际 {outlet_length_default}m"
        print("✓ 默认水深处理测试通过")
        
        print("\n冒烟测试全部通过！")
        print("运行完整属性测试请使用: pytest tests/test_transition_length_property.py -v")
        
    except Exception as e:
        print(f"\n✗ 冒烟测试失败: {e}")
        import traceback
        traceback.print_exc()
