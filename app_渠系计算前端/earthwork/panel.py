# -*- coding: utf-8 -*-
"""挖填工程量工作区，所有耗时工作使用隔离快照。"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QPlainTextEdit,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from app_渠系计算前端.task_runner import TaskRunner
from .project_state import normalize_earthwork_payload
from 土石方计算.services.construction_rules import normalize_asset_construction, validate_u_angle


_STATE_NAMES = {
    "IDLE": "待准备", "EMPTY": "尚无结果",
    "DRAFT": "待准备", "VALIDATING": "检查输入", "QUEUED": "等待 Rhino",
    "RUNNING": "正在计算", "CHECKING": "正在复核", "PREPARED": "结果待提交",
    "COMMITTING": "正在提交模型", "READY": "已完成并发布", "FAILED": "计算失败",
    "CANCELLED": "已取消", "STALE": "结果已过期", "DISCONNECTED": "Rhino 已断开",
}
_KIND_NAMES = {"open_channel": "明渠", "culvert": "暗涵", "siphon": "倒虹管", "pipe": "倒虹管", "support": "支墩 / 镇墩基础", "unsupported": "暂未支持"}
_TERMINAL_STATES = {"READY", "FAILED", "CANCELLED", "STALE", "DISCONNECTED"}
_ACTIVE_STATES = {"VALIDATING", "QUEUED", "RUNNING", "CHECKING", "PREPARED", "COMMITTING"}
_VALID_ROW_STATES = {"PASS", "PASSED", "VALID", "READY", "CHECKED"}
_SECTION_NAMES = {
    "trapezoidal_channel": "梯形明渠", "rectangular_channel": "矩形明渠",
    "u_channel": "U 形明渠", "compound_trapezoidal_channel": "复式梯形明渠",
    "circular_channel": "圆形明渠（完整圆断面非满流）",
    "circular_culvert": "圆形暗涵", "rectangular_culvert": "矩形暗涵",
    "arch_culvert": "圆拱直墙暗涵", "circular_siphon": "圆形倒虹管",
    "box_foundation": "矩形基础",
}


def _default_workspace_factory(data=None):
    from 土石方计算.services.workspace import EarthworkWorkspace
    return EarthworkWorkspace(data=data)


def _source_hash(data: dict) -> str:
    """只关注设计来源，报告姓名等修改不使工程量过期。"""
    relevant = {key: data.get(key) for key in (
        "merged_panel", "water_profile_panel", "siphon_manager_data",
        "open_channel_panel", "culvert_panel", "siphon_panel",
    )}
    text = json.dumps(relevant, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _station_label(value):
    """显示桩号只取三位小数，完整数值保留在数据及提示中。"""
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return "未指定"
    sign = "−" if value < 0 else ""
    millimetres = round(abs(float(value)) * 1000)
    kilometres, remainder = divmod(millimetres, 1000000)
    return f"{sign}{kilometres}+{remainder / 1000:07.3f}"


def _asset_status_label(asset, state, rows):
    """按当前任务和该建筑物的全部成果行判断，历史成功不能覆盖本次失败。"""
    if not asset.get("enabled", True):
        return "未纳入计算"
    job_state = state.get("job_state")
    if job_state == "FAILED":
        return "计算失败"
    if job_state in _ACTIVE_STATES or job_state == "CANCELLED":
        return _STATE_NAMES[job_state]
    if not rows:
        return "待计算"
    result_state = state.get("result_status")
    if result_state == "STALE" or job_state == "STALE":
        return "待重算"
    if result_state == "MISSING":
        return "结果失效"
    if result_state == "DISCONNECTED" or job_state == "DISCONNECTED":
        return "待核对（未连接）"
    validations = {str(row.get("validation_status", "")).upper() for row in rows}
    if validations & {"FAIL", "FAILED", "INVALID", "ERROR"}:
        return "核验失败"
    if result_state == "READY" and validations <= _VALID_ROW_STATES:
        return "有效"
    return "待核验"


def plugin_locations():
    """同时识别源码目录及冻结程序随包资源。"""
    root = Path(__file__).resolve().parents[2]
    bases = [Path(getattr(sys, "_MEIPASS", root)), Path(sys.executable).resolve().parent, root]
    directories = [base / "integrations" / "rhino8" for base in bases]
    plugins = [folder / name for folder in directories for name in
               ("QxEarthwork.Rhino8.rhp", "grasshopper/build/QxEarthwork.Rhino8.rhp", "build/QxEarthwork.Rhino8.rhp")]
    plugins.append(Path(os.environ.get("APPDATA", "")) / "QxEarthwork/Rhino8/QxEarthwork.Rhino8.rhp")
    readmes = [folder / "README.zh-CN.md" for folder in directories]
    return next((path for path in plugins if path.is_file()), None), next((path for path in readmes if path.is_file()), None)


def _installed_workbench_plugin(plugin):
    """已安装时统一从 GH 标准目录加载，避免 Rhino 将开发目录加入 GHA 搜索。"""
    plugin = Path(plugin)
    installed = Path(os.environ.get("APPDATA", "")) / "Grasshopper/Libraries/QxEarthwork/QxEarthwork.Rhino8.rhp"
    engine = installed.with_name("QxEarthwork.Grasshopper.gha")
    if not installed.is_file() and not engine.is_file():
        return plugin
    if not installed.is_file() or not engine.is_file():
        raise ValueError("挖填工作台标准安装不完整，请重新安装当前完整工具包。")
    expected_manifest = plugin.with_name("grasshopper-manifest.json")
    installed_manifest = installed.with_name("grasshopper-manifest.json")
    if not expected_manifest.is_file() or not installed_manifest.is_file():
        raise ValueError("挖填工作台缺少版本清单，请重新安装当前完整工具包。")
    expected = json.loads(expected_manifest.read_text(encoding="utf-8-sig"))
    actual = json.loads(installed_manifest.read_text(encoding="utf-8-sig"))
    plugin_digest = hashlib.sha256(plugin.read_bytes()).hexdigest()
    installed_digest = hashlib.sha256(installed.read_bytes()).hexdigest()
    engine_digest = hashlib.sha256(engine.read_bytes()).hexdigest()
    if (plugin_digest != installed_digest or actual.get("plugin_sha256") != installed_digest
            or actual.get("gha_sha256") != engine_digest or expected.get("gha_sha256") != engine_digest):
        raise ValueError("已安装的挖填工作台与当前程序版本不一致，请关闭 Rhino 后重新安装当前完整工具包。")
    return installed


class StagedSlopeDialog(QDialog):
    """按左右侧逐级录入实际施工放坡和马道。"""

    def __init__(self, construction, parent=None):
        super().__init__(parent)
        self.setWindowTitle("分级开挖边坡与马道")
        self.resize(640, 440)
        self.stages = copy.deepcopy(construction)
        layout = QVBoxLayout(self)
        note = QLabel("每侧按坡脚向外的顺序填写；末级继续延伸至地面交点。未填写某侧时，沿用该侧单一开挖坡比。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["左右侧", "级高(m)", "坡比(水平/竖直)", "马道宽(m)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)
        for side, key in (("左", "excavation_stages_left"), ("右", "excavation_stages_right")):
            for stage in construction.get(key, []):
                self.add_stage(side, stage)
        buttons_row = QHBoxLayout()
        for side in ("左", "右"):
            button = QPushButton("增加" + side + "侧一级")
            button.clicked.connect(lambda _checked=False, side=side: self.add_stage(side))
            buttons_row.addWidget(button)
        remove = QPushButton("删除选中级")
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()) if self.table.currentRow() >= 0 else None)
        buttons_row.addWidget(remove)
        layout.addLayout(buttons_row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存分级边坡")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_stage(self, side, stage=None):
        stage = stage or {"height": 1.0, "slope": 0.5, "berm_width": 0.0}
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, value in enumerate((side, stage.get("height"), stage.get("slope"), stage.get("berm_width", 0))):
            item = QTableWidgetItem(str(value))
            if column == 0:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, column, item)

    def accept(self):
        result = {"excavation_stages_left": [], "excavation_stages_right": []}
        try:
            for row in range(self.table.rowCount()):
                side = self.table.item(row, 0).text()
                values = [float(self.table.item(row, column).text()) for column in (1, 2, 3)]
                if any(not math.isfinite(value) or value < 0 for value in values) or values[0] <= 0:
                    raise ValueError("级高必须为正数，坡比和马道宽必须为有限非负数")
                result["excavation_stages_left" if side == "左" else "excavation_stages_right"].append(
                    dict(zip(("height", "slope", "berm_width"), values)))
        except ValueError as exc:
            QMessageBox.warning(self, "分级边坡参数无效", str(exc))
            return
        self.stages = result
        super().accept()


class ParameterDialog(QDialog):
    """以中文字段编辑已有模板参数，不让普通操作依赖 JSON。"""

    # 路径与单位明确列示，缺省值只用于编辑展示，不自动写入工程。
    FIELDS = (
        ("section.inner_width", "净底宽", "m"),
        ("section.inner_height", "净高 / 结构总高", "m"),
        ("section.inner_side_slope", "内边坡水平比", ""),
        ("section.inner_radius", "内半径", "m"),
        ("section.u_arc_angle_degrees", "U形底圆弧圆心角 θ", "°"),
        ("section.u_side_angle_degrees", "U形直墙外倾角 α（相对竖直）", "°"),
        ("section.inner_diameter", "水力内径", "m"),
        ("section.wall_thickness", "侧墙 / 衬砌 / 管壁厚度", "m"),
        ("section.base_thickness", "底板厚度", "m"),
        ("section.roof_thickness", "顶板 / 拱圈厚度", "m"),
        ("section.wall_height", "拱涵直墙高度", "m"),
        ("section.arch_angle_degrees", "拱涵圆拱角度", "°"),
        ("section.pipe_count", "并行管数", "根"),
        ("section.pipe_spacing", "管间净距", "m"),
        ("section.compound_lower_height", "复式下层高度", "m"),
        ("section.compound_bench_width", "复式平台宽度", "m"),
        ("section.compound_upper_slope", "复式上层边坡水平比", ""),
        ("section.compound_lower_slope", "复式下层边坡水平比", ""),
        ("section.compound_right_slope", "复式右侧边坡水平比", ""),
        ("section.foundation_width", "支墩 / 镇墩基础宽度", "m"),
        ("section.foundation_height", "支墩 / 镇墩基础高度", "m"),
        ("construction.bedding_thickness", "垫层厚度", "m"),
        ("construction.bedding_extension", "垫层每侧外伸宽度", "m"),
        ("construction.working_space_left", "左侧施工工作面", "m"),
        ("construction.working_space_right", "右侧施工工作面", "m"),
        ("construction.excavation_slope_left", "左开挖边坡水平比", ""),
        ("construction.excavation_slope_right", "右开挖边坡水平比", ""),
        ("construction.bank_top_width_left", "左渠堤顶宽", "m"),
        ("construction.bank_top_width_right", "右渠堤顶宽", "m"),
        ("construction.bank_slope_left", "左渠堤外边坡水平比", ""),
        ("construction.bank_slope_right", "右渠堤外边坡水平比", ""),
    )

    def __init__(self, asset, parent=None):
        super().__init__(parent)
        self.setWindowTitle("施工参数 · " + str(asset.get("name", "建筑物")))
        self.resize(540, 520)
        self.asset = copy.deepcopy(asset)
        asset = copy.deepcopy(asset)
        normalize_asset_construction(asset)
        self._staged_slopes = {key: copy.deepcopy(asset.get("construction", {}).get(key, []))
                               for key in ("excavation_stages_left", "excavation_stages_right")}
        layout = QVBoxLayout(self)
        notice = QLabel("空白表示未提供。长度单位为米，角度单位为度；坡比填写每 1 米竖向高度对应的水平距离。"
                        "U形缺省为底圆弧180°、直墙外倾0°。")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        form = QFormLayout()
        self.enabled = QCheckBox("纳入本次计算")
        self.enabled.setChecked(asset.get("enabled", True))
        self.section_type = QComboBox()
        for key, label in _SECTION_NAMES.items():
            self.section_type.addItem(label, key)
        if self.section_type.findData(asset.get("section_type")) < 0:
            self.section_type.addItem("未支持 / 保留原记录", asset.get("section_type", "unsupported"))
        self.section_type.setCurrentIndex(self.section_type.findData(asset.get("section_type", "unsupported")))
        self.target_mode = QComboBox()
        for label, mode in (("保持原地形并形成渠堤", "union_terrain"), ("恢复至原地面", "restore_terrain"), ("已提供明确设计地面", "finished_profile")):
            self.target_mode.addItem(label, mode)
        target_mode = asset.get("construction", {}).get("target_mode") or ("union_terrain" if asset.get("kind") == "open_channel" else "restore_terrain")
        self.target_mode.setCurrentIndex(max(0, self.target_mode.findData(target_mode)))
        form.addRow("参与计算", self.enabled)
        form.addRow("施工断面", self.section_type)
        form.addRow("最终土体", self.target_mode)
        self.installation_mode = QComboBox()
        for label, mode in (("埋地管沟", "buried"), ("明管（基础另列）", "exposed"), ("架空管（基础另列）", "elevated")):
            self.installation_mode.addItem(label, mode)
        self.installation_mode.setCurrentIndex(max(0, self.installation_mode.findData(asset.get("construction", {}).get("installation_mode", "buried"))))
        form.addRow("管道施工形式", self.installation_mode)
        layout.addLayout(form)
        self.table = QTableWidget(len(self.FIELDS), 3)
        self.table.setHorizontalHeaderLabels(["工程参数", "数值", "单位"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for row, (path, name, unit) in enumerate(self.FIELDS):
            group, key = path.split(".")
            value = asset.get(group, {}).get(key)
            if asset.get("section_type") == "u_channel" and value is None:
                value = {"u_arc_angle_degrees": 180.0, "u_side_angle_degrees": 0.0}.get(key)
            for column, label in ((0, name), (2, unit)):
                item = QTableWidgetItem(label)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, column, item)
            self.table.setItem(row, 1, QTableWidgetItem("" if value is None else str(value)))
        def update_bedding_rows():
            for row,(path,_name,_unit) in enumerate(self.FIELDS):
                if path in {"construction.bedding_thickness","construction.bedding_extension"}:
                    self.table.setRowHidden(row,self.section_type.currentData()=="u_channel")
        self.section_type.currentIndexChanged.connect(update_bedding_rows)
        update_bedding_rows()
        layout.addWidget(self.table)
        slopes_button = QPushButton("设置左右分级开挖边坡与马道")
        slopes_button.clicked.connect(self.edit_staged_slopes)
        layout.addWidget(slopes_button)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存参数")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def edit_staged_slopes(self):
        dialog = StagedSlopeDialog(self._staged_slopes, self)
        if dialog.exec() == QDialog.Accepted:
            self._staged_slopes = dialog.stages

    def accept(self):
        try:
            candidate = copy.deepcopy(self.asset)
            for row, (path, _name, _unit) in enumerate(self.FIELDS):
                group, key = path.split(".")
                raw = self.table.item(row, 1).text().strip()
                if raw:
                    value = float(raw)
                    if not 0 <= value < float("inf"):
                        raise ValueError(f"{_name} 必须为有限非负数")
                    if key == "pipe_count":
                        if not value.is_integer() or value < 1:
                            raise ValueError("并行管数必须为正整数")
                        value = int(value)
                    candidate.setdefault(group, {})[key] = value
                else:
                    candidate.setdefault(group, {}).pop(key, None)
            candidate["parameter_source"] = "用户编辑"
            candidate["enabled"] = self.enabled.isChecked()
            candidate["section_type"] = self.section_type.currentData()
            if candidate["section_type"] == "u_channel":
                section = candidate.get("section", {})
                validate_u_angle("section.u_arc_angle_degrees", section.get("u_arc_angle_degrees", 180.0))
                validate_u_angle("section.u_side_angle_degrees", section.get("u_side_angle_degrees", 0.0))
            if candidate["section_type"] in _SECTION_NAMES:
                candidate["kind"] = ("support" if candidate["section_type"] == "box_foundation" else
                                     "open_channel" if candidate["section_type"].endswith("channel") else
                                     "siphon" if candidate["section_type"].endswith("siphon") else "culvert")
            candidate.setdefault("construction", {})["target_mode"] = self.target_mode.currentData()
            candidate["construction"]["installation_mode"] = self.installation_mode.currentData()
            for key, stages in self._staged_slopes.items():
                if stages:
                    candidate["construction"][key] = copy.deepcopy(stages)
                else:
                    candidate["construction"].pop(key, None)
            candidate.pop("geometry_sections", None)
            normalize_asset_construction(candidate)
            self.asset = candidate
        except ValueError as exc:
            QMessageBox.warning(self, "参数无效", str(exc))
            return
        super().accept()


class TestProfileDialog(QDialog):
    """把验收假定展示为可编辑测试参数，并保留原始资料。"""

    def __init__(self, has_selection, parent=None):
        super().__init__(parent)
        self.setWindowTitle("应用测试纵断面与施工参数")
        self.resize(590, 410)
        layout = QVBoxLayout(self)
        description = QLabel(
            "只用于软件验收。原始坐标与原始资料保留，测试高程将沿真实地形采样生成。\n"
            "默认测试壁厚、底板、顶板均为 0.20 m；左右工作面各 0.50 m；"
            "开挖坡比均为 0.50；垫层厚 0.15 m、每侧外伸 0.20 m；"
            "明渠两侧堤顶宽 0.50 m、外坡比 1.50。"
            "原资料已有的内部尺寸优先保留，缺失尺寸采用模板明确记录的测试值。"
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        self.scope = QComboBox()
        self.scope.addItem("全部已启用区段", "all")
        if has_selection:
            self.scope.addItem("仅选中区段", "selected")
        form.addRow("应用范围", self.scope)
        self.replacement = QComboBox()
        self.replacement.addItem("保留原断面类型", None)
        for kind in ("rectangular_channel", "trapezoidal_channel", "rectangular_culvert", "circular_siphon"):
            self.replacement.addItem("明确改为测试" + _SECTION_NAMES[kind], kind)
        form.addRow("测试断面", self.replacement)
        self.cover = QDoubleSpinBox()
        self.cover.setRange(0, 100)
        self.cover.setDecimals(3)
        self.cover.setValue(1.0)
        self.cover.setSuffix(" m")
        self.channel_depth = QDoubleSpinBox()
        self.channel_depth.setRange(-50, 100)
        self.channel_depth.setDecimals(3)
        self.channel_depth.setValue(0.8)
        self.channel_depth.setSuffix(" m")
        form.addRow("管涵测试覆土厚度", self.cover)
        form.addRow("明渠底低于地面深度", self.channel_depth)
        layout.addLayout(form)
        notice = QLabel("沿线原交点折线仅作为本次测试线路；原曲线要素仍保存在来源中。负的明渠埋深表示测试填方段。")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("按真实地形生成测试参数")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class EarthworkPanel(QWidget):
    """工程保存、Rhino 会话及可核查模型数量的统一入口。"""

    data_changed = Signal()

    def __init__(self, parent=None, *, project_provider=None, session_provider=None, workspace_factory=None):
        super().__init__(parent)
        self.setObjectName("earthworkPanel")
        self._project_provider = project_provider
        self._session_provider = session_provider
        self._workspace_factory = workspace_factory or _default_workspace_factory
        self.workspace = self._workspace_factory()
        self.calculation_runner = TaskRunner(self)
        self._restoring = False
        self._last_event = 0
        self._last_result_id = None
        self._last_terrain_hash = None
        self._last_seen_session_revision = None
        self._current_job = None
        self._discovery_path = None
        self._rhino_process = None
        self._pending_test_profile = None
        self._pending_axis = None
        self._result_rows = []
        self._local_task_label = ""
        self._selection_from_rhino = False
        self._build_ui()
        self.calculation_runner.running_changed.connect(self._set_busy)
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._poll_status)
        self._timer.start()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)
        self._refresh_assets()
        self._poll_status()

    def _button(self, text, callback, layout):
        button = QPushButton(text)
        button.clicked.connect(lambda: self._guard(callback))
        layout.addWidget(button)
        return button

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.calculation_tabs = QTabWidget(self)
        outer.addWidget(self.calculation_tabs)
        from .independent_panel import IndependentEarthworkPanel
        self.independent_panel = IndependentEarthworkPanel(
            terrain_provider=lambda: copy.deepcopy(self.workspace.data.get("terrain")),
            assets_provider=lambda: copy.deepcopy(self.workspace.data.get("assets", [])))
        self.independent_panel.data_changed.connect(self._emit_changed)
        self.calculation_tabs.addTab(self.independent_panel, "独立算量")
        native_page = QWidget()
        self.calculation_tabs.addTab(native_page, "Rhino 地形与三维检查")
        from .network_panel import NetworkEarthworkPanel
        self.network_panel = NetworkEarthworkPanel()
        self.network_panel.data_changed.connect(self._emit_changed)
        self.calculation_tabs.addTab(self.network_panel, "全线与多结构")
        layout = QVBoxLayout(native_page)
        layout.setContentsMargins(20, 16, 20, 16)
        title = QLabel("挖填工程量 · Rhino 8 联动")
        title.setStyleSheet("font-size: 21px; font-weight: 600; color: #17365D;")
        layout.addWidget(title)
        subtitle = QLabel("地形与线路 → 施工参数 → 挖填计算 → 模型查看与成果。天然挖方和成型填方分别统计。")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        connection = QGroupBox("1　地形与设计来源")
        source_layout = QVBoxLayout(connection)
        row = QHBoxLayout()
        self.connect_button = self._button("连接 Rhino 8", self.start_bridge, row)
        self._button("插件安装说明", self.show_plugin_help, row)
        self._button("打开 Rhino 挖填工作台", self.open_rhino_workbench, row)
        self.select_terrain_button = self._button("在 Rhino 选取地形", self.select_terrain, row)
        self.import_terrain_button = self._button("导入 DWG / DXF 地形", self.import_terrain, row)
        source_layout.addLayout(row)
        terrain_note = QLabel("点云建网时自动识别测量范围，剔除异常长的跨接三角面；明显异常高程按邻近地形筛查，处理记录随工程保存。")
        terrain_note.setWordWrap(True)
        source_layout.addWidget(terrain_note)
        row = QHBoxLayout()
        self.import_excel_button = self._button("导入线路 Excel", self.import_excel, row)
        self.import_project_button = self._button("读取当前水面线与倒虹吸", self.import_current_project, row)
        self.import_package_button = self._button("导入挖填工程数据", self.import_workspace, row)
        source_layout.addLayout(row)
        self.connection_label = QLabel("Rhino 尚未连接；可以先准备建筑物与施工参数。")
        self.connection_label.setWordWrap(True)
        self.terrain_label = QLabel("地形：未指定")
        self.terrain_label.setWordWrap(True)
        source_layout.addWidget(self.connection_label)
        source_layout.addWidget(self.terrain_label)
        self.domain_label = QLabel("计算封闭辅助面：接收地形和设计高程后自动生成，不作为设计高程。")
        self.domain_label.setWordWrap(True)
        source_layout.addWidget(self.domain_label)
        layout.addWidget(connection)

        splitter = QSplitter(Qt.Vertical)
        assets_group = QGroupBox("2　建筑物与施工参数")
        assets_layout = QVBoxLayout(assets_group)
        self.asset_table = QTableWidget(0, 6)
        self.asset_table.setObjectName("earthworkAssets")
        self.asset_table.setHorizontalHeaderLabels(["建筑物", "类型", "起止桩号", "断面", "参数来源", "状态"])
        self.asset_table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.asset_table.horizontalHeader().setMinimumSectionSize(90)
        self.asset_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.asset_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in enumerate((210, 95, 225, 145, 215, 135)):
            self.asset_table.setColumnWidth(column, width)
        self.asset_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.asset_table.setSelectionMode(QTableWidget.SingleSelection)
        self.asset_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.asset_table.doubleClicked.connect(lambda: self._guard(self.edit_parameters))
        assets_layout.addWidget(self.asset_table)
        row = QHBoxLayout()
        self.edit_button = self._button("编辑选中段施工参数", self.edit_parameters, row)
        self.bind_axis_button = self._button("绑定 Rhino 空间轴线", self.bind_native_axis, row)
        self.test_button = self._button("明确应用测试纵断面与参数", self.apply_test_parameters, row)
        row.addStretch()
        assets_layout.addLayout(row)
        splitter.addWidget(assets_group)

        results_group = QGroupBox("3　挖填数量与三维模型")
        results_layout = QVBoxLayout(results_group)
        row = QHBoxLayout()
        self.calculate_button = self._button("计算并更新模型", self.start_calculation, row)
        self.cancel_button = self._button("取消计算", self.cancel_calculation, row)
        self.cancel_button.setEnabled(False)
        self.state_label = QLabel("待准备")
        row.addWidget(self.state_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        row.addWidget(self.progress, 1)
        results_layout.addLayout(row)
        self.result_table = QTableWidget(0, 7)
        self.result_table.setObjectName("earthworkResults")
        self.result_table.setHorizontalHeaderLabels(["建筑物 / 区段", "挖方 m³", "周边回填 m³", "新增填筑 m³", "总填方 m³", "状态", "复核信息"])
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.result_table.setSelectionMode(QTableWidget.SingleSelection)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.result_table.horizontalHeader().setMinimumSectionSize(105)
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in enumerate((235, 130, 155, 155, 145, 135, 250)):
            self.result_table.setColumnWidth(column, width)
        self.result_table.itemSelectionChanged.connect(self._select_result)
        results_layout.addWidget(self.result_table)
        self.totals_label = QLabel("尚无已发布工程量。未计算和失败区段不会按零统计。")
        self.totals_label.setWordWrap(True)
        results_layout.addWidget(self.totals_label)
        row = QHBoxLayout()
        self.stage_combo = QComboBox()
        for label, role in (("全部模型", "all"), ("原地形", "terrain"), ("永久结构", "structure"), ("挖方体", "cut"), ("周边回填体", "backfill"), ("新增填筑体", "embankment")):
            self.stage_combo.addItem(label, role)
        row.addWidget(self.stage_combo)
        self._button("显示阶段", self.show_stage, row)
        self.station_spin = QDoubleSpinBox()
        self.station_spin.setRange(-1e9, 1e9)
        self.station_spin.setDecimals(3)
        self.station_spin.setSuffix(" m")
        row.addWidget(QLabel("剖切桩号"))
        row.addWidget(self.station_spin)
        self._button("按桩号剖切", self.show_section, row)
        self.export_package_button = self._button("导出完整工程包", self.export_package, row)
        results_layout.addLayout(row)
        row = QHBoxLayout()
        self.export_table_button = self._button("导出 Excel / CSV 量表", self.export_quantities, row)
        self.export_dxf_button = self._button("由 Rhino 导出三维模型 DXF", self.export_model_dxf, row)
        row.addStretch()
        results_layout.addLayout(row)
        self.model_path_label = QLabel("三维模型：尚无已发布文件")
        self.model_path_label.setWordWrap(True)
        self.model_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        results_layout.addWidget(self.model_path_label)
        splitter.addWidget(results_group)
        splitter.setSizes([230, 320])
        layout.addWidget(splitter, 1)
        self.message_box = QPlainTextEdit()
        self.message_box.setReadOnly(True)
        self.message_box.setMaximumHeight(100)
        self.message_box.setPlaceholderText("地形覆盖、参数缺项、施工冲突和模型核验信息在此显示。")
        layout.addWidget(self.message_box)

    def _guard(self, callback):
        try:
            return callback()
        except Exception as exc:
            self._log(str(exc))
            QMessageBox.warning(self, "挖填工程量", str(exc))
            return None

    def _log(self, message):
        if message:
            self.message_box.appendPlainText(str(message))
            self.message_box.document().setMaximumBlockCount(500)

    def _emit_changed(self):
        if not self._restoring:
            self.data_changed.emit()
        session = self._session_provider() if self._session_provider else None
        self._last_seen_session_revision = getattr(session, "revision", None)

    def _set_busy(self, busy):
        for button in (self.calculate_button, self.import_excel_button, self.import_project_button,
                       self.import_package_button, self.edit_button, self.test_button,
                       self.select_terrain_button, self.import_terrain_button,
                       self.export_table_button, self.export_dxf_button, self.bind_axis_button,
                       self.export_package_button):
            button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    def _refresh_assets(self):
        assets = self.workspace.data.get("assets", [])
        selected = self.selected_asset_id()
        self.asset_table.setRowCount(len(assets))
        for row, asset in enumerate(assets):
            source = "测试参数（不作为工程设计）" if asset.get("test_only") or asset.get("is_test") else asset.get("parameter_source", "原始资料 / 待补齐")
            name = str(asset.get("name") or "").strip() or f"{_SECTION_NAMES.get(asset.get('section_type'), '建筑物')} · 段 {row + 1}"
            values = [name, _KIND_NAMES.get(asset.get("kind"), "暂未支持"),
                      f"{_station_label(asset.get('station_start'))} ～ {_station_label(asset.get('station_end'))}",
                      _SECTION_NAMES.get(asset.get("section_type"), "未支持"), source,
                      ""]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, asset.get("asset_id"))
                    item.setToolTip(str(asset.get("asset_id", "")))
                if column == 2:
                    item.setToolTip(f"原始起点：{asset.get('station_start')!r}\n原始终点：{asset.get('station_end')!r}")
                self.asset_table.setItem(row, column, item)
            if asset.get("asset_id") == selected:
                self.asset_table.selectRow(row)
        self._refresh_asset_statuses()

    def _refresh_asset_statuses(self, state=None):
        """轮询只更新状态列，不重建表格或改变当前选中建筑物。"""
        state = dict(self.workspace.status() if state is None else state)
        state.setdefault("result_status", self.workspace.data.get("result_status", "EMPTY"))
        result = state.get("result") or self.workspace.data.get("last_result") or {}
        rows_by_asset = {}
        for item in result.get("rows", []):
            identities = set(item.get("participants") or [])
            if item.get("asset_id"):
                identities.add(item["asset_id"])
            for identity in identities:
                rows_by_asset.setdefault(identity, []).append(item)
        assets = {item.get("asset_id"): item for item in self.workspace.data.get("assets", [])}
        for row in range(self.asset_table.rowCount()):
            identity = self.asset_table.item(row, 0).data(Qt.UserRole)
            label = _asset_status_label(assets.get(identity, {}), state, rows_by_asset.get(identity, []))
            item = self.asset_table.item(row, 5)
            if item.text() != label:
                item.setText(label)

    def selected_asset_id(self):
        row = self.asset_table.currentRow()
        item = self.asset_table.item(row, 0) if row >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def set_assets(self, assets):
        self.workspace.set_assets(copy.deepcopy(assets))
        self._update_domain_preview()
        self._refresh_assets()
        self._emit_changed()

    def start_bridge(self):
        path = self.workspace.start_bridge()
        self._discovery_path = str(path)
        self.connection_label.setText("连接已准备。点击“打开 Rhino 挖填工作台”，或在 Rhino 运行 QxEarthwork 自动连接。")
        self._log("当前工程已准备好本机连接，可在主程序或 Rhino 中文工作台操作。")
        return path

    def open_rhino_workbench(self):
        if self.workspace.status().get("connected"):
            self.workspace.bridge.enqueue("open_workbench", {})
            return
        if self._rhino_process is not None and self._rhino_process.poll() is None:
            self.start_bridge()
            self._log("Rhino 窗口已启动。请在该窗口的挖填工作台连接主程序；工作台关闭时可运行 QxEarthwork 重新打开。")
            return
        plugin, _readme = plugin_locations()
        if not plugin:
            raise ValueError("未找到挖填工作台插件，请先安装完整插件包。")
        plugin = _installed_workbench_plugin(plugin)
        candidates = []
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\McNeel\Rhinoceros\8.0\Install") as key:
                folder = winreg.QueryValueEx(key, "Path")[0]
                candidates.extend([Path(folder) / "Rhino.exe", Path(folder) / "System/Rhino.exe"])
        except (ImportError, OSError):
            pass
        candidates.extend([Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Rhino 8/System/Rhino.exe",
                           Path(r"F:\Program Files\Rhino 8\System\Rhino.exe")])
        executable = next((path for path in candidates if path.is_file()), None)
        if executable is None:
            raise ValueError("未找到 Rhino 8。请安装后重试，或在已有 Rhino 中运行 QxEarthwork。")
        discovery = self.start_bridge()
        # 通过 Rhino 自带 Python 调用真实插件加载接口，避免依赖未注册的加载命令。
        bootstrap = self.workspace.resource_root / "session" / "open-workbench.py"
        bootstrap.parent.mkdir(parents=True, exist_ok=True)
        bootstrap_log = bootstrap.with_suffix(".log")
        bootstrap.write_text(
            "# -*- coding: utf-8 -*-\nimport io\n"
            "_log = io.open(u" + json.dumps(str(bootstrap_log)) + ", 'w', encoding='utf-8')\n"
            "try:\n"
            "    _log.write(u'bootstrap_started\\n')\n    _log.flush()\n"
            "    import Rhino\n    import System\n    import clr\n"
            "    plugin_id = clr.Reference[System.Guid]()\n"
            "    loaded = Rhino.PlugIns.PlugIn.LoadPlugIn(u" + json.dumps(str(plugin)) + ", plugin_id)\n"
            "    _log.write(u'plugin_loaded=' + str(loaded) + u'\\n')\n    _log.flush()\n"
            "    if loaded not in (Rhino.PlugIns.LoadPlugInResult.Success, Rhino.PlugIns.LoadPlugInResult.SuccessAlreadyLoaded):\n"
            "        raise RuntimeError('Rhino workbench plugin could not load: ' + str(loaded))\n"
            "    opened = Rhino.RhinoApp.RunScript(u" + json.dumps(f'_QxEarthworkConnect "{discovery}"') + ", False)\n"
            "    _log.write(u'workbench_opened=' + str(opened) + u'\\n')\n    _log.flush()\n"
            "    if not opened:\n        raise RuntimeError('Rhino workbench command could not start')\n"
            "except Exception as error:\n"
            "    _log.write(u'bootstrap_error=' + type(error).__name__ + u'\\n')\n    _log.flush()\n    raise\n"
            "finally:\n    _log.close()\n",
            encoding="utf-8")
        macro = f'-_RunPythonScript ({bootstrap})'
        # Rhino 自行解析原始命令行，必须只给 /runscript 的值加引号；列表形式会把整个参数包住。
        command_line = subprocess.list2cmdline([str(executable), "/nosplash", "/notemplate", "/netfx"])
        command_line += f' /runscript="{macro}"'
        self._rhino_process = subprocess.Popen(command_line, executable=str(executable), shell=False)
        self._log("正在打开 Rhino 挖填工作台，连接就绪后可选择地形和建筑物轴线。")

    def show_plugin_help(self):
        plugin, readme = plugin_locations()
        if readme:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(readme)))
        if plugin:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(plugin.parent)))
            self._log(f"插件文件：{plugin}\n安装后通过“打开 Rhino 挖填工作台”进入，Rhino 内也可运行 QxEarthwork。")
        else:
            self._log("尚未找到随包 Rhino 插件。请完成 integrations/rhino8 的插件构建或使用包含插件的发行包。")

    def _update_domain_preview(self):
        terrain = self.workspace.data.get("terrain") or {}
        bounds = terrain.get("bounds")
        if not bounds or len(bounds) != 2 or any(len(point) != 3 for point in bounds):
            return
        derive = getattr(self.workspace, "_complete_calculation_domain", None)
        if derive is None:
            return
        settings = copy.deepcopy(self.workspace.data.get("settings") or {})
        automatic = settings.get("domain_auto", "base_z" not in settings and "clip_top_z" not in settings)
        if automatic:
            settings.pop("base_z", None)
            settings.pop("clip_top_z", None)
        snapshot = {"assets": copy.deepcopy(self.workspace.data.get("assets", [])), "settings": settings}
        derive(snapshot, bounds)
        settings["domain_auto"] = bool(automatic)
        self.workspace.data["settings"] = settings
        self.domain_label.setText(
            f"计算封闭辅助面：底高程 {settings['base_z']:.3f} m，顶高程 {settings['clip_top_z']:.3f} m"
            + ("（随地形与结构范围自动更新，不是设计高程）" if automatic else "（工程指定的计算范围）"))

    def bind_native_axis(self):
        identity = self.selected_asset_id()
        asset = next((item for item in self.workspace.data.get("assets", []) if item.get("asset_id") == identity), None)
        if asset is None:
            raise ValueError("请先选择要绑定空间轴线的建筑物")
        if not self.workspace.status().get("connected"):
            raise ValueError("请先连接 Rhino 文档")
        settings = self.workspace.data.get("settings", {})
        self._pending_axis = {"asset_id": identity, "asset": copy.deepcopy(asset)}
        reference = "pipe_axis" if asset.get("kind") == "siphon" or asset.get("section_type") == "circular_culvert" else "inner_invert"
        self.workspace.bridge.enqueue("axis_select", {
            "asset_id": identity, "station_start": asset.get("station_start", 0),
            "sample_spacing": settings.get("section_max_spacing", settings.get("section_interval", 10)),
            "chord_tolerance": settings.get("curve_chord_tolerance", 0.01),
            "elevation_reference": reference,
        })
        self._log("请在 Rhino 选择真实三维" + ("管轴线" if reference == "pipe_axis" else "渠道 / 涵洞内底线") + "；确认后保留原资料并绑定原生曲线。")

    def _handle_workbench_action(self, event):
        """Rhino 工作台共用主程序的来源校验、快照任务和编辑入口。"""
        action = event.get("action")
        data = event.get("data") or {}
        if action in ("axis", "select"):
            identity = data.get("asset_id")
            for row in range(self.asset_table.rowCount()):
                if self.asset_table.item(row, 0).data(Qt.UserRole) == identity:
                    self.asset_table.selectRow(row)
                    break
            else:
                raise ValueError("所选建筑物已改变，请在 Rhino 工作台重新选择。")
        handlers = {
            "terrain": self.select_terrain, "axis": self.bind_native_axis,
            "calculate": self.start_calculation, "cancel": self.cancel_calculation,
            "show_stage": lambda: self.workspace.show_stage(data["role"]),
            "select": lambda: self.workspace.select(data["asset_id"]),
            "section": lambda: self.workspace.section(data["station"], data.get("asset_id")),
        }
        if action not in handlers:
            raise ValueError("未知工作台操作")
        handlers[action]()

    def _apply_native_axis(self, event):
        identity = event.get("asset_id")
        pending = self._pending_axis
        if event.get("source") == "grasshopper":
            # GH按钮也是显式绑定入口；只接受构造原生曲线期间未变更的工程与设计。
            if (event.get("expected_design_revision") != self.workspace.data.get("revisions", {}).get("design", 0)
                    or event.get("expected_project_generation") != self.workspace.data.get("project_generation", 0)):
                raise ValueError("轴线生成期间工程或建筑物已修改，请重新绑定轴线。")
            current = next((item for item in self.workspace.data.get("assets", [])
                            if item.get("asset_id") == identity), None)
            if current is None:
                raise ValueError("轴线对应的建筑物不存在，请重新选择建筑物后绑定轴线。")
            pending = {"asset_id": identity, "asset": copy.deepcopy(current)}
        if not pending or pending["asset_id"] != identity:
            return
        self._pending_axis = None
        assets = copy.deepcopy(self.workspace.data.get("assets", []))
        index = next((i for i, item in enumerate(assets) if item.get("asset_id") == identity), None)
        if index is None or assets[index] != pending["asset"]:
            raise ValueError("选择原生轴线期间建筑物已修改，请重新绑定")
        alignment = copy.deepcopy(event.get("alignment") or {})
        if alignment.get("elevation_reference") not in ("pipe_axis", "inner_invert"):
            raise ValueError("Rhino 轴线缺少明确的管轴 / 内底高程基准")
        curve_path = alignment.get("native_curve_path") or alignment.get("native_axis_path")
        curve_hash = alignment.get("native_curve_sha256") or alignment.get("native_axis_sha256")
        if not alignment.get("native_samples") or not curve_path or not curve_hash:
            raise ValueError("Rhino 原生轴线缺少采样或原生资源，未修改建筑物")
        item = assets[index]
        item.setdefault("original_fields", {}).setdefault("alignment_before_rhino", copy.deepcopy(item.get("alignment", {})))
        item.setdefault("alignment", {}).update(alignment)
        item["geometry_sections"] = []
        native = alignment["native_samples"]
        item["station_start"] = native[0]["station"]
        item["station_end"] = native[-1]["station"]
        item["parameter_source"] = "Rhino 原生空间轴线"
        self.set_assets(assets)
        self._log("已绑定真实 Rhino 空间轴线，旧几何已失效；施工参数仍须完整。")

    def select_terrain(self):
        self.workspace.request_terrain(automatic_boundary=True, boundary_gap_factor=4.0,
                                       filter_elevation_outliers=True, meshing_method="meshpatch_points")
        self._log("请在 Rhino 中选取真实高程点、等高线或有效地形网格。")

    def import_terrain(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择真实高程地形图", "", "地形图 (*.dwg *.dxf)")
        if not path:
            return
        if self.calculation_runner.isRunning():
            raise ValueError("上一项任务尚未结束")
        workspace = self.workspace
        session = self._session_provider() if self._session_provider else None
        generation = getattr(session, "generation", None)
        destination = workspace.resource_root / "terrain-imports"
        self._current_job = None
        self._local_task_label = "正在筛选地形图层并清零线宽"
        self._log("开始自动前处理：GCD 块插入点、SQX/JQX 等高线中心线；忽略文字、其他图层及线宽。")

        def work(token):
            from 土石方计算.io.terrain_preprocessor import prepare_terrain_source
            return prepare_terrain_source(path, destination, cancel_token=token)

        def completed(value):
            self._local_task_label = ""
            current = self._session_provider() if self._session_provider else None
            if generation != getattr(current, "generation", None) or self.workspace is not workspace:
                return
            report = value["report"]
            workspace.data["terrain_preprocessing"] = copy.deepcopy(value)
            self._emit_changed()
            self._log(f"地形前处理完成：{report['gcd_insert_count']} 个 GCD 高程点、"
                      f"{report['contour_count']} 条 SQX/JQX 等高线，"
                      f"剔除 {report['ignored_entities']} 个无关对象，"
                      f"清零 {report['width_cleared_contours']} 条多段线的宽度。")
            self._log(f"筛选副本：{value['source_path']}；核对报告：{value['report_path']}")
            quality = report.get("quality_filter", {})
            if quality:
                self._log(f"高程筛查：剔除 {quality['removed_point_count']} 个异常点、"
                          f"{quality['removed_contour_count']} 条异常等高线；"
                          f"保留 {quality['output_point_count']:,} 个源顶点及原始高程。")
            options = {"layer_names": report["layer_names"], "meshing_method": "meshpatch_points", "conflict_policy": "gcd_max",
                       "automatic_boundary": True, "boundary_gap_factor": 4.0,
                       "filter_elevation_outliers": not bool(quality)}
            for field in ("quality_report_path", "quality_report_sha256", "raw_native_sources_path", "raw_native_sources_sha256"):
                if field in report:
                    options[field] = report[field]
            if report["native_sources_compatible"]:
                options.update(native_sources_path=report["native_sources_path"],
                               native_sources_sha256=report["native_sources_sha256"])
            workspace.request_terrain(source_path=value["source_path"], **options)
            self._log("已发送筛查后的 GCD 高程点与 SQX/JQX 顶点建网，并按局部点距自动裁剪测量范围。")
            self._log("高程冲突处理：同位置 GCD 取较高高程，GCD 优先于等高线；处理记录随副本保存。")

        def failed(exc):
            self._local_task_label = ""
            self._log(f"地形前处理失败，未送入 Rhino：{exc}")

        def cancelled():
            self._local_task_label = ""
            self._log("地形前处理已取消，未送入 Rhino。")

        self.calculation_runner.submit(work, on_success=completed, on_error=failed, on_cancelled=cancelled)

    def import_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入建筑物与线路资料", "", "Excel 工作簿 (*.xlsx)")
        if not path:
            return
        from 土石方计算.adapters.source_adapters import load_batch_sample
        imported = load_batch_sample(path)
        self.set_assets(imported["assets"])
        self.workspace.data.pop("source_project_hash", None)
        self.workspace.data.pop("source_requires_refresh", None)
        for issue in imported.get("issues", []):
            self._log(issue.get("message", str(issue)) if isinstance(issue, dict) else issue)
        self._log(f"已导入 {len(imported['assets'])} 个建筑物区段；施工参数及纵断面缺项会单独提示。")

    def import_current_project(self):
        if self._project_provider is None:
            raise ValueError("当前没有绑定主工程，无法读取水面线资料")
        from 土石方计算.adapters.source_adapters import adapt_profile_nodes, adapt_siphon_config
        project = copy.deepcopy(self._project_provider())
        profile = project.get("merged_panel") or project.get("water_profile_panel") or {}
        nodes = profile.get("calculated_nodes") or profile.get("nodes") or []
        assets, issues = [], []
        if nodes:
            converted = adapt_profile_nodes(nodes, source={"kind": "current_project", "module": "water_profile"})
            assets.extend(converted.get("assets", []))
            issues.extend(converted.get("issues", []))
        siphons = (project.get("siphon_manager_data") or {}).get("siphons", {})
        for name, config in siphons.items():
            converted = adapt_siphon_config(config, name=name)
            specific = converted.get("assets", [])
            if specific:
                assets = [item for item in assets if not (item.get("kind") == "siphon" and item.get("name") == name)]
                for item in specific:
                    item["asset_id"] = "siphon-" + hashlib.sha256(str(name).encode("utf-8")).hexdigest()[:12] + "-" + item["asset_id"]
                assets.extend(specific)
            issues.extend(converted.get("issues", []))
        if not assets:
            raise ValueError("当前工程没有可读取的水面线节点或倒虹吸专项几何，请先完成线路输入")
        self.set_assets(assets)
        self.workspace.data["source_project_hash"] = _source_hash(project)
        self.workspace.data["source_requires_refresh"] = False
        for issue in issues:
            self._log(issue.get("message", str(issue)) if isinstance(issue, dict) else issue)
        self._emit_changed()

    def edit_parameters(self):
        identity = self.selected_asset_id()
        assets = copy.deepcopy(self.workspace.data.get("assets", []))
        index = next((i for i, asset in enumerate(assets) if asset.get("asset_id") == identity), None)
        if index is None:
            raise ValueError("请先选择一个建筑物区段")
        dialog = ParameterDialog(assets[index], self)
        if dialog.exec() == QDialog.Accepted:
            assets[index] = dialog.asset
            self.set_assets(assets)

    def apply_test_parameters(self):
        if not self.workspace.data.get("assets"):
            raise ValueError("请先导入建筑物与线路")
        if not self.workspace.data.get("terrain") or not self.workspace.status().get("connected"):
            raise ValueError("请先连接 Rhino 并接收有效地形，测试纵断面需要真实地形高程")
        if self._pending_test_profile:
            raise ValueError("正在等待上一批地形采样")
        identity = self.selected_asset_id()
        dialog = TestProfileDialog(bool(identity), self)
        if dialog.exec() != QDialog.Accepted:
            return
        all_assets = copy.deepcopy(self.workspace.data["assets"])
        selected = ([item for item in all_assets if item.get("asset_id") == identity]
                    if dialog.scope.currentData() == "selected" else
                    [item for item in all_assets if item.get("enabled", True)])
        if not selected:
            raise ValueError("所选范围没有可用建筑物，请先启用支持的施工区段")
        profile = {"cover_depth": dialog.cover.value(), "open_invert_depth": dialog.channel_depth.value()}
        replacement = dialog.replacement.currentData()
        if replacement:
            profile["section_type_overrides"] = {item["asset_id"]: replacement for item in selected}
        self.request_test_profile(selected, profile)

    def request_test_profile(self, selected, profile):
        """冻结测试请求，收到逐点有效的地形高程后才改动设计。"""
        points, groups = [], []
        for item in selected:
            plan = item.get("alignment", {}).get("plan_points", [])
            if len(plan) < 2:
                raise ValueError(f"{item.get('name', '区段')} 至少需要两个平面点")
            start = len(points)
            points.extend([[p["x"], p["y"]] for p in plan])
            groups.append((item["asset_id"], start, len(plan)))
        request_id = uuid.uuid4().hex
        self._pending_test_profile = {
            "request_id": request_id, "assets": copy.deepcopy(selected), "profile": copy.deepcopy(profile),
            "groups": groups, "count": len(points), "source_assets": copy.deepcopy(self.workspace.data["assets"]),
            "terrain_hash": (self.workspace.data.get("terrain") or {}).get("geometry_hash"),
        }
        try:
            self.workspace.sample_terrain(points, request_id=request_id)
        except Exception:
            self._pending_test_profile = None
            raise
        self._log(f"正在查询 {len(points)} 个原始线路点的真实地形高程；缺失覆盖时不会编造高程。")

    def _apply_terrain_samples(self, event):
        pending = self._pending_test_profile
        if not pending or event.get("request_id") != pending["request_id"]:
            return
        self._pending_test_profile = None
        if (self.workspace.data["assets"] != pending["source_assets"] or
                (self.workspace.data.get("terrain") or {}).get("geometry_hash") != pending["terrain_hash"]):
            raise ValueError("地形采样期间资料已改变，旧测试请求已作废，请重新应用测试参数")
        samples = event.get("points_xyz", [])
        if event.get("missing_indices") or len(samples) != pending["count"]:
            raise ValueError("部分线路点缺少真实地形覆盖，测试纵断面未应用；请补齐地形或缩小测试范围")
        elevations = {}
        for identity, start, count in pending["groups"]:
            values = samples[start:start + count]
            if any(not isinstance(point, (list, tuple)) or len(point) < 3 or point[2] is None for point in values):
                raise ValueError("地形查询返回缺失高程，测试纵断面未应用")
            elevations[identity] = [point[2] for point in values]
        from 土石方计算.services.construction_templates import apply_test_profile
        updated = apply_test_profile(pending["assets"], ground_elevations=elevations, profile=pending["profile"])
        by_id = {item["asset_id"]: item for item in updated}
        assets = [by_id.get(item["asset_id"], item) for item in self.workspace.data["assets"]]
        self.workspace.data.setdefault("settings", {})["test_only"] = True
        self.set_assets(assets)
        self._log(f"已对 {len(updated)} 个区段应用基于真实地形的测试纵断面与施工参数，原始资料保持不变。")

    def _check_source(self):
        expected = self.workspace.data.get("source_project_hash")
        if expected and self._project_provider:
            if _source_hash(self._project_provider()) != expected:
                if not self.workspace.data.get("source_requires_refresh"):
                    self.workspace.invalidate("design")
                    self.workspace.data["source_requires_refresh"] = True
                    self._log("原工程的线路或断面已修改，请重新读取当前水面线与倒虹吸后计算。")
                    self._refresh_asset_statuses()
                    self._emit_changed()
                return False
        return True

    def start_calculation(self):
        if self.calculation_runner.isRunning():
            raise ValueError("上一项计算尚未结束")
        if not self._check_source():
            raise ValueError("设计来源已改变，请重新读取当前工程资料")
        workspace = self.workspace
        session = self._session_provider() if self._session_provider else None
        generation = getattr(session, "generation", None)
        workspace.data["project_generation"] = generation or 0
        def wait_for_result(token):
            token.raise_if_cancelled()
            job_id = workspace.create_job()
            while True:
                if token.is_cancelled:
                    workspace.cancel_job(job_id)
                    token.raise_if_cancelled()
                state = workspace.status()
                if state.get("job_state") in _TERMINAL_STATES:
                    return state
                threading.Event().wait(0.15)

        def completed(state):
            current = self._session_provider() if self._session_provider else None
            if generation != getattr(current, "generation", None) or self.workspace is not workspace:
                return
            self._poll_status()
            self._emit_changed()
            if state.get("job_state") != "READY":
                self._log(state.get("message") or _STATE_NAMES.get(state.get("job_state"), "计算未完成"))

        def failed(exc):
            self._log(str(exc))
            workspace.complete_ui_action("calculate", str(exc))

        self.calculation_runner.submit(wait_for_result, on_success=completed,
                                       on_error=failed,
                                       on_cancelled=lambda: self._log("本次计算已取消，上一版已发布结果仍保留。"))

    def cancel_calculation(self):
        if self._current_job and not self._local_task_label:
            self.workspace.cancel_job(self._current_job)
        self.calculation_runner.cancel()

    def _select_result(self):
        if self._selection_from_rhino:
            return
        row = self.result_table.currentRow()
        if 0 <= row < len(self._result_rows):
            selected = self._result_rows[row]
            payload = {key: selected[key] for key in ("asset_id", "segment_id", "participants") if selected.get(key) is not None}
            if payload:
                bridge = getattr(self.workspace, "bridge", None)
                if bridge is not None:
                    self._guard(lambda: bridge.enqueue("select", payload))
                elif payload.get("asset_id"):
                    self._guard(lambda: self.workspace.select(payload["asset_id"]))

    def show_stage(self):
        self.workspace.show_stage(self.stage_combo.currentData())

    def show_section(self):
        self.workspace.section(self.station_spin.value())

    def export_quantities(self):
        result = copy.deepcopy(self.workspace.data.get("last_result"))
        if not result:
            raise ValueError("尚无已发布工程量，不能导出数量表")
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "导出已发布快照的工程量", "挖填工程量.xlsx", "Excel 工作簿 (*.xlsx);;CSV 表格 (*.csv)")
        if not path:
            return
        if not Path(path).suffix:
            path += ".csv" if "*.csv" in selected_filter else ".xlsx"
        from .exporters import export_quantity_table
        result_status = self.workspace.data.get("result_status", "UNKNOWN")
        test_only = result.get("test_only")
        self._current_job = None
        self._local_task_label = "正在导出工程量表"

        def work(token):
            return export_quantity_table(result, path, result_status=result_status,
                                         test_only=test_only, cancel_check=token.raise_if_cancelled)

        def done(value):
            self._local_task_label = ""
            self._log(f"已导出同一结果快照的工程量表：{value}")

        def failed(exc):
            self._local_task_label = ""
            self._log(f"量表导出失败：{exc}")

        self.calculation_runner.submit(work, on_success=done, on_error=failed,
                                       on_cancelled=lambda: self._finish_export_cancel())

    def _finish_export_cancel(self):
        self._local_task_label = ""
        self._log("量表导出已取消，原有文件保持不变。")

    def export_model_dxf(self):
        result = copy.deepcopy(self.workspace.data.get("last_result"))
        if not result or not result.get("model_path"):
            raise ValueError("尚无已发布的三维模型，不能导出 DXF")
        if not self.workspace.status().get("connected"):
            raise ValueError("三维模型 DXF 由 Rhino 原生导出，请先连接 Rhino")
        path, _ = QFileDialog.getSaveFileName(self, "导出同一三维模型为 DXF", "挖填三维模型.dxf", "DXF 模型 (*.dxf)")
        if path:
            if not Path(path).suffix:
                path += ".dxf"
            if Path(path).suffix.lower() != ".dxf":
                raise ValueError("请选择 .dxf 文件")
            self.workspace.bridge.enqueue("export_dxf", {
                "result_id": result["result_id"], "model_path": result["model_path"],
                "model_sha256": result.get("model_sha256"), "output_path": str(Path(path).resolve()),
                "result_status": self.workspace.data.get("result_status", "UNKNOWN"),
            })
            self._log("已请求 Rhino 原生导出已发布模型；此成果是三维网格 DXF，不是新计算的二维断面图。")

    def export_package(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出可搬迁的完整挖填工程包", "挖填工程包.zip", "工程包 (*.zip)")
        if path:
            workspace = self.workspace
            self._current_job = None
            self._local_task_label = "正在导出完整工程包"

            def work(token):
                target = Path(path).resolve()
                # 服务导出采用 qxearth 后缀；短临时名也避免叠加用户长文件名。
                temporary = target.with_name(f".qx-{uuid.uuid4().hex}.qxearth")
                produced = temporary
                try:
                    token.raise_if_cancelled()
                    produced = Path(workspace.export_package(temporary))
                    token.raise_if_cancelled()
                    os.replace(produced, target)
                finally:
                    for candidate in {temporary, produced}:
                        if candidate.exists():
                            candidate.unlink()
                return str(target)

            def completed(value):
                self._local_task_label = ""
                self._log(f"已导出工程快照、资源和现有成果：{value}")

            def failed(exc):
                self._local_task_label = ""
                self._log(f"工程包导出失败：{exc}")

            self.calculation_runner.submit(work, on_success=completed, on_error=failed,
                                           on_cancelled=self._finish_export_cancel)

    def import_workspace(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入完整工程包或工程快照", "", "挖填工程 (*.zip *.qxearth *.json)")
        if path:
            if Path(path).suffix.lower() in (".zip", ".qxearth"):
                self.workspace.import_package(path)
                self._discovery_path = None
                self._last_result_id = None
                self._last_event = 0
                self._refresh_assets()
                self._display_result(self.workspace.data.get("last_result"))
                self._poll_status()
            else:
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
                self.from_project_dict(data)
            self._emit_changed()

    def _display_result(self, result):
        self._result_rows = list((result or {}).get("rows", []))
        self.result_table.blockSignals(True)
        try:
            self.result_table.setRowCount(len(self._result_rows))
            for row, item in enumerate(self._result_rows):
                values = [item.get("name", item.get("segment_id", ""))]
                values.extend("—" if item.get(key) is None else f"{item[key]:,.3f}" for key in
                              ("cut_volume", "backfill_volume", "embankment_volume", "fill_volume"))
                validation = str(item.get("validation_status", "待核验"))
                values.append({"valid": "核验通过", "VALID": "核验通过", "passed": "核验通过",
                               "PASSED": "核验通过", "READY": "已发布", "CHECKED": "已核验"}.get(validation, validation))
                values.append("；".join(str(v) for v in item.get("diagnostics", [])))
                for column, value in enumerate(values):
                    self.result_table.setItem(row, column, QTableWidgetItem(value))
        finally:
            self.result_table.blockSignals(False)
        if result:
            totals = result.get("totals", {})
            labels = (("cut_volume", "挖方"), ("backfill_volume", "周边回填"),
                      ("embankment_volume", "新增填筑"), ("fill_volume", "总填方"))
            self.totals_label.setText("　".join(f"{label} {totals[key]:,.3f} m³" if key in totals else f"{label} 未完成" for key, label in labels))
            self.model_path_label.setText("三维模型：" + str(result.get("model_path") or "未找到对应模型文件"))
        else:
            self.totals_label.setText("尚无已发布工程量。未计算和失败区段不会按零统计。")
            self.model_path_label.setText("三维模型：尚无已发布文件")

    def _poll_status(self):
        try:
            state = self.workspace.status()
            name = state.get("job_state", "DRAFT")
            result_state = state.get("result_status")
            label = _STATE_NAMES.get(name, str(name))
            if state.get("result") and result_state in ("STALE", "DISCONNECTED", "MISSING"):
                saved_label = {"STALE": "原成果已过期，请重新计算",
                               "DISCONNECTED": "已存成果待核对，请重新连接 Rhino",
                               "MISSING": "成果模型缺失，请重新计算"}[result_state]
                # 已失效的历史成果不能继续以“已完成”作为当前状态。
                label = saved_label if name in ("IDLE", "DRAFT", "READY", "STALE", "DISCONNECTED") else label + " · " + saved_label
            self.state_label.setText(self._local_task_label or label)
            self.state_label.setToolTip(str(state.get("message") or ""))
            if state.get("connected"):
                self.connection_label.setText("Rhino 已连接；操作绑定的工程文档。")
            elif self._discovery_path:
                starting = self._rhino_process is not None and self._rhino_process.poll() is None
                self.connection_label.setText("Rhino 已启动，正在等待挖填工作台连接。" if starting
                                              else "连接已准备，等待 Rhino 挖填工作台连接。")
            elif self.workspace.data.get("last_result"):
                self.connection_label.setText("Rhino 未连接，以下为已保存结果；重新绑定后可定位模型。")
            else:
                self.connection_label.setText("Rhino 尚未连接；可以先准备建筑物与施工参数。")
            if state.get("job_id"):
                self._current_job = state["job_id"]
            progress = state.get("progress")
            if progress is not None:
                self.progress.setRange(0, 100)
                self.progress.setValue(int(round(100 * float(progress))))
            elif self.calculation_runner.isRunning():
                self.progress.setRange(0, 0)
            elif not state.get("job_id"):
                # 地形前处理结束后恢复静止进度条，避免无任务时仍显示持续运行。
                self.progress.setRange(0, 100)
                self.progress.setValue(0)
            terrain = self.workspace.data.get("terrain") or {}
            self.terrain_label.setText("地形：" + (f"{terrain.get('vertex_count', '—')} 个顶点，{terrain.get('face_count', '—')} 个三角面" if terrain else "未指定"))
            terrain_hash = terrain.get("geometry_hash")
            if terrain_hash != self._last_terrain_hash:
                had_terrain = self._last_terrain_hash is not None
                self._last_terrain_hash = terrain_hash
                evidence = terrain.get("source_preprocessing") or {}
                boundary_filter = evidence.get("boundary_filter") or {}
                if terrain_hash and boundary_filter.get("mode") == "automatic_local_spacing":
                    self._log(f"自动范围裁剪完成：移除 {boundary_filter.get('removed_face_count', 0):,} 个外围跨接面，"
                              f"保留 {terrain.get('face_count', 0):,} 个三角面。")
                if terrain_hash or had_terrain:
                    self._update_domain_preview()
                    self._emit_changed()
            result = state.get("result") or self.workspace.data.get("last_result")
            result_id = result.get("result_id") if result else None
            if result_id != self._last_result_id:
                self._last_result_id = result_id
                self._display_result(result)
                self._emit_changed()
            self._refresh_asset_statuses(state)
            for event in state.get("events", []):
                identity = event.get("id", event.get("sequence", 0))
                if identity and identity <= self._last_event:
                    continue
                self._last_event = max(self._last_event, identity or 0)
                if event.get("message"):
                    self._log(event["message"])
                if event.get("event") == "failure":
                    self._pending_test_profile = None
                    self._pending_axis = None
                if event.get("event") == "ui_action":
                    try:
                        self._handle_workbench_action(event)
                    except (ValueError, TypeError, KeyError, RuntimeError) as exc:
                        self.workspace.complete_ui_action(event.get("action"), str(exc))
                        self._log(str(exc))
                    else:
                        self.workspace.complete_ui_action(event.get("action"))
                if event.get("event") == "dxf_exported":
                    self._log("Rhino 三维模型 DXF 已导出：" + str(event.get("output_path", "")))
                if event.get("event") == "terrain_samples":
                    try:
                        self._apply_terrain_samples(event)
                    except (ValueError, TypeError, KeyError) as exc:
                        self._log(str(exc))
                if event.get("event") == "axis_bound":
                    try:
                        self._apply_native_axis(event)
                    except (ValueError, TypeError, KeyError) as exc:
                        self._log(str(exc))
                if event.get("event") in ("selection", "selected", "selection_changed"):
                    for row in range(self.asset_table.rowCount()):
                        if self.asset_table.item(row, 0).data(Qt.UserRole) == event.get("asset_id"):
                            self.asset_table.selectRow(row)
                            break
                    self._selection_from_rhino = True
                    try:
                        matches = [(row, item) for row, item in enumerate(self._result_rows)
                                   if (event.get("segment_id") and item.get("segment_id") == event["segment_id"])
                                   or (not event.get("segment_id") and event.get("asset_id")
                                       and item.get("asset_id") == event["asset_id"])]
                        if matches:
                            self.result_table.selectRow(matches[0][0])
                            self.result_table.scrollToItem(self.result_table.item(matches[0][0], 0))
                    finally:
                        self._selection_from_rhino = False
            session = self._session_provider() if self._session_provider else None
            revision = getattr(session, "revision", None)
            if revision != self._last_seen_session_revision:
                self._last_seen_session_revision = revision
                self._check_source()
        except Exception as exc:
            self.state_label.setText("状态读取失败")
            self.state_label.setToolTip(str(exc))

    def to_project_dict(self):
        data = copy.deepcopy(self.workspace.to_dict())
        data["independent"] = self.independent_panel.to_project_dict()
        data["network"] = self.network_panel.to_project_dict()
        data["ui_state"] = {"selected_asset_id": self.selected_asset_id(),
                            "stage": self.stage_combo.currentData(), "station": self.station_spin.value()}
        return data

    def from_project_dict(self, data):
        normalized = normalize_earthwork_payload(data or {})
        self._restoring = True
        try:
            self.calculation_runner.invalidate()
            self.workspace.close()
            self.workspace = self._workspace_factory(normalized or None)
            self._current_job = None
            self._discovery_path = None
            self._pending_test_profile = None
            self._pending_axis = None
            self._last_event = 0
            self._last_result_id = None
            self._last_terrain_hash = None
            self._refresh_assets()
            self._display_result(self.workspace.data.get("last_result"))
            ui = normalized.get("ui_state") or {}
            self.stage_combo.setCurrentIndex(max(0, self.stage_combo.findData(ui.get("stage", "all"))))
            self.station_spin.setValue(float(ui.get("station", 0)))
            for row in range(self.asset_table.rowCount()):
                if self.asset_table.item(row, 0).data(Qt.UserRole) == ui.get("selected_asset_id"):
                    self.asset_table.selectRow(row)
            if normalized.get("migration_status") == "legacy_unverified":
                self._log("旧土石方原型数据已保留为未验证历史资料，请重新建立地形与施工参数后计算。")
            for issue in normalized.get("resource_issues", []):
                self._log(issue.get("message", str(issue)) if isinstance(issue, dict) else str(issue))
            self._update_domain_preview()
            self.independent_panel.from_project_dict(normalized.get("independent") or {})
            self.network_panel.from_project_dict(normalized.get("network") or {})
            self._poll_status()
        finally:
            self._restoring = False

    def reset_to_default(self):
        self.from_project_dict({})

    def shutdown(self):
        self.independent_panel.shutdown()
        self.network_panel.shutdown()
        self._timer.stop()
        self.calculation_runner.invalidate()
        self.workspace.close()
