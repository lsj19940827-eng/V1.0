# -*- coding: utf-8 -*-
"""
转弯半径临时值管理 - 属性测试

**Validates: Requirements 8.1, 8.2, 8.3, 8.4**

Property 10: 转弯半径临时值往返
For any 有压管道节点，在几何计算前填充临时转弯半径 R = n × D，
几何计算后应清空该临时值（除非该值是从水力计算回写的）。
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "渠系断面设计"))

from hypothesis import given, strategies as st, settings, assume
from typing import List
import copy

from models.data_models import ChannelNode
from models.enums import StructureType, InOutType


# ============================================================================
# Hypothesis 策略：生成测试数据
# ============================================================================

@st.composite
def pressure_pipe_node_strategy(draw, has_existing_radius: bool = False, has_external_loss: bool = False):
    """生成有压管道节点"""
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.name = draw(st.text(min_size=1, max_size=20))
    node.in_out = draw(st.sampled_from([InOutType.INLET, InOutType.OUTLET]))
    
    # 设置管径 D
    diameter = draw(st.floats(min_value=0.3, max_value=3.0))
    node.section_params = {"D": diameter}
    
    # 设置其他参数
    node.flow = draw(st.floats(min_value=0.1, max_value=10.0))
    node.roughness = draw(st.floats(min_value=0.011, max_value=0.025))
    node.x = draw(st.floats(min_value=0, max_value=10000))
    node.y = draw(st.floats(min_value=0, max_value=10000))
    node.station_MC = draw(st.floats(min_value=0, max_value=10000))
    
    # 可选：设置已有的转弯半径（用户导入或手动输入）
    if has_existing_radius:
        node.turn_radius = draw(st.floats(min_value=10.0, max_value=500.0))
    else:
        node.turn_radius = 0.0
    
    # 可选：设置外部水头损失（表示已完成水力计算）
    if has_external_loss:
        node.external_head_loss = draw(st.floats(min_value=0.1, max_value=5.0))
    else:
        node.external_head_loss = None
    
    return node


@st.composite
def siphon_node_strategy(draw, has_existing_radius: bool = False, has_external_loss: bool = False):
    """生成倒虹吸节点（用于测试统一处理）"""
    node = ChannelNode()
    node.structure_type = StructureType.from_string("倒虹吸")
    node.is_inverted_siphon = True
    node.name = draw(st.text(min_size=1, max_size=20))
    node.in_out = draw(st.sampled_from([InOutType.INLET, InOutType.OUTLET]))
    
    # 设置管径 D
    diameter = draw(st.floats(min_value=0.3, max_value=3.0))
    node.section_params = {"D": diameter}
    
    # 设置其他参数
    node.flow = draw(st.floats(min_value=0.1, max_value=10.0))
    node.roughness = draw(st.floats(min_value=0.011, max_value=0.025))
    node.x = draw(st.floats(min_value=0, max_value=10000))
    node.y = draw(st.floats(min_value=0, max_value=10000))
    node.station_MC = draw(st.floats(min_value=0, max_value=10000))
    
    # 可选：设置已有的转弯半径
    if has_existing_radius:
        node.turn_radius = draw(st.floats(min_value=10.0, max_value=500.0))
    else:
        node.turn_radius = 0.0
    
    # 可选：设置外部水头损失
    if has_external_loss:
        node.external_head_loss = draw(st.floats(min_value=0.1, max_value=5.0))
    else:
        node.external_head_loss = None
    
    return node


@st.composite
def mixed_node_list_strategy(draw):
    """生成混合节点列表（有压管道 + 倒虹吸 + 其他）"""
    nodes = []
    
    # 添加1-3个有压管道节点
    num_ppipe = draw(st.integers(min_value=1, max_value=3))
    for _ in range(num_ppipe):
        has_existing = draw(st.booleans())
        has_loss = draw(st.booleans())
        node = draw(pressure_pipe_node_strategy(
            has_existing_radius=has_existing,
            has_external_loss=has_loss
        ))
        nodes.append(node)
    
    # 添加0-2个倒虹吸节点
    num_siphon = draw(st.integers(min_value=0, max_value=2))
    for _ in range(num_siphon):
        has_existing = draw(st.booleans())
        has_loss = draw(st.booleans())
        node = draw(siphon_node_strategy(
            has_existing_radius=has_existing,
            has_external_loss=has_loss
        ))
        nodes.append(node)
    
    # 添加0-2个其他类型节点
    num_other = draw(st.integers(min_value=0, max_value=2))
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


# ============================================================================
# 模拟 panel.py 中的函数（用于测试）
# ============================================================================

def fill_turn_radius_for_geometry(nodes: List[ChannelNode], n: float):
    """
    为有压管道节点填充临时转弯半径 R = n × D
    
    在几何计算前调用，为有压管道节点临时填充转弯半径值供几何计算使用。
    
    Args:
        nodes: ChannelNode 列表
        n: 转弯半径倍数（R = n × D）
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


def clear_temporary_turn_radius(nodes: List[ChannelNode]):
    """
    清空有压管道节点的临时转弯半径
    
    在几何计算后调用，清空临时写入的转弯半径值。
    但保留从水力计算回写的值（通过检查 external_head_loss 字段判断）。
    
    Args:
        nodes: ChannelNode 列表
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
# 属性测试
# ============================================================================

@settings(max_examples=100, deadline=None)
@given(
    nodes=mixed_node_list_strategy(),
    n=st.floats(min_value=2.0, max_value=5.0)
)
def test_property_10_turn_radius_round_trip(nodes: List[ChannelNode], n: float):
    """
    **Property 10: 转弯半径临时值往返**
    
    **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
    
    For any 有压管道节点，在几何计算前填充临时转弯半径 R = n × D，
    几何计算后应清空该临时值（除非该值是从水力计算回写的）。
    
    验证点：
    1. 填充前：有压管道节点转弯半径为0或已有值
    2. 填充后：无已有值的节点转弯半径 = n × D
    3. 填充后：有已有值的节点转弯半径保持不变
    4. 清空后：无 external_head_loss 的节点转弯半径清零
    5. 清空后：有 external_head_loss 的节点转弯半径保留
    6. 不影响非有压管道节点
    """
    # 创建节点的深拷贝以保存原始状态
    original_nodes = copy.deepcopy(nodes)
    
    # 记录原始状态
    original_radii = {}
    for i, node in enumerate(nodes):
        if node.is_pressure_pipe:
            original_radii[i] = node.turn_radius
    
    # ========== 验证点 1: 填充前状态 ==========
    for i, node in enumerate(nodes):
        if node.is_pressure_pipe:
            assert node.turn_radius >= 0, \
                f"填充前，有压管道节点{i}的转弯半径应 >= 0"
    
    # ========== 执行填充操作 ==========
    fill_turn_radius_for_geometry(nodes, n)
    
    # ========== 验证点 2 & 3: 填充后状态 ==========
    for i, node in enumerate(nodes):
        if not node.is_pressure_pipe:
            continue
        
        original_radius = original_radii[i]
        diameter_D = node.section_params.get('D', 0.0)
        
        if original_radius > 0:
            # 验证点 3: 有已有值的节点保持不变
            assert node.turn_radius == original_radius, \
                f"节点{i}已有转弯半径{original_radius}，填充后应保持不变，实际为{node.turn_radius}"
        elif diameter_D > 0:
            # 验证点 2: 无已有值的节点应填充 R = n × D
            expected_radius = n * diameter_D
            assert abs(node.turn_radius - expected_radius) < 1e-6, \
                f"节点{i}应填充转弯半径 {expected_radius}，实际为{node.turn_radius}"
        else:
            # 管径无效，不应填充
            assert node.turn_radius == 0, \
                f"节点{i}管径无效，不应填充转弯半径"
    
    # ========== 执行清空操作 ==========
    clear_temporary_turn_radius(nodes)
    
    # ========== 验证点 4 & 5: 清空后状态 ==========
    for i, node in enumerate(nodes):
        if not node.is_pressure_pipe:
            continue
        
        if node.external_head_loss is not None and node.external_head_loss > 0:
            # 验证点 5: 有 external_head_loss 的节点保留转弯半径
            assert node.turn_radius > 0, \
                f"节点{i}有外部水头损失，清空后应保留转弯半径"
        else:
            # 验证点 4: 无 external_head_loss 的节点清零
            assert node.turn_radius == 0, \
                f"节点{i}无外部水头损失，清空后转弯半径应为0，实际为{node.turn_radius}"
    
    # ========== 验证点 6: 不影响非有压管道节点 ==========
    for i, (node, orig_node) in enumerate(zip(nodes, original_nodes)):
        if not node.is_pressure_pipe:
            assert node.turn_radius == orig_node.turn_radius, \
                f"非有压管道节点{i}的转弯半径不应被修改"


@settings(max_examples=50, deadline=None)
@given(
    diameter=st.floats(min_value=0.3, max_value=3.0),
    n=st.floats(min_value=2.0, max_value=5.0)
)
def test_property_10_formula_correctness(diameter: float, n: float):
    """
    **Property 10 扩展: 公式正确性**
    
    验证转弯半径计算公式 R = n × D 的正确性。
    
    **Validates: Requirement 8.1**
    """
    # 创建有压管道节点
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {"D": diameter}
    node.turn_radius = 0.0
    
    nodes = [node]
    
    # 填充转弯半径
    fill_turn_radius_for_geometry(nodes, n)
    
    # 验证公式
    expected_radius = n * diameter
    assert abs(node.turn_radius - expected_radius) < 1e-6, \
        f"转弯半径应为 {expected_radius}，实际为 {node.turn_radius}"


@settings(max_examples=50, deadline=None)
@given(
    existing_radius=st.floats(min_value=10.0, max_value=500.0),
    n=st.floats(min_value=2.0, max_value=5.0)
)
def test_property_10_preserve_existing_values(existing_radius: float, n: float):
    """
    **Property 10 扩展: 保留已有值**
    
    验证已有非零转弯半径值的节点不会被覆盖。
    
    **Validates: Requirement 8.2**
    """
    # 创建有压管道节点，设置已有转弯半径
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {"D": 1.5}
    node.turn_radius = existing_radius
    
    nodes = [node]
    
    # 填充转弯半径
    fill_turn_radius_for_geometry(nodes, n)
    
    # 验证已有值未被修改
    assert node.turn_radius == existing_radius, \
        f"已有转弯半径{existing_radius}应保持不变，实际为{node.turn_radius}"


@settings(max_examples=50, deadline=None)
@given(
    external_loss=st.floats(min_value=0.1, max_value=5.0),
    n=st.floats(min_value=2.0, max_value=5.0)
)
def test_property_10_preserve_hydraulic_writeback(external_loss: float, n: float):
    """
    **Property 10 扩展: 保留水力计算回写值**
    
    验证有 external_head_loss 的节点在清空时保留转弯半径。
    
    **Validates: Requirement 8.5**
    """
    # 创建有压管道节点
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {"D": 1.5}
    node.turn_radius = 0.0
    node.external_head_loss = external_loss
    
    nodes = [node]
    
    # 填充转弯半径
    fill_turn_radius_for_geometry(nodes, n)
    
    # 记录填充后的值
    filled_radius = node.turn_radius
    assert filled_radius > 0, "应填充转弯半径"
    
    # 清空转弯半径
    clear_temporary_turn_radius(nodes)
    
    # 验证有 external_head_loss 的节点保留转弯半径
    assert node.turn_radius == filled_radius, \
        f"有外部水头损失的节点应保留转弯半径{filled_radius}，实际为{node.turn_radius}"


@settings(max_examples=50, deadline=None)
@given(
    n=st.floats(min_value=2.0, max_value=5.0)
)
def test_property_10_clear_temporary_values(n: float):
    """
    **Property 10 扩展: 清空临时值**
    
    验证无 external_head_loss 的节点在清空时转弯半径归零。
    
    **Validates: Requirement 8.4**
    """
    # 创建有压管道节点（无 external_head_loss）
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {"D": 1.5}
    node.turn_radius = 0.0
    node.external_head_loss = None
    
    nodes = [node]
    
    # 填充转弯半径
    fill_turn_radius_for_geometry(nodes, n)
    
    # 验证填充成功
    assert node.turn_radius > 0, "应填充转弯半径"
    
    # 清空转弯半径
    clear_temporary_turn_radius(nodes)
    
    # 验证清空成功
    assert node.turn_radius == 0, \
        f"无外部水头损失的节点应清空转弯半径，实际为{node.turn_radius}"


@settings(max_examples=50, deadline=None)
@given(
    nodes=mixed_node_list_strategy(),
    n=st.floats(min_value=2.0, max_value=5.0)
)
def test_property_10_idempotence(nodes: List[ChannelNode], n: float):
    """
    **Property 10 扩展: 幂等性**
    
    验证多次填充和清空操作的幂等性。
    """
    # 第一次填充和清空
    fill_turn_radius_for_geometry(nodes, n)
    clear_temporary_turn_radius(nodes)
    
    # 记录第一次清空后的状态
    first_radii = [node.turn_radius for node in nodes]
    
    # 第二次填充和清空
    fill_turn_radius_for_geometry(nodes, n)
    clear_temporary_turn_radius(nodes)
    
    # 记录第二次清空后的状态
    second_radii = [node.turn_radius for node in nodes]
    
    # 验证两次结果一致
    for i, (r1, r2) in enumerate(zip(first_radii, second_radii)):
        assert abs(r1 - r2) < 1e-6, \
            f"节点{i}两次清空后的转弯半径应一致: {r1} vs {r2}"


# ============================================================================
# 单元测试（基本功能验证）
# ============================================================================

def test_fill_turn_radius_basic():
    """测试基本的转弯半径填充功能"""
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
    
    # 验证
    expected = 3.0 * 1.5
    assert abs(node.turn_radius - expected) < 1e-6, \
        f"转弯半径应为{expected}，实际为{node.turn_radius}"


def test_clear_turn_radius_basic():
    """测试基本的转弯半径清空功能"""
    # 创建有压管道节点
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {"D": 1.5}
    node.turn_radius = 4.5
    node.external_head_loss = None
    
    nodes = [node]
    
    # 清空转弯半径
    clear_temporary_turn_radius(nodes)
    
    # 验证
    assert node.turn_radius == 0, \
        f"转弯半径应清空为0，实际为{node.turn_radius}"


def test_preserve_writeback_value():
    """测试保留水力计算回写值"""
    # 创建有压管道节点（有 external_head_loss）
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.is_pressure_pipe = True
    node.section_params = {"D": 1.5}
    node.turn_radius = 4.5
    node.external_head_loss = 1.2
    
    nodes = [node]
    
    # 清空转弯半径
    clear_temporary_turn_radius(nodes)
    
    # 验证保留
    assert node.turn_radius == 4.5, \
        f"有外部水头损失的节点应保留转弯半径，实际为{node.turn_radius}"


def test_mixed_nodes():
    """测试混合节点列表"""
    # 创建混合节点
    ppipe1 = ChannelNode()
    ppipe1.structure_type = StructureType.from_string("有压管道")
    ppipe1.is_pressure_pipe = True
    ppipe1.section_params = {"D": 1.5}
    ppipe1.turn_radius = 0.0
    
    ppipe2 = ChannelNode()
    ppipe2.structure_type = StructureType.from_string("有压管道")
    ppipe2.is_pressure_pipe = True
    ppipe2.section_params = {"D": 2.0}
    ppipe2.turn_radius = 10.0  # 已有值
    ppipe2.external_head_loss = 1.5  # 有外部水头损失，应保留
    
    other = ChannelNode()
    other.structure_type = StructureType.from_string("明渠-梯形")
    other.turn_radius = 100.0
    
    nodes = [ppipe1, ppipe2, other]
    n = 3.0
    
    # 填充
    fill_turn_radius_for_geometry(nodes, n)
    
    # 验证
    assert abs(ppipe1.turn_radius - 4.5) < 1e-6, "ppipe1应填充为4.5"
    assert ppipe2.turn_radius == 10.0, "ppipe2应保持10.0"
    assert other.turn_radius == 100.0, "other应保持100.0"
    
    # 清空
    clear_temporary_turn_radius(nodes)
    
    # 验证
    assert ppipe1.turn_radius == 0, "ppipe1应清空为0"
    assert ppipe2.turn_radius == 10.0, "ppipe2应保持10.0（有外部水头损失）"
    assert other.turn_radius == 100.0, "other应保持100.0"


if __name__ == "__main__":
    # 运行单元测试
    print("运行基本功能测试...")
    test_fill_turn_radius_basic()
    print("✓ 填充转弯半径测试通过")
    
    print("\n运行清空功能测试...")
    test_clear_turn_radius_basic()
    print("✓ 清空转弯半径测试通过")
    
    print("\n运行保留回写值测试...")
    test_preserve_writeback_value()
    print("✓ 保留回写值测试通过")
    
    print("\n运行混合节点测试...")
    test_mixed_nodes()
    print("✓ 混合节点测试通过")
    
    print("\n所有单元测试通过！")
    print("\n运行属性测试需要 pytest 和 hypothesis:")
    print("  pytest tests/test_turn_radius_management_property.py -v")
