# -*- coding: utf-8 -*-
"""
Task 13.1 单元测试：水力计算跳过渐变段损失逻辑

验证 calculate_transition_loss() 函数正确处理 transition_skip_loss 标记
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.hydraulic_calc import HydraulicCalculator
from core.calculator import WaterProfileCalculator


def test_skip_loss_true_returns_zero():
    """
    测试 skip_loss=True 时跳过损失计算
    
    场景：有压管道侧的渐变段标记 transition_skip_loss=True
    期望：calculate_transition_loss() 返回 0，但仍然计算渐变段长度
    
    Requirements: 10.1, 10.2, 10.3
    """
    # 创建前一节点（有压管道出口）
    prev_node = ChannelNode()
    prev_node.structure_type = StructureType.from_string("有压管道")
    prev_node.name = "有压管道1"
    prev_node.in_out = InOutType.OUTLET
    prev_node.section_params = {"D": 1.5}
    prev_node.station_MC = 100.0
    prev_node.velocity = 2.0
    prev_node.water_depth = 1.5
    prev_node.flow_section = "渠道1"
    
    # 创建渐变段节点（标记 skip_loss=True）
    transition = ChannelNode()
    transition.is_transition = True
    transition.transition_skip_loss = True  # 关键：跳过损失标记
    transition.transition_type = "出口"
    transition.transition_form = "曲线形反弯扭曲面"
    transition.station_MC = 105.0
    transition.flow_section = "渠道1"
    
    # 创建后一节点（隧洞进口）
    next_node = ChannelNode()
    next_node.structure_type = StructureType.from_string("隧洞-圆形")
    next_node.name = "隧洞1"
    next_node.in_out = InOutType.INLET
    next_node.section_params = {"D": 2.0}
    next_node.station_MC = 110.0
    next_node.velocity = 1.5
    next_node.water_depth = 2.0
    next_node.flow_section = "渠道1"
    
    # 创建水力计算器
    settings = ProjectSettings()
    calc = HydraulicCalculator(settings)
    
    # 调用 calculate_transition_loss
    all_nodes = [prev_node, transition, next_node]
    loss = calc.calculate_transition_loss(transition, prev_node, next_node, all_nodes)
    
    # 验证结果
    assert loss == 0.0, \
        f"skip_loss=True 时应返回 0，实际返回 {loss}"
    
    # 验证渐变段长度仍然被计算（可能为0如果水面宽度相同，但字段应该被设置）
    assert hasattr(transition, 'transition_length'), \
        "skip_loss=True 时仍应设置 transition_length 字段"
    
    # 验证水头损失字段被设置为 0
    assert transition.head_loss_transition == 0.0, \
        f"skip_loss=True 时 head_loss_transition 应为 0，实际为 {transition.head_loss_transition}"


def test_skip_loss_false_calculates_normally():
    """
    测试 skip_loss=False 时正常计算损失
    
    场景：明渠侧的渐变段标记 transition_skip_loss=False
    期望：calculate_transition_loss() 正常计算并返回非零损失
    
    Requirements: 10.1, 10.2, 10.3
    """
    # 创建前一节点（明渠）
    prev_node = ChannelNode()
    prev_node.structure_type = StructureType.from_string("明渠-梯形")
    prev_node.flow_section = "渠道1"
    prev_node.section_params = {"b": 2.0, "m": 1.5, "h": 1.8}
    prev_node.station_MC = 100.0
    prev_node.velocity = 1.5
    prev_node.water_depth = 1.5
    prev_node.roughness = 0.025
    
    # 创建渐变段节点（标记 skip_loss=False）
    transition = ChannelNode()
    transition.is_transition = True
    transition.transition_skip_loss = False  # 关键：不跳过损失
    transition.transition_type = "进口"
    transition.transition_form = "曲线形反弯扭曲面"
    transition.station_MC = 105.0
    
    # 创建后一节点（隧洞进口）
    next_node = ChannelNode()
    next_node.structure_type = StructureType.from_string("隧洞-圆形")
    next_node.name = "隧洞1"
    next_node.in_out = InOutType.INLET
    next_node.section_params = {"D": 2.0}
    next_node.station_MC = 110.0
    next_node.velocity = 2.0
    next_node.water_depth = 1.8
    next_node.roughness = 0.014
    
    # 创建水力计算器
    settings = ProjectSettings()
    calc = HydraulicCalculator(settings)
    
    # 调用 calculate_transition_loss
    all_nodes = [prev_node, transition, next_node]
    loss = calc.calculate_transition_loss(transition, prev_node, next_node, all_nodes)
    
    # 验证结果
    assert loss > 0, \
        f"skip_loss=False 时应计算损失并返回非零值，实际返回 {loss}"
    
    # 验证渐变段长度被计算
    assert transition.transition_length > 0, \
        f"渐变段长度应被计算，实际长度 {transition.transition_length}"
    
    # 验证水头损失字段被正确设置
    assert transition.head_loss_transition == loss, \
        f"head_loss_transition 应等于返回值 {loss}，实际为 {transition.head_loss_transition}"
    
    # 验证局部损失和沿程损失都被计算
    assert hasattr(transition, 'transition_head_loss_local'), \
        "应计算局部水头损失"
    assert hasattr(transition, 'transition_head_loss_friction'), \
        "应计算沿程水头损失"


def test_existing_transition_length_still_builds_length_details():
    """
    测试已有渐变段长度时仍会生成双击详情数据

    场景：transition_length 已经由表格/旧结果回填，但本次仍需双击查看详情
    期望：calculate_transition_loss() 不应因为长度已存在而跳过
    transition_length_calc_details 的重建
    """
    prev_node = ChannelNode()
    prev_node.structure_type = StructureType.from_string("明渠-梯形")
    prev_node.flow_section = "渠道1"
    prev_node.section_params = {"B": 2.0, "m": 1.5, "h": 1.6}
    prev_node.velocity = 1.4
    prev_node.water_depth = 1.6
    prev_node.roughness = 0.014

    transition = ChannelNode()
    transition.is_transition = True
    transition.transition_skip_loss = False
    transition.transition_type = "进口"
    transition.transition_form = "曲线形反弯扭曲面"
    transition.transition_length = 9.0
    transition.flow_section = "渠道1"

    next_node = ChannelNode()
    next_node.structure_type = StructureType.from_string("隧洞-圆形")
    next_node.name = "隧洞1"
    next_node.in_out = InOutType.INLET
    next_node.section_params = {"D": 2.4}
    next_node.velocity = 2.1
    next_node.water_depth = 1.8
    next_node.roughness = 0.014
    next_node.flow_section = "渠道1"

    calc = HydraulicCalculator(ProjectSettings())
    loss = calc.calculate_transition_loss(
        transition, prev_node, next_node, [prev_node, transition, next_node]
    )

    assert loss > 0, "已有长度时仍应继续计算渐变段损失"
    assert transition.transition_length == 9.0, "已有长度不应被本次损失计算覆盖"
    assert transition.transition_length_calc_details, \
        "已有长度时仍应生成渐变段长度详情，供双击查看"
    assert "B1" in transition.transition_length_calc_details
    assert "B2" in transition.transition_length_calc_details
    assert "L_result" in transition.transition_length_calc_details


def test_skip_loss_still_calculates_length():
    """
    测试 skip_loss=True 时仍然计算渐变段长度
    
    场景：倒虹吸侧的渐变段标记 transition_skip_loss=True
    期望：渐变段长度被正确计算并设置到 transition_length 字段
    
    Requirements: 10.2
    """
    # 创建前一节点（倒虹吸出口）
    prev_node = ChannelNode()
    prev_node.structure_type = StructureType.from_string("倒虹吸")
    prev_node.name = "倒虹吸1"
    prev_node.in_out = InOutType.OUTLET
    prev_node.section_params = {"D": 1.2}
    prev_node.station_MC = 200.0
    prev_node.velocity = 2.5
    prev_node.water_depth = 1.2
    prev_node.flow_section = "渠道2"
    
    # 创建渐变段节点（标记 skip_loss=True）
    transition = ChannelNode()
    transition.is_transition = True
    transition.transition_skip_loss = True
    transition.transition_type = "出口"
    transition.transition_form = "曲线形反弯扭曲面"
    transition.station_MC = 205.0
    transition.flow_section = "渠道2"
    
    # 创建后一节点（渡槽进口）
    next_node = ChannelNode()
    next_node.structure_type = StructureType.from_string("渡槽-U形")
    next_node.name = "渡槽1"
    next_node.in_out = InOutType.INLET
    next_node.section_params = {"b": 1.5, "h": 1.8}
    next_node.station_MC = 210.0
    next_node.velocity = 1.8
    next_node.water_depth = 1.5
    next_node.flow_section = "渠道2"
    
    # 创建水力计算器
    settings = ProjectSettings()
    calc = HydraulicCalculator(settings)
    
    # 调用 calculate_transition_loss
    all_nodes = [prev_node, transition, next_node]
    loss = calc.calculate_transition_loss(transition, prev_node, next_node, all_nodes)
    
    # 验证损失为 0
    assert loss == 0.0, \
        f"skip_loss=True 时损失应为 0，实际为 {loss}"
    
    # 验证渐变段长度字段被设置
    assert hasattr(transition, 'transition_length'), \
        "skip_loss=True 时仍应设置 transition_length 字段"
    
    # 验证长度是非负的
    assert transition.transition_length >= 0, \
        f"渐变段长度应为非负值，实际长度 {transition.transition_length}"


def test_skip_loss_existing_length_still_builds_length_details():
    """
    测试 skip_loss=True 且已有长度时仍能补建双击详情

    场景：旧结果或表格回填已经给了 transition_length，
    当前重新计算只需补详情，不应覆盖当前采用长度。
    """
    prev_node = ChannelNode()
    prev_node.structure_type = StructureType.from_string("明渠-梯形")
    prev_node.flow_section = "渠道3"
    prev_node.section_params = {"B": 2.2, "m": 1.5, "h": 1.4}
    prev_node.velocity = 1.3
    prev_node.water_depth = 1.4
    prev_node.roughness = 0.014

    transition = ChannelNode()
    transition.is_transition = True
    transition.transition_skip_loss = True
    transition.transition_type = "进口"
    transition.transition_form = "曲线形反弯扭曲面"
    transition.transition_length = 7.5
    transition.flow_section = "渠道3"

    next_node = ChannelNode()
    next_node.structure_type = StructureType.from_string("倒虹吸")
    next_node.name = "倒虹吸1"
    next_node.in_out = InOutType.INLET
    next_node.section_params = {"D": 2.0}
    next_node.velocity = 2.0
    next_node.water_depth = 1.6
    next_node.roughness = 0.014
    next_node.flow_section = "渠道3"

    calc = HydraulicCalculator(ProjectSettings())
    loss = calc.calculate_transition_loss(
        transition, prev_node, next_node, [prev_node, transition, next_node]
    )

    assert loss == 0.0, "skip_loss=True 时损失应保持为 0"
    assert transition.transition_length == 7.5, "已有长度应保留为当前采用长度"
    assert transition.transition_length_calc_details, \
        "skip_loss=True 且已有长度时仍应补建长度详情"
    assert transition.transition_length_calc_details.get("actual_length") == 7.5
    assert transition.transition_length_calc_details.get("L_result") == 7.5
    assert transition.transition_length_calc_details.get("uses_existing_length") is True


def test_main_calculator_preserves_existing_skip_loss_length_details():
    """
    测试主计算入口 calculate_transition_losses() 也走兼容逻辑

    场景：生产流程中 skip_loss 渐变段已有采用长度（可能来自压缩/合并）。
    期望：主计算入口不覆盖当前长度，并补建双击详情。
    """
    prev_node = ChannelNode()
    prev_node.structure_type = StructureType.from_string("明渠-梯形")
    prev_node.flow_section = "渠道4"
    prev_node.section_params = {"B": 2.2, "m": 1.5, "h": 1.4}
    prev_node.velocity = 1.3
    prev_node.water_depth = 1.4
    prev_node.roughness = 0.014

    transition = ChannelNode()
    transition.is_transition = True
    transition.transition_skip_loss = True
    transition.transition_type = "进口"
    transition.transition_form = "曲线形反弯扭曲面"
    transition.transition_length = 7.5
    transition.flow_section = "渠道4"

    next_node = ChannelNode()
    next_node.structure_type = StructureType.from_string("倒虹吸")
    next_node.name = "倒虹吸2"
    next_node.in_out = InOutType.INLET
    next_node.section_params = {"D": 2.0}
    next_node.velocity = 2.0
    next_node.water_depth = 1.6
    next_node.roughness = 0.014
    next_node.flow_section = "渠道4"

    calc = WaterProfileCalculator(ProjectSettings())
    nodes = [prev_node, transition, next_node]

    calc.calculate_transition_losses(nodes)

    assert transition.head_loss_transition == 0.0, "skip_loss=True 时主入口也应保持损失为 0"
    assert transition.transition_length == 7.5, "主计算入口不应覆盖当前采用长度"
    assert transition.transition_length_calc_details, "主计算入口应补建长度详情"
    assert transition.transition_length_calc_details.get("actual_length") == 7.5
    assert transition.transition_length_calc_details.get("L_result") == 7.5
    assert transition.transition_length_calc_details.get("uses_existing_length") is True


if __name__ == "__main__":
    # 运行测试
    test_skip_loss_true_returns_zero()
    print("✓ test_skip_loss_true_returns_zero passed")
    
    test_skip_loss_false_calculates_normally()
    print("✓ test_skip_loss_false_calculates_normally passed")

    test_existing_transition_length_still_builds_length_details()
    print("✓ test_existing_transition_length_still_builds_length_details passed")
    
    test_skip_loss_still_calculates_length()
    print("✓ test_skip_loss_still_calculates_length passed")

    test_skip_loss_existing_length_still_builds_length_details()
    print("✓ test_skip_loss_existing_length_still_builds_length_details passed")

    test_main_calculator_preserves_existing_skip_loss_length_details()
    print("✓ test_main_calculator_preserves_existing_skip_loss_length_details passed")
    
    print("\n所有测试通过！")
