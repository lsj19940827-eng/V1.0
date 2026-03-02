# -*- coding: utf-8 -*-
"""
倒虹吸水力计算软件 - 数据模型层
定义全局参数、结构段、空间节点等核心数据结构
"""

import math
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Tuple, Optional


class SegmentDirection(Enum):
    """结构段方向枚举 —— 区分通用构件、平面段和纵断面段"""
    COMMON = "通用"             # 通用构件（进/出水口、拦污栅、闸门槽、旁通管等），仅贡献ξ
    PLAN = "平面"               # 平面段（水平转弯，从推求水面线表格自动提取）
    LONGITUDINAL = "纵断面"     # 纵断面段（竖向剖面，从DXF导入或手动输入）


class TurnType(Enum):
    """转弯类型枚举"""
    NONE = "无"
    ARC = "圆弧"        # 有转弯半径的圆弧型转弯（平面圆曲线/纵断面竖曲线/fillet）
    FOLD = "折线"        # 无转弯半径的折线型转弯


class SegmentType(Enum):
    """结构段类型枚举"""
    INLET = "进水口"
    STRAIGHT = "直管"
    BEND = "弯管"
    FOLD = "折管"
    TRASH_RACK = "拦污栅"
    GATE_SLOT = "闸门槽"
    BYPASS_PIPE = "旁通管"  # 冲沙、放空、进人孔等
    PIPE_TRANSITION = "管道渐变段"  # 压力管道渐变段 ξjb（收缩0.05/扩散0.10）
    OTHER = "其他"
    OUTLET = "出水口"


# 通用构件类型集合 —— 几乎所有倒虹吸都包含，仅贡献局部阻力系数ξ，不涉及几何线形
COMMON_SEGMENT_TYPES = {
    SegmentType.INLET,
    SegmentType.OUTLET,
    SegmentType.TRASH_RACK,
    SegmentType.GATE_SLOT,
    SegmentType.BYPASS_PIPE,
    SegmentType.PIPE_TRANSITION,
    SegmentType.OTHER,
}


def is_common_type(segment_type: SegmentType) -> bool:
    """判断某个结构段类型是否属于通用构件（不涉及平面/纵断面几何线形）"""
    return segment_type in COMMON_SEGMENT_TYPES


class V2Strategy(Enum):
    """进口渐变段末端流速 v₂ 计算策略枚举"""
    AUTO_PIPE = "自动（= 管道流速）"        # v₂ = 管道实际流速 Q/(πD²/4)，推荐
    V1_PLUS_02 = "v₁ + 0.2"               # v₂ = v₁ + 0.2，经验增量法
    SECTION_CALC = "由断面参数计算"          # v₂ = Q / [(B + m×h) × h]
    MANUAL = "手动输入"                     # 用户直接填写


class GradientType(Enum):
    """渐变段类型枚举"""
    NONE = "无"
    REVERSE_BEND = "反弯扭曲面"
    QUARTER_ARC = "1/4圆弧"
    SQUARE_HEAD = "方头型"
    LINEAR_TWIST = "直线扭曲面"


class InletOutletShape(Enum):
    """进水口形状枚举（表L.1.4-2）"""
    FULLY_ROUNDED = "进口完全修圆"      # ξ = 0.05~0.10
    SLIGHTLY_ROUNDED = "进口稍微修圆"   # ξ = 0.20~0.25
    NOT_ROUNDED = "进口没有修圆"        # ξ = 0.50


# 进水口形状对应的局部阻力系数（表L.1.4-2）
INLET_SHAPE_COEFFICIENTS = {
    InletOutletShape.FULLY_ROUNDED: (0.05, 0.10),      # 范围 0.05~0.10，默认取中值
    InletOutletShape.SLIGHTLY_ROUNDED: (0.20, 0.25),   # 范围 0.20~0.25
    InletOutletShape.NOT_ROUNDED: (0.50, 0.50),        # 固定值 0.50
}


class TrashRackBarShape(Enum):
    """拦污栅栅条形状枚举（表 L.1.4-1）"""
    RECTANGULAR = "矩形"
    ROUNDED_HEAD = "单侧圆头"
    CIRCULAR = "圆形"
    OVAL = "双侧圆头"
    TRAPEZOID = "倒梯形单侧圆头"
    PEAR_SHAPE = "梨形/流线型"
    SHARP_TAIL = "两端尖锐型"


@dataclass
class GlobalParameters:
    """全局参数对象"""
    Q: float = 0.0                      # 设计流量 (m³/s)
    v_guess: float = 0.0                # 拟定流速 (m/s)
    roughness_n: float = 0.014          # 糙率
    inlet_type: GradientType = GradientType.NONE    # 进口渐变段型式
    outlet_type: GradientType = GradientType.NONE   # 出口渐变段型式
    v_channel_in: float = 0.0           # 进口渐变段始端流速 v₁ (m/s)
    v_pipe_in: float = 0.0              # 进口渐变段末端流速 v₂ (m/s)
    v_channel_out: float = 0.0          # 出口渐变段始端流速 v (m/s)
    v_pipe_out: float = 0.0             # 出口渐变段末端流速 v₃ (m/s)
    xi_inlet: float = 0.0               # 进口局部阻力系数
    xi_outlet: float = 0.0              # 出口局部阻力系数
    v2_strategy: V2Strategy = V2Strategy.AUTO_PIPE  # v₂ 计算策略（默认自动=管道流速）
    num_pipes: int = 1                  # 管道根数（并联管道数量，默认单管）


@dataclass
class StructureSegment:
    """结构段对象"""
    segment_type: SegmentType = SegmentType.STRAIGHT  # 类型
    length: float = 0.0                  # 长度 (直管长或折管左+右) (m)
    radius: float = 0.0                  # 弯管半径 R (仅弯管有效) (m)
    angle: float = 0.0                   # 弯管圆心角或折管折角 (度)
    xi_user: Optional[float] = None      # 用户手动输入的局部阻力系数
    xi_calc: Optional[float] = None      # 程序计算出的局部阻力系数
    coordinates: List[Tuple[float, float]] = field(default_factory=list)  # 几何坐标点集合
    locked: bool = False                 # 是否锁定（从DXF导入的行）
    trash_rack_params: Optional['TrashRackParams'] = None  # 拦污栅参数（仅当类型为拦污栅时有效）
    inlet_shape: Optional['InletOutletShape'] = None  # 进水口形状（仅当类型为进水口时有效）
    outlet_shape: Optional['InletOutletShape'] = None  # 出水口形状（仅当类型为出水口时有效）
    custom_label: str = ""               # 自定义名称（仅"其他"类型有效，如"镇墩"、"排气阀"等）
    
    # ========== 平面 / 纵断面融合新增字段 ==========
    direction: SegmentDirection = SegmentDirection.LONGITUDINAL  # 方向（默认纵断面）
    start_elevation: Optional[float] = None  # 起点高程 (m)（仅纵断面直管段使用）
    end_elevation: Optional[float] = None    # 终点高程 (m)（仅纵断面直管段使用）
    source_ip_index: Optional[int] = None    # 关联的IP点索引（仅平面段，用于同步）
    
    def get_xi(self) -> float:
        """获取局部阻力系数（用户值优先）"""
        if self.xi_user is not None:
            return self.xi_user
        if self.xi_calc is not None:
            return self.xi_calc
        return 0.0
    
    @property
    def spatial_length(self) -> float:
        """
        计算空间长度（考虑高程差）
        
        - 纵断面直管段: sqrt(length² + ΔH²)
        - 纵断面弯管段: radius × angle_radians（弧长即空间长度）
        - 平面段/通用构件: 不参与空间长度计算，返回 0
        """
        if self.direction in (SegmentDirection.PLAN, SegmentDirection.COMMON):
            return 0.0
        
        if self.segment_type in (SegmentType.STRAIGHT, SegmentType.FOLD):
            if (self.start_elevation is not None and 
                self.end_elevation is not None and
                self.length > 0):
                dh = self.end_elevation - self.start_elevation
                return math.sqrt(self.length ** 2 + dh ** 2)
            # 无高程信息时退化为水平长度
            return self.length
        
        if self.segment_type == SegmentType.BEND:
            if self.radius > 0 and self.angle > 0:
                return self.radius * math.radians(self.angle)
            return self.length
        
        # 其他类型（拦污栅等）无空间长度贡献
        return 0.0
    
    @property
    def elevation_change(self) -> float:
        """高程差 ΔH（m），仅纵断面段有效"""
        if (self.start_elevation is not None and 
            self.end_elevation is not None):
            return self.end_elevation - self.start_elevation
        return 0.0


@dataclass
class CalculationResult:
    """计算结果对象"""
    diameter: float = 0.0               # 管径 D (m)
    diameter_theory: float = 0.0        # 理论直径 (m)
    velocity: float = 0.0               # 实际流速 (m/s)
    velocity_channel_in: float = 0.0    # 进口渠道流速 v1 (m/s)
    velocity_pipe_in: float = 0.0       # 进口渐变段末端流速 v₂ (m/s)
    velocity_outlet_start: float = 0.0  # 出口渐变段始端流速 v (m/s)
    velocity_channel_out: float = 0.0   # 出口渠道流速 v3 (m/s)
    area: float = 0.0                   # 断面积 (m²)
    hydraulic_radius: float = 0.0       # 水力半径 (m)
    chezy_c: float = 0.0                # 谢才系数
    
    # 三段式水头损失（附录L规范）
    loss_inlet: float = 0.0             # 进口渐变段水面落差 ΔZ1 (m)
    loss_pipe: float = 0.0              # 管身段总水头损失 ΔZ2 (m)
    loss_friction: float = 0.0          # 沿程水头损失 hf (m)
    loss_local: float = 0.0             # 管身局部水头损失 hj (m)
    loss_outlet: float = 0.0            # 出口渐变段水面落差 ΔZ3 (m)
    total_head_loss: float = 0.0        # 总水面落差 ΔZ = ΔZ1 + ΔZ2 - ΔZ3 (m)
    
    total_length: float = 0.0           # 管道总长度 (m)
    xi_sum_middle: float = 0.0          # 中间段局部阻力系数和
    xi_inlet: float = 0.0               # 进口系数
    xi_outlet: float = 0.0              # 出口系数
    
    # 数据来源与模式说明
    data_mode: str = ""                 # 计算模式/数据来源
    data_note: str = ""                 # 模式说明或提示
    
    # 加大流量工况（内部一次计算完成，与其他模块保持一致）
    increase_percent: float = 0.0           # 加大比例 (%)，0 表示不计算
    Q_increased: float = 0.0               # 加大流量 (m³/s)
    velocity_increased: float = 0.0        # 加大流速 (m/s)
    loss_inlet_inc: float = 0.0            # 加大工况进口落差 ΔZ1加大 (m)
    loss_pipe_inc: float = 0.0             # 加大工况管身损失 ΔZ2加大 (m)
    loss_outlet_inc: float = 0.0           # 加大工况出口落差 ΔZ3加大 (m)
    total_head_loss_inc: float = 0.0       # 加大工况总落差 ΔZ加大 (m)
    
    # 加大工况实际使用的流速
    v1_inc_used: float = 0.0               # 加大工况进口始端流速 v₁加大 (m/s)
    v2_inc_used: float = 0.0               # 加大工况进口末端流速 v₂加大 (m/s)
    v3_inc_used: float = 0.0               # 加大工况出口末端流速 v₃加大 (m/s)

    # 并联管道根数
    num_pipes: int = 1                     # 管道根数（并联数量，默认单管）

    # 详细计算过程（可选输出）
    calculation_steps: List[str] = field(default_factory=list)


@dataclass
class TrashRackParams:
    """拦污栅参数对象"""
    alpha: float = 90.0                 # 栅面倾角 (度)，默认90
    has_support: bool = False           # 是否有独立支墩
    
    # 栅条参数
    bar_shape: TrashRackBarShape = TrashRackBarShape.RECTANGULAR  # 栅条形状
    beta1: float = 2.42                 # 栅条形状系数（根据形状自动设置）
    s1: float = 10.0                    # 栅条厚度 (mm)
    b1: float = 50.0                    # 栅条间距 (mm)
    
    # 支墩参数（仅当 has_support=True 时有效）
    support_shape: TrashRackBarShape = TrashRackBarShape.RECTANGULAR  # 支墩形状
    beta2: float = 2.42                 # 支墩形状系数
    s2: float = 10.0                    # 支墩厚度 (mm)
    b2: float = 50.0                    # 支墩净距 (mm)
    
    # 手动输入模式
    manual_mode: bool = False           # 是否强制手动输入
    manual_xi: float = 0.0              # 手动输入的局部阻力系数

    def to_dict(self) -> dict:
        return {
            'alpha': self.alpha,
            'has_support': self.has_support,
            'bar_shape': self.bar_shape.value,
            'beta1': self.beta1,
            's1': self.s1,
            'b1': self.b1,
            'support_shape': self.support_shape.value,
            'beta2': self.beta2,
            's2': self.s2,
            'b2': self.b2,
            'manual_mode': self.manual_mode,
            'manual_xi': self.manual_xi,
        }

    @staticmethod
    def from_dict(d: dict) -> 'TrashRackParams':
        def _shape(val):
            for s in TrashRackBarShape:
                if s.value == val:
                    return s
            return TrashRackBarShape.RECTANGULAR
        return TrashRackParams(
            alpha=d.get('alpha', 90.0),
            has_support=d.get('has_support', False),
            bar_shape=_shape(d.get('bar_shape', '矩形')),
            beta1=d.get('beta1', 2.42),
            s1=d.get('s1', 10.0),
            b1=d.get('b1', 50.0),
            support_shape=_shape(d.get('support_shape', '矩形')),
            beta2=d.get('beta2', 2.42),
            s2=d.get('s2', 10.0),
            b2=d.get('b2', 50.0),
            manual_mode=d.get('manual_mode', False),
            manual_xi=d.get('manual_xi', 0.0),
        )


# ==============================================================================
# 三维空间合并计算所需的数据模型
# ==============================================================================

@dataclass
class LongitudinalNode:
    """
    纵断面变坡点节点
    
    从AutoCAD纵断面多段线(LWPOLYLINE)解析得到。
    每个节点是一个变坡点（多段线的顶点或圆弧切点）。
    """
    chainage: float = 0.0               # 桩号 (m)
    elevation: float = 0.0              # 高程 (m)
    vertical_curve_radius: float = 0.0  # 竖曲线半径 R_v (m), 0表示折线型或无转弯
    turn_type: TurnType = TurnType.NONE # 转弯类型
    turn_angle: float = 0.0             # 竖向转角 (度), 由相邻坡段坡角差计算
    slope_before: float = 0.0           # 进入该点的坡角 β (弧度)
    slope_after: float = 0.0            # 离开该点的坡角 β (弧度)
    arc_center_s: Optional[float] = None  # 竖曲线弧心桩号坐标 Sc（仅 ARC 型有效）
    arc_center_z: Optional[float] = None  # 竖曲线弧心高程坐标 Zc（仅 ARC 型有效）
    arc_end_chainage: Optional[float] = None  # 竖曲线弧终点桩号（仅 ARC 型有效，供区间重叠检测）
    arc_theta_rad: Optional[float] = None    # 竖曲线圆心角 θ (弧度)（仅 ARC 型有效，供精确弧长计算）
    
    def to_dict(self) -> dict:
        return {
            "chainage": self.chainage,
            "elevation": self.elevation,
            "vertical_curve_radius": self.vertical_curve_radius,
            "turn_type": self.turn_type.value,
            "turn_angle": self.turn_angle,
            "slope_before": self.slope_before,
            "slope_after": self.slope_after,
            "arc_center_s": self.arc_center_s,
            "arc_center_z": self.arc_center_z,
            "arc_end_chainage": self.arc_end_chainage,
            "arc_theta_rad": self.arc_theta_rad,
        }
    
    @staticmethod
    def from_dict(d: dict) -> 'LongitudinalNode':
        tt = TurnType.NONE
        for t in TurnType:
            if t.value == d.get("turn_type", "无"):
                tt = t
                break
        return LongitudinalNode(
            chainage=d.get("chainage", 0.0),
            elevation=d.get("elevation", 0.0),
            vertical_curve_radius=d.get("vertical_curve_radius", 0.0),
            turn_type=tt,
            turn_angle=d.get("turn_angle", 0.0),
            slope_before=d.get("slope_before", 0.0),
            slope_after=d.get("slope_after", 0.0),
            arc_center_s=d.get("arc_center_s", None),
            arc_center_z=d.get("arc_center_z", None),
            arc_end_chainage=d.get("arc_end_chainage", None),
            arc_theta_rad=d.get("arc_theta_rad", None),
        )


@dataclass
class PlanFeaturePoint:
    """
    平面IP特征点
    
    从推求水面线表格的ChannelNode数据提取。
    每个特征点对应一个IP点。
    """
    chainage: float = 0.0               # MC桩号 (m)，平面轴线弧长参数
    x: float = 0.0                      # X坐标（工程坐标，X=东）
    y: float = 0.0                      # Y坐标（工程坐标，Y=北）
    azimuth_meas_deg: float = 0.0       # 测量方位角 (度)，正北=0°顺时针，0~360°，仅用于UI显示
    turn_radius: float = 0.0            # 水平转弯半径 R_h (m)
    turn_angle: float = 0.0             # 水平转角 α (度)
    turn_type: TurnType = TurnType.NONE # 转弯类型
    ip_index: int = 0                   # IP编号
    
    @property
    def azimuth_math_rad(self) -> float:
        """数学方位角 (弧度)，正东=0°逆时针。T向量公式必须使用此字段。"""
        alpha = math.pi / 2 - math.radians(self.azimuth_meas_deg)
        # 归一化到 (-π, π]
        while alpha > math.pi:
            alpha -= 2 * math.pi
        while alpha <= -math.pi:
            alpha += 2 * math.pi
        return alpha
    
    @property
    def azimuth(self) -> float:
        """向后兼容：返回测量方位角 (度)。新代码应使用 azimuth_meas_deg 或 azimuth_math_rad。"""
        return self.azimuth_meas_deg
    
    def to_dict(self) -> dict:
        return {
            "chainage": self.chainage,
            "x": self.x,
            "y": self.y,
            "azimuth": self.azimuth_meas_deg,
            "turn_radius": self.turn_radius,
            "turn_angle": self.turn_angle,
            "turn_type": self.turn_type.value,
            "ip_index": self.ip_index,
        }
    
    @staticmethod
    def from_dict(d: dict) -> 'PlanFeaturePoint':
        tt = TurnType.NONE
        for t in TurnType:
            if t.value == d.get("turn_type", "无"):
                tt = t
                break
        return PlanFeaturePoint(
            chainage=d.get("chainage", 0.0),
            x=d.get("x", 0.0),
            y=d.get("y", 0.0),
            azimuth_meas_deg=d.get("azimuth", 0.0),
            turn_radius=d.get("turn_radius", 0.0),
            turn_angle=d.get("turn_angle", 0.0),
            turn_type=tt,
            ip_index=d.get("ip_index", 0),
        )


@dataclass
class SpatialNode:
    """
    三维空间节点（合并平面+纵断面后的特征点）
    
    由 SpatialMerger 按桩号合并 PlanFeaturePoint 和 LongitudinalNode 生成。
    """
    chainage: float = 0.0               # 桩号 (m)
    x: float = 0.0                      # X坐标
    y: float = 0.0                      # Y坐标
    z: float = 0.0                      # Z坐标 (高程)
    azimuth_before: float = 0.0         # 节点前方位角 (度)
    azimuth_after: float = 0.0          # 节点后方位角 (度)
    slope_before: float = 0.0           # 节点前坡角 (弧度)
    slope_after: float = 0.0            # 节点后坡角 (弧度)
    
    # 转弯信息
    has_plan_turn: bool = False
    has_long_turn: bool = False
    plan_turn_radius: float = 0.0       # 平面转弯半径 R_h (m)
    long_turn_radius: float = 0.0       # 纵断面竖曲线半径 R_v (m)
    plan_turn_angle: float = 0.0        # 平面转角 α (度)
    long_turn_angle: float = 0.0        # 纵断面转角 (度)
    plan_turn_type: TurnType = TurnType.NONE
    long_turn_type: TurnType = TurnType.NONE
    
    # 空间计算结果
    spatial_turn_angle: float = 0.0     # θ_3D (度)
    effective_radius: float = 0.0       # 用于查表的有效半径 (m)
    effective_turn_type: TurnType = TurnType.NONE  # 用于查表的转弯类型
    
    # 竖曲线弧段标记（供精确弧长计算，风险点D）
    long_arc_end_chainage: Optional[float] = None  # 该节点为竖曲线弧起点时，弧终点桩号
    long_arc_theta_rad: Optional[float] = None     # 该节点为竖曲线弧起点时，圆心角 θ (弧度)

    # v5.0 新增：解析精确的方位角/坡角/切向量（不依赖坐标差近似）
    alpha_before_rad: float = 0.0   # 前方位角（数学角 rad，解析精确）
    alpha_after_rad: float = 0.0    # 后方位角（数学角 rad，解析精确）
    beta_before_rad: float = 0.0    # 前坡角（rad，解析精确）；与 slope_before 保持同步
    beta_after_rad: float = 0.0     # 后坡角（rad，解析精确）；与 slope_after 保持同步
    T_before: Tuple[float, float, float] = field(default_factory=lambda: (1., 0., 0.))
    T_after:  Tuple[float, float, float] = field(default_factory=lambda: (1., 0., 0.))
    theta_3d_node: float = 0.0      # 节点折转角（rad）

    @property
    def has_turn(self) -> bool:
        return self.has_plan_turn or self.has_long_turn


@dataclass
class SpatialMergeResult:
    """
    空间合并计算结果
    
    包含三维空间长度、空间转角列表及弯道损失系数。
    """
    nodes: List[SpatialNode] = field(default_factory=list)
    total_spatial_length: float = 0.0
    segment_lengths: List[float] = field(default_factory=list)
    xi_spatial_bends: float = 0.0       # 空间弯道损失系数总和
    computation_steps: List[str] = field(default_factory=list)
    has_plan_data: bool = False
    has_longitudinal_data: bool = False
    # v5.0 新增
    bend_events: List['BendEvent'] = field(default_factory=list)      # 弯道事件表（供局损查表）
    plan_segments: List['PlanSegment'] = field(default_factory=list)  # 平面分段序列
    profile_segments: List['ProfileSegment'] = field(default_factory=list)  # 纵断面分段序列


# ==============================================================================
# v5.0 新增：分段解析几何数据类
# ==============================================================================

@dataclass
class PlanSegment:
    """
    平面轴线解析分段（§4 严格数学版）
    
    覆盖 s∈[s_start, s_end] 的平面几何，可精确求值 x(s), y(s), α(s)。
    """
    seg_type: str = 'LINE'          # 'LINE' / 'ARC'
    s_start: float = 0.             # 段起桩号 (m)
    s_end: float = 0.               # 段终桩号 (m)
    # LINE 字段
    p_start: Tuple[float, float] = field(default_factory=lambda: (0., 0.))
    direction: Tuple[float, float] = field(default_factory=lambda: (1., 0.))
    # ARC 字段
    center: Tuple[float, float] = field(default_factory=lambda: (0., 0.))
    R_h: float = 0.                 # 半径 (m)
    epsilon: int = 1                # +1=左转(CCW), -1=右转(CW)
    theta_0: float = 0.             # BC点极角 atan2(y_BC-Cy, x_BC-Cx)


@dataclass
class ProfileSegment:
    """
    纵断面轴线解析分段（§5 严格数学版）
    
    覆盖 s∈[s_start, s_end] 的纵断面几何，可精确求值 z(s), β(s)。
    """
    seg_type: str = 'LINE'          # 'LINE' / 'ARC'
    s_start: float = 0.             # 段起桩号 (m)
    s_end: float = 0.               # 段终桩号 (m)
    # LINE 字段
    z_start: float = 0.             # 起点高程 (m)
    k: float = 0.                   # 斜率 dz/ds（无量纲）
    # ARC 字段
    R_v: float = 0.                 # 半径 (m)
    Sc: float = 0.                  # 圆心桩号坐标 (m)
    Zc: float = 0.                  # 圆心高程坐标 (m)
    eta: int = 1                    # +1/-1，由 z(S1)=Z1 确定
    theta_arc: float = 0.           # 圆心角 θ (rad)


@dataclass
class BendEvent:
    """
    弯道事件（§10-§11 严格数学版）
    
    以区间 [s_a, s_b] 定义，包含事件空间长度、转角和等效半径。
    等效半径严格定义为 R_eff = L_event / θ_event（几何自洽）。
    """
    s_a: float = 0.                 # 事件起桩号 (m)
    s_b: float = 0.                 # 事件终桩号 (m)
    event_type: str = 'PLAN'        # 'PLAN' / 'VERTICAL' / 'COMPOSITE'
    turn_style: TurnType = TurnType.ARC  # ARC / FOLD
    L_event: float = 0.             # 空间长度（§9解析积分，m）
    theta_event: float = 0.         # 空间转角（rad）
    R_eff: float = 0.               # 等效半径 = L/θ (m)；θ=0时为 inf
    R_h: float = 0.                 # 平面半径（可选，m）
    R_v: float = 0.                 # 纵断半径（可选，m）
    R_3d_mid: float = 0.            # 事件中点曲率半径（可选诊断，m）
