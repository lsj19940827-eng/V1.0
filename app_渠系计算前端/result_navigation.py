# -*- coding: utf-8 -*-
"""Shared multi-case result navigation helpers."""

from __future__ import annotations

import html as html_mod
import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _e(value) -> str:
    return html_mod.escape(str(value))


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
        if summary_text:
            self.setText(f"{label_text}  {summary_text}")
            self.setToolTip(f"{label_text}\n{summary_text}")
        else:
            self.setText(label_text)
            self.setToolTip(label_text)
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
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(8)

    def clear_chips(self):
        self._chips = []
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
        self.updateGeometry()

    def set_chips(self, chips):
        self._chips = list(chips or [])
        self._relayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        while self._grid.count():
            self._grid.takeAt(0)

        if not self._chips:
            self.updateGeometry()
            return

        spacing = max(0, self._grid.horizontalSpacing())
        available_width = max(1, self.contentsRect().width())
        current_width = 0
        row = 0
        column = 0

        for chip in self._chips:
            chip_width = max(chip.minimumSizeHint().width(), chip.sizeHint().width())
            required_width = chip_width if column == 0 else chip_width + spacing
            if column > 0 and current_width + required_width > available_width:
                row += 1
                column = 0
                current_width = 0
                required_width = chip_width
            self._grid.addWidget(chip, row, column, Qt.AlignLeft | Qt.AlignVCenter)
            current_width += required_width
            column += 1

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

        self._chip_host = _CaseNavChipWrap(self._card)
        self._chip_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(self._chip_host, 1, Qt.AlignTop)

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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._chips and self.isVisible():
            self._schedule_height_sync()

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
            self._chip_host._relayout()
            self._card.layout().activate()
            self.layout().activate()
            target_height = max(self.minimumSizeHint().height(), self.sizeHint().height())
            if target_height <= 0:
                return
            if self.minimumHeight() != target_height or self.maximumHeight() != target_height:
                self.setFixedHeight(target_height)
                self.updateGeometry()
        finally:
            self._syncing_height = False

    def _reset_height_constraints(self):
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)


def sync_case_result_nav_bar(bar, items, *, title: str = "工况快捷导航"):
    """Update a desktop-native case result nav bar when present."""
    if bar is None:
        return
    try:
        bar.set_items(items, title=title)
    except Exception:
        return


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
    for item in items:
        anchor_id = item["anchor_id"]
        label = item["label"]
        summary = str(item.get("summary", "") or "").strip()
        is_error = bool(item.get("is_error", False))
        accent = "#C62828" if is_error else "#1565C0"
        badge_bg = "#FDECEC" if is_error else "#EAF3FF"
        badge_fg = "#C62828" if is_error else "#1565C0"
        parts.append(
            f'<a class="codex-case-nav__link" href="#{_e(anchor_id)}" '
            f'onclick="return window.codexJumpToCase(\'{_e(anchor_id)}\');" '
            f'style="border-color:{accent};color:{accent};">'
            f'<span>{_e(label)}</span>'
        )
        if summary:
            parts.append(
                f'<span class="codex-case-nav__badge" style="background:{badge_bg};color:{badge_fg};">'
                f'{_e(summary)}</span>'
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
