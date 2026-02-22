# -*- coding: utf-8 -*-
"""
断面数据模型

包含：
- SlopeGrade         — 单级边坡参数（已在 PRD 中确认）
- ExcavationSlope    — 某桩号段的开挖边坡配置（已在 PRD 中确认）
- BackfillConfig     — 回填配置（固定厚度 / 回填到设计面）
- DesignSection      — 设计断面参数（渠底宽/渠深/内坡比/断面类型）
- DesignProfile      — 纵断面设计参数（各段纵坡 → 设计底高程）
- SectionAreaResult  — 单个横断面的面积计算结果
- CrossSectionData   — 单个横断面的完整数据（地面线 + 设计线 + 地质层）
- LongitudinalData   — 纵断面完整数据（桩号序列 + 高程序列）
- VolumeResult       — 工程量计算结果（三种方法 + 分层统计）
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import math


# ============================================================
# 边坡与回填配置（已在 PRD 第三轮讨论中确认）
# ============================================================

@dataclass
class SlopeGrade:
    """
    单级边坡参数（从渠底向上，依次叠加）

    示例：
        第一级：ratio=1.0, height=5.0, berm_width=2.0
            → 渠底往上挖 5m，坡比 1:1，顶部留 2m 马道
        第二级：ratio=0.75, height=math.inf, berm_width=0.0
            → 马道以上继续按 1:0.75 挖到地面，无马道
    """
    ratio: float          # 边坡比 m（水平:竖直 = m:1）
    height: float         # 本级高度（m），math.inf 表示延伸到地面
    berm_width: float     # 本级顶部马道宽度（m），0 表示无马道

    def __post_init__(self):
        if self.ratio < 0:
            raise ValueError(f"边坡比不能为负，got {self.ratio}")
        if self.height <= 0:
            raise ValueError(f"边坡高度必须 > 0，got {self.height}")
        if self.berm_width < 0:
            raise ValueError(f"马道宽度不能为负，got {self.berm_width}")


@dataclass
class ExcavationSlope:
    """
    某桩号段的开挖边坡配置（左/右侧独立，支持分级放坡 + 马道）
    """
    start_station: float
    end_station: float
    left_grades: list[SlopeGrade]    # 左侧分级边坡（从渠底向上）
    right_grades: list[SlopeGrade]   # 右侧分级边坡（从渠底向上）
    platform_enabled: bool = False   # 坡顶是否预留施工便道
    platform_width: float = 2.0      # 施工便道宽度（m）

    def __post_init__(self):
        if self.end_station <= self.start_station:
            raise ValueError("end_station 必须 > start_station")
        if not self.left_grades:
            raise ValueError("left_grades 不能为空")
        if not self.right_grades:
            raise ValueError("right_grades 不能为空")


class BackfillMode(Enum):
    FIXED_THICKNESS = "fixed_thickness"   # 固定厚度回填
    TO_DESIGN_SURFACE = "to_design"       # 回填到设计面


@dataclass
class BackfillConfig:
    """回填配置"""
    mode: BackfillMode = BackfillMode.FIXED_THICKNESS
    thickness: float = 0.3          # 固定厚度模式下的回填厚度（m）
    include_slope_backfill: bool = True  # 是否包含贴坡回填


# ============================================================
# 设计断面
# ============================================================

class ChannelType(Enum):
    TRAPEZOIDAL = "trapezoidal"   # 梯形明渠
    RECTANGULAR = "rectangular"   # 矩形明渠/暗涵
    CIRCULAR    = "circular"      # 圆形隧洞
    AQUEDUCT    = "aqueduct"      # 渡槽（U形/矩形）
    SIPHON      = "siphon"        # 倒虹吸
    CUSTOM      = "custom"        # 自定义


@dataclass
class DesignSection:
    """
    渠道设计断面参数（单个断面类型，与渠系断面设计模块对接）

    对于梯形明渠：b（底宽）、h（渠深）、m_left/m_right（内坡比）
    对于矩形暗涵：b（底宽）、h（断面高）
    对于其他类型：扩展字段 extra_params 存储
    """
    channel_type: ChannelType = ChannelType.TRAPEZOIDAL
    bottom_width: float = 0.0          # 渠底宽 b（m）
    depth: float = 0.0                 # 渠深 h（m）
    inner_slope_left: float = 1.0      # 左侧内坡比 m（水平:竖直）
    inner_slope_right: float = 1.0     # 右侧内坡比 m
    freeboard: float = 0.0             # 超高（m）
    lining_thickness: float = 0.0      # 衬砌厚度（m），用于计算贴坡回填
    name: str = ""                     # 断面名称
    extra_params: dict = field(default_factory=dict)  # 其他类型扩展参数

    @property
    def top_width(self) -> float:
        """设计断面口宽（m）"""
        return (self.bottom_width
                + (self.inner_slope_left + self.inner_slope_right) * self.depth)


@dataclass
class DesignProfileSegment:
    """纵断面设计中的一段（起终桩号 + 坡降）"""
    start_station: float
    end_station: float
    start_invert_elevation: float   # 起点设计底高程（m）
    slope: float                    # 坡降（负值表示顺坡，正值表示逆坡）

    def invert_at_station(self, s: float) -> float:
        """计算指定桩号处的设计底高程"""
        return self.start_invert_elevation + self.slope * (s - self.start_station)


@dataclass
class DesignProfile:
    """
    渠道纵断面设计（设计底高程来源）

    支持三种来源（已在 PRD 第一轮讨论中确认）：
    1. 模块内纵坡设计（segments）
    2. 外部 Excel 导入（桩号→设计底高程 dict）
    3. 从水面线模块读取（JSON 项目文件）
    """
    segments: list[DesignProfileSegment] = field(default_factory=list)
    station_elevation_table: dict[float, float] = field(default_factory=dict)
    source: str = "manual"  # 'manual'/'excel'/'water_profile'

    def get_invert_at_station(self, s: float) -> Optional[float]:
        """
        查询指定桩号的设计底高程。
        优先使用 station_elevation_table，否则从 segments 插值。
        """
        if self.station_elevation_table:
            stations = sorted(self.station_elevation_table)
            if not stations:
                return None
            # 线性插值
            if s <= stations[0]:
                return self.station_elevation_table[stations[0]]
            if s >= stations[-1]:
                return self.station_elevation_table[stations[-1]]
            for i in range(len(stations) - 1):
                s0, s1 = stations[i], stations[i + 1]
                if s0 <= s <= s1:
                    t = (s - s0) / (s1 - s0)
                    return (self.station_elevation_table[s0] * (1 - t)
                            + self.station_elevation_table[s1] * t)
        for seg in self.segments:
            if seg.start_station <= s <= seg.end_station:
                return seg.invert_at_station(s)
        return None


# ============================================================
# 地质分层
# ============================================================

@dataclass
class GeologyLayer:
    """单个地质层定义"""
    name: str                  # 用户自定义层名，如「残坡积层」「强风化层」
    color_index: int = 8       # ACI 颜色编号（DXF 图层颜色）
    hatch_pattern: str = "ANSI31"  # AutoCAD 填充图案名
    hatch_scale: float = 1.0
    hatch_angle: float = 0.0


@dataclass
class GeologySectionProfile:
    """
    某横断面处各地质层的界面高程（从下到上）

    layers[i] 对应 GeologyLayer 列表中的第 i 层，
    top_elevation[i] 是第 i 层顶面高程（即第 i+1 层底面高程）。
    最顶层（地面层）的上边界是地面高程。
    """
    station: float
    layer_names: list[str]         # 与 GeologyLayer.name 对应
    top_elevations: list[float]    # 各层顶面高程（长度 = len(layer_names)）

    def get_layer_top(self, layer_name: str) -> Optional[float]:
        try:
            idx = self.layer_names.index(layer_name)
            return self.top_elevations[idx]
        except ValueError:
            return None


# ============================================================
# 横断面计算结果
# ============================================================

@dataclass
class SectionAreaResult:
    """单个横断面的面积计算结果"""
    station: float
    excavation_total: float = 0.0              # 开挖总面积（m²）
    excavation_by_layer: dict[str, float] = field(default_factory=dict)  # 按地质层分
    fill_area: float = 0.0                     # 回填总面积（m²）
    excavation_width: float = 0.0             # 横断面开挖总宽度（m）
    ground_elevation_center: float = 0.0      # 中心线处地面高程（m）
    design_invert_elevation: float = 0.0      # 设计底高程（m）
    cut_depth: float = 0.0                    # 挖深（地面 - 设计底，正值为挖）

    @property
    def is_cut(self) -> bool:
        return self.cut_depth > 0

    @property
    def is_fill(self) -> bool:
        return self.cut_depth < 0


@dataclass
class CrossSectionData:
    """单个横断面的完整数据（计算输入 + 计算结果）"""
    station: float
    ground_points: list[tuple[float, float]]       # [(offset, elev), ...] 地面线采样点
    design_points: list[tuple[float, float]]        # [(offset, elev), ...] 设计断面轮廓
    excavation_boundary: list[tuple[float, float]]  # [(offset, elev), ...] 开挖边坡线
    geology_profile: Optional[GeologySectionProfile] = None
    area_result: Optional[SectionAreaResult] = None
    left_width: float = 0.0   # 断面左半宽
    right_width: float = 0.0  # 断面右半宽


# ============================================================
# 纵断面数据
# ============================================================

@dataclass
class LongitudinalData:
    """纵断面完整数据"""
    stations: list[float]                    # 桩号列表
    ground_elevations: list[float]           # 地面高程列表
    design_elevations: list[Optional[float]] # 设计底高程列表（None 表示无数据）

    def __post_init__(self):
        n = len(self.stations)
        if len(self.ground_elevations) != n:
            raise ValueError("ground_elevations 长度与 stations 不一致")
        if len(self.design_elevations) != n:
            raise ValueError("design_elevations 长度与 stations 不一致")

    def get_cut_depths(self) -> list[Optional[float]]:
        """计算各桩号的挖深（地面 - 设计底，正为挖，负为填）"""
        result = []
        for g, d in zip(self.ground_elevations, self.design_elevations):
            result.append(g - d if d is not None else None)
        return result


# ============================================================
# 工程量计算结果
# ============================================================

@dataclass
class SegmentVolume:
    """相邻两断面之间一个桩号段的工程量"""
    station_start: float
    station_end: float
    length: float                                     # 段长（m）
    excavation_avg: float = 0.0                       # 平均断面法开挖量（m³）
    excavation_prismatoid: float = 0.0                # 棱台法开挖量（m³）
    excavation_by_layer_avg: dict[str, float] = field(default_factory=dict)
    fill_avg: float = 0.0
    fill_prismatoid: float = 0.0


@dataclass
class VolumeResult:
    """完整土石方工程量计算结果"""
    segments: list[SegmentVolume] = field(default_factory=list)
    tin_volume_excavation: Optional[float] = None   # TIN体积法结果
    tin_volume_fill: Optional[float] = None

    @property
    def total_excavation_avg(self) -> float:
        return sum(s.excavation_avg for s in self.segments)

    @property
    def total_excavation_prismatoid(self) -> float:
        return sum(s.excavation_prismatoid for s in self.segments)

    @property
    def total_fill_avg(self) -> float:
        return sum(s.fill_avg for s in self.segments)

    def total_by_layer_avg(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for seg in self.segments:
            for layer, vol in seg.excavation_by_layer_avg.items():
                totals[layer] = totals.get(layer, 0.0) + vol
        return totals
