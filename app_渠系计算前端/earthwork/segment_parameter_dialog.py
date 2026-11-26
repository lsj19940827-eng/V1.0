"""Editors for the construction and material parameters of a special pipe segment."""
from __future__ import annotations

from copy import deepcopy
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from 土石方计算.services.section_scheme_bindings import _get, _set
from 土石方计算.services.section_scheme_catalog import is_selectable_section_scheme, section_scheme_catalog_path
from .engineering_drawings_dialog import _field_label, edit_discrete_components, edit_section_profile
from .parameter_form import DrawingSharedDimension, EncasementSides, PARAMETER_STYLE, align_form, optional_support_bedding, pair_fields
from .parameter_preview_binding import attach_parameter_preview
from .replacement_parameters import DEPENDENCIES, LEGACY_WIDTH, ReplacementDimension, refresh_replacement_dimensions
from .special_pipe_materials_widget import _NAMES, _label as material_label
from .workbench_parameters import AssetParameterDialog, CollapsibleParameterGroup, scheme_parameter_overrides


def _drawing_link(scheme, requested):
    button = QPushButton("查看原图")
    button.setObjectName("viewSchemeDrawing")
    button.setVisible(bool(scheme.get("source_preview")) and is_selectable_section_scheme(scheme))
    button.setToolTip(scheme.get("source_title") or scheme["title"])
    button.clicked.connect(lambda: requested.emit())
    return button


def show_segment_drawing(parent, scheme, input_files, *, library_root=None):
    from .section_scheme_view import SectionSchemeView

    if not scheme.get("source_preview") or not is_selectable_section_scheme(scheme):
        return
    dialog = QDialog(parent)
    dialog.setWindowTitle(scheme.get("source_title") or scheme["title"])
    available = dialog.screen().availableGeometry()
    dialog.resize(min(1120, available.width() - 32), min(740, available.height() - 64))
    layout = QVBoxLayout(dialog)
    controls = QHBoxLayout()
    variants = QComboBox()
    variants.addItem(scheme.get("source_title") or scheme["title"], scheme["source_preview"])
    terrain_labels = {"cut": "全挖", "mixed": "半挖半填", "fill": "全填"}
    for kind, variant in scheme.get("terrain_variants", {}).items():
        reference = variant.get("source_preview")
        if reference and variants.findData(reference) < 0:
            variants.addItem(terrain_labels.get(kind, kind), reference)
    variants.setVisible(variants.count() > 1)
    controls.addWidget(variants)
    controls.addStretch()
    view = SectionSchemeView()
    for title, callback in (("缩小", lambda: view.zoom(1 / 1.2)), ("放大", lambda: view.zoom(1.2)),
                            ("适合窗口", view.fit_to_window)):
        button = QPushButton(title)
        button.clicked.connect(callback)
        controls.addWidget(button)
    layout.addLayout(controls)
    layout.addWidget(view, 1)
    def update():
        view.show_scheme_drawing(scheme, variants.currentData(), library_root or section_scheme_catalog_path().parent, input_files)
    variants.currentIndexChanged.connect(update)
    update()
    dialog.exec()


def parameter_label(path):
    if path.rsplit(".", 1)[-1] in _NAMES:
        return material_label(path)
    return _field_label(path)


def missing_parameters(source, required, scheme=None):
    from 土石方计算.services.section_parameter_decisions import section_parameter_decisions
    rows = section_parameter_decisions(source, scheme, required, resolved_fields={})
    return [path for path, info in rows.items() if info["required"] and info["missing"] and not info["conditional"]]


def _category(path):
    if ".encasement." in path:
        return "混凝土包封"
    if ".pipe_seat." in path:
        return "管座与支承"
    if "foundation_replacement" in path:
        return "基础换填"
    if ".bedding_" in path:
        return "垫层"
    return "沟槽尺寸"


def _control_value(control):
    if isinstance(control, QComboBox):
        return control.currentData()
    if isinstance(control, QCheckBox):
        return control.isChecked()
    return control.text().strip()


def _table_values(table):
    return tuple(tuple(
        _control_value(table.cellWidget(row, col)) if table.cellWidget(row, col)
        else table.item(row, col).text() if table.item(row, col) else ""
        for col in range(table.columnCount())) for row in range(table.rowCount()))


def _preview_number(text):
    if not text:
        return None
    try:
        value = float(text)
        if math.isfinite(value):
            return value
    except ValueError:
        pass
    return "输入待补全"


class LocatedSegmentParameters(AssetParameterDialog):
    """Apply only changes to the segment draft, including edits on secondary pages."""

    drawing_requested = Signal()

    def __init__(self, source, scheme, paths, required, station_prefix, parent, *,
                 general=None, view=None, show_pipe_trench=False):
        super().__init__(source, parent, initial_page="pipe_support",
                         context_title=scheme["title"], show_scope=False, defer_preview=True)
        if view is not None:
            self.setWindowFlags(Qt.SubWindow)
        self._inline_message = None
        heading = self.layout().itemAt(0).layout()
        if view is None:
            heading.addWidget(_drawing_link(scheme, self.drawing_requested))
        else:
            for index in range(heading.count()):
                widget = heading.itemAt(index).widget()
                if widget is not None:
                    widget.hide()
            self._inline_message = QLabel()
            self._inline_message.setStyleSheet("color:#9A3C1E;")
            self._inline_message.setWordWrap(True)
            self._inline_message.hide()
            self.layout().insertWidget(self.layout().count() - 1, self._inline_message)
        source_title = scheme.get("source_title")
        if view is None and source_title and source_title != scheme["title"]:
            drawing_name = QLabel(source_title)
            drawing_name.setTextFormat(Qt.PlainText)
            drawing_name.setObjectName("parameterContext")
            drawing_name.setWordWrap(True)
            self.layout().insertWidget(1, drawing_name)
        self._geometry = {}
        geometry_buttons = {}
        self._station_prefix = station_prefix
        from 土石方计算.services.replacement_geometry import replacement_geometry_paths
        derived_paths = set(replacement_geometry_paths(scheme))
        self.replacement_dimensions = {}
        numeric = [path for path in sorted(paths) if path not in self.fields
                   and path.startswith("construction.foundation_replacement")
                   and not (derived_paths and path == LEGACY_WIDTH)]
        if numeric:
            group = QGroupBox("基础换填")
            form = QFormLayout(group)
            align_form(form)
            for path in numeric:
                if path in derived_paths:
                    row = ReplacementDimension(path, source, scheme=scheme)
                    self.replacement_dimensions[path] = row
                    self.fields[path] = row.edit
                    form.addRow(parameter_label(path), row)
                else:
                    self.number(form, path, parameter_label(path), unit="", nonnegative=True)
            if self.replacement_dimensions:
                self.pipe_support_form.insertRow(0, group)
            else:
                self.pipe_support_form.addRow(group)
        for path in sorted(required):
            if path.endswith(("_profile", ".floor_steps", ".discrete_components")):
                button = QPushButton()
                self._update_geometry_button(button, path)
                button.clicked.connect(lambda _, p=path, b=button: self._edit_geometry(p, b))
                self.pipe_support_form.addRow(parameter_label(path), button)
                geometry_buttons[path] = button
        if scheme.get("source_review_required"):
            path = "section.source_review_confirmed"
            review = QCheckBox("已核定本工程可采用此原图")
            review.setChecked(_get(source, path) is True)
            self.fields[path] = review
            note = QLabel(str(scheme["source_review_required"]))
            note.setWordWrap(True)
            self.pipe_support_form.addRow(note)
            self.pipe_support_form.addRow(review)
        self._controls = {**self.fields, **self.combos, **self.text_fields}
        self._initial = {path: _control_value(control) for path, control in self._controls.items()}
        self._initial_pipes = _table_values(self.pipe_table)
        self._initial_components = _table_values(self.component_table) if hasattr(self, "component_table") else ()
        self._initial_stages = deepcopy(self.stages)
        scheduled = {path for table in scheme.get("dimension_schedules", ()) for row in table["rows"]
                     for path in (*row.get("fields", {}), *row.get("derived_fields", {}))}
        retained = source.get("section_scheme_user_overrides", {})
        saved = source.get("section_scheme_source_values", {})
        self._schedule_fallback = {path: saved[path]["value"] if path in saved else _get(general or {}, path)
                                   for path in scheduled if isinstance(self.fields.get(path), QLineEdit)
                                   and path not in retained}
        if self._schedule_fallback:
            self.pipe_table.cellChanged.connect(self._refresh_scheduled_inputs)
            for signal in (self.pipe_table.model().rowsInserted, self.pipe_table.model().rowsRemoved):
                signal.connect(lambda *_: self._refresh_scheduled_inputs())
        if self.replacement_dimensions:
            def refresh_dimensions(*_args):
                try:
                    pipes = self._seat_preview_pipes()
                except (ValueError, TypeError, KeyError):
                    pipes = []
                refresh_replacement_dimensions(self.replacement_dimensions, source, scheme, self._controls,
                                               pipe_rows=pipes, stages=self.stages, explicit=self._edited_slopes())
            self.pipe_table.cellChanged.connect(refresh_dimensions)
            for signal in (self.pipe_table.model().rowsInserted, self.pipe_table.model().rowsRemoved):
                signal.connect(refresh_dimensions)
            for path in (*DEPENDENCIES, "section.pipe_spacing"):
                field = self._controls.get(path)
                if isinstance(field, QLineEdit):
                    field.textChanged.connect(refresh_dimensions)
                elif isinstance(field, QComboBox):
                    field.currentIndexChanged.connect(refresh_dimensions)
            for key, button in self.stage_buttons.items():
                if key.startswith("excavation_stages_"):
                    button.clicked.connect(refresh_dimensions)
            refresh_dimensions()
        preview = attach_parameter_preview(self, self.tabs, source, scheme, required=required, controls=self._controls,
                                           geometry_buttons=geometry_buttons, view=view,
                                           show_pipe_trench=show_pipe_trench)
        if preview.first_missing:
            preview.focus_parameter(preview.first_missing)
        if self.asset.get("drawing_sources_preview") and hasattr(self, "drawing_source_tree"):
            self.tabs.currentChanged.connect(self._refresh_source_page)
            if hasattr(self, "component_table"):
                self.component_table.itemChanged.connect(lambda: self._refresh_source_page(self.tabs.currentIndex()))

    def _edited_slopes(self):
        return {path: _preview_number(self.fields[path].text())
                for path in ("construction.excavation_slope_left", "construction.excavation_slope_right")
                if path in self.fields and _control_value(self.fields[path]) != self._initial[path]}

    def _refresh_scheduled_inputs(self, row=None, col=None):
        if col is not None and col not in (0, 1, 6):
            return
        resolved = self._pending_schedule(_table_values(self.pipe_table))
        if resolved is None:
            return
        for path, fallback in self._schedule_fallback.items():
            field = self.fields[path]
            if _control_value(field) != self._initial[path]:
                continue
            value = resolved.get(path, fallback)
            if path == f"construction.{self.enclosure_key}.side_thickness" and hasattr(self,"encasement_sides"):
                self.encasement_sides.follow_drawing(value)
                for key, initial in zip(self.encasement_sides.fields, self.encasement_sides.initial[1]):
                    self._initial[f"construction.{self.enclosure_key}.{key}"] = initial
            else:
                field.setText("" if value is None else str(value))
                self._initial[path] = _control_value(field)
            # An automatic change follows the drawing on every replay, so it is
            # also the baseline against which subsequent manual edits are saved.
            _set(self.original_asset, path, value)
        for control in (getattr(self, "encasement_thickness", None), getattr(self, "drawing_workspace", None)):
            if control is not None:
                control.refresh_from_fields()

    def _refresh_source_page(self, index):
        page = self.tabs.widget(index)
        if page is None or not page.isAncestorOf(self.drawing_source_tree):
            return
        from .drawing_material_details import refresh_drawing_preview

        changes = deepcopy(self._geometry)
        for path, control in self._controls.items():
            if path in self.replacement_dimensions:
                continue
            value = _control_value(control)
            if value == self._initial[path]:
                continue
            if path in self.fields and isinstance(control, QLineEdit):
                if path == "section.pipe_spacing" and "," in value.replace("，", ","):
                    value = [_preview_number(part.strip()) for part in value.replace("，", ",").split(",")]
                else:
                    value = _preview_number(value)
            if value != _get(self.original_asset, path):
                changes[path] = value
        if hasattr(self, "encasement_sides"):
            try:
                sides = self.encasement_sides.values()
            except ValueError:
                sides = {}
            for key, value in sides.items():
                path = f"construction.{self.enclosure_key}.{key}"
                if value != _get(self.original_asset, path):
                    changes[path] = value
        for key, value in self.stages.items():
            if value != self._initial_stages.get(key):
                changes["construction." + key] = value
        for path, role in (("section.material_grade", "concrete"), ("construction.bedding_grade", "bedding")):
            spec_path = "section.material_specs." + role
            spec = _get(self.asset, spec_path)
            if path in changes and spec:
                changes[spec_path] = {**spec, "grade": changes[path]}
        if self._initial_components:
            materials = _table_values(self.component_table)
            if materials != self._initial_components:
                components = deepcopy(self._component_original)
                for row, part in zip(materials, components):
                    physical_layer = part.get("geometry_kind") == "outer_offset_layer"
                    has_thickness = "thickness_m" in part and "nominal_thickness_m" not in part
                    key = "thickness_m" if physical_layer or has_thickness else "nominal_thickness_m"
                    part[key] = _preview_number(row[3])
                    part["grade"] = row[4]
                changes["section.component_specs"] = components
        columns = ("inner_diameter", "outer_diameter", "wall_thickness", "material", "lining_thickness",
                   "lining_material", "nominal_diameter_m")
        rows = _table_values(self.pipe_table)
        if len(rows) != len(self._initial_pipes):
            changes["section.pipe_count"] = len(rows)
        for row_index, row in enumerate(rows):
            previous = self._initial_pipes[row_index] if row_index < len(self._initial_pipes) else (None,) * len(row)
            for col, (key, value) in enumerate(zip(columns, row)):
                if value == previous[col]:
                    continue
                if key == "outer_diameter" and self.pipe_table.item(row_index, col).data(Qt.UserRole) is not None:
                    continue
                if key not in {"material", "lining_material"}:
                    value = _preview_number(value)
                    if key == "nominal_diameter_m" and isinstance(value, float):
                        value /= 1000.
                path = f"section.pipes[{row_index + 1}].{key}"
                section_path = "section." + key
                if row_index == 0 and section_path in self.asset.get("drawing_parameter_sources", {}):
                    path = section_path
                changes[path] = value
        labels = {path: control.accessibleName() for path, control in self._controls.items() if control.accessibleName()}
        resolved, match = self._current_schedule(rows)
        replacement = {path: row.source_record() for path, row in self.replacement_dimensions.items()}
        refresh_drawing_preview(self, changes, labels, resolved, match, replacement)

    def _pending_schedule(self, rows):
        return self._current_schedule(rows)[0]

    def _current_schedule(self, rows):
        from 土石方计算.services.section_scheme_bindings import _field_paths, hydraulic_dimensions
        from 土石方计算.services.section_scheme_catalog import match_section_scheme_size, resolve_section_scheme_fields

        scheme = self.asset["section_scheme_binding"]["scheme_snapshot"]
        diameter_columns = {0: "section.inner_diameter", 1: "section.outer_diameter", 6: "section.nominal_diameter_m"}
        if not rows or not scheme.get("dimension_schedules"):
            return None, None
        dimensions = {path: value for path, value in hydraulic_dimensions(self.original_asset).items()
                      if not path.startswith("section.pipes[")}
        dimensions["section.pipe_count"] = len(rows)
        dimensions["pipe_row_count"] = len(rows)
        for index, row in enumerate(rows, 1):
            for col, path in diameter_columns.items():
                value = _preview_number(row[col])
                if isinstance(value, float) and col == 6:
                    value /= 1000.
                value = value if isinstance(value, float) else None
                dimensions[f"section.pipes[{index}]." + path.split(".")[1]] = value
                if index == 1:
                    dimensions[path] = value
        resolved = resolve_section_scheme_fields(scheme, hydraulic_dimensions=dimensions)
        return _field_paths(resolved, template=True)[0], match_section_scheme_size(scheme, dimensions)

    def _update_geometry_button(self, button, path):
        value = self._geometry.get(path, _get(self.asset, path))
        if path.endswith(".discrete_components"):
            button.setText(f"编辑构件布置（{len(value)} 处）" if value else "填写构件布置…")
        else:
            points = value.get("points", []) if isinstance(value, dict) else value
            button.setText(f"编辑轮廓（{len(points)} 个顶点）" if points else "填写轮廓坐标…")

    def _edit_geometry(self, path, button):
        try:
            asset = self.edited_asset()
        except (TypeError, ValueError) as error:
            QMessageBox.warning(self, "请核对断面尺寸", str(error))
            return
        for key, value in self._geometry.items():
            _set(asset, key, value)
        if path.endswith(".discrete_components"):
            result = edit_discrete_components(self, asset, self._station_prefix)
        else:
            result = edit_section_profile(self, asset, path)
        if result is not None:
            self._geometry[path] = result
            self._update_geometry_button(button, path)
            self.parameter_preview.schedule()

    def accept(self):
        for row in self.replacement_dimensions.values():
            try:
                row.changes()
            except ValueError as exc:
                if self._inline_message is None:
                    QMessageBox.warning(self, "换填参数需要核对", str(exc))
                else:
                    self._inline_message.setText(str(exc))
                    self._inline_message.show()
                row.edit.setFocus()
                return
        if self._inline_message is None:
            super().accept()
            return
        try:
            self.asset = self.edited_asset()
        except (ValueError, TypeError) as exc:
            self._inline_message.setText(str(exc))
            self._inline_message.show()
            return
        QDialog.accept(self)

    def adopted_changes(self):
        # General-purpose saving also materializes implicit defaults and converts
        # legacy single-pipe sections to a table. They are not user overrides.
        paths = {path for path, control in self._controls.items()
                 if path not in self.replacement_dimensions and _control_value(control) != self._initial[path]}
        if hasattr(self, "encasement_sides"):
            paths.update(f"construction.{self.enclosure_key}.{key}" for key in self.encasement_sides.fields)
        for field, material in (("section.material_grade", "concrete"), ("construction.bedding_grade", "bedding")):
            grade = f"section.material_specs.{material}.grade"
            if field in paths and grade in self.changed_fields:
                paths.add(grade)
        paths.update("construction." + key for key, value in self.stages.items()
                     if value != self._initial_stages.get(key))
        if hasattr(self, "component_table") and _table_values(self.component_table) != self._initial_components:
            paths.add("section.component_specs")
        if _table_values(self.pipe_table) != self._initial_pipes or "section.pipe_spacing" in paths:
            paths.update(path for path in self.changed_fields if path.startswith("section.")
                         and not path.startswith(("section.material_specs", "section.component_specs")))
        changes = {path: deepcopy(_get(self.asset, path)) for path in paths
                   if _get(self.asset, path) != _get(self.original_asset, path)}
        changes.update(deepcopy(self._geometry))
        if self.replacement_dimensions:
            changes.update(self._edited_slopes())
        for row in self.replacement_dimensions.values():
            changes.update(row.changes())
        return scheme_parameter_overrides(self.asset, changes)


class MaterialSegmentParameters(QDialog):
    """The unlocated length workflow edits only the chosen support's dimensions."""

    drawing_requested = Signal()
    EditByStation = 2

    def __init__(self, source, scheme, paths, required, overrides, parent, *,
                 general=None, view=None, show_pipe_trench=False):
        super().__init__(parent, Qt.SubWindow if view is not None else Qt.Dialog)
        self.setObjectName("assetParameterEditor")
        self.setStyleSheet(PARAMETER_STYLE)
        self.setWindowTitle("特殊段材料参数")
        self.resize(560, 455)
        self.values = deepcopy(overrides)
        self._source = source
        self._required = required
        self.edits = {}
        self.replacement_dimensions = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)
        if view is None:
            title = QLabel(scheme["title"])
            title.setObjectName("structureTypeLabel")
            title.setWordWrap(True)
            heading = QHBoxLayout()
            heading.addWidget(title, 1)
            heading.addWidget(_drawing_link(scheme, self.drawing_requested))
            outer.addLayout(heading)
        from 土石方计算.services.section_scheme_bindings import hydraulic_dimensions
        from 土石方计算.services.section_scheme_catalog import match_section_scheme_size
        from .drawing_material_details import size_match_description
        match = (size_match_description(match_section_scheme_size(scheme, hydraulic_dimensions(source)))
                 if scheme.get("dimension_schedules") else "")
        basis = QLabel("　·　".join(filter(None, (scheme.get("source_title"), match))))
        basis.setWordWrap(True)
        basis.setTextFormat(Qt.PlainText)
        outer.addWidget(basis)
        basis.setVisible(view is None and bool(basis.text()))
        positioned = [path for path in missing_parameters(source, required, scheme)
                      if path.startswith("section.") or path == "construction.floor_steps"]
        if positioned:
            self.message = None
            editor = QWidget()
            pane = QVBoxLayout(editor)
            pane.setAlignment(Qt.AlignTop)
            notice = QLabel("该型号需要按桩号补充" + "、".join(parameter_label(path) for path in positioned) + "。")
            notice.setWordWrap(True)
            pane.addWidget(notice)
            outer.addWidget(editor, 1)
            buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
            buttons.button(QDialogButtonBox.Cancel).setText("取消")
            switch = buttons.addButton("按起止桩号设置", QDialogButtonBox.ActionRole)
            switch.clicked.connect(lambda: self.done(self.EditByStation))
            buttons.rejected.connect(self.reject)
            outer.addWidget(buttons)
            preview = attach_parameter_preview(self, editor, source, scheme, required=required,
                                               geometry_buttons={path: switch for path in positioned}, material=True,
                                               view=view, show_pipe_trench=show_pipe_trench)
            if preview.size_input:
                notice.setText("先按起止桩号填写公称 DN，程序会带入该型号对应的图纸尺寸。")
                preview.focus_parameter(preview.size_input)
            return
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        page = QWidget()
        page.setObjectName("materialParameterPage")
        page.setStyleSheet("QWidget#materialParameterPage {background:#f4f7fa;}")
        content = QVBoxLayout(page)
        content.setAlignment(Qt.AlignTop)
        content.setContentsMargins(0, 0, 4, 0)
        forms = {}
        enclosure = source["construction"].get("encasement") or {}
        support = source["construction"].get("pipe_seat") or {}
        width_mode = support.get("bottom_width_mode", "explicit")
        replacement = source["construction"].get("foundation_replacement") or {}
        needs_workspace = width_mode == "trench_bottom" or (
            source["construction"].get("foundation_replacement_thickness") and
            replacement.get("width", source["construction"].get("foundation_replacement_width")) is None)
        paths = {path for path in paths
                 if path.startswith(("construction.encasement.", "construction.pipe_seat.",
                                     "construction.foundation_replacement", "construction.bedding_"))
                 or path in required and (_get(source, path) is None or needs_workspace)}
        if width_mode != "explicit":
            paths.discard("construction.pipe_seat.bottom_width")
        if width_mode in {"trench_bottom", "support_chord"}:
            paths.discard("construction.pipe_seat.extension")
        if width_mode == "trench_bottom":
            paths.discard("construction.pipe_seat.height")
        from 土石方计算.services.replacement_geometry import replacement_geometry_paths
        derived_paths = set(replacement_geometry_paths(scheme))
        if derived_paths:
            paths.discard(LEGACY_WIDTH)
        side_keys = {"side_thickness", "left_thickness", "right_thickness"}
        order = ("基础换填", "混凝土包封", "管座与支承", "垫层", "沟槽尺寸")
        for path in sorted(paths, key=lambda p: (order.index(_category(p)), p)):
            name = _category(path)
            if name not in forms:
                grade = {"混凝土包封": enclosure, "管座与支承": support, "基础换填": replacement}.get(name, {}).get("grade")
                if name == "垫层" and optional_support_bedding(scheme):
                    group = CollapsibleParameterGroup("支承底部独立垫层（可选）",
                                                      expanded=bool(source["construction"].get("bedding_thickness")))
                    form = group.form
                else:
                    group = QGroupBox(f"{name} · {grade}" if grade else name)
                    form = QFormLayout(group)
                align_form(form)
                form.setContentsMargins(12, 14, 12, 10)
                content.addWidget(group)
                forms[name] = form
            if path in derived_paths:
                row = ReplacementDimension(path, source, scheme=scheme)
                self.replacement_dimensions[path] = row
                self.edits[path] = row.edit
                forms[name].addRow(parameter_label(path), row)
                continue
            if path.startswith("construction.encasement.") and path.rsplit(".", 1)[-1] in side_keys:
                if not hasattr(self, "encasement_sides"):
                    self.encasement_sides = EncasementSides(enclosure)
                    forms[name].addRow(self.encasement_sides)
                    for key, field in self.encasement_sides.fields.items():
                        field.setProperty("parameter_path", "construction.encasement." + key)
                continue
            value = _get(source, path)
            edit = QLineEdit("" if value is None else str(value))
            edit.setProperty("parameter_path", path)
            edit.setAccessibleName(parameter_label(path))
            edit.setPlaceholderText("填写设计值")
            self.edits[path] = edit
            forms[name].addRow(parameter_label(path), edit)
        if self.replacement_dimensions:
            def refresh_dimensions(*_args):
                refresh_replacement_dimensions(self.replacement_dimensions, source, scheme, self.edits)
            for path in DEPENDENCIES:
                if path in self.edits:
                    self.edits[path].textChanged.connect(refresh_dimensions)
            refresh_dimensions()
        for first, second in (("construction.encasement.top_thickness", "construction.encasement.bottom_thickness"),
                              ("construction.working_space_left", "construction.working_space_right")):
            if first in self.edits and second in self.edits:
                form = forms[_category(first)]
                pair = pair_fields(form, self.edits[first], self.edits[second])
                from 土石方计算.services.section_scheme_catalog import encasement_uniform_dimension, drawing_workspace_dimension
                if (first == "construction.encasement.top_thickness" and encasement_uniform_dimension(scheme)
                        and hasattr(self, "encasement_sides")):
                    sides = self.encasement_sides
                    self.encasement_thickness = DrawingSharedDimension(form, (pair, sides),
                        (sides.fields["side_thickness"], self.edits[first], self.edits[second]),
                        f"四面包封厚度 {encasement_uniform_dimension(scheme)}（m）", "分别设置各面厚度", sides=sides)
                elif first == "construction.working_space_left" and drawing_workspace_dimension(scheme):
                    self.drawing_workspace = DrawingSharedDimension(form, (pair,), (self.edits[first], self.edits[second]),
                        f"每侧施工工作面 {drawing_workspace_dimension(scheme)}（m）", "分别设置左右工作面")
        scroll.setWidget(page)
        outer.addWidget(scroll, 1)
        self.message = QLabel()
        self.message.setStyleSheet("color:#9A3C1E;")
        self.message.hide()
        outer.addWidget(self.message)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("采用参数")
        buttons.button(QDialogButtonBox.Save).setObjectName("saveParameters")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        controls = dict(self.edits)
        if hasattr(self, "encasement_sides"):
            controls.update({"construction.encasement." + key: edit for key, edit in self.encasement_sides.fields.items()})
        preview = attach_parameter_preview(self, scroll, source, scheme, required=required, controls=controls,
                                           material=True, view=view, show_pipe_trench=show_pipe_trench)
        if preview.first_missing:
            preview.focus_parameter(preview.first_missing)

    def accept(self):
        if self.message is None:
            return
        values = deepcopy(self.values)
        if hasattr(self, "encasement_sides"):
            try:
                sides = self.encasement_sides.values()
                for key, value in sides.items():
                    path = "construction.encasement." + key
                    if path in self._required and value is None:
                        raise ValueError("请填写" + parameter_label(path))
                    if value != _get(self._source, path):
                        values[path] = value
            except ValueError:
                self.message.setText("请填写有效的包封侧厚（m）")
                self.message.show()
                return
        for path, field in self.edits.items():
            if path in self.replacement_dimensions:
                row = self.replacement_dimensions[path]
                try:
                    changes = row.changes()
                    if path in self._required and not field.text().strip():
                        raise ValueError(row.basis.text())
                    values.update(changes)
                except ValueError as exc:
                    self.message.setText(str(exc)); self.message.show()
                    (row.action if row.edit.isReadOnly() else row.edit).setFocus()
                    return
                continue
            raw = field.text().strip()
            if not raw and path not in self._required:
                values.pop(path, None)
                continue
            try:
                value = float(raw)
                if not math.isfinite(value) or value < 0:
                    raise ValueError
            except ValueError:
                self.message.setText(parameter_label(path) + "须填写有限的非负数值")
                self.message.show()
                field.setFocus()
                return
            if value != _get(self._source, path):
                values[path] = value
        self.values = values
        super().accept()
