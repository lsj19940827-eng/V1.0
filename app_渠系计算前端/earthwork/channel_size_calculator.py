"""Compact open-channel sizing for construction forms without a reference section."""
from __future__ import annotations

import math

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QLineEdit, QPushButton

from app_渠系计算前端.increase_input_helper import get_auto_increase_percent
from calc_渠系计算算法内核.明渠设计 import quick_calculate_rectangular


_FIELDS = (
    ("flow", "设计流量 Qni (m³/s)", ""),
    ("increase_percent", "流量加大比例 (%)", ""),
    ("roughness", "糙率 n", "0.014"),
    ("slope_inverse", "比降 (1/i)", "3000"),
    ("minimum_velocity", "不淤流速 (m/s)", "0.1"),
    ("maximum_velocity", "不冲流速 (m/s)", "100"),
    ("bottom_width", "指定底宽 (m)", ""),
)
_DEFAULTS = {key: text for key, _, text in _FIELDS}


def _number(key, text):
    text = str(text if text is not None else "").strip()
    if not text and key in {"increase_percent", "bottom_width"}:
        return None
    title = next(label for field, label, _ in _FIELDS if field == key)
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"请填写有效的{title}") from None
    minimum_inclusive = key in {"increase_percent", "minimum_velocity"}
    if not math.isfinite(value) or value < 0 or (value == 0 and not minimum_inclusive):
        raise ValueError(f"请填写有效的{title}")
    return value


def _calculate_channel(values):
    values = {**_DEFAULTS, **values}
    return quick_calculate_rectangular(
        Q=_number("flow", values["flow"]), n=_number("roughness", values["roughness"]),
        slope_inv=_number("slope_inverse", values["slope_inverse"]),
        v_min=_number("minimum_velocity", values["minimum_velocity"]),
        v_max=_number("maximum_velocity", values["maximum_velocity"]),
        manual_b=_number("bottom_width", values["bottom_width"]),
        manual_increase_percent=_number("increase_percent", values["increase_percent"]),
    )


class RectangularChannelCalculator(QGroupBox):
    dimensions_applied = Signal(float, float)
    inputs_edited = Signal()

    def __init__(self, parent=None):
        super().__init__("矩形明渠水力计算", parent)
        self._defaults = dict(_DEFAULTS)
        self._dimensions = None
        grid = QGridLayout(self)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.fields = {}
        for index, (key, title, default) in enumerate(_FIELDS):
            row, pair = divmod(index, 2)
            label = QLabel(title)
            field = QLineEdit(default)
            label.setBuddy(field)
            self.fields[key] = field
            grid.addWidget(label, row, 2 * pair)
            grid.addWidget(field, row, 2 * pair + 1)
        self.fields["bottom_width"].setPlaceholderText("自动")
        self.calculate_button = QPushButton("计算")
        grid.addWidget(self.calculate_button, 3, 2, 1, 2)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        grid.addWidget(self.result_label, 4, 0, 1, 3)
        self.apply_button = QPushButton("采用净宽和边墙高")
        self.apply_button.setEnabled(False)
        grid.addWidget(self.apply_button, 4, 3)
        self.calculate_button.clicked.connect(self._calculate)
        self.apply_button.clicked.connect(self._apply)
        for field in self.fields.values():
            field.textChanged.connect(self._reset_result)
            field.textEdited.connect(self.inputs_edited)
        self._reset_result()

    def values(self):
        return {key: field.text() for key, field in self.fields.items() if field.text() != self._defaults[key]}

    def set_values(self, values, *, defaults=None):
        defaults = defaults or {}
        for key, _, default in _FIELDS:
            prefill = defaults.get(key)
            self._defaults[key] = default if prefill is None else str(prefill)
            value = values.get(key, self._defaults[key])
            self.fields[key].setText("" if value is None else str(value))
        self._reset_result()

    def set_flow(self, flow: float | None):
        field = self.fields["flow"]
        if field.text() and field.text() != self._defaults["flow"]:
            return
        self._defaults["flow"] = str(flow) if flow is not None and math.isfinite(flow) and flow > 0 else ""
        field.setText(self._defaults["flow"])

    def suggest_dimensions(self, defaults=None):
        if defaults is None:
            self._calculate(report_errors=False)
            return self._dimensions
        try:
            result = _calculate_channel(defaults)
        except (ValueError, ArithmeticError):
            return None
        return (result["b_design"], result["h_prime"]) if result["success"] else None

    def _reset_result(self):
        self._dimensions = None
        self.result_label.clear()
        self.apply_button.setEnabled(False)
        try:
            flow = _number("flow", self.fields["flow"].text())
        except ValueError:
            flow = None
        percentage = self.fields["increase_percent"]
        percentage.setPlaceholderText(
            f"自动 {get_auto_increase_percent(flow):g}%" if flow else "自动")

    def _calculate(self, *, report_errors=True):
        self._reset_result()
        try:
            result = _calculate_channel({key: field.text() for key, field in self.fields.items()})
        except (ValueError, ArithmeticError) as error:
            if report_errors:
                self.result_label.setText(str(error))
            return
        if not result["success"]:
            if report_errors:
                self.result_label.setText(result["error_message"])
            return

        # The design wall top includes the freeboard above increased-flow depth.
        width, height = result["b_design"], result["h_prime"]
        self._dimensions = width, height
        self.result_label.setText(
            f"净宽 {width:.3f} m　边墙高 {height:.3f} m　加大流量 {result['Q_increased']:.3f} m³/s")
        self.apply_button.setEnabled(True)

    def _apply(self):
        if self._dimensions:
            self.dimensions_applied.emit(*self._dimensions)
