# -*- coding: utf-8 -*-
"""
有压管道数据提取和分组 - 单元测试

**Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5**

测试有压管道数据提取和分组功能的具体示例和边界情况。
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode
from models.enums import StructureType, InOutType
from core.pressure_pipe_data import PressurePipeDataExtractor, PressurePipeGroup


def test_extract_single_pressure_pipe():
    """
    测试提取单个有压管道
    
    **Validates: Requirements 12.1, 12.3, 12.4**
    """
    # 创建进口节点
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = "有压管道1"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 1.5}
    inlet.flow = 2.5
    inlet.roughness = 0.014
    inlet.station_MC = 100
    
    # 创建出口节点
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "有压管道1"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.5}
    outlet.flow = 2.5
    outlet.roughness = 0.014
    outlet.station_MC = 200
    
    nodes = [inlet, outlet]
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证
    assert len(groups) == 1, "应提取到一个分组"
    
    group = groups[0]
    assert group.name == "有压管道1"
    assert group.inlet_node == inlet
    assert group.outlet_node == outlet
    assert group.inlet_row_index == 0
    assert group.outlet_row_index == 1
    assert group.diameter_D == 1.5
    assert group.flow == 2.5
    assert group.roughness == 0.014
    assert group.is_valid()


def test_extract_multiple_pressure_pipes():
    """
    测试提取多个有压管道
    
    **Validates: Requirement 12.1**
    """
    nodes = []
    
    # 创建3个有压管道
    for i in range(3):
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("有压管道")
        inlet.name = f"有压管道{i+1}"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 1.0 + i * 0.5}
        inlet.flow = 1.0 + i
        inlet.roughness = 0.014
        inlet.station_MC = i * 200
        nodes.append(inlet)
        
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = f"有压管道{i+1}"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.0 + i * 0.5}
        outlet.flow = 1.0 + i
        outlet.roughness = 0.014
        outlet.station_MC = i * 200 + 100
        nodes.append(outlet)
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证
    assert len(groups) == 3, "应提取到3个分组"
    
    for i, group in enumerate(groups):
        assert group.name == f"有压管道{i+1}"
        assert group.is_valid()
        assert group.diameter_D == 1.0 + i * 0.5
        assert group.flow == 1.0 + i


def test_extract_with_default_naming():
    """
    测试无名称节点的默认命名
    
    **Validates: Requirement 12.2**
    """
    # 创建无名称的进出口对
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = ""  # 空名称
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 1.0}
    inlet.flow = 1.0
    inlet.station_MC = 0
    
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = ""  # 空名称
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.0}
    outlet.flow = 1.0
    outlet.station_MC = 100
    
    nodes = [inlet, outlet]
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证
    assert len(groups) == 1, "应提取到一个分组"
    
    group = groups[0]
    assert group.name == "有压管道1", f"默认名称应为'有压管道1'，实际为'{group.name}'"
    assert group.is_valid()


def test_extract_multiple_unnamed_pairs():
    """
    测试多个无名称进出口对的默认命名
    
    **Validates: Requirement 12.2**
    """
    nodes = []
    
    # 创建3对无名称的进出口
    for i in range(3):
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("有压管道")
        inlet.name = ""
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 1.0}
        inlet.flow = 1.0
        inlet.station_MC = i * 200
        nodes.append(inlet)
        
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = ""
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.0}
        outlet.flow = 1.0
        outlet.station_MC = i * 200 + 100
        nodes.append(outlet)
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证
    assert len(groups) == 3, "应提取到3个分组"
    
    # 验证默认名称是唯一的
    names = [g.name for g in groups]
    assert len(set(names)) == 3, "默认名称应该是唯一的"
    
    for i, group in enumerate(groups):
        assert group.name.startswith("有压管道"), f"默认名称应以'有压管道'开头"
        assert group.is_valid()


def test_extract_incomplete_group_inlet_only():
    """
    测试只有进口没有出口的不完整分组
    
    **Validates: Requirement 12.5**
    """
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = "不完整有压管道"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 1.0}
    inlet.flow = 1.0
    
    nodes = [inlet]
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证
    assert len(groups) == 1, "应提取到一个分组"
    
    group = groups[0]
    assert group.name == "不完整有压管道"
    assert group.inlet_node is not None
    assert group.outlet_node is None
    assert not group.is_valid(), "只有进口的分组应该是无效的"
    
    # 验证错误消息
    msg = group.get_validation_message()
    assert "未识别到出口节点" in msg


def test_extract_incomplete_group_outlet_only():
    """
    测试只有出口没有进口的不完整分组
    
    **Validates: Requirement 12.5**
    """
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "不完整有压管道"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.0}
    outlet.flow = 1.0
    
    nodes = [outlet]
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证
    assert len(groups) == 1, "应提取到一个分组"
    
    group = groups[0]
    assert group.name == "不完整有压管道"
    assert group.inlet_node is None
    assert group.outlet_node is not None
    assert not group.is_valid(), "只有出口的分组应该是无效的"
    
    # 验证错误消息
    msg = group.get_validation_message()
    assert "未识别到进口节点" in msg


def test_extract_with_mixed_structures():
    """
    测试混合结构类型的节点列表
    
    验证只提取有压管道节点，忽略其他类型
    """
    # 创建混合节点列表
    nodes = []
    
    # 明渠节点
    channel = ChannelNode()
    channel.structure_type = StructureType.from_string("明渠-梯形")
    channel.name = "明渠段"
    nodes.append(channel)
    
    # 有压管道进口
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = "有压管道1"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 1.5}
    inlet.flow = 2.0
    nodes.append(inlet)
    
    # 隧洞节点
    tunnel = ChannelNode()
    tunnel.structure_type = StructureType.from_string("隧洞-圆形")
    tunnel.name = "隧洞段"
    nodes.append(tunnel)
    
    # 有压管道出口
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "有压管道1"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.5}
    outlet.flow = 2.0
    nodes.append(outlet)
    
    # 倒虹吸节点
    siphon = ChannelNode()
    siphon.structure_type = StructureType.from_string("倒虹吸")
    siphon.name = "倒虹吸"
    nodes.append(siphon)
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证
    assert len(groups) == 1, "应只提取到一个有压管道分组"
    
    group = groups[0]
    assert group.name == "有压管道1"
    assert group.is_valid()


def test_parameter_extraction_from_inlet():
    """
    测试从进口节点提取参数
    
    **Validates: Requirements 12.3, 12.4**
    """
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = "测试管道"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 2.0}
    inlet.flow = 3.5
    inlet.roughness = 0.016
    
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "测试管道"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 2.0}
    outlet.flow = 3.5
    outlet.roughness = 0.016
    
    nodes = [inlet, outlet]
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证参数提取
    group = groups[0]
    assert group.diameter_D == 2.0, "管径应从进口节点提取"
    assert group.flow == 3.5, "流量应从进口节点提取"
    assert group.roughness == 0.016, "糙率应从进口节点提取"


def test_parameter_extraction_from_outlet_when_inlet_missing():
    """
    测试当进口节点缺失时从出口节点提取参数
    
    **Validates: Requirements 12.3, 12.4**
    """
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "测试管道"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.8}
    outlet.flow = 2.8
    outlet.roughness = 0.015
    
    nodes = [outlet]
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证参数提取
    group = groups[0]
    assert group.diameter_D == 1.8, "管径应从出口节点提取"
    assert group.flow == 2.8, "流量应从出口节点提取"
    assert group.roughness == 0.015, "糙率应从出口节点提取"


def test_row_index_tracking():
    """
    测试行索引正确记录
    
    **Validates: Requirement 12.4**
    """
    nodes = []
    
    # 添加一些其他节点
    for i in range(3):
        other = ChannelNode()
        other.structure_type = StructureType.from_string("明渠-梯形")
        nodes.append(other)
    
    # 添加有压管道进口（索引3）
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = "有压管道1"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 1.0}
    inlet.flow = 1.0
    nodes.append(inlet)
    
    # 添加更多其他节点
    for i in range(2):
        other = ChannelNode()
        other.structure_type = StructureType.from_string("隧洞-圆形")
        nodes.append(other)
    
    # 添加有压管道出口（索引6）
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "有压管道1"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.0}
    outlet.flow = 1.0
    nodes.append(outlet)
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证行索引
    group = groups[0]
    assert group.inlet_row_index == 3, "进口行索引应为3"
    assert group.outlet_row_index == 6, "出口行索引应为6"
    assert nodes[group.inlet_row_index] == inlet
    assert nodes[group.outlet_row_index] == outlet


def test_get_pressure_pipe_names():
    """
    测试快速获取有压管道名称列表
    """
    nodes = []
    
    # 创建多个有压管道
    for i in range(3):
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("有压管道")
        inlet.name = f"管道{i+1}"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 1.0}
        nodes.append(inlet)
        
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = f"管道{i+1}"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.0}
        nodes.append(outlet)
    
    # 添加一些其他节点
    other = ChannelNode()
    other.structure_type = StructureType.from_string("明渠-梯形")
    nodes.append(other)
    
    # 获取名称列表
    names = PressurePipeDataExtractor.get_pressure_pipe_names(nodes)
    
    # 验证
    assert len(names) == 3
    assert "管道1" in names
    assert "管道2" in names
    assert "管道3" in names


def test_validate_pressure_pipe_groups():
    """
    测试分组验证功能
    """
    # 创建有效分组
    valid_group = PressurePipeGroup(name="有效管道")
    valid_group.inlet_node = ChannelNode()
    valid_group.outlet_node = ChannelNode()
    valid_group.inlet_row_index = 0
    valid_group.outlet_row_index = 1
    valid_group.diameter_D = 1.5
    
    # 创建无效分组（缺少出口）
    invalid_group = PressurePipeGroup(name="无效管道")
    invalid_group.inlet_node = ChannelNode()
    invalid_group.inlet_row_index = 0
    invalid_group.diameter_D = 1.5
    
    groups = [valid_group, invalid_group]
    
    # 验证
    all_valid, messages = PressurePipeDataExtractor.validate_pressure_pipe_groups(groups)
    
    assert not all_valid, "应检测到无效分组"
    assert len(messages) > 0, "应有验证错误消息"
    assert "无效管道" in messages[0], "错误消息应包含分组名称"


def test_empty_node_list():
    """
    测试空节点列表
    """
    nodes = []
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证
    assert len(groups) == 0, "空节点列表应返回空分组列表"


def test_no_pressure_pipes():
    """
    测试不包含有压管道的节点列表
    """
    nodes = []
    
    # 只添加其他类型的节点
    for _ in range(5):
        node = ChannelNode()
        node.structure_type = StructureType.from_string("明渠-梯形")
        nodes.append(node)
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证
    assert len(groups) == 0, "不包含有压管道的列表应返回空分组列表"


if __name__ == "__main__":
    # 运行所有测试
    import pytest
    pytest.main([__file__, "-v"])
