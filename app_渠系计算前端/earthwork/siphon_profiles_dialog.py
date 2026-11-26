"""Review and set the construction axis of every siphon in the workbench."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .profile_file import DXF_PROFILE_FILTER, read_profile_file


MODES = (
    ("自动优先采用轴线，缺轴线按覆土", "auto"),
    ("按源桩号或等长匹配", "exact"),
    ("按起桩对齐", "align_start"),
    ("按终桩对齐", "align_end"),
    ("按管顶覆土生成", "cover_depth"),
    ("暂列待计", "pending"),
)
MODE_LABELS = dict((key, label) for label, key in MODES)
STATUS_LABELS = {
    "actual": "已匹配", "aligned": "已对齐", "cover_estimate": "按覆土估算",
    "cover_generated": "覆土轴线已生成", "mismatch": "桩号待核对", "pending": "待计", "missing": "缺轴线",
}


def siphon_rows(inputs):
    from 土石方计算.services.siphon_axis_choices import is_siphon_axis_asset

    return [(network, asset) for network in inputs.get("networks", [])
            for asset in network.get("assets", []) if is_siphon_axis_asset(asset)]


def _station(value):
    rounded = round(value * 1000)
    sign = "-" if rounded < 0 else ""
    kilometres, millimetres = divmod(abs(rounded), 1_000_000)
    return f"{sign}K{kilometres}+{millimetres / 1000:07.3f}"


def _span(values):
    if not values or any(value is None for value in values):
        return "—"
    return " ～ ".join(_station(float(value)) for value in values)


class SiphonProfilesDialog(QDialog):
    """Persist only the settings applied by the user, one object at a time."""

    def __init__(self, inputs, parent=None):
        super().__init__(parent)
        from 土石方计算.services.siphon_axis_choices import describe_siphon_axis
        self.rows = siphon_rows(inputs)
        self.changed_assets = {}
        self.reports = [describe_siphon_axis(asset) for _, asset in self.rows]
        self.setWindowTitle("倒虹吸桩号对齐与暂列待计")
        self.resize(1130, 650)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(len(self.rows), 7)
        self.table.setObjectName("siphonProfilesTable")
        self.table.setHorizontalHeaderLabels(["倒虹吸 / 线路", "计量桩号", "源轴线桩号", "轴线来源",
                                              "长度差 m", "计量方式", "状态"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((175, 185, 185, 130, 82, 175)):
            self.table.setColumnWidth(column, width)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        self.editor = QGroupBox("当前倒虹吸")
        form = QFormLayout(self.editor)
        self.mode = QComboBox()
        self.mode.setObjectName("siphonProfileMode")
        self.mode.setPlaceholderText("选择桩号处理方式")
        for label, key in MODES:
            if key not in {"cover_depth","auto"}:
                self.mode.addItem(label, key)
        self.mode.setMaximumWidth(440)
        self.mode.setToolTip("按起桩或终桩对齐时，平移源桩号并裁切或延续端部坡度。")
        form.addRow("桩号处理", self.mode)
        import_row = QHBoxLayout()
        import_row.addWidget(QLabel("管道中心线（米）"))
        self.import_button = QPushButton("导入 DXF")
        self.import_button.setObjectName("siphonImportProfile")
        self.import_button.clicked.connect(self._import_file)
        import_row.addWidget(self.import_button)
        import_row.addStretch()
        form.addRow("补充轴线", import_row)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(self.details)
        layout.addWidget(self.editor)

        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setText("应用设置")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.accept)
        buttons.button(QDialogButtonBox.Cancel).setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.table.currentCellChanged.connect(self._load_selection)
        self.mode.currentIndexChanged.connect(self._update_choice)
        for row in range(len(self.rows)):
            self._display_row(row)
        self._refresh_summary()
        if self.rows:
            self.table.selectRow(0)
        else:
            self.editor.setEnabled(False)

    def _asset(self, row):
        return self.changed_assets.get(row, self.rows[row][1])

    def _display_row(self, row):
        network, _ = self.rows[row]
        asset, report = self._asset(row), self.reports[row]
        name = str(asset.get("name") or asset.get("asset_id") or "")
        route = str(network.get("name") or "")
        cover = report.get("cover_depth_m")
        mode = MODE_LABELS.get(report.get("mode"), MODE_LABELS["auto"])
        if cover is not None and (report.get("status") in {"cover_estimate", "cover_generated"}
                                  or report.get("mode") == "cover_depth"):
            mode = f"管顶覆土 {cover:g} m"
        difference = report.get("length_difference_m")
        difference_label = "—" if difference is None else f"{difference:+.3f}" if round(difference, 3) else "0.000"
        values = (
            f"{name}\n{route}" if route and route != name else name,
            _span(report.get("asset_station_range_m")),
            _span(report.get("axis_station_range_m")),
            report.get("source_label") or "—",
            difference_label,
            mode,
            STATUS_LABELS.get(report.get("status"), report.get("message") or "待核对"),
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip((report.get("message") or value) if column == 6 else value)
            self.table.setItem(row, column, item)
        self.table.setRowHeight(row, 44)

    def _refresh_summary(self):
        statuses = [report.get("status") for report in self.reports]
        axes = statuses.count("actual") + statuses.count("aligned")
        estimates = statuses.count("cover_estimate") + statuses.count("cover_generated")
        self.summary.setText(f"倒虹吸 {len(statuses)} 项 · 采用轴线 {axes} 项 · 覆土估算 {estimates} 项 · 待核或待计 {len(statuses) - axes - estimates} 项")

    def _load_selection(self, *_):
        row = self.table.currentRow()
        if row < 0:
            return
        report = self.reports[row]
        with QSignalBlocker(self.mode):
            self.mode.setCurrentIndex(self.mode.findData(report.get("mode")))
        source = report.get("source") or {}
        adjustment = report.get("adjustment") or {}
        details = [report.get("message"), source.get("filename") or source.get("path")]
        for key, label in (("station_offset_m", "桩号平移"), ("trim_start_m", "起端裁切"),
                           ("trim_end_m", "终端裁切"), ("extend_start_m", "起端延伸"),
                           ("extend_end_m", "终端延伸")):
            delta = adjustment.get(key)
            if delta is not None and abs(delta) > .001:
                details.append(f"{label} {delta:+.3f} m")
        self.details.setText(" · ".join(part for part in details if part))

    def _set_choice(self, row, mode, **source):
        from 土石方计算.services.siphon_axis_choices import configure_siphon_axis

        asset = deepcopy(self._asset(row))
        report = configure_siphon_axis(asset, mode=mode, strict=False, **source)
        self.changed_assets[row] = asset
        self.reports[row] = report
        self._display_row(row)
        self._load_selection()
        self._refresh_summary()
        self.apply_button.setEnabled(True)

    def _update_choice(self, *_):
        row = self.table.currentRow()
        if row >= 0:
            try:
                self._set_choice(row, self.mode.currentData())
            except (ValueError, TypeError, KeyError) as error:
                self.details.setText(str(error))

    def _import_file(self):
        row = self.table.currentRow()
        if row < 0:
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入倒虹吸纵断面轴线", "",
                                              DXF_PROFILE_FILTER)
        if not path:
            return
        try:
            profile, source, _ = read_profile_file(path, reference="pipe_axis", units="m", dxf_only=True)
            source["kind"] = "quantity_dxf"
            source["filename"] = Path(path).name
            mode = self.mode.currentData()
            if mode in {None, "pending"}:
                mode = "exact"
            self._set_choice(row, mode, profile=profile, source=source, source_units="m")
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.details.setText(str(error))
