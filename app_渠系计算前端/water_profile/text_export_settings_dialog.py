# -*- coding: utf-8 -*-
"""Active TextExportSettingsDialog implementation."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QEvent, QMimeData, QPoint, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QDrag, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QScrollArea,
    QSplitter,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ToolButton,
)


def _api_get(api, name):
    if isinstance(api, Mapping):
        return api[name]
    return getattr(api, name)


class AutoHeightListWidget(QListWidget):
    """List widget that reports content height and avoids inner scrolling."""

    enabledRowDropped = Signal(str, int)
    toggleRequested = Signal(str)

    def __init__(self, allow_reorder=False, auto_height=True, parent=None):
        super().__init__(parent)
        self._allow_reorder = bool(allow_reorder)
        self._auto_height = bool(auto_height)
        self._suspend_scroll_to_current = False
        self._height_cache = None
        self._height_correction = 0
        self._preferred_height = None
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        if self._auto_height:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if self._allow_reorder:
            self.setDragEnabled(True)
            self.viewport().setAcceptDrops(True)
            self.setAcceptDrops(True)
            self.setDropIndicatorShown(True)
            self.setDefaultDropAction(Qt.MoveAction)
            self.setDragDropMode(QAbstractItemView.DragDrop)
        else:
            self.setDragEnabled(False)
            self.setAcceptDrops(False)
            self.setDropIndicatorShown(False)
            self.setDragDropMode(QAbstractItemView.NoDragDrop)
        self._set_drag_feedback(False)
        self._bind_model_signals()

    def _bind_model_signals(self):
        model = self.model()
        if model is None:
            return
        model.rowsInserted.connect(self._invalidate_height_cache)
        model.rowsRemoved.connect(self._invalidate_height_cache)
        model.modelReset.connect(self._invalidate_height_cache)
        model.layoutChanged.connect(self._invalidate_height_cache)
        model.dataChanged.connect(self._invalidate_height_cache)

    def _invalidate_height_cache(self, *_args):
        self._height_cache = None
        self.updateGeometry()
        self.viewport().updateGeometry()

    def recalculate_height(self):
        self.doItemsLayout()
        if not self._auto_height:
            self.updateGeometries()
            self.viewport().updateGeometry()
            return
        self._height_correction = max(0, int(self.verticalScrollBar().maximum()))
        self._invalidate_height_cache()

    def clear(self):
        super().clear()
        self._invalidate_height_cache()

    def setItemWidget(self, item, widget):
        widget_hint = widget.sizeHint()
        row_height = max(36, widget_hint.height() + 4, widget.minimumSizeHint().height() + 4)
        item.setSizeHint(QSize(0, row_height))
        super().setItemWidget(item, widget)
        self._invalidate_height_cache()

    def current_row_id(self):
        item = self.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "").strip()

    def set_suspend_scroll_to_current(self, active):
        self._suspend_scroll_to_current = bool(active)

    def set_preferred_height(self, height):
        self._preferred_height = None if height is None else max(0, int(height))
        self.updateGeometry()
        self.viewport().updateGeometry()

    def _base_content_height(self):
        frame = self.frameWidth() * 2
        margins = self.contentsMargins()
        return frame + margins.top() + margins.bottom()

    def _row_height(self, row):
        item = self.item(row)
        if item is None:
            return 0
        hinted = item.sizeHint().height()
        if hinted <= 0:
            hinted = self.sizeHintForRow(row)
        return max(0, hinted)

    def _default_row_height(self):
        for row in range(self.count()):
            height = self._row_height(row)
            if height > 0:
                return height
        return 36

    def content_height_for_rows(self, row_count, *, clamp_to_count=True):
        row_count = max(0, int(row_count))
        actual_row_count = min(row_count, self.count()) if clamp_to_count else min(row_count, self.count())
        total = self._base_content_height()
        for row in range(actual_row_count):
            total += self._row_height(row)
        if not clamp_to_count and row_count > actual_row_count:
            total += self._default_row_height() * (row_count - actual_row_count)
        if row_count > 1:
            total += self.spacing() * (row_count - 1)
        if row_count > 0:
            total += 16 + row_count * 2
        return max(0, total)

    def _content_height(self):
        if not self._auto_height:
            return super().sizeHint().height()
        if self._height_cache is not None:
            return self._height_cache
        total = self.content_height_for_rows(self.count())
        self._height_cache = max(0, total + self._height_correction)
        return self._height_cache

    def minimumSizeHint(self):
        if not self._auto_height:
            hint = super().minimumSizeHint()
            if self._preferred_height is not None:
                hint.setHeight(0)
            return hint
        hint = super().minimumSizeHint()
        hint.setHeight(self._content_height())
        return hint

    def sizeHint(self):
        if not self._auto_height:
            hint = super().sizeHint()
            if self._preferred_height is not None:
                hint.setHeight(self._preferred_height)
            return hint
        hint = super().sizeHint()
        hint.setHeight(self._content_height())
        return hint

    def viewportSizeHint(self):
        if not self._auto_height:
            hint = super().viewportSizeHint()
            if self._preferred_height is not None:
                hint.setHeight(max(0, self._preferred_height - self.frameWidth() * 2))
            return hint
        hint = super().viewportSizeHint()
        hint.setHeight(max(0, self._content_height() - self.frameWidth() * 2))
        return hint

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_height:
            self.recalculate_height()

    def _set_drag_feedback(self, active):
        if active and self._allow_reorder:
            self.setStyleSheet(
                "QListView { border: 1px solid rgba(0, 120, 212, 0.45); "
                "background: rgba(0, 120, 212, 0.05); border-radius: 12px; }"
            )
        else:
            self.setStyleSheet("")

    def start_drag_for_row_id(self, rid):
        if not self._allow_reorder:
            return
        rid = str(rid or "").strip()
        if not rid:
            return
        for row in range(self.count()):
            item = self.item(row)
            if item is not None and str(item.data(Qt.UserRole) or "").strip() == rid:
                self.setCurrentRow(row)
                self.startDrag(Qt.MoveAction)
                return

    def startDrag(self, supportedActions):
        if not self._allow_reorder:
            return
        rid = self.current_row_id()
        if not rid:
            return
        mime = QMimeData()
        mime.setData("application/x-profile-enabled-row-id", rid.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        self._set_drag_feedback(True)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self._set_drag_feedback(False)

    def dragEnterEvent(self, event):
        if self._allow_reorder and event.mimeData().hasFormat("application/x-profile-enabled-row-id"):
            self._set_drag_feedback(True)
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self._set_drag_feedback(False)
        super().dragLeaveEvent(event)

    def dragMoveEvent(self, event):
        if self._allow_reorder and event.mimeData().hasFormat("application/x-profile-enabled-row-id"):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if not self._allow_reorder:
            super().dropEvent(event)
            return
        data = event.mimeData()
        if not data.hasFormat("application/x-profile-enabled-row-id"):
            super().dropEvent(event)
            return
        self._set_drag_feedback(False)
        try:
            rid = bytes(data.data("application/x-profile-enabled-row-id")).decode("utf-8").strip()
            if not rid:
                event.ignore()
                return
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            row = self.indexAt(pos).row()
            if row < 0:
                row = self.count()
            row = max(0, min(self.count(), row))
            self.enabledRowDropped.emit(rid, row)
            event.acceptProposedAction()
        except Exception:
            event.ignore()

    def keyPressEvent(self, event):
        rid = self.current_row_id()
        if rid and event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.toggleRequested.emit(rid)
            event.accept()
            return
        super().keyPressEvent(event)

    def scrollTo(self, index, hint=QAbstractItemView.EnsureVisible):
        if self._suspend_scroll_to_current:
            return
        super().scrollTo(index, hint)


class WrapCaptionLabel(CaptionLabel):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setText(text)

    def _effective_width(self, fallback_width):
        width = self.width()
        if width and width > 0:
            return width
        parent = self.parentWidget()
        if parent is not None:
            parent_width = parent.width()
            if parent_width and parent_width > 0:
                margins = self.contentsMargins()
                return max(1, parent_width - margins.left() - margins.right())
        return max(1, fallback_width)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        margins = self.contentsMargins()
        available_width = max(1, int(width) - margins.left() - margins.right())
        text = self.text().strip()
        if not text:
            return margins.top() + margins.bottom()
        flags = int(self.alignment()) | int(Qt.TextWordWrap)
        rect = self.fontMetrics().boundingRect(0, 0, available_width, 32767, flags, text)
        return rect.height() + margins.top() + margins.bottom()

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setHeight(self.heightForWidth(self._effective_width(hint.width())))
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setHeight(self.heightForWidth(self._effective_width(hint.width())))
        return hint


class FluentProfileDragHandle(QLabel):
    dragRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(":::")
        self._press_pos = None
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.OpenHandCursor)
        self.setFixedWidth(18)
        self.setStyleSheet("color:#7F8B99; font-size:16px; font-weight:600; letter-spacing:1px;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self._press_pos is None:
            super().mouseMoveEvent(event)
            return
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if (pos - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
            self.dragRequested.emit()
            self._press_pos = None
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_pos = None
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)


class FluentProfileRowItemWidget(QWidget):
    clicked = Signal()
    doubleClicked = Signal()
    dragRequested = Signal()

    def __init__(self, title, subtitle, enabled, recommended=False, *, display_variant="standard", parent=None):
        super().__init__(parent)
        self._selected = False
        self._enabled = bool(enabled)
        self._recommended = bool(recommended)
        self._display_variant = str(display_variant or "standard")
        self.setObjectName("profileRowItemFluent")
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        if self._display_variant == "quick_add":
            layout.setContentsMargins(10, 6, 10, 6)
            layout.setSpacing(8)
        else:
            layout.setContentsMargins(8, 3, 8, 3)
            layout.setSpacing(6)

        self.checkbox = CheckBox("")
        self.checkbox.setFixedWidth(36)
        layout.addWidget(self.checkbox, 0, Qt.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)

        self.title_label = QLabel()
        self.title_label.setTextInteractionFlags(Qt.NoTextInteraction)
        title_row.addWidget(self.title_label, 1)

        self.badge_label = QLabel("推荐")
        self.badge_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.badge_label.setVisible(False)
        title_row.addWidget(self.badge_label, 0, Qt.AlignVCenter)
        title_row.addStretch(0)

        self.subtitle_label = QLabel()
        self.subtitle_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.subtitle_label.setWordWrap(False)

        text_col.addLayout(title_row)
        text_col.addWidget(self.subtitle_label)
        layout.addLayout(text_col, 1)

        self.drag_handle = FluentProfileDragHandle(self)
        self.drag_handle.dragRequested.connect(self.dragRequested)
        layout.addWidget(self.drag_handle, 0, Qt.AlignVCenter)

        for child in (self.title_label, self.subtitle_label, self.badge_label):
            child.installEventFilter(self)

        self.set_content(title, subtitle, enabled, recommended)
        self.set_selected(False)

    def set_content(self, title, subtitle, enabled, recommended=False):
        self._enabled = bool(enabled)
        self._recommended = bool(recommended)
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)
        self.checkbox.setChecked(bool(enabled))
        self.drag_handle.setVisible(bool(enabled))
        self.badge_label.setVisible(self._recommended)
        self._apply_visual_state()

    def set_selected(self, selected):
        self._selected = bool(selected)
        self._apply_visual_state()

    def _apply_visual_state(self):
        border_radius = "12px" if self._display_variant == "quick_add" else "10px"
        if self._selected:
            self.setStyleSheet(
                "QWidget#profileRowItemFluent {"
                "background: rgba(230, 238, 248, 0.96);"
                "border: 1px solid rgba(0, 120, 212, 0.28);"
                f"border-radius: {border_radius};"
                "}"
            )
        else:
            self.setStyleSheet(
                "QWidget#profileRowItemFluent {"
                "background: rgba(255, 255, 255, 0.88);"
                "border: 1px solid rgba(198, 210, 224, 0.32);"
                f"border-radius: {border_radius};"
                "}"
            )

        if self._selected:
            title_style = (
                "color:#173A63; "
                f"font-size:{'13px' if self._display_variant == 'quick_add' else '12px'}; font-weight:600;"
            )
            subtitle_style = (
                "color:#43617E; "
                f"font-size:{'11px' if self._display_variant == 'quick_add' else '10px'};"
            )
        elif self._enabled:
            title_style = (
                "color:#24384D; "
                f"font-size:{'13px' if self._display_variant == 'quick_add' else '12px'}; font-weight:600;"
            )
            subtitle_style = (
                "color:#5C6E81; "
                f"font-size:{'11px' if self._display_variant == 'quick_add' else '10px'};"
            )
        else:
            title_style = (
                "color:#2F4457; "
                f"font-size:{'13px' if self._display_variant == 'quick_add' else '12px'}; font-weight:500;"
            )
            subtitle_style = (
                "color:#697B8D; "
                f"font-size:{'11px' if self._display_variant == 'quick_add' else '10px'};"
            )

        self.title_label.setStyleSheet(title_style)
        self.subtitle_label.setStyleSheet(subtitle_style)
        self.badge_label.setStyleSheet(
            "color:#5F6F82; background: rgba(225, 231, 238, 0.92);"
            "border: 1px solid rgba(198, 210, 224, 0.85); border-radius: 9px;"
            "padding: 1px 7px; font-size:11px;"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def eventFilter(self, obj, event):
        if obj in {self.title_label, self.subtitle_label, self.badge_label}:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self.clicked.emit()
                return True
            if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self.doubleClicked.emit()
                return True
        return super().eventFilter(obj, event)


def create_text_export_settings_dialog(api_module):
    DIALOG_STYLE = _api_get(api_module, "DIALOG_STYLE")
    normalize_text_export_settings = _api_get(api_module, "_normalize_text_export_settings")
    compute_runtime_advanced_parameter_view = _api_get(
        api_module, "_compute_runtime_advanced_parameter_view"
    )
    compute_xxpipe_runtime_advanced_parameter_view = _api_get(
        api_module, "_compute_xxpipe_runtime_advanced_parameter_view"
    )
    resolve_fluent_icon = _api_get(api_module, "_resolve_fluent_icon")
    format_number = _api_get(api_module, "_format_number")
    profile_row_def_map = dict(_api_get(api_module, "_PROFILE_ROW_DEF_MAP"))
    profile_row_visible_order = list(_api_get(api_module, "_PROFILE_ROW_VISIBLE_ORDER"))
    profile_row_visible_id_set = frozenset(profile_row_visible_order)
    tingzikou_template_row_ids = list(_api_get(api_module, "_TINGZIKOU_TEMPLATE_ROW_IDS"))
    recommended_row_ids = set(_api_get(api_module, "_PROFILE_RECOMMENDED_ROW_IDS"))
    xxpipe_row_defs = list(_api_get(api_module, "_get_xxpipe_profile_row_defs")())
    xxpipe_row_def_map = {row["id"]: dict(row) for row in xxpipe_row_defs}
    xxpipe_row_visible_order = [row["id"] for row in xxpipe_row_defs]
    xxpipe_row_visible_id_set = frozenset(xxpipe_row_visible_order)
    runtime_advanced_keys = tuple(_api_get(api_module, "_PROFILE_RUNTIME_ADVANCED_KEYS"))

    def _resolve_mode_spec(mode):
        mode_name = str(mode or "standard").strip().lower()
        if mode_name == "xxpipe":
            return {
                "mode": "xxpipe",
                "row_def_map": xxpipe_row_def_map,
                "visible_order": xxpipe_row_visible_order,
                "visible_id_set": xxpipe_row_visible_id_set,
                "default_enabled_ids": frozenset(xxpipe_row_visible_order),
                "tingzikou_template_row_ids": tuple(xxpipe_row_visible_order),
                "recommended_row_ids": frozenset(xxpipe_row_visible_order),
                "runtime_view_builder": compute_xxpipe_runtime_advanced_parameter_view,
                "read_only_rows": True,
                "toolbar_title": "纵断面行内容",
                "toolbar_hint": "固定模板，仅展示管道纵断面导出的 5 项。",
                "enabled_title": "固定 5 项",
                "enabled_hint": "这里显示 xx管 纵断面导出的固定内容，顺序和启停均已锁定。",
                "candidate_title": "可选项",
                "empty_runtime_hint": "当前按 xx管 固定模板展示全部 5 项。",
                "subtitle_enabled": "固定项",
                "subtitle_disabled": "固定项",
                "decimal_entry_key": "xxpipe_centerline_elev_decimals",
                "decimal_entry_label": "管中心线高程小数位数",
                "decimal_entry_hint": "仅影响“管中心线高程（米）”，仅接受非负整数。",
            }
        return {
            "mode": "standard",
            "row_def_map": profile_row_def_map,
            "visible_order": profile_row_visible_order,
            "visible_id_set": profile_row_visible_id_set,
            "default_enabled_ids": frozenset(
                rid for rid in tingzikou_template_row_ids if rid in profile_row_visible_id_set
            ),
            "tingzikou_template_row_ids": tuple(tingzikou_template_row_ids),
            "recommended_row_ids": frozenset(recommended_row_ids),
            "runtime_view_builder": compute_runtime_advanced_parameter_view,
            "read_only_rows": False,
            "toolbar_title": "纵断面行内容工作台",
            "toolbar_hint": "",
            "enabled_title": "已启用",
            "enabled_hint": "",
            "candidate_title": "可选项",
            "empty_runtime_hint": "当前尚未启用任何纵断面行。",
            "subtitle_enabled": "已启用",
            "subtitle_disabled": "可选项",
            "decimal_entry_key": "elev_decimals",
            "decimal_entry_label": "高程小数位数",
            "decimal_entry_hint": "仅接受非负整数。",
        }
    def _info_bar():
        return _api_get(api_module, "InfoBar")

    def _info_bar_position():
        return _api_get(api_module, "InfoBarPosition")

    def _show_error(parent, title, content):
        return _api_get(api_module, "fluent_error")(parent, title, content)

    def _basic_entry_keys(mode_spec):
        return (
            "text_height",
            "rotation",
            mode_spec["decimal_entry_key"],
            "scale_x",
            "scale_y",
        )

    def _basic_entry_labels(mode_spec):
        return {
            "text_height": "字高",
            "rotation": "旋转角度",
            mode_spec["decimal_entry_key"]: mode_spec["decimal_entry_label"],
            "scale_x": "X方向比例",
            "scale_y": "Y方向比例",
        }

    def _is_decimal_entry_key(mode_spec, key):
        return key == mode_spec["decimal_entry_key"]
    def default_profile_row_items(mode_spec):
        return [
            {"id": rid, "enabled": rid in mode_spec["default_enabled_ids"]}
            for rid in mode_spec["visible_order"]
        ]

    def normalize_profile_row_items(raw_items, *, mode_spec):
        if mode_spec["read_only_rows"]:
            return [{"id": rid, "enabled": True} for rid in mode_spec["visible_order"]]

        order = []
        enabled_map = {}
        if isinstance(raw_items, list):
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                rid = str(item.get("id", "")).strip()
                if rid not in mode_spec["visible_id_set"] or rid in order:
                    continue
                order.append(rid)
                enabled_map[rid] = bool(item.get("enabled", rid in mode_spec["default_enabled_ids"]))
        for rid in mode_spec["visible_order"]:
            if rid not in order:
                order.append(rid)
        return [
            {"id": rid, "enabled": enabled_map.get(rid, rid in mode_spec["default_enabled_ids"])}
            for rid in order
        ]

    def normalize_dialog_defaults(settings, *, mode_spec):
        normalized = normalize_text_export_settings(settings or {})
        normalized["profile_row_items"] = normalize_profile_row_items(
            normalized.get("profile_row_items"),
            mode_spec=mode_spec,
        )
        return normalized

    class TextExportSettingsState:
        def __init__(
            self,
            *,
            mode_spec,
            parameter_texts,
            compat_values,
            ordered_row_ids=None,
            enabled_row_ids=None,
            candidate_query="",
            candidate_expanded=True,
            active_list_role="enabled",
            selected_row_id="",
        ):
            self.mode_spec = dict(mode_spec or {})
            self.parameter_texts = dict(parameter_texts or {})
            self.compat_values = dict(compat_values or {})
            self.ordered_row_ids = list(ordered_row_ids or [])
            self.enabled_row_ids = list(enabled_row_ids or [])
            self.candidate_query = str(candidate_query or "")
            self.candidate_expanded = bool(candidate_expanded)
            self.active_list_role = str(active_list_role or "enabled")
            self.selected_row_id = str(selected_row_id or "")

        @classmethod
        def from_defaults(cls, defaults, *, mode_spec):
            normalized = normalize_dialog_defaults(defaults or {}, mode_spec=mode_spec)
            row_items = normalize_profile_row_items(
                normalized.get("profile_row_items"),
                mode_spec=mode_spec,
            )
            enabled_row_ids = [item["id"] for item in row_items if item.get("enabled")]
            candidate_row_ids = [item["id"] for item in row_items if not item.get("enabled")]
            selected_row_id = enabled_row_ids[0] if enabled_row_ids else (candidate_row_ids[0] if candidate_row_ids else "")
            active_role = "enabled" if enabled_row_ids else "candidate"
            return cls(
                mode_spec=mode_spec,
                parameter_texts={key: str(normalized.get(key, "")) for key in _basic_entry_keys(mode_spec)},
                compat_values={key: normalized.get(key) for key in runtime_advanced_keys},
                ordered_row_ids=[item["id"] for item in row_items],
                enabled_row_ids=enabled_row_ids,
                active_list_role=active_role,
                selected_row_id=selected_row_id,
            )

        def normalize_row_model(self):
            visible_id_set = self.mode_spec["visible_id_set"]
            visible_order = self.mode_spec["visible_order"]
            enabled = [rid for rid in self.enabled_row_ids if rid in visible_id_set]
            order = [rid for rid in self.ordered_row_ids if rid in visible_id_set]
            for rid in visible_order:
                if rid not in order:
                    order.append(rid)
            disabled = [rid for rid in order if rid not in enabled]
            self.enabled_row_ids = enabled
            self.ordered_row_ids = enabled + disabled

        def all_candidate_row_ids(self):
            self.normalize_row_model()
            return [rid for rid in self.ordered_row_ids if rid not in self.enabled_row_ids]

        def candidate_row_ids(self):
            row_ids = self.all_candidate_row_ids()
            query = self.candidate_query.strip().lower()
            if not query:
                return row_ids
            filtered = []
            for rid in row_ids:
                row_def = self.mode_spec["row_def_map"].get(rid, {})
                haystack = " ".join(
                    [rid, str(row_def.get("label", "")), str(row_def.get("hint", ""))]
                ).lower()
                if query in haystack:
                    filtered.append(rid)
            return filtered

        def row_items(self):
            self.normalize_row_model()
            enabled = set(self.enabled_row_ids)
            return normalize_profile_row_items(
                [{"id": rid, "enabled": rid in enabled} for rid in self.ordered_row_ids],
                mode_spec=self.mode_spec,
            )

        def set_basic_value(self, key, value):
            self.parameter_texts[key] = str(value)

        def parsed_basic_values(self, *, strict):
            parsed = {}
            labels = _basic_entry_labels(self.mode_spec)
            for key in _basic_entry_keys(self.mode_spec):
                raw = str(self.parameter_texts.get(key, "")).strip()
                if not raw:
                    if strict:
                        raise ValueError(f"{labels[key]}不能为空", key)
                    continue
                try:
                    value = float(raw)
                except ValueError as exc:
                    if strict:
                        raise ValueError(f"{labels[key]}必须为数值", key) from exc
                    continue
                if _is_decimal_entry_key(self.mode_spec, key):
                    if value < 0 or value != int(value):
                        if strict:
                            raise ValueError(f"{labels[key]}必须为非负整数", key)
                        continue
                    value = int(value)
                if key in {"scale_x", "scale_y"} and value <= 0:
                    if strict:
                        raise ValueError("比例必须大于0", key)
                    continue
                parsed[key] = value
            return parsed

        def build_runtime_input(self, defaults):
            settings = dict(defaults)
            settings.update(self.compat_values)
            settings.update(self.parsed_basic_values(strict=False))
            settings["profile_row_items"] = self.row_items()
            return settings

        def runtime_view(self, defaults):
            return self.mode_spec["runtime_view_builder"](self.build_runtime_input(defaults))

        def ensure_selection(self):
            enabled = list(self.enabled_row_ids)
            candidate = list(self.candidate_row_ids())
            visible = set(enabled) | set(candidate)
            if self.selected_row_id in visible:
                if self.selected_row_id in enabled:
                    self.active_list_role = "enabled"
                elif self.selected_row_id in candidate:
                    self.active_list_role = "candidate"
                return
            if enabled:
                self.selected_row_id = enabled[0]
                self.active_list_role = "enabled"
            elif candidate:
                self.selected_row_id = candidate[0]
                self.active_list_role = "candidate"
            else:
                self.selected_row_id = ""
                self.active_list_role = "enabled"

        def set_candidate_search(self, text):
            self.candidate_query = str(text or "")
            self.ensure_selection()

        def set_candidate_expanded(self, expanded):
            self.candidate_expanded = bool(expanded)

        def set_selected_row(self, rid, role=None):
            self.selected_row_id = str(rid or "").strip()
            if role in {"enabled", "candidate"}:
                self.active_list_role = role
            self.ensure_selection()

        def _get_recommended_insert_row(self, rid):
            recommended_row_ids = self.mode_spec["recommended_row_ids"]
            visible_order = self.mode_spec["visible_order"]
            if rid not in recommended_row_ids:
                return len(self.enabled_row_ids)
            current_recommended = [row_id for row_id in self.enabled_row_ids if row_id in recommended_row_ids]
            expected_recommended = [
                row_id
                for row_id in visible_order
                if row_id in recommended_row_ids and row_id in current_recommended
            ]
            if current_recommended != expected_recommended:
                return len(self.enabled_row_ids)
            rid_index = visible_order.index(rid)
            for row, row_id in enumerate(self.enabled_row_ids):
                if row_id in recommended_row_ids and visible_order.index(row_id) > rid_index:
                    return row
            previous_recommended = [
                row_id
                for row_id in self.enabled_row_ids
                if row_id in recommended_row_ids and visible_order.index(row_id) < rid_index
            ]
            if previous_recommended:
                return self.enabled_row_ids.index(previous_recommended[-1]) + 1
            return len(self.enabled_row_ids)

        def set_row_enabled(self, rid, enabled):
            rid = str(rid or "").strip()
            if rid not in self.mode_spec["visible_id_set"]:
                return False
            if self.mode_spec["read_only_rows"]:
                return False
            current_enabled = rid in self.enabled_row_ids
            enabled = bool(enabled)
            if current_enabled == enabled:
                return False
            if enabled:
                insert_row = self._get_recommended_insert_row(rid)
                self.enabled_row_ids = [row_id for row_id in self.enabled_row_ids if row_id != rid]
                self.enabled_row_ids.insert(insert_row, rid)
                self.selected_row_id = rid
                self.active_list_role = "enabled"
            else:
                previous_enabled = list(self.enabled_row_ids)
                previous_index = previous_enabled.index(rid)
                self.enabled_row_ids = [row_id for row_id in self.enabled_row_ids if row_id != rid]
                self.normalize_row_model()
                if self.enabled_row_ids:
                    fallback_index = min(previous_index, len(self.enabled_row_ids) - 1)
                    self.selected_row_id = self.enabled_row_ids[fallback_index]
                    self.active_list_role = "enabled"
                else:
                    candidates = self.candidate_row_ids()
                    self.selected_row_id = candidates[0] if candidates else ""
                    self.active_list_role = "candidate"
                self.ensure_selection()
                return True
            self.normalize_row_model()
            self.ensure_selection()
            return True

        def reorder_enabled_row(self, rid, target_row):
            if self.mode_spec["read_only_rows"]:
                return False
            rid = str(rid or "").strip()
            enabled = list(self.enabled_row_ids)
            if rid not in enabled:
                return False
            old_row = enabled.index(rid)
            enabled.pop(old_row)
            target_row = max(0, min(len(enabled), int(target_row)))
            if target_row > old_row:
                target_row -= 1
            enabled.insert(target_row, rid)
            self.enabled_row_ids = enabled
            self.normalize_row_model()
            self.selected_row_id = rid
            self.active_list_role = "enabled"
            self.ensure_selection()
            return True

        def enable_all_rows(self):
            if self.mode_spec["read_only_rows"]:
                return
            self.enabled_row_ids = list(self.mode_spec["visible_order"])
            self.normalize_row_model()
            self.selected_row_id = self.enabled_row_ids[0] if self.enabled_row_ids else ""
            self.active_list_role = "enabled"
            self.ensure_selection()

        def disable_all_rows(self):
            if self.mode_spec["read_only_rows"]:
                return
            self.enabled_row_ids = []
            self.normalize_row_model()
            candidates = self.candidate_row_ids()
            self.selected_row_id = candidates[0] if candidates else ""
            self.active_list_role = "candidate"
            self.ensure_selection()

        def restore_recommended_rows(self):
            if self.mode_spec["read_only_rows"]:
                return
            visible_order = self.mode_spec["visible_order"]
            recommended_row_ids = self.mode_spec["recommended_row_ids"]
            self.enabled_row_ids = [rid for rid in visible_order if rid in recommended_row_ids]
            self.normalize_row_model()
            self.selected_row_id = self.enabled_row_ids[0] if self.enabled_row_ids else ""
            self.active_list_role = "enabled"
            self.ensure_selection()

        def apply_tingzikou_preset(self):
            if self.mode_spec["read_only_rows"]:
                return
            visible_order = self.mode_spec["visible_order"]
            tingzikou_template_row_ids = self.mode_spec["tingzikou_template_row_ids"]
            ordered = list(tingzikou_template_row_ids) + [
                rid for rid in visible_order if rid not in tingzikou_template_row_ids
            ]
            self.ordered_row_ids = ordered
            self.enabled_row_ids = list(tingzikou_template_row_ids)
            self.normalize_row_model()
            self.selected_row_id = self.enabled_row_ids[0] if self.enabled_row_ids else ""
            self.active_list_role = "enabled"
            self.ensure_selection()

    class TextExportSettingsDialog(QDialog):
        _UI_SETTINGS_ORG = "SichuanShuifa"
        _UI_SETTINGS_APP = "HydroCalc"
        _UI_SIZE_W_KEY = "water_profile/text_export_dialog_width"
        _UI_SIZE_H_KEY = "water_profile/text_export_dialog_height"
        _DESIGN_MIN_WIDTH = 1160
        _DESIGN_MIN_HEIGHT = 700
        _DESIGN_DEFAULT_WIDTH = 2000
        _DESIGN_DEFAULT_HEIGHT = 1400
        _DEFAULT_WIDTH_RATIO = 2000 / 2560
        _DEFAULT_HEIGHT_RATIO = 1400 / 1600
        _DEFAULT_MAX_WIDTH = 2800
        _DEFAULT_MAX_HEIGHT = 1800
        _MIN_SCREEN_MARGIN = 24
        _DESIGN_SPLITTER_LEFT = 460
        _ENABLED_VISIBLE_ROW_LIMIT = 11
        _CANDIDATE_VISIBLE_ROW_LIMIT = 4
        _ICON_COLLAPSED = None
        _ICON_EXPANDED = None

        def __init__(self, parent=None, defaults=None, mode="standard"):
            super().__init__(parent)
            if self._ICON_COLLAPSED is None or self._ICON_EXPANDED is None:
                type(self)._ICON_COLLAPSED = resolve_fluent_icon(
                    "CHEVRON_RIGHT_MED", "CHEVRON_RIGHT", "CHEVRON_DOWN_MED"
                )
                type(self)._ICON_EXPANDED = resolve_fluent_icon(
                    "CHEVRON_DOWN_MED", "CHEVRON_RIGHT_MED", "CHEVRON_RIGHT"
                )

            self.setWindowTitle("纵断面文字导出设置")
            self._ui_settings = QSettings(self._UI_SETTINGS_ORG, self._UI_SETTINGS_APP)
            self._mode_spec = _resolve_mode_spec(mode)
            self._standard_defaults = normalize_dialog_defaults(
                defaults or {},
                mode_spec=_resolve_mode_spec("standard"),
            )
            self._standard_profile_row_items_snapshot = list(
                self._standard_defaults.get("profile_row_items", [])
            )
            self._defaults = normalize_dialog_defaults(defaults or {}, mode_spec=self._mode_spec)
            self._state = TextExportSettingsState.from_defaults(
                self._defaults,
                mode_spec=self._mode_spec,
            )
            self._reset_defaults_source = dict(self._defaults)
            self._row_updating = False
            self._selection_syncing = False
            self._splitter_initialized = False
            self.result = None

            self._entries = {}
            self._row_widgets = {}
            self._parameter_content_layout = None
            self._parameter_card = None
            self._parameter_left_section = None
            self._parameter_right_section = None
            self._runtime_rows_widget = None
            self._runtime_rows_layout = None
            self._runtime_row_labels = {}
            self._runtime_summary_label = None
            self._runtime_metric_labels = {}
            self._row_list = None
            self._enabled_list = None
            self._candidate_list = None
            self._enabled_caption_label = None
            self._candidate_caption_label = None
            self._candidate_body = None
            self._candidate_toggle_btn = None
            self._body_scroll = None
            self._body_content_widget = None
            self._rows_card = None
            self._workbench_splitter = None
            self._toolbar_card = None
            self._enabled_section = None
            self._candidate_section = None
            self._btn_reset = None
            self._btn_cancel = None
            self._btn_ok = None

            self._dialog_min_size = self._resolve_minimum_dialog_size()
            self.setMinimumSize(self._dialog_min_size)
            self._apply_initial_size()
            self.setSizeGripEnabled(True)
            self.setStyleSheet(
                DIALOG_STYLE
                + """
                QDialog {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #f7f9fc, stop:1 #eef3fb);
                }
                QListView {
                    border: 1px solid #d6dfef;
                    border-radius: 12px;
                    background: rgba(255,255,255,0.94);
                    padding: 4px;
                }
                QListView::item {
                    border-radius: 10px;
                    padding: 4px 6px;
                    margin: 1px 1px;
                }
                QListView::item:selected {
                    background: rgba(0, 120, 212, 0.10);
                    border: 1px solid rgba(0, 120, 212, 0.28);
                }
                QListView::item:hover {
                    background: rgba(32, 97, 181, 0.06);
                }
                QFrame#profileWorkbenchPanel {
                    background: rgba(255,255,255,0.62);
                    border: 1px solid rgba(208,218,232,0.92);
                    border-radius: 18px;
                }
                QFrame#profileSectionCard {
                    background: rgba(255,255,255,0.90);
                    border: 1px solid rgba(208,218,232,0.92);
                    border-radius: 16px;
                }
                QFrame#profileToolbarCard {
                    background: rgba(247,250,255,0.95);
                    border: 1px solid rgba(208,218,232,0.92);
                    border-radius: 16px;
                }
                QFrame#profileRuntimeMetricCard {
                    background: rgba(244,248,253,0.98);
                    border: 1px solid rgba(208,218,232,0.86);
                    border-radius: 12px;
                }
                QFrame#profileStickyFooter {
                    background: rgba(246,249,255,0.96);
                    border: 1px solid rgba(208,218,232,0.92);
                    border-radius: 16px;
                }
                QSplitter::handle:horizontal {
                    width: 10px;
                    background: transparent;
                }
                QScrollArea {
                    background: transparent;
                    border: none;
                }
                """
            )
            self._init_ui()

        def _available_geometry(self):
            screen = None
            parent_widget = self.parentWidget()
            if parent_widget is not None:
                parent_window = parent_widget.window()
                if parent_window is not None and parent_window.windowHandle() is not None:
                    screen = parent_window.windowHandle().screen()
            if screen is None:
                app = QApplication.instance()
                if app is not None:
                    screen = app.primaryScreen()
            return screen.availableGeometry() if screen is not None else None

        def _resolve_minimum_dialog_size(self):
            avail = self._available_geometry()
            if avail is None:
                return QSize(self._DESIGN_MIN_WIDTH, self._DESIGN_MIN_HEIGHT)
            width = min(self._DESIGN_MIN_WIDTH, max(820, avail.width() - self._MIN_SCREEN_MARGIN))
            height = min(self._DESIGN_MIN_HEIGHT, max(540, avail.height() - self._MIN_SCREEN_MARGIN))
            return QSize(width, height)

        def _resolve_default_dialog_size(self, avail, min_size):
            if avail is None:
                return QSize(self._DESIGN_DEFAULT_WIDTH, self._DESIGN_DEFAULT_HEIGHT)
            max_w = max(min_size.width(), int(avail.width() * 0.96))
            max_h = max(min_size.height(), int(avail.height() * 0.92))
            preferred_w = min(self._DEFAULT_MAX_WIDTH, int(round(avail.width() * self._DEFAULT_WIDTH_RATIO)))
            preferred_h = min(self._DEFAULT_MAX_HEIGHT, int(round(avail.height() * self._DEFAULT_HEIGHT_RATIO)))
            width = min(max(min_size.width(), preferred_w), max_w)
            height = min(max(min_size.height(), preferred_h), max_h)
            return QSize(width, height)

        def _apply_initial_size(self):
            avail = self._available_geometry()
            min_size = self._dialog_min_size
            if avail is not None:
                default_size = self._resolve_default_dialog_size(avail, min_size)
                default_w = default_size.width()
                default_h = default_size.height()
                max_w = max(min_size.width(), int(avail.width() * 0.96))
                max_h = max(min_size.height(), int(avail.height() * 0.92))
            else:
                default_w, default_h = self._DESIGN_DEFAULT_WIDTH, self._DESIGN_DEFAULT_HEIGHT
                max_w, max_h = 1400, 900
            width = self._read_setting_int(self._UI_SIZE_W_KEY, default_w)
            height = self._read_setting_int(self._UI_SIZE_H_KEY, default_h)
            width = max(min_size.width(), min(width, max_w))
            height = max(min_size.height(), min(height, max_h))
            self.resize(width, height)

        def _read_setting_int(self, key, default_value):
            raw = self._ui_settings.value(key, default_value)
            try:
                return int(float(raw))
            except Exception:
                return int(default_value)

        def minimumSizeHint(self):
            return QSize(self.minimumWidth(), self.minimumHeight())

        def sizeHint(self):
            avail = self._available_geometry()
            if avail is None:
                return QSize(
                    max(self.minimumWidth(), self._DESIGN_DEFAULT_WIDTH),
                    max(self.minimumHeight(), self._DESIGN_DEFAULT_HEIGHT),
                )
            return self._resolve_default_dialog_size(avail, self.minimumSizeHint())

        def closeEvent(self, event):
            self._persist_ui_state()
            super().closeEvent(event)

        def resizeEvent(self, event):
            super().resizeEvent(event)
            self._update_responsive_layout_mode()

        def showEvent(self, event):
            super().showEvent(event)
            self._update_responsive_layout_mode()

        def _persist_ui_state(self):
            size = self.size()
            self._ui_settings.setValue(self._UI_SIZE_W_KEY, int(size.width()))
            self._ui_settings.setValue(self._UI_SIZE_H_KEY, int(size.height()))

        def _make_wrap_caption(self, text=""):
            return WrapCaptionLabel(text, self)

        def _init_ui(self):
            root = QVBoxLayout(self)
            root.setContentsMargins(12, 10, 12, 10)
            root.setSpacing(10)

            self._workbench_splitter = QSplitter(Qt.Horizontal, self)
            self._workbench_splitter.setChildrenCollapsible(False)
            self._parameter_card = self._build_parameter_card()
            self._rows_card = self._build_rows_card()
            self._workbench_splitter.addWidget(self._parameter_card)
            self._workbench_splitter.addWidget(self._rows_card)
            self._workbench_splitter.setStretchFactor(0, 0)
            self._workbench_splitter.setStretchFactor(1, 1)
            root.addWidget(self._workbench_splitter, 1)

            footer = QFrame(self)
            footer.setObjectName("profileStickyFooter")
            btn_row = QHBoxLayout(footer)
            btn_row.setContentsMargins(14, 10, 14, 10)
            btn_row.setSpacing(8)
            self._btn_reset = PushButton("恢复默认")
            self._btn_reset.clicked.connect(self._reset_defaults)
            btn_row.addWidget(self._btn_reset)
            btn_row.addStretch(1)
            self._btn_cancel = PushButton("取消")
            self._btn_cancel.clicked.connect(self.reject)
            self._btn_ok = PrimaryPushButton("确定")
            self._btn_ok.clicked.connect(self._on_confirm)
            btn_row.addWidget(self._btn_cancel)
            btn_row.addWidget(self._btn_ok)
            root.addWidget(footer, 0)

            QShortcut(QKeySequence(Qt.Key_Escape), self, self.reject)
            QShortcut(QKeySequence(Qt.Key_Return), self, self._on_confirm)
            QShortcut(QKeySequence("Ctrl+Up"), self, lambda: self._move_selected_row(-1))
            QShortcut(QKeySequence("Ctrl+Down"), self, lambda: self._move_selected_row(1))
            QShortcut(QKeySequence("Ctrl+Home"), self, lambda: self._move_selected_row_to_edge(True))
            QShortcut(QKeySequence("Ctrl+End"), self, lambda: self._move_selected_row_to_edge(False))
            QShortcut(QKeySequence(Qt.Key_Delete), self, self._disable_selected_row)

            self._render()

        def _build_parameter_card(self):
            pane = QFrame(self)
            pane.setObjectName("profileWorkbenchPanel")
            pane.setMinimumWidth(340)
            pane.setMaximumWidth(620)

            pane_lay = QVBoxLayout(pane)
            pane_lay.setContentsMargins(0, 0, 0, 0)
            pane_lay.setSpacing(0)

            self._body_scroll = QScrollArea(self)
            self._body_scroll.setWidgetResizable(True)
            self._body_scroll.setFrameShape(QFrame.NoFrame)
            self._body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

            self._body_content_widget = QWidget(self)
            self._parameter_content_layout = QVBoxLayout(self._body_content_widget)
            self._parameter_content_layout.setSizeConstraint(QLayout.SetMinAndMaxSize)
            self._parameter_content_layout.setContentsMargins(8, 8, 8, 8)
            self._parameter_content_layout.setSpacing(8)

            self._parameter_left_section = self._build_basic_parameter_section()
            self._parameter_right_section = self._build_runtime_section()
            self._parameter_content_layout.addWidget(self._parameter_left_section, 0)
            self._parameter_content_layout.addWidget(self._parameter_right_section, 0)
            self._parameter_content_layout.addStretch(1)

            self._body_scroll.setWidget(self._body_content_widget)
            pane_lay.addWidget(self._body_scroll, 1)
            return pane

        def _build_rows_card(self):
            pane = QFrame(self)
            pane.setObjectName("profileWorkbenchPanel")
            pane.setMinimumWidth(480)

            pane_lay = QVBoxLayout(pane)
            pane_lay.setContentsMargins(8, 8, 8, 8)
            pane_lay.setSpacing(8)

            self._toolbar_card = self._build_toolbar_card()
            self._enabled_section = self._build_enabled_section()
            self._candidate_section = self._build_candidate_section()
            pane_lay.addWidget(self._toolbar_card, 0)
            pane_lay.addWidget(self._enabled_section, 0)
            pane_lay.addWidget(self._candidate_section, 0)
            pane_lay.addStretch(1)
            return pane

        def _build_basic_parameter_section(self):
            section = QFrame(self)
            section.setObjectName("profileSectionCard")
            lay = QVBoxLayout(section)
            lay.setContentsMargins(12, 12, 12, 12)
            lay.setSpacing(8)

            lay.addWidget(BodyLabel("基础参数"))
            lay.addWidget(
                self._make_wrap_caption("这些设置会和项目配置一起保存，用于控制文字字高、旋转和纵断面比例。")
            )

            basic_form = QGridLayout()
            basic_form.setHorizontalSpacing(8)
            basic_form.setVerticalSpacing(8)
            basic_form.setColumnStretch(0, 0)
            basic_form.setColumnStretch(1, 0)
            basic_form.setColumnStretch(2, 1)
            decimal_key = self._mode_spec["decimal_entry_key"]
            self._add_entry_row(basic_form, 0, "字高", "text_height", "用于 AutoCAD 文字字高。")
            self._add_entry_row(basic_form, 1, "旋转角度", "rotation", "默认沿纵断面竖排显示。")
            self._add_entry_row(
                basic_form,
                2,
                self._mode_spec["decimal_entry_label"],
                decimal_key,
                self._mode_spec["decimal_entry_hint"],
            )
            self._add_entry_row(basic_form, 3, "X方向比例(1:N)", "scale_x", "如 1:1000，则输入 1000。")
            self._add_entry_row(basic_form, 4, "Y方向比例(1:N)", "scale_y", "如 1:1000，则输入 1000。")
            lay.addLayout(basic_form)
            return section

        def _build_runtime_section(self):
            section = QFrame(self)
            section.setObjectName("profileSectionCard")
            lay = QVBoxLayout(section)
            lay.setContentsMargins(12, 12, 12, 12)
            lay.setSpacing(8)

            lay.addWidget(BodyLabel("启用行实时参数"))
            lay.addWidget(
                self._make_wrap_caption("这里只镜像当前已启用的行。顺序、启停和拖拽一改，左侧实时参数就立即同步。")
            )

            metrics = QFrame(self)
            metrics.setObjectName("profileRuntimeMetricCard")
            metrics_lay = QGridLayout(metrics)
            metrics_lay.setContentsMargins(8, 8, 8, 8)
            metrics_lay.setHorizontalSpacing(6)
            metrics_lay.setVerticalSpacing(6)
            metric_defs = [
                ("enabled_count", "启用项数"),
                ("total_height", "内容总高"),
                ("line_height", "生效竖线高度"),
                ("min_line_height", "最小竖线参数"),
            ]
            for index, (key, title) in enumerate(metric_defs):
                row = index // 2
                col = (index % 2) * 2
                metrics_lay.addWidget(CaptionLabel(title), row, col)
                chip = self._make_runtime_value_chip("--")
                chip.setMinimumWidth(88)
                metrics_lay.addWidget(chip, row, col + 1)
                self._runtime_metric_labels[key] = chip
            metrics_lay.setColumnStretch(0, 0)
            metrics_lay.setColumnStretch(1, 1)
            metrics_lay.setColumnStretch(2, 0)
            metrics_lay.setColumnStretch(3, 1)
            lay.addWidget(metrics)

            headers = QGridLayout()
            headers.setHorizontalSpacing(8)
            headers.setVerticalSpacing(4)
            headers.addWidget(CaptionLabel("行内容"), 0, 0)
            headers.addWidget(CaptionLabel("实时Y"), 0, 1)
            headers.addWidget(CaptionLabel("来源"), 0, 2)
            headers.setColumnStretch(0, 3)
            headers.setColumnStretch(1, 0)
            headers.setColumnStretch(2, 2)
            lay.addLayout(headers)

            self._runtime_rows_widget = QWidget(self)
            self._runtime_rows_layout = QGridLayout(self._runtime_rows_widget)
            self._runtime_rows_layout.setContentsMargins(0, 0, 0, 0)
            self._runtime_rows_layout.setHorizontalSpacing(6)
            self._runtime_rows_layout.setVerticalSpacing(4)
            self._runtime_rows_layout.setColumnStretch(0, 3)
            self._runtime_rows_layout.setColumnStretch(1, 0)
            self._runtime_rows_layout.setColumnStretch(2, 2)
            lay.addWidget(self._runtime_rows_widget)

            self._runtime_summary_label = self._make_wrap_caption("")
            lay.addWidget(self._runtime_summary_label)
            return section

        def _build_toolbar_card(self):
            card = QFrame(self)
            card.setObjectName("profileToolbarCard")
            lay = QVBoxLayout(card)
            lay.setContentsMargins(12, 10, 12, 10)
            lay.setSpacing(8)

            lay.addWidget(BodyLabel(self._mode_spec["toolbar_title"]))
            if self._mode_spec["toolbar_hint"]:
                lay.addWidget(self._make_wrap_caption(self._mode_spec["toolbar_hint"]))

            if not self._mode_spec["read_only_rows"]:
                action_row = QHBoxLayout()
                action_row.setContentsMargins(0, 0, 0, 0)
                action_row.setSpacing(6)
                btn_preset = PushButton("应用亭子口二期顶建/可研阶段模板")
                btn_preset.clicked.connect(self._apply_tingzikou_preset)
                btn_restore = PushButton("恢复推荐")
                btn_restore.clicked.connect(self._restore_recommended_rows)
                btn_enable_all = PushButton("全启用")
                btn_enable_all.clicked.connect(self._enable_all_rows)
                btn_disable_all = PushButton("全停用")
                btn_disable_all.clicked.connect(self._disable_all_rows)
                action_row.addWidget(btn_preset)
                action_row.addWidget(btn_restore)
                action_row.addWidget(btn_enable_all)
                action_row.addWidget(btn_disable_all)
                action_row.addStretch(1)
                lay.addLayout(action_row)
            return card

        def _build_enabled_section(self):
            section = QFrame(self)
            section.setObjectName("profileSectionCard")
            lay = QVBoxLayout(section)
            lay.setContentsMargins(12, 12, 12, 12)
            lay.setSpacing(8)

            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(8)
            header.addWidget(BodyLabel(self._mode_spec["enabled_title"]))
            self._enabled_caption_label = CaptionLabel("")
            header.addWidget(self._enabled_caption_label)
            header.addStretch(1)
            if not self._mode_spec["read_only_rows"]:
                btn_up = PushButton("上移")
                btn_up.clicked.connect(lambda: self._move_selected_row(-1))
                btn_down = PushButton("下移")
                btn_down.clicked.connect(lambda: self._move_selected_row(1))
                btn_top = PushButton("置顶")
                btn_top.clicked.connect(lambda: self._move_selected_row_to_edge(True))
                btn_bottom = PushButton("置底")
                btn_bottom.clicked.connect(lambda: self._move_selected_row_to_edge(False))
                header.addWidget(btn_up)
                header.addWidget(btn_down)
                header.addWidget(btn_top)
                header.addWidget(btn_bottom)
            lay.addLayout(header)

            if self._mode_spec["enabled_hint"]:
                lay.addWidget(self._make_wrap_caption(self._mode_spec["enabled_hint"]))

            self._enabled_list = AutoHeightListWidget(
                allow_reorder=not self._mode_spec["read_only_rows"],
                auto_height=False,
                parent=self,
            )
            self._enabled_list.setSpacing(4)
            self._enabled_list.setMinimumHeight(0)
            self._enabled_list.enabledRowDropped.connect(self._on_enabled_row_dropped)
            self._enabled_list.toggleRequested.connect(
                lambda rid: self._toggle_current_row(rid, show_feedback=True)
            )
            self._enabled_list.itemDoubleClicked.connect(
                lambda _item: self._toggle_current_row(show_feedback=True)
            )
            self._enabled_list.currentItemChanged.connect(
                lambda current, previous: self._on_list_current_changed("enabled", current, previous)
            )
            if not self._mode_spec["read_only_rows"]:
                self._enabled_list.customContextMenuRequested.connect(
                    lambda pos: self._show_grouped_row_context_menu("enabled", pos)
                )
            self._row_list = self._enabled_list
            lay.addWidget(self._enabled_list, 1)
            return section

        def _build_candidate_section(self):
            section = QFrame(self)
            section.setObjectName("profileSectionCard")
            lay = QVBoxLayout(section)
            lay.setContentsMargins(12, 12, 12, 12)
            lay.setSpacing(8)

            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(8)
            header.addWidget(BodyLabel(self._mode_spec["candidate_title"]))
            self._candidate_caption_label = CaptionLabel("")
            header.addWidget(self._candidate_caption_label)
            header.addStretch(1)
            self._candidate_toggle_btn = ToolButton(self)
            if self._ICON_COLLAPSED is not None:
                self._candidate_toggle_btn.setIcon(self._ICON_COLLAPSED)
            self._candidate_toggle_btn.clicked.connect(self._toggle_candidate_section)
            header.addWidget(self._candidate_toggle_btn)
            lay.addLayout(header)

            self._candidate_body = QWidget(self)
            candidate_body_lay = QVBoxLayout(self._candidate_body)
            candidate_body_lay.setContentsMargins(0, 0, 0, 0)
            candidate_body_lay.setSpacing(6)

            self._candidate_list = AutoHeightListWidget(allow_reorder=False, auto_height=False, parent=self)
            self._candidate_list.setSpacing(6)
            self._candidate_list.setMinimumHeight(0)
            self._candidate_list.toggleRequested.connect(
                lambda rid: self._toggle_current_row(rid, show_feedback=True)
            )
            self._candidate_list.itemDoubleClicked.connect(
                lambda _item: self._toggle_current_row(show_feedback=True)
            )
            self._candidate_list.currentItemChanged.connect(
                lambda current, previous: self._on_list_current_changed("candidate", current, previous)
            )
            if not self._mode_spec["read_only_rows"]:
                self._candidate_list.customContextMenuRequested.connect(
                    lambda pos: self._show_grouped_row_context_menu("candidate", pos)
                )
            candidate_body_lay.addWidget(self._candidate_list, 1)
            lay.addWidget(self._candidate_body)
            return section

        def _add_entry_row(self, layout, row, label, key, hint):
            layout.addWidget(QLabel(f"{label}:"), row, 0)
            entry = LineEdit()
            entry.setText(self._state.parameter_texts.get(key, ""))
            entry.setMinimumWidth(144)
            entry.setMaximumWidth(196)
            entry.textChanged.connect(lambda text, field=key: self._on_parameter_text_changed(field, text))
            layout.addWidget(entry, row, 1)
            layout.addWidget(self._make_wrap_caption(hint) if hint else CaptionLabel(""), row, 2)
            self._entries[key] = entry

        def _candidate_all_row_ids(self):
            return list(self._state.all_candidate_row_ids())

        def _active_candidate_list_widget(self):
            return self._candidate_list

        def _candidate_visible_rows(self, candidate_count=None):
            if candidate_count is None:
                candidate_count = len(self._candidate_all_row_ids())
            candidate_count = max(0, int(candidate_count))
            return min(candidate_count, self._CANDIDATE_VISIBLE_ROW_LIMIT)

        def _on_parameter_text_changed(self, key, text):
            self._state.set_basic_value(key, text)
            self._render_runtime_advanced_view()

        def _toggle_candidate_section(self):
            self._state.set_candidate_expanded(not self._state.candidate_expanded)
            self._refresh_all_row_lists()

        def _make_runtime_value_chip(self, text):
            label = QLabel(text)
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumWidth(76)
            label.setStyleSheet(
                "color:#173A63; background: rgba(255,255,255,0.94);"
                "border: 1px solid rgba(198,210,224,0.92); border-radius: 8px;"
                "padding: 3px 10px; font-family:'Consolas','Microsoft YaHei'; font-size:12px;"
            )
            return label

        def _clear_layout_widgets(self, layout):
            if layout is None:
                return
            while layout.count():
                item = layout.takeAt(0)
                child_layout = item.layout()
                child_widget = item.widget()
                if child_layout is not None:
                    self._clear_layout_widgets(child_layout)
                if child_widget is not None:
                    child_widget.deleteLater()

        def _row_display(self, rid, enabled, order_index=None):
            row_def = self._mode_spec["row_def_map"][rid]
            title = row_def["label"]
            if enabled and order_index is not None:
                title = f"{order_index + 1:02d}. {title}"
            subtitle_parts = [
                self._mode_spec["subtitle_enabled"] if enabled else self._mode_spec["subtitle_disabled"]
            ]
            hint = str(row_def.get("hint", "") or "").strip()
            if hint:
                subtitle_parts.append(hint)
            return title, " | ".join(subtitle_parts), rid in self._mode_spec["recommended_row_ids"]

        def _create_row_widget(self, rid, enabled, *, display_variant="standard"):
            order_index = self._state.enabled_row_ids.index(rid) if enabled and rid in self._state.enabled_row_ids else None
            title, subtitle, recommended = self._row_display(rid, enabled, order_index)
            widget = FluentProfileRowItemWidget(
                title,
                subtitle,
                enabled,
                recommended,
                display_variant=display_variant,
            )
            widget.checkbox.stateChanged.connect(
                lambda _state, row_id=rid: self._on_row_widget_checkbox_changed(row_id)
            )
            widget.clicked.connect(
                lambda row_id=rid, role=("enabled" if enabled else "candidate"): self._set_current_row_id(row_id, role)
            )
            widget.doubleClicked.connect(
                lambda row_id=rid: self._toggle_current_row(row_id, show_feedback=True)
            )
            if enabled:
                widget.drag_handle.dragRequested.connect(
                    lambda row_id=rid: self._enabled_list.start_drag_for_row_id(row_id)
                )
            if self._mode_spec["read_only_rows"]:
                widget.checkbox.setEnabled(False)
                widget.drag_handle.hide()
            return widget

        def _on_row_widget_checkbox_changed(self, rid):
            if self._row_updating:
                return
            widget = self._row_widgets.get(rid)
            if widget is None:
                return
            self._set_current_row_id(rid, "enabled" if rid in self._state.enabled_row_ids else "candidate")
            self._set_row_enabled(rid, widget.checkbox.isChecked(), show_feedback=True)

        def _refresh_section_labels(self):
            if self._enabled_caption_label is not None:
                self._enabled_caption_label.setText(f"{len(self._state.enabled_row_ids)} 项")
            if self._candidate_caption_label is not None:
                self._candidate_caption_label.setText(f"{len(self._candidate_all_row_ids())} 项")

        def _apply_scrollable_list_height(self, list_widget, visible_rows, *, clamp_to_count=True, lock_height=False):
            if list_widget is None:
                return
            visible_rows = max(0, int(visible_rows))
            preferred_height = (
                0
                if visible_rows <= 0
                else list_widget.content_height_for_rows(visible_rows, clamp_to_count=clamp_to_count)
            )
            list_widget.set_preferred_height(preferred_height)
            list_widget.setMinimumHeight(preferred_height if lock_height and preferred_height > 0 else 0)
            list_widget.setMaximumHeight(preferred_height if preferred_height > 0 else 0)
            list_widget.updateGeometry()

        def _update_row_list_height_policy(self):
            enabled_count = len(self._state.enabled_row_ids)
            candidate_count = len(self._candidate_all_row_ids())
            candidate_visible = (self._state.candidate_expanded and candidate_count > 0) or self._candidate_body_is_forced_visible()
            candidate_visible_rows = self._candidate_visible_rows(candidate_count) if candidate_visible else 0
            self._apply_scrollable_list_height(
                self._candidate_list,
                candidate_visible_rows,
                lock_height=candidate_visible_rows > 0,
            )

            enabled_visible_rows = min(max(enabled_count, 1), self._ENABLED_VISIBLE_ROW_LIMIT)
            self._apply_scrollable_list_height(self._enabled_list, enabled_visible_rows)

        def _sync_auto_height_lists(self):
            if self._enabled_list is not None:
                self._enabled_list.recalculate_height()
            if self._candidate_list is not None:
                self._candidate_list.recalculate_height()

        def _build_runtime_view_input_settings(self):
            return self._state.build_runtime_input(self._defaults)

        def _render_runtime_advanced_view(self):
            if self._runtime_rows_layout is None:
                return
            runtime = self._state.runtime_view(self._defaults)
            enabled_rows = list(runtime.get("enabled_runtime_rows") or [])
            self._runtime_row_labels = {}
            self._clear_layout_widgets(self._runtime_rows_layout)

            metric_values = {
                "enabled_count": str(len(runtime.get("enabled_row_ids") or [])),
                "total_height": format_number(runtime["total_height"]),
                "line_height": format_number(runtime["line_height"]),
                "min_line_height": format_number(runtime["min_line_height"]),
            }
            for key, chip in self._runtime_metric_labels.items():
                if chip is not None:
                    chip.setText(metric_values.get(key, "--"))

            if not enabled_rows:
                empty_label = self._make_wrap_caption(self._mode_spec["empty_runtime_hint"])
                self._runtime_rows_layout.addWidget(empty_label, 0, 0, 1, 3)
            else:
                for row_index, row in enumerate(enabled_rows):
                    title = QLabel(f"{row['order']:02d}. {row['label']}")
                    title.setStyleSheet("color:#24384D; font-size:13px; font-weight:600;")
                    value = self._make_runtime_value_chip(format_number(row["text_y"]))
                    source = self._make_wrap_caption(row.get("source_label", ""))
                    self._runtime_rows_layout.addWidget(title, row_index, 0)
                    self._runtime_rows_layout.addWidget(value, row_index, 1)
                    self._runtime_rows_layout.addWidget(source, row_index, 2)
                    self._runtime_row_labels[row["id"]] = {
                        "title": title,
                        "value": value,
                        "source": source,
                    }

            divider_row = len(enabled_rows)
            divider = QFrame(self)
            divider.setFrameShape(QFrame.HLine)
            divider.setFrameShadow(QFrame.Sunken)
            divider.setStyleSheet("color: rgba(210,218,229,0.95);")
            self._runtime_rows_layout.addWidget(divider, divider_row, 0, 1, 3)

            line_row = divider_row + 1
            line_title = QLabel("生效竖线高度")
            line_title.setStyleSheet("color:#24384D; font-size:13px; font-weight:600;")
            line_value = self._make_runtime_value_chip(format_number(runtime["line_height"]))
            line_source = self._make_wrap_caption("max(内容总高, 最小竖线参数)")
            self._runtime_rows_layout.addWidget(line_title, line_row, 0)
            self._runtime_rows_layout.addWidget(line_value, line_row, 1)
            self._runtime_rows_layout.addWidget(line_source, line_row, 2)
            self._runtime_row_labels["y_line_height"] = {
                "title": line_title,
                "value": line_value,
                "source": line_source,
            }

            if self._runtime_summary_label is not None:
                self._runtime_summary_label.setText(
                    f"实时汇总：启用 {len(runtime['enabled_row_ids'])} 项 / "
                    f"内容总高 {format_number(runtime['total_height'])} / "
                    f"生效竖线高度 {format_number(runtime['line_height'])} / "
                    f"最小竖线参数 {format_number(runtime['min_line_height'])}"
                )

        def _candidate_body_is_forced_visible(self):
            return not bool(self._state.enabled_row_ids) and bool(self._candidate_all_row_ids())

        def _refresh_all_row_lists(self, *, scroll_to_current=True):
            if not self._enabled_list or not self._candidate_list:
                return
            self._state.normalize_row_model()
            candidate_all_ids = self._candidate_all_row_ids()
            candidate_ids = list(candidate_all_ids)
            self._state.ensure_selection()
            self._row_updating = True
            try:
                self._enabled_list.clear()
                self._candidate_list.clear()
                self._row_widgets = {}
                for rid in self._state.enabled_row_ids:
                    item = QListWidgetItem()
                    item.setData(Qt.UserRole, rid)
                    widget = self._create_row_widget(rid, True)
                    self._enabled_list.addItem(item)
                    self._enabled_list.setItemWidget(item, widget)
                    self._row_widgets[rid] = widget
                for rid in candidate_ids:
                    item = QListWidgetItem()
                    item.setData(Qt.UserRole, rid)
                    widget = self._create_row_widget(rid, False)
                    self._candidate_list.addItem(item)
                    self._candidate_list.setItemWidget(item, widget)
                    self._row_widgets[rid] = widget
            finally:
                self._row_updating = False

            candidate_visible = (self._state.candidate_expanded and bool(candidate_all_ids)) or self._candidate_body_is_forced_visible()
            if self._candidate_section is not None:
                self._candidate_section.setVisible(bool(candidate_all_ids))
            if self._candidate_body is not None:
                self._candidate_body.setVisible(candidate_visible)
            if self._candidate_toggle_btn is not None:
                icon = self._ICON_EXPANDED if candidate_visible else self._ICON_COLLAPSED
                if icon is not None:
                    self._candidate_toggle_btn.setIcon(icon)
            self._refresh_section_labels()
            self._sync_current_selection(scroll_to_current=scroll_to_current)
            self._sync_auto_height_lists()
            self._render_runtime_advanced_view()
            self._update_responsive_layout_mode()

        def _render(self, *, scroll_to_current=True):
            self._refresh_all_row_lists(scroll_to_current=scroll_to_current)

        def _selected_row_id(self):
            return str(self._state.selected_row_id or "").strip()

        def _find_item_in_list(self, list_widget, rid):
            if list_widget is None:
                return None, -1
            for row in range(list_widget.count()):
                item = list_widget.item(row)
                if item is not None and str(item.data(Qt.UserRole) or "").strip() == rid:
                    return item, row
            return None, -1

        def _sync_current_selection(self, *, scroll_to_current=True):
            rid = self._selected_row_id()
            self._selection_syncing = True
            try:
                if self._enabled_list is not None:
                    self._enabled_list.set_suspend_scroll_to_current(not scroll_to_current)
                if self._candidate_list is not None:
                    self._candidate_list.set_suspend_scroll_to_current(not scroll_to_current)
                enabled_item, _ = self._find_item_in_list(self._enabled_list, rid)
                candidate_item, _ = self._find_item_in_list(self._candidate_list, rid)
                if enabled_item is not None:
                    if self._candidate_list is not None:
                        self._candidate_list.clearSelection()
                        self._candidate_list.setCurrentItem(None)
                    self._enabled_list.setCurrentItem(enabled_item)
                    if scroll_to_current:
                        self._enabled_list.scrollToItem(enabled_item, QAbstractItemView.PositionAtCenter)
                elif candidate_item is not None:
                    if self._enabled_list is not None:
                        self._enabled_list.clearSelection()
                        self._enabled_list.setCurrentItem(None)
                    self._candidate_list.setCurrentItem(candidate_item)
                    if scroll_to_current and (
                        self._state.candidate_expanded or self._candidate_body_is_forced_visible()
                    ):
                        self._candidate_list.scrollToItem(candidate_item, QAbstractItemView.PositionAtCenter)
                else:
                    if self._enabled_list is not None:
                        self._enabled_list.clearSelection()
                        self._enabled_list.setCurrentItem(None)
                    if self._candidate_list is not None:
                        self._candidate_list.clearSelection()
                        self._candidate_list.setCurrentItem(None)
            finally:
                if self._enabled_list is not None:
                    self._enabled_list.set_suspend_scroll_to_current(False)
                if self._candidate_list is not None:
                    self._candidate_list.set_suspend_scroll_to_current(False)
                self._selection_syncing = False
            self._update_row_widget_selection()

        def _set_current_row_id(self, rid, role=None, prefer_enabled=None, *, scroll_to_current=True):
            if prefer_enabled is True:
                role = "enabled"
            elif prefer_enabled is False:
                role = "candidate"
            self._state.set_selected_row(rid, role)
            self._sync_current_selection(scroll_to_current=scroll_to_current)

        def _capture_body_scroll_value(self):
            values = {}
            if self._body_scroll is not None:
                values["parameter"] = int(self._body_scroll.verticalScrollBar().value())
            for role, list_widget in (
                ("enabled", self._enabled_list),
                ("candidate", self._active_candidate_list_widget()),
            ):
                if list_widget is None:
                    continue
                bar = list_widget.verticalScrollBar()
                current_value = int(bar.value())
                anchor_item = list_widget.itemAt(QPoint(8, 8))
                anchor_rid = str(anchor_item.data(Qt.UserRole) or "").strip() if anchor_item is not None else ""
                anchor_offset = 0
                if anchor_item is not None:
                    rect = list_widget.visualItemRect(anchor_item)
                    anchor_offset = int(rect.top())
                values[role] = {
                    "value": current_value,
                    "at_top": current_value <= int(bar.minimum()) + 2,
                    "at_bottom": current_value >= int(bar.maximum()) - 2,
                    "anchor_rid": anchor_rid,
                    "anchor_offset": anchor_offset,
                }
            return values

        def _restore_body_scroll_value(self, value):
            if not isinstance(value, dict):
                return
            if self._body_scroll is not None and "parameter" in value:
                bar = self._body_scroll.verticalScrollBar()
                desired = max(int(bar.minimum()), min(int(value["parameter"]), int(bar.maximum())))
                bar.setValue(desired)
            for role, list_widget in (
                ("enabled", self._enabled_list),
                ("candidate", self._active_candidate_list_widget()),
            ):
                if list_widget is None or role not in value:
                    continue
                state = value[role] if isinstance(value[role], dict) else {"value": value[role]}
                bar = list_widget.verticalScrollBar()
                if state.get("at_top"):
                    bar.setValue(int(bar.minimum()))
                    continue
                if state.get("at_bottom"):
                    bar.setValue(int(bar.maximum()))
                    continue
                anchor_rid = str(state.get("anchor_rid") or "").strip()
                if anchor_rid:
                    item, _ = self._find_item_in_list(list_widget, anchor_rid)
                    if item is not None:
                        list_widget.scrollToItem(item, QAbstractItemView.PositionAtTop)
                        desired = int(bar.value()) - int(state.get("anchor_offset", 0))
                        desired = max(int(bar.minimum()), min(desired, int(bar.maximum())))
                        bar.setValue(desired)
                        continue
                desired = max(int(bar.minimum()), min(int(state.get("value", 0)), int(bar.maximum())))
                bar.setValue(desired)

        def _focus_active_row_list(self):
            target = self._active_candidate_list_widget() if self._state.active_list_role == "candidate" else self._enabled_list
            if target is None:
                return
            target.setFocus(Qt.OtherFocusReason)

        def _ensure_active_selection_visible(self):
            rid = self._selected_row_id()
            if not rid:
                return
            if rid in self._state.enabled_row_ids:
                list_widget = self._enabled_list
            else:
                list_widget = self._active_candidate_list_widget()
            if list_widget is None:
                return
            item, _ = self._find_item_in_list(list_widget, rid)
            if item is None:
                return
            if not list_widget.viewport().rect().intersects(list_widget.visualItemRect(item)):
                list_widget.scrollToItem(item, QAbstractItemView.EnsureVisible)

        def _on_list_current_changed(self, role, current, previous):
            if self._selection_syncing or current is None:
                self._update_row_widget_selection()
                return
            rid = str(current.data(Qt.UserRole) or "").strip()
            self._state.set_selected_row(rid, role)
            other = self._candidate_list if role == "enabled" else self._enabled_list
            self._selection_syncing = True
            try:
                if other is not None:
                    other.clearSelection()
                    other.setCurrentItem(None)
            finally:
                self._selection_syncing = False
            self._update_row_widget_selection()

        def _update_row_widget_selection(self):
            current_rid = self._selected_row_id()
            for rid, widget in self._row_widgets.items():
                if widget is not None:
                    widget.set_selected(rid == current_rid)

        def _show_grouped_row_context_menu(self, role, pos):
            if self._mode_spec["read_only_rows"]:
                return
            list_widget = self._enabled_list if role == "enabled" else self._active_candidate_list_widget()
            if list_widget is None:
                return
            item = list_widget.itemAt(pos)
            if item is None:
                return
            rid = str(item.data(Qt.UserRole) or "").strip()
            self._set_current_row_id(rid, role)
            menu = QMenu(self)
            if role == "enabled":
                action_toggle = menu.addAction("停用")
                menu.addSeparator()
                action_up = menu.addAction("上移")
                action_down = menu.addAction("下移")
                action_top = menu.addAction("置顶")
                action_bottom = menu.addAction("置底")
                row = self._state.enabled_row_ids.index(rid)
                action_up.setEnabled(row > 0)
                action_top.setEnabled(row > 0)
                action_down.setEnabled(row < len(self._state.enabled_row_ids) - 1)
                action_bottom.setEnabled(row < len(self._state.enabled_row_ids) - 1)
            else:
                action_toggle = menu.addAction("启用")
                action_up = action_down = action_top = action_bottom = None
            chosen = menu.exec(list_widget.viewport().mapToGlobal(pos))
            if chosen == action_toggle:
                self._set_row_enabled(rid, role != "enabled", show_feedback=True)
            elif chosen == action_up:
                self._move_selected_row(-1)
            elif chosen == action_down:
                self._move_selected_row(1)
            elif chosen == action_top:
                self._move_selected_row_to_edge(True)
            elif chosen == action_bottom:
                self._move_selected_row_to_edge(False)

        def _row_data_from_table(self):
            return self._state.row_items()

        def _set_row_enabled(self, rid, enabled, *, show_feedback=False):
            body_scroll_value = self._capture_body_scroll_value()
            if not self._state.set_row_enabled(rid, enabled):
                return
            self._render(scroll_to_current=False)
            self._restore_body_scroll_value(body_scroll_value)
            self._ensure_active_selection_visible()
            self._focus_active_row_list()
            self._restore_body_scroll_value(body_scroll_value)
            self._ensure_active_selection_visible()
            app = QApplication.instance()
            if app is not None:
                app.processEvents()
                self._restore_body_scroll_value(body_scroll_value)
                self._ensure_active_selection_visible()
            QTimer.singleShot(
                0,
                lambda state=body_scroll_value: (
                    self._restore_body_scroll_value(state),
                    self._ensure_active_selection_visible(),
                ),
            )
            QTimer.singleShot(
                0,
                lambda state=body_scroll_value: QTimer.singleShot(
                    0,
                    lambda nested_state=state: (
                        self._restore_body_scroll_value(nested_state),
                        self._ensure_active_selection_visible(),
                    ),
                ),
            )
            if show_feedback:
                row_label = self._mode_spec["row_def_map"][rid]["label"]
                info_bar = _info_bar()
                info_bar_position = _info_bar_position()
                if enabled:
                    info_bar.success(
                        "已启用",
                        f"{row_label} 已加入导出。",
                        parent=self,
                        position=info_bar_position.TOP_RIGHT,
                        duration=1200,
                    )
                else:
                    info_bar.info(
                        "已停用",
                        f"{row_label} 已移回可选项。",
                        parent=self,
                        position=info_bar_position.TOP_RIGHT,
                        duration=1200,
                    )

        def _toggle_current_row(self, rid=None, *, show_feedback=False):
            rid = str(rid or self._selected_row_id() or "").strip()
            if not rid:
                return
            self._set_row_enabled(rid, rid not in self._state.enabled_row_ids, show_feedback=show_feedback)

        def _reorder_enabled_row(self, rid, target_row):
            if self._state.reorder_enabled_row(rid, target_row):
                self._render()

        def _on_enabled_row_dropped(self, rid, target_row):
            if self._row_updating:
                return
            self._reorder_enabled_row(rid, target_row)

        def _enable_all_rows(self):
            if self._mode_spec["read_only_rows"]:
                return
            self._state.enable_all_rows()
            self._render()
            info_bar = _info_bar()
            info_bar_position = _info_bar_position()
            info_bar.success(
                "已全启用",
                "所有可选行已加入导出。",
                parent=self,
                position=info_bar_position.TOP_RIGHT,
                duration=1200,
            )

        def _disable_all_rows(self):
            if self._mode_spec["read_only_rows"]:
                return
            self._state.disable_all_rows()
            self._render()
            info_bar = _info_bar()
            info_bar_position = _info_bar_position()
            info_bar.info(
                "已全停用",
                "当前没有启用任何导出行。",
                parent=self,
                position=info_bar_position.TOP_RIGHT,
                duration=1200,
            )

        def _restore_recommended_rows(self):
            if self._mode_spec["read_only_rows"]:
                return
            self._state.restore_recommended_rows()
            self._render()
            info_bar = _info_bar()
            info_bar_position = _info_bar_position()
            info_bar.success(
                "已恢复推荐",
                "已切换到推荐的启用项组合。",
                parent=self,
                position=info_bar_position.TOP_RIGHT,
                duration=1200,
            )

        def _apply_tingzikou_preset(self):
            if self._mode_spec["read_only_rows"]:
                return
            self._state.apply_tingzikou_preset()
            self._render()
            info_bar = _info_bar()
            info_bar_position = _info_bar_position()
            info_bar.success(
                "模板已应用",
                "已切换为亭子口推荐顺序。",
                parent=self,
                position=info_bar_position.TOP_RIGHT,
                duration=1500,
            )

        def _move_selected_row(self, delta):
            if self._mode_spec["read_only_rows"]:
                return
            rid = self._selected_row_id()
            if not rid or rid not in self._state.enabled_row_ids:
                return
            row = self._state.enabled_row_ids.index(rid)
            target = row + int(delta)
            if target < 0 or target >= len(self._state.enabled_row_ids):
                return
            insertion_row = target + 1 if delta > 0 else target
            self._reorder_enabled_row(rid, insertion_row)

        def _move_selected_row_to_edge(self, to_top):
            if self._mode_spec["read_only_rows"]:
                return
            rid = self._selected_row_id()
            if not rid or rid not in self._state.enabled_row_ids:
                return
            target = 0 if to_top else len(self._state.enabled_row_ids) - 1
            self._reorder_enabled_row(rid, target)

        def _disable_selected_row(self):
            if self._mode_spec["read_only_rows"]:
                return
            rid = self._selected_row_id()
            if rid and rid in self._state.enabled_row_ids:
                self._set_row_enabled(rid, False, show_feedback=True)

        def _reset_defaults(self):
            self._state = TextExportSettingsState.from_defaults(
                self._reset_defaults_source,
                mode_spec=self._mode_spec,
            )
            for key, entry in self._entries.items():
                entry.setText(self._state.parameter_texts.get(key, ""))
            self._render()

        def _focus_invalid_entry(self, key):
            entry = self._entries.get(key)
            if not entry:
                return
            entry.setFocus()
            entry.selectAll()

        def _update_responsive_layout_mode(self):
            if self._workbench_splitter is None:
                return
            if not self._splitter_initialized:
                sizes = self._workbench_splitter.sizes()
                total = sum(sizes) if sizes else max(0, self.width() - 32)
                left_target = min(
                    self._parameter_card.maximumWidth(),
                    max(self._parameter_card.minimumWidth(), self._DESIGN_SPLITTER_LEFT),
                )
                if total > 0 and self._rows_card is not None:
                    left_target = min(
                        left_target,
                        max(self._parameter_card.minimumWidth(), total - self._rows_card.minimumWidth()),
                    )
                self._workbench_splitter.setSizes([left_target, max(1, total - left_target)])
                self._splitter_initialized = True

            self._update_row_list_height_policy()

        def _on_confirm(self):
            try:
                parsed = self._state.parsed_basic_values(strict=True)
                row_items = self._row_data_from_table()
                if not any(item.get("enabled") for item in row_items):
                    if self._row_list is not None:
                        self._row_list.setFocus()
                    raise ValueError("至少选择1项行内容", None)

                runtime_input = dict(self._defaults)
                runtime_input.update(self._state.compat_values)
                runtime_input.update(parsed)
                runtime_input["profile_row_items"] = row_items
                runtime = self._state.runtime_view(runtime_input)

                compatibility_values = {}
                runtime_values = runtime["legacy_writeback_values"]
                runtime_enabled_state = runtime["legacy_enabled_state"]
                for key in runtime_advanced_keys:
                    if key == "y_line_height":
                        compatibility_values[key] = float(
                            runtime_values.get(key, self._state.compat_values.get(key, 120))
                        )
                        continue
                    if runtime_enabled_state.get(key):
                        compatibility_values[key] = float(runtime_values.get(key))
                    else:
                        compatibility_values[key] = self._state.compat_values.get(
                            key, self._defaults.get(key)
                        )

                result = dict(self._defaults)
                result.update(parsed)
                result.update(compatibility_values)
                if self._mode_spec["read_only_rows"]:
                    preserved_row_items = list(self._standard_profile_row_items_snapshot)
                    result["profile_row_items"] = preserved_row_items
                    self.result = normalize_dialog_defaults(
                        result,
                        mode_spec=_resolve_mode_spec("standard"),
                    )
                    self.result["profile_row_items"] = preserved_row_items
                else:
                    result["profile_row_items"] = row_items
                    self.result = normalize_dialog_defaults(result, mode_spec=self._mode_spec)
                    self.result["profile_row_items"] = row_items
                self.accept()
            except ValueError as exc:
                message, key = exc.args
                if key:
                    self._focus_invalid_entry(key)
                _show_error(self, "输入错误", f"请输入有效的数值。\n{message}")

    TextExportSettingsDialog.__name__ = "TextExportSettingsDialog"
    return TextExportSettingsDialog


__all__ = ["AutoHeightListWidget", "create_text_export_settings_dialog"]

