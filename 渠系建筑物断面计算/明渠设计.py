# -*- coding: utf-8 -*-
"""
明渠水力设计计算统一模块

水力设计依据:
--------------------------------------------------
规范条款 6.4.8：渠道岸顶超高应符合下列规定：
1 1级～3级渠道岸顶超高应按土石坝设计要求经论证确定。
2 4级、5级渠道岸顶超高可按下式计算确定：
   Fb = 1/4 * hb + 0.2
式中：Fb —— 渠道岸顶超高 (m)；
      hb —— 渠道通过加大流量时的水深 (m)。
--------------------------------------------------

本模块提供三种明渠断面类型（梯形、矩形、圆形）的水力计算功能。
所有断面类型在架构上处于并列地位，具有统一的调用逻辑。

版本: V2.0 (结构整合版)
"""

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, List, Any
from enum import Enum

# ============================================================
# 1. 枚举与类型定义
# ============================================================

class SectionType(Enum):
    """明渠断面类型"""
    TRAPEZOIDAL = "trapezoidal"   # 梯形明渠
    RECTANGULAR = "rectangular"     # 矩形明渠
    CIRCULAR = "circular"           # 圆形明渠


# ============================================================
# 2. 常量定义
# ============================================================

# --- 通用常量 ---
ZERO_TOLERANCE = 1e-9

# --- 梯形与矩形明渠常量 ---
MAX_BETA = 8.0               # 最大宽深比
FLOW_TOLERANCE = 0.01        # 流量计算容差
B_TOLERANCE = 0.005          # 底宽计算容差
MAX_H_ITER = 300             # 水深迭代次数
MAX_B_ITER = 100             # 底宽迭代次数

# --- 附录E 梯形渠道实用经济断面计算常量 ---
# α值范围：面积增大系数，从1.00（水力最佳）到1.05（最宽浅）
ALPHA_VALUES = [1.00, 1.01, 1.02, 1.03, 1.04, 1.05]

# --- 圆形明渠常量 ---
PI = math.pi
MIN_FREEBOARD = 0.4                     # 最小安全超高 (m)
MIN_FREE_AREA_PERCENT = 15.0            # 最小净空面积百分比 (%)
MIN_FLOW_FACTOR = 0.4                   # 最小流量系数
ITERATION_DIAMETER_STEP = 0.001         # 直径迭代步长 (m)
FINAL_DIAMETER_ROUNDING_STEP = 0.1      # 最终直径取整步长 (m)
MAX_ITERATIONS_Y = 100                  # y/D求解最大迭代次数
TOLERANCE_Y = 0.0001                    # y/D求解收敛精度
MAX_ITERATIONS_D_CALC = 25000           # D计算最大迭代次数
MAX_ALLOWED_D = 20.0                    # 最大允许直径 (m)


# ============================================================
# 3. 数据模型（各断面通用）
# ============================================================

@dataclass
class HydraulicResult:
    """水力计算结果数据类（通用）"""
    y: float = -1.0          # 水深 (m)
    A: float = -1.0          # 过水面积 (m²)
    P: float = -1.0          # 湿周 (m)
    R: float = -1.0          # 水力半径 (m)
    V: float = -1.0          # 流速 (m/s)
    FB: float = -1.0         # 安全超高/干舷 (m)
    PA: float = -1.0         # 净空面积百分比 (0-1)
    Q_check: float = -1.0    # 校验流量 (m³/s)
    theta: float = 0.0       # 圆心角 (rad，仅圆形使用)
    success: bool = False    # 计算是否成功


@dataclass
class DesignResult:
    """设计计算结果数据类（通用）"""
    # 直径相关（仅圆形使用）
    D_calculated: float = -1.0      # 计算直径 (m)
    D_design: float = -1.0          # 设计直径 (m)
    section_total_area: float = -1.0 # 断面总面积 (m²)

    # 底宽相关（梯形和矩形使用）
    b_calculated: float = -1.0      # 计算底宽 (m)
    b_design: float = -1.0          # 设计底宽 (m)

    # 水力结果
    design: HydraulicResult = field(default_factory=HydraulicResult)
    Q_increased: float = -1.0
    increased: HydraulicResult = field(default_factory=HydraulicResult)
    Q_min: float = -1.0
    minimum: HydraulicResult = field(default_factory=HydraulicResult)

    # 状态信息
    increase_percent: float = 0.0
    increase_percent_source: str = ""
    success: bool = False
    error_message: str = ""
    check_passed: bool = True
    check_errors: List[str] = field(default_factory=list)


@dataclass
class InputData:
    """输入数据类（通用）"""
    Q_design: float = 0.0           # 设计流量 (m³/s)
    n_roughness: float = 0.0        # 糙率
    slope_inv: float = 0.0          # 坡度倒数 (1/i)
    v_min_allowable: float = 0.0    # 最小允许流速 (m/s)
    v_max_allowable: float = 0.0    # 最大允许流速 (m/s)
    increase_percent_manual: Optional[float] = None  # 手动输入加大比例 (%)
    D_manual: Optional[float] = None  # 手动输入直径 (m，仅圆形使用)


# ============================================================
# 4. 附录E 梯形渠道实用经济断面计算函数
# ============================================================

def calculate_optimal_hydraulic_section(Q: float, n: float, i: float, m: float) -> Tuple[float, float, float, float]:
    """
    计算水力最佳断面 (附录E E.0.1)
    
    第一阶段：计算基准——水力最佳断面
    
    参数:
        Q: 设计流量 (m³/s)
        n: 糙率
        i: 渠底比降
        m: 边坡系数 (矩形时 m=0)
    
    返回:
        (h0, b0, beta0, K) - 水力最佳断面的水深、底宽、宽深比、几何形状因子K
    """
    if Q <= 0 or n <= 0 or i <= 0:
        return -1.0, -1.0, -1.0, -1.0
    
    # 步骤1.1: 计算几何形状因子 K = 2√(1+m²) - m
    sqrt_1_m2 = math.sqrt(1 + m * m)
    K = 2 * sqrt_1_m2 - m
    
    if K <= ZERO_TOLERANCE:
        return -1.0, -1.0, -1.0, -1.0
    
    # 步骤1.2: 计算水力最佳水深 h0
    # h0 = 1.189 × (nQ / (K × √i))^0.375
    # 注: 1.189 ≈ (1/K^(2/3))^(3/8) 的简化系数，实际按原公式计算更精确
    # 原公式: h0 = [ nQ / (√i × K^(2/3)) ]^(3/8)
    denominator = K ** (2.0 / 3.0)
    h0 = (n * Q / (math.sqrt(i) * denominator)) ** (3.0 / 8.0)
    
    # 步骤1.3: 计算水力最佳断面的其他参数
    # 最佳底宽: b0 = [2√(1+m²) - 2m] × h0 = 2(√(1+m²) - m) × h0
    b0 = 2 * (sqrt_1_m2 - m) * h0
    
    # 最佳宽深比: β0 = b0/h0 = 2(√(1+m²) - m)
    beta0 = 2 * (sqrt_1_m2 - m)
    
    return h0, b0, beta0, K


def calculate_eta_from_alpha(alpha: float) -> float:
    """
    根据α值计算水深比 η = h/h0 (公式 E.0.2-2)
    
    方程: (h/h0)² - 2α^2.5(h/h0) + α = 0
    解析解 (取较小根): η = α^2.5 - √(α^5 - α)
    
    参数:
        alpha: 面积增大系数 (1.00 ~ 1.05)
    
    返回:
        η (h/h0比值)
    """
    if alpha < 1.0:
        alpha = 1.0
    
    # 当 α = 1.00 时，η = 1.0
    if abs(alpha - 1.00) < ZERO_TOLERANCE:
        return 1.0
    
    # η = α^2.5 - √(α^5 - α)
    alpha_2_5 = alpha ** 2.5
    alpha_5 = alpha ** 5
    
    discriminant = alpha_5 - alpha
    if discriminant < 0:
        # 理论上不应该发生，但做保护
        return 1.0
    
    eta = alpha_2_5 - math.sqrt(discriminant)
    
    return eta


def calculate_beta_from_alpha_eta(alpha: float, eta: float, K: float, m: float) -> float:
    """
    根据α、η和K计算宽深比β (公式 E.0.2-3)
    
    β = [α/η² × K] - m
    
    参数:
        alpha: 面积增大系数
        eta: 水深比 h/h0
        K: 几何形状因子 (2√(1+m²) - m)
        m: 边坡系数
    
    返回:
        β (宽深比)
    """
    if eta <= ZERO_TOLERANCE:
        return -1.0
    
    beta = (alpha / (eta * eta)) * K - m
    
    return beta


def calculate_all_appendix_e_schemes(Q: float, n: float, i: float, m: float) -> List[Dict[str, Any]]:
    """
    计算附录E所有α值(1.00~1.05)对应的断面方案
    
    参数:
        Q: 设计流量 (m³/s)
        n: 糙率
        i: 渠底比降
        m: 边坡系数
    
    返回:
        方案列表，每个方案包含: alpha, eta, h, b, beta, A, V, scheme_type
    """
    schemes = []
    
    # 计算水力最佳断面
    h0, b0, beta0, K = calculate_optimal_hydraulic_section(Q, n, i, m)
    if h0 < 0 or K < 0:
        return schemes
    
    # 定义方案类型描述
    scheme_types = {
        1.00: "水力最佳断面",
        1.01: "实用经济断面",
        1.02: "实用经济断面",
        1.03: "实用经济断面",
        1.04: "实用经济断面",
        1.05: "实用经济断面"
    }
    
    for alpha in ALPHA_VALUES:
        eta = calculate_eta_from_alpha(alpha)
        h = h0 * eta
        beta = calculate_beta_from_alpha_eta(alpha, eta, K, m)
        b = beta * h
        A = (b + m * h) * h
        V = Q / A if A > ZERO_TOLERANCE else 0
        
        # 计算湿周和水力半径
        X = b + 2 * h * math.sqrt(1 + m * m)
        R = A / X if X > ZERO_TOLERANCE else 0
        
        # 面积增加百分比
        area_increase = (alpha - 1.0) * 100
        
        schemes.append({
            'alpha': alpha,
            'eta': eta,
            'h': h,
            'b': b,
            'beta': beta,
            'A': A,
            'X': X,
            'R': R,
            'V': V,
            'area_increase': area_increase,
            'scheme_type': scheme_types.get(alpha, "实用经济断面")
        })
    
    return schemes


def calculate_economic_section_appendix_e(Q: float, n: float, i: float, m: float, 
                                           v_min: float, v_max: float) -> Tuple[bool, float, float, float, float, str, List[Dict]]:
    """
    使用附录E算法计算经济实用断面
    
    按照"梯形渠道实用经济断面计算流程"：
    - 第一阶段：计算水力最佳断面 h0
    - 第二阶段：对α=1.00~1.05生成所有方案
    - 优先选择α=1.00（水力最佳断面），如果流速不满足则逐步增大α
    
    参数:
        Q: 设计流量 (m³/s)
        n: 糙率
        i: 渠底比降
        m: 边坡系数
        v_min: 最小允许流速 (m/s)
        v_max: 最大允许流速 (m/s)
    
    返回:
        (success, h, b, beta, alpha_used, design_method, all_schemes)
        all_schemes: 所有α值方案的列表，用于展示备选方案
    """
    # ========== 计算所有方案 ==========
    all_schemes = calculate_all_appendix_e_schemes(Q, n, i, m)
    
    if not all_schemes:
        return False, -1, -1, -1, -1, "水力最佳断面计算失败", []
    
    # ========== 选择满足流速约束的最优方案 ==========
    selected_scheme = None
    for scheme in all_schemes:
        V = scheme['V']
        if V > v_min and V < v_max:
            selected_scheme = scheme
            break  # 优先选择α最小的满足约束的方案
    
    if selected_scheme:
        alpha = selected_scheme['alpha']
        if abs(alpha - 1.00) < ZERO_TOLERANCE:
            method = "灌溉与排水工程设计标准-2018 附录E 水力最佳断面(α=1.00)与实用经济断面(α=1.01~1.05)"
        else:
            method = f"灌溉与排水工程设计标准-2018 附录E 水力最佳断面(α=1.00)与实用经济断面(α=1.01~1.05)"
        return (True, selected_scheme['h'], selected_scheme['b'], 
                selected_scheme['beta'], alpha, method, all_schemes)
    
    # 如果所有方案都不满足流速约束，返回水力最佳断面
    first_scheme = all_schemes[0]  # α=1.00
    V0 = first_scheme['V']
    
    if V0 <= v_min:
        return (False, first_scheme['h'], first_scheme['b'], 
                first_scheme['beta'], 1.00, "附录E计算(流速过低)", all_schemes)
    elif V0 >= v_max:
        return (False, first_scheme['h'], first_scheme['b'], 
                first_scheme['beta'], 1.00, "附录E计算(流速过高)", all_schemes)
    else:
        return (True, first_scheme['h'], first_scheme['b'], 
                first_scheme['beta'], 1.00, "附录E水力最佳断面", all_schemes)


# ============================================================
# 5. 梯形与矩形明渠水力计算
# ============================================================

def calculate_area(b: float, h: float, m: float) -> float:
    """
    计算梯形明渠的过水面积

    参数:
        b: 渠道底宽 (m)
        h: 渠道水深 (m)
        m: 渠道边坡系数 (矩形时 m=0)

    返回:
        过水面积 (m²)
    """
    if h < 0:
        h = 0
    return (b + m * h) * h


def calculate_wetted_perimeter(b: float, h: float, m: float) -> float:
    """
    计算梯形明渠的湿周

    参数:
        b: 渠道底宽 (m)
        h: 渠道水深 (m)
        m: 渠道边坡系数 (矩形时 m=0)

    返回:
        湿周 (m)
    """
    if h < 0:
        h = 0
    return b + 2 * h * math.sqrt(1 + m * m)


def calculate_hydraulic_radius(b: float, h: float, m: float) -> float:
    """
    计算梯形明渠的水力半径

    参数:
        b: 渠道底宽 (m)
        h: 渠道水深 (m)
        m: 渠道边坡系数 (矩形时 m=0)

    返回:
        水力半径 (m)
    """
    A = calculate_area(b, h, m)
    X = calculate_wetted_perimeter(b, h, m)

    if X > ZERO_TOLERANCE:
        return A / X
    else:
        return 0.0


def calculate_flow_rate(b: float, h: float, i: float, n: float, m: float) -> float:
    """
    计算梯形明渠的流量（曼宁公式）

    参数:
        b: 渠道底宽 (m)
        h: 渠道水深 (m)
        i: 渠道底坡
        n: 渠道糙率
        m: 渠道边坡系数 (矩形时 m=0)

    返回:
        流量 (m³/s)，计算出错时返回 -1
    """
    if h <= ZERO_TOLERANCE or n <= ZERO_TOLERANCE or i <= ZERO_TOLERANCE:
        return 0.0

    A = calculate_area(b, h, m)
    R = calculate_hydraulic_radius(b, h, m)

    if A <= ZERO_TOLERANCE or R <= ZERO_TOLERANCE:
        return 0.0

    try:
        Q = (1.0 / n) * A * (R ** (2.0 / 3.0)) * (i ** 0.5)
        return Q
    except:
        return -1.0


def calculate_velocity(Q: float, A: float) -> float:
    """
    计算水流流速

    参数:
        Q: 流量 (m³/s)
        A: 过水面积 (m²)

    返回:
        流速 (m/s)
    """
    if A > ZERO_TOLERANCE:
        return Q / A
    else:
        return 0.0


def calculate_depth_for_flow(target_Q: float, b: float, i: float, n: float, m: float,
                              initial_guess_h: float = -1) -> float:
    """
    根据给定流量反算水深

    参数:
        target_Q: 目标流量 (m³/s)
        b: 渠道底宽 (m)
        i: 渠道底坡
        n: 渠道糙率
        m: 渠道边坡系数 (矩形时 m=0)
        initial_guess_h: 初始水深猜测值

    返回:
        计算得到的水深 (m)，失败返回 -1
    """
    MAX_ITER = 200
    TOLERANCE = 0.0005

    # 输入有效性检查
    if target_Q <= ZERO_TOLERANCE or b < 0 or i <= ZERO_TOLERANCE or n <= ZERO_TOLERANCE:
        return -1.0

    # 确定初始猜测值
    if initial_guess_h > 0:
        h_guess = initial_guess_h
    else:
        try:
            h_guess = (target_Q / b) ** 0.5 if b > 0 else 0.1
            if h_guess <= ZERO_TOLERANCE:
                h_guess = 0.1
        except:
            h_guess = 0.1

    if h_guess <= ZERO_TOLERANCE:
        h_guess = 0.01

    # 迭代求解
    for _ in range(MAX_ITER):
        h_prev = h_guess
        Q_calc = calculate_flow_rate(b, h_guess, i, n, m)

        if Q_calc < 0:
            return -1.0

        # 检查收敛
        if abs(Q_calc - target_Q) <= TOLERANCE * target_Q:
            return h_guess

        # 调整猜测值
        if Q_calc > ZERO_TOLERANCE:
            adj_factor = (target_Q / Q_calc) ** 0.375
            adj_factor = max(0.5, min(1.5, adj_factor))
            h_guess = h_guess * adj_factor
        elif target_Q > Q_calc:
            h_guess = h_guess * 1.5
        else:
            h_guess = h_guess * 0.5

        # 防止无效值
        if h_guess <= ZERO_TOLERANCE:
            h_guess = h_prev / 2 + ZERO_TOLERANCE
        if h_guess <= ZERO_TOLERANCE:
            h_guess = 0.001
        if h_guess > 1000:
            return -1.0

        # 防止停滞
        if abs(h_guess - h_prev) < ZERO_TOLERANCE / 10:
            return h_guess

    return -1.0


def calculate_dimensions_for_flow_and_beta(Q: float, i: float, n: float, m: float,
                                            target_beta: float) -> Tuple[bool, float, float]:
    """
    根据给定流量和宽深比计算水深和底宽

    参数:
        Q: 设计流量 (m³/s)
        i: 渠道底坡
        n: 渠道糙率
        m: 渠道边坡系数 (矩形时 m=0)
        target_beta: 目标宽深比

    返回:
        (成功标志, 水深h, 底宽b)
    """
    # 输入有效性检查
    if Q <= ZERO_TOLERANCE or i <= ZERO_TOLERANCE or n <= ZERO_TOLERANCE or target_beta <= ZERO_TOLERANCE:
        return False, -1.0, -1.0

    try:
        # 计算几何常数
        C1 = target_beta + m
        C2 = target_beta + 2 * math.sqrt(1 + m * m)

        if C1 <= ZERO_TOLERANCE or C2 <= ZERO_TOLERANCE:
            return False, -1.0, -1.0

        # 计算组合系数K
        K = (1 / n) * C1 * ((C1 / C2) ** (2.0 / 3.0)) * (i ** 0.5)

        if K <= ZERO_TOLERANCE:
            return False, -1.0, -1.0

        # 解出h
        h_pow_8_3 = Q / K
        if h_pow_8_3 <= 0:
            return False, -1.0, -1.0

        h_out = h_pow_8_3 ** (3.0 / 8.0)
        b_out = target_beta * h_out

        if h_out > 0 and b_out >= 0:
            return True, h_out, b_out

    except:
        pass

    return False, -1.0, -1.0


def calculate_depth_for_flow_and_bottom_width(Q: float, i: float, n: float, m: float,
                                               target_b: float) -> Tuple[bool, float]:
    """
    根据给定流量和底宽计算水深（二分法）

    参数:
        Q: 设计流量 (m³/s)
        i: 渠道底坡
        n: 渠道糙率
        m: 渠道边坡系数 (矩形时 m=0)
        target_b: 目标底宽 (m)

    返回:
        (成功标志, 水深h)
    """
    MAX_ITER = 500
    TOLERANCE = 0.0001

    # 输入有效性检查
    if Q <= ZERO_TOLERANCE or i <= ZERO_TOLERANCE or n <= ZERO_TOLERANCE or target_b <= ZERO_TOLERANCE:
        return False, -1.0

    # 设置初始搜索范围
    h_min = 0.001
    h_max = 50.0

    # 检查边界条件
    Q_min = calculate_flow_rate(target_b, h_min, i, n, m)
    Q_max = calculate_flow_rate(target_b, h_max, i, n, m)

    if Q_min < 0 or Q_max < 0:
        return False, -1.0

    if Q < Q_min:
        return False, -1.0

    if Q > Q_max:
        h_max = 100.0
        Q_max = calculate_flow_rate(target_b, h_max, i, n, m)
        if Q_max < 0 or Q > Q_max:
            return False, -1.0

    # 二分法迭代求解
    Q_calc = 0
    h_current = 0
    for _ in range(MAX_ITER):
        h_current = (h_min + h_max) / 2
        Q_calc = calculate_flow_rate(target_b, h_current, i, n, m)

        if Q_calc < 0:
            return False, -1.0

        # 检查收敛
        if abs(Q_calc - Q) <= TOLERANCE * Q:
            return True, h_current

        # 调整搜索范围
        if Q_calc < Q:
            h_min = h_current
        else:
            h_max = h_current

        # 防止搜索范围过小
        if (h_max - h_min) < ZERO_TOLERANCE:
            break

    # 放宽容差再检查
    if abs(Q_calc - Q) <= TOLERANCE * Q * 10:
        return True, h_current

    return False, -1.0


def get_flow_increase_percent(design_Q: float) -> float:
    """
    根据设计流量查找加大流量百分比

    参数:
        design_Q: 设计流量 (m³/s)

    返回:
        加大百分比 (如30表示30%)
    """
    if design_Q <= 0:
        return 0.0
    elif design_Q < 1:
        return 30.0
    elif design_Q < 5:
        return 25.0
    elif design_Q < 20:
        return 20.0
    elif design_Q < 50:
        return 15.0
    elif design_Q < 100:
        return 10.0
    elif design_Q <= 300:
        return 5.0
    else:
        return 5.0


def quick_calculate_trapezoidal(Q: float, m: float, n: float, slope_inv: float,
                                v_min: float, v_max: float,
                                manual_beta: float = None,
                                manual_b: float = None,
                                manual_increase_percent: float = None) -> Dict[str, Any]:
    """
    梯形明渠快速计算主函数

    参数:
        Q: 设计流量 (m³/s)
        m: 边坡系数
        n: 糙率
        slope_inv: 坡度倒数 (1/i)
        v_min: 不淤流速 (m/s)
        v_max: 不冲流速 (m/s)
        manual_beta: 手动指定宽深比 (可选)
        manual_b: 手动指定底宽 (可选)
        manual_increase_percent: 手动加大百分比 (可选)

    返回:
        包含所有计算结果的字典
    """
    result = {
        'success': False,
        'error_message': '',
        'design_method': '',

        # 设计工况结果
        'b_design': 0,      # 设计底宽
        'h_design': 0,      # 设计水深
        'V_design': 0,      # 设计流速
        'A_design': 0,      # 过水面积
        'X_design': 0,      # 湿周
        'R_design': 0,      # 水力半径
        'Beta_design': 0,   # 宽深比
        'Q_calc': 0,        # 计算流量

        # 加大流量工况
        'increase_percent': 0,  # 加大百分比
        'Q_increased': 0,       # 加大流量
        'h_increased': 0,       # 加大水深
        'V_increased': 0,       # 加大流速

        # 渠道尺寸
        'Fb': 0,            # 超高
        'h_prime': 0,       # 渠道高度

        # 设计方法标记
        'used_manual_beta': False,
        'used_manual_b': False,
        
        # 附录E备选方案列表（仅当未指定手动参数时填充）
        'appendix_e_schemes': [],
    }

    # 计算坡度
    i = 1.0 / slope_inv

    # ========== 输入参数验证 ==========
    if Q <= ZERO_TOLERANCE:
        result['error_message'] = 'Q (流量) 必须大于0'
        return result
    if m < 0:
        result['error_message'] = 'm (边坡) 不能为负'
        return result
    if n <= ZERO_TOLERANCE:
        result['error_message'] = 'n (糙率) 必须大于0'
        return result
    if slope_inv <= ZERO_TOLERANCE:
        result['error_message'] = '坡度倒数必须大于0'
        return result
    if v_min >= v_max:
        result['error_message'] = '不淤流速必须小于不冲流速'
        return result

    # 设计变量
    b_designed = 0
    h_designed = 0
    V_designed = 0
    design_successful = False
    design_method = ''

    # ========== 手动底宽优先 ==========
    if manual_b is not None and manual_b > ZERO_TOLERANCE:
        success, h_out = calculate_depth_for_flow_and_bottom_width(Q, i, n, m, manual_b)
        if success:
            A_out = calculate_area(manual_b, h_out, m)
            V_out = calculate_velocity(Q, A_out)
            Beta_out = manual_b / h_out if h_out > ZERO_TOLERANCE else 0

            if V_out > v_min and V_out < v_max and Beta_out > ZERO_TOLERANCE and Beta_out <= MAX_BETA:
                b_designed = manual_b
                h_designed = h_out
                V_designed = V_out
                design_successful = True
                design_method = '手动底宽'
                result['used_manual_b'] = True
            else:
                if V_out <= v_min or V_out >= v_max:
                    design_method = '手动底宽(流速不符)'
                else:
                    design_method = '手动底宽(宽深比不符)'
        else:
            design_method = '手动底宽(计算失败)'

    # ========== 手动宽深比次之 (如果底宽未指定) ==========
    if not design_successful and manual_beta is not None and manual_beta > ZERO_TOLERANCE:
        success, h_out, b_out = calculate_dimensions_for_flow_and_beta(Q, i, n, m, manual_beta)
        if success:
            A_out = calculate_area(b_out, h_out, m)
            V_out = calculate_velocity(Q, A_out)

            if V_out > v_min and V_out < v_max:
                b_designed = b_out
                h_designed = h_out
                V_designed = V_out
                design_successful = True
                design_method = '手动宽深比'
                result['used_manual_beta'] = True
            else:
                design_method = '手动宽深比(流速不符)'
        else:
            design_method = '手动宽深比(计算失败)'

    # ========== 附录E算法计算（如果两者都未成功）==========
    if not design_successful:
        # 使用附录E梯形渠道实用经济断面算法
        success_e, h_e, b_e, beta_e, alpha_e, method_e, all_schemes = calculate_economic_section_appendix_e(
            Q, n, i, m, v_min, v_max
        )
        
        if success_e and h_e > 0 and b_e > 0:
            b_designed = b_e
            h_designed = h_e
            A_e = calculate_area(b_e, h_e, m)
            V_designed = calculate_velocity(Q, A_e) if A_e > ZERO_TOLERANCE else 0
            design_successful = True
            design_method = method_e
            # 存储所有备选方案供用户参考
            result['appendix_e_schemes'] = all_schemes

    # ========== 填充结果 ==========
    if design_successful:
        # 底宽四舍五入到三位小数（用于显示和后续计算）
        b_designed = round(b_designed, 3)
        # 水深四舍五入到三位小数（用于显示和后续计算）
        h_designed = round(h_designed, 3)

        # 使用四舍五入后的值重新计算所有参数（确保计算链路一致性）
        A_designed = calculate_area(b_designed, h_designed, m)
        A_designed = round(A_designed, 3)  # 过水面积保留3位小数
        
        X_designed = calculate_wetted_perimeter(b_designed, h_designed, m)
        X_designed = round(X_designed, 3)  # 湿周保留3位小数
        
        R_designed = calculate_hydraulic_radius(b_designed, h_designed, m)
        R_designed = round(R_designed, 3)  # 水力半径保留3位小数
        
        V_designed = calculate_velocity(Q, A_designed)
        V_designed = round(V_designed, 3)  # 流速保留3位小数
        
        Q_calc = calculate_flow_rate(b_designed, h_designed, i, n, m)
        Q_calc = round(Q_calc, 3)  # 计算流量保留3位小数
        
        Beta_designed = b_designed / h_designed if h_designed > ZERO_TOLERANCE else 0
        Beta_designed = round(Beta_designed, 3)  # 宽深比保留3位小数

        result['success'] = True
        result['b_design'] = b_designed
        result['h_design'] = h_designed
        result['V_design'] = V_designed
        result['A_design'] = A_designed
        result['X_design'] = X_designed
        result['R_design'] = R_designed
        result['Beta_design'] = Beta_designed
        result['Q_calc'] = Q_calc
        result['design_method'] = design_method

        # ========== 计算加大流量工况 ==========
        if manual_increase_percent is not None and manual_increase_percent >= 0:
            increase_percent = manual_increase_percent
        else:
            increase_percent = get_flow_increase_percent(Q)

        Q_increased = Q * (1 + increase_percent / 100)
        Q_increased = round(Q_increased, 3)  # 加大流量保留3位小数
        
        # 使用保留3位小数的底宽进行加大水深计算
        h_increased = calculate_depth_for_flow(Q_increased, b_designed, i, n, m, h_designed)

        result['increase_percent'] = increase_percent
        result['Q_increased'] = Q_increased

        if h_increased > 0:
            h_increased = round(h_increased, 3)  # 加大水深保留3位小数
            result['h_increased'] = h_increased
            
            # 使用保留3位小数的值计算后续参数
            A_increased = calculate_area(b_designed, h_increased, m)
            A_increased = round(A_increased, 3)
            result['A_increased'] = A_increased
            
            V_increased = calculate_velocity(Q_increased, A_increased)
            V_increased = round(V_increased, 3)
            result['V_increased'] = V_increased
            
            X_increased = calculate_wetted_perimeter(b_designed, h_increased, m)
            X_increased = round(X_increased, 3)
            result['X_increased'] = X_increased
            
            R_increased = calculate_hydraulic_radius(b_designed, h_increased, m)
            R_increased = round(R_increased, 3)
            result['R_increased'] = R_increased

            # 【规范 6.4.8-2】计算超高和渠道高度
            # Fb = (1/4) * hb + 0.2，使用保留3位小数的加大水深
            Fb = 0.25 * h_increased + 0.2
            Fb = round(Fb, 3)  # 超高保留3位小数
            
            h_prime = h_increased + Fb
            h_prime = round(h_prime, 3)  # 渠道高度保留3位小数

            result['Fb'] = Fb
            result['h_prime'] = h_prime
        else:
            result['h_increased'] = -1
            result['V_increased'] = -1
            result['A_increased'] = -1
            result['X_increased'] = -1
            result['R_increased'] = -1
            result['Fb'] = -1
            result['h_prime'] = -1
    else:
        result['error_message'] = design_method if design_method else '无法找到满足约束条件的设计方案'
        result['design_method'] = design_method

    return result


def quick_calculate_rectangular(Q: float, n: float, slope_inv: float,
                               v_min: float, v_max: float,
                               manual_beta: float = None,
                               manual_b: float = None,
                               manual_increase_percent: float = None) -> Dict[str, Any]:
    """
    矩形明渠快速计算 (梯形明渠 m=0 的特例)

    参数:
        Q: 设计流量 (m³/s)
        n: 糙率
        slope_inv: 坡度倒数 (1/i)
        v_min: 不淤流速 (m/s)
        v_max: 不冲流速 (m/s)
        manual_beta: 手动指定宽深比 (可选)
        manual_b: 手动指定底宽 (可选)
        manual_increase_percent: 手动加大百分比 (可选)

    返回:
        包含所有计算结果的字典
    """
    return quick_calculate_trapezoidal(Q, 0.0, n, slope_inv, v_min, v_max,
                                      manual_beta, manual_b, manual_increase_percent)


# ============================================================
# 6. 圆形明渠水力计算
# ============================================================

def round_up_to_step(value: float, step_val: float) -> float:
    """
    向上舍入到指定步长的倍数
    """
    if step_val <= 1e-7:
        return value
    return math.ceil(value / step_val) * step_val


def get_design_diameter_rounded(D_calculated: float) -> float:
    """
    根据计算直径获取设计直径（向上取整）
    """
    if D_calculated <= 0.5:
        return round_up_to_step(D_calculated, 0.05)
    elif D_calculated <= 1.5:
        return round_up_to_step(D_calculated, 0.1)
    else:
        return round_up_to_step(D_calculated, 0.2)


def get_circular_flow_increase_percent(design_Q: float) -> float:
    """
    根据设计流量确定圆形明渠的自动加大比例
    """
    if design_Q <= 0:
        return 25.0
    elif design_Q < 1:
        return 30.0
    elif design_Q < 5:
        return 25.0
    elif design_Q < 20:
        return 20.0
    elif design_Q < 50:
        return 15.0
    elif design_Q < 100:
        return 10.0
    else:
        return 5.0


def get_circular_coefficients_for_y_over_D(y_over_D: float) -> Tuple[float, float, float, float]:
    """
    计算给定y/D比值的无量纲系数（圆形明渠）
    """
    alpha = y_over_D
    if alpha <= 1e-7:
        return (0.0, 0.0, 0.0, 0.0)
    if alpha >= 0.9999999:
        alpha = 0.9999999
    acos_arg = 1 - 2 * alpha
    acos_arg = max(-1.0, min(1.0, acos_arg))
    theta = 2 * math.acos(acos_arg)
    k_A = (theta - math.sin(theta)) / 8
    k_P = theta / 2
    k_R = k_A / k_P if k_P > 1e-7 and k_A > 1e-7 else 0.0
    return (k_A, k_P, k_R, theta)


def calculate_water_depth_y_circular(D: float, K_target: float) -> Tuple[float, float, float, float, float]:
    """
    根据给定直径D和流量模数K_target求解水深y（圆形明渠）
    """
    if D <= 1e-6 or K_target < -1e-7:
        return (-1.0, 0.0, -1.0, -1.0, -1.0)
    if abs(K_target) < 1e-8:
        return (0.0, 0.0, 0.0, 0.0, 0.0)
    A_full = PI * D**2 / 4
    R_full = D / 4
    K_full_geometric = A_full * R_full**(2/3)
    if K_target > K_full_geometric * 1.017:
        return (-1.0, 0.0, -1.0, -1.0, -1.0)
    y_low, y_high = 1e-6 * D, D
    for _ in range(MAX_ITERATIONS_Y):
        y_mid = (y_low + y_high) / 2
        y_mid = max(1e-7 * D, min(0.9999999 * D, y_mid))
        acos_param = 1 - (2 * y_mid / D)
        acos_param = max(-1.0, min(1.0, acos_param))
        theta_calc = 2 * math.acos(acos_param)
        A_calc = (D**2 / 8) * (theta_calc - math.sin(theta_calc))
        P_calc = (D / 2) * theta_calc
        if P_calc < 1e-7 or A_calc < 1e-7:
            K_calc, R_calc = 0.0, 0.0
        else:
            R_calc = A_calc / P_calc
            K_calc = A_calc * R_calc**(2/3) if R_calc > 1e-7 else 0.0
        if abs(K_calc - K_target) < TOLERANCE_Y or (y_high - y_low) / 2 < TOLERANCE_Y / (D * 1000 + K_target + 1):
            return (y_mid, theta_calc, A_calc, P_calc, R_calc)
        if K_calc < K_target: y_low = y_mid
        else: y_high = y_mid
    return (-1.0, 0.0, -1.0, -1.0, -1.0)


def calculate_circular_hydraulics(D: float, Q: float, n: float, slope: float, K_req: float) -> HydraulicResult:
    """
    计算给定直径D和流量Q的圆形明渠水力特性
    """
    result = HydraulicResult()
    if D <= 0 or K_req < -1e-7:
        return result
    total_channel_area = PI * D**2 / 4
    y, theta, A, P, R = calculate_water_depth_y_circular(D, K_req)
    if y < -1e-7 or A < -1e-7 or P < -1e-7 or R < -1e-7:
        return result
    result.y, result.A, result.P, result.R, result.theta = y, A, P, R, theta
    if abs(Q) < 1e-7:
        result.V, result.Q_check = 0.0, 0.0
    elif A > 1e-6:
        result.V = Q / A
    else:
        result.V = -999.0
        return result
    result.FB = D - y
    if total_channel_area > 1e-6 and A >= -1e-7:
        result.PA = max(0.0, min(1.0, (total_channel_area - A) / total_channel_area))
    else:
        result.PA = 0.0 if total_channel_area <= 1e-6 else -1.0
    if n > 1e-6 and slope > 1e-9 and A > 1e-6 and R > 1e-6:
        result.Q_check = (1 / n) * A * R**(2/3) * math.sqrt(slope)
    elif abs(Q) < 1e-7:
        result.Q_check = 0.0
    result.success = True
    return result


def solve_D_and_y_from_A_and_R(A_target: float, R_target: float) -> Tuple[bool, float, float, float]:
    """
    根据目标面积和水力半径求解直径D和水深y（圆形明渠）
    """
    if A_target <= 1e-7 or R_target <= 1e-7:
        return (False, -1.0, -1.0, -1.0)
    target_val_R2_div_A = (R_target**2) / A_target
    min_possible_ratio = 1.0 / (4 * PI)
    if target_val_R2_div_A < min_possible_ratio * 0.9:
        return (False, -1.0, -1.0, -1.0)
    alpha_low, alpha_high = 0.0001, 0.999999
    if target_val_R2_div_A < 0.12:
        alpha_low = 0.6
    for _ in range(MAX_ITERATIONS_Y):
        alpha_mid = (alpha_low + alpha_high) / 2
        k_A_calc, k_P_calc, k_R_calc, theta_calc = get_circular_coefficients_for_y_over_D(alpha_mid)
        if k_A_calc <= 1e-8:
            f_alpha = 1e10
            alpha_low = alpha_mid
            continue
        f_alpha = (k_R_calc**2) / k_A_calc
        if abs(f_alpha - target_val_R2_div_A) < TOLERANCE_Y * 0.1 or (alpha_high - alpha_low) / 2 < TOLERANCE_Y * 0.01:
            if k_A_calc > 0:
                D_out = math.sqrt(A_target / k_A_calc)
                if D_out > MAX_ALLOWED_D: return (False, -1.0, -1.0, -1.0)
                return (True, D_out, alpha_mid * D_out, alpha_mid)
            return (False, -1.0, -1.0, -1.0)
        if f_alpha > target_val_R2_div_A: alpha_low = alpha_mid
        else: alpha_high = alpha_mid
    return (False, -1.0, -1.0, -1.0)


def _find_diameter_linear_search(Q_design, Q_inc, Q_min, n_roughness, slope,
                                   v_min_allowable, v_max_allowable,
                                   K_req_design, K_req_inc, K_req_min):
    """
    线性步进法查找满足约束的最小直径（原始算法，保留用于验证）
    
    返回:
        D_calculated: 满足约束的最小直径（精度0.001m），失败返回-1
    """
    current_D = 0.1  # 从最小直径 0.1m 开始搜索
    current_D = max(current_D, ITERATION_DIAMETER_STEP)
    D_calculated = -1
    for _ in range(MAX_ITERATIONS_D_CALC):
        met = True
        h_d = calculate_circular_hydraulics(current_D, Q_design, n_roughness, slope, K_req_design)
        if not h_d.success or h_d.V < v_min_allowable or h_d.V > v_max_allowable or h_d.FB < MIN_FREEBOARD or h_d.PA < (MIN_FREE_AREA_PERCENT / 100):
            met = False
        if met:
            h_i = calculate_circular_hydraulics(current_D, Q_inc, n_roughness, slope, K_req_inc)
            if not h_i.success or h_i.V < v_min_allowable or h_i.V > v_max_allowable or h_i.FB < MIN_FREEBOARD or h_i.PA < (MIN_FREE_AREA_PERCENT / 100):
                met = False
        if met:
            h_m = calculate_circular_hydraulics(current_D, Q_min, n_roughness, slope, K_req_min)
            if not h_m.success or h_m.V < v_min_allowable:
                met = False
        if met:
            D_calculated = current_D
            break
        current_D = round(current_D + ITERATION_DIAMETER_STEP, 5)
        if current_D > MAX_ALLOWED_D:
            break
    return D_calculated


def _find_diameter_binary_search(Q_design, Q_inc, Q_min, n_roughness, slope,
                                  v_min_allowable, v_max_allowable,
                                  K_req_design, K_req_inc, K_req_min):
    """
    二分法查找满足约束的最小直径
    
    约束条件分析：
    - 超高FB、净空面积PA：与D单调递增（D增大则满足）
    - 流速V：与D单调递减（D增大则V减小）
    - 流速有上下界约束：v_min <= V <= v_max
    
    搜索策略：
    1. 二分查找满足"超高+净空面积+流速上限"约束的最小D
    2. 验证该D是否满足流速下限约束
    
    返回:
        D_calculated: 满足约束的最小直径（精度0.001m），失败返回-1
    """
    def check_lower_bound_constraints(D):
        """检查下界约束：success + FB + PA + V <= v_max（这些约束随D增大而满足）"""
        # 设计工况
        h_d = calculate_circular_hydraulics(D, Q_design, n_roughness, slope, K_req_design)
        if not (h_d.success and
                h_d.V <= v_max_allowable and
                h_d.FB >= MIN_FREEBOARD and
                h_d.PA >= MIN_FREE_AREA_PERCENT / 100):
            return False
        # 加大工况
        h_i = calculate_circular_hydraulics(D, Q_inc, n_roughness, slope, K_req_inc)
        if not (h_i.success and
                h_i.V <= v_max_allowable and
                h_i.FB >= MIN_FREEBOARD and
                h_i.PA >= MIN_FREE_AREA_PERCENT / 100):
            return False
        # 最小工况只需检查success
        h_m = calculate_circular_hydraulics(D, Q_min, n_roughness, slope, K_req_min)
        if not h_m.success:
            return False
        return True
    
    def check_all_constraints(D):
        """检查所有约束（包括流速下限）"""
        # 设计工况
        h_d = calculate_circular_hydraulics(D, Q_design, n_roughness, slope, K_req_design)
        if not (h_d.success and
                v_min_allowable <= h_d.V <= v_max_allowable and
                h_d.FB >= MIN_FREEBOARD and
                h_d.PA >= MIN_FREE_AREA_PERCENT / 100):
            return False
        # 加大工况
        h_i = calculate_circular_hydraulics(D, Q_inc, n_roughness, slope, K_req_inc)
        if not (h_i.success and
                v_min_allowable <= h_i.V <= v_max_allowable and
                h_i.FB >= MIN_FREEBOARD and
                h_i.PA >= MIN_FREE_AREA_PERCENT / 100):
            return False
        # 最小工况
        h_m = calculate_circular_hydraulics(D, Q_min, n_roughness, slope, K_req_min)
        if not (h_m.success and h_m.V >= v_min_allowable):
            return False
        return True
    
    # 初始化搜索区间
    D_low = max(0.1, ITERATION_DIAMETER_STEP)
    D_high = MAX_ALLOWED_D
    
    # 边界条件预检查：最小直径已满足所有约束
    if check_all_constraints(D_low):
        return round(math.ceil(D_low / ITERATION_DIAMETER_STEP) * ITERATION_DIAMETER_STEP, 5)
    
    # 检查最大直径是否满足下界约束（FB/PA/V上限）
    if not check_lower_bound_constraints(D_high):
        # 即使最大直径也无法满足超高/净空/流速上限约束，无解
        return -1
    
    # 二分查找满足下界约束的最小D
    while (D_high - D_low) > ITERATION_DIAMETER_STEP:
        D_mid = (D_low + D_high) / 2
        if check_lower_bound_constraints(D_mid):
            D_high = D_mid  # 满足下界约束，缩小上界
        else:
            D_low = D_mid   # 不满足，增大下界
    
    # 精度修正：向上舍入到0.001m
    D_result = math.ceil(D_high / ITERATION_DIAMETER_STEP) * ITERATION_DIAMETER_STEP
    D_result = round(D_result, 5)
    
    # 最终验证所有约束（包括流速下限）
    if D_result <= MAX_ALLOWED_D and check_all_constraints(D_result):
        return D_result
    else:
        # 满足下界约束但不满足流速下限，说明无解
        return -1


def process_circular_single_row(input_data: InputData) -> DesignResult:
    """
    处理单行圆形明渠计算
    """
    result = DesignResult()
    Q_design, n_roughness, slope_inv = input_data.Q_design, input_data.n_roughness, input_data.slope_inv
    v_min_allowable, v_max_allowable = input_data.v_min_allowable, input_data.v_max_allowable
    increase_percent_manual, D_manual = input_data.increase_percent_manual, input_data.D_manual
    if Q_design <= 0 or n_roughness <= 0 or slope_inv <= 0:
        result.error_message = "输入值无效（Q、N、坡度倒数必须大于0）"
        return result
    slope = 1 / slope_inv
    if increase_percent_manual is not None and increase_percent_manual >= 0:
        increase_percent_val = increase_percent_manual / 100.0
        result.increase_percent_source = "(手动)"
    else:
        increase_percent_val = get_circular_flow_increase_percent(Q_design) / 100.0
        result.increase_percent_source = "(自动)"
    result.increase_percent = increase_percent_val * 100
    K_req_design = Q_design * n_roughness / math.sqrt(slope)
    Q_inc = Q_design * (1 + increase_percent_val)
    K_req_inc = Q_inc * n_roughness / math.sqrt(slope)
    Q_min = Q_design * MIN_FLOW_FACTOR
    K_req_min = Q_min * n_roughness / math.sqrt(slope)
    result.Q_increased, result.Q_min = Q_inc, Q_min
    if D_manual is not None and D_manual > 0:
        D_design = D_manual
        result.D_calculated, result.D_design = round(D_manual, 3), D_design
        result.section_total_area = round(PI * D_design**2 / 4, 3)
        result.design = calculate_circular_hydraulics(D_design, Q_design, n_roughness, slope, K_req_design)
        result.increased = calculate_circular_hydraulics(D_design, Q_inc, n_roughness, slope, K_req_inc)
        result.minimum = calculate_circular_hydraulics(D_design, Q_min, n_roughness, slope, K_req_min)

        # 检查计算是否成功
        if not result.design.success:
            result.success = False
            result.error_message = f"计算失败：手动指定的直径 D={D_manual} m 过小，无法满足设计流量工况的要求。"
            return result

        if not result.increased.success:
            result.success = False
            result.error_message = (
                f"计算失败：手动指定的直径 D={D_manual} m 过小，无法满足加大流量工况的要求。\n\n"
                "建议解决方案：\n"
                "1. 增大直径\n"
                "2. 或者留空直径输入框，由系统自动计算最优直径"
            )
            return result

        result.success, result.check_passed = True, True
        return result
    # 使用二分法查找满足约束的最小直径
    D_calculated = _find_diameter_binary_search(
        Q_design, Q_inc, Q_min, n_roughness, slope,
        v_min_allowable, v_max_allowable,
        K_req_design, K_req_inc, K_req_min
    )
    if D_calculated <= 0:
        result.error_message = "计算无解"
        return result
    D_design = get_design_diameter_rounded(D_calculated)
    result.D_calculated, result.D_design, result.check_passed = round(D_calculated, 3), D_design, True
    result.section_total_area = round(PI * D_design**2 / 4, 3)
    result.design = calculate_circular_hydraulics(D_design, Q_design, n_roughness, slope, K_req_design)
    result.increased = calculate_circular_hydraulics(D_design, Q_inc, n_roughness, slope, K_req_inc)
    result.minimum = calculate_circular_hydraulics(D_design, Q_min, n_roughness, slope, K_req_min)
    result.success = True
    return result


def process_circular_batch(data_list: List[InputData]) -> List[DesignResult]:
    """
    批量处理多行圆形明渠数据
    """
    return [process_circular_single_row(data) for data in data_list]


def circular_result_to_dict(result: DesignResult) -> Dict[str, Any]:
    """
    将DesignResult转换为字典格式（圆形明渠）
    """
    return {
        "D_calculated": round(result.D_calculated, 3) if result.D_calculated > 0 else None,
        "D_design": round(result.D_design, 3) if result.D_design > 0 else None,
        "section_total_area": round(result.section_total_area, 3) if result.section_total_area > 0 else None,
        "A_d": round(result.design.A, 3) if result.design.A > 0 else None,
        "P_d": round(result.design.P, 3) if result.design.P > 0 else None,
        "R_d": round(result.design.R, 3) if result.design.R > 0 else None,
        "y_d": round(result.design.y, 3) if result.design.y >= 0 else None,
        "V_d": round(result.design.V, 3) if result.design.V >= 0 else None,
        "Q_check_d": round(result.design.Q_check, 3) if result.design.Q_check >= 0 else None,
        "PA_d": round(result.design.PA * 100, 1) if result.design.PA >= 0 else None,
        "FB_d": round(result.design.FB, 3) if result.design.FB >= 0 else None,
        "increase_percent": f"{result.increase_percent:.1f}% {result.increase_percent_source}",
        "Q_inc": round(result.Q_increased, 3) if result.Q_increased > 0 else None,
        "y_i": round(result.increased.y, 3) if result.increased.y >= 0 else None,
        "V_i": round(result.increased.V, 3) if result.increased.V >= 0 else None,
        "A_i": round(result.increased.A, 3) if result.increased.A > 0 else None,
        "P_i": round(result.increased.P, 3) if result.increased.P > 0 else None,
        "R_i": round(result.increased.R, 3) if result.increased.R > 0 else None,
        "Q_check_i": round(result.increased.Q_check, 3) if result.increased.Q_check >= 0 else None,
        "PA_i": round(result.increased.PA * 100, 1) if result.increased.PA >= 0 else None,
        "FB_i": round(result.increased.FB, 3) if result.increased.FB >= 0 else None,
        "Q_min": round(result.Q_min, 3) if result.Q_min > 0 else None,
        "y_m": round(result.minimum.y, 3) if result.minimum.y >= 0 else None,
        "V_m": round(result.minimum.V, 3) if result.minimum.V >= 0 else None,
        "success": result.success,
        "check_passed": result.check_passed,
        "error_message": result.error_message if result.error_message else None,
        "check_errors": result.check_errors if result.check_errors else None,
    }


def quick_calculate_circular(Q: float, n: float, slope_inv: float,
                             v_min: float = 0.5, v_max: float = 3.0,
                             increase_percent: Optional[float] = None,
                             manual_D: Optional[float] = None) -> Dict[str, Any]:
    """
    快速计算单个圆形明渠断面

    参数:
        Q: 设计流量 (m³/s)
        n: 糙率
        slope_inv: 坡度倒数 (1/i)
        v_min: 最小允许流速 (m/s)
        v_max: 最大允许流速 (m/s)
        increase_percent: 手动加大百分比 (可选)
        manual_D: 手动指定直径 (m，可选)

    返回:
        包含所有计算结果的字典
    """
    input_data = InputData(Q_design=Q, n_roughness=n, slope_inv=slope_inv, v_min_allowable=v_min,
                          v_max_allowable=v_max, increase_percent_manual=increase_percent, D_manual=manual_D)
    result = process_circular_single_row(input_data)
    return circular_result_to_dict(result)


def calculate_circular_hydraulic_params(D: float, y: float) -> Dict[str, float]:
    """
    根据直径和水深计算水力参数（圆形明渠）
    """
    if D <= 0 or y < 0 or y > D: return {"A": -1, "P": -1, "R": -1, "theta": -1}
    if y == 0: return {"A": 0, "P": 0, "R": 0, "theta": 0}
    k_A, k_P, k_R, theta = get_circular_coefficients_for_y_over_D(y / D)
    return {"A": round(k_A * D**2, 6), "P": round(k_P * D, 6), "R": round(k_R * D, 6), "theta": round(theta, 6)}


def calculate_circular_flow_capacity(D: float, n: float, slope_inv: float, y: float) -> float:
    """
    根据直径、糙率、坡度和水深计算流量（圆形明渠）
    """
    if D <= 0 or n <= 0 or slope_inv <= 0 or y < 0 or y > D: return -1.0
    if y == 0: return 0.0
    params = calculate_circular_hydraulic_params(D, y)
    if params["A"] < 0 or params["R"] < 0: return -1.0
    A, R, slope = params["A"], params["R"], 1 / slope_inv
    if R <= 0: return 0.0
    return round((1 / n) * A * R**(2/3) * math.sqrt(slope), 6)


# ============================================================
# 7. 统一调用接口
# ============================================================

def design_channel(section_type: SectionType, **kwargs) -> Dict[str, Any]:
    """
    统一的明渠设计计算接口

    参数:
        section_type: 明渠断面类型 (TRAPEZOIDAL, RECTANGULAR, CIRCULAR)
        **kwargs: 对应断面类型的计算参数

    返回:
        计算结果字典
    """
    if section_type == SectionType.CIRCULAR:
        # 映射通用参数到圆形明渠参数
        Q = kwargs.get('Q') or kwargs.get('Q_design')
        n = kwargs.get('n') or kwargs.get('n_roughness')
        slope_inv = kwargs.get('slope_inv')
        v_min = kwargs.get('v_min') or kwargs.get('v_min_allowable', 0.5)
        v_max = kwargs.get('v_max') or kwargs.get('v_max_allowable', 3.0)
        inc = kwargs.get('manual_increase_percent') or kwargs.get('increase_percent')
        manual_D = kwargs.get('manual_D') or kwargs.get('D_manual')

        return quick_calculate_circular(Q, n, slope_inv, v_min, v_max, inc, manual_D)

    elif section_type == SectionType.RECTANGULAR:
        return quick_calculate_rectangular(
            kwargs.get('Q'), kwargs.get('n'), kwargs.get('slope_inv'),
            kwargs.get('v_min'), kwargs.get('v_max'),
            kwargs.get('manual_beta'), kwargs.get('manual_b'),
            kwargs.get('manual_increase_percent')
        )

    else: # TRAPEZOIDAL
        return quick_calculate_trapezoidal(
            kwargs.get('Q'), kwargs.get('m', 0.0), kwargs.get('n'), kwargs.get('slope_inv'),
            kwargs.get('v_min'), kwargs.get('v_max'),
            kwargs.get('manual_beta'), kwargs.get('manual_b'),
            kwargs.get('manual_increase_percent')
        )


# ============================================================
# 8. 向后兼容接口（保持原有函数名）
# ============================================================

def quick_calculate(Q: float, m: float, n: float, slope_inv: float,
                    v_min: float, v_max: float,
                    manual_beta: float = None,
                    manual_b: float = None,
                    manual_increase_percent: float = None) -> Dict[str, Any]:
    """
    梯形明渠快速计算（向后兼容接口）
    """
    return quick_calculate_trapezoidal(Q, m, n, slope_inv, v_min, v_max,
                                      manual_beta, manual_b, manual_increase_percent)


# ============================================================
# 9. 测试代码
# ============================================================

if __name__ == '__main__':
    # ---------------------------------------------------------
    # 1. 断面独立调用测试
    # ---------------------------------------------------------
    print("=" * 70)
    print("测试: 断面独立调用接口")
    print("=" * 70)

    # 梯形明渠
    print("\n[梯形明渠案例]")
    res_t = quick_calculate_trapezoidal(Q=5.0, m=1.0, n=0.014, slope_inv=3000, v_min=0.5, v_max=3.0)
    print(f"  设计结果: b={res_t['b_design']:.2f}m, h={res_t['h_design']:.2f}m, V={res_t['V_design']:.2f}m/s")

    # 矩形明渠
    print("\n[矩形明渠案例]")
    res_r = quick_calculate_rectangular(Q=2.0, n=0.014, slope_inv=2000, v_min=0.4, v_max=2.5)
    print(f"  设计结果: b={res_r['b_design']:.2f}m, h={res_r['h_design']:.2f}m, V={res_r['V_design']:.2f}m/s")

    # 圆形明渠
    print("\n[圆形明渠案例]")
    res_c = quick_calculate_circular(Q=5.0, n=0.014, slope_inv=1000, v_min=0.6, v_max=3.0)
    print(f"  设计结果: D={res_c['D_design']:.2f}m, y={res_c['y_d']:.2f}m, V={res_c['V_d']:.2f}m/s")

    # ---------------------------------------------------------
    # 2. 统一接口 (design_channel) 测试
    # ---------------------------------------------------------
    print("\n" + "=" * 70)
    print("测试: 统一接口 design_channel")
    print("=" * 70)

    test_params = {'Q': 10.0, 'n': 0.016, 'slope_inv': 5000, 'v_min': 0.6, 'v_max': 2.5}

    for stype in SectionType:
        print(f"\n[统一接口测试 - {stype.value}]")
        # 补充断面特有参数
        params = test_params.copy()
        if stype == SectionType.TRAPEZOIDAL: params['m'] = 1.5

        result = design_channel(stype, **params)

        if result['success']:
            size_key = 'D_design' if stype == SectionType.CIRCULAR else 'b_design'
            depth_key = 'y_d' if stype == SectionType.CIRCULAR else 'h_design'
            vel_key = 'V_d' if stype == SectionType.CIRCULAR else 'V_design'
            print(f"  成功: 尺寸={result[size_key]:.2f}m, 水深={result[depth_key]:.2f}m, 流速={result[vel_key]:.2f}m/s")
        else:
            print(f"  失败: {result.get('error_message')}")

    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)
