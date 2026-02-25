# -*- coding: utf-8 -*-
"""
水力计算模块

提供水力学相关计算功能，包括流速、水力半径、水头损失、水位衔接等。
注意：具体计算公式将在后续完善。
"""

import math
from typing import List, Dict, Optional
import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import StructureType, InOutType
from config.constants import (
    GRAVITY, ZERO_TOLERANCE, VELOCITY_PRECISION, 
    ELEVATION_PRECISION, HEAD_LOSS_PRECISION, LOCAL_LOSS_COEFFICIENTS,
    TRANSITION_ZETA_COEFFICIENTS, TRANSITION_TWISTED_ZETA_RANGE,
    TRANSITION_LENGTH_COEFFICIENTS, TRANSITION_LENGTH_CONSTRAINTS
)


class HydraulicCalculator:
    """
    水力计算器
    
    负责水力学相关计算，包括：
    - 流速计算
    - 水力半径计算
    - 沿程水头损失
    - 局部水头损失
    - 水位衔接（水面线推求）
    """
    
    def __init__(self, settings: ProjectSettings):
        """
        初始化水力计算器
        
        Args:
            settings: 项目设置（包含流量、糙率等参数）
        """
        self.settings = settings
        self.design_flow = settings.design_flow
        self.max_flow = settings.max_flow
        self.roughness = settings.roughness
        
        # 倒虹吸水头损失字典（按名称匹配）
        self.inverted_siphon_losses: Dict[str, float] = {}
    
    def import_inverted_siphon_losses(self, losses: Dict[str, float]) -> None:
        """
        导入倒虹吸水头损失数据
        
        Args:
            losses: 倒虹吸名称到水头损失的映射 {"名称1": 损失值1, ...}
        """
        self.inverted_siphon_losses = losses.copy()
    
    def _estimate_structure_height(self, node: ChannelNode) -> None:
        """
        根据断面类型和参数推算结构高度
        
        仅对结构高度可从断面参数精确确定的类型进行推算：
          - 明渠-圆形 / 隧洞-圆形: D（直径）
          - 隧洞-马蹄形: 2×r（等效直径）
        
        倒虹吸不需要结构总高，也不需要计算渠顶高程，不做推算。
        其他类型（明渠-梯形/矩形、渡槽、隧洞-圆拱直墙型、矩形暗涵等）
        的结构高度必须从批量计算导入，不做近似估算。
        
        Args:
            node: 渠道节点（原地修改 structure_height）
        """
        if node.structure_height > 0:
            return  # 已有值，无需推算
        
        if not node.structure_type:
            return
        
        struct_name = node.structure_type.value if node.structure_type else ""
        params = node.section_params or {}
        
        # 明渠-U形: 结构高度从 h_prime 获取
        if "明渠-U形" in struct_name:
            h_prime_u = params.get('h_prime', 0)
            if h_prime_u and h_prime_u > 0:
                node.structure_height = h_prime_u
            return

        # 明渠-圆形 / 隔洞-圆形: 结构高度 = 直径 D（精确）
        if "圆形" in struct_name:
            D = params.get('D', 0)
            if D and D > 0:
                node.structure_height = D
                return
        
        # 隧洞-马蹄形: 结构高度 = 2R（精确）
        if "马蹄形" in struct_name:
            r = params.get('R_circle', params.get('r', params.get('内半径', 0)))
            if r and r > 0:
                node.structure_height = 2 * r
                return
    
    def _get_bottom_width(self, params: dict) -> float:
        """从断面参数中获取底宽（兼容多种键名）"""
        return params.get('B', params.get('底宽', params.get('b', 0)))
    
    def _get_diameter(self, params: dict) -> float:
        """从断面参数中获取直径（兼容多种键名）"""
        return params.get('D', params.get('直径', 0))
    
    def _get_radius(self, params: dict) -> float:
        """从断面参数中获取半径（兼容多种键名）"""
        return params.get('R_circle', params.get('半径', params.get('内半径', params.get('r', 0))))
    
    def _circular_area(self, D: float, h: float) -> float:
        """计算圆形断面过水面积"""
        r = D / 2
        if h >= D:
            return math.pi * r * r
        cos_arg = max(-1.0, min(1.0, (r - h) / r))
        theta = 2 * math.acos(cos_arg)
        return r * r * (theta - math.sin(theta)) / 2
    
    def _circular_perimeter(self, D: float, h: float) -> float:
        """计算圆形断面湿周"""
        r = D / 2
        if h >= D:
            return math.pi * D
        cos_arg = max(-1.0, min(1.0, (r - h) / r))
        theta = 2 * math.acos(cos_arg)
        return r * theta

    # 马蹄形标准参数（与隧洞设计.py保持一致）
    _HORSESHOE_PARAMS = {
        1: (3.0, 0.294515, 0.201996),   # Ⅰ型: t, theta, c
        2: (2.0, 0.424031, 0.436624),   # Ⅱ型: t, theta, c
    }

    def _horseshoe_std_area(self, section_type: int, r: float, h: float) -> float:
        """马蹄形标准断面过水面积（真实公式，非圆形近似）"""
        try:
            t, theta, c = self._HORSESHOE_PARAMS[section_type]
        except KeyError:
            return self._circular_area(2 * r, h)
        R_arch = t * r
        e = R_arch * (1 - math.cos(theta))
        h = min(max(h, 0.0), 2 * r)
        if h <= 0:
            return 0.0
        if h <= e:
            cos_val = max(-1.0, min(1.0, 1 - h / R_arch))
            beta = math.acos(cos_val)
            return R_arch ** 2 * (beta - 0.5 * math.sin(2 * beta))
        elif h <= r:
            sin_val = max(-1.0, min(1.0, (1 - h / r) / t))
            alpha = math.asin(sin_val)
            return R_arch ** 2 * (c - alpha - 0.5 * math.sin(2 * alpha)
                                  + ((2 * t - 2) / t) * math.sin(alpha))
        else:
            cos_val = max(-1.0, min(1.0, h / r - 1))
            phi_half = math.acos(cos_val)
            phi = 2 * phi_half
            return r ** 2 * (t ** 2 * c + 0.5 * (math.pi - phi + math.sin(phi)))

    def _horseshoe_std_perimeter(self, section_type: int, r: float, h: float) -> float:
        """马蹄形标准断面湿周（真实公式，非圆形近似）"""
        try:
            t, theta, c = self._HORSESHOE_PARAMS[section_type]
        except KeyError:
            return self._circular_perimeter(2 * r, h)
        R_arch = t * r
        e = R_arch * (1 - math.cos(theta))
        h = min(max(h, 0.0), 2 * r)
        if h <= 0:
            return 0.0
        if h <= e:
            cos_val = max(-1.0, min(1.0, 1 - h / R_arch))
            beta = math.acos(cos_val)
            return 2 * R_arch * beta
        elif h <= r:
            sin_val = max(-1.0, min(1.0, (1 - h / r) / t))
            alpha = math.asin(sin_val)
            return 2 * t * r * (2 * theta - alpha)
        else:
            cos_val = max(-1.0, min(1.0, h / r - 1))
            phi_half = math.acos(cos_val)
            phi = 2 * phi_half
            return 4 * t * r * theta + r * (math.pi - phi)

    def _horseshoe_std_surface_width(self, section_type: int, r: float, h: float) -> float:
        """马蹄形标准断面水面宽度（精确几何公式）"""
        try:
            t, theta, c = self._HORSESHOE_PARAMS[section_type]
        except KeyError:
            rr = r
            if h <= 0 or h > 2 * rr:
                return 0.0
            return 2 * math.sqrt(max(0.0, rr * rr - (rr - h) ** 2))
        R_arch = t * r
        e = R_arch * (1 - math.cos(theta))
        h = min(max(h, 0.0), 2 * r)
        if h <= 0:
            return 0.0
        if h <= e:
            cos_val = max(-1.0, min(1.0, 1 - h / R_arch))
            beta = math.acos(cos_val)
            return 2 * R_arch * math.sin(beta)
        elif h <= r:
            sin_val = max(-1.0, min(1.0, (1 - h / r) / t))
            alpha = math.asin(sin_val)
            return 2 * r * (t * math.cos(alpha) - t + 1)
        else:
            cos_val = max(-1.0, min(1.0, h / r - 1))
            phi_half = math.acos(cos_val)
            return 2 * r * math.sin(phi_half)

    def _horseshoe_section_type(self, sv: str) -> int:
        """从结构类型字符串解析马蹄形型号（1=Ⅰ型，2=Ⅱ型）"""
        if 'Ⅱ' in sv or 'II' in sv or '2' in sv:
            return 2
        return 1

    def _arch_tunnel_area(self, B: float, H_total: float, theta_rad: float, h: float) -> float:
        """圆拱直墙型过水面积（真实公式，与隧洞设计.py一致）"""
        if B <= 0 or H_total <= 0 or h <= 0 or theta_rad <= 0:
            return 0.0
        sin_half = math.sin(theta_rad / 2)
        if abs(sin_half) < 1e-9:
            return 0.0
        R_arch = (B / 2) / sin_half
        H_arch = R_arch * (1 - math.cos(theta_rad / 2))
        H_straight = max(0.0, H_total - H_arch)
        calc_depth = min(h, H_total)
        if calc_depth <= H_straight:
            return B * calc_depth
        Area_rect = B * H_straight
        h_in_arch = calc_depth - H_straight
        if h_in_arch >= H_arch - 1e-9:
            return Area_rect + (R_arch ** 2 / 2) * (theta_rad - math.sin(theta_rad))
        Area_arch_total = (R_arch ** 2 / 2) * (theta_rad - math.sin(theta_rad))
        h_dry = H_arch - h_in_arch
        d_temp = R_arch - h_dry
        acos_arg = max(-1.0, min(1.0, d_temp / R_arch))
        alpha_temp = math.acos(acos_arg)
        Area_dry = R_arch ** 2 * alpha_temp - d_temp * math.sqrt(max(0.0, R_arch ** 2 - d_temp ** 2))
        return Area_rect + Area_arch_total - Area_dry

    def _arch_tunnel_perimeter(self, B: float, H_total: float, theta_rad: float, h: float) -> float:
        """圆拱直墙型湿周（真实公式，与隧洞设计.py一致）"""
        if B <= 0 or H_total <= 0 or h <= 0 or theta_rad <= 0:
            return 0.0
        sin_half = math.sin(theta_rad / 2)
        if abs(sin_half) < 1e-9:
            return 0.0
        R_arch = (B / 2) / sin_half
        H_arch = R_arch * (1 - math.cos(theta_rad / 2))
        H_straight = max(0.0, H_total - H_arch)
        calc_depth = min(h, H_total)
        if calc_depth <= H_straight:
            return B + 2 * calc_depth
        h_in_arch = calc_depth - H_straight
        if h_in_arch >= H_arch - 1e-9:
            return B + 2 * H_straight + R_arch * theta_rad
        Total_Arc = R_arch * theta_rad
        h_dry = H_arch - h_in_arch
        d_temp = R_arch - h_dry
        acos_arg = max(-1.0, min(1.0, d_temp / R_arch))
        alpha_temp = math.acos(acos_arg)
        L_dry = 2 * R_arch * alpha_temp
        return B + 2 * H_straight + Total_Arc - L_dry

    def _arch_tunnel_surface_width(self, B: float, H_total: float, theta_rad: float, h: float) -> float:
        """圆拱直墙型水面宽度
        - h <= H_straight: 矩形段，B = 底宽（常数）
        - h > H_straight: 拱部，宽度随水深增加而收窄
        """
        if B <= 0 or H_total <= 0 or theta_rad <= 0:
            return B
        sin_half = math.sin(theta_rad / 2)
        if abs(sin_half) < 1e-9:
            return B
        R_arch = (B / 2) / sin_half
        H_arch = R_arch * (1 - math.cos(theta_rad / 2))
        H_straight = max(0.0, H_total - H_arch)
        h = min(h, H_total)
        if h <= H_straight:
            return B
        delta_h = h - H_straight
        cos_half = math.cos(theta_rad / 2)
        val = R_arch ** 2 - (delta_h + R_arch * cos_half) ** 2
        return 2 * math.sqrt(max(0.0, val))

    def _rect_chamfer_area(self, b: float, h: float, chamfer_angle_deg: float, chamfer_length: float) -> float:
        """带倒角矩形断面过水面积（与渡槽设计.py公式完全一致）"""
        if chamfer_angle_deg <= 0 or chamfer_length <= 0:
            return b * h
        chamfer_height = chamfer_length * math.tan(math.radians(chamfer_angle_deg))
        if chamfer_height <= 0:
            return b * h
        if h >= chamfer_height:
            return b * h - chamfer_length * chamfer_height
        else:
            return b * h - 2 * chamfer_length * h + chamfer_length * h ** 2 / chamfer_height

    def _rect_chamfer_perimeter(self, b: float, h: float, chamfer_angle_deg: float, chamfer_length: float) -> float:
        """带倒角矩形断面湿周（与渡槽设计.py公式完全一致）"""
        if chamfer_angle_deg <= 0 or chamfer_length <= 0:
            return b + 2 * h
        chamfer_height = chamfer_length * math.tan(math.radians(chamfer_angle_deg))
        chamfer_hypotenuse = chamfer_length / math.cos(math.radians(chamfer_angle_deg))
        if chamfer_height <= 0:
            return b + 2 * h
        if h >= chamfer_height:
            return (b + 2 * h) - 2 * (chamfer_length + chamfer_height) + 2 * chamfer_hypotenuse
        else:
            return (b - 2 * chamfer_length) + 2 * (h / chamfer_height) * chamfer_hypotenuse

    def _rect_chamfer_surface_width(self, b: float, h: float, chamfer_angle_deg: float, chamfer_length: float) -> float:
        """带倒角矩形断面水面宽度
        - h >= chamfer_height: 水面在矩形区，宽度 = b
        - h < chamfer_height:  水面在倒角区，宽度 = b - 2*cl*(1 - h/ch)
        """
        if chamfer_angle_deg <= 0 or chamfer_length <= 0:
            return b
        chamfer_height = chamfer_length * math.tan(math.radians(chamfer_angle_deg))
        if chamfer_height <= 0 or h >= chamfer_height:
            return b
        return b - 2 * chamfer_length * (1 - h / chamfer_height)

    def get_cross_section_area(self, node: ChannelNode) -> float:
        """
        计算过水断面面积
        
        根据断面形式和参数计算，覆盖所有断面类型：
        - 矩形类：明渠-矩形、渡槽-矩形、矩形暗涵、隧洞-圆拱直墙型
        - 梯形：明渠-梯形
        - 圆形类：明渠-圆形、隧洞-圆形、倒虹吸
        - U形渡槽：半圆底 + 矩形上部
        - 马蹄形隧洞：标准Ⅰ/Ⅱ型真实公式
        
        注意：使用 .value 字符串比较而非 enum 对象比较，
        避免双路径导入(models.enums vs 推求水面线.models.enums)导致的类不匹配。
        
        Args:
            node: 渠道节点
            
        Returns:
            过水断面面积（m²）
        """
        params = node.section_params
        structure_type = node.structure_type
        
        if not structure_type:
            return 0.0
        
        sv = structure_type.value  # 使用字符串比较避免双路径导入问题
        
        h = params.get('水深', params.get('h', node.water_depth))
        if h <= 0:
            return 0.0
        
        # 矩形类：明渠-矩形、渡槽-矩形、矩形暗涵
        if sv in ("明渠-矩形", "渡槽-矩形", "矩形暗涵"):
            b = self._get_bottom_width(params)
            if sv == "渡槽-矩形":
                ca = params.get('chamfer_angle', 0) or 0
                cl = params.get('chamfer_length', 0) or 0
                if ca > 0 and cl > 0:
                    return self._rect_chamfer_area(b, h, ca, cl)
            return b * h

        # 隧洞-圆拱直墙型：使用真实圆弧公式（需 H_total 和 theta_deg 参数）
        elif sv == "隧洞-圆拱直墙型":
            b = self._get_bottom_width(params)
            H_total = params.get('H_total', 0) or 0
            theta_deg = params.get('theta_deg', 0) or 0
            if b > 0 and H_total > 0 and theta_deg > 0:
                return self._arch_tunnel_area(b, H_total, math.radians(theta_deg), h)
            return b * h  # 退化为矩形近似（参数不足时）

        # 梯形：明渠-梯形
        elif sv == "明渠-梯形":
            b = self._get_bottom_width(params)
            m = params.get('边坡', params.get('m', 0))
            return (b + m * h) * h
        
        # 圆形类：明渠-圆形、隧洞-圆形、倒虹吸
        elif sv in ("明渠-圆形", "隧洞-圆形", "倒虹吸"):
            D = self._get_diameter(params)
            if D > 0:
                return self._circular_area(D, h)
            return params.get('A', params.get('面积', 0))
        
        # U形渡槽：半圆底（半径R）+ 矩形上部（宽2R）
        elif sv == "渡槽-U形":
            R = self._get_radius(params)
            if R > 0:
                if h <= R:
                    return self._circular_area(2 * R, h)
                else:
                    A_semi = math.pi * R * R / 2
                    A_rect = 2 * R * (h - R)
                    return A_semi + A_rect
            return params.get('A', params.get('面积', 0))
        
        # 马蹄形隧洞：使用真实马蹄形公式
        elif "马蹄形" in sv:
            R = self._get_radius(params)
            if R > 0:
                stype = self._horseshoe_section_type(sv)
                return self._horseshoe_std_area(stype, R, h)
            return params.get('A', params.get('面积', 0))
        
        # 明渠-U形：圆弧底+斜直线壁
        elif sv == "明渠-U形":
            R_u = self._get_radius(params)
            theta_u = params.get('theta_deg', 0) or 0
            m_u = params.get('m', params.get('边坡', 0)) or 0
            if R_u > 0 and theta_u > 0:
                theta_rad_u = math.radians(theta_u)
                h0_u = R_u * (1.0 - math.cos(theta_rad_u / 2.0))
                if h <= h0_u:
                    cos_arg = max(-1.0, min(1.0, (R_u - h) / R_u))
                    acos_val = math.acos(cos_arg)
                    return R_u * R_u * acos_val - (R_u - h) * math.sqrt(max(0.0, R_u * R_u - (R_u - h) ** 2))
                else:
                    h_s = h - h0_u
                    b_arc_u = 2.0 * R_u * math.sin(theta_rad_u / 2.0)
                    A_arc = R_u * R_u * (theta_rad_u / 2.0 - math.sin(theta_rad_u / 2.0) * math.cos(theta_rad_u / 2.0))
                    return A_arc + (b_arc_u + m_u * h_s) * h_s
            return params.get('A', params.get('面积', 0))
        
        else:
            return params.get('A', params.get('面积', 0))
    
    def get_wetted_perimeter(self, node: ChannelNode) -> float:
        """
        计算湿周
        
        根据断面形式和参数计算，覆盖所有断面类型。
        使用 .value 字符串比较避免双路径导入问题。
        
        Args:
            node: 渠道节点
            
        Returns:
            湿周（m）
        """
        params = node.section_params
        structure_type = node.structure_type
        
        if not structure_type:
            return 0.0
        
        sv = structure_type.value
        
        h = params.get('水深', params.get('h', node.water_depth))
        if h <= 0:
            return 0.0
        
        # 矩形类：明渠-矩形、渡槽-矩形、矩形暗涵
        if sv in ("明渠-矩形", "渡槽-矩形", "矩形暗涵"):
            b = self._get_bottom_width(params)
            if sv == "渡槽-矩形":
                ca = params.get('chamfer_angle', 0) or 0
                cl = params.get('chamfer_length', 0) or 0
                if ca > 0 and cl > 0:
                    return self._rect_chamfer_perimeter(b, h, ca, cl)
            return b + 2 * h

        # 隧洞-圆拱直墙型：使用真实圆弧公式
        elif sv == "隧洞-圆拱直墙型":
            b = self._get_bottom_width(params)
            H_total = params.get('H_total', 0) or 0
            theta_deg = params.get('theta_deg', 0) or 0
            if b > 0 and H_total > 0 and theta_deg > 0:
                return self._arch_tunnel_perimeter(b, H_total, math.radians(theta_deg), h)
            return b + 2 * h  # 退化为矩形近似（参数不足时）

        # 明渠-U形：圆弧底+斜直线壁
        elif sv == "明渠-U形":
            R_u = self._get_radius(params)
            theta_u = params.get('theta_deg', 0) or 0
            m_u = params.get('m', params.get('边坡', 0)) or 0
            if R_u > 0 and theta_u > 0:
                theta_rad_u = math.radians(theta_u)
                h0_u = R_u * (1.0 - math.cos(theta_rad_u / 2.0))
                if h <= h0_u:
                    cos_arg = max(-1.0, min(1.0, (R_u - h) / R_u))
                    acos_val = math.acos(cos_arg)
                    return 2.0 * R_u * acos_val
                else:
                    h_s = h - h0_u
                    chi_arc = theta_rad_u * R_u
                    return chi_arc + 2.0 * h_s * math.sqrt(1.0 + m_u * m_u)
            return params.get('X', params.get('湿周', params.get('P', 0)))

        # 梯形：明渠-梯形
        elif sv == "明渠-梯形":
            b = self._get_bottom_width(params)
            m = params.get('边坡', params.get('m', 0))
            return b + 2 * h * math.sqrt(1 + m * m)
        
        # 圆形类：明渠-圆形、隧洞-圆形、倒虹吸
        elif sv in ("明渠-圆形", "隧洞-圆形", "倒虹吸"):
            D = self._get_diameter(params)
            if D > 0:
                return self._circular_perimeter(D, h)
            return params.get('X', params.get('湿周', params.get('P', 0)))
        
        # U形渡槽：半圆底（半径R）+ 矩形侧壁
        elif sv == "渡槽-U形":
            R = self._get_radius(params)
            if R > 0:
                if h <= R:
                    return self._circular_perimeter(2 * R, h)
                else:
                    P_semi = math.pi * R  # 半圆弧长
                    P_rect = 2 * (h - R)  # 两侧矩形壁
                    return P_semi + P_rect
            return params.get('X', params.get('湿周', params.get('P', 0)))
        
        # 马蹄形隧洞：使用真实马蹄形公式
        elif "马蹄形" in sv:
            R = self._get_radius(params)
            if R > 0:
                stype = self._horseshoe_section_type(sv)
                return self._horseshoe_std_perimeter(stype, R, h)
            return params.get('X', params.get('湿周', params.get('P', 0)))
        
        else:
            return params.get('X', params.get('湿周', params.get('P', 0)))
    
    def calculate_hydraulic_radius(self, node: ChannelNode) -> float:
        """
        计算水力半径
        
        R = A / χ
        
        Args:
            node: 渠道节点
            
        Returns:
            水力半径（m）
        """
        A = self.get_cross_section_area(node)
        P = self.get_wetted_perimeter(node)
        
        if P <= ZERO_TOLERANCE:
            return 0.0
        
        return A / P
    
    def calculate_velocity(self, node: ChannelNode, flow: Optional[float] = None) -> float:
        """
        计算流速
        
        v = Q / A
        
        Args:
            node: 渠道节点
            flow: 流量（m³/s），默认使用设计流量
            
        Returns:
            流速（m/s）
        """
        if flow is None:
            flow = self.design_flow
        
        A = self.get_cross_section_area(node)
        
        if A <= ZERO_TOLERANCE:
            return 0.0
        
        v = flow / A
        return round(v, VELOCITY_PRECISION)
    
    def solve_circular_normal_depth(self, Q: float, D: float, n: float, slope_i: float) -> float:
        """
        求解圆形断面正常水深（二分法）
        
        基于曼宁公式：Q = (1/n) × A × R^(2/3) × √i
        其中 A、R 由 D 和 h 的圆形断面公式计算。
        
        Args:
            Q: 设计流量（m³/s）
            D: 直径（m）
            n: 糙率
            slope_i: 底坡 i
            
        Returns:
            正常水深 h（m），失败返回 0.0
        """
        if Q <= 0 or D <= 0 or n <= 0 or slope_i <= 0:
            return 0.0
        
        h_low = 0.001
        h_high = D * 0.95  # 不超过 95% 直径（避免满流奇点）
        r = D / 2
        
        for _ in range(200):
            h = (h_low + h_high) / 2
            cos_arg = max(-1.0, min(1.0, (r - h) / r))
            theta = 2 * math.acos(cos_arg)
            A = r * r * (theta - math.sin(theta)) / 2
            P = r * theta
            if P <= 1e-10:
                h_low = h
                continue
            R_hyd = A / P
            if R_hyd <= 1e-10:
                h_low = h
                continue
            Q_calc = (1.0 / n) * A * (R_hyd ** (2.0 / 3.0)) * math.sqrt(slope_i)
            
            if abs(Q_calc - Q) / max(Q, 1e-10) < 1e-6:
                return round(h, 3)
            if Q_calc < Q:
                h_low = h
            else:
                h_high = h
        
        # 返回最后的近似值
        return round((h_low + h_high) / 2, 3)
    
    def ensure_circular_water_depth(self, node: ChannelNode) -> None:
        """
        确保圆形明渠节点的水深和水力参数已计算
        
        如果水深为 0 且有足够的输入参数（D、n、slope、Q），
        则自动求解正常水深并填充 section_params。
        
        Args:
            node: 渠道节点（原地修改）
        """
        sv = node.structure_type.value if node.structure_type else ""
        if sv != "明渠-圆形":
            return
        
        params = node.section_params
        D = params.get('D', params.get('直径', 0))
        if D <= 0:
            return
        
        h = params.get('水深', params.get('h', node.water_depth))
        if h > 0:
            # 水深已有，确保 section_params 中的 A/X/R 已填充
            self._fill_circular_section_params(node, D, h)
            return
        
        # 水深为 0，尝试求解
        Q = node.flow if node.flow > 0 else self.design_flow
        n = node.roughness if node.roughness > 0 else self.roughness
        slope_i = node.slope_i
        
        if Q <= 0 or n <= 0 or slope_i <= 0:
            return
        
        h = self.solve_circular_normal_depth(Q, D, n, slope_i)
        if h > 0:
            node.water_depth = h
            self._fill_circular_section_params(node, D, h)
    
    def _fill_circular_section_params(self, node: ChannelNode, D: float, h: float) -> None:
        """
        根据直径和水深，填充圆形断面的 A、X(湿周)、R(水力半径) 到 section_params
        
        Args:
            node: 渠道节点
            D: 直径
            h: 水深
        """
        r = D / 2
        if h >= D:
            A = math.pi * r * r
            P = math.pi * D
        elif h > 0:
            cos_arg = max(-1.0, min(1.0, (r - h) / r))
            theta = 2 * math.acos(cos_arg)
            A = r * r * (theta - math.sin(theta)) / 2
            P = r * theta
        else:
            return
        
        R_hyd = A / P if P > 0 else 0
        
        node.section_params['A'] = round(A, 3)
        node.section_params['X'] = round(P, 3)
        node.section_params['R'] = round(R_hyd, 3)
        
        # 同时计算流速
        Q = node.flow if node.flow > 0 else self.design_flow
        if Q > 0 and A > 0:
            node.velocity = round(Q / A, VELOCITY_PRECISION)
    
    def fill_section_params(self, node: ChannelNode) -> None:
        """
        通用方法：计算并填充所有断面类型的 A（过水断面面积）、X（湿周）、R（水力半径）到 section_params
        
        对圆形明渠可自动求解水深（ensure_circular_water_depth），
        其余类型从几何参数直接计算。
        
        Args:
            node: 渠道节点（原地修改）
        """
        if node.is_transition:
            return
        if not node.structure_type:
            return
        
        sv = node.structure_type.value if node.structure_type else ""
        
        # 圆形明渠：可自动求解水深（如果水深为0但有D/n/slope/Q）
        if sv == "明渠-圆形":
            self.ensure_circular_water_depth(node)
            return
        
        # 圆形隧洞/倒虹吸：使用 D 直接计算（不需要求解水深）
        if sv in ("隧洞-圆形", "倒虹吸"):
            D = self._get_diameter(node.section_params)
            h = node.water_depth
            if D > 0 and h > 0:
                self._fill_circular_section_params(node, D, h)
            return
        
        h = node.water_depth
        if h <= 0:
            return
        
        A = self.get_cross_section_area(node)
        P = self.get_wetted_perimeter(node)
        R_hyd = A / P if P > ZERO_TOLERANCE else 0.0
        
        if A > 0:
            node.section_params['A'] = round(A, 3)
        if P > 0:
            node.section_params['X'] = round(P, 3)
        if R_hyd > 0:
            node.section_params['R'] = round(R_hyd, 3)
        
        # 同时计算流速（如果尚未设置）
        if node.velocity <= 0:
            Q = node.flow if node.flow > 0 else self.design_flow
            if Q > 0 and A > 0:
                node.velocity = round(Q / A, VELOCITY_PRECISION)
    
    def calculate_friction_slope(self, node: ChannelNode) -> float:
        """
        计算水力坡降（曼宁公式反算）
        
        J = (v × n / R^(2/3))²
        
        Args:
            node: 渠道节点
            
        Returns:
            水力坡降
        """
        # TODO: 根据实际需求完善计算
        v = node.velocity
        R = self.calculate_hydraulic_radius(node)
        n = self.roughness
        
        if R <= ZERO_TOLERANCE or v <= 0:
            return 0.0
        
        # 曼宁公式反算坡降
        J = (v * n / (R ** (2.0 / 3.0))) ** 2
        
        return J
    
    def calculate_friction_loss(self, node1: ChannelNode, node2: ChannelNode, 
                                transition_length: float = 0.0) -> float:
        """
        计算沿程水头损失
        
        hf = slope_i × 有效长度
        
        有效长度 = (node2.station_MC - node1.station_MC) 
                 - 渐变段长度（若两行之间有渐变段）
                 - node1.arc_length / 2 
                 - node2.arc_length / 2
        
        Args:
            node1: 起点
            node2: 终点
            transition_length: 两节点间的渐变段总长度（默认0）
            
        Returns:
            沿程水头损失（m）
        """
        # 计算里程MC差
        L_mc = node2.station_MC - node1.station_MC
        
        # 扣除渐变段长度
        L_mc -= transition_length
        
        # 扣除弧长的一半
        arc1 = node1.arc_length if node1.arc_length else 0.0
        arc2 = node2.arc_length if node2.arc_length else 0.0
        L_mc -= (arc1 / 2.0)
        L_mc -= (arc2 / 2.0)
        
        # 防止负值
        effective_length = max(0.0, L_mc)
        
        if effective_length <= 0:
            return 0.0
        
        # 优先使用node2的底坡（下游点），如果没有则使用node1的
        slope_i = node2.slope_i if node2.slope_i and node2.slope_i > 0 else node1.slope_i
        
        if slope_i and slope_i > 0:
            # 使用底坡计算: hf = slope_i × 有效长度
            hf = slope_i * effective_length
            
            # 保存计算详情到下游节点（与损失值保存位置一致）
            node2.friction_calc_details = {
                'method': 'slope',
                'slope_i': slope_i,
                'L_effective': effective_length,
                'hf': round(hf, HEAD_LOSS_PRECISION)
            }
            
            return round(hf, HEAD_LOSS_PRECISION)
        else:
            # 底坡缺失时，回退到曼宁公式
            return self._calculate_friction_loss_manning(node1, node2, effective_length)
    
    def _calculate_friction_loss_manning(self, node1: ChannelNode, node2: ChannelNode, 
                                         length: float) -> float:
        """
        备用方法：使用曼宁公式计算沿程损失（当底坡数据缺失时）
        
        hf = J_avg × L
        
        Args:
            node1: 起点
            node2: 终点
            length: 计算长度
            
        Returns:
            沿程水头损失（m）
        """
        J1 = self.calculate_friction_slope(node1)
        J2 = self.calculate_friction_slope(node2)
        J_avg = (J1 + J2) / 2 if J2 > 0 else J1
        
        hf = J_avg * length
        
        # 保存计算详情到下游节点（与损失值保存位置一致）
        n = node1.roughness if node1.roughness > 0 else self.roughness
        v1 = node1.velocity if node1.velocity > 0 else 0
        v2 = node2.velocity if node2.velocity > 0 else 0
        R1 = node1.section_params.get('R', node1.section_params.get('水力半径', 0))
        R2 = node2.section_params.get('R', node2.section_params.get('水力半径', 0))
        
        node2.friction_calc_details = {
            'method': 'manning',
            'n': n,
            'v1': v1,
            'v2': v2,
            'R1': R1,
            'R2': R2,
            'J1': J1,
            'J2': J2,
            'J_avg': J_avg,
            'L': length,
            'hf': round(hf, HEAD_LOSS_PRECISION)
        }
        
        return round(hf, HEAD_LOSS_PRECISION)
    
    def calculate_local_loss(self, node: ChannelNode) -> float:
        """
        计算局部水头损失
        
        hj = ζ × v²/(2g)
        
        Args:
            node: 渠道节点
            
        Returns:
            局部水头损失（m）
        """
        # TODO: 根据实际需求完善计算
        
        # 分水闸/分水口：局部损失为0（过闸损失在head_loss_gate中单独计算）
        if getattr(node, 'is_diversion_gate', False):
            return 0.0
        
        # 倒虹吸：使用外部导入的水头损失
        sv = node.structure_type.value if node.structure_type else ""
        if sv == "倒虹吸":
            if node.name in self.inverted_siphon_losses:
                return self.inverted_siphon_losses[node.name]
            if node.external_head_loss is not None:
                return node.external_head_loss
            return 0.0
        
        # 其他建筑物：根据进出口标识和类型查找系数
        structure_name = node.structure_type.value if node.structure_type else ""
        
        if structure_name in LOCAL_LOSS_COEFFICIENTS:
            coeffs = LOCAL_LOSS_COEFFICIENTS[structure_name]
        else:
            coeffs = None
        
        if coeffs is not None:
            io_val = node.in_out.value if node.in_out else ""
            if io_val == "进":
                zeta = coeffs.get("进口", 0.0)
            elif io_val == "出":
                zeta = coeffs.get("出口", 0.0)
            else:
                zeta = 0.0
            
            v = node.velocity
            hj = zeta * v * v / (2 * GRAVITY)
            return round(hj, HEAD_LOSS_PRECISION)
        
        return 0.0
    
    def calculate_bend_loss(self, node: ChannelNode) -> float:
        """
        计算弯道水头损失
        
        公式：h_w = (n² × L × v²) / R^(4/3) × (3/4) × √(B / R_c)
        
        物理逻辑：弯道总损失 = 基础沿程损失 × 弯道影响修正系数
        
        其中：
        - 基本沿程阻力部分：n²·L·v² / R^(4/3) 基于曼宁公式
        - 弯道修正系数部分：(3/4)·√(B/R_c) 反映水面宽度与弯道半径之比对能量损失的影响
        
        Args:
            node: 渠道节点（包含弯道长度、流速、水力半径、转弯半径等参数）
            
        Returns:
            弯道水头损失（m）
        """
        # 获取弯道长度（使用弧长）
        L = node.arc_length
        if L <= ZERO_TOLERANCE:
            return 0.0
        
        # 获取糙率
        n = node.roughness if node.roughness > 0 else self.roughness
        if n <= ZERO_TOLERANCE:
            return 0.0
        
        # 获取流速
        v = node.velocity
        if v <= ZERO_TOLERANCE:
            return 0.0
        
        # 获取水力半径
        R = node.section_params.get('R', node.section_params.get('水力半径', 0))
        if R <= ZERO_TOLERANCE:
            return 0.0
        
        # 获取转弯半径（弯道半径）
        Rc = node.turn_radius
        if Rc <= ZERO_TOLERANCE:
            Rc = self.settings.turn_radius
        if Rc <= ZERO_TOLERANCE:
            return 0.0
        
        # 计算水面宽度 B = b + 2mh
        h = node.water_depth
        
        # 对于圆形断面，水面宽度需要单独计算
        D = node.section_params.get('D', node.section_params.get('直径', 0))
        if D > 0 and h > 0:
            # 圆形断面水面宽度: B = 2 × √(D×h - h²)，当 h < D/2 时
            if h <= D:
                r = D / 2
                if h <= r:
                    B = 2 * math.sqrt(r * r - (r - h) ** 2)
                else:
                    B = 2 * math.sqrt(r * r - (h - r) ** 2)
            else:
                B = D  # 满流时水面宽度为直径
        else:
            # 检查是否只有半径参数（马蹄形隧洞、U形渡槽等）
            R_circle = node.section_params.get('R_circle', node.section_params.get('半径', node.section_params.get('内半径', node.section_params.get('r', 0))))
            sv_bend = node.structure_type.value if node.structure_type else ""
            if R_circle > ZERO_TOLERANCE:
                if "马蹄形" in sv_bend:
                    stype = self._horseshoe_section_type(sv_bend)
                    B = self._horseshoe_std_surface_width(stype, R_circle, h)
                elif "渡槽-U形" in sv_bend:
                    if h <= R_circle:
                        B = 2 * math.sqrt(max(0.0, R_circle * R_circle - (R_circle - h) ** 2))
                    else:
                        B = 2 * R_circle
                elif "明渠-U形" in sv_bend:
                    theta_u_b = node.section_params.get('theta_deg', 0) or 0
                    m_u_b = node.section_params.get('m', node.section_params.get('边坡', 0))
                    if theta_u_b > 0 and R_circle > 0:
                        h0_u_b = R_circle * (1.0 - math.cos(math.radians(theta_u_b / 2.0)))
                        if h <= h0_u_b:
                            B = 2 * math.sqrt(max(0.0, R_circle ** 2 - (R_circle - h) ** 2))
                        else:
                            b_arc_u_b = 2 * R_circle * math.sin(math.radians(theta_u_b / 2.0))
                            B = b_arc_u_b + 2 * m_u_b * (h - h0_u_b)
                    else:
                        B = 2 * math.sqrt(max(0.0, R_circle ** 2 - (R_circle - min(h, R_circle)) ** 2)) \
                            if h <= R_circle else 2 * R_circle
                else:
                    b = 2 * R_circle
                    m = node.section_params.get('m', node.section_params.get('边坡系数', node.section_params.get('边坡', 0)))
                    B = b + 2 * m * h
            else:
                b = node.section_params.get('B', node.section_params.get('底宽', node.section_params.get('b', 0)))
                if "圆拱直墙" in sv_bend and b > 0:
                    H_total = node.section_params.get('H_total', 0) or 0
                    theta_deg = node.section_params.get('theta_deg', 0) or 0
                    if H_total > 0 and theta_deg > 0:
                        B = self._arch_tunnel_surface_width(b, H_total, math.radians(theta_deg), h)
                    else:
                        B = b
                elif sv_bend == "渡槽-矩形" and b > 0:
                    ca = node.section_params.get('chamfer_angle', 0) or 0
                    cl = node.section_params.get('chamfer_length', 0) or 0
                    if ca > 0 and cl > 0:
                        B = self._rect_chamfer_surface_width(b, h, ca, cl)
                    else:
                        B = b
                else:
                    m = node.section_params.get('m', node.section_params.get('边坡系数', node.section_params.get('边坡', 0)))
                    B = b + 2 * m * h

            # 兜底：当底宽缺失导致B为0时，尝试从过水断面面积A反算
            # 公式推导：A = (b+mh)*h → b+mh = A/h → B = b+2mh = A/h + mh
            if B <= ZERO_TOLERANCE:
                m = node.section_params.get('m', node.section_params.get('边坡系数', node.section_params.get('边坡', 0)))
                A = node.section_params.get('A', node.section_params.get('面积', 0))
                if A > ZERO_TOLERANCE and h > ZERO_TOLERANCE:
                    B = A / h + m * h

        if B <= ZERO_TOLERANCE:
            return 0.0

        # 计算弯道水头损失
        # h_w = (n² × L × v²) / R^(4/3) × (3/4) × √(B / R_c)
        hw = (n ** 2 * L * v ** 2) / (R ** (4.0 / 3.0)) * 0.75 * math.sqrt(B / Rc)

        # 保存计算详情（用于双击展示）
        node.bend_calc_details = {
            'n': n,
            'L': L,
            'v': v,
            'R': R,
            'Rc': Rc,
            'B': B,
            'hw': round(hw, HEAD_LOSS_PRECISION)
        }

        return round(hw, HEAD_LOSS_PRECISION)
    
    def calculate_water_profile(self, nodes: List[ChannelNode], 
                                method: str = "backward") -> None:
        """
        推求水面线
        
        Args:
            nodes: 节点列表（原地修改）
            method: 推算方法
                - "backward": 逆推法（从下游向上游）
                - "forward": 顺推法（从上游向下游）
        """
        # TODO: 根据实际需求完善水面线推求逻辑
        
        if not nodes:
            return
        
        if method == "forward":
            self._calculate_forward(nodes)
        else:
            self._calculate_backward(nodes)
    
    def _calculate_forward(self, nodes: List[ChannelNode]) -> None:
        """
        顺推法：从上游向下游计算
        
        Z_下 = Z_上 - hf - hj - hw - h_transition
        
        渐变段行处理规则（方案B）：
        - 渐变段行不显示水位和渠底高程
        - 渐变段损失计入下游节点的水位计算
        """
        # 设置起点水位（第一个非渐变段节点）
        first_regular_node = None
        first_regular_node_idx = 0
        for idx, node in enumerate(nodes):
            if not node.is_transition:
                first_regular_node = node
                first_regular_node_idx = idx
                break
        
        # ===== 预处理：确保所有断面的水深和水力参数(A/X/R)已计算 =====
        for node in nodes:
            if not node.is_transition:
                self.fill_section_params(node)
        
        # ===== 预处理：确保所有节点的结构高度已设置（用于计算渠顶高程） =====
        for node in nodes:
            if not node.is_transition and node.structure_height <= 0:
                self._estimate_structure_height(node)
        
        # ===== 兜底：自动插入的明渠段如果仍缺少结构高度，从最近的同类明渠节点继承 =====
        for idx, node in enumerate(nodes):
            if not node.is_transition and getattr(node, 'is_auto_inserted_channel', False) and node.structure_height <= 0:
                st_val = node.structure_type.value if node.structure_type else ""
                # 向上搜索最近的同类明渠节点
                for j in range(idx - 1, -1, -1):
                    prev = nodes[j]
                    if prev.is_transition or getattr(prev, 'is_auto_inserted_channel', False):
                        continue
                    prev_st = prev.structure_type.value if prev.structure_type else ""
                    if "明渠" in prev_st and prev.structure_height > 0:
                        node.structure_height = prev.structure_height
                        break
                # 如果向上没找到，向下搜索
                if node.structure_height <= 0:
                    for j in range(idx + 1, len(nodes)):
                        nxt = nodes[j]
                        if nxt.is_transition or getattr(nxt, 'is_auto_inserted_channel', False):
                            continue
                        nxt_st = nxt.structure_type.value if nxt.structure_type else ""
                        if "明渠" in nxt_st and nxt.structure_height > 0:
                            node.structure_height = nxt.structure_height
                            break
        
        if first_regular_node:
            first_regular_node.water_level = self.settings.start_water_level
            if first_regular_node.water_depth > 0:
                first_regular_node.bottom_elevation = first_regular_node.water_level - first_regular_node.water_depth
                if first_regular_node.structure_height > 0:
                    first_regular_node.top_elevation = first_regular_node.bottom_elevation + first_regular_node.structure_height
            # 计算第一个节点的流速和弯道损失
            if first_regular_node.velocity <= 0:
                first_regular_node.velocity = self.calculate_velocity(first_regular_node)
            if first_regular_node.arc_length > ZERO_TOLERANCE:
                first_regular_node.head_loss_bend = self.calculate_bend_loss(first_regular_node)
        
        # 遍历计算水位
        prev_regular_node = first_regular_node
        prev_regular_node_idx = first_regular_node_idx
        
        for i in range(len(nodes)):
            curr_node = nodes[i]
            
            # 跳过第一个节点（已设置水位）和渐变段
            if curr_node == first_regular_node:
                continue
            if curr_node.is_transition:
                continue
            
            # ===== 闸类型特殊处理（分水闸/分水口/泄水闸/节制闸等） =====
            # 闸是点状结构，仅产生过闸水头损失，不计算沿程/弯道/局部损失
            if getattr(curr_node, 'is_diversion_gate', False):
                head_loss_gate = getattr(curr_node, 'head_loss_gate', 0.0) or 0.0
                
                # 水位 = 前一节点水位 - 过闸水头损失
                curr_node.water_level = prev_regular_node.water_level - head_loss_gate
                
                # 各项损失清零（仅过闸损失有效）
                curr_node.head_loss_friction = 0.0
                curr_node.head_loss_bend = 0.0
                curr_node.head_loss_local = 0.0
                curr_node.head_loss_total = head_loss_gate
                
                # 更新状态
                prev_regular_node = curr_node
                prev_regular_node_idx = i
                continue
            
            # ===== 常规节点处理 =====
            # 计算当前节点的流速（如果未设置）
            if curr_node.velocity <= 0:
                curr_node.velocity = self.calculate_velocity(curr_node)
            
            # 计算当前节点的弯道损失（如果有弧长且未计算）
            if curr_node.arc_length > ZERO_TOLERANCE and curr_node.head_loss_bend == 0:
                curr_node.head_loss_bend = self.calculate_bend_loss(curr_node)
            hw = curr_node.head_loss_bend or 0.0
            
            # 查找前一个非渐变段节点到当前节点之间的渐变段损失
            accumulated_transition_loss = 0.0
            transition_len_between = 0.0
            for j in range(prev_regular_node_idx + 1, i):
                if nodes[j].is_transition:
                    transition_loss = self._estimate_transition_loss(prev_regular_node, curr_node)
                    accumulated_transition_loss += transition_loss
                    if nodes[j].transition_length:
                        transition_len_between += nodes[j].transition_length
            
            # 计算沿程损失
            hf = self.calculate_friction_loss(prev_regular_node, curr_node, transition_len_between)
            curr_node.head_loss_friction = hf
            
            # 计算局部损失
            hj = self.calculate_local_loss(curr_node)
            curr_node.head_loss_local = hj
            
            # 计算当前节点水位
            curr_node.water_level = prev_regular_node.water_level - hf - hj - hw - accumulated_transition_loss
            
            # 获取预留、过闸、倒虹吸损失
            head_loss_reserve = getattr(curr_node, 'head_loss_reserve', 0.0) or 0.0
            head_loss_gate = getattr(curr_node, 'head_loss_gate', 0.0) or 0.0
            head_loss_siphon = getattr(curr_node, 'head_loss_siphon', 0.0) or 0.0
            
            # 计算总水头损失（不含渐变段损失）
            # 注：总损失包含局部水头损失（hj），以便与水位递推/累计损失一致
            curr_node.head_loss_total = hw + hf + hj + head_loss_reserve + head_loss_gate + head_loss_siphon
            
            # 计算渠底高程
            if curr_node.water_depth > 0:
                curr_node.bottom_elevation = curr_node.water_level - curr_node.water_depth
                # 计算渠顶高程 = 渠底高程 + 结构高度
                if curr_node.structure_height > 0:
                    curr_node.top_elevation = curr_node.bottom_elevation + curr_node.structure_height
            
            # 更新状态
            prev_regular_node = curr_node
            prev_regular_node_idx = i

    def recalculate_water_levels_with_transition_losses(self, nodes: List[ChannelNode]) -> None:
        """
        使用已计算的渐变段损失重新递推水位

        目的：
        - 渐变段损失在计算完成后才有精确值
        - 通过二次递推确保水位与累计损失一致

        Args:
            nodes: 节点列表（包含渐变段行）
        """
        if not nodes:
            return

        # 找到第一个非渐变段节点，作为起点
        first_regular_node = None
        first_regular_idx = 0
        for idx, node in enumerate(nodes):
            if not node.is_transition:
                first_regular_node = node
                first_regular_idx = idx
                break

        if not first_regular_node:
            return

        # 起点水位
        first_regular_node.water_level = self.settings.start_water_level
        if first_regular_node.water_depth > 0:
            first_regular_node.bottom_elevation = first_regular_node.water_level - first_regular_node.water_depth
            if first_regular_node.structure_height > 0:
                first_regular_node.top_elevation = first_regular_node.bottom_elevation + first_regular_node.structure_height

        prev_regular_node = first_regular_node
        prev_regular_idx = first_regular_idx

        for i in range(first_regular_idx + 1, len(nodes)):
            curr_node = nodes[i]

            # 跳过渐变段行
            if curr_node.is_transition:
                continue

            # 分水闸/分水口：仅考虑过闸损失
            if getattr(curr_node, 'is_diversion_gate', False):
                head_loss_gate = getattr(curr_node, 'head_loss_gate', 0.0) or 0.0
                curr_node.water_level = prev_regular_node.water_level - head_loss_gate
                if curr_node.water_depth > 0:
                    curr_node.bottom_elevation = curr_node.water_level - curr_node.water_depth
                    if curr_node.structure_height > 0:
                        curr_node.top_elevation = curr_node.bottom_elevation + curr_node.structure_height
                prev_regular_node = curr_node
                prev_regular_idx = i
                continue

            # 累加上一个常规节点到当前节点之间的渐变段损失
            transition_loss = 0.0
            for j in range(prev_regular_idx + 1, i):
                if nodes[j].is_transition:
                    loss = nodes[j].head_loss_transition or 0.0
                    if loss <= 0 and nodes[j].transition_calc_details:
                        loss = nodes[j].transition_calc_details.get('total', 0.0) or 0.0
                    transition_loss += loss

            # 读取各项损失（已在前序计算中得到）
            hf = curr_node.head_loss_friction or 0.0
            hj = curr_node.head_loss_local or 0.0
            hw = curr_node.head_loss_bend or 0.0
            h_reserve = getattr(curr_node, 'head_loss_reserve', 0.0) or 0.0
            h_gate = getattr(curr_node, 'head_loss_gate', 0.0) or 0.0
            h_siphon = getattr(curr_node, 'head_loss_siphon', 0.0) or 0.0

            total_drop = hf + hj + hw + h_reserve + h_gate + h_siphon + transition_loss
            curr_node.water_level = prev_regular_node.water_level - total_drop

            if curr_node.water_depth > 0:
                curr_node.bottom_elevation = curr_node.water_level - curr_node.water_depth
                if curr_node.structure_height > 0:
                    curr_node.top_elevation = curr_node.bottom_elevation + curr_node.structure_height

            prev_regular_node = curr_node
            prev_regular_idx = i
    
    def apply_siphon_outlet_elevation(self, nodes: List[ChannelNode]) -> None:
        """
        应用公式10.3.6计算倒虹吸出口渐变段末端（下游渠道起始）的底面高程
        
        公式：H_d = H_u + h_u - h_d - ΔZ
        
        式中：
            H_d —— 下游渠道起始断面底部高程（m）
            H_u —— 上游渠道末端断面底部高程（m）
            h_u —— 上游渠道设计水深（m）
            h_d —— 下游渠道设计水深（m）
            ΔZ  —— 上、下游水面总落差值（m），包括倒虹吸水损和渐变段损失
        
        用于验算/修正倒虹吸出口下游第一个渠道节点的渠底高程。
        
        Args:
            nodes: 完整节点列表（含渐变段行）
        """
        for i, node in enumerate(nodes):
            # 查找倒虹吸出口节点
            sv_node = node.structure_type.value if node.structure_type else ""
            if sv_node != "倒虹吸":
                continue
            io_val = node.in_out.value if node.in_out else ""
            if io_val != "出":
                continue
            
            # 向前查找上游渠道末端节点（倒虹吸进口之前的明渠节点）
            upstream_channel = None
            for j in range(i - 1, -1, -1):
                n = nodes[j]
                if n.is_transition:
                    continue
                # 跳过倒虹吸内部节点
                sv_n = n.structure_type.value if n.structure_type else ""
                if sv_n == "倒虹吸":
                    continue
                # 找到上游明渠/渠道节点
                if n.water_depth > 0 and n.bottom_elevation:
                    upstream_channel = n
                    break
            
            # 向后查找下游渠道起始节点（倒虹吸出口之后的第一个非渐变段节点）
            downstream_channel = None
            for j in range(i + 1, len(nodes)):
                n = nodes[j]
                if n.is_transition:
                    continue
                # 找到下游明渠/渠道节点
                if n.water_depth > 0:
                    downstream_channel = n
                    break
            
            if not upstream_channel or not downstream_channel:
                continue
            
            # 计算参数
            H_u = upstream_channel.bottom_elevation  # 上游渠道末端底部高程
            h_u = upstream_channel.water_depth        # 上游渠道设计水深
            h_d = downstream_channel.water_depth      # 下游渠道设计水深
            
            # ΔZ = 上下游水面总落差 = 上游水位 - 下游水位
            upstream_wl = upstream_channel.water_level if upstream_channel.water_level else (H_u + h_u)
            downstream_wl = downstream_channel.water_level if downstream_channel.water_level else 0.0
            delta_Z = upstream_wl - downstream_wl
            
            # 应用公式10.3.6: H_d = H_u + h_u - h_d - ΔZ
            H_d = H_u + h_u - h_d - delta_Z
            H_d = round(H_d, ELEVATION_PRECISION)
            
            # 保存公式10.3.6计算详情（供双击弹窗展示）
            calc_details = {
                'H_u': H_u,
                'h_u': h_u,
                'h_d': h_d,
                'upstream_wl': upstream_wl,
                'downstream_wl': downstream_wl,
                'delta_Z': delta_Z,
                'H_d': H_d,
                'upstream_name': upstream_channel.name or '',
                'downstream_name': downstream_channel.name or '',
            }
            
            # 将 H_d 赋值给倒虹吸出口节点本身（显示在出口行的渠底高程列）
            node.bottom_elevation = H_d
            node.siphon_outlet_elev_details = calc_details
            
            # 更新下游节点渠底高程（以公式10.3.6为准）
            if downstream_channel.bottom_elevation:
                # 已有渠底高程时，使用公式验算值（两者应一致，取公式值）
                downstream_channel.bottom_elevation = H_d
            else:
                downstream_channel.bottom_elevation = H_d
            # 更新渠顶高程
            if downstream_channel.structure_height > 0:
                downstream_channel.top_elevation = downstream_channel.bottom_elevation + downstream_channel.structure_height
            
            # 【建议4】倒虹吸进口行也显示渠底高程（取上游渠道末端的渠底高程 H_u）
            for j in range(i - 1, -1, -1):
                n = nodes[j]
                if n.is_transition:
                    continue
                sv_n2 = n.structure_type.value if n.structure_type else ""
                io_n = n.in_out.value if n.in_out else ""
                if sv_n2 == "倒虹吸" and io_n == "进":
                    n.bottom_elevation = round(H_u, ELEVATION_PRECISION)
                    break
                # 如果碰到非倒虹吸节点就停止
                if sv_n2 != "倒虹吸":
                    break
    
    def _estimate_transition_loss(self, prev_node: ChannelNode, next_node: ChannelNode) -> float:
        """
        预估渐变段损失（用于水位推求）
        
        Args:
            prev_node: 前一节点
            next_node: 后一节点
            
        Returns:
            渐变段损失估算值（m）
        """
        from config.constants import TRANSITION_ZETA_COEFFICIENTS, TRANSITION_LENGTH_COEFFICIENTS, ZERO_TOLERANCE, GRAVITY, HEAD_LOSS_PRECISION
        
        # 获取流速
        v1 = prev_node.velocity if prev_node.velocity > 0 else 0
        v2 = next_node.velocity if next_node.velocity > 0 else 0
        
        if v1 <= ZERO_TOLERANCE and v2 <= ZERO_TOLERANCE:
            return 0.0
        
        # 根据前后节点结构类型判定渐变段类型（进口/出口相对于特殊建筑物而言）
        sv_next = next_node.structure_type.value if next_node.structure_type else ""
        sv_prev = prev_node.structure_type.value if prev_node.structure_type else ""
        _special_kw = ("隧洞", "渡槽", "倒虹吸", "暗涵")
        if any(kw in sv_next for kw in _special_kw):
            transition_type = "进口"
        else:
            transition_type = "出口"
        if transition_type == "进口":
            transition_form = getattr(self.settings, 'transition_inlet_form', "曲线形反弯扭曲面") or "曲线形反弯扭曲面"
        else:
            transition_form = getattr(self.settings, 'transition_outlet_form', "曲线形反弯扭曲面") or "曲线形反弯扭曲面"
        
        # 获取ζ系数
        if transition_type in TRANSITION_ZETA_COEFFICIENTS:
            zeta_table = TRANSITION_ZETA_COEFFICIENTS[transition_type]
            zeta = zeta_table.get(transition_form, 0.2)
        else:
            zeta = 0.2
        
        # 计算局部水头损失
        h_j1 = zeta * abs(v2 * v2 - v1 * v1) / (2 * GRAVITY)
        
        # 计算水面宽度
        B1 = self.get_water_surface_width(prev_node)
        B2 = self.get_water_surface_width(next_node)
        
        # 计算渐变段长度
        coefficient = TRANSITION_LENGTH_COEFFICIENTS.get(transition_type, 3.5)
        length = coefficient * abs(B1 - B2)
        
        # 计算沿程损失（平均值法）
        R1 = prev_node.section_params.get('R', 0) if prev_node.section_params else 0
        R2 = next_node.section_params.get('R', 0) if next_node.section_params else 0
        R_avg = (R1 + R2) / 2 if (R1 > 0 and R2 > 0) else max(R1, R2)
        v_avg = (v1 + v2) / 2 if (v1 > 0 and v2 > 0) else max(v1, v2)
        
        n = prev_node.roughness if prev_node.roughness > 0 else self.roughness
        
        if R_avg > ZERO_TOLERANCE and v_avg > ZERO_TOLERANCE:
            i = (v_avg * n / (R_avg ** (2.0 / 3.0))) ** 2
            h_f = i * length
        else:
            h_f = 0.0
        
        return round(h_j1 + h_f, HEAD_LOSS_PRECISION)
    
    def _calculate_backward(self, nodes: List[ChannelNode]) -> None:
        """
        逆推法：从下游向上游计算
        
        Z_上 = Z_下 + hf + hj
        """
        # 设置起点水位（此处起点是计算的起始点，即最上游）
        nodes[0].water_level = self.settings.start_water_level
        
        # 实际应用中，逆推法通常是已知下游水位，向上游推算
        # 这里简化为顺推处理，后续根据需求调整
        self._calculate_forward(nodes)
    
    # ========== 渐变段水头损失计算方法 ==========
    
    def get_water_surface_width(self, node: ChannelNode) -> float:
        """
        计算水面宽度B
        
        - 梯形/矩形: B = b + 2mh
        - 圆形: B = 2√(r² - (r-h)²)，当 h <= r 时
        - 马蹄形/U形等只有半径的断面: 底宽 = 2 × 半径
        
        Args:
            node: 渠道节点
            
        Returns:
            水面宽度（m）
        """
        h = node.water_depth
        if h <= ZERO_TOLERANCE:
            h = node.section_params.get('水深', node.section_params.get('h', 0))
        if h <= ZERO_TOLERANCE:
            return 0.0
        
        params = node.section_params
        
        # 检查是否为圆形断面（有直径参数）
        D = params.get('D', params.get('直径', 0))
        if D > 0:
            r = D / 2
            if h <= D:
                if h <= r:
                    B = 2 * math.sqrt(r * r - (r - h) ** 2)
                else:
                    B = 2 * math.sqrt(r * r - (h - r) ** 2)
            else:
                B = D
            return B
        
        sv = node.structure_type.value if node.structure_type else ""

        # 检查是否只有半径参数（马蹄形隧洞、U形渡槽等）
        R_circle = params.get('R_circle', params.get('半径', params.get('内半径', params.get('r', 0))))
        if R_circle > ZERO_TOLERANCE:
            if "马蹄形" in sv:
                stype = self._horseshoe_section_type(sv)
                return self._horseshoe_std_surface_width(stype, R_circle, h)
            elif "渡槽-U形" in sv:
                if h <= R_circle:
                    return 2 * math.sqrt(max(0.0, R_circle * R_circle - (R_circle - h) ** 2))
                else:
                    return 2 * R_circle
            elif "明渠-U形" in sv:
                theta_u_w = params.get('theta_deg', 0) or 0
                m_u_w = params.get('m', params.get('边坡', 0)) or 0
                if theta_u_w > 0 and R_circle > 0:
                    h0_u_w = R_circle * (1.0 - math.cos(math.radians(theta_u_w / 2.0)))
                    if h <= h0_u_w:
                        return 2 * math.sqrt(max(0.0, R_circle ** 2 - (R_circle - h) ** 2))
                    else:
                        b_arc_u_w = 2 * R_circle * math.sin(math.radians(theta_u_w / 2.0))
                        return b_arc_u_w + 2 * m_u_w * (h - h0_u_w)
                return 2 * math.sqrt(max(0.0, R_circle ** 2 - (R_circle - min(h, R_circle)) ** 2)) \
                    if h <= R_circle else 2 * R_circle
            # 其他只有半径参数的断面：底宽 = 2 × 半径
            b = 2 * R_circle
        else:
            b = params.get('B', params.get('底宽', params.get('b', 0)))
            if "圆拱直墙" in sv and b > 0:
                H_total = params.get('H_total', 0) or 0
                theta_deg = params.get('theta_deg', 0) or 0
                if H_total > 0 and theta_deg > 0:
                    return self._arch_tunnel_surface_width(b, H_total, math.radians(theta_deg), h)
            if sv == "渡槽-矩形" and b > 0:
                ca = params.get('chamfer_angle', 0) or 0
                cl = params.get('chamfer_length', 0) or 0
                if ca > 0 and cl > 0:
                    return self._rect_chamfer_surface_width(b, h, ca, cl)

        m = params.get('m', params.get('边坡系数', params.get('边坡', 0)))

        B = b + 2 * m * h
        return B
    
    def get_channel_design_depth(self, flow_section: str, nodes: List[ChannelNode]) -> float:
        """
        获取同一流量段内明渠结构的设计水深
        
        在nodes中查找同一flow_section的明渠节点，返回其设计水深（若多个取最大值）
        
        Args:
            flow_section: 流量段标识
            nodes: 节点列表
            
        Returns:
            设计水深（m）
        """
        max_depth = 0.0
        
        for node in nodes:
            # 检查是否为同一流量段
            if node.flow_section != flow_section:
                continue
            
            # 检查是否为明渠结构
            if node.structure_type is None:
                continue
            
            struct_name = node.structure_type.value
            if "明渠" not in struct_name:
                continue
            
            # 获取水深
            depth = node.water_depth
            if depth <= 0:
                depth = node.section_params.get('水深', node.section_params.get('h', 0))
            
            if depth > max_depth:
                max_depth = depth
        
        # 如果没找到，返回默认值
        if max_depth <= 0:
            max_depth = 2.0  # 默认2米
        
        return max_depth
    
    def get_transition_zeta(self, transition_node: ChannelNode) -> float:
        """
        获取渐变段局部损失系数ζ
        
        从TRANSITION_ZETA_COEFFICIENTS表查找，支持手动修改和直线形扭曲面插值
        
        Args:
            transition_node: 渐变段节点
            
        Returns:
            ζ系数
        """
        transition_type = transition_node.transition_type  # "进口"或"出口"
        form = transition_node.transition_form
        
        # 如果用户手动设置了ζ值，直接使用
        if transition_node.transition_zeta > ZERO_TOLERANCE:
            return transition_node.transition_zeta
        
        # 从表K.1.2查找
        if transition_type in TRANSITION_ZETA_COEFFICIENTS:
            zeta_table = TRANSITION_ZETA_COEFFICIENTS[transition_type]
            
            if form in zeta_table:
                return zeta_table[form]
            
            elif form == "直线形扭曲面":
                # 根据θ角度线性插值
                theta = transition_node.transition_theta
                range_config = TRANSITION_TWISTED_ZETA_RANGE.get(transition_type, {})
                
                min_theta = range_config.get("min_theta", 15)
                max_theta = range_config.get("max_theta", 37)
                min_zeta = range_config.get("min_zeta", 0.0)
                max_zeta = range_config.get("max_zeta", 0.1)
                
                if theta <= min_theta:
                    return min_zeta
                elif theta >= max_theta:
                    return max_zeta
                else:
                    # 线性插值
                    ratio = (theta - min_theta) / (max_theta - min_theta)
                    return min_zeta + ratio * (max_zeta - min_zeta)
        
        # 默认值
        return 0.1 if transition_type == "进口" else 0.2
    
    def calculate_transition_length(self, transition_node: ChannelNode,
                                    prev_node: ChannelNode,
                                    next_node: ChannelNode,
                                    all_nodes: List[ChannelNode]) -> float:
        """
        计算渐变段长度L
        
        基本公式：
        - 进口: L = 2.5 × |B1 - B2|
        - 出口: L = 3.5 × |B1 - B2|
        
        约束条件：
        - 渡槽进口: max(计算值, 6倍渠道设计水深)
        - 渡槽出口: max(计算值, 8倍渠道设计水深)
        - 隧洞进出口: max(计算值, 5倍渠道水深, 3倍洞径或洞宽)
        
        Args:
            transition_node: 渐变段节点
            prev_node: 前一节点（渐变段起始端）
            next_node: 后一节点（渐变段末端）
            all_nodes: 所有节点列表（用于查找渠道水深）
            
        Returns:
            渐变段长度L（m）
        """
        # 计算水面宽度
        B1 = self.get_water_surface_width(prev_node)
        B2 = self.get_water_surface_width(next_node)
        
        transition_node.transition_water_width_1 = B1
        transition_node.transition_water_width_2 = B2
        
        # 基本公式
        transition_type = transition_node.transition_type
        coefficient = TRANSITION_LENGTH_COEFFICIENTS.get(transition_type, 2.5)
        L_basic = coefficient * abs(B1 - B2)
        
        # 应用约束条件
        L_result = L_basic
        
        # 确定结构类型：出口渐变段→从 prev_node（建筑物出口），进口渐变段→从 next_node（建筑物进口）
        if transition_type == "进口":
            struct_node = next_node
        else:
            struct_node = prev_node
        structure_type = struct_node.structure_type if struct_node else prev_node.structure_type
        if structure_type is None:
            return L_result
        
        struct_name = structure_type.value
        
        # 获取相邻明渠的水深（而非整个流量段的最大水深）
        # - 出口渐变段（建筑物出口→明渠）：使用 next_node（下游明渠）的水深
        # - 进口渐变段（明渠→建筑物进口）：使用 prev_node（上游明渠）的水深
        channel_depth = 0.0
        if transition_type == "出口":
            # 出口渐变段：使用下游节点（next_node）的水深
            if next_node and next_node.water_depth > 0:
                channel_depth = next_node.water_depth
            elif next_node and next_node.section_params:
                channel_depth = next_node.section_params.get('水深', next_node.section_params.get('h', 0))
        else:
            # 进口渐变段：使用上游节点（prev_node）的水深
            if prev_node and prev_node.water_depth > 0:
                channel_depth = prev_node.water_depth
            elif prev_node and prev_node.section_params:
                channel_depth = prev_node.section_params.get('水深', prev_node.section_params.get('h', 0))
        
        # 如果相邻节点水深无效，回退到查找同一流量段的明渠水深
        if channel_depth <= 0:
            channel_depth = self.get_channel_design_depth(
                transition_node.flow_section, all_nodes
            )
        
        # 渡槽约束
        if "渡槽" in struct_name:
            constraints = TRANSITION_LENGTH_CONSTRAINTS.get("渡槽", {})
            type_constraint = constraints.get(transition_type, {})
            depth_multiplier = type_constraint.get("depth_multiplier", 6)
            L_min = depth_multiplier * channel_depth
            L_result = max(L_result, L_min)
        
        # 隧洞约束
        elif "隧洞" in struct_name:
            constraints = TRANSITION_LENGTH_CONSTRAINTS.get("隧洞", {})
            type_constraint = constraints.get(transition_type, {})
            
            # 5倍渠道水深
            depth_multiplier = type_constraint.get("depth_multiplier", 5)
            L_depth = depth_multiplier * channel_depth
            
            # 3倍洞径或洞宽（从结构节点获取）
            tunnel_multiplier = type_constraint.get("tunnel_multiplier", 3)
            _sp = struct_node.section_params if struct_node.section_params else {}
            D = _sp.get('D', _sp.get('直径', 0))
            B = _sp.get('B', _sp.get('底宽', 0))
            # 对于马蹄形隧洞等只有半径的断面，需要将半径换算为直径
            R_circle = _sp.get('R_circle', _sp.get('半径', _sp.get('内半径', 0)))
            if R_circle > 0 and D == 0:
                D = 2 * R_circle  # 半径换算为直径
            tunnel_size = max(D, B)
            L_tunnel = tunnel_multiplier * tunnel_size
            
            L_result = max(L_result, L_depth, L_tunnel)
        
        # 倒虹吸约束（规范10.2.4）
        # 进口渐变段长度宜取上游渠道设计水深的3~5倍（取大值5倍）
        # 出口渐变段长度宜取下游渠道设计水深的4~6倍（取大值6倍）
        # 注意：与隧洞不同，倒虹吸不使用洞径约束，仅用水深倍数
        elif "倒虹吸" in struct_name:
            constraints = TRANSITION_LENGTH_CONSTRAINTS.get("倒虹吸", {})
            type_constraint = constraints.get(transition_type, {})
            depth_multiplier = type_constraint.get("depth_multiplier", 5 if transition_type == "进口" else 6)
            L_min = depth_multiplier * channel_depth
            L_result = max(L_result, L_min)
        
        # 矩形暗涵：无额外约束，纯用基础公式 L=k×|B₁-B₂|
        # elif "暗涵" in struct_name: pass  # L_result = L_basic已足够
        
        # 记录渐变段长度计算详情（用于双击展示）
        transition_node.transition_length_calc_details = {
            "transition_type": transition_type,
            "struct_name": struct_name,
            "B1": B1,
            "B2": B2,
            "coefficient": coefficient,
            "L_basic": L_basic,
            "channel_depth": channel_depth,
            "L_result": L_result,
            "constraint_applied": struct_name if L_result > L_basic else "",
            "prev_name": prev_node.name or "",
            "next_name": next_node.name or "",
        }
        # 补充各约束类型的详细参数
        if "渡槽" in struct_name:
            depth_multiplier = TRANSITION_LENGTH_CONSTRAINTS.get("渡槽", {}).get(transition_type, {}).get("depth_multiplier", 6)
            transition_node.transition_length_calc_details["depth_multiplier"] = depth_multiplier
            transition_node.transition_length_calc_details["L_depth"] = depth_multiplier * channel_depth
            transition_node.transition_length_calc_details["constraint_desc"] = f"{depth_multiplier}倍渠道设计水深"
        elif "隧洞" in struct_name:
            _tc = TRANSITION_LENGTH_CONSTRAINTS.get("隧洞", {}).get(transition_type, {})
            _dm = _tc.get("depth_multiplier", 5)
            _tm = _tc.get("tunnel_multiplier", 3)
            _sp2 = struct_node.section_params if struct_node.section_params else {}
            _D = _sp2.get('D', _sp2.get('直径', 0))
            _B = _sp2.get('B', _sp2.get('底宽', 0))
            _Rc = _sp2.get('R_circle', _sp2.get('半径', _sp2.get('内半径', 0)))
            if _Rc > 0 and _D == 0:
                _D = 2 * _Rc
            _ts = max(_D, _B)
            transition_node.transition_length_calc_details["depth_multiplier"] = _dm
            transition_node.transition_length_calc_details["L_depth"] = _dm * channel_depth
            transition_node.transition_length_calc_details["tunnel_multiplier"] = _tm
            transition_node.transition_length_calc_details["tunnel_size"] = _ts
            transition_node.transition_length_calc_details["L_tunnel"] = _tm * _ts
            transition_node.transition_length_calc_details["constraint_desc"] = f"max({_dm}倍水深, {_tm}倍洞径/洞宽)"
        elif "倒虹吸" in struct_name:
            _dm = TRANSITION_LENGTH_CONSTRAINTS.get("倒虹吸", {}).get(transition_type, {}).get("depth_multiplier", 5 if transition_type == "进口" else 6)
            transition_node.transition_length_calc_details["depth_multiplier"] = _dm
            transition_node.transition_length_calc_details["L_depth"] = _dm * channel_depth
            transition_node.transition_length_calc_details["constraint_desc"] = f"{_dm}倍渠道设计水深"
        elif "暗涵" in struct_name:
            transition_node.transition_length_calc_details["constraint_desc"] = "仅基础公式"
        
        return L_result
    
    def calculate_transition_friction_loss(self, transition_node: ChannelNode,
                                           prev_node: ChannelNode,
                                           next_node: ChannelNode,
                                           length: float) -> float:
        """
        计算渐变段沿程水头损失（平均值法）
        
        步骤：
        1. 计算两断面的R和v平均值
        2. 代入曼宁公式求平均水力坡降i
        3. h_f = i × L
        
        Args:
            transition_node: 渐变段节点
            prev_node: 前一节点
            next_node: 后一节点
            length: 渐变段长度
            
        Returns:
            沿程水头损失（m）
        """
        # 获取水力半径
        R1 = prev_node.section_params.get('R', prev_node.section_params.get('水力半径', 0))
        R2 = next_node.section_params.get('R', next_node.section_params.get('水力半径', 0))
        
        if R1 <= 0:
            R1 = self.calculate_hydraulic_radius(prev_node)
        if R2 <= 0:
            R2 = self.calculate_hydraulic_radius(next_node)
        
        R_avg = (R1 + R2) / 2 if (R1 > 0 and R2 > 0) else max(R1, R2)
        transition_node.transition_avg_R = R_avg
        
        # 获取流速
        v1 = prev_node.velocity
        v2 = next_node.velocity
        v_avg = (v1 + v2) / 2 if (v1 > 0 and v2 > 0) else max(v1, v2)
        transition_node.transition_avg_v = v_avg
        
        # 糙率
        n = transition_node.roughness if transition_node.roughness > 0 else self.roughness
        
        # 曼宁公式反算水力坡降
        if R_avg > ZERO_TOLERANCE and v_avg > ZERO_TOLERANCE:
            i = (v_avg * n / (R_avg ** (2.0 / 3.0))) ** 2
        else:
            i = 0.0
        
        # 沿程损失
        h_f = i * length
        
        return round(h_f, HEAD_LOSS_PRECISION)
    
    def calculate_transition_loss(self, transition_node: ChannelNode,
                                  prev_node: ChannelNode,
                                  next_node: ChannelNode,
                                  all_nodes: List[ChannelNode]) -> float:
        """
        计算渐变段水头损失
        
        包括：
        1. 局部水头损失 h_j1 = ξ₁ × |v₂² - v₁²| / (2g)
        2. 沿程水头损失 h_f = i × L（使用平均值法）
        
        Args:
            transition_node: 渐变段节点
            prev_node: 前一节点（渐变段起始端）
            next_node: 后一节点（渐变段末端）
            all_nodes: 所有节点列表（用于查找渠道水深）
            
        Returns:
            总水头损失（m）
        """
        # 1. 获取ζ系数
        zeta = self.get_transition_zeta(transition_node)
        transition_node.transition_zeta = zeta
        
        # 2. 计算渐变段长度
        length = self.calculate_transition_length(
            transition_node, prev_node, next_node, all_nodes
        )
        transition_node.transition_length = length
        
        # 3. 获取起始和末端流速
        v1 = prev_node.velocity
        v2 = next_node.velocity
        transition_node.transition_velocity_1 = v1
        transition_node.transition_velocity_2 = v2
        
        # 4. 计算局部水头损失: h_j1 = ξ × |v₂² - v₁²| / (2g)
        h_j1 = zeta * abs(v2 * v2 - v1 * v1) / (2 * GRAVITY)
        h_j1 = round(h_j1, HEAD_LOSS_PRECISION)
        transition_node.transition_head_loss_local = h_j1
        
        # 5. 计算沿程水头损失（使用平均值法）
        h_f = self.calculate_transition_friction_loss(
            transition_node, prev_node, next_node, length
        )
        transition_node.transition_head_loss_friction = h_f
        
        # 6. 总损失
        total_loss = h_j1 + h_f
        transition_node.head_loss_transition = round(total_loss, HEAD_LOSS_PRECISION)
        
        # 7. 记录计算详细过程（用于LaTeX显示）
        transition_node.transition_calc_details = {
            "transition_type": transition_node.transition_type,
            "transition_form": transition_node.transition_form,
            "zeta": zeta,
            "v1": v1,
            "v2": v2,
            "B1": transition_node.transition_water_width_1,
            "B2": transition_node.transition_water_width_2,
            "length": length,
            "R_avg": transition_node.transition_avg_R,
            "v_avg": transition_node.transition_avg_v,
            "h_j1": h_j1,
            "h_f": h_f,
            "total": total_loss,
        }
        
        return total_loss

    def calculate_transition_loss_inline(self, prev_node: ChannelNode,
                                         next_node: ChannelNode,
                                         settings: ProjectSettings) -> tuple:
        """
        计算渐变段水头损失（内联方式，不依赖专用渐变段节点）
        
        将计算结果返回，供调用方累加到相邻节点的总损失中。
        
        Args:
            prev_node: 前一节点（出口侧）
            next_node: 后一节点（进口侧）
            settings: 项目设置（用于获取渐变段形式等参数）
            
        Returns:
            tuple: (total_loss, details_dict)
                - total_loss: 总水头损失（m）
                - details_dict: 详细计算信息字典（用于双击显示）
        """
        # 1. 确定渐变段类型和形式（进口/出口相对于特殊建筑物而言）
        sv_next = next_node.structure_type.value if next_node.structure_type else ""
        _special_kw = ("隧洞", "渡槽", "倒虹吸", "暗涵")
        if any(kw in sv_next for kw in _special_kw):
            transition_type = "进口"
            transition_form = getattr(settings, 'transition_inlet_form', "曲线形反弯扭曲面") or "曲线形反弯扭曲面"
        else:
            transition_type = "出口"
            transition_form = getattr(settings, 'transition_outlet_form', "曲线形反弯扭曲面") or "曲线形反弯扭曲面"
        
        # 2. 获取ζ系数
        if transition_type in TRANSITION_ZETA_COEFFICIENTS:
            zeta_table = TRANSITION_ZETA_COEFFICIENTS[transition_type]
            zeta = zeta_table.get(transition_form, 0.2)
        else:
            zeta = 0.2
        
        # 3. 计算水面宽度
        B1 = self.get_water_surface_width(prev_node)
        B2 = self.get_water_surface_width(next_node)
        
        # 4. 计算渐变段长度
        coefficient = TRANSITION_LENGTH_COEFFICIENTS.get(transition_type, 3.5)
        L_basic = coefficient * abs(B1 - B2)
        
        # 应用约束条件（从特殊建筑物节点获取结构类型）
        length = L_basic
        struct_node = next_node if transition_type == "进口" else prev_node
        structure_type = struct_node.structure_type
        if structure_type:
            struct_name = structure_type.value
            # 水深：出口→下游明渠(next_node)，进口→上游明渠(prev_node)
            channel_node = prev_node if transition_type == "进口" else next_node
            channel_depth = channel_node.water_depth if channel_node.water_depth > 0 else 0
            
            # 渡槽约束
            if "渡槽" in struct_name:
                constraints = TRANSITION_LENGTH_CONSTRAINTS.get("渡槽", {})
                type_constraint = constraints.get(transition_type, {})
                depth_multiplier = type_constraint.get("depth_multiplier", 6 if transition_type == "进口" else 8)
                L_min = depth_multiplier * channel_depth
                length = max(length, L_min)
            
            # 隧洞约束
            elif "隧洞" in struct_name:
                constraints = TRANSITION_LENGTH_CONSTRAINTS.get("隧洞", {})
                type_constraint = constraints.get(transition_type, {})
                depth_multiplier = type_constraint.get("depth_multiplier", 5)
                tunnel_multiplier = type_constraint.get("tunnel_multiplier", 3)
                
                L_depth = depth_multiplier * channel_depth
                
                # 获取洞径（从结构节点）
                params = struct_node.section_params or {}
                D = params.get('D', params.get('直径', 0))
                R = params.get('R_circle', params.get('半径', 0))
                tunnel_size = D if D > 0 else (2 * R if R > 0 else 0)
                L_tunnel = tunnel_multiplier * tunnel_size
                
                length = max(length, L_depth, L_tunnel)
        
        # 5. 获取流速
        v1 = prev_node.velocity
        v2 = next_node.velocity
        
        # 6. 计算局部水头损失: h_j1 = ξ × |v₂² - v₁²| / (2g)
        h_j1 = zeta * abs(v2 * v2 - v1 * v1) / (2 * GRAVITY)
        h_j1 = round(h_j1, HEAD_LOSS_PRECISION)
        
        # 7. 计算沿程水头损失（平均值法）
        # 获取水力半径
        R1 = prev_node.section_params.get('R', prev_node.section_params.get('水力半径', 0)) if prev_node.section_params else 0
        R2 = next_node.section_params.get('R', next_node.section_params.get('水力半径', 0)) if next_node.section_params else 0
        
        if R1 <= 0:
            R1 = self.calculate_hydraulic_radius(prev_node)
        if R2 <= 0:
            R2 = self.calculate_hydraulic_radius(next_node)
        
        R_avg = (R1 + R2) / 2 if (R1 > 0 and R2 > 0) else max(R1, R2)
        v_avg = (v1 + v2) / 2 if (v1 > 0 and v2 > 0) else max(v1, v2)
        
        # 糙率
        n = prev_node.roughness if prev_node.roughness > 0 else self.roughness
        
        # 曼宁公式反算水力坡降
        if R_avg > ZERO_TOLERANCE and v_avg > ZERO_TOLERANCE:
            i = (v_avg * n / (R_avg ** (2.0 / 3.0))) ** 2
        else:
            i = 0.0
        
        h_f = i * length
        h_f = round(h_f, HEAD_LOSS_PRECISION)
        
        # 8. 总损失
        total_loss = round(h_j1 + h_f, HEAD_LOSS_PRECISION)
        
        # 9. 构建详细计算信息
        details = {
            "transition_type": transition_type,
            "transition_form": transition_form,
            "zeta": zeta,
            "v1": v1,
            "v2": v2,
            "B1": B1,
            "B2": B2,
            "length": length,
            "R_avg": R_avg,
            "v_avg": v_avg,
            "h_j1": h_j1,
            "h_f": h_f,
            "total": total_loss,
        }
        
        return total_loss, details
