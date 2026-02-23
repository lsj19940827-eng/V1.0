# -*- coding: utf-8 -*-
"""
横断面面积计算器

负责：
1. 将开挖边坡线叠加到地面线上，生成设计开挖轮廓
2. 用 Shoelace 公式计算开挖面积（总量 + 按地质层分）
3. 计算回填面积（贴坡回填 / 固定厚度）
"""

from __future__ import annotations
import math
import numpy as np
from typing import Optional

from 土石方计算.models.section import (
    SlopeGrade,
    ExcavationSlope,
    BackfillConfig,
    BackfillMode,
    DesignSection,
    GeologySectionProfile,
    SectionAreaResult,
    CrossSectionData,
)


class CrossSectionCalculator:
    """
    横断面面积计算器

    Usage
    -----
    >>> calc = CrossSectionCalculator()
    >>> cs = calc.compute(section_data, design_section, slope_config,
    ...                   invert_elevation, backfill_config)
    """

    def compute(
        self,
        section: CrossSectionData,
        design_sec: DesignSection,
        slope_config: ExcavationSlope,
        invert_elevation: float,
        backfill_cfg: Optional[BackfillConfig] = None,
    ) -> CrossSectionData:
        """
        计算单个横断面的设计线、开挖边坡线和面积。

        修改传入的 section（填充 design_points, excavation_boundary, area_result）
        并返回同一对象。

        Parameters
        ----------
        section : 已有地面线数据的横断面
        design_sec : 设计断面参数
        slope_config : 该桩号段的开挖边坡配置
        invert_elevation : 该断面的设计底高程（m）
        backfill_cfg : 回填配置
        """
        # 1. 生成设计断面轮廓（相对于中心线偏距坐标系）
        design_pts = self._build_design_outline(design_sec, invert_elevation)
        section.design_points = design_pts

        # 2. 生成开挖边坡线（从设计断面边缘延伸到地面）
        ground_pts = section.ground_points
        ground_elev_center = self._get_ground_elev_at_offset(ground_pts, 0.0)

        excav_pts = self._build_excavation_boundary(
            design_pts, ground_pts, slope_config, invert_elevation
        )
        section.excavation_boundary = excav_pts
        section.has_platform = slope_config.platform_enabled
        section.platform_width = slope_config.platform_width
        # 衬砌厚度：优先取设计断面的lining_thickness，其次取backfill固定厚度
        if design_sec.lining_thickness > 0:
            section.lining_thickness = design_sec.lining_thickness
        elif backfill_cfg and backfill_cfg.mode.value == "fixed_thickness":
            section.lining_thickness = backfill_cfg.thickness

        # 3. 计算面积
        area_result = self._compute_areas(
            ground_pts=ground_pts,
            design_pts=design_pts,
            excav_boundary=excav_pts,
            invert_elevation=invert_elevation,
            ground_elev_center=ground_elev_center,
            geology=section.geology_profile,
            backfill_cfg=backfill_cfg or BackfillConfig(),
            station=section.station,
        )
        section.area_result = area_result
        return section

    # ------------------------------------------------------------------
    # 设计断面轮廓线生成
    # ------------------------------------------------------------------

    @staticmethod
    def _build_design_outline(
        design: DesignSection,
        invert_elev: float,
    ) -> list[tuple[float, float]]:
        """
        生成梯形明渠设计断面轮廓（(offset, elevation) 列表，从左到右）。

        返回闭合多边形的顶点（不重复起点）：
        左上角 → 左下角（渠底左端）→ 右下角 → 右上角
        """
        b = design.bottom_width
        h = design.depth
        ml = design.inner_slope_left
        mr = design.inner_slope_right

        # 渠底左右端 offset
        left_bottom = -b / 2.0
        right_bottom = b / 2.0

        # 渠顶左右端 offset（口宽考虑内坡）
        left_top = left_bottom - ml * h
        right_top = right_bottom + mr * h

        pts = [
            (left_top,    invert_elev + h),   # 左上（渠口左）
            (left_bottom, invert_elev),         # 左下（渠底左）
            (right_bottom, invert_elev),        # 右下（渠底右）
            (right_top,   invert_elev + h),    # 右上（渠口右）
        ]
        return pts

    # ------------------------------------------------------------------
    # 开挖边坡线生成
    # ------------------------------------------------------------------

    @staticmethod
    def _build_excavation_boundary(
        design_pts: list[tuple[float, float]],
        ground_pts: list[tuple[float, float]],
        slope_cfg: ExcavationSlope,
        invert_elevation: float,
    ) -> list[tuple[float, float]]:
        """
        从设计断面口部延伸开挖边坡线到地面，生成完整开挖边界。

        开挖边界 = 左坡线（从渠口左向左上延伸） + 地面线（中间段） + 右坡线

        坡脚起点：设计断面渠口处（left_top, right_top）。
        分级放坡：按 SlopeGrade 序列逐级计算坡面端点 + 马道拐点，
                  最后一级延伸直到与地面线相交。
        """
        if not design_pts:
            return []

        # 渠口左/右起点
        left_toe = design_pts[0]    # (offset, elev)
        right_toe = design_pts[-1]

        # 左侧开挖坡线（从渠口向左上延伸，offset 递减）
        left_slope_pts = CrossSectionCalculator._trace_slope(
            start_offset=left_toe[0],
            start_elev=left_toe[1],
            ground_pts=ground_pts,
            grades=slope_cfg.left_grades,
            direction=-1,   # 向左
            platform_enabled=slope_cfg.platform_enabled,
            platform_width=slope_cfg.platform_width,
        )

        # 右侧开挖坡线（从渠口向右上延伸，offset 递增）
        right_slope_pts = CrossSectionCalculator._trace_slope(
            start_offset=right_toe[0],
            start_elev=right_toe[1],
            ground_pts=ground_pts,
            grades=slope_cfg.right_grades,
            direction=+1,   # 向右
            platform_enabled=slope_cfg.platform_enabled,
            platform_width=slope_cfg.platform_width,
        )

        # 左/右坡顶（地面交点）的偏距
        lx = left_slope_pts[-1][0] if left_slope_pts else left_toe[0]
        rx = right_slope_pts[-1][0] if right_slope_pts else right_toe[0]

        # 地面线段：取 [lx, rx] 范围内的地面点，并确保端点精确包含
        ground_segment: list[tuple[float, float]] = []
        if left_slope_pts:
            ground_segment.append(left_slope_pts[-1])   # 左地面交点
        ground_segment.extend(
            pt for pt in ground_pts if lx < pt[0] < rx
        )
        if right_slope_pts:
            ground_segment.append(right_slope_pts[-1])  # 右地面交点

        # 构建闭合开掘多边形（逆时针，面积为正）：
        #   左坡线（坐脚到左地面交点）
        #   → 地面线段（左到右）
        #   → 右坡线反向（右地面交点到坐脚）
        #   → 设计轮廓反向（右踏 → 左踏，封闭）
        polygon: list[tuple[float, float]] = []
        polygon.extend(left_slope_pts)                     # left_toe → left_ground_top
        polygon.extend(ground_segment[1:])                 # 跳过 left_ground_top 重复点
        polygon.extend(list(reversed(right_slope_pts))[1:]) # right_ground_top → right_toe
        polygon.extend(list(reversed(design_pts))[1:])     # right_toe → left_toe（跳过重复点）

        return polygon

    @staticmethod
    def _trace_slope(
        start_offset: float,
        start_elev: float,
        ground_pts: list[tuple[float, float]],
        grades: list[SlopeGrade],
        direction: int,   # +1 向右 / -1 向左
        platform_enabled: bool = False,
        platform_width: float = 2.0,
    ) -> list[tuple[float, float]]:
        """
        从坡脚沿分级边坡向上追踪，直到与地面线相交。

        返回坡线上的折点列表（不含起点）。
        """
        pts: list[tuple[float, float]] = [(start_offset, start_elev)]  # 包含起点
        cur_offset = start_offset
        cur_elev = start_elev

        for grade in grades:
            h = grade.height
            is_last = math.isinf(h)
            if not is_last:
                # 非最后一级：按高度计算坡面终点
                delta_h = h
                delta_offset = direction * grade.ratio * delta_h
                cur_offset += delta_offset
                cur_elev += delta_h
                pts.append((cur_offset, cur_elev))
                # 马道（水平平台）
                if grade.berm_width > 0:
                    cur_offset += direction * grade.berm_width
                    pts.append((cur_offset, cur_elev))
            else:
                # 最后一级：延伸到与地面线相交
                intersect = CrossSectionCalculator._find_slope_ground_intersect(
                    start_offset=cur_offset,
                    start_elev=cur_elev,
                    slope_ratio=grade.ratio,
                    direction=direction,
                    ground_pts=ground_pts,
                )
                if intersect is not None:
                    pts.append(intersect)
                    cur_offset, cur_elev = intersect
                else:
                    # 地面线范围不足，延伸到地面线端点
                    if direction > 0:
                        pts.append(ground_pts[-1])
                    else:
                        pts.append(ground_pts[0])
                break   # 最后一级完成

        # 坡顶施工便道（可选）
        if platform_enabled and not math.isinf(grades[-1].height):
            cur_offset += direction * platform_width
            pts.append((cur_offset, pts[-1][1]))

        return pts

    @staticmethod
    def _find_slope_ground_intersect(
        start_offset: float,
        start_elev: float,
        slope_ratio: float,
        direction: int,
        ground_pts: list[tuple[float, float]],
    ) -> Optional[tuple[float, float]]:
        """
        求坡线与地面折线的交点（线段求交法）。

        坡线方程：elev = start_elev + (x - start_offset) / slope_ratio（当 slope_ratio>0）
        方向确保只向指定方向延伸。
        """
        if slope_ratio < 1e-10:
            return None

        def slope_z_at(x: float) -> float:
            return start_elev + abs(x - start_offset) / slope_ratio

        # 遍历地面线各段，找第一个交点
        for i in range(len(ground_pts) - 1):
            x0, z0 = ground_pts[i]
            x1, z1 = ground_pts[i + 1]
            # 只处理坡线延伸方向的线段
            if direction > 0 and x1 < start_offset:
                continue
            if direction < 0 and x0 > start_offset:
                continue

            sz0 = slope_z_at(x0)
            sz1 = slope_z_at(x1)

            # 若坡线已低于地面，寻找交叉点
            if (z0 - sz0) * (z1 - sz1) <= 0:
                # 线性插值求交
                d_slope = sz1 - sz0
                d_ground = z1 - z0
                denom = d_ground - d_slope
                if abs(denom) < 1e-10:
                    continue
                t = (sz0 - z0) / denom
                t = max(0.0, min(1.0, t))
                xi = x0 + t * (x1 - x0)
                zi = z0 + t * (z1 - z0)
                # 确保交点在坡线延伸方向上（不在起点的反方向）
                if direction > 0 and xi < start_offset - 1e-6:
                    continue
                if direction < 0 and xi > start_offset + 1e-6:
                    continue
                return (xi, zi)

        return None

    # ------------------------------------------------------------------
    # 面积计算
    # ------------------------------------------------------------------

    def _compute_areas(
        self,
        ground_pts: list[tuple[float, float]],
        design_pts: list[tuple[float, float]],
        excav_boundary: list[tuple[float, float]],
        invert_elevation: float,
        ground_elev_center: float,
        geology: Optional[GeologySectionProfile],
        backfill_cfg: BackfillConfig,
        station: float,
    ) -> SectionAreaResult:
        """
        计算开掘面积（总量 + 地质分层）和回填面积。
        """
        cut_depth = ground_elev_center - invert_elevation

        # 开掘总面积：直接用开掘多边形（包含坐脚心线 + 边坡线 + 地面线）
        if excav_boundary and len(excav_boundary) >= 3:
            excav_total = self._shoelace_area(excav_boundary)
        else:
            # 备用：无边坡配置时用地面/设计直接围成的面积
            excav_total = self._area_between_lines(
                upper=ground_pts, lower=design_pts
            )

        # 地质分层面积
        excav_by_layer: dict[str, float] = {}
        if geology is not None and excav_total > 0:
            excav_by_layer = self._split_by_geology(
                ground_pts=ground_pts,
                design_pts=design_pts,
                geology=geology,
            )

        # 回填面积（设计线在地面线以下的区域）
        fill_area = self._compute_fill_area(
            ground_pts=ground_pts,
            design_pts=design_pts,
            backfill_cfg=backfill_cfg,
        )

        return SectionAreaResult(
            station=station,
            excavation_total=max(0.0, excav_total),
            excavation_by_layer=excav_by_layer,
            fill_area=max(0.0, fill_area),
            ground_elevation_center=ground_elev_center,
            design_invert_elevation=invert_elevation,
            cut_depth=cut_depth,
        )

    @staticmethod
    def _shoelace_area(pts: list[tuple[float, float]]) -> float:
        """
        Shoelace 公式计算多边形面积（带符号，顺时针为负）。
        """
        n = len(pts)
        if n < 3:
            return 0.0
        arr = np.array(pts)
        x, y = arr[:, 0], arr[:, 1]
        area = 0.5 * abs(
            np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)
        )
        return float(area)

    @staticmethod
    def _area_between_lines(
        upper: list[tuple[float, float]],
        lower: list[tuple[float, float]],
    ) -> float:
        """
        计算两条折线之间（upper 在上、lower 在下）围成的面积。
        使用 shapely 多边形求面积（鲁棒性好，自动处理交叉情况）。
        """
        try:
            from shapely.geometry import Polygon
            # 合并成闭合多边形：upper 从左到右，lower 从右到左
            poly_pts = list(upper) + list(reversed(lower))
            if len(poly_pts) < 3:
                return 0.0
            poly = Polygon(poly_pts)
            return float(poly.area) if poly.is_valid else 0.0
        except ImportError:
            # 退化为 Shoelace
            poly_pts = list(upper) + list(reversed(lower))
            return CrossSectionCalculator._shoelace_area(poly_pts)

    @staticmethod
    def _split_by_geology(
        ground_pts: list[tuple[float, float]],
        design_pts: list[tuple[float, float]],
        geology: GeologySectionProfile,
    ) -> dict[str, float]:
        """
        按地质分层线切分开挖面积。

        策略：对每一层，构造该层上下界折线，用 shapely 求与开挖区域的交集面积。
        """
        try:
            from shapely.geometry import Polygon, LineString
        except ImportError:
            return {}

        result: dict[str, float] = {}

        # 开挖区域多边形
        excav_poly_pts = list(ground_pts) + list(reversed(design_pts))
        if len(excav_poly_pts) < 3:
            return {}
        excav_poly = Polygon(excav_poly_pts)
        if not excav_poly.is_valid:
            excav_poly = excav_poly.buffer(0)

        # 各层界面高程（水平线近似）
        x_min = min(p[0] for p in ground_pts + design_pts) - 1.0
        x_max = max(p[0] for p in ground_pts + design_pts) + 1.0

        prev_z = min(p[1] for p in design_pts)   # 从底部开始
        for i, name in enumerate(geology.layer_names):
            top_z = geology.top_elevations[i]
            # 该层区域：水平带 [prev_z, top_z]
            layer_band = Polygon([
                (x_min, prev_z), (x_max, prev_z),
                (x_max, top_z),  (x_min, top_z),
            ])
            try:
                intersection = excav_poly.intersection(layer_band)
                result[name] = float(intersection.area)
            except Exception:
                result[name] = 0.0
            prev_z = top_z

        # 最顶层（从最高分层界面到地面线）
        if geology.layer_names:
            top_layer = geology.layer_names[-1]
            layer_band = Polygon([
                (x_min, prev_z),
                (x_max, prev_z),
                (x_max, max(p[1] for p in ground_pts) + 1.0),
                (x_min, max(p[1] for p in ground_pts) + 1.0),
            ])
            try:
                intersection = excav_poly.intersection(layer_band)
                result[top_layer] = (result.get(top_layer, 0.0)
                                     + float(intersection.area))
            except Exception:
                pass

        return result

    @staticmethod
    def _compute_fill_area(
        ground_pts: list[tuple[float, float]],
        design_pts: list[tuple[float, float]],
        backfill_cfg: BackfillConfig,
    ) -> float:
        """
        计算回填面积（设计线高于地面线的区域 + 贴坡回填）。
        """
        try:
            from shapely.geometry import Polygon
            # 设计线在地面线以上的区域
            poly_pts = list(design_pts) + list(reversed(ground_pts))
            if len(poly_pts) < 3:
                return 0.0
            poly = Polygon(poly_pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            base_fill = float(poly.area)
        except ImportError:
            base_fill = 0.0

        if not backfill_cfg.include_slope_backfill:
            return base_fill

        # 贴坡回填（固定厚度模式）
        if backfill_cfg.mode == BackfillMode.FIXED_THICKNESS:
            # 贴坡面积 ≈ 内坡面周长 × 厚度（简化近似）
            slope_perimeter = sum(
                math.hypot(design_pts[i + 1][0] - design_pts[i][0],
                           design_pts[i + 1][1] - design_pts[i][1])
                for i in range(len(design_pts) - 1)
            )
            base_fill += slope_perimeter * backfill_cfg.thickness

        return base_fill

    # ------------------------------------------------------------------
    # 辅助工具
    # ------------------------------------------------------------------

    @staticmethod
    def _get_ground_elev_at_offset(
        ground_pts: list[tuple[float, float]],
        offset: float = 0.0,
    ) -> float:
        """从地面线折点序列中插值指定偏距处的高程"""
        if not ground_pts:
            return float("nan")
        offsets = [p[0] for p in ground_pts]
        elevs = [p[1] for p in ground_pts]
        return float(np.interp(offset, offsets, elevs))
