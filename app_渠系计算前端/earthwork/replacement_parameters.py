"""Drawing-linked replacement dimensions for buried pipes and box culverts."""
from copy import deepcopy
import math

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from 土石方计算.services.section_scheme_bindings import _get, _set
from 土石方计算.services.replacement_geometry import WIDTH, WIDTH_ALIAS as LEGACY_WIDTH, SLOPE, derived_replacement_fields
DEPENDENCIES = (
    "construction.working_space_left", "construction.working_space_right",
    "construction.excavation_slope_left", "construction.excavation_slope_right",
    "construction.pipe_seat.support_angle", "construction.pipe_seat.extension",
    "construction.pipe_seat.bottom_width", "construction.pipe_seat.height",
    "construction.excavation_layer_mode",
)


def _format(value):
    if value is None:
        return ""
    numeric = _number(value)
    return f"{numeric:.6f}".rstrip("0").rstrip(".") if numeric is not None else str(value)


def _number(text):
    try:
        value = float(text)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


class ReplacementDimension(QWidget):
    changed = Signal()

    def __init__(self, path, source, *, scheme=None):
        super().__init__()
        self.path = path
        self.box_paddy = (scheme or {}).get("scheme_id", source.get("section_scheme_id")) == "tzk_box_paddy"
        self.name = "石渣换填上宽" if path == WIDTH else "换填收坡"
        self._legacy = _get(source, LEGACY_WIDTH) if path == WIDTH else None
        self._initial_value = self._legacy if self._legacy is not None else _get(source, path)
        mode = (source.get("replacement_parameter_modes") or {}).get(path)
        self._manual = mode == "manual" if mode else self._initial_value is not None
        self._initial_manual = self._manual
        self._automatic = None
        self._updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        line = QHBoxLayout()
        self.edit = QLineEdit("" if self._initial_value is None else str(self._initial_value))
        self.edit.setProperty("parameter_path", path)
        self.edit.setAccessibleName(self.name)
        self.action = QPushButton()
        self.action.setAutoDefault(False)
        line.addWidget(self.edit, 1)
        line.addWidget(self.action)
        layout.addLayout(line)
        self.basis = QLabel()
        self.basis.setWordWrap(True)
        self.basis.setStyleSheet("color: #4f677a;")
        layout.addWidget(self.basis)
        self.action.clicked.connect(self._toggle)
        self.edit.textChanged.connect(self._edited)
        self._show_mode()

    def _show_mode(self):
        automatic_available = self._automatic is not None
        self.edit.setReadOnly(not self._manual and automatic_available)
        self.edit.setPlaceholderText("填写设计值")
        self.action.setText("恢复自动" if self._manual else "手动调整")
        self.action.setVisible(self._manual or automatic_available)
        self.action.setAccessibleName(self.name + " · " + self.action.text())

    def _edited(self):
        if self._updating:
            return
        if not self._manual:
            self._manual = True
            self._show_mode()
        self.changed.emit()

    def _toggle(self):
        self._manual = not self._manual
        self._show_mode()
        if self._manual:
            if self._automatic is not None:
                self._updating = True
                self.edit.setText(str(self._automatic))
                self._updating = False
            self.edit.setFocus()
            self.edit.selectAll()
        else:
            self._show_automatic_value()
        self.changed.emit()

    def _show_automatic_value(self):
        self._updating = True
        self.edit.setText(_format(self._automatic))
        self._updating = False

    def refresh(self, value, asset):
        self._automatic = value
        construction = asset.get("construction", {})
        if self.box_paddy and self.path == WIDTH:
            section = asset.get("section") or {}
            wall = section.get("wall_thickness")
            factors = (("涵身净宽", section.get("inner_width")),
                       ("左墙厚", section.get("wall_thickness_left", wall)),
                       ("右墙厚", section.get("wall_thickness_right", wall)),
                       ("左工作面", construction.get("working_space_left", .5)),
                       ("右工作面", construction.get("working_space_right", .5)))
            missing = [label for label, number in factors if _number(number) is None]
            if value is None or missing:
                required = "、".join(missing) or "涵身尺寸和左右工作面"
                text = f"核对{required}后可自动计算，也可直接填写换填上宽。"
            else:
                terms = " + ".join(label+" "+_format(number) for label, number in factors)
                text = f"{terms} = {_format(value)} m。图示两侧工作面各 0.50 m。"
        elif self.box_paddy and self.path == SLOPE:
            text = "原图石渣换填层两侧竖直，上下等宽，收坡取 0。"
        elif self.path == WIDTH:
            left, right = (_number(construction.get("working_space_"+side)) for side in ("left", "right"))
            if value is not None and left is not None and right is not None:
                multi = len(asset.get("section", {}).get("pipes") or []) > 1
                span = "管座外缘跨度" if multi else "管座底宽"
                text = f"{span} {_format(value-left-right)} + 左工作面 {_format(left)} + 右工作面 {_format(right)} = {_format(value)} m"
            else:
                text = "核对管座底宽和左右工作面后可自动计算，也可手动填写上宽。"
        else:
            left, right = (_number(construction.get("excavation_slope_"+side)) for side in ("left", "right"))
            if value is not None:
                text = f"左右开挖坡比均为 1:{_format(value)}，换填按相同坡比收坡。"
            elif any(construction.get("excavation_stages_"+side) for side in ("left","right")) or (
                    construction.get("excavation_layer_mode") == "surface_thickness"):
                text = "本段采用分级或分层开挖，请手动填写换填层的收坡。"
            elif left is not None and right is not None and left != right:
                text = f"左侧开挖 1:{_format(left)}，右侧 1:{_format(right)}。请手动填写本段换填收坡。"
            else:
                text = "核定本段左右开挖坡比后可自动取值，也可手动填写换填收坡。"
        self.basis.setText(text)
        if not self._manual:
            self._show_automatic_value()
        self._show_mode()

    def source_record(self):
        return {"adopted_value": _number(self.edit.text()) if self._manual else self._automatic, "user_override": self._manual,
                "title": "本段换填几何", "geometry_derived": True, "geometry_basis": self.basis.text()}

    def changes(self):
        if not self._manual:
            if not self._initial_manual:
                return {}
            cleared = {self.path: None}
            if self.path == WIDTH:
                cleared[LEGACY_WIDTH] = None
            return cleared
        value = _number(self.edit.text())
        if value is None or value < 0 or (self.path == WIDTH and value == 0):
            raise ValueError(self.name + ("须大于零" if self.path == WIDTH else "须为非负数"))
        if self._initial_manual and value == _number(self._initial_value):
            return {}
        overrides = {self.path: value}
        if self._legacy is not None:
            overrides[LEGACY_WIDTH] = None
        return overrides


def refresh_replacement_dimensions(rows, source, scheme, fields, *, pipe_rows=None, stages=None, explicit=None):
    asset = {**source, "construction":deepcopy(source.get("construction") or {})}
    if pipe_rows is not None:
        asset["section"] = {"pipes": pipe_rows}
        gap = fields["section.pipe_spacing"].text().strip().replace("，", ",")
        if gap:
            items = [_number(item) for item in gap.split(",")]
            asset["section"]["pipe_spacing"] = items if len(items) > 1 else items[0]
    for path in DEPENDENCIES:
        if path in fields:
            widget = fields[path]
            value = widget.currentData() if hasattr(widget, "currentData") else _number(widget.text())
            _set(asset, path, value)
    if stages is not None:
        asset["construction"].update(stages)
    computed = derived_replacement_fields(asset, scheme, explicit=explicit)
    for path, row in rows.items():
        row.refresh(computed.get(path), asset)
