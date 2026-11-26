"""One main-program page for terrain, construction sections and quantities."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from filesystem_paths import filesystem_path, resolved_path
import tempfile
from time import perf_counter
import uuid

import numpy as np
from PySide6.QtCore import Qt,Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,
    QComboBox,QFileDialog,QTableWidget,QTableWidgetItem,QHeaderView,
    QDoubleSpinBox,QSlider,QMessageBox,QMenu,QDialog,QDialogButtonBox,
    QFormLayout,QCheckBox,QInputDialog,QGroupBox)
from qfluentwidgets import InfoBar, InfoBarPosition

from app_渠系计算前端.task_runner import TaskRunner
from 土石方计算.services.workbench_diagnostics import TerrainSourceChanged, TerrainUnavailable
from .project_state import source_channel_name
from .section_preparation import construction_field_label, route_identity
from .terrain_plan import TerrainPlanMixin
from .workbench_parameters import AssetParameterDialog,LAYERED_EXCAVATION_FIELDS,layered_excavation_applicable
from .workbench_results import WorkbenchResultsMixin
from .workbench_workflow import WorkbenchWorkflowMixin


class CurrentDesignChanged(ValueError):
    """A calculation needs the current hydraulic design before it can proceed."""


def serialize_inputs(inputs):
    from 土石方计算.services.construction_rules import normalize_construction_inputs
    from 土石方计算.services.network_alignment import NetworkAlignment

    # The analytic alignment already copies its geometry when serialized.
    # Keep it out of the first copy so each route geometry is copied once.
    alignments = {}
    networks = inputs.get("networks", [])
    if isinstance(networks, (list, tuple)):
        alignments = {i: owner["alignment"] for i, owner in enumerate(networks)
                      if type(owner.get("alignment")) is NetworkAlignment}
    if alignments:
        owners = [{**owner, "alignment": None} if i in alignments else owner
                  for i, owner in enumerate(networks)]
        networks = tuple(owners) if isinstance(networks, tuple) else owners
        data = copy.deepcopy({**inputs, "networks": networks})
    else:
        data = copy.deepcopy(inputs)
    normalize_construction_inputs(data)
    for index, network in enumerate(data.get("networks", [])):
        value = alignments.get(index, network.get("alignment"))
        if hasattr(value, "to_dict"):
            network["alignment"] = value.to_dict()
    return data


def restore_inputs(data):
    from 土石方计算.services.network_alignment import NetworkAlignment
    from 土石方计算.services.construction_rules import normalize_construction_inputs
    result=copy.deepcopy(data)
    normalize_construction_inputs(result)
    for network in result.get("networks",[]):
        value=network.get("alignment")
        if isinstance(value,dict) and value.get("elements"):network["alignment"]=NetworkAlignment.from_dict(value)
    return result


def _range_result_note(payload, field, label):
    report=(payload or {}).get(field) or {}
    if isinstance(report,dict) and report.get("range_count"):
        return f"{label}{report['range_count']}段，共{report['total_length_m']:.3f}m"
    return ""


def result_scope_prefix(payload):
    """Keep the recorded calculation scope visible through UI state changes."""
    from 土石方计算.services.workbench_scope import deferred_scope_note
    notes=[deferred_scope_note(payload or {}),
           _range_result_note(payload,"automatic_unsupported_pipe_ranges","悬空区段"),
           _range_result_note(payload,"terrain_unmeasured_ranges","地形缺测")]
    prefix="".join(note.rstrip("；")+"；" for note in notes if note)
    if notes[0]:return prefix
    if not payload or payload.get("partial_acceptance") is not True or not payload.get("defined_scope"):
        return prefix
    scope=payload["defined_scope"]
    if not isinstance(scope,dict):return prefix+"局部TEST；范围待核对；"
    identifier=scope.get("deferred_asset_id")
    names={str(item.get("name") or (item.get("original_asset_snapshot") or {}).get("name") or "")
           for item in payload.get("excluded_assets",[]) if item.get("asset_id")==identifier}
    names.discard("")
    name=next(iter(names)) if len(names)==1 else str(identifier or "未计对象")
    try:
        start,end=float(scope["station_start"]),float(scope["station_end"])
        if not math.isfinite(start) or not math.isfinite(end) or start<0 or end<=start:raise ValueError
    except (KeyError,TypeError,ValueError):return prefix+"局部TEST；范围待核对；"
    def station(value):
        kilometres,millimetres=divmod(round(value*1000),1_000_000)
        return f"K{kilometres}+{millimetres/1000:07.3f}"
    return prefix+f"局部TEST；{name}{station(start)}-{station(end)}未计；"


def _is_saved_quantity_result(payload):
    validation=payload.get("validation") or {}
    return ((payload.get("method") == "exact_tin_actual_midpoint_section_integration" and bool(payload.get("sections")))
            or any(validation.get(key) for key in ("automatic_unsupported_only", "automatic_terrain_unmeasured_only",
                                                    "automatic_tunnel_exposed_only"))
            or bool(validation.get("sluice_gate_only") and payload.get("quantity_items"))
            or bool(validation.get("trenchless_only") and payload.get("trenchless_excavation_rows")))


def source_hash(snapshot):
    from 土石方计算.services.workbench_identity import source_project_hash
    return source_project_hash(snapshot)


def _water_project_inputs(snapshot):
    from 土石方计算.adapters.workbench_sources import import_workbench_project

    panel = snapshot.get("merged_panel") or snapshot.get("water_profile_panel") or {}
    if not panel.get("calculated_nodes"):
        raise ValueError("请先完成水面线计算，或打开已有水面线成果的项目文件。")
    if panel.get("water_result_current") is False:
        raise ValueError("水面线计算输入已修改，请重新推求水面线后再读取成果")
    if (panel.get("merged_section") or {}).get("sync_ready") is False:
        raise ValueError("水面线源表已修改，请先完成断面和水面线计算，再带入最新成果")
    inputs = import_workbench_project(snapshot)
    for issue in inputs.get("diagnostics", []):
        if issue.get("code") == "no_design_sources":
            raise ValueError(issue["message"])
    settings = panel.get("project_settings") or {}
    name = settings.get("channel_name") or settings.get("project_name")
    if name:
        inputs["project_name"] = str(name) + str(settings.get("channel_level") or "")
    return panel, inputs


def _prepare_saved_water_project(snapshot):
    from 土石方计算.adapters.workbench_sources import estimate_workbench_project_connections, merge_workbench_profile_routes
    from 土石方计算.services.construction_defaults import apply_assumed_construction
    from 土石方计算.services.earthwork_scope import trenchless_exclusions

    panel, inputs = _water_project_inputs(snapshot)
    inputs = estimate_workbench_project_connections(inputs, snapshot)
    apply_assumed_construction(inputs)
    networks = [dict(network, alignment=network["alignment"].to_dict())
                for network in inputs.get("networks", []) if network.get("alignment") is not None]
    if not networks and not trenchless_exclusions(inputs):
        raise ValueError("工程中没有可用的中心轴线。请在水面线核对平面坐标，重新计算后保存工程。")
    viewer_routes = merge_workbench_profile_routes(networks, snapshot)
    centerline = next((route["alignment"] for route in viewer_routes if route.get("profile_segment_ids")), {})
    return inputs, source_channel_name(panel), centerline


def display_text(text):
    names={"design_profile":"纵断面高程/轴线","station_range":"施工起止桩号",
           "section.inner_width":"净空宽度","section.inner_height":"净空高度","section.inner_radius":"净内半径",
           "section.inner_diameter":"水力内径","section.outer_diameter":"施工外径","section.material":"管材",
           "section.base_thickness":"底板/底弧厚度","section.wall_thickness_left":"左墙/衬砌厚度",
           "section.lining_thickness":"墙拱衬砌厚度","section.shotcrete_thickness":"喷护厚度",
           "section.rock_class":"围岩衬砌方案","construction.excavation_clearance":"超挖预留厚度",
           "section.material_specs.bedding":"砂垫层材料参数","section.material_specs":"材料参数",
           "section.wall_thickness_right":"右墙/衬砌厚度","section.roof_thickness":"顶板/拱圈厚度",
           "section.bottom_length":"坑底总长","section.bottom_width":"坑底总宽","section.floor_elevation":"坑底高程",
           "section.foundation_length":"基础长度","section.foundation_width":"基础宽度","section.foundation_height":"基础高度",
           "section.pipe_spacing":"管间净距","construction.bedding_thickness":"垫层厚度","construction.bedding_extension":"垫层外伸",
           "construction.target_mode":"施工完成面方式","construction.installation_mode":"管道敷设方式",
           "construction.excavation_base_mode":"开挖底面方式","construction.cover_depth":"管顶埋深",
           "construction.excavation_layer_mode":"简化分层开挖方式","construction.overburden_thickness":"覆盖层竖直厚度"}
    for side,label in (("left","左侧"),("right","右侧"),("front","前侧"),("back","后侧")):
        for prefix,name in (("working_space_","施工工作面"),("excavation_slope_","开挖坡比"),("excavation_stages_","开挖分级与马道"),("overburden_slope_","覆盖层开挖坡比"),("bedrock_slope_","基岩开挖坡比"),("bank_top_width_","平台宽度"),("bank_slope_","填筑坡比"),("bank_stages_","填筑分级与马道")):
            names["construction."+prefix+side]=label+name
    value=str(text)
    for key in sorted(names,key=len,reverse=True):value=value.replace(key,names[key])
    return re.sub(r"(参数[：:\s]+)([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)?)",
                  lambda match: match[1] + construction_field_label(match[2]), value)


def copied_construction(candidate,item,scope):
    """Copy the explicit layer choice only to supported open-cut recipients."""
    from 土石方计算.services.batch_cover_profiles import is_pressure_cover_asset
    from 土石方计算.services.design_profiles import PIPE_AXIS_CONTROLS

    construction=copy.deepcopy(candidate.get("construction",{}))
    if is_pressure_cover_asset(item):
        for key in PIPE_AXIS_CONTROLS:
            construction.pop(key, None)
    if scope=="all":
        construction={k:v for k,v in construction.items() if k.startswith(("working_space_","excavation_slope_","excavation_stages_","bedding_","bank_")) or k in {"excavation_base_mode","excavation_clearance",*LAYERED_EXCAVATION_FIELDS}}
    prospective=copy.deepcopy(item)
    prospective.setdefault("construction",{}).update(construction)
    if not layered_excavation_applicable(prospective):
        for key in LAYERED_EXCAVATION_FIELDS:construction.pop(key,None)
    return construction


def default_delivery_root():
    if getattr(sys,"frozen",False):
        from PySide6.QtCore import QStandardPaths
        folder=QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        return Path(folder or str(Path.home()/"Documents"))/"土石方算量成果"
    return Path(__file__).resolve().parents[2]/"outputs"/"土石方一键成果"


DEFAULT_DRAWING_OPTIONS={"interval":20.,"all_sections":True,"paper":"A3","scale":1000,
                         "include_plan":False,"include_profile":False,"sections_only":True,"concise":True,
                         "section_layout":"overview"}


class SectionWorkbenchPanel(WorkbenchWorkflowMixin,WorkbenchResultsMixin,TerrainPlanMixin,QWidget):
    data_changed=Signal()
    progress_event=Signal(str,float,str)
    _task_progress_event=Signal(int,str,float,str)

    def __init__(self,parent=None,*,project_provider=None,session_provider=None,
                 project_file_opener=None):
        super().__init__(parent);self.setObjectName("sectionEarthworkWorkbench")
        self._project_provider=project_provider;self._session_provider=session_provider
        self._project_file_opener = project_file_opener
        self._opening_project_file = False
        self._terrain_processing_mode="combined"
        self.runner=TaskRunner(self);self.runner.running_changed.connect(self._busy);self.progress_event.connect(self._progress)
        self._task_progress_event.connect(self._task_progress)
        self.map_terrain_runner=TaskRunner(self)
        self.project_id=str(uuid.uuid4());self._inputs={"networks":[],"pits":[],"excluded":[],"diagnostics":[]}
        self._result=self._calculation=self._tin=None;self._valid=False;self._restoring=False
        self._input_revision = 0
        self._source_hash=None;self._terrain_identity={};self._section_groups={};self._records=[];self._legacy_payload=None
        self._measured_assets = {}
        self._terrain_import_failed = False
        self._pending_terrain_path = ""
        self._pending_terrain_note = ""
        self._source_channel_name = ""
        self._read_saved_water = False
        self._saved_water_centerline = None
        self._centerline_batch_network = None
        self._map_restore_attempt=None;self._shutting_down=False;self._query_view=None;self.last_delivery_path=""
        self._connection_draft_state=None
        self._drawing_options=DEFAULT_DRAWING_OPTIONS.copy()
        self._build_ui()

    def _build_ui(self):
        layout=QVBoxLayout(self);layout.setContentsMargins(16,12,16,12)
        self._build_workflow_header(layout)
        # Retain the selection model shared by the professional editors and the saved project.
        self.structure_filter = QComboBox(self)
        self.structure_filter.hide()
        self.structure_filter.addItem("全部结构", None)
        self.structure_filter.currentIndexChanged.connect(self._filter_assets)
        self.table = QTableWidget(0, 4, self)
        self.table.hide()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemChanged.connect(self._inclusion_changed)
        self.include_visible_button = QPushButton("纳入所列", self)
        self.exclude_visible_button = QPushButton("排除所列", self)
        self.include_visible_button.hide()
        self.exclude_visible_button.hide()
        self.include_visible_button.clicked.connect(lambda: self._guard(lambda: self.set_visible_inclusion(True)))
        self.exclude_visible_button.clicked.connect(lambda: self._guard(lambda: self.set_visible_inclusion(False)))
        self.excluded_label = QLabel(self)
        self.excluded_label.hide()

        review = self.result_review_layout
        viewbar = QHBoxLayout()
        self.view_combo = QComboBox()
        self.view_combo.addItem("横断面", "section")
        self.view_combo.addItem("施工纵断面", "profile")
        self.view_combo.currentIndexChanged.connect(self._result_view_changed)
        viewbar.addWidget(self.view_combo)
        self.layers = {}
        self.result_layer_controls = QWidget()
        layer_layout = QHBoxLayout(self.result_layer_controls)
        layer_layout.setContentsMargins(0, 0, 0, 0)
        for key, name in (("ground", "地面"), ("structure", "结构"), ("construction", "施工"), ("quantities", "挖填")):
            box = QCheckBox(name)
            box.setChecked(True)
            box.stateChanged.connect(self._draw)
            layer_layout.addWidget(box)
            self.layers[key] = box
        viewbar.addWidget(self.result_layer_controls)
        self.result_profile_preview_button = QPushButton("生成结构纵断面")
        self.result_profile_preview_button.clicked.connect(lambda: self._guard(self.query_station, notice="查看断面"))
        self.result_profile_preview_button.hide()
        viewbar.addWidget(self.result_profile_preview_button)
        viewbar.addStretch()
        review.addLayout(viewbar)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        self.figure = Figure(figsize=(8, 5), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        review.addWidget(self.canvas, 1)
        self.result_browse_controls = QWidget()
        browse = QHBoxLayout(self.result_browse_controls)
        browse.setContentsMargins(0, 0, 0, 0)
        self.previous = QPushButton("上一断面")
        self.previous.clicked.connect(lambda: self.slider.setValue(self.slider.value()-1))
        browse.addWidget(self.previous)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self._browse_changed)
        browse.addWidget(self.slider, 1)
        self.next = QPushButton("下一断面")
        self.next.clicked.connect(lambda: self.slider.setValue(self.slider.value()+1))
        browse.addWidget(self.next)
        self.station_spin = QDoubleSpinBox()
        self.station_spin.setDecimals(3)
        self.station_spin.setRange(-1e8, 1e8)
        self.station_spin.setSuffix(" m")
        browse.addWidget(self.station_spin)
        self.query_button = QPushButton("查看此桩")
        self.query_button.clicked.connect(lambda: self._guard(self.query_station, notice="查看断面"))
        browse.addWidget(self.query_button)
        review.addWidget(self.result_browse_controls)
        self.section_label = QLabel("计算或打开已保存成果后，可逐桩查看断面。")
        self.section_label.setWordWrap(True)
        review.addWidget(self.section_label)
        self._terrain_options={"conflict_policy":"points_priority","duplicate_point_policy":"max","contour_crossing_policy":"release_conflicting_segments"};self._draw()
        self._refresh_workflow()

    @staticmethod
    def _style_step_button(button,background,hover,*,foreground="#FFFFFF",border=None):
        button.setMinimumHeight(42)
        button.setStyleSheet(f"QPushButton {{background:{background};color:{foreground};border:1px solid {border or background};border-radius:6px;padding:8px 16px;font-weight:600;}} QPushButton:hover {{background:{hover};}} QPushButton:disabled {{background:#EDF0F4;color:#8B96A5;border-color:#DCE2E9;}}")

    @staticmethod
    def _structure_key(asset):
        return str(asset.get("kind") or ""),str(asset.get("section_type") or "")

    @staticmethod
    def _structure_label(asset):
        from 土石方计算.io.network_exporter import SECTION_NAMES
        shape=SECTION_NAMES.get(asset.get("section_type"),asset.get("section_type") or "其他结构")
        family={"pressure_pipe":"有压管道","pipe":"管道","siphon":"倒虹吸","open_channel":"明渠","culvert":"暗涵","aqueduct":"渡槽","tunnel":"隧洞"}.get(asset.get("kind"))
        if asset.get("kind") in {"pressure_pipe","pipe","siphon"} and asset.get("section_type") in {"circular_siphon","circular_channel"}:return family+"（圆管）"
        return f"{family} · {shape}" if family and family not in shape else shape

    def _filter_assets(self,*_):
        selected=self.structure_filter.currentData();first=None
        blocked=self.table.blockSignals(True)
        try:
            for row,(_,asset) in enumerate(self._all_assets()):
                visible=selected is None or self._structure_key(asset)==tuple(selected)
                self.table.setRowHidden(row,not visible)
                if visible and first is None:first=row
            current=self.table.currentRow()
            if first is not None and (current<0 or self.table.isRowHidden(current)):self.table.selectRow(first)
        finally:
            self.table.blockSignals(blocked)
        if not blocked:self._selection_changed()
        else:self._refresh_workflow()

    def _inclusion_changed(self,item):
        if item.column()!=0 or self._restoring:return
        assets=self._all_assets()
        if item.row()<0 or item.row()>=len(assets):return
        asset=assets[item.row()][1]
        enabled=item.checkState()==Qt.Checked
        if enabled==asset.get("enabled",True):return
        if not self._require_applied_workspace():
            self._refresh_assets()
            return
        self._apply_inclusion([asset],enabled)

    def set_visible_inclusion(self,enabled):
        if not self._require_applied_workspace():return
        selected=self.structure_filter.currentData()
        assets=[asset for _,asset in self._all_assets()
                if selected is None or self._structure_key(asset)==tuple(selected)]
        self._apply_inclusion(assets,enabled)

    def _apply_inclusion(self,assets,enabled):
        changed=[asset for asset in assets if not asset.get("generated_aqueduct_foundation")
                 and asset.get("enabled",True)!=enabled]
        if not changed:return
        for asset in changed:
            asset["enabled"]=enabled
        self._invalidate()
        self._refresh_assets()
        if self._section_workspace is not None:self._ensure_section_workspace()
        self._log(f"已将{len(changed)}个对象"+("纳入本次计算。" if enabled else "排除本次计算，施工参数已保留。"))

    def open_siphon_profiles(self):
        if not self._require_applied_workspace():return
        from .siphon_profiles_dialog import SiphonProfilesDialog
        from 土石方计算.services.workbench_automatic_ranges import has_workbench_automatic_ranges, restore_workbench_automatic_ranges
        inputs=self._inputs
        if has_workbench_automatic_ranges(inputs):
            inputs=restore_inputs(restore_workbench_automatic_ranges(inputs))
        dialog=SiphonProfilesDialog(inputs,self)
        try:
            if dialog.exec()!=QDialog.Accepted or not dialog.changed_assets:return
            for row,updated in dialog.changed_assets.items():
                _,asset=dialog.rows[row]
                asset.clear()
                asset.update(updated)
            self._inputs=inputs
            self._refresh_source_diagnostics()
            self._invalidate()
            self._refresh_assets()
            self._log(f"已应用 {len(dialog.changed_assets)} 项倒虹吸纵断面设置。")
        finally:
            dialog.deleteLater()

    def open_transition_connections(self, *, candidate_id=None):
        if self.runner.isRunning() or getattr(self, "_ui_busy", False):return
        from .transition_connections_dialog import TransitionConnectionsDialog
        dialog=TransitionConnectionsDialog(self._inputs,self,draft_state=self._connection_draft_state,
                                           candidate_id=candidate_id)
        try:
            accepted=dialog.exec()==QDialog.Accepted
            draft=getattr(dialog,"draft_state",None)
            self._connection_draft_state=copy.deepcopy(draft() if callable(draft) else draft)
            if not accepted or not getattr(dialog,"updated_inputs",None):return
            self._inputs=restore_inputs(dialog.updated_inputs)
            self._refresh_source_diagnostics()
            self._invalidate()
            self._refresh_assets()
            self._rebase_auxiliary_draft()
            if self._section_workspace is not None:self._ensure_section_workspace()
            self._log("连接段设置已应用，计量对象与对应断面已更新。")
        finally:
            dialog.deleteLater()

    def _refresh_structure_filter(self):
        selected=self.structure_filter.currentData();groups={}
        for _,asset in self._all_assets():
            key=self._structure_key(asset)
            if key not in groups:groups[key]=[self._structure_label(asset),0]
            groups[key][1]+=1
        self.structure_filter.blockSignals(True);self.structure_filter.clear();self.structure_filter.addItem("全部结构",None)
        for key,(label,count) in groups.items():self.structure_filter.addItem(f"{label}（{count}）",key)
        index=next((i for i in range(self.structure_filter.count())
                    if self.structure_filter.itemData(i)==selected),0)
        self.structure_filter.setCurrentIndex(max(0,index));self.structure_filter.blockSignals(False)
        self._filter_assets()

    def _refresh_workflow(self):
        if not hasattr(self,"workflow_hint") or not hasattr(self,"structure_filter"):return
        self._refresh_terrain_source_label()
        name = str(self._source_channel_name or self._inputs.get("project_name") or "")
        self.workbench_project_name.setText(name)
        self.workbench_project_name.setVisible(bool(name))
        from 土石方计算.services.earthwork_scope import trenchless_exclusions
        from 土石方计算.services.sluice_gate import is_sluice_gate
        from 土石方计算.services.workbench_automatic_ranges import has_workbench_automatic_ranges
        from 土石方计算.services.workbench_calculator import workbench_requires_section_terrain
        busy=self.runner.isRunning() or getattr(self,"_ui_busy",False);assets=self._all_assets()
        readiness = self._workbench_readiness()
        automatic_ranges=has_workbench_automatic_ranges(self._inputs)
        has_bores = bool(trenchless_exclusions(self._inputs))
        has_gates = any(is_sluice_gate(asset) for _, asset in assets)
        structure_only = (has_bores or has_gates) and not (
            automatic_ranges or workbench_requires_section_terrain(self._inputs))
        query_available=False
        try:
            network,asset=self.selected_asset()
            from 土石方计算.services.unburied_preview import is_unburied_pipe
            query_available = not is_sluice_gate(asset) and (not self._result or (self._valid and
                (bool(self._section_groups.get(self._measured_asset_id(network,asset))) or is_unburied_pipe(asset))))
        except ValueError:pass
        self._refresh_source_actions(readiness)
        self._refresh_workbench_primary_action(readiness, busy)
        self.query_button.setEnabled(not busy and not structure_only and query_available)
        self._refresh_result_profile_action()
        self.drawing_settings_button.setEnabled(not busy and not structure_only)
        self.structure_filter.setEnabled(not busy and bool(assets))
        self.table.setEnabled(not busy)
        self.include_visible_button.setEnabled(not busy and bool(assets))
        self.exclude_visible_button.setEnabled(not busy and bool(assets))
        self.component_button.setEnabled(not busy and bool(self._result))
        has_bore_details=bool((self._result or {}).get("trenchless_excavation_rows"))
        self.trenchless_button.setVisible(has_bore_details)
        self.trenchless_button.setEnabled(not busy and has_bore_details)
        self.centerline_source_button.setEnabled(not busy and not self.map_terrain_runner.isRunning())
        self._refresh_workspace_actions()
        self._refresh_terrain_plan()
        self._refresh_section_preparation(readiness)
        self._refresh_results_stage(readiness=readiness)

    def _set_centerline_batch_network(self, network):
        from 土石方计算.services.network_alignment import NetworkAlignment

        previous = self._centerline_batch_network
        if previous and {**previous, "alignment": previous["alignment"].to_dict()} == network:
            return
        batch_network = copy.deepcopy(network)
        batch_network["alignment"] = NetworkAlignment.from_dict(network["alignment"])
        self._centerline_batch_network = batch_network
        self._refresh_workflow()

    def open_centerline_profile(self):
        if self.runner.isRunning() or self.map_terrain_runner.isRunning():
            raise ValueError("当前地形或算量任务尚未结束，请等待完成或取消。")
        from .centerline_profile_dialog import CenterlineProfileDialog
        dialog = CenterlineProfileDialog(self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def open_engineering_drawings(self):
        try:
            owner, asset = self.selected_asset()
        except ValueError:
            self.show_project_and_terrain()
            return
        self._open_section_preparation_item(route_identity(owner), asset["asset_id"])

    def bind_drawing_templates(self):
        return self.open_engineering_drawings()

    def _legacy_bind_drawing_templates(self):
        from .drawing_bindings_dialog import DrawingBindingsDialog
        from 土石方计算.services.drawing_bindings import apply_drawing_bindings
        if not self._inputs.get("networks"):raise ValueError("请先读取水面线成果")
        dialog=DrawingBindingsDialog(self._inputs,self)
        if dialog.exec()!=QDialog.Accepted:return
        candidate=copy.deepcopy(self._inputs)
        if dialog.project_context is not None:candidate["drawing_project_context"]=copy.deepcopy(dialog.project_context)
        report=apply_drawing_bindings(candidate,dialog.bindings)
        if report["rejected"]:raise ValueError("；".join(item["reason"] for item in report["rejected"]))
        if not report["applied_count"]:return
        candidate.pop("drawing_binding_issues",None)
        self._inputs=candidate
        self._invalidate();self._refresh_source_diagnostics();self._refresh_assets()
        self._log(f"已绑定{report['applied_count']}条真实图纸构造，替换{len(report['field_changes'])}项参数，保留{len(report['preserved_overrides'])}项用户覆盖；一键算量采用本次构造。")
        self.data_changed.emit()

    def _adopt_drawing_sources(self,inputs,previous_bindings=None,project_context=None):
        from 土石方计算.services.drawing_bindings import binding_candidates,restore_drawing_bindings
        if project_context:inputs["drawing_project_context"]=copy.deepcopy(project_context)
        try:
            from 土石方计算.services.drawing_station_mapping import infer_drawing_station_mapping
            mapping=infer_drawing_station_mapping(inputs)
            if mapping.get("confirmed"):
                context=inputs.setdefault("drawing_project_context",{})
                context["station_mapping_confirmed"]=True;context["station_mapping_evidence"]=mapping
        except ImportError:pass
        if previous_bindings:
            report=restore_drawing_bindings(inputs,previous_bindings)
            if report["rejected"]:
                inputs["drawing_binding_issues"]=report["rejected"]
                self._log("部分原图绑定已不匹配当前设计，保留待核清单；请重新绑定后算量。")
                return
        existing=inputs.get("drawing_bindings",[])
        candidates=[r for r in binding_candidates(inputs) if r.get("auto_applicable") and r.get("status")=="ready"
                    and not any(old.get("asset_id")==r.get("asset_id") and old.get("template_id")==r.get("template_id")
                        and old["station_start"]<=r["station_start"]+1e-7 and old["station_end"]>=r["station_end"]-1e-7 for old in existing)]
        if candidates:
            self._log("已找到可参考的原图构造；请在工程断面看板确认方案和桩号范围后采用。")

    def show_component_quantities(self):
        if not self._result:raise ValueError("请先计算或打开已有成果")
        records=self._result.get("quantity_items",[])
        if not records:raise ValueError("此历史成果没有材料构件明细，请使用当前图纸绑定重新计算")
        dialog=QDialog(self);dialog.setWindowTitle("材料构件工程量");dialog.resize(1100,650)
        layout=QVBoxLayout(dialog)
        length_materials=bool((self._result.get("special_pipe_materials") or {}).get("length_mode_active"))
        note=QLabel(("特殊材料按长度修正，土方与逐桩施工图保留原依据；未定位条目不对应实际桩号。" if length_materials else "按实际材料区域与铺设面计算；体积和面积分别计量。")+("当前为历史成果，需重算。" if not self._valid else ""));note.setWordWrap(True);layout.addWidget(note)
        table=QTableWidget(len(records),11);table.setHorizontalHeaderLabels(["对象","材料计量依据","长度m","起桩m","止桩m","构件","材料","等级","数量","单位","图纸模板"])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        material_names={"concrete":"混凝土","bedding":"垫层/找平","mortar":"砂浆","geomembrane":"防渗膜","membrane":"防渗膜","steel":"钢材","sand":"砂料","rockfill":"石渣换填","sand_gravel":"砂砾料"}
        template_names={item["template_id"]:(item.get("template_snapshot") or {}).get("title",item["template_id"])
                        for item in self._inputs.get("drawing_bindings",[])}
        template_names.update({item["scheme_id"]:(item.get("scheme_snapshot") or {}).get("title",item["scheme_id"])
                              for item in self._inputs.get("section_scheme_bindings",[])})
        for row,item in enumerate(records):
            unlocated=bool(item.get("special_material_group_id") or item.get("material_mode")=="length" or item.get("measurement_mode")=="length") and item.get("station_start") is None
            basis=item.get("quantity_basis_label") or item.get("material_basis_label") or ("按长度（未定位）" if unlocated else "按实际桩号")
            template=item.get("scheme_title") or template_names.get(item.get("scheme_id") or item.get("template_id"),item.get("scheme_id") or item.get("template_id") or "当前设计参数")
            values=[item.get("asset_name") or item.get("asset_id"),basis,item.get("length_m"),"未定位" if unlocated else item.get("station_start"),"未定位" if unlocated else item.get("station_end"),item.get("name"),material_names.get(item.get("material"),item.get("material")),item.get("grade"),item.get("quantity"),{"m3":"m³","m2":"m²"}.get(item.get("unit"),item.get("unit")),template]
            for column,value in enumerate(values):table.setItem(row,column,QTableWidgetItem(f"{value:.4f}" if isinstance(value,float) else str(value if value is not None else "")))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents);table.horizontalHeader().setStretchLastSection(True);layout.addWidget(table)
        close=QPushButton("关闭");close.clicked.connect(dialog.accept);layout.addWidget(close);dialog.exec()

    def show_trenchless_quantities(self):
        from 土石方计算.io.structure_quantity_tables import trenchless_quantity_note,trenchless_excavation_table
        title,headers,records=trenchless_excavation_table(self._result or {})
        if not records:raise ValueError("当前成果没有非开挖洞挖明细")
        dialog=QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(940,410)
        layout=QVBoxLayout(dialog)
        note=QLabel(trenchless_quantity_note(self._result) + (" 当前为历史成果。" if not self._valid else ""))
        note.setWordWrap(True)
        layout.addWidget(note)
        # The export keeps the internal object identifier in its second column.
        visible_columns=[index for index in range(len(headers)) if index!=1]
        table=QTableWidget(len(records),len(visible_columns))
        table.setHorizontalHeaderLabels([headers[index] for index in visible_columns])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        for row,record in enumerate(records):
            for column,index in enumerate(visible_columns):
                value=record[index]
                label="—" if value is None else f"{value:,.3f}" if isinstance(value,(int,float)) else str(value)
                table.setItem(row,column,QTableWidgetItem(label))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        close=QPushButton("关闭")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def _guard(self, callback, *, notice=None):
        try:
            return callback() is not False
        except CurrentDesignChanged as exc:
            self._navigate_workflow(0, prepare=False)
            self._focus_design_source()
            self._show_operation_notice("设计资料待更新", exc)
        except Exception as exc:
            if notice and isinstance(exc, (ValueError, OSError)):
                self._show_operation_notice(notice, exc)
            else:
                self._log(str(exc))
                QMessageBox.warning(self, "土石方算量", display_text(exc))
        return False

    def _show_operation_notice(self, title, message):
        self._log(message)
        InfoBar.warning(title, display_text(message), orient=Qt.Vertical, parent=self.workflow_stack.currentWidget(),
                        position=InfoBarPosition.TOP, duration=12000)

    def _log(self,text):self.messages.appendPlainText(display_text(text))

    def _invalidate(self,*_):
        if self._restoring:return
        self._input_revision += 1
        self._skipped_section_message=None
        basis=self._inputs.get("quantity_basis") or {}
        scheme_fields={"section_scheme_binding_count","section_scheme_binding_sha256"}
        if basis.keys()-scheme_fields:
            from 土石方计算.services.construction_defaults import refresh_quantity_basis
            refresh_quantity_basis(self._inputs)
        self._valid=False
        if self._result:self.summary.setText(result_scope_prefix(self._result)+"输入已改变，当前显示历史成果；请重新计算后保存。")
        if self._query_view and self._records and self._records[0] is self._query_view["section"]:
            self._browse_changed(self.slider.value(),draw=False)
        self._refresh_workflow()
        self.data_changed.emit()

    def _all_assets(self):
        assets=[(network,asset) for network in self._inputs.get("networks",[]) for asset in network.get("assets",[])]+[(None,pit) for pit in self._inputs.get("pits",[])]
        if getattr(self,"_valid",False) and getattr(self,"_result",None):
            seen={asset.get("asset_id") for _,asset in assets}
            for pit in self._result.get("inputs",{}).get("workbench",{}).get("pits",[]):
                if pit.get("generated_aqueduct_foundation") and pit.get("asset_id") not in seen:
                    assets.append((None,pit));seen.add(pit["asset_id"])
        return assets

    @staticmethod
    def _deferred_asset(asset):
        from 土石方计算.services.sluice_gate import is_sluice_gate

        if is_sluice_gate(asset):return False
        if asset.get("generated_aqueduct_foundation"):return False
        return asset.get("section_type") in {"box_foundation","rectangular_pit","pit"} or asset.get("kind") in {"pit","gate","box_foundation"}

    def selected_asset(self):
        row=self.table.currentRow();assets=self._all_assets()
        if 0<=row<len(assets):return assets[row]
        if len(assets)==1:return assets[0]
        raise ValueError("请先选择区段")

    def _read_current_project_from_button(self):
        self._clear_design_notice()
        try:
            imported = self.import_current_project()
        except Exception as exc:
            self._log(str(exc))
            InfoBar.error("读取失败", display_text(exc), parent=self.source_page,
                          position=InfoBarPosition.TOP, duration=8000)
            return
        if not imported:
            InfoBar.warning("暂未读取", "请先处理未应用修改。", parent=self.workflow_stack.currentWidget(),
                            position=InfoBarPosition.TOP, duration=8000)
            return
        self._notify_design_loaded("已读取项目文件中保存的水面线成果。" if self._read_saved_water else "")

    def _notify_design_loaded(self, next_step="", *, title="读取成功", fallback_name=""):
        content = self._design_source_names(self._all_assets()) or fallback_name or self.input_label.text()
        if next_step:
            content += "\n" + next_step
        notice = InfoBar.success(title, content, orient=Qt.Vertical, parent=self.workflow_stack.currentWidget(),
                                 position=InfoBarPosition.TOP, duration=9000)
        if notice is not None:
            notice.setProperty("workbenchDesignNotice", True)
            notice.contentLabel.setTextFormat(Qt.PlainText)

    def _clear_design_notice(self):
        for notice in self.findChildren(InfoBar):
            if notice.property("workbenchDesignNotice"):
                notice.close()

    def _design_source_names(self, assets):
        from 土石方计算.services.earthwork_scope import trenchless_method

        channel_name = str(self._source_channel_name or self._inputs.get("project_name") or "").strip()
        placeholders = {"", "-", "—", "/", "当前渠道工程", "默认管线"}
        channel_names = [channel_name] if channel_name not in placeholders else []
        pipeline_project = channel_name.endswith(("干管", "支管", "管线", "管道"))
        building_names = []

        def add_building_name(asset, method):
            name = str(asset.get("name") or asset.get("base_name") or "").strip()
            if name not in placeholders and name not in {asset.get("source_type"), (method or {}).get("method")}:
                building_names.append(name)

        for network, asset in assets:
            if asset.get("transition_candidate_id") or asset.get("generated_aqueduct_foundation"):
                continue
            owner = network or {}
            source = owner.get("source") or {}
            if source.get("kind") == "estimated_water_profile_connection":
                continue
            pipeline_route = source.get("kind") == "pressure_pipe_manager_data"
            if pipeline_route:
                route_name = str(owner.get("name") or "").strip()
                if (route_name not in placeholders and route_name != source.get("route_key")
                        and not re.fullmatch(r"流量段.*\s+整线\d+|连续整线\d+|.*连续整线", route_name)):
                    channel_names.append(route_name)

            method = trenchless_method(asset)
            source_type = str(asset.get("source_type") or "")
            canal_building = (source_type.startswith(("倒虹吸", "渡槽", "隧洞", "暗涵"))
                              or (asset.get("kind") in {"siphon", "aqueduct", "tunnel", "culvert"}
                                  and not source_type.startswith(("明渠", "有压管道", "自动估算连接段"))))
            if method or (canal_building and not (pipeline_project or pipeline_route)):
                add_building_name(asset, method)

        for record in self._inputs.get("excluded", []):
            asset = record.get("original_asset_snapshot") or record
            method = trenchless_method(asset) or trenchless_method(record)
            if method:
                add_building_name(asset if asset.get("name") or asset.get("base_name") else record, method)

        lines = []
        if channel_names:
            lines.append("渠道名称 " + "、".join(dict.fromkeys(channel_names)))
        if building_names:
            lines.append("建筑物名称 " + "、".join(dict.fromkeys(building_names)))
        return "\n".join(lines)

    def import_current_project(self):
        if not self._require_applied_workspace():return False
        if self._project_provider is None:raise ValueError("当前没有绑定主工程，请在主程序打开设计成果")
        from 土石方计算.adapters.workbench_sources import (
            crosses_legacy_flow_sections, estimate_workbench_project_connections, replay_gate_user_parameters,
        )
        snapshot=copy.deepcopy(self._project_provider())
        source_panel, inputs = _water_project_inputs(snapshot)
        current_source_hash = source_hash(snapshot)
        self._read_saved_water = snapshot.get("earthwork_recovered_saved_water", False)
        from 土石方计算.services.drawing_bindings import capture_drawing_overrides
        from 土石方计算.services.siphon_axis_choices import is_siphon_axis_asset,siphon_source_boundary
        previous_inputs=copy.deepcopy(self._inputs)
        previous_bindings=capture_drawing_overrides(self._inputs)
        project_context=copy.deepcopy(self._inputs.get("drawing_project_context"))
        def source_keys(value):
            keys=set()
            for network in value.get("networks",[]):
                if (network.get("source") or {}).get("kind")=="estimated_water_profile_connection":continue
                route=str(network.get("source_identity") or network.get("network_id") or "")
                for asset in network.get("assets",[]):
                    if not asset.get("source_identity") or asset.get("transition_candidate_id"):continue
                    shape=asset.get("section_type")
                    boundary=siphon_source_boundary(asset) if is_siphon_axis_asset(asset) else None
                    keys.add(("water_siphon_boundary",boundary,shape) if boundary else (
                        route,str(asset["source_identity"]),shape))
            return keys
        prior_keys,current_keys=source_keys(previous_inputs),source_keys(inputs)
        prior_name,current_name=previous_inputs.get("project_name") or "",inputs.get("project_name") or ""
        same_project=(self._source_hash == current_source_hash or
            (bool(prior_keys and current_keys and prior_keys.intersection(current_keys))
             and prior_name==current_name and (bool(current_name) or prior_keys==current_keys)))
        if not same_project:
            self.pipe_general.reset_context()
            self.pipe_segments.reset_context()
            self.pipe_profile_editor.restore_drafts([])
            self._pipe_key=None
            self._pipe_profile_member=None
            self._channel_profile_key=None
            self._pipe_exact_profile=False
            self._workbench_object=None
        if same_project:
            for key in ("slope_support_rows","slope_support_templates","special_pipe_materials"):
                if key in previous_inputs:inputs[key]=copy.deepcopy(previous_inputs[key])
        elif previous_inputs.get("slope_support_rows") or previous_inputs.get("slope_support_templates") or previous_inputs.get("special_pipe_materials"):
            self._log("当前工程来源与原支护清单或特殊材料配置不一致或无法确认，未将原支护清单、模板及特殊材料配置移入新工程。")
        if same_project:
            from 土石方计算.services.transition_connections import replay_transition_connections
            inputs,connection_report=replay_transition_connections(inputs,previous_inputs)
            if connection_report["replayed"]:
                self._log(f"已保留{len(connection_report['replayed'])}个连接段的计量设置，采用本次水面线高程。")
            for item in connection_report["pending_review"]:
                self._log(item["message"])
        inputs = estimate_workbench_project_connections(inputs, snapshot, estimate_circular=False)

        from 土石方计算.services.pipe_dimensions import (
            adopted_construction_diameter_fields, is_pipe_asset, normalize_pipe_dimensions,
        )
        from 土石方计算.services.sluice_gate import is_sluice_gate

        def retain_actual_outer(prior,asset,path):
            if prior.get("outer_diameter") is None or adopted_construction_diameter_fields(prior):
                return False
            sources=asset.get("parameter_sources") or {}
            overrides={**(asset.get("drawing_user_overrides") or {}),
                       **(asset.get("section_scheme_user_overrides") or {})}
            auto=prior.get("dn_envelope_diameter_m")
            if auto is not None and path not in overrides and not str(sources.get(path,"")).startswith("用户"):
                try:
                    if math.isclose(float(prior["outer_diameter"]),float(auto),rel_tol=1e-9,abs_tol=1e-9):return False
                except (TypeError,ValueError):pass
            return True

        def retain_construction_sizes(prior, current, asset, prefix):
            retained = set()
            for key in adopted_construction_diameter_fields(prior):
                value = copy.deepcopy(prior[key])
                current[key] = value
                path = f"{prefix}.{key}"
                asset.setdefault("drawing_user_overrides", {})[path] = value
                retained.add(path)
            return retained
        # A water-profile recalculation refreshes hydraulic geometry while
        # retaining construction choices the engineer has already entered.
        previous={asset.get("asset_id"):asset for _,asset in self._all_assets()}
        previous_assumptions=self._inputs.get("construction_assumptions",[])
        retained_assumptions=[]
        thickness_fields=("base_thickness","wall_thickness_left","wall_thickness_right","roof_thickness",
                          "wall_thickness","lining_thickness","material","lining_material","pipe_spacing",
                          "inner_chamfers","material_grade","material_specs","component_specs")
        for network in inputs.get("networks",[]):
            for asset in network.get("assets",[]):
                old=previous.get(asset.get("asset_id"))
                if (old and not crosses_legacy_flow_sections(old) and old.get("section_type")==asset.get("section_type")
                        and old.get("source_identity")==asset.get("source_identity") and same_project):
                    if is_sluice_gate(asset):
                        replay_gate_user_parameters(asset, old)
                        continue
                    from 土石方计算.services.tunnel_source_parameters import refresh_tunnel_source_parameters
                    refresh_tunnel_source_parameters(asset,old)
                    source_paths=set(asset.get("source_tunnel_parameter_paths") or [])
                    asset.setdefault("construction",{}).update({
                        key:copy.deepcopy(value) for key,value in old.get("construction",{}).items()
                        if "construction."+key not in source_paths})
                    for key in thickness_fields:
                        if key in old.get("section",{}) and "section."+key not in source_paths:
                            asset.setdefault("section",{})[key]=copy.deepcopy(old["section"][key])
                    section=asset.get("section",{})
                    prior_section=old.get("section",{})
                    actual_outer=retain_actual_outer(prior_section,old,"section.outer_diameter")
                    if actual_outer:section["outer_diameter"]=copy.deepcopy(prior_section["outer_diameter"])
                    pipe_preserved=retain_construction_sizes(prior_section,section,asset,"section")
                    dn_section=section.get("nominal_diameter_m") is not None or any(
                        pipe.get("nominal_diameter_m") is not None for pipe in section.get("pipes") or [])
                    if not dn_section and not actual_outer and section.get("inner_diameter") is not None and section.get("wall_thickness") is not None:
                        section["outer_diameter"]=float(section["inner_diameter"])+2*float(section["wall_thickness"])+2*float(section.get("lining_thickness") or 0.)
                    old_pipes=old.get("section",{}).get("pipes") or []
                    new_pipes=section.get("pipes") or []
                    if old_pipes and len(old_pipes)==len(new_pipes):
                        for index,(prior,current) in enumerate(zip(old_pipes,new_pipes),1):
                            pipe_preserved.update(retain_construction_sizes(prior,current,asset,f"section.pipes[{index}]"))
                            for key in ("wall_thickness","lining_thickness","material","lining_material"):
                                if key in prior:
                                    current[key]=copy.deepcopy(prior[key]);pipe_preserved.add(f"section.pipes[{index}].{key}")
                            pipe_outer=retain_actual_outer(prior,old,f"section.pipes[{index}].outer_diameter")
                            if pipe_outer:
                                current["outer_diameter"]=copy.deepcopy(prior["outer_diameter"])
                                pipe_preserved.add(f"section.pipes[{index}].outer_diameter")
                            if (not dn_section and not pipe_outer and current.get("inner_diameter") is not None
                                    and current.get("wall_thickness") is not None):
                                current["outer_diameter"]=float(current["inner_diameter"])+2*float(current["wall_thickness"])+2*float(current.get("lining_thickness") or 0.)
                    preserved_fields={"construction."+key for key in old.get("construction",{}) if "construction."+key not in source_paths}
                    preserved_fields.update("section."+key for key in thickness_fields if key in old.get("section",{}) and "section."+key not in source_paths)
                    if actual_outer:preserved_fields.add("section.outer_diameter")
                    preserved_fields.update(pipe_preserved)
                    for key,value in old.get("parameter_sources",{}).items():
                        if key in preserved_fields:asset.setdefault("parameter_sources",{})[key]=copy.deepcopy(value)
                    normalize_pipe_dimensions(asset)
                    if old.get("parameter_source")=="user_confirmed":asset["parameter_source"]="user_confirmed"
                    retained_assumptions.extend(copy.deepcopy(item) for item in previous_assumptions
                        if item.get("asset_id")==asset.get("asset_id") and item.get("field") in preserved_fields)
        if retained_assumptions:inputs.setdefault("construction_assumptions",[]).extend(retained_assumptions)
        from 土石方计算.services.construction_defaults import apply_assumed_construction
        apply_assumed_construction(inputs)
        self._adopt_drawing_sources(inputs,previous_bindings,project_context)
        if same_project:
            from 土石方计算.services.section_scheme_bindings import replay_unbound_flow_section_parameters
            inputs = replay_unbound_flow_section_parameters(inputs, previous_inputs)
        if previous_inputs.get("section_scheme_bindings"):
            from 土石方计算.services.section_scheme_bindings import replay_section_schemes
            inputs=replay_section_schemes(inputs,previous_inputs)
        if same_project:
            from 土石方计算.services.drawing_bindings import _slice
            # Frame and pipe edits may belong to a sliced source part whose
            # suffixed id does not exist until the fresh design is split again.
            # Split the NEW profile; never restore the old hydraulic elevations.
            for prior_network in previous_inputs.get("networks",[]):
                route_source=prior_network.get("source_identity") or prior_network.get("network_id")
                network=next((n for n in inputs.get("networks",[]) if
                    (n.get("source_identity") or n.get("network_id"))==route_source),None)
                if network is None:continue
                for old in prior_network.get("assets",[]):
                    prior_section=old.get("section") or {}
                    has_frames=bool(prior_section.get("aqueduct_frame_layout"))
                    has_pipe_edits=is_pipe_asset(old) and (
                        adopted_construction_diameter_fields(prior_section)
                        or retain_actual_outer(prior_section,old,"section.outer_diameter")
                        or any(prior_section.get(k) is not None for k in ("wall_thickness","lining_thickness"))
                        or any(adopted_construction_diameter_fields(p)
                            or retain_actual_outer(p,old,f"section.pipes[{i}].outer_diameter")
                            or any(p.get(k) is not None for k in ("wall_thickness","lining_thickness"))
                            for i,p in enumerate(prior_section.get("pipes") or [],1)))
                    if not has_frames and not has_pipe_edits:continue
                    family=[a for a in network.get("assets",[]) if a.get("source_identity")==old.get("source_identity")
                        and a.get("section_type")==old.get("section_type")]
                    a,b=old.get("station_start"),old.get("station_end")
                    targets=[]
                    if a is not None and b is not None:
                        for current in list(family):
                            start,end=max(a,current["station_start"]),min(b,current["station_end"])
                            if end>start+1e-7:targets.append(_slice(network,current,start,end))
                    if not targets:
                        if has_frames:
                            inputs.setdefault("unmatched_aqueduct_frame_layouts",[]).append(copy.deepcopy(old))
                            inputs.setdefault("section_scheme_binding_issues",[]).append({"reason":
                                old.get("name",old["asset_id"])+"：原排架区段已不在当前设计范围，旧布置已保留，须核对来源区段后再算量"})
                        continue
                    for asset in targets:
                        section=asset.setdefault("section",{})
                        if has_pipe_edits:
                            pairs=[("section",prior_section,section)]
                            old_pipes,new_pipes=prior_section.get("pipes") or [],section.get("pipes") or []
                            if len(old_pipes)==len(new_pipes):
                                pairs.extend((f"section.pipes[{i}]",prior,current)
                                    for i,(prior,current) in enumerate(zip(old_pipes,new_pipes),1))
                            for prefix,prior,current in pairs:
                                keys=[k for k in ("wall_thickness","lining_thickness","material","lining_material") if k in prior]
                                if retain_actual_outer(prior,old,prefix+".outer_diameter"):keys.append("outer_diameter")
                                for key in keys:
                                    current[key]=copy.deepcopy(prior[key])
                                paths={f"{prefix}.{key}" for key in keys}
                                paths.update(retain_construction_sizes(prior,current,asset,prefix))
                                for path in paths:
                                    if path in old.get("parameter_sources",{}):
                                        asset.setdefault("parameter_sources",{})[path]=copy.deepcopy(old["parameter_sources"][path])
                            normalize_pipe_dimensions(asset)
                        if has_frames:
                            for key in ("aqueduct_frame_layout","discrete_components"):
                                if key in prior_section:section[key]=copy.deepcopy(prior_section[key])
                            asset["aqueduct_frame_refresh_status"]="retained_pending_source_validation"
                            inputs.setdefault("diagnostics",[]).append({"code":"aqueduct_frames_retained_on_refresh",
                                "severity":"info","asset_id":asset["asset_id"],"source_identity":asset.get("source_identity"),
                                "message":asset.get("name",asset["asset_id"])+"：已保留排架布置和旧柱高；算量前核对当前水面线、地形及路线，变化时须重新生成排架。"})
        from 土石方计算.services.estimated_connections import estimate_circular_connection_gaps
        if same_project:
            from 土石方计算.services.calculation_selection import replay_calculation_selection
            prior_estimate_ids = {item["asset_id"] for item in previous_inputs.get("connector_estimates", ())
                                  if item.get("section_type") == "circular_culvert"}
            prior_networks = previous_inputs.get("networks", ())
            # Restore the reference culverts' ranges before using their envelopes.
            inputs, selection_report = replay_calculation_selection(inputs, {
                "networks": [network for network in prior_networks if network.get("network_id") not in prior_estimate_ids],
            })
            from 土石方计算.services.siphon_axis_choices import refresh_siphon_axis_choices
            from 土石方计算.services.pipe_profile_sources import refresh_pipe_profile_choices
            refresh_siphon_axis_choices(inputs,previous_inputs)
            refresh_pipe_profile_choices(inputs,previous_inputs)
        inputs = estimate_circular_connection_gaps(inputs)
        if same_project:
            prior_estimate_ids.difference_update(row["previous_candidate_id"] for row in connection_report["replayed"])
            if prior_estimate_ids:
                # The newly generated connections have their own inclusion choices.
                current = {"networks": [network for network in inputs["networks"]
                                        if network.get("network_id") in prior_estimate_ids]}
                previous = {"networks": [network for network in prior_networks
                                         if network.get("network_id") in prior_estimate_ids]}
                selected, report = replay_calculation_selection(current, previous)
                by_id = {network["network_id"]: network for network in selected["networks"]}
                inputs["networks"] = [by_id.get(network["network_id"], network) for network in inputs["networks"]]
                selection_report["warnings"].extend(report["warnings"])
                inputs["unmatched_calculation_selection"].extend(report["warnings"])
            for issue in selection_report["warnings"]:
                self._log(issue["message"])
        if inputs.get("connector_estimates"):
            self._log(f"已按相邻断面和水面线估算 {len(inputs['connector_estimates'])} 个连接区段，可在「工程与地形」核对。")
        from 土石方计算.services.trenchless_edits import replay_trenchless_section_overrides
        inputs = replay_trenchless_section_overrides(inputs, previous_inputs,
            same_project=same_project or self._source_hash == current_source_hash)
        self._source_channel_name = source_channel_name(source_panel)
        self._saved_water_centerline = None
        self._workbench_design_stale = False
        self._inputs=inputs;self._source_hash=current_source_hash;self._invalidate();self._refresh_assets()
        from 土石方计算.services.batch_cover_profiles import is_pressure_cover_asset
        automatic_cover={asset["asset_id"] for _,asset in self._all_assets()
            if is_pressure_cover_asset(asset) and (asset.get("construction") or {}).get("burial_mode")=="cover_depth"}
        construction_pending=set()
        messages=[]
        for issue in inputs.get("diagnostics",[]):
            if issue.get("resolved") or issue.get("code")=="explicit_construction_assumptions":continue
            code,identifier=issue.get("code"),issue.get("asset_id")
            if code=="missing_design_profile" and identifier in automatic_cover:continue
            if code=="missing_construction" and identifier:construction_pending.add(identifier)
            else:messages.append(issue.get("message",str(issue)))
        for message in dict.fromkeys(messages):self._log(message)
        if construction_pending:self._log(f"{len(construction_pending)} 个对象的施工参数待补，可在「工程与地形」查看。")
        self._log("已读取水面线成果。")
        return True

    def choose_input(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开已保存的工程或算量成果", "",
                                             "项目文件 (*.qxproj);;一键算量成果 (工程量.xlsx);;兼容资料 (*.json)")
        if path:
            self.open_input_async(path)

    def _prepare_open_input(self, path):
        if path.suffix.lower() != ".xlsx":
            return self._read_open_input(path), path

        from 土石方计算.services.workbench_delivery import delivery_project_path, read_delivery_manifest

        workbook = filesystem_path(path, extended=True)
        manifest = read_delivery_manifest(path.parent)
        project = delivery_project_path(path.parent)
        if (path.name != "工程量.xlsx" or not workbook.is_file()
                or manifest.get("status") not in {"READY", "READY_WITH_DRAWING_ISSUES"}
                or not manifest.get("project_id") or not manifest.get("input_hash") or not project.is_file()):
            raise ValueError("找不到该工程量表对应的算量工程记录，请打开已保存的项目文件。")
        kind, data = self._read_open_input(project)
        state = (data[0].get("earthwork_panel") or {}) if kind == "project" else {}
        if (state.get("project_id") != manifest["project_id"]
                or (state.get("last_result") or {}).get("input_hash") != manifest["input_hash"]):
            raise ValueError("工程记录与选中的算量成果不一致。")
        return (kind, data), project

    @staticmethod
    def _read_open_input(path):
        is_project = path.suffix.lower() == ".qxproj"
        if is_project:
            from app_渠系计算前端.project_codec import ProjectCodec
            raw = ProjectCodec.read(path)
        else:
            raw = json.loads(filesystem_path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("请选择项目管理保存的工程文件或已保存的算量成果。")
        if _is_saved_quantity_result(raw):
            from 土石方计算.services.workbench_calculator import enrich_saved_sections
            return "quantity", enrich_saved_sections(raw)
        water = raw.get("merged_panel") or raw.get("water_profile_panel")
        standalone = raw.get("kind") == "section_workbench"
        earthwork = raw if standalone else (raw.get("earthwork_panel") or {})
        has_workbench = earthwork.get("kind") == "section_workbench"
        if is_project:
            inputs = earthwork.get("workbench_inputs") or {}
            terrain = earthwork.get("terrain") or {}
            has_progress = standalone or (has_workbench and (earthwork.get("last_result") or any(
                inputs.get(key) for key in ("networks", "pits", "excluded", "transition_candidates"))))
            if has_progress:
                from 土石方计算.adapters.workbench_sources import with_saved_batch_bore_diameters
                from 土石方计算.services.pipe_profile_sources import with_saved_water_axes
                project = ProjectCodec.normalize({"version": "2.0", "earthwork_panel": earthwork},
                                                 copy_input=False) if standalone else raw
                return "project", (with_saved_batch_bore_diameters(with_saved_water_axes(project)), None)
            has_terrain = has_workbench and bool(terrain.get("path") or terrain.get("cache_path"))
            if water:
                try:
                    return "project", (raw, _prepare_saved_water_project(raw))
                except ValueError:
                    if not has_terrain:
                        raise
            if has_terrain:
                return "project", (raw, None)
            if has_workbench:
                raise ValueError("文件中没有已计算的水面线或已保存的挖填成果。")
        if water and not has_workbench:
            return "water", _prepare_saved_water_project(raw)
        return "input", raw

    def _apply_open_input(self, value, path, *, preserve_task_feedback=False):
        kind, data = value
        if kind == "quantity":
            self.load_result(data, enriched=True)
            self._log("已打开保存的断面法成果，数量保持原值。")
        elif kind == "water":
            self._apply_saved_water_project(data, preserve_task_feedback=preserve_task_feedback)
        elif kind == "project":
            self._apply_project_file(data, path, preserve_task_feedback=preserve_task_feedback)
        else:
            self._apply_input(data, path, preserve_task_feedback=preserve_task_feedback)

    def _saved_water_state(self, design, saved_state=None):
        inputs, channel_name, centerline = design
        self._adopt_drawing_sources(inputs)
        state = {
            "schema_version": "1.0", "kind": "section_workbench", "project_id": str(uuid.uuid4()),
            "settings": self._accuracy(),
            "drawing_options": self._drawing_options, "output_directory": self.output_directory.text(),
            "auto_delivery": self.auto_delivery.isChecked(),
        }
        if saved_state and saved_state.get("kind") == "section_workbench":
            state.update(saved_state)
        state.update(workbench_inputs=serialize_inputs(inputs), source_project_hash=None,
                     ui_state={"workflow_step": 0, "source_channel_name": channel_name,
                               "saved_water_centerline": centerline})
        return state

    def _apply_project_file(self, value, path, *, preserve_task_feedback):
        project, design = value
        state = project.get("earthwork_panel") or {}
        if design is not None:
            state = self._saved_water_state(design, state)
            project = {**project, "earthwork_panel": state}
        if self._project_file_opener is not None:
            self._opening_project_file = preserve_task_feedback
            try:
                opened = self._project_file_opener(str(path), project)
            finally:
                self._opening_project_file = False
            if not opened:
                self.feedback.cancelled("已取消打开项目文件。")
                return
            if design is not None and self.project_id == state["project_id"] and self._project_provider is not None:
                current = self._project_provider()
                water = current.get("merged_panel") or current.get("water_profile_panel") or {}
                if water.get("calculated_nodes") and water.get("water_result_current") is not False:
                    self._source_hash = source_hash(current)
        else:
            self.from_project_dict({**state, "source_project_hash": None}, preserve_task_feedback=preserve_task_feedback)
            self.data_changed.emit()
        guidance = self._project_open_guidance(design is not None)
        self._log(guidance)
        if preserve_task_feedback:
            self._notify_design_loaded(guidance, title="项目已打开", fallback_name=path.stem)

    def _project_open_guidance(self, from_water):
        from 土石方计算.services.earthwork_scope import trenchless_exclusions
        from 土石方计算.services.workbench_calculator import workbench_requires_section_terrain

        if self._result:
            if self._valid:
                return "已恢复上次算量成果。"
            return "已恢复上次算量成果，当前输入需重算。"
        if not self._all_assets() and not trenchless_exclusions(self._inputs):
            if self._inputs.get("transition_candidates"):
                return "已恢复连接段资料，可在「工程与地形」查看待补范围。"
            return "已恢复地形来源，接下来读取水面线成果。" if self.terrain_path.text() else "待读取水面线成果。"
        restored = "已带入水面线成果。" if from_water else "已恢复上次挖填进度。"
        if not self.terrain_path.text() and workbench_requires_section_terrain(self._inputs):
            return restored + "接下来导入地形图。"
        if self.terrain_path.text():
            return restored + "已恢复地形来源。"
        return restored

    def _apply_saved_water_project(self, design, *, preserve_task_feedback=False):
        self.from_project_dict(self._saved_water_state(design), preserve_task_feedback=preserve_task_feedback)
        self.data_changed.emit()
        next_step = self._project_open_guidance(True)
        self._log(next_step)
        if preserve_task_feedback:
            self._notify_design_loaded(next_step)

    def open_input_async(self,path):
        path=resolved_path(path)
        self._clear_design_notice()
        def work(token):
            token.raise_if_cancelled()
            prepared = self._prepare_open_input(path)
            token.raise_if_cancelled()
            return prepared
        self._submit_task(work, title="工程资料读取", message="正在打开项目文件。",
                          on_success=lambda value: self._apply_open_input(*value, preserve_task_feedback=True),
                          on_error=lambda error: self._log("打开资料失败："+str(error)))

    def load_input(self,path):
        self._apply_open_input(*self._prepare_open_input(resolved_path(path)))

    def _apply_input(self,raw,path,*,preserve_task_feedback=False):
        if _is_saved_quantity_result(raw):
            self.load_result(raw);self._log("已打开保存的断面法成果，数量保持原值。")
        elif raw.get("assets") is not None and raw.get("alignment"):
            from 土石方计算.services.network_project import load_network
            network,identity=load_network(path);self._inputs={"networks":[network],"pits":[],"excluded":[],"diagnostics":[],"input_files":[identity]}
            self._source_hash=None;self._saved_water_centerline=None;self._source_channel_name="";self._invalidate();self._refresh_assets()
        elif isinstance(raw.get("networks"),list):
            from 土石方计算.io.independent_terrain import file_sha256
            self._inputs=restore_inputs(raw)
            self._inputs.setdefault("pits",[]);self._inputs.setdefault("excluded",[]);self._inputs.setdefault("diagnostics",[])
            self._inputs.setdefault("input_files",[]).append({"path":str(path),"sha256":file_sha256(path)})
            self._source_hash=None;self._saved_water_centerline=None;self._source_channel_name="";self._invalidate();self._refresh_assets()
        elif raw.get("kind")=="section_workbench" or (raw.get("earthwork_panel") or {}).get("kind")=="section_workbench":
            from 土石方计算.adapters.workbench_sources import with_saved_batch_bore_diameters
            from 土石方计算.services.pipe_profile_sources import with_saved_water_axes
            state = (raw if raw.get("kind") == "section_workbench"
                     else with_saved_batch_bore_diameters(with_saved_water_axes(raw))["earthwork_panel"])
            self.from_project_dict({**state, "source_project_hash": None}, preserve_task_feedback=preserve_task_feedback)
        else:
            from 土石方计算.adapters.workbench_sources import estimate_workbench_project_connections, import_workbench_project
            inputs = import_workbench_project(raw)
            if any(issue.get("code") == "no_design_sources" for issue in inputs.get("diagnostics", [])):
                raise ValueError("文件中没有已计算的水面线或已保存的挖填成果。")
            self._inputs=estimate_workbench_project_connections(inputs,raw)
            self._source_channel_name=source_channel_name(raw.get("merged_panel") or raw.get("water_profile_panel") or {})
            self._source_hash=None;self._saved_water_centerline=None;self._invalidate();self._refresh_assets()

    def load_result(self,payload,*,enriched=False):
        from 土石方计算.services.workbench_calculator import enrich_saved_sections
        if not enriched:payload=enrich_saved_sections(payload)
        self._centerline_batch_network = None
        self._pending_terrain_path = ""
        self._pending_terrain_note = ""
        self._terrain_map_note = ""
        self._saved_water_centerline = None
        self._terrain_import_failed=False
        self.last_delivery_path = ""
        self.section_bore_card.reset_context()
        inp=payload.get("inputs",{});work=inp.get("workbench",inp.get("workbench_inputs"))
        if not work and inp.get("network"):work={"networks":[inp["network"]],"pits":[],"excluded":[],"diagnostics":[]}
        if work:self._inputs=restore_inputs(work)
        self._source_hash=None;self._source_channel_name="";self._tin=None;terrain=payload.get("terrain",{})
        self.terrain_path.setText(terrain.get("path",""));self._terrain_identity=copy.deepcopy(terrain)
        self._map_restore_attempt=None;self._sync_terrain_mode(terrain)
        restoring=self._restoring;self._restoring=True
        try:self._restore_accuracy(inp.get("accuracy",{}))
        finally:self._restoring=restoring
        self._calculated((None,payload))

    def choose_terrain_file(self, parent=None):
        path, _ = QFileDialog.getOpenFileName(parent or self, "导入地形图或测点", "",
            "地形资料 (*.dxf *.dwg *.csv *.xyz *.txt *.3dm *.npz *.json)")
        return path

    def choose_terrain(self):
        path=self.choose_terrain_file()
        if path:self._guard(lambda:self.load_terrain_path(path))

    def _new_terrain_options(self,path,networks):
        from 土石方计算.io.terrain_corridor import automatic_terrain_corridor
        options=copy.deepcopy(self._terrain_options)
        for key in ("point_layers","contour_layers"):options.pop(key,None)
        saved_scope=options.get("route_corridor")
        if saved_scope is None or saved_scope.get("automatic"):
            options.pop("route_corridor",None)
            if not self._inputs.get("pits"):
                corridor=automatic_terrain_corridor(Path(path),networks)
                if corridor is not None:options["route_corridor"]=corridor
        root=self.output_directory.text().strip() or str(default_delivery_root())
        options.setdefault("clean_output_dir",str(Path(root)/"地形自动净化"/Path(path).stem))
        return options

    def _select_terrain_path(self, path):
        path = str(Path(path).resolve())
        self._pending_terrain_path = path
        self._pending_terrain_note = ""
        self._refresh_workflow()
        return path

    def _profile_terrain_request(self):
        if not self._pending_terrain_path:
            return self._terrain_request()
        return {"path": self._pending_terrain_path, "tin": None, "identity": {},
                "mode": "combined", "options": copy.deepcopy(self._terrain_options)}

    def _commit_selected_terrain(self, tin, path):
        self.map_terrain_runner.invalidate()
        self._pending_terrain_path = ""
        self._pending_terrain_note = ""
        self._map_restore_attempt = None
        tin.import_report.setdefault("path", path)
        for key in ("point_layers", "contour_layers"):
            self._terrain_options.pop(key, None)
        self._accept_tin(tin)
        self._invalidate()

    def _load_selected_terrain(self,token,path,options,progress):
        from 土石方计算.io.independent_terrain import load_terrain
        tin=load_terrain(path,terrain_mode="combined",terrain_options=options,cancelled=lambda:token.is_cancelled,
            progress=progress)
        token.raise_if_cancelled()
        progress("terrain_cache",0.,"正在保存计算地形缓存。")
        return self._cache_tin(tin,token,options)

    def load_terrain_path(self,path):
        if self.runner.isRunning():
            raise RuntimeError("当前任务正在进行，请完成或取消后再导入地形。")
        options=self._new_terrain_options(path,self._inputs.get("networks",[]))
        path=self._select_terrain_path(path)
        started=perf_counter()
        def work(token):
            return self._load_selected_terrain(token,path,options,lambda *a:self._task_progress_event.emit(token.generation,*a))
        def done(tin):
            self._commit_selected_terrain(tin, path)
            self._log(f"地形就绪：{len(tin.points):,}顶点、{len(tin.triangles):,}三角面；处理总耗时 {perf_counter()-started:.2f} 秒；计算缓存已保存，可用于算量。")
            corridor=self._terrain_identity.get("corridor_preparation") or {}
            if corridor.get("kind")=="route_scoped_streaming_survey_sources":
                self._log(f"大图按工程路线两侧各 {corridor['half_width_m']:g} m 读取。测点高程保持原值，"
                          f"等高线平面简化容差 {corridor['constant_z_xy_tolerance_m']:g} m，处理范围见地形报告。")
            clean=self._terrain_identity.get("clean_terrain",{})
            if clean.get("dxf_path"):self._log("已自动去除原图杂项，干净地形图："+clean["dxf_path"])
            self.data_changed.emit()

        def cancelled():
            self._pending_terrain_note = "地形读取已取消。可重试或选择其他地形。"
            if not self.terrain_path.text():
                self._terrain_import_failed = True
            self._log(self._pending_terrain_note)

        self._submit_task(work,title="地形处理",message="正在读取、净化并建立计算地形。",on_success=done,on_error=self._terrain_failed,on_cancelled=cancelled,success_message="地形已导入。")

    def _terrain_failed(self,error):
        message = "地形处理未完成：" + display_text(error)
        if self._pending_terrain_path:
            self._pending_terrain_note = message
            if not self.terrain_path.text():
                self._terrain_import_failed = True
        else:
            self._terrain_import_failed = True
            self._terrain_map_note = message
        self._refresh_workflow()
        self._log(message);report=getattr(error,"import_report",{}) or {}
        if report:self._log(json.dumps(report,ensure_ascii=False,default=str)[:3500])

    def _sync_terrain_mode(self,identity):
        mode=identity.get("terrain_mode")
        if mode not in ("points","combined","mesh"):
            has_resource=any(identity.get(key) for key in ("path","cache_path","source_sha256","vertex_count","face_count")) or self._tin is not None
            mode="mesh" if has_resource else "combined"
        self._terrain_processing_mode=mode

    def _accept_tin(self,tin):
        before = self._terrain_identity
        self._tin=tin;self._terrain_import_failed=False;self._terrain_identity=copy.deepcopy(getattr(tin,"import_report",{}))
        self._terrain_map_note = ""
        if self._terrain_identity.get("path"):self.terrain_path.setText(self._terrain_identity["path"])
        if (before.get("path") != self._terrain_identity.get("path")
                and before.get("cache_sha256") == self._terrain_identity.get("source_sha256")
                and before.get("cache_sha256")):
            self._log("原地形文件暂不可用，已从校验通过的工程缓存恢复计算地形。")
        elif (before.get("cache_sha256") and before.get("cache_sha256") != self._terrain_identity.get("cache_sha256")
                and before["cache_sha256"] == self._terrain_identity.get("rebuilt_from_cache_sha256")):
            self._log("已从原地形重建缓存，计算网格与工程记录一致。")
        self._sync_terrain_mode(self._terrain_identity)
        self._refresh_visible_design_profile()
        self._refresh_workflow()

    @staticmethod
    def _cache_tin(tin,token,options):
        from 土石方计算.io.independent_terrain import save_terrain,file_sha256
        identity=getattr(tin,"import_report",{})
        folder=Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())/"CanalHydraulics"/"earthwork"/"terrain-cache"
        folder.mkdir(parents=True,exist_ok=True);token.raise_if_cancelled()
        # Fail promptly on an unwritable cache instead of tempfile's Windows
        # name retry loop; existing projects retain their recorded cache paths.
        staging=str(folder/("terrain-"+uuid.uuid4().hex+".npz"))
        fd=os.open(staging,os.O_CREAT|os.O_EXCL|os.O_RDWR);os.close(fd)
        # A mode round trip may retain different source metadata. Cache by saved
        # bytes, so existing project snapshots continue to refer to immutable files.
        saved_identity=copy.deepcopy(identity)
        saved_identity.pop("cache_path",None);saved_identity.pop("cache_sha256",None)
        try:
            tin.import_report=saved_identity
            save_terrain(tin,staging,cancelled=lambda:token.is_cancelled)
            digest=file_sha256(staging,cancelled=lambda:token.is_cancelled)
            token.raise_if_cancelled();cache=folder/(digest+".npz")
            if cache.exists():
                if file_sha256(cache,cancelled=lambda:token.is_cancelled)!=digest:
                    raise ValueError("地形缓存校验失败，请重新导入原始地形")
            else:
                # Windows rename fails if another worker already published the
                # same digest; never replace an existing historical cache.
                try:os.rename(staging,cache)
                except FileExistsError:
                    if file_sha256(cache,cancelled=lambda:token.is_cancelled)!=digest:raise
            identity.update(cache_path=str(cache),cache_sha256=digest)
            token.raise_if_cancelled();return tin
        finally:
            tin.import_report=identity
            if os.path.exists(staging):os.unlink(staging)

    def _refresh_assets(self):
        self._preparation_snapshot = None
        self._workspace_source = None
        from 土石方计算.io.network_exporter import SECTION_NAMES
        from 土石方计算.services.earthwork_scope import trenchless_exclusions,trenchless_method
        from 土石方计算.services.sluice_gate import gate_missing_fields, gate_reference_asset, gate_station_range, is_sluice_gate
        from 土石方计算.services.unburied_preview import is_unburied_pipe
        assets=self._all_assets();old=self.table.currentRow();self.table.blockSignals(True);self.table.setRowCount(len(assets))
        for i,(owner,asset) in enumerate(assets):
            typ="有压管道" if asset.get("kind") in ("pipe","pressure_pipe") else "倒虹吸" if asset.get("kind")=="siphon" else SECTION_NAMES.get(asset.get("section_type"),asset.get("section_type","矩形基坑"))
            start,end=asset.get("station_start"),asset.get("station_end")
            span=f"{start:.3f}～{end:.3f}" if start is not None and end is not None else (
                "局部切片" if asset.get("kind")=="pit" else "桩号待补")
            missing=self._remaining_missing(asset);status="已禁用，未计量" if not asset.get("enabled",True) else "首版暂不计量" if self._deferred_asset(asset) else "明/架空管，仅结构查看" if is_unburied_pipe(asset) and not asset.get("section_scheme_binding") else "需补齐" if missing else "已匹配断面" if asset.get("section_scheme_binding") else "可核对"
            if is_sluice_gate(asset):
                typ = "闸"
                start, end = gate_station_range(asset)
                if start is not None and end is not None:
                    span = f"{start:.3f}～{end:.3f}"
                elif asset.get("gate_station") is not None:
                    span = f"中心 {asset['gate_station']:.3f}"
                if asset.get("enabled", True):
                    reference = gate_reference_asset(self._inputs, owner, asset)
                    status = "需补齐" if gate_missing_fields(asset, reference) else "可算"
            if asset.get("enabled",True) and not self._deferred_asset(asset) and not is_unburied_pipe(asset) and asset.get("construction",{}).get("burial_mode")=="cover_depth" and not self._cover_confirmed(asset,owner,self._cover_request()):status="算量时自动生成管轴"
            method=trenchless_method(asset)
            if method:
                typ=method["method"]
                if asset.get("enabled",True):status="按非开挖圆孔单列"
            pending=asset.get("calculation_deferred") if asset.get("enabled",True) else None
            if pending:status="本次待核，未计量"
            values=(asset.get("name",asset.get("asset_id","")),typ,span,status)
            for j,value in enumerate(values):
                item=QTableWidgetItem(str(value));item.setFlags(item.flags()&~Qt.ItemIsEditable);item.setToolTip(str(value)+"\n"+str(asset.get("asset_id","")))
                if j==3 and pending:item.setToolTip(pending["reason"])
                if j==0:
                    item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if asset.get("enabled",True) else Qt.Unchecked)
                    if asset.get("generated_aqueduct_foundation"):
                        item.setFlags(item.flags()&~Qt.ItemIsUserCheckable)
                self.table.setItem(i,j,item)
        self.table.blockSignals(False)
        bores=trenchless_exclusions(self._inputs)
        bore_ids={x["asset_id"] for x in bores if x.get("asset_id")}
        excluded=[x for x in self._inputs.get("excluded",[]) if x.get("asset_id") not in bore_ids]
        excluded_ids={x.get("asset_id") for x in excluded}
        from 土石方计算.services.workbench_calculator import SUPPORTED
        for _,asset in assets:
            if (not asset.get("enabled",True) or self._deferred_asset(asset)
                    or asset.get("section_type") not in SUPPORTED and not is_sluice_gate(asset)) and asset.get("asset_id") not in excluded_ids|bore_ids:
                excluded.append({"asset_id":asset.get("asset_id"),"name":asset.get("name",asset.get("asset_id",""))})
                excluded_ids.add(asset.get("asset_id"))
        names="；".join(x.get("name",x.get("message",str(x))) for x in excluded[:6])
        if len(excluded)>6:names+=f"等{len(excluded)}项，详见工程量表"
        scope_lines=[]
        if excluded:scope_lines.append("未纳入："+names)
        if bores:
            bore_names="；".join(str(x.get("name") or x.get("construction_method") or "非开挖") for x in bores[:6])
            if len(bores)>6:bore_names+=f"等{len(bores)}项"
            scope_lines.append("非开挖圆孔单列："+bore_names)
        self.excluded_label.setText("\n".join(scope_lines))
        if assets or bores or excluded or self._inputs.get("transition_candidates"):
            self.input_label.setText(self._design_source_names(assets) or "已读入设计资料。")
        else:
            self.input_label.setText("尚未读取设计资料。")
        if assets:self.table.selectRow(max(0,min(old,len(assets)-1)))
        self._refresh_pipe_objects()
        self._refresh_gate_context()
        self._refresh_structure_filter()
        self._refresh_workflow()

    @staticmethod
    def _remaining_missing(asset):
        paths=asset.setdefault("source_missing_fields",list(asset.get("missing_fields",[])))
        missing=[]
        for path in set(paths+asset.get("missing_fields",[])):
            value=asset
            for key in path.split("."):
                value=value.get(key) if isinstance(value,dict) else None
            if value is None or isinstance(value,(list,dict)) and not value:missing.append(path)
        asset["missing_fields"]=sorted(missing);return missing

    def _refresh_source_diagnostics(self, inputs=None):
        inputs = self._inputs if inputs is None else inputs
        assets = [a for n in inputs.get("networks", []) for a in n.get("assets", [])] + list(inputs.get("pits", []))
        for asset in assets:self._remaining_missing(asset)
        for network in inputs.get("networks",[]):
            network.setdefault("source_missing_fields",list(network.get("missing_fields",[])))
            missing={field for asset in network.get("assets",[]) for field in asset.get("missing_fields",[])}
            if network.get("alignment") is None:missing.add("alignment")
            network["missing_fields"]=sorted(missing)
        for issue in inputs.get("diagnostics",[]):
            identifier=issue.get("asset_id")
            family=[a for a in assets if identifier and identifier in (a.get("asset_id"),a.get("parent_asset_id"))]
            field=issue.get("field")
            if field and family and all(field not in a.get("missing_fields",[]) for a in family):
                issue.setdefault("original_message",issue.get("message"));issue.setdefault("original_severity",issue.get("severity","error"));issue["resolved"]=True
                issue["severity"]="info";issue["message"]="已补齐："+issue["original_message"]
            elif field and family and issue.get("resolved"):
                issue["resolved"]=False;issue["severity"]=issue.get("original_severity","error")
                issue["message"]=issue.get("original_message",issue.get("message"))

    def edit_parameters(self,*,template=False):
        targets=self._all_assets()
        network,asset=self.selected_asset()
        if asset.get("generated_aqueduct_foundation"):
            parent=asset.get("parent_original_asset_id",asset.get("parent_asset_id"))
            for row,(owner,item) in enumerate(self._all_assets()):
                if owner is not None and item.get("asset_id")==parent:
                    self.table.selectRow(row)
                    self._log("该基础由渡槽附属构件生成；已打开所属渡槽参数。")
                    return self.edit_parameters(template=template)
            raise ValueError("基础所属渡槽来源缺失，请重新读取水面线成果")
        if self._deferred_asset(asset):raise ValueError("首版暂不计闸基/独立基坑；原始资料和历史断面保留")
        dialog=AssetParameterDialog(asset,self,template=template)
        if dialog.exec()!=QDialog.Accepted:return
        candidate=dialog.asset;scope=dialog.scope_value;selected_id=asset["asset_id"]
        for path,change in getattr(dialog,"changed_fields",{}).items():
            candidate.setdefault("parameter_sources",{})[path]="用户覆盖：施工参数编辑"
            candidate.setdefault("drawing_user_overrides",{})[path]=copy.deepcopy(change["after"])
        selected_target=(candidate.get("construction") or {}).get("target_mode")
        if scope=="all" and selected_target=="cover_depth":
            try:
                final_cover=float(candidate["construction"]["final_cover_depth"])
                if not math.isfinite(final_cover) or final_cover<0:raise ValueError
            except (KeyError,TypeError,ValueError):
                raise ValueError(f"{asset.get('name',selected_id)}（{selected_id}，{asset.get('station_start')}～{asset.get('station_end')}m）：完成面覆土厚度需填写有限的非负值")
        if scope=="asset":
            start,end=dialog.override_range or (None,None)
            if network is not None and (start!=asset.get("station_start") or end!=asset.get("station_end")):
                if start<asset["station_start"] or end>asset["station_end"]:raise ValueError("覆盖区间必须位于所选区段内")
                rows=network["assets"];index=rows.index(asset);parts=[]
                for left,right,edited in ((asset["station_start"],start,False),(start,end,True),(end,asset["station_end"],False)):
                    if right<=left:continue
                    part=copy.deepcopy(candidate if edited else asset);part.update(station_start=left,station_end=right)
                    part["asset_id"]=asset["asset_id"]+f"-{left:.3f}-{right:.3f}";part["parent_asset_id"]=asset["asset_id"];parts.append(part)
                    if edited:selected_id=part["asset_id"]
                rows[index:index+1]=parts
            else:asset.clear();asset.update(candidate)
        else:
            # Validate every recipient before changing any asset. A recipient's
            # existing staged slope must never be silently discarded by a template.
            for _,item in targets:
                if "station_start" not in item or self._deferred_asset(item) or item.get("generated_aqueduct_foundation"):continue
                if scope=="type" and self._structure_key(item)!=self._structure_key(asset):continue
                construction=copied_construction(candidate,item,scope)
                proposed=dict(item.get("construction",{}));proposed.update(construction)
                if proposed.get("excavation_layer_mode")=="surface_thickness" and any(proposed.get("excavation_stages_"+side) for side in ("left","right")):
                    raise ValueError(str(item.get("name") or item.get("asset_id"))+"已有开挖分级/马道；请先清空该区段分级，或缩小简化分层参数的应用范围。原参数未修改。")
            for _,item in targets:
                if "station_start" not in item or self._deferred_asset(item) or item.get("generated_aqueduct_foundation"):continue
                if scope=="type" and self._structure_key(item)!=self._structure_key(asset):continue
                construction=copied_construction(candidate,item,scope)
                item.setdefault("construction",{}).update(construction)
                if scope=="all":
                    if item is asset and selected_target is not None:
                        item["construction"]["target_mode"]=selected_target
                        if selected_target=="cover_depth":item["construction"]["final_cover_depth"]=final_cover
                    elif item["construction"].get("target_mode") is None:
                        stype=item.get("section_type","")
                        if item.get("kind")=="open_channel" or stype in {"trapezoidal_channel","rectangular_channel","u_channel"}:
                            item["construction"]["target_mode"]="union_terrain"
                        elif item.get("kind") in {"culvert","pipe","pressure_pipe","siphon"} or stype in {"rectangular_culvert","arch_culvert","circular_culvert","circular_siphon","circular_channel"}:
                            item["construction"]["target_mode"]="restore_terrain"
                keys=("wall_thickness_left","wall_thickness_right","wall_thickness","base_thickness","roof_thickness")
                if scope=="type":keys+=("inner_chamfers","material_grade","material_specs","component_specs")
                if item.get("kind")==candidate.get("kind")=="tunnel":
                    keys+=("lining_thickness","shotcrete_thickness","shotcrete_grade")
                # Absolute stations and member elevations belong only to the
                # edited object, even when common construction is copied.
                if item is asset:
                    keys+=("discrete_components","quantity_rules","quantity_scope_not_applicable")
                    for key in ("overbreak_material","overbreak_grade"):
                        if key in candidate.get("construction",{}):
                            item["construction"][key]=copy.deepcopy(candidate["construction"][key])
                for key in keys:
                    if key in candidate.get("section",{}):
                        item.setdefault("section",{})[key]=copy.deepcopy(candidate["section"][key])
                        path="section."+key
                        item.setdefault("parameter_sources",{})[path]="用户覆盖：批量施工参数设置"
                        item.setdefault("drawing_user_overrides",{})[path]=copy.deepcopy(candidate["section"][key])
                for key,value in construction.items():
                    path="construction."+key
                    item.setdefault("parameter_sources",{})[path]="用户覆盖：批量施工参数设置"
                    item.setdefault("drawing_user_overrides",{})[path]=copy.deepcopy(value)
                if item.get("kind")==candidate.get("kind")=="tunnel":
                    rock=candidate.get("section",{}).get("rock_class")
                    option=(candidate.get("source_tunnel_lining_options") or {}).get(rock)
                    own_option=(item.get("source_tunnel_lining_options") or {}).get(rock)
                    if (candidate.get("tunnel_lining_selection_mode")=="source_library"
                            and option and own_option==option):
                        from 土石方计算.services.tunnel_source_parameters import apply_tunnel_lining_option
                        apply_tunnel_lining_option(item,rock)
                    else:
                        item.setdefault("section",{}).pop("rock_class",None)
                        item["tunnel_lining_selection_mode"]="manual"
                        item["source_tunnel_lining_selection_required"]=False
                    for field in ("missing_fields","source_missing_fields"):
                        if field in item:item[field]=[path for path in item[field] if path!="section.rock_class"]
                item.update(workbench_geometry=True,parameter_source="user_confirmed")
        from 土石方计算.services.construction_rules import normalize_construction_inputs
        normalize_construction_inputs(self._inputs)
        self._refresh_source_diagnostics();self._invalidate();self._refresh_assets();self._rebase_auxiliary_draft();self._log("施工参数已保存；原净空尺寸和原始设计成果保留。")
        for row,(owner,item) in enumerate(self._all_assets()):
            if item["asset_id"]==selected_id and owner is network:self.table.selectRow(row);break
        if network is None:self.station_spin.setValue(0.)
        selected_network,selected=self.selected_asset()
        from 土石方计算.services.unburied_preview import is_unburied_pipe
        if (is_unburied_pipe(selected) or selected.get("construction",{}).get("burial_mode")!="cover_depth") and self.section_views.currentWidget() is not self.pipe_page:self.preview_selected()

    def _terrain_request(self):
        options=copy.deepcopy(self._terrain_options)
        corridor=(self._terrain_identity.get("terrain_options") or {}).get("route_corridor")
        if corridor is not None:options["route_corridor"]=copy.deepcopy(corridor)
        request={"tin":self._tin,"path":self.terrain_path.text(),"mode":self._terrain_processing_mode,
                 "options":options,"identity":copy.deepcopy(self._terrain_identity),
                 "terrain_progress":self._task_progress_event.emit}
        if corridor is not None:
            # Capture route references, not the full object/section inputs.
            request["scope_networks"]=[{"alignment":network.get("alignment"),"test_only":network.get("test_only")}
                                       for network in self._inputs.get("networks",[])]
        return request

    @staticmethod
    def _refresh_scoped_terrain(token,request,scope):
        from 土石方计算.io.independent_terrain import file_sha256,load_terrain
        from 土石方计算.io.terrain_corridor import route_corridor_for_networks,terrain_corridor_covers

        required=route_corridor_for_networks(request.get("scope_networks",[]),scope)
        if terrain_corridor_covers(scope,required):return None
        identity=request["identity"]
        origin=identity.get("original_source") or {"path":identity.get("path"),"source_sha256":identity.get("source_sha256")}
        paths=[Path(value) for value in dict.fromkeys((origin.get("path"),request.get("path"),identity.get("path"))) if value]
        available=[path for path in paths if path.suffix.lower() in (".dwg",".dxf") and path.is_file()]
        prefix="当前工程路线超出已保存的计算地形范围。"
        if not available:
            raise TerrainUnavailable(prefix+"原始地形图不可用，请重新导入覆盖当前路线的地形。")
        expected=origin.get("source_sha256")
        source=next((path for path in available if expected and
                     file_sha256(path,cancelled=lambda:token.is_cancelled)==expected),None)
        if source is None:
            raise TerrainSourceChanged(prefix+"原始地形图未通过来源校验，请重新导入。")
        emit=request.get("terrain_progress")
        if emit:emit(token.generation,"terrain",0.,"工程路线已超出原计算走廊，正在按当前路线重新读取原图。")
        options=request["options"]
        mode=request["mode"] if request["mode"] in ("points","combined") else identity.get("terrain_mode","combined")
        import_options={**(identity.get("terrain_options") or {}),**options,"route_corridor":required}
        tin=load_terrain(source,terrain_mode=mode,terrain_options=import_options,cancelled=lambda:token.is_cancelled,
            progress=(lambda *args:emit(token.generation,*args)) if emit else None)
        if tin.import_report.get("source_sha256")!=expected:
            raise TerrainSourceChanged(prefix+"重新读取期间原始地形图已改变，请重新导入。")
        options["route_corridor"]=required
        return SectionWorkbenchPanel._cache_tin(tin,token,options)

    @staticmethod
    def _ensure_tin(token,request):
        from 土石方计算.io.independent_terrain import load_terrain,file_sha256
        identity = request["identity"]
        source = request["path"]
        cache = identity.get("cache_path")
        expected_cache = identity.get("cache_sha256")
        expected_mesh = identity.get("terrain_sha256")
        expected_source = identity.get("source_sha256")
        if not source and not (cache and expected_cache):
            raise TerrainUnavailable("尚未导入计算地形。")
        scope=(identity.get("terrain_options") or {}).get("route_corridor") if identity.get("corridor_preparation") else None
        if scope is not None:
            refreshed=SectionWorkbenchPanel._refresh_scoped_terrain(token,request,scope)
            if refreshed is not None:return refreshed
        source_exists = bool(source and Path(source).is_file())
        cancelled = lambda: token.is_cancelled
        if source_exists and expected_source and file_sha256(source, cancelled=cancelled) != expected_source:
            raise TerrainSourceChanged("源地形文件已改变，请重新导入")
        tin = request["tin"]
        emit = request.get("terrain_progress")
        progress = (lambda *args: emit(token.generation, *args)) if emit else None

        def load_bound_cache():
            if expected_cache and file_sha256(cache, cancelled=cancelled) != expected_cache:
                raise TerrainSourceChanged("保存地形缓存已改变，请重新导入")
            cached = load_terrain(cache, cancelled=cancelled)
            if expected_cache and cached.import_report.get("source_sha256") != expected_cache:
                raise TerrainSourceChanged("读取期间保存地形缓存已改变，请重新导入")
            if expected_mesh and cached.import_report.get("terrain_sha256") != expected_mesh:
                raise TerrainSourceChanged("保存的地形网格与工程记录不一致，请重新导入")
            return cached

        if not source_exists:
            if not cache or not expected_cache or not Path(cache).is_file():
                raise TerrainUnavailable("原地形文件及可核对缓存不可用，请重新导入地形。")
            tin = load_bound_cache()
            original = (identity.get("original_source") or tin.import_report.get("original_source")
                        or {"path": source, "source_sha256": expected_source})
            tin.import_report.update(cache_path=cache, cache_sha256=expected_cache, original_source=original)
        elif tin is None and cache:
            try:
                tin = load_bound_cache()
            except (FileNotFoundError, PermissionError, TerrainSourceChanged) as error:
                if not expected_source or not expected_mesh:
                    raise TerrainSourceChanged("地形缓存无法核对，缺少原地形或网格校验记录，请重新导入地形。") from error
                if progress:
                    progress("terrain", 0., "正在用原地形重建缓存并核对计算网格。")
                options = {**(identity.get("terrain_options") or request["options"]), "export_clean_terrain": False}
                mode = identity.get("terrain_mode")
                rebuilt = load_terrain(source, mesh_index=identity.get("mesh_index"),
                    terrain_mode=mode if mode in ("points", "combined") else "combined",
                    terrain_options=options, cancelled=cancelled, progress=progress)
                expected_snapshot = identity.get("source_snapshot_sha256")
                if (rebuilt.import_report.get("source_sha256") != expected_source
                        or rebuilt.import_report.get("terrain_sha256") != expected_mesh
                        or (expected_snapshot and rebuilt.import_report.get("source_snapshot_sha256") != expected_snapshot)):
                    raise TerrainSourceChanged("重建网格与工程记录不一致，请重新导入地形并复核。") from error
                # Publishing under new immutable cache bytes keeps the damaged
                # resource available for diagnostics and other project snapshots.
                rebuilt.import_report = {**rebuilt.import_report, **identity,
                    "rebuilt_from_cache_sha256": expected_cache}
                tin = SectionWorkbenchPanel._cache_tin(rebuilt, token, options)
            else:
                tin.import_report = identity
        if tin is None:
            tin=load_terrain(source,terrain_mode=request["mode"] if request["mode"] in ("points","combined") else "combined",
                terrain_options=request["options"],cancelled=cancelled,progress=progress)
        actual=getattr(tin,"import_report",{}).get("terrain_mode")
        if request["mode"] in ("points","combined") and actual!=request["mode"]:
            from 土石方计算.io.independent_terrain import rebuild_terrain_mode
            tin=rebuild_terrain_mode(tin,request["mode"],terrain_options=request["options"],cancelled=lambda:token.is_cancelled)
            tin=SectionWorkbenchPanel._cache_tin(tin,token,request["options"])
        return tin

    def _cover_request(self):
        request=self._terrain_request();request["cover_sample_step"]=min(self.step.value(),10.)
        return request

    @staticmethod
    def _cover_hash(value):
        from 土石方计算.services.batch_cover_profiles import cover_hash
        return cover_hash(value)

    @staticmethod
    def _cover_parameters(network,asset,sample_step):
        from 土石方计算.services.batch_cover_profiles import cover_parameters
        return cover_parameters(network,asset,sample_step)

    @staticmethod
    def _cover_terrain(request,tin=None):
        from 土石方计算.services.batch_cover_profiles import cover_terrain
        return cover_terrain(request,tin)

    @classmethod
    def _cover_input_hash(cls,network,asset,request,tin=None):
        from 土石方计算.services.batch_cover_profiles import cover_input_hash
        return cover_input_hash(network,asset,request,tin)

    @classmethod
    def _cover_profile_hash(cls,asset):
        from 土石方计算.services.batch_cover_profiles import cover_profile_hash
        return cover_profile_hash(asset)

    @classmethod
    def _cover_confirmed(cls,asset,network,request,tin=None):
        from 土石方计算.services.batch_cover_profiles import cover_confirmed
        return cover_confirmed(asset,network,request,tin)

    @classmethod
    def _validate_cover_confirmations(cls,inputs,request,tin=None,*,allow_partial=False):
        from 土石方计算.services.pipe_axis_continuity import (
            inspect_pipe_axis_continuity,PipeAxisContinuityError,is_in_calculation_scope,
            partial_axis_deferral_diagnostics,
        )
        report=inspect_pipe_axis_continuity(inputs)
        can_defer=allow_partial and bool(partial_axis_deferral_diagnostics(inputs,report))
        if not can_defer and any(d["code"] in {"pipe_axis_transition_undefined","profile_jump"} or d["code"].startswith("unsupported_") for d in report["diagnostics"]):raise PipeAxisContinuityError(report)
        for network in inputs.get("networks",[]):
            for asset in network.get("assets",[]):
                if not is_in_calculation_scope(asset):continue
                if asset.get("construction",{}).get("burial_mode")=="cover_depth" and not cls._cover_confirmed(asset,network,request,tin):
                    raise ValueError("管顶埋深生成输入或地形已改变，需重新生成并确认预览轴线："+asset.get("name",asset.get("asset_id",""))+f" K{asset['station_start']:.3f}～{asset['station_end']:.3f}")
        if not report["valid"] and not can_defer:raise PipeAxisContinuityError(report)

    def generate_cover(self, *, candidate=None, source_inputs=None, source_key=None, candidates=None, on_applied=None):
        from .pipe_profile_mapping import profile_key
        from 土石方计算.services.batch_cover_profiles import is_pressure_cover_asset
        if source_inputs is None:
            network, asset = self.selected_asset()
            selected = [(network, asset, candidate)]
        else:
            candidates = candidates or {source_key: candidate}
            selected = [(n, a, candidates[key]) for n in source_inputs.get("networks", ())
                        for a in n.get("assets", ()) if (key := profile_key(n, a)) in candidates]
            if len(selected) != len(candidates):
                raise ValueError("请重新选择要预览的管线。")
        if any(n is None or not (is_pressure_cover_asset(a) or a.get("section_type") in
                   ("circular_culvert", "circular_channel")) for n, a, _ in selected):
            raise ValueError("请选择要生成覆土纵断面的管线。")
        from 土石方计算.services.batch_cover_profiles import generate_workbench_cover_preview,bind_cover_generation_metadata
        request = self._cover_request()
        sample_step = request["cover_sample_step"]
        jobs = []
        for owner, asset, proposed in selected:
            frozen = copy.deepcopy(proposed if proposed is not None else asset)
            jobs.append((copy.deepcopy(owner), frozen, self._cover_parameters(owner, frozen, sample_step)))
            if proposed is None:
                asset["cover_preview_confirmed"] = self._cover_confirmed(asset, owner, request)
        start = min(asset["station_start"] for _, asset, _ in selected)
        end = max(asset["station_end"] for _, asset, _ in selected)
        bores = list(self._cover_bores(source_inputs, selected, start, end)) if len(selected) > 1 else []
        project_id=self.project_id;revision=self._input_revision
        target_keys = [profile_key(n, a) for n, a, _ in selected]
        input_keys = [self._cover_hash(parameters[-1]) for _, _, parameters in jobs]
        terrain_key=self._cover_hash({"path":request["path"],"mode":request["mode"],"options":request["options"],"identity":request["identity"]})
        def current_matches(actual_tin=None):
            try:
                current = selected if source_inputs is not None else [(*self.selected_asset(), candidate)]
                now=self._cover_request()
                terrain_matches=self._cover_hash({"path":now["path"],"mode":now["mode"],"options":now["options"],"identity":now["identity"]})==terrain_key
                if not terrain_matches and actual_tin is not None:
                    # The independent map runner can finish the very same
                    # requested mode rebuild while this preview is running.
                    # Accept only its identical, already verified cache bytes.
                    actual_report=getattr(now.get("tin"),"import_report",{})
                    consistent=actual_report.get("cache_sha256")==now["identity"].get("cache_sha256")
                    base_keys=("path","mode","options")
                    terrain_matches=(consistent and all(now[k]==request[k] for k in base_keys)
                                     and (not request["identity"].get("source_sha256") or now["identity"].get("source_sha256")==request["identity"].get("source_sha256"))
                                     and self._cover_terrain(now)==self._cover_terrain(now,actual_tin))
                return (self.project_id==project_id and self._input_revision==revision
                        and [profile_key(n, a) for n, a, _ in current] == target_keys
                        and [self._cover_hash(self._cover_parameters(n, a if proposed is None else proposed, sample_step)[-1])
                             for n, a, proposed in current] == input_keys
                        and terrain_matches
                        and now["cover_sample_step"]==sample_step)
            except (ValueError,TypeError,KeyError):return False
        def work(token):
            from .pipe_design_preview import sample_ground
            from 土石方计算.adapters.workbench_sources import trenchless_plan_alignment
            from 土石方计算.services.pipe_axis_continuity import assess_cover_preview

            tin=self._ensure_tin(token,request)
            if not getattr(tin,"import_report",{}).get("cache_sha256"):tin=self._cache_tin(tin,token,request["options"])
            previews = []
            ground_alignments = []
            for owner, frozen, parameters in jobs:
                alignment, pipes, spacing, depth, segments, _, _ = parameters
                ground_alignments.append(alignment)
                preview = generate_workbench_cover_preview(tin, alignment, pipes, cover_depth=depth,
                    cover_segments=segments, spacing=spacing, sample_step=sample_step, cancelled=lambda: token.is_cancelled)
                previews.append(assess_cover_preview(owner, frozen, preview))
            for bore, _ in bores:
                if (alignment := trenchless_plan_alignment(bore)) is not None:
                    ground_alignments.append(alignment)
            stations = [point["station"] for preview in previews for point in preview.get("samples", ())]
            ground = sample_ground(tin, tuple(ground_alignments), (start, end), token, extra_stations=stations)
            return tin, previews, ground
        def done(value):
            tin, previews, ground = value
            if not current_matches(tin):self._log("生成预览期间工程、区段或地形输入已改变；旧轴线保留，未应用迟到预览。");return
            from .pipe_preview_chart import PipePreviewChart
            from 土石方计算.services.pipe_axis_continuity import cover_preview_series

            dialog=QDialog(self);dialog.setWindowTitle("管顶埋深生成预览");dialog.resize(850,540);ly=QVBoxLayout(dialog)
            series = [cover_preview_series(preview, index, "axis_elevation")
                      for preview in previews for index in range(len(preview["pipes"]))]
            series.extend(self._cover_bore_series(bores))
            chart = PipePreviewChart(dialog)
            chart.set_data(series, ground=ground, reference_label="管道中心轴线", station_bounds=(start, end))
            ly.addWidget(chart, 1)
            summary = []
            steps = sorted({step for preview in previews
                            if (step := (preview.get("cover_generation_options") or {}).get("control_step_m")) is not None})
            if steps:
                summary.append("管轴控制点间距 " + "、".join(f"{step:g} m" for step in steps))
            minimums = [preview.get("minimum_checked_cover") for preview in previews]
            minimums = [value if value is not None else
                        (preview.get("actual_cover_summary") or {}).get("minimum_sampled_actual_cover_m")
                        for preview, value in zip(previews, minimums, strict=True)]
            if any(value is not None for value in minimums):
                label = "明挖段最小覆土" if len(selected) > 1 else "最小覆土"
                summary.append(f"{label} {min(value for value in minimums if value is not None):.2f} m")
            if summary:
                note = QLabel("　·　".join(summary))
                note.setWordWrap(True)
                ly.addWidget(note)
            diagnostics = [issue for preview in previews for issue in preview.get("diagnostics", [])
                           if issue.get("severity") != "info"]
            for issue in diagnostics[:8]:
                label=QLabel(issue.get("message",str(issue)));label.setWordWrap(True);ly.addWidget(label)
            if len(diagnostics)>8:ly.addWidget(QLabel(f"另有 {len(diagnostics)-8} 项待核对"))
            buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
            buttons.button(QDialogButtonBox.Ok).setText("采用轴线")
            buttons.button(QDialogButtonBox.Cancel).setText("取消")
            buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);ly.addWidget(buttons)
            if any(p.get("valid") is False for p in previews) or any(x.get("severity") == "error" for x in diagnostics):
                buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            if dialog.exec()==QDialog.Accepted:
                if not current_matches(tin):self._log("确认时工程或生成输入已改变；未应用旧预览，请重新生成。");return
                from 土石方计算.services.pipe_axis_continuity import apply_checked_cover_preview,PipeAxisContinuityError
                current = selected if source_inputs is not None else [(*self.selected_asset(), candidate)]
                try:
                    updated_assets = [apply_checked_cover_preview(owner, frozen if proposed is not None else item,
                                                                 preview, confirmed=True)
                                      for (owner, item, proposed), (_, frozen, _), preview in
                                      zip(current, jobs, previews, strict=True)]
                except PipeAxisContinuityError as exc:self._log(str(exc));return
                self._accept_tin(tin)
                for (owner, _, _), (_, _, parameters), preview, updated in zip(current, jobs, previews, updated_assets, strict=True):
                    updated.update(cover_pipe_layout_mode=parameters[-2], cover_preview_confirmed=True,
                                   workbench_geometry=True, pipe_profile_choice="cover_depth")
                    bind_cover_generation_metadata(updated,preview)
                    updated["cover_confirmation"]={"schema_version":"1.0","input_sha256":self._cover_input_hash(owner,updated,self._cover_request()),"profile_sha256":self._cover_profile_hash(updated)}
                for (_, item, _), updated in zip(current, updated_assets, strict=True):
                    item.clear()
                    item.update(updated)
                if source_inputs is not None:self._inputs=source_inputs
                if on_applied is not None:on_applied()
                self._refresh_source_diagnostics();self._refresh_assets();self._invalidate();self._rebase_auxiliary_draft()
                self._log("已采用按管顶覆土生成的轴线。")
        self._submit_task(work,title="覆土纵断面预览",message="正在沿管线读取地形并生成轴线。",on_success=done,on_error=self._failed)

    @staticmethod
    def _cover_bores(inputs, selected, start, end):
        from 土石方计算.services.earthwork_scope import trenchless_exclusions, trenchless_intersections

        for bore in trenchless_exclusions(inputs):
            intervals = {bounds for owner, _, _ in selected
                         for bounds in trenchless_intersections([bore], owner, start, end)}
            if intervals:
                yield bore, sorted(intervals)

    @staticmethod
    def _cover_bore_series(bores):
        from 土石方计算.services.design_profiles import evaluate_profile, normalize_design_profile, profile_break_stations

        for bore, intervals in bores:
            raw = bore.get("trenchless_route_profile")
            if raw is None:
                continue
            try:
                profile = normalize_design_profile(raw)
            except (ValueError, TypeError, KeyError):
                continue
            knots = profile_break_stations(profile)
            for left, right in intervals:
                left = max(left, profile["station_start"])
                right = min(right, profile["station_end"])
                if right > left:
                    stations = np.unique([*np.linspace(left, right, 100), *(s for s in knots if left < s < right)])
                    yield stations, [evaluate_profile(profile, station)[0] for station in stations]

    def import_profile(self):
        import os
        from .profile_file import DXF_PROFILE_FILTER, read_profile_file
        from 土石方计算.services.siphon_axis_choices import is_siphon_axis_asset

        network,asset=self.selected_asset()
        if network is None:raise ValueError("独立基坑请直接编辑坑底高程")
        dxf_only=is_siphon_axis_asset(asset)
        from 土石方计算.services.design_profiles import normalize_design_profile,profile_break_stations,evaluate_profile,clip_design_profile
        dialog=QDialog(self);dialog.setWindowTitle("补充或调整真实纵断面");dialog.resize(600,480);layout=QVBoxLayout(dialog)
        heading=QLabel("控制表以米显示。明渠、圆涵填净内底；管道可选首管轴或共同外管底。局部零起桩轴线按所选区段长度自动对齐。")
        heading.setWordWrap(True);layout.addWidget(heading)
        table=QTableWidget(0,2);table.setHorizontalHeaderLabels(["桩号 m","高程 m"]);layout.addWidget(table)
        add=QPushButton("增加控制点");add.clicked.connect(lambda:table.insertRow(table.rowCount()));layout.addWidget(add)
        load=QPushButton("导入 DXF" if dxf_only else "导入纵断面（CSV / DXF / JSON）");layout.addWidget(load)
        load.setObjectName("profileImportFile")
        is_pipe=asset.get("kind") in ("pipe","pressure_pipe","siphon") or asset.get("section_type","").startswith("circular")
        from 土石方计算.services.batch_cover_profiles import is_pressure_cover_asset
        route_pipe=is_pressure_cover_asset(asset)
        is_round_culvert=asset.get("section_type") in ("circular_culvert","circular_channel")
        reference=QComboBox()
        if is_pipe:
            reference.addItem("首根管轴高程","pipe_axis");reference.addItem("共同外管底高程","common_outer_bottom")
            if is_round_culvert:reference.addItem("圆涵净内底高程（内衬后的净空）","inner_invert")
        else:reference.addItem("内底高程","inner_invert")
        current=asset.get("design_profile") or {}
        if is_pipe and not is_round_culvert and current.get("reference")=="inner_invert":reference.addItem("管内底高程（保留来源，需核对）","inner_invert")
        if current.get("reference") and reference.findData(current["reference"])<0:
            reference.addItem("来源高程基准未识别（需核对）",current["reference"])
        reference.setCurrentIndex(max(0,reference.findData(current.get("reference") or ("pipe_axis" if is_pipe else "inner_invert"))));layout.addWidget(reference)
        unit_row=QHBoxLayout();unit_row.addWidget(QLabel("导入坐标单位"))
        source_units=QComboBox();source_units.setObjectName("profileImportUnits")
        for label,value in (("米 (m)","m"),("毫米 (mm)","mm"),("厘米 (cm)","cm"),("英寸 (in)","in"),("英尺 (ft)","ft")):
            source_units.addItem(label,value)
        unit_row.addWidget(source_units);unit_row.addStretch();layout.addLayout(unit_row)
        origin_row=QHBoxLayout();origin_row.addWidget(QLabel("源线起点对应桩号"))
        source_origin=QDoubleSpinBox();source_origin.setObjectName("profileImportStationOrigin")
        source_origin.setDecimals(6);source_origin.setRange(-1e8,1e8);source_origin.setSuffix(" m")
        source_origin.setKeyboardTracking(False)
        source_origin.setValue(float(asset["station_start"]));origin_row.addWidget(source_origin)
        alignment_choice=QComboBox();alignment_choice.setObjectName("profileImportAlignment")
        for label,mode in (("按源桩号或等长匹配","auto"),("对齐当前对象起桩","align_start"),("对齐当前对象终桩","align_end")):
            alignment_choice.addItem(label,mode)
        origin_row.addWidget(alignment_choice);origin_row.addStretch();layout.addLayout(origin_row)
        scope_row=QHBoxLayout();scope_label=QLabel("应用范围");scope_row.addWidget(scope_label)
        application_scope=QComboBox();application_scope.setObjectName("profileImportScope")
        application_scope.addItem("当前对象","current");application_scope.addItem("纵线覆盖的同线管段","covered_route")
        application_scope.setEnabled(False);scope_row.addWidget(application_scope);scope_row.addStretch()
        scope_label.setVisible(route_pipe);application_scope.setVisible(route_pipe);layout.addLayout(scope_row)
        import_status=QLabel();import_status.setObjectName("profileImportStatus");import_status.setWordWrap(True);layout.addWidget(import_status)
        replace_arc=QCheckBox("明确采用折线控制高程，替换当前真实圆弧")
        replace_arc.setToolTip("不勾选时，未修改的真实圆弧按原形保存；修改弧上控制值须补充真实新弧线，或明确选择折线。")
        replace_arc.setVisible(False);layout.addWidget(replace_arc)
        draft={"profile":None,"rows":[],"source":None,"accepted":None,"imported_profile":None,
               "group_candidate":None,"group_report":None,"origin_override":None,"import_path":None,
               "mapped_mode":None}
        def populate(profile,source=None):
            rows=[{"station":s,"elevation":evaluate_profile(profile,s)[0]} for s in profile_break_stations(profile)]
            table.blockSignals(True);table.setRowCount(len(rows))
            for i,row in enumerate(rows):
                for j,key in enumerate(("station","elevation")):table.setItem(i,j,QTableWidgetItem(str(row[key])))
            table.blockSignals(False)
            draft.update(profile=profile,rows=rows,source=source,accepted=None,group_candidate=None)
            replace_arc.setChecked(False);replace_arc.setVisible(any(e["kind"]=="arc" for e in profile["elements"]))
        if current:
            populate(normalize_design_profile(current))
        elif asset.get("profile_points"):
            populate(normalize_design_profile(asset["profile_points"],reference=reference.currentData()))
        def table_rows():
            rows=[]
            for i in range(table.rowCount()):
                row={}
                for j,key in enumerate(("station","elevation")):
                    item=table.item(i,j);text=item.text().strip() if item else ""
                    try:value=float(text)
                    except ValueError as exc:raise ValueError(f"控制高程第{i+1}行的{'桩号' if j==0 else '高程'}为空或无效") from exc
                    if not math.isfinite(value):raise ValueError(f"控制高程第{i+1}行必须为有限数值")
                    row[key]=value
                rows.append(row)
            return rows
        def import_file(path):
            from 土石方计算.services.imported_design_profiles import prepare_imported_profile,bind_imported_route_profile
            profile,source,imported_reference=read_profile_file(path,
                reference=reference.currentData(),units=source_units.currentData(),dxf_only=dxf_only)
            draft["import_path"]=path
            declared_units=source["declared_dxf_units"]
            full_profile=copy.deepcopy(profile)
            factor={"m":1.,"mm":.001,"cm":.01,"in":.0254,"ft":.3048}[source_units.currentData()]
            source_start=full_profile["station_start"]*factor
            mapping_override=None
            mapping_mode=alignment_choice.currentData()
            mapping_offset=None
            if mapping_mode=="align_start":
                mapping_offset=float(asset["station_start"])-source_start
            elif mapping_mode=="align_end":
                mapping_offset=float(asset["station_end"])-full_profile["station_end"]*factor
            elif draft["origin_override"] is not None:
                mapping_offset=draft["origin_override"]-source_start
            if mapping_offset is not None:
                mapping_override={"station_offset_m":mapping_offset,"source_units":source_units.currentData(),
                                  "mapping_basis":alignment_choice.currentText() if mapping_mode!="auto" else "源线起点对应指定桩号"}
            group_report=None
            if route_pipe:
                def route_preview(mapping):
                    return bind_imported_route_profile(self._inputs,network,asset,full_profile,source=source,
                        mapping=mapping,source_units=source_units.currentData(),scope="covered_route")
                try:preview,group_report=route_preview(mapping_override)
                except ValueError:
                    if mapping_override is not None or abs(source_start)>.001:raise
                    mapping_override={"station_offset_m":float(asset["station_start"])-source_start,
                        "source_units":source_units.currentData(),"mapping_basis":"局部零起桩对应所选对象起桩"}
                    preview,group_report=route_preview(mapping_override)
                profile=next(a["design_profile"] for n in preview["networks"] for a in n.get("assets",[])
                             if a["asset_id"]==asset["asset_id"])
                mapping=group_report["mapping"]
            else:
                offset=mapping_override["station_offset_m"] if mapping_override else None
                try:profile,mapping=prepare_imported_profile(profile,asset,inputs={"networks":[network]},source_units=source_units.currentData(),station_offset=offset)
                except ValueError:
                    if offset is not None or abs(source_start)>.001:raise
                    profile,mapping=prepare_imported_profile(full_profile,asset,source_units=source_units.currentData(),
                        station_offset=float(asset["station_start"])-source_start)
            if imported_reference:
                index=reference.findData(imported_reference)
                if index<0:reference.addItem("来源高程基准未识别（需核对）",imported_reference);index=reference.count()-1
                reference.setCurrentIndex(index)
            source["station_mapping"]=mapping
            source["source_origin_m"]=source_start+mapping.get("station_offset_m",0.)
            source_origin.blockSignals(True);source_origin.setValue(source["source_origin_m"]);source_origin.blockSignals(False)
            populate(profile,source)
            draft.update(imported_profile=full_profile,group_report=group_report,mapped_mode=mapping_mode)
            count=len((group_report or {}).get("assets",[]));bores=len((group_report or {}).get("trenchless",[]))
            group_available=route_pipe and (count>1 or bores>0)
            application_scope.setEnabled(group_available)
            application_scope.setItemText(1,f"纵线覆盖的同线管段（{count}段）" if group_available else "纵线覆盖的同线管段")
            application_scope.setCurrentIndex(1 if group_available else 0)
            declared={0:"未指定",1:"英寸",2:"英尺",4:"毫米",5:"厘米",6:"米"}.get(declared_units,str(declared_units))
            prefix=f"图纸单位标注：{declared}；" if declared_units is not None else ""
            offset=mapping.get("station_offset_m",0.)
            mapped=f"；局部桩号已平移 {offset:g}m" if offset else ""
            coverage=f"；含{bores}个非开挖段" if bores else ""
            import_status.setText(prefix+f"本次坐标按{source_units.currentText()}读取{mapped}{coverage}。")
            self._log("轴线已读取到编辑草稿。")
        def choose():
            file_filter=DXF_PROFILE_FILTER if dxf_only else "纵断面 (*.csv *.dxf *.json)"
            path,_=QFileDialog.getOpenFileName(dialog,"导入纵断面","",file_filter)
            if path:import_file(path)
        def remap(*_):
            source_origin.setEnabled(alignment_choice.currentData()=="auto")
            if draft["import_path"]:self._guard(lambda:import_file(draft["import_path"]))
        source_units.currentIndexChanged.connect(remap)
        alignment_choice.currentIndexChanged.connect(remap)
        def origin_changed(value):
            draft["origin_override"]=value
            remap()
        source_origin.valueChanged.connect(origin_changed)
        load.clicked.connect(lambda:self._guard(choose))
        def local_controls_changed(*_):
            application_scope.setCurrentIndex(0);application_scope.setEnabled(False)
            draft["group_candidate"]=None
        table.itemChanged.connect(local_controls_changed)
        replace_arc.toggled.connect(lambda checked:local_controls_changed() if checked else None)
        def read_candidate():
            allowed={"pipe_axis","common_outer_bottom"} if is_pipe else {"inner_invert"}
            if is_round_culvert:allowed.add("inner_invert")
            if is_pipe and not is_round_culvert and reference.currentData()=="inner_invert":raise ValueError("请核对首管管轴或共同外管底高程；不能直接把管内底重新标为管轴")
            if reference.currentData() not in allowed:raise ValueError("来源高程基准未识别，请明确选择实际高程基准后再确认")
            rows=table_rows();edited=rows!=draft["rows"]
            original=draft["profile"]
            if original and not edited and not replace_arc.isChecked():
                candidate=normalize_design_profile(original,reference=reference.currentData())
            else:
                if original and any(e["kind"]=="arc" for e in original["elements"]) and not replace_arc.isChecked():
                    raise ValueError("控制值已改变，原圆弧不能继续沿用；请补充真实新轴线，或明确勾选采用折线控制高程")
                candidate=normalize_design_profile(rows,reference=reference.currentData())
            source=draft["source"]
            if source and hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest()!=source["sha256"]:
                raise ValueError("编辑期间轴线源文件已改变，请重新导入")
            if source and (source["coordinate_units"]!=source_units.currentData() or abs(source["source_origin_m"]-source_origin.value())>1e-6
                           or source["path"]!=str(Path(draft["import_path"]).resolve())
                           or draft["mapped_mode"]!=alignment_choice.currentData()):
                raise ValueError("导入单位或起点桩号已改变，请重新导入轴线")
            clipped=clip_design_profile(candidate,asset["station_start"],asset["station_end"])
            if is_round_culvert and clipped["reference"]=="inner_invert":
                from 土石方计算.services.design_profiles import pipe_axis_profile
                section=asset.get("section",{});first=(section.get("pipes") or [section])[0]
                outer=first.get("outer_diameter",section.get("outer_diameter"))
                if outer is None:
                    diameter=first.get("inner_diameter",section.get("inner_diameter"))
                    inner_radius=first.get("inner_radius",section.get("inner_radius"))
                    wall=first.get("wall_thickness",section.get("wall_thickness"))
                    lining=first.get("lining_thickness",section.get("lining_thickness",0.))
                    if diameter is not None:inner_radius=float(diameter)/2
                    if inner_radius is None or wall is None:raise ValueError("圆涵净内底换算需先补齐真实净内径与施工外径，或净内径、壁厚及内衬厚度")
                    outer=2*(float(inner_radius)+float(wall)+float(lining))
                radius=float(outer)/2
                # Validate the exact derived axis, including arc domain and
                # dimensions. Save the original inner-invert reference itself.
                pipe_axis_profile({"design_profile":clipped,"section":section},radius,radius)
            if is_pipe:
                from 土石方计算.services.pipe_axis_continuity import inspect_pipe_axis_continuity,PipeAxisContinuityError
                candidate_asset=copy.deepcopy(asset);candidate_asset["design_profile"]=clipped
                report=inspect_pipe_axis_continuity({"networks":[{**network,"assets":[candidate_asset]}]},scope="all")
                # A real source axis can be saved before dimensions are known.
                # An already demonstrated jump/unsupported curve cannot be
                # accepted as a continuous axis; formal calculation rechecks.
                if any(d["code"]!="pipe_axis_validation_input" for d in report["diagnostics"]):raise PipeAxisContinuityError(report)
                draft["axis_dimensions_pending"]=not report["valid"]
            if application_scope.currentData()=="covered_route" and draft["imported_profile"] is not None:
                from 土石方计算.services.imported_design_profiles import bind_imported_route_profile
                full=normalize_design_profile(draft["imported_profile"],reference=reference.currentData())
                updated,group_report=bind_imported_route_profile(self._inputs,network,asset,full,source=source,
                    mapping=source["station_mapping"],source_units=source["coordinate_units"],scope="covered_route")
                draft.update(group_candidate=updated,group_report=group_report)
            return clipped,edited
        def confirm():
            try:draft["accepted"]=read_candidate()
            except (ValueError,TypeError,OSError) as exc:QMessageBox.warning(dialog,"纵断面需要核对",str(exc));return
            dialog.accept()
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(confirm);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()!=QDialog.Accepted:return
        data,edited=draft["accepted"] or read_candidate()
        if draft.get("group_candidate") is not None:
            self._inputs=draft["group_candidate"]
            report=draft["group_report"]
            self._refresh_source_diagnostics();self._invalidate();self._refresh_assets()
            self._log(f"已将纵线应用到{len(report.get('assets',[]))}个同线管段，并更新{len(report.get('trenchless',[]))}个非开挖段轴线。")
            return
        if route_pipe and asset.get("axis_source")=="water_profile_real_elevation" and asset.get("design_profile"):
            asset.setdefault("water_profile_design_profile",copy.deepcopy(asset["design_profile"]))
        if asset.get("design_profile") and not asset.get("original_design_profile"):asset["original_design_profile"]=copy.deepcopy(asset["design_profile"])
        # The individual editor replaces any earlier workbench siphon choice.
        asset.pop("siphon_axis_choice",None)
        asset.pop("siphon_axis_input",None)
        asset["design_profile"]=data
        asset["profile_points"]=[{"station":s,"elevation":evaluate_profile(data,s)[0]} for s in profile_break_stations(data)]
        asset.setdefault("alignment",{}).update(profile_points=copy.deepcopy(asset["profile_points"]),elevation_reference=data["reference"])
        asset["profile_source"]="user_input_real_elevation";asset["cover_preview_confirmed"]=True
        if is_pipe:
            asset.setdefault("construction",{}).update(burial_mode="actual_axis",axis_confirmed=True)
            if route_pipe:
                from 土石方计算.services.design_profiles import sync_bound_axis_controls
                asset["pipe_profile_choice"]="quantity_dxf"
                sync_bound_axis_controls(asset)
            asset["axis_source"]="user_input_real_elevation"
            asset.pop("axis_cover_samples",None);asset.pop("axis_preview_sha256",None)
            asset.pop("cover_confirmation",None)
            asset.pop("cover_generation_options",None);asset.pop("cover_actual_cover_summary",None)
        if draft["source"]:
            source=draft["source"];asset["profile_source_file"]={**source,"control_values_edited":edited}
            files=self._inputs.setdefault("input_files",[])
            files[:]=[f for f in files if os.path.normcase(str(f.get("path","")))!=os.path.normcase(source["path"])]+[copy.deepcopy(source)]
        asset["missing_fields"]=[f for f in asset.get("missing_fields",[]) if f!="design_profile"]
        self._invalidate();self._log("已保存真实轴线草稿；管道尺寸待补齐，补齐后仍须校核逐管连续性。" if draft.get("axis_dimensions_pending") else "已保存控制高程；实际覆土将在断面预览和计算中重新核对。")

    def add_pit(self):
        pit={"asset_id":"pit-"+uuid.uuid4().hex[:10],"name":"矩形平底基坑","kind":"pit","section_type":"rectangular_pit","section":{},"placement":{},"construction":{"target_mode":"restore_terrain"},"workbench_geometry":True}
        dialog=AssetParameterDialog(pit,self)
        if dialog.exec()==QDialog.Accepted:self._inputs.setdefault("pits",[]).append(dialog.asset);self._invalidate();self._refresh_assets()

    def _sampling_changed(self,*_):
        self.sampling_note.setText(f"常规最大间距{self.step.value():g}m，弯道自动加密，平均断面法；新增断面参与算量和包络。")

    def _restore_accuracy(self,settings):
        self.step.setValue(settings.get("profile_step",20))
        self._sampling_changed()

    def _accuracy(self):return {"sampling_mode":"fixed","profile_step":self.step.value()}

    def _require_current_project_source(self):
        if self._source_hash and self._project_provider:
            snapshot=self._project_provider()
            panel=snapshot.get("merged_panel") or snapshot.get("water_profile_panel") or {}
            if panel.get("water_result_current") is False or source_hash(snapshot)!=self._source_hash:
                self._workbench_design_stale = True
                self._invalidate()
                ready = (bool(panel.get("calculated_nodes")) and panel.get("water_result_current") is not False
                         and (panel.get("merged_section") or {}).get("sync_ready") is not False)
                if ready:
                    raise CurrentDesignChanged("主工程已有更新的水面线成果。读取水面线成果后继续算量。")
                raise CurrentDesignChanged("主工程的设计输入已变化。完成水面线计算后，重新读取水面线成果。")
            return snapshot

    def start_calculation(self):
        if not self._require_applied_workspace() or not self._require_applied_special_segment():return
        from 土石方计算.io.independent_terrain import TerrainImportError
        from 土石方计算.services.workbench_automatic_ranges import has_workbench_automatic_ranges, restore_workbench_automatic_ranges
        from 土石方计算.services.earthwork_scope import trenchless_exclusions
        from 土石方计算.services.pipe_axis_continuity import is_in_calculation_scope
        from 土石方计算.services.sluice_gate import workbench_has_ready_gates
        from 土石方计算.services.workbench_calculator import workbench_requires_section_terrain
        from 土石方计算.services.workbench_scope import (clear_calculation_deferrals, defer_calculation_assets,
            preflight_calculation_assets, supports_partial_calculation)
        if self.runner.isRunning():raise RuntimeError("上一任务尚未结束，请等待完成或取消。")
        self._require_current_project_source()
        # Reopen automatic ranges only in the candidate. The adopted sections
        # and their inputs stay together until the replacement is complete.
        inputs = (restore_inputs(restore_workbench_automatic_ranges(self._inputs))
                  if has_workbench_automatic_ranges(self._inputs) else copy.deepcopy(self._inputs))
        assets = [(network, asset) for network in inputs.get("networks", []) for asset in network.get("assets", [])]
        has_bores=bool(trenchless_exclusions(inputs))
        if not assets and not inputs.get("pits") and not has_bores:raise ValueError("先读取渠道、暗涵或管道工程成果")
        self._adopt_drawing_sources(inputs)
        from 土石方计算.services.drawing_bindings import validate_active_bindings
        if inputs.get("drawing_binding_issues"):raise ValueError("真实图纸绑定存在待核区段，请通过“绑定真实断面”处理后算量")
        validate_active_bindings(inputs,raise_on_error=True)
        allow_partial=supports_partial_calculation(inputs)
        if not allow_partial:
            for network,asset in assets:
                if (is_in_calculation_scope(asset) and network is not None
                        and network.get("alignment") is None):
                    raise ValueError("需要补齐实际平面轴线："+asset.get("name",""))
        request=self._cover_request()
        self._refresh_source_diagnostics(inputs)
        accuracy=self._accuracy()
        clear_calculation_deferrals(inputs)
        from 土石方计算.services.estimated_connections import estimate_circular_connection_gaps
        prior_estimates = {row["asset_id"] for row in inputs.get("connector_estimates", ())}
        inputs = estimate_circular_connection_gaps(inputs)
        new_connection_estimates = sum(row["asset_id"] not in prior_estimates
                                       for row in inputs.get("connector_estimates", ()))
        pending=preflight_calculation_assets(inputs,require_profile=False) if allow_partial else []
        needs_terrain=workbench_requires_section_terrain(inputs)
        bore_only=has_bores and not needs_terrain
        has_gates=workbench_has_ready_gates(inputs)
        gate_only=has_gates and not needs_terrain and not has_bores
        def work(token):
            from 土石方计算.services.pipe_axis_continuity import calculate_checked_workbench
            def calculate_without_terrain(reason=None):
                calculated=calculate_checked_workbench(None,inputs,accuracy=accuracy,
                    allow_partial_scope=allow_partial,terrain_unavailable_reason=reason,
                    cancelled=lambda:token.is_cancelled)
                return None,calculated,inputs,{"completed":[]}
            if not needs_terrain and (has_bores or has_gates or pending):
                return calculate_without_terrain()
            self._task_progress_event.emit(token.generation,"terrain",0.,"正在核对并准备计算地形。")
            try:
                tin=self._ensure_tin(token,request)
            except (TerrainUnavailable, TerrainSourceChanged, TerrainImportError, OSError) as error:
                token.raise_if_cancelled()
                if not allow_partial or not (has_bores or has_gates):
                    raise
                self._task_progress_event.emit(token.generation, "sections", 0.,
                    "先计算资料完整的闸室及非开挖区段。" if has_gates else
                    "计算地形暂不可用，先计算资料完整的非开挖洞段。")
                return calculate_without_terrain(str(error))
            from 土石方计算.services.default_section_schemes import ensure_default_section_schemes, pending_default_section_assets
            cover_inputs = inputs
            if pending_default_section_assets(inputs):
                self._task_progress_event.emit(token.generation,"construction",0.,"正在准备各区段的常规施工断面。")
                cover_inputs, _ = ensure_default_section_schemes(inputs, cancelled=lambda: token.is_cancelled)
                token.raise_if_cancelled()
            from 土石方计算.services.batch_cover_profiles import BatchCoverProfileError, prepare_batch_cover_profiles
            self._task_progress_event.emit(token.generation,"cover",0.,"正在准备施工纵断面与管道覆土参数。")
            prepared,cover_report=prepare_batch_cover_profiles(tin,cover_inputs,cover_depth=None,
                sample_step=request["cover_sample_step"],terrain_request=request,
                raise_on_error=not allow_partial,
                cancelled=lambda:token.is_cancelled,progress=lambda *a:self._task_progress_event.emit(token.generation,*a))
            if cover_report["failures"] and not defer_calculation_assets(prepared,cover_report["failures"]):
                raise BatchCoverProfileError(cover_report,prepared)
            if allow_partial:preflight_calculation_assets(prepared,require_profile=True)
            self._validate_cover_confirmations(prepared,request,tin,allow_partial=allow_partial)
            self._task_progress_event.emit(token.generation,"sections",0.,"正在逐断面计算挖方、回填与填筑。")
            calculated=calculate_checked_workbench(tin,prepared,terrain_request=request,accuracy=accuracy,
                allow_partial_scope=allow_partial,cover_failures=cover_report["failures"],
                split_tunnel_exposure=True,
                cancelled=lambda:token.is_cancelled,progress=lambda *a:self._task_progress_event.emit(token.generation,*a))
            return tin,calculated,prepared,cover_report
        expected_source=self._source_hash
        revision = self._input_revision
        automatic_delivery = self.auto_delivery.isChecked()
        output_root = self.output_directory.text().strip()
        def done(value):
            if revision != self._input_revision:
                raise ValueError("计算期间算量输入已修改，请按当前输入重新计算。")
            if expected_source and self._project_provider:
                current=self._project_provider()
                panel=current.get("merged_panel") or current.get("water_profile_panel") or {}
                if panel.get("water_result_current") is False or source_hash(current)!=expected_source:
                    self._workbench_design_stale = True
                    self._invalidate()
                    raise ValueError("计算期间主程序设计成果已变化；未发布本次成果，请完成水面线计算后重新读取当前设计")
            self._results_calculating = False
            self._inputs=value[2]
            if value[0] is not None:self._accept_tin(value[0])
            elif self.terrain_path.text() and (terrain_reason := value[1][1].get("terrain_deferred_reason")):
                self._terrain_import_failed = True
                self._terrain_map_note = terrain_reason
            self.last_delivery_path = ""
            self._calculated(value[1])
            if value[3]["completed"]:self._log(f"已自动生成 {len(value[3]['completed'])} 个管段的覆土纵断面。")
            if new_connection_estimates:
                self._log(f"已按相邻圆管涵估算 {new_connection_estimates} 个连接段，采用依据见连接段明细。")
            if automatic_delivery and self._valid:
                from 土石方计算.services.workbench_delivery import delivery_directory
                folder = output_root or str(default_delivery_root())
                if not output_root:
                    self.output_directory.setText(folder)
                    self._log("已采用默认成果目录：" + folder)
                self.export_delivery_to(delivery_directory(folder, self._inputs, project_name=self._source_channel_name))
            elif self._valid and self._result.get("terrain_unmeasured_ranges"):
                self.feedback.succeed("可计量区段已完成，地形缺测区段已列入工程量表。")
            elif self._valid and self._result.get("calculation_deferred_assets"):
                self.feedback.succeed("可计量对象已完成，待核对象及原因已单列。")
            elif not self._valid:self.feedback.fail("本次未形成可导出的有效成果，请查看过程记录中的待核事项。")
        def cancelled():
            self._results_calculating = False
            self._results_preparing = False
            self._log("本次算量已取消，上次成果仍可查看。" if self._valid else "本次算量已取消，可按当前输入重新计算。")
            self._refresh_results_stage()

        self._results_calculating = True
        self._result_setting_mode = ""
        self._submit_task(work,title="挖填量计算",
            message="正在计算闸室结构量。" if gate_only else "正在计算非开挖圆孔洞挖量。" if bore_only else "正在准备地形与施工参数，随后逐断面计算挖填量。",
            on_success=done,on_error=self._failed,on_cancelled=cancelled,
            success_message="洞挖量已算好，可查看明细或保存成果。" if bore_only else "数量已算好，可逐桩查看断面或保存成果。")

    def _calculated(self,value):
        self._results_preparing = False
        self._historical_review_id = None
        self.result_tabs.setCurrentIndex(0)
        self._query_view=None
        self._skipped_section_message=None
        self._calculation,self._result=value
        payload=self._result
        if self._calculation is not None and (payload.get("default_section_scheme_policy")
                                               or payload.get("calculation_deferred_assets")):
            # A fresh calculation adopts the same defaults used by its sections.
            # Reopening an old result must preserve newer saved input edits.
            self._inputs=restore_inputs(payload["inputs"]["workbench"])
        if payload.get("automatic_construction_resolutions"):
            if self._calculation is not None:
                self._inputs=restore_inputs(payload["inputs"]["workbench"])
            for item in payload["automatic_construction_resolutions"]:
                self._log(item.get("message") or "已记录局部支护直槽施工假定；支护结构量另计。")
        skipped=payload.get("automatic_unsupported_pipe_ranges") or {}
        if skipped.get("range_count"):
            if self._calculation is not None:
                self._inputs=restore_inputs(payload["inputs"]["workbench"])
            self._log(f"已跳过{skipped['range_count']}处悬空区段，共{skipped['total_length_m']:.3f}m。")
        terrain_gap_note=_range_result_note(payload,"terrain_unmeasured_ranges","地形缺测")
        if terrain_gap_note:
            if self._calculation is not None:
                self._inputs=restore_inputs(payload["inputs"]["workbench"])
            self._log(terrain_gap_note+"。起止桩号和长度列入工程量表。")
        from 土石方计算.services.workbench_identity import result_contract_is_current
        from 土石方计算.services.network_section_calculator import section_result_publishable
        self._valid=(section_result_publishable(payload)
                     and result_contract_is_current(payload))
        accuracy=(payload.get("inputs") or {}).get("accuracy",{})
        self._valid=self._valid and accuracy.get("sampling_mode")=="fixed" and accuracy.get("profile_step",20)==self.step.value()
        from 土石方计算.services.pipe_axis_continuity import require_result_pipe_axis_continuity,PipeAxisContinuityError
        try:require_result_pipe_axis_continuity(payload,current_inputs=self._inputs)
        except PipeAxisContinuityError as exc:self._valid=False;self._log("保留历史断面；正式成果未通过管轴连接校核："+str(exc))
        self._section_groups={}
        for section in payload.get("sections",[]):self._section_groups.setdefault(section["asset_id"],[]).append(section)
        for values in self._section_groups.values():values.sort(key=lambda s:(s["station"],str(s.get("side",""))))
        self._measured_assets = {
            (str(row.get("route_id") or ""), row.get("original_asset_id") or row["asset_id"]): row["asset_id"]
            for row in payload.get("assets") or payload.get("rows") or () if row.get("asset_id")
        }
        self._refresh_assets()
        from 土石方计算.io.workbench_drawings import VOLUMES
        from 土石方计算.io.structure_quantity_tables import trenchless_summary_columns
        bore_records=payload.get("trenchless_excavation_rows") or []
        validation=payload.get("validation") or {}
        bore_only=validation.get("trenchless_only")
        gate_only=validation.get("sluice_gate_only")
        gaps_only=validation.get("automatic_terrain_unmeasured_only")
        tunnels_pending_only=validation.get("automatic_tunnel_exposed_only")
        volume_labels=list(VOLUMES) if not (bore_only or gate_only or gaps_only or tunnels_pending_only) else []
        if gate_only:
            volume_labels.append(("all_concrete_volume", "闸室混凝土"))
        if bore_records:
            volume_labels.extend((key,name) for key,name in trenchless_summary_columns(payload)
                                 if not bore_only or key!="total_excavation_volume")
        self.summary.setText((result_scope_prefix(payload) or ((payload.get("quantity_basis") or {}).get("label","")+"；" if payload.get("quantity_basis") else "TEST；" if payload.get("test_only") else ""))+("历史/未收敛成果；" if not self._valid else "")+"；".join(f"{name} {payload[key]:,.3f}m³" for key,name in volume_labels if payload.get(key) is not None))
        if bore_records and payload.get("trenchless_excavation_complete") is False:
            base=self.summary.text().rstrip("；")
            self.summary.setText((base+"；" if base else "")+"非开挖段资料待补，详见洞挖明细")
        if accuracy.get("sampling_mode")=="fixed" and not (bore_only or gate_only):
            from 土石方计算.io.workbench_drawings import section_sampling_note
            self._log(section_sampling_note(payload))
        if payload.get("layered_excavation_scope"):
            from 土石方计算.io.workbench_drawings import layered_scope_note,layered_volume_columns
            self._log("；".join(f"{name} {payload[key]:,.3f}m³" for key,name in layered_volume_columns(payload))+"；"+layered_scope_note(payload))
        if (payload.get("special_pipe_materials") or {}).get("length_mode_active"):
            self._log(f"全部已计混凝土 {payload.get('all_concrete_volume',0.):,.3f}m³（含管座、包封等分项）；特殊材料按长度修正，土方保留原断面依据，回填未随长度材料变化修正")
        if payload.get("quantity_scope_issues"):
            for item in payload["quantity_scope_issues"]:
                self._log(f"待补分项：{item.get('name') or item.get('asset_id','')}：{item.get('message','')}")
        if gaps_only:
            self.section_label.setText("地形缺测区段的起止桩号和长度已列入工程量表。")
        elif tunnels_pending_only:
            self.section_label.setText("隧洞露顶待计区段的起止桩号和长度已列入工程量表。")
        elif validation.get("automatic_unsupported_only"):
            self.section_label.setText("悬空区段已跳过，起止桩号和长度列入工程量表。")
        elif bore_only:
            self.section_label.setText("非开挖区段按圆孔计量，可查看洞挖明细。")
            self._log("已计算非开挖圆孔洞挖量。" if self._valid else "已打开历史非开挖成果，请复算后导出。")
        elif gate_only:
            self.section_label.setText("闸室底板和边墙工程量可在结构分项中查看。")
            self._log("闸室结构量已计算。")
        else:
            self._log((f"已完成 {len(payload.get('sections',[])):,} 个断面，全部可浏览；逐桩图采用原土方构造，特殊材料另按已采用长度修正。" if (payload.get("special_pipe_materials") or {}).get("length_mode_active") else f"已完成 {len(payload.get('sections',[])):,} 个断面，全部可浏览；图纸与量表使用同一快照。") if self._valid else "已读取历史断面供核查；算法已更新、输入已变化或复算未通过时，请重新计算后导出。")
        self._selection_changed();self.data_changed.emit()

    def _failed(self,error):
        was_calculating = self._results_calculating
        self._results_calculating = False
        if was_calculating:
            from 土石方计算.io.independent_terrain import TerrainImportError
            if isinstance(error, (TerrainImportError, TerrainSourceChanged, TerrainUnavailable)):
                self._terrain_import_failed = True
                self._terrain_map_note = str(error)
        if isinstance(error, TerrainSourceChanged):
            self._invalidate()
        self._log(str(error))
        for item in getattr(error,"diagnostics",[]):self._log(item.get("message",str(item)) if isinstance(item,dict) else item)
        if was_calculating:
            self._results_preparing = False
            self._show_records()
            self.feedback.show()
        self._refresh_workflow()

    def _busy(self,busy):
        self._ui_busy=busy
        self._set_workflow_busy(busy)
        self.cancel_button.setEnabled(busy or self.map_terrain_runner.isRunning())
        if not busy:self.cancel_button.setText("取消")
        self.cancel_button.setVisible(busy or self.map_terrain_runner.isRunning());self._refresh_workflow()

    def _submit_task(self,work,*,title,message="",on_success=None,on_error=None,on_cancelled=None,success_message="",cancel_message="本次任务已取消，已有成果与输入草稿保留。",transient_success=False):
        if self.runner.isRunning():raise RuntimeError("上一任务尚未结束，请等待完成或取消。")
        self.feedback.show()
        generation=self.feedback.start(title,message)
        def succeeded(value):
            if on_success:on_success(value)
            # A success callback can chain delivery, which owns the new feedback.
            if self.feedback.generation==generation and self.feedback.active:
                self.feedback.succeed(success_message)
                if transient_success:self.feedback.hide()
        def failed(error):
            if self.feedback.generation==generation:self.feedback.fail(display_text(error))
            if on_error:on_error(error)
            else:self._log(str(error))
        def cancelled():
            if self.feedback.generation==generation:
                self.feedback.cancelled(cancel_message)
            if on_cancelled:on_cancelled()
        try:return self.runner.submit(work,on_success=succeeded,on_error=failed,on_cancelled=cancelled)
        except Exception as exc:
            failed(exc);raise

    def _request_cancel(self):
        self.runner.cancel();self.map_terrain_runner.cancel();self.feedback.request_cancel()
        self.cancel_button.setText("正在取消…");self.cancel_button.setEnabled(False)

    def _task_progress(self,generation,stage,fraction,message):
        if generation!=self.runner.generation or not self.runner.isRunning():return
        self._progress(stage,fraction,message)

    def _progress(self,stage,fraction,message):
        if not self.feedback.active:return
        self.feedback.update_progress(stage,fraction,display_text(message));self._log(message)

    def _selection_changed(self):
        self._skipped_section_message=None
        self.result_restore_review_button.hide()
        row=self.table.currentRow()
        if row>=0 and self.table.isRowHidden(row):
            self.structure_filter.setCurrentIndex(0)
        self._refresh_workflow()
        if self._viewing_historical_result():
            self._restore_review_records()
            return
        try:network,asset=self.selected_asset()
        except ValueError:self._records=[];self._draw();return
        self._set_review_records(self._measured_asset_id(network, asset))

    def _result_route_id(self, network):
        if network is None:
            return "independent_pits"
        for key in ("route_id", "network_id", "name"):
            if network.get(key):
                return str(network[key])
        return next((f"route-{i}" for i, item in enumerate(self._inputs.get("networks", ()), 1)
                     if item is network), "")

    def _measured_asset_id(self, network, asset):
        route = self._result_route_id(network)
        identifier = self._measured_assets.get((route, asset["asset_id"]), asset["asset_id"])
        records = self._section_groups.get(identifier, ())
        if records and records[0].get("route_id") and str(records[0]["route_id"]) != route:
            return None
        return identifier

    def _set_review_records(self, asset_id):
        self._skipped_section_message = None
        self.result_restore_review_button.hide()
        self._query_view = None
        self._records = self._section_groups.get(asset_id, [])
        if not self._records and not self._viewing_historical_result():
            try:
                _, asset = self.selected_asset()
            except ValueError:
                pass
            else:
                start, end = asset.get("station_start"), asset.get("station_end")
                if start is not None and end is not None and not start <= self.station_spin.value() <= end:
                    self.station_spin.setValue(start)
        self.slider.setRange(0, max(0, len(self._records)-1))
        self.slider.setValue(0)
        self._browse_changed(0)

    def _browse_changed(self,index,*,draw=True):
        self.previous.setEnabled(index > 0)
        self.next.setEnabled(index + 1 < len(self._records))
        self.slider.setEnabled(len(self._records) > 1)
        if self._records:
            section=self._records[min(index,len(self._records)-1)];self.station_spin.setValue(section["station"])
            if section.get("preview_kind")=="unburied_pipe":
                self.section_label.setText(f"位置 {section['station']:.3f}m　"+section["message"])
            else:
                areas=section.get("roles",{});self.section_label.setText(f"{index+1}/{len(self._records)}　位置 {section['station']:.3f}m　"+"；".join(f"{name}{areas.get(role,{}).get('area',0):.3f}m²" for role,name in (("excavation","挖"),("backfill","回填"),("embankment","填筑"))))
                if section.get("geology",{}).get("mode")=="surface_thickness":
                    self.section_label.setText(self.section_label.text()+"；"+"；".join(f"{name}{areas.get(role,{}).get('area',0):.3f}m²" for role,name in (("overburden","覆盖层挖方"),("bedrock","基岩挖方")))+f"；简化分层厚度{section['geology']['thickness']:g}m（竖直）")
            if section.get("view_only"):
                historical=not self._valid and self._query_view and section is self._query_view["section"]
                self.section_label.setText(self.section_label.text()+("　历史查看断面（未加入积分）" if historical else "　查看断面（未加入积分）"))
            elif not section.get("preview_kind"):
                suffix = "　已计量断面"
                if any(0 <= neighbor < len(self._records) and
                       abs(self._records[neighbor]["station"] - section["station"]) < 1e-8
                       for neighbor in (index - 1, index + 1)):
                    suffix += {"left": " · 分界前", "right": " · 分界后"}.get(section.get("side"), "")
                self.section_label.setText(self.section_label.text() + suffix)
        elif self._result is not None:
            self.section_label.setText(getattr(self, "_skipped_section_message", "") or "当前建筑物没有已计量横断面。")
        if draw:self._draw()

    def _query_result_identity(self):
        """Bind the UI-only record to the actual saved calculation snapshot."""
        payload=self._result or {};digest=payload.get("input_hash")
        if not isinstance(digest,str) or len(digest)!=64 or not isinstance(payload.get("inputs"),dict):return None
        from 土石方计算.services.independent_project import input_hash,terrain_identity
        try:
            if input_hash(payload["inputs"],terrain_identity(payload.get("terrain",{})))!=digest:return None
        except (TypeError,ValueError):return None
        return {"project_id":self.project_id,"input_hash":digest,"calculation_contract":payload.get("calculation_contract")}

    @staticmethod
    def _query_record_hash(section):
        return hashlib.sha256(json.dumps(section,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf8")).hexdigest()

    def _valid_query_view(self,view,station):
        if not isinstance(view,dict):return False
        try:
            network,asset=self.selected_asset();section=view["section"]
            if view.get("source_asset_id")!=asset["asset_id"] or view.get("result_identity")!=self._query_result_identity():return False
            if not view.get("result_identity") or not isinstance(section,dict) or section.get("view_only") is not True:return False
            if not math.isfinite(station) or abs(float(section["station"])-station)>1e-8:return False
            if "station_start" in asset and not asset["station_start"]<=station<=asset["station_end"]:return False
            known=self._section_groups.get(section.get("asset_id"),[])
            if not known or section.get("route_id")!=known[0].get("route_id"):return False
            if section["asset_id"]!=self._measured_asset_id(network,asset):return False
            return view.get("section_sha256")==self._query_record_hash(section)
        except (KeyError,TypeError,ValueError):return False

    def _saved_query_view(self):
        if self._query_view and self._records and self._records[min(self.slider.value(),len(self._records)-1)] is self._query_view["section"] and self._valid_query_view(self._query_view,self.station_spin.value()):
            return copy.deepcopy(self._query_view)
        return None

    def _restore_query_view(self,ui):
        if not self._all_assets():self.station_spin.setValue(0.);return
        try:station=float(ui["query_station"])
        except (KeyError,TypeError,ValueError):return
        if not math.isfinite(station) or not self.station_spin.minimum()<=station<=self.station_spin.maximum():return
        view=ui.get("query_view")
        if view is not None:
            if not self._valid_query_view(view,station):
                self._log("保存的查看断面身份不匹配，已恢复正式断面。");return
            self._query_view=copy.deepcopy(view);self._records=[self._query_view["section"]]
            self.slider.setRange(0,0);self.slider.setValue(0);self._browse_changed(0)
            self.result_restore_review_button.show()
        else:self.station_spin.setValue(station)

    def preview_selected(self):
        from 土石方计算.services.unburied_preview import is_unburied_pipe
        if not self.terrain_path.text() and not is_unburied_pipe(self.selected_asset()[1]):return
        self.query_station()

    def _show_skipped_section(self,section):
        self._query_view=None
        self._records=[]
        self._skipped_section_message=section["message"]
        self.slider.setRange(0,0)
        self._browse_changed(0,draw=False)
        self.section_label.setText(section["message"])
        try:
            network, asset = self.selected_asset()
        except ValueError:
            self.result_restore_review_button.hide()
        else:
            self.result_restore_review_button.setVisible(bool(self._section_groups.get(self._measured_asset_id(network,asset))))
        self._draw()

    def _measured_section_at_station(self, network, station, precision):
        matches = []
        for row, (owner, asset) in enumerate(self._all_assets()):
            if owner is not network or not self._section_groups.get(self._measured_asset_id(owner, asset)):
                continue
            start, end = asset.get("station_start"), asset.get("station_end")
            if start is not None and end is not None and start - precision <= station <= end + precision:
                matches.append((row, asset))
        return matches[0] if len(matches) == 1 else None

    def query_station(self):
        network,asset=self.selected_asset();station=self.station_spin.value()
        measured_id = self._measured_asset_id(network, asset)
        route = self._result_route_id(network)
        query_id = f"{route}::{asset['asset_id']}" if network is not None else measured_id
        if self._valid and network is not None:
            from 土石方计算.services.workbench_automatic_ranges import skipped_workbench_section
            for origin in ("automatic_unsupported_pipe_origin", "automatic_tunnel_exposure_origin", "automatic_terrain_gap_origin"):
                source = (asset.get(origin) or {}).get("source_asset_id")
                if source and (skipped := skipped_workbench_section(self._inputs, f"{route}::{source}", station, "right")):
                    self._show_skipped_section(skipped)
                    return
            skipped = skipped_workbench_section(self._inputs, query_id, station, "right")
            if skipped:
                self._show_skipped_section(skipped)
                return
        if network is not None:
            start, end = asset.get("station_start"), asset.get("station_end")
            if start is not None and end is not None:
                precision = .5 * 10 ** -self.station_spin.decimals()
                if not start - precision <= station <= end + precision:
                    match = self._measured_section_at_station(network, station, precision) if self._valid else None
                    if match is None:
                        raise ValueError(f"当前区段桩号范围为 {start:.3f} ～ {end:.3f} m。请输入范围内的桩号，或选择对应建筑物。")
                    row, asset = match
                    self.table.selectRow(row)
                    self.station_spin.setValue(station)
                    measured_id = self._measured_asset_id(network, asset)
                    query_id = f"{route}::{asset['asset_id']}"
                    start, end = asset["station_start"], asset["station_end"]
                    self._log(f"已按桩号定位至{asset.get('name') or asset['asset_id']}。")
                station = min(end, max(start, station))
        self._skipped_section_message=None
        from 土石方计算.services.unburied_preview import is_unburied_pipe,preview_identity
        if network is not None and is_unburied_pipe(asset) and not asset.get("section_scheme_binding"):
            frozen_network=copy.deepcopy(network);frozen_asset=copy.deepcopy(asset)
            identity=preview_identity(network,asset);project_id=self.project_id
            def work(token):
                from 土石方计算.services.unburied_preview import preview_unburied_section,preview_unburied_profile
                token.raise_if_cancelled()
                section=preview_unburied_section(frozen_network,frozen_asset,station,cancelled=lambda:token.is_cancelled)
                profile=preview_unburied_profile(frozen_network,frozen_asset,station=station,cancelled=lambda:token.is_cancelled)
                token.raise_if_cancelled();return section,profile
            def done(value):
                try:current_network,current_asset=self.selected_asset()
                except ValueError:return
                if self.project_id!=project_id or current_network is None or preview_identity(current_network,current_asset)!=identity:return
                section,profile=value
                self._unburied_profile={"project_id":project_id,"identity":identity,"records":profile}
                self._records=[section];self.slider.setRange(0,0);self._browse_changed(0)
                self._log(section["message"]+"；预览未写入工程量快照。")
                from 土石方计算.services.pipe_axis_continuity import inspect_pipe_axis_continuity
                report=inspect_pipe_axis_continuity({"networks":[{**current_network,"assets":[current_asset]}]},scope="all")
                for issue in report["diagnostics"]:self._log("只读轴线核对："+issue["message"])
            self._submit_task(work,title="结构断面预览",message="正在生成当前桩号的结构断面。",on_success=done,on_error=self._view_failed,
                               on_cancelled=lambda:self._log("结构预览已取消；已保存工程量保留。"))
            return
        records = self._section_groups.get(measured_id, [])
        if self._valid and records:
            closest = min(range(len(records)), key=lambda i: abs(records[i]["station"] - station))
            if abs(records[closest]["station"] - station) <= .5 * 10 ** -self.station_spin.decimals():
                if self._records is records and records[self.slider.value()]["station"] == records[closest]["station"]:
                    closest = self.slider.value()
                self._records = records
                self._query_view = None
                self.result_restore_review_button.hide()
                self.slider.setRange(0,len(records)-1)
                self.slider.setValue(closest)
                self._browse_changed(closest)
                return
        inputs=copy.deepcopy(self._inputs);accuracy=self._accuracy();request=self._terrain_request()
        query_identity=self._query_result_identity() if self._valid else None
        def work(token):
            from 土石方计算.services.workbench_calculator import query_workbench_section
            tin=self._ensure_tin(token,request);return tin,query_workbench_section(tin,inputs,query_id,station,accuracy=accuracy)
        def done(value):
            try:
                current_network, current_asset = self.selected_asset()
            except ValueError:
                return
            if current_network is not network or current_asset is not asset:
                return
            self._accept_tin(value[0]);section=value[1];self._query_view=None
            if section.get("skipped"):
                self._show_skipped_section(section)
                return
            if query_identity is not None and self._valid and query_identity==self._query_result_identity():
                self._query_view={"source_asset_id":asset["asset_id"],"result_identity":query_identity,"section":section,"section_sha256":self._query_record_hash(section)}
            self._records=[section];self.slider.setRange(0,0);self._browse_changed(0);self.data_changed.emit()
            self.result_restore_review_button.setVisible(bool(records))
        self._submit_task(work,title="断面查看",message=f"正在读取桩号 {station:.3f}m 的地形与施工断面。",on_success=done,on_error=self._view_failed)

    def _view_failed(self,error):
        self._log("查看断面未完成："+str(error)+"；未改变已完成的工程量。")

    def _result_view_changed(self, *_):
        section = self.view_combo.currentData() == "section"
        self.result_browse_controls.setVisible(section)
        self.result_layer_controls.setVisible(section)
        self._refresh_result_profile_action()
        self._draw()

    def _refresh_result_profile_action(self):
        from 土石方计算.services.unburied_preview import is_unburied_pipe

        preview = self.result_profile_preview_button
        show = False
        if self.view_combo.currentData() == "profile":
            try:
                network, asset = self.selected_asset()
            except ValueError:
                pass
            else:
                show = network is not None and is_unburied_pipe(asset)
        preview.setVisible(show)
        preview.setEnabled(self.query_button.isEnabled())

    def _draw(self,*_):
        if not hasattr(self,"figure"):return
        self.figure.clear();axes=self.figure.add_subplot();axes.set_facecolor("#FAFCFE")
        view=self.view_combo.currentData()
        if view=="profile":self._draw_profile(axes)
        elif self._records:
            from 土石方计算.io.workbench_drawings import geometry_items,ground_parts,section_limits,construction_lines,component_lines,interface_parts,NAMES
            from matplotlib.patches import PathPatch
            from matplotlib.path import Path as MPath
            from .section_scheme_view import pipe_cut_note
            s=self._records[min(self.slider.value(),len(self._records)-1)];palette={"excavation":"#D86C55","overburden":"#C98C4B","bedrock":"#A45E6B","backfill":"#E7BC50","embankment":"#73A9D4","concrete":"#929BA4","bedding":"#B695CD","construction":"#2A8D83","net_void":"#333D49","outer":"#333D49"}
            used=set()
            for role,poly,fill in geometry_items(s):
                from shapely.geometry.polygon import orient
                poly=orient(poly,sign=1.)
                group="quantities" if role in ("excavation","overburden","bedrock","backfill","embankment") else "construction" if role=="construction" else "structure"
                if not self.layers[group].isChecked():continue
                if fill:
                    verts=[];codes=[]
                    for ring in [poly.exterior,*poly.interiors]:
                        coords=list(ring.coords);verts.extend(coords);codes.extend([MPath.MOVETO]+[MPath.LINETO]*(len(coords)-2)+[MPath.CLOSEPOLY])
                    patch=PathPatch(MPath(verts,codes),facecolor=palette.get(role,"#CCC"),edgecolor=palette.get(role,"#666"),alpha=.35,label=NAMES.get(role,role) if role not in used else None);axes.add_patch(patch)
                else:
                    p=np.asarray(poly.exterior.coords);axes.plot(p[:,0],p[:,1],color=palette.get(role,"#444"),lw=1.3,ls="--" if role=="construction" else "-",label=NAMES.get(role,role) if role not in used else None)
                used.add(role)
            if self.layers["structure"].isChecked():
                for role,line in component_lines(s):
                    axes.plot(line[:,0],line[:,1],color="#8B3D90",lw=1.5,ls="-.",label=NAMES.get(role,role) if role not in used else None)
                    used.add(role)
            if self.layers["construction"].isChecked():
                for i,p in enumerate(construction_lines(s)):
                    axes.plot(p[:,0],p[:,1],color="#2A8D83",lw=1.2,ls="--",label="施工边界" if i==0 else None)
                used.add("construction")
            if self.layers["ground"].isChecked():
                for i,p in enumerate(ground_parts(s)):axes.plot(p[:,0],p[:,1],color="#593F26",lw=1.6,label="原地面" if i==0 else None)
                for i,p in enumerate(interface_parts(s)):
                    axes.plot(p[:,0],p[:,1],color="#98704A",lw=1.2,ls="-.",label=f"简化基覆界面（竖直厚{s['geology']['thickness']:g}m）" if i==0 else None)
            left,right,bottom,top=section_limits(s);axes.set_xlim(left,right);axes.set_ylim(bottom-max(.6,(top-bottom)*.1),top+max(.6,(top-bottom)*.15))
            preview=s.get("preview_kind")=="unburied_pipe"
            structure = s.get("structure_geometry") or {}
            pipes = structure.get("pipes") or []
            title = "结构预览（未计土方/基础）" if preview else "横断面"
            test = s.get("test_only") if preview else (self._result or {}).get("test_only")
            caption = pipe_cut_note(pipes)
            axes.axvline(0,color="#BBC5CF",lw=.7,ls=":")
            axes.set_aspect("equal",adjustable="box")
            axes.set_title(f"{'TEST ' if test else ''}{title} {s['station']:.3f}m" + ("\n" + caption if caption else ""),
                           fontfamily="Microsoft YaHei")
            if preview and self.layers["structure"].isChecked():
                for i,(x,z) in enumerate(s["structure_geometry"].get("pipe_centers",[]),1):
                    axes.plot([x],[z],marker="+",color="#245A93",ms=7)
                    axes.annotate(f"管{i}轴 ▽{z:.3f}m",xy=(x,z),xytext=(8,8),textcoords="offset points",fontfamily="Microsoft YaHei",fontsize=8)
            z=s.get("design_elevation")
            if z is not None:axes.annotate(f"▽{z:.3f}m",xy=(0,z),xytext=(8,-18),textcoords="offset points",fontfamily="Microsoft YaHei",fontsize=8,arrowprops={"arrowstyle":"-","color":"#566675"},bbox={"facecolor":"white","edgecolor":"none","alpha":.8})
            from 土石方计算.io.workbench_drawings import polygons
            envelope_only = any(pipe.get("earthwork_envelope_only") for pipe in pipes)
            outlines = polygons(structure.get("outer" if envelope_only else "net_void"))
            if outlines:
                l,b,r,t = min(outlines,key=lambda p:abs(p.centroid.x)).bounds
                dimension = "竖切外包" if envelope_only else "竖切净空" if pipes else "当前剖切净空"
                axes.text(.01,.02,f"{dimension}宽{r-l:.3f}m，高{t-b:.3f}m",transform=axes.transAxes,fontfamily="Microsoft YaHei",fontsize=8,bbox={"facecolor":"white","edgecolor":"none","alpha":.8})
            axes.set_xlabel("横向偏距 (m)　面对桩号增大方向：左负、右正",fontfamily="Microsoft YaHei");axes.set_ylabel("绝对高程 (m)",fontfamily="Microsoft YaHei")
            axes.ticklabel_format(style="plain",useOffset=False)
            if used or self.layers["ground"].isChecked():axes.legend(prop={"family":"Microsoft YaHei","size":8},loc="best")
        else:
            from 土石方计算.services.unburied_preview import is_unburied_pipe
            try:unburied=is_unburied_pipe(self.selected_asset()[1])
            except ValueError:unburied=False
            validation=(self._result or {}).get("validation") or {}
            gap_list="地形缺测区段已列入工程量表。" if self._valid and validation.get("automatic_terrain_unmeasured_only") else ""
            message=(getattr(self,"_skipped_section_message",None) or gap_list or
                ("点击“查看此桩”显示真实管道结构\n明管/架空段未计土方/基础" if unburied else
                 "当前建筑物没有已计量横断面。" if self._result is not None else "导入地形与渠道成果后查看\n施工参数、结构和挖填断面"))
            axes.text(.5,.5,message,transform=axes.transAxes,ha="center",va="center",fontfamily="Microsoft YaHei",color="#778493")
        axes.grid(alpha=.15);self.canvas.draw_idle()

    def _draw_profile(self,axes):
        from 土石方计算.services.unburied_preview import is_unburied_pipe,preview_identity
        if self._skipped_section_message and self.result_review_picker.currentIndex() < 0:
            axes.text(.5,.5,self._skipped_section_message,transform=axes.transAxes,ha="center",fontfamily="Microsoft YaHei")
            return
        if self._viewing_historical_result():
            network, asset = None, {}
            values = self._section_groups.get(self._historical_review_id, [])
        else:
            try:network,asset=self.selected_asset()
            except ValueError:return
            values=self._section_groups.get(self._measured_asset_id(network, asset),[])
        unburied=network is not None and is_unburied_pipe(asset)
        if unburied:
            preview=getattr(self,"_unburied_profile",{})
            values=preview.get("records",[]) if preview.get("project_id")==self.project_id and preview.get("identity")==preview_identity(network,asset) else []
            axes.set_title("真实管轴及结构预览（未计土方/基础）",fontfamily="Microsoft YaHei")
            if not values:axes.text(.5,.5,"点击“生成结构纵断面”查看真实管轴及结构高程",transform=axes.transAxes,ha="center",fontfamily="Microsoft YaHei")
        if values:
            values=sorted(values,key=lambda s:s["station"]);stations=[s["station"] for s in values]
            from 土石方计算.io.workbench_drawings import longitudinal_values
            profiles=[longitudinal_values(s) for s in values]
            names={"design_base":"设计高程基准","ground":"轴线原地面","outer_top":"结构外顶","outer_bottom":"结构外底","bedding_bottom":"垫层底","construction_floor":"施工槽底","finished":"轴线完成面"}
            keys=list(names)+sorted(set(k for row in profiles for k in row if k.startswith("pipe_")))
            for key in keys:
                heights=[np.nan if row.get(key) is None else row[key] for row in profiles]
                if not np.isfinite(heights).any():continue
                name=names.get(key)
                if name is None:
                    _,index,level=key.split("_");name=f"管{index}"+{"axis":"管轴","top":"外管顶","bottom":"外管底","ground":"正上方地面"}[level]
                style=":" if "bottom" in key or key=="construction_floor" else "--" if "axis" in key or key=="outer_top" else "-." if key=="finished" else "-"
                from 土石方计算.services.pipe_axis_continuity import disconnected_series
                xs,ys=disconnected_series([{ "station":s["station"],"height":height} for s,height in zip(values,heights)],"height")
                axes.plot(xs,ys,label=name,ls=style,lw=1.2)
            axes.legend(prop={"family":"Microsoft YaHei","size":8},ncol=2)
        axes.set_xlabel("桩号/切片位置 (m)",fontfamily="Microsoft YaHei");axes.set_ylabel("高程 (m)",fontfamily="Microsoft YaHei");axes.ticklabel_format(style="plain",useOffset=False)

    def drawing_settings(self):
        dialog=QDialog(self);dialog.setWindowTitle("DXF出图设置");form=QFormLayout(dialog)
        interval=QDoubleSpinBox();interval.setRange(.25,1000);interval.setValue(self._drawing_options["interval"]);form.addRow("出图间距 m",interval)
        all_sections=QCheckBox("输出全部计算断面");all_sections.setChecked(self._drawing_options["all_sections"]);form.addRow(all_sections)
        all_sections.setToolTip("取消勾选后，按出图间距选取已计算断面，并保留结构交界等关键断面。")
        interval.setDisabled(all_sections.isChecked())
        all_sections.toggled.connect(interval.setDisabled)
        arrangement=QComboBox();arrangement.addItem("总览长图（每行10个断面）","overview");arrangement.addItem("按图幅分页","pages")
        arrangement.setCurrentIndex(max(0,arrangement.findData(self._drawing_options.get("section_layout","overview"))));form.addRow("排版",arrangement)
        paper=QComboBox();paper.addItems(["A3","A1"]);paper.setCurrentText(self._drawing_options["paper"]);form.addRow("分页图幅",paper)
        paper.setEnabled(arrangement.currentData()=="pages");arrangement.currentIndexChanged.connect(lambda _:paper.setEnabled(arrangement.currentData()=="pages"))
        scale=QComboBox();scale.addItem("自动适配",0)
        for value in (50,100,200,250,500,1000):scale.addItem(f"1:{value}",value)
        scale.setCurrentIndex(max(0,scale.findData(self._drawing_options["scale"])));form.addRow("比例",scale)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
        if dialog.exec()==QDialog.Accepted:self._drawing_options.update(interval=interval.value(),all_sections=all_sections.isChecked(),paper=paper.currentText(),scale=scale.currentData(),section_layout=arrangement.currentData());self.data_changed.emit()

    def choose_output_directory(self):
        folder=QFileDialog.getExistingDirectory(self,"选择一键算量成果目录",self.output_directory.text())
        if folder:self.output_directory.setText(folder);self.data_changed.emit()

    def _delivery_matches_result(self, directory, result):
        from 土石方计算.services.workbench_delivery import delivery_matches_result
        return delivery_matches_result(directory, (result or {}).get("input_hash"), self.project_id)

    def open_delivery_directory(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if not self._delivery_matches_result(self.last_delivery_path, self._result):
            self.last_delivery_path = ""
            if self._valid:
                self.result_tabs.setCurrentWidget(self.result_files_page)
            self._refresh_results_stage()
            message = "找不到原成果目录或其中成果已更换。"
            message += (f"可点击“{self.file_delivery_button.text()}”从当前结果重新保存。"
                        if self._valid else "可再次算量后保存成果。")
            self._show_operation_notice("打开成果目录", message)
            return False
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_delivery_path)):
            self._show_operation_notice("打开成果目录", f"请在文件资源管理器中打开 {self.last_delivery_path}")
            return False

    def export_delivery_to(self,directory):
        if not self._valid or self._result is None:raise ValueError("请先完成当前工程算量")
        project = self._require_current_project_source()
        from 土石方计算.services.workbench_delivery import read_delivery_manifest, save_workbench_delivery
        # A new calculation replaces this result tree. Exporters only read it
        # and take a detached copy before rewriting portable resource paths.
        payload=self._result;state=self.to_project_dict(include_result=False);options=copy.deepcopy(self._drawing_options)
        snapshot=copy.deepcopy({key: value for key, value in project.items() if key!="earthwork_panel"}) if project else None
        def work(token):
            return save_workbench_delivery(payload,directory,workbench_state=state,drawing_options=options,project_snapshot=snapshot,
                cancelled=lambda:token.is_cancelled,progress=lambda *a:self._task_progress_event.emit(token.generation,*a))
        def done(path):
            if self.project_id != state["project_id"] or self._result is not payload:
                self.feedback.succeed("原工程的成果已保存到 " + str(path))
                return
            self.last_delivery_path = path
            self.result_tabs.setCurrentWidget(self.result_files_page)
            self._log("算量成果已保存：" + path)
            failures = read_delivery_manifest(path).get("drawing_failures") or {}
            if failures:
                for filename, reason in failures.items():
                    self._log(f"待补导 {filename}：{reason}")
                self.feedback.succeed(f"工程量表已保存，{len(failures)} 份图纸待补导。")
            self._refresh_results_stage()
            self.data_changed.emit()
        message="数量已算好，正在生成并核对工程量表和图纸。" if payload.get("sections") else "数量已算好，正在生成并核对工程量表。"
        cancel_message = "成果保存已取消，当前工程量可继续查看。"
        self._submit_task(
            work, title="算量成果保存", message=message, on_success=done, on_error=self._export_failed,
            on_cancelled=lambda: self._log(cancel_message),
            success_message="计算与保存已完成，点击“打开成果目录”查看文件。", cancel_message=cancel_message,
        )

    def _result_export_path(self, filename, suffix):
        chosen = Path(filename)
        if chosen.suffix.lower() == suffix:
            return str(chosen)
        target = chosen.with_suffix(suffix)
        if filesystem_path(target).exists():
            answer = QMessageBox.question(self, "替换已有成果", f"所选格式对应的文件已存在：\n{target}\n要替换这份文件吗？",
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return None
        return str(target)

    def choose_result_export(self, kind):
        if not self._require_applied_workspace():
            return
        exports = {
            "opening": ("导出开挖线", "挖填平面外包络.dxf", "DXF 文件 (*.dxf)", {"envelopes_only": True}),
            "quantities": ("导出工程量表格", "工程量.xlsx", "Excel 文件 (*.xlsx)", {}),
            "sections": ("导出断面算量", "施工断面.dxf", "DXF 文件 (*.dxf)", {"sections_only": True}),
        }
        title, name, filters, options = exports[kind]
        root = self.last_delivery_path or self.output_directory.text().strip()
        path, _ = QFileDialog.getSaveFileName(self, title, str(Path(root) / name) if root else name, filters)
        if path:
            path = self._result_export_path(path, Path(name).suffix)
        if path:
            self.export_to(path, write_audit=False, **options)

    def choose_export_all(self):
        if not self._require_applied_workspace():return
        from 土石方计算.services.workbench_delivery import delivery_directory
        root=self.output_directory.text().strip()
        if not root:
            root=QFileDialog.getExistingDirectory(self,"选择成果保存目录",str(default_delivery_root()))
        if root:self.export_delivery_to(delivery_directory(root, self._inputs, project_name=self._source_channel_name))

    def export_to(self,path,*,table="assets",envelopes_only=False,opening_only=False,sections_only=False,write_audit=True):
        if not self._valid or self._result is None:raise ValueError("请先形成与当前输入一致的完整成果")
        self._require_current_project_source()
        from 土石方计算.services.pipe_axis_continuity import require_result_pipe_axis_continuity,PipeAxisContinuityError
        try:require_result_pipe_axis_continuity(self._result,current_inputs=self._inputs)
        except PipeAxisContinuityError:self._invalidate();raise
        from 土石方计算.io.section_exporter import export_section_result
        payload=self._result;options=copy.deepcopy(self._drawing_options)
        channel_name = self._source_channel_name
        if envelopes_only:options["envelopes_only"]=True
        if opening_only:options.update(envelopes_only=True,opening_only=True)
        if sections_only:options.update(include_plan=False,include_profile=False,concise=True)
        target = resolved_path(path)

        def work(token):
            export_options = {"table": table, "drawing_options": options, "cancelled": lambda: token.is_cancelled,
                              "channel_name": channel_name, "write_audit": write_audit}
            try:
                return export_section_result(payload, target, **export_options), False
            except PermissionError as error:
                occupied = getattr(error, "filename2", None) or error.filename
                audit = target.with_suffix(target.suffix + ".audit.json")
                if (not occupied or resolved_path(occupied) not in (target, audit)
                        or not filesystem_path(occupied).is_file()):
                    raise
                token.raise_if_cancelled()
                alternate = target.with_name(f"{target.stem}_另存_{uuid.uuid4().hex[:10]}{target.suffix}")
                self._task_progress_event.emit(token.generation, "delivery", 0., "原成果文件暂时无法替换，正在同目录另存。")
                return export_section_result(payload, alternate, **export_options), True

        def done(outcome):
            saved_path, alternate = outcome
            if alternate:
                message = "原成果文件暂时无法替换，已另存并回读核对：" + saved_path
                self.feedback.succeed(message)
                self._log(message)
            else:
                self._log("已保存并回读核对：" + saved_path)

        self._submit_task(work, title="算量成果导出", message="正在生成文件并回读核对。", on_success=done,
                          on_error=self._export_failed, on_cancelled=lambda: self._log("导出已取消；已计算数量和已有文件保留。"),
                          success_message="文件已保存并回读核对。")

    def _export_failed(self,error):
        message="导出未完成："+str(error)+"；已计算数量保留，可重新导出。"
        self._log(message)
        self._show_records()
        if self._valid and isinstance(error, OSError):
            self.result_tabs.setCurrentIndex(2)
            self._result_setting_mode = "delivery"
            self._refresh_results_stage()
        self.feedback.fail(display_text(message))
        self.feedback.show()

    def to_project_dict(self,*,include_result=True):
        terrain = {"path": self.terrain_path.text(), **copy.deepcopy(self._terrain_identity)}
        recovery_path = ""
        result = self._result or {}
        if self._valid and result.get("terrain_deferred_reason") and (result.get("validation") or {}).get("trenchless_only"):
            recovery_path = self._pending_terrain_path or self.terrain_path.text()
            terrain = {}
        return {"schema_version":"1.0","kind":"section_workbench","project_id":self.project_id,"workbench_inputs":serialize_inputs(self._inputs),
                "terrain":terrain,"terrain_mode":self._terrain_processing_mode,
                "terrain_options":copy.deepcopy(self._terrain_options),"settings":self._accuracy(),"drawing_options":copy.deepcopy(self._drawing_options),
                "output_directory":self.output_directory.text(),"auto_delivery":self.auto_delivery.isChecked(),"last_delivery_path":self.last_delivery_path,
                "last_result":copy.deepcopy(self._result) if include_result else None,"result_status":"READY" if self._valid else "STALE","source_project_hash":self._source_hash,
                "ui_state":{"workflow_step":self.workflow_stack.currentIndex(),"section_workspace":self._saved_workspace_state(),
                            "result_tab":self.result_tabs.currentIndex(),
                            "pipe_general_drafts":self.pipe_general.export_drafts(),
                            "pipe_special_drafts":self.pipe_segments.export_drafts(),
                            "pipe_profile_drafts":self.pipe_profile_editor.export_drafts(),
                            "trenchless_drafts":self.section_bore_card.export_drafts(),
                            "gate_drafts":self.gate_page.export_drafts(),
                            "section_drafts":copy.deepcopy(list(self._section_drafts.values())),
                            "workbench_view":self._saved_workbench_view(),"workbench_object":self._workbench_object,
                            "route_profile_group":self._channel_profile_key if self.section_views.currentWidget() is self.route_profile_page else None,
                            "pipe_exact_profile":self.section_views.currentWidget() is self.pipe_profile_page and self._pipe_exact_profile,
                            "pipe_construction_object":self._pipe_key if self.section_views.currentWidget() is self.pipe_page else None,
                            "connection_draft":copy.deepcopy(self._connection_draft_state),"selected_asset":self.table.currentRow(),"section_index":self.slider.value(),"view":self.view_combo.currentData(),"query_station":self.station_spin.value(),"query_view":self._saved_query_view(),"source_channel_name":self._source_channel_name,"saved_water_centerline":copy.deepcopy(self._saved_water_centerline),"terrain_recovery_path":recovery_path},"legacy_payload":copy.deepcopy(self._legacy_payload)}

    def _saved_inputs_match_result(self):
        recorded=(self._result.get("inputs") or {}).get("workbench")
        if not isinstance(recorded,dict):return False
        current=serialize_inputs(self._inputs);recorded=serialize_inputs(restore_inputs(recorded))
        if (self._result.get("test_only") is True and self._result.get("partial_acceptance") is True
                and self._result.get("defined_scope")):
            # Older editable TEST inputs may omit annotations that are already
            # preserved verbatim in the saved quantity result.
            for key in ("defined_scope","partial_acceptance","acceptance_scope"):
                if key not in current and recorded.get(key)==self._result.get(key):
                    recorded.pop(key,None)
        # Rendering fills the derived missing-field lists even for snapshots
        # produced directly by the service, before they have visited the UI.
        for source in (current,recorded):
            assets=[a for n in source.get("networks",[]) for a in n.get("assets",[])]+list(source.get("pits",[]))
            for asset in assets:self._remaining_missing(asset)
        return current==recorded

    def from_project_dict(self,data,*,preserve_task_feedback=False,normalized=False,take_ownership=False):
        from .project_state import normalize_earthwork_payload
        data = data or {}
        if normalized:
            if not take_ownership:
                data = copy.deepcopy(data)
        else:
            data = normalize_earthwork_payload(data)
        preserve_task_feedback = preserve_task_feedback or self._opening_project_file
        self._centerline_batch_network = None
        self._pending_terrain_path = ""
        self._pending_terrain_note = ""
        self._terrain_map_note = ""
        self._saved_water_centerline = (data.get("ui_state") or {}).get("saved_water_centerline")
        self._source_channel_name = str((data.get("ui_state") or {}).get("source_channel_name") or "")
        if not preserve_task_feedback:self.feedback.stop()
        self._dispose_section_workspace()
        self._section_drafts.clear()
        self.gate_page.reset_context()
        self.pipe_general.reset_context()
        self.pipe_segments.reset_context()
        self.section_bore_card.reset_context()
        self._pipe_key = None
        self._pipe_profile_member = None
        self._channel_profile_key = None
        self._pipe_special_key = None
        self._pipe_exact_profile = False
        self._workbench_object = None
        self.section_views.setCurrentWidget(self.section_scroll)
        self.pipe_general.restore_drafts((data.get("ui_state") or {}).get("pipe_general_drafts") or {})
        self.pipe_segments.restore_drafts((data.get("ui_state") or {}).get("pipe_special_drafts") or {})
        self.pipe_profile_editor.restore_drafts((data.get("ui_state") or {}).get("pipe_profile_drafts") or [])
        self._results_calculating = self._results_preparing = False
        self._workbench_design_stale = False
        self._result_setting_mode = ""
        self._rendered_result = None
        self.result_restore_review_button.hide()
        self._pending_workspace_state=copy.deepcopy(data.get("ui_state",{}).get("section_workspace"))
        self._connection_draft_state=copy.deepcopy(data.get("ui_state",{}).get("connection_draft"))
        self.records_toggle.setChecked(False)
        if not preserve_task_feedback:self.feedback.hide()
        self.runner.invalidate();self.map_terrain_runner.invalidate();self._restoring=True
        try:
            self._result=self._calculation=self._tin=None;self._valid=False;self._map_restore_attempt=None
            self._records=[];self._section_groups={};self._measured_assets={};self._query_view=None;self._skipped_section_message=None;self.station_spin.setValue(0.);self.section_label.clear()
            self.summary.setText("尚无计算成果");self.slider.setRange(0,0)
            if data.get("kind")!="section_workbench":
                # Direct legacy/empty opens must not retain the previous
                # project's editable geometry or terrain selection.
                self.project_id=str(uuid.uuid4());self._inputs={"networks":[],"pits":[],"excluded":[],"diagnostics":[]}
                self._source_hash=None;self._terrain_identity={};self.terrain_path.clear()
                self._terrain_processing_mode="combined"
                self.last_delivery_path=""
                self._refresh_assets()
                self._legacy_payload=data;network=data.get("network",{});old=network.get("last_result") or data.get("last_result")
                if old and old.get("method")=="exact_tin_actual_midpoint_section_integration":self.load_result(old)
                else:self._log("已保留旧工程资料；请读取当前设计成果后按新版断面法计算。")
                return
            self.project_id=data.get("project_id") or self.project_id;self._inputs=restore_inputs(data.get("workbench_inputs",{}));self._source_hash=data.get("source_project_hash")
            self._restore_section_drafts((data.get("ui_state") or {}).get("section_drafts") or [])
            self.gate_page.restore_drafts((data.get("ui_state") or {}).get("gate_drafts") or [])
            self.section_bore_card.restore_drafts((data.get("ui_state") or {}).get("trenchless_drafts") or [])
            self._terrain_identity=copy.deepcopy(data.get("terrain",{}));self.terrain_path.setText(self._terrain_identity.get("path",""));self._tin=None
            self._sync_terrain_mode(self._terrain_identity)
            self._terrain_options={"conflict_policy":"points_priority","duplicate_point_policy":"max","contour_crossing_policy":"release_conflicting_segments",**copy.deepcopy(data.get("terrain_options",{}))}
            self._restore_accuracy(data.get("settings",{}))
            self.output_directory.setText(data.get("output_directory") or str(default_delivery_root()))
            self.auto_delivery.setChecked(data.get("auto_delivery",True))
            saved_directory = data.get("last_delivery_path", "")
            self.last_delivery_path = saved_directory if self._delivery_matches_result(saved_directory, data.get("last_result")) else ""
            self._drawing_options={**DEFAULT_DRAWING_OPTIONS,**data.get("drawing_options",{})};self._legacy_payload=data.get("legacy_payload")
            if data.get("last_result"):
                self._calculated((None,data["last_result"]));self._valid=self._valid and data.get("result_status")=="READY" and not data.get("resource_issues") and data.get("valid_result",True)
                if not self.terrain_path.text() and self._result.get("terrain_deferred_reason"):
                    self._pending_terrain_path = str((data.get("ui_state") or {}).get("terrain_recovery_path") or "")
                    self._pending_terrain_note = self._result["terrain_deferred_reason"]
                # READY is a saved status, not evidence that the current draft
                # still matches the construction used by the quantity table.
                self._valid=self._valid and self._saved_inputs_match_result()
                result_accuracy=(self._result.get("inputs") or {}).get("accuracy",{})
                self._valid=self._valid and result_accuracy.get("sampling_mode")=="fixed" and result_accuracy.get("profile_step",20)==self.step.value()
                if not self._valid:
                    self.summary.setText(result_scope_prefix(self._result)+"保存的历史成果；请核对资料后重新计算。")
            else:self._refresh_assets()
            ui=data.get("ui_state",{});self.table.selectRow(min(ui.get("selected_asset",0),self.table.rowCount()-1));self.slider.setValue(ui.get("section_index",0));self.view_combo.setCurrentIndex(max(0,self.view_combo.findData(ui.get("view","section"))))
            self._restore_query_view(ui)
            result_tab = ui.get("result_tab", 0)
            if isinstance(result_tab, int) and 0 <= result_tab < self.result_tabs.count():
                self.result_tabs.setCurrentIndex(result_tab)
            step = ui.get("workflow_step", 2 if self._result else 0)
            if "result_tab" not in ui and ui.get("view") == "plan" and step == 2:
                step = 0
            self._navigate_workflow(step, prepare=False)
        finally:
            self._restoring=False;self._terrain_import_failed=False;self._refresh_workflow();self._draw()
            self._restore_workflow_editor(data.get("ui_state") or {})

    def shutdown(self,*_,**__):
        self._dispose_section_workspace()
        self._shutting_down=True;self.feedback.stop();self.runner.invalidate();self._terrain_display_pending=None
        self.terrain_display_runner.invalidate()
        self.map_terrain_runner.invalidate()
