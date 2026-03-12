# -*- coding: utf-8 -*-
"""
水面线面板 CAD 工具集

移植自原版 TK 的工程辅助功能，包括：
1. 生成纵断面表格（AutoCAD pl + -text 命令）
2. 生成bzzh2命令内容（ZDM用）
3. 建筑物名称上平面图（AutoCAD -TEXT 命令）
4. IP坐标及弯道参数表导出Excel
5. 断面汇总表
"""

import os
import sys
import math
import copy
import json

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QGroupBox, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QApplication, QScrollArea, QWidget, QComboBox, QFrame,
    QSizePolicy, QMenu, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, Signal, QMimeData, QSettings, QSize, QEvent
from PySide6.QtGui import QFont, QShortcut, QKeySequence, QDrag, QColor

from qfluentwidgets import (
    PushButton, PrimaryPushButton, LineEdit, SearchLineEdit,
    PopupTeachingTip, TeachingTipTailPosition, InfoBarIcon,
    ElevatedCardWidget, HeaderCardWidget, ListWidget, SegmentedWidget,
    ToolButton, FluentIcon, BodyLabel, CaptionLabel, InfoBar, InfoBarPosition, CheckBox,
)

from app_渠系计算前端.styles import (
    auto_resize_table, DIALOG_STYLE,
    fluent_info, fluent_error, fluent_question,
)

# 确保推求水面线模块可用
_pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_water_profile_dir = os.path.join(_pkg_root, '推求水面线')
if _water_profile_dir not in sys.path:
    sys.path.insert(0, _water_profile_dir)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

try:
    from models.data_models import ProjectSettings
    from models.enums import StructureType, InOutType
    MODELS_AVAILABLE = True
except ImportError:
    MODELS_AVAILABLE = False

_PRESSURIZED_PIPE_MATERIALS = [
    "PCCP管",
    "球墨铸铁管",
    "钢管",
    "钢筋混凝土管",
    "玻璃钢夹砂管",
]


class _ProfileRowItemWidget(QWidget):
    """列表行组件：使用 qfluentwidgets.CheckBox 保持 Fluent 原生勾选框样式。"""

    clicked = Signal()
    doubleClicked = Signal()
    dragRequested = Signal()

    def __init__(self, title, subtitle, enabled, parent=None):
        super().__init__(parent)
        self._press_pos = None
        self._selected = False
        self._enabled = bool(enabled)

        self.setObjectName("profileRowItem")
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(10)

        self.checkbox = CheckBox("")
        self.checkbox.setChecked(bool(enabled))
        self.checkbox.setFixedWidth(36)
        self.checkbox.clicked.connect(self.clicked)
        layout.addWidget(self.checkbox, 0, Qt.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        self.title_label = QLabel()
        self.title_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.subtitle_label = QLabel()
        self.subtitle_label.setTextInteractionFlags(Qt.NoTextInteraction)

        text_col.addWidget(self.title_label)
        text_col.addWidget(self.subtitle_label)
        layout.addLayout(text_col, 1)

        for child in (self.title_label, self.subtitle_label):
            child.installEventFilter(self)

        self.set_content(title, subtitle, enabled)
        self.set_selected(False)

    def set_content(self, title, subtitle, enabled):
        self._enabled = bool(enabled)
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)
        self._apply_visual_state()

    def set_selected(self, selected):
        self._selected = bool(selected)
        self._apply_visual_state()

    def _apply_visual_state(self):
        if self._selected:
            self.setStyleSheet(
                "QWidget#profileRowItem {"
                "background: rgba(210, 232, 255, 0.92);"
                "border: 1px solid rgba(0, 120, 212, 0.34);"
                "border-left: 4px solid #1596D1;"
                "border-radius: 8px;"
                "}"
            )
        else:
            self.setStyleSheet(
                "QWidget#profileRowItem {"
                "background: transparent;"
                "border: 1px solid transparent;"
                "border-radius: 8px;"
                "}"
            )
        if self._selected:
            self.title_label.setStyleSheet("color:#173A63; font-size:15px; font-weight:600;")
            self.subtitle_label.setStyleSheet("color:#34506E; font-size:13px;")
        elif self._enabled:
            self.title_label.setStyleSheet("color:#1E5EBE; font-size:15px;")
            self.subtitle_label.setStyleSheet("color:#2D5EAA; font-size:13px;")
        else:
            self.title_label.setStyleSheet("color:#6B7785; font-size:15px;")
            self.subtitle_label.setStyleSheet("color:#7E8A9C; font-size:13px;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self._press_pos is None:
            super().mouseMoveEvent(event)
            return
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if (pos - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
            self.dragRequested.emit()
            self._press_pos = None
        super().mouseMoveEvent(event)

    def eventFilter(self, obj, event):
        if obj in {self.title_label, self.subtitle_label}:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._press_pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                self.clicked.emit()
                return True
            if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self.clicked.emit()
                self.doubleClicked.emit()
                return True
            if event.type() == QEvent.MouseMove and (event.buttons() & Qt.LeftButton) and self._press_pos is not None:
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                if (pos - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
                    self.dragRequested.emit()
                    self._press_pos = None
                    return True
        return super().eventFilter(obj, event)


class _ProfileRowListWidget(QListWidget):
    """单列表行配置控件：勾选启用，已启用项支持拖拽排序。"""

    enabledRowDropped = Signal(str, int)  # row_id, target_row

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.viewport().setAcceptDrops(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self._set_drag_feedback(False)

    def start_drag_for_row_id(self, rid):
        rid = str(rid or "").strip()
        if not rid:
            return
        for row in range(self.count()):
            item = self.item(row)
            if item is not None and str(item.data(Qt.UserRole) or "").strip() == rid:
                self.setCurrentRow(row)
                self.startDrag(Qt.MoveAction)
                return

    def _set_drag_feedback(self, active: bool):
        self.setStyleSheet(
            "QListView { border: 1px solid rgba(0, 120, 212, 0.65); "
            "background: rgba(0, 120, 212, 0.06); }"
            if active else ""
        )

    def _enabled_count(self) -> int:
        count = 0
        for row in range(self.count()):
            item = self.item(row)
            if item is not None and bool(item.data(Qt.UserRole + 1)):
                count += 1
        return count

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if item is None or not bool(item.data(Qt.UserRole + 1)):
            return
        rid = str(item.data(Qt.UserRole) or "").strip()
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
        if event.mimeData().hasFormat("application/x-profile-enabled-row-id"):
            self._set_drag_feedback(True)
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self._set_drag_feedback(False)
        super().dragLeaveEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-profile-enabled-row-id"):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
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
            enabled_count = self._enabled_count()
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            row = self.indexAt(pos).row()
            if row < 0:
                row = enabled_count
            row = max(0, min(enabled_count, row))
            self.enabledRowDropped.emit(rid, row)
            event.acceptProposedAction()
        except Exception:
            event.ignore()


class _SingleListTextExportSettingsDialog(QDialog):
    """纵断面文字导出参数与行配置弹窗（单列表勾选 + 拖拽排序版）。"""

    _UI_SETTINGS_ORG = "SichuanShuifa"
    _UI_SETTINGS_APP = "HydroCalc"
    _UI_SIZE_W_KEY = "water_profile/text_export_dialog_width"
    _UI_SIZE_H_KEY = "water_profile/text_export_dialog_height"
    _UI_PREVIEW_EXPANDED_KEY = "water_profile/text_export_dialog_preview_expanded"
    _ICON_COLLAPSED = None
    _ICON_EXPANDED = None

    def __init__(self, parent=None, defaults=None):
        super().__init__(parent)
        if self._ICON_COLLAPSED is None or self._ICON_EXPANDED is None:
            type(self)._ICON_COLLAPSED = _resolve_fluent_icon("CHEVRON_RIGHT_MED", "CHEVRON_RIGHT", "CHEVRON_DOWN_MED")
            type(self)._ICON_EXPANDED = _resolve_fluent_icon("CHEVRON_DOWN_MED", "CHEVRON_RIGHT_MED", "CHEVRON_RIGHT")
        self.setWindowTitle("纵断面文字导出设置")
        self.setMinimumSize(960, 500)
        self._ui_settings = QSettings(self._UI_SETTINGS_ORG, self._UI_SETTINGS_APP)
        self._preview_expanded = self._read_setting_bool(self._UI_PREVIEW_EXPANDED_KEY, True)
        self._apply_initial_size()
        self.setSizeGripEnabled(True)
        self.setStyleSheet(DIALOG_STYLE + """
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f7f9fc, stop:1 #eef3fb);
            }
            QListView {
                border: 1px solid #d6dfef;
                border-radius: 10px;
                background: rgba(255,255,255,0.92);
                padding: 4px;
            }
            QListView::item {
                border-radius: 8px;
                padding: 7px 10px;
                margin: 1px 1px;
            }
            QListView::item:selected {
                background: rgba(0, 120, 212, 0.16);
                border: 1px solid rgba(0, 120, 212, 0.35);
            }
            QListView::item:hover {
                background: rgba(32, 97, 181, 0.08);
            }
        """)
        self.result = None
        self._row_updating = False

        defaults = _normalize_text_export_settings(defaults or {})
        self._defaults = dict(defaults)

        self._entries = {}
        self._ordered_row_ids = list(_PROFILE_ROW_VISIBLE_ORDER)
        self._enabled_row_ids = []
        self._row_widgets = {}

        self._row_list = None
        self._advanced_body = None
        self._advanced_toggle_btn = None
        self._preview_label = None
        self._preview_body = None
        self._preview_toggle_btn = None

        self._init_ui()

    def _read_setting_bool(self, key, default=False):
        raw = self._ui_settings.value(key, default)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        text = str(raw).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return bool(default)

    def _read_setting_int(self, key, default_value):
        raw = self._ui_settings.value(key, default_value)
        try:
            return int(float(raw))
        except Exception:
            return int(default_value)

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

    def _apply_initial_size(self):
        avail = self._available_geometry()
        if avail is not None:
            default_w = min(max(self.minimumWidth(), int(avail.width() * 0.78)), 1360)
            default_h = min(max(self.minimumHeight(), int(avail.height() * 0.72)), int(avail.height() * 0.92))
            max_w = max(self.minimumWidth(), int(avail.width() * 0.96))
            max_h = max(self.minimumHeight(), int(avail.height() * 0.92))
        else:
            default_w, default_h = 1160, 640
            max_w, max_h = 1400, 900

        width = self._read_setting_int(self._UI_SIZE_W_KEY, default_w)
        height = self._read_setting_int(self._UI_SIZE_H_KEY, default_h)
        width = max(self.minimumWidth(), min(width, max_w))
        height = max(self.minimumHeight(), min(height, max_h))
        self.resize(width, height)

    def _persist_ui_state(self):
        size = self.size()
        self._ui_settings.setValue(self._UI_SIZE_W_KEY, int(size.width()))
        self._ui_settings.setValue(self._UI_SIZE_H_KEY, int(size.height()))
        self._ui_settings.setValue(self._UI_PREVIEW_EXPANDED_KEY, bool(self._preview_expanded))

    def closeEvent(self, event):
        self._persist_ui_state()
        super().closeEvent(event)

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 8, 14, 8)
        root.setSpacing(6)

        body_row = QHBoxLayout()
        body_row.setSpacing(8)

        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        left_col.addWidget(self._build_basic_card())
        left_col.addWidget(self._build_advanced_card())
        left_col.addStretch(0)

        right_col = QVBoxLayout()
        right_col.setSpacing(8)
        right_col.addWidget(self._build_rows_card(), 0)
        right_col.addWidget(self._build_preview_card(), 0)
        right_col.addStretch(1)

        body_row.addLayout(left_col, 38)
        body_row.addLayout(right_col, 62)
        body_row.setAlignment(left_col, Qt.AlignTop)
        body_row.setAlignment(right_col, Qt.AlignTop)
        root.addLayout(body_row, 1)

        btn_row = QHBoxLayout()
        btn_reset = PushButton("恢复默认")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch(1)
        btn_cancel = PushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = PrimaryPushButton("确定")
        btn_ok.clicked.connect(self._on_confirm)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        root.addLayout(btn_row)

        self._load_rows(self._defaults.get("profile_row_items"))
        for entry in self._entries.values():
            entry.textChanged.connect(self._update_preview)
        self._update_preview()

        QShortcut(QKeySequence(Qt.Key_Escape), self, self.reject)
        QShortcut(QKeySequence(Qt.Key_Return), self, self._on_confirm)
        QShortcut(QKeySequence("Ctrl+Up"), self, lambda: self._move_selected_row(-1))
        QShortcut(QKeySequence("Ctrl+Down"), self, lambda: self._move_selected_row(1))
        QShortcut(QKeySequence("Ctrl+Home"), self, lambda: self._move_selected_row_to_edge(True))
        QShortcut(QKeySequence("Ctrl+End"), self, lambda: self._move_selected_row_to_edge(False))
        QShortcut(QKeySequence(Qt.Key_Delete), self, self._disable_selected_row)

    def _build_basic_card(self):
        card = ElevatedCardWidget(self)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(12, 10, 12, 10)
        card_lay.setSpacing(8)

        card_lay.addWidget(BodyLabel("基础参数"))
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.setColumnStretch(0, 0)
        form.setColumnStretch(1, 0)
        form.setColumnStretch(2, 1)
        self._add_entry_row(form, 0, "字高", "text_height", "")
        self._add_entry_row(form, 1, "旋转角度", "rotation", "")
        self._add_entry_row(form, 2, "高程小数位数", "elev_decimals", "")
        self._add_entry_row(form, 3, "X方向比例(1:N)", "scale_x", "如 1:1000 则输入 1000")
        self._add_entry_row(form, 4, "Y方向比例(1:N)", "scale_y", "如 1:1000 则输入 1000")
        card_lay.addLayout(form)
        return card

    def _build_advanced_card(self):
        card = ElevatedCardWidget(self)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(12, 10, 12, 10)
        card_lay.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(BodyLabel("高级参数（旧版Y坐标）"))
        self._advanced_toggle_btn = ToolButton(self._ICON_COLLAPSED)
        self._advanced_toggle_btn.clicked.connect(self._toggle_advanced)
        row.addStretch(1)
        row.addWidget(self._advanced_toggle_btn)
        card_lay.addLayout(row)

        self._advanced_body = QWidget()
        adv_form = QGridLayout(self._advanced_body)
        adv_form.setHorizontalSpacing(8)
        adv_form.setVerticalSpacing(6)
        adv_form.setColumnStretch(2, 1)
        self._add_entry_row(adv_form, 0, "渠底文字Y", "y_bottom", "")
        self._add_entry_row(adv_form, 1, "渠顶文字Y", "y_top", "")
        self._add_entry_row(adv_form, 2, "水面文字Y", "y_water", "")
        self._add_entry_row(adv_form, 3, "建筑物名称Y", "y_name", "兼容旧项目")
        self._add_entry_row(adv_form, 4, "坡降Y", "y_slope", "兼容旧项目")
        self._add_entry_row(adv_form, 5, "IP点名称Y", "y_ip", "兼容旧项目")
        self._add_entry_row(adv_form, 6, "里程桩号Y", "y_station", "兼容旧项目")
        self._add_entry_row(adv_form, 7, "最小竖线高度", "y_line_height", "最小值 > 0")
        self._advanced_body.setVisible(False)
        card_lay.addWidget(self._advanced_body)
        return card

    def _build_rows_card(self):
        card = ElevatedCardWidget(self)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(12, 10, 12, 10)
        card_lay.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.addWidget(BodyLabel(
            f"纵断面行内容（{len(_PROFILE_ROW_VISIBLE_ORDER)}项可选，勾选启用，已启用项可拖动排序）"
        ))
        title_row.addStretch(1)
        btn_preset = PushButton("应用亭子口二期项建/可研阶段模板")
        btn_preset.clicked.connect(self._apply_tingzikou_preset)
        title_row.addWidget(btn_preset)
        card_lay.addLayout(title_row)

        quick_row = QHBoxLayout()
        btn_enable_all = PushButton("全启用")
        btn_enable_all.clicked.connect(self._enable_all_rows)
        btn_disable_all = PushButton("全停用")
        btn_disable_all.clicked.connect(self._disable_all_rows)
        btn_restore_recommended = PushButton("恢复推荐")
        btn_restore_recommended.clicked.connect(self._restore_recommended_rows)
        quick_row.addWidget(btn_enable_all)
        quick_row.addWidget(btn_disable_all)
        quick_row.addWidget(btn_restore_recommended)
        quick_row.addStretch(1)
        card_lay.addLayout(quick_row)

        hint = CaptionLabel(
            "操作说明：勾选即启用；拖动已启用项即可排序；右键支持启用/停用/置顶/置底；Ctrl+Up/Ctrl+Down 可微调顺序。"
        )
        hint.setWordWrap(True)
        card_lay.addWidget(hint)

        hidden_hint = CaptionLabel(
            "本版本暂不显示：IP文字(BE)、桩号文字(BK)，避免与 IP点名称、里程桩号重复。"
        )
        hidden_hint.setWordWrap(True)
        card_lay.addWidget(hidden_hint)

        self._row_list = _ProfileRowListWidget(self)
        self._row_list.enabledRowDropped.connect(self._on_enabled_row_dropped)
        self._row_list.itemDoubleClicked.connect(lambda _item: self._toggle_current_row())
        self._row_list.currentItemChanged.connect(lambda _current, _previous: self._update_row_widget_selection())
        self._row_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._row_list.customContextMenuRequested.connect(self._show_row_context_menu)
        card_lay.addWidget(self._row_list, 1)

        sort_row = QHBoxLayout()
        btn_up = PushButton("上移")
        btn_up.clicked.connect(lambda: self._move_selected_row(-1))
        btn_down = PushButton("下移")
        btn_down.clicked.connect(lambda: self._move_selected_row(1))
        btn_top = PushButton("置顶")
        btn_top.clicked.connect(lambda: self._move_selected_row_to_edge(True))
        btn_bottom = PushButton("置底")
        btn_bottom.clicked.connect(lambda: self._move_selected_row_to_edge(False))
        sort_row.addWidget(btn_up)
        sort_row.addWidget(btn_down)
        sort_row.addWidget(btn_top)
        sort_row.addWidget(btn_bottom)
        sort_row.addStretch(1)
        card_lay.addLayout(sort_row)
        return card

    def _build_preview_card(self):
        card = ElevatedCardWidget(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(BodyLabel("当前配置预览"))
        row.addStretch(1)
        self._preview_toggle_btn = ToolButton(self._ICON_EXPANDED)
        self._preview_toggle_btn.clicked.connect(self._toggle_preview)
        row.addWidget(self._preview_toggle_btn)
        lay.addLayout(row)

        self._preview_body = QWidget()
        preview_lay = QVBoxLayout(self._preview_body)
        preview_lay.setContentsMargins(0, 0, 0, 0)
        preview_lay.setSpacing(0)

        self._preview_label = QLabel()
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet("color:#245A9B; font-family:'Consolas','Microsoft YaHei';")
        preview_lay.addWidget(self._preview_label)
        lay.addWidget(self._preview_body)
        self._set_preview_expanded(self._preview_expanded)
        return card

    def _set_preview_expanded(self, expanded):
        self._preview_expanded = bool(expanded)
        if self._preview_body is not None:
            self._preview_body.setVisible(self._preview_expanded)
        if self._preview_toggle_btn is not None:
            self._preview_toggle_btn.setIcon(self._ICON_EXPANDED if self._preview_expanded else self._ICON_COLLAPSED)

    def _toggle_preview(self):
        self._set_preview_expanded(not self._preview_expanded)

    def _add_entry_row(self, layout, row, label, key, hint):
        layout.addWidget(QLabel(f"{label}:"), row, 0)
        entry = LineEdit()
        entry.setText(str(self._defaults.get(key, "")))
        entry.setFixedWidth(130)
        layout.addWidget(entry, row, 1)
        layout.addWidget(CaptionLabel(hint), row, 2)
        self._entries[key] = entry

    def _toggle_advanced(self):
        visible = not self._advanced_body.isVisible()
        self._advanced_body.setVisible(visible)
        self._advanced_toggle_btn.setIcon(self._ICON_EXPANDED if visible else self._ICON_COLLAPSED)

    def _selected_row_id(self):
        if not self._row_list:
            return ""
        item = self._row_list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "").strip()

    def _set_current_row_id(self, rid):
        if not self._row_list or not rid:
            return
        for row in range(self._row_list.count()):
            item = self._row_list.item(row)
            if item is not None and str(item.data(Qt.UserRole) or "").strip() == rid:
                self._row_list.setCurrentRow(row)
                return

    def _create_row_item(self, rid, order_index):
        enabled = rid in self._enabled_row_ids
        row_def = _PROFILE_ROW_DEF_MAP[rid]
        label = row_def["label"]
        if enabled:
            title = f"{order_index + 1:02d}. {label}  [拖动排序]"
            status = "已启用"
        else:
            title = f"--. {label}"
            status = "未启用"
        if rid in _PROFILE_RECOMMENDED_ROW_IDS:
            title += "  ★推荐"
        detail = row_def.get("hint", "")
        subtitle = f"{status} | {detail}" if detail else status
        item = QListWidgetItem()
        item.setData(Qt.UserRole, rid)
        item.setData(Qt.UserRole + 1, enabled)
        item.setData(Qt.UserRole + 2, title)
        item.setData(Qt.UserRole + 3, subtitle)
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if enabled:
            flags |= Qt.ItemIsDragEnabled
        item.setFlags(flags)
        item.setSizeHint(QSize(0, 56))
        if enabled:
            item.setForeground(QColor("#174EA6") if rid in _PROFILE_RECOMMENDED_ROW_IDS else QColor("#1F2D3D"))
        else:
            item.setForeground(QColor("#6B7785"))
        return item

    def _create_row_widget(self, item):
        rid = str(item.data(Qt.UserRole) or "").strip()
        enabled = bool(item.data(Qt.UserRole + 1))
        title = str(item.data(Qt.UserRole + 2) or "")
        subtitle = str(item.data(Qt.UserRole + 3) or "")

        widget = _ProfileRowItemWidget(title, subtitle, enabled, self._row_list)
        widget.checkbox.stateChanged.connect(
            lambda _state, row_item=item, row_id=rid: self._on_row_widget_checkbox_changed(row_item, row_id)
        )
        widget.clicked.connect(lambda row_id=rid: self._set_current_row_id(row_id))
        widget.doubleClicked.connect(self._toggle_current_row)
        widget.dragRequested.connect(lambda row_id=rid: self._row_list.start_drag_for_row_id(row_id))
        return widget

    def _on_row_widget_checkbox_changed(self, item, rid):
        if self._row_updating or item is None:
            return
        self._set_current_row_id(rid)
        widget = self._row_widgets.get(rid)
        if widget is None:
            return
        self._set_row_enabled(rid, widget.checkbox.isChecked(), show_feedback=True)

    def _update_row_widget_selection(self):
        if not self._row_list:
            return
        current = self._row_list.currentItem()
        current_rid = str(current.data(Qt.UserRole) or "").strip() if current is not None else ""
        for rid, widget in self._row_widgets.items():
            if widget is not None:
                widget.set_selected(rid == current_rid)

    def _normalize_row_model(self):
        enabled = [rid for rid in self._enabled_row_ids if rid in _PROFILE_ROW_VISIBLE_ID_SET]
        order = [rid for rid in self._ordered_row_ids if rid in _PROFILE_ROW_VISIBLE_ID_SET]
        for rid in _PROFILE_ROW_VISIBLE_ORDER:
            if rid not in order:
                order.append(rid)
        disabled = [rid for rid in order if rid not in enabled]
        self._enabled_row_ids = enabled
        self._ordered_row_ids = enabled + disabled

    def _refresh_row_list(self):
        if not self._row_list:
            return
        self._normalize_row_model()
        keep_current = self._selected_row_id()

        self._row_updating = True
        try:
            self._row_list.clear()
            self._row_widgets = {}
            enabled_index = 0
            for rid in self._ordered_row_ids:
                item = self._create_row_item(rid, enabled_index)
                self._row_list.addItem(item)
                widget = self._create_row_widget(item)
                self._row_widgets[rid] = widget
                self._row_list.setItemWidget(item, widget)
                if rid in self._enabled_row_ids:
                    enabled_index += 1
        finally:
            self._row_updating = False

        self._ensure_row_list_visible_rows()
        self._set_current_row_id(keep_current)
        self._update_row_widget_selection()
        self._update_preview()

    def _ensure_row_list_visible_rows(self):
        if not self._row_list:
            return
        row_h = self._row_list.sizeHintForRow(0)
        if row_h <= 0:
            row_h = 50
        visible_rows = min(max(10, len(_PROFILE_ROW_VISIBLE_ORDER)), len(_PROFILE_ROW_VISIBLE_ORDER))
        target_h = row_h * visible_rows + 12
        self._row_list.setMinimumHeight(target_h)
        self._row_list.setMaximumHeight(target_h)

    def _load_rows(self, row_items):
        normalized = _normalize_profile_row_items(row_items)
        self._ordered_row_ids = [item["id"] for item in normalized]
        self._enabled_row_ids = [item["id"] for item in normalized if item.get("enabled")]
        self._refresh_row_list()

    def _row_data_from_table(self):
        self._normalize_row_model()
        enabled = set(self._enabled_row_ids)
        return _normalize_profile_row_items([
            {"id": rid, "enabled": rid in enabled}
            for rid in self._ordered_row_ids
        ])

    def _set_row_enabled(self, rid, enabled, *, show_feedback=False):
        if rid not in _PROFILE_ROW_VISIBLE_ID_SET:
            return
        current_enabled = rid in self._enabled_row_ids
        if current_enabled == bool(enabled):
            return

        if enabled:
            self._enabled_row_ids = [row_id for row_id in self._enabled_row_ids if row_id != rid] + [rid]
        else:
            self._enabled_row_ids = [row_id for row_id in self._enabled_row_ids if row_id != rid]
        self._normalize_row_model()
        self._refresh_row_list()
        self._set_current_row_id(rid)

        if show_feedback:
            row_label = _PROFILE_ROW_DEF_MAP[rid]["label"]
            if enabled:
                InfoBar.success(
                    "已启用",
                    f"{row_label} 已加入导出",
                    parent=self,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=1200,
                )
            else:
                InfoBar.info(
                    "已停用",
                    f"{row_label} 已移出导出",
                    parent=self,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=1200,
                )

    def _toggle_current_row(self):
        rid = self._selected_row_id()
        if not rid:
            return
        self._set_row_enabled(rid, rid not in self._enabled_row_ids, show_feedback=True)

    def _on_row_item_changed(self, item):
        if self._row_updating or item is None:
            return
        rid = str(item.data(Qt.UserRole) or "").strip()
        enabled = item.checkState() == Qt.Checked
        self._set_row_enabled(rid, enabled, show_feedback=True)

    def _enable_all_rows(self):
        self._enabled_row_ids = list(_PROFILE_ROW_VISIBLE_ORDER)
        self._refresh_row_list()

    def _disable_all_rows(self):
        self._enabled_row_ids = []
        self._refresh_row_list()

    def _restore_recommended_rows(self):
        self._enabled_row_ids = [
            rid for rid in _PROFILE_ROW_VISIBLE_ORDER
            if rid in _PROFILE_RECOMMENDED_ROW_IDS
        ]
        self._refresh_row_list()

    def _apply_tingzikou_preset(self):
        ordered = list(_TINGZIKOU_TEMPLATE_ROW_IDS) + [
            rid for rid in _PROFILE_ROW_VISIBLE_ORDER if rid not in _TINGZIKOU_TEMPLATE_ROW_IDS
        ]
        self._ordered_row_ids = ordered
        self._enabled_row_ids = list(_TINGZIKOU_TEMPLATE_ROW_IDS)
        self._refresh_row_list()
        InfoBar.success(
            "模板已应用",
            "已切换为亭子口推荐顺序",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=1500,
        )

    def _reorder_enabled_row(self, rid, target_row):
        enabled = list(self._enabled_row_ids)
        if rid not in enabled:
            return
        old_row = enabled.index(rid)
        enabled.pop(old_row)
        target_row = max(0, min(len(enabled), int(target_row)))
        if target_row > old_row:
            target_row -= 1
        enabled.insert(target_row, rid)
        self._enabled_row_ids = enabled
        self._refresh_row_list()
        self._set_current_row_id(rid)

    def _on_enabled_row_dropped(self, rid, target_row):
        if self._row_updating:
            return
        self._reorder_enabled_row(rid, target_row)

    def _move_selected_row(self, delta):
        rid = self._selected_row_id()
        if not rid or rid not in self._enabled_row_ids:
            return
        row = self._enabled_row_ids.index(rid)
        target = row + int(delta)
        if target < 0 or target >= len(self._enabled_row_ids):
            return
        # _reorder_enabled_row() 接收的是“原列表中的插入位置”；
        # 向下移动时需要插入到目标项之后，避免弹出后又插回原位。
        insertion_row = target + 1 if delta > 0 else target
        self._reorder_enabled_row(rid, insertion_row)

    def _move_selected_row_to_edge(self, to_top):
        rid = self._selected_row_id()
        if not rid or rid not in self._enabled_row_ids:
            return
        target = 0 if to_top else len(self._enabled_row_ids) - 1
        self._reorder_enabled_row(rid, target)

    def _disable_selected_row(self):
        rid = self._selected_row_id()
        if rid and rid in self._enabled_row_ids:
            self._set_row_enabled(rid, False, show_feedback=True)

    def _show_row_context_menu(self, pos):
        if not self._row_list:
            return
        item = self._row_list.itemAt(pos)
        if item is None:
            return
        self._row_list.setCurrentItem(item)
        rid = str(item.data(Qt.UserRole) or "").strip()
        enabled = rid in self._enabled_row_ids
        menu = QMenu(self)
        action_toggle = menu.addAction("停用" if enabled else "启用")
        action_up = action_down = action_top = action_bottom = None
        if enabled:
            menu.addSeparator()
            action_up = menu.addAction("上移")
            action_down = menu.addAction("下移")
            action_top = menu.addAction("置顶")
            action_bottom = menu.addAction("置底")

            row = self._enabled_row_ids.index(rid)
            action_up.setEnabled(row > 0)
            action_top.setEnabled(row > 0)
            action_down.setEnabled(row < len(self._enabled_row_ids) - 1)
            action_bottom.setEnabled(row < len(self._enabled_row_ids) - 1)

        chosen = menu.exec(self._row_list.viewport().mapToGlobal(pos))
        if chosen == action_toggle:
            self._set_row_enabled(rid, not enabled, show_feedback=True)
        elif chosen == action_up:
            self._move_selected_row(-1)
        elif chosen == action_down:
            self._move_selected_row(1)
        elif chosen == action_top:
            self._move_selected_row_to_edge(True)
        elif chosen == action_bottom:
            self._move_selected_row_to_edge(False)

    def _update_preview(self):
        try:
            enabled = [item for item in self._row_data_from_table() if item.get("enabled")]
            labels = [_PROFILE_ROW_DEF_MAP[item["id"]]["label"] for item in enabled[:6]]
            summary = "、".join(labels) if labels else "无"
            if len(enabled) > 6:
                summary += f" ...（共{len(enabled)}行）"
            self._preview_label.setText(
                f"已启用行：{summary}\n"
                f"示例：-text X,Y {self._entries['text_height'].text().strip()} "
                f"{self._entries['rotation'].text().strip()} 文本"
            )
        except Exception:
            self._preview_label.setText("预览不可用")

    def _reset_defaults(self):
        original = {
            "y_bottom": 1, "y_top": 31, "y_water": 16,
            "text_height": 3.5, "rotation": 90, "elev_decimals": 3,
            "y_name": 115, "y_slope": 105, "y_ip": 77,
            "y_station": 47, "y_line_height": 120,
            "scale_x": 1, "scale_y": 1,
        }
        for key, value in original.items():
            if key in self._entries:
                self._entries[key].setText(str(value))
        self._load_rows(_default_profile_row_items())
        self._update_preview()

    def _focus_invalid_entry(self, key):
        entry = self._entries.get(key)
        if not entry:
            return
        if key in {"y_bottom", "y_top", "y_water", "y_name", "y_slope", "y_ip", "y_station", "y_line_height"}:
            if self._advanced_body and not self._advanced_body.isVisible():
                self._toggle_advanced()
        entry.setFocus()
        entry.selectAll()

    def _on_confirm(self):
        try:
            parsed = {}
            ordered_keys = [
                "text_height", "rotation", "elev_decimals", "scale_x", "scale_y",
                "y_bottom", "y_top", "y_water",
                "y_name", "y_slope", "y_ip", "y_station", "y_line_height",
            ]
            labels = {
                "text_height": "字高",
                "rotation": "旋转角度",
                "elev_decimals": "高程小数位数",
                "scale_x": "X方向比例",
                "scale_y": "Y方向比例",
                "y_bottom": "渠底文字Y",
                "y_top": "渠顶文字Y",
                "y_water": "水面文字Y",
                "y_name": "建筑物名称Y",
                "y_slope": "坡降Y",
                "y_ip": "IP点名称Y",
                "y_station": "里程桩号Y",
                "y_line_height": "最小竖线高度",
            }
            for key in ordered_keys:
                entry = self._entries[key]
                txt = entry.text().strip()
                if not txt:
                    self._focus_invalid_entry(key)
                    raise ValueError(f"{labels[key]}不能为空")
                try:
                    val = float(txt)
                except ValueError:
                    self._focus_invalid_entry(key)
                    raise ValueError(f"{labels[key]}必须为数值")
                if key == "elev_decimals":
                    if val < 0 or val != int(val):
                        self._focus_invalid_entry(key)
                        raise ValueError("高程小数位数必须为非负整数")
                    val = int(val)
                if key in ("scale_x", "scale_y", "y_line_height") and val <= 0:
                    self._focus_invalid_entry(key)
                    raise ValueError("比例与最小竖线高度必须大于0")
                parsed[key] = val

            row_items = self._row_data_from_table()
            if not any(item.get("enabled") for item in row_items):
                if self._row_list is not None:
                    self._row_list.setFocus()
                raise ValueError("至少选择1项行内容")

            result = dict(self._defaults)
            result.update(parsed)
            result["profile_row_items"] = row_items
            self.result = _normalize_text_export_settings(result)
            self.accept()
        except ValueError as e:
            fluent_error(self, "输入错误", f"请输入有效的数值\n{str(e)}")

# ================================================================
# 辅助工具函数
# ================================================================

def _resolve_fluent_icon(*names):
    """按候选名称顺序获取可用 FluentIcon，避免版本差异导致属性不存在。"""
    for name in names:
        icon = getattr(FluentIcon, name, None)
        if icon is not None:
            return icon
    for fallback_name in ("CHEVRON_RIGHT", "CHEVRON_DOWN_MED", "ADD"):
        icon = getattr(FluentIcon, fallback_name, None)
        if icon is not None:
            return icon
    raise AttributeError("未找到可用的 FluentIcon 回退图标")


def _format_number(value):
    """格式化数值：保留完整精度，去除无意义的尾零"""
    return f"{value:.15g}"


def _get_building_display_name(node):
    """获取纵断面用的建筑物名称显示"""
    struct_str = node.get_structure_type_str() or ""
    if node.is_transition or struct_str == "渐变段":
        return ""
    if getattr(node, "is_auto_inserted_channel", False):
        return ""
    if struct_str.startswith("明渠"):
        return struct_str
    if struct_str == "矩形暗涵":
        return struct_str
    # 隧洞/倒虹吸/有压管道/渡槽 等特殊建筑物：只有进/出节点参与建筑物名称段的划定；
    # 内部 IP 节点不标注名称，否则 building_segments 会被碎化导致坡降行出现重叠。
    if _is_special_structure_sv(getattr(node, "structure_type", None)):
        if _in_out_val(getattr(node, "in_out", None)) not in ("进", "出"):
            return ""
    if node.name:
        category = struct_str.split("-")[0]
        return f"{node.name}{category}"
    return struct_str.split("-")[0] if struct_str else ""


def _estimate_text_width(text, text_height):
    """估算 AutoCAD 中文字的总宽度（用于居中对齐）

    中文字符（CJK）宽度 ≈ text_height
    ASCII 字符（字母/数字/标点）宽度 ≈ text_height × 0.7
    """
    width = 0.0
    for ch in text:
        if ord(ch) > 127:
            width += text_height
        else:
            width += text_height * 0.7
    return width


def _format_slope_text(slope_i):
    """格式化坡降为显示文本"""
    if slope_i is not None and slope_i > 0:
        slope_inv = round(1.0 / slope_i)
        return f"1/{slope_inv}"
    return "/"


def _get_node_slope_text(node, next_node=None):
    """获取节点坡降文本（直接使用节点自身的 slope_i）。"""
    return _format_slope_text(getattr(node, 'slope_i', None))


def _struct_val(struct_type):
    """获取 StructureType 的字符串值（兼容双路径导入的 enum 实例）"""
    if struct_type is None:
        return ""
    return struct_type.value if hasattr(struct_type, 'value') else str(struct_type)


def _in_out_val(in_out):
    """获取 InOutType 的字符串值（兼容双路径导入的 enum 实例）"""
    if in_out is None:
        return ""
    return in_out.value if hasattr(in_out, 'value') else str(in_out)


def _is_special_structure_sv(struct_type):
    """判断是否为特殊建筑物（隧洞/倒虹吸/有压管道/渡槽/矩形暗涵），使用字符串值比较

    避免双路径导入导致 enum 实例比较失败"""
    sv = _struct_val(struct_type)
    return any(k in sv for k in ("隧洞", "倒虹吸", "有压管道", "渡槽", "暗涵"))


_PROFILE_ROW_DEFS = [
    {
        "id": "building_name",
        "label": "建筑物名称",
        "hint": "按建筑物段居中标注",
        "header_lines": ["建筑物名称"],
        "height": 10.0,
        "anchor": "center",
    },
    {
        "id": "slope",
        "label": "坡降",
        "hint": "按建筑物段显示坡降",
        "header_lines": ["坡降"],
        "height": 10.0,
        "anchor": "center",
    },
    {
        "id": "ip_name",
        "label": "IP点名称",
        "hint": "IP节点名称（特殊建筑仅进/出点）",
        "header_lines": ["IP点名称"],
        "height": 40.0,
        "anchor": "bottom2",
    },
    {
        "id": "station",
        "label": "里程桩号(千米+米)",
        "hint": "显示格式：1+234.567",
        "header_lines": ["里程桩号", "（千米+米）"],
        "height": 30.0,
        "anchor": "bottom2",
    },
    {
        "id": "top_elev",
        "label": "渠顶高程(m)",
        "hint": "节点渠顶高程",
        "header_lines": ["渠顶高程(m)"],
        "height": 15.0,
        "anchor": "bottom1",
    },
    {
        "id": "water_elev",
        "label": "设计水位(m)",
        "hint": "节点设计水位",
        "header_lines": ["设计水位(m)"],
        "height": 15.0,
        "anchor": "bottom1",
    },
    {
        "id": "bottom_elev",
        "label": "渠底高程(m)",
        "hint": "节点渠底高程",
        "header_lines": ["渠底高程(m)"],
        "height": 15.0,
        "anchor": "bottom1",
    },
    {
        "id": "bd_ip_before",
        "label": "IP弯前(BD)",
        "hint": "IP文字弯前点（BC）",
        "header_lines": ["IP弯前"],
        "height": 40.0,
        "anchor": "bottom2",
    },
    {
        "id": "be_ip_text",
        "label": "IP文字(BE)",
        "hint": "IP文字中心点（MC）",
        "header_lines": ["IP文字"],
        "height": 30.0,
        "anchor": "bottom2",
    },
    {
        "id": "bf_ip_after",
        "label": "IP弯后(BF)",
        "hint": "IP文字弯后点（EC）",
        "header_lines": ["IP弯后"],
        "height": 40.0,
        "anchor": "bottom2",
    },
    {
        "id": "bj_station_before",
        "label": "桩号文字弯前(BJ)",
        "hint": "桩号文字弯前点（BC）",
        "header_lines": ["桩号文字弯前"],
        "height": 30.0,
        "anchor": "bottom2",
    },
    {
        "id": "bk_station",
        "label": "桩号文字(BK)",
        "hint": "桩号文字中心点（MC）",
        "header_lines": ["桩号文字"],
        "height": 25.0,
        "anchor": "bottom2",
    },
    {
        "id": "bl_station_after",
        "label": "桩号文字弯后(BL)",
        "hint": "桩号文字弯后点（EC）",
        "header_lines": ["桩号文字弯后"],
        "height": 30.0,
        "anchor": "bottom2",
    },
]
_PROFILE_ROW_DEF_MAP = {d["id"]: d for d in _PROFILE_ROW_DEFS}
_PROFILE_ROW_DEFAULT_ORDER = [d["id"] for d in _PROFILE_ROW_DEFS]
_PROFILE_ROW_VISIBLE_ORDER = [
    "building_name",
    "slope",
    "ip_name",
    "station",
    "top_elev",
    "water_elev",
    "bottom_elev",
    "bd_ip_before",
    # "be_ip_text",   # 暂停展示：与“IP点名称”语义重复
    "bf_ip_after",
    "bj_station_before",
    # "bk_station",   # 暂停展示：与“里程桩号”语义重复
    "bl_station_after",
]
_PROFILE_ROW_VISIBLE_ID_SET = frozenset(_PROFILE_ROW_VISIBLE_ORDER)
_PROFILE_ROW_HIDDEN_IDS = frozenset(
    rid for rid in _PROFILE_ROW_DEFAULT_ORDER if rid not in _PROFILE_ROW_VISIBLE_ID_SET
)
_TINGZIKOU_TEMPLATE_ROW_IDS = [
    "building_name", "slope", "ip_name", "station",
    "top_elev", "water_elev", "bottom_elev",
]
_PROFILE_RECOMMENDED_ROW_IDS = {
    "building_name", "slope", "top_elev", "water_elev", "bottom_elev"
}
_PROFILE_EXTENDED_ROW_IDS = [rid for rid in _PROFILE_ROW_VISIBLE_ORDER if rid not in _TINGZIKOU_TEMPLATE_ROW_IDS]
_SPECIAL_STRUCTURE_FULLNAME_MAP = (
    ("隧洞", "隧洞"),
    ("倒虹吸", "倒虹吸"),
    ("有压管道", "有压管道"),
    ("渡槽", "渡槽"),
    ("暗涵", "暗涵"),
)
_SPECIAL_ANGLE_TOL_DEG = 0.01
_BC_ROW_IDS = frozenset({"bd_ip_before", "bj_station_before"})
_EC_ROW_IDS = frozenset({"bf_ip_after", "bl_station_after"})


def _default_profile_row_items():
    enabled_default = set(_TINGZIKOU_TEMPLATE_ROW_IDS)
    return [{"id": rid, "enabled": rid in enabled_default} for rid in _PROFILE_ROW_VISIBLE_ORDER]


def _normalize_profile_row_items(raw_items):
    enabled_default = set(_TINGZIKOU_TEMPLATE_ROW_IDS)
    order = []
    enabled_map = {}

    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("id", "")).strip()
            if rid not in _PROFILE_ROW_VISIBLE_ID_SET or rid in order:
                continue
            order.append(rid)
            enabled_map[rid] = bool(item.get("enabled", rid in enabled_default))

    for rid in _PROFILE_ROW_VISIBLE_ORDER:
        if rid not in order:
            order.append(rid)

    return [{"id": rid, "enabled": enabled_map.get(rid, rid in enabled_default)} for rid in order]


def _normalize_text_export_settings(settings):
    src = dict(settings or {})
    src["y_bottom"] = src.get("y_bottom", 1)
    src["y_top"] = src.get("y_top", 31)
    src["y_water"] = src.get("y_water", 16)
    src["text_height"] = src.get("text_height", 3.5)
    src["rotation"] = src.get("rotation", 90)
    src["elev_decimals"] = int(src.get("elev_decimals", 3))
    src["y_name"] = src.get("y_name", 115)
    src["y_slope"] = src.get("y_slope", 105)
    src["y_ip"] = src.get("y_ip", 77)
    src["y_station"] = src.get("y_station", 47)
    src["y_line_height"] = src.get("y_line_height", 120)
    src["scale_x"] = src.get("scale_x", 1)
    src["scale_y"] = src.get("scale_y", 1)
    src["profile_row_items"] = _normalize_profile_row_items(src.get("profile_row_items"))
    return src


def _get_enabled_profile_row_ids(settings):
    normalized = _normalize_text_export_settings(settings)
    return [item["id"] for item in normalized["profile_row_items"] if item.get("enabled")]


def _build_profile_row_layout(settings):
    normalized = _normalize_text_export_settings(settings)
    enabled_ids = [item["id"] for item in normalized["profile_row_items"] if item.get("enabled")]
    if not enabled_ids:
        return [], {}, 0.0, float(normalized.get("y_line_height", 120)), [0.0]

    total_height = sum(float(_PROFILE_ROW_DEF_MAP[rid]["height"]) for rid in enabled_ids)
    min_line_height = float(normalized.get("y_line_height", 120))
    line_height = max(total_height, min_line_height)

    row_layout = {}
    boundaries = {0.0, total_height, line_height}
    cursor_top = total_height
    for rid in enabled_ids:
        row_def = _PROFILE_ROW_DEF_MAP[rid]
        height = float(row_def["height"])
        top = cursor_top
        bottom = top - height
        cursor_top = bottom

        if row_def["anchor"] == "center":
            text_y = (bottom + top) / 2.0
        elif row_def["anchor"] == "bottom1":
            text_y = bottom + 1.0
        else:
            text_y = bottom + 2.0

        row_layout[rid] = {
            "bottom": bottom,
            "top": top,
            "text_y": text_y,
            "height": height,
            "header_lines": list(row_def.get("header_lines", [])),
            "label": row_def["label"],
        }
        boundaries.add(bottom)
        boundaries.add(top)

    return enabled_ids, row_layout, total_height, line_height, sorted(boundaries)


def _compute_node_vline_segments(node, row_layout, enabled_row_ids, v_top, tol=1e-9):
    """计算单个 IP 节点的竖线分段（按 BC/MC/EC x 坐标分组）。

    当 station_BC 或 station_EC 与 station_MC 不同时，将竖线按行的
    x 坐标组拆分，使每段竖线仅穿越属于同一 x 坐标组的行。

    返回 [(station_x, y_bottom, y_top), ...], station_x 为未缩放的原始桩号。
    """
    mc = float(getattr(node, "station_MC", 0) or 0.0)
    bc = float(getattr(node, "station_BC", mc) or mc)
    ec = float(getattr(node, "station_EC", mc) or mc)

    bc_differs = abs(bc - mc) > tol
    ec_differs = abs(ec - mc) > tol

    if not (bc_differs or ec_differs):
        return [(mc, 0.0, v_top)]

    bc_intervals = []
    ec_intervals = []
    for rid in enabled_row_ids:
        if rid not in row_layout:
            continue
        if rid in _BC_ROW_IDS and bc_differs:
            bc_intervals.append((row_layout[rid]["bottom"], row_layout[rid]["top"]))
        elif rid in _EC_ROW_IDS and ec_differs:
            ec_intervals.append((row_layout[rid]["bottom"], row_layout[rid]["top"]))

    if not bc_intervals and not ec_intervals:
        return [(mc, 0.0, v_top)]

    exclude = sorted(bc_intervals + ec_intervals)

    segments = []
    y_cursor = 0.0
    for exc_bot, exc_top in exclude:
        if exc_bot > y_cursor + tol and exc_bot <= v_top + tol:
            segments.append((mc, y_cursor, min(exc_bot, v_top)))
        y_cursor = max(y_cursor, exc_top)
    if y_cursor < v_top - tol:
        segments.append((mc, y_cursor, v_top))

    for bot, top in bc_intervals:
        eff_bot = max(bot, 0.0)
        eff_top = min(top, v_top)
        if eff_top > eff_bot + tol:
            segments.append((bc, eff_bot, eff_top))

    for bot, top in ec_intervals:
        eff_bot = max(bot, 0.0)
        eff_top = min(top, v_top)
        if eff_top > eff_bot + tol:
            segments.append((ec, eff_bot, eff_top))

    return segments


def _is_special_inout_node(node):
    if not _is_special_structure_sv(getattr(node, "structure_type", None)):
        return False
    return _in_out_val(getattr(node, "in_out", None)) in ("进", "出")


def _get_special_structure_full_name(struct_type):
    sv = _struct_val(struct_type)
    for key, full in _SPECIAL_STRUCTURE_FULLNAME_MAP:
        if key in sv:
            return full
    if "-" in sv:
        return sv.split("-")[0]
    return sv


def _merge_building_and_structure_name(building_name, structure_full):
    name = (building_name or "").strip()
    struct = (structure_full or "").strip()
    if not struct:
        return name
    if struct in name:
        return name
    return f"{name}{struct}" if name else struct


def _build_profile_ip_base_text(node):
    ip_no = int(getattr(node, "ip_number", 0) or 0)
    ip_text = f"IP{ip_no}"
    if _is_special_inout_node(node):
        merged_name = _merge_building_and_structure_name(
            getattr(node, "name", ""),
            _get_special_structure_full_name(getattr(node, "structure_type", None)),
        )
        in_out = _in_out_val(getattr(node, "in_out", None))
        detail = f"{merged_name}{in_out}".strip()
        return f"{ip_text} {detail}".strip()
    return ip_text


def _iter_profile_ip_nodes(nodes):
    special_stations = set()
    for node in nodes:
        if _is_special_inout_node(node):
            special_stations.add(round(float(getattr(node, "station_MC", 0) or 0.0), 6))

    result = []
    for node in nodes:
        struct_str = node.get_structure_type_str() or ""
        if getattr(node, "is_transition", False) or struct_str == "渐变段":
            continue
        if getattr(node, "is_auto_inserted_channel", False):
            continue
        # 特殊建筑物（隧洞/倒虹吸/有压管道/渡槽/暗涵）内部的 IP 节点也需要显示（只显示 IPxx）；
        # 仅排除普通节点中与特殊建筑进/出口桩号重合的节点（避免双重标注）。
        if not _is_special_structure_sv(getattr(node, "structure_type", None)):
            if round(float(getattr(node, "station_MC", 0) or 0.0), 6) in special_stations:
                continue
        result.append(node)
    return result


def _build_ip_related_row_records(nodes, station_prefix):
    """构建 BD/BE/BF/BJ/BK/BL 六类文本记录。

    返回: {row_id: [{"x": float, "text": str, "node": node}, ...], ...}
    """
    row_ids = [
        "ip_name",
        "bd_ip_before", "be_ip_text", "bf_ip_after",
        "bj_station_before", "bk_station", "bl_station_after",
    ]
    records = {rid: [] for rid in row_ids}
    last_x_map = {rid: None for rid in row_ids}

    ip_nodes = _iter_profile_ip_nodes(nodes)
    for node in ip_nodes:
        base_text = _build_profile_ip_base_text(node)
        angle = abs(float(getattr(node, "turn_angle", 0) or 0.0))
        is_special = _is_special_inout_node(node)

        before_text = base_text if (is_special or angle <= 0) else f"{base_text}弯前"
        after_text = base_text if (is_special or angle <= 0) else f"{base_text}弯后"
        center_text = base_text

        station_bc = float(getattr(node, "station_BC", _profile_station_value(node)) or 0.0)
        station_mc = _profile_station_value(node)
        station_ec = float(getattr(node, "station_EC", station_mc) or station_mc)

        try:
            station_before = ProjectSettings.format_station(station_bc, station_prefix)
            station_center = ProjectSettings.format_station(station_mc, station_prefix)
            station_after = ProjectSettings.format_station(station_ec, station_prefix)
        except Exception:
            station_before = f"{station_prefix}{station_bc:.3f}"
            station_center = f"{station_prefix}{station_mc:.3f}"
            station_after = f"{station_prefix}{station_ec:.3f}"

        row_payloads = [
            ("ip_name", station_mc, center_text),
            ("bd_ip_before", station_bc, before_text),
            ("be_ip_text", station_mc, center_text),
            ("bf_ip_after", station_ec, after_text),
            ("bj_station_before", station_bc, station_before),
            ("bk_station", station_mc, station_center),
            ("bl_station_after", station_ec, station_after),
        ]
        for rid, x_val, text_val in row_payloads:
            adjusted_x = float(x_val)
            prev_x = last_x_map.get(rid)
            if prev_x is not None and abs(prev_x - adjusted_x) <= 1e-9:
                adjusted_x += 6.0
            records[rid].append({
                "x": adjusted_x,
                "text": str(text_val),
                "node": node,
            })
            last_x_map[rid] = adjusted_x

    return records


def _build_special_angle_warning(nodes, tol_deg=_SPECIAL_ANGLE_TOL_DEG):
    near_msgs = []
    over_msgs = []
    for node in _iter_profile_ip_nodes(nodes):
        if not _is_special_inout_node(node):
            continue
        angle = abs(float(getattr(node, "turn_angle", 0) or 0.0))
        base_text = _build_profile_ip_base_text(node)
        if angle >= tol_deg:
            over_msgs.append(f"{base_text}: {angle:.6f}°")
        elif angle > 0:
            near_msgs.append(f"{base_text}: {angle:.6f}°")

    if not near_msgs and not over_msgs:
        return ""

    lines = ["检测到特殊建筑进/出点转角异常："]
    if near_msgs:
        lines.append("接近0（建议复核）:")
        lines.extend([f"  - {m}" for m in near_msgs])
    if over_msgs:
        lines.append(f"超过阈值 {tol_deg:.3f}°（建议重点复核）:")
        lines.extend([f"  - {m}" for m in over_msgs])
    lines.append("提示：本次仅提醒，不阻断导出。")
    return "\n".join(lines)


def _show_special_angle_warning(panel, nodes):
    msg = _build_special_angle_warning(nodes, tol_deg=_SPECIAL_ANGLE_TOL_DEG)
    if msg:
        fluent_info(panel.window(), "特殊建筑转角提示", msg)


def _profile_station_value(node):
    """提取纵断面导出用 station_MC 浮点值。"""
    try:
        return float(getattr(node, "station_MC", 0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _profile_elevation_score(node):
    """计算节点高程完整度分值（非零项越多越优先）。"""
    score = 0
    for attr in ("bottom_elevation", "top_elevation", "water_level"):
        try:
            val = float(getattr(node, attr, 0) or 0.0)
        except (TypeError, ValueError):
            val = 0.0
        if abs(val) > 1e-9:
            score += 1
    return score


def _is_profile_text_export_node(node):
    """判断节点是否属于纵断面文本行“真实节点”（排除渐变段与自动插入明渠段）。"""
    struct_str = node.get_structure_type_str() or ""
    if getattr(node, "is_transition", False) or struct_str == "渐变段":
        return False
    if getattr(node, "is_auto_inserted_channel", False):
        return False
    return True


def _build_profile_text_nodes(nodes):
    """构建纵断面四行文本输出节点（真实节点过滤 + 同桩号归并 + 冲突校验）。"""
    grouped_by_station = {}
    station_order = []
    for node in nodes:
        if not _is_profile_text_export_node(node):
            continue
        station_val = _profile_station_value(node)
        station_key = round(station_val, 9)
        if station_key not in grouped_by_station:
            grouped_by_station[station_key] = []
            station_order.append(station_key)
        grouped_by_station[station_key].append(node)

    def _node_label(node_obj):
        ip_no = getattr(node_obj, "ip_number", None)
        ip_label = f"IP{ip_no}" if ip_no is not None else "IP?"
        name = str(getattr(node_obj, "name", "") or "").strip()
        return f"{ip_label}({name})" if name else ip_label

    def _resolve_elev(group_nodes, attr_name, field_label, station_value, tol=1e-6):
        non_zero_values = []
        fallback_values = []
        for group_node in group_nodes:
            try:
                value = float(getattr(group_node, attr_name, 0) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            fallback_values.append(value)
            if abs(value) > tol:
                non_zero_values.append((value, group_node))

        unique_values = []
        for value, group_node in non_zero_values:
            if not any(abs(value - prev_value) <= tol for prev_value, _ in unique_values):
                unique_values.append((value, group_node))

        if len(unique_values) > 1:
            detail = "；".join(f"{val:.6f}@{_node_label(nd)}" for val, nd in unique_values)
            raise ValueError(
                f"纵断面导出检测到同桩号冲突：桩号 {station_value:.6f} 的{field_label}存在多个非零值（{detail}）"
            )

        if unique_values:
            return unique_values[0][0]
        return fallback_values[0] if fallback_values else 0.0

    merged_nodes = []
    field_labels = {
        "bottom_elevation": "渠底高程",
        "top_elevation": "渠顶高程",
        "water_level": "设计水位",
    }
    for station_key in station_order:
        group = grouped_by_station[station_key]
        representative = max(group, key=_profile_elevation_score)
        station_val = _profile_station_value(representative)

        merged = copy.copy(representative)
        merged.station_MC = station_val
        for attr_name, field_label in field_labels.items():
            setattr(merged, attr_name, _resolve_elev(group, attr_name, field_label, station_val))
        merged_nodes.append(merged)
    return merged_nodes


def _resolve_segment_mid_mc(seg_start, seg_end, boundary_mcs, tol=1e-9):
    """根据边界竖线计算段落中心MC；单点段优先取所在单元格几何中心。"""
    bounds = sorted({float(val) for val in boundary_mcs})
    if not bounds:
        return (seg_start + seg_end) / 2.0

    left_bound = max((val for val in bounds if val <= seg_start + tol), default=seg_start)
    right_bound = min((val for val in bounds if val >= seg_end - tol), default=seg_end)

    if right_bound - left_bound <= tol:
        pivot = seg_start if abs(seg_start - seg_end) <= tol else (seg_start + seg_end) / 2.0
        prev_bound = max((val for val in bounds if val < pivot - tol), default=None)
        next_bound = min((val for val in bounds if val > pivot + tol), default=None)
        if abs(seg_start - seg_end) <= tol:
            if next_bound is not None and abs(pivot - bounds[0]) <= tol:
                right_bound = next_bound
            elif prev_bound is not None and abs(pivot - bounds[-1]) <= tol:
                left_bound = prev_bound
            elif prev_bound is not None and next_bound is not None:
                left_bound, right_bound = prev_bound, next_bound
            elif next_bound is not None:
                right_bound = next_bound
            elif prev_bound is not None:
                left_bound = prev_bound

    return (left_bound + right_bound) / 2.0


def _is_gate_name(name):
    """判断建筑物显示名称是否为闸类点状建筑物（分水闸/分水口/节制闸/泄水闸等）"""
    if not name:
        return False
    return "闸" in name or "分水" in name


def _get_segment_slope_text(mc_list, mc_to_node):
    """从建筑物段的节点列表中提取坡降文本

    遍历段内所有 MC 对应的节点，取第一个有效的 slope_i 作为坡降。
    Args:
        mc_list: 该建筑物段包含的桩号列表
        mc_to_node: {station_MC: node} 查找表
    Returns:
        坡降文本（如 "1/3000"），无数据时返回 None
    """
    for mc in mc_list:
        node = mc_to_node.get(mc)
        if node:
            st = _format_slope_text(getattr(node, 'slope_i', None))
            if st != "/":
                return st
    return None


def _merge_segments_across_gates(segments, gate_mc_set=None):
    """合并被闸（点状建筑物）拆分的同名段落

    规则：如果段落 i 和段落 j 的值相同，且 i~j 之间的所有段落
    都是闸类点状建筑物，则将 j 的 MC 列表合并到 i，闸段保留不变。

    对建筑物名称段落：通过名称判断闸（_is_gate_name）。
    对坡降等段落：通过 gate_mc_set（闸节点的桩号集合）判断。

    Args:
        segments: [(value, [mc_list]), ...] 按位置排列的段落
        gate_mc_set: 闸节点桩号集合，仅在非名称场景下使用
    """
    if len(segments) <= 2:
        return segments

    def _is_gate_seg(val, mc_list):
        if gate_mc_set is not None:
            return all(mc in gate_mc_set for mc in mc_list)
        return _is_gate_name(val)

    merged = []
    i = 0
    while i < len(segments):
        val, mc_list = segments[i]

        if _is_gate_seg(val, mc_list):
            merged.append((val, list(mc_list)))
            i += 1
            continue

        # 非闸段：尝试向后合并同名段（跳过中间的闸段）
        mc_list = list(mc_list)
        j = i + 1
        while j + 1 < len(segments):
            mid_val, mid_mcs = segments[j]
            next_val, next_mcs = segments[j + 1]
            if _is_gate_seg(mid_val, mid_mcs) and next_val == val:
                merged.append((mid_val, list(mid_mcs)))  # 闸段保留
                mc_list.extend(next_mcs)
                j += 2
            else:
                break

        merged.append((val, mc_list))
        i = j if j > i + 1 else i + 1

    return merged


# ================================================================
# DXF 共享辅助工具
# ================================================================

class _OffsetMSP:
    """包装 ezdxf modelspace，自动为所有绘图操作添加坐标偏移。
    用于在同一 DXF 文件中将多个表格放置在不同位置。"""

    def __init__(self, msp, ox=0, oy=0):
        self._msp = msp
        self._ox = ox
        self._oy = oy

    def _p(self, pt):
        return (pt[0] + self._ox, pt[1] + self._oy)

    def add_line(self, start, end, dxfattribs=None):
        return self._msp.add_line(self._p(start), self._p(end),
                                   dxfattribs=dxfattribs or {})

    def add_lwpolyline(self, points, dxfattribs=None):
        return self._msp.add_lwpolyline(
            [self._p(p) for p in points], dxfattribs=dxfattribs or {})

    def add_text(self, text, dxfattribs=None):
        entity = self._msp.add_text(text, dxfattribs=dxfattribs or {})
        return _OffsetTextEntity(entity, self._ox, self._oy)


class _OffsetTextEntity:
    """包装 ezdxf text 实体，自动为 set_placement 添加坐标偏移。"""

    def __init__(self, entity, ox, oy):
        self._entity = entity
        self._ox = ox
        self._oy = oy

    def set_placement(self, point, align=None):
        p = (point[0] + self._ox, point[1] + self._oy)
        if align is not None:
            return self._entity.set_placement(p, align=align)
        return self._entity.set_placement(p)


def _setup_dxf_style(doc):
    """设置 DXF 文档的中文字体样式（仿宋，宽度因子0.7）。"""
    if "Standard" in doc.styles:
        _sty = doc.styles.get("Standard")
    else:
        _sty = doc.styles.add("Standard")
    _sty.dxf.font = ""
    _sty.dxf.width = 0.7
    try:
        if "ACAD" not in doc.appids:
            doc.appids.new("ACAD")
    except Exception:
        pass
    _sty.set_xdata("ACAD", [(1000, "仿宋"), (1071, 0)])


def _ensure_profile_layers(doc, layer_prefix=""):
    """确保纵断面所需的图层存在。layer_prefix 用于合并导出时区分组件。"""
    layer_defs = [
        ("表格线框", 7), ("渠底高程线", 3), ("渠顶高程线", 1),
        ("设计水位线", 5), ("文字标注", 7),
    ]
    for name, color in layer_defs:
        full = layer_prefix + name
        if full not in doc.layers:
            doc.layers.new(full, dxfattribs={"color": color})


def _compute_ip_preview_data(nodes, station_prefix):
    """从节点列表计算IP坐标及弯道参数表预览数据。
    返回 (preview_data, real_nodes)。"""
    real_nodes = [
        n for n in nodes
        if not getattr(n, 'is_transition', False)
        and not getattr(n, 'is_auto_inserted_channel', False)
    ]

    def _safe_float(val, default=0.0):
        if val is None:
            return default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def _format_ip_name(node):
        try:
            if _in_out_val(node.in_out) in ("进", "出"):
                struct_abbr = ""
                struct_str = _struct_val(node.structure_type)
                if struct_str:
                    if "隧洞" in struct_str: struct_abbr = "隧"
                    elif "倒虹吸" in struct_str: struct_abbr = "倒"
                    elif "有压管道" in struct_str: struct_abbr = "管"
                    elif "渡槽" in struct_str: struct_abbr = "渡"
                    elif "暗涵" in struct_str: struct_abbr = "暗"
                in_out_str = "进" if _in_out_val(node.in_out) == "进" else "出"
                return f"{node.name}{struct_abbr}{in_out_str}"
        except Exception:
            pass
        return f"{station_prefix}IP{getattr(node, 'ip_number', 0)}"

    def _format_station(value):
        return ProjectSettings.format_station(_safe_float(value), station_prefix)

    preview_data = []
    for idx, node in enumerate(real_nodes):
        try:
            row = [
                _format_ip_name(node),
                f"{_safe_float(node.x):.6f}",
                f"{_safe_float(node.y):.6f}",
                _format_station(node.station_BC),
                _format_station(node.station_MC),
                _format_station(node.station_EC),
                f"{_safe_float(node.turn_angle):.3f}",
                f"{_safe_float(node.turn_radius):.3f}",
                f"{_safe_float(node.tangent_length):.3f}",
                f"{_safe_float(node.arc_length):.3f}",
                f"{_safe_float(node.bottom_elevation):.3f}" if _safe_float(node.bottom_elevation) != 0 else "-",
            ]
            preview_data.append(row)
        except Exception:
            preview_data.append([
                f"IP{getattr(node, 'ip_number', '?')}",
                "0.000000", "0.000000",
                "0+000.000", "0+000.000", "0+000.000",
                "0.000", "0.000", "0.000", "0.000", "-",
            ])
    return preview_data, real_nodes


def _parse_positive_dn(text):
    """解析 DN 输入，返回正整数；非法时返回 None。"""
    if text is None:
        return None
    t = str(text).strip()
    if not t:
        return None
    try:
        fv = float(t)
    except (TypeError, ValueError):
        return None
    if not fv.is_integer():
        return None
    dn = int(fv)
    return dn if dn > 0 else None


def _normalize_dn_mm(dn_value, default_dn=1500):
    """将 DN 归一化为正整数 mm。"""
    dn = _parse_positive_dn(dn_value)
    if dn is not None:
        return dn
    default = _parse_positive_dn(default_dn)
    return default if default is not None else 1500


def _extract_named_pressurized_groups(nodes, structure_kind):
    """提取按名称分组的有压流建筑物，返回 [(name, dn_mm), ...]。"""
    groups = {}
    order = []
    if not nodes:
        return []

    is_siphon = (structure_kind == "siphon")
    default_name = "倒虹吸" if is_siphon else "有压管道"

    for node in nodes:
        if getattr(node, 'is_transition', False) or getattr(node, 'is_auto_inserted_channel', False):
            continue

        st_str = _struct_val(getattr(node, 'structure_type', None))
        if is_siphon:
            matched = bool(getattr(node, 'is_inverted_siphon', False) or ('倒虹吸' in st_str))
        else:
            matched = ('有压管道' in st_str)
        if not matched:
            continue

        raw_name = getattr(node, 'name', '') or ''
        display_name = raw_name.strip() if raw_name.strip() else default_name
        if display_name not in groups:
            groups[display_name] = 0
            order.append(display_name)

        params = getattr(node, 'section_params', {}) or {}
        d_val = 0.0
        for key in ('D', 'd'):
            try:
                v = float(params.get(key, 0) or 0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0:
                d_val = v
                break
        if d_val <= 0:
            try:
                d_val = float(getattr(node, 'structure_height', 0) or 0)
            except (TypeError, ValueError):
                d_val = 0.0

        if d_val > 0:
            dn_mm = d_val * 1000 if d_val < 20 else d_val
            groups[display_name] = max(groups[display_name], dn_mm)

    return [(name, groups[name]) for name in order]


def _merge_pressurized_param_defaults(group_items, cached_rows, default_material="球墨铸铁管"):
    """按名称将历史配置与当前分组合并，返回 [(name, material, dn_mm), ...]。"""
    cached_map = {}
    for row in cached_rows or []:
        if not isinstance(row, (tuple, list)) or len(row) < 3:
            continue
        name = str(row[0] or "").strip()
        if not name:
            continue
        mat = str(row[1] or "").strip() or default_material
        dn = _normalize_dn_mm(row[2], 1500)
        cached_map[name] = (mat, dn)

    merged = []
    for name, dn_mm in group_items or []:
        base_dn = _normalize_dn_mm(dn_mm, 1500)
        mat, dn = cached_map.get(name, (default_material, base_dn))
        merged.append((name, mat, _normalize_dn_mm(dn, base_dn)))
    return merged


def _build_pressurized_segments(qs, overrides_by_idx, params, has_source_data, segment_name_fn):
    """基于分组参数构建倒虹吸/有压管道 segments。"""
    if not params:
        return []

    overrides = overrides_by_idx or {}
    if has_source_data and overrides:
        indices = sorted(overrides.keys())
    else:
        indices = list(range(1, len(qs) + 1))
    if not indices:
        return []

    normalized_params = []
    for struct_name, pipe_material, dn_mm in params:
        normalized_params.append((
            str(struct_name or "").strip(),
            str(pipe_material or "").strip(),
            _normalize_dn_mm(dn_mm, 1500),
        ))

    multi = len(normalized_params) > 1
    segs = []
    for idx in indices:
        seg_label = segment_name_fn(idx)
        base_override = {}
        if idx in overrides and isinstance(overrides[idx], dict):
            base_override = {k: v for k, v in overrides[idx].items() if k != "name"}

        candidates = []
        for struct_name, pipe_material, dn_norm in normalized_params:
            display_name = f"{struct_name}-{seg_label}" if multi else seg_label
            seg = {"name": display_name}
            if base_override:
                seg.update(base_override)
            if 0 < idx <= len(qs):
                seg["Q"] = qs[idx - 1]
            seg["DN_mm"] = dn_norm
            seg["pipe_material"] = pipe_material
            candidates.append(seg)

        if len(candidates) <= 1:
            segs.extend(candidates)
            continue

        signatures = {
            (
                item.get("Q"),
                item.get("n"),
                item.get("DN_mm"),
                item.get("pipe_material"),
            )
            for item in candidates
        }
        if len(signatures) == 1:
            merged = dict(candidates[0])
            merged["name"] = seg_label
            segs.append(merged)
        else:
            segs.extend(candidates)
    return segs


# ================================================================
# 纵断面表格导出设置对话框
# ================================================================

class _LegacyTextExportSettingsDialog(QDialog):
    """旧版纵断面文字导出参数弹窗（保留作历史参考）。"""

    def __init__(self, parent=None, defaults=None):
        super().__init__(parent)
        self.setWindowTitle("纵断面文字导出设置")
        self.setMinimumWidth(420)
        self.setStyleSheet(DIALOG_STYLE)
        self.result = None

        if defaults is None:
            defaults = {}
        self._defaults = {
            'y_bottom': defaults.get('y_bottom', 1),
            'y_top': defaults.get('y_top', 31),
            'y_water': defaults.get('y_water', 16),
            'text_height': defaults.get('text_height', 3.5),
            'rotation': defaults.get('rotation', 90),
            'elev_decimals': defaults.get('elev_decimals', 3),
            'y_name': defaults.get('y_name', 115),
            'y_slope': defaults.get('y_slope', 105),
            'y_ip': defaults.get('y_ip', 77),
            'y_station': defaults.get('y_station', 47),
            'y_line_height': defaults.get('y_line_height', 120),
            'scale_x': defaults.get('scale_x', 1),
            'scale_y': defaults.get('scale_y', 1),
        }

        self._entries = {}
        self._init_ui()

    def _init_ui(self):
        lay = QVBoxLayout(self)

        # Y坐标设置
        y_grp = QGroupBox("Y 坐标设置（CAD 表格行高）")
        y_form = QGridLayout(y_grp)
        for row, (label, key) in enumerate([
            ("渠底文字 Y 坐标:", 'y_bottom'),
            ("渠顶文字 Y 坐标:", 'y_top'),
            ("水面文字 Y 坐标:", 'y_water'),
        ]):
            y_form.addWidget(QLabel(label), row, 0)
            e = LineEdit(); e.setText(str(self._defaults[key])); e.setFixedWidth(100)
            y_form.addWidget(e, row, 1)
            self._entries[key] = e
        lay.addWidget(y_grp)

        # 文字样式
        style_grp = QGroupBox("文字样式")
        style_form = QGridLayout(style_grp)
        for row, (label, key) in enumerate([
            ("字高:", 'text_height'),
            ("旋转角度:", 'rotation'),
            ("高程小数位数:", 'elev_decimals'),
        ]):
            style_form.addWidget(QLabel(label), row, 0)
            e = LineEdit(); e.setText(str(self._defaults[key])); e.setFixedWidth(100)
            style_form.addWidget(e, row, 1)
            self._entries[key] = e
        lay.addWidget(style_grp)

        # 纵断面信息列
        info_grp = QGroupBox("纵断面信息列 Y 坐标")
        info_form = QGridLayout(info_grp)
        for row, (label, key) in enumerate([
            ("建筑物名称 Y 坐标:", 'y_name'),
            ("坡降 Y 坐标:", 'y_slope'),
            ("IP点名称 Y 坐标:", 'y_ip'),
            ("里程桩号 Y 坐标:", 'y_station'),
            ("整线竖线高度:", 'y_line_height'),
        ]):
            info_form.addWidget(QLabel(label), row, 0)
            e = LineEdit(); e.setText(str(self._defaults[key])); e.setFixedWidth(100)
            info_form.addWidget(e, row, 1)
            self._entries[key] = e
        lay.addWidget(info_grp)

        # 比例设置
        scale_grp = QGroupBox("比例设置")
        scale_form = QGridLayout(scale_grp)
        scale_form.addWidget(QLabel("X 方向 (1:N)，N ="), 0, 0)
        e = LineEdit(); e.setText(str(self._defaults['scale_x'])); e.setFixedWidth(100)
        scale_form.addWidget(e, 0, 1)
        scale_form.addWidget(QLabel("如 1:1000 则输入 1000"), 0, 2)
        self._entries['scale_x'] = e
        scale_form.addWidget(QLabel("Y 方向 (1:N)，N ="), 1, 0)
        e = LineEdit(); e.setText(str(self._defaults['scale_y'])); e.setFixedWidth(100)
        scale_form.addWidget(e, 1, 1)
        scale_form.addWidget(QLabel("如 1:1000 则输入 1000"), 1, 2)
        self._entries['scale_y'] = e
        lay.addWidget(scale_grp)

        # 预览
        preview_grp = QGroupBox("命令格式预览")
        preview_lay = QVBoxLayout(preview_grp)
        self._preview_label = QLabel()
        self._preview_label.setStyleSheet("color: #336699;")
        self._preview_label.setFont(QFont("Consolas", 9))
        preview_lay.addWidget(self._preview_label)
        lay.addWidget(preview_grp)
        self._update_preview()
        for entry in self._entries.values():
            entry.textChanged.connect(self._update_preview)

        # 按钮
        btn_lay = QHBoxLayout()
        btn_reset = PushButton("恢复默认"); btn_reset.clicked.connect(self._reset_defaults)
        btn_lay.addWidget(btn_reset); btn_lay.addStretch()
        btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(self.reject)
        btn_ok = PrimaryPushButton("确定"); btn_ok.clicked.connect(self._on_confirm)
        btn_lay.addWidget(btn_cancel); btn_lay.addWidget(btn_ok)
        lay.addLayout(btn_lay)

        # 键盘快捷键
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.reject)
        QShortcut(QKeySequence(Qt.Key_Return), self, self._on_confirm)

    def _update_preview(self):
        try:
            y_b = self._entries['y_bottom'].text().strip()
            h = self._entries['text_height'].text().strip()
            r = self._entries['rotation'].text().strip()
            d = self._entries['elev_decimals'].text().strip()
            try:
                decimals = int(float(d))
                sample = f"{431.666:.{decimals}f}"
            except Exception:
                sample = "431.666"
            self._preview_label.setText(f"-text 里程MC,{y_b} {h} {r} {sample} ")
        except Exception:
            self._preview_label.setText("-text 里程MC,Y 字高 角度 高程 ")

    def _reset_defaults(self):
        original = {
            'y_bottom': 1, 'y_top': 31, 'y_water': 16,
            'text_height': 3.5, 'rotation': 90, 'elev_decimals': 3,
            'y_name': 115, 'y_slope': 105, 'y_ip': 77,
            'y_station': 47, 'y_line_height': 120,
            'scale_x': 1, 'scale_y': 1,
        }
        for key, value in original.items():
            self._entries[key].setText(str(value))
        self._update_preview()

    def _on_confirm(self):
        try:
            result = {}
            for key, entry in self._entries.items():
                val_str = entry.text().strip()
                if not val_str:
                    raise ValueError("参数不能为空")
                val = float(val_str)
                if key == 'elev_decimals':
                    if val < 0 or val != int(val):
                        raise ValueError("高程小数位数必须为非负整数")
                    val = int(val)
                if key in ('scale_x', 'scale_y'):
                    if val <= 0:
                        raise ValueError("比例尺必须大于0")
                result[key] = val
            self.result = result
            self.accept()
        except ValueError as e:
            fluent_error(self, "输入错误", f"请输入有效的数值:\n{str(e)}")


# ===================== 重构版：Win11 Fluent + 双列直拖 =====================

class _ProfileRowDragListWidget(ListWidget):
    """支持跨列拖放的纵断面行列表。"""

    rowsDropped = Signal(str, list, int, str)  # source_role, ids, row, target_role

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self._role = role
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.viewport().setAcceptDrops(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDrop)

    def _selected_ids(self):
        rows = sorted({self.row(item) for item in self.selectedItems()})
        out = []
        for row in rows:
            item = self.item(row)
            if item is None:
                continue
            rid = str(item.data(Qt.UserRole) or "").strip()
            if rid:
                out.append(rid)
        return out

    def startDrag(self, supportedActions):
        row_ids = self._selected_ids()
        if not row_ids:
            return
        payload = {"source": self._role, "ids": row_ids}
        mime = QMimeData()
        mime.setData(
            "application/x-profile-row-ids",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-profile-row-ids"):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-profile-row-ids"):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        data = event.mimeData()
        if not data.hasFormat("application/x-profile-row-ids"):
            super().dropEvent(event)
            return
        try:
            payload = json.loads(bytes(data.data("application/x-profile-row-ids")).decode("utf-8"))
            source_role = str(payload.get("source", "")).strip()
            row_ids = [str(rid).strip() for rid in payload.get("ids", []) if str(rid).strip()]
            if not source_role or not row_ids:
                event.ignore()
                return
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            row = self.indexAt(pos).row()
            if row < 0:
                row = self.count()
            self.rowsDropped.emit(source_role, row_ids, row, self._role)
            event.acceptProposedAction()
        except Exception:
            event.ignore()


class _LegacyTextExportSettingsDialogDualList(QDialog):
    """纵断面导出参数与行配置弹窗（Win11 Fluent 风格重构版）。"""

    _UI_SETTINGS_ORG = "SichuanShuifa"
    _UI_SETTINGS_APP = "HydroCalc"
    _UI_SIZE_W_KEY = "water_profile/text_export_dialog_width"
    _UI_SIZE_H_KEY = "water_profile/text_export_dialog_height"
    _UI_PREVIEW_EXPANDED_KEY = "water_profile/text_export_dialog_preview_expanded"
    _ICON_COLLAPSED = _resolve_fluent_icon("CHEVRON_RIGHT_MED", "CHEVRON_RIGHT", "CHEVRON_DOWN_MED")
    _ICON_EXPANDED = _resolve_fluent_icon("CHEVRON_DOWN_MED", "CHEVRON_RIGHT_MED", "CHEVRON_RIGHT")

    def __init__(self, parent=None, defaults=None):
        super().__init__(parent)
        self.setWindowTitle("纵断面文字导出设置")
        self.setMinimumSize(960, 500)
        self._ui_settings = QSettings(self._UI_SETTINGS_ORG, self._UI_SETTINGS_APP)
        self._preview_expanded = self._read_setting_bool(self._UI_PREVIEW_EXPANDED_KEY, True)
        self._apply_initial_size()
        self.setSizeGripEnabled(True)
        self.setStyleSheet(DIALOG_STYLE + """
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f7f9fc, stop:1 #eef3fb);
            }
            QListView {
                border: 1px solid #d6dfef;
                border-radius: 10px;
                background: rgba(255,255,255,0.92);
                padding: 4px;
            }
            QListView::item {
                border-radius: 8px;
                padding: 5px 10px;
                margin: 1px 1px;
            }
            QListView::item:selected {
                background: rgba(0, 120, 212, 0.16);
                border: 1px solid rgba(0, 120, 212, 0.35);
            }
            QListView::item:hover {
                background: rgba(32, 97, 181, 0.08);
            }
        """)
        self.result = None
        self._row_updating = False
        self._segment_key = "all"

        defaults = _normalize_text_export_settings(defaults or {})
        self._defaults = dict(defaults)

        self._entries = {}
        self._ordered_row_ids = list(_PROFILE_ROW_DEFAULT_ORDER)
        self._enabled_row_ids = []

        self._candidate_search = None
        self._candidate_segment = None
        self._candidate_list = None
        self._enabled_list = None
        self._advanced_body = None
        self._advanced_toggle_btn = None
        self._preview_label = None
        self._preview_body = None
        self._preview_toggle_btn = None

        self._init_ui()

    def _read_setting_bool(self, key, default=False):
        raw = self._ui_settings.value(key, default)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        text = str(raw).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return bool(default)

    def _read_setting_int(self, key, default_value):
        raw = self._ui_settings.value(key, default_value)
        try:
            return int(float(raw))
        except Exception:
            return int(default_value)

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

    def _apply_initial_size(self):
        avail = self._available_geometry()
        if avail is not None:
            default_w = min(max(self.minimumWidth(), int(avail.width() * 0.78)), 1360)
            default_h = min(max(self.minimumHeight(), int(avail.height() * 0.72)), int(avail.height() * 0.92))
            max_w = max(self.minimumWidth(), int(avail.width() * 0.96))
            max_h = max(self.minimumHeight(), int(avail.height() * 0.92))
        else:
            default_w, default_h = 1160, 640
            max_w, max_h = 1400, 900

        width = self._read_setting_int(self._UI_SIZE_W_KEY, default_w)
        height = self._read_setting_int(self._UI_SIZE_H_KEY, default_h)
        width = max(self.minimumWidth(), min(width, max_w))
        height = max(self.minimumHeight(), min(height, max_h))
        self.resize(width, height)

    def _persist_ui_state(self):
        size = self.size()
        self._ui_settings.setValue(self._UI_SIZE_W_KEY, int(size.width()))
        self._ui_settings.setValue(self._UI_SIZE_H_KEY, int(size.height()))
        self._ui_settings.setValue(self._UI_PREVIEW_EXPANDED_KEY, bool(self._preview_expanded))

    def closeEvent(self, event):
        self._persist_ui_state()
        super().closeEvent(event)

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 8, 14, 8)
        root.setSpacing(6)

        body_row = QHBoxLayout()
        body_row.setSpacing(8)

        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        left_col.addWidget(self._build_basic_card())
        left_col.addWidget(self._build_advanced_card())
        left_col.addStretch(0)

        right_col = QVBoxLayout()
        right_col.setSpacing(8)
        right_col.addWidget(self._build_rows_card(), 0)
        right_col.addWidget(self._build_preview_card(), 0)
        right_col.addStretch(1)

        body_row.addLayout(left_col, 38)
        body_row.addLayout(right_col, 62)
        body_row.setAlignment(left_col, Qt.AlignTop)
        body_row.setAlignment(right_col, Qt.AlignTop)
        root.addLayout(body_row, 1)

        btn_row = QHBoxLayout()
        btn_reset = PushButton("恢复默认")
        btn_reset.clicked.connect(self._reset_defaults)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch(1)
        btn_cancel = PushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = PrimaryPushButton("确定")
        btn_ok.clicked.connect(self._on_confirm)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        root.addLayout(btn_row)

        self._load_rows(self._defaults.get("profile_row_items"))
        for entry in self._entries.values():
            entry.textChanged.connect(self._update_preview)
        self._update_preview()

        QShortcut(QKeySequence(Qt.Key_Escape), self, self.reject)
        QShortcut(QKeySequence(Qt.Key_Return), self, self._on_confirm)
        QShortcut(QKeySequence("Ctrl+Up"), self, lambda: self._move_selected_row(-1))
        QShortcut(QKeySequence("Ctrl+Down"), self, lambda: self._move_selected_row(1))
        QShortcut(QKeySequence(Qt.Key_Delete), self, self._remove_selected_rows)
        QShortcut(QKeySequence("Ctrl+Right"), self, self._enable_selected_rows)
        QShortcut(QKeySequence("Ctrl+Left"), self, self._remove_selected_rows)

    def _build_basic_card(self):
        card = ElevatedCardWidget(self)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(12, 10, 12, 10)
        card_lay.setSpacing(8)

        card_lay.addWidget(BodyLabel("基础参数"))
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.setColumnStretch(0, 0)
        form.setColumnStretch(1, 0)
        form.setColumnStretch(2, 1)
        self._add_entry_row(form, 0, "字高", "text_height", "")
        self._add_entry_row(form, 1, "旋转角度", "rotation", "")
        self._add_entry_row(form, 2, "高程小数位数", "elev_decimals", "")
        self._add_entry_row(form, 3, "X方向比例(1:N)", "scale_x", "如 1:1000 则输入 1000")
        self._add_entry_row(form, 4, "Y方向比例(1:N)", "scale_y", "如 1:1000 则输入 1000")
        card_lay.addLayout(form)
        return card

    def _build_advanced_card(self):
        card = ElevatedCardWidget(self)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(12, 10, 12, 10)
        card_lay.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(BodyLabel("高级参数（旧版Y坐标）"))
        self._advanced_toggle_btn = ToolButton(self._ICON_COLLAPSED)
        self._advanced_toggle_btn.clicked.connect(self._toggle_advanced)
        row.addStretch(1)
        row.addWidget(self._advanced_toggle_btn)
        card_lay.addLayout(row)

        self._advanced_body = QWidget()
        adv_form = QGridLayout(self._advanced_body)
        adv_form.setHorizontalSpacing(8)
        adv_form.setVerticalSpacing(6)
        adv_form.setColumnStretch(2, 1)
        self._add_entry_row(adv_form, 0, "渠底文字Y", "y_bottom", "")
        self._add_entry_row(adv_form, 1, "渠顶文字Y", "y_top", "")
        self._add_entry_row(adv_form, 2, "水面文字Y", "y_water", "")
        self._add_entry_row(adv_form, 3, "建筑物名称Y", "y_name", "兼容旧项目")
        self._add_entry_row(adv_form, 4, "坡降Y", "y_slope", "兼容旧项目")
        self._add_entry_row(adv_form, 5, "IP点名称Y", "y_ip", "兼容旧项目")
        self._add_entry_row(adv_form, 6, "里程桩号Y", "y_station", "兼容旧项目")
        self._add_entry_row(adv_form, 7, "最小竖线高度", "y_line_height", "最小值 > 0")
        self._advanced_body.setVisible(False)
        card_lay.addWidget(self._advanced_body)
        return card

    def _build_rows_card(self):
        card = ElevatedCardWidget(self)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(12, 10, 12, 10)
        card_lay.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.addWidget(BodyLabel("纵断面行内容（13项可选，可排序）"))
        title_row.addStretch(1)
        btn_preset = PushButton("应用亭子口二期项建/可研阶段模板")
        btn_preset.clicked.connect(self._apply_tingzikou_preset)
        title_row.addWidget(btn_preset)
        card_lay.addLayout(title_row)

        quick_row = QHBoxLayout()
        btn_enable_all = PushButton("全启用")
        btn_enable_all.clicked.connect(self._enable_all_rows)
        btn_disable_all = PushButton("全停用")
        btn_disable_all.clicked.connect(self._disable_all_rows)
        btn_restore_recommended = PushButton("恢复推荐")
        btn_restore_recommended.clicked.connect(self._restore_recommended_rows)
        quick_row.addWidget(btn_enable_all)
        quick_row.addWidget(btn_disable_all)
        quick_row.addWidget(btn_restore_recommended)
        quick_row.addStretch(1)
        card_lay.addLayout(quick_row)

        list_row = QHBoxLayout()
        list_row.setSpacing(8)

        candidate_col = QVBoxLayout()
        candidate_col.setSpacing(6)
        candidate_col.addWidget(BodyLabel("可选项"))
        self._candidate_segment = SegmentedWidget(self)
        self._candidate_segment.addItem("all", "全部", onClick=lambda: self._set_candidate_segment("all"))
        self._candidate_segment.addItem("recommended", "推荐", onClick=lambda: self._set_candidate_segment("recommended"))
        self._candidate_segment.addItem("extended", "扩展", onClick=lambda: self._set_candidate_segment("extended"))
        self._candidate_segment.setCurrentItem("all")
        candidate_col.addWidget(self._candidate_segment)
        self._candidate_search = SearchLineEdit()
        self._candidate_search.setPlaceholderText("搜索行内容（中文包含匹配）")
        self._candidate_search.textChanged.connect(self._refresh_row_lists)
        candidate_col.addWidget(self._candidate_search)
        self._candidate_list = _ProfileRowDragListWidget("candidate", self)
        self._candidate_list.rowsDropped.connect(self._on_rows_dropped)
        self._candidate_list.itemDoubleClicked.connect(lambda _item: self._enable_selected_rows())
        candidate_col.addWidget(self._candidate_list, 1)

        action_col = QVBoxLayout()
        action_col.setSpacing(6)
        action_col.addStretch(1)
        btn_add = PushButton("添加 ->")
        btn_add.clicked.connect(self._enable_selected_rows)
        btn_remove = PushButton("<- 移除")
        btn_remove.clicked.connect(self._remove_selected_rows)
        action_col.addWidget(btn_add)
        action_col.addWidget(btn_remove)
        action_col.addStretch(1)

        enabled_col = QVBoxLayout()
        enabled_col.setSpacing(6)
        enabled_col.addWidget(BodyLabel("已启用项（支持拖拽排序）"))
        self._enabled_list = _ProfileRowDragListWidget("enabled", self)
        self._enabled_list.rowsDropped.connect(self._on_rows_dropped)
        self._enabled_list.itemDoubleClicked.connect(lambda _item: self._remove_selected_rows())
        enabled_col.addWidget(self._enabled_list, 1)
        sort_row = QHBoxLayout()
        btn_up = PushButton("上移")
        btn_up.clicked.connect(lambda: self._move_selected_row(-1))
        btn_down = PushButton("下移")
        btn_down.clicked.connect(lambda: self._move_selected_row(1))
        sort_row.addWidget(btn_up)
        sort_row.addWidget(btn_down)
        sort_row.addStretch(1)
        enabled_col.addLayout(sort_row)

        list_row.addLayout(candidate_col, 46)
        list_row.addLayout(action_col, 12)
        list_row.addLayout(enabled_col, 42)
        card_lay.addLayout(list_row, 0)
        return card

    def _build_preview_card(self):
        card = ElevatedCardWidget(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(BodyLabel("当前配置预览"))
        row.addStretch(1)
        self._preview_toggle_btn = ToolButton(self._ICON_EXPANDED)
        self._preview_toggle_btn.clicked.connect(self._toggle_preview)
        row.addWidget(self._preview_toggle_btn)
        lay.addLayout(row)

        self._preview_body = QWidget()
        preview_lay = QVBoxLayout(self._preview_body)
        preview_lay.setContentsMargins(0, 0, 0, 0)
        preview_lay.setSpacing(0)

        self._preview_label = QLabel()
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet("color:#245A9B; font-family:'Consolas','Microsoft YaHei';")
        preview_lay.addWidget(self._preview_label)
        lay.addWidget(self._preview_body)
        self._set_preview_expanded(self._preview_expanded)
        return card

    def _set_preview_expanded(self, expanded):
        self._preview_expanded = bool(expanded)
        if self._preview_body is not None:
            self._preview_body.setVisible(self._preview_expanded)
        if self._preview_toggle_btn is not None:
            self._preview_toggle_btn.setIcon(self._ICON_EXPANDED if self._preview_expanded else self._ICON_COLLAPSED)

    def _toggle_preview(self):
        self._set_preview_expanded(not self._preview_expanded)

    def _add_entry_row(self, layout, row, label, key, hint):
        layout.addWidget(QLabel(f"{label}:"), row, 0)
        entry = LineEdit()
        entry.setText(str(self._defaults.get(key, "")))
        entry.setFixedWidth(130)
        layout.addWidget(entry, row, 1)
        layout.addWidget(CaptionLabel(hint), row, 2)
        self._entries[key] = entry

    def _toggle_advanced(self):
        visible = not self._advanced_body.isVisible()
        self._advanced_body.setVisible(visible)
        self._advanced_toggle_btn.setIcon(self._ICON_EXPANDED if visible else self._ICON_COLLAPSED)

    def _set_candidate_segment(self, key):
        self._segment_key = key
        self._refresh_row_lists()

    def _selected_ids(self, list_widget):
        rows = sorted({list_widget.row(item) for item in list_widget.selectedItems()})
        ids = []
        for row in rows:
            item = list_widget.item(row)
            if item is None:
                continue
            rid = str(item.data(Qt.UserRole) or "").strip()
            if rid in _PROFILE_ROW_DEF_MAP:
                ids.append(rid)
        return ids

    def _create_row_item(self, rid):
        from PySide6.QtWidgets import QListWidgetItem
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QColor

        row_def = _PROFILE_ROW_DEF_MAP[rid]
        badge = "  ★推荐" if rid in _PROFILE_RECOMMENDED_ROW_IDS else ""
        title = f"{row_def['label']}{badge}"
        hint = row_def.get("hint", "")
        list_item = QListWidgetItem(f"{title}\n{hint}")
        list_item.setData(Qt.UserRole, rid)
        if rid in _PROFILE_RECOMMENDED_ROW_IDS:
            list_item.setForeground(QColor("#174EA6"))
        list_item.setSizeHint(QSize(0, 44))
        return list_item

    def _normalize_row_model(self):
        enabled = [rid for rid in self._enabled_row_ids if rid in _PROFILE_ROW_DEF_MAP]
        order = [rid for rid in self._ordered_row_ids if rid in _PROFILE_ROW_DEF_MAP]
        for rid in _PROFILE_ROW_DEFAULT_ORDER:
            if rid not in order:
                order.append(rid)
        disabled = [rid for rid in order if rid not in enabled]
        self._enabled_row_ids = enabled
        self._ordered_row_ids = enabled + disabled

    def _candidate_visible(self, rid):
        if rid in self._enabled_row_ids:
            return False
        if self._segment_key == "recommended" and rid not in _PROFILE_RECOMMENDED_ROW_IDS:
            return False
        if self._segment_key == "extended" and rid not in _PROFILE_EXTENDED_ROW_IDS:
            return False
        q = (self._candidate_search.text() if self._candidate_search else "").strip()
        if q and q not in _PROFILE_ROW_DEF_MAP[rid]["label"]:
            return False
        return True

    def _refresh_row_lists(self, *_args):
        if not self._candidate_list or not self._enabled_list:
            return
        self._normalize_row_model()
        keep_candidate = set(self._selected_ids(self._candidate_list))
        keep_enabled = set(self._selected_ids(self._enabled_list))

        self._row_updating = True
        try:
            self._candidate_list.clear()
            for rid in self._ordered_row_ids:
                if not self._candidate_visible(rid):
                    continue
                item = self._create_row_item(rid)
                self._candidate_list.addItem(item)
                if rid in keep_candidate:
                    item.setSelected(True)

            self._enabled_list.clear()
            for rid in self._enabled_row_ids:
                item = self._create_row_item(rid)
                self._enabled_list.addItem(item)
                if rid in keep_enabled:
                    item.setSelected(True)
        finally:
            self._row_updating = False
        self._ensure_row_lists_visible_rows()
        self._update_preview()

    def _ensure_row_lists_visible_rows(self):
        if not self._enabled_list or not self._candidate_list:
            return
        row_h = max(self._enabled_list.sizeHintForRow(0), self._candidate_list.sizeHintForRow(0))
        if row_h <= 0:
            row_h = 44
        visible_rows = 8
        target_h = row_h * visible_rows + 12
        for list_widget in (self._candidate_list, self._enabled_list):
            list_widget.setMinimumHeight(target_h)
            list_widget.setMaximumHeight(target_h)

    def _load_rows(self, row_items):
        normalized = _normalize_profile_row_items(row_items)
        self._ordered_row_ids = [item["id"] for item in normalized]
        self._enabled_row_ids = [item["id"] for item in normalized if item.get("enabled")]
        self._refresh_row_lists()

    def _row_data_from_table(self):
        self._normalize_row_model()
        enabled = set(self._enabled_row_ids)
        return _normalize_profile_row_items([
            {"id": rid, "enabled": rid in enabled}
            for rid in self._ordered_row_ids
        ])

    def _apply_drop(self, source_role, row_ids, row, target_role):
        ids = [rid for rid in row_ids if rid in _PROFILE_ROW_DEF_MAP]
        if not ids:
            return

        enabled = list(self._enabled_row_ids)
        if source_role == "enabled" and target_role == "enabled":
            old_pos = [enabled.index(rid) for rid in ids if rid in enabled]
            remaining = [rid for rid in enabled if rid not in ids]
            row_adj = int(row) - sum(1 for p in old_pos if p < int(row))
            row_adj = max(0, min(len(remaining), row_adj))
            enabled = remaining[:row_adj] + ids + remaining[row_adj:]
        elif source_role == "candidate" and target_role == "enabled":
            insert_pos = max(0, min(len(enabled), int(row)))
            existing = [rid for rid in enabled if rid not in ids]
            enabled = existing[:insert_pos] + ids + existing[insert_pos:]
            InfoBar.success(
                "已启用",
                f"已添加 {len(ids)} 项",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=1200,
            )
        elif source_role == "enabled" and target_role == "candidate":
            enabled = [rid for rid in enabled if rid not in ids]
            InfoBar.info(
                "已停用",
                f"已移除 {len(ids)} 项",
                parent=self,
                position=InfoBarPosition.TOP_RIGHT,
                duration=1200,
            )
        else:
            return

        self._enabled_row_ids = enabled
        self._normalize_row_model()
        self._refresh_row_lists()

    def _on_rows_dropped(self, source_role, row_ids, row, target_role):
        if self._row_updating:
            return
        self._apply_drop(source_role, row_ids, row, target_role)

    def _enable_selected_rows(self):
        ids = self._selected_ids(self._candidate_list)
        if not ids:
            return
        enabled = [rid for rid in self._enabled_row_ids if rid not in ids]
        insert_pos = self._enabled_list.currentRow()
        if insert_pos < 0:
            insert_pos = len(enabled)
        enabled[insert_pos:insert_pos] = ids
        self._enabled_row_ids = enabled
        self._refresh_row_lists()

    def _remove_selected_rows(self):
        ids = set(self._selected_ids(self._enabled_list))
        if not ids:
            return
        self._enabled_row_ids = [rid for rid in self._enabled_row_ids if rid not in ids]
        self._refresh_row_lists()

    def _enable_all_rows(self):
        self._enabled_row_ids = list(_PROFILE_ROW_DEFAULT_ORDER)
        self._refresh_row_lists()

    def _disable_all_rows(self):
        self._enabled_row_ids = []
        self._refresh_row_lists()

    def _restore_recommended_rows(self):
        self._enabled_row_ids = [
            rid for rid in _PROFILE_ROW_DEFAULT_ORDER
            if rid in _PROFILE_RECOMMENDED_ROW_IDS
        ]
        self._refresh_row_lists()

    def _apply_tingzikou_preset(self):
        ordered = list(_TINGZIKOU_TEMPLATE_ROW_IDS) + [
            rid for rid in _PROFILE_ROW_DEFAULT_ORDER if rid not in _TINGZIKOU_TEMPLATE_ROW_IDS
        ]
        self._ordered_row_ids = ordered
        self._enabled_row_ids = list(_TINGZIKOU_TEMPLATE_ROW_IDS)
        self._refresh_row_lists()
        InfoBar.success(
            "模板已应用",
            "已切换为亭子口推荐顺序",
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=1500,
        )

    def _move_selected_row(self, delta):
        row = self._enabled_list.currentRow()
        if row < 0:
            return
        target = row + int(delta)
        if target < 0 or target >= len(self._enabled_row_ids):
            return
        rid = self._enabled_row_ids.pop(row)
        self._enabled_row_ids.insert(target, rid)
        self._refresh_row_lists()
        self._enabled_list.setCurrentRow(target)

    def _update_preview(self):
        try:
            enabled = [item for item in self._row_data_from_table() if item.get("enabled")]
            labels = [_PROFILE_ROW_DEF_MAP[item["id"]]["label"] for item in enabled[:6]]
            summary = "、".join(labels) if labels else "无"
            if len(enabled) > 6:
                summary += f" ...（共{len(enabled)}行）"
            self._preview_label.setText(
                f"已启用行：{summary}\n"
                f"示例：-text X,Y {self._entries['text_height'].text().strip()} "
                f"{self._entries['rotation'].text().strip()} 文本"
            )
        except Exception:
            self._preview_label.setText("预览不可用")

    def _reset_defaults(self):
        original = {
            "y_bottom": 1, "y_top": 31, "y_water": 16,
            "text_height": 3.5, "rotation": 90, "elev_decimals": 3,
            "y_name": 115, "y_slope": 105, "y_ip": 77,
            "y_station": 47, "y_line_height": 120,
            "scale_x": 1, "scale_y": 1,
        }
        for key, value in original.items():
            if key in self._entries:
                self._entries[key].setText(str(value))
        self._load_rows(_default_profile_row_items())
        self._update_preview()

    def _focus_invalid_entry(self, key):
        entry = self._entries.get(key)
        if not entry:
            return
        if key in {"y_bottom", "y_top", "y_water", "y_name", "y_slope", "y_ip", "y_station", "y_line_height"}:
            if self._advanced_body and not self._advanced_body.isVisible():
                self._toggle_advanced()
        entry.setFocus()
        entry.selectAll()

    def _on_confirm(self):
        try:
            parsed = {}
            ordered_keys = [
                "text_height", "rotation", "elev_decimals", "scale_x", "scale_y",
                "y_bottom", "y_top", "y_water",
                "y_name", "y_slope", "y_ip", "y_station", "y_line_height",
            ]
            labels = {
                "text_height": "字高",
                "rotation": "旋转角度",
                "elev_decimals": "高程小数位数",
                "scale_x": "X方向比例",
                "scale_y": "Y方向比例",
                "y_bottom": "渠底文字Y",
                "y_top": "渠顶文字Y",
                "y_water": "水面文字Y",
                "y_name": "建筑物名称Y",
                "y_slope": "坡降Y",
                "y_ip": "IP点名称Y",
                "y_station": "里程桩号Y",
                "y_line_height": "最小竖线高度",
            }
            for key in ordered_keys:
                entry = self._entries[key]
                txt = entry.text().strip()
                if not txt:
                    self._focus_invalid_entry(key)
                    raise ValueError(f"{labels[key]}不能为空")
                try:
                    val = float(txt)
                except ValueError:
                    self._focus_invalid_entry(key)
                    raise ValueError(f"{labels[key]}必须为数值")
                if key == "elev_decimals":
                    if val < 0 or val != int(val):
                        self._focus_invalid_entry(key)
                        raise ValueError("高程小数位数必须为非负整数")
                    val = int(val)
                if key in ("scale_x", "scale_y", "y_line_height") and val <= 0:
                    self._focus_invalid_entry(key)
                    raise ValueError("比例与最小竖线高度必须大于0")
                parsed[key] = val

            row_items = self._row_data_from_table()
            if not any(item.get("enabled") for item in row_items):
                self._enabled_list.setFocus()
                raise ValueError("至少选择1项行内容")

            result = dict(self._defaults)
            result.update(parsed)
            result["profile_row_items"] = row_items
            self.result = _normalize_text_export_settings(result)
            self.accept()
        except ValueError as e:
            fluent_error(self, "输入错误", f"请输入有效的数值:\n{str(e)}")
# ================================================================
# 有压流参数配置对话框
# ================================================================

TextExportSettingsDialog = _SingleListTextExportSettingsDialog


class PressurizedPipeConfigDialog(QDialog):
    """倒虹吸/有压管道参数配置对话框（导出全部DXF专用）。"""

    def __init__(self, parent=None, siphon_rows=None, pressure_pipe_rows=None, materials=None):
        super().__init__(parent)
        self.setWindowTitle("有压流建筑物参数设置")
        self.setMinimumSize(520, 420)
        self.setStyleSheet(DIALOG_STYLE)
        self.result = None

        self._materials = list(materials or _PRESSURIZED_PIPE_MATERIALS)
        if not self._materials:
            self._materials = ["球墨铸铁管"]
        self._siphon_rows = []
        self._pressure_pipe_rows = []

        lay = QVBoxLayout(self)
        desc = QLabel(
            "请确认倒虹吸/有压管道导出参数。\n"
            "规则与倒虹吸断面汇总表一致：按材质确定糙率，按 DN 计算设计流速。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size:12px; color:#333;")
        lay.addWidget(desc)

        if siphon_rows:
            self._build_group(
                parent_layout=lay,
                group_title="倒虹吸参数",
                name_header="倒虹吸名称",
                source_rows=siphon_rows,
                target_rows=self._siphon_rows,
            )
        if pressure_pipe_rows:
            self._build_group(
                parent_layout=lay,
                group_title="有压管道参数",
                name_header="有压管道名称",
                source_rows=pressure_pipe_rows,
                target_rows=self._pressure_pipe_rows,
            )

        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_cancel = PushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = PrimaryPushButton("确认")
        btn_ok.clicked.connect(self._on_confirm)
        btn_lay.addWidget(btn_cancel)
        btn_lay.addWidget(btn_ok)
        lay.addLayout(btn_lay)

        QShortcut(QKeySequence(Qt.Key_Escape), self, self.reject)
        QShortcut(QKeySequence(Qt.Key_Return), self, self._on_confirm)

    def _build_group(self, parent_layout, group_title, name_header, source_rows, target_rows):
        group = QGroupBox(group_title)
        group.setStyleSheet("QGroupBox{font-weight:bold;font-size:12px;}")
        glay = QVBoxLayout(group)

        hdr = QGridLayout()
        hdr.setSpacing(6)
        for ci, txt in enumerate([name_header, "管道材质", "DN (mm)"]):
            lbl = QLabel(txt)
            lbl.setStyleSheet("font-size:11px; color:#555; font-weight:bold;")
            hdr.addWidget(lbl, 0, ci)
        hdr.setColumnStretch(0, 2)
        hdr.setColumnStretch(1, 3)
        hdr.setColumnStretch(2, 2)
        glay.addLayout(hdr)

        grid = QGridLayout()
        grid.setSpacing(4)
        for ri, (name, material, dn_mm) in enumerate(source_rows):
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet("font-size:12px;")
            grid.addWidget(name_lbl, ri, 0)

            mat_combo = QComboBox()
            mat_combo.addItems(self._materials)
            mat_combo.setCurrentText(material if material in self._materials else self._materials[0])
            mat_combo.setFixedWidth(160)
            grid.addWidget(mat_combo, ri, 1)

            dn_edit = LineEdit()
            dn_edit.setFixedWidth(100)
            dn_edit.setText(str(_normalize_dn_mm(dn_mm, 1500)))
            grid.addWidget(dn_edit, ri, 2)

            target_rows.append((name, mat_combo, dn_edit))

        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 2)
        glay.addLayout(grid)
        parent_layout.addWidget(group)

    def _read_rows(self, rows, title_prefix):
        out = []
        for name, mat_combo, dn_edit in rows:
            dn = _parse_positive_dn(dn_edit.text())
            if dn is None:
                fluent_error(self, "输入错误", f"{title_prefix}“{name}”的 DN 必须为正整数")
                return None
            out.append((name, mat_combo.currentText(), dn))
        return out

    def _on_confirm(self):
        siphon = self._read_rows(self._siphon_rows, "倒虹吸")
        if siphon is None:
            return
        pressure_pipe = self._read_rows(self._pressure_pipe_rows, "有压管道")
        if pressure_pipe is None:
            return
        self.result = {
            "siphon": siphon,
            "pressure_pipe": pressure_pipe,
        }
        self.accept()


# ================================================================
# 平面图参数设置对话框
# ================================================================

class PlanTextSettingsDialog(QDialog):
    """建筑物名称上平面图参数设置对话框"""

    def __init__(self, parent=None, defaults=None):
        super().__init__(parent)
        self.setWindowTitle("建筑物名称上平面图 - 参数设置")
        self.setMinimumWidth(380)
        self.setStyleSheet(DIALOG_STYLE)
        self.result = None
        if defaults is None:
            defaults = {}
        self._init_ui(defaults)

    def _init_ui(self, defaults):
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "生成 AutoCAD -TEXT 命令，将建筑物名称平行于轴线放置。\n"
            "文字位于建筑物最中间两个IP点连线段的中点处。"
        ))

        form = QGridLayout()
        form.addWidget(QLabel("垂直偏移距离 (V):"), 0, 0)
        self.offset_edit = LineEdit(); self.offset_edit.setText(str(defaults.get('offset', 10)))
        self.offset_edit.setFixedWidth(100)
        form.addWidget(self.offset_edit, 0, 1)
        form.addWidget(QLabel("文字中心到轴线的距离"), 0, 2)

        form.addWidget(QLabel("文字高度:"), 1, 0)
        self.height_edit = LineEdit(); self.height_edit.setText(str(defaults.get('text_height', 10)))
        self.height_edit.setFixedWidth(100)
        form.addWidget(self.height_edit, 1, 1)
        form.addWidget(QLabel("AutoCAD -TEXT 字高"), 1, 2)
        lay.addLayout(form)

        # 预览
        preview_grp = QGroupBox("命令格式预览")
        preview_lay = QVBoxLayout(preview_grp)
        self._preview_label = QLabel()
        self._preview_label.setStyleSheet("color: gray;")
        preview_lay.addWidget(self._preview_label)
        lay.addWidget(preview_grp)
        self._update_preview()
        self.offset_edit.textChanged.connect(self._update_preview)
        self.height_edit.textChanged.connect(self._update_preview)

        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(self.reject)
        btn_ok = PrimaryPushButton("确定"); btn_ok.clicked.connect(self._on_confirm)
        btn_lay.addWidget(btn_cancel); btn_lay.addWidget(btn_ok)
        lay.addLayout(btn_lay)

        # 键盘快捷键
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.reject)
        QShortcut(QKeySequence(Qt.Key_Return), self, self._on_confirm)

    def _update_preview(self):
        try:
            o = self.offset_edit.text().strip()
            h = self.height_edit.text().strip()
            self._preview_label.setText(
                f"-TEXT J MC x,y {h} 角度 建筑物名称\n"
                f"（文字中心偏移轴线 {o} 个单位）")
        except Exception:
            pass

    def _on_confirm(self):
        try:
            o = float(self.offset_edit.text().strip())
            h = float(self.height_edit.text().strip())
            if h <= 0:
                raise ValueError("文字高度必须大于0")
            self.result = {'offset': o, 'text_height': h}
            self.accept()
        except ValueError as e:
            fluent_error(self, "输入错误", f"请输入有效的数值:\n{e}")


# ================================================================
# 1. 生成纵断面表格 TXT
# ================================================================

def export_longitudinal_profile_txt(panel):
    """Generate longitudinal profile TXT in AutoCAD command format."""
    if not MODELS_AVAILABLE:
        fluent_info(panel.window(), "不可用", "核心模型未加载")
        return

    nodes = panel.calculated_nodes
    if not nodes:
        fluent_info(panel.window(), "警告", "没有数据可导出")
        return

    valid_nodes = [n for n in nodes if n.bottom_elevation or n.top_elevation or n.water_level]
    if not valid_nodes:
        fluent_info(panel.window(), "警告", "没有可用的高程数据，请先执行计算。")
        return

    dlg = TextExportSettingsDialog(panel.window(), panel._text_export_settings)
    if dlg.exec() != QDialog.Accepted or dlg.result is None:
        return

    panel._text_export_settings.update(dlg.result)
    settings = dlg.result

    try:
        ch_name = panel.channel_name_edit.text().strip()
        ch_level = panel.channel_level_combo.currentText()
        auto_name = f"{ch_name}{ch_level}_上纵断面表格.txt"
    except Exception:
        auto_name = "上纵断面表格.txt"

    file_path, _ = QFileDialog.getSaveFileName(
        panel, "保存上纵断面表格", auto_name,
        "文本文件 (*.txt);;所有文件 (*.*)")
    if not file_path:
        return

    _export_longitudinal_txt_to_path(panel, nodes, valid_nodes, settings, file_path)


# ================================================================
# 1b. ?????????
# ================================================================

def _draw_profile_on_msp(msp, nodes, valid_nodes, settings, station_prefix,
                         layer_prefix=""):
    """在 modelspace 上绘制纵断面表格（核心绘图逻辑）。

    msp 可以是真实的 ezdxf modelspace 或 _OffsetMSP 包装器。
    layer_prefix 用于合并导出时给图层名添加前缀以区分组件。
    返回 (width, height)。
    """
    import ezdxf

    settings = _normalize_text_export_settings(settings)
    text_height = settings["text_height"]
    rotation = settings["rotation"]
    elev_decimals = int(settings.get("elev_decimals", 3))
    scale_x = settings.get("scale_x", 1)
    scale_y = settings.get("scale_y", 1)
    enabled_row_ids, row_layout, _total_height, line_height, h_line_y_values = _build_profile_row_layout(settings)
    first_col_x_offset = text_height + 1.3

    def sx(mc):
        return mc / scale_x

    def sy(elev):
        return elev / scale_y

    def fmt_elev(value):
        if value is None:
            return f"{0:.{elev_decimals}f}"
        return f"{value:.{elev_decimals}f}"

    last_mc = nodes[-1].station_MC
    layer_grid = layer_prefix + "表格线框"
    layer_text = layer_prefix + "文字标注"

    # ======== 1. 表头区域线框 ========
    for hy in h_line_y_values:
        msp.add_line((-40, hy), (sx(0), hy), dxfattribs={"layer": layer_grid})
    msp.add_line((-40, 0), (-40, line_height), dxfattribs={"layer": layer_grid})
    msp.add_line((0, 0), (0, line_height), dxfattribs={"layer": layer_grid})

    # ======== 2. 节点竖线 ========
    if "slope" in row_layout:
        short_line_height = row_layout["slope"]["bottom"]
    elif "building_name" in row_layout:
        short_line_height = row_layout["building_name"]["bottom"]
    else:
        short_line_height = line_height

    has_bc_ec_rows = any(rid in row_layout for rid in _BC_ROW_IDS) or \
        any(rid in row_layout for rid in _EC_ROW_IDS)
    ip_segment_map = {}
    if has_bc_ec_rows:
        for n in _iter_profile_ip_nodes(nodes):
            _mc = float(getattr(n, "station_MC", 0) or 0.0)
            _bc = float(getattr(n, "station_BC", _mc) or _mc)
            _ec = float(getattr(n, "station_EC", _mc) or _mc)
            if abs(_bc - _mc) > 1e-9 or abs(_ec - _mc) > 1e-9:
                ip_segment_map[round(_mc, 6)] = n

    tall_line_mcs = []
    for node in nodes:
        mc = node.station_MC
        is_special = _is_special_inout_node(node)
        if is_special:
            tall_line_mcs.append(mc)
        v_top = line_height if is_special else short_line_height

        ip_ref = ip_segment_map.get(round(float(mc), 6)) if has_bc_ec_rows else None
        if ip_ref is not None:
            for seg_x, seg_y0, seg_y1 in _compute_node_vline_segments(
                    ip_ref, row_layout, enabled_row_ids, v_top):
                msp.add_line((sx(seg_x), seg_y0), (sx(seg_x), seg_y1),
                             dxfattribs={"layer": layer_grid})
        else:
            msp.add_line((sx(mc), 0), (sx(mc), v_top), dxfattribs={"layer": layer_grid})

    # ======== 3. 全宽水平线 ========
    for hy in h_line_y_values:
        msp.add_line((sx(0), hy), (sx(last_mc), hy), dxfattribs={"layer": layer_grid})

    # ======== 4. 渠底/渠顶/水面折线 ========
    bottom_pts = [(sx(n.station_MC), sy(n.bottom_elevation))
                  for n in valid_nodes if n.bottom_elevation]
    top_pts = [(sx(n.station_MC), sy(n.top_elevation))
               for n in valid_nodes if n.top_elevation]
    water_pts = [(sx(n.station_MC), sy(n.water_level))
                 for n in valid_nodes if n.water_level]

    if len(bottom_pts) >= 2:
        msp.add_lwpolyline(bottom_pts, dxfattribs={"layer": layer_prefix + "渠底高程线"})
    if len(top_pts) >= 2:
        msp.add_lwpolyline(top_pts, dxfattribs={"layer": layer_prefix + "渠顶高程线"})
    if len(water_pts) >= 2:
        msp.add_lwpolyline(water_pts, dxfattribs={"layer": layer_prefix + "设计水位线"})

    # ======== 5. 建筑物/坡降分段 ========
    name_mc_pairs = []
    for node in nodes:
        building_name = _get_building_display_name(node)
        if building_name:
            name_mc_pairs.append((building_name, node.station_MC))
    building_segments = []
    for bname, bmc in name_mc_pairs:
        if building_segments and building_segments[-1][0] == bname:
            building_segments[-1][1].append(bmc)
        else:
            building_segments.append((bname, [bmc]))
    building_segments = _merge_segments_across_gates(building_segments)

    # ======== 6. 各行文本 ========
    profile_text_nodes = _build_profile_text_nodes(nodes)
    ip_records = _build_ip_related_row_records(nodes, station_prefix)
    mc_to_node = {node.station_MC: node for node in nodes}
    text_attr_rot = {"layer": layer_text, "height": text_height, "rotation": rotation, "width": 0.7, "style": "Standard"}
    text_attr_no_rot = {"layer": layer_text, "height": text_height, "width": 0.7, "style": "Standard"}

    for rid in enabled_row_ids:
        y_pos = row_layout[rid]["text_y"]
        if rid in ("bottom_elev", "top_elev", "water_elev", "station"):
            for idx, node in enumerate(profile_text_nodes):
                station_mc = _profile_station_value(node)
                text_x = sx(station_mc) + first_col_x_offset if idx == 0 else sx(station_mc) - 1
                if rid == "bottom_elev":
                    text = fmt_elev(node.bottom_elevation)
                elif rid == "top_elev":
                    text = fmt_elev(node.top_elevation)
                elif rid == "water_elev":
                    text = fmt_elev(node.water_level)
                else:
                    try:
                        text = ProjectSettings.format_station(station_mc, station_prefix)
                    except Exception:
                        text = f"{station_prefix}{station_mc:.3f}"
                msp.add_text(text, dxfattribs=text_attr_rot).set_placement((text_x, y_pos))
            continue

        if rid == "building_name":
            for bname, mc_list in building_segments:
                if _is_gate_name(bname):
                    mid_mc = mc_list[0]
                else:
                    seg_start = mc_list[0]
                    seg_end = mc_list[-1]
                    mid_mc = _resolve_segment_mid_mc(seg_start, seg_end, tall_line_mcs)
                msp.add_text(bname, dxfattribs=text_attr_no_rot).set_placement(
                    (sx(mid_mc), y_pos), align=ezdxf.enums.TextEntityAlignment.MIDDLE
                )
            continue

        if rid == "slope":
            for bname, mc_list in building_segments:
                if _is_gate_name(bname):
                    continue
                seg_start = mc_list[0]
                seg_end = mc_list[-1]
                mid_mc = _resolve_segment_mid_mc(seg_start, seg_end, tall_line_mcs)
                if "倒虹吸" in bname or "有压管道" in bname:
                    msp.add_text("-", dxfattribs=text_attr_no_rot).set_placement(
                        (sx(mid_mc), y_pos), align=ezdxf.enums.TextEntityAlignment.MIDDLE
                    )
                    continue
                slope_text = _get_segment_slope_text(mc_list, mc_to_node)
                if not slope_text:
                    continue
                msp.add_text(slope_text, dxfattribs=text_attr_no_rot).set_placement(
                    (sx(mid_mc), y_pos), align=ezdxf.enums.TextEntityAlignment.MIDDLE
                )
            continue

        if rid in ip_records:
            for idx, rec in enumerate(ip_records[rid]):
                text_x = sx(rec["x"]) + first_col_x_offset if idx == 0 else sx(rec["x"]) - 1
                msp.add_text(rec["text"], dxfattribs=text_attr_rot).set_placement((text_x, y_pos))
            continue

    # ======== 7. 表头文字 ========
    header_cx = -40 + 20
    for rid in enabled_row_ids:
        row_info = row_layout[rid]
        labels = row_info.get("header_lines", [])
        if not labels:
            continue
        if len(labels) == 1:
            msp.add_text(
                labels[0], dxfattribs=text_attr_no_rot
            ).set_placement(
                (header_cx, (row_info["bottom"] + row_info["top"]) / 2.0),
                align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
            )
            continue
        line_spacing = text_height * 2.5
        block_h = line_spacing + text_height
        y_bottom_line = row_info["bottom"] + (row_info["height"] - block_h) / 2.0 + text_height / 2.0
        y_top_line = y_bottom_line + line_spacing
        msp.add_text(labels[0], dxfattribs=text_attr_no_rot).set_placement(
            (header_cx, y_top_line), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
        )
        msp.add_text(labels[1], dxfattribs=text_attr_no_rot).set_placement(
            (header_cx, y_bottom_line), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
        )

    return 40 + sx(last_mc), line_height


# ================================================================
# 1b. 生成纵断面表格 DXF（直接生成 CAD 可打开的 DXF 文件）
# ================================================================

def export_longitudinal_profile_dxf(panel):
    """一键生成上纵断面表格 DXF

    直接生成 DXF 文件，包含表格线框、渠底/渠顶/水面折线、
    高程文字、里程桩号、建筑物名称、坡降、IP点名称等全部内容。
    双击即可在 AutoCAD / 浩辰CAD / 中望CAD 中打开。
    """
    import ezdxf

    if not MODELS_AVAILABLE:
        fluent_info(panel.window(), "不可用", "核心模型未加载")
        return

    nodes = panel.calculated_nodes
    if not nodes:
        fluent_info(panel.window(), "警告", "没有数据可导出")
        return

    valid_nodes = [n for n in nodes if n.bottom_elevation or n.top_elevation or n.water_level]
    if not valid_nodes:
        fluent_info(panel.window(), "警告", "没有可用的高程数据，请先执行计算。")
        return

    # 弹出参数配置对话框（复用 TXT 版设置）
    dlg = TextExportSettingsDialog(panel.window(), panel._text_export_settings)
    if dlg.exec() != QDialog.Accepted or dlg.result is None:
        return

    settings = _normalize_text_export_settings(dlg.result)
    panel._text_export_settings.update(settings)
    if not _get_enabled_profile_row_ids(settings):
        fluent_error(panel.window(), "导出失败", "至少选择1项行内容后再导出。")
        return

    _show_special_angle_warning(panel, nodes)

    # 自动文件名
    try:
        ch_name = panel.channel_name_edit.text().strip()
        ch_level = panel.channel_level_combo.currentText()
        auto_name = f"{ch_name}{ch_level}_上纵断面表格.dxf"
    except Exception:
        auto_name = "上纵断面表格.dxf"

    file_path, _ = QFileDialog.getSaveFileName(
        panel, "保存上纵断面表格", auto_name,
        "DXF 文件 (*.dxf);;文本文件 (*.txt);;所有文件 (*.*)")
    if not file_path:
        return

    # 如果用户选择了 .txt，走原有 TXT 导出逻辑
    if file_path.lower().endswith('.txt'):
        _export_longitudinal_txt_to_path(panel, nodes, valid_nodes, settings, file_path)
        return

    try:
        try:
            proj_settings = panel._build_settings()
            station_prefix = proj_settings.get_station_prefix()
        except Exception:
            station_prefix = ""

        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        _setup_dxf_style(doc)
        _ensure_profile_layers(doc)

        _draw_profile_on_msp(msp, nodes, valid_nodes, settings, station_prefix)

        doc.saveas(file_path)

        if fluent_question(panel.window(), "完成",
                f"上纵断面表格 DXF 已生成（{len(nodes)} 个节点）:\n{file_path}\n\n是否立即打开该文件？"):
            os.startfile(file_path)

    except PermissionError:
        fluent_error(panel.window(), "文件被占用",
                     f"无法写入文件，该文件可能已被其他程序打开：\n\n{file_path}\n\n"
                     f"请先关闭该文件（如CAD等），然后重新操作。")
    except Exception as e:
        import traceback; traceback.print_exc()
        fluent_error(panel.window(), "导出错误", f"生成上纵断面表格 DXF 失败:\n{str(e)}")


def _export_longitudinal_txt_to_path(panel, nodes, valid_nodes, settings, file_path):
    """Internal helper: export longitudinal profile as AutoCAD TXT commands."""
    fmt = _format_number

    settings = _normalize_text_export_settings(settings)
    text_height = settings["text_height"]
    rotation = settings["rotation"]
    elev_decimals = int(settings.get("elev_decimals", 3))
    scale_x = settings.get("scale_x", 1)
    scale_y = settings.get("scale_y", 1)
    enabled_row_ids, row_layout, _total_height, line_height, h_line_y_values = _build_profile_row_layout(settings)
    first_col_x_offset = text_height + 1.3

    def sx(mc):
        return mc / scale_x

    def sy(elev):
        return elev / scale_y

    def fmt_elev(value):
        if value is None:
            return f"{0:.{elev_decimals}f}"
        return f"{value:.{elev_decimals}f}"

    try:
        proj_settings = panel._build_settings()
        station_prefix = proj_settings.get_station_prefix()
    except Exception:
        station_prefix = ""

    try:
        lines = []
        s_height = fmt(text_height)
        s_rotation = fmt(rotation)

        # ======== 1. ?????? ========
        for hy in h_line_y_values:
            hy_fmt = fmt(hy)
            lines.append(f"pl {fmt(sx(0))},{hy_fmt} -40,{hy_fmt} ")
        lines.append(f"pl -40,0 -40,{fmt(line_height)} ")
        lines.append(f"pl 0,0 0,{fmt(line_height)} ")
        lines.append("")

        # ======== 2. ???? ========
        if "slope" in row_layout:
            short_line_height = row_layout["slope"]["bottom"]
        elif "building_name" in row_layout:
            short_line_height = row_layout["building_name"]["bottom"]
        else:
            short_line_height = line_height

        has_bc_ec_rows = any(rid in row_layout for rid in _BC_ROW_IDS) or \
            any(rid in row_layout for rid in _EC_ROW_IDS)
        ip_segment_map = {}
        if has_bc_ec_rows:
            for n in _iter_profile_ip_nodes(nodes):
                _mc = float(getattr(n, "station_MC", 0) or 0.0)
                _bc = float(getattr(n, "station_BC", _mc) or _mc)
                _ec = float(getattr(n, "station_EC", _mc) or _mc)
                if abs(_bc - _mc) > 1e-9 or abs(_ec - _mc) > 1e-9:
                    ip_segment_map[round(_mc, 6)] = n

        tall_line_mcs = []
        for node in nodes:
            station_mc = float(getattr(node, "station_MC", 0) or 0.0)
            is_special = _is_special_inout_node(node)
            if is_special:
                tall_line_mcs.append(station_mc)
            v_top_val = line_height if is_special else short_line_height

            ip_ref = ip_segment_map.get(round(station_mc, 6)) if has_bc_ec_rows else None
            if ip_ref is not None:
                for seg_x, seg_y0, seg_y1 in _compute_node_vline_segments(
                        ip_ref, row_layout, enabled_row_ids, v_top_val):
                    lines.append(f"pl {fmt(sx(seg_x))},{fmt(seg_y0)} {fmt(sx(seg_x))},{fmt(seg_y1)} ")
            else:
                station_text = fmt(sx(station_mc))
                v_top = fmt(v_top_val)
                lines.append(f"pl {station_text},0 {station_text},{v_top} ")
        lines.append("")

        # ======== 3. ????? ========
        last_mc_scaled = fmt(sx(nodes[-1].station_MC))
        for hy in h_line_y_values:
            lines.append(f"pl {fmt(sx(0))},{fmt(hy)} {last_mc_scaled},{fmt(hy)} ")
        lines.append("")

        # ======== 4. ??/??/???? ========
        for node in valid_nodes:
            if node.bottom_elevation:
                lines.append(f"pl {fmt(sx(node.station_MC))},{fmt(sy(node.bottom_elevation))}")
        lines.append("")
        for node in valid_nodes:
            if node.top_elevation:
                lines.append(f"pl {fmt(sx(node.station_MC))},{fmt(sy(node.top_elevation))}")
        lines.append("")
        for node in valid_nodes:
            if node.water_level:
                lines.append(f"pl {fmt(sx(node.station_MC))},{fmt(sy(node.water_level))}")
        lines.append("")

        # ======== 5. ???? ========
        profile_text_nodes = _build_profile_text_nodes(nodes)
        ip_records = _build_ip_related_row_records(nodes, station_prefix)

        name_mc_pairs = []
        for node in nodes:
            building_name = _get_building_display_name(node)
            if building_name:
                name_mc_pairs.append((building_name, node.station_MC))
        building_segments = []
        for bname, bmc in name_mc_pairs:
            if building_segments and building_segments[-1][0] == bname:
                building_segments[-1][1].append(bmc)
            else:
                building_segments.append((bname, [bmc]))
        building_segments = _merge_segments_across_gates(building_segments)
        mc_to_node = {node.station_MC: node for node in nodes}

        def _should_skip_segment_slope(mc_list):
            for mc in mc_list:
                seg_node = mc_to_node.get(mc)
                if seg_node is None:
                    continue
                if getattr(seg_node, "is_inverted_siphon", False) or getattr(seg_node, "is_pressure_pipe", False):
                    return True
                struct_type = getattr(seg_node, "structure_type", None)
                struct_name = getattr(struct_type, "name", "")
                if struct_name in ("INVERTED_SIPHON", "PRESSURE_PIPE"):
                    return True
            return False

        for rid in enabled_row_ids:
            y_pos = row_layout[rid]["text_y"]
            if rid in ("bottom_elev", "top_elev", "water_elev", "station"):
                for idx, node in enumerate(profile_text_nodes):
                    station_mc = _profile_station_value(node)
                    text_x = sx(station_mc) + first_col_x_offset if idx == 0 else sx(station_mc)
                    if rid == "bottom_elev":
                        text = fmt_elev(node.bottom_elevation)
                    elif rid == "top_elev":
                        text = fmt_elev(node.top_elevation)
                    elif rid == "water_elev":
                        text = fmt_elev(node.water_level)
                    else:
                        text = ProjectSettings.format_station(station_mc, station_prefix)
                    lines.append(f"-text {fmt(text_x)},{fmt(y_pos)} {s_height} {s_rotation} {text} ")
                lines.append("")
                continue

            if rid == "building_name":
                for bname, mc_list in building_segments:
                    if _is_gate_name(bname):
                        mid_mc = mc_list[0]
                    else:
                        seg_start = mc_list[0]
                        seg_end = mc_list[-1]
                        mid_mc = _resolve_segment_mid_mc(seg_start, seg_end, tall_line_mcs)
                    lines.append(f"-text j mc {fmt(sx(mid_mc))},{fmt(y_pos)} {s_height} 0 {bname} ")
                lines.append("")
                continue

            if rid == "slope":
                for bname, mc_list in building_segments:
                    if _is_gate_name(bname):
                        continue
                    seg_start = mc_list[0]
                    seg_end = mc_list[-1]
                    mid_mc = _resolve_segment_mid_mc(seg_start, seg_end, tall_line_mcs)
                    if _should_skip_segment_slope(mc_list):
                        lines.append(f"-text j mc {fmt(sx(mid_mc))},{fmt(y_pos)} {s_height} 0 - ")
                        continue
                    slope_text = _get_segment_slope_text(mc_list, mc_to_node)
                    if not slope_text:
                        continue
                    lines.append(f"-text j mc {fmt(sx(mid_mc))},{fmt(y_pos)} {s_height} 0 {slope_text} ")
                lines.append("")
                continue

            if rid in ip_records:
                for idx, rec in enumerate(ip_records[rid]):
                    text_x = sx(rec["x"]) + first_col_x_offset if idx == 0 else sx(rec["x"])
                    lines.append(f"-text {fmt(text_x)},{fmt(y_pos)} {s_height} {s_rotation} {rec['text']} ")
                lines.append("")
                continue

        # ======== 6. ???? ========
        header_cx = fmt(-40 + 20)
        for rid in enabled_row_ids:
            row_info = row_layout[rid]
            labels = row_info.get("header_lines", [])
            if not labels:
                continue
            if len(labels) == 1:
                center_y = (row_info["bottom"] + row_info["top"]) / 2.0
                lines.append(f"-text j mc {header_cx},{fmt(center_y)} {s_height} 0 {labels[0]} ")
                continue
            line_spacing = text_height * 2.5
            block_h = line_spacing + text_height
            y_bottom_line = row_info["bottom"] + (row_info["height"] - block_h) / 2.0 + text_height / 2.0
            y_top_line = y_bottom_line + line_spacing
            lines.append(f"-text j mc {header_cx},{fmt(y_top_line)} {s_height} 0 {labels[0]} ")
            lines.append(f"-text j mc {header_cx},{fmt(y_bottom_line)} {s_height} 0 {labels[1]} ")
        lines.append("")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        if fluent_question(panel.window(), "完成", f"上纵断面表格已生成（{len(nodes)} 个节点）：{file_path}"):
            os.startfile(file_path)

    except PermissionError:
        fluent_error(panel.window(), "文件被占用", f"无法写入文件，请先关闭该文件：{file_path}")
    except Exception as e:
        import traceback; traceback.print_exc()
        fluent_error(panel.window(), "导出错误", f"生成上纵断面表格失败：{str(e)}")


# ================================================================
# 2. ??bzzh2????
# ================================================================

def extract_bzzh2_data(panel):
    """bzzh2命令提取工具

    从计算结果中提取所有有进出口标识（进/出）的建筑物节点，
    按桩号排序，整理为制表符分隔的TXT文件，供ZDM的bzzh2命令使用。
    """
    if not MODELS_AVAILABLE:
        fluent_info(panel.window(), "不可用", "核心模型未加载")
        return

    nodes = panel.calculated_nodes
    if not nodes:
        fluent_info(panel.window(), "警告", "表格中没有数据，请先导入或输入数据。")
        return

    try:
        proj_settings = panel._build_settings()
        station_prefix = proj_settings.get_station_prefix()
    except Exception:
        station_prefix = ""

    bzzh2_rows = []
    for node in nodes:
        try:
            in_out = getattr(node, 'in_out', None)
            if _in_out_val(in_out) not in ("进", "出"):
                continue
            if getattr(node, 'is_transition', False):
                continue

            station_mc = getattr(node, 'station_MC', 0.0)
            if not isinstance(station_mc, (int, float)):
                station_mc = 0.0
            station_str = ProjectSettings.format_station(station_mc, station_prefix)

            struct_name = ""
            struct_str = _struct_val(node.structure_type)
            if struct_str:
                if "隧洞" in struct_str:
                    struct_name = "隧洞"
                elif "倒虹吸" in struct_str:
                    struct_name = "倒虹吸"
                elif "有压管道" in struct_str:
                    struct_name = "有压管道"
                elif "渡槽" in struct_str:
                    struct_name = "渡槽"
                elif "暗涵" in struct_str:
                    struct_name = "暗涵"
                else:
                    struct_name = struct_str

            in_out_str = "进" if _in_out_val(in_out) == "进" else "出"
            name = getattr(node, 'name', '') or ''
            desc = f"{name}{struct_name}{in_out_str}"
            bzzh2_rows.append((station_str, desc))
        except Exception as node_err:
            import traceback; traceback.print_exc()
            print(f"[bzzh2] 跳过节点（处理异常）: {node_err}")
            continue

    if not bzzh2_rows:
        fluent_info(
            panel.window(), "无可提取数据",
            "未找到有进出口标识的建筑物节点。\n\n"
            "bzzh2命令需要隧洞、倒虹吸、有压管道、渡槽等建筑物的进/出口数据。\n"
            "请确保表格中已有相关数据并完成计算。")
        return

    # 预览对话框
    preview_dlg = QDialog(panel.window())
    preview_dlg.setWindowTitle("预览 — bzzh2命令数据（ZDM用）")
    preview_dlg.setMinimumSize(600, 400)
    preview_dlg.setStyleSheet(DIALOG_STYLE)
    dlg_lay = QVBoxLayout(preview_dlg)

    dlg_lay.addWidget(QLabel(
        f"共 {len(bzzh2_rows)} 条建筑物进出口数据，请确认内容后点击「确认导出」保存为TXT文件。"))

    table = QTableWidget(len(bzzh2_rows), 2)
    table.setHorizontalHeaderLabels(["桩号", "说明"])
    table.horizontalHeader().setStretchLastSection(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(True)
    for i, (s, d) in enumerate(bzzh2_rows):
        table.setItem(i, 0, QTableWidgetItem(s))
        table.setItem(i, 1, QTableWidgetItem(d))
    auto_resize_table(table)
    dlg_lay.addWidget(table)

    btn_lay = QHBoxLayout()
    btn_lay.addStretch()
    btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(preview_dlg.reject)
    btn_ok = PrimaryPushButton("确认导出"); btn_ok.clicked.connect(preview_dlg.accept)
    btn_lay.addWidget(btn_cancel); btn_lay.addWidget(btn_ok)
    dlg_lay.addLayout(btn_lay)

    # 绑定 ESC 关闭 / Enter 确认
    QShortcut(QKeySequence(Qt.Key_Escape), preview_dlg, preview_dlg.reject)
    QShortcut(QKeySequence(Qt.Key_Return), preview_dlg, preview_dlg.accept)

    if preview_dlg.exec() != QDialog.Accepted:
        return

    # 保存文件
    try:
        ch_name = panel.channel_name_edit.text().strip()
        ch_level = panel.channel_level_combo.currentText()
        auto_name = f"{ch_name}{ch_level}_ZDM的bzzh2命令.txt"
    except Exception:
        auto_name = "ZDM的bzzh2命令.txt"

    file_path, _ = QFileDialog.getSaveFileName(
        panel, "保存bzzh2命令数据", auto_name,
        "文本文件 (*.txt);;所有文件 (*.*)")
    if not file_path:
        return

    try:
        with open(file_path, 'w', encoding='gbk', errors='replace') as f:
            for station_str, desc in bzzh2_rows:
                f.write(f"{station_str}\t{desc}\t\n")

        if fluent_question(panel.window(), "提取完成",
                f"bzzh2命令数据提取成功！\n\n"
                f"文件保存路径:\n{file_path}\n\n"
                f"导出数据行数: {len(bzzh2_rows)}\n\n"
                f"请使用ZDM的bzzh2命令完成建筑物进出口上平面图。\n\n"
                f"是否要立即打开该txt文件？"):
            try:
                os.startfile(file_path)
            except AttributeError:
                import subprocess
                subprocess.Popen(['xdg-open', file_path])
            except Exception:
                fluent_info(panel.window(), "打开文件",
                            f"无法自动打开文件，请手动打开:\n\n{file_path}")
    except PermissionError:
        fluent_error(panel.window(), "文件被占用",
                     f"无法写入文件，该文件可能已被其他程序打开：\n\n{file_path}\n\n"
                     f"请先关闭该文件（如记事本、Word等），然后重新操作。")
    except Exception as e:
        import traceback; traceback.print_exc()
        fluent_error(panel.window(), "提取失败",
                     f"bzzh2命令数据提取过程中发生错误:\n\n{str(e)}")


# ================================================================
# 3. 建筑物名称上平面图
# ================================================================

def export_building_name_plan(panel):
    """生成「平行于轴线的建筑物名称上平面图」AutoCAD -TEXT 命令

    对于进出口之间有多个IP点的建筑物，文字放置在最中间两个相邻
    IP点连线段的中点处（垂直偏移），方向角取该中间线段的方向。
    """
    if not MODELS_AVAILABLE:
        fluent_info(panel.window(), "不可用", "核心模型未加载")
        return

    nodes = panel.calculated_nodes
    if not nodes:
        fluent_info(panel.window(), "警告", "表格中没有数据，请先导入或输入数据。")
        return

    try:
        # 按建筑物分组收集所有节点
        building_groups = {}
        building_order = []
        for node in nodes:
            if node.is_transition or getattr(node, 'is_auto_inserted_channel', False):
                continue
            if not node.name:
                continue
            key = (node.name, _struct_val(node.structure_type))
            if key not in building_groups:
                building_groups[key] = []
                building_order.append(key)
            building_groups[key].append(node)

        # 筛选有完整进出口且坐标有效的建筑物
        valid_buildings = []
        for key in building_order:
            group = building_groups[key]
            has_inlet = any(_in_out_val(n.in_out) == "进" for n in group)
            has_outlet = any(_in_out_val(n.in_out) == "出" for n in group)
            if not (has_inlet and has_outlet):
                continue
            coord_nodes = [n for n in group
                           if n.x is not None and n.y is not None and
                           (n.x != 0 or n.y != 0)]
            if len(coord_nodes) >= 2:
                valid_buildings.append((key, group, coord_nodes))

        if not valid_buildings:
            fluent_info(
                panel.window(), "无可提取数据",
                "未找到有效的建筑物进出口数据。\n\n"
                "需要隧洞、倒虹吸、有压管道、渡槽等建筑物同时存在进口和出口，\n"
                "且节点具有有效的X、Y坐标。")
            return

        # 参数设置对话框
        dlg = PlanTextSettingsDialog(panel.window(), panel._plan_text_settings)
        if dlg.exec() != QDialog.Accepted or dlg.result is None:
            return

        panel._plan_text_settings.update(dlg.result)
        offset = dlg.result['offset']
        text_height = dlg.result['text_height']

        # 生成 -TEXT 命令
        text_commands = []
        for key, all_nodes, coord_nodes in valid_buildings:
            N = len(coord_nodes)
            mid_right = N // 2
            mid_left = mid_right - 1

            node_a = coord_nodes[mid_left]
            node_b = coord_nodes[mid_right]
            # 坐标修正：node.x 存储的是北坐标N，node.y 存储的是东坐标E
            # AutoCAD 使用 X,Y 格式，X为东坐标E，Y为北坐标N
            x1, y1 = node_a.y, node_a.x
            x2, y2 = node_b.y, node_b.x

            dx = x2 - x1
            dy = y2 - y1
            if abs(dx) < 1e-10 and abs(dy) < 1e-10:
                continue

            mx = (x1 + x2) / 2
            my = (y1 + y2) / 2
            angle_rad = math.atan2(dy, dx)
            angle_deg = math.degrees(angle_rad)

            text_x = mx - offset * math.sin(angle_rad)
            text_y = my + offset * math.cos(angle_rad)

            inlet_node = next(
                (n for n in all_nodes if _in_out_val(n.in_out) == "进"),
                all_nodes[0])
            struct_name = ""
            struct_str = _struct_val(inlet_node.structure_type)
            if struct_str:
                if "隧洞" in struct_str:
                    struct_name = "隧洞"
                elif "倒虹吸" in struct_str:
                    struct_name = "倒虹吸"
                elif "有压管道" in struct_str:
                    struct_name = "有压管道"
                elif "渡槽" in struct_str:
                    struct_name = "渡槽"
                elif "暗涵" in struct_str:
                    struct_name = "暗涵"
                else:
                    struct_name = struct_str

            building_name = f"{inlet_node.name or ''}{struct_name}"
            cmd = (f"-TEXT J MC {text_x},{text_y} "
                   f"{text_height} {angle_deg} {building_name}")
            text_commands.append((building_name, N, cmd))

        if not text_commands:
            fluent_info(panel.window(), "无有效数据",
                        "没有生成任何 -TEXT 命令，请检查建筑物坐标。")
            return

        # 显示预览
        all_cmds_text = "\n".join(cmd for _, _, cmd in text_commands)

        preview = QDialog(panel.window())
        preview.setWindowTitle(f"建筑物名称上平面图 — {len(text_commands)} 条命令")
        preview.setMinimumSize(700, 400)
        preview.setStyleSheet(DIALOG_STYLE)
        p_lay = QVBoxLayout(preview)

        p_lay.addWidget(QLabel(
            f"共 {len(text_commands)} 个建筑物  |  "
            f"偏移距离: {offset}  |  文字高度: {text_height}"))

        text_widget = QTextEdit()
        text_widget.setReadOnly(True)
        text_widget.setFont(QFont("Consolas", 10))
        html_parts = []
        for i, (name, node_count, cmd) in enumerate(text_commands):
            comment = f"' [{i+1}] {name}（{node_count}个IP点）"
            html_parts.append(f'<span style="color:gray">{comment}</span><br>')
            html_parts.append(f'{cmd}<br><br>')
        text_widget.setHtml('<pre style="font-family:Consolas;font-size:10pt">' +
                            ''.join(html_parts) + '</pre>')
        p_lay.addWidget(text_widget)

        btn_lay = QHBoxLayout()
        status_label = QLabel("")
        status_label.setStyleSheet("color: green;")
        btn_lay.addWidget(status_label)
        btn_lay.addStretch()

        def copy_commands_only():
            QApplication.clipboard().setText(all_cmds_text)
            status_label.setText("✓ 已复制纯命令到剪贴板，可直接粘贴到 AutoCAD")

        def copy_all_content():
            QApplication.clipboard().setText(text_widget.toPlainText())
            status_label.setText("✓ 已复制全部内容到剪贴板（含注释）")

        btn_copy_all = PushButton("复制全部内容")
        btn_copy_all.clicked.connect(copy_all_content)
        btn_copy_cmd = PrimaryPushButton("复制纯命令")
        btn_copy_cmd.clicked.connect(copy_commands_only)
        btn_close = PushButton("关闭")
        btn_close.clicked.connect(preview.close)
        btn_lay.addWidget(btn_copy_all)
        btn_lay.addWidget(btn_copy_cmd)
        btn_lay.addWidget(btn_close)
        p_lay.addLayout(btn_lay)

        preview.exec()

    except Exception as e:
        import traceback; traceback.print_exc()
        fluent_error(panel.window(), "生成失败",
                     f"建筑物名称上平面图生成过程中发生错误:\n\n{str(e)}")


# ================================================================
# 4. IP坐标及弯道参数表
# ================================================================

def _draw_ip_table_on_msp(msp, ox, oy, preview_data,
                          title="IP坐标及弯道参数表", layer="IP_TABLE"):
    """在 modelspace 上绘制IP坐标及弯道参数表。返回 (width, height)。"""
    import ezdxf

    ROW_H = 6.0
    HDR_ROW_H = 6.0
    TITLE_ROW_H = 7.0
    TEXT_H = 2.2
    HDR_TEXT_H = 2.5
    TITLE_TEXT_H = 3.0
    COL_PAD = 3.0

    sub_headers = [
        "IP点", "E（m）", "N（m）",
        "弯前(千米+米)", "弯中(千米+米)", "弯末(千米+米)",
        "转角", "半径", "切线长", "弧长", "底高程(m)",
    ]
    group_headers = [
        (0, 0, "IP点"),
        (1, 2, "坐标值"),
        (3, 5, "桩号"),
        (6, 9, "弯道参数"),
        (10, 10, "底高程(m)"),
    ]
    v_merged = {0, 10}
    ncols = 11
    nrows = len(preview_data)

    _wf = 1.0
    def _tw(text, h):
        if text is None:
            return 0.0
        return sum(h * _wf if ord(c) > 0x7F else h * 0.6 * _wf for c in str(text))

    col_w = [0.0] * ncols
    for ci, hdr in enumerate(sub_headers):
        col_w[ci] = _tw(hdr, HDR_TEXT_H)
    for sc, ec, gtxt in group_headers:
        span = ec - sc + 1
        gw_each = _tw(gtxt, HDR_TEXT_H) / span
        for ci in range(sc, ec + 1):
            col_w[ci] = max(col_w[ci], gw_each)
    for row in preview_data:
        for ci, val in enumerate(row):
            if ci < ncols:
                col_w[ci] = max(col_w[ci], _tw(val, TEXT_H))
    col_w = [w + COL_PAD for w in col_w]

    col_x = [ox]
    for w in col_w:
        col_x.append(col_x[-1] + w)
    total_w = col_x[-1] - col_x[0]
    x_left, x_right = col_x[0], col_x[-1]

    y_title_top = oy
    y_title_bot = y_title_top - TITLE_ROW_H
    y_hdr1_bot = y_title_bot - HDR_ROW_H
    y_hdr2_bot = y_hdr1_bot - HDR_ROW_H
    y_data_top = y_hdr2_bot
    row_y = [y_data_top]
    for _ in range(nrows):
        row_y.append(row_y[-1] - ROW_H)

    dxa = {"layer": layer}

    # === 标题行 ===
    msp.add_line((x_left, y_title_top), (x_right, y_title_top), dxfattribs=dxa)
    msp.add_line((x_left, y_title_bot), (x_right, y_title_bot), dxfattribs=dxa)
    msp.add_line((x_left, y_title_top), (x_left, y_title_bot), dxfattribs=dxa)
    msp.add_line((x_right, y_title_top), (x_right, y_title_bot), dxfattribs=dxa)
    msp.add_text(
        title,
        dxfattribs={"layer": layer, "height": TITLE_TEXT_H,
                    "width": 0.7, "style": "Standard"}
    ).set_placement(
        (x_left + total_w / 2, (y_title_top + y_title_bot) / 2),
        align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER,
    )

    # === 表头区边框 ===
    msp.add_line((x_left, y_hdr2_bot), (x_right, y_hdr2_bot), dxfattribs=dxa)
    msp.add_line((x_left, y_title_bot), (x_left, y_hdr2_bot), dxfattribs=dxa)
    msp.add_line((x_right, y_title_bot), (x_right, y_hdr2_bot), dxfattribs=dxa)

    for ci in range(ncols):
        if ci not in v_merged:
            msp.add_line((col_x[ci], y_hdr1_bot), (col_x[ci + 1], y_hdr1_bot),
                         dxfattribs=dxa)

    drawn_x = set()
    for sc, ec, _ in group_headers:
        for bx in (col_x[sc], col_x[ec + 1]):
            if bx not in drawn_x:
                msp.add_line((bx, y_title_bot), (bx, y_hdr2_bot), dxfattribs=dxa)
                drawn_x.add(bx)
        if sc != ec:
            for ci in range(sc + 1, ec + 1):
                msp.add_line((col_x[ci], y_hdr1_bot), (col_x[ci], y_hdr2_bot),
                             dxfattribs=dxa)

    for sc, ec, text in group_headers:
        cx = (col_x[sc] + col_x[ec + 1]) / 2
        cy = ((y_title_bot + y_hdr2_bot) / 2 if sc in v_merged
              else (y_title_bot + y_hdr1_bot) / 2)
        msp.add_text(
            text,
            dxfattribs={"layer": layer, "height": HDR_TEXT_H,
                        "width": 0.7, "style": "Standard"}
        ).set_placement((cx, cy), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    for ci, hdr in enumerate(sub_headers):
        if ci in v_merged:
            continue
        cx = (col_x[ci] + col_x[ci + 1]) / 2
        cy = (y_hdr1_bot + y_hdr2_bot) / 2
        msp.add_text(
            hdr,
            dxfattribs={"layer": layer, "height": HDR_TEXT_H,
                        "width": 0.7, "style": "Standard"}
        ).set_placement((cx, cy), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    # === 数据区 ===
    msp.add_line((x_left, y_data_top), (x_right, y_data_top), dxfattribs=dxa)
    if nrows > 0:
        msp.add_line((x_left, row_y[-1]), (x_right, row_y[-1]), dxfattribs=dxa)
    for ri in range(1, nrows):
        msp.add_line((x_left, row_y[ri]), (x_right, row_y[ri]), dxfattribs=dxa)

    y_bottom = row_y[-1] if nrows > 0 else y_data_top
    for x in col_x:
        msp.add_line((x, y_data_top), (x, y_bottom), dxfattribs=dxa)

    for ri, row_vals in enumerate(preview_data):
        for ci, val in enumerate(row_vals):
            if val is None or val == "":
                continue
            cx = (col_x[ci] + col_x[ci + 1]) / 2
            cy = (row_y[ri] + row_y[ri + 1]) / 2
            msp.add_text(
                str(val),
                dxfattribs={"layer": layer, "height": TEXT_H,
                            "width": 0.7, "style": "Standard"}
            ).set_placement((cx, cy), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    total_h = y_title_top - (row_y[-1] if nrows > 0 else y_data_top)
    return total_w, total_h


def _write_ip_table_dxf(file_path, preview_data, title="IP坐标及弯道参数表"):
    """将IP坐标及弯道参数表写入独立DXF文件。"""
    import ezdxf
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    _setup_dxf_style(doc)
    _draw_ip_table_on_msp(msp, 0.0, 0.0, preview_data, title, "IP_TABLE")
    doc.saveas(file_path)


def export_ip_plan_table(panel):
    """导出IP坐标及弯道参数表DXF/Excel文件（含合并表头、桩号格式化）"""
    if not MODELS_AVAILABLE:
        fluent_info(panel.window(), "不可用", "核心模型未加载")
        return

    nodes = panel.calculated_nodes
    if not nodes:
        fluent_info(panel.window(), "警告", "没有数据可导出，请先执行计算")
        return

    try:
        import openpyxl
        from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    except ImportError:
        fluent_info(panel.window(), "缺少依赖",
                    "需要安装 openpyxl: pip install openpyxl")
        return

    try:
        try:
            proj_settings = panel._build_settings()
            station_prefix = proj_settings.get_station_prefix()
        except Exception:
            station_prefix = ""

        def _safe_float(val, default=0.0):
            if val is None:
                return default
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        def _format_ip_name(node):
            try:
                if _in_out_val(node.in_out) in ("进", "出"):
                    struct_abbr = ""
                    struct_str = _struct_val(node.structure_type)
                    if struct_str:
                        if "隧洞" in struct_str: struct_abbr = "隧"
                        elif "倒虹吸" in struct_str: struct_abbr = "倒"
                        elif "有压管道" in struct_str: struct_abbr = "管"
                        elif "渡槽" in struct_str: struct_abbr = "渡"
                        elif "暗涵" in struct_str: struct_abbr = "暗"
                    in_out_str = "进" if _in_out_val(node.in_out) == "进" else "出"
                    return f"{node.name}{struct_abbr}{in_out_str}"
            except Exception:
                pass
            return f"{station_prefix}IP{getattr(node, 'ip_number', 0)}"

        def _format_station(value):
            return ProjectSettings.format_station(_safe_float(value), station_prefix)

        # 过滤节点
        real_nodes = [
            n for n in nodes
            if not getattr(n, 'is_transition', False)
            and not getattr(n, 'is_auto_inserted_channel', False)
        ]

        if not real_nodes:
            fluent_info(panel.window(), "警告", "没有有效的IP点数据可导出")
            return

        # 构建预览数据
        preview_headers = [
            "IP点", "E（m）", "N（m）",
            "弯前(千米+米)", "弯中(千米+米)", "弯末(千米+米)",
            "转角", "半径", "切线长", "弧长", "底高程\nm"
        ]
        preview_data = []
        for idx, node in enumerate(real_nodes):
            try:
                row = [
                    _format_ip_name(node),
                    f"{_safe_float(node.x):.6f}",
                    f"{_safe_float(node.y):.6f}",
                    _format_station(node.station_BC),
                    _format_station(node.station_MC),
                    _format_station(node.station_EC),
                    f"{_safe_float(node.turn_angle):.3f}",
                    f"{_safe_float(node.turn_radius):.3f}",
                    f"{_safe_float(node.tangent_length):.3f}",
                    f"{_safe_float(node.arc_length):.3f}",
                    f"{_safe_float(node.bottom_elevation):.3f}" if _safe_float(node.bottom_elevation) != 0 else "-",
                ]
                preview_data.append(row)
            except Exception as row_err:
                print(f"[警告] 第{idx}行数据格式化失败: {row_err}")
                import traceback; traceback.print_exc()
                preview_data.append([
                    f"IP{getattr(node, 'ip_number', '?')}",
                    "0.000000", "0.000000",
                    "0+000.000", "0+000.000", "0+000.000",
                    "0.000", "0.000", "0.000", "0.000", "-",
                ])

        # 预览对话框
        preview_dlg = QDialog(panel.window())
        preview_dlg.setWindowTitle("预览 — IP坐标及弯道参数表")
        preview_dlg.setMinimumSize(950, 450)
        preview_dlg.setStyleSheet(DIALOG_STYLE)
        dlg_lay = QVBoxLayout(preview_dlg)

        dlg_lay.addWidget(QLabel(
            f"共 {len(preview_data)} 条IP点数据，请确认内容后点击「确认导出」保存为DXF或Excel文件。"))

        table = QTableWidget(len(preview_data), len(preview_headers))
        table.setHorizontalHeaderLabels(preview_headers)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        for r, row_data in enumerate(preview_data):
            for c, val in enumerate(row_data):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(r, c, item)
        auto_resize_table(table)
        dlg_lay.addWidget(table)

        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_cancel = PushButton("取消"); btn_cancel.clicked.connect(preview_dlg.reject)
        btn_ok = PrimaryPushButton("确认导出"); btn_ok.clicked.connect(preview_dlg.accept)
        btn_lay.addWidget(btn_cancel); btn_lay.addWidget(btn_ok)
        dlg_lay.addLayout(btn_lay)

        # 绑定 ESC 关闭 / Enter 确认
        QShortcut(QKeySequence(Qt.Key_Escape), preview_dlg, preview_dlg.reject)
        QShortcut(QKeySequence(Qt.Key_Return), preview_dlg, preview_dlg.accept)

        if preview_dlg.exec() != QDialog.Accepted:
            return

        # 保存
        try:
            ch_name = panel.channel_name_edit.text().strip()
            ch_level = panel.channel_level_combo.currentText()
            auto_name = f"{ch_name}{ch_level}_IP坐标及弯道参数表.dxf"
        except Exception:
            auto_name = "IP坐标及弯道参数表.dxf"

        file_path, _ = QFileDialog.getSaveFileName(
            panel, "保存IP坐标及弯道参数表", auto_name,
            "DXF文件 (*.dxf);;Excel文件 (*.xlsx);;所有文件 (*.*)")
        if not file_path:
            return

        # DXF 导出（紧凑排版、自适应列宽、无底色）
        if file_path.lower().endswith('.dxf'):
            _write_ip_table_dxf(file_path, preview_data)
            if fluent_question(panel.window(), "导出完成",
                    f"IP坐标及弯道参数表DXF导出成功！\n\n"
                    f"文件保存路径:\n{file_path}\n\n"
                    f"导出IP点数量: {len(real_nodes)}\n\n"
                    f"是否要立即打开该文件？"):
                try:
                    os.startfile(file_path)
                except Exception:
                    pass
            return

        # openpyxl 写入
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "IP点上平面图"

        thin_border = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin'))
        header_font = Font(name='Microsoft YaHei', size=10, bold=True)
        data_font = Font(name='Microsoft YaHei', size=10)
        center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
        left_align = Alignment(horizontal='left', vertical='center')
        header_fill = PatternFill(start_color='D9E1F2', end_color='D9E1F2', fill_type='solid')

        ws.cell(row=1, column=1, value="IP点")
        ws.cell(row=1, column=2, value="坐标值")
        ws.cell(row=1, column=4, value="桩号")
        ws.cell(row=1, column=7, value="弯道参数")
        ws.cell(row=1, column=11, value="底高程\nm")
        ws.cell(row=2, column=2, value="E（m）")
        ws.cell(row=2, column=3, value="N（m）")
        ws.cell(row=2, column=4, value="弯前(千米+米)")
        ws.cell(row=2, column=5, value="弯中(千米+米)")
        ws.cell(row=2, column=6, value="弯末(千米+米)")
        ws.cell(row=2, column=7, value="转角")
        ws.cell(row=2, column=8, value="半径")
        ws.cell(row=2, column=9, value="切线长")
        ws.cell(row=2, column=10, value="弧长")

        ws.merge_cells('A1:A2')
        ws.merge_cells('B1:C1')
        ws.merge_cells('D1:F1')
        ws.merge_cells('G1:J1')
        ws.merge_cells('K1:K2')

        for row in range(1, 3):
            for col in range(1, 12):
                cell = ws.cell(row=row, column=col)
                cell.font = header_font
                cell.alignment = center_align
                cell.border = thin_border
                cell.fill = header_fill

        for row_idx, node in enumerate(real_nodes, start=3):
            ws.cell(row=row_idx, column=1, value=_format_ip_name(node))
            cell_b = ws.cell(row=row_idx, column=2, value=_safe_float(node.x))
            cell_b.number_format = '0.000000'
            cell_c = ws.cell(row=row_idx, column=3, value=_safe_float(node.y))
            cell_c.number_format = '0.000000'
            ws.cell(row=row_idx, column=4, value=_format_station(node.station_BC))
            ws.cell(row=row_idx, column=5, value=_format_station(node.station_MC))
            ws.cell(row=row_idx, column=6, value=_format_station(node.station_EC))
            cell_g = ws.cell(row=row_idx, column=7,
                             value=round(_safe_float(node.turn_angle), 3))
            cell_g.number_format = '0.000'
            cell_h = ws.cell(row=row_idx, column=8,
                             value=round(_safe_float(node.turn_radius), 3))
            cell_h.number_format = '0.000'
            cell_i = ws.cell(row=row_idx, column=9,
                             value=round(_safe_float(node.tangent_length), 3))
            cell_i.number_format = '0.000'
            cell_j = ws.cell(row=row_idx, column=10,
                             value=round(_safe_float(node.arc_length), 3))
            cell_j.number_format = '0.000'
            _be_val = _safe_float(node.bottom_elevation)
            cell_k = ws.cell(row=row_idx, column=11,
                             value=round(_be_val, 3) if _be_val != 0 else "-")
            if _be_val != 0:
                cell_k.number_format = '0.000'

            for col in range(1, 12):
                cell = ws.cell(row=row_idx, column=col)
                cell.font = data_font
                cell.border = thin_border
                if col == 1:
                    cell.alignment = left_align
                else:
                    cell.alignment = Alignment(horizontal='center', vertical='center')

        # 自适应列宽（根据实际内容计算，避免出现 ###）
        for col_idx in range(1, 12):
            col_letter = chr(64 + col_idx)  # A=1, B=2, ...
            max_len = 0
            for row_idx2 in range(1, ws.max_row + 1):
                cell_val = ws.cell(row=row_idx2, column=col_idx).value
                if cell_val is not None:
                    s = str(cell_val)
                    # CJK字符算2个宽度单位
                    char_w = sum(2 if ord(c) > 0x7F else 1 for c in s)
                    max_len = max(max_len, char_w)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 8)

        wb.save(file_path)
        wb.close()

        if fluent_question(panel.window(), "导出完成",
                f"IP坐标及弯道参数表导出成功！\n\n"
                f"文件保存路径:\n{file_path}\n\n"
                f"导出IP点数量: {len(real_nodes)}\n\n"
                f"是否要立即打开该文件？"):
            try:
                os.startfile(file_path)
            except Exception:
                pass

    except PermissionError:
        fluent_error(panel.window(), "文件被占用",
                     f"无法写入文件，该文件可能已被其他程序打开：\n\n{file_path}\n\n"
                     f"请先关闭该文件（如Excel等），然后重新操作。")
    except Exception as e:
        import traceback
        traceback.print_exc()
        fluent_error(panel.window(), "导出失败",
                     f"IP坐标及弯道参数表导出失败，请检查以下可能的原因：\n\n"
                     f"1. 目标文件是否被其他程序占用（如AutoCAD、Excel等）\n"
                     f"2. 文件保存路径是否有写入权限\n"
                     f"3. 数据是否完整（坐标、桩号等）\n\n"
                     f"错误信息：{str(e)}\n\n"
                     f"如仍无法解决，请将以上信息反馈给技术支持。")


# ================================================================
# 6. 合并导出全部DXF（横向分区布局）
# ================================================================

def _draw_section_summary_on_msp(
    panel,
    msp,
    nodes,
    proj_settings,
    pressurized_params,
    below_y,
    summary_layer,
):
    """Draw section summary tables onto modelspace.

    Returns:
        tuple[float, float, int]: (summary_width, summary_height, drawn_table_count)
    """
    from calc_渠系计算算法内核.生成断面汇总表 import (
        _extract_segment_defaults_from_nodes,
        _segment_name,
        _dxf_draw_table,
        _dxf_auto_col_widths,
        _DXF_TABLE_GAP,
        _DXF_BUILDERS,
        compute_rect_channel,
        compute_trapezoid_channel,
        compute_tunnel,
        compute_tunnel_circular,
        compute_tunnel_horseshoe,
        compute_aqueduct_u,
        compute_aqueduct_rect,
        compute_rect_culvert,
        compute_circular_pipe,
        compute_siphon,
        compute_pressure_pipe,
        _default_segments_rect_channel,
        _default_segments_trap_channel,
        _default_segments_tunnel_arch,
        _default_segments_tunnel_circular,
        _default_segments_tunnel_horseshoe,
        _default_segments_aqueduct_u,
        _default_segments_aqueduct_rect,
        _default_segments_rect_culvert,
        _default_segments_circular_pipe,
    )

    node_defaults, flow_qs = _extract_segment_defaults_from_nodes(nodes)

    counts = []
    if proj_settings and getattr(proj_settings, "design_flows", None):
        flows = [q for q in proj_settings.design_flows if isinstance(q, (int, float)) and q > 0]
        if flows:
            counts.append(len(flows))
    if flow_qs:
        counts.append(max(flow_qs.keys()))
    if node_defaults:
        for data in node_defaults.values():
            if data:
                counts.append(max(data.keys()))
    seg_count = max(1, max(counts)) if counts else 7

    fallback_qs = [2.0, 1.3, 0.8, 0.5, 0.4, 0.2, 0.5]
    if proj_settings and getattr(proj_settings, "design_flows", None):
        flows = [q for q in proj_settings.design_flows if isinstance(q, (int, float)) and q > 0]
        if flows:
            qs = [flows[i] if i < len(flows) else flows[-1] for i in range(seg_count)]
        else:
            qs = fallback_qs[:seg_count]
    elif flow_qs:
        qs = []
        for i in range(1, seg_count + 1):
            q = flow_qs.get(i, 0.0)
            qs.append(q if q > 0 else (fallback_qs[i - 1] if i - 1 < len(fallback_qs) else fallback_qs[-1]))
    else:
        qs = list(fallback_qs[:seg_count]) + [fallback_qs[-1]] * max(0, seg_count - len(fallback_qs))

    has_source = bool(nodes) and any(node_defaults.values())

    def _make_segs(default_fn, overrides_by_idx=None):
        if has_source and overrides_by_idx is not None:
            if not overrides_by_idx:
                return []
            pool = default_fn()
            segs = []
            for idx in sorted(overrides_by_idx.keys()):
                base = dict(pool[0]) if pool else {}
                base["name"] = _segment_name(idx)
                base.update(overrides_by_idx[idx])
                if 0 < idx <= len(qs):
                    base["Q"] = qs[idx - 1]
                segs.append(base)
            return segs

        segs = default_fn()
        if len(segs) < seg_count:
            last = segs[-1] if segs else {}
            for idx in range(len(segs) + 1, seg_count + 1):
                new = dict(last)
                new["name"] = _segment_name(idx)
                segs.append(new)
        segs = segs[:seg_count]
        for i, seg in enumerate(segs):
            if overrides_by_idx and (i + 1) in overrides_by_idx:
                seg.update(overrides_by_idx[i + 1])
            if i < len(qs):
                seg["Q"] = qs[i]
        return segs

    rc = _make_segs(_default_segments_rect_channel, node_defaults.get("rect_channel"))
    tr = _make_segs(_default_segments_trap_channel, node_defaults.get("trap_channel"))
    ta = _make_segs(_default_segments_tunnel_arch, node_defaults.get("tunnel_arch"))
    tc = _make_segs(_default_segments_tunnel_circular, node_defaults.get("tunnel_circular"))
    th = _make_segs(_default_segments_tunnel_horseshoe, node_defaults.get("tunnel_horseshoe"))
    au = _make_segs(_default_segments_aqueduct_u, node_defaults.get("aqueduct_u"))
    ar = _make_segs(_default_segments_aqueduct_rect, node_defaults.get("aqueduct_rect"))
    rv = _make_segs(_default_segments_rect_culvert, node_defaults.get("rect_culvert"))
    cp = _make_segs(_default_segments_circular_pipe, node_defaults.get("circular_channel"))
    sp = _build_pressurized_segments(
        qs=qs,
        overrides_by_idx=node_defaults.get("siphon", {}),
        params=pressurized_params.get("siphon", []),
        has_source_data=has_source,
        segment_name_fn=_segment_name,
    )
    pp = _build_pressurized_segments(
        qs=qs,
        overrides_by_idx=node_defaults.get("pressure_pipe", {}),
        params=pressurized_params.get("pressure_pipe", []),
        has_source_data=has_source,
        segment_name_fn=_segment_name,
    )

    _struct_t = getattr(panel, "_custom_struct_thickness", None)
    _rock_lining = getattr(panel, "_custom_rock_lining", None)
    if _struct_t:
        _st_rc = _struct_t.get("rect_channel", {})
        for seg in rc:
            if "wall_t" in _st_rc:
                seg["wall_t"] = _st_rc["wall_t"]
            if "tie_rod" in _st_rc:
                seg["tie_rod"] = _st_rc["tie_rod"]
        _st_tr = _struct_t.get("trap_channel", {})
        for seg in tr:
            if "wall_t" in _st_tr:
                seg["wall_t"] = _st_tr["wall_t"]
            if "tie_rod" in _st_tr:
                seg["tie_rod"] = _st_tr["tie_rod"]
        _st_au = _struct_t.get("aqueduct_u", {})
        for seg in au:
            if "wall_t" in _st_au:
                seg["wall_t"] = _st_au["wall_t"]
        _st_ar = _struct_t.get("aqueduct_rect", {})
        for seg in ar:
            if "wall_t" in _st_ar:
                seg["wall_t"] = _st_ar["wall_t"]
        _st_rv = _struct_t.get("rect_culvert", {})
        for seg in rv:
            for key in ("t0", "t1", "t2"):
                if key in _st_rv:
                    seg[key] = _st_rv[key]

    _tu = getattr(panel, "_custom_tunnel_unified", {})
    _tu_arch = _tu.get("tunnel_arch", False)
    _tu_circ = _tu.get("tunnel_circular", False)
    _tu_horse = _tu.get("tunnel_horseshoe", False)

    d_rc = compute_rect_channel(rc) if rc else []
    d_tr = compute_trapezoid_channel(tr) if tr else []
    d_ta, _ = compute_tunnel(ta, _rock_lining, unified=_tu_arch) if ta else ([], {})
    d_tc, _ = compute_tunnel_circular(tc, _rock_lining, unified=_tu_circ) if tc else ([], {})
    d_th, d_th_info = compute_tunnel_horseshoe(th, rock_lining=_rock_lining, unified=_tu_horse) if th else ([], {})
    d_au = compute_aqueduct_u(au) if au else []
    d_ar = compute_aqueduct_rect(ar) if ar else []
    d_rv = compute_rect_culvert(rv) if rv else []
    d_cp = compute_circular_pipe(cp) if cp else []
    d_sp = compute_siphon(sp) if sp else []
    d_pp = compute_pressure_pipe(pp) if pp else []

    data_map = {
        "rect_channel": d_rc,
        "trap_channel": d_tr,
        "tunnel_arch": d_ta,
        "tunnel_circular": d_tc,
        "tunnel_horseshoe": d_th,
        "aqueduct_u": d_au,
        "aqueduct_rect": d_ar,
        "rect_culvert": d_rv,
        "circular_channel": d_cp,
        "siphon": d_sp,
        "pressure_pipe": d_pp,
    }
    table_order = [
        "rect_channel",
        "trap_channel",
        "tunnel_arch",
        "tunnel_circular",
        "tunnel_horseshoe",
        "aqueduct_u",
        "aqueduct_rect",
        "rect_culvert",
        "circular_channel",
        "siphon",
        "pressure_pipe",
    ]

    cur_y = below_y
    max_table_w = 0.0
    summary_h = 0.0
    drawn_table_count = 0
    for key in table_order:
        data_rows = data_map.get(key)
        builder = _DXF_BUILDERS.get(key)
        if data_rows and builder:
            title_t, headers, col_widths, rows, merge = builder(data_rows)
            if key == "tunnel_horseshoe" and d_th_info:
                st_name = d_th_info.get("section_type_name")
                if st_name:
                    title_t = f"{st_name}隧洞断面尺寸及水力要素表"
            table_h = _dxf_draw_table(
                msp,
                0.0,
                cur_y,
                title_t,
                headers,
                col_widths,
                rows,
                merge_groups=merge,
                layer=summary_layer,
            )
            auto_w = _dxf_auto_col_widths(headers, rows)
            col_count = len(headers)
            actual_w = sum(
                max(col_widths[col_idx], auto_w[col_idx]) if col_idx < len(col_widths) else auto_w[col_idx]
                for col_idx in range(col_count)
            )
            max_table_w = max(max_table_w, actual_w)
            summary_h += table_h + _DXF_TABLE_GAP
            cur_y -= (table_h + _DXF_TABLE_GAP)
            drawn_table_count += 1

    return max_table_w, summary_h, drawn_table_count


def export_combined_dxf(panel):
    """将纵断面表格、断面汇总表、IP坐标表合并导出到一个DXF文件。

    布局：纵断面表格在上方（全宽），下方左侧放断面汇总表，右侧放IP表。
    """
    import ezdxf

    if not MODELS_AVAILABLE:
        fluent_info(panel.window(), "不可用", "核心模型未加载")
        return

    nodes = panel.calculated_nodes
    if not nodes:
        fluent_info(panel.window(), "警告", "没有数据可导出，请先执行计算")
        return

    valid_nodes = [n for n in nodes if n.bottom_elevation or n.top_elevation or n.water_level]
    if not valid_nodes:
        fluent_info(panel.window(), "警告", "没有可用的高程数据，请先执行计算。")
        return

    # ---- 1. 纵断面参数设置 ----
    dlg = TextExportSettingsDialog(panel.window(), panel._text_export_settings)
    if dlg.exec() != QDialog.Accepted or dlg.result is None:
        return
    panel._text_export_settings.update(dlg.result)
    profile_settings = dlg.result

    # ---- 2. 获取项目设置 ----
    try:
        proj_settings = panel._build_settings()
        station_prefix = proj_settings.get_station_prefix()
    except Exception:
        proj_settings = None
        station_prefix = ""

    # ---- 3. 断面汇总表参数设置（构造参数、有压流参数等）----
    try:
        ch_name_for_dlg = panel.channel_name_edit.text().strip()
        ch_level_for_dlg = panel.channel_level_combo.currentText()
        auto_name_dlg = f"{ch_name_for_dlg}{ch_level_for_dlg}_断面汇总表.xlsx"
    except Exception:
        auto_name_dlg = "断面汇总表.xlsx"
    summary_dlg = SectionSummaryDialog(
        panel.window(), nodes, proj_settings, auto_name_dlg,
        panel=panel, config_only=True,
    )
    if summary_dlg.exec() != QDialog.Accepted:
        return
    cached_pressurized = getattr(panel, "_custom_pressurized_pipe_params", {}) or {}
    pressurized_params = {
        "siphon": cached_pressurized.get("siphon", []),
        "pressure_pipe": cached_pressurized.get("pressure_pipe", []),
    }

    # ---- 4. 选择保存路径 ----
    try:
        ch_name = panel.channel_name_edit.text().strip()
        ch_level = panel.channel_level_combo.currentText()
        auto_name = f"{ch_name}{ch_level}_全部表格.dxf"
    except Exception:
        auto_name = "全部表格.dxf"

    file_path, _ = QFileDialog.getSaveFileName(
        panel, "保存合并DXF（纵断面+断面汇总+IP表）", auto_name,
        "DXF 文件 (*.dxf);;所有文件 (*.*)")
    if not file_path:
        return
    if not file_path.lower().endswith('.dxf'):
        file_path += '.dxf'

    try:
        # ---- 创建 DXF 文档 ----
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        _setup_dxf_style(doc)

        # 三个组件使用独立图层（带前缀），便于在CAD中分别控制显示
        _PROF_PREFIX = "纵断面_"
        _SUMM_LAYER = "断面汇总表"
        _IP_LAYER = "IP坐标表"

        _ensure_profile_layers(doc, layer_prefix=_PROF_PREFIX)
        if _SUMM_LAYER not in doc.layers:
            doc.layers.new(_SUMM_LAYER, dxfattribs={"color": 7})   # 白色
        if _IP_LAYER not in doc.layers:
            doc.layers.new(_IP_LAYER, dxfattribs={"color": 7})     # 白色

        GAP = 20.0  # 各区域间距

        # ======== A. 纵断面表格（顶部，原点(0,0)） ========
        prof_w, prof_h = _draw_profile_on_msp(
            msp, nodes, valid_nodes, profile_settings, station_prefix,
            layer_prefix=_PROF_PREFIX)

        # 下方区域起始Y（纵断面底部再向下留间距）
        below_y = -GAP

        try:
            summary_w, summary_h, drawn_table_count = _draw_section_summary_on_msp(
                panel=panel,
                msp=msp,
                nodes=nodes,
                proj_settings=proj_settings,
                pressurized_params=pressurized_params,
                below_y=below_y,
                summary_layer=_SUMM_LAYER,
            )
        except Exception as e:
            import traceback; traceback.print_exc()
            fluent_error(
                panel.window(),
                "导出失败",
                f"断面汇总表生成失败，已取消“导出全部DXF”。\n{e}",
            )
            return

        if drawn_table_count <= 0:
            fluent_error(
                panel.window(),
                "导出失败",
                "断面汇总表无可导出内容，已取消“导出全部DXF”。",
            )
            return

        try:
            ip_preview, ip_nodes = _compute_ip_preview_data(nodes, station_prefix)
        except Exception as e:
            import traceback; traceback.print_exc()
            fluent_error(
                panel.window(),
                "导出失败",
                f"IP坐标及弯道参数表生成失败，已取消“导出全部DXF”。\n{e}",
            )
            return

        if not ip_preview:
            fluent_error(
                panel.window(),
                "导出失败",
                "IP坐标及弯道参数表无可导出内容，已取消“导出全部DXF”。",
            )
            return

        try:
            ip_ox = max(summary_w + GAP, 200.0)
            ip_oy = below_y
            _draw_ip_table_on_msp(
                msp,
                ip_ox,
                ip_oy,
                ip_preview,
                "IP坐标及弯道参数表",
                _IP_LAYER,
            )
        except Exception as e:
            import traceback; traceback.print_exc()
            fluent_error(
                panel.window(),
                "导出失败",
                f"IP坐标及弯道参数表绘制失败，已取消“导出全部DXF”。\n{e}",
            )
            return

        doc.saveas(file_path)
        if fluent_question(
            panel.window(),
            "导出完成",
            f"合并DXF已生成：\n{file_path}\n\n"
            f"包含：纵断面表格 + 断面汇总表 + IP坐标表\n"
            f"断面汇总表: {drawn_table_count} 张可用表格，IP表: {len(ip_preview)} 行数据\n"
            f"是否立即打开该文件？",
        ):
            try:
                os.startfile(file_path)
            except Exception:
                pass
        return

    except PermissionError:
        fluent_error(panel.window(), "文件被占用",
                     f"无法写入文件：\n{file_path}\n\n请先关闭该文件后重试。")
    except Exception as e:
        import traceback; traceback.print_exc()
        fluent_error(panel.window(), "导出失败",
                     f"合并DXF导出失败:\n{str(e)}")


# ================================================================
# 5. 断面汇总表
# ================================================================

class SectionSummaryDialog(QDialog):
    """断面尺寸及水力要素汇总表生成对话框（纯 PySide6 版）"""

    def __init__(self, parent, nodes, proj_settings, auto_name="", panel=None,
                 config_only=False):
        super().__init__(parent)
        self._config_only = config_only
        if config_only:
            self.setWindowTitle("断面尺寸及水力要素汇总表 — 参数设置")
        else:
            self.setWindowTitle("断面尺寸及水力要素汇总表 — 生成器")
        self.setMinimumSize(520, 560)
        self.resize(640, 780)
        self.setStyleSheet(DIALOG_STYLE)

        self._nodes = nodes
        self._proj_settings = proj_settings
        self._auto_name = auto_name
        self._panel = panel
        self._cached_pressurized = {}
        if panel is not None:
            self._cached_pressurized = getattr(panel, "_custom_pressurized_pipe_params", {}) or {}

        # 导入计算模块
        from calc_渠系计算算法内核.生成断面汇总表 import (
            _extract_segment_defaults_from_nodes,
            _segment_name,
            SIPHON_MATERIALS,
            ROCK_CLASSES,
            ROCK_LINING_DEFAULT,
            generate_excel,
            generate_dxf,
            _default_segments_rect_channel,
            _default_segments_trap_channel,
            _default_segments_tunnel_arch,
            _default_segments_tunnel_circular,
            _default_segments_tunnel_horseshoe,
            _default_segments_aqueduct_u,
            _default_segments_aqueduct_rect,
            _default_segments_rect_culvert,
            _default_segments_circular_pipe,
        )
        self._ROCK_CLASSES = ROCK_CLASSES
        self._ROCK_LINING_DEFAULT = ROCK_LINING_DEFAULT
        self._generate_excel = generate_excel
        self._generate_dxf = generate_dxf
        self._segment_name = _segment_name
        self._SIPHON_MATERIALS = SIPHON_MATERIALS
        self._default_fns = {
            'rect_channel': _default_segments_rect_channel,
            'trap_channel': _default_segments_trap_channel,
            'tunnel_arch': _default_segments_tunnel_arch,
            'tunnel_circular': _default_segments_tunnel_circular,
            'tunnel_horseshoe': _default_segments_tunnel_horseshoe,
            'aqueduct_u': _default_segments_aqueduct_u,
            'aqueduct_rect': _default_segments_aqueduct_rect,
            'rect_culvert': _default_segments_rect_culvert,
            'circular_pipe': _default_segments_circular_pipe,
        }

        node_defaults, flow_qs = _extract_segment_defaults_from_nodes(nodes)
        self._node_defaults = node_defaults
        self._flow_qs = flow_qs

        # 提取倒虹吸分组（按名称，支持不同材质和管径）
        self._siphon_groups = self._extract_siphon_groups()

        # 确定流量段数
        self._segment_count = self._get_segment_count()
        default_qs = self._build_default_qs()

        self._build_ui(default_qs)

    # ---- 流量段数计算 ----
    def _get_segment_count(self):
        counts = []
        ps = self._proj_settings
        if ps is not None and getattr(ps, "design_flows", None):
            flows = [q for q in ps.design_flows if isinstance(q, (int, float)) and q > 0]
            if flows:
                counts.append(len(flows))
        if self._flow_qs:
            counts.append(max(self._flow_qs.keys()))
        if self._node_defaults:
            for data in self._node_defaults.values():
                if data:
                    counts.append(max(data.keys()))
        return max(1, max(counts)) if counts else 7

    def _build_default_qs(self):
        fallback = [2.0, 1.3, 0.8, 0.5, 0.4, 0.2, 0.5]
        sc = self._segment_count
        ps = self._proj_settings
        if ps is not None and getattr(ps, "design_flows", None):
            flows = [q for q in ps.design_flows if isinstance(q, (int, float)) and q > 0]
            if flows:
                return [flows[i] if i < len(flows) else flows[-1] for i in range(sc)]
        if self._flow_qs:
            out = []
            for i in range(1, sc + 1):
                q = self._flow_qs.get(i, 0.0)
                out.append(q if q > 0 else (fallback[i - 1] if i - 1 < len(fallback) else fallback[-1]))
            return out
        if sc <= len(fallback):
            return list(fallback[:sc])
        return list(fallback) + [fallback[-1]] * (sc - len(fallback))

    def _extract_siphon_groups(self):
        return _extract_named_pressurized_groups(self._nodes, "siphon")
    
    def _extract_pressure_pipe_groups(self):
        return _extract_named_pressurized_groups(self._nodes, "pressure_pipe")

    def showEvent(self, event):
        """确保对话框不超出屏幕可见区域"""
        super().showEvent(event)
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            geo = self.frameGeometry()
            # 如果窗口高度超出屏幕，缩小到屏幕高度
            if geo.height() > avail.height():
                self.resize(self.width(), avail.height() - 20)
                geo = self.frameGeometry()
            # 如果顶部超出屏幕，向下移动
            if geo.top() < avail.top():
                geo.moveTop(avail.top())
            # 如果底部超出屏幕，向上移动
            if geo.bottom() > avail.bottom():
                geo.moveBottom(avail.bottom())
            # 如果左侧超出屏幕
            if geo.left() < avail.left():
                geo.moveLeft(avail.left())
            self.move(geo.topLeft())

    # ---- UI 构建 ----
    def _build_ui(self, default_qs):
        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)

        # 用 QScrollArea 包裹全部内容，防止内容超高时顶部被截断
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setSpacing(10)

        # 提示文字
        desc = QLabel("本功能将自动计算并生成多种建筑物断面水力要素汇总表（Excel），\n"
                      "可直接用于 AutoCAD 制表。")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size:13px; color:#333;")
        lay.addWidget(desc)

        # ---- 流量段参数 ----
        q_group = QGroupBox("流量段设计流量 Q (m³/s)")
        q_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:12px;}")
        q_lay = QVBoxLayout(q_group)

        q_grid = QGridLayout()
        q_grid.setSpacing(4)

        self._q_edits = []
        for i in range(self._segment_count):
            lbl = QLabel(self._segment_name(i + 1))
            lbl.setStyleSheet("font-size:12px;")
            edit = LineEdit()
            edit.setFixedWidth(100)
            edit.setText(str(default_qs[i] if i < len(default_qs) else default_qs[-1]))
            q_grid.addWidget(lbl, i, 0)
            q_grid.addWidget(edit, i, 1)
            self._q_edits.append(edit)

        q_grid.setColumnStretch(2, 1)
        q_lay.addLayout(q_grid)
        lay.addWidget(q_group)

        # ---- 倒虹吸管道参数（按名称分组） ----
        siphon_group = QGroupBox("倒虹吸管道参数")
        siphon_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:12px;}")
        siphon_lay = QVBoxLayout(siphon_group)

        # 构建倒虹吸分组列表；无数据时提供一个默认行
        if self._siphon_groups:
            siphon_items = _merge_pressurized_param_defaults(
                self._siphon_groups,
                self._cached_pressurized.get("siphon", []),
            )
        else:
            siphon_items = [("倒虹吸", "球墨铸铁管", 1500)]

        # 表头
        hdr_grid = QGridLayout()
        hdr_grid.setSpacing(6)
        for ci, txt in enumerate(['倒虹吸名称', '管道材质', 'DN (mm)']):
            lbl = QLabel(txt)
            lbl.setStyleSheet("font-size:11px; color:#555; font-weight:bold;")
            hdr_grid.addWidget(lbl, 0, ci)
        hdr_grid.setColumnStretch(0, 2)
        hdr_grid.setColumnStretch(1, 3)
        hdr_grid.setColumnStretch(2, 2)
        siphon_lay.addLayout(hdr_grid)

        self._siphon_rows = []  # [(name, mat_combo, dn_edit), ...]
        sp_grid = QGridLayout()
        sp_grid.setSpacing(4)
        for ri, (sp_name, sp_material, sp_dn) in enumerate(siphon_items):
            # 名称标签
            name_lbl = QLabel(sp_name)
            name_lbl.setStyleSheet("font-size:12px;")
            sp_grid.addWidget(name_lbl, ri, 0)

            # 材质下拉
            mat_combo = QComboBox()
            mat_combo.addItems(list(self._SIPHON_MATERIALS.keys()))
            mat_combo.setCurrentText(
                sp_material if sp_material in self._SIPHON_MATERIALS else "球墨铸铁管"
            )
            mat_combo.setFixedWidth(160)
            sp_grid.addWidget(mat_combo, ri, 1)

            # DN 输入框
            dn_edit = LineEdit()
            dn_edit.setFixedWidth(100)
            dn_val = _normalize_dn_mm(sp_dn, 1500)
            dn_edit.setText(str(dn_val))
            sp_grid.addWidget(dn_edit, ri, 2)

            self._siphon_rows.append((sp_name, mat_combo, dn_edit))

        sp_grid.setColumnStretch(0, 2)
        sp_grid.setColumnStretch(1, 3)
        sp_grid.setColumnStretch(2, 2)
        siphon_lay.addLayout(sp_grid)

        dn_note = QLabel("（DN 从倒虹吸计算结果自动导入，也可手动修改）")
        dn_note.setStyleSheet("font-size:11px; color:#666;")
        siphon_lay.addWidget(dn_note)
        lay.addWidget(siphon_group)

        # ---- 有压管道参数（与倒虹吸类似） ----
        pressure_pipe_group = QGroupBox("有压管道参数")
        pressure_pipe_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:12px;}")
        pp_lay = QVBoxLayout(pressure_pipe_group)

        # 提取有压管道分组
        self._pressure_pipe_groups = self._extract_pressure_pipe_groups()
        if self._pressure_pipe_groups:
            pp_items = _merge_pressurized_param_defaults(
                self._pressure_pipe_groups,
                self._cached_pressurized.get("pressure_pipe", []),
            )
        else:
            pp_items = [("有压管道", "球墨铸铁管", 1500)]

        # 表头
        pp_hdr_grid = QGridLayout()
        pp_hdr_grid.setSpacing(6)
        for ci, txt in enumerate(['有压管道名称', '管道材质', 'DN (mm)']):
            lbl = QLabel(txt)
            lbl.setStyleSheet("font-size:11px; color:#555; font-weight:bold;")
            pp_hdr_grid.addWidget(lbl, 0, ci)
        pp_hdr_grid.setColumnStretch(0, 2)
        pp_hdr_grid.setColumnStretch(1, 3)
        pp_hdr_grid.setColumnStretch(2, 2)
        pp_lay.addLayout(pp_hdr_grid)

        self._pressure_pipe_rows = []  # [(name, mat_combo, dn_edit), ...]
        pp_grid = QGridLayout()
        pp_grid.setSpacing(4)
        for ri, (pp_name, pp_material, pp_dn) in enumerate(pp_items):
            # 名称标签
            name_lbl = QLabel(pp_name)
            name_lbl.setStyleSheet("font-size:12px;")
            pp_grid.addWidget(name_lbl, ri, 0)

            # 材质下拉
            mat_combo = QComboBox()
            mat_combo.addItems(list(self._SIPHON_MATERIALS.keys()))
            mat_combo.setCurrentText(
                pp_material if pp_material in self._SIPHON_MATERIALS else "球墨铸铁管"
            )
            mat_combo.setFixedWidth(160)
            pp_grid.addWidget(mat_combo, ri, 1)

            # DN 输入框
            dn_edit = LineEdit()
            dn_edit.setFixedWidth(100)
            dn_val = _normalize_dn_mm(pp_dn, 1500)
            dn_edit.setText(str(dn_val))
            pp_grid.addWidget(dn_edit, ri, 2)

            self._pressure_pipe_rows.append((pp_name, mat_combo, dn_edit))

        pp_grid.setColumnStretch(0, 2)
        pp_grid.setColumnStretch(1, 3)
        pp_grid.setColumnStretch(2, 2)
        pp_lay.addLayout(pp_grid)

        pp_note = QLabel("（DN 从有压管道计算结果自动导入，也可手动修改）")
        pp_note.setStyleSheet("font-size:11px; color:#666;")
        pp_lay.addWidget(pp_note)
        lay.addWidget(pressure_pipe_group)

        # ---- 构造参数设置（Tab页签） ----
        from PySide6.QtWidgets import QTabWidget
        struct_group = QGroupBox("构造参数设置（壁厚/衬砌厚度）")
        struct_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:12px;}")
        struct_lay = QVBoxLayout(struct_group)

        struct_tabs = QTabWidget()
        struct_tabs.setStyleSheet("QTabWidget{font-size:11px;} QTabBar::tab{min-width:70px;}")

        # ---- Tab 1: 明渠类 ----
        tab_channel = QWidget()
        tc_lay = QVBoxLayout(tab_channel)
        tc_lay.setSpacing(6)

        tc_grid = QGridLayout()
        tc_grid.setSpacing(4)
        tc_grid.addWidget(QLabel(""), 0, 0)  # 空占位
        for ci, txt in enumerate(['壁厚 t (m)', '拉杆尺寸 (m)']):
            lbl = QLabel(txt)
            lbl.setStyleSheet("font-size:11px; color:#555; font-weight:bold;")
            tc_grid.addWidget(lbl, 0, ci + 1)

        def _tie_rod_pair(default_w=0.2, default_h=0.2):
            """创建拉杆尺寸 [宽] × [高] 组合控件，返回 (container, w_edit, h_edit)。"""
            container = QWidget()
            h_lay = QHBoxLayout(container)
            h_lay.setContentsMargins(0, 0, 0, 0)
            h_lay.setSpacing(3)
            w_lbl = QLabel("宽"); w_lbl.setStyleSheet("font-size:10px; color:#424242;")
            w_edit = LineEdit(); w_edit.setFixedWidth(55)
            w_edit.setText(str(default_w)); w_edit.setPlaceholderText(str(default_w))
            x_lbl = QLabel("×"); x_lbl.setFixedWidth(12)
            x_lbl.setStyleSheet("font-size:12px;")
            h_lbl = QLabel("高"); h_lbl.setStyleSheet("font-size:10px; color:#424242;")
            h_edit = LineEdit(); h_edit.setFixedWidth(55)
            h_edit.setText(str(default_h)); h_edit.setPlaceholderText(str(default_h))
            h_lay.addWidget(w_lbl)
            h_lay.addWidget(w_edit)
            h_lay.addWidget(x_lbl)
            h_lay.addWidget(h_lbl)
            h_lay.addWidget(h_edit)
            h_lay.addStretch()
            return container, w_edit, h_edit

        # 矩形明渠
        tc_grid.addWidget(QLabel("矩形明渠"), 1, 0)
        self._rect_ch_wall_t = LineEdit(); self._rect_ch_wall_t.setFixedWidth(90)
        self._rect_ch_wall_t.setText("0.3"); self._rect_ch_wall_t.setPlaceholderText("0.3")
        tc_grid.addWidget(self._rect_ch_wall_t, 1, 1)
        rc_tr_container, self._rect_ch_tie_w, self._rect_ch_tie_h = _tie_rod_pair()
        tc_grid.addWidget(rc_tr_container, 1, 2)

        # 梯形明渠
        tc_grid.addWidget(QLabel("梯形明渠"), 2, 0)
        self._trap_ch_wall_t = LineEdit(); self._trap_ch_wall_t.setFixedWidth(90)
        self._trap_ch_wall_t.setText("0.3"); self._trap_ch_wall_t.setPlaceholderText("0.3")
        tc_grid.addWidget(self._trap_ch_wall_t, 2, 1)
        tp_tr_container, self._trap_ch_tie_w, self._trap_ch_tie_h = _tie_rod_pair()
        tc_grid.addWidget(tp_tr_container, 2, 2)

        tc_grid.setColumnStretch(0, 1)
        tc_grid.setColumnStretch(1, 2)
        tc_grid.setColumnStretch(2, 3)
        tc_lay.addLayout(tc_grid)
        tc_lay.addStretch()
        struct_tabs.addTab(tab_channel, "明渠类")

        # ---- Tab 2: 渡槽类 ----
        tab_aqueduct = QWidget()
        ta_lay = QVBoxLayout(tab_aqueduct)
        ta_lay.setSpacing(6)

        ta_grid = QGridLayout()
        ta_grid.setSpacing(4)
        ta_grid.addWidget(QLabel(""), 0, 0)
        lbl_t = QLabel("壁厚 t (m)")
        lbl_t.setStyleSheet("font-size:11px; color:#555; font-weight:bold;")
        ta_grid.addWidget(lbl_t, 0, 1)

        # U形渡槽
        ta_grid.addWidget(QLabel("U形渡槽"), 1, 0)
        self._aq_u_wall_t = LineEdit(); self._aq_u_wall_t.setFixedWidth(90)
        self._aq_u_wall_t.setText("0.35"); self._aq_u_wall_t.setPlaceholderText("0.35")
        ta_grid.addWidget(self._aq_u_wall_t, 1, 1)

        # 矩形渡槽
        ta_grid.addWidget(QLabel("矩形渡槽"), 2, 0)
        self._aq_rect_wall_t = LineEdit(); self._aq_rect_wall_t.setFixedWidth(90)
        self._aq_rect_wall_t.setText("0.35"); self._aq_rect_wall_t.setPlaceholderText("0.35")
        ta_grid.addWidget(self._aq_rect_wall_t, 2, 1)

        ta_grid.setColumnStretch(0, 1)
        ta_grid.setColumnStretch(1, 2)
        ta_lay.addLayout(ta_grid)
        ta_lay.addStretch()
        struct_tabs.addTab(tab_aqueduct, "渡槽类")

        # ---- Tab 3: 暗涵 ----
        tab_culvert = QWidget()
        tv_lay = QVBoxLayout(tab_culvert)
        tv_lay.setSpacing(6)

        tv_grid = QGridLayout()
        tv_grid.setSpacing(4)
        tv_grid.addWidget(QLabel(""), 0, 0)
        for ci, txt in enumerate(['底板厚 t\u2080 (m)', '边墙厚 t\u2081 (m)', '顶板厚 t\u2082 (m)']):
            lbl = QLabel(txt)
            lbl.setStyleSheet("font-size:11px; color:#555; font-weight:bold;")
            tv_grid.addWidget(lbl, 0, ci + 1)

        tv_grid.addWidget(QLabel("矩形暗涵"), 1, 0)
        self._culvert_t0 = LineEdit(); self._culvert_t0.setFixedWidth(90)
        self._culvert_t0.setText("0.4"); self._culvert_t0.setPlaceholderText("0.4")
        tv_grid.addWidget(self._culvert_t0, 1, 1)
        self._culvert_t1 = LineEdit(); self._culvert_t1.setFixedWidth(90)
        self._culvert_t1.setText("0.4"); self._culvert_t1.setPlaceholderText("0.4")
        tv_grid.addWidget(self._culvert_t1, 1, 2)
        self._culvert_t2 = LineEdit(); self._culvert_t2.setFixedWidth(90)
        self._culvert_t2.setText("0.4"); self._culvert_t2.setPlaceholderText("0.4")
        tv_grid.addWidget(self._culvert_t2, 1, 3)

        tv_grid.setColumnStretch(0, 1)
        tv_grid.setColumnStretch(1, 2)
        tv_grid.setColumnStretch(2, 2)
        tv_grid.setColumnStretch(3, 2)
        tv_lay.addLayout(tv_grid)
        tv_lay.addStretch()
        struct_tabs.addTab(tab_culvert, "暗涵")

        # ---- Tab 4: 隧洞 ----
        tab_tunnel = QWidget()
        tt_lay = QVBoxLayout(tab_tunnel)
        tt_lay.setSpacing(6)

        tt_desc = QLabel("4种隧洞类型共用此设置（圆拱直墙型/圆形/马蹄形Ⅰ型/Ⅱ型）")
        tt_desc.setStyleSheet("font-size:11px; color:#666;")
        tt_lay.addWidget(tt_desc)

        tt_grid = QGridLayout()
        tt_grid.setSpacing(4)
        tt_grid.addWidget(QLabel(""), 0, 0)
        for ci, txt in enumerate(['底板厚 t\u2080 (m)', '边墙/顶拱/衬砌厚 t (m)']):
            lbl = QLabel(txt)
            lbl.setStyleSheet("font-size:11px; color:#555; font-weight:bold;")
            tt_grid.addWidget(lbl, 0, ci + 1)

        self._lining_edits = {}  # {rock_class: (t0_edit, t_edit)}
        for ri, rc in enumerate(self._ROCK_CLASSES):
            tt_grid.addWidget(QLabel(rc), ri + 1, 0)
            defaults = self._ROCK_LINING_DEFAULT[rc]
            t0_edit = LineEdit(); t0_edit.setFixedWidth(90)
            t0_edit.setText(str(defaults['t0'])); t0_edit.setPlaceholderText(str(defaults['t0']))
            tt_grid.addWidget(t0_edit, ri + 1, 1)
            t_edit = LineEdit(); t_edit.setFixedWidth(90)
            t_edit.setText(str(defaults['t'])); t_edit.setPlaceholderText(str(defaults['t']))
            tt_grid.addWidget(t_edit, ri + 1, 2)
            self._lining_edits[rc] = (t0_edit, t_edit)

        tt_grid.setColumnStretch(0, 1)
        tt_grid.setColumnStretch(1, 3)
        tt_grid.setColumnStretch(2, 3)
        tt_lay.addLayout(tt_grid)

        # ---- 隧洞断面设计方式 ----
        from PySide6.QtWidgets import QRadioButton, QButtonGroup, QHBoxLayout as _QHBox
        _tt_mode_row = QWidget()
        _tt_mode_hlay = _QHBox(_tt_mode_row)
        _tt_mode_hlay.setContentsMargins(0, 0, 0, 0)
        _tt_mode_hlay.setSpacing(4)
        tt_mode_lbl = QLabel("断面设计方式:")
        tt_mode_lbl.setStyleSheet("font-size:11px; color:#555; font-weight:bold; margin-top:6px;")
        _tt_mode_hlay.addWidget(tt_mode_lbl)
        _info_icon = QLabel("ⓘ")
        _info_icon.setStyleSheet(
            "font-size:13px; color:#1a73e8; font-weight:bold; margin-top:6px; cursor:pointer;"
        )
        _info_icon.setCursor(Qt.PointingHandCursor)
        _dialog_self = self
        _info_icon.mousePressEvent = lambda e: PopupTeachingTip.create(
            target=_info_icon,
            icon=InfoBarIcon.INFORMATION,
            title='断面设计方式',
            content='统一断面：按最大流量段设计统一断面尺寸，其余各流量段仅推求水深；\n'
                    '独立断面：每个流量段独立计算各自的断面尺寸。',
            isClosable=False,
            tailPosition=TeachingTipTailPosition.BOTTOM,
            duration=-1,
            parent=_dialog_self,
        )
        _tt_mode_hlay.addWidget(_info_icon)
        _tt_mode_hlay.addStretch()
        tt_lay.addWidget(_tt_mode_row)

        self._tunnel_mode_groups = {}  # {key: QButtonGroup}
        _tunnel_types = [
            ("tunnel_arch",      "圆拱直墙型"),
            ("tunnel_circular",  "圆形"),
            ("tunnel_horseshoe", "马蹄形（Ⅰ/Ⅱ型）"),
        ]
        tm_grid = QGridLayout()
        tm_grid.setSpacing(2)
        for ri, (tkey, tname) in enumerate(_tunnel_types):
            name_lbl = QLabel(tname)
            name_lbl.setStyleSheet("font-size:11px;")
            name_lbl.setFixedWidth(110)
            tm_grid.addWidget(name_lbl, ri, 0)
            rb_unified = QRadioButton("统一断面")
            rb_indep  = QRadioButton("独立断面")
            rb_unified.setStyleSheet("font-size:11px;")
            rb_indep.setStyleSheet("font-size:11px;")
            rb_indep.setChecked(True)
            bg = QButtonGroup(self)
            bg.addButton(rb_unified, 0)
            bg.addButton(rb_indep, 1)
            tm_grid.addWidget(rb_unified, ri, 1)
            tm_grid.addWidget(rb_indep, ri, 2)
            self._tunnel_mode_groups[tkey] = bg
        tt_lay.addLayout(tm_grid)

        tt_lay.addStretch()
        struct_tabs.addTab(tab_tunnel, "隧洞")

        struct_tabs.setFixedHeight(260)
        struct_lay.addWidget(struct_tabs)

        struct_note = QLabel('（不输入则使用默认值，修改后同时影响"生成断面汇总表"和"导出全部DXF"）')
        struct_note.setStyleSheet("font-size:11px; color:#666;")
        struct_lay.addWidget(struct_note)
        lay.addWidget(struct_group)

        # ---- 说明 ----
        note_group = QGroupBox("其他参数说明")
        note_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:12px;}")
        note_lay = QVBoxLayout(note_group)
        note_lbl = QLabel(
            "• 各类构造参数可在上方按类型自定义\n"
            '• 隧洞断面设计方式可在"隧洞"选项卡中按类型分别设置\n'
            "• 圆管涵、倒虹吸无需设置壁厚")
        note_lbl.setWordWrap(True)
        note_lbl.setStyleSheet("font-size:11px; color:#555;")
        note_lay.addWidget(note_lbl)
        lay.addWidget(note_group)

        # ---- 导出格式选择 ----
        from PySide6.QtWidgets import QRadioButton, QButtonGroup
        fmt_group = QGroupBox("导出格式")
        fmt_group.setStyleSheet("QGroupBox{font-weight:bold;font-size:12px;}")
        fmt_lay = QHBoxLayout(fmt_group)
        self._radio_excel = QRadioButton("Excel (.xlsx)  — 多Sheet + 汇总Sheet")
        self._radio_dxf = QRadioButton("DXF (.dxf)  — 可直接导入AutoCAD")
        self._radio_excel.setStyleSheet("font-size:11px;")
        self._radio_dxf.setStyleSheet("font-size:11px;")
        self._radio_excel.setChecked(True)
        self._fmt_btn_group = QButtonGroup(self)
        self._fmt_btn_group.addButton(self._radio_excel, 0)
        self._fmt_btn_group.addButton(self._radio_dxf, 1)
        fmt_lay.addWidget(self._radio_excel)
        fmt_lay.addWidget(self._radio_dxf)
        fmt_lay.addStretch()
        lay.addWidget(fmt_group)
        if self._config_only:
            fmt_group.setVisible(False)

        scroll.setWidget(content)
        outer_lay.addWidget(scroll, 1)

        # ---- 按钮栏（固定在底部，不随滚动） ----
        btn_lay = QHBoxLayout()
        btn_lay.setContentsMargins(10, 6, 10, 6)
        btn_lay.addStretch()
        btn_cancel = PushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_text = "确认参数" if self._config_only else "生成汇总表"
        btn_generate = PrimaryPushButton(btn_text)
        btn_generate.clicked.connect(self._on_generate)
        btn_lay.addWidget(btn_cancel)
        btn_lay.addWidget(btn_generate)
        outer_lay.addLayout(btn_lay)

    # ---- 读取构造参数 ----
    def _read_float(self, edit, default):
        """安全读取 LineEdit 的浮点值，空或非法返回默认值。"""
        t = edit.text().strip()
        if not t:
            return default
        try:
            return float(t)
        except ValueError:
            return default

    def _read_rock_lining(self):
        """从输入框读取用户自定义的围岩衬砌厚度。"""
        rock_lining = {}
        for rc in self._ROCK_CLASSES:
            t0_edit, t_edit = self._lining_edits[rc]
            defaults = self._ROCK_LINING_DEFAULT[rc]
            rock_lining[rc] = {
                't0': self._read_float(t0_edit, defaults['t0']),
                't':  self._read_float(t_edit,  defaults['t']),
            }
        return rock_lining

    def _read_tie_rod(self, w_edit, h_edit):
        """从拉杆宽/高输入框读取并组合为 'd1×d2' 字符串。"""
        w = self._read_float(w_edit, 0.2)
        h = self._read_float(h_edit, 0.2)
        return f"{w}×{h}"

    def _read_struct_thickness(self):
        """读取所有结构类型的用户自定义厚度参数，返回 dict。"""
        return {
            'rect_channel': {
                'wall_t':  self._read_float(self._rect_ch_wall_t, 0.3),
                'tie_rod': self._read_tie_rod(self._rect_ch_tie_w, self._rect_ch_tie_h),
            },
            'trap_channel': {
                'wall_t':  self._read_float(self._trap_ch_wall_t, 0.3),
                'tie_rod': self._read_tie_rod(self._trap_ch_tie_w, self._trap_ch_tie_h),
            },
            'aqueduct_u': {
                'wall_t': self._read_float(self._aq_u_wall_t, 0.35),
            },
            'aqueduct_rect': {
                'wall_t': self._read_float(self._aq_rect_wall_t, 0.35),
            },
            'rect_culvert': {
                't0': self._read_float(self._culvert_t0, 0.4),
                't1': self._read_float(self._culvert_t1, 0.4),
                't2': self._read_float(self._culvert_t2, 0.4),
            },
            'rock_lining': self._read_rock_lining(),
        }

    # ---- 生成 ----
    def _on_generate(self):
        from calc_渠系计算算法内核.生成断面汇总表 import (
            _default_segments_rect_channel,
            _default_segments_trap_channel,
            _default_segments_tunnel_arch,
            _default_segments_tunnel_circular,
            _default_segments_tunnel_horseshoe,
            _default_segments_aqueduct_u,
            _default_segments_aqueduct_rect,
            _default_segments_rect_culvert,
            _default_segments_circular_pipe,
            _segment_name,
        )

        # 读取 Q 值
        try:
            qs = [float(e.text()) for e in self._q_edits]
        except ValueError:
            fluent_error(self, "输入错误", "流量值必须为数字")
            return

        # 读取每个倒虹吸的材质和 DN
        siphon_params = []  # [(name, material, dn), ...]
        for sp_name, mat_combo, dn_edit in self._siphon_rows:
            dn = _parse_positive_dn(dn_edit.text())
            if dn is None:
                fluent_error(self, "输入错误", f"{sp_name} 的 DN 必须为正整数")
                return
            siphon_params.append((sp_name, mat_combo.currentText(), dn))
        
        # 读取每个有压管道的材质和 DN（与倒虹吸类似）
        pressure_pipe_params = []  # [(name, material, dn), ...]
        for pp_name, mat_combo, dn_edit in self._pressure_pipe_rows:
            dn = _parse_positive_dn(dn_edit.text())
            if dn is None:
                fluent_error(self, "输入错误", f"{pp_name} 的 DN 必须为正整数")
                return
            pressure_pipe_params.append((pp_name, mat_combo.currentText(), dn))

        # config_only 模式：只读取并缓存参数，不生成文件
        if self._config_only:
            struct_t = self._read_struct_thickness()
            rock_lining = struct_t['rock_lining']
            tunnel_unified = {}
            for tkey, bg in self._tunnel_mode_groups.items():
                tunnel_unified[tkey] = (bg.checkedId() == 0)
            if self._panel is not None:
                self._panel._custom_rock_lining = rock_lining
                self._panel._custom_struct_thickness = struct_t
                self._panel._custom_tunnel_unified = tunnel_unified
                self._panel._custom_pressurized_pipe_params = {
                    "siphon": list(siphon_params),
                    "pressure_pipe": list(pressure_pipe_params),
                }
            self.accept()
            return

        segment_count = self._segment_count
        node_defaults = self._node_defaults

        # 判断导出格式
        export_dxf = self._radio_dxf.isChecked()
        if export_dxf:
            ext = ".dxf"
            filter_str = "DXF 文件 (*.dxf);;所有文件 (*.*)"
            auto_name = self._auto_name.replace('.xlsx', '.dxf') if self._auto_name else ""
        else:
            ext = ".xlsx"
            filter_str = "Excel 文件 (*.xlsx);;所有文件 (*.*)"
            auto_name = self._auto_name

        # 选择保存路径
        fp, _ = QFileDialog.getSaveFileName(
            self, "保存断面汇总表", auto_name, filter_str)
        if not fp:
            return
        if not fp.lower().endswith(ext):
            fp += ext

        # 构建各表参数
        has_source_data = bool(self._nodes) and any(node_defaults.values())

        def _make_segs(default_fn, overrides_by_idx=None):
            # 有源数据时，只生成有实际节点数据的流量段
            if has_source_data and overrides_by_idx is not None:
                if not overrides_by_idx:
                    return []
                defaults_pool = default_fn()
                segs = []
                for idx in sorted(overrides_by_idx.keys()):
                    # 用默认段作为基础模板
                    base = dict(defaults_pool[0]) if defaults_pool else {}
                    base["name"] = _segment_name(idx)
                    base.update(overrides_by_idx[idx])
                    if 0 < idx <= len(qs):
                        base["Q"] = qs[idx - 1]
                    segs.append(base)
                return segs
            # 无源数据时（独立运行），用默认值生成所有段
            segs = default_fn()
            if len(segs) < segment_count:
                last = segs[-1] if segs else {}
                for idx in range(len(segs) + 1, segment_count + 1):
                    new_seg = dict(last)
                    new_seg["name"] = _segment_name(idx)
                    segs.append(new_seg)
            segs = segs[:segment_count]
            for i, seg in enumerate(segs):
                if overrides_by_idx and (i + 1) in overrides_by_idx:
                    seg.update(overrides_by_idx[i + 1])
                if i < len(qs):
                    seg["Q"] = qs[i]
            return segs

        rc_segs = _make_segs(_default_segments_rect_channel, node_defaults.get("rect_channel"))
        tr_segs = _make_segs(_default_segments_trap_channel, node_defaults.get("trap_channel"))
        tn_arch_segs = _make_segs(_default_segments_tunnel_arch, node_defaults.get("tunnel_arch"))
        tn_circ_segs = _make_segs(_default_segments_tunnel_circular, node_defaults.get("tunnel_circular"))
        tn_horse_segs = _make_segs(_default_segments_tunnel_horseshoe, node_defaults.get("tunnel_horseshoe"))
        aq_u_segs = _make_segs(_default_segments_aqueduct_u, node_defaults.get("aqueduct_u"))
        aq_rect_segs = _make_segs(_default_segments_aqueduct_rect, node_defaults.get("aqueduct_rect"))
        rv_segs = _make_segs(_default_segments_rect_culvert, node_defaults.get("rect_culvert"))
        cp_segs = _make_segs(_default_segments_circular_pipe, node_defaults.get("circular_channel"))

        if not has_source_data:
            for segs_list in [rc_segs, tr_segs, tn_arch_segs, tn_circ_segs, tn_horse_segs,
                              aq_u_segs, aq_rect_segs, rv_segs, cp_segs]:
                for i, seg in enumerate(segs_list):
                    seg["name"] = _segment_name(i + 1)

        sp_overrides = node_defaults.get("siphon", {})
        sp_segs = _build_pressurized_segments(
            qs=qs,
            overrides_by_idx=sp_overrides,
            params=siphon_params,
            has_source_data=has_source_data,
            segment_name_fn=_segment_name,
        )

        # 按结果决定表格类型
        _table_order = None
        if has_source_data:
            _table_order = []
            if node_defaults.get("rect_channel"):
                _table_order.append("rect_channel")
            if node_defaults.get("trap_channel"):
                _table_order.append("trap_channel")
            if node_defaults.get("tunnel_arch"):
                _table_order.append("tunnel_arch")
            if node_defaults.get("tunnel_circular"):
                _table_order.append("tunnel_circular")
            if node_defaults.get("tunnel_horseshoe"):
                _table_order.append("tunnel_horseshoe")
            if node_defaults.get("aqueduct_u"):
                _table_order.append("aqueduct_u")
            if node_defaults.get("aqueduct_rect"):
                _table_order.append("aqueduct_rect")
            if node_defaults.get("rect_culvert"):
                _table_order.append("rect_culvert")
            if node_defaults.get("circular_channel"):
                _table_order.append("circular_channel")
            if node_defaults.get("siphon"):
                _table_order.append("siphon")
            if node_defaults.get("pressure_pipe"):
                _table_order.append("pressure_pipe")
            if not _table_order:
                _table_order = None

        # 读取所有用户自定义的构造参数（壁厚/衬砌厚度）
        struct_t = self._read_struct_thickness()
        rock_lining = struct_t['rock_lining']

        # 将壁厚/衬砌参数注入各类型 segments
        for seg in rc_segs:
            seg['wall_t'] = struct_t['rect_channel']['wall_t']
            seg['tie_rod'] = struct_t['rect_channel']['tie_rod']
        for seg in tr_segs:
            seg['wall_t'] = struct_t['trap_channel']['wall_t']
            seg['tie_rod'] = struct_t['trap_channel']['tie_rod']
        for seg in aq_u_segs:
            seg['wall_t'] = struct_t['aqueduct_u']['wall_t']
        for seg in aq_rect_segs:
            seg['wall_t'] = struct_t['aqueduct_rect']['wall_t']
        for seg in rv_segs:
            seg['t0'] = struct_t['rect_culvert']['t0']
            seg['t1'] = struct_t['rect_culvert']['t1']
            seg['t2'] = struct_t['rect_culvert']['t2']

        # 读取隧洞断面设计方式
        tunnel_unified = {}
        for tkey, bg in self._tunnel_mode_groups.items():
            tunnel_unified[tkey] = (bg.checkedId() == 0)  # 0=统一, 1=独立

        # 存储到 panel，供"导出全部DXF"复用
        if self._panel is not None:
            self._panel._custom_rock_lining = rock_lining
            self._panel._custom_struct_thickness = struct_t
            self._panel._custom_tunnel_unified = tunnel_unified
            self._panel._custom_pressurized_pipe_params = {
                "siphon": list(siphon_params),
                "pressure_pipe": list(pressure_pipe_params),
            }

        # 构建有压管道 segments（与倒虹吸类似）
        pp_overrides = node_defaults.get("pressure_pipe", {})
        pp_segs = _build_pressurized_segments(
            qs=qs,
            overrides_by_idx=pp_overrides,
            params=pressure_pipe_params,
            has_source_data=has_source_data,
            segment_name_fn=_segment_name,
        )

        gen_kwargs = dict(
            filepath=fp,
            rect_channel_segs=rc_segs,
            trap_channel_segs=tr_segs,
            tunnel_arch_segs=tn_arch_segs,
            tunnel_circular_segs=tn_circ_segs,
            tunnel_horseshoe_segs=tn_horse_segs,
            aqueduct_u_segs=aq_u_segs,
            aqueduct_rect_segs=aq_rect_segs,
            rect_culvert_segs=rv_segs,
            circular_pipe_segs=cp_segs,
            siphon_segs=sp_segs,
            siphon_material=siphon_params[0][1] if siphon_params else "球墨铸铁管",
            pressure_pipe_segs=pp_segs,
            pressure_pipe_material=pressure_pipe_params[0][1] if pressure_pipe_params else "球墨铸铁管",
            rock_lining=rock_lining,
            table_order=_table_order,
            tunnel_unified_arch=tunnel_unified.get("tunnel_arch", False),
            tunnel_unified_circular=tunnel_unified.get("tunnel_circular", False),
            tunnel_unified_horseshoe=tunnel_unified.get("tunnel_horseshoe", False),
        )

        try:
            self.setCursor(Qt.WaitCursor)
            QApplication.processEvents()
            if export_dxf:
                self._generate_dxf(**gen_kwargs)
            else:
                self._generate_excel(**gen_kwargs)
            self.unsetCursor()
            mat_summary = '、'.join(f"{n}({m})" for n, m, _ in siphon_params)
            pp_mat_summary = '、'.join(f"{n}({m})" for n, m, _ in pressure_pipe_params) if pressure_pipe_params else ""
            fmt_name = "DXF" if export_dxf else "Excel"
            extra = "" if export_dxf else "\n表格数量以计算结果为准，另含 1 个汇总 Sheet。"
            msg_parts = [f"断面汇总表已生成（{fmt_name}）：\n{fp}\n{extra}"]
            if mat_summary:
                msg_parts.append(f"倒虹吸管道材质：{mat_summary}")
            if pp_mat_summary:
                msg_parts.append(f"有压管道材质：{pp_mat_summary}")
            msg_parts.append("\n是否立即打开该文件？")
            if fluent_question(self, "完成", "\n".join(msg_parts), yes_text="打开", no_text="关闭"):
                try:
                    os.startfile(fp)
                except Exception:
                    pass
            self.accept()
        except PermissionError:
            self.unsetCursor()
            fluent_error(self, "文件被占用",
                         f"无法写入文件，该文件可能已被其他程序打开：\n\n{fp}\n\n"
                         f"请先关闭该文件，然后重新操作。")
        except Exception as e:
            self.unsetCursor()
            import traceback; traceback.print_exc()
            fluent_error(self, "生成失败", f"错误: {e}")


def open_section_summary_table(panel):
    """打开断面汇总表生成器（纯 PySide6 对话框）"""
    nodes = panel.calculated_nodes
    if not nodes:
        fluent_info(panel.window(), "警告", "没有数据可用，请先执行计算。")
        return

    try:
        proj_settings = panel._build_settings()
    except Exception:
        proj_settings = panel._settings

    try:
        try:
            ch_name = panel.channel_name_edit.text().strip()
            ch_level = panel.channel_level_combo.currentText()
            auto_name = f"{ch_name}{ch_level}_断面汇总表.xlsx"
        except Exception:
            auto_name = "断面汇总表.xlsx"

        dlg = SectionSummaryDialog(panel.window(), nodes, proj_settings, auto_name, panel=panel)
        dlg.exec()
    except ImportError as e:
        fluent_error(
            panel.window(), "功能不可用",
            f"断面汇总表模块加载失败：\n{str(e)}")
    except Exception as e:
        import traceback; traceback.print_exc()
        fluent_error(panel.window(), "打开失败",
                     f"断面汇总表生成器打开失败：\n{str(e)}")
