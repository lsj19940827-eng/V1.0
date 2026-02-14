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

from qfluentwidgets import (
    PushButton, PrimaryPushButton, LineEdit, ComboBox, CheckBox,
    InfoBar, InfoBarPosition
)

from 渠系断面设计.styles import P, S, W, E, BG, CARD, BD, T1, T2, auto_resize_table

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
        self.setMinimumSize(480, 400)
        self.resize(520, 440)
        self.result = None
        self.segment = segment
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

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
        lay.addWidget(cgrp)

        # 加载当前值
        cur_xi = self.segment.xi_user if self.segment.xi_user is not None else self.segment.xi_calc
        if cur_xi is not None:
            self.edit_xi.setText(f"{cur_xi:.4f}")
        else:
            self._update_default_xi()
        self._update_range_hint()

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
            return
        ratio = self.omega_g / omega_q
        xi_c = (1 - ratio) ** 2
        self.lbl_calc_xi.setText(f"ξc = (1 - {self.omega_g:.4f}/{omega_q:.4f})² = {xi_c:.4f}")
        self.edit_xi.setText(f"{xi_c:.4f}")

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
        self.setMinimumSize(780, 620)
        self.resize(820, 660)
        self.result = None
        if SIPHON_AVAILABLE:
            self.params = params if params else TrashRackParams()
            self.shape_list = list(TrashRackBarShape)
        else:
            self.params = None
            self.shape_list = []
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

        self.cb_support = CheckBox("有独立支墩 (公式L.1.4-3)")
        self.cb_support.setChecked(self.params.has_support)
        self.cb_support.stateChanged.connect(self._on_mode)
        g1l.addWidget(self.cb_support, 1, 0, 1, 3)
        ll.addWidget(g1)

        # 栅条参数
        g2 = QGroupBox("栅条参数")
        g2l = QGridLayout(g2)
        g2l.addWidget(QLabel("栅条形状:"), 0, 0)
        self.combo_bar = ComboBox()
        self.combo_bar.addItems([f"{s.value} (β={CoefficientService.get_trash_rack_bar_beta(s):.2f})"
                                  for s in self.shape_list])
        idx = self.shape_list.index(self.params.bar_shape) if self.params.bar_shape in self.shape_list else 0
        self.combo_bar.setCurrentIndex(idx)
        self.combo_bar.currentIndexChanged.connect(self._on_changed)
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
        ll.addWidget(g2)

        # 支墩参数
        self.g3 = QGroupBox("支墩参数")
        g3l = QGridLayout(self.g3)
        g3l.addWidget(QLabel("支墩形状:"), 0, 0)
        self.combo_sup = ComboBox()
        self.combo_sup.addItems([f"{s.value} (β={CoefficientService.get_trash_rack_bar_beta(s):.2f})"
                                  for s in self.shape_list])
        sidx = self.shape_list.index(self.params.support_shape) if self.params.support_shape in self.shape_list else 0
        self.combo_sup.setCurrentIndex(sidx)
        self.combo_sup.currentIndexChanged.connect(self._on_changed)
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
        self.lbl_result = QLabel("--")
        self.lbl_result.setStyleSheet(f"font-size:16px;font-weight:bold;color:{P};")
        rl.addWidget(self.lbl_result)

        brow = QHBoxLayout()
        btn_ok = PrimaryPushButton("确定"); btn_ok.clicked.connect(self._on_ok)
        btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(self.reject)
        brow.addWidget(btn_ok); brow.addWidget(btn_cancel); brow.addStretch()
        rl.addLayout(brow)
        ll.addWidget(rg)

        lay.addWidget(left, stretch=1)

        # 右侧参考表
        right = QWidget()
        rlayout = QVBoxLayout(right)
        rlayout.setContentsMargins(4, 4, 4, 4)

        fig_grp = QGroupBox("栅条形状示意图 (图L.1.4-1)")
        fig_lay = QVBoxLayout(fig_grp)
        self.img_label = QLabel("(双击可查看大图)")
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setMinimumHeight(160)
        self.img_label.setStyleSheet("background:white;border:1px solid #ddd;")
        fig_lay.addWidget(self.img_label)
        rlayout.addWidget(fig_grp)
        self._load_image()

        tbl_grp = QGroupBox("形状系数表 (表L.1.4-1)")
        tl2 = QVBoxLayout(tbl_grp)
        self.ref_table = QTableWidget(len(self.shape_list), 2)
        self.ref_table.setHorizontalHeaderLabels(["形状名称", "系数 β"])
        self.ref_table.horizontalHeader().setStretchLastSection(False)
        self.ref_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.ref_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.ref_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for i, s in enumerate(self.shape_list):
            self.ref_table.setItem(i, 0, QTableWidgetItem(s.value))
            beta = CoefficientService.get_trash_rack_bar_beta(s)
            self.ref_table.setItem(i, 1, QTableWidgetItem(f"{beta:.2f}"))
        auto_resize_table(self.ref_table)
        tl2.addWidget(self.ref_table)
        rlayout.addWidget(tbl_grp)

        lay.addWidget(right, stretch=1)

        self._on_mode()
        self._update_preview()

    def _load_image(self):
        img_path = os.path.join(self.SCRIPT_DIR, "resources", "图L.1.4-1.png")
        if os.path.exists(img_path):
            pm = QPixmap(img_path)
            if not pm.isNull():
                self.img_label.setPixmap(pm.scaled(
                    self.img_label.width() - 10, 200,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation))
                return
        self.img_label.setText("图片未找到")

    def _on_mode(self):
        en = self.cb_support.isChecked()
        self.g3.setEnabled(en)
        self._on_changed()

    def _on_manual(self):
        self.ed_manual.setEnabled(self.cb_manual.isChecked())
        self._on_changed()

    def _on_changed(self, *_):
        self._update_ratios()
        self._update_preview()

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
                alpha=alpha, has_support=self.cb_support.isChecked(),
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
        if params.b1 <= 0 or params.s1 <= 0:
            self.lbl_result.setText("请输入栅条参数")
            return
        if params.has_support and (params.b2 <= 0 or params.s2 <= 0):
            self.lbl_result.setText("请输入支墩参数")
            return
        xi = CoefficientService.calculate_trash_rack_xi(params)
        self.lbl_result.setText(f"ξs = {xi:.4f}")

    def _on_ok(self):
        params = self._collect()
        if params is None:
            _msg(self, "输入错误", "请检查参数格式", "error")
            return
        self.result = params
        self.accept()


# ============================================================
# 4. 结构段编辑对话框
# ============================================================
class SegmentEditDialog(QDialog):
    """管身段编辑"""

    def __init__(self, parent, segment=None, Q=10.0, v=2.0):
        super().__init__(parent)
        self.setWindowTitle("编辑结构段")
        self.setMinimumSize(540, 420)
        self.resize(580, 480)
        self.result = None
        self.segment = segment
        self._Q, self._v = Q, v
        self._D_theory = math.sqrt(4 * Q / (math.pi * v)) if Q > 0 and v > 0 else 0
        self._user_modified_xi = False
        self._loading = False
        self._build_ui()
        if segment:
            self._load(segment)

    def _build_ui(self):
        if not SIPHON_AVAILABLE:
            QVBoxLayout(self).addWidget(QLabel("计算引擎未加载"))
            return

        lay = QGridLayout(self)
        lay.setSpacing(8)
        row = 0

        # 类型
        lay.addWidget(QLabel("类型:"), row, 0)
        self.combo_type = ComboBox()
        types = [st.value for st in SegmentType if st not in (SegmentType.INLET, SegmentType.OUTLET)]
        self.combo_type.addItems(types)
        self.combo_type.setCurrentText(SegmentType.STRAIGHT.value)
        self.combo_type.currentTextChanged.connect(self._on_type)
        lay.addWidget(self.combo_type, row, 1)
        self.lbl_dir = QLabel("[纵断面]")
        self.lbl_dir.setStyleSheet(f"color:{T2};font-size:10px;")
        lay.addWidget(self.lbl_dir, row, 2)
        row += 1

        # 长度
        lay.addWidget(QLabel("长度 (m):"), row, 0)
        self.ed_length = LineEdit(); self.ed_length.setText("0.0"); self.ed_length.setFixedWidth(120)
        self.ed_length.textChanged.connect(self._on_geom)
        lay.addWidget(self.ed_length, row, 1)
        row += 1

        # 半径
        lay.addWidget(QLabel("拐弯半径 R (m):"), row, 0)
        self.ed_radius = LineEdit(); self.ed_radius.setText("0.0"); self.ed_radius.setFixedWidth(120)
        self.ed_radius.textChanged.connect(self._on_geom)
        lay.addWidget(self.ed_radius, row, 1)
        row += 1

        # 角度
        lay.addWidget(QLabel("拐角 θ (°):"), row, 0)
        self.ed_angle = LineEdit(); self.ed_angle.setText("0.0"); self.ed_angle.setFixedWidth(120)
        self.ed_angle.textChanged.connect(self._on_geom)
        lay.addWidget(self.ed_angle, row, 1)
        row += 1

        # 起点高程
        self.lbl_se = QLabel("起点高程 (m):")
        lay.addWidget(self.lbl_se, row, 0)
        self.ed_start_elev = LineEdit(); self.ed_start_elev.setFixedWidth(120)
        lay.addWidget(self.ed_start_elev, row, 1)
        row += 1

        # 终点高程
        self.lbl_ee = QLabel("终点高程 (m):")
        lay.addWidget(self.lbl_ee, row, 0)
        self.ed_end_elev = LineEdit(); self.ed_end_elev.setFixedWidth(120)
        lay.addWidget(self.ed_end_elev, row, 1)
        row += 1

        # 空间长度
        self.lbl_sp = QLabel("空间长度 (m):")
        lay.addWidget(self.lbl_sp, row, 0)
        self.lbl_sp_val = QLabel("--")
        self.lbl_sp_val.setStyleSheet("font-weight:bold;")
        lay.addWidget(self.lbl_sp_val, row, 1)
        self.lbl_sp_hint = QLabel("= √(L² + ΔH²)")
        self.lbl_sp_hint.setStyleSheet(f"color:{T2};font-size:10px;")
        lay.addWidget(self.lbl_sp_hint, row, 2)
        row += 1

        # 局部系数
        lay.addWidget(QLabel("局部系数:"), row, 0)
        self.ed_xi = LineEdit(); self.ed_xi.setFixedWidth(100)
        lay.addWidget(self.ed_xi, row, 1)
        self.lbl_xi_hint = QLabel("(可手动修改)")
        self.lbl_xi_hint.setStyleSheet(f"color:{T2};font-size:10px;")
        lay.addWidget(self.lbl_xi_hint, row, 2)
        row += 1

        # 按钮
        brow = QHBoxLayout()
        brow.addStretch()
        btn_ok = PrimaryPushButton("确定"); btn_ok.clicked.connect(self._on_ok)
        btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(self.reject)
        brow.addWidget(btn_ok); brow.addWidget(btn_cancel)
        lay.addLayout(brow, row, 0, 1, 3)

        self._on_type()

    def _on_type(self, *_):
        t = self.combo_type.currentText()
        st = None
        for s in SegmentType:
            if s.value == t:
                st = s
                break
        is_common = st and is_common_type(st)
        self.lbl_dir.setText("[通用构件]" if is_common else "[纵断面]")

        show_elev = t in (SegmentType.STRAIGHT.value, SegmentType.FOLD.value)
        for w in (self.lbl_se, self.ed_start_elev, self.lbl_ee, self.ed_end_elev):
            w.setVisible(show_elev)

        show_sp = t in (SegmentType.STRAIGHT.value, SegmentType.FOLD.value, SegmentType.BEND.value)
        for w in (self.lbl_sp, self.lbl_sp_val, self.lbl_sp_hint):
            w.setVisible(show_sp)

        is_bend = (t == SegmentType.BEND.value)
        is_fold = (t == SegmentType.FOLD.value)
        self.ed_radius.setEnabled(is_bend)
        self.ed_angle.setEnabled(is_bend or is_fold)

        no_length = t in (SegmentType.TRASH_RACK.value, SegmentType.GATE_SLOT.value,
                          SegmentType.BYPASS_PIPE.value, SegmentType.OTHER.value)
        self.ed_length.setEnabled(not no_length)

        if not self._loading:
            self._auto_xi()

    def _on_geom(self, *_):
        if not self._loading:
            self._auto_xi()
        self._update_spatial()

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
                self.lbl_sp_hint.setText(f"= √({L:.3f}² + {dh:.2f}²)")
            elif L > 0:
                self.lbl_sp_val.setText(f"{L:.3f}")
                self.lbl_sp_hint.setText("(无高程,取水平长度)")
            else:
                self.lbl_sp_val.setText("--")
        elif t == SegmentType.BEND.value:
            try:
                r = float(self.ed_radius.text() or 0)
                a = float(self.ed_angle.text() or 0)
            except ValueError:
                r, a = 0, 0
            if r > 0 and a > 0:
                arc = r * math.radians(a)
                self.lbl_sp_val.setText(f"{arc:.3f}")
                self.lbl_sp_hint.setText(f"= R×θ = {r:.2f}×{a:.1f}°")
            else:
                self.lbl_sp_val.setText("--")

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


# ============================================================
# 7. 简洁编辑对话框（拦污栅/闸门槽/旁通管）
# ============================================================
class SimpleCommonEditDialog(QDialog):
    """拦污栅/闸门槽/旁通管 简洁编辑"""

    def __init__(self, parent, segment):
        super().__init__(parent)
        self.setWindowTitle("编辑通用构件")
        self.setMinimumSize(440, 200)
        self.resize(460, 230)
        self.segment = segment
        self.result = None
        self.trash_rack_params = segment.trash_rack_params if SIPHON_AVAILABLE else None
        self._build_ui()

    def _build_ui(self):
        if not SIPHON_AVAILABLE:
            QVBoxLayout(self).addWidget(QLabel("计算引擎未加载"))
            return
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("构件名称:"))
        lbl = QLabel(self.segment.segment_type.value)
        lbl.setStyleSheet("font-weight:bold;")
        r1.addWidget(lbl)
        r1.addStretch()
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("局部阻力系数 ξ:"))
        self.ed_xi = LineEdit(); self.ed_xi.setFixedWidth(90)
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

        brow = QHBoxLayout()
        brow.addStretch()
        btn_ok = PrimaryPushButton("确定"); btn_ok.clicked.connect(self._on_ok)
        btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(self.reject)
        brow.addWidget(btn_ok); brow.addWidget(btn_cancel)
        lay.addLayout(brow)

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
        self.result = StructureSegment(
            segment_type=self.segment.segment_type,
            direction=SegmentDirection.COMMON,
            xi_user=xi_user, xi_calc=xi_calc,
            locked=self.segment.locked,
            coordinates=self.segment.coordinates,
            custom_label=getattr(self.segment, 'custom_label', ''),
            trash_rack_params=self.trash_rack_params if self.segment.segment_type == SegmentType.TRASH_RACK else None,
            source_ip_index=self.segment.source_ip_index,
        )
        self.accept()


# ============================================================
# 通用构件编辑对话框（"其他"类型）
# ============================================================
class CommonSegmentEditDialog(QDialog):
    """编辑自定义通用构件"""

    _PRESETS = ["镇墩", "排气阀", "伸缩缝", "检修孔", "排水阀", "进人孔", "消能井", "其他"]

    def __init__(self, parent, segment):
        super().__init__(parent)
        self.setWindowTitle("编辑通用构件")
        self.setMinimumSize(420, 200)
        self.resize(440, 220)
        self.segment = segment
        self.result = None
        self._build_ui()

    def _build_ui(self):
        if not SIPHON_AVAILABLE:
            QVBoxLayout(self).addWidget(QLabel("计算引擎未加载"))
            return

        lay = QVBoxLayout(self)
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
