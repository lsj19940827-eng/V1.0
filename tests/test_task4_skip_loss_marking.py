# -*- coding: utf-8 -*-
"""
Task 4 验证测试：渐变段跳过损失标记逻辑

验证 identify_and_insert_transitions() 函数正确设置 transition_skip_loss 字段
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.calculator import WaterProfileCalculator


def test_pressure_pipe_side_skip_loss_true():
    """
    验证有压管道侧的渐变段标记 transition_skip_loss=True
    
    场景：有压管道出口 → 隧洞进口
    期望：插入的出口渐变段应标记 skip_loss=True
    """
    # 创建有压管道出口节点
    pipe_outlet = ChannelNode()
    pipe_outlet.structure_type = StructureType.from_string("有压管道")
    pipe_outlet.name = "有压管道1"
    pipe_outlet.in_out = InOutType.OUTLET
    pipe_outlet.section_params = {"D": 1.5}
    pipe_outlet.station_MC = 100.0
    
    # 创建隧洞进口节点
    tunnel_inlet = ChannelNode()
    tunnel_inlet.structure_type = StructureType.from_string("隧洞-圆形")
    tunnel_inlet.name = "隧洞1"
    tunnel_inlet.in_out = InOutType.INLET
    tunnel_inlet.section_params = {"D": 2.0}
    tunnel_inlet.station_MC = 110.0
    
    # 创建计算器并插入渐变段
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    nodes = [pipe_outlet, tunnel_inlet]
    result_nodes = calculator.identify_and_insert_transitions(nodes)
    
    # 验证结果
    # 应该有3个节点：有压管道出口 + 渐变段 + 隧洞进口
    assert len(result_nodes) == 3, f"期望3个节点，实际{len(result_nodes)}个"
    
    # 第二个节点应该是渐变段
    transition = result_nodes[1]
    assert transition.is_transition == True, "第二个节点应该是渐变段"
    
    # 渐变段应标记 skip_loss=True（有压管道侧）
    assert transition.transition_skip_loss == True, \
        "有压管道侧的渐变段应标记 transition_skip_loss=True"


def test_open_channel_side_skip_loss_false():
    """
    验证明渠/隧洞/渡槽侧的渐变段标记 transition_skip_loss=False
    
    场景：隧洞出口 → 有压管道进口（合并渐变段）
    注意：当渐变段合并为一行时，如果任一侧是有压流建筑物，
         整个合并渐变段应标记 skip_loss=True 以避免重复计算
    """
    # 创建隧洞出口节点
    tunnel_outlet = ChannelNode()
    tunnel_outlet.structure_type = StructureType.from_string("隧洞-圆形")
    tunnel_outlet.name = "隧洞1"
    tunnel_outlet.in_out = InOutType.OUTLET
    tunnel_outlet.section_params = {"D": 2.0}
    tunnel_outlet.station_MC = 100.0
    
    # 创建有压管道进口节点
    pipe_inlet = ChannelNode()
    pipe_inlet.structure_type = StructureType.from_string("有压管道")
    pipe_inlet.name = "有压管道1"
    pipe_inlet.in_out = InOutType.INLET
    pipe_inlet.section_params = {"D": 1.5}
    pipe_inlet.station_MC = 110.0
    
    # 创建计算器并插入渐变段
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    nodes = [tunnel_outlet, pipe_inlet]
    result_nodes = calculator.identify_and_insert_transitions(nodes)
    
    # 验证结果
    # 应该有3个节点：隧洞出口 + 渐变段 + 有压管道进口
    assert len(result_nodes) == 3, f"期望3个节点，实际{len(result_nodes)}个"
    
    # 第二个节点应该是渐变段
    transition = result_nodes[1]
    assert transition.is_transition == True, "第二个节点应该是渐变段"
    
    # 合并渐变段：因为有压管道侧需要跳过损失，整个合并渐变段应标记 skip_loss=True
    assert transition.transition_skip_loss == True, \
        "合并渐变段中有压管道侧需要跳过损失，因此整个合并渐变段应标记 transition_skip_loss=True"


def test_both_sides_pressurized_skip_loss_true():
    """
    验证两侧都是有压流建筑物时，渐变段标记 skip_loss=True
    
    场景：有压管道1出口 → 有压管道2进口（不同名）
    期望：插入的渐变段应标记 skip_loss=True
    """
    # 创建有压管道1出口节点
    pipe1_outlet = ChannelNode()
    pipe1_outlet.structure_type = StructureType.from_string("有压管道")
    pipe1_outlet.name = "有压管道1"
    pipe1_outlet.in_out = InOutType.OUTLET
    pipe1_outlet.section_params = {"D": 1.5}
    pipe1_outlet.station_MC = 100.0
    
    # 创建有压管道2进口节点
    pipe2_inlet = ChannelNode()
    pipe2_inlet.structure_type = StructureType.from_string("有压管道")
    pipe2_inlet.name = "有压管道2"
    pipe2_inlet.in_out = InOutType.INLET
    pipe2_inlet.section_params = {"D": 1.8}
    pipe2_inlet.station_MC = 110.0
    
    # 创建计算器并插入渐变段
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    nodes = [pipe1_outlet, pipe2_inlet]
    result_nodes = calculator.identify_and_insert_transitions(nodes)
    
    # 验证结果
    # 应该有3个节点：有压管道1出口 + 渐变段 + 有压管道2进口
    assert len(result_nodes) == 3, f"期望3个节点，实际{len(result_nodes)}个"
    
    # 第二个节点应该是渐变段
    transition = result_nodes[1]
    assert transition.is_transition == True, "第二个节点应该是渐变段"
    
    # 渐变段应标记 skip_loss=True（两侧都是有压流建筑物）
    assert transition.transition_skip_loss == True, \
        "两侧都是有压流建筑物时，渐变段应标记 transition_skip_loss=True"


def test_siphon_side_skip_loss_true():
    """
    验证倒虹吸侧的渐变段也标记 transition_skip_loss=True
    
    场景：倒虹吸出口 → 渡槽进口
    期望：插入的出口渐变段应标记 skip_loss=True
    """
    # 创建倒虹吸出口节点
    siphon_outlet = ChannelNode()
    siphon_outlet.structure_type = StructureType.from_string("倒虹吸")
    siphon_outlet.name = "倒虹吸1"
    siphon_outlet.in_out = InOutType.OUTLET
    siphon_outlet.section_params = {"D": 1.5}
    siphon_outlet.station_MC = 100.0
    
    # 创建渡槽进口节点
    aqueduct_inlet = ChannelNode()
    aqueduct_inlet.structure_type = StructureType.from_string("渡槽-U形")
    aqueduct_inlet.name = "渡槽1"
    aqueduct_inlet.in_out = InOutType.INLET
    aqueduct_inlet.section_params = {"D": 2.0}
    aqueduct_inlet.station_MC = 110.0
    
    # 创建计算器并插入渐变段
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    nodes = [siphon_outlet, aqueduct_inlet]
    result_nodes = calculator.identify_and_insert_transitions(nodes)
    
    # 验证结果
    # 应该有3个节点：倒虹吸出口 + 渐变段 + 渡槽进口
    assert len(result_nodes) == 3, f"期望3个节点，实际{len(result_nodes)}个"
    
    # 第二个节点应该是渐变段
    transition = result_nodes[1]
    assert transition.is_transition == True, "第二个节点应该是渐变段"
    
    # 渐变段应标记 skip_loss=True（倒虹吸侧）
    assert transition.transition_skip_loss == True, \
        "倒虹吸侧的渐变段应标记 transition_skip_loss=True"


def test_separate_transitions_skip_loss_correct():
    """
    验证当有足够空间插入明渠段时，skip_loss 标记的正确性
    
    这个测试验证 _should_insert_open_channel 返回的 skip_loss 标记是否正确
    """
    # 创建渡槽出口节点
    aqueduct_outlet = ChannelNode()
    aqueduct_outlet.structure_type = StructureType.from_string("渡槽-U形")
    aqueduct_outlet.name = "渡槽1"
    aqueduct_outlet.in_out = InOutType.OUTLET
    aqueduct_outlet.section_params = {"D": 2.0}
    aqueduct_outlet.station_MC = 100.0
    
    # 创建倒虹吸进口节点（里程差较大）
    siphon_inlet = ChannelNode()
    siphon_inlet.structure_type = StructureType.from_string("倒虹吸")
    siphon_inlet.name = "倒虹吸1"
    siphon_inlet.in_out = InOutType.INLET
    siphon_inlet.section_params = {"D": 1.5}
    siphon_inlet.station_MC = 200.0  # 大里程差
    
    # 创建计算器
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 调用判断函数
    result = calculator._should_insert_open_channel(aqueduct_outlet, siphon_inlet)
    
    # 验证 skip_loss 标记
    assert result['skip_loss_transition_1'] == False, \
        "渡槽侧的出口渐变段应标记 skip_loss=False"
    assert result['skip_loss_transition_2'] == True, \
        "倒虹吸侧的进口渐变段应标记 skip_loss=True"


def test_with_open_channel_insertion():
    """
    验证当有足够空间插入明渠段时，skip_loss 标记的正确性
    
    这个测试验证 _should_insert_open_channel 返回的 skip_loss 标记是否正确
    """
    # 创建倒虹吸出口节点
    siphon_outlet = ChannelNode()
    siphon_outlet.structure_type = StructureType.from_string("倒虹吸")
    siphon_outlet.name = "倒虹吸1"
    siphon_outlet.in_out = InOutType.OUTLET
    siphon_outlet.section_params = {"D": 1.5}
    siphon_outlet.station_MC = 100.0
    
    # 创建隧洞进口节点（里程差较大）
    tunnel_inlet = ChannelNode()
    tunnel_inlet.structure_type = StructureType.from_string("隧洞-圆形")
    tunnel_inlet.name = "隧洞1"
    tunnel_inlet.in_out = InOutType.INLET
    tunnel_inlet.section_params = {"D": 2.0}
    tunnel_inlet.station_MC = 200.0  # 大里程差
    
    # 创建计算器
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    
    # 调用判断函数
    result = calculator._should_insert_open_channel(siphon_outlet, tunnel_inlet)
    
    # 验证 skip_loss 标记
    assert result['skip_loss_transition_1'] == True, \
        "倒虹吸侧的出口渐变段应标记 skip_loss=True"
    assert result['skip_loss_transition_2'] == False, \
        "隧洞侧的进口渐变段应标记 skip_loss=False"


if __name__ == "__main__":
    import pytest
    
    print("运行 Task 4 验证测试...")
    pytest.main([__file__, "-v"])
