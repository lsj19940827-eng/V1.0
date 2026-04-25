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
    created_texts = []

    def __init__(self, text=""):
        super().__init__()
        self.text = text
        self.__class__.created_texts.append(text)

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
        "QLayout": _make_stub_class("QLayout"),
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
    qtcore.QTimer = type("QTimer", (), {"singleShot": staticmethod(lambda *args, **kwargs: None)})

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
    water_profile_pkg = types.ModuleType("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.water_profile")
    styles_mod = types.ModuleType("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.styles")
    styles_mod.auto_resize_table = lambda *args, **kwargs: None
    styles_mod.DIALOG_STYLE = ""
    styles_mod.fluent_info = lambda *args, **kwargs: None
    styles_mod.fluent_error = lambda *args, **kwargs: None
    styles_mod.fluent_question = lambda *args, **kwargs: False
    text_dialog_mod = types.ModuleType("app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.water_profile.text_export_settings_dialog")
    text_dialog_mod.create_text_export_settings_dialog = lambda *args, **kwargs: None

    utils_pkg = types.ModuleType("utils")
    helpers_mod = types.ModuleType("utils.pressure_pipe_result_helpers")
    helpers_mod.make_pressure_pipe_identity = lambda *args, **kwargs: ""

    sys.modules["推求水面线"] = types.ModuleType("推求水面线")
    sys.modules["推求水面线.utils"] = types.ModuleType("推求水面线.utils")
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
    sys.modules["app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.water_profile"] = water_profile_pkg
    sys.modules["app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.styles"] = styles_mod
    sys.modules["app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.water_profile.text_export_settings_dialog"] = text_dialog_mod
    sys.modules["utils"] = utils_pkg
    sys.modules["utils.pressure_pipe_result_helpers"] = helpers_mod
    sys.modules["models"] = models_pkg
    sys.modules["models.data_models"] = data_models_mod
    sys.modules["models.enums"] = enums_mod


def _load_cad_tools():
    patched_names = [
        "PySide6",
        "PySide6.QtWidgets",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "qfluentwidgets",
        "app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef",
        "app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.water_profile",
        "app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.styles",
        "app_\u6e20\u7cfb\u8ba1\u7b97\u524d\u7aef.water_profile.text_export_settings_dialog",
        "utils",
        "utils.pressure_pipe_result_helpers",
        "models",
        "models.data_models",
        "models.enums",
        "\u63a8\u6c42\u6c34\u9762\u7ebf",
        "\u63a8\u6c42\u6c34\u9762\u7ebf.utils",
    ]
    saved_modules = {name: sys.modules.get(name) for name in patched_names}
    try:
        _install_cad_tools_import_stubs()
        root = Path(__file__).resolve().parents[1]
        matches = list(root.glob("*/water_profile/cad_tools.py"))
        assert matches, "cad_tools.py not found"
        spec = importlib.util.spec_from_file_location("cad_tools_building_plan_test_mod", matches[0])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, old_module in saved_modules.items():
            if old_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old_module


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


def _reset_widget_captures():
    _TextEditStub.captured_html = []
    _LabelStub.created_texts = []


def _build_panel(nodes):
    panel = SimpleNamespace(
        calculated_nodes=nodes,
        _plan_text_settings={},
    )
    panel.window = lambda: None
    return panel


def test_building_plan_uses_table3_xy_for_command_position_angle_and_offset(monkeypatch):
    _reset_widget_captures()
    infos = []
    questions = []
    monkeypatch.setattr(cad_tools, "PlanTextSettingsDialog", _AcceptedPlanDialog)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *args, **kwargs: infos.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", lambda *args, **kwargs: questions.append(args) or True)

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
    assert infos == []
    assert questions == []


def test_building_plan_partial_missing_name_requires_confirmation_and_can_continue(monkeypatch):
    _reset_widget_captures()
    infos = []
    questions = []

    class _TrackingDialog:
        def __init__(self, *args, **kwargs):
            self.result = {"offset": 10.0, "text_height": 10.0}

        def exec(self):
            return cad_tools.QDialog.Accepted

    def _record_question(*args, **kwargs):
        questions.append((args, kwargs))
        return True

    monkeypatch.setattr(cad_tools, "PlanTextSettingsDialog", _TrackingDialog)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *args, **kwargs: infos.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", _record_question)

    panel = _build_panel(
        [
            _node(name="\u674e\u5bb6\u6c9f", structure_type="\u5012\u8679\u5438", in_out="\u8fdb", x=80.0, y=150.0),
            _node(name="\u674e\u5bb6\u6c9f", structure_type="\u5012\u8679\u5438", in_out="\u51fa", x=100.0, y=200.0),
            _node(name="", structure_type="\u6697\u6db5-\u77e9\u5f62", in_out="\u8fdb", x=10.0, y=20.0),
            _node(name="", structure_type="\u6697\u6db5-\u77e9\u5f62", in_out="\u51fa", x=20.0, y=30.0),
        ]
    )

    cad_tools.export_building_name_plan(panel)

    assert infos == []
    assert len(questions) == 1
    assert "\u540d\u79f0\u4e3a\u7a7a" in questions[0][0][2]
    assert "\u7b2c3~4\u884c\uff08\u6697\u6db5-\u77e9\u5f62\uff09" in questions[0][0][2]
    assert _TextEditStub.captured_html
    assert any("\u5df2\u8df3\u8fc7 1 \u4e2a" in text for text in _LabelStub.created_texts)
    lines = re.findall(r"-TEXT J MC [^<\r\n]+", _TextEditStub.captured_html[-1])
    assert len(lines) == 1
    assert "\u674e\u5bb6\u6c9f\u5012\u8679\u5438" in lines[0]


def test_building_plan_partial_missing_inout_can_cancel_before_parameter_dialog(monkeypatch):
    _reset_widget_captures()
    infos = []
    questions = []
    dialog_calls = []

    class _UnexpectedDialog:
        def __init__(self, *args, **kwargs):
            dialog_calls.append((args, kwargs))
            self.result = {"offset": 10.0, "text_height": 10.0}

        def exec(self):
            return cad_tools.QDialog.Accepted

    def _record_question(*args, **kwargs):
        questions.append((args, kwargs))
        return False

    monkeypatch.setattr(cad_tools, "PlanTextSettingsDialog", _UnexpectedDialog)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *args, **kwargs: infos.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", _record_question)

    panel = _build_panel(
        [
            _node(name="\u674e\u5bb6\u6c9f", structure_type="\u5012\u8679\u5438", in_out="\u8fdb", x=80.0, y=150.0),
            _node(name="\u674e\u5bb6\u6c9f", structure_type="\u5012\u8679\u5438", in_out="\u51fa", x=100.0, y=200.0),
            _node(name="\u5929\u84dd\u6865", structure_type="\u96a7\u6d1e", in_out="\u8fdb", x=10.0, y=20.0),
            _node(name="\u5929\u84dd\u6865", structure_type="\u96a7\u6d1e", in_out="", x=15.0, y=25.0),
        ]
    )

    cad_tools.export_building_name_plan(panel)

    assert infos == []
    assert len(questions) == 1
    assert "\u7f3a\u5c11\u8fdb/\u51fa\u6807\u8bb0" in questions[0][0][2]
    assert "\u7f3a\u5c11\u51fa\u53e3" in questions[0][0][2]
    assert "\u5929\u84dd\u6865" in questions[0][0][2]
    assert _TextEditStub.captured_html == []
    assert dialog_calls == []


def test_building_plan_partial_insufficient_coords_can_continue_and_preview_mentions_skipped_count(monkeypatch):
    _reset_widget_captures()
    infos = []
    questions = []

    class _TrackingDialog:
        def __init__(self, *args, **kwargs):
            self.result = {"offset": 10.0, "text_height": 10.0}

        def exec(self):
            return cad_tools.QDialog.Accepted

    def _record_question(*args, **kwargs):
        questions.append((args, kwargs))
        return True

    monkeypatch.setattr(cad_tools, "PlanTextSettingsDialog", _TrackingDialog)
    monkeypatch.setattr(cad_tools, "fluent_info", lambda *args, **kwargs: infos.append(args))
    monkeypatch.setattr(cad_tools, "fluent_question", _record_question)

    panel = _build_panel(
        [
            _node(name="\u674e\u5bb6\u6c9f", structure_type="\u5012\u8679\u5438", in_out="\u8fdb", x=80.0, y=150.0),
            _node(name="\u674e\u5bb6\u6c9f", structure_type="\u5012\u8679\u5438", in_out="\u51fa", x=100.0, y=200.0),
            _node(name="\u83b2\u6eaa", structure_type="\u6697\u6db5-\u77e9\u5f62", in_out="\u8fdb", x=0.0, y=0.0),
            _node(name="\u83b2\u6eaa", structure_type="\u6697\u6db5-\u77e9\u5f62", in_out="\u51fa", x=20.0, y=0.0),
        ]
    )

    cad_tools.export_building_name_plan(panel)

    assert infos == []
    assert len(questions) == 1
    assert "\u6709\u6548\u5750\u6807\u70b9\u4e0d\u8db3 2 \u4e2a" in questions[0][0][2]
    assert "\u4ec5 1 \u4e2a\u6709\u6548\u5750\u6807\u70b9" in questions[0][0][2]
    assert any("\u5df2\u8df3\u8fc7 1 \u4e2a" in text for text in _LabelStub.created_texts)
    lines = re.findall(r"-TEXT J MC [^<\r\n]+", _TextEditStub.captured_html[-1])
    assert len(lines) == 1
    assert "\u674e\u5bb6\u6c9f\u5012\u8679\u5438" in lines[0]


def test_building_plan_all_invalid_shows_grouped_info_details(monkeypatch):
    _reset_widget_captures()
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
            _node(name="", structure_type="\u6697\u6db5-\u77e9\u5f62", in_out="\u8fdb", x=10.0, y=20.0),
            _node(name="", structure_type="\u6697\u6db5-\u77e9\u5f62", in_out="\u51fa", x=20.0, y=30.0),
            _node(name="\u5929\u84dd\u6865", structure_type="\u96a7\u6d1e", in_out="\u8fdb", x=10.0, y=20.0),
            _node(name="\u5929\u84dd\u6865", structure_type="\u96a7\u6d1e", in_out="", x=15.0, y=25.0),
            _node(name="\u83b2\u6eaa", structure_type="\u6697\u6db5-\u77e9\u5f62", in_out="\u8fdb", x=0.0, y=0.0),
            _node(name="\u83b2\u6eaa", structure_type="\u6697\u6db5-\u77e9\u5f62", in_out="\u51fa", x=20.0, y=0.0),
        ]
    )

    cad_tools.export_building_name_plan(panel)

    assert infos, "all-invalid input should show a detailed info message"
    message = infos[-1][2]
    assert "\u540d\u79f0\u4e3a\u7a7a" in message
    assert "\u7f3a\u5c11\u8fdb/\u51fa\u6807\u8bb0" in message
    assert "\u6709\u6548\u5750\u6807\u70b9\u4e0d\u8db3 2 \u4e2a" in message
    assert "\u7b2c1~2\u884c\uff08\u6697\u6db5-\u77e9\u5f62\uff09" in message
    assert "\u5929\u84dd\u6865" in message
    assert "\u83b2\u6eaa" in message
    assert "\u4ec5 1 \u4e2a\u6709\u6548\u5750\u6807\u70b9" in message
    assert dialog_calls == []
    assert _TextEditStub.captured_html == []
