# -*- coding: utf-8 -*-
"""
倒虹吸水力计算软件 - 数据模型层
定义全局参数和结构段的数据结构
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Tuple, Optional


class SegmentType(Enum):
    """结构段类型枚举"""
    INLET = "进水口"
    STRAIGHT = "直管"
    BEND = "弯管"
    FOLD = "折管"
    TRASH_RACK = "拦污栅"
    GATE_SLOT = "闸门槽"
    BYPASS_PIPE = "旁通管"  # 冲沙、放空、进人孔等
    OTHER = "其他"
    OUTLET = "出水口"


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
    H_up: float = 0.0                   # 上游水位 (m)
    H_down: float = 0.0                 # 下游水位 (m)
    roughness_n: float = 0.014          # 糙率
    inlet_type: GradientType = GradientType.NONE    # 进口渐变段型式
    outlet_type: GradientType = GradientType.NONE   # 出口渐变段型式
    v_channel_in: float = 0.0           # 进口渐变段始端流速 v₁ (m/s)
    v_pipe_in: float = 0.0              # 进口渐变段末端流速 v₂ (m/s)
    v_channel_out: float = 0.0          # 出口渐变段始端流速 v (m/s)
    v_pipe_out: float = 0.0             # 出口渐变段末端流速 v₃ (m/s)
    H_bottom_up: float = 0.0            # 上游渠底高程 (m)
    xi_inlet: float = 0.0               # 进口局部阻力系数
    xi_outlet: float = 0.0              # 出口局部阻力系数


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
    
    def get_xi(self) -> float:
        """获取局部阻力系数（用户值优先）"""
        if self.xi_user is not None:
            return self.xi_user
        if self.xi_calc is not None:
            return self.xi_calc
        return 0.0


@dataclass
class CalculationResult:
    """计算结果对象"""
    diameter: float = 0.0               # 管径 D (m)
    diameter_theory: float = 0.0        # 理论直径 (m)
    velocity: float = 0.0               # 实际流速 (m/s)
    velocity_channel_in: float = 0.0    # 进口渠道流速 v1 (m/s)
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
    total_head_loss: float = 0.0        # 总水面落差 ΔZ = ΔZ1 + ΔZ2 + ΔZ3 (m)
    
    required_head_diff: float = 0.0     # 所需水位差 (m)
    available_head_diff: float = 0.0    # 可用水位差 (m)
    is_verified: bool = False           # 校验是否通过
    message: str = ""                   # 校验消息
    total_length: float = 0.0           # 管道总长度 (m)
    xi_sum_middle: float = 0.0          # 中间段局部阻力系数和
    xi_inlet: float = 0.0               # 进口系数
    xi_outlet: float = 0.0              # 出口系数
    
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
    s2: float = 100.0                   # 支墩厚度 (mm)
    b2: float = 1000.0                  # 支墩净距 (mm)
    
    # 手动输入模式
    manual_mode: bool = False           # 是否强制手动输入
    manual_xi: float = 0.0              # 手动输入的局部阻力系数
