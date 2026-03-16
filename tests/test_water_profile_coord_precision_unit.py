# -*- coding: utf-8 -*-
"""表3 坐标精度保真相关单元测试。"""

import importlib.util
import sys
import types
from contextlib import contextmanager
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
        "InfoBar", "InfoBarPosition", "DropDownPushButton", "RoundMenu",
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

    enums_mod = types.ModuleType("models.enums")
    enums_mod.StructureType = type("StructureType", (), {})
    enums_mod.InOutType = type("InOutType", (), {})
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
        spec = importlib.util.spec_from_file_location("wp_panel_coord_precision_test", panel_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, old_module in saved_modules.items():
            if old_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module


class _FakeItem:
    def __init__(self, text=""):
        self._text = str(text)
        self._flags = 0xFFFF
        self._data = {}
        self.alignment = None
        self.foreground = None
        self.tooltip = ""

    def text(self):
        return self._text

    def setText(self, text):
        self._text = str(text)

    def flags(self):
        return self._flags

    def setFlags(self, flags):
        self._flags = flags

    def setTextAlignment(self, alignment):
        self.alignment = alignment

    def setForeground(self, foreground):
        self.foreground = foreground

    def setToolTip(self, tooltip):
        self.tooltip = tooltip

    def data(self, role):
        return self._data.get(role)

    def setData(self, role, value):
        self._data[role] = value


class _FakeTable:
    def __init__(self, column_count):
        self._column_count = column_count
        self._rows = []

    def rowCount(self):
        return len(self._rows)

    def columnCount(self):
        return self._column_count

    def setRowCount(self, count):
        while len(self._rows) < count:
            self._rows.append([None] * self._column_count)
        while len(self._rows) > count:
            self._rows.pop()

    def insertRow(self, row):
        self._rows.insert(row, [None] * self._column_count)

    def setItem(self, row, col, item):
        self._rows[row][col] = item

    def item(self, row, col):
        if row < 0 or row >= len(self._rows):
            return None
        if col < 0 or col >= self._column_count:
            return None
        return self._rows[row][col]


class _FakeStructTypeValue:
    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, _FakeStructTypeValue) and self.value == other.value


class _FakeStructureType:
    TRANSITION = _FakeStructTypeValue("渐变段")
    INVERTED_SIPHON = _FakeStructTypeValue("倒虹吸")
    PRESSURE_PIPE = _FakeStructTypeValue("有压管道")

    @staticmethod
    def from_string(text):
        return _FakeStructTypeValue(str(text))

    @staticmethod
    def is_diversion_gate(struct_type):
        return "闸" in getattr(struct_type, "value", "") or "分水" in getattr(struct_type, "value", "")


class _FakeInOutType:
    @staticmethod
    def from_string(text):
        return SimpleNamespace(value=str(text))


def _make_basic_panel(module):
    module.QTableWidgetItem = _FakeItem
    module.QColor = lambda value: value
    module.Qt = SimpleNamespace(AlignCenter=0x0004, ItemIsEditable=0x0002, UserRole=0x0100)

    panel = module.WaterProfilePanel.__new__(module.WaterProfilePanel)
    panel.node_table = _FakeTable(len(module.NODE_ALL_HEADERS))
    panel._node_structure_heights = {}
    panel._node_chamfer_params = {}
    panel._node_u_params = {}
    panel._node_velocity_increased = {}
    panel._pressure_turn_radius_fallback_groups = set()
    panel._push_node_table_undo = lambda: None
    panel._refresh_pressure_pipe_controls = lambda: None
    panel._is_table1_source_row = lambda row: module.WaterProfilePanel._is_table1_source_row(panel, row)
    panel._sf = lambda value, default=0.0: float(value) if str(value).strip() else default
    panel._fval = lambda _widget, default=0.0: default
    panel._parse_flow_values = lambda _text: [5.0]
    panel.design_flow_edit = SimpleNamespace(text=lambda: "5.0")
    panel.turn_radius_edit = object()
    panel.roughness_edit = object()
    return panel


def _make_node(**overrides):
    defaults = {
        "flow_section": "1",
        "name": "",
        "structure_type": _FakeStructTypeValue("明渠-矩形"),
        "section_params": {},
        "is_transition": False,
        "is_auto_inserted_channel": False,
        "is_inverted_siphon": False,
        "is_diversion_gate": False,
        "is_pressure_pipe": False,
        "from_table1_source": True,
        "source_x_text": "",
        "source_y_text": "",
        "x": 0.0,
        "y": 0.0,
        "turn_radius": 0.0,
        "turn_angle": 0.0,
        "tangent_length": 0.0,
        "arc_length": 0.0,
        "curve_length": 0.0,
        "straight_distance": 0.0,
        "station_ip": None,
        "station_BC": None,
        "station_MC": None,
        "station_EC": None,
        "roughness": 0.014,
        "slope_i": 1 / 3000,
        "flow": 5.0,
        "water_depth": 0.0,
        "velocity": 0.0,
        "head_loss_transition": 0.0,
        "head_loss_bend": 0.0,
        "head_loss_friction": 0.0,
        "head_loss_reserve": 0.0,
        "head_loss_gate": 0.0,
        "head_loss_siphon": 0.0,
        "head_loss_total": 0.0,
        "head_loss_cumulative": 0.0,
        "water_level": 0.0,
        "bottom_elevation": 0.0,
        "top_elevation": 0.0,
        "velocity_increased": 0.0,
        "external_head_loss": None,
        "get_structure_type_str": lambda: "明渠-矩形",
        "get_in_out_str": lambda: "",
        "get_ip_str": lambda: "IP0",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@contextmanager
def _fake_batch_update(_table):
    yield


def test_add_node_row_preserves_source_coordinate_text_in_payload():
    module = _load_panel_module()
    panel = _make_basic_panel(module)

    module.WaterProfilePanel._add_node_row(
        panel,
        ["1", "", "明渠-矩形", "", "", "649606.177086", "3377745.982674"],
        _skip_undo=True,
        _from_table1_source=True,
    )

    payload = panel.node_table.item(0, 0).data(module.Qt.UserRole)
    assert payload[module.SOURCE_COORD_X_ROLE_KEY] == "649606.177086"
    assert payload[module.SOURCE_COORD_Y_ROLE_KEY] == "3377745.982674"
    assert payload["_from_table1_source"] is True


def test_update_table_from_nodes_full_impl_keeps_exact_source_coordinate_text():
    module = _load_panel_module()
    panel = _make_basic_panel(module)

    source_node = _make_node(
        x=649606.177086,
        y=3377745.982674,
        source_x_text="649606.177086",
        source_y_text="3377745.982674",
    )

    module.WaterProfilePanel._update_table_from_nodes_full_impl(panel, [source_node])

    assert panel.node_table.item(0, 5).text() == "649606.177086"
    assert panel.node_table.item(0, 6).text() == "3377745.982674"
    payload = panel.node_table.item(0, 0).data(module.Qt.UserRole)
    assert payload[module.SOURCE_COORD_X_ROLE_KEY] == "649606.177086"
    assert payload[module.SOURCE_COORD_Y_ROLE_KEY] == "3377745.982674"


def test_neighbor_precision_uses_higher_decimal_count_from_source_rows():
    module = _load_panel_module()
    panel = _make_basic_panel(module)

    nodes = [
        _make_node(source_x_text="649606.177086", source_y_text="3377745.982674"),
        _make_node(
            from_table1_source=False,
            is_auto_inserted_channel=True,
            source_x_text="",
            source_y_text="",
        ),
        _make_node(source_x_text="649480.48300012", source_y_text="3377634.27700012"),
    ]

    x_precision = module.WaterProfilePanel._resolve_neighbor_coord_precision(panel, nodes, 1, "x")
    y_precision = module.WaterProfilePanel._resolve_neighbor_coord_precision(panel, nodes, 1, "y")
    fallback_precision = module.WaterProfilePanel._resolve_neighbor_coord_precision(panel, [_make_node()], 0, "x")

    assert x_precision == 8
    assert y_precision == 8
    assert fallback_precision == 6


def test_apply_node_table_text_snapshot_refreshes_source_coordinate_payload():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    panel._table_batch_update = _fake_batch_update
    panel._apply_table1_source_row_lock_flags = lambda: None

    panel.node_table.setRowCount(1)
    first_item = _FakeItem("1")
    first_item.setData(
        module.Qt.UserRole,
        {
            "_from_table1_source": True,
            module.SOURCE_COORD_X_ROLE_KEY: "old-x",
            module.SOURCE_COORD_Y_ROLE_KEY: "old-y",
        },
    )
    panel.node_table.setItem(0, 0, first_item)
    panel.node_table.setItem(0, 5, _FakeItem("old-x"))
    panel.node_table.setItem(0, 6, _FakeItem("old-y"))

    snapshot = [[""] * len(module.NODE_ALL_HEADERS)]
    snapshot[0][0] = "1"
    snapshot[0][2] = "明渠-矩形"
    snapshot[0][5] = "649606.177086"
    snapshot[0][6] = "3377745.982674"

    module.WaterProfilePanel._apply_node_table_text_snapshot(panel, snapshot)

    payload = panel.node_table.item(0, 0).data(module.Qt.UserRole)
    assert payload[module.SOURCE_COORD_X_ROLE_KEY] == "649606.177086"
    assert payload[module.SOURCE_COORD_Y_ROLE_KEY] == "3377745.982674"


def test_build_nodes_from_table_reads_source_coordinate_text_without_rounding():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    module.CALCULATOR_AVAILABLE = True
    class _BuildNode:
        def __init__(self):
            self.section_params = {}
            self.is_transition = False
            self.is_auto_inserted_channel = False
            self.is_diversion_gate = False
            self.is_inverted_siphon = False
            self.is_pressure_pipe = False
            self.in_out = None
            self.external_head_loss = None

    module.ChannelNode = _BuildNode
    module.StructureType = _FakeStructureType
    module.InOutType = _FakeInOutType

    panel.node_table.setRowCount(1)
    for col, text in (
        (0, "1"),
        (1, ""),
        (2, "明渠-矩形"),
        (5, "649606.177086"),
        (6, "3377745.982674"),
        (24, "0.014"),
        (25, "3000"),
        (26, "5.0"),
    ):
        panel.node_table.setItem(0, col, _FakeItem(text))
    panel.node_table.item(0, 0).setData(
        module.Qt.UserRole,
        {
            "_from_table1_source": True,
            module.SOURCE_COORD_X_ROLE_KEY: "649606.177086",
            module.SOURCE_COORD_Y_ROLE_KEY: "3377745.982674",
        },
    )

    nodes = module.WaterProfilePanel._build_nodes_from_table(panel)

    assert len(nodes) == 1
    assert nodes[0].source_x_text == "649606.177086"
    assert nodes[0].source_y_text == "3377745.982674"
    assert nodes[0].x == 649606.177086
    assert nodes[0].y == 3377745.982674
