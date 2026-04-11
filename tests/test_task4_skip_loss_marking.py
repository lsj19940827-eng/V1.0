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
    验证有压同类结构相邻时，不再插入渐变段。

    场景：有压管道1出口 → 有压管道2进口（不同名）
    期望：直接相邻，不生成渐变段
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
    
    # 验证结果：保持原始两个节点，不额外插入渐变段
    assert len(result_nodes) == 2, f"期望2个节点，实际{len(result_nodes)}个"
    assert not any(getattr(node, "is_transition", False) for node in result_nodes), \
        "有压同类结构相邻时不应生成渐变段"


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


def test_unnamed_pressure_pipe_around_tunnel_inserts_transition_rows_after_preprocess():
    """
    验证空名称有压管道包夹隧洞时，预处理后仍能在两侧插入渐变段。
    """
    pipe_before = ChannelNode()
    pipe_before.structure_type = StructureType.from_string("有压管道")
    pipe_before.name = ""
    pipe_before.section_params = {"D": 1.5}
    pipe_before.station_MC = 100.0

    tunnel_inlet = ChannelNode()
    tunnel_inlet.structure_type = StructureType.from_string("隧洞-圆形")
    tunnel_inlet.name = "纯牛马"
    tunnel_inlet.section_params = {"D": 2.0}
    tunnel_inlet.station_MC = 130.0

    tunnel_outlet = ChannelNode()
    tunnel_outlet.structure_type = StructureType.from_string("隧洞-圆形")
    tunnel_outlet.name = "纯牛马"
    tunnel_outlet.section_params = {"D": 2.0}
    tunnel_outlet.station_MC = 180.0

    pipe_after = ChannelNode()
    pipe_after.structure_type = StructureType.from_string("有压管道")
    pipe_after.name = ""
    pipe_after.section_params = {"D": 1.5}
    pipe_after.station_MC = 210.0

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    nodes = [pipe_before, tunnel_inlet, tunnel_outlet, pipe_after]

    calculator.preprocess_nodes(nodes)
    result_nodes = calculator.identify_and_insert_transitions(nodes)

    transition_rows = [node for node in result_nodes if getattr(node, "is_transition", False)]

    assert len(transition_rows) >= 2, "空名称有压管道包夹隧洞时，两侧都应至少插入一条渐变段"
    assert getattr(result_nodes[1], "is_transition", False) == True, "隧洞进口前应出现渐变段"
    assert getattr(result_nodes[-2], "is_transition", False) == True, "隧洞出口后应出现渐变段"
    assert all(node.transition_skip_loss for node in transition_rows), "含有压管道侧的渐变段应保持 skip_loss=True"
    assert nodes[0].in_out == InOutType.NORMAL, "空名称有压管道原始进出口状态仍应保持 NORMAL"
    assert nodes[-1].in_out == InOutType.NORMAL, "空名称有压管道原始进出口状态仍应保持 NORMAL"


def test_xxpipe_unnamed_pressure_pipe_next_to_directional_drill_has_no_transition_gap():
    """
    验证 xx管 模式下，空名称普通有压管道紧邻定向钻时不再识别渐变段/补段。
    """
    anonymous_pipe = ChannelNode()
    anonymous_pipe.flow_section = "2"
    anonymous_pipe.structure_type = StructureType.from_string("有压管道")
    anonymous_pipe.name = ""
    anonymous_pipe.in_out = InOutType.NORMAL
    anonymous_pipe.section_params = {"D": 1.0}
    anonymous_pipe.station_MC = 100.0

    drill_inlet = ChannelNode()
    drill_inlet.flow_section = "2"
    drill_inlet.structure_type = StructureType.from_string("定向钻")
    drill_inlet.name = "半兽人"
    drill_inlet.in_out = InOutType.INLET
    drill_inlet.section_params = {"D": 1.0}
    drill_inlet.station_MC = 160.0

    settings = ProjectSettings()
    settings.channel_level = "支管"
    calculator = WaterProfileCalculator(settings)

    result = calculator._should_insert_open_channel(anonymous_pipe, drill_inlet, [anonymous_pipe, drill_inlet])

    assert result["need_transition_1"] == False, "xx管 匿名有压管道紧邻定向钻时不应插出口渐变段"
    assert result["need_transition_2"] == False, "xx管 匿名有压管道紧邻定向钻时不应插进口渐变段"
    assert result["need_open_channel"] == False, "xx管 匿名有压管道紧邻定向钻时不应再弹补段"


def test_xxpipe_prescan_and_insert_only_keep_tunnel_side_gaps():
    """
    验证 xx管 模式下，整组顺序里只保留匿名有压管道与隧洞之间的两处补段。
    """
    def _make_node(flow_section, structure, station, name="", in_out=InOutType.NORMAL, diameter=1.0):
        node = ChannelNode()
        node.flow_section = str(flow_section)
        node.structure_type = StructureType.from_string(structure)
        node.name = name
        node.in_out = in_out
        node.station_MC = station
        node.section_params = {"D": diameter}
        return node

    nodes = [
        _make_node(1, "有压管道", 100.0, "", InOutType.NORMAL, 1.5),
        _make_node(1, "隧洞-圆形", 160.0, "纯牛马", InOutType.INLET, 2.0),
        _make_node(1, "隧洞-圆形", 220.0, "纯牛马", InOutType.OUTLET, 2.0),
        _make_node(1, "有压管道", 280.0, "", InOutType.NORMAL, 1.5),
        _make_node(2, "有压管道", 330.0, "", InOutType.NORMAL, 1.0),
        _make_node(2, "定向钻", 390.0, "半兽人", InOutType.INLET, 1.0),
        _make_node(2, "定向钻", 450.0, "半兽人", InOutType.OUTLET, 1.0),
        _make_node(2, "有压管道", 510.0, "", InOutType.NORMAL, 1.0),
        _make_node(3, "有压管道", 560.0, "", InOutType.NORMAL, 0.8),
        _make_node(3, "顶管", 620.0, "饿了么", InOutType.INLET, 0.8),
        _make_node(3, "顶管", 680.0, "饿了么", InOutType.OUTLET, 0.8),
        _make_node(3, "有压管道", 740.0, "", InOutType.NORMAL, 0.8),
    ]

    settings = ProjectSettings()
    settings.channel_level = "支管"
    calculator = WaterProfileCalculator(settings)

    calculator.preprocess_nodes(nodes)
    gaps = calculator.pre_scan_open_channels(nodes)
    result_nodes = calculator.identify_and_insert_transitions(nodes)

    transition_rows = [node for node in result_nodes if getattr(node, "is_transition", False)]
    open_channel_rows = [node for node in result_nodes if getattr(node, "is_auto_inserted_channel", False)]

    assert len(gaps) == 2, "xx管 匿名有压管道整组里，预扫描补段只应保留纯牛马两侧"
    assert {(gap["prev_name"], gap["next_name"]) for gap in gaps} == {
        ("", "纯牛马"),
        ("纯牛马", ""),
    }, "预扫描补段应只落在纯牛马隧洞前后"
    assert len(open_channel_rows) == 0, "无可复制明渠参考时，不应额外插入补段行"
    assert len(transition_rows) == 2, "实际插入时应只保留纯牛马前后两条渐变段"


if __name__ == "__main__":
    import pytest
    
    print("运行 Task 4 验证测试...")
    pytest.main([__file__, "-v"])
