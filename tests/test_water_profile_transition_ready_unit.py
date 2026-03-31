# -*- coding: utf-8 -*-
"""WaterProfilePanel 渐变段拓扑准备状态回归测试。"""

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _install_panel_import_stubs():
    qtwidgets = types.ModuleType("PySide6.QtWidgets")
    for name in (
        "QWidget", "QVBoxLayout", "QHBoxLayout", "QLabel", "QGroupBox",
        "QSplitter", "QFrame", "QTabWidget", "QTextEdit", "QFileDialog",
        "QTableWidget", "QTableWidgetItem", "QHeaderView", "QComboBox",
        "QAbstractItemView", "QScrollArea", "QGridLayout", "QFormLayout",
        "QSizePolicy", "QDialog", "QDialogButtonBox", "QToolTip", "QCheckBox",
        "QApplication",
    ):
        setattr(qtwidgets, name, type(name, (), {}))

    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.Qt = SimpleNamespace()
    qtcore.QByteArray = type("QByteArray", (), {})
    qtcore.Signal = lambda *args, **kwargs: None
    qtcore.QTimer = type("QTimer", (), {"singleShot": staticmethod(lambda *args, **kwargs: None)})
    qtcore.QRect = type("QRect", (), {})
    qtcore.QPoint = type("QPoint", (), {})
    qtcore.QEvent = type("QEvent", (), {})
    qtcore.QObject = type("QObject", (), {})
    qtcore.QSignalBlocker = type("QSignalBlocker", (), {})

    qtgui = types.ModuleType("PySide6.QtGui")
    for name in ("QFont", "QColor", "QPixmap", "QImage", "QShortcut", "QKeySequence", "QCursor", "QBrush"):
        setattr(qtgui, name, type(name, (), {}))

    sys.modules.setdefault("PySide6", types.ModuleType("PySide6"))
    sys.modules["PySide6.QtWidgets"] = qtwidgets
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui

    qfw = types.ModuleType("qfluentwidgets")
    for name in (
        "PushButton", "PrimaryPushButton", "LineEdit", "ComboBox",
        "InfoBar", "InfoBarIcon", "InfoBarPosition", "DropDownPushButton", "RoundMenu",
        "Action", "MessageBox",
    ):
        setattr(qfw, name, type(name, (), {}))
    sys.modules["qfluentwidgets"] = qfw

    frozen_mod = types.ModuleType("app_渠系计算前端.frozen_table")
    frozen_mod.FrozenColumnTableWidget = type("FrozenColumnTableWidget", (), {})
    sys.modules["app_渠系计算前端.frozen_table"] = frozen_mod

    styles_mod = types.ModuleType("app_渠系计算前端.styles")
    styles_mod.P = styles_mod.S = styles_mod.W = styles_mod.E = ""
    styles_mod.BG = styles_mod.CARD = styles_mod.BD = styles_mod.T1 = styles_mod.T2 = ""
    styles_mod.DIALOG_STYLE = ""
    styles_mod.auto_resize_table = lambda *args, **kwargs: None
    styles_mod.CollapsibleGroupBox = type("CollapsibleGroupBox", (), {})
    styles_mod.fluent_info = lambda *args, **kwargs: None
    styles_mod.fluent_question = lambda *args, **kwargs: True
    sys.modules["app_渠系计算前端.styles"] = styles_mod

    export_mod = types.ModuleType("app_渠系计算前端.export_utils")
    export_mod.WORD_EXPORT_AVAILABLE = False
    for name in (
        "ask_open_file", "create_styled_doc", "doc_add_h1", "doc_add_h2", "doc_add_body",
        "doc_render_calc_text", "doc_add_param_table", "doc_add_result_table",
        "doc_add_styled_table", "doc_add_table_caption", "create_engineering_report_doc",
        "doc_add_eng_h", "doc_add_eng_body", "doc_render_calc_text_eng", "update_doc_toc_via_com",
    ):
        setattr(export_mod, name, lambda *args, **kwargs: None)
    sys.modules["app_渠系计算前端.export_utils"] = export_mod

    report_meta_mod = types.ModuleType("app_渠系计算前端.report_meta")
    report_meta_mod.ExportConfirmDialog = type("ExportConfirmDialog", (), {})
    report_meta_mod.build_calc_purpose = lambda *args, **kwargs: ""
    report_meta_mod.REFERENCES_BASE = []
    report_meta_mod.load_meta = lambda *args, **kwargs: {}
    sys.modules["app_渠系计算前端.report_meta"] = report_meta_mod

    selector_mod = types.ModuleType("app_渠系计算前端.structure_type_selector")
    selector_mod.StructureTypeSelector = type("StructureTypeSelector", (), {})
    sys.modules["app_渠系计算前端.structure_type_selector"] = selector_mod

    case_manager_mod = types.ModuleType("app_渠系计算前端.case_manager")
    case_manager_mod.FlowLayout = type("FlowLayout", (), {})
    sys.modules["app_渠系计算前端.case_manager"] = case_manager_mod

    batch_mod = types.ModuleType("app_渠系计算前端.batch.panel")
    batch_mod.BatchPanel = type("BatchPanel", (), {})
    batch_mod.format_station_display = lambda value: str(value)
    batch_mod.parse_station_input = lambda value: 0.0
    sys.modules["app_渠系计算前端.batch.panel"] = batch_mod

    debug_mod = types.ModuleType("app_渠系计算前端.debug_utils")
    debug_mod.debug_print = lambda *args, **kwargs: None
    sys.modules["app_渠系计算前端.debug_utils"] = debug_mod

    pressure_mod = types.ModuleType("utils.pressure_pipe_result_helpers")
    for name in (
        "make_pressure_pipe_identity", "empty_pressure_pipe_calc_records",
        "normalize_pressure_pipe_calc_records", "format_pressure_pipe_record_detail",
        "append_pressure_pipe_calc_batch_text",
    ):
        setattr(pressure_mod, name, lambda *args, **kwargs: None)
    sys.modules["utils.pressure_pipe_result_helpers"] = pressure_mod

    models_mod = types.ModuleType("models.data_models")
    models_mod.ChannelNode = type("ChannelNode", (), {})
    models_mod.ProjectSettings = type("ProjectSettings", (), {})
    sys.modules["models.data_models"] = models_mod

    class _StubStructureType:
        @staticmethod
        def is_pressure_pipe_like(_value):
            return False

        @staticmethod
        def is_pressure_pipe_like_str(text):
            return str(text or "").strip() in {"有压管道", "定向钻", "顶管"}

        @staticmethod
        def is_diversion_gate(_value):
            return False

    class _StubInOutType:
        INLET = SimpleNamespace(value="进")
        OUTLET = SimpleNamespace(value="出")
        NORMAL = SimpleNamespace(value="")

    enums_mod = types.ModuleType("models.enums")
    enums_mod.StructureType = _StubStructureType
    enums_mod.InOutType = _StubInOutType
    sys.modules["models.enums"] = enums_mod

    calculator_mod = types.ModuleType("core.calculator")
    calculator_mod.WaterProfileCalculator = type("WaterProfileCalculator", (), {})
    sys.modules["core.calculator"] = calculator_mod

    shared_mod = types.ModuleType("shared.shared_data_manager")
    shared_mod.get_shared_data_manager = lambda: None
    sys.modules["shared.shared_data_manager"] = shared_mod


def _load_panel_module():
    patched_names = [
        "PySide6",
        "PySide6.QtWidgets",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "qfluentwidgets",
        "app_渠系计算前端.frozen_table",
        "app_渠系计算前端.styles",
        "app_渠系计算前端.export_utils",
        "app_渠系计算前端.report_meta",
        "app_渠系计算前端.structure_type_selector",
        "app_渠系计算前端.case_manager",
        "app_渠系计算前端.batch.panel",
        "app_渠系计算前端.debug_utils",
        "utils.pressure_pipe_result_helpers",
        "models.data_models",
        "models.enums",
        "core.calculator",
        "shared.shared_data_manager",
    ]
    saved_modules = {name: sys.modules.get(name) for name in patched_names}
    try:
        _install_panel_import_stubs()
        panel_path = next(Path(".").glob("**/water_profile/panel.py")).resolve()
        spec = importlib.util.spec_from_file_location("wp_panel_transition_ready_test", panel_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, old_module in saved_modules.items():
            if old_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module


class _FakeInfoBar:
    records = []

    @classmethod
    def reset(cls):
        cls.records = []

    @classmethod
    def _record(cls, level, title, content):
        cls.records.append({"level": level, "title": title, "content": content})

    @classmethod
    def info(cls, title, content, **kwargs):
        cls._record("info", title, content)

    @classmethod
    def warning(cls, title, content, **kwargs):
        cls._record("warning", title, content)

    @classmethod
    def error(cls, title, content, **kwargs):
        cls._record("error", title, content)

    @classmethod
    def success(cls, title, content, **kwargs):
        cls._record("success", title, content)


class _FakeButton:
    def __init__(self):
        self.enabled = None
        self.tooltip = ""

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def setToolTip(self, tooltip):
        self.tooltip = str(tooltip)


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows

    def rowCount(self):
        return len(self._rows)

    def item(self, row, col):
        if col != 2:
            return None
        return SimpleNamespace(text=lambda: self._rows[row])


def _make_pressure_pipe_nodes():
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root / "推求水面线"))
    from models.data_models import ChannelNode
    from models.enums import StructureType, InOutType

    inlet = ChannelNode(
        flow_section="1",
        name="有压管道A",
        structure_type=StructureType.from_string("有压管道"),
        in_out=InOutType.INLET,
        flow=2.4,
        section_params={"D": 1.2, "in_out_raw": "进"},
    )
    outlet = ChannelNode(
        flow_section="1",
        name="有压管道A",
        structure_type=StructureType.from_string("有压管道"),
        in_out=InOutType.OUTLET,
        flow=2.4,
        section_params={"D": 1.2, "in_out_raw": "出"},
    )
    return [inlet, outlet]


def _install_pressure_pipe_dialog_stub(opened):
    dialog_mod = types.ModuleType("app_渠系计算前端.water_profile.water_profile_dialogs")

    class _FakePressurePipeConfigDialog:
        def __init__(self, parent=None, pipe_groups=None, manager=None):
            opened.append(
                {
                    "parent": parent,
                    "pipe_groups": pipe_groups or [],
                    "manager": manager,
                }
            )

        def exec(self):
            return 0

        def get_turn_radius_payload(self):
            return {}

        def get_d_override_payload(self):
            return {}

        def get_longitudinal_nodes_dict(self):
            return {}

    dialog_mod.PressurePipeConfigDialog = _FakePressurePipeConfigDialog
    saved = sys.modules.get("app_渠系计算前端.water_profile.water_profile_dialogs")
    sys.modules["app_渠系计算前端.water_profile.water_profile_dialogs"] = dialog_mod
    return saved


def _build_minimal_panel(WaterProfilePanel, nodes):
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._ensure_downstream_ready = lambda _action: True
    panel._build_nodes_from_table = lambda: nodes
    panel._build_settings = lambda: None
    panel._info_parent = lambda: None
    panel._pressure_pipe_manager = None
    panel._is_pressure_pipe_like_node = lambda node: True
    panel._apply_pressure_pipe_dialog_payloads = lambda *args, **kwargs: {"changed_cells": 0}
    panel._show_pressure_turn_radius_fallback_notice_if_needed = lambda: None
    panel._recalculate_geometry = lambda: None
    panel._transition_topology_prepared = False
    panel._section_sync_ready = True
    return panel


def test_pressure_pipe_calculator_requires_transition_rows_before_topology_ready():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    module.CALCULATOR_AVAILABLE = True
    module.InfoBar = _FakeInfoBar
    module.InfoBarPosition = SimpleNamespace(TOP="top")
    module.QDialog = SimpleNamespace(Accepted=1)

    nodes = _make_pressure_pipe_nodes()
    panel = _build_minimal_panel(WaterProfilePanel, nodes)
    opened = []
    saved_dialog = _install_pressure_pipe_dialog_stub(opened)
    _FakeInfoBar.reset()
    try:
        WaterProfilePanel._open_pressure_pipe_calculator(panel)
    finally:
        if saved_dialog is None:
            sys.modules.pop("app_渠系计算前端.water_profile.water_profile_dialogs", None)
        else:
            sys.modules["app_渠系计算前端.water_profile.water_profile_dialogs"] = saved_dialog

    assert opened == []
    assert any("插入渐变段" in rec["content"] for rec in _FakeInfoBar.records)


def test_pressure_pipe_calculator_allows_prepared_topology_without_transition_rows():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    module.CALCULATOR_AVAILABLE = True
    module.InfoBar = _FakeInfoBar
    module.InfoBarPosition = SimpleNamespace(TOP="top")
    module.QDialog = SimpleNamespace(Accepted=1)

    nodes = _make_pressure_pipe_nodes()
    panel = _build_minimal_panel(WaterProfilePanel, nodes)
    panel._transition_topology_prepared = True
    opened = []
    saved_dialog = _install_pressure_pipe_dialog_stub(opened)
    _FakeInfoBar.reset()
    try:
        WaterProfilePanel._open_pressure_pipe_calculator(panel)
    finally:
        if saved_dialog is None:
            sys.modules.pop("app_渠系计算前端.water_profile.water_profile_dialogs", None)
        else:
            sys.modules["app_渠系计算前端.water_profile.water_profile_dialogs"] = saved_dialog

    assert len(opened) == 1
    assert not any("插入渐变段" in rec["content"] for rec in _FakeInfoBar.records)


def test_pressure_pipe_calculator_skips_anonymous_pressure_pipe_rows():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    module.CALCULATOR_AVAILABLE = True
    module.InfoBar = _FakeInfoBar
    module.InfoBarPosition = SimpleNamespace(TOP="top")
    module.QDialog = SimpleNamespace(Accepted=1)

    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root / "推求水面线"))
    from models.data_models import ChannelNode
    from models.enums import StructureType, InOutType

    nodes = [
        ChannelNode(
            flow_section="2",
            name="",
            structure_type=StructureType.from_string("有压管道"),
            in_out=InOutType.INLET,
            flow=1.8,
            section_params={"D": 1.0, "in_out_raw": "进"},
        ),
        ChannelNode(
            flow_section="2",
            name="",
            structure_type=StructureType.from_string("有压管道"),
            in_out=InOutType.OUTLET,
            flow=1.8,
            section_params={"D": 1.0, "in_out_raw": "出"},
        ),
    ]

    panel = _build_minimal_panel(WaterProfilePanel, nodes)
    panel._transition_topology_prepared = True
    opened = []
    saved_dialog = _install_pressure_pipe_dialog_stub(opened)
    _FakeInfoBar.reset()
    try:
        WaterProfilePanel._open_pressure_pipe_calculator(panel)
    finally:
        if saved_dialog is None:
            sys.modules.pop("app_渠系计算前端.water_profile.water_profile_dialogs", None)
        else:
            sys.modules["app_渠系计算前端.water_profile.water_profile_dialogs"] = saved_dialog

    assert opened == []
    assert any("未找到有压管道数据组" in rec["content"] for rec in _FakeInfoBar.records)


def test_pressure_pipe_calculator_opens_dialog_for_xxpipe_anonymous_row_segments():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    module.CALCULATOR_AVAILABLE = True
    module.InfoBar = _FakeInfoBar
    module.InfoBarPosition = SimpleNamespace(TOP="top")
    module.QDialog = SimpleNamespace(Accepted=1)

    nodes = _make_pressure_pipe_nodes()
    panel = _build_minimal_panel(WaterProfilePanel, nodes)
    panel._transition_topology_prepared = True
    panel._build_settings = lambda: SimpleNamespace(channel_level="支管")
    panel._extract_pressure_pipe_dialog_groups = lambda _nodes, settings=None: [
        SimpleNamespace(
            name="",
            display_name="流量段1 第2行有压管道",
            storage_key="flow1-row2",
            identity="flow1-row2",
            group_mode="unnamed_row_segment",
            rows=[nodes[-1]],
            row_indices=[1],
            target_row_index=1,
            upstream_row_index=0,
            ip_points=[{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}],
            design_flow=2.4,
            diameter=1.2,
            material_key="预应力钢筒混凝土管",
            inlet_transition_form="反弯扭曲面",
            outlet_transition_form="反弯扭曲面",
            inlet_transition_zeta=0.10,
            outlet_transition_zeta=0.20,
            upstream_velocity=1.0,
            downstream_velocity=1.0,
            is_valid=lambda: True,
            get_validation_message=lambda: "",
        )
    ]
    opened = []
    saved_dialog = _install_pressure_pipe_dialog_stub(opened)
    _FakeInfoBar.reset()
    try:
        WaterProfilePanel._open_pressure_pipe_calculator(panel)
    finally:
        if saved_dialog is None:
            sys.modules.pop("app_渠系计算前端.water_profile.water_profile_dialogs", None)
        else:
            sys.modules["app_渠系计算前端.water_profile.water_profile_dialogs"] = saved_dialog

    assert len(opened) == 1
    assert opened[0]["pipe_groups"][0].storage_key == "flow1-row2"
    assert opened[0]["pipe_groups"][0].display_name == "流量段1 第2行有压管道"


def test_mark_section_results_stale_clears_transition_topology_prepared_flag():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    state = {}
    panel._section_sync_ready = True
    panel._transition_topology_prepared = True
    panel._set_downstream_actions_enabled = (
        lambda enabled, state_text="", status_kind="": state.update(
            {"enabled": enabled, "state_text": state_text, "status_kind": status_kind}
        )
    )

    WaterProfilePanel._mark_section_results_stale(panel, "状态：表3拓扑已变更", status_kind="warning")

    assert panel._section_sync_ready is False
    assert panel._transition_topology_prepared is False
    assert state == {
        "enabled": False,
        "state_text": "状态：表3拓扑已变更",
        "status_kind": "warning",
    }


def test_refresh_pressure_pipe_controls_treats_prepared_topology_as_ready():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._section_sync_ready = True
    panel._transition_topology_prepared = True
    panel.btn_pressure_pipe_calc = _FakeButton()
    panel.node_table = _FakeTable(["有压管道", "明渠-梯形"])

    WaterProfilePanel._refresh_pressure_pipe_controls(panel)

    assert panel.btn_pressure_pipe_calc.enabled is True
    assert "请先插入渐变段" not in panel.btn_pressure_pipe_calc.tooltip
