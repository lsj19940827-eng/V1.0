"""Construction dimensions exposed by the selected standard pipe section."""
from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QPushButton

from 土石方计算.services.pipe_construction_defaults import DEFAULT_MANUAL_BACKFILL_HEIGHT_M, PIPE_BACKFILL_HEIGHT_PATH
from 土石方计算.services.replacement_geometry import SLOPE, WIDTH, derived_replacement_fields, replacement_geometry_paths
from 土石方计算.services.section_geometry import pipe_specs
from 土石方计算.services.section_parameter_decisions import (
    section_parameter_decisions, unresolved_pipe_size_field,
)
from 土石方计算.services.section_scheme_bindings import _check_constraints, _get, _same
from 土石方计算.services.special_pipe_materials import _number

from .pipe_section_form import (
    LEFT, NOMINAL, OUTER, RIGHT, SLOPES, PipeSectionEditorDialog, add_form_value,
    add_numeric_parameter, focus_parameter, nominal_text, parameter_unit,
)
from .pipe_standard_drawing_details import ENCASEMENT_B1_LABEL, pipe_standard_drawing_details, shared_encasement_thickness
from .replacement_parameters import ReplacementDimension


_SEAT = "construction.pipe_seat."
_ENC = "construction.encasement."
_SIDE = _ENC + "side_thickness"
_FACES = {"left_thickness": "左侧包封厚度", "right_thickness": "右侧包封厚度",
          "bottom_thickness": "底部包封厚度", "top_thickness": "顶部包封厚度"}
_REPLACEMENT = "construction.foundation_replacement_thickness"
_REPLACEMENT_THICKNESS = "construction.foundation_replacement.thickness"
_GABION = "section.gabion_profile"
_REVIEW = "section.source_review_confirmed"
_RANGE_FIELDS = {LEFT: "左工作面宽度", RIGHT: "右工作面宽度"}


def _face_value(asset, face):
    value = _get(asset, _ENC + face)
    return _get(asset, _SIDE) if value is None and face in ("left_thickness", "right_thickness") else value


def _field_value(asset, path):
    if path == NOMINAL:
        value = _get(asset, path)
        return None if value is None else value * 1000
    if path.startswith(_ENC):
        return _face_value(asset, path.removeprefix(_ENC))
    if path == _REPLACEMENT and (nested := _get(asset, _REPLACEMENT_THICKNESS)) is not None:
        return nested
    value = _get(asset, path)
    if value is None and path.startswith("section.pipes["):
        value = _get(asset, OUTER)
    if value is None and path == PIPE_BACKFILL_HEIGHT_PATH:
        return DEFAULT_MANUAL_BACKFILL_HEIGHT_M
    return value


def _known_pipe_diameters(section):
    try:
        pipes = pipe_specs(section)
    except (TypeError, ValueError, KeyError):
        return {}
    return {(f"section.pipes[{index}].outer_diameter" if section.get("pipes") else OUTER): pipe["outer_diameter"]
            for index, pipe in enumerate(pipes, 1) if pipe.get("wall_thickness", 0) > 0}


def _numeric_fields(source, scheme, required, *, located, terrain_case, fixed_diameters):
    construction = source.get("construction") or {}
    section = source.get("section") or {}
    seat = construction.get("pipe_seat") or {}
    replacement = replacement_geometry_paths(scheme)
    decisions = section_parameter_decisions(source, scheme, required)
    fields = {}
    if located:
        if unresolved_pipe_size_field(source, scheme, decisions):
            fields[NOMINAL] = "公称 DN"
        elif pipes := section.get("pipes"):
            fields.update({f"section.pipes[{index}].outer_diameter": "施工占用直径" +
                           (f"（第 {index} 根）" if len(pipes) > 1 else "")
                           for index in range(1, len(pipes) + 1)})
        else:
            fields[OUTER] = "施工占用直径"
        for path in fixed_diameters:
            fields.pop(path, None)
    if located or replacement or seat.get("bottom_width_mode") == "trench_bottom":
        fields.update(_RANGE_FIELDS)
    else:
        fields.update({path: label for path, label in _RANGE_FIELDS.items()
                       if path in required and decisions[path]["missing"]})
    if seat.get("enabled"):
        bedding = seat.get("material_role") == "bedding"
        fields[_SEAT + "base_thickness"] = "砂垫层基底厚度" if bedding else "管座基底厚度 t"
        if bedding:
            fields[_SEAT + "support_angle"] = "砂垫层包角"
        elif seat.get("bottom_width_mode") in {"support_chord_plus_sides", "outer_diameter_plus_sides"} or (
                _SEAT + "extension" in required):
            fields[_SEAT + "extension"] = "管座单侧外伸 b1"
    uniform = False
    if (construction.get("encasement") or {}).get("enabled"):
        uniform = shared_encasement_thickness(source, scheme)
        if uniform:
            fields[_SIDE] = ENCASEMENT_B1_LABEL
        else:
            fields.update({_ENC + face: label for face, label in _FACES.items()})
    if replacement:
        fields[_REPLACEMENT] = "石渣换填厚度"
        fields[WIDTH] = "石渣换填上宽"
        fields[SLOPE] = "石渣换填收坡"
    if located or SLOPE in replacement:
        for path, label in SLOPES.items():
            side = path.rsplit("_", 1)[-1]
            if (not construction.get("excavation_stages_" + side)
                    and construction.get("excavation_layer_mode") != "surface_thickness"
                    and scheme.get("scheme_id") != "tzk_pipe_paddy"):
                fields[path] = label
    details = pipe_standard_drawing_details(scheme, terrain_case)
    if located and details and details.shows_crown_partition:
        fields[PIPE_BACKFILL_HEIGHT_PATH] = "人工夯填至管顶以上"
    return fields, uniform


class PipeSpecialParameterEditor(PipeSectionEditorDialog):
    EditByStation = 2

    def __init__(self, source, scheme, required, overrides, resolver, parent, *,
                 located, title, terrain_case, view=None):
        super().__init__(parent, object_name="pipeSpecialParameterEditor" if view is not None
                         else "enlargedSpecialPipeSection", title="特殊施工段 · 参数化断面",
                         terrain_case=terrain_case, view=view)
        self._source = source
        self._scheme = scheme
        self._required = required
        self._resolver = resolver
        self._base = deepcopy(overrides)
        self.values = deepcopy(overrides)
        self._initial = {}
        self._geometry = {}
        self.fields = self.edits = {}
        self.replacement_dimensions = {}
        self.station_mode_button = None
        self._focus = {}
        self._inline_message = self.message
        fixed_diameters = _known_pipe_diameters(source.get("section") or {}) if located else {}
        self._labels, self._uniform = _numeric_fields(source, scheme, required, located=located,
                                                     terrain_case=terrain_case, fixed_diameters=fixed_diameters)
        self._last_dn = None
        if view is None:
            add_form_value(self.form, "断面方案", title)
        nominal = nominal_text(source)
        if NOMINAL not in self._labels and nominal != "—":
            add_form_value(self.form, "公称直径", nominal)
        if fixed_diameters:
            add_form_value(self.form, "设计管外径", " / ".join(f"{value:g} m" for value in fixed_diameters.values()))
        if not located:
            decisions = section_parameter_decisions(source, scheme, required, resolved_fields={})
            if any(item["required"] and item["missing"] and path.startswith("section.")
                   for path, item in decisions.items()):
                switch = QPushButton("按起止桩号设置")
                switch.clicked.connect(lambda: self._adopt(self.EditByStation))
                self.form.addRow(switch)
                self.station_mode_button = switch
                self._focus.update({path: switch for path in required if path.startswith("section.")})
        derived = replacement_geometry_paths(scheme)
        for path, label in self._labels.items():
            if path in derived:
                row = ReplacementDimension(path, source, scheme=scheme)
                row.basis.hide()
                row.changed.connect(self.refresh)
                self.replacement_dimensions[path] = row
                self.form.addRow(label + parameter_unit(path), row)
                edit = row.edit
            else:
                edit = add_numeric_parameter(self.form, path, label, self._display_value(source, path))
                edit.textChanged.connect(self.refresh)
            self.fields[path] = self._focus[path] = edit
            self._initial[path] = edit.text().strip()

        self.review = None
        if located and _GABION in required:
            self.gabion = QPushButton("编辑轮廓")
            self.gabion.clicked.connect(self._edit_gabion)
            self.form.addRow("格宾石笼", self.gabion)
            self._focus[_GABION] = self.gabion
            self._refresh_gabion_label(_get(source, _GABION))
        if located and _REVIEW in required:
            self.review = QCheckBox("已核定管座几何")
            self.review.setChecked(_get(source, _REVIEW) is True)
            self.review.setToolTip(scheme.get("source_review_required", "核定本段采用的管座几何"))
            self.review.toggled.connect(self.refresh)
            self.form.addRow(self.review)
            self._focus[_REVIEW] = self.review
        if view is None:
            self.view.parameterRequested.connect(self.focus_parameter)
        self.buttons.accepted.connect(self.accept)
        self.refresh()

    def _display_value(self, source, path):
        if path == _SIDE and self._uniform:
            widths = [_face_value(source, face) for face in _FACES]
            return widths[0] if all(width is not None for width in widths) else None
        return _field_value(source, path)

    def focus_parameter(self, path):
        if path.startswith(_ENC) and self._uniform:
            path = _SIDE
        elif path == _SIDE:
            path = _ENC + "left_thickness"
        elif path == "construction.foundation_replacement.width":
            path = WIDTH
        elif path == _REPLACEMENT_THICKNESS:
            path = _REPLACEMENT
        elif path in {_SEAT + "bottom_width", _SEAT + "bottom_width_mode"}:
            path = _SEAT + ("extension" if _SEAT + "extension" in self._focus else "support_angle")
        row = self.replacement_dimensions.get(path)
        if row and row.edit.isReadOnly():
            row.action.setFocus()
            return True
        return focus_parameter(self._focus, path)

    def has_changes(self):
        if self._geometry or self.review is not None and self.review.isChecked() != (_get(self._source, _REVIEW) is True):
            return True
        try:
            if any(row.changes() for row in self.replacement_dimensions.values()):
                return True
        except ValueError:
            return True
        return any(edit.text().strip() != self._initial[path] for path, edit in self.fields.items()
                   if path not in self.replacement_dimensions)

    def _changes(self, *, derived=True):
        changes = deepcopy(self._geometry)
        for path, edit in self.fields.items():
            if path in self.replacement_dimensions:
                if derived:
                    changes.update(self.replacement_dimensions[path].changes())
                continue
            raw = edit.text().strip()
            if raw == self._initial[path]:
                continue
            value = _number(raw, self._labels[path], positive=path.startswith("section.") or path.endswith(".support_angle"))
            if path == NOMINAL:
                value /= 1000
                if self._source.get("section", {}).get("pipes"):
                    changes["section.pipes[1].nominal_diameter_m"] = value
            if path.endswith(".support_angle") and value > 360:
                raise ValueError("砂垫层包角须在 0° 至 360° 之间")
            baseline = self._initial[path]
            if path == NOMINAL or path in SLOPES or not baseline or not _same(value, float(baseline)):
                changes[path] = value
            if path == _REPLACEMENT and path in changes and _get(self._source, _REPLACEMENT_THICKNESS) is not None:
                changes[_REPLACEMENT_THICKNESS] = value
            if path == _SIDE and self._uniform and path in changes:
                changes.update({_ENC + face: value for face in ("top_thickness", "bottom_thickness")})
                changes.update({_ENC + face: value for face in ("left_thickness", "right_thickness")
                                if _get(self._source, _ENC + face) is not None})
        if self.review is not None and self.review.isChecked() != (_get(self._source, _REVIEW) is True):
            changes[_REVIEW] = self.review.isChecked()
        return changes

    def _resolve(self, changes):
        source, fields = self._resolver({**self._base, **changes})
        if any(path == OUTER or path.endswith(".outer_diameter") for path in changes):
            pipe_specs(source.get("section") or {})
        return source, fields

    def _sync_drawing_sizes(self, changes, source):
        dn = changes.get(NOMINAL)
        if dn == self._last_dn:
            return
        self._last_dn = dn
        for path, edit in self.fields.items():
            if path == NOMINAL or path in changes or path in self.replacement_dimensions:
                continue
            value = self._display_value(source, path)
            text = "" if value is None else str(value)
            with QSignalBlocker(edit):
                edit.setText(text)
            self._initial[path] = text

    def _refresh_replacement(self, changes, source):
        if not self.replacement_dimensions:
            return
        values = derived_replacement_fields(source, self._scheme, explicit={**self._base, **changes})
        for path, row in self.replacement_dimensions.items():
            row.refresh(values.get(path), source)
            row.setToolTip(row.basis.text())

    def _pending(self, source, defaults, changes):
        decisions = section_parameter_decisions(source, self._scheme, self._required,
                                                overrides={**self._base, **changes}, resolved_fields=defaults)
        pending = [path for path, item in decisions.items() if item["required"] and item["missing"]]
        if not any(not decisions[path]["conditional"] for path in pending):
            _check_constraints(source, self._scheme)
        return pending

    def refresh(self, *_):
        try:
            changes = self._changes(derived=False)
            source, defaults = self._resolve(changes)
            self._sync_drawing_sizes(changes, source)
            if self.replacement_dimensions:
                self._refresh_replacement(changes, source)
                changes = self._changes()
                source, defaults = self._resolve(changes)
            missing = self._pending(source, defaults, changes)
        except (TypeError, ValueError, KeyError) as error:
            self.message.setText(str(error))
            self.message.show()
            self.save_parameters.setEnabled(False)
            return
        self.message.hide()
        self.save_parameters.setEnabled(bool(changes))
        self.view.set_section_parameters(source, self._scheme, missing)

    def _refresh_gabion_label(self, value):
        points = value.get("points", []) if isinstance(value, dict) else value
        self.gabion.setText(f"编辑轮廓（{len(points)} 个顶点）" if points else "填写轮廓")

    def _edit_gabion(self):
        from .engineering_drawings_dialog import edit_section_profile

        try:
            source, _ = self._resolve(self._changes())
        except (TypeError, ValueError, KeyError) as error:
            self.message.setText(str(error))
            self.message.show()
            return
        geometry = edit_section_profile(self, source, _GABION)
        if geometry is not None:
            self._geometry[_GABION] = geometry
            self._refresh_gabion_label(geometry)
            self.refresh()

    def accept(self):
        self._adopt(self.DialogCode.Accepted)

    def _adopt(self, decision):
        try:
            changes = self._changes()
            source, defaults = self._resolve(changes)
            if decision != self.EditByStation:
                self._pending(source, defaults, changes)
        except (TypeError, ValueError, KeyError) as error:
            self.message.setText(str(error))
            self.message.show()
            return
        self.values = {**self._base, **changes}
        self.done(decision)
