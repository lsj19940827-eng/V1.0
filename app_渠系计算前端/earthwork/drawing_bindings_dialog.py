"""Review source drawing templates against actual workbench assets and ranges."""
from __future__ import annotations

from copy import deepcopy
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from 土石方计算.services.drawing_bindings import binding_candidates, list_templates


_LABELS = {
    "section.wall_thickness": "统一衬砌/墙厚", "section.wall_thickness_left": "左墙/衬砌厚度",
    "section.wall_thickness_right": "右墙/衬砌厚度", "section.base_thickness": "底板/底弧厚度",
    "section.roof_thickness": "顶板厚度", "section.inner_chamfers": "内倒角",
    "section.u_arc_angle_degrees": "U 形底弧圆心角", "section.u_side_angle_degrees": "U 形侧墙外倾角",
    "section.material_grade": "结构材料等级", "section.material_specs": "构件材料",
    "section.material":"结构主材", "section.material_specs.concrete":"结构混凝土材料", "section.material_specs.bedding":"找平/垫层材料",
    "section.structural_inner_height": "历史例图净高（仅参考）", "section.inner_width": "当前设计净宽",
    "section.inner_height": "水面线实际结构净高", "section.inner_radius": "当前设计净内半径",
    "hydraulic_height_max_m": "例图参考净高", "structural_inner_height_m": "例图参考结构净高",
    "reference_dimensions": "例图参考尺寸（不覆盖当前设计）",
    "section.component_specs": "砂浆、防渗等独立构件", "construction.bedding_thickness": "找平/垫层厚度",
    "construction.bedding_extension": "找平/垫层每侧外伸", "construction.bedding_grade": "找平/垫层材料等级",
    "path": "参数", "field": "参数", "old_value": "现值", "before": "现值",
    "new_value": "图纸值", "after": "图纸值", "value": "值", "reason": "处理依据",
    "previous": "现值", "current": "图纸值", "title": "图名",
    "name": "名称", "material": "材料", "grade": "等级", "unit": "单位",
    "component_id": "构件编号", "geometry_kind": "计量形态", "thickness_m": "厚度（m）",
    "offset_m": "外偏（m）", "after_component_id": "铺设于构件外侧", "source_handles": "原图实体编号",
    "source_sha256": "原图 SHA256", "source_identity": "原图身份", "project_name": "工程名称",
    "project_key": "工程标识", "template_id": "模板编号", "template_version": "模板版本",
    "adopted_value": "采用值", "original_value": "采用前的值", "message": "说明",
    "concrete": "混凝土", "bedding": "找平/垫层", "steel": "钢材", "mortar": "砂浆",
    "membrane": "防渗膜", "outer_offset_layer": "独立外铺材料层", "outer_surface": "实际外铺面积",
    "missing_items": "未计分项", "missing_fields": "缺少参数", "required": "所需资料",
    "mapeng": "马鹏支渠", "shihe": "石河分干渠", "left": "左干渠",
}


def _human(value):
    if value is None:
        return "未提供"
    if isinstance(value, dict):
        return "；".join(f"{_LABELS.get(str(key), str(key))}：{_human(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return "、".join(_human(item) for item in value) or "无"
    if isinstance(value, bool):
        return "是" if value else "否"
    return _LABELS.get(str(value), str(value))


def _lines(items, empty):
    if not items:
        return empty
    if not isinstance(items, (list, tuple)):
        items = [items]
    return "\n".join("• " + _human(item) for item in items)


def _status(candidate):
    if candidate.get("status") == "ready":
        return "可采用；保留用户覆盖" if candidate.get("preserved_overrides") else "可采用"
    return {"incompatible": "不适用", "needs_context": "需确认工程/施工条件"}.get(
        candidate.get("status"), "需核对")


class DrawingBindingsDialog(QDialog):
    """Return reviewed candidates; only the binding service changes engineering data.

    ``bindings`` contains the service candidates selected by the user, possibly
    narrowed to a subrange. ``project_context`` is the explicitly selected
    engineering identity, or the input's existing context. The caller persists
    that context and calls ``apply_drawing_bindings`` for the final validation.
    """

    def __init__(self, inputs, parent=None):
        super().__init__(parent)
        self.inputs = deepcopy(inputs)
        self.bindings = []
        self.project_context = deepcopy(inputs.get("drawing_project_context"))
        self.rows = []
        self.templates = list_templates()
        self.setWindowTitle("绑定真实工程断面与材料")
        self.resize(1190, 780)
        layout = QVBoxLayout(self)
        notice = QLabel("按本工程、实际对象和桩号范围选用图纸。实际净尺寸、结构高度和高程取当前水面线成果；"
                        "例图尺寸仅供参数化参考。明确匹配的构造默认采用，图纸厚度、倒角和材料参数可编辑，已有用户覆盖保留。")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        identity = QHBoxLayout()
        identity.addWidget(QLabel("本工程图纸身份"))
        self.context_choice = QComboBox()
        self.context_choice.addItem("按当前工程名称自动识别", None)
        seen = set()
        for template in self.templates:
            key = template.get("project_key")
            if not key or key in seen:
                continue
            seen.add(key)
            names = template.get("project_names") or []
            if isinstance(names, str):
                names = [names]
            title = template.get("project_name") or (names[0] if names else _LABELS.get(key,key))
            self.context_choice.addItem(str(title), key)
        if self.project_context and self.project_context.get("project_key"):
            index = self.context_choice.findData(self.project_context["project_key"])
            self.context_choice.setCurrentIndex(max(0, index))
        self.context_choice.setToolTip("只有确认属于该工程时才选用。选择工程身份后仍须逐项检查尺寸、桩号和施工条件。")
        identity.addWidget(self.context_choice)
        self.summary = QLabel()
        identity.addWidget(self.summary, 1)
        layout.addLayout(identity)
        conditions=QHBoxLayout()
        self.station_mapping=QCheckBox("已核对原图桩号与当前线路对应")
        self.station_mapping.setChecked(bool((self.project_context or {}).get("station_mapping_confirmed")))
        self.station_mapping.setToolTip("仅在已核实原图设计桩号与当前路线实际里程的对应关系后选中；否则不采用按原图桩号划分的施工分区。")
        conditions.addWidget(self.station_mapping)
        self.cover_depth_label=QLabel("已核实覆土 m")
        conditions.addWidget(self.cover_depth_label)
        self.cover_depth=QLineEdit(str((self.project_context or {}).get("cover_depth_m","")))
        self.cover_depth.setMaximumWidth(100)
        self.cover_depth.setPlaceholderText("可留空")
        conditions.addWidget(self.cover_depth)
        conditions.addStretch()
        layout.addLayout(conditions)
        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter, 1)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["采用", "工程对象", "图纸适用桩号 m", "真实断面模板", "应用范围", "检查结果"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        for column in (0, 1, 2, 5):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        splitter.addWidget(self.table)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("选中对象，查看来源、真实结构、材料等级、替换假定、用户覆盖和缺项。")
        splitter.addWidget(self.detail)
        splitter.setSizes([400, 260])
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("采用选中方案并预览")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.table.currentCellChanged.connect(lambda row, *_: self._show_detail(row))
        self.context_choice.currentIndexChanged.connect(self._context_changed)
        self.station_mapping.toggled.connect(self._context_changed)
        self.cover_depth.editingFinished.connect(self._context_changed)
        self._refresh()

    def _context_changed(self, *_):
        key = self.context_choice.currentData()
        previous = deepcopy(self.project_context or {})
        if self.sender() is self.context_choice:
            for field in ("project_key","project_identity","project_name","station_mapping_confirmed","drawing_variant","cover_depth_m","scope_confirmed"):
                previous.pop(field,None)
            for widget in (self.station_mapping,self.cover_depth):widget.blockSignals(True)
            self.station_mapping.setChecked(False);self.cover_depth.clear()
            for widget in (self.station_mapping,self.cover_depth):widget.blockSignals(False)
        if key:previous["project_key"]=key
        previous["station_mapping_confirmed"]=self.station_mapping.isChecked()
        text=self.cover_depth.text().strip()
        if text:
            try:
                depth=float(text)
                if not math.isfinite(depth) or depth<0:raise ValueError
                previous["cover_depth_m"]=depth
            except ValueError:
                self.summary.setText("覆土应为有限非负数；请核对后刷新候选。")
                self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
                return
        else:previous.pop("cover_depth_m",None)
        self.project_context=previous
        self._refresh()

    def _refresh(self):
        self.rows = []
        self.table.setRowCount(0)
        candidates = binding_candidates(self.inputs, project_context=self.project_context)
        template_projects={item["template_id"]:item.get("project_key") for item in self.templates}
        projects={template_projects.get(candidate.get("template_id")) for candidate in candidates}
        key=self.context_choice.currentData()
        if key:projects={key}
        show_all=len(projects)!=1
        self.station_mapping.setVisible(show_all or bool(projects & {"mapeng","left","shihe"}))
        for widget in (self.cover_depth_label,self.cover_depth):widget.setVisible(show_all or "shihe" in projects)
        groups = {}
        for candidate in candidates:
            key = tuple(candidate.get(field) for field in ("network_id", "asset_id", "station_start", "station_end"))
            groups.setdefault(key, []).append(candidate)
        for choices in groups.values():
            row = len(self.rows)
            applicable=[item for item in choices if item.get("auto_applicable") and item.get("status")=="ready"]
            def specificity(item):
                template=next((value for value in self.templates if value.get("template_id")==item.get("template_id")),{})
                return (bool(template.get("station_ranges")),bool(template.get("requires_station_mapping")),len(template.get("fields",{})))
            candidate=max(applicable,key=specificity) if applicable else choices[0]
            self.table.insertRow(row)
            check = QCheckBox()
            check.setChecked(bool(candidate.get("auto_applicable") and candidate.get("status") == "ready"))
            self.table.setCellWidget(row, 0, check)
            name = candidate.get("asset_name") or candidate.get("asset_id", "")
            network_name = candidate.get("network_name") or candidate.get("network_id", "")
            item = QTableWidgetItem(str(name) + ("\n" + str(network_name) if network_name else ""))
            item.setToolTip("对象编号：" + str(candidate.get("asset_id", "")))
            self.table.setItem(row, 1, item)
            self.table.setItem(row, 2, QTableWidgetItem(f"{candidate.get('station_start')} ～ {candidate.get('station_end')}"))
            choice = QComboBox()
            for option in choices:
                choice.addItem(str(option.get("title") or option["template_id"]), option)
            choice.setCurrentIndex(choices.index(candidate))
            self.table.setCellWidget(row, 3, choice)
            scope_widget = QWidget()
            scope_layout = QHBoxLayout(scope_widget)
            scope_layout.setContentsMargins(0, 0, 0, 0)
            scope = QComboBox()
            scope.addItem("候选全段", "full")
            scope.addItem("指定子段", "range")
            start = QLineEdit(str(candidate.get("station_start", "")))
            end = QLineEdit(str(candidate.get("station_end", "")))
            for field in (start, end):
                field.setMaximumWidth(100)
                field.setEnabled(False)
            scope_layout.addWidget(scope)
            scope_layout.addWidget(start)
            scope_layout.addWidget(QLabel("～"))
            scope_layout.addWidget(end)
            self.table.setCellWidget(row, 4, scope_widget)
            self.table.setItem(row, 5, QTableWidgetItem(_status(candidate)))
            record = {"choices": choices, "choice": choice, "check": check, "scope": scope, "start": start, "end": end}
            self.rows.append(record)
            check.setEnabled(candidate.get("status") == "ready")
            check.toggled.connect(self._update_summary)
            choice.currentIndexChanged.connect(lambda _, number=row: self._candidate_changed(number))
            scope.currentIndexChanged.connect(lambda _, number=row: self._scope_changed(number))
        self._update_summary()
        if self.rows:
            self.table.setCurrentCell(0, 1)
            self._show_detail(0)
        else:
            self.detail.setPlainText("当前工程没有可关联的图纸候选。请先读取水面线成果；图纸身份、断面类型及真实桩号范围须能够对应。")

    def _candidate_changed(self, row):
        record = self.rows[row]
        candidate = record["choice"].currentData()
        ready = candidate.get("status") == "ready"
        record["check"].setEnabled(ready)
        record["check"].setChecked(bool(ready and candidate.get("auto_applicable")))
        record["start"].setText(str(candidate.get("station_start", "")))
        record["end"].setText(str(candidate.get("station_end", "")))
        self.table.item(row, 5).setText(_status(candidate))
        self.table.setCurrentCell(row, 3)
        self._show_detail(row)
        self._update_summary()

    def _scope_changed(self, row):
        record = self.rows[row]
        custom = record["scope"].currentData() == "range"
        record["start"].setEnabled(custom)
        record["end"].setEnabled(custom)
        if not custom:
            candidate = record["choice"].currentData()
            record["start"].setText(str(candidate.get("station_start", "")))
            record["end"].setText(str(candidate.get("station_end", "")))

    def _update_summary(self, *_):
        selected = sum(record["check"].isChecked() for record in self.rows)
        self.summary.setText(f"{len(self.rows)} 个候选区段 · 已选 {selected} 个")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(selected > 0)

    def _show_detail(self, row):
        if not 0 <= row < len(self.rows):
            return
        candidate = self.rows[row]["choice"].currentData()
        template = next((item for item in self.templates if item.get("template_id") == candidate.get("template_id")), {})
        blocks = [
            "工程对象与范围\n"+str(candidate.get("asset_name") or candidate.get("asset_id",""))+"（"+str(candidate.get("asset_id",""))+"）\n"
                +f"图纸候选范围：{candidate.get('station_start')} ～ {candidate.get('station_end')} m；{candidate.get('scope_label','')}",
            "来源\n图纸工程："+_human(template.get("project_names") or template.get("project_name"))+"\n" + "\n".join(f"{label}：{_human(candidate.get(key) or template.get(key))}"
                for key, label in (("title", "图纸模板"), ("template_version", "版本"),
                    ("source_identity", "绑定对象来源"), ("source_sha256", "原图 SHA256"), ("source_handles", "原图实体编号"))),
            "真实结构与材料等级\n" + _lines(template.get("fields") or template.get("parameters") or template.get("values") or candidate.get("changes"), "见下方图纸参数变更。"),
            "例图尺寸（仅作参数化参考）\n"+_lines(template.get("reference_dimensions"),"本工程净尺寸、结构高度和断面角度沿用当前水面线成果。"),
            "替换现有假定\n" + _lines(candidate.get("changes"), "没有需要替换的参数。"),
            "保留用户覆盖\n" + _lines(candidate.get("preserved_overrides"), "无已有用户覆盖。"),
            "适用条件与冲突\n" + _lines(candidate.get("reasons"), "工程、断面和适用桩号检查通过。")
                + ("\n"+_lines(candidate.get("warnings"),"") if candidate.get("warnings") else ""),
            "缺项及未计分项\n" + _lines(candidate.get("missing_items") or template.get("missing_items") or template.get("missing_fields"),
                "按本模板的已明确构造计量；钢筋、接缝、附属结构等尚无完整计量规则时仍列为待补项。"),
        ]
        self.detail.setPlainText("\n\n".join(blocks))

    def accept(self):
        selected = []
        try:
            for record in self.rows:
                if not record["check"].isChecked():
                    continue
                candidate = deepcopy(record["choice"].currentData())
                if candidate.get("status") != "ready":
                    raise ValueError("存在未通过适用性检查的图纸候选。")
                start, end = float(record["start"].text()), float(record["end"].text())
                if not all(math.isfinite(value) for value in (start, end)) or start >= end:
                    raise ValueError("绑定起止桩号须为有限数字，且起桩小于止桩。")
                if start < float(candidate["station_start"]) or end > float(candidate["station_end"]):
                    raise ValueError(f"{candidate.get('asset_name', '本对象')} 的子段必须位于该图纸候选的适用桩号内。")
                candidate.update(station_start=start, station_end=end)
                selected.append(candidate)
            if not selected:
                raise ValueError("请先选择至少一个可采用的图纸候选。")
        except (TypeError, ValueError) as error:
            QMessageBox.warning(self, "绑定范围需要核对", str(error))
            return
        self.bindings = selected
        super().accept()
