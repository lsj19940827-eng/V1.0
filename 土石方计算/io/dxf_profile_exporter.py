# -*- coding: utf-8 -*-
"""
断面 DXF 图纸导出器

横断面 DXF 规格（已在 PRD 第三轮讨论中全部确认）：
- 图形元素：地面线/设计断面/开挖边坡/地质分层线/填充/马道/施工便道
- 填充图案：AutoCAD 标准填充（土方 ANSI31 / 石方三角形 / 回填 DOTS）
- 尺寸标注：全部（渠底宽/渠深/口宽/开挖深度/边坡比/各级坡高/马道宽/断面总宽/贴坡厚度）
- 文字标注：全部（桩号/地面高程/设计底高程/挖深/开挖面积/回填面积/地质名称/断面类型）
- 下方表格栏：桩号/地面高程/设计底高程/挖深/各层开挖面积/回填面积
- 图层：按元素分 8 个图层（颜色已确认）

图层名与颜色（ACI）：
    地面线   → 黄色 (2)
    设计断面 → 红色 (1)
    开挖边坡 → 绿色 (3)
    地质分层 → 青色 (4)
    填充图案 → 灰色 (8)
    尺寸标注 → 白色 (7)
    文字标注 → 白色 (7)
    表格线框 → 白色 (7)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from 土石方计算.models.section import (
    CrossSectionData,
    LongitudinalData,
    GeologyLayer,
)


@dataclass
class CrossSectionDXFConfig:
    """
    横断面 DXF 导出配置
    """
    sections_per_page: int = 4           # 每页断面数
    paper_width: float = 594.0           # 图幅宽（mm），A1 = 841×594
    paper_height: float = 420.0
    scale_h: float = 1.0 / 200.0        # 水平比例尺（1:200 → 0.005 mm/mm）
    scale_v: float = 1.0 / 200.0        # 竖向比例尺
    table_height: float = 60.0          # 下方表格栏高度（mm）
    margin: float = 20.0                # 页边距（mm）
    text_height: float = 2.5            # 标注文字高度（mm）
    dim_text_height: float = 2.0        # 尺寸标注文字高度（mm）
    output_path: str = "横断面图.dxf"


@dataclass
class LongitudinalDXFConfig:
    """
    纵断面 DXF 导出配置（复用水面线模块格式，新增地面高程/挖深行）
    """
    scale_h: float = 1.0 / 2000.0       # 水平比例尺
    scale_v: float = 1.0 / 200.0        # 竖向比例尺（夸大 10 倍）
    paper_width: float = 1189.0          # A0 横向
    paper_height: float = 841.0
    text_height: float = 3.0
    output_path: str = "纵断面图.dxf"


# 图层定义
LAYER_GROUND    = ("地面线",   2)   # 黄色
LAYER_DESIGN    = ("设计断面", 1)   # 红色
LAYER_EXCAV     = ("开挖边坡", 3)   # 绿色
LAYER_GEOLOGY   = ("地质分层", 4)   # 青色
LAYER_HATCH     = ("填充图案", 8)   # 灰色
LAYER_DIM       = ("尺寸标注", 7)   # 白色
LAYER_TEXT      = ("文字标注", 7)   # 白色
LAYER_TABLE     = ("表格线框", 7)   # 白色

ALL_LAYERS = [LAYER_GROUND, LAYER_DESIGN, LAYER_EXCAV, LAYER_GEOLOGY,
              LAYER_HATCH, LAYER_DIM, LAYER_TEXT, LAYER_TABLE]


class CrossSectionDXFExporter:
    """
    横断面批量 DXF 导出器

    Usage
    -----
    >>> exporter = CrossSectionDXFExporter(config)
    >>> exporter.export(sections, geology_layers, output_path)
    """

    def __init__(self, config: Optional[CrossSectionDXFConfig] = None):
        self._cfg = config or CrossSectionDXFConfig()

    def export(
        self,
        sections: list[CrossSectionData],
        geology_layers: Optional[list[GeologyLayer]] = None,
        output_path: Optional[str] = None,
    ) -> str:
        """
        批量导出横断面图到单个 DXF 文件。

        每页按 config.sections_per_page 排列，自动分页。

        Parameters
        ----------
        sections : 已计算面积的横断面列表
        geology_layers : 地质层定义（用于填充图案）
        output_path : 输出路径（覆盖 config.output_path）

        Returns
        -------
        实际输出文件路径
        """
        import ezdxf
        out = output_path or self._cfg.output_path
        doc = ezdxf.new(dxfversion="R2010")
        msp = doc.modelspace()

        self._setup_layers(doc)
        self._setup_styles(doc)

        # 分页排列
        spp = self._cfg.sections_per_page
        pages = [sections[i:i + spp] for i in range(0, len(sections), spp)]

        page_offset_y = 0.0
        page_h_mm = self._cfg.paper_height + self._cfg.margin

        for page_idx, page_sections in enumerate(pages):
            page_origin_y = page_offset_y + page_idx * page_h_mm
            self._draw_page(msp, page_sections, geology_layers or [],
                            page_origin_y)

        doc.saveas(out)
        return out

    # ------------------------------------------------------------------
    # 页面绘制
    # ------------------------------------------------------------------

    def _draw_page(
        self,
        msp,
        sections: list[CrossSectionData],
        geology_layers: list[GeologyLayer],
        page_origin_y: float,
    ) -> None:
        """在模型空间的指定页区域内排列多个横断面"""
        cfg = self._cfg
        n = len(sections)
        cols = min(n, 2)  # 每行最多 2 个断面
        rows_count = (n + cols - 1) // cols
        cell_w = (cfg.paper_width - 2 * cfg.margin) / cols
        cell_h = (cfg.paper_height - 2 * cfg.margin - cfg.table_height) / rows_count

        for i, sec in enumerate(sections):
            row = i // cols
            col = i % cols
            origin_x = cfg.margin + col * cell_w
            origin_y = page_origin_y + cfg.margin + (rows_count - 1 - row) * (cell_h + cfg.table_height)
            self._draw_section(msp, sec, geology_layers,
                               origin_x, origin_y, cell_w, cell_h)

    def _draw_section(
        self,
        msp,
        sec: CrossSectionData,
        geology_layers: list[GeologyLayer],
        ox: float,
        oy: float,
        width_mm: float,
        height_mm: float,
    ) -> None:
        """绘制单个横断面（含地面线/设计断面/边坡/填充/标注/表格）"""
        cfg = self._cfg
        # 坐标转换：实际距离(m) → 图纸坐标(mm)
        sh = cfg.scale_h * 1000.0   # m → mm
        sv = cfg.scale_v * 1000.0

        # 确定视图原点：以断面中心线 offset=0 为图纸中点
        cx_mm = ox + width_mm / 2.0

        def to_mm(offset_m: float, elev_m: float) -> tuple[float, float]:
            return (cx_mm + offset_m * sh,
                    oy + (elev_m - _base_elev(sec)) * sv)

        # --- 地面线 ---
        if len(sec.ground_points) >= 2:
            pts_mm = [to_mm(p[0], p[1]) for p in sec.ground_points]
            self._add_polyline(msp, pts_mm, LAYER_GROUND[0])

        # --- 设计断面轮廓 ---
        if len(sec.design_points) >= 2:
            pts_mm = [to_mm(p[0], p[1]) for p in sec.design_points]
            self._add_polyline(msp, pts_mm, LAYER_DESIGN[0], closed=False)

        # --- 开挖边坡线 ---
        if len(sec.excavation_boundary) >= 2:
            pts_mm = [to_mm(p[0], p[1]) for p in sec.excavation_boundary]
            self._add_polyline(msp, pts_mm, LAYER_EXCAV[0])

        # --- 地质分层线 ---
        if sec.geology_profile:
            self._draw_geology_lines(msp, sec, to_mm, geology_layers)

        # --- 施工便道线（虚线，坡顶平台）---
        if getattr(sec, 'has_platform', False) and sec.excavation_boundary:
            self._draw_platform_line(msp, sec, to_mm)

        # --- 开挖区域填充（按地质层分色） ---
        if sec.area_result and sec.area_result.excavation_total > 0:
            self._draw_hatch_excavation(msp, sec, to_mm, geology_layers)

        # --- 回填区域填充 ---
        if sec.area_result and sec.area_result.fill_area > 0:
            self._draw_hatch_backfill(msp, sec, to_mm)

        # --- 尺寸标注 ---
        if sec.area_result:
            self._draw_dimensions(msp, sec, to_mm, ox, oy, width_mm)

        # --- 文字标注 ---
        self._draw_text_labels(msp, sec, to_mm, ox, oy, width_mm, height_mm,
                               geology_layers)

        # --- 下方表格栏 ---
        self._draw_table(msp, sec, ox, oy - cfg.table_height, width_mm)

    def _draw_geology_lines(self, msp, sec, to_mm_fn, geology_layers):
        """绘制地质分层水平界面线"""
        geo = sec.geology_profile
        x_min = sec.ground_points[0][0] if sec.ground_points else -20.0
        x_max = sec.ground_points[-1][0] if sec.ground_points else 20.0
        for i, top_z in enumerate(geo.top_elevations):
            pt_l = to_mm_fn(x_min, top_z)
            pt_r = to_mm_fn(x_max, top_z)
            self._add_line(msp, pt_l, pt_r, LAYER_GEOLOGY[0], linetype="DASHED")
            # 地质层名称标注
            name = geo.layer_names[i] if i < len(geo.layer_names) else ""
            mid_x = (pt_l[0] + pt_r[0]) / 2
            mid_y = (pt_l[1] + pt_r[1]) / 2 - self._cfg.text_height * 1.5
            self._add_text(msp, name, (mid_x, mid_y),
                           self._cfg.text_height, LAYER_TEXT[0])

    def _draw_platform_line(self, msp, sec, to_mm_fn):
        """
        绘制施工便道线（虚线）。
        施工便道是坡顶最外侧的水平段，从开挖边界端点向外延伸 platform_width。
        """
        eb = sec.excavation_boundary
        if len(eb) < 4:
            return
        pw = getattr(sec, 'platform_width', 2.0) or 2.0

        # 左侧施工便道：开挖边界最左端水平段
        left_pt = min(eb, key=lambda p: p[0])      # 最左点
        p0_mm = to_mm_fn(left_pt[0] - pw, left_pt[1])
        p1_mm = to_mm_fn(left_pt[0], left_pt[1])
        self._add_line(msp, p0_mm, p1_mm, LAYER_EXCAV[0], linetype="DASHED")

        # 右侧施工便道：开挖边界最右端水平段
        right_pt = max(eb, key=lambda p: p[0])     # 最右点
        p2_mm = to_mm_fn(right_pt[0], right_pt[1])
        p3_mm = to_mm_fn(right_pt[0] + pw, right_pt[1])
        self._add_line(msp, p2_mm, p3_mm, LAYER_EXCAV[0], linetype="DASHED")

    def _draw_hatch_excavation(
        self, msp, sec, to_mm_fn, geology_layers: list[GeologyLayer]
    ):
        """
        绘制开挖区域填充。
        若有地质分层 → 按各层使用不同填充图案；否则统一 ANSI31。
        """
        if not sec.ground_points or not sec.design_points:
            return

        geo = sec.geology_profile
        if geo and geology_layers and len(geology_layers) >= 1:
            # 按地质层分别绘制填充
            layer_map = {gl.name: gl for gl in geology_layers}
            try:
                from shapely.geometry import Polygon
                excav_poly_pts = list(sec.ground_points) + list(reversed(sec.design_points))
                excav_poly = Polygon(excav_poly_pts)
                if not excav_poly.is_valid:
                    excav_poly = excav_poly.buffer(0)
                x_min = min(p[0] for p in sec.ground_points + sec.design_points) - 1.0
                x_max = max(p[0] for p in sec.ground_points + sec.design_points) + 1.0
                prev_z = min(p[1] for p in sec.design_points)
                for i, name in enumerate(geo.layer_names):
                    top_z = geo.top_elevations[i]
                    band = Polygon([(x_min, prev_z), (x_max, prev_z),
                                    (x_max, top_z), (x_min, top_z)])
                    intersection = excav_poly.intersection(band)
                    if intersection.area > 0.001:
                        coords = list(intersection.exterior.coords)
                        pts_mm = [to_mm_fn(p[0], p[1]) for p in coords]
                        gl = layer_map.get(name)
                        pattern = gl.hatch_pattern if gl else "ANSI31"
                        scale = gl.hatch_scale if gl else 1.0
                        self._add_hatch(msp, pts_mm, pattern,
                                        LAYER_HATCH[0], scale=scale)
                    prev_z = top_z
                # 最顶层
                if geo.layer_names:
                    top_band = Polygon([
                        (x_min, prev_z), (x_max, prev_z),
                        (x_max, max(p[1] for p in sec.ground_points) + 1),
                        (x_min, max(p[1] for p in sec.ground_points) + 1),
                    ])
                    intersection = excav_poly.intersection(top_band)
                    if intersection.area > 0.001:
                        coords = list(intersection.exterior.coords)
                        pts_mm = [to_mm_fn(p[0], p[1]) for p in coords]
                        gl = layer_map.get(geo.layer_names[-1])
                        pattern = gl.hatch_pattern if gl else "ANSI31"
                        scale = gl.hatch_scale if gl else 1.0
                        self._add_hatch(msp, pts_mm, pattern,
                                        LAYER_HATCH[0], scale=scale)
                return
            except Exception:
                pass  # 回退到整体填充
        # 无地质分层 → 整体 ANSI31
        boundary = list(sec.ground_points) + list(reversed(sec.design_points))
        pts_mm = [to_mm_fn(p[0], p[1]) for p in boundary]
        if len(pts_mm) >= 3:
            self._add_hatch(msp, pts_mm, "ANSI31", LAYER_HATCH[0], scale=1.0)

    def _draw_hatch_backfill(self, msp, sec, to_mm_fn):
        """绘制回填区域填充（DOTS 图案，回填指设计线高于地面的区域）"""
        if not sec.ground_points or not sec.design_points:
            return
        try:
            from shapely.geometry import Polygon
            # 回填区域：设计线在地面线以上
            fill_poly_pts = list(sec.design_points) + list(reversed(sec.ground_points))
            poly = Polygon(fill_poly_pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.area > 0.001:
                coords = list(poly.exterior.coords)
                pts_mm = [to_mm_fn(p[0], p[1]) for p in coords]
                self._add_hatch(msp, pts_mm, "DOTS", LAYER_HATCH[0], scale=0.5)
        except Exception:
            # 回退：用简单闭合多边形
            boundary = list(sec.design_points) + list(reversed(sec.ground_points))
            pts_mm = [to_mm_fn(p[0], p[1]) for p in boundary]
            if len(pts_mm) >= 3:
                self._add_hatch(msp, pts_mm, "DOTS", LAYER_HATCH[0], scale=0.5)

    def _draw_dimensions(self, msp, sec, to_mm_fn, ox, oy, width_mm):
        """绘制尺寸标注（渠底宽/渠深/口宽/开挖深度/边坡比/各级坡高/马道宽/断面总宽）"""
        ar = sec.area_result
        if ar is None:
            return
        cfg = self._cfg
        dh = cfg.dim_text_height
        dp = sec.design_points
        eb = sec.excavation_boundary

        # --- 渠底宽 / 渠深 / 口宽标注 ---
        if len(dp) >= 4:
            # dp: [左上, 左下, 右下, 右上]
            p_lt, p_lb, p_rb, p_rt = dp[0], dp[1], dp[2], dp[3]
            lt_mm = to_mm_fn(*p_lt)
            lb_mm = to_mm_fn(*p_lb)
            rb_mm = to_mm_fn(*p_rb)
            rt_mm = to_mm_fn(*p_rt)

            # 渠底宽（底部下方）
            bw = abs(p_rb[0] - p_lb[0])
            mid_b_x = (lb_mm[0] + rb_mm[0]) / 2.0
            self._add_text(msp, f"b={bw:.2f}",
                           (mid_b_x, lb_mm[1] - dh * 2.5), dh, LAYER_DIM[0])
            # 水平引线
            self._add_line(msp, (lb_mm[0], lb_mm[1] - dh * 1.0),
                           (rb_mm[0], rb_mm[1] - dh * 1.0), LAYER_DIM[0])

            # 渠深（左侧外）
            depth = abs(p_lt[1] - p_lb[1])
            mid_h_y = (lb_mm[1] + lt_mm[1]) / 2.0
            self._add_text(msp, f"h={depth:.2f}",
                           (lt_mm[0] - dh * 8, mid_h_y), dh, LAYER_DIM[0])
            # 竖向引线
            self._add_line(msp, (lt_mm[0] - dh * 2, lb_mm[1]),
                           (lt_mm[0] - dh * 2, lt_mm[1]), LAYER_DIM[0])

            # 口宽（顶部上方）
            tw = abs(p_rt[0] - p_lt[0])
            mid_t_x = (lt_mm[0] + rt_mm[0]) / 2.0
            self._add_text(msp, f"B={tw:.2f}",
                           (mid_t_x, lt_mm[1] + dh * 1.5), dh, LAYER_DIM[0])

        # --- 贴坡厚度（衬砌厚度）---
        lt = getattr(sec, 'lining_thickness', 0.0)
        if lt and lt > 0 and dp and len(dp) >= 4:
            # 在左内坡面标注贴坡厚度
            p_lt, p_lb = dp[0], dp[1]
            mid_slope = ((p_lt[0] + p_lb[0]) / 2, (p_lt[1] + p_lb[1]) / 2)
            mid_mm = to_mm_fn(*mid_slope)
            self._add_text(msp, f"δ={lt*100:.0f}cm",
                           (mid_mm[0] - dh * 6, mid_mm[1]),
                           dh * 0.9, LAYER_DIM[0])

        # --- 开挖深度 ---
        if ar.cut_depth > 0:
            self._add_text(msp, f"挖深={ar.cut_depth:.2f}",
                           (ox + width_mm - dh * 12, oy + dh * 2), dh, LAYER_DIM[0])

        # --- 断面开挖总宽 ---
        if eb and len(eb) >= 4:
            all_offsets = [p[0] for p in eb]
            exc_width = max(all_offsets) - min(all_offsets)
            self._add_text(msp, f"开挖宽={exc_width:.2f}",
                           (ox + width_mm - dh * 12, oy + dh * 5), dh, LAYER_DIM[0])

        # --- 边坡比标注 + 各级坡高 + 马道宽 ---
        if eb and len(eb) >= 4:
            # 分析开挖边界折点：识别坡面段、水平马道段
            # 左侧：从 design_pts[0] 往左到地面交点（eb前段）
            # 右侧：从 design_pts[-1] 往右到地面交点（eb后段）
            half = len(eb) // 2
            for side_pts, sign in [(eb[:half], -1), (eb[half:], +1)]:
                for k in range(len(side_pts) - 1):
                    p0, p1 = side_pts[k], side_pts[k + 1]
                    dz = abs(p1[1] - p0[1])
                    dx = abs(p1[0] - p0[0])
                    if dz > 0.3:
                        # 坡面段：标注坡比 1:m
                        ratio = dx / dz if dz > 1e-6 else 0
                        if ratio > 0.01:
                            mid_mm = to_mm_fn((p0[0] + p1[0]) / 2.0,
                                              (p0[1] + p1[1]) / 2.0)
                            self._add_text(msp, f"1:{ratio:.2f}",
                                           (mid_mm[0] + sign * dh * 2.5,
                                            mid_mm[1] + dh * 0.5),
                                           dh * 0.9, LAYER_DIM[0])
                        # 各级坡高竖向标注
                        p0_mm = to_mm_fn(p0[0], p0[1])
                        p1_mm = to_mm_fn(p1[0], p1[1])
                        self._add_text(msp, f"H={dz:.2f}m",
                                       (p0_mm[0] + sign * dh * 6,
                                        (p0_mm[1] + p1_mm[1]) / 2),
                                       dh * 0.8, LAYER_DIM[0])
                    elif dz < 0.1 and dx > 0.5:
                        # 水平马道：标注马道宽
                        p0_mm = to_mm_fn(p0[0], p0[1])
                        p1_mm = to_mm_fn(p1[0], p1[1])
                        mid_mm = ((p0_mm[0] + p1_mm[0]) / 2,
                                   p0_mm[1] + dh * 1.5)
                        self._add_text(msp, f"马道={dx:.2f}m",
                                       mid_mm, dh * 0.8, LAYER_DIM[0])

    def _draw_text_labels(self, msp, sec, to_mm_fn, ox, oy, width_mm, height_mm,
                           geology_layers: "list[GeologyLayer] | None" = None):
        """绘制文字标注（桩号/高程/挖深/面积/断面类型）"""
        ar = sec.area_result
        cfg = self._cfg
        th = cfg.text_height

        # 断面标题（桩号 + 断面类型）
        station_str = _format_station(sec.station)
        section_type = _guess_section_type(sec)
        title = f"{station_str}  {section_type}" if section_type else station_str
        title_x = ox + width_mm / 2.0
        title_y = oy + height_mm + th * 2
        self._add_text(msp, title, (title_x, title_y),
                       th * 1.5, LAYER_TEXT[0], align="CENTER")

        if ar is None:
            return

        # 地面高程 / 设计底高程 / 挖深 / 面积
        info_lines = [
            f"地面高程: {ar.ground_elevation_center:.3f} m",
            f"设计底高程: {ar.design_invert_elevation:.3f} m",
            f"挖深: {ar.cut_depth:.3f} m",
            f"开挖面积: {ar.excavation_total:.2f} m²",
            f"回填面积: {ar.fill_area:.2f} m²",
        ]
        for j, line in enumerate(info_lines):
            self._add_text(msp, line,
                           (ox + 2, oy + height_mm - (j + 1) * th * 1.8),
                           th, LAYER_TEXT[0])

    def _draw_table(self, msp, sec, ox: float, oy: float, width_mm: float):
        """绘制下方数据表格栏"""
        cfg = self._cfg
        th = cfg.table_height
        ar = sec.area_result

        # 表格外框
        self._add_rectangle(msp, ox, oy, ox + width_mm, oy + th, LAYER_TABLE[0])

        # 行分割线（从下到上：桩号/地面高程/设计底高程/挖深/各层开挖面积/回填面积）
        layer_names = (list(ar.excavation_by_layer.keys())
                       if ar else [])
        row_labels = (["桩号", "地面高程(m)", "设计底高程(m)", "挖深(m)"]
                      + [f"{n}开挖面积(m²)" for n in layer_names]
                      + ["回填面积(m²)"])
        n_rows = len(row_labels)
        row_h = th / n_rows
        label_col_w = 30.0

        for i, label in enumerate(row_labels):
            y_line = oy + i * row_h
            # 行分割线
            self._add_line(msp, (ox, y_line), (ox + width_mm, y_line),
                           LAYER_TABLE[0])
            # 行标签
            self._add_text(msp, label,
                           (ox + 2, y_line + row_h * 0.25),
                           cfg.text_height * 0.8, LAYER_TABLE[0])
            # 数值
            val = self._get_table_value(sec, label)
            self._add_text(msp, val,
                           (ox + label_col_w + 5, y_line + row_h * 0.25),
                           cfg.text_height * 0.8, LAYER_TABLE[0])

        # 标签列分隔线
        self._add_line(msp, (ox + label_col_w, oy),
                       (ox + label_col_w, oy + th), LAYER_TABLE[0])

    @staticmethod
    def _get_table_value(sec: CrossSectionData, label: str) -> str:
        ar = sec.area_result
        if "桩号" in label:
            return _format_station(sec.station)
        if ar is None:
            return "-"
        if "地面高程" in label:
            return f"{ar.ground_elevation_center:.3f}"
        if "设计底高程" in label:
            return f"{ar.design_invert_elevation:.3f}"
        if "挖深" in label:
            return f"{ar.cut_depth:.3f}"
        if "回填" in label:
            return f"{ar.fill_area:.2f}"
        # 分层开挖面积
        for name, area in ar.excavation_by_layer.items():
            if name in label:
                return f"{area:.2f}"
        return "-"

    # ------------------------------------------------------------------
    # ezdxf 辅助绘图方法
    # ------------------------------------------------------------------

    @staticmethod
    def _setup_layers(doc) -> None:
        for name, color in ALL_LAYERS:
            if name not in doc.layers:
                doc.layers.add(name=name, color=color)

    @staticmethod
    def _setup_styles(doc) -> None:
        """设置仿宋字体（与水面线模块保持一致）"""
        if "FSSONG" not in doc.styles:
            doc.styles.add("FSSONG", font="仿宋_GB2312.ttf")

    @staticmethod
    def _add_polyline(msp, pts_mm: list[tuple], layer: str,
                      closed: bool = False) -> None:
        if len(pts_mm) < 2:
            return
        msp.add_lwpolyline(
            pts_mm,
            dxfattribs={"layer": layer, "closed": closed}
        )

    @staticmethod
    def _add_line(msp, p0: tuple, p1: tuple, layer: str,
                  linetype: str = "CONTINUOUS") -> None:
        msp.add_line(
            start=(p0[0], p0[1], 0),
            end=(p1[0], p1[1], 0),
            dxfattribs={"layer": layer, "linetype": linetype}
        )

    @staticmethod
    def _add_text(msp, text: str, pos: tuple, height: float,
                  layer: str, align: str = "LEFT") -> None:
        msp.add_text(
            text,
            dxfattribs={
                "layer": layer,
                "height": height,
                "insert": (pos[0], pos[1]),
                "style": "FSSONG",
            }
        )

    @staticmethod
    def _add_hatch(msp, pts_mm: list[tuple], pattern: str,
                   layer: str, scale: float = 1.0) -> None:
        hatch = msp.add_hatch(color=8, dxfattribs={"layer": layer})
        hatch.set_pattern_fill(pattern, scale=scale)
        hatch.paths.add_polyline_path(pts_mm, is_closed=True)

    @staticmethod
    def _add_rectangle(msp, x0: float, y0: float,
                        x1: float, y1: float, layer: str) -> None:
        msp.add_lwpolyline(
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            dxfattribs={"layer": layer, "closed": True}
        )


class LongitudinalDXFExporter:
    """
    纵断面 DXF 导出器

    复用水面线模块的格式（`app_渠系计算前端/water_profile/cad_tools.py`），
    新增「地面高程」和「挖深/填高」数据行。

    Usage
    -----
    >>> exporter = LongitudinalDXFExporter(config)
    >>> exporter.export(long_data, output_path)
    """

    def __init__(self, config: Optional[LongitudinalDXFConfig] = None):
        self._cfg = config or LongitudinalDXFConfig()

    def export(
        self,
        long_data: LongitudinalData,
        output_path: Optional[str] = None,
    ) -> str:
        """
        导出纵断面图到 DXF 文件。

        格式参考水面线模块 cad_tools.py，包含：
        - 下方表格栏（桩号/地面高程/设计底高程/挖深填高）
        - 上方高程折线图（地面线/设计底高程线）
        - 竖向节点线

        Returns
        -------
        实际输出文件路径
        """
        import ezdxf

        out = output_path or self._cfg.output_path
        cfg = self._cfg
        doc = ezdxf.new(dxfversion="R2010")
        msp = doc.modelspace()

        # 图层
        layer_defs = [
            ("表格线框", 7), ("地面高程线", 2), ("设计底高程线", 1),
            ("文字标注", 7), ("尺寸标注", 7),
        ]
        for name, color in layer_defs:
            if name not in doc.layers:
                doc.layers.add(name=name, color=color)

        # 字体样式
        if "FSSONG" not in doc.styles:
            doc.styles.add("FSSONG", font="仿宋_GB2312.ttf")

        stations = long_data.stations
        ground_elevs = long_data.ground_elevations
        design_elevs = long_data.design_elevations
        cut_depths = long_data.get_cut_depths()
        n = len(stations)
        if n == 0:
            doc.saveas(out)
            return out

        # 比例转换
        sh = cfg.scale_h * 1000.0  # m → mm
        sv = cfg.scale_v * 1000.0
        th = cfg.text_height

        # 基准高程（取最低高程 -2m 作为绘图零线）
        all_elevs = [e for e in ground_elevs if e == e]  # 过滤 nan
        all_elevs += [e for e in design_elevs if e is not None and e == e]
        base_elev = min(all_elevs) - 2.0 if all_elevs else 0.0

        # 第一个桩号作为绘图 X 原点参考
        s0 = stations[0]

        def sx(station: float) -> float:
            return (station - s0) * sh

        def sy(elev: float) -> float:
            return (elev - base_elev) * sv

        last_sx = sx(stations[-1])

        # ======== 表格栏定义 ========
        # 行从下到上：挖深/填高, 设计底高程, 地面高程, 里程桩号
        ROW_LABELS = ["挖深/填高(m)", "设计底高程(m)", "地面高程(m)", "里程桩号"]
        ROW_H = 15.0  # 每行高度(mm)
        TABLE_H = ROW_H * len(ROW_LABELS)
        HEADER_W = 40.0  # 表头列宽(mm)

        # 表格线框 —— 水平线
        for i in range(len(ROW_LABELS) + 1):
            y = i * ROW_H
            msp.add_line((-HEADER_W, y), (last_sx, y),
                         dxfattribs={"layer": "表格线框"})

        # 表格线框 —— 表头左竖线
        msp.add_line((-HEADER_W, 0), (-HEADER_W, TABLE_H),
                     dxfattribs={"layer": "表格线框"})

        # 表头文字
        for i, label in enumerate(ROW_LABELS):
            cy = i * ROW_H + ROW_H / 2.0
            msp.add_text(
                label,
                dxfattribs={"layer": "文字标注", "height": th,
                            "width": 0.7, "style": "FSSONG"}
            ).set_placement((-HEADER_W / 2.0, cy),
                            align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

        # ======== 节点竖线 + 数值文字 ========
        rotation = 90.0
        first_col_offset = th + 1.3

        for idx, s in enumerate(stations):
            x = sx(s)
            # 竖线（穿过表格 + 向上延伸到高程区域）
            top_y = TABLE_H + max(sy(max(all_elevs)) - sy(base_elev), 50.0) + 20.0 if all_elevs else TABLE_H + 80
            msp.add_line((x, 0), (x, top_y),
                         dxfattribs={"layer": "表格线框"})

            text_x = x + first_col_offset if idx == 0 else x - 1

            # 行 0（底）：挖深/填高
            cut = cut_depths[idx]
            cut_str = f"{cut:.3f}" if cut is not None else "-"
            msp.add_text(
                cut_str,
                dxfattribs={"layer": "文字标注", "height": th,
                            "rotation": rotation, "width": 0.7, "style": "FSSONG"}
            ).set_placement((text_x, ROW_H * 0.5))

            # 行 1：设计底高程
            d = design_elevs[idx]
            d_str = f"{d:.3f}" if d is not None else "-"
            msp.add_text(
                d_str,
                dxfattribs={"layer": "文字标注", "height": th,
                            "rotation": rotation, "width": 0.7, "style": "FSSONG"}
            ).set_placement((text_x, ROW_H * 1.5))

            # 行 2：地面高程
            g = ground_elevs[idx]
            g_str = f"{g:.3f}" if g == g else "-"
            msp.add_text(
                g_str,
                dxfattribs={"layer": "文字标注", "height": th,
                            "rotation": rotation, "width": 0.7, "style": "FSSONG"}
            ).set_placement((text_x, ROW_H * 2.5))

            # 行 3（顶）：里程桩号
            msp.add_text(
                _format_station(s),
                dxfattribs={"layer": "文字标注", "height": th,
                            "rotation": rotation, "width": 0.7, "style": "FSSONG"}
            ).set_placement((text_x, ROW_H * 3.5))

        # ======== 高程折线 ========
        # 地面高程线（黄色）
        ground_pts = [(sx(s), TABLE_H + sy(g))
                      for s, g in zip(stations, ground_elevs)
                      if g == g]
        if len(ground_pts) >= 2:
            msp.add_lwpolyline(ground_pts,
                               dxfattribs={"layer": "地面高程线"})

        # 设计底高程线（红色）
        design_pts = [(sx(s), TABLE_H + sy(d))
                      for s, d in zip(stations, design_elevs)
                      if d is not None and d == d]
        if len(design_pts) >= 2:
            msp.add_lwpolyline(design_pts,
                               dxfattribs={"layer": "设计底高程线"})

        doc.saveas(out)
        return out


# ------------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------------

def _guess_section_type(sec: "CrossSectionData") -> str:
    """
    从横断面数据猜测断面类型名称（用于图纸标题）。
    """
    if not sec.design_points:
        return ""
    dp = sec.design_points
    # 梯形判断：4个顶点且左右上点不等宽
    if len(dp) == 4:
        top_w = abs(dp[3][0] - dp[0][0])
        bot_w = abs(dp[2][0] - dp[1][0])
        if abs(top_w - bot_w) > 0.01:
            return "梯形明渠"
        else:
            return "矩形明渠"
    elif len(dp) > 4:
        return "复合断面"
    return ""


def _format_station(station: float) -> str:
    """格式化桩号为 K0+000.000 格式"""
    km = int(station // 1000)
    m = station - km * 1000.0
    return f"K{km}+{m:07.3f}"


def _base_elev(sec: CrossSectionData) -> float:
    """计算断面绘图基准高程（地面线最低点再降 1m）"""
    all_elevs = [p[1] for p in sec.ground_points + sec.design_points]
    if not all_elevs:
        return 0.0
    return min(all_elevs) - 1.0
