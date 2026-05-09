# -*- coding: utf-8 -*-
"""
Shared multi-case UI helpers.

This module provides the reusable case tag chip, wrapping flow layout,
rename dialog, and external case workbench used across the desktop panels.
"""

from PySide6.QtCore import Qt, QRect, QPoint, QSize, Signal, QEvent, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QFontMetrics
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


MAX_CASES = 30

_SUB = "₀₁₂₃₄₅₆₇₈₉"


def _sub(n):
    """Convert digits to unicode subscripts, for example 12 -> ₁₂."""
    return "".join(_SUB[int(d)] for d in str(n))


CASE_TAG_ACTIVE_SS = (
    "QPushButton{background:#F2F7FF;border:1px solid #B8D1EF;border-radius:14px;"
    "color:#0E5DB8;font-size:12px;font-weight:700;padding:0 14px;text-align:center;}"
    "QPushButton:hover{background:#EAF3FF;border-color:#89B2E0;}"
)
CASE_TAG_INACTIVE_SS = (
    "QPushButton{background:#FFFFFF;border:1px solid #D7E1ED;border-radius:14px;"
    "color:#42566F;font-size:12px;font-weight:600;padding:0 14px;text-align:center;}"
    "QPushButton:hover{background:#F7FAFD;border-color:#AFC5DD;color:#244C73;}"
)
CASE_QUICK_SS = (
    "QPushButton{min-height:34px;padding:4px 14px;border:1px solid #D6E0EC;border-radius:10px;"
    "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #FFFFFF,stop:1 #F7FAFD);"
    "font-size:11px;color:#41566F;font-weight:600;}"
    "QPushButton:hover{border-color:#9FBEDE;color:#0E5DB8;background:#F1F7FF;}"
    "QPushButton:disabled{color:#9FA9B5;background:#F7F8FA;border-color:#E3E7ED;}"
)
CASE_TOGGLE_SS = (
    "QPushButton{padding:0 4px;border:none;background:transparent;"
    "color:#0E5DB8;font-size:11px;font-weight:600;text-align:right;}"
    "QPushButton:hover{color:#106ebe;text-decoration:underline;}"
)
CASE_META_LABEL_SS = "font-size:11px;color:#6B7A90;font-weight:600;"
CASE_STRIP_SS = (
    "QWidget#caseWorkbenchStrip{background:#FAFCFF;border:1px solid #E4EBF3;border-radius:14px;}"
)


class FlowLayout(QLayout):
    """A simple wrapping flow layout."""

    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing

    def addItem(self, item):
        self._items.append(item)
        self.invalidate()

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            item = self._items.pop(index)
            self.invalidate()
            return item
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
            widget = item.widget()
            if widget is not None and not widget.isVisible():
                continue
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        right = effective.x() + effective.width()

        for item in self._items:
            widget = item.widget()
            if widget is not None and not widget.isVisible():
                continue

            item_size = item.sizeHint()
            next_x = x + item_size.width()
            if next_x > right and line_height > 0:
                x = effective.x()
                y += line_height + self._spacing
                line_height = 0
                next_x = x + item_size.width()

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))

            x = next_x + self._spacing
            line_height = max(line_height, item_size.height())

        return y + line_height - rect.y() + margins.bottom()


class RenameDialog(QDialog):
    """A small rename dialog used for case chips."""

    def __init__(self, title, label, default_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        prompt_label = QLabel(label)
        prompt_label.setStyleSheet("font-size:13px;color:#333;")
        layout.addWidget(prompt_label)

        self.line_edit = QLineEdit(default_text)
        self.line_edit.setMinimumWidth(280)
        self.line_edit.setStyleSheet(
            "QLineEdit{padding:8px 10px;border:1px solid #ccc;border-radius:4px;font-size:13px;}"
            "QLineEdit:focus{border-color:#0078d4;}"
        )
        self.line_edit.selectAll()
        layout.addWidget(self.line_edit)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addStretch()

        self.ok_btn = QPushButton("确定")
        self.ok_btn.setFixedSize(80, 32)
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        self.ok_btn.setStyleSheet(
            "QPushButton{background:#0078d4;color:white;border:none;border-radius:4px;font-size:13px;font-weight:500;}"
            "QPushButton:hover{background:#106ebe;}"
            "QPushButton:pressed{background:#005a9e;}"
        )
        self.ok_btn.clicked.connect(self.accept)
        button_row.addWidget(self.ok_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedSize(80, 32)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setStyleSheet(
            "QPushButton{background:#f0f0f0;color:#333;border:1px solid #ccc;border-radius:4px;font-size:13px;}"
            "QPushButton:hover{background:#e5e5e5;border-color:#999;}"
            "QPushButton:pressed{background:#d5d5d5;}"
        )
        self.cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_btn)

        layout.addLayout(button_row)

        self.adjustSize()
        self.setMinimumWidth(max(320, self.sizeHint().width()))

    def text(self):
        return self.line_edit.text()

    @staticmethod
    def getText(parent, title, label, default_text=""):
        dialog = RenameDialog(title, label, default_text, parent)
        if parent:
            top_parent = parent.window() if hasattr(parent, "window") else parent
            if top_parent:
                parent_geo = top_parent.geometry()
                dialog_size = dialog.sizeHint()
                x = parent_geo.x() + (parent_geo.width() - dialog_size.width()) // 2
                y = parent_geo.y() + (parent_geo.height() - dialog_size.height()) // 2
                dialog.move(x, y)

        result = dialog.exec()
        return dialog.text(), result == QDialog.Accepted


class CaseTagChip(QPushButton):
    """Compact single-line chip that favors overview density."""

    switched = Signal(int)
    renamed = Signal(int, str)

    def __init__(self, index, label_text, active=False, parent=None):
        super().__init__(label_text, parent)
        self.case_index = index
        self._label_text = ""
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFlat(True)
        self.setFixedHeight(32)
        self.setMinimumWidth(84)
        self.setMaximumWidth(184)

        self.set_case_view({"label": label_text})
        self.set_active(active)
        self.clicked.connect(lambda: self.switched.emit(self.case_index))

    def set_case_index(self, index):
        self.case_index = index

    def label_text(self):
        return self._label_text

    def set_case_view(self, view):
        label = str(view.get("label", "") or "")
        tooltip = str(view.get("tooltip", "") or label)
        width = self._preferred_width(label)
        self._label_text = label
        self.setFixedWidth(width)
        self.setText(self._elided_label(label, width))
        self.setToolTip(tooltip)
        self.updateGeometry()

    def set_active(self, active):
        self.setStyleSheet(CASE_TAG_ACTIVE_SS if active else CASE_TAG_INACTIVE_SS)

    def _preferred_width(self, label):
        metrics = QFontMetrics(self.font())
        natural = metrics.horizontalAdvance(label) + 28
        return max(self.minimumWidth(), min(self.maximumWidth(), natural))

    def _elided_label(self, label, width):
        metrics = QFontMetrics(self.font())
        return metrics.elidedText(label, Qt.ElideRight, max(24, width - 28))

    def mouseDoubleClickEvent(self, event):
        text, ok = RenameDialog.getText(
            self,
            "重命名工况",
            "请输入工况名称:",
            self._label_text,
        )
        if ok and text.strip():
            self.renamed.emit(self.case_index, text.strip())


class DashedButton(QPushButton):
    """Dashed rounded button used for the add-case affordance."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._hovered = False
        self.setMouseTracking(True)
        self.setStyleSheet(
            "QPushButton{background:transparent;border:none;color:#7B8794;font-size:12px;font-weight:600;padding:4px 12px;}"
        )

    def enterEvent(self, event):
        self._hovered = True
        self.setStyleSheet(
            "QPushButton{background:#F1F7FF;border:none;color:#0E5DB8;font-size:12px;font-weight:600;padding:4px 12px;}"
        )
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.setStyleSheet(
            "QPushButton{background:transparent;border:none;color:#7B8794;font-size:12px;font-weight:600;padding:4px 12px;}"
        )
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#7FAAD7") if self._hovered else QColor("#CBD5E1"))
        pen.setStyle(Qt.DashLine)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)
        painter.end()


class CaseTagNavigator(QWidget):
    """Wrapped case overview that keeps all cases visible before scrolling."""

    add_requested = Signal()
    case_switched = Signal(int)
    case_renamed = Signal(int, str)
    expanded_changed = Signal(bool)
    view_state_changed = Signal()

    def __init__(self, collapsed_rows=3, parent=None):
        super().__init__(parent)
        self._collapsed_rows = max(1, collapsed_rows)
        self._expanded = False
        self._current_index = -1
        self._chips = []
        self._sync_pending = False
        self._can_collapse = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._content = QWidget(self)
        self._flow = FlowLayout(self._content, spacing=6)
        self._flow.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._content)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_sync()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_sync()

    def event(self, event):
        if event.type() == QEvent.LayoutRequest:
            self._schedule_sync()
        return super().event(event)

    def sync_cases(self, cases, current_index, view_getter):
        target_count = len(cases)
        chips_changed = False
        while len(self._chips) > target_count:
            chip = self._chips.pop()
            self._remove_chip(chip)
            chips_changed = True
        while len(self._chips) < target_count:
            chip = CaseTagChip(len(self._chips), "", active=False, parent=self._content)
            chip.switched.connect(self.case_switched.emit)
            chip.renamed.connect(self.case_renamed.emit)
            self._flow.addWidget(chip)
            self._chips.append(chip)
            chips_changed = True

        self._current_index = current_index if 0 <= current_index < target_count else -1

        for idx, case_data in enumerate(cases):
            chip = self._chips[idx]
            view = self._normalize_case_view(view_getter(case_data, idx), idx)
            chip.set_case_index(idx)
            chip.set_case_view(view)
            chip.set_active(idx == self._current_index)

        if chips_changed:
            self._flow.invalidate()
        self._content.updateGeometry()
        self._sync_flow_geometry()
        self._schedule_sync()

    def case_labels(self):
        return [chip.label_text() for chip in self._chips]

    def chip_count(self):
        return len(self._chips)

    def is_expanded(self):
        return self._expanded

    def can_collapse(self):
        return self._can_collapse

    def set_expanded(self, expanded):
        expanded = bool(expanded)
        if self._expanded != expanded:
            self._expanded = expanded
            self.expanded_changed.emit(self._expanded)
        self._schedule_sync()

    def _remove_chip(self, chip):
        chip.setParent(None)
        chip.deleteLater()

    @staticmethod
    def _normalize_case_view(raw_view, idx):
        if isinstance(raw_view, dict):
            view = dict(raw_view)
        else:
            view = {"label": str(raw_view or "")}

        label = str(view.get("label", "") or "")
        if not label:
            title = str(view.get("title", "") or f"工况 {idx + 1}")
            subtitle = str(view.get("subtitle", "") or "")
            label = f"{title} · {subtitle}" if subtitle else title

        tooltip = str(view.get("tooltip", "") or label)
        return {"label": label, "tooltip": tooltip}

    def _row_count(self, width):
        chips = [chip for chip in self._chips if chip.isVisible()]
        if not chips:
            return 0

        margins = self._flow.contentsMargins()
        available_width = max(1, width - margins.left() - margins.right())
        spacing = 6
        row_count = 1
        row_width = 0

        for chip in chips:
            chip_width = chip.sizeHint().width()
            if row_width and row_width + spacing + chip_width > available_width:
                row_count += 1
                row_width = chip_width
            else:
                row_width = chip_width if not row_width else row_width + spacing + chip_width

        return row_count

    def _content_height_for_width(self, width):
        return self._flow.heightForWidth(max(1, width))

    def _sync_flow_geometry(self):
        rect = self._content.contentsRect()
        if rect.width() <= 0:
            rect = QRect(0, 0, max(1, self.contentsRect().width()), max(1, self._content.height()))
        self._flow.invalidate()
        self._flow.setGeometry(rect)
        self._flow.activate()

    def _schedule_sync(self):
        if self._sync_pending:
            return
        self._sync_pending = True
        QTimer.singleShot(0, self._sync_view_state)

    def _sync_view_state(self):
        self._sync_pending = False

        self._sync_flow_geometry()
        content_width = max(1, self.contentsRect().width())
        total_rows = self._row_count(content_width)
        self._can_collapse = total_rows > self._collapsed_rows

        if not self._can_collapse:
            self._expanded = False

        chip_height = max((chip.sizeHint().height() for chip in self._chips if chip.isVisible()), default=32)
        spacing = 6
        margins = self._flow.contentsMargins()
        full_height = self._content_height_for_width(content_width)
        collapsed_height = (
            margins.top()
            + margins.bottom()
            + self._collapsed_rows * chip_height
            + max(0, self._collapsed_rows - 1) * spacing
        )
        target_height = full_height if self._expanded or not self._can_collapse else min(full_height, collapsed_height)

        self._content.setFixedHeight(max(0, full_height))
        self._sync_flow_geometry()
        self.setFixedHeight(max(chip_height, target_height))
        self.updateGeometry()
        self.view_state_changed.emit()


class CaseWorkbenchStrip(QWidget):
    """External multi-case strip shown above the input form."""

    add_requested = Signal()
    case_switched = Signal(int)
    case_renamed = Signal(int, str)
    apply_to_all_requested = Signal()
    copy_from_prev_requested = Signal()
    remove_current_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("caseWorkbenchStrip")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(CASE_STRIP_SS)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)

        self._navigator = CaseTagNavigator(collapsed_rows=3, parent=self)
        self._navigator.case_switched.connect(self.case_switched.emit)
        self._navigator.case_renamed.connect(self.case_renamed.emit)
        self._navigator.expanded_changed.connect(self._refresh_auxiliary)
        self._navigator.view_state_changed.connect(self._refresh_auxiliary)
        top_row.addWidget(self._navigator, 1)

        meta_col = QVBoxLayout()
        meta_col.setContentsMargins(0, 0, 0, 0)
        meta_col.setSpacing(6)

        self._count_label = QLabel("1 个计算工况")
        self._count_label.setStyleSheet(CASE_META_LABEL_SS)
        meta_col.addWidget(self._count_label, 0, Qt.AlignRight)

        self._add_button = DashedButton("+ 添加")
        self._add_button.setObjectName("addCaseButton")
        self._add_button.setCursor(Qt.PointingHandCursor)
        self._add_button.setFixedHeight(32)
        self._add_button.clicked.connect(self.add_requested.emit)
        meta_col.addWidget(self._add_button, 0, Qt.AlignRight)

        self._toggle_button = QPushButton("展开全部")
        self._toggle_button.setCursor(Qt.PointingHandCursor)
        self._toggle_button.setStyleSheet(CASE_TOGGLE_SS)
        self._toggle_button.clicked.connect(self._toggle_expanded)
        meta_col.addWidget(self._toggle_button, 0, Qt.AlignRight)
        meta_col.addStretch(1)
        top_row.addLayout(meta_col)

        root.addLayout(top_row)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(6)

        self._copy_all_button = QPushButton("复制参数到所有")
        self._copy_all_button.setCursor(Qt.PointingHandCursor)
        self._copy_all_button.setStyleSheet(CASE_QUICK_SS)
        self._copy_all_button.setToolTip("将当前工况的参数（不含 Q）复制到其余所有工况")
        self._copy_all_button.clicked.connect(self.apply_to_all_requested.emit)
        action_row.addWidget(self._copy_all_button)

        self._copy_prev_button = QPushButton("从上一个复制")
        self._copy_prev_button.setCursor(Qt.PointingHandCursor)
        self._copy_prev_button.setStyleSheet(CASE_QUICK_SS)
        self._copy_prev_button.setToolTip("将上一个工况的参数（不含 Q）复制到当前工况")
        self._copy_prev_button.clicked.connect(self.copy_from_prev_requested.emit)
        action_row.addWidget(self._copy_prev_button)

        self._remove_button = QPushButton("删除当前")
        self._remove_button.setCursor(Qt.PointingHandCursor)
        self._remove_button.setStyleSheet(CASE_QUICK_SS)
        self._remove_button.setToolTip("删除当前选中的工况（至少保留一个）")
        self._remove_button.clicked.connect(self.remove_current_requested.emit)
        action_row.addWidget(self._remove_button)
        action_row.addStretch(1)

        root.addLayout(action_row)

        self._case_count = 1
        self._refresh_auxiliary()

    def navigator(self):
        return self._navigator

    def sync_cases(self, cases, current_index, view_getter):
        self._case_count = len(cases)
        self._navigator.sync_cases(cases, current_index, view_getter)
        self._refresh_auxiliary()

    def case_labels(self):
        return self._navigator.case_labels()

    def chip_count(self):
        return self._navigator.chip_count()

    def is_expanded(self):
        return self._navigator.is_expanded()

    def can_collapse(self):
        return self._navigator.can_collapse()

    def set_expanded(self, expanded):
        self._navigator.set_expanded(expanded)

    def set_remove_enabled(self, enabled):
        self._remove_button.setEnabled(bool(enabled))

    def _toggle_expanded(self):
        self._navigator.set_expanded(not self._navigator.is_expanded())

    def _refresh_auxiliary(self):
        self._count_label.setText(f"{self._case_count} 个计算工况")
        can_collapse = self._navigator.can_collapse()
        self._toggle_button.setVisible(can_collapse)
        self._toggle_button.setText("收起" if can_collapse and self._navigator.is_expanded() else "展开全部")
