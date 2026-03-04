# -*- coding: utf-8 -*-
"""
数据模型定义

定义推求水面线程序中使用的核心数据结构。
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from .enums import StructureType, InOutType


@dataclass
class ChannelNode:
    """
    渠道节点数据模型
    
    存储每一行数据，包括输入参数、几何计算结果和水力计算结果。
    """
    # ========== 基础输入字段 ==========
    flow_section: str = ""                      # 流量段
    name: str = ""                              # 建筑物名称
    structure_type: Optional[StructureType] = None  # 结构形式
    x: float = 0.0                              # 坐标X
    y: float = 0.0                              # 坐标Y
    turn_radius: float = 0.0                    # 转弯半径（m），每行可不同
    
    # ========== 自动计算字段 ==========
    in_out: InOutType = InOutType.NORMAL        # 进出口标识（自动判断）
    ip_number: int = 0                          # IP编号（IP0, IP1...）
    
    # ========== 水力输入字段（每行可不同） ==========
    flow: float = 0.0                           # 流量 Q（m³/s）
    roughness: float = 0.014                    # 糙率 n
    
    # ========== 断面参数（可从多渠段导入或手动输入） ==========
    section_params: Dict[str, float] = field(default_factory=dict)
    # 可能的键: 底宽b, 水深h, 边坡m, 直径D, 内半径R 等
    
    # ========== 几何计算结果 ==========
    azimuth: float = 0.0                        # 方位角（°）
    turn_angle: float = 0.0                     # 转角（°）
    tangent_length: float = 0.0                 # 切线长（m）
    arc_length: float = 0.0                     # 弧长（m）
    curve_length: float = 0.0                   # 弯道长度（m）= EC - BC
    straight_distance: float = 0.0              # IP直线间距（m）
    station_ip: float = 0.0                     # IP点桩号（m）
    station_BC: float = 0.0                     # 弯前BC桩号（m）
    station_MC: float = 0.0                     # 里程MC桩号（m）
    station_EC: float = 0.0                     # 弯末EC桩号（m）
    check_pre_curve: float = 0.0                # 复核弯前长度（m）= L72-J72，检查起弯点是否超过上一IP
    check_post_curve: float = 0.0               # 复核弯后长度（m）= L73-J72，检查出弯点是否超过下一IP
    check_total_length: float = 0.0             # 复核总长度（m）= L72-J71-J72，夹直线长度
    
    # ========== 水力计算结果 ==========
    slope_i: float = 0.0                        # 底坡 i
    bottom_elevation: float = 0.0               # 渠底高程（m）
    top_elevation: float = 0.0                  # 渠顶高程（m）= 渠底高程 + 结构高度
    structure_height: float = 0.0               # 结构高度（m），根据结构类型不同取值不同
    water_depth: float = 0.0                    # 水深 h（m）
    water_level: float = 0.0                    # 水位 Z（m）
    velocity: float = 0.0                       # 流速 v（m/s）
    head_loss_friction: float = 0.0             # 沿程水头损失（m）
    head_loss_bend: float = 0.0                 # 弯道水头损失（m）
    head_loss_local: float = 0.0                # 局部水头损失（m）
    head_loss_reserve: float = 0.0              # 预留水头损失（m），用户可自定义输入
    head_loss_gate: float = 0.0                 # 过闸水头损失（m）
    head_loss_siphon: float = 0.0               # 倒虹吸水头损失（m）
    head_loss_total: float = 0.0                # 总水头损失（m）
    head_loss_cumulative: float = 0.0           # 累计总水头损失（m）
    
    # ========== 计算详情（用于双击展示） ==========
    bend_calc_details: Dict[str, Any] = field(default_factory=dict)      # 弯道损失计算详情
    friction_calc_details: Dict[str, Any] = field(default_factory=dict)  # 沿程损失计算详情
    siphon_outlet_elev_details: Dict[str, Any] = field(default_factory=dict)  # 倒虹吸出口渠底高程计算详情（公式10.3.6）
    
    # ========== 特殊标记 ==========
    is_inverted_siphon: bool = False            # 是否为倒虹吸（水损需外部导入）
    is_pressure_pipe: bool = False              # 是否为有压管道（水损需外部导入）
    external_head_loss: Optional[float] = None  # 外部导入的水头损失（倒虹吸/有压管道用）
    is_diversion_gate: bool = False             # 是否为闸类结构（分水闸/分水口/节制闸/泄水闸等，仅过闸水头损失）
    is_auto_inserted_channel: bool = False      # 是否为自动插入的明渠段（渐变段间连接段，不分配IP编号）
    stat_length: float = 0.0                    # 统计用长度（结构类型汇总用，不参与导出）
    
    # ========== 渐变段相关字段 ==========
    is_transition: bool = False                 # 是否为渐变段专用行
    transition_skip_loss: bool = False          # 占位渐变段，不计算水头损失（倒虹吸渐变段已含在倒虹吸水损中）
    transition_type: str = ""                   # 渐变段类型："进口"或"出口"
    transition_form: str = ""                   # 渐变段形式（如"曲线形反弯扭曲面"）
    transition_zeta: float = 0.0                # 渐变段局部损失系数ζ
    transition_theta: float = 0.0               # 直线形扭曲面的θ角度
    transition_length: float = 0.0              # 渐变段长度L（m）
    transition_water_width_1: float = 0.0       # 渐变段起始水面宽度B1（m）
    transition_water_width_2: float = 0.0       # 渐变段末端水面宽度B2（m）
    transition_velocity_1: float = 0.0          # 渐变段起始流速v1（m/s）
    transition_velocity_2: float = 0.0          # 渐变段末端流速v2（m/s）
    transition_avg_R: float = 0.0               # 渐变段平均水力半径R_avg（m）
    transition_avg_v: float = 0.0               # 渐变段平均流速v_avg（m/s）
    transition_head_loss_local: float = 0.0     # 渐变段局部水头损失h_j1（m）
    transition_head_loss_friction: float = 0.0  # 渐变段沿程水头损失h_f（m）
    head_loss_transition: float = 0.0           # 渐变段总水头损失（h_j1 + h_f）
    transition_calc_details: Dict[str, Any] = field(default_factory=dict)  # 计算详情（用于LaTeX显示）
    transition_length_calc_details: Dict[str, Any] = field(default_factory=dict)  # 渐变段长度计算详情（用于双击展示）
    
    def get_structure_type_str(self) -> str:
        """获取结构形式的字符串表示"""
        return self.structure_type.value if self.structure_type else ""
    
    def get_in_out_str(self) -> str:
        """获取进出口标识的字符串表示"""
        return self.in_out.value if self.in_out else ""
    
    def get_ip_str(self) -> str:
        """
        获取IP编号的字符串表示
        
        逻辑：
        - 基础部分：IP + 编号
        - 只有当进出口为"进"或"出"时才添加扩展信息：
          - 添加 " " + 建筑物名称 + 结构形式缩写 + 进出口
          - 结构形式缩写：隧洞→"隧"，倒虹吸→"倒"，渡槽→"渡"，其他→""
        - 中间的行（没有进出口标识）只显示IPxx
        """
        base = f"IP{self.ip_number}"
        
        # 只有当进出口为"进"或"出"时才添加扩展信息
        if self.name and self.in_out in (InOutType.INLET, InOutType.OUTLET):
            # 矩形暗涵的IP点不显示进/出后缀
            struct_str = self.structure_type.value if self.structure_type else ""
            if "暗涵" in struct_str:
                return base
            
            # 获取结构形式缩写
            struct_abbr = ""
            if self.structure_type:
                if "隧洞" in struct_str or struct_str == "隧洞":
                    struct_abbr = "隧"
                elif "倒虹吸" in struct_str or struct_str == "倒虹吸":
                    struct_abbr = "倒"
                elif "渡槽" in struct_str or struct_str == "渡槽":
                    struct_abbr = "渡"
                elif "有压管道" in struct_str or struct_str == "有压管道":
                    struct_abbr = "压"
            
            # 获取进出口简写
            in_out_str = ""
            if self.in_out == InOutType.INLET:
                in_out_str = "进"
            elif self.in_out == InOutType.OUTLET:
                in_out_str = "出"
            
            return f"{base} {self.name}{struct_abbr}{in_out_str}"
        
        return base
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于导出）"""
        return {
            "流量段": self.flow_section,
            "建筑物名称": self.name,
            "结构形式": self.get_structure_type_str(),
            "进出口判断": self.get_in_out_str(),
            "IP": self.get_ip_str(),
            "X": self.x,
            "Y": self.y,
            "转弯半径": self.turn_radius,
            "转角": self.turn_angle,
            "切线长": self.tangent_length,
            "弧长": self.arc_length,
            "弯道长度": self.curve_length,
            "IP直线间距": self.straight_distance,
            "IP点桩号": self.station_ip,
            "弯前BC": self.station_BC,
            "里程MC": self.station_MC,
            "弯末EC": self.station_EC,
            "复核弯前长度": self.check_pre_curve,
            "复核弯后长度": self.check_post_curve,
            "复核总长度": self.check_total_length,
            "流量": self.flow,
            "糙率": self.roughness,
            "比降": self.slope_i,
            "水深": self.water_depth,
            "流速": self.velocity,
            "渐变段长度": self.transition_length,
            "水头损失": self.head_loss_total,
            "水位": self.water_level,
            "渠底高程": self.bottom_elevation,
            "渠顶高程": self.top_elevation,
            "结构高度": self.structure_height,
        }
    
    def to_project_dict(self) -> Dict[str, Any]:
        """
        转换为项目保存用的完整字典（包含所有字段）
        
        用于 .qxproj 项目文件的序列化，包含所有计算结果和详情。
        """
        return {
            # ========== 基础输入字段 ==========
            "flow_section": self.flow_section,
            "name": self.name,
            "structure_type": self.structure_type.value if self.structure_type else None,
            "x": self.x,
            "y": self.y,
            "turn_radius": self.turn_radius,
            
            # ========== 自动计算字段 ==========
            "in_out": self.in_out.value if self.in_out else "",
            "ip_number": self.ip_number,
            
            # ========== 水力输入字段 ==========
            "flow": self.flow,
            "roughness": self.roughness,
            "section_params": self.section_params,
            
            # ========== 几何计算结果 ==========
            "azimuth": self.azimuth,
            "turn_angle": self.turn_angle,
            "tangent_length": self.tangent_length,
            "arc_length": self.arc_length,
            "curve_length": self.curve_length,
            "straight_distance": self.straight_distance,
            "station_ip": self.station_ip,
            "station_BC": self.station_BC,
            "station_MC": self.station_MC,
            "station_EC": self.station_EC,
            "check_pre_curve": self.check_pre_curve,
            "check_post_curve": self.check_post_curve,
            "check_total_length": self.check_total_length,
            
            # ========== 水力计算结果 ==========
            "slope_i": self.slope_i,
            "bottom_elevation": self.bottom_elevation,
            "top_elevation": self.top_elevation,
            "structure_height": self.structure_height,
            "water_depth": self.water_depth,
            "water_level": self.water_level,
            "velocity": self.velocity,
            "head_loss_friction": self.head_loss_friction,
            "head_loss_bend": self.head_loss_bend,
            "head_loss_local": self.head_loss_local,
            "head_loss_reserve": self.head_loss_reserve,
            "head_loss_gate": self.head_loss_gate,
            "head_loss_siphon": self.head_loss_siphon,
            "head_loss_total": self.head_loss_total,
            "head_loss_cumulative": self.head_loss_cumulative,
            
            # ========== 计算详情 ==========
            "bend_calc_details": self.bend_calc_details,
            "friction_calc_details": self.friction_calc_details,
            "siphon_outlet_elev_details": self.siphon_outlet_elev_details,
            
            # ========== 特殊标记 ==========
            "is_inverted_siphon": self.is_inverted_siphon,
            "is_pressure_pipe": self.is_pressure_pipe,
            "external_head_loss": self.external_head_loss,
            "is_diversion_gate": self.is_diversion_gate,
            "is_auto_inserted_channel": self.is_auto_inserted_channel,
            "stat_length": self.stat_length,
            
            # ========== 渐变段相关字段 ==========
            "is_transition": self.is_transition,
            "transition_skip_loss": self.transition_skip_loss,
            "transition_type": self.transition_type,
            "transition_form": self.transition_form,
            "transition_zeta": self.transition_zeta,
            "transition_theta": self.transition_theta,
            "transition_length": self.transition_length,
            "transition_water_width_1": self.transition_water_width_1,
            "transition_water_width_2": self.transition_water_width_2,
            "transition_velocity_1": self.transition_velocity_1,
            "transition_velocity_2": self.transition_velocity_2,
            "transition_avg_R": self.transition_avg_R,
            "transition_avg_v": self.transition_avg_v,
            "transition_head_loss_local": self.transition_head_loss_local,
            "transition_head_loss_friction": self.transition_head_loss_friction,
            "head_loss_transition": self.head_loss_transition,
            "transition_calc_details": self.transition_calc_details,
            "transition_length_calc_details": self.transition_length_calc_details,
        }
    
    @staticmethod
    def from_project_dict(d: Dict[str, Any]) -> 'ChannelNode':
        """
        从项目字典创建 ChannelNode 对象
        
        用于 .qxproj 项目文件的反序列化，支持向后兼容（缺失字段使用默认值）。
        
        Args:
            d: 序列化的字典数据
            
        Returns:
            ChannelNode 对象
        """
        node = ChannelNode()
        
        # ========== 基础输入字段 ==========
        node.flow_section = d.get("flow_section", "")
        node.name = d.get("name", "")
        
        # 结构形式：从字符串转枚举
        struct_str = d.get("structure_type")
        if struct_str:
            try:
                node.structure_type = StructureType.from_string(struct_str)
            except ValueError:
                node.structure_type = None
        
        node.x = d.get("x", 0.0)
        node.y = d.get("y", 0.0)
        node.turn_radius = d.get("turn_radius", 0.0)
        
        # ========== 自动计算字段 ==========
        in_out_str = d.get("in_out", "")
        node.in_out = InOutType.from_string(in_out_str)
        node.ip_number = d.get("ip_number", 0)
        
        # ========== 水力输入字段 ==========
        node.flow = d.get("flow", 0.0)
        node.roughness = d.get("roughness", 0.014)
        node.section_params = d.get("section_params", {})
        
        # ========== 几何计算结果 ==========
        node.azimuth = d.get("azimuth", 0.0)
        node.turn_angle = d.get("turn_angle", 0.0)
        node.tangent_length = d.get("tangent_length", 0.0)
        node.arc_length = d.get("arc_length", 0.0)
        node.curve_length = d.get("curve_length", 0.0)
        node.straight_distance = d.get("straight_distance", 0.0)
        node.station_ip = d.get("station_ip", 0.0)
        node.station_BC = d.get("station_BC", 0.0)
        node.station_MC = d.get("station_MC", 0.0)
        node.station_EC = d.get("station_EC", 0.0)
        node.check_pre_curve = d.get("check_pre_curve", 0.0)
        node.check_post_curve = d.get("check_post_curve", 0.0)
        node.check_total_length = d.get("check_total_length", 0.0)
        
        # ========== 水力计算结果 ==========
        node.slope_i = d.get("slope_i", 0.0)
        node.bottom_elevation = d.get("bottom_elevation", 0.0)
        node.top_elevation = d.get("top_elevation", 0.0)
        node.structure_height = d.get("structure_height", 0.0)
        node.water_depth = d.get("water_depth", 0.0)
        node.water_level = d.get("water_level", 0.0)
        node.velocity = d.get("velocity", 0.0)
        node.head_loss_friction = d.get("head_loss_friction", 0.0)
        node.head_loss_bend = d.get("head_loss_bend", 0.0)
        node.head_loss_local = d.get("head_loss_local", 0.0)
        node.head_loss_reserve = d.get("head_loss_reserve", 0.0)
        node.head_loss_gate = d.get("head_loss_gate", 0.0)
        node.head_loss_siphon = d.get("head_loss_siphon", 0.0)
        node.head_loss_total = d.get("head_loss_total", 0.0)
        node.head_loss_cumulative = d.get("head_loss_cumulative", 0.0)
        
        # ========== 计算详情 ==========
        node.bend_calc_details = d.get("bend_calc_details", {})
        node.friction_calc_details = d.get("friction_calc_details", {})
        node.siphon_outlet_elev_details = d.get("siphon_outlet_elev_details", {})
        
        # ========== 特殊标记 ==========
        node.is_inverted_siphon = d.get("is_inverted_siphon", False)
        node.is_pressure_pipe = d.get("is_pressure_pipe", False)
        node.external_head_loss = d.get("external_head_loss")
        node.is_diversion_gate = d.get("is_diversion_gate", False)
        node.is_auto_inserted_channel = d.get("is_auto_inserted_channel", False)
        node.stat_length = d.get("stat_length", 0.0)
        
        # ========== 渐变段相关字段 ==========
        node.is_transition = d.get("is_transition", False)
        node.transition_skip_loss = d.get("transition_skip_loss", False)
        node.transition_type = d.get("transition_type", "")
        node.transition_form = d.get("transition_form", "")
        node.transition_zeta = d.get("transition_zeta", 0.0)
        node.transition_theta = d.get("transition_theta", 0.0)
        node.transition_length = d.get("transition_length", 0.0)
        node.transition_water_width_1 = d.get("transition_water_width_1", 0.0)
        node.transition_water_width_2 = d.get("transition_water_width_2", 0.0)
        node.transition_velocity_1 = d.get("transition_velocity_1", 0.0)
        node.transition_velocity_2 = d.get("transition_velocity_2", 0.0)
        node.transition_avg_R = d.get("transition_avg_R", 0.0)
        node.transition_avg_v = d.get("transition_avg_v", 0.0)
        node.transition_head_loss_local = d.get("transition_head_loss_local", 0.0)
        node.transition_head_loss_friction = d.get("transition_head_loss_friction", 0.0)
        node.head_loss_transition = d.get("head_loss_transition", 0.0)
        node.transition_calc_details = d.get("transition_calc_details", {})
        node.transition_length_calc_details = d.get("transition_length_calc_details", {})
        
        return node


@dataclass
class ProjectSettings:
    """
    项目基础设置
    
    存储渠道的全局参数。
    支持多流量段：design_flows 和 max_flows 为流量列表。
    """
    channel_name: str = ""                      # 渠道名称
    channel_level: str = "支渠"                 # 渠道级别
    start_station: float = 0.0                  # 起始桩号（m）
    design_flow: float = 0.0                    # 设计流量 Q（m³/s）- 单值（向后兼容）
    max_flow: float = 0.0                       # 加大流量 Qmax（m³/s）- 单值（向后兼容）
    design_flows: List[float] = field(default_factory=list)  # 多流量段设计流量
    max_flows: List[float] = field(default_factory=list)     # 多流量段加大流量
    start_water_level: float = 0.0              # 起始断面水位（m）
    turn_radius: float = 0.0                    # 转弯半径 R（m）
    roughness: float = 0.014                    # 糙率 n（默认0.014，用于明渠/渡槽/隧洞/暗涵等）
    siphon_roughness: float = 0.014              # 倒虹吸糙率 n（默认0.014，倒虹吸管道专用）
    
    # ========== 渡槽/隧洞渐变段设置（表K.1.2） ==========
    transition_inlet_form: str = "曲线形反弯扭曲面"   # 渡槽/隧洞进口渐变段形式
    transition_inlet_zeta: float = 0.10               # 渡槽/隧洞进口渐变段局部损失系数
    transition_outlet_form: str = "曲线形反弯扭曲面"  # 渡槽/隧洞出口渐变段形式
    transition_outlet_zeta: float = 0.20              # 渡槽/隧洞出口渐变段局部损失系数
    open_channel_transition_form: str = "曲线形反弯扭曲面"  # 明渠渐变段形式（如梯形-矩形）
    open_channel_transition_zeta: float = 0.10        # 明渠渐变段局部损失系数
    
    # ========== 倒虹吸渐变段设置（表L.1.2） ==========
    siphon_transition_inlet_form: str = "反弯扭曲面"   # 倒虹吸进口渐变段型式
    siphon_transition_outlet_form: str = "反弯扭曲面"  # 倒虹吸出口渐变段型式
    siphon_transition_inlet_zeta: float = 0.10         # 倒虹吸进口渐变段局部损失系数
    siphon_transition_outlet_zeta: float = 0.20        # 倒虹吸出口渐变段局部损失系数
    
    # ========== 倒虹吸平面转弯半径设置 ==========
    siphon_turn_radius_n: float = 3.0                  # 倒虹吸转弯半径倍数n（R = n × D，D为管径）
    
    def get_station_prefix(self) -> str:
        """
        获取桩号前缀
        
        根据渠道名称第一个字和渠道级别生成桩号前缀
        例如：渠道名称为"南峰寺"，级别为"支渠"，则返回"南支"
        
        Returns:
            桩号前缀字符串
        """
        from config.constants import CHANNEL_LEVEL_ABBR_MAP
        
        # 获取渠道名称第一个字
        first_char = self.channel_name[0] if self.channel_name else ""
        
        # 获取级别缩写
        level_abbr = CHANNEL_LEVEL_ABBR_MAP.get(self.channel_level, "支")
        
        return f"{first_char}{level_abbr}"
    
    @staticmethod
    def format_station(station_value: float, prefix: str = "") -> str:
        """
        将桩号数值格式化为标准显示格式
        
        格式：前缀+公里数+米数，例如"南支15+020.073"
        - 公里数：整数部分除以1000
        - 米数：剩余部分，保留3位小数，整数部分补零到3位
        
        Args:
            station_value: 桩号数值（米）
            prefix: 桩号前缀
            
        Returns:
            格式化后的桩号字符串
        """
        if station_value < 0:
            station_value = 0.0
        
        # 计算公里数和米数
        km = int(station_value / 1000)
        meters = station_value % 1000
        
        # 格式化米数：整数部分3位，小数部分3位
        # 例如：20.073 -> "020.073"
        meters_str = f"{meters:07.3f}"  # 总宽度7位，包括小数点，3位小数
        
        return f"{prefix}{km}+{meters_str}"
    
    def validate(self) -> tuple:
        """
        验证设置参数的有效性
        
        支持多流量段验证：如果 design_flows 和 max_flows 有值，则使用列表进行验证。
        
        Returns:
            (is_valid, error_message): 验证结果和错误信息
        """
        errors = []
        
        # 使用多流量段列表或单值进行验证
        design_flows = self.design_flows if self.design_flows else ([self.design_flow] if self.design_flow > 0 else [])
        max_flows = self.max_flows if self.max_flows else ([self.max_flow] if self.max_flow > 0 else [])
        
        if not design_flows or all(q <= 0 for q in design_flows):
            errors.append("设计流量必须大于0")
        if not max_flows or all(q <= 0 for q in max_flows):
            errors.append("加大流量必须大于0")
        
        # 验证加大流量不小于对应的设计流量
        if design_flows and max_flows:
            for i, (dq, mq) in enumerate(zip(design_flows, max_flows)):
                if mq < dq:
                    errors.append(f"流量段{i+1}的加大流量({mq})应大于等于设计流量({dq})")
        
        if self.turn_radius < 0:
            errors.append("转弯半径不能为负数")
        if self.roughness <= 0:
            errors.append("糙率必须大于0")
        
        if errors:
            return False, "; ".join(errors)
        return True, ""
    
    def get_flow_for_segment(self, segment: int) -> tuple:
        """
        获取指定流量段的设计流量和加大流量
        
        Args:
            segment: 流量段编号（从1开始）
        
        Returns:
            (设计流量, 加大流量) 元组
        """
        design_flows = self.design_flows if self.design_flows else ([self.design_flow] if self.design_flow > 0 else [])
        max_flows = self.max_flows if self.max_flows else ([self.max_flow] if self.max_flow > 0 else [])
        
        # 获取设计流量
        if 1 <= segment <= len(design_flows):
            design_q = design_flows[segment - 1]
        elif design_flows:
            design_q = design_flows[-1]
        else:
            design_q = 0.0
        
        # 获取加大流量
        if 1 <= segment <= len(max_flows):
            max_q = max_flows[segment - 1]
        elif max_flows:
            max_q = max_flows[-1]
        else:
            max_q = 0.0
        
        return (design_q, max_q)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "渠道名称": self.channel_name,
            "渠道级别": self.channel_level,
            "起始桩号": self.start_station,
            "设计流量": self.design_flow,
            "加大流量": self.max_flow,
            "设计流量列表": self.design_flows,
            "加大流量列表": self.max_flows,
            "起始水位": self.start_water_level,
            "转弯半径": self.turn_radius,
            "糙率": self.roughness,
            "渡槽/隧洞进口渐变段形式": self.transition_inlet_form,
            "渡槽/隧洞进口渐变段局部损失系数": self.transition_inlet_zeta,
            "渡槽/隧洞出口渐变段形式": self.transition_outlet_form,
            "渡槽/隧洞出口渐变段局部损失系数": self.transition_outlet_zeta,
            "明渠渐变段形式": self.open_channel_transition_form,
            "明渠渐变段局部损失系数": self.open_channel_transition_zeta,
            "倒虹吸进口渐变段型式": self.siphon_transition_inlet_form,
            "倒虹吸出口渐变段型式": self.siphon_transition_outlet_form,
            "倒虹吸进口渐变段局部损失系数": self.siphon_transition_inlet_zeta,
            "倒虹吸出口渐变段局部损失系数": self.siphon_transition_outlet_zeta,
            "倒虹吸转弯半径倍数n": self.siphon_turn_radius_n,
        }
    
    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'ProjectSettings':
        """
        从字典创建 ProjectSettings 对象
        
        用于 .qxproj 项目文件的反序列化，支持向后兼容（缺失字段使用默认值）。
        
        Args:
            d: 序列化的字典数据
            
        Returns:
            ProjectSettings 对象
        """
        settings = ProjectSettings()
        
        # 基础信息
        settings.channel_name = d.get("渠道名称", d.get("channel_name", ""))
        settings.channel_level = d.get("渠道级别", d.get("channel_level", "支渠"))
        settings.start_station = d.get("起始桩号", d.get("start_station", 0.0))
        
        # 流量参数
        settings.design_flow = d.get("设计流量", d.get("design_flow", 0.0))
        settings.max_flow = d.get("加大流量", d.get("max_flow", 0.0))
        settings.design_flows = d.get("设计流量列表", d.get("design_flows", []))
        settings.max_flows = d.get("加大流量列表", d.get("max_flows", []))
        settings.start_water_level = d.get("起始水位", d.get("start_water_level", 0.0))
        
        # 渠道参数
        settings.turn_radius = d.get("转弯半径", d.get("turn_radius", 0.0))
        settings.roughness = d.get("糙率", d.get("roughness", 0.014))
        settings.siphon_roughness = d.get("倒虹吸糙率", d.get("siphon_roughness", 0.014))
        
        # 渡槽/隧洞渐变段设置
        settings.transition_inlet_form = d.get("渡槽/隧洞进口渐变段形式", 
                                                d.get("transition_inlet_form", "曲线形反弯扭曲面"))
        settings.transition_inlet_zeta = d.get("渡槽/隧洞进口渐变段局部损失系数", 
                                                d.get("transition_inlet_zeta", 0.10))
        settings.transition_outlet_form = d.get("渡槽/隧洞出口渐变段形式", 
                                                 d.get("transition_outlet_form", "曲线形反弯扭曲面"))
        settings.transition_outlet_zeta = d.get("渡槽/隧洞出口渐变段局部损失系数", 
                                                 d.get("transition_outlet_zeta", 0.20))
        
        # 明渠渐变段设置
        settings.open_channel_transition_form = d.get("明渠渐变段形式", 
                                                       d.get("open_channel_transition_form", "曲线形反弯扭曲面"))
        settings.open_channel_transition_zeta = d.get("明渠渐变段局部损失系数", 
                                                       d.get("open_channel_transition_zeta", 0.10))
        
        # 倒虹吸渐变段设置
        settings.siphon_transition_inlet_form = d.get("倒虹吸进口渐变段型式", 
                                                       d.get("siphon_transition_inlet_form", "反弯扭曲面"))
        settings.siphon_transition_outlet_form = d.get("倒虹吸出口渐变段型式", 
                                                        d.get("siphon_transition_outlet_form", "反弯扭曲面"))
        settings.siphon_transition_inlet_zeta = d.get("倒虹吸进口渐变段局部损失系数", 
                                                       d.get("siphon_transition_inlet_zeta", 0.10))
        settings.siphon_transition_outlet_zeta = d.get("倒虹吸出口渐变段局部损失系数", 
                                                        d.get("siphon_transition_outlet_zeta", 0.20))
        
        # 倒虹吸转弯半径
        settings.siphon_turn_radius_n = d.get("倒虹吸转弯半径倍数n", 
                                               d.get("siphon_turn_radius_n", 3.0))
        
        return settings


@dataclass
class OpenChannelParams:
    """明渠段参数（供渐变段插入逻辑使用）"""
    name: str = "-"
    structure_type: str = "明渠-梯形"
    bottom_width: float = 0.0
    water_depth: float = 0.0
    side_slope: float = 0.0
    roughness: float = 0.014
    slope_inv: float = 3000.0
    flow: float = 0.0
    flow_section: str = ""
    structure_height: float = 0.0
    arc_radius: float = 0.0    # 圆弧半径（明渠-U形用）
    theta_deg: float = 0.0     # 圆弧圆心角（明渠-U形用）
