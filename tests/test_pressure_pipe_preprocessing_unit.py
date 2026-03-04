# -*- coding: utf-8 -*-
"""
有压管道节点预处理 - 单元测试

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**

测试 preprocess_nodes() 函数对有压管道节点的处理：
- 测试有压管道节点正确识别
- 测试管径 D 提取
- 测试进出口标识提取
- 测试建筑物名称提取
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.calculator import WaterProfileCalculator


def test_pressure_pipe_node_identification():
    """
    测试有压管道节点正确识别
    
    **Validates: Requirement 1.1**
    """
    # 创建测试节点
    pressure_pipe = ChannelNode()
    pressure_pipe.structure_type = StructureType.from_string("有压管道")
    pressure_pipe.name = "有压管道1"
    pressure_pipe.section_params = {"D": 1.5}
    
    channel = ChannelNode()
    channel.structure_type = StructureType.from_string("明渠-梯形")
    channel.name = "明渠1"
    
    nodes = [pressure_pipe, channel]
    
    # 预处理节点
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    calculator.preprocess_nodes(nodes)
    
    # 验证有压管道节点被正确识别
    assert nodes[0].is_pressure_pipe == True, "有压管道节点应设置 is_pressure_pipe=True"
    assert nodes[1].is_pressure_pipe == False, "明渠节点不应设置 is_pressure_pipe=True"


def test_diameter_extraction():
    """
    测试管径 D 提取
    
    **Validates: Requirement 1.3**
    """
    # 创建有压管道节点，管径为 2.0m
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "有压管道1"
    node.section_params = {"D": 2.0}
    
    # 预处理节点
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    calculator.preprocess_nodes([node])
    
    # 验证管径被保留在 section_params 中
    assert "D" in node.section_params, "有压管道节点应包含管径 D"
    assert node.section_params["D"] == 2.0, f"管径应为 2.0，实际为 {node.section_params['D']}"


def test_inlet_outlet_identification():
    """
    测试进出口标识提取
    
    **Validates: Requirement 1.2**
    
    业务规则：同一建筑物的第一次出现为进口，最后一次出现为出口
    """
    # 创建同一有压管道的多个节点
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = "有压管道1"
    inlet.section_params = {"D": 1.5}
    inlet.x = 0
    inlet.y = 0
    
    middle = ChannelNode()
    middle.structure_type = StructureType.from_string("有压管道")
    middle.name = "有压管道1"
    middle.section_params = {"D": 1.5}
    middle.x = 100
    middle.y = 0
    
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "有压管道1"
    outlet.section_params = {"D": 1.5}
    outlet.x = 200
    outlet.y = 0
    
    nodes = [inlet, middle, outlet]
    
    # 预处理节点
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    calculator.preprocess_nodes(nodes)
    
    # 验证进出口标识
    assert nodes[0].in_out == InOutType.INLET, "第一个节点应为进口"
    assert nodes[1].in_out == InOutType.NORMAL, "中间节点应为普通断面"
    assert nodes[2].in_out == InOutType.OUTLET, "最后一个节点应为出口"


def test_building_name_extraction():
    """
    测试建筑物名称提取
    
    **Validates: Requirement 1.4**
    """
    # 创建有压管道节点，带有建筑物名称
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "有压管道A"
    node.section_params = {"D": 1.2}
    
    # 预处理节点
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    calculator.preprocess_nodes([node])
    
    # 验证建筑物名称被保留
    assert node.name == "有压管道A", f"建筑物名称应为'有压管道A'，实际为'{node.name}'"
    assert node.is_pressure_pipe == True, "有压管道节点应被正确标记"


def test_multiple_pressure_pipes_with_different_names():
    """
    测试多个不同名称的有压管道
    
    **Validates: Requirements 1.1, 1.4**
    
    验证不同名称的有压管道能够被独立识别和分组
    """
    # 创建两个不同名称的有压管道
    pipe1_inlet = ChannelNode()
    pipe1_inlet.structure_type = StructureType.from_string("有压管道")
    pipe1_inlet.name = "有压管道1"
    pipe1_inlet.section_params = {"D": 1.0}
    
    pipe1_outlet = ChannelNode()
    pipe1_outlet.structure_type = StructureType.from_string("有压管道")
    pipe1_outlet.name = "有压管道1"
    pipe1_outlet.section_params = {"D": 1.0}
    
    pipe2_inlet = ChannelNode()
    pipe2_inlet.structure_type = StructureType.from_string("有压管道")
    pipe2_inlet.name = "有压管道2"
    pipe2_inlet.section_params = {"D": 1.5}
    
    pipe2_outlet = ChannelNode()
    pipe2_outlet.structure_type = StructureType.from_string("有压管道")
    pipe2_outlet.name = "有压管道2"
    pipe2_outlet.section_params = {"D": 1.5}
    
    nodes = [pipe1_inlet, pipe1_outlet, pipe2_inlet, pipe2_outlet]
    
    # 预处理节点
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    calculator.preprocess_nodes(nodes)
    
    # 验证所有节点都被标记为有压管道
    for node in nodes:
        assert node.is_pressure_pipe == True, f"节点 {node.name} 应被标记为有压管道"
    
    # 验证进出口标识
    assert nodes[0].in_out == InOutType.INLET, "有压管道1 第一个节点应为进口"
    assert nodes[1].in_out == InOutType.OUTLET, "有压管道1 第二个节点应为出口"
    assert nodes[2].in_out == InOutType.INLET, "有压管道2 第一个节点应为进口"
    assert nodes[3].in_out == InOutType.OUTLET, "有压管道2 第二个节点应为出口"


def test_pressure_pipe_with_siphon():
    """
    测试有压管道与倒虹吸共存
    
    **Validates: Requirements 1.1, 1.6**
    
    验证有压管道和倒虹吸能够被正确区分
    """
    # 创建有压管道和倒虹吸节点
    pressure_pipe = ChannelNode()
    pressure_pipe.structure_type = StructureType.from_string("有压管道")
    pressure_pipe.name = "有压管道1"
    pressure_pipe.section_params = {"D": 1.5}
    
    siphon = ChannelNode()
    siphon.structure_type = StructureType.from_string("倒虹吸")
    siphon.name = "倒虹吸1"
    siphon.section_params = {"D": 1.2}
    
    nodes = [pressure_pipe, siphon]
    
    # 预处理节点
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    calculator.preprocess_nodes(nodes)
    
    # 验证有压管道标记
    assert nodes[0].is_pressure_pipe == True, "有压管道节点应设置 is_pressure_pipe=True"
    assert nodes[0].is_inverted_siphon == False, "有压管道节点不应设置 is_inverted_siphon=True"
    
    # 验证倒虹吸标记
    assert nodes[1].is_pressure_pipe == False, "倒虹吸节点不应设置 is_pressure_pipe=True"
    assert nodes[1].is_inverted_siphon == True, "倒虹吸节点应设置 is_inverted_siphon=True"
    
    # 验证 is_pressurized_flow_structure() 函数
    assert calculator.is_pressurized_flow_structure(nodes[0]) == True, \
        "有压管道应被识别为有压流建筑物"
    assert calculator.is_pressurized_flow_structure(nodes[1]) == True, \
        "倒虹吸应被识别为有压流建筑物"
    
    # 验证 is_pressure_pipe() 函数
    assert calculator.is_pressure_pipe(nodes[0]) == True, \
        "有压管道应被 is_pressure_pipe() 识别"
    assert calculator.is_pressure_pipe(nodes[1]) == False, \
        "倒虹吸不应被 is_pressure_pipe() 识别为有压管道"


if __name__ == "__main__":
    print("运行有压管道节点预处理单元测试...")
    
    test_pressure_pipe_node_identification()
    print("✓ 测试有压管道节点正确识别")
    
    test_diameter_extraction()
    print("✓ 测试管径 D 提取")
    
    test_inlet_outlet_identification()
    print("✓ 测试进出口标识提取")
    
    test_building_name_extraction()
    print("✓ 测试建筑物名称提取")
    
    test_multiple_pressure_pipes_with_different_names()
    print("✓ 测试多个不同名称的有压管道")
    
    test_pressure_pipe_with_siphon()
    print("✓ 测试有压管道与倒虹吸共存")
    
    print("\n所有单元测试通过！")
