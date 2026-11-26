"""Whole-route construction sections, surface quantities and saved records."""
from __future__ import annotations
import copy
import json
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QDoubleSpinBox, QMessageBox)

from app_渠系计算前端.task_feedback import TaskFeedbackWidget
from app_渠系计算前端.task_runner import TaskRunner


class NetworkEarthworkPanel(QWidget):
    data_changed = Signal()
    progress_event = Signal(str, float, str)
    _task_progress_event = Signal(int, str, float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.runner = TaskRunner(self)
        self.runner.running_changed.connect(self._busy)
        self.progress_event.connect(self._progress)
        self._task_progress_event.connect(self._task_progress)
        self._network = self._result = self._calculation = None
        self._restoring = False
        layout = QVBoxLayout(self)
        title = QLabel("全线与多结构挖填算量")
        title.setStyleSheet("font-size:21px;font-weight:600;color:#17365D")
        layout.addWidget(title)
        layout.addWidget(QLabel("施工断面与原地形比较挖填面积，沿真实路线积分；断面与逐段积分记录可复核。"))
        self.terrain_path, self.network_path = QLineEdit(), QLineEdit()
        self.choose_buttons = []
        for label, field, callback in (("地形 3DM", self.terrain_path, self.choose_terrain),
                                        ("全线输入 JSON", self.network_path, self.choose_network)):
            row = QHBoxLayout(); row.addWidget(QLabel(label)); row.addWidget(field)
            button = QPushButton("选择"); button.clicked.connect(callback); row.addWidget(button)
            self.choose_buttons.append(button); layout.addLayout(row)
            field.textChanged.connect(self._invalidate)
        self.input_label = QLabel("请读取全线输入；原结构组和连接段均须完整。")
        self.input_label.setWordWrap(True); layout.addWidget(self.input_label)
        settings = QHBoxLayout()
        self.chord = QDoubleSpinBox(); self.chord.setDecimals(3); self.chord.setRange(.001, .5); self.chord.setValue(.04)
        self.step = QDoubleSpinBox(); self.step.setRange(.5, 50); self.step.setValue(20)
        self.tolerance = QDoubleSpinBox(); self.tolerance.setDecimals(3); self.tolerance.setRange(.01, 2); self.tolerance.setValue(1.)
        for label, field in (("断面圆弧弦高容差 m", self.chord), ("初始纵向间距 m", self.step), ("相对收敛差 %", self.tolerance)):
            settings.addWidget(QLabel(label)); settings.addWidget(field); field.valueChanged.connect(self._invalidate)
        layout.addLayout(settings)
        self.summary = QLabel("未生成当前成果"); layout.addWidget(self.summary)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["名称", "类型", "起桩 m", "止桩 m", "挖方 m³", "周边回填 m³", "新增填筑 m³", "总填方 m³"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.calculate_button = QPushButton("计算全线工程量")
        self.calculate_button.clicked.connect(lambda: self._guard(self.start_calculation))
        self.cancel_button = QPushButton("取消"); self.cancel_button.clicked.connect(self.cancel_task); self.cancel_button.setEnabled(False)
        self.export_button = QPushButton("导出当前成果"); self.export_button.setEnabled(False)
        self.export_button.clicked.connect(lambda: self._guard(self.choose_export))
        for button in (self.calculate_button, self.cancel_button, self.export_button): actions.addWidget(button)
        layout.addLayout(actions)
        self.feedback = TaskFeedbackWidget(self)
        self.progress = self.feedback.bar
        layout.addWidget(self.feedback)
        self.messages = QPlainTextEdit(); self.messages.setReadOnly(True); self.messages.setMaximumHeight(155)
        layout.addWidget(self.messages)

    def _guard(self, callback):
        try: callback()
        except Exception as exc: QMessageBox.warning(self, "全线算量", str(exc))

    def _invalidate(self, *_):
        if self._restoring: return
        if self.runner.isRunning():
            self.runner.invalidate()
            self.feedback.stop()
        self._result = self._calculation = None
        self.export_button.setEnabled(False); self.summary.setText("输入已改变，请重新计算")
        self.table.setRowCount(0)
        self.data_changed.emit()

    def choose_terrain(self):
        path, _ = QFileDialog.getOpenFileName(self, "已有地形", "", "Rhino地形 (*.3dm)")
        if path: self.terrain_path.setText(path)

    def choose_network(self):
        path, _ = QFileDialog.getOpenFileName(self, "完整全线输入", "", "全线输入 (*.json)")
        if path: self._guard(lambda: self.load_input(path, background=True))

    def load_input(self, path, *, background=False):
        from 土石方计算.services.network_project import load_network, validate_network_extent
        def read(token, generation):
            token.raise_if_cancelled()
            network, identity = load_network(path)
            token.raise_if_cancelled()
            validate_network_extent(network)
            return network
        def completed(network):
            self.network_path.setText(str(Path(path).resolve()))
            self._display_input(network)
        if background:
            self._submit_task("读取全线输入", "正在读取线路、结构及桩号范围，请稍候。", read,
                              on_success=completed, success_message="全线输入已读取，可以开始计算工程量。",
                              cancel_message="已取消读取全线输入")
        else:
            network, identity = load_network(path)
            validate_network_extent(network)
            completed(network)

    def _display_input(self, network):
        self._network = network
        report = network.get("report", {})
        self.input_label.setText(f"{'测试算例；' if network.get('test_only') else ''}{network.get('name', report.get('case_id', ''))}："
            f"真长 {network['alignment'].total_length:,.3f} m，{len(network['assets'])} 个结构及连接对象。"
            "设计纵断面与施工参数随输入文件保存。")
        self.messages.appendPlainText("全线输入已读取；已核对全部桩号范围。")

    def start_calculation(self):
        from 土石方计算.services.network_project import load_network, validate_network_extent, calculate_network_request
        from 土石方计算.io.independent_terrain import load_terrain
        network_path = self.network_path.text()
        terrain = self.terrain_path.text()
        accuracy = {"chord_tolerance": self.chord.value(), "profile_step": self.step.value(),
                    "relative_tolerance": self.tolerance.value()/100, "absolute_tolerance": 10., "max_refinements": 2}
        self._invalidate()
        def work(token, generation):
            token.raise_if_cancelled()
            network, identity = load_network(network_path)
            token.raise_if_cancelled()
            validate_network_extent(network)
            self._task_progress_event.emit(generation, "terrain", 0., "线路范围已核对，正在读取原地形三角网。")
            tin = load_terrain(terrain, cancelled=lambda: token.is_cancelled)
            result, payload = calculate_network_request(tin, network, accuracy=accuracy, method="sections",
                cancelled=lambda: token.is_cancelled, progress=lambda *args: self._task_progress_event.emit(generation, *args))
            payload["network_file"] = identity
            return result, payload
        self._submit_task("计算全线挖填工程量", "正在核对全线输入和施工参数，随后读取地形并逐断面计算。", work,
                          on_success=self._calculated, success_message="全线工程量计算完成，可以查看和导出成果。",
                          cancel_message="已取消；未发布部分工程量")

    def _calculated(self, value):
        from 土石方计算.io.independent_terrain import file_sha256
        source = value[1].get("network_file", {})
        if source and file_sha256(source["path"]) != source["sha256"]:
            self._failed(ValueError("计算期间全线输入文件已改变，请重新计算"))
            return
        self._calculation, self._result = value
        payload = self._result
        self.summary.setText(("测试算例：" if payload.get("test_only") else "")+"；".join(
            f"{name} {payload[key]:,.3f} m³" for name, key in (("挖方", "excavation_volume"),
            ("周边回填", "backfill_volume"), ("新增填筑", "embankment_volume"), ("总填方", "total_fill_volume"))))
        rows = payload.get("rows", payload.get("assets", [])); self.table.setRowCount(len(rows))
        from 土石方计算.io.network_exporter import structure_label
        for i, row in enumerate(rows):
            for j, key in enumerate(("name", "section_type", "station_start", "station_end", "excavation_volume", "backfill_volume", "embankment_volume", "total_fill_volume")):
                value = row.get(key, "")
                if key == "section_type": value = structure_label(payload, row)
                self.table.setItem(i, j, QTableWidgetItem(f"{value:,.3f}" if isinstance(value, (int, float)) else str(value)))
        self.export_button.setEnabled(True)
        self.messages.appendPlainText("全部结构完成，断面面积、曲线修正及逐段积分收敛记录可随成果导出。")
        self.data_changed.emit()

    def _failed(self, error):
        self.feedback.fail(str(error))
        self._result = self._calculation = None; self.export_button.setEnabled(False)
        self.summary.setText("本次未形成完整成果"); self.messages.appendPlainText(str(error))
        for value in getattr(error, "diagnostics", []): self.messages.appendPlainText(str(value))

    def _busy(self, busy):
        for field in [self.terrain_path, self.network_path, self.chord, self.step, self.tolerance, *self.choose_buttons, self.calculate_button]: field.setEnabled(not busy)
        self.cancel_button.setEnabled(busy); self.export_button.setEnabled(not busy and self._result is not None)
        if not busy:
            self.cancel_button.setText("取消")
            if self.feedback.active:
                self.feedback.stop()

    def _progress(self, stage, fraction, message):
        if not self.feedback.active:
            return
        self.feedback.update_progress(stage, fraction, message)
        self.messages.appendPlainText(message)

    def _task_progress(self, generation, stage, fraction, message):
        if generation == self.feedback.generation:
            self._progress(stage, fraction, message)

    def _submit_task(self, title, message, work, *, on_success, success_message, cancel_message, on_error=None):
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
                               on_error=on_error or self._failed, on_cancelled=cancelled)
        except Exception as exc:
            self.feedback.fail(str(exc))
            raise

    def cancel_task(self):
        if self.runner.isRunning():
            self.feedback.request_cancel()
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("正在取消…")
            self.runner.cancel()

    def choose_export(self):
        path, selected = QFileDialog.getSaveFileName(self, "保存全线成果", "全线工程量_TEST.csv",
            "分项工程量 CSV (*.csv);;逐断面记录 CSV (*.csv);;逐段积分 CSV (*.csv);;完整记录 JSON (*.json);;断面对比 DXF (*.dxf);;地形与断面展示 3DM (*.3dm)")
        table = "sections" if selected.startswith("逐断面") else "segments" if selected.startswith("逐段") else "assets"
        if path: self.export_to(path, table=table)

    def export_to(self, path, *, table="assets"):
        from 土石方计算.io.network_exporter import export_network_result
        from 土石方计算.io.independent_terrain import file_sha256
        if self._result is None: raise ValueError("请先完成全线计算")
        source = self._result.get("network_file", {})
        if source and file_sha256(source["path"]) != source["sha256"]:
            self._invalidate(); raise ValueError("全线输入文件已改变，请重新计算")
        payload, result = copy.deepcopy(self._result), self._calculation
        def save(token, generation):
            if payload.get("method") == "exact_tin_actual_midpoint_section_integration":
                from 土石方计算.io.section_exporter import export_section_result
                return export_section_result(payload, path, result, table=table)
            return export_network_result(payload, path, result)
        self._submit_task("导出全线挖填成果", "正在保存工程量和断面成果，请稍候。", save,
                          on_success=lambda p: self.messages.appendPlainText(f"已保存：{p}"),
                          success_message=f"成果已保存：{path}", cancel_message="已取消导出成果",
                          on_error=self._export_failed)

    def _export_failed(self, error):
        self.feedback.fail(str(error))
        self.messages.appendPlainText(f"导出未完成：{error}。本次已完成的工程量仍保留，可重新导出。")
        self.export_button.setEnabled(self._result is not None)

    def to_project_dict(self):
        return {"schema_version": "1.0", "network_path": self.network_path.text(),
                "terrain_path": self.terrain_path.text(), "chord": self.chord.value(), "step": self.step.value(),
                "tolerance_percent": self.tolerance.value(), "last_result": copy.deepcopy(self._result)}

    def from_project_dict(self, data):
        if not isinstance(data, dict) or data.get("schema_version", "1.0") != "1.0": raise ValueError("全线工程格式不受支持")
        self.runner.invalidate(); self.feedback.stop(); self._restoring = True
        try:
            self.network_path.setText(data.get("network_path", "")); self.terrain_path.setText(data.get("terrain_path", ""))
            self.chord.setValue(data.get("chord", .04)); self.step.setValue(data.get("step", 20))
            self.tolerance.setValue(data.get("tolerance_percent", 1.)); self._result = self._calculation = None
            self.table.setRowCount(0); self.export_button.setEnabled(False)
            self.summary.setText("已恢复输入；历史结果须重新计算后导出")
        finally: self._restoring = False

    def shutdown(self):
        self.runner.invalidate()
        self.feedback.stop()
