# -*- coding: utf-8 -*-
"""
矩形暗涵水力计算面板 —— QWidget 版本

支持：矩形暗涵（经济最优断面 / 指定底宽 / 指定宽深比）
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
from PySide6.QtWidgets import QSizePolicy
from PySide6.QtWebEngineWidgets import QWebEngineView

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

from app_渠系计算前端.styles import P, S, W, E, BG, CARD, BD, T1, T2, INPUT_LABEL_STYLE, INPUT_SECTION_STYLE, INPUT_HINT_STYLE
from app_渠系计算前端.export_utils import (
    WORD_EXPORT_AVAILABLE, add_formula_to_doc, try_convert_formula_line, ask_open_file,
    create_styled_doc, doc_add_h1, doc_add_formula, doc_render_calc_text, doc_add_figure,
    doc_add_styled_table, doc_add_table_caption, doc_add_body,
    create_engineering_report_doc, doc_add_eng_h, doc_add_eng_body,
    doc_render_calc_text_eng, update_doc_toc_via_com,
)
from app_渠系计算前端.report_meta import (
    ExportConfirmDialog, build_calc_purpose, REFERENCES_BASE, load_meta
)
from app_渠系计算前端.culvert.dxf_export import export_culvert_dxf
from app_渠系计算前端.formula_renderer import (
    plain_text_to_formula_html, load_formula_page, make_plain_html,
    HelpPageBuilder
)
if WORD_EXPORT_AVAILABLE:
    from docx import Document as DocxDocument
    from docx.shared import Pt, Cm


class CulvertPanel(QWidget):
    """矩形暗涵水力计算面板"""
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
        self._init_ui()
        self._rebuild_case_tags()

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
        self.inc_edit = self._field(fl, "流量加大比例 (%):", "")
        self.inc_hint = QLabel("(留空则自动计算)")
        self.inc_hint.setStyleSheet(INPUT_HINT_STYLE)
        fl.addWidget(self.inc_hint)

        fl.addWidget(self._sep())
        fl.addWidget(self._slbl("【可选参数】"))
        self.bh_lbl, self.bh_edit = self._field2(fl, "指定宽深比 β:", "")
        self.hb_lbl, self.hb_edit = self._field2(fl, "指定高宽比 H/B:", "")
        self.B_lbl, self.B_edit = self._field2(fl, "指定底宽 B (m):", "")
        fl.addWidget(self._hint("(β 与 H/B 不可同时填写)"))
        fl.addWidget(self._hint("(B 可单独填写，也可与 H/B 合用)"))
        lbl_b1 = QLabel("高宽比H/B、宽高比B/H 建议不超过1.2（超出时提醒，不作强制）")
        lbl_b1.setStyleSheet(f"font-family: 'Microsoft YaHei', sans-serif; font-size: 11px; color: #0066CC;")
        fl.addWidget(lbl_b1)
        lbl_b2 = QLabel("留空则自动搜索经济最优断面（B×H 最小）")
        lbl_b2.setStyleSheet(f"font-family: 'Microsoft YaHei', sans-serif; font-size: 11px; color: #0066CC;")
        fl.addWidget(lbl_b2)
        lbl_ref = QLabel("参考 GB 50288-2018 第11.2.5条")
        lbl_ref.setStyleSheet(f"font-family: 'Microsoft YaHei', sans-serif; font-size: 11px; color: {T2};")
        fl.addWidget(lbl_ref)

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
        self.inc_edit.setVisible(enabled)
        self.inc_hint.setVisible(enabled)

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
        w = self.window()
        return w if w else self

    # ================================================================
    # 工况管理
    # ================================================================
    @staticmethod
    def _default_case():
        return {
            'custom_label': None,
            'Q': '5.0', 'n': '0.014', 'slope_inv': '2000',
            'v_min': '0.1', 'v_max': '100.0',
            'inc_checked': True, 'inc_pct': '',
            'detail_checked': True,
            'bh': '', 'hb': '', 'B': '',
        }

    def _save_current_case(self):
        if not (0 <= self._current_case_idx < len(self._cases)):
            return
        c = self._cases[self._current_case_idx]
        c['Q'] = self.Q_edit.text()
        c['n'] = self.n_edit.text()
        c['slope_inv'] = self.slope_edit.text()
        c['v_min'] = self.vmin_edit.text()
        c['v_max'] = self.vmax_edit.text()
        c['inc_checked'] = self.inc_cb.isChecked()
        c['inc_pct'] = self.inc_edit.text()
        c['detail_checked'] = self.detail_cb.isChecked()
        c['bh'] = self.bh_edit.text()
        c['hb'] = self.hb_edit.text()
        c['B'] = self.B_edit.text()

    def _load_case(self, idx):
        if not (0 <= idx < len(self._cases)):
            return
        c = self._cases[idx]
        self._loading_case = True
        self.Q_edit.blockSignals(True)
        self.Q_edit.setText(c.get('Q', ''))
        self.Q_edit.blockSignals(False)
        self.n_edit.setText(c.get('n', '0.014'))
        self.slope_edit.setText(c.get('slope_inv', '2000'))
        self.vmin_edit.setText(c.get('v_min', '0.1'))
        self.vmax_edit.setText(c.get('v_max', '100.0'))
        self.inc_cb.setChecked(c.get('inc_checked', True))
        self.inc_edit.setText(c.get('inc_pct', ''))
        self.detail_cb.setChecked(c.get('detail_checked', True))
        self.bh_edit.setText(c.get('bh', ''))
        self.hb_edit.setText(c.get('hb', ''))
        self.B_edit.setText(c.get('B', ''))
        self._on_inc_toggle(None)
        self._loading_case = False

    def _switch_case(self, idx):
        if idx == self._current_case_idx:
            return
        self._save_current_case()
        self._current_case_idx = idx
        self._load_case(idx)
        self._rebuild_case_tags()

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
        q_text = (case.get('Q', '') or '').strip() or '?'
        return f"Q{_sub(idx + 1)}={q_text}"

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
        self._rebuild_case_tags()

    def _apply_to_all_cases(self):
        self._save_current_case()
        src = self._cases[self._current_case_idx]
        keys = ('n', 'slope_inv', 'v_min', 'v_max', 'inc_checked', 'inc_pct',
                'detail_checked', 'bh', 'hb', 'B')
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
        prev = self._cases[self._current_case_idx - 1]
        curr = self._cases[self._current_case_idx]
        for k in ('n', 'slope_inv', 'v_min', 'v_max', 'inc_checked', 'inc_pct',
                   'detail_checked', 'bh', 'hb', 'B'):
            curr[k] = prev[k]
        self._load_case(self._current_case_idx)
        InfoBar.success(title="已复制", content=f"已从工况{self._current_case_idx}复制参数",
                        parent=self._info_parent(), position=InfoBarPosition.TOP, duration=2000)

    # ================================================================
    # 计算
    # ================================================================
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

        Q = _fv('Q', '设计流量 Q')
        n = _fv('n', '糙率 n')
        slope_inv = _fv('slope_inv', '水力坡降倒数')
        v_min = _fv('v_min', '不淤流速', must_positive=False)
        v_max = _fv('v_max', '不冲流速', must_positive=False)

        if v_min >= v_max:
            raise ValueError(f"工况{case_num}: 不淤流速必须小于不冲流速")

        use_increase = case.get('inc_checked', True)
        manual_increase = _fv_opt('inc_pct') if use_increase else 0
        manual_B = _fv_opt('B')
        target_BH_ratio = _fv_opt('bh')
        target_HB_ratio = _fv_opt('hb')

        if target_BH_ratio and target_HB_ratio:
            raise ValueError(f"工况{case_num}: 宽深比 β 与高宽比 H/B 不能同时指定")

        input_params = {
            'Q': Q, 'n': n, 'slope_inv': slope_inv,
            'v_min': v_min, 'v_max': v_max,
            'manual_B': manual_B,
            'target_BH_ratio': target_BH_ratio,
            'target_HB_ratio': target_HB_ratio,
            'manual_increase': manual_increase,
            'use_increase': use_increase,
        }
        return input_params

    def _calculate(self):
        self._save_current_case()
        self._all_results = []
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
                    {'Q': q_val},
                    {'success': False, 'error_message': msg}
                ))
                continue
            try:
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
        out = ["=" * 70, f"  {title}", "=" * 70, "", msg, "", "-" * 70, "请修正后重新计算。", "=" * 70]
        self.result_text.setHtml(make_plain_html("\n".join(out)))

    # ================================================================
    # 结果显示
    # ================================================================
    def _display_all_results(self):
        """显示所有工况计算结果"""
        _multi = len(self._all_results) > 1
        all_text_parts = []
        all_plain_parts = []

        for case_idx, params, result in self._all_results:
            if not result.get('success'):
                q_raw = params.get('Q', '')
                try:
                    q_text = f"{float(q_raw):.3f} m³/s"
                except Exception:
                    q_text = '-'
                part = (
                    f"【工况 {case_idx + 1}｜矩形暗涵｜Q = {q_text}】\n\n"
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
            self._draw_rect(axes[0], r['B'], r['H'], r['h_design'], r['V_design'], p['Q'], "设计流量")
            self._draw_rect(axes[1], r['B'], r['H'], r['h_increased'], r['V_increased'], r['Q_increased'], "加大流量")
        else:
            ncols = min(n, 3)
            nrows = (n + ncols - 1) // ncols
            axes = self.section_fig.subplots(nrows, ncols, squeeze=False)
            for idx, (ci, p, r) in enumerate(success_results):
                row, col = divmod(idx, ncols)
                ax = axes[row][col]
                self._draw_rect(ax, r['B'], r['H'], r['h_design'], r['V_design'], p['Q'],
                                f"工况{ci+1} Q={p['Q']:.2f}")
            for idx in range(n, nrows * ncols):
                row, col = divmod(idx, ncols)
                axes[row][col].set_visible(False)
        self.section_fig.tight_layout()
        self.section_canvas.draw()

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
        load_formula_page(self.result_text, plain_text_to_formula_html(txt))

    def _build_culvert_result_text(self, p, result, detail, case_num=None):
        """构建单个工况的结果文本，case_num 为 None 时不显示工况前缀"""
        Q, n = p['Q'], p['n']
        slope_inv = p['slope_inv']; i = 1.0 / slope_inv
        v_min, v_max = p['v_min'], p['v_max']
        inc_src = "(指定)" if p.get('manual_increase') else "(自动计算)"
        is_optimal = result.get('is_optimal_section', False)
        target_HB = p.get('target_HB_ratio')

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
            o.append(f"【工况 {case_num + 1}｜矩形暗涵｜Q = {Q:.3f} m³/s】")
            o.append("")
        o.append("=" * 70)
        if is_optimal:
            o.append("              矩形暗涵水力计算结果（经济最优断面）")
        elif target_HB:
            o.append(f"              矩形暗涵水力计算结果（指定高宽比 H/B={target_HB:.2f}）")
        else:
            o.append("              矩形暗涵水力计算结果")
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
                o.append("  1. 加大流量比例:")
                o.append(f"      = {inc_pct:.1f}% {inc_src}")
                o.append("")
                o.append("  2. 加大流量计算:")
                o.append(f"      Q加大 = Q × (1 + {inc_pct:.1f}%)")
                o.append(f"           = {Q:.3f} × {1 + inc_pct/100:.3f}")
                o.append(f"           = {Q_inc:.3f} m³/s")
                o.append("")

                o.append("  3. 加大水深计算:")
                o.append(f"      根据加大流量 Q加大 = {Q_inc:.3f} m³/s 和底宽 B = {B:.2f} m，利用曼宁公式反算水深:")
                o.append(f"      h加大 = {h_inc:.3f} m")
                o.append("")

                A_inc = B * h_inc
                chi_inc = B + 2 * h_inc
                R_inc = A_inc / chi_inc if chi_inc > 0 else 0

                o.append("  4. 加大流量工况过水面积:")
                o.append(f"      A加大 = B × h加大")
                o.append(f"           = {B:.2f} × {h_inc:.3f}")
                o.append(f"           = {A_inc:.3f} m²")
                o.append("")

                o.append("  5. 加大流量工况湿周:")
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
        self._cases = [self._default_case()]
        self._current_case_idx = 0
        self._all_results = []
        self._load_case(0)
        self._rebuild_case_tags()
        self._update_calc_btn_text()
        self._show_initial_help()
        self.section_fig.clear(); self.section_canvas.draw()
        self.inc_hint.setText("(留空则自动计算)")
        self.current_result = None
        self._export_plain_text = ""

    def _export_dxf(self):
        if not self.current_result or not self.current_result.get('success'):
            InfoBar.warning("提示", "请先进行计算后再导出。", parent=self._info_parent(), duration=3000, position=InfoBarPosition.TOP); return
        res = self.current_result; p = self.input_params
        B = res.get('B', 0.0); H = res.get('H', 0.0)
        default_name = f'暗渠断面_矩形_B{B:.2f}xH{H:.2f}.dxf'
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
            export_culvert_dxf(filepath, res, p, scale_denom)
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
        auto_purpose = build_calc_purpose('culvert', project=meta.project_name, name=channel_name, section_type='矩形')
        n_cases = len(self._all_results)
        current_label = self._auto_label(self._cases[self._current_case_idx], self._current_case_idx) if self._cases else '工况1'
        dlg = ExportConfirmDialog('culvert', '矩形暗涵水力计算书', auto_purpose,
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
        desc = f'矩形暗涵水力断面设计计算（{first_method}）' if n_export == 1 else f'矩形暗涵水力断面设计计算（{n_export}个工况）'

        doc = create_engineering_report_doc(
            meta=meta,
            calc_title='矩形暗涵水力计算书',
            calc_content_desc=desc,
            calc_purpose=purpose,
            references=refs,
            calc_program_text=f'渠系建筑物水力计算系统 V1.0\n{desc}',
        )
        doc.add_page_break()

        # 5. 基础公式
        doc_add_eng_h(doc, '5、基础公式')
        doc_add_formula(doc, r'Q = \frac{1}{n} \cdot A \cdot R^{2/3} \cdot i^{1/2}', '曼宁公式：')
        doc_add_formula(doc, r'A = B \cdot h', '过水面积：')
        doc_add_formula(doc, r'P = B + 2h', '湿周：')
        doc_add_formula(doc, r'R = \frac{A}{P} = \frac{Bh}{B+2h}', '水力半径：')
        # 如果任意工况使用经济最优
        if any(r.get('is_optimal_section') for _, _, r in export_results):
            doc_add_formula(doc, r'\min A = B \times H \text{ (经济最优)}', '优化目标：')

        # 6. 计算过程
        doc_add_eng_h(doc, '6、计算过程')
        _marker = '{{NORM_TABLE_11_2_5}}'
        _multi = n_export > 1

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

            if _marker in calc_text:
                _parts = calc_text.split(_marker, 1)
                doc_render_calc_text_eng(doc, _parts[0], skip_title_keyword='矩形暗涵水力计算结果')
                doc_add_table_caption(doc, '表 11.2.5  无压涵洞的净空高度(m)')
                _H = result.get('H', 0)
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
                doc_render_calc_text_eng(doc, calc_text, skip_title_keyword='矩形暗涵水力计算结果')

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
        self._cases = cases
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
