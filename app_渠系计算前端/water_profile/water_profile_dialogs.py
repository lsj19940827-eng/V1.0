# -*- coding: utf-8 -*-
"""
水面线面板辅助对话框

包含：
- BuildingLengthDialog: 建筑物长度统计对话框
- BatchChannelConfirmDialog: 批量明渠段插入确认对话框
- OpenChannelDialog: 明渠段参数选择对话框（逐一弹窗模式）
- PressurePipeConfigDialog: 有压管道计算配置对话框
"""

import math
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QGroupBox, QGridLayout, QComboBox, QLineEdit,
    QRadioButton, QButtonGroup, QSplitter, QApplication,
    QSizePolicy, QTabWidget, QCheckBox, QScrollArea, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor, QShortcut, QKeySequence

from app_渠系计算前端.styles import auto_resize_table, fluent_info, fluent_error, fluent_question

try:
    from qfluentwidgets import PushButton, PrimaryPushButton, LineEdit, ComboBox
except ImportError:
    PushButton = QPushButton
    PrimaryPushButton = QPushButton
    LineEdit = QLineEdit
    ComboBox = QComboBox


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


# OpenChannelParams 已移至核心数据模型层，从此处重新导出以保持兼容
from 推求水面线.models.data_models import OpenChannelParams

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
    轻量级纵断面画布，复用倒虹吸 PipelineCanvas 的缩放/平移/绘制模式，
    但直接工作在节点字典数据上，无需 StructureSegment 模型。
    """

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

        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._drag_start = None
        self._drag_pan_start = None
        self._nodes = []

    def set_nodes(self, nodes):
        self._nodes = nodes or []
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self.update()

    def zoom_reset(self):
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self.update()

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
    """纵断面预览对话框 —— 可调整大小，内含大画布"""

    def __init__(self, parent=None, pipe_name="", nodes=None):
        super().__init__(parent)
        self.setWindowTitle(f"纵断面预览 — {pipe_name}")
        self.resize(800, 500)
        self.setMinimumSize(500, 350)
        self.setModal(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self._canvas = SimpleProfileCanvas(self)
        self._canvas.set_nodes(nodes or [])
        lay.addWidget(self._canvas, 1)

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

        btn_reset.clicked.connect(self._canvas.zoom_reset)
        btn_close.clicked.connect(self.accept)

        toolbar.addWidget(btn_reset)
        toolbar.addWidget(btn_close)

        lay.addLayout(toolbar)


# ============================================================
# 有压管道计算配置对话框
# ============================================================
class PressurePipeConfigDialog(QDialog):
    """有压管道计算配置对话框（在计算前配置参数）"""

    def __init__(self, parent=None, pipe_groups=None, manager=None):
        super().__init__(parent)
        self.setWindowTitle("有压管道水力计算配置")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        self.setModal(True)

        self._pipe_groups = pipe_groups or []
        self._manager = manager

        # 存储每个管道的纵断面数据 {pipe_name: [LongitudinalNode字典列表]}
        self._longitudinal_data = {}
        # 存储每个管道卡片的UI组件引用 {pipe_name: {hint, stats, canvas, expand_btn, table}}
        self._card_widgets = {}

        # 从manager加载已有的纵断面数据
        if self._manager and self._pipe_groups:
            for group in self._pipe_groups:
                config = self._manager.get_pipe_config(group.name)
                if config and config.longitudinal_nodes:
                    self._longitudinal_data[group.name] = config.longitudinal_nodes

        self._init_ui()

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
        if self._pipe_groups:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)

            scroll_widget = QWidget()
            scroll_lay = QVBoxLayout(scroll_widget)
            scroll_lay.setSpacing(12)

            for group in self._pipe_groups:
                card = self._create_pipe_card(group)
                scroll_lay.addWidget(card)

            scroll_lay.addStretch()
            scroll.setWidget(scroll_widget)
            lay.addWidget(scroll, 1)

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

    def _create_pipe_card(self, group):
        """为单个管道创建卡片（分层结构：摘要 + 迷你画布 + 可展开表格）"""
        from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QHeaderView

        card = QGroupBox(f"管道: {group.name}")
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
        info_label = QLabel(f"流量: {group.design_flow:.3f} m\u00b3/s  |  管径: {group.diameter:.3f} m  |  管材: {group.material_key}")
        info_label.setStyleSheet("font-size: 12px; color: #7F8C8D; font-weight: normal;")
        card_lay.addWidget(info_label)

        # 工具栏
        toolbar = QHBoxLayout()
        try:
            from qfluentwidgets import PushButton as FPB
            btn_import = FPB("导入纵断面DXF")
            btn_clear = FPB("清空纵断面")
            btn_preview = FPB("预览纵断面")
        except ImportError:
            btn_import = QPushButton("导入纵断面DXF")
            btn_clear = QPushButton("清空纵断面")
            btn_preview = QPushButton("预览纵断面")

        btn_import.clicked.connect(lambda: self._import_longitudinal_dxf(group.name, group.ip_points))
        btn_clear.clicked.connect(lambda: self._clear_longitudinal(group.name))
        btn_preview.clicked.connect(lambda: self._preview_longitudinal(group.name))
        btn_clear.setEnabled(False)
        btn_preview.setEnabled(False)
        toolbar.addWidget(btn_import)
        toolbar.addWidget(btn_clear)
        toolbar.addWidget(btn_preview)
        toolbar.addStretch()
        card_lay.addLayout(toolbar)

        # 空状态提示标签
        hint_label = QLabel("尚未导入纵断面数据，请点击「导入纵断面DXF」")
        hint_label.setStyleSheet(
            "font-size: 12px; color: #E65100; background: #FFF8E1; "
            "border: 1px solid #FFE0B2; border-radius: 4px; "
            "padding: 8px 12px; font-weight: normal;"
        )
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setObjectName(f"hint_{group.name}")
        card_lay.addWidget(hint_label)

        # 统计摘要标签
        stats_label = QLabel("")
        stats_label.setStyleSheet(
            "font-size: 12px; color: #546E7A; background: #ECEFF1; "
            "border: 1px solid #CFD8DC; border-radius: 4px; "
            "padding: 6px 10px; font-weight: normal;"
        )
        stats_label.setWordWrap(True)
        stats_label.setObjectName(f"stats_{group.name}")
        stats_label.setVisible(False)
        card_lay.addWidget(stats_label)

        # 迷你画布
        mini_canvas = SimpleProfileCanvas(self, fixed_height=200)
        mini_canvas.setObjectName(f"canvas_{group.name}")
        mini_canvas.setStyleSheet(
            "border: 1px solid #CFD8DC; border-radius: 4px;"
        )
        mini_canvas.setVisible(False)
        card_lay.addWidget(mini_canvas)

        # 展开/折叠按钮
        expand_btn = QPushButton("▶ 查看详细节点数据")
        expand_btn.setStyleSheet(
            "QPushButton { font-size: 12px; color: #1976D2; background: transparent; "
            "border: none; text-align: left; padding: 4px 0; font-weight: normal; }"
            "QPushButton:hover { color: #1565C0; text-decoration: underline; }"
        )
        expand_btn.setCursor(Qt.PointingHandCursor)
        expand_btn.setObjectName(f"expand_{group.name}")
        expand_btn.setVisible(False)
        card_lay.addWidget(expand_btn)

        # 纵断面节点表（默认折叠）
        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["桩号(m)", "高程(m)", "竖曲线半径(m)", "转弯类型", "转角(\u00b0)"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setMaximumHeight(200)
        table.setObjectName(f"long_table_{group.name}")
        table.setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        card_lay.addWidget(table)

        # 展开/折叠点击事件
        def toggle_table(checked=False, _name=group.name):
            tbl = self.findChild(QTableWidget, f"long_table_{_name}")
            btn = self.findChild(QPushButton, f"expand_{_name}")
            if tbl and btn:
                vis = not tbl.isVisible()
                tbl.setVisible(vis)
                btn.setText("▼ 隐藏详细节点数据" if vis else "▶ 查看详细节点数据")
        expand_btn.clicked.connect(toggle_table)

        # 保存组件引用
        self._card_widgets[group.name] = {
            'hint': hint_label,
            'stats': stats_label,
            'canvas': mini_canvas,
            'expand_btn': expand_btn,
            'table': table,
            'btn_clear': btn_clear,
            'btn_preview': btn_preview,
        }

        # 根据已有数据初始化状态
        has_data = group.name in self._longitudinal_data and self._longitudinal_data[group.name]
        if has_data:
            self._update_card_data_state(group.name, show_data=True)
        else:
            self._update_card_data_state(group.name, show_data=False)

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

    def _update_card_data_state(self, pipe_name, show_data=True):
        """切换卡片的数据显示状态"""
        w = self._card_widgets.get(pipe_name)
        if not w:
            return

        if show_data and pipe_name in self._longitudinal_data and self._longitudinal_data[pipe_name]:
            nodes = self._longitudinal_data[pipe_name]
            w['hint'].setVisible(False)
            w['stats'].setText(self._compute_stats(nodes))
            w['stats'].setVisible(True)
            w['canvas'].set_nodes(nodes)
            w['canvas'].setVisible(True)
            w['expand_btn'].setText("▶ 查看详细节点数据")
            w['expand_btn'].setVisible(True)
            w['table'].setVisible(False)
            w['btn_clear'].setEnabled(True)
            w['btn_preview'].setEnabled(True)
            self._refresh_long_table(pipe_name, w['table'])
        else:
            w['hint'].setVisible(True)
            w['stats'].setVisible(False)
            w['canvas'].setVisible(False)
            w['expand_btn'].setVisible(False)
            w['table'].setVisible(False)
            w['table'].setRowCount(0)
            w['btn_clear'].setEnabled(False)
            w['btn_preview'].setEnabled(False)

    def _import_longitudinal_dxf(self, pipe_name, ip_points):
        """导入纵断面DXF"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        import os
        import sys

        # 已有数据时弹出替换确认
        if pipe_name in self._longitudinal_data and self._longitudinal_data[pipe_name]:
            if not fluent_question(self, "确认替换",
                                   "当前已有纵断面数据，导入DXF将替换现有数据。\n\n是否继续？"):
                return

        _siphon_dir = os.path.join(os.path.dirname(__file__), '..', '..', '倒虹吸水力计算系统')
        if _siphon_dir not in sys.path:
            sys.path.insert(0, _siphon_dir)

        try:
            from dxf_parser import DxfParser
            import ezdxf
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
            chainage_offset = 0.0
            if ip_points and len(ip_points) > 0:
                doc = ezdxf.readfile(filepath)
                msp = doc.modelspace()
                polys = list(msp.query('LWPOLYLINE'))
                if not polys:
                    polys = list(msp.query('POLYLINE'))
                if polys:
                    first_point = list(polys[0].get_points(format='xyseb'))[0]
                    x_start = first_point[0]
                    mc_inlet = ip_points[0].get('x', 0.0)
                    chainage_offset = mc_inlet - x_start

            long_nodes, message = DxfParser.parse_longitudinal_profile(filepath, chainage_offset=chainage_offset)

            if not long_nodes:
                QMessageBox.critical(self, "导入失败", message or "DXF文件中未找到纵断面数据")
                return

            long_nodes_dict = []
            for node in long_nodes:
                node_dict = {
                    'chainage': node.chainage,
                    'elevation': node.elevation,
                    'vertical_curve_radius': node.vertical_curve_radius,
                    'turn_type': node.turn_type.name if hasattr(node.turn_type, 'name') else str(node.turn_type),
                    'turn_angle': node.turn_angle,
                    'slope_before': node.slope_before,
                    'slope_after': node.slope_after,
                    'arc_center_s': node.arc_center_s,
                    'arc_center_z': node.arc_center_z,
                    'arc_end_chainage': node.arc_end_chainage,
                    'arc_theta_rad': node.arc_theta_rad,
                }
                long_nodes_dict.append(node_dict)

            self._longitudinal_data[pipe_name] = long_nodes_dict

            if ip_points and len(ip_points) >= 2:
                ip_start = ip_points[0].get('x', 0.0)
                ip_end = ip_points[-1].get('x', 0.0)
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
                        del self._longitudinal_data[pipe_name]
                        self._update_card_data_state(pipe_name, show_data=False)
                        return

            self._update_card_data_state(pipe_name, show_data=True)
            fluent_info(self, "导入成功", f"{message}\n变坡点节点: {len(long_nodes)} 个")

        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def _clear_longitudinal(self, pipe_name):
        """清空纵断面数据"""
        if pipe_name not in self._longitudinal_data:
            return

        if not fluent_question(self, "确认清空", f"确定要清空管道 '{pipe_name}' 的纵断面数据吗？"):
            return

        del self._longitudinal_data[pipe_name]
        self._update_card_data_state(pipe_name, show_data=False)

    def _preview_longitudinal(self, pipe_name):
        """弹出纵断面预览对话框"""
        from PySide6.QtWidgets import QMessageBox

        if pipe_name not in self._longitudinal_data or not self._longitudinal_data[pipe_name]:
            QMessageBox.information(self, "预览", f"管道 '{pipe_name}' 尚未导入纵断面数据")
            return

        dlg = LongitudinalPreviewDialog(self, pipe_name=pipe_name,
                                         nodes=self._longitudinal_data[pipe_name])
        dlg.exec()

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
        """判断结构类型是否为建筑物（渡槽/隧洞/倒虹吸）"""
        return any(kw in structure_type for kw in ('渡槽', '隧洞', '倒虹吸'))

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
# 批量明渠段插入确认对话框
# ============================================================
class BatchChannelConfirmDialog(QDialog):
    """
    批量明渠段插入确认对话框（PySide6版）

    展示所有需要插入明渠段的位置，提供表格编辑和逐一确认两种模式。
    """

    RESULT_TABLE_EDIT = "table_edit"
    RESULT_MANUAL_EACH = "manual_each"
    RESULT_CANCELLED = "cancelled"

    STRUCTURE_TYPES = ["明渠-梯形", "明渠-矩形", "明渠-圆形", "明渠-U形"]

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

        self.setWindowTitle("批量插入明渠段")
        self.resize(1100, 580)
        self.setMinimumSize(900, 400)
        self._create_ui()
        self._fill_all_recommended()

    def _create_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(6)

        # 标题 & 统计
        has_upstream = sum(1 for g in self.gaps_info if g.get('has_upstream'))
        no_upstream = self.total_count - has_upstream

        lbl_title = QLabel(f"系统检测到 <b>{self.total_count}</b> 处需要插入明渠段")
        lay.addWidget(lbl_title)

        if has_upstream == self.total_count:
            lbl_sub = QLabel(f"全部 {self.total_count} 处均可自动匹配同流量段明渠参数")
            lbl_sub.setStyleSheet("color: green;")
        else:
            lbl_sub = QLabel(f"其中 {has_upstream} 处可自动匹配参数，{no_upstream} 处需手动输入")
            lbl_sub.setStyleSheet("color: #CC6600;")
        lay.addWidget(lbl_sub)

        # 原理说明
        tip_grp = QGroupBox("为什么需要插入明渠段？")
        tip_lay = QVBoxLayout(tip_grp)
        tip_text = (
            "渠系中各建筑物之间往往存在无建筑物覆盖的空余渠段。"
            "系统通过比较相邻建筑物间的里程差与渐变段长度之和，自动检测出这些空隙位置。\n"
            "为保证水面线推算的连续性，需要在空隙处补充明渠段。"
            "推荐直接复制上游已有明渠的断面参数，也可手动修改。"
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
        self.param_table = QTableWidget(self.total_count, 10)
        headers = ["#", "上游", "下游", "可用长度(m)", "结构形式", "B(m)", "m", "n", "底坡1/i", "Q(m³/s)"]
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
            type_cb.addItems(self.STRUCTURE_TYPES)
            type_cb.setCurrentIndex(0)
            self.param_table.setCellWidget(idx, 4, type_cb)

            # B, m, n, 底坡, Q 输入框
            row_widgets = {'gap': gap, 'type_combo': type_cb, 'entries': {}}
            for c, key in [(5, 'B'), (6, 'm'), (7, 'n'), (8, 'slope'), (9, 'Q')]:
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

            self._row_widgets.append(row_widgets)

            # 若有经济断面预算选项，切换类型时自动填充
            computed_opts = gap.get('computed_channel_options')
            if computed_opts:
                row_ref = row_widgets  # capture reference
                def _make_type_handler(rw, opts):
                    def _on_type_changed(index):
                        selected = rw['type_combo'].currentText()
                        p = opts.get(selected)
                        if p:
                            rw['gap']['upstream_channel'] = dict(p)
                            rw['gap']['upstream_channel'].update({
                                'flow': gap['flow'],
                                'flow_section': gap.get('flow_section', ''),
                                'structure_height': 0.0,
                                'name': '-',
                            })
                            self._push_param_undo()
                            self._param_undo_group += 1
                            try:
                                self._fill_recommended(self._row_widgets.index(rw))
                            finally:
                                self._param_undo_group -= 1
                    return _on_type_changed
                type_cb.currentIndexChanged.connect(_make_type_handler(row_ref, computed_opts))

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

    def _fill_recommended(self, row_idx):
        """用上游参数填充一行"""
        row = self._row_widgets[row_idx]
        up = row['gap'].get('upstream_channel')
        if not up:
            return
        st = up.get('structure_type', '明渠-梯形')
        idx_in_combo = self.STRUCTURE_TYPES.index(st) if st in self.STRUCTURE_TYPES else 0
        row['type_combo'].blockSignals(True)
        row['type_combo'].setCurrentIndex(idx_in_combo)
        row['type_combo'].blockSignals(False)

        entries = row['entries']
        # U形明渠使用半径R（arc_radius），其他使用底宽B
        if st == "明渠-U形":
            b_val = up.get('arc_radius', 0)
        else:
            b_val = up.get('bottom_width', 0)
        self._set_cell(entries['B'][0], entries['B'][1], f"{b_val:.2f}")
        self._set_cell(entries['m'][0], entries['m'][1], f"{up.get('side_slope', 0)}")
        self._set_cell(entries['n'][0], entries['n'][1], f"{up.get('roughness', 0.014)}")
        self._set_cell(entries['slope'][0], entries['slope'][1], f"{up.get('slope_inv', 3000):.0f}")
        self._set_cell(entries['Q'][0], entries['Q'][1], f"{row['gap']['flow']:.3f}")

    def _fill_all_recommended(self):
        self._push_param_undo()
        self._param_undo_group += 1
        try:
            for i, row in enumerate(self._row_widgets):
                if row['gap'].get('upstream_channel'):
                    self._fill_recommended(i)
        finally:
            self._param_undo_group -= 1

    def _fill_with_fallback_if_empty(self):
        """auto_confirm模式专用：对未填充的行使用 fallback 参数（原始上游明渠）兜底填充"""
        for i, row in enumerate(self._row_widgets):
            if not row['gap'].get('has_upstream'):
                fallback = row['gap'].get('upstream_channel_fallback')
                if fallback:
                    orig = row['gap'].get('upstream_channel')
                    row['gap']['upstream_channel'] = fallback
                    self._fill_recommended(i)
                    row['gap']['upstream_channel'] = orig

    def _clear_all(self):
        self._push_param_undo()
        self._param_undo_group += 1
        for row in self._row_widgets:
            row['type_combo'].blockSignals(True)
            row['type_combo'].setCurrentIndex(0)
            row['type_combo'].blockSignals(False)
            entries = row['entries']
            self._set_cell(entries['B'][0], entries['B'][1], "")
            self._set_cell(entries['m'][0], entries['m'][1], "")
            self._set_cell(entries['n'][0], entries['n'][1], "0.014")
            self._set_cell(entries['slope'][0], entries['slope'][1], "3000")
            self._set_cell(entries['Q'][0], entries['Q'][1], f"{row['gap']['flow']:.3f}")
        self._param_undo_group -= 1

    def _on_mode_change(self):
        enabled = self.rb_table.isChecked()
        self._fill_btn.setEnabled(enabled)
        self._clear_btn.setEnabled(enabled)
        # 禁用/启用表格编辑
        for r in range(self.param_table.rowCount()):
            for c in range(5, 10):
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

    def _on_ok(self):
        if self.rb_table.isChecked():
            params = self._validate_and_collect()
            if params is None:
                return
            self.result = {'mode': self.RESULT_TABLE_EDIT, 'params': params}
        else:
            self.result = {'mode': self.RESULT_MANUAL_EACH, 'params': {}}
        self.accept()

    def closeEvent(self, event):
        if fluent_question(self, "确认取消",
                "关闭后将跳过明渠段插入，渠段之间可能出现空隙。\n确定要取消吗？"):
            self.result = {'mode': self.RESULT_CANCELLED, 'params': {}}
            event.accept()
        else:
            event.ignore()

    def get_result(self):
        return self.result


# ============================================================
# 明渠段参数选择对话框（逐一弹窗模式）
# ============================================================
class OpenChannelDialog(QDialog):
    """
    明渠段参数选择对话框（PySide6版）

    用于在建筑物之间插入明渠段时，让用户选择参数来源。
    """

    STRUCTURE_TYPES = ["明渠-梯形", "明渠-矩形", "明渠-圆形", "明渠-U形"]

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

        if total_count > 1:
            self.setWindowTitle(f"插入明渠段 ({current_index}/{total_count})")
        else:
            self.setWindowTitle("插入明渠段")
        self.resize(520, 560)
        self.setMinimumSize(420, 440)
        self._create_ui()

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
        self.rb_copy = QRadioButton("复制同流量段明渠参数（推荐）")
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
            info = f"  → {st_type}  {b_label}  m={up.get('side_slope', 0)}  n={up.get('roughness', 0.014)}  底坡1/{up.get('slope_inv', 3000):.0f}"
            lbl_info = QLabel(info)
            lbl_info.setStyleSheet("color: green; margin-left: 20px;")
            src_lay.addWidget(lbl_info)
        else:
            self.rb_copy.setEnabled(False)
            self.rb_manual.setChecked(True)

        src_lay.addWidget(self.rb_manual)
        lay.addWidget(src_grp)

        # 参数编辑区
        param_grp = QGroupBox("明渠段参数")
        pg = QGridLayout(param_grp)
        pg.setVerticalSpacing(10)
        pg.setHorizontalSpacing(12)
        pg.setContentsMargins(12, 16, 12, 12)

        _row_h = 32
        pg.addWidget(QLabel("结构形式:"), 0, 0)
        self.type_combo = QComboBox()
        self.type_combo.setMinimumHeight(_row_h)
        self.type_combo.addItems(self.STRUCTURE_TYPES)
        pg.addWidget(self.type_combo, 0, 1)

        pg.addWidget(QLabel("底宽 B(m):"), 1, 0)
        self.edit_B = QLineEdit()
        self.edit_B.setMinimumHeight(_row_h)
        pg.addWidget(self.edit_B, 1, 1)

        pg.addWidget(QLabel("边坡 m:"), 2, 0)
        self.edit_m = QLineEdit()
        self.edit_m.setMinimumHeight(_row_h)
        pg.addWidget(self.edit_m, 2, 1)

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
        self._param_widgets = [self.type_combo, self.edit_B, self.edit_m,
                               self.edit_n, self.edit_slope, self.edit_Q]

        # 如果有上游参数，默认填充
        if self.upstream_channel:
            self._fill_from_upstream()
        self._on_source_change()  # 初始化启用/禁用状态
        self.rb_copy.toggled.connect(self._on_source_change)

    def _fill_from_upstream(self):
        """用上游参数填充"""
        up = self.upstream_channel
        if not up:
            return
        st = up.get('structure_type', '明渠-梯形')
        idx = self.STRUCTURE_TYPES.index(st) if st in self.STRUCTURE_TYPES else 0
        self.type_combo.setCurrentIndex(idx)
        # U形明渠使用半径R（arc_radius），其他使用底宽B
        if st == "明渠-U形":
            b_val = up.get('arc_radius', 0)
        else:
            b_val = up.get('bottom_width', 0)
        self.edit_B.setText(f"{b_val:.2f}")
        self.edit_m.setText(f"{up.get('side_slope', 0)}")
        self.edit_n.setText(f"{up.get('roughness', 0.014)}")
        self.edit_slope.setText(f"{up.get('slope_inv', 3000):.0f}")

    def _on_source_change(self, checked=None):
        is_manual = self.rb_manual.isChecked()
        for w in self._param_widgets:
            w.setEnabled(is_manual)
        if not is_manual and self.upstream_channel:
            self._fill_from_upstream()

    def _on_apply_all(self):
        """剩余全部用推荐"""
        self.apply_all_remaining = True
        if self.upstream_channel:
            self._fill_from_upstream()
        self._on_ok()

    def _on_ok(self):
        try:
            st = self.type_combo.currentText()
            B = float(self.edit_B.text() or 0)
            m = float(self.edit_m.text() or 0) if st == "明渠-梯形" else 0
            n = float(self.edit_n.text() or 0.014)
            si = float(self.edit_slope.text() or 3000)
            Q = float(self.edit_Q.text() or 0)
            slope_i = 1.0 / si if si > 0 else 0

            if Q <= 0:
                fluent_info(self, "输入错误", "流量 Q 必须大于 0")
                return
            # U形明渠和圆形明渠没有底宽B，验证时跳过
            if B <= 0 and st not in ("明渠-圆形", "明渠-U形"):
                fluent_info(self, "输入错误", "底宽 B 必须大于 0")
                return
            # U形明渠验证半径R
            if st == "明渠-U形" and B <= 0:
                fluent_info(self, "输入错误", "半径 R 必须大于 0")
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
