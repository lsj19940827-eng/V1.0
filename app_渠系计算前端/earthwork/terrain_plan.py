"""The source page's independent, read-only plan of terrain and design routes."""
from __future__ import annotations

import json
import math
from pathlib import Path
from time import perf_counter

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)
from matplotlib.backend_bases import MouseButton
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

from app_渠系计算前端.task_runner import TaskRunner


class _TerrainPlanCanvas(FigureCanvasQTAgg):
    """Transform the last plan image while the wheel is moving on a dense map."""

    def __init__(self, figure):
        super().__init__(figure)
        self._rendered_axes = None
        self._rendered_box = None
        self._rendered_view = None
        self._render_seconds = 0.
        self._zoom_image = None
        self._zoom_view = None
        self._zoom_settle = QTimer(self)
        self._zoom_settle.setSingleShot(True)
        self._zoom_settle.setInterval(120)
        self._zoom_settle.timeout.connect(self.draw_idle)

    def draw(self):
        self._zoom_settle.stop()
        self._zoom_image = None
        started = perf_counter()
        super().draw()
        self._render_seconds = perf_counter() - started
        self._rendered_axes = self.figure.axes[0] if self.figure.axes else None
        if self._rendered_axes is not None:
            self._rendered_box = self._rendered_axes.bbox.frozen()
            self._rendered_view = self._rendered_axes.viewLim.frozen()

    def show_zoom(self, axes):
        if axes is not self._rendered_axes or self._render_seconds < 0.045:
            self.draw_idle()
            return
        if self._zoom_image is None:
            width, height = int(self.renderer.width), int(self.renderer.height)
            self._zoom_image = QImage(self.buffer_rgba(), width, height, width * 4,
                                      QImage.Format.Format_RGBA8888).copy()
        self._zoom_view = axes.viewLim.frozen()
        self._zoom_settle.start()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._zoom_image is None:
            return
        box = self._rendered_box
        ratio = self.device_pixel_ratio
        source = QRectF(box.x0, self._zoom_image.height() - box.y1, box.width, box.height)
        plot = QRectF(source.left() / ratio, source.top() / ratio,
                      source.width() / ratio, source.height() / ratio)
        rendered, view = self._rendered_view, self._zoom_view
        x_scale, y_scale = plot.width() / view.width, plot.height() / view.height
        target = QRectF(plot.left() + (rendered.x0 - view.x0) * x_scale,
                        plot.top() + (view.y1 - rendered.y1) * y_scale,
                        rendered.width * x_scale, rendered.height * y_scale)
        visible = target.intersected(plot)
        with QPainter(self) as painter:
            painter.fillRect(plot, Qt.GlobalColor.white)
            if not visible.isEmpty():
                sx, sy = source.width() / target.width(), source.height() / target.height()
                crop = QRectF(source.left() + (visible.left() - target.left()) * sx,
                              source.top() + (visible.top() - target.top()) * sy,
                              visible.width() * sx, visible.height() * sy)
                painter.drawImage(visible, self._zoom_image, crop)


class TerrainPlanMixin:
    def _build_terrain_plan(self, layout):
        from matplotlib.figure import Figure

        self.terrain_display_runner = TaskRunner(self)
        self.terrain_display_runner.running_changed.connect(self._terrain_display_running_changed)
        self.map_terrain_runner.running_changed.connect(self._map_terrain_busy)
        self._terrain_display_context = None
        self._terrain_display_cache = {}
        self._terrain_display_pending = None
        self._terrain_display_running_key = None
        self._terrain_display_stopped = None
        self._terrain_display_desired_key = None
        self._terrain_plan_state = None
        self._terrain_map_note = ""
        self._terrain_zoom = None
        self._terrain_full_extent = None
        self._terrain_enlarged_dialog = None

        self._terrain_plan_host = layout
        self._terrain_plan_widget = QWidget()
        layout.addWidget(self._terrain_plan_widget, 1)
        layout = QVBoxLayout(self._terrain_plan_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        title = QLabel("地形与线路平面")
        title.setStyleSheet("font-weight:600;color:#17365D")
        toolbar.addWidget(title, 1)
        self.terrain_display_range = QLabel("已加载范围")
        toolbar.addWidget(self.terrain_display_range)
        self.terrain_fit_button = QPushButton("还原视图")
        self.terrain_fit_button.setToolTip("恢复当前范围的全图；在图上滚动鼠标滚轮可放大或缩小。")
        self.terrain_fit_button.setEnabled(False)
        self.terrain_fit_button.clicked.connect(self._reset_terrain_zoom)
        toolbar.addWidget(self.terrain_fit_button)
        self.terrain_expand_button = QPushButton("放大查看")
        self.terrain_expand_button.setToolTip("在大窗口查看地形与线路平面，也可双击图面。")
        self.terrain_expand_button.hide()
        self.terrain_expand_button.clicked.connect(self._toggle_enlarged_terrain_plan)
        toolbar.addWidget(self.terrain_expand_button)
        self.terrain_layer_button = QPushButton("图层")
        self.terrain_layer_button.setCheckable(True)
        self.terrain_layer_button.setAccessibleName("地形平面图层")
        toolbar.addWidget(self.terrain_layer_button)
        self.terrain_display_button = QPushButton("刷新显示")
        self.terrain_display_button.clicked.connect(self._terrain_display_action)
        toolbar.addWidget(self.terrain_display_button)
        layout.addLayout(toolbar)

        self.plan_display_controls = QWidget()
        controls = QVBoxLayout(self.plan_display_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        self.terrain_layers = {}
        for row in ((('points', '测点 / 网格顶点'), ('source_contours', '原始等高线'),
                     ('boundary', '有效边界')),
                    (('generated_contours', '计算等高线'), ('anomalies', '异常标记'))):
            row_layout = QHBoxLayout()
            for key, label in row:
                box = QCheckBox(label)
                box.setChecked(key not in ("generated_contours", "anomalies"))
                box.toggled.connect(self._redraw_terrain_plan)
                self.terrain_layers[key] = box
                row_layout.addWidget(box)
            controls.addLayout(row_layout)
        generated_row = controls.itemAt(1).layout()
        self.terrain_display_interval = QDoubleSpinBox()
        self.terrain_display_interval.setDecimals(2)
        self.terrain_display_interval.setRange(0, 10000)
        self.terrain_display_interval.setSpecialValueText("自动等高距")
        self.terrain_display_interval.setSuffix(" m")
        self.terrain_display_interval.setToolTip("计算等高线的图面等高距")
        self.terrain_display_interval.setEnabled(False)
        self.terrain_display_interval.valueChanged.connect(self._redraw_terrain_plan)
        self.terrain_layers["generated_contours"].toggled.connect(self.terrain_display_interval.setEnabled)
        generated_row.addWidget(self.terrain_display_interval)
        self.plan_display_controls.hide()
        self.terrain_layer_button.toggled.connect(self.plan_display_controls.setVisible)
        layout.addWidget(self.plan_display_controls)

        self.terrain_figure = Figure(figsize=(6.4, 4.2), layout="constrained")
        self.terrain_figure.set_facecolor("#FFFFFF")
        self.terrain_canvas = _TerrainPlanCanvas(self.terrain_figure)
        self.terrain_canvas.setObjectName("terrainPlanCanvas")
        self.terrain_canvas.setAccessibleName("地形与线路平面图")
        self.terrain_canvas.setToolTip("滚轮以鼠标位置为中心缩放，双击图面放大查看。")
        self.terrain_canvas.mpl_connect("scroll_event", self._zoom_terrain_plan)
        self.terrain_canvas.mpl_connect("button_press_event", self._terrain_plan_clicked)
        self.terrain_canvas.setMinimumSize(280, 240)
        layout.addWidget(self.terrain_canvas, 1)
        self.terrain_display_status = QLabel()
        self.terrain_display_status.setWordWrap(True)
        self.terrain_display_status.setStyleSheet("color:#53667C")
        layout.addWidget(self.terrain_display_status)
        self.workflow_stack.currentChanged.connect(self._terrain_plan_step_changed)

    def _terrain_plan_step_changed(self, index):
        self._terrain_plan_state = None
        if index == 0:
            self._refresh_terrain_plan()
            return
        if self._terrain_enlarged_dialog is not None:
            self._terrain_enlarged_dialog.reject()
        if self.terrain_display_runner.isRunning():
            self._terrain_display_pending = None
            self._terrain_display_running_key = None
            self.terrain_display_runner.invalidate()

    def _redraw_terrain_plan(self, *_):
        self._refresh_terrain_plan(force=True)

    def _zoom_terrain_plan(self, event):
        axes = event.inaxes
        if (axes is None or event.xdata is None or event.ydata is None or not event.step
                or not axes.has_data()):
            return
        wheel = event.guiEvent
        steps = event.step
        if wheel is not None and not wheel.pixelDelta().isNull():
            steps = wheel.pixelDelta().y() / 40
        factor = 1.25 ** -max(-4, min(4, steps))
        xlim = tuple(event.xdata + (x - event.xdata) * factor for x in axes.get_xlim())
        ylim = tuple(event.ydata + (y - event.ydata) * factor for y in axes.get_ylim())
        if (not steps or min(xlim[1] - xlim[0], ylim[1] - ylim[0]) < 0.01
                or not all(map(math.isfinite, (*xlim, *ylim)))):
            return
        self._terrain_zoom = (self._plan_view_source, xlim, ylim)
        axes.set_xlim(*xlim)
        axes.set_ylim(*ylim)
        self.terrain_fit_button.setEnabled(True)
        self.terrain_canvas.show_zoom(axes)

    def _reset_terrain_zoom(self):
        self._terrain_zoom = None
        axes, = self.terrain_figure.axes
        xlim, ylim = self._terrain_full_extent
        axes.set_xlim(*xlim)
        axes.set_ylim(*ylim)
        self.terrain_fit_button.setEnabled(False)
        self.terrain_canvas.draw_idle()

    def _terrain_plan_clicked(self, event):
        if event.dblclick and event.button == MouseButton.LEFT:
            self._toggle_enlarged_terrain_plan()

    def _toggle_enlarged_terrain_plan(self):
        if self._terrain_enlarged_dialog is not None:
            self._terrain_enlarged_dialog.reject()
            return
        if self.terrain_expand_button.isHidden():
            return
        dialog = QDialog(self, Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        dialog.setObjectName("enlargedTerrainPlan")
        dialog.setWindowTitle("地形与线路平面")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        layout = QVBoxLayout(dialog)
        layout.addWidget(self._terrain_plan_widget, 1)
        self._terrain_enlarged_dialog = dialog
        self.terrain_expand_button.setText("返回")
        self.terrain_expand_button.setToolTip("返回工程与地形页，也可双击图面。")
        self.terrain_canvas.setToolTip("滚轮以鼠标位置为中心缩放，双击图面返回。")
        dialog.finished.connect(self._restore_embedded_terrain_plan)
        dialog.showMaximized()

    def _restore_embedded_terrain_plan(self, _):
        dialog = self._terrain_enlarged_dialog
        self._terrain_enlarged_dialog = None
        self._terrain_plan_host.addWidget(self._terrain_plan_widget, 1)
        self.terrain_expand_button.setText("放大查看")
        self.terrain_expand_button.setToolTip("在大窗口查看地形与线路平面，也可双击图面。")
        self.terrain_expand_button.setVisible(any(axes.has_data() for axes in self.terrain_figure.axes))
        self.terrain_canvas.setToolTip("滚轮以鼠标位置为中心缩放，双击图面放大查看。")
        self._terrain_plan_widget.show()
        dialog.deleteLater()

    def _refresh_terrain_plan(self, *, force=False):
        if (self._shutting_down or self._restoring or self.workflow_stack.currentIndex() != 0
                or not hasattr(self, "terrain_canvas")):
            return
        self._restore_map_tin()
        networks = self._inputs.get("networks", ())
        alignments = tuple(network.get("alignment") for network in networks)
        excluded = self._inputs.get("excluded", ())
        batch_alignment = None
        if (self._centerline_batch_network
                and not any(hasattr(alignment, "sample_stations") for alignment in alignments)):
            batch_alignment = self._centerline_batch_network["alignment"]
        self._plan_view_source = (id(self._tin), tuple(map(id, alignments)), tuple(map(id, excluded)),
                                  id(batch_alignment))
        state = (self._plan_view_source, self.terrain_path.text(), self._pending_terrain_path,
                 self._pending_terrain_note, self._terrain_import_failed, self._terrain_map_note, self.runner.isRunning(),
                 self.map_terrain_runner.isRunning())
        if not force and state == self._terrain_plan_state:
            return
        self._terrain_plan_state = state
        self.terrain_figure.clear()
        axes = self.terrain_figure.add_subplot(111)
        self._draw_plan(axes, networks, excluded, batch_alignment)
        self._terrain_full_extent = (axes.get_xlim(), axes.get_ylim())
        self.terrain_expand_button.setVisible(self._terrain_enlarged_dialog is not None or axes.has_data())
        if self._terrain_zoom and self._terrain_zoom[0] == self._plan_view_source:
            axes.set_xlim(*self._terrain_zoom[1])
            axes.set_ylim(*self._terrain_zoom[2])
        else:
            self._terrain_zoom = None
        self.terrain_fit_button.setEnabled(bool(self._terrain_zoom))
        self._update_terrain_display_action()
        self.terrain_canvas.draw_idle()

    def _map_terrain_busy(self, busy):
        main_busy = self.runner.isRunning()
        self._refresh_terrain_source_label()
        self.cancel_button.setEnabled(busy or main_busy)
        self.cancel_button.setVisible(busy or main_busy)
        self.centerline_source_button.setEnabled(not busy and not main_busy)
        self._update_terrain_display_action()
        if not busy and not main_busy:
            self.cancel_button.setText("取消")
        if not busy:
            self._refresh_terrain_plan()

    def _restore_map_tin(self):
        if (self._tin is not None or self._terrain_import_failed or self.map_terrain_runner.isRunning()
                or not self.terrain_path.text() or not self._terrain_identity):
            return
        request = self._terrain_request()
        key = self._map_request_key(request)
        if self._map_restore_attempt == key:
            return
        self._map_restore_attempt = key
        # Opening a saved project may need a legacy source read to show its map.
        # Previewing it is independent from the explicit terrain import/export.
        request["options"]["export_clean_terrain"] = False
        request.pop("terrain_progress", None)

        def load(token):
            tin = self._ensure_tin(token, request)
            if not tin.import_report.get("cache_path") and Path(request["path"]).suffix.lower() in {".dwg", ".dxf"}:
                tin = self._cache_tin(tin, token, request["options"])
            return tin

        def done(tin):
            if self._map_request_key(self._terrain_request()) == key:
                self._terrain_map_note = ""
                self._accept_tin(tin)

        def finish(message, *, failed=False):
            if self._map_request_key(self._terrain_request()) != key:
                return
            self._terrain_map_note = message
            if failed:
                self._terrain_import_failed = True
            self._log(message)
            self._refresh_workflow()

        self.map_terrain_runner.submit(load, on_success=done,
            on_error=lambda error: finish("地形平面恢复未完成：" + str(error), failed=True),
            on_cancelled=lambda: finish("地形平面恢复已取消。"))

    @staticmethod
    def _map_request_key(request):
        identity = request["identity"]
        return (request["path"], request["mode"], identity.get("source_sha256"), identity.get("cache_sha256"),
                json.dumps(request["options"], sort_keys=True),
                tuple(id(network.get("alignment")) for network in request.get("scope_networks", ())))

    def _draw_plan(self, axes, networks, excluded, batch_alignment):
        from matplotlib.collections import LineCollection
        from 土石方计算.adapters.workbench_sources import restore_source_plan_alignment, trenchless_plan_alignment
        from 土石方计算.services.earthwork_scope import is_trenchless_exclusion

        trenchless = [record for record in excluded if is_trenchless_exclusion(record)]
        legacy_ids = {record["route_id"] for record in trenchless
                      if record.get("route_id") and not record.get("plan_elements")}
        plan_routes = []
        legacy_alignments = {}
        if batch_alignment is not None:
            plan_routes.append((batch_alignment, "剖切中心轴线", "#245A93"))
        for network in networks:
            alignment = network.get("alignment")
            if hasattr(alignment, "sample_stations"):
                plan_routes.append((alignment, "线路", "#245A93"))
            route_id = network.get("source_identity") or network.get("route_id") or network.get("network_id")
            if route_id in legacy_ids and route_id not in legacy_alignments:
                if (source_plan := restore_source_plan_alignment(network)) is not None:
                    legacy_alignments[route_id] = source_plan
        for record in trenchless:
            source_plan = None if record.get("plan_elements") else legacy_alignments.get(record.get("route_id"))
            if (alignment := trenchless_plan_alignment(record, source_plan)) is not None:
                plan_routes.append((alignment, record.get("construction_method") or "非开挖", "#A75A0B"))
        routes = []
        labels = set()
        for alignment, label, color in plan_routes:
            step = max(10., (alignment.end_station - alignment.start_station) / 1500.)
            stations = set(alignment.sample_stations(step))
            # Render short arcs and include their exact extrema in the display bounds.
            for element in alignment.elements:
                if element.get("kind") != "arc":
                    continue
                start = element["start_angle"]
                end = start + element["sweep_angle"]
                segments = max(2, math.ceil(abs(element["sweep_angle"]) / math.radians(10)))
                stations.update(element["station_start"] + element["length"] * i / segments
                                for i in range(1, segments))
                for quadrant in range(math.ceil(min(start, end) / (math.pi / 2)),
                                      math.floor(max(start, end) / (math.pi / 2)) + 1):
                    fraction = (quadrant * math.pi / 2 - start) / element["sweep_angle"]
                    if 0 <= fraction <= 1:
                        stations.add(element["station_start"] + fraction * element["length"])
            xy = np.asarray([alignment.get_xy_at_station(station) for station in sorted(stations)])
            routes.append(xy)
            axes.plot(xy[:, 0], xy[:, 1], lw=1.8, color=color,
                      zorder=4, label=label if label not in labels else None)
            labels.add(label)
        route_extent = None
        if routes:
            xy = np.concatenate(routes)
            low, high = xy.min(axis=0), xy.max(axis=0)
            route_extent = (*low, *high)
        self.terrain_fit_button.setVisible(bool(routes) or self._tin is not None)
        self._set_terrain_display_context()
        key = self._request_terrain_display()
        display = self._terrain_display_cache.get(key)
        self.terrain_display_status.setToolTip("")
        if display:
            extent = display.get("bounds")
            self.terrain_display_status.setToolTip(self._terrain_display_text(display, key))
            status = "已叠加线路与地形" if routes else "已显示地形，尚无可显示的设计线路"
            if self._pending_terrain_note:
                status = "当前采用地形 · " + self._pending_terrain_note
            if extent and route_extent and (
                    route_extent[0] < extent[0] or route_extent[1] < extent[1]
                    or route_extent[2] > extent[2] or route_extent[3] > extent[3]):
                status += " · 部分线路超出已加载地形范围"
            self.terrain_display_status.setText(status)
            if self.terrain_layers["points"].isChecked():
                points = display["measured_points"]
                if len(points):
                    axes.scatter(points[:, 0], points[:, 1], s=3, c=points[:, 2], cmap="terrain",
                                 alpha=.45, zorder=1, label=display["point_label"])
            if self.terrain_layers["source_contours"].isChecked():
                lines = [contour[:, :2] for contour in display["source_contours"]]
                if lines:
                    # Submit one path to the renderer and preserve every contour break.
                    vertices = np.full((sum(map(len, lines)) + len(lines), 2), np.nan)
                    start = 0
                    for line in lines:
                        stop = start + len(line)
                        vertices[start:stop] = line
                        start = stop + 1
                    axes.plot(*vertices.T, color="#8DA071", lw=.65, alpha=.75, label="原始等高线")
            if self.terrain_layers["generated_contours"].isChecked():
                contours = display["generated_contours"]
                lines = [contour["segments"][:, :, :2] for contour in contours]
                if lines:
                    axes.add_collection(LineCollection(np.concatenate(lines), colors="#678D9C", linewidths=.6,
                                                       alpha=.7, label="计算等高线"))
                for contour in contours[::max(1, math.ceil(len(contours) / 8))]:
                    segments = contour["segments"]
                    point = segments[len(segments) // 2, :, :2].mean(axis=0)
                    axes.text(*point, f"{contour['elevation']:g}", fontsize=7, color="#557C87", clip_on=True,
                              bbox={"facecolor": "white", "edgecolor": "none", "alpha": .7, "pad": .2})
            if self.terrain_layers["boundary"].isChecked() and len(display["boundary_segments"]):
                axes.add_collection(LineCollection(display["boundary_segments"][:, :, :2], colors="#404F61",
                                                   linewidths=1.1, alpha=.85, label="有效边界"))
            if self.terrain_layers["anomalies"].isChecked():
                points = display["anomaly_points"]
                if len(points):
                    axes.scatter(points[:, 0], points[:, 1], s=28, c="#C74345", marker="x", zorder=6,
                                 label="异常资料位置")
                if display["anomaly_contours"]:
                    axes.add_collection(LineCollection([contour[:, :2] for contour in display["anomaly_contours"]],
                        colors="#C74345", linewidths=1.1, linestyles="--", label="异常或让位原片段"))
            self._fit_terrain_plan(axes, extent, route_extent)
        elif self._tin is None:
            if self._pending_terrain_note or self._terrain_map_note:
                message = self._pending_terrain_note or self._terrain_map_note
            elif self.map_terrain_runner.isRunning():
                message = "正在读取本工程的地形缓存。"
            elif self.runner.isRunning() and self._pending_terrain_path:
                message = "正在准备地形平面。"
            elif routes:
                message = "已显示设计线路"
            else:
                message = ""
            self.terrain_display_status.setText(message)
            self._update_terrain_display_action()
            if not routes:
                empty = "当前设计缺少平面线路" if networks or excluded else "读取设计资料后显示线路"
                axes.text(.5, .5, empty, transform=axes.transAxes, ha="center", va="center",
                          color="#62748B", fontfamily="Microsoft YaHei")
                axes.set_axis_off()
        elif self.terrain_display_runner.isRunning() and self.terrain_layers["points"].isChecked():
            # Make the terrain visible while the worker builds its detailed display layers.
            measured = getattr(self._tin, "measured_points", ())
            points = measured if len(measured) else self._tin.points
            sample = np.asarray(points[::max(1, math.ceil(len(points) / 2500))])
            if len(sample):
                axes.scatter(sample[:, 0], sample[:, 1], s=3, color="#799769", alpha=.55,
                             label="测点预览" if len(measured) else "网格预览")
        if axes.get_legend_handles_labels()[0]:
            axes.legend(prop={"family": "Microsoft YaHei", "size": 8}, loc="upper right")
        axes.set_aspect("equal", adjustable="box")
        axes.ticklabel_format(style="plain", useOffset=False)
        axes.set_xlabel("X (m)")
        axes.set_ylabel("Y (m)")

    @staticmethod
    def _fit_terrain_plan(axes, extent, route_extent):
        if extent is None:
            return
        lo_x, lo_y, hi_x, hi_y = extent
        if route_extent is not None:
            lo_x, lo_y = min(lo_x, route_extent[0]), min(lo_y, route_extent[1])
            hi_x, hi_y = max(hi_x, route_extent[2]), max(hi_y, route_extent[3])
        margin = max(hi_x - lo_x, hi_y - lo_y) * .025 or 1.
        axes.set_xlim(lo_x - margin, hi_x + margin)
        axes.set_ylim(lo_y - margin, hi_y + margin)

    def _set_terrain_display_context(self):
        identity = self._terrain_identity
        context = (id(self._tin), identity.get("source_sha256"), identity.get("cache_sha256"),
                   identity.get("terrain_sha256"), identity.get("path"))
        if context != self._terrain_display_context:
            self.terrain_display_runner.invalidate()
            self._terrain_display_cache.clear()
            self._terrain_display_pending = None
            self._terrain_display_stopped = None
            self._terrain_display_running_key = None
            self._terrain_display_context = context

    def _request_terrain_display(self):
        key = (self._terrain_display_context, self.terrain_display_interval.value(),
               self.terrain_layers["generated_contours"].isChecked(), self.terrain_layers["boundary"].isChecked())
        self._terrain_display_desired_key = key
        if self._tin is None or key in self._terrain_display_cache or key == self._terrain_display_stopped:
            self._terrain_display_pending = None
            if self.terrain_display_runner.isRunning() and self._terrain_display_running_key != key:
                self.terrain_display_runner.invalidate()
                self._terrain_display_running_key = None
            return key
        if self.terrain_display_runner.isRunning() and self._terrain_display_running_key == key:
            return key
        self._terrain_display_pending = (key, self._tin)
        if self.terrain_display_runner.isRunning():
            self.terrain_display_runner.invalidate()
            self._terrain_display_running_key = None
        else:
            self._start_pending_terrain_display()
        return key

    def _start_pending_terrain_display(self):
        pending = self._terrain_display_pending
        if not pending or self.terrain_display_runner.isRunning() or self.workflow_stack.currentIndex() != 0:
            return
        key, tin = pending
        self._terrain_display_pending = None
        if tin is not self._tin or key[0] != self._terrain_display_context:
            return
        self._terrain_display_running_key = key
        self.terrain_display_status.setText("正在生成平面预览。")

        def work(token):
            from 土石方计算.io.terrain_display import build_terrain_display

            return build_terrain_display(tin, interval=key[1], include_contours=key[2],
                                         include_boundary=key[3], cancelled=lambda: token.is_cancelled)

        def done(display):
            if tin is not self._tin or key[0] != self._terrain_display_context:
                return
            self._terrain_display_running_key = None
            self._terrain_display_cache[key] = display
            while len(self._terrain_display_cache) > 2:
                self._terrain_display_cache.pop(next(iter(self._terrain_display_cache)))
            self._redraw_terrain_plan()

        def failed(error):
            self._terrain_display_running_key = None
            self._terrain_display_stopped = key
            self.terrain_display_status.setText("平面预览未完成：" + str(error))
            self._log("地形显示：" + str(error))

        self.terrain_display_runner.submit(work, on_success=done, on_error=failed)

    def _terrain_display_text(self, display, key):
        meta = display["metadata"]
        scope = self._terrain_identity.get("corridor_preparation") or {}
        width = scope.get("half_width_m")
        text = f"已加载线路两侧各 {width:g} m · " if width is not None else ""
        text += f"平面范围内 {meta['selected_face_count']:,} 个三角面"
        if self.terrain_layers["points"].isChecked():
            text += f" · 显示 {display['shown_point_count']:,} 个{display['point_label']}"
        if key[2]:
            text += f" · 显示等高距 {meta['display_interval']:g} m"
        if self.terrain_layers["anomalies"].isChecked() and display["unlocated_anomaly_count"]:
            text += f" · {display['unlocated_anomaly_count']} 处异常资料缺少原坐标"
        return text

    def _terrain_display_running_changed(self, running):
        self._update_terrain_display_action()
        if not running:
            self._terrain_display_running_key = None
            self._start_pending_terrain_display()

    def _update_terrain_display_action(self):
        has_terrain = self._tin is not None
        restoring = self.map_terrain_runner.isRunning()
        recovering = bool(self._pending_terrain_note or self._terrain_import_failed)
        self.terrain_display_range.setVisible(has_terrain)
        self.terrain_layer_button.setVisible(has_terrain)
        self.terrain_display_button.setVisible(has_terrain or restoring or recovering)
        if self.terrain_display_runner.isRunning():
            label = "停止预览"
        elif restoring:
            label = "停止读取"
        elif recovering:
            label = "重试地形"
        else:
            label = "刷新显示"
        self.terrain_display_button.setText(label)

    def _terrain_display_action(self):
        if self.terrain_display_runner.isRunning():
            self._terrain_display_stopped = self._terrain_display_desired_key
            self._terrain_display_pending = None
            self.terrain_display_runner.invalidate()
            self._terrain_display_running_key = None
            self.terrain_display_status.setText("已停止生成，可刷新显示。")
        elif self.map_terrain_runner.isRunning():
            self.map_terrain_runner.cancel()
        elif self._pending_terrain_note:
            self._retry_pending_terrain()
        elif self._terrain_import_failed and self._terrain_identity and self._map_restore_attempt:
            self._terrain_import_failed = False
            self._map_restore_attempt = None
            self._terrain_map_note = ""
            self._redraw_terrain_plan()
        elif self._terrain_import_failed and self.terrain_path.text():
            self._guard(lambda: self.load_terrain_path(self.terrain_path.text()))
        else:
            self._map_restore_attempt = None
            self._terrain_map_note = ""
            self._terrain_display_stopped = None
            self._terrain_display_cache.clear()
            self._redraw_terrain_plan()
