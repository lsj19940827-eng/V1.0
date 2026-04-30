# -*- coding: utf-8 -*-
"""
暗涵水力计算面板 —— QWidget 版本

支持：矩形 / 圆拱直墙型
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
    QPushButton, QApplication, QRadioButton, QButtonGroup,
    QTableWidget,
)
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import QSizePolicy
from app_渠系计算前端.webview_compat import create_web_view, scroll_view_to_anchor

from qfluentwidgets import (
    ComboBox, PushButton, PrimaryPushButton, LineEdit,
    CheckBox, InfoBar, InfoBarPosition
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
    HB_RATIO_LIMIT,
)
from 圆拱直墙型暗涵设计 import quick_calculate_arch_culvert

from app_渠系计算前端.styles import P, S, W, E, BG, CARD, BD, T1, T2, INPUT_LABEL_STYLE, INPUT_SECTION_STYLE, INPUT_HINT_STYLE
from app_渠系计算前端.export_utils import (
    WORD_EXPORT_AVAILABLE, add_formula_to_doc, try_convert_formula_line, ask_open_file,
    create_styled_doc, doc_add_h1, doc_add_formula, doc_render_calc_text, doc_add_figure,
    doc_add_result_table, doc_add_styled_table, doc_add_table_caption, doc_add_body,
    create_engineering_report_doc, doc_add_eng_h, doc_add_eng_body,
    doc_render_calc_text_eng, update_doc_toc_via_com,
)
from app_渠系计算前端.report_meta import (
    ExportConfirmDialog, build_calc_purpose, REFERENCES_BASE, load_meta
)
from app_渠系计算前端.dxf_multi_export import (
    DxfExportCaseEntry,
    choose_scale_denom,
    export_combined_case_dxf,
    export_single_case_dxf,
    format_empty_export_warning,
    format_export_result_message,
    partition_valid_case_entries,
    select_case_entries,
    show_multi_case_dxf_dialog,
)
from app_渠系计算前端.culvert.dxf_export import (
    export_culvert_dxf,
    draw_culvert_dxf_on_msp,
    draw_culvert_comparison_table,
)
from app_渠系计算前端.culvert.comparison import (
    CULVERT_COMPARISON_SPEC,
    build_culvert_comparison_tables,
)
from app_渠系计算前端.section_comparison import (
    add_section_comparison_word_tables,
    build_table_clipboard_text,
    fill_comparison_table,
)
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
    normalize_increase_mode,
    resolve_increase_input,
)
from app_渠系计算前端.plot_title_utils import apply_flow_velocity_title
from app_渠系计算前端.tunnel.geometry import (
    arch_half_width as _arch_half_width,
    build_arch_geometry as _build_arch_geometry,
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


_CULVERT_RECT = "矩形"
_CULVERT_ARCH = "圆拱直墙型"
_CULVERT_FULL_NAME_MAP = {
    _CULVERT_RECT: "暗涵-矩形",
    _CULVERT_ARCH: "暗涵-圆拱直墙型",
}


def _normalize_culvert_section_type(value):
    """统一暗涵子类型口径，兼容旧项目里的历史文本。"""
    text = str(value or "").strip()
    if text in {"", "矩形", "暗涵", "暗渠", "矩形暗渠", "矩形暗涵", "暗涵-矩形"}:
        return _CULVERT_RECT
    if text in {"圆拱直墙型", "圆拱直墙型暗涵", "暗涵圆拱直墙型", "暗涵-圆拱直墙型", "隧洞-圆拱直墙型"}:
        return _CULVERT_ARCH
    return _CULVERT_RECT


def _culvert_full_name(section_type):
    """返回用于结果区和导出文案的暗涵全名。"""
    return _CULVERT_FULL_NAME_MAP.get(_normalize_culvert_section_type(section_type), _CULVERT_FULL_NAME_MAP[_CULVERT_RECT])


def _culvert_base_formula_items(section_type, include_optimal=False):
    """按暗涵子类型返回 Word 计算书基础公式。"""
    normalized = _normalize_culvert_section_type(section_type)
    items = [
        ('曼宁公式：', r'Q = \frac{1}{n} \cdot A \cdot R^{2/3} \cdot i^{1/2}'),
    ]
    if normalized == _CULVERT_ARCH:
        items.extend([
            ('水力半径：', r'R = \frac{A}{P}'),
            ('拱顶半径：', r'R_{拱} = \frac{B}{2\sin(\theta/2)}'),
            ('总高关系：', r'H = H_{直墙} + R_{拱} \cdot (1 - \cos(\theta/2))'),
            ('拱部面积：', r'A_{拱} = \frac{R_{拱}^{2}}{2} \cdot (\theta - \sin\theta)'),
        ])
        return items

    items.extend([
        ('过水面积：', r'A = B \cdot h'),
        ('湿周：', r'P = B + 2h'),
        ('水力半径：', r'R = \frac{A}{P} = \frac{Bh}{B+2h}'),
    ])
    if include_optimal:
        items.append(('优化目标：', r'\min A = B \times H \text{ (经济最优)}'))
    return items


class CulvertPanel(QWidget):
    """暗涵水力计算面板。"""
    data_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.input_params = {}
        self.current_result = None
        self._export_plain_text = ""
        self._cases = [self._default_case()]
        self._current_case_idx = 0
        self._all_results = []          # [(case_idx, input_params, result), ...]
        self._loading_case = False
        self._panel_key = "culvert"
        self._results_dirty = False
        self._has_rendered_results = False
        self._init_ui()
        self._setup_result_dirty_tracking()
        self._rebuild_case_tags()
        # 首次进入时按当前工况同步界面可见性，避免两套加大流量输入同时显示。
        self._load_case(self._current_case_idx)

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
        # 智能自适应宽度：根据内容 sizeHint 设置，不硬编码最大宽度
        scroll.setMinimumWidth(280)
        scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        splitter.addWidget(scroll)

        out_w = QWidget()
        self._build_output(out_w)
        splitter.addWidget(out_w)
        # 设置 stretch factor：输出区域优先扩展
        splitter.setStretchFactor(0, 0)  # 输入区域不主动扩展
        splitter.setStretchFactor(1, 1)  # 输出区域优先扩展
        # 初始宽度根据内容自适应
        preferred_width = inp_w.sizeHint().width() + 20  # 加上边距
        splitter.setSizes([max(300, min(preferred_width, 500)), 900])

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

        section_row = QHBoxLayout()
        section_row.addWidget(QLabel("断面类型:"))
        self.section_combo = ComboBox()
        self.section_combo.addItems([_CULVERT_RECT, _CULVERT_ARCH])
        self.section_combo.currentTextChanged.connect(self._on_section_type_changed)
        section_row.addWidget(self.section_combo, 1)
        fl.addLayout(section_row)

        # 通用参数
        self.Q_edit = self._field(fl, "设计流量 Q (m³/s):", "5.0")
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
        self._optional_title = self._slbl("【可选参数】")
        fl.addWidget(self._optional_title)
        self.bh_lbl, self.bh_edit = self._field2(fl, "指定宽深比 β:", "")
        self.hb_lbl, self.hb_edit = self._field2(fl, "指定高宽比 H/B:", "")
        self.B_lbl, self.B_edit = self._field2(fl, "指定底宽 B (m):", "")
        self._rect_hint_ratio = self._hint("(β 与 H/B 不可同时填写)")
        fl.addWidget(self._rect_hint_ratio)
        self._rect_hint_bottom = self._hint("(B 可单独填写，也可与 H/B 合用)")
        fl.addWidget(self._rect_hint_bottom)
        self._rect_hint_ratio_limit = QLabel("高宽比H/B、宽高比B/H 建议不超过1.2（超出时提醒，不作强制）")
        self._rect_hint_ratio_limit.setStyleSheet(f"font-family: 'Microsoft YaHei', sans-serif; font-size: 11px; color: #0066CC;")
        fl.addWidget(self._rect_hint_ratio_limit)
        self._rect_hint_optimal = QLabel("留空则自动搜索经济最优断面（B×H 最小）")
        self._rect_hint_optimal.setStyleSheet(f"font-family: 'Microsoft YaHei', sans-serif; font-size: 11px; color: #0066CC;")
        fl.addWidget(self._rect_hint_optimal)
        self._rect_hint_ref = QLabel("参考 GB 50288-2018 第11.2.5条")
        self._rect_hint_ref.setStyleSheet(f"font-family: 'Microsoft YaHei', sans-serif; font-size: 11px; color: {T2};")
        fl.addWidget(self._rect_hint_ref)

        self.theta_lbl, self.theta_edit = self._field2(fl, "圆心角 θ (度):", "180")
        self._arch_hint_theta = self._hint("(留空则按 180° 处理)")
        fl.addWidget(self._arch_hint_theta)
        self.arch_B_lbl, self.arch_B_edit = self._field2(fl, "指定底宽 B (m):", "")
        self._arch_hint_bottom = self._hint("(留空则自动搜索圆拱直墙型断面)")
        fl.addWidget(self._arch_hint_bottom)
        self.arch_H_straight_lbl, self.arch_H_straight_edit = self._field2(fl, "直墙高度 H直 (m):", "")
        self._arch_hint_wall = self._hint("(留空则由程序自动计算；填写时需同时填写底宽 B)")
        fl.addWidget(self._arch_hint_wall)
        self.theta_lbl.hide()
        self.theta_edit.hide()
        self._arch_hint_theta.hide()
        self.arch_B_lbl.hide()
        self.arch_B_edit.hide()
        self._arch_hint_bottom.hide()
        self.arch_H_straight_lbl.hide()
        self.arch_H_straight_edit.hide()
        self._arch_hint_wall.hide()

        fl.addWidget(self._sep())
        self.detail_cb = CheckBox("输出详细计算过程")
        self.detail_cb.setChecked(True)
        fl.addWidget(self.detail_cb)

        br = QHBoxLayout()
        self._calc_btn = PrimaryPushButton("计算"); self._calc_btn.setCursor(Qt.PointingHandCursor); self._calc_btn.clicked.connect(self._calculate)
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

    def _on_section_type_changed(self, section_type):
        """切换暗涵子类型时同步当前工况，并切换可见输入项。"""
        is_rect = _normalize_culvert_section_type(section_type) == _CULVERT_RECT
        rect_widgets = (
            self.bh_lbl, self.bh_edit,
            self.hb_lbl, self.hb_edit,
            self.B_lbl, self.B_edit,
            self._rect_hint_ratio,
            self._rect_hint_bottom,
            self._rect_hint_ratio_limit,
            self._rect_hint_optimal,
            self._rect_hint_ref,
        )
        arch_widgets = (
            self.theta_lbl, self.theta_edit,
            self._arch_hint_theta,
            self.arch_B_lbl, self.arch_B_edit,
            self._arch_hint_bottom,
            self.arch_H_straight_lbl, self.arch_H_straight_edit,
            self._arch_hint_wall,
        )
        for widget in rect_widgets:
            widget.setVisible(is_rect)
        for widget in arch_widgets:
            widget.setVisible(not is_rect)
        self._optional_title.setText("【矩形参数】" if is_rect else "【圆拱直墙型参数】")
        if not self._loading_case and 0 <= self._current_case_idx < len(self._cases):
            self._cases[self._current_case_idx]['section_type'] = _normalize_culvert_section_type(section_type)
            self._rebuild_case_tags()

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

        # Tab3: 工况对比
        t3 = QWidget(); t3l = QVBoxLayout(t3); t3l.setContentsMargins(5, 5, 5, 5)
        cmp_grp = QGroupBox("工况对比"); cmp_lay = QVBoxLayout(cmp_grp)
        self.comparison_hint = QLabel("请先完成计算，系统会在这里汇总各工况的关键水力结果和结构尺寸。")
        self.comparison_hint.setWordWrap(True)
        self.comparison_hint.setStyleSheet("color:#666; font-size:12px;")
        cmp_lay.addWidget(self.comparison_hint)
        cmp_lay.addWidget(QLabel("水力结果对比表"))
        self.comparison_hydraulic_table = QTableWidget(0, len(CULVERT_COMPARISON_SPEC.hydraulic_columns))
        self._configure_comparison_table(self.comparison_hydraulic_table)
        fill_comparison_table(
            self.comparison_hydraulic_table,
            CULVERT_COMPARISON_SPEC.hydraulic_columns,
            [],
        )
        cmp_lay.addWidget(self.comparison_hydraulic_table)
        cmp_lay.addWidget(QLabel("结构尺寸对比表"))
        self.comparison_dimension_table = QTableWidget(0, len(CULVERT_COMPARISON_SPEC.dimension_columns))
        self._configure_comparison_table(self.comparison_dimension_table)
        fill_comparison_table(
            self.comparison_dimension_table,
            CULVERT_COMPARISON_SPEC.dimension_columns,
            [],
        )
        cmp_lay.addWidget(self.comparison_dimension_table)
        self.comparison_table = self.comparison_hydraulic_table
        t3l.addWidget(cmp_grp)
        self.notebook.addTab(t3, "工况对比")

        self._show_initial_help()

    def _show_initial_help(self):
        sync_case_result_nav_bar(getattr(self, "_result_case_nav", None), [])
        h = HelpPageBuilder("暗涵水力计算", '请输入参数后点击“计算”按钮')
        h.section("断面特点")
        h.bullet_list([
            "高宽比H/B、宽高比B/H 建议不超过1.2（GB 50288-2018 第11.2.5条，超出时计算仍执行，仅给出提醒）",
            "最小净空面积 10%，最大 30%",
            "最小净空高度 0.4m",
        ])
        h.section("计算模式总览")
        h.table(
            ["可选参数填写方式", "程序行为"],
            [
                ["全部留空", "经济最优断面（B×H 最小，β 无硬约束），两阶段 β 扫描"],
                ["指定宽深比 β", "以 β=B/h 为约束，自动搜索最小B和H"],
                ["指定高宽比 H/B", "以 H=(H/B)×B 为约束，自动搜索最小B"],
                ["指定底宽 B", "固定B，自动搜索满足约束的H"],
                ["指定B + 高宽比 H/B", "固定B，H=(H/B)×B，直接验算"],
            ]
        )
        h.hint("宽深比 β 与高宽比 H/B 不可同时填写（过约束）")
        h.section("经济最优断面")
        h.text("当底宽和宽深比均留空时，自动搜索总面积 B×H 最小的断面（β 无硬约束）：")
        h.formula("min A = B × H", "优化目标：总截面面积最小")
        h.hint("明渠 β=2 对暗涵不再是最优——高宽比限制会将 H 强行拉大，浪费截面。实测可节省约 10~15% 材料。")
        h.text("搜索流程（全部留空时自动执行）：")
        h.numbered_list([
            ("遍历宽深比 β", "在 0.5~2.5 范围内逐步尝试，无需手动指定底宽"),
            ("由曼宁公式解析求解设计水深和底宽", "每个 β 对应唯一的水深 h 和底宽 B，无需迭代试算"),
            ("热启动割线法快速求解加大流量水深", "以相邻 β 的结果作为初始估计，自动收敛"),
            ("确定涵洞高度的可行范围", "综合净空面积 ≥10%、净空高度等约束，确定涵高下限；H/B≤1.2 为建议值不参与硬约束"),
            ("校核涵高上下限", "涵高上限由净空面积 ≤30% 决定；无可行涵高时自动跳过该 β"),
            ("两阶段搜索最优解", "先粗扫定位最优区间，再细扫精确求解，全程取总面积最小的方案"),
        ])
        h.hint("涵高下限由两个条件取最大值：净空面积不低于 10%、净空高度不小于 0.4m 或涵高的 1/6")
        h.hint("涵高上限由净空面积不超过 30% 决定；H/B≤1.2 为建议值，超出时结果中给出 ⚠ 提醒")
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
            "可指定宽深比或底宽",
            "留空则自动搜索经济最优断面（B×H 最小）",
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
        return self

    # ================================================================
    # 工况管理
    # ================================================================
    @staticmethod
    def _default_case():
        return {
            'custom_label': None,
            'section_type': _CULVERT_RECT,
            'theta_deg': '180',
            'Q': '5.0', 'n': '0.014', 'slope_inv': '2000',
            'v_min': '0.1', 'v_max': '100.0',
            'inc_checked': True, 'inc_pct': '', 'inc_mode': INCREASE_MODE_PERCENT, 'inc_q_text': '',
            'detail_checked': True,
            'bh': '', 'hb': '', 'B': '',
            'arch_B': '',
            'arch_H_straight': '',
        }

    @staticmethod
    def _ensure_case_defaults(case):
        """补齐旧项目缺失的暗涵家族字段。"""
        merged = copy.deepcopy(CulvertPanel._default_case())
        merged.update(case or {})
        merged['section_type'] = _normalize_culvert_section_type(merged.get('section_type', _CULVERT_RECT))
        merged['theta_deg'] = str(merged.get('theta_deg', '180') or '180')
        return merged

    def _save_current_case(self):
        if not (0 <= self._current_case_idx < len(self._cases)):
            return
        c = self._cases[self._current_case_idx]
        c['section_type'] = _normalize_culvert_section_type(self.section_combo.currentText())
        c['theta_deg'] = self.theta_edit.text()
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
        c['bh'] = self.bh_edit.text()
        c['hb'] = self.hb_edit.text()
        c['B'] = self.B_edit.text()
        c['arch_B'] = self.arch_B_edit.text()
        c['arch_H_straight'] = self.arch_H_straight_edit.text()

    def _load_case(self, idx):
        if not (0 <= idx < len(self._cases)):
            return
        c = self._ensure_case_defaults(self._cases[idx])
        self._cases[idx] = c
        self._loading_case = True
        self.section_combo.setCurrentText(_normalize_culvert_section_type(c.get('section_type', _CULVERT_RECT)))
        self.Q_edit.blockSignals(True)
        self.Q_edit.setText(c.get('Q', ''))
        self.Q_edit.blockSignals(False)
        self.n_edit.setText(c.get('n', '0.014'))
        self.slope_edit.setText(c.get('slope_inv', '2000'))
        self.vmin_edit.setText(c.get('v_min', '0.1'))
        self.vmax_edit.setText(c.get('v_max', '100.0'))
        self.inc_cb.setChecked(c.get('inc_checked', True))
        self.inc_edit.setText(c.get('inc_pct', ''))
        self.inc_q_edit.setText(c.get('inc_q_text', ''))
        self._set_increase_mode(c.get('inc_mode', INCREASE_MODE_PERCENT))
        self.detail_cb.setChecked(c.get('detail_checked', True))
        self.bh_edit.setText(c.get('bh', ''))
        self.hb_edit.setText(c.get('hb', ''))
        self.B_edit.setText(c.get('B', ''))
        self.theta_edit.setText(c.get('theta_deg', '180'))
        self.arch_B_edit.setText(c.get('arch_B', ''))
        self.arch_H_straight_edit.setText(c.get('arch_H_straight', ''))
        self._on_inc_toggle(None)
        self._on_section_type_changed(self.section_combo.currentText())
        self._loading_case = False

    def _switch_case(self, idx):
        if idx != self._current_case_idx:
            self._save_current_case()
            self._current_case_idx = idx
            self._load_case(idx)
            self._rebuild_case_tags()
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
        q_text = (case.get('Q', '') or '').strip() or '?'
        custom = (case.get('custom_label') or '').strip()
        section_type = _normalize_culvert_section_type(case.get('section_type', _CULVERT_RECT))
        family_name = _culvert_full_name(section_type)
        label = f"{custom or family_name} · Q={q_text}"
        tooltip_lines = [label, f"断面类型：{section_type}", f"设计流量 Q={q_text} m³/s"]
        if section_type == _CULVERT_ARCH:
            tooltip_lines.insert(2, f"圆心角 θ={case.get('theta_deg', '180') or '180'}°")
            h_straight = str(case.get('arch_H_straight', '') or '').strip()
            if h_straight:
                tooltip_lines.insert(3, f"直墙高度 H直={h_straight}m")
        return {
            "label": label,
            "tooltip": "\n".join(tooltip_lines),
        }

    def _case_label(self, case, idx):
        return self._case_view(case, idx)["label"]

    def _auto_label(self, case, idx):
        q_text = (case.get('Q', '') or '').strip() or '?'
        section_type = _normalize_culvert_section_type(case.get('section_type', _CULVERT_RECT))
        return f"{section_type}-Q{_sub(idx + 1)}={q_text}"

    def _on_case_renamed(self, idx, new_name):
        if 0 <= idx < len(self._cases):
            self._cases[idx]['custom_label'] = new_name
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
            self._clear_comparison_tables("参数已变更，请重新计算后查看工况对比。")

    def _mark_results_fresh(self):
        self._results_dirty = False
        self._has_rendered_results = bool(self._all_results)

    def _configure_comparison_table(self, table):
        """设置工况对比表的通用交互样式。"""
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.ExtendedSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.installEventFilter(self)

    def eventFilter(self, obj, event):
        """处理两张对比表的全选和复制快捷键。"""
        tables = {
            getattr(self, "comparison_hydraulic_table", None),
            getattr(self, "comparison_dimension_table", None),
        }
        if obj in tables and event.type() == QEvent.KeyPress:
            mods = event.modifiers()
            ctrl_only = bool(mods & Qt.ControlModifier) and not (
                mods & (Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
            )
            if ctrl_only and event.key() == Qt.Key_A:
                obj.selectAll()
                return True
            if ctrl_only and event.key() == Qt.Key_C:
                self._copy_comparison_selection_to_clipboard(obj)
                return True
        return super().eventFilter(obj, event)

    def _copy_comparison_selection_to_clipboard(self, table):
        """复制当前对比表选区到剪贴板。"""
        text, row_count, col_count = build_table_clipboard_text(table)
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
        """更新工况对比提示。"""
        if hasattr(self, "comparison_hint"):
            self.comparison_hint.setText(text)

    def _clear_comparison_tables(self, hint="请先完成计算，系统会在这里汇总各工况的关键水力结果和结构尺寸。"):
        """清空工况对比两张表。"""
        for table in (
            getattr(self, "comparison_hydraulic_table", None),
            getattr(self, "comparison_dimension_table", None),
        ):
            if table is not None:
                table.setRowCount(0)
        self._set_comparison_hint(hint)

    def _refresh_comparison_tables(self):
        """按成功工况刷新暗涵工况对比表。"""
        if not hasattr(self, "comparison_hydraulic_table"):
            return
        tables = build_culvert_comparison_tables(getattr(self, "_all_results", []))
        fill_comparison_table(
            self.comparison_hydraulic_table,
            CULVERT_COMPARISON_SPEC.hydraulic_columns,
            tables.hydraulic_rows,
        )
        fill_comparison_table(
            self.comparison_dimension_table,
            CULVERT_COMPARISON_SPEC.dimension_columns,
            tables.dimension_rows,
        )
        if tables.hydraulic_rows:
            self._set_comparison_hint("已汇总成功计算的工况；圆拱直墙型按暗涵断面口径显示。")
        else:
            self._set_comparison_hint("当前没有可汇总的成功工况，请检查计算结果。")

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

    def _case_result_nav_summary(self, case_idx, params, result):
        q_raw = params.get("Q", self._cases[case_idx].get("Q", ""))
        try:
            q_text = f"Q={float(q_raw):.3f}"
        except Exception:
            q_text = f"Q={str(q_raw).strip() or '?'}"
        if not result.get("success"):
            return "计算失败"
        section_type = _normalize_culvert_section_type(params.get("section_type", self._cases[case_idx].get("section_type", _CULVERT_RECT)))
        return f"{_culvert_full_name(section_type)} · {q_text}"

    def _build_case_nav_items(self):
        items = []
        for case_idx, params, result in self._all_results:
            items.append({
                "case_idx": case_idx,
                "anchor_id": make_case_result_anchor(self._panel_key, case_idx),
                "label": self._case_result_nav_label(case_idx),
                "summary": self._case_result_nav_summary(case_idx, params, result),
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
        keys = (
            'section_type', 'theta_deg',
            'n', 'slope_inv', 'v_min', 'v_max', 'inc_checked', 'inc_pct', 'inc_mode', 'inc_q_text',
            'detail_checked', 'bh', 'hb', 'B', 'arch_B', 'arch_H_straight',
        )
        for i, case in enumerate(self._cases):
            if i != self._current_case_idx:
                for k in keys:
                    case[k] = src[k]
        n_copied = len(self._cases) - 1
        if n_copied == 0:
            InfoBar.warning(title="提示", content="当前只有一个工况，无需复制",
                            parent=self._info_parent(), position=InfoBarPosition.TOP, duration=2000)
            return
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
        curr = self._cases[self._current_case_idx]
        for k in (
            'section_type', 'theta_deg',
            'n', 'slope_inv', 'v_min', 'v_max', 'inc_checked', 'inc_pct', 'inc_mode', 'inc_q_text',
            'detail_checked', 'bh', 'hb', 'B', 'arch_B', 'arch_H_straight',
        ):
            curr[k] = prev[k]
        self._load_case(self._current_case_idx)
        InfoBar.success(title="已复制", content=f"已从工况{self._current_case_idx}复制参数",
                        parent=self._info_parent(), position=InfoBarPosition.TOP, duration=2000)

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

    def _parse_case(self, case, case_num):
        """解析单个工况数据，返回 (input_params, kwargs) 或抛异常"""
        def _fv(key, label, must_positive=True):
            t = (case.get(key, '') or '').strip()
            if not t:
                raise ValueError(f"工况{case_num}: 请输入{label}")
            try:
                v = float(t)
            except ValueError:
                raise ValueError(f"工况{case_num}: {label}输入无效")
            if must_positive and v <= 0:
                raise ValueError(f"工况{case_num}: {label}必须大于0")
            return v

        def _fv_opt(key):
            t = (case.get(key, '') or '').strip()
            if not t:
                return None
            try:
                return float(t)
            except ValueError:
                return None

        def _fv_opt_labeled(key, label, must_nonnegative=False):
            """解析可选数字字段，非空但非法时给出明确提示。"""
            t = (case.get(key, '') or '').strip()
            if not t:
                return None
            try:
                value = float(t)
            except ValueError as exc:
                raise ValueError(f"工况{case_num}: {label}输入无效") from exc
            if must_nonnegative and value < 0:
                raise ValueError(f"工况{case_num}: {label}不能为负数")
            return value

        Q = _fv('Q', '设计流量 Q')
        n = _fv('n', '糙率 n')
        slope_inv = _fv('slope_inv', '水力坡降倒数')
        v_min = _fv('v_min', '不淤流速', must_positive=False)
        v_max = _fv('v_max', '不冲流速', must_positive=False)

        if v_min >= v_max:
            raise ValueError(f"工况{case_num}: 不淤流速必须小于不冲流速")

        use_increase = case.get('inc_checked', True)
        increase_resolution = resolve_increase_input(
            use_increase=use_increase,
            mode=case.get('inc_mode', INCREASE_MODE_PERCENT),
            design_q=Q,
            percent_text=case.get('inc_pct', ''),
            q_increased_text=case.get('inc_q_text', ''),
            disabled_percent=0.0,
        )
        manual_increase = increase_resolution.manual_increase_percent
        inc_mode = increase_resolution.mode
        section_type = _normalize_culvert_section_type(case.get('section_type', _CULVERT_RECT))

        input_params = {
            'section_type': section_type,
            'Q': Q, 'n': n, 'slope_inv': slope_inv,
            'v_min': v_min, 'v_max': v_max,
            'manual_increase': manual_increase,
            'use_increase': use_increase,
            'inc_mode': inc_mode,
            'inc_pct_text': case.get('inc_pct', ''),
            'inc_q_text': case.get('inc_q_text', ''),
        }
        if section_type == _CULVERT_ARCH:
            theta_text = (case.get('theta_deg', '') or '').strip()
            try:
                theta_deg = float(theta_text) if theta_text else 180.0
            except ValueError as exc:
                raise ValueError(f"工况{case_num}: 圆心角 θ 输入无效") from exc
            if theta_deg <= 0:
                raise ValueError(f"工况{case_num}: 圆心角 θ 必须大于0")
            input_params['theta_deg'] = theta_deg
            manual_B = _fv_opt('arch_B')
            manual_H_straight = _fv_opt_labeled('arch_H_straight', '直墙高度 H直', must_nonnegative=True)
            if manual_H_straight is not None and (manual_B is None or manual_B <= 0):
                raise ValueError(f"工况{case_num}: 填写直墙高度 H直 时必须同时填写底宽 B")
            input_params['manual_B'] = manual_B
            input_params['manual_H_straight'] = manual_H_straight
            return input_params

        manual_B = _fv_opt('B')
        target_BH_ratio = _fv_opt('bh')
        target_HB_ratio = _fv_opt('hb')
        if target_BH_ratio and target_HB_ratio:
            raise ValueError(f"工况{case_num}: 宽深比 β 与高宽比 H/B 不能同时指定")
        input_params['manual_B'] = manual_B
        input_params['target_BH_ratio'] = target_BH_ratio
        input_params['target_HB_ratio'] = target_HB_ratio
        return input_params

    def _calculate(self):
        self._prepare_calculation_run()
        errors = []

        for i, case in enumerate(self._cases):
            try:
                params = self._parse_case(case, i + 1)
            except (ValueError, TypeError) as ex:
                msg = str(ex)
                errors.append(msg)
                q_text = str(case.get('Q', '') or '').strip()
                try:
                    q_val = float(q_text) if q_text else 0.0
                except Exception:
                    q_val = 0.0
                self._all_results.append((
                    i,
                    {
                        'Q': q_val,
                        'section_type': _normalize_culvert_section_type(case.get('section_type', _CULVERT_RECT)),
                        'theta_deg': case.get('theta_deg', '180'),
                    },
                    {'success': False, 'error_message': msg}
                ))
                continue
            try:
                if params['section_type'] == _CULVERT_ARCH:
                    result = quick_calculate_arch_culvert(
                        Q=params['Q'], n=params['n'], slope_inv=params['slope_inv'],
                        v_min=params['v_min'], v_max=params['v_max'],
                        theta_deg=params['theta_deg'],
                        manual_B=params['manual_B'],
                        manual_H_straight=params['manual_H_straight'],
                        manual_increase_percent=params['manual_increase'],
                    )
                else:
                    result = quick_calculate_rectangular_culvert(
                        Q=params['Q'], n=params['n'], slope_inv=params['slope_inv'],
                        v_min=params['v_min'], v_max=params['v_max'],
                        target_BH_ratio=params['target_BH_ratio'],
                        target_HB_ratio=params['target_HB_ratio'],
                        manual_B=params['manual_B'],
                        manual_increase_percent=params['manual_increase'],
                    )
                self._all_results.append((i, params, result))
            except Exception as ex:
                msg = f"工况{i+1}: 计算出错 - {str(ex)}"
                errors.append(msg)
                self._all_results.append((i, params, {'success': False, 'error_message': msg}))

        if errors:
            InfoBar.error(title="输入错误", content="\n".join(errors),
                          parent=self._info_parent(), position=InfoBarPosition.TOP, duration=6000)
        if not self._all_results:
            return

        # 兼容旧属性
        _, first_params, first_result = self._all_results[0]
        self.input_params = first_params
        self.current_result = first_result

        # 显示结果
        self._display_all_results()
        self.data_changed.emit()

    def _show_error(self, title, msg):
        sync_case_result_nav_bar(getattr(self, "_result_case_nav", None), [])
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
        """在轻量测试替身上也能生成加大流量说明。"""
        builder = getattr(self, '_increase_summary_lines', None)
        if callable(builder):
            return builder(params, result)
        return CulvertPanel._increase_summary_lines(self, params, result)

    # ================================================================
    # 结果显示
    # ================================================================
    def _display_all_results(self):
        """显示所有工况计算结果"""
        _multi = len(self._all_results) > 1
        all_text_parts = []
        all_plain_parts = []

        for case_idx, params, result in self._all_results:
            section_type = _normalize_culvert_section_type(
                params.get('section_type', self._cases[case_idx].get('section_type', _CULVERT_RECT))
            ) if case_idx < len(self._cases) else _normalize_culvert_section_type(params.get('section_type'))
            family_name = _culvert_full_name(section_type)
            if not result.get('success'):
                q_raw = params.get('Q', '')
                try:
                    q_text = f"{float(q_raw):.3f} m³/s"
                except Exception:
                    q_text = '-'
                part = (
                    f"【工况 {case_idx + 1}｜{family_name}｜Q = {q_text}】\n\n"
                    f"计算失败："
                    f"{result.get('error_message', '未知错误')}\n"
                )
                all_text_parts.append(part)
                all_plain_parts.append(part)
                continue

            detail = self._cases[case_idx].get('detail_checked', True) if case_idx < len(self._cases) else True
            txt = self._build_culvert_result_text(params, result, detail, case_idx if _multi else None)

            import re as _re
            plain = _re.sub(
                r'\{\{HTML\}\}.*?\{\{/HTML\}\}',
                '{{NORM_TABLE_11_2_5}}',
                txt, flags=_re.DOTALL
            )
            all_text_parts.append(txt)
            all_plain_parts.append(plain)

        self._export_plain_text = "\n\n".join(all_plain_parts)
        full_html = plain_text_to_formula_html("\n\n".join(all_text_parts))
        load_formula_page(self.result_text, full_html)

        # 断面图：显示第一个成功结果（或当前工况）
        self._update_section_plot_all()

    def _display_all_results_legacy(self):
        """显示所有工况计算结果，并为多工况提供快捷定位。"""
        _multi = len(self._all_results) > 1
        all_plain_parts = []
        all_html_parts = []

        for case_idx, params, result in self._all_results:
            section_type = _normalize_culvert_section_type(
                params.get('section_type', self._cases[case_idx].get('section_type', _CULVERT_RECT))
            ) if case_idx < len(self._cases) else _normalize_culvert_section_type(params.get('section_type'))
            family_name = _culvert_full_name(section_type)
            if not result.get('success'):
                q_raw = params.get('Q', '')
                try:
                    q_text = f"{float(q_raw):.3f} m³/s"
                except Exception:
                    q_text = "-"
                plain = (
                    f"【工况 {case_idx + 1}｜{family_name}｜Q = {q_text}】\n\n"
                    f"计算失败：\n{result.get('error_message', '未知错误')}\n"
                )
                body_text = plain.split("\n\n", 1)[-1]
                body_html = plain_text_to_formula_body(body_text)
            else:
                detail = self._cases[case_idx].get('detail_checked', True) if case_idx < len(self._cases) else True
                txt = self._build_culvert_result_text(params, result, detail)
                export_txt = self._build_culvert_result_text(
                    params,
                    result,
                    detail,
                    case_idx if _multi else None,
                )
                import re as _re
                plain = _re.sub(
                    r'\{\{HTML\}\}.*?\{\{/HTML\}\}',
                    '{{NORM_TABLE_11_2_5}}',
                    export_txt, flags=_re.DOTALL
                )
                body_html = plain_text_to_formula_body(txt)
                body_html = prepend_result_summary_to_body("culvert", params, result, body_html)
            all_plain_parts.append(plain)
            all_html_parts.append(
                wrap_case_result_block(
                    self._panel_key,
                    case_idx,
                    f"工况 {case_idx + 1}",
                    body_html,
                    subtitle=self._case_result_nav_label(case_idx),
                    is_error=not result.get("success"),
                )
            )

        self._export_plain_text = "\n\n".join(all_plain_parts)
        nav_builder = getattr(self, "_build_case_nav_items", None)
        nav_items = nav_builder() if callable(nav_builder) else []
        nav_html = build_result_nav_bar(nav_items, hidden=True)
        combined_body = nav_html + "\n".join(all_html_parts)
        combined_head = build_result_navigation_head()
        load_formula_page(self.result_text, wrap_with_katex(combined_body, extra_head=combined_head))
        sync_case_result_nav_bar(getattr(self, "_result_case_nav", None), nav_items)

        self._mark_results_fresh()
        self._jump_to_case_result(self._current_case_idx, defer_until_load=True)
        self._update_section_plot_all()
        refresh_comparison = getattr(self, "_refresh_comparison_tables", None)
        if callable(refresh_comparison):
            refresh_comparison()

    def _display_all_results(self):
        return CulvertPanel._display_all_results_legacy(self)

    def _update_section_plot_all(self):
        """多工况断面图"""
        success_results = [(ci, p, r) for ci, p, r in self._all_results if r.get('success')]
        self.section_fig.clear()
        if not success_results:
            self.section_canvas.draw()
            return
        n = len(success_results)
        if n == 1:
            ci, p, r = success_results[0]
            axes = self.section_fig.subplots(1, 2)
            self._draw_case_section(axes[0], p, r, r['h_design'], r['V_design'], p['Q'], "设计流量")
            self._draw_case_section(axes[1], p, r, r['h_increased'], r['V_increased'], r['Q_increased'], "加大流量")
        else:
            ncols = min(n, 3)
            nrows = (n + ncols - 1) // ncols
            axes = self.section_fig.subplots(nrows, ncols, squeeze=False)
            for idx, (ci, p, r) in enumerate(success_results):
                row, col = divmod(idx, ncols)
                ax = axes[row][col]
                self._draw_case_section(ax, p, r, r['h_design'], r['V_design'], p['Q'], f"工况{ci+1} Q={p['Q']:.2f}")
            for idx in range(n, nrows * ncols):
                row, col = divmod(idx, ncols)
                axes[row][col].set_visible(False)
        self.section_fig.tight_layout()
        self.section_canvas.draw()

    def _draw_case_section(self, ax, params, result, h_w, velocity, flow, title):
        """按暗涵子类型绘制断面图。"""
        section_type = _normalize_culvert_section_type(params.get('section_type', _CULVERT_RECT))
        if section_type == _CULVERT_ARCH:
            theta_rad = math.radians(result.get('theta_deg', params.get('theta_deg', 180.0)))
            self._draw_arch(ax, result['B'], result['H_total'], theta_rad, h_w, velocity, flow, title)
            return
        self._draw_rect(ax, result['B'], result['H'], h_w, velocity, flow, title)

    def _update_result_display(self, result):
        """兼容单结果调用"""
        if not result['success']:
            self._show_error("计算失败", result.get('error_message', '未知错误'))
            return
        detail = self.detail_cb.isChecked()
        txt = self._build_culvert_result_text(self.input_params, result, detail)
        import re as _re
        self._export_plain_text = _re.sub(
            r'\{\{HTML\}\}.*?\{\{/HTML\}\}', '{{NORM_TABLE_11_2_5}}', txt, flags=_re.DOTALL
        )
        html = prepend_result_summary_to_html(
            "culvert",
            getattr(self, "input_params", {}),
            result,
            plain_text_to_formula_html(txt),
        )
        load_formula_page(self.result_text, html)

    def _build_arch_result_text(self, p, result, detail, case_num=None):
        """构建圆拱直墙型暗涵结果文本。"""
        Q, n = p['Q'], p['n']
        slope_inv = p['slope_inv']; i = 1.0 / slope_inv
        v_min, v_max = p['v_min'], p['v_max']
        family_name = _culvert_full_name(_CULVERT_ARCH)

        B = result.get('B', 0.0)
        H_total = result.get('H_total', 0.0)
        H_straight = result.get('H_straight', 0.0)
        theta_deg = result.get('theta_deg', p.get('theta_deg', 180.0))
        A_total = result.get('A_total', 0.0)
        HB_ratio = result.get('HB_ratio', H_total / B if B else 0.0)
        theta_rad = math.radians(theta_deg) if theta_deg else 0.0
        sin_half = math.sin(theta_rad / 2.0) if theta_rad else 0.0
        R_arch = (B / 2.0) / sin_half if B > 0 and abs(sin_half) > 1e-9 else 0.0
        H_arch = R_arch * (1.0 - math.cos(theta_rad / 2.0)) if R_arch else 0.0
        h_straight_source = "按用户输入固定" if result.get('used_manual_H_straight') else "H直 = H总 - H拱"

        h_d = result.get('h_design', 0.0)
        V_d = result.get('V_design', 0.0)
        A_d = result.get('A_design', 0.0)
        P_d = result.get('P_design', 0.0)
        R_hyd_d = result.get('R_hyd_design', 0.0)
        fb_pct_d = result.get('freeboard_pct_design', 0.0)
        fb_hgt_d = result.get('freeboard_hgt_design', 0.0)

        use_increase = p.get('use_increase', True)
        inc_pct = result.get('increase_percent', 0.0)
        Q_inc = result.get('Q_increased', 0.0)
        h_inc = result.get('h_increased', 0.0)
        V_inc = result.get('V_increased', 0.0)
        A_inc = result.get('A_increased', 0.0)
        P_inc = result.get('P_increased', 0.0)
        R_hyd_inc = result.get('R_hyd_increased', 0.0)
        fb_pct_inc = result.get('freeboard_pct_inc', 0.0)
        fb_hgt_inc = result.get('freeboard_hgt_inc', 0.0)

        fb_min_req = result.get('fb_min_required', 0.0)
        fb_area_val = fb_pct_inc if use_increase else fb_pct_d
        fb_hgt_val = fb_hgt_inc if use_increase else fb_hgt_d
        fb_area_ok = MIN_FREEBOARD_PCT_RECT * 100.0 - 0.1 <= fb_area_val <= MAX_FREEBOARD_PCT_RECT * 100.0 + 0.1
        fb_hgt_ok = fb_hgt_val >= fb_min_req - 1e-3
        fb_ok = fb_area_ok and fb_hgt_ok
        vel_ok = v_min <= V_d <= v_max

        o = []
        if case_num is not None:
            o.append(f"【工况 {case_num + 1}｜{family_name}｜Q = {Q:.3f} m³/s】")
            o.append("")
        o.append("=" * 70)
        o.append(f"              {family_name}水力计算结果")
        o.append("=" * 70)
        o.append("")

        if not detail:
            o.append("【输入参数】")
            o.append("")
            o.append(f"  1. 设计流量:")
            o.append(f"     Q = {Q:.3f} m³/s")
            o.append("")
            o.append(f"  2. 糙率:")
            o.append(f"     n = {n}")
            o.append("")
            o.append(f"  3. 水力坡降:")
            o.append(f"     = 1/{int(slope_inv)}")
            o.append("")
            o.append(f"  4. 不淤流速:")
            o.append(f"     = {v_min} m/s")
            o.append("")
            o.append(f"  5. 不冲流速:")
            o.append(f"     = {v_max} m/s")
            o.append("")

            o.append("【断面尺寸】")
            o.append(f"  宽度 B = {B:.2f} m")
            o.append(f"  高度 H = {H_total:.2f} m")
            o.append(f"  直墙高 H直 = {H_straight:.3f} m（{h_straight_source}）")
            o.append(f"  拱顶圆心角 θ = {theta_deg:.1f}°")
            o.append(f"  总面积 A总 = {A_total:.3f} m²")
            o.append("")

            o.append("【设计流量工况】")
            o.append(f"  设计水深 h = {h_d:.3f} m")
            o.append(f"  设计流速 V = {V_d:.3f} m/s")
            o.append(f"  净空高度 Fb = {fb_hgt_d:.3f} m")
            o.append(f"  净空比例 = {fb_pct_d:.1f}%")
            o.append("")

            if use_increase:
                o.append("【加大流量工况】")
                for line in CulvertPanel._safe_increase_summary_lines(self, p, result):
                    o.append(f"  {line}")
                o.append(f"  加大水深 h加大 = {h_inc:.3f} m")
                o.append(f"  加大流速 V加大 = {V_inc:.3f} m/s")
                o.append(f"  净空高度 Fb加大 = {fb_hgt_inc:.3f} m")
                o.append(f"  净空比例 = {fb_pct_inc:.1f}%")
                o.append("")

            o.append("【验证结果】")
            o.append(f"  流速验证: {'✓ 通过' if vel_ok else '✗ 未通过'}")
            o.append(f"  净空要求: 面积 10%~30%，净空高度 ≥ {fb_min_req:.3f} m")
            o.append(f"  净空验证: {'✓ 通过' if fb_ok else '✗ 需注意'}")
            o.append("")
            return "\n".join(o)

        o.append("【一、输入参数】")
        o.append("")
        o.append(f"  1. 设计流量:")
        o.append(f"     Q = {Q:.3f} m³/s")
        o.append("")
        o.append(f"  2. 糙率:")
        o.append(f"     n = {n}")
        o.append("")
        o.append(f"  3. 水力坡降:")
        o.append(f"     = 1/{int(slope_inv)}")
        o.append("")
        o.append(f"  4. 不淤流速:")
        o.append(f"     = {v_min} m/s")
        o.append("")
        o.append(f"  5. 不冲流速:")
        o.append(f"     = {v_max} m/s")
        o.append("")

        o.append("【二、断面尺寸】")
        o.append("")
        o.append("  1. 设计尺寸:")
        o.append(f"     宽度 B = {B:.2f} m")
        o.append(f"     总高 H = {H_total:.2f} m")
        o.append(f"     直墙高 H直 = {H_straight:.3f} m")
        o.append(f"     拱顶圆心角 θ = {theta_deg:.1f}°")
        o.append("")
        o.append("  2. 直墙高度来源:")
        if R_arch:
            o.append(f"     R拱 = (B/2) / sin(θ/2) = {R_arch:.3f} m")
            o.append(f"     H拱 = R拱 × (1 - cos(θ/2)) = {H_arch:.3f} m")
            o.append(f"     H直 = {H_straight:.3f} m（{h_straight_source}）")
        else:
            o.append(f"     H直 = {H_straight:.3f} m（{h_straight_source}）")
        o.append("")
        o.append("  3. 高宽比计算:")
        o.append(f"     H/B = {H_total:.2f} / {B:.2f} = {HB_ratio:.3f}")
        o.append("")
        o.append("  4. 断面总面积:")
        o.append(f"     A总 = {A_total:.3f} m²")
        o.append("")

        o.append("【三、设计流量工况】")
        o.append("")
        o.append("  1. 设计水深:")
        o.append(f"     h = {h_d:.3f} m")
        o.append("")
        o.append("  2. 过水面积与湿周:")
        o.append(f"     A = {A_d:.3f} m²")
        o.append(f"     χ = {P_d:.3f} m")
        o.append("")
        o.append("  3. 水力半径:")
        o.append(f"     R = A / χ = {A_d:.3f} / {P_d:.3f} = {R_hyd_d:.3f} m")
        o.append("")
        o.append("  4. 设计流速:")
        o.append(f"     V = (1/n) × R^(2/3) × i^(1/2)")
        o.append(f"       = (1/{n}) × {R_hyd_d:.3f}^(2/3) × {i:.6f}^(1/2)")
        if R_hyd_d > 0:
            o.append(f"       = {1/n:.2f} × {R_hyd_d**(2/3):.4f} × {math.sqrt(i):.6f}")
        o.append(f"       = {V_d:.3f} m/s")
        o.append("")
        o.append("  5. 净空情况:")
        o.append(f"     净空高度 Fb = {fb_hgt_d:.3f} m")
        o.append(f"     净空比例 = {fb_pct_d:.1f}%")
        o.append("")

        if use_increase:
            o.append("【四、加大流量工况】")
            o.append("")
            o.append("  1. 加大流量输入说明:")
            for line in CulvertPanel._safe_increase_summary_lines(self, p, result):
                o.append(f"     {line}")
            o.append("")
            o.append("  2. 加大水深:")
            o.append(f"     h加大 = {h_inc:.3f} m")
            o.append("")
            o.append("  3. 加大流量工况水力要素:")
            o.append(f"     A加大 = {A_inc:.3f} m²")
            o.append(f"     χ加大 = {P_inc:.3f} m")
            o.append(f"     R加大 = {R_hyd_inc:.3f} m")
            o.append(f"     V加大 = {V_inc:.3f} m/s")
            o.append("")
            o.append("  4. 加大流量工况净空:")
            o.append(f"     净空高度 Fb加大 = {fb_hgt_inc:.3f} m")
            o.append(f"     净空比例 = {fb_pct_inc:.1f}%")
            o.append("")

        section_num_fb = "五" if use_increase else "四"
        section_num_verify = "六" if use_increase else "五"
        o.append(f"【{section_num_fb}、净空校核】")
        o.append("")
        o.append("  按暗涵净空要求校核：")
        for line in str(result.get('fb_check_details', '')).splitlines():
            o.append(f"  {line}")
        o.append("")
        o.append("  本断面校核结果:")
        o.append(f"    净空面积比 = {fb_area_val:.1f}%")
        o.append(f"    要求 10%~30% → {'通过 ✓' if fb_area_ok else '需注意 ✗'}")
        o.append(f"    净空高度 = {fb_hgt_val:.3f} m")
        o.append(f"    要求 ≥ {fb_min_req:.3f} m → {'通过 ✓' if fb_hgt_ok else '需注意 ✗'}")
        o.append("")

        o.append(f"【{section_num_verify}、设计验证】")
        o.append("")
        o.append(f"  流速验证: {v_min} ≤ {V_d:.3f} ≤ {v_max} → {'通过 ✓' if vel_ok else '未通过 ✗'}")
        o.append(f"  净空验证: {'通过 ✓' if fb_ok else '需注意 ✗'}")
        return "\n".join(o)

    def _build_culvert_result_text(self, p, result, detail, case_num=None):
        """构建单个工况的结果文本，case_num 为 None 时不显示工况前缀"""
        section_type = _normalize_culvert_section_type(p.get('section_type', _CULVERT_RECT))
        if section_type == _CULVERT_ARCH:
            return self._build_arch_result_text(p, result, detail, case_num)

        Q, n = p['Q'], p['n']
        slope_inv = p['slope_inv']; i = 1.0 / slope_inv
        v_min, v_max = p['v_min'], p['v_max']
        is_optimal = result.get('is_optimal_section', False)
        target_HB = p.get('target_HB_ratio')
        family_name = _culvert_full_name(section_type)

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

        use_increase_val = p.get('use_increase', True)
        vel_ok = v_min <= V_d <= v_max
        if H <= 3.0:
            fb_req_by_rule = max(0.4, H / 6.0)
        else:
            fb_req_by_rule = 0.5
        if use_increase_val:
            fb_area_ok = 10.0 - 0.1 <= fb_pct_inc <= 30.0 + 0.1
            fb_hgt_ok = fb_hgt_inc >= fb_req_by_rule - 1e-3
        else:
            fb_area_ok = 10.0 - 0.1 <= fb_pct_d <= 30.0 + 0.1
            fb_hgt_ok = fb_hgt_d >= fb_req_by_rule - 1e-3
        fb_ok = fb_area_ok and fb_hgt_ok

        o = []
        if case_num is not None:
            o.append(f"【工况 {case_num + 1}｜{family_name}｜Q = {Q:.3f} m³/s】")
            o.append("")
        o.append("=" * 70)
        if is_optimal:
            o.append(f"              {family_name}水力计算结果（经济最优断面）")
        elif target_HB:
            o.append(f"              {family_name}水力计算结果（指定高宽比 H/B={target_HB:.2f}）")
        else:
            o.append(f"              {family_name}水力计算结果")
        o.append("=" * 70)
        o.append("")

        if not detail:
            # ── 简要输出 ──
            o.append("【输入参数】")
            o.append("")
            o.append(f"  1. 设计流量:")
            o.append(f"     Q = {Q:.3f} m³/s")
            o.append("")
            o.append(f"  2. 糙率:")
            o.append(f"     n = {n}")
            o.append("")
            o.append(f"  3. 水力坡降:")
            o.append(f"     = 1/{int(slope_inv)}")
            o.append("")
            o.append(f"  4. 不淤流速:")
            o.append(f"     = {v_min} m/s")
            o.append("")
            o.append(f"  5. 不冲流速:")
            o.append(f"     = {v_max} m/s")
            o.append("")

            o.append("【断面尺寸】")
            if is_optimal:
                o.append("  ★ 采用经济最优断面（B×H 最小）")
                o.append(f"    （B={B:.2f}m，H={H:.2f}m，A={B*H:.3f}m²，β={BH_ratio:.3f}）")
            elif target_HB:
                o.append(f"  ★ 按指定高宽比 H/B={target_HB:.2f} 计算")
            o.append(f"  宽度 B = {B:.2f} m")
            o.append(f"  高度 H = {H:.2f} m")
            hb_ratio_ok = result.get('hb_ratio_ok', True)
            bh_box_ratio_ok = result.get('bh_box_ratio_ok', True)
            BH_box = B / H if H > 0 else 0
            o.append(f"  宽深比 β = B/h = {BH_ratio:.3f}")
            o.append(f"  高宽比 H/B = {HB_ratio:.3f}" + ("" if hb_ratio_ok else "  ⚠ 超出建议值1.2"))
            o.append(f"  宽高比 B/H = {BH_box:.3f}" + ("" if bh_box_ratio_ok else "  ⚠ 超出建议值1.2"))
            if not hb_ratio_ok:
                o.append('{{HTML}}<div style="margin:2px 0 2px 16px;padding:3px 10px;background:#FFF3E0;border-left:3px solid #FF8C00;border-radius:3px;font-size:13px;color:#E65100;"><b>⚠</b> 高宽比偏大：H/B = ' + f'{HB_ratio:.3f}' + '，建议 H/B ≤ 1.2（GB 50288-2018 第11.2.5条建议值）</div>')
                o.append('{{/HTML}}')
            if not bh_box_ratio_ok:
                o.append('{{HTML}}<div style="margin:2px 0 2px 16px;padding:3px 10px;background:#FFF3E0;border-left:3px solid #FF8C00;border-radius:3px;font-size:13px;color:#E65100;"><b>⚠</b> 宽高比偏大：B/H = ' + f'{BH_box:.3f}' + '，建议 B/H ≤ 1.2（断面宽浅，请确认结构合理性）</div>')
                o.append('{{/HTML}}')
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
                for line in CulvertPanel._safe_increase_summary_lines(self, p, result):
                    o.append(f"  {line}")
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
            o.append("")
            o.append(f"  1. 设计流量:")
            o.append(f"     Q = {Q:.3f} m³/s")
            o.append("")
            o.append(f"  2. 糙率:")
            o.append(f"     n = {n}")
            o.append("")
            o.append(f"  3. 水力坡降:")
            o.append(f"     = 1/{int(slope_inv)}")
            o.append("")
            o.append(f"  4. 不淤流速:")
            o.append(f"     = {v_min} m/s")
            o.append("")
            o.append(f"  5. 不冲流速:")
            o.append(f"     = {v_max} m/s")
            o.append("")

            o.append("【二、断面尺寸】")
            o.append("")
            o.append("  1. 设计尺寸:")
            if is_optimal:
                o.append("     ★★★ 采用经济最优断面 ★★★")
                o.append("     (当底宽和宽深比均留空时，自动搜索总面积 B×H 最小的断面)")
                o.append(f"     最优断面: B = {B:.2f} m，H = {H:.2f} m，A = {B*H:.3f} m²")
                o.append(f"     实际 β = B/h = {B:.2f}/{h_d:.3f} = {BH_ratio:.3f}")
                o.append(f"     洞高 H = {H:.2f} m（满足所有净空约束的最小洞高）")
                o.append(f"     断面面积 A = B×H = {B:.2f}×{H:.2f} = {B*H:.3f} m²（满足约束的最小值）")
            elif target_HB:
                o.append(f"     ★★★ 按指定高宽比计算 ★★★")
                o.append(f"     指定 H/B = {target_HB:.2f}，涵洞高度 H = {target_HB:.2f} × B")
            o.append(f"     宽度 B = {B:.2f} m")
            o.append(f"     高度 H = {H:.2f} m")
            o.append("")

            o.append("  2. 宽深比计算:")
            o.append(f"     β = B / h")
            o.append(f"       = {B:.2f} / {h_d:.3f}")
            o.append(f"       = {BH_ratio:.3f}")
            if is_optimal:
                o.append("     (经济最优，β 无硬约束）")
            o.append("")

            hb_ratio_ok_d = result.get('hb_ratio_ok', True)
            bh_box_ratio_ok_d = result.get('bh_box_ratio_ok', True)
            BH_box_d = B / H if H > 0 else 0
            o.append("  3. 高宽比计算:")
            o.append(f"     H/B = {H:.2f} / {B:.2f} = {HB_ratio:.3f}" + ("" if hb_ratio_ok_d else "  ⚠"))
            o.append(f"     B/H = {B:.2f} / {H:.2f} = {BH_box_d:.3f}" + ("" if bh_box_ratio_ok_d else "  ⚠"))
            o.append("     (建议值: H/B 及 B/H 宜不超过1.2，GB 50288-2018 第11.2.5条)")
            if not hb_ratio_ok_d:
                o.append('{{HTML}}<div style="margin:2px 0 2px 24px;padding:3px 10px;background:#FFF3E0;border-left:3px solid #FF8C00;border-radius:3px;font-size:13px;color:#E65100;"><b>⚠</b> 高宽比 H/B = ' + f'{HB_ratio:.3f}' + ' 超出建议值1.2</div>')
                o.append('{{/HTML}}')
            if not bh_box_ratio_ok_d:
                o.append('{{HTML}}<div style="margin:2px 0 2px 24px;padding:3px 10px;background:#FFF3E0;border-left:3px solid #FF8C00;border-radius:3px;font-size:13px;color:#E65100;"><b>⚠</b> 宽高比 B/H = ' + f'{BH_box_d:.3f}' + ' 超出建议值1.2</div>')
                o.append('{{/HTML}}')
            o.append("")

            o.append("  4. 总断面积计算:")
            o.append(f"     A总 = B × H")
            o.append(f"        = {B:.2f} × {H:.2f}")
            o.append(f"        = {A_total:.3f} m²")
            o.append("")

            o.append("【三、设计流量工况】")
            o.append("")
            o.append("  1. 设计水深计算:")
            o.append(f"     根据设计流量 Q = {Q:.3f} m³/s 和底宽 B = {B:.2f} m，利用曼宁公式反算水深:")
            o.append(f"     h = {h_d:.3f} m")
            o.append("")

            o.append("  2. 过水面积计算:")
            o.append(f"     A = B × h")
            o.append(f"       = {B:.2f} × {h_d:.3f}")
            o.append(f"       = {A_d:.3f} m²")
            o.append("")

            o.append("  3. 湿周计算:")
            o.append(f"     χ = B + 2×h")
            o.append(f"       = {B:.2f} + 2×{h_d:.3f}")
            o.append(f"       = {B:.2f} + {2*h_d:.3f}")
            o.append(f"       = {P_d:.3f} m")
            o.append("")

            o.append("  4. 水力半径计算:")
            o.append(f"     R = A / χ")
            o.append(f"       = {A_d:.3f} / {P_d:.3f}")
            o.append(f"       = {R_hyd_d:.3f} m")
            o.append("")

            o.append("  5. 设计流速计算 (曼宁公式):")
            o.append(f"     V = (1/n) × R^(2/3) × i^(1/2)")
            o.append(f"       = (1/{n}) × {R_hyd_d:.3f}^(2/3) × {i:.6f}^(1/2)")
            if R_hyd_d > 0:
                o.append(f"       = {1/n:.2f} × {R_hyd_d**(2/3):.4f} × {math.sqrt(i):.6f}")
            o.append(f"       = {V_d:.3f} m/s")
            o.append("")

            Q_chk = A_d * V_d
            o.append("  6. 计算流量验证:")
            o.append(f"     Q计算 = A × V")
            o.append(f"          = {A_d:.3f} × {V_d:.3f}")
            o.append(f"          = {Q_chk:.3f} m³/s")
            if Q > 0:
                o.append(f"     误差 = {abs(Q_chk - Q) / Q * 100:.2f}%")
            o.append("")

            o.append("  7. 净空高度计算:")
            o.append(f"      Fb = H - h")
            o.append(f"         = {H:.2f} - {h_d:.3f}")
            o.append(f"         = {fb_hgt_d:.3f} m")
            o.append("")

            o.append("  8. 净空面积比计算:")
            o.append(f"      PA = (H - h) / H × 100%")
            o.append(f"         = ({H:.2f} - {h_d:.3f}) / {H:.2f} × 100%")
            o.append(f"         = {fb_pct_d:.1f}%")
            o.append("")

            if use_increase_val:
                o.append("【四、加大流量工况】")
                o.append("")
                o.append("  1. 加大流量输入说明:")
                for line in CulvertPanel._safe_increase_summary_lines(self, p, result):
                    o.append(f"      {line}")
                o.append("")
                o.append("  2. 加大水深计算:")
                o.append(f"      根据加大流量 Q加大 = {Q_inc:.3f} m³/s 和底宽 B = {B:.2f} m，利用曼宁公式反算水深:")
                o.append(f"      h加大 = {h_inc:.3f} m")
                o.append("")

                A_inc = B * h_inc
                chi_inc = B + 2 * h_inc
                R_inc = A_inc / chi_inc if chi_inc > 0 else 0

                o.append("  3. 加大流量工况过水面积:")
                o.append(f"      A加大 = B × h加大")
                o.append(f"           = {B:.2f} × {h_inc:.3f}")
                o.append(f"           = {A_inc:.3f} m²")
                o.append("")

                o.append("  4. 加大流量工况湿周:")
                o.append(f"      χ加大 = B + 2×h加大")
                o.append(f"           = {B:.2f} + 2×{h_inc:.3f}")
                o.append(f"           = {B:.2f} + {2 * h_inc:.3f}")
                o.append(f"           = {chi_inc:.3f} m")
                o.append("")

                o.append("  6. 加大流量工况水力半径:")
                o.append(f"      R加大 = A加大 / χ加大")
                o.append(f"           = {A_inc:.3f} / {chi_inc:.3f}")
                o.append(f"           = {R_inc:.3f} m")
                o.append("")

                o.append("  7. 加大流量工况流速 (曼宁公式):")
                o.append(f"      V加大 = (1/n) × R^(2/3) × i^(1/2)")
                o.append(f"           = (1/{n}) × {R_inc:.3f}^(2/3) × {i:.6f}^(1/2)")
                if R_inc > 0:
                    o.append(f"           = {1/n:.2f} × {R_inc**(2/3):.4f} × {math.sqrt(i):.6f}")
                o.append(f"           = {V_inc:.3f} m/s")
                o.append("")

                Q_chk_inc = V_inc * A_inc
                o.append("  8. 流量校核:")
                o.append(f"      Q计算 = A加大 × V加大")
                o.append(f"           = {A_inc:.3f} × {V_inc:.3f}")
                o.append(f"           = {Q_chk_inc:.3f} m³/s")
                if Q_inc > 0:
                    o.append(f"      误差 = {abs(Q_chk_inc - Q_inc) / Q_inc * 100:.2f}%")
                o.append("")

                o.append("  9. 加大流量工况净空:")
                o.append(f"      净空高度 Fb加大 = H - h加大 = {H:.2f} - {h_inc:.3f} = {fb_hgt_inc:.3f} m")
                o.append(f"      净空面积 PA加大 = (H - h加大) / H × 100% = {fb_pct_inc:.1f}%")
                o.append("")

            # 净空验证
            section_num_fb = "五" if use_increase_val else "四"
            o.append(f"【{section_num_fb}、净空验证】")
            o.append("")
            o.append("  根据《灌溉与排水工程设计标准》GB 50288-2018 第11.2.5条：")
            o.append("  涵洞横断面形式应符合下列规定：")
            o.append("    1 小流量涵洞宜采用预制圆管涵；")
            o.append("    2 无压涵洞当洞顶填土高度较小时宜选用盖板涵洞或箱涵，")
            o.append("      涵顶填土高度较大时宜采用城门洞型、蛋型（高升拱）或管涵；")
            o.append("    3 有压涵洞应选用管涵或箱涵；")
            o.append("    4 拱涵或四铰涵不应使用于沉陷量大的地基上；")
            o.append("    5 无压涵洞内设计水面以上的净空面积宜取涵洞断面面积的10%~30%，")
            o.append("      且涵洞内顶点至最高水面之间的净空高度应符合表11.2.5的规定，")
            o.append("      并不应小于0.4m。")
            o.append("")
            o.append('{{HTML}}<div class="norm-table-title">表 11.2.5&emsp;无压涵洞的净空高度(m)</div>')
            o.append('<table class="norm-table">')
            o.append('<tr><th rowspan="2">进口净高</th><th colspan="3">净空高度</th></tr>')
            o.append('<tr><th>圆涵</th><th>拱涵</th><th>矩形涵洞</th></tr>')
            o.append('<tr><td>≤3</td><td>≥D/4</td><td>≥D/4</td><td>≥D/6</td></tr>')
            o.append('<tr><td>&gt;3</td><td>≥0.75</td><td>≥0.75</td><td>≥0.5</td></tr>')
            o.append('</table>')
            o.append('<div class="norm-table-note">注：表中D为涵洞内侧高度或者圆涵内径(m)。</div>')
            o.append('{{/HTML}}')
            o.append("")
            o.append("  本涵洞净空验证（矩形涵洞）：")
            if H <= 3.0:
                o.append(f"    进口净高 H = {H:.2f}m ≤ 3m")
                o.append(f"    查表：净空高度应 ≥ D/6 = {H:.2f}/6 = {H/6:.3f}m")
                o.append(f"    同时不应小于0.4m")
                o.append(f"    → 要求净空高度 ≥ max(0.4, {H/6:.3f}) = {fb_req_by_rule:.3f}m")
            else:
                o.append(f"    进口净高 H = {H:.2f}m > 3m")
                o.append(f"    查表：净空高度应 ≥ 0.5m")
                o.append(f"    → 要求净空高度 ≥ 0.5m")
            o.append("")

            fb_pct_verify = fb_pct_inc if use_increase_val else fb_pct_d
            fb_hgt_verify = fb_hgt_inc if use_increase_val else fb_hgt_d
            fb_cond_label = "加大流量工况" if use_increase_val else "设计流量工况"
            o.append(f"  净空验证结果（{fb_cond_label}）：")
            o.append(f"  a) 净空面积验证: 10% ≤ {fb_pct_verify:.1f}% ≤ 30%")
            o.append(f"     → {'通过 ✓' if fb_area_ok else '未通过 ✗'}")
            o.append(f"  b) 净空高度验证: {fb_hgt_verify:.3f}m ≥ {fb_req_by_rule:.3f}m")
            o.append(f"     → {'通过 ✓' if fb_hgt_ok else '未通过 ✗'}")
            o.append("")

            # 综合验证
            section_num_sum = "六" if use_increase_val else "五"
            o.append(f"【{section_num_sum}、综合验证】")
            o.append("")
            o.append(f"  1. 流速验证:")
            o.append(f"     范围要求: {v_min} ≤ V ≤ {v_max} m/s")
            o.append(f"     设计流速: V = {V_d:.3f} m/s")
            o.append(f"     结果: {'通过 ✓' if vel_ok else '未通过 ✗'}")
            o.append("")
            o.append(f"  2. 净空面积验证:")
            o.append(f"     规范要求: 10% ≤ PA ≤ 30%")
            o.append(f"     计算结果: PA = {fb_pct_verify:.1f}%")
            o.append(f"     结果: {'通过 ✓' if fb_area_ok else '未通过 ✗'}")
            o.append("")
            o.append(f"  3. 净空高度验证:")
            o.append(f"     规范要求: Fb ≥ {fb_req_by_rule:.3f} m")
            o.append(f"     计算结果: Fb = {fb_hgt_verify:.3f} m")
            o.append(f"     结果: {'通过 ✓' if fb_hgt_ok else '未通过 ✗'}")
            o.append("")

        o.append("=" * 70)
        all_checks_ok = vel_ok and fb_area_ok and fb_hgt_ok
        if is_optimal:
            o.append(f"  综合验证结果: {'全部通过 ✓' if all_checks_ok else '未通过 ✗'} (经济最优断面)")
        else:
            o.append(f"  综合验证结果: {'全部通过 ✓' if all_checks_ok else '未通过 ✗'}")
        o.append("=" * 70)
        return "\n".join(o)

    # ================================================================
    # 断面图
    # ================================================================
    def _update_section_plot(self, result):
        self.section_fig.clear()
        if not result.get('success'):
            self.section_canvas.draw(); return

        Q = self.input_params['Q']
        Q_inc = result['Q_increased']
        axes = self.section_fig.subplots(1, 2)
        self._draw_case_section(axes[0], self.input_params, result, result['h_design'], result['V_design'], Q, "设计流量")
        self._draw_case_section(axes[1], self.input_params, result, result['h_increased'], result['V_increased'], Q_inc, "加大流量")
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
        apply_flow_velocity_title(ax, title, Q, V, fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='brown', lw=3)

    def _draw_arch(self, ax, B, H_total, theta_rad, h_w, V, Q, title):
        """绘制圆拱直墙型暗涵断面。"""
        geom = _build_arch_geometry(B, H_total, theta_rad)
        start_angle = geom['start_angle']
        end_angle = geom['end_angle']
        arch_theta = np.linspace(start_angle, end_angle, 101)
        arch_x = geom['center'][0] + geom['R_arch'] * np.cos(arch_theta)
        arch_y = geom['center'][1] + geom['R_arch'] * np.sin(arch_theta)
        H_straight = geom['H_straight']
        ax.plot([-B/2, -B/2], [0, H_straight], 'k-', lw=2)
        ax.plot([B/2, B/2], [0, H_straight], 'k-', lw=2)
        ax.plot([-B/2, B/2], [0, 0], 'k-', lw=2)
        ax.plot(arch_x, arch_y, 'k-', lw=2)
        if h_w > 0:
            if h_w <= H_straight:
                wx = [-B/2, -B/2, B/2, B/2]
                wy = [0, h_w, h_w, 0]
                ax.fill(wx, wy, color='lightblue', alpha=0.7)
            else:
                rect_x = [-B/2, -B/2, B/2, B/2]
                rect_y = [0, H_straight, H_straight, 0]
                ax.fill(rect_x, rect_y, color='lightblue', alpha=0.7)
                fill_theta = np.linspace(geom['start_angle'], geom['end_angle'], 101)
                fill_x = geom['center'][0] + geom['R_arch'] * np.cos(fill_theta)
                fill_y = geom['center'][1] + geom['R_arch'] * np.sin(fill_theta)
                mask = fill_y <= h_w + 1e-9
                if np.any(mask):
                    arch_fill_x = fill_x[mask]
                    arch_fill_y = fill_y[mask]
                    polygon_x = np.concatenate(([-_arch_half_width(geom, h_w)], arch_fill_x, [_arch_half_width(geom, h_w)]))
                    polygon_y = np.concatenate(([h_w], arch_fill_y, [h_w]))
                    ax.fill(polygon_x, polygon_y, color='lightblue', alpha=0.7)
            water_half_width = _arch_half_width(geom, h_w)
            ax.plot([-water_half_width, water_half_width], [h_w, h_w], 'b-', lw=1.5)
        ax.annotate('', xy=(B/2, -0.08*H_total), xytext=(-B/2, -0.08*H_total), arrowprops=dict(arrowstyle='<->', color='gray', lw=1.5))
        ax.text(0, -0.16*H_total, f'B={B:.2f}m', ha='center', fontsize=9, color='gray')
        ax.annotate('', xy=(B/2+0.1*B, H_total), xytext=(B/2+0.1*B, 0), arrowprops=dict(arrowstyle='<->', color='purple', lw=1.5))
        ax.text(B/2+0.18*B, H_total/2, f'H={H_total:.2f}m', fontsize=8, color='purple', rotation=90, va='center')
        if H_straight > 1e-9:
            ax.annotate('', xy=(-B/2-0.1*B, H_straight), xytext=(-B/2-0.1*B, 0), arrowprops=dict(arrowstyle='<->', color='teal', lw=1.3))
            ax.text(-B/2-0.18*B, H_straight/2, f'H直={H_straight:.2f}m', fontsize=8, color='teal', rotation=90, va='center', ha='center')
        # 水深标注放在 H直 外侧，避免两个竖向尺寸重叠。
        if h_w > 0:
            ax.annotate('', xy=(-B/2-0.28*B, h_w), xytext=(-B/2-0.28*B, 0), arrowprops=dict(arrowstyle='<->', color='blue', lw=1.5))
            ax.text(-B/2-0.36*B, h_w/2, f'h={h_w:.2f}m', ha='right', fontsize=8, color='blue', rotation=90, va='center')
        ax.text(0.04 * B, H_total * 0.98, f'θ={math.degrees(theta_rad):.0f}°', fontsize=9, color='purple')
        ax.set_xlim(-B*1.05, B*0.9)
        ax.set_ylim(-H_total*0.3, H_total*1.2)
        ax.set_aspect('equal')
        apply_flow_velocity_title(ax, title, Q, V, fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='brown', lw=3)

    # ================================================================
    # 清空 / 导出
    # ================================================================
    def _clear(self):
        self._save_current_case()
        self._all_results = []
        self._results_dirty = False
        self._has_rendered_results = False
        self._rebuild_case_tags()
        self._update_calc_btn_text()
        self._show_initial_help()
        self.section_fig.clear(); self.section_canvas.draw()
        self._refresh_increase_hint()
        self.current_result = None
        self._export_plain_text = ""
        self._clear_comparison_tables()

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
                InfoBar.success("导出成功", f"DXF已保存到: {filepath}", parent=self._info_parent(), duration=4000, position=InfoBarPosition.TOP)
                ask_open_file(filepath, self._info_parent())
            except ImportError as e:
                InfoBar.error("缺少依赖", str(e), parent=self._info_parent(), duration=6000, position=InfoBarPosition.TOP)
            except PermissionError:
                InfoBar.error("文件被占用", "无法写入文件，请关闭已打开的同名DXF文件。", parent=self._info_parent(), duration=8000, position=InfoBarPosition.TOP)
            except Exception as e:
                InfoBar.error("导出失败", f"DXF导出失败: {str(e)}", parent=self._info_parent(), duration=5000, position=InfoBarPosition.TOP)
            return

        dialog_result = show_multi_case_dxf_dialog(self._info_parent(), "暗涵断面", case_entries, self._current_case_idx)
        if dialog_result is None:
            return
        selected_entries = select_case_entries(case_entries, dialog_result.scope, self._current_case_idx, dialog_result.checked_case_indexes)
        valid_entries, invalid_entries = partition_valid_case_entries(selected_entries)
        if not valid_entries:
            InfoBar.warning("提示", format_empty_export_warning(invalid_entries), parent=self._info_parent(), duration=4000, position=InfoBarPosition.TOP)
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
        result_map = {case_idx: (params, result) for case_idx, params, result in self._all_results}
        for case_idx, case in enumerate(self._cases):
            params, result = result_map.get(case_idx, ({}, None))
            invalid_reason = None
            if results_dirty and self._all_results:
                invalid_reason = "结果已失效"
            elif result is None:
                invalid_reason = "无计算结果"
            elif not result.get("success"):
                invalid_reason = "计算失败"
            entries.append(
                DxfExportCaseEntry(
                    case_idx=case_idx,
                    label=self._case_label(case, case_idx),
                    input_params=params or {},
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
        content = "参数已变更，请先重新计算后再导出。" if entry is not None and entry.invalid_reason == "结果已失效" else "请先进行计算后再导出。"
        InfoBar.warning("提示", content, parent=self._info_parent(), duration=3000, position=InfoBarPosition.TOP)

    def _single_dxf_default_name(self, entry):
        result = entry.result or {}
        input_params = entry.input_params or {}
        section_type = _normalize_culvert_section_type(input_params.get('section_type', _CULVERT_RECT))
        if section_type == _CULVERT_ARCH:
            return f"暗涵-圆拱直墙型断面_B{result.get('B', 0.0):.2f}xH{result.get('H_total', 0.0):.2f}.dxf"
        return f"暗涵-矩形断面_B{result.get('B', 0.0):.2f}xH{result.get('H', 0.0):.2f}.dxf"

    def _combined_dxf_default_name(self, count):
        return f"暗涵断面_{count}个工况_合并.dxf"

    def _choose_dxf_filepath(self, default_name):
        filepath, _ = QFileDialog.getSaveFileName(self, "保存DXF文件", default_name, "DXF文件 (*.dxf);;所有文件 (*.*)")
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
        export_single_case_dxf(
            filepath,
            entry,
            scale,
            draw_culvert_dxf_on_msp,
            draw_summary_table=draw_culvert_comparison_table,
        )
        return filepath

    def _export_combined_dxf_entries(self, entries, scale_denom):
        filepath = self._choose_dxf_filepath(self._combined_dxf_default_name(len(entries)))
        if not filepath:
            return None
        return export_combined_case_dxf(
            filepath,
            entries,
            scale_denom,
            draw_culvert_dxf_on_msp,
            draw_summary_table=draw_culvert_comparison_table,
        )

    def _export_report(self):
        if not self.current_result or not self.current_result.get('success'):
            InfoBar.warning("提示", "请先进行计算后再导出。", parent=self._info_parent(), duration=3000, position=InfoBarPosition.TOP); return
        filepath, _ = QFileDialog.getSaveFileName(self, "保存报告", "", "文本文件 (*.txt);;所有文件 (*.*)")
        if not filepath: return
        try:
            content = self._export_plain_text if self._export_plain_text else ''
            # 纯文本导出时将占位标记替换为文本表格
            _txt_table = (
                "  表 11.2.5  无压涵洞的净空高度(m)\n"
                "  进口净高    圆涵      拱涵      矩形涵洞\n"
                "    ≤3       ≥D/4      ≥D/4       ≥D/6\n"
                "    >3       ≥0.75     ≥0.75      ≥0.5\n"
                "  注：表中D为涵洞内侧高度或者圆涵内径(m)。"
            )
            content = content.replace('{{NORM_TABLE_11_2_5}}', _txt_table)
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
        if not self._all_results:
            InfoBar.warning("提示", "请先计算。", parent=self._info_parent(), duration=3000, position=InfoBarPosition.TOP); return
        meta = load_meta()
        channel_name = getattr(self, 'input_params', {}).get('channel_name', '')
        section_name = _culvert_full_name(getattr(self, 'input_params', {}).get('section_type', _CULVERT_RECT))
        auto_purpose = build_calc_purpose('culvert', project=meta.project_name, name=channel_name, section_type=section_name)
        n_cases = len(self._all_results)
        current_label = self._auto_label(self._cases[self._current_case_idx], self._current_case_idx) if self._cases else '工况1'
        dlg = ExportConfirmDialog('culvert', '暗涵水力计算书', auto_purpose,
                                  parent=self._info_parent(),
                                  n_cases=n_cases, current_case_label=current_label)
        from PySide6.QtWidgets import QDialog
        if dlg.exec() != QDialog.Accepted:
            return
        self._word_export_meta = dlg.get_meta()
        self._word_export_purpose = dlg.get_calc_purpose()
        self._word_export_refs = dlg.get_references()
        self._word_export_scope = dlg.get_export_scope() if n_cases > 1 else 'all'
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
        """构建Word报告文档（工程产品运行卡格式），支持多工况"""
        meta = getattr(self, '_word_export_meta', load_meta())
        purpose = getattr(self, '_word_export_purpose', '')
        refs = getattr(self, '_word_export_refs', REFERENCES_BASE.get('culvert', []))
        scope = getattr(self, '_word_export_scope', 'all')

        # 确定要导出的工况
        if scope == 'current':
            export_results = [(ci, p, r) for ci, p, r in self._all_results if ci == self._current_case_idx]
        else:
            export_results = list(self._all_results)

        n_export = len(export_results)
        first_method = export_results[0][2].get('design_method', '') if export_results else ''
        first_section = _culvert_full_name(export_results[0][1].get('section_type', _CULVERT_RECT)) if export_results else _culvert_full_name(_CULVERT_RECT)
        desc = f'{first_section}水力断面设计计算（{first_method}）' if n_export == 1 else f'暗涵水力断面设计计算（{n_export}个工况）'

        doc = create_engineering_report_doc(
            meta=meta,
            calc_title='暗涵水力计算书',
            calc_content_desc=desc,
            calc_purpose=purpose,
            references=refs,
            calc_program_text=f'渠系建筑物水力计算系统 V1.0\n{desc}',
        )
        doc.add_page_break()

        # 5. 基础公式
        doc_add_eng_h(doc, '5、基础公式')
        formula_section_types = []
        for _, params, _ in export_results:
            section_type = _normalize_culvert_section_type(params.get('section_type', _CULVERT_RECT))
            if section_type not in formula_section_types:
                formula_section_types.append(section_type)
        if not formula_section_types:
            formula_section_types.append(_CULVERT_RECT)

        has_rect_optimal = any(
            _normalize_culvert_section_type(params.get('section_type', _CULVERT_RECT)) == _CULVERT_RECT
            and result.get('is_optimal_section')
            for _, params, result in export_results
        )
        for idx, section_type in enumerate(formula_section_types):
            if len(formula_section_types) > 1:
                if idx > 0:
                    doc_add_eng_body(doc, '')
                doc_add_eng_body(doc, f'{_culvert_full_name(section_type)}：')
            for label, formula in _culvert_base_formula_items(
                section_type,
                include_optimal=(section_type == _CULVERT_RECT and has_rect_optimal),
            ):
                doc_add_formula(doc, formula, label)

        # 6. 计算过程
        doc_add_eng_h(doc, '6、计算过程')
        _marker = '{{NORM_TABLE_11_2_5}}'
        _multi = n_export > 1
        add_section_comparison_word_tables(
            doc,
            export_results,
            CULVERT_COMPARISON_SPEC,
            heading_func=doc_add_eng_h,
            table_func=doc_add_styled_table,
        )

        for ri, (case_idx, params, result) in enumerate(export_results):
            if not result.get('success'):
                doc_add_eng_body(doc, f'工况{case_idx+1}: 计算失败 - {result.get("error_message", "未知错误")}')
                continue

            detail = self._cases[case_idx].get('detail_checked', True) if case_idx < len(self._cases) else True
            txt = self._build_culvert_result_text(params, result, detail, case_idx if _multi else None)
            import re as _re
            calc_text = _re.sub(r'\{\{HTML\}\}.*?\{\{/HTML\}\}', _marker, txt, flags=_re.DOTALL)

            if _multi:
                section_prefix = f'6.{ri+1}'
                doc_add_eng_h(doc, f'{section_prefix}、工况{case_idx+1} (Q={params["Q"]:.3f} m³/s)')

            summary_items = build_result_summary_word_items("culvert", params, result)
            if summary_items:
                doc_add_eng_h(doc, '重点结果汇总')
                doc_add_result_table(doc, summary_items)

            if _marker in calc_text:
                _parts = calc_text.split(_marker, 1)
                skip_keyword = f"{_culvert_full_name(params.get('section_type', _CULVERT_RECT))}水力计算结果"
                doc_render_calc_text_eng(doc, _parts[0], skip_title_keyword=skip_keyword)
                doc_add_table_caption(doc, '表 11.2.5  无压涵洞的净空高度(m)')
                _H = result.get('H', result.get('H_total', 0))
                doc_add_styled_table(doc,
                    headers=['进口净高', '圆涵', '拱涵', '矩形涵洞'],
                    data=[['≤3', '≥D/4', '≥D/4', '≥D/6'], ['>3', '≥0.75', '≥0.75', '≥0.5']],
                    highlight_col=3,
                    highlight_val='≥D/6' if _H <= 3.0 else '≥0.5',
                    with_full_border=True,
                )
                doc_add_eng_body(doc, '注：表中D为涵洞内侧高度或者圆涵内径(m)。')
                doc_render_calc_text_eng(doc, _parts[1])
            else:
                skip_keyword = f"{_culvert_full_name(params.get('section_type', _CULVERT_RECT))}水力计算结果"
                doc_render_calc_text_eng(doc, calc_text, skip_title_keyword=skip_keyword)

        # 7. 断面图
        try:
            import tempfile
            tmp = os.path.join(tempfile.gettempdir(), '_culvert_section.png')
            self.section_fig.savefig(tmp, dpi=150, bbox_inches='tight')
            doc_add_eng_h(doc, '7、断面图')
            doc_add_figure(doc, tmp, width_cm=14)
            os.remove(tmp)
        except Exception:
            pass
        doc.save(filepath)

    # ================================================================
    # 项目序列化
    # ================================================================
    def to_project_dict(self):
        """将当前面板状态序列化为可 JSON 化的字典"""
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
        """从项目字典恢复面板状态"""
        cases = data.get('cases')
        if not cases or not isinstance(cases, list):
            return
        self._cases = [self._ensure_case_defaults(case) for case in cases]
        self._current_case_idx = min(data.get('current_case_idx', 0), len(self._cases) - 1)
        self._load_case(self._current_case_idx)
        self._rebuild_case_tags()
        self._update_calc_btn_text()
        self._all_results = data.get('all_results', []) or []
        self.current_result = data.get('current_result')
        self.input_params = data.get('input_params') or {}
        if self._all_results:
            try:
                self._display_all_results()
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
