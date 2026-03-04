# -*- coding: utf-8 -*-
"""
明渠段插入逻辑 - 单元测试

**Validates: Requirements 6.1, 6.5**

测试具体示例和边界情况
"""

import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "推求水面线"))

import pytest
from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from core.calculator import WaterProfileCalculator


class TestOpenChannelInsertion:
    """明渠段插入逻辑单元测试"""
    
    def setup_method(self):
        """测试前准备"""
        self.settings = ProjectSettings()
        self.calculator = WaterProfileCalculator(self.settings)
    
    def test_insert_open_channel_when_distance_large(self):
        """
        测试：里程差大于渐变段长度之和时插入明渠段
        
        **Validates: Requirements 6.1**
        """
        # 创建有压管道出口节点
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = "有压管道1"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.5}
        outlet.station_MC = 100.0
        outlet.water_depth = 2.0
        
        # 创建隧洞进口节点
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("隧洞-圆形")
        inlet.name = "隧洞1"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 2.0}
        inlet.station_MC = 150.0  # 距离 50m
        inlet.water_depth = 2.0
        
        # 调用判断函数
        result = self.calculator._should_insert_open_channel(outlet, inlet)
        
        # 渐变段长度：出口 6*2.0=12m, 进口 5*2.0=10m, 总计 22m
        # 里程差 50m > 22m，应插入明渠段
        assert result['need_open_channel'] == True, "里程差大于渐变段长度之和时应插入明渠段"
        assert result['need_transition_1'] == True, "应插入出口渐变段"
        assert result['need_transition_2'] == True, "应插入进口渐变段"
        assert result['skip_loss_transition_1'] == True, "有压管道侧渐变段应标记 skip_loss=True"
        assert result['skip_loss_transition_2'] == False, "隧洞侧渐变段应标记 skip_loss=False"
        
        # 验证可用长度计算
        expected_available = 50.0 - (result['transition_length_1'] + result['transition_length_2'])
        assert abs(result['available_length'] - expected_available) < 0.001, \
            f"明渠段可用长度应为 {expected_available}m, 实际 {result['available_length']}m"
        assert result['available_length'] > 0, "可用长度应为正数"
    
    def test_no_open_channel_when_distance_small(self):
        """
        测试：里程差小于渐变段长度之和时不插入明渠段
        
        **Validates: Requirements 6.1**
        """
        # 创建有压管道出口节点
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = "有压管道1"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.5}
        outlet.station_MC = 100.0
        outlet.water_depth = 2.0
        
        # 创建隧洞进口节点
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("隧洞-圆形")
        inlet.name = "隧洞1"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 2.0}
        inlet.station_MC = 115.0  # 距离 15m
        inlet.water_depth = 2.0
        
        # 调用判断函数
        result = self.calculator._should_insert_open_channel(outlet, inlet)
        
        # 渐变段长度：出口 12m, 进口 10m, 总计 22m
        # 里程差 15m < 22m，不应插入明渠段
        assert result['need_open_channel'] == False, "里程差小于渐变段长度之和时不应插入明渠段"
        assert result['available_length'] < 0, "可用长度应为负数"
    
    def test_available_length_calculation(self):
        """
        测试：明渠段可用长度计算
        
        **Validates: Requirements 6.5**
        """
        # 创建有压管道出口节点
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = "有压管道1"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.5}
        outlet.station_MC = 100.0
        outlet.water_depth = 2.5
        
        # 创建渡槽进口节点
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("渡槽-U形")
        inlet.name = "渡槽1"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 2.0}
        inlet.station_MC = 200.0  # 距离 100m
        inlet.water_depth = 3.0
        
        # 调用判断函数
        result = self.calculator._should_insert_open_channel(outlet, inlet)
        
        # 验证可用长度 = 里程差 - 渐变段长度之和
        distance = 100.0
        total_transition_length = result['transition_length_1'] + result['transition_length_2']
        expected_available = distance - total_transition_length
        
        assert result['need_open_channel'] == True, "应插入明渠段"
        assert abs(result['available_length'] - expected_available) < 0.001, \
            f"可用长度计算错误: 期望 {expected_available}m, 实际 {result['available_length']}m"
    
    def test_pressure_pipe_to_tunnel(self):
        """
        测试：有压管道出口 → 隧洞进口
        
        **Validates: Requirements 6.2, 6.6**
        """
        # 创建有压管道出口节点
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = "有压管道1"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.5}
        outlet.station_MC = 100.0
        outlet.water_depth = 2.0
        
        # 创建隧洞进口节点
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("隧洞-圆形")
        inlet.name = "隧洞1"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 2.0}
        inlet.station_MC = 150.0
        inlet.water_depth = 2.0
        
        # 调用判断函数
        result = self.calculator._should_insert_open_channel(outlet, inlet)
        
        # 验证有压管道侧渐变段标记 skip_loss=True
        assert result['skip_loss_transition_1'] == True, "有压管道出口侧渐变段应标记 skip_loss=True"
        assert result['skip_loss_transition_2'] == False, "隧洞进口侧渐变段应标记 skip_loss=False"
    
    def test_pressure_pipe_to_aqueduct(self):
        """
        测试：有压管道出口 → 渡槽进口
        
        **Validates: Requirements 6.2, 6.6**
        """
        # 创建有压管道出口节点
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = "有压管道1"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.5}
        outlet.station_MC = 100.0
        outlet.water_depth = 2.0
        
        # 创建渡槽进口节点
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("渡槽-U形")
        inlet.name = "渡槽1"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 2.0}
        inlet.station_MC = 150.0
        inlet.water_depth = 2.0
        
        # 调用判断函数
        result = self.calculator._should_insert_open_channel(outlet, inlet)
        
        # 验证有压管道侧渐变段标记 skip_loss=True
        assert result['skip_loss_transition_1'] == True, "有压管道出口侧渐变段应标记 skip_loss=True"
        assert result['skip_loss_transition_2'] == False, "渡槽进口侧渐变段应标记 skip_loss=False"
    
    def test_pressure_pipe_to_culvert(self):
        """
        测试：有压管道出口 → 矩形暗涵进口
        
        **Validates: Requirements 6.2, 6.6**
        """
        # 创建有压管道出口节点
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = "有压管道1"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.5}
        outlet.station_MC = 100.0
        outlet.water_depth = 2.0
        
        # 创建矩形暗涵进口节点
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("矩形暗涵")
        inlet.name = "暗涵1"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"b": 2.0, "h": 1.5}
        inlet.station_MC = 150.0
        inlet.water_depth = 1.5
        
        # 调用判断函数
        result = self.calculator._should_insert_open_channel(outlet, inlet)
        
        # 验证有压管道侧渐变段标记 skip_loss=True
        assert result['skip_loss_transition_1'] == True, "有压管道出口侧渐变段应标记 skip_loss=True"
        assert result['skip_loss_transition_2'] == False, "暗涵进口侧渐变段应标记 skip_loss=False"
    
    def test_tunnel_to_pressure_pipe(self):
        """
        测试：隧洞出口 → 有压管道进口
        
        **Validates: Requirements 6.3, 6.6**
        """
        # 创建隧洞出口节点
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("隧洞-圆形")
        outlet.name = "隧洞1"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 2.0}
        outlet.station_MC = 100.0
        outlet.water_depth = 2.0
        
        # 创建有压管道进口节点
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("有压管道")
        inlet.name = "有压管道1"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 1.5}
        inlet.station_MC = 150.0
        inlet.water_depth = 2.0
        
        # 调用判断函数
        result = self.calculator._should_insert_open_channel(outlet, inlet)
        
        # 验证有压管道侧渐变段标记 skip_loss=True
        assert result['skip_loss_transition_1'] == False, "隧洞出口侧渐变段应标记 skip_loss=False"
        assert result['skip_loss_transition_2'] == True, "有压管道进口侧渐变段应标记 skip_loss=True"
    
    def test_aqueduct_to_pressure_pipe(self):
        """
        测试：渡槽出口 → 有压管道进口
        
        **Validates: Requirements 6.3, 6.6**
        """
        # 创建渡槽出口节点
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("渡槽-U形")
        outlet.name = "渡槽1"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 2.0}
        outlet.station_MC = 100.0
        outlet.water_depth = 2.0
        
        # 创建有压管道进口节点
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("有压管道")
        inlet.name = "有压管道1"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 1.5}
        inlet.station_MC = 150.0
        inlet.water_depth = 2.0
        
        # 调用判断函数
        result = self.calculator._should_insert_open_channel(outlet, inlet)
        
        # 验证有压管道侧渐变段标记 skip_loss=True
        assert result['skip_loss_transition_1'] == False, "渡槽出口侧渐变段应标记 skip_loss=False"
        assert result['skip_loss_transition_2'] == True, "有压管道进口侧渐变段应标记 skip_loss=True"
    
    def test_pressure_pipe_to_pressure_pipe_different_names(self):
        """
        测试：有压管道 → 有压管道（不同名称）
        
        **Validates: Requirements 6.2, 6.3, 6.6**
        """
        # 创建有压管道1出口节点
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = "有压管道1"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.5}
        outlet.station_MC = 100.0
        outlet.water_depth = 2.0
        
        # 创建有压管道2进口节点
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("有压管道")
        inlet.name = "有压管道2"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 1.5}
        inlet.station_MC = 150.0
        inlet.water_depth = 2.0
        
        # 调用判断函数
        result = self.calculator._should_insert_open_channel(outlet, inlet)
        
        # 不同名称的有压管道应插入渐变段，两侧都标记 skip_loss=True
        assert result['need_transition_1'] == True, "不同名称有压管道之间应插入出口渐变段"
        assert result['need_transition_2'] == True, "不同名称有压管道之间应插入进口渐变段"
        assert result['skip_loss_transition_1'] == True, "有压管道出口侧渐变段应标记 skip_loss=True"
        assert result['skip_loss_transition_2'] == True, "有压管道进口侧渐变段应标记 skip_loss=True"
    
    def test_edge_case_zero_distance(self):
        """
        测试：边界情况 - 里程差为零
        """
        # 创建有压管道出口节点
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = "有压管道1"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.5}
        outlet.station_MC = 100.0
        outlet.water_depth = 2.0
        
        # 创建隧洞进口节点（相同里程）
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("隧洞-圆形")
        inlet.name = "隧洞1"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 2.0}
        inlet.station_MC = 100.0  # 相同里程
        inlet.water_depth = 2.0
        
        # 调用判断函数
        result = self.calculator._should_insert_open_channel(outlet, inlet)
        
        # 里程差为零，不应插入明渠段
        assert result['need_open_channel'] == False, "里程差为零时不应插入明渠段"
        assert result['distance'] == 0.0, "里程差应为零"
    
    def test_edge_case_very_small_distance(self):
        """
        测试：边界情况 - 里程差非常小
        """
        # 创建有压管道出口节点
        outlet = ChannelNode()
        outlet.structure_type = StructureType.from_string("有压管道")
        outlet.name = "有压管道1"
        outlet.in_out = InOutType.OUTLET
        outlet.section_params = {"D": 1.5}
        outlet.station_MC = 100.0
        outlet.water_depth = 2.0
        
        # 创建隧洞进口节点（距离很小）
        inlet = ChannelNode()
        inlet.structure_type = StructureType.from_string("隧洞-圆形")
        inlet.name = "隧洞1"
        inlet.in_out = InOutType.INLET
        inlet.section_params = {"D": 2.0}
        inlet.station_MC = 100.5  # 距离 0.5m
        inlet.water_depth = 2.0
        
        # 调用判断函数
        result = self.calculator._should_insert_open_channel(outlet, inlet)
        
        # 里程差很小，不应插入明渠段
        assert result['need_open_channel'] == False, "里程差很小时不应插入明渠段"
        assert result['available_length'] < 0, "可用长度应为负数"


if __name__ == "__main__":
    print("运行明渠段插入逻辑单元测试...")
    print("运行命令: pytest tests/test_open_channel_insertion_unit.py -v")
    pytest.main([__file__, "-v"])
