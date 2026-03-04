# -*- coding: utf-8 -*-
"""
转弯半径临时值管理 - 单元测试

**Validates: Requirements 8.1, 8.2, 8.4, 8.5**

测试转弯半径临时值管理功能的具体示例和边界情况。
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "渠系断面设计"))

from models.data_models import ChannelNode
from models.enums import StructureType, InOutType


# ============================================================================
# 模拟 panel.py 中的函数（用于测试）
# ============================================================================

def fill_turn_radius_for_geometry(nodes, n):
    """
    为有压管道节点填充临时转弯半径 R = n × D
    
    在几何计算前调用，为有压管道节点临时填充转弯半径值供几何计算使用。
    
    Args:
        nodes: ChannelNode 列表
        n: 转弯半径倍数（R = n × D）
        
    Requirements: 8.1, 8.2, 8.3
    """
    if not nodes:
        return
    
    for node in nodes:
        # 只处理有压管道节点
        if not node.is_pressure_pipe:
            continue
        
        # 如果已有非零转弯半径值，保留不变（可能是用户导入或手动输入的值）
        if node.turn_radius and node.turn_radius > 0:
            continue
        
        # 从 section_params 中获取管径 D
        diameter_D = node.section_params.get('D', 0.0)
        if diameter_D <= 0:
            continue
        
        # 计算临时转弯半径 R = n × D
        node.turn_radius = n * diameter_D


def clear_temporary_turn_radius(nodes):
    """
    清空有压管道节点的临时转弯半径
    
    在几何计算后调用，清空临时写入的转弯半径值。
    但保留从水力计算回写的值（通过检查 external_head_loss 字段判断）。
    
    Args:
        nodes: ChannelNode 列表
        
    Requirements: 8.4, 8.5
    """
    if not nodes:
        return
    
    for node in nodes:
        # 只处理有压管道节点
        if not node.is_pressure_pipe:
            continue
        
        # 如果有 external_head_loss 值，说明已经完成水力计算并回写了转弯半径
        # 这种情况下保留转弯半径值不清空
        if node.external_head_loss is not None and node.external_head_loss > 0:
            continue
        
        # 清空临时转弯半径
        node.turn_radius = 0.0


# ============================================================================
# 单元测试
# ============================================================================

def test_fill_temporary_turn_radius():
    """
    测试临时值填充
    
    **Validates: Requirement 8.1**
    """
    # 创建有压管道节点
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {"D": 1.5}
    node.turn_radius = 0.0
    
    nodes = [node]
    n = 3.0
    
    # 填充转弯半径
    fill_turn_radius_for_geometry(nodes, n)
    
    # 验证：R = n × D = 3.0 × 1.5 = 4.5
    assert abs(node.turn_radius - 4.5) < 1e-6, \
        f"转弯半径应为4.5，实际为{node.turn_radius}"


def test_preserve_user_imported_value():
    """
    测试保留用户导入值
    
    **Validates: Requirement 8.2**
    """
    # 创建有压管道节点，设置已有转弯半径（用户导入）
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {"D": 1.5}
    node.turn_radius = 50.0  # 用户导入的值
    
    nodes = [node]
    n = 3.0
    
    # 填充转弯半径
    fill_turn_radius_for_geometry(nodes, n)
    
    # 验证：应保留用户导入的值
    assert node.turn_radius == 50.0, \
        f"应保留用户导入的转弯半径50.0，实际为{node.turn_radius}"


def test_clear_temporary_value():
    """
    测试清空临时值
    
    **Validates: Requirement 8.4**
    """
    # 创建有压管道节点
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {"D": 1.5}
    node.turn_radius = 0.0
    node.external_head_loss = None  # 无外部水头损失
    
    nodes = [node]
    n = 3.0
    
    # 填充转弯半径
    fill_turn_radius_for_geometry(nodes, n)
    assert node.turn_radius > 0, "应填充转弯半径"
    
    # 清空转弯半径
    clear_temporary_turn_radius(nodes)
    
    # 验证：应清空临时值
    assert node.turn_radius == 0, \
        f"应清空临时转弯半径，实际为{node.turn_radius}"


def test_preserve_hydraulic_writeback_value():
    """
    测试保留水力计算回写值
    
    **Validates: Requirement 8.5**
    """
    # 创建有压管道节点，设置外部水头损失（表示已完成水力计算）
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {"D": 1.5}
    node.turn_radius = 0.0
    node.external_head_loss = 1.2  # 有外部水头损失
    
    nodes = [node]
    n = 3.0
    
    # 填充转弯半径
    fill_turn_radius_for_geometry(nodes, n)
    filled_radius = node.turn_radius
    assert filled_radius > 0, "应填充转弯半径"
    
    # 清空转弯半径
    clear_temporary_turn_radius(nodes)
    
    # 验证：应保留回写值
    assert node.turn_radius == filled_radius, \
        f"应保留水力计算回写的转弯半径{filled_radius}，实际为{node.turn_radius}"


def test_multiple_pressure_pipes():
    """
    测试多个有压管道节点
    """
    # 创建多个有压管道节点
    node1 = ChannelNode()
    node1.structure_type = StructureType.from_string("有压管道")
    node1.is_pressure_pipe = True
    node1.section_params = {"D": 1.0}
    node1.turn_radius = 0.0
    
    node2 = ChannelNode()
    node2.structure_type = StructureType.from_string("有压管道")
    node2.is_pressure_pipe = True
    node2.section_params = {"D": 2.0}
    node2.turn_radius = 0.0
    
    node3 = ChannelNode()
    node3.structure_type = StructureType.from_string("有压管道")
    node3.is_pressure_pipe = True
    node3.section_params = {"D": 1.5}
    node3.turn_radius = 0.0
    node3.external_head_loss = 0.8  # 有外部水头损失
    
    nodes = [node1, node2, node3]
    n = 3.0
    
    # 填充转弯半径
    fill_turn_radius_for_geometry(nodes, n)
    
    # 验证填充
    assert abs(node1.turn_radius - 3.0) < 1e-6, "node1应填充为3.0"
    assert abs(node2.turn_radius - 6.0) < 1e-6, "node2应填充为6.0"
    assert abs(node3.turn_radius - 4.5) < 1e-6, "node3应填充为4.5"
    
    # 清空转弯半径
    clear_temporary_turn_radius(nodes)
    
    # 验证清空
    assert node1.turn_radius == 0, "node1应清空"
    assert node2.turn_radius == 0, "node2应清空"
    assert abs(node3.turn_radius - 4.5) < 1e-6, "node3应保留（有外部水头损失）"


def test_mixed_node_types():
    """
    测试混合节点类型（有压管道 + 其他）
    """
    # 创建有压管道节点
    ppipe = ChannelNode()
    ppipe.structure_type = StructureType.from_string("有压管道")
    ppipe.is_pressure_pipe = True
    ppipe.section_params = {"D": 1.5}
    ppipe.turn_radius = 0.0
    
    # 创建明渠节点
    channel = ChannelNode()
    channel.structure_type = StructureType.from_string("明渠-梯形")
    channel.is_pressure_pipe = False
    channel.turn_radius = 100.0
    
    # 创建隧洞节点
    tunnel = ChannelNode()
    tunnel.structure_type = StructureType.from_string("隧洞-圆形")
    tunnel.is_pressure_pipe = False
    tunnel.turn_radius = 150.0
    
    nodes = [ppipe, channel, tunnel]
    n = 3.0
    
    # 填充转弯半径
    fill_turn_radius_for_geometry(nodes, n)
    
    # 验证：只有有压管道节点被填充
    assert abs(ppipe.turn_radius - 4.5) < 1e-6, "有压管道应填充"
    assert channel.turn_radius == 100.0, "明渠不应被修改"
    assert tunnel.turn_radius == 150.0, "隧洞不应被修改"
    
    # 清空转弯半径
    clear_temporary_turn_radius(nodes)
    
    # 验证：只有有压管道节点被清空
    assert ppipe.turn_radius == 0, "有压管道应清空"
    assert channel.turn_radius == 100.0, "明渠不应被修改"
    assert tunnel.turn_radius == 150.0, "隧洞不应被修改"


def test_zero_diameter():
    """
    测试管径为零的情况
    """
    # 创建有压管道节点，管径为0
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {"D": 0.0}
    node.turn_radius = 0.0
    
    nodes = [node]
    n = 3.0
    
    # 填充转弯半径
    fill_turn_radius_for_geometry(nodes, n)
    
    # 验证：管径为0时不应填充
    assert node.turn_radius == 0, \
        f"管径为0时不应填充转弯半径，实际为{node.turn_radius}"


def test_missing_diameter():
    """
    测试缺少管径参数的情况
    """
    # 创建有压管道节点，缺少管径参数
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {}  # 缺少 D
    node.turn_radius = 0.0
    
    nodes = [node]
    n = 3.0
    
    # 填充转弯半径
    fill_turn_radius_for_geometry(nodes, n)
    
    # 验证：缺少管径时不应填充
    assert node.turn_radius == 0, \
        f"缺少管径时不应填充转弯半径，实际为{node.turn_radius}"


def test_empty_node_list():
    """
    测试空节点列表
    """
    nodes = []
    n = 3.0
    
    # 填充转弯半径（不应报错）
    fill_turn_radius_for_geometry(nodes, n)
    
    # 清空转弯半径（不应报错）
    clear_temporary_turn_radius(nodes)
    
    # 验证：无异常抛出
    assert True, "空节点列表应正常处理"


def test_none_node_list():
    """
    测试 None 节点列表
    """
    nodes = None
    n = 3.0
    
    # 填充转弯半径（不应报错）
    fill_turn_radius_for_geometry(nodes, n)
    
    # 清空转弯半径（不应报错）
    clear_temporary_turn_radius(nodes)
    
    # 验证：无异常抛出
    assert True, "None 节点列表应正常处理"


def test_different_n_values():
    """
    测试不同的 n 值
    """
    # 创建有压管道节点
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {"D": 2.0}
    node.turn_radius = 0.0
    
    nodes = [node]
    
    # 测试 n = 2.0
    fill_turn_radius_for_geometry(nodes, 2.0)
    assert abs(node.turn_radius - 4.0) < 1e-6, "n=2.0时，R应为4.0"
    
    # 清空
    clear_temporary_turn_radius(nodes)
    assert node.turn_radius == 0, "应清空"
    
    # 测试 n = 5.0
    fill_turn_radius_for_geometry(nodes, 5.0)
    assert abs(node.turn_radius - 10.0) < 1e-6, "n=5.0时，R应为10.0"
    
    # 清空
    clear_temporary_turn_radius(nodes)
    assert node.turn_radius == 0, "应清空"


def test_external_head_loss_zero():
    """
    测试 external_head_loss 为 0 的情况
    """
    # 创建有压管道节点，external_head_loss 为 0
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {"D": 1.5}
    node.turn_radius = 0.0
    node.external_head_loss = 0.0  # 为 0
    
    nodes = [node]
    n = 3.0
    
    # 填充转弯半径
    fill_turn_radius_for_geometry(nodes, n)
    assert node.turn_radius > 0, "应填充转弯半径"
    
    # 清空转弯半径
    clear_temporary_turn_radius(nodes)
    
    # 验证：external_head_loss 为 0 时应清空
    assert node.turn_radius == 0, \
        f"external_head_loss为0时应清空转弯半径，实际为{node.turn_radius}"


def test_siphon_nodes_not_affected():
    """
    测试倒虹吸节点不受影响
    
    注意：fill_turn_radius_for_geometry 和 clear_temporary_turn_radius
    只处理 is_pressure_pipe=True 的节点，不处理倒虹吸节点。
    """
    # 创建倒虹吸节点
    siphon = ChannelNode()
    siphon.structure_type = StructureType.from_string("倒虹吸")
    siphon.is_inverted_siphon = True
    siphon.is_pressure_pipe = False  # 倒虹吸不是有压管道
    siphon.section_params = {"D": 1.5}
    siphon.turn_radius = 0.0
    
    nodes = [siphon]
    n = 3.0
    
    # 填充转弯半径
    fill_turn_radius_for_geometry(nodes, n)
    
    # 验证：倒虹吸节点不应被填充
    assert siphon.turn_radius == 0, \
        f"倒虹吸节点不应被填充，实际为{siphon.turn_radius}"


def test_round_trip_consistency():
    """
    测试往返一致性
    """
    # 创建有压管道节点
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {"D": 1.5}
    node.turn_radius = 0.0
    
    nodes = [node]
    n = 3.0
    
    # 第一次往返
    fill_turn_radius_for_geometry(nodes, n)
    clear_temporary_turn_radius(nodes)
    first_result = node.turn_radius
    
    # 第二次往返
    fill_turn_radius_for_geometry(nodes, n)
    clear_temporary_turn_radius(nodes)
    second_result = node.turn_radius
    
    # 验证：两次结果应一致
    assert first_result == second_result, \
        f"两次往返结果应一致: {first_result} vs {second_result}"


if __name__ == "__main__":
    # 运行所有测试
    print("运行单元测试...")
    
    test_fill_temporary_turn_radius()
    print("✓ test_fill_temporary_turn_radius")
    
    test_preserve_user_imported_value()
    print("✓ test_preserve_user_imported_value")
    
    test_clear_temporary_value()
    print("✓ test_clear_temporary_value")
    
    test_preserve_hydraulic_writeback_value()
    print("✓ test_preserve_hydraulic_writeback_value")
    
    test_multiple_pressure_pipes()
    print("✓ test_multiple_pressure_pipes")
    
    test_mixed_node_types()
    print("✓ test_mixed_node_types")
    
    test_zero_diameter()
    print("✓ test_zero_diameter")
    
    test_missing_diameter()
    print("✓ test_missing_diameter")
    
    test_empty_node_list()
    print("✓ test_empty_node_list")
    
    test_none_node_list()
    print("✓ test_none_node_list")
    
    test_different_n_values()
    print("✓ test_different_n_values")
    
    test_external_head_loss_zero()
    print("✓ test_external_head_loss_zero")
    
    test_siphon_nodes_not_affected()
    print("✓ test_siphon_nodes_not_affected")
    
    test_round_trip_consistency()
    print("✓ test_round_trip_consistency")
    
    print("\n所有单元测试通过！")
    print("\n使用 pytest 运行测试:")
    print("  pytest tests/test_turn_radius_management_unit.py -v")
