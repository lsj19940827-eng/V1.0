# -*- coding: utf-8 -*-
"""有压管道导出结果映射的单元测试。"""

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _load_module(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    extractor_mod = types.ModuleType("utils.pressure_pipe_extractor")

    class _PressurePipeDataExtractor:
        @staticmethod
        def extract_pipes(nodes, settings=None):
            _ = settings
            groups = []
            grouped = {}
            for idx, node in enumerate(nodes or []):
                if not getattr(node, "is_pressure_pipe", False):
                    continue
                key = (str(getattr(node, "name", "") or "").strip(), str(getattr(node, "flow_section", "") or "").strip())
                grouped.setdefault(key, []).append((idx, node))
            for (name, flow_section), items in grouped.items():
                row_indices = [idx for idx, _node in items]
                rows = [node for _idx, node in items]
                groups.append(
                    SimpleNamespace(
                        name=name,
                        rows=rows,
                        row_indices=row_indices,
                        outlet_row_index=row_indices[-1],
                    )
                )
            return groups

    extractor_mod.PressurePipeDataExtractor = _PressurePipeDataExtractor
    sys.modules["utils.pressure_pipe_extractor"] = extractor_mod

    helper_path = next(Path(".").glob("**/pressure_pipe_result_helpers.py")).resolve()
    helper_mod = _load_module("pressure_pipe_result_helpers_test_mod", helper_path)
    utils_pkg = sys.modules.setdefault("utils", types.ModuleType("utils"))
    setattr(utils_pkg, "pressure_pipe_result_helpers", helper_mod)
    setattr(utils_pkg, "pressure_pipe_extractor", extractor_mod)
    sys.modules["utils.pressure_pipe_result_helpers"] = helper_mod

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


def _install_runtime_pressure_pipe_extractor_stub():
    extractor_mod = types.ModuleType("utils.pressure_pipe_extractor")

    class _PressurePipeDataExtractor:
        @staticmethod
        def extract_pipes(nodes, settings=None):
            _ = settings
            groups = []
            grouped = {}
            for idx, node in enumerate(nodes or []):
                if not getattr(node, "is_pressure_pipe", False):
                    continue
                key = (str(getattr(node, "name", "") or "").strip(), str(getattr(node, "flow_section", "") or "").strip())
                grouped.setdefault(key, []).append((idx, node))
            for (name, _flow_section), items in grouped.items():
                row_indices = [idx for idx, _node in items]
                rows = [node for _idx, node in items]
                groups.append(
                    SimpleNamespace(
                        name=name,
                        rows=rows,
                        row_indices=row_indices,
                        outlet_row_index=row_indices[-1],
                    )
                )
            return groups

    extractor_mod.PressurePipeDataExtractor = _PressurePipeDataExtractor
    utils_pkg = sys.modules.setdefault("utils", types.ModuleType("utils"))
    setattr(utils_pkg, "pressure_pipe_extractor", extractor_mod)
    sys.modules["utils.pressure_pipe_extractor"] = extractor_mod


def _restore_runtime_pressure_pipe_extractor_stub(saved_utils, saved_extractor):
    """恢复运行期 extractor 桩，避免污染后续真实提取器测试。"""
    if saved_extractor is None:
        sys.modules.pop("utils.pressure_pipe_extractor", None)
    else:
        sys.modules["utils.pressure_pipe_extractor"] = saved_extractor

    if saved_utils is None:
        sys.modules.pop("utils", None)
    else:
        sys.modules["utils"] = saved_utils


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
        "utils",
        "utils.pressure_pipe_extractor",
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
        spec = importlib.util.spec_from_file_location("wp_panel_export_results_test", panel_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.WaterProfilePanel
    finally:
        for name, old_module in saved_modules.items():
            if old_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module


def test_get_pressure_pipe_export_results_prefers_calc_records_over_manager():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._pressure_pipe_calc_records = {
        "last_run_at": "2026-03-15 12:00:00",
        "records": [
            {
                "flow_section": "1",
                "name": "牛马道",
                "identity": "1::牛马道",
                "status": "success",
                "total_head_loss": 1.234,
            }
        ],
    }
    panel._pressure_pipe_manager = SimpleNamespace(
        to_dict=lambda: {
            "pipes": {
                "牛马道": {"name": "牛马道", "total_head_loss": 9.876},
            }
        }
    )

    result = WaterProfilePanel.get_pressure_pipe_export_results(
        panel,
        rows=[{"name": "牛马道", "flow_section": "1"}],
    )

    assert result["1::牛马道"]["total_head_loss"] == 1.234
    assert result["1::牛马道"]["source"] == "calc_records"


def test_get_pressure_pipe_export_results_uses_manager_when_calc_records_missing():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._pressure_pipe_calc_records = {"records": []}
    panel._pressure_pipe_manager = SimpleNamespace(
        to_dict=lambda: {
            "pipes": {
                "牛马道": {"name": "牛马道", "total_head_loss": 2.468},
            }
        }
    )

    result = WaterProfilePanel.get_pressure_pipe_export_results(
        panel,
        rows=[{"name": "牛马道", "flow_section": "1"}],
    )

    assert result["1::牛马道"]["total_head_loss"] == 2.468
    assert result["1::牛马道"]["source"] == "manager"


def test_get_pressure_pipe_export_results_matches_same_name_by_identity_without_cross_flow_mix():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._pressure_pipe_calc_records = {
        "records": [
            {
                "flow_section": "1",
                "name": "同名管道",
                "identity": "1::同名管道",
                "status": "success",
                "total_head_loss": 3.111,
            },
            {
                "flow_section": "2",
                "name": "同名管道",
                "identity": "2::同名管道",
                "status": "success",
                "total_head_loss": 4.222,
            },
        ]
    }
    panel._pressure_pipe_manager = SimpleNamespace(to_dict=lambda: {"pipes": {}})

    result = WaterProfilePanel.get_pressure_pipe_export_results(
        panel,
        rows=[
            {"name": "同名管道", "flow_section": "1"},
            {"name": "同名管道", "flow_section": "2"},
        ],
    )

    assert result["1::同名管道"]["total_head_loss"] == 3.111
    assert result["2::同名管道"]["total_head_loss"] == 4.222


def test_get_pressure_pipe_export_results_uses_table3_current_value_before_calc_records_and_manager():
    WaterProfilePanel = _load_panel_class()
    saved_utils = sys.modules.get("utils")
    saved_extractor = sys.modules.get("utils.pressure_pipe_extractor")
    _install_runtime_pressure_pipe_extractor_stub()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    try:
        panel._pressure_pipe_calc_records = {
            "records": [
                {
                    "flow_section": "3",
                    "name": "牛马道",
                    "identity": "3::牛马道",
                    "status": "success",
                    "total_head_loss": 0.111,
                }
            ]
        }
        panel._pressure_pipe_manager = SimpleNamespace(
            to_dict=lambda: {
                "pipes": {
                    "牛马道": {"name": "牛马道", "total_head_loss": 0.222},
                }
            }
        )
        panel._build_settings = lambda: object()
        panel._build_nodes_from_table = lambda: [
            SimpleNamespace(name="牛马道", flow_section="3", is_pressure_pipe=True, head_loss_siphon=0.5627),
        ]

        result = WaterProfilePanel.get_pressure_pipe_export_results(
            panel,
            rows=[{"name": "牛马道", "flow_section": "3"}],
        )
    finally:
        _restore_runtime_pressure_pipe_extractor_stub(saved_utils, saved_extractor)

    assert result["3::牛马道"]["total_head_loss"] == 0.5627
    assert result["3::牛马道"]["source"] == "table3"


def test_get_pressure_pipe_export_results_uses_table3_external_head_loss_when_head_loss_siphon_missing():
    WaterProfilePanel = _load_panel_class()
    saved_utils = sys.modules.get("utils")
    saved_extractor = sys.modules.get("utils.pressure_pipe_extractor")
    _install_runtime_pressure_pipe_extractor_stub()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    try:
        panel._pressure_pipe_calc_records = {"records": []}
        panel._pressure_pipe_manager = SimpleNamespace(to_dict=lambda: {"pipes": {}})
        panel._build_settings = lambda: object()
        panel._build_nodes_from_table = lambda: [
            SimpleNamespace(
                name="牛马道",
                flow_section="3",
                is_pressure_pipe=True,
                head_loss_siphon=0.0,
                external_head_loss=0.5627,
            ),
        ]

        result = WaterProfilePanel.get_pressure_pipe_export_results(
            panel,
            rows=[{"name": "牛马道", "flow_section": "3"}],
        )
    finally:
        _restore_runtime_pressure_pipe_extractor_stub(saved_utils, saved_extractor)

    assert result["3::牛马道"]["total_head_loss"] == 0.5627
    assert result["3::牛马道"]["source"] == "table3"


def test_get_pressure_pipe_export_results_prefers_row_identity_over_legacy_identity():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._pressure_pipe_calc_records = {
        "records": [
            {
                "flow_section": "1",
                "name": "同名管道",
                "identity": "flow1-row3",
                "status": "success",
                "total_head_loss": 2.222,
            }
        ]
    }
    panel._pressure_pipe_manager = SimpleNamespace(
        to_dict=lambda: {
            "pipes": {
                "1::同名管道": {
                    "name": "同名管道",
                    "flow_section": "1",
                    "total_head_loss": 9.999,
                }
            }
        }
    )

    result = WaterProfilePanel.get_pressure_pipe_export_results(
        panel,
        rows=[
            {
                "name": "同名管道",
                "flow_section": "1",
                "identity": "1::同名管道",
                "pressure_pipe_row_identity": "flow1-row3",
            }
        ],
    )

    assert result["flow1-row3"]["total_head_loss"] == 2.222
    assert result["flow1-row3"]["source"] == "calc_records"
