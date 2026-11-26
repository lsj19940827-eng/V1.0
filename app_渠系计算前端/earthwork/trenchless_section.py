"""Edit the excavation diameter and radial clearance of a trenchless span."""
from __future__ import annotations

from collections import Counter

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from 土石方计算.services.contracts import finite_number
from 土石方计算.services.earthwork_scope import TRENCHLESS_RADIAL_CLEARANCE_M, trenchless_bore_values, trenchless_edit_key


_LENGTH_BASIS = {
    "design_profile_spatial": "设计纵断面空间长度",
    "plan_chainage": "平面桩号差",
}
_KEY_FIELDS = ("route_id", "source_identity", "construction_method", "station_start", "station_end")


def _label():
    label = QLabel()
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    return label


def _number_text(value):
    return f"{value:.12g}" if value is not None else ""


class TrenchlessSectionCard(QFrame):
    save_requested = Signal(object, object, object)
    draft_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drafts = {}
        self._section_rows = ()
        self._keys = ()
        self._excluded = False
        self._row = None
        self._key = None
        self._override_text = None
        self._clearance_text = ""
        self._parameters = None
        self.setObjectName("trenchlessSectionCard")
        self.setStyleSheet("""
            #trenchlessSectionCard {background:white;border:1px solid #DDE3EB;border-radius:5px;}
            #trenchlessSectionCard QLabel {background:transparent;color:#18212E;}
            #trenchlessSectionCard QLineEdit {min-height:22px;padding:0 8px;border:1px solid #DDE3EB;border-radius:5px;}
            #trenchlessSectionCard QLineEdit:focus {border-color:#3346A2;}
            #trenchlessSectionCard QLineEdit:read-only {background:#F6F8FA;}
            #trenchlessSectionCard QPushButton {min-height:27px;padding:0 10px;}
            #trenchlessSectionCard QPushButton[primary="true"]:enabled {background:#3346A2;color:white;}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 11, 18, 11)
        layout.setSpacing(8)
        heading = QLabel("施工断面")
        heading.setStyleSheet("font-size:18px;font-weight:600;color:#18212E;")
        layout.addWidget(heading)

        self.span_selector = QWidget()
        span_form = QFormLayout(self.span_selector)
        span_form.setContentsMargins(0, 0, 0, 0)
        span_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        span_form.setHorizontalSpacing(24)
        self.span_choice = QComboBox()
        self.span_choice.currentIndexChanged.connect(self._load_span)
        span_form.addRow("计量区段", self.span_choice)
        self.span_selector.hide()
        layout.addWidget(self.span_selector)

        self.form = QFormLayout()
        self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.form.setHorizontalSpacing(24)
        self.nominal_diameter = QLineEdit()
        self.nominal_diameter.setMaximumWidth(180)
        self.nominal_diameter.setReadOnly(True)
        self.form.addRow("公称直径（m）", self.nominal_diameter)
        self.clearance_edit = QLineEdit()
        self.clearance_edit.setMaximumWidth(180)
        self.clearance_edit.setToolTip("修改开挖直径时按公称直径反算每侧预留。修改每侧预留时按公式更新开挖直径。")
        self.clearance_edit.textEdited.connect(self._clearance_edited)
        self.form.addRow("每侧预留（m）", self.clearance_edit)
        self.diameter_edit = QLineEdit()
        self.diameter_edit.setMaximumWidth(180)
        self.diameter_edit.textEdited.connect(self._diameter_edited)
        self.form.addRow("开挖直径（m）", self.diameter_edit)
        self.length = _label()
        self.volume = _label()
        self.form.addRow("计量长度", self.length)
        self.form.addRow("计量结果", self.volume)
        layout.addLayout(self.form)

        self.error = _label()
        self.error.setStyleSheet("color:#A32632;")
        self.error.hide()
        layout.addWidget(self.error)
        self.actions = QWidget()
        buttons = QHBoxLayout(self.actions)
        buttons.setContentsMargins(0, 0, 0, 0)
        self.restore_button = QPushButton("恢复自动直径")
        self.restore_button.clicked.connect(self._restore_auto)
        self.cancel_button = QPushButton("放弃修改")
        self.cancel_button.clicked.connect(self._cancel)
        self.save_button = QPushButton("保存参数")
        self.save_button.setProperty("primary", True)
        self.save_button.clicked.connect(self._save)
        for button in (self.restore_button, self.cancel_button, self.save_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addWidget(self.actions)
        self._load_span()

    def set_section(self, section_rows, *, excluded):
        selected = self._key
        self._section_rows = tuple(section_rows)
        self._excluded = excluded
        keys = [trenchless_edit_key(row) if row.get("editable", True) else None for _, row in self._section_rows]
        counts = Counter(keys)
        self._keys = tuple(key if not excluded and counts[key] == 1 else None for key in keys)
        index = self._keys.index(selected) if selected is not None and selected in self._keys else 0
        with QSignalBlocker(self.span_choice):
            self.span_choice.clear()
            for span, _ in self._section_rows:
                self.span_choice.addItem(span)
            self.span_choice.setCurrentIndex(index)
        self.span_selector.setVisible(len(self._section_rows) > 1)
        self._load_span()

    def _saved_texts(self):
        row = self._row or {}
        override = row.get("bore_diameter_override_m")
        clearance = row.get("radial_clearance_m", TRENCHLESS_RADIAL_CLEARANCE_M)
        return _number_text(override) if override is not None else None, _number_text(clearance)

    def _load_span(self, *_):
        index = self.span_choice.currentIndex()
        self._row = self._section_rows[index][1] if index >= 0 else None
        self._key = self._keys[index] if index >= 0 else None
        row = self._row or {}
        editable = self._key is not None
        self.diameter_edit.setReadOnly(not editable)
        self.clearance_edit.setReadOnly(not editable)
        self.actions.setVisible(editable)
        self._override_text, self._clearance_text = self._drafts.get(self._key, self._saved_texts())
        self.nominal_diameter.setText(_number_text(row.get("pipe_diameter_m")))
        self.nominal_diameter.setPlaceholderText("待补公称直径" if self._row else "—")
        self.clearance_edit.setText(self._clearance_text if self._row else "")
        self.clearance_edit.setPlaceholderText("—")
        self.diameter_edit.setText(_number_text(row.get("bore_diameter_m")))
        self.diameter_edit.setPlaceholderText("待补公称直径" if self._row else "—")
        length = row.get("length_m")
        self.length.setText(f"{length:.3f} m" if length is not None else "待核起止桩号" if self._row else "—")
        self.length.setToolTip(_LENGTH_BASIS.get(row.get("length_basis"), ""))
        self._preview()

    def _diameter_edited(self, text):
        self._override_text = text
        self._remember()

    def _clearance_edited(self, text):
        self._override_text = None
        self._clearance_text = text
        self._remember()

    def _restore_auto(self):
        self._clearance_text = self.clearance_edit.text() or self._clearance_text
        self._override_text = None
        self._remember()

    def _remember(self):
        if self._key is None:
            return
        draft = self._override_text, self._clearance_text
        previous = self._drafts.get(self._key)
        if draft == self._saved_texts():
            self._drafts.pop(self._key, None)
        else:
            self._drafts[self._key] = draft
        self._preview()
        if previous != self._drafts.get(self._key):
            self.draft_changed.emit()

    def _automatic_clearance(self):
        clearance = finite_number(self._clearance_text, "每侧预留")
        if clearance < 0:
            raise ValueError("每侧预留不能小于 0 m。")
        return clearance

    def _preview(self):
        row = self._row or {}
        volume = row.get("trenchless_excavation_volume")
        self._parameters = None
        error = ""
        if self._key is not None:
            nominal = row.get("pipe_diameter_m")
            manual = self._override_text is not None
            clearance_text = "" if manual else self._clearance_text
            try:
                override = finite_number(self._override_text, "开挖直径") if manual else None
                if manual and nominal is not None:
                    if override < nominal:
                        error = f"开挖直径不能小于公称直径 {_number_text(nominal)} m。"
                        if self._key in self._drafts:
                            raise ValueError(error)
                    else:
                        clearance_text = _number_text((override - nominal) / 2)
                try:
                    clearance = self._automatic_clearance()
                except ValueError:
                    if not manual:
                        raise
                    clearance = row.get("radial_clearance_m", TRENCHLESS_RADIAL_CLEARANCE_M)
                diameter, _, volume = trenchless_bore_values(nominal, row.get("length_m"), clearance, override)
                self._parameters = override, clearance
            except ValueError as exc:
                diameter = volume = None
                error = str(exc)
            text = self._override_text if self._override_text is not None else _number_text(diameter)
            if text != self.diameter_edit.text():
                self.diameter_edit.setText(text)
            if clearance_text != self.clearance_edit.text():
                self.clearance_edit.setText(clearance_text)
            self.diameter_edit.setPlaceholderText("待补公称直径" if not manual and nominal is None else "—")
            self.clearance_edit.setPlaceholderText("待补公称直径" if manual and nominal is None else "—")
        self.error.setText(error)
        self.error.setVisible(bool(error))
        if volume is not None:
            result = f"{volume:.3f} m³"
        elif self._excluded:
            result = "本次不计"
        else:
            result = "待计量" if self._row else "待补施工资料"
        self.volume.setText(result)
        dirty = self._key in self._drafts
        self.restore_button.setEnabled(self._override_text is not None)
        self.cancel_button.setEnabled(dirty)
        self.save_button.setEnabled(dirty and self._parameters is not None)

    def _save(self):
        if self._key in self._drafts and self._parameters is not None:
            self.save_requested.emit(self._key, *self._parameters)

    def _cancel(self):
        self.accept_edit(self._key)

    def accept_edit(self, key):
        if self._drafts.pop(key, None) is not None:
            if key == self._key:
                self._load_span()
            self.draft_changed.emit()

    def first_unapplied_edit(self):
        if self._key in self._drafts:
            return self._key
        return next(iter(self._drafts), None)

    def select_edit(self, key):
        if key is None or key not in self._keys:
            return False
        self.span_choice.setCurrentIndex(self._keys.index(key))
        return True

    def retain_drafts(self, valid_keys):
        removed = self._drafts.keys() - valid_keys
        for key in removed:
            del self._drafts[key]
        if self._key in removed:
            self._load_span()

    def export_drafts(self):
        return [{"key": list(key), "diameter_override": override, "clearance": clearance}
                for key, (override, clearance) in self._drafts.items()]

    def restore_drafts(self, state):
        self._drafts.clear()
        for item in state if isinstance(state, (list, tuple)) else ():
            if not isinstance(item, dict):
                continue
            raw_key, override, clearance = item.get("key"), item.get("diameter_override"), item.get("clearance")
            if (isinstance(raw_key, (list, tuple)) and len(raw_key) == len(_KEY_FIELDS)
                    and isinstance(clearance, str) and (override is None or isinstance(override, str))):
                key = trenchless_edit_key(dict(zip(_KEY_FIELDS, raw_key)))
                if key is not None:
                    self._drafts[key] = override, clearance
        self._load_span()

    def reset_context(self):
        self._drafts.clear()
        self.set_section((), excluded=False)
