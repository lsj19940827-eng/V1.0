# -*- coding: utf-8 -*-
"""WaterProfilePanel 空名称提示规则单测。"""

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
        def allows_empty_name(structure_type):
            value = getattr(structure_type, "value", structure_type)
            return str(value or "").strip() in {"明渠-矩形", "有压管道"}

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
        spec = importlib.util.spec_from_file_location("wp_panel_optional_name_notice_test", panel_path)
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
    def info(cls, title, content, **kwargs):
        _ = kwargs
        cls.records.append({"level": "info", "title": title, "content": content})


def _make_panel(module, channel_level):
    panel = module.WaterProfilePanel.__new__(module.WaterProfilePanel)
    panel.channel_level_combo = SimpleNamespace(currentText=lambda: channel_level)
    panel._build_settings = lambda: SimpleNamespace(channel_level=channel_level)
    panel._info_parent = lambda: None
    return panel


def _make_node(structure_type, name=""):
    return SimpleNamespace(
        structure_type=SimpleNamespace(value=structure_type),
        name=name,
        is_transition=False,
        is_auto_inserted_channel=False,
        get_structure_type_str=lambda: structure_type,
    )


def test_show_optional_blank_name_notice_skips_xxpipe_pressure_pipe_rows():
    module = _load_panel_module()
    module.StructureType = SimpleNamespace(
        allows_empty_name=lambda structure_type: str(getattr(structure_type, "value", structure_type) or "").strip()
        in {"明渠-矩形", "有压管道"}
    )
    module.InfoBar = _FakeInfoBar
    module.InfoBarPosition = SimpleNamespace(TOP="TOP")
    panel = _make_panel(module, "支管")
    node = _make_node("有压管道", name="")

    _FakeInfoBar.reset()
    panel._show_optional_blank_name_notice([node], action_name="计算")

    assert _FakeInfoBar.records == []


def test_show_optional_blank_name_notice_keeps_open_channel_notice():
    module = _load_panel_module()
    module.StructureType = SimpleNamespace(
        allows_empty_name=lambda structure_type: str(getattr(structure_type, "value", structure_type) or "").strip()
        in {"明渠-矩形", "有压管道"}
    )
    module.InfoBar = _FakeInfoBar
    module.InfoBarPosition = SimpleNamespace(TOP="TOP")
    panel = _make_panel(module, "支渠")
    node = _make_node("明渠-矩形", name="")

    _FakeInfoBar.reset()
    panel._show_optional_blank_name_notice([node], action_name="计算")

    assert len(_FakeInfoBar.records) == 1
    assert "部分建筑物名称为空" in _FakeInfoBar.records[0]["content"]
    assert "第1行（明渠-矩形）" in _FakeInfoBar.records[0]["content"]
