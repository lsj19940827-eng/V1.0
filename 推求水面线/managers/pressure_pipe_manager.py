# -*- coding: utf-8 -*-
"""
有压管道数据持久化管理器

管理有压管道计算数据的保存和加载。
"""

import json
import os
from datetime import datetime
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict, field


@dataclass
class PressurePipeConfig:
    """单个有压管道的配置数据"""
    name: str = ""                          # 管道名称
    Q: float = 0.0                          # 设计流量 (m³/s)
    D: float = 0.0                          # 管径 (m)
    material_key: str = ""                  # 管材键名
    local_loss_ratio: float = 0.15          # 局部损失比例（简化模式用）
    
    # 渐变段参数
    inlet_transition_form: str = "反弯扭曲面"   # 进口渐变段型式
    outlet_transition_form: str = "反弯扭曲面"  # 出口渐变段型式
    inlet_transition_zeta: float = 0.10         # 进口渐变段损失系数
    outlet_transition_zeta: float = 0.20        # 出口渐变段损失系数
    
    # 流速参数
    upstream_velocity: float = 0.0          # 上游渠道流速 v₁ (m/s)
    downstream_velocity: float = 0.0        # 下游渠道流速 v₃ (m/s)
    pipe_velocity: float = 0.0              # 管内流速 V (m/s)
    
    # IP点信息
    ip_points: List[Dict[str, Any]] = None  # IP点列表 [{x, y, turn_radius, turn_angle}, ...]
    plan_total_length: float = 0.0          # 管道总长度 (m)
    
    # 纵断面变坡点节点（从DXF导入，可选）
    longitudinal_nodes: List[Dict[str, Any]] = None
    
    # 计算结果
    friction_loss: Optional[float] = None           # 沿程水头损失 (m)
    total_bend_loss: Optional[float] = None         # 弯头局部损失合计 (m)
    inlet_transition_loss: Optional[float] = None   # 进口渐变段损失 (m)
    outlet_transition_loss: Optional[float] = None  # 出口渐变段损失 (m)
    total_head_loss: Optional[float] = None         # 总水头损失 (m)
    calculated_at: str = ""                         # 计算时间
    data_mode: str = ""                             # 数据模式（平面模式 / 空间模式（平面+纵断面））
    
    def __post_init__(self):
        if self.ip_points is None:
            self.ip_points = []
        if self.longitudinal_nodes is None:
            self.longitudinal_nodes = []


class PressurePipeManager:
    """
    有压管道数据持久化管理器
    
    管理多个有压管道的参数配置和计算结果的持久化存储。
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
            "pipes": {}
        }
        
        # 尝试加载现有配置
        if self._config_path and os.path.exists(self._config_path):
            self.load_config()
    
    def _get_config_path(self, project_path: str) -> str:
        """
        根据项目路径生成配置文件路径
        
        配置文件命名规则：项目文件名 + ".ppipe.json"
        如果没有项目路径，使用默认路径
        """
        if not project_path:
            # 使用默认路径（在程序目录下）
            import sys
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            return os.path.join(base_dir, "ppipe_config.json")
        
        # 去掉原始扩展名，添加 .ppipe.json
        base_name = os.path.splitext(project_path)[0]
        return base_name + ".ppipe.json"
    
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
                "pipes": {}
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
            print(f"加载有压管道配置失败: {e}")
            self._config = {
                "version": "1.0",
                "last_modified": "",
                "pipes": {}
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
            print(f"保存有压管道配置失败: {e}")
    
    def get_pipe_config(self, pipe_name: str) -> Optional[PressurePipeConfig]:
        """
        获取指定管道的配置
        
        Args:
            pipe_name: 管道名称
            
        Returns:
            配置对象，如果不存在返回None
        """
        pipes = self._config.get("pipes", {})
        if pipe_name not in pipes:
            return None
        
        data = pipes[pipe_name]
        return PressurePipeConfig(
            name=data.get("name", pipe_name),
            Q=data.get("Q", 0.0),
            D=data.get("D", 0.0),
            material_key=data.get("material_key", ""),
            local_loss_ratio=data.get("local_loss_ratio", 0.15),
            inlet_transition_form=data.get("inlet_transition_form", "反弯扭曲面"),
            outlet_transition_form=data.get("outlet_transition_form", "反弯扭曲面"),
            inlet_transition_zeta=data.get("inlet_transition_zeta", 0.10),
            outlet_transition_zeta=data.get("outlet_transition_zeta", 0.20),
            upstream_velocity=data.get("upstream_velocity", 0.0),
            downstream_velocity=data.get("downstream_velocity", 0.0),
            pipe_velocity=data.get("pipe_velocity", 0.0),
            ip_points=data.get("ip_points", []),
            plan_total_length=data.get("plan_total_length", 0.0),
            longitudinal_nodes=data.get("longitudinal_nodes", []),
            friction_loss=data.get("friction_loss"),
            total_bend_loss=data.get("total_bend_loss"),
            inlet_transition_loss=data.get("inlet_transition_loss"),
            outlet_transition_loss=data.get("outlet_transition_loss"),
            total_head_loss=data.get("total_head_loss"),
            calculated_at=data.get("calculated_at", ""),
            data_mode=data.get("data_mode", ""),
        )
    
    def set_pipe_config(self, pipe_name: str, config: PressurePipeConfig):
        """
        设置指定管道的配置
        
        Args:
            pipe_name: 管道名称
            config: 配置对象
        """
        if "pipes" not in self._config:
            self._config["pipes"] = {}
        
        self._config["pipes"][pipe_name] = {
            "name": config.name,
            "Q": config.Q,
            "D": config.D,
            "material_key": config.material_key,
            "local_loss_ratio": config.local_loss_ratio,
            "inlet_transition_form": config.inlet_transition_form,
            "outlet_transition_form": config.outlet_transition_form,
            "inlet_transition_zeta": config.inlet_transition_zeta,
            "outlet_transition_zeta": config.outlet_transition_zeta,
            "upstream_velocity": config.upstream_velocity,
            "downstream_velocity": config.downstream_velocity,
            "pipe_velocity": config.pipe_velocity,
            "ip_points": config.ip_points,
            "plan_total_length": config.plan_total_length,
            "longitudinal_nodes": config.longitudinal_nodes,
            "friction_loss": config.friction_loss,
            "total_bend_loss": config.total_bend_loss,
            "inlet_transition_loss": config.inlet_transition_loss,
            "outlet_transition_loss": config.outlet_transition_loss,
            "total_head_loss": config.total_head_loss,
            "calculated_at": config.calculated_at,
            "data_mode": config.data_mode,
        }
        
        self.save_config()
    
    def set_result(self, pipe_name: str, total_head_loss: float, 
                   friction_loss: float = 0, total_bend_loss: float = 0,
                   inlet_transition_loss: float = 0, outlet_transition_loss: float = 0,
                   pipe_velocity: float = 0, plan_total_length: float = 0,
                   data_mode: str = "", longitudinal_nodes: Optional[List[Dict[str, Any]]] = None):
        """
        保存计算结果
        
        Args:
            pipe_name: 管道名称
            total_head_loss: 总水头损失 (m)
            friction_loss: 沿程水头损失 (m)
            total_bend_loss: 弯头局部损失合计 (m)
            inlet_transition_loss: 进口渐变段损失 (m)
            outlet_transition_loss: 出口渐变段损失 (m)
            pipe_velocity: 管内流速 (m/s)
            plan_total_length: 管道总长度 (m)
        """
        if "pipes" not in self._config:
            self._config["pipes"] = {}
        
        if pipe_name not in self._config["pipes"]:
            self._config["pipes"][pipe_name] = {"name": pipe_name}
        
        self._config["pipes"][pipe_name].update({
            "total_head_loss": total_head_loss,
            "friction_loss": friction_loss,
            "total_bend_loss": total_bend_loss,
            "inlet_transition_loss": inlet_transition_loss,
            "outlet_transition_loss": outlet_transition_loss,
            "pipe_velocity": pipe_velocity,
            "plan_total_length": plan_total_length,
            "data_mode": data_mode or "",
            "longitudinal_nodes": longitudinal_nodes or [],
            "calculated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        
        self.save_config()
    
    def get_result(self, pipe_name: str) -> Optional[float]:
        """
        获取指定管道的总水头损失
        
        Args:
            pipe_name: 管道名称
            
        Returns:
            总水头损失值，如果不存在返回None
        """
        pipes = self._config.get("pipes", {})
        if pipe_name not in pipes:
            return None
        return pipes[pipe_name].get("total_head_loss")
    
    def get_all_results(self) -> Dict[str, float]:
        """
        获取所有管道的水头损失结果
        
        Returns:
            {管道名称: 总水头损失} 字典
        """
        results = {}
        pipes = self._config.get("pipes", {})
        for name, data in pipes.items():
            if data.get("total_head_loss") is not None:
                results[name] = data["total_head_loss"]
        return results
    
    def remove_pipe(self, pipe_name: str):
        """删除指定管道的配置"""
        if "pipes" in self._config and pipe_name in self._config["pipes"]:
            del self._config["pipes"][pipe_name]
            self.save_config()
    
    def get_all_pipe_names(self) -> List[str]:
        """获取所有管道名称"""
        return list(self._config.get("pipes", {}).keys())
    
    def has_result(self, pipe_name: str) -> bool:
        """检查指定管道是否有计算结果"""
        pipes = self._config.get("pipes", {})
        if pipe_name not in pipes:
            return False
        return pipes[pipe_name].get("total_head_loss") is not None
    
    def clear_all(self):
        """清空所有配置"""
        self._config = {
            "version": "1.0",
            "last_modified": "",
            "pipes": {}
        }
        self.save_config()

    def to_dict(self) -> Dict[str, Any]:
        """将 manager 内部数据序列化为字典（用于存入 .qxproj）"""
        import copy
        return copy.deepcopy(self._config)

    def from_dict(self, data: Dict[str, Any]):
        """从字典恢复 manager 内部数据（用于从 .qxproj 加载）"""
        if not data or not isinstance(data, dict):
            return
        import copy
        self._config = copy.deepcopy(data)


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    print("=== 有压管道管理器测试 ===")
    
    # 创建管理器
    manager = PressurePipeManager()
    
    # 创建配置
    config = PressurePipeConfig(
        name="测试管道",
        Q=2.0,
        D=1.0,
        material_key="HDPE管",
        upstream_velocity=1.0,
        downstream_velocity=1.0,
        ip_points=[
            {"x": 0, "y": 0, "turn_radius": 0, "turn_angle": 0},
            {"x": 100, "y": 50, "turn_radius": 3.0, "turn_angle": 30},
            {"x": 200, "y": 50, "turn_radius": 0, "turn_angle": 0},
        ],
        plan_total_length=212.0,
    )
    
    # 保存配置
    manager.set_pipe_config("测试管道", config)
    print("配置已保存")
    
    # 保存计算结果
    manager.set_result(
        "测试管道",
        total_head_loss=0.5,
        friction_loss=0.3,
        total_bend_loss=0.1,
        inlet_transition_loss=0.05,
        outlet_transition_loss=0.05,
        pipe_velocity=2.5,
        plan_total_length=212.0,
    )
    print("计算结果已保存")
    
    # 读取配置
    loaded_config = manager.get_pipe_config("测试管道")
    if loaded_config:
        print(f"读取配置: {loaded_config.name}, Q={loaded_config.Q}, D={loaded_config.D}")
        print(f"总水头损失: {loaded_config.total_head_loss}")
    
    # 获取所有结果
    results = manager.get_all_results()
    print(f"所有结果: {results}")
