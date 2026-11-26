"""General buried sections in the pipe construction workspace."""
from __future__ import annotations

import math
from copy import deepcopy

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from 土石方计算.services.pipe_construction_defaults import DEFAULT_MANUAL_BACKFILL_HEIGHT_M, PIPE_BACKFILL_HEIGHT_PATH
from 土石方计算.services.pipe_dimensions import construction_pipe_dimension_values
from 土石方计算.services.pipe_general_section import (
    apply_general_section, edited_general_section, general_section_groups,
)
from 土石方计算.services.section_parameter_decisions import section_parameter_decisions
from 土石方计算.services.section_scheme_bindings import _digest, _get, _same, format_station
from 土石方计算.services.special_pipe_materials import _number

from .pipe_section_comparison import PipeSectionComparison
from .pipe_section_form import (
    LEFT as _LEFT, RIGHT as _RIGHT, SLOPES as _SLOPES,
    PipeSectionEditorDialog, add_form_value, add_numeric_parameter, focus_parameter,
)


_CHANGED_SCOPE = "一般施工范围已更新，请重新打开断面图。"
_DN = ".nominal_diameter_m"
_WALL = ".construction_wall_thickness_m"
_OD = ".outer_diameter"
_PIPE_SIZES = (_DN, _WALL)
_COUNT = "section.pipe_count"
_SPACING = "section.pipe_spacing"
_FINISH = "construction.target_mode"
_FINISH_FIELDS = {
    "construction.final_cover_depth": "管外顶至完成面",
    "construction.bank_top_width_left": "左侧平台宽度",
    "construction.bank_top_width_right": "右侧平台宽度",
    "construction.bank_slope_left": "左填筑坡比",
    "construction.bank_slope_right": "右填筑坡比",
}
_COVER_MODES = {"cover_depth", "cover_above_terrain"}


def _seat(asset):
    construction = asset.get("construction") or {}
    for key in ("pipe_seat", "pipe_support"):
        seat = construction.get(key) or {}
        if seat and seat.get("material_role") == "bedding" and seat.get("enabled", True):
            return "construction." + key, seat
    return "", {}


def _scheme_title(scheme):
    title = scheme.get("title")
    scheme_id = scheme.get("scheme_id", "")
    if scheme_id.startswith(("tzk_pipe_", "tzk_siphon_")) and scheme_id[-2:-1] == "_":
        label = scheme_id[-1:].upper() + "型"
        if not title:
            return label
        if not title.startswith(label):
            return label + " · " + title
    return title or "已采用施工断面"


def _scope_label(group):
    spans = []
    for key, _, prefix in group["spans"]:
        start, end = key[2:]
        if spans and spans[-1][0] == prefix and math.isclose(start, spans[-1][2], rel_tol=0., abs_tol=1e-7):
            spans[-1] = prefix, spans[-1][1], end
        else:
            spans.append((prefix, start, end))
    return "、".join(f"{format_station(start, prefix)} ～ {format_station(end, prefix)}" for prefix, start, end in spans)


def _draft_key(members, group):
    return _digest([members, [span[0] for span in group["spans"]]])


def _valid_member(member):
    return isinstance(member, (list, tuple)) and len(member) == 2 and all(isinstance(value, str) and value for value in member)


def _pipe_fields(part):
    pipes = (part.get("section") or {}).get("pipes") or []
    if not pipes:
        return [("section", "")]
    return [(f"section.pipes[{i}]", f"（第 {i} 根）" if len(pipes) > 1 else "")
            for i in range(1, len(pipes) + 1)]


def _editable_fields(part):
    fields = {}
    for prefix, suffix in _pipe_fields(part):
        fields[prefix + _DN] = "公称直径" + suffix
        fields[prefix + _WALL] = "壁厚" + suffix
        fields[prefix + _OD] = "施工外径" + suffix
    fields.update({_LEFT: "左工作面宽度", _RIGHT: "右工作面宽度"})
    seat_prefix, seat = _seat(part)
    if seat_prefix:
        fields[seat_prefix + ".base_thickness"] = "砂垫层基底厚度"
        if seat.get("height") is None or seat.get("bottom_width_mode") == "trench_bottom":
            fields[seat_prefix + ".support_angle"] = "砂垫层包角"
    for path, label in _SLOPES.items():
        side = path.rpartition("_")[2]
        if not _get(part, "construction.excavation_stages_" + side):
            fields[path] = label
    fields[PIPE_BACKFILL_HEIGHT_PATH] = "人工夯填至管顶以上"
    fields.update({_COUNT: "管数", _SPACING: "管间净距", _FINISH: "完成面方式"})
    fields.update((path, label) for path, label in _FINISH_FIELDS.items()
                  if ".bank_slope_" not in path or not _get(part, path.replace("bank_slope_", "bank_stages_")))
    return fields


def _dimension_text(value):
    if value is None:
        return "—"
    text = f"{value:.9f}".rstrip("0")
    text += "0" * max(0, 3 - len(text.partition(".")[2]))
    return text


class PipeGeneralSectionWidget(QWidget):
    inputs_applied = Signal(object)
    draft_changed = Signal()
    conflicting_draft_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pipeGeneralSection")
        self._inputs = {}
        self._live_inputs = self._inputs
        self._live_member_sets = None
        self._members = ()
        self._groups = []
        self._drafts = {}
        self.edits = {}
        self._edit_labels = {}
        self._original_values = {}
        self._diameters = {}
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("pipeGeneralSectionCard")
        card.setStyleSheet("""
            #pipeGeneralSectionCard {background:#FFFFFF;border:0;}
            #pipeGeneralSectionCard QLabel {background:transparent;color:#18212E;}
            #pipeGeneralSectionCard QComboBox,#pipeGeneralSectionCard QLineEdit {
                min-height:22px;padding:0 8px;border:1px solid #DDE3EB;border-radius:5px;background:white;}
            #pipeGeneralSectionCard QLineEdit:focus {border-color:#3346A2;}
            #pipeGeneralSectionCard QPushButton {
                min-height:29px;padding:0 11px;border:1px solid #DDE3EB;border-radius:5px;background:#FFFFFF;color:#18212E;}
            #pipeGeneralSectionCard QPushButton:hover {background:#F7F8FB;}
            #pipeGeneralSectionCard QPushButton[primary="true"]:enabled {background:#3346A2;color:white;border-color:#3346A2;}
            #pipeGeneralSectionCard QPushButton:disabled {background:#F7F8FB;color:#6E7788;}
        """)
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 11, 18, 11)
        layout.setSpacing(8)
        heading = QLabel("一般施工段")
        heading.setStyleSheet("font-size:18px;font-weight:600;color:#18212E;")
        layout.addWidget(heading)
        top = QHBoxLayout()
        self.scope_label = QLabel("一般段范围")
        self.scope = QComboBox()
        self.scope.setAccessibleName("一般段的规格及范围")
        self.scope.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.scope.setMinimumContentsLength(20)
        self.scope.currentIndexChanged.connect(self._select_group)
        self.scope_summary = QLabel()
        self.scope_summary.setTextFormat(Qt.PlainText)
        self.scope_summary.setWordWrap(True)
        self.scope_summary.hide()
        top.addWidget(self.scope_label)
        top.addWidget(self.scope, 1)
        top.addWidget(self.scope_summary, 2)
        top.addStretch(1)
        layout.addLayout(top)
        self.empty = QLabel("当前对象暂无一般段。")
        layout.addWidget(self.empty)
        self.body = QWidget()
        row = QHBoxLayout(self.body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        self.comparison = PipeSectionComparison()
        self.comparison.setMinimumHeight(285)
        self.comparison.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.comparison.model.parameterRequested.connect(self.focus_parameter)
        self.comparison.model_enlargement_requested.connect(self._open_model_editor)
        row.addWidget(self.comparison, 1)

        side = QWidget()
        side.setMinimumWidth(210)
        side.setMaximumWidth(290)
        side.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        details = QVBoxLayout(side)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(5)
        self.edit_form = QFormLayout()
        self.edit_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.edit_form.setVerticalSpacing(4)
        details.addLayout(self.edit_form)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.PlainText)
        self.error.setStyleSheet("color:#A32632;")
        self.error.hide()
        details.addWidget(self.error)
        actions = QHBoxLayout()
        self.cancel_button = QPushButton("取消修改")
        self.cancel_button.clicked.connect(self._cancel)
        self.save_button = QPushButton("保存参数")
        self.save_button.setProperty("primary", True)
        self.save_button.setToolTip("将修改应用到所列一般施工段范围。")
        self.save_button.clicked.connect(self._save)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.save_button)
        actions.addStretch(1)
        details.addLayout(actions)
        details.addStretch(1)
        row.addWidget(side)
        layout.addWidget(self.body, 1)
        self.body.hide()

    def set_live_inputs(self, inputs, *, member_sets=None):
        self._live_inputs = inputs
        self._live_member_sets = {tuple(sorted(set(members))) for members in member_sets} if member_sets is not None else None

    def set_context(self, inputs, member_identities, *, preferred_asset_id=None):
        self._inputs = inputs
        self._live_inputs = inputs
        members = tuple(sorted(set(map(tuple, member_identities))))
        old_group = self._group()
        previous_spans = {span[0] for span in old_group["spans"]} if old_group and members == self._members else set()
        self._members = members
        self._groups = general_section_groups(inputs, members)
        selected, selected_priority = -1, -1
        with QSignalBlocker(self.scope):
            self.scope.clear()
            for index, group in enumerate(self._groups):
                label = _scope_label(group)
                self.scope.addItem(label, group["id"])
                self.scope.setItemData(index, label, Qt.ToolTipRole)
                priority = 0
                if any(span[0] in previous_spans for span in group["spans"]):
                    priority = 1
                if preferred_asset_id and any(preferred_asset_id in (span[0][1], span[1]) for span in group["spans"]):
                    priority += 2
                if self._active_draft(group):
                    priority += 1
                if priority > selected_priority:
                    selected, selected_priority = index, priority
            self.scope.setCurrentIndex(selected)
        multiple = len(self._groups) > 1
        shared_scope = len(self._groups) == 1 and len(self._groups[0]["spans"]) > 1
        self.scope.setVisible(multiple)
        self.scope_summary.setText(_scope_label(self._groups[0]) if shared_scope else "")
        self.scope_summary.setVisible(shared_scope)
        self.scope_label.setVisible(multiple or shared_scope)
        self._select_group()

    def _group(self):
        index = self.scope.currentIndex()
        return self._groups[index] if 0 <= index < len(self._groups) else None

    def _key(self, group):
        return _draft_key(self._members, group)

    def _active_draft(self, group):
        draft = self._drafts.get(self._key(group), {}).get("values", {})
        return bool(draft.keys() & _editable_fields(group["asset"]).keys())

    def _select_group(self, *_):
        group = self._group()
        self.error.hide()
        self.empty.setVisible(group is None)
        self.body.setVisible(group is not None)
        if group is None:
            return
        self.comparison.set_source(group["scheme"], self._inputs.get("input_files", ()))
        self._load_fields(group)

    def _render(self, updates=None, *, view=None, diameters=None):
        group = self._group()
        if group is None:
            return
        part = edited_general_section(group["asset"], updates) if updates else group["asset"]
        if diameters is None:
            diameters = self._diameters
        for edit, dimension in zip(diameters.values(), construction_pipe_dimension_values(part)):
            edit.setPlaceholderText(_dimension_text(dimension["outer_diameter"]))
        scheme = group["scheme"]
        pending = [path for path, decision in section_parameter_decisions(part, scheme).items()
                   if decision["required"] and decision["missing"]]
        render = self.comparison.set_model if view is None else view.set_section_parameters
        render(part, scheme, pending)

    def _load_fields(self, group):
        while self.edit_form.rowCount():
            self.edit_form.removeRow(0)
        part = group["asset"]
        draft = self._drafts.get(self._key(group), {}).get("values", {})
        self._edit_labels = _editable_fields(part)
        self._original_values = {path: self._original_value(part, path) for path in self._edit_labels}
        for (prefix, _), dimension in zip(_pipe_fields(part), construction_pipe_dimension_values(part)):
            for field in _PIPE_SIZES:
                self._original_values[prefix + field] = dimension[field[1:]]
            outside = prefix + _OD
            manual = dimension["has_legacy_outer_diameter"] or any(
                (part.get(key) or {}).get(outside) is not None
                for key in ("drawing_user_overrides", "section_scheme_user_overrides")
            ) and _get(part, prefix + _WALL) is None
            self._original_values[outside] = dimension["outer_diameter"] if manual else None
        self.edits, self._diameters, self._finish_expander = self._build_parameter_fields(self.edit_form, group, draft)
        self._watch_form(self.edits, self._on_edit)
        self._on_edit(publish=False)

    def _build_parameter_fields(self, form, group, values):
        part = group["asset"]
        add_form_value(form, "断面方案", _scheme_title(group["scheme"]))
        fields = {}
        diameters = {}
        for path, label in self._edit_labels.items():
            if path in {_COUNT, _SPACING, _FINISH} or path in _FINISH_FIELDS:
                continue
            fields[path] = add_numeric_parameter(form, path, label, values.get(path, self._original_text(path)))
            if path.endswith(_OD):
                fields[path].setToolTip("填写已知施工外径。改动公称直径或施工壁厚时，可重新按公式确定外径。")
                diameters[path.removesuffix(_OD)] = fields[path]

        multi = QCheckBox("多管并行")
        form.addRow(multi)
        for path in (_COUNT, _SPACING):
            fields[path] = add_numeric_parameter(form, path, self._edit_labels[path],
                                                 values.get(path, self._original_text(path)))
        count, spacing = fields[_COUNT], fields[_SPACING]
        spacing.setToolTip("填写相邻两根管外壁之间的净距。不同净距可按从左至右以逗号分隔。")
        multi.setChecked(count.text() != "1")

        def show_multi(active):
            form.setRowVisible(count, active)
            form.setRowVisible(spacing, active)

        def set_multi(active):
            show_multi(active)
            if not active:
                count.setText("1")
            elif count.text() == "1":
                count.setText("2")

        multi.toggled.connect(set_multi)
        show_multi(multi.isChecked())

        expander = QToolButton()
        expander.setText("回填完成面")
        expander.setCheckable(True)
        expander.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        form.addRow(expander)
        finish = fields[_FINISH] = QComboBox()
        finish.setAccessibleName(self._edit_labels[_FINISH])
        finish.setToolTip("按指定完成面整形时，以完成面和实际地形计算挖填。")
        finish.addItem("恢复原地面", "restore_terrain")
        finish.addItem("按指定完成面整形", "cover_depth")
        existing = self._original_values[_FINISH]
        if finish.findData(existing) < 0:
            finish.addItem("仅补填至指定完成面" if existing == "cover_above_terrain" else "沿用当前完成面", existing)
        finish.setCurrentIndex(max(0, finish.findData(values.get(_FINISH, existing))))
        form.addRow(self._edit_labels[_FINISH], finish)
        finish_fields = [path for path in _FINISH_FIELDS if path in self._edit_labels]
        for path in finish_fields:
            field = fields[path] = add_numeric_parameter(form, path, self._edit_labels[path],
                                                         values.get(path, self._original_text(path)))
            if ".bank_top_width_" in path:
                field.setToolTip("从该侧管道外缘到填筑平台边缘的水平宽度。")
        staged_sides = "、".join(label for side, label in (("left", "左侧"), ("right", "右侧"))
                               if _get(part, "construction.bank_stages_" + side))
        staged = QLabel(f"{staged_sides}沿用已设填筑分级。") if staged_sides else None
        if staged is not None:
            staged.setWordWrap(True)
            form.addRow(staged)

        def show_finish(*_):
            expanded = expander.isChecked()
            expander.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
            form.setRowVisible(finish, expanded)
            details = expanded and finish.currentData() in _COVER_MODES
            for path in finish_fields:
                form.setRowVisible(fields[path], details)
            if staged is not None:
                form.setRowVisible(staged, details)

        expander.setChecked(any(path in values for path in [_FINISH, *finish_fields]))
        expander.toggled.connect(show_finish)
        finish.currentIndexChanged.connect(show_finish)
        show_finish()
        return fields, diameters, expander

    @staticmethod
    def _original_value(part, path):
        value = _get(part, path)
        if path == _COUNT:
            explicit = _get(part, "section.pipes")
            if explicit:
                return len(explicit)
            if value is None:
                return 1
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return value
            return int(numeric) if numeric.is_integer() else value
        if path == _FINISH:
            return value or "restore_terrain"
        if path in ("construction.bank_top_width_left", "construction.bank_top_width_right") and value is None:
            return 0
        if value is None and path.endswith(".support_angle"):
            value = _seat(part)[1].get("angle", 120.)
        if value is None and path == PIPE_BACKFILL_HEIGHT_PATH:
            value = DEFAULT_MANUAL_BACKFILL_HEIGHT_M
        return value

    def _original_text(self, path):
        value = self._original_values[path]
        if value is not None and path.endswith(_PIPE_SIZES):
            return f"{value * 1000:.12g}"
        if isinstance(value, (list, tuple)):
            return "，".join(f"{item:g}" for item in value)
        return "" if value is None else str(value)

    def _raw_changes(self, edits=None):
        fields = self.edits if edits is None else edits
        values = {path: str(edit.currentData()) if isinstance(edit, QComboBox) else edit.text().strip()
                  for path, edit in fields.items()}
        for path in fields:
            if not path.endswith(_OD) or not values[path] or values[path] != self._original_text(path):
                continue
            prefix = path.removesuffix(_OD)
            if any(values[prefix + size] != self._original_text(prefix + size) for size in _PIPE_SIZES):
                with QSignalBlocker(fields[path]):
                    fields[path].clear()
                values[path] = ""
        if values[_FINISH] not in _COVER_MODES:
            for path in _FINISH_FIELDS:
                values.pop(path, None)
        if values[_COUNT] == "1":
            values.pop(_SPACING)
        return {path: value for path, value in values.items() if value != self._original_text(path)}

    def _changes(self, raw):
        values = {}
        for path, value in raw.items():
            if path == _FINISH:
                parsed = value
            elif path.endswith(_OD) and not value:
                parsed = None
            elif path == _SPACING and ("," in value or "，" in value):
                parsed = [_number(item.strip(), self._edit_labels[path]) for item in value.replace("，", ",").split(",")]
            else:
                parsed = _number(value, self._edit_labels[path], positive=path.endswith((_DN, _OD, ".support_angle")))
                if path.endswith(_PIPE_SIZES):
                    parsed /= 1000
            if not _same(parsed, self._original_values[path]):
                values[path] = parsed
        for path in values:
            if (path.endswith(_OD) and values[path] is not None
                    and any(path.removesuffix(_OD) + field in values for field in _PIPE_SIZES)):
                raise ValueError("指定施工外径与修改公称直径、壁厚请分别保存。")
        return values

    @staticmethod
    def _watch_form(fields, callback):
        for edit in fields.values():
            signal = edit.currentIndexChanged if isinstance(edit, QComboBox) else edit.textChanged
            signal.connect(callback)

    @staticmethod
    def _mark_unavailable_diameters(raw, diameters):
        for prefix, edit in diameters.items():
            if any(prefix + field in raw for field in (*_PIPE_SIZES, _OD)):
                edit.setPlaceholderText("—")

    def _on_edit(self, *_args, publish=True):
        group = self._group()
        if group is None:
            return
        raw = self._raw_changes()
        error = ""
        try:
            updates = self._changes(raw)
            self._render(updates)
        except ValueError as failure:
            error = str(failure)
            updates = {}
        if publish:
            key = self._key(group)
            if error or updates:
                self._drafts[key] = {"member": list(group["spans"][0][0][:2]),
                                     "members": [list(member) for member in self._members], "values": raw}
            else:
                self._drafts.pop(key, None)
            self.draft_changed.emit()
        self.cancel_button.setEnabled(bool(raw))
        self.save_button.setEnabled(bool(updates))
        if error:
            self.error.setText(error)
            self.error.show()
            if not publish:
                self._render()
            self._mark_unavailable_diameters(raw, self._diameters)
            return
        self.error.hide()

    def focus_parameter(self, path, *, station=None):
        if not isinstance(path, str) or not path:
            return False
        if station is not None:
            for index, group in enumerate(self._groups):
                if any(span[0][2] <= station <= span[0][3] for span in group["spans"]):
                    self.scope.setCurrentIndex(index)
                    break
        return self._group() is not None and self._focus_edit(self.edits, self._finish_expander, path)

    @staticmethod
    def _focus_edit(fields, finish_expander, path):
        if path in fields and (path == _FINISH or path in _FINISH_FIELDS):
            finish_expander.setChecked(True)
        return focus_parameter(fields, path)

    def _cancel(self):
        group = self._group()
        if group is None:
            return
        removed = self._drafts.pop(self._key(group), None)
        self._load_fields(group)
        if removed:
            self.draft_changed.emit()

    def _save(self):
        if self._group() is None:
            return
        self._save_changes(self.edits, self.error)

    def _save_changes(self, edits, error_label, *, dialog=None, opened_group=None):
        group = self._group()
        try:
            if group is None or (opened_group is not None and group is not opened_group):
                raise ValueError(_CHANGED_SCOPE)
            conflict = self.first_unapplied_edit(include_scope=True, overlapping=group["spans"])
            if conflict:
                if dialog is None:
                    self.conflicting_draft_requested.emit(conflict)
                error_label.setText("两份一般段草稿涉及同一范围。请取消其中一份再保存。")
                error_label.show()
                return
            updated = apply_general_section(
                self._inputs, group["spans"], self._changes(self._raw_changes(edits)))
        except (ValueError, TypeError, KeyError, StopIteration) as error:
            error_label.setText(str(error) or "一般段已变化，请重新选择。")
            error_label.show()
            return
        if dialog is not None:
            dialog.accept()
        self._cancel()
        if updated is not None:
            self.inputs_applied.emit(updated)

    def _open_model_editor(self):
        group = self._group()
        if group is None:
            return
        dialog = PipeSectionEditorDialog(self.window(), object_name="enlargedGeneralPipeSection",
                                         title="一般施工段 · 参数化断面",
                                         terrain_case=self.comparison.terrain_case.currentData())
        original_draft = self._raw_changes()
        fields, diameters, finish_expander = self._build_parameter_fields(dialog.form, group, original_draft)
        dialog.view.parameterRequested.connect(lambda path: self._focus_edit(fields, finish_expander, path))
        dialog.buttons.accepted.connect(
            lambda: self._save_changes(fields, dialog.message, dialog=dialog, opened_group=group))

        def refresh(*_):
            raw = {}
            try:
                if self._group() is not group:
                    raise ValueError(_CHANGED_SCOPE)
                raw = self._raw_changes(fields)
                updates = self._changes(raw)
                self._render(updates, view=dialog.view, diameters=diameters)
            except ValueError as failure:
                dialog.message.setText(str(failure))
                dialog.message.show()
                dialog.save_parameters.setEnabled(False)
                self._mark_unavailable_diameters(raw, diameters)
                return
            dialog.message.hide()
            dialog.save_parameters.setEnabled(bool(updates) or (bool(original_draft) and raw != original_draft))

        self._watch_form(fields, refresh)
        refresh()
        dialog.open()

    def first_unapplied_edit(self, *, include_scope=False, overlapping=None, member_scope=None):
        scopes = {}
        span_keys = {span[0] for span in overlapping or ()}
        scope_members = set(member_scope) if member_scope is not None else None
        for key, draft in self._drafts.items():
            if not draft["values"]:
                continue
            member = tuple(draft["member"])
            members = tuple(map(tuple, draft.get("members", ())))
            if not members and member in self._members:
                members = self._members
            if not members or (self._live_member_sets is not None and members not in self._live_member_sets):
                continue
            if scope_members is not None and scope_members.isdisjoint(members):
                continue
            if overlapping is not None and (
                    members == self._members or not any(span[:2] in members for span in span_keys)):
                continue
            if members not in scopes:
                groups = (self._groups if self._live_inputs is self._inputs and members == self._members
                          else general_section_groups(self._live_inputs, members))
                scopes[members] = {_draft_key(members, group): group for group in groups}
            group = scopes[members].get(key)
            if group is None or (overlapping is not None
                                 and not any(span[0] in span_keys for span in group["spans"])):
                continue
            if draft["values"].keys() & _editable_fields(group["asset"]).keys():
                return (member, members) if include_scope else member
        return None

    def export_drafts(self):
        return deepcopy(self._drafts)

    def restore_drafts(self, state):
        if not isinstance(state, dict):
            self._drafts = {}
            return
        self._drafts = {}
        for key, draft in state.items():
            if not isinstance(draft, dict) or not isinstance(draft.get("values"), dict) or not _valid_member(draft.get("member")):
                continue
            members = draft.get("members", ())
            if isinstance(members, (list, tuple)) and all(_valid_member(member) for member in members):
                self._drafts[key] = deepcopy(draft)

    def reset_context(self):
        self._drafts.clear()
        self._live_member_sets = None
        self.set_context({}, ())
