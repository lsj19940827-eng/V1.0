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
        "format_pressure_pipe_chain_summary", "append_pressure_pipe_calc_batch_text",
        "build_pressure_pipe_transition_note",
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
        def __init__(self, parent=None, pipe_groups=None, manager=None, **kwargs):
            opened.append(
                {
                    "parent": parent,
                    "pipe_groups": pipe_groups or [],
                    "manager": manager,
                    **kwargs,
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


def test_collect_xxpipe_route_context_map_uses_resolved_first_non_tunnel_anchor(monkeypatch):
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel

    route_nodes = [
        SimpleNamespace(
            name="穿山段",
            structure_type=SimpleNamespace(value="隧洞-圆形"),
            station_MC=0.0,
            x=0.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            name="穿路段",
            structure_type=SimpleNamespace(value="有压管道"),
            station_MC=None,
            x=20.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
        SimpleNamespace(
            name="穿路段B",
            structure_type=SimpleNamespace(value="顶管"),
            station_MC=60.0,
            x=60.0,
            y=0.0,
            is_transition=False,
            is_auto_inserted_channel=False,
        ),
    ]
    group = SimpleNamespace(
        route_key="flow2-route1",
        route_display_name="流量段2 整线1",
        route_start_row_index=0,
        route_end_row_index=2,
        row_indices=[0, 1, 2],
        target_row_index=1,
    )
    cad_tools_mod = types.ModuleType("app_渠系计算前端.water_profile.cad_tools")
    cad_tools_mod.resolve_xxpipe_profile_station_targets = lambda nodes, station_prefix="": (
        [
            {"node": route_nodes[0], "station_mc": 0.0},
            {"node": route_nodes[1], "station_mc": 20.0},
            {"node": route_nodes[2], "station_mc": 60.0},
        ],
        [],
    )
    monkeypatch.setitem(sys.modules, "app_渠系计算前端.water_profile.cad_tools", cad_tools_mod)

    route_map = WaterProfilePanel._collect_xxpipe_route_context_map(route_nodes, [group])

    assert route_map["flow2-route1"]["import_anchor_station_mc"] == 20.0


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


def test_pressure_pipe_calculator_opens_dialog_for_continuous_xxqu_anonymous_rows():
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
    panel._build_settings = lambda: SimpleNamespace(channel_level="支渠")
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
    assert opened[0]["xxpipe_route_mode"] is True
    assert len(opened[0]["pipe_groups"]) == 2


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


def test_pressure_pipe_calculator_opens_route_only_dialog_for_supported_xxpipe_routes():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    module.CALCULATOR_AVAILABLE = True
    module.InfoBar = _FakeInfoBar
    module.InfoBarPosition = SimpleNamespace(TOP="top")
    module.QDialog = SimpleNamespace(Accepted=1)

    nodes = _make_pressure_pipe_nodes()
    panel = _build_minimal_panel(WaterProfilePanel, nodes)
    panel._transition_topology_prepared = True
    panel._build_settings = lambda: SimpleNamespace(channel_level="干管")
    panel._extract_pressure_pipe_dialog_groups = lambda _nodes, settings=None: [
        SimpleNamespace(
            name="穿路段A",
            display_name="穿路段A",
            storage_key="flow1-route1-a",
            identity="1::穿路段A",
            group_mode="named_group",
            route_key="flow1-route1",
            route_display_name="流量段1 整线1",
            route_start_row_index=0,
            route_end_row_index=1,
            route_start_mc=0.0,
            route_end_mc=10.0,
            route_ip_points=[{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}],
            row_indices=[0, 1],
            target_row_index=1,
            upstream_row_index=0,
            segment_start_mc=0.0,
            segment_end_mc=10.0,
            rows=nodes,
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
    panel._extract_pressure_pipe_dialog_chains = lambda _nodes, settings=None: [
        SimpleNamespace(flow_section="1", start_row_index=0, end_row_index=1, members=[])
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
    assert opened[0]["xxpipe_route_mode"] is True
    assert len(opened[0]["pressure_chains"]) == 1
    assert opened[0]["pipe_groups"][0].route_key == "flow1-route1"
    assert not any("隧洞" in rec["content"] for rec in _FakeInfoBar.records)


def test_pressure_pipe_calculator_keeps_tunnel_mixed_xxpipe_routes_available():
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
            flow_section="1",
            name="穿路段A",
            structure_type=StructureType.from_string("有压管道"),
            in_out=InOutType.INLET,
            flow=2.4,
            section_params={"D": 1.2, "in_out_raw": "进"},
        ),
        ChannelNode(
            flow_section="1",
            name="穿路段A",
            structure_type=StructureType.from_string("顶管"),
            in_out=InOutType.OUTLET,
            flow=2.4,
            section_params={"D": 1.2, "in_out_raw": "出"},
        ),
        ChannelNode(
            flow_section="2",
            name="穿山段",
            structure_type=StructureType.from_string("有压管道"),
            in_out=InOutType.INLET,
            flow=2.4,
            section_params={"D": 1.2, "in_out_raw": "进"},
        ),
        ChannelNode(
            flow_section="2",
            name="穿山段",
            structure_type=StructureType.from_string("隧洞"),
            in_out=InOutType.NORMAL,
            flow=2.4,
            section_params={"D": 1.2},
        ),
        ChannelNode(
            flow_section="2",
            name="穿山段",
            structure_type=StructureType.from_string("有压管道"),
            in_out=InOutType.OUTLET,
            flow=2.4,
            section_params={"D": 1.2, "in_out_raw": "出"},
        ),
    ]

    panel = _build_minimal_panel(WaterProfilePanel, nodes)
    panel._transition_topology_prepared = True
    panel._build_settings = lambda: SimpleNamespace(channel_level="干管")
    panel._extract_pressure_pipe_dialog_groups = lambda _nodes, settings=None: [
        SimpleNamespace(
            name="穿路段A",
            display_name="穿路段A",
            storage_key="flow1-route1-a",
            identity="1::穿路段A",
            group_mode="named_group",
            route_key="flow1-route1",
            route_display_name="流量段1 整线1",
            route_start_row_index=0,
            route_end_row_index=1,
            route_start_mc=0.0,
            route_end_mc=10.0,
            route_ip_points=[{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}],
            row_indices=[0, 1],
            target_row_index=1,
            upstream_row_index=0,
            segment_start_mc=0.0,
            segment_end_mc=10.0,
            rows=nodes[:2],
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
        ),
        SimpleNamespace(
            name="穿山段",
            display_name="穿山段",
            storage_key="flow2-route1-a",
            identity="2::穿山段",
            group_mode="named_group",
            route_key="flow2-route1",
            route_display_name="流量段2 整线1",
            route_start_row_index=2,
            route_end_row_index=4,
            route_start_mc=20.0,
            route_end_mc=40.0,
            route_ip_points=[{"x": 20.0, "y": 0.0}, {"x": 40.0, "y": 0.0}],
            row_indices=[2, 3, 4],
            target_row_index=4,
            upstream_row_index=2,
            segment_start_mc=20.0,
            segment_end_mc=40.0,
            rows=nodes[2:],
            ip_points=[{"x": 20.0, "y": 0.0}, {"x": 40.0, "y": 0.0}],
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
        ),
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
    assert [group.route_key for group in opened[0]["pipe_groups"]] == ["flow1-route1", "flow2-route1"]
    assert "flow2-route1" in opened[0]["route_import_targets"]
    assert len(opened[0]["pressure_chains"]) == 1
    assert not any("夹带隧洞" in rec["content"] for rec in _FakeInfoBar.records)


def test_prepare_pressure_pipe_dialog_context_enables_route_mode_for_continuous_xxqu():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._extract_pressure_pipe_dialog_groups = lambda _nodes, settings=None: [
        SimpleNamespace(
            route_key="flow7-route1",
            route_display_name="末端连续整线",
            route_ip_points=[{"x": 0.0, "y": 0.0}, {"x": 40.0, "y": 0.0}],
            display_name="穿路段",
            row_indices=[0, 1],
            target_row_index=1,
        )
    ]
    panel._extract_pressure_pipe_dialog_chains = lambda _nodes, settings=None: [
        SimpleNamespace(flow_section="7", start_row_index=0, end_row_index=2, members=[object(), object()])
    ]
    panel._extract_pressure_pipe_routes = lambda _nodes, settings=None: [
        SimpleNamespace(route_key="flow7-route1", route_display_name="末端连续整线")
    ]
    panel._build_pressure_pipe_chain_descriptors = lambda chains: [{"flow_section": "7", "member_count": 2}]
    panel._collect_xxpipe_route_context_map = lambda nodes, pipe_groups: {
        "flow7-route1": {
            "display_name": "末端连续整线",
            "import_anchor_station_mc": 40.0,
            "targets": [],
            "nodes": [],
        }
    }
    panel._get_current_channel_level_text = lambda settings=None: "支渠"
    panel._get_settings_station_prefix = lambda settings=None: ""

    result = WaterProfilePanel._prepare_pressure_pipe_dialog_context(
        panel,
        ["stub-node"],
        settings=SimpleNamespace(channel_level="支渠"),
    )

    assert result["xxpipe_route_mode"] is True
    assert "flow7-route1" in result["route_import_targets"]


def test_prepare_pressure_pipe_dialog_context_keeps_noncontinuous_xxqu_in_group_mode():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._extract_pressure_pipe_dialog_groups = lambda _nodes, settings=None: [
        SimpleNamespace(display_name="白马庙", route_key="", route_display_name="")
    ]
    panel._extract_pressure_pipe_dialog_chains = lambda _nodes, settings=None: []
    panel._extract_pressure_pipe_routes = lambda _nodes, settings=None: []
    panel._build_pressure_pipe_chain_descriptors = lambda chains: []
    panel._collect_xxpipe_route_context_map = lambda nodes, pipe_groups: {}
    panel._get_current_channel_level_text = lambda settings=None: "支渠"
    panel._get_settings_station_prefix = lambda settings=None: ""

    result = WaterProfilePanel._prepare_pressure_pipe_dialog_context(
        panel,
        ["stub-node"],
        settings=SimpleNamespace(channel_level="支渠"),
    )

    assert result["xxpipe_route_mode"] is False
    assert result["route_import_targets"] == {}


def test_pressure_pipe_calculator_clears_route_profile_segments_when_pure_xxpipe_route_recomputed():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    module.CALCULATOR_AVAILABLE = True
    module.InfoBar = _FakeInfoBar
    module.InfoBarPosition = SimpleNamespace(TOP="top")
    module.QDialog = SimpleNamespace(Accepted=1)
    module.normalize_pressure_pipe_calc_records = lambda data: data
    module.build_pressure_pipe_transition_note = lambda **kwargs: ""

    route_key = "flow1-route1"
    long_nodes = [
        {"chainage": 0.0, "elevation": 422.0, "turn_type": "NONE", "turn_angle": 0.0, "vertical_curve_radius": 0.0},
        {"chainage": 10.0, "elevation": 420.0, "turn_type": "NONE", "turn_angle": 0.0, "vertical_curve_radius": 0.0},
    ]
    group = SimpleNamespace(
        name="穿路段A",
        display_name="穿路段A",
        storage_key="flow1-route1-a",
        identity="1::穿路段A",
        group_mode="named_group",
        route_key=route_key,
        route_display_name="流量段1 整线1",
        route_start_row_index=0,
        route_end_row_index=1,
        route_start_mc=0.0,
        route_end_mc=10.0,
        route_ip_points=[{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}],
        row_indices=[0, 1],
        target_row_index=1,
        upstream_row_index=0,
        segment_start_mc=0.0,
        segment_end_mc=10.0,
        rows=[],
        ip_points=[{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}],
        design_flow=2.4,
        diameter=1.2,
        material_key="预应力钢筒混凝土管",
        inlet_transition_form="反弯扭曲面",
        outlet_transition_form="反弯扭曲面",
        inlet_transition_zeta=0.10,
        outlet_transition_zeta=0.20,
        has_inlet_transition=False,
        has_outlet_transition=False,
        inlet_transition_reason="",
        outlet_transition_reason="",
        upstream_velocity=1.0,
        downstream_velocity=1.0,
        is_valid=lambda: True,
        get_validation_message=lambda: "",
    )

    class _FakeAcceptedDialog:
        def __init__(self, parent=None, pipe_groups=None, manager=None, **kwargs):
            self._longitudinal = {route_key: list(long_nodes)}

        def exec(self):
            return module.QDialog.Accepted

        def get_turn_radius_payload(self):
            return {}

        def get_d_override_payload(self):
            return {}

        def get_longitudinal_nodes_dict(self):
            return dict(self._longitudinal)

    class _CaptureManager:
        def __init__(self):
            self.calls = []

        def get_pipe_config(self, _pipe_name):
            return None

        def set_result(self, pipe_name, **kwargs):
            self.calls.append({"pipe_name": pipe_name, **kwargs})

    pressure_dialog_mod = types.ModuleType("app_渠系计算前端.water_profile.water_profile_dialogs")
    pressure_dialog_mod.PressurePipeConfigDialog = _FakeAcceptedDialog
    saved_dialog = sys.modules.get("app_渠系计算前端.water_profile.water_profile_dialogs")
    sys.modules["app_渠系计算前端.water_profile.water_profile_dialogs"] = pressure_dialog_mod

    pressure_calc_mod = types.ModuleType("core.pressure_pipe_calc")
    pressure_calc_mod.PIPE_MATERIALS = {"预应力钢筒混凝土管": {}}
    pressure_calc_mod.calc_total_head_loss = lambda **kwargs: SimpleNamespace(
        total_length=10.0,
        pipe_velocity=1.1,
        friction_loss=0.2,
        total_bend_loss=0.03,
        inlet_transition_loss=0.01,
        outlet_transition_loss=0.01,
        total_head_loss=0.25,
        calc_steps="ok",
        data_mode="平面模式",
        has_inlet_transition=False,
        has_outlet_transition=False,
        inlet_transition_reason="",
        outlet_transition_reason="",
        friction_details={},
        bend_details={},
    )
    pressure_calc_mod.calc_total_head_loss_with_spatial = lambda **kwargs: SimpleNamespace(
        total_length=10.0,
        pipe_velocity=1.1,
        friction_loss=0.2,
        total_bend_loss=0.03,
        inlet_transition_loss=0.01,
        outlet_transition_loss=0.01,
        total_head_loss=0.25,
        calc_steps="ok",
        data_mode="空间模式（平面+纵断面）",
        has_inlet_transition=False,
        has_outlet_transition=False,
        inlet_transition_reason="",
        outlet_transition_reason="",
        friction_details={},
        bend_details={},
    )
    saved_pressure_calc = sys.modules.get("core.pressure_pipe_calc")
    sys.modules["core.pressure_pipe_calc"] = pressure_calc_mod

    pressure_common_mod = types.ModuleType("utils.pressure_pipe_common")
    pressure_common_mod.resolve_pressure_pipe_material = (
        lambda raw_material_key, _pipe_materials, default_material="": {
            "canonical_key": raw_material_key or default_material,
            "display_value": raw_material_key or default_material,
            "used_default": False,
        }
    )
    saved_pressure_common = sys.modules.get("utils.pressure_pipe_common")
    sys.modules["utils.pressure_pipe_common"] = pressure_common_mod

    panel = _build_minimal_panel(WaterProfilePanel, [SimpleNamespace(structure_type="有压管道")])
    panel._transition_topology_prepared = True
    panel._build_settings = lambda: SimpleNamespace(channel_level="干管")
    panel._pressure_pipe_manager = _CaptureManager()
    panel._prepare_pressure_pipe_dialog_context = lambda _nodes, settings=None, show_xxpipe_warning=True: {
        "pipe_groups": [group],
        "chain_descriptors": [],
        "xxpipe_route_mode": True,
        "route_import_targets": {route_key: {"display_name": "流量段1 整线1"}},
        "blocked_route_names": [],
    }
    panel._build_pressure_pipe_route_profile_segments = (
        lambda pipe_groups, longitudinal_nodes_dict: {
            route_key: [
                {
                    "segment_identity": group.identity,
                    "structure_type": "有压管道",
                    "source_kind": "non_tunnel_dxf",
                    "start_mc": 0.0,
                    "end_mc": 10.0,
                    "longitudinal_nodes": list(long_nodes),
                    "warnings": [],
                }
            ]
        }
    )
    panel._update_pressure_pipe_last_result_button = lambda: None
    panel._append_pressure_pipe_calc_details = lambda *_args, **_kwargs: None
    panel._show_pressure_pipe_calc_summary_dialog = lambda *_args, **_kwargs: None

    _FakeInfoBar.reset()
    try:
        WaterProfilePanel._open_pressure_pipe_calculator(panel)
    finally:
        if saved_dialog is None:
            sys.modules.pop("app_渠系计算前端.water_profile.water_profile_dialogs", None)
        else:
            sys.modules["app_渠系计算前端.water_profile.water_profile_dialogs"] = saved_dialog
        if saved_pressure_calc is None:
            sys.modules.pop("core.pressure_pipe_calc", None)
        else:
            sys.modules["core.pressure_pipe_calc"] = saved_pressure_calc
        if saved_pressure_common is None:
            sys.modules.pop("utils.pressure_pipe_common", None)
        else:
            sys.modules["utils.pressure_pipe_common"] = saved_pressure_common

    assert panel._pressure_pipe_manager.calls
    assert panel._pressure_pipe_manager.calls[0]["profile_segments"] == []


def test_build_pressure_pipe_route_profile_segments_uses_group_identity_without_typeerror():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel

    route_key = "flow1-route1"
    group = SimpleNamespace(
        name="穿路段A",
        display_name="穿路段A",
        identity="1::穿路段A",
        storage_key="flow1-route1-a",
        route_key=route_key,
        structure_type="有压管道",
        segment_start_mc=0.0,
        segment_end_mc=10.0,
    )
    route_nodes = [
        {
            "chainage": 0.0,
            "elevation": 422.0,
            "turn_type": "NONE",
            "turn_angle": 0.0,
            "vertical_curve_radius": 0.0,
        },
        {
            "chainage": 10.0,
            "elevation": 420.0,
            "turn_type": "NONE",
            "turn_angle": 0.0,
            "vertical_curve_radius": 0.0,
        },
    ]

    result = WaterProfilePanel._build_pressure_pipe_route_profile_segments(
        [group],
        {route_key: route_nodes},
    )

    assert route_key in result
    assert result[route_key][0]["segment_identity"] == "1::穿路段A"
    assert result[route_key][0]["source_kind"] == "non_tunnel_dxf"


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


def test_collect_pending_pressure_pipe_execute_members_allows_completed_prefix_writeback():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    identity = "1::苟家湾::rows83"
    start_node = SimpleNamespace(
        name="苟家湾",
        structure_type=SimpleNamespace(value="有压管道"),
        section_params={},
        pressure_pipe_window_override={},
        head_loss_siphon=0.0,
    )
    next_node = SimpleNamespace(
        name="大石包",
        structure_type=SimpleNamespace(value="定向钻"),
        section_params={
            "pressure_pipe_window_override": {
                "enabled": True,
                "identity": identity,
                "storage_key": identity,
                "display_name": "苟家湾（前缀段）",
                "group_mode": "chain_prefix_member",
                "target_row_index": 1,
                "upstream_row_index": 0,
                "total_head_loss": 0.3188,
            }
        },
        pressure_pipe_window_override={},
        head_loss_siphon=0.0,
    )
    chain_member = SimpleNamespace(
        identity=identity,
        display_name="苟家湾（前缀段）",
        member_type="named_group",
        member_role="prefix_segment",
        structure_type="有压管道",
        target_row_index=0,
        prefix_target_row_index=0,
        prefix_end_row_index=1,
        should_generate_row_loss=True,
        is_anchor_member=False,
    )
    panel._prepare_pressure_pipe_dialog_context = lambda _nodes, settings=None, show_xxpipe_warning=False: {
        "pipe_groups": [
            SimpleNamespace(
                identity=identity,
                display_name="苟家湾（前缀段）",
                group_mode="named_group",
                target_row_index=1,
                outlet_row_index=-1,
            )
        ],
        "chain_descriptors": [{"members": [chain_member]}],
    }
    panel._pressure_pipe_calc_records = {
        "records": [
            {
                "identity": identity,
                "status": "success",
                "writeback_enabled": True,
                "group_mode": "chain_prefix_member",
                "target_row_index": 1,
                "total_head_loss": 0.3188,
            }
        ]
    }

    pending = WaterProfilePanel._collect_pending_pressure_pipe_execute_members(
        panel,
        [start_node, next_node],
        settings=None,
    )

    assert pending == []


def test_collect_pending_pressure_pipe_execute_members_stays_ready_after_silent_recalc_override_reload():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root / "推求水面线"))
    from core.hydraulic_calc import HydraulicCalculator
    from models.data_models import ChannelNode, ProjectSettings
    from models.enums import StructureType, InOutType

    def _make_open_channel(station_mc: float, velocity: float, name: str) -> ChannelNode:
        node = ChannelNode()
        node.name = name
        node.flow_section = "1"
        node.structure_type = StructureType.from_string("明渠-梯形")
        node.station_MC = station_mc
        node.velocity = velocity
        node.water_depth = 1.3
        node.roughness = 0.025
        node.section_params = {"B": 2.4, "m": 1.5, "h": 1.3}
        return node

    identity = "1::苟家湾::rows83"
    upstream = _make_open_channel(0.0, 0.85, "上游明渠")
    target_node = ChannelNode()
    target_node.flow_section = "1"
    target_node.name = "大石包"
    target_node.structure_type = StructureType.from_string("定向钻")
    target_node.in_out = InOutType.INLET
    target_node.station_MC = 21.6
    target_node.flow = 0.32
    target_node.velocity = 0.0
    target_node.water_depth = 1.1
    target_node.section_params = {
        "D": 1.0,
        "pipe_material": "球墨铸铁管",
        "pressure_pipe_window_override": {
            "enabled": True,
            "identity": identity,
            "storage_key": identity,
            "display_name": "苟家湾（前缀段）",
            "group_mode": "chain_prefix_member",
            "data_mode": "链前缀段",
            "applied_at": "2026-04-08 21:13:14",
            "calc_steps": "prefix-step",
            "target_row_index": 1,
            "upstream_row_index": 0,
            "Q": 0.32,
            "D": 1.0,
            "total_length": 21.6,
            "pipe_velocity": 0.41,
            "friction_loss": 0.3188,
            "total_bend_loss": 0.0,
            "local_loss": 0.0,
            "inlet_transition_loss": 0.0,
            "outlet_transition_loss": 0.0,
            "total_head_loss": 0.3188,
            "friction_details": {"method": "gb50288", "hf": 0.3188},
            "bend_details": {},
            "local_details": {"method": "chain_prefix_member", "hj": 0.0},
        },
    }
    downstream = _make_open_channel(60.0, 0.92, "下游明渠")

    settings = ProjectSettings()
    settings.channel_level = "支渠"
    settings.start_water_level = 100.0
    calc = HydraulicCalculator(settings)
    for node in (upstream, target_node, downstream):
        calc.fill_section_params(node)
    calc.calculate_water_profile([upstream, target_node, downstream], method="forward")

    start_node = SimpleNamespace(
        name="苟家湾",
        structure_type=SimpleNamespace(value="有压管道"),
        section_params={},
        pressure_pipe_window_override={},
        head_loss_siphon=0.0,
    )
    chain_member = SimpleNamespace(
        identity=identity,
        display_name="苟家湾（前缀段）",
        member_type="named_group",
        member_role="prefix_segment",
        structure_type="有压管道",
        target_row_index=0,
        prefix_target_row_index=0,
        prefix_end_row_index=1,
        should_generate_row_loss=True,
        is_anchor_member=False,
    )
    panel._prepare_pressure_pipe_dialog_context = lambda _nodes, settings=None, show_xxpipe_warning=False: {
        "pipe_groups": [
            SimpleNamespace(
                identity=identity,
                display_name="苟家湾（前缀段）",
                group_mode="named_group",
                target_row_index=1,
                outlet_row_index=-1,
            )
        ],
        "chain_descriptors": [{"members": [chain_member]}],
    }
    panel._pressure_pipe_calc_records = {
        "records": [
            {
                "identity": identity,
                "status": "success",
                "writeback_enabled": True,
                "group_mode": "chain_prefix_member",
                "target_row_index": 1,
                "total_head_loss": 0.3188,
            }
        ]
    }

    pending = WaterProfilePanel._collect_pending_pressure_pipe_execute_members(
        panel,
        [start_node, target_node],
        settings=None,
    )

    assert pending == []


def test_collect_pending_pressure_pipe_execute_members_blocks_missing_prefix_writeback():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    identity = "1::苟家湾::rows83"
    start_node = SimpleNamespace(
        name="苟家湾",
        structure_type=SimpleNamespace(value="有压管道"),
        section_params={},
        pressure_pipe_window_override={},
        head_loss_siphon=0.0,
    )
    next_node = SimpleNamespace(
        name="大石包",
        structure_type=SimpleNamespace(value="定向钻"),
        section_params={},
        pressure_pipe_window_override={},
        head_loss_siphon=0.0,
    )
    chain_member = SimpleNamespace(
        identity=identity,
        display_name="苟家湾（前缀段）",
        member_type="named_group",
        member_role="prefix_segment",
        structure_type="有压管道",
        target_row_index=0,
        prefix_target_row_index=0,
        prefix_end_row_index=1,
        should_generate_row_loss=True,
        is_anchor_member=False,
    )
    panel._prepare_pressure_pipe_dialog_context = lambda _nodes, settings=None, show_xxpipe_warning=False: {
        "pipe_groups": [
            SimpleNamespace(
                identity=identity,
                display_name="苟家湾（前缀段）",
                group_mode="named_group",
                target_row_index=1,
                outlet_row_index=-1,
            )
        ],
        "chain_descriptors": [{"members": [chain_member]}],
    }
    panel._pressure_pipe_calc_records = {"records": []}

    pending = WaterProfilePanel._collect_pending_pressure_pipe_execute_members(
        panel,
        [start_node, next_node],
        settings=None,
    )

    assert pending == ["苟家湾（前缀段）"]


def test_collect_pending_pressure_pipe_execute_members_allows_completed_named_tunnel_row_override():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    identity = "flow1-row3"
    start_node = SimpleNamespace(
        name="上游连接段",
        structure_type=SimpleNamespace(value="有压管道"),
        section_params={},
        pressure_pipe_window_override={},
        head_loss_siphon=0.0,
    )
    tunnel_node = SimpleNamespace(
        name="唐家湾",
        structure_type=SimpleNamespace(value="隧洞"),
        section_params={
            "pressure_pipe_window_override": {
                "enabled": True,
                "identity": identity,
                "storage_key": identity,
                "display_name": "唐家湾",
                "group_mode": "chain_tunnel_member",
                "target_row_index": 1,
                "upstream_row_index": 0,
                "total_head_loss": 0.2312,
            }
        },
        pressure_pipe_window_override={},
        head_loss_siphon=0.0,
    )
    chain_member = SimpleNamespace(
        identity=identity,
        display_name="唐家湾",
        member_type="named_group",
        member_role="special_segment",
        structure_type="隧洞",
        target_row_index=1,
        should_generate_row_loss=True,
        is_anchor_member=False,
    )
    panel._prepare_pressure_pipe_dialog_context = lambda _nodes, settings=None, show_xxpipe_warning=False: {
        "pipe_groups": [
            SimpleNamespace(
                identity=identity,
                display_name="唐家湾",
                group_mode="named_group",
                target_row_index=1,
                outlet_row_index=1,
            )
        ],
        "chain_descriptors": [{"members": [chain_member]}],
    }
    panel._pressure_pipe_calc_records = {
        "records": [
            {
                "identity": identity,
                "status": "success",
                "writeback_enabled": True,
                "group_mode": "chain_tunnel_member",
                "target_row_index": 1,
                "total_head_loss": 0.2312,
            }
        ]
    }
    panel._build_pressure_pipe_execute_record_map = lambda: {
        identity: {
            "identity": identity,
            "status": "success",
            "writeback_enabled": True,
            "group_mode": "chain_tunnel_member",
            "target_row_index": 1,
            "total_head_loss": 0.2312,
        }
    }

    pending = WaterProfilePanel._collect_pending_pressure_pipe_execute_members(
        panel,
        [start_node, tunnel_node],
        settings=None,
    )

    assert pending == []
