# -*- coding: utf-8 -*-
"""连续承压链结果回写的单元测试。"""

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
    info_bar_cls = type(
        "InfoBar",
        (),
        {
            "success": staticmethod(lambda *args, **kwargs: None),
            "warning": staticmethod(lambda *args, **kwargs: None),
            "error": staticmethod(lambda *args, **kwargs: None),
            "info": staticmethod(lambda *args, **kwargs: None),
        },
    )
    for name in (
        "PushButton", "PrimaryPushButton", "LineEdit", "ComboBox",
        "DropDownPushButton", "RoundMenu",
        "Action", "MessageBox",
    ):
        setattr(qfw, name, type(name, (), {}))
    qfw.InfoBar = info_bar_cls
    qfw.InfoBarPosition = SimpleNamespace(TOP="TOP")
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
    helper_mod = _load_module("pressure_pipe_result_helpers_chain_apply_test_mod", helper_path)
    utils_pkg = sys.modules.setdefault("utils", types.ModuleType("utils"))
    setattr(utils_pkg, "pressure_pipe_result_helpers", helper_mod)
    sys.modules["utils.pressure_pipe_result_helpers"] = helper_mod

    extractor_mod = types.ModuleType("utils.pressure_pipe_extractor")
    extractor_mod.PressurePipeDataExtractor = type("PressurePipeDataExtractor", (), {})
    setattr(utils_pkg, "pressure_pipe_extractor", extractor_mod)
    sys.modules["utils.pressure_pipe_extractor"] = extractor_mod

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

    enums_mod = types.ModuleType("models.enums")
    enums_mod.StructureType = _StubStructureType
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
        spec = importlib.util.spec_from_file_location("wp_panel_chain_apply_test", panel_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.WaterProfilePanel
    finally:
        for name, old_module in saved_modules.items():
            if old_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module


def test_apply_pressure_pipe_member_result_skips_anchor_row():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._pressure_pipe_calc_done = {}

    node = SimpleNamespace(
        section_params={},
        pressure_pipe_window_override={},
        head_loss_friction=0.0,
        head_loss_bend=0.0,
        head_loss_local=0.0,
        head_loss_siphon=0.0,
        external_head_loss=None,
        head_loss_total=0.0,
    )
    group = SimpleNamespace(
        group_mode="chain_row_member",
        target_row_index=0,
        upstream_row_index=-1,
    )
    record = {
        "identity": "flow2-row1",
        "display_name": "流量段2 第1行有压管道",
        "status": "success",
        "writeback_enabled": False,
        "note": "链起点锚点，本行不写回",
    }

    changed = WaterProfilePanel._apply_pressure_pipe_member_result(panel, node, group, record)

    assert changed is False
    assert node.section_params == {}
    assert panel._pressure_pipe_calc_done == {}


def test_build_pressure_pipe_chain_anchor_record_preserves_zero_indices_and_uses_blank_losses():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._get_pressure_chain_member_identity = WaterProfilePanel._get_pressure_chain_member_identity

    member = SimpleNamespace(
        member_type="single_row",
        identity="flow1-row1",
        storage_key="flow1-row1",
        display_name="流量段1 第1行有压管道",
        flow_section="1",
        structure_type="有压管道",
        target_row_index=0,
        upstream_row_index=0,
    )

    record = WaterProfilePanel._build_pressure_chain_anchor_record(panel, member)

    assert record["target_row_index"] == 0
    assert record["upstream_row_index"] == 0
    assert record["total_head_loss"] is None
    assert record["friction_loss"] is None
    assert record["total_bend_loss"] is None
    assert record["inlet_transition_loss"] is None
    assert record["outlet_transition_loss"] is None
    assert record["pipe_velocity"] is None
    assert record["total_length"] is None


def test_apply_pressure_pipe_member_result_writes_chain_row_override():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._pressure_pipe_calc_done = {}

    node = SimpleNamespace(
        section_params={},
        pressure_pipe_window_override={},
        head_loss_friction=0.0,
        head_loss_bend=0.0,
        head_loss_local=0.0,
        head_loss_siphon=0.0,
        external_head_loss=None,
        head_loss_total=0.0,
    )
    group = SimpleNamespace(
        group_mode="chain_tunnel_member",
        target_row_index=1,
        upstream_row_index=0,
    )
    record = {
        "identity": "flow2-row4",
        "display_name": "半兽人",
        "storage_key": "flow2-row4",
        "status": "success",
        "writeback_enabled": True,
        "group_mode": "chain_tunnel_member",
        "target_row_index": 1,
        "upstream_row_index": 0,
        "data_mode": "链成员模式",
        "Q": 1.8,
        "D": 1.5,
        "total_length": 108.4,
        "pipe_velocity": 1.02,
        "friction_loss": 0.2101,
        "total_bend_loss": 0.0123,
        "local_loss": 0.0088,
        "inlet_transition_loss": 0.0,
        "outlet_transition_loss": 0.0088,
        "total_head_loss": 0.2312,
        "friction_details": {"method": "slope", "hf": 0.2101},
        "bend_details": {"method": "manning_bend", "hw": 0.0123},
        "local_details": {"method": "local", "hj": 0.0088},
    }

    changed = WaterProfilePanel._apply_pressure_pipe_member_result(panel, node, group, record)

    assert changed is True
    assert node.section_params["pressure_pipe_window_override"]["identity"] == "flow2-row4"
    assert node.section_params["pressure_pipe_window_override"]["group_mode"] == "chain_tunnel_member"
    assert abs(node.head_loss_friction - 0.2101) < 1e-9
    assert abs(node.head_loss_bend - 0.0123) < 1e-9
    assert abs(node.head_loss_local - 0.0088) < 1e-9
    assert abs(node.head_loss_total - 0.2312) < 1e-9
    assert node.external_head_loss is None
    assert panel._pressure_pipe_calc_done["flow2-row4"] is True


def test_apply_pressure_pipe_results_falls_back_to_batch_chain_records():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._pressure_pipe_calc_done = {}

    upstream_node = SimpleNamespace(
        section_params={},
        pressure_pipe_window_override={},
        head_loss_friction=0.0,
        head_loss_bend=0.0,
        head_loss_local=0.0,
        head_loss_siphon=0.0,
        external_head_loss=None,
        head_loss_total=0.0,
    )
    target_node = SimpleNamespace(
        section_params={},
        pressure_pipe_window_override={},
        head_loss_friction=0.0,
        head_loss_bend=0.0,
        head_loss_local=0.0,
        head_loss_siphon=0.0,
        external_head_loss=None,
        head_loss_total=0.0,
    )

    chain_member = SimpleNamespace(
        member_type="single_row",
        identity="flow2-row4",
        storage_key="flow2-row4",
        display_name="半兽人",
        structure_type="隧洞",
        target_row_index=1,
        upstream_row_index=0,
        should_generate_row_loss=True,
    )
    chain = SimpleNamespace(
        flow_section="2",
        start_row_index=0,
        end_row_index=1,
        members=[chain_member],
    )

    panel._build_settings = lambda: SimpleNamespace(get_station_prefix=lambda: "")
    panel._build_nodes_from_table = lambda: [upstream_node, target_node]
    panel._extract_pressure_pipe_dialog_groups = lambda nodes, settings=None: []
    panel._extract_pressure_pipe_dialog_chains = lambda nodes, settings=None: [chain]
    panel._build_pressure_pipe_chain_descriptors = (
        WaterProfilePanel._build_pressure_pipe_chain_descriptors.__get__(panel, WaterProfilePanel)
    )
    panel._get_pressure_chain_member_identity = WaterProfilePanel._get_pressure_chain_member_identity
    panel._apply_pressure_pipe_member_result = (
        WaterProfilePanel._apply_pressure_pipe_member_result.__get__(panel, WaterProfilePanel)
    )
    panel._normalize_pressure_pipe_window_override = lambda payload: dict(payload or {})
    panel._set_pressure_pipe_window_override = (
        lambda node, override: (
            setattr(node, "pressure_pipe_window_override", dict(override or {})),
            node.section_params.__setitem__("pressure_pipe_window_override", dict(override or {})),
        )
    )
    panel._build_pressure_pipe_window_override_payload = (
        WaterProfilePanel._build_pressure_pipe_window_override_payload.__get__(panel, WaterProfilePanel)
    )
    panel._append_loss_undo_snapshot = lambda snapshot: None
    panel._snapshot_editable_cols = lambda: {}
    panel._update_table_from_nodes_full = lambda nodes, prefix: None
    panel._recalculate_silent = lambda: None
    panel._info_parent = lambda: None
    panel._ensure_pressure_pipe_row_identity = lambda node, idx: None
    panel.node_table = SimpleNamespace()
    panel.nodes = []

    batch_data = {
        "last_run_at": "2026-03-31 22:40:16",
        "records": [
            {
                "identity": "flow2-row4",
                "display_name": "半兽人",
                "storage_key": "flow2-row4",
                "status": "success",
                "writeback_enabled": True,
                "group_mode": "chain_tunnel_member",
                "target_row_index": 1,
                "upstream_row_index": 0,
                "data_mode": "链成员模式",
                "Q": 1.55,
                "D": 1.4,
                "total_length": 108.4,
                "pipe_velocity": 1.02,
                "friction_loss": 0.2101,
                "total_bend_loss": 0.0123,
                "local_loss": 0.0088,
                "inlet_transition_loss": 0.0,
                "outlet_transition_loss": 0.0088,
                "total_head_loss": 0.2312,
                "friction_details": {"hf": 0.2101},
                "bend_details": {"hw": 0.0123},
                "local_details": {"hj": 0.0088},
            }
        ],
        "summary": {"total": 1, "success": 1, "failed": 0},
    }

    WaterProfilePanel._apply_pressure_pipe_results(panel, {}, batch_data)

    assert target_node.section_params["pressure_pipe_window_override"]["identity"] == "flow2-row4"
    assert target_node.section_params["pressure_pipe_window_override"]["group_mode"] == "chain_tunnel_member"
    assert abs(target_node.head_loss_total - 0.2312) < 1e-9
    assert panel._pressure_pipe_calc_done["flow2-row4"] is True


def test_apply_pressure_pipe_results_applies_chain_member_outside_pipe_groups():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)
    panel._pressure_pipe_calc_done = {}
    panel.node_table = SimpleNamespace()

    node0 = SimpleNamespace(
        section_params={},
        pressure_pipe_window_override={},
        head_loss_friction=0.0,
        head_loss_bend=0.0,
        head_loss_local=0.0,
        head_loss_siphon=0.0,
        external_head_loss=None,
        head_loss_total=0.0,
    )
    node1 = SimpleNamespace(
        section_params={},
        pressure_pipe_window_override={},
        head_loss_friction=0.0,
        head_loss_bend=0.0,
        head_loss_local=0.0,
        head_loss_siphon=0.0,
        external_head_loss=None,
        head_loss_total=0.0,
    )
    named_group = SimpleNamespace(
        outlet_row_index=0,
        group_mode="named_group",
    )
    tunnel_member = SimpleNamespace(
        identity="flow2-row4",
        target_row_index=1,
        group_mode="chain_tunnel_member",
    )

    panel._build_settings = lambda: SimpleNamespace(get_station_prefix=lambda: "")
    panel._build_nodes_from_table = lambda: [node0, node1]
    panel._extract_pressure_pipe_dialog_groups = lambda nodes, settings=None: [named_group]
    panel._extract_pressure_pipe_dialog_chains = lambda nodes, settings=None: [SimpleNamespace(members=[tunnel_member])]
    panel._build_pressure_pipe_chain_descriptors = lambda chains: [{"members": [tunnel_member]}]
    panel._build_pressure_pipe_group_identity = lambda group: "named-1"
    panel._is_pressure_pipe_row_segment_group = lambda group: False
    panel._get_pressure_chain_member_identity = lambda member: getattr(member, "identity", "")
    panel._ensure_pressure_pipe_row_identity = lambda node, idx: setattr(node, "_ensured_row_index", idx)
    panel._append_loss_undo_snapshot = lambda snapshot: None
    panel._snapshot_editable_cols = lambda: {}
    panel._update_table_from_nodes_full = lambda nodes, prefix: None
    panel._recalculate_silent = lambda: setattr(panel, "_silent_recalc_called", True)
    panel._info_parent = lambda: None

    applied_identities = []

    def _apply_member_result(node, group, record):
        applied_identities.append(record["identity"])
        if record["identity"] != "flow2-row4":
            return False
        node.section_params["pressure_pipe_window_override"] = {"identity": record["identity"]}
        panel._pressure_pipe_calc_done[record["identity"]] = True
        return True

    panel._apply_pressure_pipe_member_result = _apply_member_result

    results_by_identity = {
        "flow2-row4": {
            "identity": "flow2-row4",
            "status": "success",
            "writeback_enabled": True,
            "group_mode": "chain_tunnel_member",
            "target_row_index": 1,
            "total_head_loss": 0.2312,
        }
    }
    batch_data = {"summary": {"total": 1, "success": 1, "failed": 0}}

    WaterProfilePanel._apply_pressure_pipe_results(panel, results_by_identity, batch_data)

    assert applied_identities == ["flow2-row4"]
    assert panel._pressure_pipe_calc_done["flow2-row4"] is True
    assert node1.section_params["pressure_pipe_window_override"]["identity"] == "flow2-row4"
    assert getattr(node1, "_ensured_row_index", None) == 1
    assert getattr(panel, "_silent_recalc_called", False) is True


def test_build_pressure_pipe_chain_descriptors_uses_global_chain_name_for_cross_section_chain():
    WaterProfilePanel = _load_panel_class()
    panel = WaterProfilePanel.__new__(WaterProfilePanel)

    chain = SimpleNamespace(
        flow_section="2",
        start_row_index=0,
        end_row_index=3,
        members=[
            SimpleNamespace(flow_section="2"),
            SimpleNamespace(flow_section="3"),
            SimpleNamespace(flow_section="3"),
        ],
    )

    descriptors = WaterProfilePanel._build_pressure_pipe_chain_descriptors(panel, [chain])

    assert len(descriptors) == 1
    descriptor = descriptors[0]
    assert descriptor["display_name"] == "连续承压链1"
    assert descriptor["flow_section"] == "2、3"
    assert descriptor["chain_id"].startswith("chain1-")
