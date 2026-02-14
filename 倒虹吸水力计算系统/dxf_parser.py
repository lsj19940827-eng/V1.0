# -*- coding: utf-8 -*-
"""
倒虹吸水力计算软件 - DXF解析引擎
负责将非结构化的CAD几何图形转换为结构段数据和纵断面变坡点节点表
"""

import math
from typing import List, Tuple, Optional
from siphon_models import (
    StructureSegment, SegmentType, SegmentDirection, LongitudinalNode, TurnType,
    InletOutletShape, INLET_SHAPE_COEFFICIENTS
)


class DxfParser:
    """DXF解析器类"""
    
    @staticmethod
    def parse_dxf(file_path: str) -> Tuple[List[StructureSegment], float, str]:
        """
        解析DXF文件
        
        Args:
            file_path: DXF文件路径
            
        Returns:
            (结构段列表, 上游渠底高程建议值, 消息)
        """
        try:
            import ezdxf
        except ImportError:
            return [], 0.0, "错误：未安装ezdxf库，请运行 pip install ezdxf"
        
        try:
            doc = ezdxf.readfile(file_path)
        except Exception as e:
            return [], 0.0, f"错误：无法读取DXF文件 - {str(e)}"
        
        msp = doc.modelspace()
        
        # 查找LWPOLYLINE实体
        polylines = list(msp.query('LWPOLYLINE'))
        if not polylines:
            # 也尝试查找POLYLINE
            polylines = list(msp.query('POLYLINE'))
        
        if not polylines:
            return [], 0.0, "错误：DXF文件中未找到多段线(LWPOLYLINE/POLYLINE)实体"
        
        # 使用第一条多段线
        polyline = polylines[0]
        
        # 提取顶点和凸度
        vertices = []
        bulges = []
        
        if hasattr(polyline, 'get_points'):
            # LWPOLYLINE
            for point in polyline.get_points(format='xyseb'):
                x, y, start_width, end_width, bulge = point
                vertices.append((x, y))
                bulges.append(bulge)
        elif hasattr(polyline, 'vertices'):
            # POLYLINE
            for vertex in polyline.vertices:
                vertices.append((vertex.dxf.location.x, vertex.dxf.location.y))
                bulges.append(vertex.dxf.bulge if hasattr(vertex.dxf, 'bulge') else 0.0)
        else:
            return [], 0.0, "错误：无法解析多段线顶点"
        
        if len(vertices) < 2:
            return [], 0.0, "错误：多段线顶点数量不足"
        
        # 构建结构段列表
        segments = DxfParser._build_segments(vertices, bulges)
        
        # 返回首点Y坐标作为上游渠底高程建议值
        h_bottom_up = vertices[0][1] if vertices else 0.0
        
        return segments, h_bottom_up, f"成功解析DXF文件，共{len(segments)}个结构段"
    
    @staticmethod
    def _build_segments(vertices: List[Tuple[float, float]], 
                        bulges: List[float]) -> List[StructureSegment]:
        """
        构建结构段列表
        
        Args:
            vertices: 顶点列表
            bulges: 凸度列表
            
        Returns:
            结构段列表
        """
        segments = []
        
        # 创建进水口（默认"进口稍微修圆"，系数取中值0.225）
        inlet_shape = InletOutletShape.SLIGHTLY_ROUNDED
        inlet_xi = sum(INLET_SHAPE_COEFFICIENTS[inlet_shape]) / 2
        inlet = StructureSegment(
            segment_type=SegmentType.INLET,
            coordinates=[vertices[0]],
            locked=True,
            inlet_shape=inlet_shape,
            xi_calc=inlet_xi,
            direction=SegmentDirection.COMMON
        )
        segments.append(inlet)
        
        # 用于折管检测的临时存储
        prev_direction = None
        temp_straight_segments = []
        
        for i in range(len(vertices) - 1):
            p1 = vertices[i]
            p2 = vertices[i + 1]
            bulge = bulges[i] if i < len(bulges) else 0.0
            
            if abs(bulge) > 1e-6:
                # 弯管识别
                segment = DxfParser._create_bend_segment(p1, p2, bulge)
                
                # 处理之前累积的直管段
                if temp_straight_segments:
                    segments.extend(DxfParser._process_straight_segments(temp_straight_segments))
                    temp_straight_segments = []
                    prev_direction = None
                
                segments.append(segment)
            else:
                # 直管段
                length = math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
                direction = DxfParser._get_direction(p1, p2)
                
                straight_seg = {
                    'p1': p1,
                    'p2': p2,
                    'length': length,
                    'direction': direction
                }
                temp_straight_segments.append(straight_seg)
        
        # 处理剩余的直管段
        if temp_straight_segments:
            segments.extend(DxfParser._process_straight_segments(temp_straight_segments))
        
        # 创建出水口（初始系数设为0，待用户设置渠道参数后计算）
        outlet = StructureSegment(
            segment_type=SegmentType.OUTLET,
            coordinates=[vertices[-1]],
            locked=True,
            direction=SegmentDirection.COMMON
        )
        segments.append(outlet)
        
        return segments
    
    @staticmethod
    def _create_bend_segment(p1: Tuple[float, float], 
                              p2: Tuple[float, float], 
                              bulge: float) -> StructureSegment:
        """
        创建弯管段
        
        Args:
            p1: 起点
            p2: 终点
            bulge: 凸度
            
        Returns:
            弯管结构段
        """
        # 计算弦长
        chord_length = math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
        
        # 根据凸度计算半径和圆心角
        # bulge = tan(θ/4)，其中θ是圆心角
        # 半径 R = chord / (2 * sin(θ/2))
        angle_rad = 4 * math.atan(abs(bulge))
        angle_deg = math.degrees(angle_rad)
        
        if abs(math.sin(angle_rad / 2)) > 1e-6:
            radius = chord_length / (2 * math.sin(angle_rad / 2))
        else:
            radius = chord_length / 2
        
        # 计算弧长
        arc_length = radius * angle_rad
        
        return StructureSegment(
            segment_type=SegmentType.BEND,
            length=arc_length,
            radius=radius,
            angle=angle_deg,
            coordinates=[p1, p2],
            locked=True,
            start_elevation=p1[1],
            end_elevation=p2[1]
        )
    
    @staticmethod
    def _get_direction(p1: Tuple[float, float], 
                       p2: Tuple[float, float]) -> Tuple[float, float]:
        """
        计算方向向量（单位化）
        """
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.sqrt(dx**2 + dy**2)
        if length > 1e-6:
            return (dx / length, dy / length)
        return (0.0, 0.0)
    
    @staticmethod
    def _process_straight_segments(straight_segments: list) -> List[StructureSegment]:
        """
        处理直管段，检测折管
        
        Args:
            straight_segments: 直管段列表
            
        Returns:
            处理后的结构段列表
        """
        if not straight_segments:
            return []
        
        result = []
        
        for i, seg in enumerate(straight_segments):
            if i == 0:
                # 第一段直接作为直管
                result.append(StructureSegment(
                    segment_type=SegmentType.STRAIGHT,
                    length=seg['length'],
                    coordinates=[seg['p1'], seg['p2']],
                    locked=True,
                    start_elevation=seg['p1'][1],
                    end_elevation=seg['p2'][1]
                ))
            else:
                # 检查与前一段的角度
                prev_dir = straight_segments[i - 1]['direction']
                curr_dir = seg['direction']
                
                # 计算夹角
                dot = prev_dir[0] * curr_dir[0] + prev_dir[1] * curr_dir[1]
                dot = max(-1.0, min(1.0, dot))  # 防止浮点误差
                angle_rad = math.acos(dot)
                angle_deg = math.degrees(angle_rad)
                
                if angle_deg > 1.0:  # 大于1度认为是折管
                    # 将前一段的末端改为折管
                    if result and result[-1].segment_type == SegmentType.STRAIGHT:
                        # 合并为折管
                        prev_seg = result[-1]
                        fold_seg = StructureSegment(
                            segment_type=SegmentType.FOLD,
                            length=prev_seg.length + seg['length'],
                            angle=angle_deg,
                            coordinates=prev_seg.coordinates + [seg['p2']],
                            locked=True,
                            start_elevation=prev_seg.coordinates[0][1],
                            end_elevation=seg['p2'][1]
                        )
                        result[-1] = fold_seg
                    else:
                        # 单独创建折管
                        result.append(StructureSegment(
                            segment_type=SegmentType.FOLD,
                            length=seg['length'],
                            angle=angle_deg,
                            coordinates=[seg['p1'], seg['p2']],
                            locked=True,
                            start_elevation=seg['p1'][1],
                            end_elevation=seg['p2'][1]
                        ))
                else:
                    # 共线，创建直管
                    result.append(StructureSegment(
                        segment_type=SegmentType.STRAIGHT,
                        length=seg['length'],
                        coordinates=[seg['p1'], seg['p2']],
                        locked=True,
                        start_elevation=seg['p1'][1],
                        end_elevation=seg['p2'][1]
                    ))
        
        return result
    
    # ==================================================================
    # 新增：纵断面多段线解析为变坡点节点表
    # ==================================================================
    
    @staticmethod
    def parse_longitudinal_profile(file_path: str, 
                                    chainage_offset: float = 0.0
                                    ) -> Tuple[List[LongitudinalNode], str]:
        """
        解析DXF纵断面多段线为变坡点节点表
        
        多段线坐标约定（1:1 实际坐标）：
        - X 坐标 = 桩号（局部值，需加 chainage_offset 对齐到 MC 桩号）
        - Y 坐标 = 高程 (m)
        - bulge ≠ 0 的段 = 竖曲线（fillet产生的圆弧），半径 R_v 由 bulge 推算
        - bulge = 0 的段 = 等坡直线段
        
        Args:
            file_path: DXF文件路径
            chainage_offset: 桩号偏移量，使多段线起点X对齐到实际MC桩号
                             公式: 实际桩号 = X + chainage_offset
            
        Returns:
            (变坡点节点列表, 消息)
        """
        try:
            import ezdxf
        except ImportError:
            return [], "错误：未安装ezdxf库，请运行 pip install ezdxf"
        
        try:
            doc = ezdxf.readfile(file_path)
        except Exception as e:
            return [], f"错误：无法读取DXF文件 - {str(e)}"
        
        msp = doc.modelspace()
        
        # 查找多段线
        polylines = list(msp.query('LWPOLYLINE'))
        if not polylines:
            polylines = list(msp.query('POLYLINE'))
        if not polylines:
            return [], "错误：DXF文件中未找到多段线(LWPOLYLINE/POLYLINE)实体"
        
        polyline = polylines[0]
        
        # 提取顶点和凸度
        vertices = []
        bulges = []
        
        if hasattr(polyline, 'get_points'):
            for point in polyline.get_points(format='xyseb'):
                x, y, start_width, end_width, bulge = point
                vertices.append((x, y))
                bulges.append(bulge)
        elif hasattr(polyline, 'vertices'):
            for vertex in polyline.vertices:
                vx = vertex.dxf.location.x
                vy = vertex.dxf.location.y
                vb = vertex.dxf.bulge if hasattr(vertex.dxf, 'bulge') else 0.0
                vertices.append((vx, vy))
                bulges.append(vb)
        else:
            return [], "错误：无法解析多段线顶点"
        
        if len(vertices) < 2:
            return [], "错误：多段线顶点数量不足（至少需要2个点）"
        
        # 构建变坡点节点表
        nodes = DxfParser._build_longitudinal_nodes(vertices, bulges, chainage_offset)
        
        msg = (f"成功解析纵断面DXF：{len(vertices)}个顶点 → "
               f"{len(nodes)}个变坡点节点")
        return nodes, msg
    
    @staticmethod
    def _build_longitudinal_nodes(vertices: List[Tuple[float, float]],
                                   bulges: List[float],
                                   chainage_offset: float
                                   ) -> List[LongitudinalNode]:
        """
        从多段线顶点和凸度构建变坡点节点表
        
        处理流程：
        1. 遍历所有顶点，区分直线段和圆弧段
        2. 对直线段：计算坡角 β = arctan(ΔY/ΔX)
        3. 对圆弧段：从 bulge 推算竖曲线半径 R_v 和圆弧角
        4. 在每个变坡点处，记录前后坡角和转弯信息
        """
        n = len(vertices)
        
        # 第1步：为每个段计算属性（直线或圆弧）
        segments_info = []
        for i in range(n - 1):
            p1 = vertices[i]
            p2 = vertices[i + 1]
            bulge = bulges[i] if i < len(bulges) else 0.0
            
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            chord = math.sqrt(dx**2 + dy**2)
            
            if abs(bulge) > 1e-8 and chord > 1e-6:
                # 圆弧段（竖曲线，由fillet产生）
                angle_rad = 4 * math.atan(abs(bulge))
                sin_half = math.sin(angle_rad / 2)
                radius = chord / (2 * sin_half) if sin_half > 1e-8 else chord / 2
                arc_len = radius * angle_rad
                
                # 圆弧的起点切线方向和终点切线方向
                # 对于纵断面圆弧，起点坡角和终点坡角通过相邻直线段确定
                segments_info.append({
                    'type': 'arc',
                    'p1': p1, 'p2': p2,
                    'chord': chord,
                    'radius': radius,
                    'arc_angle_deg': math.degrees(angle_rad),
                    'arc_len': arc_len,
                    'bulge': bulge,
                })
            else:
                # 直线段（等坡段）
                slope_angle = math.atan2(dy, dx) if abs(dx) > 1e-8 else (
                    math.pi / 2 if dy > 0 else -math.pi / 2)
                horiz_len = abs(dx)  # 水平投影长度（桩号增量）
                
                segments_info.append({
                    'type': 'line',
                    'p1': p1, 'p2': p2,
                    'chord': chord,
                    'slope_angle': slope_angle,  # 坡角 β (弧度)
                    'horiz_len': horiz_len,
                })
        
        # 第2步：提取关键变坡点
        # 策略：只在直线段→圆弧段、圆弧段→直线段的交界处以及首末端创建节点
        nodes = []
        
        # 起点节点
        x0, y0 = vertices[0]
        first_slope = segments_info[0].get('slope_angle', 0.0) if segments_info[0]['type'] == 'line' else 0.0
        nodes.append(LongitudinalNode(
            chainage=x0 + chainage_offset,
            elevation=y0,
            turn_type=TurnType.NONE,
            slope_after=first_slope,
        ))
        
        # 遍历每一段
        i = 0
        while i < len(segments_info):
            seg = segments_info[i]
            
            if seg['type'] == 'line':
                # 直线段：检查下一段是否也是直线段（折线型转弯）
                if i + 1 < len(segments_info):
                    next_seg = segments_info[i + 1]
                    if next_seg['type'] == 'line':
                        # 两段直线段相邻 → 折线型转弯
                        slope1 = seg['slope_angle']
                        slope2 = next_seg['slope_angle']
                        angle_diff = abs(math.degrees(slope2 - slope1))
                        
                        if angle_diff > 0.5:  # 大于0.5度视为有转角
                            px, py = seg['p2']
                            nodes.append(LongitudinalNode(
                                chainage=px + chainage_offset,
                                elevation=py,
                                turn_type=TurnType.FOLD,
                                turn_angle=angle_diff,
                                slope_before=slope1,
                                slope_after=slope2,
                            ))
                i += 1
                
            elif seg['type'] == 'arc':
                # 圆弧段（竖曲线）：确定前后坡角
                slope_before = 0.0
                slope_after = 0.0
                
                # 前方坡角：取前一个直线段的坡角
                if i > 0 and segments_info[i - 1]['type'] == 'line':
                    slope_before = segments_info[i - 1]['slope_angle']
                
                # 后方坡角：取后一个直线段的坡角
                if i + 1 < len(segments_info) and segments_info[i + 1]['type'] == 'line':
                    slope_after = segments_info[i + 1]['slope_angle']
                
                turn_angle = abs(math.degrees(slope_after - slope_before))
                
                # 圆弧起点作为变坡点节点
                px, py = seg['p1']
                nodes.append(LongitudinalNode(
                    chainage=px + chainage_offset,
                    elevation=py,
                    turn_type=TurnType.ARC,
                    vertical_curve_radius=seg['radius'],
                    turn_angle=turn_angle if turn_angle > 0.1 else seg['arc_angle_deg'],
                    slope_before=slope_before,
                    slope_after=slope_after,
                ))
                
                # 圆弧终点也记录（作为下一段的起点参考）
                ex, ey = seg['p2']
                nodes.append(LongitudinalNode(
                    chainage=ex + chainage_offset,
                    elevation=ey,
                    turn_type=TurnType.NONE,  # 终点不是转弯点
                    slope_before=slope_after,
                    slope_after=slope_after,
                ))
                
                i += 1
        
        # 终点节点（如果最后一个还没被添加）
        xn, yn = vertices[-1]
        last_chainage = xn + chainage_offset
        if not nodes or abs(nodes[-1].chainage - last_chainage) > 0.01:
            last_slope = 0.0
            if segments_info and segments_info[-1]['type'] == 'line':
                last_slope = segments_info[-1]['slope_angle']
            nodes.append(LongitudinalNode(
                chainage=last_chainage,
                elevation=yn,
                turn_type=TurnType.NONE,
                slope_before=last_slope,
            ))
        
        # 第3步：确保节点按桩号排序且无重复
        nodes.sort(key=lambda nd: nd.chainage)
        
        # 合并过于接近的节点（桩号差 < 0.01m）
        merged = [nodes[0]] if nodes else []
        for nd in nodes[1:]:
            if abs(nd.chainage - merged[-1].chainage) < 0.01:
                # 保留转弯信息较多的那个
                if nd.turn_type != TurnType.NONE and merged[-1].turn_type == TurnType.NONE:
                    merged[-1] = nd
            else:
                merged.append(nd)
        
        return merged
    
    @staticmethod
    def validate_dxf(file_path: str) -> Tuple[bool, str]:
        """
        校验DXF文件
        
        Args:
            file_path: DXF文件路径
            
        Returns:
            (是否有效, 消息)
        """
        try:
            import ezdxf
        except ImportError:
            return False, "未安装ezdxf库"
        
        try:
            doc = ezdxf.readfile(file_path)
            msp = doc.modelspace()
            
            # 检查是否存在多段线
            polylines = list(msp.query('LWPOLYLINE'))
            if not polylines:
                polylines = list(msp.query('POLYLINE'))
            
            if not polylines:
                return False, "文件中未找到多段线实体"
            
            return True, "DXF文件格式有效"
            
        except Exception as e:
            return False, f"文件读取失败: {str(e)}"


if __name__ == "__main__":
    # 测试代码
    print("DXF解析器测试")
    print("请提供DXF文件路径进行测试")
