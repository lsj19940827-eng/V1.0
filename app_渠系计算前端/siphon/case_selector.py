# -*- coding: utf-8 -*-
"""倒虹吸紧凑工况选择控件，与 case_manager 协作管理工况文件。"""

import os
import shutil

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QComboBox,
    QSizePolicy,
    QWidget,
)
from qfluentwidgets import Action, FluentIcon, PushButton, RoundMenu, MenuAnimationType

from .case_manager import CaseInfo, CaseManager


class CaseSelector(QWidget):
    """底部操作栏使用的紧凑工况选择器。"""

    case_selected = Signal(object)
    case_changed = Signal()

    def __init__(self, manager: CaseManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._current_case = None
        self._syncing = False
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        """构建一行内的工况选择和管理入口。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(QLabel("工况:"))

        self.combo_cases = QComboBox()
        self.combo_cases.setFixedWidth(150)
        self.combo_cases.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_cases.setToolTip("选择当前倒虹吸工况（单个方案，不是项目文件）")
        self.combo_cases.currentIndexChanged.connect(self._on_combo_changed)
        layout.addWidget(self.combo_cases)

        self.btn_new = PushButton("+")
        self.btn_new.setFixedWidth(34)
        self.btn_new.setToolTip("新建工况")
        self.btn_new.clicked.connect(self._create_case)
        layout.addWidget(self.btn_new)

        self.btn_more = PushButton("更多")
        self.btn_more.setFixedWidth(62)
        self.btn_more.setToolTip("管理单个倒虹吸工况：从文件添加、导出当前、重命名、复制或删除；不是项目文件")
        self.btn_more.clicked.connect(self._show_more_menu)
        layout.addWidget(self.btn_more)

        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def refresh(self, select_case: CaseInfo = None):
        """刷新下拉框，必要时选中指定工况。"""
        selected_path = self._case_path(select_case) or self._case_path(self._current_case)
        self.manager._load_cases()

        self._syncing = True
        self.combo_cases.clear()
        for case in self.manager.cases:
            self.combo_cases.addItem(case.name, case)

        target_index = self._find_index_by_path(selected_path)
        if target_index < 0 and self.combo_cases.count() > 0:
            target_index = 0
        self.combo_cases.setCurrentIndex(target_index)
        self._current_case = self.combo_cases.itemData(target_index) if target_index >= 0 else None
        self._syncing = False
        self._update_enabled_state()

    def get_current_case(self) -> CaseInfo:
        """获取当前选中的工况。"""
        return self._current_case

    def set_current_case(self, case: CaseInfo):
        """外部指定当前工况。"""
        self.refresh(case)

    def _on_combo_changed(self, index: int):
        """用户切换下拉框时发出工况切换信号。"""
        if self._syncing:
            return
        case = self.combo_cases.itemData(index)
        if case is None:
            self._current_case = None
            self._update_enabled_state()
            return
        if self._case_path(case) == self._case_path(self._current_case):
            return
        self._update_enabled_state()
        self.case_selected.emit(case)
        self._current_case = case
        self._update_enabled_state()

    def _create_case(self):
        """新建工况并切换过去。"""
        old_case = self._current_case
        case = self.manager.create_case()
        self.refresh(case)
        self._emit_case_selected_after_refresh(old_case)
        self.case_changed.emit()

    def _import_case(self):
        """导入工况文件并切换过去。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "从文件添加工况", "", "倒虹吸工况 (*.siphon.json *.json)"
        )
        if not path:
            return
        try:
            case = self.manager.import_case_file(path)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", f"工况文件格式错误或损坏：{exc}")
            return
        old_case = self._current_case
        self.refresh(case)
        self._emit_case_selected_after_refresh(old_case)
        self.case_changed.emit()

    def _show_more_menu(self):
        """弹出当前工况的低频操作菜单。"""
        menu = RoundMenu(parent=self)
        act_rename = Action(FluentIcon.EDIT, "重命名")
        act_copy = Action(FluentIcon.COPY, "复制")
        act_import = Action(FluentIcon.FOLDER, "从文件添加工况...")
        act_export = Action(FluentIcon.SHARE, "导出当前工况...")
        act_delete = Action(FluentIcon.DELETE, "删除")

        menu.addAction(act_rename)
        menu.addAction(act_copy)
        menu.addAction(act_import)
        menu.addAction(act_export)
        menu.addSeparator()
        menu.addAction(act_delete)

        act_rename.triggered.connect(self._rename_current_case)
        act_copy.triggered.connect(self._duplicate_current_case)
        act_import.triggered.connect(self._import_case)
        act_export.triggered.connect(self._export_current_case)
        act_delete.triggered.connect(self._delete_current_case)

        pos = self.btn_more.mapToGlobal(self.btn_more.rect().bottomLeft())
        menu.exec(pos, aniType=MenuAnimationType.DROP_DOWN)

    def _rename_current_case(self):
        """重命名当前工况。"""
        case = self.get_current_case()
        if case is None:
            return
        text, ok = QInputDialog.getText(self, "重命名工况", "工况名称:", text=case.name)
        if not ok:
            return
        new_name = self.manager._clean_case_name(text)
        if not new_name or new_name == case.name:
            return
        if any(c.name == new_name and self._case_path(c) != self._case_path(case)
               for c in self.manager.cases):
            QMessageBox.warning(self, "无法重命名", "已存在同名工况。")
            return
        self.manager.rename_case(case, new_name)
        self.refresh(case)
        self.case_changed.emit()

    def _duplicate_current_case(self):
        """复制当前工况并切换到副本。"""
        case = self.get_current_case()
        if case is None:
            return
        new_case = self.manager.duplicate_case(case)
        old_case = self._current_case
        self.refresh(new_case)
        self._emit_case_selected_after_refresh(old_case)
        self.case_changed.emit()

    def _export_current_case(self):
        """导出当前工况文件。"""
        case = self.get_current_case()
        if case is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出当前工况", f"{case.name}.siphon.json", "倒虹吸工况 (*.siphon.json *.json)"
        )
        if path:
            shutil.copy(case.file_path, path)

    def _delete_current_case(self):
        """删除当前工况，并保证至少保留一个可选工况。"""
        case = self.get_current_case()
        if case is None:
            return
        ret = QMessageBox.question(
            self,
            "删除工况",
            f"确定删除“{case.name}”吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return

        self.manager.delete_case(case)
        self.manager._load_cases()
        if not self.manager.cases:
            next_case = self.manager.create_case()
        else:
            next_case = self.manager.cases[0]
        self.refresh(next_case)
        self.case_selected.emit(self._current_case)
        self.case_changed.emit()

    def _emit_case_selected_after_refresh(self, old_case: CaseInfo):
        """刷新到目标工况后，先让面板仍能保存旧工况，再完成切换。"""
        target_case = self._current_case
        self._current_case = old_case
        self.case_selected.emit(target_case)
        self._current_case = target_case
        self._update_enabled_state()

    def _find_index_by_path(self, file_path: str) -> int:
        """按文件路径查找下拉框索引。"""
        if not file_path:
            return -1
        target = os.path.abspath(file_path)
        for idx in range(self.combo_cases.count()):
            case = self.combo_cases.itemData(idx)
            if self._case_path(case) and os.path.abspath(case.file_path) == target:
                return idx
        return -1

    def _update_enabled_state(self):
        """根据是否有工况更新低频按钮可用状态。"""
        has_case = self._current_case is not None
        self.btn_more.setEnabled(has_case)

    @staticmethod
    def _case_path(case: CaseInfo) -> str:
        """安全取得工况文件路径。"""
        return getattr(case, "file_path", "") if case is not None else ""
