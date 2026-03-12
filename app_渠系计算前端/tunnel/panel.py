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
import copy
import html as html_mod

_pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_pkg_root, "calc_渠系计算算法内核"))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QSplitter, QFrame, QTabWidget, QTextEdit, QFileDialog, QScrollArea,
    QPushButton,
)
from PySide6.QtCore import Qt, Signal
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

from app_渠系计算前端.styles import P, S, W, E, BG, CARD, BD, T1, T2, INPUT_LABEL_STYLE, INPUT_SECTION_STYLE, INPUT_HINT_STYLE
from app_渠系计算前端.export_utils import (
    WORD_EXPORT_AVAILABLE, add_formula_to_doc, try_convert_formula_line, ask_open_file,
    create_styled_doc, doc_add_h1, doc_add_formula, doc_render_calc_text, doc_add_figure,
    create_engineering_report_doc, doc_add_eng_h, doc_add_eng_body,
    doc_render_calc_text_eng, update_doc_toc_via_com,
)
from app_渠系计算前端.report_meta import (
    ExportConfirmDialog, build_calc_purpose, REFERENCES_BASE, load_meta
)
from app_渠系计算前端.case_manager import (
    FlowLayout as _FlowLayout,
    CaseTagChip as _CaseTagChip,
    DashedButton as _DashedButton,
    MAX_CASES,
    _SUB, _sub,
    CASE_TAG_ACTIVE_SS as _CASE_TAG_ACTIVE_SS,
    CASE_TAG_INACTIVE_SS as _CASE_TAG_INACTIVE_SS,
    CASE_QUICK_SS as _CASE_QUICK_SS,
)
from app_渠系计算前端.tunnel.dxf_export import export_tunnel_dxf
from app_渠系计算前端.formula_renderer import (
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
    data_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.input_params = {}
        self.current_result = None
        self._export_plain_text = ""
        # 多工况状态
        self._cases = [self._default_case()]
        self._current_case_idx = 0
        self._all_results = []
        self._loading_case = False
        self._init_ui()
        self._rebuild_case_tags()

    # ================================================================
    # 默认工况
    # ================================================================
    @staticmethod
    def _default_case():
        return {
            'custom_label': '',
            'section_type': '圆形',
            'Q': '10.0', 'n': '0.014', 'slope_inv': '2000',
            'v_min': '0.1', 'v_max': '100.0',
            'inc_checked': True, 'inc_pct': '',
            'detail_checked': True,
            # 圆形参数
            'D': '',
            # 圆拱直墙型参数
            'theta_deg': '', 'B_hs': '',
            # 马蹄形参数
            'r': '',
        }

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

        # ---- 工况标签导航 ----
        _tag_row = QHBoxLayout()
        _tag_row.setSpacing(4)
        self._case_tag_container = QWidget()
        self._case_tag_flow = _FlowLayout(self._case_tag_container, spacing=5)
        self._case_tag_flow.setContentsMargins(0, 0, 0, 0)
        _tag_row.addWidget(self._case_tag_container, 1)
        self._add_case_btn = _DashedButton("+ 添加")
        self._add_case_btn.setCursor(Qt.PointingHandCursor)
        self._add_case_btn.setFixedHeight(28)
        self._add_case_btn.clicked.connect(self._add_case)
        _tag_row.addWidget(self._add_case_btn)
        fl.addLayout(_tag_row)
        self._case_count_label = QLabel("1 个计算工况")
        self._case_count_label.setStyleSheet("font-size:11px;color:#999;")
        fl.addWidget(self._case_count_label)

        # 工况管理行（与工况标签挂钩）
        _quick_row = QHBoxLayout()
        _quick_row.setSpacing(4)
        _copy_all_btn = QPushButton("复制参数到所有")
        _copy_all_btn.setCursor(Qt.PointingHandCursor)
        _copy_all_btn.setStyleSheet(_CASE_QUICK_SS)
        _copy_all_btn.setToolTip("将当前工况的参数（不含Q）复制到其余所有工况")
        _copy_all_btn.clicked.connect(self._apply_to_all_cases)
        _quick_row.addWidget(_copy_all_btn)
        _copy_prev_btn = QPushButton("从上一个复制")
        _copy_prev_btn.setCursor(Qt.PointingHandCursor)
        _copy_prev_btn.setStyleSheet(_CASE_QUICK_SS)
        _copy_prev_btn.setToolTip("将上一个工况的参数（不含Q）复制到当前工况")
        _copy_prev_btn.clicked.connect(self._copy_from_prev_case)
        _quick_row.addWidget(_copy_prev_btn)
        self._del_case_btn = QPushButton("删除当前")
        self._del_case_btn.setCursor(Qt.PointingHandCursor)
        self._del_case_btn.setStyleSheet(_CASE_QUICK_SS)
        self._del_case_btn.setToolTip("删除当前选中的工况（至少保留一个）")
        self._del_case_btn.clicked.connect(self._remove_current_case)
        _quick_row.addWidget(self._del_case_btn)
        fl.addLayout(_quick_row)

        fl.addWidget(self._sep())

        # 断面类型
        r = QHBoxLayout(); r.addWidget(QLabel("断面类型:"))
        self.section_combo = ComboBox()
        self.section_combo.addItems(["圆形", "圆拱直墙型", "马蹄形标准Ⅰ型", "马蹄形标准Ⅱ型"])
        self.section_combo.currentTextChanged.connect(self._on_section_type_changed)
        r.addWidget(self.section_combo, 1); fl.addLayout(r)

        # 通用参数
        self.Q_edit = self._field(fl, "设计流量 Q (m³/s):", "10.0")
        self.Q_edit.textChanged.connect(self._on_q_text_changed)
        self.n_edit = self._field(fl, "糙率 n:", "0.014")
        self.slope_edit = self._field(fl, "水力坡降 1/", "2000")

        fl.addWidget(self._slbl("【流速参数】"))
        self.vmin_edit = self._field(fl, "不淤流速 (m/s):", "0.1")
        self.vmax_edit = self._field(fl, "不冲流速 (m/s):", "100.0")
        fl.addWidget(self._hint("(一般情况下保持默认数值即可)"))

        self.inc_cb = CheckBox("考虑加大流量比例系数")
        self.inc_cb.setChecked(True)
        self.inc_cb.stateChanged.connect(self._on_inc_toggle)
        fl.addWidget(self.inc_cb)
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
        self.D_lbl, self.D_edit = self._field2(circ_lay, "指定直径 D (m):", "")
        circ_lay.addWidget(self._hint("(留空则自动计算)"))
        fl.addWidget(self.circ_grp)

        # 圆拱直墙参数
        self.hs_grp = QWidget()
        hs_lay = QVBoxLayout(self.hs_grp); hs_lay.setContentsMargins(0,0,0,0); hs_lay.setSpacing(5)
        hs_lay.addWidget(self._slbl("【圆拱直墙型参数】"))
        self.theta_lbl, self.theta_edit = self._field2(hs_lay, "拱顶圆心角 (度):", "")
        hs_lay.addWidget(self._hint("(留空则采用180°)"))
        self.B_hs_lbl, self.B_hs_edit = self._field2(hs_lay, "指定底宽 B (m):", "")
        hs_lay.addWidget(self._hint("(指定底宽留空则自动计算)"))
        fl.addWidget(self.hs_grp)
        self.hs_grp.hide()

        # 马蹄形参数
        self.shoe_grp = QWidget()
        shoe_lay = QVBoxLayout(self.shoe_grp); shoe_lay.setContentsMargins(0,0,0,0); shoe_lay.setSpacing(5)
        shoe_lay.addWidget(self._slbl("【马蹄形断面参数】"))
        self.r_lbl, self.r_edit = self._field2(shoe_lay, "指定半径 r (m):", "")
        shoe_lay.addWidget(self._hint("(留空则自动计算)"))
        fl.addWidget(self.shoe_grp)
        self.shoe_grp.hide()

        fl.addWidget(self._sep())
        self.detail_cb = CheckBox("输出详细计算过程")
        self.detail_cb.setChecked(True)
        fl.addWidget(self.detail_cb)

        br = QHBoxLayout()
        self._calc_btn = PrimaryPushButton("计算")
        self._calc_btn.setCursor(Qt.PointingHandCursor)
        self._calc_btn.clicked.connect(self._calculate)
        clb = PushButton("清空"); clb.setCursor(Qt.PointingHandCursor); clb.clicked.connect(self._clear)
        br.addWidget(self._calc_btn); br.addWidget(clb); fl.addLayout(br)

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

    def _on_inc_toggle(self, _state):
        enabled = self.inc_cb.isChecked()
        self.inc_edit.setVisible(enabled)
        self.inc_hint.setVisible(enabled)

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

        # 断面类型切换时同步当前工况，确保工况标签实时刷新
        if self._loading_case:
            return
        if not hasattr(self, '_cases'):
            return
        if 0 <= self._current_case_idx < len(self._cases):
            self._cases[self._current_case_idx]['section_type'] = stype
        self._rebuild_case_tags()

    # ================================================================
    # 工况管理
    # ================================================================
    def _save_current_case(self):
        c = self._cases[self._current_case_idx]
        c['section_type'] = self.section_combo.currentText()
        c['Q'] = self.Q_edit.text()
        c['n'] = self.n_edit.text()
        c['slope_inv'] = self.slope_edit.text()
        c['v_min'] = self.vmin_edit.text()
        c['v_max'] = self.vmax_edit.text()
        c['inc_checked'] = self.inc_cb.isChecked()
        c['inc_pct'] = self.inc_edit.text()
        c['detail_checked'] = self.detail_cb.isChecked()
        # 圆形参数
        c['D'] = self.D_edit.text()
        # 圆拱直墙型参数
        c['theta_deg'] = self.theta_edit.text()
        c['B_hs'] = self.B_hs_edit.text()
        # 马蹄形参数
        c['r'] = self.r_edit.text()

    def _load_case(self, idx):
        if idx < 0 or idx >= len(self._cases):
            return
        self._loading_case = True
        c = self._cases[idx]
        self.section_combo.blockSignals(True)
        self.section_combo.setCurrentText(c.get('section_type', '圆形'))
        self.section_combo.blockSignals(False)
        self._on_section_type_changed(c.get('section_type', '圆形'))

        self.Q_edit.setText(c.get('Q', '10.0'))
        self.n_edit.setText(c.get('n', '0.014'))
        self.slope_edit.setText(c.get('slope_inv', '2000'))
        self.vmin_edit.setText(c.get('v_min', '0.1'))
        self.vmax_edit.setText(c.get('v_max', '100.0'))
        self.inc_cb.setChecked(c.get('inc_checked', True))
        self.inc_edit.setText(c.get('inc_pct', ''))
        self.detail_cb.setChecked(c.get('detail_checked', True))
        # 圆形参数
        self.D_edit.setText(c.get('D', ''))
        # 圆拱直墙型参数
        self.theta_edit.setText(c.get('theta_deg', ''))
        self.B_hs_edit.setText(c.get('B_hs', ''))
        # 马蹄形参数
        self.r_edit.setText(c.get('r', ''))
        self._loading_case = False

    def _switch_case(self, idx):
        if idx == self._current_case_idx:
            return
        self._save_current_case()
        self._current_case_idx = idx
        self._load_case(idx)
        self._rebuild_case_tags()
        self._update_calc_btn_text()

    def _add_case(self):
        if len(self._cases) >= MAX_CASES:
            InfoBar.warning(title="提示", content=f"最多支持 {MAX_CASES} 个工况",
                            parent=self._info_parent(), position=InfoBarPosition.TOP, duration=2000)
            return
        self._save_current_case()
        new_case = copy.deepcopy(self._cases[self._current_case_idx])
        new_case['Q'] = ''
        new_case['custom_label'] = None
        self._cases.append(new_case)
        self._current_case_idx = len(self._cases) - 1
        self._load_case(self._current_case_idx)
        self._rebuild_case_tags()
        self._update_calc_btn_text()
        self.Q_edit.setFocus()

    def _remove_current_case(self):
        if len(self._cases) <= 1:
            InfoBar.warning(title="提示", content="至少保留一个工况",
                            parent=self._info_parent(), position=InfoBarPosition.TOP, duration=2000)
            return
        idx = self._current_case_idx
        self._cases.pop(idx)
        if self._current_case_idx >= len(self._cases):
            self._current_case_idx = len(self._cases) - 1
        self._load_case(self._current_case_idx)
        self._rebuild_case_tags()
        self._update_calc_btn_text()
        InfoBar.success(title="已删除", content=f"工况{idx + 1} 已删除，当前 {len(self._cases)} 个工况",
                        parent=self._info_parent(), position=InfoBarPosition.TOP, duration=2000)

    def _rebuild_case_tags(self):
        if not hasattr(self, '_case_tag_flow'):
            return
        layout = self._case_tag_flow
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for i, case in enumerate(self._cases):
            label = case.get('custom_label') or self._auto_label(case, i)
            chip = _CaseTagChip(i, label, active=(i == self._current_case_idx))
            chip.switched.connect(self._switch_case)
            chip.renamed.connect(self._on_case_renamed)
            layout.addWidget(chip)
        n = len(self._cases)
        self._case_count_label.setText(f"{n} 个计算工况")
        self._case_tag_container.updateGeometry()
        self._case_tag_container.update()

    def _auto_label(self, case, idx):
        stype = case.get('section_type', '圆形')
        q_text = (case.get('Q', '') or '').strip() or '?'
        return f"{stype}-Q{_sub(idx + 1)}={q_text}"

    def _on_case_renamed(self, idx, new_label):
        if 0 <= idx < len(self._cases):
            self._cases[idx]['custom_label'] = new_label
            self._rebuild_case_tags()

    def _update_calc_btn_text(self):
        n = len(self._cases)
        if n <= 1:
            self._calc_btn.setText("计算")
        else:
            self._calc_btn.setText(f"计算全部 ({n}个工况)")

    def _on_q_text_changed(self, text):
        if self._loading_case:
            return
        if not hasattr(self, '_cases'):
            return
        if 0 <= self._current_case_idx < len(self._cases):
            self._cases[self._current_case_idx]['Q'] = text
        self._rebuild_case_tags()

    def _apply_to_all_cases(self):
        self._save_current_case()
        src = self._cases[self._current_case_idx]
        n_copied = len(self._cases) - 1
        if n_copied == 0:
            InfoBar.warning(title="提示", content="当前只有一个工况，无需复制",
                            parent=self._info_parent(), position=InfoBarPosition.TOP, duration=2000)
            return
        for i, c in enumerate(self._cases):
            if i == self._current_case_idx:
                continue
            if c.get('section_type') == src.get('section_type'):
                for k, v in src.items():
                    if k not in ('custom_label', 'Q'):
                        c[k] = v
            else:
                for k in ('n', 'slope_inv', 'v_min', 'v_max', 'inc_checked', 'inc_pct', 'detail_checked'):
                    c[k] = src.get(k, c.get(k))
        InfoBar.success(title="已复制", content=f"参数已复制到其余 {n_copied} 个工况",
                        parent=self._info_parent(), position=InfoBarPosition.TOP, duration=2000)

    def _copy_from_prev_case(self):
        if self._current_case_idx == 0:
            InfoBar.warning(title="提示", content="当前已是第一个工况",
                            parent=self._info_parent(), position=InfoBarPosition.TOP, duration=2000)
            return
        self._save_current_case()
        prev = self._cases[self._current_case_idx - 1]
        cur = self._cases[self._current_case_idx]
        if prev.get('section_type') == cur.get('section_type'):
            for k, v in prev.items():
                if k not in ('custom_label', 'Q'):
                    cur[k] = v
        else:
            for k in ('n', 'slope_inv', 'v_min', 'v_max', 'inc_checked', 'inc_pct', 'detail_checked'):
                cur[k] = prev.get(k, cur.get(k))
        self._load_case(self._current_case_idx)
        InfoBar.success(title="已复制", content=f"已从工况{self._current_case_idx}复制参数",
                        parent=self._info_parent(), position=InfoBarPosition.TOP, duration=2000)

    def _show_initial_help(self):
        h = HelpPageBuilder("隧洞水力计算", '请输入参数后点击“计算”按钮')
        h.section("支持断面类型")
        h.numbered_list([
            ("圆形断面", "最小直径 2.0m，最小净空高度 0.4m"),
            ("圆拱直墙型", "拱顶圆心角 90~180°，推荐高宽比 1.0~1.5"),
            ("马蹄形标准Ⅰ型", "t=3，底拱半径为3r，适用于地质条件较好的隧洞"),
            ("马蹄形标准Ⅱ型", "t=2，底拱半径为2r，适用于地质条件一般的隧洞"),
        ])
        h.section("计算模式总览")
        h.table(
            ["断面类型 / 可选参数填写方式", "程序行为"],
            [
                ["圆形 — 留空直径 D", "自动搜索满足净空约束的最小直径 D"],
                ["圆形 — 指定直径 D", "固定 D，反算水深并验算净空和流速"],
                ["圆拱直墙型 — 全部留空", "按默认圆心角 180° 自动搜索最优底宽 B"],
                ["圆拱直墙型 — 指定圆心角 θ", "约束拱形，自动搜索满足约束的最优 B"],
                ["圆拱直墙型 — 指定底宽 B", "固定 B，自动确定拱高并验算"],
                ["马蹄形 — 留空半径 r", "自动搜索满足净空约束的最小半径 r"],
                ["马蹄形 — 指定半径 r", "固定 r，反算水深并验算净空和流速"],
            ]
        )
        h.section("曼宁公式")
        h.text("计算基于曼宁公式：")
        h.formula("Q = (1/n) × A × R^(2/3) × i^(1/2)", "流量公式")
        h.section("净空约束条件")
        h.bullet_list([
            "最小净空面积 15%",
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
        return self

    # ================================================================
    # 计算
    # ================================================================
    def _parse_and_calc_case(self, case_dict):
        """解析单个工况并计算，返回 (input_params, result) 或抛出异常"""
        stype = case_dict.get('section_type', '圆形')
        Q = float(case_dict.get('Q') or 0)
        n = float(case_dict.get('n') or 0)
        slope_inv = float(case_dict.get('slope_inv') or 0)
        v_min = float(case_dict.get('v_min') or 0)
        v_max = float(case_dict.get('v_max') or 0)

        if Q <= 0:
            raise ValueError("设计流量 Q 必须大于0")
        if n <= 0:
            raise ValueError("糙率 n 必须大于0")
        if slope_inv <= 0:
            raise ValueError("水力坡降倒数必须大于0")
        if v_min >= v_max:
            raise ValueError("不淤流速必须小于不冲流速")

        use_increase = case_dict.get('inc_checked', True)
        inc_text = case_dict.get('inc_pct', '')
        manual_increase = float(inc_text) if inc_text.strip() else None
        if not use_increase:
            manual_increase = 0

        input_params = {
            'Q': Q, 'n': n, 'slope_inv': slope_inv,
            'v_min': v_min, 'v_max': v_max,
            'section_type': stype, 'manual_increase': manual_increase,
            'use_increase': use_increase,
            'detail_checked': case_dict.get('detail_checked', True),
        }

        if stype == "圆形":
            d_text = case_dict.get('D', '')
            manual_D = float(d_text) if d_text.strip() else None
            input_params['manual_D'] = manual_D
            result = quick_calculate_circular(
                Q=Q, n=n, slope_inv=slope_inv,
                v_min=v_min, v_max=v_max,
                manual_D=manual_D,
                manual_increase_percent=manual_increase
            )
        elif stype == "圆拱直墙型":
            theta_text = case_dict.get('theta_deg', '')
            theta_deg = float(theta_text) if theta_text.strip() else 180
            b_text = case_dict.get('B_hs', '')
            manual_B = float(b_text) if b_text.strip() else None
            input_params['theta_deg'] = theta_deg
            input_params['manual_B'] = manual_B
            result = quick_calculate_horseshoe(
                Q=Q, n=n, slope_inv=slope_inv,
                v_min=v_min, v_max=v_max,
                theta_deg=theta_deg,
                manual_B=manual_B,
                manual_increase_percent=manual_increase
            )
        else:
            sec_type_int = 1 if "Ⅰ" in stype else 2
            r_text = case_dict.get('r', '')
            manual_r = float(r_text) if r_text.strip() else None
            input_params['sec_type_int'] = sec_type_int
            input_params['manual_r'] = manual_r
            result = quick_calculate_horseshoe_std(
                Q=Q, n=n, slope_inv=slope_inv,
                v_min=v_min, v_max=v_max,
                section_type=sec_type_int,
                manual_r=manual_r,
                manual_increase_percent=manual_increase
            )
        return input_params, result

    def _calculate(self):
        self._save_current_case()
        self._all_results = []
        error_msgs = []

        for i, c in enumerate(self._cases):
            label = c.get('custom_label') or self._auto_label(c, i)
            try:
                inp, res = self._parse_and_calc_case(c)
                self._all_results.append({'label': label, 'input': inp, 'result': res, 'case': c})
                if not res.get('success'):
                    error_msgs.append(f"[{label}] {res.get('error_message', '未知错误')}")
            except Exception as e:
                self._all_results.append({'label': label, 'input': None, 'result': {'success': False, 'error_message': str(e)}, 'case': c})
                error_msgs.append(f"[{label}] {str(e)}")

        if self._all_results:
            last = self._all_results[-1]
            self.input_params = last.get('input') or {}
            self.current_result = last.get('result')

        if error_msgs:
            InfoBar.warning(
                title="部分工况计算失败",
                content="\n".join(error_msgs),
                parent=self._info_parent(),
                position=InfoBarPosition.TOP,
                duration=6000
            )
        if self._all_results:
            self._display_all_results()
            self._update_section_plot_all()
            self.data_changed.emit()

    def _show_error(self, title, msg):
        out = ["=" * 70, f"  {title}", "=" * 70, "", msg, "", "-" * 70, "请修正后重新计算。", "=" * 70]
        self.result_text.setHtml(make_plain_html("\n".join(out)))

    # ================================================================
    # 结果显示
    # ================================================================
    def _display_all_results(self):
        """显示所有工况的计算结果"""
        all_text_parts = []
        for case_idx, item in enumerate(self._all_results):
            inp = item.get('input')
            res = item.get('result')
            case = item.get('case') or {}
            stype = (inp or {}).get('section_type', case.get('section_type', '圆形'))
            q_raw = (inp or {}).get('Q', case.get('Q', ''))
            try:
                q_text = f"{float(q_raw):.3f}"
            except Exception:
                q_text = (str(q_raw).strip() or '-')
            q_part = f"{q_text} m³/s" if q_text != '-' else '-'
            header = f"【工况 {case_idx + 1}｜{stype}断面｜Q = {q_part}】"
            if not res:
                continue
            if not res.get('success'):
                all_text_parts.append(
                    f"{header}\n\n"
                    f"计算失败：{res.get('error_message', '未知错误')}\n"
                )
                continue
            self.input_params = inp
            stype = inp.get('section_type', '圆形')
            detail = inp.get('detail_checked', True)
            if stype == "圆形":
                type_label = "圆形"
            elif stype == "圆拱直墙型":
                type_label = "圆拱直墙型"
            else:
                type_label = res.get('section_type', '马蹄形')
            txt = self._build_result_text(res, type_label, detail, inp)
            all_text_parts.append(header + "\n\n" + txt)

        combined = "\n".join(all_text_parts)
        self._export_plain_text = combined
        load_formula_page(self.result_text, plain_text_to_formula_html(combined))

    def _build_result_text(self, result, type_label, detail, p):
        """构建单个工况的结果文本（从_show_result提取）"""
        Q, n = p['Q'], p['n']
        slope_inv = p['slope_inv']; i = 1.0 / slope_inv
        v_min, v_max = p['v_min'], p['v_max']
        inc_src = "(指定)" if p.get('manual_increase') else "(自动计算)"
        stype = p.get('section_type', '圆形')

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
        o.append(f"              隧洞水力计算结果 - {type_label}")
        o.append("=" * 70)
        o.append("")

        if not detail:
            o.append("【输入参数】")
            o.append(f"  断面类型: {stype}")
            o.append(f"  设计流量 Q = {Q:.3f} m³/s")
            o.append(f"  糙率 n = {n}")
            o.append(f"  水力坡降 = 1/{int(slope_inv)}")
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
            o.append(f"  净空高度 = {fb_hgt_d:.3f} m, 净空比例 = {fb_pct_d:.1f}%")
            o.append("")
            use_increase = p.get('use_increase', True)
            if use_increase:
                o.append("【加大流量工况】")
                o.append(f"  加大比例 = {inc_pct:.1f}% {inc_src}")
                o.append(f"  加大流量 = {Q_inc:.3f} m³/s")
                o.append(f"  加大水深 = {h_inc:.3f} m, 流速 = {V_inc:.3f} m/s")
                o.append(f"  净空高度 = {fb_hgt_inc:.3f} m, 净空比例 = {fb_pct_inc:.1f}%")
                o.append("")
            vel_ok = v_min <= V_d <= v_max
            fb_ok = fb_pct_inc >= 15 and fb_hgt_inc >= 0.4
            o.append(f"【验证】 流速: {'✓' if vel_ok else '✗'}  净空: {'✓' if fb_ok else '需注意'}")
        else:
            # 详细输出（简化版，保留关键信息）
            o.append("【一、输入参数】")
            o.append(f"  断面类型: {stype}")
            o.append(f"  设计流量 Q = {Q:.3f} m³/s")
            o.append(f"  糙率 n = {n}, 水力坡降 = 1/{int(slope_inv)}")
            o.append(f"  流速范围: {v_min} ~ {v_max} m/s")
            o.append("")
            o.append("【二、断面尺寸】")
            if stype == "圆形":
                D = result['D']
                o.append(f"  直径 D = {D:.2f} m")
                o.append(f"  断面总面积 A总 = π×D²/4 = {A_total:.3f} m²")
            elif stype == "圆拱直墙型":
                B = result['B']; H_total = result['H_total']
                o.append(f"  宽度 B = {B:.2f} m, 高度 H = {H_total:.2f} m")
                o.append(f"  拱顶圆心角 θ = {result['theta_deg']:.1f}°")
                o.append(f"  断面总面积 A总 = {A_total:.3f} m²")
            else:
                r_val = result['r']
                o.append(f"  半径 r = {r_val:.2f} m, 等效直径 2r = {result['D_equiv']:.2f} m")
                o.append(f"  断面总面积 A总 = {A_total:.3f} m²")
            o.append("")
            o.append("【三、设计流量工况】")
            o.append(f"  水深 h = {h_d:.3f} m")
            o.append(f"  过水面积 A = {A_d:.3f} m², 湿周 χ = {P_d:.3f} m")
            o.append(f"  水力半径 R = {R_hyd_d:.3f} m")
            o.append(f"  流速 V = {V_d:.3f} m/s")
            o.append(f"  净空面积比 = {fb_pct_d:.1f}%, 净空高度 = {fb_hgt_d:.3f} m")
            o.append("")
            use_increase = p.get('use_increase', True)
            if use_increase:
                o.append("【四、加大流量工况】")
                o.append(f"  加大比例 = {inc_pct:.1f}% {inc_src}")
                o.append(f"  加大流量 Q加大 = {Q_inc:.3f} m³/s")
                o.append(f"  水深 h加大 = {h_inc:.3f} m")
                o.append(f"  过水面积 A加大 = {A_inc:.3f} m², 湿周 χ加大 = {P_inc:.3f} m")
                o.append(f"  水力半径 R加大 = {R_hyd_inc:.3f} m")
                o.append(f"  流速 V加大 = {V_inc:.3f} m/s")
                o.append(f"  净空面积比 = {fb_pct_inc:.1f}%, 净空高度 = {fb_hgt_inc:.3f} m")
                o.append("")
            o.append("【五、设计验证】")
            vel_ok = v_min <= V_d <= v_max
            fb_pct_ok = fb_pct_inc >= 15
            fb_hgt_ok = fb_hgt_inc >= 0.4
            o.append(f"  流速验证: {v_min} ≤ {V_d:.3f} ≤ {v_max} → {'通过 ✓' if vel_ok else '未通过 ✗'}")
            o.append(f"  净空面积验证: {fb_pct_inc:.1f}% ≥ 15% → {'通过 ✓' if fb_pct_ok else '需注意 ✗'}")
            o.append(f"  净空高度验证: {fb_hgt_inc:.3f}m ≥ 0.4m → {'通过 ✓' if fb_hgt_ok else '需注意 ✗'}")

        return "\n".join(o)

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
        inc_src = "(指定)" if p.get('manual_increase') else "(自动计算)"
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
            o.append("")
            o.append(f"  1. 断面类型:")
            o.append(f"     {stype}")
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
            o.append(f"     = {v_min} m/s")
            o.append("")
            o.append(f"  6. 不冲流速:")
            o.append(f"     = {v_max} m/s")
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

            use_increase = p.get('use_increase', True)
            if use_increase:
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
            o.append(f"  流速验证: {'✓ 通过' if vel_ok else '✗ 未通过'}")
            if use_increase:
                fb_ok = fb_pct_inc >= 15 and fb_hgt_inc >= 0.4
                o.append(f"  净空验证: {'✓ 通过' if fb_ok else '需注意'}")
            else:
                fb_ok = fb_pct_d >= 15 and fb_hgt_d >= 0.4
                o.append(f"  净空验证(设计): {'✓ 通过' if fb_ok else '需注意'}")
            o.append("")
        else:
            # ============ 详细输出（对齐原版格式） ============
            o.append("【一、输入参数】")
            o.append("")
            o.append(f"  1. 断面类型:")
            o.append(f"     {stype}")
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
            o.append(f"     = {v_min} m/s")
            o.append("")
            o.append(f"  6. 不冲流速:")
            o.append(f"     = {v_max} m/s")
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
                o.append(f"  1. 断面类型: {st_name}")
                o.append(f"  2. 设计半径: r = {r_val:.2f} m")
                o.append(f"  3. 等效直径: 2r = {D_equiv:.2f} m")
                o.append(f"  4. 断面总面积: A总 = {A_total:.3f} m²")
                o.append("")

            # 设计流量工况
            o.append("【三、设计流量工况计算】")
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
            use_increase = p.get('use_increase', True)
            if use_increase:
              o.append("【四、加大流量工况计算】")
              o.append("")
              o.append(f"  1. 加大流量计算:")
              o.append(f"      流量加大比例 = {inc_pct:.1f}% {inc_src}")
            o.append(f"      Q加大 = Q × (1 + {inc_pct/100:.2f})")
            o.append(f"           = {Q:.3f} × {1+inc_pct/100:.2f}")
            o.append(f"           = {Q_inc:.3f} m³/s")
            o.append("")

            o.append("  2. 加大水深计算:")
            o.append(f"      根据加大流量 Q加大 = {Q_inc:.3f} m³/s，利用曼宁公式反算水深:")
            o.append(f"      h加大 = {h_inc:.3f} m")
            o.append("")

            # 加大工况过水面积和湿周
            if stype == "圆形":
                D = result['D']; R_radius = D / 2
                if h_inc > 0 and D > 0 and h_inc < D:
                    theta_inc = 2 * math.acos((R_radius - h_inc) / R_radius)
                    o.append("  3. 圆心角计算:")
                    o.append(f"      θ加大 = 2 × arccos((R - h加大) / R)")
                    o.append(f"           = 2 × arccos(({R_radius:.3f} - {h_inc:.3f}) / {R_radius:.3f})")
                    o.append(f"           = 2 × arccos({(R_radius - h_inc)/R_radius:.4f})")
                    o.append(f"           = {math.degrees(theta_inc):.2f}° ({theta_inc:.4f} rad)")
                    o.append("")
                    o.append("  4. 过水面积计算:")
                    o.append(f"      A加大 = (D²/8) × (θ加大 - sinθ加大)")
                    o.append(f"           = ({D:.3f}²/8) × ({theta_inc:.4f} - sin{theta_inc:.4f})")
                    o.append(f"           = {D**2/8:.4f} × {theta_inc - math.sin(theta_inc):.4f}")
                    o.append(f"           = {A_inc:.3f} m²")
                    o.append("")
                    o.append("  5. 湿周计算:")
                    o.append(f"      χ加大 = (D/2) × θ加大")
                    o.append(f"           = ({D:.3f}/2) × {theta_inc:.4f}")
                    o.append(f"           = {R_radius:.3f} × {theta_inc:.4f}")
                    o.append(f"           = {P_inc:.3f} m")
                    o.append("")
                else:
                    o.append(f"  3. 过水面积: A加大 = {A_inc:.3f} m²")
                    o.append("")
                    o.append(f"  4. 湿周: χ加大 = {P_inc:.3f} m")
                    o.append("")
            elif stype == "圆拱直墙型":
                B_hs = result['B']; H_hs = result['H_total']
                theta_deg_hs = result['theta_deg']
                theta_rad_hs = math.radians(theta_deg_hs)
                if abs(math.sin(theta_rad_hs / 2)) > 1e-9 and B_hs > 0:
                    R_arch = (B_hs / 2) / math.sin(theta_rad_hs / 2)
                    H_arch = R_arch * (1 - math.cos(theta_rad_hs / 2))
                    H_straight = max(0, H_hs - H_arch)
                    o.append("  3. 过水面积计算 (圆拱直墙型):")
                    if h_inc <= H_straight:
                        o.append(f"      水深 h加大 = {h_inc:.3f} m ≤ 直墙高度 {H_straight:.3f} m")
                        o.append(f"      A加大 = B × h加大 = {B_hs:.2f} × {h_inc:.3f} = {A_inc:.3f} m²")
                    else:
                        o.append(f"      水深 h加大 = {h_inc:.3f} m > 直墙高度 {H_straight:.3f} m")
                        o.append(f"      A加大 = 直墙部分 + 拱部过水面积")
                        o.append(f"           = {A_inc:.3f} m²")
                    o.append("")
                    o.append("  4. 湿周计算 (圆拱直墙型):")
                    if h_inc <= H_straight:
                        o.append(f"      χ加大 = B + 2×h加大 = {B_hs:.2f} + 2×{h_inc:.3f}")
                        o.append(f"           = {P_inc:.3f} m")
                    else:
                        o.append(f"      χ加大 = 底宽 + 直墙段 + 拱部湿周")
                        o.append(f"           = {P_inc:.3f} m")
                    o.append("")
                else:
                    o.append(f"  3. 过水面积: A加大 = {A_inc:.3f} m²")
                    o.append("")
                    o.append(f"  4. 湿周: χ加大 = {P_inc:.3f} m")
                    o.append("")
            else:
                r_val = result['r']
                horseshoe_type_id = 1 if 'Ⅰ' in type_label else 2
                t_val = 3.0 if horseshoe_type_id == 1 else 2.0
                R_arch_hs = t_val * r_val
                e_val = R_arch_hs * (1 - math.cos(0.294515 if horseshoe_type_id == 1 else 0.424031))
                st_name = '标准Ⅰ型' if horseshoe_type_id == 1 else '标准Ⅱ型'
                o.append(f"  3. 过水面积计算 ({st_name}):")
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
                o.append(f"  4. 湿周计算 ({st_name}):")
                o.append(f"      χ加大 = {P_inc:.3f} m")
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

            Q_chk_inc = V_inc * A_inc
            o.append("  7. 流量校核:")
            o.append(f"      Q计算 = A加大 × V加大")
            o.append(f"           = {A_inc:.3f} × {V_inc:.3f}")
            o.append(f"           = {Q_chk_inc:.3f} m³/s")
            if Q_inc > 0:
                o.append(f"      误差 = {abs(Q_chk_inc - Q_inc) / Q_inc * 100:.2f}%")
            o.append("")

            o.append("  8. 净空面积计算:")
            o.append(f"      PA加大 = (A总 - A加大) / A总 × 100%")
            o.append(f"           = ({A_total:.3f} - {A_inc:.3f}) / {A_total:.3f} × 100%")
            o.append(f"           = {fb_pct_inc:.1f}%")
            o.append("")
            o.append("  9. 净空高度计算:")
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
            if use_increase:
                fb_pct_ok = fb_pct_inc >= 15
                fb_hgt_ok = fb_hgt_inc >= 0.4
            else:
                fb_pct_ok = fb_pct_d >= 15
                fb_hgt_ok = fb_hgt_d >= 0.4

            o.append(f"  1. 流速验证:")
            o.append(f"      范围要求: {v_min} ≤ V ≤ {v_max} m/s")
            o.append(f"      设计流速: V = {V_d:.3f} m/s")
            o.append(f"      结果: {'通过 ✓' if vel_ok else '未通过 ✗'}")
            o.append("")
            o.append(f"  2. 净空面积验证:")
            o.append(f"      规范要求: PA ≥ 15%")
            o.append(f"      计算结果: PA = {fb_pct_inc:.1f}%")
            o.append(f"      结果: {'通过 ✓' if fb_pct_ok else '需注意 ✗'}")
            o.append("")
            o.append(f"  3. 净空高度验证:")
            o.append(f"      规范要求: Fb ≥ 0.4 m")
            o.append(f"      计算结果: Fb = {fb_hgt_inc:.3f} m")
            o.append(f"      结果: {'通过 ✓' if fb_hgt_ok else '需注意 ✗'}")
            o.append("")

        o.append("=" * 70)
        vel_ok = v_min <= V_d <= v_max
        fb_pct_ok = fb_pct_inc >= 15
        fb_hgt_ok = fb_hgt_inc >= 0.4
        all_checks_ok = vel_ok and fb_pct_ok and fb_hgt_ok
        o.append(f"  综合验证结果: {'全部通过 ✓' if all_checks_ok else '未通过 ✗'}")
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

    def _update_section_plot_all(self):
        """绘制所有工况的断面图（网格布局）"""
        self.section_fig.clear()
        valid = [r for r in self._all_results if r.get('result', {}).get('success')]
        if not valid:
            self.section_canvas.draw()
            return
        n = len(valid)
        cols = min(n, 3)
        rows = (n + cols - 1) // cols
        axes = self.section_fig.subplots(rows, cols, squeeze=False)
        for idx, item in enumerate(valid):
            r_idx, c_idx = divmod(idx, cols)
            ax = axes[r_idx][c_idx]
            res = item['result']
            inp = item['input']
            label = item['label']
            stype = inp.get('section_type', '圆形')
            Q = inp['Q']
            h_d = res['h_design']
            V_d = res['V_design']
            if stype == "圆形":
                D = res['D']
                self._draw_circular(ax, D, h_d, V_d, Q, label)
            elif stype == "圆拱直墙型":
                B = res['B']; H = res['H_total']; theta = math.radians(res['theta_deg'])
                self._draw_horseshoe(ax, B, H, theta, h_d, V_d, Q, label)
            else:
                r_val = res['r']
                sec_int = inp.get('sec_type_int', 1)
                self._draw_horseshoe_std(ax, sec_int, r_val, h_d, V_d, Q, label)
        # 隐藏多余子图
        for idx in range(n, rows * cols):
            r_idx, c_idx = divmod(idx, cols)
            axes[r_idx][c_idx].axis('off')
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
        self._cases = [self._default_case()]
        self._current_case_idx = 0
        self._all_results = []
        self._load_case(0)
        self._rebuild_case_tags()
        self._update_calc_btn_text()

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
        from app_渠系计算前端.styles import fluent_select
        scale_str, ok = fluent_select(self, '选择比例尺', '输出比例尺 (图纸单位: mm):', scales, 2)
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
        if not self._all_results or not any(r.get('result', {}).get('success') for r in self._all_results):
            InfoBar.warning("提示", "请先计算。", parent=self._info_parent(), duration=3000, position=InfoBarPosition.TOP); return
        stype = self.input_params.get('section_type', '圆形')
        channel_name = getattr(self, '_channel_name', '')
        meta = load_meta()
        auto_purpose = build_calc_purpose('tunnel', project=meta.project_name, name=channel_name, section_type=stype)
        n_cases = len(self._cases)
        cur_case = self._cases[self._current_case_idx]
        cur_label = cur_case.get('custom_label') or self._auto_label(cur_case, self._current_case_idx)
        dlg = ExportConfirmDialog('tunnel', '隧洞水力计算书', auto_purpose, parent=self._info_parent(), n_cases=n_cases, current_case_label=cur_label)
        from PySide6.QtWidgets import QDialog
        if dlg.exec() != QDialog.Accepted:
            return
        self._word_export_meta = dlg.get_meta()
        self._word_export_purpose = dlg.get_calc_purpose()
        self._word_export_refs = dlg.get_references()
        self._word_export_scope = dlg.get_export_scope()
        filepath, _ = QFileDialog.getSaveFileName(self, "保存Word报告", "", "Word文档 (*.docx);;所有文件 (*.*)")
        if not filepath: return
        try:
            self._build_word_report(filepath)
            InfoBar.success("导出成功", f"Word报告已保存到: {filepath}", parent=self._info_parent(), duration=4000, position=InfoBarPosition.TOP)
            ask_open_file(filepath, self._info_parent())
        except PermissionError:
            InfoBar.error("文件被占用", "请关闭同名Word文档后重试。", parent=self._info_parent(), duration=8000, position=InfoBarPosition.TOP)
        except Exception as e:
            InfoBar.error("导出失败", str(e), parent=self._info_parent(), duration=5000, position=InfoBarPosition.TOP)

    def _build_word_report(self, filepath):
        """构建Word报告文档（工程产品运行卡格式）"""
        scope = getattr(self, '_word_export_scope', 'all')
        meta = getattr(self, '_word_export_meta', load_meta())
        purpose = getattr(self, '_word_export_purpose', '')
        refs = getattr(self, '_word_export_refs', REFERENCES_BASE.get('tunnel', []))

        # 确定导出的工况
        if scope == 'current':
            export_results = [r for r in self._all_results if r.get('result', {}).get('success')]
            if self._current_case_idx < len(export_results):
                export_results = [export_results[self._current_case_idx]]
        else:
            export_results = [r for r in self._all_results if r.get('result', {}).get('success')]

        if not export_results:
            return

        first_inp = export_results[0].get('input', {})
        stype = first_inp.get('section_type', '圆形')
        method = export_results[0].get('result', {}).get('design_method', '')

        doc = create_engineering_report_doc(
            meta=meta,
            calc_title='隧洞水力计算书',
            calc_content_desc=f'隧洞水力断面设计计算（{stype}断面）',
            calc_purpose=purpose,
            references=refs,
            calc_program_text=f'渠系建筑物水力计算系统 V1.0\n隧洞水力计算（{stype}断面 · {method}）',
        )
        doc.add_page_break()

        # 5. 基础公式
        doc_add_eng_h(doc, '5、基础公式')
        doc_add_formula(doc, r'Q = \frac{1}{n} \cdot A \cdot R^{2/3} \cdot i^{1/2}', '曼宁公式：')
        doc_add_formula(doc, r'R = \frac{A}{P}', '水力半径：')

        # 6. 计算过程
        doc_add_eng_h(doc, '6、计算过程')
        for item in export_results:
            label = item['label']
            inp = item['input']
            res = item['result']
            s = inp.get('section_type', '圆形')
            detail = inp.get('detail_checked', True)
            if s == "圆形":
                type_label = "圆形"
            elif s == "圆拱直墙型":
                type_label = "圆拱直墙型"
            else:
                type_label = res.get('section_type', '马蹄形')
            txt = self._build_result_text(res, type_label, detail, inp)
            if len(export_results) > 1:
                doc_add_eng_body(doc, f"【工况: {label}】")
            doc_render_calc_text_eng(doc, txt, skip_title_keyword='隧洞水力计算结果')

        # 7. 断面图
        try:
            import tempfile
            tmp = os.path.join(tempfile.gettempdir(), '_tunnel_section.png')
            self.section_fig.savefig(tmp, dpi=150, bbox_inches='tight')
            doc_add_eng_h(doc, '7、断面图')
            doc_add_figure(doc, tmp, width_cm=14)
            os.remove(tmp)
        except Exception:
            pass
        doc.save(filepath)

    # ================================================================
    # 项目保存/加载
    # ================================================================
    def to_project_dict(self):
        """序列化当前状态供项目保存"""
        self._save_current_case()
        return {
            'cases': copy.deepcopy(self._cases),
            'current_case_idx': self._current_case_idx,
            'all_results': copy.deepcopy(self._all_results),
            'current_result': copy.deepcopy(self.current_result),
            'input_params': copy.deepcopy(getattr(self, 'input_params', None)),
            'notebook_idx': self.notebook.currentIndex() if hasattr(self, 'notebook') else 0,
        }

    def from_project_dict(self, data):
        """从项目数据恢复状态"""
        cases = data.get('cases', [])
        if not cases:
            cases = [self._default_case()]
        self._cases = cases
        self._current_case_idx = data.get('current_case_idx', 0)
        if self._current_case_idx >= len(self._cases):
            self._current_case_idx = 0
        self._load_case(self._current_case_idx)
        self._rebuild_case_tags()
        self._update_calc_btn_text()
        self._all_results = data.get('all_results', []) or []
        self.current_result = data.get('current_result')
        self.input_params = data.get('input_params') or {}
        if self._all_results:
            try:
                self._display_all_results()
                self._update_section_plot_all()
            except Exception:
                self._all_results = []
                self.current_result = None
                self._show_initial_help()
        else:
            self.current_result = None
            self._show_initial_help()
        if hasattr(self, 'notebook'):
            idx = data.get('notebook_idx')
            if isinstance(idx, int):
                idx = max(0, min(idx, self.notebook.count() - 1))
                self.notebook.setCurrentIndex(idx)
