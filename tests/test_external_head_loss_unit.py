# -*- coding: utf-8 -*-
"""
Task 14.2 单元测试：外部水头损失累加

验证 external_head_loss 字段被正确累加到总水头损失计算中

Requirements: 10.4, 10.5
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.hydraulic_calc import HydraulicCalculator


def test_external_head_loss_included_in_total():
    """
    测试有 external_head_loss 时正确累加到总损失
    
    场景：有压管道出口节点设置了 external_head_loss
    期望：head_loss_total 包含 external_head_loss
    
    Requirements: 10.4, 10.5
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
    outlet.external_head_loss = 2.5  # 设置外部水头损失
    
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
    settings.start_water_level = 100.0
    calc = HydraulicCalculator(settings)
    
    # 填充断面参数
    for node in nodes:
        calc.fill_section_params(node)
    
    # 执行水面线计算
    calc.calculate_water_profile(nodes, method="forward")
    
    # 验证: head_loss_total 必须包含 external_head_loss
    assert outlet.head_loss_total >= 2.5, \
        f"总水头损失 ({outlet.head_loss_total:.3f}) 必须至少包含 external_head_loss (2.5)"
    
    # 计算其他所有损失之和
    other_losses = (
        (outlet.head_loss_friction or 0.0) +
        (outlet.head_loss_local or 0.0) +
        (outlet.head_loss_bend or 0.0) +
        (getattr(outlet, 'head_loss_reserve', 0.0) or 0.0) +
        (getattr(outlet, 'head_loss_gate', 0.0) or 0.0) +
        (getattr(outlet, 'head_loss_siphon', 0.0) or 0.0)
    )
    
    expected_total = other_losses + 2.5
    
    assert abs(outlet.head_loss_total - expected_total) < 0.01, \
        f"总水头损失应该等于所有损失之和。" \
        f"预期: {expected_total:.3f} (其他损失: {other_losses:.3f} + external: 2.5), " \
        f"实际: {outlet.head_loss_total:.3f}"


def test_no_external_head_loss_not_affected():
    """
    测试无 external_head_loss 时不影响计算
    
    场景：节点没有设置 external_head_loss（None 或 0）
    期望：head_loss_total 正常计算，不包含额外损失
    
    Requirements: 10.4, 10.5
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
    
    # 创建明渠节点（无 external_head_loss）
    channel1 = ChannelNode()
    channel1.structure_type = StructureType.from_string("明渠-梯形")
    channel1.flow_section = "渠道1"
    channel1.section_params = {"b": 2.0, "m": 1.5, "h": 1.5}
    channel1.station_MC = 100.0
    channel1.velocity = 1.5
    channel1.water_depth = 1.5
    channel1.roughness = 0.025
    channel1.external_head_loss = None  # 明确设置为 None
    
    # 创建下游明渠节点
    channel2 = ChannelNode()
    channel2.structure_type = StructureType.from_string("明渠-梯形")
    channel2.flow_section = "渠道1"
    channel2.section_params = {"b": 2.0, "m": 1.5, "h": 1.5}
    channel2.station_MC = 150.0
    channel2.velocity = 1.5
    channel2.water_depth = 1.5
    channel2.roughness = 0.025
    
    nodes = [start_channel, channel1, channel2]
    
    # 创建水力计算器
    settings = ProjectSettings()
    settings.start_water_level = 100.0
    calc = HydraulicCalculator(settings)
    
    # 填充断面参数
    for node in nodes:
        calc.fill_section_params(node)
    
    # 执行水面线计算
    calc.calculate_water_profile(nodes, method="forward")
    
    # 验证: head_loss_total 应该等于其他损失之和（不含 external_head_loss）
    other_losses = (
        (channel1.head_loss_friction or 0.0) +
        (channel1.head_loss_local or 0.0) +
        (channel1.head_loss_bend or 0.0) +
        (getattr(channel1, 'head_loss_reserve', 0.0) or 0.0) +
        (getattr(channel1, 'head_loss_gate', 0.0) or 0.0) +
        (getattr(channel1, 'head_loss_siphon', 0.0) or 0.0)
    )
    
    assert abs(channel1.head_loss_total - other_losses) < 0.01, \
        f"无 external_head_loss 时，总水头损失应该等于其他损失之和。" \
        f"预期: {other_losses:.3f}, 实际: {channel1.head_loss_total:.3f}"


def test_external_head_loss_zero():
    """
    测试 external_head_loss 为 0 时的处理
    
    场景：节点的 external_head_loss 设置为 0
    期望：head_loss_total 正常计算，不增加额外损失
    
    Requirements: 10.4, 10.5
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
    
    # 创建有压管道出口节点（external_head_loss = 0）
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "有压管道1"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.5}
    outlet.station_MC = 100.0
    outlet.velocity = 2.0
    outlet.water_depth = 1.5
    outlet.flow_section = "渠道1"
    outlet.external_head_loss = 0.0  # 设置为 0
    
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
    settings.start_water_level = 100.0
    calc = HydraulicCalculator(settings)
    
    # 填充断面参数
    for node in nodes:
        calc.fill_section_params(node)
    
    # 执行水面线计算
    calc.calculate_water_profile(nodes, method="forward")
    
    # 验证: head_loss_total 应该等于其他损失之和（external_head_loss = 0 不增加损失）
    other_losses = (
        (outlet.head_loss_friction or 0.0) +
        (outlet.head_loss_local or 0.0) +
        (outlet.head_loss_bend or 0.0) +
        (getattr(outlet, 'head_loss_reserve', 0.0) or 0.0) +
        (getattr(outlet, 'head_loss_gate', 0.0) or 0.0) +
        (getattr(outlet, 'head_loss_siphon', 0.0) or 0.0)
    )
    
    assert abs(outlet.head_loss_total - other_losses) < 0.01, \
        f"external_head_loss = 0 时，总水头损失应该等于其他损失之和。" \
        f"预期: {other_losses:.3f}, 实际: {outlet.head_loss_total:.3f}"


def test_multiple_nodes_with_external_loss():
    """
    测试多个节点都有 external_head_loss 的情况
    
    场景：多个有压管道出口节点都设置了 external_head_loss
    期望：每个节点的 head_loss_total 都正确包含各自的 external_head_loss
    
    Requirements: 10.4, 10.5
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
    
    # 创建第一个有压管道出口节点
    outlet1 = ChannelNode()
    outlet1.structure_type = StructureType.from_string("有压管道")
    outlet1.name = "有压管道1"
    outlet1.in_out = InOutType.OUTLET
    outlet1.section_params = {"D": 1.5}
    outlet1.station_MC = 100.0
    outlet1.velocity = 2.0
    outlet1.water_depth = 1.5
    outlet1.flow_section = "渠道1"
    outlet1.external_head_loss = 1.5
    
    # 创建中间明渠节点
    middle_channel = ChannelNode()
    middle_channel.structure_type = StructureType.from_string("明渠-梯形")
    middle_channel.flow_section = "渠道1"
    middle_channel.section_params = {"b": 2.0, "m": 1.5, "h": 1.5}
    middle_channel.station_MC = 150.0
    middle_channel.velocity = 1.5
    middle_channel.water_depth = 1.5
    middle_channel.roughness = 0.025
    
    # 创建第二个有压管道出口节点
    outlet2 = ChannelNode()
    outlet2.structure_type = StructureType.from_string("有压管道")
    outlet2.name = "有压管道2"
    outlet2.in_out = InOutType.OUTLET
    outlet2.section_params = {"D": 1.8}
    outlet2.station_MC = 200.0
    outlet2.velocity = 2.2
    outlet2.water_depth = 1.8
    outlet2.flow_section = "渠道1"
    outlet2.external_head_loss = 2.8
    
    # 创建下游明渠节点
    end_channel = ChannelNode()
    end_channel.structure_type = StructureType.from_string("明渠-梯形")
    end_channel.flow_section = "渠道1"
    end_channel.section_params = {"b": 2.0, "m": 1.5, "h": 1.5}
    end_channel.station_MC = 250.0
    end_channel.velocity = 1.5
    end_channel.water_depth = 1.5
    end_channel.roughness = 0.025
    
    nodes = [start_channel, outlet1, middle_channel, outlet2, end_channel]
    
    # 创建水力计算器
    settings = ProjectSettings()
    settings.start_water_level = 100.0
    calc = HydraulicCalculator(settings)
    
    # 填充断面参数
    for node in nodes:
        calc.fill_section_params(node)
    
    # 执行水面线计算
    calc.calculate_water_profile(nodes, method="forward")
    
    # 验证第一个有压管道出口
    other_losses1 = (
        (outlet1.head_loss_friction or 0.0) +
        (outlet1.head_loss_local or 0.0) +
        (outlet1.head_loss_bend or 0.0) +
        (getattr(outlet1, 'head_loss_reserve', 0.0) or 0.0) +
        (getattr(outlet1, 'head_loss_gate', 0.0) or 0.0) +
        (getattr(outlet1, 'head_loss_siphon', 0.0) or 0.0)
    )
    expected_total1 = other_losses1 + 1.5
    
    assert abs(outlet1.head_loss_total - expected_total1) < 0.01, \
        f"第一个有压管道出口的总水头损失应包含 external_head_loss。" \
        f"预期: {expected_total1:.3f}, 实际: {outlet1.head_loss_total:.3f}"
    
    # 验证第二个有压管道出口
    other_losses2 = (
        (outlet2.head_loss_friction or 0.0) +
        (outlet2.head_loss_local or 0.0) +
        (outlet2.head_loss_bend or 0.0) +
        (getattr(outlet2, 'head_loss_reserve', 0.0) or 0.0) +
        (getattr(outlet2, 'head_loss_gate', 0.0) or 0.0) +
        (getattr(outlet2, 'head_loss_siphon', 0.0) or 0.0)
    )
    expected_total2 = other_losses2 + 2.8
    
    assert abs(outlet2.head_loss_total - expected_total2) < 0.01, \
        f"第二个有压管道出口的总水头损失应包含 external_head_loss。" \
        f"预期: {expected_total2:.3f}, 实际: {outlet2.head_loss_total:.3f}"


if __name__ == "__main__":
    # 运行测试
    test_external_head_loss_included_in_total()
    print("✓ test_external_head_loss_included_in_total")
    
    test_no_external_head_loss_not_affected()
    print("✓ test_no_external_head_loss_not_affected")
    
    test_external_head_loss_zero()
    print("✓ test_external_head_loss_zero")
    
    test_multiple_nodes_with_external_loss()
    print("✓ test_multiple_nodes_with_external_loss")
    
    print("\n所有单元测试通过！")
