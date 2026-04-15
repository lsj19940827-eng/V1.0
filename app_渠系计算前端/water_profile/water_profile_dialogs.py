# -*- coding: utf-8 -*-
"""
水面线面板辅助对话框

包含：
- BuildingLengthDialog: 建筑物长度统计对话框
- BatchChannelConfirmDialog: 批量补段插入确认对话框
- OpenChannelDialog: 补段参数选择对话框（逐一弹窗模式）
- PressurePipeConfigDialog: 有压管道计算配置对话框
"""

import copy
import math
import datetime
from collections import Counter
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QGroupBox, QGridLayout, QComboBox, QLineEdit,
    QRadioButton, QButtonGroup, QSplitter, QApplication,
    QSizePolicy, QTabWidget, QCheckBox, QScrollArea, QFrame, QStackedWidget
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QColor, QShortcut, QKeySequence

from app_渠系计算前端.styles import auto_resize_table, fluent_info, fluent_error, fluent_question
from 推求水面线.models.data_models import OpenChannelParams
from 推求水面线.utils.pressure_pipe_common import coerce_row_index

try:
    from qfluentwidgets import PushButton, PrimaryPushButton, LineEdit, ComboBox
except ImportError:
    PushButton = QPushButton
    PrimaryPushButton = QPushButton
    LineEdit = QLineEdit
    ComboBox = QComboBox


def _build_longitudinal_dxf_import_guidance_text() -> str:
    """返回纵断面 DXF 导入前说明文案。"""
    return (
        "合格的纵断面 DXF 需要满足：\n"
        "1. DXF 文件里有可识别的纵断面管道中心线，建议只保留这一根多段线。\n"
        "2. 该轴线按 1:1 绘制，其中 Y 为管道中心线的真实高程（米）。\n"
        "3. 若文件里有多条相近多段线，系统会优先识别更像纵断面的那条，必要时会请你确认。\n"
        "4. 为提高识别成功率，建议把纵断面放在“纵断”或“纵剖”等清晰图层。"
    )


# ============================================================
# 正常水深计算（曼宁公式）
# ============================================================
def calculate_normal_depth(Q, B, m, n, i, D=0.0):
    """计算明渠正常水深（曼宁公式），支持梯形/矩形/圆形断面"""
    if Q <= 0 or n <= 0 or i <= 0:
        return 0.0
    # 圆形断面
    if D > 0 and B <= 0:
        h_low, h_high = 0.001, D * 0.95
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
            Q_calc = (1.0 / n) * A * (R_hyd ** (2.0 / 3.0)) * math.sqrt(i)
            if abs(Q_calc - Q) / max(Q, 1e-10) < 1e-6:
                return h
            if Q_calc < Q:
                h_low = h
            else:
                h_high = h
        return (h_low + h_high) / 2
    # 梯形/矩形断面
    if B <= 0:
        return 0.0
    h = 1.0
    for _ in range(100):
        A = (B + m * h) * h
        P = B + 2 * h * math.sqrt(1 + m * m)
        R = A / P if P > 0 else 0
        if R <= 0:
            h *= 1.5
            continue
        Q_calc = A * (1 / n) * (R ** (2.0 / 3.0)) * math.sqrt(i)
        f = Q_calc - Q
        if abs(f) < 1e-6:
            return h
        dA = B + 2 * m * h
        dP = 2 * math.sqrt(1 + m * m)
        dR = (dA * P - A * dP) / (P * P) if P > 0 else 0
        dQ = (dA * (R ** (2.0 / 3.0)) + A * (2.0 / 3.0) * (R ** (-1.0 / 3.0)) * dR) * (1 / n) * math.sqrt(i)
        if abs(dQ) < 1e-10:
            h *= 1.1
            continue
        h_new = h - f / dQ
        h = h_new if h_new > 0 else h / 2
    return h


TRANSITION_FILLER_TYPES = ["明渠-梯形", "明渠-矩形", "明渠-圆形", "明渠-U形", "暗涵-矩形", "暗涵-圆拱直墙型"]
MANUAL_TRANSITION_FILLER_TYPES = [item for item in TRANSITION_FILLER_TYPES if item != "暗涵-圆拱直墙型"]


def normalize_transition_structure_type(structure_type: str) -> str:
    aliases = {
        "矩形": "明渠-矩形",
        "暗涵": "暗涵-矩形",
        "暗渠": "暗涵-矩形",
        "矩形暗渠": "暗涵-矩形",
        "矩形暗涵": "暗涵-矩形",
        "圆拱直墙型暗涵": "暗涵-圆拱直墙型",
        "暗涵圆拱直墙型": "暗涵-圆拱直墙型",
    }
    return aliases.get(structure_type or "", structure_type or "")


def is_transition_culvert_type(structure_type: str) -> bool:
    return normalize_transition_structure_type(structure_type) in {"暗涵-矩形", "暗涵-圆拱直墙型"}


def is_transition_arch_culvert_type(structure_type: str) -> bool:
    return normalize_transition_structure_type(structure_type) == "暗涵-圆拱直墙型"


def is_transition_u_channel_type(structure_type: str) -> bool:
    return normalize_transition_structure_type(structure_type) == "明渠-U形"


def is_transition_circular_channel_type(structure_type: str) -> bool:
    return normalize_transition_structure_type(structure_type) == "明渠-圆形"


def describe_transition_gap_source(gap: Dict[str, Any]) -> str:
    reference = gap.get("reference_segment") or gap.get("upstream_channel")
    if not reference:
        return "需手动填写"
    structure_type = normalize_transition_structure_type(reference.get("structure_type", ""))
    family_label = "暗渠" if is_transition_culvert_type(structure_type) else "明渠"
    scope_label = "同段" if reference.get("flow_section") == gap.get("flow_section") else "跨段"
    return f"自动推荐-{scope_label}{family_label}"


def build_transition_fill_params(
    structure_type: str,
    B: float,
    m: float,
    H: float,
    n: float,
    slope_inv: float,
    Q: float,
    flow_section: str,
    upstream_channel: Optional[Dict[str, Any]] = None,
    theta_deg: float = 180.0,
) -> Optional[OpenChannelParams]:
    structure_type = normalize_transition_structure_type(structure_type)
    slope_i = 1.0 / slope_inv if slope_inv > 0 else 0.0

    if Q <= 0 or n <= 0 or slope_i <= 0:
        return None

    if is_transition_culvert_type(structure_type):
        if B <= 0 or H <= 0:
            return None
        if is_transition_arch_culvert_type(structure_type):
            theta_value = (upstream_channel or {}).get("theta_deg", theta_deg) or theta_deg or 180.0
            h, ok = solve_water_depth_horseshoe(B, H, math.radians(theta_value), n, slope_i, Q)
        else:
            theta_value = 0.0
            h, ok = solve_water_depth_rectangular(B, H, n, slope_i, Q)
        if (not ok or h <= 0) and upstream_channel:
            h = upstream_channel.get("water_depth", 0.0)
        if h <= 0:
            return None
        return OpenChannelParams(
            name="-",
            structure_type=structure_type,
            bottom_width=B,
            water_depth=h,
            side_slope=0.0,
            roughness=n,
            slope_inv=slope_inv,
            flow=Q,
            flow_section=flow_section,
            structure_height=H,
            theta_deg=theta_value,
        )

    if B <= 0 and not is_transition_circular_channel_type(structure_type) and not is_transition_u_channel_type(structure_type):
        return None

    if is_transition_u_channel_type(structure_type) and B <= 0:
        return None

    D_param = B if is_transition_circular_channel_type(structure_type) else 0.0
    B_param = 0.0 if is_transition_circular_channel_type(structure_type) or is_transition_u_channel_type(structure_type) else B
    side_slope = m if structure_type == "明渠-梯形" else 0.0
    h = calculate_normal_depth(Q, B_param, side_slope, n, slope_i, D=D_param)
    if h <= 0 and upstream_channel:
        h = upstream_channel.get("water_depth", 0.0)
    if h <= 0:
        return None

    structure_height = upstream_channel.get("structure_height", 0.0) if upstream_channel else 0.0
    if is_transition_u_channel_type(structure_type):
        return OpenChannelParams(
            name="-",
            structure_type=structure_type,
            bottom_width=0.0,
            water_depth=h,
            side_slope=0.0,
            roughness=n,
            slope_inv=slope_inv,
            flow=Q,
            flow_section=flow_section,
            structure_height=structure_height,
            arc_radius=B,
            theta_deg=(upstream_channel or {}).get("theta_deg", 0.0),
        )

    return OpenChannelParams(
        name="-",
        structure_type=structure_type,
        bottom_width=B,
        water_depth=h,
        side_slope=side_slope,
        roughness=n,
        slope_inv=slope_inv,
        flow=Q,
        flow_section=flow_section,
        structure_height=structure_height,
    )


from 矩形暗涵设计 import solve_water_depth_rectangular
from 隧洞设计 import solve_water_depth_horseshoe

from PySide6.QtGui import (
    QPainter, QPen, QBrush, QPolygonF,
    QWheelEvent, QMouseEvent, QPaintEvent
)
from PySide6.QtCore import QPointF, QRectF


# ============================================================
# 轻量级纵断面画布 —— 用于有压管道纵断面预览
# ============================================================
_TURN_TYPE_CN = {"NONE": "无", "ARC": "圆弧", "FOLD": "折线",
                 "无": "无", "圆弧": "圆弧", "折线": "折线"}


class SimpleProfileCanvas(QWidget):
    """
    轻量级管道可视化画布，支持纵断面/平面图双视图切换、缩放、平移。
    直接工作在节点字典数据上，无需 StructureSegment 模型。
    """

    view_changed = Signal(str)
    zoom_changed = Signal(float)
    open_detail_requested = Signal()

    C_BG = QColor(20, 20, 30)
    C_PIPE = QColor(0, 255, 0)
    C_ARROW = QColor(0, 204, 0)
    C_INLET = QColor(0, 255, 255)
    C_BEND = QColor(255, 170, 0)
    C_NODE = QColor(0, 255, 0)
    C_ELEV = QColor(170, 170, 170)
    C_ELEV_LOW = QColor(255, 136, 136)
    C_INFO = QColor(170, 170, 170)
    C_HINT = QColor(136, 136, 136)
    C_GRID = QColor(40, 40, 50)

    def __init__(self, parent=None, fixed_height=None):
        super().__init__(parent)
        if fixed_height:
            self.setFixedHeight(fixed_height)
        else:
            self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

        self._view_mode = "plan"
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._drag_start = None
        self._drag_pan_start = None
        self._nodes = []
        self._ip_points = []

    # ---- 公共接口 ----

    def set_nodes(self, nodes):
        self._nodes = nodes or []
        if self._view_mode == "profile":
            self._zoom = 1.0
            self._pan_x = 0.0
            self._pan_y = 0.0
        self.update()

    def set_ip_points(self, ip_points):
        self._ip_points = ip_points or []
        if self._view_mode == "plan":
            self._zoom = 1.0
            self._pan_x = 0.0
            self._pan_y = 0.0
        self.update()

    def set_view_mode(self, mode):
        if mode in ("profile", "plan") and mode != self._view_mode:
            self._view_mode = mode
            self._zoom = 1.0
            self._pan_x = 0.0
            self._pan_y = 0.0
            self.update()
            self.view_changed.emit(mode)

    def get_view_mode(self):
        return self._view_mode

    def has_plan_data(self):
        return len(self._ip_points) >= 2

    def has_profile_data(self):
        return len(self._nodes) >= 2

    def zoom_reset(self):
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self.update()
        self.zoom_changed.emit(self._zoom)

    def get_zoom_percent(self):
        return int(self._zoom * 100)

    # ---- 事件 ----

    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
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

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and (self.has_plan_data() or self.has_profile_data()):
            self.open_detail_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ---- 缩放 ----

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

    def _make_transform(self, data_bounds, w, h, margin=50):
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

    # ---- 绘制 ----

    def _draw_profile(self, p, w, h):
        nodes = self._nodes
        if not nodes or len(nodes) < 2:
            self._draw_centered_text(p, w, h, "暂无纵断面数据\n请导入纵断面DXF")
            return

        coords = [(n['chainage'], n['elevation']) for n in nodes]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        bounds = (min(xs), max(xs), min(ys), max(ys))
        transform, scale = self._make_transform(bounds, w, h)
        screen_pts = [transform(c[0], c[1]) for c in coords]

        pipe_lines = [(screen_pts[k][0], screen_pts[k][1],
                       screen_pts[k + 1][0], screen_pts[k + 1][1])
                      for k in range(len(screen_pts) - 1)]

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
            self._draw_endpoint(p, screen_pts[0], "起点", True)
            occupied_rects.append((screen_pts[0][0] - 30, screen_pts[0][1] - 18 - _lbl_h,
                                   screen_pts[0][0] + 30, screen_pts[0][1] - 18))
            self._draw_endpoint(p, screen_pts[-1], "终点", False)
            occupied_rects.append((screen_pts[-1][0] - 30, screen_pts[-1][1] - 18 - _lbl_h,
                                   screen_pts[-1][0] + 30, screen_pts[-1][1] - 18))

        # 弯折点标记
        for i, node in enumerate(nodes):
            tt = node.get('turn_type', 'NONE')
            angle = node.get('turn_angle', 0.0)
            if tt in ('NONE', '无') or angle == 0:
                if i > 0 and i < len(nodes) - 1:
                    p.setPen(QPen(Qt.white, 1))
                    p.setBrush(QBrush(self.C_NODE))
                    p.drawEllipse(QPointF(*screen_pts[i]), 4, 4)
                continue
            sx, sy = screen_pts[i]
            p.setPen(QPen(Qt.white, 1))
            p.setBrush(QBrush(self.C_BEND))
            p.drawEllipse(QPointF(sx, sy), 5, 5)

            tt_cn = _TURN_TYPE_CN.get(tt, tt)
            angle_text = f"{tt_cn} {angle:.1f}°"
            ft = QFont("Microsoft YaHei", 8)
            p.setFont(ft)
            fm_b = p.fontMetrics()
            atw = fm_b.horizontalAdvance(angle_text)

            # 标注方向：根据前后段计算法线
            if i > 0 and i < len(nodes) - 1:
                v1x, v1y = sx - screen_pts[i - 1][0], sy - screen_pts[i - 1][1]
                v2x, v2y = screen_pts[i + 1][0] - sx, screen_pts[i + 1][1] - sy
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
            else:
                nx, ny = 0, -1

            bend_placed = False
            for lbl_off in [22, 36, 50]:
                for d in [1, -1]:
                    atx = sx + nx * d * lbl_off
                    aty = sy + ny * d * lbl_off
                    rect_b = (atx - atw / 2, aty - _lbl_h, atx + atw / 2, aty)
                    overlap = any(
                        rect_b[0] < dr[2] and rect_b[2] > dr[0] and
                        rect_b[1] < dr[3] and rect_b[3] > dr[1]
                        for dr in occupied_rects
                    )
                    if not overlap:
                        overlap = any(
                            self._line_rect_intersect(lx1, ly1, lx2, ly2, rect_b)
                            for lx1, ly1, lx2, ly2 in pipe_lines
                        )
                    if not overlap:
                        p.setPen(QPen(self.C_BEND))
                        p.drawText(QPointF(atx - atw / 2, aty), angle_text)
                        occupied_rects.append(rect_b)
                        bend_placed = True
                        break
                if bend_placed:
                    break
            if not bend_placed:
                atx = sx + nx * 22
                aty = sy + ny * 22
                p.setPen(QPen(self.C_BEND))
                p.drawText(QPointF(atx - atw / 2, aty), angle_text)
                occupied_rects.append((atx - atw / 2, aty - _lbl_h, atx + atw / 2, aty))

        # 高程标注
        elev_labels = []
        if coords:
            elev_labels.append((screen_pts[0][0], screen_pts[0][1], coords[0][1], self.C_ELEV))
            elev_labels.append((screen_pts[-1][0], screen_pts[-1][1], coords[-1][1], self.C_ELEV))
        for i, node in enumerate(nodes):
            tt = node.get('turn_type', 'NONE')
            angle = node.get('turn_angle', 0.0)
            if tt not in ('NONE', '无') and angle != 0:
                elev_labels.append((screen_pts[i][0], screen_pts[i][1], coords[i][1], self.C_ELEV))
        if coords:
            min_elev_idx = ys.index(min(ys))
            if min_elev_idx != 0 and min_elev_idx != len(coords) - 1:
                elev_labels.append((screen_pts[min_elev_idx][0], screen_pts[min_elev_idx][1],
                                    min(ys), self.C_ELEV_LOW))

        elev_labels.sort(key=lambda lbl: lbl[0])
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

        drawn_rects = list(occupied_rects)
        base_offset_y = 16
        font_e = QFont("Microsoft YaHei", 8)
        p.setFont(font_e)

        for sx, sy, elev, color in unique_labels:
            text = f"▽{elev:.3f}m"
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(text)

            attempts = [
                (sx, sy + base_offset_y, 'below'),
                (sx, sy - base_offset_y, 'above'),
                (sx, sy + base_offset_y + _lbl_h, 'below'),
                (sx, sy - base_offset_y - _lbl_h, 'above'),
                (sx + tw / 2 + 8, sy + base_offset_y, 'below'),
                (sx - tw / 2 - 8, sy - base_offset_y, 'above'),
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
                    for lx1, ly1, lx2, ly2 in pipe_lines:
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

        # 底部信息
        total_len = coords[-1][0] - coords[0][0] if coords else 0
        bend_cnt = sum(1 for n in nodes if n.get('turn_type', 'NONE') not in ('NONE', '无')
                       and n.get('turn_angle', 0) != 0)
        min_elev = min(ys) if ys else 0
        info = (f"桩号: {coords[0][0]:.1f}~{coords[-1][0]:.1f}m | "
                f"节点: {len(nodes)} | 弯/折: {bend_cnt} | "
                f"最低高程: {min_elev:.2f}m | 缩放: {int(self._zoom * 100)}%")
        p.setPen(QPen(self.C_INFO))
        p.setFont(QFont("Microsoft YaHei", 9))
        p.drawText(QRectF(0, h - 22, w, 20), Qt.AlignCenter, info)

    # ---- 平面视图 ----

    def _draw_plan(self, p, w, h):
        ip_list = self._ip_points
        if not ip_list or len(ip_list) < 2:
            self._draw_centered_text(p, w, h, "暂无平面数据\n有压管道至少需要2个IP点")
            return

        xs = [pt['x'] for pt in ip_list]
        ys = [pt['y'] for pt in ip_list]
        bounds = (min(xs), max(xs), min(ys), max(ys))
        transform, scale = self._make_transform(bounds, w, h)
        screen_pts = [transform(pt['x'], pt['y']) for pt in ip_list]

        # 计算累计桩号
        chainages = [0.0]
        for i in range(1, len(ip_list)):
            dx = ip_list[i]['x'] - ip_list[i - 1]['x']
            dy = ip_list[i]['y'] - ip_list[i - 1]['y']
            chainages.append(chainages[-1] + math.sqrt(dx * dx + dy * dy))

        # 预计算转角
        computed_angles = [0.0] * len(ip_list)
        for i in range(1, len(ip_list) - 1):
            if ip_list[i].get('turn_angle', 0) > 0:
                computed_angles[i] = ip_list[i]['turn_angle']
            else:
                dx1 = ip_list[i]['x'] - ip_list[i - 1]['x']
                dy1 = ip_list[i]['y'] - ip_list[i - 1]['y']
                dx2 = ip_list[i + 1]['x'] - ip_list[i]['x']
                dy2 = ip_list[i + 1]['y'] - ip_list[i]['y']
                len1 = math.sqrt(dx1 * dx1 + dy1 * dy1)
                len2 = math.sqrt(dx2 * dx2 + dy2 * dy2)
                if len1 > 1e-6 and len2 > 1e-6:
                    cos_a = (dx1 * dx2 + dy1 * dy2) / (len1 * len2)
                    cos_a = max(-1.0, min(1.0, cos_a))
                    angle_deg = math.degrees(math.acos(cos_a))
                    if angle_deg > 0.5:
                        computed_angles[i] = round(angle_deg, 1)

        # 管道线
        pen = QPen(self.C_PIPE, 3)
        p.setPen(pen)
        for i in range(len(screen_pts) - 1):
            p.drawLine(QPointF(*screen_pts[i]), QPointF(*screen_pts[i + 1]))

        # 箭头
        for i in range(len(screen_pts) - 1):
            self._draw_arrow(p, screen_pts[i], screen_pts[i + 1], self.C_ARROW)

        # 节点圆圈
        for i, sp in enumerate(screen_pts):
            is_start = (i == 0)
            is_end = (i == len(screen_pts) - 1)
            is_bend = computed_angles[i] > 0

            if is_start or is_end:
                r, color = 7, self.C_INLET
            elif is_bend:
                r, color = 5, self.C_BEND
            else:
                r, color = 5, self.C_NODE

            p.setPen(QPen(Qt.white, 1))
            p.setBrush(QBrush(color))
            p.drawEllipse(QPointF(*sp), r, r)

        # ---- 标签智能布局 ----
        occupied = []

        if len(screen_pts) > 1:
            _total_sd = sum(
                math.sqrt((screen_pts[k + 1][0] - screen_pts[k][0]) ** 2 +
                          (screen_pts[k + 1][1] - screen_pts[k][1]) ** 2)
                for k in range(len(screen_pts) - 1)
            )
            avg_sd = _total_sd / (len(screen_pts) - 1)
        else:
            avg_sd = 200.0
        label_scale = min(1.0, max(0.45, avg_sd / 120.0))
        show_mc_for_bends = avg_sd >= 60

        for i, sp in enumerate(screen_pts):
            r = max(4, int((8 if (i == 0 or i == len(screen_pts) - 1) else 6) * label_scale))
            occupied.append((sp[0] - r, sp[1] - r, sp[0] + r, sp[1] + r))

        plan_pipe_lines = [(screen_pts[k][0], screen_pts[k][1],
                            screen_pts[k + 1][0], screen_pts[k + 1][1])
                           for k in range(len(screen_pts) - 1)]

        pending = []
        for i, sp in enumerate(screen_pts):
            is_start = (i == 0)
            is_end = (i == len(screen_pts) - 1)
            is_bend = computed_angles[i] > 0
            mc_text = f"MC {chainages[i]:.3f}"
            if is_start:
                pending.append((sp[0], sp[1], "进水口", self.C_INLET, 9))
                pending.append((sp[0], sp[1], mc_text, self.C_ELEV, 8))
            elif is_end:
                pending.append((sp[0], sp[1], "出水口", self.C_INLET, 9))
                pending.append((sp[0], sp[1], mc_text, self.C_ELEV, 8))
            elif is_bend:
                pending.append((sp[0], sp[1], f"α={computed_angles[i]:.3f}°", self.C_BEND, 8))
                if show_mc_for_bends:
                    pending.append((sp[0], sp[1], mc_text, self.C_ELEV, 8))

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

            if best:
                cx, cy, rect = best
                occupied.append(rect)
                p.setPen(QPen(color))
                p.setFont(ft)
                p.drawText(QPointF(cx - tw / 2,
                                   cy + (fm.ascent() - fm.descent()) / 2), text)
            else:
                cy = ay - th / 2 - 50
                rect = (ax - tw / 2 - pad, cy - th / 2 - pad,
                        ax + tw / 2 + pad, cy + th / 2 + pad)
                occupied.append(rect)
                p.setPen(QPen(color))
                p.setFont(ft)
                p.drawText(QPointF(ax - tw / 2,
                                   cy + (fm.ascent() - fm.descent()) / 2), text)

        # 底部信息
        plan_len = chainages[-1] if chainages else 0
        bend_cnt = sum(1 for a in computed_angles if a > 0)
        info = f"平面总长: {plan_len:.1f}m | IP点: {len(ip_list)} | 弯管: {bend_cnt} | 缩放: {int(self._zoom * 100)}%"
        p.setPen(QPen(self.C_INFO))
        p.setFont(QFont("Microsoft YaHei", 9))
        p.drawText(QRectF(0, h - 22, w, 20), Qt.AlignCenter, info)

    # ---- 绘图工具 ----

    def _draw_centered_text(self, p, w, h, text):
        p.setPen(QPen(self.C_HINT))
        p.setFont(QFont("Microsoft YaHei", 11))
        p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, text)

    def _draw_arrow(self, p, pt1, pt2, color):
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

    def _draw_endpoint(self, p, pt, label, is_inlet):
        sx, sy = pt
        p.setPen(QPen(Qt.white, 1))
        p.setBrush(QBrush(self.C_INLET))
        p.drawEllipse(QPointF(sx, sy), 7, 7)
        p.setPen(QPen(self.C_INLET))
        p.setFont(QFont("Microsoft YaHei", 9))
        p.drawText(QPointF(sx - 16, sy - 18), label)

    def _line_rect_intersect(self, x1, y1, x2, y2, rect):
        left, top, right, bottom = rect
        if left <= x1 <= right and top <= y1 <= bottom:
            return True
        if left <= x2 <= right and top <= y2 <= bottom:
            return True
        edges = [
            (left, top, right, top), (right, top, right, bottom),
            (left, bottom, right, bottom), (left, top, left, bottom),
        ]
        for ex1, ey1, ex2, ey2 in edges:
            if self._segs_cross(x1, y1, x2, y2, ex1, ey1, ex2, ey2):
                return True
        return False

    @staticmethod
    def _segs_cross(x1, y1, x2, y2, x3, y3, x4, y4):
        d1x, d1y = x2 - x1, y2 - y1
        d2x, d2y = x4 - x3, y4 - y3
        cross = d1x * d2y - d1y * d2x
        if abs(cross) < 1e-10:
            return False
        t = ((x3 - x1) * d2y - (y3 - y1) * d2x) / cross
        u = ((x3 - x1) * d1y - (y3 - y1) * d1x) / cross
        return 0 <= t <= 1 and 0 <= u <= 1


# ============================================================
# 纵断面预览对话框
# ============================================================
class LongitudinalPreviewDialog(QDialog):
    """管道预览对话框 —— 支持纵断面/平面图双视图，可调整大小"""

    view_mode_changed = Signal(str)

    _ACTIVE_BTN_STYLE = (
        "QPushButton { font-size: 12px; font-weight: bold; color: #FFFFFF; "
        "background: #1976D2; border: 1px solid #1565C0; border-radius: 4px; "
        "padding: 4px 14px; }"
    )
    _INACTIVE_BTN_STYLE = (
        "QPushButton { font-size: 12px; color: #546E7A; "
        "background: #ECEFF1; border: 1px solid #CFD8DC; border-radius: 4px; "
        "padding: 4px 14px; }"
        "QPushButton:hover { background: #CFD8DC; }"
    )

    def __init__(self, parent=None, pipe_name="", nodes=None, ip_points=None):
        super().__init__(parent)
        self.setWindowTitle(f"管道预览 — {pipe_name}")
        self.resize(800, 500)
        self.setMinimumSize(500, 350)
        self.setModal(False)
        self.setWindowFlag(Qt.Window, True)
        self._pipe_name = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # 顶部视图切换工具栏
        view_bar = QHBoxLayout()
        view_bar.setSpacing(4)
        self._btn_plan = QPushButton("平面图")
        self._btn_plan.setFixedSize(80, 28)
        self._btn_plan.setCursor(Qt.PointingHandCursor)
        self._btn_profile = QPushButton("纵断面")
        self._btn_profile.setFixedSize(80, 28)
        self._btn_profile.setCursor(Qt.PointingHandCursor)
        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet("font-size: 12px; color: #90A4AE;")
        view_bar.addWidget(self._btn_plan)
        view_bar.addWidget(self._btn_profile)
        view_bar.addStretch()
        view_bar.addWidget(self._zoom_label)
        lay.addLayout(view_bar)

        self._canvas = SimpleProfileCanvas(self)
        self._canvas.zoom_changed.connect(self._sync_zoom_label)
        lay.addWidget(self._canvas, 1)

        self._btn_plan.clicked.connect(lambda: self._switch_view("plan"))
        self._btn_profile.clicked.connect(lambda: self._switch_view("profile"))

        # 底部工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addStretch()

        try:
            from qfluentwidgets import PushButton as FluentPushButton
            btn_reset = FluentPushButton("重置视图")
            btn_close = FluentPushButton("关闭")
        except ImportError:
            btn_reset = QPushButton("重置视图")
            btn_close = QPushButton("关闭")

        btn_reset.clicked.connect(self._on_reset)
        btn_close.clicked.connect(self.close)

        toolbar.addWidget(btn_reset)
        toolbar.addWidget(btn_close)

        lay.addLayout(toolbar)

        self.sync_pipe_data(pipe_name=pipe_name, nodes=nodes, ip_points=ip_points)

    def sync_pipe_data(self, pipe_name="", nodes=None, ip_points=None, view_mode=None):
        self._pipe_name = pipe_name or self._pipe_name
        self.setWindowTitle(f"管道预览 — {self._pipe_name}")
        self._canvas.set_nodes(nodes or [])
        self._canvas.set_ip_points(ip_points or [])

        has_nodes = bool(nodes and len(nodes) >= 2)
        has_ip = bool(ip_points and len(ip_points) >= 2)
        self._btn_plan.setEnabled(has_ip)
        self._btn_profile.setEnabled(has_nodes)

        target_mode = view_mode
        if target_mode not in ("plan", "profile"):
            if has_ip:
                target_mode = "plan"
            elif has_nodes:
                target_mode = "profile"
            else:
                target_mode = "plan"

        if target_mode == "profile" and not has_nodes:
            target_mode = "plan" if has_ip else "profile"
        if target_mode == "plan" and not has_ip:
            target_mode = "profile" if has_nodes else "plan"

        self._canvas.set_view_mode(target_mode)
        self._apply_view_mode_style(target_mode)
        self._sync_zoom_label()

    def show_and_focus(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _switch_view(self, mode):
        self._canvas.set_view_mode(mode)
        self._apply_view_mode_style(mode)
        self._sync_zoom_label()
        self.view_mode_changed.emit(mode)

    def _on_reset(self):
        self._canvas.zoom_reset()
        self._sync_zoom_label()

    def _sync_zoom_label(self, _zoom=None):
        self._zoom_label.setText(f"{self._canvas.get_zoom_percent()}%")

    def _apply_view_mode_style(self, mode):
        if mode == "plan":
            self._btn_plan.setStyleSheet(self._ACTIVE_BTN_STYLE)
            self._btn_profile.setStyleSheet(self._INACTIVE_BTN_STYLE)
        else:
            self._btn_plan.setStyleSheet(self._INACTIVE_BTN_STYLE)
            self._btn_profile.setStyleSheet(self._ACTIVE_BTN_STYLE)


# ============================================================
# 有压管道计算配置对话框
# ============================================================
class PressurePipeConfigDialog(QDialog):
    """有压管道计算配置对话框（在计算前配置参数）"""

    _SCREEN_WIDTH_RATIO = 0.88
    _SCREEN_HEIGHT_RATIO = 0.92
    _FALLBACK_MAX_WIDTH = 1200
    _FALLBACK_MAX_HEIGHT = 980
    _WINDOW_CHROME_PADDING = 24

    _VIEW_BTN_ACTIVE = (
        "QPushButton { font-size: 12px; font-weight: bold; color: #FFFFFF; "
        "background: #1976D2; border: 1px solid #1565C0; border-radius: 4px; "
        "padding: 3px 10px; }"
    )
    _VIEW_BTN_INACTIVE = (
        "QPushButton { font-size: 12px; color: #546E7A; "
        "background: #ECEFF1; border: 1px solid #CFD8DC; border-radius: 4px; "
        "padding: 3px 10px; }"
        "QPushButton:hover { background: #CFD8DC; }"
    )
    _ROUTE_CARD_STYLE = """
        QGroupBox {
            font-size: 13px; font-weight: bold; color: #2E7D32;
            border: 2px solid #60C16B; border-radius: 8px;
            margin-top: 12px; padding: 16px 12px 12px 12px;
            background: #FFFFFF;
        }
        QGroupBox::title {
            subcontrol-origin: margin; left: 16px;
            padding: 0 8px; background: #FFFFFF;
        }
    """
    _ROUTE_CARD_HIGHLIGHT_STYLE = """
        QGroupBox {
            font-size: 13px; font-weight: bold; color: #C45500;
            border: 2px solid #E65100; border-radius: 8px;
            margin-top: 12px; padding: 16px 12px 12px 12px;
            background: #FFF8E1;
        }
        QGroupBox::title {
            subcontrol-origin: margin; left: 16px;
            padding: 0 8px; background: #FFF8E1;
        }
    """
    _IMPORT_BTN_HIGHLIGHT_STYLE = (
        "QPushButton { font-size: 12px; font-weight: bold; color: #FFFFFF; "
        "background: #E65100; border: 1px solid #BF360C; border-radius: 4px; "
        "padding: 4px 14px; }"
        "QPushButton:hover { background: #F57C00; }"
    )
    _TUNNEL_SECTION_OPTIONS = (
        ("圆形隧洞", "隧洞-圆形"),
        ("圆拱直墙型隧洞", "隧洞-圆拱直墙型"),
        ("马蹄形Ⅰ型隧洞", "隧洞-马蹄形Ⅰ型"),
        ("马蹄形Ⅱ型隧洞", "隧洞-马蹄形Ⅱ型"),
    )
    _TUNNEL_SECTION_ALIAS = {
        "隧洞-圆形": "圆形隧洞",
        "圆形": "圆形隧洞",
        "圆形隧洞": "圆形隧洞",
        "隧洞-圆拱直墙型": "圆拱直墙型隧洞",
        "隧洞-圆弧直墙型": "圆拱直墙型隧洞",
        "隧洞-圆拱直墙": "圆拱直墙型隧洞",
        "隧洞-圆弧直墙": "圆拱直墙型隧洞",
        "圆拱直墙型": "圆拱直墙型隧洞",
        "圆拱直墙型隧洞": "圆拱直墙型隧洞",
        "圆弧直墙型隧洞": "圆拱直墙型隧洞",
        "隧洞-马蹄形Ⅰ型": "马蹄形Ⅰ型隧洞",
        "隧洞-马蹄形Ⅰ": "马蹄形Ⅰ型隧洞",
        "马蹄形Ⅰ型": "马蹄形Ⅰ型隧洞",
        "马蹄形Ⅰ型隧洞": "马蹄形Ⅰ型隧洞",
        "隧洞-马蹄形Ⅱ型": "马蹄形Ⅱ型隧洞",
        "隧洞-马蹄形Ⅱ": "马蹄形Ⅱ型隧洞",
        "马蹄形Ⅱ型": "马蹄形Ⅱ型隧洞",
        "马蹄形Ⅱ型隧洞": "马蹄形Ⅱ型隧洞",
    }
    _TUNNEL_PARAM_SPECS = {
        "圆形隧洞": (("D", "洞径 D(m)"),),
        "圆拱直墙型隧洞": (("B", "底宽 B(m)"),),
        "马蹄形Ⅰ型隧洞": (("R", "内半径 r(m)"),),
        "马蹄形Ⅱ型隧洞": (("R", "内半径 r(m)"),),
    }
    _TUNNEL_PROFILE_MODE_HYDRAULIC = "hydraulic_display"

    def __init__(
        self,
        parent=None,
        pipe_groups=None,
        manager=None,
        pressure_chains=None,
        xxpipe_route_mode: bool = False,
        route_import_targets: Dict[str, Any] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("有压管道水力计算配置")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        self.setModal(True)

        self._pipe_groups = pipe_groups or []
        self._manager = manager
        self._pressure_chains = list(pressure_chains or [])
        self._xxpipe_route_mode = bool(xxpipe_route_mode)
        self._route_import_targets = {}
        for key, value in (route_import_targets or {}).items():
            route_key = str(key or "").strip()
            if not route_key:
                continue
            if isinstance(value, dict):
                self._route_import_targets[route_key] = dict(value)
            else:
                self._route_import_targets[route_key] = {"targets": list(value or [])}

        # 存储每个管道的纵断面数据 {pipe_name: [LongitudinalNode字典列表]}
        self._longitudinal_data = {}
        # 存储每条整线导入原线几何 {pipe_name: {vertices, bulges, source_kind}}
        self._raw_profile_polyline_data: Dict[str, Dict[str, Any]] = {}
        # 记录已识别为失效的旧纵断面缓存提示，便于界面直接提示重新导入
        self._stale_longitudinal_hint_texts: Dict[str, str] = {}
        # 存储每个管道卡片的UI组件引用 {pipe_name: {hint, stats, canvas, expand_btn, table}}
        self._card_widgets = {}
        # 存储每条整线卡片的UI组件引用 {route_key: {...}}
        self._route_widgets = {}
        self._radius_configs: Dict[str, Dict[str, Any]] = {}
        self._d_override_payload: Dict[str, float] = {}
        self._tunnel_payload: Dict[str, Dict[str, Any]] = {}
        self._last_apply_summary: Dict[str, Any] = {}
        self._syncing_radius = False
        self._last_turn_n = 3.0
        self._canvas_viewer = None
        self._active_viewer_pipe_name = ""
        self._pipe_scroll_area = None
        self._pipe_scroll_widget = None
        self._did_apply_initial_size = False
        self._route_contexts = self._build_route_contexts()

        # 从manager加载已有的纵断面数据
        if self._manager and self._pipe_groups:
            for group in self._pipe_groups:
                group_key = self._group_storage_key(group)
                route_key = self._group_route_key(group)
                self._restore_manager_route_longitudinal_data(route_key)
                config = self._get_manager_group_config(group)
                self._sync_group_tunnel_defaults(group, config=config)
                if config and config.longitudinal_nodes:
                    storage_key = route_key or group_key
                    if storage_key not in self._longitudinal_data:
                        self._longitudinal_data[storage_key] = list(config.longitudinal_nodes)
                if config:
                    _cfg_turn_n = float(getattr(config, "turn_n", 0.0) or 0.0)
                    _cfg_turn_r = float(getattr(config, "turn_R", 0.0) or 0.0)
                    _cfg_applied = bool(_cfg_turn_r > 0)
                    self._radius_configs[group_key] = {
                        "turn_n": _cfg_turn_n,
                        "turn_R": _cfg_turn_r,
                        "force_override": bool(getattr(config, "force_override", False)),
                        "radius_applied_at": str(getattr(config, "radius_applied_at", "") or ""),
                        "applied": _cfg_applied,
                        "dirty": False,
                        "applied_turn_n": _cfg_turn_n if _cfg_applied else 0.0,
                        "applied_turn_R": _cfg_turn_r if _cfg_applied else 0.0,
                    }

        self._last_turn_n = self._resolve_last_turn_n()
        self._cleanup_stale_saved_longitudinal_caches()

        self._init_ui()
        self._apply_initial_size()

    @staticmethod
    def _group_storage_key(group) -> str:
        """返回分组稳定存储键。"""
        key = str(getattr(group, "storage_key", "") or "").strip()
        if key:
            return key
        identity = str(getattr(group, "identity", "") or "").strip()
        if identity:
            return identity
        return str(getattr(group, "name", "") or "").strip()

    @staticmethod
    def _group_display_name(group) -> str:
        """返回分组展示名称。"""
        display_name = str(getattr(group, "display_name", "") or "").strip()
        if display_name:
            return display_name
        name = str(getattr(group, "name", "") or "").strip()
        return name or "未命名有压管道"

    @staticmethod
    def _group_identity(group) -> str:
        """返回分组稳定身份键。"""
        identity = str(getattr(group, "identity", "") or "").strip()
        if identity:
            return identity
        return str(getattr(group, "name", "") or "").strip()

    @staticmethod
    def _chain_item_value(item, key: str, default=None):
        """兼容字典/对象两种链描述结构。"""
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    def _resolve_pressure_chain_display_name(self, chain) -> str:
        """返回连续承压链展示名称。"""
        display_name = str(self._chain_item_value(chain, "display_name", "") or "").strip()
        if display_name:
            return display_name
        flow_section = str(self._chain_item_value(chain, "flow_section", "") or "").strip() or "-"
        chain_id = str(self._chain_item_value(chain, "chain_id", "") or "").strip()
        return chain_id or f"流量段{flow_section} 连续承压链"

    def _resolve_pressure_chain_members(self, chain) -> List[Any]:
        """返回连续承压链成员列表。"""
        members = self._chain_item_value(chain, "members", []) or []
        return list(members)

    def _resolve_chain_member_group(self, member):
        """返回链成员关联的有压管道分组。"""
        return self._chain_item_value(member, "group", None)

    def _build_pressure_chain_summary_text(self, chain) -> str:
        """构造连续承压链摘要。"""
        flow_section = str(self._chain_item_value(chain, "flow_section", "") or "").strip() or "-"
        start_row_index = coerce_row_index(self._chain_item_value(chain, "start_row_index", -1))
        end_row_index = coerce_row_index(
            self._chain_item_value(chain, "end_row_index", start_row_index),
            start_row_index,
        )
        members = self._resolve_pressure_chain_members(chain)
        pressure_count = 0
        tunnel_count = 0
        for member in members:
            structure_type = str(self._chain_item_value(member, "structure_type", "") or "").strip()
            if "隧洞" in structure_type:
                tunnel_count += 1
            else:
                pressure_count += 1
        row_range = "-"
        if start_row_index >= 0 and end_row_index >= 0:
            row_range = f"第{start_row_index + 1}行 ~ 第{end_row_index + 1}行"
        return (
            f"流量段: {flow_section}  |  范围: {row_range}  |  "
            f"成员数: {len(members)}（有压成员 {pressure_count}，隧洞成员 {tunnel_count}）"
        )

    def _create_chain_readonly_member_card(self, member):
        """创建连续承压链只读成员卡片。"""
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #F6FBFF; border: 1px solid #CFE3F5; border-radius: 6px; }"
        )
        frame_lay = QVBoxLayout(frame)
        frame_lay.setContentsMargins(12, 10, 12, 10)
        frame_lay.setSpacing(4)

        display_name = str(self._chain_item_value(member, "display_name", "") or "").strip() or "未命名成员"
        structure_type = str(self._chain_item_value(member, "structure_type", "") or "").strip() or "承压成员"
        target_row_index = coerce_row_index(self._chain_item_value(member, "target_row_index", -1))
        row_text = f"第{target_row_index + 1}行" if target_row_index >= 0 else "未定位行"

        title = QLabel(f"{structure_type}: {display_name}")
        title.setStyleSheet("font-size: 12px; font-weight: bold; color: #1F4E79;")
        frame_lay.addWidget(title)

        info = QLabel(f"位置: {row_text}")
        info.setStyleSheet("font-size: 12px; color: #546E7A;")
        frame_lay.addWidget(info)

        hint = QLabel("本成员参与连续承压链计算，不需要设置有压管道的 R / D 参数。")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 12px; color: #607D8B;")
        frame_lay.addWidget(hint)
        return frame

    def _create_pressure_chain_card(self, chain, used_group_keys: set[str]):
        """按连续承压链创建界面卡片。"""
        chain_name = self._resolve_pressure_chain_display_name(chain)
        card = QGroupBox(f"链路: {chain_name}")
        card.setStyleSheet("""
            QGroupBox {
                font-size: 13px; font-weight: bold; color: #1B5E20;
                border: 2px solid #66BB6A; border-radius: 8px;
                margin-top: 12px; padding: 16px 12px 12px 12px;
                background: #FFFFFF;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 16px;
                padding: 0 8px; background: #FFFFFF;
            }
        """)
        card_lay = QVBoxLayout(card)
        card_lay.setSpacing(10)

        summary_label = QLabel(self._build_pressure_chain_summary_text(chain))
        summary_label.setWordWrap(True)
        summary_label.setStyleSheet("font-size: 12px; color: #607D8B; font-weight: normal;")
        card_lay.addWidget(summary_label)

        for member in self._resolve_pressure_chain_members(chain):
            group = self._resolve_chain_member_group(member)
            if group is not None:
                used_group_keys.add(self._group_storage_key(group))
                card_lay.addWidget(self._create_pipe_card(group))
                continue
            card_lay.addWidget(self._create_chain_readonly_member_card(member))

        return card

    @staticmethod
    def _group_edit_rows(group):
        """返回需要用于 D/R 参数编辑的目标行。"""
        rows = list(getattr(group, "rows", []) or [])
        if str(getattr(group, "group_mode", "") or "").strip() == "unnamed_row_segment" and rows:
            return rows[-1:]
        return rows

    @staticmethod
    def _group_route_key(group) -> str:
        """返回分组所属整线键。"""
        return str(getattr(group, "route_key", "") or "").strip()

    @staticmethod
    def _group_route_display_name(group) -> str:
        """返回整线展示名称。"""
        route_display_name = str(getattr(group, "route_display_name", "") or "").strip()
        if route_display_name:
            return route_display_name
        return ""

    @staticmethod
    def _group_route_ip_points(group) -> List[Dict[str, Any]]:
        """返回整线平面点；没有整线数据时回退到本段平面点。"""
        route_points = list(getattr(group, "route_ip_points", []) or [])
        if route_points:
            return route_points
        return list(getattr(group, "ip_points", []) or [])

    @staticmethod
    def _structure_type_text(raw_value) -> str:
        """把结构类型统一转成可判断的文本。"""
        value = getattr(raw_value, "value", raw_value)
        return str(value or "").strip()

    @classmethod
    def _group_is_tunnel_segment(cls, group) -> bool:
        """判断分段是否为隧洞，用于 xx管 整线模式下保留必要卡片。"""
        return "隧洞" in cls._structure_type_text(getattr(group, "structure_type", ""))

    @classmethod
    def _route_node_requires_import_coverage(cls, node) -> bool:
        """xx管 整线导入时，只校验非隧洞目标桩号是否被覆盖。"""
        return "隧洞" not in cls._structure_type_text(getattr(node, "structure_type", ""))

    def _build_route_contexts(self) -> Dict[str, Dict[str, Any]]:
        """从分组列表中整理整线卡上下文。"""
        contexts: Dict[str, Dict[str, Any]] = {}
        for group in self._pipe_groups or []:
            route_key = self._group_route_key(group)
            if not route_key:
                continue
            if route_key not in contexts:
                contexts[route_key] = {
                    "route_key": route_key,
                    "display_name": self._group_route_display_name(group) or route_key,
                    "ip_points": self._group_route_ip_points(group),
                    "route_start_row_index": getattr(group, "route_start_row_index", None),
                    "route_end_row_index": getattr(group, "route_end_row_index", None),
                    "route_start_mc": getattr(group, "route_start_mc", None),
                    "route_end_mc": getattr(group, "route_end_mc", None),
                    "groups": [],
                }
            contexts[route_key]["groups"].append(group)
            if not contexts[route_key].get("ip_points"):
                contexts[route_key]["ip_points"] = self._group_route_ip_points(group)
        return contexts

    def _lookup_visual_widgets(self, pipe_name: str) -> Dict[str, Any]:
        """按键名查找可视化卡片组件，优先整线卡。"""
        route_widgets = self._route_widgets.get(pipe_name)
        if route_widgets:
            return route_widgets
        return self._card_widgets.get(pipe_name, {})

    def _get_manager_group_config(self, group):
        """优先按 storage_key 读取配置，兼容旧数据按名称回退。"""
        if not self._manager:
            return None
        group_key = self._group_storage_key(group)
        config = self._manager.get_pipe_config(group_key)
        if config is not None:
            return config
        legacy_name = str(getattr(group, "name", "") or "").strip()
        if legacy_name and legacy_name != group_key:
            return self._manager.get_pipe_config(legacy_name)
        return None

    def _restore_manager_route_longitudinal_data(self, route_key: str):
        """优先从 route 级缓存恢复整线纵断面，避免 group 入口被清理后重开丢失。"""
        if not self._manager:
            return
        route_key = str(route_key or "").strip()
        if not route_key or (
            route_key in self._longitudinal_data
            and route_key in self._raw_profile_polyline_data
        ):
            return
        get_route_config = getattr(self._manager, "get_route_config", None)
        if not callable(get_route_config):
            return
        route_config = get_route_config(route_key)
        if not isinstance(route_config, dict):
            return
        longitudinal_nodes = list(route_config.get("longitudinal_nodes", []) or [])
        raw_profile_polyline = dict(route_config.get("raw_profile_polyline", {}) or {})
        if longitudinal_nodes:
            self._longitudinal_data[route_key] = longitudinal_nodes
        if raw_profile_polyline:
            self._raw_profile_polyline_data[route_key] = raw_profile_polyline

    def _resolve_pipe_label(self, pipe_key: str) -> str:
        """根据键名解析界面展示名称。"""
        widgets = self._lookup_visual_widgets(pipe_key)
        display_name = str(widgets.get("display_name", "") or "").strip()
        if display_name:
            return display_name
        for group in self._pipe_groups or []:
            if self._group_route_key(group) == pipe_key:
                route_display_name = self._group_route_display_name(group)
                if route_display_name:
                    return route_display_name
            if self._group_storage_key(group) == pipe_key:
                return self._group_display_name(group)
        return str(pipe_key or "未命名有压管道")

    def _cleanup_stale_saved_longitudinal_caches(self):
        """在弹窗载入时标记覆盖不完整的旧纵断面缓存。"""
        if not (self._xxpipe_route_mode and self._longitudinal_data):
            return

        for pipe_name, longitudinal_nodes in list(self._longitudinal_data.items()):
            route_key = str(pipe_name or "").strip()
            if not route_key or route_key not in self._route_contexts:
                continue

            coverage_state = self._collect_xxpipe_route_import_coverage_state(
                route_key,
                longitudinal_nodes,
            )
            missing_targets = list(coverage_state.get("missing_targets", []) or [])
            station_errors = list(coverage_state.get("station_errors", []) or [])
            if station_errors or missing_targets:
                self._stale_longitudinal_hint_texts[route_key] = self._build_xxpipe_incomplete_longitudinal_hint_text(
                    coverage_state,
                )
                continue

            self._stale_longitudinal_hint_texts.pop(route_key, None)

    @classmethod
    def _build_xxpipe_incomplete_longitudinal_hint_text(
        cls,
        coverage_state: Dict[str, Any],
    ) -> str:
        """为整线卡片构造“已保留但待补导入”的提示。"""
        missing_targets = list((coverage_state or {}).get("missing_targets", []) or [])
        if missing_targets:
            return cls._build_stale_longitudinal_hint_text(missing_targets)
        station_errors = list((coverage_state or {}).get("station_errors", []) or [])
        if station_errors:
            return "已保留当前导入的纵断面，但当前桩号还无法完成覆盖校验，请检查桩号或继续补导入后再开始计算。"
        display_name = str((coverage_state or {}).get("display_name", "") or "").strip()
        if display_name:
            return f"已保留“{display_name}”当前导入的纵断面，请继续补导入后再开始计算。"
        return "已保留当前导入的纵断面，请继续补导入后再开始计算。"

    @classmethod
    def _build_xxpipe_route_hint_text(cls, pipe_name, widgets, hint_text: str) -> str:
        """统一返回整线/分段卡片当前应展示的提示文案。"""
        hint = str(hint_text or "").strip()
        if hint:
            return hint
        return str(widgets.get("default_hint_text", "") or "")

    @classmethod
    def _format_longitudinal_measure(
        cls,
        value,
        min_decimals: int = 3,
        max_decimals: int = 6,
    ) -> str:
        """格式化纵断面桩号数值，保留必要小数位。"""
        from app_渠系计算前端.water_profile import cad_tools

        return cad_tools._format_xxpipe_longitudinal_measure(
            value,
            min_decimals=min_decimals,
            max_decimals=max_decimals,
        )

    @classmethod
    def _format_longitudinal_gap_text(cls, gap_m: float) -> str:
        """把纵断面缺口优先格式化成毫米，必要时补充米值。"""
        from app_渠系计算前端.water_profile import cad_tools

        return cad_tools._format_xxpipe_longitudinal_gap_text(gap_m)

    @staticmethod
    def _format_missing_target_preview_text(item) -> str:
        """统一格式化未覆盖节点预览文本。"""
        from app_渠系计算前端.water_profile import cad_tools

        return cad_tools._format_xxpipe_missing_target_preview_text(item)

    @classmethod
    def _build_missing_target_preview(cls, missing_targets, max_items: int = 3) -> str:
        """生成未覆盖节点的预览文本。"""
        from app_渠系计算前端.water_profile import cad_tools

        return cad_tools._build_xxpipe_missing_target_preview(
            missing_targets,
            max_items=max_items,
        )

    @classmethod
    def _extract_longitudinal_chainage_range(cls, longitudinal_nodes):
        """提取导入纵断面的起止桩号范围。"""
        from app_渠系计算前端.water_profile import cad_tools

        return cad_tools._extract_xxpipe_longitudinal_chainage_range(longitudinal_nodes)

    @classmethod
    def _build_xxpipe_import_coverage_error_message(
        cls,
        display_name: str,
        coverage_state: Dict[str, Any],
    ) -> str:
        """生成用户可直接照着修改的纵断面覆盖不足提示。"""
        from app_渠系计算前端.water_profile import cad_tools

        return cad_tools._build_xxpipe_coverage_error_message(display_name, coverage_state)

    @classmethod
    def _build_stale_longitudinal_hint_text(cls, missing_targets: List[Any]) -> str:
        """构造旧缓存失效时的界面提示。"""
        from app_渠系计算前端.water_profile import cad_tools

        return cad_tools._build_xxpipe_stale_longitudinal_hint_text(missing_targets)

    def _resolve_last_turn_n(self) -> float:
        n_values = []
        if self._manager and hasattr(self._manager, "get_all_pipe_names"):
            for pipe_name in self._manager.get_all_pipe_names():
                cfg = self._manager.get_pipe_config(pipe_name)
                if not cfg:
                    continue
                n_val = float(getattr(cfg, "turn_n", 0.0) or 0.0)
                if n_val > 0:
                    n_values.append((str(getattr(cfg, "radius_applied_at", "") or ""), n_val))
        if not n_values:
            return 3.0
        n_values.sort(key=lambda item: item[0])
        return float(n_values[-1][1])

    @staticmethod
    def _safe_float(value, default=0.0) -> float:
        try:
            if value is None:
                return default
            txt = str(value).strip()
            if txt == "":
                return default
            return float(txt)
        except (ValueError, TypeError):
            return default

    @classmethod
    def _resolve_ip_point_chainage(cls, point, prefer_station: bool = True):
        """优先按项目桩号读取平面点链长，缺失时再回退到原始 X。"""
        if not isinstance(point, dict):
            return None
        candidates = ("station_mc", "x") if prefer_station else ("x", "station_mc")
        for key in candidates:
            value = cls._safe_float(point.get(key, None), None)
            if value is not None and math.isfinite(value):
                return float(value)
        return None

    @classmethod
    def _resolve_ip_points_chainage_range(cls, ip_points, prefer_station: bool = True):
        """提取平面点的起止链长范围。"""
        values = []
        for point in list(ip_points or []):
            chainage = cls._resolve_ip_point_chainage(point, prefer_station=prefer_station)
            if chainage is None:
                continue
            values.append(float(chainage))
        if len(values) < 2:
            return None
        return float(values[0]), float(values[-1])

    @classmethod
    def _raise_if_import_stays_in_raw_coordinate_space(cls, pipe_label: str, ip_points, long_nodes):
        """识别导入结果仍停留在原始工程坐标的情况，避免错误数据被保存。"""
        if not long_nodes:
            return

        station_range = cls._resolve_ip_points_chainage_range(ip_points, prefer_station=True)
        raw_x_range = cls._resolve_ip_points_chainage_range(ip_points, prefer_station=False)
        if station_range is None or raw_x_range is None:
            return

        station_start, station_end = station_range
        raw_x_start, raw_x_end = raw_x_range
        if abs(station_start - raw_x_start) <= 100.0 and abs(station_end - raw_x_end) <= 100.0:
            return

        long_start = cls._safe_float(getattr(long_nodes[0], "chainage", None), None)
        long_end = cls._safe_float(getattr(long_nodes[-1], "chainage", None), None)
        if long_start is None or long_end is None:
            return

        if abs(long_start - raw_x_start) <= 1.0 and abs(long_end - raw_x_end) <= 1.0:
            raise ValueError(
                f"{pipe_label} 导入后的桩号仍停留在原始坐标空间，请检查 DXF 对齐起点后重新导入。"
            )

    @staticmethod
    def _parse_optional_float_text(text: str):
        """把输入框文本解析成浮点数，空字符串返回 None。"""
        raw = str(text or "").strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        return value

    @classmethod
    def _detect_tunnel_section_type(cls, *candidate_texts) -> str:
        """识别当前分组对应的隧洞断面类型。"""
        for raw_text in candidate_texts:
            text = str(raw_text or "").strip()
            if not text:
                continue
            normalized = cls._TUNNEL_SECTION_ALIAS.get(text)
            if normalized:
                return normalized
            if "圆形" in text:
                return "圆形隧洞"
            if "圆拱直墙" in text or "圆弧直墙" in text:
                return "圆拱直墙型隧洞"
            if "马蹄形Ⅰ" in text or "马蹄形I" in text:
                return "马蹄形Ⅰ型隧洞"
            if "马蹄形Ⅱ" in text or "马蹄形II" in text:
                return "马蹄形Ⅱ型隧洞"
        return ""

    @classmethod
    def _normalize_tunnel_section_type(cls, section_type: str, structure_type: str = "") -> str:
        """把隧洞断面类型统一成界面选项。"""
        detected = cls._detect_tunnel_section_type(section_type, structure_type)
        if detected:
            return detected
        return "圆形隧洞"

    @classmethod
    def _tunnel_section_type_to_structure_type(cls, section_type: str) -> str:
        """把隧洞断面选项转换成结构形式文本。"""
        normalized = cls._normalize_tunnel_section_type(section_type)
        for label, structure_type in cls._TUNNEL_SECTION_OPTIONS:
            if label == normalized:
                return structure_type
        return "隧洞-圆形"

    @staticmethod
    def _extract_tunnel_section_params_from_rows(group) -> Dict[str, float]:
        """优先从分组行数据中提取隧洞断面参数。"""
        for node in getattr(group, "rows", []) or []:
            params = getattr(node, "section_params", {}) or {}
            if not isinstance(params, dict):
                continue
            values: Dict[str, float] = {}
            for target_key, source_keys in {
                "D": ("D", "d"),
                "B": ("B", "b", "b_design"),
                "H": ("H", "h", "H_total", "structure_height"),
                "R": ("R", "R_circle", "r"),
            }.items():
                for source_key in source_keys:
                    value = PressurePipeConfigDialog._safe_float(params.get(source_key), 0.0)
                    if value > 0:
                        values[target_key] = float(value)
                        break
                if target_key == "H":
                    node_height = PressurePipeConfigDialog._safe_float(
                        getattr(node, "structure_height", 0.0),
                        0.0,
                    )
                    if node_height > 0 and values.get("H", 0.0) <= 0:
                        values["H"] = float(node_height)
            if values:
                return values
        return {}

    @classmethod
    def _resolve_tunnel_section_params(cls, group, config=None, section_type: str = "") -> Dict[str, float]:
        """汇总隧洞断面参数，优先当前表1/节点，再回退到旧缓存。"""
        sources = [
            cls._extract_tunnel_section_params_from_rows(group),
            getattr(group, "tunnel_section_params", None),
            getattr(config, "tunnel_section_params", None) if config is not None else None,
        ]
        resolved: Dict[str, float] = {}
        for params in sources:
            if not isinstance(params, dict):
                continue
            for key in ("D", "B", "H", "R"):
                if key in resolved:
                    continue
                value = cls._safe_float(params.get(key, params.get("R_circle" if key == "R" else key, 0.0)), 0.0)
                if value > 0:
                    resolved[key] = float(value)
        if "R" not in resolved:
            r_circle = cls._safe_float(
                (getattr(group, "tunnel_section_params", {}) or {}).get("R_circle"),
                0.0,
            )
            if r_circle > 0:
                resolved["R"] = float(r_circle)
        normalized_section_type = cls._detect_tunnel_section_type(section_type)
        if normalized_section_type:
            allowed_keys = [
                param_key
                for param_key, _label_text in cls._TUNNEL_PARAM_SPECS.get(normalized_section_type, ())
            ]
            resolved = {
                key: float(resolved[key])
                for key in allowed_keys
                if cls._safe_float(resolved.get(key), 0.0) > 0
            }
        return resolved

    @classmethod
    def _sync_group_tunnel_defaults(cls, group, config=None):
        """按表1优先、旧缓存兜底的顺序补齐隧洞参数。"""
        if not cls._group_is_tunnel_segment(group):
            return

        structure_text = cls._structure_type_text(getattr(group, "structure_type", ""))
        start_node = (getattr(group, "rows", []) or [None])[0]
        end_node = (getattr(group, "rows", []) or [None])[-1]

        segment_source = str(getattr(group, "segment_geometry_source", "") or "").strip()
        if not segment_source:
            segment_source = "generated_tunnel"
        setattr(group, "segment_geometry_source", segment_source)

        profile_mode = str(getattr(group, "tunnel_profile_mode", "") or "").strip()
        if not profile_mode:
            profile_mode = str(getattr(config, "tunnel_profile_mode", "") or "").strip() if config is not None else ""
        setattr(group, "tunnel_profile_mode", profile_mode or cls._TUNNEL_PROFILE_MODE_HYDRAULIC)

        inlet_value = cls._safe_float(getattr(start_node, "bottom_elevation", None), 0.0)
        if inlet_value <= 0:
            inlet_value = cls._safe_float(getattr(group, "tunnel_invert_inlet", None), 0.0)
        if inlet_value <= 0:
            inlet_value = cls._safe_float(getattr(config, "tunnel_invert_inlet", None), 0.0) if config is not None else 0.0
        setattr(group, "tunnel_invert_inlet", float(inlet_value) if inlet_value > 0 else None)

        slope_value = cls._safe_float(getattr(start_node, "slope_i", None), 0.0)
        if slope_value <= 0:
            slope_value = cls._safe_float(getattr(group, "tunnel_slope_i", None), 0.0)
        if slope_value <= 0:
            slope_value = cls._safe_float(getattr(config, "tunnel_slope_i", None), 0.0) if config is not None else 0.0
        setattr(group, "tunnel_slope_i", float(slope_value) if slope_value > 0 else None)

        outlet_value = cls._safe_float(getattr(end_node, "bottom_elevation", None), 0.0)
        if outlet_value <= 0:
            outlet_value = cls._safe_float(getattr(group, "tunnel_invert_outlet_check", None), 0.0)
        if outlet_value <= 0:
            outlet_value = cls._safe_float(getattr(config, "tunnel_invert_outlet_check", None), 0.0) if config is not None else 0.0
        setattr(group, "tunnel_invert_outlet_check", float(outlet_value) if outlet_value > 0 else None)

        roughness_value = cls._safe_float(getattr(group, "roughness", None), 0.0)
        if roughness_value <= 0:
            roughness_value = cls._safe_float(getattr(start_node, "roughness", None), 0.0)
        if roughness_value <= 0:
            roughness_value = cls._safe_float(getattr(group, "tunnel_roughness_n", None), 0.0)
        if roughness_value <= 0:
            roughness_value = cls._safe_float(getattr(config, "tunnel_roughness_n", None), 0.0) if config is not None else 0.0
        setattr(group, "tunnel_roughness_n", float(roughness_value) if roughness_value > 0 else None)

        config_section_type = getattr(config, "tunnel_section_type", "") if config is not None else ""
        detected_section_type = cls._detect_tunnel_section_type(
            getattr(group, "tunnel_section_type", ""),
            structure_text,
        )
        section_type = detected_section_type or cls._detect_tunnel_section_type(config_section_type)
        setattr(group, "tunnel_section_type", section_type)
        setattr(group, "tunnel_section_params", cls._resolve_tunnel_section_params(group, config=config, section_type=section_type))
        roughness_n = cls._safe_float(getattr(group, "tunnel_roughness_n", None), 0.0)
        if roughness_n > 0:
            setattr(group, "roughness", roughness_n)
            for node in list(getattr(group, "rows", []) or []):
                try:
                    node.roughness = roughness_n
                except Exception:
                    continue
        slope_i = cls._safe_float(getattr(group, "tunnel_slope_i", None), 0.0)
        if slope_i > 0:
            for node in list(getattr(group, "rows", []) or []):
                try:
                    if cls._safe_float(getattr(node, "slope_i", None), 0.0) <= 0:
                        node.slope_i = slope_i
                except Exception:
                    continue

    @staticmethod
    def _fmt_radius(value: float) -> str:
        if value and value > 0:
            return f"{float(value):.2f}"
        return ""

    @staticmethod
    def _fmt_turn_n(value: float) -> str:
        if value and value > 0:
            return f"{float(value):.3f}".rstrip("0").rstrip(".")
        return ""

    def _collect_group_d_values(self, group) -> List[float]:
        values = []
        for node in self._group_edit_rows(group):
            sp = getattr(node, "section_params", {}) or {}
            d_val = self._safe_float(sp.get("D", 0.0), 0.0)
            values.append(d_val)
        return values

    def _suggest_group_d(self, group) -> float:
        d_values = self._collect_group_d_values(group)
        valid_vals = [round(v, 6) for v in d_values if v > 0]
        if valid_vals:
            counter = Counter(valid_vals)
            max_count = max(counter.values())
            candidates = [val for val, cnt in counter.items() if cnt == max_count]
            if len(candidates) == 1:
                return float(candidates[0])
            inlet_d = self._safe_float(getattr(group, "diameter", 0.0), 0.0)
            if inlet_d > 0:
                return inlet_d
            return float(candidates[0])
        inlet_d = self._safe_float(getattr(group, "diameter", 0.0), 0.0)
        return inlet_d if inlet_d > 0 else 0.0

    def _is_group_d_consistent(self, group) -> bool:
        d_values = [round(v, 6) for v in self._collect_group_d_values(group) if v > 0]
        if not d_values:
            return False
        return len(set(d_values)) == 1

    def _group_radius_values(self, group) -> List[float]:
        values = []
        for node in self._group_edit_rows(group):
            r_val = self._safe_float(getattr(node, "turn_radius", 0.0), 0.0)
            if r_val > 0:
                values.append(round(r_val, 6))
        return sorted(set(values))

    def _apply_group_d_override(self, group, target_d: float):
        if target_d <= 0:
            return
        rounded_d = round(float(target_d), 3)
        for node in self._group_edit_rows(group):
            if not hasattr(node, "section_params") or not node.section_params:
                node.section_params = {}
            node.section_params["D"] = rounded_d
        group.diameter = rounded_d
        self._d_override_payload[self._group_storage_key(group)] = rounded_d

    def _build_group_identity(self, group) -> str:
        return self._group_identity(group)

    def _persist_group_radius_config(self, group, turn_n: float, turn_r: float, force_override: bool):
        if not self._manager:
            return
        group_key = self._group_storage_key(group)
        route_key = self._group_route_key(group)
        cfg = self._get_manager_group_config(group)
        if cfg is None:
            try:
                from managers.pressure_pipe_manager import PressurePipeConfig
                cfg = PressurePipeConfig()
            except Exception:
                return
            cfg.name = self._group_display_name(group)
            cfg.Q = float(getattr(group, "design_flow", 0.0) or 0.0)
            cfg.D = float(getattr(group, "diameter", 0.0) or 0.0)
            cfg.material_key = str(getattr(group, "material_key", "") or "")
            cfg.ip_points = list(getattr(group, "ip_points", []) or [])
        cfg.route_key = route_key
        cfg.route_display_name = self._group_route_display_name(group)
        cfg.turn_n = round(float(turn_n), 3) if turn_n > 0 else 0.0
        cfg.turn_R = round(float(turn_r), 2) if turn_r > 0 else 0.0
        cfg.force_override = bool(force_override)
        cfg.radius_applied_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        longitudinal_key = route_key or group_key
        cfg.longitudinal_nodes = self._longitudinal_data.get(
            longitudinal_key, getattr(cfg, "longitudinal_nodes", []) or []
        )
        self._manager.set_pipe_config(group_key, cfg)

    def _refresh_apply_summary_label(self):
        label = getattr(self, "_lbl_apply_summary", None)
        if not label:
            return
        applied = 0
        total = len(self._pipe_groups or [])
        for group in self._pipe_groups or []:
            cfg = self._radius_configs.get(self._group_storage_key(group), {})
            if bool(cfg.get("applied")) and self._safe_float(cfg.get("applied_turn_R", 0.0), 0.0) > 0:
                applied += 1
        if total <= 0:
            label.setText("平面R未检测到管道分组")
            return
        label.setText(f"平面R已应用 {applied}/{total} 组")

    def _resolve_group_turn_state(self, group) -> Dict[str, Any]:
        group_key = self._group_storage_key(group)
        cfg = dict(self._radius_configs.get(group_key, {}) or {})
        radius_values = self._group_radius_values(group)
        mixed_radius = len(radius_values) > 1
        row_r = radius_values[0] if len(radius_values) == 1 else 0.0
        suggest_d = self._suggest_group_d(group)
        has_cfg_turn_r = "turn_R" in cfg
        has_cfg_turn_n = "turn_n" in cfg

        turn_r = self._safe_float(cfg.get("turn_R", 0.0), 0.0)
        if (not has_cfg_turn_r) and turn_r <= 0 and row_r > 0:
            turn_r = row_r
        turn_n = self._safe_float(cfg.get("turn_n", 0.0), 0.0)
        if turn_n <= 0 and turn_r > 0 and suggest_d > 0:
            turn_n = turn_r / suggest_d
        if turn_n <= 0 and (not has_cfg_turn_n):
            turn_n = self._last_turn_n if self._last_turn_n > 0 else 3.0

        applied = bool(cfg.get("applied", False))
        applied_turn_r = self._safe_float(cfg.get("applied_turn_R", 0.0), 0.0)
        applied_turn_n = self._safe_float(cfg.get("applied_turn_n", 0.0), 0.0)
        if applied and applied_turn_r <= 0 and turn_r > 0:
            applied_turn_r = turn_r
        if applied and applied_turn_n <= 0:
            if turn_n > 0:
                applied_turn_n = turn_n
            elif applied_turn_r > 0 and suggest_d > 0:
                applied_turn_n = applied_turn_r / suggest_d

        cfg_turn_n = self._safe_float(cfg.get("turn_n", 0.0), 0.0)
        cfg_turn_r = self._safe_float(cfg.get("turn_R", 0.0), 0.0)
        dirty = bool(cfg.get("dirty", False))
        if applied and applied_turn_r > 0:
            same_as_applied = bool(
                cfg_turn_n > 0
                and cfg_turn_r > 0
                and abs(cfg_turn_r - applied_turn_r) <= 1e-9
                and abs(cfg_turn_n - applied_turn_n) <= 1e-9
            )
            if same_as_applied:
                dirty = False

        normalized = {
            "turn_n": round(float(turn_n), 6) if turn_n > 0 else 0.0,
            "turn_R": round(float(turn_r), 6) if turn_r > 0 else 0.0,
            "force_override": bool(cfg.get("force_override", False)),
            "applied": bool(applied and applied_turn_r > 0),
            "radius_applied_at": str(cfg.get("radius_applied_at", "") or ""),
            "dirty": dirty,
            "applied_turn_n": round(float(applied_turn_n), 6) if applied_turn_n > 0 else 0.0,
            "applied_turn_R": round(float(applied_turn_r), 6) if applied_turn_r > 0 else 0.0,
            "mixed_radius": mixed_radius,
            "radius_values": radius_values,
            "d_consistent": self._is_group_d_consistent(group),
            "suggest_d": suggest_d,
        }
        self._radius_configs[group_key] = dict(normalized)
        return normalized

    @staticmethod
    def _fmt_live_value(value: float, digits: int = 6) -> str:
        if value <= 0:
            return ""
        txt = f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
        return txt if txt else ""

    def _update_group_apply_button(self, group, dirty: bool):
        widgets = self._card_widgets.get(self._group_storage_key(group), {})
        btn_apply_group = widgets.get("btn_apply_group")
        if not btn_apply_group:
            return
        btn_apply_group.setText("应用*" if dirty else "应用")
        if dirty:
            btn_apply_group.setToolTip("参数已修改，尚未应用")
            btn_apply_group.setStyleSheet("font-weight: bold; color: #E65100;")
        else:
            btn_apply_group.setToolTip("")
            btn_apply_group.setStyleSheet("")

    def _set_group_dirty(self, group, dirty: bool):
        cfg = self._radius_configs.setdefault(self._group_storage_key(group), {})
        cfg["dirty"] = bool(dirty)

    def _update_group_radius_ui(self, group, preserve_input: bool = False):
        widgets = self._card_widgets.get(self._group_storage_key(group), {})
        if not widgets:
            return
        turn_n_edit = widgets.get("turn_n_edit")
        turn_r_edit = widgets.get("turn_r_edit")
        force_chk = widgets.get("force_override_chk")
        radius_status = widgets.get("radius_status_label")
        d_status = widgets.get("d_status_label")
        d_target_edit = widgets.get("d_target_edit")
        btn_unify_d = widgets.get("btn_unify_d")
        if not turn_n_edit or not turn_r_edit:
            return

        state = self._resolve_group_turn_state(group)
        _keep_n_text = turn_n_edit.text() if preserve_input else None
        _keep_r_text = turn_r_edit.text() if preserve_input else None

        self._syncing_radius = True
        try:
            if state["turn_n"] > 0:
                turn_n_edit.setText(self._fmt_turn_n(state["turn_n"]))
            elif not turn_n_edit.text().strip():
                turn_n_edit.setText("")

            if state["turn_R"] > 0:
                turn_r_edit.setText(self._fmt_radius(state["turn_R"]))
                turn_r_edit.setPlaceholderText("输入 R (m)")
            else:
                if not turn_r_edit.text().strip():
                    turn_r_edit.setText("")
                turn_r_edit.setPlaceholderText("混合值" if state["mixed_radius"] else "输入 R (m)")

            if force_chk is not None and force_chk.isChecked() != state["force_override"]:
                force_chk.setChecked(state["force_override"])
        finally:
            self._syncing_radius = False
        if preserve_input:
            self._syncing_radius = True
            try:
                turn_n_edit.setText(_keep_n_text or "")
                turn_r_edit.setText(_keep_r_text or "")
            finally:
                self._syncing_radius = False

        if d_target_edit:
            cur_txt = d_target_edit.text().strip()
            if (not cur_txt) and state["suggest_d"] > 0:
                d_target_edit.setText(f"{state['suggest_d']:.3f}")
        if d_status:
            if state["d_consistent"] and state["suggest_d"] > 0:
                d_status.setText(f"D一致：{state['suggest_d']:.3f} m")
                d_status.setStyleSheet("font-size: 12px; color: #2E7D32;")
            elif state["d_consistent"]:
                d_status.setText("D一致：当前值为空")
                d_status.setStyleSheet("font-size: 12px; color: #2E7D32;")
            else:
                d_values = ", ".join(f"{v:.3f}" for v in self._collect_group_d_values(group) if v > 0)
                d_status.setText(f"D不一致（已阻断应用）：{d_values or '无有效D'}")
                d_status.setStyleSheet("font-size: 12px; color: #D84315;")
        if btn_unify_d:
            btn_unify_d.setEnabled(not state["d_consistent"])

        self._update_group_apply_button(group, bool(state.get("dirty", False)))
        if radius_status:
            if state.get("dirty", False):
                radius_status.setText("已修改未应用：当前输入仅预览，点击“应用”后生效")
                radius_status.setStyleSheet("font-size: 12px; color: #EF6C00;")
            elif state["mixed_radius"] and state["turn_R"] <= 0:
                radius_status.setText("平面R为混合值：建议先应用统一参数")
                radius_status.setStyleSheet("font-size: 12px; color: #EF6C00;")
            elif state["applied"] and state["applied_turn_R"] > 0:
                ts = state["radius_applied_at"]
                suffix = f"（{ts}）" if ts else ""
                radius_status.setText(
                    f"已应用：R={state['applied_turn_R']:.2f} m, n={state['applied_turn_n']:.3f}{suffix}"
                )
                radius_status.setStyleSheet("font-size: 12px; color: #2E7D32;")
            else:
                radius_status.setText("未应用平面R参数")
                radius_status.setStyleSheet("font-size: 12px; color: #546E7A;")

        self._refresh_apply_summary_label()

    def _on_group_turn_n_changed(self, group):
        if self._syncing_radius:
            return
        widgets = self._card_widgets.get(self._group_storage_key(group), {})
        turn_n_edit = widgets.get("turn_n_edit")
        turn_r_edit = widgets.get("turn_r_edit")
        if not turn_n_edit or not turn_r_edit:
            return
        cfg = self._radius_configs.setdefault(self._group_storage_key(group), {})
        raw_n = turn_n_edit.text().strip()
        turn_n = self._safe_float(raw_n, 0.0)
        n_valid = (raw_n != "") and (turn_n > 0)

        cfg["turn_n"] = round(float(turn_n), 6) if n_valid else 0.0
        self._set_group_dirty(group, True)

        can_link = n_valid and self._is_group_d_consistent(group)
        suggest_d = self._suggest_group_d(group) if can_link else 0.0
        if can_link and suggest_d > 0:
            turn_r = turn_n * suggest_d
            cfg["turn_R"] = round(float(turn_r), 6)
            self._last_turn_n = turn_n
            self._syncing_radius = True
            try:
                turn_r_edit.setText(self._fmt_live_value(turn_r, digits=6))
            finally:
                self._syncing_radius = False
        self._update_group_radius_ui(group, preserve_input=True)

    def _on_group_turn_r_changed(self, group):
        if self._syncing_radius:
            return
        widgets = self._card_widgets.get(self._group_storage_key(group), {})
        turn_n_edit = widgets.get("turn_n_edit")
        turn_r_edit = widgets.get("turn_r_edit")
        if not turn_n_edit or not turn_r_edit:
            return
        cfg = self._radius_configs.setdefault(self._group_storage_key(group), {})
        raw_r = turn_r_edit.text().strip()
        turn_r = self._safe_float(raw_r, 0.0)
        r_valid = (raw_r != "") and (turn_r > 0)

        cfg["turn_R"] = round(float(turn_r), 6) if r_valid else 0.0
        self._set_group_dirty(group, True)

        can_link = r_valid and self._is_group_d_consistent(group)
        suggest_d = self._suggest_group_d(group) if can_link else 0.0
        if can_link and suggest_d > 0:
            turn_n = turn_r / suggest_d
            cfg["turn_n"] = round(float(turn_n), 6)
            self._last_turn_n = turn_n
            self._syncing_radius = True
            try:
                turn_n_edit.setText(self._fmt_live_value(turn_n, digits=6))
            finally:
                self._syncing_radius = False
        self._update_group_radius_ui(group, preserve_input=True)

    def _on_group_turn_n_editing_finished(self, group):
        if self._syncing_radius:
            return
        widgets = self._card_widgets.get(self._group_storage_key(group), {})
        turn_n_edit = widgets.get("turn_n_edit")
        if not turn_n_edit:
            return
        raw_n = turn_n_edit.text().strip()
        turn_n = self._safe_float(raw_n, 0.0)
        if raw_n and turn_n > 0:
            cfg = self._radius_configs.setdefault(self._group_storage_key(group), {})
            cfg["turn_n"] = round(float(turn_n), 6)
            self._syncing_radius = True
            try:
                turn_n_edit.setText(self._fmt_turn_n(turn_n))
            finally:
                self._syncing_radius = False
        self._update_group_radius_ui(group, preserve_input=False)

    def _on_group_turn_r_editing_finished(self, group):
        if self._syncing_radius:
            return
        widgets = self._card_widgets.get(self._group_storage_key(group), {})
        turn_r_edit = widgets.get("turn_r_edit")
        if not turn_r_edit:
            return
        raw_r = turn_r_edit.text().strip()
        turn_r = self._safe_float(raw_r, 0.0)
        if raw_r and turn_r > 0:
            cfg = self._radius_configs.setdefault(self._group_storage_key(group), {})
            cfg["turn_R"] = round(float(turn_r), 6)
            self._syncing_radius = True
            try:
                turn_r_edit.setText(self._fmt_radius(turn_r))
            finally:
                self._syncing_radius = False
        self._update_group_radius_ui(group, preserve_input=False)

    def _on_unify_group_d_clicked(self, group):
        widgets = self._card_widgets.get(self._group_storage_key(group), {})
        d_target_edit = widgets.get("d_target_edit")
        target_d = self._safe_float(d_target_edit.text() if d_target_edit else "", 0.0)
        if target_d <= 0:
            target_d = self._suggest_group_d(group)
        if target_d <= 0:
            fluent_error(self, "统一D失败", f"组“{self._group_display_name(group)}”未找到有效D建议值")
            return
        self._apply_group_d_override(group, target_d)
        if d_target_edit:
            d_target_edit.setText(f"{target_d:.3f}")
        self._update_group_radius_ui(group)
        fluent_info(self, "已统一D", f"组“{self._group_display_name(group)}”已统一为 D={target_d:.3f} m")

    def _apply_group_radius(self, group):
        group_key = self._group_storage_key(group)
        widgets = self._card_widgets.get(group_key, {})
        turn_n_edit = widgets.get("turn_n_edit")
        turn_r_edit = widgets.get("turn_r_edit")
        force_chk = widgets.get("force_override_chk")
        if not turn_n_edit or not turn_r_edit:
            return False, "缺少R参数输入控件"

        if not self._is_group_d_consistent(group):
            return False, "组内D不一致，请先执行“一键统一D”"

        suggest_d = self._suggest_group_d(group)
        if suggest_d <= 0:
            return False, "未检测到有效D，无法计算R=n×D"

        turn_n_in = self._safe_float(turn_n_edit.text(), 0.0)
        turn_r_in = self._safe_float(turn_r_edit.text(), 0.0)

        if turn_r_in > 0:
            turn_r = round(turn_r_in, 2)
            turn_n = round((turn_r / suggest_d), 3) if suggest_d > 0 else round(turn_n_in, 3)
        elif turn_n_in > 0:
            turn_n = round(turn_n_in, 3)
            turn_r = round(turn_n * suggest_d, 2)
        else:
            base_n = self._last_turn_n if self._last_turn_n > 0 else 3.0
            turn_n = round(base_n, 3)
            turn_r = round(turn_n * suggest_d, 2)

        if turn_r <= 0:
            return False, "转弯半径R无效"

        force_override = bool(force_chk.isChecked()) if force_chk else False
        applied_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._radius_configs[group_key] = {
            "turn_n": turn_n,
            "turn_R": turn_r,
            "force_override": force_override,
            "applied": True,
            "radius_applied_at": applied_at,
            "dirty": False,
            "applied_turn_n": turn_n,
            "applied_turn_R": turn_r,
        }
        self._last_turn_n = turn_n

        self._syncing_radius = True
        try:
            turn_n_edit.setText(self._fmt_turn_n(turn_n))
            turn_r_edit.setText(self._fmt_radius(turn_r))
        finally:
            self._syncing_radius = False

        self._persist_group_radius_config(group, turn_n, turn_r, force_override)
        self._update_group_radius_ui(group)
        return True, f"R={turn_r:.2f} m, n={turn_n:.3f}"

    def _on_apply_group_clicked(self, group):
        ok, message = self._apply_group_radius(group)
        if ok:
            fluent_info(self, "应用成功", f"组“{self._group_display_name(group)}”已应用：{message}")
        else:
            fluent_error(self, "应用失败", f"组“{self._group_display_name(group)}”：{message}")

    def _on_apply_all_groups_clicked(self):
        selected_groups = []
        for group in self._pipe_groups or []:
            widgets = self._card_widgets.get(self._group_storage_key(group), {})
            force_chk = widgets.get("force_override_chk")
            if force_chk and force_chk.isChecked():
                selected_groups.append(group)

        if not selected_groups:
            self._last_apply_summary = {"ok": 0, "failed": 0, "skipped": len(self._pipe_groups or [])}
            self._refresh_apply_summary_label()
            fluent_info(self, "提示", "未勾选“强制覆盖表1”的分组，未执行批量应用")
            return

        ok_count = 0
        failed_msgs = []
        for group in selected_groups:
            ok, msg = self._apply_group_radius(group)
            if ok:
                ok_count += 1
            else:
                failed_msgs.append(f"{self._group_display_name(group)}: {msg}")

        self._last_apply_summary = {
            "ok": ok_count,
            "failed": len(failed_msgs),
            "skipped": max(0, len(self._pipe_groups or []) - len(selected_groups)),
            "failed_messages": failed_msgs,
        }
        self._refresh_apply_summary_label()

        if failed_msgs:
            fluent_error(
                self,
                "部分组应用失败",
                f"成功 {ok_count} 组，失败 {len(failed_msgs)} 组。\n" + "\n".join(failed_msgs[:8]),
            )
        else:
            fluent_info(
                self,
                "全部应用完成",
                f"已应用 {ok_count} 组（仅处理勾选“强制覆盖表1”的分组）",
            )

    def get_turn_radius_payload(self) -> Dict[str, Dict[str, Any]]:
        payload: Dict[str, Dict[str, Any]] = {}
        for group in self._pipe_groups or []:
            state = self._resolve_group_turn_state(group)
            applied_turn_r = self._safe_float(state.get("applied_turn_R", 0.0), 0.0)
            applied_turn_n = self._safe_float(state.get("applied_turn_n", 0.0), 0.0)
            if (not state["applied"]) and (not state["force_override"]):
                continue
            if applied_turn_r <= 0:
                continue
            payload[self._group_storage_key(group)] = {
                "turn_n": round(float(applied_turn_n), 3) if applied_turn_n > 0 else 0.0,
                "turn_R": round(float(applied_turn_r), 2) if applied_turn_r > 0 else 0.0,
                "force_override": bool(state["force_override"]),
                "applied": bool(state["applied"] and applied_turn_r > 0),
                "radius_applied_at": str(state["radius_applied_at"] or ""),
                "row_indices": list(getattr(group, "row_indices", []) or []),
                "identity": self._build_group_identity(group),
                "display_name": self._group_display_name(group),
            }
        return payload

    def get_d_override_payload(self) -> Dict[str, float]:
        return {k: round(float(v), 3) for k, v in (self._d_override_payload or {}).items() if float(v) > 0}

    def get_apply_summary(self) -> Dict[str, Any]:
        return dict(self._last_apply_summary or {})

    def _init_ui(self):
        """初始化UI"""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)

        # 标题说明
        title = QLabel("有压管道水力计算配置")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #1976D2;")
        lay.addWidget(title)

        desc = QLabel(
            "系统将根据表格中的有压管道数据，计算沿程损失、弯头损失、渐变段损失等，\n"
            "并将总水头损失回写到\"倒虹吸/有压管道水头损失\"列。"
        )
        desc.setStyleSheet("font-size: 12px; color: #616161;")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        # 分隔线
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #E0E0E0;")
        lay.addWidget(line)

        # 如果有多个管道，显示管道卡片
        route_only_mode = bool(self._xxpipe_route_mode and self._route_contexts)
        if self._pipe_groups or self._pressure_chains:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

            scroll_widget = QWidget()
            scroll_lay = QVBoxLayout(scroll_widget)
            scroll_lay.setSpacing(12)

            used_group_keys = set()
            for route_context in self._route_contexts.values():
                route_card = self._create_route_card(route_context)
                scroll_lay.addWidget(route_card)
            if not route_only_mode:
                for chain in self._pressure_chains:
                    scroll_lay.addWidget(self._create_pressure_chain_card(chain, used_group_keys))

            for group in self._pipe_groups:
                if self._group_storage_key(group) in used_group_keys:
                    continue
                if route_only_mode and not self._group_is_tunnel_segment(group):
                    continue
                card = self._create_pipe_card(group)
                scroll_lay.addWidget(card)

            scroll_lay.addStretch()
            scroll.setWidget(scroll_widget)
            self._pipe_scroll_area = scroll
            self._pipe_scroll_widget = scroll_widget
            lay.addWidget(scroll, 1)

            if not route_only_mode:
                radius_toolbar = QHBoxLayout()
                radius_toolbar.setSpacing(10)
                self._lbl_apply_summary = QLabel("平面R尚未应用")
                self._lbl_apply_summary.setStyleSheet("font-size: 12px; color: #546E7A;")
                radius_toolbar.addWidget(self._lbl_apply_summary, 1)
                btn_apply_all = PushButton("应用到全部管道")
                btn_apply_all.clicked.connect(self._on_apply_all_groups_clicked)
                radius_toolbar.addWidget(btn_apply_all, 0, Qt.AlignRight)
                lay.addLayout(radius_toolbar)
                self._refresh_apply_summary_label()

        lay.addStretch()

        # 底部按钮
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()

        try:
            from qfluentwidgets import PushButton as FluentPushButton
            from qfluentwidgets import PrimaryPushButton as FluentPrimaryPushButton
            btn_cancel = FluentPushButton("取消")
            btn_start = FluentPrimaryPushButton("开始计算")
        except ImportError:
            btn_cancel = QPushButton("取消")
            btn_start = QPushButton("开始计算")

        btn_cancel.setFixedWidth(90)
        btn_start.setFixedWidth(110)

        btn_cancel.clicked.connect(self.reject)
        btn_start.clicked.connect(self.accept)

        btn_lay.addWidget(btn_cancel)
        btn_lay.addSpacing(10)
        btn_lay.addWidget(btn_start)

        lay.addLayout(btn_lay)

    def accept(self):
        """开始计算前，先校验 xx管 整线是否已导入纵断面。"""
        missing_route_keys = self._collect_missing_xxpipe_route_keys()
        incomplete_route_states = self._collect_incomplete_xxpipe_route_states()
        if missing_route_keys or incomplete_route_states:
            blocked_route_keys = list(dict.fromkeys(list(incomplete_route_states.keys()) + list(missing_route_keys)))
            self._apply_xxpipe_route_missing_highlights(blocked_route_keys)
            self._focus_missing_xxpipe_route(blocked_route_keys[0])
            if incomplete_route_states:
                first_route_key = blocked_route_keys[0]
                coverage_state = incomplete_route_states.get(first_route_key) or {}
                display_name = str(
                    coverage_state.get("display_name", "") or self._resolve_pipe_label(first_route_key)
                ).strip()
                fluent_error(
                    self,
                    "纵断面仍不完整",
                    self._build_xxpipe_import_coverage_error_message(display_name, coverage_state),
                )
                return
            fluent_error(self, "缺少步骤", self._build_missing_xxpipe_route_message(missing_route_keys))
            return
        self._apply_xxpipe_route_missing_highlights([])
        tunnel_error = self._validate_and_persist_tunnel_group_configs()
        if tunnel_error:
            group_key, message = tunnel_error
            self._focus_tunnel_group_card(group_key)
            fluent_error(self, "隧洞参数不完整", message)
            return
        super().accept()

    @staticmethod
    def _pick_size_value(*values) -> int:
        positive = [int(v) for v in values if isinstance(v, (int, float)) and int(v) > 0]
        return max(positive) if positive else 0

    def _available_geometry(self):
        screen = None
        parent_widget = self.parentWidget()
        if parent_widget is not None:
            parent_window = parent_widget.window()
            if parent_window is not None and parent_window.windowHandle() is not None:
                screen = parent_window.windowHandle().screen()
            if screen is None and parent_window is not None:
                try:
                    screen = parent_window.screen()
                except Exception:
                    screen = None
        if screen is None:
            app = QApplication.instance()
            if app is not None:
                screen = app.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    def _resolve_content_size(self) -> QSize:
        root_layout = self.layout()
        if root_layout is None:
            return QSize(self.minimumWidth(), self.minimumHeight())

        self.ensurePolished()
        root_layout.activate()

        margins = root_layout.contentsMargins()
        spacing = max(0, root_layout.spacing())
        total_w = margins.left() + margins.right()
        total_h = margins.top() + margins.bottom()
        visible_items = 0

        for index in range(root_layout.count()):
            item = root_layout.itemAt(index)
            if item is None or item.spacerItem() is not None:
                continue

            if item.widget() is not None:
                widget = item.widget()
                if widget is self._pipe_scroll_area and self._pipe_scroll_widget is not None:
                    self._pipe_scroll_widget.adjustSize()
                    hint = self._pipe_scroll_widget.sizeHint()
                    width_hint = self._pick_size_value(
                        hint.width(),
                        self._pipe_scroll_widget.minimumSizeHint().width(),
                    )
                    height_hint = self._pick_size_value(
                        hint.height(),
                        self._pipe_scroll_widget.minimumSizeHint().height(),
                    )
                else:
                    hint = widget.sizeHint()
                    width_hint = self._pick_size_value(
                        hint.width(),
                        widget.minimumSizeHint().width(),
                        widget.minimumWidth(),
                    )
                    height_hint = self._pick_size_value(
                        hint.height(),
                        widget.minimumSizeHint().height(),
                        widget.minimumHeight(),
                    )
            elif item.layout() is not None:
                hint = item.layout().sizeHint()
                width_hint = self._pick_size_value(hint.width())
                height_hint = self._pick_size_value(hint.height())
            else:
                continue

            total_w = max(total_w, margins.left() + margins.right() + width_hint)
            total_h += height_hint
            visible_items += 1

        if visible_items > 1:
            total_h += spacing * (visible_items - 1)

        total_w = max(self.minimumWidth(), total_w + self._WINDOW_CHROME_PADDING)
        total_h = max(self.minimumHeight(), total_h + self._WINDOW_CHROME_PADDING)
        return QSize(total_w, total_h)

    def _apply_initial_size(self):
        content_size = self._resolve_content_size()
        avail = self._available_geometry()
        if avail is not None:
            max_w = max(self.minimumWidth(), int(avail.width() * self._SCREEN_WIDTH_RATIO))
            max_h = max(self.minimumHeight(), int(avail.height() * self._SCREEN_HEIGHT_RATIO))
        else:
            max_w = self._FALLBACK_MAX_WIDTH
            max_h = self._FALLBACK_MAX_HEIGHT

        target_w = min(content_size.width(), max_w)
        target_h = min(content_size.height(), max_h)
        target_w = max(self.minimumWidth(), target_w)
        target_h = max(self.minimumHeight(), target_h)
        self.resize(target_w, target_h)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._did_apply_initial_size:
            self._apply_initial_size()
            self._did_apply_initial_size = True

    def _format_row_range_text(self, start_row_index, end_row_index) -> str:
        """格式化整线行号范围。"""
        if start_row_index is None or end_row_index is None:
            return "范围: -"
        return f"范围: 第{int(start_row_index) + 1}行 ~ 第{int(end_row_index) + 1}行"

    def _format_chainage_range_text(self, start_mc, end_mc) -> str:
        """格式化整线桩号范围。"""
        if start_mc is None or end_mc is None:
            return "桩号: -"
        return f"桩号: {float(start_mc):.3f} ~ {float(end_mc):.3f} m"

    def _build_route_summary_text(self, route_context: Dict[str, Any]) -> str:
        """生成整线摘要文本。"""
        groups = list(route_context.get("groups", []) or [])
        return (
            f"{self._format_row_range_text(route_context.get('route_start_row_index'), route_context.get('route_end_row_index'))}"
            f"  |  {self._format_chainage_range_text(route_context.get('route_start_mc'), route_context.get('route_end_mc'))}"
            f"  |  成员数: {len(groups)}"
        )

    def _build_segment_summary_text(self, group) -> str:
        """生成子段摘要文本。"""
        route_key = self._group_route_key(group)
        if not route_key:
            return ""
        route_name = self._group_route_display_name(group) or route_key
        segment_start = getattr(group, "segment_start_mc", None)
        segment_end = getattr(group, "segment_end_mc", None)
        if segment_start is None or segment_end is None:
            return f"整线: {route_name}  |  本段损失按子段单独计算"
        return (
            f"整线: {route_name}  |  本段桩号: {float(segment_start):.3f} ~ "
            f"{float(segment_end):.3f} m  |  本段损失按子段单独计算"
        )

    def _add_visual_section(self, card_lay, pipe_name: str, ip_points, is_route_card: bool = False) -> Dict[str, Any]:
        """为卡片补充统一的平面/纵断面可视化区域。"""
        from PySide6.QtWidgets import QPushButton, QTableWidget, QHeaderView

        toolbar = QHBoxLayout()
        try:
            from qfluentwidgets import PushButton as FPB
            btn_import = FPB("导入纵断面DXF")
            btn_clear = FPB("清空纵断面")
            btn_preview = FPB("预览")
        except ImportError:
            btn_import = QPushButton("导入纵断面DXF")
            btn_clear = QPushButton("清空纵断面")
            btn_preview = QPushButton("预览")

        btn_import.clicked.connect(lambda: self._import_longitudinal_dxf(pipe_name, ip_points))
        btn_clear.clicked.connect(lambda: self._clear_longitudinal(pipe_name))
        btn_preview.clicked.connect(lambda: self._open_canvas_viewer(pipe_name))
        btn_clear.setEnabled(False)
        has_ip_for_preview = len(ip_points or []) >= 2
        btn_preview.setEnabled(has_ip_for_preview)
        toolbar.addWidget(btn_import)
        toolbar.addWidget(btn_clear)
        toolbar.addWidget(btn_preview)
        toolbar.addStretch()
        card_lay.addLayout(toolbar)

        if self._xxpipe_route_mode and is_route_card:
            hint_text = "还未导入纵断面DXF，请点击上方按钮完成这一步"
        else:
            hint_text = "尚未导入纵断面数据，请点击「导入纵断面DXF」"
        hint_label = QLabel(hint_text)
        hint_label.setStyleSheet(
            "font-size: 12px; color: #E65100; background: #FFF8E1; "
            "border: 1px solid #FFE0B2; border-radius: 4px; "
            "padding: 8px 12px; font-weight: normal;"
        )
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setObjectName(f"hint_{pipe_name}")
        hint_label.setVisible(False)
        card_lay.addWidget(hint_label)

        import_guidance_label = QLabel(_build_longitudinal_dxf_import_guidance_text())
        import_guidance_label.setWordWrap(True)
        import_guidance_label.setStyleSheet(
            "font-size: 12px; color: #35516B; background: #F5F9FF; "
            "border: 1px solid #D6E4FF; border-radius: 4px; "
            "padding: 8px 12px; font-weight: normal;"
        )
        import_guidance_label.setObjectName(f"import_guidance_{pipe_name}")
        card_lay.addWidget(import_guidance_label)

        stats_label = QLabel("")
        stats_label.setStyleSheet(
            "font-size: 12px; color: #546E7A; background: #ECEFF1; "
            "border: 1px solid #CFD8DC; border-radius: 4px; "
            "padding: 6px 10px; font-weight: normal;"
        )
        stats_label.setWordWrap(True)
        stats_label.setObjectName(f"stats_{pipe_name}")
        stats_label.setVisible(False)
        card_lay.addWidget(stats_label)

        view_toolbar = QHBoxLayout()
        view_toolbar.setSpacing(4)
        btn_view_plan = QPushButton("平面图")
        btn_view_plan.setFixedSize(70, 26)
        btn_view_plan.setCursor(Qt.PointingHandCursor)
        btn_view_plan.setStyleSheet(self._VIEW_BTN_ACTIVE)
        btn_view_profile = QPushButton("纵断面")
        btn_view_profile.setFixedSize(70, 26)
        btn_view_profile.setCursor(Qt.PointingHandCursor)
        btn_view_profile.setStyleSheet(self._VIEW_BTN_INACTIVE)
        zoom_label = QLabel("100%")
        zoom_label.setStyleSheet("font-size: 11px; color: #90A4AE; font-weight: normal;")
        btn_zoom_reset = QPushButton("重置")
        btn_zoom_reset.setFixedSize(44, 22)
        btn_zoom_reset.setStyleSheet(
            "QPushButton { font-size: 11px; color: #546E7A; background: #ECEFF1; "
            "border: 1px solid #CFD8DC; border-radius: 3px; padding: 1px 6px; }"
            "QPushButton:hover { background: #CFD8DC; }"
        )
        btn_zoom_reset.setCursor(Qt.PointingHandCursor)
        view_toolbar.addWidget(btn_view_plan)
        view_toolbar.addWidget(btn_view_profile)
        view_toolbar.addStretch()
        view_toolbar.addWidget(zoom_label)
        view_toolbar.addWidget(btn_zoom_reset)
        card_lay.addLayout(view_toolbar)

        mini_canvas = SimpleProfileCanvas(self, fixed_height=200)
        mini_canvas.setObjectName(f"canvas_{pipe_name}")
        mini_canvas.setStyleSheet("border: 1px solid #CFD8DC; border-radius: 4px;")
        card_lay.addWidget(mini_canvas)
        mini_canvas.open_detail_requested.connect(
            lambda _name=pipe_name: self._open_canvas_viewer(_name)
        )

        btn_view_plan.clicked.connect(lambda: self._set_card_view_mode(pipe_name, "plan", sync_viewer=True))
        btn_view_profile.clicked.connect(lambda: self._set_card_view_mode(pipe_name, "profile", sync_viewer=True))
        btn_zoom_reset.clicked.connect(lambda _c=False, _name=pipe_name: self._on_canvas_zoom_reset(_name))

        if has_ip_for_preview:
            mini_canvas.set_ip_points(ip_points)
            mini_canvas.set_view_mode("plan")

        has_long = pipe_name in self._longitudinal_data and self._longitudinal_data[pipe_name]
        btn_view_profile.setEnabled(bool(has_long))

        expand_btn = QPushButton("▶ 查看详细节点数据")
        expand_btn.setStyleSheet(
            "QPushButton { font-size: 12px; color: #1976D2; background: transparent; "
            "border: none; text-align: left; padding: 4px 0; font-weight: normal; }"
            "QPushButton:hover { color: #1565C0; text-decoration: underline; }"
        )
        expand_btn.setCursor(Qt.PointingHandCursor)
        expand_btn.setObjectName(f"expand_{pipe_name}")
        expand_btn.setVisible(False)
        card_lay.addWidget(expand_btn)

        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["桩号(m)", "高程(m)", "竖曲线半径(m)", "转弯类型", "转角(°)"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setMaximumHeight(200)
        table.setObjectName(f"long_table_{pipe_name}")
        table.setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        card_lay.addWidget(table)

        def toggle_table(checked=False, _name=pipe_name):
            tbl = self.findChild(QTableWidget, f"long_table_{_name}")
            btn = self.findChild(QPushButton, f"expand_{_name}")
            if tbl and btn:
                vis = not tbl.isVisible()
                tbl.setVisible(vis)
                btn.setText("▼ 隐藏详细节点数据" if vis else "▶ 查看详细节点数据")

        expand_btn.clicked.connect(toggle_table)

        return {
            "hint": hint_label,
            "default_hint_text": hint_text,
            "import_guidance": import_guidance_label,
            "stats": stats_label,
            "canvas": mini_canvas,
            "expand_btn": expand_btn,
            "table": table,
            "btn_import": btn_import,
            "btn_clear": btn_clear,
            "btn_preview": btn_preview,
            "btn_view_plan": btn_view_plan,
            "btn_view_profile": btn_view_profile,
            "zoom_label": zoom_label,
            "btn_zoom_reset": btn_zoom_reset,
        }

    def _create_route_card(self, route_context: Dict[str, Any]):
        """为整线创建统一几何卡片。"""
        route_key = str(route_context.get("route_key", "") or "").strip()
        display_name = str(route_context.get("display_name", "") or route_key).strip()
        route_ip_points = list(route_context.get("ip_points", []) or [])

        card = QGroupBox(f"链路: {display_name}")
        card.setStyleSheet(self._ROUTE_CARD_STYLE)

        card_lay = QVBoxLayout(card)
        card_lay.setSpacing(10)

        info_label = QLabel(self._build_route_summary_text(route_context))
        info_label.setStyleSheet("font-size: 12px; color: #607D8B; font-weight: normal;")
        info_label.setWordWrap(True)
        card_lay.addWidget(info_label)

        if self._xxpipe_route_mode:
            desc_text = "整线卡负责统一导入平面/纵断面，当前弹窗仅保留整线轴线配置。"
        else:
            desc_text = "整线卡负责统一导入平面/纵断面，下面各分段只保留参数配置和分段计算。"
        desc_label = QLabel(desc_text)
        desc_label.setStyleSheet("font-size: 12px; color: #546E7A; font-weight: normal;")
        desc_label.setWordWrap(True)
        card_lay.addWidget(desc_label)

        visual_refs = self._add_visual_section(card_lay, route_key, route_ip_points, is_route_card=True)
        self._route_widgets[route_key] = {
            "card": card,
            "display_name": display_name,
            "route_context": route_context,
            **visual_refs,
        }
        if route_key in self._longitudinal_data and self._longitudinal_data[route_key]:
            self._update_card_data_state(route_key, show_data=True)
        else:
            self._update_card_data_state(route_key, show_data=False)
        return card

    def _update_tunnel_param_panel(self, group):
        """刷新隧洞摘要区，展示当前从表1读取到的结果。"""
        widgets = self._card_widgets.get(self._group_storage_key(group), {})
        value_map = {
            "section_type": widgets.get("tunnel_summary_section_type_value"),
            "size": widgets.get("tunnel_summary_size_value"),
            "roughness": widgets.get("tunnel_summary_roughness_value"),
            "slope": widgets.get("tunnel_summary_slope_value"),
            "hint": widgets.get("tunnel_summary_hint_label"),
        }
        if not any(value_map.values()):
            return
        snapshot = self._build_tunnel_group_snapshot(group, config=self._get_manager_group_config(group))
        if value_map["section_type"] is not None:
            value_map["section_type"].setText(snapshot["section_type_display"])
        if value_map["size"] is not None:
            value_map["size"].setText(snapshot["size_text"])
        if value_map["roughness"] is not None:
            value_map["roughness"].setText(snapshot["roughness_text"])
        if value_map["slope"] is not None:
            value_map["slope"].setText(snapshot["slope_text"])
        if value_map["hint"] is not None:
            value_map["hint"].setText(snapshot["hint_text"])

    def _create_tunnel_param_panel(self, card_lay, group, card_refs: Dict[str, Any]):
        """为隧洞子段创建只读摘要面板。"""
        panel = QFrame()
        panel.setStyleSheet(
            "QFrame { background: #FFF8E1; border: 1px solid #F0C36D; border-radius: 6px; }"
        )
        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(10, 8, 10, 8)
        panel_lay.setSpacing(8)

        title = QLabel("隧洞参数摘要")
        title.setStyleSheet("font-size: 12px; color: #8A4F00; font-weight: bold;")
        panel_lay.addWidget(title)

        note = QLabel(
            "当前按水力核算模式处理：本段隧洞参数直接从表1读取，当前窗口只展示读取结果；"
            "如需修改，请回表1调整。隧洞底线仍按计算结果反推显示，仅供水力核算，不作施工高程。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 12px; color: #7A5A00;")
        panel_lay.addWidget(note)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        section_type_value = QLabel("读取中")
        size_value = QLabel("读取中")
        roughness_value = QLabel("读取中")
        slope_value = QLabel("读取中")
        for value_label in (section_type_value, size_value, roughness_value, slope_value):
            value_label.setStyleSheet("font-size: 12px; color: #37474F;")
            value_label.setWordWrap(True)

        grid.addWidget(QLabel("断面类型："), 0, 0)
        grid.addWidget(section_type_value, 0, 1)
        grid.addWidget(QLabel("断面尺寸："), 0, 2)
        grid.addWidget(size_value, 0, 3)
        grid.addWidget(QLabel("糙率 n："), 1, 0)
        grid.addWidget(roughness_value, 1, 1)
        grid.addWidget(QLabel("坡降 i："), 1, 2)
        grid.addWidget(slope_value, 1, 3)
        panel_lay.addLayout(grid)

        hint_label = QLabel("")
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet(
            "font-size: 12px; color: #8A4F00; background: #FFF3CD; "
            "border: 1px solid #F0C36D; border-radius: 4px; padding: 6px 8px;"
        )
        panel_lay.addWidget(hint_label)

        card_refs.update(
            {
                "tunnel_summary_section_type_value": section_type_value,
                "tunnel_summary_size_value": size_value,
                "tunnel_summary_roughness_value": roughness_value,
                "tunnel_summary_slope_value": slope_value,
                "tunnel_summary_hint_label": hint_label,
            }
        )
        card_lay.addWidget(panel)
        self._update_tunnel_param_panel(group)

    def _create_pipe_card(self, group):
        """为单个管道创建卡片（分层结构：摘要 + 迷你画布 + 可展开表格）"""
        from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QHeaderView

        group_key = self._group_storage_key(group)
        display_name = self._group_display_name(group)
        route_key = self._group_route_key(group)
        route_managed = bool(route_key)

        card = QGroupBox(f"管道: {display_name}")
        card.setStyleSheet("""
            QGroupBox {
                font-size: 13px; font-weight: bold; color: #2C3E50;
                border: 2px solid #3498DB; border-radius: 8px;
                margin-top: 12px; padding: 16px 12px 12px 12px;
                background: #FFFFFF;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 16px;
                padding: 0 8px; background: #FFFFFF;
            }
        """)

        card_lay = QVBoxLayout(card)
        card_lay.setSpacing(10)

        # 基本信息
        info_label = QLabel(
            f"流量: {group.design_flow:.3f} m\u00b3/s  |  管径: {group.diameter:.3f} m  |  管材: {group.material_key}"
        )
        info_label.setStyleSheet("font-size: 12px; color: #7F8C8D; font-weight: normal;")
        card_lay.addWidget(info_label)

        segment_label = QLabel(self._build_segment_summary_text(group))
        segment_label.setStyleSheet("font-size: 12px; color: #607D8B; font-weight: normal;")
        segment_label.setWordWrap(True)
        segment_label.setVisible(route_managed)
        card_lay.addWidget(segment_label)

        # 平面转弯半径参数（R=n×D 与 R 双入口）
        radius_panel = QFrame()
        radius_panel.setStyleSheet(
            "QFrame { background: #F7FAFC; border: 1px solid #CFD8DC; border-radius: 6px; }"
        )
        radius_lay = QVBoxLayout(radius_panel)
        radius_lay.setContentsMargins(10, 8, 10, 8)
        radius_lay.setSpacing(6)

        row_n = QHBoxLayout()
        row_n.setSpacing(8)
        lbl_n_title = QLabel("转弯倍数 n（R = n × D）：")
        lbl_n_title.setStyleSheet("font-size: 12px; color: #1565C0; font-weight: bold;")
        row_n.addWidget(lbl_n_title)
        turn_n_edit = LineEdit()
        turn_n_edit.setPlaceholderText("如: 5")
        turn_n_edit.setFixedWidth(90)
        row_n.addWidget(turn_n_edit)
        lbl_n_hint = QLabel("（请确认倍数）")
        lbl_n_hint.setStyleSheet("color: #FF6600; font-size: 12px;")
        row_n.addWidget(lbl_n_hint)
        row_n.addStretch()
        radius_lay.addLayout(row_n)

        row_r = QHBoxLayout()
        row_r.setSpacing(8)
        lbl_r_title = QLabel("转弯半径 R（m）：")
        lbl_r_title.setStyleSheet("font-size: 12px; color: #37474F;")
        row_r.addWidget(lbl_r_title)
        turn_r_edit = LineEdit()
        turn_r_edit.setPlaceholderText("输入 R (m)")
        turn_r_edit.setFixedWidth(110)
        row_r.addWidget(turn_r_edit)
        lbl_r_hint = QLabel("← 修改 R 将反推 n")
        lbl_r_hint.setStyleSheet("color: #888; font-size: 12px;")
        row_r.addWidget(lbl_r_hint)
        row_r.addStretch()
        radius_lay.addLayout(row_r)

        row_d = QHBoxLayout()
        row_d.setSpacing(8)
        d_status_label = QLabel("")
        d_status_label.setStyleSheet("font-size: 12px; color: #546E7A;")
        row_d.addWidget(d_status_label, 1)
        row_d.addWidget(QLabel("统一D:"))
        d_target_edit = LineEdit()
        d_target_edit.setPlaceholderText("D(m)")
        d_target_edit.setFixedWidth(100)
        row_d.addWidget(d_target_edit)
        btn_unify_d = PushButton("一键统一D")
        btn_unify_d.clicked.connect(lambda: self._on_unify_group_d_clicked(group))
        row_d.addWidget(btn_unify_d)
        radius_lay.addLayout(row_d)

        row_apply = QHBoxLayout()
        row_apply.setSpacing(8)
        force_override_chk = QCheckBox("强制覆盖表1")
        row_apply.addWidget(force_override_chk)
        radius_status_label = QLabel("未应用平面R参数")
        radius_status_label.setStyleSheet("font-size: 12px; color: #546E7A;")
        row_apply.addWidget(radius_status_label, 1)
        btn_apply_group = PushButton("应用")
        btn_apply_group.clicked.connect(lambda: self._on_apply_group_clicked(group))
        row_apply.addWidget(btn_apply_group)
        radius_lay.addLayout(row_apply)

        turn_n_edit.textEdited.connect(lambda _txt, g=group: self._on_group_turn_n_changed(g))
        turn_r_edit.textEdited.connect(lambda _txt, g=group: self._on_group_turn_r_changed(g))
        turn_n_edit.editingFinished.connect(lambda g=group: self._on_group_turn_n_editing_finished(g))
        turn_r_edit.editingFinished.connect(lambda g=group: self._on_group_turn_r_editing_finished(g))

        card_lay.addWidget(radius_panel)

        card_refs = {
            'card': card,
            'display_name': display_name,
            'turn_n_edit': turn_n_edit,
            'turn_r_edit': turn_r_edit,
            'force_override_chk': force_override_chk,
            'radius_status_label': radius_status_label,
            'd_status_label': d_status_label,
            'd_target_edit': d_target_edit,
            'btn_unify_d': btn_unify_d,
            'btn_apply_group': btn_apply_group,
            'route_key': route_key,
        }
        self._card_widgets[group_key] = card_refs
        if self._group_is_tunnel_segment(group):
            self._create_tunnel_param_panel(card_lay, group, card_refs)
        if route_managed:
            notice_label = QLabel("整线几何、纵断面导入和预览已统一放到上方整线卡。")
            notice_label.setStyleSheet(
                "font-size: 12px; color: #546E7A; background: #F5F7FA; "
                "border: 1px solid #D9E2EC; border-radius: 4px; padding: 8px 10px;"
            )
            notice_label.setWordWrap(True)
            card_lay.addWidget(notice_label)
            card_refs['route_notice_label'] = notice_label
        else:
            card_refs.update(self._add_visual_section(card_lay, group_key, getattr(group, 'ip_points', []) or [], is_route_card=False))

        force_override_chk.toggled.connect(
            lambda checked, g=group_key: (
                self._radius_configs.setdefault(g, {}).update({"force_override": bool(checked)}),
                self._refresh_apply_summary_label()
            )
        )
        self._update_group_radius_ui(group)

        # 根据已有数据初始化状态
        has_long_data = group_key in self._longitudinal_data and self._longitudinal_data[group_key]
        if has_long_data:
            self._update_card_data_state(group_key, show_data=True)

        return card

    def _compute_stats(self, nodes):
        """计算纵断面节点统计摘要"""
        if not nodes:
            return ""
        chainages = [n['chainage'] for n in nodes]
        elevations = [n['elevation'] for n in nodes]
        arc_cnt = sum(1 for n in nodes if n.get('turn_type') in ('ARC', '圆弧') and n.get('turn_angle', 0) != 0)
        fold_cnt = sum(1 for n in nodes if n.get('turn_type') in ('FOLD', '折线') and n.get('turn_angle', 0) != 0)
        total_len = chainages[-1] - chainages[0] if len(chainages) >= 2 else 0

        parts = [
            f"节点数: {len(nodes)}",
            f"桩号: {chainages[0]:.1f} ~ {chainages[-1]:.1f} m",
            f"高程: {min(elevations):.2f} ~ {max(elevations):.2f} m",
        ]
        bend_parts = []
        if arc_cnt:
            bend_parts.append(f"圆弧\u00d7{arc_cnt}")
        if fold_cnt:
            bend_parts.append(f"折线\u00d7{fold_cnt}")
        if bend_parts:
            parts.append(f"弯头: {' '.join(bend_parts)}")
        parts.append(f"总长度: {total_len:.1f} m")
        return "  |  ".join(parts)

    def _collect_missing_xxpipe_route_keys(self) -> List[str]:
        """收集 xx管 模式下仍未导入纵断面的整线。"""
        if not (self._xxpipe_route_mode and self._route_contexts):
            return []
        missing = []
        for route_key in self._route_contexts.keys():
            if not (self._longitudinal_data.get(route_key) or []):
                missing.append(route_key)
        return missing

    def _collect_incomplete_xxpipe_route_states(self) -> Dict[str, Dict[str, Any]]:
        """收集已导入但仍未覆盖完整的整线。"""
        if not (self._xxpipe_route_mode and self._route_contexts):
            return {}

        incomplete: Dict[str, Dict[str, Any]] = {}
        for route_key in self._route_contexts.keys():
            longitudinal_nodes = list(self._longitudinal_data.get(route_key, []) or [])
            if not longitudinal_nodes:
                continue
            coverage_state = self._collect_xxpipe_route_import_coverage_state(
                route_key,
                longitudinal_nodes,
            )
            if list(coverage_state.get("station_errors", []) or []) or list(
                coverage_state.get("missing_targets", []) or []
            ):
                incomplete[route_key] = coverage_state
        return incomplete

    def _build_missing_xxpipe_route_message(self, route_keys: List[str]) -> str:
        """构造 xx管 缺少纵断面的统一提示语。"""
        route_names = [self._resolve_pipe_label(route_key) for route_key in route_keys if str(route_key).strip()]
        if len(route_names) == 1:
            return f"还差一步：请先为“{route_names[0]}”导入纵断面DXF，然后再开始计算。"
        route_text = "；".join(route_names)
        return f"还差一步：以下整线还没有导入纵断面DXF：{route_text}。请先分别导入后再开始计算。"

    @classmethod
    def _format_tunnel_size_text(cls, section_type: str, section_params: Dict[str, float]) -> str:
        """把隧洞尺寸参数整理成摘要文本。"""
        parts = []
        for param_key, _label_text in cls._TUNNEL_PARAM_SPECS.get(section_type, ()):
            value = cls._safe_float(section_params.get(param_key), 0.0)
            if value > 0:
                parts.append(f"{param_key} = {float(value):.3f} m")
        return "；".join(parts) if parts else "未填写"

    @classmethod
    def _build_tunnel_group_snapshot(cls, group, config=None) -> Dict[str, Any]:
        """整理当前隧洞分组的只读摘要与校验结果。"""
        cls._sync_group_tunnel_defaults(group, config=config)
        structure_text = cls._structure_type_text(getattr(group, "structure_type", ""))
        detected_section_type = cls._detect_tunnel_section_type(
            getattr(group, "tunnel_section_type", ""),
            structure_text,
        )
        resolved_section_type = detected_section_type or cls._detect_tunnel_section_type(
            getattr(config, "tunnel_section_type", "") if config is not None else ""
        )
        section_type = resolved_section_type or ""
        section_params = cls._resolve_tunnel_section_params(group, config=config, section_type=section_type)
        roughness_n = cls._safe_float(getattr(group, "tunnel_roughness_n", getattr(group, "roughness", None)), 0.0)
        slope_i = cls._safe_float(getattr(group, "tunnel_slope_i", None), 0.0)

        missing_items: List[str] = []
        if not section_type:
            missing_items.append("断面类型")
        required_params = cls._TUNNEL_PARAM_SPECS.get(section_type, ())
        normalized_params: Dict[str, float] = {}
        for param_key, label_text in required_params:
            value = cls._safe_float(section_params.get(param_key), 0.0)
            if value > 0:
                normalized_params[param_key] = float(value)
            else:
                missing_items.append(label_text)
        if roughness_n <= 0:
            missing_items.append("糙率 n")
        if slope_i <= 0:
            missing_items.append("坡降 i")

        hint_text = "参数请回表1修改。"
        if missing_items:
            hint_text = f"参数请回表1修改；当前缺少：{'、'.join(missing_items)}。"

        return {
            "display_name": cls._group_display_name(group),
            "section_type": section_type,
            "section_type_display": section_type or "未填写",
            "section_params": normalized_params,
            "size_text": cls._format_tunnel_size_text(section_type, normalized_params),
            "roughness_n": float(roughness_n) if roughness_n > 0 else None,
            "roughness_text": cls._fmt_live_value(roughness_n, digits=4) if roughness_n > 0 else "未填写",
            "slope_i": float(slope_i) if slope_i > 0 else None,
            "slope_text": cls._fmt_live_value(slope_i, digits=6) if slope_i > 0 else "未填写",
            "missing_items": missing_items,
            "hint_text": hint_text,
        }

    @staticmethod
    def _build_tunnel_group_error_message(snapshot: Dict[str, Any]) -> str:
        """生成开始计算前的隧洞缺项提示。"""
        display_name = str(snapshot.get("display_name", "") or "").strip() or "当前隧洞段"
        missing_items = list(snapshot.get("missing_items", []) or [])
        if not missing_items:
            return ""
        if len(missing_items) == 1:
            return f"“{display_name}”缺少{missing_items[0]}，参数请回表1修改。"
        return f"“{display_name}”缺少以下参数：{'、'.join(missing_items)}，参数请回表1修改。"

    def _validate_and_persist_tunnel_group_configs(self):
        """校验隧洞参数，并把表1派生快照写回分组与缓存。"""
        for group in self._pipe_groups or []:
            if not self._group_is_tunnel_segment(group):
                continue

            snapshot = self._build_tunnel_group_snapshot(group, config=self._get_manager_group_config(group))
            if snapshot["missing_items"]:
                return self._group_storage_key(group), self._build_tunnel_group_error_message(snapshot)

            setattr(group, "segment_geometry_source", "generated_tunnel")
            setattr(group, "tunnel_slope_i", float(snapshot["slope_i"]))
            setattr(group, "tunnel_roughness_n", float(snapshot["roughness_n"]))
            setattr(group, "tunnel_profile_mode", self._TUNNEL_PROFILE_MODE_HYDRAULIC)
            setattr(group, "tunnel_section_type", snapshot["section_type"])
            setattr(group, "tunnel_section_params", dict(snapshot["section_params"]))
            setattr(group, "roughness", float(snapshot["roughness_n"]))
            for node in list(getattr(group, "rows", []) or []):
                try:
                    node.roughness = float(snapshot["roughness_n"])
                    node.slope_i = float(snapshot["slope_i"])
                except Exception:
                    continue
            self._persist_tunnel_group_config(group)
        return None

    def _persist_tunnel_group_config(self, group):
        """把隧洞参数持久化到有压管道配置里。"""
        if not self._manager:
            return
        try:
            from managers.pressure_pipe_manager import PressurePipeConfig
        except Exception:
            return

        group_key = self._group_storage_key(group)
        cfg = self._get_manager_group_config(group)
        if cfg is None:
            cfg = PressurePipeConfig()
            cfg.name = self._group_display_name(group)
            cfg.Q = float(getattr(group, "design_flow", 0.0) or 0.0)
            cfg.D = float(getattr(group, "diameter", 0.0) or 0.0)
            cfg.material_key = str(getattr(group, "material_key", "") or "")
            cfg.ip_points = list(getattr(group, "ip_points", []) or [])

        cfg.route_key = self._group_route_key(group)
        cfg.route_display_name = self._group_route_display_name(group)
        cfg.segment_geometry_source = str(getattr(group, "segment_geometry_source", "") or "").strip()
        cfg.tunnel_invert_inlet = getattr(group, "tunnel_invert_inlet", None)
        cfg.tunnel_slope_i = getattr(group, "tunnel_slope_i", None)
        cfg.tunnel_invert_outlet_check = getattr(group, "tunnel_invert_outlet_check", None)
        cfg.tunnel_roughness_n = getattr(group, "tunnel_roughness_n", None)
        cfg.tunnel_profile_mode = str(getattr(group, "tunnel_profile_mode", "") or "").strip()
        cfg.tunnel_section_type = str(getattr(group, "tunnel_section_type", "") or "").strip()
        cfg.tunnel_section_params = dict(getattr(group, "tunnel_section_params", {}) or {})
        longitudinal_key = cfg.route_key or group_key
        cfg.longitudinal_nodes = list(
            self._longitudinal_data.get(longitudinal_key, getattr(cfg, "longitudinal_nodes", []) or [])
        )
        self._manager.set_pipe_config(group_key, cfg)

    def get_tunnel_payload(self) -> Dict[str, Dict[str, Any]]:
        """兼容旧接口：隧洞参数不再通过弹窗回写主表。"""
        return {}

    def _set_route_missing_longitudinal_highlight(self, route_key: str, highlighted: bool):
        """切换整线卡与导入按钮的高亮状态。"""
        widgets = self._route_widgets.get(str(route_key or "").strip(), {})
        card = widgets.get("card")
        btn_import = widgets.get("btn_import")
        if card is not None:
            card.setProperty("missing_longitudinal_highlight", bool(highlighted))
            card.setStyleSheet(self._ROUTE_CARD_HIGHLIGHT_STYLE if highlighted else self._ROUTE_CARD_STYLE)
            card.style().unpolish(card)
            card.style().polish(card)
        if btn_import is not None:
            btn_import.setProperty("missing_longitudinal_highlight", bool(highlighted))
            btn_import.setStyleSheet(self._IMPORT_BTN_HIGHLIGHT_STYLE if highlighted else "")
            btn_import.style().unpolish(btn_import)
            btn_import.style().polish(btn_import)

    def _apply_xxpipe_route_missing_highlights(self, missing_route_keys: List[str]):
        """按缺失情况统一刷新整线卡高亮。"""
        missing_set = {str(item or "").strip() for item in (missing_route_keys or []) if str(item or "").strip()}
        for route_key in self._route_widgets.keys():
            self._set_route_missing_longitudinal_highlight(route_key, route_key in missing_set)

    def _focus_missing_xxpipe_route(self, route_key: str):
        """滚动到缺失纵断面的整线卡，并把焦点落到导入按钮。"""
        widgets = self._route_widgets.get(str(route_key or "").strip(), {})
        card = widgets.get("card")
        btn_import = widgets.get("btn_import")
        if card is not None and self._pipe_scroll_area is not None:
            try:
                self._pipe_scroll_area.ensureWidgetVisible(card, 0, 80)
            except Exception:
                pass
        if btn_import is not None:
            try:
                btn_import.setFocus(Qt.OtherFocusReason)
            except Exception:
                pass

    def _focus_tunnel_group_card(self, group_key: str):
        """滚动到隧洞参数卡，并尽量把焦点落到提示区域。"""
        widgets = self._card_widgets.get(str(group_key or "").strip(), {})
        card = widgets.get("card")
        edit = widgets.get("tunnel_summary_hint_label")
        if card is not None and self._pipe_scroll_area is not None:
            try:
                self._pipe_scroll_area.ensureWidgetVisible(card, 0, 80)
            except Exception:
                pass
        if edit is not None:
            try:
                edit.setFocus(Qt.OtherFocusReason)
            except Exception:
                pass

    def _on_canvas_zoom_reset(self, pipe_name):
        """重置画布缩放"""
        w = self._lookup_visual_widgets(pipe_name)
        canvas = w.get('canvas')
        if not w or canvas is None:
            return
        canvas.zoom_reset()
        if w.get('zoom_label') is not None:
            w['zoom_label'].setText(f"{canvas.get_zoom_percent()}%")

    def _set_card_view_mode(self, pipe_name, mode, sync_viewer=False):
        w = self._lookup_visual_widgets(pipe_name)
        canvas = w.get('canvas')
        if not w or canvas is None:
            return
        has_profile = canvas.has_profile_data()
        has_plan = canvas.has_plan_data()
        if mode == "profile" and not has_profile:
            return
        if mode == "plan" and not has_plan:
            return
        canvas.set_view_mode(mode)
        w['zoom_label'].setText(f"{canvas.get_zoom_percent()}%")
        if mode == "plan":
            w['btn_view_plan'].setStyleSheet(self._VIEW_BTN_ACTIVE)
            w['btn_view_profile'].setStyleSheet(self._VIEW_BTN_INACTIVE)
        else:
            w['btn_view_plan'].setStyleSheet(self._VIEW_BTN_INACTIVE)
            w['btn_view_profile'].setStyleSheet(self._VIEW_BTN_ACTIVE)
        if sync_viewer and self._active_viewer_pipe_name == pipe_name:
            self._sync_canvas_viewer(pipe_name)

    def _ensure_canvas_viewer(self):
        viewer = getattr(self, "_canvas_viewer", None)
        if viewer is not None:
            return viewer
        viewer = LongitudinalPreviewDialog(self)
        viewer.view_mode_changed.connect(self._on_viewer_mode_changed)
        self._canvas_viewer = viewer
        return viewer

    def _sync_canvas_viewer(self, pipe_name):
        viewer = getattr(self, "_canvas_viewer", None)
        if viewer is None:
            return
        widgets = self._lookup_visual_widgets(pipe_name)
        if not widgets or widgets.get("canvas") is None:
            return
        self._active_viewer_pipe_name = pipe_name
        viewer.sync_pipe_data(
            pipe_name=self._resolve_pipe_label(pipe_name),
            nodes=self._longitudinal_data.get(pipe_name) or [],
            ip_points=getattr(widgets["canvas"], "_ip_points", []) or [],
            view_mode=widgets["canvas"].get_view_mode(),
        )

    def _open_canvas_viewer(self, pipe_name):
        widgets = self._lookup_visual_widgets(pipe_name)
        if not widgets or widgets.get("canvas") is None:
            return
        canvas = widgets["canvas"]
        if not canvas.has_plan_data() and not canvas.has_profile_data():
            fluent_info(self, "预览", f"管道 '{self._resolve_pipe_label(pipe_name)}' 暂无可预览的数据")
            return
        viewer = self._ensure_canvas_viewer()
        self._sync_canvas_viewer(pipe_name)
        viewer.show_and_focus()

    def _on_viewer_mode_changed(self, mode):
        pipe_name = getattr(self, "_active_viewer_pipe_name", "")
        if pipe_name:
            self._set_card_view_mode(pipe_name, mode, sync_viewer=False)

    def _update_card_data_state(self, pipe_name, show_data=True):
        """切换卡片的纵断面数据显示状态（画布始终可见）"""
        w = self._lookup_visual_widgets(pipe_name)
        if not w or w.get('canvas') is None:
            return

        if show_data and pipe_name in self._longitudinal_data and self._longitudinal_data[pipe_name]:
            nodes = self._longitudinal_data[pipe_name]
            hint_text = self._stale_longitudinal_hint_texts.get(str(pipe_name or "").strip(), "")
            w['hint'].setText(self._build_xxpipe_route_hint_text(pipe_name, w, hint_text))
            w['hint'].setVisible(bool(hint_text))
            w['stats'].setText(self._compute_stats(nodes))
            w['stats'].setVisible(True)
            w['canvas'].set_nodes(nodes)
            w['expand_btn'].setText("▶ 查看详细节点数据")
            w['expand_btn'].setVisible(True)
            w['table'].setVisible(False)
            w['btn_clear'].setEnabled(True)
            w['btn_preview'].setEnabled(True)
            w['btn_view_profile'].setEnabled(True)
            self._refresh_long_table(pipe_name, w['table'])
            if pipe_name in self._route_widgets:
                self._set_route_missing_longitudinal_highlight(pipe_name, False)
        else:
            has_plan = w['canvas'].has_plan_data()
            show_hint = not has_plan
            if self._xxpipe_route_mode and pipe_name in self._route_widgets:
                show_hint = True
            hint_text = self._stale_longitudinal_hint_texts.get(str(pipe_name or "").strip(), "")
            w['hint'].setText(self._build_xxpipe_route_hint_text(pipe_name, w, hint_text))
            w['hint'].setVisible(show_hint)
            w['stats'].setVisible(False)
            w['expand_btn'].setVisible(False)
            w['table'].setVisible(False)
            w['table'].setRowCount(0)
            w['btn_clear'].setEnabled(False)
            w['btn_preview'].setEnabled(has_plan)
            w['btn_view_profile'].setEnabled(False)
            if w['canvas'].get_view_mode() == "profile":
                self._set_card_view_mode(pipe_name, "plan", sync_viewer=False)
            w['zoom_label'].setText(f"{w['canvas'].get_zoom_percent()}%")
            if pipe_name in self._route_widgets:
                self._set_route_missing_longitudinal_highlight(pipe_name, False)
        if self._active_viewer_pipe_name == pipe_name:
            self._sync_canvas_viewer(pipe_name)

    def _resolve_route_import_payload(self, pipe_name: str) -> Dict[str, Any]:
        """读取整线导入校验上下文。"""
        payload = self._route_import_targets.get(str(pipe_name or "").strip(), {})
        return payload if isinstance(payload, dict) else {}

    def _resolve_xxpipe_route_import_anchor_station(self, pipe_name: str, ip_points) -> float | None:
        """在起点夹带隧洞时，用首个非隧洞节点作为 DXF 对齐锚点。"""
        payload = self._resolve_route_import_payload(pipe_name)
        anchor_station = self._safe_float(payload.get("import_anchor_station_mc", None), None)
        if anchor_station is not None:
            return anchor_station

        route_nodes = list(payload.get("nodes", []) or [])
        first_target_index = next(
            (
                index
                for index, node in enumerate(route_nodes)
                if self._route_node_requires_import_coverage(node)
            ),
            None,
        )
        if first_target_index is not None:
            target_node = route_nodes[first_target_index]
            anchor_station = self._safe_float(
                getattr(target_node, "station_MC", getattr(target_node, "station_mc", None)),
                None,
            )
            if anchor_station is not None:
                return anchor_station

            try:
                from app_渠系计算前端.water_profile.cad_tools import (
                    resolve_xxpipe_profile_station_targets,
                )

                station_targets, _station_errors = resolve_xxpipe_profile_station_targets(
                    route_nodes,
                    station_prefix=str(payload.get("station_prefix", "") or ""),
                )
                if first_target_index < len(station_targets):
                    anchor_station = self._safe_float(
                        station_targets[first_target_index].get("station_mc", None),
                        None,
                    )
                    if anchor_station is not None:
                        return anchor_station
            except Exception:
                pass

        if ip_points:
            anchor_station = self._safe_float(
                ip_points[0].get("station_mc", ip_points[0].get("x", None)),
                None,
            )
        return anchor_station

    def _collect_xxpipe_route_import_anchor_candidates(self, pipe_name: str, ip_points) -> List[float]:
        """收集整线补导入可尝试的非隧洞起点锚点。"""
        payload = self._resolve_route_import_payload(pipe_name)
        route_nodes = list(payload.get("nodes", []) or [])
        anchors: List[float] = []
        inside_non_tunnel_segment = False

        for node in route_nodes:
            if getattr(node, "is_transition", False) or getattr(node, "is_auto_inserted_channel", False):
                continue
            if not self._route_node_requires_import_coverage(node):
                inside_non_tunnel_segment = False
                continue

            station_mc = self._safe_float(
                getattr(node, "station_MC", getattr(node, "station_mc", None)),
                None,
            )
            if station_mc is None:
                continue
            if not inside_non_tunnel_segment:
                anchors.append(float(station_mc))
            inside_non_tunnel_segment = True

        fallback_anchor = self._resolve_xxpipe_route_import_anchor_station(pipe_name, ip_points)
        if fallback_anchor is not None and not any(
            abs(float(item) - float(fallback_anchor)) <= 1e-6 for item in anchors
        ):
            anchors.insert(0, float(fallback_anchor))

        if not anchors and fallback_anchor is not None:
            anchors.append(float(fallback_anchor))
        return anchors

    def _pick_xxpipe_route_import_anchor(
        self,
        pipe_name: str,
        anchor_candidates: List[float],
        existing_nodes,
    ) -> float | None:
        """根据当前未覆盖的首个目标，优先选择最合理的补导入锚点。"""
        if not anchor_candidates:
            return None
        if not existing_nodes:
            return float(anchor_candidates[0])

        coverage_state = self._collect_xxpipe_route_import_coverage_state(pipe_name, existing_nodes)
        missing_targets = list(coverage_state.get("missing_targets", []) or [])
        first_missing_station = self._safe_float(
            missing_targets[0].get("station_mc", None),
            None,
        ) if missing_targets else None
        if first_missing_station is None:
            return float(anchor_candidates[0])

        preferred_before = [
            float(anchor)
            for anchor in anchor_candidates
            if float(anchor) <= float(first_missing_station) + 1e-6
        ]
        if preferred_before:
            return max(preferred_before)
        return min(anchor_candidates, key=lambda item: abs(float(item) - float(first_missing_station)))

    @staticmethod
    def _convert_imported_longitudinal_nodes(long_nodes) -> List[Dict[str, Any]]:
        """把解析器返回的纵断面节点统一转成字典列表。"""
        long_nodes_dict: List[Dict[str, Any]] = []
        for node in long_nodes or []:
            long_nodes_dict.append(
                {
                    "chainage": node.chainage,
                    "elevation": node.elevation,
                    "vertical_curve_radius": node.vertical_curve_radius,
                    "turn_type": node.turn_type.name if hasattr(node.turn_type, "name") else str(node.turn_type),
                    "turn_angle": node.turn_angle,
                    "slope_before": node.slope_before,
                    "slope_after": node.slope_after,
                    "arc_center_s": node.arc_center_s,
                    "arc_center_z": node.arc_center_z,
                    "arc_end_chainage": node.arc_end_chainage,
                    "arc_theta_rad": node.arc_theta_rad,
                }
            )
        return long_nodes_dict

    @staticmethod
    def _merge_longitudinal_nodes(existing_nodes, imported_nodes) -> List[Dict[str, Any]]:
        """按桩号合并多次导入的纵断面，后导入的同桩号节点覆盖旧节点。"""
        merged_map: Dict[float, Dict[str, Any]] = {}
        for nodes in (existing_nodes or [], imported_nodes or []):
            for raw in list(nodes or []):
                if not isinstance(raw, dict):
                    continue
                try:
                    chainage = float(raw.get("chainage"))
                except (TypeError, ValueError):
                    continue
                merged_map[round(chainage, 6)] = dict(raw)

        merged_nodes = list(merged_map.values())
        merged_nodes.sort(key=lambda item: float(item.get("chainage", 0.0) or 0.0))
        return merged_nodes

    @staticmethod
    def _read_imported_raw_profile_polyline(filepath: str, dxf_parser_cls, chainage_offset: float) -> Dict[str, Any]:
        """读取并标准化已套偏移的导入原线几何。"""
        from utils.pressure_pipe_longitudinal_utils import normalize_raw_profile_polyline

        get_raw_profile = getattr(dxf_parser_cls, "get_longitudinal_profile_raw_polyline", None)
        if not callable(get_raw_profile):
            return {}
        raw_profile_polyline, _error = get_raw_profile(
            filepath,
            chainage_offset=chainage_offset,
        )
        return normalize_raw_profile_polyline(raw_profile_polyline)

    @staticmethod
    def _merge_raw_profile_polylines(existing_raw_profile_polyline, imported_raw_profile_polyline) -> Dict[str, Any]:
        """按覆盖范围合并多次导入的原线几何。"""
        from utils.pressure_pipe_longitudinal_utils import merge_raw_profile_polylines

        return merge_raw_profile_polylines(existing_raw_profile_polyline, imported_raw_profile_polyline)

    @staticmethod
    def _read_longitudinal_profile_start_x(filepath: str, dxf_parser_cls) -> float:
        """读取纵断面图原始起点桩号，供自动对齐锚点使用。"""
        get_start_x = getattr(dxf_parser_cls, "get_longitudinal_profile_start_x", None)
        if callable(get_start_x):
            return float(get_start_x(filepath))

        import ezdxf

        doc = ezdxf.readfile(filepath)
        msp = doc.modelspace()
        polys = list(msp.query('LWPOLYLINE'))
        if not polys:
            polys = list(msp.query('POLYLINE'))
        if not polys:
            raise ValueError("DXF文件中未找到纵断面数据")

        polyline = polys[0]
        if hasattr(polyline, "get_points"):
            first_point = list(polyline.get_points(format='xyseb'))[0]
            return float(first_point[0])
        if hasattr(polyline, "vertices"):
            first_vertex = list(polyline.vertices)[0]
            return float(first_vertex.dxf.location.x)
        raise ValueError("错误：无法解析多段线顶点")

    def _resolve_xxpipe_route_import_result(self, pipe_name: str, filepath: str, dxf_parser_cls, ip_points):
        """为整线补导入选择最合适的锚点，并返回合并后的纵断面。"""
        existing_nodes = list(self._longitudinal_data.get(str(pipe_name or "").strip(), []) or [])
        existing_raw_profile_polyline = dict(
            self._raw_profile_polyline_data.get(str(pipe_name or "").strip(), {}) or {}
        )
        anchor_candidates = self._collect_xxpipe_route_import_anchor_candidates(pipe_name, ip_points)
        if not anchor_candidates:
            anchor_candidates = [0.0]
        preferred_anchor = self._pick_xxpipe_route_import_anchor(
            pipe_name,
            anchor_candidates,
            existing_nodes,
        )
        if preferred_anchor is None:
            preferred_anchor = float(anchor_candidates[0])

        x_start = self._read_longitudinal_profile_start_x(filepath, dxf_parser_cls)
        chainage_offset = float(preferred_anchor) - x_start
        long_nodes, message = dxf_parser_cls.parse_longitudinal_profile(
            filepath,
            chainage_offset=chainage_offset,
        )
        converted_nodes = self._convert_imported_longitudinal_nodes(long_nodes)
        merged_nodes = self._merge_longitudinal_nodes(existing_nodes, converted_nodes)
        imported_raw_profile_polyline = self._read_imported_raw_profile_polyline(
            filepath,
            dxf_parser_cls,
            chainage_offset,
        )
        merged_raw_profile_polyline = self._merge_raw_profile_polylines(
            existing_raw_profile_polyline,
            imported_raw_profile_polyline,
        )
        coverage_state = self._collect_xxpipe_route_import_coverage_state(pipe_name, merged_nodes)
        return {
            "anchor_station": float(preferred_anchor),
            "chainage_offset": chainage_offset,
            "message": str(message or "").strip(),
            "long_nodes": list(long_nodes or []),
            "merged_nodes": merged_nodes,
            "raw_profile_polyline": imported_raw_profile_polyline,
            "merged_raw_profile_polyline": merged_raw_profile_polyline,
            "coverage_state": coverage_state,
        }

    def _collect_xxpipe_route_import_coverage_state(self, pipe_name: str, longitudinal_nodes) -> Dict[str, Any]:
        """收集 xx管 整线纵断面覆盖情况，供导入校验和旧缓存识别共用。"""
        payload = self._resolve_route_import_payload(pipe_name)
        route_nodes = [
            node for node in list(payload.get("nodes", []) or [])
            if self._route_node_requires_import_coverage(node)
        ]
        station_prefix = str(payload.get("station_prefix", "") or "")
        display_name = str(payload.get("display_name", "") or self._resolve_pipe_label(pipe_name)).strip()
        if not route_nodes:
            return {
                "display_name": display_name,
                "station_errors": [],
                "missing_targets": [],
            }

        from app_渠系计算前端.water_profile.cad_tools import (
            _XXPIPE_PROFILE_STATION_TOL,
            resolve_xxpipe_profile_station_targets,
            sample_xxpipe_centerline_elevation,
        )

        station_targets, station_errors = resolve_xxpipe_profile_station_targets(
            route_nodes,
            station_prefix=station_prefix,
        )
        missing_targets = []
        for target in station_targets:
            station_mc = target.get("station_mc", None)
            if station_mc is None:
                continue
            try:
                sample_xxpipe_centerline_elevation(longitudinal_nodes, float(station_mc))
            except ValueError as exc:
                if "超出 xx管轴线高程覆盖范围" not in str(exc):
                    raise
                missing_targets.append(
                    {
                        "label": str(target.get("label", "-") or "-").strip(),
                        "station_text": str(target.get("station_text", "-") or "-").strip(),
                        "station_mc": float(station_mc),
                    }
                )

        coverage_start, coverage_end = self._extract_longitudinal_chainage_range(longitudinal_nodes)

        return {
            "display_name": display_name,
            "station_errors": list(station_errors or []),
            "missing_targets": missing_targets,
            "coverage_start": coverage_start,
            "coverage_end": coverage_end,
            "coverage_tol": float(_XXPIPE_PROFILE_STATION_TOL),
        }

    def _validate_xxpipe_route_import_coverage(self, pipe_name: str, longitudinal_nodes):
        """xx管 整线导入后立即校验导出节点桩号是否都被覆盖。"""
        coverage_state = self._collect_xxpipe_route_import_coverage_state(pipe_name, longitudinal_nodes)
        display_name = str(coverage_state.get("display_name", "") or self._resolve_pipe_label(pipe_name)).strip()
        station_errors = list(coverage_state.get("station_errors", []) or [])
        if station_errors:
            raise ValueError(
                f"{display_name} 缺少可用于导入校验的桩号信息：\n"
                + "；".join(
                    f"{item['label']}（{item['reason']}）"
                    for item in station_errors
                )
            )

        missing_targets = list(coverage_state.get("missing_targets", []) or [])
        if missing_targets:
            raise ValueError(
                self._build_xxpipe_import_coverage_error_message(display_name, coverage_state)
            )

    def _import_longitudinal_dxf(self, pipe_name, ip_points):
        """导入纵断面DXF"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        import os
        import sys
        pipe_label = self._resolve_pipe_label(pipe_name)
        card_key = str(pipe_name or "").strip()
        route_merge_mode = bool(self._xxpipe_route_mode and card_key in self._route_contexts)

        # 已有数据时弹出替换确认
        if (not route_merge_mode) and pipe_name in self._longitudinal_data and self._longitudinal_data[pipe_name]:
            if not fluent_question(self, "确认替换",
                                   "当前已有纵断面数据，导入DXF将替换现有数据。\n\n是否继续？"):
                return

        _siphon_dir = os.path.join(os.path.dirname(__file__), '..', '..', '倒虹吸水力计算系统')
        if _siphon_dir not in sys.path:
            sys.path.insert(0, _siphon_dir)

        try:
            from dxf_parser import DxfParser
        except ImportError:
            QMessageBox.warning(self, "导入失败", "DXF解析器未加载")
            return

        _res_dir = os.path.join(_siphon_dir, "resources")
        if not os.path.isdir(_res_dir):
            _res_dir = ""

        filepath, _ = QFileDialog.getOpenFileName(self, "选择纵断面DXF文件", _res_dir, "DXF文件 (*.dxf);;所有文件 (*.*)")
        if not filepath:
            return

        try:
            if not self._confirm_longitudinal_dxf_candidate_if_needed(pipe_name, filepath, DxfParser):
                return

            coverage_state = None
            merged_nodes = None
            if route_merge_mode:
                route_import_result = self._resolve_xxpipe_route_import_result(
                    pipe_name,
                    filepath,
                    DxfParser,
                    ip_points,
                )
                if not route_import_result:
                    QMessageBox.critical(self, "导入失败", "DXF文件中未找到纵断面数据")
                    return
                long_nodes = list(route_import_result.get("long_nodes", []) or [])
                message = str(route_import_result.get("message", "") or "").strip()
                merged_nodes = list(route_import_result.get("merged_nodes", []) or [])
                merged_raw_profile_polyline = dict(
                    route_import_result.get("merged_raw_profile_polyline", {}) or {}
                )
                coverage_state = dict(route_import_result.get("coverage_state", {}) or {})
            else:
                chainage_offset = 0.0
                if ip_points and len(ip_points) > 0:
                    x_start = self._read_longitudinal_profile_start_x(filepath, DxfParser)
                    mc_inlet = self._resolve_ip_point_chainage(ip_points[0], prefer_station=True)
                    if mc_inlet is None:
                        mc_inlet = self._safe_float(ip_points[0].get('x', 0.0), 0.0)
                    if self._xxpipe_route_mode:
                        resolved_anchor = self._resolve_xxpipe_route_import_anchor_station(
                            pipe_name,
                            ip_points,
                        )
                        if resolved_anchor is not None:
                            mc_inlet = resolved_anchor
                    chainage_offset = mc_inlet - x_start

                long_nodes, message = DxfParser.parse_longitudinal_profile(
                    filepath,
                    chainage_offset=chainage_offset,
                )
                raw_profile_polyline = self._read_imported_raw_profile_polyline(
                    filepath,
                    DxfParser,
                    chainage_offset,
                )

            if not long_nodes:
                QMessageBox.critical(self, "导入失败", message or "DXF文件中未找到纵断面数据")
                return

            self._raise_if_import_stays_in_raw_coordinate_space(
                pipe_label,
                ip_points,
                long_nodes,
            )

            if route_merge_mode:
                display_name = str(
                    (coverage_state or {}).get("display_name", "") or pipe_label
                ).strip()
                station_errors = list((coverage_state or {}).get("station_errors", []) or [])
                missing_targets = list((coverage_state or {}).get("missing_targets", []) or [])
                self._longitudinal_data[pipe_name] = list(merged_nodes or [])
                if merged_raw_profile_polyline:
                    self._raw_profile_polyline_data[pipe_name] = merged_raw_profile_polyline
                else:
                    self._raw_profile_polyline_data.pop(pipe_name, None)
                if station_errors or missing_targets:
                    self._stale_longitudinal_hint_texts[card_key] = self._build_xxpipe_incomplete_longitudinal_hint_text(
                        coverage_state,
                    )
                else:
                    self._stale_longitudinal_hint_texts.pop(card_key, None)
                self._persist_longitudinal_data_for_card(pipe_name)
                self._update_card_data_state(pipe_name, show_data=True)
                if station_errors or missing_targets:
                    fluent_info(
                        self,
                        "已导入一部分纵断面",
                        f"{display_name}\n{message}\n\n"
                        f"{self._build_xxpipe_import_coverage_error_message(display_name, coverage_state)}\n\n"
                        "可以继续导入剩余纵断面文件。",
                    )
                    return

                self._persist_longitudinal_data_for_card(pipe_name)
                fluent_info(
                    self,
                    "导入成功",
                    f"{display_name}\n{message}\n"
                    f"本次导入节点: {len(long_nodes)} 个，累计节点: {len(merged_nodes or [])} 个",
                )
                return

            long_nodes_dict = self._convert_imported_longitudinal_nodes(long_nodes)

            if not self._xxpipe_route_mode and ip_points and len(ip_points) >= 2:
                expected_range = self._resolve_ip_points_chainage_range(ip_points, prefer_station=True)
                if expected_range is None:
                    expected_range = self._resolve_ip_points_chainage_range(ip_points, prefer_station=False)
                ip_start, ip_end = expected_range if expected_range is not None else (0.0, 0.0)
                long_start = long_nodes[0].chainage
                long_end = long_nodes[-1].chainage

                warning_msg = ""
                if long_start > ip_start + 1.0:
                    warning_msg += f"纵断面起点桩号({long_start:.2f}m)晚于平面进口桩号({ip_start:.2f}m)\n"
                if long_end < ip_end - 1.0:
                    warning_msg += f"纵断面终点桩号({long_end:.2f}m)早于平面出口桩号({ip_end:.2f}m)\n"

                if warning_msg:
                    warning_msg += "\n超出纵断面范围的部分将按平面数据处理。\n是否继续？"
                    if not fluent_question(self, "桩号范围警告", warning_msg):
                        self._update_card_data_state(pipe_name, show_data=False)
                        return

            self._longitudinal_data[pipe_name] = long_nodes_dict
            if raw_profile_polyline:
                self._raw_profile_polyline_data[pipe_name] = raw_profile_polyline
            else:
                self._raw_profile_polyline_data.pop(pipe_name, None)
            self._stale_longitudinal_hint_texts.pop(card_key, None)
            self._persist_longitudinal_data_for_card(pipe_name)
            self._update_card_data_state(pipe_name, show_data=True)
            fluent_info(self, "导入成功", f"{pipe_label}\n{message}\n变坡点节点: {len(long_nodes)} 个")

        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def _confirm_longitudinal_dxf_candidate_if_needed(self, pipe_name, filepath, dxf_parser_cls):
        """当候选过于接近时，先让用户确认是否按推荐项继续导入。"""
        if not hasattr(dxf_parser_cls, "inspect_longitudinal_profile_candidates"):
            return True

        selection, error = dxf_parser_cls.inspect_longitudinal_profile_candidates(filepath)
        if error:
            raise ValueError(error)
        if not selection or not selection.get("needs_confirmation"):
            return True

        candidates = list(selection.get("candidates", []) or [])
        if len(candidates) < 2:
            return True

        first = candidates[0]
        second = candidates[1]
        pipe_label = self._resolve_pipe_label(pipe_name)

        def _format_candidate(candidate):
            """格式化候选摘要文本。"""
            layer_name = str(candidate.get("layer", "") or "未分层")
            x_span = float(candidate.get("x_span", 0.0) or 0.0)
            path_length = float(candidate.get("path_length", 0.0) or 0.0)
            return f"图层={layer_name}，X跨度={x_span:.3f}m，路径长={path_length:.3f}m"

        message = (
            f"{pipe_label}\n"
            "检测到两个很接近的纵断面候选，系统准备按推荐候选继续导入。\n\n"
            f"推荐候选：{_format_candidate(first)}\n"
            f"备选候选：{_format_candidate(second)}\n\n"
            "如果这两条线看起来都像纵断面，请先核对推荐候选是否正确。\n"
            "是否继续按推荐候选导入？"
        )
        return fluent_question(self, "纵断面候选确认", message)

    def _clear_longitudinal(self, pipe_name):
        """清空纵断面数据"""
        if pipe_name not in self._longitudinal_data and pipe_name not in self._raw_profile_polyline_data:
            return

        if not fluent_question(self, "确认清空", f"确定要清空管道 '{self._resolve_pipe_label(pipe_name)}' 的纵断面数据吗？"):
            return

        self._longitudinal_data.pop(pipe_name, None)
        self._raw_profile_polyline_data.pop(pipe_name, None)
        self._stale_longitudinal_hint_texts.pop(str(pipe_name or "").strip(), None)
        self._persist_longitudinal_data_for_card(pipe_name)
        self._update_card_data_state(pipe_name, show_data=False)

    def _persist_longitudinal_data_for_card(self, pipe_name):
        """把当前卡片的纵断面数据即时同步到持久层。"""
        if not self._manager:
            return

        card_key = str(pipe_name or "").strip()
        nodes_payload = list(self._longitudinal_data.get(card_key, []) or [])
        raw_profile_polyline_payload = dict(self._raw_profile_polyline_data.get(card_key, {}) or {})
        route_context = self._route_contexts.get(card_key, {})
        set_route_longitudinal_nodes = getattr(self._manager, "set_route_longitudinal_nodes", None)
        if isinstance(route_context, dict) and callable(set_route_longitudinal_nodes):
            set_route_longitudinal_nodes(
                card_key,
                nodes_payload,
                str(route_context.get("display_name", "") or card_key).strip(),
                raw_profile_polyline=raw_profile_polyline_payload,
            )
            for group in list(route_context.get("groups", []) or []):
                self._persist_longitudinal_data_for_group(group, nodes_payload, raw_profile_polyline_payload)
            return

        group = None
        for item in self._pipe_groups or []:
            if self._group_storage_key(item) == card_key:
                group = item
                break
        if group is None:
            return

        self._persist_longitudinal_data_for_group(group, nodes_payload, raw_profile_polyline_payload)

    def _persist_longitudinal_data_for_group(self, group, nodes_payload, raw_profile_polyline_payload=None):
        """把整线或分段纵断面同步回对应子段配置，避免再次回读旧缓存。"""
        if not self._manager:
            return

        try:
            from managers.pressure_pipe_manager import PressurePipeConfig
        except Exception:
            return

        group_key = self._group_storage_key(group)
        cfg = self._get_manager_group_config(group)
        if cfg is None:
            cfg = PressurePipeConfig()
            cfg.name = self._group_display_name(group)
            cfg.Q = float(getattr(group, "design_flow", 0.0) or 0.0)
            cfg.D = float(getattr(group, "diameter", 0.0) or 0.0)
            cfg.material_key = str(getattr(group, "material_key", "") or "")
            cfg.ip_points = list(getattr(group, "ip_points", []) or [])

        cfg.route_key = self._group_route_key(group)
        cfg.route_display_name = self._group_route_display_name(group)
        cfg.longitudinal_nodes = list(nodes_payload or [])
        cfg.raw_profile_polyline = dict(raw_profile_polyline_payload or {})
        self._manager.set_pipe_config(group_key, cfg)

    def _preview_longitudinal(self, pipe_name):
        """弹出管道预览对话框（含纵断面+平面图双视图）"""
        self._open_canvas_viewer(pipe_name)

    def closeEvent(self, event):
        viewer = getattr(self, "_canvas_viewer", None)
        if viewer is not None:
            viewer.close()
            self._canvas_viewer = None
            self._active_viewer_pipe_name = ""
        super().closeEvent(event)

    def _refresh_long_table(self, pipe_name, table):
        """刷新纵断面节点表（优化显示格式）"""
        if pipe_name not in self._longitudinal_data:
            return

        nodes = self._longitudinal_data[pipe_name]
        table.setRowCount(len(nodes))

        for i, node in enumerate(nodes):
            table.setItem(i, 0, QTableWidgetItem(f"{node['chainage']:.2f}"))
            table.setItem(i, 1, QTableWidgetItem(f"{node['elevation']:.3f}"))

            r = node.get('vertical_curve_radius', 0.0)
            table.setItem(i, 2, QTableWidgetItem(f"{r:.2f}" if r != 0 else "-"))

            tt_raw = node.get('turn_type', 'NONE')
            tt_cn = _TURN_TYPE_CN.get(tt_raw, tt_raw)
            table.setItem(i, 3, QTableWidgetItem(tt_cn))

            angle = node.get('turn_angle', 0.0)
            table.setItem(i, 4, QTableWidgetItem(f"{angle:.1f}\u00b0" if angle != 0 else "-"))

    def get_longitudinal_nodes_dict(self):
        """获取所有管道的纵断面数据字典"""
        return self._longitudinal_data.copy()

    def get_raw_profile_polyline_dict(self):
        """获取所有管道的导入原线几何字典。"""
        return copy.deepcopy(self._raw_profile_polyline_data)


class BuildingLengthDialog(QDialog):
    """
    建筑物长度统计对话框（PySide6版）

    以表格形式展示各建筑物的长度详情和按结构类型汇总，
    支持复制到剪贴板和复制排版格式。
    """

    # 统一样式常量
    _TABLE_FONT = "Microsoft YaHei"
    _TABLE_FONT_SIZE = 10
    _ROW_HEIGHT = 32
    _HEADER_STYLE = (
        "QHeaderView::section {"
        "  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #F0F4FA, stop:1 #E2E8F0);"
        "  color: #1A2942;"
        "  font-weight: bold;"
        "  font-size: 10pt;"
        "  padding: 6px 10px;"
        "  border: none;"
        "  border-bottom: 2px solid #CBD5E1;"
        "  border-right: 1px solid #E2E8F0;"
        "}"
    )
    _TABLE_STYLE = (
        "QTableWidget {"
        "  gridline-color: #E8ECF1;"
        "  border: 1px solid #D1D9E6;"
        "  border-radius: 6px;"
        "  selection-background-color: #DBEAFE;"
        "  selection-color: #1E3A5F;"
        "}"
        "QTableWidget::item {"
        "  padding: 4px 8px;"
        "}"
        "QTableWidget::item:alternate {"
        "  background: #F8FAFC;"
        "}"
    )

    def __init__(self, parent, building_lengths: List[Dict[str, Any]],
                 channel_total_length: float = 0.0,
                 type_summary: List[Dict[str, Any]] = None,
                 station_prefix: str = ""):
        super().__init__(parent)
        self.building_lengths = building_lengths or []
        self.channel_total_length = channel_total_length
        self._type_summary = type_summary
        self._station_prefix = station_prefix

        self.setWindowTitle("建筑物长度统计")
        self.setMinimumSize(500, 350)
        self._create_ui()
        self._load_data()
        self._auto_resize_dialog()

    def _setup_table(self, table: QTableWidget):
        """统一设置表格样式"""
        table.setFont(QFont(self._TABLE_FONT, self._TABLE_FONT_SIZE))
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(self._ROW_HEIGHT)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setShowGrid(True)
        table.setStyleSheet(self._TABLE_STYLE)
        table.horizontalHeader().setStyleSheet(self._HEADER_STYLE)
        table.horizontalHeader().setMinimumHeight(36)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

    def _create_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        # ---- QTabWidget：明细 / 汇总 两个Tab页 ----
        self.tab_widget = QTabWidget()
        self.tab_widget.setFont(QFont(self._TABLE_FONT, 10))
        self.tab_widget.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #D1D9E6; border-radius: 6px; "
            "  background: white; padding: 6px; }"
            "QTabBar::tab { padding: 8px 20px; font-size: 10pt; font-weight: bold; "
            "  border: 1px solid #D1D9E6; border-bottom: none; border-radius: 6px 6px 0 0; "
            "  margin-right: 2px; background: #F0F4FA; color: #4A5568; }"
            "QTabBar::tab:selected { background: white; color: #1A56DB; "
            "  border-bottom: 2px solid #1A56DB; }"
            "QTabBar::tab:hover:!selected { background: #E8ECF1; }"
        )

        # ---- Tab1：建筑物长度明细 ----
        tab_detail = QWidget()
        detail_lay = QVBoxLayout(tab_detail)
        detail_lay.setContentsMargins(6, 8, 6, 6)
        detail_lay.setSpacing(6)
        self.detail_table = QTableWidget()
        detail_headers = ["序号", "建筑物名称", "结构形式", "长度(m)", "起始桩号(m)", "终止桩号(m)", "备注"]
        self.detail_table.setColumnCount(len(detail_headers))
        self.detail_table.setHorizontalHeaderLabels(detail_headers)
        self._setup_table(self.detail_table)
        detail_lay.addWidget(self.detail_table, stretch=1)

        self.lbl_total = QLabel()
        self.lbl_total.setStyleSheet(
            "font-size: 10pt; color: #1E3A5F; font-weight: bold; padding: 4px 2px;"
        )
        detail_lay.addWidget(self.lbl_total)
        lbl_basis = QLabel("统计口径：按桩号差统计；渐变段单列；自动插入明渠计入对应类型")
        lbl_basis.setStyleSheet("color: #4A5568; font-size: 9pt; padding-left: 2px;")
        detail_lay.addWidget(lbl_basis)
        self.tab_widget.addTab(tab_detail, "建筑物长度明细")

        # ---- Tab2：按结构类型汇总 ----
        tab_summary = QWidget()
        summary_lay = QVBoxLayout(tab_summary)
        summary_lay.setContentsMargins(6, 8, 6, 6)
        summary_lay.setSpacing(6)
        self.summary_table = QTableWidget()
        summary_headers = ["序号", "结构类型", "数量", "累计长度(m)"]
        self.summary_table.setColumnCount(len(summary_headers))
        self.summary_table.setHorizontalHeaderLabels(summary_headers)
        self._setup_table(self.summary_table)
        summary_lay.addWidget(self.summary_table, stretch=1)
        self.tab_widget.addTab(tab_summary, "按结构类型汇总")

        lay.addWidget(self.tab_widget, stretch=1)

        # 按钮区
        btn_lay = QHBoxLayout()
        btn_lay.setContentsMargins(0, 4, 0, 0)
        btn_copy = PushButton("复制到剪贴板")
        btn_copy.clicked.connect(self._copy_to_clipboard)
        btn_format = PushButton("排版表预览(Excel)")
        btn_format.setToolTip(
            "将建筑物明细重新排版为左右对照表格（左侧为各建筑物进出口桩号及长度，\n"
            "右侧为各结构类型汇总长度），可直接复制粘贴到 Excel 中，\n"
            "用于填写渠道特性统计表和分段土石方汇总表。"
        )
        btn_format.clicked.connect(self._copy_formatted)
        btn_close = PushButton("关闭")
        btn_close.clicked.connect(self.accept)
        btn_lay.addWidget(btn_copy)
        btn_lay.addWidget(btn_format)
        btn_lay.addStretch()
        btn_lay.addWidget(btn_close)
        lay.addLayout(btn_lay)

    @staticmethod
    def _is_building_type(structure_type: str) -> bool:
        """判断结构类型是否为建筑物（渡槽/隧洞/暗涵/倒虹吸）"""
        return any(kw in structure_type for kw in ('渡槽', '隧洞', '暗涵', '倒虹吸'))

    def _load_data(self):
        """加载明细和汇总数据到表格"""
        total_length = 0.0

        # 明细表
        self.detail_table.setRowCount(len(self.building_lengths))
        for i, item in enumerate(self.building_lengths):
            length = item.get('length', 0.0)
            total_length += length
            # 非建筑物类型（渡槽/隧洞/倒虹吸以外）名称显示为"-"
            name = item.get('name', '')
            st = item.get('structure_type', '')
            display_name = name if self._is_building_type(st) else '-'
            vals = [
                str(i + 1),
                display_name,
                st,
                f"{length:.3f}",
                f"{item.get('start_station', 0.0):.3f}",
                f"{item.get('end_station', 0.0):.3f}",
                item.get('note', ''),
            ]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                cell.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                self.detail_table.setItem(i, c, cell)

        # 合计 + 校验
        count = len(self.building_lengths)
        diff = abs(total_length - self.channel_total_length)
        if self.channel_total_length > 0 and diff < 0.001:
            verify = f"  (桩号总长: {self.channel_total_length:.3f} m, 校验通过)"
        elif self.channel_total_length > 0:
            verify = f"  (桩号总长: {self.channel_total_length:.3f} m, 差值: {diff:.3f} m)"
        else:
            verify = ""
        self.lbl_total.setText(f"合计: {count} 个段落,  总长度: {total_length:.3f} m{verify}")

        # 汇总表
        if self._type_summary is None:
            self._type_summary = self._calc_type_summary()

        n = len(self._type_summary)
        self.summary_table.setRowCount(n + 1)  # 多一行合计
        total_count = 0
        total_len_sum = 0.0
        for i, item in enumerate(self._type_summary):
            cnt = item['count']
            tl = item['total_length']
            total_count += cnt
            total_len_sum += tl
            vals = [
                str(i + 1),
                item['structure_type'],
                str(cnt),
                f"{tl:.3f}",
            ]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                cell.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                self.summary_table.setItem(i, c, cell)

        # 合计行
        sum_vals = ["", "合计", str(total_count), f"{total_len_sum:.3f}"]
        bold_font = QFont(self._TABLE_FONT, self._TABLE_FONT_SIZE)
        bold_font.setBold(True)
        for c, v in enumerate(sum_vals):
            cell = QTableWidgetItem(v)
            cell.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            cell.setFont(bold_font)
            self.summary_table.setItem(n, c, cell)

    def _auto_resize_dialog(self):
        """根据两个表格内容自动调整窗口大小"""
        # 先让表格根据内容调整列宽
        self.detail_table.resizeColumnsToContents()
        self.summary_table.resizeColumnsToContents()

        # 为每列增加适当内边距（左右各12px）
        for table in (self.detail_table, self.summary_table):
            header = table.horizontalHeader()
            for c in range(header.count()):
                cur_w = header.sectionSize(c)
                table.setColumnWidth(c, cur_w + 24)

        # 计算明细表所需宽度（含对话框边距24 + Tab内边距12 + 面板padding12 + 竖滚动条17 + 余量）
        extra = 80
        detail_w = sum(
            self.detail_table.columnWidth(c)
            for c in range(self.detail_table.columnCount())
        ) + extra

        # 计算汇总表所需宽度
        summary_w = sum(
            self.summary_table.columnWidth(c)
            for c in range(self.summary_table.columnCount())
        ) + extra

        # 取两个表格宽度的最大值作为窗口宽度
        content_w = max(detail_w, summary_w)

        # 计算明细表所需高度
        detail_rows = self.detail_table.rowCount()
        summary_rows = self.summary_table.rowCount()
        max_rows = max(detail_rows, summary_rows)
        table_h = 36 + max_rows * self._ROW_HEIGHT + 4  # 表头 + 数据行
        fixed_h = 130  # Tab栏 + 合计标签 + 按钮 + 边距
        content_h = table_h + fixed_h

        # 限制最大尺寸为屏幕的 85%/70%
        screen = self.screen()
        if screen:
            sg = screen.availableGeometry()
            max_w = int(sg.width() * 0.85)
            max_h = int(sg.height() * 0.70)
        else:
            max_w, max_h = 1400, 750

        win_w = min(max(content_w, 500), max_w)
        win_h = min(max(content_h, 350), max_h)
        self.resize(win_w, win_h)

        # 窗口大小确定后，启用最后一列拉伸填充多余空间
        self.detail_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.horizontalHeader().setStretchLastSection(True)

    def _calc_type_summary(self):
        """按结构类型汇总累计长度（用唯一名称计数，被分水闸拆分的同名隧洞只算1个）"""
        type_map = {}
        for item in self.building_lengths:
            st = item.get('structure_type', '')
            name = item.get('name', '')
            if not st or '连接' in name:
                continue
            length = item.get('length', 0.0)
            if st not in type_map:
                type_map[st] = {'names': set(), 'total_length': 0.0}
            type_map[st]['names'].add(name)
            type_map[st]['total_length'] += length
        return [
            {'structure_type': k, 'count': len(v['names']), 'total_length': v['total_length']}
            for k, v in sorted(type_map.items())
        ]

    def _copy_to_clipboard(self):
        """复制到剪贴板（制表符分隔，含明细和汇总）"""
        lines = ["【建筑物长度明细】"]
        lines.append("序号\t建筑物名称\t结构形式\t长度(m)\t起始桩号(m)\t终止桩号(m)\t备注")
        for i in range(self.detail_table.rowCount()):
            row = []
            for c in range(self.detail_table.columnCount()):
                item = self.detail_table.item(i, c)
                row.append(item.text() if item else "")
            lines.append("\t".join(row))
        total_length = sum(item.get('length', 0.0) for item in self.building_lengths)
        lines.append(f"合计\t{len(self.building_lengths)} 个段落\t\t{total_length:.3f}\t\t\t")
        lines.append("")
        lines.append("【按结构类型汇总】")
        lines.append("序号\t结构类型\t数量\t累计长度(m)")
        for i in range(self.summary_table.rowCount()):
            row = []
            for c in range(self.summary_table.columnCount()):
                item = self.summary_table.item(i, c)
                row.append(item.text() if item else "")
            lines.append("\t".join(row))

        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(lines))
        fluent_info(self, "提示", "已复制到剪贴板（含明细和汇总）")

    def _copy_formatted(self):
        """打开排版格式预览对话框"""
        type_summary = self._type_summary if self._type_summary is not None else self._calc_type_summary()
        try:
            dlg = FormattedLayoutDialog(
                self, self.building_lengths, type_summary,
                station_prefix=self._station_prefix
            )
            dlg.exec()
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            traceback.print_exc()
            fluent_error(self, "错误", f"打开排版格式预览失败：\n{tb_str}")

    @staticmethod
    def _format_station(value, prefix=""):
        """格式化桩号显示"""
        km = int(value // 1000)
        remainder = value - km * 1000
        s = f"{km}+{remainder:07.3f}"
        return f"{prefix}{s}" if prefix else s


# ============================================================
# 排版格式预览对话框
# ============================================================
class FormattedLayoutDialog(QDialog):
    """
    排版格式预览对话框（PySide6版）

    以表格形式展示可直接复制粘贴到 Excel 的工程排版格式，
    左侧为建筑物明细（名称、进出口桩号、长度），
    右侧为各结构类型汇总长度。
    """

    def __init__(self, parent, building_lengths: List[Dict[str, Any]],
                 type_summary: List[Dict[str, Any]],
                 station_prefix: str = ""):
        super().__init__(parent)
        self._building_lengths = building_lengths or []
        self._type_summary = type_summary or []
        self._station_prefix = station_prefix

        self.setWindowTitle("排版格式预览")
        self.setMinimumSize(700, 400)

        # 预先生成数据（供 UI 和复制共用）
        self._headers, self._table_data = self._build_table_data()

        self._create_ui()
        self._auto_resize()

    def _build_table_data(self):
        """
        构建表格数据（表头 + 二维数据）

        布局：左侧4列为建筑物明细，右侧2列为结构类型汇总。
        分水闸/分水口不参与统计，从明细和汇总中均排除。
        """
        prefix = self._station_prefix

        # 过滤明细数据：排除分水闸/分水口和渐变段
        detail_items = [
            item for item in self._building_lengths
            if '分水' not in item.get('structure_type', '')
            and item.get('structure_type', '') != '渐变段'
        ]

        # 构建右侧汇总行：排除分水闸/分水口，含末行"总长度"
        summary_rows = []
        for item in self._type_summary:
            if '分水' in item.get('structure_type', ''):
                continue
            summary_rows.append({
                'label': item['structure_type'],
                'length': item['total_length'],
            })
        # 添加"总长度"汇总行
        total_all = sum(item.get('total_length', 0.0) for item in self._type_summary)
        summary_rows.append({
            'label': '总长度',
            'length': total_all,
        })

        headers = ["建筑物名称", "进口桩号", "出口桩号", "长度", "各建筑物总长度", "长度（m）"]

        # 确定总行数（左右取最大值）
        detail_count = len(detail_items)
        summary_count = len(summary_rows)
        max_rows = max(detail_count, summary_count)

        data = []
        for i in range(max_rows):
            # 左侧：建筑物明细
            if i < detail_count:
                item = detail_items[i]
                raw_name = item.get('name', '')
                struct_type = item.get('structure_type', '')
                if '连接' in raw_name:
                    name = struct_type or raw_name
                else:
                    name = f"{raw_name}{struct_type}" if struct_type else raw_name
                start_station = self._format_station(
                    item.get('start_station', 0.0), prefix)
                end_station = self._format_station(
                    item.get('end_station', 0.0), prefix)
                length = f"{item.get('length', 0.0):.3f}"
            else:
                name = ""
                start_station = ""
                end_station = ""
                length = ""

            # 右侧：结构类型汇总
            if i < summary_count:
                s = summary_rows[i]
                s_label = s['label']
                s_length = f"{s['length']:.3f}"
            else:
                s_label = ""
                s_length = ""

            data.append([name, start_station, end_station, length, s_label, s_length])

        return headers, data

    def _create_ui(self):
        """创建预览界面"""
        lay = QVBoxLayout(self)
        lay.setSpacing(6)

        # 说明标签
        hint_label = QLabel(
            "以下内容为制表符分隔格式，可直接复制粘贴到 Excel 中使用。\n"
            "用于渠道特性统计表和分段土石方汇总表。"
        )
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("color: black; font-size: 13px;")
        lay.addWidget(hint_label)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(len(self._headers))
        self.table.setHorizontalHeaderLabels(self._headers)
        self.table.setRowCount(len(self._table_data))
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setSelectionMode(QAbstractItemView.ContiguousSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFont(QFont("Microsoft YaHei", 10))
        self.table.verticalHeader().setDefaultSectionSize(28)

        # 右侧汇总列浅蓝底色
        summary_bg = QColor("#EDF4FC")
        total_bg = QColor("#D6E8F7")

        # 计算"总长度"行索引
        summary_count = len([
            item for item in self._type_summary
            if '分水' not in item.get('structure_type', '')
        ]) + 1  # +1 for "总长度" row
        total_row_idx = summary_count - 1

        for r, row_data in enumerate(self._table_data):
            for c, val in enumerate(row_data):
                cell = QTableWidgetItem(str(val))
                # 数值列居中
                if c in (2, 3, 5):
                    cell.setTextAlignment(Qt.AlignCenter)
                elif c == 1:
                    cell.setTextAlignment(Qt.AlignCenter)
                else:
                    cell.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)

                # 右侧汇总列设置背景色
                if c >= 4:
                    if r == total_row_idx:
                        cell.setBackground(total_bg)
                    else:
                        cell.setBackground(summary_bg)

                self.table.setItem(r, c, cell)

        lay.addWidget(self.table, stretch=1)

        # 按钮区
        btn_lay = QHBoxLayout()
        btn_copy = PushButton("复制到剪贴板")
        btn_copy.clicked.connect(self._copy_to_clipboard)
        btn_close = PushButton("关闭")
        btn_close.clicked.connect(self.accept)
        btn_lay.addWidget(btn_copy)
        btn_lay.addStretch()
        btn_lay.addWidget(btn_close)
        lay.addLayout(btn_lay)

    def _auto_resize(self):
        """根据内容自动调整列宽和窗口大小"""
        auto_resize_table(self.table)

        # 计算所需宽度
        total_w = 0
        for c in range(self.table.columnCount()):
            total_w += self.table.columnWidth(c)
        # 加上行号列、滚动条和边距
        total_w += self.table.verticalHeader().width() + 50

        # 计算所需高度
        row_count = self.table.rowCount()
        row_h = self.table.verticalHeader().defaultSectionSize()
        header_h = self.table.horizontalHeader().height()
        table_h = header_h + row_count * row_h + 4
        fixed_h = 120  # 说明标签 + 按钮 + 边距
        total_h = table_h + fixed_h

        # 限制最大尺寸为屏幕的 85%
        screen = self.screen()
        if screen:
            sg = screen.availableGeometry()
            max_w = int(sg.width() * 0.85)
            max_h = int(sg.height() * 0.65)
        else:
            max_w, max_h = 1400, 700

        win_w = min(max(total_w, 700), max_w)
        win_h = min(max(total_h, 400), max_h)
        self.resize(win_w, win_h)

    def _generate_tsv_text(self) -> str:
        """从表头和数据生成制表符分隔文本"""
        lines = ["\t".join(self._headers)]
        for row in self._table_data:
            lines.append("\t".join(str(cell) for cell in row))
        return "\n".join(lines)

    def _copy_to_clipboard(self):
        """将排版文本复制到剪贴板（制表符分隔格式）"""
        text = self._generate_tsv_text()
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        fluent_info(self, "提示", "排版格式已复制到剪贴板，可直接粘贴到 Excel")

    @staticmethod
    def _format_station(value, prefix=""):
        """格式化桩号显示"""
        km = int(value // 1000)
        remainder = value - km * 1000
        s = f"{km}+{remainder:07.3f}"
        return f"{prefix}{s}" if prefix else s


# ============================================================
# 批量补段插入确认对话框
# ============================================================
class BatchChannelConfirmDialog(QDialog):
    """
    批量补段插入确认对话框（PySide6版）

    展示所有需要插入补段的位置，提供表格编辑和逐一确认两种模式。
    """

    RESULT_TABLE_EDIT = "table_edit"
    RESULT_MANUAL_EACH = "manual_each"
    RESULT_CANCELLED = "cancelled"

    STRUCTURE_TYPES = TRANSITION_FILLER_TYPES
    MANUAL_STRUCTURE_TYPES = MANUAL_TRANSITION_FILLER_TYPES

    @classmethod
    def _build_structure_type_options(cls, allow_arch_culvert_source: bool = False):
        """按来源限制补段结构形式选项。"""
        options = list(cls.MANUAL_STRUCTURE_TYPES)
        if allow_arch_culvert_source and "暗涵-圆拱直墙型" not in options:
            options.append("暗涵-圆拱直墙型")
        return options

    @staticmethod
    def _set_combo_items(combo, options, current_text=""):
        """刷新下拉选项，并尽量保留当前值。"""
        target_text = str(current_text or "").strip()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(list(options))
        if target_text:
            target_index = combo.findText(target_text)
            if target_index >= 0:
                combo.setCurrentIndex(target_index)
        combo.blockSignals(False)

    @classmethod
    def _gap_allows_arch_culvert_source(cls, gap: Dict[str, Any]) -> bool:
        """仅在带入链路已明确是圆拱直墙型时，保留该选项。"""
        reference = gap.get("reference_segment") or gap.get("upstream_channel") or {}
        structure_type = normalize_transition_structure_type(reference.get("structure_type", ""))
        return structure_type == "暗涵-圆拱直墙型"

    def __init__(self, parent, total_count: int, gaps_info: list):
        super().__init__(parent)
        self.total_count = total_count
        self.gaps_info = gaps_info
        self.result = {'mode': self.RESULT_MANUAL_EACH, 'params': {}}
        self._row_widgets = []
        self._param_undo_stack = []
        self._param_redo_stack = []
        self._param_undo_group = 0
        self._param_pre_edit_snapshot = None

        self.setWindowTitle("批量插入补段")
        self.resize(1280, 580)
        self.setMinimumSize(1040, 400)
        self._create_ui()
        self._fill_all_recommended()

    def _create_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(6)

        # 标题 & 统计
        has_reference = sum(1 for g in self.gaps_info if g.get('has_reference'))
        missing_reference = self.total_count - has_reference

        lbl_title = QLabel(f"系统检测到 <b>{self.total_count}</b> 处需要插入补段")
        lay.addWidget(lbl_title)

        if has_reference == self.total_count:
            lbl_sub = QLabel(f"全部 {self.total_count} 处均可自动匹配补段参数")
            lbl_sub.setStyleSheet("color: green;")
        else:
            lbl_sub = QLabel(f"其中 {has_reference} 处可自动匹配参数，{missing_reference} 处需手动输入")
            lbl_sub.setStyleSheet("color: #CC6600;")
        lay.addWidget(lbl_sub)

        # 原理说明
        tip_grp = QGroupBox("为什么需要插入补段？")
        tip_lay = QVBoxLayout(tip_grp)
        tip_text = (
            "渠系中各建筑物之间往往存在无建筑物覆盖的空余渠段。"
            "系统通过比较相邻建筑物间的里程差与渐变段长度之和，自动检测出这些空隙位置。\n"
            "为保证水面线推算的连续性，需要在空隙处补充补段。"
            "推荐直接复制系统找到的参考补段断面参数，也可手动修改。"
        )
        lbl_tip = QLabel(tip_text)
        lbl_tip.setWordWrap(True)
        lbl_tip.setStyleSheet("color: #0055AA;")
        tip_lay.addWidget(lbl_tip)
        lay.addWidget(tip_grp)

        # 模式选择
        mode_lay = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.rb_table = QRadioButton("在下方表格中统一编辑（推荐）")
        self.rb_manual = QRadioButton("逐一弹窗确认")
        self.rb_table.setChecked(True)
        self.mode_group.addButton(self.rb_table)
        self.mode_group.addButton(self.rb_manual)
        self.rb_table.toggled.connect(self._on_mode_change)
        mode_lay.addWidget(self.rb_table)
        mode_lay.addWidget(self.rb_manual)
        mode_lay.addStretch()
        lay.addLayout(mode_lay)

        # 工具栏
        tb = QHBoxLayout()
        self._fill_btn = PushButton("全部填充推荐参数")
        self._fill_btn.clicked.connect(self._fill_all_recommended)
        self._clear_btn = PushButton("全部清空")
        self._clear_btn.clicked.connect(self._clear_all)
        tb.addWidget(self._fill_btn)
        tb.addWidget(self._clear_btn)
        tb.addStretch()
        lay.addLayout(tb)

        # 参数表格
        self.param_table = QTableWidget(self.total_count, 12)
        headers = ["#", "上游", "下游", "可用长度(m)", "结构形式", "B(m)", "H(m)", "m", "n", "底坡1/i", "Q(m3/s)", "状态/来源"]
        self.param_table.setHorizontalHeaderLabels(headers)
        self.param_table.horizontalHeader().setStretchLastSection(False)
        self.param_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.param_table.setFont(QFont("Microsoft YaHei", 10))
        self.param_table.verticalHeader().setVisible(False)
        self.param_table.setAlternatingRowColors(True)

        self._row_widgets = []
        for idx, gap in enumerate(self.gaps_info):
            # # 列
            item_idx = QTableWidgetItem(str(idx + 1))
            item_idx.setFlags(item_idx.flags() & ~Qt.ItemIsEditable)
            item_idx.setTextAlignment(Qt.AlignCenter)
            self.param_table.setItem(idx, 0, item_idx)

            # 上游列：名称(结构形式)
            prev_name = gap.get('prev_name', '')
            prev_struct = gap.get('prev_struct', '')
            prev_text = f"{prev_name}({prev_struct})" if prev_name else prev_struct
            item_prev = QTableWidgetItem(prev_text)
            item_prev.setFlags(item_prev.flags() & ~Qt.ItemIsEditable)
            item_prev.setToolTip(prev_text)
            self.param_table.setItem(idx, 1, item_prev)

            # 下游列：名称(结构形式)
            next_name = gap.get('next_name', '')
            next_struct = gap.get('next_struct', '')
            next_text = f"{next_name}({next_struct})" if next_name else next_struct
            item_next = QTableWidgetItem(next_text)
            item_next.setFlags(item_next.flags() & ~Qt.ItemIsEditable)
            item_next.setToolTip(next_text)
            self.param_table.setItem(idx, 2, item_next)

            # 可用长度列
            item_len = QTableWidgetItem(f"{gap['available_length']:.1f}")
            item_len.setFlags(item_len.flags() & ~Qt.ItemIsEditable)
            item_len.setTextAlignment(Qt.AlignCenter)
            self.param_table.setItem(idx, 3, item_len)

            # 结构形式 ComboBox
            type_cb = QComboBox()
            allow_arch_culvert_source = self._gap_allows_arch_culvert_source(gap)
            type_cb.addItems(self._build_structure_type_options(allow_arch_culvert_source))
            type_cb.setCurrentIndex(0)
            self.param_table.setCellWidget(idx, 4, type_cb)

            # B, m, n, 底坡, Q 输入框
            row_widgets = {
                'gap': gap,
                'type_combo': type_cb,
                'entries': {},
                'allow_arch_culvert_source': allow_arch_culvert_source,
            }
            for c, key in [(5, 'B'), (6, 'H'), (7, 'm'), (8, 'n'), (9, 'slope'), (10, 'Q')]:
                default_val = ""
                if key == 'n':
                    default_val = "0.014"
                elif key == 'slope':
                    default_val = "3000"
                elif key == 'Q':
                    default_val = f"{gap['flow']:.3f}"
                item = QTableWidgetItem(default_val)
                item.setTextAlignment(Qt.AlignCenter)
                self.param_table.setItem(idx, c, item)
                row_widgets['entries'][key] = (idx, c)

            status_text = describe_transition_gap_source(gap)
            item_status = QTableWidgetItem(status_text)
            item_status.setFlags(item_status.flags() & ~Qt.ItemIsEditable)
            item_status.setTextAlignment(Qt.AlignCenter)
            item_status.setToolTip(status_text)
            if status_text == "需手动填写":
                item_status.setForeground(QColor("#CC6600"))
            else:
                item_status.setForeground(QColor("#2E7D32"))
            self.param_table.setItem(idx, 11, item_status)

            self._row_widgets.append(row_widgets)
            type_cb.currentTextChanged.connect(lambda _text, row_idx=idx: self._apply_row_type_mode(row_idx))
            self._apply_row_type_mode(idx)

        self._apply_param_table_column_widths()
        lay.addWidget(self.param_table, stretch=1)
        self.param_table.currentCellChanged.connect(self._on_param_current_cell_changed)
        self.param_table.cellChanged.connect(self._on_param_cell_changed)
        undo_sc = QShortcut(QKeySequence.StandardKey.Undo, self.param_table)
        undo_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        undo_sc.activated.connect(self._undo_param_table)
        redo_sc = QShortcut(QKeySequence.StandardKey.Redo, self.param_table)
        redo_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        redo_sc.activated.connect(self._redo_param_table)

        # 底部按钮
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_ok = PrimaryPushButton("确定")
        btn_ok.clicked.connect(self._on_ok)
        btn_ok.setFixedWidth(100)
        btn_ok.setDefault(True)
        btn_ok.setFocus()
        btn_lay.addWidget(btn_ok)
        lay.addLayout(btn_lay)

    def _apply_param_table_column_widths(self):
        header = self.param_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.Interactive)

        width_map = {
            0: 44,
            1: 170,
            2: 170,
            3: 110,
            4: 120,
            5: 80,
            6: 80,
            7: 65,
            8: 80,
            9: 90,
            10: 100,
        }
        for col, width in width_map.items():
            self.param_table.setColumnWidth(col, width)

        metrics = self.param_table.fontMetrics()
        status_width = metrics.horizontalAdvance("状态/来源") + 26
        for row in range(self.param_table.rowCount()):
            item = self.param_table.item(row, 11)
            if item and item.text():
                status_width = max(status_width, metrics.horizontalAdvance(item.text()) + 26)
        self.param_table.setColumnWidth(11, max(145, status_width))

    def _snapshot_param_table(self):
        rows = []
        for r in range(self.param_table.rowCount()):
            row = []
            for c in range(self.param_table.columnCount()):
                if c == 4:
                    combo = self.param_table.cellWidget(r, 4)
                    row.append(combo.currentText() if combo else "明渠-梯形")
                else:
                    item = self.param_table.item(r, c)
                    row.append(item.text() if item else "")
            rows.append(row)
        return rows

    def _restore_param_table(self, snapshot):
        self.param_table.blockSignals(True)
        self._param_undo_group += 1
        try:
            for r, row_data in enumerate(snapshot):
                for c, val in enumerate(row_data):
                    if c == 4:
                        combo = self.param_table.cellWidget(r, 4)
                        if combo:
                            combo.blockSignals(True)
                            idx = combo.findText(val)
                            if idx >= 0:
                                combo.setCurrentIndex(idx)
                            combo.blockSignals(False)
                    elif c >= 5:
                        item = self.param_table.item(r, c)
                        if item:
                            item.setText(val)
                        else:
                            new_item = QTableWidgetItem(val)
                            new_item.setTextAlignment(Qt.AlignCenter)
                            self.param_table.setItem(r, c, new_item)
        finally:
            self._param_undo_group -= 1
            self.param_table.blockSignals(False)

    def _push_param_undo(self):
        if self._param_undo_group > 0:
            return
        self._param_undo_stack.append(self._snapshot_param_table())
        if len(self._param_undo_stack) > 20:
            self._param_undo_stack.pop(0)
        self._param_redo_stack.clear()
        self._param_pre_edit_snapshot = None

    def _on_param_current_cell_changed(self, row, col, prev_row, prev_col):
        if self._param_undo_group == 0:
            self._param_pre_edit_snapshot = self._snapshot_param_table()

    def _on_param_cell_changed(self, row, col):
        if self._param_undo_group == 0 and self._param_pre_edit_snapshot is not None:
            self._param_undo_stack.append(self._param_pre_edit_snapshot)
            if len(self._param_undo_stack) > 20:
                self._param_undo_stack.pop(0)
            self._param_redo_stack.clear()
            self._param_pre_edit_snapshot = None

    def _undo_param_table(self):
        if not self._param_undo_stack:
            return
        self._param_redo_stack.append(self._snapshot_param_table())
        if len(self._param_redo_stack) > 20:
            self._param_redo_stack.pop(0)
        self._restore_param_table(self._param_undo_stack.pop())

    def _redo_param_table(self):
        if not self._param_redo_stack:
            return
        self._param_undo_stack.append(self._snapshot_param_table())
        if len(self._param_undo_stack) > 20:
            self._param_undo_stack.pop(0)
        self._restore_param_table(self._param_redo_stack.pop())

    def _set_cell(self, row, col, val):
        """设置表格单元格值"""
        item = self.param_table.item(row, col)
        if item is None:
            item = QTableWidgetItem(str(val))
            item.setTextAlignment(Qt.AlignCenter)
            self.param_table.setItem(row, col, item)
        else:
            item.setText(str(val))

    def _apply_row_type_mode(self, row_idx):
        row = self._row_widgets[row_idx]
        structure_type = normalize_transition_structure_type(row['type_combo'].currentText())
        entries = row['entries']
        is_culvert = is_transition_culvert_type(structure_type)
        h_item = self.param_table.item(*entries['H'])
        m_item = self.param_table.item(*entries['m'])
        if h_item:
            if is_culvert:
                h_item.setFlags(h_item.flags() | Qt.ItemIsEditable)
            else:
                h_item.setFlags(h_item.flags() & ~Qt.ItemIsEditable)
                if h_item.text().strip():
                    h_item.setText("")
        if m_item:
            if is_culvert:
                m_item.setFlags(m_item.flags() & ~Qt.ItemIsEditable)
                if m_item.text().strip():
                    m_item.setText("")
            else:
                m_item.setFlags(m_item.flags() | Qt.ItemIsEditable)

    def _fill_recommended(self, row_idx):
        """用上游参数填充一行"""
        row = self._row_widgets[row_idx]
        up = row['gap'].get('reference_segment') or row['gap'].get('upstream_channel')
        if not up:
            return
        st = normalize_transition_structure_type(up.get('structure_type', '明渠-梯形'))
        self._set_combo_items(
            row['type_combo'],
            self._build_structure_type_options(row.get('allow_arch_culvert_source', False)),
            current_text=st,
        )
        self._apply_row_type_mode(row_idx)

        entries = row['entries']
        # U形明渠使用半径R（arc_radius），其他使用底宽B
        if st == "明渠-U形":
            b_val = up.get('arc_radius', 0)
        else:
            b_val = up.get('bottom_width', 0)
        self._set_cell(entries['B'][0], entries['B'][1], f"{b_val:.2f}")
        self._set_cell(entries['H'][0], entries['H'][1], f"{up.get('structure_height', 0):.2f}" if is_transition_culvert_type(st) and up.get('structure_height', 0) > 0 else "")
        self._set_cell(entries['m'][0], entries['m'][1], "" if is_transition_culvert_type(st) else f"{up.get('side_slope', 0)}")
        self._set_cell(entries['n'][0], entries['n'][1], f"{up.get('roughness', 0.014)}")
        self._set_cell(entries['slope'][0], entries['slope'][1], f"{up.get('slope_inv', 3000):.0f}")
        self._set_cell(entries['Q'][0], entries['Q'][1], f"{row['gap']['flow']:.3f}")

    def _fill_all_recommended(self):
        self._push_param_undo()
        self._param_undo_group += 1
        try:
            for i, row in enumerate(self._row_widgets):
                if row['gap'].get('reference_segment') or row['gap'].get('upstream_channel'):
                    self._fill_recommended(i)
        finally:
            self._param_undo_group -= 1

    def _clear_all(self):
        self._push_param_undo()
        self._param_undo_group += 1
        for row in self._row_widgets:
            row['type_combo'].blockSignals(True)
            row['type_combo'].setCurrentIndex(0)
            row['type_combo'].blockSignals(False)
            entries = row['entries']
            self._set_cell(entries['B'][0], entries['B'][1], "")
            self._set_cell(entries['H'][0], entries['H'][1], "")
            self._set_cell(entries['m'][0], entries['m'][1], "")
            self._set_cell(entries['n'][0], entries['n'][1], "0.014")
            self._set_cell(entries['slope'][0], entries['slope'][1], "3000")
            self._set_cell(entries['Q'][0], entries['Q'][1], f"{row['gap']['flow']:.3f}")
            self._apply_row_type_mode(self._row_widgets.index(row))
        self._param_undo_group -= 1

    def _on_mode_change(self):
        enabled = self.rb_table.isChecked()
        self._fill_btn.setEnabled(enabled)
        self._clear_btn.setEnabled(enabled)
        # 禁用/启用表格编辑
        for r in range(self.param_table.rowCount()):
            for c in range(5, 11):
                item = self.param_table.item(r, c)
                if item:
                    if enabled:
                        item.setFlags(item.flags() | Qt.ItemIsEditable)
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def _get_cell_val(self, row, col, default=0.0):
        item = self.param_table.item(row, col)
        if item is None:
            return default
        text = item.text().strip()
        if not text:
            return default
        try:
            return float(text)
        except ValueError:
            return default

    def _validate_and_collect(self):
        """验证表格并收集参数"""
        params = {}
        for idx, row in enumerate(self._row_widgets):
            entries = row['entries']
            try:
                st = row['type_combo'].currentText()
                B = self._get_cell_val(entries['B'][0], entries['B'][1])
                m = self._get_cell_val(entries['m'][0], entries['m'][1]) if st == "明渠-梯形" else 0
                n = self._get_cell_val(entries['n'][0], entries['n'][1], 0.014)
                si = self._get_cell_val(entries['slope'][0], entries['slope'][1], 3000)
                Q = self._get_cell_val(entries['Q'][0], entries['Q'][1])
                slope_i = 1.0 / si if si > 0 else 0

                if Q <= 0:
                    fluent_info(self, "输入错误", f"第 {idx+1} 处: 流量 Q 必须大于 0")
                    return None
                # U形明渠和圆形明渠没有底宽B，验证时跳过
                if B <= 0 and st not in ("明渠-圆形", "明渠-U形"):
                    fluent_info(self, "输入错误", f"第 {idx+1} 处: 底宽 B 必须大于 0")
                    return None
                # U形明渠验证半径R
                if st == "明渠-U形" and B <= 0:
                    fluent_info(self, "输入错误", f"第 {idx+1} 处: 半径 R 必须大于 0")
                    return None
                if n <= 0:
                    fluent_info(self, "输入错误", f"第 {idx+1} 处: 糙率 n 必须大于 0")
                    return None

                D_param = B if st == "明渠-圆形" else 0.0
                B_param = 0.0 if st in ("明渠-圆形", "明渠-U形") else B
                h = calculate_normal_depth(Q, B_param, m, n, slope_i, D=D_param)
                if h <= 0:
                    up = row['gap'].get('upstream_channel')
                    if up and up.get('water_depth', 0) > 0:
                        h = up['water_depth']
                    else:
                        fluent_info(self, "计算错误",
                                    f"第 {idx+1} 处: 无法计算有效水深，请检查参数")
                        return None

                # 从上游渠道继承结构高度（用于计算渠顶高程）
                up = row['gap'].get('upstream_channel') or {}
                sh = up.get('structure_height', 0.0)
                
                # U形明渠：B字段存储的是半径R，需要设置到arc_radius
                if st == "明渠-U形":
                    params[idx] = OpenChannelParams(
                        name="-", structure_type=st,
                        bottom_width=0, water_depth=h, side_slope=m,
                        roughness=n, slope_inv=si, flow=Q,
                        flow_section=row['gap'].get('flow_section', ''),
                        structure_height=sh,
                        arc_radius=B,
                        theta_deg=up.get('theta_deg', 0.0),
                    )
                else:
                    params[idx] = OpenChannelParams(
                        name="-", structure_type=st,
                        bottom_width=B, water_depth=h, side_slope=m,
                        roughness=n, slope_inv=si, flow=Q,
                        flow_section=row['gap'].get('flow_section', ''),
                        structure_height=sh,
                    )
            except ValueError:
                fluent_info(self, "输入错误", f"第 {idx+1} 处: 请输入有效数值")
                return None
        return params

    def _validate_and_collect_v2(self):
        params = {}
        for idx, row in enumerate(self._row_widgets):
            entries = row['entries']
            try:
                st = normalize_transition_structure_type(row['type_combo'].currentText())
                B = self._get_cell_val(entries['B'][0], entries['B'][1])
                H = self._get_cell_val(entries['H'][0], entries['H'][1])
                m = self._get_cell_val(entries['m'][0], entries['m'][1]) if st == "明渠-梯形" else 0.0
                n = self._get_cell_val(entries['n'][0], entries['n'][1], 0.014)
                si = self._get_cell_val(entries['slope'][0], entries['slope'][1], 3000)
                Q = self._get_cell_val(entries['Q'][0], entries['Q'][1])
                if Q <= 0:
                    fluent_info(self, "输入错误", f"第 {idx+1} 处: 流量 Q 必须大于 0")
                    return None
                if B <= 0 and st not in ("明渠-圆形", "明渠-U形"):
                    fluent_info(self, "输入错误", f"第 {idx+1} 处: 底宽 B 必须大于 0")
                    return None
                if st == "明渠-U形" and B <= 0:
                    fluent_info(self, "输入错误", f"第 {idx+1} 处: 半径 R 必须大于 0")
                    return None
                if is_transition_culvert_type(st) and H <= 0:
                    fluent_info(self, "输入错误", f"第 {idx+1} 处: 暗涵高度 H 必须大于 0")
                    return None
                if n <= 0 or si <= 0:
                    fluent_info(self, "输入错误", f"第 {idx+1} 处: 糙率 n 和底坡 1/i 必须大于 0")
                    return None

                upstream = row['gap'].get('reference_segment') or row['gap'].get('upstream_channel')
                params[idx] = build_transition_fill_params(
                    structure_type=st,
                    B=B,
                    m=m,
                    H=H,
                    n=n,
                    slope_inv=si,
                    Q=Q,
                    flow_section=row['gap'].get('flow_section', ''),
                    upstream_channel=upstream,
                    theta_deg=(upstream or {}).get('theta_deg', 180.0) if is_transition_arch_culvert_type(st) else 180.0,
                )
                if params[idx] is None:
                    fluent_info(self, "计算错误", f"第 {idx+1} 处: 无法生成有效的补段参数，请检查 B/H/m/n/底坡")
                    return None
            except ValueError:
                fluent_info(self, "输入错误", f"第 {idx+1} 处: 请输入有效数值")
                return None
        return params

    def _on_ok(self):
        if self.rb_table.isChecked():
            params = self._validate_and_collect_v2()
            if params is None:
                return
            self.result = {'mode': self.RESULT_TABLE_EDIT, 'params': params}
        else:
            self.result = {'mode': self.RESULT_MANUAL_EACH, 'params': {}}
        self.accept()

    def closeEvent(self, event):
        if fluent_question(self, "确认取消",
                "关闭后将跳过补段插入，渠段之间可能出现空隙。\n确定要取消吗？"):
            self.result = {'mode': self.RESULT_CANCELLED, 'params': {}}
            event.accept()
        else:
            event.ignore()

    def get_result(self):
        return self.result


# ============================================================
# 补段参数选择对话框（逐一弹窗模式）
# ============================================================
class OpenChannelDialog(QDialog):
    """
    补段参数选择对话框（PySide6版）

    用于在建筑物之间插入补段时，让用户选择参数来源。
    """

    STRUCTURE_TYPES = TRANSITION_FILLER_TYPES
    MANUAL_STRUCTURE_TYPES = MANUAL_TRANSITION_FILLER_TYPES

    @classmethod
    def _build_structure_type_options(cls, allow_arch_culvert_source: bool = False):
        """按来源限制补段结构形式选项。"""
        options = list(cls.MANUAL_STRUCTURE_TYPES)
        if allow_arch_culvert_source and "暗涵-圆拱直墙型" not in options:
            options.append("暗涵-圆拱直墙型")
        return options

    def __init__(self, parent,
                 upstream_channel: Optional[Dict] = None,
                 available_length: float = 0.0,
                 prev_structure: str = "",
                 next_structure: str = "",
                 flow_section: str = "",
                 flow: float = 0.0,
                 current_index: int = 1,
                 total_count: int = 1):
        super().__init__(parent)
        self.upstream_channel = upstream_channel
        self.available_length = available_length
        self.prev_structure = prev_structure
        self.next_structure = next_structure
        self.flow_section = flow_section
        self.flow = flow
        self.current_index = current_index
        self.total_count = total_count

        self._result: Optional[OpenChannelParams] = None
        self.apply_all_remaining = False
        self._allow_arch_culvert_source = (
            normalize_transition_structure_type(
                (self.upstream_channel or {}).get("structure_type", "")
            )
            == "暗涵-圆拱直墙型"
        )

        if total_count > 1:
            self.setWindowTitle(f"插入补段 ({current_index}/{total_count})")
        else:
            self.setWindowTitle("插入补段")
        self.resize(520, 560)
        self.setMinimumSize(420, 440)
        self._create_ui()

    def _refresh_structure_type_choices(self, current_text=""):
        """按当前来源模式刷新结构形式选项。"""
        allow_arch_culvert_source = self._allow_arch_culvert_source and not self.rb_manual.isChecked()
        options = self._build_structure_type_options(allow_arch_culvert_source)
        target_text = str(current_text or "").strip()
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        self.type_combo.addItems(options)
        if target_text:
            target_index = self.type_combo.findText(target_text)
            if target_index >= 0:
                self.type_combo.setCurrentIndex(target_index)
        self.type_combo.blockSignals(False)

    def _create_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        # 位置信息
        loc_grp = QGroupBox("插入位置")
        loc_lay = QVBoxLayout(loc_grp)
        loc_lay.addWidget(QLabel(f"前方建筑物: {self.prev_structure}"))
        loc_lay.addWidget(QLabel(f"后方建筑物: {self.next_structure}"))
        loc_lay.addWidget(QLabel(f"可用长度: {self.available_length:.1f} m    流量段: {self.flow_section}    流量: {self.flow:.3f} m³/s"))
        lay.addWidget(loc_grp)

        # 参数来源
        src_grp = QGroupBox("参数来源")
        src_lay = QVBoxLayout(src_grp)
        self.src_group = QButtonGroup(self)
        self.rb_copy = QRadioButton("复制推荐补段参数（推荐）")
        self.rb_manual = QRadioButton("手动输入参数")
        self.src_group.addButton(self.rb_copy)
        self.src_group.addButton(self.rb_manual)
        src_lay.addWidget(self.rb_copy)

        if self.upstream_channel:
            self.rb_copy.setChecked(True)
            up = self.upstream_channel
            # U形明渠显示半径R，其他显示底宽B
            st_type = up.get('structure_type', '')
            if st_type == "明渠-U形":
                b_label = f"R={up.get('arc_radius', 0):.2f}m"
            else:
                b_label = f"B={up.get('bottom_width', 0):.2f}m"
            if is_transition_culvert_type(st_type):
                extra_label = f"H={up.get('structure_height', 0):.2f}m"
            else:
                extra_label = f"m={up.get('side_slope', 0)}"
            info = f"  → {st_type}  {b_label}  {extra_label}  n={up.get('roughness', 0.014)}  底坡1/{up.get('slope_inv', 3000):.0f}"
            lbl_info = QLabel(info)
            lbl_info.setStyleSheet("color: green; margin-left: 20px;")
            src_lay.addWidget(lbl_info)
        else:
            self.rb_copy.setEnabled(False)
            self.rb_manual.setChecked(True)

        src_lay.addWidget(self.rb_manual)
        lay.addWidget(src_grp)

        # 参数编辑区
        param_grp = QGroupBox("补段参数")
        pg = QGridLayout(param_grp)
        pg.setVerticalSpacing(10)
        pg.setHorizontalSpacing(12)
        pg.setContentsMargins(12, 16, 12, 12)

        _row_h = 32
        self._secondary_row_height = _row_h
        pg.addWidget(QLabel("结构形式:"), 0, 0)
        self.type_combo = QComboBox()
        self.type_combo.setMinimumHeight(_row_h)
        self._refresh_structure_type_choices()
        pg.addWidget(self.type_combo, 0, 1)

        pg.addWidget(QLabel("底宽 B(m):"), 1, 0)
        self.edit_B = QLineEdit()
        self.edit_B.setMinimumHeight(_row_h)
        pg.addWidget(self.edit_B, 1, 1)
        self.secondary_label = QLabel("边坡 m:")
        pg.addWidget(self.secondary_label, 2, 0)
        self.edit_m = QLineEdit()
        self.edit_m.setMinimumHeight(_row_h)
        self.edit_m.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.edit_H = QLineEdit()
        self.edit_H.setMinimumHeight(_row_h)
        self.edit_H.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.secondary_input_stack = QStackedWidget()
        self.secondary_input_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.secondary_input_stack.addWidget(self.edit_m)
        self.secondary_input_stack.addWidget(self.edit_H)
        self._sync_secondary_input_height()
        pg.addWidget(self.secondary_input_stack, 2, 1)

        pg.addWidget(QLabel("糙率 n:"), 3, 0)
        self.edit_n = QLineEdit()
        self.edit_n.setMinimumHeight(_row_h)
        self.edit_n.setText("0.014")
        pg.addWidget(self.edit_n, 3, 1)

        pg.addWidget(QLabel("底坡 1/i:"), 4, 0)
        self.edit_slope = QLineEdit()
        self.edit_slope.setMinimumHeight(_row_h)
        self.edit_slope.setText("3000")
        pg.addWidget(self.edit_slope, 4, 1)

        pg.addWidget(QLabel("流量 Q(m³/s):"), 5, 0)
        self.edit_Q = QLineEdit()
        self.edit_Q.setMinimumHeight(_row_h)
        self.edit_Q.setText(f"{self.flow:.3f}")
        pg.addWidget(self.edit_Q, 5, 1)

        lay.addWidget(param_grp)

        # 按钮区
        btn_lay = QHBoxLayout()
        if self.total_count > 1 and self.current_index < self.total_count:
            btn_all = PushButton("剩余全部用推荐")
            btn_all.clicked.connect(self._on_apply_all)
            btn_lay.addWidget(btn_all)
        btn_lay.addStretch()
        btn_skip = PushButton("跳过")
        btn_skip.clicked.connect(self.reject)
        btn_ok = PrimaryPushButton("确定")
        btn_ok.clicked.connect(self._on_ok)
        btn_lay.addWidget(btn_skip)
        btn_lay.addWidget(btn_ok)
        lay.addLayout(btn_lay)

        # 收集可编辑控件，用于禁用/启用切换
        self._param_widgets = [self.type_combo, self.edit_B, self.edit_H, self.edit_m,
                               self.edit_n, self.edit_slope, self.edit_Q]

        # 如果有上游参数，默认填充
        if self.upstream_channel:
            self._fill_from_upstream()
        self._on_source_change()  # 初始化启用/禁用状态
        self.rb_copy.toggled.connect(self._on_source_change)
        self.type_combo.currentTextChanged.connect(self._update_type_mode)
        self._update_type_mode()

    def _update_type_mode(self, _text=None):
        structure_type = normalize_transition_structure_type(self.type_combo.currentText())
        is_culvert = is_transition_culvert_type(structure_type)
        self.secondary_label.setText("高度 H(m):" if is_culvert else "边坡 m:")
        self.secondary_input_stack.setCurrentWidget(self.edit_H if is_culvert else self.edit_m)
        self._sync_secondary_input_height()
        self.edit_H.setEnabled(self.rb_manual.isChecked() and is_culvert)
        self.edit_m.setEnabled(self.rb_manual.isChecked() and not is_culvert)
        if is_culvert:
            self.edit_m.clear()
        else:
            self.edit_H.clear()

    def _sync_secondary_input_height(self):
        row_height = getattr(self, "_secondary_row_height", 0)
        for widget in (self.edit_m, self.edit_H):
            row_height = max(
                row_height,
                widget.minimumHeight(),
                widget.minimumSizeHint().height(),
                widget.sizeHint().height(),
            )

        for widget in (self.edit_m, self.edit_H):
            widget.setMinimumHeight(row_height)
            widget.updateGeometry()

        self.secondary_input_stack.setMinimumHeight(row_height)
        self.secondary_input_stack.setMaximumHeight(row_height)
        self.secondary_input_stack.updateGeometry()

    def _fill_from_upstream(self):
        """用上游参数填充"""
        up = self.upstream_channel
        if not up:
            return
        st = up.get('structure_type', '明渠-梯形')
        st = normalize_transition_structure_type(st)
        self._refresh_structure_type_choices(st)
        # U形明渠使用半径R（arc_radius），其他使用底宽B
        if st == "明渠-U形":
            b_val = up.get('arc_radius', 0)
        else:
            b_val = up.get('bottom_width', 0)
        self.edit_B.setText(f"{b_val:.2f}")
        self.edit_H.setText(f"{up.get('structure_height', 0):.2f}" if is_transition_culvert_type(st) and up.get('structure_height', 0) > 0 else "")
        self.edit_m.setText("" if is_transition_culvert_type(st) else f"{up.get('side_slope', 0)}")
        self.edit_n.setText(f"{up.get('roughness', 0.014)}")
        self.edit_slope.setText(f"{up.get('slope_inv', 3000):.0f}")
        self._update_type_mode()

    def _on_source_change(self, checked=None):
        is_manual = self.rb_manual.isChecked()
        current_text = self.type_combo.currentText()
        self._refresh_structure_type_choices(current_text)
        for w in self._param_widgets:
            w.setEnabled(is_manual)
        if not is_manual and self.upstream_channel:
            self._fill_from_upstream()
        self._update_type_mode()

    def _on_apply_all(self):
        """剩余全部用推荐"""
        self.apply_all_remaining = True
        if self.upstream_channel:
            self._fill_from_upstream()
        self._on_ok()

    def _on_ok(self):
        try:
            st = normalize_transition_structure_type(self.type_combo.currentText())
            B = float(self.edit_B.text() or 0)
            H = float(self.edit_H.text() or 0)
            m = float(self.edit_m.text() or 0) if st == "明渠-梯形" else 0.0
            n = float(self.edit_n.text() or 0.014)
            si = float(self.edit_slope.text() or 3000)
            Q = float(self.edit_Q.text() or 0)

            if Q <= 0:
                fluent_info(self, "输入错误", "流量 Q 必须大于 0")
                return
            if B <= 0 and st not in ("明渠-圆形", "明渠-U形"):
                fluent_info(self, "输入错误", "底宽 B 必须大于 0")
                return
            if st == "明渠-U形" and B <= 0:
                fluent_info(self, "输入错误", "半径 R 必须大于 0")
                return
            if is_transition_culvert_type(st) and H <= 0:
                fluent_info(self, "输入错误", "暗涵高度 H 必须大于 0")
                return

            self._result = build_transition_fill_params(
                structure_type=st,
                B=B,
                m=m,
                H=H,
                n=n,
                slope_inv=si,
                Q=Q,
                flow_section=self.flow_section,
                upstream_channel=self.upstream_channel,
                theta_deg=(self.upstream_channel or {}).get('theta_deg', 180.0) if is_transition_arch_culvert_type(st) else 180.0,
            )
            if self._result is None:
                fluent_info(self, "计算错误", "无法生成有效的补段参数，请检查 B/H/m/n/底坡")
                return
            self.accept()
            return
            D_param = B if st == "明渠-圆形" else 0.0
            B_param = 0.0 if st in ("明渠-圆形", "明渠-U形") else B
            h = calculate_normal_depth(Q, B_param, m, n, slope_i, D=D_param)
            if h <= 0 and self.upstream_channel:
                h = self.upstream_channel.get('water_depth', 0)
            if h <= 0:
                fluent_info(self, "计算错误", "无法计算有效水深，请检查参数")
                return

            # 从上游渠道继承结构高度（用于计算渠顶高程）
            sh = self.upstream_channel.get('structure_height', 0.0) if self.upstream_channel else 0.0
            
            # U形明渠：B字段存储的是半径R，需要设置到arc_radius
            if st == "明渠-U形":
                theta_deg = self.upstream_channel.get('theta_deg', 0.0) if self.upstream_channel else 0.0
                self._result = OpenChannelParams(
                    name="-", structure_type=st,
                    bottom_width=0, water_depth=h, side_slope=m,
                    roughness=n, slope_inv=si, flow=Q,
                    flow_section=self.flow_section,
                    structure_height=sh,
                    arc_radius=B,
                    theta_deg=theta_deg,
                )
            else:
                self._result = OpenChannelParams(
                    name="-", structure_type=st,
                    bottom_width=B, water_depth=h, side_slope=m,
                    roughness=n, slope_inv=si, flow=Q,
                    flow_section=self.flow_section,
                    structure_height=sh,
                )
            self.accept()
        except ValueError:
            fluent_info(self, "输入错误", "请输入有效数值")

    def get_result(self):
        return self._result


# ============================================================
# 转弯半径自动计算详情对话框
# ============================================================
class TurnRadiusCalcDialog(QDialog):
    """展示转弯半径自动计算的详细过程：表格 + 规范依据 + 结论"""

    def __init__(self, parent=None, rec_r=0.0, max_r=0.0,
                 details=None, controlling_name=""):
        """
        Parameters
        ----------
        rec_r : float  - 推荐值（向上取整后）
        max_r : float  - 计算最大值（未取整）
        details : list  - [(name, stype, dim_str, basis, r_val), ...]
        controlling_name : str - 控制节点名称
        """
        super().__init__(parent)
        self.setWindowTitle("转弯半径自动计算")
        self.setMinimumWidth(620)
        self.setMinimumHeight(380)
        self.setStyleSheet("QDialog { background: #FAFBFC; }")

        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 16, 20, 16)

        # ---- 顶部结论区 ----
        top = QHBoxLayout()
        top.setSpacing(12)

        icon_lbl = QLabel("📐")
        icon_lbl.setStyleSheet("font-size: 32px;")
        icon_lbl.setFixedSize(48, 48)
        icon_lbl.setAlignment(Qt.AlignCenter)
        top.addWidget(icon_lbl)

        result_box = QVBoxLayout()
        result_box.setSpacing(2)
        val_lbl = QLabel(f"{rec_r:.1f} m")
        val_lbl.setStyleSheet(
            "font-size: 28px; font-weight: bold; color: #1976D2;"
        )
        result_box.addWidget(val_lbl)
        sub_lbl = QLabel("推荐转弯半径（向上取整）")
        sub_lbl.setStyleSheet("font-size: 12px; color: #424242;")
        result_box.addWidget(sub_lbl)
        top.addLayout(result_box)
        top.addStretch()

        if controlling_name and details:
            ctrl_lbl = QLabel(f"控制节点：{controlling_name}")
            ctrl_lbl.setStyleSheet(
                "font-size: 12px; color: #E65100; font-weight: bold;"
                "background: #FFF3E0; border-radius: 4px; padding: 4px 10px;"
            )
            top.addWidget(ctrl_lbl)

        lay.addLayout(top)

        # ---- 分隔线 ----
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #E0E0E0;")
        lay.addWidget(sep)

        # ---- 中间表格区 ----
        if details:
            tbl_label = QLabel(f"逐节点计算明细（共 {len(details)} 个有效节点）")
            tbl_label.setStyleSheet(
                "font-size: 13px; font-weight: bold; color: #424242;"
            )
            lay.addWidget(tbl_label)

            headers = ["序号", "节点名称", "结构类型", "关键尺寸", "规范公式", "Rmin (m)"]
            tbl = QTableWidget(len(details), len(headers))
            tbl.setHorizontalHeaderLabels(headers)
            tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
            tbl.setAlternatingRowColors(True)
            tbl.verticalHeader().setVisible(False)
            tbl.setStyleSheet("""
                QTableWidget {
                    border: 1px solid #E0E0E0; border-radius: 4px;
                    background: white; alternate-background-color: #F5F7FA;
                    font-size: 12px; gridline-color: #EEEEEE;
                }
                QTableWidget::item { padding: 4px 6px; }
                QTableWidget::item:selected { background: #E3F2FD; color: #1565C0; }
                QHeaderView::section {
                    background: #ECEFF1; color: #37474F; font-weight: bold;
                    font-size: 12px; padding: 6px 4px;
                    border: none; border-bottom: 2px solid #B0BEC5;
                }
            """)

            HIGHLIGHT_BG = QColor("#FFF8E1")
            HIGHLIGHT_FG = QColor("#E65100")
            STAR = " ★"

            for row, (name, stype, dim, basis_str, r_val) in enumerate(details):
                is_ctrl = (name == controlling_name)
                items_data = [
                    str(row + 1),
                    (name + STAR) if is_ctrl else name,
                    stype,
                    dim,
                    basis_str,
                    f"{r_val:.1f}",
                ]
                for col, text in enumerate(items_data):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignCenter if col in (0, 5) else Qt.AlignLeft | Qt.AlignVCenter)
                    if is_ctrl:
                        item.setBackground(HIGHLIGHT_BG)
                        item.setForeground(HIGHLIGHT_FG)
                        f = item.font()
                        f.setBold(True)
                        item.setFont(f)
                    tbl.setItem(row, col, item)

            h_header = tbl.horizontalHeader()
            h_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            h_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            h_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
            h_header.setSectionResizeMode(3, QHeaderView.Stretch)
            h_header.setSectionResizeMode(4, QHeaderView.Stretch)
            h_header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
            tbl.setMaximumHeight(min(36 * len(details) + 36, 260))
            lay.addWidget(tbl, 1)
        else:
            no_data = QLabel("未找到有效建筑物节点，使用默认转弯半径。")
            no_data.setStyleSheet("font-size: 13px; color: #424242; padding: 20px;")
            no_data.setAlignment(Qt.AlignCenter)
            lay.addWidget(no_data)

        # ---- 底部规范依据 ----
        ref_grp = QGroupBox("规范依据")
        ref_grp.setStyleSheet("""
            QGroupBox {
                font-size: 12px; font-weight: bold; color: #1976D2;
                border: 1px solid #E0E0E0; border-radius: 6px;
                margin-top: 10px; padding: 12px 10px 8px 10px;
                background: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 12px;
                padding: 0 6px; background: white;
            }
        """)
        ref_lay = QVBoxLayout(ref_grp)
        ref_lay.setSpacing(4)
        ref_items = [
            ("隧洞", "弯曲半径 ≥ 洞径(或洞宽) × 5"),
            ("明渠", "弯曲半径 ≥ 水面宽度 × 5"),
            ("渡槽", "弯道半径 ≥ 连接明渠渠底宽度 × 5"),
            ("暗涵", "弯曲半径 ≥ 涵宽 × 5"),
        ]
        for cat, rule in ref_items:
            rl = QLabel(f"  •  {cat}：{rule}")
            rl.setStyleSheet("font-size: 13px; color: #616161; font-weight: normal;")
            ref_lay.addWidget(rl)
        note = QLabel("取所有建筑物中的最大值，向上取整，作为统一转弯半径。")
        note.setStyleSheet(
            "font-size: 13px; color: #1976D2; font-weight: normal; margin-top: 4px;"
        )
        ref_lay.addWidget(note)
        src = QLabel("——《灌溉与排水工程设计标准》(GB 50288)")
        src.setStyleSheet("font-size: 11px; color: #555555; font-weight: normal;")
        src.setAlignment(Qt.AlignRight)
        ref_lay.addWidget(src)
        lay.addWidget(ref_grp)

        # ---- 底部按钮 ----
        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_ok = PrimaryPushButton("确定")
        btn_ok.setFixedWidth(90)
        btn_ok.clicked.connect(self.accept)
        btn_lay.addWidget(btn_ok)
        lay.addLayout(btn_lay)
