"""Calculation confirmation, result review, and delivery for the workbench."""
from filesystem_paths import filesystem_path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSizePolicy,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from .choice_display import ChoiceDisplay
from .section_preparation import (
    _display_routes, building_display_name, flow_section_label, pending_connection_entries, route_identity,
)


def _saved_buildings(source):
    buildings = {(route_identity(network), str(asset["asset_id"])): asset
                 for network in source.get("networks", ()) for asset in network.get("assets", ())
                 if asset.get("asset_id")}
    buildings.update({("independent_pits", str(asset["asset_id"])): asset
                      for asset in source.get("pits", ()) if asset.get("asset_id")})
    return buildings


def _result_building_name(row, buildings):
    route = str(row.get("route_id") or row.get("network_id") or "")
    for field in ("original_asset_id", "asset_id"):
        asset = buildings.get((route, str(row.get(field) or "")))
        if asset is not None:
            break
    asset = asset or row
    return " · ".join(filter(None, (building_display_name(asset), flow_section_label(asset.get("flow_section")))))


def _label(text="", *, wrap=False, heading=False):
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(wrap)
    if heading:
        label.setStyleSheet("font-size:16px;font-weight:600;color:#17365D")
    return label


class _QuantityTable(QTableWidget):
    _minimum_widths = ()

    def fit_result(self, rows, numeric_columns):
        font = self.fontMetrics()
        em = font.horizontalAdvance("量")
        widths = []
        for column in range(self.columnCount()):
            heading = self.horizontalHeaderItem(column)
            heading.setTextAlignment((Qt.AlignRight if column in numeric_columns else Qt.AlignHCenter) | Qt.AlignVCenter)
            header_width = self.horizontalHeader().fontMetrics().horizontalAdvance(heading.text()) + 20
            natural = max((font.horizontalAdvance(str(row[column])) for row in rows), default=0) + 16
            if column < 2:
                natural = min(max(natural, 7 * em), 16 * em)
            elif column in numeric_columns:
                natural = max(natural, font.horizontalAdvance("100,000.000") + 16)
            widths.append(max(natural, header_width, self.horizontalHeader().minimumSectionSize()))
        self._minimum_widths = widths
        self._distribute_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._distribute_width()

    def _distribute_width(self):
        if not self._minimum_widths:
            return
        spare = max(0, self.viewport().width() - sum(self._minimum_widths))
        weights = (3, 3, 3, 2, 2, 2)
        used = 0
        for column, (width, weight) in enumerate(zip(self._minimum_widths, weights)):
            extra = spare - used if column == len(weights) - 1 else spare * weight // sum(weights)
            self.setColumnWidth(column, width + extra)
            used += extra


def _table(headers, stretch, table_type=QTableWidget):
    table = table_type(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    header = table.horizontalHeader()
    header.setMinimumSectionSize(48)
    header.setSectionResizeMode(QHeaderView.ResizeToContents)
    for column in stretch:
        header.setSectionResizeMode(column, QHeaderView.Stretch)
    return table


def _fill(table, rows, numeric_columns=()):
    table.setRowCount(len(rows))
    for index, values in enumerate(rows):
        for column, value in enumerate(values):
            text = str(value)
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            if column in numeric_columns:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(index, column, item)


def _confirmation_rows(readiness):
    rows = []
    ready_label = "资料齐备" if readiness.has_draft else "本次计量"
    for entry in readiness.rows:
        row = entry.row
        terrain = set(entry.terrain_spans)
        bores = set(entry.bore_spans)
        for spans, status, label in (
            (entry.ready_spans, "ready", ready_label),
            (entry.pending_spans, "pending", "待更新设计" if readiness.design_stale else "待补"),
            (entry.excluded_spans, "excluded", "本次不计"),
        ):
            for span in spans:
                detail = label
                if status == "pending" and span in terrain:
                    detail = "待补地形"
                elif status == "ready" and span in bores:
                    detail = f"{ready_label} · 非开挖"
                rows.append((row.route_name, row.name, span, detail, status))
    return tuple(rows)


def _range_text(start, end):
    return f"{start:.3f} ～ {end:.3f}" if start is not None and end is not None else "—"


def _result_span(row, prefixes):
    from 土石方计算.services.section_scheme_bindings import format_station

    start, end = row.get("station_start"), row.get("station_end")
    if start is None or end is None:
        return "—"
    if row.get("coordinate_kind") == "pit_local_slice" or row.get("route_id") == "independent_pits":
        return f"{_range_text(start, end)} m"
    prefix = prefixes.get(str(row.get("route_id") or row.get("network_id") or ""), "K")
    return f"{format_station(start, prefix)} ～ {format_station(end, prefix)}"


class WorkbenchResultsMixin:
    def _build_results_page(self):
        from .workbench_panel import default_delivery_root

        self._results_calculating = False
        self._results_preparing = False
        self._results_preparation_key = None
        self._rendered_result = None
        self._result_scope_targets = []
        self._result_review_rows = ()
        self._historical_review_id = None
        self._result_setting_mode = ""
        self._skipped_section_message = None

        self.results_page = QWidget()
        self.results_page.setObjectName("workbenchResults")
        self.results_page.setStyleSheet("""
            QWidget#workbenchResults QPushButton[confirmationPrimary="true"] {
                background:#3346A2;color:#FFFFFF;border-color:#3346A2;font-weight:600;}
            QWidget#workbenchResults QPushButton[confirmationPrimary="true"]:hover {background:#27377E;}
            QWidget#workbenchResults QPushButton[confirmationPrimary="true"]:disabled {
                color:#79879A;background:#F7F8FB;border-color:#DDE3EB;}
        """)
        page = QVBoxLayout(self.results_page)
        page.setContentsMargins(0, 0, 0, 0)
        title_row = QHBoxLayout()
        self.results_title = _label("确认算量范围", heading=True)
        title_row.addWidget(self.results_title, 1)
        self.results_history_button = QPushButton("返回上次成果")
        self.results_history_button.clicked.connect(self._view_historical_result)
        title_row.addWidget(self.results_history_button)
        self.results_recalculate_button = QPushButton("确认算量范围")
        self.results_recalculate_button.clicked.connect(lambda: self._guard(self._open_workbench_readiness_action))
        title_row.addWidget(self.results_recalculate_button)
        page.addLayout(title_row)

        self.result_states = QStackedWidget()
        page.addWidget(self.result_states, 1)
        self.result_preflight = QWidget()
        preflight = QVBoxLayout(self.result_preflight)
        preflight.setContentsMargins(0, 0, 0, 0)
        self.result_states.addWidget(self.result_preflight)
        confirmation_header = QHBoxLayout()
        self.preflight_count = _label("", wrap=True)
        confirmation_header.addWidget(self.preflight_count, 1)
        self.results_source_button = QPushButton()
        self.results_source_button.setProperty("workspaceAction", True)
        self.results_source_button.clicked.connect(self._return_to_results_source)
        confirmation_header.addWidget(self.results_source_button)
        self.result_scope_button = QPushButton("调整计量范围")
        self.result_scope_button.setProperty("workspaceAction", True)
        self.result_scope_button.clicked.connect(lambda: self._guard(self._open_section_scope, notice="计量范围"))
        confirmation_header.addWidget(self.result_scope_button)
        preflight.addLayout(confirmation_header)
        self.result_preflight_table = _table(("线路", "建筑物", "计量区段", "本次范围"), (1,))
        self.result_preflight_table.setAccessibleName("本次计量范围")
        self.result_preflight_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.result_preflight_table.setColumnWidth(0, 138)
        preflight.addWidget(self.result_preflight_table, 3)
        self.results_task_table = _table(("待补事项", "区段", "处理"), (0,))
        self.results_task_table.setAccessibleName("待补事项")
        self.results_task_table.setMinimumHeight(100)
        preflight.addWidget(self.results_task_table, 2)
        self.results_draft_button = QPushButton("处理未应用修改")
        self.results_draft_button.setProperty("workspaceAction", True)
        self.results_draft_button.clicked.connect(lambda: self._guard(
            lambda: self._open_workbench_readiness_action("draft")))
        preflight.addWidget(self.results_draft_button)
        self.result_preflight_empty = QWidget()
        preflight.addWidget(self.result_preflight_empty, 1)
        self.results_progress_page = QWidget()
        running = QVBoxLayout(self.results_progress_page)
        running.addWidget(_label("正在计算本次计量范围。", wrap=True))
        running.addStretch()
        self.result_states.addWidget(self.results_progress_page)

        self.result_tabs = QTabWidget()
        self.result_states.addWidget(self.result_tabs)
        quantities_page = QWidget()
        quantities = QVBoxLayout(quantities_page)
        quantities.setContentsMargins(6, 7, 6, 6)
        self.result_metrics = _label("", wrap=True)
        self.result_metrics.setStyleSheet("font-weight:600;padding:8px;background:#EDF3F8;color:#17365D")
        quantities.addWidget(self.result_metrics)
        self.result_metric_strip = QWidget()
        metric_strip = QHBoxLayout(self.result_metric_strip)
        metric_strip.setContentsMargins(0, 0, 0, 0)
        self.result_metric_values = {}
        for key, label in (("excavation_volume", "开挖"), ("backfill_volume", "回填"), ("embankment_volume", "填筑")):
            tile = QFrame()
            tile.setStyleSheet("QFrame {background:#EDF3F8;border-radius:5px;} QLabel {color:#17365D;}")
            metric = QVBoxLayout(tile)
            metric.setContentsMargins(11, 6, 11, 6)
            metric.setSpacing(1)
            metric.addWidget(_label(label))
            value = self.result_metric_values[key] = _label()
            value.setStyleSheet("font-size:20px;font-weight:600")
            metric.addWidget(value)
            metric_strip.addWidget(tile, 1)
        quantities.addWidget(self.result_metric_strip)
        self.summary = _label("尚无计算成果", wrap=True)
        self.summary.hide()  # The full status remains available to the workbench and process records.
        quantities.addWidget(self.summary)
        self.result_basis = _label("", wrap=True)
        quantities.addWidget(self.result_basis)
        self.result_quantity_heading = _label("分建筑物工程量", heading=True)
        quantities.addWidget(self.result_quantity_heading)
        self.result_quantity_table = _table(
            ("线路", "建筑物", "起止桩号", "开挖（m³）", "回填（m³）", "填筑（m³）"), (), _QuantityTable)
        self.result_quantity_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.result_quantity_table.setWordWrap(False)
        self.result_quantity_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        quantities.addWidget(self.result_quantity_table, 3)
        self.result_quantity_table.cellDoubleClicked.connect(self._review_quantity_row)
        issue_header = QHBoxLayout()
        self.result_issue_heading = _label("本次未计范围", heading=True)
        issue_header.addWidget(self.result_issue_heading, 1)
        self.result_locate_button = QPushButton("查看选中区段")
        self.result_locate_button.clicked.connect(lambda: self._locate_result_issue(self.result_issue_table.currentRow()))
        issue_header.addWidget(self.result_locate_button)
        quantities.addLayout(issue_header)
        self.result_issue_table = _table(("事项", "线路 / 建筑物", "范围（m）", "长度（m）"), (1,))
        self.result_issue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.result_issue_table.setColumnWidth(0, 180)
        self.result_issue_table.cellDoubleClicked.connect(lambda row, _column: self._locate_result_issue(row))
        self.result_issue_table.itemSelectionChanged.connect(self._refresh_issue_action)
        quantities.addWidget(self.result_issue_table, 2)
        detail_actions = QHBoxLayout()
        self.component_button = QPushButton("材料构件明细")
        self.component_button.clicked.connect(lambda: self._guard(self.show_component_quantities, notice="材料构件明细"))
        detail_actions.addWidget(self.component_button)
        self.trenchless_button = QPushButton("非开挖洞挖明细")
        self.trenchless_button.clicked.connect(lambda: self._guard(self.show_trenchless_quantities, notice="非开挖洞挖明细"))
        detail_actions.addWidget(self.trenchless_button)
        detail_actions.addStretch()
        quantities.addLayout(detail_actions)
        self.result_tabs.addTab(quantities_page, "工程量")

        review_page = QWidget()
        self.result_review_layout = QVBoxLayout(review_page)
        self.result_review_layout.setContentsMargins(6, 7, 6, 6)
        review_header = QHBoxLayout()
        review_header.addWidget(_label("建筑物"))
        self.result_review_picker = QComboBox()
        self.result_review_picker.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.result_review_picker.setMinimumContentsLength(14)
        self.result_review_picker.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.result_review_picker.setPlaceholderText("未计区段")
        self.result_review_picker.currentIndexChanged.connect(self._select_result_review_row)
        self.result_review_display = ChoiceDisplay(self.result_review_picker, wrap=True)
        review_header.addWidget(self.result_review_display, 1)
        self.result_restore_review_button = QPushButton("返回已计断面")
        self.result_restore_review_button.clicked.connect(self._return_to_measured_sections)
        self.result_restore_review_button.hide()
        review_header.addWidget(self.result_restore_review_button)
        self.result_review_layout.addLayout(review_header)
        self.result_tabs.addTab(review_page, "断面复核")

        self.result_files_page = QWidget()
        files = QVBoxLayout(self.result_files_page)
        files.setContentsMargins(6, 7, 6, 6)
        self.result_file_status = _label("", wrap=True)
        files.addWidget(self.result_file_status)
        self.result_files_table = _table(("文件", "内容"), (0, 1))
        files.addWidget(self.result_files_table, 1)
        file_actions = QHBoxLayout()
        self.file_delivery_button = QPushButton()
        self.export_button = self.file_delivery_button  # Handle used by desktop diagnostics.
        self.file_delivery_button.clicked.connect(self._activate_delivery_action)
        self._style_step_button(self.file_delivery_button, "#246BCE", "#1859B1")
        file_actions.addWidget(self.file_delivery_button)
        self.retry_delivery_button = QPushButton("重新生成完整成果")
        self.retry_delivery_button.setToolTip("重新生成工程量表和图纸，保存到新目录。")
        self.retry_delivery_button.clicked.connect(lambda: self._guard(self.choose_export_all, notice="保存成果"))
        self.retry_delivery_button.hide()
        file_actions.addWidget(self.retry_delivery_button)
        file_actions.addStretch()
        files.addLayout(file_actions)
        self.result_tabs.addTab(self.result_files_page, "成果文件")

        # Calculation settings and delivery settings have separate purposes.
        self.sampling_controls = QWidget()
        sampling = QHBoxLayout(self.sampling_controls)
        sampling.setContentsMargins(0, 0, 0, 0)
        sampling.addWidget(_label("计算横断面最大间距"))
        self.step = QDoubleSpinBox()
        self.step.setRange(.25, 10000)
        self.step.setValue(20)
        self.step.setSuffix(" m")
        self.step.setToolTip("弯道自动加密，新断面同时参与算量与开挖包络。")
        sampling.addWidget(self.step)
        self.sampling_note = _label("", wrap=True)
        sampling.addWidget(self.sampling_note, 1)
        page.addWidget(self.sampling_controls)
        self.step.valueChanged.connect(self._invalidate)
        self.step.valueChanged.connect(self._sampling_changed)
        self._sampling_changed()

        self.result_save_controls = QWidget()
        saving = QHBoxLayout(self.result_save_controls)
        saving.setContentsMargins(0, 0, 0, 0)
        saving.addWidget(_label("成果目录"))
        self.output_directory = QLineEdit(str(default_delivery_root()))
        self.output_directory.setToolTip("每次保存整套成果时新建目录。")
        saving.addWidget(self.output_directory, 1)
        self.output_directory_button = QPushButton("更改")
        self.output_directory_button.clicked.connect(self.choose_output_directory)
        saving.addWidget(self.output_directory_button)
        self.auto_delivery = QCheckBox("算完自动保存成果")
        self.auto_delivery.setChecked(True)
        self.auto_delivery.toggled.connect(self._refresh_results_stage)
        saving.addWidget(self.auto_delivery)
        self.drawing_settings_button = QPushButton("出图设置")
        self.drawing_settings_button.clicked.connect(lambda: self._guard(self.drawing_settings))
        saving.addWidget(self.drawing_settings_button)
        page.addWidget(self.result_save_controls)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        page.addWidget(line)
        footer = QHBoxLayout()
        self.results_settings_note = _label("", wrap=True)
        footer.addWidget(self.results_settings_note, 1)
        self.results_interval_button = QPushButton("计算设置")
        self.results_interval_button.clicked.connect(lambda: self._toggle_results_settings("calculation"))
        footer.addWidget(self.results_interval_button)
        self.results_delivery_settings_button = QPushButton("成果设置")
        self.results_delivery_settings_button.clicked.connect(lambda: self._toggle_results_settings("delivery"))
        footer.addWidget(self.results_delivery_settings_button)
        self.calculate_button = QPushButton("开始算量")
        self.calculate_button.clicked.connect(lambda: self._guard(self._start_from_confirmation, notice="算量准备"))
        self._style_step_button(self.calculate_button, "#168267", "#106B54")
        footer.addWidget(self.calculate_button)
        self.open_delivery_button = QPushButton()
        self.open_delivery_button.clicked.connect(self._activate_delivery_action)
        footer.addWidget(self.open_delivery_button)
        self.records_toggle = QToolButton()
        self.records_toggle.setText("过程记录")
        self.records_toggle.setCheckable(True)
        footer.addWidget(self.records_toggle)
        page.addLayout(footer)
        self.result_details = QWidget()
        records = QVBoxLayout(self.result_details)
        records.setContentsMargins(0, 0, 0, 0)
        self.messages = QPlainTextEdit()
        self.messages.setReadOnly(True)
        self.messages.setMaximumHeight(94)
        records.addWidget(self.messages)
        self.records_toggle.toggled.connect(self.result_details.setVisible)
        self.result_details.hide()
        page.addWidget(self.result_details)
        self.result_tabs.currentChanged.connect(self._refresh_results_stage)
        self.sampling_controls.hide()
        self.result_save_controls.hide()
        return self.results_page

    def _toggle_results_settings(self, mode):
        self._result_setting_mode = "" if self._result_setting_mode == mode else mode
        self._refresh_results_stage()

    def _view_historical_result(self):
        self._results_preparing = False
        self._refresh_results_stage()

    def _show_calculation_confirmation(self):
        self._results_preparing = True
        self._refresh_results_stage()

    def _return_to_results_source(self):
        readiness = self._workbench_readiness()
        action = "design" if readiness.action == "design" else readiness.terrain_action
        if action:
            return self._open_workbench_readiness_action(action)

    def _start_from_confirmation(self):
        if self._workbench_readiness().can_calculate:
            return self.start_calculation()

    def _activate_delivery_action(self):
        if self._delivery_action_opens_directory:
            return self._guard(self.open_delivery_directory)
        return self._guard(self.choose_export_all, notice="保存成果")

    def _refresh_results_stage(self, *_, readiness=None):
        if not hasattr(self, "results_settings_note"):
            return
        busy = getattr(self, "_ui_busy", False) or self.runner.isRunning()
        complete = self._result is not None and not (self._results_preparing or self._results_calculating)
        before = not complete and not self._results_calculating
        if before or complete:
            readiness = readiness or self._workbench_readiness()
        if self._results_calculating:
            stage = self.results_progress_page
            title = "正在算量"
        elif complete:
            stage = self.result_tabs
            title = "算量完成" if self._valid else "上次成果 · 需重算"
        else:
            stage = self.result_preflight
            title = "确认算量范围" if readiness.can_calculate else "算量准备"
        self.result_states.setCurrentWidget(stage)
        self.results_title.setText(title)
        self.results_history_button.setVisible(before and self._result is not None)
        self.result_review_picker.setEnabled(not busy)
        self.result_restore_review_button.setEnabled(not busy)
        if hasattr(self, "station_spin"):
            self.station_spin.setReadOnly(busy or self._viewing_historical_result())
        files_tab = self.result_tabs.currentWidget() is self.result_files_page
        self.results_interval_button.setVisible(before)
        self.results_delivery_settings_button.setVisible(before or (complete and files_tab))
        if not before:
            self.calculate_button.hide()
        self.sampling_controls.setVisible(before and self._result_setting_mode == "calculation")
        self.result_save_controls.setVisible(self.results_delivery_settings_button.isVisibleTo(self.results_page)
                                             and self._result_setting_mode == "delivery")
        saved = bool(complete and self.last_delivery_path and filesystem_path(self.last_delivery_path).is_dir())
        self._delivery_action_opens_directory = saved
        can_manage_delivery = complete and (saved or self._valid)
        action_text = "保存全部成果"
        if saved:
            action_text = "打开成果目录" if self._valid else "打开上次成果目录"
        for button in (self.file_delivery_button, self.open_delivery_button):
            button.setText(action_text)
            button.setEnabled(can_manage_delivery and not busy)
        self.file_delivery_button.setVisible(can_manage_delivery)
        self.open_delivery_button.setVisible(can_manage_delivery and not files_tab)
        self.retry_delivery_button.setEnabled(saved and self._valid and not busy)
        self.results_settings_note.setVisible(complete or before)
        note = ""
        if before and readiness.has_design:
            saving = "计算后自动保存" if self.auto_delivery.isChecked() else "计算后手动保存"
            note = f"最大间距 {self.step.value():g} m · 弯道自动加密 · {saving}"
        elif saved:
            note = "已有整套成果目录" if self._valid else "上次成果已保存"
        self.results_settings_note.setText(note)
        self.results_recalculate_button.setVisible(complete)
        if complete:
            self.results_recalculate_button.setText(self._workbench_action_text(readiness))
            self.results_recalculate_button.setEnabled(not busy)
            self._refresh_result_display(saved)
        elif before:
            self._refresh_calculation_confirmation(busy, readiness)

    def _refresh_calculation_confirmation(self, busy, readiness):
        tasks = readiness.snapshot.tasks
        rows = _confirmation_rows(readiness)
        ready_label = "资料齐备" if readiness.has_draft else "本次可算"
        self.preflight_count.setText(
            f"{ready_label} {readiness.ready_count} 个对象　　待补 {readiness.pending_count} 个　　不计 {readiness.excluded_count} 个"
            if rows else "尚未读取设计资料")
        self.result_preflight_table.setVisible(bool(rows))
        self.result_preflight_empty.setVisible(not rows)
        key = (rows, tasks)
        if key != self._results_preparation_key:
            _fill(self.result_preflight_table, [row[:4] for row in rows])
            for index, row in enumerate(rows):
                item = self.result_preflight_table.item(index, 3)
                item.setForeground(QColor({"ready": "#16664C", "pending": "#895514", "excluded": "#526177"}[row[4]]))
            self.results_task_table.setRowCount(0)
            _fill(self.results_task_table, [(f"{task.route_name} · {task.name} · {task.message}", task.span, "")
                                           for task in tasks])
            for index, task in enumerate(tasks):
                button = QPushButton(task.action_label)
                button.clicked.connect(lambda _, item=task: self._guard(lambda: self._open_section_task(item), notice="施工待补"))
                self.results_task_table.setCellWidget(index, 2, button)
            self._results_preparation_key = key
        self.results_task_table.setVisible(bool(tasks))
        self.results_task_table.setEnabled(not busy)
        action = readiness.action
        self.results_draft_button.setVisible(action == "draft")
        self.results_draft_button.setEnabled(not busy)
        source_action = "design" if action == "design" else readiness.terrain_action
        self.results_source_button.setVisible(source_action is not None)
        self.results_source_button.setEnabled(not busy)
        if source_action is not None:
            self.results_source_button.setText(self._workbench_action_text(readiness, action=source_action))
        self.calculate_button.setVisible(readiness.can_calculate)
        self.calculate_button.setEnabled(not busy and readiness.can_calculate)
        submission_labels = {"partial_bore": "先算非开挖洞挖", "partial_ready": "先算已就绪区段"}
        self.calculate_button.setText(submission_labels.get(action, "开始算量"))
        has_scope = any(row.parts for row in readiness.snapshot.rows)
        self.result_scope_button.setVisible(has_scope)
        self.result_scope_button.setEnabled(has_scope and not busy)
        for button, primary in (
            (self.results_source_button, action == source_action),
            (self.result_scope_button, action == "scope"),
            (self.results_draft_button, action == "draft"),
        ):
            if button.property("confirmationPrimary") != primary:
                button.setProperty("confirmationPrimary", primary)
                button.style().unpolish(button)
                button.style().polish(button)
                button.update()

    def _refresh_review_picker(self):
        historical = self._viewing_historical_result()
        detached = bool(self._skipped_section_message and self.result_review_picker.currentIndex() < 0)
        if historical:
            source = self._result.get("assets") or self._result.get("rows") or []
            inputs = (self._result.get("inputs") or {}).get("workbench") or {}
            buildings = _saved_buildings(inputs)
            names = {key: name for key, (_, name) in _display_routes(inputs, self._source_channel_name).items()}
            rows = tuple((asset.get("asset_id"), names.get(str(asset.get("route_id"))) or asset.get("network_name")
                          or str(asset.get("route_id") or ""), _result_building_name(asset, buildings),
                          _range_text(asset.get("station_start"), asset.get("station_end")))
                         for asset in source if asset.get("asset_id") in self._section_groups)
            selection = self._historical_review_id
        else:
            names = {row.route_id: row.route_name for row in self._section_preparation().rows}
            rows = tuple((index, names.get(route_identity(network), str((network or {}).get("name") or "")),
                          building_display_name(asset),
                          _range_text(asset.get("station_start"), asset.get("station_end")))
                         for index, (network, asset) in enumerate(self._all_assets()))
            selection = self.table.currentRow()
        picker = self.result_review_picker
        picker.blockSignals(True)
        if rows != self._result_review_rows:
            picker.clear()
            for key, *parts in rows:
                picker.addItem(" · ".join(value for value in parts if value), key)
            self._result_review_rows = rows
        index = picker.findData(selection)
        picker.setCurrentIndex(-1 if detached else max(0, index) if historical and rows else index)
        picker.setToolTip(picker.currentText())
        picker.blockSignals(False)
        self.result_review_display.refresh()
        if detached:
            self.query_button.setEnabled(False)
        elif historical and picker.currentData() != self._historical_review_id:
            self._restore_review_records()

    def _select_result_review_row(self, _):
        row = self.result_review_picker.currentData()
        if self._viewing_historical_result():
            self._restore_review_records()
        elif row is not None and row == self.table.currentRow():
            self._selection_changed()
        elif row is not None:
            self.table.selectRow(row)

    def _viewing_historical_result(self):
        return self._result is not None and not (self._valid or self._results_preparing or self._results_calculating)

    def _restore_review_records(self):
        if self._viewing_historical_result():
            self._historical_review_id = self.result_review_picker.currentData()
            self._set_review_records(self._historical_review_id)
        else:
            self._selection_changed()

    def _return_to_measured_sections(self):
        station = self.station_spin.value()
        self._restore_review_records()
        if self._records:
            nearest = min(range(len(self._records)), key=lambda i: abs(self._records[i]["station"] - station))
            self.slider.setValue(nearest)

    def _refresh_result_display(self, saved):
        payload = self._result
        basis = (payload.get("quantity_basis") or {}).get("label", "")
        from .workbench_panel import result_scope_prefix
        headline = result_scope_prefix(payload).rstrip("；") or basis or ("TEST" if payload.get("test_only") else "")
        section_count = len(payload.get("sections") or [])
        if section_count:
            headline = " · ".join(filter(None, (f"{section_count:,} 个计算断面", headline)))
        self.result_basis.setText(headline)
        self.result_basis.setVisible(bool(headline))
        saved_path = self.last_delivery_path if saved else ""
        failures = self._refresh_result_files(bool(section_count), saved_path)
        self.retry_delivery_button.setVisible(self._valid and bool(failures))
        status = saved_path or ("成果待保存" if self._valid else "按当前输入完成算量后可保存成果。")
        if failures:
            status += "\n待补导图纸 " + "、".join(failures)
            self.results_settings_note.setText("工程量表已保存，部分图纸待补导")
        self.result_file_status.setText(status)
        self.result_file_status.setToolTip(self.result_file_status.text())
        self._refresh_review_picker()
        if payload is self._rendered_result:
            self._refresh_issue_action()
            return
        self._rendered_result = payload
        self._populate_quantity_result(payload)

    def _populate_quantity_result(self, payload):
        from 土石方计算.io.structure_quantity_tables import trenchless_summary_columns

        validation = payload.get("validation") or {}
        bore_only = validation.get("trenchless_only")
        gate_only = validation.get("sluice_gate_only")
        no_sections = any(validation.get(key) for key in ("automatic_terrain_unmeasured_only",
                          "automatic_unsupported_only", "automatic_tunnel_exposed_only"))
        bore_rows = payload.get("trenchless_excavation_rows") or []
        notes = ["本次无已计施工断面"] if no_sections else []
        if (payload.get("special_pipe_materials") or {}).get("length_mode_active"):
            notes.append("特殊材料按录入长度计量，土方保留原断面依据。")
            if payload.get("all_concrete_volume") is not None:
                notes.append(f"混凝土合计（含管座、包封） {payload['all_concrete_volume']:,.3f} m³")
        if bore_rows:
            notes.extend(f"{name}  {payload[key]:,.3f} m³" for key, name in trenchless_summary_columns(payload)
                         if payload.get(key) is not None)
            pending_bores = sum(item.get("trenchless_excavation_volume") is None for item in bore_rows)
            if pending_bores:
                notes.append(f"{pending_bores} 段洞挖待补资料")
        if gate_only:
            notes.append(f"闸室混凝土 {payload['all_concrete_volume']:,.3f} m³")
        self.result_metrics.setText("　 · 　".join(notes))
        self.result_metrics.setVisible(bool(notes))
        self.result_metric_strip.setVisible(not (no_sections or bore_only or gate_only))
        for key, label in self.result_metric_values.items():
            label.setText(f"{payload[key]:,.3f} m³" if payload.get(key) is not None else "—")
        rows = payload.get("assets") or payload.get("rows") or []
        self._result_quantity_rows = rows
        source = (payload.get("inputs") or {}).get("workbench") or {}
        buildings = _saved_buildings(source)
        route_names = {key: name for key, (_, name) in _display_routes(source, self._source_channel_name).items()}
        prefixes = {route_identity(network): network.get("station_prefix") or "K"
                    for network in source.get("networks", ())}

        def amount(row, key):
            return f"{row[key]:,.3f}" if row.get(key) is not None else "—"

        if bore_rows and not rows:
            self.result_quantity_heading.setText("非开挖洞挖明细")
            headers = ("线路", "建筑物", "起止桩号", "施工方式", "洞挖（m³）", "状态")
            numeric_columns = (4,)
            table_rows = []
            for item in bore_rows:
                route = str(item.get("route_id") or item.get("network_id") or "")
                status = "已计" if item.get("trenchless_excavation_volume") is not None else "待补资料"
                table_rows.append((route_names.get(route, route), _result_building_name(item, buildings),
                                   _result_span(item, prefixes),
                                   item.get("construction_method") or "—", amount(item, "trenchless_excavation_volume"), status))
        else:
            self.result_quantity_heading.setText("分建筑物工程量")
            mixed_positions = any(row.get("coordinate_kind") == "pit_local_slice"
                                  or row.get("route_id") == "independent_pits" for row in rows)
            headers = ("线路", "建筑物", "桩号 / 局部位置" if mixed_positions else "起止桩号",
                       "开挖（m³）", "回填（m³）", "填筑（m³）")
            numeric_columns = (3, 4, 5)
            table_rows = [(route_names.get(str(row.get("route_id")), row.get("network_name", "")),
                           _result_building_name(row, buildings), _result_span(row, prefixes),
                           amount(row, "excavation_volume"), amount(row, "backfill_volume"), amount(row, "embankment_volume"))
                          for row in rows]
        self.result_quantity_table.setHorizontalHeaderLabels(headers)
        _fill(self.result_quantity_table, table_rows, numeric_columns)
        self.result_quantity_table.fit_result(table_rows, numeric_columns)
        self.result_quantity_heading.setVisible(bool(table_rows))
        self.result_quantity_table.setVisible(bool(table_rows))
        self.component_button.setVisible(bool(payload.get("quantity_items")))
        self._populate_result_issues(payload, route_names)

    def _refresh_result_files(self, has_sections, saved_path):
        key = (has_sections, saved_path)
        if key == getattr(self, "_result_files_key", None):
            return self._result_drawing_failures

        from 土石方计算.services.workbench_delivery import read_delivery_manifest
        manifest = read_delivery_manifest(saved_path)
        failures = manifest.get("drawing_failures")
        if not isinstance(failures, dict):
            failures = {}
        files = [("工程量.xlsx", "分建筑物工程量、结构形式汇总及区段明细")]
        if has_sections:
            files.append(("施工断面.dxf", "施工断面与面积"))
            recorded = {record.get("path") for record in manifest.get("files") or () if isinstance(record, dict)}
            recorded.update(failures)
            if "开挖线.dxf" in recorded and "挖填平面外包络.dxf" not in recorded:
                files.append(("开挖线.dxf", "开挖开口线"))
            else:
                files.append(("挖填平面外包络.dxf", "开挖开口线、填筑边界线和挖填联合包络线"))
        failures = {name: failures[name] for name, _ in files if name in failures}
        _fill(self.result_files_table, [
            (name, f"待补导 · {failures[name]}" if name in failures else description)
            for name, description in files
        ])
        self._result_files_key = key
        self._result_drawing_failures = failures
        return failures

    def _populate_result_issues(self, payload, route_names):
        from 土石方计算.io.unsupported_range_tables import skipped_range_building_name
        from 土石方计算.services.earthwork_scope import is_trenchless_exclusion
        from 土石方计算.services.unmeasured_terrain_scope import AUTOMATIC_TERRAIN_GAP_CODE
        from 土石方计算.services.unsupported_pipe_scope import AUTOMATIC_UNSUPPORTED_PIPE_CODE

        output = []
        targets = []
        seen = set()
        inputs = payload.get("inputs") or {}
        for item in payload.get("excluded_assets") or []:
            code = item.get("code")
            start, end = item.get("station_start"), item.get("station_end")
            route = str(item.get("route_id") or item.get("network_id") or "")
            name = item.get("name") or item.get("building_name") or item.get("asset_id") or "未命名建筑物"
            if code in (AUTOMATIC_TERRAIN_GAP_CODE, AUTOMATIC_UNSUPPORTED_PIPE_CODE):
                name = skipped_range_building_name(item, inputs)
            elif name in ("-", "—", "/", "未命名"):
                name = item.get("source_type") or ("倒虹吸" if item.get("kind") == "siphon" else "有压管道")
            source = item.get("source_asset_id") or item.get("parent_asset_id") or item.get("asset_id") or name
            if code in (AUTOMATIC_TERRAIN_GAP_CODE, AUTOMATIC_UNSUPPORTED_PIPE_CODE):
                kind = "地形缺测" if code == AUTOMATIC_TERRAIN_GAP_CODE else "悬空"
                label = kind
            elif code == "tunnel_exposed" and item.get("scope_status") == "automatic_excluded_interval":
                kind = "隧洞露顶待计"
                label = "待计 · " + (item.get("reason") or "隧洞开挖轮廓出露原地面")
            elif item.get("scope_status") == "automatic_deferred":
                kind = "pending"
                label = "待补 · " + (item.get("reason") or "施工资料")
            elif is_trenchless_exclusion(item):
                continue
            else:
                kind = ""
                label = "本次不计"
            key = (kind, route, source, start, end)
            if key in seen:
                continue
            seen.add(key)
            line = route_names.get(route) or item.get("route_name") or item.get("network_name") or route
            place = " / ".join(str(value) for value in (line, name) if value)
            length = f"{end-start:,.3f}" if start is not None and end is not None else "—"
            output.append((label, place, _range_text(start, end), length))
            targets.append((kind, item))
        source = (payload.get("inputs") or {}).get("workbench") or {}
        displayed_routes = _display_routes(source, self._source_channel_name)
        for candidate, row in pending_connection_entries(source, displayed_routes, self._source_channel_name):
            start, end = candidate.get("station_start"), candidate.get("station_end")
            length = f"{end-start:,.3f}" if start is not None and end is not None else "—"
            output.append((f"待补 · {row.detail}", f"{row.route_name} / {row.name}", _range_text(start, end), length))
            targets.append(("transition", candidate))
        self._result_scope_targets = targets
        _fill(self.result_issue_table, output)
        self.result_issue_table.setVisible(bool(output))
        self.result_issue_heading.setVisible(bool(output))
        self.result_locate_button.setVisible(any(kind for kind, _ in targets))
        if output:
            self.result_issue_table.selectRow(0)
        self._refresh_issue_action()

    def _refresh_issue_action(self):
        row = self.result_issue_table.currentRow()
        kind = self._result_scope_targets[row][0] if 0 <= row < len(self._result_scope_targets) else ""
        pending = kind in {"pending", "transition"}
        self.result_locate_button.setEnabled(bool(kind) and not (pending and self._viewing_historical_result()))
        self.result_locate_button.setText("处理所选待补事项" if pending else "查看选中区段")

    def _select_result_asset(self, asset_id, route_id=None, source_id=None):
        fallback = None
        for index, (network, asset) in enumerate(self._all_assets()):
            if route_id and str(route_id) != self._result_route_id(network):
                continue
            if asset_id is not None and self._measured_asset_id(network, asset) == asset_id:
                fallback = index
                break
            if fallback is None and source_id and source_id in (
                    asset.get("asset_id"), asset.get("source_asset_id"), asset.get("parent_asset_id"),
                    (asset.get("automatic_unsupported_pipe_origin") or {}).get("source_asset_id"),
                    (asset.get("automatic_terrain_gap_origin") or {}).get("source_asset_id"),
                    (asset.get("automatic_tunnel_exposure_origin") or {}).get("source_asset_id")):
                fallback = index
        if fallback is None:
            return False
        self.table.selectRow(fallback)
        self._restore_review_records()
        self._refresh_review_picker()
        return True

    def _review_quantity_row(self, row, _column):
        if 0 <= row < len(self._result_quantity_rows):
            item = self._result_quantity_rows[row]
            self.result_tabs.setCurrentIndex(1)
            if self._viewing_historical_result():
                self.result_review_picker.setCurrentIndex(self.result_review_picker.findData(item.get("asset_id")))
                self._restore_review_records()
            else:
                self._select_result_asset(item.get("asset_id"), item.get("route_id"), item.get("original_asset_id"))

    def _locate_result_issue(self, row):
        if not 0 <= row < len(self._result_scope_targets):
            return
        kind, item = self._result_scope_targets[row]
        if kind == "transition":
            if not self._viewing_historical_result():
                self._guard(lambda: self.open_transition_connections(candidate_id=item["candidate_id"]), notice="连接段设置")
        elif kind == "pending":
            if self._viewing_historical_result():
                return
            route = str(item.get("route_id") or "")
            task = next((task for task in self._section_preparation().tasks
                         if task.route_id == route and task.asset_id == item.get("asset_id")), None)
            if task:
                self._guard(lambda: self._open_section_task(task), notice="施工待补")
            elif item.get("code") in {"missing_terrain", "section_terrain_unavailable"}:
                self._navigate_workflow(0, prepare=False)
                self.terrain_button.setFocus()
                self.workflow_hint.setText(f"{self.result_issue_table.item(row, 1).text()} · {item.get('reason') or '计算地形待补'}。"
                                           "请导入覆盖该区段的地形后重新算量。")
                self.workflow_hint.show()
            else:
                self._guard(lambda: self._open_section_preparation_item(route, item.get("asset_id")), notice="施工待补")
        elif kind:
            self.result_tabs.setCurrentIndex(1)
            source = item.get("source_asset_id") or item.get("parent_asset_id") or item.get("asset_id")
            if self._viewing_historical_result():
                index = self.result_review_picker.findData(source)
                selected = index >= 0
                self.result_review_picker.setCurrentIndex(index)
            else:
                selected = self._select_result_asset(item.get("asset_id"), item.get("route_id"), source)
            if not selected:
                self.result_review_picker.blockSignals(True)
                self.result_review_picker.setCurrentIndex(-1)
                self.result_review_picker.blockSignals(False)
                self.result_review_display.refresh()
            self.view_combo.setCurrentIndex(self.view_combo.findData("section"))
            start, end = item["station_start"], item["station_end"]
            self.station_spin.setValue(start)
            place = self.result_issue_table.item(row, 1).text()
            has_records = selected and bool(self._records)
            self._show_skipped_section({"message": f"{place} · {kind} · "
                                                   f"{_range_text(start, end)} m（{end-start:.3f} m）"})
            self.result_restore_review_button.setVisible(has_records)
            if not selected:
                self.query_button.setEnabled(False)
