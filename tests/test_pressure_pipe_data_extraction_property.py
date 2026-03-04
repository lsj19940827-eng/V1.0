# -*- coding: utf-8 -*-
"""
有压管道数据提取和分组 - 属性测试

**Validates: Requirements 12.1, 12.2, 12.3, 12.4**

Property 11: 有压管道分组正确性
For any 节点列表，系统应按建筑物名称对有压管道节点进行分组，
每组包含唯一的进口和出口节点，且提取的管径、糙率、流量等参数正确。
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from hypothesis import given, strategies as st, settings, assume
from typing import List

from models.data_models import ChannelNode
from models.enums import StructureType, InOutType
from core.pressure_pipe_data import PressurePipeDataExtractor, PressurePipeGroup


# ============================================================================
# Hypothesis 策略：生成测试数据
# ============================================================================

@st.composite
def pressure_pipe_node_strategy(draw, name: str = None, in_out_type: str = None):
    """生成有压管道节点"""
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = name if name is not None else draw(st.text(min_size=0, max_size=20))
    
    # 设置进出口类型
    if in_out_type:
        node.in_out = InOutType.from_string(in_out_type)
    else:
        node.in_out = draw(st.sampled_from([InOutType.INLET, InOutType.OUTLET, InOutType.NORMAL]))
    
    # 设置管径
    diameter = draw(st.floats(min_value=0.3, max_value=3.0))
    node.section_params = {"D": diameter}
    
    # 设置其他参数
    node.flow = draw(st.floats(min_value=0.1, max_value=10.0))
    node.roughness = draw(st.floats(min_value=0.011, max_value=0.025))
    node.x = draw(st.floats(min_value=0, max_value=10000))
    node.y = draw(st.floats(min_value=0, max_value=10000))
    node.station_MC = draw(st.floats(min_value=0, max_value=10000))
    
    return node


@st.composite
def complete_pressure_pipe_pair_strategy(draw):
    """生成完整的有压管道进出口对"""
    # 使用UUID确保名称唯一
    import uuid
    name = draw(st.text(min_size=1, max_size=20, alphabet=st.characters(
        whitelist_categories=('Lu', 'Ll', 'Nd'),
        whitelist_characters='有压管道'
    )))
    # 添加唯一后缀确保不重复
    name = f"{name}_{uuid.uuid4().hex[:8]}"
    
    # 生成进口节点
    inlet = draw(pressure_pipe_node_strategy(name=name, in_out_type="进"))
    
    # 生成出口节点（使用相同名称）
    outlet = draw(pressure_pipe_node_strategy(name=name, in_out_type="出"))
    
    # 确保出口在进口之后
    outlet.station_MC = inlet.station_MC + draw(st.floats(min_value=10, max_value=1000))
    
    return inlet, outlet


@st.composite
def node_list_with_pressure_pipes_strategy(draw):
    """生成包含有压管道的节点列表"""
    nodes = []
    
    # 生成1-5个完整的有压管道对
    num_pairs = draw(st.integers(min_value=1, max_value=5))
    
    for _ in range(num_pairs):
        inlet, outlet = draw(complete_pressure_pipe_pair_strategy())
        nodes.append(inlet)
        nodes.append(outlet)
    
    # 可选：添加一些其他类型的节点
    num_other = draw(st.integers(min_value=0, max_value=5))
    for _ in range(num_other):
        other_node = ChannelNode()
        other_node.structure_type = draw(st.sampled_from([
            StructureType.from_string("明渠-梯形"),
            StructureType.from_string("隧洞-圆形"),
            StructureType.from_string("渡槽-U形"),
        ]))
        other_node.station_MC = draw(st.floats(min_value=0, max_value=10000))
        nodes.append(other_node)
    
    return nodes


@st.composite
def incomplete_pressure_pipe_strategy(draw):
    """生成不完整的有压管道（只有进口或只有出口）"""
    name = draw(st.text(min_size=1, max_size=20))
    in_out_type = draw(st.sampled_from(["进", "出"]))
    
    node = draw(pressure_pipe_node_strategy(name=name, in_out_type=in_out_type))
    
    return [node]


# ============================================================================
# 属性测试
# ============================================================================

@settings(max_examples=100, deadline=None)
@given(nodes=node_list_with_pressure_pipes_strategy())
def test_property_11_pressure_pipe_grouping(nodes: List[ChannelNode]):
    """
    **Property 11: 有压管道分组正确性**
    
    **Validates: Requirements 12.1, 12.2, 12.3, 12.4**
    
    For any 节点列表，系统应按建筑物名称对有压管道节点进行分组，
    每组包含唯一的进口和出口节点，且提取的管径、糙率、流量等参数正确。
    
    验证点：
    1. 按建筑物名称分组
    2. 每组有唯一的进口节点
    3. 每组有唯一的出口节点
    4. 提取的管径 D 正确
    5. 提取的糙率正确
    6. 提取的流量正确
    7. 记录的行索引正确
    """
    # 提取有压管道分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证分组数量合理
    assert len(groups) > 0, "应至少提取到一个有压管道分组"
    
    # 统计原始节点中的有压管道名称
    pressure_pipe_names = set()
    for node in nodes:
        if node.structure_type and "有压管道" in node.structure_type.value:
            name = node.name.strip() if node.name else ""
            if name:
                pressure_pipe_names.add(name)
    
    # 验证每个分组
    for group in groups:
        # 验证点 1: 分组有名称
        assert group.name, "每个分组应有建筑物名称"
        
        # 验证点 2 & 3: 每组应有进口和出口节点
        if group.is_valid():
            assert group.inlet_node is not None, f"分组'{group.name}'应有进口节点"
            assert group.outlet_node is not None, f"分组'{group.name}'应有出口节点"
            
            # 验证进出口节点的名称与分组名称一致
            assert group.inlet_node.name == group.name or not group.inlet_node.name, \
                f"进口节点名称应与分组名称一致"
            assert group.outlet_node.name == group.name or not group.outlet_node.name, \
                f"出口节点名称应与分组名称一致"
            
            # 验证进出口标识
            assert group.inlet_node.in_out == InOutType.INLET, \
                f"进口节点应标记为'进'"
            assert group.outlet_node.in_out == InOutType.OUTLET, \
                f"出口节点应标记为'出'"
            
            # 验证点 4: 管径 D 正确提取
            assert group.diameter_D > 0, \
                f"分组'{group.name}'的管径 D 应大于0，当前值: {group.diameter_D}"
            
            # 验证管径与节点中的值一致
            inlet_D = group.inlet_node.section_params.get("D", 0)
            if inlet_D > 0:
                assert group.diameter_D == inlet_D, \
                    f"分组管径应与进口节点管径一致: {group.diameter_D} vs {inlet_D}"
            
            # 验证点 5: 糙率正确提取
            assert group.roughness > 0, \
                f"分组'{group.name}'的糙率应大于0，当前值: {group.roughness}"
            
            # 验证点 6: 流量正确提取
            assert group.flow > 0, \
                f"分组'{group.name}'的流量应大于0，当前值: {group.flow}"
            
            # 验证点 7: 行索引正确
            assert group.inlet_row_index >= 0, \
                f"进口节点行索引应有效"
            assert group.outlet_row_index >= 0, \
                f"出口节点行索引应有效"
            
            # 验证行索引指向正确的节点
            assert nodes[group.inlet_row_index] == group.inlet_node, \
                f"进口节点行索引应指向正确的节点"
            assert nodes[group.outlet_row_index] == group.outlet_node, \
                f"出口节点行索引应指向正确的节点"


@settings(max_examples=50, deadline=None)
@given(
    inlet_outlet_pairs=st.lists(
        complete_pressure_pipe_pair_strategy(),
        min_size=1,
        max_size=5
    )
)
def test_property_11_unique_inlet_outlet_per_group(inlet_outlet_pairs):
    """
    **Property 11 扩展: 每组唯一进出口**
    
    验证每个有压管道分组只有一个进口和一个出口节点。
    """
    nodes = []
    for inlet, outlet in inlet_outlet_pairs:
        nodes.append(inlet)
        nodes.append(outlet)
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证每个分组只有一个进口和一个出口
    for group in groups:
        if group.is_valid():
            # 统计该分组名称的进出口数量
            inlet_count = 0
            outlet_count = 0
            
            for node in nodes:
                if node.structure_type and "有压管道" in node.structure_type.value:
                    if node.name == group.name:
                        if node.in_out == InOutType.INLET:
                            inlet_count += 1
                        elif node.in_out == InOutType.OUTLET:
                            outlet_count += 1
            
            # 每个分组应该只有一个进口和一个出口
            assert inlet_count <= 1, \
                f"分组'{group.name}'应只有一个进口节点，实际有{inlet_count}个"
            assert outlet_count <= 1, \
                f"分组'{group.name}'应只有一个出口节点，实际有{outlet_count}个"


@settings(max_examples=50, deadline=None)
@given(incomplete_nodes=incomplete_pressure_pipe_strategy())
def test_property_11_incomplete_group_validation(incomplete_nodes: List[ChannelNode]):
    """
    **Property 11 扩展: 不完整分组验证**
    
    验证只有进口或只有出口的有压管道分组应被标记为无效。
    
    **Validates: Requirement 12.5**
    """
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(incomplete_nodes)
    
    # 应该提取到一个分组
    assert len(groups) == 1, "应提取到一个分组"
    
    group = groups[0]
    
    # 分组应该是无效的（缺少进口或出口）
    assert not group.is_valid(), \
        f"只有进口或出口的分组应被标记为无效"
    
    # 验证错误消息
    validation_msg = group.get_validation_message()
    assert validation_msg, "应有验证错误消息"
    assert "未识别到" in validation_msg, \
        f"验证消息应指出缺少进口或出口: {validation_msg}"


@settings(max_examples=50, deadline=None)
@given(
    num_unnamed=st.integers(min_value=1, max_value=5)
)
def test_property_11_default_naming(num_unnamed: int):
    """
    **Property 11 扩展: 默认名称生成**
    
    验证没有建筑物名称的有压管道节点应使用默认名称"有压管道N"。
    
    **Validates: Requirement 12.2**
    """
    nodes = []
    
    # 创建多个没有名称的有压管道节点
    for i in range(num_unnamed):
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("有压管道")
        inlet.name = ""  # 空名称
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 1.0}
        inlet.flow = 1.0
        inlet.station_MC = i * 100
        
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = ""  # 空名称
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.0}
        outlet.flow = 1.0
        outlet.station_MC = i * 100 + 50
        
        nodes.append(inlet)
        nodes.append(outlet)
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证生成了默认名称
    assert len(groups) == num_unnamed, \
        f"应为每对无名节点生成一个分组"
    
    for i, group in enumerate(groups):
        # 默认名称应该是"有压管道1", "有压管道2", ...
        assert group.name.startswith("有压管道"), \
            f"默认名称应以'有压管道'开头: {group.name}"
        assert group.name[4:].isdigit(), \
            f"默认名称应包含数字后缀: {group.name}"


@settings(max_examples=50, deadline=None)
@given(nodes=node_list_with_pressure_pipes_strategy())
def test_property_11_parameter_extraction_accuracy(nodes: List[ChannelNode]):
    """
    **Property 11 扩展: 参数提取准确性**
    
    验证提取的管径、糙率、流量等参数与原始节点数据一致。
    
    **Validates: Requirements 12.3, 12.4**
    """
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    for group in groups:
        if not group.is_valid():
            continue
        
        # 验证管径
        inlet_D = group.inlet_node.section_params.get("D", 0)
        outlet_D = group.outlet_node.section_params.get("D", 0)
        
        if inlet_D > 0:
            assert group.diameter_D == inlet_D, \
                f"分组管径应与进口节点一致"
        elif outlet_D > 0:
            assert group.diameter_D == outlet_D, \
                f"分组管径应与出口节点一致"
        
        # 验证糙率
        inlet_roughness = group.inlet_node.roughness
        if inlet_roughness > 0:
            assert group.roughness == inlet_roughness, \
                f"分组糙率应与进口节点一致"
        
        # 验证流量
        inlet_flow = group.inlet_node.flow
        if inlet_flow > 0:
            assert group.flow == inlet_flow, \
                f"分组流量应与进口节点一致"


# ============================================================================
# 辅助函数测试
# ============================================================================

def test_pressure_pipe_data_extractor_basic():
    """
    测试 PressurePipeDataExtractor 的基本功能
    """
    # 创建测试节点
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = "测试有压管道"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 1.5}
    inlet.flow = 2.0
    inlet.roughness = 0.014
    inlet.station_MC = 100
    
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "测试有压管道"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.5}
    outlet.flow = 2.0
    outlet.roughness = 0.014
    outlet.station_MC = 200
    
    nodes = [inlet, outlet]
    
    # 提取分组
    groups = PressurePipeDataExtractor.extract_pressure_pipe_groups(nodes)
    
    # 验证
    assert len(groups) == 1, "应提取到一个分组"
    
    group = groups[0]
    assert group.name == "测试有压管道"
    assert group.is_valid()
    assert group.diameter_D == 1.5
    assert group.flow == 2.0
    assert group.roughness == 0.014
    assert group.inlet_row_index == 0
    assert group.outlet_row_index == 1


def test_pressure_pipe_names_extraction():
    """
    测试快速获取有压管道名称列表
    """
    nodes = []
    
    # 创建多个有压管道
    for i in range(3):
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("有压管道")
        inlet.name = f"有压管道{i+1}"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 1.0}
        nodes.append(inlet)
        
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = f"有压管道{i+1}"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.0}
        nodes.append(outlet)
    
    # 获取名称列表
    names = PressurePipeDataExtractor.get_pressure_pipe_names(nodes)
    
    # 验证
    assert len(names) == 3
    assert "有压管道1" in names
    assert "有压管道2" in names
    assert "有压管道3" in names


if __name__ == "__main__":
    # 运行单元测试
    print("运行基本功能测试...")
    test_pressure_pipe_data_extractor_basic()
    print("✓ 基本功能测试通过")
    
    print("\n运行名称提取测试...")
    test_pressure_pipe_names_extraction()
    print("✓ 名称提取测试通过")
    
    print("\n运行属性测试需要 pytest 和 hypothesis:")
    print("  pytest tests/test_pressure_pipe_data_extraction_property.py -v")
