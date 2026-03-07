# -*- coding: utf-8 -*-
"""倒虹吸工况侧边栏 - Fluent Design"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QMenu, QFileDialog
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush
from qfluentwidgets import PushButton, FluentIcon, RoundMenu, Action, MenuAnimationType

from .case_manager import CaseManager, CaseInfo


class CaseListItem(QListWidgetItem):
    """工况列表项"""
    def __init__(self, case: CaseInfo):
        super().__init__(case.name)
        self.case = case
        self.setFlags(self.flags() | Qt.ItemIsEditable)


class CaseSidebar(QWidget):
    """工况侧边栏 - Fluent Design"""
    case_selected = Signal(object)
    case_changed = Signal()

    def __init__(self, manager: CaseManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.current_case = None
        self._editing_item = None
        self._init_ui()
        self._load_cases()

    def _init_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.btn_new = PushButton(FluentIcon.ADD, "新建")
        self.btn_new.setFixedHeight(32)
        self.btn_new.clicked.connect(self._on_new_case)
        toolbar.addWidget(self.btn_new)

        self.btn_import = PushButton(FluentIcon.FOLDER, "导入")
        self.btn_import.setFixedHeight(32)
        self.btn_import.clicked.connect(self._on_import_case)
        toolbar.addWidget(self.btn_import)

        lay.addLayout(toolbar)

        # 工况列表
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)
        self.list_widget.itemChanged.connect(self._on_item_renamed)
        self.list_widget.keyPressEvent = self._on_key_press
        self.list_widget.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                padding: 4px;
            }
            QListWidget::item {
                border-radius: 4px;
                padding: 8px;
                margin: 2px;
            }
            QListWidget::item:hover {
                background: rgba(0, 0, 0, 0.05);
            }
            QListWidget::item:selected {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0078D4, stop:1 #106EBE);
                color: white;
            }
        """)
        lay.addWidget(self.list_widget)

    def _load_cases(self):
        """加载工况列表"""
        self.list_widget.clear()
        for case in self.manager.cases:
            item = CaseListItem(case)
            self.list_widget.addItem(item)

        if self.manager.cases and not self.current_case:
            self.list_widget.setCurrentRow(0)
            self.current_case = self.manager.cases[0]
            self.case_selected.emit(self.current_case)

    def _on_new_case(self):
        """新建工况"""
        case = self.manager.create_case()
        item = CaseListItem(case)
        self.list_widget.addItem(item)
        self.list_widget.setCurrentItem(item)
        self.current_case = case
        self.case_selected.emit(case)
        self.case_changed.emit()

    def _on_import_case(self):
        """导入工况"""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入工况", "", "倒虹吸工况 (*.siphon.json *.json)"
        )
        if path:
            import shutil
            import os
            fname = os.path.basename(path)
            if not fname.endswith('.siphon.json'):
                fname = fname.replace('.json', '.siphon.json')
            dest = os.path.join(self.manager.cases_dir, fname)
            shutil.copy(path, dest)
            self.manager._load_cases()
            self._load_cases()
            self.case_changed.emit()

    def _export_case(self, case: CaseInfo):
        """导出工况"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出工况", f"{case.name}.siphon.json",
            "倒虹吸工况 (*.siphon.json *.json)"
        )
        if path:
            import shutil
            shutil.copy(case.file_path, path)

    def _on_item_clicked(self, item: CaseListItem):
        """单击切换工况"""
        if item.case != self.current_case:
            self.current_case = item.case
            self.case_selected.emit(item.case)

    def _on_item_double_clicked(self, item: CaseListItem):
        """双击重命名"""
        self._editing_item = item
        self.list_widget.editItem(item)

    def _on_item_renamed(self, item: CaseListItem):
        """重命名完成"""
        if self._editing_item == item:
            new_name = item.text()
            if new_name and new_name != item.case.name:
                self.manager.rename_case(item.case, new_name)
                self.case_changed.emit()
            else:
                item.setText(item.case.name)
            self._editing_item = None

    def _on_context_menu(self, pos):
        """右键菜单 - Fluent Design"""
        item = self.list_widget.itemAt(pos)
        if not item:
            return

        menu = RoundMenu(parent=self)

        act_rename = Action(FluentIcon.EDIT, "重命名")
        act_copy = Action(FluentIcon.COPY, "复制")
        act_export = Action(FluentIcon.SHARE, "导出")
        act_delete = Action(FluentIcon.DELETE, "删除")

        menu.addAction(act_rename)
        menu.addAction(act_copy)
        menu.addAction(act_export)
        menu.addSeparator()
        menu.addAction(act_delete)

        act_rename.triggered.connect(lambda: self._on_item_double_clicked(item))
        act_copy.triggered.connect(lambda: self._duplicate_case(item))
        act_export.triggered.connect(lambda: self._export_case(item.case))
        act_delete.triggered.connect(lambda: self._delete_case(item))

        menu.exec(self.list_widget.mapToGlobal(pos), aniType=MenuAnimationType.DROP_DOWN)

    def _duplicate_case(self, item):
        """复制工况"""
        new_case = self.manager.duplicate_case(item.case)
        new_item = CaseListItem(new_case)
        self.list_widget.addItem(new_item)
        self.case_changed.emit()

    def _delete_case(self, item):
        """删除工况"""
        self.manager.delete_case(item.case)
        self.list_widget.takeItem(self.list_widget.row(item))
        if item.case == self.current_case:
            if self.list_widget.count() > 0:
                self.list_widget.setCurrentRow(0)
                self.current_case = self.list_widget.item(0).case
                self.case_selected.emit(self.current_case)
            else:
                self.current_case = None
        self.case_changed.emit()

    def _on_key_press(self, event):
        """键盘事件处理"""
        if event.key() == Qt.Key_Delete:
            item = self.list_widget.currentItem()
            if item:
                self._delete_case(item)
        else:
            QListWidget.keyPressEvent(self.list_widget, event)

    def _on_rows_moved(self):
        """拖拽排序完成"""
        new_order = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            new_order.append(item.case)
        self.manager.reorder_cases(new_order)
        self.case_changed.emit()

    def get_current_case(self) -> CaseInfo:
        """获取当前工况"""
        return self.current_case

    def refresh(self):
        """刷新列表"""
        self.manager._load_cases()
        self._load_cases()
