# -*- coding: utf-8 -*-
"""
Task 14.1 属性测试：外部水头损失累加

**Property 12: 外部水头损失累加**

*For any* 有压管道出口节点，如果其 `external_head_loss` 字段有值，
该值应被累加到总水头损失计算中。

**Validates: Requirements 10.4, 10.5**
"""

import sys
import os
from hypothesis import given, strategies as st, settings

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.hydraulic_calc import HydraulicCalculator


@st.composite
def pressure_pipe_outlet_with_external_loss(draw):
    """
    生成有压管道出口节点，带有 external_head_loss
    """
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = draw(st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('L',))))
    node.in_out = InOutType.OUTLET
    node.section_params = {"D": draw(st.floats(min_value=0.5, max_value=3.0))}
    node.station_MC = draw(st.floats(min_value=0, max_value=10000))
    node.velocity = draw(st.floats(min_value=0.1, max_value=5.0))
    node.water_depth = draw(st.floats(min_value=0.1, max_value=3.0))
    node.flow_section = "渠道1"
    
    # 设置外部水头损失
    node.external_head_loss = draw(st.floats(min_value=0.1, max_value=10.0))
    
    return node


@st.composite
def regular_node_generator(draw):
    """
    生成常规节点（明渠、隧洞等）
    """
    structure_types = [
        "明渠-梯形", "明渠-矩形", "隧洞-圆形", "渡槽-U形"
    ]
    
    node = ChannelNode()
    node.structure_type = StructureType.from_string(draw(st.sampled_from(structure_types)))
    node.flow_section = "渠道1"
    node.station_MC = draw(st.floats(min_value=0, max_value=10000))
    node.velocity = draw(st.floats(min_value=0.1, max_value=5.0))
    node.water_depth = draw(st.floats(min_value=0.1, max_value=3.0))
    node.roughness = draw(st.floats(min_value=0.01, max_value=0.05))
    
    # 设置断面参数
    if "梯形" in node.structure_type.value:
        node.section_params = {
            "b": draw(st.floats(min_value=1.0, max_value=5.0)),
            "m": draw(st.floats(min_value=0.5, max_value=2.0)),
            "h": node.water_depth
        }
    elif "矩形" in node.structure_type.value:
        node.section_params = {
            "b": draw(st.floats(min_value=1.0, max_value=5.0)),
            "h": node.water_depth
        }
    elif "圆形" in node.structure_type.value:
        D = draw(st.floats(min_value=1.0, max_value=3.0))
        node.section_params = {"D": D}
        # 确保水深不超过直径
        node.water_depth = min(node.water_depth, D * 0.9)
    elif "U形" in node.structure_type.value:
        node.section_params = {
            "R_circle": draw(st.floats(min_value=0.5, max_value=2.0)),
            "theta_deg": draw(st.floats(min_value=60, max_value=120))
        }
    
    return node


@given(
    outlet_node=pressure_pipe_outlet_with_external_loss(),
    next_node=regular_node_generator(),
    start_water_level=st.floats(min_value=100, max_value=200)
)
@settings(max_examples=100, deadline=None)
def test_property_12_external_head_loss_accumulation(outlet_node, next_node, start_water_level):
    """
    **Property 12: 外部水头损失累加**
    
    *For any* 有压管道出口节点，如果其 `external_head_loss` 字段有值，
    该值应被累加到总水头损失计算中。
    
    **Validates: Requirements 10.4, 10.5**
    """
    # 创建一个起始节点（明渠）
    start_node = ChannelNode()
    start_node.structure_type = StructureType.from_string("明渠-梯形")
    start_node.flow_section = "渠道1"
    start_node.section_params = {"b": 2.0, "m": 1.5, "h": 1.5}
    start_node.station_MC = 50.0
    start_node.velocity = 1.5
    start_node.water_depth = 1.5
    start_node.roughness = 0.025
    
    # 确保节点顺序正确：起始节点 -> 有压管道出口 -> 下游节点
    outlet_node.station_MC = 100.0
    next_node.station_MC = 150.0
    
    # 创建节点列表
    nodes = [start_node, outlet_node, next_node]
    
    # 创建水力计算器
    settings = ProjectSettings()
    settings.start_water_level = start_water_level
    calc = HydraulicCalculator(settings)
    
    # 填充断面参数
    for node in nodes:
        if not node.is_transition:
            calc.fill_section_params(node)
    
    # 执行水面线计算
    calc.calculate_water_profile(nodes, method="forward")
    
    # 验证点 1: 有压管道出口节点的 external_head_loss 应该被包含在 head_loss_total 中
    external_loss = outlet_node.external_head_loss or 0.0
    
    # 计算预期的总损失（不含 external_head_loss）
    expected_loss_without_external = (
        (outlet_node.head_loss_friction or 0.0) +
        (outlet_node.head_loss_local or 0.0) +
        (outlet_node.head_loss_bend or 0.0) +
        (getattr(outlet_node, 'head_loss_reserve', 0.0) or 0.0) +
        (getattr(outlet_node, 'head_loss_gate', 0.0) or 0.0) +
        (getattr(outlet_node, 'head_loss_siphon', 0.0) or 0.0)
    )
    
    # 实际总损失应该包含 external_head_loss
    expected_total_loss = expected_loss_without_external + external_loss
    
    assert abs(outlet_node.head_loss_total - expected_total_loss) < 0.01, \
        f"有压管道出口节点的总水头损失应包含 external_head_loss。" \
        f"预期: {expected_total_loss:.3f}, 实际: {outlet_node.head_loss_total:.3f}, " \
        f"external_head_loss: {external_loss:.3f}"
    
    # 验证点 2: 下游节点的水位应该考虑上游节点的 external_head_loss
    # next_node 的总损失也应该正确计算
    next_external_loss = getattr(next_node, 'external_head_loss', None) or 0.0
    next_expected_loss_without_external = (
        (next_node.head_loss_friction or 0.0) +
        (next_node.head_loss_local or 0.0) +
        (next_node.head_loss_bend or 0.0) +
        (getattr(next_node, 'head_loss_reserve', 0.0) or 0.0) +
        (getattr(next_node, 'head_loss_gate', 0.0) or 0.0) +
        (getattr(next_node, 'head_loss_siphon', 0.0) or 0.0)
    )
    next_expected_total_loss = next_expected_loss_without_external + next_external_loss
    
    assert abs(next_node.head_loss_total - next_expected_total_loss) < 0.01, \
        f"下游节点的总水头损失计算也应正确。" \
        f"预期: {next_expected_total_loss:.3f}, 实际: {next_node.head_loss_total:.3f}"


@given(
    external_loss=st.floats(min_value=0.1, max_value=10.0),
    start_water_level=st.floats(min_value=100, max_value=200)
)
@settings(max_examples=100, deadline=None)
def test_property_12_external_loss_included_in_total(external_loss, start_water_level):
    """
    **Property 12 扩展: 外部水头损失必须包含在总损失中**
    
    验证 external_head_loss 被正确累加到 head_loss_total
    
    **Validates: Requirements 10.4, 10.5**
    """
    # 创建起始明渠节点
    start_channel = ChannelNode()
    start_channel.structure_type = StructureType.from_string("明渠-梯形")
    start_channel.flow_section = "渠道1"
    start_channel.section_params = {"b": 2.0, "m": 1.5, "h": 1.5}
    start_channel.station_MC = 50.0
    start_channel.velocity = 1.5
    start_channel.water_depth = 1.5
    start_channel.roughness = 0.025
    
    # 创建有压管道出口节点
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "有压管道1"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.5}
    outlet.station_MC = 100.0
    outlet.velocity = 2.0
    outlet.water_depth = 1.5
    outlet.flow_section = "渠道1"
    outlet.external_head_loss = external_loss
    
    # 创建下游明渠节点
    channel = ChannelNode()
    channel.structure_type = StructureType.from_string("明渠-梯形")
    channel.flow_section = "渠道1"
    channel.section_params = {"b": 2.0, "m": 1.5, "h": 1.5}
    channel.station_MC = 150.0
    channel.velocity = 1.5
    channel.water_depth = 1.5
    channel.roughness = 0.025
    
    nodes = [start_channel, outlet, channel]
    
    # 创建水力计算器
    settings = ProjectSettings()
    settings.start_water_level = start_water_level
    calc = HydraulicCalculator(settings)
    
    # 填充断面参数
    for node in nodes:
        calc.fill_section_params(node)
    
    # 执行水面线计算
    calc.calculate_water_profile(nodes, method="forward")
    
    # 验证: head_loss_total 必须包含 external_head_loss
    assert outlet.head_loss_total >= external_loss, \
        f"总水头损失 ({outlet.head_loss_total:.3f}) 必须至少包含 external_head_loss ({external_loss:.3f})"
    
    # 更严格的验证: 计算其他所有损失之和
    other_losses = (
        (outlet.head_loss_friction or 0.0) +
        (outlet.head_loss_local or 0.0) +
        (outlet.head_loss_bend or 0.0) +
        (getattr(outlet, 'head_loss_reserve', 0.0) or 0.0) +
        (getattr(outlet, 'head_loss_gate', 0.0) or 0.0) +
        (getattr(outlet, 'head_loss_siphon', 0.0) or 0.0)
    )
    
    expected_total = other_losses + external_loss
    
    assert abs(outlet.head_loss_total - expected_total) < 0.01, \
        f"总水头损失应该等于所有损失之和。" \
        f"预期: {expected_total:.3f} (其他损失: {other_losses:.3f} + external: {external_loss:.3f}), " \
        f"实际: {outlet.head_loss_total:.3f}"


if __name__ == "__main__":
    # 运行测试
    test_property_12_external_head_loss_accumulation()
    print("✓ test_property_12_external_head_loss_accumulation")
    
    test_property_12_external_loss_included_in_total()
    print("✓ test_property_12_external_loss_included_in_total")
    
    print("\n所有属性测试通过！")
