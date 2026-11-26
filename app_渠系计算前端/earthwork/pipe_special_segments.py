"""Focused construction editor for pressure pipes and inverted siphons."""
from __future__ import annotations

from copy import deepcopy
import math
import re

from PySide6.QtCore import QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from 土石方计算.services.batch_cover_profiles import is_pressure_cover_asset
from 土石方计算.services.pipe_special_segments import (
    is_special_pipe_object, positioned_length, positioned_pipe_ranges, positioned_pipe_spans, save_pipe_segment,
    save_positioned_pipe_spans, segment_records,
)
from 土石方计算.services.design_profiles import PIPE_AXIS_CONTROLS
from 土石方计算.services.replacement_geometry import SLOPE
from 土石方计算.services.section_scheme_bindings import (
    _digest, _get, _root, _route, draft_section_scheme_fields, format_station, parse_station,
)
from 土石方计算.services.section_scheme_catalog import load_section_schemes
from 土石方计算.services.special_pipe_materials import (
    archive_invalid_material_groups, draft_special_material_fields, invalid_special_material_groups, list_special_material_groups,
    is_segment_scheme, special_material_schemes,
)

from .pipe_section_comparison import PipeSectionComparison
from .pipe_special_parameter_editor import PipeSpecialParameterEditor
from .pipe_standard_drawing_details import (
    ENCASEMENT_B1_LABEL, ENCASEMENT_SIDE, displayed_pipe_parameters, shared_encasement_thickness,
)


_GENERAL_LENGTH_LABEL = "一般材料余长（沿管轴）"
_AXIS_LENGTH_HINT = "桩号沿平面线路量取，管轴长度包含沿线高差。"
_SOURCE_PATHS = {"construction." + key for key in PIPE_AXIS_CONTROLS}
_STATION_FIELDS = {"start": "起点桩号", "end": "终点桩号"}


def _blank_station_row():
    return dict.fromkeys(_STATION_FIELDS, "")


def _station_rows(draft):
    return draft.get("station_rows") or [{key: draft.get(key, "") for key in _STATION_FIELDS}]


def _scope_values(draft):
    mode = draft["mode"]
    if mode != "station":
        return [str(draft.get(mode, "")).strip()]
    values = ([str(row[key]).strip() for key in _STATION_FIELDS] for row in _station_rows(draft))
    return [value for pair in values if any(pair) for value in pair]


def _text(value):
    return "" if value is None else f"{value:.3f}".rstrip("0").rstrip(".")


def _percent_text(value):
    if value is None:
        return "—"
    return "<0.001%" if 0 < value < .001 else f"{_text(value)}%"


def _scheme_title(scheme):
    from .drawing_material_details import drawing_option_title
    title = drawing_option_title(scheme)
    match = re.match(r"([A-Z]+型|\d+[—－-]\d+剖面)", scheme.get("source_title") or "")
    return f"{match[1]} · {title}" if match and match[1] not in title else title


def _button(text, handler):
    button = QPushButton(text)
    button.clicked.connect(handler)
    return button


def _parameter_label(path):
    from .segment_parameter_dialog import parameter_label
    return parameter_label(path)


def segment_numeric_paths(source, defaults, required, overrides):
    return {path for path in (required | set(defaults) | set(overrides)) - _SOURCE_PATHS
            if path.startswith("construction.") and
            (_get(source, path) is None or type(_get(source, path)) in (int, float))
            and not path.endswith(("_confirmed", ".floor_steps"))}


def _label(text=""):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.PlainText)
    label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
    return label


class _FormStack(QStackedWidget):
    def sizeHint(self):
        return self.currentWidget().sizeHint() if self.currentWidget() else super().sizeHint()

    def minimumSizeHint(self):
        return self.currentWidget().minimumSizeHint() if self.currentWidget() else super().minimumSizeHint()


class PipeSpecialSegmentsWidget(QWidget):
    inputs_applied = Signal(object)
    source_requested = Signal(str, str)
    back_requested = Signal()
    draft_changed = Signal()

    def __init__(self, parent=None, *, before_commit=None):
        super().__init__(parent)
        self._inputs, self._drafts = {}, {}
        self._identity = None
        self._draft_owner = None
        self._member_identities = ()
        self._groups, self._records, self._visible = [], [], []
        self.invalidate_material_groups()
        self._catalog = None
        self._prefix = "K"
        self._loading = False
        self._route_level = False
        self._before_commit = before_commit
        self._inline_editor = None
        self._make_ui()

    def _make_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0,0,0,0)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)
        canvas = QWidget()
        canvas.setObjectName("pipeSegmentCanvas")
        canvas.setStyleSheet("#pipeSegmentCanvas{background:#FFFFFF;}")
        self.scroll.setWidget(canvas)
        content = QVBoxLayout(canvas)
        content.setContentsMargins(8,3,8,8)
        self.card = QFrame()
        self.card.setObjectName("pipeSegmentCard")
        self.card.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Maximum)
        self.setStyleSheet("""
            #pipeSegmentCard {background:#FFFFFF;border:1px solid #DDE3EB;border-radius:6px;}
            #pipeSegmentCard QLabel {background:transparent;color:#213A51;}
            #pipeSegmentCard QComboBox,#pipeSegmentCard QLineEdit {
                min-height:30px;padding:0 8px;border:1px solid #B9C9D8;border-radius:5px;background:white;}
            #pipeSegmentCard QComboBox:disabled,#pipeSegmentCard QLineEdit:disabled {
                color:#53687C;background:#F7FAFD;}
            #pipeSegmentCard QPushButton,#pipeSegmentActions QPushButton {
                min-height:30px;padding:0 12px;border:1px solid #BDCDDB;border-radius:5px;background:#F8FAFC;color:#24405B;}
            #pipeSegmentCard QPushButton:hover,#pipeSegmentActions QPushButton:hover {background:#EAF2FA;}
            #pipeSegmentCard QPushButton:checked,#pipeSegmentCard QPushButton[primary="true"],
            #pipeSegmentActions QPushButton[primary="true"] {
                background:#3346A2;color:white;border-color:#3346A2;}
            #pipeSegmentActions QPushButton[primary="true"]:disabled {
                background:#EDF0F4;color:#8B96A5;border-color:#DCE2E9;}
            #pipeSegmentCard QPushButton:disabled {color:#7990A4;}
            #pipeSegmentRecords {
                border:0;background:white;selection-background-color:#E8F1FC;selection-color:#193A58;}
            #pipeSegmentRecords QHeaderView::section {
                border:0;border-bottom:1px solid #DDE6EE;background:#F4F7FA;
                color:#4E6579;font-weight:600;padding:5px 8px;}
            #pipeSegmentRecords::item {padding:0 8px;}
        """)
        content.addWidget(self.card)
        content.addStretch()
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(18,14,18,14)
        layout.setSpacing(12)
        head = QHBoxLayout()
        self.heading = _label("特殊施工段")
        self.heading.setStyleSheet("font-size:18px;font-weight:600;color:#1B3B60;")
        head.addWidget(self.heading, 1)
        self.source_button = _button("纵断面来源", self._open_source)
        self.source_button.setToolTip("定位当前对象的纵断面来源。")
        head.addWidget(self.source_button)
        self.add_button = _button("添加", self.open_add)
        self.add_button.setAccessibleName("添加特殊施工段")
        self.add_button.setProperty("primary",True)
        head.addWidget(self.add_button)
        layout.addLayout(head)
        self.spec = QComboBox()
        self.spec.setAccessibleName("施工规格")
        self.spec.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.spec.currentIndexChanged.connect(self._select_spec)
        self.notice = _label()
        self.notice.setStyleSheet("color:#94520F;")
        layout.addWidget(self.notice)
        self.archive = _button("归档失配的历史材料设置", self._archive)
        layout.addWidget(self.archive, 0, Qt.AlignLeft)
        self.archive.hide()
        self.pages = _FormStack()
        self.pages.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.pages.currentChanged.connect(self.pages.updateGeometry)
        layout.addWidget(self.pages)
        listing = QWidget()
        box = QVBoxLayout(listing)
        box.setContentsMargins(0, 0, 0, 0)
        self.general = _label()
        box.addWidget(self.general)
        self.scheme_totals = _label()
        self.scheme_totals.hide()
        box.addWidget(self.scheme_totals)
        self.table = QTableWidget(0, 4)
        self.table.setObjectName("pipeSegmentRecords")
        self.table.setAccessibleName("特殊施工段列表")
        self.table.setToolTip("双击一行可修改。")
        self.table.setHorizontalHeaderLabels(["施工做法", "设置方式及范围", "管轴长度（m）", "占全线"])
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeaderItem(2).setToolTip(_AXIS_LENGTH_HINT)
        self.table.horizontalHeaderItem(2).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.horizontalHeaderItem(3).setToolTip("本条实际管轴长度占整条管轴长度的比例。")
        self.table.horizontalHeaderItem(3).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.setColumnHidden(3, True)
        self.table.cellDoubleClicked.connect(lambda *_: self._edit())
        self.table.itemSelectionChanged.connect(self._selection)
        box.addWidget(self.table)
        bar = QHBoxLayout()
        bar.addStretch()
        self.edit_button = _button("编辑", self._edit)
        self.edit_button.setAccessibleName("编辑所选特殊施工段")
        self.remove_button = _button("移除", self._remove)
        self.remove_button.setAccessibleName("移除所选特殊施工段")
        bar.addWidget(self.edit_button)
        bar.addWidget(self.remove_button)
        box.addLayout(bar)
        self.pages.addWidget(listing)

        editor = QWidget()
        form_box = QVBoxLayout(editor)
        form_box.setContentsMargins(0, 0, 0, 0)
        form_box.setSpacing(8)
        self.general_context = _label()
        form_box.addWidget(self.general_context)
        form_box.addWidget(_label("特殊段施工做法"))
        self.schemes = QComboBox()
        self.schemes.setAccessibleName("施工做法")
        self.schemes.currentIndexChanged.connect(self._scheme_changed)
        form_box.addWidget(self.schemes)
        self.parameter_summary = _label()
        self.parameter_summary.setStyleSheet("color:#435F77;")
        form_box.addWidget(self.parameter_summary)
        self.comparison = PipeSectionComparison()
        self.comparison.setMinimumHeight(270)
        self.comparison.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.comparison.model.parameterRequested.connect(self._focus_comparison_parameter)
        self.comparison.model_enlargement_requested.connect(self._open_model_editor)
        previews = QHBoxLayout()
        previews.setSpacing(12)
        previews.addWidget(self.comparison, 1)
        self.parameter_host = QWidget()
        self.parameter_form = QVBoxLayout(self.parameter_host)
        self.parameter_form.setContentsMargins(0, 0, 0, 0)
        self.parameter_host.hide()
        previews.addWidget(self.parameter_host, 0, Qt.AlignTop)
        form_box.addLayout(previews)
        modes = QHBoxLayout()
        group = QButtonGroup(self)
        self.modes = {}
        for mode, text in (("station", "起止桩号"), ("length", "总长度"), ("ratio", "占比")):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setStyleSheet("""
                QPushButton:checked {background:#1965A7;color:white;}
                QPushButton:disabled {background:#EDF0F4;color:#8B96A5;border-color:#DCE2E9;}
            """)
            button.clicked.connect(lambda _, m=mode: self._choose_mode(m))
            group.addButton(button)
            modes.addWidget(button)
            self.modes[mode] = button
        modes.addStretch()
        form_box.addLayout(modes)
        scope_choice = QHBoxLayout()
        self.spec_label = _label("施工规格")
        self.spec_label.setBuddy(self.spec)
        scope_choice.addWidget(self.spec_label)
        scope_choice.addWidget(self.spec, 1)
        form_box.addLayout(scope_choice)
        self.scope_inputs = _FormStack()
        self.scope_inputs.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        self.edits, self.scope_labels = {}, {}
        self._make_station_inputs()
        for key, name in (("length", "特殊段总长度（m）"), ("ratio", "占当前对象整条管轴的比例（%）")):
            page = QWidget()
            field = QVBoxLayout(page)
            field.setContentsMargins(0, 0, 0, 0)
            field.setSpacing(4)
            label = _label(name)
            edit = QLineEdit()
            label.setBuddy(edit)
            edit.setAccessibleName(name)
            edit.textChanged.connect(lambda text, k=key: self._set_value(k, text))
            self.edits[key] = edit
            self.scope_labels[key] = label
            field.addWidget(label)
            field.addWidget(edit)
            self.scope_inputs.addWidget(page)
        form_box.addWidget(self.scope_inputs)
        self.summary = _label()
        self.summary.setObjectName("pipeSegmentScopeSummary")
        self.summary.setAccessibleName("特殊段范围预览")
        self.summary.setToolTip(_AXIS_LENGTH_HINT)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary.hide()
        form_box.addWidget(self.summary)
        self.error = _label()
        self.error.setStyleSheet("color:#A03E25;")
        self.error.hide()
        form_box.addWidget(self.error)
        self.editor_actions = QWidget()
        self.editor_actions.setObjectName("pipeSegmentActions")
        controls = QHBoxLayout(self.editor_actions)
        controls.setContentsMargins(8, 0, 8, 7)
        controls.addStretch()
        self.cancel_button = _button("取消", self.cancel)
        self.save_button = _button("保存特殊段", self.save)
        self.save_button.setProperty("primary",True)
        controls.addWidget(self.cancel_button)
        controls.addWidget(self.save_button)
        outer.addWidget(self.editor_actions)
        self.editor_actions.hide()
        self.pages.addWidget(editor)
        self.pages.currentChanged.connect(self._update_page_visibility)
        self._update_page_visibility(self.pages.currentIndex())

    def _make_station_inputs(self):
        page = QWidget()
        form = QVBoxLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.addWidget(_label("请填写明挖桩号。遇定向钻、顶管等非开挖区段时，分行填写两侧的明挖范围。"))
        self.station_grid = QGridLayout()
        self.station_grid.setColumnStretch(1, 1)
        self.station_grid.setColumnStretch(2, 1)
        self.station_grid.setVerticalSpacing(4)
        self.station_edits = []
        self.station_remove_buttons = []
        for column, (key, name) in enumerate(_STATION_FIELDS.items(), 1):
            label = _label(name)
            self.scope_labels[key] = label
            self.station_grid.addWidget(label, 0, column)
        self._append_station_inputs()
        self.edits.update(self.station_edits[0])
        for key, edit in self.station_edits[0].items():
            self.scope_labels[key].setBuddy(edit)
        form.addLayout(self.station_grid)
        self.add_station_row_button = _button("添加一行", self._add_station_row)
        form.addWidget(self.add_station_row_button, 0, Qt.AlignLeft)
        self.scope_inputs.addWidget(page)

    def _append_station_inputs(self):
        index = len(self.station_edits)
        row = index + 1
        self.station_grid.addWidget(_label(str(row)), row, 0)
        edits = {}
        for column, (key, name) in enumerate(_STATION_FIELDS.items(), 1):
            edit = QLineEdit()
            edit.setAccessibleName(f"第 {row} 行{name}")
            edit.setToolTip(_AXIS_LENGTH_HINT)
            edit.textChanged.connect(lambda text, k=key: self._set_station_value(index, k, text))
            self.station_grid.addWidget(edit, row, column)
            edits[key] = edit
        self.station_edits.append(edits)
        remove = _button("删除", lambda: self._remove_station_row(index))
        remove.setAccessibleName(f"删除第 {row} 行桩号")
        self.station_grid.addWidget(remove, row, 3)
        self.station_remove_buttons.append(remove)
        if index:
            self.setTabOrder(self.station_remove_buttons[index - 1], edits["start"])
            self.setTabOrder(remove, self.add_station_row_button)

    def _sync_station_inputs(self, rows):
        while len(self.station_edits) < len(rows):
            self._append_station_inputs()
        while len(self.station_edits) > len(rows):
            row = len(self.station_edits)
            for column in range(4):
                widget = self.station_grid.itemAtPosition(row, column).widget()
                self.station_grid.removeWidget(widget)
                widget.hide()
                widget.deleteLater()
            self.station_edits.pop()
            self.station_remove_buttons.pop()
        part = self._group()["parts"][0]
        for row, edits in zip(rows, self.station_edits):
            for (key, edit), fraction in zip(edits.items(), (0.1, 0.3)):
                if edit.text() != row[key]:
                    with QSignalBlocker(edit):
                        edit.setText(row[key])
                station = part["station_start"] + fraction * (part["station_end"] - part["station_start"])
                edit.setPlaceholderText("如 " + format_station(station, self._prefix))
        self.scope_inputs.updateGeometry()

    def _update_page_visibility(self, index):
        editing = index == 1
        self.add_button.setVisible(not editing)
        self.editor_actions.setVisible(editing)
        self.source_button.setVisible(bool(self._source_target()))
        show_scope = editing and self.spec.count() > 1 and (self._draft() or {}).get("mode") != "station"
        self.spec_label.setVisible(show_scope)
        self.spec.setVisible(show_scope)

    def _group(self):
        selected = self.spec.currentData()
        return next((group for group in self._groups if group["group_id"] == selected), None)

    def _mode_groups(self, mode):
        if mode == "station":
            return [group for group in self._groups if not group.get("source_groups")]
        covered = {identity for group in self._groups for identity in group.get("source_groups", ())}
        return [group for group in self._groups if group["group_id"] not in covered]

    def _fill_scope_options(self, mode, wanted, *, hint=None):
        choices = self._mode_groups(mode)
        with QSignalBlocker(self.spec):
            self.spec.clear()
            for group in choices:
                section = group["general_asset"].get("section", {})
                diameter = section.get("outer_diameter", section.get("inner_diameter"))
                label = self._range_text(group)
                if diameter:
                    label = f"φ{_text(diameter)} m　{label}"
                self.spec.addItem(label, group["group_id"])
            index = self.spec.findData(wanted)
            if index < 0 and hint:
                matches = [i for i, group in enumerate(choices) if self._spec_hint(group) == hint]
                if len(matches) == 1:
                    index = matches[0]
            self.spec.setCurrentIndex(max(0, index))
        return index

    def _draft(self):
        return self._drafts.get(self._draft_owner)

    @staticmethod
    def _edit_signature(draft):
        return _digest([draft["mode"], draft.get("scheme"), draft.get("overrides", {}), _scope_values(draft)])

    def first_unapplied_edit(self):
        if self._inline_editor is not None and self._inline_editor.has_changes():
            return self._draft_owner
        networks = self._inputs.get("networks")
        current = {(_route(network),_root(part)) for network in networks for part in network.get("assets",[])
                   if is_special_pipe_object(part) and part.get("enabled",True)} if networks is not None else None
        for identity,draft in self._drafts.items():
            if current is not None and identity not in current:
                continue
            if draft.get("editing"):
                if draft.get("original_edit") and self._edit_signature(draft)!=draft["original_edit"]:
                    return identity
            elif draft.get("overrides") or any(_scope_values(draft)):
                return identity
        return None

    def export_drafts(self):
        return [dict(route_id=k[0], asset_id=k[1], draft=deepcopy(v)) for k,v in self._drafts.items()]

    def reset_context(self):
        self.invalidate_material_groups()
        self._close_inline_editor()
        self._drafts.clear()
        self._identity = self._draft_owner = None
        self._member_identities = ()
        self._route_level = False
        self._inputs = {}
        self._groups, self._records, self._visible = [], [], []
        self._loading = True
        self.spec.clear()
        self.schemes.clear()
        self._loading = False
        self.notice.clear()
        self.notice.hide()
        self.archive.hide()
        self._list()

    def restore_drafts(self, state):
        if state == {}:
            state = []
        if isinstance(state, list):
            self._close_inline_editor()
            self._drafts = {(s["route_id"], s["asset_id"]): deepcopy(s["draft"]) for s in state
                if isinstance(s, dict) and isinstance(s.get("route_id"), str) and isinstance(s.get("asset_id"), str)
                and isinstance(s.get("draft"), dict) and s["draft"].get("mode") in self.modes}
            if self._identity:
                self.set_context(self._inputs, *self._identity, member_identities=self._member_identities,
                                 route_level=self._route_level)

    def invalidate_material_groups(self):
        self._material_group_context = None

    def set_context(self, inputs, route_id, asset_id, *, member_identities=None, route_level=False):
        if not self.finish_inline_edit():
            return False
        route_id, asset_id = str(route_id), str(asset_id)
        self._inputs = inputs
        network = next((n for n in inputs.get("networks", []) if _route(n) == route_id), {})
        asset = next((a for a in network.get("assets", []) if str(a.get("asset_id")) == asset_id), {})
        self._identity = (route_id, _root(asset) or asset_id)
        self._member_identities = tuple(dict.fromkeys((self._identity, *(member_identities or ()))))
        self._route_level = route_level
        self._draft_owner = next((key for key in self._member_identities if key in self._drafts), self._identity)
        self._prefix = network.get("station_prefix") or "K"
        self._loading = True
        self.notice.clear()
        self._groups = []
        try:
            cached = self._material_group_context
            if cached is None or cached[0] is not inputs:
                groups = list_special_material_groups(inputs, include_pipe_scopes=True)
                special_groups = [group for group in groups
                                  if any(is_special_pipe_object(part) for part in group["parts"])]
                stale_records = (invalid_special_material_groups(inputs)
                                 if inputs.get("special_pipe_materials") else ())
                stale_members = {(record["route_id"], record["asset_id"]) for record in stale_records}
                cached = self._material_group_context = (inputs, special_groups, stale_members)
            _, groups, stale_members = cached
            self._groups = [group for group in groups
                            if (group["route_id"], group["asset_id"]) in self._member_identities]
            stale = not stale_members.isdisjoint(self._member_identities)
            if stale:
                self.notice.setText("本对象有旧材料记录的规格已变化，可归档后按当前规格填写。")
            self.archive.setVisible(stale)
        except (ValueError, KeyError, TypeError) as exc:
            self.notice.setText(str(exc))
            self.archive.hide()
        prior = self.spec.currentData()
        draft = self._draft()
        wanted = draft.get("group") if draft else prior
        mode = draft.get("mode") if draft else "station"
        index = self._fill_scope_options(mode, wanted, hint=(draft or {}).get("spec_hint"))
        self.notice.setVisible(bool(self.notice.text()))
        self._loading = False
        if self._groups and draft and (index >= 0 or not draft.get("editing")
                                        and (self.spec.count() == 1 or mode == "station")):
            if draft.get("editing"):
                draft.setdefault("editing_group", draft["group"])
            if draft.get("mode") != "station":
                draft["group"] = self._group()["group_id"]
            self._editor()
        else:
            self._list()
            if self._groups and draft:
                self.notice.setText("草稿原规格已变化。选择当前规格后可继续填写。")
                self.notice.show()
        self._update_page_visibility(self.pages.currentIndex())
        return True

    def _spec_hint(self, group):
        # A working-space edit changes the material-group hash. The same pipe
        # dimensions and station intervals identify its draft after this edit.
        return _digest([group["specification"]["section"], self._range_text(group)])

    def _range_text(self, group):
        if group.get("source_groups"):
            start = group["parts"][0]["station_start"]
            end = max(part["station_end"] for part in group["parts"])
            return f"{format_station(start, self._prefix)} ～ {format_station(end, self._prefix)}"
        intervals = []
        for part in group["parts"]:
            a,b = part["station_start"],part["station_end"]
            if intervals and abs(intervals[-1][1]-a) < 1e-8:
                intervals[-1][1] = b
            else:
                intervals.append([a,b])
        return "、".join(f"{format_station(a,self._prefix)} ～ {format_station(b,self._prefix)}" for a,b in intervals)

    def _station_scope(self):
        draft = self._draft()
        ranges = [(row["start"], row["end"]) for row in _station_rows(draft)]
        return positioned_pipe_ranges(self._inputs, self._mode_groups("station"), ranges, prefix=self._prefix,
                                      editing=draft.get("editing"), editing_group=draft.get("editing_group"))

    def _station_reference(self):
        for row in _station_rows(self._draft()):
            try:
                return parse_station(row["start"], prefix=self._prefix), row["end"]
            except ValueError:
                continue
        return None, ""

    def _positioned_group(self):
        draft = self._draft()
        if draft["mode"] != "station":
            return self._group()
        start, end_text = self._station_reference()
        if start is None:
            return self._group()
        groups = self._mode_groups("station")
        try:
            end = parse_station(end_text, prefix=self._prefix)
            spans, _ = positioned_pipe_spans(self._inputs, groups, start, end, prefix=self._prefix,
                                             allow_trenchless=False)
            return spans[0].group
        except ValueError:
            if draft.get("overrides"):
                return self._group()
        matches = [group for group in groups
                   if any(part["station_start"] <= start < part["station_end"] for part in group["parts"])]
        return matches[0] if len(matches) == 1 else self._group()

    def _select_positioned_group(self):
        group = self._positioned_group()
        draft = self._draft()
        group_id = group["group_id"]
        previous_id = draft.get("group")
        previous = next((item for item in self._groups if item["group_id"] == previous_id), None)
        signature = _digest([group["section_type"], group["specification"]["section"]])
        previous_signature = (
            _digest([previous["section_type"], previous["specification"]["section"]])
            if previous else draft.get("section_signature")
        )
        matches = (previous_signature == signature if previous_signature
                   else draft.get("spec_hint") in (None, self._spec_hint(group)))
        if not matches:
            saved = draft.setdefault("overrides_by_group", {})
            if previous_id:
                saved[previous_id] = draft["overrides"]
            draft["overrides"] = saved.get(group_id, {})
        with QSignalBlocker(self.spec):
            self.spec.setCurrentIndex(self.spec.findData(group_id))
        draft.update(group=group_id, section_signature=signature)
        return group

    def _select_spec(self, *_):
        if self._loading:
            return
        if self.pages.currentIndex() == 1 and self._draft() and not self._draft().get("editing"):
            draft = self._draft()
            index = self.spec.currentIndex()
            with QSignalBlocker(self.spec):
                self.spec.setCurrentIndex(self.spec.findData(draft["group"]))
                if not self.finish_inline_edit():
                    return
                self.spec.setCurrentIndex(index)
            self._draft().update(group=self._group()["group_id"], overrides={})
            self._editor()
            self.draft_changed.emit()
        else:
            self._list()

    def _list(self):
        self._close_inline_editor()
        self._fill_scope_options("station", self.spec.currentData())
        group = self._group()
        self.pages.setCurrentIndex(0)
        self.heading.setText("特殊施工段")
        self.spec.setEnabled(True)
        self.add_button.setEnabled(bool(group))
        self._records = [dict(record, group_id=scope["group_id"])
                         for scope in self._groups for record in segment_records(scope)]
        if self._route_level:
            self._update_route_overview()
        else:
            self.scheme_totals.hide()
        self.table.setColumnHidden(3, not self._route_level)
        self.table.setRowCount(len(self._records))
        self.table.setVisible(bool(self._records))
        self.table.setFixedHeight(self.table.horizontalHeader().sizeHint().height() +
                                  self.table.verticalHeader().defaultSectionSize()*min(6,len(self._records))+6)
        for i, r in enumerate(self._records):
            scope_hint = ""
            if r["mode"] == "station":
                scope = f"{format_station(r['start'], self._prefix)} ～ {format_station(r['end'], self._prefix)}"
                if r["soil_only"]:
                    scope += " · 原土方断面"
            else:
                source = next(group for group in self._groups if group["group_id"] == r["group_id"])
                if self._route_level:
                    scope = ("按占比" if r["mode"] == "ratio" else "按总长度") + " · 位置待定"
                    scope_hint = self._range_text(source)
                else:
                    ratio_basis = ("占全长" if source.get("source_groups") or len(self._member_identities) == 1
                                   else "占管段轴长")
                    scope = (f"{ratio_basis} {_text(r['percent'])}%" if r["mode"] == "ratio"
                             else "按总长度") + " · 位置待定"
                    if len(self._mode_groups("length")) > 1:
                        scope = self._range_text(source) + " · " + scope
            for j, text in enumerate((_scheme_title(r["scheme"]), scope, _text(r["length"]) or "待补纵断面",
                                      _percent_text(r.get("whole_pipe_percent")))):
                item = QTableWidgetItem(text)
                if j in (2, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                elif j == 1 and scope_hint:
                    item.setToolTip(f"材料适用范围 {scope_hint}")
                self.table.setItem(i, j, item)
        if group and not self._route_level:
            guide = self._general_section_text(group["general_asset"]) + "。仅在局部做法有变化时添加特殊施工段。"
            if group["object_axis_length_m"] is not None:
                guide += f"　{_GENERAL_LENGTH_LABEL} {_text(self._remaining())} m"
            self.general.setText(guide)
        elif not self._route_level:
            self.general.setText("当前对象没有可设置的埋管区段。")
        self._selection()

    def _update_route_overview(self):
        from 土石方计算.services.pipe_special_route_overview import pipe_special_route_overview

        overview = pipe_special_route_overview(
            self._inputs, self._member_identities, self._records, material_groups=self._groups)
        total = overview["axis_length_m"]
        axis = f"整条管轴 {_text(total)} m" if total is not None else "整条管轴长度待补"
        if overview["axis_basis"] == "plan_chainage_in_trenchless":
            axis += "（部分非开挖段按平面桩长）"
        self.general.setText(axis if self._records else f"{axis}　·　暂无特殊施工段")
        for record, percent in zip(self._records, overview["record_percentages"], strict=True):
            record["whole_pipe_percent"] = percent
        subtotals = []
        for row in overview["schemes"]:
            title = _scheme_title(row["scheme"])
            type_code = title.split(" · ", 1)[0]
            if type_code.endswith("型"):
                title = type_code
            value = (_percent_text(row["percent"]) if row["percent"] is not None
                     else f"{_text(row['length_m'])} m" if row["length_m"] is not None else "待补纵断面")
            subtotals.append(f"{title} {value}")
        label = "材料合计" if overview["has_soil_only_records"] else "特殊段合计"
        percent = overview["special_percent"]
        if percent is not None and len(subtotals) > 1:
            subtotals.append(f"{label} {_percent_text(percent)}")
        self.scheme_totals.setText("　·　".join(subtotals))
        self.scheme_totals.setVisible(bool(subtotals))

    @staticmethod
    def _general_section_text(asset):
        binding = asset.get("section_scheme_binding") or {}
        scheme = binding.get("scheme_snapshot") or {}
        if scheme:
            return "一般段默认采用 " + _scheme_title(scheme)
        return "一般段沿用当前施工断面"

    def _selection(self):
        for button in (self.edit_button, self.remove_button):
            button.setVisible(bool(self._records))
            button.setEnabled(bool(self.table.selectedItems()))

    def _source_target(self):
        group = self._group()
        if not group:
            return None
        parts = group["parts"]
        draft = self._draft() or {}
        part = parts[0]
        if draft.get("mode") == "station":
            start, _ = self._station_reference()
            if start is not None:
                part = next((item for item in parts if start < item["station_end"]), part)
        if is_pressure_cover_asset(part):
            return group["route_id"], part["asset_id"]
        return None

    def _open_source(self):
        if self.finish_inline_edit() and (target := self._source_target()):
            self.source_requested.emit(*target)

    def _archive(self):
        result = self._inputs
        stale = {(record["route_id"], record["asset_id"]) for record in invalid_special_material_groups(result)}
        for identity in self._member_identities:
            if identity in stale:
                result = archive_invalid_material_groups(result, *identity)
        self.inputs_applied.emit(result)

    def open_add(self):
        if not self._group():
            return
        draft = self._draft()
        if not draft:
            self._drafts[self._draft_owner] = {"group": self._group()["group_id"], "mode":"station",
                "scheme":"", "station_rows": [_blank_station_row()], "length":"", "ratio":"", "overrides":{}}
        else:
            self._fill_scope_options(draft["mode"], draft["group"], hint=draft.get("spec_hint"))
            if draft["mode"] != "station" and draft["group"] != self._group()["group_id"]:
                draft.update(group=self._group()["group_id"], editing=None, overrides={})
        self._editor()
        self.draft_changed.emit()

    def _edit(self):
        row = self.table.currentRow()
        if row < 0:
            return
        r = self._records[row]
        percent = r.get("percent")
        local_ratio = self._route_level and r["mode"] == "ratio" and r.get("percent_basis") != "whole_pipe"
        if local_ratio:
            percent = r.get("whole_pipe_percent")
        ratio_text = format(percent, ".16g") if r["mode"] == "ratio" and percent is not None else ""
        self._fill_scope_options(r["mode"], r["group_id"])
        draft = {"group":r["group_id"], "editing_group":r["group_id"],
            "editing":r["key"], "mode":r["mode"],
            "scheme":r["scheme"]["scheme_id"], "overrides":deepcopy(r["overrides"]),
            "length":str(r["length"]) if r["mode"]=="length" else "",
            "ratio":ratio_text}
        if r["mode"] == "station":
            draft["station_rows"] = [{key: format_station(r[key], self._prefix) for key in _STATION_FIELDS}]
        if local_ratio:
            draft["legacy_ratio"] = {"display": ratio_text, "percent": r["percent"]}
        if self._route_level:
            draft["ratio_basis"] = "whole_pipe"
        self._drafts[self._draft_owner] = draft
        self._editor()
        self.draft_changed.emit()

    def _editor(self):
        draft = self._draft()
        group = self._select_positioned_group()
        if self._catalog is None:
            self._catalog = load_section_schemes(None)
        self._records = segment_records(group)
        draft["spec_hint"] = self._spec_hint(group)
        self._loading = True
        mode = draft["mode"]
        if self._route_level and mode == "ratio" and draft.get("ratio_basis") != "whole_pipe":
            self._align_ratio_draft(draft, group)
        self.modes[mode].setChecked(True)
        self.scope_inputs.setCurrentIndex(["station","length","ratio"].index(mode))
        self.heading.setText("编辑特殊施工段" if draft.get("editing") else "添加特殊施工段")
        context = "。各行共用所选施工做法和手填参数。" if mode == "station" else "。以下设置仅应用于本特殊段。"
        self.general_context.setText(self._general_section_text(self._general_asset(group)) + context)
        self.spec.setEnabled(not draft.get("editing"))
        local = not self._route_level and len(self._member_identities) > 1 and not group.get("source_groups")
        self.scope_labels["ratio"].setText("占所选管段轴长的比例（%）" if local
                                          else "占当前对象整条管轴的比例（%）")
        self.edits["ratio"].setAccessibleName(self.scope_labels["ratio"].text())
        if mode == "station":
            self._visible = [s for s in self._catalog if is_segment_scheme(group, s)]
        else:
            self._visible = special_material_schemes(group,self._catalog)
        editing_group = next((item for item in self._groups if item["group_id"] == draft.get("editing_group")), group)
        original = next((r for r in segment_records(editing_group) if r["key"] == draft.get("editing")), None)
        if original:
            saved = original["scheme"]
            if is_segment_scheme(group, saved) and (mode=="station" or special_material_schemes(group,[saved])):
                self._visible = [saved]+[s for s in self._visible if s["scheme_id"]!=saved["scheme_id"]]
        self.schemes.clear()
        self.schemes.setPlaceholderText("请选择新的施工做法")
        for s in self._visible:
            self.schemes.addItem(_scheme_title(s), s["scheme_id"])
            self.schemes.setItemData(self.schemes.count() - 1, s.get("source_title"), Qt.ToolTipRole)
        index = self.schemes.findData(draft.get("scheme"))
        if not draft.get("scheme"):
            fallback = "tzk_siphon_d" if group["section_type"]=="circular_siphon" else "tzk_pipe_d"
            index = max(0, self.schemes.findData(fallback))
        self.schemes.setCurrentIndex(index)
        if index >= 0:
            draft["scheme"] = self.schemes.currentData()
        if draft.get("editing") and "original_edit" not in draft:
            draft["original_edit"] = self._edit_signature(draft)
        for key in ("length", "ratio"):
            self.edits[key].setText(draft.get(key, ""))
        self._sync_station_inputs(_station_rows(draft))
        self._refresh_scope_modes()
        self.pages.setCurrentIndex(1)
        self.error.clear()
        self.error.hide()
        self._loading = False
        self._refresh_parameters()
        self._refresh_summary()
        self._update_page_visibility(1)

    def _align_ratio_draft(self, draft, group):
        """Show the whole-pipe equivalent of a previously typed local percentage."""
        local, total = group.get("object_axis_length_m"), group.get("whole_pipe_axis_length_m")
        if not local or not total:
            return
        try:
            percent = float(draft.get("ratio") or "")
        except (TypeError, ValueError):
            return
        if math.isfinite(percent):
            unchanged = draft.get("original_edit") == self._edit_signature(draft)
            display = format(percent * local / total, ".16g")
            if draft.get("editing") and "legacy_ratio" not in draft:
                draft["legacy_ratio"] = {"display": display, "percent": percent}
            draft["ratio"] = display
            draft["ratio_basis"] = "whole_pipe"
            if unchanged:
                draft["original_edit"] = self._edit_signature(draft)

    def _refresh_scope_modes(self):
        draft = self._draft()
        mode = draft["mode"]
        has_input = any(_scope_values(draft))
        for name, button in self.modes.items():
            button.setEnabled(name == mode or not has_input)
        if mode == "station":
            self.station_remove_buttons[0].setEnabled(len(self.station_edits) > 1 or has_input)
        editor = self._inline_editor
        if editor is not None and editor.station_mode_button is not None:
            editor.station_mode_button.setEnabled(self.modes["station"].isEnabledTo(self))

    def _choose_mode(self, mode):
        draft = self._draft()
        if mode == draft["mode"] or not self.modes[mode].isEnabledTo(self) or not self.finish_inline_edit():
            self.modes[draft["mode"]].setChecked(True)
            return False
        previous = self._group()
        wanted = draft.get("editing_group") if mode != "station" and draft.get("editing_group") else previous["group_id"]
        if mode != "station":
            matching = next((group for group in self._mode_groups(mode) if wanted in group.get("source_groups", ())), None)
            if matching:
                wanted = matching["group_id"]
        self._fill_scope_options(mode, wanted)
        draft["mode"] = mode
        self._editor()
        self.draft_changed.emit()
        return True

    def _scheme_changed(self, *_):
        if not self._loading and self._draft():
            index = self.schemes.currentIndex()
            with QSignalBlocker(self.schemes):
                self.schemes.setCurrentIndex(self.schemes.findData(self._draft().get("scheme")))
                if not self.finish_inline_edit():
                    return
                self.schemes.setCurrentIndex(index)
            self._draft().update(scheme=self.schemes.currentData(), overrides={})
            self._draft().pop("overrides_by_group", None)
            self.error.clear()
            self.error.hide()
            self._refresh_parameters()
            self.draft_changed.emit()

    def _set_value(self, key, value):
        draft = self._draft()
        if self._loading or not draft:
            return
        draft[key] = value
        if self._route_level and key == "ratio":
            draft["ratio_basis"] = "whole_pipe"
        self._refresh_scope_inputs()
        self.draft_changed.emit()

    def _set_station_value(self, index, key, value):
        if self._loading or not self._draft():
            return
        rows = list(_station_rows(self._draft()))
        rows[index] = {**rows[index], key: value}
        self._change_station_rows(rows, resize=False)

    def _add_station_row(self):
        rows = [*_station_rows(self._draft()), _blank_station_row()]
        if self._change_station_rows(rows, resize=True):
            start = self.station_edits[-1]["start"]
            start.setFocus()
            QTimer.singleShot(0, start, lambda: self.scroll.ensureWidgetVisible(self.add_station_row_button))

    def _remove_station_row(self, index):
        rows = list(_station_rows(self._draft()))
        rows.pop(index)
        if not rows:
            rows.append(_blank_station_row())
        if self._change_station_rows(rows, resize=True):
            self.station_edits[min(index, len(rows) - 1)]["start"].setFocus()

    def _change_station_rows(self, rows, *, resize):
        draft = self._draft()
        previous = _station_rows(draft)
        group = self._group()
        general = self._general_asset(group)
        draft["station_rows"] = rows
        next_group = self._positioned_group()
        if next_group is not group or self._general_asset(next_group) is not general:
            draft["station_rows"] = previous
            if not self.finish_inline_edit():
                self._sync_station_inputs(previous)
                return False
            draft["station_rows"] = rows
            self._editor()
        else:
            if resize:
                self._sync_station_inputs(rows)
            self._refresh_scope_inputs()
        for key in _STATION_FIELDS:
            draft.pop(key, None)
        self.draft_changed.emit()
        return True

    def _refresh_scope_inputs(self):
        self._refresh_scope_modes()
        self._refresh_summary()
        self.error.clear()
        self.error.hide()

    def _refresh_summary(self):
        group, d = self._group(), self._draft()
        denominator = group.get("whole_pipe_axis_length_m") if self._route_level else group["object_axis_length_m"]
        mode = d["mode"]
        length = None
        scope_valid = mode != "station"
        if mode == "station":
            summary = ""
            if any(_scope_values(d)):
                try:
                    spans, _ = self._station_scope()
                    intervals = [f"{format_station(span.start, self._prefix)} ～ "
                                 f"{format_station(span.end, self._prefix)}" for span in spans]
                    heading = "实际明挖范围"
                    if len(spans) > 1:
                        heading += f"　·　{len(spans)} 段"
                    lengths = [positioned_length(span.group, span.start, span.end) for span in spans]
                    if all(value is not None for value in lengths):
                        length = math.fsum(lengths)
                        heading += f"　·　{'合计' if len(spans) > 1 else ''}管轴长 {_text(length)} m"
                        if self._route_level and denominator:
                            heading += f"　·　占全线 {_percent_text(100 * length / denominator)}"
                    if len(spans) > 1:
                        intervals = [f"{interval}　·　{_text(metres) + ' m' if metres is not None else '管轴长待补'}"
                                     for interval, metres in zip(intervals, lengths)]
                    summary = "\n".join([heading, *intervals, "按各段施工断面与实际地形计算挖填和材料。"])
                    scope_valid = True
                except ValueError as error:
                    summary = str(error)
        else:
            multiple_members = not self._route_level and len(self._member_identities) > 1 and not group.get("source_groups")
            axis = "所选管段轴长" if multiple_members else "整条管轴"
            summary = f"{axis} {_text(denominator)} m" if denominator is not None else (
                "所选管段轴长待补" if multiple_members else "整条管轴长度待补"
            )
            if group.get("has_pending_profile_gap") and denominator is not None:
                measured = "所选管段已识别轴长" if multiple_members else "当前已识别管轴全长"
                summary = f"{measured} {_text(denominator)} m（间隔待补）"
            available = group["available_length_m"]
            basis_key = "whole_pipe_axis_basis" if self._route_level else "object_axis_basis"
            if group.get(basis_key) == "plan_chainage_in_trenchless":
                summary += "　·　非开挖按平面桩长"
            if denominator is not None and abs(available - denominator) > 1e-8:
                summary += f"　·　明挖计量轴长 {_text(available)} m"
            try:
                quantity=float(d[mode])
                length=denominator*quantity/100 if mode=="ratio" else quantity
                if length>0 and math.isfinite(length):
                    share = "占所选管段轴长" if multiple_members else "占全长"
                    summary += ("　·　折算 "+_text(length)+" m" if mode=="ratio" else
                                f"　·　{share} {_text(100*length/denominator)}%" if denominator else "")
            except (TypeError, ValueError):
                pass
            if length is not None and length > 0 and denominator is not None:
                remainder = self._remaining(d.get("editing")) - length
                if remainder >= -1e-8:
                    summary += f"　·　{_GENERAL_LENGTH_LABEL} {_text(max(0., remainder))} m"
            summary += "\n挖填沿用现有施工断面和实际地形。构造材料按长度折算。"
        background, foreground = ("#F5F8FB", "#254866") if scope_valid else ("#FFF2ED", "#A03E25")
        self.summary.setStyleSheet(f"background:{background};color:{foreground};padding:8px 11px;border-radius:4px;")
        self.summary.setText(summary)
        self.summary.setVisible(bool(summary))
        self.save_button.setEnabled(scope_valid)

    def _remaining(self, editing=None):
        group = self._group()
        available = group["available_length_m"]
        if group.get("source_groups") and not group["errors"]:
            from 土石方计算.services.special_pipe_materials import _material_pool
            available = _material_pool(group)["available_length_m"]
        return max(0., available - math.fsum(
            r["length"] or 0. for r in self._records if r["key"] != editing and not r.get("soil_only")
            and r.get("group_id", group["group_id"]) == group["group_id"]))

    def _scheme(self):
        return self._visible[self.schemes.currentIndex()] if self.schemes.currentIndex()>=0 else {}

    def _applicable_overrides(self):
        draft = self._draft()
        overrides = {path: value for path, value in draft.get("overrides", {}).items()
                     if path not in _SOURCE_PATHS and (draft["mode"] == "station" or path.startswith("construction."))}
        if not draft.get("editing") and draft.get("scheme") == "tzk_pipe_paddy":
            replacement = overrides.get("construction.foundation_replacement")
            if not isinstance(replacement, dict) or "side_slope" not in replacement:
                overrides.setdefault(SLOPE, 1)
        return overrides

    def _general_asset(self, group):
        draft = self._draft()
        general = group["general_asset"]
        if draft["mode"] == "station":
            start, _ = self._station_reference()
            if start is not None:
                general = min((p for p in group["general_parts"] if start < p["station_end"]),
                              key=lambda part: part["station_start"], default=general)
        return general

    def _parameter_context(self):
        scheme = self._scheme()
        draft = self._draft()
        general = self._general_asset(self._group())
        resolve = draft_section_scheme_fields if draft["mode"] == "station" else draft_special_material_fields
        source, defaults = resolve(general, scheme, self._applicable_overrides())
        required = set(scheme.get("required_fields", [])) | set(scheme.get("constraints", {}).get("required_fields", []))
        for variant in scheme.get("terrain_variants", {}).values():
            required.update(variant.get("required_fields", []))
            for selector in variant.get("selectors", []):
                required.update(selector.get("required_fields", []))
        for selector in scheme.get("selectors", []):
            required.update(selector.get("required_fields", []))
        if scheme.get("source_review_required"):
            required.add("section.source_review_confirmed")
        return source, defaults, required, general

    def _refresh_parameters(self, *, refresh_drawing=True):
        self._close_inline_editor()
        self._refresh_parameter_preview(refresh_drawing=refresh_drawing)
        if self._scheme():
            self._open_parameter_editor()

    def _refresh_parameter_preview(self, *, refresh_drawing):
        from 土石方计算.services.section_parameter_decisions import section_parameter_decisions, unresolved_pipe_size_field
        scheme = self._scheme()
        self._first_missing_parameter = None
        self.comparison.setVisible(bool(scheme))
        self.parameter_summary.clear()
        self.parameter_summary.setToolTip("")
        self.parameter_summary.hide()
        if not scheme:
            return
        source, defaults, _, _ = self._parameter_context()
        decisions = section_parameter_decisions(source, scheme, overrides=self._applicable_overrides(),
                                                resolved_fields=defaults)
        missing = [p for p, d in decisions.items() if d["required"] and d["missing"]]
        if refresh_drawing:
            self.comparison.set_source(scheme, self._inputs.get("input_files", []))
        self.comparison.set_model(source, scheme, missing)
        size_field = unresolved_pipe_size_field(source, scheme, decisions)
        if size_field:
            self._first_missing_parameter = size_field if self._draft()["mode"] == "station" else "section.outer_diameter"
            self.parameter_summary.setText("待补管径")
            self.parameter_summary.show()
            return
        if missing:
            display = displayed_pipe_parameters(source, scheme, missing)
            shared = shared_encasement_thickness(source, scheme)
            labels = [ENCASEMENT_B1_LABEL if shared and path == ENCASEMENT_SIDE else _parameter_label(path)
                      for path in display]
            self._first_missing_parameter = display[0]
            self.parameter_summary.setText("待填写　" + "、".join(labels[:2]) +
                                           (f" 等 {len(labels)} 项" if len(labels) > 2 else ""))
            self.parameter_summary.setToolTip("、".join(labels))
            self.parameter_summary.show()
            return
        from 土石方计算.services.section_scheme_bindings import _check_constraints
        try:
            _check_constraints(source, scheme)
        except ValueError as error:
            message = str(error)
            paths = (scheme.get("constraints") or {}).get("field_ranges", {})
            self._first_missing_parameter = next((path for path in paths if path in message), None)
            if self._first_missing_parameter:
                message = message.replace(self._first_missing_parameter, _parameter_label(self._first_missing_parameter))
            elif "收坡后底宽" in message:
                modes = source.get("replacement_parameter_modes") or {}
                width = "construction.foundation_replacement_width"
                self._first_missing_parameter = width if modes.get(width) == "manual" and modes.get(SLOPE) != "manual" else SLOPE
            self.parameter_summary.setText(message)
            self.parameter_summary.show()

    def _open_parameter_editor(self, *, enlarged=False):
        draft, scheme = self._draft(), self._scheme()
        if not scheme:
            return
        source, _, required, general = self._parameter_context()
        located = draft["mode"] == "station"
        resolve = draft_section_scheme_fields if located else draft_special_material_fields
        workbench = self.window()
        was_active = workbench.isActiveWindow()
        dialog = PipeSpecialParameterEditor(
            source, scheme, required, self._applicable_overrides(), lambda values: resolve(general, scheme, values),
            workbench if enlarged else self.parameter_host, located=located, title=_scheme_title(scheme),
            terrain_case=self.comparison.terrain_case.currentData(), view=None if enlarged else self.comparison.model,
        )
        if dialog.station_mode_button is not None:
            dialog.station_mode_button.setEnabled(self.modes["station"].isEnabledTo(self))
        dialog.finished.connect(lambda decision: self._finish_parameters(dialog, draft, decision, enlarged=enlarged))
        if enlarged:
            dialog.open()
            if self._first_missing_parameter:
                dialog.focus_parameter(self._first_missing_parameter)
        else:
            self._inline_editor = dialog
            dialog.cancel_parameters.setText("取消修改")
            self.parameter_form.addWidget(dialog)
            self.parameter_host.show()
            dialog.show()
            if was_active:
                workbench.activateWindow()

    def _focus_comparison_parameter(self, path):
        if self._inline_editor is not None:
            self._inline_editor.focus_parameter(path)

    def _open_model_editor(self):
        if self.finish_inline_edit():
            self._open_parameter_editor(enlarged=True)

    def finish_inline_edit(self):
        editor = self._inline_editor
        if editor is None or not editor.has_changes():
            return True
        editor.accept()
        if self._inline_editor is editor and not editor.message.isHidden():
            self.scroll.ensureWidgetVisible(editor.message)
        return self._inline_editor is not editor

    def _close_inline_editor(self):
        editor, self._inline_editor = self._inline_editor, None
        if editor is None:
            return
        editor.hide()
        self.parameter_form.removeWidget(editor)
        editor.deleteLater()
        self.parameter_host.hide()

    def _finish_parameters(self, dialog, opened_draft, decision, *, enlarged=False):
        if not enlarged:
            self._close_inline_editor()
        draft = self._draft()
        if draft is not opened_draft:
            return
        if decision in (QDialog.Accepted, PipeSpecialParameterEditor.EditByStation):
            overrides = {**draft.get("overrides", {}), **dialog.values}
            if overrides != draft.get("overrides", {}):
                draft["overrides"] = overrides
                self.error.clear()
                self.error.hide()
                if decision == QDialog.Accepted:
                    self.draft_changed.emit()
        if decision == PipeSpecialParameterEditor.EditByStation and self._choose_mode("station"):
            if enlarged:
                self._open_parameter_editor(enlarged=True)
            return
        self._refresh_parameters(refresh_drawing=False)

    def cancel(self):
        self._close_inline_editor()
        self._drafts.pop(self._draft_owner, None)
        self._list()
        self.draft_changed.emit()

    def _accept(self, result, *, focus_station=None):
        self._close_inline_editor()
        self._drafts.pop(self._draft_owner, None)
        self.set_context(result, *self._identity, member_identities=self._member_identities,
                         route_level=self._route_level)
        if focus_station is not None:
            for row, record in enumerate(self._records):
                if record["mode"] == "station" and record["start"] <= focus_station < record["end"]:
                    self.table.selectRow(row)
                    break
        self.inputs_applied.emit(result)
        self.draft_changed.emit()

    def _can_commit(self):
        return self.finish_inline_edit() and (self._before_commit is None or self._before_commit())

    def save(self):
        if not self._can_commit():
            return False
        draft, group, scheme = self._draft(), self._group(),self._scheme()
        try:
            if not scheme:
                raise ValueError("请选择可用于本段的施工做法")
            mode = draft["mode"]
            focus_station = None
            if mode == "station":
                spans, _ = self._station_scope()
                result = save_positioned_pipe_spans(
                    self._inputs, spans, scheme=scheme, overrides=self._applicable_overrides(),
                    editing=draft.get("editing"), editing_group=draft.get("editing_group"),
                )
                focus_station = (spans[0].start + spans[0].end) / 2
            else:
                source, editing = self._inputs, draft.get("editing")
                if editing and draft.get("editing_group") != group["group_id"]:
                    source = save_pipe_segment(source, draft["editing_group"], editing=editing, remove=True)
                    editing = None
                quantity, percent_basis = draft.get(mode), None
                if self._route_level and mode == "ratio":
                    previous = draft.get("legacy_ratio")
                    if editing and previous and quantity.strip() == previous["display"]:
                        quantity = previous["percent"]
                    else:
                        percent_basis = "whole_pipe"
                result = save_pipe_segment(
                    source, group["group_id"], mode=mode, scheme=scheme, quantity=quantity,
                    overrides=self._applicable_overrides(), editing=editing, percent_basis=percent_basis,
                )
        except (ValueError, KeyError, TypeError) as exc:
            message=str(exc)
            for path in scheme.get("required_fields",[]):
                message=message.replace(path,_parameter_label(path))
            self.error.setText(message)
            self.error.show()
            self.scroll.ensureWidgetVisible(self.error)
            return False
        self._accept(result, focus_station=focus_station)
        return True

    def _remove(self):
        i=self.table.currentRow()
        if i < 0 or not self._can_commit():
            return
        try:
            record = self._records[i]
            result = save_pipe_segment(self._inputs, record["group_id"], editing=record["key"], remove=True)
        except (ValueError, KeyError, TypeError) as exc:
            self.notice.setText(str(exc))
            self.notice.show()
            return
        self._accept(result)
