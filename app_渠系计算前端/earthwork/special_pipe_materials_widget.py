"""Explicit, isolated length/station choices for continuous pipe materials."""
from __future__ import annotations

from copy import deepcopy
import json
import math
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)


_NAMES = {
    "outer_diameter": "施工外径", "working_space_left": "左工作面", "working_space_right": "右工作面",
    "base_thickness": "管座底厚", "extension": "管座外伸", "support_angle": "管座包角（°）",
    "side_thickness": "侧面包封厚度", "bottom_thickness": "底部包封厚度", "top_thickness": "顶部包封厚度",
    "foundation_replacement_thickness": "石渣换填厚度", "foundation_replacement_width": "石渣换填上宽",
    "side_slope": "换填收坡 1:m", "width": "换填宽度", "thickness": "换填厚度",
    "bedding_thickness": "垫层厚度", "bedding_extension": "垫层外伸", "bottom_width": "管座底宽",
}


def _label(path):
    key = path.rsplit(".", 1)[-1]
    text = _NAMES.get(key, key)
    return text if "坡" in text or "°" in text else text + "（m）"


class SpecialPipeMaterialsWidget(QWidget):
    """Drafts stay here; only a successful explicit apply emits new inputs."""

    inputs_applied = Signal(object)
    draft_changed = Signal()
    view_mode_changed = Signal(str)
    soil_preview_requested = Signal()

    def __init__(self, parent=None, *, library_root=None):
        super().__init__(parent)
        self.library_root = Path(library_root) if library_root else None
        self._inputs = {}
        self._groups = []
        self._schemes = []
        self._drafts = {}
        self._adopted_states = {}
        self._baseline = None
        self._building = False
        self._active_id = None
        self._rows = []
        self._invalid_configurations = []
        self._preserve_next_adoption = False
        self._apply_notice = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)
        head = QHBoxLayout()
        title = QLabel("特殊管段材料设置")
        self.title_label = title
        title.setStyleSheet("font-size:15px;font-weight:600;")
        head.addWidget(title)
        self.group_choice = QComboBox()
        self.group_choice.setMinimumContentsLength(18)
        head.addWidget(self.group_choice, 1)
        root.addLayout(head)
        modes = QHBoxLayout()
        self.length_button = QPushButton("按长度填写（推荐）")
        self.station_button = QPushButton("按起止桩号填写")
        self.mode_buttons = QButtonGroup(self)
        self.mode_buttons.setExclusive(True)
        for key, button in (("length", self.length_button), ("station", self.station_button)):
            button.setCheckable(True)
            button.setProperty("material_mode", key)
            button.setMinimumHeight(32)
            button.setStyleSheet("QPushButton:checked{background:#1965A7;color:white;font-weight:600;border:2px solid #114F8B;} QPushButton{border:1px solid #8BA4BB;}")
            self.mode_buttons.addButton(button)
            modes.addWidget(button, 1)
            button.clicked.connect(lambda _, value=key: self.select_mode(value))
        root.addLayout(modes)
        self.choice_hint = QLabel("特殊管段材料按长度或按桩号，选一种即可，无需重复填写。")
        self.choice_hint.setWordWrap(True)
        root.addWidget(self.choice_hint)
        self.basis_label = QLabel()
        self.basis_label.setWordWrap(True)
        root.addWidget(self.basis_label)
        self.invalid_panel = QWidget()
        invalid_layout = QHBoxLayout(self.invalid_panel)
        invalid_layout.setContentsMargins(0,0,0,0)
        self.invalid_notice = QLabel()
        self.invalid_notice.setWordWrap(True)
        self.invalid_notice.setStyleSheet("color:#9F5715;")
        invalid_layout.addWidget(self.invalid_notice,1)
        self.archive_button = QPushButton("归档上述失效材料设置")
        self.archive_button.clicked.connect(self.archive_invalid_settings)
        invalid_layout.addWidget(self.archive_button)
        self.invalid_panel.hide()
        root.addWidget(self.invalid_panel)
        self.soil_preview_button = QPushButton("查看原土方断面…")
        self.soil_preview_button.setToolTip("查看实际桩号的原施工构造和地形，不将长度材料安排到此桩号。")
        self.soil_preview_button.clicked.connect(self.soil_preview_requested)
        root.addWidget(self.soil_preview_button, 0, Qt.AlignLeft)
        self.length_panel = QWidget()
        box = QVBoxLayout(self.length_panel)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(5)
        self.totals_label = QLabel()
        self.totals_label.setStyleSheet("font-weight:600;color:#235D46;padding:4px 0;")
        box.addWidget(self.totals_label)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["特殊类型 / 采用断面", "长度（m）", "构造参数", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 120)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setMinimumHeight(116)
        self.table.setMaximumHeight(225)
        box.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.add_button = QPushButton("＋ 添加特殊长度")
        self.remove_button = QPushButton("删除选中记录")
        self.import_button = QPushButton("从原桩号设置汇总长度")
        actions.addWidget(self.add_button)
        actions.addWidget(self.remove_button)
        actions.addWidget(self.import_button)
        actions.addStretch(1)
        box.addLayout(actions)
        self.scope_label = QLabel("只调整管座、包封、垫层和换填材料；土方沿用原依据。各行填写互不重复的净长度，不生成沿线桩号。")
        self.scope_label.setWordWrap(True)
        self.scope_label.setStyleSheet("color:#51677B;")
        box.addWidget(self.scope_label)
        root.addWidget(self.length_panel)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self.apply_button = QPushButton("应用材料设置")
        self.apply_button.setStyleSheet("background:#1965A7;color:white;font-weight:600;")
        head.addWidget(self.apply_button)
        self.group_choice.currentIndexChanged.connect(self._group_changed)
        self.add_button.clicked.connect(self.add_row)
        self.remove_button.clicked.connect(self.remove_selected_row)
        self.import_button.clicked.connect(self.import_station_rows)
        self.apply_button.clicked.connect(self.apply)

    def group(self):
        index = self.group_choice.currentIndex()
        return self._groups[index] if 0 <= index < len(self._groups) else None

    def current_mode(self):
        return "length" if self.length_button.isChecked() else "station"

    def _state(self):
        rows = []
        for row_index, source in enumerate(self._rows):
            record = deepcopy(source)
            combo = self.table.cellWidget(row_index, 0)
            edit = self.table.cellWidget(row_index, 1)
            if combo and combo.currentIndex() >= 0:
                record["scheme_id"] = combo.currentData()
                saved = record.get("scheme_snapshot")
                scheme = saved if saved and saved.get("scheme_id") == record["scheme_id"] else self._scheme(record["scheme_id"])
                if scheme:
                    record["scheme_snapshot"] = deepcopy(scheme)
            record["length_text"] = edit.text() if edit else str(record.get("length_m", ""))
            record.pop("length_m", None)
            rows.append(record)
        return {"mode": self.current_mode(), "rows": rows}

    @staticmethod
    def _draft_from_group(group):
        rows = []
        for source in group.get("rows", []):
            record = deepcopy(source)
            value = record.pop("length_m", None)
            record["length_text"] = "" if value is None else f"{float(value):g}"
            rows.append(record)
        return {"mode": group.get("mode", "length"), "rows": rows}

    def has_pending_draft(self):
        drafts = deepcopy(self._drafts)
        if self._active_id and self.group():
            drafts[self._active_id] = self._state()
        return any(self._comparable_state(state) != self._comparable_state(self._adopted_states.get(identifier))
                   for identifier, state in drafts.items())

    @staticmethod
    def _comparable_state(state):
        # Unapplied length text remains recoverable while station mode is in
        # use, but an inactive length form must not block station calculation.
        if isinstance(state,dict) and state.get("mode") == "station":
            return {"mode":"station"}
        return state

    def current_pending_draft(self):
        return bool(self.group() and self._comparable_state(self._state()) != self._comparable_state(self._baseline))

    def set_context(self, inputs, asset_identity, schemes, *, discard=False):
        if not discard and self._active_id and self.group():
            self._drafts[self._active_id] = self._state()
        if discard:
            self._drafts.clear()
        from 土石方计算.services.special_pipe_materials import list_special_material_groups
        try:
            groups = list_special_material_groups(inputs)
        except (ValueError, TypeError, KeyError) as error:
            groups = []
            self.status_label.setText("特殊材料分组待完善：" + str(error))
        self._inputs = deepcopy(inputs)
        self._schemes = deepcopy(schemes)
        self._adopted_states = {group["group_id"]: self._draft_from_group(group) for group in groups}
        from 土石方计算.services.special_pipe_materials import invalid_special_material_groups
        self._invalid_configurations = invalid_special_material_groups(inputs) if inputs.get("special_pipe_materials") else []
        self.invalid_panel.setVisible(bool(self._invalid_configurations))
        if self._invalid_configurations:
            identities = list(dict.fromkeys(str(item.get("route_id", ""))+" / "+str(item.get("asset_id", ""))
                                           for item in self._invalid_configurations))
            self.invalid_notice.setText("材料规格已变化或对象已移除：" + "、".join(identities) +
                "。旧设置不能继续计量；归档会完整保留上述失配记录，土方和其他有效材料设置不改，可撤销。")
        route, root = asset_identity or (None, None)
        self._groups = [group for group in groups if str(group.get("route_id")) == str(route)
                        and str(group.get("asset_id")) == str(root)]
        self._building = True
        previous = self._active_id
        self.group_choice.clear()
        for index, group in enumerate(self._groups):
            asset = group.get("general_asset") or next(iter(group.get("parts", [])), {})
            section = asset.get("section", {})
            diameter = section.get("outer_diameter", section.get("inner_diameter"))
            label = str(group.get("name") or root or "管道")
            if diameter is not None:
                label += (" · 外径 " if section.get("outer_diameter") is not None else " · 净内径 ") + f"{float(diameter):g}m"
            label += f" · {int(section.get('pipe_count', len(section.get('pipes', [])) or 1))}管"
            label += f" · 规格组 {index+1}"
            self.group_choice.addItem(label, group["group_id"])
            if previous == group["group_id"]:
                self.group_choice.setCurrentIndex(index)
        self._building = False
        self.setVisible(bool(self._groups or self._invalid_configurations))
        self._load_group()

    def _group_changed(self, *_):
        if self._building:
            return
        if self._active_id:
            self._drafts[self._active_id] = self._state()
        self._load_group()

    def _load_group(self):
        group = self.group()
        self._building = True
        self._active_id = group.get("group_id") if group else None
        self._baseline = self._draft_from_group(group) if group else None
        state = deepcopy(self._drafts.get(self._active_id, self._baseline)) if group else {"mode":"length", "rows":[]}
        self.length_button.setChecked(state["mode"] == "length")
        self.station_button.setChecked(state["mode"] == "station")
        self._render_rows(state.get("rows", []))
        self._building = False
        self._update_status()
        self.view_mode_changed.emit(self.current_mode())

    def _eligible_schemes(self):
        group = self.group() or {}
        if not group:
            return []
        from 土石方计算.services.special_pipe_materials import special_material_schemes
        return special_material_schemes(group, self._schemes)

    def _scheme(self, identifier):
        return next((scheme for scheme in self._schemes if scheme.get("scheme_id") == identifier), None)

    def _render_rows(self, rows):
        from .drawing_material_details import drawing_option_title
        from 土石方计算.services.special_pipe_materials import special_material_schemes
        self._rows = deepcopy(rows)
        self.table.setRowCount(len(rows))
        for index, record in enumerate(rows):
            combo = QComboBox()
            choices = self._eligible_schemes()
            saved = record.get("scheme_snapshot")
            saved_eligible = bool(saved and special_material_schemes(self.group(), [saved]))
            if saved_eligible and all(s.get("scheme_id") != saved.get("scheme_id") for s in choices):
                choices.append(saved)
            for scheme in choices:
                combo.addItem(drawing_option_title(scheme), scheme["scheme_id"])
            combo.setPlaceholderText("请选择新的施工做法")
            selected = combo.findData(record.get("scheme_id")) if not saved or saved_eligible else -1
            combo.setCurrentIndex(selected)
            combo.currentIndexChanged.connect(lambda _, i=index: self._row_scheme_changed(i))
            self.table.setCellWidget(index, 0, combo)
            edit = QLineEdit(record.get("length_text", str(record.get("length_m", ""))))
            edit.setPlaceholderText("如 30")
            edit.setReadOnly(selected < 0)
            edit.textChanged.connect(self._changed)
            self.table.setCellWidget(index, 1, edit)
            button = QPushButton("核对 / 补参数…")
            button.setEnabled(selected >= 0)
            button.clicked.connect(lambda _, i=index: self.edit_parameters(i))
            self.table.setCellWidget(index, 2, button)
            self.table.setItem(index, 3, QTableWidgetItem("待核对"))

    def _row_scheme_changed(self, index):
        if self._building:
            return
        if 0 <= index < len(self._rows):
            self.table.cellWidget(index, 1).setReadOnly(False)
            self.table.cellWidget(index, 2).setEnabled(True)
            self._rows[index]["overrides"] = {}
            for key in ("scheme_snapshot", "scheme_sha256", "scheme_title"):
                self._rows[index].pop(key, None)
        self._changed()

    def select_mode(self, mode):
        if mode not in {"length", "station"} or not self.group():
            return
        self.length_button.setChecked(mode == "length")
        self.station_button.setChecked(mode == "station")
        if (mode == "length" and not self._rows and (self.group() or {}).get("mode") == "station"
                and not (self.group() or {}).get("configured")):
            self.import_station_rows()
        self._changed()
        self.view_mode_changed.emit(mode)

    def add_row(self, *_):
        if not self.group():
            return
        schemes = self._eligible_schemes()
        if not schemes:
            self.status_label.setText("本规格组暂无可按长度计算的特殊构造断面。")
            return
        state = self._state()
        state["rows"].append({"record_id": uuid.uuid4().hex, "scheme_id": schemes[0]["scheme_id"],
                              "scheme_snapshot": deepcopy(schemes[0]), "length_text":"", "overrides":{}})
        self._building = True
        self._render_rows(state["rows"])
        self._building = False
        self._changed()
        self.table.cellWidget(self.table.rowCount()-1, 1).setFocus()

    def remove_selected_row(self):
        index = self.table.currentRow()
        if index < 0:
            return
        rows = self._state()["rows"]
        rows.pop(index)
        self._building = True
        self._render_rows(rows)
        self._building = False
        self._changed()

    def import_station_rows(self):
        group = self.group()
        if not group:
            return
        from 土石方计算.services.special_pipe_materials import summarize_station_material_rows
        try:
            rows = summarize_station_material_rows(self._inputs, group["group_id"])
            state = self._draft_from_group({"rows": rows})
        except (ValueError, TypeError, KeyError) as error:
            self.status_label.setText("未汇总：" + self._friendly(error))
            return
        self._building = True
        self._render_rows(state["rows"])
        self._building = False
        self._changed()

    def _changed(self, *_):
        if self._building:
            return
        self._update_status()
        self.draft_changed.emit()

    def _friendly(self, error):
        text = str(error)
        for root in ("section.", "construction."):
            for name in _NAMES:
                text = text.replace(root + name, _label(root + name))
        for index in range(self.table.rowCount()):
            scheme = self._scheme(self.table.cellWidget(index, 0).currentData()) or {}
            for path in scheme.get("required_fields", []):
                text = text.replace(path, _label(path))
        return text

    def _effective_parameters(self, record):
        from 土石方计算.services.special_pipe_materials import draft_special_material_fields

        general = self.group()["general_asset"]
        scheme = record.get("scheme_snapshot") or self._scheme(record.get("scheme_id")) or {}
        asset, fields = draft_special_material_fields(general, scheme, record.get("overrides") or {})
        return asset, scheme, fields

    def edit_parameters(self, row):
        from .pipe_special_segments import segment_numeric_paths
        from .segment_parameter_dialog import MaterialSegmentParameters, show_segment_drawing

        if not 0 <= row < self.table.rowCount() or self.table.cellWidget(row, 0).currentIndex() < 0:
            return
        record = self._state()["rows"][row]
        try:
            asset, scheme, defaults = self._effective_parameters(record)
        except (ValueError, KeyError, TypeError) as error:
            self.status_label.setText(self._friendly(error))
            return
        required = set(scheme.get("required_fields", [])) | set((scheme.get("constraints") or {}).get("required_fields", []))
        overrides = record.get("overrides") or {}
        paths = segment_numeric_paths(asset, defaults, required, overrides)
        dialog = MaterialSegmentParameters(asset, scheme, paths, required, overrides, self,
                                           general=self.group()["general_asset"])
        files = self._inputs.get("input_files", [])
        dialog.drawing_requested.connect(lambda: show_segment_drawing(dialog, scheme, files, library_root=self.library_root))
        decision = dialog.exec()
        if decision == MaterialSegmentParameters.EditByStation:
            self.select_mode("station")
        elif decision == QDialog.Accepted:
            self._rows[row]["overrides"] = deepcopy(dialog.values)
            self._rows[row]["scheme_snapshot"] = deepcopy(scheme)
            self._changed()

    def _numeric_rows(self):
        rows = []
        adopted = {row.get("record_id"): row for row in (self.group() or {}).get("rows", [])}
        for index, record in enumerate(self._state()["rows"], 1):
            text = record.pop("length_text", "")
            try:
                value = float(text)
            except (TypeError,ValueError):
                raise ValueError(f"第{index}条特殊长度请输入米数")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"第{index}条特殊长度须大于0")
            old = adopted.get(record.get("record_id"), {})
            if old.get("length_m") is not None:
                if value == float(f"{float(old['length_m']):g}"):
                    value = old["length_m"]
                elif "object_percent" in record:
                    record.pop("object_percent")
                    record["length_source"] = "用户填写实际管轴长度"
            record["length_m"] = value
            rows.append(record)
        return rows

    def _update_status(self):
        group = self.group()
        mode = self.current_mode()
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred if mode == "length" else QSizePolicy.Maximum)
        self.length_panel.setVisible(bool(group and mode == "length"))
        self.soil_preview_button.setVisible(bool(group and mode == "length"))
        self.apply_button.setText("应用长度材料设置" if mode == "length" else "采用桩号方式")
        for control in (self.title_label,self.group_choice,self.length_button,self.station_button,
                        self.choice_hint,self.basis_label,self.apply_button):
            control.setVisible(bool(group))
        if not group:
            self.status_label.hide()
            self.apply_button.setEnabled(False)
            return
        adopted = "按长度" if group.get("mode") == "length" else "按起止桩号"
        editing = "按长度" if mode == "length" else "按起止桩号"
        has_positioned = group.get("has_station_specials", False)
        soil = "已有桩号特殊构造＋实际地形" if has_positioned else "当前一般断面＋实际地形"
        self.basis_label.setText(f"材料当前采用：{adopted}　｜正在编辑：{editing}\n土方依据：{soil}；切换材料填写方式不改变土方依据。")
        total = float(group.get("available_length_m", 0.))
        try:
            rows = self._numeric_rows() if mode == "length" else []
            used = sum(record["length_m"] for record in rows)
            self.totals_label.setText(f"本组可用总长 {total:,.3f} m　特殊长度 {used:,.3f} m　剩余一般长度 {total-used:,.3f} m")
            if used > total + 1e-7:
                raise ValueError("特殊长度合计超过本规格组可用总长，请调整。")
            if mode == "length" and group.get("errors"):
                raise ValueError("；".join(str(error) for error in group["errors"]))
            if mode == "length":
                from 土石方计算.services.special_pipe_materials import validate_length_material_rows
                validate_length_material_rows(group, rows)
            pending = self.current_pending_draft()
            self.status_label.setText("待应用：仅调整材料，原桩号土方依据保留。" if pending else
                "当前材料设置已采用；修改后点击“" + self.apply_button.text() + "”。")
            self.status_label.setStyleSheet("color:#51677B;")
            self.status_label.setVisible(mode == "length")
            self.apply_button.setEnabled(pending)
        except (ValueError,TypeError) as error:
            self.status_label.setText(self._friendly(error))
            self.status_label.setStyleSheet("color:#AE493D;")
            self.status_label.show()
            self.apply_button.setEnabled(False)
            used = 0.
            for index in range(self.table.rowCount()):
                try:
                    used += float(self.table.cellWidget(index,1).text())
                except (ValueError, TypeError):
                    pass
            self.totals_label.setText(f"本组可用总长 {total:,.3f} m　已填特殊长度 {used:,.3f} m（待核对）")
        self.import_button.setEnabled(group.get("has_selectable_station_specials", False))
        self.add_button.setEnabled(bool(self._eligible_schemes()))
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 0).currentIndex() < 0:
                self.table.item(row, 3).setText("原做法已停用")
                continue
            record = self._state()["rows"][row]
            try:
                from 土石方计算.services.section_parameter_decisions import section_parameter_decisions
                from .segment_parameter_dialog import parameter_label
                asset, scheme, fields = self._effective_parameters(record)
                decisions = section_parameter_decisions(asset, scheme, overrides=record.get("overrides"), resolved_fields=fields)
                missing = [path for path, info in decisions.items() if info["required"] and info["missing"]]
                status = "待补 " + "、".join(parameter_label(path) for path in missing[:2]) if missing else "参数齐全"
            except (ValueError,KeyError,TypeError):
                status = "参数待核对"
            self.table.item(row, 3).setText(status)

    def apply(self):
        group = self.group()
        if not group:
            return
        from 土石方计算.services.special_pipe_materials import apply_length_materials, set_special_material_mode
        try:
            if self.current_mode() == "length":
                result = apply_length_materials(self._inputs, group["group_id"], self._numeric_rows())
            else:
                result = set_special_material_mode(self._inputs, group["group_id"], "station")
        except (ValueError,TypeError,KeyError) as error:
            self.status_label.setText("未应用：" + self._friendly(error))
            self.status_label.setStyleSheet("color:#AE493D;")
            return
        if result == self._inputs:
            self.status_label.setText("设置未改变。")
            return
        self._drafts.pop(group["group_id"], None)
        self.inputs_applied.emit(result)

    def export_draft(self):
        drafts = deepcopy(self._drafts)
        if self._active_id and self.group():
            drafts[self._active_id] = self._state()
        return json.loads(json.dumps({"group_id": self._active_id, "drafts":drafts}, ensure_ascii=False, allow_nan=False))

    def discard_drafts(self):
        self._drafts.clear()
        self._active_id = None

    def adopt_current_group(self):
        if self._active_id:
            if self._preserve_next_adoption or self.current_mode() == "station":
                self._drafts[self._active_id] = self._state()
            else:
                self._drafts.pop(self._active_id, None)
        self._active_id = None
        self._preserve_next_adoption = False

    def has_invalid_configurations(self):
        return bool(self._invalid_configurations)

    def archive_invalid_settings(self):
        if not self._invalid_configurations:
            return
        from 土石方计算.services.special_pipe_materials import archive_invalid_material_groups
        result=deepcopy(self._inputs)
        identities=list(dict.fromkeys((item.get("route_id"),item.get("asset_id"))
                                      for item in self._invalid_configurations))
        try:
            for route,root in identities:
                result=archive_invalid_material_groups(result,route,root)
        except (ValueError,TypeError,KeyError) as error:
            self.invalid_notice.setText("未归档："+str(error))
            return
        for item in self._invalid_configurations:
            self._drafts.pop(item["group_id"],None)
        self._preserve_next_adoption=True
        self._apply_notice="已将失效材料设置完整归档，可撤销；土方和其他有效材料设置未改变。请按当前规格重新填写。"
        self.inputs_applied.emit(result)

    def take_apply_notice(self):
        text=self._apply_notice
        self._apply_notice=None
        return text

    def restore_draft(self, state):
        if not isinstance(state,dict) or not isinstance(state.get("drafts"),dict):
            return False
        try:
            state = json.loads(json.dumps(state,ensure_ascii=False,allow_nan=False))
        except (ValueError,TypeError):
            return False
        for draft in state["drafts"].values():
            if not isinstance(draft,dict) or draft.get("mode") not in {"length","station"} or not isinstance(draft.get("rows"),list):
                return False
            for row in draft["rows"]:
                if (not isinstance(row,dict) or not isinstance(row.get("length_text", ""),str)
                        or not isinstance(row.get("scheme_id"),str)
                        or not isinstance(row.get("overrides",{}),dict)
                        or row.get("scheme_snapshot") is not None and not isinstance(row["scheme_snapshot"],dict)):
                    return False
        self._drafts = deepcopy(state["drafts"])
        index = self.group_choice.findData(state.get("group_id"))
        self._building = True
        if index >= 0:
            self.group_choice.setCurrentIndex(index)
        self._building = False
        self._load_group()
        return True
