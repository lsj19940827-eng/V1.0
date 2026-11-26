"""Engineering section board: source fidelity, guided ranges and isolated edits."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, Qt, QTimer, QElapsedTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout,
    QComboBox, QHeaderView, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QScrollArea,
    QSplitter, QStackedWidget, QTabWidget, QTableView, QVBoxLayout, QWidget, QPushButton,
    QFormLayout, QCheckBox, QToolButton, QTableWidget, QTableWidgetItem, QCompleter, QSizePolicy)

from app_渠系计算前端.task_runner import TaskRunner
from .section_scheme_view import SectionSchemeView, DrawingPreview
from .parameter_section_view import ParameterSectionView, supports_parameter_section

from 土石方计算.services.engineering_drawings import (
    NOTICE, DrawingLibraryError, catalog_path, list_drawings, load_evidence_texts,
)
from 土石方计算.services.section_scheme_catalog import is_selectable_section_scheme

_SAVED_SECTION_MESSAGE = "本段沿用工程已保存的构造参数。选择型号可预览新的断面。"


def _unavailable_adopted_scheme(part):
    binding = (part or {}).get("section_scheme_binding") or {}
    saved = binding.get("scheme_snapshot")
    identity = binding.get("scheme_id") or (part or {}).get("section_scheme_id")
    if not saved and not identity:
        return False
    return not is_selectable_section_scheme(saved or {"scheme_id": identity}, part.get("section_type"))


def _display(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


_STATUS_LABELS = {"verified_source": "原图已核对", "verified_drawing_fact": "图纸事实已核对",
    "conditional_rule": "有适用条件", "candidate_lookup": "候选规则，待绑定",
    "archive_unsupported": "已归档，尚未接入计算", "reference_table_only": "仅作原设计参考表",
    "needs_scope_resolution": "适用范围待核对", "conflict": "存在冲突", "pending": "待核对",
    "reference_library_only": "资料库参考，尚未绑定计算", "unbound": "尚未绑定"}


def _status(value):
    return _STATUS_LABELS.get(str(value), str(value or "未标明"))


_VALUE_LABELS = {"station_text": "原图桩号", "station_handle": "桩号实体编号", "scope": "适用条件",
    "length_m": "长度（m）", "length_handle": "长度实体编号", "parsed_station_m": "解析桩号（m）",
    "station_difference_m": "桩号差（m）", "status": "状态", "position": "图面位置",
    "handle": "原图实体编号", "source_id": "来源编号", "name": "名称", "value": "值",
    "unit": "单位", "inner_width_m": "净宽（m）", "inner_height_m": "净高（m）",
    "wall_thickness_cm": "墙厚（cm）", "base_thickness_cm": "底板厚（cm）",
    "roof_thickness_cm": "顶板厚（cm）", "note": "说明", "text": "原文"}


def _value_text(value, indent=""):
    if isinstance(value, dict):
        return "\n".join(indent + _VALUE_LABELS.get(key, str(key)) + "：" +
            (_status(item) if key == "status" else _value_text(item, indent + "  "))
            for key, item in value.items())
    if isinstance(value, list):
        return "\n".join(indent + "• " + _value_text(item, indent + "  ") for item in value)
    return _display(value)


def _facts_text(items, *, issues=False):
    if not items:
        return "暂无登记。"
    if isinstance(items, (str, dict)):
        items = [items]
    blocks = []
    for index, item in enumerate(items, 1):
        if isinstance(item, dict):
            if issues:
                lines = [_display(item.get("issue") or item.get("label") or item.get("message") or "待核对项")]
                for key, label in (("detail", "说明"), ("required", "处理要求"), ("source_id", "来源编号"),
                                   ("handles", "原图实体编号"), ("source_handles", "原图实体编号")):
                    if item.get(key):
                        lines.append(f"{label}：{_value_text(item[key])}")
            else:
                lines = [_display(item.get("label") or item.get("name") or "构造条目")]
                for key, label in (("value", "取值"), ("unit", "单位"), ("applicability", "适用条件"),
                                   ("note", "说明"), ("source_handles", "原图实体编号"), ("raw_text", "原文")):
                    if item.get(key) is not None and item.get(key) != "":
                        lines.append(f"{label}：{_value_text(item[key])}")
                if item.get("status"):
                    lines.insert(1, "状态：" + _status(item["status"]))
            blocks.append(f"{index}. " + "\n".join(lines))
        else:
            blocks.append(f"{index}. {_display(item)}")
    return "\n\n".join(blocks)


class EvidenceTextModel(QAbstractTableModel):
    HEADERS = ("布局", "原图实体编号", "图层", "实体类型", "原文")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.records = []

    def set_records(self, records):
        self.beginResetModel()
        self.records = records
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        record = self.records[index.row()]
        values = (record.get("layout", ""), record.get("handle", ""), record.get("layer", ""),
                  record.get("entity_type", record.get("type", record.get("dxftype", ""))),
                  record.get("text") or record.get("plain_text") or record.get("raw_text", ""))
        return _display(values[index.column()])

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)


_FIELD_NAMES = {
    "nominal_diameter_m": "公称DN对应直径",
    "inner_width": "净宽", "inner_height": "净高", "inner_radius": "净半径",
    "inner_diameter": "净内径", "outer_diameter": "施工外径", "wall_height": "直墙净高",
    "base_thickness": "底板厚度", "wall_thickness": "管壁厚度", "lining_thickness": "衬砌厚度",
    "wall_thickness_left": "左墙厚度", "wall_thickness_right": "右墙厚度",
    "roof_thickness": "顶板厚度", "u_bottom_thickness": "U形底弧厚度",
    "top_thickness": "顶板厚度", "side_slope": "内边坡 1:m", "inner_side_slope": "内边坡 1:m",
    "bedding_thickness": "垫层厚度", "bedding_extension": "垫层外伸",
    "working_space_left": "左工作面", "working_space_right": "右工作面",
    "excavation_slope_left": "左开挖坡比 1:m", "excavation_slope_right": "右开挖坡比 1:m",
    "excavation_clearance": "开挖预留",
    "bank_top_width_left": "左平台宽", "bank_top_width_right": "右平台宽",
    "bank_slope_left": "左填坡 1:m", "bank_slope_right": "右填坡 1:m",
    "overburden_thickness": "覆盖层竖直厚度", "shotcrete_thickness": "喷护厚度",
    "support_angle": "管床包角（°）", "width": "宽度", "height": "高度",
    "thickness": "厚度", "extension": "外伸", "pipe_count": "管道根数",
    "pipe_spacing": "管间净距", "arch_angle_degrees": "拱圆心角（°）",
    "u_angle": "U形圆弧角（°）", "bottom_radius": "底弧半径",
    "bottom_width": "底部净宽", "u_arc_angle_degrees": "U形圆弧角（°）",
    "u_side_angle_degrees": "U形直线段角（°）", "side_thickness": "侧面包封厚度",
    "bottom_thickness": "底部包封厚度", "foundation_replacement_thickness": "换填厚度",
    "foundation_replacement_width": "换填宽度", "retaining_wall_profile": "挡墙断面轮廓",
    "foundation_replacement_profile": "基础换填轮廓", "floor_steps": "开挖底部台阶",
    "discrete_components": "沿线独立构件",
    "gabion_profile": "格宾石笼断面轮廓", "fill_membrane_confirmed": "全填段防渗做法核定",
    "source_review_confirmed": "原图效力核定",
    "fill_membrane_mode": "全填段防渗做法",
    "rockfill_profile": "大块石回填轮廓",
}
_NET_FIELDS = {"inner_width", "inner_height", "inner_radius", "inner_diameter", "wall_height",
               "side_slope", "inner_side_slope", "arch_angle_degrees", "u_angle", "bottom_radius",
               "bottom_width", "u_arc_angle_degrees", "u_side_angle_degrees"}
_COMPLEX_FIELDS = {"retaining_wall_profile", "foundation_replacement_profile", "gabion_profile", "rockfill_profile", "floor_steps", "discrete_components", "fill_membrane_confirmed", "fill_membrane_mode", "source_review_confirmed"}


def _get_path(data, path, default=None):
    for key in path.split("."):
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data


def _set_path(data, path, value):
    parts = path.split(".")
    for key in parts[:-1]:
        data = data.setdefault(key, {})
    if value is None:
        data.pop(parts[-1], None)
    else:
        data[parts[-1]] = copy.deepcopy(value)


def _net_field(path):
    return path.startswith("section.") and path.split(".")[-1] in _NET_FIELDS


def _field_label(path):
    enclosure_labels = {"top_thickness": "顶部包封厚度", "bottom_thickness": "底部包封厚度",
                        "left_thickness": "左侧包封厚度", "right_thickness": "右侧包封厚度"}
    if path.startswith("construction.encasement.") and path.rsplit(".", 1)[-1] in enclosure_labels:
        return enclosure_labels[path.rsplit(".", 1)[-1]] + "（m）"
    if path == "construction.foundation_replacement.side_slope":
        return "换填收坡 1:m"
    if path == "construction.foundation_replacement_width":
        return "石渣换填上宽（m）"
    key = path.split(".")[-1]
    prefix = "管床 · " if ".pipe_seat." in path else ""
    name = _FIELD_NAMES.get(key, key)
    return prefix + name + ("（m）" if key in _FIELD_NAMES and "坡" not in name and "°" not in name and key != "pipe_count" and key not in _COMPLEX_FIELDS else "")


def _required_paths(scheme):
    required = set(scheme.get("required_fields", []))
    children = [*scheme.get("terrain_variants", {}).values(), *scheme.get("selectors", [])]
    for child in children:
        required.update(_required_paths(child))
    return required


def edit_discrete_components(parent, asset, station_prefix):
    import uuid
    from 土石方计算.services.section_scheme_bindings import format_station, parse_station

    dialog = QDialog(parent)
    dialog.setWindowTitle("支承、墩台与基础 · 按实际布置逐项设置")
    dialog.resize(1360, 720)
    layout = QVBoxLayout(dialog)
    guide = QLabel("每行是一处实际构件：纵向长度＝终点－起点，高度＝顶高程－底高程。桩号可填米数或 K0+180；高程填写绝对高程。\n只有勾选“基础挖槽”才计该处基础开挖和周边回填；选中该行后在下表填写四侧工作面及坡比。前侧为桩号减小方向，后侧为桩号增大方向。")
    guide.setWordWrap(True)
    layout.addWidget(guide)
    table = QTableWidget(0, 11)
    table.setHorizontalHeaderLabels(["构件名称", "类别", "材料", "等级", "起点桩号", "终点桩号", "横偏距 m", "横宽 m", "底高程 m", "顶高程 m", "基础挖槽"])
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    layout.addWidget(table, 1)
    actions = QHBoxLayout()
    add = QPushButton("增加一处构件")
    remove = QPushButton("删除选中构件")
    actions.addWidget(add)
    actions.addWidget(remove)
    actions.addStretch()
    layout.addLayout(actions)
    details_title = QLabel("选中一个构件，设置该构件基础四侧的开挖参数")
    layout.addWidget(details_title)
    construction = QTableWidget(4, 3)
    construction.setHorizontalHeaderLabels(["方向", "工作面宽（m）", "开挖坡比（1:m）"])
    construction.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    construction.setMaximumHeight(164)
    directions = (("left", "左侧"), ("right", "右侧"), ("front", "前侧（小桩号端）"), ("back", "后侧（大桩号端）"))
    for row, (_, name) in enumerate(directions):
        label = QTableWidgetItem(name)
        label.setFlags(Qt.ItemIsEnabled)
        construction.setItem(row, 0, label)
    layout.addWidget(construction)
    status = QLabel("未提供的构件保持缺项；不会自动补建墩台、镇墩或基础。")
    status.setWordWrap(True)
    layout.addWidget(status)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.button(QDialogButtonBox.Ok).setText("采用布置")
    buttons.button(QDialogButtonBox.Cancel).setText("取消")
    layout.addWidget(buttons)
    state = {"loading": False, "row": -1}
    def add_row(member=None):
        member = copy.deepcopy(member or {})
        member.setdefault("component_id", "member_" + uuid.uuid4().hex[:12])
        row = table.rowCount()
        table.insertRow(row)
        for column, key in ((0,"name"),(3,"grade"),(4,"station_start"),(5,"station_end"),(6,"offset"),(7,"width"),(8,"bottom_elevation"),(9,"top_elevation")):
            value = member.get(key, 0. if key == "offset" else "")
            text = format_station(value, station_prefix) if value != "" and key.startswith("station_") else str(value)
            item = QTableWidgetItem(text)
            if column == 0:
                item.setData(Qt.UserRole, member)
            table.setItem(row, column, item)
        category = QComboBox()
        for label, key in (("支承","support"),("墩台","pier"),("基础","foundation"),("镇墩","anchor"),("拉杆","tie_rod")):
            category.addItem(label,key)
        category.setCurrentIndex(max(0,category.findData(member.get("scope_category","support"))))
        table.setCellWidget(row,1,category)
        materials = QComboBox()
        for label, key in (("混凝土","concrete"),("浆砌石","masonry"),("钢材","steel")):
            materials.addItem(label,key)
        materials.setCurrentIndex(max(0,materials.findData(member.get("material","concrete"))))
        table.setCellWidget(row,2,materials)
        check = QCheckBox("计挖填")
        check.setChecked(bool(member.get("excavate")))
        table.setCellWidget(row,10,check)
        table.selectRow(row)
    def show_details(row, *_):
        state["loading"] = True
        state["row"] = row
        member = table.item(row,0).data(Qt.UserRole) if row >= 0 and table.item(row,0) else {}
        values = {**asset.get("construction", {}), **member.get("construction", {})}
        for r,(side,_) in enumerate(directions):
            for c,prefix in ((1,"working_space_"),(2,"excavation_slope_")):
                value = values.get(prefix+side)
                construction.setItem(r,c,QTableWidgetItem("" if value is None else str(value)))
        state["loading"] = False
        details_title.setText(f"第 {row+1} 行构件的基础开挖参数（不挖槽时不计）" if row >= 0 else "请选择构件")
    def store_details(item):
        row = state["row"]
        if state["loading"] or row < 0 or item.column() == 0 or not table.item(row,0):
            return
        member = table.item(row,0).data(Qt.UserRole) or {}
        side = directions[item.row()][0]
        key = ("working_space_" if item.column() == 1 else "excavation_slope_") + side
        member.setdefault("construction", {})[key] = item.text().strip()
        table.item(row,0).setData(Qt.UserRole,member)
    table.currentCellChanged.connect(show_details)
    construction.itemChanged.connect(store_details)
    add.clicked.connect(lambda: add_row())
    remove.clicked.connect(lambda: table.removeRow(table.currentRow()) if table.currentRow() >= 0 else None)
    for member in asset.get("section",{}).get("discrete_components",[]):
        add_row(member)
    if table.rowCount() == 0:
        add_row()
    def save():
        members = []
        try:
            for row in range(table.rowCount()):
                member = copy.deepcopy(table.item(row,0).data(Qt.UserRole) or {})
                member["name"] = table.item(row,0).text().strip()
                if not member["name"]:
                    raise ValueError(f"第 {row+1} 行请填写构件名称。")
                member.update(scope_category=table.cellWidget(row,1).currentData(),
                              material=table.cellWidget(row,2).currentData(),
                              grade=table.item(row,3).text().strip(),excavate=table.cellWidget(row,10).isChecked())
                for column,key in ((4,"station_start"),(5,"station_end"),(6,"offset"),(7,"width"),(8,"bottom_elevation"),(9,"top_elevation")):
                    text = table.item(row,column).text().strip()
                    try:
                        value = parse_station(text, prefix=station_prefix) if key.startswith("station_") else float(text)
                        if not math.isfinite(value):
                            raise ValueError
                    except ValueError:
                        raise ValueError(f"第 {row+1} 行的「{table.horizontalHeaderItem(column).text()}」未填完整或无法识别。") from None
                    member[key] = value
                if not asset["station_start"] <= member["station_start"] < member["station_end"] <= asset["station_end"]:
                    raise ValueError(f"第 {row+1} 行桩号须递增并位于当前应用区段内。")
                if member["width"] <= 0 or member["top_elevation"] <= member["bottom_elevation"]:
                    raise ValueError(f"第 {row+1} 行横宽必须大于零，顶高程必须高于底高程。")
                if member["excavate"]:
                    values = {**asset.get("construction", {}), **member.get("construction", {})}
                    own = member.setdefault("construction", {})
                    for side, name in directions:
                        for prefix, label in (("working_space_","工作面宽"),("excavation_slope_","开挖坡比")):
                            key=prefix+side
                            try:
                                value=float(values.get(key))
                                if not math.isfinite(value) or value<0:raise ValueError
                            except (ValueError,TypeError):
                                table.selectRow(row)
                                raise ValueError(f"第 {row+1} 行基础挖槽须补齐{name}{label}（不小于零）。") from None
                            own[key]=value
                members.append(member)
            state["members"] = members
            dialog.accept()
        except ValueError as error:
            status.setText(str(error))
            status.setStyleSheet("color:#AC4537;")
    buttons.accepted.connect(save)
    buttons.rejected.connect(dialog.reject)
    if dialog.exec() == QDialog.Accepted:
        return state.get("members")
    return None


def edit_section_profile(parent, asset, path):
    from 土石方计算.services.section_scheme_components import validate_scheme_profile, apply_scheme_profiles
    from 土石方计算.services.section_geometry import section_structure, structure_mapping, add_foundation_materials
    from shapely.geometry import mapping, LineString
    field = path.split(".")[-1]
    floor_mode = field == "floor_steps"
    value = _get_path(asset, path) or {}
    if isinstance(value, list):
        value = {"points": value}
    dialog = QDialog(parent)
    dialog.setWindowTitle(_field_label(path) + " · 按设计轮廓逐点输入")
    dialog.resize(1060, 650)
    layout = QVBoxLayout(dialog)
    guide = QLabel("单位均为米。横偏距：结构中心线为 0，左负右正。" +
        ("相对高程：当前结构、管座及垫层的最底面为 0。\n从左到右填写不闭合的槽底折线，同一横偏距可重复形成竖直台阶；不得穿入材料。" if floor_mode else
         "相对高程：当前净空内底为 0，向上为正。\n按顺时针或逆时针顺序填写顶点，程序自动闭合。原图未确定的建基位置须采用本工程设计值。") +
        ("\n只计石笼填石体积；网箱及连接件本轮未计。" if field == "gabion_profile" else ""))
    guide.setWordWrap(True)
    layout.addWidget(guide)
    material_row = QHBoxLayout()
    material_row.addWidget(QLabel("材料"))
    material = QComboBox()
    material.addItem("浆砌石", "masonry")
    material.addItem("混凝土", "concrete")
    material.addItem("石笼填石", "rockfill")
    default_material = "masonry" if field == "retaining_wall_profile" else "rockfill" if field in {"gabion_profile", "rockfill_profile"} else "concrete"
    material.setCurrentIndex(max(0, material.findData(value.get("material", default_material))))
    material_row.addWidget(material)
    material_row.addWidget(QLabel("材料等级"))
    grade = QLineEdit(str(value.get("grade") or ""))
    grade.setPlaceholderText("按本工程设计填写；缺失不猜测")
    material_row.addWidget(grade)
    material_widget = QWidget()
    material_widget.setLayout(material_row)
    material_widget.setVisible(not floor_mode)
    layout.addWidget(material_widget)
    split = QSplitter()
    layout.addWidget(split, 1)
    table_side = QWidget()
    table_layout = QVBoxLayout(table_side)
    table_layout.setContentsMargins(0, 0, 8, 0)
    points = value.get("points", [])
    table = QTableWidget(max(2 if floor_mode else 3, len(points)), 2)
    table.setHorizontalHeaderLabels(["横偏距（m）", "相对基础底高程（m）" if floor_mode else "相对内底高程（m）"])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    for row, point in enumerate(points):
        for column, coordinate in enumerate(point):
            table.setItem(row, column, QTableWidgetItem(f"{coordinate:g}"))
    table_layout.addWidget(table, 1)
    row_buttons = QHBoxLayout()
    add = QPushButton("增加顶点")
    add.clicked.connect(lambda: table.insertRow(table.rowCount()))
    remove = QPushButton("删除选中顶点")
    remove.clicked.connect(lambda: table.removeRow(table.currentRow()) if table.currentRow() >= 0 else None)
    row_buttons.addWidget(add)
    row_buttons.addWidget(remove)
    table_layout.addLayout(row_buttons)
    split.addWidget(table_side)
    view = SectionSchemeView()
    split.addWidget(view)
    split.setSizes([360, 650])
    status = QLabel("请先填写至少三个顶点；轮廓会实时显示。")
    status.setWordWrap(True)
    layout.addWidget(status)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.button(QDialogButtonBox.Ok).setText("采用轮廓")
    buttons.button(QDialogButtonBox.Cancel).setText("取消")
    layout.addWidget(buttons)
    state = {}
    def check():
        state.clear()
        try:
            coordinates = []
            for row in range(table.rowCount()):
                values = [table.item(row, c).text().strip() if table.item(row, c) else "" for c in range(2)]
                if not any(values):
                    continue
                if not all(values):
                    raise ValueError(f"第 {row+1} 点尚有空值，请把两列坐标补齐。")
                try:
                    coordinates.append([float(v) for v in values])
                except ValueError:
                    raise ValueError(f"第 {row+1} 点请填写数字，单位为米。") from None
            if floor_mode:
                if len(coordinates) < 2 or any(not math.isfinite(v) for p in coordinates for v in p):
                    raise ValueError("槽底折线至少需要两个有限数值顶点。")
                if any(b[0] < a[0] for a,b in zip(coordinates[:-1],coordinates[1:])):
                    raise ValueError("请从左到右填写，横偏距不得倒序。")
                polygon = LineString(coordinates)
                if not polygon.is_simple or polygon.length <= 1e-8:
                    raise ValueError("槽底折线自交或长度为零，请核对顶点顺序。")
                spec = {"points": coordinates, "reference": "foundation_bottom"}
            else:
                spec, polygon = validate_scheme_profile({"points": coordinates, "reference": "inner_invert",
                    "material": material.currentData(), "grade": grade.text().strip(), "name": _field_label(path)}, field=field)
            clean = copy.deepcopy(asset)
            for key in ("retaining_wall_profile", "foundation_replacement_profile", "gabion_profile", "rockfill_profile"):
                clean.setdefault("section", {}).pop(key, None)
            try:
                base = section_structure(clean, elevation=0.)
            except ValueError:
                base = None
            if base is not None:
                if floor_mode:
                    from 土石方计算.services.section_geometry import construction_floor_steps
                    structure = add_foundation_materials(base, asset.get("construction", {}))
                    line = construction_floor_steps({**asset.get("construction", {}), "floor_steps": spec}, structure)
                    if LineString(line).intersection(structure["occupancy"].buffer(-1e-8)).length > 1e-7:
                        raise ValueError("槽底折线穿入结构或材料，请将该处台阶降到材料底部以下。")
                else:
                    proposed = copy.deepcopy(asset)
                    _set_path(proposed, path, spec)
                    structure = apply_scheme_profiles(base, proposed, 0.)
                record = {"station": 0., "design_elevation": 0., "structure_geometry": structure_mapping(structure)}
            else:
                record = ({"station": 0., "design_elevation": 0.} if floor_mode else
                    {"station": 0., "design_elevation": 0., "structure_geometry": {"component_regions": {
                        spec["component_id"]: {**spec, "geometry": mapping(polygon)}}}})
            view.set_section(record)
            if floor_mode:
                view._line(line if base is not None else coordinates, "#258C81", 2.)
                view._finish()
            state["profile"] = {k: v for k, v in spec.items() if k not in {"component_id", "unit", "occupies_space"}}
            status.setText((f"折线有效 · 长度 {polygon.length:.3f} m。" if floor_mode else f"轮廓有效 · 面积 {polygon.area:.3f} m²。") + ("已核对当前结构占位。" if base is not None else "当前主体参数未齐；应用时还需核对材料占位。"))
            buttons.button(QDialogButtonBox.Ok).setEnabled(True)
        except ValueError as error:
            status.setText(str(error))
            buttons.button(QDialogButtonBox.Ok).setEnabled(False)
    table.itemChanged.connect(lambda _: check())
    material.currentIndexChanged.connect(lambda _: check())
    grade.textChanged.connect(lambda _: check())
    remove.clicked.connect(check)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    check()
    if dialog.exec() == QDialog.Accepted:
        return state.get("profile")
    return None


class EngineeringDrawingsDialog(QDialog):
    """Isolated drafts, with explicit adoption for dialog and embedded use."""

    inputs_applied = Signal(object)
    draft_changed = Signal()
    request_calculation = Signal()
    pipe_special_requested = Signal(str, str)

    def __init__(self, parent=None, *, inputs=None, preview_callback=None, library_path=None, terrain=None,
                 embedded=False, prepare_defaults=True):
        super().__init__(parent)
        self.embedded = bool(embedded)
        if self.embedded:
            self.setWindowFlags(Qt.Widget)
        self.setWindowTitle("工程断面看板 · 特殊材料按长度或桩号填写")
        self.resize(1460, 920)
        self.setMinimumSize(880, 520) if self.embedded else self.setMinimumSize(1080, 720)
        self.library_path = Path(library_path or catalog_path())
        self.scheme_path = self.library_path.with_name("section_schemes.json")
        self.updated_inputs = copy.deepcopy(inputs or {"networks": []})
        self.has_changes = False
        self._preview_callback = preview_callback
        self._terrain = terrain
        self._history = []
        self._overrides = {}
        self._parameter_edits = {}
        self._parameter_baseline = {}
        self._replacement_rows = {}
        self._parameter_actions = {}
        self._inspection_mode = False
        self._inline_parameters = False
        self._explicit_scheme = False
        self._editing_defaults_ready = False
        self.default_report = {"changed": False, "errors": []}
        self._preview_candidate = False
        self._building = False
        self._suppress_draft_changed = True
        self._closed = False
        self._epoch = 0
        self._record = None
        self._report = None
        self._preview_pending = False
        self._component_navigation_epoch = None
        self._groups = []
        self.schemes = []
        self.drawings = []
        self._visible_schemes = []
        self._active_asset_identity = None
        self.runner = TaskRunner(self)
        self.runner.running_changed.connect(self._runner_changed)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(320)
        self._debounce.timeout.connect(self._start_preview)
        self._clock = QElapsedTimer()
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(1000)
        self._progress_timer.timeout.connect(self._update_elapsed)
        self._build_ui()
        try:
            from 土石方计算.services.section_scheme_catalog import load_section_schemes
            self.schemes = load_section_schemes(self.scheme_path)
            self.drawings = list_drawings(self.library_path)
        except (ImportError, ValueError, OSError) as error:
            self.library_status.setText("断面目录未就绪：" + str(error))
        if prepare_defaults:
            self._prepare_editing_defaults()
        self._refresh_assets()
        if not self.embedded:
            self._fit_available_screen()
            self.finished.connect(self._dispose)
        self._suppress_draft_changed = False

    def _prepare_editing_defaults(self):
        from 土石方计算.services.default_section_schemes import ensure_default_section_schemes

        self.updated_inputs, self.default_report = ensure_default_section_schemes(self.updated_inputs, self.schemes)
        self._editing_defaults_ready = True
        if self.default_report["changed"]:
            self.has_changes = True
            self.notice.setText("未指定地段采用一般埋管断面。应用修改后，重新算量生成新成果。")

    def _notify_draft_changed(self):
        if not self._building and not self._suppress_draft_changed and not self._closed:
            self.draft_changed.emit()

    def set_preview_context(self, callback, terrain):
        """Replace external preview resources without rebuilding the draft form."""
        self._preview_callback = callback
        self._terrain = terrain
        self._record = None
        self._schedule_preview()

    def export_workspace_state(self):
        """Serialize the editing surface separately from adopted project inputs."""
        group = self._asset() or {}
        checked = []
        for row in range(self.ranges_table.rowCount()):
            item = self.ranges_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                part = item.data(Qt.UserRole)
                checked.append([part.get("asset_id"), part.get("station_start"), part.get("station_end")])
        state = {
            "version": 1,
            "route_id": group.get("route_id"), "group_id": group.get("asset_id"),
            "part_id": self.selected_asset_id(),
            "structure_group": self.structure_choice.currentText(),
            "scheme_id": (self._scheme() or {}).get("scheme_id"),
            "station_text": self.station_edit.text(), "side": self.side_choice.currentData(),
            "start_text": self.start_edit.text(), "end_text": self.end_edit.text(),
            "batch": self.batch_check.isChecked(), "checked_ranges": checked,
            "overrides": copy.deepcopy(self._overrides),
            "parameter_text": {path: edit.text() for path, edit in self._parameter_edits.items()
                               if path not in self._replacement_rows
                               or self._replacement_rows[path].source_record()["user_override"]},
            "parameter_baseline": copy.deepcopy(self._parameter_baseline),
            "net_override": self.net_override.isChecked(), "source_review": self.source_review.isChecked(),
            "aqueduct_component": self._aqueduct_component_kind(), "view_mode": self.view_mode.currentData(),
            "preview_candidate": self._preview_candidate,
            "explicit_scheme": self._explicit_scheme,
            "pending_draft": self.has_pending_draft(),
            "parameters_open": self.embedded or self.parameters_toggle.isChecked(),
            "ranges_open": self.embedded or self.ranges_toggle.isChecked(),
            "special_materials_workspace": self.materials_widget.export_draft(),
        }
        return json.loads(json.dumps(state, ensure_ascii=False, allow_nan=False))

    def restore_workspace_state(self, state):
        """Restore raw draft text without adopting it or invalidating results."""
        previous = self._suppress_draft_changed
        self._suppress_draft_changed = True
        try:
            return self._restore_workspace_state(state)
        finally:
            self._suppress_draft_changed = previous

    def _restore_workspace_state(self, state):
        if not isinstance(state, dict) or state.get("version") != 1 or self._closed:
            return False
        group_index = next((index for index, group in enumerate(self._groups)
            if (group["route_id"], group["asset_id"]) == (state.get("route_id"), state.get("group_id"))), None)
        if group_index is None:
            return False
        group = self._groups[group_index]
        if state.get("part_id") not in {part.get("asset_id") for part in group.get("parts", [])}:
            return False
        scheme = next((item for item in self.schemes if item.get("scheme_id") == state.get("scheme_id")
                       and item.get("structure_group", "其他结构") == state.get("structure_group")), None)
        explicit_scheme = bool(state.get("explicit_scheme", state.get("preview_candidate")))
        if (not self._inline_parameters or explicit_scheme) and not is_selectable_section_scheme(scheme, group.get("section_type")):
            return False
        texts = state.get("parameter_text")
        baseline = state.get("parameter_baseline")
        checked = state.get("checked_ranges")
        if (not isinstance(texts, dict) or not all(isinstance(key, str) and isinstance(value, str)
                for key, value in texts.items()) or not isinstance(baseline, dict)
                or not all(value is None or isinstance(value, (int, float)) for value in baseline.values())
                or not isinstance(state.get("overrides"), dict) or not isinstance(checked, list)
                or not all(isinstance(row, list) and len(row) == 3 for row in checked)
                or not all(isinstance(state.get(key), str) for key in ("station_text", "start_text", "end_text"))
                or state.get("side") not in {"left", "right"}
                or state.get("view_mode") not in {"current", "source", "model"}
                or state.get("aqueduct_component") not in {"body", "columns", "foundation"}):
            return False
        known_ranges = [[part.get("asset_id"), part.get("station_start"), part.get("station_end")]
                        for part in group.get("parts", [])]
        if any(row not in known_ranges for row in checked):
            return False
        try:
            state = json.loads(json.dumps(state, ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError):
            return False

        self._debounce.stop()
        self.runner.invalidate()
        self._record = None
        # This is intentional restoration, so bypass navigation's draft guard.
        self._active_asset_identity = group["route_id"], group["asset_id"]
        self._building = True
        self.asset_choice.setCurrentIndex(group_index)
        self._building = False
        self._asset_changed()
        self._building = True
        self.station_edit.setText(state["station_text"])
        self.side_choice.setCurrentIndex(self.side_choice.findData(state["side"]))
        self.start_edit.setText(state["start_text"])
        self.end_edit.setText(state["end_text"])
        self.batch_check.setChecked(bool(state.get("batch")))
        self.structure_choice.setCurrentIndex(self.structure_choice.findText(state["structure_group"]))
        self._building = False
        self._structure_changed(user_change=False)
        self._building = True
        self.scheme_list.setCurrentRow(next((index for index, item in enumerate(self._visible_schemes)
                                            if item.get("scheme_id") == state["scheme_id"]), -1))
        for row in range(self.ranges_table.rowCount()):
            item = self.ranges_table.item(row, 0)
            part = item.data(Qt.UserRole)
            identity = [part.get("asset_id"), part.get("station_start"), part.get("station_end")]
            item.setCheckState(Qt.Checked if identity in checked else Qt.Unchecked)
        self._overrides = copy.deepcopy(state["overrides"])
        self._preview_candidate = bool(state.get("preview_candidate"))
        self._explicit_scheme = explicit_scheme
        self._update_source_review()
        self._load_parameters(extra_fields=state["parameter_baseline"])
        self._building = True
        for path, text in state["parameter_text"].items():
            if path in self._parameter_edits:
                # Earlier drafts serialized the displayed dimensions as plain text too.
                if path in self._replacement_rows and path not in state["overrides"]:
                    old = baseline.get(path)
                    if text == ("" if old is None else f"{old:g}"):
                        continue
                self._parameter_edits[path].setText(text)
        for control in self._shared_dimensions:
            control.refresh_from_fields()
        self._parameter_baseline.update({path: value for path, value in baseline.items() if path in self._parameter_edits})
        self.net_override.setChecked(bool(state.get("net_override")))
        blocked = self.source_review.blockSignals(True)
        self.source_review.setChecked(bool(state.get("source_review")))
        self.source_review.blockSignals(blocked)
        self.aqueduct_component_choice.setCurrentIndex(self.aqueduct_component_choice.findData(state["aqueduct_component"]))
        self.view_mode.setCurrentIndex(self.view_mode.findData(state["view_mode"]))
        self.parameters_toggle.setChecked(bool(state.get("parameters_open")))
        if not self.embedded:
            self.ranges_toggle.setChecked(bool(state.get("ranges_open")))
        self._building = False
        self._net_mode_changed(self.net_override.isChecked())
        self.description.setText(str((scheme or {}).get("description") or "")[:220])
        self.description.setToolTip(str((scheme or {}).get("description") or ""))
        self._update_aqueduct_component_ui()
        if state.get("special_materials_workspace"):
            self.materials_widget.restore_draft(state["special_materials_workspace"])
        self._update_impact()
        self.notice.setStyleSheet("")
        self.notice.setText("已恢复未应用的修改，请核对后应用到指定范围。" if self.has_pending_draft()
                            else "已恢复断面工作区的查看位置与范围。")
        self._schedule_preview()
        self._component_navigation_epoch = self._epoch if self._aqueduct_component_kind() != "body" else None
        return True

    def selected_asset_id(self):
        return (self._current_part() or self._asset() or {}).get("asset_id")

    def selected_route_id(self):
        return (self._asset() or {}).get("route_id") or ""

    def select_asset(self, asset_id, *, route_id=None, drafts=None):
        """Select a root or split-part identity; retain any unapplied draft."""
        target = str(asset_id)
        for index, group in enumerate(self._groups):
            if route_id is not None and str(group["route_id"]) != str(route_id):
                continue
            part_row = next((row for row, part in enumerate(group.get("parts", []))
                             if target == str(part.get("asset_id"))), None)
            if target == str(group["asset_id"]) or part_row is not None:
                split_part = part_row is not None and target != str(group["asset_id"])
                same_group = index == self.asset_choice.currentIndex()
                identity = group["route_id"], group["asset_id"]
                if drafts is not None and identity in drafts and self.restore_workspace_state_for_switch(
                        drafts, identity, same_group):
                    return True
                if same_group and not split_part:
                    return True
                if self.embedded and self.has_pending_draft():
                    if drafts is None or same_group:
                        self._show_pending_draft()
                        return False
                    drafts[self._active_asset_identity] = self.export_workspace_state()
                    self._active_asset_identity = identity
                self.asset_choice.setCurrentIndex(index)
                if split_part:
                    self._select_range(part_row)
                return True
        return False

    def restore_workspace_state_for_switch(self, drafts, identity, same_group):
        if same_group and self.has_pending_draft():
            return False
        previous = self._active_asset_identity
        current = self.export_workspace_state() if self.has_pending_draft() else None
        if not self.restore_workspace_state(drafts[identity]):
            return False
        del drafts[identity]
        if current and previous != identity:
            drafts[previous] = current
        return True

    def set_inspection_mode(self, inspect):
        """Show the current section and adopted values before exposing editors."""
        if not self.embedded:
            return
        if inspect and self.has_pending_draft():
            self._show_pending_draft()
            return
        if not inspect and not self._editing_defaults_ready and not self._inline_parameters:
            # Section queries already apply defaults to the selected object in
            # their worker. Prepare the full editing model only on entry to edit.
            group = self._asset()
            identity = (group["route_id"], group["asset_id"]) if group else None
            part_id = self.selected_asset_id()
            station = self.station_edit.text()
            self._prepare_editing_defaults()
            self._refresh_assets(identity)
            if part_id:
                self.select_asset(part_id, route_id=identity[0] if identity else None)
            self.station_edit.setText(station)
            self._station_changed()
        self._inspection_mode = bool(inspect)
        if inspect:
            if self._aqueduct_component_kind() != "body":
                self.aqueduct_component_choice.setCurrentIndex(0)
            self.view_mode.setCurrentIndex(0)
        self._update_aqueduct_component_ui()

    def open_inline_parameters(self):
        if not self.embedded or self._inline_parameters:
            return
        self._inline_parameters = True
        self._inspection_mode = False
        self.inspection_edit.hide()
        self.section_heading.hide()
        self.asset_range.hide()
        if not self.has_pending_draft():
            if supports_parameter_section(self._current_part()):
                self.view_mode.setCurrentIndex(self.view_mode.findData("model"))
            self._update_source_review()
            self._load_parameters()
        self._update_aqueduct_component_ui()
        self._update_impact()

    def _toggle_inline_options(self, checked):
        self._update_aqueduct_component_ui()
        self.inline_options.setText("收起断面方案" if checked else "断面方案")
        if checked:
            self.main_splitter.setSizes([210, 550, 270, 0])

    def _editing_current_structure(self):
        return self._inline_parameters and not self._explicit_scheme

    def _parameter_scheme(self):
        if self._editing_current_structure():
            return ((self._current_part() or {}).get("section_scheme_binding") or {}).get("scheme_snapshot")
        return self._scheme()

    def focus_parameter(self, path):
        edit = self._parameter_edits.get(path)
        if edit is None or not edit.isEnabled():
            return False
        self.parameter_scroll.ensureWidgetVisible(edit)
        edit.setFocus()
        return True

    def _start_special_range(self):
        if self._request_focused_pipe_editor():
            return
        self.set_inspection_mode(False)
        if self._inline_parameters:
            self.inline_options.setChecked(True)
        self._add_special_range()

    def _request_focused_pipe_editor(self):
        if not self.embedded or not getattr(self, "use_focused_pipe_editor", False):
            return False
        from .pipe_special_segments import is_special_pipe_object
        group = self._asset() or {}
        if not any(is_special_pipe_object(part) for part in group.get("parts", [])):
            return False
        self.pipe_special_requested.emit(group["route_id"], group["asset_id"])
        return True

    def _update_inspection_ui(self):
        if not self.embedded:
            return
        inspect = self._inspection_mode
        inline = self._inline_parameters and not inspect
        options = self.inline_options.isChecked()
        changing = self.inspection_panel.isHidden() == inspect
        self.inspection_edit.setText("编辑断面与参数" if inspect else "查看断面")
        self.inspection_tools.setVisible(inspect)
        self.main_splitter.widget(0).setVisible(not inspect and (not inline or options))
        self.inspection_panel.setVisible(inspect)
        self.inline_options.setVisible(inline)
        self.inspection_edit.setVisible(not self._inline_parameters)
        workbench = getattr(self, "_workbench_navigation", False)
        self.asset_choice.setVisible(not inspect and not workbench)
        self.asset_choice_label.setVisible(not inspect and not workbench)
        self.inspection_object.setVisible(inspect and not workbench)
        if workbench:
            self.section_heading.setText(str((self._asset() or {}).get("name") or "施工断面"))
        self.notice.setVisible(not inspect)
        part = self._current_part() or {}
        self.inspection_special.setEnabled(bool(part))
        if inline:
            self.side_choice.setVisible(len((self._asset() or {}).get("parts", ())) > 1)
            scheme = self._parameter_scheme() or {}
            self.parameter_heading.setText(str(scheme.get("title") or "当前区段参数"))
            self.parameter_heading.setToolTip(self.parameter_heading.text())
            for control in (self.description, self.add_special_button, self.restore_default_button,
                            self.batch_check, self.ranges_toggle, self.range_panel):
                if not options:
                    control.hide()
        if not inspect:
            if changing:
                self.main_splitter.setSizes([210, 550, 270, 0])
            self.undo_button.show()
            self.discard_draft_button.show()
            return
        self.inspection_object.setText(str((self._asset() or {}).get("name") or self.asset_choice.currentText()))
        for control in (self.parameter_panel, self.materials_widget, self.ranges_toggle,
                        self.add_special_button, self.restore_default_button, self.batch_check,
                        self.range_panel, self.start_label, self.start_edit, self.start_hint,
                        self.end_label, self.end_edit, self.end_hint, self.length_hint,
                        self.impact, self.undo_button, self.impact_button, self.apply_button,
                        self.discard_draft_button, self.locate_button, self.source_review, self.description):
            control.hide()
        self.workspace_body_scroll.show()
        if changing:
            self.main_splitter.setSizes([0, 900, 0, 260])
        self._update_inspection_values()

    def _update_inspection_values(self):
        if not self._inspection_mode:
            return
        part = self._current_part() or {}
        scheme = self._scheme() or {}
        rows = []
        binding = part.get("section_scheme_binding") or {}
        adopted_scheme = binding.get("title") or (binding.get("scheme_snapshot") or {}).get("title")
        rows.append("断面方案  " + str(adopted_scheme or scheme.get("title") or "当前结构断面"))
        sources = part.get("parameter_sources") or {}
        section = part.get("section") or {}
        construction = part.get("construction") or {}
        envelope_only = section.get("earthwork_envelope_only")
        nominal = section.get("nominal_diameter_m")
        if envelope_only and nominal:
            rows.append(f"公称直径  DN{1000 * nominal:g}")
        seat = construction.get("pipe_seat") or construction.get("pipe_support") or {}
        has_seat_base = seat.get("enabled", True) and isinstance(seat.get("base_thickness"), (int, float))
        for key in ("inner_diameter", "outer_diameter", "inner_width", "inner_height",
                    "inner_radius", "bottom_width", "base_thickness", "lining_thickness",
                    "bedding_thickness", "working_space_left", "working_space_right"):
            if key in ("inner_diameter", "outer_diameter", "inner_width", "inner_height", "inner_radius", "bottom_width"):
                if not isinstance(section.get(key), (int, float)) or section[key] <= 0:
                    continue
            if key == "inner_radius" and section.get("inner_diameter"):
                continue
            if key == "inner_diameter" and envelope_only:
                continue
            if key == "bedding_thickness" and has_seat_base and not construction.get(key):
                continue
            group = "construction" if key in {"bedding_thickness", "working_space_left", "working_space_right"} else "section"
            value = (part.get(group) or {}).get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                path = f"{group}.{key}"
                source = sources.get(path)
                label = "施工占位直径" if key == "outer_diameter" and envelope_only else _field_label(path)
                rows.append(f"{label}  {value:g} m" + (f"\n{source}" if source else ""))
        if has_seat_base:
            label = "砂垫层基底厚度" if seat.get("material_role") == "bedding" else "管座基底厚度"
            rows.append(f"{label}  {seat['base_thickness']:g} m")
        self.inspection_values.setText("\n\n".join(rows))
        self.side_choice.setVisible(len((self._asset() or {}).get("parts", ())) > 1)

    def has_pending_draft(self):
        """Include unfinished/invalid text, which is absent from numeric overrides."""
        if hasattr(self, "materials_widget") and self.materials_widget.has_pending_draft():
            return True
        if self._material_length_view():
            return False
        return self._has_parameter_draft() or bool(self._preview_candidate and
            (self._scheme() or {}).get("structure_group") != "边坡支护")

    def _has_parameter_draft(self):
        if self._overrides:
            return True
        for path, edit in self._parameter_edits.items():
            if path in self._replacement_rows:
                try:
                    if self._replacement_rows[path].changes():
                        return True
                except ValueError:
                    return True
                continue
            baseline = self._parameter_baseline.get(path)
            expected = "" if baseline is None else f"{baseline:g}"
            if edit.isEnabled() and edit.text().strip() != expected:
                try:
                    if baseline is not None and float(edit.text()) == float(baseline):
                        continue
                except ValueError:
                    pass
                return True
        return False

    def _show_pending_draft(self):
        self.notice.setText("还有未应用的材料设置：请点击“应用长度材料设置”，或放弃未应用修改。" if
            self._material_length_view() else "还有未应用的修改：请先应用到上述范围，或点击“放弃未应用修改”。")
        self.notice.setStyleSheet("color:#9F5715;")
        self.discard_draft_button.setEnabled(True)

    def discard_pending_draft(self):
        """Restore adopted data without changing history or emitting a commit."""
        group = self._asset()
        identity = (group["route_id"], group["asset_id"]) if group else None
        self.materials_widget.discard_drafts()
        self._refresh_assets(identity)
        self.notice.setStyleSheet("")
        self.notice.setText("已放弃未应用修改，当前显示已采用的区段参数。")
        self.discard_draft_button.setEnabled(False)
        self._notify_draft_changed()

    def _finish_workspace(self):
        if self.has_pending_draft():
            self._show_pending_draft()
            return
        if self.embedded:
            self.request_calculation.emit()
        else:
            self.accept()

    def _emit_inputs_applied(self):
        self.notice.setStyleSheet("")
        self.discard_draft_button.setEnabled(self.has_pending_draft())
        self.inputs_applied.emit(copy.deepcopy(self.updated_inputs))

    def _fit_available_screen(self):
        screen = self.parentWidget().screen() if self.parentWidget() else self.screen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width, height = max(640, available.width() - 32), max(480, available.height() - 70)
        self.setMinimumSize(min(1080, width), min(720, height))
        self.resize(min(1460, width), min(920, height))

    def use_workbench_navigation(self):
        self._workbench_navigation = True
        self.done_button.hide()
        if not self.library_status.text().startswith("断面目录未就绪"):
            self.library_status.hide()
        self.open_inline_parameters()
        self._update_inspection_ui()

    def _build_ui(self):
        self.setStyleSheet("""
            QDialog { background:#F4F7FA; }
            QLabel { color:#253C51; }
            QLineEdit, QComboBox { min-height:26px; padding:2px 6px; }
            QPushButton { padding:6px 12px; }
            QListWidget { border:1px solid #D7E0E8; background:white; padding:4px; }
            QListWidget::item { padding:10px 7px; margin:2px; }
            QListWidget::item:selected { background:#E5F0FC; color:#164F86; border-radius:4px; }
            QToolButton { padding:5px; border:0; font-weight:600; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6) if self.embedded else root.setContentsMargins(16, 12, 16, 12)
        if self.embedded:
            root.setSpacing(4)
        title = self.section_heading = QLabel("断面与施工" if self.embedded else "工程断面看板")
        title.setStyleSheet("font-size:18px;font-weight:600;")
        header = QHBoxLayout()
        header.addWidget(title)
        self.library_status = QLabel("一般地段使用默认断面，只需添加少量特殊地段")
        self.library_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        header.addWidget(self.library_status, 1)
        header.addStretch(1)
        self.inspection_edit = QPushButton("查看断面")
        self.inspection_edit.setVisible(self.embedded)
        self.inspection_edit.clicked.connect(lambda: self.set_inspection_mode(not self._inspection_mode))
        header.addWidget(self.inspection_edit)
        self.inline_options = QPushButton("断面方案")
        self.inline_options.setCheckable(True)
        self.inline_options.hide()
        self.inline_options.toggled.connect(self._toggle_inline_options)
        root.addLayout(header)

        objects = QHBoxLayout()
        self.asset_choice_label = QLabel("工程对象")
        objects.addWidget(self.asset_choice_label)
        self.asset_choice = QComboBox()
        self.asset_choice.setMinimumWidth(200 if self.embedded else 260)
        self.asset_choice.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.asset_choice.setMinimumContentsLength(16)
        objects.addWidget(self.asset_choice, 1)
        self.inspection_object = QLabel()
        self.inspection_object.setTextFormat(Qt.PlainText)
        self.inspection_object.hide()
        objects.addWidget(self.inspection_object, 1)
        self.asset_range = QLabel()
        self.asset_range.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        objects.addWidget(self.asset_range, 1)
        objects.addWidget(QLabel("查看桩号"))
        self.station_edit = QLineEdit()
        self.station_edit.setMaximumWidth(125)
        self.station_edit.setPlaceholderText("180 或 K0+180")
        objects.addWidget(self.station_edit)
        self.side_choice = QComboBox()
        self.side_choice.addItem("分界后侧", "right")
        self.side_choice.addItem("分界前侧", "left")
        objects.addWidget(self.side_choice)
        self.locate_button = QPushButton("定位 / 局部设置")
        self.locate_button.setToolTip("定位此桩所属区段，并带入明确的起止范围；可再缩小范围。")
        objects.addWidget(self.locate_button)
        objects.addWidget(self.inline_options)
        root.addLayout(objects)
        self.station_error = QLabel()
        self.station_error.setStyleSheet("color:#AF4136;")
        self.station_error.hide()
        root.addWidget(self.station_error)

        from .special_pipe_materials_widget import SpecialPipeMaterialsWidget
        self.materials_widget = SpecialPipeMaterialsWidget(self, library_root=self.library_path.parent)
        self.materials_widget.inputs_applied.connect(self._apply_material_inputs)
        self.materials_widget.draft_changed.connect(self._material_draft_changed)
        self.materials_widget.view_mode_changed.connect(self._material_view_changed)
        self.materials_widget.soil_preview_requested.connect(self._show_material_soil_preview)
        root.addWidget(self.materials_widget)

        self.main_splitter = QSplitter()
        if self.embedded:
            # Only the editing/preview area can scroll. Range entry and the
            # adoption actions remain in the fixed lower part of the workspace.
            self.workspace_body_scroll = QScrollArea()
            self.workspace_body_scroll.setFrameShape(QScrollArea.NoFrame)
            self.workspace_body_scroll.setWidgetResizable(True)
            self.workspace_body_scroll.setMinimumHeight(140)
            self.workspace_body_scroll.setWidget(self.main_splitter)
            root.addWidget(self.workspace_body_scroll, 1)
        else:
            root.addWidget(self.main_splitter, 1)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        if self.embedded:
            left_layout.setSpacing(4)
        left_layout.addWidget(QLabel("结构形式" if self.embedded else "1  结构形式"))
        self.structure_choice = QComboBox()
        left_layout.addWidget(self.structure_choice)
        self.aqueduct_component_panel = QWidget()
        component_layout = QVBoxLayout(self.aqueduct_component_panel)
        component_layout.setContentsMargins(0, 5, 0, 0)
        component_layout.addWidget(QLabel("渡槽构件"))
        self.aqueduct_component_choice = QComboBox()
        for label, key in (("槽身", "body"), ("排架柱", "columns"), ("扩大基础", "foundation")):
            self.aqueduct_component_choice.addItem(label, key)
        component_layout.addWidget(self.aqueduct_component_choice)
        self.aqueduct_component_details = QWidget()
        component_details = QVBoxLayout(self.aqueduct_component_details)
        component_details.setContentsMargins(0, 5, 0, 5)
        self.aqueduct_component_summary = QLabel()
        self.aqueduct_component_summary.setWordWrap(True)
        component_details.addWidget(self.aqueduct_component_summary)
        self.frame_button = QPushButton("设置排架柱…")
        self.frame_button.clicked.connect(lambda: self._edit_aqueduct_frames())
        component_details.addWidget(self.frame_button)
        self.aqueduct_manual_button = QPushButton("已有构件与手工补充…")
        self.aqueduct_manual_button.clicked.connect(lambda: self._edit_discrete_components(actual=True))
        component_details.addWidget(self.aqueduct_manual_button)
        component_guide = QLabel("排架柱与扩大基础使用同一份区段布置，标高和数量联动；槽身方案单独设置。")
        component_guide.setWordWrap(True)
        component_details.addWidget(component_guide)
        component_layout.addWidget(self.aqueduct_component_details)
        left_layout.addWidget(self.aqueduct_component_panel)
        self.scheme_header = QLabel("2  工况与构造方案")
        left_layout.addWidget(self.scheme_header)
        self.scheme_list = QListWidget()
        self.drawing_list = self.scheme_list
        left_layout.addWidget(self.scheme_list, 1)
        self.support_button = QPushButton("支护类型与长度计量…")
        self.support_button.clicked.connect(self._edit_slope_support)
        left_layout.addWidget(self.support_button)
        self.dn_button = QPushButton("采用DN作为施工占位径")
        self.dn_button.setToolTip("将当前管道已有水面线管径登记为DN；明确实际外径优先，移除旧的假定壁厚扩大值。历史工程量保留待重算。")
        self.dn_button.clicked.connect(self._use_dn_envelope)
        self.dn_button.setEnabled(False)
        left_layout.addWidget(self.dn_button)
        self.terrain_hint = QLabel("填挖形式按实际地形自动判别。\n道路、水田等特殊环境可按区段指定。")
        self.terrain_hint.setWordWrap(True)
        self.terrain_hint.setStyleSheet("color:#61758A;padding:8px 2px;")
        left_layout.addWidget(self.terrain_hint)
        self.aqueduct_component_spacer = QWidget()
        left_layout.addWidget(self.aqueduct_component_spacer, 1)
        left.setMinimumWidth(190 if self.embedded else 220)
        self.main_splitter.addWidget(left)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        if self.embedded:
            center_layout.setSpacing(4)
        view_bar = QHBoxLayout()
        self.view_mode = QComboBox()
        self.view_mode.addItem("当前计算断面", "current")
        self.view_mode.addItem("原 DXF 对照", "source")
        self.view_mode.addItem("参数化断面", "model")
        if self._preview_callback is None:
            self.view_mode.setCurrentIndex(self.view_mode.findData("model"))
        view_bar.addWidget(self.view_mode)
        self.view_status = QLabel("选择工程对象以显示当前断面")
        self.view_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.view_status.setWordWrap(True)
        view_bar.addWidget(self.view_status, 1)
        for label, callback in (("−", lambda: self.preview_stack.currentWidget().zoom(1 / 1.2)),
                                ("＋", lambda: self.preview_stack.currentWidget().zoom(1.2)),
                                ("适合窗口", lambda: self.preview_stack.currentWidget().fit_to_window())):
            button = QPushButton(label)
            button.clicked.connect(callback)
            view_bar.addWidget(button)
        self.parameters_toggle = QToolButton()
        self.parameters_toggle.setText("参数")
        self.parameters_toggle.setCheckable(True)
        self.parameters_toggle.setChecked(self.embedded)
        view_bar.addWidget(self.parameters_toggle)
        center_layout.addLayout(view_bar)
        self.preview = SectionSchemeView()
        self.model_view = ParameterSectionView()
        self.model_view.parameterRequested.connect(self._focus_model_parameter)
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.preview)
        self.preview_stack.addWidget(self.model_view)
        if self.embedded:
            self.preview.setMinimumSize(300, 120)
            self.model_view.setMinimumSize(300, 120)
        center_layout.addWidget(self.preview_stack, 1)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setMaximumHeight(32 if self.embedded else 64)
        self.description.setStyleSheet("padding:5px;color:#51677B;")
        center_layout.addWidget(self.description)
        self.source_review = QCheckBox("已核定本工程可采用此原图")
        self.source_review.setStyleSheet("color:#9F5715;background:#FFF4DD;padding:6px;")
        self.source_review.hide()
        self.source_review.toggled.connect(self._source_review_changed)
        center_layout.addWidget(self.source_review)
        self.progress = QLabel()
        self.progress.setWordWrap(True)
        center_layout.addWidget(self.progress)
        self.main_splitter.addWidget(center)

        self.parameter_panel = QWidget()
        parameter_layout = QVBoxLayout(self.parameter_panel)
        parameter_layout.setContentsMargins(12, 0, 0, 0)
        if self.embedded:
            parameter_layout.setSpacing(4)
        self.parameter_heading = QLabel("当前区段参数")
        self.parameter_heading.setWordWrap(True)
        self.parameter_heading.setStyleSheet("font-weight:600;")
        parameter_layout.addWidget(self.parameter_heading)
        self.net_override = QCheckBox("手动调整净尺寸")
        self.net_override.setToolTip("未手动覆盖的净尺寸跟随水面线；手动值仅用于算量，不改水面线成果。")
        parameter_layout.addWidget(self.net_override)
        self.net_restore = QPushButton("净尺寸恢复跟随水面线")
        self.net_restore.clicked.connect(self._restore_net)
        parameter_layout.addWidget(self.net_restore)
        self.parameter_scroll = QScrollArea()
        self.parameter_scroll.setWidgetResizable(True)
        parameter_layout.addWidget(self.parameter_scroll, 1)
        parameter_actions = QHBoxLayout()
        self.structure_parameters_button = QPushButton("结构参数…")
        self.structure_parameters_button.clicked.connect(lambda: self._advanced_parameters("结构参数"))
        parameter_actions.addWidget(self.structure_parameters_button)
        self.construction_parameters_button = QPushButton("施工参数…")
        self.construction_parameters_button.clicked.connect(lambda: self._advanced_parameters("施工参数"))
        parameter_actions.addWidget(self.construction_parameters_button)
        if self.embedded:
            parameter_layout.insertLayout(3, parameter_actions)
        else:
            parameter_layout.addLayout(parameter_actions)
        self.parameter_panel.setMinimumWidth(250 if self.embedded else 270)
        self.parameter_panel.setMaximumWidth(350)
        self.main_splitter.addWidget(self.parameter_panel)
        self.parameter_panel.setVisible(self.embedded)
        self.inspection_panel = QScrollArea()
        self.inspection_panel.setWidgetResizable(True)
        self.inspection_panel.setFrameShape(QScrollArea.NoFrame)
        self.inspection_panel.setMinimumWidth(195)
        self.inspection_panel.setMaximumWidth(320)
        inspection_content = QWidget()
        inspection_layout = QVBoxLayout(inspection_content)
        inspection_layout.setContentsMargins(9, 2, 7, 4)
        current_label = QLabel("已采用参数")
        current_label.setStyleSheet("font-weight:600;")
        inspection_layout.addWidget(current_label)
        self.inspection_values = QLabel()
        self.inspection_values.setTextFormat(Qt.PlainText)
        self.inspection_values.setWordWrap(True)
        inspection_layout.addWidget(self.inspection_values)
        inspection_layout.addStretch(1)
        self.inspection_panel.setWidget(inspection_content)
        self.main_splitter.addWidget(self.inspection_panel)
        self.inspection_panel.hide()
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([210, 550, 270, 0] if self.embedded else [245, 950, 290, 0])
        self.main_splitter.setChildrenCollapsible(False)
        self.parameters_toggle.toggled.connect(lambda checked: self.parameter_panel.setVisible(
            (self.embedded or checked) and self._aqueduct_component_kind() == "body"))

        range_bar = QHBoxLayout()
        self.ranges_toggle = QToolButton()
        self.ranges_toggle.setText("桩号区段与应用范围" if self.embedded else "3  桩号区段与应用范围")
        self.ranges_toggle.setCheckable(True)
        self.ranges_toggle.setChecked(True)
        self.ranges_toggle.setArrowType(Qt.NoArrow if self.embedded else Qt.DownArrow)
        if self.embedded:
            self.ranges_toggle.setCheckable(False)
            self.ranges_toggle.setCursor(Qt.ArrowCursor)
        self.ranges_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        range_bar.addWidget(self.ranges_toggle)
        self.add_special_button = QPushButton("＋ 添加特殊地段")
        self.add_special_button.setToolTip("只填写特殊地段的起止桩号；其他范围继续使用默认断面。")
        self.add_special_button.clicked.connect(self._add_special_range)
        range_bar.addWidget(self.add_special_button)
        self.restore_default_button = QPushButton("恢复一般段")
        self.restore_default_button.setToolTip("将下方起止范围恢复为一般埋管断面，其他特殊地段保留；支持撤销。")
        self.restore_default_button.clicked.connect(self._restore_default_range)
        range_bar.addWidget(self.restore_default_button)
        range_bar.addStretch()
        self.batch_check = QCheckBox("批量应用到表内勾选区段")
        range_bar.addWidget(self.batch_check)
        root.addLayout(range_bar)
        self.range_panel = QWidget()
        range_layout = QVBoxLayout(self.range_panel)
        range_layout.setContentsMargins(0, 0, 0, 0)
        self.default_summary = QLabel()
        self.default_summary.setWordWrap(True)
        self.default_summary.setStyleSheet("color:#235D46;background:#EAF5EF;padding:4px 8px;border-radius:4px;")
        self.default_summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        range_layout.addWidget(self.default_summary)
        self.ranges_table = QTableWidget(0, 5)
        self.ranges_table.setHorizontalHeaderLabels(["选用", "起止桩号", "长度（m）", "当前方案", "状态"])
        self.ranges_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.ranges_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.ranges_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.ranges_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.ranges_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.ranges_table.setColumnWidth(0, 48)
        self.ranges_table.setColumnWidth(2, 90)
        self.ranges_table.setColumnWidth(4, 120)
        self.ranges_table.verticalHeader().hide()
        self.ranges_table.setMaximumHeight(120 if self.embedded else 148)
        self.ranges_table.setMinimumHeight(88 if self.embedded else 85)
        range_layout.addWidget(self.ranges_table)
        root.addWidget(self.range_panel)

        inputs = QHBoxLayout()
        self.start_label = QLabel("起点")
        inputs.addWidget(self.start_label)
        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText("如 180 / 0+180 / K0+180")
        inputs.addWidget(self.start_edit, 1)
        self.start_hint = QLabel()
        inputs.addWidget(self.start_hint)
        self.end_label = QLabel("终点")
        inputs.addWidget(self.end_label)
        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText("如 220 / 0+220 / K0+220")
        inputs.addWidget(self.end_edit, 1)
        self.end_hint = QLabel()
        inputs.addWidget(self.end_hint)
        self.length_hint = QLabel()
        inputs.addWidget(self.length_hint)
        root.addLayout(inputs)
        self.impact = QLabel("选择工程对象后，点击区段带入范围；输入米数即可，无需固定写法。")
        self.impact.setWordWrap(True)
        self.impact.setStyleSheet("padding:7px 10px;background:#EAF2F9;border-radius:4px;")
        root.addWidget(self.impact)

        footer = QHBoxLayout()
        self.inspection_tools = QWidget()
        inspection_tools = QHBoxLayout(self.inspection_tools)
        inspection_tools.setContentsMargins(0, 0, 0, 0)
        self.inspection_special = QPushButton("＋ 添加特殊地段")
        self.inspection_special.clicked.connect(self._start_special_range)
        inspection_tools.addWidget(self.inspection_special)
        self.inspection_tools.hide()
        footer.addWidget(self.inspection_tools)
        self.notice = QLabel("附属数量按支护清单及构件布置计算，未填项目仍列缺项。")
        self.notice.setWordWrap(True)
        self.notice.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        if self.embedded:
            root.addWidget(self.notice)
            footer.addStretch(1)
        else:
            footer.addWidget(self.notice, 1)
        self.undo_button = QPushButton("撤销本次修改")
        self.undo_button.setEnabled(False)
        footer.addWidget(self.undo_button)
        details = QPushButton("查看应用影响")
        self.impact_button = details
        details.clicked.connect(self._show_impact)
        footer.addWidget(details)
        self.apply_button = QPushButton("应用到上述范围")
        self.apply_button.setStyleSheet("background:#1965A7;color:white;font-weight:600;")
        footer.addWidget(self.apply_button)
        self.cancel_preview_button = QPushButton("取消预览")
        self.cancel_preview_button.hide()
        footer.addWidget(self.cancel_preview_button)
        self.discard_draft_button = QPushButton("放弃未应用修改")
        self.discard_draft_button.setEnabled(False)
        self.discard_draft_button.clicked.connect(self.discard_pending_draft)
        footer.addWidget(self.discard_draft_button)
        self.done_button = QPushButton("下一步：算量与成果" if self.embedded else "完成")
        footer.addWidget(self.done_button)
        cancel = QPushButton("取消")
        cancel.setVisible(not self.embedded)
        footer.addWidget(cancel)
        root.addLayout(footer)

        self.asset_choice.currentIndexChanged.connect(self._asset_changed)
        self.structure_choice.currentIndexChanged.connect(self._structure_changed)
        self.aqueduct_component_choice.currentIndexChanged.connect(self._aqueduct_component_changed)
        self.scheme_list.currentRowChanged.connect(self._scheme_changed)
        self.scheme_list.itemClicked.connect(self._activate_inline_scheme)
        self.view_mode.currentIndexChanged.connect(self._view_mode_changed)
        self.station_edit.editingFinished.connect(self._station_changed)
        self.side_choice.currentIndexChanged.connect(self._station_changed)
        self.locate_button.clicked.connect(self._locate_station)
        self.ranges_table.cellClicked.connect(self._select_range)
        self.ranges_table.itemChanged.connect(self._range_edited)
        self.start_edit.textChanged.connect(self._range_edited)
        self.end_edit.textChanged.connect(self._range_edited)
        self.batch_check.toggled.connect(self._range_edited)
        self.ranges_toggle.toggled.connect(self._toggle_ranges)
        self.net_override.toggled.connect(self._net_mode_changed)
        self.apply_button.clicked.connect(self._apply)
        self.undo_button.clicked.connect(self._undo)
        self.done_button.clicked.connect(self._finish_workspace)
        cancel.clicked.connect(self.reject)
        self.cancel_preview_button.clicked.connect(self._cancel_preview)

    def _toggle_ranges(self, checked):
        self.range_panel.setVisible((self.embedded or checked) and self._aqueduct_component_kind() == "body")
        self.ranges_toggle.setArrowType(Qt.NoArrow if self.embedded else Qt.DownArrow if checked else Qt.RightArrow)

    def _aqueduct_component_kind(self):
        return self.aqueduct_component_choice.currentData() if self.structure_choice.currentText() == "渡槽" else "body"

    def _aqueduct_component_changed(self, *_):
        if self._building:
            return
        self._update_aqueduct_component_ui()
        # Navigation queries actual adopted geometry while preserving the
        # independent, possibly unfinished body-scheme candidate and its fields.
        self._schedule_preview()
        self._component_navigation_epoch = self._epoch

    def _update_aqueduct_component_ui(self):
        aqueduct = self.structure_choice.currentText() == "渡槽"
        component = self._aqueduct_component_kind()
        body = component == "body"
        self.aqueduct_component_panel.setVisible(aqueduct)
        self.aqueduct_component_spacer.setVisible(aqueduct and not body)
        self.aqueduct_component_details.setVisible(aqueduct and not body)
        self.frame_button.setVisible(aqueduct and not body)
        self.aqueduct_manual_button.setVisible(aqueduct and not body)
        self.frame_button.setText("设置扩大基础…" if component == "foundation" else "设置排架柱…")
        self.scheme_header.setText(("" if self.embedded else "2  ") + ("槽身工况与构造方案" if aqueduct else "工况与构造方案"))
        for widget in (self.scheme_header, self.scheme_list, self.terrain_hint, self.support_button,
                       self.dn_button, self.view_mode, self.description, self.parameters_toggle,
                       self.ranges_toggle, self.add_special_button, self.restore_default_button,
                       self.batch_check, self.start_label, self.start_edit,
                       self.start_hint, self.end_label, self.end_edit, self.end_hint, self.length_hint,
                       self.impact, self.impact_button, self.apply_button, self.locate_button):
            widget.setVisible(body)
        self.parameters_toggle.setVisible(body and not self.embedded)
        self.parameter_panel.setVisible(body and (self.embedded or self.parameters_toggle.isChecked()))
        self.range_panel.setVisible(body and (self.embedded or self.ranges_toggle.isChecked()))
        self.source_review.setVisible(body and bool((self._parameter_scheme() or {}).get("source_review_required")))
        self.restore_default_button.setVisible(body and self._default_scheme() is not None)
        part = self._current_part()
        try:
            station = self._parse(self.station_edit.text())
            if not part or not part["station_start"]-1e-8 <= station <= part["station_end"]+1e-8:
                part = None
        except (TypeError, ValueError):
            part = None
        editable = bool(aqueduct and not body and part and part.get("section_type") in {"aqueduct_u", "aqueduct_rectangular"})
        self.frame_button.setEnabled(editable)
        self.aqueduct_manual_button.setEnabled(editable)
        if not editable:
            self.aqueduct_component_summary.setText("仅浏览渡槽构件分类。请先选择实际渡槽工程对象，并定位其有效桩号区段。")
        else:
            section = part.get("section", {})
            saved = section.get("aqueduct_frame_layout") or {}
            snapshot = saved.get("generated_snapshot") or {}
            members = section.get("discrete_components") or []
            columns = len(snapshot.get("columns") or [])
            foundations = sum(bool(member.get("generated_aqueduct_foundation_member")) for member in members)
            summary = (f"当前实际区段：{part.get('name') or part['asset_id']}\n"
                       f"{self._format(part['station_start'])} ～ {self._format(part['station_end'])}\n")
            summary += f"已布置排架柱 {columns} 根、扩大基础 {foundations} 座。" if saved else "尚未配置自动排架与基础布置。"
            self.aqueduct_component_summary.setText(summary)
        self._update_material_mode_ui()
        self._update_inspection_ui()

    def _material_length_view(self):
        widget = getattr(self, "materials_widget", None)
        return bool(widget and widget.group() and widget.current_mode() == "length"
                    and self._aqueduct_component_kind() == "body")

    def _update_material_mode_ui(self):
        widget = getattr(self, "materials_widget", None)
        if widget is None:
            return
        length_view = self._material_length_view()
        has_group = bool(widget.group())
        widget.setVisible((has_group or widget.has_invalid_configurations()) and self._aqueduct_component_kind() == "body")
        target = getattr(self, "workspace_body_scroll", self.main_splitter)
        if self.embedded:
            self.workspace_body_scroll.setMinimumHeight(80 if has_group else 140)
        target.setVisible(not length_view)
        if length_view:
            for control in (self.ranges_toggle, self.add_special_button, self.restore_default_button,
                    self.batch_check, self.range_panel, self.start_label, self.start_edit, self.start_hint,
                    self.end_label, self.end_edit, self.end_hint, self.length_hint, self.impact,
                    self.impact_button, self.apply_button):
                control.hide()

    def _material_view_changed(self, mode):
        if not hasattr(self, "apply_button"):
            return
        self._record = None
        self._update_aqueduct_component_ui()
        self._update_impact()
        self.discard_draft_button.setEnabled(self.has_pending_draft())
        self._schedule_preview()

    def _material_draft_changed(self):
        self.discard_draft_button.setEnabled(self.has_pending_draft())
        self._notify_draft_changed()

    def _show_material_soil_preview(self):
        if self._record is None:
            self.notice.setText("当前桩号的原土方断面尚未生成；请先导入地形或等待预览完成。长度材料设置不改变此断面。")
            self._schedule_preview()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("原土方依据断面 · 长度材料未定位到此桩号")
        dialog.resize(1150, 720)
        layout = QVBoxLayout(dialog)
        label = QLabel("查看桩号：" + self.station_edit.text() + "\n当前图以此桩号实际采用的原施工构造及真实地形为准；特殊长度材料不映射到此桩号。")
        label.setWordWrap(True)
        layout.addWidget(label)
        view = SectionSchemeView(dialog)
        view.set_section(self._record)
        layout.addWidget(view, 1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def _apply_material_inputs(self, inputs):
        if inputs == self.updated_inputs:
            return
        asset = self._asset()
        identity = (asset["route_id"], asset["asset_id"]) if asset else None
        station_draft = self.export_workspace_state() if self._has_parameter_draft() or self._preview_candidate else None
        action_notice = self.materials_widget.take_apply_notice()
        self._history.append(copy.deepcopy(self.updated_inputs))
        self.updated_inputs = copy.deepcopy(inputs)
        self.has_changes = True
        self.undo_button.setEnabled(True)
        self.materials_widget.adopt_current_group()
        self._refresh_assets(identity)
        if station_draft:
            station_draft["special_materials_workspace"] = self.materials_widget.export_draft()
            self.restore_workspace_state(station_draft)
        self.notice.setText(action_notice or "特殊材料设置已应用，需重新算量；原桩号土方依据保留，回填未随长度材料作位置修正。")
        self._emit_inputs_applied()

    def _restore_aqueduct_component(self, component):
        self.aqueduct_component_choice.blockSignals(True)
        self.aqueduct_component_choice.setCurrentIndex(max(0, self.aqueduct_component_choice.findData(component)))
        self.aqueduct_component_choice.blockSignals(False)
        self._update_aqueduct_component_ui()

    def _asset(self):
        index = self.asset_choice.currentIndex()
        return self._groups[index] if 0 <= index < len(self._groups) else None

    def _scheme(self):
        index = self.scheme_list.currentRow()
        scheme = self._visible_schemes[index] if 0 <= index < len(self._visible_schemes) else None
        if scheme and not self._preview_candidate:
            saved = ((self._current_part() or {}).get("section_scheme_binding") or {}).get("scheme_snapshot")
            if (is_selectable_section_scheme(saved, (self._asset() or {}).get("section_type"))
                    and saved.get("scheme_id") == scheme.get("scheme_id")):
                return saved
        return scheme

    def _prefix(self):
        asset = self._asset() or {}
        for network in self.updated_inputs.get("networks", []):
            if asset.get("route_id") in (network.get("route_id"), network.get("network_id")):
                return network.get("station_prefix") or "K"
        return asset.get("station_prefix") or "K"

    def _format(self, value):
        from 土石方计算.services.section_scheme_bindings import format_station
        return format_station(value, self._prefix())

    def _parse(self, text):
        from 土石方计算.services.section_scheme_bindings import parse_station
        return parse_station(text, prefix=self._prefix())

    def _refresh_assets(self, identity=None):
        from 土石方计算.services.section_scheme_bindings import list_asset_groups
        self._groups = list_asset_groups(self.updated_inputs, skip_incomplete=self.embedded)
        known = {s.get("scheme_id") for s in self.schemes}
        for group in self._groups:
            for part in group.get("parts", []):
                saved = (part.get("section_scheme_binding") or {}).get("scheme_snapshot")
                if is_selectable_section_scheme(saved, part.get("section_type")) and saved.get("scheme_id") not in known:
                    self.schemes.append(copy.deepcopy(saved))
                    known.add(saved["scheme_id"])
        self._building = True
        self.asset_choice.clear()
        for group in self._groups:
            self.asset_choice.addItem(str(group.get("route_name") or group["route_id"]) + " / " + str(group.get("name") or group["asset_id"]))
        if identity:
            for index, group in enumerate(self._groups):
                if (group["route_id"], group["asset_id"]) == identity:
                    self.asset_choice.setCurrentIndex(index)
                    break
        self._building = False
        self._asset_changed()

    def _asset_changed(self, *_):
        if self._building:
            return
        asset = self._asset()
        identity = (asset["route_id"], asset["asset_id"]) if asset else None
        previous_identity = self._active_asset_identity
        if self.embedded and previous_identity and identity != previous_identity and self.has_pending_draft():
            for index, previous in enumerate(self._groups):
                if (previous["route_id"], previous["asset_id"]) == previous_identity:
                    self.asset_choice.blockSignals(True)
                    self.asset_choice.setCurrentIndex(index)
                    self.asset_choice.blockSignals(False)
                    self._show_pending_draft()
                    return
        self._active_asset_identity = identity
        self.dn_button.setEnabled(bool(asset and asset.get("section_type") in {"circular_channel", "circular_culvert", "circular_siphon"}))
        self._overrides = {}
        self._preview_candidate = False
        self._record = None
        self._building = True
        self.structure_choice.clear()
        self._asset_schemes = [s for s in self.schemes if is_selectable_section_scheme(s, (asset or {}).get("section_type"))]
        groups = list(dict.fromkeys(s.get("structure_group", "其他结构") for s in self._asset_schemes))
        for group in groups:
            self.structure_choice.addItem(group)
        if asset:
            from 土石方计算.services.section_scheme_bindings import scheme_candidates
            candidates = scheme_candidates(asset, self.schemes)
            preferred = self._default_scheme() or (candidates[0] if candidates else None)
            current = self._current_part()
            saved = ((current or {}).get("section_scheme_binding") or {}).get("scheme_snapshot")
            if is_selectable_section_scheme(saved, asset.get("section_type")):
                preferred = saved
            if preferred:
                index = self.structure_choice.findText(preferred.get("structure_group", ""))
                self.structure_choice.setCurrentIndex(max(0, index))
            self.asset_range.setText(f"可设置范围  {self._format(asset['station_start'])} ～ {self._format(asset['station_end'])}")
            self.start_edit.setText(self._format(asset["station_start"]))
            self.end_edit.setText(self._format(asset["station_end"]))
            self.station_edit.setText(self._format((asset["station_start"] + asset["station_end"]) / 2))
            stations = sorted({float(p[k]) for p in asset.get("parts", []) for k in ("station_start", "station_end")})
            for edit in (self.start_edit, self.end_edit, self.station_edit):
                completer = QCompleter([self._format(s) for s in stations], edit)
                completer.setCaseSensitivity(Qt.CaseInsensitive)
                edit.setCompleter(completer)
        else:
            self.asset_range.setText("未加载工程 · 可浏览原图，加载水面线和地形后匹配区段")
            self.view_mode.setCurrentIndex(1)
            self.start_edit.clear()
            self.end_edit.clear()
            self.station_edit.clear()
        for widget in (self.start_edit, self.end_edit, self.station_edit, self.locate_button, self.side_choice,
                       self.batch_check, self.parameters_toggle, self.add_special_button):
            widget.setEnabled(bool(asset))
        self._building = False
        self._refresh_ranges()
        self._structure_changed(user_change=False)
        if (self._inline_parameters and previous_identity and identity != previous_identity
                and self.view_mode.currentData() == "model"):
            self._view_mode_changed()
        if self._editing_defaults_ready and not getattr(self, "_workbench_navigation", False):
            self.materials_widget.set_context(self.updated_inputs, identity, self.schemes)

    def _structure_changed(self, *_, user_change=True):
        if self._building:
            return
        self._building = True
        self.aqueduct_component_choice.blockSignals(True)
        self.aqueduct_component_choice.setCurrentIndex(0)
        self.aqueduct_component_choice.blockSignals(False)
        self.scheme_list.clear()
        group = self.structure_choice.currentText()
        self._visible_schemes = [s for s in self._asset_schemes if s.get("structure_group", "其他结构") == group]
        from .drawing_material_details import drawing_option_title
        for scheme in self._visible_schemes:
            title = drawing_option_title(scheme)
            if scheme.get("structure_group") == "边坡支护":
                title = title.replace("（本轮未计）", "（按长度计量）")
            self.scheme_list.addItem(title)
        if self._visible_schemes:
            current_type = (self._asset() or {}).get("section_type")
            selected = next((i for i, s in enumerate(self._visible_schemes) if current_type in s.get("section_types", [])), 0)
            part = self._current_part()
            binding = (part or {}).get("section_scheme_binding", {})
            scheme_id = binding.get("scheme_id") or (part or {}).get("section_scheme_id") or (self._default_scheme() or {}).get("scheme_id")
            for index, scheme in enumerate(self._visible_schemes):
                if scheme.get("scheme_id") == scheme_id:
                    selected = index
                    break
            self.scheme_list.setCurrentRow(-1 if not user_change and _unavailable_adopted_scheme(part) else selected)
        self._building = False
        self._scheme_changed(user_change=user_change)

    def _scheme_changed(self, *_, user_change=True):
        if self._building:
            return
        self._overrides = {}
        self._preview_candidate = bool(user_change and self._asset())
        self._explicit_scheme = self._preview_candidate
        self._record = None
        scheme = self._scheme()
        if scheme:
            description = str(scheme.get("description") or "")
            if scheme.get("structure_group") == "边坡支护":
                description = "按原图类型配置坡面和每延米清单，再填写长度。\n点击左侧「支护类型与长度计量」，支护独立计量，主体断面保留。"
            source = next((d.get("title", "") for d in self.drawings if d.get("drawing_id") == scheme.get("drawing_id")), "")
            self.description.setText(description[:220] + ("\n来源：" + source if source and "来源" not in description else ""))
            self.description.setToolTip(description)
        elif _unavailable_adopted_scheme(self._current_part()):
            self.description.setText(_SAVED_SECTION_MESSAGE)
            self.description.setToolTip("")
        else:
            self.description.setText("该结构暂无可选断面方案。")
            self.description.setToolTip("")
        self._update_source_review()
        self._load_parameters()
        self._update_impact()
        self._schedule_preview()
        self._update_aqueduct_component_ui()
        if user_change and self._asset():
            self._notify_draft_changed()

    def _activate_inline_scheme(self, _):
        if self._editing_current_structure() and not self.has_pending_draft():
            self._scheme_changed()

    def _update_source_review(self):
        scheme = self._parameter_scheme() or {}
        warning = scheme.get("source_review_required")
        self.source_review.blockSignals(True)
        self.source_review.setVisible(bool(warning) and self._aqueduct_component_kind() == "body")
        self.source_review.setText("原图效力待核：" + (str(warning) if isinstance(warning, str) else "原图有作废或待复核标记") + "  ｜已核定本工程可以采用")
        self.source_review.setToolTip(str(warning or ""))
        self.source_review.setChecked(bool(_get_path(self._candidate_asset(), "section.source_review_confirmed")))
        self.source_review.setEnabled(bool(self._asset()))
        self.source_review.blockSignals(False)

    def _source_review_changed(self, checked):
        self._overrides["section.source_review_confirmed"] = bool(checked)
        self._preview_candidate = True
        self._update_impact()
        self._schedule_preview()
        self._notify_draft_changed()

    def _current_part(self, station=None):
        asset = self._asset()
        if not asset:
            return None
        if station is None:
            try:
                station = self._parse(self.station_edit.text())
            except ValueError:
                station = asset["station_start"]
        parts = asset.get("parts", [])
        side = self.side_choice.currentData()
        ordered = parts if side == "left" else list(reversed(parts))
        return next((p for p in ordered if p["station_start"] - 1e-8 <= station <= p["station_end"] + 1e-8), parts[0] if parts else asset)

    def _refresh_ranges(self):
        from 土石方计算.services.special_pipe_materials import _special

        self._building = True
        parts = (self._asset() or {}).get("parts", [])
        self.ranges_table.setRowCount(len(parts))
        for row, part in enumerate(parts):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            check.setCheckState(Qt.Unchecked)
            check.setData(Qt.UserRole, part)
            self.ranges_table.setItem(row, 0, check)
            binding = part.get("section_scheme_binding") or {}
            name = (binding.get("scheme_snapshot") or {}).get("title") or binding.get("title") or binding.get("scheme_title") or part.get("section_scheme_title")
            identity = binding.get("scheme_id") or part.get("section_scheme_id")
            name = name or next((s["title"] for s in self.schemes if s["scheme_id"] == identity), self._base_section_label(part))
            if _unavailable_adopted_scheme(part):
                name = "工程已保存的构造"
            condition = (binding.get("scheme_snapshot") or {}).get("condition")
            is_general = condition == "general" and not _special(part)
            pending_default = not binding and name == "一般埋管段" and bool(self.default_report.get("errors"))
            values = (f"{self._format(part['station_start'])} ～ {self._format(part['station_end'])}",
                      f"{part['station_end']-part['station_start']:.3f}", name,
                      ("一般段 · 待重算" if self.has_changes else "一般段") if is_general else
                      (("已设置 · 待重算" if self.has_changes else "已设置") if binding else
                       "默认断面待补参" if pending_default else "默认采用"))
            for column, value in enumerate(values, 1):
                self.ranges_table.setItem(row, column, QTableWidgetItem(value))
        self._building = False
        self._refresh_default_summary()

    def _default_scheme(self):
        from 土石方计算.services.default_section_schemes import default_section_scheme
        group = self._asset() or {}
        representative = next(iter(group.get("parts", [])), group)
        return default_section_scheme(representative, self.schemes)

    @staticmethod
    def _base_section_label(part):
        from 土石方计算.services.earthwork_scope import trenchless_method
        if trenchless_method(part):
            return "非开挖段（保留原设置）"
        if not part.get("enabled", True):
            return "停用段（保留原设置）"
        mode = (part.get("construction") or {}).get("installation_mode", "buried")
        if mode in {"elevated", "above_ground"}:
            return "架空段（保留原设置）"
        if mode in {"exposed", "open"}:
            return "明管段（保留原设置）"
        if part.get("drawing_binding") or part.get("drawing_bindings"):
            return "已采用原图断面"
        if part.get("section_type") in {"circular_siphon", "circular_channel", "circular_culvert"}:
            from 土石方计算.services.default_section_schemes import needs_default_section_scheme
            if not needs_default_section_scheme(part):
                return "当前管道构造（保留原设置）"
            return "一般埋管段"
        return "当前结构断面"

    def _refresh_default_summary(self):
        group = self._asset() or {}
        default = self._default_scheme()
        from 土石方计算.services.special_pipe_materials import _special
        specials = [part for part in group.get("parts", []) if _special(part)]
        if default:
            text = f"默认：一般埋管段。未指定范围自动采用，无需逐段填写；已设特殊段 {len(specials)} 段。"
        else:
            text = "未指定范围沿用当前结构断面；只有需要不同构造的地段才填写起止桩号。"
        from 土石方计算.services.default_section_schemes import needs_default_section_scheme
        pending = [part for part in group.get("parts", []) if needs_default_section_scheme(part)]
        errors = getattr(self, "default_report", {}).get("errors", []) if pending else []
        if errors:
            text = "一般埋管默认断面尚有必要参数待补；特殊地段仍按起止桩号单独设置。 " + "；".join(str(item) for item in errors[:1])
        self.default_summary.setText(text)
        self.default_summary.setToolTip("默认断面：" + str((default or {}).get("title", "当前结构断面")) +
            "。已明确设置的方案、明管、架空、非开挖及停用段保留原设置。")
        self.restore_default_button.setEnabled(bool(group and default))

    def _sync_adopted_scheme(self, part):
        if _unavailable_adopted_scheme(part):
            self.scheme_list.blockSignals(True)
            self.scheme_list.setCurrentRow(-1)
            self.scheme_list.blockSignals(False)
            self.description.setText(_SAVED_SECTION_MESSAGE)
            self.description.setToolTip("")
            return
        binding = part.get("section_scheme_binding") or {}
        identity = binding.get("scheme_id") or part.get("section_scheme_id") or (self._default_scheme() or {}).get("scheme_id")
        scheme = next((item for item in self.schemes if item.get("scheme_id") == identity), None)
        if scheme is None:
            return
        group = self.structure_choice.findText(scheme.get("structure_group", "其他结构"))
        if group >= 0 and group != self.structure_choice.currentIndex():
            self.structure_choice.blockSignals(True)
            self.structure_choice.setCurrentIndex(group)
            self.structure_choice.blockSignals(False)
            self._structure_changed(user_change=False)
        for index, item in enumerate(self._visible_schemes):
            if item.get("scheme_id") == identity:
                self.scheme_list.blockSignals(True)
                self.scheme_list.setCurrentRow(index)
                self.scheme_list.blockSignals(False)
                break
        self.description.setText(str(scheme.get("description") or "")[:220])
        self.description.setToolTip(str(scheme.get("description") or ""))

    def _add_special_range(self):
        if self._request_focused_pipe_editor():
            return
        if not self._asset():
            return
        if self.materials_widget.group():
            self.materials_widget.select_mode("station")
        if self._has_parameter_draft():
            self._show_pending_draft()
            return
        self.ranges_toggle.setChecked(True)
        self._building = True
        self.batch_check.setChecked(False)
        for row in range(self.ranges_table.rowCount()):
            self.ranges_table.item(row, 0).setCheckState(Qt.Unchecked)
        current_type = self._asset().get("section_type")
        if not self._scheme() or self._scheme().get("condition") == "general":
            selected = next((index for index, scheme in enumerate(self._visible_schemes)
                if scheme.get("condition") != "general" and current_type in scheme.get("section_types", [])
                and scheme.get("calculation_status") != "not_in_scope"), self.scheme_list.currentRow())
            self.scheme_list.setCurrentRow(selected)
        self.start_edit.clear()
        self.end_edit.clear()
        self._building = False
        self._scheme_changed(user_change=True)
        self.notice.setText("选择特殊断面，只填本段起止桩号；应用后可继续添加下一段。其余范围自动采用默认断面。")
        self.start_edit.setFocus()

    def _restore_default_range(self):
        if not self._asset() or not self._default_scheme():
            return
        if self.has_pending_draft():
            self._show_pending_draft()
            return
        try:
            from 土石方计算.services.default_section_schemes import restore_default_section_range
            result = self.updated_inputs
            group = self._asset()
            for start, end in self._ranges():
                result = restore_default_section_range(result, route_id=group["route_id"],
                    asset_id=group["asset_id"], station_start=start, station_end=end, schemes=self.schemes)
        except (ValueError, TypeError, KeyError) as error:
            self.impact.setText("未恢复：" + self._friendly_error(error))
            return
        self._history.append(copy.deepcopy(self.updated_inputs))
        self.updated_inputs = result
        self.has_changes = True
        self.undo_button.setEnabled(True)
        self._refresh_assets((group["route_id"], group["asset_id"]))
        self.notice.setText("所选范围已恢复一般埋管段，其他特殊段保留；正式工程量需重新计算。")
        self._emit_inputs_applied()

    def _select_range(self, row, column=1):
        if self._building or column == 0:
            return
        if self.embedded and self.has_pending_draft():
            self._show_pending_draft()
            return
        item = self.ranges_table.item(row, 0)
        if item is None:
            return
        part = item.data(Qt.UserRole)
        self._building = True
        self.start_edit.setText(self._format(part["station_start"]))
        self.end_edit.setText(self._format(part["station_end"]))
        self.station_edit.setText(self._format((part["station_start"] + part["station_end"]) / 2))
        self._building = False
        self._overrides = {}
        self._preview_candidate = False
        self._explicit_scheme = False
        self._sync_adopted_scheme(part)
        self._load_parameters()
        scheme = self._scheme() or {}
        description = str(scheme.get("description") or "")
        self.description.setText(_SAVED_SECTION_MESSAGE if _unavailable_adopted_scheme(part) else description[:220])
        self._update_source_review()
        self._update_impact()
        self._schedule_preview()

    def _station_changed(self, *_):
        if self._building:
            return
        self._record = None
        if not self.has_pending_draft() and self._aqueduct_component_kind() == "body" and self._current_part():
            self._sync_adopted_scheme(self._current_part())
        if not (self.embedded and self.has_pending_draft()):
            self._load_parameters()
        self._update_inspection_values()
        self._schedule_preview()

    def _locate_station(self):
        station = self._valid_station()
        if station is None:
            return
        if self.has_pending_draft():
            self._show_pending_draft()
            return
        part = self._current_part(station)
        if part and part["station_start"] - 1e-8 <= station <= part["station_end"] + 1e-8:
            self._building = True
            self.start_edit.setText(self._format(part["station_start"]))
            self.end_edit.setText(self._format(part["station_end"]))
            self._building = False
            self._sync_adopted_scheme(part)
            self._load_parameters()
            self._update_impact()
            self._schedule_preview()
            self.start_edit.setFocus()
            self.start_edit.selectAll()
        else:
            self.station_error.setText("此桩号位于已有区段之间。请从区段表选择要设置的范围。")
            self.station_error.show()

    def _valid_station(self):
        asset = self._asset()
        if not asset:
            return None
        try:
            station = self._parse(self.station_edit.text())
            if not asset["station_start"] <= station <= asset["station_end"]:
                raise ValueError("查看桩号超出当前对象范围，请在上方可设置范围内选择。")
        except ValueError as error:
            self.station_error.setText(str(error))
            self.station_error.show()
            return None
        self.station_error.hide()
        return station

    def _ranges(self):
        if self.batch_check.isChecked():
            ranges = []
            for row in range(self.ranges_table.rowCount()):
                item = self.ranges_table.item(row, 0)
                if item.checkState() == Qt.Checked:
                    part = item.data(Qt.UserRole)
                    ranges.append((part["station_start"], part["station_end"]))
            if not ranges:
                raise ValueError("请在区段表第一列勾选要批量应用的区段。")
            return ranges
        start = self._parse(self.start_edit.text())
        end = self._parse(self.end_edit.text())
        if end <= start:
            raise ValueError("终点必须大于起点；单桩定位后也需要明确一个有长度的范围。")
        return [(start, end)]

    def _range_edited(self, *_):
        if self._building:
            return
        self._notify_draft_changed()
        self._update_impact()
        if self._preview_candidate:
            try:
                ranges = self._ranges()
                station = self._parse(self.station_edit.text())
                if not any(start <= station <= end for start, end in ranges):
                    start, end = ranges[0]
                    self.station_edit.setText(self._format((start + end) / 2))
                    self._record = None
            except ValueError:
                pass
            self._schedule_preview()

    def _update_impact(self):
        self._report = None
        self.apply_button.setEnabled(False)
        pending = self.has_pending_draft()
        self.discard_draft_button.setEnabled(pending)
        editing_current = self._editing_current_structure()
        for control in (self.structure_choice, self.scheme_list, self.add_special_button):
            control.setEnabled(not (editing_current and pending))
        self.apply_button.setText("应用到上述范围" if self._preview_candidate or editing_current else "预览所选方案")
        asset, scheme = self._asset(), self._parameter_scheme()
        self.restore_default_button.setEnabled(bool(asset and self._default_scheme() and not self.has_pending_draft()))
        if scheme and scheme.get("structure_group") == "边坡支护":
            self.impact.setText("支护使用独立长度清单；点击左侧「支护类型与长度计量」，无需替换主体断面或填写主结构桩号。")
            self.length_hint.clear()
            return
        for edit, hint in ((self.start_edit, self.start_hint), (self.end_edit, self.end_hint)):
            try:
                value = self._parse(edit.text())
                if asset and not asset["station_start"] <= value <= asset["station_end"]:
                    raise ValueError("超出对象范围")
                hint.setText(self._format(value))
                hint.setStyleSheet("color:#56788C;")
                edit.setStyleSheet("")
            except ValueError as error:
                hint.setText("请输入桩号" if not edit.text().strip() else str(error))
                hint.setStyleSheet("color:#AE493D;")
                edit.setStyleSheet("border:1px solid #CF8A7E;" if edit.text() else "")
        if not asset:
            self.impact.setText("未加载工程。可查看原图；加载工程后再指定桩号范围。")
            self.length_hint.clear()
            return
        if not scheme and not editing_current:
            self.impact.setText("请选择与当前工程对象对应的断面方案。")
            return
        if not self._preview_candidate and not self.has_pending_draft():
            self.impact.setText("修改参数后应用到所填桩号范围。" if editing_current else
                                "当前显示已采用的断面。无需特殊设置时可直接算量；有特殊地段时点击“添加特殊地段”，只填写该段起止桩号。")
            self.length_hint.clear()
            self.apply_button.setEnabled(not editing_current)
            return
        if not self.batch_check.isChecked() and (not self.start_edit.text().strip() or not self.end_edit.text().strip()):
            self.impact.setText("请填写应用参数的起止桩号。" if editing_current else
                                f"为「{scheme['title']}」填写特殊地段的起止桩号，例如 180 和 220；其余范围继续采用默认断面。")
            self.length_hint.clear()
            return
        try:
            ranges = self._ranges()
            overrides = self._collect_overrides()
            from 土石方计算.services.section_scheme_bindings import edit_current_section_parameters, preview_scheme_application
            reports = []
            for start, end in ranges:
                arguments = dict(route_id=asset["route_id"], asset_id=asset["asset_id"],
                                 station_start=start, station_end=end, overrides=overrides)
                if editing_current:
                    _, report = edit_current_section_parameters(self.updated_inputs, **arguments)
                else:
                    report = preview_scheme_application(self.updated_inputs, scheme=scheme, **arguments)
                reports.append(report)
            errors = [self._friendly_error(e) for report in reports for e in report.get("errors", [])]
            total = sum(end - start for start, end in ranges)
            self.length_hint.setText(f"共 {total:g} m" + (f" / {len(ranges)} 段" if len(ranges) > 1 else ""))
            if errors or any(not r.get("valid") for r in reports):
                self.impact.setText("请先修正：" + "；".join(errors[:3]))
                if self._preview_candidate and any("补齐参数" in error for error in errors):
                    self.parameters_toggle.setChecked(True)
                return
            text = (f"将 {self._format(ranges[0][0])} ～ {self._format(ranges[0][1])}" if len(ranges) == 1 else
                    f"将勾选的 {len(ranges)} 个区段") + f"，共 {total:g} m"
            text += "，应用当前参数修改。" if editing_current else f"，设为「{scheme['title']}」。"
            replaced_rows = [r for report in reports for r in report.get("replaced_ranges", []) if r.get("scheme_id")]
            replaced = len(replaced_rows)
            if replaced:
                examples = [f"{self._format(r['station_start'])}～{self._format(r['station_end'])}「{r.get('title', '')}」" for r in replaced_rows[:2]]
                text += f"\n替换 {replaced} 处：" + "、".join(examples) + "；未覆盖部分保留。"
            warnings = list(dict.fromkeys(str(w) for r in reports for w in r.get("warnings", [])))
            pending = list(dict.fromkeys("实际判为" + item.get("label", "对应工况") + "时需" +
                "、".join(_field_label(path) for path in item.get("fields", []))
                for report in reports for item in report.get("pending_terrain_requirements", [])))
            if pending:
                text += "\n" + "；".join(pending[:2])
            elif warnings:
                text += "\n" + "；".join(warnings[:2])
            self.impact.setToolTip("\n".join(warnings + pending))
            self.impact.setText(text)
            self._report = reports
            self.apply_button.setEnabled(True)
        except (ValueError, TypeError, KeyError) as error:
            self.impact.setText(self._friendly_error(error))
            self.length_hint.clear()

    def _friendly_error(self, error):
        text = str(error)
        paths = set(self._parameter_edits) | _required_paths(self._scheme() or {})
        for path in sorted(paths, key=len, reverse=True):
            text = text.replace(path, _field_label(path))
        return text

    def _show_impact(self):
        self._update_impact()
        if not self._report:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("应用影响 · 核对后返回看板应用")
        dialog.resize(850, 470)
        layout = QVBoxLayout(dialog)
        summary = QLabel(self.impact.text())
        summary.setWordWrap(True)
        layout.addWidget(summary)
        rows = []
        for report in self._report:
            for item in report.get("replaced_ranges", []):
                rows.append((f"{self._format(item['station_start'])}～{self._format(item['station_end'])}",
                             "断面方案", item.get("title", "未匹配"), self._scheme()["title"]))
            for item in report.get("field_changes", []):
                rows.append((f"{self._format(item['station_start'])}～{self._format(item['station_end'])}",
                             _field_label(item["field"]), _display(item.get("before")), _display(item.get("after"))))
            for item in report.get("preserved_ranges", []):
                rows.append((f"{self._format(item['station_start'])}～{self._format(item['station_end'])}", "范围保留", "原设置", "保持原设置"))
        table = QTableWidget(len(rows), 4)
        table.setHorizontalHeaderLabels(["桩号范围", "内容", "应用前", "应用后"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value)))
        layout.addWidget(table, 1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def _candidate_asset(self):
        if self._record is not None and self._record.get("effective_asset"):
            try:
                station = self._parse(self.station_edit.text())
                if abs(float(self._record["station"]) - station) < 1e-8:
                    effective = copy.deepcopy(self._current_part() or {})
                    computed = self._record["effective_asset"]
                    for root in ("section", "construction"):
                        for key, value in computed.get(root, {}).items():
                            if key not in {"discrete_components", "quantity_rules"}:
                                effective.setdefault(root, {})[key] = copy.deepcopy(value)
                    for path, value in self._overrides.items():
                        if value is not None:
                            _set_path(effective, path, value)
                    return effective
            except (ValueError, KeyError, TypeError):
                pass
        part = copy.deepcopy(self._current_part() or {})
        if self._editing_current_structure() and self._preview_candidate and part:
            from 土石方计算.services.section_scheme_bindings import draft_current_section_parameters
            return draft_current_section_parameters(part, self._overrides)[0]
        if self._preview_candidate:
            try:
                from 土石方计算.services.section_scheme_bindings import preview_scheme_application
                asset = self._asset()
                start, end = self._ranges()[0]
                report = preview_scheme_application(self.updated_inputs, route_id=asset["route_id"],
                    asset_id=asset["asset_id"], scheme=self._parameter_scheme(), station_start=start,
                    station_end=end, overrides=self._overrides)
                if report.get("valid") and report.get("affected_parts"):
                    station = self._parse(self.station_edit.text())
                    parts = report["affected_parts"]
                    return copy.deepcopy(next((p for p in parts if p["station_start"] <= station <= p["station_end"]), parts[0]))
            except (ValueError, TypeError, KeyError):
                pass
            scheme = self._parameter_scheme() or {}
            if part and part.get("section_type") in scheme.get("section_types", ()):
                from 土石方计算.services.section_scheme_bindings import draft_section_scheme_fields
                try:
                    return draft_section_scheme_fields(part, scheme, self._overrides)[0]
                except (ValueError, TypeError, KeyError):
                    pass
        for path, value in self._overrides.items():
            if value is not None:
                _set_path(part, path, value)
        return part

    def _load_parameters(self, *, extra_fields=None):
        self._building = True
        asset = self._candidate_asset()
        scheme = self._parameter_scheme() or {}
        required_paths = _required_paths(scheme)
        if self._inline_parameters:
            required_paths.update(path for path in asset.get("missing_fields", []) if isinstance(path, str)
                                  and path.startswith(("section.", "construction.")))
        values = {}
        for root in ("section", "construction"):
            for key, value in asset.get(root, {}).items():
                if key in _FIELD_NAMES and isinstance(value, (int, float)) and not isinstance(value, bool):
                    values[root + "." + key] = value
        for path, value in scheme.get("fields", {}).items():
            actual = _get_path(asset, path, value)
            if isinstance(actual, (int, float)) and not isinstance(actual, bool) and path.split(".")[-1] in _FIELD_NAMES:
                values[path] = actual
        for path in required_paths:
            if isinstance(path, str) and path.split(".")[-1] in _FIELD_NAMES and path.split(".")[-1] not in _COMPLEX_FIELDS:
                values.setdefault(path, _get_path(asset, path))
        for path, value in (extra_fields or {}).items():
            if isinstance(path, str) and path.startswith(("section.", "construction.")) and path.split(".")[-1] in _FIELD_NAMES:
                values.setdefault(path, value)
        if asset.get("section_type") in {"u_channel", "aqueduct_u"}:
            # U-channel width is derived from radius, arc/wall angles and height.
            # A legacy rectangular width may remain in source data but has no
            # effect on this geometry, so it must not look like an editable size.
            values.pop("section.inner_width", None)
        if self._inline_parameters:
            from 土石方计算.services.construction_rules import bedding_applicable
            if not bedding_applicable(asset):
                values.pop("construction.bedding_thickness", None)
                values.pop("construction.bedding_extension", None)
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(3, 8, 3, 8)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self._parameter_edits = {}
        self._replacement_rows = {}
        self._shared_dimensions = []
        self._parameter_actions = {"section.source_review_confirmed": self.source_review}
        from 土石方计算.services.section_scheme_catalog import drawing_workspace_dimension, encasement_uniform_dimension
        from 土石方计算.services.replacement_geometry import replacement_geometry_paths
        part = self._current_part() or {}
        enclosure = (asset.get("construction") or {}).get("encasement") or {}
        if encasement_uniform_dimension(scheme):
            for key in ("left_thickness", "right_thickness"):
                if enclosure.get(key) is not None:
                    values["construction.encasement." + key] = enclosure[key]
        linked = replacement_geometry_paths(scheme) if part.get("section_type") in scheme.get("section_types", ()) else ()
        if linked:
            from 土石方计算.services.section_scheme_bindings import draft_section_scheme_fields
            replacement_source, _ = draft_section_scheme_fields(part, scheme, self._overrides)
            initial_overrides = self._overrides.copy()
            for path in linked:
                values[path] = _get_path(replacement_source, path)
        self._parameter_baseline = copy.deepcopy(values)
        manual = any(_net_field(path) and value is not None for path, value in self._overrides.items())
        binding = asset.get("section_scheme_binding", {})
        manual = manual or any(_net_field(path) for path in binding.get("overrides", {}))
        if self._editing_current_structure() and not scheme:
            manual = manual or any(_net_field(path) for path in asset.get("drawing_user_overrides", {}))
        self.net_override.setChecked(manual)
        self.net_restore.setEnabled(not self._inline_parameters or manual)
        for path, value in sorted(values.items(), key=lambda pair: (not _net_field(pair[0]), pair[0])):
            if path in linked:
                from .replacement_parameters import ReplacementDimension
                control = ReplacementDimension(path, replacement_source, scheme=scheme)
                self._replacement_rows[path] = control
                self._parameter_edits[path] = control.edit
                control.edit.setProperty("parameter_path", path)
                control.edit.installEventFilter(self)
                control.changed.connect(lambda p=path: self._replacement_changed(p, initial_overrides))
                form.addRow(_field_label(path), control)
                continue
            edit = QLineEdit("" if value is None else f"{value:g}")
            edit.setPlaceholderText("待补充")
            edit.setProperty("parameter_path", path)
            edit.installEventFilter(self)
            net = _net_field(path)
            edit.setEnabled(not net or manual)
            edit.setToolTip("水面线来源；勾选手动调整后可覆盖" if net else "修改后先预览，点击应用才写入当前区段")
            self._parameter_edits[path] = edit
            form.addRow(_field_label(path), edit)
            edit.textEdited.connect(lambda _, p=path: self._parameter_changed(p))
        from .parameter_form import DrawingSharedDimension
        grouped = (
            (drawing_workspace_dimension(scheme), ["construction.working_space_left", "construction.working_space_right"],
             "每侧工作面 b（m）", "分别设置左右工作面"),
            (encasement_uniform_dimension(scheme), ["construction.encasement." + key for key in (
             "side_thickness", "top_thickness", "bottom_thickness", "left_thickness", "right_thickness")],
             "四面包封厚度 b1（m）", "分别设置包封厚度"),
        )
        for symbol, paths, label, split_label in grouped:
            fields = [self._parameter_edits[p] for p in paths if p in self._parameter_edits]
            if symbol and len(fields) > 1:
                control = DrawingSharedDimension(form, fields, fields, label, split_label)
                self._shared_dimensions.append(control)
                control.value.setProperty("parameter_path", fields[0].property("parameter_path"))
                control.value.installEventFilter(self)
                control.value.textChanged.connect(lambda _, group=paths: self._shared_dimension_changed(group))
                control.separate.toggled.connect(lambda split, group=paths: None if split else self._shared_dimension_changed(group))
        for path in ("section.retaining_wall_profile", "section.foundation_replacement_profile", "section.gabion_profile", "section.rockfill_profile", "construction.floor_steps"):
            if path in required_paths or _get_path(asset, path) is not None:
                value = _get_path(asset, path)
                points = value.get("points", []) if isinstance(value, dict) else value or []
                button = QPushButton(f"编辑轮廓（{len(points)} 个点）" if points else "补充轮廓坐标…")
                button.clicked.connect(lambda _, p=path: self._edit_profile(p))
                self._parameter_actions[path] = button
                form.addRow(_field_label(path), button)
        if "section.discrete_components" in required_paths or asset.get("section", {}).get("discrete_components"):
            button = QPushButton("编辑构件与基础布置…")
            button.clicked.connect(self._edit_discrete_components)
            self._parameter_actions["section.discrete_components"] = button
            form.addRow("墩、支承、基础", button)
        if "section.fill_membrane_confirmed" in required_paths:
            choice = QComboBox()
            choice.addItem("待核定全填段防渗做法", None)
            choice.addItem("全填段设置防渗膜", "with_membrane")
            choice.addItem("全填段不设防渗膜", "without_membrane")
            choice.setCurrentIndex(max(0, choice.findData(_get_path(asset, "section.fill_membrane_mode"))))
            choice.setToolTip("只在地形自动判为全填时采用；填挖形式仍由实际地形决定。")
            choice.currentIndexChanged.connect(lambda _: self._choice_changed("section.fill_membrane_mode", choice.currentData()))
            form.addRow("全填段防渗", choice)
            self._parameter_actions["section.fill_membrane_mode"] = choice
            check = QCheckBox("已核定本工程全填段的防渗做法")
            check.setChecked(_get_path(asset, "section.fill_membrane_confirmed") is True)
            check.setToolTip("原图全填防渗层须按本工程设计核定；仅显式勾选才记录确认。")
            check.toggled.connect(lambda checked: self._confirmation_changed("section.fill_membrane_confirmed", checked))
            form.addRow(check)
            self._parameter_actions["section.fill_membrane_confirmed"] = check
        if not values:
            form.addRow(QLabel("选中工程对象后显示实际参数。"))
        old = self.parameter_scroll.takeWidget()
        self.parameter_scroll.setWidget(widget)
        if old:
            old.deleteLater()
        self._building = False
        if self._replacement_rows:
            self._refresh_replacement_rows(replacement_source, scheme)
        self._update_aqueduct_component_ui()

    def _refresh_replacement_rows(self, source, scheme):
        from 土石方计算.services.replacement_geometry import derived_replacement_fields
        values = derived_replacement_fields(source, scheme, self._overrides)
        for path, control in self._replacement_rows.items():
            control.refresh(values.get(path), source)

    def _replacement_changed(self, path, original):
        if self._building:
            return
        from 土石方计算.services.replacement_geometry import WIDTH, WIDTH_ALIAS
        for key in ((path, WIDTH_ALIAS) if path == WIDTH else (path,)):
            if key in original:
                self._overrides[key] = original[key]
            else:
                self._overrides.pop(key, None)
        try:
            self._overrides.update(self._replacement_rows[path].changes())
        except ValueError:
            pass
        self._preview_candidate = True
        self._update_impact()
        self._schedule_preview()
        self._notify_draft_changed()

    def _shared_dimension_changed(self, paths):
        if self._building:
            return
        present = [path for path in paths if path in self._parameter_edits]
        for path in present:
            try:
                value = float(self._parameter_edits[path].text())
            except ValueError:
                continue
            if math.isfinite(value) and value >= 0:
                self._overrides[path] = value
        self._parameter_changed(present[0])

    def _confirmation_changed(self, path, checked):
        if not self._building:
            self._overrides[path] = bool(checked)
            self._preview_candidate = True
            self._update_impact()
            self._schedule_preview()
            self._notify_draft_changed()

    def _choice_changed(self, path, value):
        if not self._building:
            self._overrides[path] = value
            self._preview_candidate = True
            self._update_impact()
            self._schedule_preview()
            self._notify_draft_changed()

    def _edit_discrete_components(self, *, actual=False):
        """Place actual supports/foundations with engineering fields and chainages."""
        asset = copy.deepcopy(self._current_part() or {}) if actual else self._candidate_asset()
        if actual and (self.structure_choice.currentText() != "渡槽" or self._aqueduct_component_kind() == "body"
                       or asset.get("section_type") not in {"aqueduct_u", "aqueduct_rectangular"}):
            return
        members = edit_discrete_components(self, asset, self._prefix())
        if members is None:
            return
        if actual:
            updated = copy.deepcopy(asset)
            updated.setdefault("section", {})["discrete_components"] = members
            self._commit_aqueduct_part(asset, updated, self._aqueduct_component_kind(),
                "当前渡槽区段构件清单已更新，正式工程量需重新计算；自动布置构件若改动须重新生成。")
            return
        self._adopt_component_parameter("section.discrete_components", members)

    def _edit_profile(self, path):
        profile = edit_section_profile(self, self._candidate_asset(), path)
        if profile is not None:
            self._adopt_component_parameter(path, profile)

    def _adopt_component_parameter(self, path, value):
        self._overrides[path] = value
        self._preview_candidate = True
        self._load_parameters()
        self._update_impact()
        self._schedule_preview()
        self._notify_draft_changed()

    def _net_mode_changed(self, checked):
        if self._building:
            return
        for path, edit in self._parameter_edits.items():
            if _net_field(path):
                edit.setEnabled(checked)
        self._notify_draft_changed()

    def _parameter_changed(self, path):
        if self._building:
            return
        self._preview_candidate = True
        try:
            value = float(self._parameter_edits[path].text())
            if math.isfinite(value) and value >= 0:
                if self._editing_current_structure() and value == self._parameter_baseline.get(path):
                    self._overrides.pop(path, None)
                else:
                    self._overrides[path] = value
        except ValueError:
            pass
        if self._editing_current_structure():
            self._preview_candidate = self._has_parameter_draft()
        if self._replacement_rows:
            from 土石方计算.services.section_scheme_bindings import draft_section_scheme_fields
            scheme = self._parameter_scheme()
            source, _ = draft_section_scheme_fields(self._current_part(), scheme, self._overrides)
            self._refresh_replacement_rows(source, scheme)
        self._update_impact()
        self._schedule_preview()
        self._notify_draft_changed()

    def _collect_overrides(self):
        from 土石方计算.services.construction_rules import validate_u_angle

        overrides = copy.deepcopy(self._overrides)
        for path, edit in self._parameter_edits.items():
            if path in self._replacement_rows:
                overrides.update(self._replacement_rows[path].changes())
                continue
            if not edit.isEnabled():
                continue
            text = edit.text().strip()
            baseline = self._parameter_baseline.get(path)
            if not text:
                if baseline is not None or path in overrides:
                    raise ValueError(f"请填写{_field_label(path)}，或恢复原值。")
                continue
            try:
                value = float(text)
                if not math.isfinite(value) or value < 0:
                    raise ValueError
            except ValueError:
                raise ValueError(f"{_field_label(path)}应为不小于零的数值。") from None
            validate_u_angle(path, value)
            if baseline is not None and text == f"{baseline:g}":
                continue
            if baseline is None or abs(value - float(baseline)) > 1e-12:
                overrides[path] = value
        return overrides

    def _restore_net(self):
        for path in self._parameter_edits:
            if _net_field(path):
                self._overrides[path] = None
        self._preview_candidate = True
        self._record = None
        self._load_parameters()
        self._building = True
        self.net_override.setChecked(False)
        self._building = False
        self._net_mode_changed(False)
        self._update_impact()
        self._schedule_preview()

    def _advanced_parameters(self, initial_tab=None, *, focus_path=None):
        if not self._asset() or self._aqueduct_component_kind() != "body":
            return
        from .workbench_parameters import AssetParameterDialog, scheme_parameter_overrides
        asset = self._candidate_asset()
        scheme = self._parameter_scheme()
        editor = AssetParameterDialog(asset, self, initial_page=initial_tab or "construction", show_scope=False,
                                      preview_scheme=scheme)
        if focus_path and hasattr(editor, "parameter_preview"):
            editor.parameter_preview.focus_parameter(focus_path)
        editor.setWindowTitle("区段构造参数 · " + (scheme or {}).get("title", "当前断面"))
        if editor.exec() == QDialog.Accepted:
            values = {path: change["after"] for path, change in editor.changed_fields.items()}
            if not values:
                return
            self._overrides.update(scheme_parameter_overrides(editor.asset, values))
            self._preview_candidate = True
            self._load_parameters()
            self._update_impact()
            self._schedule_preview()
            self._notify_draft_changed()

    def _application_inputs(self):
        asset, scheme = self._asset(), self._parameter_scheme()
        editing_current = self._editing_current_structure()
        if not asset or not scheme and not editing_current:
            return copy.deepcopy(self.updated_inputs)
        from 土石方计算.services.section_scheme_bindings import apply_section_scheme, edit_current_section_parameters
        result = copy.deepcopy(self.updated_inputs)
        overrides = self._collect_overrides()
        for start, end in self._ranges():
            arguments = dict(route_id=asset["route_id"], asset_id=asset["asset_id"],
                             station_start=start, station_end=end, overrides=overrides)
            if editing_current:
                result, _ = edit_current_section_parameters(result, **arguments)
            else:
                result = apply_section_scheme(result, scheme=scheme, **arguments)
        if result.get("special_pipe_materials") and not editing_current:
            from 土石方计算.services.special_pipe_materials import (
                _is_pipe_scope_id, list_special_material_groups, set_special_material_mode, validate_special_pipe_materials,
            )
            ranges = self._ranges()
            for group in list_special_material_groups(result):
                if not group.get("source_groups") and group["route_id"] == asset["route_id"] and group["asset_id"] == asset["asset_id"] and any(
                        float(part["station_end"]) > start and float(part["station_start"]) < end
                        for part in group.get("parts", []) for start, end in ranges):
                    result = set_special_material_mode(result, group["group_id"], "station")
            if any(map(_is_pipe_scope_id, result["special_pipe_materials"]["groups"])):
                validate_special_pipe_materials(result, raise_on_error=True)
        return result

    def _apply(self):
        if self._aqueduct_component_kind() != "body":
            return
        if not self._preview_candidate:
            self._preview_candidate = True
            self._record = None
            self._load_parameters()
            self._update_impact()
            self._schedule_preview()
            self._notify_draft_changed()
            return
        self._update_impact()
        if not self._report or not self.apply_button.isEnabled():
            return
        try:
            result = self._application_inputs()
        except (ValueError, TypeError, KeyError) as error:
            self.impact.setText("未应用：" + str(error))
            return
        asset = self._asset()
        identity = asset["route_id"], asset["asset_id"]
        self._history.append(copy.deepcopy(self.updated_inputs))
        self.updated_inputs = result
        self.has_changes = True
        self.undo_button.setEnabled(True)
        self._refresh_assets(identity)
        self.notice.setText("区段设置已更新，正式工程量需重新计算；附属项目按清单及缺项说明核对。")
        self._emit_inputs_applied()

    def _undo(self):
        if not self._history:
            return
        asset = self._asset()
        identity = (asset["route_id"], asset["asset_id"]) if asset else None
        self.updated_inputs = self._history.pop()
        self.materials_widget.discard_drafts()
        self.has_changes = bool(self._history) or bool(self.default_report["changed"])
        self.undo_button.setEnabled(bool(self._history))
        self._refresh_assets(identity)
        self.notice.setText("已撤销上一次修改；附属项目按清单及缺项说明核对。")
        self._emit_inputs_applied()

    def _edit_slope_support(self):
        if self.embedded and self.has_pending_draft():
            self._show_pending_draft()
            return
        from .slope_support_dialog import SlopeSupportDialog
        scheme = self._scheme() or {}
        code = str(scheme.get("scheme_id", ""))[-1:].upper()
        dialog = SlopeSupportDialog(self.updated_inputs, self, initial_type=code if code in "ABCD" and code else "A")
        if dialog.exec() != QDialog.Accepted or dialog.updated_inputs == self.updated_inputs:
            return
        asset = self._asset()
        identity = (asset["route_id"], asset["asset_id"]) if asset else None
        self._history.append(copy.deepcopy(self.updated_inputs))
        self.updated_inputs = copy.deepcopy(dialog.updated_inputs)
        self.has_changes = True; self.undo_button.setEnabled(True)
        self._refresh_assets(identity)
        self.notice.setText(f"已保存 {len(self.updated_inputs.get('slope_support_rows', []))} 条支护长度记录，正式工程量需重新计算。")
        self._emit_inputs_applied()

    def _commit_aqueduct_part(self, part, updated, component, notice):
        group = self._asset()
        if not group or updated == part:
            return
        route = next((n for n in self.updated_inputs.get("networks", [])
            if str(n.get("route_id") or n.get("network_id") or n.get("name", "")) == group["route_id"]), None)
        if route is None:
            return
        index = next((i for i, original in enumerate(route.get("assets", [])) if original["asset_id"] == part["asset_id"]), None)
        if index is None:
            return
        draft = {"station": self.station_edit.text(), "side": self.side_choice.currentIndex(),
            "start": self.start_edit.text(), "end": self.end_edit.text(), "batch": self.batch_check.isChecked(),
            "ranges_open": self.ranges_toggle.isChecked(), "parameters_open": self.parameters_toggle.isChecked(),
            "view_mode": self.view_mode.currentIndex(), "scheme_id": (self._scheme() or {}).get("scheme_id"),
            "overrides": copy.deepcopy(self._overrides), "candidate": self._preview_candidate,
            "explicit_scheme": self._explicit_scheme,
            "parameter_edits": self._parameter_edits, "parameter_baseline": self._parameter_baseline,
            "parameter_widget": self.parameter_scroll.takeWidget(), "net_override": self.net_override.isChecked(),
            "review_checked": self.source_review.isChecked(), "description": self.description.text(),
            "description_tip": self.description.toolTip(), "report": self._report,
            "impact": self.impact.text(), "impact_tip": self.impact.toolTip(),
            "range_hints": [(widget.text(), widget.styleSheet()) for widget in (self.start_hint, self.end_hint, self.length_hint)],
            "range_styles": (self.start_edit.styleSheet(), self.end_edit.styleSheet()),
            "apply_enabled": self.apply_button.isEnabled(), "apply_text": self.apply_button.text(),
            "checked_ranges": {(item.data(Qt.UserRole).get("asset_id"), item.data(Qt.UserRole).get("station_start"),
                item.data(Qt.UserRole).get("station_end")) for row in range(self.ranges_table.rowCount())
                if (item := self.ranges_table.item(row, 0)).checkState() == Qt.Checked}}
        self._history.append(copy.deepcopy(self.updated_inputs))
        route["assets"][index] = copy.deepcopy(updated)
        self.has_changes = True; self.undo_button.setEnabled(True)
        self._refresh_assets((group["route_id"], group["asset_id"]))
        # Rebuilding asset rows must not move a component edit to another part
        # or discard the independently unfinished body-scheme form.
        self._building = True
        self.station_edit.setText(draft["station"])
        self.side_choice.setCurrentIndex(draft["side"])
        self.start_edit.setText(draft["start"])
        self.end_edit.setText(draft["end"])
        self.batch_check.setChecked(draft["batch"])
        self.ranges_toggle.setChecked(draft["ranges_open"])
        self.parameters_toggle.setChecked(draft["parameters_open"])
        self.view_mode.setCurrentIndex(draft["view_mode"])
        self.scheme_list.blockSignals(True)
        for row, scheme in enumerate(self._visible_schemes):
            if scheme.get("scheme_id") == draft["scheme_id"]:
                self.scheme_list.setCurrentRow(row)
                break
        self.scheme_list.blockSignals(False)
        self.ranges_table.blockSignals(True)
        for row in range(self.ranges_table.rowCount()):
            item = self.ranges_table.item(row, 0)
            data = item.data(Qt.UserRole)
            item.setCheckState(Qt.Checked if (data.get("asset_id"), data.get("station_start"), data.get("station_end")) in draft["checked_ranges"] else Qt.Unchecked)
        self.ranges_table.blockSignals(False)
        fresh = self.parameter_scroll.takeWidget()
        if fresh:
            fresh.deleteLater()
        self.parameter_scroll.setWidget(draft["parameter_widget"])
        self._parameter_edits = draft["parameter_edits"]
        self._parameter_baseline = draft["parameter_baseline"]
        self.net_override.blockSignals(True)
        self.net_override.setChecked(draft["net_override"])
        self.net_override.blockSignals(False)
        self.source_review.blockSignals(True)
        self.source_review.setChecked(draft["review_checked"])
        self.source_review.blockSignals(False)
        self._overrides = draft["overrides"]
        self._preview_candidate = draft["candidate"]
        self._explicit_scheme = draft["explicit_scheme"]
        self._record = None
        self._report = draft["report"]
        self.description.setText(draft["description"])
        self.description.setToolTip(draft["description_tip"])
        self.impact.setText(draft["impact"])
        self.impact.setToolTip(draft["impact_tip"])
        for widget, (text, style) in zip((self.start_hint, self.end_hint, self.length_hint), draft["range_hints"]):
            widget.setText(text)
            widget.setStyleSheet(style)
        for widget, style in zip((self.start_edit, self.end_edit), draft["range_styles"]):
            widget.setStyleSheet(style)
        self.apply_button.setEnabled(draft["apply_enabled"])
        self.apply_button.setText(draft["apply_text"])
        self._building = False
        self._restore_aqueduct_component(component)
        self._schedule_preview()
        self._component_navigation_epoch = self._epoch
        self.notice.setText(notice)
        self._emit_inputs_applied()

    def _edit_aqueduct_frames(self, component=None):
        from .aqueduct_frames_dialog import AqueductFramesDialog
        component = component or self._aqueduct_component_kind()
        group, part = self._asset(), self._current_part()
        if (component not in {"columns", "foundation"} or self.structure_choice.currentText() != "渡槽"
                or not self.frame_button.isEnabled() or not group or not part
                or part.get("section_type") not in {"aqueduct_u", "aqueduct_rectangular"}):
            return
        if self._terrain is None:
            self.notice.setText("请先在工作台导入地形，再设置排架并自动取高。")
            return
        route = next((n for n in self.updated_inputs.get("networks", [])
            if str(n.get("route_id") or n.get("network_id") or n.get("name", "")) == group["route_id"]), None)
        if route is None:
            self.notice.setText("当前渡槽缺少可核对的线路平面，无法定位排架。")
            return
        dialog = AqueductFramesDialog(part, self._terrain, alignment=route.get("alignment"),
            station_prefix=self._prefix(), initial_component=component, parent=self)
        if dialog.exec() != QDialog.Accepted or dialog.asset == part:
            return
        self._commit_aqueduct_part(part, dialog.asset, component,
            "当前渡槽区段排架与基础布置已更新，柱与基础标高联动；正式工程量需重新计算。")

    def _use_dn_envelope(self):
        if self.embedded and self.has_pending_draft():
            self._show_pending_draft()
            return
        from 土石方计算.services.pipe_dimensions import use_nominal_pipe_envelope
        group = self._asset()
        if not group: return
        candidate = copy.deepcopy(self.updated_inputs)
        part_ids = {p["asset_id"] for p in group.get("parts", [])}
        removed = set()
        for route in candidate.get("networks", []):
            rid = str(route.get("route_id") or route.get("network_id") or route.get("name", ""))
            if rid != group["route_id"]: continue
            for asset in route.get("assets", []):
                if asset["asset_id"] not in part_ids: continue
                try:
                    use_nominal_pipe_envelope(asset)
                except (ValueError, TypeError) as error:
                    self.notice.setText("尚未采用DN占位：" + str(error))
                    return
                from 土石方计算.services.section_scheme_bindings import _get
                for key in ("missing_fields", "source_missing_fields"):
                    if key in asset:
                        asset[key] = [p for p in asset[key] if not isinstance(p, str) or _get(asset, p) is None]
                removed.update((asset["asset_id"], p["field"]) for p in asset.get("pipe_dn_replaced_assumptions", []))
        if "construction_assumptions" in candidate:
            candidate["construction_assumptions"] = [r for r in candidate["construction_assumptions"]
                if (r.get("asset_id"), r.get("field")) not in removed]
        if candidate == self.updated_inputs:
            self.notice.setText("当前管道已采用DN占位或明确实际外径，参数未改变。")
            return
        self._history.append(copy.deepcopy(self.updated_inputs)); self.updated_inputs = candidate
        self.has_changes = True; self.undo_button.setEnabled(True)
        self._refresh_assets((group["route_id"], group["asset_id"]))
        self.notice.setText("当前管道已采用DN施工占位，明确实际外径保留；缺实际壁厚的管材量未计，正式工程量需重新计算。")
        self._emit_inputs_applied()

    def _schedule_preview(self):
        if self._building or self._closed:
            return
        self._epoch += 1
        self._preview_pending = True
        self._debounce.start()
        if self.runner.isRunning():
            self.runner.invalidate()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.FocusIn and self.preview_stack.currentWidget() is self.model_view:
            path = watched.property("parameter_path")
            if path:
                self.model_view.focusParameter(path)
        return super().eventFilter(watched, event)

    def _focus_model_parameter(self, path):
        if self._inspection_mode:
            return
        self.parameters_toggle.setChecked(True)
        target = self._parameter_edits.get(path) or self._parameter_actions.get(path)
        if target is None and path.startswith("section.pipes[1]."):
            key = "section." + path.rsplit(".", 1)[1]
            target = self._parameter_edits.get(key)
            if target is not None:
                path = key
        for control in self._shared_dimensions:
            if target in control.fields and not control.separate.isChecked():
                target = control.value
                break
        if target is None:
            self._advanced_parameters(focus_path=path)
            return
        if self.parameter_scroll.widget().isAncestorOf(target):
            self.parameter_scroll.ensureWidgetVisible(target)
        if target.isEnabled():
            target.setFocus()
            if isinstance(target, QLineEdit):
                target.selectAll()
        elif _net_field(path):
            self.view_status.setText(_field_label(path) + "沿用导入值，可在参数栏勾选手动调整")
            self.net_override.setFocus()

    def _show_parametric_model(self):
        from 土石方计算.services.section_parameter_decisions import section_parameter_decisions
        from 土石方计算.services.section_scheme_bindings import draft_current_section_parameters, draft_section_scheme_fields

        self.preview_stack.setCurrentWidget(self.model_view)
        self.progress.clear()
        part = self._current_part() or {}
        scheme = self._parameter_scheme() or {}
        editing_current = self._editing_current_structure()
        mismatched = self._preview_candidate and not editing_current and part.get("section_type") not in scheme.get("section_types", ())
        if not supports_parameter_section(part) or mismatched:
            self.model_view.show_message("请选择与本段结构匹配的断面型号，可在原 DXF 对照中查看图纸。")
            self.view_status.setText("选择断面型号")
            return
        fields = None
        overrides = {}
        if self._preview_candidate:
            try:
                overrides = self._collect_overrides()
                if editing_current:
                    part, fields = draft_current_section_parameters(part, overrides)
                else:
                    part, fields = draft_section_scheme_fields(part, scheme, overrides)
            except (ValueError, TypeError, KeyError) as error:
                self.model_view.show_message(str(error))
                self.view_status.setText("请核对本段参数")
                return
        else:
            scheme = (part.get("section_scheme_binding") or {}).get("scheme_snapshot") or {}
        decisions = section_parameter_decisions(part, scheme, overrides=overrides, resolved_fields=fields)
        pending = [path for path, decision in decisions.items() if decision["required"] and decision["missing"]]
        self.model_view.set_section_parameters(part, scheme, pending)
        label = ("参数修改预览" if editing_current else "待采用方案") if self._preview_candidate else "本段已采用"
        self.view_status.setText(label + (f" · 待补 {len(pending)} 项参数" if pending else " · 点击尺寸定位参数"))

    def _view_mode_changed(self, *_):
        if self._building:
            return
        if self._aqueduct_component_kind() != "body":
            self._schedule_preview()
            return
        mode = self.view_mode.currentData()
        if mode in {"source", "model"}:
            self._debounce.stop()
            self._epoch += 1
            self._preview_pending = False
            self.runner.invalidate()
            self._progress_timer.stop()
            self.progress.clear()
            if mode == "source":
                self._show_source()
            else:
                self._show_parametric_model()
        else:
            self.preview_stack.setCurrentWidget(self.preview)
            self._schedule_preview()

    def _source_reference(self):
        from 土石方计算.services.section_scheme_bindings import _preview_names
        scheme = self._parameter_scheme() or {}
        case = (self._record or {}).get("terrain_case", {})
        if case.get("source_preview") in _preview_names(scheme):
            return case["source_preview"]
        code = case.get("code")
        variants = scheme.get("terrain_variants", {})
        variant = variants.get(code, {}) if isinstance(variants, dict) else next((v for v in variants if v.get("condition") == code), {})
        return variant.get("source_preview") or scheme.get("source_preview")

    def _show_source(self):
        self.preview_stack.setCurrentWidget(self.preview)
        status = self.preview.show_scheme_drawing(self._parameter_scheme() or {}, self._source_reference(),
            self.library_path.parent, self.updated_inputs.get("input_files", []))
        self.view_status.setText(status)

    def _start_preview(self):
        if self._closed:
            return
        component_view = self._aqueduct_component_kind() != "body"
        if self.view_mode.currentData() == "model" and not component_view:
            self._preview_pending = False
            self._show_parametric_model()
            return
        self.preview_stack.setCurrentWidget(self.preview)
        if self.runner.isRunning():
            self._preview_pending = True
            return
        self._preview_pending = False
        if self.view_mode.currentData() == "source" and not component_view:
            self._show_source()
            return
        asset = self._asset()
        if not asset:
            self.preview.show_message("未加载工程。请先加载水面线和地形；原图对照仍可浏览。")
            return
        if component_view and (self._current_part() or {}).get("section_type") not in {"aqueduct_u", "aqueduct_rectangular"}:
            self.preview.show_message("当前工程对象不是渡槽。请先选择实际渡槽工程对象，再查看排架柱或扩大基础。")
            self.view_status.setText("渡槽构件分类浏览")
            return
        station = self._valid_station()
        if station is None:
            self.preview.show_message("请输入当前对象范围内的查看桩号。")
            return
        if self._preview_callback is None:
            self.preview.show_message("尚未加载当前工程地形，无法生成实际施工断面。\n原 DXF 对照可正常查看。")
            self.view_status.setText("当前施工断面待地形数据")
            return
        try:
            candidate = self._application_inputs() if self._preview_candidate and not component_view and not self._material_length_view() else copy.deepcopy(self.updated_inputs)
        except (ValueError, TypeError, KeyError) as error:
            self.preview.show_message("候选断面待完善：\n" + str(error))
            self.view_status.setText("候选未应用 · 请完善参数或桩号范围")
            return
        epoch, asset_id, side = self._epoch, asset["asset_id"], self.side_choice.currentData()
        route_id = asset["route_id"]
        navigation_preview = epoch == self._component_navigation_epoch
        callback = self._preview_callback
        self._clock.start()
        self._progress_timer.start()
        self.progress.setText(f"正在生成 {self._format(station)} 施工断面…")
        self.preview.show_message("正在读取该桩地形并生成施工断面…")
        self.cancel_preview_button.show()
        self.cancel_preview_button.setEnabled(True)
        def work(token):
            token.raise_if_cancelled()
            import inspect
            kwargs = {"side": side}
            parameters = inspect.signature(callback).parameters
            if "token" in parameters:
                kwargs["token"] = token
            if "route_id" in parameters:
                kwargs["route_id"] = route_id
            result = callback(candidate, asset_id, station, **kwargs)
            token.raise_if_cancelled()
            return result
        def done(record):
            if epoch == self._epoch and not self._closed:
                self._record = record
                if (not navigation_preview and not component_view
                        and self.focusWidget() not in self._parameter_edits.values()
                        and not self._has_parameter_draft()):
                    self._load_parameters()
                if self.view_mode.currentData() == "source" and not component_view:
                    self._show_source()
                else:
                    self._show_record(record)
                self.progress.setText("当前桩预览已完成 · 工程量尚未重新计算" if self.has_changes or (self._preview_candidate and not component_view) else "当前桩预览已完成")
        def failed(error):
            if epoch == self._epoch and not self._closed:
                self.preview.show_message("当前断面无法生成：\n" + str(error))
                self.progress.setText("预览未完成；可切换原 DXF 对照并补齐所需参数。")
        self.runner.submit(work, on_success=done, on_error=failed,
                           on_cancelled=lambda: self.progress.setText("预览已取消"))

    def _show_record(self, record):
        self.preview_stack.setCurrentWidget(self.preview)
        part = record.get("effective_asset") or self._current_part() or {}
        reference = (part.get("design_profile") or {}).get("reference") or (part.get("alignment") or {}).get("elevation_reference")
        self.preview.set_section(record, elevation_reference=reference)
        case = record.get("terrain_case", {})
        label = case.get("label") or ""
        component = self._aqueduct_component_kind()
        state = (("排架柱" if component == "columns" else "扩大基础") + " · 当前实际区段断面" if component != "body"
                 else "候选预览 · 未应用" if self._preview_candidate else "当前已采用断面")
        self.view_status.setText(state + "  " + self._format(record["station"]) + (" · " + label + "（地形自动）" if label else ""))

    def _update_elapsed(self):
        if self.runner.isRunning():
            self.progress.setText(f"正在生成当前桩施工断面… 已用 {self._clock.elapsed() // 1000} 秒")

    def _runner_changed(self, running):
        if not running:
            self._progress_timer.stop()
            self.cancel_preview_button.hide()
            if self._preview_pending and not self._closed:
                self._debounce.start(20)

    def _cancel_preview(self):
        self._preview_pending = False
        self._debounce.stop()
        self.runner.cancel()
        self.progress.setText("正在取消当前桩预览…")
        self.cancel_preview_button.setEnabled(False)

    def _dispose(self, *_):
        self._closed = True
        self._debounce.stop()
        self._progress_timer.stop()
        self.runner.invalidate()

    def dispose_workspace(self):
        """Called by the owner only when replacing the project or closing it."""
        self._dispose()

    def closeEvent(self, event):
        if not self.embedded:
            self._dispose()
        super().closeEvent(event)
