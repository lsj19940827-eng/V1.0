import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import math
import os
from typing import List, Optional
from PIL import Image, ImageTk
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
class SegmentType(Enum):
    INLET = "进水口"
    STRAIGHT = "直管"
    BEND = "弯管"
    FOLD = "折管"
    TRASH_RACK = "拦污栅"
    GATE_SLOT = "闸门槽"
    BYPASS_PIPE = "旁通管"
    OTHER = "其他"
    OUTLET = "出水口"
class GradientType(Enum):
    NONE = "无"
    REVERSE_BEND = "反弯扭曲面"
    QUARTER_ARC = "1/4圆弧"
    SQUARE_HEAD = "方头型"
    LINEAR_TWIST = "直线扭曲面"
class InletOutletShape(Enum):
    FULLY_ROUNDED = "进口完全修圆"
    SLIGHTLY_ROUNDED = "进口稍微修圆"
    NOT_ROUNDED = "进口没有修圆"
INLET_SHAPE_COEFFICIENTS = {
    InletOutletShape.FULLY_ROUNDED: (0.05, 0.10),
    InletOutletShape.SLIGHTLY_ROUNDED: (0.20, 0.25),
    InletOutletShape.NOT_ROUNDED: (0.50, 0.50),
}
class TrashRackBarShape(Enum):
    RECTANGULAR = "矩形"
    ROUNDED_HEAD = "单侧圆头"
    CIRCULAR = "圆形"
    OVAL = "双侧圆头"
    TRAPEZOID = "倒梯形单侧圆头"
    PEAR_SHAPE = "梨形/流线型"
    SHARP_TAIL = "两端尖锐型"
@dataclass
class GlobalParameters:
    Q: float = 0.0
    v_guess: float = 0.0
    H_up: float = 0.0
    H_down: float = 0.0
    roughness_n: float = 0.014
    inlet_type: GradientType = GradientType.NONE
    outlet_type: GradientType = GradientType.NONE
    v_channel_in: float = 0.0
    v_pipe_in: float = 0.0
    v_channel_out: float = 0.0
    v_pipe_out: float = 0.0
    H_bottom_up: float = 0.0
    xi_inlet: float = 0.0
    xi_outlet: float = 0.0
@dataclass
class StructureSegment:
    segment_type: SegmentType = SegmentType.STRAIGHT
    length: float = 0.0
    radius: float = 0.0
    angle: float = 0.0
    xi_user: Optional[float] = None
    xi_calc: Optional[float] = None
    coordinates: List[Tuple[float, float]] = field(default_factory=list)
    locked: bool = False
    trash_rack_params: Optional['TrashRackParams'] = None
    inlet_shape: Optional['InletOutletShape'] = None
    outlet_shape: Optional['InletOutletShape'] = None
    def get_xi(self) -> float:
        if self.xi_user is not None:
            return self.xi_user
        if self.xi_calc is not None:
            return self.xi_calc
        return 0.0
@dataclass
class CalculationResult:
    diameter: float = 0.0
    diameter_theory: float = 0.0
    velocity: float = 0.0
    velocity_channel_in: float = 0.0
    velocity_channel_out: float = 0.0
    area: float = 0.0
    hydraulic_radius: float = 0.0
    chezy_c: float = 0.0
    loss_inlet: float = 0.0
    loss_pipe: float = 0.0
    loss_friction: float = 0.0
    loss_local: float = 0.0
    loss_outlet: float = 0.0
    total_head_loss: float = 0.0
    required_head_diff: float = 0.0
    available_head_diff: float = 0.0
    is_verified: bool = False
    message: str = ""
    total_length: float = 0.0
    xi_sum_middle: float = 0.0
    xi_inlet: float = 0.0
    xi_outlet: float = 0.0
    calculation_steps: List[str] = field(default_factory=list)
@dataclass
class TrashRackParams:
    alpha: float = 90.0
    has_support: bool = False
    bar_shape: TrashRackBarShape = TrashRackBarShape.RECTANGULAR
    beta1: float = 2.42
    s1: float = 10.0
    b1: float = 50.0
    support_shape: TrashRackBarShape = TrashRackBarShape.RECTANGULAR
    beta2: float = 2.42
    s2: float = 100.0
    b2: float = 1000.0
    manual_mode: bool = False
    manual_xi: float = 0.0
class DxfParser:
    @staticmethod
    def parse_dxf(file_path: str) -> Tuple[List[StructureSegment], float, str]:
        try:
            import ezdxf
        except ImportError:
            return [], 0.0, "错误：未安装ezdxf库，请运行 pip install ezdxf"
        try:
            doc = ezdxf.readfile(file_path)
        except Exception as e:
            return [], 0.0, f"错误：无法读取DXF文件 - {str(e)}"
        msp = doc.modelspace()
        polylines = list(msp.query('LWPOLYLINE'))
        if not polylines:
            polylines = list(msp.query('POLYLINE'))
        if not polylines:
            return [], 0.0, "错误：DXF文件中未找到多段线(LWPOLYLINE/POLYLINE)实体"
        polyline = polylines[0]
        vertices = []
        bulges = []
        if hasattr(polyline, 'get_points'):
            for point in polyline.get_points(format='xyseb'):
                x, y, start_width, end_width, bulge = point
                vertices.append((x, y))
                bulges.append(bulge)
        elif hasattr(polyline, 'vertices'):
            for vertex in polyline.vertices:
                vertices.append((vertex.dxf.location.x, vertex.dxf.location.y))
                bulges.append(vertex.dxf.bulge if hasattr(vertex.dxf, 'bulge') else 0.0)
        else:
            return [], 0.0, "错误：无法解析多段线顶点"
        if len(vertices) < 2:
            return [], 0.0, "错误：多段线顶点数量不足"
        segments = DxfParser._build_segments(vertices, bulges)
        h_bottom_up = vertices[0][1] if vertices else 0.0
        return segments, h_bottom_up, f"成功解析DXF文件，共{len(segments)}个结构段"
    @staticmethod
    def _build_segments(vertices: List[Tuple[float, float]], bulges: List[float]) -> List[StructureSegment]:
        segments = []
        inlet = StructureSegment(segment_type=SegmentType.INLET,coordinates=[vertices[0]],locked=True)
        segments.append(inlet)
        prev_direction = None
        temp_straight_segments = []
        for i in range(len(vertices) - 1):
            p1 = vertices[i]
            p2 = vertices[i + 1]
            bulge = bulges[i] if i < len(bulges) else 0.0
            if abs(bulge) > 1e-6:
                segment = DxfParser._create_bend_segment(p1, p2, bulge)
                if temp_straight_segments:
                    segments.extend(DxfParser._process_straight_segments(temp_straight_segments))
                    temp_straight_segments = []
                    prev_direction = None
                segments.append(segment)
            else:
                length = math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
                direction = DxfParser._get_direction(p1, p2)
                straight_seg = {'p1': p1,'p2': p2,'length': length,'direction': direction}
                temp_straight_segments.append(straight_seg)
        if temp_straight_segments:
            segments.extend(DxfParser._process_straight_segments(temp_straight_segments))
        outlet = StructureSegment(segment_type=SegmentType.OUTLET,coordinates=[vertices[-1]],locked=True)
        segments.append(outlet)
        return segments
    @staticmethod
    def _create_bend_segment(p1: Tuple[float, float], p2: Tuple[float, float], bulge: float) -> StructureSegment:
        chord_length = math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
        angle_rad = 4 * math.atan(abs(bulge))
        angle_deg = math.degrees(angle_rad)
        if abs(math.sin(angle_rad / 2)) > 1e-6:
            radius = chord_length / (2 * math.sin(angle_rad / 2))
        else:
            radius = chord_length / 2
        arc_length = radius * angle_rad
        return StructureSegment(segment_type=SegmentType.BEND,length=arc_length,radius=radius,angle=angle_deg,coordinates=[p1, p2],locked=True)
    @staticmethod
    def _get_direction(p1: Tuple[float, float], p2: Tuple[float, float]) -> Tuple[float, float]:
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.sqrt(dx**2 + dy**2)
        if length > 1e-6:
            return (dx / length, dy / length)
        return (0.0, 0.0)
    @staticmethod
    def _process_straight_segments(straight_segments: list) -> List[StructureSegment]:
        if not straight_segments:
            return []
        result = []
        for i, seg in enumerate(straight_segments):
            if i == 0:
                result.append(StructureSegment(segment_type=SegmentType.STRAIGHT,length=seg['length'],coordinates=[seg['p1'], seg['p2']],locked=True))
            else:
                prev_dir = straight_segments[i - 1]['direction']
                curr_dir = seg['direction']
                dot = prev_dir[0] * curr_dir[0] + prev_dir[1] * curr_dir[1]
                dot = max(-1.0, min(1.0, dot))
                angle_rad = math.acos(dot)
                angle_deg = math.degrees(angle_rad)
                if angle_deg > 1.0:
                    if result and result[-1].segment_type == SegmentType.STRAIGHT:
                        prev_seg = result[-1]
                        fold_seg = StructureSegment(segment_type=SegmentType.FOLD,length=prev_seg.length + seg['length'],angle=angle_deg,coordinates=prev_seg.coordinates + [seg['p2']],locked=True)
                        result[-1] = fold_seg
                    else:
                        result.append(StructureSegment(segment_type=SegmentType.FOLD,length=seg['length'],angle=angle_deg,coordinates=[seg['p1'], seg['p2']],locked=True))
                else:
                    result.append(StructureSegment(segment_type=SegmentType.STRAIGHT,length=seg['length'],coordinates=[seg['p1'], seg['p2']],locked=True))
        return result
    @staticmethod
    def validate_dxf(file_path: str) -> Tuple[bool, str]:
        try:
            import ezdxf
        except ImportError:
            return False, "未安装ezdxf库"
        try:
            doc = ezdxf.readfile(file_path)
            msp = doc.modelspace()
            polylines = list(msp.query('LWPOLYLINE'))
            if not polylines:
                polylines = list(msp.query('POLYLINE'))
            if not polylines:
                return False, "文件中未找到多段线实体"
            return True, "DXF文件格式有效"
        except Exception as e:
            return False, f"文件读取失败: {str(e)}"
class CoefficientService:
    INLET_COEFFICIENTS = {
        GradientType.NONE: 0.00,
        GradientType.REVERSE_BEND: 0.10,
        GradientType.QUARTER_ARC: 0.15,
        GradientType.SQUARE_HEAD: 0.30,
        GradientType.LINEAR_TWIST: 0.20,
    }
    OUTLET_COEFFICIENTS = {
        GradientType.NONE: 0.00,
        GradientType.REVERSE_BEND: 0.20,
        GradientType.QUARTER_ARC: 0.25,
        GradientType.SQUARE_HEAD: 0.75,
        GradientType.LINEAR_TWIST: 0.40,
    }
    BEND_90_TABLE = [
        (0.5, 1.20),
        (1.0, 0.80),
        (1.5, 0.60),
        (2.0, 0.48),
        (3.0, 0.36),
        (4.0, 0.30),
        (5.0, 0.29),
        (6.0, 0.28),
        (7.0, 0.27),
        (8.0, 0.26),
        (9.0, 0.25),
        (10.0, 0.24),
        (11.0, 0.23),
    ]
    ANGLE_CORRECTION_TABLE = [
        (5, 0.125),
        (10, 0.23),
        (20, 0.40),
        (30, 0.55),
        (40, 0.65),
        (50, 0.75),
        (60, 0.83),
        (70, 0.88),
        (80, 0.95),
        (90, 1.00),
        (100, 1.05),
        (120, 1.13),
        (140, 1.20),
    ]
    TRASH_RACK_BAR_COEFFICIENTS = {
        TrashRackBarShape.RECTANGULAR: 2.42,
        TrashRackBarShape.ROUNDED_HEAD: 1.83,
        TrashRackBarShape.CIRCULAR: 1.79,
        TrashRackBarShape.OVAL: 1.67,
        TrashRackBarShape.TRAPEZOID: 1.04,
        TrashRackBarShape.PEAR_SHAPE: 0.92,
        TrashRackBarShape.SHARP_TAIL: 0.76,
    }
    @classmethod
    def get_gradient_coeff(cls, gradient_type: GradientType, is_inlet: bool) -> float:
        if is_inlet:
            return cls.INLET_COEFFICIENTS.get(gradient_type, 0.0)
        else:
            return cls.OUTLET_COEFFICIENTS.get(gradient_type, 0.0)
    @classmethod
    def _linear_interpolate(cls, table: list, x: float) -> float:
        if x <= table[0][0]:
            return table[0][1]
        if x >= table[-1][0]:
            return table[-1][1]
        for i in range(len(table) - 1):
            x1, y1 = table[i]
            x2, y2 = table[i + 1]
            if x1 <= x <= x2:
                return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
        return table[-1][1]
    @classmethod
    def get_xi_90(cls, r_d_ratio: float) -> float:
        return cls._linear_interpolate(cls.BEND_90_TABLE, r_d_ratio)
    @classmethod
    def get_gamma(cls, angle: float) -> float:
        return cls._linear_interpolate(cls.ANGLE_CORRECTION_TABLE, angle)
    @classmethod
    def calculate_bend_coeff(cls, R: float, D: float, angle: float, verbose: bool = False) -> tuple:
        steps = []
        r_d_ratio = R / D
        steps.append(f"计算 R/D0 = {R:.3f} / {D:.3f} = {r_d_ratio:.3f}")
        xi_90 = cls.get_xi_90(r_d_ratio)
        steps.append(f"查表 L.1.4-3，根据 R/D0 = {r_d_ratio:.3f}，线性插值得 xi_90 = {xi_90:.4f}")
        gamma = cls.get_gamma(angle)
        steps.append(f"查表 L.1.4-4，根据 theta = {angle:.1f} 度，线性插值得 gamma = {gamma:.4f}")
        xi = xi_90 * gamma
        steps.append(f"计算弯管系数 xi = xi_90 * gamma = {xi_90:.4f} * {gamma:.4f} = {xi:.4f}")
        if verbose:
            return xi, "\n".join(steps)
        return xi
    @classmethod
    def get_trash_rack_bar_beta(cls, shape: TrashRackBarShape) -> float:
        return cls.TRASH_RACK_BAR_COEFFICIENTS.get(shape, 2.42)
    @classmethod
    def calculate_trash_rack_xi(cls, params: TrashRackParams, verbose: bool = False):
        steps = []
        if params.manual_mode:
            xi = params.manual_xi
            steps.append(f"手动输入模式，xi = {xi:.4f}")
            if verbose:
                return xi, "\n".join(steps)
            return xi
        if params.alpha < 0 or params.alpha > 180:
            error_msg = "错误: 栅面倾角 alpha 必须在0~180度范围内"
            if verbose:
                return 0.0, error_msg
            return 0.0
        if params.b1 <= 0:
            error_msg = "错误: 栅条间距 b1 不能为0或负数"
            if verbose:
                return 0.0, error_msg
            return 0.0
        if params.has_support and params.b2 <= 0:
            error_msg = "错误: 支墩净距 b2 不能为0或负数"
            if verbose:
                return 0.0, error_msg
            return 0.0
        alpha_rad = math.radians(params.alpha)
        steps.append(f"栅面倾角 alpha = {params.alpha:.1f} 度 = {alpha_rad:.4f} 弧度")
        steps.append(f"sin(alpha) = {math.sin(alpha_rad):.4f}")
        ratio1 = params.s1 / params.b1
        term_a = params.beta1 * (ratio1 ** (4.0 / 3.0))
        steps.append(f"")
        steps.append(f"栅条参数:")
        steps.append(f"  形状: {params.bar_shape.value}, beta1 = {params.beta1:.2f}")
        steps.append(f"  栅条厚度 s1 = {params.s1:.1f} mm")
        steps.append(f"  栅条间距 b1 = {params.b1:.1f} mm")
        steps.append(f"  阻塞比 s1/b1 = {ratio1:.4f}")
        steps.append(f"  栅条项 A = beta1 * (s1/b1)^(4/3)")
        steps.append(f"         = {params.beta1:.2f} * ({ratio1:.4f})^(4/3)")
        steps.append(f"         = {term_a:.4f}")
        if params.has_support:
            ratio2 = params.s2 / params.b2
            term_b = params.beta2 * (ratio2 ** (4.0 / 3.0))
            steps.append(f"")
            steps.append(f"支墩参数:")
            steps.append(f"  形状: {params.support_shape.value}, beta2 = {params.beta2:.2f}")
            steps.append(f"  支墩厚度 s2 = {params.s2:.1f} mm")
            steps.append(f"  支墩净距 b2 = {params.b2:.1f} mm")
            steps.append(f"  阻塞比 s2/b2 = {ratio2:.4f}")
            steps.append(f"  支墩项 B = beta2 * (s2/b2)^(4/3)")
            steps.append(f"         = {params.beta2:.2f} * ({ratio2:.4f})^(4/3)")
            steps.append(f"         = {term_b:.4f}")
            xi = (term_a + term_b) * math.sin(alpha_rad)
            steps.append(f"")
            steps.append(f"应用公式 L.1.4-3 (有独立支墩):")
            steps.append(f"  xi = (A + B) * sin(alpha)")
            steps.append(f"     = ({term_a:.4f} + {term_b:.4f}) * {math.sin(alpha_rad):.4f}")
            steps.append(f"     = {xi:.4f}")
        else:
            xi = term_a * math.sin(alpha_rad)
            steps.append(f"")
            steps.append(f"应用公式 L.1.4-2 (无独立支墩):")
            steps.append(f"  xi = A * sin(alpha)")
            steps.append(f"     = {term_a:.4f} * {math.sin(alpha_rad):.4f}")
            steps.append(f"     = {xi:.4f}")
        if verbose:
            return xi, "\n".join(steps)
        return xi
    @classmethod
    def calculate_fold_coeff(cls, angle: float, verbose: bool = False) -> tuple:
        steps = []
        angle_rad = math.radians(angle)
        half_angle_rad = angle_rad / 2
        steps.append(f"折管折角 θ = {angle:.1f}°")
        steps.append(f"θ/2 = {angle/2:.1f}° = {half_angle_rad:.4f} rad")
        sin_half = math.sin(half_angle_rad)
        sin2_half = sin_half ** 2
        sin4_half = sin_half ** 4
        steps.append(f"sin(θ/2) = {sin_half:.4f}")
        steps.append(f"sin²(θ/2) = {sin2_half:.4f}")
        steps.append(f"sin⁴(θ/2) = {sin4_half:.4f}")
        term1 = 0.9457 * sin2_half
        term2 = 2.047 * sin4_half
        xi = term1 + term2
        steps.append(f"")
        steps.append(f"应用公式: ζ = 0.9457 * sin²(θ/2) + 2.047 * sin⁴(θ/2)")
        steps.append(f"  = 0.9457 × {sin2_half:.4f} + 2.047 × {sin4_half:.4f}")
        steps.append(f"  = {term1:.4f} + {term2:.4f}")
        steps.append(f"  = {xi:.4f}")
        if verbose:
            return xi, "\n".join(steps)
        return xi
class DxfParser:
    @staticmethod
    def parse_dxf(file_path: str) -> Tuple[List[StructureSegment], float, str]:
        try:
            import ezdxf
        except ImportError:
            return [], 0.0, "错误：未安装ezdxf库，请运行 pip install ezdxf"
        try:
            doc = ezdxf.readfile(file_path)
        except Exception as e:
            return [], 0.0, f"错误：无法读取DXF文件 - {str(e)}"
        msp = doc.modelspace()
        polylines = list(msp.query('LWPOLYLINE'))
        if not polylines:
            polylines = list(msp.query('POLYLINE'))
        if not polylines:
            return [], 0.0, "错误：DXF文件中未找到多段线(LWPOLYLINE/POLYLINE)实体"
        polyline = polylines[0]
        vertices = []
        bulges = []
        if hasattr(polyline, 'get_points'):
            for point in polyline.get_points(format='xyseb'):
                x, y, start_width, end_width, bulge = point
                vertices.append((x, y))
                bulges.append(bulge)
        elif hasattr(polyline, 'vertices'):
            for vertex in polyline.vertices:
                vertices.append((vertex.dxf.location.x, vertex.dxf.location.y))
                bulges.append(vertex.dxf.bulge if hasattr(vertex.dxf, 'bulge') else 0.0)
        else:
            return [], 0.0, "错误：无法解析多段线顶点"
        if len(vertices) < 2:
            return [], 0.0, "错误：多段线顶点数量不足"
        segments = DxfParser._build_segments(vertices, bulges)
        h_bottom_up = vertices[0][1] if vertices else 0.0
        return segments, h_bottom_up, f"成功解析DXF文件，共{len(segments)}个结构段"
    @staticmethod
    def _build_segments(vertices: List[Tuple[float, float]], 
                        bulges: List[float]) -> List[StructureSegment]:
        segments = []
        inlet = StructureSegment(
            segment_type=SegmentType.INLET,
            coordinates=[vertices[0]],
            locked=True
        )
        segments.append(inlet)
        prev_direction = None
        temp_straight_segments = []
        for i in range(len(vertices) - 1):
            p1 = vertices[i]
            p2 = vertices[i + 1]
            bulge = bulges[i] if i < len(bulges) else 0.0
            if abs(bulge) > 1e-6:
                segment = DxfParser._create_bend_segment(p1, p2, bulge)
                if temp_straight_segments:
                    segments.extend(DxfParser._process_straight_segments(temp_straight_segments))
                    temp_straight_segments = []
                    prev_direction = None
                segments.append(segment)
            else:
                length = math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
                direction = DxfParser._get_direction(p1, p2)
                straight_seg = {
                    'p1': p1,
                    'p2': p2,
                    'length': length,
                    'direction': direction
                }
                temp_straight_segments.append(straight_seg)
        if temp_straight_segments:
            segments.extend(DxfParser._process_straight_segments(temp_straight_segments))
        outlet = StructureSegment(
            segment_type=SegmentType.OUTLET,
            coordinates=[vertices[-1]],
            locked=True
        )
        segments.append(outlet)
        return segments
    @staticmethod
    def _create_bend_segment(p1: Tuple[float, float], 
                              p2: Tuple[float, float], 
                              bulge: float) -> StructureSegment:
        chord_length = math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
        angle_rad = 4 * math.atan(abs(bulge))
        angle_deg = math.degrees(angle_rad)
        if abs(math.sin(angle_rad / 2)) > 1e-6:
            radius = chord_length / (2 * math.sin(angle_rad / 2))
        else:
            radius = chord_length / 2
        arc_length = radius * angle_rad
        return StructureSegment(
            segment_type=SegmentType.BEND,
            length=arc_length,
            radius=radius,
            angle=angle_deg,
            coordinates=[p1, p2],
            locked=True
        )
    @staticmethod
    def _get_direction(p1: Tuple[float, float], 
                       p2: Tuple[float, float]) -> Tuple[float, float]:
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.sqrt(dx**2 + dy**2)
        if length > 1e-6:
            return (dx / length, dy / length)
        return (0.0, 0.0)
    @staticmethod
    def _process_straight_segments(straight_segments: list) -> List[StructureSegment]:
        if not straight_segments:
            return []
        result = []
        for i, seg in enumerate(straight_segments):
            if i == 0:
                result.append(StructureSegment(
                    segment_type=SegmentType.STRAIGHT,
                    length=seg['length'],
                    coordinates=[seg['p1'], seg['p2']],
                    locked=True
                ))
            else:
                prev_dir = straight_segments[i - 1]['direction']
                curr_dir = seg['direction']
                dot = prev_dir[0] * curr_dir[0] + prev_dir[1] * curr_dir[1]
                dot = max(-1.0, min(1.0, dot))
                angle_rad = math.acos(dot)
                angle_deg = math.degrees(angle_rad)
                if angle_deg > 1.0:
                    if result and result[-1].segment_type == SegmentType.STRAIGHT:
                        prev_seg = result[-1]
                        fold_seg = StructureSegment(
                            segment_type=SegmentType.FOLD,
                            length=prev_seg.length + seg['length'],
                            angle=angle_deg,
                            coordinates=prev_seg.coordinates + [seg['p2']],
                            locked=True
                        )
                        result[-1] = fold_seg
                    else:
                        result.append(StructureSegment(
                            segment_type=SegmentType.FOLD,
                            length=seg['length'],
                            angle=angle_deg,
                            coordinates=[seg['p1'], seg['p2']],
                            locked=True
                        ))
                else:
                    result.append(StructureSegment(
                        segment_type=SegmentType.STRAIGHT,
                        length=seg['length'],
                        coordinates=[seg['p1'], seg['p2']],
                        locked=True
                    ))
        return result
    @staticmethod
    def validate_dxf(file_path: str) -> Tuple[bool, str]:
        try:
            import ezdxf
        except ImportError:
            return False, "未安装ezdxf库"
        try:
            doc = ezdxf.readfile(file_path)
            msp = doc.modelspace()
            polylines = list(msp.query('LWPOLYLINE'))
            if not polylines:
                polylines = list(msp.query('POLYLINE'))
            if not polylines:
                return False, "文件中未找到多段线实体"
            return True, "DXF文件格式有效"
        except Exception as e:
            return False, f"文件读取失败: {str(e)}"
class HydraulicCore:
    GRAVITY = 9.81
    @staticmethod
    def round_diameter(d_theory: float) -> float:
        if d_theory <= 1.0:
            step = 0.05
        elif d_theory <= 1.6:
            step = 0.1
        else:
            step = 0.2
        return math.ceil(d_theory / step) * step
    @staticmethod
    def execute_calculation(global_params: GlobalParameters,
                           segments: List[StructureSegment],
                           diameter_override: Optional[float] = None,
                           verbose: bool = False) -> CalculationResult:
        result = CalculationResult()
        steps = []
        Q = global_params.Q
        v_guess = global_params.v_guess
        n = global_params.roughness_n
        H_up = global_params.H_up
        H_down = global_params.H_down
        g = HydraulicCore.GRAVITY
        v_1 = global_params.v_channel_in if global_params.v_channel_in > 0 else 0.0
        v_2 = global_params.v_pipe_in if global_params.v_pipe_in > 0 else 0.0
        v_out = global_params.v_channel_out if global_params.v_channel_out > 0 else 0.0
        v_3 = global_params.v_pipe_out if global_params.v_pipe_out > 0 else 0.0
        result.velocity_channel_in = v_1
        result.velocity_channel_out = v_3
        steps.append("=" * 50)
        steps.append("步骤1：几何设计与流速计算 (Geometry & Velocity)")
        steps.append("=" * 50)
        omega = Q / v_guess
        steps.append(f"管道断面积 ω = Q / v_guess = {Q:.4f} / {v_guess:.4f} = {omega:.4f} m²")
        D_theory = math.sqrt(4 * omega / math.pi)
        steps.append(f"理论直径 D = √(4ω/π) = √(4×{omega:.4f}/π) = {D_theory:.4f} m")
        if diameter_override is not None:
            D = diameter_override
            steps.append(f"使用用户指定的自定义设计管径: D = {D:.4f} m")
        else:
            D = HydraulicCore.round_diameter(D_theory)
            steps.append(f"管径取整: D = {D:.4f} m (理论值 {D_theory:.4f} m)")
        result.diameter = D
        result.diameter_theory = D_theory
        A_actual = math.pi * D ** 2 / 4
        result.area = A_actual
        steps.append(f"实际断面积 A = πD²/4 = π×{D:.4f}²/4 = {A_actual:.4f} m²")
        v = Q / A_actual
        result.velocity = v
        steps.append(f"实际流速 v = Q/A = {Q:.4f}/{A_actual:.4f} = {v:.4f} m/s")
        R_h = D / 4
        result.hydraulic_radius = R_h
        steps.append(f"水力半径 R_h = D/4 = {D:.4f}/4 = {R_h:.4f} m")
        steps.append("")
        steps.append("=" * 50)
        steps.append("步骤2：阻力参数初始化 (Resistance Setup)")
        steps.append("=" * 50)
        C = (1 / n) * (R_h ** (1/6))
        result.chezy_c = C
        steps.append(f"谢才系数 C = (1/n) × R_h^(1/6) = (1/{n:.4f}) × {R_h:.4f}^(1/6) = {C:.4f}")
        steps.append("")
        steps.append("局部阻力系数计算：")
        xi_sum_middle = 0.0
        total_length = 0.0
        for i, seg in enumerate(segments):
            if seg.segment_type == SegmentType.BEND:
                if seg.radius > 0:
                    xi_bend, bend_steps = CoefficientService.calculate_bend_coeff(
                        seg.radius, D, seg.angle, verbose=True
                    )
                    seg.xi_calc = xi_bend
                    if seg.xi_user is None:
                        steps.append(f"  弯管段{i}: R={seg.radius:.2f}m, θ={seg.angle:.1f}°")
                        steps.append(f"    {bend_steps.replace(chr(10), chr(10) + '    ')}")
                        xi_sum_middle += xi_bend
                    else:
                        xi_sum_middle += seg.xi_user
                        steps.append(f"  弯管段{i}: 使用用户值 ξ={seg.xi_user:.4f}")
                total_length += seg.length
            elif seg.segment_type == SegmentType.STRAIGHT:
                total_length += seg.length
                steps.append(f"  直管段{i}: L={seg.length:.2f}m")
            elif seg.segment_type == SegmentType.FOLD:
                total_length += seg.length
                if seg.angle > 0:
                    xi_fold, fold_steps = CoefficientService.calculate_fold_coeff(
                        seg.angle, verbose=True
                    )
                    seg.xi_calc = xi_fold
                    if seg.xi_user is None:
                        steps.append(f"  折管段{i}: L={seg.length:.2f}m, θ={seg.angle:.1f}°")
                        steps.append(f"    {fold_steps.replace(chr(10), chr(10) + '    ')}")
                        xi_sum_middle += xi_fold
                    else:
                        xi_sum_middle += seg.xi_user
                        steps.append(f"  折管段{i}: 使用用户值 ξ={seg.xi_user:.4f}")
                else:
                    xi = seg.get_xi()
                    xi_sum_middle += xi
                    steps.append(f"  折管段{i}: L={seg.length:.2f}m, θ={seg.angle:.1f}°, ξ={xi:.4f}")
            elif seg.segment_type == SegmentType.TRASH_RACK:
                xi = seg.get_xi()
                xi_sum_middle += xi
                steps.append(f"  拦污栅{i}: ξ={xi:.4f}")
            elif seg.segment_type == SegmentType.OTHER:
                xi = seg.get_xi()
                xi_sum_middle += xi
                if seg.length > 0:
                    total_length += seg.length
                steps.append(f"  其他段{i}: L={seg.length:.2f}m, ξ={xi:.4f}")
        result.total_length = total_length
        result.xi_sum_middle = xi_sum_middle
        steps.append(f"管道总长度 L = {total_length:.4f} m")
        steps.append(f"管身段局部阻力系数和 Σξ_middle = {xi_sum_middle:.4f}")
        xi_1 = global_params.xi_inlet
        xi_2 = global_params.xi_outlet
        result.xi_inlet = xi_1
        result.xi_outlet = xi_2
        steps.append(f"进口系数 ξ_1 = {xi_1:.4f} (表 L.1.2)")
        steps.append(f"出口系数 ξ_2 = {xi_2:.4f} (表 L.1.4-5 或 L.1.3)")
        steps.append("")
        steps.append("=" * 50)
        steps.append("步骤3：水头损失求解 (Head Loss Calculation)")
        steps.append("=" * 50)
        steps.append("依据规范 L.1.6: ΔZ = ΔZ1 + ΔZ2 - ΔZ3")
        steps.append("")
        steps.append("【3.1 进口渐变段水面落差 ΔZ1】")
        steps.append("  公式 L.1.2-2: ΔZ1 = (1 + ξ1) × (v₂² - v₁²) / (2g)")
        steps.append("  注: v₁ = 进口渐变段始端流速，v₂ = 进口渐变段末端流速")
        delta_Z1 = (1 + xi_1) * (v_2**2 - v_1**2) / (2 * g)
        result.loss_inlet = delta_Z1
        steps.append(f"  ΔZ1 = (1 + {xi_1:.4f}) × ({v_2:.4f}² - {v_1:.4f}²) / (2×{g})")
        steps.append(f"      = {1 + xi_1:.4f} × ({v_2**2:.4f} - {v_1**2:.4f}) / {2*g:.2f}")
        steps.append(f"      = {delta_Z1:.4f} m")
        steps.append("")
        steps.append("【3.2 管身段总水头损失 ΔZ2】")
        steps.append("  公式 L.1.4-7: ΔZ2 = hf + hj")
        steps.append("")
        h_f = (v ** 2 * total_length) / (C ** 2 * R_h)
        result.loss_friction = h_f
        steps.append("  沿程损失 hf = L × v² / (C² × R_h)")
        steps.append(f"    = {total_length:.4f} × {v:.4f}² / ({C:.4f}² × {R_h:.4f})")
        steps.append(f"    = {h_f:.4f} m")
        steps.append("")
        h_j = xi_sum_middle * v ** 2 / (2 * g)
        result.loss_local = h_j
        steps.append("  管身局部损失 hj = Σξ_middle × v² / (2g)")
        steps.append(f"    = {xi_sum_middle:.4f} × {v:.4f}² / (2×{g})")
        steps.append(f"    = {h_j:.4f} m")
        steps.append("")
        delta_Z2 = h_f + h_j
        result.loss_pipe = delta_Z2
        steps.append(f"  ΔZ2 = hf + hj = {h_f:.4f} + {h_j:.4f} = {delta_Z2:.4f} m")
        steps.append("")
        steps.append("【3.3 出口渐变段水面落差 ΔZ3】")
        steps.append("  公式 L.1.3-2: ΔZ3 = (1 - ξ2) × (v² - v₃²) / (2g)")
        steps.append("  注: v = 出口渐变段始端流速，v₃ = 出口渐变段末端流速")
        delta_Z3 = (1 - xi_2) * (v_out**2 - v_3**2) / (2 * g)
        result.loss_outlet = delta_Z3
        steps.append(f"  ΔZ3 = (1 - {xi_2:.4f}) × ({v_out:.4f}² - {v_3:.4f}²) / (2×{g})")
        steps.append(f"      = {1 - xi_2:.4f} × ({v_out**2:.4f} - {v_3**2:.4f}) / {2*g:.2f}")
        steps.append(f"      = {delta_Z3:.4f} m")
        steps.append("")
        steps.append("【3.4 总水面落差 ΔZ】")
        steps.append("  公式 L.1.6: ΔZ = ΔZ1 + ΔZ2 - ΔZ3")
        delta_Z = delta_Z1 + delta_Z2 - delta_Z3
        result.total_head_loss = delta_Z
        steps.append(f"  ΔZ = {delta_Z1:.4f} + {delta_Z2:.4f} - {delta_Z3:.4f}")
        steps.append(f"     = {delta_Z:.4f} m")
        steps.append("")
        steps.append("=" * 50)
        steps.append("步骤4：校验与结果生成 (Verification)")
        steps.append("=" * 50)
        available_head = H_up - H_down
        result.available_head_diff = available_head
        steps.append(f"可用水位差 (H_up - H_down) = {H_up:.4f} - {H_down:.4f} = {available_head:.4f} m")
        result.required_head_diff = delta_Z
        steps.append(f"所需水位差 ΔZ = {delta_Z:.4f} m")
        if available_head >= delta_Z:
            result.is_verified = True
            margin = available_head - delta_Z
            result.message = f"校验通过！可用水位差 {available_head:.4f}m >= 所需落差 {delta_Z:.4f}m，安全裕度 {margin:.4f}m"
            steps.append(f"✓ {result.message}")
        else:
            result.is_verified = False
            deficit = delta_Z - available_head
            result.message = f"校验失败！可用水位差 {available_head:.4f}m < 所需落差 {delta_Z:.4f}m，差额 {deficit:.4f}m"
            steps.append(f"✗ {result.message}")
        if verbose:
            result.calculation_steps = steps
        return result
    @staticmethod
    def format_result(result: CalculationResult, show_steps: bool = False) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append("                    计算结果汇总")
        lines.append("=" * 60)
        lines.append(f"理论管径: {result.diameter_theory:.4f} m")
        lines.append(f"设计管径: {result.diameter:.4f} m")
        lines.append(f"断面积: {result.area:.4f} m²")
        lines.append(f"管内流速 v: {result.velocity:.4f} m/s")
        lines.append(f"进口渐变段始端流速 v₁: {result.velocity_channel_in:.4f} m/s")
        lines.append(f"出口渐变段末端流速 v₃: {result.velocity_channel_out:.4f} m/s")
        lines.append(f"水力半径: {result.hydraulic_radius:.4f} m")
        lines.append(f"谢才系数: {result.chezy_c:.4f}")
        lines.append("-" * 60)
        lines.append("水头损失分解（附录L规范）：")
        lines.append(f"  进口渐变段落差 ΔZ1: {result.loss_inlet:.4f} m")
        lines.append(f"  管身段水头损失 ΔZ2: {result.loss_pipe:.4f} m")
        lines.append(f"    └ 沿程损失 hf: {result.loss_friction:.4f} m")
        lines.append(f"    └ 局部损失 hj: {result.loss_local:.4f} m")
        lines.append(f"  出口渐变段落差 ΔZ3: {result.loss_outlet:.4f} m")
        lines.append(f"  总水面落差 ΔZ: {result.total_head_loss:.4f} m")
        lines.append("-" * 60)
        lines.append(f"管道总长: {result.total_length:.4f} m")
        lines.append(f"可用水位差: {result.available_head_diff:.4f} m")
        lines.append(f"所需水位差: {result.required_head_diff:.4f} m")
        lines.append("-" * 60)
        lines.append(f"校验结果: {'通过' if result.is_verified else '失败'}")
        lines.append(f"详细信息: {result.message}")
        lines.append("=" * 60)
        if show_steps and result.calculation_steps:
            lines.append("")
            lines.append("详细计算过程：")
            lines.append("")
            lines.extend(result.calculation_steps)
        return "\n".join(lines)
class InvertedSiphonCalculator(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("倒虹吸水力计算")
        self.geometry("1200x800")
        self.minsize(1000, 700)
        self.segments: List[StructureSegment] = []
        self.calculation_result: Optional[CalculationResult] = None
        self.show_detailed_process = tk.BooleanVar(value=True)
        self._v_channel_out_user_modified = False
        self._create_ui()
        self._init_default_segments()
    def _create_ui(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._create_visual_area(main_frame)
        self._create_parameter_area(main_frame)
        self._create_operation_area(main_frame)
    def _create_visual_area(self, parent):
        visual_frame = ttk.LabelFrame(parent, text="管道剖面图", padding=5)
        visual_frame.pack(fill=tk.X, pady=(0, 5))
        toolbar = ttk.Frame(visual_frame)
        toolbar.pack(fill=tk.X, pady=(0, 5))
        zoom_frame = ttk.Frame(toolbar)
        zoom_frame.pack(side=tk.LEFT, padx=5)
        ttk.Label(zoom_frame, text="缩放:").pack(side=tk.LEFT, padx=2)
        ttk.Button(zoom_frame, text="放大", command=self._zoom_in, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(zoom_frame, text="缩小", command=self._zoom_out, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(zoom_frame, text="重置", command=self._zoom_reset, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(zoom_frame, text="适应窗口", command=self._zoom_fit, width=8).pack(side=tk.LEFT, padx=2)
        self.zoom_label = ttk.Label(zoom_frame, text="100%")
        self.zoom_label.pack(side=tk.LEFT, padx=5)
        canvas_container = ttk.Frame(visual_frame)
        canvas_container.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(canvas_container,height=250,bg='black',highlightthickness=1,highlightbackground='gray')
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.zoom_level = 1.0
        self.pan_offset_x = 0
        self.pan_offset_y = 0
        self._drag_start = None
        self.canvas.bind('<Configure>', self._on_canvas_resize)
        self.canvas.bind('<MouseWheel>', self._on_mouse_wheel)
        self.canvas.bind('<Button-4>', self._on_mouse_wheel)
        self.canvas.bind('<Button-5>', self._on_mouse_wheel)
        self.canvas.bind('<ButtonPress-1>', self._on_canvas_drag_start)
        self.canvas.bind('<B1-Motion>', self._on_canvas_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_canvas_drag_end)
    def _create_parameter_area(self, parent):
        param_frame = ttk.Frame(parent)
        param_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.notebook = ttk.Notebook(param_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self._create_basic_params_tab()
        self._create_segments_tab()
    def _create_basic_params_tab(self):
        tab1 = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab1, text="基本参数")
        left_frame = ttk.LabelFrame(tab1, text="全局水力参数", padding=10)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        right_frame = ttk.LabelFrame(tab1, text="渐变段配置", padding=10)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
        row = 0
        ttk.Label(left_frame, text="计算目标:").grid(row=row, column=0, sticky='e', pady=2)
        self.calc_target = ttk.Combobox(left_frame, values=["设计截面"], state='readonly', width=15)
        self.calc_target.set("设计截面")
        self.calc_target.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        row += 1
        ttk.Label(left_frame, text="设计流量 Q (m³/s):").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_Q = ttk.Entry(left_frame, width=15)
        self.entry_Q.insert(0, "10.0")
        self.entry_Q.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.entry_Q.bind('<KeyRelease>', self._on_Qv_changed)
        row += 1
        ttk.Label(left_frame, text="拟定流速 v (m/s):").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_v = ttk.Entry(left_frame, width=15)
        self.entry_v.insert(0, "2.0")
        self.entry_v.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.entry_v.bind('<KeyRelease>', self._on_Qv_changed)
        row += 1
        ttk.Label(left_frame, text="上游水位 (m):").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_H_up = ttk.Entry(left_frame, width=15)
        self.entry_H_up.insert(0, "100.0")
        self.entry_H_up.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.entry_H_up.bind('<KeyRelease>', self._on_water_level_changed)
        row += 1
        ttk.Label(left_frame, text="下游水位 (m):").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_H_down = ttk.Entry(left_frame, width=15)
        self.entry_H_down.insert(0, "98.0")
        self.entry_H_down.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.entry_H_down.bind('<KeyRelease>', self._on_water_level_changed)
        row += 1
        ttk.Label(left_frame, text="上游渠底高程 (m):").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_H_bottom = ttk.Entry(left_frame, width=15)
        self.entry_H_bottom.insert(0, "95.0")
        self.entry_H_bottom.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.entry_H_bottom.bind('<KeyRelease>', self._on_water_level_changed)
        row += 1
        ttk.Label(left_frame, text="糙率 n:").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_n = ttk.Entry(left_frame, width=15)
        self.entry_n.insert(0, "0.014")
        self.entry_n.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        row += 1
        ttk.Label(left_frame, text="自定义设计管径 D (m):").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_D_custom = ttk.Entry(left_frame, width=15)
        self.entry_D_custom.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.entry_D_custom.bind('<KeyRelease>', self._on_D_custom_changed)
        ttk.Label(left_frame, text="(留空则自动计算)", font=('', 8)).grid(row=row, column=2, sticky='w')
        row += 1
        row = 0
        ttk.Label(right_frame, text="进口渐变段型式:").grid(row=row, column=0, sticky='e', pady=2)
        self.combo_inlet_type = ttk.Combobox(right_frame,values=[gt.value for gt in GradientType],state='readonly',width=15)
        self.combo_inlet_type.set(GradientType.NONE.value)
        self.combo_inlet_type.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.combo_inlet_type.bind('<<ComboboxSelected>>', self._on_inlet_type_changed)
        row += 1
        ttk.Label(right_frame, text="进口局部水头损失系数 ξ₁:").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_xi_inlet = ttk.Entry(right_frame, width=15)
        self.entry_xi_inlet.insert(0, "0.0")
        self.entry_xi_inlet.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        row += 1
        ttk.Label(right_frame, text="进口渐变段始端流速v₁ (m/s):").grid(row=row, column=0, sticky='e', pady=2)
        v1_frame = tk.Frame(right_frame)
        v1_frame.grid(row=row, column=1, columnspan=2, sticky='w', pady=2, padx=5)
        self.entry_v_channel_in = ttk.Entry(v1_frame, width=15)
        self.entry_v_channel_in.insert(0, "1.0")
        self.entry_v_channel_in.pack(side=tk.LEFT)
        self.entry_v_channel_in.bind('<KeyRelease>', self._on_v_channel_in_changed)
        tk.Label(v1_frame, text="(可采用上游渠道断面平均流速)", fg='#FF6600', font=('Microsoft YaHei', 8)).pack(side=tk.LEFT, padx=(2, 0))
        row += 1
        ttk.Label(right_frame, text="进口渐变段末端流速v₂ (m/s):").grid(row=row, column=0, sticky='e', pady=2)
        v2_frame = tk.Frame(right_frame)
        v2_frame.grid(row=row, column=1, columnspan=2, sticky='w', pady=2, padx=5)
        self.entry_v_pipe_in = ttk.Entry(v2_frame, width=15)
        self.entry_v_pipe_in.insert(0, "1.2")
        self.entry_v_pipe_in.pack(side=tk.LEFT)
        self.entry_v_pipe_in.bind('<Double-Button-1>', self._open_inlet_section_dialog)
        self.entry_v_pipe_in.bind('<FocusOut>', self._validate_inlet_velocity)
        tk.Label(v2_frame, text="(双击设置断面参数自动计算)", fg='#0066CC', font=('Microsoft YaHei', 9)).pack(side=tk.LEFT, padx=(2, 0))
        row += 1
        tk.Label(right_frame, text="默认规则：未设置进口渐变段末端断面参数时，v₂ = v₁ + 0.2", fg='#666666', font=('Microsoft YaHei', 9)).grid(row=row, column=1, columnspan=2, sticky='w', pady=(0, 5), padx=5)
        row += 1
        self.inlet_section_B = None
        self.inlet_section_h = None
        self.inlet_section_m = None
        ttk.Separator(right_frame, orient='horizontal').grid(row=row, column=0, columnspan=3, sticky='ew', pady=10)
        row += 1
        ttk.Label(right_frame, text="出口渐变段型式:").grid(row=row, column=0, sticky='e', pady=2)
        self.combo_outlet_type = ttk.Combobox(right_frame,values=[gt.value for gt in GradientType],state='readonly',width=15)
        self.combo_outlet_type.set(GradientType.NONE.value)
        self.combo_outlet_type.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        self.combo_outlet_type.bind('<<ComboboxSelected>>', self._on_outlet_type_changed)
        row += 1
        ttk.Label(right_frame, text="出口局部水头损失系数 ξ₂:").grid(row=row, column=0, sticky='e', pady=2)
        self.entry_xi_outlet = ttk.Entry(right_frame, width=15)
        self.entry_xi_outlet.insert(0, "0.0")
        self.entry_xi_outlet.grid(row=row, column=1, sticky='w', pady=2, padx=5)
        row += 1
        ttk.Label(right_frame, text="出口渐变段始端流速v (m/s):").grid(row=row, column=0, sticky='e', pady=2)
        v_out_frame = tk.Frame(right_frame)
        v_out_frame.grid(row=row, column=1, columnspan=2, sticky='w', pady=2, padx=5)
        self.entry_v_channel_out = ttk.Entry(v_out_frame, width=15)
        default_v_out = self.entry_v.get().strip() or "2.0"
        self.entry_v_channel_out.insert(0, default_v_out)
        self.entry_v_channel_out.pack(side=tk.LEFT)
        self.entry_v_channel_out.bind('<KeyRelease>', self._on_v_channel_out_user_modified)
        tk.Label(v_out_frame, text="(可采用管道出口处流速)", fg='#FF6600', font=('Microsoft YaHei', 8)).pack(side=tk.LEFT, padx=(2, 0))
        row += 1
        ttk.Label(right_frame, text="出口渐变段末端流速v₃ (m/s):").grid(row=row, column=0, sticky='e', pady=2)
        v3_frame = tk.Frame(right_frame)
        v3_frame.grid(row=row, column=1, columnspan=2, sticky='w', pady=2, padx=5)
        self.entry_v_pipe_out = ttk.Entry(v3_frame, width=15)
        self.entry_v_pipe_out.insert(0, "1.8835")
        self.entry_v_pipe_out.pack(side=tk.LEFT)
        tk.Label(v3_frame, text="(可采用下游渠道断面平均流速)", fg='#FF6600', font=('Microsoft YaHei', 8)).pack(side=tk.LEFT, padx=(2, 0))
    def _get_global_params(self) -> Optional[GlobalParameters]:
        try:
            v_channel_in = float(self.entry_v_channel_in.get() or 0)
            v_pipe_in_str = self.entry_v_pipe_in.get().strip()
            if not v_pipe_in_str:
                if self.inlet_section_B is not None and self.inlet_section_h is not None and self.inlet_section_m is not None:
                    try:
                        Q = float(self.entry_Q.get())
                        v_pipe_in = self._calculate_trapezoidal_velocity(self.inlet_section_B, self.inlet_section_h, self.inlet_section_m, Q)
                    except:
                        v_pipe_in = v_channel_in + 0.2
                else:
                    v_pipe_in = v_channel_in + 0.2
            else:
                v_pipe_in = float(v_pipe_in_str)
            params = GlobalParameters(Q=float(self.entry_Q.get()),v_guess=float(self.entry_v.get()),H_up=float(self.entry_H_up.get()),H_down=float(self.entry_H_down.get()),roughness_n=float(self.entry_n.get()),inlet_type=self._get_gradient_type_by_name(self.combo_inlet_type.get()),outlet_type=self._get_gradient_type_by_name(self.combo_outlet_type.get()),v_channel_in=v_channel_in,v_pipe_in=v_pipe_in,v_channel_out=float(self.entry_v_channel_out.get() or 0),v_pipe_out=float(self.entry_v_pipe_out.get() or 0),H_bottom_up=float(self.entry_H_bottom.get() or 0),xi_inlet=float(self.entry_xi_inlet.get()),xi_outlet=float(self.entry_xi_outlet.get()))
            return params
        except ValueError as e:
            messagebox.showerror("输入错误", f"参数格式错误，请检查输入\n{str(e)}")
            return None
    def _create_segments_tab(self):
        tab2 = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab2, text="结构段信息")
        toolbar = ttk.Frame(tab2)
        toolbar.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(toolbar, text="导入 DXF", command=self._import_dxf).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="添加段", command=self._add_segment).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="删除段", command=self._delete_segment).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="清空", command=self._clear_segments).pack(side=tk.LEFT, padx=2)
        ttk.Label(toolbar, text="结构段数:").pack(side=tk.LEFT, padx=(20, 2))
        self.label_segment_count = ttk.Label(toolbar, text="0")
        self.label_segment_count.pack(side=tk.LEFT)
        table_frame = ttk.Frame(tab2)
        table_frame.pack(fill=tk.BOTH, expand=True)
        columns = ('序号', '类型', '长度(m)', '拐弯半径R(m)', '拐角θ(°)', '局部系数', '锁定')
        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=8)
        self.tree.heading('序号', text='序号')
        self.tree.heading('类型', text='类型')
        self.tree.heading('长度(m)', text='长度(m)')
        self.tree.heading('拐弯半径R(m)', text='拐弯半径R(m)')
        self.tree.heading('拐角θ(°)', text='拐角θ(°)')
        self.tree.heading('局部系数', text='局部系数')
        self.tree.heading('锁定', text='锁定')
        self.tree.column('序号', width=50, anchor='center')
        self.tree.column('类型', width=100, anchor='center')
        self.tree.column('长度(m)', width=100, anchor='center')
        self.tree.column('拐弯半径R(m)', width=120, anchor='center')
        self.tree.column('拐角θ(°)', width=100, anchor='center')
        self.tree.column('局部系数', width=100, anchor='center')
        self.tree.column('锁定', width=60, anchor='center')
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<Double-1>', self._on_tree_double_click)
        self._drag_data = {'item': None, 'index': None, 'start_y': None}
        self.tree.bind('<Button-1>', self._on_drag_start)
        self.tree.bind('<B1-Motion>', self._on_drag_motion)
        self.tree.bind('<ButtonRelease-1>', self._on_drag_release)
        info_frame = ttk.LabelFrame(tab2, text="操作说明", padding=10)
        info_frame.pack(fill=tk.X, pady=(5, 0))
        info_text = """1. 点击"导入 DXF"可从CAD文件导入管道几何
2. 点击"添加段"手动添加结构段
3. 双击表格行可编辑该行数据
4. 拖拽表格行可调整顺序（首末行除外）
5. 第一行为进水口，最后一行为出水口
6. 类型包括：进水口、直管、弯管、折管、拦污栅、闸门槽、旁通管、其他、出水口"""
        ttk.Label(info_frame, text=info_text, justify='left').pack(anchor='w')
    def _create_operation_area(self, parent):
        op_frame = ttk.Frame(parent)
        op_frame.pack(fill=tk.X, pady=(5, 0))
        formula_frame = ttk.LabelFrame(op_frame, text="计算公式", padding=5)
        formula_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        formula_text = """谢才公式: C = (1/n) × R^(1/6)
沿程损失: hf = v²L/(C²R)
局部损失: hj = Σξ × v²/(2g)
总损失: hw = hf + hj"""
        ttk.Label(formula_frame, text=formula_text, justify='left', font=('Consolas', 9)).pack()
        middle_frame = ttk.Frame(op_frame)
        middle_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
        ttk.Label(middle_frame, text="倒虹吸名称:").pack(side=tk.LEFT)
        self.entry_job_name = ttk.Entry(middle_frame, width=30)
        self.entry_job_name.insert(0, "倒虹吸水力计算")
        self.entry_job_name.pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(middle_frame,text="输出详细计算过程",variable=self.show_detailed_process).pack(side=tk.LEFT, padx=20)
        btn_frame = ttk.Frame(op_frame)
        btn_frame.pack(side=tk.RIGHT)
        self.btn_calculate = ttk.Button(btn_frame, text="计算", command=self._execute_calculation, width=12)
        self.btn_calculate.pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="导出结果", command=self._export_result, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="关闭", command=self.destroy, width=12).pack(side=tk.LEFT, padx=2)
    def _init_default_segments(self):
        inlet_shape = InletOutletShape.SLIGHTLY_ROUNDED
        inlet_xi = sum(INLET_SHAPE_COEFFICIENTS[inlet_shape]) / 2
        outlet_xi = 0.0
        self.segments = [
            StructureSegment(segment_type=SegmentType.INLET, locked=True, inlet_shape=inlet_shape, xi_calc=inlet_xi),
            StructureSegment(segment_type=SegmentType.TRASH_RACK, length=1.0),
            StructureSegment(segment_type=SegmentType.GATE_SLOT, length=0.5),
            StructureSegment(segment_type=SegmentType.BYPASS_PIPE, xi_user=0.1),
            StructureSegment(segment_type=SegmentType.FOLD, length=5.0),
            StructureSegment(segment_type=SegmentType.STRAIGHT, length=50.0),
            StructureSegment(segment_type=SegmentType.BEND, length=10.0, radius=5.0, angle=45.0),
            StructureSegment(segment_type=SegmentType.STRAIGHT, length=100.0),
            StructureSegment(segment_type=SegmentType.BEND, length=10.0, radius=5.0, angle=45.0),
            StructureSegment(segment_type=SegmentType.STRAIGHT, length=50.0),
            StructureSegment(segment_type=SegmentType.OTHER, xi_user=0.1),
            StructureSegment(segment_type=SegmentType.OUTLET, locked=True, xi_calc=outlet_xi)
        ]
        self._refresh_tree()
    def _refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, seg in enumerate(self.segments):
            xi = seg.xi_user if seg.xi_user is not None else (seg.xi_calc if seg.xi_calc is not None else '--')
            if isinstance(xi, float):
                xi = f"{xi:.4f}"
            type_display = seg.segment_type.value
            if seg.segment_type == SegmentType.INLET and seg.inlet_shape:
                type_display = f"进水口({seg.inlet_shape.value})"
            elif seg.segment_type == SegmentType.OUTLET:
                type_display = "出水口"
            values = (i + 1,type_display,f"{seg.length:.2f}" if seg.length > 0 else '--',f"{seg.radius:.2f}" if seg.radius > 0 else '--',f"{seg.angle:.1f}" if seg.angle > 0 else '--',xi,'是' if seg.locked else '否')
            self.tree.insert('', 'end', values=values)
        self.label_segment_count.config(text=str(len(self.segments)))
        self._draw_pipeline()
    def _on_inlet_type_changed(self, event=None):
        type_name = self.combo_inlet_type.get()
        gradient_type = self._get_gradient_type_by_name(type_name)
        coeff = CoefficientService.get_gradient_coeff(gradient_type, True)
        self.entry_xi_inlet.delete(0, tk.END)
        self.entry_xi_inlet.insert(0, f"{coeff:.4f}")
        if self.segments and self.segments[0].segment_type == SegmentType.INLET:
            self.segments[0].xi_calc = coeff
            self._refresh_tree()
    def _on_outlet_type_changed(self, event=None):
        type_name = self.combo_outlet_type.get()
        gradient_type = self._get_gradient_type_by_name(type_name)
        coeff = CoefficientService.get_gradient_coeff(gradient_type, False)
        self.entry_xi_outlet.delete(0, tk.END)
        self.entry_xi_outlet.insert(0, f"{coeff:.4f}")
        if self.segments and self.segments[-1].segment_type == SegmentType.OUTLET:
            self.segments[-1].xi_calc = coeff
            self._refresh_tree()
    def _get_gradient_type_by_name(self, name: str) -> GradientType:
        for gt in GradientType:
            if gt.value == name:
                return gt
        return GradientType.NONE
    def _calculate_trapezoidal_velocity(self, B: float, h: float, m: float, Q: float) -> float:
        area = (B + m * h) * h
        if area <= 0:
            return 0.0
        velocity = Q / area
        return velocity
    def _on_v_channel_in_changed(self, event=None):
        try:
            if self.inlet_section_B is not None and self.inlet_section_h is not None and self.inlet_section_m is not None:
                self._on_inlet_section_changed()
                return
            v1_str = self.entry_v_channel_in.get().strip()
            if not v1_str:
                return
            v1 = float(v1_str)
            if v1 <= 0:
                return
            v2 = v1 + 0.2
            self.entry_v_pipe_in.delete(0, tk.END)
            self.entry_v_pipe_in.insert(0, f"{v2:.4f}")
        except ValueError:
            pass
    def _on_inlet_section_changed(self, event=None):
        try:
            if self.inlet_section_B is None or self.inlet_section_h is None or self.inlet_section_m is None:
                return
            Q = float(self.entry_Q.get())
            if self.inlet_section_B <= 0 or self.inlet_section_h <= 0 or self.inlet_section_m < 0 or Q <= 0:
                return
            v2 = self._calculate_trapezoidal_velocity(self.inlet_section_B, self.inlet_section_h, self.inlet_section_m, Q)
            self.entry_v_pipe_in.delete(0, tk.END)
            self.entry_v_pipe_in.insert(0, f"{v2:.4f}")
        except ValueError:
            pass
    def _open_inlet_section_dialog(self, event=None):
        try:
            Q = float(self.entry_Q.get())
            if Q <= 0:
                messagebox.showwarning("参数错误", "请先设置有效的设计流量Q")
                return
        except ValueError:
            messagebox.showwarning("参数错误", "请先设置有效的设计流量Q")
            return
        dialog = InletSectionDialog(self, Q=Q,B=self.inlet_section_B,h=self.inlet_section_h,m=self.inlet_section_m)
        self.wait_window(dialog)
        if hasattr(dialog, 'result_B'):
            self.inlet_section_B = dialog.result_B
            self.inlet_section_h = dialog.result_h
            self.inlet_section_m = dialog.result_m
            if dialog.result_velocity is not None:
                self.entry_v_pipe_in.delete(0, tk.END)
                self.entry_v_pipe_in.insert(0, f"{dialog.result_velocity:.4f}")
                self._validate_inlet_velocity()
            elif self.inlet_section_B is None:
                self._on_v_channel_in_changed()
    def _validate_inlet_velocity(self, event=None):
        try:
            v1_str = self.entry_v_channel_in.get().strip()
            v2_str = self.entry_v_pipe_in.get().strip()
            if not v1_str or not v2_str:
                return
            v1 = float(v1_str)
            v2 = float(v2_str)
            if v2 <= v1:
                messagebox.showwarning("错误", "进口渐变段末端流速必须大于始端流速!")
        except ValueError:
            pass
    def _import_dxf(self):
        file_path = filedialog.askopenfilename(title="选择DXF文件",filetypes=[("DXF文件", "*.dxf"), ("所有文件", "*.*")])
        if not file_path:
            return
        segments, h_bottom, message = DxfParser.parse_dxf(file_path)
        if not segments:
            messagebox.showerror("导入失败", message)
            return
        self.segments = segments
        self._refresh_tree()
        self.entry_H_bottom.delete(0, tk.END)
        self.entry_H_bottom.insert(0, f"{h_bottom:.2f}")
        messagebox.showinfo("导入成功", f"{message}\n建议上游渠底高程: {h_bottom:.2f}m")
    def _add_segment(self):
        try:
            Q = float(self.entry_Q.get())
            v = float(self.entry_v.get())
        except ValueError:
            Q = 10.0
            v = 2.0
        dialog = SegmentEditDialog(self, "添加结构段", Q=Q, v=v)
        self.wait_window(dialog)
        if dialog.result:
            if self.segments and self.segments[-1].segment_type == SegmentType.OUTLET:
                self.segments.insert(-1, dialog.result)
            else:
                self.segments.append(dialog.result)
            self._refresh_tree()
    def _delete_segment(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择要删除的行")
            return
        item = selection[0]
        index = self.tree.index(item)
        if self.segments[index].segment_type in [SegmentType.INLET, SegmentType.OUTLET]:
            messagebox.showwarning("提示", "不能删除进水口或出水口")
            return
        if messagebox.askyesno("确认", "确定要删除选中的结构段吗？"):
            del self.segments[index]
            self._refresh_tree()
    def _clear_segments(self):
        if messagebox.askyesno("确认", "确定要清空所有结构段吗？"):
            self._init_default_segments()
    def _on_drag_start(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        index = self.tree.index(item)
        if index == 0 or index == len(self.segments) - 1:
            self._drag_data = {'item': None, 'index': None, 'start_y': None}
            return
        self._drag_data = {'item': item,'index': index,'start_y': event.y}
        self.tree.selection_set(item)
    def _on_drag_motion(self, event):
        if not self._drag_data['item']:
            return
        target_item = self.tree.identify_row(event.y)
        if not target_item:
            return
        target_index = self.tree.index(target_item)
        current_index = self._drag_data['index']
        if target_index == 0 or target_index == len(self.segments) - 1:
            return
        if target_index != current_index:
            self.segments[current_index], self.segments[target_index] = self.segments[target_index], self.segments[current_index]
            self._drag_data['index'] = target_index
            self._refresh_tree()
            children = self.tree.get_children()
            if target_index < len(children):
                self._drag_data['item'] = children[target_index]
                self.tree.selection_set(children[target_index])
    def _on_drag_release(self, event):
        self._drag_data = {'item': None, 'index': None, 'start_y': None}
    def _on_tree_double_click(self, event):
        selection = self.tree.selection()
        if not selection:
            return
        item = selection[0]
        index = self.tree.index(item)
        segment = self.segments[index]
        if segment.segment_type == SegmentType.INLET:
            dialog = InletShapeDialog(self, segment)
            self.wait_window(dialog)
            if dialog.result:
                self.segments[index] = dialog.result
                self._refresh_tree()
            return
        if segment.segment_type == SegmentType.OUTLET:
            try:
                Q = float(self.entry_Q.get())
                v = float(self.entry_v.get())
            except ValueError:
                Q = 10.0
                v = 2.0
            dialog = OutletShapeDialog(self, segment, Q=Q, v=v)
            self.wait_window(dialog)
            if dialog.result:
                self.segments[index] = dialog.result
                self._refresh_tree()
            return
        if segment.locked:
            if not messagebox.askyesno("提示", "该行已锁定（从DXF导入），确定要编辑吗？"):
                return
        try:
            Q = float(self.entry_Q.get())
            v = float(self.entry_v.get())
        except ValueError:
            Q = 10.0
            v = 2.0
        dialog = SegmentEditDialog(self, "编辑结构段", segment, Q=Q, v=v)
        self.wait_window(dialog)
        if dialog.result:
            self.segments[index] = dialog.result
            self._refresh_tree()
    def _get_global_params(self) -> Optional[GlobalParameters]:
        try:
            v_channel_in = float(self.entry_v_channel_in.get() or 0)
            v_pipe_in_str = self.entry_v_pipe_in.get().strip()
            if not v_pipe_in_str:
                if self.inlet_section_B is not None and self.inlet_section_h is not None and self.inlet_section_m is not None:
                    try:
                        Q = float(self.entry_Q.get())
                        v_pipe_in = self._calculate_trapezoidal_velocity(self.inlet_section_B, self.inlet_section_h, self.inlet_section_m, Q)
                    except:
                        v_pipe_in = v_channel_in + 0.2
                else:
                    v_pipe_in = v_channel_in + 0.2
            else:
                v_pipe_in = float(v_pipe_in_str)
            params = GlobalParameters(Q=float(self.entry_Q.get()),v_guess=float(self.entry_v.get()),H_up=float(self.entry_H_up.get()),H_down=float(self.entry_H_down.get()),roughness_n=float(self.entry_n.get()),inlet_type=self._get_gradient_type_by_name(self.combo_inlet_type.get()),outlet_type=self._get_gradient_type_by_name(self.combo_outlet_type.get()),v_channel_in=v_channel_in,v_pipe_in=v_pipe_in,v_channel_out=float(self.entry_v_channel_out.get() or 0),v_pipe_out=float(self.entry_v_pipe_out.get() or 0),H_bottom_up=float(self.entry_H_bottom.get() or 0),xi_inlet=float(self.entry_xi_inlet.get()),xi_outlet=float(self.entry_xi_outlet.get()))
            return params
        except ValueError as e:
            messagebox.showerror("输入错误", f"参数格式错误，请检查输入\n{str(e)}")
            return None
    def _execute_calculation(self):
        params = self._get_global_params()
        if params is None:
            return
        if params.Q <= 0:
            messagebox.showerror("输入错误", "设计流量必须大于0")
            return
        if params.v_guess <= 0:
            messagebox.showerror("输入错误", "拟定流速必须大于0")
            return
        diameter_override = None
        custom_d = self.entry_D_custom.get().strip()
        if custom_d:
            try:
                diameter_override = float(custom_d)
            except ValueError:
                messagebox.showerror("输入错误", "自定义设计管径格式错误")
                return
        self.config(cursor='wait')
        self.update()
        try:
            result = HydraulicCore.execute_calculation(params,self.segments,diameter_override=diameter_override,verbose=self.show_detailed_process.get())
            self.calculation_result = result
            self._refresh_tree()
            self._show_result(result)
        except Exception as e:
            messagebox.showerror("计算错误", f"计算过程发生错误:\n{str(e)}")
        finally:
            self.config(cursor='')
    def _show_result(self, result: CalculationResult):
        result_window = tk.Toplevel(self)
        result_window.title("计算结果")
        result_window.geometry("700x600")
        result_window.transient(self)
        text_frame = ttk.Frame(result_window, padding=10)
        text_frame.pack(fill=tk.BOTH, expand=True)
        text = tk.Text(text_frame, wrap=tk.WORD, font=('Consolas', 10))
        scrollbar = ttk.Scrollbar(text_frame, orient='vertical', command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        result_text = HydraulicCore.format_result(result, show_steps=self.show_detailed_process.get())
        text.insert('1.0', result_text)
        text.config(state='disabled')
        ttk.Button(result_window, text="关闭", command=result_window.destroy).pack(pady=10)
    def _export_result(self):
        if not self.calculation_result:
            messagebox.showwarning("提示", "请先执行计算")
            return
        file_path = filedialog.asksaveasfilename(title="保存结果",defaultextension=".txt",filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not file_path:
            return
        try:
            result_text = HydraulicCore.format_result(self.calculation_result,show_steps=self.show_detailed_process.get())
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(f"倒虹吸名称: {self.entry_job_name.get()}\n\n")
                f.write(result_text)
            messagebox.showinfo("导出成功", f"结果已保存到:\n{file_path}")
        except Exception as e:
            messagebox.showerror("导出失败", f"保存文件时发生错误:\n{str(e)}")
    def _on_water_level_changed(self, event=None):
        if hasattr(self, '_redraw_pending'):
            self.after_cancel(self._redraw_pending)
        self._redraw_pending = self.after(100, self._draw_pipeline)
    def _on_Qv_changed(self, event=None):
        if hasattr(self, '_update_xi_pending'):
            self.after_cancel(self._update_xi_pending)
        self._update_xi_pending = self.after(200, self._update_after_Q_changed)
    def _update_after_Q_changed(self):
        self._update_segment_coefficients()
        self._on_inlet_section_changed()
        self._update_v_channel_out_default()
    def _on_v_channel_out_user_modified(self, event=None):
        self._v_channel_out_user_modified = True
    def _update_v_channel_out_default(self):
        if self._v_channel_out_user_modified:
            return
        try:
            v = self.entry_v.get().strip()
            if v:
                self.entry_v_channel_out.delete(0, tk.END)
                self.entry_v_channel_out.insert(0, v)
        except Exception:
            pass
    def _on_D_custom_changed(self, event=None):
        custom_d = self.entry_D_custom.get().strip()
        if custom_d:
            self.entry_v.configure(state='disabled')
        else:
            self.entry_v.configure(state='normal')
        if hasattr(self, '_update_xi_pending'):
            self.after_cancel(self._update_xi_pending)
        self._update_xi_pending = self.after(200, self._update_segment_coefficients)
    def _update_segment_coefficients(self):
        try:
            Q = float(self.entry_Q.get())
            v = float(self.entry_v.get())
        except ValueError:
            return
        if Q <= 0 or v <= 0:
            return
        custom_d = self.entry_D_custom.get().strip()
        if custom_d:
            try:
                D = float(custom_d)
            except ValueError:
                omega = Q / v
                D = math.sqrt(4 * omega / math.pi)
        else:
            omega = Q / v
            D = math.sqrt(4 * omega / math.pi)
        if D <= 0:
            return
        updated = False
        for seg in self.segments:
            if seg.segment_type == SegmentType.BEND and seg.radius > 0 and seg.angle > 0:
                if seg.xi_user is None:
                    xi_bend = CoefficientService.calculate_bend_coeff(seg.radius, D, seg.angle, verbose=False)
                    seg.xi_calc = xi_bend
                    updated = True
        if updated:
            self._refresh_tree()
    def _on_canvas_resize(self, event):
        self._draw_pipeline()
    def _zoom_in(self):
        self.zoom_level = min(5.0, self.zoom_level * 1.2)
        self._update_zoom_label()
        self._draw_pipeline()
    def _zoom_out(self):
        self.zoom_level = max(0.2, self.zoom_level / 1.2)
        self._update_zoom_label()
        self._draw_pipeline()
    def _zoom_reset(self):
        self.zoom_level = 1.0
        self.pan_offset_x = 0
        self.pan_offset_y = 0
        self._update_zoom_label()
        self._draw_pipeline()
    def _zoom_fit(self):
        self.zoom_level = 1.0
        self.pan_offset_x = 0
        self.pan_offset_y = 0
        self._update_zoom_label()
        self._draw_pipeline()
    def _update_zoom_label(self):
        if hasattr(self, 'zoom_label'):
            self.zoom_label.config(text=f"{int(self.zoom_level * 100)}%")
    def _on_mouse_wheel(self, event):
        mouse_x = event.x
        mouse_y = event.y
        if event.num == 4 or (hasattr(event, 'delta') and event.delta > 0):
            factor = 1.15
        else:
            factor = 1 / 1.15
        new_zoom = self.zoom_level * factor
        if 0.2 <= new_zoom <= 5.0:
            canvas_center_x = self.canvas.winfo_width() / 2
            canvas_center_y = self.canvas.winfo_height() / 2
            dx = mouse_x - canvas_center_x - self.pan_offset_x
            dy = mouse_y - canvas_center_y - self.pan_offset_y
            old_zoom = self.zoom_level
            self.zoom_level = new_zoom
            scale_change = new_zoom / old_zoom
            self.pan_offset_x -= dx * (scale_change - 1)
            self.pan_offset_y -= dy * (scale_change - 1)
            self._update_zoom_label()
            self._draw_pipeline()
    def _on_canvas_drag_start(self, event):
        self._drag_start = (event.x, event.y)
    def _on_canvas_drag(self, event):
        if self._drag_start:
            dx = event.x - self._drag_start[0]
            dy = event.y - self._drag_start[1]
            self.pan_offset_x += dx
            self.pan_offset_y += dy
            self._drag_start = (event.x, event.y)
            self._draw_pipeline()
    def _on_canvas_drag_end(self, event):
        self._drag_start = None
    def _draw_pipeline(self):
        self.canvas.delete('all')
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width < 10 or height < 10:
            return
        all_coords = []
        for seg in self.segments:
            all_coords.extend(seg.coordinates)
        if not all_coords:
            self._draw_simplified_pipeline(width, height)
            return
        xs = [c[0] for c in all_coords]
        ys = [c[1] for c in all_coords]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        try:
            H_up = float(self.entry_H_up.get())
            H_down = float(self.entry_H_down.get())
            min_y = min(min_y, H_down - 5)
            max_y = max(max_y, H_up + 5)
        except:
            H_up = 100.0
            H_down = 98.0
        margin = 50
        data_width = max_x - min_x if max_x > min_x else 1
        data_height = max_y - min_y if max_y > min_y else 1
        base_scale_x = (width - 2 * margin) / data_width
        base_scale_y = (height - 2 * margin) / data_height
        base_scale = min(base_scale_x, base_scale_y)
        scale = base_scale * self.zoom_level
        center_x = width / 2 + self.pan_offset_x
        center_y = height / 2 + self.pan_offset_y
        data_center_x = (min_x + max_x) / 2
        data_center_y = (min_y + max_y) / 2
        def transform(x, y):
            sx = center_x + (x - data_center_x) * scale
            sy = center_y - (y - data_center_y) * scale
            return sx, sy
        points = []
        for coord in all_coords:
            points.append(transform(coord[0], coord[1]))
        if len(points) >= 2:
            for i in range(len(points) - 1):
                self.canvas.create_line(points[i][0], points[i][1],points[i + 1][0], points[i + 1][1],fill='#00FF00', width=3)
        if points:
            self._draw_inlet_shape(points[0][0], points[0][1], scale, is_inlet=True)
            self._draw_outlet_shape(points[-1][0], points[-1][1], scale, is_inlet=False)
        try:
            x_up, y_up = transform(min_x, H_up)
            line_length = 80 * self.zoom_level
            self.canvas.create_line(x_up - line_length/2, y_up, x_up + line_length/2, y_up, fill='#00FFFF', width=2)
            self._draw_water_symbol(x_up, y_up, "上游水位", H_up)
            x_down, y_down = transform(max_x, H_down)
            self.canvas.create_line(x_down - line_length/2, y_down, x_down + line_length/2, y_down,fill='#00FFFF', width=2)
            self._draw_water_symbol(x_down, y_down, "下游水位", H_down)
        except:
            pass
        total_length = sum(seg.length for seg in self.segments if seg.length > 0)
        info_text = f"总长度: {total_length:.1f}m | 结构段: {len(self.segments)} | 水位差: {H_up - H_down:.2f}m | 缩放: {int(self.zoom_level * 100)}%"
        self.canvas.create_text(width / 2, height - 10, text=info_text, fill='#AAAAAA', font=('', 9))
    def _draw_simplified_pipeline(self, width, height):
        margin = 50
        total_length = sum(seg.length for seg in self.segments if seg.length > 0)
        if total_length <= 0:
            total_length = 100
        try:
            H_up = float(self.entry_H_up.get())
            H_down = float(self.entry_H_down.get())
            H_bottom = float(self.entry_H_bottom.get())
        except:
            H_up = 100.0
            H_down = 98.0
            H_bottom = 95.0
        siphon_depth = max(5, (H_up - H_down) * 2)
        H_lowest = H_bottom - siphon_depth
        points = []
        segment_positions = []
        current_x = 0.0
        seg_lengths = []
        for seg in self.segments:
            if seg.segment_type in [SegmentType.INLET, SegmentType.OUTLET]:
                seg_lengths.append(0)
            else:
                seg_lengths.append(seg.length if seg.length > 0 else 5)
        num_segs = len(self.segments)
        for i, seg in enumerate(self.segments):
            progress = current_x / total_length if total_length > 0 else 0
            current_y = H_bottom - siphon_depth * math.sin(math.pi * progress)
            segment_positions.append((current_x, current_y, seg.segment_type.value))
            points.append((current_x, current_y))
            if seg.segment_type == SegmentType.INLET:
                pass
            elif seg.segment_type == SegmentType.OUTLET:
                pass
            else:
                current_x += seg.length if seg.length > 0 else 5
        if points:
            end_y = H_bottom - siphon_depth * math.sin(math.pi * 1.0)
            points.append((total_length, H_bottom - (H_up - H_down) * 0.5))
        if len(points) < 5:
            smooth_points = []
            for t in [0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.0]:
                x = t * total_length
                y = H_bottom - siphon_depth * math.sin(math.pi * t)
                smooth_points.append((x, y))
            points = smooth_points
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        min_y = min(min_y, H_lowest - 2)
        max_y = max(max_y, H_up + 5)
        data_width = max_x - min_x if max_x > min_x else 1
        data_height = max_y - min_y if max_y > min_y else 1
        base_scale_x = (width - 2 * margin) / data_width
        base_scale_y = (height - 2 * margin) / data_height
        base_scale = min(base_scale_x, base_scale_y)
        scale = base_scale * self.zoom_level
        center_x = width / 2 + self.pan_offset_x
        center_y = height / 2 + self.pan_offset_y
        data_center_x = (min_x + max_x) / 2
        data_center_y = (min_y + max_y) / 2
        def transform(x, y):
            sx = center_x + (x - data_center_x) * scale
            sy = center_y - (y - data_center_y) * scale
            return sx, sy
        canvas_points = [transform(p[0], p[1]) for p in points]
        if len(canvas_points) >= 2:
            flat_points = []
            for pt in canvas_points:
                flat_points.extend([pt[0], pt[1]])
            if len(flat_points) >= 4:
                self.canvas.create_line(flat_points, fill='#00FF00', width=3, smooth=True)
        for i, (x, y, seg_name) in enumerate(segment_positions):
            cx, cy = transform(x, y)
            self.canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill='#00FF00', outline='white', width=1)
        if canvas_points:
            start_pt = canvas_points[0]
            end_pt = canvas_points[-1]
            self._draw_inlet_shape(start_pt[0], start_pt[1], scale, is_inlet=True)
            self.canvas.create_text(start_pt[0], start_pt[1] - 45, text="进水口", fill='cyan', anchor='s', font=('', 9))
            self._draw_outlet_shape(end_pt[0], end_pt[1], scale, is_inlet=False)
            self.canvas.create_text(end_pt[0], end_pt[1] - 45, text="出水口", fill='cyan', anchor='s', font=('', 9))
        try:
            x_up, y_up = transform(min_x, H_up)
            line_length = 80 * self.zoom_level
            self.canvas.create_line(x_up - line_length/2, y_up, x_up + line_length/2, y_up, fill='#00FFFF', width=2, dash=(5, 3))
            self._draw_water_symbol(x_up, y_up, "上游水位", H_up)
            x_down, y_down = transform(max_x, H_down)
            self.canvas.create_line(x_down - line_length/2, y_down, x_down + line_length/2, y_down,fill='#00FFFF', width=2, dash=(5, 3))
            self._draw_water_symbol(x_down, y_down, "下游水位", H_down)
            x_b1, y_b = transform(min_x, H_bottom)
            x_b2, _ = transform(max_x, H_bottom)
            self.canvas.create_line(x_b1, y_b, x_b2, y_b, fill='#666666', width=1, dash=(3, 3))
            self.canvas.create_text(x_b1 + 5, y_b + 12, text=f"渠底 {H_bottom:.1f}m", fill='#888888', anchor='w', font=('', 8))
        except:
            pass
        total_length = sum(seg.length for seg in self.segments if seg.length > 0)
        info_text = f"总长度: {total_length:.1f}m | 结构段: {len(self.segments)} | 水位差: {H_up - H_down:.2f}m | 缩放: {int(self.zoom_level * 100)}%"
        self.canvas.create_text(width / 2, height - 10, text=info_text, fill='#AAAAAA', font=('', 9))
    def _draw_water_symbol(self, x, y, label, value):
        size = 10
        points = [x, y - size, x - size, y + size, x + size, y + size]
        self.canvas.create_polygon(points, fill='#00FFFF', outline='white', width=1)
        self.canvas.create_text(x, y - size - 5, text=f"{label}", fill='#00FFFF', anchor='s', font=('', 9, 'bold'))
        self.canvas.create_text(x, y + size + 12, text=f"{value:.2f}m", fill='#FFFF00', anchor='n', font=('', 9))
    def _draw_inlet_shape(self, x, y, scale, is_inlet=True):
        inlet_shape = None
        if self.segments and self.segments[0].segment_type == SegmentType.INLET:
            inlet_shape = self.segments[0].inlet_shape
        if inlet_shape is None:
            inlet_shape = InletOutletShape.SLIGHTLY_ROUNDED
        self._draw_inlet_profile(x, y, inlet_shape)
    def _draw_outlet_shape(self, x, y, scale, is_inlet=False):
        outlet_shape = None
        if self.segments and self.segments[-1].segment_type == SegmentType.OUTLET:
            outlet_shape = self.segments[-1].outlet_shape
        if outlet_shape is None:
            outlet_shape = InletOutletShape.SLIGHTLY_ROUNDED
        self._draw_outlet_profile(x, y, outlet_shape)
    def _draw_inlet_profile(self, x, y, inlet_shape):
        base_size = max(12, 20 * min(self.zoom_level, 2.0))
        wall_length = base_size * 2.0
        wall_thickness = 3
        pipe_half_height = base_size * 0.4
        if inlet_shape == InletOutletShape.FULLY_ROUNDED:
            curve_length = base_size * 1.2
            self.canvas.create_line(x - wall_length, y - base_size, x - curve_length, y - base_size,fill='#00FF00', width=wall_thickness)
            points_upper = []
            for i in range(15):
                t = i / 14.0
                cx = x - curve_length + curve_length * t
                cy = y - base_size + (base_size - pipe_half_height) * (t ** 0.5)
                points_upper.extend([cx, cy])
            if len(points_upper) >= 4:
                self.canvas.create_line(points_upper, fill='#00FF00', width=wall_thickness, smooth=True)
            self.canvas.create_line(x - wall_length, y + pipe_half_height, x, y + pipe_half_height,fill='#00FF00', width=wall_thickness)
            self._draw_hatch_lines(x - wall_length, y - base_size - 5, x - curve_length, y - base_size, is_upper=True)
        elif inlet_shape == InletOutletShape.SLIGHTLY_ROUNDED:
            curve_length = base_size * 0.6
            self.canvas.create_line(x - wall_length, y - base_size, x - curve_length, y - base_size,fill='#00FF00', width=wall_thickness)
            points_upper = []
            for i in range(10):
                t = i / 9.0
                cx = x - curve_length + curve_length * t
                cy = y - base_size + (base_size - pipe_half_height) * (t ** 0.3)
                points_upper.extend([cx, cy])
            if len(points_upper) >= 4:
                self.canvas.create_line(points_upper, fill='#00FF00', width=wall_thickness, smooth=True)
            self.canvas.create_line(x - wall_length, y + pipe_half_height, x, y + pipe_half_height,fill='#00FF00', width=wall_thickness)
            self._draw_hatch_lines(x - wall_length, y - base_size - 5, x - curve_length, y - base_size, is_upper=True)
        elif inlet_shape == InletOutletShape.NOT_ROUNDED:
            self.canvas.create_line(x - wall_length, y - base_size, x, y - base_size,fill='#00FF00', width=wall_thickness)
            self.canvas.create_line(x, y - base_size, x, y - pipe_half_height,fill='#00FF00', width=wall_thickness)
            self.canvas.create_line(x - wall_length, y + pipe_half_height, x, y + pipe_half_height,fill='#00FF00', width=wall_thickness)
            self._draw_hatch_lines(x - wall_length, y - base_size - 5, x, y - base_size, is_upper=True)
    def _draw_outlet_profile(self, x, y, outlet_shape):
        base_size = max(12, 20 * min(self.zoom_level, 2.0))
        wall_length = base_size * 2.0
        wall_thickness = 3
        pipe_half_height = base_size * 0.4
        if outlet_shape == InletOutletShape.FULLY_ROUNDED:
            curve_length = base_size * 1.2
            self.canvas.create_line(x + curve_length, y - base_size, x + wall_length, y - base_size,fill='#00FF00', width=wall_thickness)
            radius = base_size * 0.8
            self.canvas.create_arc(x + curve_length - radius, y - base_size, x + curve_length + radius, y - base_size + 2*radius,start=270, extent=90, style='arc',outline='#00FF00', width=wall_thickness)
            self.canvas.create_line(x, y - pipe_half_height, x + curve_length - radius, y - pipe_half_height,fill='#00FF00', width=wall_thickness)
            self.canvas.create_line(x, y + pipe_half_height, x + wall_length, y + pipe_half_height,fill='#00FF00', width=wall_thickness)
            self._draw_hatch_lines(x + curve_length, y - base_size - 5, x + wall_length, y - base_size, is_upper=True)
        elif outlet_shape == InletOutletShape.SLIGHTLY_ROUNDED:
            curve_length = base_size * 0.6
            self.canvas.create_line(x + curve_length, y - base_size, x + wall_length, y - base_size,fill='#00FF00', width=wall_thickness)
            radius = base_size * 0.4
            self.canvas.create_arc(x + curve_length - radius, y - base_size,x + curve_length + radius, y - base_size + 2*radius,start=270, extent=90, style='arc',outline='#00FF00', width=wall_thickness)
            self.canvas.create_line(x, y - pipe_half_height, x + curve_length - radius, y - pipe_half_height,fill='#00FF00', width=wall_thickness)
            self.canvas.create_line(x, y + pipe_half_height, x + wall_length, y + pipe_half_height,fill='#00FF00', width=wall_thickness)
            self._draw_hatch_lines(x + curve_length, y - base_size - 5, x + wall_length, y - base_size, is_upper=True)
        elif outlet_shape == InletOutletShape.NOT_ROUNDED:
            self.canvas.create_line(x, y - base_size, x + wall_length, y - base_size,fill='#00FF00', width=wall_thickness)
            self.canvas.create_line(x, y - base_size, x, y - pipe_half_height,fill='#00FF00', width=wall_thickness)
            self.canvas.create_line(x, y + pipe_half_height, x + wall_length, y + pipe_half_height,fill='#00FF00', width=wall_thickness)
            self._draw_hatch_lines(x, y - base_size - 5, x + wall_length, y - base_size, is_upper=True)
    def _draw_hatch_lines(self, x1, y1, x2, y2, is_upper=True):
        spacing = 6
        num_lines = int(abs(x2 - x1) / spacing)
        for i in range(num_lines + 1):
            lx = x1 + i * spacing
            if lx > x2:
                break
            if is_upper:
                self.canvas.create_line(lx, y2, lx + 5, y1, fill='#00FF00', width=1)
            else:
                self.canvas.create_line(lx, y1, lx + 5, y2, fill='#00FF00', width=1)
class SegmentEditDialog(tk.Toplevel):
    def __init__(self, parent, title: str, segment: Optional[StructureSegment] = None, Q: float = 10.0, v: float = 2.0):
        super().__init__(parent)
        self.title(title)
        self.geometry("520x350")
        self.transient(parent)
        self.grab_set()
        self.result: Optional[StructureSegment] = None
        self.segment = segment
        self._user_modified_xi = False
        self._loading_data = False
        self._Q = Q
        self._v = v
        self._D_theory = self._calculate_theory_diameter()
        self._create_ui()
        if segment:
            self._load_segment(segment)
        else:
            self._on_type_changed()
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    def _calculate_theory_diameter(self) -> float:
        if self._Q > 0 and self._v > 0:
            omega = self._Q / self._v
            return math.sqrt(4 * omega / math.pi)
        return 0.0
    def _create_ui(self):
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        row = 0
        ttk.Label(frame, text="类型:").grid(row=row, column=0, sticky='e', pady=5)
        self.combo_type = ttk.Combobox(frame,values=[st.value for st in SegmentType if st not in [SegmentType.INLET, SegmentType.OUTLET]],state='readonly',width=20)
        self.combo_type.set(SegmentType.STRAIGHT.value)
        self.combo_type.grid(row=row, column=1, sticky='w', pady=5, padx=10)
        self.combo_type.bind('<<ComboboxSelected>>', self._on_type_changed)
        row += 1
        ttk.Label(frame, text="长度 (m):").grid(row=row, column=0, sticky='e', pady=5)
        self.entry_length = ttk.Entry(frame, width=20)
        self.entry_length.insert(0, "0.0")
        self.entry_length.grid(row=row, column=1, sticky='w', pady=5, padx=10)
        self.entry_length.bind('<KeyRelease>', self._on_geometry_param_changed)
        row += 1
        ttk.Label(frame, text="拐弯半径 R (m):").grid(row=row, column=0, sticky='e', pady=5)
        self.entry_radius = ttk.Entry(frame, width=20)
        self.entry_radius.insert(0, "0.0")
        self.entry_radius.grid(row=row, column=1, sticky='w', pady=5, padx=10)
        self.entry_radius.bind('<KeyRelease>', self._on_geometry_param_changed)
        row += 1
        ttk.Label(frame, text="拐角 θ (°):").grid(row=row, column=0, sticky='e', pady=5)
        self.entry_angle = ttk.Entry(frame, width=20)
        self.entry_angle.insert(0, "0.0")
        self.entry_angle.grid(row=row, column=1, sticky='w', pady=5, padx=10)
        self.entry_angle.bind('<KeyRelease>', self._on_geometry_param_changed)
        row += 1
        ttk.Label(frame, text="局部系数:").grid(row=row, column=0, sticky='e', pady=5)
        xi_frame = ttk.Frame(frame)
        xi_frame.grid(row=row, column=1, columnspan=2, sticky='w', pady=5, padx=10)
        self.entry_xi = ttk.Entry(xi_frame, width=15)
        self.entry_xi.pack(side=tk.LEFT)
        self.entry_xi.bind('<KeyPress>', self._on_xi_manual_input)
        self.label_xi_hint = ttk.Label(xi_frame, text="(可手动修改)", font=('', 8))
        self.label_xi_hint.pack(side=tk.LEFT, padx=5)
        self.btn_trash_rack_config = ttk.Button(xi_frame, text="详细配置", command=self._open_trash_rack_config)
        row += 1
        self.trash_rack_params: Optional[TrashRackParams] = None
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=20)
        ttk.Button(btn_frame, text="确定", command=self._on_ok, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.destroy, width=10).pack(side=tk.LEFT, padx=5)
    def _on_type_changed(self, event=None):
        type_name = self.combo_type.get()
        if type_name not in [SegmentType.TRASH_RACK.value, SegmentType.GATE_SLOT.value, SegmentType.BYPASS_PIPE.value, SegmentType.OTHER.value]:
            length_text = self.entry_length.get().strip()
            if length_text == "--":
                self.entry_length.config(state='normal')
                self.entry_length.delete(0, tk.END)
                self.entry_length.insert(0, "0.0")
            else:
                self.entry_length.config(state='normal')
        if type_name == SegmentType.BEND.value:
            self.entry_radius.config(state='normal')
            self.entry_angle.config(state='normal')
            self.entry_xi.config(state='normal')
            self.label_xi_hint.config(text="(留空则计算时自动确定)")
            self.btn_trash_rack_config.pack_forget()
            self._auto_calculate_xi()
        elif type_name == SegmentType.FOLD.value:
            self.entry_radius.config(state='normal')
            self.entry_radius.delete(0, tk.END)
            self.entry_radius.insert(0, "--")
            self.entry_radius.config(state='disabled')
            self.entry_angle.config(state='normal')
            self.entry_xi.config(state='normal')
            self.label_xi_hint.config(text="(根据拐角θ自动计算)")
            self.btn_trash_rack_config.pack_forget()
            self._auto_calculate_xi()
        elif type_name == SegmentType.TRASH_RACK.value:
            self.entry_length.config(state='normal')
            self.entry_length.delete(0, tk.END)
            self.entry_length.insert(0, "--")
            self.entry_length.config(state='disabled')
            self.entry_radius.config(state='normal')
            self.entry_radius.delete(0, tk.END)
            self.entry_radius.insert(0, "--")
            self.entry_radius.config(state='disabled')
            self.entry_angle.config(state='normal')
            self.entry_angle.delete(0, tk.END)
            self.entry_angle.insert(0, "--")
            self.entry_angle.config(state='disabled')
            self.entry_xi.config(state='readonly')
            self.label_xi_hint.config(text="")
            self.btn_trash_rack_config.pack(side=tk.LEFT, padx=5)
            if self.trash_rack_params is None:
                self.trash_rack_params = TrashRackParams()
            xi = CoefficientService.calculate_trash_rack_xi(self.trash_rack_params)
            self.entry_xi.config(state='normal')
            self.entry_xi.delete(0, tk.END)
            self.entry_xi.insert(0, f"{xi:.4f}")
            self.entry_xi.config(state='readonly')
        elif type_name == SegmentType.GATE_SLOT.value:
            self.entry_length.config(state='normal')
            self.entry_length.delete(0, tk.END)
            self.entry_length.insert(0, "--")
            self.entry_length.config(state='disabled')
            self.entry_radius.config(state='normal')
            self.entry_radius.delete(0, tk.END)
            self.entry_radius.insert(0, "--")
            self.entry_radius.config(state='disabled')
            self.entry_angle.config(state='normal')
            self.entry_angle.delete(0, tk.END)
            self.entry_angle.insert(0, "--")
            self.entry_angle.config(state='disabled')
            self.entry_xi.config(state='normal')
            if not self.entry_xi.get().strip() or not self._user_modified_xi:
                self.entry_xi.delete(0, tk.END)
                self.entry_xi.insert(0, "0.1")
                self._user_modified_xi = False
            self.label_xi_hint.config(text="炁排规范2018附录L：平板门门槽ξm= 0.05～0.15")
            self.btn_trash_rack_config.pack_forget()
        elif type_name == SegmentType.BYPASS_PIPE.value:
            self.entry_length.config(state='normal')
            self.entry_length.delete(0, tk.END)
            self.entry_length.insert(0, "--")
            self.entry_length.config(state='disabled')
            self.entry_radius.config(state='normal')
            self.entry_radius.delete(0, tk.END)
            self.entry_radius.insert(0, "--")
            self.entry_radius.config(state='disabled')
            self.entry_angle.config(state='normal')
            self.entry_angle.delete(0, tk.END)
            self.entry_angle.insert(0, "--")
            self.entry_angle.config(state='disabled')
            self.entry_xi.config(state='normal')
            if not self.entry_xi.get().strip() or not self._user_modified_xi:
                self.entry_xi.delete(0, tk.END)
                self.entry_xi.insert(0, "0.1")
                self._user_modified_xi = False
            self.label_xi_hint.config(text="旁通管水头损失系数ξp\n冲沙、放空、进人孔等，一般采0.10")
            self.btn_trash_rack_config.pack_forget()
        else:
            self.entry_length.config(state='normal')
            self.entry_length.delete(0, tk.END)
            self.entry_length.insert(0, "--")
            self.entry_length.config(state='disabled')
            self.entry_radius.config(state='normal')
            self.entry_radius.delete(0, tk.END)
            self.entry_radius.insert(0, "--")
            self.entry_radius.config(state='disabled')
            self.entry_angle.config(state='normal')
            self.entry_angle.delete(0, tk.END)
            self.entry_angle.insert(0, "--")
            self.entry_angle.config(state='disabled')
            self.entry_xi.config(state='normal')
            if not self.entry_xi.get().strip() or not self._user_modified_xi:
                self.entry_xi.delete(0, tk.END)
                self.entry_xi.insert(0, "0.1")
                self._user_modified_xi = False
            self.label_xi_hint.config(text="(默认倔0.1，可手动修改)")
            self.btn_trash_rack_config.pack_forget()
    def _on_geometry_param_changed(self, event=None):
        self._auto_calculate_xi()
    def _auto_calculate_xi(self):
        if hasattr(self, '_loading_data') and self._loading_data:
            return
        type_name = self.combo_type.get()
        current_xi = self.entry_xi.get().strip()
        if current_xi and hasattr(self, '_user_modified_xi') and self._user_modified_xi:
            return
        if type_name == SegmentType.BEND.value:
            try:
                radius = float(self.entry_radius.get() or 0)
                angle = float(self.entry_angle.get() or 0)
                if radius > 0 and angle > 0 and self._D_theory > 0:
                    xi_bend = CoefficientService.calculate_bend_coeff(radius, self._D_theory, angle, verbose=False)
                    self.entry_xi.delete(0, tk.END)
                    self.entry_xi.insert(0, f"{xi_bend:.4f}")
                    self._user_modified_xi = False
                elif radius > 0 and angle > 0:
                    self.entry_xi.delete(0, tk.END)
                    self._user_modified_xi = False
                else:
                    self.entry_xi.delete(0, tk.END)
                    self._user_modified_xi = False
            except ValueError:
                pass
        elif type_name == SegmentType.FOLD.value:
            try:
                angle = float(self.entry_angle.get() or 0)
                if angle > 0:
                    xi_fold = CoefficientService.calculate_fold_coeff(angle, verbose=False)
                    self.entry_xi.delete(0, tk.END)
                    self.entry_xi.insert(0, f"{xi_fold:.4f}")
                    self._user_modified_xi = False
                else:
                    self.entry_xi.delete(0, tk.END)
                    self._user_modified_xi = False
            except ValueError:
                pass
    def _open_trash_rack_config(self):
        dialog = TrashRackConfigDialog(self, self.trash_rack_params)
        self.wait_window(dialog)
        if dialog.result:
            self.trash_rack_params = dialog.result
            xi = CoefficientService.calculate_trash_rack_xi(self.trash_rack_params)
            self.entry_xi.config(state='normal')
            self.entry_xi.delete(0, tk.END)
            self.entry_xi.insert(0, f"{xi:.4f}")
            self.entry_xi.config(state='readonly')
    def _on_xi_manual_input(self, event=None):
        self._user_modified_xi = True
    def _load_segment(self, segment: StructureSegment):
        self._loading_data = True
        if segment.segment_type in [SegmentType.INLET, SegmentType.OUTLET]:
            self.combo_type.config(values=[st.value for st in SegmentType])
        self.combo_type.set(segment.segment_type.value)
        self.entry_length.delete(0, tk.END)
        self.entry_length.insert(0, f"{segment.length:.2f}")
        self.entry_radius.delete(0, tk.END)
        self.entry_radius.insert(0, f"{segment.radius:.2f}")
        self.entry_angle.delete(0, tk.END)
        self.entry_angle.insert(0, f"{segment.angle:.1f}")
        if segment.trash_rack_params:
            self.trash_rack_params = segment.trash_rack_params
        if segment.xi_user is not None:
            self.entry_xi.delete(0, tk.END)
            self.entry_xi.insert(0, f"{segment.xi_user:.4f}")
            self._user_modified_xi = True
        elif segment.xi_calc is not None:
            self.entry_xi.delete(0, tk.END)
            self.entry_xi.insert(0, f"{segment.xi_calc:.4f}")
            self._user_modified_xi = False
        self._on_type_changed()
        self._loading_data = False
    def _on_ok(self):
        try:
            type_name = self.combo_type.get()
            segment_type = None
            for st in SegmentType:
                if st.value == type_name:
                    segment_type = st
                    break
            if segment_type is None:
                messagebox.showerror("错误", "请选择类型")
                return
            length_text = self.entry_length.get().strip()
            length = 0.0 if length_text == "--" or not length_text else float(length_text)
            radius_text = self.entry_radius.get().strip()
            radius = 0.0 if radius_text == "--" or not radius_text else float(radius_text)
            angle_text = self.entry_angle.get().strip()
            angle = 0.0 if angle_text == "--" or not angle_text else float(angle_text)
            xi_user = None
            xi_calc_new = None
            xi_text = self.entry_xi.get().strip()
            if xi_text:
                xi_value = float(xi_text)
                if self._user_modified_xi:
                    xi_user = xi_value
                else:
                    xi_calc_new = xi_value
            if segment_type == SegmentType.BEND:
                if radius <= 0:
                    messagebox.showerror("输入错误", "弯管必须输入拐弯半径 R")
                    return
                if angle <= 0:
                    messagebox.showerror("输入错误", "弯管必须输入拐角 θ")
                    return
            if segment_type == SegmentType.TRASH_RACK:
                if self.trash_rack_params is None:
                    messagebox.showwarning("提示", "请先点击\"详细配置\"按钮配置拦污栅参数")
                    return
            coords = self.segment.coordinates if self.segment else []
            locked = self.segment.locked if self.segment else False
            xi_calc = xi_calc_new if xi_calc_new is not None else (self.segment.xi_calc if self.segment else None)
            self.result = StructureSegment(segment_type=segment_type,length=length,radius=radius,angle=angle,xi_user=xi_user,xi_calc=xi_calc,coordinates=coords,locked=locked,trash_rack_params=self.trash_rack_params if segment_type == SegmentType.TRASH_RACK else None)
            self.destroy()
        except ValueError as e:
            messagebox.showerror("输入错误", f"请检查数值格式:\n{str(e)}")
class TrashRackConfigDialog(tk.Toplevel):
    def __init__(self, parent, params: Optional[TrashRackParams] = None):
        super().__init__(parent)
        self.title("拦污栅详细配置")
        self.geometry("750x700")
        self.transient(parent)
        self.grab_set()
        self.result: Optional[TrashRackParams] = None
        self.params = params if params else TrashRackParams()
        self._create_ui()
        if params:
            self._load_params()
        else:
            self._update_result_preview()
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    def _create_ui(self):
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(main_frame, text="拦污栅局部水头损失系数计算", font=('', 12, 'bold')).pack(pady=(0, 15))
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        params_frame = ttk.LabelFrame(left_frame, text="基本参数", padding=10)
        params_frame.pack(fill=tk.X, pady=5)
        row = 0
        ttk.Label(params_frame, text="栅面倾角 α (°):").grid(row=row, column=0, sticky='e', pady=5)
        self.entry_alpha = ttk.Entry(params_frame, width=15)
        self.entry_alpha.insert(0, "90.0")
        self.entry_alpha.grid(row=row, column=1, sticky='w', pady=5, padx=5)
        self.entry_alpha.bind('<KeyRelease>', self._on_param_changed)
        ttk.Label(params_frame, text="(0°～180°，竖直90°)", fg='gray').grid(row=row, column=2, sticky='w')
        row += 1
        self.var_has_support = tk.BooleanVar(value=False)
        ttk.Checkbutton(params_frame, text="考虑支墚影响", variable=self.var_has_support, command=self._on_mode_changed).grid(row=row, column=0, columnspan=3, sticky='w', pady=5)
        bar_frame = ttk.LabelFrame(left_frame, text="栅条参数", padding=10)
        bar_frame.pack(fill=tk.X, pady=5)
        row = 0
        ttk.Label(bar_frame, text="栅条形状:").grid(row=row, column=0, sticky='e', pady=5)
        self.shape_list = list(TrashRackBarShape)
        self.combo_bar_shape = ttk.Combobox(bar_frame, values=[s.value for s in self.shape_list], state='readonly', width=18)
        self.combo_bar_shape.current(0)
        self.combo_bar_shape.grid(row=row, column=1, sticky='w', pady=5, padx=5)
        self.combo_bar_shape.bind('<<ComboboxSelected>>', self._on_bar_shape_changed)
        row += 1
        ttk.Label(bar_frame, text="栅条厚度 s₁ (m):").grid(row=row, column=0, sticky='e', pady=5)
        self.entry_s1 = ttk.Entry(bar_frame, width=15)
        self.entry_s1.insert(0, "0.01")
        self.entry_s1.grid(row=row, column=1, sticky='w', pady=5, padx=5)
        self.entry_s1.bind('<KeyRelease>', self._on_param_changed)
        row += 1
        ttk.Label(bar_frame, text="栅条间距 b₁ (m):").grid(row=row, column=0, sticky='e', pady=5)
        self.entry_b1 = ttk.Entry(bar_frame, width=15)
        self.entry_b1.insert(0, "0.05")
        self.entry_b1.grid(row=row, column=1, sticky='w', pady=5, padx=5)
        self.entry_b1.bind('<KeyRelease>', self._on_param_changed)
        row += 1
        ttk.Label(bar_frame, text="栅条阻塞比 s₁/b₁:").grid(row=row, column=0, sticky='e', pady=5)
        self.label_ratio1 = ttk.Label(bar_frame, text="--", foreground='blue')
        self.label_ratio1.grid(row=row, column=1, sticky='w', pady=5, padx=5)
        support_frame = ttk.LabelFrame(left_frame, text="支墚参数", padding=10)
        support_frame.pack(fill=tk.X, pady=5)
        row = 0
        ttk.Label(support_frame, text="支墚形状:").grid(row=row, column=0, sticky='e', pady=5)
        self.combo_support_shape = ttk.Combobox(support_frame, values=[s.value for s in self.shape_list], state='readonly', width=18)
        self.combo_support_shape.current(0)
        self.combo_support_shape.grid(row=row, column=1, sticky='w', pady=5, padx=5)
        self.combo_support_shape.bind('<<ComboboxSelected>>', self._on_support_shape_changed)
        row += 1
        ttk.Label(support_frame, text="支墚厚度 s₂ (m):").grid(row=row, column=0, sticky='e', pady=5)
        self.entry_s2 = ttk.Entry(support_frame, width=15)
        self.entry_s2.insert(0, "0.1")
        self.entry_s2.grid(row=row, column=1, sticky='w', pady=5, padx=5)
        self.entry_s2.bind('<KeyRelease>', self._on_param_changed)
        row += 1
        ttk.Label(support_frame, text="支墚净距 b₂ (m):").grid(row=row, column=0, sticky='e', pady=5)
        self.entry_b2 = ttk.Entry(support_frame, width=15)
        self.entry_b2.insert(0, "1.0")
        self.entry_b2.grid(row=row, column=1, sticky='w', pady=5, padx=5)
        self.entry_b2.bind('<KeyRelease>', self._on_param_changed)
        row += 1
        ttk.Label(support_frame, text="支墚阻塞比 s₂/b₂:").grid(row=row, column=0, sticky='e', pady=5)
        self.label_ratio2 = ttk.Label(support_frame, text="--", foreground='blue')
        self.label_ratio2.grid(row=row, column=1, sticky='w', pady=5, padx=5)
        manual_frame = ttk.LabelFrame(left_frame, text="手动输入", padding=10)
        manual_frame.pack(fill=tk.X, pady=5)
        self.var_manual = tk.BooleanVar(value=False)
        ttk.Checkbutton(manual_frame, text="启用手动输入模式（直接指定系数）", variable=self.var_manual, command=self._on_manual_mode_changed).pack(anchor='w', pady=5)
        xi_frame = ttk.Frame(manual_frame)
        xi_frame.pack(fill=tk.X, pady=5)
        ttk.Label(xi_frame, text="手动系数:").pack(side=tk.LEFT, padx=5)
        self.entry_manual_xi = ttk.Entry(xi_frame, width=15, state='disabled')
        self.entry_manual_xi.insert(0, "0.0")
        self.entry_manual_xi.pack(side=tk.LEFT, padx=5)
        self.entry_manual_xi.bind('<KeyRelease>', self._update_result_preview)
        result_frame = ttk.LabelFrame(left_frame, text="计算结果", padding=10)
        result_frame.pack(fill=tk.X, pady=5)
        result_inner = ttk.Frame(result_frame)
        result_inner.pack()
        ttk.Label(result_inner, text="局部水头损失系数 ξ:", font=('', 11)).pack(side=tk.LEFT, padx=5)
        self.label_result = ttk.Label(result_inner, text="--", font=('', 11, 'bold'), foreground='blue')
        self.label_result.pack(side=tk.LEFT, padx=5)
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        ref_frame = ttk.LabelFrame(right_frame, text="参考表：栅条形状系数β (表L.1.4-1)", padding=10)
        ref_frame.pack(fill=tk.BOTH, expand=True)
        tree_frame = ttk.Frame(ref_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        columns = ('形状', 'β')
        self.ref_tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=8)
        self.ref_tree.heading('形状', text='栅条形状')
        self.ref_tree.heading('β', text='系数β')
        self.ref_tree.column('形状', width=180, anchor='w')
        self.ref_tree.column('β', width=80, anchor='center')
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.ref_tree.yview)
        self.ref_tree.configure(yscrollcommand=scrollbar.set)
        self.ref_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        for shape in TrashRackBarShape:
            beta = CoefficientService.get_trash_rack_bar_beta(shape)
            self.ref_tree.insert('', 'end', values=(shape.value, f"{beta:.2f}"))
        self.ref_tree.bind('<<TreeviewSelect>>', self._on_table_select)
        btn_frame = ttk.Frame(self, padding=10)
        btn_frame.pack()
        ttk.Button(btn_frame, text="确定", command=self._on_ok, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.destroy, width=12).pack(side=tk.LEFT, padx=5)
    def _load_params(self):
        self.entry_alpha.insert(0, f"{self.params.alpha:.1f}")
        self.var_has_support.set(self.params.has_support)
        bar_idx = self.shape_list.index(self.params.bar_shape)
        self.combo_bar_shape.current(bar_idx)
        self.entry_s1.insert(0, f"{self.params.s1:.1f}")
        self.entry_b1.insert(0, f"{self.params.b1:.1f}")
        support_idx = self.shape_list.index(self.params.support_shape)
        self.combo_support_shape.current(support_idx)
        self.entry_s2.insert(0, f"{self.params.s2:.1f}")
        self.entry_b2.insert(0, f"{self.params.b2:.1f}")
        self.var_manual.set(self.params.manual_mode)
        if self.params.manual_mode:
            self.entry_manual_xi.config(state='normal')
            self.entry_manual_xi.insert(0, f"{self.params.manual_xi:.4f}")
        self._on_mode_changed()
    def _on_mode_changed(self):
        has_support = self.var_has_support.get()
        entry_state = 'normal' if has_support else 'disabled'
        combo_state = 'readonly' if has_support else 'disabled'
        self.combo_support_shape.config(state=combo_state)
        self.entry_s2.config(state=entry_state)
        self.entry_b2.config(state=entry_state)
        self._update_result_preview()
    def _on_bar_shape_changed(self, event=None):
        self._update_result_preview()
    def _on_support_shape_changed(self, event=None):
        self._update_result_preview()
    def _on_param_changed(self, event=None):
        self._update_ratio_display()
        self._update_result_preview()
    def _on_manual_mode_changed(self):
        manual = self.var_manual.get()
        self.entry_manual_xi.config(state='normal' if manual else 'disabled')
        self._update_result_preview()
    def _on_table_select(self, event=None):
        selection = self.ref_tree.selection()
        if selection:
            item = selection[0]
            idx = self.ref_tree.index(item)
            self.combo_bar_shape.current(idx)
            self._update_result_preview()
    def _update_ratio_display(self):
        try:
            s1 = float(self.entry_s1.get() or 0)
            b1 = float(self.entry_b1.get() or 1)
            if b1 > 0:
                self.label_ratio1.config(text=f"{s1/b1:.4f}")
            else:
                self.label_ratio1.config(text="错误: b1=0")
        except:
            self.label_ratio1.config(text="--")
        try:
            s2 = float(self.entry_s2.get() or 0)
            b2 = float(self.entry_b2.get() or 1)
            if b2 > 0:
                self.label_ratio2.config(text=f"{s2/b2:.4f}")
            else:
                self.label_ratio2.config(text="错误: b2=0")
        except:
            self.label_ratio2.config(text="--")
    def _update_result_preview(self):
        try:
            params = self._collect_params()
            if params is None:
                self.label_result.config(text="参数错误", foreground='red')
                return
            xi = CoefficientService.calculate_trash_rack_xi(params)
            if xi < 0:
                self.label_result.config(text="负数(不合理)", foreground='red')
            elif xi == 0.0 and not params.manual_mode:
                self.label_result.config(text="Error", foreground='red')
            else:
                self.label_result.config(text=f"{xi:.4f}", foreground='blue')
        except Exception as e:
            self.label_result.config(text=f"错误: {str(e)}", foreground='red')
    def _collect_params(self) -> Optional[TrashRackParams]:
        try:
            alpha = float(self.entry_alpha.get() or 90)
            if alpha < 0 or alpha > 180:
                return None
            has_support = self.var_has_support.get()
            bar_idx = self.combo_bar_shape.current()
            bar_shape = self.shape_list[bar_idx] if bar_idx >= 0 else TrashRackBarShape.RECTANGULAR
            beta1 = CoefficientService.get_trash_rack_bar_beta(bar_shape)
            s1 = float(self.entry_s1.get() or 0)
            b1 = float(self.entry_b1.get() or 0)
            support_idx = self.combo_support_shape.current()
            support_shape = self.shape_list[support_idx] if support_idx >= 0 else TrashRackBarShape.RECTANGULAR
            beta2 = CoefficientService.get_trash_rack_bar_beta(support_shape)
            s2 = float(self.entry_s2.get() or 0)
            b2 = float(self.entry_b2.get() or 0)
            manual_mode = self.var_manual.get()
            manual_xi = float(self.entry_manual_xi.get() or 0) if manual_mode else 0.0
            return TrashRackParams(alpha=alpha,has_support=has_support,bar_shape=bar_shape,beta1=beta1,s1=s1,b1=b1,support_shape=support_shape,beta2=beta2,s2=s2,b2=b2,manual_mode=manual_mode,manual_xi=manual_xi)
        except ValueError:
            return None
    def _on_ok(self):
        params = self._collect_params()
        if params is None:
            messagebox.showerror("输入错误", "请检查数值格式\n栅面倾角必须在0~180度范围内")
            return
        if params.alpha < 0 or params.alpha > 180:
            messagebox.showerror("输入错误", "栅面倾角必须在0~180度范围内")
            return
        if params.b1 <= 0:
            messagebox.showerror("输入错误", "栅条间距 b1 必须大于0")
            return
        if params.has_support and params.b2 <= 0:
            messagebox.showerror("输入错误", "支墚净距 b2 必须大于0")
            return
        xi = CoefficientService.calculate_trash_rack_xi(params)
        if xi < 0:
            messagebox.showerror("计算错误", f"计算出的系数为负数({xi:.4f})，不符合工程实际\n请检查参数设置，特别是栅面倾角")
            return
        self.result = params
        self.destroy()
class InletSectionDialog(tk.Toplevel):
    def __init__(self, parent, Q: float, B: float = None, h: float = None, m: float = None):
        super().__init__(parent)
        self.title("进口渐变段末端断面参数设置")
        self.geometry("480x420")
        self.transient(parent)
        self.grab_set()
        self.Q = Q
        self.result_B = B
        self.result_h = h
        self.result_m = m
        self.result_velocity = None
        self._create_ui()
        if B is not None:
            self.entry_B.insert(0, str(B))
        if h is not None:
            self.entry_h.insert(0, str(h))
        if m is not None:
            self.entry_m.insert(0, str(m))
        if B is not None and h is not None and m is not None:
            self._calculate_velocity()
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    def _create_ui(self):
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="设置渐变段末端断面参数，自动计算该断面流速", font=('Microsoft YaHei', 10, 'bold')).pack(anchor='w', pady=(0, 15))
        input_frame = ttk.Frame(frame)
        input_frame.pack(fill=tk.X, pady=10)
        row = 0
        ttk.Label(input_frame, text="渐变段末端底宽B (m):").grid(row=row, column=0, sticky='e', pady=8, padx=5)
        self.entry_B = ttk.Entry(input_frame, width=20)
        self.entry_B.grid(row=row, column=1, sticky='w', pady=8, padx=5)
        self.entry_B.bind('<KeyRelease>', lambda e: self._calculate_velocity())
        row += 1
        ttk.Label(input_frame, text="渐变段末端水深h (m):").grid(row=row, column=0, sticky='e', pady=8, padx=5)
        self.entry_h = ttk.Entry(input_frame, width=20)
        self.entry_h.grid(row=row, column=1, sticky='w', pady=8, padx=5)
        self.entry_h.bind('<KeyRelease>', lambda e: self._calculate_velocity())
        row += 1
        ttk.Label(input_frame, text="渐变段边坡比m:").grid(row=row, column=0, sticky='e', pady=8, padx=5)
        self.entry_m = ttk.Entry(input_frame, width=20)
        self.entry_m.grid(row=row, column=1, sticky='w', pady=8, padx=5)
        self.entry_m.bind('<KeyRelease>', lambda e: self._calculate_velocity())
        ttk.Label(input_frame, text="m=0表示矩形断面", fg='gray').grid(row=row, column=2, sticky='w', padx=5)
        row += 1
        result_frame = ttk.LabelFrame(frame, text="计算结果", padding=10)
        result_frame.pack(fill=tk.X, pady=15)
        info_frame = ttk.Frame(result_frame)
        info_frame.pack(fill=tk.X)
        ttk.Label(info_frame, text=f"设计流量 Q = {self.Q:.3f} m³/s", font=('', 10)).pack(anchor='w', pady=2)
        ttk.Label(info_frame, text="梅形断面面积公式：ω = (B + mh) × h", font=('Consolas', 9)).pack(anchor='w', pady=2)
        ttk.Label(info_frame, text="流速公式： v = Q / ω", font=('Consolas', 9)).pack(anchor='w', pady=2)
        ttk.Separator(result_frame, orient='horizontal').pack(fill=tk.X, pady=8)
        result_display = ttk.Frame(result_frame)
        result_display.pack()
        ttk.Label(result_display, text="断面流速 v₂:", font=('', 11)).pack(side=tk.LEFT, padx=5)
        self.label_velocity = ttk.Label(result_display, text="--", font=('', 11, 'bold'), foreground='blue')
        self.label_velocity.pack(side=tk.LEFT, padx=5)
        ttk.Label(result_display, text="m/s", font=('', 10)).pack(side=tk.LEFT)
        tip_frame = ttk.Frame(frame)
        tip_frame.pack(fill=tk.X, pady=10)
        ttk.Label(tip_frame, text="说明：", font=('', 9, 'bold'), foreground='#FF6600').pack(anchor='w')
        tip_text = """• 设置后，程序将禁用\"默认规则\" (v₂ = v₁ + 0.2)
• 点击\"清除\"可恢复使用默认规则
• 矩形断面：设 m = 0
• 梅形断面：m 为边坡系数（如 m=1.5 表示 1:1.5 边坡）"""
        ttk.Label(tip_frame, text=tip_text, justify='left', font=('', 8), foreground='#666666').pack(anchor='w', padx=15)
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=15)
        ttk.Button(btn_frame, text="确定", command=self._on_ok, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="清除", command=self._on_clear, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.destroy, width=12).pack(side=tk.LEFT, padx=5)
    def _calculate_velocity(self):
        try:
            B = float(self.entry_B.get() or 0)
            h = float(self.entry_h.get() or 0)
            m = float(self.entry_m.get() or 0)
            if B <= 0 or h <= 0 or m < 0:
                self.label_velocity.config(text="--")
                return
            area = (B + m * h) * h
            if area <= 0:
                self.label_velocity.config(text="错误")
                return
            velocity = self.Q / area
            self.label_velocity.config(text=f"{velocity:.4f}")
        except ValueError:
            self.label_velocity.config(text="--")
    def _on_ok(self):
        try:
            B = float(self.entry_B.get())
            h = float(self.entry_h.get())
            m = float(self.entry_m.get())
            if B <= 0 or h <= 0 or m < 0:
                messagebox.showerror("输入错误", "参数必须大于零（m可为0）")
                return
            area = (B + m * h) * h
            if area <= 0:
                messagebox.showerror("计算错误", "断面面积必须大于零")
                return
            velocity = self.Q / area
            self.result_B = B
            self.result_h = h
            self.result_m = m
            self.result_velocity = velocity
            self.destroy()
        except ValueError:
            messagebox.showerror("输入错误", "请检查数值格式")
    def _on_clear(self):
        self.result_B = None
        self.result_h = None
        self.result_m = None
        self.result_velocity = None
        self.destroy()
class InletShapeDialog(tk.Toplevel):
    def __init__(self, parent, segment: StructureSegment):
        super().__init__(parent)
        self.title("进水口形状选择")
        self.geometry("500x380")
        self.transient(parent)
        self.grab_set()
        self.segment = segment
        self.result = None
        self._create_ui()
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    def _create_ui(self):
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="选择进水口形状，系统将自动计算局部系数", font=('', 11, 'bold')).pack(pady=(0, 20))
        shape_frame = ttk.LabelFrame(frame, text="进水口形状选项", padding=15)
        shape_frame.pack(fill=tk.BOTH, expand=True)
        self.var_shape = tk.StringVar()
        current_shape = self.segment.inlet_shape if self.segment.inlet_shape else InletOutletShape.SLIGHTLY_ROUNDED
        self.var_shape.set(current_shape.value)
        for shape in InletOutletShape:
            rb = ttk.Radiobutton(shape_frame, text=shape.value, variable=self.var_shape, value=shape.value, command=self._on_shape_changed)
            rb.pack(anchor='w', pady=8)
        result_frame = ttk.LabelFrame(frame, text="局部水头损失系数", padding=10)
        result_frame.pack(fill=tk.X, pady=15)
        result_inner = ttk.Frame(result_frame)
        result_inner.pack()
        ttk.Label(result_inner, text="进口系数 ξ₁:", font=('', 10)).pack(side=tk.LEFT, padx=5)
        self.label_xi = ttk.Label(result_inner, text="--", font=('', 11, 'bold'), foreground='blue')
        self.label_xi.pack(side=tk.LEFT, padx=5)
        self._on_shape_changed()
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="确定", command=self._on_ok, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.destroy, width=12).pack(side=tk.LEFT, padx=5)
    def _on_shape_changed(self):
        shape_name = self.var_shape.get()
        for shape in InletOutletShape:
            if shape.value == shape_name:
                xi_range = INLET_SHAPE_COEFFICIENTS[shape]
                xi = sum(xi_range) / 2
                self.label_xi.config(text=f"{xi:.4f}")
                return
    def _on_ok(self):
        shape_name = self.var_shape.get()
        for shape in InletOutletShape:
            if shape.value == shape_name:
                xi_range = INLET_SHAPE_COEFFICIENTS[shape]
                xi = sum(xi_range) / 2
                self.result = StructureSegment(segment_type=SegmentType.INLET,locked=True,inlet_shape=shape,xi_calc=xi,coordinates=self.segment.coordinates)
                self.destroy()
                return
class OutletShapeDialog(tk.Toplevel):
    def __init__(self, parent, segment: StructureSegment, Q: float = 10.0, v: float = 2.0):
        super().__init__(parent)
        self.title("出水口局部阻力系数")
        self.geometry("520x480")
        self.transient(parent)
        self.grab_set()
        self.segment = segment
        self.result = None
        self._Q = Q
        self._v = v
        self._create_ui()
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    def _create_ui(self):
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="选择出水口形状并设置系数", font=('', 11, 'bold')).pack(pady=(0, 15))
        mode_frame = ttk.LabelFrame(frame, text="计算模式", padding=10)
        mode_frame.pack(fill=tk.X, pady=5)
        self.var_mode = tk.StringVar(value="auto")
        ttk.Radiobutton(mode_frame, text="自动计算（根据形状查表）", variable=self.var_mode, value="auto", command=self._on_mode_changed).pack(anchor='w', pady=5)
        ttk.Radiobutton(mode_frame, text="手动输入系数", variable=self.var_mode, value="manual", command=self._on_mode_changed).pack(anchor='w', pady=5)
        shape_frame = ttk.LabelFrame(frame, text="出水口形状选项", padding=10)
        shape_frame.pack(fill=tk.X, pady=5)
        self.var_shape = tk.StringVar()
        current_shape = self.segment.outlet_shape if self.segment.outlet_shape else InletOutletShape.SLIGHTLY_ROUNDED
        self.var_shape.set(current_shape.value)
        for shape in InletOutletShape:
            rb = ttk.Radiobutton(shape_frame, text=shape.value, variable=self.var_shape, value=shape.value, command=self._on_shape_changed)
            rb.pack(anchor='w', pady=5)
        manual_frame = ttk.LabelFrame(frame, text="手动输入", padding=10)
        manual_frame.pack(fill=tk.X, pady=5)
        ttk.Label(manual_frame, text="局部系数 ξ₂:").pack(side=tk.LEFT, padx=5)
        self.entry_manual_xi = ttk.Entry(manual_frame, width=15, state='disabled')
        self.entry_manual_xi.insert(0, "0.0")
        self.entry_manual_xi.pack(side=tk.LEFT, padx=5)
        self.entry_manual_xi.bind('<KeyRelease>', self._on_manual_xi_changed)
        result_frame = ttk.LabelFrame(frame, text="计算结果", padding=10)
        result_frame.pack(fill=tk.X, pady=10)
        result_inner = ttk.Frame(result_frame)
        result_inner.pack()
        ttk.Label(result_inner, text="出口系数 ξ₂:", font=('', 10)).pack(side=tk.LEFT, padx=5)
        self.label_xi = ttk.Label(result_inner, text="--", font=('', 11, 'bold'), foreground='blue')
        self.label_xi.pack(side=tk.LEFT, padx=5)
        self._on_shape_changed()
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="确定", command=self._on_ok, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.destroy, width=12).pack(side=tk.LEFT, padx=5)
    def _on_mode_changed(self):
        mode = self.var_mode.get()
        if mode == "manual":
            self.entry_manual_xi.config(state='normal')
            for child in self.winfo_children():
                if isinstance(child, ttk.LabelFrame) and child.cget('text') == "出水口形状选项":
                    for widget in child.winfo_children():
                        if isinstance(widget, ttk.Radiobutton):
                            widget.config(state='disabled')
        else:
            self.entry_manual_xi.config(state='disabled')
            for child in self.winfo_children():
                if isinstance(child, ttk.LabelFrame) and child.cget('text') == "出水口形状选项":
                    for widget in child.winfo_children():
                        if isinstance(widget, ttk.Radiobutton):
                            widget.config(state='normal')
        self._update_result()
    def _on_shape_changed(self):
        self._update_result()
    def _on_manual_xi_changed(self, event=None):
        self._update_result()
    def _update_result(self):
        mode = self.var_mode.get()
        if mode == "manual":
            try:
                xi = float(self.entry_manual_xi.get() or 0)
                self.label_xi.config(text=f"{xi:.4f}")
            except ValueError:
                self.label_xi.config(text="--")
        else:
            shape_name = self.var_shape.get()
            for shape in InletOutletShape:
                if shape.value == shape_name:
                    xi_range = CoefficientService.OUTLET_COEFFICIENTS.get(shape, (0.0, 0.0))
                    xi = sum(xi_range) / 2
                    self.label_xi.config(text=f"{xi:.4f}")
                    return
    def _on_ok(self):
        mode = self.var_mode.get()
        if mode == "manual":
            try:
                xi = float(self.entry_manual_xi.get())
                self.result = StructureSegment(segment_type=SegmentType.OUTLET,locked=True,xi_calc=xi,coordinates=self.segment.coordinates)
                self.destroy()
            except ValueError:
                messagebox.showerror("输入错误", "请输入有效的系数数值")
        else:
            shape_name = self.var_shape.get()
            for shape in InletOutletShape:
                if shape.value == shape_name:
                    xi_range = CoefficientService.OUTLET_COEFFICIENTS.get(shape, (0.0, 0.0))
                    xi = sum(xi_range) / 2
                    self.result = StructureSegment(segment_type=SegmentType.OUTLET,locked=True,outlet_shape=shape,xi_calc=xi,coordinates=self.segment.coordinates)
                    self.destroy()
                    return
def main():
    app = InvertedSiphonCalculator()
    app.mainloop()
if __name__ == "__main__":
    main()
class ConfigManager:
    @staticmethod
    def get_default_params() -> GlobalParameters:
        return GlobalParameters(Q=10.0,v_guess=2.0,H_up=100.0,H_down=98.0,roughness_n=0.014,inlet_type=GradientType.NONE,outlet_type=GradientType.NONE,v_channel_in=1.0,v_pipe_in=1.2,v_channel_out=2.0,v_pipe_out=1.8835,H_bottom_up=95.0,xi_inlet=0.0,xi_outlet=0.0)
    @staticmethod
    def get_default_segments() -> List[StructureSegment]:
        inlet_shape = InletOutletShape.SLIGHTLY_ROUNDED
        inlet_xi = sum(INLET_SHAPE_COEFFICIENTS[inlet_shape]) / 2
        outlet_xi = 0.0
        return [StructureSegment(segment_type=SegmentType.INLET, locked=True, inlet_shape=inlet_shape, xi_calc=inlet_xi),StructureSegment(segment_type=SegmentType.TRASH_RACK, length=1.0),StructureSegment(segment_type=SegmentType.GATE_SLOT, length=0.5),StructureSegment(segment_type=SegmentType.BYPASS_PIPE, xi_user=0.1),StructureSegment(segment_type=SegmentType.FOLD, length=5.0),StructureSegment(segment_type=SegmentType.STRAIGHT, length=50.0),StructureSegment(segment_type=SegmentType.BEND, length=10.0, radius=5.0, angle=45.0),StructureSegment(segment_type=SegmentType.STRAIGHT, length=100.0),StructureSegment(segment_type=SegmentType.BEND, length=10.0, radius=5.0, angle=45.0),StructureSegment(segment_type=SegmentType.STRAIGHT, length=50.0),StructureSegment(segment_type=SegmentType.OTHER, xi_user=0.1),StructureSegment(segment_type=SegmentType.OUTLET, locked=True, xi_calc=outlet_xi)]
    @staticmethod
    def validate_params(params: GlobalParameters) -> Tuple[bool, str]:
        if params.Q <= 0:
            return False, "设计流量必须大于0"
        if params.v_guess <= 0:
            return False, "拟定流速必须大于0"
        if params.H_up <= params.H_down:
            return False, "上游水位必须高于下游水位"
        if params.roughness_n <= 0 or params.roughness_n > 0.1:
            return False, "糙率值超出合理范围(0~0.1)"
        if params.v_channel_in < 0:
            return False, "流速不能为负数"
        if params.v_pipe_in <= params.v_channel_in:
            return False, "进口渐变段末端流速应大于始端流速"
        return True, "OK"
    @staticmethod
    def validate_segments(segments: List[StructureSegment]) -> Tuple[bool, str]:
        if not segments:
            return False, "结构段列表为空"
        if len(segments) < 2:
            return False, "至少需要进水口和出水口"
        if segments[0].segment_type != SegmentType.INLET:
            return False, "第一段必须是进水口"
        if segments[-1].segment_type != SegmentType.OUTLET:
            return False, "最后一段必须是出水口"
        for i, seg in enumerate(segments):
            if seg.segment_type == SegmentType.BEND:
                if seg.radius <= 0:
                    return False, f"第{i+1}段弯管半径必须大于0"
                if seg.angle <= 0 or seg.angle > 180:
                    return False, f"第{i+1}段弯管角度超出范围(0~180)"
            if seg.segment_type == SegmentType.FOLD:
                if seg.angle <= 0 or seg.angle >= 180:
                    return False, f"第{i+1}段折管角度超出范围(0~180)"
        return True, "OK"
class CalculationHelper:
    @staticmethod
    def calculate_flow_area(Q: float, v: float) -> float:
        if v <= 0:
            return 0.0
        return Q / v
    @staticmethod
    def calculate_diameter_from_area(area: float) -> float:
        if area <= 0:
            return 0.0
        return math.sqrt(4 * area / math.pi)
    @staticmethod
    def calculate_velocity_from_Q_D(Q: float, D: float) -> float:
        if D <= 0:
            return 0.0
        area = math.pi * D ** 2 / 4
        return Q / area
    @staticmethod
    def calculate_reynolds_number(v: float, D: float, nu: float = 1e-6) -> float:
        if nu <= 0 or D <= 0:
            return 0.0
        return v * D / nu
    @staticmethod
    def calculate_friction_factor(Re: float, roughness: float, D: float) -> float:
        if Re <= 0 or D <= 0:
            return 0.02
        e_D = roughness / D
        if Re < 2300:
            return 64 / Re
        f = 0.02
        for _ in range(20):
            f_new = 1 / ((-2 * math.log10(e_D / 3.7 + 2.51 / (Re * math.sqrt(f)))) ** 2)
            if abs(f_new - f) < 1e-6:
                break
            f = f_new
        return f
    @staticmethod
    def format_velocity(v: float) -> str:
        if v < 0.1:
            return f"{v*1000:.1f} mm/s"
        elif v < 10:
            return f"{v:.2f} m/s"
        else:
            return f"{v:.1f} m/s"
    @staticmethod
    def format_length(L: float) -> str:
        if L < 1:
            return f"{L*100:.1f} cm"
        elif L < 1000:
            return f"{L:.2f} m"
        else:
            return f"{L/1000:.3f} km"
    @staticmethod
    def format_head_loss(h: float) -> str:
        if h < 0.001:
            return f"{h*1000:.2f} mm"
        elif h < 1:
            return f"{h*100:.2f} cm"
        else:
            return f"{h:.4f} m"
class ValidationUtils:
    @staticmethod
    def is_valid_number(value, min_val=None, max_val=None) -> bool:
        try:
            num = float(value)
            if min_val is not None and num < min_val:
                return False
            if max_val is not None and num > max_val:
                return False
            return True
        except:
            return False
    @staticmethod
    def is_valid_positive(value) -> bool:
        try:
            return float(value) > 0
        except:
            return False
    @staticmethod
    def is_valid_non_negative(value) -> bool:
        try:
            return float(value) >= 0
        except:
            return False
    @staticmethod
    def is_valid_angle(value) -> bool:
        try:
            angle = float(value)
            return 0 < angle <= 180
        except:
            return False
    @staticmethod
    def is_valid_roughness(value) -> bool:
        try:
            n = float(value)
            return 0.008 <= n <= 0.03
        except:
            return False
class FileUtils:
    @staticmethod
    def get_safe_filename(name: str) -> str:
        invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in invalid_chars:
            name = name.replace(char, '_')
        return name
    @staticmethod
    def ensure_extension(filename: str, ext: str) -> str:
        if not ext.startswith('.'):
            ext = '.' + ext
        if not filename.lower().endswith(ext.lower()):
            filename += ext
        return filename
    @staticmethod
    def get_unique_filename(base_path: str) -> str:
        if not os.path.exists(base_path):
            return base_path
        directory = os.path.dirname(base_path)
        filename = os.path.basename(base_path)
        name, ext = os.path.splitext(filename)
        counter = 1
        while True:
            new_path = os.path.join(directory, f"{name}_{counter}{ext}")
            if not os.path.exists(new_path):
                return new_path
            counter += 1
class Constants:
    G = 9.81
    PI = math.pi
    E = math.e
    WATER_DENSITY = 1000.0
    KINEMATIC_VISCOSITY = 1e-6
    MIN_VELOCITY = 0.3
    MAX_VELOCITY = 5.0
    MIN_DIAMETER = 0.2
    MAX_DIAMETER = 5.0
    STANDARD_DIAMETERS = [0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
    DEFAULT_ROUGHNESS = 0.014
    DEFAULT_FLOW_RATE = 10.0
    DEFAULT_VELOCITY = 2.0
class GeometryCalculator:
    @staticmethod
    def calculate_arc_length(radius: float, angle_deg: float) -> float:
        if radius <= 0 or angle_deg <= 0:
            return 0.0
        angle_rad = math.radians(angle_deg)
        return radius * angle_rad
    @staticmethod
    def calculate_chord_length(radius: float, angle_deg: float) -> float:
        if radius <= 0 or angle_deg <= 0:
            return 0.0
        angle_rad = math.radians(angle_deg)
        return 2 * radius * math.sin(angle_rad / 2)
    @staticmethod
    def calculate_arc_height(radius: float, angle_deg: float) -> float:
        if radius <= 0 or angle_deg <= 0:
            return 0.0
        angle_rad = math.radians(angle_deg)
        return radius * (1 - math.cos(angle_rad / 2))
    @staticmethod
    def calculate_circle_area(diameter: float) -> float:
        if diameter <= 0:
            return 0.0
        return math.pi * (diameter / 2) ** 2
    @staticmethod
    def calculate_hydraulic_radius_circle(diameter: float) -> float:
        if diameter <= 0:
            return 0.0
        return diameter / 4
    @staticmethod
    def calculate_trapezoidal_area(B: float, h: float, m: float) -> float:
        if B < 0 or h < 0 or m < 0:
            return 0.0
        return (B + m * h) * h
    @staticmethod
    def calculate_trapezoidal_wetted_perimeter(B: float, h: float, m: float) -> float:
        if B < 0 or h < 0 or m < 0:
            return 0.0
        return B + 2 * h * math.sqrt(1 + m ** 2)
    @staticmethod
    def calculate_trapezoidal_hydraulic_radius(B: float, h: float, m: float) -> float:
        area = GeometryCalculator.calculate_trapezoidal_area(B, h, m)
        perimeter = GeometryCalculator.calculate_trapezoidal_wetted_perimeter(B, h, m)
        if perimeter <= 0:
            return 0.0
        return area / perimeter
    @staticmethod
    def distance_between_points(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        return math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)
    @staticmethod
    def angle_between_vectors(v1: Tuple[float, float], v2: Tuple[float, float]) -> float:
        dot = v1[0] * v2[0] + v1[1] * v2[1]
        mag1 = math.sqrt(v1[0] ** 2 + v1[1] ** 2)
        mag2 = math.sqrt(v2[0] ** 2 + v2[1] ** 2)
        if mag1 <= 0 or mag2 <= 0:
            return 0.0
        cos_angle = dot / (mag1 * mag2)
        cos_angle = max(-1.0, min(1.0, cos_angle))
        return math.degrees(math.acos(cos_angle))
class HydraulicFormulas:
    @staticmethod
    def chezy_coefficient(n: float, R: float) -> float:
        if n <= 0 or R <= 0:
            return 0.0
        return (1.0 / n) * (R ** (1.0 / 6.0))
    @staticmethod
    def manning_velocity(n: float, R: float, S: float) -> float:
        if n <= 0 or R <= 0 or S < 0:
            return 0.0
        return (1.0 / n) * (R ** (2.0 / 3.0)) * (S ** 0.5)
    @staticmethod
    def darcy_weisbach_head_loss(f: float, L: float, D: float, v: float) -> float:
        if D <= 0:
            return 0.0
        g = 9.81
        return f * (L / D) * (v ** 2) / (2 * g)
    @staticmethod
    def local_head_loss(xi: float, v: float) -> float:
        g = 9.81
        return xi * (v ** 2) / (2 * g)
    @staticmethod
    def velocity_head(v: float) -> float:
        g = 9.81
        return (v ** 2) / (2 * g)
    @staticmethod
    def froude_number(v: float, g: float, h: float) -> float:
        if h <= 0:
            return 0.0
        return v / math.sqrt(g * h)
    @staticmethod
    def critical_depth_rectangular(Q: float, B: float, g: float = 9.81) -> float:
        if B <= 0 or g <= 0 or Q < 0:
            return 0.0
        q = Q / B
        return (q ** 2 / g) ** (1.0 / 3.0)
    @staticmethod
    def specific_energy(h: float, v: float, g: float = 9.81) -> float:
        return h + (v ** 2) / (2 * g)
class ErrorMessages:
    INVALID_FLOW_RATE = "设计流量必须大于0"
    INVALID_VELOCITY = "流速必须大于0"
    INVALID_WATER_LEVEL = "上游水位必须高于下游水位"
    INVALID_ROUGHNESS = "糙率值超出合理范围"
    INVALID_DIAMETER = "管径值超出合理范围"
    INVALID_ANGLE = "角度值超出合理范围(0-180°)"
    INVALID_RADIUS = "半径必须大于0"
    INVALID_LENGTH = "长度必须大于等于0"
    EMPTY_SEGMENTS = "结构段列表为空"
    MISSING_INLET = "缺少进水口"
    MISSING_OUTLET = "缺少出水口"
    CALCULATION_ERROR = "计算过程出现错误"
    FILE_NOT_FOUND = "文件未找到"
    FILE_READ_ERROR = "文件读取错误"
    FILE_WRITE_ERROR = "文件写入错误"
    DXF_PARSE_ERROR = "DXF文件解析错误"
    PARAMETER_ERROR = "参数错误"
class SuccessMessages:
    CALCULATION_COMPLETE = "计算完成"
    VERIFICATION_PASSED = "校验通过"
    FILE_SAVED = "文件已保存"
    DXF_IMPORTED = "DXF文件导入成功"
    SEGMENT_ADDED = "结构段已添加"
    SEGMENT_UPDATED = "结构段已更新"
    SEGMENT_DELETED = "结构段已删除"
    CONFIG_LOADED = "配置已加载"
    EXPORT_SUCCESS = "导出成功"
class UnitConverter:
    @staticmethod
    def meters_to_cm(m: float) -> float:
        return m * 100
    @staticmethod
    def cm_to_meters(cm: float) -> float:
        return cm / 100
    @staticmethod
    def meters_to_mm(m: float) -> float:
        return m * 1000
    @staticmethod
    def mm_to_meters(mm: float) -> float:
        return mm / 1000
    @staticmethod
    def cubic_meters_to_liters(m3: float) -> float:
        return m3 * 1000
    @staticmethod
    def liters_to_cubic_meters(L: float) -> float:
        return L / 1000
    @staticmethod
    def degrees_to_radians(deg: float) -> float:
        return math.radians(deg)
    @staticmethod
    def radians_to_degrees(rad: float) -> float:
        return math.degrees(rad)
class DataValidator:
    @staticmethod
    def validate_all(params: GlobalParameters, segments: List[StructureSegment]) -> Tuple[bool, List[str]]:
        errors = []
        valid_params, msg_params = ConfigManager.validate_params(params)
        if not valid_params:
            errors.append(f"参数验证失败: {msg_params}")
        valid_segments, msg_segments = ConfigManager.validate_segments(segments)
        if not valid_segments:
            errors.append(f"结构段验证失败: {msg_segments}")
        return len(errors) == 0, errors
    @staticmethod
    def check_velocity_range(v: float) -> Tuple[bool, str]:
        if v < Constants.MIN_VELOCITY:
            return False, f"流速{v:.2f}m/s小于推荐最小值{Constants.MIN_VELOCITY}m/s"
        if v > Constants.MAX_VELOCITY:
            return False, f"流速{v:.2f}m/s大于推荐最大值{Constants.MAX_VELOCITY}m/s"
        return True, "OK"
    @staticmethod
    def check_diameter_range(D: float) -> Tuple[bool, str]:
        if D < Constants.MIN_DIAMETER:
            return False, f"管径{D:.3f}m小于最小值{Constants.MIN_DIAMETER}m"
        if D > Constants.MAX_DIAMETER:
            return False, f"管径{D:.3f}m大于最大值{Constants.MAX_DIAMETER}m"
        return True, "OK"
    @staticmethod
    def suggest_diameter(D_theory: float) -> float:
        for d in Constants.STANDARD_DIAMETERS:
            if d >= D_theory:
                return d
        return Constants.STANDARD_DIAMETERS[-1]
    @staticmethod
    def check_reynolds_number(Re: float) -> str:
        if Re < 2300:
            return "层流"
        elif Re < 4000:
            return "过渡流"
        else:
            return "紊流"
    @staticmethod
    def check_froude_number(Fr: float) -> str:
        if Fr < 1.0:
            return "缓流"
        elif Fr == 1.0:
            return "临界流"
        else:
            return "急流"
class AppInfo:
    APP_NAME = "倒虹吸水力计算软件"
    VERSION = "1.0.0"
    AUTHOR = "刘思杰"
    COPYRIGHT = "Copyright 2024"
    DESCRIPTION = "基于GB 50288-2018附录L的倒虹吸水力计算软件"
    def __str__(self):
        return f"{self.APP_NAME} v{self.VERSION} by {self.AUTHOR}"