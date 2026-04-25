# -*- coding: utf-8 -*-
"""倒虹吸 donor 告警汇总与参数映射单元测试。"""

import importlib
import sys
import types
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from 推求水面线.utils.siphon_extractor import SiphonGroup


def _install_gui_stubs():
    patched_names = [
        "PySide6",
        "PySide6.QtWidgets",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "qfluentwidgets",
        "app_渠系计算前端.siphon.panel",
        "app_渠系计算前端.styles",
    ]
    original_modules = {name: sys.modules.get(name) for name in patched_names}

    qtwidgets = types.ModuleType("PySide6.QtWidgets")
    for name in (
        "QApplication", "QDialog", "QVBoxLayout", "QHBoxLayout", "QTabWidget", "QLabel",
        "QWidget", "QProgressBar", "QTableWidget", "QTableWidgetItem",
        "QHeaderView", "QAbstractItemView", "QCheckBox", "QSizePolicy", "QFrame",
    ):
        setattr(qtwidgets, name, type(name, (), {}))

    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.Qt = SimpleNamespace(
        Window=0,
        WindowMinimized=1,
        WindowActive=2,
        Key_Escape=27,
    )
    qtcore.QTimer = type("QTimer", (), {"singleShot": staticmethod(lambda *args, **kwargs: None)})

    qtgui = types.ModuleType("PySide6.QtGui")
    qtgui.QFont = type("QFont", (), {})

    sys.modules.setdefault("PySide6", types.ModuleType("PySide6"))
    sys.modules["PySide6.QtWidgets"] = qtwidgets
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui

    qfw = types.ModuleType("qfluentwidgets")
    qfw.PushButton = type("PushButton", (), {})
    qfw.PrimaryPushButton = type("PrimaryPushButton", (), {})
    qfw.InfoBar = type("InfoBar", (), {"warning": staticmethod(lambda *args, **kwargs: None)})
    qfw.InfoBarPosition = SimpleNamespace(TOP="TOP")
    sys.modules["qfluentwidgets"] = qfw

    panel_mod = types.ModuleType("app_渠系计算前端.siphon.panel")
    panel_mod.SiphonPanel = type("SiphonPanel", (), {})
    sys.modules["app_渠系计算前端.siphon.panel"] = panel_mod

    styles_mod = types.ModuleType("app_渠系计算前端.styles")
    styles_mod.P = ""
    styles_mod.S = ""
    styles_mod.T1 = ""
    styles_mod.T2 = ""
    styles_mod.BD = ""
    styles_mod.DIALOG_STYLE = ""
    styles_mod.auto_resize_table = lambda *args, **kwargs: None
    sys.modules["app_渠系计算前端.styles"] = styles_mod

    return original_modules


def _restore_modules(original_modules):
    """恢复被桩替换的模块，避免影响其他测试。"""
    for name, module in original_modules.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def _get_dialog_class():
    original_modules = _install_gui_stubs()
    sys.modules.pop("app_渠系计算前端.siphon.multi_siphon_dialog", None)
    try:
        mod = importlib.import_module("app_渠系计算前端.siphon.multi_siphon_dialog")
        return mod.MultiSiphonDialog
    finally:
        sys.modules.pop("app_渠系计算前端.siphon.multi_siphon_dialog", None)
        _restore_modules(original_modules)


def _get_dialog_module():
    original_modules = _install_gui_stubs()
    sys.modules.pop("app_渠系计算前端.siphon.multi_siphon_dialog", None)
    try:
        return importlib.import_module("app_渠系计算前端.siphon.multi_siphon_dialog")
    finally:
        sys.modules.pop("app_渠系计算前端.siphon.multi_siphon_dialog", None)
        _restore_modules(original_modules)


def _fake_dialog(turn_n: float = 0.0):
    return SimpleNamespace(_siphon_turn_radius_n=turn_n)


def test_group_increased_velocity_maps_to_panel_param_keys():
    MultiSiphonDialog = _get_dialog_class()
    group = SiphonGroup(
        name="虹吸A",
        design_flow=2.0,
        roughness=0.014,
        upstream_velocity_increased=1.234,
        downstream_velocity_increased=2.345,
    )

    params = MultiSiphonDialog._build_params_from_group(_fake_dialog(), group)

    assert params["v_channel_in_inc"] == 1.234
    assert params["v_pipe_out_inc"] == 2.345


def test_zero_increased_velocity_not_injected_into_params():
    MultiSiphonDialog = _get_dialog_class()
    group = SiphonGroup(
        name="虹吸B",
        design_flow=1.0,
        roughness=0.014,
        upstream_velocity_increased=0.0,
        downstream_velocity_increased=0.0,
    )

    params = MultiSiphonDialog._build_params_from_group(_fake_dialog(), group)

    assert "v_channel_in_inc" not in params
    assert "v_pipe_out_inc" not in params


def test_group_diameter_override_maps_to_panel_param_key():
    MultiSiphonDialog = _get_dialog_class()
    group = SiphonGroup(
        name="虹吸C",
        design_flow=1.0,
        roughness=0.014,
        diameter_override=1.6,
    )

    params = MultiSiphonDialog._build_params_from_group(_fake_dialog(), group)

    assert params["D_override"] == 1.6


def test_collect_velocity_source_warning_metadata_covers_new_categories():
    MultiSiphonDialog = _get_dialog_class()
    groups = [
        SiphonGroup(
            name="same-culvert",
            upstream_velocity_source="same_section_donor",
            downstream_velocity_source="same_section_donor",
            upstream_velocity_provenance={
                "scan_direction": "downstream",
                "donor_name": "culvert-donor",
                "section_family": "culvert",
            },
            downstream_velocity_provenance={
                "scan_direction": "downstream",
                "donor_name": "culvert-donor",
                "section_family": "culvert",
            },
        ),
        SiphonGroup(
            name="cross-culvert",
            upstream_velocity_source="cross_section_donor",
            downstream_velocity_source="cross_section_donor",
            upstream_velocity_provenance={
                "scan_direction": "downstream",
                "donor_name": "cross-donor",
                "donor_flow_section": "2",
                "redesigned": True,
                "redesign_mode": "keep_bottom_width_raise_height",
                "section_family": "culvert",
                "structure_type": "矩形暗涵",
                "dimensions": {"B": 1.6, "H_total": 2.4},
            },
            downstream_velocity_provenance={
                "scan_direction": "downstream",
                "donor_name": "cross-donor",
                "donor_flow_section": "2",
                "redesigned": True,
                "redesign_mode": "keep_bottom_width_raise_height",
                "section_family": "culvert",
                "structure_type": "矩形暗涵",
                "dimensions": {"B": 1.6, "H_total": 2.4},
            },
        ),
        SiphonGroup(
            name="missing-siphon",
            upstream_velocity_source="missing",
            downstream_velocity_source="missing",
        ),
    ]

    metadata = MultiSiphonDialog._collect_velocity_source_warning_metadata(groups)

    same_item = metadata["same_section"][0]
    cross_item = metadata["cross_section"][0]
    redesigned_item = metadata["redesigned"][0]
    missing_item = metadata["missing"][0]

    assert "same-culvert" in same_item
    assert "邻接断面流速已复用同段暗渠" in same_item
    assert "culvert-donor" in same_item

    assert "cross-culvert" in cross_item
    assert "邻接断面流速已借用跨段暗渠" in cross_item
    assert "第2流量段" in cross_item
    assert "cross-donor" in cross_item

    assert "cross-culvert" in redesigned_item
    assert "保留原底宽并自动增大高度" in redesigned_item
    assert "矩形暗渠" in redesigned_item
    assert "H=2.40 m" in redesigned_item

    assert "missing-siphon" in missing_item
    assert "仍未找到可用邻接断面（明渠或暗渠）" in missing_item


def test_build_velocity_source_warning_message_omits_empty_sections():
    MultiSiphonDialog = _get_dialog_class()
    message = MultiSiphonDialog._build_velocity_source_warning_message(
        {
            "same_section": ["same-culvert：上游/下游邻接断面流速已复用同段暗渠（下游侧断面“culvert-donor”）"],
            "cross_section": [],
            "redesigned": [],
            "missing": [],
        }
    )

    assert "流速来源提醒" not in message
    assert "邻接断面流速" in message
    assert "v₁加大/v₃加大" in message
    assert "同段复用：" in message
    assert "跨段借型并重算：" not in message
    assert "借用后重定邻接断面：" not in message
    assert "仍未找到可用邻接断面：" not in message


def test_show_velocity_source_warnings_once_merges_into_single_infobar():
    mod = _get_dialog_module()
    MultiSiphonDialog = mod.MultiSiphonDialog
    calls = []

    mod.InfoBar = type(
        "InfoBarSpy",
        (),
        {"warning": staticmethod(lambda *args, **kwargs: calls.append((args, kwargs)))},
    )

    dialog = SimpleNamespace(
        _velocity_source_warnings_shown=False,
        siphon_groups=[
            SiphonGroup(
                name="same-culvert",
                upstream_velocity_source="same_section_donor",
                downstream_velocity_source="same_section_donor",
                upstream_velocity_provenance={
                    "scan_direction": "downstream",
                    "donor_name": "culvert-donor",
                    "section_family": "culvert",
                },
                downstream_velocity_provenance={
                    "scan_direction": "downstream",
                    "donor_name": "culvert-donor",
                    "section_family": "culvert",
                },
            ),
            SiphonGroup(
                name="cross-culvert",
                upstream_velocity_source="cross_section_donor",
                downstream_velocity_source="cross_section_donor",
                upstream_velocity_provenance={
                    "scan_direction": "downstream",
                    "donor_name": "cross-donor",
                    "donor_flow_section": "2",
                    "redesigned": True,
                    "redesign_mode": "keep_bottom_width_raise_height",
                    "section_family": "culvert",
                    "structure_type": "矩形暗涵",
                    "dimensions": {"B": 1.6, "H_total": 2.4},
                },
                downstream_velocity_provenance={
                    "scan_direction": "downstream",
                    "donor_name": "cross-donor",
                    "donor_flow_section": "2",
                    "redesigned": True,
                    "redesign_mode": "keep_bottom_width_raise_height",
                    "section_family": "culvert",
                    "structure_type": "矩形暗涵",
                    "dimensions": {"B": 1.6, "H_total": 2.4},
                },
            ),
            SiphonGroup(
                name="missing-siphon",
                upstream_velocity_source="missing",
                downstream_velocity_source="missing",
            ),
        ],
    )

    MultiSiphonDialog._show_velocity_source_warnings_once(dialog)
    MultiSiphonDialog._show_velocity_source_warnings_once(dialog)

    assert len(calls) == 1
    warning_args, warning_kwargs = calls[0]
    assert warning_args[0] == "流速来源提醒"
    assert "同段复用：" in warning_args[1]
    assert "跨段借型并重算：" in warning_args[1]
    assert "借用后重定邻接断面：" in warning_args[1]
    assert "仍未找到可用邻接断面：" in warning_args[1]
    assert "请人工确认并补录" in warning_args[1]
    assert "暗渠" in warning_args[1]
    assert warning_kwargs["parent"] is dialog
