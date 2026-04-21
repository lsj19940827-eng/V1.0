# -*- coding: utf-8 -*-
"""
倒虹吸水力计算软件 - DXF解析引擎
负责将非结构化的CAD几何图形转换为结构段数据和纵断面变坡点节点表
"""

import math
from typing import List, Tuple, Optional
from arc_geometry import (
    build_arc_geometry,
    build_plan_arc_geometry_from_context,
    clone_arc_geometry,
    reverse_arc_geometry,
)
from siphon_models import (
    StructureSegment, SegmentType, SegmentDirection, LongitudinalNode, TurnType,
    InletOutletShape, INLET_SHAPE_COEFFICIENTS, PlanFeaturePoint,
    GEOMETRY_STORAGE_DECIMALS,
)


class DxfParser:
    """DXF解析器类"""

    @staticmethod
    def _round_geometry_value(value: float) -> float:
        """统一几何字段的后台保留精度。"""
        return round(float(value), GEOMETRY_STORAGE_DECIMALS)
    
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
        center = DxfParser._compute_arc_center(p1, p2, bulge)
        
        return StructureSegment(
            segment_type=SegmentType.BEND,
            length=arc_length,
            radius=radius,
            angle=angle_deg,
            coordinates=[p1, p2],
            locked=True,
            start_elevation=p1[1],
            end_elevation=p2[1],
            arc_geometry=build_arc_geometry(
                kind="profile",
                mode="dxf_segment",
                start=p1,
                end=p2,
                center=center,
                radius=radius,
                sweep_rad=angle_rad,
                clockwise=(bulge < 0),
                start_chainage=p1[0],
                end_chainage=p2[0],
            ),
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
                        # 合并为折管（直管 + 当前段）
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
                    elif result and result[-1].segment_type == SegmentType.FOLD:
                        # 上一段已是折管（连续折点）：新折管以上一折管右端段的长度作为左半段
                        # 取上一折管末端两坐标作为本折管的起始直线长度
                        prev_fold = result[-1]
                        prev_end_coords = prev_fold.coordinates
                        prev_half_len = straight_segments[i - 1]['length']
                        fold_seg = StructureSegment(
                            segment_type=SegmentType.FOLD,
                            length=prev_half_len + seg['length'],
                            angle=angle_deg,
                            coordinates=[seg['p1'], seg['p2']],
                            locked=True,
                            start_elevation=seg['p1'][1],
                            end_elevation=seg['p2'][1]
                        )
                        result.append(fold_seg)
                    else:
                        # 单独创建折管（首段就是折管）
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
    def _extract_longitudinal_polyline_vertices(polyline) -> Tuple[List[Tuple[float, float]], List[float]]:
        """提取纵断面多段线顶点和凸度。"""
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
            raise ValueError("错误：无法解析多段线顶点")

        if len(vertices) < 2:
            raise ValueError("错误：多段线顶点数量不足（至少需要2个点）")
        return vertices, bulges

    @staticmethod
    def _normalize_longitudinal_polyline_direction(
        vertices: List[Tuple[float, float]],
        bulges: List[float],
    ) -> Tuple[List[Tuple[float, float]], List[float]]:
        """把纵断面多段线统一成桩号递增方向。"""
        if len(vertices) < 2:
            return vertices, bulges
        if vertices[-1][0] >= vertices[0][0]:
            return vertices, bulges

        reversed_vertices = list(reversed(vertices))
        segment_bulges = [
            float(bulges[i]) if i < len(bulges) else 0.0
            for i in range(len(vertices) - 1)
        ]
        reversed_bulges = [-segment_bulges[i] for i in range(len(segment_bulges) - 1, -1, -1)]
        reversed_bulges.append(0.0)
        return reversed_vertices, reversed_bulges

    @staticmethod
    def _is_preferred_longitudinal_layer(layer_name: str) -> bool:
        """判断图层名是否命中纵断面优先关键词。"""
        normalized_name = str(layer_name or "").upper()
        keywords = ("JQX", "纵剖", "纵断", "纵剖面")
        return any(keyword in normalized_name for keyword in keywords)

    @staticmethod
    def _is_local_coordinate_longitudinal_candidate(
        vertices: List[Tuple[float, float]],
    ) -> bool:
        """通过绝对坐标量级区分局部坐标和工程大坐标。"""
        max_abs_coord = max(
            max(abs(float(x)), abs(float(y)))
            for x, y in vertices
        )
        return max_abs_coord < 100000.0

    @staticmethod
    def _compute_longitudinal_polyline_path_length(
        vertices: List[Tuple[float, float]],
        bulges: List[float],
    ) -> float:
        """计算多段线路径总长，圆弧段按真实弧长计。"""
        total_length = 0.0
        for i in range(len(vertices) - 1):
            p1 = vertices[i]
            p2 = vertices[i + 1]
            bulge = float(bulges[i]) if i < len(bulges) else 0.0
            chord = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            if abs(bulge) > 1e-8 and chord > 1e-6:
                angle_rad = 4 * math.atan(abs(bulge))
                sin_half = math.sin(angle_rad / 2)
                radius = chord / (2 * sin_half) if sin_half > 1e-8 else chord / 2
                total_length += radius * angle_rad
            else:
                total_length += chord
        return float(total_length)

    @staticmethod
    def _is_longitudinal_polyline_closed(
        polyline,
        vertices: List[Tuple[float, float]],
    ) -> bool:
        """统一判断多段线是否闭合。"""
        closed_attr = getattr(polyline, "closed", None)
        if isinstance(closed_attr, bool) and closed_attr:
            return True

        is_closed_attr = getattr(polyline, "is_closed", None)
        try:
            if callable(is_closed_attr):
                if bool(is_closed_attr()):
                    return True
            elif isinstance(is_closed_attr, bool) and is_closed_attr:
                return True
        except Exception:
            pass

        if len(vertices) > 2:
            start = vertices[0]
            end = vertices[-1]
            if math.hypot(end[0] - start[0], end[1] - start[1]) < 1e-6:
                return True
        return False

    @staticmethod
    def _build_longitudinal_profile_candidate(polyline, entity_index: int) -> dict:
        """提取一个纵断面候选的排序信息和规范化几何。"""
        vertices, bulges = DxfParser._extract_longitudinal_polyline_vertices(polyline)
        normalized_vertices, normalized_bulges = (
            DxfParser._normalize_longitudinal_polyline_direction(vertices, bulges)
        )

        xs = [float(point[0]) for point in normalized_vertices]
        ys = [float(point[1]) for point in normalized_vertices]
        x_span = max(xs) - min(xs)
        y_span = max(ys) - min(ys)
        layer_name = str(getattr(polyline.dxf, "layer", "") or "")
        has_preferred_layer = DxfParser._is_preferred_longitudinal_layer(layer_name)
        is_local_coordinate = DxfParser._is_local_coordinate_longitudinal_candidate(
            normalized_vertices
        )
        is_closed = DxfParser._is_longitudinal_polyline_closed(polyline, vertices)
        has_obvious_horizontal_span = x_span >= max(10.0, y_span * 1.5)
        has_enough_x_span = x_span >= 20.0

        return {
            "entity_index": int(entity_index),
            "layer": layer_name,
            "vertices": normalized_vertices,
            "bulges": normalized_bulges,
            "x_span": float(x_span),
            "y_span": float(y_span),
            "path_length": DxfParser._compute_longitudinal_polyline_path_length(
                normalized_vertices,
                normalized_bulges,
            ),
            "vertex_count": len(normalized_vertices),
            "is_closed": is_closed,
            "has_preferred_layer": has_preferred_layer,
            "is_local_coordinate": is_local_coordinate,
            "has_obvious_horizontal_span": has_obvious_horizontal_span,
            "has_enough_x_span": has_enough_x_span,
            "is_eligible": (
                (not is_closed)
                and has_obvious_horizontal_span
                and has_enough_x_span
            ),
        }

    @staticmethod
    def _rank_longitudinal_profile_candidates(candidates: List[dict]) -> Tuple[List[dict], str]:
        """按统一规则排序纵断面候选。"""
        comparison_candidates = [item for item in candidates if item["is_eligible"]]
        comparison_mode = "eligible_only" if comparison_candidates else "fallback_all"

        def primary_sort_key(item: dict) -> tuple:
            return (
                0 if item["has_preferred_layer"] else 1,
                0 if item["is_local_coordinate"] else 1,
                -item["x_span"],
                -item["path_length"],
                -item["vertex_count"],
                item["entity_index"],
            )

        def fallback_sort_key(item: dict) -> tuple:
            return (
                0 if not item["is_closed"] else 1,
                0 if item["has_obvious_horizontal_span"] else 1,
                0 if item["has_enough_x_span"] else 1,
                0 if item["has_preferred_layer"] else 1,
                0 if item["is_local_coordinate"] else 1,
                -item["x_span"],
                -item["path_length"],
                -item["vertex_count"],
                item["entity_index"],
            )

        comparison_ids = {
            item["entity_index"]
            for item in (
                comparison_candidates if comparison_candidates else candidates
            )
        }
        for candidate in candidates:
            candidate["is_in_comparison_pool"] = (
                candidate["entity_index"] in comparison_ids
            )

        if comparison_mode == "eligible_only":
            secondary_candidates = [
                item for item in candidates if not item["is_in_comparison_pool"]
            ]
            ranked_candidates = sorted(comparison_candidates, key=primary_sort_key)
            ranked_candidates.extend(
                sorted(secondary_candidates, key=fallback_sort_key)
            )
            return ranked_candidates, comparison_mode

        return sorted(candidates, key=fallback_sort_key), comparison_mode

    @staticmethod
    def _needs_longitudinal_profile_confirmation(
        ranked_candidates: List[dict],
    ) -> bool:
        """当头两名非常接近时，给上层一个可确认的提示。"""
        if len(ranked_candidates) < 2:
            return False

        first = ranked_candidates[0]
        second = ranked_candidates[1]
        if not (first.get("is_in_comparison_pool") and second.get("is_in_comparison_pool")):
            return False
        if first["has_preferred_layer"] != second["has_preferred_layer"]:
            return False
        if first["is_local_coordinate"] != second["is_local_coordinate"]:
            return False

        def is_close(left: float, right: float, threshold: float = 0.05) -> bool:
            base = max(abs(left), abs(right), 1.0)
            return abs(left - right) / base <= threshold

        return (
            is_close(first["x_span"], second["x_span"])
            and is_close(first["path_length"], second["path_length"])
            and abs(first["vertex_count"] - second["vertex_count"]) <= 1
        )

    @staticmethod
    def _select_longitudinal_profile_candidate(
        file_path: str,
    ) -> Tuple[Optional[dict], Optional[dict], str]:
        """读取、排序并返回已选中的纵断面候选。"""
        try:
            import ezdxf
        except ImportError:
            return None, None, "错误：未安装ezdxf库，请运行 pip install ezdxf"

        try:
            doc = ezdxf.readfile(file_path)
        except Exception as e:
            return None, None, f"错误：无法读取DXF文件 - {str(e)}"

        msp = doc.modelspace()

        polylines = list(msp.query('LWPOLYLINE'))
        if not polylines:
            polylines = list(msp.query('POLYLINE'))
        if not polylines:
            return None, None, "错误：DXF文件中未找到多段线(LWPOLYLINE/POLYLINE)实体"

        candidates = []
        last_error = ""
        for entity_index, polyline in enumerate(polylines):
            try:
                candidate = DxfParser._build_longitudinal_profile_candidate(
                    polyline,
                    entity_index,
                )
            except ValueError as exc:
                last_error = str(exc)
                continue
            candidates.append(candidate)

        if not candidates:
            return None, None, last_error or "错误：未找到可用的纵断面多段线"

        ranked_candidates, comparison_mode = (
            DxfParser._rank_longitudinal_profile_candidates(candidates)
        )
        needs_confirmation = DxfParser._needs_longitudinal_profile_confirmation(
            ranked_candidates
        )

        selection = {
            "selected_rank_index": 0,
            "selected_entity_index": ranked_candidates[0]["entity_index"],
            "comparison_mode": comparison_mode,
            "needs_confirmation": needs_confirmation,
            "confirmation_rank_indices": [0, 1] if needs_confirmation else [],
            "candidates": [],
        }

        for rank_index, candidate in enumerate(ranked_candidates):
            selection["candidates"].append({
                "rank_index": rank_index,
                "entity_index": candidate["entity_index"],
                "layer": candidate["layer"],
                "x_span": candidate["x_span"],
                "y_span": candidate["y_span"],
                "path_length": candidate["path_length"],
                "vertex_count": candidate["vertex_count"],
                "is_closed": candidate["is_closed"],
                "has_preferred_layer": candidate["has_preferred_layer"],
                "is_local_coordinate": candidate["is_local_coordinate"],
                "has_obvious_horizontal_span": candidate["has_obvious_horizontal_span"],
                "has_enough_x_span": candidate["has_enough_x_span"],
                "is_eligible": candidate["is_eligible"],
                "is_in_comparison_pool": candidate["is_in_comparison_pool"],
            })

        return ranked_candidates[0], selection, ""

    @staticmethod
    def inspect_longitudinal_profile_candidates(file_path: str) -> Tuple[dict, str]:
        """返回纵断面候选排序结果，供上层在接近时决定是否需要确认。"""
        _selected_candidate, selection, error = (
            DxfParser._select_longitudinal_profile_candidate(file_path)
        )
        if selection is None:
            return {}, error
        return selection, ""

    @staticmethod
    def _load_longitudinal_polyline_geometry(
        file_path: str,
    ) -> Tuple[List[Tuple[float, float]], List[float], str]:
        """读取并返回统一选中的纵断面多段线几何。"""
        selected_candidate, _selection, error = (
            DxfParser._select_longitudinal_profile_candidate(file_path)
        )
        if not selected_candidate:
            return [], [], error
        return (
            list(selected_candidate["vertices"]),
            list(selected_candidate["bulges"]),
            "",
        )

    @staticmethod
    def get_longitudinal_profile_start_x(file_path: str) -> float:
        """返回规范化后的纵断面起点 X，用于计算桩号偏移。"""
        vertices, _bulges, error = DxfParser._load_longitudinal_polyline_geometry(file_path)
        if not vertices:
            raise ValueError(error or "错误：DXF文件中未找到纵断面数据")
        return float(vertices[0][0])

    @staticmethod
    def get_longitudinal_profile_raw_polyline(
        file_path: str,
        chainage_offset: float = 0.0,
    ) -> Tuple[dict, str]:
        """返回已套桩号偏移后的原始纵断面多段线几何。"""
        vertices, bulges, error = DxfParser._load_longitudinal_polyline_geometry(file_path)
        if not vertices:
            return {}, error

        shifted_vertices = [
            (float(x) + float(chainage_offset), float(y))
            for x, y in list(vertices or [])
        ]
        return (
            {
                "vertices": shifted_vertices,
                "bulges": [
                    float(bulges[index]) if index < len(bulges) else 0.0
                    for index in range(len(shifted_vertices))
                ],
                "source_kind": "selected_raw_polyline",
            },
            "",
        )
    
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
        vertices, bulges, error = DxfParser._load_longitudinal_polyline_geometry(file_path)
        if not vertices:
            return [], error
        
        # 构建变坡点节点表
        nodes = DxfParser._build_longitudinal_nodes(vertices, bulges, chainage_offset)
        
        msg = (f"成功解析纵断面DXF：{len(vertices)}个顶点 → "
               f"{len(nodes)}个变坡点节点")
        return nodes, msg
    
    @staticmethod
    def _compute_arc_center(p1: Tuple[float, float], p2: Tuple[float, float],
                            bulge: float) -> Tuple[float, float]:
        """DXF 圆弧弧心坐标 (Sc, Zc)。bulge>0 CCW，弧心在弦左侧；<0 CW 在右侧。"""
        S1, Z1 = p1; S2, Z2 = p2
        dS, dZ = S2 - S1, Z2 - Z1
        chord = math.sqrt(dS**2 + dZ**2)
        if chord < 1e-9:
            return (S1 + S2) / 2, (Z1 + Z2) / 2
        angle_rad = 4 * math.atan(abs(bulge))
        sin_half = math.sin(angle_rad / 2)
        if sin_half < 1e-9:
            return (S1 + S2) / 2, (Z1 + Z2) / 2
        radius = chord / (2 * sin_half)
        Sm, Zm = (S1 + S2) / 2, (Z1 + Z2) / 2
        perp_S, perp_Z = -dZ / chord, dS / chord
        d = math.sqrt(max(0.0, radius**2 - (chord / 2)**2))
        sign = 1.0 if bulge > 0 else -1.0
        return Sm + sign * d * perp_S, Zm + sign * d * perp_Z

    @staticmethod
    def _arc_tangent_slope(S: float, Z: float, Sc: float, Zc: float) -> float:
        """
        弧上点 (S,Z) 处切线坡角 β（弧度）。
        dZ/ds = -(S-Sc)/(Z-Zc) = tanβ，必须经 math.atan 转换为 β 弧度。
        注：不能用 atan2(-(S-Sc), Z-Zc)：当 Z<Zc（谷底弧）时 x分量<0，atan2会加±π错误。
        """
        denom = Z - Zc
        return 0.0 if abs(denom) < 1e-9 else math.atan(-(S - Sc) / denom)

    @staticmethod
    def _build_longitudinal_nodes(vertices: List[Tuple[float, float]],
                                   bulges: List[float],
                                   chainage_offset: float
                                   ) -> List[LongitudinalNode]:
        """
        从多段线顶点和凸度构建变坡点节点表

        v2.1 更新：
        - 圆弧段用弧心公式计算弧端切线坡角，不再仅依赖相邻直线段
        - 处理 arc→arc、arc→line、line→arc 全部过渡情形
        - ARC 节点存储弧心坐标 (arc_center_s, arc_center_z) 供 Z 轴精确插值
        """
        n = len(vertices)
        
        # 第1步：为每个段计算属性（直线或圆弧），圆弧段额外计算弧心和弧端切线坡角
        segments_info = []
        for i in range(n - 1):
            p1 = vertices[i]
            p2 = vertices[i + 1]
            bulge = bulges[i] if i < len(bulges) else 0.0
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            chord = math.sqrt(dx**2 + dy**2)
            
            if abs(bulge) > 1e-8 and chord > 1e-6:
                angle_rad = 4 * math.atan(abs(bulge))
                sin_half = math.sin(angle_rad / 2)
                radius = chord / (2 * sin_half) if sin_half > 1e-8 else chord / 2
                Sc, Zc = DxfParser._compute_arc_center(p1, p2, bulge)
                slope_start = DxfParser._arc_tangent_slope(p1[0], p1[1], Sc, Zc)
                slope_end   = DxfParser._arc_tangent_slope(p2[0], p2[1], Sc, Zc)
                segments_info.append({
                    'type': 'arc', 'p1': p1, 'p2': p2,
                    'radius': radius, 'arc_angle_deg': math.degrees(angle_rad),
                    'arc_len': radius * angle_rad, 'bulge': bulge,
                    'Sc': Sc, 'Zc': Zc,
                    'slope_start': slope_start, 'slope_end': slope_end,
                })
            else:
                slope_angle = math.atan2(dy, dx) if abs(dx) > 1e-8 else (
                    math.pi / 2 if dy > 0 else -math.pi / 2)
                segments_info.append({
                    'type': 'line', 'p1': p1, 'p2': p2,
                    'slope_angle': slope_angle,
                })
        
        # 第2步：提取关键变坡点
        # 通用规则：只要曲率突变（1/R 从 0 变为非 0，或切线不连续）就生成节点
        nodes = []
        
        # 起点节点
        x0, y0 = vertices[0]
        seg0 = segments_info[0]
        first_slope = seg0['slope_angle'] if seg0['type'] == 'line' else seg0['slope_start']
        nodes.append(LongitudinalNode(
            chainage=x0 + chainage_offset, elevation=y0,
            turn_type=TurnType.NONE, slope_after=first_slope,
        ))
        
        i = 0
        while i < len(segments_info):
            seg = segments_info[i]
            
            if seg['type'] == 'line':
                # 线→线：坡角差 > 0.5° → 折点
                if i + 1 < len(segments_info) and segments_info[i + 1]['type'] == 'line':
                    slope1 = seg['slope_angle']
                    slope2 = segments_info[i + 1]['slope_angle']
                    angle_diff = abs(math.degrees(slope2 - slope1))
                    if angle_diff > 0.5:
                        px, py = seg['p2']
                        nodes.append(LongitudinalNode(
                            chainage=px + chainage_offset, elevation=py,
                            turn_type=TurnType.FOLD, turn_angle=angle_diff,
                            slope_before=slope1, slope_after=slope2,
                        ))
                # 线→弧：弧起点切线 = 弧的 slope_start（已由弧心公式精确计算）
                # 不需要额外节点，由弧段开头的 ARC 节点处理
                i += 1
                
            elif seg['type'] == 'arc':
                # 确定进入弧段前的坡角
                if i > 0:
                    prev = segments_info[i - 1]
                    slope_before = prev['slope_angle'] if prev['type'] == 'line' else prev['slope_end']
                else:
                    slope_before = seg['slope_start']
                # 确定离开弧段后的坡角
                if i + 1 < len(segments_info):
                    nxt = segments_info[i + 1]
                    slope_after = nxt['slope_angle'] if nxt['type'] == 'line' else nxt['slope_start']
                else:
                    slope_after = seg['slope_end']
                
                turn_angle = abs(math.degrees(slope_after - slope_before))
                
                # 弧起点节点（ARC 类型）
                px, py = seg['p1']
                ex_ch = seg['p2'][0] + chainage_offset
                arc_theta = math.radians(seg['arc_angle_deg'])
                nodes.append(LongitudinalNode(
                    chainage=px + chainage_offset, elevation=py,
                    turn_type=TurnType.ARC,
                    vertical_curve_radius=seg['radius'],
                    turn_angle=turn_angle if turn_angle > 0.1 else seg['arc_angle_deg'],
                    slope_before=slope_before, slope_after=slope_after,
                    arc_center_s=seg['Sc'] + chainage_offset,
                    arc_center_z=seg['Zc'],
                    arc_end_chainage=ex_ch,
                    arc_theta_rad=arc_theta,
                ))
                
                # 弧终点节点（NONE 参考点，供区间端点插值用）
                ex, ey = seg['p2']
                nodes.append(LongitudinalNode(
                    chainage=ex + chainage_offset, elevation=ey,
                    turn_type=TurnType.NONE,
                    slope_before=seg['slope_end'], slope_after=seg['slope_end'],
                ))
                i += 1
        
        # 终点节点
        xn, yn = vertices[-1]
        last_chainage = xn + chainage_offset
        if not nodes or abs(nodes[-1].chainage - last_chainage) > 0.01:
            last = segments_info[-1]
            last_slope = last['slope_angle'] if last['type'] == 'line' else last['slope_end']
            nodes.append(LongitudinalNode(
                chainage=last_chainage, elevation=yn,
                turn_type=TurnType.NONE, slope_before=last_slope,
            ))
        
        # 第3步：排序并去重（保留转弯信息更丰富的节点）
        nodes.sort(key=lambda nd: nd.chainage)
        merged = [nodes[0]] if nodes else []
        for nd in nodes[1:]:
            if abs(nd.chainage - merged[-1].chainage) < 0.01:
                if nd.turn_type != TurnType.NONE and merged[-1].turn_type == TurnType.NONE:
                    merged[-1] = nd
            else:
                merged.append(nd)
        return merged
    
    # ==================================================================
    # 新增：平面多段线解析为PlanFeaturePoint + StructureSegment(PLAN)
    # ==================================================================

    @staticmethod
    def _compute_measurement_azimuth(dx: float, dy: float) -> float:
        """
        计算测量方位角（正北=0°顺时针），返回0-360°
        
        Args:
            dx: X方向增量（东向为正）
            dy: Y方向增量（北向为正）
        """
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return 0.0
        # 数学角：正东=0°逆时针
        math_angle_rad = math.atan2(dy, dx)
        # 转换为测量角：正北=0°顺时针
        meas_rad = math.pi / 2 - math_angle_rad
        meas_deg = math.degrees(meas_rad) % 360.0
        return meas_deg

    @staticmethod
    def _build_plan_segment_infos_from_points(
            plan_points: List[PlanFeaturePoint]) -> List[dict]:
        """
        兼容入口：从 PlanFeaturePoint 派生平面有向段信息。

        真实实现统一落在 _build_plan_seg_infos_from_feature_points，
        这里保留旧名称，避免其它调用点分叉。
        """
        return DxfParser._build_plan_seg_infos_from_feature_points(plan_points)

    @staticmethod
    def _rebuild_plan_geometry_from_segment_infos(
            seg_infos: List[dict]) -> Tuple[List[PlanFeaturePoint],
                                            List[StructureSegment],
                                            float]:
        """
        兼容入口：从平面有向段信息重建规范化平面几何。

        真实实现统一落在 _build_plan_geometry_from_seg_infos。
        """
        return DxfParser._build_plan_geometry_from_seg_infos(seg_infos)

    @staticmethod
    def parse_plan_polyline(file_path: str) -> Tuple[
            List['PlanFeaturePoint'], List[StructureSegment], str]:
        """
        解析平面DXF多段线（工程坐标：X=东，Y=北）
        
        同时生成 PlanFeaturePoint 列表（用于三维空间合并计算）
        和 StructureSegment 列表（direction=PLAN，用于表格显示和计算）。
        
        坐标约定：
        - X = 工程X坐标（东向），单位米
        - Y = 工程Y坐标（北向），单位米
        - bulge ≠ 0 的段 = 圆曲线（水平转弯弧）
        - bulge = 0 的段 = 直线段
        - 起点桩号 = 0
        
        Args:
            file_path: DXF文件路径
            
        Returns:
            (PlanFeaturePoint列表, StructureSegment列表, 消息)
        """
        try:
            import ezdxf
        except ImportError:
            return [], [], "错误：未安装ezdxf库，请运行 pip install ezdxf"
        
        try:
            doc = ezdxf.readfile(file_path)
        except Exception as e:
            return [], [], f"错误：无法读取DXF文件 - {str(e)}"
        
        msp = doc.modelspace()
        
        # 查找多段线
        polylines = list(msp.query('LWPOLYLINE'))
        if not polylines:
            polylines = list(msp.query('POLYLINE'))
        if not polylines:
            return [], [], "错误：DXF文件中未找到多段线(LWPOLYLINE/POLYLINE)实体"
        
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
            return [], [], "错误：无法解析多段线顶点"
        
        if len(vertices) < 2:
            return [], [], "错误：多段线顶点数量不足（至少需要2个点）"
        
        # 处理闭合多段线：如果首尾坐标几乎相同，去掉最后一个点
        if len(vertices) > 2:
            d_close = math.sqrt((vertices[-1][0] - vertices[0][0])**2 +
                                (vertices[-1][1] - vertices[0][1])**2)
            if d_close < 1e-6:
                vertices = vertices[:-1]
                bulges = bulges[:-1]
        
        if len(vertices) < 2:
            return [], [], "错误：去除闭合重复点后顶点不足"
        
        n = len(vertices)
        
        # ---- 第1步：计算每个段的几何属性 ----
        seg_infos = []  # 每段: {type, p1, p2, length, chord, bulge, radius, angle_rad, ...}
        for i in range(n - 1):
            p1 = vertices[i]
            p2 = vertices[i + 1]
            bulge = bulges[i] if i < len(bulges) else 0.0
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            chord = math.sqrt(dx**2 + dy**2)
            
            if abs(bulge) > 1e-8 and chord > 1e-6:
                # 圆弧段
                angle_rad = 4 * math.atan(abs(bulge))
                sin_half = math.sin(angle_rad / 2)
                radius = chord / (2 * sin_half) if sin_half > 1e-8 else chord / 2
                arc_length = radius * angle_rad
                center = DxfParser._compute_arc_center(p1, p2, bulge)
                seg_infos.append({
                    'type': 'arc', 'p1': p1, 'p2': p2,
                    'chord': chord, 'bulge': bulge,
                    'radius': radius, 'angle_rad': angle_rad,
                    'length': arc_length,
                    'center': center,
                    'clockwise': bulge < 0,
                    'mode': 'dxf_segment',
                })
            else:
                # 直线段
                if chord < 1e-6:
                    continue  # 跳过退化段
                seg_infos.append({
                    'type': 'line', 'p1': p1, 'p2': p2,
                    'chord': chord, 'length': chord,
                })
        
        if not seg_infos:
            return [], [], "错误：解析后无有效段"
        
        # ---- 第2步：计算每个段的方向向量（用于折角检测）----
        for si in seg_infos:
            dx = si['p2'][0] - si['p1'][0]
            dy = si['p2'][1] - si['p1'][1]
            d = math.sqrt(dx**2 + dy**2)
            if d > 1e-9:
                si['dir'] = (dx / d, dy / d)
            else:
                si['dir'] = (1.0, 0.0)
        
        # ---- 第3步：生成 PlanFeaturePoint 列表和 StructureSegment 列表 ----
        plan_points, plan_segments, _total_length = DxfParser._build_plan_geometry_from_seg_infos(
            seg_infos
        )
        
        msg = (f"成功解析平面DXF：{n}个顶点 → "
               f"{len(plan_points)}个特征点, {len(plan_segments)}个平面段")
        return plan_points, plan_segments, msg

    @staticmethod
    def _build_plan_seg_infos_from_feature_points(
        plan_points: List['PlanFeaturePoint']
    ) -> list:
        """
        从 PlanFeaturePoint 列表恢复有向平面段信息。

        用于导入后“平面反向”时以特征点为单一真实来源重建平面段。
        """
        if not plan_points or len(plan_points) < 2:
            return []

        ordered_points = sorted(
            enumerate(plan_points),
            key=lambda item: (item[1].chainage, item[1].ip_index, item[0]),
        )
        pts = [item[1] for item in ordered_points]

        seg_infos = []
        for idx in range(len(pts) - 1):
            start = pts[idx]
            end = pts[idx + 1]
            p1 = (float(start.x), float(start.y))
            p2 = (float(end.x), float(end.y))
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            chord = math.sqrt(dx**2 + dy**2)
            chainage_delta = float(end.chainage) - float(start.chainage)

            if (start.turn_type == TurnType.ARC and
                    float(start.turn_radius) > 0 and
                    float(start.turn_angle) > 0):
                angle_rad = math.radians(float(start.turn_angle))
                radius = float(start.turn_radius)
                length = chainage_delta if chainage_delta > 1e-6 else radius * angle_rad
                arc_geometry = clone_arc_geometry(start.arc_geometry)
                if arc_geometry is not None:
                    start_pt = tuple(arc_geometry.get('start', []))
                    end_pt = tuple(arc_geometry.get('end', []))
                    if start_pt != p1 or end_pt != p2:
                        arc_geometry = None
                if arc_geometry is None:
                    prev_point = None
                    if idx > 0:
                        prev = pts[idx - 1]
                        prev_point = (float(prev.x), float(prev.y))
                    next_point = None
                    if idx + 2 < len(pts):
                        nxt2 = pts[idx + 2]
                        next_point = (float(nxt2.x), float(nxt2.y))
                    arc_geometry = build_plan_arc_geometry_from_context(
                        start=p1,
                        end=p2,
                        radius=radius,
                        sweep_rad=angle_rad,
                        start_chainage=float(start.chainage),
                        end_chainage=float(end.chainage),
                        prev_point=prev_point,
                        next_point=next_point,
                        mode='manual_rebuilt',
                    )
                seg_infos.append({
                    'type': 'arc',
                    'p1': p1,
                    'p2': p2,
                    'chord': chord,
                    'radius': radius,
                    'angle_rad': angle_rad,
                    'length': length,
                    'dir': DxfParser._get_direction(p1, p2),
                    'azimuth_meas_deg': DxfParser._compute_measurement_azimuth(dx, dy),
                    'source_ip_index': start.ip_index,
                    'arc_geometry': arc_geometry,
                    'mode': arc_geometry.get('mode', 'manual_rebuilt') if arc_geometry else 'manual_rebuilt',
                })
            else:
                length = chainage_delta if chainage_delta > 1e-6 else chord
                if chord < 1e-6 and length < 1e-6:
                    continue
                seg_infos.append({
                    'type': 'line',
                    'p1': p1,
                    'p2': p2,
                    'chord': chord,
                    'length': length,
                    'dir': DxfParser._get_direction(p1, p2),
                    'azimuth_meas_deg': DxfParser._compute_measurement_azimuth(dx, dy),
                    'source_ip_index': start.ip_index,
                })

        return seg_infos

    @staticmethod
    def _resolve_plan_arc_geometry(
        si: dict,
        start_chainage: float,
        end_chainage: float,
        prev_point: Optional[Tuple[float, float]] = None,
        next_point: Optional[Tuple[float, float]] = None,
    ) -> Optional[dict]:
        """把平面段信息统一解析成规范化圆弧真源。"""
        arc_geometry = clone_arc_geometry(si.get('arc_geometry'))
        if arc_geometry is not None:
            return build_arc_geometry(
                kind=arc_geometry.get('kind', 'plan') or 'plan',
                mode=arc_geometry.get('mode', si.get('mode', 'manual_rebuilt')) or 'manual_rebuilt',
                start=si['p1'],
                end=si['p2'],
                center=arc_geometry.get('center'),
                radius=arc_geometry.get('radius', si.get('radius', 0.0)),
                sweep_rad=arc_geometry.get('sweep_rad', si.get('angle_rad', 0.0)),
                clockwise=arc_geometry.get('clockwise', False),
                start_chainage=start_chainage,
                end_chainage=end_chainage,
            )

        if si.get('center') is not None and si.get('clockwise') is not None:
            return build_arc_geometry(
                kind="plan",
                mode=si.get('mode', 'dxf_segment') or 'dxf_segment',
                start=si['p1'],
                end=si['p2'],
                center=si.get('center'),
                radius=si.get('radius', 0.0),
                sweep_rad=si.get('angle_rad', 0.0),
                clockwise=si.get('clockwise', False),
                start_chainage=start_chainage,
                end_chainage=end_chainage,
            )

        return build_plan_arc_geometry_from_context(
            start=si['p1'],
            end=si['p2'],
            radius=si.get('radius', 0.0),
            sweep_rad=si.get('angle_rad', 0.0),
            start_chainage=start_chainage,
            end_chainage=end_chainage,
            prev_point=prev_point,
            next_point=next_point,
            mode=si.get('mode', 'manual_rebuilt') or 'manual_rebuilt',
        )

    @staticmethod
    def _build_plan_geometry_from_seg_infos(
        seg_infos: list
    ) -> Tuple[List['PlanFeaturePoint'], List[StructureSegment], float]:
        """从有向平面段信息构建规范化平面特征点、平面段和平面总长。"""
        if not seg_infos:
            return [], [], 0.0

        plan_points = []
        chainage = 0.0

        for i, si in enumerate(seg_infos):
            px, py = si['p1']
            dx_seg = si['p2'][0] - si['p1'][0]
            dy_seg = si['p2'][1] - si['p1'][1]
            azimuth = DxfParser._compute_measurement_azimuth(dx_seg, dy_seg)

            turn_type = TurnType.NONE
            turn_angle = 0.0
            turn_radius = 0.0
            arc_geometry = None

            if si['type'] == 'arc':
                turn_type = TurnType.ARC
                turn_angle = math.degrees(si['angle_rad'])
                turn_radius = si['radius']
                prev_point = seg_infos[i - 1]['p1'] if i > 0 else None
                next_point = seg_infos[i + 1]['p2'] if i + 1 < len(seg_infos) else None
                arc_geometry = DxfParser._resolve_plan_arc_geometry(
                    si,
                    start_chainage=chainage,
                    end_chainage=chainage + si['length'],
                    prev_point=prev_point,
                    next_point=next_point,
                )
            elif i > 0 and seg_infos[i - 1]['type'] == 'line' and si['type'] == 'line':
                prev_dir = seg_infos[i - 1]['dir']
                curr_dir = si['dir']
                dot = prev_dir[0] * curr_dir[0] + prev_dir[1] * curr_dir[1]
                dot = max(-1.0, min(1.0, dot))
                fold_angle = math.degrees(math.acos(dot))
                if fold_angle > 1.0:
                    turn_type = TurnType.FOLD
                    turn_angle = fold_angle

            plan_points.append(PlanFeaturePoint(
                chainage=DxfParser._round_geometry_value(chainage),
                x=px,
                y=py,
                azimuth_meas_deg=DxfParser._round_geometry_value(azimuth),
                turn_radius=DxfParser._round_geometry_value(turn_radius),
                turn_angle=DxfParser._round_geometry_value(turn_angle),
                turn_type=turn_type,
                ip_index=i,
                arc_geometry=arc_geometry,
            ))
            chainage += si['length']

        last_si = seg_infos[-1]
        last_px, last_py = last_si['p2']
        last_dx = last_si['p2'][0] - last_si['p1'][0]
        last_dy = last_si['p2'][1] - last_si['p1'][1]
        last_azimuth = DxfParser._compute_measurement_azimuth(last_dx, last_dy)
        plan_points.append(PlanFeaturePoint(
            chainage=DxfParser._round_geometry_value(chainage),
            x=last_px,
            y=last_py,
            azimuth_meas_deg=DxfParser._round_geometry_value(last_azimuth),
            turn_type=TurnType.NONE,
            ip_index=len(seg_infos),
        ))

        plan_segments = DxfParser._build_plan_segments(seg_infos)
        return plan_points, plan_segments, DxfParser._round_geometry_value(chainage)

    @staticmethod
    def build_plan_geometry_from_feature_points(
        plan_points: List['PlanFeaturePoint']
    ) -> Tuple[List['PlanFeaturePoint'], List[StructureSegment], float]:
        """从现有 PlanFeaturePoint 重建规范化平面几何。"""
        seg_infos = DxfParser._build_plan_seg_infos_from_feature_points(plan_points)
        return DxfParser._build_plan_geometry_from_seg_infos(seg_infos)

    @staticmethod
    def reverse_plan_geometry(
        plan_points: List['PlanFeaturePoint']
    ) -> Tuple[List['PlanFeaturePoint'], List[StructureSegment], float]:
        """反向当前平面特征点，并重建规范化平面几何。"""
        seg_infos = DxfParser._build_plan_seg_infos_from_feature_points(plan_points)
        if not seg_infos:
            return [], [], 0.0

        reversed_infos = []
        for idx, si in enumerate(reversed(seg_infos)):
            p1 = si['p2']
            p2 = si['p1']
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            reversed_si = dict(si)
            reversed_si['p1'] = p1
            reversed_si['p2'] = p2
            reversed_si['dir'] = DxfParser._get_direction(p1, p2)
            reversed_si['azimuth_meas_deg'] = DxfParser._compute_measurement_azimuth(dx, dy)
            reversed_si['source_ip_index'] = idx
            if si.get('type') == 'arc':
                reversed_si['arc_geometry'] = reverse_arc_geometry(si.get('arc_geometry'))
                if si.get('clockwise') is not None:
                    reversed_si['clockwise'] = not bool(si.get('clockwise'))
            reversed_infos.append(reversed_si)

        return DxfParser._build_plan_geometry_from_seg_infos(reversed_infos)

    @staticmethod
    def _build_plan_segments(seg_infos: list) -> List[StructureSegment]:
        """
        从平面段信息列表构建 StructureSegment 列表（direction=PLAN）
        
        不生成进水口/出水口（平面段不涉及）。
        """
        segments = []
        temp_straight = []
        chainage = 0.0
        
        for i, si in enumerate(seg_infos):
            seg_start_chainage = chainage
            seg_end_chainage = chainage + si['length']
            if si['type'] == 'arc':
                # 处理之前累积的直线段
                if temp_straight:
                    segments.extend(
                        DxfParser._process_plan_straight_segments(temp_straight))
                    temp_straight = []
                
                # 弯管段
                prev_point = seg_infos[i - 1]['p1'] if i > 0 else None
                next_point = seg_infos[i + 1]['p2'] if i + 1 < len(seg_infos) else None
                segments.append(StructureSegment(
                    segment_type=SegmentType.BEND,
                    length=DxfParser._round_geometry_value(si['length']),
                    radius=DxfParser._round_geometry_value(si['radius']),
                    angle=DxfParser._round_geometry_value(math.degrees(si['angle_rad'])),
                    coordinates=[si['p1'], si['p2']],
                    locked=True,
                    direction=SegmentDirection.PLAN,
                    source_ip_index=si.get('source_ip_index'),
                    arc_geometry=DxfParser._resolve_plan_arc_geometry(
                        si,
                        start_chainage=seg_start_chainage,
                        end_chainage=seg_end_chainage,
                        prev_point=prev_point,
                        next_point=next_point,
                    ),
                ))
            else:
                # 直线段 — 累积后统一处理折管检测
                temp_straight.append(si)
            chainage = seg_end_chainage
        
        # 处理剩余直线段
        if temp_straight:
            segments.extend(
                DxfParser._process_plan_straight_segments(temp_straight))
        
        return segments

    @staticmethod
    def _process_plan_straight_segments(straight_infos: list) -> List[StructureSegment]:
        """
        处理连续平面直线段，检测折管。
        逻辑与 _process_straight_segments 类似，但 direction=PLAN、无高程。
        """
        if not straight_infos:
            return []
        
        result = []
        
        for i, si in enumerate(straight_infos):
            if i == 0:
                result.append(StructureSegment(
                    segment_type=SegmentType.STRAIGHT,
                    length=DxfParser._round_geometry_value(si['length']),
                    coordinates=[si['p1'], si['p2']],
                    locked=True,
                    direction=SegmentDirection.PLAN,
                    source_ip_index=si.get('source_ip_index'),
                ))
            else:
                prev_dir = straight_infos[i - 1]['dir']
                curr_dir = si['dir']
                dot = prev_dir[0] * curr_dir[0] + prev_dir[1] * curr_dir[1]
                dot = max(-1.0, min(1.0, dot))
                angle_deg = math.degrees(math.acos(dot))
                
                if angle_deg > 1.0:
                    # 折管
                    if result and result[-1].segment_type == SegmentType.STRAIGHT:
                        prev_seg = result[-1]
                        fold_seg = StructureSegment(
                            segment_type=SegmentType.FOLD,
                            length=DxfParser._round_geometry_value(prev_seg.length + si['length']),
                            angle=DxfParser._round_geometry_value(angle_deg),
                            coordinates=prev_seg.coordinates + [si['p2']],
                            locked=True,
                            direction=SegmentDirection.PLAN,
                            source_ip_index=si.get('source_ip_index'),
                        )
                        result[-1] = fold_seg
                    elif result and result[-1].segment_type == SegmentType.FOLD:
                        prev_half_len = straight_infos[i - 1]['length']
                        fold_seg = StructureSegment(
                            segment_type=SegmentType.FOLD,
                            length=DxfParser._round_geometry_value(prev_half_len + si['length']),
                            angle=DxfParser._round_geometry_value(angle_deg),
                            coordinates=[si['p1'], si['p2']],
                            locked=True,
                            direction=SegmentDirection.PLAN,
                            source_ip_index=si.get('source_ip_index'),
                        )
                        result.append(fold_seg)
                    else:
                        result.append(StructureSegment(
                            segment_type=SegmentType.FOLD,
                            length=DxfParser._round_geometry_value(si['length']),
                            angle=DxfParser._round_geometry_value(angle_deg),
                            coordinates=[si['p1'], si['p2']],
                            locked=True,
                            direction=SegmentDirection.PLAN,
                            source_ip_index=si.get('source_ip_index'),
                        ))
                else:
                    result.append(StructureSegment(
                        segment_type=SegmentType.STRAIGHT,
                        length=DxfParser._round_geometry_value(si['length']),
                        coordinates=[si['p1'], si['p2']],
                        locked=True,
                        direction=SegmentDirection.PLAN,
                        source_ip_index=si.get('source_ip_index'),
                    ))
        
        return result

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
