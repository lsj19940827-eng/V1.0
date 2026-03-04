# -*- coding: utf-8 -*-
"""
有压管道渐变段长度计算 - 单元测试

**Validates: Requirements 2.6, 14.1, 14.2, 14.3**

测试 _estimate_transition_length() 函数对有压管道的处理：
- 测试有压管道进口渐变段长度
- 测试有压管道出口渐变段长度
- 测试与倒虹吸公式一致性
- 测试默认水深处理
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.calculator import WaterProfileCalculator


def test_pressure_pipe_inlet_transition_length():
    """
    测试有压管道进口渐变段长度
    
    **Validates: Requirement 14.1**
    
    验证：
    - 进口渐变段长度 = 5 × h_design
    - 使用 GB 50288-2018 §10.2.4 公式
    """
    # 创建有压管道节点
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "有压管道1"
    node.section_params = {"D": 1.5}
    node.water_depth = 2.5  # 设计水深 2.5m
    node.in_out = InOutType.INLET
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 计算进口渐变段长度
    inlet_length = calculator._estimate_transition_length(node, "进口")
    
    # 验证：进口渐变段长度 = 5 × 2.5 = 12.5m
    expected_length = 5 * 2.5
    assert abs(inlet_length - expected_length) < 0.001, \
        f"有压管道进口渐变段长度应为 {expected_length}m (5×2.5), 实际 {inlet_length}m"


def test_pressure_pipe_outlet_transition_length():
    """
    测试有压管道出口渐变段长度
    
    **Validates: Requirement 14.2**
    
    验证：
    - 出口渐变段长度 = 6 × h_design
    - 使用 GB 50288-2018 §10.2.4 公式
    """
    # 创建有压管道节点
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "有压管道1"
    node.section_params = {"D": 1.5}
    node.water_depth = 3.0  # 设计水深 3.0m
    node.in_out = InOutType.OUTLET
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 计算出口渐变段长度
    outlet_length = calculator._estimate_transition_length(node, "出口")
    
    # 验证：出口渐变段长度 = 6 × 3.0 = 18.0m
    expected_length = 6 * 3.0
    assert abs(outlet_length - expected_length) < 0.001, \
        f"有压管道出口渐变段长度应为 {expected_length}m (6×3.0), 实际 {outlet_length}m"


def test_siphon_pressure_pipe_formula_consistency():
    """
    测试倒虹吸与有压管道公式一致性
    
    **Validates: Requirement 2.6, 14.3**
    
    验证：
    - 倒虹吸和有压管道使用相同的渐变段长度计算公式
    - 进口: 5 × h_design
    - 出口: 6 × h_design
    """
    # 创建有压管道节点
    pressure_pipe = ChannelNode()
    pressure_pipe.structure_type = StructureType.from_string("有压管道")
    pressure_pipe.name = "有压管道1"
    pressure_pipe.section_params = {"D": 1.5}
    pressure_pipe.water_depth = 2.0
    pressure_pipe.in_out = InOutType.INLET
    
    # 创建倒虹吸节点（相同参数）
    siphon = ChannelNode()
    siphon.structure_type = StructureType.from_string("倒虹吸")
    siphon.name = "倒虹吸1"
    siphon.section_params = {"D": 1.5}
    siphon.water_depth = 2.0
    siphon.in_out = InOutType.INLET
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 计算进口渐变段长度
    pipe_inlet_length = calculator._estimate_transition_length(pressure_pipe, "进口")
    siphon_inlet_length = calculator._estimate_transition_length(siphon, "进口")
    
    # 验证进口渐变段长度一致
    assert abs(pipe_inlet_length - siphon_inlet_length) < 0.001, \
        f"有压管道和倒虹吸的进口渐变段长度应相同: {pipe_inlet_length}m vs {siphon_inlet_length}m"
    
    # 验证进口渐变段长度 = 5 × 2.0 = 10.0m
    assert abs(pipe_inlet_length - 10.0) < 0.001, \
        f"进口渐变段长度应为 10.0m (5×2.0), 实际 {pipe_inlet_length}m"
    
    # 计算出口渐变段长度
    pipe_outlet_length = calculator._estimate_transition_length(pressure_pipe, "出口")
    siphon_outlet_length = calculator._estimate_transition_length(siphon, "出口")
    
    # 验证出口渐变段长度一致
    assert abs(pipe_outlet_length - siphon_outlet_length) < 0.001, \
        f"有压管道和倒虹吸的出口渐变段长度应相同: {pipe_outlet_length}m vs {siphon_outlet_length}m"
    
    # 验证出口渐变段长度 = 6 × 2.0 = 12.0m
    assert abs(pipe_outlet_length - 12.0) < 0.001, \
        f"出口渐变段长度应为 12.0m (6×2.0), 实际 {pipe_outlet_length}m"


def test_default_water_depth_handling():
    """
    测试默认水深处理
    
    **Validates: Requirement 14.4**
    
    验证：
    - 当 water_depth ≤ 0 时，使用默认水深 2.0m
    - 进口渐变段长度 = 5 × 2.0 = 10.0m
    - 出口渐变段长度 = 6 × 2.0 = 12.0m
    """
    # 创建有压管道节点（水深为0）
    node_zero = ChannelNode()
    node_zero.structure_type = StructureType.from_string("有压管道")
    node_zero.name = "有压管道1"
    node_zero.section_params = {"D": 1.5}
    node_zero.water_depth = 0.0
    node_zero.in_out = InOutType.INLET
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 计算渐变段长度
    inlet_length = calculator._estimate_transition_length(node_zero, "进口")
    outlet_length = calculator._estimate_transition_length(node_zero, "出口")
    
    # 验证使用默认水深 2.0m
    assert abs(inlet_length - 10.0) < 0.001, \
        f"当 water_depth=0 时，进口渐变段长度应为 10.0m (5×2.0), 实际 {inlet_length}m"
    assert abs(outlet_length - 12.0) < 0.001, \
        f"当 water_depth=0 时，出口渐变段长度应为 12.0m (6×2.0), 实际 {outlet_length}m"
    
    # 测试负水深
    node_negative = ChannelNode()
    node_negative.structure_type = StructureType.from_string("有压管道")
    node_negative.name = "有压管道2"
    node_negative.section_params = {"D": 1.5}
    node_negative.water_depth = -1.5
    node_negative.in_out = InOutType.INLET
    
    inlet_length_neg = calculator._estimate_transition_length(node_negative, "进口")
    outlet_length_neg = calculator._estimate_transition_length(node_negative, "出口")
    
    # 验证使用默认水深 2.0m
    assert abs(inlet_length_neg - 10.0) < 0.001, \
        f"当 water_depth=-1.5 时，进口渐变段长度应为 10.0m (5×2.0), 实际 {inlet_length_neg}m"
    assert abs(outlet_length_neg - 12.0) < 0.001, \
        f"当 water_depth=-1.5 时，出口渐变段长度应为 12.0m (6×2.0), 实际 {outlet_length_neg}m"


def test_various_water_depths():
    """
    测试不同水深下的渐变段长度计算
    
    验证：
    - 不同水深下公式正确应用
    - 进口: 5 × h_design
    - 出口: 6 × h_design
    """
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 测试多个水深值
    test_cases = [
        (1.0, 5.0, 6.0),    # 水深1.0m: 进口5.0m, 出口6.0m
        (1.5, 7.5, 9.0),    # 水深1.5m: 进口7.5m, 出口9.0m
        (2.0, 10.0, 12.0),  # 水深2.0m: 进口10.0m, 出口12.0m
        (3.0, 15.0, 18.0),  # 水深3.0m: 进口15.0m, 出口18.0m
        (4.5, 22.5, 27.0),  # 水深4.5m: 进口22.5m, 出口27.0m
    ]
    
    for water_depth, expected_inlet, expected_outlet in test_cases:
        # 创建有压管道节点
        node = ChannelNode()
        node.structure_type = StructureType.from_string("有压管道")
        node.name = "有压管道1"
        node.section_params = {"D": 1.5}
        node.water_depth = water_depth
        node.in_out = InOutType.INLET
        
        # 计算渐变段长度
        inlet_length = calculator._estimate_transition_length(node, "进口")
        outlet_length = calculator._estimate_transition_length(node, "出口")
        
        # 验证结果
        assert abs(inlet_length - expected_inlet) < 0.001, \
            f"水深{water_depth}m时，进口渐变段长度应为 {expected_inlet}m, 实际 {inlet_length}m"
        assert abs(outlet_length - expected_outlet) < 0.001, \
            f"水深{water_depth}m时，出口渐变段长度应为 {expected_outlet}m, 实际 {outlet_length}m"


def test_inlet_outlet_ratio():
    """
    测试进口和出口渐变段长度比例
    
    验证：
    - 出口渐变段长度 / 进口渐变段长度 = 6 / 5 = 1.2
    """
    # 创建有压管道节点
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "有压管道1"
    node.section_params = {"D": 1.5}
    node.water_depth = 2.8
    node.in_out = InOutType.INLET
    
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 计算渐变段长度
    inlet_length = calculator._estimate_transition_length(node, "进口")
    outlet_length = calculator._estimate_transition_length(node, "出口")
    
    # 验证比例
    ratio = outlet_length / inlet_length
    expected_ratio = 6.0 / 5.0
    
    assert abs(ratio - expected_ratio) < 0.001, \
        f"出口/进口渐变段长度比例应为 {expected_ratio}, 实际 {ratio}"


if __name__ == "__main__":
    print("运行有压管道渐变段长度计算单元测试...")
    
    test_pressure_pipe_inlet_transition_length()
    print("✓ 测试有压管道进口渐变段长度")
    
    test_pressure_pipe_outlet_transition_length()
    print("✓ 测试有压管道出口渐变段长度")
    
    test_siphon_pressure_pipe_formula_consistency()
    print("✓ 测试倒虹吸与有压管道公式一致性")
    
    test_default_water_depth_handling()
    print("✓ 测试默认水深处理")
    
    test_various_water_depths()
    print("✓ 测试不同水深下的渐变段长度计算")
    
    test_inlet_outlet_ratio()
    print("✓ 测试进口和出口渐变段长度比例")
    
    print("\n所有单元测试通过！")
