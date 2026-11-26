"""Select buried pipe objects and the common construction values to apply."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QVBoxLayout,
)

from 土石方计算.services.pipe_batch_parameters import BATCH_FIELDS, apply_pipe_batch_parameters, pipe_batch_objects
from 土石方计算.services.section_scheme_bindings import _get, format_station
from .section_preparation import building_display_name, building_structure


class PipeBatchParametersDialog(QDialog):
    def __init__(self, inputs, parent=None, *, selected=None, selected_keys=()):
        super().__init__(parent)
        self.setWindowTitle("批量设置施工参数")
        self.resize(490,420)
        self.inputs = inputs
        self.updated_inputs = None
        self.objects = pipe_batch_objects(inputs)
        checked_keys = set(selected_keys)
        if selected is not None:
            checked_keys.add(selected)
        self.field_checks, self.edits, self._typed = {}, {}, set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18,16,18,16)
        layout.setSpacing(10)
        self.targets_label = QLabel("应用对象")
        self.targets = QListWidget()
        self.targets.setAccessibleName("应用对象")
        self.targets.setAlternatingRowColors(True)
        self.targets.setWordWrap(True)
        self.targets.setMinimumHeight(78)
        for key,(network,parts) in self.objects.items():
            name = building_display_name(parts[0])
            route = str(network.get("name") or key[0])
            span = ""
            starts = [p.get("station_start") for p in parts]
            ends = [p.get("station_end") for p in parts]
            if all(v is not None for v in starts+ends):
                prefix = network.get("station_prefix") or "K"
                span = f"　{format_station(min(starts),prefix)} ～ {format_station(max(ends),prefix)}"
            row = QListWidgetItem(f"{route} / {name}　{building_structure(parts[0])}{span}")
            row.setData(Qt.UserRole,key)
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(Qt.Checked if key in checked_keys else Qt.Unchecked)
            self.targets.addItem(row)
        layout.addWidget(self.targets_label)
        layout.addWidget(self.targets,1)
        layout.addWidget(QLabel("要修改的参数"))
        form=QGridLayout()
        form.setVerticalSpacing(8)
        for i,(field,(label,_)) in enumerate(BATCH_FIELDS.items()):
            check=QCheckBox(label)
            edit=QLineEdit()
            edit.setMinimumHeight(29)
            edit.setAccessibleName(label)
            edit.setEnabled(False)
            check.toggled.connect(edit.setEnabled)
            edit.textEdited.connect(lambda _value, k=field:self._typed.add(k))
            self.field_checks[field],self.edits[field]=check,edit
            form.addWidget(check,i,0)
            form.addWidget(edit,i,1)
        layout.addLayout(form)
        self.message=QLabel()
        self.message.setStyleSheet("color:#A03E25;")
        self.message.setWordWrap(True)
        self.message.hide()
        layout.addWidget(self.message)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("应用到所选对象")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.targets.itemChanged.connect(self._refresh_values)
        self._refresh_values()

    def _keys(self):
        return [tuple(self.targets.item(i).data(Qt.UserRole)) for i in range(self.targets.count())
                if self.targets.item(i).checkState()==Qt.Checked]

    def _refresh_values(self):
        selected=self._keys()
        self.targets_label.setText(f"应用对象（已选 {len(selected)} 个）")
        parts=[part for key in selected for part in self.objects[key][1]]
        for field,(_,paths) in BATCH_FIELDS.items():
            if field in self._typed:
                continue
            edit=self.edits[field]
            numbers={_get(part,path) for part in parts for path in paths}
            single=next(iter(numbers)) if len(numbers)==1 else None
            edit.setText(f"{float(single):g}" if isinstance(single,(float,int)) else "")
            edit.setPlaceholderText("各段当前值不同" if len(numbers)>1 else "填写设计值")

    def accept(self):
        values={key:self.edits[key].text() for key,check in self.field_checks.items() if check.isChecked()}
        try:
            self.updated_inputs = apply_pipe_batch_parameters(self.inputs,self._keys(),values)
        except (ValueError,TypeError,KeyError) as error:
            self.message.setText(str(error))
            self.message.show()
            return
        super().accept()
