# -*- coding: utf-8 -*-
"""
有压管道渐变段插入决策 - 单元测试

**Validates: Requirements 2.1, 2.2, 2.4, 2.5, 4.4, 4.5**

测试 _should_insert_open_channel() 函数对有压同类结构的处理：
- 测试有压管道出口 → 隧洞进口
- 测试渡槽出口 → 有压管道进口
- 测试有压同类结构相邻时不插渐变段
- 测试有压管道 → 倒虹吸
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.calculator import WaterProfileCalculator


def test_pressure_pipe_outlet_to_tunnel_inlet():
    """
    测试有压管道出口 → 隧洞进口
    
    **Validates: Requirement 2.1, 4.1**
    
    验证：
    - 应插入出口渐变段
    - 应插入进口渐变段
    - 有压管道侧渐变段标记 skip_loss=True
    - 隧洞侧渐变段标记 skip_loss=False
    """
    # 创建有压管道出口节点
    pressure_pipe_outlet = ChannelNode()
    pressure_pipe_outlet.structure_type = StructureType.from_string("有压管道")
    pressure_pipe_outlet.name = "有压管道1"
    pressure_pipe_outlet.in_out = InOutType.OUTLET
    pressure_pipe_outlet.section_params = {"D": 1.5}
    pressure_pipe_outlet.station_MC = 100.0
    
    # 创建隧洞进口节点
    tunnel_inlet = ChannelNode()
    tunnel_inlet.structure_type = StructureType.from_string("隧洞-圆形")
    tunnel_inlet.name = "隧洞1"
    tunnel_inlet.in_out = InOutType.INLET
    tunnel_inlet.section_params = {"D": 2.0}
    tunnel_inlet.station_MC = 120.0
    
    # 调用判断函数
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._should_insert_open_channel(pressure_pipe_outlet, tunnel_inlet)
    
    # 验证结果
    assert result['need_transition_1'] == True, "应插入有压管道出口渐变段"
    assert result['need_transition_2'] == True, "应插入隧洞进口渐变段"
    assert result['skip_loss_transition_1'] == True, "有压管道侧渐变段应标记 skip_loss=True"
    assert result['skip_loss_transition_2'] == False, "隧洞侧渐变段应标记 skip_loss=False"
    assert result['distance'] == 20.0, f"里程差应为 20.0，实际为 {result['distance']}"


def test_aqueduct_outlet_to_pressure_pipe_inlet():
    """
    测试渡槽出口 → 有压管道进口
    
    **Validates: Requirement 2.2, 4.6**
    
    验证：
    - 应插入出口渐变段
    - 应插入进口渐变段
    - 渡槽侧渐变段标记 skip_loss=False
    - 有压管道侧渐变段标记 skip_loss=True
    """
    # 创建渡槽出口节点
    aqueduct_outlet = ChannelNode()
    aqueduct_outlet.structure_type = StructureType.from_string("渡槽-U形")
    aqueduct_outlet.name = "渡槽1"
    aqueduct_outlet.in_out = InOutType.OUTLET
    aqueduct_outlet.section_params = {"b": 2.0, "h": 1.5}
    aqueduct_outlet.station_MC = 200.0
    
    # 创建有压管道进口节点
    pressure_pipe_inlet = ChannelNode()
    pressure_pipe_inlet.structure_type = StructureType.from_string("有压管道")
    pressure_pipe_inlet.name = "有压管道2"
    pressure_pipe_inlet.in_out = InOutType.INLET
    pressure_pipe_inlet.section_params = {"D": 1.8}
    pressure_pipe_inlet.station_MC = 225.0
    
    # 调用判断函数
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._should_insert_open_channel(aqueduct_outlet, pressure_pipe_inlet)
    
    # 验证结果
    assert result['need_transition_1'] == True, "应插入渡槽出口渐变段"
    assert result['need_transition_2'] == True, "应插入有压管道进口渐变段"
    assert result['skip_loss_transition_1'] == False, "渡槽侧渐变段应标记 skip_loss=False"
    assert result['skip_loss_transition_2'] == True, "有压管道侧渐变段应标记 skip_loss=True"
    assert result['distance'] == 25.0, f"里程差应为 25.0，实际为 {result['distance']}"


def test_same_pressure_pipe_same_diameter():
    """
    测试有压管道 → 有压管道（同名同径）
    
    **Validates: Requirement 2.4**
    
    验证：
    - 不应插入渐变段
    """
    # 创建同一有压管道的出口节点
    pipe_outlet = ChannelNode()
    pipe_outlet.structure_type = StructureType.from_string("有压管道")
    pipe_outlet.name = "有压管道1"
    pipe_outlet.in_out = InOutType.OUTLET
    pipe_outlet.section_params = {"D": 1.5}
    pipe_outlet.station_MC = 100.0
    
    # 创建同一有压管道的进口节点（下一段）
    pipe_inlet = ChannelNode()
    pipe_inlet.structure_type = StructureType.from_string("有压管道")
    pipe_inlet.name = "有压管道1"
    pipe_inlet.in_out = InOutType.INLET
    pipe_inlet.section_params = {"D": 1.5}
    pipe_inlet.station_MC = 150.0
    
    # 调用判断函数
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._should_insert_open_channel(pipe_outlet, pipe_inlet)
    
    # 验证结果
    assert result['need_transition_1'] == False, "同名同径有压管道之间不应插入出口渐变段"
    assert result['need_transition_2'] == False, "同名同径有压管道之间不应插入进口渐变段"
    assert result['need_open_channel'] == False, "同名同径有压管道之间不应插入明渠段"


def test_pressure_pipe_like_neighbors_skip_transitions_even_with_different_names():
    """
    测试有压同类结构相邻时，不再因为名称不同插入渐变段。
    """
    # 创建第一个有压管道的出口节点
    pipe1_outlet = ChannelNode()
    pipe1_outlet.structure_type = StructureType.from_string("有压管道")
    pipe1_outlet.name = "有压管道1"
    pipe1_outlet.in_out = InOutType.OUTLET
    pipe1_outlet.section_params = {"D": 1.5}
    pipe1_outlet.station_MC = 100.0
    
    # 创建第二个有压管道的进口节点
    pipe2_inlet = ChannelNode()
    pipe2_inlet.structure_type = StructureType.from_string("有压管道")
    pipe2_inlet.name = "有压管道2"
    pipe2_inlet.in_out = InOutType.INLET
    pipe2_inlet.section_params = {"D": 1.8}
    pipe2_inlet.station_MC = 130.0
    
    # 调用判断函数
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._should_insert_open_channel(pipe1_outlet, pipe2_inlet)
    
    # 验证结果
    assert result['need_transition_1'] == False, "有压同类结构之间不应插入出口渐变段"
    assert result['need_transition_2'] == False, "有压同类结构之间不应插入进口渐变段"
    assert result['need_open_channel'] == False, "有压同类结构之间不应插入连接段"
    assert result['distance'] == 30.0, f"里程差应为 30.0，实际为 {result['distance']}"


def test_pressure_pipe_to_siphon():
    """
    测试有压管道 → 倒虹吸
    
    **Validates: Requirement 4.4**
    
    验证：
    - 应插入出口渐变段
    - 应插入进口渐变段
    - 两侧都标记 skip_loss=True（都是有压流建筑物）
    """
    # 创建有压管道出口节点
    pipe_outlet = ChannelNode()
    pipe_outlet.structure_type = StructureType.from_string("有压管道")
    pipe_outlet.name = "有压管道1"
    pipe_outlet.in_out = InOutType.OUTLET
    pipe_outlet.section_params = {"D": 1.5}
    pipe_outlet.station_MC = 100.0
    
    # 创建倒虹吸进口节点
    siphon_inlet = ChannelNode()
    siphon_inlet.structure_type = StructureType.from_string("倒虹吸")
    siphon_inlet.name = "倒虹吸1"
    siphon_inlet.in_out = InOutType.INLET
    siphon_inlet.section_params = {"D": 1.2}
    siphon_inlet.station_MC = 125.0
    
    # 调用判断函数
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._should_insert_open_channel(pipe_outlet, siphon_inlet)
    
    # 验证结果
    assert result['need_transition_1'] == True, "有压管道与倒虹吸之间应插入出口渐变段"
    assert result['need_transition_2'] == True, "有压管道与倒虹吸之间应插入进口渐变段"
    assert result['skip_loss_transition_1'] == True, "有压管道侧渐变段应标记 skip_loss=True"
    assert result['skip_loss_transition_2'] == True, "倒虹吸侧渐变段应标记 skip_loss=True"
    assert result['distance'] == 25.0, f"里程差应为 25.0，实际为 {result['distance']}"


def test_unnamed_pressure_pipe_before_tunnel_inlet_uses_local_outlet_role():
    """
    测试空名称有压管道在隧洞进口上游时，插渐变段阶段可临时视为出口。

    验证：
    - 不改空名称有压管道的常规 NORMAL 状态
    - 仅在插渐变段判断时，仍能识别出两侧渐变段需求
    """
    pressure_pipe = ChannelNode()
    pressure_pipe.structure_type = StructureType.from_string("有压管道")
    pressure_pipe.name = ""
    pressure_pipe.in_out = InOutType.NORMAL
    pressure_pipe.section_params = {"D": 1.5}
    pressure_pipe.station_MC = 100.0

    tunnel_inlet = ChannelNode()
    tunnel_inlet.structure_type = StructureType.from_string("隧洞-圆形")
    tunnel_inlet.name = "隧洞1"
    tunnel_inlet.in_out = InOutType.INLET
    tunnel_inlet.section_params = {"D": 2.0}
    tunnel_inlet.station_MC = 130.0

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._should_insert_open_channel(pressure_pipe, tunnel_inlet)

    assert result["need_transition_1"] == True, "空名称有压管道上游侧应临时识别为出口渐变段"
    assert result["need_transition_2"] == True, "隧洞进口侧应识别为进口渐变段"
    assert result["skip_loss_transition_1"] == True, "有压管道侧仍应跳过渐变段损失"
    assert result["skip_loss_transition_2"] == False, "隧洞侧不应跳过渐变段损失"


def test_tunnel_outlet_to_unnamed_pressure_pipe_uses_local_inlet_role():
    """
    测试空名称有压管道在隧洞出口下游时，插渐变段阶段可临时视为进口。
    """
    tunnel_outlet = ChannelNode()
    tunnel_outlet.structure_type = StructureType.from_string("隧洞-圆形")
    tunnel_outlet.name = "隧洞1"
    tunnel_outlet.in_out = InOutType.OUTLET
    tunnel_outlet.section_params = {"D": 2.0}
    tunnel_outlet.station_MC = 200.0

    pressure_pipe = ChannelNode()
    pressure_pipe.structure_type = StructureType.from_string("有压管道")
    pressure_pipe.name = ""
    pressure_pipe.in_out = InOutType.NORMAL
    pressure_pipe.section_params = {"D": 1.5}
    pressure_pipe.station_MC = 230.0

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._should_insert_open_channel(tunnel_outlet, pressure_pipe)

    assert result["need_transition_1"] == True, "隧洞出口侧应识别为出口渐变段"
    assert result["need_transition_2"] == True, "空名称有压管道下游侧应临时识别为进口渐变段"
    assert result["skip_loss_transition_1"] == False, "隧洞侧不应跳过渐变段损失"
    assert result["skip_loss_transition_2"] == True, "有压管道侧仍应跳过渐变段损失"


def test_siphon_to_pressure_pipe():
    """
    测试倒虹吸 → 有压管道
    
    **Validates: Requirement 4.5**
    
    验证：
    - 应插入出口渐变段
    - 应插入进口渐变段
    - 两侧都标记 skip_loss=True（都是有压流建筑物）
    """
    # 创建倒虹吸出口节点
    siphon_outlet = ChannelNode()
    siphon_outlet.structure_type = StructureType.from_string("倒虹吸")
    siphon_outlet.name = "倒虹吸1"
    siphon_outlet.in_out = InOutType.OUTLET
    siphon_outlet.section_params = {"D": 1.2}
    siphon_outlet.station_MC = 200.0
    
    # 创建有压管道进口节点
    pipe_inlet = ChannelNode()
    pipe_inlet.structure_type = StructureType.from_string("有压管道")
    pipe_inlet.name = "有压管道1"
    pipe_inlet.in_out = InOutType.INLET
    pipe_inlet.section_params = {"D": 1.5}
    pipe_inlet.station_MC = 230.0
    
    # 调用判断函数
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._should_insert_open_channel(siphon_outlet, pipe_inlet)
    
    # 验证结果
    assert result['need_transition_1'] == True, "倒虹吸与有压管道之间应插入出口渐变段"
    assert result['need_transition_2'] == True, "倒虹吸与有压管道之间应插入进口渐变段"
    assert result['skip_loss_transition_1'] == True, "倒虹吸侧渐变段应标记 skip_loss=True"
    assert result['skip_loss_transition_2'] == True, "有压管道侧渐变段应标记 skip_loss=True"
    assert result['distance'] == 30.0, f"里程差应为 30.0，实际为 {result['distance']}"


def test_pressure_pipe_like_neighbors_skip_transitions_even_with_different_diameter():
    """
    测试有压同类结构相邻时，不再因为管径不同插入渐变段。
    """
    # 创建同一有压管道的出口节点（管径 1.5m）
    pipe_outlet = ChannelNode()
    pipe_outlet.structure_type = StructureType.from_string("有压管道")
    pipe_outlet.name = "有压管道1"
    pipe_outlet.in_out = InOutType.OUTLET
    pipe_outlet.section_params = {"D": 1.5}
    pipe_outlet.station_MC = 100.0
    
    # 创建同一有压管道的进口节点（管径 2.0m）
    pipe_inlet = ChannelNode()
    pipe_inlet.structure_type = StructureType.from_string("有压管道")
    pipe_inlet.name = "有压管道1"
    pipe_inlet.in_out = InOutType.INLET
    pipe_inlet.section_params = {"D": 2.0}
    pipe_inlet.station_MC = 130.0
    
    # 调用判断函数
    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._should_insert_open_channel(pipe_outlet, pipe_inlet)
    
    # 验证结果
    assert result['need_transition_1'] == False, "有压同类结构之间不应插入出口渐变段"
    assert result['need_transition_2'] == False, "有压同类结构之间不应插入进口渐变段"
    assert result['need_open_channel'] == False, "有压同类结构之间不应插入连接段"


def test_pressure_pipe_to_directional_drill_skips_transitions():
    """测试有压管道与定向钻相邻时，不插渐变段。"""
    pipe_outlet = ChannelNode()
    pipe_outlet.structure_type = StructureType.from_string("有压管道")
    pipe_outlet.name = "九龙右有压管道"
    pipe_outlet.in_out = InOutType.OUTLET
    pipe_outlet.section_params = {"D": 1.5}
    pipe_outlet.station_MC = 100.0

    drill_inlet = ChannelNode()
    drill_inlet.structure_type = StructureType.from_string("定向钻")
    drill_inlet.name = "穿路段"
    drill_inlet.in_out = InOutType.INLET
    drill_inlet.section_params = {"D": 1.2}
    drill_inlet.station_MC = 150.0

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._should_insert_open_channel(pipe_outlet, drill_inlet)

    assert result["need_transition_1"] == False, "有压管道与定向钻之间不应插入出口渐变段"
    assert result["need_transition_2"] == False, "有压管道与定向钻之间不应插入进口渐变段"
    assert result["need_open_channel"] == False, "有压管道与定向钻之间不应插入连接段"


def test_pipe_jacking_to_directional_drill_skips_transitions():
    """测试顶管与定向钻相邻时，不插渐变段。"""
    pipe_jacking_outlet = ChannelNode()
    pipe_jacking_outlet.structure_type = StructureType.from_string("顶管")
    pipe_jacking_outlet.name = "穿通高速顶管"
    pipe_jacking_outlet.in_out = InOutType.OUTLET
    pipe_jacking_outlet.section_params = {"D": 1.1}
    pipe_jacking_outlet.station_MC = 220.0

    drill_inlet = ChannelNode()
    drill_inlet.structure_type = StructureType.from_string("定向钻")
    drill_inlet.name = "穿路定向钻"
    drill_inlet.in_out = InOutType.INLET
    drill_inlet.section_params = {"D": 0.9}
    drill_inlet.station_MC = 260.0

    settings = ProjectSettings()
    calculator = WaterProfileCalculator(settings)
    result = calculator._should_insert_open_channel(pipe_jacking_outlet, drill_inlet)

    assert result["need_transition_1"] == False, "顶管与定向钻之间不应插入出口渐变段"
    assert result["need_transition_2"] == False, "顶管与定向钻之间不应插入进口渐变段"
    assert result["need_open_channel"] == False, "顶管与定向钻之间不应插入连接段"


if __name__ == "__main__":
    print("运行有压管道渐变段插入决策单元测试...")
    
    test_pressure_pipe_outlet_to_tunnel_inlet()
    print("✓ 测试有压管道出口 → 隧洞进口")
    
    test_aqueduct_outlet_to_pressure_pipe_inlet()
    print("✓ 测试渡槽出口 → 有压管道进口")
    
    test_same_pressure_pipe_same_diameter()
    print("✓ 测试有压管道 → 有压管道（同名同径）")
    
    test_pressure_pipe_like_neighbors_skip_transitions_even_with_different_names()
    print("✓ 测试有压同类结构 → 不同名仍不插渐变段")
    
    test_pressure_pipe_to_siphon()
    print("✓ 测试有压管道 → 倒虹吸")

    test_unnamed_pressure_pipe_before_tunnel_inlet_uses_local_outlet_role()
    print("✓ 测试空名称有压管道 → 隧洞进口")

    test_tunnel_outlet_to_unnamed_pressure_pipe_uses_local_inlet_role()
    print("✓ 测试隧洞出口 → 空名称有压管道")

    test_siphon_to_pressure_pipe()
    print("✓ 测试倒虹吸 → 有压管道")
    
    test_pressure_pipe_like_neighbors_skip_transitions_even_with_different_diameter()
    print("✓ 测试有压同类结构 → 不同径仍不插渐变段")

    test_pressure_pipe_to_directional_drill_skips_transitions()
    print("✓ 测试有压管道 → 定向钻")

    test_pipe_jacking_to_directional_drill_skips_transitions()
    print("✓ 测试顶管 → 定向钻")
    
    print("\n所有单元测试通过！")
