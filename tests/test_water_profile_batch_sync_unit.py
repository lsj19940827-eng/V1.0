"""WaterProfilePanel 与断面批量输入区联动的回归测试。"""

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


def _load_panel_class():
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
        spec = importlib.util.spec_from_file_location("wp_panel_mod_sync_test", panel_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.WaterProfilePanel
    finally:
        for name, old_module in saved_modules.items():
            if old_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module


class _FakeLineEdit:
    def __init__(self, text=""):
        self._text = text

    def text(self):
        return self._text

    def setText(self, text):
        self._text = str(text)


class _FakeComboBox:
    def __init__(self, items, current=""):
        self._items = list(items)
        self._current = current if current in self._items else (self._items[0] if self._items else "")

    def currentText(self):
        return self._current

    def findText(self, text):
        try:
            return self._items.index(text)
        except ValueError:
            return -1

    def setCurrentIndex(self, index):
        self._current = self._items[index]


def test_sync_batch_settings_updates_global_and_flow_fields():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    panel.channel_name_edit = _FakeLineEdit("默认名")
    panel.channel_level_combo = _FakeComboBox(["总干渠", "干渠", "支渠"], current="支渠")
    panel.start_wl_edit = _FakeLineEdit("100.0")
    panel.start_station_edit = _FakeLineEdit("0+000.000")
    panel._section_flow_segments_edit = _FakeLineEdit("5.0, 4.0, 3.0")
    panel.design_flow_edit = _FakeLineEdit("")
    panel.max_flow_edit = _FakeLineEdit("")

    callback_state = {"called": False}

    def _mark_design_change():
        callback_state["called"] = True
        panel.max_flow_edit.setText("auto-filled")

    panel._on_design_flow_changed = _mark_design_change

    bp = SimpleNamespace(
        channel_name_edit=_FakeLineEdit("龙塘"),
        channel_level_combo=_FakeComboBox(["总干渠", "干渠", "支渠"], current="干渠"),
        start_wl_edit=_FakeLineEdit("2392.271"),
        start_station_edit=_FakeLineEdit("0+000.000"),
        flow_segments_edit=_FakeLineEdit("4.6, 4.0, 3.2"),
    )
    panel._batch_backend = bp

    WaterProfilePanel._sync_batch_settings(panel)

    assert panel.channel_name_edit.text() == "龙塘"
    assert panel.channel_level_combo.currentText() == "干渠"
    assert panel.start_wl_edit.text() == "2392.271"
    assert panel.start_station_edit.text() == "0+000.000"
    assert panel._section_flow_segments_edit.text() == "4.6, 4.0, 3.2"
    assert panel.design_flow_edit.text() == "4.6, 4.0, 3.2"
    assert callback_state["called"] is True
    assert panel.max_flow_edit.text() == "auto-filled"


def test_load_section_sample_triggers_sync_after_loading():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    state = {"loaded": False, "synced": False, "marked": False, "switched": False}

    class _FakeBatchBackend:
        def _add_sample_data(self):
            state["loaded"] = True

    class _FakeTable:
        @staticmethod
        def rowCount():
            return 1

    panel._batch_backend = _FakeBatchBackend()
    panel._tab_section_input = object()
    panel._section_input_table = _FakeTable()
    panel._sync_batch_settings = lambda: state.__setitem__("synced", True)
    panel._switch_workspace_tab = lambda _tab: state.__setitem__("switched", True)
    panel._mark_section_results_stale = lambda _msg: state.__setitem__("marked", True)

    WaterProfilePanel._load_section_sample_1(panel)

    assert state["loaded"] is True
    assert state["synced"] is True
    assert state["switched"] is True
    assert state["marked"] is True


def test_load_section_sample_4_triggers_sync_after_loading():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    state = {"loaded": False, "synced": False, "marked": False, "switched": False}

    class _FakeBatchBackend:
        def _add_sample_data_4(self):
            state["loaded"] = True

    class _FakeTable:
        @staticmethod
        def rowCount():
            return 1

    panel._batch_backend = _FakeBatchBackend()
    panel._tab_section_input = object()
    panel._section_input_table = _FakeTable()
    panel._sync_batch_settings = lambda: state.__setitem__("synced", True)
    panel._switch_workspace_tab = lambda _tab: state.__setitem__("switched", True)
    panel._mark_section_results_stale = lambda _msg: state.__setitem__("marked", True)

    WaterProfilePanel._load_section_sample_4(panel)

    assert state["loaded"] is True
    assert state["synced"] is True
    assert state["switched"] is True
    assert state["marked"] is True
