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


class _FakeLineEdit:
    def __init__(self, text=""):
        self._text = str(text)

    def text(self):
        return self._text

    def setText(self, text):
        self._text = str(text)

    def setPlaceholderText(self, _text):
        pass


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
    DIRECTIONAL_DRILL = _FakeStructTypeValue("定向钻")
    PIPE_JACKING = _FakeStructTypeValue("顶管")

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
    module.Qt = SimpleNamespace(
        AlignCenter=0x0004,
        ItemIsEditable=0x0002,
        ItemIsEnabled=0x0001,
        ItemIsSelectable=0x0004,
        UserRole=0x0100,
    )

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
    panel._fval = (
        lambda widget, default=0.0: (
            float(widget.text().strip())
            if getattr(widget, "text", None) and str(widget.text()).strip()
            else default
        )
    )
    panel._parse_flow_values = lambda _text: [5.0]
    panel.design_flow_edit = SimpleNamespace(text=lambda: "5.0")
    panel.channel_level_combo = SimpleNamespace(currentText=lambda: "支管")
    panel.turn_radius_edit = _FakeLineEdit("")
    panel.roughness_edit = _FakeLineEdit("")
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


def _make_batch_result(**overrides):
    defaults = {
        "flow_section": "1",
        "building_name": "甘家沟充水渠",
        "section_type": "明渠-矩形",
        "raw_result": {},
        "coord_X": 3441081.797491,
        "coord_Y": 639354.23486,
        "B": 1.5,
        "D": "",
        "R": "",
        "m": 0,
        "n": 0.014,
        "slope_inv": 2000,
        "Q": 1.0,
        "use_increase": False,
        "h": 0.789,
        "V": 0.845,
        "V_max": 0.0,
        "A": 1.183,
        "X": 3.078,
        "R_hydraulic": 0.385,
        "H_total": 1.19,
        "turn_radius": 0.0,
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


def test_build_nodes_from_table_prefers_ip_cell_metadata_for_special_entry_exit_rows():
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
        (1, "黄角坝"),
        (2, "隧洞-圆形"),
        (3, "进"),
        (4, "黄角坝隧进"),
        (5, "649606.177086"),
        (6, "3377745.982674"),
        (24, "0.014"),
        (25, "3000"),
        (26, "5.0"),
    ):
        panel.node_table.setItem(0, col, _FakeItem(text))

    panel.node_table.item(0, 4).setData(
        module.Qt.UserRole,
        {
            "_raw_ip_number": 5,
            "_display_ip_number": None,
        },
    )

    nodes = module.WaterProfilePanel._build_nodes_from_table(panel)

    assert len(nodes) == 1
    assert nodes[0].ip_number == 5
    assert nodes[0].display_ip_number is None


def test_update_table_from_nodes_full_impl_shows_row_level_loss_for_unnamed_pressure_pipe_rows():
    module = _load_panel_module()
    panel = _make_basic_panel(module)

    anonymous_pipe = _make_node(
        structure_type=_FakeStructureType.PRESSURE_PIPE,
        is_pressure_pipe=True,
        head_loss_bend=0.0100,
        head_loss_friction=0.0215,
        head_loss_total=0.0315,
        get_structure_type_str=lambda: "有压管道",
        get_in_out_str=lambda: "",
    )

    module.WaterProfilePanel._update_table_from_nodes_full_impl(panel, [anonymous_pipe])

    assert panel.node_table.item(0, 38).text() == "0.0315"
    payload = panel.node_table.item(0, 0).data(module.Qt.UserRole)
    assert payload["_pressure_pipe_row_identity"]


def test_build_nodes_from_table_preserves_unnamed_pressure_pipe_display_loss_without_double_counting():
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
        (0, "2"),
        (1, ""),
        (2, "有压管道"),
        (24, "0.014"),
        (25, "3000"),
        (26, "1.8"),
        (34, "0.0100"),
        (35, "0.0215"),
        (38, "0.0315"),
        (39, "0.0315"),
    ):
        panel.node_table.setItem(0, col, _FakeItem(text))
    panel.node_table.item(0, 0).setData(
        module.Qt.UserRole,
        {"_pressure_pipe_row_identity": "flow2-row1"},
    )

    nodes = module.WaterProfilePanel._build_nodes_from_table(panel)

    assert len(nodes) == 1
    assert getattr(nodes[0], "pressure_pipe_row_identity", "") == "flow2-row1"
    assert getattr(nodes[0], "head_loss_siphon", 0.0) == 0.0
    assert getattr(nodes[0], "_pressure_pipe_display_loss", 0.0) == 0.0315


def test_build_nodes_from_table_preserves_explicit_zero_turn_radius_for_pressure_pipe():
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

    panel.node_table.setRowCount(2)
    for col, text in (
        (0, "1"),
        (1, ""),
        (2, "有压管道"),
        (21, "1.2"),
        (24, "0.014"),
        (25, "3000"),
        (26, "5.0"),
    ):
        panel.node_table.setItem(0, col, _FakeItem(text))
    for col, text in (
        (0, "1"),
        (1, ""),
        (2, "有压管道"),
        (7, "0"),
        (21, "1.2"),
        (24, "0.014"),
        (25, "3000"),
        (26, "5.0"),
    ):
        panel.node_table.setItem(1, col, _FakeItem(text))

    nodes = module.WaterProfilePanel._build_nodes_from_table(panel)

    assert len(nodes) == 2
    assert nodes[1].turn_radius == 0.0
    assert getattr(nodes[1], "turn_radius_is_explicit", False) is True


def test_build_nodes_from_table_restores_compound_trapezoid_hidden_params():
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
        (2, "明渠-复式梯形"),
        (20, "4.8"),
        (24, "0.015"),
        (25, "3000"),
        (26, "4.2"),
        (27, "2.100"),
        (28, "10.822"),
        (29, "11.335"),
        (30, "0.955"),
    ):
        panel.node_table.setItem(0, col, _FakeItem(text))
    panel.node_table.item(0, 0).setData(
        module.Qt.UserRole,
        {
            "_from_table1_source": True,
            "_compound_trapezoid_params": {
                "m1": 0.5,
                "B1": 3.4,
                "m2": 1.25,
                "B2": 4.8,
                "m3": 1.5,
                "h1": 1.2,
            },
        },
    )

    nodes = module.WaterProfilePanel._build_nodes_from_table(panel)

    assert len(nodes) == 1
    assert nodes[0].structure_type.value == "明渠-复式梯形"
    assert nodes[0].section_params["B"] == 4.8
    assert nodes[0].section_params["m1"] == 0.5
    assert nodes[0].section_params["B1"] == 3.4
    assert nodes[0].section_params["m2"] == 1.25
    assert nodes[0].section_params["B2"] == 4.8
    assert nodes[0].section_params["m3"] == 1.5
    assert nodes[0].section_params["h1"] == 1.2


def test_build_nodes_from_table_defaults_blank_turn_radius_to_zero_for_regular_row():
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

    panel.node_table.setRowCount(2)
    for row in range(2):
        for col, text in (
            (0, "1"),
            (1, ""),
            (2, "明渠-矩形"),
            (24, "0.014"),
            (25, "3000"),
            (26, "5.0"),
        ):
            panel.node_table.setItem(row, col, _FakeItem(text))

    nodes = module.WaterProfilePanel._build_nodes_from_table(panel)

    assert len(nodes) == 2
    assert nodes[1].turn_radius == 0.0
    assert getattr(nodes[1], "turn_radius_is_explicit", False) is False


def test_import_from_batch_defaults_blank_turn_radius_text_to_zero():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    module.SHARED_DATA_AVAILABLE = True
    module.CALCULATOR_AVAILABLE = False
    module.QSignalBlocker = lambda *_args, **_kwargs: object()
    module.InfoBar = SimpleNamespace(
        success=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)
    module.auto_resize_table = lambda *_args, **_kwargs: None
    module.get_shared_data_manager = lambda: SimpleNamespace(
        get_batch_results=lambda: [
            _make_batch_result(
                section_type="明渠-矩形",
                turn_radius=0.0,
                raw_result={},
            )
        ]
    )

    panel._sync_batch_settings = lambda: None
    panel._clear_nodes = lambda: panel.node_table.setRowCount(0)
    panel._choose_roughness_value = lambda *_args, **_kwargs: None
    panel._update_siphon_roughness_overview = lambda *_args, **_kwargs: None
    panel._update_pressure_pipe_roughness_overview = lambda *_args, **_kwargs: None
    panel._on_design_flow_changed = lambda: None
    panel._apply_table1_source_row_lock_flags = lambda: None
    panel._refresh_pressure_pipe_controls = lambda: None
    panel._recalculate_geometry = lambda: None
    panel._info_parent = lambda: None
    panel.design_flow_edit = SimpleNamespace(text=lambda: "5.0", setText=lambda _text: None)

    module.WaterProfilePanel._import_from_batch(panel)

    assert panel.node_table.item(0, 7).text() == "0"
    assert panel.turn_radius_edit.text() == ""


def test_import_from_batch_keeps_turn_radius_entry_blank_for_mixed_positive_values():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    module.SHARED_DATA_AVAILABLE = True
    module.CALCULATOR_AVAILABLE = False
    module.QSignalBlocker = lambda *_args, **_kwargs: object()
    module.InfoBar = SimpleNamespace(
        success=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)
    module.auto_resize_table = lambda *_args, **_kwargs: None
    module.get_shared_data_manager = lambda: SimpleNamespace(
        get_batch_results=lambda: [
            _make_batch_result(section_type="明渠-矩形", turn_radius=30.0, raw_result={"turn_radius_text": "30"}),
            _make_batch_result(section_type="明渠-矩形", turn_radius=40.0, raw_result={"turn_radius_text": "40"}),
        ]
    )

    panel._sync_batch_settings = lambda: None
    panel._clear_nodes = lambda: panel.node_table.setRowCount(0)
    panel._choose_roughness_value = lambda *_args, **_kwargs: None
    panel._update_siphon_roughness_overview = lambda *_args, **_kwargs: None
    panel._update_pressure_pipe_roughness_overview = lambda *_args, **_kwargs: None
    panel._on_design_flow_changed = lambda: None
    panel._apply_table1_source_row_lock_flags = lambda: None
    panel._refresh_pressure_pipe_controls = lambda: None
    panel._recalculate_geometry = lambda: None
    panel._info_parent = lambda: None
    panel.design_flow_edit = SimpleNamespace(text=lambda: "5.0", setText=lambda _text: None)

    module.WaterProfilePanel._import_from_batch(panel)

    assert panel.turn_radius_edit.text() == ""
    assert panel.node_table.item(0, 7).text() == "30"
    assert panel.node_table.item(1, 7).text() == "40"


def test_import_from_batch_sets_turn_radius_entry_for_uniform_positive_values():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    module.SHARED_DATA_AVAILABLE = True
    module.CALCULATOR_AVAILABLE = False
    module.QSignalBlocker = lambda *_args, **_kwargs: object()
    module.InfoBar = SimpleNamespace(
        success=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)
    module.auto_resize_table = lambda *_args, **_kwargs: None
    module.get_shared_data_manager = lambda: SimpleNamespace(
        get_batch_results=lambda: [
            _make_batch_result(section_type="明渠-矩形", turn_radius=30.0, raw_result={"turn_radius_text": "30"}),
            _make_batch_result(section_type="明渠-矩形", turn_radius=30.0, raw_result={"turn_radius_text": "30"}),
        ]
    )

    panel._sync_batch_settings = lambda: None
    panel._clear_nodes = lambda: panel.node_table.setRowCount(0)
    panel._choose_roughness_value = lambda *_args, **_kwargs: None
    panel._update_siphon_roughness_overview = lambda *_args, **_kwargs: None
    panel._update_pressure_pipe_roughness_overview = lambda *_args, **_kwargs: None
    panel._on_design_flow_changed = lambda: None
    panel._apply_table1_source_row_lock_flags = lambda: None
    panel._refresh_pressure_pipe_controls = lambda: None
    panel._recalculate_geometry = lambda: None
    panel._info_parent = lambda: None
    panel.design_flow_edit = SimpleNamespace(text=lambda: "5.0", setText=lambda _text: None)

    module.WaterProfilePanel._import_from_batch(panel)

    assert panel.turn_radius_edit.text() == "30.0"


def test_update_table_from_nodes_full_impl_preserves_explicit_zero_turn_radius_text():
    module = _load_panel_module()
    panel = _make_basic_panel(module)

    source_node = _make_node(
        structure_type=_FakeStructureType.PRESSURE_PIPE,
        is_pressure_pipe=True,
        turn_radius=0.0,
        turn_radius_is_explicit=True,
        turn_radius_text="0",
        get_structure_type_str=lambda: "有压管道",
        get_in_out_str=lambda: "",
    )

    module.WaterProfilePanel._update_table_from_nodes_full_impl(panel, [source_node])

    assert panel.node_table.item(0, 7).text() == "0"


def test_update_table_from_nodes_inner_preserves_explicit_zero_turn_radius_text():
    module = _load_panel_module()
    panel = _make_basic_panel(module)

    source_node = _make_node(
        structure_type=_FakeStructureType.PRESSURE_PIPE,
        is_pressure_pipe=True,
        turn_radius=0.0,
        turn_radius_is_explicit=True,
        turn_radius_text="0",
        get_structure_type_str=lambda: "有压管道",
        get_in_out_str=lambda: "",
    )

    module.WaterProfilePanel._update_table_from_nodes_inner(panel, [source_node])

    assert panel.node_table.item(0, 7).text() == "0"


def test_recalculate_geometry_impl_preserves_explicit_zero_turn_radius_for_pressure_pipe():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    module.CALCULATOR_AVAILABLE = True
    module.ProjectSettings = SimpleNamespace(format_station=lambda value, _prefix="": f"{value:.3f}")

    class _FakeCalculator:
        def __init__(self, _settings):
            pass

        def calculate_geometry(self, _nodes):
            return None

        def preprocess_nodes(self, _nodes):
            return None

    module.WaterProfileCalculator = _FakeCalculator

    panel.node_table.setRowCount(2)
    for row, radius_text in ((0, ""), (1, "0")):
        panel.node_table.setItem(row, 2, _FakeItem("有压管道"))
        panel.node_table.setItem(row, 7, _FakeItem(radius_text))

    nodes = [
        _make_node(
            structure_type=_FakeStructureType.PRESSURE_PIPE,
            is_pressure_pipe=True,
            get_structure_type_str=lambda: "有压管道",
            get_in_out_str=lambda: "",
            get_ip_str=lambda: "IP0",
            station_ip=0.0,
            station_BC=0.0,
            station_MC=0.0,
            station_EC=0.0,
        ),
        _make_node(
            structure_type=_FakeStructureType.PRESSURE_PIPE,
            is_pressure_pipe=True,
            turn_radius=0.0,
            turn_radius_is_explicit=True,
            turn_radius_text="0",
            get_structure_type_str=lambda: "有压管道",
            get_in_out_str=lambda: "",
            get_ip_str=lambda: "IP1",
            station_ip=10.0,
            station_BC=10.0,
            station_MC=10.0,
            station_EC=10.0,
        ),
    ]

    panel._build_nodes_from_table = lambda: nodes
    panel._build_settings = lambda: SimpleNamespace(get_station_prefix=lambda: "")

    module.WaterProfilePanel._recalculate_geometry_impl(panel)

    assert panel.node_table.item(1, 7).text() == "0"


def test_apply_pressure_pipe_turn_radius_payload_skips_explicit_zero_rows_without_force_override():
    module = _load_panel_module()
    panel = _make_basic_panel(module)

    panel.node_table.setRowCount(1)
    panel.node_table.setItem(0, 7, _FakeItem("0"))
    panel._get_pressure_pipe_group_storage_key = lambda group: group.name
    panel._is_pressure_pipe_row_segment_group = lambda _group: False
    panel._set_table_cell_text_preserve_flags = (
        lambda row, col, text: panel.node_table.setItem(row, col, _FakeItem(text))
    )

    group = SimpleNamespace(name="组1", row_indices=[0])

    result = module.WaterProfilePanel._apply_pressure_pipe_turn_radius_payload(
        panel,
        [group],
        {"组1": {"turn_R": 12.0, "force_override": False}},
    )

    assert result["changed_cells"] == 0
    assert panel.node_table.item(0, 7).text() == "0"


def test_apply_pressure_pipe_manager_tunnel_config_to_group_prefers_table1_values():
    module = _load_panel_module()
    rows = [
        SimpleNamespace(roughness=None),
        SimpleNamespace(roughness=None),
    ]
    group = SimpleNamespace(
        structure_type=SimpleNamespace(value="隧洞-圆形"),
        segment_geometry_source="generated_tunnel",
        tunnel_slope_i=0.01,
        tunnel_roughness_n=0.018,
        tunnel_section_type="圆形隧洞",
        tunnel_section_params={"D": 2.6},
        rows=rows,
    )
    config = SimpleNamespace(
        segment_geometry_source="legacy_cache",
        tunnel_slope_i=0.002,
        tunnel_roughness_n=0.014,
        tunnel_section_type="圆拱直墙型隧洞",
        tunnel_section_params={"B": 3.2},
        tunnel_profile_mode="hydraulic_display",
    )

    module.WaterProfilePanel._apply_pressure_pipe_manager_tunnel_config_to_group(group, config)

    assert group.segment_geometry_source == "generated_tunnel"
    assert group.tunnel_slope_i == 0.01
    assert group.tunnel_roughness_n == 0.018
    assert group.tunnel_section_type == "圆形隧洞"
    assert group.tunnel_section_params == {"D": 2.6}
    assert group.tunnel_profile_mode == "hydraulic_display"
    assert rows[0].roughness == 0.018
    assert rows[1].roughness == 0.018


def test_apply_pressure_pipe_dialog_payloads_skips_tunnel_backfill_chain():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    panel._apply_pressure_pipe_d_override_payload = lambda _groups, _payload: 2
    panel._apply_pressure_pipe_turn_radius_payload = (
        lambda _groups, _payload: {"changed_cells": 3, "force_groups": 1, "fill_groups": 2}
    )
    panel._apply_pressure_pipe_tunnel_payload = (
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应再走隧洞 payload 回写主表"))
    )
    lock_calls = []
    panel._apply_table1_source_row_lock_flags = lambda: lock_calls.append("locked")

    result = module.WaterProfilePanel._apply_pressure_pipe_dialog_payloads(
        panel,
        [SimpleNamespace(name="组1")],
        {"组1": {"turn_R": 15.0}},
        {"组1": {"diameter": 1.6}},
    )

    assert result == {
        "changed_cells": 5,
        "d_changed": 2,
        "radius_changed": 3,
        "force_groups": 1,
        "fill_groups": 2,
    }
    assert lock_calls == ["locked"]


def test_insert_transitions_preserves_explicit_zero_turn_radius_text():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    module.CALCULATOR_AVAILABLE = True
    module.InfoBar = SimpleNamespace(
        error=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        success=lambda *args, **kwargs: None,
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)
    module.auto_resize_table = lambda *_args, **_kwargs: None
    module.fluent_question = lambda *_args, **_kwargs: True

    dialog_module_name = "app_渠系计算前端.water_profile.water_profile_dialogs"
    saved_dialog_module = sys.modules.get(dialog_module_name)
    dialog_module = types.ModuleType(dialog_module_name)

    class _FakeBatchChannelConfirmDialog:
        RESULT_CANCELLED = "cancelled"
        RESULT_TABLE_EDIT = "table_edit"

        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return 0

        def get_result(self):
            return {"mode": "manual", "params": {}}

    class _FakeOpenChannelDialog:
        def __init__(self, *_args, **_kwargs):
            self.apply_all_remaining = False

        def exec(self):
            return 0

        def get_result(self):
            return None

    dialog_module.BatchChannelConfirmDialog = _FakeBatchChannelConfirmDialog
    dialog_module.OpenChannelDialog = _FakeOpenChannelDialog
    dialog_module.OpenChannelParams = type("OpenChannelParams", (), {})
    sys.modules[dialog_module_name] = dialog_module

    class _FakeCalculator:
        def __init__(self, _settings):
            pass

        def preprocess_nodes(self, _nodes):
            return None

        def pre_scan_open_channels(self, _nodes):
            return []

        def prepare_transitions(self, nodes, _callback):
            return nodes

    module.WaterProfileCalculator = _FakeCalculator

    try:
        panel.node_table.setRowCount(2)
        panel._updating_cells = False
        panel._table_batch_update = _fake_batch_update
        panel.max_flow_edit = SimpleNamespace(text=lambda: "5.5")
        panel.design_flow_edit = SimpleNamespace(text=lambda: "5.0")
        panel._ensure_downstream_ready = lambda _action: True
        panel._build_settings = lambda: SimpleNamespace(
            validate=lambda: (True, ""),
            get_station_prefix=lambda: "",
        )
        panel._build_nodes_from_table = lambda: [
            _make_node(
                structure_type=_FakeStructureType.PRESSURE_PIPE,
                is_pressure_pipe=True,
                get_structure_type_str=lambda: "有压管道",
                get_in_out_str=lambda: "",
                get_ip_str=lambda: "IP0",
            ),
            _make_node(
                structure_type=_FakeStructureType.PRESSURE_PIPE,
                is_pressure_pipe=True,
                turn_radius=0.0,
                turn_radius_is_explicit=True,
                turn_radius_text="0",
                get_structure_type_str=lambda: "有压管道",
                get_in_out_str=lambda: "",
                get_ip_str=lambda: "IP1",
            ),
        ]

        module.WaterProfilePanel._insert_transitions(panel)

        assert panel.node_table.item(1, 7).text() == "0"
    finally:
        if saved_dialog_module is None:
            sys.modules.pop(dialog_module_name, None)
        else:
            sys.modules[dialog_module_name] = saved_dialog_module


def test_insert_transitions_defaults_blank_turn_radius_text_to_zero():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    module.CALCULATOR_AVAILABLE = True
    module.InfoBar = SimpleNamespace(
        error=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        success=lambda *args, **kwargs: None,
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)
    module.auto_resize_table = lambda *_args, **_kwargs: None
    module.fluent_question = lambda *_args, **_kwargs: True

    dialog_module_name = "app_渠系计算前端.water_profile.water_profile_dialogs"
    saved_dialog_module = sys.modules.get(dialog_module_name)
    dialog_module = types.ModuleType(dialog_module_name)

    class _FakeBatchChannelConfirmDialog:
        RESULT_CANCELLED = "cancelled"
        RESULT_TABLE_EDIT = "table_edit"

        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return 0

        def get_result(self):
            return {"mode": "manual", "params": {}}

    class _FakeOpenChannelDialog:
        def __init__(self, *_args, **_kwargs):
            self.apply_all_remaining = False

        def exec(self):
            return 0

        def get_result(self):
            return None

    dialog_module.BatchChannelConfirmDialog = _FakeBatchChannelConfirmDialog
    dialog_module.OpenChannelDialog = _FakeOpenChannelDialog
    dialog_module.OpenChannelParams = type("OpenChannelParams", (), {})
    sys.modules[dialog_module_name] = dialog_module

    class _FakeCalculator:
        def __init__(self, _settings):
            pass

        def preprocess_nodes(self, _nodes):
            return None

        def pre_scan_open_channels(self, _nodes):
            return []

        def prepare_transitions(self, nodes, _callback):
            return nodes

    module.WaterProfileCalculator = _FakeCalculator

    try:
        panel.node_table.setRowCount(2)
        panel._updating_cells = False
        panel._table_batch_update = _fake_batch_update
        panel.max_flow_edit = SimpleNamespace(text=lambda: "5.5")
        panel.design_flow_edit = SimpleNamespace(text=lambda: "5.0")
        panel._ensure_downstream_ready = lambda _action: True
        panel._build_settings = lambda: SimpleNamespace(
            validate=lambda: (True, ""),
            get_station_prefix=lambda: "",
        )
        panel._build_nodes_from_table = lambda: [
            _make_node(
                structure_type=_FakeStructureType.PRESSURE_PIPE,
                is_pressure_pipe=True,
                get_structure_type_str=lambda: "有压管道",
                get_in_out_str=lambda: "",
                get_ip_str=lambda: "IP0",
            ),
            _make_node(
                structure_type=_FakeStructureType.PRESSURE_PIPE,
                is_pressure_pipe=True,
                turn_radius=0.0,
                turn_radius_is_explicit=False,
                get_structure_type_str=lambda: "有压管道",
                get_in_out_str=lambda: "",
                get_ip_str=lambda: "IP1",
            ),
        ]

        module.WaterProfilePanel._insert_transitions(panel)

        assert panel.node_table.item(1, 7).text() == "0"
    finally:
        if saved_dialog_module is None:
            sys.modules.pop(dialog_module_name, None)
        else:
            sys.modules[dialog_module_name] = saved_dialog_module


def test_update_table_from_nodes_full_impl_hides_row_level_pressure_pipe_loss_outside_xxpipe():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    panel.channel_level_combo = SimpleNamespace(currentText=lambda: "支渠")

    anonymous_pipe = _make_node(
        structure_type=_FakeStructureType.PRESSURE_PIPE,
        is_pressure_pipe=True,
        head_loss_bend=0.0100,
        head_loss_friction=0.0215,
        head_loss_total=0.0315,
        get_structure_type_str=lambda: "有压管道",
        get_in_out_str=lambda: "",
    )

    module.WaterProfilePanel._update_table_from_nodes_full_impl(panel, [anonymous_pipe])

    assert panel.node_table.item(0, 38).text() == "-"
    payload = panel.node_table.item(0, 0).data(module.Qt.UserRole)
    assert module.PRESSURE_PIPE_ROW_ID_ROLE_KEY not in payload


def test_build_nodes_from_table_ignores_row_level_pressure_pipe_display_loss_outside_xxpipe():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    panel.channel_level_combo = SimpleNamespace(currentText=lambda: "支渠")
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
        (0, "2"),
        (1, ""),
        (2, "有压管道"),
        (24, "0.014"),
        (25, "3000"),
        (26, "1.8"),
        (34, "0.0100"),
        (35, "0.0215"),
        (38, "0.0315"),
        (39, "0.0315"),
    ):
        panel.node_table.setItem(0, col, _FakeItem(text))
    panel.node_table.item(0, 0).setData(
        module.Qt.UserRole,
        {"_pressure_pipe_row_identity": "flow2-row1"},
    )

    nodes = module.WaterProfilePanel._build_nodes_from_table(panel)

    assert len(nodes) == 1
    assert getattr(nodes[0], "head_loss_siphon", 0.0) == 0.0
    assert getattr(nodes[0], "_pressure_pipe_display_loss", 0.0) == 0.0


def test_import_from_batch_persists_use_increase_payload_for_open_channel_rows():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    module.SHARED_DATA_AVAILABLE = True
    module.CALCULATOR_AVAILABLE = False
    module.QSignalBlocker = lambda *_args, **_kwargs: object()
    module.InfoBar = SimpleNamespace(
        success=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)
    module.auto_resize_table = lambda *_args, **_kwargs: None
    module.get_shared_data_manager = lambda: SimpleNamespace(
        get_batch_results=lambda: [_make_batch_result(use_increase=False)]
    )

    panel._sync_batch_settings = lambda: None
    panel._clear_nodes = lambda: panel.node_table.setRowCount(0)
    panel._choose_roughness_value = lambda *_args, **_kwargs: None
    panel._update_siphon_roughness_overview = lambda *_args, **_kwargs: None
    panel._update_pressure_pipe_roughness_overview = lambda *_args, **_kwargs: None
    panel._on_design_flow_changed = lambda: None
    panel._apply_table1_source_row_lock_flags = lambda: None
    panel._refresh_pressure_pipe_controls = lambda: None
    panel._recalculate_geometry = lambda: None
    panel._info_parent = lambda: None
    panel.design_flow_edit = SimpleNamespace(text=lambda: "5.0", setText=lambda _text: None)

    module.WaterProfilePanel._import_from_batch(panel)

    payload = panel.node_table.item(0, 0).data(module.Qt.UserRole)
    assert payload[module.USE_INCREASE_ROLE_KEY] is False


def test_import_from_batch_preserves_explicit_zero_turn_radius_text():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    module.SHARED_DATA_AVAILABLE = True
    module.CALCULATOR_AVAILABLE = False
    module.QSignalBlocker = lambda *_args, **_kwargs: object()
    module.InfoBar = SimpleNamespace(
        success=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)
    module.auto_resize_table = lambda *_args, **_kwargs: None
    module.get_shared_data_manager = lambda: SimpleNamespace(
        get_batch_results=lambda: [
            _make_batch_result(
                section_type="有压管道",
                D=0.4,
                n=0.0,
                slope_inv=0,
                turn_radius=0.0,
                raw_result={"is_pressure_pipe": True, "turn_radius_text": "0"},
            )
        ]
    )

    panel._sync_batch_settings = lambda: None
    panel._clear_nodes = lambda: panel.node_table.setRowCount(0)
    panel._choose_roughness_value = lambda *_args, **_kwargs: None
    panel._update_siphon_roughness_overview = lambda *_args, **_kwargs: None
    panel._update_pressure_pipe_roughness_overview = lambda *_args, **_kwargs: None
    panel._on_design_flow_changed = lambda: None
    panel._apply_table1_source_row_lock_flags = lambda: None
    panel._refresh_pressure_pipe_controls = lambda: None
    panel._recalculate_geometry = lambda: None
    panel._info_parent = lambda: None
    panel.design_flow_edit = SimpleNamespace(text=lambda: "5.0", setText=lambda _text: None)

    module.WaterProfilePanel._import_from_batch(panel)

    assert panel.node_table.item(0, 7).text() == "0"
    assert panel.turn_radius_edit.text() == ""


def test_import_from_batch_persists_pressure_pipe_row_identity_for_pressure_like_rows():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    module.SHARED_DATA_AVAILABLE = True
    module.CALCULATOR_AVAILABLE = True
    module.QSignalBlocker = lambda *_args, **_kwargs: object()
    module.InfoBar = SimpleNamespace(
        success=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)
    module.auto_resize_table = lambda *_args, **_kwargs: None
    module.get_shared_data_manager = lambda: SimpleNamespace(
        get_batch_results=lambda: [
            _make_batch_result(
                section_type="定向钻",
                building_name="1#定向钻",
                raw_result={"is_pressure_pipe": True, "pipe_material": "钢管", "in_out_raw": "进"},
                D=1.4,
                n=0.0,
                slope_inv=0,
            )
        ]
    )
    module.StructureType = _FakeStructureType
    module.InOutType = _FakeInOutType

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

    panel._sync_batch_settings = lambda: None
    panel._clear_nodes = lambda: panel.node_table.setRowCount(0)
    panel._choose_roughness_value = lambda *_args, **_kwargs: None
    panel._update_siphon_roughness_overview = lambda *_args, **_kwargs: None
    panel._update_pressure_pipe_roughness_overview = lambda *_args, **_kwargs: None
    panel._on_design_flow_changed = lambda: None
    panel._apply_table1_source_row_lock_flags = lambda: None
    panel._refresh_pressure_pipe_controls = lambda: None
    panel._recalculate_geometry = lambda: None
    panel._calculate_recommended_turn_radius = lambda _nodes: 0.0
    panel._info_parent = lambda: None
    panel.design_flow_edit = SimpleNamespace(text=lambda: "5.0", setText=lambda _text: None)

    module.WaterProfilePanel._import_from_batch(panel)

    payload = panel.node_table.item(0, 0).data(module.Qt.UserRole)
    assert payload[module.PRESSURE_PIPE_ROW_ID_ROLE_KEY] == "flow1-row1"

    nodes = module.WaterProfilePanel._build_nodes_from_table(panel)

    assert len(nodes) == 1
    assert nodes[0].pressure_pipe_row_identity == "flow1-row1"


def test_auto_calc_turn_radius_falls_back_to_unified_default_value():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    module.CALCULATOR_AVAILABLE = True
    panel._info_parent = lambda: None
    module.InfoBar = SimpleNamespace(
        warning=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)
    panel._build_nodes_from_table = lambda: [
        _make_node(
            structure_type=_FakeStructTypeValue("明渠-矩形"),
            get_structure_type_str=lambda: "明渠-矩形",
            section_params={},
        )
    ]

    dialog_module_name = "app_渠系计算前端.water_profile.water_profile_dialogs"
    saved_dialog_module = sys.modules.get(dialog_module_name)
    dialog_module = types.ModuleType(dialog_module_name)

    class _FakeTurnRadiusCalcDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return 0

    dialog_module.TurnRadiusCalcDialog = _FakeTurnRadiusCalcDialog
    sys.modules[dialog_module_name] = dialog_module

    try:
        module.WaterProfilePanel._auto_calc_turn_radius(panel)
    finally:
        if saved_dialog_module is None:
            sys.modules.pop(dialog_module_name, None)
        else:
            sys.modules[dialog_module_name] = saved_dialog_module

    assert panel.turn_radius_edit.text() == "20.0"


def test_build_settings_keeps_blank_turn_radius_at_zero():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    module.CALCULATOR_AVAILABLE = True

    class _FakeProjectSettings:
        def __init__(self):
            self.turn_radius = None

    module.ProjectSettings = _FakeProjectSettings
    panel.channel_name_edit = _FakeLineEdit("测试渠道")
    panel.channel_level_combo = SimpleNamespace(currentText=lambda: "支管")
    panel.start_wl_edit = _FakeLineEdit("397.16")
    panel.design_flow_edit = _FakeLineEdit("5.0")
    panel.max_flow_edit = _FakeLineEdit("5.5")
    panel.start_station_edit = _FakeLineEdit("0+000.000")
    panel.roughness_edit = _FakeLineEdit("0.014")
    panel.turn_radius_edit = _FakeLineEdit("")
    panel.trans_inlet_combo = SimpleNamespace(currentText=lambda: "曲线形反弯扭曲面")
    panel.trans_inlet_zeta = _FakeLineEdit("0.10")
    panel.trans_outlet_combo = SimpleNamespace(currentText=lambda: "曲线形反弯扭曲面")
    panel.trans_outlet_zeta = _FakeLineEdit("0.20")
    panel.oc_trans_combo = SimpleNamespace(currentText=lambda: "曲线形反弯扭曲面")
    panel.oc_trans_zeta = _FakeLineEdit("0.10")
    panel.siphon_inlet_combo = SimpleNamespace(currentText=lambda: "反弯扭曲面")
    panel.siphon_inlet_zeta = _FakeLineEdit("0.10")
    panel.siphon_outlet_combo = SimpleNamespace(currentText=lambda: "反弯扭曲面")
    panel.siphon_outlet_zeta = _FakeLineEdit("0.20")
    panel._get_current_start_station_value = lambda: 0.0
    panel._parse_flow_values = lambda text: [float(text)]

    settings = module.WaterProfilePanel._build_settings(panel)

    assert settings.turn_radius == 0.0


def test_apply_pending_turn_radius_updates_only_real_source_rows_after_confirm():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    panel.turn_radius_edit = _FakeLineEdit("18")
    panel._recalculate_geometry = lambda: None
    panel._apply_table1_source_row_lock_flags = lambda: None
    panel._refresh_pressure_pipe_controls = lambda: None
    panel._info_parent = lambda: None
    panel._ask_destructive_confirm = lambda *args, **kwargs: True
    info_calls = []
    module.InfoBar = SimpleNamespace(
        warning=lambda *args, **kwargs: None,
        success=lambda *args, **kwargs: info_calls.append((args, kwargs)),
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)

    panel.node_table.setRowCount(3)
    for row, is_source in ((0, True), (1, False), (2, True)):
        first_item = _FakeItem(str(row + 1))
        first_item.setData(module.Qt.UserRole, {"_from_table1_source": is_source})
        panel.node_table.setItem(row, 0, first_item)
        panel.node_table.setItem(row, 2, _FakeItem("明渠-矩形" if is_source else "渐变段"))
        panel.node_table.setItem(row, 7, _FakeItem(""))

    changed = module.WaterProfilePanel._apply_pending_turn_radius_to_source_rows(panel)

    assert changed == 2
    assert panel.node_table.item(0, 7).text() == "18"
    assert panel.node_table.item(1, 7).text() == ""
    assert panel.node_table.item(2, 7).text() == "18"
    assert len(info_calls) == 1


def test_apply_pending_turn_radius_rejects_invalid_value():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    panel.turn_radius_edit = _FakeLineEdit("-5")
    panel._info_parent = lambda: None
    panel._ask_destructive_confirm = lambda *args, **kwargs: True
    warning_calls = []
    module.InfoBar = SimpleNamespace(
        warning=lambda *args, **kwargs: warning_calls.append((args, kwargs)),
        success=lambda *args, **kwargs: None,
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)

    panel.node_table.setRowCount(1)
    first_item = _FakeItem("1")
    first_item.setData(module.Qt.UserRole, {"_from_table1_source": True})
    panel.node_table.setItem(0, 0, first_item)
    panel.node_table.setItem(0, 2, _FakeItem("明渠-矩形"))
    panel.node_table.setItem(0, 7, _FakeItem(""))

    changed = module.WaterProfilePanel._apply_pending_turn_radius_to_source_rows(panel)

    assert changed == 0
    assert panel.node_table.item(0, 7).text() == ""
    assert len(warning_calls) == 1


def test_import_from_batch_roundtrips_use_increase_into_rebuilt_nodes():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    module.SHARED_DATA_AVAILABLE = True
    module.CALCULATOR_AVAILABLE = True
    module.QSignalBlocker = lambda *_args, **_kwargs: object()
    module.InfoBar = SimpleNamespace(
        success=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)
    module.auto_resize_table = lambda *_args, **_kwargs: None
    module.get_shared_data_manager = lambda: SimpleNamespace(
        get_batch_results=lambda: [_make_batch_result(use_increase=False)]
    )
    module.StructureType = _FakeStructureType
    module.InOutType = _FakeInOutType

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

    panel._sync_batch_settings = lambda: None
    panel._clear_nodes = lambda: panel.node_table.setRowCount(0)
    panel._choose_roughness_value = lambda *_args, **_kwargs: None
    panel._update_siphon_roughness_overview = lambda *_args, **_kwargs: None
    panel._update_pressure_pipe_roughness_overview = lambda *_args, **_kwargs: None
    panel._on_design_flow_changed = lambda: None
    panel._apply_table1_source_row_lock_flags = lambda: None
    panel._refresh_pressure_pipe_controls = lambda: None
    panel._recalculate_geometry = lambda: None
    panel._calculate_recommended_turn_radius = lambda _nodes: 0.0
    panel._info_parent = lambda: None
    panel.design_flow_edit = SimpleNamespace(text=lambda: "5.0", setText=lambda _text: None)

    module.WaterProfilePanel._import_from_batch(panel)

    nodes = module.WaterProfilePanel._build_nodes_from_table(panel)

    assert len(nodes) == 1
    assert nodes[0].use_increase is False
    assert nodes[0].section_params["use_increase"] is False


def test_import_from_batch_roundtrips_directional_drill_as_pressure_pipe_like():
    module = _load_panel_module()
    panel = _make_basic_panel(module)
    module.SHARED_DATA_AVAILABLE = True
    module.CALCULATOR_AVAILABLE = True
    module.QSignalBlocker = lambda *_args, **_kwargs: object()
    module.InfoBar = SimpleNamespace(
        success=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    module.InfoBarPosition = SimpleNamespace(TOP=1)
    module.auto_resize_table = lambda *_args, **_kwargs: None
    module.get_shared_data_manager = lambda: SimpleNamespace(
        get_batch_results=lambda: [
            _make_batch_result(
                section_type="定向钻",
                raw_result={"is_pressure_pipe": True, "pipe_material": "钢管", "in_out_raw": "进"},
                D=1.4,
                n=0.0,
                slope_inv=0,
            )
        ]
    )
    module.StructureType = _FakeStructureType
    module.InOutType = _FakeInOutType

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

    panel._sync_batch_settings = lambda: None
    panel._clear_nodes = lambda: panel.node_table.setRowCount(0)
    panel._choose_roughness_value = lambda *_args, **_kwargs: None
    panel._update_siphon_roughness_overview = lambda *_args, **_kwargs: None
    panel._update_pressure_pipe_roughness_overview = lambda *_args, **_kwargs: None
    panel._on_design_flow_changed = lambda: None
    panel._apply_table1_source_row_lock_flags = lambda: None
    panel._refresh_pressure_pipe_controls = lambda: None
    panel._recalculate_geometry = lambda: None
    panel._calculate_recommended_turn_radius = lambda _nodes: 0.0
    panel._info_parent = lambda: None
    panel.design_flow_edit = SimpleNamespace(text=lambda: "5.0", setText=lambda _text: None)

    module.WaterProfilePanel._import_from_batch(panel)
    nodes = module.WaterProfilePanel._build_nodes_from_table(panel)

    assert panel.node_table.item(0, 2).text() == "定向钻"
    assert len(nodes) == 1
    assert nodes[0].structure_type.value == "定向钻"
    assert nodes[0].is_pressure_pipe is True
