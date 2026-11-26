"""Editable support schedules, separate from hydraulic section bindings."""
from __future__ import annotations

from copy import deepcopy
import json
import math
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)

from 土石方计算.services.slope_support_quantities import (
    TYPE_LABELS, calculate_slope_support_quantities, default_slope_support_parameters)


PARAMETERS = (
    ("slope_width_m", "坡面展开宽（m，优先采用）"),
    ("height_m", "或：竖直坡高（m）"),
    ("slope_ratio", "坡比 1:m 中的 m"),
    ("shotcrete_thickness_m", "喷混凝土厚度（m）"),
    ("drain_inner_width_m", "排水沟净宽（m）"),
    ("drain_inner_depth_m", "排水沟净深（m）"),
    ("drain_thickness_m", "排水沟混凝土厚度（m）"),
)
ITEMS = {
    "vegetation": ("草皮/喷播绿化", "vegetation", "", "m2"),
    "frame_beam": ("框格梁混凝土", "concrete", "C25", "m3"),
    "planting_soil": ("回填耕植土", "planting_soil", "", "m3"),
    "frame_rebar": ("框格梁钢筋", "steel", "", "kg"),
    "shotcrete": ("喷生态混凝土", "shotcrete", "C25W8F100", "m3"),
    "mesh": ("挂网净面积", "steel_mesh", "φ6@20cm", "m2"),
    "anchors_3m": ("3m锚杆", "steel", "φ22", "m"),
    "anchors_6m": ("6m锚杆", "steel", "φ22", "m"),
    "pvc_drainage": ("PVC排水管", "pvc", "D5cm", "m"),
    "anchor_grouting": ("锚杆灌浆", "grout", "", "m3"),
    "drain_concrete": ("排水沟混凝土", "concrete", "C20", "m3"),
    "mesh_lap_loss": ("挂网搭接增量", "steel_mesh", "φ6@20cm", "m2"),
}
TYPE_ITEMS = {
    "A": ("vegetation", "drain_concrete"),
    "B": ("vegetation", "frame_beam", "planting_soil", "frame_rebar", "drain_concrete"),
    "C": ("shotcrete", "anchors_3m", "pvc_drainage", "anchor_grouting", "drain_concrete"),
    "D": ("shotcrete", "mesh", "anchors_3m", "anchors_6m", "pvc_drainage", "anchor_grouting", "drain_concrete", "mesh_lap_loss"),
}


class SlopeSupportDialog(QDialog):
    def __init__(self, inputs, parent=None, *, initial_type="A"):
        super().__init__(parent)
        self.setWindowTitle("边坡支护数量 · 按类型和长度")
        self.resize(1160, 810)
        self.updated_inputs = deepcopy(inputs)
        self.rows = deepcopy(inputs.get("slope_support_rows", []))
        self.templates = deepcopy(inputs.get("slope_support_templates", []))
        self._editing_id = None
        self._loading = False
        root = QVBoxLayout(self)
        intro = QLabel("首次填写坡面展开宽，或坡高与坡比；也可填写每延米清单并保存为模板。以后选模板、填长度即可。单侧长度×两侧会计两倍；已填总长度时请选择单侧。")
        intro.setWordWrap(True)
        root.addWidget(intro)
        split = QSplitter()
        root.addWidget(split, 1)
        left = QWidget(); left_layout = QVBoxLayout(left)
        self.rows_table = QTableWidget(0, 4)
        self.rows_table.setHorizontalHeaderLabels(["名称", "类型", "单侧长度m", "侧数"])
        self.rows_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rows_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rows_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.rows_table.cellClicked.connect(self._select_row)
        left_layout.addWidget(self.rows_table)
        bar = QHBoxLayout()
        for text, callback in (("新增记录", self._new_row), ("删除选中记录", self._delete_row)):
            button = QPushButton(text); button.clicked.connect(callback); bar.addWidget(button)
        left_layout.addLayout(bar)
        self.result_text = QPlainTextEdit(); self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(230)
        left_layout.addWidget(self.result_text)
        split.addWidget(left)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        right = QWidget(); form = QFormLayout(right)
        self.type_choice = QComboBox()
        for code, label in TYPE_LABELS.items(): self.type_choice.addItem(label, code)
        form.addRow("支护类型", self.type_choice)
        self.template_choice = QComboBox(); form.addRow("复用模板", self.template_choice)
        self.name_edit = QLineEdit(); form.addRow("记录名称", self.name_edit)
        self.length_edit = QLineEdit(); self.length_edit.setPlaceholderText("必填，m")
        form.addRow("单侧沿线长度（m）", self.length_edit)
        self.side_choice = QComboBox(); self.side_choice.addItem("单侧 / 已汇总总长", 1); self.side_choice.addItem("相同构造的左右两侧", 2)
        form.addRow("计量侧数", self.side_choice)
        self.parameter_edits = {}
        for key, label in PARAMETERS:
            edit = QLineEdit(); edit.setPlaceholderText("留空表示待补")
            self.parameter_edits[key] = edit; form.addRow(label, edit)
        self.drain_check = QCheckBox("计入排水沟（尺寸或每米指标明确后计算）")
        form.addRow(self.drain_check)
        hint = QLabel("每延米指标可覆盖上面的几何计算。新指标留空采用几何公式或列为缺项；清空已引用模板的指标会列为待补。单位m表示每米支护对应的构件总长度，count表示每米支护对应的根数。平台和多级坡须按实际范围分别配置。")
        hint.setWordWrap(True); form.addRow(hint)
        self.rates_table = QTableWidget(0, 6)
        self.rates_table.setHorizontalHeaderLabels(["分项", "材质", "等级", "工程量单位", "每米支护的工程量", "编号"])
        self.rates_table.horizontalHeaderItem(4).setToolTip("填每1m单侧支护对应的工程量；例如锚杆单位m填总杆长/m，单位count填根/m。不是每根长度。")
        self.rates_table.setMinimumHeight(225)
        self.rates_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.rates_table.setColumnHidden(5, True)
        form.addRow(self.rates_table)
        self.template_name = QLineEdit(); self.template_name.setPlaceholderText("保存后可重复使用")
        form.addRow("模板名称", self.template_name)
        save_template = QPushButton("将当前构造保存为模板"); save_template.clicked.connect(self._save_template)
        form.addRow(save_template)
        self.save_row_button = QPushButton("保存本条记录"); self.save_row_button.clicked.connect(self._save_row)
        form.addRow(self.save_row_button)
        scroll.setWidget(right); split.addWidget(scroll); split.setSizes([440, 690])
        self.error = QLabel(); self.error.setWordWrap(True); self.error.setStyleSheet("color:#A63E2F")
        root.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("采用清单并返回看板")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._finish); buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.type_choice.currentIndexChanged.connect(self._type_changed)
        self.template_choice.currentIndexChanged.connect(self._template_changed)
        self.type_choice.setCurrentIndex(max(0, self.type_choice.findData(initial_type)))
        self._new_row(); self._refresh_rows()
        screen = self.screen()
        if screen: self.resize(min(1160, screen.availableGeometry().width()-32), min(810, screen.availableGeometry().height()-70))

    @staticmethod
    def _number(text, label, *, positive=False):
        try: value = float(text)
        except ValueError: raise ValueError(label + "须填写数字") from None
        if not math.isfinite(value) or value < 0 or positive and value <= 0:
            raise ValueError(label + ("须为有限正数" if positive else "须为有限非负数"))
        return value

    def _refresh_templates(self):
        self.template_choice.blockSignals(True)
        self.template_choice.clear(); self.template_choice.addItem("不引用模板 / 当前构造", None)
        for template in self.templates:
            if template["type"] == self.type_choice.currentData():
                self.template_choice.addItem(template.get("name", template["id"]), template["id"])
        self.template_choice.blockSignals(False)

    def _set_rates(self, items=()):
        chosen = {item["component_id"]: item for item in items}
        keys = list(dict.fromkeys([*TYPE_ITEMS[self.type_choice.currentData()], *chosen]))
        self.rates_table.setRowCount(len(keys))
        for row, key in enumerate(keys):
            default = ITEMS.get(key, (key, "", "", "m3")); item = chosen.get(key, {})
            values = (item.get("name", default[0]), item.get("material", default[1]),
                item.get("grade", default[2]), item.get("unit", default[3]), item.get("quantity_per_m", ""), key)
            for column, value in enumerate(values):
                cell = QTableWidgetItem("" if value is None else str(value))
                if column == 3:
                    cell.setToolTip("工程量单位：m3体积、m2面积、m构件总长、kg质量、count根数；系数均按每米支护填写。")
                if column == 5: cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.rates_table.setItem(row, column, cell)

    def _type_changed(self):
        if self._loading: return
        self._refresh_templates()
        self._set_parameters(default_slope_support_parameters(self.type_choice.currentData()))
        self._set_rates()

    def _set_parameters(self, parameters):
        for key, edit in self.parameter_edits.items():
            edit.setText(str(parameters[key]) if parameters.get(key) is not None else "")
        self.drain_check.setChecked(parameters.get("drain_enabled", True))

    def _template_changed(self):
        if self._loading: return
        template = next((t for t in self.templates if t["id"] == self.template_choice.currentData()), None)
        if template:
            self._set_parameters({**default_slope_support_parameters(template["type"]), **template.get("parameters", {})})
            self._set_rates(template.get("per_m_items", []))
            self.template_name.setText(template.get("name", ""))

    def _new_row(self):
        self._editing_id = None; self.rows_table.clearSelection(); self.rows_table.setCurrentCell(-1, -1)
        self.name_edit.clear(); self.length_edit.clear(); self.template_name.clear()
        self.side_choice.setCurrentIndex(0); self._type_changed(); self.error.clear()

    def _read_construction(self):
        parameters = {"drain_enabled": self.drain_check.isChecked()}
        for key, edit in self.parameter_edits.items():
            # A blank is an explicit missing value. Omitting it would restore
            # the old dimension from the referenced template during merging.
            parameters[key] = (self._number(edit.text().strip(), dict(PARAMETERS)[key])
                               if edit.text().strip() else None)
        template = next((t for t in self.templates if t["id"] == self.template_choice.currentData()), {})
        inherited = {item["component_id"] for item in template.get("per_m_items", [])}
        items = []
        for row in range(self.rates_table.rowCount()):
            values = [self.rates_table.item(row, col).text().strip() for col in range(6)]
            if not values[4] and values[5] not in inherited: continue
            if values[3] not in {"m3", "m2", "m", "kg", "count"}: raise ValueError("计量单位须为m3、m2、m、kg或count")
            items.append(dict(zip(("name", "material", "grade", "unit"), values[:4]),
                component_id=values[5], quantity_per_m=(self._number(values[4], values[0]+"每延米指标") if values[4] else None)))
        return parameters, items

    def _read_row(self):
        parameters, items = self._read_construction()
        row = {"id": self._editing_id or "support_"+uuid.uuid4().hex[:16],
            "type": self.type_choice.currentData(), "name": self.name_edit.text().strip() or self.type_choice.currentText(),
            "length_m": self._number(self.length_edit.text().strip(), "支护长度", positive=True),
            "side_count": self.side_choice.currentData(), "parameters": parameters, "per_m_items": items}
        if self.template_choice.currentData(): row["template_id"] = self.template_choice.currentData()
        return row

    def _save_row(self):
        try:
            row = self._read_row()
            proposed = [deepcopy(x) for x in self.rows if x["id"] != row["id"]]
            index = next((i for i, x in enumerate(self.rows) if x["id"] == row["id"]), len(proposed))
            proposed.insert(index, row)
            calculate_slope_support_quantities({"slope_support_rows": proposed, "slope_support_templates": self.templates})
        except (ValueError, TypeError) as error:
            self.error.setText(str(error)); return False
        self.rows = proposed; self._editing_id = row["id"]
        self.error.setText("本条已保存；清单中的缺项仍会明确列出。")
        self._refresh_rows(); return True

    def _save_template(self):
        try:
            name = self.template_name.text().strip()
            if not name: raise ValueError("请填写模板名称")
            parameters, items = self._read_construction()
            existing = next((t for t in self.templates if t.get("name") == name and t["type"] == self.type_choice.currentData()), None)
            template = {"id": existing["id"] if existing else "support_template_"+uuid.uuid4().hex[:16],
                "type": self.type_choice.currentData(), "name": name, "parameters": parameters, "per_m_items": items}
            proposed = [t for t in self.templates if t["id"] != template["id"]] + [template]
            calculate_slope_support_quantities({"slope_support_rows": self.rows, "slope_support_templates": proposed})
            self.templates = proposed
            self._refresh_templates(); self.template_choice.setCurrentIndex(self.template_choice.findData(template["id"]))
            self.error.setText("模板已保存，后续记录可复用。")
        except (ValueError, TypeError) as error: self.error.setText(str(error))

    def _select_row(self, index, _column=0):
        row = self.rows[index]; self._loading = True
        self._editing_id = row["id"]
        self.type_choice.setCurrentIndex(self.type_choice.findData(row["type"]))
        self._refresh_templates(); self.template_choice.setCurrentIndex(max(0, self.template_choice.findData(row.get("template_id"))))
        template = next((t for t in self.templates if t["id"] == row.get("template_id")), {})
        self.name_edit.setText(row.get("name", "")); self.length_edit.setText(str(row["length_m"]))
        self.side_choice.setCurrentIndex(self.side_choice.findData(row.get("side_count", 1)))
        self._set_parameters({**default_slope_support_parameters(row["type"]), **template.get("parameters", {}), **row.get("parameters", {})})
        items = {i["component_id"]: i for i in template.get("per_m_items", [])}
        items.update({i["component_id"]: i for i in row.get("per_m_items", [])})
        self._set_rates(items.values()); self.template_name.setText(template.get("name", ""))
        self._loading = False; self.error.clear()

    def _delete_row(self):
        selected = self.rows_table.selectionModel().selectedRows()
        if not selected:
            self.error.setText("请先选择需要删除的支护记录。")
            return
        index = selected[0].row()
        if 0 <= index < len(self.rows): del self.rows[index]
        self._new_row(); self._refresh_rows()

    def _refresh_rows(self):
        self.rows_table.setRowCount(len(self.rows))
        for i, row in enumerate(self.rows):
            for j, value in enumerate((row.get("name", ""), row["type"], row["length_m"], row.get("side_count", 1))):
                self.rows_table.setItem(i, j, QTableWidgetItem(str(value)))
        try:
            report = calculate_slope_support_quantities({"slope_support_rows": self.rows, "slope_support_templates": self.templates})
            totals = {}
            for item in report["quantity_items"]:
                key = (item["name"], item["unit"]); totals[key] = totals.get(key, 0.) + item["quantity"]
            lines = [f"{name}：{value:.3f} {unit}" for (name, unit), value in totals.items()]
            issues = [x.get("message", str(x)) for x in report["scope_issues"]]
            self.result_text.setPlainText("\n".join([f"已保存 {len(self.rows)} 条支护记录", *lines, *(["待补："+"；".join(issues)] if issues else [])]))
        except (ValueError, TypeError) as error: self.result_text.setPlainText(str(error))

    def _finish(self):
        # Include a populated current form, including edits made after selecting
        # a stored row; blank new forms do not manufacture an empty record.
        if (self._editing_id is not None or self.length_edit.text().strip()) and not self._save_row(): return
        try:
            calculate_slope_support_quantities({"slope_support_rows": self.rows, "slope_support_templates": self.templates})
        except (ValueError, TypeError) as error: self.error.setText(str(error)); return
        self.updated_inputs["slope_support_rows"] = deepcopy(self.rows)
        self.updated_inputs["slope_support_templates"] = deepcopy(self.templates)
        self.accept()
