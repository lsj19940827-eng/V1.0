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
        self.style_sheet = ""
        self.properties = {}

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def setToolTip(self, tooltip):
        self.tooltip = str(tooltip)

    def setStyleSheet(self, style_sheet):
        self.style_sheet = str(style_sheet)

    def styleSheet(self):
        return self.style_sheet

    def setProperty(self, name, value):
        self.properties[str(name)] = value

    def property(self, name):
        return self.properties.get(str(name))

    def style(self):
        return SimpleNamespace(
            unpolish=lambda _widget: None,
            polish=lambda _widget: None,
        )


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


def _load_real_pressure_pipe_test_support():
    project_root = Path(__file__).resolve().parents[1]
    module_root = str(project_root / "推求水面线")
    if module_root not in sys.path:
        sys.path.insert(0, module_root)
    from models.data_models import ChannelNode
    from models.enums import StructureType, InOutType
    from utils.pressure_pipe_extractor import PressurePipeDataExtractor

    return SimpleNamespace(
        ChannelNode=ChannelNode,
        StructureType=StructureType,
        InOutType=InOutType,
        PressurePipeDataExtractor=PressurePipeDataExtractor,
    )


def _make_stationed_pressure_node(
    flow_section,
    name,
    structure,
    in_out,
    station_mc,
    x,
    y,
    *,
    diameter=1.2,
    flow=2.4,
):
    support = _load_real_pressure_pipe_test_support()
    node = support.ChannelNode()
    node.flow_section = flow_section
    node.name = name
    node.structure_type = support.StructureType.from_string(structure)
    node.in_out = in_out
    node.flow = flow
    node.station_MC = float(station_mc)
    node.x = float(x)
    node.y = float(y)
    node.section_params = {
        "D": diameter,
        "in_out_raw": getattr(in_out, "value", str(in_out)),
    }
    return node


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


def test_collect_missing_structure_height_names_skips_pressure_pipe_like_rows_in_mixed_route():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel

    nodes = [
        SimpleNamespace(
            name="-",
            structure_type=SimpleNamespace(value="有压管道"),
            is_transition=False,
            bottom_elevation=352.4,
            top_elevation=0.0,
        ),
        SimpleNamespace(
            name="罗家湾",
            structure_type=SimpleNamespace(value="隧洞-圆拱直墙型"),
            is_transition=False,
            bottom_elevation=351.8,
            top_elevation=353.6,
        ),
        SimpleNamespace(
            name="-",
            structure_type=SimpleNamespace(value="定向钻"),
            is_transition=False,
            bottom_elevation=350.1,
            top_elevation=0.0,
        ),
    ]

    result = WaterProfilePanel._collect_missing_structure_height_names(nodes)

    assert result == []


def test_collect_missing_structure_height_names_keeps_real_tunnel_missing_height_warning():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel

    nodes = [
        SimpleNamespace(
            name="-",
            structure_type=SimpleNamespace(value="有压管道"),
            is_transition=False,
            bottom_elevation=352.4,
            top_elevation=0.0,
        ),
        SimpleNamespace(
            name="罗家湾",
            structure_type=SimpleNamespace(value="隧洞-圆拱直墙型"),
            is_transition=False,
            bottom_elevation=351.8,
            top_elevation=0.0,
        ),
    ]

    result = WaterProfilePanel._collect_missing_structure_height_names(nodes)

    assert result == ["罗家湾"]


def test_collect_missing_structure_height_names_skips_auto_inserted_helper_rows():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel

    nodes = [
        SimpleNamespace(
            name="-",
            structure_type=SimpleNamespace(value="明渠-矩形"),
            is_transition=False,
            is_auto_inserted_channel=True,
            bottom_elevation=351.8,
            top_elevation=0.0,
        ),
        SimpleNamespace(
            name="罗家湾",
            structure_type=SimpleNamespace(value="隧洞-圆拱直墙型"),
            is_transition=False,
            is_auto_inserted_channel=False,
            bottom_elevation=351.8,
            top_elevation=0.0,
        ),
    ]

    result = WaterProfilePanel._collect_missing_structure_height_names(nodes)

    assert result == ["罗家湾"]


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


def test_pressure_pipe_calculator_repairs_stale_sync_flags_when_table3_topology_still_valid():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    module.CALCULATOR_AVAILABLE = True
    module.InfoBar = _FakeInfoBar
    module.InfoBarPosition = SimpleNamespace(TOP="top")
    module.QDialog = SimpleNamespace(Accepted=1)

    nodes = _make_pressure_pipe_nodes()
    nodes.append(
        SimpleNamespace(
            is_transition=True,
            structure_type=SimpleNamespace(value="渐变段"),
        )
    )
    panel = _build_minimal_panel(WaterProfilePanel, nodes)
    panel._ensure_downstream_ready = WaterProfilePanel._ensure_downstream_ready.__get__(
        panel,
        WaterProfilePanel,
    )
    panel._section_sync_ready = False
    panel._transition_topology_prepared = False

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
    assert panel._section_sync_ready is True
    assert panel._transition_topology_prepared is True
    assert not any("操作已锁定" in rec["title"] for rec in _FakeInfoBar.records)


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


def test_prepare_pressure_pipe_dialog_context_counts_route_import_targets_by_pressure_runs():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = _build_minimal_panel(WaterProfilePanel, [])
    support = _load_real_pressure_pipe_test_support()
    extractor = support.PressurePipeDataExtractor
    in_out = support.InOutType
    settings = SimpleNamespace(channel_level="支管")

    panel._extract_pressure_pipe_dialog_groups = (
        lambda nodes, settings=None: extractor.extract_dialog_pipe_groups(nodes, settings=settings)
    )
    panel._extract_pressure_pipe_dialog_chains = (
        lambda nodes, settings=None: extractor.extract_continuous_pressure_chains(nodes, settings=settings)
    )
    panel._extract_pressure_pipe_routes = (
        lambda nodes, settings=None: extractor.extract_pressure_routes(nodes, settings=settings)
    )
    panel._get_current_channel_level_text = lambda settings=None: "支管"
    panel._get_settings_station_prefix = lambda settings=None: ""

    leading_tunnel_nodes = [
        _make_stationed_pressure_node("8", "前置隧洞1", "隧洞-圆形", in_out.NORMAL, 0.0, 0.0, 0.0, flow=0.0),
        _make_stationed_pressure_node("8", "前置隧洞2", "隧洞-圆形", in_out.NORMAL, 20.0, 20.0, 0.0, flow=0.0),
        _make_stationed_pressure_node("8", "九龙右支管", "有压管道", in_out.INLET, 40.0, 40.0, 2.0, diameter=0.8, flow=0.49),
        _make_stationed_pressure_node("8", "九龙右支管", "顶管", in_out.OUTLET, 60.0, 60.0, 2.0, diameter=0.8, flow=0.49),
        _make_stationed_pressure_node("8", "尾置隧洞", "隧洞-圆形", in_out.NORMAL, 80.0, 80.0, 3.0, flow=0.0),
    ]
    leading_result = WaterProfilePanel._prepare_pressure_pipe_dialog_context(
        panel,
        leading_tunnel_nodes,
        settings=settings,
    )

    assert leading_result["xxpipe_route_mode"] is True
    assert len(leading_result["route_import_targets"]) == 1
    assert len(leading_result["pressure_routes"]) == 1
    assert set(leading_result["route_import_targets"]) == {
        group.route_key for group in leading_result["pipe_groups"] if getattr(group, "route_key", "")
    }

    split_route_nodes = [
        _make_stationed_pressure_node("2", "穿路段", "定向钻", in_out.INLET, 10.0, 10.0, 0.0, diameter=1.0, flow=1.8),
        _make_stationed_pressure_node("2", "穿路段", "定向钻", in_out.OUTLET, 30.0, 30.0, 0.0, diameter=1.0, flow=1.8),
        _make_stationed_pressure_node("3", "中间隧洞", "隧洞-圆形", in_out.NORMAL, 50.0, 50.0, 2.0, flow=0.0),
        _make_stationed_pressure_node("3", "", "有压管道", in_out.NORMAL, 80.0, 80.0, 4.0, diameter=1.0, flow=1.8),
    ]
    split_result = WaterProfilePanel._prepare_pressure_pipe_dialog_context(
        panel,
        split_route_nodes,
        settings=settings,
    )

    assert split_result["xxpipe_route_mode"] is True
    assert len(split_result["route_import_targets"]) == 2
    assert len(split_result["pressure_routes"]) == 2
    assert set(split_result["route_import_targets"]) == {
        group.route_key for group in split_result["pipe_groups"] if getattr(group, "route_key", "")
    }


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


def test_pressure_pipe_calculator_keeps_route_profile_segments_when_pure_xxpipe_route_recomputed():
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
    assert panel._pressure_pipe_manager.calls[0]["profile_segments"] is None


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


def test_mark_section_results_stale_disables_all_downstream_buttons():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._section_sync_ready = True
    panel._transition_topology_prepared = True
    panel._btn_transition = _FakeButton()
    panel._btn_siphon = _FakeButton()
    panel._btn_calc = _FakeButton()
    panel.btn_pressure_pipe_calc = _FakeButton()
    panel.node_table = _FakeTable(["有压管道"])
    panel._section_state_label = None
    panel._section_status_bar = None
    panel._section_state_icon = None

    WaterProfilePanel._mark_section_results_stale(panel, "状态：表3拓扑已变更", status_kind="warning")

    assert panel._section_sync_ready is False
    assert panel._btn_transition.enabled is False
    assert panel._btn_siphon.enabled is False
    assert panel._btn_calc.enabled is False
    assert panel.btn_pressure_pipe_calc.enabled is False
    for btn in (panel._btn_transition, panel._btn_siphon, panel.btn_pressure_pipe_calc, panel._btn_calc):
        assert btn.styleSheet() == ""
        assert btn.property("table3_locked_look") is None


def test_refresh_pressure_pipe_controls_keeps_button_disabled_when_sync_not_ready():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._section_sync_ready = False
    panel._transition_topology_prepared = False
    panel.btn_pressure_pipe_calc = _FakeButton()
    panel.btn_pressure_pipe_calc.setEnabled(False)
    panel.node_table = _FakeTable(["有压管道", "明渠-梯形"])

    WaterProfilePanel._refresh_pressure_pipe_controls(panel)

    assert panel.btn_pressure_pipe_calc.enabled is False
    assert panel.btn_pressure_pipe_calc.tooltip == ""


def test_set_downstream_actions_enabled_reenables_buttons_without_custom_style():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._btn_transition = _FakeButton()
    panel._btn_siphon = _FakeButton()
    panel._btn_calc = _FakeButton()
    panel.btn_pressure_pipe_calc = _FakeButton()
    panel._section_state_label = None
    panel._section_status_bar = None
    panel._section_state_icon = None

    WaterProfilePanel._set_downstream_actions_enabled(panel, False, state_text="状态：表3拓扑已变更")
    WaterProfilePanel._set_downstream_actions_enabled(panel, True, state_text="状态：断面全成功")

    for btn in (panel._btn_transition, panel._btn_siphon, panel.btn_pressure_pipe_calc, panel._btn_calc):
        assert btn.enabled is True
        assert btn.styleSheet() == ""
        assert btn.property("table3_locked_look") is None


def test_refresh_pressure_pipe_controls_treats_prepared_topology_as_ready_without_changing_enabled_state():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._section_sync_ready = True
    panel._transition_topology_prepared = True
    panel.btn_pressure_pipe_calc = _FakeButton()
    panel.btn_pressure_pipe_calc.setEnabled(False)
    panel.node_table = _FakeTable(["有压管道", "明渠-梯形"])

    WaterProfilePanel._refresh_pressure_pipe_controls(panel)

    assert panel.btn_pressure_pipe_calc.enabled is False
    assert "请先插入渐变段" not in panel.btn_pressure_pipe_calc.tooltip


def test_resolve_loaded_section_gate_state_treats_missing_sync_ready_as_legacy_ready():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel

    sync_ready, legacy_loaded = WaterProfilePanel._resolve_loaded_section_gate_state(
        {"state_text": "状态：历史项目"},
        3,
    )

    assert sync_ready is True
    assert legacy_loaded is True


def test_resolve_loaded_section_gate_state_recovers_successful_loaded_project_even_if_sync_ready_false():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel

    sync_ready, legacy_loaded = WaterProfilePanel._resolve_loaded_section_gate_state(
        {"sync_ready": False, "state_text": "状态：断面全成功，表1+表2已同步到表3"},
        3,
        calculated_node_count=3,
        result_row_count=2,
    )

    assert sync_ready is True
    assert legacy_loaded is True


def test_resolve_loaded_section_gate_state_keeps_explicit_false_for_stale_loaded_project():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel

    sync_ready, legacy_loaded = WaterProfilePanel._resolve_loaded_section_gate_state(
        {"sync_ready": False, "state_text": "状态：表1已更新，请重新执行断面批量计算"},
        3,
        calculated_node_count=3,
        result_row_count=2,
    )

    assert sync_ready is False
    assert legacy_loaded is False


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


def test_collect_pending_pressure_pipe_execute_members_accepts_real_split_parent_when_only_row_members_have_results():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root / "推求水面线"))
    from models.data_models import ChannelNode
    from models.enums import StructureType, InOutType
    from utils.pressure_pipe_extractor import PressurePipeDataExtractor

    def _make_node(
        row_index: int,
        flow_section: str,
        name: str,
        structure_type: str,
        in_out,
        flow: float,
    ) -> ChannelNode:
        node = ChannelNode()
        node.flow_section = flow_section
        node.name = name
        node.structure_type = StructureType.from_string(structure_type)
        node.in_out = in_out
        node.flow = flow
        node.station_MC = float(row_index * 10)
        node.x = float(row_index * 10)
        node.y = 0.0
        node.arc_length = 0.0
        node.velocity = 0.8
        node.water_depth = 1.0
        node.head_loss_siphon = 0.0
        node.section_params = {
            "D": 1.0,
            "in_out_raw": in_out.value if hasattr(in_out, "value") else str(in_out),
        }
        node.pressure_pipe_window_override = {}
        return node

    nodes = [
        _make_node(0, "1", "上游明渠", "明渠-梯形", InOutType.NORMAL, 0.0),
        *[
            _make_node(
                row_index,
                "1",
                "洞梁村",
                "有压管道",
                InOutType.INLET if row_index == 1 else (
                    InOutType.OUTLET if row_index == 17 else InOutType.NORMAL
                ),
                0.27,
            )
            for row_index in range(1, 18)
        ],
        _make_node(18, "1", "下游明渠", "明渠-梯形", InOutType.NORMAL, 0.0),
    ]

    settings = SimpleNamespace(channel_level="支渠")
    pipe_groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(nodes, settings=settings)
    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(nodes, settings=settings)
    chain_descriptors = WaterProfilePanel._build_pressure_pipe_chain_descriptors(panel, chains)
    source_lookup = WaterProfilePanel._build_pressure_chain_source_lookup(chain_descriptors)

    panel._prepare_pressure_pipe_dialog_context = (
        lambda _nodes, settings=None, show_xxpipe_warning=False: {
            "pipe_groups": pipe_groups,
            "chain_descriptors": chain_descriptors,
        }
    )
    panel._pressure_pipe_calc_records = {"records": []}

    for member in chain_descriptors[0]["members"]:
        target_row_index = int(getattr(member, "target_row_index", -1))
        nodes[target_row_index].section_params["pressure_pipe_window_override"] = {
            "enabled": True,
            "identity": getattr(member, "identity", ""),
            "storage_key": getattr(member, "storage_key", ""),
            "display_name": getattr(member, "display_name", ""),
            "group_mode": "chain_row_member",
            "target_row_index": target_row_index,
            "upstream_row_index": int(getattr(member, "upstream_row_index", -1)),
            "total_head_loss": 0.1,
        }

    assert [getattr(member, "identity", "") for member in source_lookup["1::洞梁村::rows2-18"]] == [
        f"flow1-row{row_index}"
        for row_index in range(2, 19)
    ]

    pending = WaterProfilePanel._collect_pending_pressure_pipe_execute_members(
        panel,
        nodes,
        settings=settings,
    )

    assert pending == []


def test_collect_pending_pressure_pipe_execute_members_accepts_real_same_name_long_tail_after_apply():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._pressure_pipe_calc_done = {}

    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root / "推求水面线"))
    from models.data_models import ChannelNode
    from models.enums import StructureType, InOutType
    from utils.pressure_pipe_extractor import PressurePipeDataExtractor

    def _make_node(
        row_index: int,
        flow_section: str,
        name: str,
        structure_type: str,
        in_out,
        flow: float,
    ) -> ChannelNode:
        node = ChannelNode()
        node.flow_section = flow_section
        node.name = name
        node.structure_type = StructureType.from_string(structure_type)
        node.in_out = in_out
        node.flow = flow
        node.station_MC = float(row_index * 10)
        node.x = float(row_index * 10)
        node.y = 0.0
        node.arc_length = 0.0
        node.velocity = 0.8
        node.water_depth = 1.0
        node.head_loss_friction = 0.0
        node.head_loss_bend = 0.0
        node.head_loss_local = 0.0
        node.head_loss_siphon = 0.0
        node.head_loss_total = 0.0
        node.head_loss_reserve = 0.0
        node.head_loss_gate = 0.0
        node.external_head_loss = None
        node.section_params = {
            "D": 1.0,
            "in_out_raw": in_out.value if hasattr(in_out, "value") else str(in_out),
        }
        node.pressure_pipe_window_override = {}
        node.pressure_pipe_named_group_result = {}
        node.pressure_pipe_row_identity = f"flow{flow_section}-row{row_index + 1}"
        return node

    nodes = [
        _make_node(0, "1", "上游明渠", "明渠-梯形", InOutType.NORMAL, 0.0),
        _make_node(1, "1", "洞梁村", "有压管道", InOutType.INLET, 0.27),
        _make_node(2, "1", "洞梁村", "有压管道", InOutType.OUTLET, 0.27),
        _make_node(3, "1", "穿路段", "定向钻", InOutType.INLET, 0.27),
        _make_node(4, "1", "穿路段", "定向钻", InOutType.OUTLET, 0.27),
        *[
            _make_node(
                row_index,
                "1",
                "洞梁村",
                "有压管道",
                InOutType.INLET if row_index == 5 else (
                    InOutType.OUTLET if row_index == 21 else InOutType.NORMAL
                ),
                0.27,
            )
            for row_index in range(5, 22)
        ],
        _make_node(22, "1", "下游明渠", "明渠-梯形", InOutType.NORMAL, 0.0),
    ]

    settings = SimpleNamespace(channel_level="支渠")
    pipe_groups = PressurePipeDataExtractor.extract_dialog_pipe_groups(nodes, settings=settings)
    chains = PressurePipeDataExtractor.extract_continuous_pressure_chains(nodes, settings=settings)
    chain_descriptors = WaterProfilePanel._build_pressure_pipe_chain_descriptors(panel, chains)

    panel._prepare_pressure_pipe_dialog_context = (
        lambda _nodes, settings=None, show_xxpipe_warning=False: {
            "pipe_groups": pipe_groups,
            "chain_descriptors": chain_descriptors,
        }
    )

    row_records = []
    for member in chain_descriptors[0]["members"]:
        member_type = str(getattr(member, "member_type", "") or "").strip()
        member_role = str(getattr(member, "member_role", "") or "").strip()
        structure_type = str(getattr(member, "structure_type", "") or "").strip()
        record = {
            "identity": getattr(member, "identity", ""),
            "storage_key": getattr(member, "storage_key", ""),
            "display_name": getattr(member, "display_name", ""),
            "status": "success",
            "writeback_enabled": True,
            "data_mode": "链成员模式",
            "target_row_index": int(getattr(member, "target_row_index", -1)),
            "upstream_row_index": int(getattr(member, "upstream_row_index", -1)),
            "Q": 0.27,
            "D": 1.0,
            "total_length": 10.0,
            "pipe_velocity": 0.8,
            "friction_loss": 0.01,
            "total_bend_loss": 0.0,
            "local_loss": 0.0,
            "inlet_transition_loss": 0.0,
            "outlet_transition_loss": 0.0,
            "total_head_loss": 0.01,
            "friction_details": {},
            "bend_details": {},
            "local_details": {},
        }
        if member_role == "prefix_segment":
            record["group_mode"] = "chain_prefix_member"
        elif member_type == "single_row":
            record["group_mode"] = "chain_tunnel_member" if "隧洞" in structure_type else "chain_row_member"
        row_records.append(record)
        assert WaterProfilePanel._apply_pressure_pipe_member_result(
            panel,
            nodes[record["target_row_index"]],
            member,
            record,
        ) is True

    panel._pressure_pipe_calc_records = {"records": row_records}

    pending = WaterProfilePanel._collect_pending_pressure_pipe_execute_members(
        panel,
        nodes,
        settings=settings,
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


def test_collect_pending_pressure_pipe_execute_members_accepts_named_group_hidden_result():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    target_node = SimpleNamespace(
        flow_section="1",
        name="洞梁村",
        structure_type=SimpleNamespace(value="有压管道"),
        in_out=SimpleNamespace(value="出"),
        section_params={},
        pressure_pipe_window_override={},
        pressure_pipe_named_group_result={
            "identity": "1::洞梁村",
            "storage_key": "1::洞梁村",
            "display_name": "洞梁村",
            "structure_type": "有压管道",
            "total_head_loss": 10.4901,
            "applied_at": "2026-04-10 12:00:00",
            "calc_steps": "group-step",
            "target_row_index": 0,
        },
        head_loss_siphon=0.0,
        external_head_loss=None,
    )

    panel._prepare_pressure_pipe_dialog_context = lambda _nodes, settings=None, show_xxpipe_warning=False: {
        "pipe_groups": [
            SimpleNamespace(
                identity="1::洞梁村",
                display_name="洞梁村",
                group_mode="named_group",
                target_row_index=-1,
                outlet_row_index=0,
            )
        ],
        "chain_descriptors": [],
    }
    panel._pressure_pipe_calc_records = {
        "records": [
            {
                "identity": "1::洞梁村",
                "status": "success",
                "writeback_enabled": True,
                "group_mode": "named_group",
                "target_row_index": 0,
                "total_head_loss": 10.4901,
            }
        ]
    }

    pending = WaterProfilePanel._collect_pending_pressure_pipe_execute_members(
        panel,
        [target_node],
        settings=SimpleNamespace(),
    )

    assert pending == []


def test_collect_pending_pressure_pipe_execute_members_skips_split_named_group_parent():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    parent_identity = "1::洞梁村::rows2-4"
    row_identities = ["flow1-row2", "flow1-row3", "flow1-row4"]

    upstream = SimpleNamespace(
        name="上游明渠",
        structure_type=SimpleNamespace(value="明渠-梯形"),
        section_params={},
        pressure_pipe_window_override={},
        head_loss_siphon=0.0,
    )
    row_nodes = []
    for identity in row_identities:
        row_nodes.append(
            SimpleNamespace(
                name="洞梁村",
                structure_type=SimpleNamespace(value="有压管道"),
                section_params={
                    "pressure_pipe_window_override": {
                        "enabled": True,
                        "identity": identity,
                        "storage_key": identity,
                        "display_name": "洞梁村",
                        "group_mode": "chain_row_member",
                        "target_row_index": len(row_nodes) + 1,
                        "upstream_row_index": len(row_nodes),
                        "total_head_loss": 0.12 + len(row_nodes) * 0.01,
                    }
                },
                pressure_pipe_window_override={},
                head_loss_siphon=0.0,
            )
        )

    chain_members = [
        SimpleNamespace(
            identity=identity,
            display_name=f"洞梁村（第{idx + 1}段）",
            member_type="single_row",
            member_role="regular_segment",
            structure_type="有压管道",
            target_row_index=idx + 1,
            upstream_row_index=idx,
            should_generate_row_loss=True,
            is_anchor_member=False,
        )
        for idx, identity in enumerate(row_identities)
    ]
    split_group = SimpleNamespace(
        identity=parent_identity,
        display_name="洞梁村",
        group_mode="named_group",
        target_row_index=3,
        outlet_row_index=3,
        split_to_row_members=True,
        split_row_member_identities=list(row_identities),
    )
    panel._prepare_pressure_pipe_dialog_context = lambda _nodes, settings=None, show_xxpipe_warning=False: {
        "pipe_groups": [split_group],
        "chain_descriptors": [{"members": chain_members}],
    }
    panel._pressure_pipe_calc_records = {
        "records": [
            {
                "identity": identity,
                "status": "success",
                "writeback_enabled": True,
                "group_mode": "chain_row_member",
                "target_row_index": idx + 1,
                "total_head_loss": 0.12 + idx * 0.01,
            }
            for idx, identity in enumerate(row_identities)
        ]
    }

    pending = WaterProfilePanel._collect_pending_pressure_pipe_execute_members(
        panel,
        [upstream, *row_nodes],
        settings=None,
    )

    assert pending == []


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


def test_pressure_pipe_calculator_skips_named_group_total_when_split_to_row_members():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    module.CALCULATOR_AVAILABLE = True
    module.InfoBar = _FakeInfoBar
    module.InfoBarPosition = SimpleNamespace(TOP="top")
    module.QDialog = SimpleNamespace(Accepted=1)
    module.normalize_pressure_pipe_calc_records = lambda data: data
    module.build_pressure_pipe_transition_note = lambda **kwargs: ""

    parent_identity = "1::洞梁村::rows2-4"
    row_identities = ["flow1-row2", "flow1-row3", "flow1-row4"]
    parent_group = SimpleNamespace(
        name="洞梁村",
        display_name="洞梁村",
        storage_key=parent_identity,
        identity=parent_identity,
        group_mode="named_group",
        split_to_row_members=True,
        split_row_member_identities=list(row_identities),
        route_key="flow1-route1",
        route_display_name="赛金连续整线",
        route_start_row_index=1,
        route_end_row_index=3,
        row_indices=[1, 2, 3],
        target_row_index=3,
        upstream_row_index=0,
        outlet_row_index=3,
        segment_start_mc=10.0,
        segment_end_mc=50.0,
        rows=[],
        ip_points=[{"x": 10.0, "y": 0.0}, {"x": 50.0, "y": 0.0}],
        design_flow=0.27,
        diameter=1.0,
        material_key="预应力钢筒混凝土管",
        inlet_transition_form="反弯扭曲面",
        outlet_transition_form="反弯扭曲面",
        inlet_transition_zeta=0.10,
        outlet_transition_zeta=0.20,
        has_inlet_transition=True,
        has_outlet_transition=True,
        inlet_transition_reason="",
        outlet_transition_reason="",
        upstream_velocity=1.0,
        downstream_velocity=1.0,
        is_valid=lambda: True,
        get_validation_message=lambda: "",
    )
    chain_members = [
        SimpleNamespace(
            identity=identity,
            storage_key=identity,
            display_name=f"洞梁村（第{idx + 1}段）",
            base_display_name="洞梁村",
            flow_section="1",
            structure_type="有压管道",
            member_role="regular_segment",
            member_type="single_row",
            target_row_index=idx + 1,
            upstream_row_index=idx,
            should_generate_row_loss=True,
            is_anchor_member=False,
            group=SimpleNamespace(
                identity=identity,
                storage_key=identity,
                display_name=f"洞梁村（第{idx + 1}段）",
                route_key="flow1-route1",
                route_display_name="赛金连续整线",
                target_row_index=idx + 1,
                upstream_row_index=idx,
            ),
        )
        for idx, identity in enumerate(row_identities)
    ]

    class _FakeAcceptedDialog:
        def __init__(self, parent=None, pipe_groups=None, manager=None, **kwargs):
            self._longitudinal = {}

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
        total_length=40.0,
        pipe_velocity=0.8,
        friction_loss=0.2,
        total_bend_loss=0.03,
        inlet_transition_loss=0.01,
        outlet_transition_loss=0.01,
        total_head_loss=0.25,
        calc_steps="group",
        data_mode="平面模式",
        has_inlet_transition=True,
        has_outlet_transition=True,
        inlet_transition_reason="",
        outlet_transition_reason="",
        friction_details={},
        bend_details={},
    )
    pressure_calc_mod.calc_total_head_loss_with_spatial = pressure_calc_mod.calc_total_head_loss
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

    nodes = [
        SimpleNamespace(structure_type="明渠-梯形", name="上游明渠"),
        SimpleNamespace(structure_type="有压管道", name="洞梁村"),
        SimpleNamespace(structure_type="有压管道", name="洞梁村"),
        SimpleNamespace(structure_type="有压管道", name="洞梁村"),
    ]
    panel = _build_minimal_panel(WaterProfilePanel, nodes)
    panel._transition_topology_prepared = True
    panel._build_settings = lambda: SimpleNamespace(channel_level="支渠")
    panel._pressure_pipe_manager = _CaptureManager()
    panel._prepare_pressure_pipe_dialog_context = lambda _nodes, settings=None, show_xxpipe_warning=True: {
        "pipe_groups": [parent_group],
        "chain_descriptors": [{"members": chain_members}],
        "xxpipe_route_mode": True,
        "route_import_targets": {},
        "blocked_route_names": [],
    }
    panel._resolve_pressure_pipe_group_longitudinal_nodes = lambda group, longitudinal_nodes_dict, route_profile_segments_by_key=None: ([], [], "")
    panel._build_pressure_pipe_route_profile_segments = lambda pipe_groups, longitudinal_nodes_dict: {}
    panel._calculate_pressure_chain_single_row_member_result = lambda member, _nodes, _settings: {
        "identity": member.identity,
        "storage_key": member.storage_key,
        "display_name": member.display_name,
        "status": "success",
        "writeback_enabled": True,
        "group_mode": "chain_row_member",
        "target_row_index": member.target_row_index,
        "upstream_row_index": member.upstream_row_index,
        "total_head_loss": 0.11 + member.target_row_index * 0.01,
    }
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

    records = panel._pressure_pipe_calc_records["records"]
    row_records = [record for record in records if record["identity"] in row_identities]
    parent_records = [record for record in records if record["identity"] == parent_identity]

    assert [record["identity"] for record in row_records] == row_identities
    assert len(parent_records) == 1
    assert parent_records[0]["writeback_enabled"] is False



def test_collect_pending_pressure_pipe_execute_members_allows_completed_named_tail_row_members():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    group_identity = "1::洞梁村::rows2-4"

    upstream = SimpleNamespace(
        name="上游明渠",
        structure_type=SimpleNamespace(value="明渠-梯形"),
        section_params={},
        pressure_pipe_window_override={},
        head_loss_siphon=0.0,
    )

    def _make_named_row(identity: str, display_name: str, target_row_index: int, total_head_loss: float):
        override = {
            "enabled": True,
            "identity": identity,
            "storage_key": identity,
            "display_name": display_name,
            "group_mode": "chain_row_member",
            "target_row_index": target_row_index,
            "upstream_row_index": target_row_index - 1,
            "total_head_loss": total_head_loss,
        }
        return SimpleNamespace(
            name="洞梁村",
            structure_type=SimpleNamespace(value="有压管道"),
            section_params={"pressure_pipe_window_override": override},
            pressure_pipe_window_override={},
            head_loss_siphon=0.0,
        )

    member1 = SimpleNamespace(
        identity="flow1-row2",
        display_name="洞梁村（前段）",
        member_type="single_row",
        member_role="regular_segment",
        structure_type="有压管道",
        target_row_index=1,
        upstream_row_index=0,
        should_generate_row_loss=True,
        is_anchor_member=False,
        source_identity_aliases=[group_identity],
    )
    member2 = SimpleNamespace(
        identity="flow1-row3",
        display_name="洞梁村（中段1）",
        member_type="single_row",
        member_role="regular_segment",
        structure_type="有压管道",
        target_row_index=2,
        upstream_row_index=1,
        should_generate_row_loss=True,
        is_anchor_member=False,
        source_identity_aliases=[group_identity],
    )
    member3 = SimpleNamespace(
        identity="flow1-row4",
        display_name="洞梁村（后段）",
        member_type="single_row",
        member_role="regular_segment",
        structure_type="有压管道",
        target_row_index=3,
        upstream_row_index=2,
        should_generate_row_loss=True,
        is_anchor_member=False,
        source_identity_aliases=[group_identity],
    )
    panel._prepare_pressure_pipe_dialog_context = lambda _nodes, settings=None, show_xxpipe_warning=False: {
        "pipe_groups": [
            SimpleNamespace(
                identity=group_identity,
                display_name="洞梁村",
                group_mode="named_group",
                target_row_index=3,
                outlet_row_index=3,
            )
        ],
        "chain_descriptors": [{"members": [member1, member2, member3]}],
    }
    panel._build_pressure_pipe_execute_record_map = lambda: {
        "flow1-row2": {
            "identity": "flow1-row2",
            "status": "success",
            "writeback_enabled": True,
            "group_mode": "chain_row_member",
            "target_row_index": 1,
            "total_head_loss": 0.1021,
        },
        "flow1-row3": {
            "identity": "flow1-row3",
            "status": "success",
            "writeback_enabled": True,
            "group_mode": "chain_row_member",
            "target_row_index": 2,
            "total_head_loss": 0.0864,
        },
        "flow1-row4": {
            "identity": "flow1-row4",
            "status": "success",
            "writeback_enabled": True,
            "group_mode": "chain_row_member",
            "target_row_index": 3,
            "total_head_loss": 0.0913,
        },
    }

    pending = WaterProfilePanel._collect_pending_pressure_pipe_execute_members(
        panel,
        [
            upstream,
            _make_named_row("flow1-row2", "洞梁村（前段）", 1, 0.1021),
            _make_named_row("flow1-row3", "洞梁村（中段1）", 2, 0.0864),
            _make_named_row("flow1-row4", "洞梁村（后段）", 3, 0.0913),
        ],
        settings=None,
    )

    assert pending == []


def test_collect_pending_pressure_pipe_execute_members_ignores_tunnel_only_chain_without_pressure_pipe_groups():
    module = _load_panel_module()
    WaterProfilePanel = module.WaterProfilePanel
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    tunnel_member = SimpleNamespace(
        identity="flow1-row3-tunnel",
        display_name="龙塘隧洞",
        member_type="single_row",
        member_role="special_segment",
        structure_type="隧洞",
        target_row_index=2,
        upstream_row_index=1,
        should_generate_row_loss=True,
        is_anchor_member=False,
    )
    panel._prepare_pressure_pipe_dialog_context = lambda _nodes, settings=None, show_xxpipe_warning=False: {
        "pipe_groups": [],
        "chain_descriptors": [{"members": [tunnel_member]}],
    }
    panel._build_pressure_pipe_execute_record_map = lambda: {}

    pending = WaterProfilePanel._collect_pending_pressure_pipe_execute_members(
        panel,
        [
            SimpleNamespace(name="上游明渠", structure_type=SimpleNamespace(value="明渠-梯形"), section_params={}),
            SimpleNamespace(name="下游明渠", structure_type=SimpleNamespace(value="明渠-梯形"), section_params={}),
            SimpleNamespace(name="龙塘隧洞", structure_type=SimpleNamespace(value="隧洞"), section_params={}),
        ],
        settings=None,
    )

    assert pending == []
