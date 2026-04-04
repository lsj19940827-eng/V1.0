# -*- coding: utf-8 -*-
"""有压管道纵断面导出映射的单元测试。"""

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

    helper_path = next(Path(".").glob("**/pressure_pipe_result_helpers.py")).resolve()
    helper_mod = _load_module("pressure_pipe_result_helpers_longitudinal_nodes_test_mod", helper_path)
    long_utils_path = next(Path(".").glob("**/pressure_pipe_longitudinal_utils.py")).resolve()
    long_utils_mod = _load_module("pressure_pipe_longitudinal_utils_test_mod", long_utils_path)
    utils_pkg = sys.modules.setdefault("utils", types.ModuleType("utils"))
    setattr(utils_pkg, "pressure_pipe_result_helpers", helper_mod)
    setattr(utils_pkg, "pressure_pipe_longitudinal_utils", long_utils_mod)
    sys.modules["utils.pressure_pipe_result_helpers"] = helper_mod
    sys.modules["utils.pressure_pipe_longitudinal_utils"] = long_utils_mod

    models_mod = types.ModuleType("models.data_models")
    models_mod.ChannelNode = type("ChannelNode", (), {})
    models_mod.ProjectSettings = type("ProjectSettings", (), {})
    models_mod.TransitionLengthRule = type("TransitionLengthRule", (), {})
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
    shared_mod.normalize_section_type_name = lambda value: str(value or "").strip()
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
        "utils",
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
        spec = importlib.util.spec_from_file_location("wp_panel_export_longitudinal_nodes_test", panel_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.WaterProfilePanel
    finally:
        for name, old_module in saved_modules.items():
            if old_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module


def test_get_pressure_pipe_longitudinal_nodes_for_export_prefers_identity_match():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._pressure_pipe_manager = SimpleNamespace(
        to_dict=lambda: {
            "pipes": {
                "牛马道": {
                    "name": "牛马道",
                    "longitudinal_nodes": [{"chainage": 9.0, "elevation": 98.0}],
                },
                "1::牛马道": {
                    "name": "牛马道",
                    "longitudinal_nodes": [{"chainage": 1.0, "elevation": 100.0}],
                },
            }
        }
    )

    result = WaterProfilePanel.get_pressure_pipe_longitudinal_nodes_for_export(
        panel,
        rows=[{"name": "牛马道", "flow_section": "1"}],
    )

    assert result == {
        "1::牛马道": [{"chainage": 1.0, "elevation": 100.0}],
    }


def test_get_pressure_pipe_longitudinal_nodes_for_export_uses_unique_name_fallback():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._pressure_pipe_manager = SimpleNamespace(
        to_dict=lambda: {
            "pipes": {
                "牛马道": {
                    "name": "牛马道",
                    "longitudinal_nodes": [{"chainage": 2.0, "elevation": 101.5}],
                }
            }
        }
    )

    result = WaterProfilePanel.get_pressure_pipe_longitudinal_nodes_for_export(
        panel,
        rows=[{"name": "牛马道", "flow_section": "3"}],
    )

    assert result == {
        "3::牛马道": [{"chainage": 2.0, "elevation": 101.5}],
    }


def test_get_pressure_pipe_longitudinal_nodes_for_export_avoids_cross_flow_mix_and_filters_empty():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._pressure_pipe_manager = SimpleNamespace(
        to_dict=lambda: {
            "pipes": {
                "同名管道": {
                    "name": "同名管道",
                    "longitudinal_nodes": [{"chainage": 5.0, "elevation": 88.0}],
                },
                "2::空纵断面": {
                    "name": "空纵断面",
                    "longitudinal_nodes": [],
                },
            }
        }
    )

    result = WaterProfilePanel.get_pressure_pipe_longitudinal_nodes_for_export(
        panel,
        rows=[
            {"name": "同名管道", "flow_section": "1"},
            {"name": "同名管道", "flow_section": "2"},
            {"name": "空纵断面", "flow_section": "2"},
        ],
    )

    assert result == {}


def test_get_pressure_pipe_longitudinal_nodes_for_export_reads_route_bucket_and_clips_segment():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    group = SimpleNamespace(
        storage_key="flow2-row6",
        route_key="flow2-route1",
        route_display_name="流量段2 整线1",
        display_name="流量段2 第6行有压管道",
        name="",
        identity="flow2-row6",
        flow_section="2",
        segment_start_mc=20.0,
        segment_end_mc=60.0,
    )
    panel._pressure_pipe_manager = SimpleNamespace(
        get_pipe_config=lambda key: SimpleNamespace(
            longitudinal_nodes=[
                {"chainage": 0.0, "elevation": 100.0, "turn_type": "NONE"},
                {"chainage": 40.0, "elevation": 96.0, "turn_type": "NONE"},
                {"chainage": 80.0, "elevation": 92.0, "turn_type": "NONE"},
            ]
        ) if key == "flow2-row6" else None
    )
    panel._build_settings = lambda: object()
    panel._build_nodes_from_table = lambda: ["stub-node"]
    panel._extract_pressure_pipe_dialog_groups = lambda nodes, settings=None: [group]

    result = WaterProfilePanel.get_pressure_pipe_longitudinal_nodes_for_export(
        panel,
        rows=[{"name": "", "flow_section": "2", "identity": "flow2-row6"}],
    )

    assert list(result) == ["flow2-row6"]
    assert result["flow2-row6"][0]["chainage"] == 20.0
    assert result["flow2-row6"][-1]["chainage"] == 60.0


def test_get_pressure_pipe_longitudinal_nodes_for_export_falls_back_to_route_bucket_when_storage_key_changes():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    group = SimpleNamespace(
        storage_key="flow2-row8",
        route_key="flow2-route1",
        route_display_name="流量段2 整线1",
        display_name="流量段2 第8行有压管道",
        name="",
        identity="flow2-row8",
        flow_section="2",
        segment_start_mc=20.0,
        segment_end_mc=60.0,
    )
    panel._pressure_pipe_manager = SimpleNamespace(
        get_pipe_config=lambda key: None,
        to_dict=lambda: {
            "pipes": {
                "flow2-row6": {
                    "name": "流量段2 第6行有压管道",
                    "route_key": "flow2-route1",
                    "route_display_name": "流量段2 整线1",
                    "longitudinal_nodes": [],
                }
            },
            "routes": {
                "flow2-route1": {
                    "display_name": "流量段2 整线1",
                    "longitudinal_nodes": [
                        {"chainage": 0.0, "elevation": 100.0, "turn_type": "NONE"},
                        {"chainage": 40.0, "elevation": 96.0, "turn_type": "NONE"},
                        {"chainage": 80.0, "elevation": 92.0, "turn_type": "NONE"},
                    ],
                }
            },
        },
    )
    panel._build_settings = lambda: object()
    panel._build_nodes_from_table = lambda: ["stub-node"]
    panel._extract_pressure_pipe_dialog_groups = lambda nodes, settings=None: [group]

    result = WaterProfilePanel.get_pressure_pipe_longitudinal_nodes_for_export(
        panel,
        rows=[{"name": "", "flow_section": "2", "identity": "flow2-row8"}],
    )

    assert list(result) == ["flow2-row8"]
    assert result["flow2-row8"][0]["chainage"] == 20.0
    assert result["flow2-row8"][-1]["chainage"] == 60.0


def test_get_pressure_pipe_longitudinal_nodes_for_export_keeps_route_nodes_for_xxpipe_anchor_group():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    route_nodes = [
        {"chainage": 0.0, "elevation": 100.0, "turn_type": "NONE"},
        {"chainage": 40.0, "elevation": 96.0, "turn_type": "NONE"},
        {"chainage": 80.0, "elevation": 92.0, "turn_type": "NONE"},
    ]
    group = SimpleNamespace(
        group_mode="unnamed_row_segment",
        storage_key="flow1-row1",
        route_key="flow1-route1",
        route_display_name="流量段1 整线1",
        display_name="流量段1 第1行有压管道",
        name="",
        identity="flow1-row1",
        flow_section="1",
        segment_start_mc=0.0,
        segment_end_mc=0.0,
        target_row_index=0,
        upstream_row_index=-1,
        route_start_row_index=0,
    )
    panel._pressure_pipe_manager = SimpleNamespace(
        get_pipe_config=lambda key: None,
        to_dict=lambda: {
            "routes": {
                "flow1-route1": {
                    "display_name": "流量段1 整线1",
                    "longitudinal_nodes": route_nodes,
                }
            }
        },
    )
    panel._build_settings = lambda: object()
    panel._build_nodes_from_table = lambda: ["stub-node"]
    panel._extract_pressure_pipe_dialog_groups = lambda nodes, settings=None: [group]

    result = WaterProfilePanel.get_pressure_pipe_longitudinal_nodes_for_export(
        panel,
        rows=[{"name": "", "flow_section": "1", "identity": "flow1-row1"}],
    )

    assert list(result) == ["flow1-row1"]
    assert result["flow1-row1"] == route_nodes


def test_get_pressure_pipe_longitudinal_nodes_for_export_reads_route_profile_segments():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    group = SimpleNamespace(
        storage_key="flow2-mixed-tunnel",
        route_key="flow2-route1",
        route_display_name="流量段2 整线1",
        display_name="穿山段隧洞",
        name="穿山段",
        identity="flow2-mixed-tunnel",
        flow_section="2",
        segment_start_mc=0.0,
        segment_end_mc=20.0,
    )
    panel._pressure_pipe_manager = SimpleNamespace(
        get_pipe_config=lambda key: None,
        to_dict=lambda: {
            "routes": {
                "flow2-route1": {
                    "display_name": "流量段2 整线1",
                    "profile_segments": [
                        {
                            "segment_identity": "flow2-mixed-tunnel",
                            "source_kind": "generated_tunnel",
                            "start_mc": 0.0,
                            "end_mc": 20.0,
                            "longitudinal_nodes": [
                                {"chainage": 0.0, "elevation": 420.0, "turn_type": "NONE"},
                                {"chainage": 20.0, "elevation": 419.8, "turn_type": "NONE"},
                            ],
                        },
                        {
                            "segment_identity": "flow2-row6",
                            "source_kind": "non_tunnel_dxf",
                            "start_mc": 20.0,
                            "end_mc": 80.0,
                            "longitudinal_nodes": [
                                {"chainage": 20.0, "elevation": 418.0, "turn_type": "NONE"},
                                {"chainage": 80.0, "elevation": 412.0, "turn_type": "NONE"},
                            ],
                        },
                    ],
                }
            }
        },
    )
    panel._build_settings = lambda: object()
    panel._build_nodes_from_table = lambda: ["stub-node"]
    panel._extract_pressure_pipe_dialog_groups = lambda nodes, settings=None: [group]

    result = WaterProfilePanel.get_pressure_pipe_longitudinal_nodes_for_export(
        panel,
        rows=[{"name": "穿山段", "flow_section": "2", "identity": "flow2-mixed-tunnel"}],
    )

    assert list(result) == ["flow2-mixed-tunnel"]
    assert result["flow2-mixed-tunnel"] == [
        {"chainage": 0.0, "elevation": 420.0, "turn_type": "NONE"},
        {"chainage": 20.0, "elevation": 419.8, "turn_type": "NONE"},
    ]
