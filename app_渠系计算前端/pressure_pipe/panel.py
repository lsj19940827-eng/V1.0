# -*- coding: utf-8 -*-
"""
有压管道设计面板 —— QWidget 版本

功能：单次计算（推荐管径 + 候选表 + 详细过程）、批量计算（后台线程 + 进度 + CSV/PDF）
"""

import sys
import os
import copy
import math
import html as html_mod
from dataclasses import asdict, fields, is_dataclass
from types import SimpleNamespace

_pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_pkg_root, "calc_渠系计算算法内核"))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QSplitter, QFrame, QTabWidget, QTextEdit, QFileDialog,
    QScrollArea, QProgressBar, QPushButton, QLayout, QRadioButton, QButtonGroup,
)
from PySide6.QtCore import Qt, QThread, Signal, QRect, QPoint, QSize, QTimer
from PySide6.QtGui import QPainter, QPen, QColor
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    _WEB_ENGINE_IMPORT_ERROR = None
except ImportError as _web_engine_error:
    QWebEngineView = None
    _WEB_ENGINE_IMPORT_ERROR = _web_engine_error

from qfluentwidgets import (
    ComboBox, PushButton, PrimaryPushButton, LineEdit,
    CheckBox, InfoBar, InfoBarPosition
)

from 有压管道设计 import (
    PIPE_MATERIALS,
    DEFAULT_Q_RANGE, DEFAULT_SLOPE_DENOMINATORS,
    SPEC_672_TEXT,
    PressurePipeInput, DiameterCandidate, RecommendationResult,
    get_flow_increase_percent, evaluate_single_diameter,
    recommend_diameter, build_detailed_process_text,
    run_batch_scan, BatchScanConfig, BatchScanResult,
)
from calc_渠系计算算法内核.pe_pipe_catalog import (
    PE_STANDARD,
    get_pe_nominal_diameter_guidance,
    get_pe_pipe_spec,
    get_pe_pressure_options,
    get_pe_sdr,
)
from calc_渠系计算算法内核.pipe_product_catalog import (
    DI_PRODUCT_STANDARD,
    DUCTILE_IRON_CLASS_OPTIONS,
    FRPM_PRODUCT_STANDARD,
    PCCP_VARIANTS,
    format_pipe_product_spec,
    get_catalog_family,
    get_pipe_product_spec,
    get_ductile_iron_specs,
)

from app_渠系计算前端.styles import (
    P, S, W, E, BG, CARD, BD, T1, T2,
    INPUT_LABEL_STYLE, INPUT_SECTION_STYLE, INPUT_HINT_STYLE
)
from app_渠系计算前端.formula_renderer import (
    plain_text_to_formula_html, load_formula_page, make_plain_html,
    HelpPageBuilder,
)
from app_渠系计算前端.pressure_pipe.diameter_explanation import (
    diameter_summary_html as build_diameter_explanation_html, diameter_candidate_row_html,
    add_diameter_summary_to_word, add_candidate_diameters_to_word,
)
from app_渠系计算前端.pressure_pipe.result_details import concise_process_text
from app_渠系计算前端.pressure_pipe.flow_comparison import (
    compare_flows, flow_summary_html, velocity_note,
)
from app_渠系计算前端.pressure_pipe.slope_controls import SlopeComparisonControls
from app_渠系计算前端.pressure_pipe.steel_controls import (
    STEEL_CASE_DEFAULTS, SteelPipeControls, parse_steel_state, normalize_steel_case,
)
from app_渠系计算前端.pressure_pipe.steel_sizing_explanation import (
    steel_sizing_html, add_steel_sizing_to_word, steel_result_heading,
)
from app_渠系计算前端.increase_input_helper import (
    INCREASE_MODE_PERCENT,
    INCREASE_MODE_Q_INCREASED,
    build_increase_hint_text,
    build_increase_summary_lines,
    normalize_increase_mode,
    resolve_increase_input,
)
from app_渠系计算前端.webview_compat import create_web_view, scroll_view_to_anchor
from app_渠系计算前端.result_navigation import (
    CaseResultNavigationBar,
    apply_case_result_state,
    build_result_nav_bar,
    build_result_navigation_head,
    case_result_jump_hint,
    collect_case_result_state,
    has_fresh_case_results,
    is_case_result_stale,
    make_case_result_anchor,
    sync_case_result_nav_bar,
    wrap_case_result_block,
)
from app_渠系计算前端.export_utils import (
    WORD_EXPORT_AVAILABLE, ask_open_file,
    create_engineering_report_doc, doc_add_eng_h, doc_add_eng_body,
    doc_add_formula, doc_render_calc_text_eng, doc_add_result_table,
    doc_add_styled_table,
)
from app_渠系计算前端.report_meta import (
    ExportConfirmDialog, build_calc_purpose, REFERENCES_BASE,
    PRESSURE_PIPE_PRODUCT_REFERENCES, load_meta,
)

from app_渠系计算前端.case_manager import (
    CaseTagNavigator as _CaseTagNavigator,
    CaseWorkbenchStrip as _CaseWorkbenchStrip,
)


def _e(s):
    return html_mod.escape(str(s))


def _fmt_g(value):
    """将规格数值格式化为不带多余小数的工程写法。"""
    return f"{float(value):g}"


def _is_pe_candidate(candidate):
    """判断候选结果是否携带 PE 商品规格。"""
    return getattr(candidate, "nominal_outer_diameter_mm", None) is not None


def _is_product_candidate(candidate):
    """判断候选结果是否携带统一产品目录元数据。"""
    return bool(getattr(candidate, "product_family", None))


def _material_display_name(material_key):
    """返回界面与报告使用的友好管材名，同时保留内部兼容键。"""
    material = PIPE_MATERIALS[material_key]
    return material.get("display_name", material["name"])


PE_WORD_REFERENCES = PRESSURE_PIPE_PRODUCT_REFERENCES["PE"]
LEGACY_MATERIAL_KEY_ORDER_V1 = (
    "HDPE管",
    "玻璃钢夹砂管",
    "球墨铸铁管",
    "预应力钢筒混凝土管",
    "预应力钢筒混凝土管_n014",
    "预应力钢筒混凝土管_n015",
    "钢管",
)

PE_GRADE_TOOLTIP = (
    "PE80、PE100 表示管材的材料等级，PE100 的材料强度更高。"
)
PE_PN_TOOLTIP = (
    "PN 表示公称压力。选好材料等级和 PN 后，程序会按规范匹配 SDR，无需另填。"
)
PE_DN_TOOLTIP = (
    "填写管子的公称外径，单位为毫米；留空时由程序按规范推荐。\n"
    "壁厚和计算内径由程序自动确定。"
)


def _build_pe_learning_text(grade, pn_mpa, manual_dn_text="", *, batch=False):
    """用简短中文说明当前 PE 规格和管径填写方式。"""
    normalized_grade = str(grade or "PE100").upper()
    sdr = get_pe_sdr(normalized_grade, pn_mpa)
    manual_dn = str(manual_dn_text or "").strip()
    if batch:
        diameter_mode = "批量计算会按规范推荐满足流速和水损要求的最小管径。"
    elif manual_dn:
        try:
            guidance = get_pe_nominal_diameter_guidance(
                normalized_grade, pn_mpa, manual_dn
            )
        except ValueError:
            guidance = None
        if guidance is not None and guidance.is_available:
            diameter_mode = (
                f"已指定外径 {manual_dn} mm，程序自动查取壁厚，并按内径计算水损。"
            )
        else:
            diameter_mode = "请填写当前材料和压力下的标准外径，可参考下方提示。"
    else:
        diameter_mode = "管径留空时，程序按规范推荐满足流速和水损要求的最小管径。"
    return (
        "【选径说明】\n"
        f"{normalized_grade} 为材料等级，PN {_fmt_g(pn_mpa)} MPa 为公称压力。\n"
        f"SDR {_fmt_g(sdr)} 已按规范自动匹配，无需填写。\n"
        f"{diameter_mode}"
    )


def _build_pe_dn_suggestion(grade, pn_mpa, dn_text):
    """生成指定 PE 公称外径的实时规范校验和相邻规格建议。"""
    requested_text = str(dn_text or "").strip()
    if not requested_text:
        return "", None, "empty"
    try:
        guidance = get_pe_nominal_diameter_guidance(
            grade, pn_mpa, requested_text
        )
    except ValueError as exc:
        return f"[输入提示] {exc}", None, "invalid"

    if guidance.is_available:
        spec = get_pe_pipe_spec(grade, pn_mpa, guidance.requested_mm)
        return (
            f"标准外径 {spec.nominal_outer_diameter_mm} mm；"
            f"壁厚 {_fmt_g(spec.nominal_wall_thickness_mm)} mm；"
            f"计算内径 {_fmt_g(spec.hydraulic_inner_diameter_mm)} mm。",
            None,
            "valid",
        )

    nearby_text = "、".join(str(dn) for dn in guidance.nearby_mm)
    if guidance.upper_mm is not None:
        action_text = f"可先选大一档的 {guidance.upper_mm} mm，再计算流速和水损。"
    else:
        action_text = "当前材料和压力下没有更大的规格，请调整材料等级、压力或管材。"
    return (
        f"{_fmt_g(guidance.requested_mm)} mm 不是当前材料和压力下的标准外径。\n"
        f"附近可选外径：{nearby_text} mm。{action_text}",
        guidance.upper_mm,
        "invalid",
    )


def _pressure_pipe_report_references(
    references, has_pe_product_specs, product_families=(), all_results=None,
):
    """优先按结果快照的标准版本列依据，避免将旧结果误标为新版。"""
    merged = list(references or ())
    if has_pe_product_specs:
        merged.extend(PE_WORD_REFERENCES)
    if all_results is not None:
        titles = [title for values in PRESSURE_PIPE_PRODUCT_REFERENCES.values() for title in values]
        titles.extend((
            "《水及燃气用球墨铸铁管、管件和附件》(GB/T 13295-2019)",
            "《水利水电工程球墨铸铁管道技术导则》(T/CWHIDA 0002-2018)",
        ))
        for _, _, result in all_results:
            candidate = getattr(result, "recommended", None)
            if not candidate or not getattr(candidate, "product_family", None):
                continue
            saved = getattr(candidate, "product_standard_references", ()) or ()
            if not saved and getattr(candidate, "product_standard", None):
                saved = (candidate.product_standard,)
            for reference in saved:
                code = reference.replace("—", "-")
                merged.append(next((title for title in titles if f"({code})" in title), reference))
        return list(dict.fromkeys(merged))
    for family in ("DI", "PCCP", "FRPM", "STEEL"):
        if family in set(product_families or ()):
            merged.extend(PRESSURE_PIPE_PRODUCT_REFERENCES[family])
    return list(dict.fromkeys(merged))


def _results_have_pe_product_specs(all_results):
    """仅当结果确实带有 PE 产品尺寸元数据时启用 PE 报告口径。"""
    return any(
        _is_pe_candidate(getattr(result, "recommended", None))
        for _, _, result in all_results
        if getattr(result, "recommended", None) is not None
    )


def _results_product_families(all_results):
    """收集成果中实际采用的统一产品目录族。"""
    return {
        getattr(result.recommended, "product_family", None)
        for _, _, result in all_results
        if getattr(result, "recommended", None) is not None
        and getattr(result.recommended, "product_family", None)
    }


def _pe_procurement_text(candidate, include_standard=True):
    """生成可直接用于询价和造价的 PE 管规格文本。"""
    grade = getattr(candidate, "pe_material_grade", None) or "PE"
    dn_mm = getattr(candidate, "nominal_outer_diameter_mm", None)
    wall_mm = getattr(candidate, "nominal_wall_thickness_mm", None)
    sdr = getattr(candidate, "pe_sdr", None)
    pn_mpa = getattr(candidate, "pe_nominal_pressure_mpa", None)
    standard = getattr(candidate, "product_standard", None) or PE_STANDARD
    text = (
        f"{grade}给水管，DN{_fmt_g(dn_mm)}×{_fmt_g(wall_mm)} mm，"
        f"SDR{_fmt_g(sdr)}，PN{_fmt_g(pn_mpa)} MPa"
    )
    return f"{text}，{standard}" if include_standard else text


def _product_procurement_text(candidate, include_standard=True):
    """生成 DI、PCCP、FRPM 产品目录候选的工程规格文本。"""
    if _is_pe_candidate(candidate):
        return _pe_procurement_text(candidate, include_standard=include_standard)
    family = getattr(candidate, "product_family", None)
    dn_mm = getattr(candidate, "nominal_diameter_mm", None)
    if family == "DI":
        text = (
            f"球墨铸铁管 DN{_fmt_g(dn_mm)}，{candidate.class_code}，"
            f"DE{_fmt_g(candidate.outer_diameter_mm)}×e"
            f"{_fmt_g(candidate.nominal_wall_thickness_mm)} mm，"
            f"水泥砂浆内衬 {_fmt_g(candidate.lining_thickness_mm)} mm"
        )
    elif family == "PCCP":
        variant_name = "埋置式" if candidate.product_variant == "PCCPE" else "内衬式"
        text = (
            f"{variant_name}预应力钢筒混凝土管 {candidate.product_variant}，"
            f"DN={_fmt_g(dn_mm)} mm"
        )
    elif family == "FRPM":
        text = f"玻璃钢夹砂管，内径系列 DN{_fmt_g(dn_mm)}"
    elif family == "STEEL":
        text = (
            f"钢管 DN{_fmt_g(candidate.outer_diameter_mm)}×"
            f"{_fmt_g(candidate.nominal_wall_thickness_mm)} mm（构造最小壁厚），"
            f"单侧内衬 {_fmt_g(candidate.lining_thickness_mm)} mm"
        )
    else:
        return f"D={candidate.D:g} m"
    if not include_standard:
        return text
    references = tuple(getattr(candidate, "product_standard_references", ()) or ())
    if not references and getattr(candidate, "product_standard", None):
        references = (candidate.product_standard,)
    return text + ("，" + "、".join(references) if references else "")


def _frpm_dimension_boundary(candidate):
    """返回 FRPM 管端内径范围和相对设计内径偏差，其他候选返回空值。"""
    if getattr(candidate, "product_family", None) != "FRPM":
        return None
    minimum_mm = getattr(candidate, "minimum_inner_diameter_mm", None)
    maximum_mm = getattr(candidate, "maximum_inner_diameter_mm", None)
    tolerance_mm = getattr(candidate, "selected_inner_diameter_tolerance_mm", None)
    if minimum_mm is None or maximum_mm is None or tolerance_mm is None:
        return None
    return (
        f"{_fmt_g(minimum_mm)}～{_fmt_g(maximum_mm)} mm",
        f"±{_fmt_g(tolerance_mm)} mm",
    )


class _FallbackHtmlView(QTextEdit):
    """QWebEngine 不可用时的轻量降级视图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setAcceptRichText(True)


def _create_result_view(parent=None):
    return create_web_view(parent)


# ============================================================
# SpinBox / 标签芯片 辅助组件
# ============================================================
_SPINBTN_SS = """
    QPushButton { border:none; background:#f5f5f5; font-size:15px; color:#555; }
    QPushButton:hover { background:#e0e8f0; color:#0078d4; }
    QPushButton:pressed { background:#d0dde8; }
"""
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
MAX_CASES = 30
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
        self._initial_help_rendered = False
        self._cases = [self._default_case()]
        self._current_case_idx = 0
        self._all_results = []
        self._last_errors: list[str] = []
        self._panel_key = "pressure-pipe"
        self._results_dirty = False
        self._stale_result_case_indexes = set()
        self._all_results_stale = False
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
        if not self._initial_help_rendered:
            # 启动阶段先完成主窗口装配，首次真正显示该页时再渲染帮助内容。
            QTimer.singleShot(0, self._ensure_initial_help_rendered)

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

        # ---- 单次计算参数组 ----
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
        mat_display = [(k, _material_display_name(k)) for k in PIPE_MATERIALS]
        self._mat_keys = [k for k, _ in mat_display]
        self.material_combo.addItems([n for _, n in mat_display])
        self.material_combo.currentIndexChanged.connect(self._on_material_changed)
        r.addWidget(self.material_combo, 1)
        fl.addLayout(r)

        # PE 产品规格由材料等级和 PN 共同确定，与水力内径分开输入。
        self.pe_grade_row = QWidget()
        pe_grade_lay = QHBoxLayout(self.pe_grade_row)
        pe_grade_lay.setContentsMargins(0, 0, 0, 0)
        self.pe_grade_lbl = QLabel("PE 材料等级:")
        self.pe_grade_lbl.setMinimumWidth(140)
        self.pe_grade_lbl.setStyleSheet(INPUT_LABEL_STYLE)
        self.pe_grade_lbl.setToolTip(PE_GRADE_TOOLTIP)
        pe_grade_lay.addWidget(self.pe_grade_lbl)
        self.pe_grade_combo = ComboBox()
        self.pe_grade_combo.addItems(["PE100", "PE80"])
        self.pe_grade_combo.setToolTip(PE_GRADE_TOOLTIP)
        self.pe_grade_combo.currentTextChanged.connect(self._on_pe_grade_changed)
        pe_grade_lay.addWidget(self.pe_grade_combo, 1)
        fl.addWidget(self.pe_grade_row)

        self.pe_pn_row = QWidget()
        pe_pn_lay = QHBoxLayout(self.pe_pn_row)
        pe_pn_lay.setContentsMargins(0, 0, 0, 0)
        self.pe_pn_lbl = QLabel("公称压力 PN:")
        self.pe_pn_lbl.setMinimumWidth(140)
        self.pe_pn_lbl.setStyleSheet(INPUT_LABEL_STYLE)
        self.pe_pn_lbl.setToolTip(PE_PN_TOOLTIP)
        pe_pn_lay.addWidget(self.pe_pn_lbl)
        self.pe_pn_combo = ComboBox()
        self.pe_pn_combo.setToolTip(PE_PN_TOOLTIP)
        self.pe_pn_combo.currentIndexChanged.connect(self._refresh_pe_learning_hint)
        pe_pn_lay.addWidget(self.pe_pn_combo, 1)
        fl.addWidget(self.pe_pn_row)
        self.pe_spec_hint = self._hint("")
        self.pe_spec_hint.setWordWrap(True)
        self.pe_spec_hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.pe_spec_hint.setStyleSheet(
            f"QLabel {{ font-family:'Microsoft YaHei',sans-serif; font-size:11px; "
            f"color:{T2}; background:{CARD}; border:1px solid {BD}; "
            "border-radius:6px; padding:8px; }}"
        )
        fl.addWidget(self.pe_spec_hint)
        self._populate_pe_pn_combo(
            self.pe_pn_combo, "PE100", preferred=1.0, options_attr="_pe_pn_options"
        )

        # 管长
        fl.addWidget(self._slbl("【管道参数】"))
        self.length_edit = self._field(fl, "管长 L (m):", "1000")
        self.local_ratio_edit = self._field(fl, "局部水头损失比例:", "0.15")

        # 可选参数
        fl.addWidget(self._sep())
        fl.addWidget(self._slbl("【可选参数】"))
        self.D_lbl, self.D_edit = self._field2(fl, "指定水力内径 D (m):", "")
        self.D_edit.setPlaceholderText("留空则自动推荐经济管径")
        self.pe_dn_lbl, self.pe_dn_edit = self._field2(fl, "指定 PE 公称外径 DN (mm):", "")
        self.pe_dn_edit.setPlaceholderText("留空按规范推荐")
        self.pe_dn_lbl.setToolTip(PE_DN_TOOLTIP)
        self.pe_dn_edit.setToolTip(PE_DN_TOOLTIP)
        self.pe_dn_edit.textChanged.connect(self._refresh_pe_learning_hint)
        self.pe_dn_guidance_row = QWidget()
        pe_dn_guidance_lay = QHBoxLayout(self.pe_dn_guidance_row)
        pe_dn_guidance_lay.setContentsMargins(0, 0, 0, 0)
        pe_dn_guidance_lay.setSpacing(8)
        self.pe_dn_guidance_hint = self._hint("")
        self.pe_dn_guidance_hint.setWordWrap(True)
        pe_dn_guidance_lay.addWidget(self.pe_dn_guidance_hint, 1)
        self.pe_dn_use_upper_btn = PushButton("")
        self.pe_dn_use_upper_btn.setMinimumWidth(108)
        self.pe_dn_use_upper_btn.clicked.connect(self._use_pe_upper_dn_suggestion)
        pe_dn_guidance_lay.addWidget(self.pe_dn_use_upper_btn)
        self.pe_dn_guidance_row.hide()
        fl.addWidget(self.pe_dn_guidance_row)
        self._pe_upper_dn_suggestion = None
        self._refresh_pe_learning_hint()

        # 新工况固定按规范选径；旧工况保留原内径，并提供主动迁移入口。
        self._use_product_catalog = True
        self.product_catalog_upgrade_btn = PushButton("按规范重新选径")
        self.product_catalog_upgrade_btn.clicked.connect(self._enable_product_catalog)
        self.product_catalog_upgrade_btn.hide()
        fl.addWidget(self.product_catalog_upgrade_btn)
        self.product_dn_lbl, self.product_dn_edit = self._field2(
            fl, "指定公称直径 (mm):", ""
        )
        self.product_dn_edit.setPlaceholderText("留空按规范推荐")
        self.product_dn_edit.textChanged.connect(self._refresh_product_catalog_hint)

        self._di_class_options = tuple(DUCTILE_IRON_CLASS_OPTIONS)
        self.di_class_row, self.di_class_combo = self._combo_field(
            fl, "球墨铸铁管等级:",
            ["规范推荐", *DUCTILE_IRON_CLASS_OPTIONS[1:]],
        )
        self.di_class_combo.currentIndexChanged.connect(self._refresh_product_catalog_hint)
        self._pccp_variants = tuple(PCCP_VARIANTS)
        self.pccp_variant_row, self.pccp_variant_combo = self._combo_field(
            fl, "PCCP 产品型式:", ["PCCPE（埋置式）", "PCCPL（内衬式）"],
        )
        self.pccp_variant_combo.currentIndexChanged.connect(
            self._refresh_product_catalog_hint
        )
        self.product_catalog_hint = self._hint("")
        self.product_catalog_hint.setWordWrap(True)
        self.product_catalog_hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fl.addWidget(self.product_catalog_hint)
        self.steel_controls = SteelPipeControls()
        self.steel_controls.changed.connect(self._on_result_inputs_changed)
        fl.addWidget(self.steel_controls)
        fl.addWidget(self._sep())

        # 加大流量
        self.inc_cb = CheckBox("考虑加大流量")
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
        self.inc_lbl, self.inc_edit = self._field2(fl, "加大比例 (%):", "")
        self.inc_edit.setPlaceholderText("留空则自动计算")
        self.inc_q_lbl, self.inc_q_edit = self._field2(fl, "加大流量 Q加大 (m³/s):", "")
        self.inc_edit.textChanged.connect(self._refresh_increase_hint)
        self.inc_q_edit.textChanged.connect(self._refresh_increase_hint)
        self.inc_hint = self._hint("(留空则自动计算)")
        self.inc_derived_hint = self.inc_hint
        fl.addWidget(self.inc_hint)

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

        self.slope_controls = SlopeComparisonControls()
        self._unpr_container = self.slope_controls
        self.batch_n_edit = self.slope_controls.n_edit
        self._unpr_container.hide()
        self.slope_controls.changed.connect(self._mark_comparison_stale)
        self.batch_unpr_cb.toggled.connect(self._mark_comparison_stale)
        fl2.addWidget(self._unpr_container)

        # 管材多选（默认全选）
        fl2.addWidget(self._slbl("【管材选择】"))
        self._mat_cbs = {}
        for k, v in PIPE_MATERIALS.items():
            cb_mat = CheckBox(v.get("display_name", v["name"]))
            cb_mat.setChecked(True)
            fl2.addWidget(cb_mat)
            self._mat_cbs[k] = cb_mat

        # 批量计算中 PE 候选尺寸同样按选定等级和 PN 的规范目录生成。
        self.batch_pe_row = QWidget()
        batch_pe_lay = QVBoxLayout(self.batch_pe_row)
        batch_pe_lay.setContentsMargins(16, 2, 0, 2)
        batch_pe_lay.setSpacing(4)
        batch_grade_line = QHBoxLayout()
        batch_grade_lbl = QLabel("PE 材料等级:")
        batch_grade_lbl.setMinimumWidth(120)
        batch_grade_lbl.setStyleSheet(INPUT_LABEL_STYLE)
        batch_grade_lbl.setToolTip(PE_GRADE_TOOLTIP)
        batch_grade_line.addWidget(batch_grade_lbl)
        self.batch_pe_grade_combo = ComboBox()
        self.batch_pe_grade_combo.addItems(["PE100", "PE80"])
        self.batch_pe_grade_combo.setToolTip(PE_GRADE_TOOLTIP)
        self.batch_pe_grade_combo.currentTextChanged.connect(self._on_batch_pe_grade_changed)
        batch_grade_line.addWidget(self.batch_pe_grade_combo, 1)
        batch_pe_lay.addLayout(batch_grade_line)
        batch_pn_line = QHBoxLayout()
        batch_pn_lbl = QLabel("公称压力 PN:")
        batch_pn_lbl.setMinimumWidth(120)
        batch_pn_lbl.setStyleSheet(INPUT_LABEL_STYLE)
        batch_pn_lbl.setToolTip(PE_PN_TOOLTIP)
        batch_pn_line.addWidget(batch_pn_lbl)
        self.batch_pe_pn_combo = ComboBox()
        self.batch_pe_pn_combo.setToolTip(PE_PN_TOOLTIP)
        self.batch_pe_pn_combo.currentIndexChanged.connect(
            self._refresh_batch_pe_learning_hint
        )
        batch_pn_line.addWidget(self.batch_pe_pn_combo, 1)
        batch_pe_lay.addLayout(batch_pn_line)
        self.batch_pe_spec_hint = self._hint("")
        self.batch_pe_spec_hint.setWordWrap(True)
        self.batch_pe_spec_hint.setToolTip(PE_PN_TOOLTIP)
        batch_pe_lay.addWidget(self.batch_pe_spec_hint)
        fl2.addWidget(self.batch_pe_row)
        self._populate_pe_pn_combo(
            self.batch_pe_pn_combo, "PE100", preferred=1.0,
            options_attr="_batch_pe_pn_options",
        )
        self._refresh_batch_pe_learning_hint()
        self._mat_cbs["HDPE管"].stateChanged.connect(self._sync_batch_pe_controls)

        # 批量计算默认对 DI、PCCP、FRPM 使用同一套规范产品目录。
        self.batch_product_catalog_row = QWidget()
        batch_catalog_lay = QVBoxLayout(self.batch_product_catalog_row)
        batch_catalog_lay.setContentsMargins(16, 2, 0, 2)
        batch_catalog_lay.setSpacing(4)
        self.batch_di_class_row, self.batch_di_class_combo = self._combo_field(
            batch_catalog_lay, "球墨铸铁管等级:",
            ["规范推荐", *DUCTILE_IRON_CLASS_OPTIONS[1:]],
            label_width=120,
        )
        self.batch_pccp_variant_row, self.batch_pccp_variant_combo = self._combo_field(
            batch_catalog_lay, "PCCP 产品型式:",
            ["PCCPE（埋置式）", "PCCPL（内衬式）"], label_width=120,
        )
        self.batch_product_catalog_hint = self._hint("")
        self.batch_product_catalog_hint.setWordWrap(True)
        batch_catalog_lay.addWidget(self.batch_product_catalog_hint)
        fl2.addWidget(self.batch_product_catalog_row)
        for material_key, checkbox in self._mat_cbs.items():
            if get_catalog_family(material_key):
                checkbox.stateChanged.connect(self._sync_batch_product_catalog_controls)
        self._sync_batch_product_catalog_controls()

        self.batch_steel_controls = SteelPipeControls(batch=True)
        fl2.addWidget(self.batch_steel_controls)
        self._mat_cbs['钢管'].toggled.connect(self.batch_steel_controls.setVisible)
        self.batch_steel_controls.setVisible(self._mat_cbs['钢管'].isChecked())

        fl2.addWidget(self._sep())

        # 输出选项
        fl2.addWidget(self._slbl("【输出选项】"))
        self.out_csv_cb = CheckBox("CSV 计算结果")
        self.out_csv_cb.setChecked(True)
        self.out_csv_cb.setToolTip("包含所有工况的原始数据（管径/流速/水损等），可用Excel打开做后续分析")
        fl2.addWidget(self.out_csv_cb)
        self.out_pdf_cb = CheckBox("图表 PDF（流速水损对比 + 优选设计点）")
        self.out_pdf_cb.setChecked(True)
        self.out_pdf_cb.setToolTip("启用无压对比时：输出默认候选的输水能力、充满度与同流量流速图\n保留有压优选设计点图；全部管径和底坡的完整数据可导出 CSV")
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
        self._result_case_nav = CaseResultNavigationBar(grp)
        self._result_case_nav.case_requested.connect(self._jump_to_case_result)
        gl.addWidget(self._result_case_nav)
        self.result_view = _create_result_view()
        gl.addWidget(self.result_view)
        if _WEB_ENGINE_IMPORT_ERROR is not None:
            warn = QLabel("当前环境未能加载 Qt WebEngine，结果页已自动降级为简化 HTML 视图。")
            warn.setWordWrap(True)
            warn.setStyleSheet("font-size:12px;color:#a15c00;padding:4px 0;")
            gl.addWidget(warn)
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

        for edit in (self.batch_q_start, self.batch_q_end, self.batch_q_step,
                     self.batch_length_edit, self.batch_local_ratio_edit):
            edit.textChanged.connect(self._mark_comparison_stale)
        for checkbox in self._mat_cbs.values():
            checkbox.toggled.connect(self._mark_comparison_stale)
        for combo in (self.batch_pe_grade_combo, self.batch_pe_pn_combo,
                      self.batch_di_class_combo, self.batch_pccp_variant_combo):
            combo.currentIndexChanged.connect(self._mark_comparison_stale)
        for edit in self.batch_steel_controls.findChildren(LineEdit):
            edit.textChanged.connect(self._mark_comparison_stale)

    # ----------------------------------------------------------------
    # 辅助 UI
    # ----------------------------------------------------------------
    def _current_material_key(self):
        """返回当前单次计算选中的内部管材键。"""
        idx = self.material_combo.currentIndex()
        if 0 <= idx < len(self._mat_keys):
            return self._mat_keys[idx]
        return self._mat_keys[0]

    @staticmethod
    def _set_combo_text(combo, text):
        """按文本安全设置下拉框，找不到时保持原值。"""
        idx = combo.findText(str(text))
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _selected_pe_pn(self, combo, options_attr, default=1.0):
        """返回 PE PN 下拉框当前对应的数值。"""
        options = getattr(self, options_attr, ())
        idx = combo.currentIndex()
        if 0 <= idx < len(options):
            return float(options[idx])
        return float(default)

    def _populate_pe_pn_combo(self, combo, grade, preferred, options_attr):
        """按 PE 材料等级刷新 PN/SDR 选项。"""
        options = tuple(get_pe_pressure_options(grade))
        combo.blockSignals(True)
        combo.clear()
        combo.addItems([
            f"PN {_fmt_g(pn)} MPa（SDR {_fmt_g(get_pe_sdr(grade, pn))}）"
            for pn in options
        ])
        selected_idx = 0
        if preferred is not None:
            for idx, pn in enumerate(options):
                if abs(float(pn) - float(preferred)) < 1e-9:
                    selected_idx = idx
                    break
        combo.setCurrentIndex(selected_idx)
        combo.blockSignals(False)
        setattr(self, options_attr, options)

    def _on_material_changed(self, _index):
        """切换管材时同步 PE 与其他产品目录输入的可见性。"""
        self._sync_pe_controls()
        self._sync_product_catalog_controls()

    def _sync_pe_controls(self):
        """仅在选中 PE 管时显示等级、PN 和公称外径输入。"""
        is_pe = self._current_material_key() == "HDPE管"
        for widget in (
            self.pe_grade_row,
            self.pe_pn_row,
            self.pe_spec_hint,
            self.pe_dn_lbl,
            self.pe_dn_edit,
        ):
            widget.setVisible(is_pe)
        if hasattr(self, "pe_dn_guidance_row"):
            has_dn_text = bool(self.pe_dn_edit.text().strip())
            self.pe_dn_guidance_row.setVisible(is_pe and has_dn_text)
        catalog_enabled = (
            bool(get_catalog_family(self._current_material_key()))
            and getattr(self, "_use_product_catalog", True)
        )
        self.D_lbl.setVisible(not is_pe and not catalog_enabled and self._current_material_key() != "钢管")
        self.D_edit.setVisible(not is_pe and not catalog_enabled and self._current_material_key() != "钢管")
        self.D_edit.setEnabled(not is_pe and not catalog_enabled and self._current_material_key() != "钢管")
        self.pe_dn_edit.setEnabled(is_pe)
        if is_pe:
            self._refresh_pe_dn_suggestion()

    def _selected_di_class(self, combo=None):
        """返回球墨铸铁管等级下拉框的稳定代码。"""
        target = combo or self.di_class_combo
        idx = target.currentIndex()
        if 0 <= idx < len(self._di_class_options):
            return self._di_class_options[idx]
        return target.property("legacy_di_class") or "PREFERRED"

    def _selected_pccp_variant(self, combo=None):
        """返回 PCCP 产品型式下拉框的稳定代码。"""
        target = combo or self.pccp_variant_combo
        idx = target.currentIndex()
        return self._pccp_variants[idx] if 0 <= idx < len(self._pccp_variants) else "PCCPE"

    def _enable_product_catalog(self):
        """由用户主动将旧工况转入规范选径，保留原内径供迁移校核。"""
        self._save_current_case()
        self._use_product_catalog = True
        self._sync_product_catalog_controls()

    def _sync_product_catalog_controls(self, *_args):
        """同步 DI、PCCP、FRPM 产品目录控件与历史 D 输入。"""
        if not hasattr(self, "product_catalog_upgrade_btn"):
            return
        material_key = self._current_material_key()
        family = get_catalog_family(material_key)
        is_pe = material_key == "HDPE管"
        enabled = bool(family and self._use_product_catalog)
        self.product_catalog_upgrade_btn.setVisible(bool(family) and not enabled)
        self.product_dn_lbl.setVisible(enabled)
        self.product_dn_edit.setVisible(enabled)
        self.product_dn_edit.setEnabled(enabled)
        self.di_class_row.setVisible(enabled and family == "DI")
        self.pccp_variant_row.setVisible(enabled and family == "PCCP")
        self.product_catalog_hint.setVisible(enabled)
        self.D_lbl.setVisible(not is_pe and not enabled)
        self.D_edit.setVisible(not is_pe and not enabled)
        self.D_edit.setEnabled(not is_pe and not enabled)
        if family == "DI":
            self.product_dn_lbl.setText("指定公称尺寸 DN (mm):")
        elif family == "PCCP":
            self.product_dn_lbl.setText("指定公称内径 DN (mm):")
        elif family == "FRPM":
            self.product_dn_lbl.setText("指定内径系列 DN (mm):")
        self._refresh_product_catalog_hint()

        if hasattr(self, 'steel_controls'):
            is_steel = material_key == '钢管'
            self.steel_controls.setVisible(is_steel)
            if is_steel:
                self.D_lbl.hide()
                self.D_edit.hide()
                self.D_edit.setEnabled(False)

    def _refresh_product_catalog_hint(self, *_args):
        """显示当前产品目录的口径基准、适用边界和指定规格校验。"""
        if not hasattr(self, "product_catalog_hint"):
            return
        material_key = self._current_material_key()
        family = get_catalog_family(material_key)
        if not family or not self._use_product_catalog:
            self.product_catalog_hint.setText("")
            return
        di_class = self._selected_di_class()
        pccp_variant = self._selected_pccp_variant()
        if family == "DI":
            text = (
                f"球墨铸铁管按 {DI_PRODUCT_STANDARD} 选径。"
                "选“规范推荐”时，等级随管径自动匹配。"
            )
            try:
                get_ductile_iron_specs(di_class)
            except ValueError as exc:
                self.product_catalog_hint.setText(text + f"\n[需重新选级] {exc}")
                return
        elif family == "PCCP":
            text = "按所选管型的标准内径选径，管型和摩阻参数可分别选择。"
        else:
            text = f"玻璃钢夹砂管按 {FRPM_PRODUCT_STANDARD} 的标准内径选径。"
        dn_text = self.product_dn_edit.text().strip()
        if dn_text:
            try:
                spec = get_pipe_product_spec(
                    material_key, dn_text,
                    ductile_iron_class=di_class, pccp_variant=pccp_variant,
                )
                text += f"\n[符合规范] {format_pipe_product_spec(spec)}。"
            except ValueError as exc:
                text += f"\n[输入提示] {exc}"
        else:
            text += "\n管径留空时，程序按规范推荐满足流速和水损要求的最小管径。"
        self.product_catalog_hint.setText(text)

    def _on_pe_grade_changed(self, grade):
        """材料等级变化时保留可兼容的 PN，并刷新 SDR 显示。"""
        preferred = self._selected_pe_pn(
            self.pe_pn_combo, "_pe_pn_options", default=1.0
        )
        self._populate_pe_pn_combo(
            self.pe_pn_combo, grade, preferred=preferred, options_attr="_pe_pn_options"
        )
        self._refresh_pe_learning_hint()

    def _refresh_pe_learning_hint(self, *_args):
        """按当前 PE 等级、压力和公称外径输入刷新选径说明。"""
        if not hasattr(self, "pe_spec_hint"):
            return
        grade = self.pe_grade_combo.currentText() or "PE100"
        pn_mpa = self._selected_pe_pn(
            self.pe_pn_combo, "_pe_pn_options", default=1.0
        )
        manual_dn_text = self.pe_dn_edit.text() if hasattr(self, "pe_dn_edit") else ""
        self.pe_spec_hint.setText(
            _build_pe_learning_text(grade, pn_mpa, manual_dn_text)
        )
        self._refresh_pe_dn_suggestion()

    def _refresh_pe_dn_suggestion(self):
        """实时提示当前输入外径是否合规，并给出附近规范公称外径。"""
        if not hasattr(self, "pe_dn_guidance_row"):
            return
        grade = self.pe_grade_combo.currentText() or "PE100"
        pn_mpa = self._selected_pe_pn(
            self.pe_pn_combo, "_pe_pn_options", default=1.0
        )
        text, upper_dn, state = _build_pe_dn_suggestion(
            grade, pn_mpa, self.pe_dn_edit.text()
        )
        self._pe_upper_dn_suggestion = upper_dn
        is_pe = self._current_material_key() == "HDPE管"
        self.pe_dn_guidance_row.setVisible(is_pe and state != "empty")
        self.pe_dn_guidance_hint.setText(text)
        if state == "valid":
            color = "#137333"
        elif state == "invalid":
            color = "#A15C00"
        else:
            color = T2
        self.pe_dn_guidance_hint.setStyleSheet(
            f"font-family:'Microsoft YaHei',sans-serif; font-size:11px; color:{color};"
        )
        self.pe_dn_use_upper_btn.setVisible(upper_dn is not None)
        if upper_dn is not None:
            self.pe_dn_use_upper_btn.setText(f"采用 {upper_dn} mm")
            self.pe_dn_use_upper_btn.setToolTip(
                "仅填入相邻上一级规范外径；仍须重新计算并检查流速和水损。"
            )

    def _use_pe_upper_dn_suggestion(self):
        """经用户点击后填入相邻上一级规范公称外径。"""
        if self._pe_upper_dn_suggestion is None:
            return
        self.pe_dn_edit.setText(str(self._pe_upper_dn_suggestion))
        self.pe_dn_edit.setFocus()

    def _on_batch_pe_grade_changed(self, grade):
        """批量计算材料等级变化时刷新 PN/SDR 选项。"""
        preferred = self._selected_pe_pn(
            self.batch_pe_pn_combo, "_batch_pe_pn_options", default=1.0
        )
        self._populate_pe_pn_combo(
            self.batch_pe_pn_combo,
            grade,
            preferred=preferred,
            options_attr="_batch_pe_pn_options",
        )
        self._refresh_batch_pe_learning_hint()

    def _refresh_batch_pe_learning_hint(self, *_args):
        """刷新批量 PE 规格设置旁的规范说明。"""
        if not hasattr(self, "batch_pe_spec_hint"):
            return
        grade = self.batch_pe_grade_combo.currentText() or "PE100"
        pn_mpa = self._selected_pe_pn(
            self.batch_pe_pn_combo, "_batch_pe_pn_options", default=1.0
        )
        self.batch_pe_spec_hint.setText(_build_pe_learning_text(grade, pn_mpa, batch=True))

    def _sync_batch_pe_controls(self, *_args):
        """未选择 PE 批量计算时隐藏其专用规格设置。"""
        pe_checkbox = self._mat_cbs.get("HDPE管")
        self.batch_pe_row.setVisible(bool(pe_checkbox and pe_checkbox.isChecked()))

    def _sync_batch_product_catalog_controls(self, *_args):
        """按批量管材勾选状态显示 DI/PCCP/FRPM 目录设置。"""
        if not hasattr(self, "batch_product_catalog_row"):
            return
        selected_families = {
            get_catalog_family(key)
            for key, checkbox in self._mat_cbs.items()
            if checkbox.isChecked() and get_catalog_family(key)
        }
        has_catalog_material = bool(selected_families)
        enabled = has_catalog_material
        self.batch_product_catalog_row.setVisible(has_catalog_material)
        self.batch_di_class_row.setVisible(enabled and "DI" in selected_families)
        self.batch_pccp_variant_row.setVisible(enabled and "PCCP" in selected_families)
        self.batch_product_catalog_hint.setText("程序按各管材的规范规格自动选径。")

    def _ensure_initial_help_rendered(self):
        """首次真正显示面板时再补初始帮助，避免阻塞主窗口启动。"""
        if self._initial_help_rendered:
            return
        self._show_initial_help()

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

    def _field2(self, lay, label, default=""):
        r = QHBoxLayout()
        l = QLabel(label)
        l.setMinimumWidth(140)
        l.setStyleSheet(INPUT_LABEL_STYLE)
        r.addWidget(l)
        e = LineEdit()
        e.setText(default)
        r.addWidget(e, 1)
        lay.addLayout(r)
        return l, e

    def _combo_field(self, lay, label, items, label_width=140):
        """创建可整体显隐的标签与下拉框行。"""
        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        field_label = QLabel(label)
        field_label.setMinimumWidth(label_width)
        field_label.setStyleSheet(INPUT_LABEL_STYLE)
        row_lay.addWidget(field_label)
        combo = ComboBox()
        combo.addItems(items)
        row_lay.addWidget(combo, 1)
        lay.addWidget(row)
        return row, combo

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

    def _increase_summary_lines(self, inp, result):
        """生成加大流量输入说明。"""
        rec = getattr(result, "recommended", None)
        result_q = inp.Q if rec is None else rec.Q_increased
        result_pct = 0.0 if rec is None else rec.increase_pct
        return build_increase_summary_lines(
            use_increase=getattr(inp, "use_increase", True),
            mode=getattr(inp, "inc_mode", INCREASE_MODE_PERCENT),
            percent_text=getattr(inp, "inc_pct_text", ""),
            q_increased_text=getattr(inp, "inc_q_text", ""),
            result_increase_percent=result_pct,
            result_q_increased=result_q,
        )

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

    def _mark_comparison_stale(self, *_args):
        """记录批量输入修改，并保留旧项目快照的过期标记。"""
        self.data_changed.emit()
        if getattr(self, '_comparison_rows', None):
            self._comparison_status = '参数已修改；当前仍为上次计算结果，请重新批量计算更新。'

    # ----------------------------------------------------------------
    # 工况管理
    # ----------------------------------------------------------------
    @staticmethod
    def _default_case():
        return {
            'custom_label': None,
            'Q': '0.5', 'material_idx': 0, 'material_key': 'HDPE管', 'length': '1000',
            'local_ratio': '0.15', 'D': '', 'inc_checked': True, 'inc_pct': '',
            'pe_grade': 'PE100', 'pe_pn_mpa': 1.0, 'pe_dn_mm': '',
            'catalog_schema_version': 2, 'use_product_catalog': True,
            'product_dn_mm': '', 'ductile_iron_class': 'PREFERRED',
            'pccp_variant': 'PCCPE',
            'inc_mode': INCREASE_MODE_PERCENT, 'inc_q_text': '',
            **STEEL_CASE_DEFAULTS,
        }

    def _normalized_case_data(self, case):
        """补齐新字段，并保留旧工况的管材索引和水力内径语义。"""
        defaults = self._default_case()
        if not isinstance(case, dict):
            return defaults
        normalized = copy.deepcopy(case)
        is_legacy_catalog_case = 'catalog_schema_version' not in normalized

        # material_key 是新稳定标识；旧 material_idx 只按冻结的 V1 顺序解释一次。
        material_key = normalized.get('material_key')
        if material_key not in PIPE_MATERIALS:
            try:
                legacy_index = int(normalized.get('material_idx', 0))
            except (TypeError, ValueError):
                legacy_index = 0
            if 0 <= legacy_index < len(LEGACY_MATERIAL_KEY_ORDER_V1):
                material_key = LEGACY_MATERIAL_KEY_ORDER_V1[legacy_index]
            if material_key not in PIPE_MATERIALS:
                material_key = self._mat_keys[0]
        normalized['material_key'] = material_key
        normalized['material_idx'] = self._mat_keys.index(material_key)
        if material_key == '钢管':
            normalized = normalize_steel_case(normalized)
        if is_legacy_catalog_case:
            normalized['catalog_schema_version'] = 1
            normalized['use_product_catalog'] = False
            legacy_d = normalized.get('D')
            if get_catalog_family(material_key) and str(legacy_d or '').strip():
                normalized['legacy_product_manual_D'] = legacy_d

        # 旧项目没有 pe_dn_mm；D 对 PE 表示水力内径，不能直接改解释为公称外径。
        if 'pe_dn_mm' not in normalized:
            legacy_d = normalized.get('D')
            if material_key == 'HDPE管' and str(legacy_d or '').strip():
                normalized['legacy_pe_manual_D'] = legacy_d

        for key, value in defaults.items():
            normalized.setdefault(key, copy.deepcopy(value))
        return normalized

    def _copy_case_parameters(self, source, target):
        """复制除流量和名称外的工况参数，并正确同步旧 PE 迁移标记。"""
        source = self._normalized_case_data(source)
        defaults = self._default_case()
        for key in (
            'material_idx', 'material_key', 'length', 'local_ratio', 'D',
            'pe_grade', 'pe_pn_mpa', 'pe_dn_mm',
            'catalog_schema_version', 'use_product_catalog', 'product_dn_mm',
            'ductile_iron_class', 'pccp_variant',
            'inc_checked', 'inc_pct', 'inc_mode', 'inc_q_text',
            *STEEL_CASE_DEFAULTS,
        ):
            target[key] = copy.deepcopy(source.get(key, defaults[key]))
        if 'legacy_pe_manual_D' in source:
            target['legacy_pe_manual_D'] = copy.deepcopy(source['legacy_pe_manual_D'])
        else:
            target.pop('legacy_pe_manual_D', None)
        if 'legacy_product_manual_D' in source:
            target['legacy_product_manual_D'] = copy.deepcopy(
                source['legacy_product_manual_D']
            )
        else:
            target.pop('legacy_product_manual_D', None)

    def _save_current_case(self):
        """将当前UI字段保存到当前工况数据"""
        if not (0 <= self._current_case_idx < len(self._cases)):
            return
        c = self._cases[self._current_case_idx]
        # 旧项目没有 pe_dn_mm；先保留旧 D 的真实“水力内径”语义，避免本次保存把它静默丢失。
        legacy_pe_manual_D = c.get('legacy_pe_manual_D')
        legacy_product_manual_D = c.get('legacy_product_manual_D')
        if legacy_pe_manual_D is None and 'pe_dn_mm' not in c:
            try:
                old_material_idx = int(c.get('material_idx', 0))
            except (TypeError, ValueError):
                old_material_idx = 0
            if 0 <= old_material_idx < len(LEGACY_MATERIAL_KEY_ORDER_V1):
                if LEGACY_MATERIAL_KEY_ORDER_V1[old_material_idx] == 'HDPE管' and str(c.get('D', '')).strip():
                    legacy_pe_manual_D = c.get('D')
        c['Q'] = self.Q_edit.text()
        c['material_idx'] = self.material_combo.currentIndex()
        c['material_key'] = self._current_material_key()
        c['length'] = self.length_edit.text()
        c['local_ratio'] = self.local_ratio_edit.text()
        c['D'] = self.D_edit.text()
        c['pe_grade'] = self.pe_grade_combo.currentText() or 'PE100'
        c['pe_pn_mpa'] = self._selected_pe_pn(
            self.pe_pn_combo, "_pe_pn_options", default=1.0
        )
        c['pe_dn_mm'] = self.pe_dn_edit.text()
        c['catalog_schema_version'] = 2
        c['use_product_catalog'] = self._use_product_catalog
        c['product_dn_mm'] = self.product_dn_edit.text()
        c['ductile_iron_class'] = self._selected_di_class()
        c['pccp_variant'] = self._selected_pccp_variant()
        c.update(self.steel_controls.state())
        if c['material_key'] == '钢管':
            c['D'] = ''
        if self._current_material_key() != 'HDPE管' or c['pe_dn_mm'].strip():
            c.pop('legacy_pe_manual_D', None)
        elif legacy_pe_manual_D is not None:
            c['legacy_pe_manual_D'] = legacy_pe_manual_D
        product_family = get_catalog_family(c['material_key'])
        if not product_family or c['product_dn_mm'].strip():
            c.pop('legacy_product_manual_D', None)
        elif not c['use_product_catalog']:
            if c['D'].strip():
                c['legacy_product_manual_D'] = c['D']
            else:
                c.pop('legacy_product_manual_D', None)
        elif legacy_product_manual_D is not None:
            c['legacy_product_manual_D'] = legacy_product_manual_D
        c['inc_checked'] = self.inc_cb.isChecked()
        c['inc_pct'] = self.inc_edit.text()
        c['inc_mode'] = self._current_increase_mode()
        c['inc_q_text'] = self.inc_q_edit.text()

    def _load_case(self, idx):
        """将指定工况数据加载到UI字段"""
        if not (0 <= idx < len(self._cases)):
            return
        c = self._normalized_case_data(self._cases[idx])
        self._cases[idx] = c
        self._loading_case = True
        self.Q_edit.blockSignals(True)
        self.Q_edit.setText(c.get('Q', ''))
        self.Q_edit.blockSignals(False)
        self.material_combo.blockSignals(True)
        material_key = c.get('material_key')
        if material_key not in PIPE_MATERIALS:
            try:
                legacy_index = int(c.get('material_idx', 0))
            except (TypeError, ValueError):
                legacy_index = 0
            material_key = (
                LEGACY_MATERIAL_KEY_ORDER_V1[legacy_index]
                if 0 <= legacy_index < len(LEGACY_MATERIAL_KEY_ORDER_V1)
                else self._mat_keys[0]
            )
        if material_key not in PIPE_MATERIALS:
            material_key = self._mat_keys[0]
        self.material_combo.setCurrentIndex(self._mat_keys.index(material_key))
        self.material_combo.blockSignals(False)
        pe_grade = str(c.get('pe_grade', 'PE100') or 'PE100').upper()
        if pe_grade not in ("PE100", "PE80"):
            pe_grade = "PE100"
        self.pe_grade_combo.blockSignals(True)
        self._set_combo_text(self.pe_grade_combo, pe_grade)
        self.pe_grade_combo.blockSignals(False)
        try:
            preferred_pn = float(c.get('pe_pn_mpa', 1.0))
        except (TypeError, ValueError):
            preferred_pn = 1.0
        self._populate_pe_pn_combo(
            self.pe_pn_combo,
            pe_grade,
            preferred=preferred_pn,
            options_attr="_pe_pn_options",
        )
        self.length_edit.setText(c.get('length', '1000'))
        self.local_ratio_edit.setText(c.get('local_ratio', '0.15'))
        self.D_edit.setText(c.get('D', ''))
        self.steel_controls.set_state(c)
        self.pe_dn_edit.setText(c.get('pe_dn_mm', ''))
        self._use_product_catalog = bool(c.get('use_product_catalog', True))
        self.product_dn_edit.setText(c.get('product_dn_mm', ''))
        di_class = str(c.get('ductile_iron_class', 'PREFERRED') or 'PREFERRED').upper()
        self.di_class_combo.setProperty("legacy_di_class", di_class)
        if di_class not in self._di_class_options:
            # 保留旧等级，不静默选成新版首选；用户主动重选后才可重新计算。
            self.di_class_combo.setCurrentIndex(-1)
        else:
            self.di_class_combo.setCurrentIndex(self._di_class_options.index(di_class))
        pccp_variant = str(c.get('pccp_variant', 'PCCPE') or 'PCCPE').upper()
        if pccp_variant not in self._pccp_variants:
            pccp_variant = 'PCCPE'
        self.pccp_variant_combo.setCurrentIndex(self._pccp_variants.index(pccp_variant))
        self.inc_cb.setChecked(c.get('inc_checked', True))
        self.inc_edit.setText(c.get('inc_pct', ''))
        self.inc_q_edit.setText(c.get('inc_q_text', ''))
        self._set_increase_mode(c.get('inc_mode', INCREASE_MODE_PERCENT))
        self._on_inc_toggle(None)
        self._sync_pe_controls()
        self._sync_product_catalog_controls()
        self._loading_case = False

    def _focus_design_flow_input(self):
        """切换工况后聚焦设计流量，方便直接覆盖输入。"""
        self.Q_edit.setFocus()
        self.Q_edit.selectAll()

    def _switch_case(self, idx):
        """切换到指定工况"""
        switched = idx != self._current_case_idx
        if switched:
            self._save_current_case()
            self._current_case_idx = idx
            self._load_case(idx)
            self._rebuild_case_tags()
            self.data_changed.emit()
        if has_fresh_case_results(
            all_results=self._all_results,
            has_rendered_results=self._has_rendered_results,
            results_dirty=self._results_dirty,
            case_idx=idx,
            stale_case_indexes=getattr(self, "_stale_result_case_indexes", set()),
            all_results_stale=getattr(self, "_all_results_stale", False),
        ):
            self._jump_to_case_result(idx)
        if switched:
            self._focus_design_flow_input()

    def _add_case(self):
        """添加新工况（从当前工况复制参数，清空Q）"""
        if len(self._cases) >= MAX_CASES:
            InfoBar.warning(title="提示", content=f"最多支持 {MAX_CASES} 个工况",
                            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=3000)
            return
        self._save_current_case()
        new_case = dict(self._cases[self._current_case_idx])
        new_case['Q'] = ''
        new_case['custom_label'] = None
        self._cases.append(new_case)
        self._mark_results_dirty(mark_case=False)
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
        self._mark_results_dirty(all_cases=True)
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
        if getattr(self, "_loading_case", False):
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

    def _case_result_state_kwargs(self, case_idx):
        """返回目标工况结果状态判断所需的参数。"""
        return {
            "all_results": self._all_results,
            "has_rendered_results": self._has_rendered_results,
            "results_dirty": self._results_dirty,
            "case_idx": case_idx,
            "stale_case_indexes": getattr(self, "_stale_result_case_indexes", set()),
            "all_results_stale": getattr(self, "_all_results_stale", False),
        }

    def _mark_results_dirty(
        self,
        case_idx=None,
        *,
        all_cases=False,
        mark_case=True,
        case_indexes=None,
    ):
        """标记旧结果过期；默认只标记当前工况。"""
        if getattr(self, "_loading_case", False):
            return
        if self._has_rendered_results or self._all_results:
            self._results_dirty = True
            if not hasattr(self, "_stale_result_case_indexes"):
                self._stale_result_case_indexes = set()
            if all_cases:
                self._all_results_stale = True
                self._stale_result_case_indexes.clear()
            elif not getattr(self, "_all_results_stale", False):
                targets = case_indexes
                if targets is None and mark_case:
                    targets = [self._current_case_idx if case_idx is None else case_idx]
                for target in targets or []:
                    try:
                        self._stale_result_case_indexes.add(int(target))
                    except (TypeError, ValueError):
                        continue

    def _mark_results_fresh(self):
        self._results_dirty = False
        self._stale_result_case_indexes = set()
        self._all_results_stale = False
        self._has_rendered_results = bool(self._all_results)

    def _show_result_jump_hint(self, stale=False, reason=None):
        title, content = case_result_jump_hint(stale=stale, reason=reason)
        InfoBar.warning(
            title=title,
            content=content,
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=2500,
        )

    def _case_result_nav_label(self, case_idx):
        if 0 <= case_idx < len(self._cases):
            return self._case_label(self._cases[case_idx], case_idx)
        return f"工况 {case_idx + 1}"

    def _case_result_nav_summary(self, case_idx, inp, result):
        if getattr(result, "recommended", None) is None:
            return "计算失败"
        rec = result.recommended
        q_text = f"Q={inp.Q:g}"
        if rec is None:
            return q_text
        if _is_pe_candidate(rec):
            return (
                f"{q_text} · DN={_fmt_g(rec.nominal_outer_diameter_mm)}mm"
                f" · di={_fmt_g(rec.hydraulic_inner_diameter_mm)}mm"
            )
        if _is_product_candidate(rec):
            return (
                f"{q_text} · {rec.nominal_symbol}={_fmt_g(rec.nominal_diameter_mm)}mm"
                f" · di={_fmt_g(rec.hydraulic_inner_diameter_mm)}mm"
            )
        return f"{q_text} · D={rec.D*1000:.0f}mm"

    def _build_case_nav_items(self):
        items = []
        for case_idx, inp, result in self._all_results:
            items.append({
                "case_idx": case_idx,
                "anchor_id": make_case_result_anchor(self._panel_key, case_idx),
                "label": self._case_result_nav_label(case_idx),
                "summary": self._case_result_nav_summary(case_idx, inp, result),
                "is_error": getattr(result, "recommended", None) is None,
            })
        return items

    def _jump_to_case_result(self, case_idx, *, defer_until_load=False):
        if not has_fresh_case_results(**self._case_result_state_kwargs(case_idx)):
            all_results_stale = getattr(self, "_all_results_stale", False)
            self._show_result_jump_hint(
                stale=is_case_result_stale(
                    case_idx=case_idx,
                    results_dirty=self._results_dirty,
                    stale_case_indexes=getattr(self, "_stale_result_case_indexes", set()),
                    all_results_stale=all_results_stale,
                ),
                reason="structure_stale" if all_results_stale else None,
            )
            return False
        self.notebook.setCurrentIndex(0)
        return scroll_view_to_anchor(
            self.result_view,
            make_case_result_anchor(self._panel_key, case_idx),
            highlight=True,
            smooth=True,
            defer_until_load=defer_until_load,
        )

    def _case_view(self, case, idx):
        q_text = (case.get('Q', '') or '').strip() or '?'
        length_text = (case.get('length', '') or '').strip()
        custom = (case.get('custom_label') or '').strip()
        label = f"{custom or '有压管道'} · Q={q_text}"
        return {
            "label": label,
            "tooltip": f"{label}\n设计流量 Q={q_text} m³/s" + (f"\n管长 L={length_text} m" if length_text else ""),
        }

    def _case_label(self, case, idx):
        return self._case_view(case, idx)["label"]

    def _on_case_renamed(self, idx, new_name):
        if 0 <= idx < len(self._cases):
            self._cases[idx]['custom_label'] = new_name
            self._rebuild_case_tags()

    def _apply_to_all_cases(self):
        """将当前工况的参数（不含Q）复制到所有其他工况"""
        self._save_current_case()
        self._mark_results_dirty(
            case_indexes=[i for i in range(len(self._cases)) if i != self._current_case_idx]
        )
        src = self._cases[self._current_case_idx]
        for i, case in enumerate(self._cases):
            if i != self._current_case_idx:
                self._copy_case_parameters(src, case)
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
        self._mark_results_dirty()
        prev = self._cases[self._current_case_idx - 1]
        curr = self._cases[self._current_case_idx]
        self._copy_case_parameters(prev, curr)
        self._load_case(self._current_case_idx)
        InfoBar.success(title="已复制", content=f"已从工况{self._current_case_idx}复制参数",
                        parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)
        self.data_changed.emit()

    def _show_initial_help(self):
        """初始帮助页：含水力计算及各类有压管产品规格依据摘要。"""
        self._initial_help_rendered = True
        sync_case_result_nav_bar(getattr(self, "_result_case_nav", None), [])
        h = HelpPageBuilder("有压管道水力计算", '请输入参数后点击"计算"按钮')

        h.section("支持功能")
        h.bullet_list([
            "单次计算：自动推荐经济管径，展示前5个候选规格",
            "PE 选型：选好材料等级和公称压力，程序自动匹配壁厚并推荐管径",
            "指定管径：PE 管填写公称外径，其他管材按输入框标注填写；留空按规范推荐",
            "批量计算：多管材/多工况扫描，生成 CSV + PDF 图表",
        ])
        h.text("管材支持：聚乙烯（PE）管、玻璃钢夹砂管、球墨铸铁管、预应力钢筒混凝土管、钢管")
        h.hint(
            "管材选型说明：球墨铸铁管 DN 需由外径、壁厚和内衬换算名义内径；"
            "PCCPE/PCCPL 与三档摩阻参数预设相互独立；玻璃钢夹砂管只用内径系列自动选型，"
            "外径系列仅作连接和采购参考。"
        )
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
        h.section("规范依据：GB/T 20203-2017（摘要）")
        h.text("《管道输水灌溉工程技术规范》 GB/T 20203-2017 第5.1.4~5.1.6条。")

        h.section("5.1.4.1  管道沿程水头损失（式14）")
        h.text("管道沿程水头损失应按式(14)计算，各种管材的 f、m、b 值可按表4确定。")
        h.formula("hf = f × Q^m × L / D^b", "沿程水头损失公式 (式14)")
        h.bullet_list([
            "hf —— 管道沿程水头损失，单位为米(m)",
            "f —— 管材摩阻系数",
            "Q —— 计算管段的设计流量，单位为立方米每小时(m³/h)",
            "D —— 管道内径，单位为毫米(mm)",
            "L —— 管长，单位为米(m)",
            "m —— 流量指数",
            "b —— 管径指数",
        ])

        h.section("表4  f、m、b 值（摘要）")
        h.table(
            ["管材类别", "f", "m", "b"],
            [
                ["混凝土管 (n=0.013)", "1.312×10⁶", "2", "5.33"],
                ["混凝土管 (n=0.014)", "1.516×10⁶", "2", "5.33"],
                ["混凝土管 (n=0.015)", "1.749×10⁶", "2", "5.33"],
                ["硬塑料管", "0.948×10⁵", "1.77", "4.77"],
                ["钢管、铸铁管", "6.25×10⁵", "1.9", "5.1"],
                ["球墨铸铁管", "1.899×10⁵ ~ 2.232×10⁵", "1.852", "4.87"],
                ["铝合金管", "0.861×10⁵", "1.74", "4.74"],
            ]
        )
        h.hint(
            "球墨铸铁管 f 值在规范中为区间；程序同时列出 1.899×10⁵ 与 "
            "2.232×10⁵ 两组水损。推荐和类别判定仍按上限值，用户可按设计依据取用。"
        )

        h.section("5.1.4.4  管道局部水头损失（式17）")
        h.text("管道局部水头损失应按式(17)计算，规划阶段可按沿程水头损失的 10%~15% 估算。")
        h.formula("hj = ζ × v^2 / (2g)", "局部水头损失公式 (式17)")
        h.bullet_list([
            "hj —— 管道局部水头损失，单位为米(m)",
            "ζ —— 局部损失系数",
            "v —— 管内流速，单位为米每秒(m/s)",
            "g —— 重力加速度，单位为米每二次方秒(m/s²)",
        ])
        h.hint("本程序局部损失按比例法简化：默认局部损失比例 0.15，可按 10%~15% 范围手动调整。")

        h.section("5.1.5  允许设计流速（摘要）")
        h.text("5.1.5.1 允许设计流速宜根据管线、管材、管径、管网结构及管道投资、运行成本等因素综合考虑确定。")
        h.bullet_list([
            "5.1.5.2(a)：在设计流量下，管内最小流速不宜低于 0.3 m/s；配水管网兼有施肥或施药任务时，不宜低于 0.6 m/s。",
            "5.1.5.2(b)：自压管道输水灌溉系统设计流速不宜大于 2.5 m/s；采用较大流速时应进行惯性力和推力分析。",
            "5.1.5.2(c)：机压管道输水灌溉系统设计流速不宜大于 2.0 m/s。",
            "5.1.5.3：采用多泥沙水源时，设计流速应大于管道临界不淤流速，缺乏试验时可按附录A经验公式计算。",
        ])

        h.section("5.1.6  管径与管道工作压力（摘要）")
        h.text("5.1.6.1 管道系统各管段直径应通过技术经济分析计算确定；初选管径时可按式(18)估算。")
        h.formula("D = 18.8 × √(Q / v)", "初选管径估算公式 (式18)")
        h.text("5.1.6.2 计算管径时，流速可采用经济流速，不同管材可按表5确定。")

        h.section("表5  管道经济流速推荐表（单位：m/s，摘要）")
        h.table(
            ["管材类别", "经济流速范围 (m/s)"],
            [
                ["混凝土管", "0.5 ~ 1.0"],
                ["钢筋混凝土管", "0.8 ~ 1.5"],
                ["硬塑料管", "1.0 ~ 1.5"],
                ["金属管", "1.5 ~ 2.0"],
                ["薄膜管", "0.5 ~ 1.2"],
            ]
        )
        h.text("5.1.6.4 正常运行时管顶内水压不宜小于 2m，局部不应出现负值。")
        h.hint("说明：本程序当前推荐筛选规则仍按 GB 50288-2018 执行；GB/T 20203-2017 条款在此页面按摘要并列展示。")

        h.divider()
        h.section("PE 管怎么选管径")
        h.text("PE 管按公称外径 DN 选规格。例如 DN630，指公称外径 630 mm。")
        h.text(
            "先选材料等级和公称压力。管径留空时，程序按规范推荐满足流速和水损要求的最小管径；"
            "也可输入已有的标准管径。壁厚由程序查表确定，流速和水损按内径计算。"
        )
        h.text("规格依据：GB/T 13663.2—2018《给水用聚乙烯（PE）管道系统 第2部分：管材》。")

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
        if not math.isfinite(Q) or Q <= 0:
            raise ValueError(f"工况{case_num}: Q 必须大于 0，且为有限数值")

        length_text = (case.get('length', '') or '').strip()
        if not length_text:
            raise ValueError(f"工况{case_num}: 请输入管长 L")
        try:
            length_m = float(length_text)
        except ValueError:
            raise ValueError(f"工况{case_num}: 管长 L 输入无效")
        if not math.isfinite(length_m) or length_m <= 0:
            raise ValueError(f"工况{case_num}: 管长 L 必须大于 0，且为有限数值")

        mat_key = case.get('material_key')
        if mat_key not in PIPE_MATERIALS:
            try:
                mat_idx = int(case.get('material_idx', 0))
            except (TypeError, ValueError):
                mat_idx = 0
            mat_key = (
                LEGACY_MATERIAL_KEY_ORDER_V1[mat_idx]
                if 0 <= mat_idx < len(LEGACY_MATERIAL_KEY_ORDER_V1)
                else self._mat_keys[0]
            )
        if mat_key not in PIPE_MATERIALS:
            mat_key = self._mat_keys[0]

        increase_resolution = resolve_increase_input(
            use_increase=case.get('inc_checked', True),
            mode=case.get('inc_mode', INCREASE_MODE_PERCENT),
            design_q=Q,
            percent_text=case.get('inc_pct', ''),
            q_increased_text=case.get('inc_q_text', ''),
            disabled_percent=0.0,
        )
        manual_pct = increase_resolution.manual_increase_percent

        ratio_text = (case.get('local_ratio', '') or '').strip()
        if not ratio_text:
            raise ValueError(f"工况{case_num}: 请输入局部损失比例")
        try:
            local_ratio = float(ratio_text)
        except ValueError:
            raise ValueError(f"工况{case_num}: 局部损失比例输入无效")
        if not math.isfinite(local_ratio) or local_ratio < 0:
            raise ValueError(f"工况{case_num}: 局部损失比例不能为负数，且必须为有限数值")

        manual_D = None
        manual_pe_dn = None
        manual_product_dn = None
        steel_kwargs = {}
        use_product_catalog = bool(case.get('use_product_catalog', False))
        ductile_iron_class = str(
            case.get('ductile_iron_class', 'PREFERRED') or 'PREFERRED'
        ).upper()
        if use_product_catalog and mat_key == "球墨铸铁管":
            get_ductile_iron_specs(ductile_iron_class)
        pccp_variant = str(case.get('pccp_variant', 'PCCPE') or 'PCCPE').upper()
        pe_grade = str(case.get('pe_grade', 'PE100') or 'PE100').upper()
        try:
            pe_pn_mpa = float(case.get('pe_pn_mpa', 1.0))
            get_pe_sdr(pe_grade, pe_pn_mpa)
        except (TypeError, ValueError) as ex:
            raise ValueError(f"工况{case_num}: {ex}") from ex

        if mat_key == "HDPE管":
            dn_text = (case.get('pe_dn_mm', '') or '').strip()
            if dn_text:
                try:
                    manual_pe_dn = float(dn_text)
                    spec = get_pe_pipe_spec(pe_grade, pe_pn_mpa, manual_pe_dn)
                except (TypeError, ValueError) as ex:
                    raise ValueError(
                        f"工况{case_num}: PE 公称外径 DN 必须取 {PE_STANDARD} "
                        f"中所选等级/PN 的离散规格；{ex}"
                    ) from ex
                manual_pe_dn = float(spec.nominal_outer_diameter_mm)
            legacy_d_text = case.get('legacy_pe_manual_D')
            if legacy_d_text is None and 'pe_dn_mm' not in case:
                legacy_d_text = case.get('D', '')
            legacy_d_text = str(legacy_d_text or '').strip()
            if legacy_d_text:
                try:
                    manual_D = float(legacy_d_text)
                except ValueError as ex:
                    raise ValueError(f"工况{case_num}: 旧版 PE 水力内径 D 输入无效") from ex
                if not math.isfinite(manual_D) or manual_D <= 0:
                    raise ValueError(f"工况{case_num}: 旧版 PE 水力内径 D 必须大于 0")
        elif get_catalog_family(mat_key) and use_product_catalog:
            dn_text = (case.get('product_dn_mm', '') or '').strip()
            if dn_text:
                try:
                    spec = get_pipe_product_spec(
                        mat_key, dn_text,
                        ductile_iron_class=ductile_iron_class,
                        pccp_variant=pccp_variant,
                    )
                except (TypeError, ValueError) as ex:
                    raise ValueError(
                        f"工况{case_num}: 指定公称直径不在当前可选规格中；{ex}"
                    ) from ex
                manual_product_dn = float(spec.nominal_diameter_mm)
            legacy_d_text = str(case.get('legacy_product_manual_D') or '').strip()
            if legacy_d_text:
                try:
                    manual_D = float(legacy_d_text)
                except ValueError as ex:
                    raise ValueError(
                        f"工况{case_num}: 旧版产品水力内径 D 输入无效"
                    ) from ex
                if not math.isfinite(manual_D) or manual_D <= 0:
                    raise ValueError(
                        f"工况{case_num}: 旧版产品水力内径 D 必须大于 0"
                    )
        elif mat_key == '钢管':
            try:
                steel_kwargs = parse_steel_state(case)
            except ValueError as exc:
                raise ValueError(f'工况{case_num}: {exc}') from exc
        else:
            d_text = (case.get('D', '') or '').strip()
            if d_text:
                try:
                    manual_D = float(d_text)
                except ValueError as ex:
                    raise ValueError(f"工况{case_num}: 管径 D 输入无效") from ex
                if not math.isfinite(manual_D) or manual_D <= 0:
                    raise ValueError(f"工况{case_num}: 指定管径 D 必须大于 0，且为有限数值")

        parsed = PressurePipeInput(
            Q=Q, material_key=mat_key,
            length_m=length_m,
            manual_increase_percent=manual_pct,
            local_loss_ratio=local_ratio,
            manual_D=manual_D,
            pe_material_grade=pe_grade,
            pe_nominal_pressure_mpa=pe_pn_mpa,
            manual_nominal_diameter_mm=manual_pe_dn,
            use_product_catalog=use_product_catalog,
            manual_product_diameter_mm=manual_product_dn,
            ductile_iron_class=ductile_iron_class,
            pccp_variant=pccp_variant,
            **steel_kwargs,
        )
        parsed.inc_mode = increase_resolution.mode
        parsed.inc_pct_text = case.get('inc_pct', '')
        parsed.inc_q_text = case.get('inc_q_text', '')
        parsed.use_increase = case.get('inc_checked', True)
        return parsed

    def _calculate(self):
        self._save_current_case()
        self._all_results = []
        errors = []

        for i, case in enumerate(self._cases):
            try:
                inp = self._parse_case(case, i + 1)
            except (ValueError, TypeError) as ex:
                msg = str(ex)
                errors.append(msg)
                q_text = (case.get('Q', '') or '').strip()
                length_text = (case.get('length', '') or '').strip()
                try:
                    q_value = float(q_text) if q_text else 0.0
                except Exception:
                    q_value = 0.0
                try:
                    length_value = float(length_text) if length_text else 0.0
                except Exception:
                    length_value = 0.0
                mat_key = case.get('material_key')
                if mat_key not in PIPE_MATERIALS:
                    try:
                        mat_idx = int(case.get('material_idx', 0))
                    except (TypeError, ValueError):
                        mat_idx = 0
                    mat_key = (
                        LEGACY_MATERIAL_KEY_ORDER_V1[mat_idx]
                        if 0 <= mat_idx < len(LEGACY_MATERIAL_KEY_ORDER_V1)
                        else self._mat_keys[0]
                    )
                if mat_key not in PIPE_MATERIALS:
                    mat_key = self._mat_keys[0]
                inp = SimpleNamespace(
                    Q=q_value,
                    material_key=mat_key,
                    length_m=length_value,
                    use_increase=case.get('inc_checked', True),
                    inc_mode=normalize_increase_mode(case.get('inc_mode', INCREASE_MODE_PERCENT)),
                    inc_pct_text=case.get('inc_pct', ''),
                    inc_q_text=case.get('inc_q_text', ''),
                )
                self._all_results.append((
                    i,
                    inp,
                    SimpleNamespace(
                        recommended=None,
                        reason=msg,
                        category="无可用",
                        top_candidates=[],
                        calc_steps=msg,
                        auto_recommended=None,
                    ),
                ))
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
                sync_case_result_nav_bar(getattr(self, "_result_case_nav", None), [])
                load_formula_page(self.result_view, plain_text_to_formula_html(err_txt))
                self.notebook.setCurrentIndex(0)
                self.data_changed.emit()
            return

        # 向后兼容
        _, _, first_result = self._all_results[0]
        self.current_result = first_result
        plain_text_parts = []
        for idx, inp, res in self._all_results:
            part_lines = [f"===== 工况{idx+1} ====="]
            if getattr(res, "recommended", None) is not None:
                part_lines.extend(self._increase_summary_lines(inp, res))
                part_lines.append("")
            part_lines.append(res.calc_steps)
            plain_text_parts.append("\n".join(part_lines))
        self._export_plain_text = "\n\n".join(plain_text_parts)

        # 显示结果
        self._display_all_results()
        self.data_changed.emit()

    def _build_result_card_html(self, case_idx, inp, result):
        """按设计/加大工况并列展示结果，保留候选排序及产品尺寸说明。"""
        rec = result.recommended
        mat_name = _material_display_name(inp.material_key)
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
        increase_summary_html = "".join(
            f'<div style="font-size:12px;color:#4a5568;line-height:1.6;">{_e(line)}</div>'
            for line in self._increase_summary_lines(inp, result)
        )
        is_pe = _is_pe_candidate(rec)
        is_product = _is_product_candidate(rec) and not is_pe
        legacy_migration_flags = [
            flag for flag in getattr(rec, "flags", [])
            if str(flag).startswith("旧版水力内径")
        ]
        migration_html = ""
        if legacy_migration_flags:
            migration_review_text = (
                "请按当前工程压力与温度复核 PN 后保存"
                if is_pe else "请按当前工程压力、结构和供货条件复核后保存"
            )
            migration_html = f"""
        <div style="margin:8px 0;padding:10px 14px;background:#fff8e1;
                    border:1px solid #ffcc80;border-left:5px solid #ef6c00;border-radius:8px;
                    font-size:12px;color:#8a4b08;">
            旧项目规格迁移：{_e(legacy_migration_flags[0])}。{_e(migration_review_text)}。
        </div>"""
        frpm_boundary = _frpm_dimension_boundary(rec)
        if frpm_boundary:
            frpm_range_text, frpm_tolerance_text = frpm_boundary
            frpm_boundary_html = f"""
            <div style="font-size:12px;color:#455a64;margin-top:4px;">
                管端内直径允许范围 {_e(frpm_range_text)}；相对所选设计内径值允许偏差
                {_e(frpm_tolerance_text)}。定案时仍须按厂家选定设计内径和实测尺寸复核。</div>"""
        else:
            frpm_boundary_html = ""
        if is_pe:
            procurement_html = f"""
        <div style="margin:8px 0 10px;padding:13px 16px;background:#eef8ff;
                    border:1px solid #90caf9;border-left:5px solid #1565c0;border-radius:8px;
                    font-family:'Microsoft YaHei',sans-serif;">
            <div style="font-size:11px;color:#607d8b;margin-bottom:4px;">造价 / 采购规格</div>
            <div style="font-size:16px;font-weight:800;color:#0d47a1;">
                {_e(_pe_procurement_text(rec))}</div>
            <div style="font-size:12px;color:#455a64;margin-top:5px;">
                水力计算采用名义内径 d<sub>i</sub> = {_fmt_g(rec.hydraulic_inner_diameter_mm)} mm，
                公称外径 DN 用于造价与采购。</div>
        </div>"""
        elif is_product:
            product_heading = '造价 / 采购规格'
            if rec.product_family == 'STEEL':
                product_heading = steel_result_heading(result)
            procurement_html = f"""
        <div style="margin:8px 0 10px;padding:13px 16px;background:#eef8ff;
                    border:1px solid #90caf9;border-left:5px solid #1565c0;border-radius:8px;
                    font-family:'Microsoft YaHei',sans-serif;">
            <div style="font-size:11px;color:#607d8b;margin-bottom:4px;">{_e(product_heading)}</div>
            <div style="font-size:16px;font-weight:800;color:#0d47a1;">
                {_e(_product_procurement_text(rec))}</div>
            <div style="font-size:12px;color:#455a64;margin-top:5px;">
                水力计算采用 {_e(getattr(rec, 'hydraulic_inner_diameter_basis', None) or '计算内径')} d<sub>i</sub> =
                {_fmt_g(rec.hydraulic_inner_diameter_mm)} mm。</div>
            {frpm_boundary_html}
        </div>"""
        else:
            procurement_html = ""
        has_f_range = (
            inp.material_key == "球墨铸铁管"
            and getattr(rec, "hf_total_lower_km", None) is not None
            and getattr(rec, "h_loss_total_lower_m", None) is not None
        )
        # 推荐或指定结论集中放在首屏，不再依赖末尾重复的结果汇总。
        result_label = '指定管径' if is_manual else '参考管径' if result.category == '兜底' else '推荐管径'
        nominal_mm = rec.nominal_outer_diameter_mm if is_pe else rec.nominal_diameter_mm if is_product else None
        result_heading = (f'{result_label} DN {_fmt_g(nominal_mm)}' if nominal_mm is not None
                          else f'{result_label}（水力内径）{rec.D * 1000:g} mm')
        # 同一指标按设计/加大两列展示，分类与选径仍使用内核的原始结果。
        flow = compare_flows(inp, rec)
        loss_condition_label = flow.loss_label
        html = case_header + migration_html + flow_summary_html(
            inp, rec, result_heading, mat_name, cat_color,
        )

        if has_f_range:
            html += """
        <div style="margin:4px 0 8px;padding:8px 12px;background:#eef6ff;
                    border-left:3px solid #1976d2;border-radius:5px;font-size:12px;color:#3f4f5f;">
            球墨铸铁管的推荐管径与类别按 f 上限 223200 判定；结果表同时列出
            f 上限 223200 和 f 下限 189900，用户可按采用的设计依据选取。
        </div>"""

        # 自动推荐对比条（仅指定D模式，且自动推荐与指定D不同时）
        auto_rec = result.auto_recommended
        manual_differs = False
        if is_manual and auto_rec is not None:
            if is_pe and _is_pe_candidate(auto_rec):
                manual_differs = (
                    auto_rec.nominal_outer_diameter_mm != rec.nominal_outer_diameter_mm
                )
            elif is_product and _is_product_candidate(auto_rec):
                manual_differs = auto_rec.product_spec_id != rec.product_spec_id
            else:
                manual_differs = abs(auto_rec.D - rec.D) > 1e-6
        if manual_differs:
            ac = {"经济": S, "妥协": W, "兜底": E}.get(auto_rec.category, T2)
            auto_dimension_text = (
                _pe_procurement_text(auto_rec, include_standard=False)
                + f"；di={_fmt_g(auto_rec.hydraulic_inner_diameter_mm)} mm"
                if _is_pe_candidate(auto_rec)
                else _product_procurement_text(auto_rec, include_standard=False)
                + f"；di={_fmt_g(auto_rec.hydraulic_inner_diameter_mm)} mm"
                if _is_product_candidate(auto_rec)
                else f"D = {auto_rec.D}m ({auto_rec.D*1000:.0f}mm)"
            )
            html += f"""
        <div style="display:flex;gap:14px;margin:2px 0 6px;padding:8px 18px;
                    background:{CARD};border:1px dashed {ac};border-radius:8px;
                    align-items:center;flex-wrap:wrap;opacity:0.85;">
            <span style="background:{ac};color:white;padding:2px 10px;
                         border-radius:10px;font-size:11px;font-weight:bold;">
                自动推荐({auto_rec.category}区)</span>
            <span style="font-size:12px;color:{T2};">{_e(auto_dimension_text)}</span>
            <span style="font-size:12px;color:{T2};">设计流速 = {auto_rec.V_press:.4f} m/s</span>
            <span style="font-size:12px;color:{T2};">{loss_condition_label}总水损 = {auto_rec.hf_total_km:.4f} m/km</span>
            <span style="font-size:12px;color:{T2};">{loss_condition_label}全管长水损 = {auto_rec.h_loss_total_m:.4f} m</span>
        </div>"""

        # 候选表
        _CAT_COLORS = {"经济": "#2e7d32", "妥协": "#e67e22", "兜底": "#c62828", "指定": "#1565c0"}
        candidates = result.top_candidates
        candidate_explanations = []
        if candidates:
            _tbl_title = f"候选管径对比（工况{case_idx+1}：Q = {inp.Q} m³/s）" if _multi else "候选管径对比"
            pe_table_note = ""
            if is_pe:
                pe_table_note = (
                    f" · {rec.pe_material_grade} / SDR{_fmt_g(rec.pe_sdr)} / "
                    f"PN{_fmt_g(rec.pe_nominal_pressure_mpa)} MPa · {rec.product_standard or PE_STANDARD}"
                )
            elif is_product:
                pe_table_note = " · " + " / ".join(rec.product_standard_references)
            html += f"""
        <div style="font-size:13px;font-weight:600;color:#555;margin:10px 0 4px;
                    padding-left:4px;border-left:3px solid #90caf9;">
            {_tbl_title}
            <span style="font-size:11px;color:#888;margin-left:8px;font-weight:500;">
                排序：推荐优先，类别优先，同类别按总水损{_e(pe_table_note)}
            </span>
        </div>"""
            if is_pe:
                dimension_header_html = """
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">公称外径 × 壁厚<br>DN×en(mm)</th>
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">材料 / SDR / PN</th>
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">水力内径<br>di(mm)</th>"""
            elif is_product:
                dimension_header_html = """
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">产品规格</th>
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">水力内径<br>di(mm)</th>"""
            else:
                dimension_header_html = """
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">D(m)</th>
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">D(mm)</th>"""
            loss_title = f'{loss_condition_label}总水损'
            range_note = '<br>f 上限 / 下限' if has_f_range else ''
            loss_header_html = f'<th style="padding:7px 8px;color:#555;font-size:12px;">{loss_title}{range_note}<br>(m/km)</th>'
            increased_header_html = ('<th style="padding:7px 8px;color:#555;font-size:12px;">'
                                     '加大流速<br>(m/s)</th>') if flow.show_increased else ''
            html += f"""
        <table class="candidate-comparison" style="width:100%;border-collapse:collapse;font-size:13px;margin:4px 0 12px;">
            <tr style="background:#f8f9fa;">
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">#</th>
                {dimension_header_html}
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">设计流速<br>(m/s)</th>
                {increased_header_html}
                {loss_header_html}
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;">类别<br>按设计流速</th>
                <th style="padding:7px 8px;border-bottom:2px solid #e0e0e0;color:#555;
                           font-weight:600;text-align:center;font-size:12px;"></th>
            </tr>"""
            for i, c in enumerate(candidates):
                if is_pe and _is_pe_candidate(c):
                    is_rec = (
                        rec is not None
                        and c.nominal_outer_diameter_mm == rec.nominal_outer_diameter_mm
                    )
                    dimension_cells_html = f"""
                <td style="{{td_s}}">DN{_fmt_g(c.nominal_outer_diameter_mm)}×{_fmt_g(c.nominal_wall_thickness_mm)}</td>
                <td style="{{td_s}}">{_e(c.pe_material_grade)} / SDR{_fmt_g(c.pe_sdr)}<br>PN{_fmt_g(c.pe_nominal_pressure_mpa)} MPa</td>
                <td style="{{td_s}}">{_fmt_g(c.hydraulic_inner_diameter_mm)}</td>"""
                elif is_product and _is_product_candidate(c):
                    is_rec = bool(rec and c.product_spec_id == rec.product_spec_id)
                    dimension_cells_html = f"""
                <td style="{{td_s}}">{_e(c.nominal_symbol)} {_fmt_g(c.nominal_diameter_mm)}</td>
                <td style="{{td_s}}">{_fmt_g(c.hydraulic_inner_diameter_mm)}</td>"""
                else:
                    is_rec = bool(rec and abs(c.D - rec.D) < 1e-6)
                    dimension_cells_html = f"""
                <td style="{{td_s}}">{c.D:.3f}</td>
                <td style="{{td_s}}">{c.D*1000:.0f}</td>"""
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
                display_cat = "指定" if is_user else c.category
                cc = _CAT_COLORS.get(display_cat, "#666")
                badge_html = ""
                if is_user:
                    badge_html = ('<span style="display:inline-block;background:#e67e22;color:#fff;'
                                  'padding:2px 8px;border-radius:10px;font-size:11px;'
                                  'font-weight:600;">★ 指定</span>')
                elif is_rec:
                    is_steel_reference = c.product_family == 'STEEL' and c.category == '兜底'
                    badge_color = '#c62828' if is_steel_reference else '#2e7d32'
                    badge_label = '参考' if is_steel_reference else '推荐'
                    badge_html = (f'<span style="display:inline-block;background:{badge_color};color:#fff;'
                                  'padding:2px 8px;border-radius:10px;font-size:11px;'
                                  f'font-weight:600;">★ {badge_label}</span>')
                td_s = f"padding:7px 8px;text-align:center;border-bottom:1px solid #f0f0f0;{td_extra}"
                if has_f_range and getattr(c, "hf_total_lower_km", None) is not None:
                    total_cell = f"{c.hf_total_km:.4f}<br>{c.hf_total_lower_km:.4f}"
                else:
                    total_cell = f"{c.hf_total_km:.4f}"
                candidate_flow = compare_flows(inp, c)
                increased_cell_html = ''
                if flow.show_increased:
                    value = candidate_flow.loss_velocity
                    value_text = '—' if value is None else f'{value:.4f}'
                    velocity_status, velocity_color = velocity_note(value)
                    increased_cell_html = (f'<td style="{td_s}color:{velocity_color};" '
                                           f'title="{_e(velocity_status)}">{value_text}</td>')
                dimension_cells_html = dimension_cells_html.format(td_s=td_s)
                html += f"""
            <tr style="{row_style}">
                <td style="{td_s}">{i+1}</td>
                {dimension_cells_html}
                <td style="{td_s}">{c.V_press:.4f}</td>
                {increased_cell_html}
                <td style="{td_s}">{total_cell}</td>
                <td style="{td_s}color:{cc};font-weight:bold;">{_e(display_cat)}</td>
                <td style="{td_s}">{badge_html}</td>
            </tr>"""
                # 当前规格已在尺寸说明中完整代入，其他候选各保留一次。
                if not is_rec:
                    candidate_explanations.append(diameter_candidate_row_html(c, 1))
            html += "\n        </table>"

        # 先完成横向比较，再按推荐规格、流量取值、选径依据和逐档换算查看细节。
        html += procurement_html + f"""
        <div style="margin:8px 0 10px;padding:10px 14px;background:#f8fafc;border:1px solid #dbe7f3;
                    border-radius:8px;font-family:'Microsoft YaHei',sans-serif;">
            {increase_summary_html}
        </div>"""
        html += steel_sizing_html(rec) + build_diameter_explanation_html(rec)
        if any(candidate_explanations):
            html += (
                '<div style="font-size:14px;font-weight:700;color:#34495e;margin:14px 0 8px;">'
                '其他候选的壁厚与内径换算（按对比表顺序，当前规格见上文）</div>'
                '<table class="candidate-dimensions" style="width:100%;border-collapse:collapse;">'
                + ''.join(candidate_explanations) + '</table>'
            )

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
                if _is_pe_candidate(rec):
                    summary = (
                        f"DN={_fmt_g(rec.nominal_outer_diameter_mm)}mm "
                        f"di={_fmt_g(rec.hydraulic_inner_diameter_mm)}mm {cat}"
                    )
                else:
                    summary = f"D={rec.D*1000:.0f}mm {cat}"
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
                    full_html += plain_text_to_formula_html(concise_process_text(result))

        load_formula_page(self.result_view, full_html)
        self.notebook.setCurrentIndex(0)

    def _display_all_results(self):
        """显示所有工况结果，并为多工况提供共享导航与定位。"""
        _multi = len(self._all_results) > 1
        parts = []

        for case_idx, inp, result in self._all_results:
            body_html = self._build_result_card_html(case_idx, inp, result)
            if self.detail_cb.isChecked() and getattr(result, "calc_steps", ""):
                title = f"工况 {case_idx + 1} 详细计算过程" if _multi else "详细计算过程"
                body_html += (
                    f'<h3 style="margin:20px 0 8px;padding:8px 14px;'
                    f'background:#fafafa;border-left:4px solid #1565c0;'
                    f'border-radius:0 8px 8px 0;font-size:15px;'
                    f'font-weight:700;color:#1565c0;">{title}</h3>'
                    f'{plain_text_to_formula_html(concise_process_text(result))}'
                )
            parts.append(
                wrap_case_result_block(
                    self._panel_key,
                    case_idx,
                    f"工况 {case_idx + 1}",
                    body_html,
                    subtitle=self._case_result_nav_label(case_idx),
                    is_error=getattr(result, "recommended", None) is None,
                )
            )

        full_html = "\n".join(parts)
        if _multi:
            nav_builder = getattr(self, "_build_case_nav_items", None)
            nav_items = nav_builder() if callable(nav_builder) else []
            full_html = (
                build_result_navigation_head()
                + build_result_nav_bar(nav_items, hidden=True)
                + full_html
            )
        else:
            nav_items = []
        load_formula_page(self.result_view, full_html)
        sync_case_result_nav_bar(getattr(self, "_result_case_nav", None), nav_items)
        if not getattr(self, "_suppress_project_restore_side_effects", False):
            self.notebook.setCurrentIndex(0)
            self._mark_results_fresh()
            self._jump_to_case_result(self._current_case_idx, defer_until_load=True)

    def _clear(self):
        self._save_current_case()
        self._all_results = []
        self._last_errors = []
        self._results_dirty = False
        self._stale_result_case_indexes = set()
        self._all_results_stale = False
        self._has_rendered_results = False
        self._rebuild_case_tags()
        self._update_calc_btn_text()
        self.current_result = None
        self._export_plain_text = ""
        self._show_initial_help()
        self._refresh_increase_hint()
        InfoBar.success(title="已清空", content="计算结果已清空，输入参数已保留",
                        parent=self, position=InfoBarPosition.TOP_RIGHT, duration=2000)
        self.data_changed.emit()

    # ================================================================
    # Word 导出
    # ================================================================
    def _info_parent(self):
        """获取InfoBar宿主，优先当前页面。"""
        return self

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
        has_pe_product_specs = _results_have_pe_product_specs(self._all_results)
        product_families = _results_product_families(self._all_results)
        base_references = _pressure_pipe_report_references(
            REFERENCES_BASE.get('pressure_pipe', []), has_pe_product_specs, product_families,
            all_results=self._all_results,
        )
        auto_purpose = build_calc_purpose('pressure_pipe', project=meta.project_name)
        dlg = ExportConfirmDialog(
            'pressure_pipe',
            '有压管道水力计算书',
            auto_purpose,
            parent=self._info_parent(),
            base_references=base_references,
        )
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
        refs = list(getattr(self, '_word_export_refs', REFERENCES_BASE.get('pressure_pipe', [])))
        has_pe_product_specs = _results_have_pe_product_specs(self._all_results)
        product_families = _results_product_families(self._all_results)
        refs = _pressure_pipe_report_references(
            refs, has_pe_product_specs, product_families, all_results=self._all_results,
        )

        # 取第一个工况的管材名作为封面描述
        _, first_inp, _ = self._all_results[0]
        first_mat_name = _material_display_name(first_inp.material_key)
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
        doc_add_eng_body(doc, '根据《灌溉与排水工程设计标准》(GB 50288-2018) 第6.7.2条，并参照《管道输水灌溉工程技术规范》(GB/T 20203-2017) 第5.1.4~5.1.6条：')
        doc_add_formula(doc, r'h_f = f \times \frac{L \times Q^m}{d^b}', '沿程水头损失公式：')
        doc_add_formula(doc, r'h_j = \zeta \times \frac{v^2}{2g}', '局部水头损失规范公式（GB/T 20203 式(17)）：')
        doc_add_formula(doc, r'h_j = \xi_j \times h_f', '局部水头损失（按沿程损失比例简化）：')
        doc_add_formula(doc, r'V = \frac{4Q}{\pi D^2}', '管道流速公式（D 取所选规格的公称内径或换算内径）：')
        if has_pe_product_specs:
            doc_add_formula(doc, r'd_i = \mathrm{DN} - 2e_n', 'PE 管名义计算内径：')
            doc_add_eng_body(
                doc,
                f'PE 管产品规格按 {PE_STANDARD} 输出材料等级、DN×en、SDR 和 PN；'
                '造价采用公称外径 DN 规格，流速与水头损失采用名义计算内径 di。'
            )
        if "DI" in product_families:
            doc_add_formula(doc, r'd_i = DE - 2(e_{\mathrm{nom}}+e_c)', '球墨铸铁管名义计算内径：')
            doc_add_eng_body(
                doc,
                '球墨铸铁管按各结果记录的产品标准版本、DN、插口外径 DE、公称壁厚及水泥砂浆内衬厚度换算名义内径；实际供货尺寸仍须复核。'
            )
        if "PCCP" in product_families:
            doc_add_eng_body(
                doc,
                'PCCP 按产品型式和公称内径 DN 选径；PCCPE/PCCPL 型式与水力摩阻预设分别记录，结构、压力等级和配筋不由本水力模块确定。'
            )
        if "FRPM" in product_families:
            doc_add_eng_body(
                doc,
                '玻璃钢夹砂管按 GB/T 21238—2016 内径系列进行水力选径；外径系列仅作连接和采购参考，不在缺少厂家壁厚时反算内径。'
            )
        doc_add_eng_body(doc, '经济流速范围：0.9 m/s ≤ V ≤ 1.5 m/s。')
        doc_add_eng_body(doc, 'GB/T 20203-2017 第5.1.4.4：规划阶段局部损失可按沿程损失的10%~15%估算（程序默认局部损失比例为0.15，可手动调整）。')
        doc_add_eng_body(doc, 'GB/T 20203-2017 第5.1.5.2：允许设计流速要求包括最小流速0.3m/s（施肥施药工况0.6m/s）以及自压系统不宜大于2.5m/s、机压系统不宜大于2.0m/s。')
        doc_add_eng_body(doc, 'GB/T 20203-2017 第5.1.6.4：正常运行时管顶内水压不宜小于2m，局部不应出现负值。')
        doc_add_eng_body(doc, '说明：当前程序推荐筛选规则仍按 GB 50288-2018 执行（经济区0.9~1.5m/s、妥协区0.6~0.9m/s且hf总≤5m/km）。')

        # 6、计算过程
        doc_add_eng_h(doc, '6、计算过程')
        doc_render_calc_text_eng(doc, self._export_plain_text or '',
                                  skip_title_keyword='有压管道水力计算结果')

        # 7、计算结果汇总（逐工况）
        for ri, (case_idx, inp, result) in enumerate(self._all_results):
            rec = result.recommended
            if rec is None:
                continue
            display_result_category = "指定" if result.category == "指定" else result.category
            mat_key = inp.material_key
            mat_name = _material_display_name(mat_key)
            mat_info = PIPE_MATERIALS[mat_key]
            is_pe = _is_pe_candidate(rec)
            is_product = _is_product_candidate(rec) and not is_pe
            section_prefix = f'7.{ri+1}' if n_cases > 1 else '7'
            title = f'{section_prefix}、工况{case_idx+1} 计算结果汇总' if n_cases > 1 else '7、计算结果汇总'
            doc_add_eng_h(doc, title)
            summary_items = [("管材类型", mat_name)]
            if is_pe or is_product:
                nominal_mm = rec.nominal_outer_diameter_mm if is_pe else rec.nominal_diameter_mm
                summary_items.append((
                    "指定管径" if result.category == "指定" else "推荐管径",
                    f"DN {_fmt_g(nominal_mm)}",
                ))
            if is_pe:
                summary_items += [
                    ("造价 / 采购规格", _pe_procurement_text(rec)),
                    ("公称外径 DN", f"{_fmt_g(rec.nominal_outer_diameter_mm)} mm"),
                    ("公称壁厚", f"{_fmt_g(rec.nominal_wall_thickness_mm)} mm"),
                    ("名义计算内径 di", f"{_fmt_g(rec.hydraulic_inner_diameter_mm)} mm"),
                    ("PE 材料 / 压力", f"{rec.pe_material_grade}，SDR{_fmt_g(rec.pe_sdr)}，PN{_fmt_g(rec.pe_nominal_pressure_mpa)} MPa"),
                    ("产品标准", rec.product_standard or PE_STANDARD),
                ]
                legacy_flags = [
                    flag for flag in getattr(rec, "flags", [])
                    if str(flag).startswith("旧版水力内径")
                ]
                if legacy_flags:
                    summary_items.append(("旧项目规格迁移", legacy_flags[0]))
            elif is_product:
                summary_items += [
                    (steel_result_heading(result) if rec.product_family == 'STEEL' else "造价 / 采购规格", _product_procurement_text(rec)),
                    (
                        rec.nominal_basis if rec.product_family == 'STEEL' else f"公称直径 {rec.nominal_symbol}",
                        f"{_fmt_g(rec.nominal_diameter_mm)} mm（{rec.nominal_basis}）",
                    ),
                    (
                        "水力计算内径 di",
                        f"{_fmt_g(rec.hydraulic_inner_diameter_mm)} mm",
                    ),
                    (
                        "水力内径取值依据",
                        rec.hydraulic_inner_diameter_basis or "目录名义内径",
                    ),
                    ("产品标准", "、".join(rec.product_standard_references)),
                ]
                frpm_boundary = _frpm_dimension_boundary(rec)
                if frpm_boundary:
                    frpm_range_text, frpm_tolerance_text = frpm_boundary
                    summary_items += [
                        ("管端内直径允许范围", frpm_range_text),
                        ("相对所选设计内径值允许偏差", frpm_tolerance_text),
                    ]
                legacy_flags = [
                    flag for flag in getattr(rec, "flags", [])
                    if str(flag).startswith("旧版水力内径")
                ]
                if legacy_flags:
                    summary_items.append(("旧项目规格迁移", legacy_flags[0]))
            summary_items += [
                (
                    "管材系数",
                    (
                        f"f = {float(mat_info['f_min']):.0f}～{float(mat_info['f']):.0f}, "
                        f"m = {mat_info['m']}, b = {mat_info['b']}"
                        if mat_info.get("f_min") is not None
                        else f"f = {mat_info['f']}, m = {mat_info['m']}, b = {mat_info['b']}"
                    ),
                ),
                ("设计流量 Q", f"{inp.Q} m³/s"),
                ("管长 L", f"{inp.length_m} m"),
                ("局部损失比例", str(inp.local_loss_ratio)),
            ]
            for line in self._increase_summary_lines(inp, result):
                key, _, value = line.partition(" = ")
                summary_items.append((key, value))
            if not is_pe and not is_product:
                summary_items.append(("推荐管径 D", f"{rec.D} m ({rec.D*1000:.0f} mm)"))
            summary_items += [
                ("推荐类别", display_result_category),
                ("有压流速 V", f"{rec.V_press:.4f} m/s"),
            ]
            if getattr(rec, "hf_total_lower_km", None) is not None:
                summary_items += [
                    ("沿程水损（f上限 / 下限）", f"{rec.hf_friction_km:.4f} / {rec.hf_friction_lower_km:.4f} m/km"),
                    ("局部水损（f上限 / 下限）", f"{rec.hf_local_km:.4f} / {rec.hf_local_lower_km:.4f} m/km"),
                    ("总水损（f上限 / 下限）", f"{rec.hf_total_km:.4f} / {rec.hf_total_lower_km:.4f} m/km"),
                    ("按管长折算总损失（f上限 / 下限）", f"{rec.h_loss_total_m:.4f} / {rec.h_loss_total_lower_m:.4f} m"),
                    ("取值说明", "推荐与类别判定按 f 上限；上下限结果均供设计选用"),
                ]
            else:
                summary_items += [
                    ("沿程水损", f"{rec.hf_friction_km:.4f} m/km"),
                    ("局部水损", f"{rec.hf_local_km:.4f} m/km"),
                    ("总水损", f"{rec.hf_total_km:.4f} m/km"),
                    ("按管长折算总损失", f"{rec.h_loss_total_m:.4f} m"),
                ]
            doc_add_result_table(doc, summary_items)
            add_steel_sizing_to_word(doc, rec)
            add_diameter_summary_to_word(doc, rec)

            # 候选管径对比表
            candidates = result.top_candidates
            if candidates:
                sec_num = f'8.{ri+1}' if n_cases > 1 else '8'
                doc_add_eng_h(doc, f'{sec_num}、候选管径对比表')
                doc_add_eng_body(doc, '排序规则：推荐优先，类别优先级（经济→妥协→兜底），同类别按总水头损失升序。')
                has_f_range = getattr(rec, "hf_total_lower_km", None) is not None
                if is_pe:
                    headers = [
                        "公称外径×壁厚 DN×en(mm)", "材料/SDR/PN", "水力内径 di(mm)",
                        "V(m/s)", "hf(m/km)", "hj(m/km)", "hf总(m/km)", "H损(m)", "类别",
                    ]
                elif is_product:
                    loss_headers = (
                        ["hf上/下(m/km)", "hj上/下(m/km)", "hf总上/下(m/km)", "H损上/下(m)"]
                        if has_f_range else ["hf(m/km)", "hj(m/km)", "hf总(m/km)", "H损(m)"]
                    )
                    headers = ["产品规格", "水力内径 di(mm)", "V(m/s)", *loss_headers, "类别"]
                elif has_f_range:
                    headers = [
                        "D(m)", "D(mm)", "V(m/s)", "hf上/下(m/km)",
                        "hj上/下(m/km)", "hf总上/下(m/km)", "H损上/下(m)", "类别",
                    ]
                else:
                    headers = ["D(m)", "D(mm)", "V(m/s)", "hf(m/km)", "hj(m/km)",
                                "hf总(m/km)", "H损(m)", "类别"]
                data = []
                for c in candidates:
                    display_cat = "指定" if "用户指定" in c.flags else c.category
                    if is_pe and _is_pe_candidate(c):
                        data.append([
                            f"DN{_fmt_g(c.nominal_outer_diameter_mm)}×{_fmt_g(c.nominal_wall_thickness_mm)}",
                            f"{c.pe_material_grade}/SDR{_fmt_g(c.pe_sdr)}/PN{_fmt_g(c.pe_nominal_pressure_mpa)}",
                            _fmt_g(c.hydraulic_inner_diameter_mm),
                            f"{c.V_press:.4f}", f"{c.hf_friction_km:.4f}",
                            f"{c.hf_local_km:.4f}", f"{c.hf_total_km:.4f}",
                            f"{c.h_loss_total_m:.4f}", display_cat,
                        ])
                    elif is_product and _is_product_candidate(c):
                        product_losses = [
                            f"{c.hf_friction_km:.4f}", f"{c.hf_local_km:.4f}",
                            f"{c.hf_total_km:.4f}", f"{c.h_loss_total_m:.4f}",
                        ]
                        if has_f_range and getattr(c, "hf_total_lower_km", None) is not None:
                            product_losses = [
                                f"{c.hf_friction_km:.4f} / {c.hf_friction_lower_km:.4f}",
                                f"{c.hf_local_km:.4f} / {c.hf_local_lower_km:.4f}",
                                f"{c.hf_total_km:.4f} / {c.hf_total_lower_km:.4f}",
                                f"{c.h_loss_total_m:.4f} / {c.h_loss_total_lower_m:.4f}",
                            ]
                        data.append([
                            _product_procurement_text(c, include_standard=False),
                            _fmt_g(c.hydraulic_inner_diameter_mm), f"{c.V_press:.4f}",
                            *product_losses, display_cat,
                        ])
                    elif has_f_range and getattr(c, "hf_total_lower_km", None) is not None:
                        data.append([
                            f"{c.D:.3f}", f"{c.D*1000:.0f}", f"{c.V_press:.4f}",
                            f"{c.hf_friction_km:.4f} / {c.hf_friction_lower_km:.4f}",
                            f"{c.hf_local_km:.4f} / {c.hf_local_lower_km:.4f}",
                            f"{c.hf_total_km:.4f} / {c.hf_total_lower_km:.4f}",
                            f"{c.h_loss_total_m:.4f} / {c.h_loss_total_lower_m:.4f}",
                            display_cat,
                        ])
                    else:
                        data.append([
                            f"{c.D:.3f}", f"{c.D*1000:.0f}", f"{c.V_press:.4f}",
                            f"{c.hf_friction_km:.4f}", f"{c.hf_local_km:.4f}",
                            f"{c.hf_total_km:.4f}", f"{c.h_loss_total_m:.4f}",
                            display_cat,
                        ])
                highlight_value = (
                    f"DN{_fmt_g(rec.nominal_outer_diameter_mm)}×{_fmt_g(rec.nominal_wall_thickness_mm)}"
                    if is_pe else _product_procurement_text(rec, include_standard=False)
                    if is_product else f"{rec.D:.3f}"
                )
                doc_add_styled_table(doc, headers, data,
                                      highlight_col=0, highlight_val=highlight_value,
                                      with_full_border=True)
                add_candidate_diameters_to_word(doc, candidates)

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

        # 解析 Q 范围（从 SpinBox 读取）
        try:
            q_start = float(self.batch_q_start.text().strip())
            q_end   = float(self.batch_q_end.text().strip())
            q_step  = float(self.batch_q_step.text().strip())
            if not all(math.isfinite(value) for value in (q_start, q_end, q_step)) or q_start <= 0 or q_step <= 0 or q_start > q_end:
                raise ValueError("参数无效")
            import numpy as np
            q_values = np.round(np.arange(q_start, q_end + q_step * 0.5, q_step), 2)
        except (ValueError, TypeError):
            InfoBar.error(title="参数错误", content="Q范围参数无效，请检查起始/终止/步长",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return

        # 先检查完整自定义输入，不能悄悄使用有效子集。
        height_limit, area_limit = None, None
        if self.batch_unpr_cb.isChecked():
            try:
                slope_denoms = self.slope_controls.values()
                height_limit, area_limit = self.slope_controls.criteria()
                n_unpr = float(self.batch_n_edit.text().strip())
                if not math.isfinite(n_unpr) or n_unpr <= 0:
                    raise ValueError("无压糙率必须为正有限数")
            except ValueError as exc:
                InfoBar.error(title="无压对比参数错误", content=str(exc),
                              parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
                return
        else:
            slope_denoms, n_unpr = [], 0.0

        # 管长
        bl_text = self.batch_length_edit.text().strip()
        if not bl_text:
            InfoBar.error(title="参数错误", content="请输入管长 L",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return
        try:
            length_m = float(bl_text)
            if not math.isfinite(length_m) or length_m <= 0:
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
            if not math.isfinite(local_ratio) or local_ratio < 0:
                raise ValueError
        except ValueError:
            InfoBar.error(title="参数错误", content="局部损失比例输入无效",
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return

        pe_grade = self.batch_pe_grade_combo.currentText() or "PE100"
        pe_pn_mpa = self._selected_pe_pn(
            self.batch_pe_pn_combo, "_batch_pe_pn_options", default=1.0
        )
        try:
            get_pe_sdr(pe_grade, pe_pn_mpa)
        except ValueError as ex:
            InfoBar.error(title="PE 规格错误", content=str(ex),
                          parent=self, position=InfoBarPosition.TOP_RIGHT, duration=4000)
            return

        steel_kwargs = {}
        if '钢管' in selected_mats:
            try:
                steel_kwargs = parse_steel_state(self.batch_steel_controls.state(), batch=True)
            except ValueError as exc:
                InfoBar.error(title='钢管尺寸错误', content=str(exc), parent=self,
                              position=InfoBarPosition.TOP_RIGHT, duration=5000)
                return
        # 选择输出目录
        output_dir = QFileDialog.getExistingDirectory(self, "选择输出目录", "")
        if not output_dir:
            return

        config = BatchScanConfig(
            q_values=q_values,
            slope_denominators=slope_denoms,
            unpr_clearance_height=height_limit,
            unpr_clearance_area=area_limit,
            # None 表示由内核按管材选用目录；关闭产品目录时，非 PE 回退默认内径序列。
            diameter_values=None,
            materials=selected_mats,
            n_unpr=n_unpr,
            length_m=length_m,
            local_loss_ratio=local_ratio,
            output_dir=output_dir,
            output_csv=self.out_csv_cb.isChecked(),
            output_pdf_charts=self.out_pdf_cb.isChecked(),
            output_merged_pdf=self.out_merged_cb.isChecked(),
            output_subplot_png=self.out_png_cb.isChecked(),
            pe_material_grade=pe_grade,
            pe_nominal_pressure_mpa=pe_pn_mpa,
            use_product_catalogs=True,
            ductile_iron_class=self._selected_di_class(self.batch_di_class_combo),
            pccp_variant=self._selected_pccp_variant(self.batch_pccp_variant_combo),
            **steel_kwargs,
        )

        # 切换UI
        self.batch_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.batch_progress.setVisible(True)
        self.batch_progress.setValue(0)
        self.batch_status_label.setVisible(True)
        self.batch_status_label.setText("正在准备...")
        self.batch_log.clear()
        self._last_batch_log_message = ""
        self._append_batch_log_message("批量计算已启动，正在准备计算任务...")
        self._append_batch_log_message(
            f"流量 {len(q_values)} 个，坡度 {len(slope_denoms) if slope_denoms else 0} 个，"
            f"管材 {len(selected_mats)} 种；输出目录：{output_dir}"
        )
        if "HDPE管" in selected_mats:
            self._append_batch_log_message(
                f"PE 规格：{pe_grade}，PN{_fmt_g(pe_pn_mpa)} MPa（"
                f"SDR{_fmt_g(get_pe_sdr(pe_grade, pe_pn_mpa))}），{PE_STANDARD}"
            )
        selected_families = {
            get_catalog_family(key) for key in selected_mats if get_catalog_family(key)
        }
        if selected_families:
            details = []
            if "DI" in selected_families:
                details.append(
                    f"球墨铸铁管等级：{self.batch_di_class_combo.currentText()}"
                )
            if "PCCP" in selected_families:
                details.append(
                    f"PCCP={self._selected_pccp_variant(self.batch_pccp_variant_combo)}"
                )
            if "FRPM" in selected_families:
                details.append("玻璃钢夹砂管：标准内径")
            self._append_batch_log_message("管材规格：" + "，".join(details))
        self.notebook.setCurrentIndex(1)

        # 启动线程
        self._batch_comparison_inputs = self._comparison_input_state()
        self._batch_worker = _BatchWorker(config, self)
        self._batch_worker.progress.connect(self._on_batch_progress)
        self._batch_worker.finished.connect(self._on_batch_finished)
        self._batch_worker.error.connect(self._on_batch_error)
        self._batch_worker.start()

    def _cancel_batch(self):
        if self._batch_worker:
            self._batch_worker.cancel()
            self.batch_status_label.setText("正在取消...")
            self._append_batch_log_message("已请求取消，正在等待当前步骤结束...")

    def _append_batch_log_message(self, message):
        """向批量日志追加非重复消息，保证长任务运行中持续可见。"""
        text = str(message or "").strip()
        if not text or text == getattr(self, "_last_batch_log_message", ""):
            return
        self.batch_log.append(text)
        self._last_batch_log_message = text

    def _on_batch_progress(self, current, total, msg):
        if total > 0:
            self.batch_progress.setMaximum(total)
            self.batch_progress.setValue(current)
        self.batch_status_label.setText(msg)
        self._append_batch_log_message(msg)

    def _on_batch_finished(self, result: BatchScanResult):
        self.batch_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self.batch_progress.setVisible(False)
        self.batch_status_label.setText("完成")

        if any("用户取消" in log for log in result.logs):
            self.batch_status_label.setText("已取消")
            self._append_batch_log_message("批量计算已取消；保留上次完成的结果。")
            return
        self._comparison_rows = result.comparison_rows
        self._comparison_status = ''
        self._comparison_view_state = {}
        self.notebook.setCurrentIndex(1)
        if result.comparison_rows:
            if getattr(self, '_batch_comparison_inputs', None) != self._comparison_input_state():
                self._mark_comparison_stale()
        if result.comparison_csv_path:
            self._append_batch_log_message(f"无压对比明细: {result.comparison_csv_path}")

        for log in result.logs:
            self._append_batch_log_message(log)

        if result.csv_path:
            self._append_batch_log_message(f"CSV 路径: {result.csv_path}")
        if result.merged_pdf:
            self._append_batch_log_message(f"合并PDF: {result.merged_pdf}")
        for path in result.generated_pdfs:
            self._append_batch_log_message(f"图表 PDF: {path}")
        for path in result.generated_pngs:
            self._append_batch_log_message(f"子图 PNG: {path}")
        self._append_batch_log_message(
            f"批量计算完成：共生成 {len(result.generated_pdfs)} 个PDF，"
            f"{len(result.generated_pngs)} 个PNG。"
        )

        InfoBar.success(
            title="批量计算完成",
            content=f"已完成；生成 {len(result.generated_pdfs)} PDF、{len(result.generated_pngs)} PNG",
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

    @staticmethod
    def _dataclass_or_object_dict(obj):
        """把 dataclass 或普通对象转成 JSON 友好的字典。"""
        if obj is None:
            return {}
        if is_dataclass(obj):
            return PressurePipePanel._json_safe_value(asdict(obj))
        if isinstance(obj, dict):
            return PressurePipePanel._json_safe_value(obj)
        if hasattr(obj, "__dict__"):
            return PressurePipePanel._json_safe_value(vars(obj))
        return {}

    @staticmethod
    def _json_safe_value(value):
        """递归清理项目保存数据，避免 JSON 严格模式拒绝非有限浮点数。"""
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if is_dataclass(value):
            return PressurePipePanel._json_safe_value(asdict(value))
        if isinstance(value, dict):
            return {
                copy.deepcopy(key): PressurePipePanel._json_safe_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [PressurePipePanel._json_safe_value(item) for item in value]
        return copy.deepcopy(value)

    @staticmethod
    def _filter_dataclass_kwargs(cls, data):
        """只保留 dataclass 已声明字段，避免动态属性破坏重建。"""
        if not isinstance(data, dict):
            return {}
        names = {field.name for field in fields(cls)}
        return {key: copy.deepcopy(value) for key, value in data.items() if key in names}

    def _candidate_to_project_dict(self, candidate):
        """序列化一个管径候选结果。"""
        if candidate is None:
            return None
        return self._dataclass_or_object_dict(candidate)

    def _candidate_from_project_dict(self, data):
        """从项目数据恢复一个管径候选结果。"""
        if data is None:
            return None
        if not isinstance(data, dict):
            return data
        try:
            return DiameterCandidate(**self._filter_dataclass_kwargs(DiameterCandidate, data))
        except Exception:
            return SimpleNamespace(**copy.deepcopy(data))

    def _input_to_project_dict(self, inp):
        """序列化单个有压管道工况输入。"""
        data = self._dataclass_or_object_dict(inp)
        for key in ("inc_mode", "inc_pct_text", "inc_q_text", "use_increase"):
            if hasattr(inp, key):
                data[key] = copy.deepcopy(getattr(inp, key))
        return {
            "class": inp.__class__.__name__ if inp is not None else "",
            "data": data,
        }

    def _input_from_project_dict(self, payload):
        """从项目数据恢复工况输入对象。"""
        if not isinstance(payload, dict):
            return SimpleNamespace()
        data = copy.deepcopy(payload.get("data", {}) or {})
        class_name = payload.get("class", "")
        if class_name == "PressurePipeInput":
            try:
                inp = PressurePipeInput(**self._filter_dataclass_kwargs(PressurePipeInput, data))
            except Exception:
                inp = SimpleNamespace(**data)
        else:
            inp = SimpleNamespace(**data)
        for key in ("inc_mode", "inc_pct_text", "inc_q_text", "use_increase"):
            if key in data:
                setattr(inp, key, data[key])
        if not hasattr(inp, "use_increase"):
            inp.use_increase = True
        if not hasattr(inp, "inc_mode"):
            inp.inc_mode = INCREASE_MODE_PERCENT
        if not hasattr(inp, "inc_pct_text"):
            inp.inc_pct_text = ""
        if not hasattr(inp, "inc_q_text"):
            inp.inc_q_text = ""
        return inp

    def _result_to_project_dict(self, result):
        """序列化一个推荐结果或错误结果。"""
        if result is None:
            return None
        return {
            "class": result.__class__.__name__,
            "recommended": self._candidate_to_project_dict(getattr(result, "recommended", None)),
            "top_candidates": [
                self._candidate_to_project_dict(candidate)
                for candidate in (getattr(result, "top_candidates", []) or [])
            ],
            "category": getattr(result, "category", ""),
            "reason": getattr(result, "reason", ""),
            "calc_steps": getattr(result, "calc_steps", ""),
            "auto_recommended": self._candidate_to_project_dict(
                getattr(result, "auto_recommended", None)
            ),
        }

    def _result_from_project_dict(self, payload):
        """从项目数据恢复推荐结果或错误结果。"""
        if payload is None:
            return None
        if not isinstance(payload, dict):
            return payload
        recommended = self._candidate_from_project_dict(payload.get("recommended"))
        top_candidates = [
            candidate
            for candidate in (
                self._candidate_from_project_dict(item)
                for item in (payload.get("top_candidates", []) or [])
            )
            if candidate is not None
        ]
        auto_recommended = self._candidate_from_project_dict(payload.get("auto_recommended"))
        data = {
            "recommended": recommended,
            "top_candidates": top_candidates,
            "category": payload.get("category", ""),
            "reason": payload.get("reason", ""),
            "calc_steps": payload.get("calc_steps", ""),
            "auto_recommended": auto_recommended,
        }
        try:
            return RecommendationResult(**data)
        except Exception:
            return SimpleNamespace(**data)

    def _all_results_to_project_list(self):
        """序列化所有单项工况结果。"""
        items = []
        for case_idx, inp, result in self._all_results or []:
            try:
                idx = int(case_idx)
            except (TypeError, ValueError):
                idx = 0
            items.append({
                "case_idx": idx,
                "input": self._input_to_project_dict(inp),
                "result": self._result_to_project_dict(result),
            })
        return items

    def _all_results_from_project_list(self, payload):
        """从项目数据恢复所有单项工况结果。"""
        restored = []
        for item in payload or []:
            if not isinstance(item, dict):
                continue
            try:
                case_idx = int(item.get("case_idx", 0))
            except (TypeError, ValueError):
                case_idx = 0
            inp = self._input_from_project_dict(item.get("input"))
            result = self._result_from_project_dict(item.get("result"))
            if result is None:
                continue
            restored.append((case_idx, inp, result))
        return restored

    def _build_export_plain_text_from_results(self):
        """根据恢复出的结果重建 Word 导出纯文本。"""
        plain_text_parts = []
        for idx, inp, res in self._all_results or []:
            part_lines = [f"===== 工况{idx + 1} ====="]
            if getattr(res, "recommended", None) is not None:
                part_lines.extend(self._increase_summary_lines(inp, res))
                part_lines.append("")
            part_lines.append(getattr(res, "calc_steps", "") or getattr(res, "reason", ""))
            plain_text_parts.append("\n".join(part_lines))
        return "\n\n".join(plain_text_parts)

    # ================================================================
    # 项目保存/加载
    # ================================================================
    def _comparison_input_state(self):
        """提取影响批量结果的输入，用于保存和识别计算期间的编辑。"""
        return {
            'enabled': self.batch_unpr_cb.isChecked(), 'inputs': self.slope_controls.state(),
            'flow_range': [self.batch_q_start.text(), self.batch_q_end.text(), self.batch_q_step.text()],
            'length': self.batch_length_edit.text(), 'local_ratio': self.batch_local_ratio_edit.text(),
            'materials': [key for key, checkbox in self._mat_cbs.items() if checkbox.isChecked()],
            'pe_grade': self.batch_pe_grade_combo.currentText(), 'pe_pn': self.batch_pe_pn_combo.currentText(),
            'di_class': self.batch_di_class_combo.currentText(), 'pccp': self.batch_pccp_variant_combo.currentText(),
            'steel': self.batch_steel_controls.state(),
        }

    def _comparison_project_state(self):
        """保存无压输入与结果快照，兼容尚未构造批量区的调用者。"""
        if not hasattr(self, 'slope_controls'):
            return {}
        return {**self._comparison_input_state(), 'rows': getattr(self, '_comparison_rows', []),
                'status': getattr(self, '_comparison_status', ''),
                'view': getattr(self, '_comparison_view_state', {})}

    def to_project_dict(self):
        """序列化当前状态用于项目保存。"""
        self._save_current_case()
        return self._json_safe_value({
            'cases': copy.deepcopy(self._cases),
            'current_case_idx': int(self._current_case_idx),
            'last_errors': list(self._last_errors),
            'all_results': self._all_results_to_project_list(),
            'current_result': self._result_to_project_dict(self.current_result),
            'export_plain_text': self._export_plain_text,
            'result_state': collect_case_result_state(self),
            'notebook_idx': self.notebook.currentIndex() if hasattr(self, 'notebook') else 0,
            'steel_batch': self.batch_steel_controls.state() if hasattr(self, 'batch_steel_controls') else dict(STEEL_CASE_DEFAULTS),
            'unpressurized_comparison': self._comparison_project_state(),
        })

    def from_project_dict(self, data):
        """从项目数据恢复面板状态。"""
        if not isinstance(data, dict):
            return
        self.batch_steel_controls.set_state(data.get('steel_batch') or STEEL_CASE_DEFAULTS)
        comparison = data.get('unpressurized_comparison') or {}
        self.slope_controls.set_state(comparison.get('inputs'))
        self.batch_unpr_cb.setChecked(bool(comparison.get('enabled', False)))
        for edit, value in zip((self.batch_q_start, self.batch_q_end, self.batch_q_step), comparison.get('flow_range', [])):
            edit.setText(str(value))
        if 'length' in comparison:
            self.batch_length_edit.setText(str(comparison['length']))
        if 'local_ratio' in comparison:
            self.batch_local_ratio_edit.setText(str(comparison['local_ratio']))
        if 'materials' in comparison:
            for key, checkbox in self._mat_cbs.items():
                checkbox.setChecked(key in comparison['materials'])
        for key, combo in (('pe_grade', self.batch_pe_grade_combo), ('pe_pn', self.batch_pe_pn_combo),
                           ('di_class', self.batch_di_class_combo), ('pccp', self.batch_pccp_variant_combo)):
            if key in comparison:
                self._set_combo_text(combo, comparison[key])
        # 保留旧项目快照供兼容存档，不再构造已移除的结果页面。
        self._comparison_rows = copy.deepcopy(comparison.get('rows') or [])
        self._comparison_status = comparison.get('status') or ''
        self._comparison_view_state = copy.deepcopy(comparison.get('view') or {})
        cases = data.get('cases')
        if isinstance(cases, list) and cases:
            self._cases = [self._normalized_case_data(case) for case in cases]
        else:
            self._cases = [self._default_case()]

        idx = data.get('current_case_idx', 0)
        self._current_case_idx = idx if isinstance(idx, int) else 0
        if self._current_case_idx < 0 or self._current_case_idx >= len(self._cases):
            self._current_case_idx = 0

        self._all_results = self._all_results_from_project_list(data.get('all_results', []))
        self.current_result = None
        self._last_errors = list(data.get('last_errors', []) or [])
        self._load_case(self._current_case_idx)
        self._rebuild_case_tags()
        self._update_calc_btn_text()

        if self._all_results:
            result_state = data.get('result_state')
            restored_current = self._result_from_project_dict(data.get('current_result'))
            self.current_result = restored_current or self._all_results[0][2]
            self._export_plain_text = (
                data.get('export_plain_text')
                or self._build_export_plain_text_from_results()
            )
            try:
                self._suppress_project_restore_side_effects = True
                self._display_all_results()
            except Exception:
                self._all_results = []
                self.current_result = None
                self._export_plain_text = ""
                sync_case_result_nav_bar(getattr(self, "_result_case_nav", None), [])
                self._show_initial_help()
            finally:
                self._suppress_project_restore_side_effects = False
            if self._all_results:
                apply_case_result_state(self, result_state)
                # 历史钢管结果仍可查看，重算前不得误标成新的最小外径计算成果。
                old_steel_indexes = [index for index, inp, saved in self._all_results
                                     if inp.material_key == '钢管'
                                     and not getattr(saved.recommended, 'steel_sizing_trace', None)]
                if old_steel_indexes:
                    self._mark_results_dirty(case_indexes=old_steel_indexes)
            if hasattr(self, 'notebook'):
                tab_idx = data.get('notebook_idx')
                if isinstance(tab_idx, int):
                    tab_idx = max(0, min(tab_idx, self.notebook.count() - 1))
                    self.notebook.setCurrentIndex(tab_idx)
            return

        if self._last_errors:
            err_txt = "部分或全部工况计算失败：\n\n" + "\n".join(self._last_errors)
            self._export_plain_text = err_txt
            sync_case_result_nav_bar(getattr(self, "_result_case_nav", None), [])
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
