"""Edit a gate chamber in the construction workbench."""
from __future__ import annotations

import copy
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from 土石方计算.adapters.workbench_sources import gate_user_override_paths
from 土石方计算.services.section_scheme_bindings import format_station
from 土石方计算.services.sluice_gate import (
    DEFAULT_GATE_LINING_MULTIPLIER, gate_missing_fields, gate_quantity_items, gate_station_range,
    reference_gate_dimensions, reference_gate_lining, resolve_gate_section,
)

from .channel_size_calculator import RectangularChannelCalculator
from .section_preparation import construction_field_label, flow_section_label
from .section_scheme_view import SectionSchemeView


_FIELDS = (
    ("construction.gate_length", "闸长 (m)"),
    ("section.inner_width", "闸室净宽 (m)"),
    ("section.inner_height", "边墙净高 (m)"),
    ("construction.gate_lining_multiplier", "衬砌厚度倍率"),
    ("section.base_thickness", "底板厚度 (m)"),
    ("section.wall_thickness_left", "左边墙厚度 (m)"),
    ("section.wall_thickness_right", "右边墙厚度 (m)"),
)


class GateSectionPage(QScrollArea):
    applied = Signal(object, object)
    draft_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self._key = None
        self._asset = None
        self._reference = None
        self._prefix = "K"
        self._drafts = {}
        self._calculator_values = {}
        self._calculator_defaults = {}
        self._suggested_dimensions = {}
        content = QWidget()
        self.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 9, 9, 6)

        self.title = QLabel()
        self.title.setTextFormat(Qt.PlainText)
        self.title.setStyleSheet("font-size:20px;font-weight:600;color:#18212E")
        layout.addWidget(self.title)
        self.span = QLabel()
        self.span.setTextFormat(Qt.PlainText)
        self.span.setStyleSheet("color:#596578")
        layout.addWidget(self.span)

        body = QHBoxLayout()
        layout.addLayout(body, 1)
        self.preview = SectionSchemeView()
        self.preview.setMinimumWidth(300)
        self.preview.setAccessibleName("闸室参数化断面")
        body.addWidget(self.preview, 1)
        right = QVBoxLayout()
        body.addLayout(right)
        parameters = QGroupBox("闸室结构参数")
        right.addWidget(parameters)
        form = QFormLayout(parameters)
        self.reference_label = QLabel()
        self.reference_label.setTextFormat(Qt.PlainText)
        self.reference_label.setWordWrap(True)
        form.addRow(self.reference_label)
        self.edits = {}
        for path, title in _FIELDS:
            edit = QLineEdit()
            edit.setAccessibleName(title)
            edit.setMaximumWidth(140)
            edit.textEdited.connect(lambda value, field=path: self._edit_changed(field, value))
            edit.editingFinished.connect(self._refresh_preview)
            self.edits[path] = edit
            form.addRow(title, edit)
        self.calculator = RectangularChannelCalculator()
        self.calculator.dimensions_applied.connect(self._use_channel_dimensions)
        self.calculator.inputs_edited.connect(self.draft_changed)
        right.addWidget(self.calculator)
        right.addStretch(1)

        self.quantity_label = QLabel()
        self.quantity_label.setWordWrap(True)
        layout.addWidget(self.quantity_label)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        actions.addWidget(self.status, 1)
        self.discard_button = QPushButton("放弃未应用修改")
        self.discard_button.clicked.connect(self._discard)
        actions.addWidget(self.discard_button)
        self.apply_button = QPushButton("应用到当前闸")
        self.apply_button.setStyleSheet("background:#1965A7;color:white;font-weight:600;padding:6px 12px;")
        self.apply_button.clicked.connect(self._apply)
        actions.addWidget(self.apply_button)

    def bind(self, key, owner, asset, reference):
        changed = key != self._key
        if changed and self._key is not None:
            self._calculator_values[self._key] = self.calculator.values()
        self._key, self._asset, self._reference = key, asset, reference
        self._prefix = owner.get("station_prefix") or "K"
        self.title.setText(str(asset.get("name") or "闸"))
        name = (reference or {}).get("name")
        flow = flow_section_label((reference or {}).get("flow_section"))
        if reference:
            caption = "参考断面  " + " · ".join(filter(None, (name, flow)))
        else:
            caption = "净宽和边墙净高可用明渠水力计算预填。"
        if reference_gate_lining(asset, reference):
            caption += "\n厚度按水面线衬砌厚度 × 倍率预填。"
        self.reference_label.setText(caption + "\n可直接修改，清空后恢复预填值。")
        dimensions = reference_gate_dimensions(reference)
        needs_calculator = len(dimensions) < 2
        calculator_changed = needs_calculator == self.calculator.isHidden()
        self.calculator.setVisible(needs_calculator)
        defaults = {"flow": asset.get("gate_design_flow"), **(asset.get("gate_channel_inputs") or {})}
        width = (asset.get("gate_source_parameters") or {}).get("section.inner_width") or dimensions.get("inner_width")
        if width is not None:
            defaults["bottom_width"] = width
        if changed or calculator_changed or defaults != self._calculator_defaults:
            overrides = self._calculator_values.get(key, {}) if changed else self.calculator.values()
            self._calculator_defaults = defaults
            self.calculator.set_values(overrides, defaults=defaults)
            suggested = self.calculator.suggest_dimensions() if needs_calculator else None
            self._suggested_dimensions = dict(zip(("inner_width", "inner_height"), suggested)) if suggested else {}
        elif not needs_calculator:
            self._suggested_dimensions = {}
        self._load()

    def reset_context(self):
        self._key = self._asset = self._reference = None
        self._drafts.clear()
        self._calculator_values.clear()
        self._calculator_defaults = {}
        self._suggested_dimensions = {}

    def export_drafts(self):
        calculator_values = {**self._calculator_values}
        if self._key is not None:
            calculator_values[self._key] = self.calculator.values()
        return [{"key": list(key), "fields": dict(self._drafts.get(key, {})),
                 "calculator": dict(calculator_values.get(key, {}))}
                for key in dict.fromkeys((*self._drafts, *calculator_values))
                if self._drafts.get(key) or calculator_values.get(key)]

    def restore_drafts(self, drafts):
        self._drafts.clear()
        self._calculator_values.clear()
        for draft in drafts:
            key = draft.get("key") if isinstance(draft, dict) else None
            if not isinstance(key, (list, tuple)) or len(key) != 2 or not all(isinstance(part, str) for part in key):
                continue
            fields = draft.get("fields")
            if isinstance(fields, dict):
                self._drafts[tuple(key)] = {path: value for path, value in fields.items()
                                           if path in self.edits and isinstance(value, str)}
            if isinstance(calculator := draft.get("calculator"), dict):
                self._calculator_values[tuple(key)] = dict(calculator)

    def retain_drafts(self, keys):
        self._drafts = {key: fields for key, fields in self._drafts.items() if key in keys and fields}
        self._calculator_values = {key: values for key, values in self._calculator_values.items() if key in keys and values}

    def first_draft(self):
        return next(iter(self._drafts), None)

    def accept(self, key):
        self._drafts.pop(key, None)

    def _stored_text(self, path):
        group, field = path.split(".")
        value = (self._asset.get(group) or {}).get(field)
        if value is None and field == "gate_lining_multiplier":
            value = DEFAULT_GATE_LINING_MULTIPLIER
        return "" if value is None else str(value)

    def _load(self):
        draft = self._drafts.get(self._key, {})
        for path, edit in self.edits.items():
            edit.setText(draft.get(path, self._stored_text(path)))
        self._refresh_preview()

    def _set_override(self, path, value):
        fields = self._drafts.setdefault(self._key, {})
        if value.strip() == self._stored_text(path):
            fields.pop(path, None)
        else:
            fields[path] = value
        if not fields:
            self._drafts.pop(self._key)

    def _edit_changed(self, path, value):
        if self._key is None:
            return
        self._set_override(path, value)
        self._refresh_preview(editing=path)
        self.draft_changed.emit()

    def _use_channel_dimensions(self, width, height):
        self._set_override("section.inner_width", f"{width:.12g}")
        self._set_override("section.inner_height", f"{height:.12g}")
        self._load()
        self.draft_changed.emit()

    def _candidate(self):
        candidate = copy.deepcopy(self._asset)
        draft = self._drafts.get(self._key, {})
        source = candidate.get("gate_source_parameters") or {}
        overrides = gate_user_override_paths(candidate)
        candidate.setdefault("construction", {}).pop("gate_lining_basis", None)
        overrides.discard("construction.gate_lining_basis")
        for path, label in _FIELDS:
            if path not in draft:
                continue
            group, field = path.split(".")
            target = candidate.setdefault(group, {})
            text = draft[path].strip()
            if not text:
                if path in source:
                    target[field] = source[path]
                else:
                    target.pop(field, None)
                overrides.discard(path)
                continue
            try:
                value = float(text)
            except ValueError:
                value = math.nan
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label}须填写大于零的数值。")
            target[field] = value
            overrides.add(path)
        resolved = reference_gate_dimensions(self._reference)
        section = candidate.setdefault("section", {})
        for field, value in self._suggested_dimensions.items():
            if field not in resolved and section.get(field) in (None, ""):
                section[field] = value
                overrides.add(f"section.{field}")
        if overrides or "gate_user_overrides" in candidate:
            candidate["gate_user_overrides"] = sorted(overrides)
        return candidate

    def _refresh_preview(self, *, editing=None):
        if self._asset is None:
            return
        self.discard_button.setEnabled(self._key in self._drafts)
        self.apply_button.setEnabled(False)
        self.quantity_label.clear()
        captions = [flow_section_label(self._asset.get("flow_section"))]
        station = self._asset.get("gate_station")
        if station is not None:
            captions.append(f"中心桩号 {format_station(station, self._prefix)}")
        try:
            candidate = self._candidate()
        except ValueError as error:
            self.span.setText(" · ".join(filter(None, captions)))
            self.status.setText(str(error))
            return
        start, end = gate_station_range(candidate)
        if start is not None and end is not None:
            captions.append(f"{format_station(start, self._prefix)} ～ {format_station(end, self._prefix)}")
        self.span.setText(" · ".join(filter(None, captions)))
        section = resolve_gate_section(candidate, self._reference)
        for path, edit in self.edits.items():
            value = section.get(path.split(".")[-1]) if path.startswith("section.") else None
            edit.setPlaceholderText(f"{value:.6g}" if value is not None else
                f"{DEFAULT_GATE_LINING_MULTIPLIER:g}" if path.endswith("gate_lining_multiplier") else "")
            if editing != path:
                text = self._drafts.get(self._key, {}).get(path, self._stored_text(path))
                if not text:
                    group, field = path.split(".")
                    value = value if group == "section" else (candidate.get(group) or {}).get(field)
                    if value is None and field == "gate_lining_multiplier":
                        value = DEFAULT_GATE_LINING_MULTIPLIER
                    text = f"{float(value):.12g}" if value is not None else ""
                edit.setText(text)
        self.preview.set_gate_section(section)
        try:
            items = gate_quantity_items(candidate, self._reference)
        except ValueError as error:
            self.status.setText(str(error))
            return
        if items:
            details = [f"{item['name']} {item['quantity']:.3f} m³" for item in items]
            details.append(f"合计 {math.fsum(item['quantity'] for item in items):.3f} m³")
            self.quantity_label.setText("  ·  ".join(details))
        missing = gate_missing_fields(candidate, self._reference)
        self.status.setText("待补 " + "、".join(construction_field_label(path) for path in missing) if missing else "")
        changed = any(candidate.get(key, {}) != self._asset.get(key, {}) for key in ("section", "construction"))
        self.apply_button.setEnabled(not missing and (self._key in self._drafts or changed))

    def _discard(self):
        self._drafts.pop(self._key, None)
        self._load()
        self.draft_changed.emit()

    def _apply(self):
        if self.apply_button.isEnabled():
            self.applied.emit(self._key, self._candidate())
