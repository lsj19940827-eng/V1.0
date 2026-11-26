"""Bind the current, unsaved construction form to a selectable section drawing."""
from __future__ import annotations

from copy import deepcopy
from html import escape
import math
import re

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from 土石方计算.services.section_scheme_bindings import _get, _set, hydraulic_dimensions
from 土石方计算.services.section_scheme_catalog import resolve_section_scheme_fields
from .choice_display import ChoiceDisplay
from .drawing_material_details import _field_name


_PIPE_COLUMNS = ("inner_diameter", "outer_diameter", "wall_thickness", "material",
                 "lining_thickness", "lining_material", "nominal_diameter_m")
_PIPE_FIELD = re.compile(r"^section\.pipes\[(\d+)\]\.(\w+)$")
_MARKS = {"missing": "#a5411f", "manual": "#685189", "derived": "#24705b",
          "project_default": "#486f83", "drawing": "#386387", "imported": "#486f83"}


def _canonical(path):
    return path.replace("construction.pipe_support.", "construction.pipe_seat.").replace(
        "construction.pipe_encasement.", "construction.encasement.")


def _raw(control):
    if isinstance(control, QCheckBox):
        return control.isChecked()
    if isinstance(control, QComboBox):
        return control.currentData()
    return control.text().strip()


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _field_value(path, control, text_fields):
    raw = _raw(control)
    if not isinstance(control, QLineEdit) or path in text_fields:
        return raw
    if path == "section.pipe_spacing" and "," in raw.replace("，", ","):
        return [_number(part) for part in raw.replace("，", ",").split(",")]
    return _number(raw)


def _assign(model, path, value):
    if value is not None:
        _set(model, path, value)
        return
    parent, _, name = path.rpartition(".")
    node = _get(model, parent)
    if isinstance(node, dict):
        node.pop(name, None)


class ParameterPreviewBinding(QWidget):
    def __init__(self, dialog, editor, source, scheme, required, controls, geometry_buttons, material, *,
                 view=None, show_pipe_trench=False):
        super().__init__(dialog)
        from .parameter_section_view import ParameterSectionView

        self.dialog, self.editor, self.source = dialog, editor, source
        self.scheme = scheme or {}
        self.required = set(required)
        self.controls = dict(controls)
        self.geometry_buttons = dict(geometry_buttons or {})
        self.material = material
        self.table = getattr(dialog, "pipe_table", None)
        self.components = getattr(dialog, "component_table", None)
        self.initial = {path: _raw(control) for path, control in self.controls.items()}
        self.active_path = None
        self.missing_paths = ()
        self.first_missing = None
        self.size_input = None
        self.decisions = {}
        self._labels = {}
        self._focus_paths = {}
        self._marked = set()
        self._origins = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.view = view if view is not None else ParameterSectionView(self, show_pipe_trench=show_pipe_trench)
        if view is None:
            heading = QHBoxLayout()
            title = QLabel("断面预览")
            title.setStyleSheet("font-weight:600;color:#214864")
            heading.addWidget(title)
            heading.addStretch()
            fit = QPushButton("适合窗口")
            fit.setAutoDefault(False)
            fit.clicked.connect(self.view.fit_to_window)
            heading.addWidget(fit)
            box.addLayout(heading)
            self.view.setMinimumSize(160, 130)
            self.view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
            box.addWidget(self.view, 1)
        self.view.parameterRequested.connect(self.focus_parameter)
        spec = QWidget()
        spec_row = QHBoxLayout(spec)
        spec_row.setContentsMargins(0, 0, 0, 0)
        spec_row.addWidget(QLabel("所属规格 · 施工外径（m）"))
        self.specification = QLineEdit()
        self.specification.setReadOnly(True)
        self.specification.setAccessibleName("所属规格施工外径（m）")
        self.specification.setProperty("parameter_path", "section.outer_diameter")
        self._watch_focus(self.specification, "section.outer_diameter")
        spec_row.addWidget(self.specification, 1)
        spec.setVisible(material)
        box.addWidget(spec)
        self.origin = QLabel()
        self.origin.setObjectName("parameterOrigin")
        self.origin.setTextFormat(Qt.PlainText)
        self.origin.setWordWrap(True)
        box.addWidget(self.origin)
        self.pending = QWidget()
        bar = QHBoxLayout(self.pending)
        bar.setContentsMargins(0, 0, 0, 0)
        self.pending_count = QLabel()
        self.pending_count.setStyleSheet("font-weight:600;color:#954323")
        self.pending_list = QComboBox()
        self.pending_list.setAccessibleName("待补参数")
        self.pending_list.setMinimumContentsLength(4)
        self.pending_list.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.pending_display = ChoiceDisplay(self.pending_list, wrap=True)
        locate = QPushButton("定位")
        locate.setAutoDefault(False)
        locate.clicked.connect(lambda: self.focus_parameter(self.pending_list.currentData()))
        self.pending_list.activated.connect(lambda _: self.focus_parameter(self.pending_list.currentData()))
        bar.addWidget(self.pending_count)
        bar.addWidget(self.pending_display, 1)
        bar.addWidget(locate)
        box.addWidget(self.pending)
        self.pending.hide()
        self._connect()
        self.initial_pipes = self._pipe_cells()
        self.initial_components = self._component_cells()
        self._inline_baseline = self._current_values() if view is not None else None

    def _current_values(self):
        model, overrides, invalid = self._draft()
        return deepcopy((model["section"], model["construction"], overrides, invalid))

    def has_changes(self):
        return self._current_values() != self._inline_baseline

    def detach(self):
        self._timer.stop()
        self.view.parameterRequested.disconnect(self.focus_parameter)

    def _connect(self):
        candidates = dict(self.controls)
        for path, button in self.geometry_buttons.items():
            candidates[path] = button
            button.clicked.connect(self.schedule)
        for path, row in getattr(self.dialog, "replacement_dimensions", {}).items():
            self._watch_focus(row.action, path)
            row.changed.connect(self.schedule)
        for name, path in (("drawing_workspace", "construction.working_space_left"),
                           ("encasement_thickness", "construction.encasement.side_thickness")):
            group = getattr(self.dialog, name, None)
            if group is not None:
                self._watch_focus(group.value, path)
                group.separate.toggled.connect(self.schedule)
        for path, control in candidates.items():
            self._watch_focus(control, path)
            if isinstance(control, QLineEdit):
                control.textChanged.connect(self.schedule)
            elif isinstance(control, QCheckBox):
                control.toggled.connect(self.schedule)
            elif isinstance(control, QComboBox):
                control.currentIndexChanged.connect(self.schedule)
        if self.table is not None:
            self.table.cellChanged.connect(self.schedule)
            self.table.currentCellChanged.connect(self._table_focus)
            self.table.model().rowsInserted.connect(self.schedule)
            self.table.model().rowsRemoved.connect(self.schedule)
        if self.components is not None:
            self.components.cellChanged.connect(self.schedule)
            self.components.currentCellChanged.connect(lambda *_: self._highlight("section.component_specs"))
        for key, button in getattr(self.dialog, "stage_buttons", {}).items():
            self._watch_focus(button, f"construction.{key}")
            button.clicked.connect(self.schedule)
        labels = self.editor.findChildren(QLabel)
        for widget in self._focus_paths:
            label = next((item for item in labels if item.buddy() is widget), None)
            if label is None and widget.parentWidget() is not None:
                form = widget.parentWidget().layout()
                if isinstance(form, QFormLayout):
                    label = form.labelForField(widget)
            if isinstance(label, QLabel):
                self._labels[widget] = (label, label.text())

    def _watch_focus(self, widget, path):
        widget.installEventFilter(self)
        self._focus_paths[widget] = path

    def eventFilter(self, watched, event):
        if event.type() == QEvent.FocusIn and watched in self._focus_paths:
            self._highlight(self._focus_paths[watched])
        return super().eventFilter(watched, event)

    def _table_focus(self, row, column, *_):
        if row >= 0 and 0 <= column < len(_PIPE_COLUMNS):
            self._highlight(f"section.pipes[{row+1}].{_PIPE_COLUMNS[column]}")

    def schedule(self, *_):
        self._timer.start(0)

    def _pipe_cells(self):
        rows = []
        if self.table is not None:
            for i in range(self.table.rowCount()):
                cells = []
                for j in range(self.table.columnCount()):
                    combo = self.table.cellWidget(i, j)
                    if combo is not None:
                        if not combo.property("parameterPreviewConnected"):
                            combo.currentIndexChanged.connect(self.schedule)
                            combo.setProperty("parameterPreviewConnected", True)
                        cells.append(combo.currentData())
                    else:
                        item = self.table.item(i, j)
                        cells.append(item.text().strip() if item else "")
                rows.append(tuple(cells))
        return tuple(rows)

    def _read_pipe_table(self, section, raw_rows, overrides, invalid):
        originals = getattr(self.dialog, "_pipe_original", [])
        rows = []
        for index, raw in enumerate(raw_rows):
            pipe = dict(originals[index]) if index < len(originals) else {}
            if self.source.get("cover_pipe_layout_mode") == "spacing":
                pipe.pop("offset", None)
            for col, key in enumerate(_PIPE_COLUMNS):
                value = raw[col] if col in {3,5} else _number(raw[col])
                path = f"section.pipes[{index+1}].{key}"
                if value is None and raw[col] and col not in {3,5}:
                    invalid.add(path)
                if value is None:
                    pipe.pop(key, None)
                else:
                    pipe[key] = value / 1000 if col == 6 else value
                if index >= len(self.initial_pipes) or self.initial_pipes[index][col] != raw[col]:
                    overrides[path] = pipe.get(key)
            pipe["earthwork_envelope_only"] = not bool(pipe.get("wall_thickness"))
            rows.append(pipe)
        section.update(pipes=rows, pipe_count=len(rows))
        for key in _PIPE_COLUMNS:
            if rows and key in rows[0]:
                section[key] = rows[0][key]
            else:
                section.pop(key, None)

    def _component_cells(self):
        if self.components is None:
            return ()
        return tuple((self.components.item(row, 3).text().strip(), self.components.item(row, 4).text().strip())
                     for row in range(self.components.rowCount()))

    def _draft(self):
        model = {**self.source, "section": deepcopy(self.source.get("section") or {}),
                 "construction": deepcopy(self.source.get("construction") or {})}
        overrides = dict(self.source.get("section_scheme_user_overrides") or {})
        if self.material:
            overrides.update(getattr(self.dialog, "values", {}))
        baseline = getattr(self.dialog, "_initial", self.initial)
        invalid = set()
        for path, control in self.controls.items():
            if not path.startswith(("section.", "construction.")):
                continue
            value = _field_value(path, control, getattr(self.dialog, "text_fields", {}))
            raw = _raw(control)
            if raw != self.initial.get(path):
                _assign(model, path, value)
                if isinstance(control, QLineEdit) and raw and (value is None or isinstance(value, list) and None in value):
                    invalid.add(path)
            if raw != baseline.get(path) and path not in getattr(self.dialog, "replacement_dimensions", {}):
                overrides[path] = value
        sides = getattr(self.dialog, "encasement_sides", None)
        if sides is not None:
            try:
                for key, value in sides.values().items():
                    path = f"construction.{getattr(self.dialog, 'enclosure_key', 'encasement')}.{key}"
                    _assign(model, path, value)
            except ValueError:
                pass  # Incomplete values stay visible as empty dimensions.
        rows = getattr(self.dialog, "replacement_dimensions", {})
        if rows:
            for key in ("replacement_parameter_modes", "section_scheme_user_overrides", "drawing_user_overrides"):
                model[key] = dict(model.get(key) or {})
        for path, row in rows.items():
            state = row.source_record()
            _assign(model, path, state["adopted_value"])
            if state["user_override"]:
                overrides[path] = state["adopted_value"]
                model["replacement_parameter_modes"][path] = "manual"
            else:
                overrides.pop(path, None)
                model["section_scheme_user_overrides"].pop(path, None)
                model["drawing_user_overrides"].pop(path, None)
                model["replacement_parameter_modes"][path] = "automatic"
        for path, value in getattr(self.dialog, "_geometry", {}).items():
            _set(model, path, value)
            overrides[path] = value
        pipe_cells = self._pipe_cells()
        if self.table is not None and pipe_cells != self.initial_pipes:
            self._read_pipe_table(model["section"], pipe_cells, overrides, invalid)
        component_cells = self._component_cells()
        if component_cells != self.initial_components:
            components = deepcopy(self.dialog._component_original)
            for spec, (thickness, grade) in zip(components, component_cells):
                solid = spec.get("geometry_kind") == "outer_offset_layer"
                key = "thickness_m" if solid or ("thickness_m" in spec and "nominal_thickness_m" not in spec) else "nominal_thickness_m"
                value = _number(thickness)
                if (solid or thickness) and (value is None or value <= 0):
                    invalid.add("section.component_specs")
                if value is None:
                    spec.pop(key, None)
                else:
                    spec[key] = value
                spec["grade"] = grade
            model["section"]["component_specs"] = components
            overrides["section.component_specs"] = components
        for key, value in getattr(self.dialog, "stages", {}).items():
            if value:
                model["construction"][key] = value
            else:
                model["construction"].pop(key, None)
            if value != (self.source.get("construction") or {}).get(key, []):
                overrides["construction." + key] = value
        return model, overrides, invalid

    def refresh(self):
        from 土石方计算.services.section_parameter_decisions import section_parameter_decisions, unresolved_pipe_size_field

        model, overrides, invalid = self._draft()
        dimensions = hydraulic_dimensions(model)
        resolved = resolve_section_scheme_fields(self.scheme, hydraulic_dimensions=dimensions) if self.scheme else {}
        self.decisions = section_parameter_decisions(model, self.scheme, self.required, overrides, resolved)
        for path in invalid:
            self.decisions[path] = dict(value=None, missing=True, origin="missing", origin_label="数值待核对",
                                        required=True, conditional=False, basis="填写有效数值后可更新此尺寸。")
        self.model_asset = model
        self.missing_paths = tuple(path for path, info in self.decisions.items()
                                   if info["required"] and info["missing"] and not info.get("conditional"))
        self.size_input = unresolved_pipe_size_field(model, self.scheme, self.decisions)
        self.first_missing = self.size_input or next(iter(self.missing_paths), None)
        self.view.set_section_parameters(model, self.scheme, self.missing_paths)
        current = self.pending_list.currentData()
        self.pending_list.clear()
        seen = set()
        if self.size_input:
            self.pending_list.addItem("公称 DN（mm）", self.size_input)
        for path in self.missing_paths:
            field = self._target(path)
            if field is not None and field in seen:
                continue
            if field is not None:
                seen.add(field)
            self.pending_list.addItem(self._name(path), path)
        self.pending_list.setCurrentIndex(max(0, self.pending_list.findData(current)))
        self.pending_display.refresh()
        self.pending_count.setText("先填规格" if self.size_input else f"待补 {self.pending_list.count()} 项")
        self.pending.setVisible(bool(self.missing_paths))
        self._update_labels()
        if self.material:
            from 土石方计算.services.section_geometry import pipe_specs
            try:
                pipes = pipe_specs(model["section"], require_material=False)
                sizes = "、".join(f"{p['outer_diameter']:g}" for p in pipes)
            except (ValueError, TypeError, KeyError):
                sizes = "待核对"
            self.specification.setText(sizes)
        self._highlight(self.active_path or self.first_missing)

    def _name(self, path):
        target = self._target(path)
        if target in self._labels:
            return self._labels[target][1].strip()
        return _field_name(path)

    @staticmethod
    def _origin_label(info):
        if info["missing"] and not info["required"]:
            if info.get("conditional"):
                return "、".join(info.get("conditions", ())) + "时核定"
            return "可选"
        return info["origin_label"]

    def _update_labels(self):
        chosen = {}
        marked = set()
        for path, info in self.decisions.items():
            target = self._target(path)
            if target is None:
                continue
            if path in self.missing_paths:
                marked.add(target)
            if target in self._labels:
                previous = chosen.get(target)
                if previous is None or path in self.missing_paths or (
                        not (previous["required"] and previous["missing"]) and info["origin"] == "manual"):
                    chosen[target] = info
        for widget in self._marked ^ marked:
            widget.setProperty("parameterMissing", widget in marked)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self._marked = marked
        for widget, (label, original) in self._labels.items():
            info = chosen.get(widget)
            key = (info["origin"], self._origin_label(info)) if info else None
            if self._origins.get(widget) == key:
                continue
            self._origins[widget] = key
            label.setTextFormat(Qt.RichText)
            text = escape(original)
            if info:
                color = "#617580" if info["missing"] and not info["required"] else _MARKS.get(info["origin"], "#576c7b")
                text += f'<br/><span style="font-size:10px;color:{color}">{escape(self._origin_label(info))}</span>'
            label.setText(text)

    def _highlight(self, path):
        self.active_path = path
        if path:
            self.view.focusParameter(_canonical(path))
        info = self.decisions.get(path)
        if info is None and path and (match := _PIPE_FIELD.fullmatch(path)):
            info = self.decisions.get("section." + match[2])
        if self.size_input and path in {self.size_input, "section.pipes[1].nominal_diameter_m"}:
            self.origin.setText("先在按桩号设置中填写公称 DN，匹配本型号的图纸尺寸。" if self.material else
                                "填写公称 DN 后，程序按本型号的尺寸表带入对应参数。")
        elif path and self.material and (path == "section.outer_diameter" or _PIPE_FIELD.fullmatch(path)):
            self.origin.setText("管径随所属规格，可在该管段的结构参数中修改。")
        elif path and info:
            self.origin.setText("　·　".join(filter(None, (self._name(path), self._origin_label(info), info.get("basis")))))
        elif path in self.controls and _get(getattr(self, "model_asset", self.source), path) is None:
            self.origin.setText(f"{self._name(path)}　·　可选")
        else:
            self.origin.setText("点选图上尺寸可定位参数。")

    def _target(self, path):
        canonical = _canonical(path)
        for name, prefix in (("drawing_workspace", "construction.working_space_"),
                             ("encasement_thickness", "construction.encasement.")):
            shared = getattr(self.dialog, name, None)
            if shared and not shared.separate.isChecked() and canonical.startswith(prefix) and (
                    name == "drawing_workspace" or canonical.endswith("_thickness")):
                return shared.value
        if canonical.startswith("construction.encasement."):
            key = canonical.rsplit(".",1)[-1]
            sides = getattr(self.dialog, "encasement_sides", None)
            if sides and key in sides.fields:
                if not sides.split.isChecked():
                    key = "side_thickness"
                elif key == "side_thickness":
                    key = "left_thickness"
                return sides.fields[key]
        if path not in self.controls and canonical.startswith("construction.pipe_seat."):
            path = canonical.replace("construction.pipe_seat.", "construction." + getattr(self.dialog, "seat_key", "pipe_seat") + ".")
        if path not in self.controls and canonical.startswith("construction.encasement."):
            path = canonical.replace("construction.encasement.", "construction." + getattr(self.dialog, "enclosure_key", "encasement") + ".")
        if path in getattr(self.dialog, "replacement_dimensions", {}):
            row = self.dialog.replacement_dimensions[path]
            return row.action if row.edit.isReadOnly() else row.edit
        if path in self.controls:
            return self.controls[path]
        stage = getattr(self.dialog, "stage_buttons", {}).get(path.removeprefix("construction."))
        if stage is not None:
            return stage
        if path == "section.component_specs" and self.components is not None:
            return self.components
        if path in self.geometry_buttons:
            return self.geometry_buttons[path]
        if self.material and self.size_input and path == self.size_input:
            return self.geometry_buttons.get("section.outer_diameter", self.specification)
        if _PIPE_FIELD.fullmatch(path) or path.startswith("section.") and path[8:] in _PIPE_COLUMNS:
            return self.table if self.table is not None else self.specification
        return None

    def focus_parameter(self, path):
        if not path:
            return
        self._highlight(path)
        target = self._target(path)
        if target is None:
            return
        node = target
        while node and node is not self.dialog:
            if hasattr(node, "setExpanded") and hasattr(node, "isExpanded"):
                node.setExpanded(True)
            node = node.parentWidget()
        tabs = getattr(self.dialog, "tabs", None)
        if tabs is not None:
            for index in range(tabs.count()):
                page = tabs.widget(index)
                if page.isAncestorOf(target):
                    tabs.setCurrentIndex(index)
                    if isinstance(page, QScrollArea):
                        page.ensureWidgetVisible(target)
                    break
        if target is self.table and self.table is not None:
            match = _PIPE_FIELD.fullmatch(path)
            row, key = (int(match[1])-1, match[2]) if match else (0, path[8:])
            if 0 <= row < self.table.rowCount() and key in _PIPE_COLUMNS:
                self.table.setCurrentCell(row, _PIPE_COLUMNS.index(key))
        elif isinstance(self.editor, QScrollArea) and self.editor.isAncestorOf(target):
            self.editor.ensureWidgetVisible(target)
        target.setFocus(Qt.OtherFocusReason)
        if isinstance(target, QLineEdit) and not target.isReadOnly():
            target.selectAll()
        self._highlight(path)


def attach_parameter_preview(dialog, editor, source, scheme=None, *, required=(), controls=None,
                             geometry_buttons=None, material=False, view=None, show_pipe_trench=False):
    """Replace a root form or tab widget with the live preview and the original editor."""
    if controls is None:
        controls = {**getattr(dialog, "fields", {}), **getattr(dialog, "combos", {}), **getattr(dialog, "text_fields", {})}
    binding = ParameterPreviewBinding(dialog, editor, source, scheme, required, controls, geometry_buttons, material,
                                      view=view, show_pipe_trench=show_pipe_trench)
    root = dialog.layout()
    index = root.indexOf(editor)
    if view is None:
        root.removeWidget(editor)
        split = QSplitter(Qt.Horizontal)
        split.setObjectName("parameterPreviewSplit")
        split.setChildrenCollapsible(False)
        split.addWidget(binding)
        split.addWidget(editor)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 5)
        root.insertWidget(index, split, 1)
        area = dialog.screen().availableGeometry()
        width = min(1180, area.width()-32)
        dialog.resize(width, min(740, area.height()-64))
        split.setSizes([int(width*.43), int(width*.57)])
    else:
        root.insertWidget(index, binding)
    dialog.setStyleSheet(dialog.styleSheet() + """
        #assetParameterEditor QLineEdit[parameterMissing="true"],
        #assetParameterEditor QComboBox[parameterMissing="true"] { border:1px solid #b45e36; background:#fff7ed; }
    """)
    dialog.parameter_preview = binding
    binding.refresh()
    return binding
