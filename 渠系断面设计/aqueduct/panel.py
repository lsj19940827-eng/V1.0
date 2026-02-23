# -*- coding: utf-8 -*-
"""
渡槽水力计算面板 —— QWidget 版本（可嵌入主导航框架）

支持：U形断面 / 矩形断面（可带倒角）
功能：参数输入、计算、结果显示、断面图、导出Word/TXT/图表
"""

import sys
import os
import math
import re
import html as html_mod

# 将计算模块目录加入搜索路径
_pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_pkg_root, "渠系建筑物断面计算"))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QSplitter, QFrame, QTabWidget, QTextEdit, QFileDialog, QScrollArea
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWebEngineWidgets import QWebEngineView

from qfluentwidgets import (
    ComboBox, PushButton, PrimaryPushButton, LineEdit,
    CheckBox, InfoBar, InfoBarPosition
)

import matplotlib
matplotlib.use('QtAgg')
import matplotlib.pyplot as plt
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavToolbar
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavToolbar
from matplotlib.figure import Figure
import numpy as np

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun']
plt.rcParams['axes.unicode_minus'] = False

# 计算引擎
from 渡槽设计 import (
    quick_calculate_u,
    quick_calculate_rect,
)

# 共享模块
from 渠系断面设计.styles import P, S, W, E, BG, CARD, BD, T1, T2, INPUT_LABEL_STYLE, INPUT_SECTION_STYLE, INPUT_HINT_STYLE, fluent_question
from 渠系断面设计.export_utils import (
    WORD_EXPORT_AVAILABLE, add_formula_to_doc, try_convert_formula_line, ask_open_file,
    create_styled_doc, doc_add_h1, doc_add_formula, doc_render_calc_text, doc_add_figure,
)
from 渠系断面设计.aqueduct.dxf_export import export_aqueduct_dxf
from 渠系断面设计.formula_renderer import (
    plain_text_to_formula_html, plain_text_to_formula_body,
    load_formula_page, make_plain_html,
    HelpPageBuilder
)
if WORD_EXPORT_AVAILABLE:
    from docx import Document as DocxDocument
    from docx.shared import Pt, Cm


def _e(s):
    """HTML转义"""
    return html_mod.escape(str(s))


class AqueductPanel(QWidget):
    """渡槽水力计算面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.input_params = {}
        self.current_result = None
        self._export_plain_text = ""
        self._init_ui()

    # ================================================================
    # UI 构建
    # ================================================================
    def _init_ui(self):
        main_lay = QHBoxLayout(self)
        main_lay.setContentsMargins(10, 8, 10, 8)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        main_lay.addWidget(splitter)

        # 左侧输入
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        inp_w = QWidget()
        self._build_input(inp_w)
        scroll.setWidget(inp_w)
        scroll.setMinimumWidth(280)
        scroll.setMaximumWidth(420)
        splitter.addWidget(scroll)

        # 右侧输出
        out_w = QWidget()
        self._build_output(out_w)
        splitter.addWidget(out_w)
        splitter.setSizes([340, 900])

    # ----------------------------------------------------------------
    # 输入面板
    # ----------------------------------------------------------------
    def _build_input(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(6)
        grp = QGroupBox("输入参数")
        fl = QVBoxLayout(grp)
        fl.setSpacing(5)

        # 槽身断面类型
        r = QHBoxLayout(); r.addWidget(QLabel("断面类型:"))
        self.section_combo = ComboBox()
        self.section_combo.addItems(["U形", "矩形"])
        self.section_combo.currentTextChanged.connect(self._on_section_type_changed)
        r.addWidget(self.section_combo, 1); fl.addLayout(r)

        # 通用参数
        self.Q_edit = self._field(fl, "设计流量 Q (m³/s):", "5.0")
        self.n_edit = self._field(fl, "糙率 n:", "0.014")
        self.slope_edit = self._field(fl, "水力坡降 1/", "3000")

        fl.addWidget(self._slbl("【流速参数】"))
        self.vmin_edit = self._field(fl, "不淤流速 (m/s):", "0.1")
        self.vmax_edit = self._field(fl, "不冲流速 (m/s):", "100.0")
        fl.addWidget(self._hint("(一般情况下保持默认数值即可)"))

        fl.addWidget(self._slbl("【流量加大】"))
        self.inc_edit = self._field(fl, "流量加大比例 (%):", "")
        self.inc_hint = QLabel("(留空则自动计算)")
        self.inc_hint.setStyleSheet(INPUT_HINT_STYLE)
        fl.addWidget(self.inc_hint)

        fl.addWidget(self._sep())
        fl.addWidget(self._slbl("【可选参数】"))

        # U形参数
        self.u_section_grp = QWidget()
        u_lay = QVBoxLayout(self.u_section_grp)
        u_lay.setContentsMargins(0, 0, 0, 0)
        u_lay.setSpacing(5)
        self.R_lbl, self.R_edit = self._field2(u_lay, "指定内半径 R (m):", "")
        u_lay.addWidget(self._hint("(留空则自动搜索最优半径)"))
        fl.addWidget(self.u_section_grp)

        # 矩形参数
        self.rect_section_grp = QWidget()
        rect_lay = QVBoxLayout(self.rect_section_grp)
        rect_lay.setContentsMargins(0, 0, 0, 0)
        rect_lay.setSpacing(5)
        self.ratio_lbl, self.ratio_edit = self._field2(rect_lay, "深宽比 (H/B):", "")
        rect_lay.addWidget(self._hint("(留空默认0.8)"))
        self.B_lbl, self.B_edit = self._field2(rect_lay, "指定槽宽 B (m):", "")
        rect_lay.addWidget(self._hint("(二选一，都留空按深宽比0.8计算)"))
        rect_lay.addWidget(self._sep())
        rect_lay.addWidget(self._slbl("【倒角参数（可选）】"))
        self.chamfer_angle_lbl, self.chamfer_angle_edit = self._field2(rect_lay, "倒角角度 (度):", "")
        self.chamfer_len_lbl, self.chamfer_len_edit = self._field2(rect_lay, "倒角底边长 (m):", "")
        rect_lay.addWidget(self._hint("(均留空表示无倒角)"))
        fl.addWidget(self.rect_section_grp)
        self.rect_section_grp.hide()

        fl.addWidget(self._sep())
        self.detail_cb = CheckBox("输出详细计算过程")
        self.detail_cb.setChecked(True)
        fl.addWidget(self.detail_cb)

        br = QHBoxLayout()
        cb = PrimaryPushButton("计算"); cb.setCursor(Qt.PointingHandCursor); cb.clicked.connect(self._calculate)
        clb = PushButton("清空"); clb.setCursor(Qt.PointingHandCursor); clb.clicked.connect(self._clear)
        br.addWidget(cb); br.addWidget(clb); fl.addLayout(br)

        er = QHBoxLayout()
        ec = PushButton("导出DXF"); ec.clicked.connect(self._export_dxf)
        ew = PushButton("导出Word"); ew.clicked.connect(self._export_word)
        er.addWidget(ec); er.addWidget(ew)
        fl.addLayout(er)

        lay.addWidget(grp)
        lay.addStretch()

    def _field(self, lay, label, default=""):
        r = QHBoxLayout(); l = QLabel(label); l.setMinimumWidth(140)
        l.setStyleSheet(INPUT_LABEL_STYLE)
        r.addWidget(l); e = LineEdit(); e.setText(default); r.addWidget(e, 1); lay.addLayout(r)
        return e

    def _field2(self, lay, label, default=""):
        r = QHBoxLayout(); l = QLabel(label); l.setMinimumWidth(140)
        l.setStyleSheet(INPUT_LABEL_STYLE)
        r.addWidget(l); e = LineEdit(); e.setText(default); r.addWidget(e, 1); lay.addLayout(r)
        return l, e

    def _slbl(self, t):
        l = QLabel(t); l.setStyleSheet(INPUT_SECTION_STYLE); return l

    def _hint(self, t):
        l = QLabel(t); l.setStyleSheet(INPUT_HINT_STYLE); return l

    def _sep(self):
        f = QFrame(); f.setFrameShape(QFrame.HLine); f.setStyleSheet(f"color:{BD};"); return f

    # ----------------------------------------------------------------
    # 输出面板
    # ----------------------------------------------------------------
    def _build_output(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(0, 0, 0, 0)
        self.notebook = QTabWidget()
        lay.addWidget(self.notebook)

        # Tab1: 计算结果
        t1 = QWidget(); t1l = QVBoxLayout(t1); t1l.setContentsMargins(5, 5, 5, 5)
        grp = QGroupBox("计算结果详情"); gl = QVBoxLayout(grp)
        self.result_text = QWebEngineView()
        gl.addWidget(self.result_text)
        t1l.addWidget(grp)
        self.notebook.addTab(t1, "计算结果")

        # Tab2: 断面图
        t2 = QWidget(); t2l = QVBoxLayout(t2); t2l.setContentsMargins(5, 5, 5, 5)
        self.section_fig = Figure(figsize=(8, 6), dpi=100)
        self.section_canvas = FigureCanvas(self.section_fig)
        self.section_toolbar = NavToolbar(self.section_canvas, t2)
        t2l.addWidget(self.section_toolbar)
        t2l.addWidget(self.section_canvas)
        self.notebook.addTab(t2, "断面图")

        self._show_initial_help()

    # ----------------------------------------------------------------
    # 断面类型切换
    # ----------------------------------------------------------------
    def _on_section_type_changed(self, stype):
        if stype == "U形":
            self.u_section_grp.show()
            self.rect_section_grp.hide()
        else:
            self.u_section_grp.hide()
            self.rect_section_grp.show()

    # ----------------------------------------------------------------
    # 初始帮助
    # ----------------------------------------------------------------
    def _show_initial_help(self):
        h = HelpPageBuilder("渡槽水力计算", '请输入参数后点击“计算”按钮')
        h.section("支持断面类型")
        h.numbered_list([
            ("U形断面", "底部半圆 + 直立侧墙，推荐 f/R = 0.4~0.6，H/(2R) = 0.7~0.9"),
            ("矩形断面", "可选倒角设计，深宽比推荐值 0.6~0.8"),
        ])
        h.section("计算模式总览")
        h.table(
            ["断面类型 / 可选参数填写方式", "程序行为"],
            [
                ["U形 — 留空内半径 R", "自动搜索最优 R（最小化槽身面积）"],
                ["U形 — 指定内半径 R", "固定 R，计算水深并验算超高和流速"],
                ["矩形 — 全部留空", "按默认深宽比 0.8 自动搜索最优槽宽 B"],
                ["矩形 — 指定深宽比 H/B", "按指定深宽比约束，自动搜索最优槽宽 B"],
                ["矩形 — 指定槽宽 B", "固定 B，按深宽比确定槽高 H，反算水深"],
            ]
        )
        h.hint("矩形渡槽：深宽比 H/B 与槽宽 B 不可同时填写（二选一）")
        h.section("曼宁公式")
        h.formula("Q = (1/n) × A × R^(2/3) × i^(1/2)", "流量公式")
        h.formula("V = (1/n) × R^(2/3) × i^(1/2)", "流速公式")
        h.section("矩形渡槽计算流程")
        h.numbered_list([
            ("输入参数", "Q、n、i、α（深宽比约束，默认0.8）"),
            ("加大流量计算", "根据设计流量自动确定加大比例"),
            ("槽宽B搜索", "B ∈ [0.50m, 20.0m]，步长0.01m，目标槽高 H = B × α"),
            ("水深反算", "曼宁公式二分法迭代求解 h"),
            ("槽高确定", "规范9.4.1-2，取设计/加大两工况超高最大值"),
            ("约束检验", "H ≤ H_目标 = B × α，取第一个有效解"),
            ("流速校核", "规范9.4.1-1，推荐 1.0~2.5 m/s"),
        ])
        h.section("U形断面自动搜索逻辑")
        h.text("未指定内半径R时，自动搜索最优R（最小化槽身总面积）：")
        h.bullet_list([
            "搜索范围：R = 0.2m ~ 15.0m，步长 0.01m",
            "f/R 在 0.4~0.6 范围内",
            "H/(2R) 在 0.7~0.9 范围内",
            "设计流量超高 ≥ R/5（规范 9.4.1-2）",
            "加大流量超高 ≥ 0.10m（规范 9.4.1-2）",
        ])
        h.section("加大流量比例规范表")
        h.table(
            ["设计流量 Q (m³/s)", "加大比例"],
            [
                ["Q < 1", "30%"],
                ["1 ≤ Q < 5", "25%"],
                ["5 ≤ Q < 20", "20%"],
                ["20 ≤ Q < 50", "15%"],
                ["50 ≤ Q < 100", "10%"],
                ["Q ≥ 100", "5%"],
            ]
        )
        self.result_text.setHtml(h.build())

    # ----------------------------------------------------------------
    # 辅助：读取输入值
    # ----------------------------------------------------------------
    def _fval(self, edit, default=0.0):
        t = edit.text().strip()
        if not t: return default
        try: return float(t)
        except ValueError: return default

    def _fval_opt(self, edit):
        t = edit.text().strip()
        if not t: return None
        try: return float(t)
        except ValueError: return None

    def _info_parent(self):
        """获取InfoBar的父窗口"""
        w = self.window()
        return w if w else self

    # ================================================================
    # 计算
    # ================================================================
    def _calculate(self):
        stype = self.section_combo.currentText()
        try:
            Q = self._fval(self.Q_edit)
            n = self._fval(self.n_edit)
            slope_inv = self._fval(self.slope_edit)
            v_min = self._fval(self.vmin_edit)
            v_max = self._fval(self.vmax_edit)

            if Q <= 0:
                self._show_error("参数错误", "请输入有效的设计流量 Q（必须大于0）。"); return
            if n <= 0:
                self._show_error("参数错误", "请输入有效的糙率 n（必须大于0）。"); return
            if slope_inv <= 0:
                self._show_error("参数错误", "请输入有效的水力坡降倒数（必须大于0）。"); return
            if v_min >= v_max:
                self._show_error("参数错误", "不淤流速必须小于不冲流速。"); return

            manual_increase = self._fval_opt(self.inc_edit)

            if stype == "U形":
                manual_R = self._fval_opt(self.R_edit)
                self.input_params = {
                    'Q': Q, 'n': n, 'slope_inv': slope_inv,
                    'v_min': v_min, 'v_max': v_max,
                    'section_type': stype,
                    'manual_R': manual_R,
                    'manual_increase': manual_increase
                }
                result = quick_calculate_u(
                    Q=Q, n=n, slope_inv=slope_inv,
                    v_min=v_min, v_max=v_max,
                    manual_R=manual_R,
                    manual_increase_percent=manual_increase
                )
            else:
                manual_B = self._fval_opt(self.B_edit)
                depth_width_ratio = self._fval_opt(self.ratio_edit)

                # 倒角参数完整性检查
                chamfer_angle_txt = self.chamfer_angle_edit.text().strip()
                chamfer_len_txt = self.chamfer_len_edit.text().strip()
                has_angle = bool(chamfer_angle_txt)
                has_len = bool(chamfer_len_txt)

                if has_angle != has_len:
                    filled = "倒角角度" if has_angle else "倒角底边长"
                    missing = "倒角底边长" if has_angle else "倒角角度"
                    ignore = fluent_question(
                        self.window(),
                        "倒角参数不完整",
                        f"您填写了「{filled}」但未填写「{missing}」。\n\n"
                        f"点击「忽略倒角继续」将按普通矩形断面计算；\n"
                        f"点击「返回补全」可补全参数后重新计算。",
                        yes_text="忽略倒角继续",
                        no_text="返回补全"
                    )
                    if not ignore:
                        return
                    chamfer_angle = 0
                    chamfer_length = 0
                else:
                    chamfer_angle = self._fval(self.chamfer_angle_edit, 0)
                    chamfer_length = self._fval(self.chamfer_len_edit, 0)
                self.input_params = {
                    'Q': Q, 'n': n, 'slope_inv': slope_inv,
                    'v_min': v_min, 'v_max': v_max,
                    'section_type': stype,
                    'manual_B': manual_B,
                    'depth_width_ratio': depth_width_ratio,
                    'chamfer_angle': chamfer_angle,
                    'chamfer_length': chamfer_length,
                    'manual_increase': manual_increase
                }
                result = quick_calculate_rect(
                    Q=Q, n=n, slope_inv=slope_inv,
                    v_min=v_min, v_max=v_max,
                    depth_width_ratio=depth_width_ratio,
                    chamfer_angle=chamfer_angle,
                    chamfer_length=chamfer_length,
                    manual_increase_percent=manual_increase,
                    manual_B=manual_B
                )

            self.current_result = result

            # 更新加大比例提示
            if result.get('success') and 'increase_percent' in result:
                ap = result['increase_percent']
                src = "指定" if self.inc_edit.text().strip() else "自动计算"
                self.inc_hint.setText(f"({src}: {ap:.1f}%)")

            self._update_result_display(result)
            self._update_section_plot(result)

        except Exception as e:
            self._show_error("计算错误", f"计算过程出错: {str(e)}")

    def _show_error(self, title, msg):
        out = []
        out.append("=" * 70)
        out.append(f"  {title}")
        out.append("=" * 70)
        out.append("")
        out.append(msg)
        out.append("")
        out.append("-" * 70)
        out.append("请修正后重新计算。")
        out.append("=" * 70)
        self.result_text.setHtml(make_plain_html("\n".join(out)))

    # ================================================================
    # 结果显示分发
    # ================================================================
    def _update_result_display(self, result):
        if not result['success']:
            self._show_error("计算失败", result.get('error_message', '未知错误'))
            return
        stype = result.get('section_type', 'U形')
        detail = self.detail_cb.isChecked()
        if stype == 'U形':
            if detail: self._show_u_detail(result)
            else: self._show_u_brief(result)
        else:
            if detail: self._show_rect_detail(result)
            else: self._show_rect_brief(result)

    # ================================================================
    # U形 - 简要结果
    # ================================================================
    def _show_u_brief(self, result):
        p = self.input_params
        Q, n = p['Q'], p['n']
        slope_inv = p['slope_inv']; i = 1.0 / slope_inv

        o = []
        o.append("=" * 70)
        o.append("              渡槽水力计算结果（U形断面）")
        o.append("=" * 70)
        o.append("")
        o.append("【输入参数】")
        o.append("")
        o.append(f"  1. 断面类型:")
        o.append(f"     U形")
        o.append("")
        o.append(f"  2. 设计流量:")
        o.append(f"     Q = {Q:.3f} m³/s")
        o.append("")
        o.append(f"  3. 糙率:")
        o.append(f"     n = {n}")
        o.append("")
        o.append(f"  4. 水力坡降:")
        o.append(f"     = 1/{int(slope_inv)}")
        o.append("")
        o.append(f"  5. 不淤流速:")
        o.append(f"     = {p['v_min']} m/s")
        o.append("")
        o.append(f"  6. 不冲流速:")
        o.append(f"     = {p['v_max']} m/s")
        o.append("")
        o.append("【设计方法】")
        o.append("")
        o.append(f"  1. 采用方法:")
        o.append(f"     {result['design_method']}")
        o.append("")
        o.append("【断面尺寸】")
        o.append(f"  内半径 R = {result['R']:.3f} m")
        o.append(f"  直段高度 f = {result['f']:.3f} m")
        o.append(f"  槽宽 B = 2R = {result['B']:.3f} m")
        o.append(f"  f/R = {result['f_R']:.3f}")
        o.append(f"  H/(2R) = {result['H_B']:.3f}")
        o.append(f"  槽身总高 H = {result['H_total']:.3f} m")
        o.append("")
        o.append("【设计工况】")
        o.append(f"  设计水深 h = {result['h_design']:.3f} m")
        o.append(f"  设计流速 V = {result['V_design']:.3f} m/s")
        o.append(f"  过水面积 A = {result['A_design']:.3f} m²")
        o.append(f"  水力半径 R水 = {result['R_hyd_design']:.3f} m")
        o.append("")
        o.append("【加大流量工况】")
        inc_src = "(指定)" if p.get('manual_increase') else "(自动计算)"
        o.append(f"  流量加大比例 = {result['increase_percent']:.1f}% {inc_src}")
        o.append(f"  加大流量 Q加大 = {result['Q_increased']:.3f} m³/s")
        o.append(f"  加大水深 h加大 = {result['h_increased']:.3f} m")
        o.append(f"  加大流速 V加大 = {result['V_increased']:.3f} m/s")
        o.append(f"  超高 Fb = {result['Fb']:.3f} m")
        o.append("")

        # 警告信息
        if result.get('warning_message'):
            o.append("【流速提示】")
            o.append(f"  {result['warning_message']}")
            o.append("")

        o.append("【验证结果】")
        V_d = result['V_design']
        vel_ok = 1.0 <= V_d <= 2.5
        o.append(f"  流速验证: V={V_d:.3f}m/s (推荐1.0~2.5) → {'✓ 通过' if vel_ok else '⚠ 超出推荐范围'}")
        Fb = result['Fb']
        R_val = result['R']
        Fb_ok = Fb >= 0.10
        Fb_design_ok = (result['H_total'] - result['h_design']) >= R_val / 5
        o.append(f"  超高验证(加大): Fb={Fb:.3f}m ≥ 0.10m → {'✓ 通过' if Fb_ok else '✗ 未通过'}")
        o.append(f"  超高验证(设计): ≥ R/5={R_val/5:.3f}m → {'✓ 通过' if Fb_design_ok else '✗ 未通过'}")
        all_pass = Fb_ok and Fb_design_ok
        o.append("")
        o.append("=" * 70)
        o.append(f"  综合验证结果: {'全部通过 ✓' if all_pass else '未通过 ✗'}")
        o.append("=" * 70)
        txt = "\n".join(o)
        self._export_plain_text = txt
        load_formula_page(self.result_text, plain_text_to_formula_html(txt))

    # ================================================================
    # U形 - 详细结果
    # ================================================================
    def _show_u_detail(self, result):
        p = self.input_params
        Q, n = p['Q'], p['n']
        slope_inv = p['slope_inv']; i = 1.0 / slope_inv
        v_min, v_max = p['v_min'], p['v_max']
        R_val = result['R']; f_val = result['f']; B = result['B']
        H_total = result['H_total']
        h_d = result['h_design']; V_d = result['V_design']
        A_d = result['A_design']; P_d = result['P_design']
        R_hyd = result['R_hyd_design']
        inc_pct = result['increase_percent']
        Q_inc = result['Q_increased']
        h_inc = result['h_increased']; V_inc = result['V_increased']
        A_inc = result.get('A_increased', 0); P_inc = result.get('P_increased', 0)
        R_hyd_inc = result.get('R_hyd_increased', 0)
        Fb = result['Fb']
        inc_src = "(指定)" if p.get('manual_increase') else "(自动计算)"

        o = []
        o.append("=" * 70)
        o.append("              渡槽水力计算结果（U形断面）")
        o.append("=" * 70)
        o.append("")
        o.append("【一、输入参数】")
        o.append("")
        _n = 1
        o.append(f"  {_n}. 断面类型:")
        o.append(f"     U形")
        o.append("")
        _n += 1
        o.append(f"  {_n}. 设计流量:")
        o.append(f"     Q = {Q:.3f} m³/s")
        o.append("")
        _n += 1
        o.append(f"  {_n}. 糙率:")
        o.append(f"     n = {n}")
        o.append("")
        _n += 1
        o.append(f"  {_n}. 水力坡降:")
        o.append(f"     = 1/{int(slope_inv)}")
        o.append("")
        _n += 1
        o.append(f"  {_n}. 不淤流速:")
        o.append(f"     = {v_min} m/s")
        o.append("")
        _n += 1
        o.append(f"  {_n}. 不冲流速:")
        o.append(f"     = {v_max} m/s")
        o.append("")
        if p.get('manual_R'):
            _n += 1
            o.append(f"  {_n}. 指定内半径:")
            o.append(f"     R = {p['manual_R']} m")
            o.append("")
        if p.get('manual_increase'):
            _n += 1
            o.append(f"  {_n}. 指定加大比例:")
            o.append(f"     = {p['manual_increase']}%")
            o.append("")

        o.append("【二、断面尺寸】")
        o.append("")
        o.append("  1. 内半径:")
        o.append(f"     R = {R_val:.2f} m")
        o.append("")
        o.append("  2. 槽宽计算:")
        o.append(f"     B = 2 × R")
        o.append(f"       = 2 × {R_val:.2f}")
        o.append(f"       = {B:.2f} m")
        o.append("")
        o.append("  3. 直段高度:")
        o.append(f"     f = {f_val:.2f} m")
        o.append(f"     f/R = {f_val:.2f} / {R_val:.2f} = {result['f_R']:.3f}")
        o.append("")
        o.append("  4. 槽身总高计算:")
        o.append(f"     H = R + f")
        o.append(f"       = {R_val:.2f} + {f_val:.2f}")
        o.append(f"       = {H_total:.2f} m")
        o.append("")
        o.append("  5. H/B比值计算:")
        H_B_ratio = H_total / B if B > 0 else 0
        o.append(f"     H/B = 槽身总高 ÷ 槽宽")
        o.append(f"         = {H_total:.2f} ÷ {B:.2f}")
        o.append(f"         = {H_B_ratio:.3f}")
        o.append("")

        o.append("【三、设计流量工况】")
        o.append("")
        o.append("  1. 设计水深计算:")
        o.append(f"     根据设计流量 Q = {Q:.3f} m³/s，利用曼宁公式反算水深:")
        o.append(f"     h = {h_d:.3f} m")
        o.append("")

        o.append("  2. 过水面积计算 (U形断面):")
        if h_d <= R_val:
            theta_val = math.acos((R_val - h_d) / R_val) if R_val > 0 else 0
            o.append(f"     当 h ≤ R 时:")
            o.append(f"     θ = arccos((R-h)/R) = arccos(({R_val:.2f}-{h_d:.3f})/{R_val:.2f})")
            o.append(f"       = {math.degrees(theta_val):.2f}° = {theta_val:.4f} rad")
            o.append(f"     A = R² × (θ - sinθ×cosθ)")
            o.append(f"       = {R_val:.2f}² × ({theta_val:.4f} - {math.sin(theta_val):.4f}×{math.cos(theta_val):.4f})")
            o.append(f"       = {A_d:.3f} m²")
        else:
            o.append(f"     当 h > R 时:")
            o.append(f"     A = πR²/2 + 2R×(h-R)")
            o.append(f"       = π×{R_val:.2f}²/2 + 2×{R_val:.2f}×({h_d:.3f}-{R_val:.2f})")
            o.append(f"       = {math.pi*R_val**2/2:.3f} + {2*R_val*(h_d-R_val):.3f}")
            o.append(f"       = {A_d:.3f} m²")
        o.append("")

        o.append("  3. 湿周计算 (U形断面):")
        if h_d <= R_val:
            o.append(f"     当 h ≤ R 时:")
            o.append(f"     P = 2Rθ = 2×{R_val:.2f}×{theta_val:.4f}")
            o.append(f"       = {P_d:.3f} m")
        else:
            o.append(f"     当 h > R 时:")
            o.append(f"     P = πR + 2×(h-R)")
            o.append(f"       = π×{R_val:.2f} + 2×({h_d:.3f}-{R_val:.2f})")
            o.append(f"       = {math.pi*R_val:.3f} + {2*(h_d-R_val):.3f}")
            o.append(f"       = {P_d:.3f} m")
        o.append("")

        o.append("  4. 水力半径计算:")
        o.append(f"     R水 = A / P")
        o.append(f"        = {A_d:.3f} / {P_d:.3f}")
        o.append(f"        = {R_hyd:.3f} m")
        o.append("")

        o.append("  5. 设计流速计算 (曼宁公式):")
        o.append(f"     V = (1/n) × R水^(2/3) × i^(1/2)")
        o.append(f"       = (1/{n}) × {R_hyd:.3f}^(2/3) × {i:.6f}^(1/2)")
        if R_hyd > 0:
            o.append(f"       = {1/n:.2f} × {R_hyd**(2/3):.4f} × {math.sqrt(i):.6f}")
        o.append(f"       = {V_d:.3f} m/s")
        o.append("")

        o.append("  6. 计算流量验证:")
        o.append(f"     Q计算 = A × V")
        o.append(f"          = {A_d:.3f} × {V_d:.3f}")
        o.append(f"          = {A_d * V_d:.3f} m³/s")
        o.append(f"     误差 = {abs(A_d * V_d - Q) / Q * 100:.2f}%")
        o.append("")

        o.append("【四、加大流量工况】")
        o.append("")
        o.append("  1. 加大流量计算:")
        o.append(f"      流量加大比例 = {inc_pct:.1f}% {inc_src}")
        o.append(f"      Q加大 = Q × (1 + {inc_pct:.1f}%)")
        o.append(f"           = {Q:.3f} × {1 + inc_pct/100:.3f}")
        o.append(f"           = {Q_inc:.3f} m³/s")
        o.append("")
        o.append("  2. 加大水深计算:")
        o.append(f"      根据加大流量 Q加大 = {Q_inc:.3f} m³/s，利用曼宁公式反算水深:")
        o.append(f"      h加大 = {h_inc:.3f} m")
        o.append("")

        o.append("  3. 过水面积计算 (U形断面):")
        if h_inc <= R_val:
            theta_inc = math.acos((R_val - h_inc) / R_val) if R_val > 0 else 0
            o.append(f"      当 h加大 ≤ R 时:")
            o.append(f"      θ = arccos((R-h加大)/R) = arccos(({R_val:.2f}-{h_inc:.3f})/{R_val:.2f})")
            o.append(f"        = {math.degrees(theta_inc):.2f}° = {theta_inc:.4f} rad")
            o.append(f"      A加大 = R² × (θ - sinθ×cosθ)")
            o.append(f"           = {R_val:.2f}² × ({theta_inc:.4f} - {math.sin(theta_inc):.4f}×{math.cos(theta_inc):.4f})")
            o.append(f"           = {A_inc:.3f} m²")
        else:
            o.append(f"      当 h加大 > R 时:")
            o.append(f"      A加大 = πR²/2 + 2R×(h加大-R)")
            o.append(f"           = π×{R_val:.2f}²/2 + 2×{R_val:.2f}×({h_inc:.3f}-{R_val:.2f})")
            o.append(f"           = {math.pi*R_val**2/2:.3f} + {2*R_val*(h_inc-R_val):.3f}")
            o.append(f"           = {A_inc:.3f} m²")
        o.append("")

        o.append("  4. 湿周计算 (U形断面):")
        if h_inc <= R_val:
            o.append(f"      当 h加大 ≤ R 时:")
            o.append(f"      P加大 = 2Rθ = 2×{R_val:.2f}×{theta_inc:.4f}")
            o.append(f"           = {P_inc:.3f} m")
        else:
            o.append(f"      当 h加大 > R 时:")
            o.append(f"      P加大 = πR + 2×(h加大-R)")
            o.append(f"           = π×{R_val:.2f} + 2×({h_inc:.3f}-{R_val:.2f})")
            o.append(f"           = {math.pi*R_val:.3f} + {2*(h_inc-R_val):.3f}")
            o.append(f"           = {P_inc:.3f} m")
        o.append("")

        o.append("  5. 水力半径计算:")
        o.append(f"      R加大 = A加大 / P加大")
        o.append(f"           = {A_inc:.3f} / {P_inc:.3f}")
        o.append(f"           = {R_hyd_inc:.3f} m")
        o.append("")

        o.append("  6. 加大流速计算 (曼宁公式):")
        o.append(f"      V加大 = (1/n) × R加大^(2/3) × i^(1/2)")
        o.append(f"           = (1/{n}) × {R_hyd_inc:.3f}^(2/3) × {i:.6f}^(1/2)")
        if R_hyd_inc > 0:
            o.append(f"           = {1/n:.2f} × {R_hyd_inc**(2/3):.4f} × {math.sqrt(i):.6f}")
        o.append(f"           = {V_inc:.3f} m/s")
        o.append("")

        o.append("  7. 流量校核:")
        o.append(f"      Q计算 = A加大 × V加大")
        o.append(f"           = {A_inc:.3f} × {V_inc:.3f}")
        o.append(f"           = {A_inc * V_inc:.3f} m³/s")
        if Q_inc > 0:
            o.append(f"      误差 = {abs(A_inc * V_inc - Q_inc) / Q_inc * 100:.2f}%")
        o.append("")

        o.append("  8. 超高计算:")
        o.append(f"      Fb = H - h加大 = {H_total:.2f} - {h_inc:.3f} = {Fb:.3f} m")
        o.append("")

        # 警告信息
        if result.get('warning_message'):
            o.append("【流速提示】")
            o.append(f"  {result['warning_message']}")
            o.append("")

        o.append("【五、验证】")
        o.append("")

        v_recommended_min = 1.0
        v_recommended_max = 2.5
        vel_ok = v_recommended_min <= V_d <= v_recommended_max
        o.append(f"  1. 流速验证（规范 9.4.1-1）")
        o.append(f"     规范要求: 1.0 ≤ V ≤ 2.5 m/s")
        o.append(f"     计算结果: V = {V_d:.3f} m/s")
        if vel_ok:
            o.append(f"     结果: 通过 ✓")
        else:
            if V_d < v_recommended_min:
                o.append(f"     结果: 超出推荐范围 ⚠")
                o.append(f"     提示: 流速过小，可能造成淤积，建议调整断面尺寸")
            else:
                o.append(f"     结果: 超出推荐范围 ⚠")
                o.append(f"     提示: 流速过大，可能造成冲刷，建议调整断面尺寸")
        o.append("")

        o.append(f"  2. 超高验证（规范 9.4.1-2）")
        Fb_design_min = R_val / 5
        Fb_design = H_total - h_d
        Fb_inc_min = 0.10
        fb_design_ok = Fb_design >= Fb_design_min
        fb_inc_ok = Fb >= Fb_inc_min
        o.append(f"     断面类型: U形")
        o.append(f"     规范要求:")
        o.append(f"       - 设计流量: 超高不应小于槽身直径的1/10 (即2R/10 = R/5 = {Fb_design_min:.3f} m)")
        o.append(f"       - 加大流量: 超高不应小于 0.10 m")
        o.append(f"")
        o.append(f"     计算结果:")
        o.append(f"       - 设计流量超高: Fb_设计 = H - h_设计 = {H_total:.2f} - {h_d:.3f} = {Fb_design:.3f} m")
        o.append(f"       - 加大流量超高: Fb_加大 = H - h_加大 = {H_total:.2f} - {h_inc:.3f} = {Fb:.3f} m")
        o.append(f"")
        o.append(f"     验证结果:")
        o.append(f"       - 设计流量: {Fb_design:.3f} {'≥' if fb_design_ok else '<'} {Fb_design_min:.3f} → {'通过 ✓' if fb_design_ok else '未通过 ✗'}")
        o.append(f"       - 加大流量: {Fb:.3f} {'≥' if fb_inc_ok else '<'} {Fb_inc_min:.2f} → {'通过 ✓' if fb_inc_ok else '未通过 ✗'}")
        o.append("")

        all_pass = fb_inc_ok and fb_design_ok
        o.append("=" * 70)
        o.append(f"  综合验证结果: {'全部通过 ✓' if all_pass else '未通过 ✗'}")
        o.append("=" * 70)
        txt = "\n".join(o)
        self._export_plain_text = txt
        load_formula_page(self.result_text, plain_text_to_formula_html(txt))

    # ================================================================
    # 矩形 - 简要结果
    # ================================================================
    def _show_rect_brief(self, result):
        p = self.input_params
        Q, n = p['Q'], p['n']
        slope_inv = p['slope_inv']
        inc_src = "(指定)" if p.get('manual_increase') else "(自动计算)"

        o = []
        o.append("=" * 70)
        o.append("              渡槽水力计算结果（矩形断面）")
        o.append("=" * 70)
        o.append("")
        o.append("【输入参数】")
        o.append("")
        o.append(f"  1. 断面类型:")
        o.append(f"     矩形")
        o.append("")
        o.append(f"  2. 设计流量:")
        o.append(f"     Q = {Q:.3f} m³/s")
        o.append("")
        o.append(f"  3. 糙率:")
        o.append(f"     n = {n}")
        o.append("")
        o.append(f"  4. 水力坡降:")
        o.append(f"     = 1/{int(slope_inv)}")
        o.append("")
        o.append(f"  5. 不淤流速:")
        o.append(f"     = {p['v_min']} m/s")
        o.append("")
        o.append(f"  6. 不冲流速:")
        o.append(f"     = {p['v_max']} m/s")
        o.append("")
        o.append("【设计方法】")
        o.append("")
        o.append(f"  1. 采用方法:")
        o.append(f"     {result['design_method']}")
        o.append("")
        o.append("【断面尺寸】")
        o.append(f"  槽宽 B = {result['B']:.3f} m")
        o.append(f"  槽身总高 H = {result['H_total']:.3f} m")
        B_val = result['B']; H_val = result['H_total']
        H_B_ratio = H_val / B_val if B_val > 0 else 0
        o.append(f"  H/B = {H_B_ratio:.3f}")
        if result.get('has_chamfer'):
            o.append(f"  倒角角度 = {result['chamfer_angle']}°")
            o.append(f"  倒角底边长 = {result['chamfer_length']} m")
        o.append("")
        o.append("【设计工况】")
        o.append(f"  设计水深 h = {result['h_design']:.3f} m")
        o.append(f"  设计流速 V = {result['V_design']:.3f} m/s")
        o.append(f"  过水面积 A = {result['A_design']:.3f} m²")
        o.append(f"  水力半径 R = {result['R_hyd_design']:.3f} m")
        o.append("")
        o.append("【加大流量工况】")
        o.append(f"  流量加大比例 = {result['increase_percent']:.1f}% {inc_src}")
        o.append(f"  加大流量 Q加大 = {result['Q_increased']:.3f} m³/s")
        o.append(f"  加大水深 h加大 = {result['h_increased']:.3f} m")
        o.append(f"  加大流速 V加大 = {result['V_increased']:.3f} m/s")
        o.append(f"  超高 Fb = {result['Fb']:.3f} m")
        o.append("")

        if result.get('warning_message'):
            o.append("【流速提示】")
            o.append(f"  {result['warning_message']}")
            o.append("")

        o.append("【验证结果】")
        V_d = result['V_design']
        vel_ok = 1.0 <= V_d <= 2.5
        o.append(f"  流速验证: V={V_d:.3f}m/s (推荐1.0~2.5) → {'✓ 通过' if vel_ok else '⚠ 超出推荐范围'}")
        Fb = result['Fb']
        h_d = result['h_design']
        Fb_inc_ok = Fb >= 0.10
        Fb_design_min = h_d / 12 + 0.05
        Fb_design = result['H_total'] - h_d
        Fb_design_ok = Fb_design >= Fb_design_min
        o.append(f"  超高验证(加大): Fb={Fb:.3f}m ≥ 0.10m → {'✓ 通过' if Fb_inc_ok else '✗ 未通过'}")
        o.append(f"  超高验证(设计): Fb={Fb_design:.3f}m ≥ h/12+0.05={Fb_design_min:.3f}m → {'✓ 通过' if Fb_design_ok else '✗ 未通过'}")
        all_pass = Fb_inc_ok and Fb_design_ok
        o.append("")
        o.append("=" * 70)
        o.append(f"  综合验证结果: {'全部通过 ✓' if all_pass else '未通过 ✗'}")
        o.append("=" * 70)
        txt = "\n".join(o)
        self._export_plain_text = txt
        load_formula_page(self.result_text, plain_text_to_formula_html(txt))

    # ================================================================
    # 矩形 - 详细结果
    # ================================================================
    def _show_rect_detail(self, result):
        p = self.input_params
        Q, n = p['Q'], p['n']
        slope_inv = p['slope_inv']; i = 1.0 / slope_inv
        v_min, v_max = p['v_min'], p['v_max']
        B = result['B']; H_total = result['H_total']
        h_d = result['h_design']; V_d = result['V_design']
        A_d = result['A_design']; P_d = result['P_design']
        R_hyd = result['R_hyd_design']
        inc_pct = result['increase_percent']
        Q_inc = result['Q_increased']
        h_inc = result['h_increased']; V_inc = result['V_increased']
        A_inc = result.get('A_increased', 0); P_inc = result.get('P_increased', 0)
        R_hyd_inc = result.get('R_hyd_increased', 0)
        Fb = result['Fb']
        inc_src = "(指定)" if p.get('manual_increase') else "(自动计算)"
        has_chamfer = result.get('has_chamfer', False)
        ratio = result.get('depth_width_ratio', 0)

        o = []
        o.append("=" * 70)
        o.append("              渡槽水力计算结果（矩形断面）")
        o.append("=" * 70)
        o.append("")
        o.append("【一、输入参数】")
        o.append("")
        _n = 1
        o.append(f"  {_n}. 断面类型:")
        o.append(f"     矩形")
        o.append("")
        _n += 1
        o.append(f"  {_n}. 设计流量:")
        o.append(f"     Q = {Q:.3f} m³/s")
        o.append("")
        _n += 1
        o.append(f"  {_n}. 糙率:")
        o.append(f"     n = {n}")
        o.append("")
        _n += 1
        o.append(f"  {_n}. 水力坡降:")
        o.append(f"     = 1/{int(slope_inv)}")
        o.append("")
        _n += 1
        o.append(f"  {_n}. 不淤流速:")
        o.append(f"     = {v_min} m/s")
        o.append("")
        _n += 1
        o.append(f"  {_n}. 不冲流速:")
        o.append(f"     = {v_max} m/s")
        o.append("")
        if p.get('manual_B'):
            _n += 1
            o.append(f"  {_n}. 指定槽宽:")
            o.append(f"     B = {p['manual_B']} m")
            o.append("")
        if p.get('depth_width_ratio'):
            _n += 1
            o.append(f"  {_n}. 指定深宽比:")
            o.append(f"     = {p['depth_width_ratio']}")
            o.append("")
        if has_chamfer:
            _n += 1
            o.append(f"  {_n}. 倒角角度:")
            o.append(f"     = {result['chamfer_angle']}°")
            o.append("")
            _n += 1
            o.append(f"  {_n}. 倒角底边长:")
            o.append(f"     = {result['chamfer_length']} m")
            o.append("")
        if p.get('manual_increase'):
            _n += 1
            o.append(f"  {_n}. 指定加大比例:")
            o.append(f"     = {p['manual_increase']}%")
            o.append("")

        o.append("【二、断面尺寸】")
        o.append("")
        o.append("  1. 断面尺寸:")
        o.append(f"     槽宽 B = {B:.2f} m")
        o.append(f"     深宽比 = {ratio:.3f}")
        o.append("")

        # 计算两个工况的超高需求
        Fb_design_min = h_d / 12 + 0.05
        H_design_required = h_d + Fb_design_min
        H_inc_required = h_inc + 0.10

        o.append("  2. 槽高计算（规范 9.4.1-2）:")
        o.append(f"     设计流量: H1 = h设计 + (h设计/12 + 0.05)")
        o.append(f"              = {h_d:.3f} + ({h_d:.3f}/12 + 0.05)")
        o.append(f"              = {h_d:.3f} + {Fb_design_min:.3f}")
        o.append(f"              = {H_design_required:.3f} m")
        o.append(f"     加大流量: H2 = h加大 + 0.10")
        o.append(f"              = {h_inc:.3f} + 0.10")
        o.append(f"              = {H_inc_required:.3f} m")
        o.append(f"     取最大值: H = max({H_design_required:.3f}, {H_inc_required:.3f})")
        o.append(f"              = {max(H_design_required, H_inc_required):.3f} m")
        o.append(f"     向上取整: H = {H_total:.2f} m")
        o.append("")

        o.append("  3. H/B比值计算:")
        H_B_ratio = H_total / B if B > 0 else 0
        o.append(f"     H/B = 槽身总高 ÷ 槽宽")
        o.append(f"         = {H_total:.2f} ÷ {B:.2f}")
        o.append(f"         = {H_B_ratio:.3f}")
        o.append("")

        if has_chamfer:
            o.append(f"  倒角角度 = {result.get('chamfer_angle', 0):.1f}°")
            o.append(f"  倒角底边 = {result.get('chamfer_length', 0):.2f} m")
            o.append("")

        o.append("【三、设计流量工况】")
        o.append("")
        o.append("  1. 设计水深计算:")
        o.append(f"     根据设计流量 Q = {Q:.3f} m³/s，利用曼宁公式反算水深:")
        o.append(f"     h = {h_d:.3f} m")
        o.append("")

        if has_chamfer:
            chamfer_angle_val = result.get('chamfer_angle', 0)
            chamfer_length_val = result.get('chamfer_length', 0)
            chamfer_height_val = chamfer_length_val * math.tan(math.radians(chamfer_angle_val)) if chamfer_angle_val > 0 else 0

            o.append("  2. 过水面积计算 (矩形断面-带倒角):")
            if h_d >= chamfer_height_val:
                chamfer_area_val = 0.5 * chamfer_length_val * chamfer_height_val
                A_rect = B * h_d
                o.append(f"     倒角高度 = 倒角底边 × tan(倒角角度)")
                o.append(f"             = {chamfer_length_val:.2f} × tan({chamfer_angle_val:.1f}°) = {chamfer_height_val:.3f} m")
                o.append(f"     A = B×h - 2×(½×倒角底边×倒角高度)")
                o.append(f"       = {B:.2f}×{h_d:.3f} - 2×(½×{chamfer_length_val:.2f}×{chamfer_height_val:.3f})")
                o.append(f"       = {A_rect:.3f} - {2*chamfer_area_val:.3f}")
                o.append(f"       = {A_d:.3f} m²")
            else:
                o.append(f"     倒角高度 = {chamfer_height_val:.3f} m > 水深 h = {h_d:.3f} m")
                o.append(f"     A = B×h - (倒角底边/倒角高度)×h²")
                o.append(f"       = {B:.2f}×{h_d:.3f} - ({chamfer_length_val:.2f}/{chamfer_height_val:.3f})×{h_d:.3f}²")
                o.append(f"       = {A_d:.3f} m²")
            o.append("")

            o.append("  3. 湿周计算 (矩形断面-带倒角):")
            if h_d >= chamfer_height_val:
                hyp_val = chamfer_length_val / math.cos(math.radians(chamfer_angle_val)) if chamfer_angle_val > 0 else chamfer_length_val
                wall_above = h_d - chamfer_height_val
                bottom_width = B - 2 * chamfer_length_val
                o.append(f"     倒角斜边 = 倒角底边/cos(倒角角度) = {chamfer_length_val:.2f}/cos({chamfer_angle_val:.1f}°) = {hyp_val:.3f} m")
                o.append(f"     P = (B-2×倒角底边) + 2×倒角斜边 + 2×(h-倒角高度)")
                o.append(f"       = ({B:.2f}-2×{chamfer_length_val:.2f}) + 2×{hyp_val:.3f} + 2×({h_d:.3f}-{chamfer_height_val:.3f})")
                o.append(f"       = {bottom_width:.2f} + {2*hyp_val:.3f} + {2*wall_above:.3f}")
                o.append(f"       = {P_d:.3f} m")
            else:
                o.append(f"     P = (B-2×倒角底边) + 2×h/sin(倒角角度)")
                o.append(f"       = ({B:.2f}-2×{chamfer_length_val:.2f}) + 2×{h_d:.3f}/sin({chamfer_angle_val:.1f}°)")
                o.append(f"       = {P_d:.3f} m")
            o.append("")
        else:
            o.append("  2. 过水面积计算 (矩形断面):")
            o.append(f"     A = B × h")
            o.append(f"       = {B:.2f} × {h_d:.3f}")
            o.append(f"       = {A_d:.3f} m²")
            o.append("")

            o.append("  3. 湿周计算 (矩形断面):")
            o.append(f"     P = B + 2×h")
            o.append(f"       = {B:.2f} + 2×{h_d:.3f}")
            o.append(f"       = {B:.2f} + {2*h_d:.3f}")
            o.append(f"       = {P_d:.3f} m")
            o.append("")

        o.append("  4. 水力半径计算:")
        o.append(f"     R = A / P")
        o.append(f"       = {A_d:.3f} / {P_d:.3f}")
        o.append(f"       = {R_hyd:.3f} m")
        o.append("")

        o.append("  5. 设计流速计算 (曼宁公式):")
        o.append(f"     V = (1/n) × R^(2/3) × i^(1/2)")
        o.append(f"       = (1/{n}) × {R_hyd:.3f}^(2/3) × {i:.6f}^(1/2)")
        if R_hyd > 0:
            o.append(f"       = {1/n:.2f} × {R_hyd**(2/3):.4f} × {math.sqrt(i):.6f}")
        o.append(f"       = {V_d:.3f} m/s")
        o.append("")

        o.append("  6. 计算流量验证:")
        o.append(f"     Q计算 = A × V")
        o.append(f"          = {A_d:.3f} × {V_d:.3f}")
        o.append(f"          = {A_d * V_d:.3f} m³/s")
        o.append(f"     误差 = {abs(A_d * V_d - Q) / Q * 100:.2f}%")
        o.append("")

        o.append("【四、加大流量工况】")
        o.append("")
        o.append("  1. 加大流量计算:")
        o.append(f"      流量加大比例 = {inc_pct:.1f}% {inc_src}")
        o.append(f"      Q加大 = Q × (1 + {inc_pct:.1f}%)")
        o.append(f"           = {Q:.3f} × {1 + inc_pct/100:.3f}")
        o.append(f"           = {Q_inc:.3f} m³/s")
        o.append("")
        o.append("  2. 加大水深计算:")
        o.append(f"      根据加大流量 Q加大 = {Q_inc:.3f} m³/s，利用曼宁公式反算水深:")
        o.append(f"      h加大 = {h_inc:.3f} m")
        o.append("")

        if has_chamfer:
            o.append("  3. 过水面积计算 (矩形断面-带倒角):")
            if h_inc >= chamfer_height_val:
                chamfer_area_val_inc = 0.5 * chamfer_length_val * chamfer_height_val
                A_rect_inc = B * h_inc
                o.append(f"      倒角高度 = {chamfer_length_val:.2f} × tan({chamfer_angle_val:.1f}°) = {chamfer_height_val:.3f} m")
                o.append(f"      A加大 = B×h加大 - 2×(½×倒角底边×倒角高度)")
                o.append(f"           = {B:.2f}×{h_inc:.3f} - 2×(½×{chamfer_length_val:.2f}×{chamfer_height_val:.3f})")
                o.append(f"           = {A_rect_inc:.3f} - {2*chamfer_area_val_inc:.3f}")
                o.append(f"           = {A_inc:.3f} m²")
            else:
                o.append(f"      倒角高度 = {chamfer_height_val:.3f} m > 水深 h加大 = {h_inc:.3f} m")
                o.append(f"      A加大 = B×h加大 - (倒角底边/倒角高度)×h加大²")
                o.append(f"           = {B:.2f}×{h_inc:.3f} - ({chamfer_length_val:.2f}/{chamfer_height_val:.3f})×{h_inc:.3f}²")
                o.append(f"           = {A_inc:.3f} m²")
            o.append("")

            o.append("  4. 湿周计算 (矩形断面-带倒角):")
            if h_inc >= chamfer_height_val:
                hyp_val_inc = chamfer_length_val / math.cos(math.radians(chamfer_angle_val)) if chamfer_angle_val > 0 else chamfer_length_val
                wall_above_inc = h_inc - chamfer_height_val
                bottom_width_inc = B - 2 * chamfer_length_val
                o.append(f"      倒角斜边 = {chamfer_length_val:.2f}/cos({chamfer_angle_val:.1f}°) = {hyp_val_inc:.3f} m")
                o.append(f"      P加大 = (B-2×倒角底边) + 2×倒角斜边 + 2×(h加大-倒角高度)")
                o.append(f"           = ({B:.2f}-2×{chamfer_length_val:.2f}) + 2×{hyp_val_inc:.3f} + 2×({h_inc:.3f}-{chamfer_height_val:.3f})")
                o.append(f"           = {bottom_width_inc:.2f} + {2*hyp_val_inc:.3f} + {2*wall_above_inc:.3f}")
                o.append(f"           = {P_inc:.3f} m")
            else:
                o.append(f"      P加大 = (B-2×倒角底边) + 2×h加大/sin(倒角角度)")
                o.append(f"           = ({B:.2f}-2×{chamfer_length_val:.2f}) + 2×{h_inc:.3f}/sin({chamfer_angle_val:.1f}°)")
                o.append(f"           = {P_inc:.3f} m")
            o.append("")
        else:
            o.append("  3. 过水面积计算 (矩形断面):")
            o.append(f"      A加大 = B × h加大")
            o.append(f"           = {B:.2f} × {h_inc:.3f}")
            o.append(f"           = {A_inc:.3f} m²")
            o.append("")

            o.append("  4. 湿周计算 (矩形断面):")
            o.append(f"      P加大 = B + 2×h加大")
            o.append(f"           = {B:.2f} + 2×{h_inc:.3f}")
            o.append(f"           = {B:.2f} + {2*h_inc:.3f}")
            o.append(f"           = {P_inc:.3f} m")
            o.append("")

        o.append("  5. 水力半径计算:")
        o.append(f"      R加大 = A加大 / P加大")
        o.append(f"           = {A_inc:.3f} / {P_inc:.3f}")
        o.append(f"           = {R_hyd_inc:.3f} m")
        o.append("")

        o.append("  6. 加大流速计算 (曼宁公式):")
        o.append(f"      V加大 = (1/n) × R加大^(2/3) × i^(1/2)")
        o.append(f"           = (1/{n}) × {R_hyd_inc:.3f}^(2/3) × {i:.6f}^(1/2)")
        if R_hyd_inc > 0:
            o.append(f"           = {1/n:.2f} × {R_hyd_inc**(2/3):.4f} × {math.sqrt(i):.6f}")
        o.append(f"           = {V_inc:.3f} m/s")
        o.append("")

        o.append("  7. 流量校核:")
        o.append(f"      Q计算 = A加大 × V加大")
        o.append(f"           = {A_inc:.3f} × {V_inc:.3f}")
        o.append(f"           = {A_inc * V_inc:.3f} m³/s")
        if Q_inc > 0:
            o.append(f"      误差 = {abs(A_inc * V_inc - Q_inc) / Q_inc * 100:.2f}%")
        o.append("")

        o.append("  8. 超高计算:")
        o.append(f"      Fb = H - h加大 = {H_total:.2f} - {h_inc:.3f} = {Fb:.3f} m")
        o.append("")

        if result.get('warning_message'):
            o.append("【流速提示】")
            o.append(f"  {result['warning_message']}")
            o.append("")

        o.append("【五、验证】")
        o.append("")

        v_recommended_min = 1.0
        v_recommended_max = 2.5
        vel_ok = v_recommended_min <= V_d <= v_recommended_max
        o.append(f"  1. 流速验证（规范 9.4.1-1）")
        o.append(f"     规范要求: 1.0 ≤ V ≤ 2.5 m/s")
        o.append(f"     计算结果: V = {V_d:.3f} m/s")
        if vel_ok:
            o.append(f"     结果: 通过 ✓")
        else:
            if V_d < v_recommended_min:
                o.append(f"     结果: 超出推荐范围 ⚠")
                o.append(f"     提示: 流速过小，可能造成淤积，建议调整断面尺寸")
            else:
                o.append(f"     结果: 超出推荐范围 ⚠")
                o.append(f"     提示: 流速过大，可能造成冲刷，建议调整断面尺寸")
        o.append("")

        o.append(f"  2. 超高验证（规范 9.4.1-2）")
        Fb_design_min2 = h_d / 12 + 0.05
        Fb_design = H_total - h_d
        Fb_inc_min = 0.10
        fb_design_ok = Fb_design >= Fb_design_min2
        fb_inc_ok = Fb >= Fb_inc_min
        o.append(f"     断面类型: 矩形")
        o.append(f"     规范要求:")
        o.append(f"       - 设计流量: 超高不应小于 h/12 + 0.05 = {h_d:.3f}/12 + 0.05 = {Fb_design_min2:.3f} m")
        o.append(f"       - 加大流量: 超高不应小于 0.10 m")
        o.append(f"")
        o.append(f"     计算结果:")
        o.append(f"       - 设计流量超高: Fb_设计 = H - h_设计 = {H_total:.2f} - {h_d:.3f} = {Fb_design:.3f} m")
        o.append(f"       - 加大流量超高: Fb_加大 = H - h_加大 = {H_total:.2f} - {h_inc:.3f} = {Fb:.3f} m")
        o.append(f"")
        o.append(f"     验证结果:")
        o.append(f"       - 设计流量: {Fb_design:.3f} {'≥' if fb_design_ok else '<'} {Fb_design_min2:.3f} → {'通过 ✓' if fb_design_ok else '未通过 ✗'}")
        o.append(f"       - 加大流量: {Fb:.3f} {'≥' if fb_inc_ok else '<'} {Fb_inc_min:.3f} → {'通过 ✓' if fb_inc_ok else '未通过 ✗'}")
        o.append("")

        all_pass = fb_inc_ok and fb_design_ok
        o.append("=" * 70)
        o.append(f"  综合验证结果: {'全部通过 ✓' if all_pass else '未通过 ✗'}")
        o.append("=" * 70)
        txt = "\n".join(o)
        self._export_plain_text = txt
        load_formula_page(self.result_text, plain_text_to_formula_html(txt))

    # ================================================================
    # 断面图
    # ================================================================
    def _update_section_plot(self, result):
        self.section_fig.clear()
        if not result.get('success'):
            self.section_canvas.draw(); return

        stype = result.get('section_type', 'U形')
        Q = self.input_params['Q']
        Q_inc = result['Q_increased']

        if stype == 'U形':
            R = result['R']; f = result['f']
            h_d = result['h_design']; V_d = result['V_design']
            h_inc = result['h_increased']; V_inc = result['V_increased']
            H_total = result['H_total']
            axes = self.section_fig.subplots(1, 2)
            self._draw_u_section(axes[0], R, f, H_total, h_d, V_d, Q, "设计流量")
            self._draw_u_section(axes[1], R, f, H_total, h_inc, V_inc, Q_inc, "加大流量")
        else:
            B = result['B']; H_total = result['H_total']
            h_d = result['h_design']; V_d = result['V_design']
            h_inc = result['h_increased']; V_inc = result['V_increased']
            axes = self.section_fig.subplots(1, 2)
            self._draw_rect_section(axes[0], B, H_total, h_d, V_d, Q, "设计流量", result)
            self._draw_rect_section(axes[1], B, H_total, h_inc, V_inc, Q_inc, "加大流量", result)

        self.section_fig.tight_layout()
        self.section_canvas.draw()

    def _draw_u_section(self, ax, R, f, H_total, h_w, V, Q, title):
        """绘制U形断面"""
        # 半圆底部
        theta = np.linspace(np.pi, 2*np.pi, 50)
        cx = R * np.cos(theta)
        cy = R * np.sin(theta) + R  # 底部中心在(0, R)
        # 直段
        left_wall = [(-R, R), (-R, R + f)]
        right_wall = [(R, R), (R, R + f)]
        top = [(-R, R + f), (R, R + f)]

        # 绘制槽壁
        ax.plot(cx, cy, 'k-', lw=2)
        ax.plot([-R, -R], [R, R + f], 'k-', lw=2)
        ax.plot([R, R], [R, R + f], 'k-', lw=2)
        ax.plot([-R, R], [R + f, R + f], 'k--', lw=1)

        # 绘制水面
        if h_w > 0:
            if h_w <= R:
                # 水面在半圆内
                cos_val = max(-1, min(1, 1 - h_w / R))
                angle = math.acos(cos_val)
                water_theta = np.linspace(np.pi + (np.pi/2 - angle), 2*np.pi - (np.pi/2 - angle), 50)
                wx = R * np.cos(water_theta)
                wy = R * np.sin(water_theta) + R
                water_w = R * math.sin(angle)
                wx = np.concatenate([[-water_w], wx, [water_w]])
                wy = np.concatenate([[h_w], wy, [h_w]])
                ax.fill(wx, wy, color='lightblue', alpha=0.7)
                ax.plot([-water_w, water_w], [h_w, h_w], 'b-', lw=1.5)
            else:
                # 水面在直段
                # 半圆部分全满
                water_theta = np.linspace(np.pi, 2*np.pi, 50)
                wx_bottom = R * np.cos(water_theta)
                wy_bottom = R * np.sin(water_theta) + R
                # 加上直段
                wx = np.concatenate([[-R], wx_bottom, [R, R, -R]])
                wy = np.concatenate([[h_w], wy_bottom, [R, h_w, h_w]])
                ax.fill(wx, wy, color='lightblue', alpha=0.7)
                ax.plot([-R, R], [h_w, h_w], 'b-', lw=1.5)

        # 标注槽宽
        ax.annotate('', xy=(R, -0.15*R), xytext=(-R, -0.15*R),
                     arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, -0.3*R, f'B={2*R:.2f}m', ha='center', fontsize=9, color='gray')

        # 标注半径 R
        ax.annotate('', xy=(0, R), xytext=(R*0.7, R*0.3),
                     arrowprops=dict(arrowstyle='->', color='green', lw=1.2))
        ax.text(R*0.75, R*0.15, f'R={R:.2f}m', ha='left', fontsize=8, color='green')

        # 标注总高
        ax.annotate('', xy=(R+0.15*R, R+f), xytext=(R+0.15*R, 0),
                     arrowprops=dict(arrowstyle='<->', color='purple', lw=1.5))
        ax.text(R+0.25*R, (R+f)/2, f'H={H_total:.2f}m', ha='left', fontsize=9, color='purple', rotation=90, va='center')

        # 标注水深
        if h_w > 0:
            ax.annotate('', xy=(-R-0.15*R, h_w), xytext=(-R-0.15*R, 0),
                         arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-R-0.25*R, h_w/2, f'h={h_w:.2f}m', ha='right', fontsize=9, color='blue', rotation=90, va='center')

        ax.set_xlim(-R*2.2, R*2.2)
        ax.set_ylim(-R*0.6, (R+f)*1.2)
        ax.set_aspect('equal')
        ax.set_title(f'{title}\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='brown', lw=3)

    def _draw_rect_section(self, ax, B, H_total, h_w, V, Q, title, result=None):
        """绘制矩形断面（支持倒角）"""
        H = H_total
        has_chamfer = result.get('has_chamfer', False) if result else False
        chamfer_angle = result.get('chamfer_angle', 0) if result else 0
        chamfer_length = result.get('chamfer_length', 0) if result else 0

        if has_chamfer and chamfer_angle > 0 and chamfer_length > 0:
            chamfer_height = chamfer_length * math.tan(math.radians(chamfer_angle))

            # 绘制带倒角的槽身轮廓
            ax.plot([-B/2, -B/2], [chamfer_height, H], 'k-', lw=2)
            ax.plot([B/2, B/2], [chamfer_height, H], 'k-', lw=2)
            ax.plot([-B/2 + chamfer_length, B/2 - chamfer_length], [0, 0], 'k-', lw=2)
            ax.plot([-B/2, -B/2 + chamfer_length], [chamfer_height, 0], 'k-', lw=2)
            ax.plot([B/2 - chamfer_length, B/2], [0, chamfer_height], 'k-', lw=2)
            ax.plot([-B/2, B/2], [H, H], 'k--', lw=1)

            # 绘制水面
            if h_w > 0:
                if h_w <= chamfer_height:
                    water_x_left = -B/2 + chamfer_length * (h_w / chamfer_height)
                    water_x_right = B/2 - chamfer_length * (h_w / chamfer_height)
                    water_x = [water_x_left, -B/2 + chamfer_length, B/2 - chamfer_length, water_x_right]
                    water_y = [h_w, 0, 0, h_w]
                    ax.fill(water_x, water_y, color='lightblue', alpha=0.7)
                    ax.plot([water_x_left, water_x_right], [h_w, h_w], 'b-', lw=1.5)
                else:
                    water_x = [-B/2, -B/2 + chamfer_length, B/2 - chamfer_length, B/2, B/2, -B/2]
                    water_y = [chamfer_height, 0, 0, chamfer_height, h_w, h_w]
                    ax.fill(water_x, water_y, color='lightblue', alpha=0.7)
                    ax.plot([-B/2, B/2], [h_w, h_w], 'b-', lw=1.5)

            # 标注倒角角度
            ax.text(-B/2 + chamfer_length/2, chamfer_height/2,
                    f'{chamfer_angle:.0f}°', ha='center', va='center',
                    fontsize=7, color='orange', fontweight='bold')
        else:
            # 无倒角，普通矩形
            ax.plot([-B/2, -B/2], [0, H], 'k-', lw=2)
            ax.plot([B/2, B/2], [0, H], 'k-', lw=2)
            ax.plot([-B/2, B/2], [0, 0], 'k-', lw=2)
            ax.plot([-B/2, B/2], [H, H], 'k--', lw=1)

            if h_w > 0:
                wx = [-B/2, -B/2, B/2, B/2]
                wy = [0, h_w, h_w, 0]
                ax.fill(wx, wy, color='lightblue', alpha=0.7)
                ax.plot([-B/2, B/2], [h_w, h_w], 'b-', lw=1.5)

        # 标注槽宽
        ax.annotate('', xy=(B/2, -0.1*H), xytext=(-B/2, -0.1*H),
                     arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, -0.2*H, f'B={B:.2f}m', ha='center', fontsize=9, color='gray')

        # 标注总高
        ax.annotate('', xy=(B/2+0.1*B, H), xytext=(B/2+0.1*B, 0),
                     arrowprops=dict(arrowstyle='<->', color='purple', lw=1.5))
        ax.text(B/2+0.15*B, H/2, f'H={H:.2f}m', ha='left', fontsize=9, color='purple', rotation=90, va='center')

        # 标注水深
        if h_w > 0:
            ax.annotate('', xy=(-B/2-0.1*B, h_w), xytext=(-B/2-0.1*B, 0),
                         arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-B/2-0.15*B, h_w/2, f'h={h_w:.2f}m', ha='right', fontsize=9, color='blue', rotation=90, va='center')

        ax.set_xlim(-B*0.9, B*0.9)
        ax.set_ylim(-H*0.35, H*1.2)
        ax.set_aspect('equal')

        title_suffix = "(带倒角)" if has_chamfer and chamfer_angle > 0 else ""
        ax.set_title(f'{title}{title_suffix}\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='brown', lw=3)

    # ================================================================
    # 清空
    # ================================================================
    def _clear(self):
        self._show_initial_help()
        self.section_fig.clear()
        self.section_canvas.draw()
        self.inc_hint.setText("(留空则自动计算)")
        self.current_result = None

    # ================================================================
    # 导出
    # ================================================================
    def _export_dxf(self):
        if not self.current_result or not self.current_result.get('success'):
            InfoBar.warning("提示", "请先进行计算后再导出。", parent=self._info_parent(), duration=3000, position=InfoBarPosition.TOP)
            return
        res = self.current_result; p = self.input_params
        stype = res.get('section_type', p.get('section_type', 'U形'))
        if stype == 'U形':
            R = res.get('R', 0.0); H = res.get('H_total', 0.0)
            default_name = f'渡槽断面_U形_R{R:.2f}xH{H:.2f}.dxf'
        else:
            B = res.get('B', 0.0); H = res.get('H_total', 0.0)
            default_name = f'渡槽断面_矩形_B{B:.2f}xH{H:.2f}.dxf'
        scales = ['1:20', '1:50', '1:100', '1:200', '1:500']
        from 渠系断面设计.styles import fluent_select
        scale_str, ok = fluent_select(self, '选择比例尺', '输出比例尺 (图纸单位: mm):', scales, 2)
        if not ok: return
        scale_denom = int(scale_str.split(':')[1])
        filepath, _ = QFileDialog.getSaveFileName(
            self, "保存DXF文件", default_name, "DXF文件 (*.dxf);;所有文件 (*.*)"
        )
        if not filepath: return
        try:
            export_aqueduct_dxf(filepath, res, p, scale_denom)
            InfoBar.success("导出成功", f"DXF已保存到: {filepath}", parent=self._info_parent(), duration=4000, position=InfoBarPosition.TOP)
            ask_open_file(filepath, self._info_parent())
        except ImportError as e:
            InfoBar.error("缺少依赖", str(e), parent=self._info_parent(), duration=6000, position=InfoBarPosition.TOP)
        except PermissionError:
            InfoBar.error("文件被占用", "无法写入文件，请先关闭已打开的同名DXF文件。", parent=self._info_parent(), duration=8000, position=InfoBarPosition.TOP)
        except Exception as e:
            InfoBar.error("导出失败", f"DXF导出失败: {str(e)}", parent=self._info_parent(), duration=5000, position=InfoBarPosition.TOP)

    def _export_report(self):
        if not self.current_result or not self.current_result.get('success'):
            InfoBar.warning("提示", "请先进行计算后再导出。", parent=self._info_parent(), duration=3000, position=InfoBarPosition.TOP)
            return
        filepath, _ = QFileDialog.getSaveFileName(self, "保存报告", "", "文本文件 (*.txt);;所有文件 (*.*)")
        if not filepath: return
        try:
            content = self._export_plain_text if self._export_plain_text else ''
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            InfoBar.success("导出成功", f"报告已保存到: {filepath}", parent=self._info_parent(), duration=4000, position=InfoBarPosition.TOP)
            ask_open_file(filepath, self._info_parent())
        except PermissionError:
            InfoBar.error("文件被占用", "无法写入文件，请先关闭已打开的同名文件（如记事本等），然后重新操作。", parent=self._info_parent(), duration=8000, position=InfoBarPosition.TOP)
        except Exception as e:
            InfoBar.error("导出失败", f"保存失败: {str(e)}", parent=self._info_parent(), duration=5000, position=InfoBarPosition.TOP)

    def _export_word(self):
        if not WORD_EXPORT_AVAILABLE:
            InfoBar.warning("缺少依赖",
                "Word导出需要安装 python-docx、latex2mathml、lxml。请执行: pip install python-docx latex2mathml lxml",
                parent=self._info_parent(), duration=6000, position=InfoBarPosition.TOP)
            return
        if not self.current_result or not self.current_result.get('success'):
            InfoBar.warning("提示", "请先进行计算后再导出。", parent=self._info_parent(), duration=3000, position=InfoBarPosition.TOP)
            return
        filepath, _ = QFileDialog.getSaveFileName(self, "保存Word报告", "", "Word文档 (*.docx);;所有文件 (*.*)")
        if not filepath: return
        try:
            self._build_word_report(filepath)
            InfoBar.success("导出成功", f"Word报告已保存到: {filepath}", parent=self._info_parent(), duration=4000, position=InfoBarPosition.TOP)
            ask_open_file(filepath, self._info_parent())
        except PermissionError:
            InfoBar.error("文件被占用", "无法写入文件，请先关闭已打开的同名Word文档，然后重新操作。", parent=self._info_parent(), duration=8000, position=InfoBarPosition.TOP)
        except Exception as e:
            InfoBar.error("导出失败", f"Word导出失败: {str(e)}", parent=self._info_parent(), duration=5000, position=InfoBarPosition.TOP)

    def _build_word_report(self, filepath):
        """构建Word报告文档（方案3高端咨询报告风格）"""
        res = self.current_result
        stype = res.get('section_type', 'U形')
        method = res.get("design_method", "")

        doc = create_styled_doc(
            title='渡槽水力计算书',
            subtitle=f'{stype}断面  ·  {method}',
            header_text=f'渡槽水力计算书（{stype}断面）'
        )
        doc.add_page_break()

        # 一、基础公式
        doc_add_h1(doc, '一、基础公式')
        doc_add_formula(doc, r'Q = \frac{1}{n} \cdot A \cdot R^{2/3} \cdot i^{1/2}', '曼宁公式：')
        if stype == 'U形':
            doc_add_formula(doc, r'B = 2R', '槽宽：')
            doc_add_formula(doc, r'H = f + R', '槽高：')
        else:
            doc_add_formula(doc, r'A = B \cdot h', '过水面积：')
            doc_add_formula(doc, r'P = B + 2h', '湿周：')
        doc_add_formula(doc, r'R_{hyd} = \frac{A}{P}', '水力半径：')

        # 二、计算过程
        doc_add_h1(doc, '二、计算过程')
        doc_render_calc_text(doc, self._export_plain_text or '', skip_title_keyword='渡槽水力计算结果')

        # 三、断面图
        try:
            import tempfile
            tmp = os.path.join(tempfile.gettempdir(), '_aqueduct_section.png')
            self.section_fig.savefig(tmp, dpi=150, bbox_inches='tight')
            doc_add_h1(doc, '三、断面图')
            doc_add_figure(doc, tmp, width_cm=14)
            os.remove(tmp)
        except Exception:
            pass

        doc.save(filepath)
