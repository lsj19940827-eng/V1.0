# -*- coding: utf-8 -*-
"""
几何计算模块

提供平面几何计算功能，包括方位角、转角、切线长、弧长、桩号等计算。
注意：具体计算公式将在后续完善。
"""

import math
from typing import List, Tuple, Optional
import sys
import os

# 添加父目录到路径以支持相对导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.data_models import ChannelNode, ProjectSettings
from models.enums import InOutType
from config.constants import ZERO_TOLERANCE, ANGLE_PRECISION, LENGTH_PRECISION


class GeometryCalculator:
    """
    几何计算器
    
    负责平面几何相关的计算，包括：
    - 方位角计算
    - 转角计算
    - 切线长计算
    - 弧长计算
    - 桩号推算
    """
    
    def __init__(self, settings: ProjectSettings):
        """
        初始化几何计算器
        
        Args:
            settings: 项目设置（包含默认转弯半径等参数）
        """
        self.settings = settings
        self.default_turn_radius = settings.turn_radius  # 默认转弯半径
    
    def calculate_azimuth(self, x1: float, y1: float, x2: float, y2: float) -> float:
        """
        计算两点间的方位角
        
        方位角定义：从正北方向顺时针到连线方向的角度（0~360°）
        
        Args:
            x1, y1: 起点坐标
            x2, y2: 终点坐标
            
        Returns:
            方位角（度）
        """
        # TODO: 实现方位角计算公式
        # 基本公式: azimuth = atan2(dx, dy) 并转换到 0-360 范围
        dx = x2 - x1
        dy = y2 - y1
        
        if abs(dx) < ZERO_TOLERANCE and abs(dy) < ZERO_TOLERANCE:
            return 0.0
        
        # 计算方位角（弧度）
        azimuth_rad = math.atan2(dx, dy)
        
        # 转换为度数
        azimuth_deg = math.degrees(azimuth_rad)
        
        # 转换到 0-360 范围
        if azimuth_deg < 0:
            azimuth_deg += 360.0
        
        return azimuth_deg
    
    def calculate_distance(self, x1: float, y1: float, x2: float, y2: float) -> float:
        """
        计算两点间的距离
        
        Args:
            x1, y1: 起点坐标
            x2, y2: 终点坐标
            
        Returns:
            距离（m）
        """
        dx = x2 - x1
        dy = y2 - y1
        distance = math.sqrt(dx * dx + dy * dy)
        return distance
    
    def calculate_turn_angle_by_cosine(self, x_prev: float, y_prev: float, 
                                        x_curr: float, y_curr: float,
                                        x_next: float, y_next: float) -> float:
        """
        使用余弦定理计算转角
        
        根据三个相邻点的坐标，计算中间点的转角（偏角）。
        公式：
        - a² = (X(i+1) - X(i))² + (Y(i+1) - Y(i))²  当前到下一点
        - b² = (X(i+1) - X(i-1))² + (Y(i+1) - Y(i-1))²  前一点到下一点
        - c² = (X(i) - X(i-1))² + (Y(i) - Y(i-1))²  前一点到当前点
        - cosθ = (a² + c² - b²) / (2 × √a² × √c²)
        - α = 180° - arccos(cosθ) × 180/π
        
        Args:
            x_prev, y_prev: 前一点坐标
            x_curr, y_curr: 当前点坐标
            x_next, y_next: 下一点坐标
            
        Returns:
            转角（度）
        """
        # 计算三边的平方
        a_sq = (x_next - x_curr) ** 2 + (y_next - y_curr) ** 2  # 当前到下一点
        b_sq = (x_next - x_prev) ** 2 + (y_next - y_prev) ** 2  # 前一点到下一点
        c_sq = (x_curr - x_prev) ** 2 + (y_curr - y_prev) ** 2  # 前一点到当前点
        
        a = math.sqrt(a_sq)
        c = math.sqrt(c_sq)
        
        # 防止除零
        if a < ZERO_TOLERANCE or c < ZERO_TOLERANCE:
            return 0.0
        
        # 计算余弦值
        cos_theta = (a_sq + c_sq - b_sq) / (2 * a * c)
        
        # 限制cos_theta在[-1, 1]范围内，防止浮点误差
        cos_theta = max(-1.0, min(1.0, cos_theta))
        
        # 计算转角: α = 180° - arccos(cosθ) × 180/π
        theta_deg = math.degrees(math.acos(cos_theta))
        turn_angle = 180.0 - theta_deg
        
        return turn_angle
    
    def calculate_turn_angle(self, azimuth1: float, azimuth2: float) -> float:
        """
        计算转角
        
        转角定义：前后两段线路方位角之差
        正值为右转，负值为左转
        
        Args:
            azimuth1: 前一段方位角（度）
            azimuth2: 后一段方位角（度）
            
        Returns:
            转角（度）
        """
        # TODO: 根据实际需求完善转角计算
        # 基本公式: 转角 = 后方位角 - 前方位角
        delta = azimuth2 - azimuth1
        
        # 归一化到 -180 ~ 180 范围
        while delta > 180:
            delta -= 360
        while delta < -180:
            delta += 360
        
        return delta
    
    def calculate_tangent_length(self, turn_angle: float, turn_radius: float) -> float:
        """
        计算切线长
        
        切线长 T = R × tan(α/2)
        其中 R 为转弯半径，α 为转角（弧度）
        
        Args:
            turn_angle: 转角（度）
            turn_radius: 转弯半径（m）
            
        Returns:
            切线长（m）
        """
        # TODO: 根据实际需求完善切线长计算
        if abs(turn_angle) < ZERO_TOLERANCE:
            return 0.0
        
        if turn_radius <= 0:
            return 0.0
        
        # 转换为弧度
        alpha_rad = math.radians(abs(turn_angle))
        
        # T = R × tan(α/2)
        tangent = turn_radius * math.tan(alpha_rad / 2)
        
        return tangent
    
    def calculate_arc_length(self, turn_angle: float, turn_radius: float) -> float:
        """
        计算弧长
        
        弧长 L = R × α
        其中 R 为转弯半径，α 为转角（弧度）
        
        Args:
            turn_angle: 转角（度）
            turn_radius: 转弯半径（m）
            
        Returns:
            弧长（m）
        """
        # TODO: 根据实际需求完善弧长计算
        if abs(turn_angle) < ZERO_TOLERANCE:
            return 0.0
        
        if turn_radius <= 0:
            return 0.0
        
        # 转换为弧度
        alpha_rad = math.radians(abs(turn_angle))
        
        # L = R × α
        arc = turn_radius * alpha_rad
        
        return arc
    
    def calculate_curve_elements(self, turn_angle: float, turn_radius: float) -> Tuple[float, float]:
        """
        计算曲线要素（切线长和弧长）
        
        Args:
            turn_angle: 转角（度）
            turn_radius: 转弯半径（m）
            
        Returns:
            (切线长, 弧长)
        """
        tangent = self.calculate_tangent_length(turn_angle, turn_radius)
        arc = self.calculate_arc_length(turn_angle, turn_radius)
        return tangent, arc
    
    def calculate_all_geometry(self, nodes: List[ChannelNode]) -> None:
        """
        计算所有节点的几何参数
        
        包括转角、切线长、弧长、直线距离等
        注意：当节点有进出口标记（"进"或"出"）时，其转角、切线长、弧长均为0
        
        Args:
            nodes: 节点列表（原地修改）
        """
        if len(nodes) < 2:
            return
        
        # 第一步：计算各段直线距离（IP间距）
        # IP直线间距存储在当前节点，表示从前一点到当前点的距离
        for i in range(1, len(nodes)):
            prev_node = nodes[i - 1]
            curr_node = nodes[i]
            
            # 计算直线距离（IP间距）: D = √((Y(i)-Y(i-1))² + (X(i)-X(i-1))²)
            distance = self.calculate_distance(prev_node.x, prev_node.y, curr_node.x, curr_node.y)
            curr_node.straight_distance = distance
        
        # 第二步：计算转角和曲线要素（使用余弦定理）
        # 注意：当节点有进出口标记时，跳过计算，保持为0
        for i in range(1, len(nodes) - 1):
            node = nodes[i]
            
            # 如果是进出口节点，转角、切线长、弧长保持为0
            if node.in_out in (InOutType.INLET, InOutType.OUTLET):
                node.turn_angle = 0.0
                node.tangent_length = 0.0
                node.arc_length = 0.0
                continue
            
            prev_node = nodes[i - 1]
            next_node = nodes[i + 1]
            
            # 使用余弦定理计算转角
            turn_angle = self.calculate_turn_angle_by_cosine(
                prev_node.x, prev_node.y,
                node.x, node.y,
                next_node.x, next_node.y
            )
            node.turn_angle = turn_angle
            
            # 获取该节点的转弯半径（如果未设置则使用默认值）
            turn_radius = node.turn_radius if node.turn_radius > 0 else self.default_turn_radius
            
            # 计算切线长: T = R × tan(α/2 × π/180)
            tangent = self.calculate_tangent_length(turn_angle, turn_radius)
            node.tangent_length = tangent
            
            # 计算弧长: L = π × R × α / 180
            arc = self.calculate_arc_length(turn_angle, turn_radius)
            node.arc_length = arc
    
    def calculate_stations(self, nodes: List[ChannelNode], start_station: float = 0.0) -> None:
        """
        计算所有节点的桩号
        
        包括IP点桩号、BC桩号、MC桩号、EC桩号
        
        公式：
        - IP点桩号 = 起始桩号 + 累计直线距离
        - 里程MC递推: S_MC(i) = S_MC(i-1) + D(i-1,i) - T(i-1) - T(i) + L_arc(i-1)/2 + L_arc(i)/2
        - 弯前BC: S_BC = S_MC - L_arc/2
        - 弯末EC: S_EC = S_BC + L_arc
        
        Args:
            nodes: 节点列表（原地修改）
            start_station: 起始桩号（m），默认为0
        """
        if not nodes:
            return
        
        # 起点桩号
        nodes[0].station_ip = start_station
        nodes[0].station_MC = start_station
        nodes[0].station_BC = start_station
        nodes[0].station_EC = start_station
        
        # 累计IP直线距离
        cumulative_ip_distance = start_station
        
        for i in range(1, len(nodes)):
            prev_node = nodes[i - 1]
            curr_node = nodes[i]
            
            # IP点桩号 = 累计直线距离
            # straight_distance现在存储在curr_node中，表示从prev_node到curr_node的距离
            cumulative_ip_distance += curr_node.straight_distance
            curr_node.station_ip = cumulative_ip_distance
            
            # 里程MC递推公式:
            # S_MC(i) = S_MC(i-1) + D(i-1,i) - T(i-1) - T(i) + L_arc(i-1)/2 + L_arc(i)/2
            # D(i-1,i) = curr_node.straight_distance (从前一点到当前点的距离)
            prev_T = prev_node.tangent_length
            curr_T = curr_node.tangent_length
            prev_L = prev_node.arc_length
            curr_L = curr_node.arc_length
            
            station_MC = (prev_node.station_MC + 
                          curr_node.straight_distance - 
                          prev_T - curr_T + 
                          prev_L / 2 + curr_L / 2)
            curr_node.station_MC = station_MC
            
            # 弯前BC: S_BC = S_MC - L_arc/2
            curr_node.station_BC = curr_node.station_MC - curr_L / 2
            
            # 弯末EC: S_EC = S_BC + L_arc
            curr_node.station_EC = curr_node.station_BC + curr_L
            
            # 弯道长度 = EC - BC
            curr_node.curve_length = curr_node.station_EC - curr_node.station_BC
        
        # 第四步：计算复核长度（用于检查设计合理性，不能出现负数）
        for i in range(len(nodes)):
            curr_node = nodes[i]
            prev_tangent = nodes[i - 1].tangent_length if i > 0 else 0.0
            next_straight = nodes[i + 1].straight_distance if i < len(nodes) - 1 else 0.0
            
            # 复核弯前长度 = L72 - J72 (当前IP直线间距 - 当前切线长)
            # 检查起弯点是否超过上一IP
            curr_node.check_pre_curve = curr_node.straight_distance - curr_node.tangent_length
            
            # 复核弯后长度 = L73 - J72 (下一段IP直线间距 - 当前切线长)
            # 检查出弯点是否超过下一IP
            curr_node.check_post_curve = next_straight - curr_node.tangent_length
            
            # 复核总长度 = L72 - J71 - J72 (当前IP直线间距 - 上一切线长 - 当前切线长)
            # 夹直线长度，检查两弯道之间是否有足够的直线段
            curr_node.check_total_length = curr_node.straight_distance - prev_tangent - curr_node.tangent_length
