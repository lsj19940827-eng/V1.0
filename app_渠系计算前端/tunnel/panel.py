# -*- coding: utf-8 -*-
"""
隧洞水力计算面板 —— QWidget 版本

支持：圆形 / 平底圆形 / 圆拱直墙型 / 马蹄形标准Ⅰ型 / 马蹄形标准Ⅱ型
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
    QSplitter, QFrame, QTabWidget, QTextEdit, QFileDialog, QScrollArea, QDialog,
    QPushButton, QApplication, QRadioButton, QButtonGroup,
    QTableWidget, QTableWidgetItem,
)
from PySide6.QtCore import Qt, Signal, QEvent
from app_渠系计算前端.webview_compat import create_web_view, scroll_view_to_anchor

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
    quick_calculate_flat_bottom_circular,
    quick_calculate_horseshoe,
    quick_calculate_horseshoe_std,
    PI, MIN_FREEBOARD_PCT_TUNNEL, MIN_FREEBOARD_HGT_TUNNEL,
)

from app_渠系计算前端.styles import P, S, W, E, BG, CARD, BD, T1, T2, INPUT_LABEL_STYLE, INPUT_SECTION_STYLE, INPUT_HINT_STYLE
from app_渠系计算前端.export_utils import (
    WORD_EXPORT_AVAILABLE, add_formula_to_doc, try_convert_formula_line, ask_open_file,
    create_styled_doc, doc_add_h1, doc_add_formula, doc_render_calc_text, doc_add_figure,
    doc_add_result_table,
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
    CaseTagNavigator as _CaseTagNavigator,
    CaseWorkbenchStrip as _CaseWorkbenchStrip,
)
from app_渠系计算前端.dxf_multi_export import (
    DxfExportCaseEntry,
    choose_scale_denom,
    export_combined_case_dxf,
    format_empty_export_warning,
    format_export_result_message,
    partition_valid_case_entries,
    select_case_entries,
    show_multi_case_dxf_dialog,
)
from app_渠系计算前端.tunnel.dxf_export import (
    export_tunnel_dxf,
    draw_tunnel_dxf_on_msp,
    draw_tunnel_comparison_table,
)
from app_渠系计算前端.tunnel.comparison import (
    TUNNEL_COMPARISON_COLUMNS,
    build_tunnel_comparison_rows,
    comparison_header_text,
    format_comparison_cell,
)
from app_渠系计算前端.tunnel.clearance_sizing_dialog import HorseshoeClearanceSizingDialog
from app_渠系计算前端.formula_renderer import (
    plain_text_to_formula_html, plain_text_to_formula_body, wrap_with_katex,
    load_formula_page, make_plain_html,
    HelpPageBuilder
)
from app_渠系计算前端.increase_input_helper import (
    INCREASE_MODE_PERCENT,
    INCREASE_MODE_Q_INCREASED,
    build_increase_hint_text,
    build_increase_summary_lines,
    calculate_q_increased,
    get_auto_increase_percent,
    normalize_increase_mode,
    resolve_increase_input,
)
from app_渠系计算前端.plot_title_utils import (
    apply_flow_velocity_title,
    format_flow_velocity_metrics,
)
from app_渠系计算前端.tunnel.geometry import (
    arch_half_width as _arch_half_width,
    build_arch_geometry as _build_arch_geometry,
    build_flat_bottom_circle_geometry as _build_flat_bottom_circle_geometry,
    build_standard_horseshoe_geometry as _build_standard_horseshoe_geometry,
    flat_bottom_circle_half_width as _flat_bottom_circle_half_width,
    flat_bottom_circle_surface_width as _flat_bottom_circle_surface_width,
    sample_arc as _sample_arc,
    standard_horseshoe_half_width as _standard_horseshoe_half_width,
)
from app_渠系计算前端.result_navigation import (
    CaseResultNavigationBar,
    build_result_nav_bar,
    build_result_navigation_head,
    make_case_result_anchor,
    sync_case_result_nav_bar,
    wrap_case_result_block,
)
from app_渠系计算前端.result_summary import (
    build_result_summary_word_items,
    prepend_result_summary_to_body,
    prepend_result_summary_to_html,
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
        self._panel_key = "tunnel"
        self._results_dirty = False
        self._has_rendered_results = False
        self._init_ui()
        self._setup_result_dirty_tracking()
        self._rebuild_case_tags()
        # 首次进入时按当前工况同步界面可见性，避免两套加大流量输入同时显示。
        self._load_case(self._current_case_idx)

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
            'inc_checked': True, 'inc_pct': '', 'inc_mode': INCREASE_MODE_PERCENT, 'inc_q_text': '',
            'detail_checked': True,
            # 圆形参数
            'D': '',
            # 平底圆形参数
            'flat_bottom_D': '', 'flat_bottom_B': '',
            # 圆拱直墙型参数
            'theta_deg': '', 'B_hs': '', 'H_straight_hs': '',
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
        self._input_title = QLabel("输入参数")
        self._input_title.setStyleSheet("font-size:18px;font-weight:700;color:#0E5DB8;padding:0 2px 2px 2px;")
        lay.addWidget(self._input_title)
        self._case_strip = _CaseWorkbenchStrip(parent)
        self._case_strip.add_requested.connect(self._add_case)
        self._case_strip.case_switched.connect(self._switch_case)
        self._case_strip.case_renamed.connect(self._on_case_renamed)
        self._case_strip.apply_to_all_requested.connect(self._apply_to_all_cases)
        self._case_strip.copy_from_prev_requested.connect(self._copy_from_prev_case)
        self._case_strip.remove_current_requested.connect(self._remove_current_case)
        self._case_nav = self._case_strip.navigator()
        lay.addWidget(self._case_strip)
        grp = QGroupBox("输入参数")
        self._input_group = grp
        grp.setTitle("")
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
        self._case_tag_container.hide()
        self._add_case_btn.hide()
        self._case_count_label.hide()
        self._case_nav = _CaseTagNavigator(parent=grp)
        self._case_nav.add_requested.connect(self._add_case)
        self._case_nav.case_switched.connect(self._switch_case)
        self._case_nav.case_renamed.connect(self._on_case_renamed)
        fl.addWidget(self._case_nav)

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
        self._case_tag_container.hide()
        self._add_case_btn.hide()
        self._case_count_label.hide()
        self._case_nav.hide()
        _copy_all_btn.hide()
        _copy_prev_btn.hide()
        self._del_case_btn.hide()
        self._legacy_case_nav = self._case_nav
        self._case_nav = self._case_strip.navigator()

        fl.addWidget(self._sep())

        # 断面类型
        r = QHBoxLayout(); r.addWidget(QLabel("断面类型:"))
        self.section_combo = ComboBox()
        self.section_combo.addItems(["圆形", "平底圆形", "圆拱直墙型", "马蹄形标准Ⅰ型", "马蹄形标准Ⅱ型"])
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
        self.inc_mode_row = QWidget()
        self.inc_mode_row_lay = QHBoxLayout(self.inc_mode_row)
        self.inc_mode_row_lay.setContentsMargins(0, 0, 0, 0)
        self.inc_mode_row_lay.setSpacing(10)
        self.inc_mode_row_lay.addWidget(self._hint("输入方式:"))
        self.inc_mode_group = QButtonGroup(self)
        self.inc_mode_percent_rb = QRadioButton("按比例")
        self.inc_mode_q_rb = QRadioButton("按Q加大")
        self.inc_mode_group.addButton(self.inc_mode_percent_rb)
        self.inc_mode_group.addButton(self.inc_mode_q_rb)
        self.inc_mode_percent_rb.setChecked(True)
        self.inc_mode_percent_rb.toggled.connect(self._on_inc_mode_changed)
        self.inc_mode_q_rb.toggled.connect(self._on_inc_mode_changed)
        self.inc_mode_row_lay.addWidget(self.inc_mode_percent_rb)
        self.inc_mode_row_lay.addWidget(self.inc_mode_q_rb)
        self.inc_mode_row_lay.addStretch()
        fl.addWidget(self.inc_mode_row)
        self.inc_lbl, self.inc_edit = self._field2(fl, "流量加大比例 (%):", "")
        self.inc_q_lbl, self.inc_q_edit = self._field2(fl, "加大流量 Q加大 (m³/s):", "")
        self.inc_edit.textChanged.connect(self._refresh_increase_hint)
        self.inc_q_edit.textChanged.connect(self._refresh_increase_hint)
        self.inc_hint = QLabel("(留空则自动计算)")
        self.inc_hint.setStyleSheet(INPUT_HINT_STYLE)
        self.inc_derived_hint = self.inc_hint
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

        # 平底圆形参数
        self.flat_bottom_grp = QWidget()
        flat_bottom_lay = QVBoxLayout(self.flat_bottom_grp); flat_bottom_lay.setContentsMargins(0,0,0,0); flat_bottom_lay.setSpacing(5)
        flat_bottom_lay.addWidget(self._slbl("【平底圆形参数】"))
        self.flat_bottom_D_lbl, self.flat_bottom_D_edit = self._field2(flat_bottom_lay, "直径 D (m):", "")
        self.flat_bottom_B_lbl, self.flat_bottom_B_edit = self._field2(flat_bottom_lay, "平底宽 B (m):", "")
        flat_bottom_lay.addWidget(self._hint("(平底圆形需同时填写 D 和 B)"))
        fl.addWidget(self.flat_bottom_grp)
        self.flat_bottom_grp.hide()

        # 圆拱直墙参数
        self.hs_grp = QWidget()
        hs_lay = QVBoxLayout(self.hs_grp); hs_lay.setContentsMargins(0,0,0,0); hs_lay.setSpacing(5)
        hs_lay.addWidget(self._slbl("【圆拱直墙型参数】"))
        self.theta_lbl, self.theta_edit = self._field2(hs_lay, "拱顶圆心角 (度):", "")
        hs_lay.addWidget(self._hint("(留空则采用180°)"))
        self.B_hs_lbl, self.B_hs_edit = self._field2(hs_lay, "指定底宽 B (m):", "")
        hs_lay.addWidget(self._hint("(指定底宽留空则自动计算)"))
        self.H_straight_hs_lbl, self.H_straight_hs_edit = self._field2(hs_lay, "直墙高度 H直 (m):", "")
        hs_lay.addWidget(self._hint("(留空则由程序自动计算；填写时需同时填写底宽 B)"))
        self.clearance_sizing_btn = PrimaryPushButton("按加大流量净空比例反推断面尺寸")
        self.clearance_sizing_btn.setCursor(Qt.PointingHandCursor)
        self.clearance_sizing_btn.setMinimumHeight(36)
        self.clearance_sizing_btn.setToolTip("根据加大流量、目标净空比例和高宽比反推断面尺寸")
        self.clearance_sizing_btn.clicked.connect(self._open_clearance_sizing_dialog)
        hs_lay.addWidget(self.clearance_sizing_btn)
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
        is_percent_mode = self._current_increase_mode() == INCREASE_MODE_PERCENT
        self.inc_mode_row.setVisible(enabled)
        self.inc_lbl.setVisible(enabled and is_percent_mode)
        self.inc_edit.setVisible(enabled and is_percent_mode)
        self.inc_q_lbl.setVisible(enabled and not is_percent_mode)
        self.inc_q_edit.setVisible(enabled and not is_percent_mode)
        self.inc_hint.setVisible(enabled)
        self._refresh_increase_hint()

    def _current_increase_mode(self):
        return INCREASE_MODE_Q_INCREASED if self.inc_mode_q_rb.isChecked() else INCREASE_MODE_PERCENT

    def _set_increase_mode(self, mode):
        normalized = normalize_increase_mode(mode)
        if normalized == INCREASE_MODE_Q_INCREASED:
            self.inc_mode_q_rb.setChecked(True)
        else:
            self.inc_mode_percent_rb.setChecked(True)
        self._on_inc_toggle(None)

    def _on_inc_mode_changed(self, _checked):
        self._on_inc_toggle(None)

    def _refresh_increase_hint(self):
        self.inc_hint.setText(build_increase_hint_text(
            use_increase=self.inc_cb.isChecked(),
            mode=self._current_increase_mode(),
            design_q_text=self.Q_edit.text(),
            percent_text=self.inc_edit.text(),
            q_increased_text=self.inc_q_edit.text(),
        ))

    # ----------------------------------------------------------------
    def _build_output(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(0, 0, 0, 0)
        self.notebook = QTabWidget()
        lay.addWidget(self.notebook)

        t1 = QWidget(); t1l = QVBoxLayout(t1); t1l.setContentsMargins(5,5,5,5)
        grp = QGroupBox("计算结果详情"); gl = QVBoxLayout(grp)
        self._result_case_nav = CaseResultNavigationBar(grp)
        self._result_case_nav.case_requested.connect(self._jump_to_case_result)
        gl.addWidget(self._result_case_nav)
        self.result_text = create_web_view()
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

        t3 = QWidget(); t3l = QVBoxLayout(t3); t3l.setContentsMargins(5,5,5,5)
        cmp_grp = QGroupBox("工况对比"); cmp_lay = QVBoxLayout(cmp_grp)
        self.comparison_hint = QLabel("请先完成计算，系统会在这里汇总各工况的关键水力结果和洞身尺寸。")
        self.comparison_hint.setWordWrap(True)
        self.comparison_hint.setStyleSheet("color:#666; font-size:12px;")
        cmp_lay.addWidget(self.comparison_hint)
        self.comparison_table = QTableWidget(0, len(TUNNEL_COMPARISON_COLUMNS))
        self.comparison_table.setHorizontalHeaderLabels(
            [comparison_header_text(col) for col in TUNNEL_COMPARISON_COLUMNS]
        )
        self.comparison_table.verticalHeader().setVisible(False)
        self.comparison_table.setAlternatingRowColors(True)
        self.comparison_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.comparison_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.comparison_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.comparison_table.horizontalHeader().setStretchLastSection(True)
        self.comparison_table.installEventFilter(self)
        cmp_lay.addWidget(self.comparison_table)
        t3l.addWidget(cmp_grp)
        self.notebook.addTab(t3, "工况对比")

        self._show_initial_help()

    # ----------------------------------------------------------------
    def _on_section_type_changed(self, stype):
        self.circ_grp.hide(); self.flat_bottom_grp.hide(); self.hs_grp.hide(); self.shoe_grp.hide()
        if stype == "圆形":
            self.circ_grp.show()
        elif stype == "平底圆形":
            self.flat_bottom_grp.show()
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
        c['inc_mode'] = self._current_increase_mode()
        c['inc_q_text'] = self.inc_q_edit.text()
        c['detail_checked'] = self.detail_cb.isChecked()
        # 圆形参数
        c['D'] = self.D_edit.text()
        # 平底圆形参数
        c['flat_bottom_D'] = self.flat_bottom_D_edit.text()
        c['flat_bottom_B'] = self.flat_bottom_B_edit.text()
        # 圆拱直墙型参数
        c['theta_deg'] = self.theta_edit.text()
        c['B_hs'] = self.B_hs_edit.text()
        c['H_straight_hs'] = self.H_straight_hs_edit.text()
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
        self.inc_q_edit.setText(c.get('inc_q_text', ''))
        self._set_increase_mode(c.get('inc_mode', INCREASE_MODE_PERCENT))
        self.detail_cb.setChecked(c.get('detail_checked', True))
        # 圆形参数
        self.D_edit.setText(c.get('D', ''))
        # 平底圆形参数
        self.flat_bottom_D_edit.setText(c.get('flat_bottom_D', ''))
        self.flat_bottom_B_edit.setText(c.get('flat_bottom_B', ''))
        # 圆拱直墙型参数
        self.theta_edit.setText(c.get('theta_deg', ''))
        self.B_hs_edit.setText(c.get('B_hs', ''))
        self.H_straight_hs_edit.setText(c.get('H_straight_hs', ''))
        # 马蹄形参数
        self.r_edit.setText(c.get('r', ''))
        self._loading_case = False

    def _switch_case(self, idx):
        if idx != self._current_case_idx:
            self._save_current_case()
            self._current_case_idx = idx
            self._load_case(idx)
            self._rebuild_case_tags()
            self._update_calc_btn_text()
        self._jump_to_case_result(idx)

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
        self._mark_results_dirty()
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
        self._mark_results_dirty()
        self._cases.pop(idx)
        if self._current_case_idx >= len(self._cases):
            self._current_case_idx = len(self._cases) - 1
        self._load_case(self._current_case_idx)
        self._rebuild_case_tags()
        self._update_calc_btn_text()
        InfoBar.success(title="已删除", content=f"工况{idx + 1} 已删除，当前 {len(self._cases)} 个工况",
                        parent=self._info_parent(), position=InfoBarPosition.TOP, duration=2000)

    def _rebuild_case_tags(self):
        if hasattr(self, '_case_strip'):
            self._case_strip.sync_cases(self._cases, self._current_case_idx, self._case_view)
            self._case_strip.set_remove_enabled(len(self._cases) > 1)
            self._case_nav = self._case_strip.navigator()
            return
        if hasattr(self, '_case_nav'):
            self._case_nav.sync_cases(self._cases, self._current_case_idx, self._case_view)
            return
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

    def _case_view(self, case, idx):
        stype = case.get('section_type', '圆形')
        q_text = (case.get('Q', '') or '').strip() or '?'
        custom = (case.get('custom_label') or '').strip()
        label = f"{custom or stype} · Q={q_text}"
        return {
            "label": label,
            "tooltip": f"{label}\n断面类型：{stype}\n设计流量 Q={q_text} m³/s",
        }

    def _case_label(self, case, idx):
        return self._case_view(case, idx)["label"]

    def _auto_label(self, case, idx):
        stype = case.get('section_type', '圆形')
        q_text = (case.get('Q', '') or '').strip() or '?'
        return f"{stype}-Q{_sub(idx + 1)}={q_text}"

    @staticmethod
    def _section_plot_title(case_idx, section_type, custom_label=None):
        custom = (custom_label or '').strip()
        if custom:
            return custom
        stype = section_type or '圆形'
        if case_idx is None:
            return stype
        return f"工况 {case_idx + 1}｜{stype}"

    @staticmethod
    def _section_plot_metrics(Q, V):
        return format_flow_velocity_metrics(Q, V)

    @staticmethod
    def _apply_section_plot_title(ax, title, Q, V):
        apply_flow_velocity_title(ax, title, Q, V, fontsize=10)

    @staticmethod
    def _horseshoe_plot_geometry(B, H_total, theta_rad):
        return _build_arch_geometry(B, H_total, theta_rad)

    @staticmethod
    def _horseshoe_plot_half_width(geom, h):
        if not geom:
            return 0.0
        return _arch_half_width(geom, h)

    @staticmethod
    def _horseshoe_cap_polygon(geom, h_w, samples=30):
        if not geom:
            return None, None
        h_clamped = min(max(h_w, geom['H_straight']), geom['H_total'])
        if h_clamped <= geom['H_straight'] + 1e-9:
            return None, None

        sin_value = max(-1.0, min(1.0, (h_clamped - geom['center_y']) / geom['R_arch']))
        right_angle = math.asin(sin_value)
        left_angle = math.pi - right_angle
        water_half_width = TunnelPanel._horseshoe_plot_half_width(geom, h_clamped)

        right_arc_theta = np.linspace(right_angle, geom['start_angle'], samples)
        left_arc_theta = np.linspace(geom['end_angle'], left_angle, samples)
        right_arc_x = geom['R_arch'] * np.cos(right_arc_theta)
        right_arc_y = geom['center_y'] + geom['R_arch'] * np.sin(right_arc_theta)
        left_arc_x = geom['R_arch'] * np.cos(left_arc_theta)
        left_arc_y = geom['center_y'] + geom['R_arch'] * np.sin(left_arc_theta)

        fill_x = np.concatenate((
            np.array([-water_half_width, water_half_width]),
            right_arc_x,
            np.array([-geom['B'] / 2]),
            left_arc_x,
        ))
        fill_y = np.concatenate((
            np.array([h_clamped, h_clamped]),
            right_arc_y,
            np.array([geom['H_straight']]),
            left_arc_y,
        ))
        return fill_x, fill_y

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
        self._refresh_increase_hint()
        self._rebuild_case_tags()

    def _setup_result_dirty_tracking(self):
        if not hasattr(self, "_input_group"):
            return
        for widget in self._input_group.findChildren(QWidget):
            if hasattr(widget, "textChanged"):
                try:
                    widget.textChanged.connect(self._on_result_inputs_changed)
                except Exception:
                    pass
            if hasattr(widget, "currentTextChanged"):
                try:
                    widget.currentTextChanged.connect(self._on_result_inputs_changed)
                except Exception:
                    pass
            if hasattr(widget, "stateChanged"):
                try:
                    widget.stateChanged.connect(self._on_result_inputs_changed)
                except Exception:
                    pass

    def _on_result_inputs_changed(self, *_args):
        self._mark_results_dirty()

    def _mark_results_dirty(self):
        if self._loading_case:
            return
        if self._has_rendered_results or self._all_results:
            self._results_dirty = True
            self._clear_comparison_table("参数已变更，请重新计算后查看工况对比。")

    def _mark_results_fresh(self):
        self._results_dirty = False
        self._has_rendered_results = bool(self._all_results)

    def _show_result_jump_hint(self, stale=False):
        content = (
            "参数已变更，请先重新计算后查看对应工况结果。"
            if stale else
            "当前没有可定位的计算结果，请先完成计算。"
        )
        InfoBar.warning(
            title="无法定位结果",
            content=content,
            parent=self._info_parent(),
            position=InfoBarPosition.TOP,
            duration=2500,
        )

    def _case_result_nav_label(self, case_idx):
        if 0 <= case_idx < len(self._cases):
            return self._case_label(self._cases[case_idx], case_idx)
        return f"工况 {case_idx + 1}"

    def _case_result_nav_summary(self, case_idx, item):
        inp = item.get("input") or {}
        case = item.get("case") or {}
        res = item.get("result") or {}
        stype = inp.get("section_type") or case.get("section_type", "圆形")
        q_raw = inp.get("Q", case.get("Q", ""))
        try:
            q_text = f"Q={float(q_raw):.3f}"
        except Exception:
            q_text = f"Q={str(q_raw).strip() or '?'}"
        return "计算失败" if not res.get("success") else f"{stype} · {q_text}"

    def _build_case_nav_items(self):
        items = []
        for case_idx, item in enumerate(self._all_results):
            result = item.get("result") or {}
            items.append({
                "case_idx": case_idx,
                "anchor_id": make_case_result_anchor(self._panel_key, case_idx),
                "label": self._case_result_nav_label(case_idx),
                "summary": self._case_result_nav_summary(case_idx, item),
                "is_error": not result.get("success"),
            })
        return items

    def _jump_to_case_result(self, case_idx, *, defer_until_load=False):
        if not self._all_results or not self._has_rendered_results:
            self._show_result_jump_hint(stale=False)
            return False
        if self._results_dirty:
            self._show_result_jump_hint(stale=True)
            return False
        self.notebook.setCurrentIndex(0)
        return scroll_view_to_anchor(
            self.result_text,
            make_case_result_anchor(self._panel_key, case_idx),
            highlight=True,
            smooth=True,
            defer_until_load=defer_until_load,
        )

    def _apply_to_all_cases(self):
        self._save_current_case()
        self._mark_results_dirty()
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
                for k in ('n', 'slope_inv', 'v_min', 'v_max', 'inc_checked', 'inc_pct', 'inc_mode', 'inc_q_text', 'detail_checked'):
                    c[k] = src.get(k, c.get(k))
        InfoBar.success(title="已复制", content=f"参数已复制到其余 {n_copied} 个工况",
                        parent=self._info_parent(), position=InfoBarPosition.TOP, duration=2000)

    def _copy_from_prev_case(self):
        if self._current_case_idx == 0:
            InfoBar.warning(title="提示", content="当前已是第一个工况",
                            parent=self._info_parent(), position=InfoBarPosition.TOP, duration=2000)
            return
        self._save_current_case()
        self._mark_results_dirty()
        prev = self._cases[self._current_case_idx - 1]
        cur = self._cases[self._current_case_idx]
        if prev.get('section_type') == cur.get('section_type'):
            for k, v in prev.items():
                if k not in ('custom_label', 'Q'):
                    cur[k] = v
        else:
            for k in ('n', 'slope_inv', 'v_min', 'v_max', 'inc_checked', 'inc_pct', 'inc_mode', 'inc_q_text', 'detail_checked'):
                cur[k] = prev.get(k, cur.get(k))
        self._load_case(self._current_case_idx)
        InfoBar.success(title="已复制", content=f"已从工况{self._current_case_idx}复制参数",
                        parent=self._info_parent(), position=InfoBarPosition.TOP, duration=2000)

    def _show_initial_help(self):
        sync_case_result_nav_bar(getattr(self, "_result_case_nav", None), [])
        h = HelpPageBuilder("隧洞水力计算", '请输入参数后点击“计算”按钮')
        h.section("支持断面类型")
        h.numbered_list([
            ("圆形断面", "最小直径 2.0m，最小净空高度 0.4m"),
            ("平底圆形断面", "输入 D 和 B，自动推导总高 H，并按净空约束验算"),
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
                ["平底圆形 — 指定 D 和 B", "固定输入尺寸，自动推导总高 H 并验算"],
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

    def _read_current_float(self, edit, label, *, must_positive=True, default=None):
        """读取当前输入框数值，用于独立助手弹窗。"""
        text = (edit.text() or "").strip()
        if not text:
            if default is not None:
                return default
            raise ValueError(f"请输入{label}")
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError(f"{label}输入无效") from exc
        if must_positive and value <= 0:
            raise ValueError(f"{label}必须大于0")
        return value

    def _build_clearance_sizing_context(self):
        """整理圆拱直墙净空反推弹窗所需的当前工况参数。"""
        Q = self._read_current_float(self.Q_edit, "设计流量 Q")
        n = self._read_current_float(self.n_edit, "糙率 n")
        slope_inv = self._read_current_float(self.slope_edit, "水力坡降倒数")
        v_min = self._read_current_float(self.vmin_edit, "不淤流速", must_positive=False)
        v_max = self._read_current_float(self.vmax_edit, "不冲流速", must_positive=False)
        if v_min >= v_max:
            raise ValueError("不淤流速必须小于不冲流速")
        theta_deg = self._read_current_float(
            self.theta_edit,
            "拱顶圆心角",
            must_positive=True,
            default=180.0,
        )
        use_increase = self.inc_cb.isChecked()
        increase_mode = self._current_increase_mode()
        percent_text = self.inc_edit.text()
        q_increased_text = self.inc_q_edit.text()
        if use_increase:
            increase_resolution = resolve_increase_input(
                use_increase=True,
                mode=increase_mode,
                design_q=Q,
                percent_text=percent_text,
                q_increased_text=q_increased_text,
                disabled_percent=0.0,
            )
            q_increased = increase_resolution.q_increased_value
            if increase_resolution.mode == INCREASE_MODE_Q_INCREASED:
                q_increased_source = "manual_q"
            elif (percent_text or "").strip():
                q_increased_source = "manual_percent"
            else:
                q_increased_source = "auto_percent"
        else:
            auto_percent = get_auto_increase_percent(Q)
            q_increased = calculate_q_increased(Q, auto_percent)
            q_increased_source = "auto_when_disabled"
        return {
            "Q_design": Q,
            "Q_increased": q_increased if q_increased is not None else 0.0,
            "Q_increased_source": q_increased_source,
            "n": n,
            "slope_inv": slope_inv,
            "v_min": v_min,
            "v_max": v_max,
            "theta_deg": theta_deg,
        }

    def _open_clearance_sizing_dialog(self):
        """打开圆拱直墙型按净空反推尺寸弹窗。"""
        if self.section_combo.currentText() != "圆拱直墙型":
            InfoBar.warning(
                title="提示",
                content="请先将断面类型切换为圆拱直墙型。",
                parent=self._info_parent(),
                position=InfoBarPosition.TOP,
                duration=2500,
            )
            return
        try:
            context = self._build_clearance_sizing_context()
        except ValueError as exc:
            InfoBar.warning(
                title="输入错误",
                content=str(exc),
                parent=self._info_parent(),
                position=InfoBarPosition.TOP,
                duration=3500,
            )
            return
        dlg = HorseshoeClearanceSizingDialog(self._info_parent(), context)
        if dlg.exec() == QDialog.Accepted and dlg.result_payload:
            self._apply_clearance_sizing_result(dlg.result_payload)

    def _apply_clearance_sizing_result(self, result):
        """把反推尺寸采用到当前工况，但不触发主计算。"""
        self.theta_edit.setText(f"{float(result.get('theta_deg', 0.0)):.3f}")
        self.B_hs_edit.setText(f"{float(result.get('B', 0.0)):.3f}")
        self.H_straight_hs_edit.setText(f"{float(result.get('H_straight', 0.0)):.3f}")
        if 0 <= self._current_case_idx < len(self._cases):
            self._save_current_case()
        self._mark_results_dirty()
        try:
            self.data_changed.emit()
        except Exception:
            pass
        InfoBar.success(
            title="已采用",
            content="已回填 θ、B 和 H直。请点击“计算”刷新结果。",
            parent=self._info_parent(),
            position=InfoBarPosition.TOP,
            duration=3000,
        )

    # ================================================================
    # 计算
    # ================================================================
    def _prepare_calculation_run(self):
        # Flush pending UI updates before reading the active case snapshot.
        try:
            QApplication.sendPostedEvents(None, 0)
            QApplication.processEvents()
        except Exception:
            pass
        self._save_current_case()
        self._rebuild_case_tags()
        self._all_results = []
        self.current_result = None
        self.input_params = {}
        self._export_plain_text = ""

    def _parse_and_calc_case(self, case_dict, case_num):
        """解析单个工况并计算，返回 (input_params, result) 或抛出异常"""
        def _required_float(key, label, must_positive=True):
            text = (case_dict.get(key, "") or "").strip()
            if not text:
                raise ValueError(f"工况{case_num}: 请输入{label}")
            try:
                value = float(text)
            except ValueError as exc:
                raise ValueError(f"工况{case_num}: {label}输入无效") from exc
            if must_positive and value <= 0:
                raise ValueError(f"工况{case_num}: {label}必须大于0")
            return value

        def _optional_float(key, label, must_nonnegative=False):
            text = (case_dict.get(key, "") or "").strip()
            if not text:
                return None
            try:
                value = float(text)
            except ValueError as exc:
                raise ValueError(f"工况{case_num}: {label}输入无效") from exc
            if must_nonnegative and value < 0:
                raise ValueError(f"工况{case_num}: {label}不能为负数")
            return value

        stype = case_dict.get('section_type', '圆形')
        Q = _required_float('Q', '设计流量 Q')
        n = _required_float('n', '糙率 n')
        slope_inv = _required_float('slope_inv', '水力坡降倒数')
        v_min = _required_float('v_min', '不淤流速', must_positive=False)
        v_max = _required_float('v_max', '不冲流速', must_positive=False)
        if v_min >= v_max:
            raise ValueError("不淤流速必须小于不冲流速")

        use_increase = case_dict.get('inc_checked', True)
        increase_resolution = resolve_increase_input(
            use_increase=use_increase,
            mode=case_dict.get('inc_mode', INCREASE_MODE_PERCENT),
            design_q=Q,
            percent_text=case_dict.get('inc_pct', ''),
            q_increased_text=case_dict.get('inc_q_text', ''),
            disabled_percent=0.0,
        )
        manual_increase = increase_resolution.manual_increase_percent
        inc_mode = increase_resolution.mode

        input_params = {
            'Q': Q, 'n': n, 'slope_inv': slope_inv,
            'v_min': v_min, 'v_max': v_max,
            'section_type': stype, 'manual_increase': manual_increase,
            'use_increase': use_increase,
            'detail_checked': case_dict.get('detail_checked', True),
            'inc_mode': inc_mode,
            'inc_pct_text': case_dict.get('inc_pct', ''),
            'inc_q_text': case_dict.get('inc_q_text', ''),
        }

        if stype == "平底圆形":
            flat_bottom_D = _required_float('flat_bottom_D', '平底圆形直径 D')
            flat_bottom_B = _required_float('flat_bottom_B', '平底圆形平底宽 B')
            input_params['manual_D'] = flat_bottom_D
            input_params['manual_B'] = flat_bottom_B
            result = quick_calculate_flat_bottom_circular(
                Q=Q, n=n, slope_inv=slope_inv,
                v_min=v_min, v_max=v_max,
                manual_D=flat_bottom_D,
                manual_B=flat_bottom_B,
                manual_increase_percent=manual_increase
            )
        elif stype == "圆形":
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
            theta_deg = _optional_float('theta_deg', '拱顶圆心角') or 180
            manual_B = _optional_float('B_hs', '指定底宽 B')
            manual_H_straight = _optional_float('H_straight_hs', '直墙高度 H直', must_nonnegative=True)
            if manual_H_straight is not None and (manual_B is None or manual_B <= 0):
                raise ValueError(f"工况{case_num}: 填写直墙高度 H直 时必须同时填写底宽 B")
            input_params['theta_deg'] = theta_deg
            input_params['manual_B'] = manual_B
            input_params['manual_H_straight'] = manual_H_straight
            result = quick_calculate_horseshoe(
                Q=Q, n=n, slope_inv=slope_inv,
                v_min=v_min, v_max=v_max,
                theta_deg=theta_deg,
                manual_B=manual_B,
                manual_H_straight=manual_H_straight,
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
        self._prepare_calculation_run()
        error_msgs = []

        for i, c in enumerate(self._cases):
            label = c.get('custom_label') or self._auto_label(c, i)
            try:
                inp, res = self._parse_and_calc_case(c, i + 1)
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
            self._refresh_comparison_table()
            self.data_changed.emit()

    def _show_error(self, title, msg):
        sync_case_result_nav_bar(getattr(self, "_result_case_nav", None), [])
        self._clear_comparison_table("当前计算失败，请修正参数后重新计算。")
        out = ["=" * 70, f"  {title}", "=" * 70, "", msg, "", "-" * 70, "请修正后重新计算。", "=" * 70]
        self.result_text.setHtml(make_plain_html("\n".join(out)))

    def _increase_summary_lines(self, params, result):
        """生成加大流量输入说明。"""
        return build_increase_summary_lines(
            use_increase=params.get('use_increase', True),
            mode=params.get('inc_mode', INCREASE_MODE_PERCENT),
            percent_text=params.get('inc_pct_text', ''),
            q_increased_text=params.get('inc_q_text', ''),
            result_increase_percent=result.get('increase_percent', 0.0),
            result_q_increased=result.get('Q_increased', params.get('Q', 0.0)),
        )

    def _safe_increase_summary_lines(self, params, result):
        """兼容轻量测试替身，生成加大流量输入说明。"""
        builder = getattr(self, '_increase_summary_lines', None)
        if callable(builder):
            return builder(params, result)
        return TunnelPanel._increase_summary_lines(self, params, result)

    # ================================================================
    # 结果显示
    # ================================================================
    def _display_all_results_legacy(self):
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
            type_label = TunnelPanel._resolve_result_type_label(self, stype, res)
            txt = self._build_result_text(res, type_label, detail, inp)
            all_text_parts.append(header + "\n\n" + txt)

        combined = "\n".join(all_text_parts)
        self._export_plain_text = combined
        load_formula_page(self.result_text, plain_text_to_formula_html(combined))

    def _display_all_results_legacy(self):
        """显示所有工况的计算结果，并在多工况时生成顶部导航。"""
        _multi = len(self._all_results) > 1
        all_text_parts = []
        all_html_parts = []

        for case_idx, item in enumerate(self._all_results):
            inp = item.get('input')
            res = item.get('result') or {}
            case = item.get('case') or {}
            stype = (inp or {}).get('section_type', case.get('section_type', '圆形'))
            q_raw = (inp or {}).get('Q', case.get('Q', ''))
            try:
                q_text = f"{float(q_raw):.3f}"
            except Exception:
                q_text = (str(q_raw).strip() or '-')
            header = f"【工况 {case_idx + 1}｜{stype}断面｜Q = {q_text} m³/s】"
            if not res:
                continue
            if not res.get('success'):
                plain = f"{header}\n\n计算失败：{res.get('error_message', '未知错误')}\n"
                body_text = plain.split("\n\n", 1)[-1]
                body_html = plain_text_to_formula_body(body_text)
            else:
                self.input_params = inp
                detail = inp.get('detail_checked', True)
                type_label = TunnelPanel._resolve_result_type_label(self, stype, res)
                txt = self._build_result_text(res, type_label, detail, inp)
                plain = header + "\n\n" + txt
                body_html = plain_text_to_formula_body(txt)
                body_html = prepend_result_summary_to_body("tunnel", inp or {}, res, body_html)
            all_text_parts.append(plain)
            all_html_parts.append(
                wrap_case_result_block(
                    self._panel_key,
                    case_idx,
                    f"工况 {case_idx + 1}",
                    body_html,
                    subtitle=self._case_result_nav_label(case_idx),
                    is_error=not res.get("success"),
                )
            )

        self._export_plain_text = "\n".join(all_text_parts)
        nav_builder = getattr(self, "_build_case_nav_items", None)
        nav_items = nav_builder() if callable(nav_builder) else []
        nav_html = build_result_nav_bar(nav_items, hidden=True)
        combined_body = nav_html + "\n".join(all_html_parts)
        combined_head = build_result_navigation_head()
        load_formula_page(self.result_text, wrap_with_katex(combined_body, extra_head=combined_head))
        sync_case_result_nav_bar(getattr(self, "_result_case_nav", None), nav_items)

        self._mark_results_fresh()
        self._jump_to_case_result(self._current_case_idx, defer_until_load=True)

    def _display_all_results(self):
        return TunnelPanel._display_all_results_legacy(self)

    def eventFilter(self, obj, event):
        """处理工况对比表快捷键，支持全选后复制到 Excel。"""
        table = getattr(self, "comparison_table", None)
        if obj is table and event.type() == QEvent.KeyPress:
            mods = event.modifiers()
            ctrl_only = bool(mods & Qt.ControlModifier) and not (
                mods & (Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
            )
            if ctrl_only and event.key() == Qt.Key_A:
                table.selectAll()
                return True
            if ctrl_only and event.key() == Qt.Key_C:
                self._copy_comparison_selection_to_clipboard()
                return True
        return super().eventFilter(obj, event)

    def _build_comparison_clipboard_text(self):
        """生成可粘贴到 Excel 的工况对比表文本。"""
        table = getattr(self, "comparison_table", None)
        if table is None:
            return "", 0, 0
        indexes = table.selectedIndexes()
        if not indexes:
            return "", 0, 0
        rows = sorted({idx.row() for idx in indexes})
        cols = sorted({idx.column() for idx in indexes})
        selected = {(idx.row(), idx.column()) for idx in indexes}

        header_cells = []
        for col in cols:
            header_item = table.horizontalHeaderItem(col)
            header_cells.append(header_item.text() if header_item else "")

        lines = ["\t".join(header_cells)]
        for row in rows:
            row_cells = []
            for col in cols:
                if (row, col) not in selected:
                    row_cells.append("")
                    continue
                item = table.item(row, col)
                row_cells.append(item.text() if item else "")
            lines.append("\t".join(row_cells))
        return "\n".join(lines), len(rows), len(cols)

    def _copy_comparison_selection_to_clipboard(self):
        """复制工况对比表选区到剪贴板，供 Excel 直接粘贴。"""
        text, row_count, col_count = self._build_comparison_clipboard_text()
        if not text:
            return
        QApplication.clipboard().setText(text)
        InfoBar.success(
            "已复制",
            f"已复制 {row_count} 行 × {col_count} 列到剪贴板，可粘贴到 Excel。",
            parent=self._info_parent(),
            duration=2000,
            position=InfoBarPosition.TOP,
        )

    def _set_comparison_hint(self, text):
        """更新工况对比表提示。"""
        if hasattr(self, "comparison_hint"):
            self.comparison_hint.setText(text)

    def _clear_comparison_table(self, hint="请先完成计算，系统会在这里汇总各工况的关键水力结果和洞身尺寸。"):
        """清空工况对比表。"""
        if hasattr(self, "comparison_table"):
            self.comparison_table.setRowCount(0)
            self._set_comparison_hint(hint)

    def _refresh_comparison_table(self):
        """用当前成功工况刷新工况对比表。"""
        if not hasattr(self, "comparison_table"):
            return
        rows = build_tunnel_comparison_rows(getattr(self, "_all_results", []))
        self.comparison_table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            for col_idx, column in enumerate(TUNNEL_COMPARISON_COLUMNS):
                text = format_comparison_cell(row.get(column.key), column.digits)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self.comparison_table.setItem(row_idx, col_idx, item)
        self.comparison_table.resizeColumnsToContents()
        if rows:
            self._set_comparison_hint("已汇总成功计算的工况；周长和断面积按完整洞身几何统计。")
        else:
            self._set_comparison_hint("当前没有可汇总的成功工况，请检查计算结果。")

    def _resolve_result_type_label(self, stype, result):
        """统一解析结果标题，避免平底圆形落回默认分支。"""
        if stype == "平底圆形":
            return "平底圆形"
        if stype == "圆形":
            return "圆形"
        if stype == "圆拱直墙型":
            return "圆拱直墙型"
        return result.get('section_type', '马蹄形')

    @staticmethod
    def _horseshoe_arch_metrics(result):
        """计算圆拱直墙型拱部与直墙高度展示参数。"""
        B = result.get('B', 0) or 0
        H_total = result.get('H_total', 0) or 0
        theta_deg = result.get('theta_deg', 180) or 180
        try:
            theta_rad = math.radians(float(theta_deg))
            sin_half = math.sin(theta_rad / 2)
            if B <= 0 or sin_half <= 1e-9:
                return None
            R_arch = (B / 2) / sin_half
            H_arch = R_arch * (1 - math.cos(theta_rad / 2))
            H_straight = result.get('H_straight', None)
            if H_straight is None:
                H_straight = max(0, H_total - H_arch)
            source = "按用户输入固定" if result.get('used_manual_H_straight') else "H直 = H总 - H拱"
            return {
                'R_arch': R_arch,
                'H_arch': H_arch,
                'H_straight': H_straight,
                'source': source,
            }
        except Exception:
            return None

    def _build_result_text(self, result, type_label, detail, p):
        """构建单个工况的结果文本（从_show_result提取）"""
        Q, n = p['Q'], p['n']
        slope_inv = p['slope_inv']; i = 1.0 / slope_inv
        v_min, v_max = p['v_min'], p['v_max']
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
            if stype == "平底圆形":
                o.append(f"  直径 D = {result.get('D', 0):.2f} m")
                o.append(f"  平底宽 B = {result.get('B', 0):.2f} m")
                o.append(f"  推导总高 H = {result.get('H_total', 0):.2f} m")
            elif stype == "圆形":
                o.append(f"  直径 D = {result.get('D', 0):.2f} m")
            elif stype == "圆拱直墙型":
                o.append(f"  宽度 B = {result.get('B', 0):.2f} m")
                o.append(f"  高度 H = {result.get('H_total', 0):.2f} m")
                arch_metrics = self._horseshoe_arch_metrics(result)
                if arch_metrics:
                    o.append(f"  拱半径 R拱 = {arch_metrics['R_arch']:.3f} m")
                    o.append(f"  拱高 H拱 = {arch_metrics['H_arch']:.3f} m")
                    o.append(f"  直墙高度 H直 = {arch_metrics['H_straight']:.3f} m")
                    o.append(f"  直墙高度来源: {arch_metrics['source']}")
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
                for line in TunnelPanel._safe_increase_summary_lines(self, p, result):
                    o.append(f"  {line}")
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
            if stype == "平底圆形":
                D = result['D']; B = result['B']; H_total = result['H_total']
                o.append(f"  直径 D = {D:.2f} m, 平底宽 B = {B:.2f} m")
                o.append(f"  推导总高 H = {H_total:.2f} m")
                o.append(f"  断面总面积 A总 = {A_total:.3f} m²")
            elif stype == "圆形":
                D = result['D']
                o.append(f"  直径 D = {D:.2f} m")
                o.append(f"  断面总面积 A总 = π×D²/4 = {A_total:.3f} m²")
            elif stype == "圆拱直墙型":
                B = result['B']; H_total = result['H_total']
                o.append(f"  宽度 B = {B:.2f} m, 高度 H = {H_total:.2f} m")
                o.append(f"  拱顶圆心角 θ = {result['theta_deg']:.1f}°")
                arch_metrics = self._horseshoe_arch_metrics(result)
                if arch_metrics:
                    o.append(f"  拱半径 R拱 = (B/2) / sin(θ/2) = {arch_metrics['R_arch']:.3f} m")
                    o.append(f"  拱高 H拱 = R拱 × (1 - cos(θ/2)) = {arch_metrics['H_arch']:.3f} m")
                    o.append(f"  直墙高度 H直 = {arch_metrics['H_straight']:.3f} m")
                    o.append(f"  直墙高度来源: {arch_metrics['source']}")
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
                for line in TunnelPanel._safe_increase_summary_lines(self, p, result):
                    o.append(f"  {line}")
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
        if stype == "平底圆形":
            self._show_result(result, "平底圆形", detail)
        elif stype == "圆形":
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
            if stype == "平底圆形":
                o.append(f"  直径 D = {result.get('D', 0):.2f} m")
                o.append(f"  平底宽 B = {result.get('B', 0):.2f} m")
                o.append(f"  推导总高 H = {result.get('H_total', 0):.2f} m")
            elif stype == "圆形":
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
                for line in TunnelPanel._safe_increase_summary_lines(self, p, result):
                    o.append(f"  {line}")
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
            if stype == "平底圆形":
                D = result['D']; B = result['B']; H_total = result['H_total']
                o.append("【二、断面尺寸】")
                o.append("")
                o.append("  1. 输入尺寸:")
                o.append(f"     D = {D:.2f} m")
                o.append(f"     B = {B:.2f} m")
                o.append("")
                o.append("  2. 推导总高:")
                o.append(f"     H = {H_total:.3f} m")
                o.append("")
                o.append("  3. 断面总面积:")
                o.append(f"     A总 = {A_total:.3f} m²")
                o.append("")
            elif stype == "圆形":
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
                arch_metrics = self._horseshoe_arch_metrics(result)
                o.append("【二、断面尺寸】")
                o.append("")
                o.append(f"  1. 设计宽度: B = {B:.2f} m")
                o.append(f"  2. 设计高度: H = {H_total:.2f} m")
                o.append(f"  3. 拱顶圆心角: θ = {theta_deg:.1f}°")
                if arch_metrics:
                    o.append("  4. 直墙高度推导:")
                    o.append(f"     R拱 = (B/2) / sin(θ/2) = {arch_metrics['R_arch']:.3f} m")
                    o.append(f"     H拱 = R拱 × (1 - cos(θ/2)) = {arch_metrics['H_arch']:.3f} m")
                    o.append(f"     H直 = H总 - H拱 = {arch_metrics['H_straight']:.3f} m")
                    o.append(f"     来源: {arch_metrics['source']}")
                    next_idx = 5
                else:
                    next_idx = 4
                o.append(f"  {next_idx}. 高宽比: H/B = {H_total:.2f}/{B:.2f} = {result.get('HB_ratio', 0):.3f}")
                o.append(f"  {next_idx + 1}. 断面总面积: A总 = {A_total:.3f} m²")
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
            elif stype == "平底圆形":
                o.append("  2. 过水面积计算 (平底圆形):")
                o.append(f"     A = {A_d:.3f} m²")
                o.append("")
                o.append("  3. 湿周计算 (平底圆形):")
                o.append(f"     χ = {P_d:.3f} m")
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
                o.append("  1. 加大流量输入说明:")
                for line in TunnelPanel._safe_increase_summary_lines(self, p, result):
                    o.append(f"      {line}")
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
            elif stype == "平底圆形":
                o.append("  3. 过水面积计算 (平底圆形):")
                o.append(f"      A加大 = {A_inc:.3f} m²")
                o.append("")
                o.append("  4. 湿周计算 (平底圆形):")
                o.append(f"      χ加大 = {P_inc:.3f} m")
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
        html = prepend_result_summary_to_html(
            "tunnel",
            getattr(self, "input_params", {}),
            result,
            plain_text_to_formula_html(txt),
        )
        load_formula_page(self.result_text, html)

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

        if stype == "平底圆形":
            D = result['D']; B = result['B']
            self._draw_flat_bottom_circle(axes[0], D, B, result['h_design'], result['V_design'], Q, "设计流量")
            self._draw_flat_bottom_circle(axes[1], D, B, result['h_increased'], result['V_increased'], Q_inc, "加大流量")
        elif stype == "圆形":
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
        valid = [
            (case_idx, item)
            for case_idx, item in enumerate(self._all_results)
            if item.get('result', {}).get('success')
        ]
        if not valid:
            self.section_canvas.draw()
            return
        n = len(valid)
        cols = min(n, 3)
        rows = (n + cols - 1) // cols
        axes = self.section_fig.subplots(rows, cols, squeeze=False)
        for plot_idx, (case_idx, item) in enumerate(valid):
            r_idx, c_idx = divmod(plot_idx, cols)
            ax = axes[r_idx][c_idx]
            res = item['result']
            inp = item['input']
            case = item.get('case') or {}
            stype = inp.get('section_type', '圆形')
            title = self._section_plot_title(case_idx, stype, case.get('custom_label'))
            Q = inp['Q']
            h_d = res['h_design']
            V_d = res['V_design']
            if stype == "平底圆形":
                D = res['D']; B = res['B']
                self._draw_flat_bottom_circle(ax, D, B, h_d, V_d, Q, title)
            elif stype == "圆形":
                D = res['D']
                self._draw_circular(ax, D, h_d, V_d, Q, title)
            elif stype == "圆拱直墙型":
                B = res['B']; H = res['H_total']; theta = math.radians(res['theta_deg'])
                self._draw_horseshoe(ax, B, H, theta, h_d, V_d, Q, title)
            else:
                r_val = res['r']
                sec_int = inp.get('sec_type_int', 1)
                self._draw_horseshoe_std(ax, sec_int, r_val, h_d, V_d, Q, title)
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
        ax.set_aspect('equal'); self._apply_section_plot_title(ax, title, Q, V)
        ax.grid(True, alpha=0.3); ax.axhline(y=0, color='brown', lw=3)

    def _draw_flat_bottom_circle(self, ax, D, B, h_w, V, Q, title):
        """绘制平底圆形断面。"""
        geom = _build_flat_bottom_circle_geometry(D, B)
        arc_points = _sample_arc(geom['top_arc'], samples=100)
        ax.plot([geom['bottom_left'][0], geom['bottom_right'][0]], [0, 0], 'k-', lw=2)
        ax.plot([point[0] for point in arc_points], [point[1] for point in arc_points], 'k-', lw=2)

        if h_w > 0:
            water_depth = min(h_w, geom['H_total'])
            y_samples = np.linspace(0, water_depth, 60)
            left_x = [-_flat_bottom_circle_half_width(geom, y) for y in y_samples]
            right_x = [_flat_bottom_circle_half_width(geom, y) for y in y_samples]
            fill_x = left_x + right_x[::-1]
            fill_y = list(y_samples) + list(y_samples[::-1])
            ax.fill(fill_x, fill_y, color='lightblue', alpha=0.7)
            water_width = _flat_bottom_circle_surface_width(geom, water_depth)
            if water_width > 0:
                ax.plot([-water_width / 2.0, water_width / 2.0], [water_depth, water_depth], 'b-', lw=1.5)

        H_total = geom['H_total']
        ax.annotate('', xy=(B/2, -0.08*H_total), xytext=(-B/2, -0.08*H_total), arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, -0.16*H_total, f'B={B:.2f}m', ha='center', fontsize=9, color='gray')
        ax.annotate('', xy=(D/2, -0.22*H_total), xytext=(-D/2, -0.22*H_total), arrowprops=dict(arrowstyle='<->', color='gray', lw=1.2))
        ax.text(0, -0.30*H_total, f'D={D:.2f}m', ha='center', fontsize=8, color='gray')
        ax.annotate('', xy=(D/2+0.1*D, H_total), xytext=(D/2+0.1*D, 0), arrowprops=dict(arrowstyle='<->', color='purple', lw=1.5))
        ax.text(D/2+0.18*D, H_total/2, f'H={H_total:.2f}m', fontsize=8, color='purple', rotation=90, va='center')
        # 标注水深，和圆形断面保持同一展示口径。
        if h_w > 0:
            ax.annotate('', xy=(-D/2-0.10*D, h_w), xytext=(-D/2-0.10*D, 0), arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-D/2-0.18*D, h_w/2, f'h={h_w:.2f}m', ha='right', fontsize=8, color='blue', rotation=90, va='center')
        ax.set_xlim(-D*0.95, D*0.9); ax.set_ylim(-H_total*0.42, H_total*1.2)
        ax.set_aspect('equal'); self._apply_section_plot_title(ax, title, Q, V)
        ax.grid(True, alpha=0.3); ax.axhline(y=0, color='brown', lw=3)

    def _draw_horseshoe(self, ax, B, H_total, theta_rad, h_w, V, Q, title):
        """绘制圆拱直墙型断面"""
        geom = self._horseshoe_plot_geometry(B, H_total, theta_rad)
        R_arch = geom['R_arch']
        H_straight = geom['H_straight']
        center_y = geom['center_y']
        # 拱部
        start_angle = geom['start_angle']
        end_angle = geom['end_angle']
        arch_theta = np.linspace(start_angle, end_angle, 101)
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
                    fill_x, fill_y = self._horseshoe_cap_polygon(geom, h_w)
                    if fill_x is not None and fill_y is not None:
                        ax.fill(fill_x, fill_y, color='lightblue', alpha=0.7)
            water_half_width = self._horseshoe_plot_half_width(geom, h_w)
            ax.plot([-water_half_width, water_half_width], [h_w, h_w], 'b-', lw=1.5)
        # 标注
        ax.annotate('', xy=(B/2, -0.08*H_total), xytext=(-B/2, -0.08*H_total), arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, -0.16*H_total, f'B={B:.2f}m', ha='center', fontsize=9, color='gray')
        ax.annotate('', xy=(B/2+0.1*B, H_total), xytext=(B/2+0.1*B, 0), arrowprops=dict(arrowstyle='<->', color='purple', lw=1.5))
        ax.text(B/2+0.18*B, H_total/2, f'H={H_total:.2f}m', fontsize=8, color='purple', rotation=90, va='center')
        if H_straight > 0:
            ax.annotate('', xy=(-B/2-0.1*B, H_straight), xytext=(-B/2-0.1*B, 0), arrowprops=dict(arrowstyle='<->', color='darkgreen', lw=1.2))
            ax.text(-B/2-0.18*B, H_straight/2, f'H直={H_straight:.2f}m', fontsize=8, color='darkgreen', rotation=90, va='center', ha='right')
        # 水深标注放在 H直 外侧，避免两个竖向尺寸重叠。
        if h_w > 0:
            ax.annotate('', xy=(-B/2-0.28*B, h_w), xytext=(-B/2-0.28*B, 0), arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-B/2-0.36*B, h_w/2, f'h={h_w:.2f}m', ha='right', fontsize=8, color='blue', rotation=90, va='center')
        ax.set_xlim(-B*1.05, B*0.9); ax.set_ylim(-H_total*0.3, H_total*1.2)
        ax.set_aspect('equal'); self._apply_section_plot_title(ax, title, Q, V)
        ax.grid(True, alpha=0.3); ax.axhline(y=0, color='brown', lw=3)

    def _draw_horseshoe_std(self, ax, sec_type, r, h_w, V, Q, title):
        """绘制标准马蹄形断面（真实圆弧预览）"""
        geom = _build_standard_horseshoe_geometry(sec_type, r)
        type_name = geom['type_name']
        for arc in geom['arcs']:
            points = _sample_arc(arc, samples=80)
            x_vals = [point[0] for point in points]
            y_vals = [point[1] for point in points]
            ax.plot(x_vals, y_vals, 'k-', lw=2)

        if h_w > 0 and h_w < 2 * r:
            water_half_width = _standard_horseshoe_half_width(geom, h_w)
            water_heights = np.linspace(0, h_w, 50)
            wl_x = [-_standard_horseshoe_half_width(geom, h) for h in water_heights]
            wl_y = list(water_heights)
            wr_x = [_standard_horseshoe_half_width(geom, h) for h in water_heights]
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
        ax.set_aspect('equal'); self._apply_section_plot_title(ax, f'{title} ({type_name})', Q, V)
        ax.grid(True, alpha=0.3); ax.axhline(y=0, color='brown', lw=3)

    # ================================================================
    # 清空 / 导出
    # ================================================================
    def _clear(self):
        self._save_current_case()
        self._show_initial_help()
        self.section_fig.clear(); self.section_canvas.draw()
        self._refresh_increase_hint()
        self.current_result = None
        self._all_results = []
        self._results_dirty = False
        self._has_rendered_results = False
        self._rebuild_case_tags()
        self._update_calc_btn_text()
        self._export_plain_text = ""
        self._clear_comparison_table()

    def _export_dxf(self):
        case_entries = self._build_dxf_export_case_entries()
        current_entry = self._get_current_dxf_export_entry(case_entries)
        if len(self._cases) <= 1:
            if current_entry is None or not current_entry.is_valid:
                self._warn_single_dxf_entry_unavailable(current_entry)
                return
            try:
                filepath = self._export_single_dxf_entry(current_entry)
                if not filepath:
                    return
                InfoBar.success(
                    "导出成功",
                    f"DXF已保存到: {filepath}",
                    parent=self._info_parent(),
                    duration=4000,
                    position=InfoBarPosition.TOP,
                )
                ask_open_file(filepath, self._info_parent())
            except ImportError as e:
                InfoBar.error("缺少依赖", str(e), parent=self._info_parent(), duration=6000, position=InfoBarPosition.TOP)
            except PermissionError:
                InfoBar.error("文件被占用", "无法写入文件，请关闭已打开的同名DXF文件。", parent=self._info_parent(), duration=8000, position=InfoBarPosition.TOP)
            except Exception as e:
                InfoBar.error("导出失败", f"DXF导出失败: {str(e)}", parent=self._info_parent(), duration=5000, position=InfoBarPosition.TOP)
            return

        dialog_result = show_multi_case_dxf_dialog(
            self._info_parent(),
            "隧洞断面",
            case_entries,
            self._current_case_idx,
        )
        if dialog_result is None:
            return
        selected_entries = select_case_entries(
            case_entries,
            dialog_result.scope,
            self._current_case_idx,
            dialog_result.checked_case_indexes,
        )
        valid_entries, invalid_entries = partition_valid_case_entries(selected_entries)
        if not valid_entries:
            InfoBar.warning(
                "提示",
                format_empty_export_warning(invalid_entries),
                parent=self._info_parent(),
                duration=4000,
                position=InfoBarPosition.TOP,
            )
            return
        try:
            if len(valid_entries) == 1:
                filepath = self._export_single_dxf_entry(valid_entries[0], scale_denom=dialog_result.scale_denom)
            else:
                filepath = self._export_combined_dxf_entries(valid_entries, dialog_result.scale_denom)
            if not filepath:
                return
            InfoBar.success(
                "导出成功",
                f"{format_export_result_message(len(valid_entries), invalid_entries)}\n文件：{filepath}",
                parent=self._info_parent(),
                duration=5000,
                position=InfoBarPosition.TOP,
            )
            ask_open_file(filepath, self._info_parent())
        except ImportError as e:
            InfoBar.error("缺少依赖", str(e), parent=self._info_parent(), duration=6000, position=InfoBarPosition.TOP)
        except PermissionError:
            InfoBar.error("文件被占用", "无法写入文件，请关闭已打开的同名DXF文件。", parent=self._info_parent(), duration=8000, position=InfoBarPosition.TOP)
        except Exception as e:
            InfoBar.error("导出失败", f"DXF导出失败: {str(e)}", parent=self._info_parent(), duration=5000, position=InfoBarPosition.TOP)

    def _build_dxf_export_case_entries(self):
        entries = []
        results_dirty = bool(getattr(self, "_results_dirty", False))
        for case_idx, case in enumerate(self._cases):
            item = self._all_results[case_idx] if case_idx < len(self._all_results) else None
            input_params = (item or {}).get("input") or {}
            result = (item or {}).get("result")
            invalid_reason = None
            if results_dirty and self._all_results:
                invalid_reason = "结果已失效"
            elif item is None or result is None:
                invalid_reason = "无计算结果"
            elif not result.get("success"):
                invalid_reason = "计算失败"
            entries.append(
                DxfExportCaseEntry(
                    case_idx=case_idx,
                    label=self._case_label(case, case_idx),
                    input_params=input_params,
                    result=result,
                    is_valid=invalid_reason is None,
                    invalid_reason=invalid_reason,
                )
            )
        return entries

    def _get_current_dxf_export_entry(self, case_entries):
        for entry in case_entries:
            if entry.case_idx == self._current_case_idx:
                return entry
        return case_entries[0] if case_entries else None

    def _warn_single_dxf_entry_unavailable(self, entry):
        if entry is not None and entry.invalid_reason == "结果已失效":
            content = "参数已变更，请先重新计算后再导出。"
        else:
            content = "请先进行计算后再导出。"
        InfoBar.warning(
            "提示",
            content,
            parent=self._info_parent(),
            duration=3000,
            position=InfoBarPosition.TOP,
        )

    def _single_dxf_default_name(self, entry):
        result = entry.result or {}
        input_params = entry.input_params or {}
        stype = input_params.get('section_type', '圆形')
        if stype == '平底圆形':
            return f"隧洞断面_平底圆形_D{result.get('D', 0.0):.2f}_B{result.get('B', 0.0):.2f}.dxf"
        if stype == '圆形':
            return f"隧洞断面_圆形_D{result.get('D', 0.0):.2f}.dxf"
        if stype == '圆拱直墙型':
            return f"隧洞断面_圆拱直墙_B{result.get('B', 0.0):.2f}xH{result.get('H_total', 0.0):.2f}.dxf"
        return f"隧洞断面_马蹄形_r{result.get('r', 0.0):.2f}.dxf"

    def _combined_dxf_default_name(self, count):
        return f"隧洞断面_{count}个工况_合并.dxf"

    def _choose_dxf_filepath(self, default_name):
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "保存DXF文件",
            default_name,
            "DXF文件 (*.dxf);;所有文件 (*.*)",
        )
        if not filepath:
            return None
        return filepath if filepath.lower().endswith(".dxf") else f"{filepath}.dxf"

    def _export_single_dxf_entry(self, entry, scale_denom=None):
        scale = scale_denom if scale_denom is not None else choose_scale_denom(self)
        if scale is None:
            return None
        filepath = self._choose_dxf_filepath(self._single_dxf_default_name(entry))
        if not filepath:
            return None
        export_tunnel_dxf(filepath, entry.result or {}, entry.input_params or {}, scale)
        return filepath

    def _export_combined_dxf_entries(self, entries, scale_denom):
        filepath = self._choose_dxf_filepath(self._combined_dxf_default_name(len(entries)))
        if not filepath:
            return None
        return export_combined_case_dxf(
            filepath,
            entries,
            scale_denom,
            draw_tunnel_dxf_on_msp,
            draw_summary_table=draw_tunnel_comparison_table,
        )

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
            type_label = TunnelPanel._resolve_result_type_label(self, s, res)
            txt = self._build_result_text(res, type_label, detail, inp)
            if len(export_results) > 1:
                doc_add_eng_body(doc, f"【工况: {label}】")
            summary_items = build_result_summary_word_items("tunnel", inp, res)
            if summary_items:
                doc_add_eng_h(doc, '重点结果汇总')
                doc_add_result_table(doc, summary_items)
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
                self._refresh_comparison_table()
            except Exception:
                self._all_results = []
                self.current_result = None
                self._clear_comparison_table()
                self._show_initial_help()
        else:
            self.current_result = None
            self._clear_comparison_table()
            self._show_initial_help()
        if hasattr(self, 'notebook'):
            idx = data.get('notebook_idx')
            if isinstance(idx, int):
                idx = max(0, min(idx, self.notebook.count() - 1))
                self.notebook.setCurrentIndex(idx)
