"""Construction inputs shown by the selected structure type."""
from __future__ import annotations
import copy
import json
import math
import re
import uuid

from 土石方计算.services.construction_rules import U_ANGLE_DEFAULTS, bedding_applicable, normalize_asset_construction, is_circular_culvert, validate_u_angle
from 土石方计算.services.aqueduct_components import QUANTITY_SCOPE_CATEGORIES
from 土石方计算.services.pipe_dimensions import normalize_pipe_dimensions
from 土石方计算.services.pipe_construction_defaults import DEFAULT_MANUAL_BACKFILL_HEIGHT_M, apply_pipe_construction_defaults
from 土石方计算.services.batch_cover_profiles import DEFAULT_WORKBENCH_COVER_M, is_pressure_cover_asset
from 土石方计算.services.section_geometry import pipe_specs
from 土石方计算.io.network_exporter import SECTION_NAMES

from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QGridLayout,QFormLayout,QLabel,QLineEdit,
    QComboBox,QPushButton,QDialogButtonBox,QTableWidget,QTableWidgetItem,QMessageBox,QTabWidget,QWidget,QCheckBox,QPlainTextEdit,QGroupBox,QToolButton,
    QScrollArea,QFrame,QHeaderView)
from PySide6.QtCore import Qt

from .parameter_form import PARAMETER_STYLE, DrawingSharedDimension, EncasementSides, align_form, optional_support_bedding, pair_fields


AQUEDUCT_SCOPE_LABELS=tuple(QUANTITY_SCOPE_CATEGORIES["aqueduct"].items())
TUNNEL_SCOPE_LABELS=tuple(QUANTITY_SCOPE_CATEGORIES["tunnel"].items())
LAYERED_EXCAVATION_FIELDS=("excavation_layer_mode","overburden_thickness",
    "overburden_slope_left","overburden_slope_right","bedrock_slope_left","bedrock_slope_right")
LAYERED_EXCAVATION_SECTION_TYPES={"trapezoidal_channel","rectangular_channel","u_channel",
    "rectangular_culvert","circular_culvert","arch_culvert","circular_siphon","circular_channel"}


def layered_excavation_applicable(asset):
    """Keep the editor and batch copying restricted to ordinary open cuts."""
    return (asset.get("section_type") in LAYERED_EXCAVATION_SECTION_TYPES and
            asset.get("construction",{}).get("installation_mode") not in {"exposed","elevated","open","above_ground"})


def _scope_box(options,value=None):
    box=QComboBox();box.addItem("未归类（仍提示范围待核对）",None)
    for key,name in options:box.addItem(name,key)
    if value is not None and box.findData(value)<0:box.addItem("保留现有类别："+str(value),value)
    box.setCurrentIndex(max(0,box.findData(value)));return box


def _get(data,path):
    for key in path.split("."):
        if not isinstance(data,dict):return None
        data=data.get(key)
    return data


def _set(data,path,value):
    parts=path.split(".");node=data
    for key in parts[:-1]:node=node.setdefault(key,{})
    if value is None:node.pop(parts[-1],None)
    else:node[parts[-1]]=value


def _parameter_changes(before,after):
    """Expose actual user edits so the caller can preserve field provenance."""
    changes={}
    def visit(old,new,path):
        if isinstance(old,dict) and isinstance(new,dict) and not path.endswith(".inner_chamfers"):
            for key in sorted(set(old)|set(new)):visit(old.get(key),new.get(key),path+"."+key)
        elif old!=new:changes[path]={"before":copy.deepcopy(old),"after":copy.deepcopy(new)}
    for root in ("section","construction"):visit(before.get(root,{}),after.get(root,{}),root)
    return changes


def scheme_parameter_overrides(asset, values):
    """Keep row-level derivation metadata while binding only declared scalar inputs."""
    from 土石方计算.services.pipe_dimensions import DN_ENVELOPE_BASIS
    section = asset.get("section", {})
    first_pipe = (section.get("pipes") or [section])[0]
    derived = {"section.dn_envelope_diameter_m", "section.diameter_basis",
               "section.construction_inner_diameter_m", "section.inner_diameter_is_placeholder",
               "section.earthwork_envelope_only"}
    automatic = first_pipe.get("dn_envelope_diameter_m")
    if (first_pipe.get("diameter_basis") == DN_ENVELOPE_BASIS and automatic is not None
            and first_pipe.get("outer_diameter") == automatic):
        derived.add("section.outer_diameter")
    return {path: copy.deepcopy(value) for path, value in values.items() if path not in derived}


def _uniform_chamfer(value):
    if not isinstance(value,dict):return value
    sizes=[]
    for corner in ("bottom_left","bottom_right","top_left","top_right"):
        item=value.get(corner,0.)
        if isinstance(item,(list,tuple)):
            if len(item)!=2 or item[0]!=item[1]:return None
            item=item[0]
        sizes.append(item)
    return sizes[0] if all(item==sizes[0] for item in sizes) else None


class CollapsibleParameterGroup(QWidget):
    """Keep optional controls available without disabling or clearing their values."""
    def __init__(self,title,parent=None,*,expanded=False):
        super().__init__(parent)
        layout=QVBoxLayout(self);layout.setContentsMargins(0,2,0,2);layout.setSpacing(4)
        self.toggle=QToolButton();self.toggle.setText(title);self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setStyleSheet("QToolButton { border:0; padding:6px 0; font-weight:600; }")
        layout.addWidget(self.toggle)
        self.body=QWidget();self.form=QFormLayout(self.body)
        self.form.setContentsMargins(12,4,8,8);self.form.setVerticalSpacing(10)
        layout.addWidget(self.body);self.toggle.toggled.connect(self.setExpanded)
        self.setExpanded(expanded)

    def setExpanded(self,expanded):
        self.toggle.setChecked(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.body.setVisible(expanded)

    def isExpanded(self):
        return self.toggle.isChecked()


class StageDialog(QDialog):
    def __init__(self,values,parent=None):
        super().__init__(parent);self.setWindowTitle("分级边坡与马道");self.resize(490,330)
        layout=QVBoxLayout(self);layout.addWidget(QLabel("从该结构的起坡点向外依次填写；最后一级延伸至原地面，其级高不限制接地。"))
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(["级高 m","坡比 1:m","马道宽 m"]);layout.addWidget(self.table)
        for value in values:self.add_row(value)
        if not values:self.add_row()
        row=QHBoxLayout();add=QPushButton("增加一级");add.clicked.connect(lambda:self.add_row());row.addWidget(add)
        remove=QPushButton("删除选中级");remove.clicked.connect(lambda:self.table.removeRow(self.table.currentRow()) if self.table.currentRow()>=0 else None);row.addWidget(remove);layout.addLayout(row)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def add_row(self,value=None):
        value=value or {};row=self.table.rowCount();self.table.insertRow(row)
        for i,key in enumerate(("height","slope","berm_width")):self.table.setItem(row,i,QTableWidgetItem(str(value.get(key,""))))

    def accept(self):
        try:
            self.values=[]
            for row in range(self.table.rowCount()):
                v=[float(self.table.item(row,c).text()) for c in range(3)]
                if not all(math.isfinite(x) for x in v) or v[0]<=0 or min(v[1:])<0:raise ValueError("级高须大于零，坡比和马道宽须为非负数")
                self.values.append(dict(zip(("height","slope","berm_width"),v)))
        except (ValueError,AttributeError) as exc:QMessageBox.warning(self,"参数未完整",str(exc));return
        super().accept()


class QuantityRuleDialog(QDialog):
    """A normal form for supplementary quantities; retain unknown source fields."""
    def __init__(self,rule=None,parent=None,*,kind=None):
        super().__init__(parent);self.rule=copy.deepcopy(rule or {});self.fields={}
        self.setWindowTitle("补充分项计量");self.resize(600,660)
        layout=QVBoxLayout(self)
        label=QLabel("填写本工程设计值。总量只计一次；单件量和尺寸量乘以重复件数。未填写的项目仍作为缺项提示。")
        label.setWordWrap(True);layout.addWidget(label)
        from PySide6.QtWidgets import QScrollArea
        page=QWidget();form=QFormLayout(page);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);layout.addWidget(scroll);self._rule_form=form
        self.rule.setdefault("id",self.rule.get("component_id") or "item_"+uuid.uuid4().hex[:12])
        for key,name in (("name","项目名称"),("id","分项编号（英文）"),("material","材质"),("grade","材料等级")):
            field=QLineEdit(str(self.rule.get(key) or ""));self.fields[key]=field;form.addRow(name,field)
        categories=AQUEDUCT_SCOPE_LABELS if kind=="aqueduct" else TUNNEL_SCOPE_LABELS if kind=="tunnel" else tuple(dict(AQUEDUCT_SCOPE_LABELS+TUNNEL_SCOPE_LABELS).items())
        self.scope_category=_scope_box(categories,self.rule.get("scope_category"));form.addRow("计量范围类别",self.scope_category)
        self.unit=QComboBox()
        for name,value in (("体积 m³","m3"),("面积 m²","m2"),("长度 m","m"),("质量 kg","kg"),("个/件/处","count")):self.unit.addItem(name,value)
        self.unit.setCurrentIndex(max(0,self.unit.findData(self.rule.get("unit","count"))));form.addRow("计量单位",self.unit)
        self.mode=QComboBox()
        for name,value in (("已知总量","quantity"),("单件计量值 × 件数","quantity_per_unit"),("按尺寸或件数计量","dimensions")):self.mode.addItem(name,value)
        mode="quantity" if "quantity" in self.rule else "quantity_per_unit" if "quantity_per_unit" in self.rule else "dimensions"
        self.mode.setCurrentIndex(self.mode.findData(mode));form.addRow("计量方式",self.mode)
        for key,name in (("quantity","明确总量（按所选单位）"),("quantity_per_unit","每件计量值（按所选单位）"),("count","重复件数"),
                         ("length_m","单件长度 m"),("width_m","单件宽度 m"),("height_m","单件高度 m"),("cross_section_area_m2","单件截面积 m²"),("mass_per_unit_kg","单件质量 kg"),
                         ("station","指定桩号 m"),("station_start","适用起桩 m"),("station_end","适用止桩 m")):
            value=self.rule.get(key,1 if key=="count" else None);field=QLineEdit("" if value is None else str(value));self.fields[key]=field;form.addRow(name,field)
        hint=QLabel("尺寸量：m³填长×宽×高，或截面积×长；m²填长×宽；m填长；kg填单件质量。指定桩号与起止桩号任选一种；留空作用于本区段。")
        hint.setWordWrap(True);form.addRow(hint)
        self.mode.currentIndexChanged.connect(self.refresh_measure_fields);self.unit.currentIndexChanged.connect(self.refresh_measure_fields);self.refresh_measure_fields()
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def refresh_measure_fields(self):
        mode=self.mode.currentData();unit=self.unit.currentData()
        visible={"quantity"} if mode=="quantity" else {"quantity_per_unit","count"} if mode=="quantity_per_unit" else {"count"}|set({"m3":("length_m","width_m","height_m","cross_section_area_m2"),"m2":("length_m","width_m"),"m":("length_m",),"kg":("mass_per_unit_kg",),"count":()}.get(unit,()))
        for key in ("quantity","quantity_per_unit","count","length_m","width_m","height_m","cross_section_area_m2","mass_per_unit_kg"):
            field=self.fields[key];field.setVisible(key in visible);self._rule_form.labelForField(field).setVisible(key in visible)

    def accept(self):
        try:
            rule=copy.deepcopy(self.rule)
            for key in ("name","id","material","grade"):
                value=self.fields[key].text().strip()
                if value:rule[key]=value
                else:rule.pop(key,None)
            if not rule.get("name") or not rule.get("material"):raise ValueError("请填写项目名称和材质")
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}",rule.get("id","")):raise ValueError("编号须为字母开头的英文、数字或下划线，最长80字符")
            if "component_id" in rule:rule["component_id"]=rule["id"]
            category=self.scope_category.currentData()
            if category:rule["scope_category"]=category
            else:rule.pop("scope_category",None)
            numeric={}
            for key,field in self.fields.items():
                if key in ("name","id","material","grade"):continue
                text=field.text().strip()
                if text:
                    value=float(text)
                    if not math.isfinite(value) or value<0 and not key.startswith("station"):raise ValueError("数量和尺寸须为有限非负数")
                    numeric[key]=value
            mode=self.mode.currentData();unit=self.unit.currentData()
            if mode in {"quantity","quantity_per_unit"} and mode not in numeric:raise ValueError("请填写所选计量方式的数量")
            if mode=="dimensions":
                needed={"m3":("length_m","width_m","height_m"),"m2":("length_m","width_m"),"m":("length_m",),"kg":("mass_per_unit_kg",),"count":()}.get(unit,())
                if unit=="m3" and "cross_section_area_m2" in numeric:needed=("cross_section_area_m2","length_m")
                if any(key not in numeric for key in needed):raise ValueError("请按计量单位补齐尺寸")
            if "station" in numeric and any(key in numeric for key in ("station_start","station_end")):raise ValueError("指定桩号与起止桩号只能选一种")
            if ("station_start" in numeric)!=("station_end" in numeric):raise ValueError("适用起止桩号须成对填写")
            if "station_start" in numeric and numeric["station_start"]>=numeric["station_end"]:raise ValueError("适用起桩须小于止桩")
            measure_keys={"quantity","quantity_per_unit","count","length_m","width_m","height_m","cross_section_area_m2","mass_per_unit_kg","station","station_start","station_end"}
            for key in measure_keys:rule.pop(key,None)
            for key in ("station","station_start","station_end"):
                if key in numeric:rule[key]=numeric[key]
            if mode in {"quantity","quantity_per_unit"}:rule[mode]=numeric[mode]
            else:
                for key in measure_keys-{"quantity","quantity_per_unit","count","station","station_start","station_end"}:
                    if key in numeric:rule[key]=numeric[key]
            if mode!="quantity":rule["count"]=numeric.get("count",1.)
            rule["unit"]=unit;self.rule=rule
        except (ValueError,TypeError) as exc:QMessageBox.warning(self,"分项规则需要核对",str(exc));return
        super().accept()


class AssetParameterDialog(QDialog):
    def __init__(self,asset,parent=None,*,template=False,initial_page="construction",context_title="",show_scope=True,
                 preview_scheme=None, defer_preview=False):
        super().__init__(parent);self.asset=copy.deepcopy(asset);self.fields={};self.stages={};self.stage_buttons={};self.combos={};self.text_fields={};self.changed_fields={};self.changed_paths=();self.nonnegative_fields={}
        normalize_asset_construction(self.asset)
        apply_pipe_construction_defaults(self.asset)
        self.original_asset=copy.deepcopy(self.asset)
        asset=self.asset
        self.setWindowTitle("全线施工模板" if template else "施工与结构参数")
        self.edit_scope=show_scope and not context_title
        self.setObjectName("assetParameterEditor")
        self.setStyleSheet(PARAMETER_STYLE)
        available = self.screen().availableGeometry()
        self.resize(min(900, available.width()-32), min(680, available.height()-64))
        self.template=template;self.pipe=asset.get("kind") in ("pressure_pipe","siphon") or asset.get("section_type") in ("circular_culvert","circular_channel","circular_siphon")
        self.pipe_envelope_only=self.pipe and asset.get("section",{}).get("earthwork_envelope_only") is True
        pipe_construction = asset.get("construction", {})
        self.seat_key = "pipe_support" if "pipe_support" in pipe_construction and "pipe_seat" not in pipe_construction else "pipe_seat"
        self.enclosure_key = "pipe_encasement" if "pipe_encasement" in pipe_construction and "encasement" not in pipe_construction else "encasement"
        seat = pipe_construction.get(self.seat_key) or {}
        self.pipe_seat_width_mode=seat.get("bottom_width_mode","explicit")
        self.pipe_seat_chord_mode=self.pipe and self.pipe_seat_width_mode in {"support_chord","support_chord_plus_sides"}
        self.pipe_seat_trench_mode=self.pipe and self.pipe_seat_width_mode=="trench_bottom"
        self.pipe_seat_bedding_trench_mode=self.pipe_seat_trench_mode and seat.get("material_role")=="bedding"
        self.pit=asset.get("section_type")=="box_foundation" or asset.get("section_type")=="rectangular_pit" and (asset.get("kind") in ("pit","foundation","rectangular_pit") or asset.get("placement"))
        self.open=asset.get("section_type","").endswith("channel") and not self.pipe
        self.tunnel=asset.get("section_type") in {"arch_tunnel","circular_tunnel","flat_bottom_tunnel","horseshoe_tunnel"}
        self.aqueduct=asset.get("section_type") in {"aqueduct_u","aqueduct_rectangular"}
        self.crest_excavation=asset.get("section_type") in {"u_channel","trapezoidal_channel"}
        layout=QVBoxLayout(self);layout.setContentsMargins(16,14,16,12);layout.setSpacing(10)
        kind_label={"pipe":"有压管道","pressure_pipe":"有压管道","siphon":"倒虹吸"}.get(asset.get("kind"))
        self.structure_type_label=QLabel(kind_label or SECTION_NAMES.get(asset.get("section_type"),"基坑 / 基础" if self.pit else asset.get("section_type","结构参数")))
        self.structure_type_label.setObjectName("structureTypeLabel")
        header=QHBoxLayout();header.setSpacing(12)
        name=context_title or asset.get("name","")
        if name and name not in {"-","—",self.structure_type_label.text()}:
            context=QLabel(str(name));context.setObjectName("schemeTitle" if context_title else "parameterContext")
            context.setTextFormat(Qt.PlainText);context.setWordWrap(True)
            self.structure_type_label.setProperty("secondary",bool(context_title))
            if context_title:
                header.addWidget(context,1);header.addWidget(self.structure_type_label)
            else:
                header.addWidget(self.structure_type_label);header.addWidget(context,1)
        else:
            header.addWidget(self.structure_type_label);header.addStretch()
        layout.addLayout(header)
        self.tabs=QTabWidget();self.tabs.setObjectName("parameterTabs")
        self.tabs.setDocumentMode(True);layout.addWidget(self.tabs,1)
        structure=self.form_page("结构参数")
        if self.pit:
            for key,label in (("bottom_length","坑底总长（含工作面）"),("bottom_width","坑底总宽（含工作面）"),("floor_elevation","坑底高程"),("foundation_length","基础长"),("foundation_width","基础宽"),("foundation_height","基础高")):
                self.number(structure,"section."+key,label)
            xy=asset.get("placement",{}).get("center_xy",[None,None])
            for i,label in enumerate(("中心X","中心Y")):
                field=QLineEdit("" if xy[i] is None else str(xy[i]));self.fields[f"_center_{i}"]=field;structure.addRow(label+" m",field)
            direction=asset.get("placement",{}).get("direction")
            angle=math.degrees(math.atan2(direction[1],direction[0])) if direction else None
            self.number(structure,"placement.angle_degrees","平面方位角","°",fallback=angle)
        elif self.tunnel:
            typ=asset.get("section_type")
            if typ in {"circular_tunnel","flat_bottom_tunnel"}:
                self.number(structure,"section.inner_diameter","水面线净内径")
                if typ=="flat_bottom_tunnel":self.number(structure,"section.bottom_width","水面线平底净宽")
            elif typ=="horseshoe_tunnel":
                self.number(structure,"section.inner_radius","水面线标准马蹄形半径")
                self.choice(structure,"section.horseshoe_type","水面线马蹄形类别",[("标准马蹄形Ⅰ型",1),("标准马蹄形Ⅱ型",2)],default=1)
            else:
                for key,label,unit in (("inner_width","水面线净宽","m"),("inner_height","水面线实际结构净高","m"),("wall_height","水面线直墙净高","m"),("arch_angle_degrees","水面线拱圆心角","°")):
                    self.number(structure,"section."+key,label,unit)
            options=asset.get("source_tunnel_lining_options") or {}
            self.tunnel_lining_choice=QComboBox()
            self.tunnel_lining_choice.addItem("待选围岩方案或明确填写实际厚度",None)
            for rock,values in options.items():
                self.tunnel_lining_choice.addItem(f"{rock}  底板 {values['t0']} m / 墙拱 {values['t']} m",rock)
            self.tunnel_lining_choice.addItem("手动填写实际厚度","manual")
            selected=asset.get("section",{}).get("rock_class")
            if selected not in options and asset.get("section",{}).get("lining_thickness") is not None:
                selected="manual"
            self.tunnel_lining_choice.setCurrentIndex(max(0,self.tunnel_lining_choice.findData(selected)))
            structure.addRow("水面线围岩衬砌方案",self.tunnel_lining_choice)
            self.number(structure,"section.base_thickness","底板厚度 t₀",nonnegative=True)
            self.number(structure,"section.lining_thickness","边墙／顶拱衬砌法向厚度 t",nonnegative=True)
            for key,label in (("wall_thickness_left","来源左墙厚度"),("wall_thickness_right","来源右墙厚度"),("roof_thickness","来源顶拱厚度")):
                if asset.get("section",{}).get(key) is not None:self.number(structure,"section."+key,label,nonnegative=True)
            self.tunnel_lining_choice.currentIndexChanged.connect(self._tunnel_lining_option_changed)
            hint=QLabel("围岩方案采用当前水面线保存的 t₀、t。未选方案时须明确填写厚度；喷护和超挖未给时保留空白，无该项请填写 0。")
            hint.setWordWrap(True);structure.addRow(hint)
            self.number(structure,"section.shotcrete_thickness","初期喷护法向厚度",nonnegative=True)
            self.text(structure,"section.shotcrete_grade","初期喷护混凝土等级")
            self.fields["section.shotcrete_thickness"].setToolTip("喷护作为独立材料层计量；无喷护填0，不能以示例图尺寸代替本工程构造设计。")
        elif self.pipe:
            pipes=asset.get("section",{}).get("pipes")
            if not pipes:
                sec=asset.get("section",{});count=int(sec.get("pipe_count") or 1)
                pipes=[{key:sec[key] for key in ("inner_diameter","outer_diameter","wall_thickness","lining_thickness","lining_material",
                    "nominal_diameter_m","hydraulic_inner_diameter_m","earthwork_envelope_only","dn_envelope_diameter_m",
                    "diameter_basis","construction_inner_diameter_m") if key in sec} for _ in range(count)]
            self._pipe_original=copy.deepcopy(pipes)
            self.pipe_table=QTableWidget(len(pipes),7);self.pipe_table.setHorizontalHeaderLabels(["水力D / 净内径 m","采用外径 m","实际壁厚 m","管材","内衬厚 m","内衬材质","公称DN mm"])
            self.pipe_table.horizontalHeader().moveSection(6,0)
            self.pipe_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.pipe_table.horizontalHeader().setMinimumSectionSize(84)
            self.pipe_table.setMinimumHeight(min(260,70+38*len(pipes)))
            self.pipe_table.setMaximumHeight(280)
            self.pipe_table.setToolTip("DN默认作为施工占位外径；采用外径可按实际值覆盖。实际壁厚留空时不推算管壁或内衬材料数量。补真实壁厚后按采用外径减两侧壁厚/内衬确定实体净内径；原水力D仍独立保留。")
            for row,pipe in enumerate(pipes):
                for column,key in enumerate(("inner_diameter","outer_diameter","wall_thickness")):
                    value=pipe.get(key);self.pipe_table.setItem(row,column,QTableWidgetItem("" if value is None else str(value)))
                self.pipe_table.item(row,1).setData(Qt.UserRole,pipe.get("dn_envelope_diameter_m"))
                nominal=pipe.get("nominal_diameter_m",asset.get("section",{}).get("nominal_diameter_m"))
                self.pipe_table.setItem(row,6,QTableWidgetItem("" if nominal is None else f"{float(nominal)*1000:g}"))
                if nominal is not None:
                    self.pipe_table.item(row,0).setFlags(self.pipe_table.item(row,0).flags() & ~Qt.ItemIsEditable)
                    self.pipe_table.item(row,0).setToolTip("保留来源水力D；编辑公称DN和采用外径不会改写源水力成果。")
                material=self.pipe_material_box(pipe.get("material",asset.get("section",{}).get("material")))
                self.pipe_table.setCellWidget(row,3,material)
                lining=pipe.get("lining_thickness",asset.get("section",{}).get("lining_thickness",0.))
                self.pipe_table.setItem(row,4,QTableWidgetItem("" if lining is None else str(lining)))
                self.pipe_table.setCellWidget(row,5,self.lining_material_box(pipe.get("lining_material",asset.get("section",{}).get("lining_material"))))
            self.pipe_table.cellChanged.connect(self.refresh_dn_pipe_outer)
            structure.addRow(self.pipe_table)
            # A widget must own inline layouts while form rows are regrouped;
            # transferring a bare QLayoutItem can double-delete it at Qt shutdown.
            pipe_controls=QWidget();row=QHBoxLayout(pipe_controls);row.setContentsMargins(0,0,0,0)
            add=QPushButton("增加管道");add.clicked.connect(self.add_pipe_row);row.addWidget(add)
            remove=QPushButton("删除最后一根");remove.clicked.connect(lambda:self.pipe_table.removeRow(self.pipe_table.rowCount()-1) if self.pipe_table.rowCount()>1 else None);row.addWidget(remove);row.addStretch();structure.addRow(pipe_controls)
            self.number(structure,"section.pipe_spacing","相邻管净距")
            gap=asset.get("section",{}).get("pipe_spacing")
            if isinstance(gap,list):self.fields["section.pipe_spacing"].setText(", ".join(str(value) for value in gap))
            self.fields["section.pipe_spacing"].setPlaceholderText("统一净距，或用逗号分隔各净距")
            self.fields["section.pipe_spacing"].setToolTip("N根管可填一个统一净距，或依次填写N-1个净距（逗号分隔）。每个值均为米，原不同净距会分别保留。")
            self.choice(structure,"section.material","统一管材",[("分别设置",None),("混凝土","concrete"),("钢材","steel"),("球墨铸铁","ductile_iron"),("塑料/其他","other")],default=asset.get("section",{}).get("material"))
            self.combos["section.material"].currentIndexChanged.connect(self.apply_pipe_material)
        else:
            typ=asset.get("section_type")
            shape=[("inner_radius","净内半径"),("inner_height","水面线实际结构净高"),("u_arc_angle_degrees","底弧圆心角"),("u_side_angle_degrees","侧墙外倾角")] if typ in {"u_channel","aqueduct_u"} else [("inner_width","净底宽"),("inner_height","水面线实际结构净高")]
            if typ=="trapezoidal_channel":shape.append(("inner_side_slope","净空内坡比 1:m"))
            if typ=="compound_trapezoidal_channel":
                shape += [("compound_lower_height", "平台距渠底高度"), ("compound_bench_width", "平台宽度"),
                          ("compound_lower_slope", "左下侧内坡比 1:m"), ("compound_upper_slope", "左上侧内坡比 1:m"),
                          ("compound_right_slope", "右侧内坡比 1:m")]
            if typ=="arch_culvert":shape +=[("wall_height","直墙净高"),("arch_angle_degrees","拱圆心角")]
            for key,label in shape:
                path = "section." + key
                self.number(structure, path, label, "°" if "angle" in key else "" if "slope" in key else "m",
                            fallback=U_ANGLE_DEFAULTS.get(path))
            self.fields["section.inner_height"].setToolTip("来自当前水面线的实际结构高度。此处修改只作为本算量区段的用户覆盖，不改写源水面线成果；例图高度不覆盖本值。")
            for key,label in (("wall_thickness_left","左墙/衬砌厚度"),("wall_thickness_right","右墙/衬砌厚度"),("base_thickness","底板/底弧厚度")):
                fallback=asset.get("section",{}).get("wall_thickness") if key.startswith("wall_thickness_") else None
                self.number(structure,"section."+key,label,fallback=fallback)
            if not self.open and not self.aqueduct:self.number(structure,"section.roof_thickness","顶板/拱圈厚度")
            if typ=="rectangular_culvert":
                chamfers=asset.get("section",{}).get("inner_chamfers")
                uniform=_uniform_chamfer(chamfers)
                if isinstance(chamfers,dict) and uniform is None:
                    names={"bottom_left":"左下","bottom_right":"右下","top_left":"左上","top_right":"右上"}
                    label=QLabel("；".join(names.get(key,key)+"："+str(value)+" m" for key,value in chamfers.items()))
                    label.setWordWrap(True);structure.addRow("内倒角（分别设置，保留原值）",label)
                else:
                    self.number(structure,"section.inner_chamfers","四角统一内倒角",fallback=0.)
                    field=self.fields["section.inner_chamfers"]
                    field.setText(str(uniform if uniform is not None else 0.))
                    self._chamfer_display=field.text()
                    field.setToolTip("四个内角均采用等边直角倒角；边长单位为米。填0表示无倒角。")
            all_link=QPushButton("底板、左右墙同厚" if self.open or self.aqueduct else "底板、左右墙、顶板同厚")
            all_link.setToolTip("采用已填写的左墙厚度统一设置；也可在上方分别填写各部位厚度。")
            def link_structure_thickness():
                value=self.fields["section.wall_thickness_left"].text()
                for key in ("wall_thickness_right","base_thickness","roof_thickness"):
                    if "section."+key in self.fields:self.fields["section."+key].setText(value)
            all_link.clicked.connect(link_structure_thickness);structure.addRow(all_link)
        self.text(structure,"section.material_grade","管身材料等级" if self.pipe else "结构混凝土/主材等级")
        construction=self.form_page("施工参数")
        if self.pipe:
            self.add_pipe_construction_defaults(construction)
        if bedding_applicable(asset) and not (self.tunnel or self.aqueduct):
            for key,label in (("bedding_thickness","垫层厚度"),("bedding_extension","垫层每侧外伸")):
                self.number(construction,"construction."+key,label)
            self.text(construction,"construction.bedding_grade","找平/垫层材料等级")
        if self.tunnel:
            label=QLabel("隧洞按封闭洞身外轮廓计挖方，初期喷护在永久衬砌外侧，超挖余量继续向外偏移；不生成地表明挖放坡。")
            label.setWordWrap(True);construction.addRow(label)
            self.number(construction,"construction.excavation_clearance","洞周法向超挖预留",nonnegative=True)
            self.text(construction,"construction.overbreak_material","超挖环隙填充材料",placeholder="未提供填充材料，不推定为土方回填")
            self.text(construction,"construction.overbreak_grade","超挖环隙填充材料等级")
        elif self.aqueduct:
            label=QLabel("槽身按水面线净空及衬砌厚度计算。墩台、基础、拉杆在“渡槽附属构件”逐项提供；本页参数用于勾选基础挖槽的构件。前后施工工作面及端坡沿构件起止桩方向展开，左右参数沿横断面展开。")
            label.setWordWrap(True);construction.addRow(label)
            for side,label in (("left","左"),("right","右"),("front","前"),("back","后")):
                self.number(construction,"construction.working_space_"+side,label+"基础施工工作面",nonnegative=True)
                self.number(construction,"construction.excavation_slope_"+side,label+"基础开挖坡比1:m","",nonnegative=True)
                self.stage_button(construction,"excavation_stages_"+side,label+"基础开挖分级/马道")
            for key,label in (("bedding_thickness","基础垫层厚度"),("bedding_extension","基础垫层每侧外伸")):
                self.number(construction,"construction."+key,label,nonnegative=True)
            self.text(construction,"construction.bedding_grade","基础垫层材料等级")
        else:
            if self.crest_excavation:
                label=QLabel("U型、梯形明渠沿渠身外轮廓开挖；在渠顶高程向两侧展开平台，再由平台外缘放坡接原地面。渠底工作面与平底沟槽模式不用于此类断面。")
                label.setWordWrap(True);construction.addRow(label)
                self.number(construction,"construction.excavation_clearance","渠身外轮廓法向施工余量",fallback=0.,nonnegative=True)
            elif asset.get("section_type")=="rectangular_channel":
                label=QLabel("矩形明渠从渠底施工工作面两侧起坡，保留现有开挖方式。")
                label.setWordWrap(True);construction.addRow(label)
            sides=("left","right","front","back") if self.pit else ("left","right")
            for side,label in zip(sides,("左","右","前","后")):
                if not self.crest_excavation:
                    work_label=(label+"施工工作面（从管外壁起）" if self.pipe and (self.pipe_seat_trench_mode or asset.get("construction",{}).get("working_space_reference")=="pipe_outer")
                                else label+"渠底施工工作面" if self.open else label+"施工工作面")
                    self.number(construction,"construction.working_space_"+side,work_label)
                self.number(construction,"construction.excavation_slope_"+side,label+"开挖坡比1:m","")
                self.stage_button(construction,"excavation_stages_"+side,label+"开挖分级/马道")
            if not self.pit and not self.crest_excavation:self.choice(construction,"construction.excavation_base_mode","开挖底面",[("平底沟槽","flat"),("沿结构外轮廓" if not bedding_applicable(asset) else "沿结构/垫层外轮廓","offset")],default="flat")
        self.add_layered_excavation(construction)
        if self.open:
            for side,label in (("left","左"),("right","右")):
                self.number(construction,"construction.bank_top_width_"+side,label+"渠顶平台宽",nonnegative=True)
                if self.crest_excavation:self.fields["construction.bank_top_width_"+side].setToolTip("从渠顶结构外缘向外的水平平台宽。开挖边坡由平台外缘、渠顶高程起坡；填筑边坡也由该平台外缘起坡。填0表示直接从渠顶外缘起坡。")
                self.number(construction,"construction.bank_slope_"+side,label+"填筑坡比1:m","")
                self.stage_button(construction,"bank_stages_"+side,label+"填筑分级/马道")
            _set(self.asset,"construction.target_mode","union_terrain")
        elif self.pit:_set(self.asset,"construction.target_mode","restore_terrain")
        elif self.tunnel or self.aqueduct:pass
        else:
            if is_circular_culvert(asset) and not asset.get("transition_candidate_id"):
                label=QLabel("圆管涵对应程序结构形式“明渠-圆形”，安装后地下挖槽回填至原地面；已设平台和填坡参数的地上支承填筑另列新增填筑。另有明确覆土设计时，可选择覆土完成面并填写覆土厚度；圆管内净空不计回填。")
                label.setWordWrap(True);construction.addRow(label)
            choices=[("恢复原地面","restore_terrain"),("按覆土完成面填筑","cover_depth")]
            if asset.get("construction",{}).get("target_mode")=="union_terrain":
                choices.append(("沿用当前结构与地形完成面","union_terrain"))
            if asset.get("transition_candidate_id"):
                choices.append(("仅在原地面以上补足涵顶覆土","cover_above_terrain"))
            if asset.get("construction",{}).get("target_mode")=="finished_profile":
                choices.append(("保留已提供的设计完成面","finished_profile"))
            self.choice(construction,"construction.target_mode","施工完成后",choices,default="restore_terrain")
            self.number(construction,"construction.final_cover_depth","管／涵顶至回填完成面",nonnegative=True)
            final_depth=self.fields["construction.final_cover_depth"]
            final_depth.setToolTip("从结构外顶至设计回填完成面的竖向距离，用于计算填筑量。")
            final_label=construction.labelForField(final_depth)
            target_mode=self.combos["construction.target_mode"]
            def show_final_depth():
                visible=target_mode.currentData() in {"cover_depth","cover_above_terrain"}
                final_label.setVisible(visible)
                final_depth.setVisible(visible)
            target_mode.currentIndexChanged.connect(show_final_depth)
            show_final_depth()
            for side,label in (("left","左"),("right","右")):
                self.number(construction,"construction.bank_top_width_"+side,label+"完成面平台宽")
                self.number(construction,"construction.bank_slope_"+side,label+"填筑坡比1:m","")
                self.stage_button(construction,"bank_stages_"+side,label+"填筑分级/马道")
        if self.pipe:
            burial=self.form_page("管座与包封")
            self.pipe_support_form=burial
            self.choice(burial,"construction.installation_mode","敷设",[("明挖埋管","buried"),("明管（不算基础）","exposed"),("架空（不算基础）","elevated")],default="buried")
            if context_title:
                burial.setRowVisible(self.combos["construction.installation_mode"],False)
            if is_pressure_cover_asset(asset):
                from .pipe_profile_sources import profile_source_label
                source=QLabel(profile_source_label(asset))
                source.setTextFormat(Qt.PlainText)
                source.setWordWrap(True)
                source.setObjectName("constructionProfileSource")
                source.setToolTip("在工程对象的「设计纵断面」页签选择来源或设置管顶覆土。")
                burial.addRow("管轴高程来源",source)
            else:
                self.choice(burial,"construction.burial_mode","高程来源",[("设计纵断面","actual_axis"),("按涵顶覆土生成","cover_depth")],default="actual_axis")
                self.number(burial,"construction.cover_depth","原地面至涵外顶",fallback=DEFAULT_WORKBENCH_COVER_M,nonnegative=True)
                culvert_depth=self.fields["construction.cover_depth"]
                culvert_mode=self.combos["construction.burial_mode"]
                def show_culvert_depth():
                    burial.setRowVisible(culvert_depth,culvert_mode.currentData()=="cover_depth")
                culvert_mode.currentIndexChanged.connect(show_culvert_depth)
                show_culvert_depth()
            seat_title="包角垫层 / 管基" if seat.get("material_role")=="bedding" else "混凝土管座"
            self.pipe_optional_details={}
            groups=[(self.seat_key,seat_title,[]),
                    (self.enclosure_key,"混凝土包封",[("top_thickness","顶部厚度"),("bottom_thickness","底部厚度")])]
            def active(group):
                config=pipe_construction.get(group) or {}
                return bool(config) and config.get("enabled",True)
            groups.sort(key=lambda item:not active(item[0]))
            for group,title,fields in groups:
                if context_title and not active(group):
                    continue
                grade = (pipe_construction.get(group) or {}).get("grade")
                group_title = f"{title} · {grade}" if grade else title
                container=QGroupBox(group_title if context_title else "")
                optional_form=QFormLayout(container);align_form(optional_form)
                optional_form.setContentsMargins(14,14 if context_title else 8,14,10)
                burial.addRow(container)
                check=QCheckBox(title);check.setChecked(active(group))
                self.fields["construction."+group+".enabled"]=check
                optional_form.addRow(check);optional_form.setRowVisible(check,not context_title)
                details=QWidget();parameters=QFormLayout(details);align_form(parameters);parameters.setContentsMargins(0,0,0,0)
                self.pipe_optional_details[group]=details;optional_form.addRow(details)
                check.toggled.connect(details.setVisible)
                if group==self.seat_key:
                    self._add_seat_dimensions(parameters,seat,bool(context_title))
                else:
                    for key,label in fields:
                        self.number(parameters,"construction."+group+"."+key,label,nonnegative=True)
                    top = self.fields[f"construction.{group}.top_thickness"]
                    bottom = self.fields[f"construction.{group}.bottom_thickness"]
                    pair = pair_fields(parameters, top, bottom)
                    self.encasement_sides=EncasementSides(pipe_construction.get(group) or {})
                    parameters.addRow(self.encasement_sides)
                    for key,edit in self.encasement_sides.fields.items():
                        self.fields[f"construction.{group}.{key}"]=edit
                    snapshot = (asset.get("section_scheme_binding") or {}).get("scheme_snapshot") or {}
                    from 土石方计算.services.section_scheme_catalog import encasement_uniform_dimension
                    symbol = encasement_uniform_dimension(snapshot)
                    if symbol:
                        sides = self.encasement_sides
                        self.encasement_thickness = DrawingSharedDimension(
                            parameters, (pair, sides), (sides.fields["side_thickness"], top, bottom),
                            f"四面包封厚度 {symbol}（m）", "分别设置各面厚度", sides=sides)
                details.setVisible(check.isChecked())
            if hasattr(self,"pipe_seat_width_hint"):
                self.pipe_table.cellChanged.connect(self.refresh_pipe_seat_width)
                self.pipe_table.model().rowsRemoved.connect(self.refresh_pipe_seat_width)
                self.pipe_table.model().rowsInserted.connect(self.refresh_pipe_seat_width)
                for key in ("support_angle","height","extension","bottom_width"):
                    edit=self.fields.get(f"construction.{self.seat_key}.{key}")
                    if edit is not None:edit.textChanged.connect(self.refresh_pipe_seat_width)
                if self.pipe_seat_trench_mode:
                    self.fields["section.pipe_spacing"].textChanged.connect(self.refresh_pipe_seat_width)
                    for side in ("left","right"):
                        self.fields["construction.working_space_"+side].textChanged.connect(self.refresh_pipe_seat_width)
                    if self.pipe_seat_bedding_trench_mode:
                        self.combos[f"construction.{self.seat_key}.side_boundary_mode"].currentIndexChanged.connect(self.refresh_pipe_seat_width)
                self.refresh_pipe_seat_width()
        if self.aqueduct:self.add_discrete_components()
        if self.aqueduct or self.tunnel:
            self.add_quantity_rules();self.add_quantity_scope()
        self.add_drawing_material_details()
        if not self.pit:
            self.application_options=CollapsibleParameterGroup("应用范围与桩号（可选）",expanded=template)
            layout.addWidget(self.application_options)
            self.application_options.setVisible(self.edit_scope)
            scope=QHBoxLayout();self.scope=QComboBox()
            self.scope.addItem("本区段","asset");self.scope.addItem("同结构形式全部区段（施工与厚度）","type");self.scope.addItem("全线施工默认（保留净尺寸）","all")
            self.scope.setCurrentIndex(2 if template else 0);scope.addWidget(QLabel("应用范围"));scope.addWidget(self.scope);self.application_options.form.addRow(scope)
            override=QHBoxLayout();self.start=QLineEdit(str(asset.get("station_start","")));self.end=QLineEdit(str(asset.get("station_end","")))
            override.addWidget(QLabel("本区段覆盖起止桩号 m"));override.addWidget(self.start);override.addWidget(self.end);self.application_options.form.addRow(override)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.button(QDialogButtonBox.Ok).setText("采用参数" if context_title else "保存参数")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.Ok).setObjectName("saveParameters")
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self._organize_parameter_pages(structure,construction)
        self.tabs.tabBar().moveTab(1,0)
        if context_title and self.pipe:
            self.select_page("pipe_support")
            self.tabs.tabBar().moveTab(self.tabs.currentIndex(),0)
        self.select_page(initial_page)
        if hasattr(self,"layer_mode"):
            self.layer_mode.currentIndexChanged.connect(self.refresh_layered_excavation)
            installation=self.combos.get("construction.installation_mode")
            if installation is not None:installation.currentIndexChanged.connect(self.refresh_layered_excavation)
            self.refresh_layered_excavation()

        if not defer_preview:
            from .parameter_section_view import supports_parameter_section
            if supports_parameter_section(self.asset):
                from .parameter_preview_binding import attach_parameter_preview
                scheme = preview_scheme or (self.asset.get("section_scheme_binding") or {}).get("scheme_snapshot") or {}
                self.parameter_preview = attach_parameter_preview(self, self.tabs, self.asset, scheme)

    def form_page(self,name):
        page=QWidget();page.setObjectName("parameterPage")
        form=QFormLayout(page);align_form(form);form.setContentsMargins(14,12,14,14)
        scroll=QScrollArea();scroll.setFrameShape(QFrame.NoFrame);scroll.setWidgetResizable(True)
        scroll.setWidget(page);self.tabs.addTab(scroll,name)
        return form

    def select_page(self,page):
        title={"pipe_support":"管座与包封","construction":"施工参数","structure":"结构参数"}.get(page,page)
        index=next((i for i in range(self.tabs.count()) if self.tabs.tabText(i)==title),0)
        self.tabs.setCurrentIndex(index)

    def _organize_parameter_pages(self,structure,construction):
        """Arrange existing editors only; the parameter and save contracts stay intact."""
        self.parameter_groups={}
        by_widget={field:path for values in (self.fields,self.text_fields,self.combos) for path,field in values.items()}
        stage_widgets=set(self.stage_buttons.values())
        layered_widgets={getattr(self,name,None) for name in ("layer_mode","layer_hint","layer_link")}
        layered_widgets.discard(None)
        def structure_group(widget):
            path=by_widget.get(widget,"")
            if path in self.text_fields or path=="section.material":return "材料等级"
            if "thickness" in path or path=="section.inner_chamfers" or isinstance(widget,QPushButton) and "同厚" in widget.text():return "结构厚度"
            return "断面尺寸"
        def construction_group(widget):
            path=by_widget.get(widget,"")
            if widget is getattr(self,"pipe_recommendation",None):return "施工参考值"
            if widget in getattr(self,"pipe_default_widgets",()) or path.startswith("construction.backfill_partition."):return "沟槽回填"
            if widget in stage_widgets or widget in layered_widgets or path.removeprefix("construction.") in LAYERED_EXCAVATION_FIELDS:return "分级与分层（选填）"
            if path.startswith("construction.bedding_"):return "垫层与找平"
            if path.startswith("construction.bank_") or path in {"construction.target_mode","construction.final_cover_depth"}:return "回填与完成面"
            return "开挖与工作面" if not self.tunnel else "洞身超挖与填充"
        self._group_form_rows(structure,structure_group,("断面尺寸","结构厚度","材料等级"))
        excavation_name="洞身超挖与填充" if self.tunnel else "开挖与工作面"
        if self.pipe:
            fill=self.form_page("回填与完成面")
            self.tabs.tabBar().moveTab(self.tabs.count()-1,3)
            self._group_form_rows(construction,construction_group,
                (excavation_name,"分级与分层（选填）","施工参考值","垫层与找平","回填与完成面","沟槽回填"),
                destinations={"回填与完成面":fill,"沟槽回填":fill,"垫层与找平":self.pipe_support_form})
            for title,stem in ((excavation_name,"working_space"),(excavation_name,"excavation_slope"),
                               ("回填与完成面","bank_top_width"),("回填与完成面","bank_slope")):
                group=self.parameter_groups.get(title)
                if group is not None:
                    left, right = (self.fields[f"construction.{stem}_{side}"] for side in ("left", "right"))
                    pair = pair_fields(group.layout(), left, right)
                    if stem == "working_space":
                        from 土石方计算.services.section_scheme_catalog import drawing_workspace_dimension
                        symbol = drawing_workspace_dimension((self.asset.get("section_scheme_binding") or {}).get("scheme_snapshot"))
                        if symbol:
                            self.drawing_workspace = DrawingSharedDimension(
                                group.layout(), (pair,), (left, right), f"每侧施工工作面 {symbol}（m）", "分别设置左右工作面")
            bedding=self.parameter_groups.get("垫层与找平")
            if bedding:
                form = bedding.form if isinstance(bedding, CollapsibleParameterGroup) else bedding.layout()
                pair_fields(form,self.fields["construction.bedding_thickness"],
                            self.fields["construction.bedding_extension"])
        else:
            self._group_form_rows(construction,construction_group,
                (excavation_name,"回填与完成面","垫层与找平","分级与分层（选填）"),columns=2)

    def add_pipe_construction_defaults(self,form):
        """Keep supplied construction recommendations and editable fill rules visible."""
        options=self.asset.get("construction",{}).get("pipe_default_options",{})
        hint=QLabel();hint.setWordWrap(True);hint.setObjectName("pipeConstructionDefaultsHint")
        if options.get("status")=="READY":
            hint.setText("表7.2　单侧工作面 {working_space_m:g} m　·　砂垫层 {sand_bedding_thickness_m:g} m\n"
                "外基座厚 {concrete_seat_thickness_m:g} m　·　外包混凝土厚 {encasement_thickness_m:g} m".format(**options))
        else:
            hint.setText("表7.2按Excel管径D加载管道施工默认值；表内分档为D≤0.5 m、0.5＜D≤1.0 m、1.0＜D≤3.0 m。超出范围须填写工作面及支承尺寸。")
        self.pipe_recommendation=hint;form.addRow(hint);self.pipe_default_widgets=[]
        self.number(form,"construction.backfill_partition.above_crown_height_m","人工夯实至管顶以上",
                    fallback=DEFAULT_MANUAL_BACKFILL_HEIGHT_M,nonnegative=True)
        self.number(form,"construction.backfill_partition.max_particle_size_mm","人工回填区最大硬块粒径","mm",fallback=50.,nonnegative=True)
        for key,label in (("exclude_organic_material","人工回填区不得含有机物"),
                          ("exclude_frozen_soil","人工回填区不得含冻土"),
                          ("fine_soil_at_sensitive_locations","接口、防腐层、电缆周围采用细粒土")):
            path="construction.backfill_partition."+key
            check=QCheckBox(label);check.setChecked(_get(self.asset,path) is not False)
            self.fields[path]=check;form.addRow(check);self.pipe_default_widgets.append(check)
        note=QLabel("无特殊地面荷载要求时，槽底至管顶以上所设高度范围采用人工夯实，以上至完成地面采用机械夯实。")
        note.setWordWrap(True);form.addRow(note);self.pipe_default_widgets.append(note)

    def _group_form_rows(self,form,classify,order,*,columns=1,destinations=None):
        rows={name:[] for name in order}
        while form.rowCount():
            row=form.takeRow(0)
            rows[classify(row.fieldItem.widget())].append(row)
        grid=QGridLayout() if columns>1 else None
        if grid is not None:
            grid.setAlignment(Qt.AlignTop);grid.setHorizontalSpacing(14);grid.setVerticalSpacing(12)
            for column in range(columns):grid.setColumnStretch(column,1)
        position=0
        for title in order:
            if not rows[title]:continue
            if title=="分级与分层（选填）":
                active=any(self.stages.values()) or _get(self.asset,"construction.excavation_layer_mode")=="surface_thickness"
                group=CollapsibleParameterGroup(title,expanded=active);target=group.form
            elif title == "垫层与找平" and optional_support_bedding(
                    (self.asset.get("section_scheme_binding") or {}).get("scheme_snapshot")):
                group = CollapsibleParameterGroup("支承底部独立垫层（可选）",
                                                  expanded=bool(_get(self.asset, "construction.bedding_thickness")))
                target = group.form
            else:
                group=QGroupBox(title);target=QFormLayout(group)
                target.setContentsMargins(12,16,12,12);align_form(target)
            self.parameter_groups[title]=group
            for row in rows[title]:
                label=row.labelItem.widget() if row.labelItem else None
                field=row.fieldItem.widget() or row.fieldItem.layout()
                if label is not None:target.addRow(label,field)
                else:target.addRow(field)
            if grid is None:(destinations or {}).get(title,form).addRow(group)
            elif isinstance(group,CollapsibleParameterGroup):
                grid.addWidget(group,(position+columns-1)//columns,0,1,columns,Qt.AlignTop)
            else:
                grid.addWidget(group,position//columns,position%columns,Qt.AlignTop);position+=1
        if grid is not None:form.addRow(grid)

    def pipe_material_box(self,value=None):
        box=QComboBox()
        for name,key in (("需核对",None),("混凝土","concrete"),("钢材","steel"),("球墨铸铁","ductile_iron"),("塑料/其他","other")):box.addItem(name,key)
        aliases={"rc":"concrete","混凝土":"concrete","钢筋混凝土":"concrete","钢管":"steel","钢材":"steel","plastic":"other","pvc":"other","hdpe":"other",
                 "di":"ductile_iron","球墨铸铁":"ductile_iron","球墨铸铁管":"ductile_iron"}
        value=aliases.get(str(value).lower(),value)
        if value is not None and box.findData(value)<0:box.addItem("保留原管材："+str(value),value)
        box.setCurrentIndex(max(0,box.findData(value)));return box

    def add_pipe_row(self):
        row=self.pipe_table.rowCount();self.pipe_table.insertRow(row)
        for column in (0,1,2,6):self.pipe_table.setItem(row,column,QTableWidgetItem(""))
        self.pipe_table.setCellWidget(row,3,self.pipe_material_box(self.combos["section.material"].currentData()))
        self.pipe_table.setItem(row,4,QTableWidgetItem("0"))
        self.pipe_table.setCellWidget(row,5,self.lining_material_box())

    def refresh_dn_pipe_outer(self,row,column):
        """Keep an automatic DN occupation visible while retaining actual overrides."""
        if column not in (1,6):return
        outer=self.pipe_table.item(row,1)
        if outer is None:return
        try:
            text=outer.text().strip();current=float(text) if text else None
            auto=outer.data(Qt.UserRole)
            if column==1:
                if auto is not None and current!=float(auto):
                    self.pipe_table.blockSignals(True);outer.setData(Qt.UserRole,None);self.pipe_table.blockSignals(False)
                return
            nominal=float(self.pipe_table.item(row,6).text())/1000.
            if not math.isfinite(nominal) or nominal<=0:return
            if current is None or auto is not None and current==float(auto):
                self.pipe_table.blockSignals(True)
                outer.setText(f"{nominal:g}");outer.setData(Qt.UserRole,nominal)
                self.pipe_table.blockSignals(False)
                if hasattr(self,"pipe_seat_width_hint"):self.refresh_pipe_seat_width()
        except (ValueError,TypeError,AttributeError):return

    def _add_seat_dimensions(self,form,seat,drawing):
        self._seat_form=form
        prefix=f"construction.{self.seat_key}."
        mode=self.pipe_seat_width_mode
        bedding=seat.get("material_role")=="bedding"
        self.number(form,prefix+"support_angle","垫层包角（中心角）" if bedding else "支承角","°",nonnegative=True)
        self.fields[prefix+"support_angle"].setPlaceholderText(f"采用 {seat.get('angle',120)}°")
        self.number(form,prefix+"base_thickness","管外底以下垫层厚度" if bedding else "管外底以下管座厚度",nonnegative=True)
        if mode not in {"support_chord","trench_bottom"} and (not drawing or seat.get("height") is not None):
            self.number(form,prefix+"height","支承高度",nonnegative=True)
            self.fields[prefix+"height"].setPlaceholderText("按支承角计算")
        if mode=="explicit":
            self.number(form,prefix+"bottom_width","指定底宽",nonnegative=True)
            self.fields[prefix+"bottom_width"].setPlaceholderText("按管外径与两侧外伸计算")
        if mode in {"explicit","inner_diameter_offset","support_chord_plus_sides"}:
            self.number(form,prefix+"extension","每侧外伸",nonnegative=True)
        if self.pipe_seat_bedding_trench_mode:
            self.choice(form,prefix+"side_boundary_mode","垫层两侧边界",[
                ("延伸至实际开挖边坡","excavation"),("竖直侧边（历史构造）","vertical")],default="excavation")
        if self.pipe_seat_trench_mode:
            self.pipe_seat_side_hint=QLabel()
            self.pipe_seat_side_hint.setWordWrap(True)
            form.addRow(self.pipe_seat_side_hint)
        self.pipe_seat_width_hint=QLineEdit()
        self.pipe_seat_width_hint.setReadOnly(True)
        label="计算底宽"
        if self.pipe_seat_trench_mode:
            label="垫层铺满槽底工作面 · 槽底宽" if self.pipe_seat_bedding_trench_mode else "槽底宽"
        self.pipe_seat_width_hint.setAccessibleName(label+"（m）")
        form.addRow(label+" m",self.pipe_seat_width_hint)

    def _seat_preview_pipes(self):
        """Read the current envelopes, including spacing-derived or explicit offsets."""
        pipes=[]
        for row in range(self.pipe_table.rowCount()):
            def number_at(column):
                item=self.pipe_table.item(row,column)
                return float(item.text()) if item and item.text().strip() else None
            outer,inner,wall,lining=number_at(1),number_at(0),number_at(2),number_at(4) or 0.
            if outer is None:
                nominal=number_at(6)
                if nominal is not None:
                    outer=nominal/1000.
                elif inner is not None and wall is not None:
                    outer=inner+2*(wall+lining)
            if outer is None or not math.isfinite(outer) or outer<=0:raise ValueError("请核对施工外径")
            # The quantity geometry uses the outside envelope as the bore when
            # no actual wall is supplied, and the constructed bore otherwise.
            bore=outer-2*((wall or 0.)+lining)
            if not math.isfinite(bore) or bore<=0:raise ValueError("请核对壁厚及内衬")
            pipe={"outer_diameter":outer,"seat_bore":bore,"earthwork_envelope_only":True}
            if row<len(self._pipe_original) and self.asset.get("cover_pipe_layout_mode")!="spacing":
                offset=self._pipe_original[row].get("offset")
                if offset is not None:pipe["offset"]=offset
            pipes.append(pipe)
        if not pipes:raise ValueError("请填写管径")
        if self.pipe_seat_trench_mode:
            text=self.fields["section.pipe_spacing"].text().strip().replace("，",",")
            if len(pipes)>1 and not text and not all("offset" in pipe for pipe in pipes):
                raise ValueError("请填写相邻管净距")
            spacing=0.
            if text:
                spacing=[float(value) for value in text.split(",")] if "," in text else float(text)
            return pipe_specs({"pipes":pipes,"pipe_spacing":spacing})
        return pipes

    def refresh_pipe_seat_width(self,*_args):
        mode=self.pipe_seat_width_mode
        prefix=f"construction.{self.seat_key}."
        form=self._seat_form
        height=self.fields.get(prefix+"height")
        form.setRowVisible(self.fields[prefix+"support_angle"],self.pipe_seat_chord_mode or not height or not height.text().strip())
        explicit=self.fields.get(prefix+"bottom_width")
        use_explicit=bool(explicit and explicit.text().strip())
        if explicit:
            form.setRowVisible(self.fields[prefix+"extension"],not use_explicit)
        form.setRowVisible(self.pipe_seat_width_hint,not use_explicit)
        if use_explicit:return
        formulas={"trench_bottom":"管排最外缘跨度 + 左右工作面","support_chord":"施工外径 × sin(包角/2)",
                  "support_chord_plus_sides":"施工外径 × sin(包角/2) + 2 × 每侧外伸",
                  "inner_diameter_offset":"断面计算净径 + 2 × 每侧外伸","explicit":"施工外径 + 2 × 每侧外伸"}
        formula=formulas.get(mode)
        if formula is None:
            self.pipe_seat_width_hint.setText("请核对管座底宽取法")
            return
        if self.pipe_seat_trench_mode:
            excavation=self.pipe_seat_bedding_trench_mode and self.combos[prefix+"side_boundary_mode"].currentData()=="excavation"
            note=("垫层顶面延伸至实际开挖边坡，计入左右两侧三角形。" if excavation else "历史竖直侧边，顶宽同槽底宽。")
            self.pipe_seat_side_hint.setText(note)
            formula+="，工作面从管外壁起。"+note
        self.pipe_seat_width_hint.setToolTip(formula)
        try:
            pipes=self._seat_preview_pipes()
            if self.pipe_seat_trench_mode:
                left,right=(float(self.fields["construction.working_space_"+side].text() or 0) for side in ("left","right"))
                if not all(math.isfinite(v) and v>=0 for v in (left,right)):raise ValueError("请核对左右工作面")
                span=max(p["offset"]+p["outer_diameter"]/2 for p in pipes)-min(p["offset"]-p["outer_diameter"]/2 for p in pipes)
                self.pipe_seat_width_hint.setText(f"{span+left+right:.6f}（槽底宽）")
                return
            extension=self.fields.get(prefix+"extension")
            margin=float(extension.text() or 0.) if extension else 0.
            if not math.isfinite(margin) or margin<0:raise ValueError("请核对每侧外伸")
            chord=1.
            if self.pipe_seat_chord_mode:
                fallback=(self.asset["construction"][self.seat_key]).get("angle",120)
                angle=float(self.fields[prefix+"support_angle"].text() or fallback)
                if not 0<angle<180:raise ValueError("包角应大于 0° 并小于 180°")
                chord=math.sin(math.radians(angle/2))
            widths=[(p["seat_bore"] if mode=="inner_diameter_offset" else p["outer_diameter"]*chord)+2*margin for p in pipes]
            values=f"{widths[0]:.6f}"
            if len(widths)>1:
                entries=[f"{i}号管 {w:.6f}" for i,w in enumerate(widths,1)]
                values="　".join(entries)
                self.pipe_seat_width_hint.setToolTip(formula+"\n"+"\n".join(value+" m" for value in entries))
            self.pipe_seat_width_hint.setText(values+"（"+formula+"）")
            self.pipe_seat_width_hint.setCursorPosition(0)
        except (ValueError,TypeError,KeyError) as error:
            self.pipe_seat_width_hint.setText(str(error) if isinstance(error,ValueError) and not str(error).startswith("could not convert") else "请核对管径及尺寸")

    def lining_material_box(self,value=None):
        box=self.pipe_material_box(value)
        box.addItem("与本管管壁同材","same_as_wall")
        box.setCurrentIndex(max(0,box.findData(value)))
        return box

    def apply_pipe_material(self):
        value=self.combos["section.material"].currentData()
        if value is not None:
            for row in range(self.pipe_table.rowCount()):
                box=self.pipe_table.cellWidget(row,3);box.setCurrentIndex(box.findData(value))

    def number(self,form,path,label,unit="m",fallback=None,*,nonnegative=False):
        value=_get(self.asset,path)
        if value is None:value=fallback
        field=QLineEdit("" if value is None else str(value));field.setPlaceholderText("未提供")
        field.setAccessibleName(label);field.setProperty("parameter_path",path)
        self.fields[path]=field;form.addRow(label+(" "+unit if unit else ""),field)
        if nonnegative:self.nonnegative_fields[path]=label

    def add_layered_excavation(self,form):
        if self.asset.get("section_type") not in LAYERED_EXCAVATION_SECTION_TYPES:
            if self.asset.get("construction",{}).get("excavation_layer_mode")=="surface_thickness":
                label=QLabel("此结构不支持简化分层开挖；请先核对结构类型与已有分层参数。")
                label.setWordWrap(True);form.addRow(label)
            return
        self.choice(form,"construction.excavation_layer_mode","开挖分层方式",
            [("原单层/分级边坡","none"),("简化分层：原地面竖直下移厚度","surface_thickness")],default="none")
        self.layer_mode=self.combos["construction.excavation_layer_mode"]
        self.layer_hint=QLabel("基覆界面按各位置原地面高程减去覆盖层竖直厚度生成，属于简化假定。与管顶覆土厚度无关；两层坡比均须由用户提供。已有开挖分级/马道须先清空，才能启用简化分层。")
        self.layer_hint.setWordWrap(True);form.addRow(self.layer_hint)
        self.number(form,"construction.overburden_thickness","覆盖层竖直厚度",nonnegative=True)
        for layer,name in (("overburden","覆盖层"),("bedrock","基岩")):
            for side,label in (("left","左"),("right","右")):
                self.number(form,"construction."+layer+"_slope_"+side,label+name+"开挖坡比1:m","",nonnegative=True)
        self.layer_link=QPushButton("分层坡比左右相同（左 → 右）")
        def copy_left_slopes():
            for layer in ("overburden","bedrock"):
                self.fields["construction."+layer+"_slope_right"].setText(self.fields["construction."+layer+"_slope_left"].text())
        self.layer_link.clicked.connect(copy_left_slopes);form.addRow(self.layer_link)

    def refresh_layered_excavation(self):
        asset=copy.deepcopy(self.asset)
        installation=self.combos.get("construction.installation_mode")
        if installation is not None:asset.setdefault("construction",{})["installation_mode"]=installation.currentData()
        applicable=layered_excavation_applicable(asset)
        active=self.layer_mode.currentData()=="surface_thickness"
        stages=any(self.stages.get("excavation_stages_"+side) for side in ("left","right"))
        if self.sender() is self.layer_mode and active and stages:
            QMessageBox.warning(self,"分层开挖需要核对","请先在左右开挖分级/马道中清空已有分级，再启用简化分层；原分级数据已保留。")
            self.layer_mode.blockSignals(True);self.layer_mode.setCurrentIndex(self.layer_mode.findData("none"));self.layer_mode.blockSignals(False)
            active=False
        self.layer_mode.setEnabled(applicable or active)
        self.layer_mode.setToolTip("仅适用于普通线性明挖；明管、架空管、隧洞、基坑及专用结构不适用。")
        for key in LAYERED_EXCAVATION_FIELDS[1:]:self.fields["construction."+key].setEnabled(active and applicable)
        self.layer_link.setEnabled(active and applicable)
        for side in ("left","right"):
            field=self.fields.get("construction.excavation_slope_"+side)
            if field is not None:field.setEnabled(not active)
            button=self.stage_buttons.get("excavation_stages_"+side)
            if button is not None:button.setEnabled(not active or stages)
        self.layer_hint.setToolTip("当前敷设方式不进行地表明挖，不能启用简化分层。" if not applicable else "")

    def validate_layered_excavation(self):
        construction=self.asset.get("construction",{})
        if construction.get("excavation_layer_mode")!="surface_thickness":return
        if not layered_excavation_applicable(self.asset):raise ValueError("简化分层仅适用于普通线性明挖；当前结构或敷设方式不适用")
        if any(self.stages.get("excavation_stages_"+side,construction.get("excavation_stages_"+side)) for side in ("left","right")):
            raise ValueError("请先清空左右开挖分级/马道，再启用简化分层；原分级数据已保留")
        for key in LAYERED_EXCAVATION_FIELDS[1:]:
            value=construction.get(key)
            if value is None:raise ValueError("简化分层须填写覆盖层竖直厚度及覆盖层、基岩左右开挖坡比")
            if not math.isfinite(float(value)) or float(value)<0:raise ValueError("简化分层厚度和两层坡比须为有限非负数")

    def add_discrete_components(self):
        form=self.form_page("渡槽附属构件")
        label=QLabel("逐项填写拉杆、支承、墩台及基础的实际布置。每行按起止桩号、横宽和绝对高程构成矩形实体；重复构件逐行录入。勾选“基础挖槽”才计算该构件的开挖及周边回填。空表表示尚未提供附属实体，结果会列明缺项。")
        label.setWordWrap(True);form.addRow(label)
        self._discrete_original=copy.deepcopy(self.asset.get("section",{}).get("discrete_components",[]))
        self.discrete_table=QTableWidget(0,12)
        self.discrete_table.setHorizontalHeaderLabels(["构件名称","材质","等级","起桩 m","止桩 m","横偏距 m","横宽 m","底高程 m","顶高程 m","基础挖槽","构件ID","范围类别"])
        self.discrete_table.setMinimumHeight(230)
        self.discrete_table.horizontalHeader().moveSection(11,1);self.discrete_table.setColumnHidden(10,True)
        for column,width in {0:130,1:100,2:80,3:90,4:90,5:90,6:90,7:90,8:90,9:90,11:150}.items():self.discrete_table.setColumnWidth(column,width)
        self.discrete_table.setToolTip("桩号与高程采用当前路线的真实坐标，不采用内部拼接桩号。每行实体纵向长度=止桩-起桩，高度=顶高程-底高程。")
        for component in self._discrete_original:self.add_discrete_row(component)
        form.addRow(self.discrete_table)
        row=QHBoxLayout();add=QPushButton("增加构件");add.clicked.connect(lambda:self.add_discrete_row());row.addWidget(add)
        remove=QPushButton("删除选中构件");remove.clicked.connect(lambda:self.discrete_table.removeRow(self.discrete_table.currentRow()) if self.discrete_table.currentRow()>=0 else None);row.addWidget(remove);form.addRow(row)
        identifiers=QCheckBox("显示构件追踪编号");identifiers.toggled.connect(lambda visible:self.discrete_table.setColumnHidden(10,not visible));form.addRow(identifiers)

    def add_discrete_row(self,component=None):
        component=copy.deepcopy(component or {});row=self.discrete_table.rowCount();self.discrete_table.insertRow(row)
        component.setdefault("component_id","component_"+uuid.uuid4().hex[:12])
        for column,key in enumerate(("name","material","grade","station_start","station_end","offset","width","bottom_elevation","top_elevation")):
            value=component.get(key)
            item=QTableWidgetItem("" if value is None else str(value))
            if column==0:item.setData(Qt.UserRole,component)
            self.discrete_table.setItem(row,column,item)
        check=QCheckBox();check.setChecked(bool(component.get("excavate",False)));self.discrete_table.setCellWidget(row,9,check)
        self.discrete_table.setItem(row,10,QTableWidgetItem(str(component["component_id"])))
        self.discrete_table.setCellWidget(row,11,_scope_box(AQUEDUCT_SCOPE_LABELS,component.get("scope_category")))

    def add_quantity_scope(self):
        form=self.form_page("计量范围确认")
        label=QLabel("按本工程实际构造逐类核对。已输入且归类的实体或分项纳入对应类别；只有本工程确定不需要的类别才勾选“不适用”。未提供、未确认或未归类的项目保留为缺项，不当作零工程量。")
        label.setWordWrap(True);form.addRow(label)
        options=AQUEDUCT_SCOPE_LABELS if self.aqueduct else TUNNEL_SCOPE_LABELS
        existing=self.asset.get("section",{}).get("quantity_scope_not_applicable",[])
        self.not_applicable_scope={};known={key for key,_name in options}
        self._unknown_not_applicable=[key for key in existing if key not in known]
        for key,name in options:
            check=QCheckBox(name+"：本工程不适用（用户确认）");check.setChecked(key in existing)
            self.not_applicable_scope[key]=check;form.addRow(check)

    def add_quantity_rules(self):
        form=self.form_page("其他分项计量")
        label=QLabel("用于接缝、止水、支座数量、排水、灌浆等补充分项。规则与附属实体分别列项，同一构件勿重复录入。点击增加或编辑即可填写；未填写不表示这些工程量为零。")
        label.setWordWrap(True);form.addRow(label)
        self.quantity_rules_table=QTableWidget(0,6);self.quantity_rules_table.setHorizontalHeaderLabels(["分项名称","材质","单位","件数","计量方式","稳定编号"])
        self.quantity_rules_table.setMinimumHeight(200);self.quantity_rules_table.cellDoubleClicked.connect(lambda row,_column:self.edit_quantity_rule(row));form.addRow(self.quantity_rules_table)
        row=QHBoxLayout()
        add=QPushButton("增加分项");add.clicked.connect(lambda:self.edit_quantity_rule());row.addWidget(add)
        edit=QPushButton("编辑选中分项");edit.clicked.connect(lambda:self.edit_quantity_rule(self.quantity_rules_table.currentRow()));row.addWidget(edit)
        remove=QPushButton("删除选中分项");remove.clicked.connect(self.remove_quantity_rule);row.addWidget(remove);form.addRow(row)
        self.quantity_rules_editor=QPlainTextEdit()
        self.quantity_rules_editor.setPlainText(json.dumps(self.asset.get("section",{}).get("quantity_rules",[]),ensure_ascii=False,indent=2))
        self.quantity_rules_editor.setPlaceholderText('[{"id":"joint_01","name":"止水带","unit":"m","quantity_per_unit":8,"count":4}]')
        self.quantity_rules_editor.setMinimumHeight(200);self.quantity_rules_editor.setVisible(False)
        advanced=QCheckBox("显示高级规则文本（JSON）");advanced.toggled.connect(self.quantity_rules_editor.setVisible);form.addRow(advanced);form.addRow(self.quantity_rules_editor)
        self.quantity_rules_editor.textChanged.connect(self.refresh_quantity_rule_table);self.refresh_quantity_rule_table()

    def quantity_rules(self):
        rules=json.loads(self.quantity_rules_editor.toPlainText().strip() or "[]")
        if not isinstance(rules,list) or any(not isinstance(rule,dict) for rule in rules):raise ValueError("分项规则须为对象列表")
        return rules

    def refresh_quantity_rule_table(self):
        try:rules=self.quantity_rules()
        except (ValueError,TypeError):return
        self.quantity_rules_table.setRowCount(len(rules))
        for row,rule in enumerate(rules):
            mode="总量 "+str(rule["quantity"]) if "quantity" in rule else "每件 "+str(rule["quantity_per_unit"]) if "quantity_per_unit" in rule else "构件尺寸"
            values=(rule.get("name",""),rule.get("material",""),rule.get("unit",""),rule.get("count",1),mode,rule.get("id",""))
            for column,value in enumerate(values):
                item=QTableWidgetItem(str(value));item.setFlags(item.flags()&~Qt.ItemIsEditable);self.quantity_rules_table.setItem(row,column,item)

    def edit_quantity_rule(self,row=None):
        try:rules=self.quantity_rules()
        except (ValueError,TypeError) as exc:QMessageBox.warning(self,"分项规则需要核对",str(exc));return
        existing=isinstance(row,int) and 0<=row<len(rules)
        dialog=QuantityRuleDialog(rules[row] if existing else None,self,kind="aqueduct" if self.aqueduct else "tunnel")
        if dialog.exec()==QDialog.Accepted:
            if existing:rules[row]=dialog.rule
            else:rules.append(dialog.rule)
            self.quantity_rules_editor.setPlainText(json.dumps(rules,ensure_ascii=False,indent=2))

    def remove_quantity_rule(self):
        row=self.quantity_rules_table.currentRow()
        try:rules=self.quantity_rules()
        except (ValueError,TypeError) as exc:QMessageBox.warning(self,"分项规则需要核对",str(exc));return
        if 0<=row<len(rules):
            del rules[row];self.quantity_rules_editor.setPlainText(json.dumps(rules,ensure_ascii=False,indent=2))

    def save_additional_components(self):
        if hasattr(self,"discrete_table"):
            components=[];identifiers=set()
            for row in range(self.discrete_table.rowCount()):
                component=copy.deepcopy(self.discrete_table.item(row,0).data(Qt.UserRole) or {})
                for column,key in enumerate(("name","material","grade","station_start","station_end","offset","width","bottom_elevation","top_elevation")):
                    text=self.discrete_table.item(row,column).text().strip()
                    if column<3:
                        if text:component[key]=text
                        else:component.pop(key,None)
                    else:
                        if not text:raise ValueError(f"第{row+1}行附属构件的桩号、横偏距、横宽和高程须完整填写")
                        value=float(text)
                        if not math.isfinite(value):raise ValueError("附属构件参数须为有限数字")
                        component[key]=value
                identifier=self.discrete_table.item(row,10).text().strip()
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}",identifier) or identifier in identifiers:raise ValueError("附属构件ID须为字母开头的英文、数字或下划线，最长80字符且不得重复")
                identifiers.add(identifier);component["component_id"]=identifier
                if not component.get("name") or not component.get("material"):raise ValueError("每项附属构件须填写名称和材质")
                if component["station_end"]<=component["station_start"] or component["width"]<=0 or component["top_elevation"]<=component["bottom_elevation"]:
                    raise ValueError("附属构件须满足起桩小于止桩、横宽大于0、顶高程高于底高程")
                component["excavate"]=self.discrete_table.cellWidget(row,9).isChecked()
                category=self.discrete_table.cellWidget(row,11).currentData()
                if category:component["scope_category"]=category
                else:component.pop("scope_category",None)
                components.append(component)
            self.asset.setdefault("section",{})["discrete_components"]=components
        if hasattr(self,"quantity_rules_editor"):
            try:rules=json.loads(self.quantity_rules_editor.toPlainText().strip() or "[]")
            except json.JSONDecodeError as exc:raise ValueError("其他分项规则JSON格式错误："+str(exc)) from exc
            if not isinstance(rules,list) or any(not isinstance(rule,dict) for rule in rules):raise ValueError("其他分项规则须为JSON对象列表")
            identifiers={component["component_id"] for component in self.asset.get("section",{}).get("discrete_components",[])}
            for rule in rules:
                identifier=rule.get("id")
                if not isinstance(identifier,str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}",identifier) or identifier in identifiers:raise ValueError("分项规则id须为字母开头的英文、数字或下划线，最长80字符且不得与其他规则或实体构件重复")
                identifiers.add(identifier)
                if rule.get("unit") not in {"m3","m2","m","kg","count"}:raise ValueError("分项规则unit须为m3、m2、m、kg或count")
                for key,value in rule.items():
                    if isinstance(value,(float,int)) and not isinstance(value,bool) and not math.isfinite(value):raise ValueError("分项规则须使用有限数字")
            self.asset.setdefault("section",{})["quantity_rules"]=rules
            if rules:
                from 土石方计算.services.aqueduct_components import quantity_rule_items
                quantity_rule_items(self.asset)
        if hasattr(self,"not_applicable_scope"):
            selected=[key for key,check in self.not_applicable_scope.items() if check.isChecked()]
            self.asset.setdefault("section",{})["quantity_scope_not_applicable"]=selected+self._unknown_not_applicable

    def _tunnel_lining_option_changed(self):
        selected=self.tunnel_lining_choice.currentData()
        options=self.asset.get("source_tunnel_lining_options") or {}
        if selected in options:
            self.fields["section.base_thickness"].setText(str(options[selected]["t0"]))
            self.fields["section.lining_thickness"].setText(str(options[selected]["t"]))

    def text(self,form,path,label,*,placeholder="填写材料等级"):
        value=_get(self.asset,path)
        if value is None:
            key={"section.material_grade":"concrete","construction.bedding_grade":"bedding","section.shotcrete_grade":"shotcrete"}.get(path)
            if key:value=self.asset.get("section",{}).get("material_specs",{}).get(key,{}).get("grade")
        field=QLineEdit("" if value is None else str(value));field.setPlaceholderText(placeholder);self.text_fields[path]=field;form.addRow(label,field)

    def add_drawing_material_details(self):
        specs=self.asset.get("section",{}).get("material_specs",{})
        components=self.asset.get("section",{}).get("component_specs",[])
        sources=self.asset.get("drawing_parameter_sources",{})
        if not any((specs,components,sources)):return
        from .drawing_material_details import populate_drawing_details

        form = self.form_page("图纸与材料依据")
        self._component_original = copy.deepcopy(components)
        populate_drawing_details(self, form, specs, components, sources)

    def choice(self,form,path,label,values,default=None):
        field=QComboBox()
        for name,value in values:field.addItem(name,value)
        value=_get(self.asset,path) or default
        if path=="construction.installation_mode":
            value={"above_ground":"exposed","open":"exposed"}.get(value,value)
            if field.findData(value)<0:field.addItem("待确认敷设方式",None);value=None
        field.setCurrentIndex(max(0,field.findData(value)));self.combos[path]=field;form.addRow(label,field)

    def stage_button(self,form,key,label):
        self.stages[key]=copy.deepcopy(self.asset.get("construction",{}).get(key,[]))
        button=QPushButton(label+f"（{len(self.stages[key])}级）")
        def edit():
            dialog=StageDialog(self.stages[key],self)
            if dialog.exec()==QDialog.Accepted:self.stages[key]=dialog.values;button.setText(label+f"（{len(dialog.values)}级）")
        button.clicked.connect(edit);self.stage_buttons[key]=button;form.addRow(button)

    def edited_asset(self):
        """Read the current form for a geometry preview or an explicit save."""
        previous_asset = self.asset
        self.asset = copy.deepcopy(previous_asset)
        try:
            side_values={}
            if hasattr(self,"encasement_sides"):
                side_values={f"construction.{self.enclosure_key}.{k}":v for k,v in self.encasement_sides.values().items()}
            for path,field in self.fields.items():
                if path in side_values:value=side_values[path]
                elif isinstance(field,QCheckBox):value=field.isChecked()
                else:
                    text=field.text().strip()
                    if path=="section.pipe_spacing":
                        old_gap=self.asset.get("section",{}).get("pipe_spacing")
                        if not text:value=[] if isinstance(old_gap,list) and self.pipe_table.rowCount()==1 else None
                        else:
                            entries=text.replace("，",",").split(",")
                            if any(not item.strip() for item in entries):raise ValueError("相邻管净距不能含空项，请填一个单值或N-1个逗号分隔的值")
                            gaps=[float(item) for item in entries]
                            if not all(math.isfinite(gap) and gap>=0 for gap in gaps):raise ValueError("相邻管净距须为有限非负数")
                            value=gaps if len(gaps)>1 or isinstance(old_gap,list) and self.pipe_table.rowCount()==2 else gaps[0]
                    else:
                        label=field.accessibleName() or "该参数"
                        try:
                            value=float(text) if text else U_ANGLE_DEFAULTS.get(path)
                        except ValueError:
                            raise ValueError(label+"须填写数值") from None
                        if value is not None:
                            validate_u_angle(path, value)
                            if not math.isfinite(value):raise ValueError(label+"须为有限数字")
                        if path in self.nonnegative_fields and value is not None and value<0:raise ValueError(self.nonnegative_fields[path]+"须为非负数")
                        if path=="section.inner_chamfers":
                            if value is None or value<0:raise ValueError("内倒角须为有限非负数")
                            original=self.original_asset.get("section",{}).get("inner_chamfers")
                            if isinstance(original,dict) and text==getattr(self,"_chamfer_display",None):value=copy.deepcopy(original)
                if path.startswith("_center_"):
                    if value is None:raise ValueError("基坑中心坐标需要补齐")
                    xy=self.asset.setdefault("placement",{}).setdefault("center_xy",[0.,0.]);xy[int(path[-1])]=value
                else:_set(self.asset,path,value)
            for path,field in self.text_fields.items():
                value=field.text().strip() or None
                _set(self.asset,path,value)
                key={"section.material_grade":"concrete","construction.bedding_grade":"bedding","section.shotcrete_grade":"shotcrete"}.get(path)
                if key and key in self.asset.get("section",{}).get("material_specs",{}):
                    _set(self.asset,"section.material_specs."+key+".grade",value)
            if hasattr(self,"component_table"):
                components=copy.deepcopy(self._component_original)
                for row,component in enumerate(components):
                    text=self.component_table.item(row,3).text().strip()
                    is_region=component.get("geometry_kind")=="outer_offset_layer"
                    key="thickness_m" if is_region or "thickness_m" in component and "nominal_thickness_m" not in component else "nominal_thickness_m"
                    if text:
                        value=float(text)
                        if not math.isfinite(value) or value<=0:raise ValueError(str(component.get("name","独立材料"))+"厚度须为有限正数")
                        component[key]=value
                    elif is_region:raise ValueError(str(component.get("name","独立材料"))+"的实体厚度不能留空")
                    else:component.pop(key,None)
                    grade=self.component_table.item(row,4).text().strip()
                    if grade:component["grade"]=grade
                    elif component.get("grade"):component.pop("grade",None)
                self.asset.setdefault("section",{})["component_specs"]=components
            for path,field in self.combos.items():_set(self.asset,path,field.currentData())
            if self.tunnel:
                section=self.asset.setdefault("section",{})
                selected=self.tunnel_lining_choice.currentData()
                options=self.asset.get("source_tunnel_lining_options") or {}
                if self.asset.get("source_tunnel_lining_selection_required") and (
                        section.get("base_thickness") is None or section.get("lining_thickness") is None):
                    raise ValueError("请先选择本段围岩衬砌方案，或明确填写实际底板及墙拱厚度")
                if selected in options:
                    section["rock_class"]=selected
                    exact=(section.get("base_thickness")==options[selected]["t0"]
                        and section.get("lining_thickness")==options[selected]["t"])
                    self.asset["tunnel_lining_selection_mode"]="source_library" if exact else "manual"
                elif section.get("lining_thickness") is not None:
                    section.pop("rock_class",None)
                    self.asset["tunnel_lining_selection_mode"]="manual"
                self.asset["source_tunnel_lining_selection_required"]=False
                for key in ("missing_fields","source_missing_fields"):
                    if key in self.asset:self.asset[key]=[p for p in self.asset[key] if p!="section.rock_class"]
            if self.pit and self.asset.get("placement",{}).get("angle_degrees") is not None:
                angle=math.radians(self.asset["placement"]["angle_degrees"])
                self.asset["placement"]["direction"]=[math.cos(angle),math.sin(angle)]
            for key,values in self.stages.items():
                if values:self.asset.setdefault("construction",{})[key]=values
                else:self.asset.setdefault("construction",{}).pop(key,None)
            self.validate_layered_excavation()
            if self.pipe:
                pipes=[];original=self._pipe_original
                for row in range(self.pipe_table.rowCount()):
                    pipe=copy.deepcopy(original[row]) if row<len(original) else {}
                    if self.asset.get("cover_pipe_layout_mode") == "spacing":
                        # An earlier cover preview recorded these derived offsets.
                        # Let the edited diameters, pipe count and gaps place the pipes again.
                        pipe.pop("offset", None)
                    for key in ("inner_diameter","outer_diameter","wall_thickness"):pipe.pop(key,None)
                    for c,key in enumerate(("inner_diameter","outer_diameter","wall_thickness")):
                        item=self.pipe_table.item(row,c);text=item.text().strip() if item else ""
                        if text:pipe[key]=float(text)
                    outer_item=self.pipe_table.item(row,1)
                    auto_outer=outer_item.data(Qt.UserRole) if outer_item is not None else None
                    if auto_outer is not None:
                        pipe["dn_envelope_diameter_m"]=float(auto_outer)
                        pipe["diameter_basis"]="nominal_dn_construction_envelope"
                    for key,label in (("inner_diameter","水力D/净内径"),("outer_diameter","施工外径"),("wall_thickness","实际壁厚")):
                        if key in pipe and (not math.isfinite(pipe[key]) or pipe[key]<=0):raise ValueError(label+"须为有限正数")
                    item=self.pipe_table.item(row,6);text=item.text().strip() if item else ""
                    if text:
                        nominal=float(text)/1000.
                        if not math.isfinite(nominal) or nominal<=0:raise ValueError("公称DN须为有限正数，单位mm")
                        pipe["nominal_diameter_m"]=nominal
                        if pipe.get("hydraulic_inner_diameter_m") is None and pipe.get("inner_diameter") is not None:
                            pipe["hydraulic_inner_diameter_m"]=pipe["inner_diameter"]
                        if "outer_diameter" not in pipe:pipe.update(outer_diameter=nominal,dn_envelope_diameter_m=nominal,diameter_basis="nominal_dn_construction_envelope")
                    else:pipe.pop("nominal_diameter_m",None)
                    item=self.pipe_table.item(row,4);text=item.text().strip() if item else ""
                    lining=float(text) if text else 0.
                    if not math.isfinite(lining) or lining<0:raise ValueError("内衬厚度须为有限非负数")
                    lining_material=self.pipe_table.cellWidget(row,5).currentData()
                    if lining>0 and lining_material is None:raise ValueError(f"请核对第{row+1}根管的内衬材质")
                    if lining or "lining_thickness" in pipe or self.asset.get("section",{}).get("lining_thickness") is not None:pipe["lining_thickness"]=lining
                    if lining_material is not None or "lining_material" in pipe:pipe["lining_material"]=lining_material
                    if "outer_diameter" not in pipe:
                        if not all(k in pipe for k in ("inner_diameter","wall_thickness")):raise ValueError("每根管需施工外径，或明确的内径与壁厚")
                        pipe["outer_diameter"]=pipe["inner_diameter"]+2*(pipe["wall_thickness"]+lining)
                    material=self.pipe_table.cellWidget(row,3).currentData()
                    if "wall_thickness" in pipe:
                        if material is None:raise ValueError(f"请核对第{row+1}根管的管材")
                        if pipe.get("earthwork_envelope_only") and pipe.get("nominal_diameter_m") is None:
                            pipe.pop("inner_diameter_is_placeholder",None)
                        pipe.pop("earthwork_envelope_only",None)
                    else:
                        if lining>0:raise ValueError(f"第{row+1}根管须先提供实际管壁厚度，才能计算内衬材料")
                        pipe["earthwork_envelope_only"]=True
                        for key in ("lining_thickness","lining_material","construction_inner_diameter_m","inner_diameter_is_placeholder"):pipe.pop(key,None)
                    if material is not None:pipe["material"]=material
                    else:pipe.pop("material",None)
                    pipes.append(pipe)
                self.asset.setdefault("section",{})["pipes"]=pipes;self.asset["section"]["pipe_count"]=len(pipes)
                spacing=self.asset["section"].get("pipe_spacing")
                if isinstance(spacing,list) and len(spacing)!=len(pipes)-1:
                    raise ValueError(f"{len(pipes)}根管须填写一个统一净距或{len(pipes)-1}个相邻净距；当前填写了{len(spacing)}个")
                if len(pipes)>1 and spacing is None:
                    missing=self.asset.setdefault("missing_fields",[])
                    if "section.pipe_spacing" not in missing:missing.append("section.pipe_spacing")
                if pipes:
                    for key in ("inner_diameter","outer_diameter","wall_thickness","lining_thickness","lining_material","nominal_diameter_m",
                                "hydraulic_inner_diameter_m","dn_envelope_diameter_m","diameter_basis","construction_inner_diameter_m"):
                        if key in pipes[0]:self.asset["section"][key]=copy.deepcopy(pipes[0][key])
                        else:self.asset["section"].pop(key,None)
                    if all(p.get("earthwork_envelope_only") for p in pipes):self.asset["section"]["earthwork_envelope_only"]=True
                    else:self.asset["section"].pop("earthwork_envelope_only",None)
                normalize_pipe_dimensions(self.asset)
                layout = pipe_specs(self.asset["section"], require_material=False)
                if self.asset.get("cover_pipe_layout_mode") == "spacing" and (len(layout) == 1 or spacing is not None):
                    for pipe, placed in zip(self.asset["section"]["pipes"], layout):
                        pipe["offset"] = placed["offset"]
            if hasattr(self,"pipe_seat_width_hint"):
                seat=self.asset.setdefault("construction",{}).setdefault(self.seat_key,{})
                if self.pipe_seat_width_mode!="explicit":
                    seat.pop("bottom_width",None)
                if self.pipe_seat_width_mode in {"support_chord","trench_bottom"}:
                    seat.pop("extension",None)
                    seat.pop("height",None)
                if seat.get("enabled",True):
                    angle=seat.get("support_angle",seat.get("angle",120))
                    if not 0<float(angle)<=360:raise ValueError("支承角应大于 0° 并且不超过 360°")
                    if self.pipe_seat_chord_mode and float(angle)>=180:
                        raise ValueError("按弦宽确定底宽时，支承角应小于 180°")
                    if seat.get("bottom_width") is not None and seat["bottom_width"]<=0:
                        raise ValueError("指定底宽须大于零")
                if self.pipe_seat_trench_mode:
                    self.asset["construction"]["working_space_reference"]="pipe_outer"
                    if self.pipe_seat_bedding_trench_mode:
                        seat["side_boundary_mode"]=self.combos[f"construction.{self.seat_key}.side_boundary_mode"].currentData()
            self.save_additional_components()
            normalize_asset_construction(self.asset)
            self.asset["workbench_geometry"]=True;self.asset["parameter_source"]="user_confirmed"
            edit_range=self.edit_scope and not self.pit
            self.scope_value=self.scope.currentData() if edit_range else "asset"
            self.override_range=(float(self.start.text()),float(self.end.text())) if edit_range else None
            if self.override_range and not all(math.isfinite(x) for x in self.override_range):raise ValueError("起止桩号须为有限数字")
            if self.override_range and self.override_range[0]>=self.override_range[1]:raise ValueError("起桩须小于止桩")
            self.changed_fields=_parameter_changes(self.original_asset,self.asset)
            self.changed_paths=tuple(self.changed_fields)
            return self.asset
        finally:
            self.asset = previous_asset

    def accept(self):
        try:
            self.asset = self.edited_asset()
        except (ValueError,TypeError) as exc:
            QMessageBox.warning(self,"参数需要核对",str(exc))
            return
        super().accept()
