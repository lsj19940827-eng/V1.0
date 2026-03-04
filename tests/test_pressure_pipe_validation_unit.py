# -*- coding: utf-8 -*-
"""
有压管道数据验证 - 单元测试

**Validates: Requirements 17.1, 17.2, 18.1, 18.2, 18.3, 18.4**

测试有压管道数据验证功能的具体示例和边界情况。
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

from models.data_models import ChannelNode
from models.enums import StructureType, InOutType
from core.pressure_pipe_data import (
    PressurePipeGroup,
    validate_pressure_pipe_node,
    validate_pressure_pipe_group
)


def test_validate_valid_node():
    """
    测试验证有效的有压管道节点
    
    **Validates: Requirements 18.1, 18.2, 18.3**
    """
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "测试有压管道"
    node.in_out = InOutType.INLET
    node.section_params = {"D": 1.5}
    node.flow = 2.0
    node.roughness = 0.014
    node.station_MC = 100
    
    # 验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=1)
    
    assert is_valid, f"有效节点应通过验证，错误: {errors}"
    assert len(errors) == 0, "有效节点不应有错误消息"


def test_validate_invalid_diameter_zero():
    """
    测试检测管径为零的节点
    
    **Validates: Requirement 18.1**
    """
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "测试有压管道"
    node.in_out = InOutType.INLET
    node.section_params = {"D": 0.0}  # 管径为零
    node.flow = 2.0
    node.roughness = 0.014
    
    # 验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=5)
    
    assert not is_valid, "管径为零的节点应验证失败"
    assert len(errors) > 0, "应有错误消息"
    
    # 检查错误消息内容
    error_text = " ".join(errors)
    assert "5" in error_text, "错误消息应包含行号"
    assert "管径" in error_text, "错误消息应提到管径"


def test_validate_invalid_diameter_negative():
    """
    测试检测管径为负数的节点
    
    **Validates: Requirement 18.1**
    """
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "测试有压管道"
    node.in_out = InOutType.INLET
    node.section_params = {"D": -1.5}  # 管径为负数
    node.flow = 2.0
    node.roughness = 0.014
    
    # 验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=3)
    
    assert not is_valid, "管径为负数的节点应验证失败"
    assert len(errors) > 0, "应有错误消息"
    
    error_text = " ".join(errors)
    assert "3" in error_text, "错误消息应包含行号"
    assert "管径" in error_text, "错误消息应提到管径"
    assert "-1.5" in error_text, "错误消息应包含具体的无效值"


def test_validate_missing_diameter():
    """
    测试检测缺少管径的节点
    
    **Validates: Requirement 17.1**
    """
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "测试有压管道"
    node.in_out = InOutType.INLET
    node.section_params = {}  # 缺少管径
    node.flow = 2.0
    node.roughness = 0.014
    
    # 验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=7)
    
    assert not is_valid, "缺少管径的节点应验证失败"
    assert len(errors) > 0, "应有错误消息"
    
    error_text = " ".join(errors)
    assert "7" in error_text, "错误消息应包含行号"
    assert "缺少管径" in error_text, "错误消息应指出缺少管径"


def test_validate_invalid_roughness_zero():
    """
    测试检测糙率为零的节点
    
    **Validates: Requirement 18.2**
    """
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "测试有压管道"
    node.in_out = InOutType.INLET
    node.section_params = {"D": 1.5}
    node.flow = 2.0
    node.roughness = 0.0  # 糙率为零
    
    # 验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=10)
    
    assert not is_valid, "糙率为零的节点应验证失败"
    assert len(errors) > 0, "应有错误消息"
    
    error_text = " ".join(errors)
    assert "10" in error_text, "错误消息应包含行号"
    assert "糙率" in error_text, "错误消息应提到糙率"


def test_validate_invalid_roughness_negative():
    """
    测试检测糙率为负数的节点
    
    **Validates: Requirement 18.2**
    """
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "测试有压管道"
    node.in_out = InOutType.INLET
    node.section_params = {"D": 1.5}
    node.flow = 2.0
    node.roughness = -0.014  # 糙率为负数
    
    # 验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=12)
    
    assert not is_valid, "糙率为负数的节点应验证失败"
    assert len(errors) > 0, "应有错误消息"
    
    error_text = " ".join(errors)
    assert "12" in error_text, "错误消息应包含行号"
    assert "糙率" in error_text, "错误消息应提到糙率"


def test_validate_invalid_flow_zero():
    """
    测试检测流量为零的节点
    
    **Validates: Requirement 18.3**
    """
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "测试有压管道"
    node.in_out = InOutType.INLET
    node.section_params = {"D": 1.5}
    node.flow = 0.0  # 流量为零
    node.roughness = 0.014
    
    # 验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=15)
    
    assert not is_valid, "流量为零的节点应验证失败"
    assert len(errors) > 0, "应有错误消息"
    
    error_text = " ".join(errors)
    assert "15" in error_text, "错误消息应包含行号"
    assert "流量" in error_text, "错误消息应提到流量"


def test_validate_invalid_flow_negative():
    """
    测试检测流量为负数的节点
    
    **Validates: Requirement 18.3**
    """
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "测试有压管道"
    node.in_out = InOutType.INLET
    node.section_params = {"D": 1.5}
    node.flow = -2.0  # 流量为负数
    node.roughness = 0.014
    
    # 验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=18)
    
    assert not is_valid, "流量为负数的节点应验证失败"
    assert len(errors) > 0, "应有错误消息"
    
    error_text = " ".join(errors)
    assert "18" in error_text, "错误消息应包含行号"
    assert "流量" in error_text, "错误消息应提到流量"


def test_validate_missing_in_out_identifier():
    """
    测试检测缺少进出口标识的节点
    
    **Validates: Requirement 17.2**
    """
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "测试有压管道"
    node.in_out = InOutType.NORMAL  # 不是进或出
    node.section_params = {"D": 1.5}
    node.flow = 2.0
    node.roughness = 0.014
    
    # 验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=20)
    
    assert not is_valid, "缺少进出口标识的节点应验证失败"
    assert len(errors) > 0, "应有错误消息"
    
    error_text = " ".join(errors)
    assert "20" in error_text, "错误消息应包含行号"
    assert "进出口" in error_text, "错误消息应提到进出口标识"


def test_validate_multiple_errors():
    """
    测试检测多个错误的节点
    
    验证所有错误都被报告
    """
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "测试有压管道"
    node.in_out = InOutType.NORMAL  # 错误1：缺少进出口标识
    node.section_params = {"D": -1.0}  # 错误2：管径无效
    node.flow = 0.0  # 错误3：流量无效
    node.roughness = -0.014  # 错误4：糙率无效
    
    # 验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=25)
    
    assert not is_valid, "有多个错误的节点应验证失败"
    assert len(errors) == 4, f"应报告4个错误，实际报告了{len(errors)}个"
    
    # 验证所有错误都被报告
    error_text = " ".join(errors)
    assert "管径" in error_text, "应报告管径错误"
    assert "糙率" in error_text, "应报告糙率错误"
    assert "流量" in error_text, "应报告流量错误"
    assert "进出口" in error_text, "应报告进出口标识错误"


def test_validate_valid_group():
    """
    测试验证有效的有压管道分组
    
    **Validates: Requirements 18.1, 18.2, 18.3, 18.4**
    """
    # 创建进口节点
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = "测试有压管道"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 1.5}
    inlet.flow = 2.0
    inlet.roughness = 0.014
    inlet.station_MC = 100
    
    # 创建出口节点
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "测试有压管道"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.5}
    outlet.flow = 2.0
    outlet.roughness = 0.014
    outlet.station_MC = 200
    
    # 创建分组
    group = PressurePipeGroup(
        name="测试有压管道",
        inlet_node=inlet,
        outlet_node=outlet,
        inlet_row_index=0,
        outlet_row_index=1,
        diameter_D=1.5,
        roughness=0.014,
        flow=2.0
    )
    
    # 验证
    is_valid, errors = validate_pressure_pipe_group(group)
    
    assert is_valid, f"有效分组应通过验证，错误: {errors}"
    assert len(errors) == 0, "有效分组不应有错误消息"


def test_validate_group_missing_inlet():
    """
    测试检测缺少进口的分组
    
    **Validates: Requirement 17.3**
    """
    # 创建出口节点
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "测试有压管道"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.5}
    outlet.flow = 2.0
    outlet.roughness = 0.014
    outlet.station_MC = 200
    
    # 创建分组（缺少进口）
    group = PressurePipeGroup(
        name="测试有压管道",
        inlet_node=None,  # 缺少进口
        outlet_node=outlet,
        inlet_row_index=-1,
        outlet_row_index=1,
        diameter_D=1.5,
        roughness=0.014,
        flow=2.0
    )
    
    # 验证
    is_valid, errors = validate_pressure_pipe_group(group)
    
    assert not is_valid, "缺少进口的分组应验证失败"
    assert len(errors) > 0, "应有错误消息"
    
    error_text = " ".join(errors)
    assert "测试有压管道" in error_text, "错误消息应包含建筑物名称"
    assert "进口" in error_text, "错误消息应指出缺少进口"


def test_validate_group_missing_outlet():
    """
    测试检测缺少出口的分组
    
    **Validates: Requirement 17.4**
    """
    # 创建进口节点
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = "测试有压管道"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 1.5}
    inlet.flow = 2.0
    inlet.roughness = 0.014
    inlet.station_MC = 100
    
    # 创建分组（缺少出口）
    group = PressurePipeGroup(
        name="测试有压管道",
        inlet_node=inlet,
        outlet_node=None,  # 缺少出口
        inlet_row_index=0,
        outlet_row_index=-1,
        diameter_D=1.5,
        roughness=0.014,
        flow=2.0
    )
    
    # 验证
    is_valid, errors = validate_pressure_pipe_group(group)
    
    assert not is_valid, "缺少出口的分组应验证失败"
    assert len(errors) > 0, "应有错误消息"
    
    error_text = " ".join(errors)
    assert "测试有压管道" in error_text, "错误消息应包含建筑物名称"
    assert "出口" in error_text, "错误消息应指出缺少出口"


def test_validate_group_invalid_station_order():
    """
    测试检测里程顺序错误的分组
    
    **Validates: Requirement 18.4**
    """
    # 创建进口节点
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = "测试有压管道"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 1.5}
    inlet.flow = 2.0
    inlet.roughness = 0.014
    inlet.station_MC = 200  # 进口里程大于出口
    
    # 创建出口节点
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "测试有压管道"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.5}
    outlet.flow = 2.0
    outlet.roughness = 0.014
    outlet.station_MC = 100  # 出口里程小于进口
    
    # 创建分组
    group = PressurePipeGroup(
        name="测试有压管道",
        inlet_node=inlet,
        outlet_node=outlet,
        inlet_row_index=0,
        outlet_row_index=1,
        diameter_D=1.5,
        roughness=0.014,
        flow=2.0
    )
    
    # 验证
    is_valid, errors = validate_pressure_pipe_group(group)
    
    assert not is_valid, "里程顺序错误的分组应验证失败"
    assert len(errors) > 0, "应有错误消息"
    
    error_text = " ".join(errors)
    assert "测试有压管道" in error_text, "错误消息应包含建筑物名称"
    assert "里程" in error_text, "错误消息应提到里程"
    assert "200" in error_text and "100" in error_text, "错误消息应包含具体的里程值"


def test_validate_group_invalid_diameter():
    """
    测试检测管径无效的分组
    
    **Validates: Requirement 18.1**
    """
    # 创建进口节点
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = "测试有压管道"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 1.5}
    inlet.flow = 2.0
    inlet.roughness = 0.014
    inlet.station_MC = 100
    
    # 创建出口节点
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "测试有压管道"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.5}
    outlet.flow = 2.0
    outlet.roughness = 0.014
    outlet.station_MC = 200
    
    # 创建分组（管径无效）
    group = PressurePipeGroup(
        name="测试有压管道",
        inlet_node=inlet,
        outlet_node=outlet,
        inlet_row_index=0,
        outlet_row_index=1,
        diameter_D=-1.0,  # 管径无效
        roughness=0.014,
        flow=2.0
    )
    
    # 验证
    is_valid, errors = validate_pressure_pipe_group(group)
    
    assert not is_valid, "管径无效的分组应验证失败"
    assert len(errors) > 0, "应有错误消息"
    
    error_text = " ".join(errors)
    assert "管径" in error_text, "错误消息应提到管径"


def test_validate_group_invalid_roughness():
    """
    测试检测糙率无效的分组
    
    **Validates: Requirement 18.2**
    """
    # 创建进口节点
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = "测试有压管道"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 1.5}
    inlet.flow = 2.0
    inlet.roughness = 0.014
    inlet.station_MC = 100
    
    # 创建出口节点
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "测试有压管道"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.5}
    outlet.flow = 2.0
    outlet.roughness = 0.014
    outlet.station_MC = 200
    
    # 创建分组（糙率无效）
    group = PressurePipeGroup(
        name="测试有压管道",
        inlet_node=inlet,
        outlet_node=outlet,
        inlet_row_index=0,
        outlet_row_index=1,
        diameter_D=1.5,
        roughness=-0.014,  # 糙率无效
        flow=2.0
    )
    
    # 验证
    is_valid, errors = validate_pressure_pipe_group(group)
    
    assert not is_valid, "糙率无效的分组应验证失败"
    assert len(errors) > 0, "应有错误消息"
    
    error_text = " ".join(errors)
    assert "糙率" in error_text, "错误消息应提到糙率"


def test_validate_group_invalid_flow():
    """
    测试检测流量无效的分组
    
    **Validates: Requirement 18.3**
    """
    # 创建进口节点
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = "测试有压管道"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 1.5}
    inlet.flow = 2.0
    inlet.roughness = 0.014
    inlet.station_MC = 100
    
    # 创建出口节点
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "测试有压管道"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.5}
    outlet.flow = 2.0
    outlet.roughness = 0.014
    outlet.station_MC = 200
    
    # 创建分组（流量无效）
    group = PressurePipeGroup(
        name="测试有压管道",
        inlet_node=inlet,
        outlet_node=outlet,
        inlet_row_index=0,
        outlet_row_index=1,
        diameter_D=1.5,
        roughness=0.014,
        flow=0.0  # 流量无效
    )
    
    # 验证
    is_valid, errors = validate_pressure_pipe_group(group)
    
    assert not is_valid, "流量无效的分组应验证失败"
    assert len(errors) > 0, "应有错误消息"
    
    error_text = " ".join(errors)
    assert "流量" in error_text, "错误消息应提到流量"


def test_validate_group_multiple_errors():
    """
    测试检测分组的多个错误
    
    验证所有错误都被报告
    """
    # 创建进口节点
    inlet = ChannelNode()
    inlet.structure_type = StructureType.from_string("有压管道")
    inlet.name = "测试有压管道"
    inlet.in_out = InOutType.INLET
    inlet.section_params = {"D": 1.5}
    inlet.flow = 2.0
    inlet.roughness = 0.014
    inlet.station_MC = 200  # 错误1：进口里程大于出口
    
    # 创建出口节点
    outlet = ChannelNode()
    outlet.structure_type = StructureType.from_string("有压管道")
    outlet.name = "测试有压管道"
    outlet.in_out = InOutType.OUTLET
    outlet.section_params = {"D": 1.5}
    outlet.flow = 2.0
    outlet.roughness = 0.014
    outlet.station_MC = 100
    
    # 创建分组（多个错误）
    group = PressurePipeGroup(
        name="测试有压管道",
        inlet_node=inlet,
        outlet_node=outlet,
        inlet_row_index=0,
        outlet_row_index=1,
        diameter_D=-1.0,  # 错误2：管径无效
        roughness=0.0,  # 错误3：糙率无效
        flow=-2.0  # 错误4：流量无效
    )
    
    # 验证
    is_valid, errors = validate_pressure_pipe_group(group)
    
    assert not is_valid, "有多个错误的分组应验证失败"
    assert len(errors) == 4, f"应报告4个错误，实际报告了{len(errors)}个"
    
    # 验证所有错误都被报告
    error_text = " ".join(errors)
    assert "管径" in error_text, "应报告管径错误"
    assert "糙率" in error_text, "应报告糙率错误"
    assert "流量" in error_text, "应报告流量错误"
    assert "里程" in error_text, "应报告里程顺序错误"


def test_error_message_format():
    """
    测试错误消息格式
    
    验证错误消息包含必要的信息（行号、具体问题）
    """
    node = ChannelNode()
    node.structure_type = StructureType.from_string("有压管道")
    node.name = "测试有压管道"
    node.in_out = InOutType.INLET
    node.section_params = {"D": -1.5}
    node.flow = 2.0
    node.roughness = 0.014
    
    # 验证
    is_valid, errors = validate_pressure_pipe_node(node, row_index=42)
    
    assert not is_valid
    assert len(errors) > 0
    
    # 检查错误消息格式
    error_msg = errors[0]
    assert "第 42 行" in error_msg, "错误消息应包含'第 X 行'格式的行号"
    assert "管径" in error_msg, "错误消息应指出具体问题"
    assert "-1.5" in error_msg, "错误消息应包含具体的无效值"


if __name__ == "__main__":
    # 运行所有测试
    import pytest
    pytest.main([__file__, "-v"])
