# -*- coding: utf-8 -*-
"""
隧洞水力计算面板 —— QWidget 版本

支持：圆形 / 圆拱直墙型 / 马蹄形标准Ⅰ型 / 马蹄形标准Ⅱ型
功能：参数输入、计算、结果显示、断面图、导出Word/TXT/图表
"""

import sys
import os
import math
import re
import html as html_mod

_pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_pkg_root, "渠系建筑物断面计算"))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QSplitter, QFrame, QTabWidget, QTextEdit, QFileDialog, QScrollArea, QInputDialog
)
from PySide6.QtCore import Qt
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

from 隧洞设计 import (
    quick_calculate_circular,
    quick_calculate_horseshoe,
    quick_calculate_horseshoe_std,
    PI, MIN_FREEBOARD_PCT_TUNNEL, MIN_FREEBOARD_HGT_TUNNEL,
)

from 渠系断面设计.styles import P, S, W, E, BG, CARD, BD, T1, T2, INPUT_LABEL_STYLE, INPUT_SECTION_STYLE, INPUT_HINT_STYLE
from 渠系断面设计.export_utils import (
    WORD_EXPORT_AVAILABLE, add_formula_to_doc, try_convert_formula_line, ask_open_file,
    create_styled_doc, doc_add_h1, doc_add_formula, doc_render_calc_text, doc_add_figure,
)
from 渠系断面设计.tunnel.dxf_export import export_tunnel_dxf
from 渠系断面设计.formula_renderer import (
    plain_text_to_formula_html, load_formula_page, make_plain_html,
    HelpPageBuilder
)
if WORD_EXPORT_AVAILABLE:
    from docx import Document as DocxDocument
    from docx.shared import Pt, Cm


def _e(s):
    return html_mod.escape(str(s))


class TunnelPanel(QWidget):
    """隧洞水力计算面板"""

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

        out_w = QWidget()
        self._build_output(out_w)
        splitter.addWidget(out_w)
        splitter.setSizes([340, 900])

    # ----------------------------------------------------------------
    def _build_input(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(6)
        grp = QGroupBox("输入参数")
        fl = QVBoxLayout(grp)
        fl.setSpacing(5)

        # 断面类型
        r = QHBoxLayout(); r.addWidget(QLabel("断面类型:"))
        self.section_combo = ComboBox()
        self.section_combo.addItems(["圆形", "圆拱直墙型", "马蹄形标准Ⅰ型", "马蹄形标准Ⅱ型"])
        self.section_combo.currentTextChanged.connect(self._on_section_type_changed)
        r.addWidget(self.section_combo, 1); fl.addLayout(r)

        # 通用参数
        self.Q_edit = self._field(fl, "设计流量 Q (m³/s):", "10.0")
        self.n_edit = self._field(fl, "糙率 n:", "0.014")
        self.slope_edit = self._field(fl, "水力坡降 1/", "2000")

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

        # 圆形参数
        self.circ_grp = QWidget()
        circ_lay = QVBoxLayout(self.circ_grp); circ_lay.setContentsMargins(0,0,0,0); circ_lay.setSpacing(5)
        circ_lay.addWidget(self._slbl("【圆形断面参数】"))
        self.D_lbl, self.D_edit = self._field2(circ_lay, "手动直径 D (m):", "")
        circ_lay.addWidget(self._hint("(留空则自动计算)"))
        fl.addWidget(self.circ_grp)

        # 圆拱直墙参数
        self.hs_grp = QWidget()
        hs_lay = QVBoxLayout(self.hs_grp); hs_lay.setContentsMargins(0,0,0,0); hs_lay.setSpacing(5)
        hs_lay.addWidget(self._slbl("【圆拱直墙型参数】"))
        self.theta_lbl, self.theta_edit = self._field2(hs_lay, "拱顶圆心角 (度):", "")
        hs_lay.addWidget(self._hint("(留空则采用180°)"))
        self.B_hs_lbl, self.B_hs_edit = self._field2(hs_lay, "手动底宽 B (m):", "")
        hs_lay.addWidget(self._hint("(手动底宽留空则自动计算)"))
        fl.addWidget(self.hs_grp)
        self.hs_grp.hide()

        # 马蹄形参数
        self.shoe_grp = QWidget()
        shoe_lay = QVBoxLayout(self.shoe_grp); shoe_lay.setContentsMargins(0,0,0,0); shoe_lay.setSpacing(5)
        shoe_lay.addWidget(self._slbl("【马蹄形断面参数】"))
        self.r_lbl, self.r_edit = self._field2(shoe_lay, "手动半径 r (m):", "")
        shoe_lay.addWidget(self._hint("(留空则自动计算)"))
        fl.addWidget(self.shoe_grp)
        self.shoe_grp.hide()

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
    def _build_output(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(0, 0, 0, 0)
        self.notebook = QTabWidget()
        lay.addWidget(self.notebook)

        t1 = QWidget(); t1l = QVBoxLayout(t1); t1l.setContentsMargins(5,5,5,5)
        grp = QGroupBox("计算结果详情"); gl = QVBoxLayout(grp)
        self.result_text = QWebEngineView()
        gl.addWidget(self.result_text)
        t1l.addWidget(grp)
        self.notebook.addTab(t1, "计算结果")

        t2 = QWidget(); t2l = QVBoxLayout(t2); t2l.setContentsMargins(5,5,5,5)
        self.section_fig = Figure(figsize=(8, 6), dpi=100)
        self.section_canvas = FigureCanvas(self.section_fig)
        self.section_toolbar = NavToolbar(self.section_canvas, t2)
        t2l.addWidget(self.section_toolbar)
        t2l.addWidget(self.section_canvas)
        self.notebook.addTab(t2, "断面图")

        self._show_initial_help()

    # ----------------------------------------------------------------
    def _on_section_type_changed(self, stype):
        self.circ_grp.hide(); self.hs_grp.hide(); self.shoe_grp.hide()
        if stype == "圆形":
            self.circ_grp.show()
        elif stype == "圆拱直墙型":
            self.hs_grp.show()
        else:
            self.shoe_grp.show()

    def _show_initial_help(self):
        h = HelpPageBuilder("隧洞水力计算", '请输入参数后点击“计算”按钮')
        h.section("支持断面类型")
        h.numbered_list([
            ("圆形断面", "最小直径 2.0m，最小净空高度 0.4m"),
            ("圆拱直墙型", "拱顶圆心角 90~180°，推荐高宽比 1.0~1.5"),
            ("马蹄形标准Ⅰ型", "t=3，底拱半径为3r，适用于地质条件较好的隧洞"),
            ("马蹄形标准Ⅱ型", "t=2，底拱半径为2r，适用于地质条件一般的隧洞"),
        ])
        h.section("曼宁公式")
        h.text("计算基于曼宁公式：")
        h.formula("Q = (1/n) × A × R^(2/3) × i^(1/2)", "流量公式")
        h.section("净空约束条件")
        h.bullet_list([
            "最小净空面积 10%",
            "最小净空高度 0.4m",
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

            if Q <= 0: self._show_error("参数错误", "请输入有效的设计流量 Q（必须大于0）。"); return
            if n <= 0: self._show_error("参数错误", "请输入有效的糙率 n（必须大于0）。"); return
            if slope_inv <= 0: self._show_error("参数错误", "请输入有效的水力坡降倒数（必须大于0）。"); return
            if v_min >= v_max: self._show_error("参数错误", "不淤流速必须小于不冲流速。"); return

            manual_increase = self._fval_opt(self.inc_edit)
            self.input_params = {
                'Q': Q, 'n': n, 'slope_inv': slope_inv,
                'v_min': v_min, 'v_max': v_max,
                'section_type': stype, 'manual_increase': manual_increase
            }

            if stype == "圆形":
                manual_D = self._fval_opt(self.D_edit)
                self.input_params['manual_D'] = manual_D
                result = quick_calculate_circular(
                    Q=Q, n=n, slope_inv=slope_inv,
                    v_min=v_min, v_max=v_max,
                    manual_D=manual_D,
                    manual_increase_percent=manual_increase
                )
            elif stype == "圆拱直墙型":
                theta_deg = self._fval(self.theta_edit, 180)
                manual_B = self._fval_opt(self.B_hs_edit)
                self.input_params['theta_deg'] = theta_deg
                self.input_params['manual_B'] = manual_B
                result = quick_calculate_horseshoe(
                    Q=Q, n=n, slope_inv=slope_inv,
                    v_min=v_min, v_max=v_max,
                    theta_deg=theta_deg,
                    manual_B=manual_B,
                    manual_increase_percent=manual_increase
                )
            else:
                sec_type_int = 1 if "Ⅰ" in stype else 2
                manual_r = self._fval_opt(self.r_edit)
                self.input_params['sec_type_int'] = sec_type_int
                self.input_params['manual_r'] = manual_r
                result = quick_calculate_horseshoe_std(
                    Q=Q, n=n, slope_inv=slope_inv,
                    v_min=v_min, v_max=v_max,
                    section_type=sec_type_int,
                    manual_r=manual_r,
                    manual_increase_percent=manual_increase
                )

            self.current_result = result

            if result.get('success') and 'increase_percent' in result:
                ap = result['increase_percent']
                src = "手动指定" if self.inc_edit.text().strip() else "自动计算"
                self.inc_hint.setText(f"({src}: {ap:.1f}%)")

            self._update_result_display(result)
            self._update_section_plot(result)

        except ValueError as e:
            error_detail = str(e)
            if "invalid literal" in error_detail or "could not convert" in error_detail:
                self._show_error("输入错误", "参数输入不完整或格式错误，请检查并填写所有必填参数：\n- 设计流量 Q\n- 糙率 n\n- 水力坡降 1/x")
            else:
                self._show_error("输入错误", f"{error_detail}")
        except Exception as e:
            self._show_error("计算错误", f"计算过程出错: {str(e)}")

    def _show_error(self, title, msg):
        out = ["=" * 70, f"  {title}", "=" * 70, "", msg, "", "-" * 70, "请修正后重新计算。", "=" * 70]
        self.result_text.setHtml(make_plain_html("\n".join(out)))

    # ================================================================
    # 结果显示
    # ================================================================
    def _update_result_display(self, result):
        if not result['success']:
            self._show_error("计算失败", result.get('error_message', '未知错误'))
            return
        stype = self.input_params.get('section_type', '圆形')
        detail = self.detail_cb.isChecked()
        if stype == "圆形":
            self._show_result(result, "圆形", detail)
        elif stype == "圆拱直墙型":
            self._show_result(result, "圆拱直墙型", detail)
        else:
            self._show_result(result, result.get('section_type', '马蹄形'), detail)

    def _show_result(self, result, type_label, detail):
        p = self.input_params
        Q, n = p['Q'], p['n']
        slope_inv = p['slope_inv']; i = 1.0 / slope_inv
        v_min, v_max = p['v_min'], p['v_max']
        inc_src = "(手动指定)" if p.get('manual_increase') else "(自动计算)"
        stype = self.input_params.get('section_type', '圆形')

        A_total = result.get('A_total', 0)
        h_d = result['h_design']; V_d = result['V_design']
        A_d = result['A_design']; P_d = result['P_design']
        R_hyd_d = result['R_hyd_design']
        fb_pct_d = result['freeboard_pct_design']; fb_hgt_d = result['freeboard_hgt_design']
        inc_pct = result['increase_percent']; Q_inc = result['Q_increased']
        h_inc = result['h_increased']; V_inc = result['V_increased']
        A_inc = result.get('A_increased', 0); P_inc = result.get('P_increased', 0)
        R_hyd_inc = result.get('R_hyd_increased', 0)
        fb_pct_inc = result['freeboard_pct_inc']; fb_hgt_inc = result['freeboard_hgt_inc']

        o = []
        o.append("=" * 70)
        o.append(f"              隧洞水力计算结果 - {type_label}")
        o.append("=" * 70)
        o.append("")

        if not detail:
            # ============ 简要输出（对齐原版格式） ============
            o.append("【输入参数】")
            o.append(f"  断面类型 = {stype}")
            o.append(f"  设计流量 Q = {Q:.3f} m³/s")
            o.append(f"  糙率 n = {n}")
            o.append(f"  水力坡降 = 1/{int(slope_inv)}")
            o.append(f"  不淤流速 = {v_min} m/s")
            o.append(f"  不冲流速 = {v_max} m/s")
            o.append("")

            o.append("【断面尺寸】")
            if stype == "圆形":
                o.append(f"  直径 D = {result.get('D', 0):.2f} m")
            elif stype == "圆拱直墙型":
                o.append(f"  宽度 B = {result.get('B', 0):.2f} m")
                o.append(f"  高度 H = {result.get('H_total', 0):.2f} m")
            else:
                o.append(f"  半径 r = {result.get('r', 0):.2f} m")
            o.append(f"  总面积 A = {A_total:.3f} m²")
            o.append("")

            o.append("【设计流量工况】")
            o.append(f"  设计水深 h = {h_d:.3f} m")
            o.append(f"  设计流速 V = {V_d:.3f} m/s")
            o.append(f"  净空高度 Fb = {fb_hgt_d:.3f} m")
            o.append(f"  净空比例 = {fb_pct_d:.1f}%")
            o.append("")

            o.append("【加大流量工况】")
            o.append(f"  流量加大比例 = {inc_pct:.1f}% {inc_src}")
            o.append(f"  加大流量 Q加大 = {Q_inc:.3f} m³/s")
            o.append(f"  加大水深 h加大 = {h_inc:.3f} m")
            o.append(f"  加大流速 V加大 = {V_inc:.3f} m/s")
            o.append(f"  净空高度 Fb加大 = {fb_hgt_inc:.3f} m")
            o.append(f"  净空比例 = {fb_pct_inc:.1f}%")
            o.append("")

            o.append("【验证结果】")
            vel_ok = v_min <= V_d <= v_max
            fb_ok = fb_pct_inc >= 15 and fb_hgt_inc >= 0.4
            o.append(f"  流速验证: {'✓ 通过' if vel_ok else '✗ 未通过'}")
            o.append(f"  净空验证: {'✓ 通过' if fb_ok else '需注意'}")
            o.append("")
        else:
            # ============ 详细输出（对齐原版格式） ============
            o.append("【一、输入参数】")
            o.append(f"  断面类型 = {stype}")
            o.append(f"  设计流量 Q = {Q:.3f} m³/s")
            o.append(f"  糙率 n = {n}")
            o.append(f"  水力坡降 = 1/{int(slope_inv)}")
            o.append(f"  不淤流速 = {v_min} m/s")
            o.append(f"  不冲流速 = {v_max} m/s")
            o.append("")

            # 断面尺寸
            if stype == "圆形":
                D = result['D']
                o.append("【二、断面尺寸】")
                o.append("")
                o.append(f"  1. 设计直径:")
                o.append(f"     D = {D:.2f} m")
                o.append("")
                o.append(f"  2. 断面总面积计算:")
                o.append(f"     A总 = π × D² / 4")
                o.append(f"        = {PI:.4f} × {D:.2f}² / 4")
                o.append(f"        = {A_total:.3f} m²")
                o.append("")
            elif stype == "圆拱直墙型":
                B = result['B']; H_total = result['H_total']
                theta_deg = result['theta_deg']
                o.append("【二、断面尺寸】")
                o.append("")
                o.append(f"  1. 设计宽度: B = {B:.2f} m")
                o.append(f"  2. 设计高度: H = {H_total:.2f} m")
                o.append(f"  3. 拱顶圆心角: θ = {theta_deg:.1f}°")
                o.append(f"  4. 高宽比: H/B = {H_total:.2f}/{B:.2f} = {result.get('HB_ratio', 0):.3f}")
                o.append(f"  5. 断面总面积: A总 = {A_total:.3f} m²")
                o.append("")
            else:
                r_val = result['r']; D_equiv = result['D_equiv']
                o.append("【二、断面尺寸】")
                o.append("")
                st_name = '标准Ⅰ型' if 'Ⅰ' in type_label else '标准Ⅱ型'
                o.append(f"  断面类型: {st_name}")
                o.append(f"  1. 设计半径: r = {r_val:.2f} m")
                o.append(f"  2. 等效直径: 2r = {D_equiv:.2f} m")
                o.append(f"  3. 断面总面积: A总 = {A_total:.3f} m²")
                o.append("")

            # 设计流量工况
            o.append("【三、设计流量工况计算】")
            o.append(f"  Q = {Q:.3f} m³/s")
            o.append("")
            o.append("  1. 设计水深计算:")
            o.append(f"     根据设计流量 Q = {Q:.3f} m³/s，利用曼宁公式反算水深:")
            o.append(f"     h = {h_d:.3f} m")
            o.append("")

            # 过水面积和湿周公式推导
            if stype == "圆形":
                D = result['D']; R_radius = D / 2
                if h_d > 0 and D > 0 and h_d < D:
                    theta_d = 2 * math.acos((R_radius - h_d) / R_radius)
                    o.append("  2. 圆心角计算:")
                    o.append(f"     θ = 2 × arccos((R - h) / R)")
                    o.append(f"       = 2 × arccos(({R_radius:.3f} - {h_d:.3f}) / {R_radius:.3f})")
                    o.append(f"       = 2 × arccos({(R_radius - h_d)/R_radius:.4f})")
                    o.append(f"       = {math.degrees(theta_d):.2f}° ({theta_d:.4f} rad)")
                    o.append("")
                    o.append("  3. 过水面积计算:")
                    o.append(f"     A = (D²/8) × (θ - sinθ)")
                    o.append(f"       = ({D:.3f}²/8) × ({theta_d:.4f} - sin{theta_d:.4f})")
                    o.append(f"       = {D**2/8:.4f} × {theta_d - math.sin(theta_d):.4f}")
                    o.append(f"       = {A_d:.3f} m²")
                    o.append("")
                    o.append("  4. 湿周计算:")
                    o.append(f"     χ = (D/2) × θ")
                    o.append(f"       = ({D:.3f}/2) × {theta_d:.4f}")
                    o.append(f"       = {R_radius:.3f} × {theta_d:.4f}")
                    o.append(f"       = {P_d:.3f} m")
                    o.append("")
                else:
                    o.append(f"  2. 过水面积: A = {A_d:.3f} m²")
                    o.append("")
                    o.append(f"  3. 湿周: χ = {P_d:.3f} m")
                    o.append("")
            elif stype == "圆拱直墙型":
                B_hs = result['B']; H_hs = result['H_total']
                theta_deg_hs = result['theta_deg']
                theta_rad_hs = math.radians(theta_deg_hs)
                if abs(math.sin(theta_rad_hs / 2)) > 1e-9 and B_hs > 0:
                    R_arch = (B_hs / 2) / math.sin(theta_rad_hs / 2)
                    H_arch = R_arch * (1 - math.cos(theta_rad_hs / 2))
                    H_straight = max(0, H_hs - H_arch)
                    o.append("  2. 过水面积计算 (圆拱直墙型):")
                    if h_d <= H_straight:
                        o.append(f"     水深 h = {h_d:.3f} m ≤ 直墙高度 {H_straight:.3f} m")
                        o.append(f"     A = B × h = {B_hs:.2f} × {h_d:.3f} = {A_d:.3f} m²")
                    else:
                        o.append(f"     水深 h = {h_d:.3f} m > 直墙高度 {H_straight:.3f} m")
                        o.append(f"     A = 直墙部分 + 拱部过水面积")
                        o.append(f"       = {A_d:.3f} m²")
                    o.append("")
                    o.append("  3. 湿周计算 (圆拱直墙型):")
                    if h_d <= H_straight:
                        o.append(f"     χ = B + 2×h = {B_hs:.2f} + 2×{h_d:.3f}")
                        o.append(f"       = {P_d:.3f} m")
                    else:
                        o.append(f"     χ = 底宽 + 直墙段 + 拱部湿周")
                        o.append(f"       = {P_d:.3f} m")
                    o.append("")
                else:
                    o.append(f"  2. 过水面积: A = {A_d:.3f} m²")
                    o.append("")
                    o.append(f"  3. 湿周: χ = {P_d:.3f} m")
                    o.append("")
            else:
                r_val = result['r']
                horseshoe_type_id = 1 if 'Ⅰ' in type_label else 2
                t_val = 3.0 if horseshoe_type_id == 1 else 2.0
                R_arch_hs = t_val * r_val
                e_val = R_arch_hs * (1 - math.cos(0.294515 if horseshoe_type_id == 1 else 0.424031))
                st_name = '标准Ⅰ型' if horseshoe_type_id == 1 else '标准Ⅱ型'
                o.append(f"  2. 过水面积计算 ({st_name}):")
                if h_d <= e_val:
                    o.append(f"     水深 h = {h_d:.3f} m ≤ 底拱段高度 e = {e_val:.3f} m")
                    o.append(f"     处于底拱段，按底拱段公式计算:")
                elif h_d <= r_val:
                    o.append(f"     底拱段高度 e = {e_val:.3f} m < 水深 h = {h_d:.3f} m ≤ r = {r_val:.2f} m")
                    o.append(f"     处于侧拱段，按侧拱段公式计算:")
                else:
                    o.append(f"     水深 h = {h_d:.3f} m > r = {r_val:.2f} m")
                    o.append(f"     处于顶拱段，按顶拱段公式计算:")
                o.append(f"     A = {A_d:.3f} m²")
                o.append("")
                o.append(f"  3. 湿周计算 ({st_name}):")
                o.append(f"     χ = {P_d:.3f} m")
                o.append("")

            o.append(f"  4. 水力半径计算:")
            o.append(f"      R = A / χ")
            o.append(f"        = {A_d:.3f} / {P_d:.3f}")
            o.append(f"        = {R_hyd_d:.3f} m")
            o.append("")
            o.append(f"  5. 设计流速计算 (曼宁公式):")
            o.append(f"      V = (1/n) × R^(2/3) × i^(1/2)")
            o.append(f"        = (1/{n}) × {R_hyd_d:.3f}^(2/3) × {i:.6f}^(1/2)")
            if R_hyd_d > 0:
                o.append(f"        = {1/n:.2f} × {R_hyd_d**(2/3):.4f} × {math.sqrt(i):.6f}")
            o.append(f"        = {V_d:.3f} m/s")
            o.append("")
            o.append(f"  6. 流量校核:")
            Q_chk = V_d * A_d
            o.append(f"      Q计算 = V × A")
            o.append(f"           = {V_d:.3f} × {A_d:.3f}")
            o.append(f"           = {Q_chk:.3f} m³/s")
            if Q_chk > 0:
                o.append(f"      误差 = {abs(Q_chk - Q)/Q*100:.2f}%")
            o.append("")

            o.append("  7. 净空面积计算:")
            o.append(f"     PA = (A总 - A) / A总 × 100%")
            o.append(f"        = ({A_total:.3f} - {A_d:.3f}) / {A_total:.3f} × 100%")
            o.append(f"        = {fb_pct_d:.1f}%")
            o.append("")
            o.append("  8. 净空高度计算:")
            if stype == "圆形":
                D = result['D']
                o.append(f"     Fb = D - h = {D:.3f} - {h_d:.3f} = {fb_hgt_d:.3f} m")
            elif stype in ("马蹄形标准Ⅰ型", "马蹄形标准Ⅱ型"):
                r_val = result['r']
                o.append(f"     Fb = 2r - h = {2*r_val:.3f} - {h_d:.3f} = {fb_hgt_d:.3f} m")
            else:
                H_total_val = result.get('H_total', 0)
                o.append(f"     Fb = H - h = {H_total_val:.3f} - {h_d:.3f} = {fb_hgt_d:.3f} m")
            o.append("")

            # 加大流量工况
            o.append("【四、加大流量工况计算】")
            o.append("")
            o.append(f"  9. 加大流量计算:")
            o.append(f"      流量加大比例 = {inc_pct:.1f}% {inc_src}")
            o.append(f"      Q加大 = Q × (1 + {inc_pct/100:.2f})")
            o.append(f"           = {Q:.3f} × {1+inc_pct/100:.2f}")
            o.append(f"           = {Q_inc:.3f} m³/s")
            o.append("")

            o.append("  10. 加大水深计算:")
            o.append(f"      根据加大流量 Q加大 = {Q_inc:.3f} m³/s，利用曼宁公式反算水深:")
            o.append(f"      h加大 = {h_inc:.3f} m")
            o.append("")

            # 加大工况过水面积和湿周
            if stype == "圆形":
                D = result['D']; R_radius = D / 2
                if h_inc > 0 and D > 0 and h_inc < D:
                    theta_inc = 2 * math.acos((R_radius - h_inc) / R_radius)
                    o.append("  11. 圆心角计算:")
                    o.append(f"      θ加大 = 2 × arccos((R - h加大) / R)")
                    o.append(f"           = 2 × arccos(({R_radius:.3f} - {h_inc:.3f}) / {R_radius:.3f})")
                    o.append(f"           = 2 × arccos({(R_radius - h_inc)/R_radius:.4f})")
                    o.append(f"           = {math.degrees(theta_inc):.2f}° ({theta_inc:.4f} rad)")
                    o.append("")
                    o.append("  12. 过水面积计算:")
                    o.append(f"      A加大 = (D²/8) × (θ加大 - sinθ加大)")
                    o.append(f"           = ({D:.3f}²/8) × ({theta_inc:.4f} - sin{theta_inc:.4f})")
                    o.append(f"           = {D**2/8:.4f} × {theta_inc - math.sin(theta_inc):.4f}")
                    o.append(f"           = {A_inc:.3f} m²")
                    o.append("")
                    o.append("  13. 湿周计算:")
                    o.append(f"      χ加大 = (D/2) × θ加大")
                    o.append(f"           = ({D:.3f}/2) × {theta_inc:.4f}")
                    o.append(f"           = {R_radius:.3f} × {theta_inc:.4f}")
                    o.append(f"           = {P_inc:.3f} m")
                    o.append("")
                else:
                    o.append(f"  11. 过水面积: A加大 = {A_inc:.3f} m²")
                    o.append("")
                    o.append(f"  12. 湿周: χ加大 = {P_inc:.3f} m")
                    o.append("")
            elif stype == "圆拱直墙型":
                B_hs = result['B']; H_hs = result['H_total']
                theta_deg_hs = result['theta_deg']
                theta_rad_hs = math.radians(theta_deg_hs)
                if abs(math.sin(theta_rad_hs / 2)) > 1e-9 and B_hs > 0:
                    R_arch = (B_hs / 2) / math.sin(theta_rad_hs / 2)
                    H_arch = R_arch * (1 - math.cos(theta_rad_hs / 2))
                    H_straight = max(0, H_hs - H_arch)
                    o.append("  11. 过水面积计算 (圆拱直墙型):")
                    if h_inc <= H_straight:
                        o.append(f"      水深 h加大 = {h_inc:.3f} m ≤ 直墙高度 {H_straight:.3f} m")
                        o.append(f"      A加大 = B × h加大 = {B_hs:.2f} × {h_inc:.3f} = {A_inc:.3f} m²")
                    else:
                        o.append(f"      水深 h加大 = {h_inc:.3f} m > 直墙高度 {H_straight:.3f} m")
                        o.append(f"      A加大 = 直墙部分 + 拱部过水面积")
                        o.append(f"           = {A_inc:.3f} m²")
                    o.append("")
                    o.append("  12. 湿周计算 (圆拱直墙型):")
                    if h_inc <= H_straight:
                        o.append(f"      χ加大 = B + 2×h加大 = {B_hs:.2f} + 2×{h_inc:.3f}")
                        o.append(f"           = {P_inc:.3f} m")
                    else:
                        o.append(f"      χ加大 = 底宽 + 直墙段 + 拱部湿周")
                        o.append(f"           = {P_inc:.3f} m")
                    o.append("")
                else:
                    o.append(f"  11. 过水面积: A加大 = {A_inc:.3f} m²")
                    o.append("")
                    o.append(f"  12. 湿周: χ加大 = {P_inc:.3f} m")
                    o.append("")
            else:
                r_val = result['r']
                horseshoe_type_id = 1 if 'Ⅰ' in type_label else 2
                t_val = 3.0 if horseshoe_type_id == 1 else 2.0
                R_arch_hs = t_val * r_val
                e_val = R_arch_hs * (1 - math.cos(0.294515 if horseshoe_type_id == 1 else 0.424031))
                st_name = '标准Ⅰ型' if horseshoe_type_id == 1 else '标准Ⅱ型'
                o.append(f"  11. 过水面积计算 ({st_name}):")
                if h_inc <= e_val:
                    o.append(f"      水深 h加大 = {h_inc:.3f} m ≤ 底拱段高度 e = {e_val:.3f} m")
                    o.append(f"      处于底拱段，按底拱段公式计算:")
                elif h_inc <= r_val:
                    o.append(f"      底拱段高度 e = {e_val:.3f} m < 水深 h加大 = {h_inc:.3f} m ≤ r = {r_val:.2f} m")
                    o.append(f"      处于侧拱段，按侧拱段公式计算:")
                else:
                    o.append(f"      水深 h加大 = {h_inc:.3f} m > r = {r_val:.2f} m")
                    o.append(f"      处于顶拱段，按顶拱段公式计算:")
                o.append(f"      A加大 = {A_inc:.3f} m²")
                o.append("")
                o.append(f"  12. 湿周计算 ({st_name}):")
                o.append(f"      χ加大 = {P_inc:.3f} m")
                o.append("")

            o.append("  13. 水力半径计算:")
            o.append(f"      R加大 = A加大 / P加大")
            o.append(f"           = {A_inc:.3f} / {P_inc:.3f}")
            o.append(f"           = {R_hyd_inc:.3f} m")
            o.append("")

            o.append("  14. 加大流速计算 (曼宁公式):")
            o.append(f"      V加大 = (1/n) × R加大^(2/3) × i^(1/2)")
            o.append(f"           = (1/{n}) × {R_hyd_inc:.3f}^(2/3) × {i:.6f}^(1/2)")
            if R_hyd_inc > 0:
                o.append(f"           = {1/n:.2f} × {R_hyd_inc**(2/3):.4f} × {math.sqrt(i):.6f}")
            o.append(f"           = {V_inc:.3f} m/s")
            o.append("")

            Q_chk_inc = V_inc * A_inc
            o.append("  15. 流量校核:")
            o.append(f"      Q计算 = A加大 × V加大")
            o.append(f"           = {A_inc:.3f} × {V_inc:.3f}")
            o.append(f"           = {Q_chk_inc:.3f} m³/s")
            if Q_inc > 0:
                o.append(f"      误差 = {abs(Q_chk_inc - Q_inc) / Q_inc * 100:.2f}%")
            o.append("")

            o.append("  16. 净空面积计算:")
            o.append(f"      PA加大 = (A总 - A加大) / A总 × 100%")
            o.append(f"           = ({A_total:.3f} - {A_inc:.3f}) / {A_total:.3f} × 100%")
            o.append(f"           = {fb_pct_inc:.1f}%")
            o.append("")
            o.append("  17. 净空高度计算:")
            if stype == "圆形":
                D = result['D']
                o.append(f"      Fb加大 = D - h加大 = {D:.3f} - {h_inc:.3f} = {fb_hgt_inc:.3f} m")
            elif stype in ("马蹄形标准Ⅰ型", "马蹄形标准Ⅱ型"):
                r_val = result['r']
                o.append(f"      Fb加大 = 2r - h加大 = {2*r_val:.3f} - {h_inc:.3f} = {fb_hgt_inc:.3f} m")
            else:
                H_total_val = result.get('H_total', 0)
                o.append(f"      Fb加大 = H - h加大 = {H_total_val:.3f} - {h_inc:.3f} = {fb_hgt_inc:.3f} m")
            o.append("")

            # 验证
            o.append("【五、设计验证】")
            o.append("")
            vel_ok = v_min <= V_d <= v_max
            fb_pct_ok = fb_pct_inc >= 15
            fb_hgt_ok = fb_hgt_inc >= 0.4

            o.append(f"  18. 流速验证:")
            o.append(f"      范围要求: {v_min} ≤ V ≤ {v_max} m/s")
            o.append(f"      设计流速: V = {V_d:.3f} m/s")
            o.append(f"      结果: {'通过 ✓' if vel_ok else '未通过 ✗'}")
            o.append("")
            o.append(f"  19. 净空面积验证:")
            o.append(f"      规范要求: 净空面积 ≥ 15%")
            o.append(f"      计算结果: {fb_pct_inc:.1f}%")
            o.append(f"      结果: {'通过 ✓' if fb_pct_ok else '需注意 ✗'}")
            o.append("")
            o.append(f"  20. 净空高度验证:")
            o.append(f"      规范要求: 净空高度 ≥ 0.4m")
            o.append(f"      计算结果: Fb = {fb_hgt_inc:.3f} m")
            o.append(f"      结果: {'通过 ✓' if fb_hgt_ok else '需注意 ✗'}")
            o.append("")

        o.append("=" * 70)
        o.append(f"  综合验证结果: {'全部通过 ✓' if result['success'] else '未通过 ✗'}")
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

        stype = self.input_params.get('section_type', '圆形')
        Q = self.input_params['Q']
        Q_inc = result['Q_increased']
        axes = self.section_fig.subplots(1, 2)

        if stype == "圆形":
            D = result['D']
            self._draw_circular(axes[0], D, result['h_design'], result['V_design'], Q, "设计流量")
            self._draw_circular(axes[1], D, result['h_increased'], result['V_increased'], Q_inc, "加大流量")
        elif stype == "圆拱直墙型":
            B = result['B']; H = result['H_total']; theta = math.radians(result['theta_deg'])
            self._draw_horseshoe(axes[0], B, H, theta, result['h_design'], result['V_design'], Q, "设计流量")
            self._draw_horseshoe(axes[1], B, H, theta, result['h_increased'], result['V_increased'], Q_inc, "加大流量")
        else:
            r_val = result['r']
            sec_int = self.input_params.get('sec_type_int', 1)
            self._draw_horseshoe_std(axes[0], sec_int, r_val, result['h_design'], result['V_design'], Q, "设计流量")
            self._draw_horseshoe_std(axes[1], sec_int, r_val, result['h_increased'], result['V_increased'], Q_inc, "加大流量")

        self.section_fig.tight_layout()
        self.section_canvas.draw()

    def _draw_circular(self, ax, D, h_w, V, Q, title):
        R = D / 2
        theta = np.linspace(0, 2*np.pi, 100)
        cx = R * np.cos(theta); cy = R + R * np.sin(theta)
        ax.plot(cx, cy, 'k-', lw=2)
        if 0 < h_w < D:
            h_off = h_w - R
            if abs(h_off) <= R:
                half_a = math.acos(max(-1, min(1, h_off / R)))
                water_w = math.sqrt(max(0, R**2 - h_off**2))
                wa = np.linspace(np.pi/2 + half_a, np.pi/2 - half_a + 2*np.pi, 50)
                wx = R * np.cos(wa); wy = R + R * np.sin(wa)
                mask = wy <= h_w + 0.001
                wxf = wx[mask]; wyf = wy[mask]
                if len(wxf) > 0:
                    px = np.concatenate([[water_w], wxf, [-water_w]])
                    py = np.concatenate([[h_w], wyf, [h_w]])
                    ax.fill(px, py, color='lightblue', alpha=0.7)
                    ax.plot([-water_w, water_w], [h_w, h_w], 'b-', lw=1.5)
        ax.annotate('', xy=(R, R), xytext=(-R, R), arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, R+0.15*R, f'D={D:.2f}m', ha='center', fontsize=9, color='gray')
        if h_w > 0:
            ax.annotate('', xy=(-R-0.12*R, h_w), xytext=(-R-0.12*R, 0), arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-R-0.2*R, h_w/2, f'h={h_w:.2f}m', ha='right', fontsize=8, color='blue', rotation=90, va='center')
        ax.set_xlim(-R*1.7, R*1.7); ax.set_ylim(-R*0.4, D*1.2)
        ax.set_aspect('equal'); ax.set_title(f'{title}\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3); ax.axhline(y=0, color='brown', lw=3)

    def _draw_horseshoe(self, ax, B, H_total, theta_rad, h_w, V, Q, title):
        """绘制圆拱直墙型断面"""
        R_arch = (B / 2) / math.sin(theta_rad / 2) if abs(math.sin(theta_rad / 2)) > 1e-9 else B/2
        H_arch = R_arch * (1 - math.cos(theta_rad / 2))
        H_straight = max(0, H_total - H_arch)
        center_y = H_straight + R_arch * math.cos(theta_rad / 2)
        # 拱部
        start_angle = math.pi/2 - theta_rad/2
        end_angle = math.pi/2 + theta_rad/2
        arch_theta = np.linspace(start_angle, end_angle, 50)
        arch_x = R_arch * np.cos(arch_theta)
        arch_y = center_y + R_arch * np.sin(arch_theta)
        # 直墙
        ax.plot([-B/2, -B/2], [0, H_straight], 'k-', lw=2)
        ax.plot([B/2, B/2], [0, H_straight], 'k-', lw=2)
        ax.plot([-B/2, B/2], [0, 0], 'k-', lw=2)
        ax.plot(arch_x, arch_y, 'k-', lw=2)
        # 水面
        if h_w > 0:
            if h_w <= H_straight:
                wx = [-B/2, -B/2, B/2, B/2]
                wy = [0, h_w, h_w, 0]
                ax.fill(wx, wy, color='lightblue', alpha=0.7)
            else:
                rect_x = [-B/2, -B/2, B/2, B/2]
                rect_y = [0, min(h_w, H_straight), min(h_w, H_straight), 0]
                ax.fill(rect_x, rect_y, color='lightblue', alpha=0.7)
                if h_w > H_straight and h_w <= H_total:
                    hw_in = h_w - H_straight
                    d_temp = R_arch - (H_arch - hw_in)
                    if abs(d_temp) <= R_arch:
                        alpha_t = math.acos(max(-1, min(1, d_temp / R_arch)))
                        hw_half = R_arch * math.sin(alpha_t) if alpha_t > 0 else 0
                        if hw_half > 0:
                            fill_theta = np.linspace(start_angle, math.pi/2 - alpha_t, 30)
                            fill_theta2 = np.linspace(math.pi/2 + alpha_t, end_angle, 30)
                            fill_x = np.concatenate([[hw_half], R_arch*np.cos(fill_theta[::-1]), R_arch*np.cos(fill_theta2[::-1]), [-hw_half]])
                            fill_y = np.concatenate([[h_w], center_y+R_arch*np.sin(fill_theta[::-1]), center_y+R_arch*np.sin(fill_theta2[::-1]), [h_w]])
                            valid = fill_y <= h_w + 0.01
                            ax.fill(fill_x[valid], fill_y[valid], color='lightblue', alpha=0.7)
            ax.plot([-B/2, B/2], [h_w, h_w], 'b-', lw=1.5)
        # 标注
        ax.annotate('', xy=(B/2, -0.08*H_total), xytext=(-B/2, -0.08*H_total), arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, -0.16*H_total, f'B={B:.2f}m', ha='center', fontsize=9, color='gray')
        ax.annotate('', xy=(B/2+0.1*B, H_total), xytext=(B/2+0.1*B, 0), arrowprops=dict(arrowstyle='<->', color='purple', lw=1.5))
        ax.text(B/2+0.18*B, H_total/2, f'H={H_total:.2f}m', fontsize=8, color='purple', rotation=90, va='center')
        ax.set_xlim(-B*0.9, B*0.9); ax.set_ylim(-H_total*0.3, H_total*1.2)
        ax.set_aspect('equal'); ax.set_title(f'{title}\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3); ax.axhline(y=0, color='brown', lw=3)

    def _draw_horseshoe_std(self, ax, sec_type, r, h_w, V, Q, title):
        """绘制标准马蹄形断面（精确轮廓）"""
        if sec_type == 1:
            t = 3.0; theta = 0.294515; type_name = '标准Ⅰ型'
        else:
            t = 2.0; theta = 0.424031; type_name = '标准Ⅱ型'

        R_arch = t * r
        e = R_arch * (1 - math.cos(theta))

        def get_half_width(h):
            if h <= 0: return 0
            elif h <= e:
                cos_val = max(-1, min(1, 1 - h / R_arch))
                beta = math.acos(cos_val)
                return R_arch * math.sin(beta)
            elif h <= r:
                sin_val = max(-1, min(1, (1 - h / r) / t))
                alpha = math.asin(sin_val)
                return r * (t * math.cos(alpha) - t + 1)
            elif h <= 2 * r:
                cos_val = max(-1, min(1, h / r - 1))
                phi_half = math.acos(cos_val)
                return r * math.sin(phi_half)
            else: return 0

        num_points = 100
        heights = np.linspace(0, 2*r, num_points)
        left_x = []; left_y = []; right_x = []; right_y = []
        for h in heights:
            hw = get_half_width(h)
            left_x.append(-hw); left_y.append(h)
            right_x.append(hw); right_y.append(h)

        ax.plot(left_x, left_y, 'k-', lw=2)
        ax.plot(right_x, right_y, 'k-', lw=2)

        if h_w > 0 and h_w < 2 * r:
            water_half_width = get_half_width(h_w)
            water_heights = np.linspace(0, h_w, 50)
            wl_x = [-get_half_width(h) for h in water_heights]
            wl_y = list(water_heights)
            wr_x = [get_half_width(h) for h in water_heights]
            wr_y = list(water_heights)
            fill_x = wl_x + wr_x[::-1]
            fill_y = wl_y + wr_y[::-1]
            ax.fill(fill_x, fill_y, color='lightblue', alpha=0.7)
            ax.plot([-water_half_width, water_half_width], [h_w, h_w], 'b-', lw=1.5)

        ax.annotate('', xy=(r, r), xytext=(0, r), arrowprops=dict(arrowstyle='->', color='gray', lw=1.5))
        ax.text(r/2, r+0.15*r, f'r={r:.2f}m', ha='center', fontsize=9, color='gray')
        if h_w > 0:
            ax.annotate('', xy=(-r-0.2*r, h_w), xytext=(-r-0.2*r, 0), arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-r-0.3*r, h_w/2, f'h={h_w:.2f}m', ha='right', fontsize=8, color='blue', rotation=90, va='center')
        ax.set_xlim(-r*2.2, r*2.2); ax.set_ylim(-r*0.3, 2.3*r)
        ax.set_aspect('equal'); ax.set_title(f'{title} ({type_name})\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3); ax.axhline(y=0, color='brown', lw=3)

    # ================================================================
    # 清空 / 导出
    # ================================================================
    def _clear(self):
        self._show_initial_help()
        self.section_fig.clear(); self.section_canvas.draw()
        self.inc_hint.setText("(留空则自动计算)")
        self.current_result = None

    def _export_dxf(self):
        if not self.current_result or not self.current_result.get('success'):
            InfoBar.warning("提示", "请先进行计算后再导出。", parent=self._info_parent(), duration=3000, position=InfoBarPosition.TOP); return
        res = self.current_result; p = self.input_params
        stype = p.get('section_type', '圆形')
        if stype == '圆形':
            D = res.get('D', 0.0)
            default_name = f'隧洞断面_圆形_D{D:.2f}.dxf'
        elif stype == '圆拱直墙型':
            B = res.get('B', 0.0); H = res.get('H_total', 0.0)
            default_name = f'隧洞断面_圆拱直墙_B{B:.2f}xH{H:.2f}.dxf'
        else:
            r = res.get('r', 0.0)
            default_name = f'隧洞断面_马蹄形_r{r:.2f}.dxf'
        scales = ['1:20', '1:50', '1:100', '1:200', '1:500']
        scale_str, ok = QInputDialog.getItem(self, '选择比例尺', '输出比例尺 (图纸单位: mm):', scales, 2, False)
        if not ok: return
        scale_denom = int(scale_str.split(':')[1])
        filepath, _ = QFileDialog.getSaveFileName(
            self, "保存DXF文件", default_name, "DXF文件 (*.dxf);;所有文件 (*.*)"
        )
        if not filepath: return
        try:
            export_tunnel_dxf(filepath, res, p, scale_denom)
            InfoBar.success("导出成功", f"DXF已保存到: {filepath}", parent=self._info_parent(), duration=4000, position=InfoBarPosition.TOP)
            ask_open_file(filepath, self._info_parent())
        except ImportError as e:
            InfoBar.error("缺少依赖", str(e), parent=self._info_parent(), duration=6000, position=InfoBarPosition.TOP)
        except PermissionError:
            InfoBar.error("文件被占用", "无法写入文件，请关闭已打开的同名DXF文件。", parent=self._info_parent(), duration=8000, position=InfoBarPosition.TOP)
        except Exception as e:
            InfoBar.error("导出失败", f"DXF导出失败: {str(e)}", parent=self._info_parent(), duration=5000, position=InfoBarPosition.TOP)

    def _export_report(self):
        if not self.current_result or not self.current_result.get('success'):
            InfoBar.warning("提示", "请先进行计算后再导出。", parent=self._info_parent(), duration=3000, position=InfoBarPosition.TOP); return
        filepath, _ = QFileDialog.getSaveFileName(self, "保存报告", "", "文本文件 (*.txt);;所有文件 (*.*)")
        if not filepath: return
        try:
            content = self._export_plain_text if self._export_plain_text else ''
            with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
            InfoBar.success("导出成功", f"报告已保存到: {filepath}", parent=self._info_parent(), duration=4000, position=InfoBarPosition.TOP)
            ask_open_file(filepath, self._info_parent())
        except PermissionError:
            InfoBar.error("文件被占用", "无法写入文件，请先关闭已打开的同名文件（如记事本等），然后重新操作。", parent=self._info_parent(), duration=8000, position=InfoBarPosition.TOP)
        except Exception as e:
            InfoBar.error("导出失败", str(e), parent=self._info_parent(), duration=5000, position=InfoBarPosition.TOP)

    def _export_word(self):
        if not WORD_EXPORT_AVAILABLE:
            InfoBar.warning("缺少依赖", "需要: pip install python-docx latex2mathml lxml", parent=self._info_parent(), duration=6000, position=InfoBarPosition.TOP); return
        if not self.current_result or not self.current_result.get('success'):
            InfoBar.warning("提示", "请先进行计算后再导出。", parent=self._info_parent(), duration=3000, position=InfoBarPosition.TOP); return
        filepath, _ = QFileDialog.getSaveFileName(self, "保存Word报告", "", "Word文档 (*.docx);;所有文件 (*.*)")
        if not filepath: return
        try:
            self._build_word_report(filepath)
            InfoBar.success("导出成功", f"Word报告已保存到: {filepath}", parent=self._info_parent(), duration=4000, position=InfoBarPosition.TOP)
            ask_open_file(filepath, self._info_parent())
        except PermissionError:
            InfoBar.error("文件被占用", "无法写入文件，请先关闭已打开的同名Word文档，然后重新操作。", parent=self._info_parent(), duration=8000, position=InfoBarPosition.TOP)
        except Exception as e:
            InfoBar.error("导出失败", str(e), parent=self._info_parent(), duration=5000, position=InfoBarPosition.TOP)

    def _build_word_report(self, filepath):
        """构建Word报告文档（方案3高端咨询报告风格）"""
        stype = self.input_params.get('section_type', '圆形')
        method = self.current_result.get("design_method", "")

        doc = create_styled_doc(
            title='隧洞水力计算书',
            subtitle=f'{stype}断面  ·  {method}',
            header_text=f'隧洞水力计算书（{stype}断面）'
        )
        doc.add_page_break()

        # 一、基础公式
        doc_add_h1(doc, '一、基础公式')
        doc_add_formula(doc, r'Q = \frac{1}{n} \cdot A \cdot R^{2/3} \cdot i^{1/2}', '曼宁公式：')
        doc_add_formula(doc, r'R = \frac{A}{P}', '水力半径：')

        # 二、计算过程
        doc_add_h1(doc, '二、计算过程')
        doc_render_calc_text(doc, self._export_plain_text or '', skip_title_keyword='隧洞水力计算结果')

        # 三、断面图
        try:
            import tempfile
            tmp = os.path.join(tempfile.gettempdir(), '_tunnel_section.png')
            self.section_fig.savefig(tmp, dpi=150, bbox_inches='tight')
            doc_add_h1(doc, '三、断面图')
            doc_add_figure(doc, tmp, width_cm=14)
            os.remove(tmp)
        except Exception:
            pass
        doc.save(filepath)
