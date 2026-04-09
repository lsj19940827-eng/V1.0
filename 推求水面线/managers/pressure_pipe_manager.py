# -*- coding: utf-8 -*-
"""
有压管道数据持久化管理器

管理有压管道计算数据的保存和加载。
"""

import copy
import json
import os
from datetime import datetime
from typing import Dict, Optional, Any, List
from dataclasses import dataclass


@dataclass
class PressurePipeConfig:
    """单个有压管道的配置数据"""
    name: str = ""                          # 管道名称
    base_name: str = ""                    # 基础名称
    member_display_name: str = ""          # 成员展示名称
    dxf_display_name: str = ""             # DXF 展示名称
    member_role: str = ""                  # 链内角色
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
    profile_segments: List[Dict[str, Any]] = None      # 整线纵断面分段（混合整线模式）
    route_key: str = ""                        # 所属整线键
    route_display_name: str = ""               # 整线展示名称
    profile_state: str = ""                    # 纵断面覆盖状态
    start_row_index: int = -1                  # 起始行
    end_row_index: int = -1                    # 结束行
    target_row_index: int = -1                 # 目标写回行
    upstream_row_index: int = -1               # 上游参考行
    applied_to_row_index: int = -1             # 实际写回行
    start_mc: Optional[float] = None           # 起点桩号
    end_mc: Optional[float] = None             # 终点桩号
    is_pressurized_tail_member: bool = False   # 是否末尾承压成员
    segment_geometry_source: str = ""          # 子段几何来源
    tunnel_invert_inlet: Optional[float] = None  # 隧洞进口底高
    tunnel_slope_i: Optional[float] = None     # 隧洞坡降 i
    tunnel_invert_outlet_check: Optional[float] = None  # 隧洞出口底高校核值
    tunnel_section_type: str = ""              # 隧洞断面类型
    tunnel_section_params: Dict[str, Any] = None  # 隧洞断面参数
    turn_n: float = 0.0                       # n 倍数
    turn_R: float = 0.0                       # 平面转弯半径 R(m)
    force_override: bool = False              # 是否强制覆盖表1值
    radius_applied_at: str = ""               # 半径参数应用时间
    
    # 计算结果
    friction_loss: Optional[float] = None           # 沿程水头损失 (m)
    total_bend_loss: Optional[float] = None         # 弯头局部损失合计 (m)
    local_loss: Optional[float] = None              # 局部损失 (m)
    inlet_transition_loss: Optional[float] = None   # 进口渐变段损失 (m)
    outlet_transition_loss: Optional[float] = None  # 出口渐变段损失 (m)
    total_head_loss: Optional[float] = None         # 总水头损失 (m)
    calculated_at: str = ""                         # 计算时间
    data_mode: str = ""                             # 数据模式（平面模式 / 空间模式（平面+纵断面））
    status: str = ""                                # 计算状态
    computed_from_profile_source: str = ""          # 纵断面来源
    
    def __post_init__(self):
        if self.ip_points is None:
            self.ip_points = []
        if self.longitudinal_nodes is None:
            self.longitudinal_nodes = []
        if self.profile_segments is None:
            self.profile_segments = []
        if self.tunnel_section_params is None:
            self.tunnel_section_params = {}


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
            "pipes": {},
            "routes": {},
            "segments": {},
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

    def _ensure_config_sections(self):
        """补齐持久化结构缺失的桶。"""
        if "pipes" not in self._config or not isinstance(self._config.get("pipes"), dict):
            self._config["pipes"] = {}
        if "routes" not in self._config or not isinstance(self._config.get("routes"), dict):
            self._config["routes"] = {}
        if "segments" not in self._config or not isinstance(self._config.get("segments"), dict):
            self._config["segments"] = {}
    
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
                "pipes": {},
                "routes": {},
                "segments": {},
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
                "pipes": {},
                "routes": {},
                "segments": {},
            }
        self._ensure_config_sections()
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
            return self.get_segment_config(pipe_name)

        data = pipes[pipe_name]
        route_key = data.get("route_key", "")
        route_display_name = data.get("route_display_name", "")
        longitudinal_nodes = data.get("longitudinal_nodes", [])
        profile_segments = data.get("profile_segments", [])
        if (not longitudinal_nodes) and route_key:
            route_data = self._config.get("routes", {}).get(route_key, {})
            if isinstance(route_data, dict):
                route_longitudinal_nodes = route_data.get("longitudinal_nodes", [])
                if route_longitudinal_nodes:
                    longitudinal_nodes = route_longitudinal_nodes
                route_profile_segments = route_data.get("profile_segments", [])
                if not profile_segments and route_profile_segments:
                    profile_segments = route_profile_segments
                if not route_display_name:
                    route_display_name = route_data.get("display_name", "")
        return PressurePipeConfig(
            name=data.get("name", pipe_name),
            base_name=data.get("base_name", ""),
            member_display_name=data.get("member_display_name", ""),
            dxf_display_name=data.get("dxf_display_name", ""),
            member_role=data.get("member_role", ""),
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
            longitudinal_nodes=longitudinal_nodes,
            profile_segments=profile_segments,
            route_key=route_key,
            route_display_name=route_display_name,
            profile_state=data.get("profile_state", ""),
            start_row_index=int(data.get("start_row_index", -1) or -1),
            end_row_index=int(data.get("end_row_index", -1) or -1),
            target_row_index=int(data.get("target_row_index", -1) or -1),
            upstream_row_index=int(data.get("upstream_row_index", -1) or -1),
            applied_to_row_index=int(data.get("applied_to_row_index", -1) or -1),
            start_mc=data.get("start_mc"),
            end_mc=data.get("end_mc"),
            is_pressurized_tail_member=bool(data.get("is_pressurized_tail_member", False)),
            segment_geometry_source=data.get("segment_geometry_source", ""),
            tunnel_invert_inlet=data.get("tunnel_invert_inlet"),
            tunnel_slope_i=data.get("tunnel_slope_i"),
            tunnel_invert_outlet_check=data.get("tunnel_invert_outlet_check"),
            tunnel_section_type=data.get("tunnel_section_type", ""),
            tunnel_section_params=data.get("tunnel_section_params", {}),
            turn_n=data.get("turn_n", 0.0),
            turn_R=data.get("turn_R", 0.0),
            force_override=bool(data.get("force_override", False)),
            radius_applied_at=data.get("radius_applied_at", ""),
            friction_loss=data.get("friction_loss"),
            total_bend_loss=data.get("total_bend_loss"),
            local_loss=data.get("local_loss"),
            inlet_transition_loss=data.get("inlet_transition_loss"),
            outlet_transition_loss=data.get("outlet_transition_loss"),
            total_head_loss=data.get("total_head_loss"),
            calculated_at=data.get("calculated_at", ""),
            data_mode=data.get("data_mode", ""),
            status=data.get("status", ""),
            computed_from_profile_source=data.get("computed_from_profile_source", ""),
        )

    def get_segment_config(self, identity: str) -> Optional[PressurePipeConfig]:
        """读取正式保存的连续承压分段记录。"""
        segments = self._config.get("segments", {})
        if identity not in segments:
            return None

        data = segments.get(identity, {}) if isinstance(segments.get(identity), dict) else {}
        route_key = str(data.get("route_key", "") or "").strip()
        route_data = self._config.get("routes", {}).get(route_key, {}) if route_key else {}
        route_display_name = str(
            data.get("route_display_name", "")
            or route_data.get("display_name", "")
            or ""
        ).strip()
        longitudinal_nodes = list(data.get("longitudinal_nodes", []) or [])
        if not longitudinal_nodes and isinstance(route_data, dict):
            longitudinal_nodes = list(route_data.get("longitudinal_nodes", []) or [])
        profile_segments = list(route_data.get("profile_segments", []) or []) if isinstance(route_data, dict) else []

        return PressurePipeConfig(
            name=str(data.get("member_display_name", "") or data.get("name", "") or identity).strip() or identity,
            base_name=str(data.get("base_name", "") or "").strip(),
            member_display_name=str(data.get("member_display_name", "") or "").strip(),
            dxf_display_name=str(data.get("dxf_display_name", "") or "").strip(),
            member_role=str(data.get("member_role", "") or "").strip(),
            Q=float(data.get("Q", 0.0) or 0.0),
            D=float(data.get("D", 0.0) or 0.0),
            material_key=str(data.get("material_key", "") or "").strip(),
            longitudinal_nodes=longitudinal_nodes,
            profile_segments=profile_segments,
            route_key=route_key,
            route_display_name=route_display_name,
            profile_state=str(
                data.get("profile_state", "")
                or route_data.get("profile_state", "")
                or ""
            ).strip(),
            start_row_index=int(data.get("start_row_index", -1) or -1),
            end_row_index=int(data.get("end_row_index", -1) or -1),
            target_row_index=int(data.get("target_row_index", -1) or -1),
            upstream_row_index=int(data.get("upstream_row_index", -1) or -1),
            applied_to_row_index=int(data.get("applied_to_row_index", -1) or -1),
            start_mc=data.get("start_mc"),
            end_mc=data.get("end_mc"),
            is_pressurized_tail_member=bool(data.get("is_pressurized_tail_member", False)),
            friction_loss=data.get("friction_loss"),
            total_bend_loss=data.get("bend_loss", data.get("total_bend_loss")),
            local_loss=data.get("local_loss"),
            total_head_loss=data.get("total_loss", data.get("total_head_loss")),
            calculated_at=str(data.get("calculated_at", "") or "").strip(),
            data_mode=str(data.get("data_mode", "") or "").strip(),
            status=str(data.get("status", "") or "").strip(),
            computed_from_profile_source=str(data.get("computed_from_profile_source", "") or "").strip(),
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
        if "routes" not in self._config:
            self._config["routes"] = {}

        route_key = str(config.route_key or "").strip()
        route_display_name = str(config.route_display_name or "").strip()
        long_nodes_payload = list(config.longitudinal_nodes or [])
        profile_segments_payload = list(config.profile_segments or [])
        if route_key:
            route_bucket = self._config["routes"].setdefault(route_key, {})
            route_bucket["display_name"] = route_display_name or route_bucket.get("display_name", "")
            if long_nodes_payload:
                route_bucket["longitudinal_nodes"] = long_nodes_payload
            if profile_segments_payload:
                route_bucket["profile_segments"] = profile_segments_payload
            pipe_longitudinal_nodes = []
            pipe_profile_segments = []
        else:
            pipe_longitudinal_nodes = long_nodes_payload
            pipe_profile_segments = profile_segments_payload
        
        self._config["pipes"][pipe_name] = {
            "name": config.name,
            "base_name": config.base_name,
            "member_display_name": config.member_display_name,
            "dxf_display_name": config.dxf_display_name,
            "member_role": config.member_role,
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
            "longitudinal_nodes": pipe_longitudinal_nodes,
            "profile_segments": pipe_profile_segments,
            "route_key": route_key,
            "route_display_name": route_display_name,
            "profile_state": config.profile_state,
            "start_row_index": config.start_row_index,
            "end_row_index": config.end_row_index,
            "target_row_index": config.target_row_index,
            "upstream_row_index": config.upstream_row_index,
            "applied_to_row_index": config.applied_to_row_index,
            "start_mc": config.start_mc,
            "end_mc": config.end_mc,
            "is_pressurized_tail_member": bool(config.is_pressurized_tail_member),
            "segment_geometry_source": config.segment_geometry_source,
            "tunnel_invert_inlet": config.tunnel_invert_inlet,
            "tunnel_slope_i": config.tunnel_slope_i,
            "tunnel_invert_outlet_check": config.tunnel_invert_outlet_check,
            "tunnel_section_type": config.tunnel_section_type,
            "tunnel_section_params": config.tunnel_section_params or {},
            "turn_n": config.turn_n,
            "turn_R": config.turn_R,
            "force_override": bool(config.force_override),
            "radius_applied_at": config.radius_applied_at,
            "friction_loss": config.friction_loss,
            "total_bend_loss": config.total_bend_loss,
            "local_loss": config.local_loss,
            "inlet_transition_loss": config.inlet_transition_loss,
            "outlet_transition_loss": config.outlet_transition_loss,
            "total_head_loss": config.total_head_loss,
            "calculated_at": config.calculated_at,
            "data_mode": config.data_mode,
            "status": config.status,
            "computed_from_profile_source": config.computed_from_profile_source,
        }
        
        self.save_config()

    def set_route_longitudinal_nodes(
        self,
        route_key: str,
        longitudinal_nodes: Optional[List[Dict[str, Any]]],
        route_display_name: str = "",
    ):
        """直接写入整线纵断面，供弹窗导入后即时保存。"""
        route_key = str(route_key or "").strip()
        if not route_key:
            return
        self._ensure_config_sections()

        nodes_payload = list(longitudinal_nodes or [])
        route_bucket = self._config["routes"].setdefault(route_key, {})
        route_bucket["display_name"] = str(
            route_display_name or route_bucket.get("display_name", "") or ""
        ).strip()
        route_bucket["longitudinal_nodes"] = nodes_payload

        # 已有关联子段继续保留 route_key/display_name，便于后续导出直接回读整线数据。
        for row in self._config["pipes"].values():
            if not isinstance(row, dict):
                continue
            if str(row.get("route_key", "") or "").strip() != route_key:
                continue
            row["route_key"] = route_key
            row["route_display_name"] = str(
                route_display_name or row.get("route_display_name", "") or route_bucket.get("display_name", "")
            ).strip()
        for row in self._config["segments"].values():
            if not isinstance(row, dict):
                continue
            if str(row.get("route_key", "") or "").strip() != route_key:
                continue
            row["route_key"] = route_key
            row["route_display_name"] = str(
                route_display_name or row.get("route_display_name", "") or route_bucket.get("display_name", "")
            ).strip()

        self.save_config()
    
    def set_result(self, pipe_name: str, total_head_loss: float, 
                   friction_loss: float = 0, total_bend_loss: float = 0,
                   inlet_transition_loss: float = 0, outlet_transition_loss: float = 0,
                   pipe_velocity: float = 0, plan_total_length: float = 0,
                   data_mode: str = "", longitudinal_nodes: Optional[List[Dict[str, Any]]] = None,
                   route_key: str = "", route_display_name: str = "",
                   profile_segments: Optional[List[Dict[str, Any]]] = None):
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
        self._ensure_config_sections()

        if pipe_name not in self._config["pipes"]:
            self._config["pipes"][pipe_name] = {"name": pipe_name}

        existing_row = self._config["pipes"].get(pipe_name, {})
        route_key = str(route_key or existing_row.get("route_key", "") or "").strip()
        route_display_name = str(
            route_display_name
            or existing_row.get("route_display_name", "")
            or self._config.get("routes", {}).get(route_key, {}).get("display_name", "")
            or ""
        ).strip()
        long_nodes_payload = longitudinal_nodes or []
        profile_segments_payload = None if profile_segments is None else list(profile_segments)
        if route_key:
            route_bucket = self._config["routes"].setdefault(route_key, {})
            route_bucket["display_name"] = route_display_name or route_bucket.get("display_name", "")
            route_bucket["longitudinal_nodes"] = long_nodes_payload
            if profile_segments_payload is not None:
                route_bucket["profile_segments"] = profile_segments_payload
            pipe_longitudinal_nodes = []
            pipe_profile_segments = []
        else:
            pipe_longitudinal_nodes = long_nodes_payload
            pipe_profile_segments = (
                profile_segments_payload
                if profile_segments_payload is not None
                else list(existing_row.get("profile_segments", []) or [])
            )

        self._config["pipes"][pipe_name].update({
            "total_head_loss": total_head_loss,
            "friction_loss": friction_loss,
            "total_bend_loss": total_bend_loss,
            "inlet_transition_loss": inlet_transition_loss,
            "outlet_transition_loss": outlet_transition_loss,
            "pipe_velocity": pipe_velocity,
            "plan_total_length": plan_total_length,
            "data_mode": data_mode or "",
            "longitudinal_nodes": pipe_longitudinal_nodes,
            "profile_segments": pipe_profile_segments,
            "route_key": route_key,
            "route_display_name": route_display_name,
            "calculated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        if pipe_name in self._config.get("segments", {}):
            self._config["segments"][pipe_name].update({
                "status": "success",
                "friction_loss": friction_loss,
                "bend_loss": total_bend_loss,
                "total_bend_loss": total_bend_loss,
                "total_loss": total_head_loss,
                "total_head_loss": total_head_loss,
                "computed_from_profile_source": data_mode or self._config["segments"][pipe_name].get("computed_from_profile_source", ""),
                "calculated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            if longitudinal_nodes is not None:
                self._config["segments"][pipe_name]["longitudinal_nodes"] = list(longitudinal_nodes or [])
        
        self.save_config()

    @staticmethod
    def _coerce_snapshot_row_index(value) -> int:
        """把持久化行号安全转成非负整数。"""
        try:
            row_index = int(value)
        except (TypeError, ValueError):
            return -1
        return row_index if row_index >= 0 else -1

    @classmethod
    def _normalize_snapshot_row_range(cls, payload: Dict[str, Any]) -> tuple[int, int]:
        """统一读取 route / segment / pipe 的覆盖行区间。"""
        if not isinstance(payload, dict):
            return -1, -1
        start_row = cls._coerce_snapshot_row_index(payload.get("start_row_index", -1))
        end_row = cls._coerce_snapshot_row_index(payload.get("end_row_index", start_row))
        target_row = cls._coerce_snapshot_row_index(payload.get("target_row_index", -1))
        applied_row = cls._coerce_snapshot_row_index(payload.get("applied_to_row_index", -1))
        if start_row < 0 and target_row >= 0:
            start_row = target_row
        if end_row < 0 and applied_row >= 0:
            end_row = applied_row
        if start_row < 0 and end_row >= 0:
            start_row = end_row
        if end_row < 0 and start_row >= 0:
            end_row = start_row
        if start_row < 0 or end_row < 0:
            return -1, -1
        if end_row < start_row:
            end_row = start_row
        return start_row, end_row

    @staticmethod
    def _snapshot_ranges_overlap(left_range: tuple[int, int], right_range: tuple[int, int]) -> bool:
        """判断两个区间是否重叠。"""
        left_start, left_end = left_range
        right_start, right_end = right_range
        if left_start < 0 or left_end < 0 or right_start < 0 or right_end < 0:
            return False
        return not (left_end < right_start or right_end < left_start)

    @classmethod
    def _snapshot_matches_active_ranges(
        cls,
        payload: Dict[str, Any],
        active_ranges: List[tuple[int, int]],
    ) -> bool:
        """判断历史快照是否属于当前整线活动范围。"""
        payload_range = cls._normalize_snapshot_row_range(payload)
        if payload_range == (-1, -1):
            return False
        for active_range in active_ranges:
            if cls._snapshot_ranges_overlap(payload_range, active_range):
                return True
        return False

    def _clear_pressure_route_snapshots(self, route_payloads: List[Dict[str, Any]]):
        """删除当前整线范围内的旧 route / segment / pipe 快照。"""
        routes_bucket = self._config.get("routes", {})
        segments_bucket = self._config.get("segments", {})
        pipes_bucket = self._config.get("pipes", {})
        if not isinstance(routes_bucket, dict) or not isinstance(segments_bucket, dict) or not isinstance(pipes_bucket, dict):
            return

        active_ranges = []
        current_route_keys = set()
        for payload in list(route_payloads or []):
            if not isinstance(payload, dict):
                continue
            route_key = str(payload.get("route_key", "") or "").strip()
            if route_key:
                current_route_keys.add(route_key)
            row_range = self._normalize_snapshot_row_range(payload)
            if row_range != (-1, -1):
                active_ranges.append(row_range)

        route_keys_to_remove = set(current_route_keys)
        for route_key, payload in list(routes_bucket.items()):
            route_row = payload if isinstance(payload, dict) else {}
            if str(route_key or "").strip() in current_route_keys:
                route_keys_to_remove.add(str(route_key or "").strip())
                continue
            if self._snapshot_matches_active_ranges(route_row, active_ranges):
                route_keys_to_remove.add(str(route_key or "").strip())

        segment_keys_to_remove = set()
        for identity, payload in list(segments_bucket.items()):
            row = payload if isinstance(payload, dict) else {}
            route_key = str(row.get("route_key", "") or "").strip()
            if route_key in route_keys_to_remove or self._snapshot_matches_active_ranges(row, active_ranges):
                segment_keys_to_remove.add(str(identity or "").strip())

        pipe_keys_to_remove = set()
        for identity, payload in list(pipes_bucket.items()):
            row = payload if isinstance(payload, dict) else {}
            route_key = str(row.get("route_key", "") or "").strip()
            if route_key in route_keys_to_remove or self._snapshot_matches_active_ranges(row, active_ranges):
                pipe_keys_to_remove.add(str(identity or "").strip())

        for route_key in route_keys_to_remove:
            routes_bucket.pop(route_key, None)
        for identity in segment_keys_to_remove:
            segments_bucket.pop(identity, None)
        for identity in pipe_keys_to_remove:
            pipes_bucket.pop(identity, None)

    def save_pressure_routes(
        self,
        routes,
        route_profiles: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        segment_results: Optional[List[Dict[str, Any]]] = None,
    ):
        """正式保存连续承压整线与分段结果。"""
        self._ensure_config_sections()
        route_profiles = route_profiles or {}
        save_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        route_payloads = []
        for route in list(routes or []):
            payload = (
                copy.deepcopy(route)
                if isinstance(route, dict)
                else {
                    "route_key": getattr(route, "route_key", ""),
                    "route_display_name": getattr(route, "route_display_name", ""),
                    "channel_level": getattr(route, "channel_level", ""),
                    "start_row_index": getattr(route, "start_row_index", -1),
                    "end_row_index": getattr(route, "end_row_index", -1),
                    "start_mc": getattr(route, "start_mc", 0.0),
                    "end_mc": getattr(route, "end_mc", 0.0),
                    "entered_pressurized_at_row": getattr(route, "entered_pressurized_at_row", -1),
                    "profile_state": getattr(route, "profile_state", ""),
                    "segment_identities": [
                        str(getattr(item, "identity", "") or "").strip()
                        for item in list(getattr(route, "segments", []) or [])
                        if str(getattr(item, "identity", "") or "").strip()
                    ],
                }
            )
            route_key = str(payload.get("route_key", "") or "").strip()
            if route_key:
                route_payloads.append(payload)

        self._clear_pressure_route_snapshots(route_payloads)

        for payload in route_payloads:
            route_key = str(payload.get("route_key", "") or "").strip()
            self._config["routes"][route_key] = {
                "display_name": str(payload.get("route_display_name", "") or route_key).strip(),
                "channel_level": payload.get("channel_level", ""),
                "start_row_index": payload.get("start_row_index", -1),
                "end_row_index": payload.get("end_row_index", -1),
                "start_mc": payload.get("start_mc"),
                "end_mc": payload.get("end_mc"),
                "entered_pressurized_at_row": payload.get("entered_pressurized_at_row", -1),
                "profile_state": str(payload.get("profile_state", "") or "").strip(),
                "segment_identities": list(payload.get("segment_identities", []) or []),
                "longitudinal_nodes": list(route_profiles.get(route_key, []) or []),
            }

        for segment in list(segment_results or []):
            payload = (
                copy.deepcopy(segment)
                if isinstance(segment, dict)
                else {
                    "identity": getattr(segment, "identity", ""),
                    "route_key": getattr(segment, "route_key", ""),
                    "route_display_name": getattr(segment, "route_display_name", ""),
                    "base_name": getattr(segment, "base_name", ""),
                    "member_display_name": getattr(segment, "member_display_name", ""),
                    "dxf_display_name": getattr(segment, "dxf_display_name", ""),
                    "structure_type": getattr(segment, "structure_type", ""),
                    "member_role": getattr(segment, "member_role", ""),
                    "start_row_index": getattr(segment, "start_row_index", -1),
                    "end_row_index": getattr(segment, "end_row_index", -1),
                    "target_row_index": getattr(segment, "target_row_index", -1),
                    "upstream_row_index": getattr(segment, "upstream_row_index", -1),
                    "applied_to_row_index": getattr(segment, "applied_to_row_index", -1),
                    "start_mc": getattr(segment, "start_mc", None),
                    "end_mc": getattr(segment, "end_mc", None),
                    "is_pressurized_tail_member": getattr(segment, "is_pressurized_tail_member", False),
                    "status": getattr(segment, "status", ""),
                    "friction_loss": getattr(segment, "friction_loss", None),
                    "bend_loss": getattr(segment, "bend_loss", None),
                    "local_loss": getattr(segment, "local_loss", None),
                    "total_loss": getattr(segment, "total_loss", None),
                    "note": getattr(segment, "note", ""),
                    "computed_from_profile_source": getattr(segment, "computed_from_profile_source", ""),
                    "profile_state": getattr(segment, "profile_state", ""),
                    "longitudinal_nodes": list(getattr(segment, "longitudinal_nodes", []) or []),
                }
            )
            identity = str(payload.get("identity", "") or "").strip()
            if not identity:
                continue
            route_key = str(payload.get("route_key", "") or "").strip()
            route_bucket = self._config["routes"].get(route_key, {}) if route_key else {}
            route_display_name = str(
                payload.get("route_display_name", "")
                or route_bucket.get("display_name", "")
                or ""
            ).strip()
            segment_bucket = {
                "identity": identity,
                "name": str(
                    payload.get("member_display_name", "")
                    or payload.get("base_name", "")
                    or identity
                ).strip(),
                "base_name": str(payload.get("base_name", "") or "").strip(),
                "member_display_name": str(payload.get("member_display_name", "") or "").strip(),
                "dxf_display_name": str(payload.get("dxf_display_name", "") or "").strip(),
                "route_key": route_key,
                "route_display_name": route_display_name,
                "structure_type": str(payload.get("structure_type", "") or "").strip(),
                "member_role": str(payload.get("member_role", "") or "").strip(),
                "start_row_index": payload.get("start_row_index", -1),
                "end_row_index": payload.get("end_row_index", -1),
                "target_row_index": payload.get("target_row_index", -1),
                "upstream_row_index": payload.get("upstream_row_index", -1),
                "applied_to_row_index": payload.get("applied_to_row_index", -1),
                "start_mc": payload.get("start_mc"),
                "end_mc": payload.get("end_mc"),
                "is_pressurized_tail_member": bool(payload.get("is_pressurized_tail_member", False)),
                "status": str(payload.get("status", "") or "").strip(),
                "friction_loss": payload.get("friction_loss"),
                "bend_loss": payload.get("bend_loss", payload.get("total_bend_loss")),
                "total_bend_loss": payload.get("bend_loss", payload.get("total_bend_loss")),
                "local_loss": payload.get("local_loss"),
                "total_loss": payload.get("total_loss", payload.get("total_head_loss")),
                "total_head_loss": payload.get("total_loss", payload.get("total_head_loss")),
                "note": str(payload.get("note", "") or "").strip(),
                "computed_from_profile_source": str(payload.get("computed_from_profile_source", "") or "").strip(),
                "profile_state": str(payload.get("profile_state", "") or "").strip(),
                "longitudinal_nodes": list(payload.get("longitudinal_nodes", []) or []),
                "calculated_at": save_at,
            }
            self._config["segments"][identity] = segment_bucket
            self._config["pipes"][identity] = {
                "name": segment_bucket["name"],
                "base_name": segment_bucket["base_name"],
                "member_display_name": segment_bucket["member_display_name"],
                "dxf_display_name": segment_bucket["dxf_display_name"],
                "member_role": segment_bucket["member_role"],
                "route_key": route_key,
                "route_display_name": route_display_name,
                "start_row_index": segment_bucket["start_row_index"],
                "end_row_index": segment_bucket["end_row_index"],
                "target_row_index": segment_bucket["target_row_index"],
                "upstream_row_index": segment_bucket["upstream_row_index"],
                "applied_to_row_index": segment_bucket["applied_to_row_index"],
                "start_mc": segment_bucket["start_mc"],
                "end_mc": segment_bucket["end_mc"],
                "is_pressurized_tail_member": segment_bucket["is_pressurized_tail_member"],
                "status": segment_bucket["status"],
                "friction_loss": segment_bucket["friction_loss"],
                "total_bend_loss": segment_bucket["total_bend_loss"],
                "local_loss": segment_bucket["local_loss"],
                "total_head_loss": segment_bucket["total_head_loss"],
                "computed_from_profile_source": segment_bucket["computed_from_profile_source"],
                "profile_state": segment_bucket["profile_state"],
                "calculated_at": save_at,
                "longitudinal_nodes": [],
            }

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
        segments = self._config.get("segments", {})
        if pipe_name not in pipes and pipe_name not in segments:
            return None
        row = pipes.get(pipe_name) or segments.get(pipe_name) or {}
        return row.get("total_head_loss", row.get("total_loss"))
    
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
        segments = self._config.get("segments", {})
        for name, data in segments.items():
            if name in results:
                continue
            if data.get("total_loss") is not None:
                results[name] = data["total_loss"]
        return results
    
    def remove_pipe(self, pipe_name: str):
        """删除指定管道的配置"""
        if "pipes" in self._config and pipe_name in self._config["pipes"]:
            del self._config["pipes"][pipe_name]
        if "segments" in self._config and pipe_name in self._config["segments"]:
            del self._config["segments"][pipe_name]
        self.save_config()
    
    def get_all_pipe_names(self) -> List[str]:
        """获取所有管道名称"""
        names = list(self._config.get("pipes", {}).keys())
        for name in self._config.get("segments", {}).keys():
            if name not in names:
                names.append(name)
        return names
    
    def has_result(self, pipe_name: str) -> bool:
        """检查指定管道是否有计算结果"""
        pipes = self._config.get("pipes", {})
        segments = self._config.get("segments", {})
        if pipe_name not in pipes and pipe_name not in segments:
            return False
        row = pipes.get(pipe_name) or segments.get(pipe_name) or {}
        return row.get("total_head_loss") is not None or row.get("total_loss") is not None
    
    def clear_all(self):
        """清空所有配置"""
        self._config = {
            "version": "1.0",
            "last_modified": "",
            "pipes": {},
            "routes": {},
            "segments": {},
        }
        self.save_config()

    def to_dict(self) -> Dict[str, Any]:
        """将 manager 内部数据序列化为字典（用于存入 .qxproj）"""
        return copy.deepcopy(self._config)

    def from_dict(self, data: Dict[str, Any]):
        """从字典恢复 manager 内部数据（用于从 .qxproj 加载）"""
        if not data or not isinstance(data, dict):
            return
        self._config = copy.deepcopy(data)
        if "pipes" not in self._config or not isinstance(self._config.get("pipes"), dict):
            self._config["pipes"] = {}
        if "routes" not in self._config or not isinstance(self._config.get("routes"), dict):
            self._config["routes"] = {}
        if "segments" not in self._config or not isinstance(self._config.get("segments"), dict):
            self._config["segments"] = {}


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
