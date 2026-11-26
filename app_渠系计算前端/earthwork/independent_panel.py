"""Native terrain meshes and independent quantity calculation, in one workbench."""
from __future__ import annotations
import copy
import csv
import json
import math
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QGroupBox,
    QFileDialog, QMessageBox, QPlainTextEdit, QSplitter, QDialog, QDialogButtonBox)

from app_渠系计算前端.task_feedback import TaskFeedbackWidget
from app_渠系计算前端.task_runner import TaskRunner


def _spin(value, low=-1e8, high=1e8, decimals=3):
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setValue(value)
    return box


class IndependentSlopeDialog(QDialog):
    """Explicit last stage reaches terrain, without invented huge heights."""
    def __init__(self, stages_by_side, parent=None):
        super().__init__(parent)
        self.setWindowTitle("分级放坡与马道")
        self.resize(560, 380)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("按从下到上顺序填写。末级级高留空，表示继续放坡至原地面。"))
        tabs = QTabWidget()
        self.tables = {}
        for side, stages in stages_by_side.items():
            page = QWidget()
            form = QVBoxLayout(page)
            table = QTableWidget(0, 3)
            table.setHorizontalHeaderLabels(["水平坡比", "级高 m（末级可留空）", "顶部马道宽 m"])
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            for stage in stages or [{"ratio": 1, "height": None, "berm_width": 0}]:
                row = table.rowCount()
                table.insertRow(row)
                for column, value in enumerate((stage.get("ratio",stage.get("slope",1)),stage.get("height"),stage.get("berm_width",0))):
                    table.setItem(row,column,QTableWidgetItem("" if value is None else str(value)))
            form.addWidget(table)
            buttons = QHBoxLayout()
            add = QPushButton("增加一级")
            add.clicked.connect(lambda checked=False,t=table: t.insertRow(t.rowCount()))
            remove = QPushButton("删除选中级")
            remove.clicked.connect(lambda checked=False,t=table: t.removeRow(t.currentRow()) if t.currentRow()>=0 else None)
            buttons.addWidget(add); buttons.addWidget(remove)
            form.addLayout(buttons)
            tabs.addTab(page,side)
            self.tables[side] = table
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        try:
            result = {}
            for side,table in self.tables.items():
                stages=[]
                if not table.rowCount():
                    raise ValueError(f"{side}至少需要一级边坡")
                for row in range(table.rowCount()):
                    texts=[table.item(row,c).text().strip() if table.item(row,c) else "" for c in range(3)]
                    ratio,berm=float(texts[0]),float(texts[2] or 0)
                    height=float(texts[1]) if texts[1] else None
                    if not all(math.isfinite(v) and v>=0 for v in (ratio,berm)) or (height is not None and (not math.isfinite(height) or height<=0)):
                        raise ValueError("坡比、级高和马道宽度无效")
                    if height is None and row!=table.rowCount()-1:
                        raise ValueError("仅末级可以留空表示接到原地面")
                    stages.append({"ratio":ratio,"height":height,"berm_width":berm})
                result[side]=stages
            self.stages=result
        except ValueError as error:
            QMessageBox.warning(self,"边坡参数",str(error))
            return
        super().accept()


class IndependentEarthworkPanel(QWidget):
    data_changed = Signal()
    progress_event = Signal(str, float, str)
    _task_progress_event = Signal(int, str, float, str)

    def __init__(self, parent=None, *, terrain_provider=None, assets_provider=None):
        super().__init__(parent)
        self.setObjectName("independentEarthworkPanel")
        self._terrain_provider, self._assets_provider = terrain_provider, assets_provider
        self._tin = None
        self._result = None
        self._result_object = None
        self._asset = None
        self._asset_drafts = {}
        self._restoring = False
        self._saving = False
        self.runner = TaskRunner(self)
        self.runner.running_changed.connect(self._busy)
        self.progress_event.connect(self._progress)
        self._task_progress_event.connect(self._task_progress)
        self._build_ui()

    def _button(self, text, callback, layout):
        button = QPushButton(text)
        button.clicked.connect(lambda: self._guard(callback))
        layout.addWidget(button)
        return button

    def _table(self, headers, rows=0):
        table = QTableWidget(rows, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.itemChanged.connect(self._changed)
        return table

    def _build_ui(self):
        layout = QVBoxLayout(self)
        title = QLabel("独立挖填算量")
        title.setStyleSheet("font-size:21px;font-weight:600;color:#17365D")
        layout.addWidget(title)
        note = QLabel("复用 Rhino 已有地形三角网，保留真实峰谷和折坡。天然挖方、结构回填、新增填筑分别统计。")
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.terrain_path = QLineEdit()
        self.terrain_path.setPlaceholderText("Rhino 地形 3DM / 已有网格 JSON、NPZ、DXF")
        self.terrain_path.textEdited.connect(self._terrain_changed)
        row.addWidget(self.terrain_path, 1)
        row.addWidget(QLabel("网格序号"))
        self.mesh_index = QSpinBox()
        self.mesh_index.setRange(-1, 100000)
        self.mesh_index.setSpecialValueText("自动")
        self.mesh_index.setValue(-1)
        self.mesh_index.setToolTip("单网格可用自动；多网格 3DM 须填写从 0 开始的网格序号。")
        self.mesh_index.valueChanged.connect(self._terrain_changed)
        row.addWidget(self.mesh_index)
        self.load_button = self._button("读取地形网格", self.choose_terrain, row)
        self._button("复用联动页已选地形", self.use_bound_terrain, row)
        layout.addLayout(row)
        self.terrain_label = QLabel("尚未读取地形。等高线、点云先通过 Rhino 原生功能建网。")
        self.terrain_label.setWordWrap(True)
        layout.addWidget(self.terrain_label)
        self.mode_tabs = QTabWidget()
        line_page = QWidget()
        line_layout = QVBoxLayout(line_page)
        row = QHBoxLayout()
        self._button("导入线路表 / 工程数据", self.choose_line, row)
        self._button("读取联动页建筑物", self.use_bound_assets, row)
        self.asset_combo = QComboBox()
        self.asset_combo.currentIndexChanged.connect(self._select_asset)
        row.addWidget(self.asset_combo, 1)
        self.edit_asset_button = self._button("编辑建筑物施工参数", self.edit_asset, row)
        line_layout.addLayout(row)
        self.line_table = self._table(["桩号 m", "X m", "Y m", "设计底 / 管轴高程 m"], 2)
        line_layout.addWidget(self.line_table)
        row = QHBoxLayout()
        self._button("增加点", lambda: self.line_table.insertRow(self.line_table.rowCount()), row)
        self._button("删除选中点", self.delete_line_row, row)
        self._button("按折线长度生成桩号", self.derive_stations, row)
        self.polyline_declared = QCheckBox("明确采用表中单一直线段")
        self.polyline_declared.setChecked(True)
        self.polyline_declared.toggled.connect(self._changed)
        row.addWidget(self.polyline_declared)
        line_layout.addLayout(row)
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("计算断面来源"))
        self.section_source = QComboBox()
        self.section_source.addItem("手工开挖断面", "manual")
        self.section_source.addItem("选中建筑物的施工参数", "asset")
        self.section_source.currentIndexChanged.connect(self._changed)
        source_row.addWidget(self.section_source, 1)
        line_layout.addLayout(source_row)
        self.line_note = QLabel("提供实际设计底或管轴高程。当前按单一直线段算量；转弯、回折和交叉开挖须另按施工边界处理。")
        self.line_note.setWordWrap(True)
        line_layout.addWidget(self.line_note)
        parameters = self.manual_parameters = QGroupBox("手工施工开挖断面（尺寸已含施工所需空间）")
        form = QFormLayout(parameters)
        self.manual_parameter_form = form
        self.section_type = QComboBox()
        self.section_type.addItem("矩形沟槽底面", "rectangular_trench")
        self.section_type.addItem("梯形开挖断面", "trapezoidal_channel")
        self.bottom_width, self.section_height = _spin(2, .01), _spin(2, .01)
        self.inner_left, self.inner_right = _spin(1.5, 0), _spin(1.5, 0)
        self.outer_left, self.outer_right = _spin(1, 0), _spin(1, 0)
        for label, field in (("开挖底宽 m", self.bottom_width), ("梯形断面高度 m", self.section_height),
                             ("梯形左侧水平坡比", self.inner_left), ("梯形右侧水平坡比", self.inner_right),
                             ("向原地面接坡：左水平比", self.outer_left), ("向原地面接坡：右水平比", self.outer_right)):
            form.addRow(label, field)
            field.valueChanged.connect(self._changed)
        form.insertRow(0, "施工断面", self.section_type)
        self.section_type.currentIndexChanged.connect(self._changed)
        row = QHBoxLayout()
        self.linear_multistage = QCheckBox("采用分级边坡")
        self.linear_multistage.toggled.connect(self._changed)
        row.addWidget(self.linear_multistage)
        self.linear_grades_button = self._button("设置分级边坡 / 马道", self.edit_linear_grades, row)
        form.addRow(row)
        self.linear_grades = None
        line_layout.addWidget(parameters)
        self.mode_tabs.addTab(line_page, "渠道 / 管沟")
        site_page = QWidget()
        site_layout = QVBoxLayout(site_page)
        row = QHBoxLayout()
        self._button("导入坑底边界 CSV / DXF", self.choose_site, row)
        self._button("增加边界点", lambda: self.site_table.insertRow(self.site_table.rowCount()), row)
        self._button("删除边界点", self.delete_site_row, row)
        site_layout.addLayout(row)
        self.site_table = self._table(["坑底边界 X m", "坑底边界 Y m"], 4)
        site_layout.addWidget(self.site_table)
        site_form = QFormLayout()
        self.bottom_elevation = _spin(0)
        self.site_ratio = _spin(1, 0)
        site_form.addRow("施工坑底标高 m", self.bottom_elevation)
        site_form.addRow("单级开挖水平坡比", self.site_ratio)
        self.bottom_elevation.valueChanged.connect(self._changed)
        self.site_ratio.valueChanged.connect(self._changed)
        site_layout.addLayout(site_form)
        row = QHBoxLayout()
        self.site_multistage = QCheckBox("采用分级边坡")
        self.site_multistage.toggled.connect(self._changed)
        row.addWidget(self.site_multistage)
        self.site_grades_button = self._button("设置分级放坡 / 马道", self.edit_site_grades, row)
        self.site_grades = None
        self.site_holes = []
        site_layout.addLayout(row)
        site_note = QLabel("输入施工坑底边界；程序按坡比、马道与真实地形计算开挖范围。带孔洞边界可从闭合 DXF 或工程文件读入。")
        site_note.setWordWrap(True)
        site_layout.addWidget(site_note)
        self.mode_tabs.addTab(site_page, "基坑 / 场地")
        self.mode_tabs.currentChanged.connect(self._changed)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.mode_tabs)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.result_label = QLabel("尚无当前计算结果")
        self.result_label.setWordWrap(True)
        right_layout.addWidget(self.result_label)
        self.result_table = QTableWidget(0, 5)
        self.result_table.setColumnCount(8)
        self.result_table.setHorizontalHeaderLabels(["起桩", "止桩", "长度", "挖方 m³", "周边回填 m³", "新增填筑 m³", "总填方 m³", "差分填方 m³"])
        self.result_table.horizontalHeaderItem(7).setToolTip("设计面差分填方；结构周边回填和新增填筑分别列示")
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.result_table.itemSelectionChanged.connect(self.show_section)
        right_layout.addWidget(self.result_table, 1)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        self.figure = Figure(figsize=(5, 3), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumHeight(220)
        right_layout.addWidget(self.canvas, 1)
        splitter.addWidget(right)
        splitter.setSizes([550, 600])
        layout.addWidget(splitter, 1)
        row = QHBoxLayout()
        self.test_only = QCheckBox("试验参数（成果标记为示例）")
        self.test_only.toggled.connect(self._changed)
        row.addWidget(self.test_only)
        row.addWidget(QLabel("初始断面间距 m"))
        self.interval = _spin(20, .01)
        row.addWidget(self.interval)
        row.addWidget(QLabel("左右地形搜索宽度 m"))
        self.search_width = _spin(30, .1)
        row.addWidget(self.search_width)
        row.addWidget(QLabel("相对收敛差 %"))
        self.tolerance = _spin(.1, .00001, 10, 5)
        row.addWidget(self.tolerance)
        for field in (self.interval, self.search_width, self.tolerance):
            field.valueChanged.connect(self._changed)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.calculate_button = self._button("计算工程量", self.start_calculation, row)
        self.cancel_button = self._button("取消", self.cancel_task, row)
        self.export_button = self._button("导出量表 / 断面图 / 计算记录", self.choose_export, row)
        self._button("保存独立工程", self.save_project, row)
        self._button("打开独立工程", self.open_project, row)
        layout.addLayout(row)
        self.feedback = TaskFeedbackWidget(self)
        self.progress = self.feedback.bar
        layout.addWidget(self.feedback)
        self.messages = QPlainTextEdit()
        self.messages.setReadOnly(True)
        self.messages.setMaximumHeight(80)
        layout.addWidget(self.messages)
        self._busy(False)

    def _uses_asset(self):
        return self.section_source.currentData() == "asset" and self._asset is not None

    def _refresh_input_controls(self):
        """Every editable control must belong to the current quantity input."""
        if not hasattr(self, "site_multistage"):
            return
        has_asset = self._asset is not None
        self.section_source.model().item(self.section_source.findData("asset")).setEnabled(has_asset)
        if not has_asset and self.section_source.currentData() == "asset":
            self.section_source.blockSignals(True)
            self.section_source.setCurrentIndex(self.section_source.findData("manual"))
            self.section_source.blockSignals(False)
        manual = not self._uses_asset()
        self.manual_parameters.setEnabled(manual)
        self.edit_asset_button.setEnabled(self._uses_asset() and not self.runner.isRunning())
        trapezoidal = self.section_type.currentData() == "trapezoidal_channel"
        for field in (self.section_height, self.inner_left, self.inner_right):
            field.setEnabled(trapezoidal)
            self.manual_parameter_form.labelForField(field).setEnabled(trapezoidal)
            field.setToolTip("梯形断面使用此参数" if trapezoidal else "矩形底面不使用此参数，开挖深度由地形和线路底高程确定")
        layered = self.linear_multistage.isChecked()
        for field in (self.outer_left, self.outer_right):
            field.setEnabled(not layered)
            self.manual_parameter_form.labelForField(field).setEnabled(not layered)
            field.setToolTip("已采用分级列表；取消‘采用分级边坡’后可用单级坡比" if layered else "单级接地边坡的水平量 / 竖向量")
        self.site_ratio.setEnabled(not self.site_multistage.isChecked())
        self.site_ratio.setToolTip("取消‘采用分级边坡’后可修改单级坡比" if self.site_multistage.isChecked() else "单级开挖水平坡比")
        if not manual:
            self.line_note.setText(f"当前采用「{self._asset.get('name', '建筑物')}」的结构与施工参数。下方手工尺寸不参与；"
                                   "请点击‘编辑建筑物施工参数’，或将计算断面来源切换为手工。")
        else:
            shape = "梯形断面：高度和左右坡比有效" if trapezoidal else "矩形底面：梯形高度及左右坡比不参与"
            slope = "分级边坡列表" if layered else "下方单级接地坡比"
            self.line_note.setText(f"当前采用手工{shape}；接坡采用{slope}。表中高程为施工开挖底高程，实际开挖深度由原地面确定。")
        header = "设计底 / 管轴高程 m" if self._uses_asset() else "施工开挖底高程 m"
        self.line_table.horizontalHeaderItem(3).setText(header)

    def _guard(self, callback):
        try:
            callback()
        except Exception as exc:
            self.messages.appendPlainText(str(exc))
            QMessageBox.warning(self, "挖填算量", str(exc))

    def _changed(self, *args):
        if self._restoring:
            return
        self._refresh_input_controls()
        if self.runner.isRunning():
            self.runner.invalidate()
            self.feedback.stop()
        self._result = self._result_object = None
        self.result_table.setRowCount(0)
        self.result_label.setText("输入已改变，请重新计算")
        self.export_button.setEnabled(False)
        self.figure.clear()
        self.canvas.draw_idle()
        self.data_changed.emit()

    def _terrain_changed(self, *args):
        self._tin = None
        self._changed()
        self.terrain_label.setText("地形选择已改变，请重新读取网格")

    def _busy(self, busy):
        self.mode_tabs.setEnabled(not busy)
        self.terrain_path.setEnabled(not busy)
        self.mesh_index.setEnabled(not busy)
        self.test_only.setEnabled(not busy)
        for field in (self.interval, self.search_width, self.tolerance):
            field.setEnabled(not busy)
        for button in self.findChildren(QPushButton):
            button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy and not self._saving)
        if not busy:
            self._saving = False
            self.cancel_button.setText("取消")
            if self.feedback.active:
                self.feedback.stop()
        self.export_button.setEnabled(not busy and self._result is not None and self._tin is not None)
        self._refresh_input_controls()

    def _progress(self, stage, fraction, message):
        if not self.feedback.active:
            return
        self.feedback.update_progress(stage, fraction, message)
        self.result_label.setText(message)

    def _task_progress(self, generation, stage, fraction, message):
        if generation == self.feedback.generation:
            self._progress(stage, fraction, message)

    def _submit_task(self, title, message, work, *, on_success, success_message, cancel_message):
        if self.runner.isRunning():
            raise ValueError("上一项任务尚未结束")
        generation = self.feedback.start(title, message)
        def completed(value):
            on_success(value)
            if self.feedback.active:
                self.feedback.succeed(success_message)
        def cancelled():
            self.feedback.cancelled(cancel_message)
            self.messages.appendPlainText(cancel_message)
        try:
            self.runner.submit(lambda token: work(token, generation), on_success=completed,
                               on_error=self._failed, on_cancelled=cancelled)
        except Exception as exc:
            self.feedback.fail(str(exc))
            raise

    def cancel_task(self):
        if self.runner.isRunning() and not self._saving:
            self.feedback.request_cancel()
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("正在取消…")
            self.runner.cancel()

    def choose_terrain(self):
        path, _ = QFileDialog.getOpenFileName(self, "读取已有地形网格", "", "地形网格 (*.3dm *.json *.npz *.dxf)")
        if path:
            self.load_terrain(path)

    def load_terrain(self, path, *, mesh_index=None):
        from 土石方计算.io.independent_terrain import load_terrain
        if mesh_index is not None:
            self.mesh_index.setValue(mesh_index)
        selected = self.mesh_index.value()
        selected = selected if selected >= 0 else None
        self.terrain_path.setText(str(path))
        self._terrain_changed()
        self._submit_task("读取地形", "正在读取地形三角网并核对原文件，较大地形需要一些时间。",
                          lambda token, generation: load_terrain(path, mesh_index=selected, cancelled=lambda: token.is_cancelled),
                          on_success=self._terrain_ready, success_message="地形已就绪，可以开始计算工程量。",
                          cancel_message="已取消读取地形")

    def _terrain_ready(self, tin):
        self._tin = tin
        info = tin.import_report
        low, high = info["bounds"]
        self.terrain_label.setText(f"已读取 {info['vertex_count']:,} 顶点 / {info['face_count']:,} 三角面；"
                                  f"高程 {low[2]:.3f}～{high[2]:.3f} m；保留原网格。")
        self.messages.appendPlainText("地形已就绪，可输入实际设计高程和施工参数。")
        self.data_changed.emit()

    def use_bound_terrain(self):
        terrain = self._terrain_provider() if self._terrain_provider else None
        if not terrain or not terrain.get("mesh_path"):
            raise ValueError("请先在 Rhino 联动页选取地形，或读取已有地形 3DM")
        index = terrain.get("mesh_index")
        self.mesh_index.setValue(-1 if index is None else int(index))
        self.load_terrain(terrain["mesh_path"])

    def _rows(self, table):
        rows = []
        for index in range(table.rowCount()):
            texts = [table.item(index, col).text().strip() if table.item(index, col) else "" for col in range(table.columnCount())]
            if not any(texts):
                continue
            if not all(texts):
                raise ValueError(f"第 {index+1} 行有缺项，请补齐坐标及设计高程")
            values = list(map(float, texts))
            if not all(math.isfinite(v) for v in values):
                raise ValueError(f"第 {index+1} 行含无效数值")
            rows.append(values)
        return rows

    def _set_rows(self, table, rows):
        table.blockSignals(True)
        try:
            table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                for j, value in enumerate(row):
                    table.setItem(i, j, QTableWidgetItem("" if value is None else str(value)))
        finally:
            table.blockSignals(False)

    def delete_line_row(self):
        if self.line_table.currentRow() >= 0:
            self.line_table.removeRow(self.line_table.currentRow())
            self._changed()

    def delete_site_row(self):
        if self.site_table.currentRow() >= 0:
            self.site_table.removeRow(self.site_table.currentRow())
            self._changed()

    def derive_stations(self):
        distance, previous = 0.0, None
        for row in range(self.line_table.rowCount()):
            x, y = [float(self.line_table.item(row, col).text()) for col in (1, 2)]
            if previous:
                distance += math.hypot(x-previous[0], y-previous[1])
            self.line_table.setItem(row, 0, QTableWidgetItem(str(distance)))
            previous = x, y

    def choose_line(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入线路", "", "线路或工程 (*.csv *.xlsx *.json)")
        if path:
            self.import_line(path)

    def import_line(self, path):
        path = Path(path)
        if path.suffix.lower() == ".xlsx":
            from 土石方计算.adapters.source_adapters import load_batch_sample
            converted = load_batch_sample(path)
            self.set_assets(converted["assets"])
            for issue in converted.get("issues", []):
                self.messages.appendPlainText(issue["message"])
        elif path.suffix.lower() == ".json":
            values = json.loads(path.read_text(encoding="utf-8-sig"))
            self.set_assets(values.get("assets", [values] if "asset_id" in values else []))
        else:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream))
            try:
                float(rows[0][0])
            except (ValueError, IndexError):
                rows = rows[1:]
            self._asset = None
            self.asset_combo.clear()
            self.section_source.setCurrentIndex(self.section_source.findData("manual"))
            self._set_rows(self.line_table, [list(map(float, row[:4])) for row in rows if any(row)])
            self.polyline_declared.setChecked(True)
            self._changed()

    def use_bound_assets(self):
        assets = self._assets_provider() if self._assets_provider else []
        if not assets:
            raise ValueError("请在联动页导入线路或读取当前工程，再复用其建筑物参数")
        self.set_assets(assets)

    def set_assets(self, assets):
        self._asset_drafts = {}
        self._asset = None
        self.asset_combo.blockSignals(True)
        self.asset_combo.clear()
        for asset in assets:
            self.asset_combo.addItem(asset.get("name", asset.get("asset_id", "建筑物")), copy.deepcopy(asset))
        self.asset_combo.blockSignals(False)
        if assets:
            self._select_asset(0)
        else:
            self._set_rows(self.line_table, [[None]*4,[None]*4])
            self._changed()

    def _remember_asset_rows(self):
        if self._asset:
            self._asset_drafts[str(self._asset.get("asset_id",self._asset.get("name","")))] = {
                "rows": [[self.line_table.item(r,c).text() if self.line_table.item(r,c) else ""
                          for c in range(4)] for r in range(self.line_table.rowCount())],
                "polyline_declared": self.polyline_declared.isChecked()}

    def _select_asset(self, index):
        asset = self.asset_combo.itemData(index)
        if not asset:
            return
        self._remember_asset_rows()
        self._asset = copy.deepcopy(asset)
        self.section_source.setCurrentIndex(self.section_source.findData("asset"))
        alignment = asset.get("alignment", {})
        profiles = {p["station"]: p["elevation"] for p in alignment.get("profile_points", [])}
        rows = [[p.get("station"), p.get("x"), p.get("y"), profiles.get(p.get("station"))]
                for p in alignment.get("plan_points", [])]
        draft = self._asset_drafts.get(str(asset.get("asset_id",asset.get("name",""))), {})
        self._set_rows(self.line_table, draft.get("rows", rows))
        has_curves = any(p.get("turn_radius", 0) for p in alignment.get("plan_points", []))
        self.polyline_declared.setChecked(draft.get("polyline_declared",not has_curves and not alignment.get("native_samples")))
        self._changed()

    def edit_asset(self):
        if not self._asset:
            raise ValueError("请先读取建筑物参数；手工沟槽使用下方施工断面尺寸")
        from .panel import ParameterDialog
        dialog = ParameterDialog(self._asset, self)
        if dialog.exec() == QDialog.Accepted:
            self._asset = dialog.asset
            self.asset_combo.setItemData(self.asset_combo.currentIndex(), copy.deepcopy(self._asset))
            self._changed()

    def edit_linear_grades(self):
        values = self.linear_grades or {}
        dialog = IndependentSlopeDialog({"左侧":values.get("excavation_stages_left") or [{"ratio":self.outer_left.value(),"height":None}],
                                         "右侧":values.get("excavation_stages_right") or [{"ratio":self.outer_right.value(),"height":None}]},self)
        if dialog.exec() == QDialog.Accepted:
            self.linear_grades = {"excavation_stages_left":copy.deepcopy(dialog.stages["左侧"]),
                                  "excavation_stages_right":copy.deepcopy(dialog.stages["右侧"])}
            self.linear_multistage.setChecked(True)
            self.messages.appendPlainText("已采用分级边坡；取消勾选‘采用分级边坡’可返回单级左右坡比。")
            self._changed()

    def edit_site_grades(self):
        dialog = IndependentSlopeDialog({"基坑周边":self.site_grades or [{"ratio":self.site_ratio.value(),"height":None}]},self)
        if dialog.exec() == QDialog.Accepted:
            self.site_grades = copy.deepcopy(dialog.stages["基坑周边"])
            self.site_multistage.setChecked(True)
            self.messages.appendPlainText("已采用基坑分级边坡；取消勾选‘采用分级边坡’可返回单级坡比。")
            self._changed()

    def choose_site(self):
        path, _ = QFileDialog.getOpenFileName(self, "读取闭合坑底边界", "", "边界 (*.csv *.dxf)")
        if not path:
            return
        if Path(path).suffix.lower() == ".dxf":
            import ezdxf
            from shapely.geometry import Polygon
            lines = list(ezdxf.readfile(path).modelspace().query("LWPOLYLINE"))
            polygons = [Polygon([(p[0], p[1]) for p in line.get_points()]) for line in lines if line.closed]
            if not polygons or any(not p.is_valid for p in polygons):
                raise ValueError("请提供有效的闭合坑底边界")
            outer = max(polygons, key=lambda p: p.area)
            if any(not outer.covers(p) for p in polygons):
                raise ValueError("多个独立坑底请分别计算；同一边界内部闭合线可作为排除孔洞")
            self.site_holes = [list(p.exterior.coords) for p in polygons if p is not outer]
            rows = list(outer.exterior.coords)[:-1]
        else:
            with Path(path).open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream))
            try:
                float(rows[0][0])
            except (ValueError, IndexError):
                rows = rows[1:]
            rows = [list(map(float, row[:2])) for row in rows if any(row)]
            self.site_holes = []
        self._set_rows(self.site_table, rows)
        self._changed()

    def inputs(self):
        accuracy = {"initial_interval": self.interval.value(), "relative_tolerance": self.tolerance.value()/100,
                    "absolute_tolerance": .1, "max_refinements": 10}
        if self.mode_tabs.currentIndex() == 1:
            if self.site_multistage.isChecked() and not self.site_grades:
                raise ValueError("请先设置基坑分级边坡，或取消勾选使用单级坡比")
            return {"mode": "site", "test_only":self.test_only.isChecked(), "site_boundary": self._rows(self.site_table), "site_holes": self.site_holes,
                    "bottom_elevation": self.bottom_elevation.value(), "accuracy": accuracy,
                    "site_grades": self.site_grades if self.site_multistage.isChecked() else [{"ratio": self.site_ratio.value(), "height": None, "berm_width": 0}]}
        rows = self._rows(self.line_table)
        widths = {"left_width": self.search_width.value(), "right_width": self.search_width.value()}
        if self._uses_asset():
            asset = copy.deepcopy(self._asset)
            if self.polyline_declared.isChecked():
                asset["alignment"] = {"plan_points": [{"station": s, "x": x, "y": y} for s, x, y, z in rows],
                                      "profile_points": [{"station": s, "elevation": z} for s, x, y, z in rows],
                                      "plan_geometry": "explicit_polyline", "station_basis": "user_defined",
                                      "elevation_reference": self._asset.get("alignment", {}).get("elevation_reference", "inner_invert")}
                asset.pop("geometry_sections", None)
            return {"mode": "asset", "test_only":self.test_only.isChecked(), "asset": asset, "accuracy": accuracy, **widths}
        if not self.polyline_declared.isChecked():
            raise ValueError("请明确单一直线段的坐标与设计高程")
        if self.linear_multistage.isChecked() and (not isinstance(self.linear_grades, dict)
                or any(not self.linear_grades.get(key) for key in ("excavation_stages_left", "excavation_stages_right"))):
            raise ValueError("请先设置左右两侧分级边坡，或取消勾选使用单级坡比")
        grades = (self.linear_grades or {}) if self.linear_multistage.isChecked() else {}
        section = {"section_type": self.section_type.currentData(), "bottom_width": self.bottom_width.value()}
        if section["section_type"] == "trapezoidal_channel":
            section.update(height=self.section_height.value(), left_ratio=self.inner_left.value(), right_ratio=self.inner_right.value())
        return {"mode": "linear", "test_only":self.test_only.isChecked(), "line_rows": rows, "accuracy": accuracy, **widths,
                "section": section,
                "left_grades": grades.get("excavation_stages_left") or [{"ratio": self.outer_left.value(), "height": None, "berm_width": 0}],
                "right_grades": grades.get("excavation_stages_right") or [{"ratio": self.outer_right.value(), "height": None, "berm_width": 0}]}

    def start_calculation(self):
        if self._tin is None:
            raise ValueError("请先读取现成的地形三角网")
        inputs, tin = self.inputs(), self._tin
        self._changed()
        from 土石方计算.services.independent_project import calculate_request
        from 土石方计算.io.independent_terrain import file_sha256
        def work(token, generation):
            cancelled = lambda: token.is_cancelled
            if file_sha256(tin.import_report["path"], cancelled) != tin.import_report["source_sha256"]:
                raise ValueError("原地形文件已改变，请重新读取")
            return calculate_request(tin, inputs, cancelled=cancelled,
                progress=lambda *args: self._task_progress_event.emit(generation, *args))
        self._submit_task("计算挖填工程量", "正在核对地形文件和施工参数，随后逐断面计算挖填量。", work,
                          on_success=self._calculated, success_message="挖填工程量计算完成，可以查看和导出成果。",
                          cancel_message="已取消计算；未发布部分工程量")

    def _calculated(self, value):
        payload = value[1]
        if not isinstance(payload, dict) or payload.get("status") != "READY" or payload.get("converged") is not True:
            raise ValueError("本次计算尚未通过完整收敛校核，未发布工程量；请核对输入后重新计算。")
        self._result_object, self._result = value
        self._display_result()
        self.messages.appendPlainText("计算已收敛；结果绑定当前地形和施工输入。")
        self.data_changed.emit()

    def _display_result(self):
        payload = self._result
        if not payload:
            return
        labels = []
        for label, key in (("挖方", "excavation_volume"), ("周边回填", "backfill_volume"),
                           ("新增填筑", "embankment_volume"), ("总填方", "total_fill_volume"), ("设计面差分填方", "surface_fill_volume")):
            if payload.get(key) is not None:
                labels.append(f"{label} {payload[key]:,.3f} m³")
        self.result_label.setText(("算法验收示例：" if payload.get("test_only") else "")+"；".join(labels))
        segments = payload.get("segments", [])
        self.result_table.setRowCount(len(segments))
        for row, segment in enumerate(segments):
            backfill, embankment = segment.get("backfill_volume"), segment.get("embankment_volume")
            total_fill = None if backfill is None or embankment is None else backfill+embankment
            values = [segment.get("station_start"), segment.get("station_end"), segment.get("length"),
                      segment.get("excavation_volume", segment.get("excavation_prismatoid")),
                      backfill, embankment, total_fill, segment.get("surface_fill_volume")]
            for column, value in enumerate(values):
                self.result_table.setItem(row, column, QTableWidgetItem("不适用" if value is None else f"{value:.3f}"))
        self.export_button.setEnabled(True)
        if segments:
            self.result_table.selectRow(0)
        else:
            self.show_section()

    def show_section(self):
        self.figure.clear()
        if not self._result:
            self.canvas.draw_idle()
            return
        axes = self.figure.add_subplot(111)
        if self._result.get("kind") == "site":
            from shapely.geometry import shape
            for key, color in (("bottom_boundary", "#17365D"), ("calculation_boundary", "#C0392B")):
                if self._result.get(key):
                    region = shape(self._result[key])
                    for part in ([region] if region.geom_type == "Polygon" else region.geoms):
                        for ring in [part.exterior, *part.interiors]:
                            x, y = ring.xy
                            axes.plot(x, y, color=color)
            axes.set_aspect("equal", adjustable="datalim")
            axes.set_xlabel("X (m)"); axes.set_ylabel("Y (m)")
        else:
            sections = self._result.get("sections", [])
            if sections:
                section = sections[min(max(self.result_table.currentRow(), 0), len(sections)-1)]
                from shapely.geometry import shape
                from matplotlib.path import Path as PlotPath
                from matplotlib.patches import PathPatch
                from shapely.geometry.polygon import orient
                regions = section.get("construction_regions") or {}
                for key, color, label in (("excavation", "#E8A9A3", "天然开挖"),
                                           ("backfill", "#F0C66A", "结构周边回填"),
                                           ("embankment", "#90BCE0", "新增填筑"),
                                           ("excluded_occupancy", "#B9BEC5", "结构及另列材料占位")):
                    if not regions.get(key):
                        continue
                    geometry = shape(regions[key])
                    parts = [geometry] if geometry.geom_type == "Polygon" else geometry.geoms
                    for index, part in enumerate(parts):
                        if part.is_empty or part.geom_type != "Polygon":
                            continue
                        vertices, codes = [], []
                        for ring in [orient(part).exterior, *orient(part).interiors]:
                            coords = list(ring.coords)
                            vertices.extend(coords)
                            codes.extend([PlotPath.MOVETO]+[PlotPath.LINETO]*(len(coords)-2)+[PlotPath.CLOSEPOLY])
                        axes.add_patch(PathPatch(PlotPath(vertices, codes), facecolor=color,
                                                 edgecolor=color, alpha=0.55, label=label if index == 0 else None))
                for key, color, label in (("ground_points", "#238B45", "原地面"), ("design_points", "#C0392B", "开挖线"),
                                          ("excavation_boundary", "#C0392B", None)):
                    points = section.get(key, [])
                    if points:
                        axes.plot([p[0] for p in points], [float("nan") if p[1] is None else p[1] for p in points], color=color, label=label)
                axes.set_title(f"桩号 {section['station']:.3f} m",fontfamily="Microsoft YaHei")
                axes.set_xlabel("偏距 (m)",fontfamily="Microsoft YaHei"); axes.set_ylabel("高程 (m)",fontfamily="Microsoft YaHei")
                axes.legend(prop={"family":"Microsoft YaHei"})
        axes.grid(True, alpha=.25)
        self.canvas.draw_idle()

    def _failed(self, error):
        self.feedback.fail(str(error))
        self._result = self._result_object = None
        self.result_table.setRowCount(0)
        self.figure.clear()
        self.canvas.draw_idle()
        self.export_button.setEnabled(False)
        self.result_label.setText("未生成有效结果")
        self.messages.appendPlainText(str(error))
        for item in getattr(error, "diagnostics", []):
            self.messages.appendPlainText(str(item))

    def choose_export(self):
        if not self._result:
            raise ValueError("请先完成当前计算")
        path, _ = QFileDialog.getSaveFileName(self, "导出成果", "独立挖填工程量.xlsx", "Excel (*.xlsx);;CSV (*.csv);;断面与边界 DXF (*.dxf);;Rhino 校核模型 (*.3dm);;完整计算记录 (*.json)")
        if path:
            self.export_to(path)

    def export_to(self, path):
        from 土石方计算.io.independent_exporter import export_result
        from 土石方计算.io.independent_terrain import file_sha256
        from 土石方计算.services.independent_project import input_hash, terrain_identity
        if not self._result or self._tin is None:
            raise ValueError("请先读取地形并完成当前计算")
        payload = copy.deepcopy(self._result)
        if input_hash(self.inputs(), terrain_identity(self._tin.import_report)) != payload["input_hash"]:
            raise ValueError("输入已改变，请重算后导出")
        def work(token, generation):
            if file_sha256(payload["terrain"]["path"], lambda: token.is_cancelled) != payload["terrain"]["source_sha256"]:
                raise ValueError("地形文件已改变，请重算后导出")
            token.raise_if_cancelled()
            return export_result(payload, path)
        self._saving = True
        try:
            self._submit_task("导出挖填成果", "正在核对来源并保存成果，请稍候。", work,
                              on_success=lambda p: self.messages.appendPlainText(f"已保存：{p}"),
                              success_message=f"成果已保存：{path}", cancel_message="已取消导出成果")
        except Exception:
            self._saving = False
            raise

    def to_project_dict(self):
        # Preserve incomplete editable rows without promoting them to valid inputs.
        rows = lambda table: [[table.item(r,c).text() if table.item(r,c) else "" for c in range(table.columnCount())]
                              for r in range(table.rowCount())]
        self._remember_asset_rows()
        return {"schema_version": "1.0", "terrain_path": self.terrain_path.text(), "mode": self.mode_tabs.currentIndex(),
                "section_source": self.section_source.currentData(),
                "use_linear_grades": self.linear_multistage.isChecked(), "use_site_grades": self.site_multistage.isChecked(),
                "mesh_index": self.mesh_index.value(),
                "test_only":self.test_only.isChecked(),
                "line_rows": rows(self.line_table), "site_rows": rows(self.site_table), "asset": copy.deepcopy(self._asset),
                "assets": [copy.deepcopy(self.asset_combo.itemData(i)) for i in range(self.asset_combo.count())],
                "selected_asset_index": self.asset_combo.currentIndex(),
                "asset_drafts": copy.deepcopy(self._asset_drafts),
                "site_holes": copy.deepcopy(self.site_holes), "linear_grades": copy.deepcopy(self.linear_grades),
                "site_grades": copy.deepcopy(self.site_grades), "polyline_declared": self.polyline_declared.isChecked(),
                "values": {name: getattr(self, name).value() for name in ("bottom_width", "section_height", "inner_left", "inner_right",
                           "outer_left", "outer_right", "bottom_elevation", "site_ratio", "interval", "search_width", "tolerance")},
                "section_type": self.section_type.currentData(), "last_result": copy.deepcopy(self._result)}

    def from_project_dict(self, data):
        if not isinstance(data, dict) or data.get("schema_version", "1.0") != "1.0":
            raise ValueError("独立算量工程格式不受支持")
        from .project_state import validate_independent_modes
        validate_independent_modes(data)
        self.runner.invalidate()
        self.feedback.stop()
        self._restoring = True
        try:
            self._tin = None
            self._result_object = None
            self.terrain_path.setText(data.get("terrain_path", ""))
            self.mesh_index.setValue(int(data.get("mesh_index", -1)))
            self.mode_tabs.setCurrentIndex(int(data.get("mode", 0)))
            self.test_only.setChecked(bool(data.get("test_only",False)))
            self._set_rows(self.line_table, data.get("line_rows", [["", "", "", ""], ["", "", "", ""]]))
            self._set_rows(self.site_table, data.get("site_rows", [["", ""]]*4))
            self._asset = copy.deepcopy(data.get("asset"))
            self._asset_drafts = copy.deepcopy(data.get("asset_drafts", {}))
            self.asset_combo.blockSignals(True)
            self.asset_combo.clear()
            assets = data.get("assets") or ([self._asset] if self._asset else [])
            for asset in assets:
                self.asset_combo.addItem(asset.get("name", "建筑物"), copy.deepcopy(asset))
            self.asset_combo.setCurrentIndex(min(max(int(data.get("selected_asset_index",0)),0),len(assets)-1))
            self.asset_combo.blockSignals(False)
            if self._asset is None and self.asset_combo.currentData():
                self._asset = copy.deepcopy(self.asset_combo.currentData())
            self.site_holes = copy.deepcopy(data.get("site_holes", []))
            self.linear_grades, self.site_grades = data.get("linear_grades"), data.get("site_grades")
            self.linear_multistage.setChecked(bool(data.get("use_linear_grades", self.linear_grades)))
            self.site_multistage.setChecked(bool(data.get("use_site_grades", self.site_grades)))
            source = data.get("section_source", "asset" if self._asset else "manual")
            if source not in ("manual", "asset"):
                raise ValueError("未知计算断面来源")
            self.section_source.setCurrentIndex(self.section_source.findData(source))
            self.polyline_declared.setChecked(data.get("polyline_declared", True))
            for name, value in data.get("values", {}).items():
                if hasattr(self, name) and isinstance(getattr(self, name), QDoubleSpinBox):
                    getattr(self, name).setValue(float(value))
            self.section_type.setCurrentIndex(max(0, self.section_type.findData(data.get("section_type", "rectangular_trench"))))
            self._result = copy.deepcopy(data.get("last_result"))
            self.result_table.setRowCount(0)
            self.figure.clear()
            if self._result:
                self._display_result()
                self.result_label.setText(self.result_label.text()+"（历史结果，重读地形并重算后可导出）")
            else:
                self.result_label.setText("请读取地形并计算")
            self.export_button.setEnabled(False)
            self.terrain_label.setText("请重读地形，以核对工程保存时的文件身份")
        finally:
            self._restoring = False
            self._refresh_input_controls()

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存独立工程", "独立挖填工程.json", "工程数据 (*.json)")
        if path:
            from atomic_json import atomic_write_json
            atomic_write_json(path, self.to_project_dict())

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开独立工程", "", "工程数据 (*.json)")
        if path:
            self.from_project_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))
            self.data_changed.emit()

    def shutdown(self):
        self.runner.invalidate()
        self.feedback.stop()
