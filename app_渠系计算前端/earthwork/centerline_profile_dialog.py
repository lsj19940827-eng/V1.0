"""沿已有平面轴线独立剖纵断面；工程量快照不参与此流程。"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableView, QTabWidget,
    QVBoxLayout, QWidget)

from app_渠系计算前端.task_feedback import TaskFeedbackWidget
from app_渠系计算前端.task_runner import TaskRunner
from .choice_display import ChoiceDisplay
from .workbench_workflow import terrain_source_name


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                     separators=(",", ":")).encode("utf8")
    return hashlib.sha256(raw).hexdigest()


def _terrain_source(report):
    return {key: copy.deepcopy(report[key]) for key in (
        "path", "source_sha256", "cache_path", "cache_sha256", "terrain_sha256",
        "mesh_index", "terrain_mode", "units", "vertex_count", "face_count") if key in report}


class _ProfileTerrainError(ValueError):
    """The terrain read failed and the source can be replaced in this dialog."""


class _ProfileTable(QAbstractTableModel):
    columns = (("桩号 m", "station"), ("X m", "x"), ("Y m", "y"),
               ("天然地面高程 m", "ground_elevation"),
               ("设计高程 m", "design_elevation"), ("设计高程基准", "design_label"))

    def __init__(self, points, parent=None):
        super().__init__(parent)
        self.points = points

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.points)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return self.columns[section][0] if orientation == Qt.Horizontal else str(section + 1)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        value = self.points[index.row()].get(self.columns[index.column()][1])
        if role == Qt.DisplayRole:
            return "缺测" if value is None and index.column() == 3 else "" if value is None else f"{value:.6f}" if isinstance(value, (float, int)) else str(value)
        if role == Qt.ToolTipRole:
            return "" if value is None else repr(value)


class CenterlineProfileDialog(QDialog):
    task_progress = Signal(int, str, float, str)

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        # A frozen copy prevents later callbacks from reading mutable UI inputs.
        from .workbench_panel import serialize_inputs, source_hash
        source_inputs = serialize_inputs(panel._inputs)
        self.networks = [network for network in source_inputs.get("networks", [])
                         if (network.get("alignment") or {}).get("elements")]
        if panel._saved_water_centerline:
            from 土石方计算.adapters.workbench_sources import merge_workbench_profile_routes
            self.networks = merge_workbench_profile_routes(self.networks,
                saved_alignment=panel._saved_water_centerline, route_name=panel._source_channel_name)
        elif panel._project_provider is not None and panel._source_hash and any(
                (network.get("source") or {}).get("kind") == "water_profile_panel"
                and network.get("source_route_extent") != [network["alignment"]["start_station"],
                                                            network["alignment"]["end_station"]]
                for network in self.networks if network.get("source_route_extent")):
            from 土石方计算.adapters.workbench_sources import merge_workbench_profile_routes
            try:
                snapshot = panel._project_provider()
                if source_hash(snapshot) == panel._source_hash:
                    self.networks = merge_workbench_profile_routes(self.networks, snapshot)
            except (RuntimeError, ValueError):
                pass
        self._axis_issue = ""
        imported_batch = panel._centerline_batch_network
        if not self.networks and imported_batch and imported_batch["source"].get("path"):
            batch_network = copy.deepcopy(imported_batch)
            batch_network["alignment"] = batch_network["alignment"].to_dict()
            self.networks.append(batch_network)
        if not self.networks and panel._saved_water_centerline is None and panel._project_provider is not None:
            from 土石方计算.adapters.workbench_sources import import_batch_centerline
            try:
                batch_network = import_batch_centerline(panel._project_provider())
                if batch_network is not None:
                    batch_network["alignment"] = batch_network["alignment"].to_dict()
                    self.networks.append(batch_network)
            except ValueError as error:
                self._axis_issue = str(error)
        for network in self.networks:
            for key in ("test_only", "quantity_basis", "design_source", "construction_assumptions"):
                if key in source_inputs:
                    network.setdefault(key, copy.deepcopy(source_inputs[key]))
            if source_inputs.get("test_only"):
                network["test_only"] = True
        self.request = panel._profile_terrain_request()
        self.sources_ready = False
        self.result = None
        self.last_directory = ""
        self.runner = TaskRunner(self)
        self.runner.running_changed.connect(self._busy)
        self.task_progress.connect(self._progress)
        self._close_when_idle = False
        self.setObjectName("centerlineProfileDialog")
        self.setWindowTitle("剖纵断面 — 沿平面中心轴线")
        self.resize(680, 230)
        root = QVBoxLayout(self)
        source_bar = QWidget()
        source_bar.setStyleSheet("QWidget#profileSources {background:#EAF3FE;border-radius:5px;}")
        source_bar.setObjectName("profileSources")
        source_layout = QHBoxLayout(source_bar)
        self.source_hint = QLabel()
        self.source_hint.setTextFormat(Qt.PlainText)
        self.source_hint.setWordWrap(True)
        source_layout.addWidget(self.source_hint, 1)
        self.import_axis_button = QPushButton("导入批量计算表格")
        self.import_axis_button.clicked.connect(self._choose_axis)
        source_layout.addWidget(self.import_axis_button)
        self.import_terrain_button = QPushButton("导入地形图")
        self.import_terrain_button.clicked.connect(self._choose_terrain)
        source_layout.addWidget(self.import_terrain_button)
        root.addWidget(source_bar)
        self.cut_controls = QWidget()
        cut_layout = QVBoxLayout(self.cut_controls)
        cut_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.cut_controls)
        row = QHBoxLayout()
        row.addWidget(QLabel("线路"))
        self.route = QComboBox()
        self.route.setMinimumWidth(160)
        self.route_display = ChoiceDisplay(self.route, wrap=True)
        row.addWidget(self.route_display, 1)
        self.start, self.end = self._spin(), self._spin()
        self.start.setDecimals(6)
        self.end.setDecimals(6)
        for title, field in (("起始桩号 (m)", self.start), ("终点桩号 (m)", self.end)):
            row.addWidget(QLabel(title))
            row.addWidget(field)
        self.full_route = QPushButton("整条线路")
        self.full_route.clicked.connect(self._route_changed)
        row.addWidget(self.full_route)
        cut_layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("显示采样间距"))
        self.step = self._spin(.05, 10000)
        self.step.setValue(1.)
        self.step.setSuffix(" m")
        self.step.setToolTip("沿真实轴线补充显示点；始终保留天然地形三角边交点，与算量断面间距分别设置。")
        row.addWidget(self.step)
        self.generate_button = QPushButton("开始剖切")
        self.generate_button.setAutoDefault(False)
        self.generate_button.setStyleSheet("padding:7px 18px;background:#246BCE;color:white;font-weight:600")
        self.generate_button.clicked.connect(self.generate)
        row.addWidget(self.generate_button)
        row.addStretch()
        cut_layout.addLayout(row)
        row = QHBoxLayout()
        row.addStretch()
        self.open_button = QPushButton("打开纵断面成果")
        self.open_button.setToolTip("打开导出的纵断面成果.json")
        self.open_button.clicked.connect(self.open_saved)
        row.addWidget(self.open_button)
        self.save_button = QPushButton("保存 DXF / Excel / JSON")
        self.save_button.clicked.connect(self.choose_save)
        self.save_button.setEnabled(False)
        row.addWidget(self.save_button)
        root.addLayout(row)
        self.feedback = TaskFeedbackWidget(self)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self._cancel)
        self.feedback.header_layout.addWidget(self.cancel_button)
        root.addWidget(self.feedback)
        self.feedback.hide()
        self.tabs = QTabWidget()
        plot_page = QWidget()
        plot = QVBoxLayout(plot_page)
        plot.setContentsMargins(0, 0, 0, 0)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
        self.figure = Figure(layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        plot.addWidget(NavigationToolbar2QT(self.canvas, self))
        plot.addWidget(self.canvas)
        self.tabs.addTab(plot_page, "纵断面图")
        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.tabs.addTab(self.table, "桩号与高程表")
        root.addWidget(self.tabs, 1)
        self.empty_space = QWidget()
        root.addWidget(self.empty_space, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.status)
        row = QHBoxLayout()
        self.export_scales = QWidget()
        scale_layout = QHBoxLayout(self.export_scales)
        scale_layout.setContentsMargins(0, 0, 0, 0)
        self.export_scales.hide()
        scale_layout.addWidget(QLabel("DXF 横向比例 1:"))
        self.horizontal_scale = self._spin(1, 100000)
        self.horizontal_scale.setDecimals(0)
        self.horizontal_scale.setValue(1000)
        scale_layout.addWidget(self.horizontal_scale)
        scale_layout.addWidget(QLabel("纵向比例 1:"))
        self.vertical_scale = self._spin(1, 100000)
        self.vertical_scale.setDecimals(0)
        self.vertical_scale.setValue(1000)
        scale_layout.addWidget(self.vertical_scale)
        row.addWidget(self.export_scales)
        row.addStretch()
        self.close_button = QPushButton("关闭")
        self.close_button.clicked.connect(self.reject)
        row.addWidget(self.close_button)
        root.addLayout(row)
        index = 0
        try:
            selected, _ = panel.selected_asset()
            if selected is not None:
                selected_id = selected.get("network_id")
                index = next((i for i, n in enumerate(self.networks) if n.get("network_id") == selected_id
                              or selected_id in n.get("profile_segment_ids", [])), 0)
        except ValueError:
            pass
        self._fill_routes(index)
        self.route.currentIndexChanged.connect(self._route_changed)
        for field in (self.start, self.end, self.step):
            field.valueChanged.connect(self._controls_changed)
        self._refresh_sources()
        previous = getattr(panel, "_centerline_profile_preview", None)
        identity = (previous or {}).get("source_identity", {})
        if (self.sources_ready and previous and identity.get("project_id") == panel.project_id
                and identity.get("snapshot_sha256") == self._snapshot_hash()):
            self._show_profile(copy.deepcopy(previous))

    def _fill_routes(self, index=0):
        self.route.blockSignals(True)
        self.route.clear()
        for network in self.networks:
            self.route.addItem(str(network.get("name") or network.get("network_id") or "线路"))
        self.route.setCurrentIndex(index if self.networks else -1)
        self.route.blockSignals(False)
        self.route_display.refresh()
        self._route_changed()

    def _refresh_sources(self):
        path = self.request["path"]
        ready = bool(self.networks and path)
        if ready and not self.sources_ready and self.result is None:
            self.resize(940, 270)
        self.sources_ready = ready
        if self.networks:
            source = self.networks[0].get("source") or {}
            if source.get("kind") == "batch_centerline":
                name = Path(source["path"]).name if source.get("path") else "当前批量计算表格"
                axis = f"剖切轴线来自{name}，可在“地形与线路平面”核对。"
            else:
                axis = "已带入当前工程的中心轴线。"
        else:
            axis = self._axis_issue or "导入批量计算表格以读取中心轴线。"
        if path:
            terrain = "地形：" + terrain_source_name(path)
            if path == self.panel._pending_terrain_path:
                terrain += "（剖切成功后采用为工作台地形）"
            elif self.request["tin"] is None and not self.request["identity"].get("cache_path"):
                terrain += "（剖切时读取）"
        else:
            terrain = "导入原地形图。"
        self.source_hint.setText(axis + "\n" + terrain)
        self.import_axis_button.setVisible(not self.networks)
        self.import_terrain_button.setVisible(not path)
        self.cut_controls.setVisible(ready)
        self.tabs.setVisible(self.result is not None)
        self.empty_space.setVisible(self.result is None)
        if ready and self.result is None:
            self.status.setText("可调整桩号范围和采样间距，设置完成后点击“开始剖切”。")
        self._busy(self.runner.isRunning())

    def _choose_axis(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入批量计算表格", "", "Excel 表格 (*.xlsx *.xlsm *.xls)")
        if not path:
            return
        from 土石方计算.adapters.workbench_sources import import_batch_centerline_file

        def work(token):
            network = import_batch_centerline_file(path)
            token.raise_if_cancelled()
            network["alignment"] = network["alignment"].to_dict()
            return network

        def done(network):
            self.panel._set_centerline_batch_network(network)
            self.networks = [network]
            self._fill_routes()
            self.feedback.hide()
            self.status.clear()
            self._refresh_sources()

        self.feedback.show()
        self.feedback.start("线路轴线读取", "正在读取表格中的平面坐标和转弯半径。")
        self.runner.submit(work, on_success=done, on_error=self._failed,
            on_cancelled=lambda: self.feedback.cancelled("表格读取已取消。"))

    def _choose_terrain(self):
        path = self.panel.choose_terrain_file(self)
        if path:
            self.panel._select_terrain_path(path)
            self.request = self.panel._profile_terrain_request()
            self._controls_changed()
            self.feedback.hide()
            self._refresh_sources()

    @staticmethod
    def _spin(low=-1e10, high=1e10):
        field = QDoubleSpinBox()
        field.setRange(low, high)
        field.setDecimals(3)
        return field

    def _snapshot_hash(self):
        return _digest({"networks": self.networks, "terrain": _terrain_source(self.request["identity"]),
                        "path": self.request["path"], "mode": self.request["mode"], "options": self.request["options"]})

    def _route_changed(self, *_):
        index = self.route.currentIndex()
        alignment = self.networks[index].get("alignment") if index >= 0 else None
        if alignment:
            lower, upper = alignment["start_station"], alignment["end_station"]
            for field, value in ((self.start, lower), (self.end, upper)):
                field.setRange(lower, upper)
                field.setValue(value)
        self._controls_changed()

    def _controls_changed(self, *_):
        if self.result is not None:
            self._dirty = True
            self.save_button.setEnabled(False)
            self.status.setText("剖切设置已修改，点击“开始剖切”更新图形。")

    def _busy(self, busy):
        for widget in (self.route, self.start, self.end, self.step, self.full_route,
                       self.generate_button, self.open_button, self.horizontal_scale, self.vertical_scale):
            widget.setEnabled(not busy)
        self.generate_button.setEnabled(not busy and self.sources_ready)
        self.import_axis_button.setEnabled(not busy)
        self.import_terrain_button.setEnabled(not busy)
        self.save_button.setEnabled(not busy and self.result is not None and not getattr(self, "_dirty", False))
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        self.cancel_button.setText("取消")
        if not busy and self._close_when_idle:
            super().reject()

    def _progress(self, generation, stage, fraction, message):
        if generation == self.runner.generation and self.feedback.active:
            self.feedback.update_progress(stage, fraction, message)

    def _cancel(self):
        self.runner.cancel()
        self.feedback.request_cancel()
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("正在取消…")

    def _failed(self, error):
        self.feedback.fail(str(error))
        self.status.setText(str(error))
        if isinstance(error, _ProfileTerrainError):
            self.import_terrain_button.setText("重新选择地形")
            self.import_terrain_button.show()
            if self.request["path"] == self.panel._pending_terrain_path:
                self.panel._terrain_failed(error)

    def generate(self):
        try:
            if self.runner.isRunning():
                return
            if not self.sources_ready or self.route.currentIndex() < 0:
                return
            if self.end.value() <= self.start.value():
                raise ValueError("止桩必须大于起桩。")
            network = copy.deepcopy(self.networks[self.route.currentIndex()])
            start, end, step = self.start.value(), self.end.value(), self.step.value()
            # Spin boxes format values for people; full-route endpoints retain
            # the original analytical stations, including submillimetre digits.
            alignment = network.get("alignment") or {}
            if start == self.start.minimum():
                start = alignment["start_station"]
            if end == self.end.maximum():
                end = alignment["end_station"]
            request = dict(self.request)
            request["terrain_progress"] = self.task_progress.emit
            if "scope_networks" in request:
                request["scope_networks"] = [{"alignment": network["alignment"], "test_only": network.get("test_only")}]
            terrain_identity = request["identity"]
            needs_import = request["tin"] is None and not any(terrain_identity.get(key) for key in (
                "source_sha256", "cache_path", "terrain_sha256"))
            if needs_import:
                request["options"] = self.panel._new_terrain_options(request["path"], self.networks)
            request["options"] = {**request["options"], "export_clean_terrain": False}
            ensure_tin = self.panel._ensure_tin
            load_selected_terrain = self.panel._load_selected_terrain
            cache_tin = self.panel._cache_tin
            project_id = self.panel.project_id
            self.feedback.show()
            self.feedback.start("中心轴线纵断面剖切", "正在沿中心轴线剖切原地形。")

            def work(token):
                from 土石方计算.services.centerline_profile import cut_centerline_profile
                token.raise_if_cancelled()
                def progress(stage, fraction, message):
                    self.task_progress.emit(token.generation, stage, fraction, message)

                try:
                    if needs_import:
                        tin = load_selected_terrain(token, request["path"], request["options"], progress)
                    else:
                        tin = ensure_tin(token, request)
                        if (request["tin"] is None and Path(request["path"]).suffix.lower() in {".dwg", ".dxf"}
                                and not tin.import_report.get("cache_path")):
                            progress("terrain_cache", 0., "正在保存计算地形缓存。")
                            tin = cache_tin(tin, token, request["options"])
                except Exception as error:
                    token.raise_if_cancelled()
                    raise _ProfileTerrainError(f"地形读取失败，可重试或重新选择地形。\n{error}") from error
                profile = cut_centerline_profile(tin, network, station_start=start, station_end=end,
                    sample_step=step, cancelled=lambda: token.is_cancelled, progress=progress)
                token.raise_if_cancelled()
                return tin, profile

            def done(value):
                tin, profile = value
                source = network.get("source") or {}
                if source.get("kind") == "batch_centerline" and not source.get("path"):
                    self.panel._set_centerline_batch_network(network)
                if self.panel._pending_terrain_path == request["path"]:
                    self.panel._commit_selected_terrain(tin, request["path"])
                    self.request = self.panel._terrain_request()
                    self._refresh_sources()
                elif (request["tin"] is None and self.panel._tin is None
                        and self.panel.terrain_path.text() == request["path"]):
                    self.panel._accept_tin(tin)
                    self.request = self.panel._terrain_request()
                    self._refresh_sources()
                    self.panel.data_changed.emit()
                profile["source_identity"] = {"project_id": project_id, "snapshot_sha256": self._snapshot_hash(),
                    "terrain": _terrain_source(getattr(tin, "import_report", terrain_identity))}
                self._show_profile(profile)
                self.panel._centerline_profile_preview = copy.deepcopy(profile)
                self.feedback.succeed("纵断面已生成，可查看高程表或保存 DXF。")

            self.runner.submit(work, on_success=done, on_error=self._failed,
                on_cancelled=lambda: self.feedback.cancelled("剖切已取消，已有成果保留。"))
        except Exception as error:
            self._failed(error)

    def _show_profile(self, profile):
        if self.result is None:
            self.resize(1120, 780)
        self.empty_space.hide()
        self.tabs.show()
        self.export_scales.show()
        self.result = profile
        route_index = next((i for i, network in enumerate(self.networks)
            if network.get("network_id") == profile.get("route_id")), -1)
        alignment = self.networks[route_index].get("alignment") if route_index >= 0 else None
        same_source = profile.get("source_identity", {}).get("snapshot_sha256") == self._snapshot_hash()
        sync_controls = bool(same_source and isinstance(alignment, dict) and alignment.get("elements")
            and alignment["start_station"] <= profile["station_start"] < profile["station_end"] <= alignment["end_station"])
        if sync_controls:
            self.route.blockSignals(True)
            self.route.setCurrentIndex(route_index)
            self.route.blockSignals(False)
            for field, value in ((self.start, profile["station_start"]), (self.end, profile["station_end"])):
                field.blockSignals(True)
                field.setRange(alignment["start_station"], alignment["end_station"])
                field.setValue(value)
                field.blockSignals(False)
            self.step.blockSignals(True)
            self.step.setValue(profile.get("sample_step", 1.))
            self.step.blockSignals(False)
        self._dirty = False
        self.figure.clear()
        axes = self.figure.add_subplot()
        axes.set_facecolor("#FAFCFE")
        labels = set()
        from 土石方计算.io.centerline_profile_exporter import profile_line_runs, profile_design_label
        for prefix in ("ground", "design"):
            for points in profile_line_runs(profile, prefix):
                label = "天然地面线" if prefix == "ground" else profile_design_label(points[0])
                axes.plot([p["station"] for p in points], [p[prefix + "_elevation"] for p in points],
                    color="#26744D" if prefix == "ground" else "#C54B3D",
                    linestyle="-" if prefix == "ground" else "--", linewidth=1.3,
                    label=label if label not in labels else None)
                labels.add(label)
        for gap in profile.get("missing_ranges", []):
            axes.axvspan(gap["station_start"], gap["station_end"], color="#E8C690", alpha=.35,
                         label="地形缺测" if "地形缺测" not in labels else None)
            labels.add("地形缺测")
        metadata = profile.get("metadata", {})
        prefix = "TEST 示例　" if metadata.get("test_only") else ""
        axes.set_title(prefix + str(profile.get("route_name", "")) + " 中心轴线纵断面", fontfamily="Microsoft YaHei")
        axes.set_xlabel("桩号 (m)", fontfamily="Microsoft YaHei")
        axes.set_ylabel("高程 (m)", fontfamily="Microsoft YaHei")
        axes.ticklabel_format(style="plain", useOffset=False)
        axes.grid(True, alpha=.2)
        if labels:
            axes.legend(prop={"family": "Microsoft YaHei", "size": 9}, ncol=3)
        self.canvas.draw_idle()
        old_model = self.table.model()
        self.table.setModel(_ProfileTable(profile["points"], self.table))
        if old_model is not None:
            old_model.deleteLater()
        self.table.resizeColumnsToContents()
        # Qt only samples the first visible rows when sizing columns. Later
        # stations can have more digits; size against the complete saved range.
        metrics = self.table.fontMetrics()
        for column, (title, key) in enumerate(_ProfileTable.columns[:5]):
            longest = max((f"{point[key]:.6f}" for point in profile["points"] if point.get(key) is not None), key=len, default="")
            self.table.setColumnWidth(column, max(metrics.horizontalAdvance(title), metrics.horizontalAdvance(longest)) + 22)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(len(_ProfileTable.columns) - 1, QHeaderView.Stretch)
        gaps = len(profile.get("missing_ranges", []))
        self.status.setText(f"桩号 {profile['station_start']:.3f}～{profile['station_end']:.3f} m"
                            f"　|　{len(profile['points']):,} 个点　|　地形缺测 {gaps} 处")
        self.save_button.setEnabled(True)

    def open_saved(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开纵断面成果", self.last_directory, "纵断面成果 (*.json)")
        if not path:
            return
        self.feedback.show()
        self.feedback.start("纵断面成果读取", "正在核对已保存数据。")
        def work(token):
            from 土石方计算.io.centerline_profile_exporter import load_centerline_profile
            token.raise_if_cancelled()
            return load_centerline_profile(path)
        def done(profile):
            self.last_directory = str(Path(path).parent)
            self._show_profile(profile)
            identity = profile.get("source_identity") or {}
            if (identity.get("project_id") != self.panel.project_id
                    or identity.get("snapshot_sha256") != self._snapshot_hash()):
                self.status.setText(f"当前图表来自已保存的纵断面《{profile.get('route_name') or Path(path).stem}》。\n"
                                    + self.status.text())
            self.feedback.succeed("已打开纵断面成果。")

        self.runner.submit(work, on_success=done,
            on_error=self._failed, on_cancelled=lambda: self.feedback.cancelled())

    def choose_save(self):
        folder = QFileDialog.getExistingDirectory(self, "选择纵断面成果存放位置", self.last_directory or self.panel.output_directory.text())
        if folder:
            stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(self.result.get("route_name") or "线路"))[:60].strip(" .")
            directory = Path(folder) / f"{name}_纵断面_{stamp}_{uuid.uuid4().hex[:6]}"
            self.save_to(directory)

    def save_to(self, directory):
        if self.result is None or self.runner.isRunning():
            return
        profile = copy.deepcopy(self.result)
        horizontal, vertical = self.horizontal_scale.value(), self.vertical_scale.value()
        self.feedback.show()
        self.feedback.start("纵断面成果保存", "正在保存 DXF、Excel 高程表和 JSON 成果。")
        def work(token):
            from 土石方计算.io.centerline_profile_exporter import save_centerline_profile_bundle
            token.raise_if_cancelled()
            return save_centerline_profile_bundle(profile, directory, horizontal_scale=horizontal, vertical_scale=vertical,
                cancelled=lambda: token.is_cancelled)
        def done(audit):
            self.last_directory = audit["directory"]
            self.feedback.succeed("已保存 DXF、Excel 高程表和 JSON 成果。")
            self.last_save_audit = audit
            self._prompt_open_saved_folder(self.last_directory)
        self.runner.submit(work, on_success=done, on_error=self._failed,
            on_cancelled=lambda: self.feedback.cancelled("保存已取消；请重新保存为完整成果。"))

    def _prompt_open_saved_folder(self, directory):
        prompt = QMessageBox(self)
        prompt.setAttribute(Qt.WA_DeleteOnClose)
        prompt.setIcon(QMessageBox.Question)
        prompt.setWindowTitle("纵断面成果已保存")
        prompt.setTextFormat(Qt.PlainText)
        prompt.setText(f"要打开成果所在的文件夹吗？\n\n{directory}")
        prompt.setStandardButtons(QMessageBox.Open | QMessageBox.Close)
        prompt.button(QMessageBox.Open).setText("打开文件夹")
        prompt.button(QMessageBox.Close).setText("关闭")
        prompt.setDefaultButton(QMessageBox.Close)
        prompt.setEscapeButton(QMessageBox.Close)

        def open_folder(result):
            if result == QMessageBox.Open and not QDesktopServices.openUrl(QUrl.fromLocalFile(directory)):
                QMessageBox.warning(self, "打开文件夹失败", f"无法打开成果文件夹。\n{directory}")

        prompt.finished.connect(open_folder)
        prompt.open()

    def reject(self):
        if self.runner.isRunning():
            self._close_when_idle = True
            self._cancel()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.runner.isRunning():
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
