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
    qtwidgets = types.ModuleType("PySide6.QtWidgets")
    for name in (
        "QDialog", "QVBoxLayout", "QHBoxLayout", "QTabWidget", "QLabel",
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


def _get_dialog_class():
    _install_gui_stubs()
    mod = importlib.import_module("app_渠系计算前端.siphon.multi_siphon_dialog")
    return mod.MultiSiphonDialog


def _get_dialog_module():
    _install_gui_stubs()
    return importlib.import_module("app_渠系计算前端.siphon.multi_siphon_dialog")


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


def test_collect_velocity_source_warning_metadata_covers_new_categories():
    MultiSiphonDialog = _get_dialog_class()
    groups = [
        SiphonGroup(
            name="催龙村",
            upstream_velocity_source="same_section_donor",
            downstream_velocity_source="same_section_donor",
            upstream_velocity_provenance={"scan_direction": "downstream", "donor_name": "南一支渠"},
            downstream_velocity_provenance={"scan_direction": "downstream", "donor_name": "南一支渠"},
        ),
        SiphonGroup(
            name="龙王沟",
            upstream_velocity_source="cross_section_donor",
            downstream_velocity_source="cross_section_donor",
            upstream_velocity_provenance={
                "scan_direction": "downstream",
                "donor_name": "北二支渠",
                "donor_flow_section": "2",
                "redesigned": True,
                "structure_type": "明渠-圆形",
                "dimensions": {"D": 1.5},
            },
            downstream_velocity_provenance={
                "scan_direction": "downstream",
                "donor_name": "北二支渠",
                "donor_flow_section": "2",
                "redesigned": True,
                "structure_type": "明渠-圆形",
                "dimensions": {"D": 1.5},
            },
        ),
        SiphonGroup(
            name="虹吸D",
            upstream_velocity_source="missing",
            downstream_velocity_source="missing",
        ),
    ]

    metadata = MultiSiphonDialog._collect_velocity_source_warning_metadata(groups)

    assert metadata["same_section"] == ["催龙村：上游/下游流速均借用下游侧断面“南一支渠”"]
    assert metadata["cross_section"] == [
        "龙王沟：上游/下游流速均借自第2流量段的下游侧断面“北二支渠”，并已按当前流量段的设计流量和加大流量重新计算"
    ]
    assert metadata["redesigned"] == ["龙王沟：上游/下游借用后已重新确定断面尺寸（圆形，D=1.50 m）"]
    assert metadata["missing"] == ["虹吸D：上游/下游仍未找到可借用断面"]


def test_build_velocity_source_warning_message_omits_empty_sections():
    MultiSiphonDialog = _get_dialog_class()
    message = MultiSiphonDialog._build_velocity_source_warning_message(
        {
            "same_section": ["催龙村：上游/下游流速均借用下游侧断面“南一支渠”"],
            "cross_section": [],
            "redesigned": [],
            "missing": [],
        }
    )

    assert "流速来源提醒" not in message
    assert "v₁/v₃（进口/出口渠道流速）" in message
    assert "同段借用：" in message
    assert "跨段借用并重算：" not in message
    assert "借用后重新确定断面尺寸：" not in message
    assert "仍未找到可借用断面：" not in message


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
                name="催龙村",
                upstream_velocity_source="same_section_donor",
                downstream_velocity_source="same_section_donor",
                upstream_velocity_provenance={"scan_direction": "downstream", "donor_name": "南一支渠"},
                downstream_velocity_provenance={"scan_direction": "downstream", "donor_name": "南一支渠"},
            ),
            SiphonGroup(
                name="龙王沟",
                upstream_velocity_source="cross_section_donor",
                downstream_velocity_source="cross_section_donor",
                upstream_velocity_provenance={
                    "scan_direction": "downstream",
                    "donor_name": "北二支渠",
                    "donor_flow_section": "2",
                    "redesigned": True,
                },
                downstream_velocity_provenance={
                    "scan_direction": "downstream",
                    "donor_name": "北二支渠",
                    "donor_flow_section": "2",
                    "redesigned": True,
                },
            ),
            SiphonGroup(
                name="虹吸D",
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
    assert "同段借用：" in warning_args[1]
    assert "跨段借用并重算：" in warning_args[1]
    assert "借用后重新确定断面尺寸：" in warning_args[1]
    assert "仍未找到可借用断面：" in warning_args[1]
    assert "请人工确认并补录。" in warning_args[1]
    assert warning_kwargs["parent"] is dialog
