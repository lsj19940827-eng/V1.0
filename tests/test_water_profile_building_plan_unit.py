# -*- coding: utf-8 -*-
"""Unit tests for building-name plan command generation."""

import importlib.util
import math
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


class _SignalStub:
    def connect(self, *_args, **_kwargs):
        return None


class _BaseWidgetStub:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


class _DialogStub(_BaseWidgetStub):
    Accepted = 1

    def exec(self):
        return 0


class _LayoutStub(_BaseWidgetStub):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = []

    def addWidget(self, widget):
        self.items.append(widget)

    def addLayout(self, layout):
        self.items.append(layout)

    def addStretch(self):
        self.items.append("stretch")


class _LabelStub(_BaseWidgetStub):
    def __init__(self, text=""):
        super().__init__()
        self.text = text

    def setText(self, text):
        self.text = text


class _TextEditStub(_BaseWidgetStub):
    captured_html = []

    def setHtml(self, html):
        self.captured_html.append(html)

    def toPlainText(self):
        return self.captured_html[-1] if self.captured_html else ""


class _ButtonStub(_BaseWidgetStub):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clicked = _SignalStub()


class _ClipboardStub:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


class _ApplicationStub:
    _clipboard = _ClipboardStub()

    @staticmethod
    def clipboard():
        return _ApplicationStub._clipboard


class _ProjectSettingsStub:
    @staticmethod
    def format_station(value, prefix=""):
        return f"{prefix}{value:.3f}"


class _FluentIconStub:
    def __getattr__(self, name):
        return name


def _make_stub_class(name):
    return type(name, (_BaseWidgetStub,), {})


def _install_cad_tools_import_stubs():
    qtwidgets = types.ModuleType("PySide6.QtWidgets")
    for name, cls in {
        "QDialog": _DialogStub,
        "QVBoxLayout": _LayoutStub,
        "QHBoxLayout": _LayoutStub,
        "QGridLayout": _LayoutStub,
        "QBoxLayout": _LayoutStub,
        "QLabel": _LabelStub,
        "QGroupBox": _make_stub_class("QGroupBox"),
        "QTextEdit": _TextEditStub,
        "QTableWidget": _make_stub_class("QTableWidget"),
        "QTableWidgetItem": _make_stub_class("QTableWidgetItem"),
        "QHeaderView": _make_stub_class("QHeaderView"),
        "QAbstractItemView": _make_stub_class("QAbstractItemView"),
        "QFileDialog": _make_stub_class("QFileDialog"),
        "QApplication": _ApplicationStub,
        "QScrollArea": _make_stub_class("QScrollArea"),
        "QWidget": _make_stub_class("QWidget"),
        "QComboBox": _make_stub_class("QComboBox"),
        "QFrame": _make_stub_class("QFrame"),
        "QSizePolicy": _make_stub_class("QSizePolicy"),
        "QMenu": _make_stub_class("QMenu"),
        "QListWidget": _make_stub_class("QListWidget"),
        "QListWidgetItem": _make_stub_class("QListWidgetItem"),
    }.items():
        setattr(qtwidgets, name, cls)

    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.Qt = SimpleNamespace(
        Key_Escape=27,
        Key_Return=13,
        UserRole=1000,
        MoveAction=0,
        AlignTop=0,
    )
    qtcore.Signal = lambda *args, **kwargs: _SignalStub()
    qtcore.QMimeData = _make_stub_class("QMimeData")
    qtcore.QSettings = _make_stub_class("QSettings")
    qtcore.QSize = _make_stub_class("QSize")
    qtcore.QEvent = _make_stub_class("QEvent")

    qtgui = types.ModuleType("PySide6.QtGui")
    for name in ("QFont", "QShortcut", "QKeySequence", "QDrag", "QColor"):
        setattr(qtgui, name, _make_stub_class(name))

    qfluent = types.ModuleType("qfluentwidgets")
    for name in (
        "PushButton",
        "PrimaryPushButton",
        "LineEdit",
        "SearchLineEdit",
        "PopupTeachingTip",
        "TeachingTipTailPosition",
        "InfoBarIcon",
        "ElevatedCardWidget",
        "HeaderCardWidget",
        "ListWidget",
        "SegmentedWidget",
        "ToolButton",
        "BodyLabel",
        "CaptionLabel",
        "InfoBar",
        "InfoBarPosition",
        "CheckBox",
    ):
        cls = _ButtonStub if name in ("PushButton", "PrimaryPushButton") else _make_stub_class(name)
        setattr(qfluent, name, cls)
    qfluent.FluentIcon = _FluentIconStub()

    app_pkg = types.ModuleType("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef")
    styles_mod = types.ModuleType("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.styles")
    styles_mod.auto_resize_table = lambda *args, **kwargs: None
    styles_mod.DIALOG_STYLE = ""
    styles_mod.fluent_info = lambda *args, **kwargs: None
    styles_mod.fluent_error = lambda *args, **kwargs: None
    styles_mod.fluent_question = lambda *args, **kwargs: False

    utils_pkg = types.ModuleType("utils")
    helpers_mod = types.ModuleType("utils.pressure_pipe_result_helpers")
    helpers_mod.make_pressure_pipe_identity = lambda *args, **kwargs: ""

    models_pkg = types.ModuleType("models")
    data_models_mod = types.ModuleType("models.data_models")
    data_models_mod.ProjectSettings = _ProjectSettingsStub

    enums_mod = types.ModuleType("models.enums")
    enums_mod.StructureType = _make_stub_class("StructureType")
    enums_mod.InOutType = _make_stub_class("InOutType")

    sys.modules["PySide6"] = types.ModuleType("PySide6")
    sys.modules["PySide6.QtWidgets"] = qtwidgets
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui
    sys.modules["qfluentwidgets"] = qfluent
    sys.modules["app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef"] = app_pkg
    sys.modules["app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.styles"] = styles_mod
    sys.modules["utils"] = utils_pkg
    sys.modules["utils.pressure_pipe_result_helpers"] = helpers_mod
    sys.modules["models"] = models_pkg
    sys.modules["models.data_models"] = data_models_mod
    sys.modules["models.enums"] = enums_mod


def _load_cad_tools():
    _install_cad_tools_import_stubs()
    root = Path(__file__).resolve().parents[1]
    matches = list(root.glob("*/water_profile/cad_tools.py"))
    assert matches, "cad_tools.py not found"
    spec = importlib.util.spec_from_file_location("cad_tools_building_plan_test_mod", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cad_tools = _load_cad_tools()


class _AcceptedPlanDialog:
    def __init__(self, *args, **kwargs):
        self.result = {"offset": 10.0, "text_height": 10.0}

    def exec(self):
        return cad_tools.QDialog.Accepted


def _node(*, name, structure_type, in_out, x, y):
    return SimpleNamespace(
        name=name,
        structure_type=SimpleNamespace(value=structure_type),
        in_out=in_out,
        x=float(x),
        y=float(y),
        is_transition=False,
        is_auto_inserted_channel=False,
    )


def _build_panel(nodes):
    panel = SimpleNamespace(
        calculated_nodes=nodes,
        _plan_text_settings={},
    )
    panel.window = lambda: None
    return panel


def test_building_plan_uses_table3_xy_for_command_position_angle_and_offset(monkeypatch):
    _TextEditStub.captured_html = []
    monkeypatch.setattr(cad_tools, "PlanTextSettingsDialog", _AcceptedPlanDialog)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *args, **kwargs: None)

    panel = _build_panel(
        [
            _node(name="\u674e\u5bb6\u6c9f", structure_type="\u5012\u8679\u5438", in_out="\u8fdb", x=80.0, y=150.0),
            _node(name="\u674e\u5bb6\u6c9f", structure_type="\u5012\u8679\u5438", in_out="", x=100.0, y=200.0),
            _node(name="\u674e\u5bb6\u6c9f", structure_type="\u5012\u8679\u5438", in_out="", x=130.0, y=240.0),
            _node(name="\u674e\u5bb6\u6c9f", structure_type="\u5012\u8679\u5438", in_out="\u51fa", x=160.0, y=280.0),
        ]
    )

    cad_tools.export_building_name_plan(panel)

    assert _TextEditStub.captured_html, "preview html should be captured"

    lines = re.findall(r"-TEXT J MC [^<\r\n]+", _TextEditStub.captured_html[-1])
    assert len(lines) == 1

    match = re.fullmatch(r"-TEXT J MC ([^,]+),([^ ]+) ([^ ]+) ([^ ]+) (.+)", lines[0])
    assert match, f"unexpected command format: {lines[0]}"

    text_x = float(match.group(1))
    text_y = float(match.group(2))
    text_height = float(match.group(3))
    angle_deg = float(match.group(4))
    building_name = match.group(5)

    expected_angle = math.degrees(math.atan2(40.0, 30.0))
    assert text_x == pytest.approx(107.0)
    assert text_y == pytest.approx(226.0)
    assert text_height == pytest.approx(10.0)
    assert angle_deg == pytest.approx(expected_angle)
    assert building_name == "\u674e\u5bb6\u6c9f\u5012\u8679\u5438"


def test_building_plan_skips_one_sided_building_and_shows_info(monkeypatch):
    infos = []
    dialog_calls = []

    class _UnexpectedDialog:
        def __init__(self, *args, **kwargs):
            dialog_calls.append((args, kwargs))
            self.result = {"offset": 10.0, "text_height": 10.0}

        def exec(self):
            return cad_tools.QDialog.Accepted

    monkeypatch.setattr(cad_tools, "PlanTextSettingsDialog", _UnexpectedDialog)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *args, **kwargs: infos.append(args))

    panel = _build_panel(
        [
            _node(name="\u5929\u84dd\u6865", structure_type="\u96a7\u6d1e", in_out="\u8fdb", x=10.0, y=20.0),
            _node(name="\u5929\u84dd\u6865", structure_type="\u96a7\u6d1e", in_out="", x=15.0, y=25.0),
        ]
    )

    cad_tools.export_building_name_plan(panel)

    assert infos, "one-sided structures should show an info message"
    assert "\u672a\u627e\u5230\u6709\u6548\u7684\u5efa\u7b51\u7269\u8fdb\u51fa\u53e3\u6570\u636e" in infos[-1][2]
    assert not dialog_calls, "settings dialog should not open when no valid building exists"
