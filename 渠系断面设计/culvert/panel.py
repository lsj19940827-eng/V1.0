# -*- coding: utf-8 -*-
"""
矩形暗涵水力计算面板 —— QWidget 版本

支持：矩形暗涵（水力最佳断面 / 指定底宽 / 指定宽深比）
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
    QSplitter, QFrame, QTabWidget, QTextEdit, QFileDialog, QScrollArea
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

from 矩形暗涵设计 import (
    quick_calculate_rectangular_culvert,
    get_required_freeboard_height_rect,
    MIN_FREEBOARD_PCT_RECT, MAX_FREEBOARD_PCT_RECT, MIN_FREEBOARD_HGT_RECT,
    OPTIMAL_BH_RATIO, HB_RATIO_LIMIT,
)

from 渠系断面设计.styles import P, S, W, E, BG, CARD, BD, T1, T2, INPUT_LABEL_STYLE, INPUT_SECTION_STYLE, INPUT_HINT_STYLE
from 渠系断面设计.export_utils import (
    WORD_EXPORT_AVAILABLE, add_formula_to_doc, try_convert_formula_line, ask_open_file,
    create_styled_doc, doc_add_h1, doc_add_formula, doc_render_calc_text, doc_add_figure,
)
from 渠系断面设计.formula_renderer import (
    plain_text_to_formula_html, load_formula_page, make_plain_html,
    HelpPageBuilder
)
if WORD_EXPORT_AVAILABLE:
    from docx import Document as DocxDocument
    from docx.shared import Pt, Cm


class CulvertPanel(QWidget):
    """矩形暗涵水力计算面板"""

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

    def _build_input(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(6)
        grp = QGroupBox("输入参数")
        fl = QVBoxLayout(grp)
        fl.setSpacing(5)

        # 通用参数
        self.Q_edit = self._field(fl, "设计流量 Q (m³/s):", "5.0")
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
        self.bh_lbl, self.bh_edit = self._field2(fl, "手动宽深比:", "")
        self.B_lbl, self.B_edit = self._field2(fl, "手动底宽 B (m):", "")
        fl.addWidget(self._hint("(二选一输入，留空则自动计算)"))
        lbl_b1 = QLabel("高宽比限值H/B（或B/H）一般不超过1.2")
        lbl_b1.setStyleSheet(f"font-family: 'Microsoft YaHei', sans-serif; font-size: 11px; color: #0066CC;")
        fl.addWidget(lbl_b1)
        lbl_b2 = QLabel("留空则采用水力最佳断面（β=B/h=2）")
        lbl_b2.setStyleSheet(f"font-family: 'Microsoft YaHei', sans-serif; font-size: 11px; color: #0066CC;")
        fl.addWidget(lbl_b2)
        lbl_ref = QLabel("参考《涵洞》（熊启钧 编著）")
        lbl_ref.setStyleSheet(f"font-family: 'Microsoft YaHei', sans-serif; font-size: 11px; color: {T2};")
        fl.addWidget(lbl_ref)

        fl.addWidget(self._sep())
        self.detail_cb = CheckBox("输出详细计算过程")
        self.detail_cb.setChecked(True)
        fl.addWidget(self.detail_cb)

        br = QHBoxLayout()
        cb = PrimaryPushButton("计算"); cb.setCursor(Qt.PointingHandCursor); cb.clicked.connect(self._calculate)
        clb = PushButton("清空"); clb.setCursor(Qt.PointingHandCursor); clb.clicked.connect(self._clear)
        br.addWidget(cb); br.addWidget(clb); fl.addLayout(br)

        er = QHBoxLayout()
        ec = PushButton("导出图表"); ec.clicked.connect(self._export_charts)
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

    def _show_initial_help(self):
        h = HelpPageBuilder("矩形暗涵水力计算", '请输入参数后点击“计算”按钮')
        h.section("断面特点")
        h.bullet_list([
            "推荐宽深比 0.5~2.5",
            "高宽比限值 H/B（或B/H）一般不超过 1.2",
            "最小净空面积 10%，最大 30%",
            "最小净空高度 0.4m",
        ])
        h.section("水力最佳断面")
        h.text("当底宽和宽深比均留空时，自动采用水力最佳断面：")
        h.formula("β = B/h = 2", "水力最佳宽深比")
        h.hint("即底宽等于 2 倍水深时，水力效率最高")
        h.section("净空约束条件")
        h.text("参考《灌溉与排水工程设计标准》 GB 50288-2018：")
        h.bullet_list([
            "净空面积应为涵洞断面总面积的 10%~30%",
            "净空高度在任何情况下均不得小于 0.4m",
            "当 H ≤ 3m 时，净空高度应 ≥ H/6",
            "当 H > 3m 时，净空高度应 ≥ 0.5m",
        ])
        h.section("宽深比说明")
        h.bullet_list([
            "宽深比 β = B/h（底宽 / 设计水深）",
            "可手动指定宽深比或底宽",
            "留空则自动按水力最佳断面计算",
        ])
        h.section("曼宁公式")
        h.formula("Q = (1/n) × A × R^(2/3) × i^(1/2)", "流量公式")
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
            manual_B = self._fval_opt(self.B_edit)
            target_BH_ratio = self._fval_opt(self.bh_edit)

            self.input_params = {
                'Q': Q, 'n': n, 'slope_inv': slope_inv,
                'v_min': v_min, 'v_max': v_max,
                'manual_B': manual_B,
                'target_BH_ratio': target_BH_ratio,
                'manual_increase': manual_increase
            }

            result = quick_calculate_rectangular_culvert(
                Q=Q, n=n, slope_inv=slope_inv,
                v_min=v_min, v_max=v_max,
                target_BH_ratio=target_BH_ratio,
                manual_B=manual_B,
                manual_increase_percent=manual_increase
            )

            self.current_result = result

            if result.get('success') and 'increase_percent' in result:
                ap = result['increase_percent']
                src = "手动指定" if self.inc_edit.text().strip() else "自动计算"
                self.inc_hint.setText(f"({src}: {ap:.1f}%)")

            self._update_result_display(result)
            self._update_section_plot(result)

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
        detail = self.detail_cb.isChecked()
        self._show_culvert_result(result, detail)

    def _show_culvert_result(self, result, detail):
        p = self.input_params
        Q, n = p['Q'], p['n']
        slope_inv = p['slope_inv']; i = 1.0 / slope_inv
        v_min, v_max = p['v_min'], p['v_max']
        inc_src = "(手动指定)" if p.get('manual_increase') else "(自动计算)"
        is_optimal = result.get('is_optimal_section', False)

        B = result['B']; H = result['H']
        h_d = result['h_design']; V_d = result['V_design']
        A_d = result['A_design']; P_d = result['P_design']
        R_hyd_d = result['R_hyd_design']
        BH_ratio = result['BH_ratio']; HB_ratio = result['HB_ratio']
        fb_pct_d = result['freeboard_pct_design']; fb_hgt_d = result['freeboard_hgt_design']
        inc_pct = result['increase_percent']; Q_inc = result['Q_increased']
        h_inc = result['h_increased']; V_inc = result['V_increased']
        fb_pct_inc = result['freeboard_pct_inc']; fb_hgt_inc = result['freeboard_hgt_inc']
        fb_min_req = result['fb_min_required']
        A_total = result.get('A_total', B * H)

        vel_ok = v_min <= V_d <= v_max
        if H <= 3.0:
            fb_req_by_rule = max(0.4, H / 6.0)
        else:
            fb_req_by_rule = 0.5
        fb_area_ok = 10.0 <= fb_pct_inc <= 30.0
        fb_hgt_ok = fb_hgt_inc >= fb_req_by_rule
        fb_ok = fb_area_ok and fb_hgt_ok

        o = []
        o.append("=" * 70)
        if is_optimal:
            o.append("              矩形暗涵水力计算结果（水力最佳断面）")
        else:
            o.append("              矩形暗涵水力计算结果")
        o.append("=" * 70)
        o.append("")

        if not detail:
            # ── 简要输出 ──
            o.append("【输入参数】")
            o.append(f"  设计流量 Q = {Q:.3f} m³/s")
            o.append(f"  糙率 n = {n}")
            o.append(f"  水力坡降 = 1/{int(slope_inv)}")
            o.append(f"  不淤流速 = {v_min} m/s")
            o.append(f"  不冲流速 = {v_max} m/s")
            o.append("")

            o.append("【断面尺寸】")
            if is_optimal:
                o.append("  ★ 采用水力最佳断面（β=B/h=2）")
            o.append(f"  宽度 B = {B:.2f} m")
            o.append(f"  高度 H = {H:.2f} m")
            o.append(f"  宽深比 β = B/h = {BH_ratio:.3f}")
            o.append(f"  高宽比 H/B = {HB_ratio:.3f}")
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
            o.append(f"  流速验证: {'✓ 通过' if vel_ok else '✗ 未通过'}")
            o.append(f"  净空验证: {'✓ 通过' if fb_ok else '✗ 需注意'}")
            o.append("")

        else:
            # ── 详细输出 ──
            o.append("【一、输入参数】")
            o.append(f"  设计流量 Q = {Q:.3f} m³/s")
            o.append(f"  糙率 n = {n}")
            o.append(f"  水力坡降 = 1/{int(slope_inv)}")
            o.append(f"  不淤流速 = {v_min} m/s")
            o.append(f"  不冲流速 = {v_max} m/s")
            o.append("")

            o.append("【二、断面尺寸】")
            if is_optimal:
                o.append("  ★★★ 采用水力最佳断面 ★★★")
                o.append("  (当底宽和宽深比均留空时，自动按水力最佳断面计算)")
                o.append("  水力最佳断面宽深比 β = B/h = 2（即底宽等于2倍水深）")
                o.append("")
            o.append(f"  宽度 B = {B:.2f} m")
            o.append(f"  高度 H = {H:.2f} m")
            o.append("")

            o.append("  1. 宽深比计算:")
            o.append(f"     β = B / h")
            o.append(f"       = {B:.2f} / {h_d:.3f}")
            o.append(f"       = {BH_ratio:.3f}")
            if is_optimal:
                o.append("     (水力最佳断面目标值 β = 2.0)")
            o.append("")

            o.append("  2. 高宽比计算:")
            o.append(f"     H/B = {H:.2f} / {B:.2f} = {HB_ratio:.3f}")
            o.append("     (限值要求: H/B 或 B/H 一般不超过1.2)")
            o.append("")

            o.append("  3. 总断面积计算:")
            o.append(f"     A总 = B × H")
            o.append(f"        = {B:.2f} × {H:.2f}")
            o.append(f"        = {A_total:.3f} m²")
            o.append("")

            o.append("【三、设计流量工况】")
            o.append("  设计水深计算:")
            o.append(f"     根据设计流量 Q = {Q:.3f} m³/s 和底宽 B = {B:.2f} m，利用曼宁公式反算水深:")
            o.append(f"     h = {h_d:.3f} m")
            o.append("")

            o.append("  4. 过水面积计算:")
            o.append(f"     A = B × h")
            o.append(f"       = {B:.2f} × {h_d:.3f}")
            o.append(f"       = {A_d:.3f} m²")
            o.append("")

            o.append("  5. 湿周计算:")
            o.append(f"     χ = B + 2×h")
            o.append(f"       = {B:.2f} + 2×{h_d:.3f}")
            o.append(f"       = {B:.2f} + {2*h_d:.3f}")
            o.append(f"       = {P_d:.3f} m")
            o.append("")

            o.append("  6. 水力半径计算:")
            o.append(f"     R = A / χ")
            o.append(f"       = {A_d:.3f} / {P_d:.3f}")
            o.append(f"       = {R_hyd_d:.3f} m")
            o.append("")

            o.append("  7. 设计流速计算 (曼宁公式):")
            o.append(f"     V = (1/n) × R^(2/3) × i^(1/2)")
            o.append(f"       = (1/{n}) × {R_hyd_d:.3f}^(2/3) × {i:.6f}^(1/2)")
            if R_hyd_d > 0:
                o.append(f"       = {1/n:.2f} × {R_hyd_d**(2/3):.4f} × {math.sqrt(i):.6f}")
            o.append(f"       = {V_d:.3f} m/s")
            o.append("")

            Q_chk = A_d * V_d
            o.append("  8. 计算流量验证:")
            o.append(f"     Q计算 = A × V")
            o.append(f"          = {A_d:.3f} × {V_d:.3f}")
            o.append(f"          = {Q_chk:.3f} m³/s")
            if Q > 0:
                o.append(f"     误差 = {abs(Q_chk - Q) / Q * 100:.2f}%")
            o.append("")

            o.append("  9. 净空高度计算:")
            o.append(f"      Fb = H - h")
            o.append(f"         = {H:.2f} - {h_d:.3f}")
            o.append(f"         = {fb_hgt_d:.3f} m")
            o.append("")

            o.append("  10. 净空面积比计算:")
            o.append(f"      PA = (H - h) / H × 100%")
            o.append(f"         = ({H:.2f} - {h_d:.3f}) / {H:.2f} × 100%")
            o.append(f"         = {fb_pct_d:.1f}%")
            o.append("")

            o.append("【四、加大流量工况】")
            o.append(f"  流量加大比例 = {inc_pct:.1f}% {inc_src}")
            o.append("")

            o.append("  11. 加大流量计算:")
            o.append(f"      Q加大 = Q × (1 + {inc_pct:.1f}%)")
            o.append(f"           = {Q:.3f} × {1 + inc_pct/100:.3f}")
            o.append(f"           = {Q_inc:.3f} m³/s")
            o.append("")

            o.append("  12. 加大水深计算:")
            o.append(f"      根据加大流量 Q加大 = {Q_inc:.3f} m³/s 和底宽 B = {B:.2f} m，利用曼宁公式反算水深:")
            o.append(f"      h加大 = {h_inc:.3f} m")
            o.append("")

            A_inc = B * h_inc
            chi_inc = B + 2 * h_inc
            R_inc = A_inc / chi_inc if chi_inc > 0 else 0

            o.append("  13. 加大流量工况过水面积:")
            o.append(f"      A加大 = B × h加大")
            o.append(f"           = {B:.2f} × {h_inc:.3f}")
            o.append(f"           = {A_inc:.3f} m²")
            o.append("")

            o.append("  14. 加大流量工况湿周:")
            o.append(f"      χ加大 = B + 2×h加大")
            o.append(f"           = {B:.2f} + 2×{h_inc:.3f}")
            o.append(f"           = {B:.2f} + {2 * h_inc:.3f}")
            o.append(f"           = {chi_inc:.3f} m")
            o.append("")

            o.append("  15. 加大流量工况水力半径:")
            o.append(f"      R加大 = A加大 / χ加大")
            o.append(f"           = {A_inc:.3f} / {chi_inc:.3f}")
            o.append(f"           = {R_inc:.3f} m")
            o.append("")

            o.append("  16. 加大流量工况流速 (曼宁公式):")
            o.append(f"      V加大 = (1/n) × R^(2/3) × i^(1/2)")
            o.append(f"           = (1/{n}) × {R_inc:.3f}^(2/3) × {i:.6f}^(1/2)")
            if R_inc > 0:
                o.append(f"           = {1/n:.2f} × {R_inc**(2/3):.4f} × {math.sqrt(i):.6f}")
            o.append(f"           = {V_inc:.3f} m/s")
            o.append("")

            Q_chk_inc = V_inc * A_inc
            o.append("  17. 流量校核:")
            o.append(f"      Q计算 = A加大 × V加大")
            o.append(f"           = {A_inc:.3f} × {V_inc:.3f}")
            o.append(f"           = {Q_chk_inc:.3f} m³/s")
            if Q_inc > 0:
                o.append(f"      误差 = {abs(Q_chk_inc - Q_inc) / Q_inc * 100:.2f}%")
            o.append("")

            o.append("  18. 加大流量工况净空:")
            o.append(f"      净空高度 Fb加大 = H - h加大 = {H:.2f} - {h_inc:.3f} = {fb_hgt_inc:.3f} m")
            o.append(f"      净空面积 PA加大 = (H - h加大) / H × 100% = {fb_pct_inc:.1f}%")
            o.append("")

            # 净空验证
            o.append("【五、净空验证】")
            o.append("")
            o.append("  根据《灌溉与排水工程设计标准》 GB 50288-2018要求：")
            o.append("  1. 净空面积要求：应为涵洞断面总面积的10%~30%")
            o.append("  2. 净空高度要求：")
            o.append("     - 在任何情况下，净空高度均不得小于0.4m")
            if H <= 3.0:
                o.append(f"     - 当涵洞内侧高度H≤3m时，净空高度应≥H/6")
                o.append(f"       H = {H:.2f}m ≤ 3m")
                o.append(f"       H/6 = {H/6:.3f}m")
                o.append(f"       要求净空高度≥max(0.4, {H/6:.3f}) = {fb_req_by_rule:.3f}m")
            else:
                o.append(f"     - 当涵洞内侧高度H>3m时，净空高度应≥0.5m")
                o.append(f"       H = {H:.2f}m > 3m")
                o.append(f"       要求净空高度≥0.5m")
            o.append("")

            o.append("  净空验证结果（加大流量工况）：")
            o.append(f"  a) 净空面积验证: 10% ≤ {fb_pct_inc:.1f}% ≤ 30%")
            o.append(f"     → {'通过 ✓' if fb_area_ok else '未通过 ✗'}")
            o.append(f"  b) 净空高度验证: {fb_hgt_inc:.3f}m ≥ {fb_req_by_rule:.3f}m")
            o.append(f"     → {'通过 ✓' if fb_hgt_ok else '未通过 ✗'}")
            o.append("")

            # 综合验证
            o.append("【六、综合验证】")
            o.append(f"  1. 流速验证: {v_min} ≤ {V_d:.3f} ≤ {v_max} → {'通过 ✓' if vel_ok else '未通过 ✗'}")
            o.append(f"  2. 净空面积验证: → {'通过 ✓' if fb_area_ok else '未通过 ✗'}")
            o.append(f"  3. 净空高度验证: → {'通过 ✓' if fb_hgt_ok else '未通过 ✗'}")
            o.append("")

        o.append("=" * 70)
        if is_optimal:
            o.append(f"  综合验证结果: {'全部通过 ✓' if result['success'] else '未通过 ✗'} (水力最佳断面)")
        else:
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

        Q = self.input_params['Q']
        Q_inc = result['Q_increased']
        B = result['B']; H = result['H']
        axes = self.section_fig.subplots(1, 2)
        self._draw_rect(axes[0], B, H, result['h_design'], result['V_design'], Q, "设计流量")
        self._draw_rect(axes[1], B, H, result['h_increased'], result['V_increased'], Q_inc, "加大流量")
        self.section_fig.tight_layout()
        self.section_canvas.draw()

    def _draw_rect(self, ax, B, H, h_w, V, Q, title):
        # 绘制涵洞壁
        ax.plot([-B/2, -B/2], [0, H], 'k-', lw=2)
        ax.plot([B/2, B/2], [0, H], 'k-', lw=2)
        ax.plot([-B/2, B/2], [0, 0], 'k-', lw=2)
        ax.plot([-B/2, B/2], [H, H], 'k-', lw=2)  # 顶部实线（暗涵封闭）
        # 水面
        if h_w > 0:
            wx = [-B/2, -B/2, B/2, B/2]
            wy = [0, h_w, h_w, 0]
            ax.fill(wx, wy, color='lightblue', alpha=0.7)
            ax.plot([-B/2, B/2], [h_w, h_w], 'b-', lw=1.5)
        # 标注底宽
        ax.annotate('', xy=(B/2, -0.1*H), xytext=(-B/2, -0.1*H),
                     arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, -0.2*H, f'B={B:.2f}m', ha='center', fontsize=9, color='gray')
        # 标注总高
        ax.annotate('', xy=(B/2+0.08*B, H), xytext=(B/2+0.08*B, 0),
                     arrowprops=dict(arrowstyle='<->', color='purple', lw=1.5))
        ax.text(B/2+0.14*B, H/2, f'H={H:.2f}m', fontsize=9, color='purple', rotation=90, va='center')
        # 标注水深
        if h_w > 0:
            ax.annotate('', xy=(-B/2-0.08*B, h_w), xytext=(-B/2-0.08*B, 0),
                         arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-B/2-0.14*B, h_w/2, f'h={h_w:.2f}m', fontsize=9, color='blue', rotation=90, va='center', ha='right')
        # 顶部填充（表示封闭暗涵）
        ax.fill_between([-B/2, B/2], H, H+0.05*H, color='gray', alpha=0.4)
        ax.set_xlim(-B*0.9, B*0.9)
        ax.set_ylim(-H*0.35, H*1.25)
        ax.set_aspect('equal')
        ax.set_title(f'{title}\nQ={Q:.2f}m$^3$/s, V={V:.2f}m/s', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='brown', lw=3)

    # ================================================================
    # 清空 / 导出
    # ================================================================
    def _clear(self):
        self._show_initial_help()
        self.section_fig.clear(); self.section_canvas.draw()
        self.inc_hint.setText("(留空则自动计算)")
        self.current_result = None
        self._export_plain_text = ""

    def _export_charts(self):
        if not self.current_result or not self.current_result.get('success'):
            InfoBar.warning("提示", "请先进行计算后再导出。", parent=self._info_parent(), duration=3000, position=InfoBarPosition.TOP); return
        folder = QFileDialog.getExistingDirectory(self, "选择保存目录")
        if not folder: return
        try:
            self.section_fig.savefig(os.path.join(folder, '矩形暗涵断面图.png'), dpi=150, bbox_inches='tight')
            InfoBar.success("导出成功", f"图表已保存到: {folder}", parent=self._info_parent(), duration=4000, position=InfoBarPosition.TOP)
        except PermissionError:
            InfoBar.error("文件被占用", "无法写入文件，请先关闭已打开的同名图片文件，然后重新操作。", parent=self._info_parent(), duration=8000, position=InfoBarPosition.TOP)
        except Exception as e:
            InfoBar.error("导出失败", str(e), parent=self._info_parent(), duration=5000, position=InfoBarPosition.TOP)

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
        method = self.current_result.get("design_method", "")

        doc = create_styled_doc(
            title='矩形暗涵水力计算书',
            subtitle=method,
            header_text='矩形暗涵水力计算书'
        )
        doc.add_page_break()

        # 一、基础公式
        doc_add_h1(doc, '一、基础公式')
        doc_add_formula(doc, r'Q = \frac{1}{n} \cdot A \cdot R^{2/3} \cdot i^{1/2}', '曼宁公式：')
        doc_add_formula(doc, r'A = B \cdot h', '过水面积：')
        doc_add_formula(doc, r'P = B + 2h', '湿周：')
        doc_add_formula(doc, r'R = \frac{A}{P} = \frac{Bh}{B+2h}', '水力半径：')
        if self.current_result.get('is_optimal_section'):
            doc_add_formula(doc, r'\beta = \frac{B}{h} = 2 \text{ (水力最佳)}', '最佳条件：')

        # 二、计算过程
        doc_add_h1(doc, '二、计算过程')
        doc_render_calc_text(doc, self._export_plain_text or '', skip_title_keyword='矩形暗涵水力计算结果')

        # 三、断面图
        try:
            import tempfile
            tmp = os.path.join(tempfile.gettempdir(), '_culvert_section.png')
            self.section_fig.savefig(tmp, dpi=150, bbox_inches='tight')
            doc_add_h1(doc, '三、断面图')
            doc_add_figure(doc, tmp, width_cm=14)
            os.remove(tmp)
        except Exception:
            pass
        doc.save(filepath)
