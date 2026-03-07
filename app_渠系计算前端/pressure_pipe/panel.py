# -*- coding: utf-8 -*-
"""
有压管道设计面板 —— QWidget 版本

功能：单次计算（推荐管径 + 候选表 + 详细过程）、批量计算（后台线程 + 进度 + CSV/PDF）
"""

import sys
import os
import copy
import html as html_mod

_pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_pkg_root, "calc_渠系计算算法内核"))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QSplitter, QFrame, QTabWidget, QTextEdit, QFileDialog,
    QScrollArea, QProgressBar, QPushButton, QLayout,
)
from PySide6.QtCore import Qt, QThread, Signal, QRect, QPoint, QSize, QTimer
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWebEngineWidgets import QWebEngineView

from qfluentwidgets import (
    ComboBox, PushButton, PrimaryPushButton, LineEdit,
    CheckBox, InfoBar, InfoBarPosition
)

from 有压管道设计 import (
    PIPE_MATERIALS, DEFAULT_DIAMETER_SERIES,
    DEFAULT_Q_RANGE, DEFAULT_SLOPE_DENOMINATORS,
    SPEC_672_TEXT,
    PressurePipeInput, RecommendationResult,
    get_flow_increase_percent, evaluate_single_diameter,
    recommend_diameter, build_detailed_process_text,
    run_batch_scan, BatchScanConfig, BatchScanResult,
)

from app_渠系计算前端.styles import (
    P, S, W, E, BG, CARD, BD, T1, T2,
    INPUT_LABEL_STYLE, INPUT_SECTION_STYLE, INPUT_HINT_STYLE
)
from app_渠系计算前端.formula_renderer import (
    plain_text_to_formula_html, load_formula_page, make_plain_html,
    HelpPageBuilder,
)
from app_渠系计算前端.export_utils import (
    WORD_EXPORT_AVAILABLE, ask_open_file,
    create_engineering_report_doc, doc_add_eng_h, doc_add_eng_body,
    doc_add_formula, doc_render_calc_text_eng, doc_add_result_table,
    doc_add_styled_table,
)
from app_渠系计算前端.report_meta import (
    ExportConfirmDialog, build_calc_purpose, REFERENCES_BASE, load_meta,
)


def _e(s):
    return html_mod.escape(str(s))


# ============================================================
# SpinBox / 标签芯片 辅助组件
# ============================================================
_SPINBTN_SS = """
    QPushButton { border:none; background:#f5f5f5; font-size:15px; color:#555; }
    QPushButton:hover { background:#e0e8f0; color:#0078d4; }
    QPushButton:pressed { background:#d0dde8; }
"""
_PRESET_SS = """
    QPushButton { padding:4px 12px; border:1px solid #d0d0d0; border-radius:14px;
                  background:#fff; font-size:12px; color:#555; }
    QPushButton:hover { border-color:#0078d4; color:#0078d4; background:#f0f7ff; }
"""
_PRESET_ACTIVE_SS = """
    QPushButton { padding:4px 12px; border:1px solid #0078d4; border-radius:14px;
                  background:#0078d4; font-size:12px; color:#fff; }
    QPushButton:hover { background:#106ebe; }
"""
_SLOPE_PRESETS = {
    "standard": [500, 750, 1000, 1500, 2000, 2500, 3000, 3500, 4000],
    "sparse":   [500, 1000, 2000, 3000, 4000],
    "dense":    [250, 500, 750, 1000, 1250, 1500, 1750, 2000, 2500, 3000, 3500, 4000, 5000],
}


class _FlowLayout(QLayout):
    """自动换行流式布局"""

    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        er = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = er.x(), er.y(), 0
        sp = self._spacing
        right = er.x() + er.width()
        for item in self._items:
            isz = item.sizeHint()
            nxt = x + isz.width()
            if nxt > right and line_h > 0:
                x = er.x()
                y += line_h + sp
                line_h = 0
                nxt = x + isz.width()
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), isz))
            x = nxt + sp
            line_h = max(line_h, isz.height())
        return y + line_h - rect.y() + m.bottom()


class _TagChip(QPushButton):
    """坡度分母标签芯片 — 点击删除"""
    removed = Signal(int)

    def __init__(self, value, parent=None):
        super().__init__(f"1/{value}  ×", parent)
        self.value = value
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(24)
        self.setStyleSheet(
            "QPushButton{background:#e8f4fd;border:none;border-radius:12px;"
            "color:#0078d4;font-size:12px;font-weight:500;padding:2px 8px 2px 10px;}"
            "QPushButton:hover{background:#d0eafc;}"
        )
        self.clicked.connect(lambda: self.removed.emit(self.value))


class _DashedButton(QPushButton):
    """虚线圆角按钮 — 用 paintEvent 手绘，绕开 QSS dashed+border-radius 渲染 bug"""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._hovered = False
        self.setMouseTracking(True)
        self.setStyleSheet(
            "QPushButton{background:transparent;border:none;"
            "color:#999;font-size:12px;padding:3px 10px;}"
        )

    def enterEvent(self, event):
        self._hovered = True
        self.setStyleSheet(
            "QPushButton{background:#f0f7ff;border:none;"
            "color:#0078d4;font-size:12px;padding:3px 10px;}"
        )
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.setStyleSheet(
            "QPushButton{background:transparent;border:none;"
            "color:#999;font-size:12px;padding:3px 10px;}"
        )
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#0078d4") if self._hovered else QColor("#ccc"))
        pen.setStyle(Qt.DashLine)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)
        p.end()


# ============================================================
# 工况标签芯片
# ============================================================
_SUB = '₀₁₂₃₄₅₆₇₈₉'
MAX_CASES = 10
def _sub(n):
    return ''.join(_SUB[int(d)] for d in str(n))

_CASE_TAG_ACTIVE_SS = (
    "QPushButton{background:#0078d4;border:2px solid #0078d4;border-radius:14px;"
    "color:#fff;font-size:12px;font-weight:600;padding:2px 14px;}"
    "QPushButton:hover{background:#106ebe;border-color:#106ebe;}"
)
_CASE_TAG_INACTIVE_SS = (
    "QPushButton{background:#f0f0f0;border:2px solid transparent;border-radius:14px;"
    "color:#666;font-size:12px;font-weight:500;padding:2px 14px;}"
    "QPushButton:hover{background:#e8f4fd;color:#0078d4;}"
)
_CASE_QUICK_SS = (
    "QPushButton{padding:4px 10px;border:1px solid #d0d0d0;border-radius:6px;"
    "background:#fff;font-size:11px;color:#555;}"
    "QPushButton:hover{border-color:#0078d4;color:#0078d4;background:#f0f7ff;}"
)


class _CaseTagChip(QPushButton):
    """工况标签芯片 — 点击切换工况"""
    switched = Signal(int)

    def __init__(self, index, label_text, active=False, parent=None):
        super().__init__(label_text, parent)
        self.case_index = index
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(28)
        self.setStyleSheet(_CASE_TAG_ACTIVE_SS if active else _CASE_TAG_INACTIVE_SS)
        self.clicked.connect(lambda: self.switched.emit(self.case_index))


# ============================================================
# 批量计算工作线程
# ============================================================
class _BatchWorker(QThread):
    """后台批量计算线程"""
    progress = Signal(int, int, str)   # current, total, message
    finished = Signal(object)          # BatchScanResult
    error = Signal(str)

    def __init__(self, config: BatchScanConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            result = run_batch_scan(
                self._config,
                progress_cb=lambda cur, tot, msg: self.progress.emit(cur, tot, msg),
                cancel_flag=lambda: self._cancel,
            )
            self.finished.emit(result)
        except Exception:
            import traceback
            self.error.emit(traceback.format_exc())


# ============================================================
# 面板
# ============================================================
class PressurePipePanel(QWidget):
    """有压管道设计面板"""
    data_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_result: RecommendationResult | None = None
        self._export_plain_text = ""
        self._batch_worker: _BatchWorker | None = None
        self._initial_sized = False
        self._cases = [self._default_case()]
        self._current_case_idx = 0
        self._all_results = []
        self._last_errors: list[str] = []
        self._init_ui()
        self._rebuild_case_tags()

    # ================================================================
    # UI 构建
    # ================================================================
    def _init_ui(self):
        main_lay = QHBoxLayout(self)
        main_lay.setContentsMargins(10, 8, 10, 8)
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        main_lay.addWidget(self._splitter)

        # 左侧: 输入参数
        self._input_scroll = QScrollArea()
        self._input_scroll.setWidgetResizable(True)
        self._input_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._input_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        inp_w = QWidget()
        self._build_input(inp_w)
        self._input_scroll.setWidget(inp_w)
        self._input_scroll.setMinimumWidth(420)
        self._splitter.addWidget(self._input_scroll)

        # 右侧: 输出区
        out_w = QWidget()
        self._build_output(out_w)
        self._splitter.addWidget(out_w)

        # 左侧保持内容宽度不被压缩，右侧弹性扩展
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([460, 840])

    # ----------------------------------------------------------------
    # 首次显示时自动适配左侧面板宽度
    # ----------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_sized:
            self._initial_sized = True
            QTimer.singleShot(0, self._auto_fit_input_width)

    def _auto_fit_input_width(self):
        """根据内容实际 sizeHint 自动设置左侧面板初始宽度"""
        content_w = self._input_scroll.widget().sizeHint().width()
        sb_w = self._input_scroll.verticalScrollBar().sizeHint().width()
        ideal = content_w + sb_w + 24          # 留少量余量
        ideal = max(ideal, 420)                 # 下限保底
        total = self._splitter.width()
        right = max(total - ideal, 400)         # 右侧至少 400
        self._splitter.setSizes([ideal, right])

    # ----------------------------------------------------------------
    # 输入区
    # ----------------------------------------------------------------
    def _build_input(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(6)

        # ---- 单次计算参数组 ----
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
        _copy_all_btn.setToolTip(
            "将当前工况的管材、管长、局部损失比例、指定管径、加大流量等参数\n"
            "复制到其余所有工况（各工况的设计流量Q保持不变）"
        )
        _copy_all_btn.clicked.connect(self._apply_to_all_cases)
        _quick_row.addWidget(_copy_all_btn)
        _copy_prev_btn = QPushButton("从上一个复制")
        _copy_prev_btn.setCursor(Qt.PointingHandCursor)
        _copy_prev_btn.setStyleSheet(_CASE_QUICK_SS)
        _copy_prev_btn.setToolTip(
            "将上一个工况的管材、管长等参数复制到当前工况\n"
            "（设计流量Q不变），方便快速填写相似工况"
        )
        _copy_prev_btn.clicked.connect(self._copy_from_prev_case)
        _quick_row.addWidget(_copy_prev_btn)
        self._del_case_btn = QPushButton("删除当前")
        self._del_case_btn.setCursor(Qt.PointingHandCursor)
        self._del_case_btn.setStyleSheet(_CASE_QUICK_SS)
        self._del_case_btn.setToolTip("删除当前选中的工况（至少保留一个）")
        self._del_case_btn.clicked.connect(self._remove_current_case)
        _quick_row.addWidget(self._del_case_btn)
        _quick_row.addStretch()
        fl.addLayout(_quick_row)
        fl.addWidget(self._sep())

        # 设计流量
        self.Q_edit = self._field(fl, "设计流量 Q (m³/s):", "0.5")
        self.Q_edit.textChanged.connect(self._on_q_text_changed)
        # 管材
        r = QHBoxLayout()
        lbl = QLabel("管材类型:")
        lbl.setMinimumWidth(140)
        lbl.setStyleSheet(INPUT_LABEL_STYLE)
        r.addWidget(lbl)
        self.material_combo = ComboBox()
        mat_display = [(k, v["name"]) for k, v in PIPE_MATERIALS.items()]
        self._mat_keys = [k for k, _ in mat_display]
        self.material_combo.addItems([n for _, n in mat_display])
        r.addWidget(self.material_combo, 1)
        fl.addLayout(r)

        # 管长
        fl.addWidget(self._slbl("【管道参数】"))
        self.length_edit = self._field(fl, "管长 L (m):", "1000")
        self.local_ratio_edit = self._field(fl, "局部水头损失比例:", "0.15")

        # 可选参数
        fl.addWidget(self._sep())
        fl.addWidget(self._slbl("【可选参数】"))
        self.D_edit = self._field(fl, "指定管径 D (m):", "")
        self.D_edit.setPlaceholderText("留空则自动推荐经济管径")
        fl.addWidget(self._sep())

        # 加大流量
        self.inc_cb = CheckBox("考虑加大流量")
        self.inc_cb.setChecked(True)
        self.inc_cb.stateChanged.connect(self._on_inc_toggle)
        fl.addWidget(self.inc_cb)
        self.inc_edit = self._field(fl, "加大比例 (%):", "")
        self.inc_edit.setPlaceholderText("留空则自动计算")

        fl.addWidget(self._sep())

        # 详细过程开关
        self.detail_cb = CheckBox("输出详细计算过程")
        self.detail_cb.setChecked(True)
        fl.addWidget(self.detail_cb)

        fl.addWidget(self._sep())

        # 按钮
        br = QHBoxLayout()
        self._calc_btn = PrimaryPushButton("计算")
        self._calc_btn.setCursor(Qt.PointingHandCursor)
        self._calc_btn.clicked.connect(self._calculate)
        clb = PushButton("清空")
        clb.setCursor(Qt.PointingHandCursor)
        clb.clicked.connect(self._clear)
        ew = PushButton("导出Word")
        ew.setCursor(Qt.PointingHandCursor)
        ew.clicked.connect(self._export_word)
        br.addWidget(self._calc_btn)
        br.addWidget(clb)
        br.addWidget(ew)
        fl.addLayout(br)

        lay.addWidget(grp)

        # ---- 批量计算参数组 ----
        grp2 = QGroupBox("批量计算")
        fl2 = QVBoxLayout(grp2)
        fl2.setSpacing(5)

        fl2.addWidget(self._hint("按参数范围批量扫描计算，生成 CSV / PDF"))

        # ---- Q 范围 SpinBox ----
        fl2.addWidget(self._slbl("流量范围 Q (m³/s)"))
        self.batch_q_start = self._spinbox_row(fl2, "起始", 0.1, 0.1, minimum=0.0, decimals=2)
        self.batch_q_end   = self._spinbox_row(fl2, "终止", 2.0, 0.1, minimum=0.01, decimals=2)
        self.batch_q_step  = self._spinbox_row(fl2, "步长", 0.1, 0.05, minimum=0.01, decimals=2)
        self._q_preview = QLabel()
        self._q_preview.setWordWrap(True)
        self._q_preview.setStyleSheet("font-size:11px; color:#999;")
        fl2.addWidget(self._q_preview)
        for _qe in (self.batch_q_start, self.batch_q_end, self.batch_q_step):
            _qe.textChanged.connect(lambda _: self._update_q_preview())
        self._update_q_preview()

        fl2.addWidget(self._sep())

        # ---- 管长 SpinBox ----
        self.batch_length_edit = self._spinbox_row(fl2, "管长 L (m)", 1000, 100, minimum=10, decimals=0)
        self.batch_local_ratio_edit = self._spinbox_row(fl2, "局部水头损失比例", 0.15, 0.01, minimum=0.0, decimals=2)

        fl2.addWidget(self._sep())

        # ---- 无压管道对比（折叠式） ----
        self.batch_unpr_cb = CheckBox("启用无压管道对比")
        self.batch_unpr_cb.setChecked(False)
        self.batch_unpr_cb.stateChanged.connect(self._on_unpr_toggle)
        fl2.addWidget(self.batch_unpr_cb)

        self._unpr_container = QWidget()
        _unpr_lay = QVBoxLayout(self._unpr_container)
        _unpr_lay.setContentsMargins(16, 4, 0, 0)
        _unpr_lay.setSpacing(4)
        _unpr_lay.addWidget(self._hint(
            "同时计算同管径无压（重力流）工况，\n"
            "用于有压/无压流速与水损对比分析"
        ))

        # -- 坡度分母 标签芯片区 --
        _unpr_lay.addWidget(self._slbl("坡度分母 (1/i)"))

        # 预设快捷按钮
        _preset_row = QHBoxLayout()
        _preset_row.setSpacing(6)
        self._slope_preset_btns = []
        for _text, _key in [("标准 9档", "standard"), ("稀疏 5档", "sparse"),
                             ("密集 13档", "dense"), ("自定义范围", "custom")]:
            _pb = QPushButton(_text)
            _pb.setCursor(Qt.PointingHandCursor)
            _pb.setStyleSheet(_PRESET_SS)
            _pb.clicked.connect(lambda _, k=_key: self._apply_slope_preset(k))
            _preset_row.addWidget(_pb)
            self._slope_preset_btns.append((_key, _pb))
        _preset_row.addStretch()
        _unpr_lay.addLayout(_preset_row)

        # 自定义范围生成器（默认隐藏）
        self._slope_range_gen = QFrame()
        self._slope_range_gen.setStyleSheet(
            "QFrame{background:#f8fafc;border:1px solid #e8e8e8;border-radius:6px;}"
        )
        self._slope_range_gen.setVisible(False)
        _rg_lay = QVBoxLayout(self._slope_range_gen)
        _rg_lay.setContentsMargins(10, 8, 10, 8)
        _rg_lay.setSpacing(4)
        _rg_title = QLabel("🔧 自定义范围生成")
        _rg_title.setStyleSheet(f"font-size:12px;color:#1976D2;font-weight:600;"
                                 "background:transparent;border:none;")
        _rg_lay.addWidget(_rg_title)
        self._rg_start = self._spinbox_row(_rg_lay, "起始", 500,  100, minimum=50, decimals=0)
        self._rg_end   = self._spinbox_row(_rg_lay, "终止", 4000, 100, minimum=50, decimals=0)
        self._rg_step  = self._spinbox_row(_rg_lay, "步长", 500,  50,  minimum=50, decimals=0)
        _rg_btn = PrimaryPushButton("生成并填入 ↓")
        _rg_btn.setCursor(Qt.PointingHandCursor)
        _rg_btn.clicked.connect(self._generate_slope_range)
        _rg_lay.addWidget(_rg_btn)
        _unpr_lay.addWidget(self._slope_range_gen)

        # 标签芯片容器（FlowLayout）
        self._slope_values: list = []
        self._slope_tag_container = QWidget()
        self._slope_tag_container.setObjectName("slopeTagBox")
        self._slope_tag_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._slope_tag_container.setStyleSheet(
            "#slopeTagBox{background:#fff;border:1px solid #d0d0d0;border-radius:6px;}"
        )
        self._slope_tag_flow = _FlowLayout(self._slope_tag_container, spacing=5)
        self._slope_tag_flow.setContentsMargins(8, 8, 8, 8)
        _unpr_lay.addWidget(self._slope_tag_container)

        # 手动添加输入行
        _add_row = QHBoxLayout()
        self._slope_add_edit = LineEdit()
        self._slope_add_edit.setPlaceholderText("输入分母，回车添加")
        self._slope_add_edit.returnPressed.connect(self._add_slope_from_input)
        _add_row.addWidget(self._slope_add_edit, 1)
        _clear_slopes_btn = QPushButton("清空全部")
        _clear_slopes_btn.setCursor(Qt.PointingHandCursor)
        _clear_slopes_btn.setFixedHeight(24)
        _clear_slopes_btn.setStyleSheet(
            "QPushButton{border:1px solid #d0d0d0;border-radius:4px;"
            "background:#fff;font-size:11px;color:#c42b1c;padding:2px 10px;}"
            "QPushButton:hover{border-color:#c42b1c;background:#fef0ef;}"
        )
        _clear_slopes_btn.clicked.connect(self._clear_all_slopes)
        _add_row.addWidget(_clear_slopes_btn)
        _unpr_lay.addLayout(_add_row)
        _unpr_lay.addWidget(self._hint("点 × 删除 | 输入回车添加 | 预设按钮快速填入"))

        _unpr_lay.addWidget(self._sep())
        self.batch_n_edit = self._spinbox_row(_unpr_lay, "糙率 n", 0.014, 0.001,
                                               minimum=0.008, decimals=3)
        self._unpr_container.setVisible(False)
        fl2.addWidget(self._unpr_container)

        # 初始化预设状态（标准9档）
        self._apply_slope_preset("standard")

        # 管材多选（默认全选）
        fl2.addWidget(self._slbl("【管材选择】"))
        self._mat_cbs = {}
        for k, v in PIPE_MATERIALS.items():
            cb_mat = CheckBox(v["name"])
            cb_mat.setChecked(True)
            fl2.addWidget(cb_mat)
            self._mat_cbs[k] = cb_mat

        fl2.addWidget(self._sep())

        # 输出选项
        fl2.addWidget(self._slbl("【输出选项】"))
        self.out_csv_cb = CheckBox("CSV 计算结果")
        self.out_csv_cb.setChecked(True)
        self.out_csv_cb.setToolTip("包含所有工况的原始数据（管径/流速/水损等），可用Excel打开做后续分析")
        fl2.addWidget(self.out_csv_cb)
        self.out_pdf_cb = CheckBox("图表 PDF（流速水损对比 + 优选设计点）")
        self.out_pdf_cb.setChecked(True)
        self.out_pdf_cb.setToolTip("图1: 各管径的流速与水损对比图\n图2: 优选设计点（经济区/妥协区）分组展示\n按管材分别生成独立PDF文件")
        fl2.addWidget(self.out_pdf_cb)
        self.out_merged_cb = CheckBox("合并 PDF（所有图表合为一个文件）")
        self.out_merged_cb.setChecked(True)
        self.out_merged_cb.setToolTip("将上面所有图表PDF合并为一个完整文档，方便一次性查阅和打印")
        fl2.addWidget(self.out_merged_cb)
        self.out_png_cb = CheckBox("子图 PNG（每个Q值独立高清图 300DPI）")
        self.out_png_cb.setChecked(True)
        self.out_png_cb.setToolTip("为每个流量Q值生成独立的高清PNG图片（300DPI），适合插入Word报告或PPT")
        fl2.addWidget(self.out_png_cb)

        # 无输出选项时的提示
        self._no_output_hint = QLabel("⚠ 请至少勾选一项输出内容")
        self._no_output_hint.setStyleSheet("font-size:11px; color:#c42b1c; margin:2px 0;")
        self._no_output_hint.setVisible(False)
        fl2.addWidget(self._no_output_hint)

        # 联动：勾选变化 → 更新按钮状态 & 合并PDF可用性
        for _cb in (self.out_csv_cb, self.out_pdf_cb, self.out_png_cb):
            _cb.stateChanged.connect(self._on_output_option_changed)
        self.out_merged_cb.stateChanged.connect(self._on_output_option_changed)
        self.out_pdf_cb.stateChanged.connect(self._on_pdf_cb_toggled)

        fl2.addWidget(self._sep())

        # 进度条
        self.batch_progress = QProgressBar()
        self.batch_progress.setVisible(False)
        fl2.addWidget(self.batch_progress)
        self.batch_status_label = QLabel("")
        self.batch_status_label.setStyleSheet("font-size:11px;color:#666;")
        self.batch_status_label.setVisible(False)
        fl2.addWidget(self.batch_status_label)

        # 按钮
        br2 = QHBoxLayout()
        self.batch_btn = PrimaryPushButton("开始批量计算")
        self.batch_btn.setCursor(Qt.PointingHandCursor)
        self.batch_btn.setToolTip("请先在【输出选项】中勾选至少一项")
        self.batch_btn.clicked.connect(self._start_batch)
        self.cancel_btn = PushButton("取消")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel_batch)
        br2.addWidget(self.batch_btn)
        br2.addWidget(self.cancel_btn)
        fl2.addLayout(br2)

        lay.addWidget(grp2)
        lay.addStretch()

    # ----------------------------------------------------------------
    # 输出区
    # ----------------------------------------------------------------
    def _build_output(self, parent):
        lay = QVBoxLayout(parent)
        lay.setContentsMargins(0, 0, 0, 0)
        self.notebook = QTabWidget()
        lay.addWidget(self.notebook)

        # Tab1: 计算结果（公式渲染）
        t1 = QWidget()
        t1l = QVBoxLayout(t1)
        t1l.setContentsMargins(5, 5, 5, 5)
        grp = QGroupBox("计算结果详情")
        gl = QVBoxLayout(grp)
        self.result_view = QWebEngineView()
        gl.addWidget(self.result_view)
        t1l.addWidget(grp)
        self.notebook.addTab(t1, "计算结果")

        # Tab2: 批量日志
        t2 = QWidget()
        t2l = QVBoxLayout(t2)
        t2l.setContentsMargins(5, 5, 5, 5)
        self.batch_log = QTextEdit()
        self.batch_log.setReadOnly(True)
        t2l.addWidget(self.batch_log)
        self.notebook.addTab(t2, "批量计算日志")

        self._show_initial_help()

    # ----------------------------------------------------------------
    # 辅助 UI
    # ----------------------------------------------------------------
    def _field(self, lay, label, default=""):
        r = QHBoxLayout()
        l = QLabel(label)
        l.setMinimumWidth(140)
        l.setStyleSheet(INPUT_LABEL_STYLE)
        r.addWidget(l)
        e = LineEdit()
        e.setText(default)
        r.addWidget(e, 1)
        lay.addLayout(r)
        return e

    def _slbl(self, t):
        l = QLabel(t)
        l.setStyleSheet(INPUT_SECTION_STYLE)
        return l

    def _hint(self, t):
        l = QLabel(t)
        l.setStyleSheet(INPUT_HINT_STYLE)
        return l

    def _sep(self):
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f"color:{BD};")
        return f

    def _fval_opt(self, edit):
        t = edit.text().strip()
        if not t: return None
        try: return float(t)
        except ValueError: return None

    def _on_inc_toggle(self, _state):
        enabled = self.inc_cb.isChecked()
        self.inc_edit.setVisible(enabled)

    def _on_unpr_toggle(self, _state):
        self._unpr_container.setVisible(self.batch_unpr_cb.isChecked())

    # ----------------------------------------------------------------
    # SpinBox 辅助
    # ----------------------------------------------------------------
    def _spinbox_row(self, lay, label, default, step, minimum=0.0, decimals=2):
        """创建 [标签] [−] [LineEdit] [+] 的一行 SpinBox，返回 LineEdit"""
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setMinimumWidth(56)
        lbl.setStyleSheet(INPUT_LABEL_STYLE)
        row.addWidget(lbl)

        minus_btn = QPushButton("−")
        minus_btn.setFixedSize(28, 28)
        minus_btn.setCursor(Qt.PointingHandCursor)
        minus_btn.setStyleSheet(_SPINBTN_SS)
        row.addWidget(minus_btn)

        edit = LineEdit()
        fmt = f"{{:.{decimals}f}}" if decimals > 0 else "{:.0f}"
        edit.setText(fmt.format(default))
        row.addWidget(edit, 1)

        plus_btn = QPushButton("+")
        plus_btn.setFixedSize(28, 28)
        plus_btn.setCursor(Qt.PointingHandCursor)
        plus_btn.setStyleSheet(_SPINBTN_SS)
        row.addWidget(plus_btn)

        lay.addLayout(row)

        def _inc():
            try:
                v = round(float(edit.text()) + step, max(decimals, 0))
                edit.setText(fmt.format(v))
            except ValueError:
                pass

        def _dec():
            try:
                v = round(float(edit.text()) - step, max(decimals, 0))
                if v >= minimum:
                    edit.setText(fmt.format(v))
            except ValueError:
                pass

        plus_btn.clicked.connect(_inc)
        minus_btn.clicked.connect(_dec)
        return edit

    # ----------------------------------------------------------------
    # Q 范围预览
    # ----------------------------------------------------------------
    def _update_q_preview(self):
        if not hasattr(self, '_q_preview'):
            return
        try:
            start = float(self.batch_q_start.text())
            end   = float(self.batch_q_end.text())
            step  = float(self.batch_q_step.text())
        except ValueError:
            self._q_preview.setText("")
            return
        if step <= 0 or start > end:
            self._q_preview.setText("<span style='color:#d32f2f;'>参数无效</span>")
            return
        values, v = [], start
        while v <= end + step * 0.01:
            values.append(round(v, 2))
            v += step
            if len(values) > 100:
                break
        count, max_show = len(values), 10
        tags = " ".join(
            f'<span style="background:#e8f4fd;color:#0078d4;padding:1px 6px;'
            f'border-radius:8px;font-size:11px;">{x}</span>'
            for x in values[:max_show]
        )
        if count > max_show:
            tags += (f' <span style="background:#f0f0f0;color:#888;padding:1px 6px;'
                     f'border-radius:8px;font-size:11px;">+{count - max_show}个</span>')
        self._q_preview.setText(f'将计算 <b>{count}</b> 个Q值：<br>{tags}')

    # ----------------------------------------------------------------
    # 坡度分母标签管理
    # ----------------------------------------------------------------
    def _apply_slope_preset(self, key):
        """切换坡度预设，更新按钮样式和标签列表"""
        for k, btn in self._slope_preset_btns:
            btn.setStyleSheet(_PRESET_ACTIVE_SS if k == key else _PRESET_SS)
        if key == "custom":
            self._slope_range_gen.setVisible(True)
            self._slope_values.clear()
            self._rebuild_slope_tags()
            return
        self._slope_range_gen.setVisible(False)
        self._slope_values = list(_SLOPE_PRESETS[key])
        self._rebuild_slope_tags()

    def _rebuild_slope_tags(self):
        """清空并重建标签芯片区"""
        layout = self._slope_tag_flow
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for val in sorted(self._slope_values):
            chip = _TagChip(val)
            chip.removed.connect(self._on_slope_tag_removed)
            layout.addWidget(chip)
        self._slope_tag_container.updateGeometry()
        self._slope_tag_container.update()

    def _on_slope_tag_removed(self, val):
        if val in self._slope_values:
            self._slope_values.remove(val)
        self._rebuild_slope_tags()

    def _add_slope_from_input(self):
        text = self._slope_add_edit.text().strip()
        if not text:
            return
        try:
            val = int(text)
        except ValueError:
            InfoBar.warning(title="输入无效", content="请输入正整数作为坡度分母",
                            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)
            return
        if val <= 0:
            InfoBar.warning(title="输入无效", content="坡度分母必须大于 0",
                            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)
            return
        if val in self._slope_values:
            InfoBar.warning(title="已存在", content=f"1/{val} 已在列表中，无需重复添加",
                            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)
            self._slope_add_edit.clear()
            return
        self._slope_values.append(val)
        self._rebuild_slope_tags()
        self._slope_add_edit.clear()

    def _clear_all_slopes(self):
        """一键清空所有坡度分母标签"""
        if not self._slope_values:
            InfoBar.warning(title="提示", content="坡度列表已为空",
                            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=1500)
            return
        n = len(self._slope_values)
        self._slope_values.clear()
        self._rebuild_slope_tags()
        InfoBar.success(title="已清空", content=f"已清空 {n} 个坡度分母",
                        parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)

    def _generate_slope_range(self):
        try:
            start = int(float(self._rg_start.text()))
            end   = int(float(self._rg_end.text()))
            step  = int(float(self._rg_step.text()))
        except ValueError:
            InfoBar.error(title="参数错误", content="起始/终止/步长输入无效，请输入数字",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=3000)
            return
        if step <= 0:
            InfoBar.error(title="参数错误", content="步长必须大于 0",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=3000)
            return
        if start > end:
            InfoBar.error(title="参数错误", content="起始值不能大于终止值",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=3000)
            return
        self._slope_values = list(range(start, end + 1, step))
        self._rebuild_slope_tags()
        InfoBar.success(title="已生成", content=f"已填入 {len(self._slope_values)} 个坡度分母",
                        parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)

    # ----------------------------------------------------------------
    # 工况管理
    # ----------------------------------------------------------------
    @staticmethod
    def _default_case():
        return {
            'Q': '0.5', 'material_idx': 0, 'length': '1000',
            'local_ratio': '0.15', 'D': '', 'inc_checked': True, 'inc_pct': '',
        }

    def _save_current_case(self):
        """将当前UI字段保存到当前工况数据"""
        if not (0 <= self._current_case_idx < len(self._cases)):
            return
        c = self._cases[self._current_case_idx]
        c['Q'] = self.Q_edit.text()
        c['material_idx'] = self.material_combo.currentIndex()
        c['length'] = self.length_edit.text()
        c['local_ratio'] = self.local_ratio_edit.text()
        c['D'] = self.D_edit.text()
        c['inc_checked'] = self.inc_cb.isChecked()
        c['inc_pct'] = self.inc_edit.text()

    def _load_case(self, idx):
        """将指定工况数据加载到UI字段"""
        if not (0 <= idx < len(self._cases)):
            return
        c = self._cases[idx]
        self.Q_edit.blockSignals(True)
        self.Q_edit.setText(c.get('Q', ''))
        self.Q_edit.blockSignals(False)
        self.material_combo.setCurrentIndex(c.get('material_idx', 0))
        self.length_edit.setText(c.get('length', '1000'))
        self.local_ratio_edit.setText(c.get('local_ratio', '0.15'))
        self.D_edit.setText(c.get('D', ''))
        self.inc_cb.setChecked(c.get('inc_checked', True))
        self.inc_edit.setText(c.get('inc_pct', ''))
        self._on_inc_toggle(None)

    def _switch_case(self, idx):
        """切换到指定工况"""
        if idx == self._current_case_idx:
            return
        self._save_current_case()
        self._current_case_idx = idx
        self._load_case(idx)
        self._rebuild_case_tags()
        self.data_changed.emit()

    def _add_case(self):
        """添加新工况（从当前工况复制参数，清空Q）"""
        if len(self._cases) >= MAX_CASES:
            InfoBar.warning(title="提示", content=f"最多支持 {MAX_CASES} 个工况",
                            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=3000)
            return
        self._save_current_case()
        new_case = dict(self._cases[self._current_case_idx])
        new_case['Q'] = ''
        self._cases.append(new_case)
        self._current_case_idx = len(self._cases) - 1
        self._load_case(self._current_case_idx)
        self._rebuild_case_tags()
        self._update_calc_btn_text()
        self.Q_edit.setFocus()
        self.data_changed.emit()

    def _remove_current_case(self):
        """删除当前工况"""
        if len(self._cases) <= 1:
            InfoBar.warning(title="提示", content="至少保留一个工况",
                            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)
            return
        idx = self._current_case_idx
        self._cases.pop(idx)
        if self._current_case_idx >= len(self._cases):
            self._current_case_idx = len(self._cases) - 1
        self._load_case(self._current_case_idx)
        self._rebuild_case_tags()
        self._update_calc_btn_text()
        InfoBar.success(title="已删除", content=f"工况{idx + 1} 已删除，当前 {len(self._cases)} 个工况",
                        parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)
        self.data_changed.emit()

    def _rebuild_case_tags(self):
        """重建工况标签芯片"""
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
            q_text = (case.get('Q', '') or '').strip() or '?'
            label = f"Q{_sub(i + 1)} = {q_text}"
            chip = _CaseTagChip(i, label, active=(i == self._current_case_idx))
            chip.switched.connect(self._switch_case)
            layout.addWidget(chip)
        n = len(self._cases)
        self._case_count_label.setText(f"{n} 个计算工况")
        self._case_tag_container.updateGeometry()
        self._case_tag_container.update()

    def _update_calc_btn_text(self):
        n = len(self._cases)
        if n <= 1:
            self._calc_btn.setText("计算")
        else:
            self._calc_btn.setText(f"计算全部 ({n}个工况)")

    def _on_q_text_changed(self, text):
        """Q值文本变化时同步更新当前工况数据和标签"""
        if not hasattr(self, '_cases'):
            return
        if 0 <= self._current_case_idx < len(self._cases):
            self._cases[self._current_case_idx]['Q'] = text
        self._rebuild_case_tags()

    def _apply_to_all_cases(self):
        """将当前工况的参数（不含Q）复制到所有其他工况"""
        self._save_current_case()
        src = self._cases[self._current_case_idx]
        keys = ('material_idx', 'length', 'local_ratio', 'D', 'inc_checked', 'inc_pct')
        for i, case in enumerate(self._cases):
            if i != self._current_case_idx:
                for k in keys:
                    case[k] = src[k]
        n_copied = len(self._cases) - 1
        if n_copied == 0:
            InfoBar.warning(title="提示", content="当前只有一个工况，无需复制",
                            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)
            return
        InfoBar.success(title="已复制", content=f"参数已复制到其余 {n_copied} 个工况",
                        parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)
        self.data_changed.emit()

    def _copy_from_prev_case(self):
        """从上一个工况复制参数（不含Q）到当前工况"""
        if self._current_case_idx == 0:
            InfoBar.warning(title="提示", content="当前已是第一个工况",
                            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)
            return
        self._save_current_case()
        prev = self._cases[self._current_case_idx - 1]
        curr = self._cases[self._current_case_idx]
        for k in ('material_idx', 'length', 'local_ratio', 'D', 'inc_checked', 'inc_pct'):
            curr[k] = prev[k]
        self._load_case(self._current_case_idx)
        InfoBar.success(title="已复制", content=f"已从工况{self._current_case_idx}复制参数",
                        parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)
        self.data_changed.emit()

    def _show_initial_help(self):
        """初始帮助页：含 GB 50288-2018 §6.7.2 规范条文"""
        h = HelpPageBuilder("有压管道水力计算", '请输入参数后点击"计算"按钮')

        h.section("支持功能")
        h.bullet_list([
            "单次计算：自动推荐经济管径，展示前5候选",
            "指定管径：可选输入管径D，查看指定管径的水力性能并与自动推荐对比",
            "批量计算：多管材/多工况扫描，生成 CSV + PDF 图表",
        ])
        h.text("管材支持：HDPE管、玻璃钢夹砂管、球墨铸铁管、预应力钢筒混凝土管、钢管")
        h.text("推荐规则：经济优先 → 妥协兜底 → 就近流速兜底")

        h.divider()
        h.section("规范依据：GB 50288—2018 §6.7.2")
        h.text("《灌溉与排水工程设计标准》 GB 50288—2018 第6.7.2条：灌溉输水管道设计应符合下列规定。")

        h.section("1  管道设计流量")
        h.text("管道设计流量应根据控制的灌溉面积计算确定。")

        h.section("2  水头损失公式")
        h.text("管道沿程水头损失和局部水头损失，可按下列公式计算：")
        h.formula("hf = f × L × Q^m / d^b", "沿程水头损失公式 (6.7.2-1)")
        h.formula("hj = \u03b6 \u00d7 V^2 / (2g)", "局部水头损失公式 (6.7.2-2)")
        h.hint("本程序局部损失采用简化比例法：hj = 局部损失比例 \u00d7 hf（默认比例 0.15，可在输入参数中修改），未逐项统计 \u03b6 值")

        h.section("符号说明")
        h.bullet_list([
            "hf —— 管道沿程水头损失 (m)",
            "f —— 摩阻系数，按表6.7.2取值",
            "L —— 管道长度 (m)",
            "Q —— 流量 (m\u00b3/h)",
            "m —— 流量指数，按表6.7.2取值",
            "d —— 管道内径 (mm)",
            "b —— 管径指数，按表6.7.2取值",
            "hj —— 管道局部水头损失 (m)",
            "\u03b6 —— 管道局部阻力系数",
            "V —— 管道流速 (m/s)",
            "g —— 重力加速度 (m/s\u00b2)",
        ])

        h.section("表6.7.2  各种管材的 f、m、b 值")
        h.table(
            ["管  材", "f", "m", "b"],
            [
                ["钢筋混凝土管 (n=0.013)", "1.312\u00d710\u2076", "2.00", "5.33"],
                ["钢筋混凝土管 (n=0.014)", "1.516\u00d710\u2076", "2.00", "5.33"],
                ["钢管、铸铁管", "6.25\u00d710\u2075", "1.90", "5.10"],
                ["硬聚氯乙烯塑料管 (PVC-U)", "0.948\u00d710\u2075", "1.77", "4.77"],
                ["铝合金管", "0.861\u00d710\u2075", "1.74", "4.74"],
                ["聚乙烯管 (PE)", "0.948\u00d710\u2075", "1.77", "4.77"],
                ["玻璃钢管 (RPMP)", "0.948\u00d710\u2075", "1.77", "4.77"],
            ]
        )

        h.section("3  经济流速")
        h.text("管道设计流速宜控制在经济流速 0.9m/s～1.5m/s，超出此范围时应经技术经济比较确定。")
        h.hint("本程序推荐规则：经济区 0.9≤V≤1.5 m/s 且 hf总≤5 m/km；妥协区 0.6≤V<0.9 m/s 且 hf总≤5 m/km")

        h.divider()
        h.section("加大流量比例规范表")
        h.table(
            ["设计流量 Q (m\u00b3/s)", "加大比例"],
            [
                ["Q < 1", "30%"],
                ["1 \u2264 Q < 5", "25%"],
                ["5 \u2264 Q < 20", "20%"],
                ["20 \u2264 Q < 50", "15%"],
                ["50 \u2264 Q < 100", "10%"],
                ["Q \u2265 100", "5%"],
            ]
        )

        self.result_view.setHtml(h.build())

    # ================================================================
    # 计算（支持多工况）
    # ================================================================
    def _parse_case(self, case, case_num):
        """解析单个工况数据，返回 PressurePipeInput 或 raise ValueError"""
        q_text = (case.get('Q', '') or '').strip()
        if not q_text:
            raise ValueError(f"工况{case_num}: 请输入设计流量 Q")
        try:
            Q = float(q_text)
        except ValueError:
            raise ValueError(f"工况{case_num}: 设计流量 Q 输入无效")
        if Q <= 0:
            raise ValueError(f"工况{case_num}: Q 必须大于 0")

        length_text = (case.get('length', '') or '').strip()
        if not length_text:
            raise ValueError(f"工况{case_num}: 请输入管长 L")
        try:
            length_m = float(length_text)
        except ValueError:
            raise ValueError(f"工况{case_num}: 管长 L 输入无效")
        if length_m <= 0:
            raise ValueError(f"工况{case_num}: 管长 L 必须大于 0")

        mat_idx = case.get('material_idx', 0)
        if mat_idx < 0 or mat_idx >= len(self._mat_keys):
            mat_idx = 0
        mat_key = self._mat_keys[mat_idx]

        manual_pct = None
        if case.get('inc_checked', True):
            txt = (case.get('inc_pct', '') or '').strip()
            if txt:
                try:
                    manual_pct = float(txt)
                except ValueError:
                    pass
        else:
            manual_pct = 0.0

        ratio_text = (case.get('local_ratio', '') or '').strip()
        if not ratio_text:
            raise ValueError(f"工况{case_num}: 请输入局部损失比例")
        try:
            local_ratio = float(ratio_text)
        except ValueError:
            raise ValueError(f"工况{case_num}: 局部损失比例输入无效")
        if local_ratio < 0:
            raise ValueError(f"工况{case_num}: 局部损失比例不能为负数")

        d_text = (case.get('D', '') or '').strip()
        manual_D = None
        if d_text:
            try:
                manual_D = float(d_text)
            except ValueError:
                raise ValueError(f"工况{case_num}: 管径 D 输入无效")
            if manual_D <= 0:
                raise ValueError(f"工况{case_num}: 指定管径 D 必须大于 0")

        return PressurePipeInput(
            Q=Q, material_key=mat_key,
            length_m=length_m,
            manual_increase_percent=manual_pct,
            local_loss_ratio=local_ratio,
            manual_D=manual_D,
        )

    def _calculate(self):
        self._save_current_case()
        self._all_results = []
        errors = []

        for i, case in enumerate(self._cases):
            try:
                inp = self._parse_case(case, i + 1)
            except (ValueError, TypeError) as ex:
                errors.append(str(ex))
                continue
            result = recommend_diameter(inp)
            self._all_results.append((i, inp, result))
        self._last_errors = list(errors)

        if errors:
            InfoBar.error(title="输入错误", content="\n".join(errors),
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=6000)
        if not self._all_results:
            if errors:
                err_txt = "部分或全部工况计算失败：\n\n" + "\n".join(errors)
                self._export_plain_text = err_txt
                load_formula_page(self.result_view, plain_text_to_formula_html(err_txt))
                self.notebook.setCurrentIndex(0)
                self.data_changed.emit()
            return

        # 向后兼容
        _, _, first_result = self._all_results[0]
        self.current_result = first_result
        self._export_plain_text = "\n\n".join(
            f"===== 工况{idx+1} =====\n{res.calc_steps}"
            for idx, _, res in self._all_results
        )

        # 显示结果
        self._display_all_results()
        self.data_changed.emit()

    def _build_result_card_html(self, case_idx, inp, result):
        """为单个工况构建结果HTML（方案D：分段标题 + 迷你摘要条 + 候选表标题 + 推荐行高亮）"""
        rec = result.recommended
        mat_name = PIPE_MATERIALS[inp.material_key]["name"]
        q_label = f"Q{_sub(case_idx + 1)} = {inp.Q} m³/s"
        subtitle = f"{q_label} · {_e(mat_name)} · L={inp.length_m}m"

        # 分段标题（带锚点，仅多工况时显示）
        _multi = len(self._all_results) > 1
        if _multi:
            case_header = f"""
        <div id="pp-case-{case_idx}" style="display:flex;align-items:center;gap:12px;
                    margin:{'0' if case_idx == 0 else '24px'} 0 8px;padding:10px 18px;
                    background:linear-gradient(135deg,#e3f2fd,#e8eaf6);
                    border-left:5px solid #1565c0;border-radius:0 10px 10px 0;">
            <span style="font-size:15px;font-weight:800;color:#1565c0;white-space:nowrap;">
                工况 {case_idx+1}</span>
            <span style="font-size:13px;color:#555;font-weight:500;">
                <span style="font-weight:700;color:#1565c0;font-size:14px;">
                    Q = {inp.Q} m³/s</span> · {_e(mat_name)} · L = {inp.length_m} m
            </span>
        </div>"""
        else:
            case_header = ""

        if not rec:
            return case_header + f"""
            <div style="background:#FFF3E0;border:2px solid {E};border-radius:10px;
                        padding:16px 20px;margin:8px 0;">
                <p style="color:{E};font-weight:bold;">工况{case_idx+1} 无可用推荐结果</p>
                <p style="font-size:12px;color:{T2};">{subtitle}</p>
                <p>{_e(result.reason)}</p>
            </div>"""

        is_manual = (result.category == "指定")
        cat_color = {"经济": S, "妥协": W, "兜底": E}.get(
            rec.category if is_manual else result.category, T2)
        badge_text = f"用户指定({rec.category})" if is_manual else f"{result.category}区推荐"

        # 迷你摘要条
        sep_style = f"width:1px;height:28px;background:#e0e0e0;flex-shrink:0;"
        html = case_header + f"""
        <div style="display:flex;gap:15px;margin:8px 0;padding:12px 16px;
                    background:linear-gradient(135deg,#f0fdf4,#ecfdf5);border-radius:10px;
                    border:1px solid {cat_color}40;align-items:center;flex-wrap:wrap;
                    font-family:'Microsoft YaHei',sans-serif;">
            <div style="text-align:center;">
                <div style="font-size:11px;color:#888;">管材</div>
                <div style="font-size:12px;color:#1a1a1a;">{_e(mat_name).replace('预应力钢筒混凝土管', '预应力<br>钢筒混凝土管').replace('(', '<br>(')}</div>
            </div>
            <div style="{sep_style}"></div>
            <div style="text-align:center;">
                <div style="font-size:11px;color:#888;">推荐管径</div>
                <div style="font-size:15px;font-weight:700;color:{cat_color};">
                    D = {rec.D*1000:.0f} mm</div>
            </div>
            <div style="{sep_style}"></div>
            <div style="text-align:center;">
                <div style="font-size:11px;color:#888;">有压流速</div>
                <div style="font-size:15px;font-weight:700;color:{cat_color};">
                    {rec.V_press:.4f} m/s</div>
            </div>
            <div style="{sep_style}"></div>
            <div style="text-align:center;">
                <div style="font-size:11px;color:#888;">总水损</div>
                <div style="font-size:14px;font-weight:700;color:#1a1a1a;">
                    {rec.hf_total_km:.4f} m/km</div>
            </div>
            <div style="{sep_style}"></div>
            <div style="text-align:center;">
                <div style="font-size:11px;color:#888;">类别</div>
                <div style="font-size:13px;font-weight:700;color:{cat_color};">
                    {_e(badge_text)}</div>
            </div>
            <div style="{sep_style}"></div>
            <div style="text-align:center;">
                <div style="font-size:11px;color:#888;">管长折算</div>
                <div style="font-size:14px;font-weight:700;color:#1a1a1a;">
                    {rec.h_loss_total_m:.4f} m</div>
            </div>
        </div>"""

        # 自动推荐对比条（仅指定D模式，且自动推荐与指定D不同时）
        auto_rec = result.auto_recommended
        if is_manual and auto_rec is not None and abs(auto_rec.D - rec.D) > 1e-6:
            ac = {"经济": S, "妥协": W, "兜底": E}.get(auto_rec.category, T2)
            html += f"""
        <div style="display:flex;gap:14px;margin:2px 0 6px;padding:8px 18px;
                    background:{CARD};border:1px dashed {ac};border-radius:8px;
                    align-items:center;flex-wrap:wrap;opacity:0.85;">
            <span style="background:{ac};color:white;padding:2px 10px;
                         border-radius:10px;font-size:11px;font-weight:bold;">
                自动推荐({auto_rec.category}区)</span>
            <span style="font-size:12px;color:{T2};">D = {auto_rec.D}m ({auto_rec.D*1000:.0f}mm)</span>
            <span style="font-size:12px;color:{T2};">V = {auto_rec.V_press:.4f} m/s</span>
            <span style="font-size:12px;color:{T2};">hf总 = {auto_rec.hf_total_km:.4f} m/km</span>
        </div>"""

        # 图例条
        html += """
        <div style="display:flex;gap:14px;margin:6px 0 4px;font-size:12px;color:#888;
                    align-items:center;flex-wrap:wrap;">"""
        for dot_color, name, desc in [
            ("#2e7d32", "经济", "V:0.9~1.5"),
            ("#e67e22", "妥协", "V:0.6~0.9"),
            ("#c62828", "兜底", "就近流速"),
        ]:
            html += f"""
            <span style="display:inline-flex;align-items:center;gap:4px;">
                <span style="width:8px;height:8px;border-radius:50%;background:{dot_color};
                             display:inline-block;"></span> {name} {desc}</span>"""
        html += f"""
            <span style="color:#bbb;font-size:11px;margin-left:auto;">
                hf总 ≤ 5 m/km 为合规</span>
        </div>"""

        # 候选表
        _CAT_COLORS = {"经济": "#2e7d32", "妥协": "#e67e22", "兜底": "#c62828"}
        candidates = result.top_candidates
        if candidates:
            _tbl_title = f"候选管径对比（工况{case_idx+1}：Q = {inp.Q} m³/s）" if _multi else "候选管径对比"
            html += f"""
        <div style="font-size:13px;font-weight:600;color:#555;margin:10px 0 4px;
                    padding-left:4px;border-left:3px solid #90caf9;">
            {_tbl_title}</div>"""
            html += """
        <table style="width:100%;border-collapse:collapse;font-size:13px;margin:4px 0 12px;">
            <tr style="background:#f8f9fa;">
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">#</th>
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">D(m)</th>
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">D(mm)</th>
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">V(m/s)</th>
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">hf(m/km)</th>
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">hj(m/km)</th>
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">hf总(m/km)</th>
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">H损(m)</th>
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">类别</th>
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;"></th>
            </tr>"""
            for i, c in enumerate(candidates):
                is_rec = (rec and abs(c.D - rec.D) < 1e-6)
                is_user = "用户指定" in c.flags
                if is_rec:
                    row_style = ("background:linear-gradient(135deg,#e8f5e9,#f1f8e9);"
                                 "border-left:4px solid #2e7d32;")
                    td_extra = "font-weight:600;"
                elif is_user:
                    row_style = "background:#FFF8E1;"
                    td_extra = "font-weight:600;"
                else:
                    row_style = ""
                    td_extra = ""
                cc = _CAT_COLORS.get(c.category, "#666")
                badge_html = ""
                if is_rec:
                    badge_html = ('<span style="display:inline-block;background:#2e7d32;color:#fff;'
                                  'padding:2px 8px;border-radius:10px;font-size:11px;'
                                  'font-weight:600;">★ 推荐</span>')
                elif is_user:
                    badge_html = ('<span style="display:inline-block;background:#e67e22;color:#fff;'
                                  'padding:2px 8px;border-radius:10px;font-size:11px;'
                                  'font-weight:600;">★ 指定</span>')
                td_s = f"padding:7px 8px;text-align:center;border-bottom:1px solid #f0f0f0;{td_extra}"
                html += f"""
            <tr style="{row_style}">
                <td style="{td_s}">{i+1}</td>
                <td style="{td_s}">{c.D:.3f}</td>
                <td style="{td_s}">{c.D*1000:.0f}</td>
                <td style="{td_s}">{c.V_press:.4f}</td>
                <td style="{td_s}">{c.hf_friction_km:.4f}</td>
                <td style="{td_s}">{c.hf_local_km:.4f}</td>
                <td style="{td_s}">{c.hf_total_km:.4f}</td>
                <td style="{td_s}">{c.h_loss_total_m:.4f}</td>
                <td style="{td_s}color:{cc};font-weight:bold;">{_e(c.category)}</td>
                <td style="{td_s}">{badge_html}</td>
            </tr>"""
            html += "\n        </table>"

        return html

    def _build_nav_bar_html(self):
        """构建顶部快捷导航条HTML（方案D）"""
        if len(self._all_results) <= 1:
            return ""
        _NAV_CAT_COLORS = {"经济": ("#2e7d32", "#e8f5e9"), "妥协": ("#e67e22", "#fff3e0"),
                           "兜底": ("#c62828", "#ffebee"), "指定": ("#1565c0", "#e3f2fd"),
                           "无可用": ("#999", "#f5f5f5")}
        btns = []
        for case_idx, inp, result in self._all_results:
            rec = result.recommended
            cat = result.category
            fg, bg = _NAV_CAT_COLORS.get(cat, ("#999", "#f5f5f5"))
            q_text = f"Q{_sub(case_idx + 1)}={inp.Q}"
            if rec:
                summary = f"D={rec.D*1000:.0f}mm {rec.category if cat == '指定' else cat}"
            else:
                summary = "无结果"
            btns.append(
                f'<a href="javascript:void(0)" onclick="document.getElementById(\'pp-case-{case_idx}\')'
                f'.scrollIntoView({{behavior:\'smooth\',block:\'start\'}})" '
                f'style="display:inline-flex;align-items:center;gap:6px;padding:6px 14px;'
                f'border:1.5px solid #1565c0;border-radius:20px;background:#fff;color:#1565c0;'
                f'font-size:13px;font-weight:600;cursor:pointer;text-decoration:none;'
                f'transition:background 0.15s;">'
                f'<span style="font-weight:800;">{_e(q_text)}</span>'
                f'<span style="font-size:11px;color:{fg};font-weight:500;background:{bg};'
                f'padding:1px 8px;border-radius:8px;">{_e(summary)}</span></a>'
            )
        return (
            '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;'
            'margin:0 0 16px;padding:10px 16px;background:#fff;border:1px solid #e0e0e0;'
            'border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,0.06);">'
            '<span style="font-size:12px;color:#999;font-weight:500;margin-right:4px;">'
            '快捷导航：</span>' + ''.join(btns) + '</div>'
        )

    def _display_all_results(self):
        """显示所有工况的结果（导航条 + 分段标题 + 多卡片堆叠）"""
        nav_html = self._build_nav_bar_html()

        parts = []
        for case_idx, inp, result in self._all_results:
            parts.append(self._build_result_card_html(case_idx, inp, result))

        full_html = nav_html + "\n".join(parts)

        if self.detail_cb.isChecked():
            _multi = len(self._all_results) > 1
            for case_idx, inp, result in self._all_results:
                if result.calc_steps:
                    _dtitle = f'工况 {case_idx+1}（Q = {inp.Q} m³/s）详细计算过程' if _multi else '详细计算过程'
                    full_html += (f'<h3 style="margin:20px 0 8px;padding:8px 14px;'
                                  f'background:#fafafa;border-left:4px solid #1565c0;'
                                  f'border-radius:0 8px 8px 0;font-size:15px;'
                                  f'font-weight:700;color:#1565c0;">'
                                  f'{_dtitle}</h3>')
                    full_html += plain_text_to_formula_html(result.calc_steps)

        load_formula_page(self.result_view, full_html)
        self.notebook.setCurrentIndex(0)

    def _clear(self):
        self._cases = [self._default_case()]
        self._current_case_idx = 0
        self._all_results = []
        self._last_errors = []
        self._load_case(0)
        self._rebuild_case_tags()
        self._update_calc_btn_text()
        self.current_result = None
        self._export_plain_text = ""
        self._show_initial_help()
        InfoBar.success(title="已清空", content="所有工况和计算结果已重置",
                        parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)
        self.data_changed.emit()

    # ================================================================
    # Word 导出
    # ================================================================
    def _info_parent(self):
        """获取InfoBar的父窗口（向上查找主窗口）"""
        w = self.window()
        return w if w else self

    def _export_word(self):
        if not WORD_EXPORT_AVAILABLE:
            InfoBar.warning("缺少依赖",
                "Word导出需要安装 python-docx、latex2mathml、lxml。请执行: pip install python-docx latex2mathml lxml",
                parent=self._info_parent(), duration=6000, position=InfoBarPosition.TOP)
            return
        if not self._all_results:
            InfoBar.warning("提示", "请先进行计算后再导出。",
                parent=self._info_parent(), duration=3000, position=InfoBarPosition.TOP)
            return
        meta = load_meta()
        auto_purpose = build_calc_purpose('pressure_pipe', project=meta.project_name)
        dlg = ExportConfirmDialog('pressure_pipe', '有压管道水力计算书', auto_purpose, parent=self._info_parent())
        from PySide6.QtWidgets import QDialog
        if dlg.exec() != QDialog.Accepted:
            return
        self._word_export_meta = dlg.get_meta()
        self._word_export_purpose = dlg.get_calc_purpose()
        self._word_export_refs = dlg.get_references()
        filepath, _ = QFileDialog.getSaveFileName(self, "保存Word报告", "", "Word文档 (*.docx);;所有文件 (*.*)")
        if not filepath:
            return
        try:
            self._build_word_report(filepath)
            InfoBar.success("导出成功", f"Word报告已保存到: {filepath}",
                parent=self._info_parent(), duration=4000, position=InfoBarPosition.TOP)
            ask_open_file(filepath, self._info_parent())
        except PermissionError:
            InfoBar.error("文件被占用", "请关闭同名Word文档后重试。",
                parent=self._info_parent(), duration=8000, position=InfoBarPosition.TOP)
        except Exception as e:
            InfoBar.error("导出失败", str(e),
                parent=self._info_parent(), duration=5000, position=InfoBarPosition.TOP)

    def _build_word_report(self, filepath):
        """构建Word报告文档（工程产品运行卡格式），支持多工况"""
        meta = getattr(self, '_word_export_meta', load_meta())
        purpose = getattr(self, '_word_export_purpose', '')
        refs = getattr(self, '_word_export_refs', REFERENCES_BASE.get('pressure_pipe', []))

        # 取第一个工况的管材名作为封面描述
        _, first_inp, _ = self._all_results[0]
        first_mat_name = PIPE_MATERIALS[first_inp.material_key]["name"]
        n_cases = len(self._all_results)
        desc = f'有压管道水力计算（{first_mat_name}）' if n_cases == 1 else f'有压管道水力计算（{n_cases}个工况）'

        doc = create_engineering_report_doc(
            meta=meta,
            calc_title='有压管道水力计算书',
            calc_content_desc=desc,
            calc_purpose=purpose,
            references=refs,
            calc_program_text=f'渠系建筑物水力计算系统 V1.0\n{desc}',
        )
        doc.add_page_break()

        # 5、基础公式
        doc_add_eng_h(doc, '5、基础公式')
        doc_add_eng_body(doc, '根据《灌溉与排水工程设计标准》(GB 50288-2018) 第6.7.2条：')
        doc_add_formula(doc, r'h_f = f \times \frac{L \times Q^m}{d^b}', '沿程水头损失公式：')
        doc_add_formula(doc, r'h_j = \xi_j \times h_f', '局部水头损失（按沿程损失比例简化）：')
        doc_add_formula(doc, r'V = \frac{4Q}{\pi D^2}', '管道流速公式：')
        doc_add_eng_body(doc, '经济流速范围：0.9 m/s ≤ V ≤ 1.5 m/s。')

        # 6、计算过程
        doc_add_eng_h(doc, '6、计算过程')
        doc_render_calc_text_eng(doc, self._export_plain_text or '',
                                  skip_title_keyword='有压管道水力计算结果')

        # 7、计算结果汇总（逐工况）
        for ri, (case_idx, inp, result) in enumerate(self._all_results):
            rec = result.recommended
            if rec is None:
                continue
            mat_key = inp.material_key
            mat_name = PIPE_MATERIALS[mat_key]["name"]
            mat_info = PIPE_MATERIALS[mat_key]
            section_prefix = f'7.{ri+1}' if n_cases > 1 else '7'
            title = f'{section_prefix}、工况{case_idx+1} 计算结果汇总' if n_cases > 1 else '7、计算结果汇总'
            doc_add_eng_h(doc, title)
            summary_items = [
                ("管材类型", mat_name),
                ("管材系数", f"f = {mat_info['f']}, m = {mat_info['m']}, b = {mat_info['b']}"),
                ("设计流量 Q", f"{inp.Q} m³/s"),
                ("管长 L", f"{inp.length_m} m"),
                ("局部损失比例", str(inp.local_loss_ratio)),
            ]
            if rec.increase_pct > 0:
                summary_items.append(("加大流量比例", f"{rec.increase_pct:.1f}%"))
                summary_items.append(("加大后流量", f"{rec.Q_increased:.4f} m³/s"))
            summary_items += [
                ("推荐管径 D", f"{rec.D} m ({rec.D*1000:.0f} mm)"),
                ("推荐类别", result.category),
                ("有压流速 V", f"{rec.V_press:.4f} m/s"),
                ("沿程水损", f"{rec.hf_friction_km:.4f} m/km"),
                ("局部水损", f"{rec.hf_local_km:.4f} m/km"),
                ("总水损", f"{rec.hf_total_km:.4f} m/km"),
                ("按管长折算总损失", f"{rec.h_loss_total_m:.4f} m"),
            ]
            doc_add_result_table(doc, summary_items)

            # 候选管径对比表
            candidates = result.top_candidates
            if candidates:
                sec_num = f'8.{ri+1}' if n_cases > 1 else '8'
                doc_add_eng_h(doc, f'{sec_num}、候选管径对比表')
                headers = ["D(m)", "D(mm)", "V(m/s)", "hf(m/km)", "hj(m/km)",
                            "hf总(m/km)", "H损(m)", "类别"]
                data = []
                for c in candidates:
                    data.append([
                        f"{c.D:.3f}", f"{c.D*1000:.0f}", f"{c.V_press:.4f}",
                        f"{c.hf_friction_km:.4f}", f"{c.hf_local_km:.4f}",
                        f"{c.hf_total_km:.4f}", f"{c.h_loss_total_m:.4f}",
                        c.category,
                    ])
                doc_add_styled_table(doc, headers, data,
                                      highlight_col=0, highlight_val=f"{rec.D:.3f}",
                                      with_full_border=True)

        doc.save(filepath)

    # ================================================================
    # 输出选项联动
    # ================================================================
    def _has_any_output(self):
        """4个输出复选框是否至少勾选了一项"""
        return (self.out_csv_cb.isChecked() or self.out_pdf_cb.isChecked()
                or self.out_merged_cb.isChecked() or self.out_png_cb.isChecked())

    def _on_output_option_changed(self):
        """任一输出复选框变化时，更新按钮可用性和提示"""
        has = self._has_any_output()
        self.batch_btn.setEnabled(has)
        self._no_output_hint.setVisible(not has)

    def _on_pdf_cb_toggled(self, state):
        """图表PDF取消时 → 自动禁用并取消合并PDF；勾选时 → 恢复合并PDF可用"""
        pdf_on = self.out_pdf_cb.isChecked()
        if not pdf_on:
            self.out_merged_cb.setChecked(False)
        self.out_merged_cb.setEnabled(pdf_on)

    # ================================================================
    # 批量计算
    # ================================================================
    def _start_batch(self):
        # 安全校验：至少勾选一项输出
        if not self._has_any_output():
            InfoBar.warning(title="无输出选项",
                            content="请在【输出选项】中至少勾选一项再开始计算",
                            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return

        # 选择输出目录
        output_dir = QFileDialog.getExistingDirectory(self, "选择输出目录", "")
        if not output_dir:
            return

        # 解析 Q 范围（从 SpinBox 读取）
        try:
            q_start = float(self.batch_q_start.text().strip())
            q_end   = float(self.batch_q_end.text().strip())
            q_step  = float(self.batch_q_step.text().strip())
            if q_step <= 0 or q_start > q_end:
                raise ValueError("参数无效")
            import numpy as np
            q_values = np.round(np.arange(q_start, q_end + q_step * 0.5, q_step), 2)
        except (ValueError, TypeError):
            InfoBar.error(title="参数错误", content="Q范围参数无效，请检查起始/终止/步长",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return

        # 解析无压对比参数（从标签芯片列表读取）
        if self.batch_unpr_cb.isChecked():
            slope_denoms = sorted(self._slope_values)
            if not slope_denoms:
                InfoBar.error(title="参数错误", content="请至少添加一个坡度分母",
                              parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
                return
            n_text = self.batch_n_edit.text().strip()
            if not n_text:
                InfoBar.error(title="参数错误", content="请输入糙率 n",
                              parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
                return
            try:
                n_unpr = float(n_text)
            except ValueError:
                InfoBar.error(title="参数错误", content="糙率 n 输入无效",
                              parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
                return
        else:
            slope_denoms = []
            n_unpr = 0.0

        # 管长
        bl_text = self.batch_length_edit.text().strip()
        if not bl_text:
            InfoBar.error(title="参数错误", content="请输入管长 L",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return
        try:
            length_m = float(bl_text)
            if length_m <= 0:
                raise ValueError
        except ValueError:
            InfoBar.error(title="参数错误", content="管长 L 输入无效",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return

        # 管材
        selected_mats = [k for k, cb in self._mat_cbs.items() if cb.isChecked()]
        if not selected_mats:
            InfoBar.error(title="参数错误", content="至少选择一种管材",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return

        lr_text = self.batch_local_ratio_edit.text().strip()
        if not lr_text:
            InfoBar.error(title="参数错误", content="请输入局部损失比例",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return
        try:
            local_ratio = float(lr_text)
            if local_ratio < 0:
                raise ValueError
        except ValueError:
            InfoBar.error(title="参数错误", content="局部损失比例输入无效",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return

        config = BatchScanConfig(
            q_values=q_values,
            slope_denominators=slope_denoms,
            diameter_values=DEFAULT_DIAMETER_SERIES,
            materials=selected_mats,
            n_unpr=n_unpr,
            length_m=length_m,
            local_loss_ratio=local_ratio,
            output_dir=output_dir,
            output_csv=self.out_csv_cb.isChecked(),
            output_pdf_charts=self.out_pdf_cb.isChecked(),
            output_merged_pdf=self.out_merged_cb.isChecked(),
            output_subplot_png=self.out_png_cb.isChecked(),
        )

        # 切换UI
        self.batch_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.batch_progress.setVisible(True)
        self.batch_progress.setValue(0)
        self.batch_status_label.setVisible(True)
        self.batch_status_label.setText("正在准备...")
        self.batch_log.clear()
        self.notebook.setCurrentIndex(1)

        # 启动线程
        self._batch_worker = _BatchWorker(config, self)
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.finished.connect(self._on_batch_finished)
        self._batch_worker.error.connect(self._on_batch_error)
        self._batch_worker.start()

    def _cancel_batch(self):
        if self._batch_worker:
            self._batch_worker.cancel()
            self.batch_status_label.setText("正在取消...")

    def _on_batch_progress(self, current, total, msg):
        if total > 0:
            self.batch_progress.setMaximum(total)
            self.batch_progress.setValue(current)
        self.batch_status_label.setText(msg)

    def _on_batch_finished(self, result: BatchScanResult):
        self.batch_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.batch_progress.setVisible(False)
        self.batch_status_label.setText("完成")

        for log in result.logs:
            self.batch_log.append(log)

        if result.csv_path:
            self.batch_log.append(f"\nCSV 路径: {result.csv_path}")
        if result.merged_pdf:
            self.batch_log.append(f"合并PDF: {result.merged_pdf}")
        self.batch_log.append(f"\n共生成 {len(result.generated_pdfs)} 个PDF, {len(result.generated_pngs)} 个PNG")

        InfoBar.success(
            title="批量计算完成",
            content=f"CSV + {len(result.generated_pdfs)} PDF 已输出",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
        )

    def _on_batch_error(self, msg):
        self.batch_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.batch_progress.setVisible(False)
        self.batch_status_label.setText("出错")
        self.batch_log.append(f"错误:\n{msg}")

        # 持久化到日志文件，方便远程排查
        try:
            import datetime
            log_dir = os.path.join(os.path.expanduser("~"), "CanalHydCalc_logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "batch_error.log")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 60}\n")
                f.write(f"时间: {datetime.datetime.now()}\n")
                f.write(msg)
                f.write("\n")
            self.batch_log.append(f"\n日志已保存至: {log_path}")
        except Exception:
            pass

        # InfoBar 只显示最后一行摘要
        lines = msg.strip().splitlines()
        summary = lines[-1] if lines else str(msg)
        if len(summary) > 120:
            summary = summary[:120] + "..."
        InfoBar.error(title="批量计算失败", content=summary,
                      parent=self, position=InfoBarPosition.TOP_RIGHT, duration=8000)

    # ================================================================
    # 项目保存/加载
    # ================================================================
    def to_project_dict(self):
        """序列化当前状态用于项目保存。"""
        self._save_current_case()
        return {
            'cases': copy.deepcopy(self._cases),
            'current_case_idx': int(self._current_case_idx),
            'last_errors': list(self._last_errors),
            'notebook_idx': self.notebook.currentIndex() if hasattr(self, 'notebook') else 0,
        }

    def from_project_dict(self, data):
        """从项目数据恢复面板状态。"""
        if not isinstance(data, dict):
            return
        cases = data.get('cases')
        if isinstance(cases, list) and cases:
            self._cases = cases
        else:
            self._cases = [self._default_case()]

        idx = data.get('current_case_idx', 0)
        self._current_case_idx = idx if isinstance(idx, int) else 0
        if self._current_case_idx < 0 or self._current_case_idx >= len(self._cases):
            self._current_case_idx = 0

        self._all_results = []
        self.current_result = None
        self._last_errors = list(data.get('last_errors', []) or [])
        self._load_case(self._current_case_idx)
        self._rebuild_case_tags()
        self._update_calc_btn_text()

        if self._last_errors:
            err_txt = "部分或全部工况计算失败：\n\n" + "\n".join(self._last_errors)
            self._export_plain_text = err_txt
            load_formula_page(self.result_view, plain_text_to_formula_html(err_txt))
            if hasattr(self, 'notebook'):
                self.notebook.setCurrentIndex(0)
        else:
            self._export_plain_text = ""
            self._show_initial_help()
            if hasattr(self, 'notebook'):
                tab_idx = data.get('notebook_idx')
                if isinstance(tab_idx, int):
                    tab_idx = max(0, min(tab_idx, self.notebook.count() - 1))
                    self.notebook.setCurrentIndex(tab_idx)
