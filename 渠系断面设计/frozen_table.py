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
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QPalette, QKeySequence


class FrozenColumnTableWidget(QTableWidget):
    """带冻结列的 QTableWidget，API 与 QTableWidget 完全兼容。"""

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
        # 在冻结视图和主表 viewport 上安装事件过滤器，
        # 彻底拦截冻结列区域的双击事件，只发射自定义信号，
        # 阻止 Qt 内部启动编辑器 / 事件穿透等一切默认行为。
        self._frozen_view.viewport().installEventFilter(self)
        self.viewport().installEventFilter(self)

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

        # 不设置任何自定义 stylesheet，完全继承主表的样式
        # 只设置 border:none 让 overlay 无边框融入主表
        fv.setStyleSheet("QTableView { border: none; }")

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
    # 事件过滤器：彻底拦截冻结列区域的双击
    # ────────────────────────────────────────────
    def eventFilter(self, obj, event):
        """拦截冻结列区域的双击事件，只发射 cellDoubleClicked 信号，
        彻底阻止 Qt 内部启动编辑器 / 事件穿透。"""
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
    # Excel 风格复制粘贴（Ctrl+C / Ctrl+V）
    # ────────────────────────────────────────────
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self._copy_selection_to_clipboard()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            self._paste_from_clipboard()
            return
        super().keyPressEvent(event)

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
