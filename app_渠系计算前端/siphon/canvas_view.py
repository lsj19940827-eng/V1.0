# -*- coding: utf-8 -*-
"""
倒虹吸管道可视化组件 —— 纵断面视图 + 平面视图
基于 QWidget + QPainter 绘制，支持缩放、平移
"""

import math
import os
import sys

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import (
    QPainter, QPen, QColor, QFont, QBrush, QPainterPath,
    QPolygonF, QWheelEvent, QMouseEvent, QPaintEvent
)

# 确保计算引擎路径
_pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_siphon_dir = os.path.join(_pkg_root, '倒虹吸水力计算系统')
if _siphon_dir not in sys.path:
    sys.path.insert(0, _siphon_dir)

# 尝试导入模型
try:
    from siphon_models import (
        SegmentType, SegmentDirection, TurnType,
        COMMON_SEGMENT_TYPES, InletOutletShape, PlanFeaturePoint
    )
    MODELS_AVAILABLE = True
except ImportError:
    MODELS_AVAILABLE = False


class PipelineCanvas(QWidget):
    """管道可视化画布 —— 支持纵断面/平面视图切换、缩放、平移"""

    view_changed = Signal(str)   # 视图切换信号
    zoom_changed = Signal(float)   # 缩放变化信号

    # 颜色常量
    C_BG = QColor(20, 20, 30)
    C_PIPE = QColor(0, 255, 0)
    C_PIPE_DIM = QColor(0, 200, 0)
    C_ARROW = QColor(0, 204, 0)
    C_INLET = QColor(0, 255, 255)
    C_BEND = QColor(255, 170, 0)
    C_NODE = QColor(0, 255, 0)
    C_ELEV = QColor(170, 170, 170)
    C_ELEV_LOW = QColor(255, 136, 136)
    C_INFO = QColor(170, 170, 170)
    C_HINT = QColor(136, 136, 136)
    C_GRID = QColor(40, 40, 50)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

        # 视图模式: "profile" 或 "plan"
        self._view_mode = "profile"

        # 缩放平移
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._drag_start = None
        self._drag_pan_start = None

        # 数据引用（由 panel 设置）
        self._segments = []
        self._plan_segments = []
        self._plan_feature_points = []
        self._plan_total_length = 0.0
        self._longitudinal_nodes = []
        self._longitudinal_is_example = True

    # ---- 公共接口 ----

    def set_view_mode(self, mode: str):
        if mode in ("profile", "plan") and mode != self._view_mode:
            self._view_mode = mode
            self._zoom = 1.0
            self._pan_x = 0.0
            self._pan_y = 0.0
            self.update()
            self.view_changed.emit(mode)
            self.zoom_changed.emit(self._zoom)

    def get_view_mode(self):
        return self._view_mode

    def set_data(self, segments=None, plan_segments=None,
                 plan_feature_points=None, plan_total_length=None,
                 longitudinal_nodes=None, longitudinal_is_example=None):
        if segments is not None:
            self._segments = segments
        if plan_segments is not None:
            self._plan_segments = plan_segments
        if plan_feature_points is not None:
            self._plan_feature_points = plan_feature_points
        if plan_total_length is not None:
            self._plan_total_length = plan_total_length
        if longitudinal_nodes is not None:
            self._longitudinal_nodes = longitudinal_nodes
        if longitudinal_is_example is not None:
            self._longitudinal_is_example = longitudinal_is_example
        self.update()

    def zoom_in(self):
        self._apply_zoom(1.2, self.width() / 2, self.height() / 2)

    def zoom_out(self):
        self._apply_zoom(1 / 1.2, self.width() / 2, self.height() / 2)

    def zoom_reset(self):
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self.update()
        self.zoom_changed.emit(self._zoom)

    def zoom_fit(self):
        self.zoom_reset()

    def auto_select_view(self):
        """根据数据状态自动选择视图"""
        if not MODELS_AVAILABLE:
            return
        has_long = any(
            seg.direction == SegmentDirection.LONGITUDINAL
            and seg.segment_type not in COMMON_SEGMENT_TYPES
            for seg in self._segments
        ) and not self._longitudinal_is_example

        has_long_coords = any(
            len(seg.coordinates) > 0 for seg in self._segments
        )
        has_plan = len(self._plan_feature_points) >= 2 or len(self._plan_segments) > 0

        if not has_long and not has_long_coords and has_plan:
            if self._view_mode == "profile":
                self.set_view_mode("plan")
        elif (has_long or has_long_coords) and not has_plan:
            if self._view_mode == "plan":
                self.set_view_mode("profile")

    # ---- 事件 ----

    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 背景
        p.fillRect(self.rect(), self.C_BG)

        w, h = self.width(), self.height()
        if w < 20 or h < 20:
            p.end()
            return

        if self._view_mode == "plan":
            self._draw_plan(p, w, h)
        else:
            self._draw_profile(p, w, h)
        p.end()

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        pos = event.position()
        self._apply_zoom(factor, pos.x(), pos.y())

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position()
            self._drag_pan_start = (self._pan_x, self._pan_y)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_start is not None and event.buttons() & Qt.LeftButton:
            dx = event.position().x() - self._drag_start.x()
            dy = event.position().y() - self._drag_start.y()
            self._pan_x = self._drag_pan_start[0] + dx
            self._pan_y = self._drag_pan_start[1] + dy
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_start = None
        self._drag_pan_start = None

    # ---- 缩放辅助 ----

    def _apply_zoom(self, factor, cx, cy):
        new_zoom = self._zoom * factor
        if 0.2 <= new_zoom <= 20.0:
            actual = new_zoom / self._zoom
            w2, h2 = self.width() / 2, self.height() / 2
            self._pan_x = (cx - w2) * (1 - actual) + self._pan_x * actual
            self._pan_y = (cy - h2) * (1 - actual) + self._pan_y * actual
            self._zoom = new_zoom
            self.update()
            self.zoom_changed.emit(self._zoom)

    # ---- 坐标变换 ----

    def _make_transform(self, data_bounds, w, h, margin=60):
        """返回 (transform_func, scale)"""
        min_x, max_x, min_y, max_y = data_bounds
        dw = max_x - min_x if max_x > min_x else 1
        dh = max_y - min_y if max_y > min_y else 1
        sx = (w - 2 * margin) / dw
        sy = (h - 2 * margin) / dh
        base_scale = min(sx, sy)
        scale = base_scale * self._zoom
        cx = w / 2 + self._pan_x
        cy = h / 2 + self._pan_y
        dcx = (min_x + max_x) / 2
        dcy = (min_y + max_y) / 2

        def transform(x, y):
            return (cx + (x - dcx) * scale,
                    cy - (y - dcy) * scale)
        return transform, scale

    # ---- 纵断面视图 ----

    def _draw_profile(self, p: QPainter, w, h):
        if not MODELS_AVAILABLE:
            self._draw_centered_text(p, w, h, "模型未加载")
            return

        # 收集管身段坐标
        pipe_segs = [s for s in self._segments
                     if s.segment_type not in COMMON_SEGMENT_TYPES and len(s.coordinates) > 0]

        all_coords = []
        for seg in pipe_segs:
            for c in seg.coordinates:
                if not all_coords or (abs(c[0] - all_coords[-1][0]) > 1e-6 or
                                       abs(c[1] - all_coords[-1][1]) > 1e-6):
                    all_coords.append(c)

        if not all_coords:
            # 无真实坐标 → 简化示意图或提示
            has_pipe = any(
                s.direction == SegmentDirection.LONGITUDINAL
                and s.segment_type not in COMMON_SEGMENT_TYPES
                for s in self._segments
            )
            if has_pipe and not self._longitudinal_is_example:
                self._draw_simplified(p, w, h)
            else:
                self._draw_centered_text(p, w, h,
                    "暂无纵断面数据\n请导入纵断面DXF或手动添加纵断面管身段")
            return

        xs = [c[0] for c in all_coords]
        ys = [c[1] for c in all_coords]
        bounds = (min(xs), max(xs), min(ys), max(ys))
        transform, scale = self._make_transform(bounds, w, h)
        screen_pts = [transform(c[0], c[1]) for c in all_coords]

        # 管线段用于标签碰撞检测
        profile_pipe_lines = [(screen_pts[k][0], screen_pts[k][1],
                                screen_pts[k + 1][0], screen_pts[k + 1][1])
                               for k in range(len(screen_pts) - 1)]

        # 标注碰撞检测用矩形列表
        occupied_rects = []
        _lbl_h = 14
        _lbl_w = 80

        # 管道中心线
        pen = QPen(self.C_PIPE, 3)
        p.setPen(pen)
        for i in range(len(screen_pts) - 1):
            p.drawLine(QPointF(*screen_pts[i]), QPointF(*screen_pts[i + 1]))

        # 方向箭头
        for i in range(len(screen_pts) - 1):
            self._draw_arrow(p, screen_pts[i], screen_pts[i + 1], self.C_ARROW)

        # 起止标记
        if screen_pts:
            self._draw_endpoint(p, screen_pts[0], "进水口", True)
            occupied_rects.append((screen_pts[0][0] - 30, screen_pts[0][1] - 18 - _lbl_h,
                                   screen_pts[0][0] + 30, screen_pts[0][1] - 18))
            self._draw_endpoint(p, screen_pts[-1], "出水口", False)
            occupied_rects.append((screen_pts[-1][0] - 30, screen_pts[-1][1] - 18 - _lbl_h,
                                   screen_pts[-1][0] + 30, screen_pts[-1][1] - 18))

        # 弯折管标记（自适应法线方向标注）
        for seg in pipe_segs:
            if seg.segment_type not in (SegmentType.BEND, SegmentType.FOLD):
                continue
            if not seg.coordinates or len(seg.coordinates) < 2:
                continue
            if seg.segment_type == SegmentType.FOLD and len(seg.coordinates) >= 3:
                bx, by = seg.coordinates[1]
            else:
                bx = (seg.coordinates[0][0] + seg.coordinates[-1][0]) / 2
                by = (seg.coordinates[0][1] + seg.coordinates[-1][1]) / 2
            bsx, bsy = transform(bx, by)

            # 绘制弯折点圆圈
            p.setPen(QPen(Qt.white, 1))
            p.setBrush(QBrush(self.C_BEND))
            p.drawEllipse(QPointF(bsx, bsy), 5, 5)

            # 自适应标注方向：根据相邻管段方向计算法线偏移
            sp_prev = transform(seg.coordinates[0][0], seg.coordinates[0][1])
            sp_next = transform(seg.coordinates[-1][0], seg.coordinates[-1][1])
            v1x, v1y = bsx - sp_prev[0], bsy - sp_prev[1]
            v2x, v2y = sp_next[0] - bsx, sp_next[1] - bsy
            len1 = math.sqrt(v1x * v1x + v1y * v1y) or 1
            len2 = math.sqrt(v2x * v2x + v2y * v2y) or 1
            v1x, v1y = v1x / len1, v1y / len1
            v2x, v2y = v2x / len2, v2y / len2
            avg_dx = (v1x + v2x) / 2
            avg_dy = (v1y + v2y) / 2
            nx, ny = -avg_dy, avg_dx
            if ny > 0:
                nx, ny = -nx, -ny
            n_len = math.sqrt(nx * nx + ny * ny) or 1
            nx, ny = nx / n_len, ny / n_len
            angle_text = f"{seg.segment_type.value} {seg.angle:.3f}°"
            ft = QFont("Microsoft YaHei", 8)
            p.setFont(ft)
            fm_b = p.fontMetrics()
            atw_b = fm_b.horizontalAdvance(angle_text)

            # 尝试多个偏移和方向避免与管线/标签重叠
            bend_placed = False
            for lbl_off in [22, 36, 50]:
                for d in [1, -1]:
                    atx = bsx + nx * d * lbl_off
                    aty = bsy + ny * d * lbl_off
                    rect_b = (atx - atw_b / 2, aty - _lbl_h,
                              atx + atw_b / 2, aty)
                    overlap = any(
                        rect_b[0] < dr[2] and rect_b[2] > dr[0] and
                        rect_b[1] < dr[3] and rect_b[3] > dr[1]
                        for dr in occupied_rects
                    )
                    if not overlap:
                        overlap = any(
                            self._line_rect_intersect(lx1, ly1, lx2, ly2, rect_b)
                            for lx1, ly1, lx2, ly2 in profile_pipe_lines
                        )
                    if not overlap:
                        p.setPen(QPen(self.C_BEND))
                        p.drawText(QPointF(atx - atw_b / 2, aty), angle_text)
                        occupied_rects.append(rect_b)
                        bend_placed = True
                        break
                if bend_placed:
                    break
            if not bend_placed:
                atx = bsx + nx * 22
                aty = bsy + ny * 22
                p.setPen(QPen(self.C_BEND))
                p.drawText(QPointF(atx - atw_b / 2, aty), angle_text)
                occupied_rects.append((atx - atw_b / 2, aty - _lbl_h,
                                       atx + atw_b / 2, aty))

        # 中间直管段分界节点（绿色小圆点）
        for si, seg in enumerate(pipe_segs):
            if seg.segment_type in (SegmentType.BEND, SegmentType.FOLD):
                continue
            if not seg.coordinates:
                continue
            sp = transform(seg.coordinates[0][0], seg.coordinates[0][1])
            if si == 0:
                continue
            p.setPen(QPen(Qt.white, 1))
            p.setBrush(QBrush(self.C_NODE))
            p.drawEllipse(QPointF(*sp), 4, 4)

        # ===== 统一高程标注（碰撞检测避免重叠） =====
        elev_labels = []

        # 起点和终点
        if all_coords:
            elev_labels.append((screen_pts[0][0], screen_pts[0][1], all_coords[0][1], self.C_ELEV))
            elev_labels.append((screen_pts[-1][0], screen_pts[-1][1], all_coords[-1][1], self.C_ELEV))

        # 弯/折管转折点
        for seg in pipe_segs:
            if seg.segment_type not in (SegmentType.BEND, SegmentType.FOLD):
                continue
            if not seg.coordinates or len(seg.coordinates) < 2:
                continue
            if seg.segment_type == SegmentType.FOLD and len(seg.coordinates) >= 3:
                bend_x, bend_y = seg.coordinates[1]
            else:
                bend_x = (seg.coordinates[0][0] + seg.coordinates[-1][0]) / 2
                bend_y = (seg.coordinates[0][1] + seg.coordinates[-1][1]) / 2
            bsx2, bsy2 = transform(bend_x, bend_y)
            elev_labels.append((bsx2, bsy2, bend_y, self.C_ELEV))

        # 中间直管段分界点
        for si, seg in enumerate(pipe_segs):
            if seg.segment_type in (SegmentType.BEND, SegmentType.FOLD):
                continue
            if not seg.coordinates or si == 0:
                continue
            sp = transform(seg.coordinates[0][0], seg.coordinates[0][1])
            elev_labels.append((sp[0], sp[1], seg.coordinates[0][1], self.C_ELEV))

        # 最低点（红色高亮）
        if all_coords:
            min_elev_idx = ys.index(min(ys))
            if min_elev_idx != 0 and min_elev_idx != len(all_coords) - 1:
                sx_low, sy_low = screen_pts[min_elev_idx]
                elev_labels.append((sx_low, sy_low, min(ys), self.C_ELEV_LOW))

        # 按屏幕X坐标排序
        elev_labels.sort(key=lambda lbl: lbl[0])

        # 去重（屏幕距离 < 5px 的点只保留一个，优先保留红色标注）
        unique_labels = []
        for lbl in elev_labels:
            duplicate = False
            for j, existing in enumerate(unique_labels):
                dist = math.sqrt((lbl[0] - existing[0]) ** 2 + (lbl[1] - existing[1]) ** 2)
                if dist < 5:
                    if lbl[3] == self.C_ELEV_LOW:
                        unique_labels[j] = lbl
                    duplicate = True
                    break
            if not duplicate:
                unique_labels.append(lbl)

        # 绘制高程标注（碰撞检测避免重叠）
        drawn_rects = list(occupied_rects)
        base_offset_y = 16
        font_e = QFont("Microsoft YaHei", 8)
        p.setFont(font_e)

        for sx, sy, elev, color in unique_labels:
            text = f"▽{elev:.3f}m"
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(text)

            # 尝试多个位置避免重叠（含管线碰撞检测）
            attempts = [
                (sx, sy + base_offset_y, 'below'),
                (sx, sy - base_offset_y, 'above'),
                (sx, sy + base_offset_y + _lbl_h, 'below'),
                (sx, sy - base_offset_y - _lbl_h, 'above'),
                (sx + tw / 2 + 8, sy + base_offset_y, 'below'),
                (sx - tw / 2 - 8, sy - base_offset_y, 'above'),
                (sx, sy + base_offset_y + _lbl_h * 2, 'below'),
                (sx, sy - base_offset_y - _lbl_h * 2, 'above'),
            ]
            lx, ly, anchor = sx, sy + base_offset_y, 'below'
            placed = False
            for ax, ay, aa in attempts:
                if aa == 'below':
                    rect = (ax - tw / 2, ay, ax + tw / 2, ay + _lbl_h)
                else:
                    rect = (ax - tw / 2, ay - _lbl_h, ax + tw / 2, ay)
                overlap = False
                for dr in drawn_rects:
                    if rect[0] < dr[2] and rect[2] > dr[0] and rect[1] < dr[3] and rect[3] > dr[1]:
                        overlap = True
                        break
                if not overlap:
                    for lx1, ly1, lx2, ly2 in profile_pipe_lines:
                        if self._line_rect_intersect(lx1, ly1, lx2, ly2, rect):
                            overlap = True
                            break
                if not overlap:
                    lx, ly, anchor = ax, ay, aa
                    drawn_rects.append(rect)
                    placed = True
                    break
            if not placed:
                lx = sx
                ly = sy + base_offset_y + _lbl_h * 2
                anchor = 'below'
                drawn_rects.append((lx - tw / 2, ly, lx + tw / 2, ly + _lbl_h))

            p.setPen(QPen(color))
            if anchor == 'below':
                p.drawText(QPointF(lx - tw / 2, ly + _lbl_h - 2), text)
            else:
                p.drawText(QPointF(lx - tw / 2, ly - 2), text)

        # 进出口形状
        if screen_pts:
            self._draw_inlet_shape(p, screen_pts[0][0], screen_pts[0][1], scale)
            self._draw_outlet_shape(p, screen_pts[-1][0], screen_pts[-1][1], scale)

        # 底部信息
        total_len = sum(s.length for s in pipe_segs if s.length > 0)
        bend_cnt = sum(1 for s in pipe_segs if s.segment_type in (SegmentType.BEND, SegmentType.FOLD))
        min_elev = min(ys)
        info = (f"总长度: {total_len:.1f}m | 结构段: {len(pipe_segs)} | "
                f"弯/折管: {bend_cnt} | 最低高程: {min_elev:.2f}m | "
                f"缩放: {int(self._zoom * 100)}%")
        p.setPen(QPen(self.C_INFO))
        p.setFont(QFont("Microsoft YaHei", 9))
        p.drawText(QRectF(0, h - 22, w, 20), Qt.AlignCenter, info)

    # ---- 平面视图 ----

    def _draw_plan(self, p: QPainter, w, h):
        if not MODELS_AVAILABLE:
            self._draw_centered_text(p, w, h, "模型未加载")
            return

        fp_list = self._plan_feature_points
        if not fp_list or len(fp_list) < 2:
            if self._plan_segments:
                fp_list = self._gen_plan_coords()
            if not fp_list or len(fp_list) < 2:
                self._draw_centered_text(p, w, h, "暂无平面数据\n请从推求水面线导入平面管道信息")
                return

        xs = [fp.x for fp in fp_list]
        ys = [fp.y for fp in fp_list]
        bounds = (min(xs), max(xs), min(ys), max(ys))
        transform, scale = self._make_transform(bounds, w, h)
        screen_pts = [transform(fp.x, fp.y) for fp in fp_list]

        # 管道线
        pen = QPen(self.C_PIPE, 3)
        p.setPen(pen)
        for i in range(len(screen_pts) - 1):
            p.drawLine(QPointF(*screen_pts[i]), QPointF(*screen_pts[i + 1]))

        # 箭头
        for i in range(len(screen_pts) - 1):
            self._draw_arrow(p, screen_pts[i], screen_pts[i + 1], self.C_ARROW)

        # 预计算转角：当 turn_angle 未设置时从坐标自动计算
        computed_angles = [0.0] * len(fp_list)
        for i in range(1, len(fp_list) - 1):
            fp_prev = fp_list[i - 1]
            fp_cur = fp_list[i]
            fp_next = fp_list[i + 1]
            if fp_cur.turn_angle > 0:
                computed_angles[i] = fp_cur.turn_angle
            else:
                # 从坐标计算转角
                dx1 = fp_cur.x - fp_prev.x
                dy1 = fp_cur.y - fp_prev.y
                dx2 = fp_next.x - fp_cur.x
                dy2 = fp_next.y - fp_cur.y
                len1 = math.sqrt(dx1 * dx1 + dy1 * dy1)
                len2 = math.sqrt(dx2 * dx2 + dy2 * dy2)
                if len1 > 1e-6 and len2 > 1e-6:
                    cos_a = (dx1 * dx2 + dy1 * dy2) / (len1 * len2)
                    cos_a = max(-1.0, min(1.0, cos_a))
                    angle_deg = math.degrees(math.acos(cos_a))
                    if angle_deg > 0.5:
                        computed_angles[i] = round(angle_deg, 1)

        # 节点（只绘制圆圈）
        for i, (fp, sp) in enumerate(zip(fp_list, screen_pts)):
            is_start = (i == 0)
            is_end = (i == len(fp_list) - 1)
            is_bend = (fp.turn_type != TurnType.NONE and fp.turn_angle != 0) or computed_angles[i] > 0

            if is_start or is_end:
                r, color = 7, self.C_INLET
            elif is_bend:
                r, color = 5, self.C_BEND
            else:
                r, color = 5, self.C_NODE

            p.setPen(QPen(Qt.white, 1))
            p.setBrush(QBrush(color))
            p.drawEllipse(QPointF(*sp), r, r)

        # ---- 标签智能布局（碰撞检测，避免文字与管线/文字重叠） ----
        occupied = []

        # 根据节点间屏幕距离动态调整标签大小
        if len(screen_pts) > 1:
            _total_sd = sum(
                math.sqrt((screen_pts[k + 1][0] - screen_pts[k][0]) ** 2 +
                          (screen_pts[k + 1][1] - screen_pts[k][1]) ** 2)
                for k in range(len(screen_pts) - 1)
            )
            avg_sd = _total_sd / (len(screen_pts) - 1)
        else:
            avg_sd = 200.0
        # 标签缩放因子：节点间距≥120px时为1.0，最小缩至0.45
        label_scale = min(1.0, max(0.45, avg_sd / 120.0))
        # 节点间距过密时隐藏弯管节点的MC桩号
        show_mc_for_bends = avg_sd >= 60

        # 节点圆圈区域标记为已占用
        for i, sp in enumerate(screen_pts):
            r = max(4, int((8 if (i == 0 or i == len(screen_pts) - 1) else 6) * label_scale))
            occupied.append((sp[0] - r, sp[1] - r, sp[0] + r, sp[1] + r))

        # 管线段用于碰撞检测
        plan_pipe_lines = [(screen_pts[k][0], screen_pts[k][1],
                            screen_pts[k + 1][0], screen_pts[k + 1][1])
                           for k in range(len(screen_pts) - 1)]

        # 收集所有待放置标签: (anchor_x, anchor_y, text, color, font_size)
        pending = []
        for i, (fp, sp) in enumerate(zip(fp_list, screen_pts)):
            is_start = (i == 0)
            is_end = (i == len(fp_list) - 1)
            is_bend = (fp.turn_type != TurnType.NONE and fp.turn_angle != 0) or computed_angles[i] > 0
            if is_start:
                pending.append((sp[0], sp[1], "进水口", self.C_INLET, 9))
                pending.append((sp[0], sp[1], f"MC {fp.chainage:.3f}", self.C_ELEV, 8))
            elif is_end:
                pending.append((sp[0], sp[1], "出水口", self.C_INLET, 9))
                pending.append((sp[0], sp[1], f"MC {fp.chainage:.3f}", self.C_ELEV, 8))
            elif is_bend:
                pending.append((sp[0], sp[1], f"α={computed_angles[i]:.3f}°", self.C_BEND, 8))
                if show_mc_for_bends:
                    pending.append((sp[0], sp[1], f"MC {fp.chainage:.3f}", self.C_ELEV, 8))

        for ax, ay, text, color, font_size in pending:
            scaled_fs = max(6, int(font_size * label_scale + 0.5))
            ft = QFont("Microsoft YaHei", scaled_fs)
            p.setFont(ft)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(text)
            th = fm.height()
            pad = 3
            gap = max(4, int(12 * label_scale))
            gap2 = max(3, int(8 * label_scale))
            gap3 = max(6, int(20 * label_scale))

            # 多方向候选位置 (center_offset_x, center_offset_y)
            cands = [
                (0, -(th / 2 + gap)),
                (0, th / 2 + gap),
                (tw / 2 + gap, 0),
                (-(tw / 2 + gap), 0),
                (tw / 2 + gap2, -(th / 2 + gap2)),
                (tw / 2 + gap2, th / 2 + gap2),
                (-(tw / 2 + gap2), -(th / 2 + gap2)),
                (-(tw / 2 + gap2), th / 2 + gap2),
                (0, -(th / 2 + gap * 2)),
                (0, th / 2 + gap * 2),
                (tw / 2 + gap3, -(th / 2 + gap)),
                (-(tw / 2 + gap3), -(th / 2 + gap)),
            ]

            # 遍历所有候选位置，选距锚点最近且不碰撞的
            best = None
            best_dist = float('inf')
            for cdx, cdy in cands:
                cx = ax + cdx
                cy = ay + cdy
                rect = (cx - tw / 2 - pad, cy - th / 2 - pad,
                        cx + tw / 2 + pad, cy + th / 2 + pad)
                overlap = any(
                    rect[0] < dr[2] and rect[2] > dr[0] and
                    rect[1] < dr[3] and rect[3] > dr[1]
                    for dr in occupied
                )
                if not overlap:
                    overlap = any(
                        self._line_rect_intersect(lx1, ly1, lx2, ly2, rect)
                        for lx1, ly1, lx2, ly2 in plan_pipe_lines
                    )
                if not overlap:
                    dist = cdx * cdx + cdy * cdy
                    if dist < best_dist:
                        best_dist = dist
                        best = (cx, cy, rect)

            placed = False
            if best:
                cx, cy, rect = best
                occupied.append(rect)
                p.setPen(QPen(color))
                p.setFont(ft)
                p.drawText(QPointF(cx - tw / 2,
                                   cy + (fm.ascent() - fm.descent()) / 2), text)
                placed = True

            if not placed:
                cy = ay - th / 2 - 50
                rect = (ax - tw / 2 - pad, cy - th / 2 - pad,
                        ax + tw / 2 + pad, cy + th / 2 + pad)
                occupied.append(rect)
                p.setPen(QPen(color))
                p.setFont(ft)
                p.drawText(QPointF(ax - tw / 2,
                                   cy + (fm.ascent() - fm.descent()) / 2), text)

        # 底部信息
        plan_len = self._plan_total_length if self._plan_total_length > 0 else sum(
            s.length for s in self._plan_segments if s.length > 0)
        bend_cnt = sum(1 for a in computed_angles if a > 0)
        info = f"平面总长: {plan_len:.1f}m | IP点: {len(fp_list)} | 弯管: {bend_cnt} | 缩放: {int(self._zoom * 100)}%"
        p.setPen(QPen(self.C_INFO))
        p.setFont(QFont("Microsoft YaHei", 9))
        p.drawText(QRectF(0, h - 22, w, 20), Qt.AlignCenter, info)

    # ---- 简化示意图 ----

    def _draw_simplified(self, p: QPainter, w, h):
        margin = 50
        total_len = sum(s.length for s in self._segments if s.length > 0) or 100
        H_bottom = 95.0
        depth = 5

        pts = []
        for t_frac in [0, 0.15, 0.3, 0.45, 0.5, 0.55, 0.7, 0.85, 1.0]:
            x = t_frac * total_len
            y = H_bottom - depth * math.sin(math.pi * t_frac)
            pts.append((x, y))

        xs = [c[0] for c in pts]
        ys = [c[1] for c in pts]
        bounds = (min(xs), max(xs), min(ys) - 2, max(ys) + 5)
        transform, scale = self._make_transform(bounds, w, h, margin)
        spts = [transform(c[0], c[1]) for c in pts]

        # 管道曲线
        pen = QPen(self.C_PIPE, 3)
        p.setPen(pen)
        path = QPainterPath(QPointF(*spts[0]))
        for i in range(1, len(spts)):
            path.lineTo(QPointF(*spts[i]))
        p.drawPath(path)

        # 起止标记
        if spts:
            self._draw_endpoint(p, spts[0], "进水口", True)
            self._draw_endpoint(p, spts[-1], "出水口", False)

        # 渠底参考线
        bl = transform(pts[0][0], H_bottom)
        br = transform(pts[-1][0], H_bottom)
        pen2 = QPen(QColor(100, 100, 100), 1, Qt.DashLine)
        p.setPen(pen2)
        p.drawLine(QPointF(*bl), QPointF(*br))
        p.setPen(QPen(self.C_HINT))
        ft = QFont("Microsoft YaHei", 8)
        p.setFont(ft)
        p.drawText(QPointF(bl[0] + 5, bl[1] + 14), "渠底高程")

        # 底部信息
        info = f"总长度: {total_len:.1f}m | 结构段: {len(self._segments)} | 缩放: {int(self._zoom * 100)}%"
        p.setPen(QPen(self.C_INFO))
        p.setFont(QFont("Microsoft YaHei", 9))
        p.drawText(QRectF(0, h - 22, w, 20), Qt.AlignCenter, info)

    # ---- 绘图工具 ----

    def _draw_centered_text(self, p: QPainter, w, h, text):
        p.setPen(QPen(self.C_HINT))
        p.setFont(QFont("Microsoft YaHei", 11))
        p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, text)

    def _draw_arrow(self, p: QPainter, pt1, pt2, color):
        x1, y1 = pt1
        x2, y2 = pt2
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        dx, dy = x2 - x1, y2 - y1
        seg_len = math.sqrt(dx * dx + dy * dy)
        if seg_len < 30:
            return
        ux, uy = dx / seg_len, dy / seg_len
        sz = 8
        px, py = -uy, ux
        tri = QPolygonF([
            QPointF(mx + ux * sz, my + uy * sz),
            QPointF(mx - ux * sz * 0.5 + px * sz * 0.5, my - uy * sz * 0.5 + py * sz * 0.5),
            QPointF(mx - ux * sz * 0.5 - px * sz * 0.5, my - uy * sz * 0.5 - py * sz * 0.5),
        ])
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        p.drawPolygon(tri)

    def _draw_endpoint(self, p: QPainter, pt, label, is_inlet):
        sx, sy = pt
        p.setPen(QPen(Qt.white, 1))
        p.setBrush(QBrush(self.C_INLET))
        p.drawEllipse(QPointF(sx, sy), 7, 7)
        p.setPen(QPen(self.C_INLET))
        p.setFont(QFont("Microsoft YaHei", 9))
        p.drawText(QPointF(sx - 16, sy - 18), label)

    def _draw_inlet_shape(self, p: QPainter, x, y, scale):
        """绘制进水口形状（纵剖面视图，按表L.1.4-2）"""
        inlet_shape = None
        if self._segments and self._segments[0].segment_type == SegmentType.INLET:
            inlet_shape = getattr(self._segments[0], 'inlet_shape', None)
        if inlet_shape is None:
            inlet_shape = InletOutletShape.SLIGHTLY_ROUNDED

        base_size = max(12, 20 * min(self._zoom, 2.0))
        wall_length = base_size * 2.0
        wall_thickness = 3
        pipe_half_height = base_size * 0.4
        pen = QPen(self.C_PIPE, wall_thickness)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        if inlet_shape == InletOutletShape.FULLY_ROUNDED:
            curve_length = base_size * 1.2
            # 上部外壁
            p.drawLine(QPointF(x - wall_length, y - base_size),
                       QPointF(x - curve_length, y - base_size))
            # 圆弧曲线
            path = QPainterPath(QPointF(x - curve_length, y - base_size))
            for i in range(1, 15):
                t = i / 14.0
                cx_ = x - curve_length + curve_length * t
                cy_ = y - base_size + (base_size - pipe_half_height) * (t ** 0.5)
                path.lineTo(QPointF(cx_, cy_))
            p.drawPath(path)
            # 下部平直
            p.drawLine(QPointF(x - wall_length, y + pipe_half_height),
                       QPointF(x, y + pipe_half_height))
        elif inlet_shape == InletOutletShape.SLIGHTLY_ROUNDED:
            curve_length = base_size * 0.6
            p.drawLine(QPointF(x - wall_length, y - base_size),
                       QPointF(x - curve_length, y - base_size))
            path = QPainterPath(QPointF(x - curve_length, y - base_size))
            for i in range(1, 10):
                t = i / 9.0
                cx_ = x - curve_length + curve_length * t
                cy_ = y - base_size + (base_size - pipe_half_height) * (t ** 0.3)
                path.lineTo(QPointF(cx_, cy_))
            p.drawPath(path)
            p.drawLine(QPointF(x - wall_length, y + pipe_half_height),
                       QPointF(x, y + pipe_half_height))
        elif inlet_shape == InletOutletShape.NOT_ROUNDED:
            p.drawLine(QPointF(x - wall_length, y - base_size),
                       QPointF(x, y - base_size))
            p.drawLine(QPointF(x, y - base_size),
                       QPointF(x, y - pipe_half_height))
            p.drawLine(QPointF(x - wall_length, y + pipe_half_height),
                       QPointF(x, y + pipe_half_height))

        # 斜线填充
        self._draw_hatch_lines(p, x - wall_length, y - base_size - 5,
                               x - (0 if inlet_shape == InletOutletShape.NOT_ROUNDED else base_size * 0.6),
                               y - base_size)

    def _draw_outlet_shape(self, p: QPainter, x, y, scale):
        """绘制出水口形状（纵剖面视图，向右延伸，镜像于进水口）"""
        outlet_shape = None
        if self._segments and self._segments[-1].segment_type == SegmentType.OUTLET:
            outlet_shape = getattr(self._segments[-1], 'outlet_shape', None)
        if outlet_shape is None:
            outlet_shape = InletOutletShape.SLIGHTLY_ROUNDED

        base_size = max(12, 20 * min(self._zoom, 2.0))
        wall_length = base_size * 2.0
        wall_thickness = 3
        pipe_half_height = base_size * 0.4
        pen = QPen(self.C_PIPE, wall_thickness)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        if outlet_shape == InletOutletShape.FULLY_ROUNDED:
            curve_length = base_size * 1.2
            p.drawLine(QPointF(x + curve_length, y - base_size),
                       QPointF(x + wall_length, y - base_size))
            # 圆弧过渡
            path = QPainterPath(QPointF(x, y - pipe_half_height))
            for i in range(1, 15):
                t = i / 14.0
                cx_ = x + curve_length * t
                cy_ = y - pipe_half_height - (base_size - pipe_half_height) * (t ** 0.5) + (base_size - pipe_half_height)
                path.lineTo(QPointF(cx_, cy_))
            p.drawPath(path)
            p.drawLine(QPointF(x, y + pipe_half_height),
                       QPointF(x + wall_length, y + pipe_half_height))
        elif outlet_shape == InletOutletShape.SLIGHTLY_ROUNDED:
            curve_length = base_size * 0.6
            p.drawLine(QPointF(x + curve_length, y - base_size),
                       QPointF(x + wall_length, y - base_size))
            path = QPainterPath(QPointF(x, y - pipe_half_height))
            for i in range(1, 10):
                t = i / 9.0
                cx_ = x + curve_length * t
                cy_ = y - pipe_half_height - (base_size - pipe_half_height) * (t ** 0.3) + (base_size - pipe_half_height)
                path.lineTo(QPointF(cx_, cy_))
            p.drawPath(path)
            p.drawLine(QPointF(x, y + pipe_half_height),
                       QPointF(x + wall_length, y + pipe_half_height))
        elif outlet_shape == InletOutletShape.NOT_ROUNDED:
            p.drawLine(QPointF(x, y - base_size),
                       QPointF(x + wall_length, y - base_size))
            p.drawLine(QPointF(x, y - base_size),
                       QPointF(x, y - pipe_half_height))
            p.drawLine(QPointF(x, y + pipe_half_height),
                       QPointF(x + wall_length, y + pipe_half_height))

        # 斜线填充
        hatch_x1 = x + (0 if outlet_shape == InletOutletShape.NOT_ROUNDED else base_size * 0.6)
        self._draw_hatch_lines(p, hatch_x1, y - base_size - 5,
                               x + wall_length, y - base_size)

    def _draw_hatch_lines(self, p: QPainter, x1, y1, x2, y2):
        """绘制斜线填充表示墙体截面"""
        spacing = 6
        num_lines = int(abs(x2 - x1) / spacing) if abs(x2 - x1) > 0 else 0
        pen = QPen(self.C_PIPE, 1)
        p.setPen(pen)
        for i in range(num_lines + 1):
            lx = min(x1, x2) + i * spacing
            if lx > max(x1, x2):
                break
            p.drawLine(QPointF(lx, y2), QPointF(lx + 5, y1))

    def _line_rect_intersect(self, x1, y1, x2, y2, rect):
        """检查线段(x1,y1)-(x2,y2)是否与矩形rect(left,top,right,bottom)相交"""
        left, top, right, bottom = rect
        if left <= x1 <= right and top <= y1 <= bottom:
            return True
        if left <= x2 <= right and top <= y2 <= bottom:
            return True
        edges = [
            (left, top, right, top),
            (right, top, right, bottom),
            (left, bottom, right, bottom),
            (left, top, left, bottom),
        ]
        for ex1, ey1, ex2, ey2 in edges:
            if self._segs_cross(x1, y1, x2, y2, ex1, ey1, ex2, ey2):
                return True
        return False

    @staticmethod
    def _segs_cross(x1, y1, x2, y2, x3, y3, x4, y4):
        """判断两线段是否相交"""
        d1x, d1y = x2 - x1, y2 - y1
        d2x, d2y = x4 - x3, y4 - y3
        cross = d1x * d2y - d1y * d2x
        if abs(cross) < 1e-10:
            return False
        t = ((x3 - x1) * d2y - (y3 - y1) * d2x) / cross
        u = ((x3 - x1) * d1y - (y3 - y1) * d1x) / cross
        return 0 <= t <= 1 and 0 <= u <= 1

    def _gen_plan_coords(self):
        """从平面段生成近似特征点"""
        if not self._plan_segments:
            return []
        if not MODELS_AVAILABLE:
            return []

        coords = []
        cx, cy = 0.0, 0.0
        az = 0.0
        idx = 0
        coords.append(PlanFeaturePoint(x=cx, y=cy, azimuth_meas_deg=math.degrees(az),
                                        ip_index=idx, chainage=0.0))
        cum_len = 0.0
        for seg in self._plan_segments:
            length = seg.length if seg.length > 0 else 0
            if seg.segment_type == SegmentType.STRAIGHT:
                cx += length * math.cos(az)
                cy += length * math.sin(az)
                cum_len += length
                idx += 1
                coords.append(PlanFeaturePoint(x=cx, y=cy, azimuth_meas_deg=math.degrees(az),
                                                ip_index=idx, chainage=cum_len))
            elif seg.segment_type == SegmentType.BEND:
                angle_rad = math.radians(seg.angle) if seg.angle else 0
                cx += length * math.cos(az + angle_rad / 2)
                cy += length * math.sin(az + angle_rad / 2)
                az += angle_rad
                cum_len += length
                idx += 1
                coords.append(PlanFeaturePoint(
                    x=cx, y=cy, azimuth_meas_deg=math.degrees(az),
                    turn_angle=seg.angle, turn_radius=seg.radius,
                    turn_type=TurnType.ARC if seg.radius > 0 else TurnType.FOLD,
                    ip_index=idx, chainage=cum_len))
        return coords
