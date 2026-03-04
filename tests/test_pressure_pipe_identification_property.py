# -*- coding: utf-8 -*-
"""
有压管道节点识别 - 属性测试

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**

Property 1: 有压管道节点识别
For any 节点列表，所有结构形式包含"有压管道"的节点应被正确识别，
并设置 is_pressure_pipe=True，同时提取管径 D、进出口标识和建筑物名称。
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from hypothesis import given, strategies as st, settings
from hypothesis import assume
from typing import List, Dict, Any

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.calculator import WaterProfileCalculator


# ============================================================================
# Hypothesis 策略：生成测试数据
# ============================================================================

@st.composite
def structure_type_strategy(draw):
    """生成结构形式枚举"""
    structure_types = [
        "明渠-梯形", "明渠-矩形", "明渠-圆形", "明渠-U形",
        "隧洞-圆形", "隧洞-圆拱直墙型", "隧洞-马蹄形Ⅰ型", "隧洞-马蹄形Ⅱ型",
        "渡槽-U形", "渡槽-矩形",
        "矩形暗涵", "倒虹吸", "有压管道",
        "分水闸", "节制闸", "泄水闸"
    ]
    type_str = draw(st.sampled_from(structure_types))
    return StructureType.from_string(type_str)


@st.composite
def in_out_type_strategy(draw):
    """生成进出口标识"""
    in_out_types = ["进", "出", ""]
    in_out_str = draw(st.sampled_from(in_out_types))
    return InOutType.from_string(in_out_str)


@st.composite
def section_params_strategy(draw, structure_type_value: str):
    """根据结构类型生成断面参数"""
    params = {}
    
    if "有压管道" in structure_type_value:
        # 有压管道必须有管径 D
        params["D"] = draw(st.floats(min_value=0.3, max_value=3.0))
    elif "倒虹吸" in structure_type_value:
        params["D"] = draw(st.floats(min_value=0.3, max_value=3.0))
    elif "隧洞" in structure_type_value or "渡槽" in structure_type_value:
        # 隧洞/渡槽可能有底宽或直径
        if draw(st.booleans()):
            params["B"] = draw(st.floats(min_value=0.5, max_value=5.0))
        else:
            params["D"] = draw(st.floats(min_value=0.5, max_value=5.0))
    elif "明渠" in structure_type_value:
        params["B"] = draw(st.floats(min_value=0.5, max_value=10.0))
        if "梯形" in structure_type_value:
            params["m"] = draw(st.floats(min_value=0.5, max_value=3.0))
    
    return params


@st.composite
def channel_node_strategy(draw):
    """生成随机渠道节点"""
    structure_type = draw(structure_type_strategy())
    structure_type_value = structure_type.value if structure_type else ""
    
    node = ChannelNode()
    node.structure_type = structure_type
    node.name = draw(st.text(min_size=0, max_size=20, alphabet=st.characters(
        whitelist_categories=('Lu', 'Ll', 'Nd'), 
        whitelist_characters='有压管道倒虹吸隧洞渡槽明渠'
    )))
    node.in_out = draw(in_out_type_strategy())
    node.x = draw(st.floats(min_value=0, max_value=10000))
    node.y = draw(st.floats(min_value=0, max_value=10000))
    node.station_MC = draw(st.floats(min_value=0, max_value=10000))
    node.flow = draw(st.floats(min_value=0.1, max_value=10.0))
    node.roughness = draw(st.floats(min_value=0.011, max_value=0.025))
    node.section_params = draw(section_params_strategy(structure_type_value))
    
    return node


@st.composite
def node_list_strategy(draw):
    """生成节点列表，确保至少包含一些有压管道节点"""
    size = draw(st.integers(min_value=1, max_value=20))
    nodes = []
    
    # 确保至少有一个有压管道节点（用于测试）
    has_pressure_pipe = False
    
    for _ in range(size):
        node = draw(channel_node_strategy())
        nodes.append(node)
        
        if node.structure_type and "有压管道" in node.structure_type.value:
            has_pressure_pipe = True
    
    # 如果没有有压管道节点，强制添加一个
    if not has_pressure_pipe and draw(st.booleans()):
        pressure_pipe_node = ChannelNode()
        pressure_pipe_node.structure_type = StructureType.from_string("有压管道")
        pressure_pipe_node.name = draw(st.text(min_size=1, max_size=10))
        pressure_pipe_node.in_out = draw(in_out_type_strategy())
        pressure_pipe_node.section_params = {"D": draw(st.floats(min_value=0.5, max_value=2.0))}
        pressure_pipe_node.flow = draw(st.floats(min_value=0.1, max_value=5.0))
        nodes.insert(draw(st.integers(min_value=0, max_value=len(nodes))), pressure_pipe_node)
    
    return nodes


# ============================================================================
# 属性测试
# ============================================================================

@settings(max_examples=100, deadline=None)
@given(nodes=node_list_strategy())
def test_property_1_pressure_pipe_identification(nodes: List[ChannelNode]):
    """
    **Property 1: 有压管道节点识别**
    
    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**
    
    For any 节点列表，所有结构形式包含"有压管道"的节点应被正确识别，
    并设置 is_pressure_pipe=True，同时提取管径 D、进出口标识和建筑物名称。
    
    验证点：
    1. 结构形式包含"有压管道"的节点 → is_pressure_pipe=True
    2. 其他节点 → is_pressure_pipe=False
    3. 有压管道节点的管径 D 应从 section_params 中提取
    4. 有压管道节点的进出口标识应被正确设置
    5. 有压管道节点的建筑物名称应被保留
    6. is_pressurized_flow_structure() 函数应正确识别倒虹吸和有压管道
    """
    # 创建计算器实例
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 预处理节点（这会设置 is_pressure_pipe 标记）
    calculator.preprocess_nodes(nodes)
    
    # 验证每个节点
    for node in nodes:
        structure_type_value = node.structure_type.value if node.structure_type else ""
        
        # 验证点 1 & 2: 有压管道节点应被正确识别
        if "有压管道" in structure_type_value:
            assert node.is_pressure_pipe == True, \
                f"节点结构形式为'{structure_type_value}'，应设置 is_pressure_pipe=True"
            
            # 验证点 3: 管径 D 应存在于 section_params 中
            if node.section_params:
                diameter = node.section_params.get("D", 0)
                assert diameter > 0, \
                    f"有压管道节点应有有效的管径 D，当前值: {diameter}"
            
            # 验证点 4: 进出口标识应被设置（如果节点有名称）
            if node.name:
                # 进出口标识应该是 INLET, OUTLET 或 NORMAL 之一
                assert node.in_out in [InOutType.INLET, InOutType.OUTLET, InOutType.NORMAL], \
                    f"有压管道节点的进出口标识无效: {node.in_out}"
            
            # 验证点 5: 建筑物名称应被保留
            # （名称在预处理中不应被修改）
            assert isinstance(node.name, str), \
                f"有压管道节点的建筑物名称应为字符串类型"
        
        else:
            # 非有压管道节点不应设置 is_pressure_pipe
            assert node.is_pressure_pipe == False, \
                f"节点结构形式为'{structure_type_value}'，不应设置 is_pressure_pipe=True"
        
        # 验证点 6: is_pressurized_flow_structure() 函数应正确识别
        is_pressurized = calculator.is_pressurized_flow_structure(node)
        is_pressure_pipe = calculator.is_pressure_pipe(node)
        
        if "有压管道" in structure_type_value:
            assert is_pressurized == True, \
                f"is_pressurized_flow_structure() 应识别有压管道节点"
            assert is_pressure_pipe == True, \
                f"is_pressure_pipe() 应识别有压管道节点"
        elif structure_type_value == "倒虹吸":
            assert is_pressurized == True, \
                f"is_pressurized_flow_structure() 应识别倒虹吸节点"
            assert is_pressure_pipe == False, \
                f"is_pressure_pipe() 不应将倒虹吸识别为有压管道"
        else:
            assert is_pressurized == False, \
                f"is_pressurized_flow_structure() 不应识别非有压流节点"
            assert is_pressure_pipe == False, \
                f"is_pressure_pipe() 不应识别非有压管道节点"


@settings(max_examples=100, deadline=None)
@given(
    nodes=node_list_strategy(),
    pressure_pipe_name=st.text(min_size=1, max_size=20)
)
def test_property_1_building_name_extraction(nodes: List[ChannelNode], pressure_pipe_name: str):
    """
    **Property 1 扩展: 建筑物名称提取**
    
    验证有压管道节点的建筑物名称能够被正确提取和保留，用于后续分组。
    """
    # 创建一个有压管道节点
    pressure_pipe_node = ChannelNode()
    pressure_pipe_node.structure_type = StructureType.from_string("有压管道")
    pressure_pipe_node.name = pressure_pipe_name
    pressure_pipe_node.in_out = InOutType.INLET
    pressure_pipe_node.section_params = {"D": 1.0}
    pressure_pipe_node.flow = 1.0
    
    # 插入到节点列表中
    test_nodes = nodes + [pressure_pipe_node]
    
    # 创建计算器并预处理
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    calculator.preprocess_nodes(test_nodes)
    
    # 验证有压管道节点的名称被保留
    processed_node = test_nodes[-1]
    assert processed_node.name == pressure_pipe_name, \
        f"有压管道节点的建筑物名称应被保留: 期望'{pressure_pipe_name}'，实际'{processed_node.name}'"
    assert processed_node.is_pressure_pipe == True, \
        "有压管道节点应被正确标记"


@settings(max_examples=50, deadline=None)
@given(
    diameter=st.floats(min_value=0.3, max_value=3.0),
    name=st.text(min_size=0, max_size=20),
    in_out=st.sampled_from(["进", "出", ""])
)
def test_property_1_diameter_extraction(diameter: float, name: str, in_out: str):
    """
    **Property 1 扩展: 管径提取**
    
    验证有压管道节点的管径 D 能够从 section_params 中正确提取。
    """
    # 创建有压管道节点
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = name
    node.in_out = InOutType.from_string(in_out)
    node.section_params = {"D": diameter}
    node.flow = 1.0
    
    # 创建计算器并预处理
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    calculator.preprocess_nodes([node])
    
    # 验证管径被保留
    assert node.section_params.get("D") == diameter, \
        f"有压管道节点的管径 D 应被保留: 期望{diameter}，实际{node.section_params.get('D')}"
    assert node.is_pressure_pipe == True, \
        "有压管道节点应被正确标记"


# ============================================================================
# 辅助函数测试
# ============================================================================

def test_is_pressurized_flow_structure_function():
    """
    测试 is_pressurized_flow_structure() 函数的正确性
    
    该函数应识别倒虹吸和有压管道为有压流建筑物
    """
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 测试有压管道
    pressure_pipe = ChannelNode()
    pressure_pipe.structure_type = StructureType.from_string("有压管道")
    assert calculator.is_pressurized_flow_structure(pressure_pipe) == True
    assert calculator.is_pressure_pipe(pressure_pipe) == True
    
    # 测试倒虹吸
    siphon = ChannelNode()
    siphon.structure_type = StructureType.from_string("倒虹吸")
    assert calculator.is_pressurized_flow_structure(siphon) == True
    assert calculator.is_pressure_pipe(siphon) == False
    
    # 测试明渠
    channel = ChannelNode()
    channel.structure_type = StructureType.from_string("明渠-梯形")
    assert calculator.is_pressurized_flow_structure(channel) == False
    assert calculator.is_pressure_pipe(channel) == False
    
    # 测试隧洞
    tunnel = ChannelNode()
    tunnel.structure_type = StructureType.from_string("隧洞-圆形")
    assert calculator.is_pressurized_flow_structure(tunnel) == False
    assert calculator.is_pressure_pipe(tunnel) == False
    
    # 测试空节点
    empty = ChannelNode()
    assert calculator.is_pressurized_flow_structure(empty) == False
    assert calculator.is_pressure_pipe(empty) == False


if __name__ == "__main__":
    # 运行单元测试
    print("运行辅助函数测试...")
    test_is_pressurized_flow_structure_function()
    print("✓ 辅助函数测试通过")
    
    print("\n运行属性测试需要 pytest 和 hypothesis:")
    print("  pytest tests/test_pressure_pipe_identification_property.py -v")
