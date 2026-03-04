# -*- coding: utf-8 -*-
"""
倒虹吸专业对话框 —— PySide6版本
包含：进水口形状、出水口系数、拦污栅配置、结构段编辑、进口断面参数、通用构件添加/编辑、简洁编辑
"""

import math
import os
import sys

# 确保计算引擎路径
_pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_siphon_dir = os.path.join(_pkg_root, '倒虹吸水力计算系统')
if _siphon_dir not in sys.path:
    sys.path.insert(0, _siphon_dir)

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QGroupBox, QFrame, QRadioButton, QButtonGroup, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QSizePolicy, QScrollArea, QWidget, QComboBox
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QColor, QPixmap, QImage
from PySide6.QtWebEngineWidgets import QWebEngineView

from qfluentwidgets import (
    PushButton, PrimaryPushButton, LineEdit, ComboBox, CheckBox,
    InfoBar, InfoBarPosition
)

from 渠系断面设计.styles import P, S, W, E, BG, CARD, BD, T1, T2, auto_resize_table
from 渠系断面设计.formula_renderer import render_latex_svg, wrap_with_katex, get_svg_height_px

# 计算引擎
try:
    from siphon_models import (
        StructureSegment, SegmentType, SegmentDirection,
        GradientType, InletOutletShape, INLET_SHAPE_COEFFICIENTS,
        TrashRackBarShape, TrashRackParams, V2Strategy,
        COMMON_SEGMENT_TYPES, is_common_type
    )
    from siphon_coefficients import CoefficientService
    from siphon_hydraulics import HydraulicCore
    SIPHON_AVAILABLE = True
except ImportError:
    SIPHON_AVAILABLE = False


_RACK_BAR_COLORS = [
    QColor(231, 76,  60),
    QColor(230, 126, 34),
    QColor(241, 196, 15),
    QColor( 46, 204, 113),
    QColor( 26, 188, 156),
    QColor( 52, 152, 219),
    QColor(155,  89, 182),
]


def _msg(parent, title, text, level="warning"):
    """统一消息提示"""
    w = parent.window() if parent else parent
    if level == "error":
        InfoBar.error(title, text, parent=w, duration=4000, position=InfoBarPosition.TOP)
    elif level == "success":
        InfoBar.success(title, text, parent=w, duration=3000, position=InfoBarPosition.TOP)
    else:
        InfoBar.warning(title, text, parent=w, duration=3000, position=InfoBarPosition.TOP)


# ============================================================
# 1. 进水口形状选择对话框
# ============================================================
class InletShapeDialog(QDialog):
    """进水口形状设置（表L.1.4-2）"""

    def __init__(self, parent, segment):
        super().__init__(parent)
        self.setWindowTitle("进水口形状设置")
        self.result = None
        self.segment = segment
        self._build_ui()
        self.adjustSize()
        self.setMinimumSize(self.sizeHint())

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        # 标题
        title = QLabel("根据表L.1.4-2选择进水口形状")
        title.setStyleSheet(f"font-size:13px;font-weight:bold;color:{T1};")
        lay.addWidget(title)

        # 形状选择
        grp = QGroupBox("进水口形状")
        gl = QVBoxLayout(grp)
        self._shape_group = QButtonGroup(self)

        if not SIPHON_AVAILABLE:
            gl.addWidget(QLabel("计算引擎未加载"))
            lay.addWidget(grp)
            return

        shapes_info = [
            (InletOutletShape.FULLY_ROUNDED, "ξ = 0.05 ~ 0.10"),
            (InletOutletShape.SLIGHTLY_ROUNDED, "ξ = 0.20 ~ 0.25"),
            (InletOutletShape.NOT_ROUNDED, "ξ = 0.50"),
        ]
        current = self.segment.inlet_shape if self.segment.inlet_shape else InletOutletShape.SLIGHTLY_ROUNDED

        for i, (shape, coeff_text) in enumerate(shapes_info):
            row = QHBoxLayout()
            rb = QRadioButton(shape.value)
            rb.setProperty("shape", shape)
            if shape == current:
                rb.setChecked(True)
            self._shape_group.addButton(rb, i)
            row.addWidget(rb)
            lbl = QLabel(coeff_text)
            lbl.setStyleSheet(f"color:{T2};")
            row.addWidget(lbl)
            row.addStretch()
            gl.addLayout(row)

        self._shape_group.buttonClicked.connect(self._on_shape_changed)
        lay.addWidget(grp)

        # 系数输入
        cgrp = QGroupBox("局部阻力系数 ξ")
        cgl = QGridLayout(cgrp)
        cgl.addWidget(QLabel("系数值:"), 0, 0)
        self.edit_xi = LineEdit()
        self.edit_xi.setFixedWidth(100)
        cgl.addWidget(self.edit_xi, 0, 1)
        self.lbl_range = QLabel("")
        self.lbl_range.setStyleSheet(f"color:{T2};font-size:11px;")
        cgl.addWidget(self.lbl_range, 1, 0, 1, 3)
        self._inlet_formula_view = QWebEngineView()
        self._inlet_formula_view.setMinimumHeight(36)
        self._inlet_formula_view.setStyleSheet(
            "border:1px solid #E3ECF9; border-radius:8px; background:#F8F9FE;")
        self._inlet_formula_view.setFixedHeight(0)
        cgl.addWidget(self._inlet_formula_view, 2, 0, 1, 3)
        lay.addWidget(cgrp)

        # 加载当前值
        cur_xi = self.segment.xi_user if self.segment.xi_user is not None else self.segment.xi_calc
        if cur_xi is not None:
            self.edit_xi.setText(f"{cur_xi:.4f}")
        else:
            self._update_default_xi()
        self._update_range_hint()
        self._update_inlet_formula()

        # 按钮
        blay = QHBoxLayout()
        blay.addStretch()
        btn_ok = PrimaryPushButton("确定")
        btn_ok.clicked.connect(self._on_ok)
        btn_cancel = PushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        blay.addWidget(btn_ok)
        blay.addWidget(btn_cancel)
        lay.addLayout(blay)

    def _get_selected_shape(self):
        btn = self._shape_group.checkedButton()
        return btn.property("shape") if btn else None

    def _on_shape_changed(self):
        self._update_default_xi()
        self._update_range_hint()
        self._update_inlet_formula()

    def _update_default_xi(self):
        shape = self._get_selected_shape()
        if shape and shape in INLET_SHAPE_COEFFICIENTS:
            r = INLET_SHAPE_COEFFICIENTS[shape]
            self.edit_xi.setText(f"{sum(r)/2:.4f}")

    def _update_range_hint(self):
        shape = self._get_selected_shape()
        if shape and shape in INLET_SHAPE_COEFFICIENTS:
            r = INLET_SHAPE_COEFFICIENTS[shape]
            if r[0] == r[1]:
                self.lbl_range.setText(f"建议值: {r[0]:.2f}")
            else:
                self.lbl_range.setText(f"建议范围: {r[0]:.2f} ~ {r[1]:.2f}")

    def _update_inlet_formula(self):
        shape = self._get_selected_shape()
        if not shape or shape not in INLET_SHAPE_COEFFICIENTS:
            self._inlet_formula_view.setFixedHeight(0)
            self._inlet_formula_view.setHtml("")
            return
        r = INLET_SHAPE_COEFFICIENTS[shape]
        xi_val = sum(r) / 2
        shape_name = shape.value if hasattr(shape, 'value') else str(shape)
        latex = (f"\\xi_{{\\text{{进}}}} = {xi_val:.4f}"
                 f" \\quad \\text{{(查表 L.1.4-2，{shape_name})}}")
        svg = render_latex_svg(latex, fontsize=14)
        if svg:
            h = get_svg_height_px(svg, padding=16)
            self._inlet_formula_view.setFixedHeight(h)
            body = f'<div style="display:flex;align-items:center;justify-content:center;height:100%;">{svg}</div>'
            self._inlet_formula_view.setHtml(wrap_with_katex(body, extra_css=(
                "html,body{margin:0;padding:0;height:100%;background:transparent;}")))
        else:
            self._inlet_formula_view.setFixedHeight(0)
            self._inlet_formula_view.setHtml("")

    def _on_ok(self):
        shape = self._get_selected_shape()
        if not shape:
            return
        try:
            xi = float(self.edit_xi.text())
        except ValueError:
            _msg(self, "输入错误", "系数格式错误", "error")
            return
        self.result = StructureSegment(
            segment_type=SegmentType.INLET,
            locked=self.segment.locked,
            coordinates=self.segment.coordinates,
            inlet_shape=shape,
            xi_user=xi,
            direction=self.segment.direction
        )
        self.accept()

    def keyPressEvent(self, event):
        """阻止 ESC 键关闭窗口"""
        if event.key() == Qt.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)


# ============================================================
# 2. 出水口局部阻力系数对话框
# ============================================================
class OutletShapeDialog(QDialog):
    """出水口系数 ξc = (1 - ωg/ωq)²"""

    _SECTION_CATEGORIES = {
        '明渠-梯形': 'trapezoidal', '明渠-矩形': 'rectangular',
        '渡槽-矩形': 'rectangular', '矩形暗涵': 'rectangular',
        '明渠-圆形': 'circular', '隧洞-圆形': 'circular',
        '渡槽-U形': 'u_shape', '隧洞-圆拱直墙型': 'arch_wall',
        '隧洞-马蹄形Ⅰ型': 'horseshoe', '隧洞-马蹄形Ⅱ型': 'horseshoe',
    }

    def __init__(self, parent, segment, Q=10.0, v=2.0, downstream_params=None):
        super().__init__(parent)
        self.setWindowTitle("出水口局部阻力系数")
        self.setMinimumSize(540, 520)
        self.resize(580, 580)
        self.result = None
        self.segment = segment
        self.Q, self.v = Q, v
        self.omega_g = Q / v if v > 0 else 0
        self.downstream_params = downstream_params or {}
        self._ds_type_str = self.downstream_params.get('type', '') or ''
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        # 标题
        tl = QHBoxLayout()
        t1 = QLabel(f"流入{self._ds_type_str or '明渠'}  " if self._ds_type_str else "流入明渠  ")
        t1.setStyleSheet("font-size:13px;font-weight:bold;")
        tl.addWidget(t1)
        t2 = QLabel("ξc = (1 - ωg/ωq)²")
        t2.setStyleSheet(f"font-size:13px;color:{P};")
        tl.addWidget(t2)
        tl.addStretch()
        lay.addLayout(tl)

        # 管道信息
        grp = QGroupBox("下游断面参数")
        gl = QVBoxLayout(grp)
        gl.addWidget(QLabel(f"管道断面积 ωg = Q/v = {self.Q:.2f}/{self.v:.2f} = {self.omega_g:.4f} m²"))
        if self._ds_type_str:
            src = QLabel(f"[已从表格自动读取: {self._ds_type_str}]")
            src.setStyleSheet(f"color:{S};")
            gl.addWidget(src)

        # 类型选择
        trow = QHBoxLayout()
        trow.addWidget(QLabel("下游断面类型:"))
        self.combo_type = ComboBox()
        self.combo_type.addItems(list(self._SECTION_CATEGORIES.keys()))
        if self._ds_type_str in self._SECTION_CATEGORIES:
            self.combo_type.setCurrentText(self._ds_type_str)
        else:
            self.combo_type.setCurrentText('明渠-梯形')
        self.combo_type.currentTextChanged.connect(self._on_type_changed)
        trow.addWidget(self.combo_type)
        trow.addStretch()
        gl.addLayout(trow)

        # 参数输入区
        self._pframe = QGridLayout()
        self._entries = {}
        self._labels = {}
        params_def = [
            ('B', '下游底宽 B (m):', self.downstream_params.get('B'), '3.0'),
            ('h', '下游水深 h (m):', self.downstream_params.get('h'), '2.0'),
            ('m', '坡比 m:', self.downstream_params.get('m'), '0'),
            ('D', '下游直径 D (m):', self.downstream_params.get('D'), '1.0'),
            ('R', '下游半径 R (m):', self.downstream_params.get('R'), '0.5'),
        ]
        for i, (key, label, auto_val, default) in enumerate(params_def):
            lbl = QLabel(label)
            self._labels[key] = lbl
            self._pframe.addWidget(lbl, i, 0)
            ed = LineEdit()
            ed.setFixedWidth(90)
            if auto_val is not None and (auto_val != 0 or key == 'm'):
                ed.setText(str(auto_val))
            else:
                ed.setText(default)
            ed.textChanged.connect(self._on_param_changed)
            self._entries[key] = ed
            self._pframe.addWidget(ed, i, 1)
        gl.addLayout(self._pframe)
        lay.addWidget(grp)

        # 计算结果
        rgrp = QGroupBox("计算结果")
        rl = QVBoxLayout(rgrp)
        self.lbl_omega_q = QLabel("下游断面面积 ωq = --")
        self.lbl_omega_q.setStyleSheet(f"color:{T2};")
        rl.addWidget(self.lbl_omega_q)
        self.lbl_calc_xi = QLabel("ξc = (1 - ωg/ωq)² = --")
        self.lbl_calc_xi.setStyleSheet(f"color:{S};font-weight:bold;font-size:12px;")
        rl.addWidget(self.lbl_calc_xi)
        self._outlet_formula_view = QWebEngineView()
        self._outlet_formula_view.setMinimumHeight(36)
        self._outlet_formula_view.setStyleSheet(
            "border:1px solid #E3ECF9; border-radius:8px; background:#F8F9FE;")
        self._outlet_formula_view.setFixedHeight(0)
        rl.addWidget(self._outlet_formula_view)
        lay.addWidget(rgrp)

        # 系数
        cgrp = QGroupBox("局部阻力系数 ξc")
        cl = QHBoxLayout(cgrp)
        cl.addWidget(QLabel("系数值:"))
        self.edit_xi = LineEdit()
        self.edit_xi.setFixedWidth(100)
        cl.addWidget(self.edit_xi)
        cl.addWidget(QLabel("(可手动修改)"))
        cl.addStretch()
        lay.addWidget(cgrp)

        cur_xi = self.segment.xi_user if self.segment.xi_user is not None else self.segment.xi_calc
        if cur_xi is not None:
            self.edit_xi.setText(f"{cur_xi:.4f}")

        # 按钮
        blay = QHBoxLayout()
        blay.addStretch()
        btn_ok = PrimaryPushButton("确定")
        btn_ok.clicked.connect(self._on_ok)
        btn_cancel = PushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        blay.addWidget(btn_ok)
        blay.addWidget(btn_cancel)
        lay.addLayout(blay)

        self._update_visibility()
        self._on_param_changed()

    def _on_type_changed(self):
        self._update_visibility()
        self._on_param_changed()

    def _update_visibility(self):
        cat = self._SECTION_CATEGORIES.get(self.combo_type.currentText(), 'trapezoidal')
        show = {'B': False, 'h': False, 'm': False, 'D': False, 'R': False}
        if cat == 'trapezoidal':
            show.update({'B': True, 'h': True, 'm': True})
        elif cat == 'rectangular':
            show.update({'B': True, 'h': True})
        elif cat == 'circular':
            show.update({'D': True, 'h': True})
        elif cat == 'u_shape':
            show.update({'R': True, 'h': True})
        elif cat == 'arch_wall':
            show.update({'B': True, 'R': True, 'h': True})
        elif cat == 'horseshoe':
            show.update({'R': True, 'h': True})
        for key in show:
            self._labels[key].setVisible(show[key])
            self._entries[key].setVisible(show[key])

    def _fval(self, key, default=0.0):
        try:
            return float(self._entries[key].text())
        except (ValueError, KeyError):
            return default

    def _on_param_changed(self):
        self._outlet_formula_view.setFixedHeight(0)
        self._outlet_formula_view.setHtml("")
        cat = self._SECTION_CATEGORIES.get(self.combo_type.currentText(), 'trapezoidal')
        h = self._fval('h')
        if h <= 0:
            self.lbl_omega_q.setText("请输入有效水深")
            return

        omega_q = 0
        formula = ""
        if cat == 'trapezoidal':
            B, m = self._fval('B'), self._fval('m')
            if B <= 0: return
            omega_q = (B + m * h) * h
            formula = f"ωq = (B+m×h)×h = ({B:.2f}+{m:.2f}×{h:.2f})×{h:.2f} = {omega_q:.4f} m²"
        elif cat == 'rectangular':
            B = self._fval('B')
            if B <= 0: return
            omega_q = B * h
            formula = f"ωq = B×h = {B:.2f}×{h:.2f} = {omega_q:.4f} m²"
        elif cat == 'circular':
            D = self._fval('D')
            if D <= 0: return
            r = D / 2
            if h >= D:
                omega_q = math.pi * r * r
                formula = f"ωq = πD²/4 = {omega_q:.4f} m² (满流)"
            else:
                cv = max(-1, min(1, (r - h) / r))
                theta = math.acos(cv)
                omega_q = r * r * (theta - math.sin(theta) * math.cos(theta))
                formula = f"ωq = {omega_q:.4f} m² (非满流, θ={math.degrees(theta):.1f}°)"
        elif cat == 'u_shape':
            R = self._fval('R')
            if R <= 0: return
            if h <= R:
                cv = max(-1, min(1, (R - h) / R))
                theta = math.acos(cv)
                omega_q = R * R * (theta - math.sin(theta) * math.cos(theta))
            else:
                omega_q = math.pi * R * R / 2 + 2 * R * (h - R)
            formula = f"ωq = {omega_q:.4f} m²"
        elif cat == 'arch_wall':
            B, R = self._fval('B'), self._fval('R')
            if B <= 0 or R <= 0: return
            wall_h = max(h - R, 0)
            rect_part = B * wall_h
            if h >= wall_h + R:
                arch_part = math.pi * R * R / 2
            else:
                ah = h - wall_h
                if ah > 0:
                    cv = max(-1, min(1, (R - ah) / R))
                    theta = math.acos(cv)
                    arch_part = R * R * (theta - math.sin(theta) * math.cos(theta))
                else:
                    arch_part = 0
            omega_q = rect_part + arch_part
            formula = f"ωq = {omega_q:.4f} m²"
        elif cat == 'horseshoe':
            R = self._fval('R')
            if R <= 0: return
            D = 2 * R
            if h >= D:
                omega_q = math.pi * R * R
            else:
                cv = max(-1, min(1, (R - h) / R))
                theta = math.acos(cv)
                omega_q = R * R * (theta - math.sin(theta) * math.cos(theta))
            formula = f"ωq = {omega_q:.4f} m²"

        self.lbl_omega_q.setText(f"下游断面面积 {formula}")
        if omega_q <= 0:
            self.lbl_calc_xi.setText("ξc = --")
            self._outlet_formula_view.setFixedHeight(0)
            self._outlet_formula_view.setHtml("")
            return
        ratio = self.omega_g / omega_q
        xi_c = (1 - ratio) ** 2
        self.lbl_calc_xi.setText(f"ξc = (1 - {self.omega_g:.4f}/{omega_q:.4f})² = {xi_c:.4f}")
        self.edit_xi.setText(f"{xi_c:.4f}")
        latex = (f"\\xi_c = \\left(1 - \\frac{{\\omega_g}}{{\\omega_q}}\\right)^2"
                 f" = \\left(1 - \\frac{{{self.omega_g:.4f}}}{{{omega_q:.4f}}}\\right)^2"
                 f" = {xi_c:.4f}")
        svg = render_latex_svg(latex, fontsize=14)
        if svg:
            h = get_svg_height_px(svg, padding=16)
            self._outlet_formula_view.setFixedHeight(h)
            body = f'<div style="display:flex;align-items:center;justify-content:center;height:100%;">{svg}</div>'
            self._outlet_formula_view.setHtml(wrap_with_katex(body, extra_css=(
                "html,body{margin:0;padding:0;height:100%;background:transparent;}")))
        else:
            self._outlet_formula_view.setFixedHeight(0)
            self._outlet_formula_view.setHtml("")

    def _on_ok(self):
        try:
            xi = float(self.edit_xi.text())
        except ValueError:
            _msg(self, "输入错误", "系数格式错误", "error")
            return
        self.result = StructureSegment(
            segment_type=SegmentType.OUTLET, locked=self.segment.locked,
            coordinates=self.segment.coordinates, outlet_shape=None,
            xi_user=xi, direction=self.segment.direction
        )
        self.accept()

    def keyPressEvent(self, event):
        """阻止 ESC 键关闭窗口"""
        if event.key() == Qt.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)


# ============================================================
# 3. 拦污栅详细配置对话框
# ============================================================
class TrashRackConfigDialog(QDialog):
    """拦污栅参数（公式L.1.4-2/3）"""

    SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                               '倒虹吸水力计算系统')

    def __init__(self, parent, params=None):
        super().__init__(parent)
        self.setWindowTitle("拦污栅详细参数配置")
        self.setMinimumSize(820, 660)
        self.resize(900, 750)
        self.result = None
        if SIPHON_AVAILABLE:
            self.params = params if params else TrashRackParams()
            self.shape_list = list(TrashRackBarShape)
        else:
            self.params = None
            self.shape_list = []
        self._active_target = 'bar'
        self._build_ui()

    def _build_ui(self):
        if not SIPHON_AVAILABLE:
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel("计算引擎未加载"))
            return

        lay = QHBoxLayout(self)
        lay.setSpacing(8)

        # 左侧参数
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(4, 4, 4, 4)

        # 基础参数
        g1 = QGroupBox("基础参数")
        g1l = QGridLayout(g1)
        g1l.addWidget(QLabel("栅面倾角(度):"), 0, 0)
        self.ed_alpha = LineEdit(); self.ed_alpha.setFixedWidth(80)
        self.ed_alpha.setText(f"{self.params.alpha:.1f}")
        self.ed_alpha.textChanged.connect(self._on_changed)
        g1l.addWidget(self.ed_alpha, 0, 1)
        g1l.addWidget(QLabel("0~180, 默认90"), 0, 2)

        g1l.addWidget(QLabel("计算模式:"), 1, 0)
        mode_w = QWidget()
        mode_lay = QVBoxLayout(mode_w)
        mode_lay.setContentsMargins(0, 2, 0, 2)
        mode_lay.setSpacing(3)
        self._mode_group = QButtonGroup(self)
        self.rb_no_support = QRadioButton("无独立支墩 (公式L.1.4-2)")
        self.rb_has_support = QRadioButton("有独立支墩 (公式L.1.4-3)")
        self._mode_group.addButton(self.rb_no_support, 0)
        self._mode_group.addButton(self.rb_has_support, 1)
        if self.params.has_support:
            self.rb_has_support.setChecked(True)
        else:
            self.rb_no_support.setChecked(True)
        self._mode_group.buttonClicked.connect(self._on_mode)
        mode_lay.addWidget(self.rb_no_support)
        mode_lay.addWidget(self.rb_has_support)
        g1l.addWidget(mode_w, 1, 1, 1, 2)
        ll.addWidget(g1)

        # 栅条参数
        self.g2 = QGroupBox("\u25cf \u6805\u6761\u53c2\u6570")
        self.g2.setStyleSheet("QGroupBox::title { color: #1d4ed8; }")
        g2l = QGridLayout(self.g2)
        g2l.addWidget(QLabel("栅条形状:"), 0, 0)
        self.combo_bar = ComboBox()
        self.combo_bar.addItems([f"{s.value} (β={CoefficientService.get_trash_rack_bar_beta(s):.2f})"
                                  for s in self.shape_list])
        idx = self.shape_list.index(self.params.bar_shape) if self.params.bar_shape in self.shape_list else 0
        self.combo_bar.setCurrentIndex(idx)
        self.combo_bar.currentIndexChanged.connect(self._on_bar_changed)
        g2l.addWidget(self.combo_bar, 0, 1, 1, 2)

        g2l.addWidget(QLabel("栅条厚度 s₁(mm):"), 1, 0)
        self.ed_s1 = LineEdit(); self.ed_s1.setFixedWidth(70)
        self.ed_s1.setText(f"{self.params.s1:.1f}")
        self.ed_s1.textChanged.connect(self._on_changed)
        g2l.addWidget(self.ed_s1, 1, 1)

        g2l.addWidget(QLabel("栅条间距 b₁(mm):"), 2, 0)
        self.ed_b1 = LineEdit(); self.ed_b1.setFixedWidth(70)
        self.ed_b1.setText(f"{self.params.b1:.1f}")
        self.ed_b1.textChanged.connect(self._on_changed)
        g2l.addWidget(self.ed_b1, 2, 1)

        self.lbl_ratio1 = QLabel("s₁/b₁: --")
        g2l.addWidget(self.lbl_ratio1, 3, 0, 1, 2)
        ll.addWidget(self.g2)

        # 支墩参数
        self.g3 = QGroupBox("\u25cf \u652f\u58a9\u53c2\u6570")
        self.g3.setStyleSheet("QGroupBox::title { color: #b45309; }")
        g3l = QGridLayout(self.g3)
        g3l.addWidget(QLabel("支墩形状:"), 0, 0)
        self.combo_sup = ComboBox()
        self.combo_sup.addItems([f"{s.value} (β={CoefficientService.get_trash_rack_bar_beta(s):.2f})"
                                  for s in self.shape_list])
        sidx = self.shape_list.index(self.params.support_shape) if self.params.support_shape in self.shape_list else 0
        self.combo_sup.setCurrentIndex(sidx)
        self.combo_sup.currentIndexChanged.connect(self._on_sup_changed)
        g3l.addWidget(self.combo_sup, 0, 1, 1, 2)

        g3l.addWidget(QLabel("支墩厚度 s₂(mm):"), 1, 0)
        self.ed_s2 = LineEdit(); self.ed_s2.setFixedWidth(70)
        self.ed_s2.setText(f"{self.params.s2:.1f}")
        self.ed_s2.textChanged.connect(self._on_changed)
        g3l.addWidget(self.ed_s2, 1, 1)

        g3l.addWidget(QLabel("支墩净距 b₂(mm):"), 2, 0)
        self.ed_b2 = LineEdit(); self.ed_b2.setFixedWidth(70)
        self.ed_b2.setText(f"{self.params.b2:.1f}")
        self.ed_b2.textChanged.connect(self._on_changed)
        g3l.addWidget(self.ed_b2, 2, 1)

        self.lbl_ratio2 = QLabel("s₂/b₂: --")
        g3l.addWidget(self.lbl_ratio2, 3, 0, 1, 2)
        ll.addWidget(self.g3)

        # 结果
        rg = QGroupBox("计算结果")
        rl = QVBoxLayout(rg)
        rl.setSpacing(8)
        self.cb_manual = CheckBox("强制手动输入")
        self.cb_manual.setChecked(self.params.manual_mode)
        self.cb_manual.stateChanged.connect(self._on_manual)
        rl.addWidget(self.cb_manual)
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("手动 ξs:"))
        self.ed_manual = LineEdit(); self.ed_manual.setFixedWidth(80)
        self.ed_manual.setEnabled(self.params.manual_mode)
        if self.params.manual_mode:
            self.ed_manual.setText(f"{self.params.manual_xi:.4f}")
        self.ed_manual.textChanged.connect(self._on_changed)
        mrow.addWidget(self.ed_manual)
        mrow.addStretch()
        rl.addLayout(mrow)
        # 结果值（大字突出）
        self.lbl_result = QLabel("--")
        self.lbl_result.setStyleSheet(f"font-size:20px;font-weight:bold;color:{P};padding:4px 0;")
        rl.addWidget(self.lbl_result)
        # 公式卡片（独立容器，固定尺寸防止布局抖动）
        self.formula_view = QWebEngineView()
        self.formula_view.setMinimumHeight(40)
        self.formula_view.setStyleSheet(
            "border:1px solid #E3ECF9; border-radius:8px; background:#F8F9FE;"
        )
        rl.addWidget(self.formula_view)
        ll.addWidget(rg)

        # 按钮行（放在 GroupBox 外部，避免重叠）
        brow = QHBoxLayout()
        btn_ok = PrimaryPushButton("确定"); btn_ok.clicked.connect(self._on_ok)
        btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(self.reject)
        brow.addWidget(btn_ok); brow.addWidget(btn_cancel); brow.addStretch()
        ll.addLayout(brow)

        lay.addWidget(left, stretch=1)

        # 右侧参考表
        right = QWidget()
        rlayout = QVBoxLayout(right)
        rlayout.setContentsMargins(4, 4, 4, 4)

        fig_grp = QGroupBox("栅条形状示意图 (图L.1.4-1)")
        fig_lay = QVBoxLayout(fig_grp)
        self.img_label = QLabel("(双击可查看大图)")
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setFixedHeight(240)
        self.img_label.setStyleSheet("background:white;border:1px solid #ddd;")
        self.img_label.mouseDoubleClickEvent = self._on_image_double_click
        fig_lay.addWidget(self.img_label)
        hint_label = QLabel("💡 双击图片可放大查看")
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setStyleSheet("color: #555; font-size: 12px; padding: 2px 0;")
        fig_lay.addWidget(hint_label)
        rlayout.addWidget(fig_grp)
        self._img_path = os.path.join(self.SCRIPT_DIR, "resources", "图L.1.4-1.png")
        self._load_image()

        self.tbl_grp = QGroupBox("形状系数表 (表L.1.4-1)  → 栅条形状")
        tl2 = QVBoxLayout(self.tbl_grp)
        self.ref_table = QTableWidget(len(self.shape_list), 3)
        self.ref_table.setHorizontalHeaderLabels(["", "形状名称", "系数 β"])
        _hh = self.ref_table.horizontalHeader()
        _hh.setSectionResizeMode(0, QHeaderView.Fixed)
        _hh.setSectionResizeMode(1, QHeaderView.Stretch)
        _hh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.ref_table.setColumnWidth(0, 6)
        self.ref_table.setColumnWidth(2, 66)
        self.ref_table.verticalHeader().setVisible(False)
        self.ref_table.verticalHeader().setDefaultSectionSize(30)
        self.ref_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.ref_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.ref_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.ref_table.setCursor(Qt.PointingHandCursor)
        self.ref_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.ref_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #c8d6e5;
                border-radius: 6px;
                gridline-color: #edf1f5;
                background: white;
            }
            QHeaderView::section {
                background: #1e3a5f;
                color: white;
                font-weight: bold;
                padding: 5px 8px;
                border: none;
            }
            QTableWidget::item {
                padding: 2px 8px;
            }
            QTableWidget::item:selected { background: transparent; color: black; }
        """)
        _betas = [CoefficientService.get_trash_rack_bar_beta(s) for s in self.shape_list]
        _bmax, _bmin = max(_betas), min(_betas)
        _brange = _bmax - _bmin if _bmax != _bmin else 1.0
        self._name_items = []
        self._beta_containers = []
        self._beta_badges = []
        self._beta_heatmap = []
        _ODD = QColor(248, 250, 252)
        _WHT = QColor(255, 255, 255)
        for i, s in enumerate(self.shape_list):
            # Col 0: 6px thin color strip
            _it0 = QTableWidgetItem()
            _it0.setFlags(Qt.ItemIsEnabled)
            self.ref_table.setItem(i, 0, _it0)
            _strip = QWidget()
            if i < len(_RACK_BAR_COLORS):
                _strip.setStyleSheet(f"background:{_RACK_BAR_COLORS[i].name()};")
            _strip.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.ref_table.setCellWidget(i, 0, _strip)

            # Col 1: shape name with alternating background
            _ni = QTableWidgetItem(s.value)
            _ni.setBackground(_ODD if i % 2 == 0 else _WHT)
            self.ref_table.setItem(i, 1, _ni)
            self._name_items.append(_ni)

            # Col 2: beta rounded badge with heatmap color
            _it2 = QTableWidgetItem()
            _it2.setFlags(Qt.ItemIsEnabled)
            self.ref_table.setItem(i, 2, _it2)
            _t = (_betas[i] - _bmin) / _brange
            _cr, _cg, _cb = int(70*_t+185), int(-50*_t+230), int(-45*_t+185)
            _hm = f"rgb({_cr},{_cg},{_cb})"
            self._beta_heatmap.append(_hm)
            _ctn = QWidget()
            _ctn.setStyleSheet(f"background:{(_ODD if i % 2 == 0 else _WHT).name()};")
            _ctn.setAttribute(Qt.WA_TransparentForMouseEvents)
            _cl = QHBoxLayout(_ctn)
            _cl.setContentsMargins(4, 2, 4, 2)
            _cl.setAlignment(Qt.AlignCenter)
            _bdg = QLabel(f"{_betas[i]:.2f}")
            _bdg.setAlignment(Qt.AlignCenter)
            _bdg.setAttribute(Qt.WA_TransparentForMouseEvents)
            _bdg.setStyleSheet(
                f"background:{_hm}; border-radius:4px;"
                f"padding:2px 10px; font-weight:bold; font-size:12px;"
            )
            _cl.addWidget(_bdg)
            self.ref_table.setCellWidget(i, 2, _ctn)
            self._beta_containers.append(_ctn)
            self._beta_badges.append(_bdg)
        self.ref_table.setColumnWidth(0, 6)
        self.ref_table.setColumnWidth(2, 72)
        self.ref_table.cellClicked.connect(self._on_table_clicked)
        tl2.addWidget(self.ref_table)
        legend_row = QHBoxLayout()
        bar_dot = QLabel("● 栅条选中")
        bar_dot.setStyleSheet("color:#1d4ed8; font-size:11px;")
        sup_dot = QLabel("● 支墩选中")
        sup_dot.setStyleSheet("color:#b45309; font-size:11px;")
        both_dot = QLabel("● 同时选中")
        both_dot.setStyleSheet("color:#7c3aed; font-size:11px;")
        legend_row.addWidget(bar_dot)
        legend_row.addSpacing(12)
        legend_row.addWidget(sup_dot)
        legend_row.addSpacing(12)
        legend_row.addWidget(both_dot)
        legend_row.addStretch()
        tl2.addLayout(legend_row)
        rlayout.addWidget(self.tbl_grp)

        lay.addWidget(right, stretch=1)

        self._on_mode()
        self._on_manual()
        self._update_preview()
        self._sync_table_highlight()

    def _load_image(self):
        if os.path.exists(self._img_path):
            pm = QPixmap(self._img_path)
            if not pm.isNull():
                lw = max(self.img_label.width() - 10, 200)
                lh = max(self.img_label.height() - 10, 160)
                self.img_label.setPixmap(pm.scaled(
                    lw, lh,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation))
                return
        self.img_label.setText("图片未找到")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_img_path'):
            self._load_image()

    def _on_image_double_click(self, event):
        """双击图片弹出大图窗口"""
        if not os.path.exists(self._img_path):
            _msg(self, "提示", "图片文件未找到", "warning")
            return
        pm = QPixmap(self._img_path)
        if pm.isNull():
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("栅条形状示意图 (图 L.1.4-1)")
        screen = self.screen().availableGeometry()
        max_w, max_h = int(screen.width() * 0.8), int(screen.height() * 0.8)
        scaled = pm.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        dlg.resize(scaled.width() + 40, scaled.height() + 60)
        vl = QVBoxLayout(dlg)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setPixmap(scaled)
        vl.addWidget(lbl)
        btn = PushButton("关闭")
        btn.clicked.connect(dlg.accept)
        vl.addWidget(btn, alignment=Qt.AlignCenter)
        dlg.exec()

    def _on_table_clicked(self, row, _col):
        """右侧表格点击 → 根据活跃目标同步对应ComboBox"""
        if 0 <= row < len(self.shape_list):
            if self._active_target == 'sup' and self.rb_has_support.isChecked():
                self.combo_sup.setCurrentIndex(row)
            else:
                self.combo_bar.setCurrentIndex(row)

    def _on_bar_changed(self, *_):
        """栅条ComboBox变化 → 记录活跃目标 + 双色高亮 + 更新计算"""
        self._active_target = 'bar'
        self._sync_table_highlight()
        self._update_tbl_title()
        self._on_changed()

    def _on_sup_changed(self, *_):
        """支墩ComboBox变化 → 记录活跃目标 + 双色高亮 + 更新计算"""
        self._active_target = 'sup'
        self._sync_table_highlight()
        self._update_tbl_title()
        self._on_changed()

    def _sync_table_highlight(self):
        """双色高亮：蓝=栅条当前选择，琥珀=支墩当前选择（col0永久保持渐变色条）"""
        if not hasattr(self, '_name_items'):
            return
        manual = self.cb_manual.isChecked()
        bar_idx = self.combo_bar.currentIndex() if not manual else -1
        sup_idx = (self.combo_sup.currentIndex() if self.rb_has_support.isChecked() and not manual else -1)
        BAR_COLOR  = QColor(219, 234, 254)
        SUP_COLOR  = QColor(254, 243, 199)
        BOTH_COLOR = QColor(233, 213, 255)
        WHITE      = QColor(255, 255, 255)
        ODD_BG     = QColor(248, 250, 252)
        for i in range(self.ref_table.rowCount()):
            is_bar = (i == bar_idx)
            is_sup = (i == sup_idx)
            if is_bar and is_sup:
                bg = BOTH_COLOR
            elif is_bar:
                bg = BAR_COLOR
            elif is_sup:
                bg = SUP_COLOR
            else:
                bg = ODD_BG if i % 2 == 0 else WHITE
            # Col 1: name item background
            if i < len(self._name_items):
                self._name_items[i].setBackground(bg)
            # Col 2: container background (badge keeps its heatmap color)
            if i < len(self._beta_containers):
                self._beta_containers[i].setStyleSheet(f"background:{bg.name()};")

    def _update_tbl_title(self):
        """根据活跃目标动态更新表格标题"""
        if not hasattr(self, 'tbl_grp'):
            return
        if self._active_target == 'sup' and self.rb_has_support.isChecked():
            self.tbl_grp.setTitle("形状系数表 (表L.1.4-1)  → 支墩形状")
        else:
            self.tbl_grp.setTitle("形状系数表 (表L.1.4-1)  → 栅条形状")

    def _on_mode(self, *_):
        manual = self.cb_manual.isChecked()
        en = self.rb_has_support.isChecked() and not manual  # B4: _on_mode 不在手动模式下重新启用 g3
        self.g3.setEnabled(en)
        if not en and self._active_target == 'sup':
            self._active_target = 'bar'
        self._sync_table_highlight()
        self._update_tbl_title()
        self._on_changed()

    def _on_manual(self):
        manual = self.cb_manual.isChecked()
        if manual:
            xi_auto = self._calc_xi_auto()
            if xi_auto is not None and xi_auto > 0:
                self.ed_manual.setText(f"{xi_auto:.4f}")
        self.ed_manual.setEnabled(manual)
        self.g2.setEnabled(not manual)
        self.g3.setEnabled(not manual and self.rb_has_support.isChecked())
        if manual:
            self._active_target = 'bar'
            self._sync_table_highlight()
            self._update_tbl_title()
        self._on_changed()

    def _on_changed(self, *_):
        self._update_ratios()
        self._update_preview()

    def _calc_xi_auto(self):
        """计算自动模式ξs（忽略手动开关），用于切换手动模式时预填"""
        try:
            alpha = float(self.ed_alpha.text() or 90)
            bi = self.combo_bar.currentIndex()
            bar_shape = self.shape_list[bi] if 0 <= bi < len(self.shape_list) else TrashRackBarShape.RECTANGULAR
            si = self.combo_sup.currentIndex()
            sup_shape = self.shape_list[si] if 0 <= si < len(self.shape_list) else TrashRackBarShape.RECTANGULAR
            temp = TrashRackParams(
                alpha=alpha, has_support=self.rb_has_support.isChecked(),
                bar_shape=bar_shape,
                beta1=CoefficientService.get_trash_rack_bar_beta(bar_shape),
                s1=float(self.ed_s1.text() or 0), b1=float(self.ed_b1.text() or 0),
                support_shape=sup_shape,
                beta2=CoefficientService.get_trash_rack_bar_beta(sup_shape),
                s2=float(self.ed_s2.text() or 0), b2=float(self.ed_b2.text() or 0),
                manual_mode=False,
            )
            return CoefficientService.calculate_trash_rack_xi(temp)
        except Exception:
            return None

    def _update_ratios(self):
        try:
            s1, b1 = float(self.ed_s1.text() or 0), float(self.ed_b1.text() or 1)
            self.lbl_ratio1.setText(f"s₁/b₁: {s1/b1:.4f}" if b1 > 0 else "s₁/b₁: 错误")
        except ValueError:
            self.lbl_ratio1.setText("s₁/b₁: --")
        try:
            s2, b2 = float(self.ed_s2.text() or 0), float(self.ed_b2.text() or 1)
            self.lbl_ratio2.setText(f"s₂/b₂: {s2/b2:.4f}" if b2 > 0 else "s₂/b₂: 错误")
        except ValueError:
            self.lbl_ratio2.setText("s₂/b₂: --")

    def _collect(self):
        try:
            alpha = float(self.ed_alpha.text() or 90)
            bi = self.combo_bar.currentIndex()
            bar_shape = self.shape_list[bi] if 0 <= bi < len(self.shape_list) else TrashRackBarShape.RECTANGULAR
            si = self.combo_sup.currentIndex()
            sup_shape = self.shape_list[si] if 0 <= si < len(self.shape_list) else TrashRackBarShape.RECTANGULAR
            return TrashRackParams(
                alpha=alpha, has_support=self.rb_has_support.isChecked(),
                bar_shape=bar_shape,
                beta1=CoefficientService.get_trash_rack_bar_beta(bar_shape),
                s1=float(self.ed_s1.text() or 0), b1=float(self.ed_b1.text() or 0),
                support_shape=sup_shape,
                beta2=CoefficientService.get_trash_rack_bar_beta(sup_shape),
                s2=float(self.ed_s2.text() or 0), b2=float(self.ed_b2.text() or 0),
                manual_mode=self.cb_manual.isChecked(),
                manual_xi=float(self.ed_manual.text() or 0) if self.cb_manual.isChecked() else 0
            )
        except ValueError:
            return None

    def _update_preview(self):
        params = self._collect()
        if params is None:
            self.lbl_result.setText("请输入参数")
            return
        if not params.manual_mode:
            if params.b1 <= 0 or params.s1 <= 0:
                self.lbl_result.setText("请输入栅条参数")
                return
            if params.has_support and (params.b2 <= 0 or params.s2 <= 0):
                self.lbl_result.setText("请输入支墩参数")
                return
        xi = CoefficientService.calculate_trash_rack_xi(params)
        self.lbl_result.setText(f"\u03bcs = {xi:.4f}")
        if not params.manual_mode and params.b1 > 0 and params.s1 > 0:
            formula_label = ("\\text{公式 L.1.4-3：}" if params.has_support and params.b2 > 0 and params.s2 > 0
                             else "\\text{公式 L.1.4-2：}")
            latex = (f"{formula_label}\\xi_s = {params.beta1:.2f} \\times "
                     f"\\left(\\frac{{{params.s1:.0f}}}{{{params.b1:.0f}}}\\right)"
                     f"^{{\\frac{{4}}{{3}}}} \\times "
                     f"\\sin({params.alpha:.0f}^{{\\circ}})")
            if params.has_support and params.b2 > 0 and params.s2 > 0:
                latex += (f" + {params.beta2:.2f} \\times "
                          f"\\left(\\frac{{{params.s2:.0f}}}{{{params.b2:.0f}}}\\right)"
                          f"^{{\\frac{{4}}{{3}}}}")
            latex += f" = {xi:.4f}"
            svg = render_latex_svg(latex, fontsize=14)
            if svg:
                h = get_svg_height_px(svg, padding=16)
                self.formula_view.setFixedHeight(h)
                body = (f'<div style="display:flex;align-items:center;'
                        f'justify-content:center;height:100%;">{svg}</div>')
                html = wrap_with_katex(body, extra_css=(
                    "html,body{margin:0;padding:0;height:100%;"
                    "background:transparent;}"))
                self.formula_view.setHtml(html)
            else:
                self.formula_view.setFixedHeight(0)
                self.formula_view.setHtml("")
        else:
            self.formula_view.setFixedHeight(0)
            self.formula_view.setHtml("")

    def _on_ok(self):
        params = self._collect()
        if params is None:
            _msg(self, "输入错误", "请检查参数格式", "error")
            return
        if not params.manual_mode:
            if params.b1 <= 0 or params.s1 <= 0:
                _msg(self, "输入错误", "栅条厚度和间距必须大于 0", "error")
                return
            if params.has_support and params.b2 <= 0:
                _msg(self, "输入错误", "支墩净距 b₂ 必须大于 0", "error")
                return
        self.result = params
        self.accept()

    def keyPressEvent(self, event):
        """阻止 ESC 键关闭窗口"""
        if event.key() == Qt.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)


# ============================================================
# 4. 结构段编辑对话框（双栏卡片式）
# ============================================================
class SegmentEditDialog(QDialog):
    """管身段编辑 — 左栏输入 / 右栏实时结果 + 公式"""

    # 结果卡片样式
    _CARD_SS = (
        "QFrame { background: #FFFFFF; border: 1px solid #E8ECF0;"
        " border-radius: 8px; }"
    )
    _CARD_HL_SS = (
        "QFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
        " stop:0 #F0F7FF, stop:1 #FFFFFF);"
        " border: 1px solid #1976D2; border-radius: 8px; }"
    )
    _LABEL_SS = "font-size:11px; color:#888;"
    _VALUE_SS = "font-size:20px; font-weight:700; color:#1976D2;"
    _HINT_SS  = "font-size:11px; color:#aaa;"
    _HINT_BLUE_SS = "font-size:11px; color:#1976D2;"

    def __init__(self, parent, segment=None, Q=10.0, v=2.0, direction=None):
        super().__init__(parent)
        self.setWindowTitle("编辑结构段")
        self.result = None
        self.segment = segment
        self._direction = direction  # 外部传入的方向（用于区分平面/纵断面）
        self._Q, self._v = Q, v
        self._D_theory = math.sqrt(4 * Q / (math.pi * v)) if Q > 0 and v > 0 else 0
        self._user_modified_xi = False
        self._loading = False
        self._build_ui()
        if segment:
            self._load(segment)

    # ---- 构建 UI ----
    def _build_ui(self):
        if not SIPHON_AVAILABLE:
            QVBoxLayout(self).addWidget(QLabel("计算引擎未加载"))
            return

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 顶部标题栏 ----
        header = QFrame()
        header.setFixedHeight(42)
        header.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            " stop:0 #1976D2, stop:1 #1565C0); }"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        h_title = QLabel("编辑结构段")
        h_title.setStyleSheet("font-size:14px; font-weight:600; color:#FFFFFF;")
        hl.addWidget(h_title)
        hl.addStretch()
        self.lbl_dir = QLabel("纵断面")
        self.lbl_dir.setStyleSheet(
            "font-size:11px; color:#FFFFFF; background:rgba(255,255,255,0.2);"
            " padding:2px 10px; border-radius:10px;"
        )
        hl.addWidget(self.lbl_dir)
        root.addWidget(header)

        # ---- 双栏主体 ----
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # == 左栏：输入 ==
        left = QWidget()
        left.setStyleSheet("QWidget { background: #FFFFFF; }")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(18, 14, 14, 10)
        ll.setSpacing(4)

        sec_lbl = QLabel("几何参数")
        sec_lbl.setStyleSheet(
            f"font-size:12px; font-weight:700; color:{P}; letter-spacing:1px;"
            " padding-left:8px; border-left:3px solid #1976D2;"
        )
        ll.addWidget(sec_lbl)
        ll.addSpacing(4)

        # 类型
        self.combo_type = ComboBox()
        types = [st.value for st in SegmentType if st not in (SegmentType.INLET, SegmentType.OUTLET)]
        self.combo_type.addItems(types)
        self.combo_type.setCurrentText(SegmentType.STRAIGHT.value)
        self.combo_type.currentTextChanged.connect(self._on_type)
        ll.addLayout(self._form_row("类型", self.combo_type))

        # 长度
        self.ed_length = LineEdit()
        self.ed_length.setText("0.0")
        self.ed_length.setFixedWidth(130)
        self.ed_length.textChanged.connect(self._on_geom)
        self._row_length = self._form_row_with_unit("长度 L", self.ed_length, "m")
        ll.addLayout(self._row_length)

        # 半径
        self.ed_radius = LineEdit()
        self.ed_radius.setText("0.0")
        self.ed_radius.setFixedWidth(130)
        self.ed_radius.textChanged.connect(self._on_geom)
        self._row_radius = self._form_row_with_unit("拐弯半径 R", self.ed_radius, "m")
        ll.addLayout(self._row_radius)

        # 角度
        self.ed_angle = LineEdit()
        self.ed_angle.setText("0.0")
        self.ed_angle.setFixedWidth(130)
        self.ed_angle.textChanged.connect(self._on_geom)
        self._row_angle = self._form_row_with_unit("拐角 θ", self.ed_angle, "°")
        ll.addLayout(self._row_angle)

        # 高程（水平排列）
        self._elev_widget = QWidget()
        elev_lay = QHBoxLayout(self._elev_widget)
        elev_lay.setContentsMargins(0, 2, 0, 2)
        elev_lay.setSpacing(10)
        self.ed_start_elev = LineEdit()
        self.ed_start_elev.setFixedWidth(90)
        self.ed_start_elev.textChanged.connect(self._on_geom)
        elev_lay.addLayout(self._mini_form("起点高程", self.ed_start_elev, "m"))
        self.ed_end_elev = LineEdit()
        self.ed_end_elev.setFixedWidth(90)
        self.ed_end_elev.textChanged.connect(self._on_geom)
        elev_lay.addLayout(self._mini_form("终点高程", self.ed_end_elev, "m"))
        elev_lay.addStretch()
        ll.addWidget(self._elev_widget)

        ll.addStretch()
        body.addWidget(left, 1)

        # == 左右分隔线 ==
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #EEE;")
        body.addWidget(sep)

        # == 右栏：结果 ==
        right = QWidget()
        right.setStyleSheet("QWidget { background: #FAFBFD; }")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(14, 14, 18, 10)
        rl.setSpacing(8)

        res_lbl = QLabel("计算结果")
        res_lbl.setStyleSheet(
            f"font-size:12px; font-weight:700; color:{P}; letter-spacing:1px;"
            " padding-left:8px; border-left:3px solid #1976D2;"
        )
        rl.addWidget(res_lbl)

        # 空间长度卡片
        self._card_sp = QFrame()
        self._card_sp.setStyleSheet(self._CARD_SS)
        csl = QVBoxLayout(self._card_sp)
        csl.setContentsMargins(12, 10, 12, 10)
        csl.setSpacing(2)
        self._csl_label = QLabel("空间长度")
        self._csl_label.setStyleSheet(self._LABEL_SS)
        csl.addWidget(self._csl_label)
        val_row = QHBoxLayout()
        self.lbl_sp_val = QLabel("--")
        self.lbl_sp_val.setStyleSheet(self._VALUE_SS)
        val_row.addWidget(self.lbl_sp_val)
        self._sp_unit = QLabel("m")
        self._sp_unit.setStyleSheet("font-size:13px; color:#999; padding-top:6px;")
        val_row.addWidget(self._sp_unit)
        val_row.addStretch()
        csl.addLayout(val_row)
        self.lbl_sp_hint = QLabel("")
        self.lbl_sp_hint.setStyleSheet(self._HINT_SS)
        csl.addWidget(self.lbl_sp_hint)
        rl.addWidget(self._card_sp)

        # 局部系数卡片
        self._card_xi = QFrame()
        self._card_xi.setStyleSheet(self._CARD_HL_SS)
        cxl = QVBoxLayout(self._card_xi)
        cxl.setContentsMargins(12, 10, 12, 10)
        cxl.setSpacing(2)
        cxl.addWidget(QLabel("局部系数 ξ", styleSheet=self._LABEL_SS))
        xi_row = QHBoxLayout()
        self.ed_xi = LineEdit()
        self.ed_xi.setFixedWidth(110)
        self.ed_xi.setStyleSheet("font-size:16px; font-weight:700;")
        xi_row.addWidget(self.ed_xi)
        xi_row.addStretch()
        cxl.addLayout(xi_row)
        self.lbl_xi_hint = QLabel("可手动修改")
        self.lbl_xi_hint.setStyleSheet(self._HINT_BLUE_SS)
        cxl.addWidget(self.lbl_xi_hint)
        rl.addWidget(self._card_xi)

        # 公式卡片
        self._formula_frame = QFrame()
        self._formula_frame.setStyleSheet(
            "QFrame { background: #F8F9FE; border: 1px solid #E3ECF9;"
            " border-radius: 8px; }"
        )
        ffl = QVBoxLayout(self._formula_frame)
        ffl.setContentsMargins(12, 8, 12, 8)
        ffl.setSpacing(4)
        self._formula_title = QLabel("计算公式")
        self._formula_title.setStyleSheet("font-size:11px; color:#666;")
        self._formula_title.setAlignment(Qt.AlignCenter)
        ffl.addWidget(self._formula_title)
        self.formula_view = QWebEngineView()
        self.formula_view.setMinimumHeight(36)
        self.formula_view.setStyleSheet("border:none; background:transparent;")
        ffl.addWidget(self.formula_view)
        rl.addWidget(self._formula_frame)

        rl.addStretch()
        body.addWidget(right, 1)

        root.addLayout(body, 1)

        # ---- 底部按钮栏 ----
        footer = QFrame()
        footer.setStyleSheet(
            "QFrame { background: #FAFAFA; border-top: 1px solid #EEE; }"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 8, 16, 8)
        fl.addStretch()
        btn_cancel = PushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        fl.addWidget(btn_cancel)
        btn_ok = PrimaryPushButton("确定")
        btn_ok.clicked.connect(self._on_ok)
        fl.addWidget(btn_ok)
        root.addWidget(footer)

        self._on_type()

    # ---- 布局辅助 ----
    @staticmethod
    def _form_row(label_text, widget):
        """标签 + 控件的单行布局"""
        lay = QVBoxLayout()
        lay.setSpacing(2)
        lbl = QLabel(label_text)
        lbl.setStyleSheet("font-size:12px; color:#666;")
        lay.addWidget(lbl)
        lay.addWidget(widget)
        return lay

    @staticmethod
    def _form_row_with_unit(label_text, widget, unit):
        """标签 + 输入框 + 单位"""
        outer = QVBoxLayout()
        outer.setSpacing(2)
        lbl = QLabel(label_text)
        lbl.setStyleSheet("font-size:12px; color:#666;")
        outer.addWidget(lbl)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(widget)
        ulbl = QLabel(unit)
        ulbl.setStyleSheet("font-size:12px; color:#999;")
        row.addWidget(ulbl)
        row.addStretch()
        outer.addLayout(row)
        return outer

    @staticmethod
    def _mini_form(label_text, widget, unit):
        """紧凑垂直表单（高程用）"""
        lay = QVBoxLayout()
        lay.setSpacing(1)
        lbl = QLabel(label_text)
        lbl.setStyleSheet("font-size:11px; color:#666;")
        lay.addWidget(lbl)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(widget)
        u = QLabel(unit)
        u.setStyleSheet("font-size:11px; color:#999;")
        row.addWidget(u)
        lay.addLayout(row)
        return lay

    # ---- 类型切换 ----
    def _on_type(self, *_):
        t = self.combo_type.currentText()
        st = None
        for s in SegmentType:
            if s.value == t:
                st = s
                break
        is_common = st and is_common_type(st)
        if is_common:
            dir_text = "通用构件"
        elif self._direction == SegmentDirection.PLAN or (
                self.segment and self.segment.direction == SegmentDirection.PLAN):
            dir_text = "平面"
        else:
            dir_text = "纵断面"
        self.lbl_dir.setText(dir_text)

        show_elev = t in (SegmentType.STRAIGHT.value, SegmentType.FOLD.value)
        self._elev_widget.setVisible(show_elev)

        show_sp = t in (SegmentType.STRAIGHT.value, SegmentType.FOLD.value, SegmentType.BEND.value)
        self._card_sp.setVisible(show_sp)

        is_bend = (t == SegmentType.BEND.value)
        is_fold = (t == SegmentType.FOLD.value)
        self.ed_radius.setEnabled(is_bend)
        self.ed_angle.setEnabled(is_bend or is_fold)

        no_length = t in (SegmentType.TRASH_RACK.value, SegmentType.GATE_SLOT.value,
                          SegmentType.BYPASS_PIPE.value, SegmentType.OTHER.value)
        self.ed_length.setEnabled(not no_length)

        if not self._loading:
            self._auto_xi()
        self._update_formula()

    # ---- 几何参数变化 ----
    def _on_geom(self, *_):
        if not self._loading:
            self._auto_xi()
        self._update_spatial()
        self._update_formula()

    # ---- 自动计算 xi ----
    def _auto_xi(self):
        if self._user_modified_xi:
            return
        t = self.combo_type.currentText()
        if t == SegmentType.BEND.value:
            try:
                r = float(self.ed_radius.text() or 0)
                a = float(self.ed_angle.text() or 0)
                if r > 0 and a > 0 and self._D_theory > 0:
                    xi = CoefficientService.calculate_bend_coeff(r, self._D_theory, a, verbose=False)
                    self.ed_xi.setText(f"{xi:.4f}")
            except ValueError:
                pass
        elif t == SegmentType.FOLD.value:
            try:
                a = float(self.ed_angle.text() or 0)
                if a > 0:
                    xi = CoefficientService.calculate_fold_coeff(a, verbose=False)
                    self.ed_xi.setText(f"{xi:.4f}")
            except ValueError:
                pass

    # ---- 更新空间长度 ----
    def _update_spatial(self):
        t = self.combo_type.currentText()
        try:
            L = float(self.ed_length.text() or 0)
        except ValueError:
            L = 0
        if t in (SegmentType.STRAIGHT.value, SegmentType.FOLD.value):
            try:
                se = float(self.ed_start_elev.text()) if self.ed_start_elev.text().strip() else None
                ee = float(self.ed_end_elev.text()) if self.ed_end_elev.text().strip() else None
            except ValueError:
                se, ee = None, None
            if se is not None and ee is not None and L > 0:
                dh = ee - se
                sp = math.sqrt(L ** 2 + dh ** 2)
                self.lbl_sp_val.setText(f"{sp:.3f}")
                self.lbl_sp_hint.setText(f"= \u221a({L:.3f}\u00b2 + {dh:.2f}\u00b2)")
            elif L > 0:
                self.lbl_sp_val.setText(f"{L:.3f}")
                self.lbl_sp_hint.setText("(\u65e0\u9ad8\u7a0b,\u53d6\u6c34\u5e73\u957f\u5ea6)")
            else:
                self.lbl_sp_val.setText("--")
                self.lbl_sp_hint.setText("")
        elif t == SegmentType.BEND.value:
            try:
                r = float(self.ed_radius.text() or 0)
                a = float(self.ed_angle.text() or 0)
            except ValueError:
                r, a = 0, 0
            if r > 0 and a > 0:
                arc = r * math.radians(a)
                self.lbl_sp_val.setText(f"{arc:.3f}")
                self.lbl_sp_hint.setText(f"= R\u00d7\u03b8 = {r:.2f}\u00d7{a:.1f}\u00b0")
            else:
                self.lbl_sp_val.setText("--")
                self.lbl_sp_hint.setText("")

    # ---- 多行 LaTeX 渲染辅助 ----
    @staticmethod
    def _render_multi_latex(lines, fontsize=14):
        """将多行 LaTeX 渲染为组合 HTML body + 总高度。

        Returns (body_html, total_height)；全部失败时返回 ('', 0)。
        """
        parts = []
        total_h = 0
        for latex in lines:
            svg = render_latex_svg(latex, fontsize=fontsize)
            if svg:
                h = get_svg_height_px(svg, padding=8)
                total_h += h
                parts.append(
                    f'<div style="margin:2px 0;text-align:center;">{svg}</div>')
        return '\n'.join(parts), total_h

    # ---- 更新公式卡片 ----
    def _update_formula(self):
        t = self.combo_type.currentText()
        latex_lines = []
        title = "计算公式"

        if t == SegmentType.BEND.value:
            title = "弯管局部阻力系数（表 L.1.4-3 / L.1.4-4 插值）"
            try:
                r = float(self.ed_radius.text() or 0)
                a = float(self.ed_angle.text() or 0)
                if r > 0 and a > 0 and self._D_theory > 0:
                    r_d = r / self._D_theory
                    xi_90 = CoefficientService.get_xi_90(r_d)
                    gamma = CoefficientService.get_gamma(a)
                    xi = xi_90 * gamma
                    latex_lines = [
                        f"R/D_0 = R / D = {r:.3f} / {self._D_theory:.3f} = {r_d:.3f}",
                        f"\\text{{查表 L.1.4-3：}}\\xi_{{90}} = {xi_90:.4f}",
                        f"\\text{{查表 L.1.4-4：}}\\gamma = {gamma:.4f}",
                        f"\\xi = \\xi_{{90}} \\times \\gamma = {xi_90:.4f} \\times {gamma:.4f} = {xi:.4f}",
                    ]
            except ValueError:
                pass
        elif t == SegmentType.FOLD.value:
            title = "折管局部阻力系数"
            try:
                a = float(self.ed_angle.text() or 0)
                xi_txt = self.ed_xi.text().strip()
                xi_val = float(xi_txt) if xi_txt else 0
                if a > 0:
                    latex_lines.append(
                        f"\\xi = 0.946\\sin^2\\!\\left(\\frac{{\\theta}}{{2}}"
                        f"\\right) + 2.05\\sin^4\\!\\left(\\frac{{\\theta}}"
                        f"{{2}}\\right) = {xi_val:.4f}")
            except ValueError:
                pass
            try:
                L = float(self.ed_length.text() or 0)
                se = float(self.ed_start_elev.text()) if self.ed_start_elev.text().strip() else None
                ee = float(self.ed_end_elev.text()) if self.ed_end_elev.text().strip() else None
                if se is not None and ee is not None and L > 0:
                    dh = ee - se
                    sp = math.sqrt(L ** 2 + dh ** 2)
                    title = "折管局部阻力系数 + 空间长度"
                    latex_lines.append(
                        f"L_s = \\sqrt{{L^2 + \\Delta H^2}} = "
                        f"\\sqrt{{{L:.3f}^2 + {dh:.2f}^2}} = {sp:.3f}"
                        f"\\;\\text{{m}}")
            except ValueError:
                pass
        elif t == SegmentType.STRAIGHT.value:
            title = "空间长度计算"
            try:
                L = float(self.ed_length.text() or 0)
                se = float(self.ed_start_elev.text()) if self.ed_start_elev.text().strip() else None
                ee = float(self.ed_end_elev.text()) if self.ed_end_elev.text().strip() else None
                if se is not None and ee is not None and L > 0:
                    dh = ee - se
                    sp = math.sqrt(L ** 2 + dh ** 2)
                    latex_lines.append(
                        f"L_s = \\sqrt{{L^2 + \\Delta H^2}} = "
                        f"\\sqrt{{{L:.3f}^2 + {dh:.2f}^2}} = {sp:.3f}"
                        f"\\;\\text{{m}}")
            except ValueError:
                pass

        self._formula_title.setText(title)
        if latex_lines:
            body, total_h = self._render_multi_latex(latex_lines)
            if body:
                self.formula_view.setFixedHeight(total_h)
                html = wrap_with_katex(body, extra_css=(
                    "html,body{margin:0;padding:0;"
                    "background:transparent;}"))
                self.formula_view.setHtml(html)
                self._formula_frame.setVisible(True)
                return
        self._formula_frame.setVisible(False)
        self.formula_view.setFixedHeight(0)
        self.formula_view.setHtml("")

    # ---- 加载已有数据 ----
    def _load(self, seg):
        self._loading = True
        if seg.segment_type in (SegmentType.INLET, SegmentType.OUTLET):
            self.combo_type.clear()
            self.combo_type.addItems([st.value for st in SegmentType])
        self.combo_type.setCurrentText(seg.segment_type.value)
        self.ed_length.setText(f"{seg.length:.3f}")
        self.ed_radius.setText(f"{seg.radius:.2f}")
        self.ed_angle.setText(f"{seg.angle:.1f}")
        if seg.start_elevation is not None:
            self.ed_start_elev.setText(f"{seg.start_elevation:.2f}")
        if seg.end_elevation is not None:
            self.ed_end_elev.setText(f"{seg.end_elevation:.2f}")
        if seg.xi_user is not None:
            self.ed_xi.setText(f"{seg.xi_user:.4f}")
            self._user_modified_xi = True
        elif seg.xi_calc is not None:
            self.ed_xi.setText(f"{seg.xi_calc:.4f}")
        self._on_type()
        self._update_spatial()
        self._loading = False

    # ---- 确定 ----
    def _on_ok(self):
        try:
            t = self.combo_type.currentText()
            st = None
            for s in SegmentType:
                if s.value == t:
                    st = s
                    break
            if st is None:
                return

            def _safe(ed, default=0.0):
                txt = ed.text().strip()
                return default if not txt or txt == "--" else float(txt)

            length = _safe(self.ed_length)
            radius = _safe(self.ed_radius)
            angle = _safe(self.ed_angle)

            xi_user, xi_calc = None, None
            xi_txt = self.ed_xi.text().strip()
            if xi_txt:
                xi_val = float(xi_txt)
                if self._user_modified_xi:
                    xi_user = xi_val
                else:
                    xi_calc = xi_val

            se_txt = self.ed_start_elev.text().strip()
            ee_txt = self.ed_end_elev.text().strip()
            start_e = float(se_txt) if se_txt else None
            end_e = float(ee_txt) if ee_txt else None

            direction = SegmentDirection.COMMON if is_common_type(st) else (
                self.segment.direction if self.segment else SegmentDirection.LONGITUDINAL)

            self.result = StructureSegment(
                segment_type=st, direction=direction,
                length=length, radius=radius, angle=angle,
                xi_user=xi_user,
                xi_calc=xi_calc if xi_calc is not None else (self.segment.xi_calc if self.segment else None),
                coordinates=self.segment.coordinates if self.segment else [],
                locked=self.segment.locked if self.segment else False,
                start_elevation=start_e, end_elevation=end_e,
                source_ip_index=self.segment.source_ip_index if self.segment else None,
            )
            self.accept()
        except ValueError as e:
            _msg(self, "输入错误", f"请检查数值: {e}", "error")


# ============================================================
# 5. 进口断面参数对话框
# ============================================================
class InletSectionDialog(QDialog):
    """进口渐变段末端断面参数 → 自动计算 v₂"""

    def __init__(self, parent, Q, B=None, h=None, m=None):
        super().__init__(parent)
        self.setWindowTitle("进口渐变段末端断面参数设置")
        self.setMinimumSize(500, 380)
        self.resize(530, 420)
        self.Q = Q
        self.result_B = B
        self.result_h = h
        self.result_m = m
        self.result_velocity = None
        self._build_ui(B, h, m)

    def _build_ui(self, B, h, m):
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        title = QLabel("设置渐变段末端断面参数，自动计算该断面流速")
        title.setStyleSheet("font-size:12px;font-weight:bold;")
        lay.addWidget(title)

        g = QGridLayout()
        g.addWidget(QLabel("渐变段末端底宽 B (m):"), 0, 0)
        self.ed_B = LineEdit(); self.ed_B.setFixedWidth(100)
        if B is not None: self.ed_B.setText(str(B))
        self.ed_B.textChanged.connect(self._calc)
        g.addWidget(self.ed_B, 0, 1)

        g.addWidget(QLabel("渐变段末端水深 h (m):"), 1, 0)
        self.ed_h = LineEdit(); self.ed_h.setFixedWidth(100)
        if h is not None: self.ed_h.setText(str(h))
        self.ed_h.textChanged.connect(self._calc)
        g.addWidget(self.ed_h, 1, 1)

        g.addWidget(QLabel("渐变段末端边坡比 m:"), 2, 0)
        self.ed_m = LineEdit(); self.ed_m.setFixedWidth(100)
        if m is not None: self.ed_m.setText(str(m))
        self.ed_m.textChanged.connect(self._calc)
        g.addWidget(self.ed_m, 2, 1)
        g.addWidget(QLabel("(1:m，如1.5表示1:1.5)"), 2, 2)
        lay.addLayout(g)

        rgrp = QGroupBox("计算结果")
        rl = QVBoxLayout(rgrp)
        rl.addWidget(QLabel("断面面积 A = (B + m×h) × h"))
        rl.addWidget(QLabel("流速 v₂ = Q / A"))
        self.lbl_result = QLabel("请输入完整参数")
        self.lbl_result.setStyleSheet(f"font-weight:bold;color:{P};")
        rl.addWidget(self.lbl_result)
        lay.addWidget(rgrp)

        brow = QHBoxLayout()
        btn_ok = PrimaryPushButton("确定"); btn_ok.clicked.connect(self._on_ok)
        btn_clr = PushButton("清除"); btn_clr.clicked.connect(self._on_clear)
        btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(self.reject)
        brow.addWidget(btn_ok); brow.addWidget(btn_clr); brow.addWidget(btn_cancel)
        brow.addStretch()
        lay.addLayout(brow)

        if B is not None and h is not None and m is not None:
            self._calc()

    def _calc(self, *_):
        try:
            Bt, ht, mt = self.ed_B.text().strip(), self.ed_h.text().strip(), self.ed_m.text().strip()
            if not Bt or not ht or not mt:
                self.lbl_result.setText("请输入完整参数")
                self.result_velocity = None
                return
            B, h, m = float(Bt), float(ht), float(mt)
            if B <= 0 or h <= 0:
                self.lbl_result.setText("B、h必须大于0")
                self.result_velocity = None
                return
            area = (B + m * h) * h
            if area <= 0:
                self.result_velocity = None
                return
            vel = self.Q / area
            self.result_velocity = vel
            self.lbl_result.setText(f"v₂ = {vel:.4f} m/s (A = {area:.4f} m²)")
        except ValueError:
            self.lbl_result.setText("参数格式错误")
            self.result_velocity = None

    def _on_ok(self):
        try:
            Bt, ht, mt = self.ed_B.text().strip(), self.ed_h.text().strip(), self.ed_m.text().strip()
            if not Bt and not ht and not mt:
                self.result_B = self.result_h = self.result_m = None
                self.result_velocity = None
                self.accept()
                return
            if not Bt or not ht or not mt:
                _msg(self, "输入不完整", "请输入完整参数或点击'清除'", "warning")
                return
            self.result_B = float(Bt)
            self.result_h = float(ht)
            self.result_m = float(mt)
            area = (self.result_B + self.result_m * self.result_h) * self.result_h
            self.result_velocity = self.Q / area
            self.accept()
        except ValueError:
            _msg(self, "输入错误", "请输入有效数字", "error")

    def _on_clear(self):
        self.ed_B.clear(); self.ed_h.clear(); self.ed_m.clear()
        self.lbl_result.setText("已清除参数")
        self.result_velocity = None

    def keyPressEvent(self, event):
        """阻止 ESC 键关闭窗口"""
        if event.key() == Qt.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)


# ============================================================
# 6. 添加自定义通用构件对话框
# ============================================================
class CommonSegmentAddDialog(QDialog):
    """添加通用构件（镇墩/排气阀等）"""

    _PRESETS = ["镇墩", "排气阀", "伸缩缝", "检修孔", "排水阀", "进人孔", "消能井", "其他"]

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("添加通用构件")
        self.setMinimumSize(420, 200)
        self.resize(440, 220)
        self.result = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("构件名称:"))
        self.combo_name = QComboBox()
        self.combo_name.setEditable(True)
        self.combo_name.addItems(self._PRESETS)
        self.combo_name.setCurrentText("其他")
        r1.addWidget(self.combo_name)
        r1.addWidget(QLabel("(可自由输入)"))
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("局部阻力系数 ξ:"))
        self.ed_xi = LineEdit(); self.ed_xi.setText("0.1"); self.ed_xi.setFixedWidth(80)
        r2.addWidget(self.ed_xi)
        r2.addStretch()
        lay.addLayout(r2)

        brow = QHBoxLayout()
        brow.addStretch()
        btn_ok = PrimaryPushButton("确定"); btn_ok.clicked.connect(self._on_ok)
        btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(self.reject)
        brow.addWidget(btn_ok); brow.addWidget(btn_cancel)
        lay.addLayout(brow)

    def _on_ok(self):
        label = self.combo_name.currentText().strip()
        if not label:
            _msg(self, "输入错误", "请输入构件名称", "error")
            return
        try:
            xi = float(self.ed_xi.text())
        except ValueError:
            _msg(self, "输入错误", "系数格式错误", "error")
            return
        self.result = (label, xi)
        self.accept()

    def keyPressEvent(self, event):
        """阻止 ESC 键关闭窗口"""
        if event.key() == Qt.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)


# ============================================================
# 7. 简洁编辑对话框（拦污栅/闸门槽/旁通管）
# ============================================================
class SimpleCommonEditDialog(QDialog):
    """拦污栅/闸门槽/旁通管/管道渐变段 简洁编辑"""

    def __init__(self, parent, segment):
        super().__init__(parent)
        self.setWindowTitle("编辑通用构件")
        self.segment = segment
        self.result = None
        self.trash_rack_params = segment.trash_rack_params if SIPHON_AVAILABLE else None
        self._build_ui()
        self.adjustSize()
        self.setMinimumSize(self.sizeHint())

    def _build_ui(self):
        if not SIPHON_AVAILABLE:
            QVBoxLayout(self).addWidget(QLabel("计算引擎未加载"))
            return
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("构件名称:"))
        lbl = QLabel(self.segment.segment_type.value)
        lbl.setStyleSheet("font-weight:bold;")
        r1.addWidget(lbl)
        r1.addStretch()
        lay.addLayout(r1)

        # ---- 管道渐变段专属：收缩/扩散单选 ----
        self._pipe_trans_group = None
        if self.segment.segment_type == SegmentType.PIPE_TRANSITION:
            self._pipe_trans_group = QButtonGroup(self)
            self._rb_contract = QRadioButton(
                f"收缩（方变圆 / 圆管收缩）  ξjb = {CoefficientService.PIPE_TRANSITION_CONTRACT}")
            self._rb_expand = QRadioButton(
                f"扩散（圆变方 / 圆管扩大）  ξjb = {CoefficientService.PIPE_TRANSITION_EXPAND}")
            self._pipe_trans_group.addButton(self._rb_contract, 0)
            self._pipe_trans_group.addButton(self._rb_expand,   1)
            # 根据已保存的 custom_label 恢复选中状态
            cur_label = getattr(self.segment, 'custom_label', '')
            if cur_label == '扩散':
                self._rb_expand.setChecked(True)
            else:
                self._rb_contract.setChecked(True)  # 默认收缩
            self._rb_contract.toggled.connect(self._on_pipe_trans_changed)
            self._rb_expand.toggled.connect(self._on_pipe_trans_changed)
            lay.addWidget(self._rb_contract)
            lay.addWidget(self._rb_expand)
            lbl_norm = QLabel("注：扩散角不宜大于 10°（GB 50288-2018 附录L.1.4-4）")
            lbl_norm.setStyleSheet("color:#0066CC;font-size:11px;")
            lay.addWidget(lbl_norm)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("局部阻力系数 ξ:"))
        self.ed_xi = LineEdit(); self.ed_xi.setFixedWidth(90)
        if self.segment.segment_type == SegmentType.PIPE_TRANSITION:
            # 系数由单选决定，初始值按已保存 label 或默认收缩
            cur_label = getattr(self.segment, 'custom_label', '')
            xi_val = (CoefficientService.PIPE_TRANSITION_EXPAND
                      if cur_label == '扩散'
                      else CoefficientService.PIPE_TRANSITION_CONTRACT)
            self.ed_xi.setText(f"{xi_val:.4f}")
            self.ed_xi.setReadOnly(True)
        else:
            xi_val = self.segment.xi_user if self.segment.xi_user is not None else (self.segment.xi_calc or 0.1)
            self.ed_xi.setText(f"{xi_val:.4f}")
        r2.addWidget(self.ed_xi)

        if self.segment.segment_type == SegmentType.TRASH_RACK:
            self.ed_xi.setReadOnly(True)
            btn_cfg = PushButton("详细配置")
            btn_cfg.clicked.connect(self._open_trash_rack)
            r2.addWidget(btn_cfg)
            if self.trash_rack_params is None:
                self.trash_rack_params = TrashRackParams()

        r2.addStretch()
        lay.addLayout(r2)

        if self.segment.segment_type == SegmentType.GATE_SLOT:
            lbl_hint = QLabel("规范推荐: 0.05 ~ 0.15（平板门门槽，GB 50288-2018 附录L）")
            lbl_hint.setStyleSheet("color:#0066CC;font-size:11px;")
            lay.addWidget(lbl_hint)

        brow = QHBoxLayout()
        brow.addStretch()
        btn_ok = PrimaryPushButton("确定"); btn_ok.clicked.connect(self._on_ok)
        btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(self.reject)
        brow.addWidget(btn_ok); brow.addWidget(btn_cancel)
        lay.addLayout(brow)

    def _on_pipe_trans_changed(self):
        """收缩/扩散单选切换 → 自动更新 ξ 显示值"""
        if self._rb_expand.isChecked():
            xi = CoefficientService.PIPE_TRANSITION_EXPAND
        else:
            xi = CoefficientService.PIPE_TRANSITION_CONTRACT
        self.ed_xi.setReadOnly(False)
        self.ed_xi.setText(f"{xi:.4f}")
        self.ed_xi.setReadOnly(True)

    def _open_trash_rack(self):
        dlg = TrashRackConfigDialog(self, self.trash_rack_params)
        if dlg.exec() == QDialog.Accepted and dlg.result:
            self.trash_rack_params = dlg.result
            xi = CoefficientService.calculate_trash_rack_xi(self.trash_rack_params)
            self.ed_xi.setReadOnly(False)
            self.ed_xi.setText(f"{xi:.4f}")
            self.ed_xi.setReadOnly(True)

    def _on_ok(self):
        try:
            xi = float(self.ed_xi.text())
        except ValueError:
            _msg(self, "输入错误", "系数格式错误", "error")
            return
        if self.segment.segment_type == SegmentType.TRASH_RACK:
            xi_user, xi_calc = None, xi
        else:
            xi_user, xi_calc = xi, self.segment.xi_calc
        # 管道渐变段：从单选按钮读取 custom_label
        if self.segment.segment_type == SegmentType.PIPE_TRANSITION:
            custom_label = '扩散' if (self._pipe_trans_group and self._rb_expand.isChecked()) else '收缩'
        else:
            custom_label = getattr(self.segment, 'custom_label', '')
        self.result = StructureSegment(
            segment_type=self.segment.segment_type,
            direction=SegmentDirection.COMMON,
            xi_user=xi_user, xi_calc=xi_calc,
            locked=self.segment.locked,
            coordinates=self.segment.coordinates,
            custom_label=custom_label,
            trash_rack_params=self.trash_rack_params if self.segment.segment_type == SegmentType.TRASH_RACK else None,
            source_ip_index=self.segment.source_ip_index,
        )
        self.accept()

    def keyPressEvent(self, event):
        """阻止 ESC 键关闭窗口"""
        if event.key() == Qt.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)


# ============================================================
# 通用构件编辑对话框（"其他"类型）
# ============================================================
class CommonSegmentEditDialog(QDialog):
    """编辑自定义通用构件"""

    _PRESETS = ["镇墩", "排气阀", "伸缩缝", "检修孔", "排水阀", "进人孔", "消能井", "其他"]

    def __init__(self, parent, segment):
        super().__init__(parent)
        self.setWindowTitle("编辑通用构件")
        self.segment = segment
        self.result = None
        self._build_ui()
        self.adjustSize()
        self.setMinimumSize(self.sizeHint())

    def _build_ui(self):
        if not SIPHON_AVAILABLE:
            QVBoxLayout(self).addWidget(QLabel("计算引擎未加载"))
            return

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("构件名称:"))
        self.combo_name = QComboBox()
        self.combo_name.setEditable(True)
        self.combo_name.addItems(self._PRESETS)
        cur = getattr(self.segment, 'custom_label', '') or self.segment.segment_type.value
        self.combo_name.setCurrentText(cur)
        r1.addWidget(self.combo_name)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("局部阻力系数 ξ:"))
        self.ed_xi = LineEdit(); self.ed_xi.setFixedWidth(90)
        xi_val = self.segment.xi_user if self.segment.xi_user is not None else (self.segment.xi_calc or 0.1)
        self.ed_xi.setText(f"{xi_val:.4f}")
        r2.addWidget(self.ed_xi)
        r2.addStretch()
        lay.addLayout(r2)

        brow = QHBoxLayout()
        brow.addStretch()
        btn_ok = PrimaryPushButton("确定"); btn_ok.clicked.connect(self._on_ok)
        btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(self.reject)
        brow.addWidget(btn_ok); brow.addWidget(btn_cancel)
        lay.addLayout(brow)

    def _on_ok(self):
        label = self.combo_name.currentText().strip()
        if not label:
            _msg(self, "输入错误", "请输入构件名称", "error")
            return
        try:
            xi = float(self.ed_xi.text())
        except ValueError:
            _msg(self, "输入错误", "系数格式错误", "error")
            return
        self.result = StructureSegment(
            segment_type=SegmentType.OTHER, direction=SegmentDirection.COMMON,
            custom_label=label, xi_user=xi,
            locked=self.segment.locked, coordinates=self.segment.coordinates,
        )
        self.accept()

    def keyPressEvent(self, event):
        """阻止 ESC 键关闭窗口"""
        if event.key() == Qt.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)
