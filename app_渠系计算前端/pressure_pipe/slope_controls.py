"""无压对比输入组件，负责坡度模式、批量编辑、可选净空条件及项目保存。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QPlainTextEdit, QLineEdit, QCheckBox, QButtonGroup, QSizePolicy,
)

from calc_渠系计算算法内核.unpressurized_comparison import (
    STANDARD_SLOPES, DEFAULT_ROUGHNESS, DEFAULT_RANGE, DEFAULT_CLEARANCE_HEIGHT,
    DEFAULT_CLEARANCE_AREA, MAX_CUSTOM_SLOPES, parse_slope_text, generate_slopes,
)


class SlopeComparisonControls(QWidget):
    """标准方案只读；自定义原文跨模式切换、关闭和项目重开保留。"""
    changed = Signal()

    def __init__(self, parent=None):
        """创建两种模式及独立编辑状态，不使用流式标签布局。"""
        super().__init__(parent)
        self.mode = "standard"
        self._undo_text = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 0, 0)
        layout.setSpacing(9)
        layout.setAlignment(Qt.AlignTop)
        self._label(layout, "按各候选管道的实际内径，计算不同底坡下的无压输水情况。")
        self._label(layout, "管道底坡", bold=True)
        row = QHBoxLayout()
        group = QButtonGroup(self)
        self.mode_buttons = {}
        for key, title in (("standard", "标准 9 档"), ("custom", "自定义")):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setMinimumHeight(32)
            button.setStyleSheet("QPushButton:checked{background:#0078d4;color:white;border-radius:5px;}")
            button.clicked.connect(lambda _checked=False, mode=key: self.set_mode(mode))
            group.addButton(button)
            self.mode_buttons[key] = button
            row.addWidget(button)
        layout.addLayout(row)
        self.standard_box = QWidget()
        self.standard_grid = QGridLayout(self.standard_box)
        self.standard_grid.setContentsMargins(0, 0, 0, 0)
        self.standard_labels = []
        for index, value in enumerate(STANDARD_SLOPES):
            label = QLabel(f"1/{value}")
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumHeight(32)
            label.setStyleSheet("background:#eaf4fc;color:#075b9c;border-radius:5px;padding:4px;")
            self.standard_grid.addWidget(label, index // 3, index % 3)
            self.standard_labels.append(label)
        layout.addWidget(self.standard_box)
        self.standard_hint = self._label(layout, "程序预设，共 9 档；修改请复制到自定义。")
        self.copy_button = QPushButton("复制标准 9 档到自定义")
        self.copy_button.clicked.connect(self.copy_standard)
        layout.addWidget(self.copy_button)

        self.custom_box = QWidget()
        self.custom_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        custom = QVBoxLayout(self.custom_box)
        custom.setContentsMargins(0, 0, 0, 0)
        custom.setAlignment(Qt.AlignTop)
        self._label(custom, "填写坡度分母，用逗号、空格或换行分隔。")
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("例如：500, 750, 1000, 2000")
        self.editor.setFixedHeight(88)
        self.editor.textChanged.connect(self._refresh)
        custom.addWidget(self.editor)
        self.feedback = self._label(custom, "")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(72)
        self.preview.setPlaceholderText("有效坡度预览")
        custom.addWidget(self.preview)
        actions = QHBoxLayout()
        clear = QPushButton("清空自定义")
        clear.clicked.connect(self.clear_custom)
        self.undo_button = QPushButton("撤销清空")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo_clear)
        actions.addWidget(clear)
        actions.addWidget(self.undo_button)
        custom.addLayout(actions)
        self.range_toggle = QCheckBox("按范围生成")
        custom.addWidget(self.range_toggle)
        self.range_box = QWidget()
        range_layout = QGridLayout(self.range_box)
        range_layout.setContentsMargins(0, 0, 0, 0)
        self.range_edits = []
        for index, (title, value) in enumerate(zip(("起始分母", "终止分母", "分母步长"), DEFAULT_RANGE)):
            edit = QLineEdit(str(value))
            range_layout.addWidget(QLabel(title), index, 0)
            range_layout.addWidget(edit, index, 1)
            self.range_edits.append(edit)
        generate = QPushButton("生成并替换自定义")
        generate.clicked.connect(self.generate_range)
        range_layout.addWidget(generate, 3, 0, 1, 2)
        self.range_feedback = QLabel("")
        self.range_feedback.setWordWrap(True)
        range_layout.addWidget(self.range_feedback, 4, 0, 1, 2)
        self.range_toggle.toggled.connect(self.range_box.setVisible)
        self.range_box.hide()
        custom.addWidget(self.range_box)
        layout.addWidget(self.custom_box)

        self.n_edit = self._input_row(layout, "无压计算糙率", DEFAULT_ROUGHNESS)
        self._label(layout, "所有无压对比统一采用此糙率。")
        self.criteria_toggle = QCheckBox("设置项目净空条件")
        layout.addWidget(self.criteria_toggle)
        self.criteria_box = QWidget()
        criteria = QVBoxLayout(self.criteria_box)
        criteria.setContentsMargins(0, 0, 0, 0)
        self.height_edit = self._input_row(criteria, "净空高度下限 (m)", DEFAULT_CLEARANCE_HEIGHT)
        self.area_edit = self._input_row(criteria, "净空面积下限 (%)", DEFAULT_CLEARANCE_AREA)
        self._label(criteria, "可留空一项。")
        self.criteria_toggle.toggled.connect(self.criteria_box.setVisible)
        self.criteria_toggle.toggled.connect(self.changed)
        self.criteria_box.hide()
        layout.addWidget(self.criteria_box)
        self.summary = self._label(layout, "", bold=True)
        for edit in (self.n_edit, self.height_edit, self.area_edit, *self.range_edits):
            edit.textChanged.connect(self.changed)
        self.set_mode("standard")

    @staticmethod
    def _label(layout, text, bold=False):
        """添加自动换行的说明，避免窄侧栏横向溢出。"""
        label = QLabel(text)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        label.setStyleSheet("color:#24577b;font-weight:600;" if bold else "color:#657180;font-size:12px;")
        layout.addWidget(label)
        return label

    @staticmethod
    def _input_row(layout, title, value):
        """构建保留原始输入的数值行，计算前统一校验。"""
        row = QHBoxLayout()
        row.addWidget(QLabel(title))
        edit = QLineEdit(str(value))
        edit.setMinimumWidth(60)
        row.addWidget(edit, 1)
        layout.addLayout(row)
        return edit

    def resizeEvent(self, event):
        """窄侧栏使用两列，普通侧栏使用三列，交由网格计算完整行高。"""
        super().resizeEvent(event)
        columns = 3 if self.width() >= 310 else 2
        for index, label in enumerate(self.standard_labels):
            self.standard_grid.addWidget(label, index // columns, index % columns)

    def set_mode(self, mode):
        """切换模式仅控制显示，绝不清空自定义内容。"""
        self.mode = "custom" if mode == "custom" else "standard"
        self.mode_buttons[self.mode].setChecked(True)
        self.standard_box.setVisible(self.mode == "standard")
        self.standard_hint.setVisible(self.mode == "standard")
        self.custom_box.setVisible(self.mode == "custom")
        self._refresh()

    def copy_standard(self):
        """明确点击复制时才替换自定义内容。"""
        self.editor.setPlainText(", ".join(map(str, STANDARD_SLOPES)))
        self.set_mode("custom")

    def clear_custom(self):
        """保留清空前的原文，允许一次恢复。"""
        if self.editor.toPlainText():
            self._undo_text = self.editor.toPlainText()
            self.editor.clear()
            self.undo_button.setEnabled(True)

    def undo_clear(self):
        """恢复最近一次清空前的输入，包括当时的无效词。"""
        if self._undo_text is not None:
            self.editor.setPlainText(self._undo_text)
            self._undo_text = None
            self.undo_button.setEnabled(False)

    def generate_range(self):
        """生成合法分母范围，错误时保留编辑器和范围输入。"""
        try:
            values = generate_slopes(*(edit.text() for edit in self.range_edits))
        except ValueError as exc:
            self.range_feedback.setText(str(exc))
            self.range_feedback.setStyleSheet("color:#b42318;")
            return
        self.editor.setPlainText(", ".join(map(str, values)))
        self.range_feedback.setStyleSheet("color:#24577b;")
        self.range_feedback.setText(f"已生成 {len(values)} 个坡度，最后一个分母为 {values[-1]}。")

    def _refresh(self):
        """显示去重结果和逐词错误，禁止有效子集掩盖错误输入。"""
        values, invalid, duplicates = parse_slope_text(self.editor.toPlainText())
        self.preview.setPlainText("，".join(f"1/{v}" for v in values[:MAX_CUSTOM_SLOPES]))
        message = f"有效坡度 {len(values)} 个"
        if duplicates:
            message += f"；{duplicates} 个重复项已去重"
        if invalid:
            message += "；请修改：" + "、".join(invalid)
        self.feedback.setText(message)
        self.feedback.setStyleSheet("color:#b42318;" if invalid else "color:#657180;")
        count = len(STANDARD_SLOPES) if self.mode == "standard" else len(values)
        self.summary.setText("自定义输入待修正" if self.mode == "custom" and invalid else f"本次对比 {count} 个坡度；同时计算设计流量与加大流量。")
        self.changed.emit()

    def values(self):
        """返回当前模式的可计算分母列表，空值和错误必须阻止开始。"""
        if self.mode == "standard":
            return list(STANDARD_SLOPES)
        values, invalid, _ = parse_slope_text(self.editor.toPlainText())
        if invalid:
            raise ValueError("请修正坡度分母：" + "、".join(invalid))
        if not values:
            raise ValueError("请至少填写一个坡度分母，或复制标准 9 档")
        return values

    def criteria(self):
        """读取可选项目条件，未启用时不把预填值用于工程判断。"""
        import math
        if not self.criteria_toggle.isChecked():
            return None, None
        values = []
        for label, edit in (("净空高度", self.height_edit), ("净空面积", self.area_edit)):
            raw = edit.text().strip()
            try:
                value = float(raw) if raw else None
            except ValueError as exc:
                raise ValueError(f"{label}下限必须为非负数，或留空") from exc
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{label}下限必须为非负有限数")
            values.append(value)
        if values[1] is not None and values[1] > 100:
            raise ValueError("净空面积下限不能超过 100%")
        if values == [None, None]:
            raise ValueError("请至少填写一项项目净空条件，或关闭此选项")
        return tuple(values)

    def state(self):
        """序列化模式和所有原始输入，包含未完成或无效输入。"""
        return dict(mode=self.mode, custom_text=self.editor.toPlainText(), roughness=self.n_edit.text(),
                    range_values=[edit.text() for edit in self.range_edits], range_open=self.range_toggle.isChecked(),
                    criteria_enabled=self.criteria_toggle.isChecked(), height=self.height_edit.text(), area=self.area_edit.text())

    def set_state(self, state):
        """恢复保存输入；旧项目没有此区时按默认关闭的标准方案恢复。"""
        state = state or {}
        self._undo_text = None
        self.undo_button.setEnabled(False)
        self.editor.setPlainText(str(state.get("custom_text", "")))
        self.n_edit.setText(str(state.get("roughness", DEFAULT_ROUGHNESS)))
        for edit, value in zip(self.range_edits, state.get("range_values", DEFAULT_RANGE)):
            edit.setText(str(value))
        self.range_toggle.setChecked(bool(state.get("range_open", False)))
        self.height_edit.setText(str(state.get("height", DEFAULT_CLEARANCE_HEIGHT)))
        self.area_edit.setText(str(state.get("area", DEFAULT_CLEARANCE_AREA)))
        self.criteria_toggle.setChecked(bool(state.get("criteria_enabled", False)))
        self.set_mode(state.get("mode", "standard"))
