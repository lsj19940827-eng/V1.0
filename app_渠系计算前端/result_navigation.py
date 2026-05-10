# -*- coding: utf-8 -*-
"""Shared multi-case result navigation helpers."""

from __future__ import annotations

import html as html_mod
import re
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _e(value) -> str:
    return html_mod.escape(str(value))


def collect_case_result_state(panel) -> dict:
    """收集多工况结果有效性状态，供项目文件保存。"""
    stale_indexes = getattr(panel, "_stale_result_case_indexes", set()) or set()
    normalized_indexes = []
    for idx in stale_indexes:
        try:
            normalized_indexes.append(int(idx))
        except (TypeError, ValueError):
            continue
    return {
        "results_dirty": bool(getattr(panel, "_results_dirty", False)),
        "stale_result_case_indexes": sorted(set(normalized_indexes)),
        "all_results_stale": bool(getattr(panel, "_all_results_stale", False)),
        "has_rendered_results": bool(getattr(panel, "_has_rendered_results", False)),
    }


def apply_case_result_state(panel, state) -> None:
    """恢复多工况结果有效性状态，需在结果重新渲染后调用。"""
    if not isinstance(state, dict):
        return

    stale_indexes = set()
    for idx in state.get("stale_result_case_indexes", []) or []:
        try:
            stale_indexes.add(int(idx))
        except (TypeError, ValueError):
            continue

    panel._results_dirty = bool(state.get("results_dirty", False))
    panel._stale_result_case_indexes = stale_indexes
    panel._all_results_stale = bool(state.get("all_results_stale", False))
    panel._has_rendered_results = bool(state.get("has_rendered_results", False))


_CASE_NAV_BAR_SS = """
QWidget#codexCaseResultNavBar {
    background: transparent;
}
QFrame#codexCaseResultNavCard {
    background: #FFFFFF;
    border: 1px solid #E0E7EF;
    border-radius: 12px;
}
QLabel#codexCaseResultNavTitle {
    font-size: 12px;
    color: #6B7A90;
    font-weight: 700;
    padding-right: 4px;
}
"""

_CASE_NAV_CHIP_BASE_SS = (
    "QPushButton{{"
    "border:1.5px solid {border};"
    "border-radius:18px;"
    "background:{bg};"
    "color:{fg};"
    "font-size:13px;"
    "font-weight:700;"
    "padding:6px 14px;"
    "text-align:center;"
    "}}"
    "QPushButton:hover{{background:{hover};}}"
    "QPushButton:pressed{{background:{pressed};}}"
)

_CASE_NAV_TOGGLE_SS = (
    "QPushButton{padding:4px 8px;border:none;background:transparent;"
    "color:#1565C0;font-size:12px;font-weight:700;text-align:right;}"
    "QPushButton:hover{color:#0E5DB8;text-decoration:underline;}"
)
_CASE_NAV_COLLAPSED_ROWS = 2
_CASE_NAV_EXPANDED_ROWS = 4
_Q_TEXT_RE = re.compile(r"Q\s*=\s*([+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+\-]?\d+)?|\?)")


def _extract_q_text(*texts) -> str:
    """从标签或摘要中提取 Q 文本。"""
    for text in texts:
        match = _Q_TEXT_RE.search(str(text or ""))
        if match:
            return f"Q={match.group(1)}"
    return ""


def _compact_case_nav_text(case_idx: int, label: str, summary: str, *, is_error: bool = False) -> str:
    """生成结果区紧凑工况标签，避免重复显示断面类型。"""
    title = f"工况{int(case_idx) + 1}"
    if is_error:
        detail = "计算失败"
    else:
        detail = _extract_q_text(summary, label)
        if not detail:
            detail = str(summary or label or "").strip()
    return f"{title}  {detail}" if detail else title


def _normalize_q_value_for_compare(raw: str) -> str:
    """规范化 Q 数值文本，用于识别只差小数位的重复提示。"""
    raw = str(raw or "").strip()
    if raw == "?":
        return "?"
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return raw
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _tooltip_compare_key(text: str) -> str:
    """生成 tooltip 去重比较键，忽略 Q 的无意义小数位。"""
    text = str(text or "").strip()
    return _Q_TEXT_RE.sub(
        lambda match: f"Q={_normalize_q_value_for_compare(match.group(1))}",
        text,
    )


def _case_nav_tooltip_text(label: str, summary: str) -> str:
    """生成结果导航提示，避免 label 和 summary 重复显示同一 Q 信息。"""
    label_text = str(label or "").strip()
    summary_text = str(summary or "").strip()
    if not summary_text:
        return label_text
    if not label_text:
        return summary_text
    if _tooltip_compare_key(label_text) == _tooltip_compare_key(summary_text):
        return summary_text
    return f"{label_text}\n{summary_text}"


class CaseResultNavChip(QPushButton):
    """Desktop-native case navigation chip."""

    case_requested = Signal(int)

    def __init__(self, case_idx: int, label: str, *, summary: str = "",
                 is_error: bool = False, parent=None):
        super().__init__(parent)
        self.case_idx = int(case_idx)
        self.setProperty("resultNavError", bool(is_error))
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        summary_text = str(summary or "").strip()
        label_text = str(label or "").strip() or f"工况 {self.case_idx + 1}"
        display_text = _compact_case_nav_text(
            self.case_idx,
            label_text,
            summary_text,
            is_error=bool(is_error),
        )
        self.setText(display_text)
        self.setToolTip(_case_nav_tooltip_text(label_text, summary_text))
        if is_error:
            self.setStyleSheet(
                _CASE_NAV_CHIP_BASE_SS.format(
                    border="#C62828",
                    bg="#FFFFFF",
                    fg="#C62828",
                    hover="#FFF4F4",
                    pressed="#FDECEC",
                )
            )
        else:
            self.setStyleSheet(
                _CASE_NAV_CHIP_BASE_SS.format(
                    border="#1565C0",
                    bg="#FFFFFF",
                    fg="#1565C0",
                    hover="#F1F7FF",
                    pressed="#EAF3FF",
                )
            )
        self.clicked.connect(self._emit_case_requested)

    def _emit_case_requested(self):
        self.case_requested.emit(self.case_idx)


class _CaseNavChipWrap(QWidget):
    """Wrap chips across multiple rows without relying on the shared FlowLayout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._chips = []
        self._horizontal_spacing = 8
        self._vertical_spacing = 8
        self.setContentsMargins(0, 0, 0, 0)

    def clear_chips(self):
        self._chips = []
        for widget in self.findChildren(CaseResultNavChip):
            widget.hide()
        self.updateGeometry()

    def set_chips(self, chips):
        self._chips = list(chips or [])
        self._relayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def row_count_for_width(self, width=None) -> int:
        """按给定宽度计算标签需要的行数。"""
        chips = [chip for chip in self._chips if chip is not None]
        if not chips:
            return 0
        spacing = max(0, self._horizontal_spacing)
        available_width = max(1, int(width or self.contentsRect().width()))
        current_width = 0
        row_count = 1
        for chip in chips:
            chip_width = self._chip_width(chip)
            required_width = chip_width if current_width == 0 else chip_width + spacing
            if current_width > 0 and current_width + required_width > available_width:
                row_count += 1
                current_width = chip_width
            else:
                current_width = chip_width if current_width == 0 else current_width + required_width
        return row_count

    def height_for_rows(self, row_count: int) -> int:
        """按行数估算导航标签区高度。"""
        chips = [chip for chip in self._chips if chip is not None]
        chip_height = max((chip.sizeHint().height() for chip in chips), default=34)
        spacing = max(0, self._vertical_spacing)
        margins = self.contentsMargins()
        rows = max(0, int(row_count))
        if rows <= 0:
            return margins.top() + margins.bottom()
        return (
            margins.top()
            + margins.bottom()
            + rows * chip_height
            + max(0, rows - 1) * spacing
        )

    def _chip_width(self, chip) -> int:
        """返回标签需要的真实宽度，避免布局压缩导致中文边缘被裁切。"""
        return max(chip.minimumSizeHint().width(), chip.sizeHint().width())

    def _chip_height(self, chip) -> int:
        """返回标签需要的真实高度。"""
        return max(chip.minimumSizeHint().height(), chip.sizeHint().height())

    def _relayout(self, width=None):
        if not self._chips:
            self.updateGeometry()
            return

        h_spacing = max(0, self._horizontal_spacing)
        v_spacing = max(0, self._vertical_spacing)
        margins = self.contentsMargins()
        available_width = max(1, int(width or self.contentsRect().width()))
        row_start_x = margins.left()
        row_y = margins.top()
        right_limit = max(row_start_x + 1, available_width - margins.right())
        current_width = 0
        row_height = 0

        for chip in self._chips:
            chip.show()
            chip_width = self._chip_width(chip)
            chip_height = self._chip_height(chip)
            required_width = chip_width if current_width == 0 else chip_width + h_spacing
            if current_width > 0 and row_start_x + current_width + required_width > right_limit:
                row_y += row_height + v_spacing
                current_width = 0
                row_height = 0
                required_width = chip_width

            x = row_start_x + current_width + (h_spacing if current_width > 0 else 0)
            chip.setGeometry(x, row_y, chip_width, chip_height)
            current_width += required_width
            row_height = max(row_height, chip_height)

        self.updateGeometry()


class CaseResultNavigationBar(QWidget):
    """Desktop-native fixed case navigation bar shown above result views."""

    case_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._chips = []
        self._items = []
        self._height_sync_pending = False
        self._syncing_height = False
        self._expanded = False
        self._can_collapse = False
        self.setObjectName("codexCaseResultNavBar")
        self.setStyleSheet(_CASE_NAV_BAR_SS)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._card = QFrame(self)
        self._card.setObjectName("codexCaseResultNavCard")
        self._card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        outer.addWidget(self._card)

        row = QHBoxLayout(self._card)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(8)

        self._title_label = QLabel("工况快捷导航", self._card)
        self._title_label.setObjectName("codexCaseResultNavTitle")
        self._title_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        row.addWidget(self._title_label, 0, Qt.AlignTop)

        self._chip_scroll = QScrollArea(self._card)
        self._chip_scroll.setWidgetResizable(False)
        self._chip_scroll.setFrameShape(QFrame.NoFrame)
        self._chip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._chip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._chip_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._chip_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea > QWidget > QWidget{background:transparent;}"
        )
        self._chip_scroll.viewport().installEventFilter(self)

        self._chip_host = _CaseNavChipWrap()
        self._chip_host.setAutoFillBackground(False)
        self._chip_scroll.setWidget(self._chip_host)
        row.addWidget(self._chip_scroll, 1, Qt.AlignTop)

        self._toggle_button = QPushButton("展开", self._card)
        self._toggle_button.setCursor(Qt.PointingHandCursor)
        self._toggle_button.setStyleSheet(_CASE_NAV_TOGGLE_SS)
        self._toggle_button.clicked.connect(self._toggle_expanded)
        self._toggle_button.hide()
        row.addWidget(self._toggle_button, 0, Qt.AlignTop)

        self.hide()

    def chips(self):
        return list(self._chips)

    def chip_count(self) -> int:
        return len(self._chips)

    def items(self):
        return list(self._items)

    def clear_items(self):
        self._items = []
        self._chips = []
        self._expanded = False
        self._can_collapse = False
        self._toggle_button.hide()
        self._chip_host.clear_chips()
        self._reset_height_constraints()
        self.hide()

    def set_items(self, items, *, title: str = "工况快捷导航"):
        normalized = list(items or [])
        self.clear_items()
        self._title_label.setText(str(title or "工况快捷导航"))
        self._items = normalized
        if len(normalized) <= 1:
            return

        for order_idx, item in enumerate(normalized):
            case_idx = item.get("case_idx")
            if case_idx is None:
                case_idx = order_idx
            chip = CaseResultNavChip(
                case_idx,
                item.get("label", ""),
                summary=item.get("summary", ""),
                is_error=bool(item.get("is_error", False)),
                parent=self._chip_host,
            )
            chip.case_requested.connect(self.case_requested.emit)
            self._chips.append(chip)

        self._chip_host.set_chips(self._chips)
        self.show()
        self._schedule_height_sync()

    def is_expanded(self) -> bool:
        """返回结果导航是否处于展开状态。"""
        return bool(self._expanded)

    def can_collapse(self) -> bool:
        """返回结果导航是否需要折叠。"""
        return bool(self._can_collapse)

    def set_expanded(self, expanded):
        """切换结果导航展开状态。"""
        self._expanded = bool(expanded)
        self._schedule_height_sync()

    def _toggle_expanded(self):
        self.set_expanded(not self._expanded)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._chips and self.isVisible():
            self._schedule_height_sync()

    def showEvent(self, event):
        super().showEvent(event)
        if self._chips:
            self._schedule_height_sync()
            QTimer.singleShot(0, self._schedule_height_sync)

    def eventFilter(self, obj, event):
        if (
            obj is self._chip_scroll.viewport()
            and event.type() in (QEvent.Resize, QEvent.Show)
            and self._chips
            and self.isVisible()
        ):
            self._schedule_height_sync()
        return super().eventFilter(obj, event)

    def _schedule_height_sync(self):
        if self._height_sync_pending:
            return
        self._height_sync_pending = True
        QTimer.singleShot(0, self._sync_height_to_contents)

    def _sync_height_to_contents(self):
        self._height_sync_pending = False
        if self._syncing_height:
            return
        if not self._chips:
            self._reset_height_constraints()
            return

        self._syncing_height = True
        try:
            toggle_was_visible = self._toggle_button.isVisible()
            self._toggle_button.setVisible(self._can_collapse)
            self._card.layout().activate()
            self.layout().activate()

            chip_width = max(1, self._chip_scroll.viewport().width())
            if chip_width <= 1:
                margins = self._card.layout().contentsMargins()
                chip_width = max(
                    1,
                    self.width()
                    - margins.left()
                    - margins.right()
                    - self._title_label.sizeHint().width()
                    - self._toggle_button.sizeHint().width()
                    - 24,
                )

            self._chip_host.setFixedWidth(chip_width)
            self._chip_host._relayout(chip_width)
            total_rows = self._chip_host.row_count_for_width(chip_width)
            self._can_collapse = total_rows > _CASE_NAV_COLLAPSED_ROWS
            if not self._can_collapse:
                self._expanded = False

            visible_rows = total_rows
            if self._can_collapse:
                row_limit = _CASE_NAV_EXPANDED_ROWS if self._expanded else _CASE_NAV_COLLAPSED_ROWS
                visible_rows = min(total_rows, row_limit)

            content_height = self._chip_host.height_for_rows(total_rows)
            viewport_height = self._chip_host.height_for_rows(visible_rows)
            self._chip_host.setFixedSize(chip_width, max(content_height, viewport_height))
            self._chip_scroll.setFixedHeight(viewport_height)
            self._chip_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarAsNeeded if total_rows > visible_rows else Qt.ScrollBarAlwaysOff
            )
            self._toggle_button.setVisible(self._can_collapse)
            self._toggle_button.setText("收起" if self._expanded else "展开")

            self._card.layout().activate()
            self.layout().activate()
            target_height = max(self.minimumSizeHint().height(), self.sizeHint().height())
            if target_height <= 0:
                return
            if self.minimumHeight() != target_height or self.maximumHeight() != target_height:
                self.setFixedHeight(target_height)
                self.updateGeometry()
            final_viewport_width = max(1, self._chip_scroll.viewport().width())
            if toggle_was_visible != self._toggle_button.isVisible() or abs(final_viewport_width - chip_width) > 2:
                self._schedule_height_sync()
        finally:
            self._syncing_height = False

    def _reset_height_constraints(self):
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self._chip_scroll.setMinimumHeight(0)
        self._chip_scroll.setMaximumHeight(16777215)


def sync_case_result_nav_bar(bar, items, *, title: str = "工况快捷导航"):
    """Update a desktop-native case result nav bar when present."""
    if bar is None:
        return
    try:
        bar.set_items(items, title=title)
    except Exception:
        return


def _normalize_case_index(value):
    """把工况序号统一成 int，无法识别时返回 None。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stale_case_index_set(stale_case_indexes):
    """把过期工况集合统一成 int 集合。"""
    if stale_case_indexes is None:
        return None
    normalized = set()
    for idx in stale_case_indexes:
        case_idx = _normalize_case_index(idx)
        if case_idx is not None:
            normalized.add(case_idx)
    return normalized


def case_result_exists(all_results, case_idx) -> bool:
    """判断目标工况是否有已渲染过的结果入口。"""
    target_idx = _normalize_case_index(case_idx)
    if target_idx is None:
        return False
    for fallback_idx, item in enumerate(all_results or []):
        item_idx = None
        if isinstance(item, (tuple, list)) and item:
            item_idx = _normalize_case_index(item[0])
        if item_idx is None:
            item_idx = fallback_idx
        if item_idx == target_idx:
            return True
    return False


def is_case_result_stale(
    *,
    case_idx,
    results_dirty,
    stale_case_indexes=None,
    all_results_stale=False,
) -> bool:
    """判断目标工况结果是否过期。"""
    if bool(all_results_stale):
        return True
    if not bool(results_dirty):
        return False
    stale_indexes = _stale_case_index_set(stale_case_indexes)
    if stale_indexes is None:
        return bool(results_dirty)
    target_idx = _normalize_case_index(case_idx)
    return target_idx in stale_indexes


def has_fresh_case_results(
    *,
    all_results,
    has_rendered_results,
    results_dirty,
    case_idx=None,
    stale_case_indexes=None,
    all_results_stale=False,
) -> bool:
    """判断当前结果是否仍可用于自动定位。"""
    if not bool(all_results) or not bool(has_rendered_results):
        return False
    if case_idx is None:
        return not bool(results_dirty) and not bool(all_results_stale)
    if not case_result_exists(all_results, case_idx):
        return False
    return not is_case_result_stale(
        case_idx=case_idx,
        results_dirty=results_dirty,
        stale_case_indexes=stale_case_indexes,
        all_results_stale=all_results_stale,
    )


def case_result_jump_hint(*, stale: bool = False, reason: str | None = None):
    """返回结果导航无法跳转时的统一提示。"""
    hint_reason = reason or ("case_stale" if stale else "empty")
    if hint_reason == "structure_stale":
        return (
            "结果已失效",
            "工况已删除，原计算结果与当前工况序号可能不一致。请执行计算后再查看计算结果。",
        )
    if hint_reason == "case_stale":
        return (
            "结果已过期",
            "因当前工况参数被修改，致使计算结果过期。请执行计算后再查看计算结果。",
        )
    return (
        "暂无计算结果",
        "当前没有可定位的计算结果，请先完成计算。",
    )


def make_case_result_anchor(panel_key: str, case_idx: int) -> str:
    """Build a stable HTML anchor id for a case result block."""
    safe_key = re.sub(r"[^a-z0-9_-]+", "-", str(panel_key or "").lower()).strip("-") or "panel"
    safe_idx = max(0, int(case_idx))
    return f"case-result-{safe_key}-{safe_idx}"


def build_result_navigation_head() -> str:
    """Return shared CSS/JS used by multi-case result pages."""
    return """
<style>
.codex-case-nav {
    display:flex;
    gap:8px;
    align-items:center;
    flex-wrap:wrap;
    margin:0 0 16px 0;
    padding:10px 16px;
    background:#FFFFFF;
    border:1px solid #E0E7EF;
    border-radius:12px;
    box-shadow:0 1px 4px rgba(0,0,0,0.06);
}
.codex-case-nav--hidden {
    display:none !important;
}
.codex-case-nav__title {
    font-size:12px;
    color:#6B7A90;
    font-weight:600;
    margin-right:4px;
}
.codex-case-nav__link {
    display:inline-flex;
    align-items:center;
    gap:6px;
    padding:6px 14px;
    border:1.5px solid #1565C0;
    border-radius:20px;
    background:#FFFFFF;
    color:#1565C0;
    font-size:13px;
    font-weight:700;
    cursor:pointer;
    text-decoration:none;
    transition:background 0.15s ease, transform 0.15s ease;
}
.codex-case-nav__link:hover {
    background:#F1F7FF;
    transform:translateY(-1px);
}
.codex-case-nav__badge {
    font-size:11px;
    font-weight:600;
    padding:1px 8px;
    border-radius:9px;
}
.codex-case-block {
    position:relative;
    margin:0 0 22px 0;
    padding:12px 14px 10px 14px;
    border-radius:14px;
    background:linear-gradient(180deg,#FFFFFF,#FBFDFF);
    border:1px solid #DFE7F1;
    box-shadow:0 2px 6px rgba(0,0,0,0.04);
    scroll-margin-top:16px;
}
.codex-case-block--error {
    border-color:#F1B7B7;
    background:linear-gradient(180deg,#FFFFFF,#FFF7F7);
}
.codex-case-block__header {
    display:flex;
    align-items:center;
    gap:10px;
    flex-wrap:wrap;
    margin:0 0 12px 0;
    padding:10px 14px;
    border-radius:12px;
    background:linear-gradient(135deg,#EAF3FF,#F4F8FF);
    border-left:4px solid #1565C0;
}
.codex-case-block--error .codex-case-block__header {
    background:linear-gradient(135deg,#FFF0F0,#FFF8F8);
    border-left-color:#C62828;
}
.codex-case-block__title {
    font-size:15px;
    font-weight:800;
    color:#1565C0;
}
.codex-case-block--error .codex-case-block__title {
    color:#C62828;
}
.codex-case-block__subtitle {
    font-size:13px;
    font-weight:500;
    color:#4E5D71;
}
.codex-case-block--flash {
    animation:codex-case-flash 1.6s ease-out 1;
}
@keyframes codex-case-flash {
    0% {
        box-shadow:0 0 0 0 rgba(21,101,192,0.38);
        background:linear-gradient(180deg,#FFFDF0,#FFFFFF);
    }
    35% {
        box-shadow:0 0 0 4px rgba(21,101,192,0.16);
        background:linear-gradient(180deg,#FFF6C9,#FFFFFF);
    }
    100% {
        box-shadow:0 2px 6px rgba(0,0,0,0.04);
        background:linear-gradient(180deg,#FFFFFF,#FBFDFF);
    }
}
</style>
<script>
(function() {
    if (window.codexJumpToCase) {
        return;
    }
    window.codexFlashCase = function(anchorId) {
        var block = document.getElementById(anchorId);
        if (!block) {
            return false;
        }
        block.classList.remove('codex-case-block--flash');
        void block.offsetWidth;
        block.classList.add('codex-case-block--flash');
        window.setTimeout(function() {
            block.classList.remove('codex-case-block--flash');
        }, 1700);
        return true;
    };
    window.codexJumpToCase = function(anchorId) {
        var block = document.getElementById(anchorId);
        if (!block) {
            return false;
        }
        try {
            block.scrollIntoView({behavior: 'smooth', block: 'start'});
        } catch (error) {
            block.scrollIntoView(true);
        }
        window.codexFlashCase(anchorId);
        return false;
    };
})();
</script>
"""
def build_result_nav_bar(items, title: str = "工况快捷导航", hidden: bool = False) -> str:
    """Build a shared top navigation bar for multi-case result pages."""
    if not items or len(items) <= 1:
        return ""

    nav_cls = "codex-case-nav codex-case-nav--hidden" if hidden else "codex-case-nav"
    parts = [f'<div class="{nav_cls}">', f'<span class="codex-case-nav__title">{_e(title)}</span>']
    for order_idx, item in enumerate(items):
        anchor_id = item["anchor_id"]
        label = item["label"]
        summary = str(item.get("summary", "") or "").strip()
        is_error = bool(item.get("is_error", False))
        case_idx = item.get("case_idx", order_idx)
        display_text = _compact_case_nav_text(case_idx, label, summary, is_error=is_error)
        accent = "#C62828" if is_error else "#1565C0"
        parts.append(
            f'<a class="codex-case-nav__link" href="#{_e(anchor_id)}" '
            f'onclick="return window.codexJumpToCase(\'{_e(anchor_id)}\');" '
            f'style="border-color:{accent};color:{accent};">'
            f'<span>{_e(display_text)}</span>'
        )
        parts.append("</a>")
    parts.append("</div>")
    return "".join(parts)


def wrap_case_result_block(
    panel_key: str,
    case_idx: int,
    title_text: str,
    body_html: str,
    *,
    subtitle: str = "",
    is_error: bool = False,
) -> str:
    """Wrap case content in a shared anchor-aware result card."""
    anchor_id = make_case_result_anchor(panel_key, case_idx)
    block_cls = "codex-case-block codex-case-block--error" if is_error else "codex-case-block"
    subtitle_html = (
        f'<span class="codex-case-block__subtitle">{_e(subtitle)}</span>' if subtitle else ""
    )
    return (
        f'<div id="{_e(anchor_id)}" class="{block_cls}" data-case-index="{int(case_idx)}">'
        f'<a name="{_e(anchor_id)}"></a>'
        f'<div class="codex-case-block__header">'
        f'<span class="codex-case-block__title">{_e(title_text)}</span>'
        f"{subtitle_html}"
        f"</div>"
        f"{body_html}"
        f"</div>"
    )
