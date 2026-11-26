"""Design profile sources for the quantity workbench."""
from __future__ import annotations

from copy import deepcopy
from math import isfinite
from pathlib import Path

from PySide6.QtCore import Qt, QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton, QRadioButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .pipe_profile_mapping import (
    ROUTE, apply_mapped_profiles, eligible_objects, mapped_profiles, profile_key,
    profile_objects, source_bounds, suggest_assignments, trenchless_targets,
)
from .profile_file import DXF_PROFILE_FILTER, read_dxf_candidates
from .pipe_design_preview import ProfilePreviewPane, ProfilePreviewSeries, show_profile_preview
from .choice_display import ChoiceDisplay
from .pipe_construction_objects import profile_source_groups, source_scope_asset, source_scope_key
from 土石方计算.services.batch_cover_profiles import DEFAULT_WORKBENCH_COVER_M
from 土石方计算.services.earthwork_scope import trenchless_exclusions, trenchless_intersections, trenchless_method
from 土石方计算.services.imported_design_profiles import _same_source_route, apply_asset_profile
from 土石方计算.services.siphon_axis_choices import configure_siphon_axis, is_siphon_axis_asset
from 土石方计算.services.pipe_profile_partitions import awaiting_water_profile_parts, resolve_profile_gap
from 土石方计算.services.pipe_profile_sources import pipe_profile_choice
from 土石方计算.services.design_profiles import sync_bound_axis_controls
from 土石方计算.services.section_scheme_bindings import format_station


def _name(asset):
    from .section_preparation import building_display_name
    return building_display_name(asset)


def _station(s):
    mm = round(abs(float(s))*1000)
    km, remainder = divmod(mm, 1_000_000)
    return f"{'-' if s < 0 else ''}K{km}+{remainder/1000:07.3f}".rstrip("0").rstrip(".")


def _span(a, b):
    return "桩号待补" if a is None or b is None else f"{_station(a)} ～ {_station(b)}"


def _blank_station_details(start, end, tunnels, pending):
    intervals = [(max(a, start), min(b, end), label) for a, b, label in (*tunnels, *pending)
                 if min(b, end) - max(a, start) > .001]
    bounds = sorted({start, end, *(s for a, b, _ in intervals for s in (a, b))})
    sections = []
    for a, b in zip(bounds, bounds[1:]):
        if b-a <= .001:
            continue
        label = next((name for left, right, name in intervals if left <= a and b <= right), "工程对象待核对")
        if sections and sections[-1][2] == label:
            sections[-1] = (sections[-1][0], b, label)
        else:
            sections.append((a, b, label))
    return "、".join(f"{_span(a, b)}　{label}" for a, b, label in sections)


def _object_label(network, asset):
    route = network.get("name") or network.get("route_id") or network.get("network_id") or ""
    return f"{route} · {_name(asset)}　{_span(asset.get('station_start'),asset.get('station_end'))}"


class PipeObjectChoice(QComboBox):
    def findData(self, value, *args):
        # Qt compares Python tuple variants by identity on Windows.
        if isinstance(value, tuple):
            return next((i for i in range(self.count()) if self.itemData(i)==value),-1)
        return super().findData(value,*args)


class _SourceChoices(QWidget):
    changed = Signal()

    choices = (
        ("water", "沿用水面线纵断面"),
        ("water_parts", "沿用水面线分段纵断面"),
        ("current", "当前设计纵断面"),
        ("dxf", "导入设计纵断面 DXF"),
        ("cover", "按管顶覆土生成"),
    )

    def __init__(self):
        super().__init__()
        self.group=QButtonGroup(self)
        column=QVBoxLayout(self)
        column.setContentsMargins(0,0,0,0)
        column.setSpacing(3)
        self.options={}
        for key, label in self.choices:
            radio=QRadioButton(label)
            radio.setProperty("source",key)
            radio.setMinimumHeight(29)
            self.group.addButton(radio)
            self.options[key]=radio
            column.addWidget(radio)
        self.group.buttonToggled.connect(lambda _,checked:self.changed.emit() if checked else None)

    def currentData(self):
        button=self.group.checkedButton()
        return button.property("source") if button else ""

    def select(self,key):
        if key in self.options:
            self.options[key].setChecked(True)
        elif self.group.checkedButton():
            self.group.setExclusive(False)
            self.group.checkedButton().setChecked(False)
            self.group.setExclusive(True)

    def configure(self, available, mode):
        for key, control in self.options.items():
            control.setVisible(key in available)
        self.select(mode)


class _SourceCombo(QComboBox):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setPlaceholderText("选择纵断面来源")
        self.currentIndexChanged.connect(lambda _: self.changed.emit())

    def select(self, mode):
        self.setCurrentIndex(self.findData(mode))

    def configure(self, available, mode):
        self.clear()
        for key, label in _SourceChoices.choices:
            if key in available:
                self.addItem(label, key)
        self.select(mode)


def water_axis(asset):
    source = asset.get("siphon_axis_input") or {}
    if asset.get("water_profile_design_profile"):
        return asset["water_profile_design_profile"]
    if asset.get("axis_source")=="water_profile_real_elevation":
        return asset.get("design_profile")
    if (source.get("source") or {}).get("kind") == "water_profile" and source.get("profile"):
        candidate=deepcopy(asset)
        result=configure_siphon_axis(candidate,mode="exact")
        if result["status"] in {"actual","aligned"}:return candidate.get("design_profile")
    return None


def _profile_mode(asset):
    if asset.get("pipe_profile_choice")=="pending_gap":
        return "pending_gap"
    if awaiting_water_profile_parts(asset):
        return "water_parts"
    status=(asset.get("siphon_axis_choice") or {}).get("status")
    if status in {"mismatch","pending"}:
        return status
    if (asset.get("construction") or {}).get("burial_mode")=="cover_depth":
        return "cover"
    if not asset.get("design_profile"):
        return ""
    source=asset.get("axis_source") or asset.get("profile_source")
    return "water" if source=="water_profile_real_elevation" else "current"


def _adopted_design_profile(asset):
    if _profile_mode(asset) == "cover" and asset.get("axis_source") != "terrain_and_user_cover_depth":
        return None
    return asset.get("design_profile")


def profile_source_label(asset):
    mode=_profile_mode(asset)
    if mode=="cover":
        construction=asset["construction"]
        segments=construction.get("cover_segments") or []
        if segments:
            return f"管顶覆土 · 分段设置（{len(segments)} 段）"
        depth=construction.get("cover_depth")
        if depth is None:
            depth=DEFAULT_WORKBENCH_COVER_M
        automatic="（工程默认）" if pipe_profile_choice(asset)!="cover_depth" else ""
        return f"管顶覆土 {float(depth):g} m"+automatic
    if mode!="current":
        return {"pending_gap":"纵断面缺口待补","water_parts":"水面线分段待确认","mismatch":"纵断面桩号待核对",
                "pending":"倒虹吸纵断面待补","water":"已沿用水面线纵断面","":"待选纵断面来源"}[mode]
    original = asset.get("profile_source_file") or {}
    return str(original.get("filename") or Path(original.get("path","")).name or "已采用设计纵断面")


def profile_scope_source_label(members, *, detail=False):
    labels = [profile_source_label(asset) for _, asset in members]
    if len(set(labels)) == 1:
        return labels[0]
    if not detail:
        return "纵断面采用多种来源"
    return "\n".join(f"{_span(asset.get('station_start'), asset.get('station_end'))}　{label}"
                     for (_, asset), label in zip(members, labels, strict=True))


def _cover_candidate(asset, depth, *, keep_segments=False):
    target = deepcopy(asset)
    resolve_profile_gap(target)
    water = water_axis(target)
    if water: target["water_profile_design_profile"] = deepcopy(water)
    construction = target.setdefault("construction", {})
    if is_siphon_axis_asset(target):
        configure_siphon_axis(target, mode="cover_depth", cover_depth_m=depth)
    else:
        same = (target.get("axis_source") == "terrain_and_user_cover_depth"
                and construction.get("burial_mode")=="cover_depth" and construction.get("cover_depth")==depth
                and (keep_segments or not construction.get("cover_segments")))
        # Preserve a previously sampled axis only for the same adopted depth.
        if not same:
            if target.get("design_profile"):
                target.setdefault("original_design_profile", deepcopy(target["design_profile"]))
            for field in ("design_profile","profile_points","axis_source","profile_source","profile_source_file",
                          "profile_import_mapping","axis_cover_samples","axis_preview_sha256","cover_confirmation",
                          "cover_generation_options","cover_actual_cover_summary","cover_preview_confirmed"):
                target.pop(field, None)
            target.setdefault("alignment", {}).pop("profile_points", None)
            construction.pop("axis_confirmed", None)
        construction.update(burial_mode="cover_depth", cover_depth=depth)
    if not keep_segments:
        construction.pop("cover_segments", None)
    target["pipe_profile_choice"] = "cover_depth"
    sync_bound_axis_controls(target)
    return target


class DxfProfileMappingDialog(QDialog):
    """Review files, candidate lines, stationing and object assignments together."""
    def __init__(self, inputs, selected, paths, parent=None, *, exact=False):
        super().__init__(parent)
        self.inputs = inputs
        objects = profile_objects(inputs)
        self.network, self.asset = objects[selected]
        self.siphon = is_siphon_axis_asset(self.asset)
        self.targets = {selected: objects[selected]} if exact else eligible_objects(objects, selected)
        tunnels = []
        if not self.siphon and not exact:
            self.targets.update(trenchless_targets(inputs,self.network))
            self.targets = dict(sorted(self.targets.items(),
                key=lambda item: (item[1][1]["station_start"], item[1][1]["station_end"])))
            tunnels = [a for n in inputs.get("networks",[]) if _same_source_route(n,self.network)
                       for a in n.get("assets",[]) if a.get("kind")=="tunnel"]
        self.display_targets = dict(self.targets)
        self.target_groups = {}
        self.display_keys = {}
        if not self.siphon:
            for members in profile_source_groups(inputs).values():
                members = tuple((n, a) for n, a in members if profile_key(n, a) in self.targets)
                if len(members) <= 1:
                    continue
                group_key = profile_key(*members[0])
                bounds = source_scope_asset(members)
                member_keys = [profile_key(n, a) for n, a in members]
                gaps = [(before["station_end"], after["station_start"])
                        for (_, before), (_, after) in zip(members, members[1:])]
                member_keys.extend(key for key, (_, asset) in self.targets.items()
                                   if (asset.get("kind") == "trenchless" or trenchless_method(asset)) and
                                   any(a - .001 <= asset["station_start"] < asset["station_end"] <= b + .001
                                       for a, b in gaps))
                self.target_groups[group_key] = tuple(key for key in self.targets if key in member_keys)
                for member_key in member_keys:
                    self.display_keys[member_key] = group_key
                    if member_key != group_key:
                        self.display_targets.pop(member_key, None)
                self.display_targets[group_key] = members[0][0], bounds
            if len(self.display_targets) == 1:
                self.display_keys[ROUTE] = next(iter(self.display_targets))
        self.route_tunnels = tunnels
        self.tunnel_ranges = [(a["station_start"],a["station_end"]) for a in tunnels
                              if a.get("station_start") is not None and a.get("station_end") is not None]
        self.curves = []
        self.file_errors = []
        for path in dict.fromkeys(paths):
            try:
                lines,source = read_dxf_candidates(path)
                lines.sort(key=lambda c: c["profile"]["station_start"] if "profile" in c else float("inf"))
                self.curves.extend(dict(c, source=source) for c in lines)
            except (ValueError,OSError) as error:
                self.file_errors.append(f"{Path(path).name}：{error}")
        self.updated_inputs = None
        self.setWindowTitle("倒虹吸 DXF 多段线匹配" if self.siphon else "有压管道 DXF 多段线匹配")
        valid_count = sum("profile" in curve for curve in self.curves)
        show_layout = valid_count > 1
        self.resize(1050,660 if show_layout else 550)
        layout = QVBoxLayout(self)
        if self.siphon:
            hint = "请核对各文件对应的倒虹吸及起桩。"
        elif not show_layout and len(self.display_targets) == 1:
            hint = "请核对图面范围和对应起桩。"
        else:
            hint = "多段线按图面从左到右排列，管段按桩号从小到大匹配。可调整采用对象和对应起桩。"
        label = QLabel(f"已选 {len(paths)} 个文件　·　{len(self.curves)} 条多段线。{hint}")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.drawing_layout = None
        if show_layout:
            from .pipe_profile_layout import DrawingProfileLayout
            self.drawing_layout = DrawingProfileLayout()
            layout.addWidget(self.drawing_layout)
        self.table = QTableWidget(len(self.curves),6)
        self.table.setObjectName("dxfProfileMappingTable")
        self.table.setHorizontalHeaderLabels(["文件 / 图层", "图面 X 范围 (m)",
                                              "坐标单位","采用对象","对应起桩 (m)","高程基准"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().hide()
        header=self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(3,QHeaderView.Stretch)
        for i,size in ((0,220),(1,164),(2,88),(4,118),(5,115)):
            self.table.setColumnWidth(i,size)
        layout.addWidget(self.table,1)
        self.controls = []
        self.suggestions = suggest_assignments(self.curves, self.targets, siphon=self.siphon,
                                               tunnel_ranges=self.tunnel_ranges)
        fixed_target = None
        if len(self.display_targets) == 1 and valid_count == 1:
            suggested = next(key for curve, (key, _) in zip(self.curves, self.suggestions) if "profile" in curve)
            fixed_target = self.display_keys.get(suggested, suggested)
        self.fixed_target = fixed_target
        for row, (curve,(suggested,origin)) in enumerate(zip(self.curves, self.suggestions)):
            source = curve["source"]
            source_item = QTableWidgetItem(f"{source['filename']}\n{curve['layer']}")
            source_item.setToolTip(f"{source['filename']}\n图层 {curve['layer']}")
            self.table.setItem(row,0,source_item)
            self.table.setRowHeight(row,45)
            if "error" in curve:
                item=QTableWidgetItem(curve["error"])
                item.setToolTip(curve["error"])
                self.table.setSpan(row,1,1,5)
                self.table.setItem(row,1,item)
                self.controls.append(None)
                continue
            self.table.setItem(row, 2, QTableWidgetItem("米"))
            self.table.setItem(row, 5, QTableWidgetItem("管道中心线"))
            target = None
            if fixed_target is not None:
                target_label = _object_label(*self.display_targets[fixed_target])
                target_item = QTableWidgetItem(target_label)
                target_item.setToolTip(target_label)
                self.table.setItem(row, 3, target_item)
            else:
                target = PipeObjectChoice()
                target.addItem("跳过此线", None)
                if not self.siphon and len(self.display_targets) > 1:
                    target.addItem("同线覆盖管段（含非开挖）", ROUTE)
                for key, (network, asset) in self.display_targets.items():
                    target.addItem(_object_label(network, asset), key)
                target.setCurrentIndex(max(0, target.findData(self.display_keys.get(suggested, suggested))))
                target.setMinimumWidth(95)
                self.table.setCellWidget(row, 3, target)
            position=QDoubleSpinBox()
            position.setDecimals(6)
            position.setRange(-1e9,1e9)
            position.setKeyboardTracking(False)
            position.setValue(origin)
            self.table.setCellWidget(row, 4, position)
            self.controls.append((target, position))
            start, end = source_bounds(curve, "m")
            self.table.setItem(row, 1, QTableWidgetItem(f"{start:.3f} ～ {end:.3f}"))
        for i, controls in enumerate(self.controls):
            if controls is None:
                continue
            target, position = controls
            if target is not None:
                target.currentIndexChanged.connect(lambda _, row=i: self._change_target(row))
            position.valueChanged.connect(lambda _: self._refresh())
        if self.drawing_layout is not None:
            self.drawing_layout.row_selected.connect(self.table.selectRow)
            self.table.currentCellChanged.connect(self._highlight_drawing_row)
        if self.table.rowCount():self.table.selectRow(0)
        preview=QPushButton("查看选中多段线")
        preview.clicked.connect(self._preview)
        layout.addWidget(preview,0,Qt.AlignLeft)
        self.tunnels=QLabel()
        self.tunnels.setWordWrap(True)
        if tunnels:
            spans = [_name(a)+"　"+_span(a.get("station_start"),a.get("station_end")) for a in tunnels]
            self.tunnels.setText("隧洞沿用各自纵断面　"+"；".join(spans))
        self.tunnels.setVisible(bool(self.tunnels.text()))
        if self.file_errors:
            failures=QLabel("以下文件未列入本次匹配\n"+"\n".join(self.file_errors))
            failures.setWordWrap(True)
            layout.addWidget(failures)
        self.status=QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.drawing_gaps = QLabel()
        self.drawing_gaps.setTextFormat(Qt.PlainText)
        self.drawing_gaps.setWordWrap(True)
        self.drawing_gaps.setTextInteractionFlags(Qt.TextSelectableByMouse)
        summary = QWidget()
        details = QVBoxLayout(summary)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(3)
        details.setAlignment(Qt.AlignTop)
        details.addWidget(self.drawing_gaps)
        details.addWidget(self.tunnels)
        details.addWidget(self.status)
        review=QScrollArea()
        review.setFrameShape(QScrollArea.NoFrame)
        review.setWidgetResizable(True)
        review.setMinimumHeight(84 if show_layout else 54)
        review.setMaximumHeight(130 if show_layout else 112)
        review.setWidget(summary)
        layout.addWidget(review)
        self.keep_covered=QCheckBox("仅采用已覆盖管段，所列缺口待补")
        self.keep_covered.setObjectName("dxfAcceptCoveredRanges")
        self.keep_covered.toggled.connect(self._update_apply)
        layout.addWidget(self.keep_covered)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        self.apply=buttons.button(QDialogButtonBox.Ok)
        self.apply.setText("采用所列匹配")
        buttons.button(QDialogButtonBox.Cancel).setText("返回")
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def _change_target(self, row):
        target, position = self.controls[row]
        dest = target.currentData()
        start, end = source_bounds(self.curves[row], "m")
        suggested, origin = self.suggestions[row]
        if dest is not None and dest == self.display_keys.get(suggested, suggested):
            start = origin
        elif dest in self.display_targets:
            _,a = self.display_targets[dest]
            translated = not self.siphon and suggested is not None and abs(origin-start) > .001
            if translated or min(end,a["station_end"])-max(start,a["station_start"])<=1e-7:
                start = a["station_start"]
        with QSignalBlocker(position):
            position.setValue(start)
        self._refresh()

    def _assignments(self):
        result=[]
        for controls in self.controls:
            if controls:
                target, station = controls
                destination = target.currentData() if target is not None else self.fixed_target
                result.append((destination, "m", station.value(), "pipe_axis"))
            else:result.append((None,"m",0.,"pipe_axis"))
        return result

    def _highlight_drawing_row(self, row, column, previous_row, previous_column):
        self.drawing_layout.set_current_row(row)
        if (hasattr(self, "mapped") and previous_row >= 0 and row >= 0
                and self.curves[row]["source"]["path"] != self.curves[previous_row]["source"]["path"]):
            self._show_drawing_gaps(self._assignments())

    def _mapped_row_extent(self, row, assignments):
        target, units, start, _ = assignments[row]
        left, right = source_bounds(self.curves[row], units)
        end = start + (right - left)
        spans = []
        for key in self.mapped:
            if target == ROUTE or key in self.target_groups.get(target, (target,)):
                asset = self.targets[key][1]
                a, b = max(start, asset["station_start"]), min(end, asset["station_end"])
                if b > a:
                    spans.append((a, b))
        if spans:
            return min(a for a, _ in spans), max(b for _, b in spans)

    def _show_drawing_gaps(self, assignments):
        gaps = self.drawing_layout.gap_rows if self.drawing_layout is not None else []
        self.drawing_gaps.setVisible(bool(gaps))
        self.tunnels.setVisible(bool(self.route_tunnels))
        if not gaps:
            self.drawing_gaps.clear()
            return
        lines = [f"图面留空 {len(gaps)} 处"]
        tunnels = [(a["station_start"], a["station_end"], _name(a)) for a in self.route_tunnels
                   if a.get("station_start") is not None and a.get("station_end") is not None]
        pending = [(a, b, "纵断面待补") for coverage in self.mapped.values() for a, b in coverage.gaps]
        shown_tunnels = set()
        if self.mapped:
            for i, (left, right) in enumerate(gaps, 1):
                upstream = self._mapped_row_extent(left, assignments)
                downstream = self._mapped_row_extent(right, assignments)
                if not upstream or not downstream:
                    continue
                start, end = upstream[1], downstream[0]
                if abs(start-end) <= .001:
                    detail = f"两侧管段在 {_station(start)} 相接"
                elif start > end:
                    detail = f"左段止于 {_station(start)}，右段起于 {_station(end)}，请核对顺序"
                else:
                    detail = _blank_station_details(start, end, tunnels, pending)
                    shown_tunnels.update((a, b) for a, b, _ in tunnels if start <= a and b <= end)
                lines.append(f"第 {i} 处　{detail}")
        if self.route_tunnels and all((a.get("station_start"), a.get("station_end")) in shown_tunnels
                                      for a in self.route_tunnels):
            self.tunnels.hide()
        self.drawing_gaps.setText("\n".join(lines))

    def _refresh(self):
        with QSignalBlocker(self.keep_covered):self.keep_covered.setChecked(False)
        assignments = self._assignments()
        try:
            self.mapped=mapped_profiles(self.curves,assignments,self.targets,target_groups=self.target_groups)
        except ValueError as error:
            self.mapped={}
            self.status.setText(str(error))
        else:
            labels=[]
            for k,coverage in self.mapped.items():
                name=_name(self.targets[k][1])
                spans="、".join(_span(p["station_start"],p["station_end"]) for p,_ in coverage.runs)
                labels.append(f"{name}　采用 {spans}")
                if coverage.gaps:labels.append("缺口待补　"+"、".join(_span(a,b) for a,b in coverage.gaps))
            skipped = sum(1 for curve, (target, *_) in zip(self.curves, assignments)
                          if "profile" in curve and target is None)
            if skipped:
                labels.append(f"{skipped} 条多段线未采用")
            self.status.setText("\n".join(labels))
        self.has_gaps=any(c.gaps for c in self.mapped.values())
        self.keep_covered.setVisible(self.has_gaps)
        if self.drawing_layout is not None:
            self.drawing_layout.set_profiles(self.curves, assignments)
            self.drawing_layout.set_current_row(self.table.currentRow())
        self._show_drawing_gaps(assignments)
        self._update_apply()

    def _update_apply(self):
        self.apply.setEnabled(bool(self.mapped) and (not self.has_gaps or self.keep_covered.isChecked()))

    def _preview(self):
        row=self.table.currentRow()
        if row<0:return
        c=self.curves[row]
        if not self.controls[row]:
            self.status.setText(c["error"])
            return
        _,unit,start,datum=self._assignments()[row]
        from 土石方计算.services.design_profiles import normalize_design_profile
        from 土石方计算.services.imported_design_profiles import prepare_imported_profile
        a,b=source_bounds(c,unit)
        def read_profiles():
            p, _ = prepare_imported_profile(normalize_design_profile(c["profile"], reference=datum),
                {"station_start": start, "station_end": start+(b-a)}, station_offset=start-a, source_units=unit)
            return [p]

        show_profile_preview(self, f"{c['source']['filename']}　{c['layer']}",
                             read_profiles, cache_key=(row, unit, start, datum),
                             station_prefix=self.network.get("station_prefix", "K"))

    def _apply(self):
        try:
            self.updated_inputs=apply_mapped_profiles(self.inputs,self.mapped,confirmed_gaps=self.keep_covered.isChecked())
        except (ValueError,OSError) as error:
            self.status.setText(str(error))
            return
        self.accept()


class _ProfileSourceForm:
    def _build_source_form(self, *, embedded):
        self._embedded = embedded
        self.inputs = {}
        self.targets = {}
        self.scopes = {}
        layout=QVBoxLayout(self)
        form=QFormLayout()
        self.object_choice=PipeObjectChoice()
        self.object_choice.setObjectName("pipeProfileObject")
        self._object_display = ChoiceDisplay(self.object_choice, wrap=True)
        form.addRow("适用范围" if embedded else "工程对象", self._object_display)
        self.current_source=QLabel()
        self.current_source.setTextFormat(Qt.PlainText)
        self.current_source.setWordWrap(True)
        form.addRow("当前采用",self.current_source)
        self.source = _SourceCombo() if embedded else _SourceChoices()
        self.source.setObjectName("pipeProfileSource")
        form.addRow("纵断面来源",self.source)
        layout.addLayout(form)
        self.dxf_row=QWidget()
        dxf=QHBoxLayout(self.dxf_row)
        dxf.setContentsMargins(0,0,0,0)
        self.files=QPushButton()
        self.files.setObjectName("pipeProfileChooseDxf")
        self.files.clicked.connect(self._choose_files)
        dxf.addWidget(self.files)
        dxf.addStretch()
        layout.addWidget(self.dxf_row)
        self.cover_row=QWidget()
        cover=QHBoxLayout(self.cover_row)
        cover.setContentsMargins(0,0,0,0)
        self.uniform_cover=QCheckBox("改用统一覆土厚度")
        cover.addWidget(self.uniform_cover)
        self.depth_label=QLabel("最小管顶覆土厚度")
        cover.addWidget(self.depth_label)
        self.depth=QDoubleSpinBox()
        self.depth.setObjectName("pipeProfileCoverDepth")
        self.depth.setToolTip("沿线原地面至管顶的最小垂直距离")
        self.depth.setDecimals(3)
        self.depth.setRange(0,10000)
        self.depth.setSuffix(" m")
        self.depth.setSingleStep(.1)
        cover.addWidget(self.depth)
        self.preview_cover = QPushButton("预览覆土纵断面")
        self.preview_cover.setObjectName("pipeProfilePreviewCover")
        self.preview_cover.clicked.connect(self._preview_cover)
        cover.addWidget(self.preview_cover)
        cover.addStretch()
        layout.addWidget(self.cover_row)
        self.preview_design=QPushButton("预览设计纵断面")
        self.preview_design.setObjectName("pipeProfilePreviewDesign")
        self.preview_design.clicked.connect(self._preview_axis)
        layout.addWidget(self.preview_design,0,Qt.AlignLeft)
        self.status=QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.confirm_water_parts=QCheckBox("仅采用已覆盖管段，所列缺口待补")
        self.confirm_water_parts.setObjectName("waterProfileAcceptCoveredRanges")
        self.confirm_water_parts.toggled.connect(self._allow_water_parts)
        layout.addWidget(self.confirm_water_parts)
        self.siphon_alignment=QPushButton("倒虹吸桩号对齐与暂列待计…")
        self.siphon_alignment.setFlat(True)
        self.siphon_alignment.setObjectName("siphonAlignmentChoices")
        self.siphon_alignment.clicked.connect(self._alignment_choices)
        layout.addWidget(self.siphon_alignment,0,Qt.AlignLeft)
        layout.addStretch()
        if embedded:
            self.cancel = QPushButton("取消修改")
            self.cancel.clicked.connect(self._cancel_changes)
            self.apply = QPushButton("采用此来源")
            self.apply.setObjectName("pipeProfileApply")
            self.apply.clicked.connect(self._adopt)
            actions = QHBoxLayout()
            actions.addStretch()
            actions.addWidget(self.cancel)
            actions.addWidget(self.apply)
            layout.addLayout(actions)
        else:
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            self.apply = buttons.button(QDialogButtonBox.Ok)
            self.apply.setText("采用此来源")
            buttons.button(QDialogButtonBox.Cancel).setText("关闭")
            buttons.accepted.connect(self._adopt)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
        self.object_choice.currentIndexChanged.connect(self._object_changed)
        self.source.changed.connect(self._source_changed)
        self.uniform_cover.toggled.connect(self._show_depth)
        return layout

    def _load_source_context(self, inputs, selected, terrain, initial_action, *, exact=False):
        self.inputs = inputs
        self.terrain = terrain
        self.updated_inputs = None
        self.cover_preview_key = None
        self.cover_preview_asset = None
        self.cover_preview_assets = {}
        self._accepted_key = None
        self.targets = profile_objects(inputs)
        scopes = profile_source_groups(inputs)
        self._preview_scope_members = ()
        if selected is not None:
            selected = tuple(selected)
            scope = source_scope_key(scopes, selected)
            if self._embedded and scope is not None:
                self._preview_scope_members = scopes[scope]
            gap = (scope is not None and selected != scope
                   and self.targets[selected][1].get("pipe_profile_choice") == "pending_gap")
            if selected in self.targets and (exact or gap):
                scopes = {selected: (self.targets[selected],)}
            else:
                selected = scope
        self.scopes = {selected: scopes[selected]} if self._embedded and selected in scopes else (
            {} if self._embedded else scopes)
        with QSignalBlocker(self.object_choice):
            self.object_choice.clear()
            for key, members in self.scopes.items():
                owner = members[0][0]
                bounds = source_scope_asset(members)
                if self._embedded:
                    start, end = bounds["station_start"], bounds["station_end"]
                    prefix = owner.get("station_prefix") or "K"
                    label = ("桩号待补" if start is None or end is None else
                             f"{format_station(start, prefix)} ～ {format_station(end, prefix)}")
                else:
                    label = _object_label(owner, bounds)
                self.object_choice.addItem(label, key)
            if selected in self.scopes:
                self.object_choice.setCurrentIndex(self.object_choice.findData(selected))
        self._object_display.refresh()
        self._object_changed()
        if initial_action in {"dxf", "cover"} and self.scopes:
            self.source.select(initial_action)

    @property
    def selected_key(self):
        return self._accepted_key or self.object_choice.currentData()

    def _members(self):
        return self.scopes[self.object_choice.currentData()]

    def _object_changed(self):
        self.source.setEnabled(bool(self.scopes))
        self.status.clear()
        if not self.scopes:
            self.current_source.setText("当前对象暂无可用纵断面")
            for w in (self.dxf_row,self.cover_row,self.preview_design,self.apply,self.confirm_water_parts,self.siphon_alignment):w.hide()
            return
        members = self._members()
        _, asset = members[0]
        self.current_source.setText(profile_scope_source_label(members, detail=True))
        self.siphon_alignment.setVisible(is_siphon_axis_asset(asset))
        self.files.setText("选择倒虹吸 DXF（可多选）" if is_siphon_axis_asset(asset) else "选择有压管道 DXF")
        depth=asset.get("construction",{}).get("cover_depth")
        self.depth.setValue(DEFAULT_WORKBENCH_COVER_M if depth is None else depth)
        constructions = [member.get("construction", {}) for _, member in members]
        depths = {c.get("cover_depth") for c in constructions}
        has_cover_settings = any(c.get("cover_segments") for c in constructions) or (
            len(depths) > 1 and all(_profile_mode(member) == "cover" for _, member in members))
        self.uniform_cover.setVisible(has_cover_settings)
        self.uniform_cover.setChecked(False)
        self._show_depth()
        with QSignalBlocker(self.source):
            modes = {_profile_mode(member) for _, member in members}
            mode = next(iter(modes)) if len(modes) == 1 else "current"
            has_current = any(member.get("design_profile") for _, member in members)
            if mode == "current" and not has_current:
                mode = ""
            available = {"dxf", "cover"}
            if all(water_axis(member) for _, member in members):
                available.add("water")
            if mode == "water_parts" or (any(member.get("water_profile_parts") for _, member in members)
                    and all(member.get("water_profile_parts") or water_axis(member) for _, member in members)):
                available.add("water_parts")
            if has_current and mode != "water":
                available.add("current")
            self.source.configure(available, mode)
        self._source_changed()

    def _source_changed(self):
        if not self.scopes:
            return
        if self._embedded:
            self._clear_inline_preview()
        mode=self.source.currentData()
        self.cover_row.setVisible(mode=="cover")
        self.dxf_row.setVisible(mode=="dxf")
        self.preview_design.setVisible(not self._embedded and mode in {"water","water_parts","current"})
        self.apply.setVisible(mode in {"water","water_parts","cover"})
        self.apply.setText("采用水面线分段" if mode=="water_parts" else "采用此来源")
        self.confirm_water_parts.setVisible(mode=="water_parts")
        with QSignalBlocker(self.confirm_water_parts):self.confirm_water_parts.setChecked(False)
        self._allow_water_parts()
        if mode=="dxf":
            _,a=self._members()[0]
            message=("可一次选择多座倒虹吸的文件，再按文件、图层和桩号核对工程对象。" if is_siphon_axis_asset(a)
                     else "同一张图中的设计线将从左到右自动分配给桩号递增的有压管段，导入前可核对和调整。")
            if self._embedded:
                message = ""
        elif mode=="water_parts":
            from 土石方计算.services.pipe_profile_sources import water_profile_spans
            spans=[span for _, asset in self._members() if asset.get("water_profile_parts")
                   for span in water_profile_spans(asset)]
            message="\n".join(("水面线已覆盖　" if kind=="mapped" else "缺口待补　")+_span(left,right)
                              for left,right,kind in spans)
        elif mode=="cover":
            if self._keep_cover_segments():
                segments = [row for _, asset in self._members() for row in self._asset_cover_segments(asset)]
                message="\n".join(f"{_span(row['station_start'],row['station_end'])}　覆土 {float(row['cover_depth']):g} m"
                                  for row in segments)
            elif not self._embedded:
                message="覆土厚度按原地面至管外顶的垂直距离填写。"
            else:
                message = ""
        else:message=""
        self.status.setText(message)
        self.status.setVisible(bool(message))
        if self._embedded and not self._loading:
            self._show_source_preview()

    def _show_depth(self):
        editable=self.uniform_cover.isHidden() or self.uniform_cover.isChecked()
        self.depth.setVisible(editable)
        self.depth_label.setVisible(editable)
        if self.source.currentData()=="cover":
            self._source_changed()

    def _keep_cover_segments(self):
        return not self.uniform_cover.isHidden() and not self.uniform_cover.isChecked()

    def _asset_cover_segments(self, asset):
        construction = asset.get("construction", {})
        depth = construction.get("cover_depth")
        return construction.get("cover_segments") or [{"station_start": asset.get("station_start"),
            "station_end": asset.get("station_end"), "cover_depth": DEFAULT_WORKBENCH_COVER_M if depth is None else depth}]

    def _cover_for_member(self, asset):
        keep = self._keep_cover_segments()
        depth = asset.get("construction", {}).get("cover_depth") if keep else self.depth.value()
        return _cover_candidate(asset, DEFAULT_WORKBENCH_COVER_M if depth is None else depth, keep_segments=keep)

    def _allow_water_parts(self):
        self.apply.setEnabled(self.source.currentData()!="water_parts" or self.confirm_water_parts.isChecked())

    def _choose_files(self):
        _,asset=self.targets[self.selected_key]
        if is_siphon_axis_asset(asset):
            paths,_=QFileDialog.getOpenFileNames(self,"选择各倒虹吸的纵断面 DXF","",DXF_PROFILE_FILTER)
        else:
            path,_=QFileDialog.getOpenFileName(self,"选择有压管道纵断面 DXF","",DXF_PROFILE_FILTER)
            paths=[path] if path else []
        if not paths:return
        dialog=DxfProfileMappingDialog(self.inputs, self.selected_key, paths, self,
                                       exact=self._embedded and self._requested_exact)
        try:
            if dialog.exec()==QDialog.Accepted and dialog.updated_inputs is not None:
                self._accept_inputs(dialog.updated_inputs)
        finally:dialog.deleteLater()

    def _preview_axis(self, *, mode=None):
        members = self._members()
        network, asset = members[0]
        mode = mode or self.source.currentData()
        preview_members = self._preview_scope_members or members
        selected_assets = {id(member) for _, member in members}
        alignments = {id(owner["alignment"]): owner["alignment"] for owner, _ in preview_members
                      if owner.get("alignment")}
        bounds = source_scope_asset(preview_members)
        station_bounds = bounds.get("station_start"), bounds.get("station_end")
        bore_profiles = []
        start, end = station_bounds
        if len(preview_members) > 1 and start is not None and end is not None:
            for bore in trenchless_exclusions(self.inputs):
                if not trenchless_intersections([bore], network, start, end):
                    continue
                if elements := bore.get("plan_elements"):
                    alignments[id(elements)] = {"elements": elements, "ip_points": [],
                                                 "start_station": elements[0]["station_start"]}
                if (mode == "current" or len(preview_members) > len(members)) and bore.get("trenchless_route_profile"):
                    bore_profiles.append(bore["trenchless_route_profile"])

        def read_profiles():
            profiles = []
            for _, member in preview_members:
                # A local source repair changes the selected member, while the chart
                # also shows the adopted design on the rest of the pipeline.
                source_mode = mode if id(member) in selected_assets else "current"
                if source_mode == "water_parts":
                    profiles.extend(profile for profile in
                                    (member.get("water_profile_parts") or [water_axis(member)]) if profile)
                else:
                    profile = water_axis(member) if source_mode == "water" else _adopted_design_profile(member)
                    if profile:
                        if self._embedded and source_mode == "current" and _profile_mode(member) == "cover":
                            profile = ProfilePreviewSeries(profile, "cover")
                        profiles.append(profile)
            if self._embedded:
                return profiles + [ProfilePreviewSeries(profile, "trenchless") for profile in bore_profiles]
            return profiles + bore_profiles

        if self._embedded:
            self._preview.prepare(read_profiles, alignment=tuple(alignments.values()) or None,
                                  terrain=self.terrain, station_prefix=network.get("station_prefix", "K"),
                                  station_bounds=station_bounds)
            self._preview.show()
            self._preview.start()
        else:
            show_profile_preview(self, _name(asset)+" · 设计纵断面", read_profiles,
                                 alignment=tuple(alignments.values()) or None, terrain=self.terrain,
                                 cache_key=(self.selected_key, mode, tuple(alignments)),
                                 station_prefix=network.get("station_prefix", "K"))

    def _alignment_choices(self):
        from .siphon_profiles_dialog import SiphonProfilesDialog
        updated=deepcopy(self.inputs)
        dialog_inputs = updated
        if self._embedded and self._requested_exact:
            owner, asset = profile_objects(updated)[self.selected_key]
            dialog_inputs = {**updated, "networks": [{**owner, "assets": [asset]}]}
        dialog = SiphonProfilesDialog(dialog_inputs, self)
        try:
            row=next((i for i,(network,asset) in enumerate(dialog.rows)
                      if profile_key(network,asset)==self.selected_key),None)
            if row is not None:dialog.table.selectRow(row)
            if dialog.exec()!=QDialog.Accepted or not dialog.changed_assets:return
            for row,target in dialog.changed_assets.items():
                _,original=dialog.rows[row]
                choice=target["siphon_axis_choice"]
                raw=(target.get("siphon_axis_input") or {}).get("source") or {}
                if choice["mode"]=="cover_depth":target["pipe_profile_choice"]="cover_depth"
                elif choice["status"] in {"actual","aligned"}:
                    if raw.get("kind")=="water_profile":
                        target["pipe_profile_choice"]="water_profile"
                        target["water_profile_design_profile"]=deepcopy(target["design_profile"])
                    else:target["pipe_profile_choice"]="quantity_dxf"
                else:target.pop("pipe_profile_choice",None)
                water=water_axis(original)
                if water:target.setdefault("water_profile_design_profile",deepcopy(water))
                original.clear()
                original.update(target)
            self._accept_inputs(updated)
        finally:dialog.deleteLater()

    def _preview_cover(self):
        self.cover_preview_key=self.selected_key
        self.cover_preview_assets = {profile_key(network, asset): self._cover_for_member(asset)
                                     for network, asset in self._members()}
        self.cover_preview_asset = self.cover_preview_assets[self.cover_preview_key]
        self._finish_selection()

    def _accept_inputs(self, updated):
        current=self.selected_key
        original=self.targets[current][1]
        targets=profile_objects(updated)
        self.updated_inputs=updated
        if current not in targets:
            root=(original.get("pipe_profile_partition") or {}).get("source_asset_id",current[1])
            self._accepted_key=next((k for k,(_,a) in targets.items() if k[0]==current[0]
                and (a.get("pipe_profile_partition") or {}).get("source_asset_id")==root
                and a.get("pipe_profile_choice")!="pending_gap"
                and original["station_start"]<=a["station_start"]<original["station_end"]),None)
        self._finish_selection()

    def _adopt(self):
        mode=self.source.currentData()
        updated=deepcopy(self.inputs)
        keys = [profile_key(*member) for member in self._members()]
        try:
            if mode=="water_parts":
                if not self.confirm_water_parts.isChecked():return
                from 土石方计算.services.pipe_profile_sources import adopt_water_profile_parts
                for key in keys:
                    network, asset = profile_objects(updated)[key]
                    if asset.get("water_profile_parts"):
                        updated = adopt_water_profile_parts(updated, network, asset)
                self._accept_inputs(updated)
                return
            if mode not in {"cover", "water"}:
                return
            targets = profile_objects(updated)
            changed = False
            for key in keys:
                _, asset = targets[key]
                target = self._adopt_member(mode, asset)
                if target is not None:
                    asset.clear()
                    asset.update(target)
                    changed = True
        except (ValueError,TypeError,KeyError) as error:
            self.status.setText(str(error))
            self.status.show()
            return
        if changed:
            self._accept_inputs(updated)
        else:
            self._finish_selection()

    def _adopt_member(self, mode, asset):
        if mode == "cover":
            construction = asset.get("construction", {})
            if (pipe_profile_choice(asset) == "cover_depth" and construction.get("burial_mode") == "cover_depth"
                    and (self._keep_cover_segments() or (construction.get("cover_depth") == self.depth.value()
                                                        and not construction.get("cover_segments")))):
                return None
            return self._cover_for_member(asset)
        profile = water_axis(asset)
        if not profile:
            raise ValueError("当前对象缺少可沿用的水面线纵断面。")
        if _profile_mode(asset) == "water" and asset.get("design_profile") == profile:
            return None
        target = deepcopy(asset)
        resolve_profile_gap(target)
        if is_siphon_axis_asset(target):
            configure_siphon_axis(target, mode="exact", profile=profile, source={"kind": "water_profile"}, strict=True)
        else:
            apply_asset_profile(target, deepcopy(profile), {"kind": "water_profile"}, axis_source="water_profile_real_elevation")
        target["pipe_profile_choice"] = "water_profile"
        return target


class PipeProfileSourcesDialog(QDialog, _ProfileSourceForm):
    def __init__(self, inputs, parent=None, *, selected=None, terrain=None, initial_action="source"):
        super().__init__(parent)
        self.setWindowTitle("管线纵断面来源")
        self.resize(690, 330)
        self._build_source_form(embedded=False)
        self._load_source_context(inputs, selected, terrain, initial_action)

    def _finish_selection(self):
        self.accept()


class PipeProfileSourcesWidget(QWidget, _ProfileSourceForm):
    """Edit the selected construction object's adopted profile in place."""

    inputs_applied = Signal(object, object)
    cover_preview_requested = Signal(object, object, object, object)
    cover_generation_requested = Signal(object)
    draft_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pipeProfileSources")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._drafts = {}
        self._loading = False
        self._requested_key = None
        self._requested_exact = False
        self._baseline = {}
        layout = self._build_source_form(embedded=True)
        self._preview = ProfilePreviewPane(self)
        self._preview.setObjectName("inlinePipeProfilePreview")
        layout.insertWidget(layout.count() - 2, self._preview, 1)
        self._preview.hide()
        self.setStyleSheet("""
            QWidget#pipeProfileSources { background:#FFFFFF; }
            QPushButton[profileControl="true"] {
                background:#FFFFFF;color:#18212E;border:1px solid #D5DEE8;
                border-radius:5px;padding:4px 8px;min-height:20px;
            }
            QPushButton[profileControl="true"]:hover {background:#F0F3F8;}
            QPushButton#pipeProfileApply {background:#3346A2;color:#FFFFFF;border-color:#3346A2;}
            QPushButton#pipeProfileApply:hover {background:#293A8E;}
            QPushButton#pipeProfileApply:disabled {background:#E9EDF4;color:#536478;border-color:#E9EDF4;}
            QPushButton[profileControl="true"]:focus {border-color:#3346A2;}
        """)
        for control in (self.files, self.apply, self.cancel, self.siphon_alignment, self.preview_cover):
            control.setProperty("profileControl", True)
        self.source.setMaximumWidth(480)
        self.source.setMinimumHeight(27)
        self.setFocusProxy(self.source)
        self.source.changed.connect(self._record_draft)
        self.depth.valueChanged.connect(self._record_draft)
        self.uniform_cover.toggled.connect(self._record_draft)
        self.set_context({})

    def set_context(self, inputs, *, selected=None, terrain=None, initial_action="source", exact=False):
        selected = tuple(selected) if selected else None
        self._requested_key = selected
        self._requested_exact = bool(exact)
        self._refresh_context(inputs, selected, terrain, initial_action)

    def showEvent(self, event):
        super().showEvent(event)
        self._show_source_preview()

    def hideEvent(self, event):
        self._clear_inline_preview()
        super().hideEvent(event)

    def _show_source_preview(self):
        if not self.isVisible() or not self.scopes:
            return
        mode = self.source.currentData()
        if mode not in {"water", "water_parts", "current"}:
            if not any(_adopted_design_profile(asset) for _, asset in self._preview_scope_members or self._members()):
                if not self.status.text():
                    waiting_for_cover = any(_profile_mode(asset) == "cover" for _, asset in self._members())
                    self.status.setText("覆土管轴待生成" if waiting_for_cover else "暂无可预览的设计纵断面")
                    self.status.show()
                return
            mode = "current"
        self._preview_axis(mode=mode)

    def _refresh_context(self, inputs, selected, terrain, initial_action="source"):
        self._loading = True
        try:
            self._clear_inline_preview()
            self._load_source_context(inputs, selected, terrain, "source", exact=self._requested_exact)
            self._baseline = self._source_values()
            draft = self._drafts.get((self.object_choice.currentData(), self._requested_exact))
            if draft is not None:
                if self.source.findData(draft["mode"]) >= 0:
                    self.source.select(draft["mode"])
                    self.uniform_cover.setChecked(draft.get("uniform", False))
                    if "depth" in draft:
                        self.depth.setValue(draft["depth"])
            elif initial_action in {"dxf", "cover"} and self.scopes:
                self.source.select(initial_action)
            self.cancel.setVisible(draft is not None)
        finally:
            self._loading = False
        self._show_source_preview()

    def _source_values(self):
        mode = self.source.currentData() or ""
        values = {"mode": mode}
        if mode == "cover":
            values.update(depth=self.depth.value(), uniform=self.uniform_cover.isChecked())
        return values

    def _record_draft(self, *_):
        key = self.object_choice.currentData()
        if self._loading or not key:
            return
        identity = key, self._requested_exact
        values = self._source_values()
        previous = self._drafts.get(identity)
        if values["mode"] in {"water", "water_parts", "cover"} and values != self._baseline:
            if self._requested_key and self._requested_key != key:
                values["member"] = self._requested_key
            self._drafts[identity] = values
        else:
            self._drafts.pop(identity, None)
        current = self._drafts.get(identity)
        self.cancel.setVisible(current is not None)
        if current != previous:
            self.draft_changed.emit()

    def _clear_inline_preview(self):
        self._preview.clear()
        self._preview.hide()

    def _cancel_changes(self):
        self.discard_draft(self.object_choice.currentData())

    def first_unapplied_edit(self, inputs=None):
        if not self._drafts:
            return None
        targets = self.targets if inputs is None else profile_objects(inputs)
        return next((key for key, _ in self._drafts if key in targets), None)

    def draft_location(self, key):
        """Return the object from which the source group draft was edited."""
        key = tuple(key) if key else None
        draft = next((values for (scope, _), values in self._drafts.items() if scope == key), {})
        return draft.get("member", key)

    def draft_is_exact(self, key):
        key = tuple(key) if key else None
        return next((exact for scope, exact in self._drafts if scope == key), False)

    def export_drafts(self):
        state = []
        for (key, exact), values in self._drafts.items():
            record = {"key": list(key), **values}
            if "member" in record:
                record["member"] = list(record["member"])
            if exact:
                record["exact"] = True
            state.append(record)
        return state

    def restore_drafts(self, state):
        self._drafts = {}
        for record in state if isinstance(state, (tuple, list)) else ():
            if not isinstance(record, dict):
                continue
            key, mode = record.get("key"), record.get("mode")
            if (not isinstance(key, (list, tuple)) or len(key) != 2
                    or not all(isinstance(part, str) for part in key)
                    or mode not in ("water", "water_parts", "cover")):
                continue
            draft = {"mode": mode}
            member = record.get("member")
            if (isinstance(member, (list, tuple)) and len(member) == 2
                    and all(isinstance(part, str) for part in member)):
                draft["member"] = tuple(member)
            if mode == "cover":
                depth = record.get("depth")
                if (not isinstance(depth, (int, float)) or isinstance(depth, bool)
                        or not 0 <= depth <= 10000 or not isfinite(depth)):
                    continue
                draft.update(depth=depth, uniform=record.get("uniform") is True)
            self._drafts[(tuple(key), record.get("exact") is True)] = draft
        self._refresh_context(self.inputs, self._requested_key, self.terrain)

    def discard_draft(self, selected, *, exact=None):
        key = tuple(selected) if selected else None
        if exact is None:
            exact = self._requested_exact
        if (key, exact) not in self._drafts and key in self.targets and not exact:
            key = source_scope_key(profile_source_groups(self.inputs), key)
        if self._drafts.pop((key, exact), None) is None:
            return
        if key == self.object_choice.currentData() and exact == self._requested_exact:
            self._refresh_context(self.inputs, self._requested_key, self.terrain)
        self.draft_changed.emit()

    def _finish_selection(self):
        if self.cover_preview_key:
            self.cover_preview_requested.emit(self.inputs, self.cover_preview_key, self.cover_preview_asset,
                                              self.cover_preview_assets)
            self.cover_preview_key = None
            return
        updated, selection = self.updated_inputs, self.selected_key
        self.discard_draft(self.object_choice.currentData())
        if updated is not None:
            self.inputs_applied.emit(updated, selection)
        elif self.source.currentData() == "cover":
            self.cover_generation_requested.emit(selection)
