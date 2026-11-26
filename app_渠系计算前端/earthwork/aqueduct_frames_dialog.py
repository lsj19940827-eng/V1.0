"""Review aqueduct frame locations and terrain-derived column elevations."""
from __future__ import annotations

from copy import deepcopy
import math
import re
import uuid

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QStackedWidget, QTableWidget,
    QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from 土石方计算.services.aqueduct_frames import generate_aqueduct_frames
from 土石方计算.services.section_scheme_bindings import parse_station


class AqueductFramesDialog(QDialog):
    """The accepted ``asset`` contains layout, generated members and height proof.

    The caller supplies the current TIN and the owning route's analytic
    alignment.  Cancel leaves the source object intact.  Users can preview
    without accepting, and applying always recomputes from current inputs.
    """

    def __init__(self, asset, tin=None, *, alignment=None, station_prefix="K", initial_component="columns", parent=None):
        super().__init__(parent)
        self.asset = deepcopy(asset)
        self._source = deepcopy(asset)
        self._tin = tin
        self._alignment = alignment
        self._station_prefix = station_prefix or "K"
        self.initial_component = initial_component if initial_component in {"columns", "foundation"} else "columns"
        self._initial_component_focused = False
        config = deepcopy(asset.get("section", {}).get("aqueduct_frame_layout") or {})
        self._layout_id = config.get("layout_id")
        self._foundation_was_configured = "foundation" in config
        self.setWindowTitle("渡槽 · " + ("扩大基础" if self.initial_component == "foundation" else "排架柱") + "（联动设置）")
        self.resize(1080, 820)
        root = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        self._scroll_area = scroll
        body = QWidget(); layout = QVBoxLayout(body)
        scroll.setWidget(body); root.addWidget(scroll, 1)
        guide = QLabel("输入实际排架位置和柱截面，逐柱读取当前水面线净渠底与柱位地形。\n"
            "柱顶＝净渠底高程－净渠底至柱顶竖距；柱高＝柱顶－基础顶。\n"
            "基础顶可直接给定地面高差，也可由持力层顶、基础嵌入深度和基础厚度确定。"
            "净渠底至柱顶竖距按实际槽底、支座及盖梁填写。可同时生成柱身、扩大基础与基坑；梁和支座按实际另设。")
        guide.setWordWrap(True)
        layout.addWidget(guide)
        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("等间距布置", "interval")
        self.mode_combo.addItem("逐排指定桩号", "explicit")
        form.addRow("布置方式", self.mode_combo)
        self.station_pages = QStackedWidget()
        interval = QWidget()
        interval_form = QFormLayout(interval)
        self.start_edit = QLineEdit(self._text(config.get("station_start")))
        self.end_edit = QLineEdit(self._text(config.get("station_end")))
        self.spacing_edit = QLineEdit(self._text(config.get("spacing")))
        self.start_edit.setPlaceholderText("首排柱中心，例如 K0+015")
        self.end_edit.setPlaceholderText("布置上限，仅按完整间距设置，不自动增加末排")
        self.spacing_edit.setPlaceholderText("按设计填写，单位 m")
        interval_form.addRow("首排中心桩号", self.start_edit)
        interval_form.addRow("布置止桩号", self.end_edit)
        interval_form.addRow("排架间距（m）", self.spacing_edit)
        self.station_pages.addWidget(interval)
        explicit = QWidget()
        explicit_form = QFormLayout(explicit)
        self.stations_edit = QPlainTextEdit("\n".join(self._text(value) for value in config.get("stations", [])))
        self.stations_edit.setMaximumHeight(80)
        self.stations_edit.setPlaceholderText("每行一个中心桩号，也可用逗号分隔，例如 K0+015、K0+027")
        explicit_form.addRow("各排中心桩号", self.stations_edit)
        self.station_pages.addWidget(explicit)
        form.addRow(self.station_pages)
        self.mode_combo.currentIndexChanged.connect(self.station_pages.setCurrentIndex)
        index = max(0, self.mode_combo.findData(config.get("mode", "interval")))
        self.mode_combo.setCurrentIndex(index)
        self.station_pages.setCurrentIndex(index)
        self.top_deduction_edit = QLineEdit(self._text(config.get("invert_to_column_top_m")))
        self.foundation_offset_edit = QLineEdit(self._text(config.get("foundation_top_offset_m")))
        self.top_deduction_edit.setPlaceholderText("按实际槽底、支座及盖梁合计竖距填写，不小于0")
        self.foundation_offset_edit.setPlaceholderText("基础顶－柱位地面；低于地面为负，高于地面为正")
        form.addRow("净渠底至柱顶竖距（m）", self.top_deduction_edit)
        self.foundation_mode_combo = QComboBox()
        self.foundation_mode_combo.addItem("基础顶相对地面高差", "offset")
        self.foundation_mode_combo.addItem("扩大基础底进入强／弱风化持力层", "weathering")
        form.addRow("柱底高程确定方式", self.foundation_mode_combo)
        self.foundation_offset_label = QLabel("基础顶相对地面高差（m）")
        form.addRow(self.foundation_offset_label, self.foundation_offset_edit)
        layout.addLayout(form)
        weathering = config.get("weathering_foundation") or {}
        self.weathering_group = QGroupBox("按风化带确定扩大基础高程")
        weathering_form = QFormLayout(self.weathering_group)
        self.bearing_layer_combo = QComboBox()
        self.bearing_layer_combo.addItem("强风化层", "strong")
        self.bearing_layer_combo.addItem("弱风化层", "weak")
        self.bearing_layer_combo.setCurrentIndex(max(0, self.bearing_layer_combo.findData(weathering.get("bearing_layer", "strong"))))
        weathering_form.addRow("基础底进入的持力层", self.bearing_layer_combo)
        self.strong_top_depth_edit = QLineEdit(self._text(weathering.get("strong_top_depth_m")))
        self.strong_bottom_depth_edit = QLineEdit(self._text(weathering.get("strong_bottom_depth_m")))
        self.weak_bottom_depth_edit = QLineEdit(self._text(weathering.get("weak_bottom_depth_m")))
        self.embedment_edit = QLineEdit(self._text(weathering.get("embedment_m")))
        self.foundation_thickness_edit = QLineEdit(self._text(weathering.get("foundation_thickness_m")))
        self.strong_top_depth_edit.setPlaceholderText("距各柱位地表竖直向下的深度；露头可填0")
        self.strong_bottom_depth_edit.setPlaceholderText("强风化下限，同时作为弱风化顶界；必填")
        self.weak_bottom_depth_edit.setPlaceholderText("可不填；填写后校核基础底是否超出弱风化层")
        self.embedment_edit.setPlaceholderText("扩大基础底低于所选持力层顶界的竖直深度，不小于0")
        self.foundation_thickness_edit.setPlaceholderText("基础顶－基础底；按设计填写，大于0")
        self.strong_top_depth_label = QLabel()
        weathering_form.addRow(self.strong_top_depth_label, self.strong_top_depth_edit)
        weathering_form.addRow("强风化下限距地表（m，必填）", self.strong_bottom_depth_edit)
        weathering_form.addRow("弱风化下限距地表（m，可选）", self.weak_bottom_depth_edit)
        weathering_form.addRow("基础底进入持力层深度（m）", self.embedment_edit)
        weathering_form.addRow("扩大基础厚度（m）", self.foundation_thickness_edit)
        weathering_guide = QLabel("风化界面按用户给定的地表竖直偏移假定，不代表钻孔插值。"
            "强风化从其顶界起算，弱风化从强风化下限起算。\n"
            "生成完整基础时，按基础全范围的最低地面推算水平基底，并在全范围校核是否穿过持力层下限；"
            "基础顶＝基础底＋基础厚度。此处不代替承载力或结构设计。")
        weathering_guide.setWordWrap(True)
        weathering_form.addRow(weathering_guide)
        foundation = config.get("foundation") or {}
        self.foundation_enable_check = QCheckBox("同时生成扩大基础与基坑")
        self.foundation_enable_check.setChecked(bool(foundation.get("enabled")) if config else True)
        weathering_form.addRow(self.foundation_enable_check)
        self.foundation_parameters_toggle = QToolButton()
        self.foundation_parameters_toggle.setText("独立矩形扩大基础（每柱一座）与四侧基坑参数")
        self.foundation_parameters_toggle.setCheckable(True)
        self.foundation_parameters_toggle.setChecked(True)
        self.foundation_parameters_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        weathering_form.addRow(self.foundation_parameters_toggle)
        self.foundation_parameters_content = QWidget()
        foundation_form = QFormLayout(self.foundation_parameters_content)
        self.foundation_length_edit = QLineEdit(self._text(foundation.get("length_m")))
        self.foundation_width_edit = QLineEdit(self._text(foundation.get("width_m")))
        self.foundation_grade_edit = QLineEdit(self._text(foundation.get("grade")))
        self.foundation_length_edit.setPlaceholderText("扩大基础沿路线方向的实际长度；单位m")
        self.foundation_width_edit.setPlaceholderText("扩大基础横向实际宽度；单位m")
        self.foundation_grade_edit.setPlaceholderText("可后补；留空表示等级待明确，不沿用柱等级")
        foundation_form.addRow("扩大基础长（沿线，m）", self.foundation_length_edit)
        foundation_form.addRow("扩大基础宽（横向，m）", self.foundation_width_edit)
        self.foundation_thickness_value_label = QLabel()
        foundation_form.addRow("扩大基础厚（m）", self.foundation_thickness_value_label)
        self.foundation_thickness_edit.textChanged.connect(self._foundation_thickness_changed)
        self._foundation_thickness_changed()
        foundation_form.addRow("扩大基础材料", QLabel("混凝土"))
        foundation_form.addRow("基础混凝土等级", self.foundation_grade_edit)
        self.foundation_pit_table = QTableWidget(4, 3)
        self.foundation_pit_table.setHorizontalHeaderLabels(["基坑方向", "基础外工作面 m", "挖坡 1:m"])
        self.foundation_pit_table.verticalHeader().setVisible(False)
        self.foundation_pit_table.horizontalHeader().setStretchLastSection(True)
        self.foundation_pit_table.setMinimumHeight(155)
        self.foundation_pit_table.setMaximumHeight(175)
        self.foundation_pit_table.setColumnWidth(0, 180)
        self.foundation_pit_table.setColumnWidth(1, 220)
        pit = foundation.get("pit_construction") or {}
        for row, (side, label) in enumerate((("left", "左侧"), ("right", "右侧"), ("front", "前侧（大桩号）"), ("back", "后侧（小桩号）"))):
            item = QTableWidgetItem(label)
            item.setData(Qt.UserRole, side)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.foundation_pit_table.setItem(row, 0, item)
            for column, prefix in ((1, "working_space_"), (2, "excavation_slope_")):
                self.foundation_pit_table.setItem(row, column, QTableWidgetItem(self._text(pit.get(prefix+side))))
        foundation_form.addRow(self.foundation_pit_table)
        same_row = QHBoxLayout()
        self.foundation_same_space_edit = QLineEdit()
        self.foundation_same_slope_edit = QLineEdit()
        self.foundation_same_space_edit.setPlaceholderText("四侧工作面 m")
        self.foundation_same_slope_edit.setPlaceholderText("四侧挖坡 1:m")
        self.foundation_same_button = QPushButton("将这两个值填入四侧")
        self.foundation_same_button.clicked.connect(self._fill_foundation_pit_sides)
        same_row.addWidget(self.foundation_same_space_edit)
        same_row.addWidget(self.foundation_same_slope_edit)
        same_row.addWidget(self.foundation_same_button)
        foundation_form.addRow(same_row)
        self.foundation_pit_hint = QLabel("四侧工作面及坡比均须明确填写；竖直坡填0，不自动假定。基础厚度共用上方输入。")
        self.foundation_pit_hint.setWordWrap(True)
        foundation_form.addRow(self.foundation_pit_hint)
        weathering_form.addRow(self.foundation_parameters_content)
        layout.addWidget(self.weathering_group)
        self.foundation_mode_combo.currentIndexChanged.connect(self._foundation_mode_changed)
        self.bearing_layer_combo.currentIndexChanged.connect(self._foundation_mode_changed)
        self.foundation_enable_check.toggled.connect(self._foundation_mode_changed)
        self.foundation_parameters_toggle.toggled.connect(self._foundation_mode_changed)
        self.foundation_mode_combo.setCurrentIndex(max(0, self.foundation_mode_combo.findData(config.get("foundation_mode", "offset"))))
        self._foundation_mode_changed()
        extent = QLabel(f"当前渡槽区段：{self._text(asset.get('station_start'))}～{self._text(asset.get('station_end'))} m。"
            "桩号为柱中心；完整柱厚须在区段内。横偏距正值为路线右侧，负值为左侧。")
        extent.setWordWrap(True)
        layout.addWidget(extent)
        self.columns_table = QTableWidget(0, 6)
        self.columns_table.setHorizontalHeaderLabels(["每排柱名称", "横偏距 m", "横宽 m", "沿线厚度 m", "材料", "等级"])
        self.columns_table.horizontalHeader().setStretchLastSection(True)
        self.columns_table.setMinimumHeight(125)
        for column, width in ((0, 160), (1, 130), (2, 130), (3, 145), (4, 160)):
            self.columns_table.setColumnWidth(column, width)
        layout.addWidget(self.columns_table)
        actions = QHBoxLayout()
        self.add_button = QPushButton("每排增加一根柱")
        self.add_button.clicked.connect(lambda: self.add_column())
        self.remove_button = QPushButton("删除选中柱")
        self.remove_button.clicked.connect(self.remove_column)
        self.preview_button = QPushButton("读取地形并预览柱高")
        self.preview_button.clicked.connect(self.preview)
        actions.addWidget(self.add_button)
        actions.addWidget(self.remove_button)
        actions.addStretch()
        actions.addWidget(self.preview_button)
        layout.addLayout(actions)
        for column in config.get("columns", []):
            self.add_column(column)
        if not self.columns_table.rowCount():
            self.add_column()
        self.preview_table = QTableWidget(0, 16)
        self.preview_table.setHorizontalHeaderLabels(["排架桩号 m", "柱名称", "柱位 X", "柱位 Y", "净渠底 m", "柱位地面 m", "柱顶 / 柱底 m", "柱高 m",
            "强风化顶 m", "强风化下限／弱风化顶 m", "弱风化下限 m", "基础底 m", "基础顶 m",
            "基础长×宽×厚 m", "基础混凝土 m³", "基础范围地面 min / max m"])
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview_table.setMinimumHeight(150)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setColumnWidth(6, 155)
        self.preview_table.setColumnWidth(9, 195)
        self.preview_table.setColumnWidth(13, 190)
        self.preview_table.setColumnWidth(15, 230)
        layout.addWidget(self.preview_table, 1)
        self.status_label = QLabel("填写位置、截面和高程修正后预览；不会自动补入排架间距或柱尺寸。")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("生成构件并采用布置")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.buttons.accepted.connect(self.apply)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        if self.screen():
            available = self.screen().availableGeometry()
            self.resize(min(1080, available.width()-32), min(820, available.height()-70))
        if tin is None or getattr(tin, "is_empty", True):
            self.status_label.setText("当前工程尚未载入有效地形，不能生成排架柱高；请先载入地形后再设置。")

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_component_focused:
            self._initial_component_focused = True
            QTimer.singleShot(0, self._focus_initial_component)

    def _focus_initial_component(self):
        if self.initial_component == "foundation":
            self.foundation_parameters_toggle.setChecked(True)
            if self.foundation_mode_combo.currentData() != "weathering":
                target = self.foundation_mode_combo
            elif not self.foundation_enable_check.isChecked():
                target = self.foundation_enable_check
            else:
                target = self.foundation_length_edit
        else:
            target = self.columns_table
        anchor = self.foundation_parameters_toggle if target is self.foundation_length_edit else target
        self._scroll_area.ensureWidgetVisible(target, 0, 24)
        top = anchor.mapTo(self._scroll_area.widget(), anchor.rect().topLeft()).y()
        self._scroll_area.verticalScrollBar().setValue(max(0, top - 28))
        if target.isEnabled():
            target.setFocus(Qt.OtherFocusReason)

    @staticmethod
    def _text(value):
        return "" if value is None else f"{value:.12g}" if isinstance(value, (int, float)) else str(value)

    def _foundation_mode_changed(self, *_):
        weathering = self.foundation_mode_combo.currentData() == "weathering"
        self.foundation_offset_label.setEnabled(not weathering)
        self.foundation_offset_edit.setEnabled(not weathering)
        self.weathering_group.setEnabled(weathering)
        self.weathering_group.setVisible(weathering)
        foundation = weathering and self.foundation_enable_check.isChecked()
        self.foundation_parameters_toggle.setEnabled(foundation)
        self.foundation_parameters_toggle.setVisible(self.foundation_enable_check.isChecked())
        self.foundation_parameters_toggle.setArrowType(Qt.DownArrow if self.foundation_parameters_toggle.isChecked() else Qt.RightArrow)
        self.foundation_parameters_content.setVisible(foundation and self.foundation_parameters_toggle.isChecked())
        required = self.bearing_layer_combo.currentData() == "strong"
        self.strong_top_depth_label.setText("强风化顶界距地表（m，必填）" if required else "强风化顶界距地表（m，可选）")

    def _foundation_thickness_changed(self, *_):
        text = self.foundation_thickness_edit.text().strip()
        self.foundation_thickness_value_label.setText(f"{text or '待填写'}（共用上方“扩大基础厚度”）")

    def _fill_foundation_pit_sides(self):
        space, slope = self.foundation_same_space_edit.text().strip(), self.foundation_same_slope_edit.text().strip()
        if not space or not slope:
            self.foundation_pit_hint.setText("请先填写同值工作面和坡比，再填入四侧；不会自动补0。")
            return
        for row in range(self.foundation_pit_table.rowCount()):
            self.foundation_pit_table.item(row, 1).setText(space)
            self.foundation_pit_table.item(row, 2).setText(slope)
        self.foundation_pit_hint.setText("四侧已填入上述值，仍可逐侧修改；尺寸和坡比须符合实际施工条件。")

    def add_column(self, column=None):
        data = deepcopy(column or {})
        data.setdefault("column_id", "column-"+uuid.uuid4().hex[:12])
        row = self.columns_table.rowCount()
        self.columns_table.insertRow(row)
        for col, key in enumerate(("name", "offset", "width", "length")):
            item = QTableWidgetItem(self._text(data.get(key)))
            if col == 0:
                item.setData(Qt.UserRole, data)
            self.columns_table.setItem(row, col, item)
        material = QComboBox()
        for label, key in (("混凝土", "concrete"), ("钢材", "steel"), ("浆砌石", "masonry")):
            material.addItem(label, key)
        value = data.get("material", "concrete")
        if material.findData(value) < 0:
            material.addItem(str(value), value)
        material.setCurrentIndex(material.findData(value))
        self.columns_table.setCellWidget(row, 4, material)
        self.columns_table.setItem(row, 5, QTableWidgetItem(self._text(data.get("grade"))))

    def remove_column(self):
        row = self.columns_table.currentRow()
        if row >= 0:
            self.columns_table.removeRow(row)

    def layout_values(self):
        mode = self.mode_combo.currentData()
        result = {"mode": mode, "invert_to_column_top_m": self.top_deduction_edit.text().strip(),
                  "foundation_mode": self.foundation_mode_combo.currentData(), "columns": []}
        if result["foundation_mode"] == "weathering":
            result["weathering_foundation"] = {"bearing_layer": self.bearing_layer_combo.currentData(),
                "strong_top_depth_m": self.strong_top_depth_edit.text().strip() or None,
                "strong_bottom_depth_m": self.strong_bottom_depth_edit.text().strip(),
                "weak_bottom_depth_m": self.weak_bottom_depth_edit.text().strip() or None,
                "embedment_m": self.embedment_edit.text().strip(),
                "foundation_thickness_m": self.foundation_thickness_edit.text().strip()}
            if self.foundation_enable_check.isChecked():
                pit = {"bedding_thickness": 0., "bedding_extension": 0.}
                for row in range(self.foundation_pit_table.rowCount()):
                    side = self.foundation_pit_table.item(row, 0).data(Qt.UserRole)
                    for column, prefix in ((1, "working_space_"), (2, "excavation_slope_")):
                        pit[prefix+side] = self.foundation_pit_table.item(row, column).text().strip()
                result["foundation"] = {"enabled": True, "length_m": self.foundation_length_edit.text().strip(),
                    "width_m": self.foundation_width_edit.text().strip(), "material": "concrete",
                    "grade": self.foundation_grade_edit.text().strip(), "pit_construction": pit}
            elif self._foundation_was_configured:
                result["foundation"] = {"enabled": False}
        else:
            result["foundation_top_offset_m"] = self.foundation_offset_edit.text().strip()
        if self._layout_id:
            result["layout_id"] = self._layout_id
        def station(text):
            return parse_station(text.strip(), prefix=self._station_prefix)
        if mode == "interval":
            result.update(station_start=station(self.start_edit.text()), station_end=station(self.end_edit.text()),
                          spacing=self.spacing_edit.text().strip())
        else:
            values = [value for value in re.split(r"[,，、;；\s]+", self.stations_edit.toPlainText().strip()) if value]
            result["stations"] = [station(value) for value in values]
        for row in range(self.columns_table.rowCount()):
            data = deepcopy(self.columns_table.item(row, 0).data(Qt.UserRole) or {})
            for col, key in enumerate(("name", "offset", "width", "length")):
                data[key] = self.columns_table.item(row, col).text().strip()
            data["material"] = self.columns_table.cellWidget(row, 4).currentData()
            data["grade"] = self.columns_table.item(row, 5).text().strip()
            result["columns"].append(data)
        return result

    def _generate(self):
        if self._tin is None or getattr(self._tin, "is_empty", True):
            self.preview_table.setRowCount(0)
            self.status_label.setText("当前工程尚未载入有效地形，不能生成排架柱高；请先载入地形后再设置。")
            self.status_label.setStyleSheet("color:#AC4537;")
            return None
        try:
            updated = generate_aqueduct_frames(self._source, self._tin, layout=self.layout_values(), alignment=self._alignment)
        except (ValueError, TypeError) as error:
            self.preview_table.setRowCount(0)
            self.status_label.setText(str(error))
            self.status_label.setStyleSheet("color:#AC4537;")
            return None
        members = {item["component_id"]: item for item in updated["section"]["discrete_components"]}
        rows = updated["section"]["aqueduct_frame_layout"]["generated_snapshot"]["columns"]
        self.preview_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            member = members[values["component_id"]]
            texts = [f"{values['station']:.3f}", member["name"], f"{values['xy'][0]:.3f}", f"{values['xy'][1]:.3f}",
                f"{values['inner_invert_elevation']:.3f}", f"{values['terrain_elevation']:.3f}",
                f"{values['top_elevation']:.3f} / {values['bottom_elevation']:.3f}", f"{values['height_m']:.3f}"]
            texts.extend("—" if values.get(key) is None else f"{values[key]:.3f}" for key in (
                "strong_top_elevation", "strong_bottom_elevation", "weak_bottom_elevation",
                "foundation_bottom_elevation", "foundation_top_elevation"))
            dimensions = [values.get(key) for key in ("foundation_length_m", "foundation_width_m", "foundation_thickness_m")]
            texts.append("×".join(f"{value:.3f}" for value in dimensions) if all(isinstance(value, (int, float)) for value in dimensions) else "—")
            texts.append(f"{values['foundation_volume_m3']:.3f}" if isinstance(values.get("foundation_volume_m3"), (int, float)) else "—")
            footprint = values.get("foundation_footprint") or {}
            extremes = [footprint.get("terrain_min_elevation"), footprint.get("terrain_max_elevation")]
            texts.append(" / ".join(f"{value:.3f}" for value in extremes) if all(isinstance(value, (int, float)) for value in extremes) else "—")
            for col, value in enumerate(texts):
                self.preview_table.setItem(row, col, QTableWidgetItem(value))
        volume = math.fsum(members[values["component_id"]]["width"]*(members[values["component_id"]]["station_end"]-members[values["component_id"]]["station_start"])*
            (members[values["component_id"]]["top_elevation"]-members[values["component_id"]]["bottom_elevation"]) for values in rows)
        foundations = [values for values in rows if values.get("foundation_component_id")]
        scope = (f"同时生成 {len(foundations)} 个扩大基础，基础混凝土 {math.fsum(values['foundation_volume_m3'] for values in foundations):.3f} m³；基坑挖填随正式算量计算。"
                 if foundations else "当前仅生成柱身；基础与基坑未生成。")
        if foundations and not updated["section"]["aqueduct_frame_layout"].get("foundation", {}).get("grade"):
            scope+="基础混凝土等级待明确。"
        self.status_label.setText(f"已取高 {len(rows)} 根柱，柱身体积合计 {volume:.3f} m³。{scope}梁和支座按实际另设。")
        self.status_label.setStyleSheet("")
        self._scroll_area.ensureWidgetVisible(self.preview_table, 0, 8)
        return updated

    def preview(self):
        return self._generate()

    def apply(self):
        updated = self._generate()
        if updated is not None:
            self.asset = updated
            self.accept()
