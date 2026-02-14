# -*- coding: utf-8 -*-
"""
倒虹吸水力计算软件 - 系数查询服务
封装《附录L》中的静态数据表和插值算法
"""

import math
from models import GradientType, TrashRackBarShape, TrashRackParams


class CoefficientService:
    """系数查询服务类"""
    
    # 渐变段系数表 (Table L.1.2)
    # 进口系数
    INLET_COEFFICIENTS = {
        GradientType.NONE: 0.00,
        GradientType.REVERSE_BEND: 0.10,
        GradientType.QUARTER_ARC: 0.15,
        GradientType.SQUARE_HEAD: 0.30,
        GradientType.LINEAR_TWIST: 0.20,  # 取均值，范围0.05~0.30
    }
    
    # 出口系数
    OUTLET_COEFFICIENTS = {
        GradientType.NONE: 0.00,
        GradientType.REVERSE_BEND: 0.20,
        GradientType.QUARTER_ARC: 0.25,
        GradientType.SQUARE_HEAD: 0.75,
        GradientType.LINEAR_TWIST: 0.40,  # 取均值，范围0.30~0.50
    }
    
    # 表 L.1.4-3 直角弯道损失系数表 (R/D0 -> xi_90)
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
    
    # 表 L.1.4-4 任意角弯道损失系数修正系数γ值表 (θ° -> γ)
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
    
    # 表 L.1.4-1 拦污栅栅条形状系数表 (β值)
    TRASH_RACK_BAR_COEFFICIENTS = {
        TrashRackBarShape.RECTANGULAR: 2.42,    # 矩形
        TrashRackBarShape.ROUNDED_HEAD: 1.83,   # 单侧圆头
        TrashRackBarShape.CIRCULAR: 1.79,       # 圆形
        TrashRackBarShape.OVAL: 1.67,           # 双侧圆头
        TrashRackBarShape.TRAPEZOID: 1.04,      # 倒梯形单侧圆头
        TrashRackBarShape.PEAR_SHAPE: 0.92,     # 梨形/流线型
        TrashRackBarShape.SHARP_TAIL: 0.76,     # 两端尖锐型
    }
    
    @classmethod
    def get_gradient_coeff(cls, gradient_type: GradientType, is_inlet: bool) -> float:
        """
        获取渐变段系数
        
        Args:
            gradient_type: 渐变段类型枚举
            is_inlet: 是否为进口
            
        Returns:
            对应的系数值
        """
        if is_inlet:
            return cls.INLET_COEFFICIENTS.get(gradient_type, 0.0)
        else:
            return cls.OUTLET_COEFFICIENTS.get(gradient_type, 0.0)
    
    @classmethod
    def _linear_interpolate(cls, table: list, x: float) -> float:
        """
        线性插值
        
        Args:
            table: 数据点列表 [(x1, y1), (x2, y2), ...]
            x: 插值点
            
        Returns:
            插值结果
        """
        # 边界处理
        if x <= table[0][0]:
            return table[0][1]
        if x >= table[-1][0]:
            return table[-1][1]
        
        # 查找插值区间
        for i in range(len(table) - 1):
            x1, y1 = table[i]
            x2, y2 = table[i + 1]
            if x1 <= x <= x2:
                # 线性插值: y = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
                return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
        
        return table[-1][1]
    
    @classmethod
    def get_xi_90(cls, r_d_ratio: float) -> float:
        """
        查表 L.1.4-3 获取直角弯道损失系数
        
        Args:
            r_d_ratio: R/D0 比值
            
        Returns:
            xi_90 值
        """
        return cls._linear_interpolate(cls.BEND_90_TABLE, r_d_ratio)
    
    @classmethod
    def get_gamma(cls, angle: float) -> float:
        """
        查表 L.1.4-4 获取任意角弯道损失系数修正系数
        
        Args:
            angle: 弯道角度 (度)
            
        Returns:
            γ 值
        """
        return cls._linear_interpolate(cls.ANGLE_CORRECTION_TABLE, angle)
    
    @classmethod
    def calculate_bend_coeff(cls, R: float, D: float, angle: float, verbose: bool = False) -> tuple:
        """
        计算弯管系数
        
        Args:
            R: 弯管半径 (m)
            D: 管径 (m)
            angle: 弯管圆心角 (度)
            verbose: 是否返回详细计算过程
            
        Returns:
            如果verbose=False，返回弯管系数 ξ
            如果verbose=True，返回 (ξ, 计算过程字符串)
        """
        steps = []
        
        # 计算比值 R/D0
        r_d_ratio = R / D
        steps.append(f"计算 R/D0 = {R:.3f} / {D:.3f} = {r_d_ratio:.3f}")
        
        # 查表获取 xi_90
        xi_90 = cls.get_xi_90(r_d_ratio)
        steps.append(f"查表 L.1.4-3，根据 R/D0 = {r_d_ratio:.3f}，线性插值得 xi_90 = {xi_90:.4f}")
        
        # 查表获取 gamma
        gamma = cls.get_gamma(angle)
        steps.append(f"查表 L.1.4-4，根据 theta = {angle:.1f} 度，线性插值得 gamma = {gamma:.4f}")
        
        # 计算弯管系数 xi = xi_90 * gamma
        xi = xi_90 * gamma
        steps.append(f"计算弯管系数 xi = xi_90 * gamma = {xi_90:.4f} * {gamma:.4f} = {xi:.4f}")
        
        if verbose:
            return xi, "\n".join(steps)
        return xi
    
    @classmethod
    def get_trash_rack_bar_beta(cls, shape: TrashRackBarShape) -> float:
        """
        获取拦污栅栅条形状系数 β
        
        Args:
            shape: 栅条形状枚举
            
        Returns:
            对应的 β 系数值
        """
        return cls.TRASH_RACK_BAR_COEFFICIENTS.get(shape, 2.42)
    
    @classmethod
    def calculate_trash_rack_xi(cls, params: TrashRackParams, verbose: bool = False):
        """
        计算拦污栅局部阻力系数
        
        公式 L.1.4-2 (无独立支墩):
            xi = beta1 * (s1/b1)^(4/3) * sin(alpha)
        
        公式 L.1.4-3 (有独立支墩):
            xi = [beta1 * (s1/b1)^(4/3) + beta2 * (s2/b2)^(4/3)] * sin(alpha)
        
        Args:
            params: 拦污栅参数对象
            verbose: 是否返回详细计算过程
            
        Returns:
            如果verbose=False，返回局部阻力系数 ξ
            如果verbose=True，返回 (ξ, 计算过程字符串)
        """
        steps = []
        
        # 如果是手动输入模式，直接返回手动值
        if params.manual_mode:
            xi = params.manual_xi
            steps.append(f"手动输入模式，xi = {xi:.4f}")
            if verbose:
                return xi, "\n".join(steps)
            return xi
        
        # 参数校验
        # 角度范围校验
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
        
        # 角度转换为弧度
        alpha_rad = math.radians(params.alpha)
        steps.append(f"栅面倾角 alpha = {params.alpha:.1f} 度 = {alpha_rad:.4f} 弧度")
        steps.append(f"sin(alpha) = {math.sin(alpha_rad):.4f}")
        
        # 计算栅条项 A = beta1 * (s1/b1)^(4/3)
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
        
        # 计算支墩项 B
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
            
            # 公式 L.1.4-3
            xi = (term_a + term_b) * math.sin(alpha_rad)
            steps.append(f"")
            steps.append(f"应用公式 L.1.4-3 (有独立支墩):")
            steps.append(f"  xi = (A + B) * sin(alpha)")
            steps.append(f"     = ({term_a:.4f} + {term_b:.4f}) * {math.sin(alpha_rad):.4f}")
            steps.append(f"     = {xi:.4f}")
        else:
            # 公式 L.1.4-2
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
        """
        计算折管局部阻力系数
        
        公式: ζ = 0.9457 * sin²(θ/2) + 2.047 * sin⁴(θ/2)
        
        Args:
            angle: 折管折角 θ (度)
            verbose: 是否返回详细计算过程
            
        Returns:
            如果verbose=False，返回折管系数 ξ
            如果verbose=True，返回 (ξ, 计算过程字符串)
        """
        steps = []
        
        # 角度转换为弧度
        angle_rad = math.radians(angle)
        half_angle_rad = angle_rad / 2
        
        steps.append(f"折管折角 θ = {angle:.1f}°")
        steps.append(f"θ/2 = {angle/2:.1f}° = {half_angle_rad:.4f} rad")
        
        # 计算 sin(θ/2) 和 sin²(θ/2) 和 sin⁴(θ/2)
        sin_half = math.sin(half_angle_rad)
        sin2_half = sin_half ** 2
        sin4_half = sin_half ** 4
        
        steps.append(f"sin(θ/2) = {sin_half:.4f}")
        steps.append(f"sin²(θ/2) = {sin2_half:.4f}")
        steps.append(f"sin⁴(θ/2) = {sin4_half:.4f}")
        
        # 计算折管系数
        # ζ = 0.9457 * sin²(θ/2) + 2.047 * sin⁴(θ/2)
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


if __name__ == "__main__":
    # 测试代码
    print("=== 渐变段系数测试 ===")
    for gt in GradientType:
        inlet = CoefficientService.get_gradient_coeff(gt, True)
        outlet = CoefficientService.get_gradient_coeff(gt, False)
        print(f"{gt.value}: 进口={inlet}, 出口={outlet}")
    
    print("\n=== 弯管系数计算测试 ===")
    # 示例：R=3m, D=1m, 角度=90°
    xi, steps = CoefficientService.calculate_bend_coeff(3.0, 1.0, 90.0, verbose=True)
    print(steps)
    print(f"弯管系数 xi = {xi}")
    
    print("\n=== 拦污栅系数计算测试 ===")
    # 验收标准测试：alpha=90°, beta1=2.42, s1=10mm, b1=50mm
    # 期望结果：xi = 0.283
    test_params = TrashRackParams(
        alpha=90.0,
        has_support=False,
        bar_shape=TrashRackBarShape.RECTANGULAR,
        beta1=2.42,
        s1=10.0,
        b1=50.0
    )
    xi, steps = CoefficientService.calculate_trash_rack_xi(test_params, verbose=True)
    print(steps)
    print(f"\n拦污栅系数 xi = {xi:.3f}")
    print(f"期望值: 0.283, 计算值: {xi:.3f}, {'通过' if abs(xi - 0.283) < 0.001 else '不通过'}")
