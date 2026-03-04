# -*- coding: utf-8 -*-
"""
有压管道数据验证 - 属性测试

**Validates: Requirements 17.1, 17.2, 17.3, 17.4, 18.1, 18.2, 18.3, 18.4, 18.5**

Property 13: 数据验证拒绝无效输入
For any 有压管道节点，如果其管径 D ≤ 0、糙率 ≤ 0、流量 ≤ 0，
或进口里程 > 出口里程，系统应报告验证错误。

Property 17: 错误报告
For any 有压管道节点，如果缺少管径 D、进出口标识，或有压管道组
只有进口没有出口（或反之），系统应显示清晰的错误提示并指出具体位置。
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from hypothesis import given, strategies as st, settings, assume
from typing import List, Dict, Any

from models.data_models import ChannelNode
from models.enums import StructureType, InOutType
from core.pressure_pipe_data import PressurePipeDataExtractor, PressurePipeGroup


# ============================================================================
# Hypothesis 策略：生成测试数据
# ============================================================================

@st.composite
def invalid_diameter_node_strategy(draw):
    """生成管径无效的有压管道节点"""
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = draw(st.text(min_size=1, max_size=20))
    node.in_out = draw(st.sampled_from([InOutType.INLET, InOutType.OUTLET]))
    
    # 生成无效管径 (≤ 0)
    invalid_D = draw(st.floats(max_value=0.0, allow_nan=False, allow_infinity=False))
    node.section_params = {"D": invalid_D}
    
    node.flow = draw(st.floats(min_value=0.1, max_value=10.0))
    node.roughness = draw(st.floats(min_value=0.011, max_value=0.025))
    node.station_MC = draw(st.floats(min_value=0, max_value=10000))
    
    return node


@st.composite
def invalid_roughness_node_strategy(draw):
    """生成糙率无效的有压管道节点"""
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = draw(st.text(min_size=1, max_size=20))
    node.in_out = draw(st.sampled_from([InOutType.INLET, InOutType.OUTLET]))
    
    node.section_params = {"D": draw(st.floats(min_value=0.3, max_value=3.0))}
    node.flow = draw(st.floats(min_value=0.1, max_value=10.0))
    
    # 生成无效糙率 (≤ 0)
    invalid_roughness = draw(st.floats(max_value=0.0, allow_nan=False, allow_infinity=False))
    node.roughness = invalid_roughness
    
    node.station_MC = draw(st.floats(min_value=0, max_value=10000))
    
    return node


@st.composite
def invalid_flow_node_strategy(draw):
    """生成流量无效的有压管道节点"""
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = draw(st.text(min_size=1, max_size=20))
    node.in_out = draw(st.sampled_from([InOutType.INLET, InOutType.OUTLET]))
    
    node.section_params = {"D": draw(st.floats(min_value=0.3, max_value=3.0))}
    
    # 生成无效流量 (≤ 0)
    invalid_flow = draw(st.floats(max_value=0.0, allow_nan=False, allow_infinity=False))
    node.flow = invalid_flow
    
    node.roughness = draw(st.floats(min_value=0.011, max_value=0.025))
    node.station_MC = draw(st.floats(min_value=0, max_value=10000))
    
    return node


@st.composite
def missing_diameter_node_strategy(draw):
    """生成缺少管径的有压管道节点"""
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = draw(st.text(min_size=1, max_size=20))
    node.in_out = draw(st.sampled_from([InOutType.INLET, InOutType.OUTLET]))
    
    # 缺少管径 D
    node.section_params = {}  # 或者 None
    
    node.flow = draw(st.floats(min_value=0.1, max_value=10.0))
    node.roughness = draw(st.floats(min_value=0.011, max_value=0.025))
    node.station_MC = draw(st.floats(min_value=0, max_value=10000))
    
    return node


@st.composite
def missing_in_out_node_strategy(draw):
    """生成缺少进出口标识的有压管道节点"""
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = draw(st.text(min_size=1, max_size=20))
    
    # 缺少进出口标识
    node.in_out = InOutType.NORMAL  # 或者其他非进出口标识
    
    node.section_params = {"D": draw(st.floats(min_value=0.3, max_value=3.0))}
    node.flow = draw(st.floats(min_value=0.1, max_value=10.0))
    node.roughness = draw(st.floats(min_value=0.011, max_value=0.025))
    node.station_MC = draw(st.floats(min_value=0, max_value=10000))
    
    return node


@st.composite
def invalid_station_order_pair_strategy(draw):
    """生成进口里程大于出口里程的有压管道节点对"""
    name = draw(st.text(min_size=1, max_size=20))
    
    # 生成进口节点
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = name
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": draw(st.floats(min_value=0.3, max_value=3.0))}
    inlet.flow = draw(st.floats(min_value=0.1, max_value=10.0))
    inlet.roughness = draw(st.floats(min_value=0.011, max_value=0.025))
    inlet.station_MC = draw(st.floats(min_value=100, max_value=10000))
    
    # 生成出口节点（里程小于进口）
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = name
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": inlet.section_params["D"]}
    outlet.flow = inlet.flow
    outlet.roughness = inlet.roughness
    # 出口里程小于进口里程
    outlet.station_MC = draw(st.floats(min_value=0, max_value=inlet.station_MC - 1))
    
    return inlet, outlet


# ============================================================================
# 属性测试
# ============================================================================

@settings(max_examples=100, deadline=None)
@given(node=invalid_diameter_node_strategy())
def test_property_13_invalid_diameter_rejection(node: ChannelNode):
    """
    **Property 13: 数据验证拒绝无效输入 - 管径**
    
    **Validates: Requirement 18.1**
    
    For any 有压管道节点，如果其管径 D ≤ 0，系统应报告验证错误。
    
    验证点：
    1. 检测到管径 ≤ 0
    2. 返回验证失败
    3. 错误消息包含管径相关信息
    """
    from core.pressure_pipe_data import validate_pressure_pipe_node
    
    # 执行验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=1)
    
    # 验证应该失败
    assert not is_valid, "管径 ≤ 0 的节点应验证失败"
    
    # 应该有错误消息
    assert len(errors) > 0, "应返回错误消息"
    
    # 错误消息应包含管径相关信息
    error_text = " ".join(errors).lower()
    assert "管径" in error_text or "d" in error_text, \
        f"错误消息应包含管径相关信息: {errors}"


@settings(max_examples=100, deadline=None)
@given(node=invalid_roughness_node_strategy())
def test_property_13_invalid_roughness_rejection(node: ChannelNode):
    """
    **Property 13: 数据验证拒绝无效输入 - 糙率**
    
    **Validates: Requirement 18.2**
    
    For any 有压管道节点，如果其糙率 ≤ 0，系统应报告验证错误。
    
    验证点：
    1. 检测到糙率 ≤ 0
    2. 返回验证失败
    3. 错误消息包含糙率相关信息
    """
    from core.pressure_pipe_data import validate_pressure_pipe_node
    
    # 执行验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=1)
    
    # 验证应该失败
    assert not is_valid, "糙率 ≤ 0 的节点应验证失败"
    
    # 应该有错误消息
    assert len(errors) > 0, "应返回错误消息"
    
    # 错误消息应包含糙率相关信息
    error_text = " ".join(errors).lower()
    assert "糙率" in error_text or "roughness" in error_text, \
        f"错误消息应包含糙率相关信息: {errors}"


@settings(max_examples=100, deadline=None)
@given(node=invalid_flow_node_strategy())
def test_property_13_invalid_flow_rejection(node: ChannelNode):
    """
    **Property 13: 数据验证拒绝无效输入 - 流量**
    
    **Validates: Requirement 18.3**
    
    For any 有压管道节点，如果其流量 ≤ 0，系统应报告验证错误。
    
    验证点：
    1. 检测到流量 ≤ 0
    2. 返回验证失败
    3. 错误消息包含流量相关信息
    """
    from core.pressure_pipe_data import validate_pressure_pipe_node
    
    # 执行验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=1)
    
    # 验证应该失败
    assert not is_valid, "流量 ≤ 0 的节点应验证失败"
    
    # 应该有错误消息
    assert len(errors) > 0, "应返回错误消息"
    
    # 错误消息应包含流量相关信息
    error_text = " ".join(errors).lower()
    assert "流量" in error_text or "flow" in error_text, \
        f"错误消息应包含流量相关信息: {errors}"


@settings(max_examples=100, deadline=None)
@given(inlet_outlet=invalid_station_order_pair_strategy())
def test_property_13_invalid_station_order_rejection(inlet_outlet):
    """
    **Property 13: 数据验证拒绝无效输入 - 里程顺序**
    
    **Validates: Requirement 18.4**
    
    For any 有压管道，如果进口里程 > 出口里程，系统应报告验证错误。
    
    验证点：
    1. 检测到进口里程 > 出口里程
    2. 返回验证失败
    3. 错误消息包含里程顺序相关信息
    """
    from core.pressure_pipe_data import validate_pressure_pipe_group
    
    inlet, outlet = inlet_outlet
    
    # 创建分组
    group = PressurePipeGroup(
        name=inlet.name,
        inlet_node=inlet,
        outlet_node=outlet,
        inlet_row_index=0,
        outlet_row_index=1,
        diameter_D=inlet.section_params.get("D", 0),
        roughness=inlet.roughness,
        flow=inlet.flow
    )
    
    # 执行验证
    is_valid, errors = validate_pressure_pipe_group(group)
    
    # 验证应该失败
    assert not is_valid, "进口里程 > 出口里程的分组应验证失败"
    
    # 应该有错误消息
    assert len(errors) > 0, "应返回错误消息"
    
    # 错误消息应包含里程相关信息
    error_text = " ".join(errors).lower()
    assert "里程" in error_text or "station" in error_text, \
        f"错误消息应包含里程相关信息: {errors}"


@settings(max_examples=100, deadline=None)
@given(node=missing_diameter_node_strategy())
def test_property_17_missing_diameter_error_reporting(node: ChannelNode):
    """
    **Property 17: 错误报告 - 缺少管径**
    
    **Validates: Requirement 17.1**
    
    For any 有压管道节点，如果缺少管径 D，系统应显示错误提示并指出具体行号。
    
    验证点：
    1. 检测到缺少管径
    2. 错误消息包含行号
    3. 错误消息清晰描述问题
    """
    from core.pressure_pipe_data import validate_pressure_pipe_node
    
    row_index = 5  # 测试行号
    
    # 执行验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=row_index)
    
    # 验证应该失败
    assert not is_valid, "缺少管径的节点应验证失败"
    
    # 应该有错误消息
    assert len(errors) > 0, "应返回错误消息"
    
    # 错误消息应包含行号
    error_text = " ".join(errors)
    assert str(row_index) in error_text or "行" in error_text, \
        f"错误消息应包含行号信息: {errors}"
    
    # 错误消息应包含管径相关信息
    assert "管径" in error_text or "D" in error_text, \
        f"错误消息应指出缺少管径: {errors}"


@settings(max_examples=100, deadline=None)
@given(node=missing_in_out_node_strategy())
def test_property_17_missing_in_out_error_reporting(node: ChannelNode):
    """
    **Property 17: 错误报告 - 缺少进出口标识**
    
    **Validates: Requirement 17.2**
    
    For any 有压管道节点，如果缺少进出口标识，系统应显示错误提示并指出具体行号。
    
    验证点：
    1. 检测到缺少进出口标识
    2. 错误消息包含行号
    3. 错误消息清晰描述问题
    """
    from core.pressure_pipe_data import validate_pressure_pipe_node
    
    row_index = 10  # 测试行号
    
    # 执行验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=row_index)
    
    # 验证应该失败
    assert not is_valid, "缺少进出口标识的节点应验证失败"
    
    # 应该有错误消息
    assert len(errors) > 0, "应返回错误消息"
    
    # 错误消息应包含行号
    error_text = " ".join(errors)
    assert str(row_index) in error_text or "行" in error_text, \
        f"错误消息应包含行号信息: {errors}"
    
    # 错误消息应包含进出口相关信息
    assert "进出口" in error_text or "进" in error_text or "出" in error_text, \
        f"错误消息应指出缺少进出口标识: {errors}"


@settings(max_examples=50, deadline=None)
@given(
    name=st.text(min_size=1, max_size=20),
    has_inlet=st.booleans(),
    has_outlet=st.booleans()
)
def test_property_17_incomplete_group_error_reporting(name: str, has_inlet: bool, has_outlet: bool):
    """
    **Property 17: 错误报告 - 不完整分组**
    
    **Validates: Requirements 17.3, 17.4**
    
    For any 有压管道分组，如果只有进口没有出口（或反之），
    系统应显示错误提示并指出建筑物名称。
    
    验证点：
    1. 检测到不完整分组
    2. 错误消息包含建筑物名称
    3. 错误消息指出缺少进口或出口
    """
    # 跳过完整分组的情况
    assume(not (has_inlet and has_outlet))
    assume(has_inlet or has_outlet)  # 至少有一个
    
    from core.pressure_pipe_data import validate_pressure_pipe_group
    
    # 创建不完整分组
    inlet_node = None
    outlet_node = None
    
    if has_inlet:
        inlet_node = ChannelNode()
        inlet_node.structure_type = StructureType.from_string("有压管道")
        inlet_node.name = name
        inlet_node.in_out = InOutType.INLET
        inlet_node.section_params = {"D": 1.0}
        inlet_node.flow = 1.0
        inlet_node.roughness = 0.014
        inlet_node.station_MC = 100
    
    if has_outlet:
        outlet_node = ChannelNode()
        outlet_node.structure_type = StructureType.from_string("有压管道")
        outlet_node.name = name
        outlet_node.in_out = InOutType.OUTLET
        outlet_node.section_params = {"D": 1.0}
        outlet_node.flow = 1.0
        outlet_node.roughness = 0.014
        outlet_node.station_MC = 200
    
    group = PressurePipeGroup(
        name=name,
        inlet_node=inlet_node,
        outlet_node=outlet_node,
        inlet_row_index=0 if has_inlet else -1,
        outlet_row_index=1 if has_outlet else -1,
        diameter_D=1.0,
        roughness=0.014,
        flow=1.0
    )
    
    # 执行验证
    is_valid, errors = validate_pressure_pipe_group(group)
    
    # 验证应该失败
    assert not is_valid, "不完整分组应验证失败"
    
    # 应该有错误消息
    assert len(errors) > 0, "应返回错误消息"
    
    # 错误消息应包含建筑物名称
    error_text = " ".join(errors)
    assert name in error_text or "建筑物" in error_text, \
        f"错误消息应包含建筑物名称: {errors}"
    
    # 错误消息应指出缺少进口或出口
    if not has_inlet:
        assert "进口" in error_text or "inlet" in error_text.lower(), \
            f"错误消息应指出缺少进口: {errors}"
    if not has_outlet:
        assert "出口" in error_text or "outlet" in error_text.lower(), \
            f"错误消息应指出缺少出口: {errors}"


# ============================================================================
# 辅助函数测试
# ============================================================================

def test_validate_pressure_pipe_node_basic():
    """
    测试 validate_pressure_pipe_node 的基本功能
    """
    from core.pressure_pipe_data import validate_pressure_pipe_node
    
    # 创建有效节点
    valid_node = ChannelNode()
    valid_node.structure_type = StructureType.from_string("有压管道")
    valid_node.name = "测试有压管道"
    valid_node.in_out = InOutType.INLET
    valid_node.section_params = {"D": 1.5}
    valid_node.flow = 2.0
    valid_node.roughness = 0.014
    valid_node.station_MC = 100
    
    # 验证应该通过
    is_valid, errors = validate_pressure_pipe_node(valid_node, row_index=1)
    assert is_valid, f"有效节点应通过验证，错误: {errors}"
    assert len(errors) == 0, "有效节点不应有错误消息"
    
    # 创建无效节点（管径 ≤ 0）
    invalid_node = ChannelNode()
    invalid_node.structure_type = StructureType.from_string("有压管道")
    invalid_node.name = "测试有压管道"
    invalid_node.in_out = InOutType.INLET
    invalid_node.section_params = {"D": -1.0}
    invalid_node.flow = 2.0
    invalid_node.roughness = 0.014
    invalid_node.station_MC = 100
    
    # 验证应该失败
    is_valid, errors = validate_pressure_pipe_node(invalid_node, row_index=2)
    assert not is_valid, "无效节点应验证失败"
    assert len(errors) > 0, "无效节点应有错误消息"


def test_validate_pressure_pipe_group_basic():
    """
    测试 validate_pressure_pipe_group 的基本功能
    """
    from core.pressure_pipe_data import validate_pressure_pipe_group
    
    # 创建有效分组
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
    
    valid_group = PressurePipeGroup(
        name="测试有压管道",
        inlet_node=inlet,
        outlet_node=outlet,
        inlet_row_index=0,
        outlet_row_index=1,
        diameter_D=1.5,
        roughness=0.014,
        flow=2.0
    )
    
    # 验证应该通过
    is_valid, errors = validate_pressure_pipe_group(valid_group)
    assert is_valid, f"有效分组应通过验证，错误: {errors}"
    assert len(errors) == 0, "有效分组不应有错误消息"
    
    # 创建无效分组（进口里程 > 出口里程）
    invalid_outlet = ChannelNode()
    invalid_outlet.structure_type = StructureType.from_string("有压管道")
    invalid_outlet.name = "测试有压管道"
    invalid_outlet.in_out = InOutType.OUTLET
    invalid_outlet.section_params = {"D": 1.5}
    invalid_outlet.flow = 2.0
    invalid_outlet.roughness = 0.014
    invalid_outlet.station_MC = 50  # 小于进口里程
    
    invalid_group = PressurePipeGroup(
        name="测试有压管道",
        inlet_node=inlet,
        outlet_node=invalid_outlet,
        inlet_row_index=0,
        outlet_row_index=1,
        diameter_D=1.5,
        roughness=0.014,
        flow=2.0
    )
    
    # 验证应该失败
    is_valid, errors = validate_pressure_pipe_group(invalid_group)
    assert not is_valid, "无效分组应验证失败"
    assert len(errors) > 0, "无效分组应有错误消息"


if __name__ == "__main__":
    # 运行单元测试
    print("运行节点验证基本功能测试...")
    test_validate_pressure_pipe_node_basic()
    print("✓ 节点验证基本功能测试通过")
    
    print("\n运行分组验证基本功能测试...")
    test_validate_pressure_pipe_group_basic()
    print("✓ 分组验证基本功能测试通过")
    
    print("\n运行属性测试需要 pytest 和 hypothesis:")
    print("  pytest tests/test_pressure_pipe_validation_property.py -v")
