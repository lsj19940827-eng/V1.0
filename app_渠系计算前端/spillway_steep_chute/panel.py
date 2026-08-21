# -*- coding: utf-8 -*-
"""泄水渠与陡坡正式前端面板，负责多工况输入、计算、展示和导出。"""

import html
import os
import re
import sys
from inspect import Parameter, signature
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from qfluentwidgets import CheckBox, ComboBox, InfoBar, InfoBarPosition, LineEdit, PrimaryPushButton, PushButton
except Exception:  # pragma: no cover - 兼容轻量测试环境
    from PySide6.QtWidgets import QCheckBox as CheckBox
    from PySide6.QtWidgets import QComboBox as ComboBox
    from PySide6.QtWidgets import QLineEdit as LineEdit
    from PySide6.QtWidgets import QPushButton as PrimaryPushButton
    from PySide6.QtWidgets import QPushButton as PushButton

    InfoBar = None
    InfoBarPosition = None

import matplotlib

matplotlib.use("QtAgg")
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavToolbar
except ImportError:  # pragma: no cover - 兼容较旧 matplotlib
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavToolbar
from matplotlib.figure import Figure

from app_渠系计算前端.case_manager import CaseWorkbenchStrip, apply_design_input_sidebar_policy
from app_渠系计算前端.export_utils import ask_open_file
from app_渠系计算前端.formula_renderer import load_formula_page, render_latex_svg, wrap_with_katex
from app_渠系计算前端.result_navigation import CaseResultNavigationBar, build_result_navigation_head, sync_case_result_nav_bar
from app_渠系计算前端.report_meta import ExportConfirmDialog, build_calc_purpose, load_meta
from app_渠系计算前端.section_comparison import ComparisonColumn, fill_comparison_table
from app_渠系计算前端.section_plot_layout import (
    configure_section_grid_canvas,
    connect_section_tab_refresh,
    create_section_plot_scroll_area,
)
from app_渠系计算前端.styles import BD, INPUT_HINT_STYLE, INPUT_LABEL_STYLE, INPUT_SECTION_STYLE
from app_渠系计算前端.webview_compat import create_web_view, scroll_view_to_anchor
from app_渠系计算前端.increase_input_helper import (
    INCREASE_MODE_PERCENT,
    INCREASE_MODE_Q_INCREASED,
    build_increase_hint_text,
    resolve_increase_input,
)

from .comparison import build_comparison_rows
from .examples import teaching_example
from .models import normalize_result
from .plotting import draw_longitudinal_profile
from .principles import build_calculation_principles, build_precalculation_principles
from .report_export import (
    export_spillway_steep_chute_excel,
    export_spillway_steep_chute_word,
)

_ROOT = Path(__file__).resolve().parents[2]
_CALC_DIR = _ROOT / "calc_渠系计算算法内核"
if str(_CALC_DIR) not in sys.path:
    sys.path.insert(0, str(_CALC_DIR))


_ENGINEERING_SYMBOL_RE = re.compile(
    r"(?<![A-Za-z0-9_Α-Ωα-ω])([A-Za-zΑ-Ωα-ω]+)_([A-Za-z0-9\u4e00-\u9fffΔ]+)"
)

INLET_CONNECTION_TYPES = ["扭曲面连接", "八字墙连接", "横隔墙连接", "手动输入流量系数"]
DEFAULT_INLET_CONNECTION_TYPE = "扭曲面连接"
MANUAL_INLET_COEFFICIENT_LABEL = "手动输入流量系数"

PRINCIPLE_FLOW_OVERVIEW = {
    "基础断面与水力要素": {
        "first": "把底宽、边坡和试算水深转成面积、湿周、水力半径和水面宽。",
        "result": "得到统一的断面水力要素。",
        "next": "供正常水深、临界水深和沿程水面线反复调用。",
    },
    "正常水深": {
        "first": "用设计流量、糙率和实际底坡反算均匀流水深。",
        "result": "得到渠道自然稳定水深。",
        "next": "用于判断坡型，并作为陡坡水面线的趋近目标。",
    },
    "临界水深": {
        "first": "求断面比能最小时的分界水深。",
        "result": "得到急流和缓流的分界条件。",
        "next": "用于坡型判别，也常作为自由陡坡入口起算水深。",
    },
    "坡型判别": {
        "first": "把实际底坡和临界底坡进行比较。",
        "result": "判断本工况是陡坡、缓坡还是临界坡。",
        "next": "决定后续水面线是否按陡槽降水曲线理解。",
    },
    "起点控制水深": {
        "first": "确定陡槽水面线从哪个水深开始算。",
        "result": "得到起点控制水深。",
        "next": "作为逐段推求水面线的第一个断面。",
    },
    "入口过流能力": {
        "first": "按入口连接形式和堰上总水头校核入口能否过流。",
        "result": "得到入口过流能力和能力比。",
        "next": "判断瓶颈是否出现在入口，而不是陡槽本身。",
    },
    "水面线逐段计算": {
        "first": "从起点水深沿陡槽逐段推算水深、水位、流速和流态。",
        "result": "得到沿程水面线和末端急流水深。",
        "next": "给纵断面图、掺气侧墙和出口水跃提供基础。",
    },
    "掺气水深与侧墙高度": {
        "first": "根据沿程高速水流估算掺气后的水深增量。",
        "result": "得到最大掺气水深和建议侧墙高度。",
        "next": "用于判断陡槽边墙是否有足够安全高度。",
    },
    "水跃与消力池": {
        "first": "用陡槽末端跃前水深和弗劳德数计算跃后水深。",
        "result": "得到消力池池长、池深和尾水判断。",
        "next": "用于确定下游消能和防冲是否需要加强。",
    },
    "出口整流段": {
        "first": "按出口扩散、跃后水深倍数和最小长度共同控制。",
        "result": "得到出口连接段建议长度。",
        "next": "用于让消能后的水流更平顺地接入下游。",
    },
    "规范校核与风险提示": {
        "first": "汇总入口、坡型、流速、尾水和布置等校核结果。",
        "result": "得到通过项、风险项和需要人工复核的提示。",
        "next": "作为最终采用前的检查清单。",
    },
}


def render_principle_inline_html(text: Any) -> str:
    """渲染计算原理段落文字，把工程符号下标转为安全 HTML。"""
    escaped = html.escape(str(text or ""))

    def _replace(match: re.Match[str]) -> str:
        symbol = match.group(1)
        subscript = match.group(2)
        return f"{symbol}<sub>{subscript}</sub>"

    return _ENGINEERING_SYMBOL_RE.sub(_replace, escaped)


def render_principle_flow_overview_html(principles: list[dict[str, str]]) -> str:
    """生成计算原理顶部 11 步路线图 HTML。"""
    items: list[str] = []
    for idx, item in enumerate(principles, start=1):
        step = str(item.get("step") or f"步骤{idx}")
        overview = PRINCIPLE_FLOW_OVERVIEW.get(step, {})
        first = overview.get("first") or str(item.get("purpose") or "")
        result = overview.get("result") or str(item.get("result") or "")
        next_use = overview.get("next") or "进入下一步计算。"
        items.append(
            "<div class='principle-flow-card'>"
            f"<div class='principle-flow-index'>{idx}</div>"
            f"<div class='principle-flow-name'>{html.escape(step)}</div>"
            f"<p><strong>先算：</strong>{html.escape(first)}</p>"
            f"<p><strong>得到：</strong>{html.escape(result)}</p>"
            f"<p><strong>用于下一步：</strong>{html.escape(next_use)}</p>"
            "</div>"
        )
    return (
        "<section class='principle-flow'>"
        "<h3>计算流程总览</h3>"
        "<p class='principle-flow-intro'>先按下面顺序看完整流程，再往下查看每一步公式和本次代入。</p>"
        f"<div class='principle-flow-grid'>{''.join(items)}</div>"
        "</section>"
    )


try:
    from 泄水渠与陡坡设计 import quick_calculate_spillway_steep_chute
except ImportError:  # pragma: no cover - 合并前给出明确错误

    def quick_calculate_spillway_steep_chute(**_params):
        """在算法内核尚未合并时给出明确错误。"""
        raise ImportError("未找到 calc_渠系计算算法内核/泄水渠与陡坡设计.py")


_HYDRAULIC_COLUMNS = (
    ComparisonColumn("case", "工况", "", None),
    ComparisonColumn("flow", "流量", "立方米/秒", 3),
    ComparisonColumn("profile_type", "水面线型", "", None),
    ComparisonColumn("end_depth", "末端水深", "米", 3),
    ComparisonColumn("max_velocity", "最大流速", "米/秒", 3),
    ComparisonColumn("max_froude", "最大弗劳德数", "", 3),
    ComparisonColumn("jump_depth", "跃后水深", "米", 3),
)

_LAYOUT_COLUMNS = (
    ComparisonColumn("case", "工况", "", None),
    ComparisonColumn("sidewall_height", "建议侧墙高度", "米", 3),
    ComparisonColumn("pool_length", "建议消力池长度", "米", 3),
    ComparisonColumn("pool_depth", "建议消力池深度", "米", 3),
    ComparisonColumn("tailwater", "尾水判断", "", None),
    ComparisonColumn("status", "状态", "", None),
)


class SpillwaySteepChutePanel(QWidget):
    """泄水渠与陡坡计算面板。"""

    data_changed = Signal()

    def __init__(self, parent=None):
        """初始化面板状态和界面。"""
        super().__init__(parent)
        self._panel_key = "spillway_steep_chute"
        self._cases: list[dict[str, Any]] = [self._default_case()]
        self._current_case_idx = 0
        self._all_results: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
        self.input_params: dict[str, Any] = {}
        self.current_result: dict[str, Any] | None = None
        self._input_fields: dict[str, LineEdit] = {}
        self._combo_fields: dict[str, ComboBox] = {}
        self._check_fields: dict[str, CheckBox] = {}
        self._input_rows: dict[str, list[QWidget]] = {}
        self._combo_rows: dict[str, list[QWidget]] = {}
        self._check_rows: dict[str, list[QWidget]] = {}
        self._suppress_case_save = False
        self._build_ui()
        self._load_case(0)
        self._refresh_case_strip()
        self._show_initial_help()

    @staticmethod
    def _default_case() -> dict[str, Any]:
        """返回默认计算工况。"""
        return {
            "custom_label": None,
            "project_name": "未命名工程",
            "ui_mode_label": "新手模式",
            "section_type": "梯形",
            "design_flow": 20.0,
            "channel_width": 1.0,
            "side_slope": 1.5,
            "chute_length": 80.0,
            "slope_input_mode_label": "直接输入底坡",
            "bed_drop": "",
            "bed_slope": 0.02,
            "roughness": 0.014,
            "start_bed_elevation": 100.0,
            "start_station": 0.0,
            "profile_mode_label": "已知长度求末端水深",
            "end_depth": "",
            "alpha_profile": 1.1,
            "control_depth_mode_label": "取临界水深",
            "manual_start_depth": "",
            "inlet_weir_width": 1.0,
            "inlet_head": 2.2,
            "inlet_connection_type_label": DEFAULT_INLET_CONNECTION_TYPE,
            "weir_coefficient": "",
            "contraction_coefficient": 1.0,
            "upstream_normal_depth": "",
            "downstream_tailwater_depth": "",
            "material_allow_velocity": "",
            "downstream_channel_width": "",
            "outlet_transition_angle_deg": 12.0,
            "outlet_rectification_factor": 10.0,
            "sidewall_freeboard_m": 0.4,
            "aeration_coefficient": 1.2,
            "pool_depth_factor": 1.10,
            "flow_cases_text": "",
            "use_increase": True,
            "inc_mode": INCREASE_MODE_PERCENT,
            "inc_pct_text": "",
            "inc_q_text": "",
            "increase_percent": "",
            "increase_flow": "",
            "detail_enabled": True,
        }

    @staticmethod
    def _normalize_case_increase_fields(case: dict[str, Any]) -> dict[str, Any]:
        """兼容旧工程的加大流量字段，并补齐新输入模式字段。"""
        has_explicit_mode = case.get("inc_mode") not in (None, "")
        if not case.get("inc_pct_text") and case.get("increase_percent") not in (None, ""):
            case["inc_pct_text"] = str(case.get("increase_percent"))
        if not case.get("inc_q_text") and case.get("increase_flow") not in (None, ""):
            case["inc_q_text"] = str(case.get("increase_flow"))
        if not has_explicit_mode:
            case["inc_mode"] = INCREASE_MODE_Q_INCREASED if case.get("inc_q_text") not in (None, "") else INCREASE_MODE_PERCENT
        if "increase_percent" not in case:
            case["increase_percent"] = case.get("inc_pct_text", "")
        if "increase_flow" not in case:
            case["increase_flow"] = case.get("inc_q_text", "")
        return case

    @staticmethod
    def _normalize_inlet_connection_label(value: Any) -> str:
        """兼容旧工程的入口连接形式字段。"""
        text = str(value or "").strip()
        if not text:
            return DEFAULT_INLET_CONNECTION_TYPE
        mapping = {
            "warped_surface": "扭曲面连接",
            "warped": "扭曲面连接",
            "扭曲面": "扭曲面连接",
            "扭曲面连接": "扭曲面连接",
            "splay_wall": "八字墙连接",
            "splayed_wall": "八字墙连接",
            "wing_wall": "八字墙连接",
            "八字墙": "八字墙连接",
            "八字墙连接": "八字墙连接",
            "diaphragm_wall": "横隔墙连接",
            "cross_wall": "横隔墙连接",
            "横隔墙": "横隔墙连接",
            "横隔墙连接": "横隔墙连接",
            "manual": MANUAL_INLET_COEFFICIENT_LABEL,
            "manual_coefficient": MANUAL_INLET_COEFFICIENT_LABEL,
            "人工流量系数": MANUAL_INLET_COEFFICIENT_LABEL,
            "手动输入流量系数": MANUAL_INLET_COEFFICIENT_LABEL,
        }
        return mapping.get(text.lower(), mapping.get(text, DEFAULT_INLET_CONNECTION_TYPE))

    @classmethod
    def _normalize_case_fields(cls, case: dict[str, Any]) -> dict[str, Any]:
        """统一兼容旧工程字段，避免旧隐藏默认值继续影响计算。"""
        cls._normalize_case_increase_fields(case)
        alpha_candidates = ("alpha_profile", "profile_energy_alpha", "alpha_e")
        alpha_value = next((case.get(key) for key in alpha_candidates if case.get(key) not in (None, "")), "")
        if alpha_value in (None, ""):
            case["alpha_profile"] = 1.1
            case["legacy_alpha_profile_migrated"] = True
        else:
            case["alpha_profile"] = alpha_value
            case["legacy_alpha_profile_migrated"] = False
        has_connection = case.get("inlet_connection_type_label") not in (None, "") or case.get("inlet_connection_type") not in (None, "")
        raw_connection = case.get("inlet_connection_type_label") or case.get("inlet_connection_type")
        manual_coefficient = case.get("weir_coefficient")
        legacy_manual_coefficient = case.get("inlet_discharge_coefficient") or case.get("mu")
        has_manual_coefficient = manual_coefficient not in (None, "") or legacy_manual_coefficient not in (None, "")
        if not has_connection and has_manual_coefficient:
            case["inlet_connection_type_label"] = MANUAL_INLET_COEFFICIENT_LABEL
            case["weir_coefficient"] = manual_coefficient if manual_coefficient not in (None, "") else legacy_manual_coefficient
            case["legacy_inlet_coefficient_migrated"] = False
        else:
            case["inlet_connection_type_label"] = cls._normalize_inlet_connection_label(raw_connection)
        if not has_connection and not has_manual_coefficient:
            case["legacy_inlet_coefficient_migrated"] = True
            case["weir_coefficient"] = ""
        case.setdefault("contraction_coefficient", 1.0)
        return case

    def _build_ui(self) -> None:
        """构建左右布局。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter)

        input_scroll = QScrollArea()
        input_scroll.setWidgetResizable(True)
        input_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        input_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        input_container = QWidget()
        self._build_inputs(input_container)
        input_scroll.setWidget(input_container)
        splitter.addWidget(input_scroll)

        output_container = QWidget()
        self._build_outputs(output_container)
        splitter.addWidget(output_container)
        apply_design_input_sidebar_policy(input_scroll, splitter)

    def _build_inputs(self, container: QWidget) -> None:
        """构建输入区。"""
        layout = QVBoxLayout(container)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(6)

        title = QLabel("输入参数")
        title.setStyleSheet("font-size:18px;font-weight:700;color:#0E5DB8;padding:0 2px 2px 2px;")
        layout.addWidget(title)

        self._case_strip = CaseWorkbenchStrip(container)
        self._case_strip.add_requested.connect(self._add_case)
        self._case_strip.case_switched.connect(self._switch_case)
        self._case_strip.case_renamed.connect(self._rename_case)
        self._case_strip.apply_to_all_requested.connect(self._apply_to_all_cases)
        self._case_strip.copy_from_prev_requested.connect(self._copy_from_prev_case)
        self._case_strip.remove_current_requested.connect(self._remove_current_case)
        layout.addWidget(self._case_strip)

        group = QGroupBox("输入参数")
        self._input_group = group
        group.setTitle("")
        form = QVBoxLayout(group)
        form.setSpacing(5)

        form.addWidget(self._slbl("【基础信息】"))
        self._combo(form, "ui_mode_label", "界面模式", ["新手模式", "专业模式"])
        self._field(form, "project_name", "工程名称", "未命名工程")
        self._combo(form, "section_type", "断面形式", ["梯形", "矩形"])
        self._field(form, "design_flow", "设计流量（立方米每秒）", "20.0")
        self._input_fields["design_flow"].textChanged.connect(self._refresh_increase_hint)
        self.use_increase_cb = self._check(form, "use_increase", "考虑加大流量")
        self.inc_cb = self.use_increase_cb
        self.use_increase_cb.stateChanged.connect(self._on_inc_toggle)
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
        form.addWidget(self.inc_mode_row)
        self._field(form, "increase_percent", "流量加大比例（百分比）", "")
        self._field(form, "increase_flow", "加大流量 Q加大（立方米每秒）", "")
        self.inc_lbl, self.inc_edit = self._input_rows["increase_percent"]
        self.inc_q_lbl, self.inc_q_edit = self._input_rows["increase_flow"]
        self.inc_edit.textChanged.connect(self._refresh_increase_hint)
        self.inc_q_edit.textChanged.connect(self._refresh_increase_hint)
        self.inc_hint = self._hint("")
        self.inc_derived_hint = self.inc_hint
        form.addWidget(self.inc_hint)
        self.auto_flow_hint = self._hint("依据规范，程序会对下泄流量自动分级进行水跃计算；先按设计流量的 10% 到 100% 初筛，再对控制区间按 1% 自动加密，加大流量会自动参与比较。")
        form.addWidget(self.auto_flow_hint)
        self._field(form, "flow_cases_text", "分级流量列表", "")

        form.addWidget(self._sep())
        form.addWidget(self._slbl("【陡槽几何】"))
        self._field(form, "channel_width", "渠底宽（米）", "1.0")
        self._field(form, "side_slope", "边坡系数", "1.5")
        self._field(form, "chute_length", "陡槽长度（米）", "80.0")
        self._combo(form, "slope_input_mode_label", "底坡输入方式", ["直接输入底坡", "按落差和长度计算"])
        self._field(form, "bed_drop", "渠底落差（米）", "")
        self._field(form, "bed_slope", "底坡", "0.02")
        self._field(form, "roughness", "糙率", "0.014")
        self._field(form, "start_bed_elevation", "起点渠底高程（米）", "100.0")
        self._field(form, "start_station", "起点桩号（米）", "0.0")
        self._combo(form, "profile_mode_label", "水面线模式", ["已知长度求末端水深", "已知两端水深求长度", "推至正常水深附近"])
        self._field(form, "end_depth", "目标末端水深（米）", "")
        self._field(form, "alpha_profile", "水面线动能修正系数", "1.1")

        form.addWidget(self._sep())
        form.addWidget(self._slbl("【上下游衔接】"))
        self._combo(form, "control_depth_mode_label", "起点控制水深", ["取临界水深", "人工指定", "进口控制", "模型试验"])
        self._field(form, "manual_start_depth", "控制水深（米）", "")
        self._field(form, "upstream_normal_depth", "上游正常水深（米）", "")
        self._field(form, "downstream_tailwater_depth", "下游尾水深（米）", "")
        self._field(form, "material_allow_velocity", "材料允许流速（米每秒）", "")

        form.addWidget(self._sep())
        form.addWidget(self._slbl("【进口、掺气与消能】"))
        self._field(form, "inlet_weir_width", "入口宽度（米）", "1.0")
        self._field(form, "inlet_head", "堰上总水头（米）", "2.2")
        self._combo(form, "inlet_connection_type_label", "入口连接形式", INLET_CONNECTION_TYPES)
        self._field(form, "weir_coefficient", "流量系数", "")
        self.inlet_coeff_hint = self._hint("侧收缩系数 ε 默认按 1.0 取值，表示无明显边界收缩或未另行折减。")
        form.addWidget(self.inlet_coeff_hint)
        self._field(form, "aeration_coefficient", "掺气系数", "1.2")
        self._field(form, "sidewall_freeboard_m", "侧墙安全超高（米）", "0.4")
        self._field(form, "pool_depth_factor", "池深安全系数", "1.10")
        self._field(form, "downstream_channel_width", "下游渠宽（米）", "")
        self._field(form, "outlet_transition_angle_deg", "出口渐变角（度）", "12.0")
        self._field(form, "outlet_rectification_factor", "整流长度系数", "10.0")

        form.addWidget(self._sep())
        self.detail_cb = self._check(form, "detail_enabled", "输出详细计算过程")

        button_row = QHBoxLayout()
        self.load_example_btn = PushButton("载入教学算例")
        self.clear_btn = PushButton("清空")
        self.calculate_btn = PrimaryPushButton("计算")
        self.load_example_btn.clicked.connect(self.load_teaching_example)
        self.clear_btn.clicked.connect(self._clear)
        self.calculate_btn.clicked.connect(self.calculate)
        button_row.addWidget(self.load_example_btn)
        button_row.addWidget(self.clear_btn)
        button_row.addWidget(self.calculate_btn)
        form.addLayout(button_row)

        export_row = QHBoxLayout()
        self.export_word_btn = PushButton("导出计算书")
        self.export_excel_btn = PushButton("导出表格")
        self.export_word_btn.clicked.connect(self.export_word)
        self.export_excel_btn.clicked.connect(self.export_excel)
        export_row.addWidget(self.export_word_btn)
        export_row.addWidget(self.export_excel_btn)
        form.addLayout(export_row)

        layout.addWidget(group)
        layout.addStretch(1)

    def _build_outputs(self, container: QWidget) -> None:
        """构建输出页签。"""
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.notebook = QTabWidget()
        layout.addWidget(self.notebook)

        principle_page = QWidget()
        principle_layout = QVBoxLayout(principle_page)
        self.principle_view = create_web_view()
        self.formula_view = self.principle_view
        principle_layout.addWidget(self.principle_view)
        self.notebook.addTab(principle_page, "计算原理")

        result_page = QWidget()
        result_layout = QVBoxLayout(result_page)
        result_layout.setContentsMargins(5, 5, 5, 5)
        result_group = QFrame()
        result_group_layout = QVBoxLayout(result_group)
        self._result_case_nav = CaseResultNavigationBar(result_group)
        self._result_case_nav.case_requested.connect(self._jump_to_case_result)
        result_group_layout.addWidget(self._result_case_nav)
        self.result_text = create_web_view()
        result_group_layout.addWidget(self.result_text)
        result_layout.addWidget(result_group)
        self.notebook.addTab(result_page, "结果汇总")

        profile_page = QWidget()
        profile_layout = QVBoxLayout(profile_page)
        self.profile_table = QTableWidget(0, 8)
        self.profile_table.setHorizontalHeaderLabels(["桩号", "渠底高程", "水深", "水位", "流速", "弗劳德数", "掺气水深", "侧墙顶高程"])
        self.profile_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        profile_layout.addWidget(self.profile_table)
        self.notebook.addTab(profile_page, "沿程水面线")

        figure_page = QWidget()
        figure_layout = QVBoxLayout(figure_page)
        self.profile_fig = Figure(figsize=(8, 5.4), dpi=100)
        self.section_fig = self.profile_fig
        self.profile_canvas = FigureCanvas(self.profile_fig)
        self.section_canvas = self.profile_canvas
        self.section_toolbar = NavToolbar(self.profile_canvas, figure_page)
        figure_layout.addWidget(self.section_toolbar)
        self._section_plot_scroll = create_section_plot_scroll_area(self.profile_canvas)
        figure_layout.addWidget(self._section_plot_scroll)
        figure_tab_index = self.notebook.addTab(figure_page, "纵断面图")
        connect_section_tab_refresh(self, figure_tab_index)

        check_page = QWidget()
        check_layout = QVBoxLayout(check_page)
        self.check_table = QTableWidget(0, 3)
        self.check_table.setHorizontalHeaderLabels(["项目", "结论", "说明"])
        self.check_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        check_layout.addWidget(self.check_table)
        self.notebook.addTab(check_page, "规范校核")

        comparison_page = QWidget()
        comparison_layout = QVBoxLayout(comparison_page)
        self.comparison_hint = QLabel("请先完成计算，系统会在这里汇总各工况的水面线、消能和布置结果。")
        self.comparison_hint.setWordWrap(True)
        self.comparison_hint.setStyleSheet("color:#666; font-size:12px;")
        comparison_layout.addWidget(self.comparison_hint)
        comparison_layout.addWidget(QLabel("水力结果对比表"))
        self.comparison_hydraulic_table = QTableWidget(0, len(_HYDRAULIC_COLUMNS))
        self._configure_table(self.comparison_hydraulic_table)
        fill_comparison_table(self.comparison_hydraulic_table, _HYDRAULIC_COLUMNS, [])
        comparison_layout.addWidget(self.comparison_hydraulic_table)
        comparison_layout.addWidget(QLabel("布置与消能对比表"))
        self.comparison_layout_table = QTableWidget(0, len(_LAYOUT_COLUMNS))
        self._configure_table(self.comparison_layout_table)
        fill_comparison_table(self.comparison_layout_table, _LAYOUT_COLUMNS, [])
        comparison_layout.addWidget(self.comparison_layout_table)
        self.comparison_table = self.comparison_hydraulic_table
        self.notebook.addTab(comparison_page, "工况对比")

        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.hide()
        layout.addWidget(self.summary_text)

    def _field(self, layout: QVBoxLayout, key: str, label: str, default: str = "") -> LineEdit:
        """添加一行输入框。"""
        row = QHBoxLayout()
        text_label = QLabel(label)
        text_label.setMinimumWidth(150)
        text_label.setStyleSheet(INPUT_LABEL_STYLE)
        row.addWidget(text_label)
        edit = LineEdit()
        edit.setText(default)
        edit.textChanged.connect(self._on_input_changed)
        row.addWidget(edit, 1)
        layout.addLayout(row)
        self._input_fields[key] = edit
        self._input_rows[key] = [text_label, edit]
        return edit

    def _combo(self, layout: QVBoxLayout, key: str, label: str, items: list[str]) -> ComboBox:
        """添加一行下拉框。"""
        row = QHBoxLayout()
        text_label = QLabel(label)
        text_label.setMinimumWidth(150)
        text_label.setStyleSheet(INPUT_LABEL_STYLE)
        row.addWidget(text_label)
        combo = ComboBox()
        combo.addItems(items)
        combo.currentTextChanged.connect(lambda _text: self._on_input_changed())
        if key in {"ui_mode_label", "inlet_connection_type_label"}:
            combo.currentTextChanged.connect(lambda _text: self._apply_mode_visibility())
        row.addWidget(combo, 1)
        layout.addLayout(row)
        self._combo_fields[key] = combo
        self._combo_rows[key] = [text_label, combo]
        return combo

    def _check(self, layout: QVBoxLayout, key: str, text: str) -> CheckBox:
        """添加复选框。"""
        check = CheckBox(text)
        check.setChecked(True)
        check.stateChanged.connect(lambda _state: self._on_input_changed())
        layout.addWidget(check)
        self._check_fields[key] = check
        self._check_rows[key] = [check]
        return check

    def _slbl(self, text: str) -> QLabel:
        """生成输入分组标题。"""
        label = QLabel(text)
        label.setStyleSheet(INPUT_SECTION_STYLE)
        return label

    def _hint(self, text: str) -> QLabel:
        """生成输入说明。"""
        label = QLabel(text)
        label.setStyleSheet(INPUT_HINT_STYLE)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        return label

    def _current_increase_mode(self) -> str:
        """读取当前加大流量输入方式。"""
        return INCREASE_MODE_Q_INCREASED if self.inc_mode_q_rb.isChecked() else INCREASE_MODE_PERCENT

    def _set_increase_mode(self, mode: Any) -> None:
        """设置加大流量输入方式，旧数据默认按比例。"""
        if mode == INCREASE_MODE_Q_INCREASED:
            self.inc_mode_q_rb.setChecked(True)
        else:
            self.inc_mode_percent_rb.setChecked(True)
        self._on_inc_toggle(None)

    def _on_inc_mode_changed(self, checked: bool) -> None:
        """切换加大流量输入方式后刷新显隐与缓存。"""
        self._on_inc_toggle(None)
        if checked and not self._suppress_case_save:
            self._on_input_changed()

    def _on_inc_toggle(self, _state: Any) -> None:
        """根据加大流量开关和输入方式显示对应控件。"""
        enabled = self.use_increase_cb.isChecked()
        is_percent_mode = self._current_increase_mode() == INCREASE_MODE_PERCENT
        self.inc_mode_row.setVisible(enabled)
        self.inc_lbl.setVisible(enabled and is_percent_mode)
        self.inc_edit.setVisible(enabled and is_percent_mode)
        self.inc_q_lbl.setVisible(enabled and not is_percent_mode)
        self.inc_q_edit.setVisible(enabled and not is_percent_mode)
        self.inc_hint.setVisible(enabled)
        self._refresh_increase_hint()

    def _refresh_increase_hint(self) -> None:
        """刷新加大流量输入提示。"""
        if not hasattr(self, "inc_hint"):
            return
        self.inc_hint.setText(
            build_increase_hint_text(
                use_increase=self.use_increase_cb.isChecked(),
                mode=self._current_increase_mode(),
                design_q_text=self._input_fields["design_flow"].text(),
                percent_text=self.inc_edit.text(),
                q_increased_text=self.inc_q_edit.text(),
            )
        )

    def _sep(self) -> QFrame:
        """生成分隔线。"""
        frame = QFrame()
        frame.setFrameShape(QFrame.HLine)
        frame.setStyleSheet(f"color:{BD};")
        return frame

    def _configure_table(self, table: QTableWidget) -> None:
        """设置表格通用交互样式。"""
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def _set_row_visible(self, key: str, visible: bool) -> None:
        """按输入键隐藏或显示一行控件。"""
        widgets = self._input_rows.get(key) or self._combo_rows.get(key) or self._check_rows.get(key) or []
        for widget in widgets:
            widget.setVisible(visible)

    def _apply_mode_visibility(self) -> None:
        """根据新手/专业模式调整高级参数显隐。"""
        mode_widget = self._combo_fields.get("ui_mode_label")
        if mode_widget is None:
            return
        professional = mode_widget.currentText() == "专业模式"
        advanced_keys = {
            "flow_cases_text",
            "slope_input_mode_label",
            "bed_drop",
            "start_station",
            "profile_mode_label",
            "end_depth",
            "control_depth_mode_label",
            "manual_start_depth",
            "alpha_profile",
            "upstream_normal_depth",
            "material_allow_velocity",
            "downstream_channel_width",
            "outlet_transition_angle_deg",
            "outlet_rectification_factor",
            "pool_depth_factor",
        }
        for key in advanced_keys:
            self._set_row_visible(key, professional)
        self._set_row_visible("flow_cases_text", False)
        inlet_connection = self._combo_fields.get("inlet_connection_type_label")
        manual_coeff = (
            professional
            and inlet_connection is not None
            and inlet_connection.currentText() == MANUAL_INLET_COEFFICIENT_LABEL
        )
        self._set_row_visible("weir_coefficient", manual_coeff)
        self._on_inc_toggle(None)

    def _on_input_changed(self, *_args) -> None:
        """输入变化后更新工况缓存。"""
        if self._suppress_case_save:
            return
        self._save_current_case()
        self._clear_results_after_input_change()
        self.data_changed.emit()

    def _clear_results_after_input_change(self) -> None:
        """参数变化后清空旧结果，避免导出或保存过期成果。"""
        if not self._all_results and self.current_result is None and not self.input_params:
            self._refresh_principle_page()
            return
        self._all_results = []
        self.input_params = {}
        self.current_result = None
        self.summary_text.setPlainText("参数已变更，请重新计算。")
        sync_case_result_nav_bar(self._result_case_nav, [])
        self._fill_table(self.profile_table, [])
        self._fill_table(self.check_table, [])
        load_formula_page(self.result_text, wrap_with_katex(self._stale_body(), extra_css=self._result_css(), extra_head=build_result_navigation_head()))
        self._refresh_principle_page()
        self._refresh_plot()
        self._refresh_comparison_tables()

    def _float_or_empty(self, key: str) -> float | str:
        """读取输入框中的数字，空值保持为空。"""
        text = self._input_fields[key].text().strip()
        if text == "":
            return ""
        return float(text)

    def _collect_inputs(self) -> dict[str, Any]:
        """读取并校验当前输入。"""
        params: dict[str, Any] = {}
        for key, field in self._input_fields.items():
            text = field.text().strip()
            if key == "project_name":
                params[key] = text
            elif key == "flow_cases_text":
                params[key] = ""
            elif text == "":
                params[key] = ""
            else:
                try:
                    params[key] = float(text)
                except ValueError as exc:
                    raise ValueError(f"{field.objectName() or key} 输入无效") from exc
        for key, combo in self._combo_fields.items():
            params[key] = combo.currentText()
        for key, check in self._check_fields.items():
            params[key] = check.isChecked()
        params["inc_mode"] = self._current_increase_mode()
        params["inc_pct_text"] = self.inc_edit.text().strip()
        params["inc_q_text"] = self.inc_q_edit.text().strip()

        section_type = "rectangular" if params.get("section_type") == "矩形" else "trapezoidal"
        profile_mode_map = {
            "已知长度求末端水深": "END_DEPTH_BY_LENGTH",
            "已知两端水深求长度": "LENGTH_BY_TWO_DEPTHS",
            "推至正常水深附近": "FULL_CURVE_TO_NORMAL",
        }
        control_mode_map = {
            "取临界水深": "critical_depth",
            "人工指定": "manual",
            "进口控制": "inlet_control",
            "模型试验": "model_test",
        }
        design_flow = float(params.get("design_flow") or 0.0)
        chute_length = float(params.get("chute_length") or 0.0)
        bed_slope = float(params.get("bed_slope") or 0.0)
        if params.get("slope_input_mode_label") == "按落差和长度计算":
            bed_drop = float(params.get("bed_drop") or 0.0)
            if chute_length <= 0 or bed_drop <= 0:
                raise ValueError("按落差和长度计算底坡时，陡槽长度和渠底落差必须大于 0")
            bed_slope = bed_drop / chute_length
        use_increase = bool(params.get("use_increase"))
        increase_resolution = resolve_increase_input(
            use_increase=use_increase,
            mode=params.get("inc_mode", INCREASE_MODE_PERCENT),
            design_q=design_flow,
            percent_text=params.get("inc_pct_text", ""),
            q_increased_text=params.get("inc_q_text", ""),
            disabled_percent=0.0,
        )
        q_increased = increase_resolution.q_increased_value
        flow_cases = self._build_auto_flow_cases(design_flow, q_increased if use_increase else None)

        control_label = params.get("control_depth_mode_label")
        control_depth_value = params.get("manual_start_depth")
        start_depth_value: float | str = ""
        manual_start_depth: float | str = ""
        inlet_control_depth: float | str = ""
        model_test_start_depth: float | str = ""
        if control_label != "取临界水深" and control_depth_value not in ("", None):
            start_depth_value = float(control_depth_value)
            if control_label == "进口控制":
                inlet_control_depth = start_depth_value
            elif control_label == "模型试验":
                model_test_start_depth = start_depth_value
            else:
                manual_start_depth = start_depth_value

        inlet_connection = self._normalize_inlet_connection_label(params.get("inlet_connection_type_label"))
        manual_weir_coefficient: float | str = ""
        if inlet_connection == MANUAL_INLET_COEFFICIENT_LABEL:
            manual_weir_coefficient = params.get("weir_coefficient", "")
            if manual_weir_coefficient in ("", None):
                raise ValueError("手动输入流量系数不能为空")

        params.update(
            {
                "custom_label": self._case_label(self._cases[self._current_case_idx], self._current_case_idx),
                "structure_name": params.get("project_name") or "泄水渠与陡坡",
                "section_type": section_type,
                "Q": design_flow,
                "b": float(params.get("channel_width") or 0.0),
                "m": 0.0 if section_type == "rectangular" else float(params.get("side_slope") or 0.0),
                "L": chute_length,
                "i": bed_slope,
                "n": float(params.get("roughness") or 0.0),
                "profile_mode": profile_mode_map.get(params.get("profile_mode_label"), "END_DEPTH_BY_LENGTH"),
                "control_depth_mode": control_mode_map.get(params.get("control_depth_mode_label"), "critical_depth"),
                "inlet_connection_type": inlet_connection,
                "weir_coefficient": manual_weir_coefficient,
                "contraction_coefficient": float(params.get("contraction_coefficient") or 1.0),
                "alpha_profile": float(params.get("alpha_profile") or 1.1),
                "legacy_inlet_coefficient_migrated": bool(
                    self._cases[self._current_case_idx].get("legacy_inlet_coefficient_migrated")
                ),
                "legacy_alpha_profile_migrated": bool(
                    self._cases[self._current_case_idx].get("legacy_alpha_profile_migrated")
                ),
                "start_depth": start_depth_value,
                "manual_start_depth": manual_start_depth,
                "inlet_control_depth": inlet_control_depth,
                "model_test_start_depth": model_test_start_depth,
                "end_depth": params.get("end_depth", ""),
                "flow_cases": flow_cases,
                "flow_case_refinement": {
                    "enabled": True,
                    "coarse_step_ratio": 0.10,
                    "refine_step_ratio": 0.01,
                },
                "use_increase": use_increase,
                "inc_mode": increase_resolution.mode,
                "increase_percent": increase_resolution.engine_increase_percent if use_increase else "",
                "manual_increase": increase_resolution.manual_increase_percent,
                "Q_increased": q_increased if use_increase else "",
                "increase_flow": q_increased if use_increase else "",
                "upstream_connection_mode": "free_to_steep",
                "upstream_channel_slope_type": "mild",
            }
        )
        return params

    @staticmethod
    def _build_auto_flow_cases(design_flow: float, q_increased: float | None = None) -> list[dict[str, float]]:
        """按10%递增自动生成消力池控制工况流量。"""
        cases: list[dict[str, float]] = []
        seen: list[float] = []

        def add_case(name: str, q_value: float) -> None:
            """加入一个不重复的流量工况。"""
            if q_value <= 0:
                return
            rounded_q = round(q_value, 6)
            if any(abs(rounded_q - existed) <= 1.0e-6 for existed in seen):
                return
            seen.append(rounded_q)
            cases.append({"name": name, "Q": rounded_q})

        for step in range(1, 11):
            add_case(f"{step * 10}%设计流量", design_flow * step / 10.0)
        if q_increased is not None:
            add_case("加大流量", q_increased)
        return cases

    def _apply_inputs(self, params: dict[str, Any]) -> None:
        """把项目、算例或工况输入写回界面。"""
        params = self._normalize_case_fields(dict(params))
        params["flow_cases_text"] = ""
        self._suppress_case_save = True
        try:
            for key, field in self._input_fields.items():
                if key in params:
                    field.setText("" if params.get(key) is None else str(params.get(key)))
            for key, combo in self._combo_fields.items():
                value = params.get(key)
                if value is not None:
                    idx = combo.findText(str(value))
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
            for key, check in self._check_fields.items():
                if key in params:
                    check.setChecked(bool(params.get(key)))
            self.inc_edit.setText(str(params.get("inc_pct_text") or ""))
            self.inc_q_edit.setText(str(params.get("inc_q_text") or ""))
            self._set_increase_mode(params.get("inc_mode", INCREASE_MODE_PERCENT))
        finally:
            self._suppress_case_save = False
        self._apply_mode_visibility()

    def _save_current_case(self) -> None:
        """保存当前工况输入。"""
        if not (0 <= self._current_case_idx < len(self._cases)):
            return
        case = dict(self._cases[self._current_case_idx])
        for key, field in self._input_fields.items():
            case[key] = "" if key == "flow_cases_text" else field.text().strip()
        for key, combo in self._combo_fields.items():
            case[key] = combo.currentText()
        for key, check in self._check_fields.items():
            case[key] = check.isChecked()
        case["inc_mode"] = self._current_increase_mode()
        case["inc_pct_text"] = self.inc_edit.text().strip()
        case["inc_q_text"] = self.inc_q_edit.text().strip()
        self._cases[self._current_case_idx] = case
        self._refresh_case_strip()

    def _load_case(self, index: int) -> None:
        """加载指定工况。"""
        if not (0 <= index < len(self._cases)):
            return
        self._current_case_idx = index
        self._apply_inputs(self._cases[index])
        self._refresh_case_strip()

    @staticmethod
    def _auto_case_label(idx: int) -> str:
        """生成未重命名工况的默认显示名。"""
        return f"工况{idx + 1}"

    def _case_label(self, case: dict[str, Any], idx: int) -> str:
        """读取工况显示名，未重命名时使用自动序号名。"""
        custom = str(case.get("custom_label") or "").strip()
        return custom or self._auto_case_label(idx)

    def _case_view(self, case: dict[str, Any], idx: int) -> dict[str, str]:
        """生成工况标签显示信息。"""
        label = self._case_label(case, idx)
        flow = case.get("design_flow", "")
        return {"label": str(label), "compact_label": f"{idx + 1}. {label}", "tooltip": f"{label}｜设计流量 {flow}"}

    def _refresh_case_strip(self) -> None:
        """刷新工况条。"""
        if hasattr(self, "_case_strip"):
            self._case_strip.sync_cases(self._cases, self._current_case_idx, self._case_view)
            self._case_strip.set_remove_enabled(len(self._cases) > 1)

    def _add_case(self) -> None:
        """新增工况。"""
        self._save_current_case()
        new_case = dict(self._cases[self._current_case_idx] if self._cases else self._default_case())
        new_case["custom_label"] = None
        self._cases.append(new_case)
        self._load_case(len(self._cases) - 1)
        self._clear_results_after_input_change()
        self.data_changed.emit()

    def _switch_case(self, index: int) -> None:
        """切换工况。"""
        self._save_current_case()
        self._load_case(index)
        self._set_current_result_for_case(index)
        self._refresh_tables()
        self._refresh_principle_page()
        self._refresh_plot()

    def _rename_case(self, index: int, new_name: str) -> None:
        """重命名工况。"""
        if 0 <= index < len(self._cases):
            self._cases[index]["custom_label"] = new_name
            if index == self._current_case_idx:
                self._input_fields["project_name"].setText(new_name)
            self._refresh_case_strip()
            self.data_changed.emit()

    def _remove_current_case(self) -> None:
        """删除当前工况。"""
        if len(self._cases) <= 1:
            self._show_tip("提示", "至少保留一个工况。", "warning")
            return
        del self._cases[self._current_case_idx]
        self._load_case(min(self._current_case_idx, len(self._cases) - 1))
        self._clear_results_after_input_change()
        self.data_changed.emit()

    def _apply_to_all_cases(self) -> None:
        """把当前工况参数复制到其他工况，保留各自名称和流量。"""
        self._save_current_case()
        source = dict(self._cases[self._current_case_idx])
        for idx, case in enumerate(self._cases):
            if idx == self._current_case_idx:
                continue
            keep = {"custom_label": case.get("custom_label"), "project_name": case.get("project_name"), "design_flow": case.get("design_flow")}
            merged = dict(source)
            merged.update({k: v for k, v in keep.items() if k != "custom_label" and v not in (None, "")})
            merged["custom_label"] = keep["custom_label"]
            self._cases[idx] = merged
        self._refresh_case_strip()
        self._clear_results_after_input_change()
        self._show_tip("已复制", "当前参数已复制到其他工况。", "success")

    def _copy_from_prev_case(self) -> None:
        """从上一个工况复制参数。"""
        if self._current_case_idx <= 0:
            self._show_tip("提示", "当前已是第一个工况。", "warning")
            return
        current_name = self._cases[self._current_case_idx].get("custom_label")
        self._cases[self._current_case_idx] = dict(self._cases[self._current_case_idx - 1])
        self._cases[self._current_case_idx]["custom_label"] = current_name or None
        self._load_case(self._current_case_idx)
        self._clear_results_after_input_change()
        self._show_tip("已复制", "已从上一个工况复制参数。", "success")

    def load_teaching_example(self) -> None:
        """载入内置教学算例。"""
        params = teaching_example()
        params.setdefault("custom_label", "熊启钧教学算例")
        params.setdefault("section_type", "梯形")
        self._apply_inputs(params)
        self._save_current_case()
        self._clear_results_after_input_change()
        self.data_changed.emit()

    def calculate(self) -> None:
        """逐工况调用算法内核并刷新结果。"""
        self._save_current_case()
        active_idx = self._current_case_idx
        results: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
        for idx, _case in enumerate(self._cases):
            self._load_case(idx)
            try:
                params = self._collect_inputs()
                result = self._call_kernel(params)
            except Exception as exc:  # noqa: BLE001 - 前端需要把错误清楚显示给用户
                params = self._safe_current_case_params()
                result = {"success": False, "summary": {"计算状态": "失败", "错误": str(exc)}, "risks": [str(exc)], "profile_points": []}
            result.setdefault("case_label", params.get("custom_label") or params.get("project_name") or f"工况{idx + 1}")
            results.append((idx, params, result))

        self._all_results = results
        self._load_case(active_idx)
        self._set_current_result_for_case(active_idx)
        self._display_all_results()
        self.data_changed.emit()

    def _result_for_case(self, index: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """按工况序号读取对应参数和结果。"""
        for case_idx, params, result in self._all_results:
            if case_idx == index:
                return params, result
        return None, None

    def _set_current_result_for_case(self, index: int) -> None:
        """把当前结果同步到当前工况。"""
        params, result = self._result_for_case(index)
        self.input_params = params or {}
        self.current_result = result

    def _safe_current_case_params(self) -> dict[str, Any]:
        """在计算异常时尽量保存当前表单值。"""
        try:
            return self._collect_inputs()
        except Exception:
            return dict(self._cases[self._current_case_idx])

    def _call_kernel(self, params: dict[str, Any]) -> Any:
        """兼容单字典签名和关键字签名。"""
        try:
            calc_signature = signature(quick_calculate_spillway_steep_chute)
            parameters = list(calc_signature.parameters.values())
        except (TypeError, ValueError):
            parameters = []

        if (
            len(parameters) == 1
            and parameters[0].kind in {Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY}
            and parameters[0].name in {"input_data", "data", "params"}
        ):
            return quick_calculate_spillway_steep_chute(params)
        return quick_calculate_spillway_steep_chute(**params)

    def _display_all_results(self) -> None:
        """刷新所有结果页。"""
        nav_items = self._build_case_nav_items()
        sync_case_result_nav_bar(self._result_case_nav, nav_items)
        body = "".join(self._case_result_html(idx, params, result) for idx, params, result in self._all_results)
        if not body:
            body = self._initial_body()
        load_formula_page(self.result_text, wrap_with_katex(body, extra_css=self._result_css(), extra_head=build_result_navigation_head()))
        self.summary_text.setPlainText(self._plain_summary_text())
        self._refresh_tables()
        self._refresh_principle_page()
        self._refresh_plot()
        self._refresh_comparison_tables()

    def _build_case_nav_items(self) -> list[dict[str, Any]]:
        """构造右侧结果导航项。"""
        items = []
        for idx, params, result in self._all_results:
            summary = normalize_result(result).summary
            items.append(
                {
                    "case_idx": idx,
                    "label": params.get("custom_label") or params.get("project_name") or f"工况{idx + 1}",
                    "summary": summary.get("水面线型") or result.get("water_profile_type") or "",
                    "anchor": f"case-{idx + 1}",
                    "stale": not result.get("success", True),
                }
            )
        return items

    def _jump_to_case_result(self, case_idx: int, *, defer_until_load: bool = False) -> None:
        """跳转到指定工况结果。"""
        scroll_view_to_anchor(self.result_text, f"case-{case_idx + 1}", defer_until_load=defer_until_load)

    def _case_result_html(self, idx: int, params: dict[str, Any], result: dict[str, Any]) -> str:
        """生成单工况 HTML。"""
        view = normalize_result(result)
        label = html.escape(str(params.get("custom_label") or params.get("project_name") or f"工况{idx + 1}"))
        success_class = "ok" if result.get("success", True) else "bad"
        parts = [f'<section class="case-card" id="case-{idx + 1}">', f'<div class="case-title">{label}</div>']
        parts.append(f'<div class="status {success_class}">{"计算完成" if result.get("success", True) else "计算失败"}</div>')
        parts.append(self._summary_grid_html(view.summary))
        parts.append(self._connection_html(result))
        parts.append(self._jump_html(result))
        if view.risks:
            parts.append("<h3>风险提示</h3><ul>" + "".join(f"<li>{html.escape(str(item))}</li>" for item in view.risks) + "</ul>")
        parts.append("</section>")
        return "".join(parts)

    def _summary_grid_html(self, summary: dict[str, Any]) -> str:
        """生成重点结果卡片。"""
        if not summary:
            return ""
        rows = "".join(
            f'<div class="metric"><span>{html.escape(str(key))}</span><strong>{html.escape(str(value))}</strong></div>'
            for key, value in summary.items()
        )
        return f"<h3>重点结果</h3><div class='metric-grid'>{rows}</div>"

    def _connection_html(self, result: dict[str, Any]) -> str:
        """生成上下游衔接说明。"""
        upstream = result.get("upstream_connection") or {}
        export = result.get("water_profile_export") or {}
        lines = []
        if upstream:
            lines.append(str(upstream.get("message") or "已完成上游衔接判断。"))
        if export:
            lines.append(str(export.get("说明") or "已生成表3轻量接口。"))
        if not lines:
            return ""
        return "<h3>上下游衔接</h3>" + "".join(f"<p>{html.escape(line)}</p>" for line in lines)

    def _jump_html(self, result: dict[str, Any]) -> str:
        """生成公式渲染和消能说明。"""
        jump = result.get("hydraulic_jump") or {}
        aeration = result.get("aeration_and_sidewall") or {}
        cards = []
        if aeration:
            cards.append(("掺气与侧墙", r"h_b=\left(1+\frac{\zeta v}{100}\right)h", aeration.get("message", "")))
        if jump:
            cards.append(("水跃与消力池", r"h_c''=\frac{h_c'}{2}\left(\sqrt{1+8Fr_1^2}-1\right)", jump.get("message", "")))
        if not cards:
            return ""
        html_parts = ["<h3>公式说明</h3>"]
        for title, latex, message in cards:
            html_parts.append(f"<div class='formula-card'><div class='formula-title'>{html.escape(title)}</div>{self._latex_html(latex)}<p>{html.escape(str(message))}</p></div>")
        return "".join(html_parts)

    @staticmethod
    def _latex_html(latex: str) -> str:
        """把公式渲染为内联 SVG，失败时显示中文提示。"""
        rendered = render_latex_svg(latex, fontsize=17)
        if rendered:
            return f"<div class='formula-svg'>{rendered}</div>"
        return "<p class='formula-fallback'>该公式暂无法渲染，请查看计算说明。</p>"

    def _plain_summary_text(self) -> str:
        """生成兼容旧测试和复制的纯文本摘要。"""
        lines = []
        for _idx, params, result in self._all_results:
            label = params.get("custom_label") or params.get("project_name") or "当前工况"
            lines.append(str(label))
            for key, value in normalize_result(result).summary.items():
                lines.append(f"{key}：{value}")
            for risk in normalize_result(result).risks:
                lines.append(f"风险提示：{risk}")
            lines.append("")
        return "\n".join(lines).strip()

    def _refresh_tables(self) -> None:
        """刷新沿程表和规范校核表。"""
        result = self.current_result or {}
        view = normalize_result(result)
        profile_rows = [
            [
                point.get("station_m", point.get("x", "")),
                point.get("bed_elevation_m", point.get("bed_elevation", "")),
                point.get("depth_m", point.get("depth", "")),
                point.get("water_elevation_m", point.get("water_elevation", "")),
                point.get("velocity_ms", ""),
                point.get("froude", ""),
                point.get("aerated_depth_m", ""),
                point.get("sidewall_top_elevation_m", ""),
            ]
            for point in view.profile_points
        ]
        self._fill_table(self.profile_table, profile_rows)
        check_rows = [
            [item.get("name") or item.get("项目") or "", item.get("result") or item.get("结论") or "", item.get("message") or item.get("说明") or ""]
            for item in view.checks
        ]
        self._fill_table(self.check_table, check_rows)

    def _current_principle_input_snapshot(self) -> dict[str, Any]:
        """安全读取当前输入快照，仅用于计算前原理预览。"""
        params: dict[str, Any] = {}
        for key, field in self._input_fields.items():
            params[key] = field.text().strip()
        for key, combo in self._combo_fields.items():
            params[key] = combo.currentText()
        for key, check in self._check_fields.items():
            params[key] = check.isChecked()
        params["custom_label"] = self._case_label(self._cases[self._current_case_idx], self._current_case_idx)
        params["inc_mode"] = self._current_increase_mode()
        params["inc_pct_text"] = self.inc_edit.text().strip()
        params["inc_q_text"] = self.inc_q_edit.text().strip()
        return params

    def _render_principle_cards(self, principles: list[dict[str, str]], intro: str) -> None:
        """把计算原理步骤渲染到页签。"""
        body_parts = ["<section class='case-card'><div class='case-title'>计算原理</div>"]
        body_parts.append(f"<p>{html.escape(intro)}</p>")
        body_parts.append(render_principle_flow_overview_html(principles))
        for idx, item in enumerate(principles, start=1):
            step = html.escape(str(item.get("step") or f"步骤{idx}"))
            purpose = html.escape(str(item.get("purpose") or ""))
            variables = render_principle_inline_html(item.get("variables") or "")
            substitution = render_principle_inline_html(item.get("substitution") or "")
            result_text = render_principle_inline_html(item.get("result") or "")
            explanation = render_principle_inline_html(item.get("explanation") or "")
            source = html.escape(str(item.get("source") or ""))
            latex = str(item.get("formula") or "")
            body_parts.append(
                "<div class='formula-card principle-card'>"
                f"<div class='formula-title'>{idx}. {step}</div>"
                f"<p><strong>计算目的：</strong>{purpose}</p>"
                f"{self._latex_html(latex)}"
                f"<p><strong>变量含义：</strong>{variables}</p>"
                f"<p><strong>本次代入：</strong>{substitution}</p>"
                f"<p><strong>计算结果：</strong>{result_text}</p>"
                f"<p><strong>原理说明：</strong>{explanation}</p>"
                f"<p><strong>来源：</strong>{source}</p>"
                "</div>"
            )
        body_parts.append("</section>")
        load_formula_page(self.principle_view, wrap_with_katex("".join(body_parts), extra_css=self._result_css()))

    def _refresh_principle_page(self) -> None:
        """刷新计算原理页。"""
        if self.current_result:
            principles = build_calculation_principles(self.current_result)
            intro = "本页按实际计算顺序说明每一步的目的、公式、变量含义、本次代入值和结果，便于复核计算过程。"
        else:
            principles = build_precalculation_principles(self._current_principle_input_snapshot())
            intro = "这里先按当前输入展示计算流程、公式、变量含义和来源；真正依赖计算的数值会在点击计算后生成。"
        self._render_principle_cards(principles, intro)

    def _refresh_plot(self) -> None:
        """刷新纵断面图。"""
        result = self.current_result or {}
        configure_section_grid_canvas(self, 1)
        draw_longitudinal_profile(self.profile_fig, result)
        self.profile_canvas.draw_idle()

    def _update_section_plot_all(self) -> None:
        """供共享画布布局在页签显示或窗口变化时刷新纵断面图。"""
        self._refresh_plot()

    def _comparison_rows(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """整理两张工况对比表。"""
        hydraulic_rows = []
        layout_rows = []
        for idx, params, result in self._all_results:
            label = params.get("custom_label") or params.get("project_name") or f"工况{idx + 1}"
            hydraulic = result.get("hydraulic") or {}
            jump = result.get("hydraulic_jump") or {}
            aeration = result.get("aeration_and_sidewall") or {}
            case_rows = build_comparison_rows(result)
            max_v = case_rows[0].get("max_v") if case_rows else ""
            hydraulic_rows.append(
                {
                    "case": label,
                    "flow": params.get("Q"),
                    "profile_type": result.get("water_profile_type") or hydraulic.get("water_profile_type"),
                    "end_depth": (result.get("profile") or {}).get("end_depth_m"),
                    "max_velocity": max_v,
                    "max_froude": (result.get("case_result") or {}).get("max_froude"),
                    "jump_depth": jump.get("conjugate_depth_m"),
                }
            )
            layout_rows.append(
                {
                    "case": label,
                    "sidewall_height": aeration.get("recommended_sidewall_height_m"),
                    "pool_length": jump.get("recommended_pool_length_m"),
                    "pool_depth": jump.get("recommended_pool_depth_m"),
                    "tailwater": jump.get("tailwater_judgement"),
                    "status": "需复核" if normalize_result(result).risks else "通过",
                }
            )
        return hydraulic_rows, layout_rows

    def _refresh_comparison_tables(self) -> None:
        """刷新工况对比页。"""
        hydraulic_rows, layout_rows = self._comparison_rows()
        fill_comparison_table(self.comparison_hydraulic_table, _HYDRAULIC_COLUMNS, hydraulic_rows)
        fill_comparison_table(self.comparison_layout_table, _LAYOUT_COLUMNS, layout_rows)
        self.comparison_hint.setText("已汇总成功计算的工况；消力池控制以第二版水跃和尾水判断为准。" if hydraulic_rows else "请先完成计算。")

    def _fill_table(self, table: QTableWidget, rows: list[list[Any]]) -> None:
        """把二维数据写入表格。"""
        table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            for col_idx, value in enumerate(row):
                item = QTableWidgetItem("" if value is None else str(value))
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, col_idx, item)

    def _show_initial_help(self) -> None:
        """展示初始帮助页。"""
        load_formula_page(self.result_text, wrap_with_katex(self._initial_body(), extra_css=self._result_css()))
        self._refresh_principle_page()

    def _initial_body(self) -> str:
        """生成初始页面。"""
        profile_formula = self._latex_html(r"h_0<h<h_k,\quad \text{采用 }b_2\text{ 型降水曲线}")
        return (
            "<section class='case-card'>"
            "<div class='case-title'>泄水渠与陡坡计算</div>"
            "<p>请填写左侧参数，或载入教学算例后点击“计算”。结果会给出水面线、上下游衔接、掺气侧墙、水跃消能和表3轻量接口。</p>"
            f"<div class='formula-card'><div class='formula-title'>标准陡坡水面线</div>{profile_formula}</div>"
            "</section>"
        )

    def _stale_body(self) -> str:
        """生成参数变化后的提示页面。"""
        return (
            "<section class='case-card'>"
            "<div class='case-title'>参数已变更</div>"
            "<p>当前输入已变化，请重新点击“计算”生成新的结果、图形和导出内容。</p>"
            "</section>"
        )

    def _principle_help_body(self) -> str:
        """生成计算原理页初始内容。"""
        steps = [
            "基础断面与水力要素",
            "正常水深",
            "临界水深",
            "坡型判别",
            "起点控制水深",
            "水面线逐段计算",
            "掺气水深与侧墙高度",
            "水跃与消力池",
            "出口整流段",
            "规范校核与风险提示",
        ]
        step_items = "".join(f"<li>{html.escape(step)}</li>" for step in steps)
        return (
            "<section class='case-card'>"
            "<div class='case-title'>计算原理</div>"
            "<p>完成计算后，这里会按审查顺序展示完整计算流程、详细公式、变量含义、本次代入值、计算结果和来源。</p>"
            f"<ol>{step_items}</ol>"
            "</section>"
        )

    @staticmethod
    def _result_css() -> str:
        """返回结果页补充样式。"""
        return """
        body { background:#F5F7FB; }
        .case-card { background:#fff; border:1px solid #E6EDF5; border-radius:8px; padding:18px 22px; margin:0 0 14px 0; }
        .case-title { font-size:20px; font-weight:700; color:#0E5DB8; margin-bottom:10px; }
        .status { display:inline-block; padding:4px 10px; border-radius:12px; font-size:12px; font-weight:700; margin-bottom:12px; }
        .status.ok { color:#1B7F46; background:#E8F6EF; }
        .status.bad { color:#B42318; background:#FDECEC; }
        h3 { font-size:15px; color:#1F3B57; margin:16px 0 8px 0; }
        p, li { color:#334155; font-size:13px; }
        .metric-grid { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:8px; }
        .metric { border:1px solid #E5ECF5; border-radius:8px; padding:9px 10px; background:#FAFCFF; }
        .metric span { display:block; color:#6B7A90; font-size:12px; }
        .metric strong { display:block; color:#1F2A37; font-size:14px; margin-top:2px; }
        .formula-card { border:1px solid #E5ECF5; border-radius:8px; background:#FAFCFF; padding:12px 14px; margin:8px 0; }
        .formula-title { color:#0E5DB8; font-weight:700; font-size:13px; margin-bottom:6px; }
        .formula-svg { overflow-x:auto; padding:6px 0; }
        .formula-fallback { color:#64748B; background:#F1F5F9; border-radius:6px; padding:8px 10px; }
        .principle-flow { border:1px solid #D8E6F7; background:#F8FBFF; border-radius:8px; padding:12px 14px; margin:12px 0 16px 0; }
        .principle-flow h3 { margin-top:0; color:#0E5DB8; }
        .principle-flow-intro { margin:0 0 10px 0; color:#475569; }
        .principle-flow-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:8px; }
        .principle-flow-card { position:relative; border:1px solid #E1EAF5; background:#FFFFFF; border-radius:8px; padding:10px 10px 10px 44px; min-height:112px; }
        .principle-flow-index { position:absolute; left:10px; top:10px; width:24px; height:24px; line-height:24px; text-align:center; border-radius:50%; background:#0E5DB8; color:#FFFFFF; font-weight:700; font-size:12px; }
        .principle-flow-name { color:#16395F; font-weight:700; font-size:13px; margin-bottom:5px; }
        .principle-flow-card p { margin:3px 0; line-height:1.5; color:#334155; font-size:12px; }
        .principle-card p { margin:6px 0; line-height:1.65; }
        """

    def _show_tip(self, title: str, content: str, level: str = "info") -> None:
        """显示轻量提示。"""
        if InfoBar is not None:
            fn = getattr(InfoBar, level, None) or getattr(InfoBar, "info")
            position = getattr(InfoBarPosition, "TOP", None) if InfoBarPosition is not None else None
            fn(title=title, content=content, parent=self, position=position, duration=2500)
            return
        QMessageBox.information(self, title, content)

    def reset_to_default(self) -> None:
        """恢复到新项目默认状态。"""
        self._suppress_case_save = True
        try:
            self._cases = [self._default_case()]
            self._current_case_idx = 0
            self._all_results = []
            self.input_params = {}
            self.current_result = None
            self._apply_inputs(self._cases[0])
        finally:
            self._suppress_case_save = False
        self._refresh_case_strip()
        self._fill_table(self.profile_table, [])
        self._fill_table(self.check_table, [])
        self.summary_text.clear()
        sync_case_result_nav_bar(self._result_case_nav, [])
        self._refresh_plot()
        self._refresh_comparison_tables()
        self._show_initial_help()

    def _clear(self) -> None:
        """清空当前计算结果，保留用户输入和多工况。"""
        self._save_current_case()
        self._all_results = []
        self.input_params = {}
        self.current_result = None
        self._fill_table(self.profile_table, [])
        self._fill_table(self.check_table, [])
        self.summary_text.clear()
        sync_case_result_nav_bar(self._result_case_nav, [])
        self._refresh_plot()
        self._refresh_comparison_tables()
        self._show_initial_help()
        self.data_changed.emit()

    def _case_label_for_export(self, idx: int, params: dict[str, Any]) -> str:
        """生成导出使用的工况名称。"""
        return self._case_label(params, idx)

    @staticmethod
    def _path_with_suffix(path: str, suffix: str) -> str:
        """确保导出路径带有正确文件后缀。"""
        output_path = Path(path)
        normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
        if output_path.suffix.lower() != normalized_suffix.lower():
            output_path = output_path.with_suffix(normalized_suffix)
        return str(output_path)

    @staticmethod
    def _safe_filename_part(text: Any, fallback: str) -> str:
        """把工程名或工况名整理成可用于文件名的文本。"""
        raw = str(text or "").strip() or fallback
        invalid_chars = '<>:"/\\|?*'
        chars = [
            "_" if char in invalid_chars or ord(char) < 32 else char
            for char in raw
        ]
        name = "".join(chars).strip(" ._")
        return (name or fallback)[:80]

    def _default_export_path(
        self,
        *,
        suffix_text: str,
        extension: str,
        scope: str = "current",
        current_label: str = "",
        current_params: dict[str, Any] | None = None,
        case_count: int = 1,
    ) -> str:
        """生成保存对话框中的默认导出文件名。"""
        params = current_params or {}
        summary = (self.current_result or {}).get("summary") if isinstance(self.current_result, dict) else {}
        label = current_label or str(
            params.get("custom_label")
            or params.get("project_name")
            or params.get("structure_name")
            or (summary or {}).get("工程名称")
            or "泄水渠与陡坡"
        )
        if scope == "all" and case_count > 1:
            label = f"{label}等{case_count}个工况"
        prefix = self._safe_filename_part(label, "泄水渠与陡坡")
        filename = f"{prefix}_{suffix_text}.{extension.lstrip('.')}"
        return os.path.join(os.getcwd(), filename)

    def _build_export_payload(self, scope: str) -> dict[str, Any] | None:
        """按导出范围整理当前或全部工况结果。"""
        if scope == "current" or len(self._all_results) <= 1:
            return self.current_result
        export_cases = [
            {
                "index": idx,
                "label": self._case_label_for_export(idx, params),
                "params": params,
                "result": result,
            }
            for idx, params, result in self._all_results
        ]
        return {"export_cases": export_cases}

    def export_word(self) -> None:
        """导出计算书。"""
        if not self.current_result:
            self._show_tip("提示", "请先完成计算。", "warning")
            return
        meta = load_meta()
        current_params = self.input_params or self._safe_current_case_params()
        case_count = len(self._all_results) if self._all_results else 1
        current_label = self._case_label_for_export(self._current_case_idx, current_params)
        auto_purpose = build_calc_purpose(
            "spillway_steep_chute",
            project=meta.project_name,
            name=str(current_params.get("project_name") or current_params.get("structure_name") or ""),
            section_type=str(current_params.get("section_type") or ""),
        )
        dialog = ExportConfirmDialog(
            "spillway_steep_chute",
            "泄水渠与陡坡计算书",
            auto_purpose,
            parent=self,
            n_cases=case_count,
            current_case_label=current_label,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        export_scope = dialog.get_export_scope()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出计算书",
            self._default_export_path(
                suffix_text="泄水渠与陡坡计算书",
                extension=".docx",
                scope=export_scope,
                current_label=current_label,
                current_params=current_params,
                case_count=case_count,
            ),
            "Word文档 (*.docx);;所有文件 (*.*)",
        )
        if path:
            path = self._path_with_suffix(path, ".docx")
            payload = self._build_export_payload(export_scope)
            export_spillway_steep_chute_word(
                path,
                payload,
                meta=dialog.get_meta(),
                calc_purpose=dialog.get_calc_purpose(),
                references=dialog.get_references(),
            )
            self._show_tip("导出成功", "文档计算书已保存。", "success")
            ask_open_file(path, self)

    def export_excel(self) -> None:
        """导出表格成果。"""
        if not self.current_result:
            self._show_tip("提示", "请先完成计算。", "warning")
            return
        current_params = self.input_params or self._safe_current_case_params()
        case_count = len(self._all_results) if self._all_results else 1
        current_label = self._case_label_for_export(self._current_case_idx, current_params)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出表格",
            self._default_export_path(
                suffix_text="泄水渠与陡坡计算表",
                extension=".xlsx",
                scope="all",
                current_label=current_label,
                current_params=current_params,
                case_count=case_count,
            ),
            "Excel文件 (*.xlsx);;所有文件 (*.*)",
        )
        if path:
            path = self._path_with_suffix(path, ".xlsx")
            export_spillway_steep_chute_excel(path, self._build_export_payload("all"))
            self._show_tip("导出成功", "表格成果已保存。", "success")
            ask_open_file(path, self)

    def to_project_dict(self) -> dict[str, Any]:
        """导出项目保存状态。"""
        self._save_current_case()
        input_params: dict[str, Any] = {}
        input_params_error = ""
        try:
            input_params = self._collect_inputs()
        except Exception as exc:  # noqa: BLE001 - 保存项目不能因临时输入中断
            input_params_error = str(exc)
        state = {
            "panel_key": self._panel_key,
            "cases": self._cases,
            "current_case_idx": self._current_case_idx,
            "input_params": input_params,
            "all_results": self._all_results,
            "current_result": self.current_result,
            "notebook_idx": self.notebook.currentIndex(),
        }
        if input_params_error:
            state["input_params_error"] = input_params_error
        return state

    def from_project_dict(self, data: dict[str, Any] | None) -> None:
        """从项目保存状态恢复面板。"""
        payload = data or {}
        cases = payload.get("cases")
        if cases:
            self._cases = [self._normalize_case_fields(dict(case)) for case in cases]
        else:
            self._cases = [dict(self._default_case())]
            legacy_input = dict(payload.get("input_params") or {})
            if "inc_mode" not in legacy_input and legacy_input.get("increase_flow") not in (None, ""):
                legacy_input["inc_mode"] = INCREASE_MODE_Q_INCREASED
            if "inlet_connection_type_label" not in legacy_input and "inlet_connection_type" not in legacy_input:
                self._cases[0]["inlet_connection_type_label"] = ""
            if "alpha_profile" not in legacy_input:
                self._cases[0]["alpha_profile"] = ""
            self._cases[0].update(legacy_input)
            self._normalize_case_fields(self._cases[0])
        self._current_case_idx = int(payload.get("current_case_idx") or 0)
        self._current_case_idx = max(0, min(self._current_case_idx, len(self._cases) - 1))
        self._load_case(self._current_case_idx)
        self._all_results = [
            (int(item[0]), dict(item[1]), dict(item[2]))
            for item in payload.get("all_results") or []
            if isinstance(item, (list, tuple)) and len(item) >= 3
        ]
        self.current_result = payload.get("current_result")
        if self.current_result and not self._all_results:
            self._all_results = [(self._current_case_idx, self._collect_inputs(), self.current_result)]
        if self._all_results:
            self._set_current_result_for_case(self._current_case_idx)
            self._display_all_results()
        index = int(payload.get("notebook_idx") or 0)
        if 0 <= index < self.notebook.count():
            self.notebook.setCurrentIndex(index)
        self.data_changed.emit()
