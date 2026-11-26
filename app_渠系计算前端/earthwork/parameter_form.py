"""Shared layout and pipe encasement controls for the construction editor."""
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGridLayout, QLabel, QLineEdit, QWidget


PARAMETER_STYLE = """
QDialog#assetParameterEditor { background: #f4f7fa; color: #21394e; }
#assetParameterEditor QLabel, #assetParameterEditor QCheckBox { color: #293f52; }
#assetParameterEditor QLabel#structureTypeLabel { color: #193c5e; font-size: 20px; font-weight: 600; }
#assetParameterEditor QLabel#parameterContext { color: #516a80; }
#assetParameterEditor QLabel#schemeTitle { color: #193c5e; font-size: 19px; font-weight: 600; }
#assetParameterEditor QLabel#structureTypeLabel[secondary="true"] { color: #516a80; font-size: 13px; font-weight: 400; }
#parameterTabs::pane { border: 1px solid #cbd9e4; background: #fff; border-radius: 5px; }
#parameterTabs QTabBar::tab { color: #4a6175; padding: 8px 12px; margin-right: 2px;
    background: #eaf0f5; border: 0; border-bottom: 3px solid transparent; }
#parameterTabs QTabBar::tab:selected { color: #174f81; font-weight: 600; background: white;
    border-bottom: 3px solid #2b72aa; }
#parameterTabs QTabBar::tab:hover:!selected { background: #e1eaf2; }
QWidget#parameterPage { background: white; }
#assetParameterEditor QGroupBox { background: white; border: 1px solid #d7e1e9;
    border-radius: 6px; margin-top: 10px; font-weight: 600; color: #22527b; }
#assetParameterEditor QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left;
    left: 11px; padding: 0 4px; background: white; }
#assetParameterEditor QLineEdit, #assetParameterEditor QComboBox { background: white;
    color: #233c50; border: 1px solid #b9c9d5; border-radius: 4px; min-height: 25px; padding: 0 6px; }
#assetParameterEditor QLineEdit:focus, #assetParameterEditor QComboBox:focus { border-color: #2677b4; }
#assetParameterEditor QLineEdit:read-only, #assetParameterEditor QLineEdit:disabled,
#assetParameterEditor QComboBox:disabled { background: #f1f5f8; color: #51697b; }
#assetParameterEditor QPushButton { color: #24445f; background: #f7fafc; border: 1px solid #bccedc;
    border-radius: 4px; min-height: 27px; padding: 0 12px; }
#assetParameterEditor QPushButton:hover { background: #eaf3fa; }
#assetParameterEditor QPushButton#saveParameters { color: white; background: #2066a2;
    border-color: #2066a2; padding: 2px 22px; font-weight: 600; }
#assetParameterEditor QPushButton#saveParameters:hover { background: #19578d; }
"""


def align_form(form):
    form.setFormAlignment(Qt.AlignTop)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(8)


def optional_support_bedding(scheme):
    fields = (scheme or {}).get("fields") or {}
    return (fields.get("construction.bedding_reference") == "pipe_seat_bottom"
            and fields.get("construction.bedding_thickness") == 0)


def pair_fields(form, first, second):
    """Keep related dimensions side by side, using the original editors and labels."""
    first_row = min(form.getWidgetPosition(field)[0] for field in (first, second))
    pair = QWidget()
    grid = QGridLayout(pair)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(4)
    for column, field in enumerate((first, second)):
        row = form.takeRow(field)
        label = row.labelItem.widget()
        label.setBuddy(field)
        grid.addWidget(label, 0, column)
        grid.addWidget(field, 1, column)
        grid.setColumnStretch(column, 1)
    form.insertRow(first_row, pair)
    return pair


class EncasementSides(QWidget):
    """Edit effective side dimensions while retaining the stored representation on a no-op."""

    def __init__(self, enclosure, parent=None):
        super().__init__(parent)
        self.original = {key: enclosure.get(key) for key in (
            "side_thickness", "left_thickness", "right_thickness")}
        common, left, right = self.original.values()
        left = common if left is None else left
        right = common if right is None else right
        self.split = QCheckBox("分别设置左右侧厚度")
        self.split.setChecked(left != right)
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        align_form(self.form)
        self.form.addRow(self.split)
        self.fields = {}
        uniform = left if left == right or common is None else common
        for key, label, value in (
            ("side_thickness", "两侧厚度", uniform),
            ("left_thickness", "左侧厚度", left),
            ("right_thickness", "右侧厚度", right),
        ):
            edit = QLineEdit("" if value is None else str(value))
            edit.setAccessibleName("包封"+label)
            edit.setPlaceholderText(f"沿用两侧厚度 {common} m" if key != "side_thickness" and common is not None else "未填写")
            self.fields[key] = edit
            self.form.addRow(QLabel(label + "  m"), edit)
        self.initial = self._state()
        self._split_basis = self.fields["side_thickness"].text()
        self.split.toggled.connect(self._switch)
        self._switch(self.split.isChecked())

    def _state(self):
        return self.split.isChecked(), tuple(edit.text() for edit in self.fields.values())

    def _switch(self, split):
        common = self.fields["side_thickness"].text()
        if split and common != self._split_basis:
            for key in ("left_thickness", "right_thickness"):
                self.fields[key].setText(common)
            self._split_basis = common
        for key, field in self.fields.items():
            self.form.setRowVisible(field, split == (key != "side_thickness"))

    def follow_drawing(self, value):
        """Refresh the common default and the sides that still inherit it."""
        self.original["side_thickness"] = value
        split, baseline = self.initial
        baseline = list(baseline)
        for i, (key, field) in enumerate(self.fields.items()):
            if key != "side_thickness":
                field.setPlaceholderText(f"沿用两侧厚度 {value} m" if value is not None else "未填写")
                if self.original[key] is not None:
                    continue
            if field.text() == baseline[i]:
                display = value
                if key == "side_thickness" and self.original["left_thickness"] is not None and (
                        self.original["left_thickness"] == self.original["right_thickness"]):
                    display = self.original["left_thickness"]
                baseline[i] = "" if display is None else str(display)
                field.setText(baseline[i])
        self.initial = split, tuple(baseline)
        self._split_basis = baseline[0]

    def values(self):
        if self._state() == self.initial:
            return self.original
        values = dict(self.original)
        split = self.split.isChecked()
        for key in (("left_thickness", "right_thickness") if split else ("side_thickness",)):
            raw = self.fields[key].text().strip()
            try:
                value = float(raw) if raw else None
            except ValueError:
                raise ValueError(self.fields[key].accessibleName()+"须填写数值") from None
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(self.fields[key].accessibleName()+"须为非负有限数值")
            if split and values[key] is None and value == values["side_thickness"]:
                continue
            values[key] = value
        if not split:
            # Geometry gives an explicit side priority over the common value.
            for key in ("left_thickness", "right_thickness"):
                if values[key] is not None:
                    values[key] = values["side_thickness"]
        return values


class DrawingSharedDimension(QWidget):
    """Edit one repeated CAD dimension, retaining separately specified project values."""

    def __init__(self, form, details, fields, label, split_label, *, sides=None):
        super().__init__()
        self.parent_form = form
        self.details = details
        self.sides = sides
        self.fields = fields
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        align_form(self.form)
        self.value = QLineEdit()
        self.value.setPlaceholderText("填写设计值")
        self.value.setAccessibleName(label)
        self.form.addRow(label, self.value)
        self.separate = QCheckBox(split_label)
        self.form.addRow(self.separate)
        first_row = min(form.getWidgetPosition(widget)[0] for widget in self.details)
        form.insertRow(first_row, self)
        self.refresh_from_fields()
        self._show_fields(self.separate.isChecked())
        self.separate.toggled.connect(self._set_separate)
        self.value.textChanged.connect(self._set_uniform)

    def _show_fields(self, separate):
        self.form.setRowVisible(self.value, not separate)
        for widget in self.details:
            self.parent_form.setRowVisible(widget, separate)

    def _set_uniform(self, text):
        if self.sides is not None:
            self.sides.split.setChecked(False)
        for field in self.fields:
            field.setText(text)

    def _set_separate(self, separate):
        self._show_fields(separate)
        if not separate:
            self.value.setText(self.fields[0].text())
            self._set_uniform(self.value.text())

    def refresh_from_fields(self):
        raw = [field.text().strip() for field in self.fields]
        # Existing projects may serialize the same size as '0.3' or '0.30'.
        try:
            values = [float(text) if text else None for text in raw]
        except ValueError:
            values = raw
        if (self.sides is not None and self.sides.split.isChecked()) or len(set(values)) > 1:
            self.separate.setChecked(True)
        self.value.blockSignals(True)
        self.value.setText(raw[0])
        self.value.blockSignals(False)
