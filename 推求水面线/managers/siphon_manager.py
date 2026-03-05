# -*- coding: utf-8 -*-
"""
倒虹吸数据持久化管理器

管理倒虹吸计算数据的保存和加载。
"""

import json
import os
from datetime import datetime
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict


@dataclass
class SiphonConfig:
    """单个倒虹吸的配置数据"""
    name: str = ""                      # 倒虹吸名称
    Q: float = 0.0                      # 设计流量 (m³/s)
    v_guess: float = 2.0                # 拟定流速 (m/s)
    roughness_n: float = 0.014          # 糙率
    
    # 渐变段参数
    inlet_type: str = "曲线形反弯扭曲面"   # 进口渐变段型式
    outlet_type: str = "曲线形反弯扭曲面"  # 出口渐变段型式
    xi_inlet: float = 0.1               # 进口渐变段损失系数
    xi_outlet: float = 0.2              # 出口渐变段损失系数
    v_channel_in: float = 0.0           # 进口渐变段始端流速
    v_pipe_in: float = 0.0              # 进口渐变段末端流速
    v_channel_out: float = 0.0          # 出口渐变段末端流速
    v_pipe_out: float = 0.0             # 出口渐变段始端流速
    
    # 结构段列表
    segments: List[Dict[str, Any]] = None
    
    # 平面段信息（从推求水面线表格自动提取）
    plan_segments: List[Dict[str, Any]] = None    # 平面段列表
    plan_total_length: float = 0.0                # 平面总水平长度 (m)
    
    # 平面IP特征点（用于三维空间合并计算）
    plan_feature_points: List[Dict[str, Any]] = None
    
    # 纵断面变坡点节点（从DXF导入）
    longitudinal_nodes: List[Dict[str, Any]] = None
    
    # 计算结果
    total_head_loss: Optional[float] = None  # 总水头损失（加大流量工况）
    diameter: Optional[float] = None          # 计算管径
    calculated_at: str = ""                   # 计算时间
    
    def __post_init__(self):
        if self.segments is None:
            self.segments = []
        if self.plan_segments is None:
            self.plan_segments = []
        if self.plan_feature_points is None:
            self.plan_feature_points = []
        if self.longitudinal_nodes is None:
            self.longitudinal_nodes = []


class SiphonManager:
    """
    倒虹吸数据持久化管理器
    
    管理多个倒虹吸的参数配置和计算结果的持久化存储。
    """
    
    def __init__(self, project_path: str = None):
        """
        初始化管理器
        
        Args:
            project_path: 项目文件路径（用于生成配置文件路径）
        """
        self._project_path = project_path
        self._config_path = self._get_config_path(project_path)
        self._config: Dict[str, Any] = {
            "version": "1.0",
            "last_modified": "",
            "siphons": {}
        }
        
        # 尝试加载现有配置
        if self._config_path and os.path.exists(self._config_path):
            self.load_config()
    
    def _get_config_path(self, project_path: str) -> str:
        """
        根据项目路径生成配置文件路径
        
        配置文件命名规则：项目文件名 + ".siphon.json"
        如果没有项目路径，使用默认路径
        """
        if not project_path:
            # 使用默认路径（在程序目录下）
            import sys
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            return os.path.join(base_dir, "siphon_config.json")
        
        # 去掉原始扩展名，添加 .siphon.json
        base_name = os.path.splitext(project_path)[0]
        return base_name + ".siphon.json"
    
    def set_project_path(self, project_path: str):
        """设置项目路径并重新加载配置"""
        self._project_path = project_path
        self._config_path = self._get_config_path(project_path)
        if os.path.exists(self._config_path):
            self.load_config()
        else:
            self._config = {
                "version": "1.0",
                "last_modified": "",
                "siphons": {}
            }
    
    def load_config(self) -> Dict[str, Any]:
        """
        加载配置文件
        
        Returns:
            配置字典
        """
        if not self._config_path or not os.path.exists(self._config_path):
            return self._config
        
        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                self._config = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"加载倒虹吸配置失败: {e}")
            self._config = {
                "version": "1.0",
                "last_modified": "",
                "siphons": {}
            }
        
        return self._config
    
    def save_config(self):
        """保存配置到文件"""
        if not self._config_path:
            return
        
        self._config["last_modified"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            # 确保目录存在
            config_dir = os.path.dirname(self._config_path)
            if config_dir and not os.path.exists(config_dir):
                os.makedirs(config_dir)
            
            with open(self._config_path, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"保存倒虹吸配置失败: {e}")
    
    def get_siphon_config(self, siphon_name: str) -> Optional[SiphonConfig]:
        """
        获取指定倒虹吸的配置
        
        Args:
            siphon_name: 倒虹吸名称
            
        Returns:
            倒虹吸配置对象，如果不存在返回 None
        """
        siphons = self._config.get("siphons", {})
        if siphon_name not in siphons:
            return None
        
        data = siphons[siphon_name]
        return SiphonConfig(
            name=siphon_name,
            Q=data.get("Q", 0.0),
            v_guess=data.get("v_guess", 2.0),
            roughness_n=data.get("roughness_n", 0.014),
            inlet_type=data.get("inlet_type", "曲线形反弯扭曲面"),
            outlet_type=data.get("outlet_type", "曲线形反弯扭曲面"),
            xi_inlet=data.get("xi_inlet", 0.1),
            xi_outlet=data.get("xi_outlet", 0.2),
            v_channel_in=data.get("v_channel_in", 0.0),
            v_pipe_in=data.get("v_pipe_in", 0.0),
            v_channel_out=data.get("v_channel_out", 0.0),
            v_pipe_out=data.get("v_pipe_out", 0.0),
            segments=data.get("segments", []),
            plan_segments=data.get("plan_segments", []),
            plan_total_length=data.get("plan_total_length", 0.0),
            plan_feature_points=data.get("plan_feature_points", []),
            longitudinal_nodes=data.get("longitudinal_nodes", []),
            total_head_loss=data.get("total_head_loss"),
            diameter=data.get("diameter"),
            calculated_at=data.get("calculated_at", "")
        )
    
    def set_siphon_config(self, config: SiphonConfig):
        """
        设置倒虹吸配置
        
        Args:
            config: 倒虹吸配置对象
        """
        if "siphons" not in self._config:
            self._config["siphons"] = {}
        
        self._config["siphons"][config.name] = {
            "Q": config.Q,
            "v_guess": config.v_guess,
            "roughness_n": config.roughness_n,
            "inlet_type": config.inlet_type,
            "outlet_type": config.outlet_type,
            "xi_inlet": config.xi_inlet,
            "xi_outlet": config.xi_outlet,
            "v_channel_in": config.v_channel_in,
            "v_pipe_in": config.v_pipe_in,
            "v_channel_out": config.v_channel_out,
            "v_pipe_out": config.v_pipe_out,
            "segments": config.segments,
            "plan_segments": config.plan_segments,
            "plan_total_length": config.plan_total_length,
            "plan_feature_points": config.plan_feature_points,
            "longitudinal_nodes": config.longitudinal_nodes,
            "total_head_loss": config.total_head_loss,
            "diameter": config.diameter,
            "calculated_at": config.calculated_at
        }
    
    def update_siphon_result(self, siphon_name: str, total_head_loss: float,
                            diameter: float = None):
        """
        更新倒虹吸计算结果（使用加大流量工况水损）

        Args:
            siphon_name: 倒虹吸名称
            total_head_loss: 总水头损失（加大流量工况）
            diameter: 计算管径
        """
        if "siphons" not in self._config:
            self._config["siphons"] = {}
        
        if siphon_name not in self._config["siphons"]:
            self._config["siphons"][siphon_name] = {}
        
        self._config["siphons"][siphon_name]["total_head_loss"] = total_head_loss
        if diameter is not None:
            self._config["siphons"][siphon_name]["diameter"] = diameter
        self._config["siphons"][siphon_name]["calculated_at"] = \
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def get_result(self, siphon_name: str) -> Optional[float]:
        """
        获取指定倒虹吸的总水头损失
        
        Args:
            siphon_name: 倒虹吸名称
            
        Returns:
            总水头损失，如果不存在返回 None
        """
        siphons = self._config.get("siphons", {})
        if siphon_name not in siphons:
            return None
        return siphons[siphon_name].get("total_head_loss")
    
    def get_all_results(self) -> Dict[str, float]:
        """
        获取所有倒虹吸的计算结果
        
        Returns:
            {倒虹吸名称: 总水头损失} 字典
        """
        results = {}
        siphons = self._config.get("siphons", {})
        
        for name, data in siphons.items():
            loss = data.get("total_head_loss")
            if loss is not None:
                results[name] = loss
        
        return results
    
    def get_siphon_names(self) -> List[str]:
        """获取所有已保存的倒虹吸名称"""
        return list(self._config.get("siphons", {}).keys())
    
    def remove_siphon(self, siphon_name: str):
        """删除指定倒虹吸的配置"""
        if "siphons" in self._config and siphon_name in self._config["siphons"]:
            del self._config["siphons"][siphon_name]
    
    def clear_all(self):
        """清空所有配置"""
        self._config["siphons"] = {}
    
    @property
    def config_path(self) -> str:
        """获取配置文件路径"""
        return self._config_path
    
    @property
    def last_modified(self) -> str:
        """获取最后修改时间"""
        return self._config.get("last_modified", "")
