"""Review detected transition connections without editing the source design."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from 土石方计算.io.concise_quantities import connection_estimate_note
from 土石方计算.services.transition_connections import connection_needs_settings, transition_section_defaults

from .channel_size_calculator import RectangularChannelCalculator

_STATUS_LABELS = {
    "ready": "可采用", "needs_parameters": "参数待明确", "applied": "已采用",
    "automatic": "已自动采用", "covered": "已有对象覆盖，不重复计量",
    "estimated": "采用默认估算",
}
_SECTION_LABELS = {
    "circular_culvert": "圆管涵", "circular_channel": "圆形明渠",
    "circular_siphon": "圆管", "rectangular_channel": "矩形明渠",
    "trapezoidal_channel": "梯形明渠", "rectangular_culvert": "矩形暗涵",
    "u_channel": "U 形明渠", "compound_trapezoidal_channel": "复式梯形明渠",
    "arch_culvert": "圆拱直墙暗涵",
}
_OPEN_SECTIONS = ("rectangular_channel", "trapezoidal_channel", "u_channel", "compound_trapezoidal_channel")
_CLOSED_SECTIONS = ("circular_culvert", "rectangular_culvert", "arch_culvert")
_RECTANGULAR_SECTIONS = {"rectangular_channel", "rectangular_culvert"}
_REPLACEABLE_STATUSES = {"applied", "automatic", "estimated"}
_DIMENSIONS = {
    "inner_width": ("净底宽 m", None), "inner_height": ("净高 m", None),
    "inner_radius": ("净内半径 m", None), "inner_side_slope": ("内边坡比 m:1", None),
    "u_arc_angle_degrees": ("底弧圆心角 °", 180), "u_side_angle_degrees": ("侧墙外倾角 °", 0),
    "compound_lower_height": ("下段高度 m", None), "compound_bench_width": ("平台宽 m", None),
    "compound_upper_slope": ("上段边坡比 m:1", None),
    "compound_lower_slope": ("下段边坡比 m:1", None),
    "compound_right_slope": ("右侧边坡比 m:1", None),
    "wall_height": ("直墙净高 m", None), "arch_angle_degrees": ("拱圆心角 °", 180),
}
_SECTION_FIELDS = {
    "rectangular_channel": ("inner_width", "inner_height"),
    "trapezoidal_channel": ("inner_width", "inner_height", "inner_side_slope"),
    "u_channel": ("inner_radius", "inner_height", "u_arc_angle_degrees", "u_side_angle_degrees"),
    "compound_trapezoidal_channel": ("inner_width", "inner_height", "compound_lower_height",
                                   "compound_bench_width", "compound_upper_slope",
                                   "compound_lower_slope", "compound_right_slope"),
    "rectangular_culvert": ("inner_width", "inner_height"),
    "arch_culvert": ("inner_width", "wall_height", "arch_angle_degrees"),
}
_LINING_LABELS = {
    "base_thickness": "底板厚 m", "u_bottom_thickness": "底弧厚 m",
    "wall_thickness": "圆涵壁厚 m", "wall_thickness_left": "左墙衬砌厚 m",
    "wall_thickness_right": "右墙衬砌厚 m", "roof_thickness": "顶板或拱衬厚 m",
}
_SIDE_FIELDS = ("wall_thickness_left", "wall_thickness_right")


def _lining_fields(shape):
    if shape == "circular_culvert":
        return ("wall_thickness",)
    if shape == "u_channel":
        return ("u_bottom_thickness", *_SIDE_FIELDS)
    if shape in _SECTION_FIELDS:
        top = ("roof_thickness",) if shape in _CLOSED_SECTIONS else ()
        return ("base_thickness", *_SIDE_FIELDS, *top)
    return ()


_COVER_FIELDS = {
    "final_cover_depth": ("涵顶覆土 m", 0.5),
    "bank_slope_left": ("左侧填筑坡比 m:1", 1.5),
    "bank_slope_right": ("右侧填筑坡比 m:1", 1.5),
    "bank_top_width_left": ("左侧平台宽 m", 0.),
    "bank_top_width_right": ("右侧平台宽 m", 0.),
}
_INVERT_FIELDS = {"start_invert": ("起桩净内底高程 m", None), "end_invert": ("终桩净内底高程 m", None)}


def _number(value):
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def _text(value):
    number = _number(value)
    return "" if number is None else f"{number:.6f}".rstrip("0").rstrip(".")


def _station(value):
    number = _number(value)
    if number is None:
        return "待明确"
    sign = "-" if number < 0 else ""
    km, rest = divmod(abs(number), 1000)
    return f"{sign}K{int(km)}+{rest:07.3f}"


def _profile_description(candidate):
    profile = candidate.get("adopted_profile") or candidate.get("profile") or {}
    points = profile.get("points") or []
    if not points:
        return "缺少可靠源高程"
    first, last = points[0], points[-1]
    reference = profile.get("reference")
    label = {"inner_invert": "内底", "pipe_axis": "管轴"}.get(reference, reference or "基准待定")
    return f"{label} {_text(first.get('elevation'))} → {_text(last.get('elevation'))}"


def _source_inverts(candidate):
    values = dict(candidate.get("source_inverts") or {})
    profile = candidate.get("adopted_profile") or candidate.get("profile") or {}
    points = profile.get("points") or []
    if points:
        values.update(start_invert=points[0].get("elevation"), end_invert=points[-1].get("elevation"))
    return values


def _candidate_basis(candidates):
    sources = [{key: value for key, value in row.items() if key not in {"channel_inputs", "source_inverts"}}
               for row in candidates]
    encoded = json.dumps(sources, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf8")).hexdigest()


class TransitionConnectionsDialog(QDialog):
    """Stage candidate choices; ``updated_inputs`` is set only after apply succeeds.

    ``draft_state()`` is JSON-safe and can be saved in the host's UI state, then
    passed back on reopen. Candidate-source changes prevent replaying old edits.
    The service owns all geometry, construction inheritance and duplicate checks.
    """

    def __init__(self, inputs, parent=None, *, draft_state=None, candidate_id=None):
        super().__init__(parent)
        self.inputs = deepcopy(inputs)
        self.updated_inputs = None
        self.report = None
        self.candidates = deepcopy(inputs.get("transition_candidates") or [])
        self._estimates = {item["asset_id"]: item for item in inputs.get("connector_estimates", [])}
        self._basis = _candidate_basis(self.candidates)
        self._applied_rows = set()
        self._unmatched_draft = None
        self._manual_rows = set()
        self._replacement_rows = set()
        self._row_settings = {}
        self._section_defaults = {}
        self._form_defaults = {}
        self._adopted_assets = {}
        current_assets = {}
        assets_by_id = {}
        for network in self.inputs.get("networks", []):
            for asset in network.get("assets", []):
                if asset.get("asset_id"):
                    assets_by_id[asset["asset_id"]] = asset
                identifier = asset.get("transition_candidate_id")
                if identifier:
                    current_assets.setdefault(identifier, []).append(asset)
        for candidate in self.candidates:
            identifier = candidate.get("candidate_id")
            assets = current_assets.get(identifier, [])
            if candidate.get("status") == "estimated":
                assets = [assets_by_id[key] for key in candidate.get("estimated_asset_ids", []) if key in assets_by_id]
            if len(assets) == 1 and assets[0].get("station_start") == candidate.get("station_start") and (
                    assets[0].get("station_end") == candidate.get("station_end")):
                self._adopted_assets[identifier] = assets[0]
        self.setWindowTitle("连接段设置")
        self.resize(1180, 780)
        layout = QVBoxLayout(self)
        introduction = QLabel(
            "已有估算直接参与算量。待补连接可先保留，继续计算已就绪区段。"
            "选择一行可核对断面、尺寸和高程。")
        introduction.setWordWrap(True)
        layout.addWidget(introduction)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(len(self.candidates), 8)
        self.table.setHorizontalHeaderLabels([
            "采用", "连接段 / 来源", "起止桩号", "长度 m", "源高程 m", "采用断面", "圆涵外径 m", "状态 / 待核事项"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((48, 170, 185, 75, 180, 125, 90, 245)):
            self.table.setColumnWidth(column, width)
        self.table.setMinimumHeight(220)
        self.table.setWordWrap(True)
        self._section_choices = []
        for row, candidate in enumerate(self.candidates):
            self._populate_row(row, candidate)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.select_ready_button = QPushButton("勾选可设置连接")
        self.select_ready_button.clicked.connect(self.select_ready)
        actions.addWidget(self.select_ready_button)
        self.clear_button = QPushButton("清除勾选")
        self.clear_button.clicked.connect(self.clear_selection)
        actions.addWidget(self.clear_button)
        self.edit_existing_button = QPushButton("修改已采用连接")
        self.edit_existing_button.clicked.connect(self._enable_replacement)
        actions.addWidget(self.edit_existing_button)
        self.manual_profile_button = QPushButton("填写缺失高程")
        self.manual_profile_button.clicked.connect(self._enable_manual_profile)
        actions.addWidget(self.manual_profile_button)
        actions.addStretch()
        actions.addWidget(QLabel("圆涵外径 D（m）"))
        self.batch_diameter = QLineEdit()
        self.batch_diameter.setPlaceholderText("明确设计直径")
        self.batch_diameter.setMaximumWidth(140)
        actions.addWidget(self.batch_diameter)
        self.batch_button = QPushButton("将所选设为圆管涵")
        self.batch_button.clicked.connect(self.set_selected_circular)
        actions.addWidget(self.batch_button)
        layout.addLayout(actions)

        self.parameters = QGroupBox("当前连接参数")
        self.parameter_layout = QGridLayout(self.parameters)
        self.fields = {}
        labels = {key: label for key, (label, _) in {**_DIMENSIONS, **_COVER_FIELDS, **_INVERT_FIELDS}.items()}
        for key, label in {**labels, **_LINING_LABELS}.items():
            field = QLineEdit()
            field.setObjectName("connection_" + key)
            field.setMaximumWidth(135)
            field.textChanged.connect(lambda value, name=key: self._change_parameter(name, value))
            self.fields[key] = (QLabel(label), field)
        self.target_label = QLabel("暗涵回填")
        self.target_mode = QComboBox()
        self.target_mode.setObjectName("connectionTargetMode")
        self.target_mode.addItem("回填至原地表", "restore_terrain")
        self.target_mode.addItem("涵顶覆土，可高于原地表", "cover_above_terrain")
        self.target_mode.currentIndexChanged.connect(self._change_target)
        parameter_area = QHBoxLayout()
        parameter_area.addWidget(self.parameters, 1)
        self.calculator = RectangularChannelCalculator()
        self.calculator.dimensions_applied.connect(self._use_channel_dimensions)
        self._calculator_row = None
        parameter_area.addWidget(self.calculator)
        layout.addLayout(parameter_area)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(94)
        self.details.setPlaceholderText("未明确条件将在这里集中列出；选择一行可查看来源与高程依据。")
        layout.addWidget(self.details)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setText("应用所选连接段")
        self.apply_button.clicked.connect(self.apply)
        self.apply_current_button = buttons.addButton("应用当前连接", QDialogButtonBox.ActionRole)
        self.apply_current_button.clicked.connect(self._apply_current)
        buttons.button(QDialogButtonBox.Cancel).setText("关闭（未应用设置保留为草稿）")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.table.itemChanged.connect(self._refresh_status)
        self.table.itemSelectionChanged.connect(self._refresh_details)
        self.batch_diameter.textChanged.connect(self._refresh_status)
        self.restore_draft_state(draft_state)
        self._refresh_status()
        if self.candidates:
            row = next((index for index, candidate in enumerate(self.candidates)
                        if candidate.get("candidate_id") == candidate_id), 0)
            self.table.selectRow(row)
            self.table.scrollToItem(self.table.item(row, 1))
        self._refresh_details()

    def _closed_candidate(self, candidate):
        return not connection_needs_settings(candidate)

    def _can_select(self, candidate, row=None):
        if candidate.get("status") == "covered":
            return False
        if self._closed_candidate(candidate) and row not in self._replacement_rows:
            return False
        return bool((candidate.get("adopted_profile") or candidate.get("profile") or {}).get("points")
                    or row in self._manual_rows)

    def _populate_row(self, row, candidate):
        suggested = self._defaults_for(row)
        adopted = self._adopted(candidate)
        section = adopted.get("section") or suggested.get("section") or {}
        diameter = section.get("outer_diameter") or section.get("nominal_diameter_m") or suggested.get("diameter_m")
        check = QTableWidgetItem()
        check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        if self._can_select(candidate, row):
            check.setFlags(check.flags() | Qt.ItemIsUserCheckable)
            check.setCheckState(Qt.Unchecked if candidate.get("source_kind") == "missing_ip_gap" else Qt.Checked)
        else:
            check.setCheckState(Qt.Unchecked)
            check.setToolTip("可用操作见下方按钮。")
        self.table.setItem(row, 0, check)
        source = "、".join(str(item) for item in candidate.get("source_types") or [])
        if candidate.get("source_kind") == "missing_ip_gap":
            source = ("缺 IP 点 · " + source).rstrip(" · ")
        values = {
            1: str(candidate.get("name") or candidate.get("candidate_id") or "连接段") + ("\n" + source if source else ""),
            2: f"{_station(candidate.get('station_start'))}～{_station(candidate.get('station_end'))}",
            3: _text((_number(candidate.get("station_end")) or 0) - (_number(candidate.get("station_start")) or 0)),
            4: _profile_description(candidate),
            6: _text(diameter),
            7: _STATUS_LABELS.get(candidate.get("status"), "需核对") + ("\n" + "；".join(candidate.get("reasons") or []) if candidate.get("reasons") else ""),
        }
        for column, text in values.items():
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            if column != 6 or not self._can_select(candidate, row):
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, column, item)
        choice = QComboBox()
        if candidate.get("status") == "estimated":
            shapes = [self._estimates.get(key, {}).get("section_type") for key in candidate.get("estimated_asset_ids", [])]
            labels = list(dict.fromkeys(_SECTION_LABELS.get(shape, "估算断面") for shape in shapes))
            choice.addItem("、".join(labels) or "估算断面", "")
        shape = adopted.get("section_type") or suggested.get("section_type") or "circular_culvert"
        for key in (*_CLOSED_SECTIONS, *_OPEN_SECTIONS):
            choice.addItem(_SECTION_LABELS[key], key)
        if choice.findData(shape) < 0:
            choice.addItem(_SECTION_LABELS.get(shape, "沿用源断面"), shape)
        if choice.itemData(0) != "":
            choice.setCurrentIndex(choice.findData(shape))
        choice.setEnabled(self._can_select(candidate, row))
        choice.currentIndexChanged.connect(lambda _index, selected=row: self._section_changed(selected))
        self._section_choices.append(choice)
        self.table.setCellWidget(row, 5, choice)
        self._update_diameter_editability(row)
        self.table.setRowHeight(row, 62)

    def _adopted(self, candidate):
        return self._adopted_assets.get(candidate.get("candidate_id")) or {
            "section_type": candidate.get("adopted_section_type"),
            "section": candidate.get("adopted_section"),
            "construction": candidate.get("adopted_construction"),
        }

    def selected_rows(self):
        return [row for row, candidate in enumerate(self.candidates)
                if self._can_select(candidate, row) and self.table.item(row, 0).checkState() == Qt.Checked]

    def select_ready(self):
        with QSignalBlocker(self.table):
            for row, candidate in enumerate(self.candidates):
                if self._can_select(candidate, row):
                    self.table.item(row, 0).setCheckState(Qt.Checked)
        self._refresh_status()

    def clear_selection(self):
        with QSignalBlocker(self.table):
            for row in range(len(self.candidates)):
                self.table.item(row, 0).setCheckState(Qt.Unchecked)
        self._refresh_status()

    def set_selected_circular(self):
        diameter = _number(self.batch_diameter.text())
        if diameter is None or diameter <= 0:
            self.status_label.setText("请填写大于零的明确设计直径，再批量设置所选连接段。")
            return
        rows = self.selected_rows()
        if not rows:
            self.status_label.setText("请先勾选需要设置的连接段。")
            return
        for row in rows:
            choice = self._section_choices[row]
            choice.setCurrentIndex(choice.findData("circular_culvert"))
            self.table.item(row, 6).setText(_text(diameter))
        self.status_label.setText(f"已将 {len(rows)} 个所选连接设为 D{_text(diameter)} 圆管涵；点击应用后参与算量。")

    def _enable_replacement(self):
        row = self.table.currentRow()
        if row < 0:
            return
        self._replacement_rows.add(row)
        self._enable_row(row)
        if not self._section_choices[row].currentData():
            shape = (self._adopted(self.candidates[row]).get("section_type")
                     or self._defaults_for(row).get("section_type")
                     or "circular_culvert")
            choice = self._section_choices[row]
            choice.setCurrentIndex(choice.findData(shape))
        self._refresh_details()

    def _enable_manual_profile(self):
        row = self.table.currentRow()
        if row < 0:
            return
        draft = self._stored_settings(row).setdefault("profile", {})
        for key, value in _source_inverts(self.candidates[row]).items():
            if _number(value) is not None:
                draft.setdefault(key, _text(value))
        self._manual_rows.add(row)
        self._enable_row(row)
        self._refresh_details()

    def _enable_row(self, row):
        candidate = self.candidates[row]
        can_select = self._can_select(candidate, row)
        check = self.table.item(row, 0)
        check.setFlags(check.flags() | Qt.ItemIsUserCheckable if can_select else check.flags() & ~Qt.ItemIsUserCheckable)
        self._section_choices[row].setEnabled(can_select)
        self._update_diameter_editability(row)
        if can_select:
            check.setCheckState(Qt.Checked)

    def _update_diameter_editability(self, row):
        item = self.table.item(row, 6)
        editable = self._can_select(self.candidates[row], row) and self._section_choices[row].currentData() == "circular_culvert"
        item.setFlags(item.flags() | Qt.ItemIsEditable if editable else item.flags() & ~Qt.ItemIsEditable)

    def _section_changed(self, row):
        if self._section_choices[row].currentData() == "circular_culvert" and not self.table.item(row, 6).text():
            self.table.item(row, 6).setText(_text(self._defaults_for(row, "circular_culvert").get("diameter_m")))
        self._update_diameter_editability(row)
        if self.table.currentRow() != row:
            self.table.selectRow(row)
        self._refresh_status()
        self._refresh_parameters()

    def _stored_settings(self, row):
        return self._row_settings.setdefault(row, {})

    def _defaults_for(self, row, shape=None):
        key = row, shape
        if key not in self._section_defaults:
            self._section_defaults[key] = transition_section_defaults(self.inputs, self.candidates[row], shape)
        return self._section_defaults[key]

    def _initial_section(self, row, shape):
        suggested = self._defaults_for(row, shape)
        candidate = self.candidates[row]
        adopted = self._adopted(candidate)
        section = suggested.get("section") or {}
        if shape == adopted.get("section_type"):
            adopted_section = {key: value for key, value in (adopted.get("section") or {}).items() if value is not None}
            if (candidate.get("status") == "estimated" and suggested.get("reference_asset_id")
                    and adopted.get("parameter_source") != "user_confirmed"
                    and not any(adopted.get(key) for key in ("drawing_user_overrides", "section_scheme_user_overrides"))):
                return {**adopted_section, **section}
            section = {**section, **adopted_section}
        return section

    def _channel_defaults(self, row, shape, section):
        candidate = self.candidates[row]
        values = {"flow": _number(candidate.get("design_flow")), **(candidate.get("channel_inputs") or {})}
        if shape in _RECTANGULAR_SECTIONS and (_number(section.get("inner_width")) or 0.) > 0.:
            values["bottom_width"] = section["inner_width"]
        return values

    def _default_shape_settings(self, row, shape):
        from 土石方计算.services.construction_defaults import apply_assumed_construction

        suggested = self._defaults_for(row, shape)
        section = deepcopy(self._initial_section(row, shape))
        construction = dict(suggested.get("construction") or {})
        adopted = self._adopted(self.candidates[row])
        if shape == adopted.get("section_type"):
            construction.update(adopted.get("construction") or {})

        if shape in _RECTANGULAR_SECTIONS:
            missing = [key for key in ("inner_width", "inner_height") if (_number(section.get(key)) or 0.) <= 0.]
            if missing:
                dimensions = self.calculator.suggest_dimensions(self._channel_defaults(row, shape, section))
                if dimensions:
                    for key, value in zip(("inner_width", "inner_height"), dimensions):
                        if key in missing:
                            section[key] = value

        # Opening a form previews the same construction defaults used on apply.
        # A known outside diameter alone does not determine a circular wall.
        if shape in _SECTION_FIELDS:
            asset = {"asset_id": "connection-form", "kind": suggested["kind"], "section_type": shape,
                     "section": section, "construction": construction}
            apply_assumed_construction({"networks": [{"assets": [asset]}]})
            if shape == "u_channel" and section.get("u_bottom_thickness") is None:
                section["u_bottom_thickness"] = section.get("base_thickness")
        elif shape == "circular_culvert" and _number(section.get("wall_thickness")) is None:
            inner, outer = (_number(section.get(key)) for key in ("inner_diameter", "outer_diameter"))
            lining = _number(section.get("lining_thickness")) or 0.
            if not section.get("earthwork_envelope_only") and inner is not None and outer is not None:
                thickness = (outer - inner) / 2. - lining
                if inner > 0. and thickness > 0.:
                    section["wall_thickness"] = thickness

        values = {key: _text(section.get(key, _DIMENSIONS[key][1])) for key in _SECTION_FIELDS.get(shape, ())}
        values.update({key: _text(section.get(key, section.get("wall_thickness") if key in _SIDE_FIELDS else None))
                       for key in _lining_fields(shape)})
        values.update({key: _text(construction.get(key, default)) for key, (_, default) in _COVER_FIELDS.items()})
        target = construction.get("target_mode")
        values["target_mode"] = "cover_above_terrain" if target in {"cover_above_terrain", "finished_profile"} else "restore_terrain"
        return values

    def _shape_draft(self, row):
        shape = self._section_choices[row].currentData()
        return self._stored_settings(row).setdefault(shape, {})

    def _shape_settings(self, row):
        shape = self._section_choices[row].currentData()
        key = row, shape
        if key not in self._form_defaults:
            self._form_defaults[key] = self._default_shape_settings(row, shape)
        return {**self._form_defaults[key], **self._shape_draft(row)}

    def _change_parameter(self, key, value):
        row = self.table.currentRow()
        if row < 0:
            return
        if key in _INVERT_FIELDS:
            self._stored_settings(row).setdefault("profile", {})[key] = value
        else:
            self._shape_draft(row)[key] = value
        self._refresh_status()

    def _change_target(self, *_):
        row = self.table.currentRow()
        if row < 0:
            return
        settings = self._shape_draft(row)
        settings["target_mode"] = self.target_mode.currentData()
        settings["target_changed"] = True
        self._refresh_status()
        self._refresh_parameters()

    def _refresh_parameters(self):
        self.calculator.hide()
        for label, field in (*self.fields.values(), (self.target_label, self.target_mode)):
            self.parameter_layout.removeWidget(label)
            self.parameter_layout.removeWidget(field)
            label.hide()
            field.hide()
        row = self.table.currentRow()
        if row < 0:
            self.manual_profile_button.setEnabled(False)
            self.edit_existing_button.setEnabled(False)
            self.apply_current_button.setEnabled(False)
            self.parameters.hide()
            return
        candidate = self.candidates[row]
        self.edit_existing_button.setEnabled(
            candidate.get("status") in _REPLACEABLE_STATUSES and row not in self._replacement_rows)
        profile = candidate.get("adopted_profile") or candidate.get("profile")
        self.manual_profile_button.setText("编辑起终桩高程" if profile else "填写缺失高程")
        self.manual_profile_button.setEnabled(
            bool(candidate.get("plan_alignment")) and row not in self._manual_rows
            and (not self._closed_candidate(candidate) or row in self._replacement_rows))
        shape = self._section_choices[row].currentData()
        active = self._can_select(candidate, row)
        self.apply_current_button.setEnabled(active)
        if not active:
            self.parameters.hide()
            return
        settings = self._shape_settings(row)
        fields = [*_SECTION_FIELDS.get(shape, ()), *_lining_fields(shape)]
        defaults = self._defaults_for(row, shape)
        reference = defaults.get("reference_name")
        self.parameters.setTitle(f"当前连接参数 · 参考 {reference}" if reference else "当前连接参数")
        section = self._initial_section(row, shape)
        required = _SECTION_FIELDS.get(shape, ())
        has_dimensions = (bool(_number(defaults.get("diameter_m")) or section.get("outer_diameter"))
                          if shape == "circular_culvert" else
                          bool(required) and all(_number(section.get(key, _DIMENSIONS[key][1])) is not None
                                                 for key in required))
        if not has_dimensions:
            slot = row, shape
            if self._calculator_row != slot:
                self._save_calculator_values()
                self._calculator_row = slot
                self.calculator.set_values(self._stored_settings(row).get("calculator", {}),
                                           defaults=self._channel_defaults(row, shape, section))
            rectangular = shape in _RECTANGULAR_SECTIONS
            self.calculator.apply_button.setText("采用净宽和净高" if rectangular else "采用为矩形明渠")
            self.calculator.show()
        if shape in _CLOSED_SECTIONS:
            fields += ["target_mode"]
            if settings["target_mode"] == "cover_above_terrain":
                fields.extend(_COVER_FIELDS)
        if row in self._manual_rows:
            fields.extend(_INVERT_FIELDS)
        self.parameters.setVisible(bool(fields))
        for index, key in enumerate(fields):
            if key == "target_mode":
                label, field = self.target_label, self.target_mode
                with QSignalBlocker(field):
                    field.setCurrentIndex(field.findData(settings[key]))
            else:
                label, field = self.fields[key]
                values = self._stored_settings(row).get("profile", {}) if key in _INVERT_FIELDS else settings
                with QSignalBlocker(field):
                    field.setText(str(values.get(key, "")))
            grid_row, column = divmod(index, 3)
            self.parameter_layout.addWidget(label, grid_row, column * 2)
            self.parameter_layout.addWidget(field, grid_row, column * 2 + 1)
            label.show()
            field.show()

    def _save_calculator_values(self):
        if self._calculator_row is not None:
            self._stored_settings(self._calculator_row[0])["calculator"] = self.calculator.values()

    def _use_channel_dimensions(self, width, height):
        row = self.table.currentRow()
        if row < 0 or not self._can_select(self.candidates[row], row):
            return
        choice = self._section_choices[row]
        if choice.currentData() not in _RECTANGULAR_SECTIONS:
            choice.setCurrentIndex(choice.findData("rectangular_channel"))
        settings = self._shape_draft(row)
        settings.update(inner_width=f"{width:.12g}", inner_height=f"{height:.12g}")
        self._refresh_parameters()
        self._refresh_status()

    def _override_for(self, row):
        candidate = self.candidates[row]
        shape = self._section_choices[row].currentData()
        override = {"section_type": shape}
        settings = self._shape_settings(row)
        edits = self._shape_draft(row)
        adopted = self._adopted(candidate)
        same_shape = shape == adopted.get("section_type")
        existing_section = deepcopy(self._initial_section(row, shape))
        existing_construction = deepcopy(adopted.get("construction") or {}) if same_shape else {}
        lining = {}
        for key in _lining_fields(shape):
            text = settings.get(key, "").strip()
            if text:
                value = _number(text)
                if value is None or value < 0. or shape in _CLOSED_SECTIONS and value == 0.:
                    condition = "大于零" if shape in _CLOSED_SECTIONS else "大于等于零"
                    raise ValueError(f"{_LINING_LABELS[key]}须{condition}")
                if key in edits:
                    lining[key] = value
        if shape == "circular_culvert":
            diameter = _number(self.table.item(row, 6).text())
            if diameter is None or diameter <= 0:
                raise ValueError("请填写大于零的明确圆管涵直径")
            prior_section = existing_section or self._initial_section(row, shape)
            prior_diameter = (prior_section.get("outer_diameter") or prior_section.get("nominal_diameter_m")
                              or self._defaults_for(row, shape).get("diameter_m"))
            wall = lining.get("wall_thickness")
            same_diameter = prior_diameter is not None and abs(float(prior_diameter) - diameter) <= 1e-6
            if wall is not None and (not same_diameter or _text(wall) != _text(prior_section.get("wall_thickness"))):
                if diameter <= 2. * wall:
                    raise ValueError("圆涵外径须大于两倍壁厚")
                override["section"] = {"outer_diameter": diameter, "inner_diameter": diameter - 2. * wall,
                                       "wall_thickness": wall}
            elif same_diameter and prior_section:
                override["section"] = deepcopy(prior_section)
            else:
                override["diameter_m"] = diameter
        elif shape in _SECTION_FIELDS:
            section = existing_section
            for key in _SECTION_FIELDS[shape]:
                number = _number(settings.get(key))
                allow_zero = key.endswith("_slope") or key in {"u_side_angle_degrees", "compound_bench_width", "wall_height"}
                if number is None or number < 0 or (number == 0 and not allow_zero):
                    raise ValueError("请填写" + _DIMENSIONS[key][0])
                if key in edits or _number(section.get(key)) is None or _text(section[key]) != settings[key]:
                    section[key] = number
            override["section"] = {**section, **lining}
        elif not shape or shape != (candidate.get("suggested_section") or {}).get("section_type"):
            raise ValueError("请选择连接断面")
        if existing_construction:
            override["construction"] = existing_construction
        if shape in _CLOSED_SECTIONS:
            target = settings["target_mode"]
            if target == "cover_above_terrain":
                construction = {**existing_construction, "target_mode": target}
                for key in _COVER_FIELDS:
                    number = _number(settings.get(key))
                    if number is None or number < 0:
                        raise ValueError("请填写" + _COVER_FIELDS[key][0])
                    construction[key] = number
                for side in ("left", "right"):
                    slope = "bank_slope_" + side
                    if construction[slope] != existing_construction.get(slope):
                        construction.pop("bank_stages_" + side, None)
                override["construction"] = construction
            elif shape != "circular_culvert" or settings.get("target_changed") or existing_construction:
                override["construction"] = {**existing_construction, "target_mode": target}
        if row in self._manual_rows:
            values = self._stored_settings(row).get("profile") or {}
            source_inverts = _source_inverts(candidate)
            endpoints = []
            for key, station in (("start_invert", "station_start"), ("end_invert", "station_end")):
                elevation = _number(values.get(key))
                if elevation is None:
                    raise ValueError("请填写" + _INVERT_FIELDS[key][0])
                if _text(source_inverts.get(key)) == values[key]:
                    elevation = _number(source_inverts[key])
                endpoints.append({"station": candidate[station], "elevation": elevation})
            profile = candidate.get("adopted_profile") or candidate.get("profile") or {}
            points = [endpoints[0], *(profile.get("points") or [])[1:-1], endpoints[-1]]
            override["profile"] = {"reference": "inner_invert", "points": points, "basis": "用户填写起终桩净内底"}
        if row in self._replacement_rows:
            override["replace_existing"] = True
            if "profile" not in override:
                profile = adopted.get("connection_profile_override")
                if not profile and not candidate.get("profile"):
                    profile = candidate.get("adopted_profile")
                if profile:
                    override["profile"] = deepcopy(profile)
        return override

    def _refresh_status(self, *_):
        if not hasattr(self, "apply_button"):
            return
        selected = len(self.selected_rows())
        applied = sum(self._closed_candidate(item) for item in self.candidates)
        missing = sum(not self._closed_candidate(item) and not self._can_select(item, row)
                      for row, item in enumerate(self.candidates))
        self.summary_label.setText(f"检测到 {len(self.candidates)} 个连接段，已采用、估算或覆盖 {applied} 个，"
                                   f"本次勾选 {selected} 个，源高程待明确 {missing} 个。")
        self.apply_button.setEnabled(bool(selected))
        # The source candidate status describes detection, whereas this column
        # must describe the user's current staged configuration. Keep original
        # warnings in the source detail rather than showing them as unfilled D.
        with QSignalBlocker(self.table):
            for row, candidate in enumerate(self.candidates):
                if not self._can_select(candidate, row):
                    continue
                try:
                    self._override_for(row)
                    status = ("已设置，待应用" if self.table.item(row, 0).checkState() == Qt.Checked
                              else "已设置，未勾选")
                except ValueError as error:
                    status = "参数待明确 · " + str(error)
                item = self.table.item(row, 7)
                item.setText(status)
                reasons = "；".join(candidate.get("reasons") or [])
                item.setToolTip(status + ("\n源资料提示：" + reasons if reasons else ""))

    def _refresh_details(self):
        lines = []
        for row, candidate in enumerate(self.candidates):
            if not self._closed_candidate(candidate) and (candidate.get("reasons") or not self._can_select(candidate, row)):
                reasons = "；".join(candidate.get("reasons") or []) or "缺少可靠源高程，待补设计资料。"
                lines.append(f"源资料提示｜{candidate.get('name') or candidate.get('candidate_id')}：{reasons}")
        selected = self.table.currentRow()
        if 0 <= selected < len(self.candidates):
            candidate = self.candidates[selected]
            profile = candidate.get("adopted_profile") or candidate.get("profile") or {}
            lines.append("\n当前连接：" + str(candidate.get("name") or candidate.get("candidate_id")))
            lines.append("源节点：" + "、".join(str(item) for item in candidate.get("source_node_ids") or []))
            lines.append("高程依据：" + str(profile.get("basis") or "未提供"))
            if candidate.get("status") == "estimated":
                for key in candidate.get("estimated_asset_ids", []):
                    estimate = self._estimates.get(key)
                    if estimate:
                        note = connection_estimate_note(estimate)
                        if note:
                            lines.append("估算依据：" + note)
            else:
                lines.append("施工构造应用后可在“断面与施工”查看。")
        self.details.setPlainText("\n".join(lines))
        self._refresh_parameters()

    def draft_state(self):
        self._save_calculator_values()
        candidates = self.updated_inputs.get("transition_candidates", ()) if self.updated_inputs is not None else self.candidates
        return {"version": 1, "basis": _candidate_basis(candidates), "batch_diameter": self.batch_diameter.text(),
                "rows": {str(candidate.get("candidate_id")): {
                    "selected": self.table.item(row, 0).checkState() == Qt.Checked,
                    "section_type": self._section_choices[row].currentData(),
                    "diameter": self.table.item(row, 6).text(),
                    "settings": deepcopy(self._row_settings.get(row) or {}),
                    "replace_existing": row in self._replacement_rows,
                    "manual_profile": row in self._manual_rows,
                } for row, candidate in enumerate(self.candidates) if row not in self._applied_rows},
                **({"unmatched_prior": deepcopy(self._unmatched_draft)} if self._unmatched_draft else {})}

    def restore_draft_state(self, state):
        if not state:
            return True
        if state.get("basis") != self._basis:
            self._unmatched_draft = deepcopy(state)
            self.status_label.setText("设计来源已变化，原连接段草稿仍保留；本次显示新检测结果，请重新核对。")
            return False
        for row, candidate in enumerate(self.candidates):
            saved = (state.get("rows") or {}).get(str(candidate.get("candidate_id")))
            if not saved:
                continue
            if saved.get("replace_existing") and candidate.get("status") in _REPLACEABLE_STATUSES:
                self._replacement_rows.add(row)
            if saved.get("manual_profile") and candidate.get("plan_alignment"):
                self._manual_rows.add(row)
            if not self._can_select(candidate, row):
                continue
            self._row_settings[row] = deepcopy(saved.get("settings") or {})
            self._enable_row(row)
            self.table.item(row, 0).setCheckState(Qt.Checked if saved.get("selected") else Qt.Unchecked)
            self.table.item(row, 6).setText(str(saved.get("diameter", "")))
            choice = self._section_choices[row]
            index = choice.findData(saved.get("section_type"))
            if index >= 0:
                choice.setCurrentIndex(index)
        self.batch_diameter.setText(str(state.get("batch_diameter", "")))
        self._unmatched_draft = deepcopy(state.get("unmatched_prior"))
        return True

    def _apply_current(self):
        row = self.table.currentRow()
        if row >= 0 and self._can_select(self.candidates[row], row):
            self._apply_rows([row])

    def apply(self):
        self._apply_rows(self.selected_rows())

    def _apply_rows(self, rows):
        from 土石方计算.services.transition_connections import apply_transition_candidates

        if not rows:
            self.status_label.setText("请勾选至少一个资料完整的连接段。")
            return
        overrides = {}
        for row in rows:
            candidate = self.candidates[row]
            try:
                overrides[candidate["candidate_id"]] = self._override_for(row)
            except ValueError as error:
                self.table.selectRow(row)
                self.status_label.setText(f"{candidate.get('name') or candidate.get('candidate_id')}：{error}。")
                return
        try:
            updated, report = apply_transition_candidates(
                self.inputs, [self.candidates[row]["candidate_id"] for row in rows],
                confirmed=True, overrides=overrides)
        except (ValueError, TypeError, KeyError) as exc:
            self.status_label.setText("连接段未应用：" + str(exc))
            return
        self.report = report
        if not report.get("valid"):
            failures = report.get("failures") or []
            self.status_label.setText("连接段未应用：" + "；".join(str(item.get("message") or item) for item in failures))
            return
        self.updated_inputs = updated
        self._applied_rows.update(rows)
        self.accept()
