"""Shared form and enlarged view for construction section parameters."""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .parameter_section_view import ParameterSectionView


OUTER = "section.outer_diameter"
NOMINAL = "section.nominal_diameter_m"
LEFT = "construction.working_space_left"
RIGHT = "construction.working_space_right"
SLOPES = {"construction.excavation_slope_left": "左开挖坡比",
          "construction.excavation_slope_right": "右开挖坡比"}


def nominal_text(part):
    section = part.get("section") or {}
    pipes = section.get("pipes") or [section]
    values = (pipe.get("nominal_diameter_m", section.get("nominal_diameter_m")) for pipe in pipes)
    return " / ".join(f"DN{value * 1000:g}" if isinstance(value, (int, float)) and math.isfinite(value) else "—"
                      for value in values)


def add_form_value(form, label, text):
    value = QLabel(text)
    value.setTextFormat(Qt.PlainText)
    value.setWordWrap(True)
    form.addRow(label, value)
    return value


def parameter_unit(path):
    if path == "section.pipe_count":
        return "（根）"
    if path.endswith((".nominal_diameter_m", ".construction_wall_thickness_m")):
        return "（mm）"
    if path.endswith(".support_angle"):
        return "（°）"
    if path in SLOPES or path.endswith((".side_slope", ".bank_slope_left", ".bank_slope_right")):
        return "（1∶n）"
    return "（m）"


def add_numeric_parameter(form, path, label, value):
    edit = QLineEdit("" if value is None else str(value))
    edit.setAccessibleName(label)
    edit.setProperty("parameter_path", path)
    edit.setMaximumWidth(104)
    form.addRow(label + parameter_unit(path), edit)
    return edit


def focus_parameter(fields, path):
    first_outer = "section.pipes[1].outer_diameter"
    first_nominal = "section.pipes[1].nominal_diameter_m"
    if isinstance(path, str) and path.endswith(".outer_diameter") and path not in fields:
        nominal = path.removesuffix("outer_diameter") + "nominal_diameter_m"
        alternatives = (first_outer, OUTER, first_nominal, NOMINAL) if path in (OUTER, first_outer) else (nominal,)
        path = next((key for key in alternatives if key in fields), path)
    elif path in (NOMINAL, first_nominal) and path not in fields:
        alternatives = (NOMINAL, first_nominal)
        path = next((key for key in alternatives if key in fields), path)
    edit = fields.get(path)
    if edit is None:
        return False
    edit.setFocus()
    if isinstance(edit, QLineEdit):
        edit.selectAll()
    return True


class PipeSectionEditorDialog(QDialog):
    def __init__(self, parent, *, object_name, title, terrain_case=None, view=None):
        super().__init__(parent, Qt.SubWindow if view is not None else
                         Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.setObjectName(object_name)
        self.setWindowTitle(title)
        self.setStyleSheet("""
            QDialog {background:#F4F7FA;}
            QLineEdit {background:white; border:1px solid #B9C9D8;
                border-radius:4px; min-height:22px; padding:0 8px;}
            QLineEdit:focus {border-color:#2262A1;}
            QPushButton {background:white; color:#24405B; border:1px solid #BDCDDB;
                border-radius:5px; min-height:27px; padding:0 10px;}
            QPushButton:hover {background:#EAF3FA;}
            QPushButton[primary="true"]:enabled {background:#2262A1; color:white; border-color:#2262A1;}
            QPushButton:disabled {color:#7990A4;}
        """)
        outer = QVBoxLayout(self)
        side = QWidget()
        form = QVBoxLayout(side)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        heading = QLabel("施工参数")
        heading.setStyleSheet("font-weight:600;")
        form.addWidget(heading)
        self.form = QFormLayout()
        self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.form.setFormAlignment(Qt.AlignTop)
        self.form.setVerticalSpacing(4)
        form.addLayout(self.form)
        form.addStretch(1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText)
        self.message.setStyleSheet("color:#A32632;")
        self.message.hide()
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.save_parameters = self.buttons.button(QDialogButtonBox.Save)
        self.save_parameters.setText("保存参数")
        self.save_parameters.setObjectName("saveParameters")
        self.save_parameters.setProperty("primary", True)
        self.cancel_parameters = self.buttons.button(QDialogButtonBox.Cancel)
        self.cancel_parameters.setText("取消")
        self.buttons.rejected.connect(self.reject)

        if view is not None:
            self.view = view
            outer.setContentsMargins(8, 4, 0, 0)
            outer.addWidget(side, 1)
            self.setMinimumWidth(260)
            self.setMaximumWidth(330)
        else:
            self.setAttribute(Qt.WA_DeleteOnClose)
            self.view = ParameterSectionView(self, show_pipe_trench=True)
            self.view.setAccessibleName("参数化断面")
            self.view.setMinimumSize(300, 220)
            self.view.set_pipe_terrain_case(terrain_case)
            plot = QVBoxLayout()
            fit = QPushButton("适合窗口")
            fit.setAutoDefault(False)
            fit.clicked.connect(self.view.fit_to_window)
            plot.addWidget(fit, alignment=Qt.AlignRight)
            plot.addWidget(self.view, 1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setMinimumWidth(275)
            scroll.setMaximumWidth(330)
            scroll.setWidget(side)
            pair = QHBoxLayout()
            pair.addLayout(plot, 1)
            pair.addWidget(scroll)
            outer.addLayout(pair, 1)
            available = self.screen().availableGeometry()
            self.resize(min(1100, available.width() - 40), min(650, available.height() - 50))
        outer.addWidget(self.message)
        outer.addWidget(self.buttons)
