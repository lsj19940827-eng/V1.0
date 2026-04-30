# -*- coding: utf-8 -*-
"""圆拱直墙型隧洞按目标净空比例反推尺寸的独立弹窗。"""

import math
import os
import sys
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import LineEdit, PrimaryPushButton, PushButton

_pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_kernel_dir = os.path.join(_pkg_root, "calc_渠系计算算法内核")
if _kernel_dir not in sys.path:
    sys.path.insert(0, _kernel_dir)

from 隧洞设计 import design_horseshoe_by_freeboard_target

from app_渠系计算前端.styles import (
    BD,
    CARD,
    DIALOG_STYLE,
    INPUT_HINT_STYLE,
    P,
    S,
    T1,
    T2,
    W,
)
from app_渠系计算前端.tunnel.geometry import (
    arch_half_width,
    build_arch_geometry,
    build_arch_water_fill_polygon,
)

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


DEFAULT_TARGET_FREEBOARD_PCT_TEXT = "15.000"
DEFAULT_HB_RATIO_TEXT = "1.200"
_PREFS_FILENAME = "tunnel_clearance_sizing_prefs.json"


def _get_clearance_sizing_prefs_path():
    """获取净空反推弹窗偏好文件路径。"""
    appdata = os.path.join(os.path.expanduser("~"), ".canal_calc")
    os.makedirs(appdata, exist_ok=True)
    return os.path.join(appdata, _PREFS_FILENAME)


def _load_clearance_sizing_prefs():
    """读取净空反推弹窗偏好。"""
    path = _get_clearance_sizing_prefs_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        print(f"读取净空反推偏好失败: {exc}")
        return {}


def _save_clearance_sizing_prefs(payload):
    """保存净空反推弹窗偏好。"""
    try:
        path = _get_clearance_sizing_prefs_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"保存净空反推偏好失败: {exc}")


def _pref_number_text(prefs, key, validator):
    """读取并校验偏好里的数字文本。"""
    text = str(prefs.get(key, "") or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return text if validator(value) else None


def _same_number(left, right, tol=1e-9):
    """判断两个上下文数值是否一致。"""
    try:
        return abs(float(left) - float(right)) <= tol
    except (TypeError, ValueError):
        return False


class HorseshoeClearanceSizingDialog(QDialog):
    """圆拱直墙型目标净空反推尺寸弹窗。"""

    def __init__(self, parent=None, context=None):
        super().__init__(parent)
        self.context = dict(context or {})
        self.result_payload = None
        self._metric_labels = {}

        self.setWindowTitle("按净空比例反推圆拱直墙尺寸")
        self.resize(820, 660)
        self.setMinimumSize(760, 600)
        self.setStyleSheet(DIALOG_STYLE + self._dialog_extra_style())

        self._build_ui()
        self._load_context()

    def _dialog_extra_style(self):
        """生成弹窗内部 Fluent 风格补充样式。"""
        return f"""
        QFrame#summaryCard, QFrame#statusCard {{
            background: #F7F9FC;
            border: 1px solid {BD};
            border-radius: 8px;
        }}
        QLabel#dialogTitle {{
            color: {T1};
            font-size: 18px;
            font-weight: 600;
        }}
        QLabel#subTitle {{
            color: {T2};
            font-size: 12px;
        }}
        QLabel#metricName {{
            color: {T2};
            font-size: 12px;
        }}
        QLabel#metricValue {{
            color: {T1};
            font-size: 13px;
            font-weight: 600;
        }}
        QLabel#statusOk {{
            color: {S};
            font-size: 13px;
            font-weight: 600;
        }}
        QLabel#statusWarn {{
            color: {W};
            font-size: 13px;
            font-weight: 600;
        }}
        """

    def _build_ui(self):
        """构建弹窗界面。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("按加大流量净空比例反推尺寸")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        subtitle = QLabel("结果只在点击“采用到当前工况”后回填 θ、B、H直，不会自动执行主计算。")
        subtitle.setObjectName("subTitle")
        root.addWidget(subtitle)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        top_row.addWidget(self._build_input_group(), 1)
        top_row.addWidget(self._build_summary_card(), 1)
        root.addLayout(top_row)

        mid_row = QHBoxLayout()
        mid_row.setSpacing(12)
        mid_row.addWidget(self._build_result_group(), 1)
        mid_row.addWidget(self._build_preview_group(), 1)
        root.addLayout(mid_row, 1)

        self.status_card = QFrame()
        self.status_card.setObjectName("statusCard")
        status_lay = QVBoxLayout(self.status_card)
        status_lay.setContentsMargins(12, 10, 12, 10)
        self.status_label = QLabel("请输入参数后点击“计算”。")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("statusWarn")
        status_lay.addWidget(self.status_label)
        root.addWidget(self.status_card)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.calc_btn = PushButton("计算")
        self.calc_btn.clicked.connect(self._calculate)
        self.apply_btn = PrimaryPushButton("采用到当前工况")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._accept_result)
        self.close_btn = PushButton("关闭")
        self.close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.calc_btn)
        btn_row.addWidget(self.apply_btn)
        btn_row.addWidget(self.close_btn)
        root.addLayout(btn_row)

    def _build_input_group(self):
        """构建输入参数区。"""
        group = QGroupBox("反推输入")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(8)

        self.q_inc_edit = LineEdit()
        self.q_inc_edit.setPlaceholderText("例如 12.0")
        form.addRow("加大流量 Q加大 (m³/s):", self.q_inc_edit)

        self.freeboard_edit = LineEdit()
        self.freeboard_edit.setPlaceholderText("例如 20")
        form.addRow("目标净空比例 (%):", self.freeboard_edit)

        self.hb_edit = LineEdit()
        self.hb_edit.setPlaceholderText("1.0~1.5")
        form.addRow("高宽比 H/B:", self.hb_edit)

        self.theta_edit = LineEdit()
        self.theta_edit.setPlaceholderText("90~180")
        form.addRow("圆心角 θ (度):", self.theta_edit)

        hint = QLabel("H/B 严格按 1.0~1.5 校核；净空比例为净空面积比。")
        hint.setStyleSheet(INPUT_HINT_STYLE)
        hint.setWordWrap(True)
        form.addRow(hint)
        return group

    def _build_summary_card(self):
        """构建当前工况摘要区。"""
        card = QFrame()
        card.setObjectName("summaryCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        title = QLabel("当前工况")
        title.setStyleSheet(f"font-weight:600;color:{P};")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        for row, (key, name) in enumerate([
            ("Q_design", "设计流量"),
            ("n", "糙率"),
            ("slope_inv", "水力坡降"),
            ("v_range", "流速范围"),
        ]):
            name_label = QLabel(name)
            name_label.setObjectName("metricName")
            value_label = QLabel("-")
            value_label.setObjectName("metricValue")
            self._metric_labels[key] = value_label
            grid.addWidget(name_label, row, 0)
            grid.addWidget(value_label, row, 1)
        layout.addLayout(grid)
        layout.addStretch()
        return card

    def _build_result_group(self):
        """构建结果展示区。"""
        group = QGroupBox("推荐尺寸与校核")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        self.result_labels = {}
        rows = [
            ("B", "底宽 B"),
            ("H_total", "总高 H"),
            ("H_straight", "直墙高度 H直"),
            ("H_arch", "拱高 H拱"),
            ("h_increased", "加大水深"),
            ("V_increased", "加大流速"),
            ("freeboard_pct_inc", "净空比例"),
            ("freeboard_hgt_inc", "净空高度"),
        ]
        for row, (key, name) in enumerate(rows):
            name_label = QLabel(name)
            name_label.setObjectName("metricName")
            value_label = QLabel("-")
            value_label.setObjectName("metricValue")
            self.result_labels[key] = value_label
            grid.addWidget(name_label, row, 0)
            grid.addWidget(value_label, row, 1)
        return group

    def _build_preview_group(self):
        """构建断面预览区。"""
        group = QGroupBox("断面预览")
        layout = QVBoxLayout(group)
        self.figure = Figure(figsize=(3.8, 3.0), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)
        self._draw_empty_preview()
        return group

    def _load_context(self):
        """把当前工况载入弹窗。"""
        prefs = _load_clearance_sizing_prefs()
        q_design = self._context_float("Q_design")
        n = self._context_float("n")
        slope_inv = self._context_float("slope_inv")
        v_min = self._context_float("v_min")
        v_max = self._context_float("v_max")
        q_inc = self._context_float("Q_increased")
        theta = self._context_float("theta_deg", 180.0)
        q_source = str(self.context.get("Q_increased_source", "") or "")

        self._metric_labels["Q_design"].setText(f"{q_design:.3f} m³/s")
        self._metric_labels["n"].setText(f"{n:.4f}")
        self._metric_labels["slope_inv"].setText(f"1/{slope_inv:.0f}")
        self._metric_labels["v_range"].setText(f"{v_min:.3f}~{v_max:.3f} m/s")

        q_inc_text = None
        if self._q_increased_pref_matches_context(prefs, q_design, q_inc, q_source):
            q_inc_text = _pref_number_text(prefs, "Q_increased", lambda value: value > q_design)
        freeboard_text = _pref_number_text(
            prefs,
            "target_freeboard_pct",
            lambda value: 15.0 <= value < 100.0,
        )
        hb_text = _pref_number_text(prefs, "hb_ratio", lambda value: 1.0 <= value <= 1.5)
        theta_text = _pref_number_text(prefs, "theta_deg", lambda value: 90.0 <= value <= 180.0)

        self.q_inc_edit.setText(q_inc_text or (f"{q_inc:.3f}" if q_inc > 0 else ""))
        self.freeboard_edit.setText(freeboard_text or DEFAULT_TARGET_FREEBOARD_PCT_TEXT)
        self.hb_edit.setText(hb_text or DEFAULT_HB_RATIO_TEXT)
        self.theta_edit.setText(theta_text or f"{theta:.3f}")

    def _q_increased_pref_matches_context(self, prefs, q_design, q_inc, q_source):
        """判断历史 Q加大 是否仍属于当前主流程上下文。"""
        if not isinstance(prefs, dict):
            return False
        return (
            _same_number(prefs.get("Q_design"), q_design)
            and _same_number(prefs.get("base_Q_increased"), q_inc)
            and str(prefs.get("Q_increased_source", "") or "") == q_source
        )

    def _context_float(self, key, default=0.0):
        """读取上下文数字。"""
        try:
            return float(self.context.get(key, default))
        except (TypeError, ValueError):
            return default

    def _read_float(self, edit, label):
        """读取输入框数字并统一报错。"""
        text = edit.text().strip()
        if not text:
            raise ValueError(f"请输入{label}")
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(f"{label}输入无效") from exc

    def _calculate(self):
        """执行反推计算。"""
        try:
            payload = self._build_payload()
            result = design_horseshoe_by_freeboard_target(**payload)
        except ValueError as exc:
            self._show_failure(str(exc))
            return

        if not result.get("success"):
            self._show_failure(result.get("error_message", "反推失败，请检查输入。"))
            return

        self._save_current_inputs()
        self.result_payload = result
        self.apply_btn.setEnabled(True)
        self.status_label.setObjectName("statusOk")
        self.status_label.setText("已得到可采用尺寸。点击“采用到当前工况”后会回填 θ、B、H直。")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self._fill_result(result)
        self._draw_preview(result)

    def _build_payload(self):
        """整理内核输入。"""
        return {
            "Q_design": self._context_float("Q_design"),
            "Q_increased": self._read_float(self.q_inc_edit, "加大流量 Q加大"),
            "n": self._context_float("n"),
            "slope_inv": self._context_float("slope_inv"),
            "v_min": self._context_float("v_min"),
            "v_max": self._context_float("v_max"),
            "theta_deg": self._read_float(self.theta_edit, "圆心角 θ"),
            "hb_ratio": self._read_float(self.hb_edit, "高宽比 H/B"),
            "target_freeboard_pct": self._read_float(self.freeboard_edit, "目标净空比例"),
        }

    def _save_current_inputs(self):
        """保存当前反推输入，供下次打开恢复。"""
        _save_clearance_sizing_prefs({
            "Q_increased": self.q_inc_edit.text().strip(),
            "Q_design": self._context_float("Q_design"),
            "base_Q_increased": self._context_float("Q_increased"),
            "Q_increased_source": str(self.context.get("Q_increased_source", "") or ""),
            "target_freeboard_pct": self.freeboard_edit.text().strip(),
            "hb_ratio": self.hb_edit.text().strip(),
            "theta_deg": self.theta_edit.text().strip(),
        })

    def _show_failure(self, message):
        """展示失败信息并禁用采用。"""
        self.result_payload = None
        self.apply_btn.setEnabled(False)
        self.status_label.setObjectName("statusWarn")
        self.status_label.setText(message)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        for label in self.result_labels.values():
            label.setText("-")
        self._draw_empty_preview()

    def _fill_result(self, result):
        """填充结果数字。"""
        units = {
            "B": " m",
            "H_total": " m",
            "H_straight": " m",
            "H_arch": " m",
            "h_increased": " m",
            "V_increased": " m/s",
            "freeboard_pct_inc": "%",
            "freeboard_hgt_inc": " m",
        }
        for key, label in self.result_labels.items():
            value = float(result.get(key, 0.0) or 0.0)
            suffix = units.get(key, "")
            label.setText(f"{value:.3f}{suffix}")

    def _draw_empty_preview(self):
        """绘制空预览。"""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.text(0.5, 0.5, "等待计算", ha="center", va="center", color=T2)
        ax.set_axis_off()
        self.canvas.draw_idle()

    def _draw_preview(self, result):
        """绘制圆拱直墙断面和加大水位线。"""
        B = float(result.get("B", 0.0) or 0.0)
        H = float(result.get("H_total", 0.0) or 0.0)
        h = float(result.get("h_increased", 0.0) or 0.0)
        theta = math.radians(float(result.get("theta_deg", 180.0) or 180.0))
        if B <= 0 or H <= 0:
            self._draw_empty_preview()
            return

        geom = build_arch_geometry(B, H, theta)
        half = geom["B"] / 2.0
        h_straight = geom["H_straight"]
        arc_t = [
            geom["start_angle"] + (geom["end_angle"] - geom["start_angle"]) * i / 80
            for i in range(81)
        ]
        arc_x = [geom["R_arch"] * math.cos(t) for t in arc_t]
        arc_y = [geom["center_y"] + geom["R_arch"] * math.sin(t) for t in arc_t]

        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.plot([-half, -half, half, half], [h_straight, 0, 0, h_straight], color="#1F2937", linewidth=1.8)
        ax.plot(arc_x, arc_y, color="#1F2937", linewidth=1.8)

        water_y = min(max(h, 0.0), H)
        water_half = arch_half_width(geom, water_y)
        fill_x, fill_y = build_arch_water_fill_polygon(geom, water_y)
        if fill_x and fill_y:
            ax.fill(fill_x, fill_y, color="#BEE3F8", alpha=0.45)
        ax.plot([-water_half, water_half], [water_y, water_y], color="#0284C7", linewidth=1.5)
        ax.set_aspect("equal", adjustable="box")
        pad = max(B, H) * 0.12
        ax.set_xlim(-half - pad, half + pad)
        ax.set_ylim(-pad * 0.35, H + pad)
        ax.set_axis_off()
        self.canvas.draw_idle()

    def _accept_result(self):
        """采用当前结果并关闭弹窗。"""
        if self.result_payload:
            self.accept()
