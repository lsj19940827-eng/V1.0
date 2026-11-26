# -*- coding: utf-8 -*-
"""无衬砌全挖梯形原型及简单折线面积计算；施工结构使用显式区域算子。"""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Optional
from shapely.geometry import Polygon, box
from 土石方计算.models.section import (
    SlopeGrade, ExcavationSlope, BackfillConfig, DesignSection, ChannelType,
    GeologySectionProfile, SectionAreaResult, CrossSectionData,
)

_TOL = 1e-9


def _validated_line(points, name, *, allow_vertical=False):
    """要求有限、按偏距排序的折线，禁止缺地形时端值外推。"""
    try:
        result = [(float(x), float(z)) for x, z in points]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}必须为二维点序列") from exc
    if len(result) < 2 or any(not math.isfinite(v) for p in result for v in p):
        raise ValueError(f"{name}至少需要两个有限坐标点")
    for first, second in zip(result, result[1:]):
        if second[0] < first[0] or (second[0] == first[0] and not allow_vertical):
            raise ValueError(f"{name}偏距必须递增")
    if result[-1][0] <= result[0][0]:
        raise ValueError(f"{name}必须具有正的水平范围")
    return result


def _line_piece_values(points, left, right, *, start_index=0):
    """按区间覆盖选择非竖直线段，不依赖可表示的浮点中点。"""
    for index in range(start_index, len(points)-1):
        x0, z0 = points[index]
        x1, z1 = points[index+1]
        if x0 < x1 and x0 <= left < right <= x1:
            def value(x):
                if x == x0:
                    return z0
                if x == x1:
                    return z1
                return z0+(z1-z0)*((x-x0)/(x1-x0))
            return value(left), value(right)
    raise ValueError("折线未覆盖计算区间")


@dataclass(frozen=True)
class SignedLineAreas:
    """原地面高于设计线为挖，低于设计线为填。"""
    excavation_area: float
    fill_area: float


def signed_line_areas(ground_points, design_points) -> SignedLineAreas:
    """在设计线偏距范围逐段积分，交叉段在差值零点拆分。

    只比较两条明确的线，不推定渠堤、结构厚度或管涵内部回填。
    地面须覆盖完整设计范围，设计线可含零水平宽度的垂直段。
    """
    ground = _validated_line(ground_points, "地面线")
    design = _validated_line(design_points, "设计线", allow_vertical=True)
    left, right = design[0][0], design[-1][0]
    if ground[0][0] > left or ground[-1][0] < right:
        raise ValueError("地面线未覆盖完整设计断面，禁止端值外推")
    offsets = sorted({left, right, *(x for x, _ in ground+design if left < x < right)})
    cut = fill = 0.0
    ground_index = design_index = 0
    for a, b in zip(offsets, offsets[1:]):
        # 偏距单调递增，每条线只向前查找一次；同偏距的竖直壁取右侧极限。
        while ground_index+1 < len(ground)-1 and ground[ground_index+1][0] <= a:
            ground_index += 1
        while design_index+1 < len(design)-1 and design[design_index+1][0] <= a:
            design_index += 1
        ga, gb = _line_piece_values(ground, a, b, start_index=ground_index)
        da, db = _line_piece_values(design, a, b, start_index=design_index)
        d0, d1, width = ga-da, gb-db, b-a
        if d0 >= 0 and d1 >= 0:
            cut += width*(d0+d1)/2
        elif d0 <= 0 and d1 <= 0:
            fill -= width*(d0+d1)/2
        else:
            first_width = width*abs(d0)/(abs(d0)+abs(d1))
            first_area = first_width*abs(d0)/2
            second_area = (width-first_width)*abs(d1)/2
            if d0 > 0:
                cut += first_area
                fill += second_area
            else:
                fill += first_area
                cut += second_area
    return SignedLineAreas(cut, fill)


class CrossSectionCalculator:
    """只保留无衬砌梯形全挖原型，不将净空断面冒充施工外边界。"""

    def compute(self, section: CrossSectionData, design_sec: DesignSection,
                slope_config: ExcavationSlope, invert_elevation: float,
                backfill_cfg: Optional[BackfillConfig] = None) -> CrossSectionData:
        design = self._build_design_outline(design_sec, invert_elevation)
        ground = _validated_line(section.ground_points, "地面线")
        self._validate_backfill(backfill_cfg)
        if slope_config.platform_enabled:
            raise ValueError("施工便道需要显式施工区域，原型不推定便道挖填边界")
        areas = signed_line_areas(ground, design)
        if areas.fill_area > _TOL:
            raise ValueError("半填或全填明渠缺少渠堤外边坡等施工边界，请使用显式施工区域")
        boundary = self._build_excavation_boundary(design, ground, slope_config, invert_elevation)
        ground_center = self._get_ground_elev_at_offset(ground, 0.0)
        result = self._compute_areas(ground, design, boundary, invert_elevation,
                                     ground_center, section.geology_profile, backfill_cfg,
                                     section.station)
        # 全部检查成功后才写入，失败不残留部分新结果。
        section.design_points = design
        section.excavation_boundary = boundary
        section.has_platform = False
        section.platform_width = 0.0
        section.lining_thickness = 0.0
        section.area_result = result
        return section

    @staticmethod
    def _validate_backfill(config):
        if config is None:
            return
        if not math.isfinite(config.thickness) or config.thickness < 0:
            raise ValueError("回填厚度必须为非负有限值")
        if config.include_slope_backfill or config.thickness > 0:
            raise ValueError("固定厚度或贴坡回填需要显式材料区域，不再以周长乘厚度估算")

    @staticmethod
    def _build_design_outline(design: DesignSection, invert_elev: float):
        if design.channel_type != ChannelType.TRAPEZOIDAL:
            raise ValueError("原型仅支持梯形明渠；暗涵、圆管等必须提供显式结构外包和施工区域")
        values = [design.bottom_width, design.depth, design.inner_slope_left,
                  design.inner_slope_right, design.lining_thickness, design.freeboard, invert_elev]
        if any(not math.isfinite(v) for v in values):
            raise ValueError("设计断面参数必须为有限值")
        if design.bottom_width <= 0 or design.depth <= 0:
            raise ValueError("渠底宽和完整渠深必须大于零")
        if min(design.inner_slope_left, design.inner_slope_right) < 0:
            raise ValueError("内坡比不能为负")
        if design.lining_thickness != 0 or design.extra_params:
            raise ValueError("结构厚度或扩展结构参数需要显式施工区域")
        if design.freeboard != 0:
            raise ValueError("原型 depth 必须为完整渠深，不能另加含义未明确的超高")
        b, h = design.bottom_width, design.depth
        return [(-b/2-design.inner_slope_left*h, invert_elev+h),
                (-b/2, invert_elev), (b/2, invert_elev),
                (b/2+design.inner_slope_right*h, invert_elev+h)]

    @staticmethod
    def _build_excavation_boundary(design_pts, ground_pts, slope_cfg, invert_elevation):
        if not design_pts:
            raise ValueError("设计断面不能为空")
        left = CrossSectionCalculator._trace_slope(*design_pts[0], ground_pts,
                                                  slope_cfg.left_grades, -1,
                                                  slope_cfg.platform_enabled, slope_cfg.platform_width)
        right = CrossSectionCalculator._trace_slope(*design_pts[-1], ground_pts,
                                                   slope_cfg.right_grades, 1,
                                                   slope_cfg.platform_enabled, slope_cfg.platform_width)
        middle = [p for p in ground_pts if left[-1][0] < p[0] < right[-1][0]]
        polygon = left+middle+list(reversed(right))+list(reversed(design_pts))[1:]
        shape = Polygon(polygon)
        if not shape.is_valid:
            raise ValueError("开挖边界自交或无效，请检查地形及分级边坡")
        return polygon

    @staticmethod
    def _ray_ground_hit(start, vector, ground_pts, max_distance=math.inf):
        """取射线参数最近的非负交点，遍历顺序不影响左侧交点选择。"""
        hits = []
        px, pz = start
        vx, vz = vector
        for (x0,z0),(x1,z1) in zip(ground_pts,ground_pts[1:]):
            wx, wz = x1-x0, z1-z0
            determinant = vx*wz-vz*wx
            dx, dz = x0-px, z0-pz
            if abs(determinant) < 1e-12:
                if abs(dx*vz-dz*vx) > _TOL:
                    continue
                norm = vx*vx+vz*vz
                params = [((x-px)*vx+(z-pz)*vz)/norm for x,z in ((x0,z0),(x1,z1))]
                if max(params) < -_TOL:
                    continue
                t = max(0.0,min(params))
            else:
                t = (dx*wz-dz*wx)/determinant
                u = (dx*vz-dz*vx)/determinant
                if not -_TOL <= u <= 1+_TOL or t < -_TOL:
                    continue
                t = max(0.0,t)
            if t <= max_distance+_TOL:
                hits.append((t,(px+t*vx,pz+t*vz)))
        return min(hits,key=lambda item:item[0]) if hits else None

    @staticmethod
    def _trace_slope(start_offset, start_elev, ground_pts, grades, direction,
                     platform_enabled=False, platform_width=2.0):
        ground = _validated_line(ground_pts,"地面线")
        if direction not in (-1,1) or not grades:
            raise ValueError("边坡方向必须为正负一，且至少有一级边坡")
        if platform_enabled:
            raise ValueError("施工便道需要显式施工区域")
        if not all(math.isfinite(v) for v in (start_offset,start_elev)):
            raise ValueError("坡脚坐标必须为有限值")
        for index,grade in enumerate(grades):
            if (not math.isfinite(grade.ratio) or grade.ratio < 0
                    or math.isnan(grade.height) or grade.height <= 0
                    or not math.isfinite(grade.berm_width) or grade.berm_width < 0):
                raise ValueError("边坡比、级高或马道宽度无效")
            if math.isinf(grade.height) and index != len(grades)-1:
                raise ValueError("无限级高只能出现在最后一级")
        ground_start = CrossSectionCalculator._get_ground_elev_at_offset(ground,start_offset)
        if ground_start < start_elev-_TOL:
            raise ValueError("坡脚高于地面，需要明确填方边界")
        current = (start_offset,start_elev)
        points = [current]
        if abs(ground_start-start_elev) <= _TOL:
            return points
        for grade in grades:
            vector = (direction*grade.ratio,1.0)
            hit = CrossSectionCalculator._ray_ground_hit(current,vector,ground,grade.height)
            if hit is not None:
                if hit[0] > _TOL:
                    points.append(hit[1])
                return points
            if math.isinf(grade.height):
                raise ValueError("边坡在有效地形范围内未与地面相交，请扩大地形范围或调整边坡")
            current = (current[0]+vector[0]*grade.height,current[1]+grade.height)
            if not ground[0][0] <= current[0] <= ground[-1][0]:
                raise ValueError("边坡超出有效地形范围，禁止接地形端点冒算")
            points.append(current)
            if grade.berm_width > 0:
                hit = CrossSectionCalculator._ray_ground_hit(current,(direction,0.0),ground,grade.berm_width)
                if hit is not None:
                    points.append(hit[1])
                    return points
                current = (current[0]+direction*grade.berm_width,current[1])
                if not ground[0][0] <= current[0] <= ground[-1][0]:
                    raise ValueError("马道超出有效地形范围")
                points.append(current)
        raise ValueError("分级边坡终点尚未到达地面，不能封闭开挖断面")

    @staticmethod
    def _find_slope_ground_intersect(start_offset,start_elev,slope_ratio,direction,ground_pts):
        ground = _validated_line(ground_pts,"地面线")
        if direction not in (-1,1) or not math.isfinite(slope_ratio) or slope_ratio < 0:
            raise ValueError("边坡方向或坡比无效")
        hit = CrossSectionCalculator._ray_ground_hit((start_offset,start_elev),(direction*slope_ratio,1.0),ground)
        return hit[1] if hit else None

    def _compute_areas(self,ground_pts,design_pts,excav_boundary,invert_elevation,
                       ground_elev_center,geology,backfill_cfg,station):
        self._validate_backfill(backfill_cfg)
        areas = signed_line_areas(ground_pts,design_pts)
        shape = Polygon(excav_boundary) if excav_boundary else None
        if shape is not None and not shape.is_valid:
            raise ValueError("开挖区域无效")
        cut = float(shape.area) if shape is not None else areas.excavation_area
        layers = self._split_by_geology(ground_pts,design_pts,geology,shape) if geology and cut > 0 else {}
        return SectionAreaResult(station=station,excavation_total=cut,
            excavation_by_layer=layers,fill_area=areas.fill_area,
            backfill_area=0.0 if areas.fill_area == 0 else None,
            embankment_area=0.0 if areas.fill_area == 0 else None,
            excavation_width=(shape.bounds[2]-shape.bounds[0]) if shape is not None and not shape.is_empty else 0.0,
            ground_elevation_center=ground_elev_center,design_invert_elevation=invert_elevation,
            cut_depth=ground_elev_center-invert_elevation)

    @staticmethod
    def _shoelace_area(pts):
        """有效简单多边形的非负面积，不将自交轮廓修成另一个区域。"""
        if len(pts) < 3:
            return 0.0
        shape = Polygon(pts)
        if not shape.is_valid:
            raise ValueError("多边形无效")
        return float(shape.area)

    @staticmethod
    def _area_between_lines(upper,lower):
        return signed_line_areas(upper,lower).excavation_area

    @staticmethod
    def _split_by_geology(ground_pts,design_pts,geology,excavation=None):
        if len(geology.layer_names) != len(geology.top_elevations) or not geology.layer_names:
            raise ValueError("地质层名称与界面数量不一致")
        tops = geology.top_elevations
        if any(not math.isfinite(z) for z in tops) or any(b < a for a,b in zip(tops,tops[1:])):
            raise ValueError("地质层界面必须为递增有限值")
        if excavation is None:
            if signed_line_areas(ground_pts,design_pts).fill_area > _TOL:
                raise ValueError("交叉地面线须先明确实际开挖区域再分层")
            left,right = design_pts[0][0],design_pts[-1][0]
            ground = [(left,CrossSectionCalculator._get_ground_elev_at_offset(ground_pts,left))]
            ground += [p for p in ground_pts if left < p[0] < right]
            ground += [(right,CrossSectionCalculator._get_ground_elev_at_offset(ground_pts,right))]
            excavation = Polygon(ground+list(reversed(design_pts)))
        if not excavation.is_valid:
            raise ValueError("分层所用开挖区域无效")
        x0,z0,x1,z1 = excavation.bounds
        result = {}
        for index,name in enumerate(geology.layer_names):
            upper = max(z1,tops[index]) if index == len(tops)-1 else tops[index]
            result[name] = result.get(name,0.0)+(float(excavation.intersection(box(x0,z0,x1,upper)).area) if upper > z0 else 0.0)
            z0 = max(z0,upper)
        return result

    @staticmethod
    def _compute_fill_area(ground_pts,design_pts,backfill_cfg=None):
        CrossSectionCalculator._validate_backfill(backfill_cfg)
        return signed_line_areas(ground_pts,design_pts).fill_area

    @staticmethod
    def _get_ground_elev_at_offset(ground_pts,offset=0.0):
        ground = _validated_line(ground_pts,"地面线")
        if not math.isfinite(offset) or not ground[0][0] <= offset <= ground[-1][0]:
            raise ValueError("指定偏距超出有效地形范围")
        for (x0,z0),(x1,z1) in zip(ground,ground[1:]):
            if x0 <= offset <= x1:
                return z0+(z1-z0)*(offset-x0)/(x1-x0)
        raise ValueError("指定偏距无地形数据")
