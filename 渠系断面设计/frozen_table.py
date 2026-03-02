# -*- coding: utf-8 -*-
"""
冻结列表格控件 —— 基于 Qt 官方 FrozenColumn 示例

继承 QTableWidget，在其上叠加一个 QTableView 作为冻结列 overlay。
两者共享同一个 model，冻结视图只显示前 N 列，其余列隐藏。
水平滚动时冻结列纹丝不动，与 Excel 冻结窗格体验一致。

用法：
    table = FrozenColumnTableWidget(rows, cols, frozen_count=4, parent=self)
    # 之后像普通 QTableWidget 一样使用 setItem / item / cellChanged 等 API
"""

from PySide6.QtWidgets import (
    QTableWidget, QTableView, QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtGui import QPalette, QKeySequence


class FrozenColumnTableWidget(QTableWidget):
    """带冻结列的 QTableWidget，API 与 QTableWidget 完全兼容。"""

    # ── 自定义信号：供面板连接以实现业务级撤销/重做 ──
    undoRequested = Signal()
    redoRequested = Signal()
    deleteRequested = Signal()  # Delete 键按下前发射，面板可记录快照
    readOnlyDeleteAttempted = Signal()  # 用户在只读单元格上尝试删除时发射

    def __init__(self, rows=0, cols=0, frozen_count=4, parent=None):
        super().__init__(rows, cols, parent)
        self._frozen_count = frozen_count
        self._first_show = True

        # 创建冻结列的 overlay 视图（作为 self 的子控件）
        self._frozen_view = QTableView(self)
        self._frozen_view.setModel(self.model())
        self._frozen_view.setSelectionModel(self.selectionModel())

        self._init_frozen_view()

        # ── 信号连接 ──
        # 主表列宽变化 → 同步到冻结视图
        self.horizontalHeader().sectionResized.connect(self._on_section_width_changed)
        # 主表行高变化 → 同步到冻结视图
        self.verticalHeader().sectionResized.connect(self._on_section_height_changed)
        # 新增行时同步行高到冻结视图
        self.model().rowsInserted.connect(self._on_rows_inserted)
        # 垂直滚动条双向同步
        self._frozen_view.verticalScrollBar().valueChanged.connect(
            self.verticalScrollBar().setValue
        )
        self.verticalScrollBar().valueChanged.connect(
            self._frozen_view.verticalScrollBar().setValue
        )

        # ── 事件过滤器 ──
        # 在冻结视图、主表 viewport 和主表自身上安装事件过滤器，
        # 拦截冻结列区域的双击事件和键盘快捷键。
        self._frozen_view.viewport().installEventFilter(self)
        self.viewport().installEventFilter(self)
        self.installEventFilter(self)  # 捕获键盘事件

    # ────────────────────────────────────────────
    # 初始化
    # ────────────────────────────────────────────
    def _init_frozen_view(self):
        fv = self._frozen_view
        fv.setFocusPolicy(Qt.NoFocus)
        fv.verticalHeader().hide()
        fv.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        # 冻结视图仅用于展示，禁止任何编辑
        fv.setEditTriggers(QAbstractItemView.NoEditTriggers)

        # 让冻结视图在无焦点时也用活跃选中色高亮（否则 NoFocus 导致选中行不显色）
        pal = fv.palette()
        pal.setColor(QPalette.Inactive, QPalette.Highlight,
                     pal.color(QPalette.Active, QPalette.Highlight))
        pal.setColor(QPalette.Inactive, QPalette.HighlightedText,
                     pal.color(QPalette.Active, QPalette.HighlightedText))
        fv.setPalette(pal)

        # 隐藏冻结视图中非冻结列
        for col in range(self._frozen_count, self.model().columnCount()):
            fv.setColumnHidden(col, True)

        # 同步冻结列的列宽
        for col in range(self._frozen_count):
            fv.setColumnWidth(col, self.columnWidth(col))

        # 关闭冻结视图自身的滚动条
        fv.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        fv.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 用 CSS border-right 作为冻结列与滚动区的分隔线（Qt Champion 推荐方案）。
        # border-right 由 widget 框架绘制，不依赖网格线，彻底避免双线伪影。
        # overlay 宽度 frozen_width+1 中的 +1 被 border-right 消耗，
        # viewport 宽度仍精确等于 frozen_width。
        fv.setStyleSheet(
            "QTableView { border: none; border-right: 1px solid #d4d4d4; }"
        )

        # 像素级滚动
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        fv.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

        # 将 viewport 堆叠到 frozen 下方（frozen 在上层）
        self.viewport().stackUnder(fv)

        fv.show()
        self._update_frozen_geometry()

    def _sync_all_properties(self):
        """将主表当前所有视觉属性同步到冻结视图（在 showEvent 中调用，
        此时外部设置的 font/行高/交替色等已全部就绪）。"""
        fv = self._frozen_view

        # 字体
        fv.setFont(self.font())

        # 交互属性
        fv.setAlternatingRowColors(self.alternatingRowColors())
        fv.setSelectionBehavior(self.selectionBehavior())
        # 注意：不同步 editTriggers，冻结视图始终禁止编辑

        # 水平表头高度同步（关键！当表头有多行文字如"底宽\nB"时，
        # 主表表头会更高，冻结视图表头必须与之一致，否则数据行错位）
        fv.horizontalHeader().setFixedHeight(self.horizontalHeader().height())

        # 默认行高（关键！外部在构造后才调用 verticalHeader().setDefaultSectionSize()）
        default_h = self.verticalHeader().defaultSectionSize()
        fv.verticalHeader().setDefaultSectionSize(default_h)

        # 同步所有已有行的行高
        for row in range(self.rowCount()):
            fv.setRowHeight(row, self.rowHeight(row))

        # 同步冻结列的列宽
        for col in range(self._frozen_count):
            if col < self.columnCount():
                fv.setColumnWidth(col, self.columnWidth(col))

        self._update_frozen_geometry()

    # ────────────────────────────────────────────
    # 几何更新
    # ────────────────────────────────────────────
    def _update_frozen_geometry(self):
        """根据当前冻结列宽度调整 overlay 的位置和大小。"""
        frozen_width = sum(
            self.columnWidth(c) for c in range(min(self._frozen_count, self.columnCount()))
        )
        fv = self._frozen_view
        # CSS border-right 从冻结列最右侧像素取 1px，替代该处网格线作为分隔线。
        # overlay 宽度 = frozen_width（精确），不侵占第一个非冻结列的空间。
        fv.setGeometry(
            self.verticalHeader().width() + self.frameWidth(),
            self.frameWidth(),
            frozen_width,
            self.viewport().height() + self.horizontalHeader().height(),
        )

    # ────────────────────────────────────────────
    # 信号槽
    # ────────────────────────────────────────────
    def _on_section_width_changed(self, logical_index, old_size, new_size):
        if logical_index < self._frozen_count:
            self._frozen_view.setColumnWidth(logical_index, new_size)
            self._update_frozen_geometry()

    def _on_section_height_changed(self, logical_index, old_size, new_size):
        self._frozen_view.setRowHeight(logical_index, new_size)

    def _on_rows_inserted(self, parent, first, last):
        """新增行时，将主表的默认行高同步到冻结视图。"""
        default_h = self.verticalHeader().defaultSectionSize()
        for row in range(first, last + 1):
            self._frozen_view.setRowHeight(row, default_h)

    # ────────────────────────────────────────────
    # 事件过滤器：拦截冻结列双击 + 键盘快捷键
    # ────────────────────────────────────────────
    def eventFilter(self, obj, event):
        """拦截冻结列区域的双击事件，以及处理键盘快捷键。"""
        # 键盘事件处理
        if event.type() == QEvent.ShortcutOverride:
            # ShortcutOverride: 只检查是否要处理，不发射信号
            if obj is self or obj is self.viewport() or obj is self._frozen_view.viewport():
                if self._should_handle_key(event):
                    event.accept()  # 告诉 Qt 我们要处理这个快捷键
                    return True
        elif event.type() == QEvent.KeyPress:
            # KeyPress: 实际处理并发射信号
            if obj is self or obj is self.viewport() or obj is self._frozen_view.viewport():
                if self._handle_key_event(event):
                    return True
        
        # 双击事件处理
        if event.type() == QEvent.MouseButtonDblClick:
            # 情况1：双击发生在冻结视图的 viewport 上
            if obj is self._frozen_view.viewport():
                index = self._frozen_view.indexAt(event.position().toPoint())
                if index.isValid():
                    row, col = index.row(), index.column()
                    self.setCurrentCell(row, col)
                    self.cellDoubleClicked.emit(row, col)
                return True  # 彻底消费，阻止冻结视图启动编辑器

            # 情况2：双击发生在主表 viewport 上，但落在冻结列区域
            if obj is self.viewport():
                index = self.indexAt(event.position().toPoint())
                if index.isValid() and index.column() < self._frozen_count:
                    return True  # 冻结列区域由上方 overlay 处理，主表不要响应

        return super().eventFilter(obj, event)

    def _should_handle_key(self, event):
        """检查是否应该处理该按键（仅检查，不发射信号）。"""
        key = event.key()
        mods = event.modifiers()
        has_ctrl = bool(mods & Qt.ControlModifier)
        has_shift = bool(mods & Qt.ShiftModifier)
        has_alt = bool(mods & Qt.AltModifier)
        has_meta = bool(mods & Qt.MetaModifier)
        
        # Ctrl+Z/Y, Ctrl+Shift+Z, Delete/Backspace
        if key == Qt.Key_Z and has_ctrl and not has_alt and not has_meta:
            return True
        if key == Qt.Key_Y and has_ctrl and not has_shift and not has_alt and not has_meta:
            return True
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            if self.state() != QAbstractItemView.State.EditingState:
                return True
        return False

    def _handle_key_event(self, event):
        """处理键盘快捷键，返回 True 表示事件已被处理。"""
        key = event.key()
        mods = event.modifiers()
        # 使用位运算检查修饰键，忽略 KeypadModifier 等平台特定标志
        has_ctrl = bool(mods & Qt.ControlModifier)
        has_shift = bool(mods & Qt.ShiftModifier)
        has_alt = bool(mods & Qt.AltModifier)
        has_meta = bool(mods & Qt.MetaModifier)
        
        # 只读表格（NoEditTriggers）不响应撤销/重做/删除操作
        is_readonly = (self.editTriggers() == QAbstractItemView.NoEditTriggers)
        
        # Ctrl+Z 撤销（仅 Ctrl，无 Shift/Alt/Meta）
        if key == Qt.Key_Z and has_ctrl and not has_shift and not has_alt and not has_meta:
            if not is_readonly:
                self.undoRequested.emit()
            return True  # 即使不处理也要拦截，避免事件传递
        # Ctrl+Y 重做（仅 Ctrl）
        if key == Qt.Key_Y and has_ctrl and not has_shift and not has_alt and not has_meta:
            if not is_readonly:
                self.redoRequested.emit()
            return True
        # Ctrl+Shift+Z 重做
        if key == Qt.Key_Z and has_ctrl and has_shift and not has_alt and not has_meta:
            if not is_readonly:
                self.redoRequested.emit()
            return True
        # Delete / Backspace 清空选中单元格（非编辑状态）
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            if self.state() != QAbstractItemView.State.EditingState:
                self._delete_selected_cells()
                return True
        
        return False  # 未处理的按键交给默认处理

    # ────────────────────────────────────────────
    # 重写事件
    # ────────────────────────────────────────────
    def showEvent(self, event):
        """首次显示时做完整属性同步（此时外部的所有设置已就绪）。"""
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            self._sync_all_properties()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 同步水平表头高度（主表表头高度可能因布局变化而改变）
        if not self._first_show:
            main_hh = self.horizontalHeader().height()
            if self._frozen_view.horizontalHeader().height() != main_hh:
                self._frozen_view.horizontalHeader().setFixedHeight(main_hh)
        self._update_frozen_geometry()

    def updateGeometries(self):
        """Qt 在表格内部几何变化时调用（行头宽度、滚动条等），
        同步刷新冻结视图位置，避免行数变化导致行头宽度改变后冻结列偏移。"""
        super().updateGeometries()
        self._update_frozen_geometry()

    def moveCursor(self, cursor_action, modifiers):
        current = super().moveCursor(cursor_action, modifiers)
        frozen_width = sum(
            self.columnWidth(c) for c in range(min(self._frozen_count, self.columnCount()))
        )
        if (
            cursor_action == QAbstractItemView.CursorAction.MoveLeft
            and current.column() >= self._frozen_count
            and self.visualRect(current).topLeft().x() < frozen_width
        ):
            new_val = (
                self.horizontalScrollBar().value()
                + self.visualRect(current).topLeft().x()
                - frozen_width
            )
            self.horizontalScrollBar().setValue(new_val)
        return current

    def scrollTo(self, index, hint=QAbstractItemView.ScrollHint.EnsureVisible):
        if index.column() < self._frozen_count:
            return
        super().scrollTo(index, hint)

    # ────────────────────────────────────────────
    # 属性同步：构造后设置的属性需要传播到冻结视图
    # ────────────────────────────────────────────
    def setFont(self, font):
        super().setFont(font)
        if hasattr(self, '_frozen_view'):
            self._frozen_view.setFont(font)

    def setAlternatingRowColors(self, enable):
        super().setAlternatingRowColors(enable)
        if hasattr(self, '_frozen_view'):
            self._frozen_view.setAlternatingRowColors(enable)

    def setSelectionBehavior(self, behavior):
        super().setSelectionBehavior(behavior)
        if hasattr(self, '_frozen_view'):
            self._frozen_view.setSelectionBehavior(behavior)

    def setEditTriggers(self, triggers):
        super().setEditTriggers(triggers)
        # 不传播到冻结视图，冻结视图始终 NoEditTriggers

    # ────────────────────────────────────────────
    # 列数变化时同步冻结视图
    # ────────────────────────────────────────────
    def setColumnCount(self, columns):
        super().setColumnCount(columns)
        self._sync_frozen_columns()

    def setHorizontalHeaderLabels(self, labels):
        super().setHorizontalHeaderLabels(labels)
        self._sync_frozen_columns()

    def _sync_frozen_columns(self):
        """当列数变化时，重新设置冻结视图的列隐藏状态。"""
        col_count = self.model().columnCount()
        for col in range(col_count):
            self._frozen_view.setColumnHidden(col, col >= self._frozen_count)
        for col in range(self._frozen_count):
            if col < col_count:
                self._frozen_view.setColumnWidth(col, self.columnWidth(col))
        self._update_frozen_geometry()

    # ────────────────────────────────────────────
    # Excel 风格键盘操作
    # ────────────────────────────────────────────
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        # 使用位运算检查修饰键
        has_ctrl = bool(mods & Qt.ControlModifier)
        has_shift = bool(mods & Qt.ShiftModifier)
        has_alt = bool(mods & Qt.AltModifier)
        has_meta = bool(mods & Qt.MetaModifier)
        ctrl_only = has_ctrl and not has_shift and not has_alt and not has_meta
        ctrl_shift_only = has_ctrl and has_shift and not has_alt and not has_meta
        
        # 只读表格（NoEditTriggers）不响应撤销/重做操作
        is_readonly = (self.editTriggers() == QAbstractItemView.NoEditTriggers)
        
        # Ctrl+C 复制
        if key == Qt.Key_C and ctrl_only:
            self._copy_selection_to_clipboard()
            return
        # Ctrl+V 粘贴（只读表格不允许粘贴）
        if key == Qt.Key_V and ctrl_only:
            if not is_readonly:
                self._paste_from_clipboard()
            return
        # Ctrl+Z 撤销（只读表格不响应）
        if key == Qt.Key_Z and ctrl_only:
            if not is_readonly:
                self.undoRequested.emit()
            return
        # Ctrl+Y 或 Ctrl+Shift+Z 重做（只读表格不响应）
        if (key == Qt.Key_Y and ctrl_only) or (key == Qt.Key_Z and ctrl_shift_only):
            if not is_readonly:
                self.redoRequested.emit()
            return
        # Delete / Backspace 清空选中单元格
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            if self.state() != QAbstractItemView.State.EditingState:
                self._delete_selected_cells()
                return
        # Tab 向右导航到下一个可编辑单元格
        if key == Qt.Key_Tab and not has_alt and not has_meta:
            if self.state() != QAbstractItemView.State.EditingState:
                forward = not has_shift
                self._navigate_next_editable(forward)
                return
        # Enter 向下导航（非编辑状态时）
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if self.state() != QAbstractItemView.State.EditingState:
                down = not has_shift
                self._navigate_vertical(down)
                return
        super().keyPressEvent(event)

    def _delete_selected_cells(self):
        """清空所有选中的可编辑单元格。"""
        # 如果表格设置了 NoEditTriggers，直接拒绝删除操作
        if self.editTriggers() == QAbstractItemView.NoEditTriggers:
            self.readOnlyDeleteAttempted.emit()
            return
        selected = self.selectedIndexes()
        if not selected:
            return
        # 先检查是否有任何可编辑的单元格，如果没有则直接返回（只读表格不响应Delete）
        editable_indexes = [
            idx for idx in selected
            if (item := self.item(idx.row(), idx.column())) and (item.flags() & Qt.ItemIsEditable)
        ]
        if not editable_indexes:
            # 通知面板：用户在只读单元格上尝试删除
            self.readOnlyDeleteAttempted.emit()
            return
        # 先通知面板记录快照（在修改前）
        self.deleteRequested.emit()
        self.blockSignals(True)
        for idx in editable_indexes:
            item = self.item(idx.row(), idx.column())
            item.setText("")
        self.blockSignals(False)
        # 逐个触发 cellChanged 以便面板可处理联动（如水头损失重算）
        for idx in editable_indexes:
            self.cellChanged.emit(idx.row(), idx.column())

    def _navigate_next_editable(self, forward=True):
        """Tab / Shift+Tab：跳到下一个/上一个可编辑单元格，跳过不可编辑列。"""
        current = self.currentIndex()
        if not current.isValid():
            return
        row, col = current.row(), current.column()
        total_cols = self.columnCount()
        total_rows = self.rowCount()
        if total_rows == 0 or total_cols == 0:
            return

        if forward:
            # 从当前位置向右查找
            c = col + 1
            r = row
            while r < total_rows:
                while c < total_cols:
                    item = self.item(r, c)
                    if item is None or (item.flags() & Qt.ItemIsEditable):
                        self.setCurrentCell(r, c)
                        return
                    c += 1
                r += 1
                c = 0
        else:
            # 从当前位置向左查找
            c = col - 1
            r = row
            while r >= 0:
                while c >= 0:
                    item = self.item(r, c)
                    if item is None or (item.flags() & Qt.ItemIsEditable):
                        self.setCurrentCell(r, c)
                        return
                    c -= 1
                r -= 1
                c = total_cols - 1

    def _navigate_vertical(self, down=True):
        """Enter / Shift+Enter：向下/向上移动一行，保持当前列。"""
        current = self.currentIndex()
        if not current.isValid():
            return
        row, col = current.row(), current.column()
        if down and row + 1 < self.rowCount():
            self.setCurrentCell(row + 1, col)
        elif not down and row > 0:
            self.setCurrentCell(row - 1, col)

    def _copy_selection_to_clipboard(self):
        """将选中单元格以 Tab 分隔、换行分行的格式复制到剪贴板（与 Excel 兼容）。"""
        from PySide6.QtWidgets import QApplication
        indexes = self.selectedIndexes()
        if not indexes:
            return
        rows = sorted(set(idx.row() for idx in indexes))
        cols = sorted(set(idx.column() for idx in indexes))
        lines = []
        for r in rows:
            row_data = []
            for c in cols:
                item = self.item(r, c)
                row_data.append(item.text() if item else "")
            lines.append("\t".join(row_data))
        QApplication.clipboard().setText("\n".join(lines))

    def _paste_from_clipboard(self):
        """从剪贴板粘贴内容到表格，从当前单元格开始，跳过不可编辑单元格。"""
        from PySide6.QtWidgets import QApplication, QTableWidgetItem
        text = QApplication.clipboard().text()
        if not text:
            return
        current = self.currentIndex()
        if not current.isValid():
            return
        start_row = current.row()
        start_col = current.column()
        lines = text.rstrip('\n\r').split('\n')
        for r_offset, line in enumerate(lines):
            cells = line.split('\t')
            for c_offset, value in enumerate(cells):
                tr = start_row + r_offset
                tc = start_col + c_offset
                if tr >= self.rowCount() or tc >= self.columnCount():
                    continue
                item = self.item(tr, tc)
                if item is None:
                    item = QTableWidgetItem()
                    self.setItem(tr, tc, item)
                if not (item.flags() & Qt.ItemIsEditable):
                    continue
                item.setText(value.strip())
